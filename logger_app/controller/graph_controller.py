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
from ressources import pens


class LiveGraphController(QtCore.QObject):

    cursor_values = QtCore.pyqtSignal(dict)    # clé -> valeur sous le curseur
    fps_changed = QtCore.pyqtSignal(float)

    REFRESH_HZ = 30
    LOGIC_HEIGHT = 0.8

    def __init__(self, widget: pg.GraphicsLayoutWidget):
        super().__init__()
        self.widget = widget
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
        for plot in (self.analog_plot, self.logic_plot):
            plot.showGrid(x=True, y=True, alpha=0.3)
            plot.setDownsampling(auto=True, mode="peak")
            plot.setClipToView(True)
            plot.setLabel("bottom", "Temps", units="s")
        self.logic_plot.setXLink(self.analog_plot)
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
        self.widget.scene().sigMouseClicked.connect(self._on_click)

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._redraw)
        self.timer.start(int(1000 / self.REFRESH_HZ))

    # ------------------------------------------------------------------ configuration
    def configure(self, cfg: LoggerConfig):
        """(Re)crée les courbes pour la configuration `cfg`."""
        self.cfg = cfg
        self.frame = None
        for key, curve in self.curves.items():
            (self.analog_plot if key[0] == "A" else self.logic_plot).removeItem(curve)
        self.curves.clear()
        self.legend.clear()
        self.widget.clear()

        if cfg.analog_signals:
            self.widget.addItem(self.analog_plot, row=0, col=0)
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
            self.widget.addItem(self.logic_plot, row=1, col=0)
            self.widget.ci.layout.setRowStretchFactor(0, 3)
            self.widget.ci.layout.setRowStretchFactor(1, 2)
            for bit in range(16):
                curve = self.logic_plot.plot(pen=pens.pen(pens.logic_color(bit)))
                curve.setVisible(("L", bit) not in self.hidden)
                self.curves[("L", bit)] = curve
            self.logic_plot.getAxis("left").setTicks(
                [[(b + self.LOGIC_HEIGHT / 2, cfg.logic_name(b)) for b in range(16)]])
            self.logic_plot.setYRange(-0.5, 16, padding=0)
            if not cfg.analog_signals:
                self.logic_plot.setXLink(None)

        if self.threshold_line in self.analog_plot.items:
            self.analog_plot.removeItem(self.threshold_line)
        if cfg.trigger_type in (TriggerType.ABOVE, TriggerType.BELOW) and cfg.analog_signals:
            self.threshold_line.setValue(cfg.threshold_physical())
            self.threshold_line.label.setFormat(
                f"seuil {cfg.analog_name(cfg.threshold_signal)} {cfg.trigger_type.label} "
                f"{cfg.threshold_physical():.4g}")
            self.analog_plot.addItem(self.threshold_line, ignoreBounds=True)

        span = cfg.frame_duration
        self.analog_plot.setXRange(0, span, padding=0)
        self.analog_plot.setLimits(xMin=-0.05 * span, xMax=1.05 * span)
        self._apply_y_range()
        self.analog_plot.setTitle("En attente de données")

    def set_auto_range(self, enabled: bool):
        self.auto_range = enabled
        self._apply_y_range()

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
        self._dirty = True

    def _redraw(self):
        if not self._dirty or self.frame is None or self.cfg is None:
            return
        self._dirty = False
        frame = self.frame
        t = frame.time()
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
        mo = frame.index * frame.raw.size * 2 / 1048576
        self.analog_plot.setTitle(f"Trame {frame.index}  -  {mo:.2f} Mo")
        self._emit_cursor_values()
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
        i = frame.n_samples - 1 if x is None else int(round(x * frame.sample_rate))
        i = min(max(i, 0), frame.n_samples - 1)
        values = {("A", s): float(frame.analog[i, j]) for j, s in enumerate(frame.analog_signals)}
        if frame.logic is not None:
            values.update({("L", b): int(frame.logic[i, b]) for b in range(16)})
        return values

    def _emit_cursor_values(self, *_):
        x = self.cursor.value() if self.cursor.isVisible() else None
        self.cursor_values.emit(self.values_at(x))
