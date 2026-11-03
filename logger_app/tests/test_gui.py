"""Interface complète (hors écran) contre le simulateur du FPGA."""
import os
import pathlib
import tempfile
import time

import numpy as np
import pytest
from PyQt6 import QtCore, QtWidgets

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


def test_measure_cursors(setup):
    """Trame connue injectée directement : rampe sur la voie 4, créneau logique."""
    from model.config import FULL_SCALE
    from model.protocol import encode_payload, make_frame
    qapp, sim, window, ctrl = setup
    cfg = ctrl.config_ctrl.to_config()                      # voies [1, 4, 6, 15], 1,25 MHz
    n = cfg.samples_per_channel
    raw = np.zeros((n, 4), dtype=np.int16)
    raw[:, 1] = (np.arange(n) * 4).astype(np.int16)         # voie 4 : rampe
    raw[n // 2:, 3] = 0b1                                   # K_HV passe à 1 à mi-trame
    frame = make_frame(encode_payload(raw), cfg, 1)
    ctrl.graph_ctrl.on_frame(frame)
    wait(qapp, lambda: False, 0.1)

    cur = ctrl.cursor_ctrl
    cur.set_type("Verticaux")
    assert cur.v_lines["analog"][0] in ctrl.graph_ctrl.analog_plot.items
    assert cur.v_lines["logic"][0] in ctrl.graph_ctrl.logic_plot.items
    assert not ctrl.tree_ctrl.view.isColumnHidden(ctrl.tree_ctrl.DELTA)

    fs = cfg.sample_rate
    i1, i2 = 1000, 3000
    cur.set_vertical(i1 / fs, i2 / fs)
    assert cur.v_lines["analog"][1].value() == pytest.approx(i2 / fs)
    assert cur.v_lines["logic"][1].value() == pytest.approx(i2 / fs)
    # Δ par voie dans l'arborescence : rampe 4 points/échantillon, gain 100 / 16384
    step = 4 * cfg.gain(4) / FULL_SCALE
    assert float(ctrl.tree_ctrl.items[("A", 4)][3].text()) == pytest.approx((i2 - i1) * step, rel=1e-4)
    assert ctrl.tree_ctrl.items[("L", 0)][3].text() == "+1"
    assert ctrl.tree_ctrl.items[("L", 0)][1].text() == "0"           # valeur en t1
    assert cur.p("Verticaux", "Δt").value() == "1.6 ms"

    # voie de mesure : clic sur la voie 4 dans l'arborescence
    ctrl.tree_ctrl.view.setCurrentIndex(ctrl.tree_ctrl.items[("A", 4)][0].index())
    assert cur.p("Voie de mesure").value() == 4
    assert cur.p("Mesures", "Échantillons").value() == str(i2 - i1 + 1)
    assert cur.p("Mesures", "Crête-crête").value().startswith(f"{(i2 - i1) * step:.4g}"[:4])

    # déplacer la ligne du panneau logique déplace celle du panneau analogique et t1
    cur.v_lines["logic"][0].setValue(2500 / fs)          # après le front (2048)
    assert cur.v_lines["analog"][0].value() == pytest.approx(2500 / fs)
    assert cur.p("Verticaux", "t1").value() == pytest.approx(2500 / fs)
    assert ctrl.tree_ctrl.items[("L", 0)][3].text() == "+0"

    # curseurs horizontaux en plus
    cur.set_type("Verticaux + horizontaux")
    cur.set_horizontal(-10.0, 15.0)
    assert cur.h_lines[1].value() == 15.0
    assert cur.p("Horizontaux", "Δy").value() == "25 V"
    assert "Δt" in cur.readout.text and "Δy (curseurs)" in cur.readout.text
    window.grab().save(str(SHOTS / "logger_cursors.png"))

    cur.set_type("Aucun")
    assert cur.v_lines["analog"][0] not in ctrl.graph_ctrl.analog_plot.items
    assert ctrl.tree_ctrl.view.isColumnHidden(ctrl.tree_ctrl.DELTA)


def test_detach_fft_window(setup):
    qapp, sim, window, ctrl = setup
    det = ctrl.detach_ctrl
    split = window.graph_splitter
    assert [split.widget(i) for i in range(3)] == [window.analoggraph, window.logicgraph,
                                                   window.fftgraph]
    window.actionFFT.setChecked(True)
    det.detach("fft")
    fft_window = det.window_of("fft")
    assert fft_window is not None and fft_window.isVisible()
    assert window.fftgraph.window() is fft_window
    assert split.indexOf(window.fftgraph) == -1
    assert ctrl.fft_ctrl.plot.vb.menu.actions()[-1].text().startswith("Réintégrer")
    # raccourcis de la fenêtre principale disponibles dans la fenêtre déportée
    assert window.actionStart in fft_window.actions()

    # le spectre déporté suit l'acquisition
    ctrl.config_ctrl.p("Échantillonnage", "Diviseur").setValue(500)
    window.actionStart.trigger()
    assert wait(qapp, lambda: ctrl.fft_ctrl.amp is not None, 15)
    wait(qapp, lambda: False, 0.2)
    assert len(ctrl.fft_ctrl.curves[1].getData()[1]) > 0
    window.actionStop.trigger()
    assert wait(qapp, lambda: not ctrl.acq_ctrl.running)
    fft_window.resize(640, 360)
    fft_window.grab().save(str(SHOTS / "logger_fft_detached.png"))

    # FFT désactivée : fenêtre masquée ; réactivée : fenêtre réaffichée
    window.actionFFT.setChecked(False)
    assert not fft_window.isVisible()
    window.actionFFT.setChecked(True)
    assert fft_window.isVisible()

    # fermer la fenêtre réintègre le spectre à sa place (sous les voies logiques)
    fft_window.close()
    qapp.processEvents()
    assert not det.is_detached("fft")
    assert split.indexOf(window.fftgraph) == 2 and window.fftgraph.isVisible()
    assert not window.menuWindows.actions()[2].isChecked()


def test_detach_all_and_restore(setup, tmp_path):
    qapp, sim, window, ctrl = setup
    det = ctrl.detach_ctrl
    det.detach("logic")
    det.detach("analog")
    assert window.graph_placeholder.isVisible()           # FFT désactivée, tout déporté
    assert det.window_of("analog").isVisible()
    # menu Fenêtres : cases cochées, « Tout réintégrer »
    actions = {a.text(): a for a in window.menuWindows.actions()}
    assert actions["Déporter « Voies logiques »"].isChecked()
    det.window_of("logic").setGeometry(120, 80, 700, 300)
    det.attach("logic")                                      # revient sous l'analogique ?
    det.attach("analog")
    split = window.graph_splitter
    assert split.indexOf(window.analoggraph) < split.indexOf(window.logicgraph)
    assert not window.graph_placeholder.isVisible()
    # position de la fenêtre conservée pour le déport suivant
    det.detach("logic")
    assert det.window_of("logic").size() == QtCore.QSize(700, 300)

    # persistance d'une session à l'autre (QSettings)
    settings = QtCore.QSettings(str(tmp_path / "s.ini"), QtCore.QSettings.Format.IniFormat)
    det.settings = settings
    det.save()
    det.attach_all()
    det.restore()
    assert det.is_detached("logic") and not det.is_detached("analog")
    actions["Tout réintégrer"].trigger()
    assert not det.is_detached("logic")


def test_logic_only_config_hides_analog(setup):
    qapp, sim, window, ctrl = setup
    ctrl.config_ctrl.p("Voies", "Nombre de voies").setValue(1)
    ctrl.config_ctrl.p("Voies", "Voie 1").setValue(15)
    assert not window.analoggraph.isVisible() and window.logicgraph.isVisible()
    ctrl.config_ctrl.p("Voies", "Voie 1").setValue(2)
    assert window.analoggraph.isVisible() and not window.logicgraph.isVisible()
