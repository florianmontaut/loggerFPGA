# controller/graph_controller.py
"""
Graphique temps réel.

Deux panneaux à axe des temps commun (comme les panneaux du GLviewer) :
    - voies analogiques (valeurs physiques), avec la ligne du seuil en trigger sur seuil ;
    - voies logiques, une voie par niveau (k + 0,8 x bit, comme `stairs(log)` de logger.m),
      affiché seulement si la voie logique est enregistrée.

Débit : le FPGA peut produire bien plus de trames que l'écran n'en affiche. Les trames
reçues ne font que remplacer la « dernière trame » ; un QTimer redessine au plus
REFRESH_HZ fois par seconde. Les courbes sont créées une fois par configuration et mises à
jour par setData (sous-échantillonnage « peak » et clipToView de pyqtgraph).
"""
from __future__ import annotations

import time

import numpy as np
import pyqtgraph as pg
from PyQt6 import QtCore

from model.config import LoggerConfig, TriggerType
from model.protocol import Frame
from ressources import pens, zoom


class LiveGraphController(QtCore.QObject):

    cursor_values = QtCore.pyqtSignal(dict)    # clé -> valeur sous le curseur
    fps_changed = QtCore.pyqtSignal(float)
    redrawn = QtCore.pyqtSignal()              # nouvelle trame dessinée (mesures à refaire)
    # panneau utile ou non pour la configuration : "analog" / "logic" / "math", bool
    availability_changed = QtCore.pyqtSignal(str, bool)
    math_errors = QtCore.pyqtSignal(dict)      # voies calculées en erreur sur la trame

    REFRESH_HZ = 30
    LOGIC_HEIGHT = 0.8

    AXIS_WIDTH = 72        # axes de gauche de même largeur : échelles des temps alignées

    def __init__(self, analog_widget: pg.GraphicsLayoutWidget,
                 logic_widget: pg.GraphicsLayoutWidget,
                 math_widget: pg.GraphicsLayoutWidget | None = None):
        super().__init__()
        # un widget par panneau : chacun peut être déporté dans sa propre fenêtre
        self.analog_widget = analog_widget
        self.logic_widget = logic_widget
        self.math_widget = math_widget or pg.GraphicsLayoutWidget()
        self.math_engine = None          # model.math_channels.MathEngine (voies calculées)
        self.cfg: LoggerConfig | None = None
        self.frame: Frame | None = None
        self._dirty = False
        self.paused = False
        self.auto_range = True
        self.curves: dict[tuple, pg.PlotDataItem] = {}
        self.hidden: set[tuple] = set()
        self._drawn = 0
        self._fps_t0 = time.perf_counter()

        self.analog_plot = pg.PlotItem()
        self.logic_plot = pg.PlotItem()
        self.math_plot = pg.PlotItem()          # voies calculées, axe des temps commun
        for plot in (self.analog_plot, self.logic_plot, self.math_plot):
            plot.showGrid(x=True, y=True, alpha=0.3)
            plot.setDownsampling(auto=True, mode="peak")
            plot.setClipToView(True)
            plot.setLabel("bottom", "Temps", units="s")
            plot.getAxis("left").setWidth(self.AXIS_WIDTH)
        self.analog_widget.addItem(self.analog_plot, row=0, col=0)
        self.logic_widget.addItem(self.logic_plot, row=0, col=0)
        self.math_widget.addItem(self.math_plot, row=0, col=0)
        self.logic_plot.setXLink(self.analog_plot)
        self.math_plot.setXLink(self.analog_plot)
        self.math_plot.showGrid(x=True, y=True, alpha=0.3)
        self.math_legend = self.math_plot.addLegend(offset=(-10, 10))
        self.logic_plot.setMouseEnabled(x=True, y=False)
        self.legend = self.analog_plot.addLegend(offset=(-10, 10))

        self.threshold_line = pg.InfiniteLine(angle=0, movable=False,
                                              pen=pg.mkPen("r", style=QtCore.Qt.PenStyle.DashLine),
                                              label="seuil", labelOpts={"position": 0.02})
        self.cursor = pg.InfiniteLine(angle=90, movable=True,
                                      pen=pg.mkPen("#888", width=1))
        self.cursor.sigPositionChanged.connect(self._emit_cursor_values)
        self.analog_plot.addItem(self.cursor, ignoreBounds=True)
        self.cursor.hide()
        self.analog_widget.scene().sigMouseClicked.connect(self._on_click)

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._redraw)
        self.timer.start(int(1000 / self.REFRESH_HZ))

    # ------------------------------------------------------------------ configuration
    def configure(self, cfg: LoggerConfig):
        """(Re)crée les courbes pour la configuration `cfg`."""
        self.cfg = cfg
        self.frame = None
        for key, curve in self.curves.items():
            self._plot_of(key).removeItem(curve)
        self.curves.clear()
        self.legend.clear()
        self.math_legend.clear()
        self.availability_changed.emit("analog", bool(cfg.analog_signals))
        self.availability_changed.emit("logic", cfg.has_logic)
        self.logic_plot.setXLink(self.analog_plot if cfg.analog_signals else None)

        if cfg.analog_signals:
            for sig in cfg.analog_signals:
                curve = self.analog_plot.plot(pen=pens.pen(pens.analog_color(sig)),
                                              name=cfg.analog_name(sig))
                curve.setVisible(("A", sig) not in self.hidden)
                self.curves[("A", sig)] = curve
            unit = {cfg.unit(s) for s in cfg.analog_signals}
            self.analog_plot.setLabel("left", "Mesures", units=unit.pop() if len(unit) == 1 else None)
            max_gain = max(abs(cfg.gain(s)) for s in cfg.analog_signals) or 1.0
            # échelle fixe de logger.m : multiple de 100 supérieur au gain maximal
            self._fixed_y = (np.floor(max_gain / 100) + 1) * 100 if max_gain >= 100 else max_gain
        if cfg.has_logic:
            for bit in range(16):
                curve = self.logic_plot.plot(pen=pens.pen(pens.logic_color(bit)))
                curve.setVisible(("L", bit) not in self.hidden)
                self.curves[("L", bit)] = curve
            self.logic_plot.getAxis("left").setTicks(
                [[(b + self.LOGIC_HEIGHT / 2, cfg.logic_name(b)) for b in range(16)]])
            zoom.limit_y(self.logic_plot.vb, -0.5, 16, margin=0.05)
            self.logic_plot.setYRange(-0.5, 16, padding=0)
            if not cfg.analog_signals:
                span, t0 = cfg.frame_duration, cfg.time_origin
                # limites d'abord : sinon la nouvelle plage est rognée par les anciennes
                zoom.limit_x(self.logic_plot.vb, t0, t0 + span,
                             min_range=10 / cfg.sample_rate, margin=0.05)
                self.logic_plot.setXRange(t0, t0 + span, padding=0)

        if self.threshold_line in self.analog_plot.items:
            self.analog_plot.removeItem(self.threshold_line)
        if cfg.trigger_type in (TriggerType.ABOVE, TriggerType.BELOW) and cfg.analog_signals:
            self.threshold_line.setValue(cfg.threshold_physical())
            self.threshold_line.label.setFormat(
                f"seuil {cfg.analog_name(cfg.threshold_signal)} {cfg.trigger_type.label} "
                f"{cfg.threshold_physical():.4g}")
            self.analog_plot.addItem(self.threshold_line, ignoreBounds=True)

        span, t0 = cfg.frame_duration, cfg.time_origin
        # limites d'abord : sinon une trame plus longue que la précédente reste rognée
        # à l'ancienne durée
        # dézoom limité à la trame (à l'enregistrement) + 5 %, zoom à 10 échantillons ;
        # sur chaque panneau : les limites ne se transmettent pas par le lien des axes
        for plot in (self.analog_plot, self.logic_plot, self.math_plot):
            zoom.limit_x(plot.vb, t0, t0 + span, min_range=10 / cfg.sample_rate, margin=0.05)
        self.analog_plot.setXRange(t0, t0 + span, padding=0)
        self._update_y_limits()
        self._apply_y_range()
        self.analog_plot.setTitle("En attente de données")

    def _plot_of(self, key) -> pg.PlotItem:
        return {"A": self.analog_plot, "L": self.logic_plot, "M": self.math_plot}[key[0]]

    # ------------------------------------------------------------------ voies calculées
    def set_math_engine(self, engine):
        self.math_engine = engine

    def configure_math(self):
        """Courbes des voies calculées actives (formules modifiées, autre configuration)."""
        for key in [k for k in self.curves if k[0] == "M"]:
            self.math_plot.removeItem(self.curves.pop(key))
        self.math_legend.clear()
        active = self.math_engine.active if self.math_engine is not None else []
        for i, item in enumerate(active):
            key = ("M", item.name)
            label = f"{item.name} ({item.unit})" if item.unit else item.name
            curve = self.math_plot.plot(pen=pens.pen(pens.math_color(i), width=1.5), name=label)
            curve.setVisible(key not in self.hidden)
            self.curves[key] = curve
        unit = {item.unit for item in active}
        self.math_plot.setLabel("left", "Voies calculées",
                                units=unit.pop() if len(unit) == 1 and active else None)
        self.availability_changed.emit("math", bool(active))
        self._dirty = self.frame is not None

    def math_results(self, frame: Frame | None = None) -> dict:
        """{nom : tableau} des voies calculées de la trame (affichée par défaut)."""
        frame = frame or self.frame
        if frame is None or self.math_engine is None:
            return {}
        return self.math_engine.evaluate(frame)[0]

    def set_auto_range(self, enabled: bool):
        self.auto_range = enabled
        self._update_y_limits()
        self._apply_y_range()

    def _update_y_limits(self, math_results: dict | None = None):
        """
        Dézoom vertical limité aux valeurs des courbes visibles (+ 25 %), comme le
        GLviewer : sans limite, pyqtgraph échoue sur des plages démesurées.
        """
        cfg, frame = self.cfg, self.frame
        if cfg is None:
            return
        if cfg.analog_signals:
            arrays = []
            if frame is not None:
                cols = [j for j, s in enumerate(frame.analog_signals)
                        if ("A", s) not in self.hidden]
                if cols:
                    arrays.append(frame.analog[:, cols])
            if self.threshold_line in self.analog_plot.items:
                arrays.append([self.threshold_line.value()])
            if not self.auto_range or not arrays:          # échelle fixe de logger.m
                arrays.append([-self._fixed_y, self._fixed_y])
            span = zoom.bounds(*arrays)
            if span is not None:
                zoom.limit_y(self.analog_plot.vb, *span)
        results = math_results if math_results is not None else (
            self.math_results() if frame is not None else {})
        visible = [y for name, y in results.items() if ("M", name) not in self.hidden]
        span = zoom.bounds(*visible) if visible else None
        zoom.limit_y(self.math_plot.vb, *(span or (-1.0, 1.0)))

    def _apply_y_range(self):
        if self.cfg is None or not self.cfg.analog_signals:
            return
        if self.auto_range:
            self.analog_plot.enableAutoRange(axis="y")
        else:
            self.analog_plot.disableAutoRange(axis="y")
            self.analog_plot.setYRange(-self._fixed_y, self._fixed_y)

    def set_visible(self, key, visible: bool):
        (self.hidden.discard if visible else self.hidden.add)(key)
        if key in self.curves:
            self.curves[key].setVisible(visible)
        self._update_y_limits()

    def set_paused(self, paused: bool):
        self.paused = paused
        if not paused:
            self._dirty = self.frame is not None

    # ------------------------------------------------------------------ données
    def on_frame(self, frame: Frame):
        """Slot des trames : ne dessine pas, mémorise la dernière."""
        if self.paused:
            return
        self.frame = frame
        self._title_suffix = ""
        self._dirty = True

    def show_frame(self, frame: Frame, title_suffix: str = ""):
        """Affiche une trame donnée (mémoire tampon), même si l'affichage est figé."""
        self.frame = frame
        self._title_suffix = title_suffix
        self._dirty = True

    def _redraw(self):
        if not self._dirty or self.frame is None or self.cfg is None:
            return
        self._dirty = False
        frame = self.frame
        t = frame.time()
        # limites de zoom avant les données : l'échelle automatique les respecte
        self._update_y_limits()
        for j, sig in enumerate(frame.analog_signals):
            curve = self.curves.get(("A", sig))
            if curve is not None:
                curve.setData(t, frame.analog[:, j], skipFiniteCheck=True)
        if frame.logic is not None:
            for bit in range(16):
                curve = self.curves.get(("L", bit))
                if curve is not None:
                    curve.setData(t, bit + self.LOGIC_HEIGHT * frame.logic[:, bit],
                                  skipFiniteCheck=True)
        if self.math_engine is not None and self.math_engine.active:
            results, errors = self.math_engine.evaluate(frame)
            for item in self.math_engine.active:
                curve = self.curves.get(("M", item.name))
                if curve is None:
                    continue
                if item.name in results:
                    curve.setData(t, results[item.name])
                else:
                    curve.setData([], [])
            self.math_errors.emit(errors)
        title = frame.meta.get("title") or (f"Trame {frame.index}"
                                            + getattr(self, "_title_suffix", ""))
        self.analog_plot.setTitle(title)
        if not self.cfg.analog_signals:
            self.logic_plot.setTitle(title)
        self._emit_cursor_values()
        self.redrawn.emit()
        self._count_fps()

    def _count_fps(self):
        self._drawn += 1
        now = time.perf_counter()
        if now - self._fps_t0 >= 1.0:
            self.fps_changed.emit(self._drawn / (now - self._fps_t0))
            self._drawn, self._fps_t0 = 0, now

    # ------------------------------------------------------------------ curseur
    def _on_click(self, ev):
        if ev.double() and self.analog_plot.sceneBoundingRect().contains(ev.scenePos()):
            x = self.analog_plot.vb.mapSceneToView(ev.scenePos()).x()
            self.cursor.setValue(x)
            self.cursor.show()
            self._emit_cursor_values()

    def hide_cursor(self):
        self.cursor.hide()
        self._emit_cursor_values()

    def values_at(self, x: float | None) -> dict:
        frame = self.frame
        if frame is None:
            return {}
        i = frame.n_samples - 1 if x is None else int(round((x - frame.t0) * frame.sample_rate))
        i = min(max(i, 0), frame.n_samples - 1)
        values = {("A", s): float(frame.analog[i, j]) for j, s in enumerate(frame.analog_signals)}
        if frame.logic is not None:
            values.update({("L", b): int(frame.logic[i, b]) for b in range(16)})
        values.update({("M", name): float(y[i]) for name, y in self.math_results(frame).items()})
        return values

    def _emit_cursor_values(self, *_):
        x = self.cursor.value() if self.cursor.isVisible() else None
        self.cursor_values.emit(self.values_at(x))
