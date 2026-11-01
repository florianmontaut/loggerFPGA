"""Interface complète (hors écran) contre le simulateur du FPGA."""
import os
import pathlib
import tempfile
import time

import numpy as np
import pytest
from PyQt6 import QtWidgets

from controller.main_controller import MainController
from model.config import LoggerConfig, TriggerType
from tools.fpga_simulator import FpgaSimulator
from view.main_window import MainWindow

# captures d'écran des tests
SHOTS = pathlib.Path(os.environ.get("LOGGER_SHOTS", tempfile.gettempdir()))


@pytest.fixture(scope="module")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def wait(qapp, cond, timeout=10.0):
    t0 = time.time()
    while not cond() and time.time() - t0 < timeout:
        qapp.processEvents()
        time.sleep(0.005)
    qapp.processEvents()
    return cond()


@pytest.fixture
def setup(qapp):
    sim = FpgaSimulator(ip="127.0.0.2", port=23300, cmd_port=23301, seed=2)
    sim.start()
    cfg = LoggerConfig(ip_fpga="127.0.0.2", port_fpga=23300, port_cmd=23301,
                       local_ip="127.0.0.1", local_port=23302, signals=[1, 4, 6, 15],
                       units=["V"] * 15)
    window = MainWindow()
    ctrl = MainController(window, cfg, remember=False)
    window.show()
    yield qapp, sim, window, ctrl
    ctrl.quit()
    window.close()
    sim.stop()
    sim.join(2)


def test_live_display(setup):
    qapp, sim, window, ctrl = setup
    window.actionStart.trigger()
    assert wait(qapp, lambda: ctrl.graph_ctrl.frame is not None and ctrl.graph_ctrl.frame.index >= 3)
    wait(qapp, lambda: False, 0.2)
    x, y = ctrl.graph_ctrl.curves[("A", 4)].getData()
    assert len(y) > 0 and np.isfinite(y).all()
    assert ctrl.graph_ctrl.curves[("L", 3)].getData()[1].max() <= 3.8
    assert ctrl.tree_ctrl.items[("A", 1)][1].text() != ""
    assert window.actionStop.isEnabled()
    window.grab().save(str(SHOTS / "logger_live.png"))
    window.actionStop.trigger()
    assert wait(qapp, lambda: not ctrl.acq_ctrl.running)
    assert window.stateLabel.text() == "Arrêté"


def test_single_frame(setup):
    qapp, sim, window, ctrl = setup
    window.actionSingle.trigger()
    assert wait(qapp, lambda: ctrl.acq_ctrl.worker is not None or ctrl.graph_ctrl.frame)
    assert wait(qapp, lambda: not ctrl.acq_ctrl.running and ctrl.graph_ctrl.frame is not None)
    assert ctrl.graph_ctrl.frame.index == 1
    assert window.framesLabel.text() == "Trames : 1"


def test_threshold_channel_choice_reorders(setup):
    qapp, sim, window, ctrl = setup
    p = ctrl.config_ctrl.p
    p("Trigger", "Type").setValue(int(TriggerType.ABOVE))
    assert p("Trigger", "Voie de seuil").opts["visible"]
    choice = [c for c in p("Trigger", "Voie de seuil").opts["limits"] if c.split()[0] == "6"][0]
    p("Trigger", "Voie de seuil").setValue(choice)
    cfg = ctrl.config_ctrl.to_config()
    assert cfg.signals == [6, 1, 4, 15]
    p("Trigger", "Seuil (physique)").setValue(50.0)
    assert ctrl.config_ctrl.to_config().threshold == 8192
    # l'arbre des voies signale la voie de seuil
    assert "(seuil)" in ctrl.tree_ctrl.items[("A", 6)][0].text()
    window.grab().save(str(SHOTS / "logger_threshold.png"))


def test_threshold_acquisition_and_hidden_curve(setup):
    qapp, sim, window, ctrl = setup
    p = ctrl.config_ctrl.p
    p("Trigger", "Type").setValue(int(TriggerType.ABOVE))
    p("Trigger", "Seuil (physique)").setValue(80.0)        # 0,8 pu sur la voie 1
    p("Acquisition", "Nombre de trames").setValue(2)
    ctrl.tree_ctrl.items[("A", 4)][0].setCheckState(
        ctrl.tree_ctrl.items[("A", 4)][0].checkState().Unchecked)
    assert not ctrl.graph_ctrl.curves[("A", 4)].isVisible()
    window.actionStart.trigger()
    assert wait(qapp, lambda: ctrl.acq_ctrl.running, 2)
    assert wait(qapp, lambda: not ctrl.acq_ctrl.running, 20)
    assert ctrl.graph_ctrl.frame.index == 2
    assert ctrl.graph_ctrl.frame.analog[:, 0].max() > 80
    assert ctrl.graph_ctrl.threshold_line.value() == pytest.approx(80, rel=1e-3)


def test_invalid_config_message(setup):
    qapp, sim, window, ctrl = setup
    p = ctrl.config_ctrl.p
    p("Voies", "Voie 2").setValue(1)                       # doublon avec la voie 1
    assert "plusieurs fois" in window.statusBar().currentMessage()


def test_fft_panel(setup):
    """Simulateur : la voie s est une sinusoïde à 50 x (s + 1) Hz."""
    qapp, sim, window, ctrl = setup
    ctrl.config_ctrl.p("Échantillonnage", "Diviseur").setValue(500)     # 50 kHz
    fft = ctrl.fft_ctrl
    assert not window.fftgraph.isVisible()
    window.actionFFT.setChecked(True)
    assert window.fftgraph.isVisible()
    fft.p("Moyennage").setValue("moyenne")
    fft.p("Nombre de trames").setValue(3)
    window.actionStart.trigger()
    assert wait(qapp, lambda: fft.averager.n_averaged >= 3, 15)
    wait(qapp, lambda: False, 0.2)
    window.actionStop.trigger()
    assert wait(qapp, lambda: not ctrl.acq_ctrl.running)

    # voie analysée par défaut : la première (voie 1 -> 100 Hz)
    fundamental = fft.p("Mesures", "Fondamental").value()
    assert fundamental.startswith("1") and "Hz" in fundamental
    peaks = {round(f, -1) for f in _peak_freqs(fft, 1)}
    assert 100 in peaks
    # clic sur la voie 6 dans l'arborescence -> voie analysée, fondamental à 350 Hz
    ctrl.tree_ctrl.view.setCurrentIndex(ctrl.tree_ctrl.items[("A", 6)][0].index())
    assert fft.p("Voie analysée").value() == 6
    assert abs(_peak_freqs(fft, 6)[0] - 350) < 15
    assert fft.p("Mesures", "Trames moyennées").value() == "3"
    # échelle dB : les courbes sont redessinées en dB
    fft.p("Échelle").setValue("dB")
    wait(qapp, lambda: False, 0.1)
    y = fft.curves[6].getData()[1]
    assert y.max() < 60 and y.min() >= -200
    window.grab().save(str(SHOTS / "logger_fft.png"))


def _peak_freqs(fft, sig):
    from model import spectrum
    j = fft.signals.index(sig)
    return [p.frequency for p in spectrum.find_peaks(fft.freq, fft.amp[:, j], 3,
                                                     fft.p("Fenêtre").value(),
                                                     min_frequency=fft.freq[1])]
