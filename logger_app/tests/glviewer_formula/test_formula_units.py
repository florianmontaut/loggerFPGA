"""Analyse des unités (copie des tests du GLviewer, sans ceux de son interface)."""
import numpy as np
import pytest

from model.formula import FormulaError, evaluate, fluids, parse, units


@pytest.mark.parametrize("text, si, scale", [
    ("°C", "K", 1), ("�C", "K", 1), ("degC", "K", 1), ("K", "K", 1),
    ("L/min", "m³/s", 1e-3 / 60), ("m3/h", "m³/s", 1 / 3600), ("m³/s", "m³/s", 1),
    ("kg/m³", "kg/m³", 1), ("J/(kg·K)", "J/(kg·K)", 1), ("W/(m²·K)", "W/(m²·K)", 1),
    ("mV", "V", 1e-3), ("kW", "W", 1e3), ("uA", "A", 1e-6), ("mbar", "Pa", 100),
    ("kWh", "J", 3.6e6), ("V/A", "Ω", 1), ("Ohm", "Ω", 1), ("1/s", "Hz", 1),
    ("%RH", "sans dimension", 0.01),
])
def test_parse_unit(text, si, scale):
    unit = units.parse_unit(text)
    assert units.dims_text(unit.dims) == si
    assert unit.scale == pytest.approx(scale)
    assert unit.text == text


@pytest.mark.parametrize("text", ["", "dB", "W/(m", "kg²x"])
def test_unknown_unit(text):
    with pytest.raises(units.UnitError):
        units.parse_unit(text)


UNITS = {"[Tin]": "°C", "[Tout]": "°C", "[P]": "W", "[Q]": "L/min", "[V]": "V",
         "[X]": "", "[Y]": "dB", "CH3": "A"}


def analyse(formula):
    return units.analyse(parse(formula), UNITS)


@pytest.mark.parametrize("formula, expected", [
    ("([Tout]-[Tin])/[P]", "K/W (résistance thermique)"),
    ("[P]/([Tout]-[Tin])", "W/K (conductance thermique)"),
    ("[Q]/60000*rho_water([Tin])*cp_water([Tin])*([Tout]-[Tin])", "W (puissance)"),
    ("[V]^2/[P]", "Ω (résistance électrique)"),
    ("[V]*CH3", "W (puissance)"),
    ("time*[P]", "J (énergie)"),
    ("sqrt([P]*[P])", "W (puissance)"),
    ("[Tin]+273.15", "°C (température)"),
    ("avg([Tin];[Tout])", "°C (température)"),
    ("max([P])", "W (puissance)"),
    ("2*[P]/1000", "W (puissance)"),
    ("-[P]", "W (puissance)"),
    ("exp(2)*3", "sans dimension"),
])
def test_result_unit(formula, expected):
    report = analyse(formula)
    assert report.issues == []
    assert units.describe(report.unit) == expected


@pytest.mark.parametrize("formula, issue", [
    ("[Tin]+[P]", "+ entre °C (température) et W (puissance)"),
    ("[P]-[V]", "- entre W"),
    ("max([P];[Tin])", "max(...) entre"),
    ("log([P])", "log d'une grandeur avec unité"),
    ("rho_water([P])", "rho_water attend une température"),
    ("[P]^[V]", "exposant avec unité"),
    ("[P]^time", "exposant avec unité"),
])
def test_inconsistent_formula(formula, issue):
    report = analyse(formula)
    assert report.unit is None
    assert any(text.startswith(issue) for text in report.issues), report.issues


@pytest.mark.parametrize("formula, note", [
    ("[X]*2", "[X] n'a pas d'unité"),
    ("[Y]+1", "unité « dB » de [Y] non reconnue"),
    ("steps(time;0;1;10;2)", "steps(...) : la table n'a pas d'unité"),
])
def test_undetermined_unit(formula, note):
    report = analyse(formula)
    assert report.unit is None and report.issues == []
    assert any(text.startswith(note) for text in report.notes), report.notes


def test_non_si_input_is_noted():
    report = analyse("[Q]*2")
    assert units.describe(report.unit) == "L/min (débit volumique)"
    assert report.notes == ["[Q] est en L/min, hors SI : 1 L/min = 1.667e-05 m³/s"]


def test_same_dimension():
    unit = analyse("([Tout]-[Tin])/[P]").unit
    assert units.same_dimension("°C/W", unit) is True
    assert units.same_dimension("K/kW", unit) is True
    assert units.same_dimension("W", unit) is False
    assert units.same_dimension("dB", unit) is None


@pytest.mark.parametrize("call, value", [
    ("rho_water(20)", 998.21), ("cp_water(20)", 4184.1), ("k_water(20)", 0.5984),
    ("mu_water(20)", 1.0016e-3), ("rho_water(25)", (998.21 + 995.65) / 2),
    ("rho_air(20)", 101325 / (287.05 * 293.15)), ("cp_air(26.85)", 1007),
    ("k_air(26.85)", 0.0263), ("mu_air(26.85)", 18.46e-6),
])
def test_fluid_values(call, value):
    assert evaluate(parse(call), {}) == pytest.approx(value, rel=1e-3)


def test_fluid_on_signal_and_out_of_range():
    t = np.array([10.0, 20.0, 150.0, np.nan])
    rho = evaluate(parse("rho_water([T])"), {"[T]": t})
    np.testing.assert_allclose(rho[:2], [999.70, 998.21])
    assert np.isnan(rho[2:]).all()          # hors table, valeur manquante
    with pytest.raises(FormulaError, match="outside the table"):
        evaluate(parse("rho_water(150)"), {})
    with pytest.raises(FormulaError, match="expects 1 argument"):
        evaluate(parse("cp_air(20;3)"), {})


def test_every_property_unit_is_known():
    for name, prop in fluids.PROPERTIES.items():
        assert units.quantity(units.parse_unit(prop.unit).dims), name
        assert fluids.function_name(prop.fluid, name.split("_")[0]) == name
