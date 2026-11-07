"""Export d'un motif : sélection, décimation, formats."""
import numpy as np
import pytest

from model import pattern as pt


def test_select_and_decimation():
    t = np.arange(100_001) * 1e-6
    y = np.sin(t * 1e3)
    p = pt.select(t, y, 0.01, 0.03)                       # 20 001 échantillons
    assert p.zone_points == 20_001 and p.points <= 2000
    assert p.t[0] == pytest.approx(0.01) and p.t[-1] == pytest.approx(0.03)   # bornes gardées
    assert p.step == 11 and np.allclose(np.diff(p.t)[:-1], 11e-6)
    small = pt.select(t, y, 0.01, 0.0105)                 # 501 points : pas de décimation
    assert small.step == 1 and small.points == 501
    assert pt.select(t, y, 0.03, 0.01).points == p.points  # bornes inversées
    for n, m in [(2001, 2000), (4000, 2000), (2000, 2000), (10, 3), (5, 2)]:
        step = pt.decimation_step(n, m)
        assert len(range(0, n, step)) + (0 if (n - 1) % step == 0 else 1) <= m
    assert pt.select(t, y, 5, 6).points == 0              # hors des données
    with pytest.raises(ValueError):
        pt.select(t, y, 0, 1, max_points=1)


def test_formats():
    p = pt.Pattern(t=np.array([1.0, 1.0005, 1.001]), y=np.array([0.5, -1.25, 2.0]),
                   step=1, zone_points=3, t_start=1.0)
    assert pt.format_pattern(p, pt.FORMATS[0], "I_HV", "A") == (
        "t (s)\tI_HV (A)\n0\t0.5\n0.0005\t-1.25\n0.001\t2\n")
    assert pt.format_pattern(p, pt.FORMATS[1], "I_HV", "A", decimal_comma=True) == (
        "t (s);I_HV (A)\n0;0,5\n0,0005;-1,25\n0,001;2\n")
    # PWL : point décimal imposé, pas d'en-tête
    assert pt.format_pattern(p, pt.FORMATS[2], decimal_comma=True) == (
        "0 0.5\n0.0005 -1.25\n0.001 2\n")
    assert pt.format_pattern(p, pt.FORMATS[3], "V PH1") == (
        "t = [0 0.0005 0.001];\nV_PH1 = [0.5 -1.25 2];\n")
    # temps absolu
    assert pt.format_pattern(p, pt.FORMATS[2], relative=False).startswith("1 0.5\n1.0005")
    with pytest.raises(ValueError):
        pt.format_pattern(p, "xls")


def test_bounds_on_samples_despite_rounding():
    t = 0.3 + np.arange(1000) * 1e-7                      # temps recalculés : arrondis
    p = pt.select(t, np.ones(1000), 0.3 + 100 * 1e-7 + 1e-18, 0.3 + 200 * 1e-7 - 1e-18)
    assert p.zone_points == 101 and p.t[0] == t[100] and p.t[-1] == t[200]
