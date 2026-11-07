# ressources/zoom.py
"""
Limites de zoom des graphiques (comme PlotPanel.update_zoom_limits du GLviewer).

Sans limite, la molette dézoome jusqu'à des plages de 1e30 : pyqtgraph échoue alors
(« Maximum allowed dimension exceeded » dans le sous-échantillonnage, glyphes et
QPainter inutilisables sous Windows). Chaque axe est donc borné par ViewBox.setLimits :

    - dézoom maximal : étendue des données + ZOOM_OUT_MARGIN de chaque côté ;
    - zoom maximal   : en X, quelques échantillons ; en Y, une fraction de l'étendue
                       (relative, et non 0.01 fixe comme le GLviewer : signaux en mV
                       d'un oscilloscope).
"""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg

ZOOM_OUT_MARGIN = 0.25          # dézoom : un quart de l'étendue de chaque côté
MIN_Y_FRACTION = 1e-6           # zoom maximal en Y : 1e-6 de l'étendue des données


def bounds(*arrays) -> tuple[float, float] | None:
    """(min, max) des valeurs finies, None s'il n'y en a pas."""
    lo, hi = np.inf, -np.inf
    for values in arrays:
        values = np.asarray(values, dtype=float)
        if values.size == 0:
            continue
        finite = values[np.isfinite(values)] if not np.isfinite(values).all() else values
        if finite.size:
            lo, hi = min(lo, float(finite.min())), max(hi, float(finite.max()))
    return (lo, hi) if lo <= hi else None


def _span(lo: float, hi: float) -> float:
    """Étendue ; une courbe plate garde une étendue non nulle (zoomable)."""
    width = hi - lo
    if width > 0:
        return width
    return max(abs(lo), abs(hi)) * 0.1 or 1.0


def limit_x(vb: pg.ViewBox, lo: float, hi: float, min_range: float | None = None,
            margin: float = ZOOM_OUT_MARGIN):
    width = _span(lo, hi)
    m = margin * width
    vb.setLimits(xMin=lo - m, xMax=hi + m, maxXRange=width + 2 * m,
                 minXRange=min(min_range, width) if min_range else None)


def limit_y(vb: pg.ViewBox, lo: float, hi: float, margin: float = ZOOM_OUT_MARGIN):
    width = _span(lo, hi)
    m = margin * width
    vb.setLimits(yMin=lo - m, yMax=hi + m, maxYRange=width + 2 * m,
                 minYRange=width * MIN_Y_FRACTION)


# bornes « libres » de pyqtgraph (ViewBox.__init__) : ±1e307, et non None (refusé par
# _effectiveLimits) ; les étendues min / max acceptent None
NO_LIMIT = 1e307


def clear_x(vb: pg.ViewBox):
    vb.setLimits(xMin=-NO_LIMIT, xMax=NO_LIMIT, minXRange=None, maxXRange=None)


def clear_y(vb: pg.ViewBox):
    vb.setLimits(yMin=-NO_LIMIT, yMax=NO_LIMIT, minYRange=None, maxYRange=None)
