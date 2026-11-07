"""Limites de zoom (ressources/zoom.py)."""
import numpy as np
import pyqtgraph as pg
import pytest
from PyQt6 import QtWidgets

from ressources import zoom


@pytest.fixture(scope="module")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_bounds_ignores_non_finite():
    assert zoom.bounds([1, np.nan, 3], [np.inf, -2]) == (-2, 3)
    assert zoom.bounds([], [np.nan]) is None


def test_limits_and_clear(qapp):
    vb = pg.ViewBox()
    zoom.limit_x(vb, 0.0, 10.0, min_range=0.5)
    zoom.limit_y(vb, -1.0, 1.0)
    limits = vb.state["limits"]
    assert limits["xLimits"] == [-2.5, 12.5] and limits["xRange"] == [0.5, 15.0]
    assert limits["yLimits"] == [-1.5, 1.5] and limits["yRange"][1] == 3.0
    zoom.limit_y(vb, 2.0, 2.0)                       # courbe plate : reste zoomable
    assert vb.state["limits"]["yRange"][1] > 0
    zoom.clear_x(vb)
    zoom.clear_y(vb)
    vb.setRange(xRange=(-1e6, 1e6))                  # plus de limite
    assert vb.viewRange()[0][1] > 1e5
