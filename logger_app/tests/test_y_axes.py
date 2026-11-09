"""Répartition des voies analogiques par axe d'ordonnées (controller/y_axes.py)."""
from controller import y_axes

UNITS = {0: "V", 1: "A", 2: "V", 3: "", 4: "A"}


def test_groups_by_mode():
    sigs = [0, 1, 2, 3, 4]
    assert y_axes.groups(sigs, UNITS.get, "single") == [sigs]
    assert y_axes.groups(sigs, UNITS.get, "channel") == [[0], [1], [2], [3], [4]]
    assert y_axes.groups(sigs, UNITS.get, "unit") == [[0, 2], [1, 4], [3]]


def test_groups_limited_to_max_axes():
    sigs = list(range(12))
    by_unit = y_axes.groups(sigs, lambda s: "VA"[s % 2], "channel")
    assert by_unit == [sigs[0::2], sigs[1::2]]           # trop de voies : par unité
    many = y_axes.groups(sigs, lambda s: f"u{s}", "channel")
    assert len(many) == y_axes.MAX_AXES
    assert many[-1] == sigs[y_axes.MAX_AXES - 1:]        # surplus sur le dernier axe
    assert sorted(s for g in many for s in g) == sigs


def test_columns_left_then_right():
    assert y_axes.columns(1) == [("left", y_axes.MAIN_COLUMN)]
    for count in range(2, y_axes.MAX_AXES + 1):
        cols = y_axes.columns(count)
        left = [c for side, c in cols if side == "left"]
        right = [c for side, c in cols if side == "right"]
        assert len(cols) == len(set(cols)) == count
        assert len(left) == (count + 1) // 2 and len(left) <= 4 and len(right) <= 4
        assert left[0] == y_axes.MAIN_COLUMN and all(c < y_axes.MAIN_COLUMN for c in left[1:])
        assert all(c > y_axes.MAIN_COLUMN + 1 for c in right)
