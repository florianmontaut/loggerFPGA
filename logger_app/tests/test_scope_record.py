"""Enregistrements longs d'oscilloscope : import CSV Tektronix -> HDF5, lecture."""
import json
import os

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
    # longueur différente : acceptée, sans tronquer la plus longue (NaN après la courte)
    rec = sr.ScopeRecord(sr.import_tek_csv([a, c], str(tmp_path / "x.h5")))
    assert not rec.uniform and rec.length == 5000
    assert np.isnan(rec.read_window(4500, 5000).data[rec.names[1]][-10:]).all()
    rec.close()


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


def test_append_csv_and_h5_channels(tmp_path):
    """Un CSV par voie (Tektronix) : voies ajoutées une à une au même enregistrement."""
    n = 30_000
    a = tek_csv(tmp_path / "tek0000CH1.csv", [np.sin(np.arange(n) / 100)])
    b = tek_csv(tmp_path / "tek0000CH2.csv", [np.cos(np.arange(n) / 100)])
    c = tek_csv(tmp_path / "tek0000CH3.csv", [np.arange(n, dtype=float)])
    h5_path = sr.import_tek_csv([a], str(tmp_path / "rec.h5"))
    steps = []
    assert sr.append_to_workspace(h5_path, [b], progress=lambda f, t: steps.append(f)) == ["CH2"]
    assert steps[-1] == 1.0
    # un .h5 (ex. une autre conversion) : voies copiées avec leur pyramide ; nom déjà pris
    other = sr.import_tek_csv([c], str(tmp_path / "autre.h5"))
    with h5py.File(other, "a") as h5:
        h5.move("signals/CH1", "signals/CH2")         # même nom qu'une voie existante
    assert sr.append_to_workspace(h5_path, [other]) == ["CH2_2"]
    rec = sr.ScopeRecord(h5_path)
    assert rec.names == ["CH1", "CH2", "CH2_2"]
    np.testing.assert_allclose(rec.read_window(0, 5).data["CH2"], np.cos(np.arange(5) / 100),
                               atol=1e-6)
    w = rec.read_window(0, n, max_raw=1000)
    assert w.envelope and w.data["CH2_2"].max() == pytest.approx(n - 1)
    rec.close()
    with h5py.File(h5_path, "r") as h5:
        assert json.loads(h5.attrs["source_files"]) == ["tek0000CH1.csv", "tek0000CH2.csv",
                                                         "autre.h5"]
        assert h5.attrs["signal_count"] == 3


def test_append_refusals_keep_file(tmp_path):
    a = tek_csv(tmp_path / "a.csv", [np.zeros(10_000)])
    h5_path = sr.import_tek_csv([a], str(tmp_path / "rec.h5"))
    before = open(h5_path, "rb").read()
    with h5py.File(tmp_path / "inconnu.h5", "w") as h5:
        h5.create_dataset("x", data=np.zeros(10))
    with pytest.raises(sr.ScopeError, match="workspace"):
        sr.append_to_workspace(h5_path, [str(tmp_path / "inconnu.h5")])
    with pytest.raises(sr.ImportCancelled):
        sr.append_to_workspace(h5_path, [tek_csv(tmp_path / "b.csv", [np.ones(10_000)])],
                               chunk_rows=2_000, cancelled=lambda: True)
    with pytest.raises(sr.ScopeError, match="lui-même"):
        sr.append_to_workspace(h5_path, [h5_path])
    assert open(h5_path, "rb").read() == before            # intact
    assert not os.path.exists(h5_path + ".partiel")


def test_append_other_timebases(tmp_path):
    """Autre échantillonnage, autre début, autre longueur : chaque voie sa base de temps."""
    n = 10_000
    a = tek_csv(tmp_path / "a.csv", [np.arange(n, dtype=float)])           # DT, T0
    b = tek_csv(tmp_path / "b.csv", [np.arange(3000, dtype=float)], dt=DT * 4,
                t0=T0 + 1000 * DT)                                         # 4 x plus lent
    h5_path = sr.import_tek_csv([a], str(tmp_path / "rec.h5"))
    assert sr.ScopeRecord(h5_path).uniform
    assert sr.append_to_workspace(h5_path, [b]) == ["b"]
    with h5py.File(h5_path, "r") as h5:
        assert h5.attrs["mixed_timebase"]
        assert h5["signals/b"].attrs["sample_interval"] == pytest.approx(4 * DT)
    rec = sr.ScopeRecord(h5_path)
    assert not rec.uniform
    assert rec.dt == pytest.approx(DT) and rec.t0 == pytest.approx(T0)
    end = T0 + 1000 * DT + 3000 * 4 * DT                                   # fin de b
    assert rec.duration == pytest.approx(end - T0, rel=1e-6)
    # brut, grille de a (la plus fine) : b interpolé (rampe : exact), NaN avant son début
    w = rec.read_window(990, 1010)
    assert not w.envelope and w.step == pytest.approx(DT)
    assert rec.names == ["CH1", "b"]
    np.testing.assert_allclose(w.data["CH1"], np.arange(990, 1011), atol=1e-3)
    assert np.isnan(w.data["b"][:10]).all()
    np.testing.assert_allclose(w.data["b"][10:], np.arange(11) / 4, atol=1e-4)
    # au-delà de a : grille de b (seule présente), échantillons bruts de b
    start = rec.index_of(T0 + 11_000 * DT)
    w = rec.read_window(start, start + 400)
    assert w.step == pytest.approx(4 * DT) and np.isnan(w.data["CH1"]).all()
    assert np.all(np.diff(w.data["b"]) == 1)
    # enveloppe de tout l'enregistrement : les deux voies, trous hors de leur étendue
    w = rec.read_window(0, rec.length, max_raw=1000, target_bins=500)
    assert w.envelope and len(w.data["CH1"]) == len(w.data["b"]) == 1000
    assert np.nanmax(w.data["CH1"]) == pytest.approx(n - 1)
    assert np.nanmax(w.data["b"]) == pytest.approx(2999)
    assert np.isnan(w.data["CH1"][-10:]).all() and np.isnan(w.data["b"][:2]).all()
    # zone (FFT, motif) : grille commune ; échantillons propres de b
    x0, dt, data = rec.read_zone(T0 + 1000 * DT, T0 + 1100 * DT, 10_000)
    assert data.shape == (101, 2) and dt == pytest.approx(DT)
    t, y = rec.read_native("b", T0 + 1000 * DT, T0 + 1100 * DT)
    assert t.size == 26 and y[0] == 0 and y[-1] == 25
    with pytest.raises(ValueError, match="au plus"):
        rec.read_zone(T0, end, 1000)
    rec.close()


def test_import_tek_csv_different_files(tmp_path):
    """Plusieurs CSV choisis ensemble, d'échantillonnages différents : acceptés."""
    a = tek_csv(tmp_path / "x_CH1.csv", [np.zeros(5000)])
    b = tek_csv(tmp_path / "x_CH2.csv", [np.ones(2000)], dt=DT * 10)
    rec = sr.ScopeRecord(sr.import_tek_csv([a, b], str(tmp_path / "x.h5")))
    assert rec.names == ["CH1", "CH2"] and not rec.uniform
    assert rec.timebases["CH2"].dt == pytest.approx(10 * DT)
    assert rec.duration == pytest.approx(20_000 * DT, rel=1e-6)
    rec.close()


def test_picoscope_import(tmp_path):
    from pico_files import attrs_h5, pico_h5
    rng = np.random.default_rng(1)
    a1, a2 = rng.standard_normal(50_000), np.arange(50_000) / 1e4
    b2 = np.arange(40_000) / 1e4                      # plus courte (filtrage)
    path = pico_h5(tmp_path / "pico.h5", {
        "A": [(a1, -1e-3, 1e-7), (a2, -1e-3, 1e-7)],
        "B": [(a1, -1e-3, 1e-7), (b2, -1e-3 + 3e-8, 1e-7)],   # stabilisation : décalée
    })
    assert sr.is_picoscope_h5(path)
    layout = sr.read_pico_layout(path)
    assert layout.count == 2 and list(layout.waveforms) == ["A", "B"]
    assert layout.select(1)[1].n == 40_000 and layout.select(1)[0].unit == "V"
    with pytest.raises(sr.ScopeError, match="convertir"):
        sr.ScopeRecord(path)
    steps = []
    out = sr.import_picoscope(path, sr.default_pico_h5_path(path, 1, 2), waveform=1,
                              progress=lambda f, t: steps.append(f))
    assert out.endswith("pico_onde2.workspace.h5") and steps[-1] == 1.0
    assert not sr.is_picoscope_h5(out)
    rec = sr.ScopeRecord(out)
    assert rec.names == ["A", "B"] and not rec.uniform and rec.units["A"] == "V"
    assert rec.timebases["B"].n == 40_000
    assert rec.timebases["B"].t0 == pytest.approx(-1e-3 + 3e-8)
    assert rec.metadata["waveform"] == 2 and rec.metadata["Version"] == "7.2.30.10560"
    w = rec.read_window(1000, 1100)
    np.testing.assert_allclose(w.data["A"], a2[1000:1101], atol=1e-6)
    # B décalée de 0,3 échantillon : interpolée sur la grille de A (rampe : exacte)
    np.testing.assert_allclose(w.data["B"][1:], (np.arange(1001, 1101) - 0.3) / 1e4,
                               atol=1e-6)
    t, y = rec.read_native("B", rec.time_of(1000), rec.time_of(1100))
    np.testing.assert_allclose(y, b2[1000:1100], atol=1e-6)       # ses instants
    w = rec.read_window(0, rec.length, max_raw=1000)
    assert w.envelope and np.isnan(w.data["B"][-10:]).all()
    rec.close()
    # forme d'onde inexistante, spectre refusé, format non reconnu
    with pytest.raises(sr.ScopeError, match="forme d'onde 3"):
        sr.import_picoscope(path, str(tmp_path / "x.h5"), waveform=2)
    spec = pico_h5(tmp_path / "spectre.h5", {"A": [(a1, 0.0, 10.0)]}, unit="Hz")
    with pytest.raises(sr.ScopeError, match="spectre"):
        sr.read_pico_layout(spec)
    # variante : attributs start (temps absolu) / interval
    other = attrs_h5(tmp_path / "attrs.h5", {"V1": (a1, 0.0, 1e-6), "V2": (a2, 0.5, 2e-6)})
    assert sr.is_picoscope_h5(other)
    layout = sr.read_pico_layout(other)
    assert layout.metadata["start_epoch_s"] == pytest.approx(1.7e9)
    assert layout.select(0)[1].t0 == pytest.approx(0.5)
    rec = sr.ScopeRecord(sr.import_picoscope(other, str(tmp_path / "attrs_ws.h5")))
    assert rec.names == ["V1", "V2"] and rec.t0 == 0.0
    rec.close()


def test_append_picoscope_to_tek(tmp_path):
    from pico_files import pico_h5
    a = tek_csv(tmp_path / "a.csv", [np.zeros(10_000)])
    h5_path = sr.import_tek_csv([a], str(tmp_path / "rec.h5"))
    pico = pico_h5(tmp_path / "p.h5", {"A": [(np.ones(8000), T0, 5e-7),
                                             (np.full(8000, 2.0), T0, 5e-7)]})
    assert sr.append_to_workspace(h5_path, [pico], waveforms={os.path.abspath(pico): 1}) \
        == ["A"]
    rec = sr.ScopeRecord(h5_path)
    assert rec.names == ["CH1", "A"] and not rec.uniform
    assert np.nanmax(rec.read_window(0, 1000).data["A"]) == pytest.approx(2.0)
    rec.close()
