# controller/y_axes.py
"""
Axes d'ordonnées multiples du graphique des voies analogiques (comme les échelles par
unité du GLviewer, controller/plot_panel.py, et les axes par voie d'un PicoScope).

Les voies sont réparties en groupes, un axe par groupe, MAX_AXES au plus : la première
moitié à gauche du graphique, le reste à droite. Le premier groupe garde la ViewBox et
l'axe de gauche du PlotItem (zoom, déplacement, curseurs, menu) ; chaque autre groupe a
une AxisScale : une ViewBox sous la principale, de même géométrie et d'axe X lié, et son
axe dans une colonne ajoutée à la mise en page du PlotItem.

Échelles :
    - automatique : chaque axe est ajusté à ses propres courbes (plein écran) ; pour le
      logger à chaque trame, pour un enregistrement d'oscilloscope une seule fois (les
      échelles ne bougent plus quand on navigue dans le temps) ;
    - molette dans le graphique : zoom en X seulement (ressources/zoom.TimeViewBox) ;
    - déplacement dans le graphique : les plages des axes suivent celle de l'axe
      principal par une relation affine (y = a * y_principal + b), toutes les courbes
      bougent ensemble ;
    - glisser ou molette SUR un axe : seule l'échelle de cet axe change (étaler ou
      décaler une voie), les autres ne bougent pas.
"""
from __future__ import annotations

import pyqtgraph as pg
from PyQt6 import QtCore

from ressources import zoom

MAX_AXES = 8
AXIS_WIDTH = 58             # largeur d'un axe supplémentaire (px)
LEFT_COLUMNS = 3            # colonnes réservées à gauche de l'axe principal
RIGHT_COLUMNS = 4           # colonnes à droite du graphique
MAIN_COLUMN = LEFT_COLUMNS  # colonne de l'axe de gauche du PlotItem après reserve_columns
FIT_MARGIN = 0.03           # marge de l'ajustement aux données, en part de l'étendue
SNAP_PIXELS = 10            # le zéro d'un axe déplacé se colle à un repère à moins de 10 px

# modes de répartition (menu Affichage) ; "auto" : par voie pour un enregistrement
# d'oscilloscope, axe unique pour le logger
MODES = {"auto": "Automatique", "channel": "Un axe par voie", "unit": "Un axe par unité",
         "single": "Axe unique"}


def groups(signals: list[int], unit_of, mode: str) -> list[list[int]]:
    """
    Voies réparties par axe. « channel » au-delà de MAX_AXES voies : par unité ; groupes
    au-delà de MAX_AXES : réunis sur le dernier axe.
    """
    signals = list(signals)
    if mode == "single" or len(signals) <= 1:
        return [signals] if signals else []
    if mode == "channel" and len(signals) <= MAX_AXES:
        return [[s] for s in signals]
    by_unit: dict[str, list[int]] = {}
    for s in signals:
        by_unit.setdefault(unit_of(s) or "", []).append(s)
    result = list(by_unit.values())
    if len(result) > MAX_AXES:
        result[MAX_AXES - 1:] = [sum(result[MAX_AXES - 1:], [])]
    return result


def columns(count: int) -> list[tuple[str, int]]:
    """(côté, colonne de la mise en page) de chaque groupe ; le premier : axe principal."""
    left = (count + 1) // 2
    return [("left", MAIN_COLUMN - g) if g < left
            else ("right", MAIN_COLUMN + 3 + g - left) for g in range(count)]


def reserve_columns(plot: pg.PlotItem):
    """
    Mise en page du PlotItem décalée de LEFT_COLUMNS colonnes : place des axes
    supplémentaires à gauche (pyqtgraph met l'axe de gauche en colonne 0).
    """
    layout = plot.layout
    items = [(plot.titleLabel, 0, 1), (plot.getAxis("top"), 1, 1),
             (plot.getAxis("left"), 2, 0), (plot.vb, 2, 1), (plot.getAxis("right"), 2, 2),
             (plot.getAxis("bottom"), 3, 1)]
    for item, _row, _col in items:
        layout.removeItem(item)
    for item, row, col in items:
        layout.addItem(item, row, col + LEFT_COLUMNS)
    total = LEFT_COLUMNS + 3 + RIGHT_COLUMNS
    for col in range(total):
        layout.setColumnPreferredWidth(col, 0)
        layout.setColumnMinimumWidth(col, 0)
        layout.setColumnSpacing(col, 0)
        layout.setColumnStretchFactor(col, 1)
    layout.setColumnStretchFactor(MAIN_COLUMN + 1, 100)
    for col in list(range(LEFT_COLUMNS)) + list(range(MAIN_COLUMN + 3, total)):
        layout.setColumnFixedWidth(col, 0)


class MainAxis(pg.AxisItem):
    """
    Axe de gauche du PlotItem. `direct` est vrai pendant un glissement ou une molette sur
    l'axe : les autres échelles ne suivent pas (seule celle de cet axe change).
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.direct = False

    def mouseDragEvent(self, event):
        self.direct = True
        try:
            super().mouseDragEvent(event)
        finally:
            self.direct = False

    def wheelEvent(self, event):
        self.direct = True
        try:
            super().wheelEvent(event)
        finally:
            self.direct = False


def style_axis(axis: pg.AxisItem, text: str, unit: str | None, color=None):
    """Titre, unité et couleur (celle de la voie d'un axe à une seule voie)."""
    if color is None:
        axis.setPen()
        axis.setTextPen()
    else:
        axis.setPen(pg.mkPen(color))
        axis.setTextPen(pg.mkPen(color))
    axis.setLabel(text, units=unit or None)


def fit_range(bounds: tuple[float, float]) -> tuple[float, float]:
    """Plage ajustée à des données (bornes y0, y1), avec une petite marge."""
    y0, y1 = bounds
    width = y1 - y0
    if width <= 0:
        width = max(abs(y0), abs(y1)) * 0.1 or 1.0
        y0, y1 = y0 - width / 2, y1 + width / 2
    margin = FIT_MARGIN * width
    return y0 - margin, y1 + margin


def snap_fractions(count: int) -> list[float]:
    """
    Repères d'alignement des zéros : le graphique est découpé en count + 1 zones de même
    hauteur, les repères sont les count limites entre deux zones (part de la hauteur,
    depuis le bas).
    """
    return [k / (count + 1) for k in range(1, count + 1)]


def snapped_fraction(fraction: float, count: int, tolerance: float) -> float | None:
    """
    Repère à moins de `tolerance` (part de la hauteur) de `fraction`, sinon None : une
    limite entre deux zones, ou le bas (0) ou le haut (1) du graphique.
    """
    if count < 1:
        return None
    k = min(max(round(fraction * (count + 1)), 0), count + 1)
    target = k / (count + 1)
    return target if abs(fraction - target) <= tolerance else None


class SnapViewBox(zoom.TimeViewBox):
    """
    ViewBox dont le zéro s'aligne sur des repères quand on déplace son axe (glissement
    sur ses graduations) : le graphique est découpé en `snap_count` + 1 zones de même
    hauteur, et le zéro se colle à la limite entre deux zones, ou au bas ou au haut du
    graphique, dont il s'approche à moins de SNAP_PIXELS. Le déplacement reste libre
    ailleurs, et avec Maj enfoncée.

    Molette sur l'axe : si le zéro est sur un repère, il y reste (zoom autour de zéro).
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.snap_count = 0             # nombre de repères (voies analogiques)
        self.on_axis_drag = None        # appelé avec True au début, False à la fin
        self._drag_range = None         # plage au début du glissement

    def zero_fraction(self) -> float:
        """Position du zéro, en part de la hauteur depuis le bas."""
        y0, y1 = self.viewRange()[1]
        return -y0 / (y1 - y0) if y1 != y0 else 0.0

    def zero_snapped(self) -> bool:
        tolerance = 0.5 / max(self.height(), 1.0)
        return snapped_fraction(self.zero_fraction(), self.snap_count, tolerance) is not None

    def mouseDragEvent(self, ev, axis=None):
        left = ev.button() == QtCore.Qt.MouseButton.LeftButton
        if axis != 1 or not left or not self.state["mouseEnabled"][1]:
            super().mouseDragEvent(ev, axis=axis)
            return
        ev.accept()
        if ev.isStart() or self._drag_range is None:
            self._drag_range = tuple(self.viewRange()[1])
            if self.on_axis_drag:
                self.on_axis_drag(True)
        y0, y1 = self._drag_range
        span, height = y1 - y0, max(self.height(), 1.0)
        # déplacement depuis le début du glissement (et non pas à pas) : le zéro collé
        # se décolle dès que la souris s'éloigne du repère
        moved = ev.pos().y() - ev.buttonDownPos().y()
        y0 += moved * span / height
        free = bool(ev.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier)
        target = None if free else snapped_fraction(-y0 / span, self.snap_count,
                                                    SNAP_PIXELS / height)
        if target is not None:
            y0 = -target * span
        self._resetTarget()
        self.setYRange(y0, y0 + span, padding=0)
        self.sigRangeChangedManually.emit(self.state["mouseEnabled"])
        if ev.isFinish():
            self._drag_range = None
            if self.on_axis_drag:
                self.on_axis_drag(False)

    def wheelEvent(self, ev, axis=None):
        if axis != 1 or not self.state["mouseEnabled"][1] or not self.zero_snapped():
            super().wheelEvent(ev, axis=axis)
            return
        scale = 1.02 ** (ev.delta() * self.state["wheelScaleFactor"])
        self._resetTarget()
        self.scaleBy(y=scale, center=pg.Point(0, 0))
        ev.accept()
        self.sigRangeChangedManually.emit([False, True])


class ScaleViewBox(SnapViewBox):
    """
    ViewBox d'une échelle ajoutée : elle ne répond qu'à son axe (glissement ou molette
    sur ses graduations, `axis` est alors précisé). Dans la zone de tracé, elle laisse la
    souris à la ViewBox principale, même placée au-dessus d'elle (voie mise en évidence).
    """

    def mouseDragEvent(self, ev, axis=None):
        if axis is None:
            ev.ignore()
        else:
            super().mouseDragEvent(ev, axis=axis)

    def wheelEvent(self, ev, axis=None):
        if axis is None:
            ev.ignore()
        else:
            super().wheelEvent(ev, axis=axis)

    def mouseClickEvent(self, ev):
        ev.ignore()


class AxisScale:
    """Échelle d'un groupe de voies au-delà du premier : sa ViewBox et son axe."""

    def __init__(self, plot: pg.PlotItem, side: str, column: int):
        self.plot = plot
        self.main_vb = plot.vb
        self.side = side
        self.column = column
        self.a, self.b = 1.0, 0.0
        self.auto = True            # ajustée à ses courbes à chaque trame
        self.fitted = False
        self.vb = ScaleViewBox(enableMenu=False)
        self.vb.setParentItem(plot)
        # sous la ViewBox principale : elle reçoit la souris (zoom, déplacement, menu)
        self.vb.setZValue(self.main_vb.zValue() - 1)
        self.vb.setMouseEnabled(x=False, y=True)
        self.vb.setXLink(self.main_vb)
        self.vb.setGeometry(self.main_vb.geometry())
        self.axis = pg.AxisItem(side)
        self.axis.linkToView(self.vb)
        self.axis.setWidth(AXIS_WIDTH)
        plot.layout.addItem(self.axis, 2, column)
        plot.layout.setColumnFixedWidth(column, AXIS_WIDTH)
        self.main_vb.sigResized.connect(self._sync_geometry)
        self.vb.sigRangeChangedManually.connect(self._on_manual)

    def set_raised(self, raised: bool):
        """Au-dessus de la ViewBox principale (voie mise en évidence) ou dessous."""
        self.vb.setZValue(self.main_vb.zValue() + (1 if raised else -1))

    def _sync_geometry(self):
        self.vb.setGeometry(self.main_vb.geometry())
        self.vb.linkedViewChanged(self.main_vb, self.vb.XAxis)

    def _on_manual(self, *_):
        """Glissement ou molette sur l'axe : échelle choisie à la main."""
        self.auto = False
        self.store_relation()

    def follow(self):
        """Plage déduite de celle de l'axe principal (zoom / déplacement du graphique)."""
        m0, m1 = self.main_vb.viewRange()[1]
        self.vb.setYRange(self.a * m0 + self.b, self.a * m1 + self.b, padding=0)

    def store_relation(self):
        """Relation entre la plage de cette échelle et celle de l'axe principal."""
        m0, m1 = self.main_vb.viewRange()[1]
        s0, s1 = self.vb.viewRange()[1]
        if m1 - m0 == 0:
            return
        self.a = (s1 - s0) / (m1 - m0)
        self.b = s0 - self.a * m0

    def fit(self, bounds: tuple[float, float] | None):
        """Plage ajustée aux données (bornes y0, y1)."""
        if bounds is None:
            return
        self.vb.setYRange(*fit_range(bounds), padding=0)
        self.fitted = True
        self.store_relation()

    def remove(self):
        self.main_vb.sigResized.disconnect(self._sync_geometry)
        self.vb.sigRangeChangedManually.disconnect(self._on_manual)
        self.plot.layout.removeItem(self.axis)
        self.plot.layout.setColumnFixedWidth(self.column, 0)
        self.vb.setXLink(None)
        for item in (self.axis, self.vb):
            item.setParentItem(None)
            if item.scene() is not None:
                item.scene().removeItem(item)
