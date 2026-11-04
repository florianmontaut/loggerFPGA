"""Enregistrements longs d'oscilloscope : import CSV Tektronix -> HDF5, lecture."""
import h5py
import numpy as np
import pytest

from model import scope_record as sr

DT = 2e-7
T0 = 1.2549998


def tek_csv(path, signals, dt=DT, t0=T0, meta=True, names=()):
    """CSV au format Tektronix : métadonnées en colonnes 0-2, temps, signaux."""
    n = len(signals[0])
    t = t0 + np.arange(n) * dt
    rows = [('"Record Length"', f"{n}", '"Points"'),
            ('"Sample Interval"', f"{dt:.8e}", "s"),
            ('"Trigger Point"', "1000", '"Samples"'),
            ('"Trigger Time"', "1.2", "s"),
            ("", "", ""),
            ('"Horizontal Offset"', "-1.0e-004", "s")] if meta else []
    rows += [(f'"{name}"', "", "") for name in names]
    with open(path, "w") as f:
        for i in range(n):
            m = rows[i] if i < len(rows) else ("", "", "")
            values = ",".join(f"{s[i]:.8e}" for s in signals)
            f.write(f"{m[0]},{m[1]},{m[2]},{t[i]:.8e},{values}\n")
    return str(path)


def test_header_and_detection(tmp_path):
    path = tek_csv(tmp_path / "a.csv", [np.zeros(50), np.ones(50)])
    header = sr.read_tek_header(path)
    assert header.n_signals == 2 and header.first_time == pytest.approx(T0)
    assert header.value("record_length") == 50 and header.value("sample_interval") == DT
    assert header.metadata["horizontal_offset"]["unit"] == "s"
    assert sr.is_tek_csv(path)
    (tmp_path / "b.csv").write_text("trame,temps_s,V\n1,0,2\n")
    assert not sr.is_tek_csv(str(tmp_path / "b.csv"))


def test_import_and_read(tmp_path):
    n = 300_000
    rng = np.random.default_rng(0)
    s1 = np.sin(np.arange(n) / 500) + 0.01 * rng.standard_normal(n)
    s2 = np.cos(np.arange(n) / 70)
    s2[123_456] = 5.0                                   # pic isolé : doit rester visible
    path = tek_csv(tmp_path / "rec.csv", [s1, s2])
    steps = []
    h5_path = sr.import_tek_csv([path], str(tmp_path / "rec.h5"), chunk_rows=70_000,
                                progress=lambda f, t: steps.append(f))
    assert steps[-1] == 1.0 and steps == sorted(steps)
    rec = sr.ScopeRecord(h5_path)
    assert rec.names == ["CH1", "CH2"] and rec.length == n
    assert rec.dt == pytest.approx(DT) and rec.t0 == pytest.approx(T0)
    # brut
    w = rec.read_window(1000, 3000)
    assert not w.envelope and w.x0 == pytest.approx(T0 + 1000 * DT) and w.step == DT
    np.testing.assert_allclose(w.data["CH1"], s1[1000:3000], rtol=1e-6, atol=1e-6)
    # enveloppe : bornes exactes, pic conservé
    w = rec.read_window(0, n, max_raw=10_000, target_bins=1000)
    assert w.envelope and w.samples_per_bin > 1
    env = w.data["CH2"]
    assert env.max() == pytest.approx(5.0) and env.min() == pytest.approx(s2.min(), abs=1e-6)
    ov = rec.overview()
    assert ov.envelope and ov.data["CH2"].max() == pytest.approx(5.0)
    # index / temps
    assert rec.index_of(rec.time_of(1234)) == 1234
    rec.close()


def test_structure_compatible_with_hdf5_viewer(tmp_path):
    """Chemins et attributs lus par hdf5_viewer_multivoies.py (projet HDF5_viewer)."""
    path = tek_csv(tmp_path / "rec.csv", [np.arange(20_000, dtype=float)])
    h5_path = sr.import_tek_csv([path], str(tmp_path / "rec.h5"))
    with h5py.File(h5_path, "r") as h5:
        assert h5.attrs["format"] == "scope_hdf5_workspace"
        assert h5.attrs["sample_interval"] == pytest.approx(DT)
        assert h5.attrs["horizontal_offset"] == pytest.approx(-1e-4)
        assert h5.attrs["record_length_declared"] == 20_000
        g = h5["signals/CH1"]
        assert g["raw/value"].shape == (20_000,) and g["raw/value"].dtype == np.float32
        assert g["overview/min"].shape == g["overview/max"].shape == (4096,)
        levels = sorted((int(lv.attrs["samples_per_bin"]), k) for k, lv in g["pyramid"].items())
        assert levels[0][0] == 4 and all("min" in g["pyramid"][k] for _, k in levels)
        # niveau 1 : min / max exacts de chaque bloc de 4 points
        np.testing.assert_array_equal(g["pyramid/level_01/min"][:3], [0, 4, 8])
        np.testing.assert_array_equal(g["pyramid/level_01/max"][:3], [3, 7, 11])


def test_several_files_one_signal_each(tmp_path):
    a = tek_csv(tmp_path / "tek0000CH1.csv", [np.zeros(5000)])
    b = tek_csv(tmp_path / "tek0000CH3.csv", [np.ones(5000)])
    rec = sr.ScopeRecord(sr.import_tek_csv([a, b], sr.default_h5_path([a, b])))
    assert rec.names == ["CH1", "CH3"] and rec.path.endswith("tek0000CH1_voies.h5")
    c = tek_csv(tmp_path / "court.csv", [np.ones(4000)])
    with pytest.raises(sr.ScopeError, match="points"):
        sr.import_tek_csv([a, c], str(tmp_path / "x.h5"))
    assert not (tmp_path / "x.h5").exists() and not (tmp_path / "x.h5.partiel").exists()


def test_cancel_and_errors(tmp_path):
    path = tek_csv(tmp_path / "rec.csv", [np.zeros(50_000)])
    with pytest.raises(sr.ImportCancelled):
        sr.import_tek_csv([path], str(tmp_path / "rec.h5"), chunk_rows=10_000,
                          cancelled=lambda: True)
    assert not (tmp_path / "rec.h5").exists()
    bad = tmp_path / "bad.csv"
    bad.write_text("a,b,c\n")
    with pytest.raises(sr.ScopeError, match="colonnes"):
        sr.read_tek_header(str(bad))
    with pytest.raises(sr.ScopeError):
        sr.ScopeRecord(str(bad))


def test_channel_names_from_metadata_rows(tmp_path):
    """Comme csv_to_hdf5.py : une ligne de métadonnée inconnue par voie = son nom."""
    path = tek_csv(tmp_path / "rec.csv", [np.zeros(5000), np.ones(5000)],
                   names=("V_HV", "I_HV"))
    header = sr.read_tek_header(path)
    assert header.extra_keys == ["V_HV", "I_HV"]
    rec = sr.ScopeRecord(sr.import_tek_csv([path], str(tmp_path / "rec.h5")))
    assert rec.names == ["V_HV", "I_HV"]
    np.testing.assert_array_equal(rec.read_window(0, 10).data["I_HV"], np.ones(10))
