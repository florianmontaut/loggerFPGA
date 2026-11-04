"""Relecture des enregistrements du logger."""
import numpy as np
import pytest

from model.config import LoggerConfig
from model.loader import RecordingError, load_recording
from model.protocol import encode_payload, make_frame
from model.recorder import save_frames

UNITS = [""] * 15
UNITS[2], UNITS[5] = "V", "A"
GAINS = [1.0] * 15
GAINS[2], GAINS[5] = 200.0, 50.0
CFG = LoggerConfig(signals=[2, 5, 15], units=UNITS, gains=GAINS, divider=40)


def frames(indexes, cfg=CFG):
    rng = np.random.default_rng(1)
    n = cfg.samples_per_channel
    out = []
    for i in indexes:
        raw = rng.integers(-30000, 30000, (n, cfg.n_channels)).astype(np.int16)
        frame = make_frame(encode_payload(raw), cfg, i, timestamp=1_700_000_000.0 + i)
        out.append(frame)
    return out


def same(a, b):
    assert a.index == b.index and a.signals == b.signals
    np.testing.assert_allclose(a.analog, b.analog, rtol=1e-8)
    if a.logic is None:
        assert b.logic is None
    else:
        np.testing.assert_array_equal(a.logic, b.logic)
    assert a.sample_rate == pytest.approx(b.sample_rate)


def test_csv_with_json(tmp_path):
    original = frames([7, 8, 12])
    path = save_frames(original, CFG, str(tmp_path / "enr.csv"))
    rec = load_recording(path)
    assert rec.from_metadata and not rec.notes
    assert rec.cfg.signals == [2, 5, 15] and rec.cfg.gains[5] == 50.0 and rec.cfg.divider == 40
    assert [f.index for f in rec.frames] == [7, 8, 12]
    for a, b in zip(original, rec.frames):
        same(a, b)
        np.testing.assert_array_equal(a.raw, b.raw)          # brut reconstitué exactement
        assert b.timestamp == a.timestamp
        assert b.meta["saved"] == b.meta["loaded"] == path


def test_csv_without_json(tmp_path):
    original = frames([3, 4])
    path = save_frames(original, CFG, str(tmp_path / "enr.csv"))
    (tmp_path / "enr.json").unlink()
    rec = load_recording(path)
    assert not rec.from_metadata and "json" in rec.notes[0]
    assert rec.cfg.signals == [0, 1, 15]                      # voies renumérotées
    assert rec.cfg.analog_names[:2] == ["V_PH1_INV1", "I_PH1_INV2"]
    assert rec.cfg.units[:2] == ["V", "A"] and rec.cfg.divider == 40
    assert rec.cfg.logic_names[:2] == ["K_HV", "K_PRE"]
    for a, b in zip(original, rec.frames):
        np.testing.assert_allclose(a.analog, b.analog, rtol=1e-8)
        np.testing.assert_array_equal(a.logic, b.logic)
        assert b.timestamp == 0.0


def test_npz_and_analog_only(tmp_path):
    cfg = LoggerConfig(signals=[0, 1], divider=25)
    original = frames([1, 2], cfg)
    rec = load_recording(save_frames(original, cfg, str(tmp_path / "enr.npz")))
    for a, b in zip(original, rec.frames):
        same(a, b)
    rec = load_recording(save_frames(original, cfg, str(tmp_path / "enr2.csv")))
    assert rec.frames[0].logic is None and rec.cfg.signals == [0, 1]


def test_legacy_one_file_per_frame(tmp_path):
    t = np.arange(4096) / 1.25e6
    table = np.column_stack([t, np.sin(t * 1e4), np.cos(t * 1e4)])
    path = tmp_path / "enr_V_HV_I_HV_div_20_5.csv"
    np.savetxt(path, table, delimiter=",", header="time_s,V_HV (V),I_HV (A)", comments="")
    rec = load_recording(str(path))
    assert [f.index for f in rec.frames] == [5]
    assert rec.cfg.analog_names[:2] == ["V_HV", "I_HV"] and rec.cfg.divider == 20
    np.testing.assert_allclose(rec.frames[0].analog[:, 1], np.cos(t * 1e4))


@pytest.mark.parametrize("content, message", [
    ("a,b,c\n1,2,3\n", "pas un enregistrement"),
    ("trame,temps_s,V\n", "Aucune donnée"),
    ("trame,temps_s,V\n1,0,x\n", "illisibles"),
])
def test_invalid_files(tmp_path, content, message):
    path = tmp_path / "x.csv"
    path.write_text(content)
    with pytest.raises(RecordingError, match=message):
        load_recording(str(path))


def test_unknown_format_and_missing_file(tmp_path):
    other = tmp_path / "x.xls"
    other.write_text("")
    with pytest.raises(RecordingError, match="Format"):
        load_recording(str(other))
    with pytest.raises(RecordingError, match="introuvable"):
        load_recording(str(tmp_path / "absent.csv"))
