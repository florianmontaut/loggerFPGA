"""Acquisition complète contre le simulateur du FPGA (boucle locale UDP)."""
import itertools
import time

import numpy as np
import pytest
from PyQt6 import QtCore

from controller.udp_worker import AcquisitionWorker
from model.config import LoggerConfig, TriggerType
from tools.fpga_simulator import FpgaSimulator

_ports = itertools.count(23100, 3)


@pytest.fixture(scope="module")
def app():
    return QtCore.QCoreApplication.instance() or QtCore.QCoreApplication([])


def run_acquisition(app, cfg_kwargs, drop_rate=0.0, timeout=10.0, stop_after=None):
    port = next(_ports)
    sim = FpgaSimulator(ip="127.0.0.2", port=port, cmd_port=port + 1, drop_rate=drop_rate,
                        seed=1)
    sim.start()
    cfg = LoggerConfig(ip_fpga="127.0.0.2", port_fpga=port, port_cmd=port + 1,
                       local_ip="127.0.0.1", local_port=port + 2, **cfg_kwargs)
    worker = AcquisitionWorker(cfg)
    frames, errors, states = [], [], []
    worker.frame_ready.connect(frames.append)
    worker.error.connect(errors.append)
    worker.state_changed.connect(states.append)
    worker.start()
    t0 = time.time()
    while worker.isRunning() and time.time() - t0 < timeout:
        app.processEvents()
        if stop_after is not None and len(frames) >= stop_after:
            worker.request_stop()
        time.sleep(0.005)
    worker.request_stop()
    worker.wait(3000)
    app.processEvents()
    sim.stop()
    sim.join(2)
    return worker, sim, frames, errors, states


def test_auto_trigger_limited_frames(app):
    worker, sim, frames, errors, states = run_acquisition(
        app, dict(signals=[3, 15], divider=20, max_frames=5))
    assert not errors
    assert [f.index for f in frames] == [1, 2, 3, 4, 5]
    assert frames[0].analog.shape == (8192, 1) and frames[0].logic.shape == (8192, 16)
    assert states[-1] == "IDLE"
    assert sim.received[-1] == bytes([0x80, 0x06, 0xAA, 0xAA, 0x00, 0x00])   # stop_msg
    assert sim.cfg["signals"] == [3, 15]


def test_threshold_trigger_on_first_channel(app):
    # seuil à 0,8 pu sur la voie 6, placée en tête de liste par set_threshold_signal
    cfg = LoggerConfig(signals=[1, 6], trigger=TriggerType.ABOVE, max_frames=3)
    cfg.set_threshold_signal(6)
    thr = int(0.8 * 16384)
    worker, sim, frames, errors, _ = run_acquisition(
        app, dict(signals=cfg.signals, trigger=TriggerType.ABOVE, threshold=thr,
                  max_frames=3, gains=[1.0] * 15), timeout=20)
    assert not errors
    assert len(frames) == 3
    assert sim.cfg["signals"] == [6, 1] and sim.cfg["threshold"] == thr
    # pas de START_MSG en mode déclenché (comme logger.m)
    assert bytes([0x80, 0x01, 0xAA, 0x55, 0, 0]) not in sim.received
    for f in frames:
        assert f.analog[:, 0].max() > 0.8          # la voie de seuil a bien franchi


def test_lost_packets_counted_as_errors(app):
    worker, sim, frames, errors, _ = run_acquisition(
        app, dict(signals=[0], max_frames=4), drop_rate=0.05)
    assert worker.stats["frames"] == 4
    assert worker.stats["errors"] == len(errors) > 0
    assert len(frames) + len(errors) == 4


def test_stop_request_while_waiting_trigger(app):
    t0 = time.time()
    # disjonction jamais simulée avant 0,3 s, arrêt demandé tout de suite après 1 trame
    worker, sim, frames, errors, states = run_acquisition(
        app, dict(signals=[0, 1], trigger=TriggerType.TRIP), stop_after=1, timeout=10)
    assert len(frames) >= 1 and states[-1] == "IDLE"
    assert time.time() - t0 < 6


def test_recording_csv(app, tmp_path):
    worker, sim, frames, errors, _ = run_acquisition(
        app, dict(signals=[2, 15], max_frames=2, record=True, record_dir=str(tmp_path),
                  record_prefix="essai"))
    files = sorted(p.name for p in tmp_path.iterdir())
    assert files == ["essai_V_PH1_INV1_Logic_div_20_1.csv", "essai_V_PH1_INV1_Logic_div_20_2.csv"]
    table = np.loadtxt(tmp_path / files[0], delimiter=",", skiprows=1)
    assert table.shape == (8192, 1 + 1 + 16)
    np.testing.assert_allclose(table[:, 1], frames[0].analog[:, 0], rtol=1e-6)


class ImmediateTripSimulator(FpgaSimulator):
    """Disjonction déclenchée dès la réception de la configuration (pendant `tempo`)."""

    def _on_message(self, msg):
        super()._on_message(msg)
        if msg[:2] == bytes([0x80, 0x00]):
            self.next_trip = 0.0


def test_trigger_during_tempo_is_not_lost(app, monkeypatch):
    import tools.fpga_simulator as simulator
    monkeypatch.setattr(simulator, "FpgaSimulator", ImmediateTripSimulator)
    monkeypatch.setitem(globals(), "FpgaSimulator", ImmediateTripSimulator)
    # diviseur élevé : tempo = 16384 x 2000 / 25 MHz + 1 ms = 1,3 s, trig reçu pendant ce temps
    worker, sim, frames, errors, _ = run_acquisition(
        app, dict(signals=[0], trigger=TriggerType.TRIP, divider=2000, max_frames=1),
        timeout=8)
    assert not errors
    assert len(frames) == 1


def test_recorder_numbering_continues(tmp_path):
    """Une nouvelle acquisition n'écrase pas les fichiers de la précédente."""
    from model.protocol import encode_payload, make_frame
    from model.recorder import FrameRecorder
    cfg = LoggerConfig(signals=[2], record_dir=str(tmp_path), record_prefix="essai")
    frame = make_frame(encode_payload(np.zeros((16384, 1), dtype=np.int16)), cfg, 1)
    first = FrameRecorder(cfg)
    paths = [first.write(frame), first.write(frame)]
    (tmp_path / "essai_V_PH1_INV1_div_20_7.npz").write_bytes(b"")   # autre format : ignoré
    second = FrameRecorder(cfg)
    paths.append(second.write(frame))
    assert [p.rsplit("_", 1)[1] for p in paths] == ["1.csv", "2.csv", "3.csv"]
    assert second.directory == str(tmp_path)


def test_recorder_unwritable_dir(tmp_path):
    from model.recorder import FrameRecorder
    blocker = tmp_path / "fichier"
    blocker.write_text("x")                      # un fichier à la place du dossier
    with pytest.raises(OSError):
        FrameRecorder(LoggerConfig(record_dir=str(blocker / "sous_dossier")))
