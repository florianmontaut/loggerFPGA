# controller/graph_controller.py
"""
Graphique temps réel.

Deux panneaux à axe des temps commun (comme les panneaux du GLviewer) :
    - voies analogiques (valeurs physiques), avec la ligne du seuil en trigger sur seuil ;
    - voies logiques, une voie par niveau (k + 0,8 x bit, comme `stairs(log)` de logger.m),
      affiché seulement si la voie logique est enregistrée.

Les voies analogiques peuvent avoir plusieurs axes d'ordonnées (controller/y_axes.py) :
un par voie pour un enregistrement d'oscilloscope, un seul pour le logger par défaut.

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
from controller import y_axes
from ressources import pens, zoom


class LiveGraphController(QtCore.QObject):

    cursor_values = QtCore.pyqtSignal(dict)    # clé -> valeur sous le curseur
    fps_changed = QtCore.pyqtSignal(float)
    redrawn = QtCore.pyqtSignal()              # nouvelle trame dessinée (mesures à refaire)
    # panneau utile ou non pour la configuration : "analog" / "logic" / "math", bool
    availability_changed = QtCore.pyqtSignal(str, bool)
    math_errors = QtCore.pyqtSignal(dict)      # voies calculées en erreur sur la trame
    # axes d'ordonnées recréés : largeur (px) des axes ajoutés à gauche, à droite
    axes_changed = QtCore.pyqtSignal(int, int)
    y_scales_changed = QtCore.pyqtSignal()     # plage d'un axe d'ordonnées modifiée

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
        # axes d'ordonnées des voies analogiques (controller/y_axes.py)
        self.axis_mode = "auto"
        self.groups: list[list[int]] = []          # voies de chaque axe
        self.scales: list[y_axes.AxisScale] = []   # axes au-delà du premier
        self._group_of: dict[int, int] = {}
        self._bounds: dict[int, tuple] = {}        # étendue des courbes visibles par axe
        # enregistrement d'oscilloscope : échelles ajustées une fois puis tenues (elles ne
        # bougent pas quand la portion affichée change), limites sur tout ce qui a été vu
        self.hold_scales = False
        self._main_fitted = False
        self._seen: dict[int, tuple] = {}
        self._fitting = False
        # voie sélectionnée dans l'arborescence, mise en évidence (highlight)
        self.highlighted: tuple | None = None
        self._highlight_curve = None
        self._highlight_pen = None
        self.snap_guides: list[pg.InfiniteLine] = []
        self._threshold_group: int | None = None   # axe de la ligne du seuil
        # décalage en X de courbes (aperçu d'un recalage, controller/align_controller.py)
        self.x_shift: dict[tuple, float] = {}
        self._drawn = 0
        self._fps_t0 = time.perf_counter()

        self.left_axis = y_axes.MainAxis("left")
        self.analog_plot = pg.PlotItem(viewBox=y_axes.SnapViewBox(),
                                       axisItems={"left": self.left_axis})
        y_axes.reserve_columns(self.analog_plot)
        self.analog_plot.vb.sigYRangeChanged.connect(self._on_main_y_changed)
        self.analog_plot.vb.sigRangeChangedManually.connect(self._on_main_manual)
        self.analog_plot.autoBtn.clicked.connect(self._on_auto_button)
        self.logic_plot = pg.PlotItem()
        # voies calculées, axe des temps commun
        self.math_plot = pg.PlotItem(viewBox=zoom.TimeViewBox())
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
        self.x_shift = {}
        self._clear_analog()
        for key, curve in self.curves.items():
            self._plot_of(key).removeItem(curve)
        self.curves.clear()
        self.legend.clear()
        self.math_legend.clear()
        self.availability_changed.emit("analog", bool(cfg.analog_signals))
        self.availability_changed.emit("logic", cfg.has_logic)
        self.logic_plot.setXLink(self.analog_plot if cfg.analog_signals else None)

        self._build_analog(cfg)
        if cfg.has_logic:
            for bit in range(16):
                curve = self.logic_plot.plot(pen=pens.pen(pens.logic_color(bit)))
                curve.setVisible(("L", bit) not in self.hidden)
                self.curves[("L", bit)] = curve
            if self.highlighted is not None and self.highlighted[0] == "L":
                self.highlight(self.highlighted)
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

    # ------------------------------------------------------------------ axes d'ordonnées
    def _clear_analog(self):
        """Retire les courbes analogiques, la ligne du seuil et les axes ajoutés."""
        if self._threshold_group is not None:
            self._remove_from_view(self.threshold_line, self._threshold_group)
            self._threshold_group = None
        for key in [k for k in self.curves if k[0] == "A"]:
            curve = self.curves.pop(key)
            self._remove_from_view(curve, self._group_of.get(key[1], 0))
            self.legend.removeItem(curve)
        for scale in self.scales:
            scale.remove()
        self.scales, self.groups, self._group_of, self._bounds = [], [], {}, {}
        self._seen, self._main_fitted = {}, False

    def _remove_from_view(self, item, group: int):
        if group == 0:
            self.analog_plot.removeItem(item)
        else:
            self.scales[group - 1].vb.removeItem(item)

    def _add_to_view(self, item, group: int, **kwargs):
        if group == 0:
            self.analog_plot.addItem(item, **kwargs)
        else:
            self.scales[group - 1].vb.addItem(item, **kwargs)

    def _build_analog(self, cfg: LoggerConfig):
        """Axes (controller/y_axes.py), courbes des voies analogiques, ligne du seuil."""
        signals = cfg.analog_signals
        self.hold_scales = cfg.record_points > 0
        mode = self.axis_mode
        if mode == "auto":      # enregistrement d'oscilloscope : calibres différents
            mode = "channel" if cfg.record_points else "single"
        self.groups = y_axes.groups(signals, cfg.unit, mode)
        self._group_of = {s: g for g, group in enumerate(self.groups) for s in group}
        places = y_axes.columns(len(self.groups))
        self.scales = [y_axes.AxisScale(self.analog_plot, side, column)
                       for side, column in places[1:]]
        for scale in self.scales:
            scale.vb.sigYRangeChanged.connect(self.y_scales_changed)
        multiple = len(self.groups) > 1
        for g, group in enumerate(self.groups):
            axis = self.left_axis if g == 0 else self.scales[g - 1].axis
            units = {cfg.unit(s) for s in group}
            unit = units.pop() if len(units) == 1 else None
            if multiple and len(group) == 1:
                y_axes.style_axis(axis, cfg.analog_name(group[0]), unit,
                                  pens.analog_color(group[0]))
            else:
                y_axes.style_axis(axis, "Mesures" if not multiple else (unit or "Mesures"),
                                  unit)
        for sig in signals:
            name = cfg.analog_name(sig)
            curve = pg.PlotDataItem(pen=pens.pen(pens.analog_color(sig)), name=name)
            group = self._group_of[sig]
            self._add_to_view(curve, group)
            if group:           # hors du PlotItem : réglages et légende à la main
                curve.setDownsampling(auto=True, method="peak")
                curve.setClipToView(True)
                self.legend.addItem(curve, name)
            curve.setVisible(("A", sig) not in self.hidden)
            self.curves[("A", sig)] = curve
        self.highlight(self.highlighted)        # courbes recréées
        # repères d'alignement des zéros : une limite de zone par voie (y_axes.SnapViewBox)
        for view in [self.analog_plot.vb] + [scale.vb for scale in self.scales]:
            view.snap_count = len(signals)
            view.on_axis_drag = self._show_snap_guides
        self._show_snap_guides(False)
        if signals:
            max_gain = max(abs(cfg.gain(s)) for s in signals) or 1.0
            # échelle fixe de logger.m : multiple de 100 supérieur au gain maximal
            self._fixed_y = (np.floor(max_gain / 100) + 1) * 100 if max_gain >= 100 else max_gain
        if cfg.trigger_type in (TriggerType.ABOVE, TriggerType.BELOW) and signals:
            self.threshold_line.setValue(cfg.threshold_physical())
            self.threshold_line.label.setFormat(
                f"seuil {cfg.analog_name(cfg.threshold_signal)} {cfg.trigger_type.label} "
                f"{cfg.threshold_physical():.4g}")
            self._threshold_group = self._group_of.get(cfg.threshold_signal, 0)
            self._add_to_view(self.threshold_line, self._threshold_group, ignoreBounds=True)
        # échelles des temps des autres graphiques alignées : même place de part et d'autre
        left = sum(1 for side, _ in places[1:] if side == "left") * y_axes.AXIS_WIDTH
        right = sum(1 for side, _ in places[1:] if side == "right") * y_axes.AXIS_WIDTH
        for plot in (self.logic_plot, self.math_plot):
            plot.layout.setContentsMargins(1 + left, 1, 1 + right, 1)
        self.axes_changed.emit(left, right)

    def set_axis_mode(self, mode: str):
        """Répartition des voies analogiques par axe : clé de y_axes.MODES."""
        if mode not in y_axes.MODES or mode == self.axis_mode:
            return
        self.axis_mode = mode
        if self.cfg is None:
            return
        self._clear_analog()
        self._build_analog(self.cfg)
        self._update_y_limits()
        self._apply_y_range()
        self._dirty = self.frame is not None

    def analog_view(self, sig: int | None) -> pg.ViewBox:
        """ViewBox (échelle verticale) de la voie analogique `sig`."""
        group = self._group_of.get(sig, 0)
        return self.analog_plot.vb if group == 0 else self.scales[group - 1].vb

    def _on_main_y_changed(self, *_):
        """
        Plage de l'axe principal modifiée : les autres échelles la suivent (zoom ou
        déplacement du graphique), sauf échelle automatique ou action sur l'axe seul.
        """
        follow = (not self.analog_plot.vb.autoRangeEnabled()[1]
                  and not self.left_axis.direct and not self._fitting)
        for scale in self.scales:
            if follow:
                scale.follow()
            else:
                scale.store_relation()
        self._place_snap_guides()
        self.y_scales_changed.emit()

    def to_main(self, sig: int | None, y: float) -> float:
        """Ordonnée de l'axe principal affichée à la hauteur de `y` sur l'axe de `sig`."""
        view = self.analog_view(sig)
        if view is self.analog_plot.vb:
            return y
        (m0, m1), (s0, s1) = self.analog_plot.vb.viewRange()[1], view.viewRange()[1]
        return m0 + (y - s0) * (m1 - m0) / (s1 - s0) if s1 != s0 else y

    def from_main(self, sig: int | None, y: float) -> float:
        """Réciproque de to_main : valeur sur l'axe de `sig` d'une ordonnée principale."""
        view = self.analog_view(sig)
        if view is self.analog_plot.vb:
            return y
        (m0, m1), (s0, s1) = self.analog_plot.vb.viewRange()[1], view.viewRange()[1]
        return s0 + (y - m0) * (s1 - s0) / (m1 - m0) if m1 != m0 else y

    def _on_main_manual(self, *_):
        """Zoom / déplacement du graphique : échelles figées, elles suivent la principale."""
        if not self.left_axis.direct and not self.analog_plot.vb.autoRangeEnabled()[1]:
            for scale in self.scales:
                scale.auto = False

    def _on_auto_button(self):
        """Bouton « A » du graphique : tous les axes de nouveau ajustés à leurs courbes."""
        if self.auto_range:
            self._main_fitted = False
            for scale in self.scales:
                scale.auto, scale.fitted = True, False
            if self.hold_scales:
                self.analog_plot.disableAutoRange(axis="y")
            self._fit_scales()

    def _fit_scales(self):
        """
        Axes ajustés à leurs courbes : à chaque trame (échelle automatique du logger), ou
        une seule fois (enregistrement d'oscilloscope, échelles tenues).
        """
        if (self.hold_scales and self.auto_range and not self._main_fitted
                and self.frame is not None and 0 in self._bounds):
            self._fitting = True                 # les autres échelles ne suivent pas
            try:
                self.analog_plot.vb.setYRange(*y_axes.fit_range(self._bounds[0]), padding=0)
            finally:
                self._fitting = False
            self._main_fitted = True
        for g, scale in enumerate(self.scales, start=1):
            if not scale.fitted or (scale.auto and not self.hold_scales):
                scale.fit(self._bounds.get(g))

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
        if self.highlighted is not None and self.highlighted[0] == "M":
            self.highlight(self.highlighted)
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
        self._main_fitted = False
        for scale in self.scales:
            scale.auto, scale.fitted = enabled, False
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
        # plusieurs axes ou échelles tenues : position libre, pour décaler une voie
        free = len(self.groups) > 1 or self.hold_scales
        self._bounds = {}
        for g, group in enumerate(self.groups):
            arrays = []
            if frame is not None:
                cols = [j for j, s in enumerate(frame.analog_signals)
                        if s in group and ("A", s) not in self.hidden]
                if cols:
                    arrays.append(frame.analog[:, cols])
            if self._threshold_group == g:
                arrays.append([self.threshold_line.value()])
            if g == 0 and (not self.auto_range or not arrays):   # échelle fixe de logger.m
                arrays.append([-self._fixed_y, self._fixed_y])
            span = zoom.bounds(*arrays)
            if span is not None:
                self._bounds[g] = span
                view = self.analog_view(group[0])
                if not free:
                    zoom.limit_y(view, *span)
                    continue
                if self.hold_scales and frame is not None:   # stables d'une portion à l'autre
                    seen = self._seen.get(g, span)
                    span = self._seen[g] = (min(seen[0], span[0]), max(seen[1], span[1]))
                zoom.limit_y_free(view, *span)
        results = math_results if math_results is not None else (
            self.math_results() if frame is not None else {})
        visible = [y for name, y in results.items() if ("M", name) not in self.hidden]
        span = zoom.bounds(*visible) if visible else None
        zoom.limit_y(self.math_plot.vb, *(span or (-1.0, 1.0)))

    def _apply_y_range(self):
        if self.cfg is None or not self.cfg.analog_signals:
            return
        if self.auto_range and self.hold_scales:
            self.analog_plot.disableAutoRange(axis="y")
        elif self.auto_range:
            self.analog_plot.enableAutoRange(axis="y")
        else:
            self.analog_plot.disableAutoRange(axis="y")
            self.analog_plot.setYRange(-self._fixed_y, self._fixed_y)
        self._fit_scales()

    def set_visible(self, key, visible: bool):
        (self.hidden.discard if visible else self.hidden.add)(key)
        if key in self.curves:
            self.curves[key].setVisible(visible)
        self._update_y_limits()
        self._fit_scales()

    def set_x_shift(self, shifts: dict):
        """Courbes tracées décalées en X ({clé : écart en s}) : aperçu d'un recalage."""
        self.x_shift = dict(shifts)
        self._dirty = self.frame is not None

    # ------------------------------------------------------------------ repères des zéros
    def _show_snap_guides(self, shown: bool):
        """Repères d'alignement des zéros, affichés pendant le déplacement d'un axe."""
        count = len(self.cfg.analog_signals) if shown and self.cfg is not None else 0
        while len(self.snap_guides) < count:
            line = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen(
                "#9aa", width=1, style=QtCore.Qt.PenStyle.DotLine))
            line.setZValue(-5)
            self.analog_plot.addItem(line, ignoreBounds=True)
            self.snap_guides.append(line)
        for k, line in enumerate(self.snap_guides):
            line.setVisible(k < count)
        self._place_snap_guides()

    def _place_snap_guides(self):
        visible = [line for line in self.snap_guides if line.isVisible()]
        if not visible:
            return
        y0, y1 = self.analog_plot.vb.viewRange()[1]
        for line, fraction in zip(visible, y_axes.snap_fractions(len(visible))):
            line.setValue(y0 + fraction * (y1 - y0))

    # ------------------------------------------------------------------ mise en évidence
    HIGHLIGHT_Z = 10
    HIGHLIGHT_WIDTH = 2.0      # mesuré : + 5 ms par tracé de trame, pour cette seule courbe

    def highlight(self, key):
        """
        Voie sélectionnée dans l'arborescence mise en évidence (comme
        GraphController.highlight du GLviewer) : sa courbe passe au premier plan, trait
        de 2 px. key None (ou sans courbe) : plus de voie en évidence.
        """
        curve = self._highlight_curve
        if curve is not None and curve is self.curves.get(self.highlighted):
            curve.setPen(self._highlight_pen)
            curve.setZValue(0)
        self.highlighted = key
        self._highlight_curve = curve = self.curves.get(key)
        group = self._group_of.get(key[1], 0) if curve is not None and key[0] == "A" else 0
        for g, scale in enumerate(self.scales, start=1):
            scale.set_raised(g == group)        # sa ViewBox au-dessus des autres
        if curve is None:
            return
        self._highlight_pen = pg.mkPen(curve.opts["pen"])
        pen = pg.mkPen(curve.opts["pen"])
        pen.setWidthF(max(pen.widthF(), self.HIGHLIGHT_WIDTH))
        curve.setPen(pen)
        curve.setZValue(self.HIGHLIGHT_Z)

    def set_faded(self, keys, opacity: float = 0.25):
        """Courbes `keys` estompées, les autres opaques (ensemble vide : toutes opaques)."""
        keys = set(keys)
        for key, curve in self.curves.items():
            curve.setOpacity(opacity if key in keys else 1.0)

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
        # voies de bases de temps différentes : trous (NaN) hors de l'étendue d'une voie
        gaps = bool(frame.meta.get("gaps"))
        for j, sig in enumerate(frame.analog_signals):
            curve = self.curves.get(("A", sig))
            if curve is not None:
                shift = self.x_shift.get(("A", sig))
                curve.setData(t + shift if shift else t, frame.analog[:, j],
                              skipFiniteCheck=not gaps, connect="finite" if gaps else "all")
        self._fit_scales()
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
                    curve.setData(t, results[item.name], connect="finite" if gaps else "all")
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
