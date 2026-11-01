"""Mesures entre curseurs."""
import numpy as np
import pytest

from model import measures

FS = 1000.0


def test_segment_on_sine():
    t = np.arange(2000) / FS
    y = 2.0 * np.sin(2 * np.pi * 5 * t) + 1.0           # 5 Hz, 2 crête, offset 1
    seg = measures.segment(y, FS, 0.0, 1.0)              # 5 périodes exactes (+1 point)
    assert seg.n == 1001 and seg.dt == pytest.approx(1.0)
    assert seg.maximum == pytest.approx(3.0, abs=1e-3)
    assert seg.minimum == pytest.approx(-1.0, abs=1e-3)
    assert seg.peak_to_peak == pytest.approx(4.0, abs=2e-3)
    assert seg.mean == pytest.approx(1.0, abs=2e-3)
    assert seg.rms == pytest.approx(np.sqrt(1 + 2.0 ** 2 / 2), abs=2e-3)


def test_snap_order_and_slope():
    y = np.arange(100, dtype=float) * 0.5                # rampe 500 unités/s
    seg = measures.segment(y, FS, 0.0504, 0.0101)        # t1 > t2 : Δ signés
    assert (seg.t1, seg.t2) == (pytest.approx(0.050), pytest.approx(0.010))
    assert seg.dy == pytest.approx(-20.0) and seg.dt == pytest.approx(-0.04)
    assert seg.slope == pytest.approx(500.0)
    assert seg.n == 41
    assert measures.segment(y, FS, -1, 10).t2 == pytest.approx(0.099)   # bornes


def test_deltas_columns_and_si():
    cols = np.column_stack([np.arange(10.0), -np.arange(10.0)])
    np.testing.assert_allclose(measures.deltas(cols, FS, 0.002, 0.007), [5, -5])
    assert measures.si(0.0025, "s") == "2.5 ms"
    assert measures.si(400, "Hz") == "400 Hz"
    assert measures.si(-1.5e-6, "s") == "-1.5 µs"
    assert measures.si(None) == "-" and measures.si(0, "V") == "0 V"
