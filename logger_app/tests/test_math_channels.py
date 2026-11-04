"""Voies calculées : formules du GLviewer sur les trames du logger."""
import numpy as np
import pytest

from model.config import LoggerConfig
from model.math_channels import MathDefinition, MathEngine, insertable_channels
from model.protocol import encode_payload, make_frame

CFG = LoggerConfig(signals=[0, 1, 15], gains=[16384.0] * 15,
                   units=["V", "A"] + [""] * 13, divider=500)          # 50 kHz


def make(v, i, bits=0):
    n = CFG.samples_per_channel
    raw = np.zeros((n, 3), dtype=np.int16)
    raw[:, 0], raw[:, 1], raw[:, 2] = v, i, bits
    return make_frame(encode_payload(raw), CFG, 1)


def engine(*defs):
    e = MathEngine()
    e.set_config(CFG)
    e.set_definitions([MathDefinition(*d) for d in defs])
    return e


def test_power_by_name_and_index_with_unit():
    n = CFG.samples_per_channel
    v = (100 * np.sin(np.arange(n) / 50)).astype(np.int16)
    e = engine(("P", "[V_HV]*[I_HV]"), ("P2", "A0*A1"))
    assert [c.computed_unit for c in e.compiled] == ["W", "W"]
    results, errors = e.evaluate(make(v, 3))
    assert not errors
    np.testing.assert_allclose(results["P"], v * 3.0)
    np.testing.assert_allclose(results["P2"], results["P"])


def test_extra_functions_and_units():
    n = CFG.samples_per_channel
    ramp = np.arange(n) % 1000                      # 1 point par échantillon
    e = engine(("d", "deriv([V_HV])"), ("q", "integ([I_HV])"), ("m", "movavg([V_HV]; 5)"),
               ("r", "rms([I_HV])"), ("pp", "pkpk([V_HV])"))
    assert [c.computed_unit for c in e.compiled] == ["V/s", "C", "V", "A", "V"]
    results, errors = e.evaluate(make(ramp.astype(np.int16), 2))
    assert not errors
    fs = CFG.sample_rate
    assert results["d"][10] == pytest.approx(fs)                   # 1 V par échantillon
    assert results["q"][-1] == pytest.approx(2 * (n - 1) / fs)     # 2 A pendant (n-1)/fs
    assert results["m"][10] == pytest.approx(10)
    assert results["m"][0] == pytest.approx(1)                     # bord : (0+1+2)/3
    assert np.all(results["r"] == 2)                              # scalaire -> droite
    assert results["pp"][0] == 999


def test_logic_and_chained_math():
    e = engine(("ET", "[K_HV]*L1"), ("NON_ET", "1-[ET]"), ("x", "ET+NON_ET"))
    results, errors = e.evaluate(make(0, 0, bits=0b11))
    assert not errors
    assert results["ET"][0] == 1 and results["NON_ET"][0] == 0 and results["x"][0] == 1
    assert e.compiled[0].computed_unit == ""                       # sans dimension


def test_errors_reported_per_channel():
    e = engine(("ok", "[V_HV]"), ("bad", "[V_HV]*"), ("unk", "[X]+1"), ("ok", "1"),
               ("deriv_num", "deriv(3)"), ("", "1"), ("V_HV", "1"))
    states = {i: c.error for i, c in enumerate(e.compiled)}
    assert states[0] is None
    assert "syntax" in states[1].lower()
    assert "voie inconnue : [X]" in states[2] and "[V_HV]" in states[2]
    assert "déjà utilisé" in states[3]
    assert states[5] == "nom vide" and "déjà utilisé" in states[6]
    results, errors = e.evaluate(make(1, 1))
    assert list(results) == ["ok"] and "nombre" in errors["deriv_num"]


def test_unit_mismatch_and_cache():
    e = engine(("s", "[V_HV]+[I_HV]"))
    assert e.compiled[0].computed_unit == "" and e.compiled[0].unit_issues
    frame = make(1, 1)
    first = e.evaluate(frame)[0]["s"]
    assert e.evaluate(frame)[0]["s"] is first                     # cache dans la trame
    e.set_definitions([MathDefinition("s", "2*[V_HV]")])
    assert e.evaluate(frame)[0]["s"][0] == 2                      # formule changée


def test_insertable_channels():
    names = insertable_channels(CFG)
    assert names[:2] == ["[V_HV]", "[I_HV]"] and "[K_HV]" in names and names[-1] == "time"


def test_readable_units():
    e = engine(("a", "[V_HV]*[V_HV]"), ("b", "[V_HV]/[I_HV]"), ("c", "[V_HV]*[I_HV]*time"),
               ("d", "2*[V_HV]"), ("e", "[V_HV]/[V_HV]"))
    assert [c.computed_unit for c in e.compiled] == ["V²", "Ω", "J", "V", ""]
