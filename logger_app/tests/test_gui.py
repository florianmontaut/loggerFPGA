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
    ctrl = MainController(window, cfg, remember=False, confirm_quit=False)
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
    assert [split.widget(i) for i in range(4)] == [window.analoggraph, window.mathgraph,
                                                   window.logicgraph, window.fftgraph]
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
    assert split.indexOf(window.fftgraph) == 3 and window.fftgraph.isVisible()
    assert not window.menuWindows.actions()[3].isChecked()


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


def test_record_button_during_acquisition(setup, tmp_path, monkeypatch):
    qapp, sim, window, ctrl = setup
    ctrl.config_ctrl.p("Enregistrement", "Dossier").setValue(str(tmp_path))
    csvs = lambda: sorted(p for p in tmp_path.iterdir() if p.suffix == ".csv")
    def trames(path):
        lines = path.read_text().splitlines()[1:]       # en-tête seul : pas encore de trame
        return {int(line.split(",", 1)[0]) for line in lines if line}
    assert window.actionRecord.isEnabled()
    messages = []
    ctrl.acq_ctrl.recording_changed.connect(lambda on, path: messages.append((on, path)))
    window.actionStart.trigger()
    assert wait(qapp, lambda: ctrl.graph_ctrl.frame is not None)
    assert csvs() == []
    assert messages == []           # pas d'« enregistrement arrêté » sans enregistrement
    # clic sur Enregistrer pendant l'acquisition : un fichier, qui grandit trame après trame
    assert window.actionRecord.isEnabled()
    window.actionRecord.trigger()
    assert wait(qapp, lambda: csvs() and len(trames(csvs()[0])) >= 2)
    assert window.recordLabel.text() == "● REC"
    assert str(tmp_path) in window.statusBar().currentMessage()
    # second clic : fichier fermé, plus rien n'y est ajouté
    window.actionRecord.trigger()
    assert wait(qapp, lambda: window.recordLabel.text() == "")
    first = csvs()[0]
    n = len(trames(first))
    wait(qapp, lambda: False, 0.3)
    assert len(trames(first)) == n
    window.actionStop.trigger()
    assert wait(qapp, lambda: not ctrl.acq_ctrl.running)

    # armé à l'arrêt, puis Démarrer : nouveau fichier, numéros de trame qui continuent
    window.actionRecord.trigger()
    assert window.actionRecord.isChecked() and window.recordLabel.text() == ""
    assert "armé" in window.statusBar().currentMessage()
    window.actionStart.trigger()
    assert wait(qapp, lambda: len(csvs()) == 2 and len(trames(csvs()[1])) >= 2)
    window.actionStop.trigger()
    assert wait(qapp, lambda: not ctrl.acq_ctrl.running)
    second = [p for p in csvs() if p != first][0]
    assert min(trames(second)) > max(trames(first))      # numérotation continue
    assert len(trames(first)) == n                       # premier fichier intact
    assert window.recordLabel.text() == "" and window.actionRecord.isChecked()


def test_record_failure_unchecks_button(setup, tmp_path, monkeypatch):
    qapp, sim, window, ctrl = setup
    warnings = []
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning",
                        lambda *args: warnings.append(args[2]))
    blocker = tmp_path / "fichier"
    blocker.write_text("x")
    ctrl.config_ctrl.p("Enregistrement", "Dossier").setValue(str(blocker / "sous_dossier"))
    window.actionRecord.setChecked(True)
    window.actionStart.trigger()
    assert wait(qapp, lambda: warnings)
    assert "Enregistrement impossible" in warnings[0]
    assert not window.actionRecord.isChecked()
    assert ctrl.acq_ctrl.running                  # l'acquisition continue sans enregistrer
    window.actionStop.trigger()
    assert wait(qapp, lambda: not ctrl.acq_ctrl.running)


def test_default_record_dir(qapp):
    from controller.main_controller import default_record_dir, resolve_record_dir
    assert resolve_record_dir(LoggerConfig(record_dir=".")).record_dir == default_record_dir()
    assert os.path.isabs(resolve_record_dir(LoggerConfig(record_dir="rel")).record_dir)


def _fill_buffer(qapp, window, ctrl, n):
    window.actionStart.trigger()
    assert wait(qapp, lambda: len(ctrl.buffer_ctrl.buffer) >= n)
    window.actionStop.trigger()
    assert wait(qapp, lambda: not ctrl.acq_ctrl.running)


def test_buffer_navigation(setup):
    qapp, sim, window, ctrl = setup
    buf = ctrl.buffer_ctrl
    ctrl.config_ctrl.p("Mémoire tampon", "Trames gardées").setValue(6)
    assert "Mo" in ctrl.config_ctrl.p("Mémoire tampon", "Mémoire nécessaire").value()
    window.actionStart.trigger()
    assert wait(qapp, lambda: len(buf.buffer) == 6 and buf.buffer[0].index > 1)
    assert window.framesList.count() == 6            # anneau : les plus anciennes sortent
    assert [buf.buffer[i].index for i in range(6)] == [
        int(window.framesList.item(i).text().split()[1]) for i in range(6)]
    assert not window.framesList.item(0).icon().isNull()

    # clic sur une trame : relecture, le direct continue de remplir la mémoire tampon
    window.framesList.setCurrentRow(2)
    chosen = buf.reviewing
    assert chosen is buf.buffer[2]
    wait(qapp, lambda: False, 0.3)
    assert ctrl.graph_ctrl.frame is chosen
    assert "mémoire tampon" in ctrl.graph_ctrl.analog_plot.titleLabel.text
    assert "Relecture" in window.bufferLabel.text()
    assert buf.buffer.latest.index > chosen.index
    # sortie de l'anneau (6 trames) pendant la relecture : toujours affichée, signalée
    assert wait(qapp, lambda: buf.buffer.position(chosen) == -1)
    wait(qapp, lambda: False, 0.1)
    assert buf.reviewing is chosen and ctrl.graph_ctrl.frame is chosen
    assert "n'est plus en mémoire tampon" in window.bufferLabel.text()
    window.framesList.setCurrentRow(2)
    chosen = buf.reviewing

    # navigation clavier : Alt+← / Alt+→ / Alt+Fin
    window.actionStop.trigger()
    assert wait(qapp, lambda: not ctrl.acq_ctrl.running)
    window.actionPrevFrame.trigger()
    assert ctrl.graph_ctrl.frame is buf.buffer[buf.buffer.position(chosen) - 1] or \
        buf.buffer.position(chosen) <= 0
    pos = buf.buffer.position(buf.reviewing)
    window.actionNextFrame.trigger()
    assert buf.buffer.position(buf.reviewing) == pos + 1
    window.actionLiveFrame.trigger()
    assert buf.live and not window.actionLiveFrame.isEnabled()
    wait(qapp, lambda: False, 0.1)
    assert ctrl.graph_ctrl.frame is buf.buffer.latest
    # depuis le direct, Alt+← remonte à l'avant-dernière trame
    window.actionPrevFrame.trigger()
    assert buf.reviewing is buf.buffer[len(buf.buffer) - 2]
    window.tree_tabs.setCurrentIndex(1)
    wait(qapp, lambda: False, 0.1)
    assert "Trame %d  —  mémoire tampon" % buf.reviewing.index in \
        ctrl.graph_ctrl.analog_plot.titleLabel.text
    window.grab().save(str(SHOTS / "logger_buffer.png"))

    # mémoire réduite : les plus anciennes sont retirées de la liste
    ctrl.config_ctrl.p("Mémoire tampon", "Trames gardées").setValue(2)
    assert len(buf.buffer) == 2 and window.framesList.count() == 2


def test_save_buffer_single_file(setup, tmp_path, monkeypatch):
    qapp, sim, window, ctrl = setup
    _fill_buffer(qapp, window, ctrl, 4)
    buf = ctrl.buffer_ctrl
    target = tmp_path / "tampon.csv"
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName",
                        lambda *a, **k: (str(target), "CSV (*.csv)"))
    assert "non enregistrée" in window.bufferLabel.text()
    window.actionSaveBuffer.trigger()
    table = np.loadtxt(target, delimiter=",", skiprows=1)
    assert list(np.unique(table[:, 0])) == [f.index for f in buf.buffer]
    assert target.with_suffix(".json").exists()
    assert buf.buffer.unsaved() == [] and "✓" in window.framesList.item(0).text()
    assert "non enregistrée" not in window.bufferLabel.text()
    # sélection seulement (menu contextuel de la liste)
    window.framesList.item(1).setSelected(True)
    window.framesList.item(2).setSelected(True)
    target = tmp_path / "selection.npz"
    buf.save_selection_action.trigger()
    assert list(np.load(target)["trame"]) == [buf.buffer[1].index, buf.buffer[2].index]


def test_quit_asks_to_save_unsaved_frames(setup, monkeypatch):
    qapp, sim, window, ctrl = setup
    _fill_buffer(qapp, window, ctrl, 2)
    buf = ctrl.buffer_ctrl
    asked = []
    answer = {"value": "cancel"}
    monkeypatch.setattr(buf, "_ask", lambda text: asked.append(text) or answer["value"])
    window.close_guard = buf.confirm_quit
    assert not window.close()                       # Annuler : la fenêtre reste ouverte
    assert window.isVisible() and "quitter" in asked[0]
    answer["value"] = "discard"
    assert window.close()                           # Ne pas enregistrer : fermeture


def test_new_channel_layout_asks_before_clearing_buffer(setup, monkeypatch):
    qapp, sim, window, ctrl = setup
    _fill_buffer(qapp, window, ctrl, 2)
    buf = ctrl.buffer_ctrl
    n = len(buf.buffer)
    monkeypatch.setattr(buf, "_ask", lambda text: "cancel")
    ctrl.config_ctrl.p("Voies", "Voie 2").setValue(7)
    window.actionStart.trigger()                    # annulé : rien ne démarre
    assert not ctrl.acq_ctrl.running and len(buf.buffer) == n
    # relire une trame de l'ancienne configuration remet l'affichage à cette configuration
    window.framesList.setCurrentRow(0)
    assert ctrl.graph_ctrl.cfg.signals == [1, 4, 6, 15]
    monkeypatch.setattr(buf, "_ask", lambda text: "discard")
    ctrl.config_ctrl.p("Voies", "Voie 2").setValue(7)
    window.actionStart.trigger()
    assert wait(qapp, lambda: len(buf.buffer) >= 1 and buf.buffer.cfg.signals == [1, 7, 6, 15])
    window.actionStop.trigger()
    assert wait(qapp, lambda: not ctrl.acq_ctrl.running)


def test_fft_frequency_axis_log_or_linear(setup, tmp_path):
    """Axe des fréquences : arbre, menu contextuel et Log X de pyqtgraph synchronisés."""
    from controller.fft_controller import FFTController, SETTINGS_KEY
    from model.protocol import encode_payload, make_frame
    qapp, sim, window, ctrl = setup
    fft = ctrl.fft_ctrl
    ctrl.config_ctrl.p("Échantillonnage", "Diviseur").setValue(500)          # 50 kHz
    cfg = ctrl.config_ctrl.to_config()
    window.actionFFT.setChecked(True)
    n = cfg.samples_per_channel
    t = np.arange(n) / cfg.sample_rate
    raw = np.zeros((n, 4), dtype=np.int16)
    raw[:, 0] = 8000 * np.sin(2 * np.pi * 100 * t) + 2000 * np.sin(2 * np.pi * 3000 * t)
    ctrl.fft_ctrl.show_frame(make_frame(encode_payload(raw), cfg, 1))
    wait(qapp, lambda: False, 0.1)
    peaks_lin = fft.peak_markers.getData()[0].copy()
    assert abs(peaks_lin[0] - 100) < 1

    # arbre des paramètres
    fft.p("Axe des fréquences").setValue("Logarithmique")
    wait(qapp, lambda: False, 0.1)
    assert fft.log_x and fft.log_action.isChecked() and fft.plot.ctrl.logXCheck.isChecked()
    assert fft.curves[1].opts["logMode"][0]
    lo, hi = fft.plot.vb.viewRange()[0]
    df = cfg.sample_rate / n
    assert lo == pytest.approx(np.log10(df), abs=0.01)
    assert hi == pytest.approx(np.log10(cfg.sample_rate / 2), abs=0.01)
    np.testing.assert_allclose(fft.peak_markers.getData()[0], np.log10(peaks_lin), rtol=1e-6)
    axis = fft.plot.getAxis("bottom")
    assert axis.tickStrings([2.0, 3.0], 1, 1.0) == ["100 Hz", "1 kHz"]
    assert "log" in axis.labelText
    window.fftgraph.grab().save(str(SHOTS / "logger_fft_log.png"))

    # menu contextuel du spectre
    fft.log_action.trigger()
    assert not fft.log_x and fft.p("Axe des fréquences").value() == "Linéaire"
    assert not fft.curves[1].opts["logMode"][0]
    assert fft.plot.vb.viewRange()[0][1] == pytest.approx(cfg.sample_rate / 2)
    # case Log X de pyqtgraph (Plot Options > Transforms)
    fft.plot.ctrl.logXCheck.setChecked(True)
    assert fft.log_x and fft.log_action.isChecked()
    assert fft.plot.vb.viewRange()[0][1] == pytest.approx(np.log10(cfg.sample_rate / 2), abs=0.01)
    assert not fft.plot.ctrl.logYCheck.isEnabled()

    # nouvelle acquisition (reconfiguration) : la plage reste en échelle log
    window.actionStart.trigger()
    assert wait(qapp, lambda: fft.amp is not None and ctrl.acq_ctrl.running)
    window.actionStop.trigger()
    assert wait(qapp, lambda: not ctrl.acq_ctrl.running)
    assert fft.plot.vb.viewRange()[0][1] < 10                       # log10(Hz), pas des Hz

    # choix mémorisé d'une session à l'autre
    settings = QtCore.QSettings(str(tmp_path / "s.ini"), QtCore.QSettings.Format.IniFormat)
    settings.setValue(SETTINGS_KEY, "Logarithmique")
    from pyqtgraph.parametertree import ParameterTree
    import pyqtgraph as pg
    other = FFTController(pg.GraphicsLayoutWidget(), ParameterTree(), settings)
    assert other.log_x and other.plot.ctrl.logXCheck.isChecked()
    other.set_log_x(False)
    assert settings.value(SETTINGS_KEY) == "Linéaire"


def test_math_channels_live(setup):
    """Voies calculées : panneau, arborescence, curseurs, erreurs, configuration."""
    qapp, sim, window, ctrl = setup
    math = ctrl.math_ctrl
    assert not window.mathgraph.isVisible()                # aucune voie calculée
    math.add()
    group = math._groups()[0]
    assert group.child("Formule").value() == "[I_HV]"      # première voie proposée
    group.child("Nom").setValue("P")
    group.child("Formule").setValue("[I_HV]*[V_PH1_INV2]")
    assert group.child("État").value() == "✓ V²"
    assert window.mathgraph.isVisible()
    assert "[V_PH1_INV1_RMS]" in math.params.child("Voies et fonctions").value()

    window.actionStart.trigger()
    assert wait(qapp, lambda: ctrl.graph_ctrl.frame is not None)
    wait(qapp, lambda: False, 0.2)
    window.actionPause.setChecked(True)                    # trame figée pour comparer
    wait(qapp, lambda: False, 0.1)
    frame = ctrl.graph_ctrl.frame
    x, y = ctrl.graph_ctrl.curves[("M", "P")].getData()
    np.testing.assert_allclose(y, frame.analog[:, 0] * frame.analog[:, 1])
    # arborescence : groupe Voies calculées, valeur sous le curseur
    assert ("M", "P") in ctrl.tree_ctrl.items
    assert ctrl.tree_ctrl.items[("M", "P")][1].text() != ""
    # curseurs verticaux : Δ de la voie calculée
    ctrl.cursor_ctrl.set_type("Verticaux")
    assert ctrl.cursor_ctrl.v_lines["math"][0] in ctrl.graph_ctrl.math_plot.items
    i1, i2 = 100, 900
    ctrl.cursor_ctrl.set_vertical(i1 / frame.sample_rate, i2 / frame.sample_rate)
    expected = y[i2] - y[i1]
    assert float(ctrl.tree_ctrl.items[("M", "P")][3].text()) == pytest.approx(expected, rel=1e-4)

    # deuxième voie : réutilise la première, modifiée en direct
    math.add()
    second = math._groups()[1]
    name = second.child("Nom").value()
    assert name == "M1"                                    # premier nom libre
    second.child("Formule").setValue("rms([P])")
    wait(qapp, lambda: False, 0.1)
    assert ctrl.graph_ctrl.curves[("M", name)].getData()[1][0] == pytest.approx(
        np.sqrt(np.mean(y ** 2)), rel=1e-6)
    # formule invalide : signalée, non tracée
    second.child("Formule").setValue("[P]*")
    assert second.child("État").value().startswith("⚠") and ("M", name) not in ctrl.graph_ctrl.curves
    # erreur de calcul sur la trame
    second.child("Formule").setValue("1/0")
    wait(qapp, lambda: False, 0.1)
    ctrl.graph_ctrl.show_frame(frame)
    wait(qapp, lambda: False, 0.1)
    assert "Division by zero" in second.child("État").value()
    window.grab().save(str(SHOTS / "logger_math.png"))
    window.actionPause.setChecked(False)
    window.actionStop.trigger()
    assert wait(qapp, lambda: not ctrl.acq_ctrl.running)

    # gardées dans la configuration (enregistrée en JSON, relue au démarrage)
    saved = ctrl.config_ctrl.read_tree().math_channels
    assert saved[0] == {"name": "P", "formula": "[I_HV]*[V_PH1_INV2]", "unit": "",
                        "enabled": True}
    math.remove(math._groups()[0])
    assert ("M", "P") not in ctrl.graph_ctrl.curves
    math.remove(math._groups()[0])
    assert not window.mathgraph.isVisible()


def test_math_channels_loaded_with_config(setup, tmp_path):
    qapp, sim, window, ctrl = setup
    cfg = ctrl.config_ctrl.read_tree()
    cfg.math_channels = [{"name": "Somme", "formula": "A1+A4", "unit": "V", "enabled": True}]
    path = tmp_path / "cfg.json"
    cfg.save(str(path))
    ctrl.load_config(str(path))
    group = ctrl.math_ctrl._groups()[0]
    assert group.child("Formule").value() == "A1+A4" and group.child("État").value() == "✓ V"
    assert ("M", "Somme") in ctrl.graph_ctrl.curves and window.mathgraph.isVisible()
