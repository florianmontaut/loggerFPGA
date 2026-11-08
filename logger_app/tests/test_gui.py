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


def _recording(tmp_path, signals, indexes, name="enr.csv"):
    from model.protocol import encode_payload, make_frame
    from model.recorder import save_frames
    cfg = LoggerConfig(signals=signals, units=["V"] * 15)
    n = cfg.samples_per_channel
    rng = np.random.default_rng(3)
    frames = [make_frame(encode_payload(rng.integers(-9000, 9000, (n, len(signals)))
                                        .astype(np.int16)), cfg, i, 1_700_000_000.0 + i)
              for i in indexes]
    return save_frames(frames, cfg, str(tmp_path / name)), frames


def test_open_recording(setup, tmp_path, monkeypatch):
    qapp, sim, window, ctrl = setup
    buf = ctrl.buffer_ctrl
    path, original = _recording(tmp_path, [1, 4, 6, 15], [21, 22, 23])
    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileNames",
                        lambda *a, **k: ([path], ""))
    window.actionOpenRecording.trigger()
    assert [f.index for f in buf.buffer] == [21, 22, 23]
    assert window.framesList.count() == 3 and window.tree_tabs.currentIndex() == 1
    assert buf.reviewing is buf.buffer[0]
    wait(qapp, lambda: False, 0.1)
    np.testing.assert_allclose(ctrl.graph_ctrl.frame.analog, original[0].analog)
    assert "enr.csv" in ctrl.graph_ctrl.analog_plot.titleLabel.text
    assert "Fichier : enr.csv" in window.bufferLabel.text()
    assert buf.buffer.unsaved() == []                       # déjà sur disque
    assert "3 trame(s) relue(s)" in window.statusBar().currentMessage()
    # navigation et voies calculées sur les trames relues
    window.actionNextFrame.trigger()
    assert buf.reviewing.index == 22
    ctrl.math_ctrl.add()
    ctrl.math_ctrl._groups()[0].child("Formule").setValue("[I_HV]*2")
    wait(qapp, lambda: False, 0.1)
    np.testing.assert_allclose(ctrl.graph_ctrl.curves[("M", "M1")].getData()[1],
                               original[1].analog[:, 0] * 2)
    window.grab().save(str(SHOTS / "logger_open_recording.png"))
    # l'acquisition suivante numérote après les trames du fichier
    assert ctrl.acq_ctrl.next_index == 24


def test_open_recording_other_layout_and_capacity(setup, tmp_path):
    qapp, sim, window, ctrl = setup
    buf = ctrl.buffer_ctrl
    ctrl.config_ctrl.p("Mémoire tampon", "Trames gardées").setValue(4)
    path, _ = _recording(tmp_path, [2, 15], range(1, 11))
    assert ctrl.open_recording(path)
    assert len(buf.buffer) == 10                            # mémoire tampon agrandie
    assert ctrl.config_ctrl.p("Mémoire tampon", "Trames gardées").value() == 10
    assert ctrl.graph_ctrl.cfg.signals == [2, 15]           # affichage à la config du fichier
    assert ("A", 2) in ctrl.tree_ctrl.items and ("A", 1) not in ctrl.tree_ctrl.items
    # nouvelle acquisition (autre disposition) : trames du fichier déjà enregistrées,
    # la mémoire tampon est vidée sans question
    window.actionStart.trigger()
    assert wait(qapp, lambda: len(buf.buffer) >= 1 and buf.buffer.cfg.signals == [1, 4, 6, 15])
    assert buf.buffer[0].index == 11
    window.actionStop.trigger()
    assert wait(qapp, lambda: not ctrl.acq_ctrl.running)


def test_open_recording_guards(setup, tmp_path, monkeypatch):
    qapp, sim, window, ctrl = setup
    buf = ctrl.buffer_ctrl
    shown = []
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", lambda *a: shown.append(a[2]))
    monkeypatch.setattr(QtWidgets.QMessageBox, "information", lambda *a: shown.append(a[2]))
    path, _ = _recording(tmp_path, [1, 4, 6, 15], [1, 2])
    # pendant l'acquisition : refusé
    window.actionStart.trigger()
    assert wait(qapp, lambda: len(buf.buffer) >= 2)
    window.actionOpenRecording.trigger()
    assert "Arrêtez l'acquisition" in shown[-1]
    window.actionStop.trigger()
    assert wait(qapp, lambda: not ctrl.acq_ctrl.running)
    # trames non enregistrées : Annuler -> rien n'est chargé
    monkeypatch.setattr(buf, "_ask", lambda text: "cancel")
    before = [f.index for f in buf.buffer]
    assert not ctrl.open_recording(path)
    assert [f.index for f in buf.buffer] == before
    # fichier invalide : message, sans question sur la mémoire tampon, qui reste intacte
    asked = []
    monkeypatch.setattr(buf, "_ask", lambda text: asked.append(text) or "discard")
    bad = tmp_path / "autre.csv"
    bad.write_text("a,b\n1,2\n")
    assert not ctrl.open_recording(str(bad))
    assert "pas un enregistrement" in shown[-1] and asked == []
    assert [f.index for f in buf.buffer] == before


def test_longer_frame_not_clipped_to_previous_duration(setup):
    """Diviseur 20 -> 500 : l'axe des temps couvre toute la nouvelle trame."""
    qapp, sim, window, ctrl = setup
    plot = ctrl.graph_ctrl.analog_plot
    assert plot.vb.viewRange()[0][1] == pytest.approx(4096 / 1.25e6)
    ctrl.config_ctrl.p("Échantillonnage", "Diviseur").setValue(500)
    assert plot.vb.viewRange()[0][1] == pytest.approx(4096 / 50e3)


# ------------------------------------------------------------------ oscilloscope

def _tek_csv(path, n=120_000, dt=1e-6, t0=-0.01):
    """CSV Tektronix : métadonnées colonnes 0-2, temps, 2 voies (sinus 1 kHz, rampe)."""
    t = t0 + np.arange(n) * dt
    s1 = np.sin(2 * np.pi * 1000 * t)
    s2 = np.linspace(-1, 1, n)
    meta = [('"Record Length"', f"{n}", '"Points"'), ('"Sample Interval"', f"{dt:.8e}", "s"),
            ('"Trigger Point"', "10000", '"Samples"'), ('"Trigger Time"', "0", "s")]
    with open(path, "w") as f:
        for i in range(n):
            m = meta[i] if i < len(meta) else ("", "", "")
            f.write(f"{m[0]},{m[1]},{m[2]},{t[i]:.8e},{s1[i]:.8e},{s2[i]:.8e}\n")
    return str(path), t, s1, s2


def _open_scope(qapp, ctrl, paths):
    assert ctrl.open_files(paths)
    assert ctrl.scope_ctrl.wait_import()
    assert wait(qapp, lambda: ctrl.scope_ctrl.active and ctrl.graph_ctrl.frame is not None)
    wait(qapp, lambda: False, 0.2)
    _no_progress_dialog(ctrl)


def _no_progress_dialog(ctrl):
    from controller.scope_controller import ProgressDialog
    assert ctrl.scope_ctrl.progress_dialog is None
    assert not [d for d in ctrl.view.findChildren(ProgressDialog) if d.isVisible()]


def test_scope_record_mode(setup, tmp_path):
    qapp, sim, window, ctrl = setup
    scope = ctrl.scope_ctrl
    scope.max_raw = 20_000                       # enregistrement de 120 000 points
    path, t, s1, s2 = _tek_csv(tmp_path / "dpo.csv")
    window.actionFFT.setChecked(True)
    ctrl.math_ctrl.add()
    ctrl.math_ctrl._groups()[0].child("Formule").setValue("[CH1]*[CH2]")
    _open_scope(qapp, ctrl, [path])
    assert (tmp_path / "dpo.h5").exists()
    assert window.overviewgraph.isVisible() and window.actionCloseScope.isEnabled()
    root = ctrl.tree_ctrl.model.item(0)
    assert root.text() == "dpo.h5" and ("A", 0) in ctrl.tree_ctrl.items
    assert ctrl.tree_ctrl.items[("A", 0)][0].text() == "CH1"
    plot = ctrl.graph_ctrl.analog_plot
    x0, x1 = plot.vb.viewRange()[0]
    assert x0 == pytest.approx(t[0]) and x1 == pytest.approx(t[0] + 120_000e-6)
    # tout l'enregistrement : enveloppe, analyses suspendues
    frame = ctrl.graph_ctrl.frame
    assert frame.meta["envelope"] and "enveloppe" in plot.titleLabel.text
    assert "zoomer" in ctrl.fft_ctrl.plot.titleLabel.text
    assert "zoomer" in ctrl.math_ctrl._groups()[0].child("État").value()
    assert frame.analog[:, 0].max() == pytest.approx(1, abs=1e-3)

    # zoom sur 10 ms : données brutes, mêmes valeurs que le CSV
    plot.setXRange(t[30_000], t[40_000], padding=0)
    assert wait(qapp, lambda: not ctrl.graph_ctrl.frame.meta["envelope"])
    wait(qapp, lambda: False, 0.2)
    frame = ctrl.graph_ctrl.frame
    i0 = int(round((frame.t0 - t[0]) / 1e-6))
    np.testing.assert_allclose(frame.analog[:, 0], s1[i0:i0 + frame.n_samples], atol=1e-6)
    assert scope.region.getRegion()[0] == pytest.approx(t[30_000], abs=1e-6)
    # FFT : 1 kHz ; voie calculée ; curseurs et mesures sur les données brutes
    assert "Spectre" == ctrl.fft_ctrl.plot.titleLabel.text
    assert abs(_peak(ctrl.fft_ctrl) - 1000) < 120
    y = ctrl.graph_ctrl.curves[("M", "M1")].yData        # getData() : rognées à la vue
    np.testing.assert_allclose(y, frame.analog[:, 0] * frame.analog[:, 1], atol=1e-9)
    ctrl.cursor_ctrl.set_type("Verticaux")
    ctrl.cursor_ctrl.set_vertical(t[31_000], t[31_250])            # un quart de période
    assert ctrl.cursor_ctrl.p("Verticaux", "Δt").value() == "250 µs"
    assert ctrl.cursor_ctrl.p("Mesures").opts["visible"]
    values = ctrl.graph_ctrl.values_at(t[31_000])
    assert values[("A", 0)] == pytest.approx(s1[31_000], abs=1e-6)
    window.grab().save(str(SHOTS / "logger_scope.png"))

    # vue d'ensemble : déplacer la zone déplace le graphique
    scope.region.setRegion((t[100_000], t[110_000]))
    assert plot.vb.viewRange()[0][0] == pytest.approx(t[100_000], abs=1e-6)

    # fermeture : retour à l'affichage du logger
    window.actionCloseScope.trigger()
    assert not scope.active and not window.overviewgraph.isVisible()
    assert ctrl.graph_ctrl.cfg.signals == [1, 4, 6, 15]


def _peak(fft):
    from model import spectrum
    j = 0
    return spectrum.find_peaks(fft.freq, fft.amp[:, j], 1, fft.p("Fenêtre").value(),
                               min_frequency=fft.freq[1])[0].frequency


def test_scope_reuse_h5_and_back_to_logger(setup, tmp_path, monkeypatch):
    qapp, sim, window, ctrl = setup
    monkeypatch.setattr(ctrl, "_ask_add_or_replace", lambda paths: "replace")
    path, *_ = _tek_csv(tmp_path / "dpo.csv", n=20_000)
    _open_scope(qapp, ctrl, [path])
    ctrl.scope_ctrl.close()
    _open_scope(qapp, ctrl, [path])                              # .h5 plus récent : réutilisé
    assert "réutilisée" in window.statusBar().currentMessage()
    _open_scope(qapp, ctrl, [str(tmp_path / "dpo.h5")])           # ouverture directe du .h5
    assert ctrl.scope_ctrl.record.names == ["CH1", "CH2"]
    # démarrer une acquisition referme l'enregistrement
    window.actionStart.trigger()
    assert not ctrl.scope_ctrl.active
    assert wait(qapp, lambda: ctrl.graph_ctrl.frame is not None
                and ctrl.graph_ctrl.frame.signals == [1, 4, 6, 15])
    window.actionStop.trigger()
    assert wait(qapp, lambda: not ctrl.acq_ctrl.running)
    # trame de la mémoire tampon choisie pendant l'affichage d'un enregistrement
    _open_scope(qapp, ctrl, [path])
    window.framesList.setCurrentRow(0)
    assert not ctrl.scope_ctrl.active and ctrl.graph_ctrl.cfg.signals == [1, 4, 6, 15]


def test_scope_invalid_files(setup, tmp_path, monkeypatch):
    qapp, sim, window, ctrl = setup
    shown = []
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", lambda *a: shown.append(a[2]))
    bad = tmp_path / "bad.h5"
    bad.write_text("pas du HDF5")
    assert not ctrl.open_files([str(bad)])
    assert "illisible" in shown[-1] and not ctrl.scope_ctrl.active
    a, *_ = _tek_csv(tmp_path / "a.csv", n=5000)
    logger_csv = tmp_path / "logger.csv"
    logger_csv.write_text("trame,temps_s,V\n1,0,2\n")
    assert not ctrl.open_files([a, str(logger_csv)])               # mélange refusé
    assert "Plusieurs fichiers" in shown[-1]


def _tek_channel(path, values, dt=1e-6, t0=-0.01):
    """CSV Tektronix d'une seule voie (un fichier par voie, comme le DPO7054)."""
    n = len(values)
    t = t0 + np.arange(n) * dt
    meta = [('"Record Length"', f"{n}", '"Points"'), ('"Sample Interval"', f"{dt:.8e}", "s")]
    with open(path, "w") as f:
        for i in range(n):
            m = meta[i] if i < len(meta) else ("", "", "")
            f.write(f"{m[0]},{m[1]},{m[2]},{t[i]:.8e},{values[i]:.8e}\n")
    return str(path)


def test_scope_one_csv_per_channel(setup, tmp_path, monkeypatch):
    qapp, sim, window, ctrl = setup
    scope = ctrl.scope_ctrl
    n = 40_000
    k = np.arange(n)
    ch1 = _tek_channel(tmp_path / "tek0000CH1.csv", np.sin(k / 300))
    ch2 = _tek_channel(tmp_path / "tek0000CH2.csv", np.cos(k / 300))
    ch3 = _tek_channel(tmp_path / "tek0000CH3.csv", k / n)
    ch4 = _tek_channel(tmp_path / "tek0000CH4.csv", -k / n)

    # plusieurs fichiers choisis ensemble (Ctrl+clic)
    _open_scope(qapp, ctrl, [ch1, ch2])
    assert scope.record.names == ["CH1", "CH2"]

    # cumul : nouveaux fichiers ouverts sur l'enregistrement affiché -> « Ajouter »
    plot = ctrl.graph_ctrl.analog_plot
    plot.setXRange(-0.01 + 10_000e-6, -0.01 + 12_000e-6, padding=0)
    wait(qapp, lambda: False, 0.2)
    view = plot.vb.viewRange()[0]
    asked = []
    monkeypatch.setattr(ctrl, "_ask_add_or_replace", lambda paths: asked.append(paths) or "add")
    assert ctrl.open_files([ch3])
    assert scope.wait_import()
    assert wait(qapp, lambda: scope.active and scope.record.names == ["CH1", "CH2", "CH3"])
    wait(qapp, lambda: False, 0.2)
    assert asked == [[ch3]]
    assert plot.vb.viewRange()[0] == pytest.approx(view, abs=1e-9)   # même portion
    assert ("A", 2) in ctrl.tree_ctrl.items
    assert ctrl.tree_ctrl.items[("A", 2)][0].text() == "CH3"
    frame = ctrl.graph_ctrl.frame
    i0 = int(round((frame.t0 + 0.01) / 1e-6))
    np.testing.assert_allclose(frame.analog[:, 2], (k / n)[i0:i0 + frame.n_samples], atol=1e-6)
    assert "CH3" in window.statusBar().currentMessage()

    # menu « Ajouter des voies à l'enregistrement... »
    assert window.actionAddScopeChannels.isEnabled()
    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileNames", lambda *a, **k: ([ch4], ""))
    window.actionAddScopeChannels.trigger()
    assert scope.wait_import()
    assert wait(qapp, lambda: scope.active and len(scope.record.names) == 4)
    assert scope.record.names[-1] == "CH4"
    wait(qapp, lambda: False, 0.1)
    _no_progress_dialog(ctrl)
    window.grab().save(str(SHOTS / "logger_scope_4_voies.png"))

    # « Remplacer » : nouvel enregistrement
    monkeypatch.setattr(ctrl, "_ask_add_or_replace", lambda paths: "replace")
    _open_scope(qapp, ctrl, [ch3])
    assert scope.record.names == ["CH1"]                   # fichier seul : CH1


def test_scope_add_refused_keeps_record(setup, tmp_path, monkeypatch):
    qapp, sim, window, ctrl = setup
    scope = ctrl.scope_ctrl
    shown = []
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", lambda *a: shown.append(a[2]))
    ch1 = _tek_channel(tmp_path / "tek0000CH1.csv", np.zeros(20_000))
    import h5py
    other = str(tmp_path / "inconnu.h5")                   # HDF5 non reconnu
    with h5py.File(other, "w") as h5:
        h5.create_dataset("x", data=np.zeros(10))
    _open_scope(qapp, ctrl, [ch1])
    monkeypatch.setattr(ctrl, "_ask_add_or_replace", lambda paths: "add")
    assert ctrl.open_files([other])
    assert scope.wait_import()
    assert wait(qapp, lambda: shown and scope.active)
    assert "workspace" in shown[-1]
    assert scope.record.names == ["CH1"]                   # enregistrement rouvert, intact
    # « Annuler » : rien ne change
    monkeypatch.setattr(ctrl, "_ask_add_or_replace", lambda paths: "cancel")
    assert not ctrl.open_files([other])
    assert scope.record.names == ["CH1"]


def test_scope_picoscope_and_timebases(setup, tmp_path, monkeypatch):
    """Export PicoScope (forme d'onde choisie), voies de bases de temps différentes."""
    from pico_files import pico_h5
    qapp, sim, window, ctrl = setup
    scope = ctrl.scope_ctrl
    n = 100_000
    t = np.arange(n) * 1e-7
    a = np.sin(2 * np.pi * 10e3 * t)
    b = np.arange(30_000) / 1e3                            # rampe, 2 x plus lente, décalée
    path = pico_h5(tmp_path / "capture.h5", {
        "A": [(np.zeros(n), 0.0, 1e-7), (a, 0.0, 1e-7)],
        "B": [(np.zeros(n), 0.0, 1e-7), (b, 2e-3, 2e-7)]})
    asked = []
    monkeypatch.setattr(scope, "choose_waveform", lambda p, count: asked.append(count) or 1)
    _open_scope(qapp, ctrl, [path])
    assert asked == [2]
    assert scope.record.names == ["A", "B"] and not scope.record.uniform
    assert scope.record.path.endswith("capture_onde2.workspace.h5")
    frame = ctrl.graph_ctrl.frame
    assert frame.meta["gaps"]
    assert ctrl.graph_ctrl.curves[("A", 1)].opts["connect"] == "finite"
    tips = ctrl.tree_ctrl.items[("A", 1)][0].toolTip()
    assert "5 MHz" in tips and "30 000 points" in tips
    assert scope.cfg.units[0] == "V"
    # zoom sur les deux voies : données brutes, grille de A, B interpolée
    ctrl.graph_ctrl.analog_plot.setXRange(2.0e-3, 2.1e-3, padding=0)
    assert wait(qapp, lambda: not ctrl.graph_ctrl.frame.meta["envelope"]
                and ctrl.graph_ctrl.frame.n_samples < 2000)
    frame = ctrl.graph_ctrl.frame
    assert frame.sample_rate == pytest.approx(1e7)
    assert np.isfinite(frame.analog).all()
    # zone (FFT) : grille commune ; motif : échantillons propres de B
    data, fs, _ = scope.read_zone(2.0e-3, 2.1e-3)
    assert fs == pytest.approx(1e7) and data.shape[1] == 2
    zone = scope.read_zone_frame(2.0e-3, 2.1e-3)
    tb, yb = zone.meta["native"][1]
    assert np.diff(tb) == pytest.approx(np.full(tb.size - 1, 2e-7))
    np.testing.assert_allclose(yb[:3], b[:3], atol=1e-6)
    # rouvrir : conversion réutilisée, forme d'onde redemandée
    scope.close()
    _open_scope(qapp, ctrl, [path])
    assert asked == [2, 2]
    assert "réutilisée" in window.statusBar().currentMessage() or scope.active
    # forme d'onde refusée (Annuler) : rien n'est ouvert
    scope.close()
    monkeypatch.setattr(scope, "choose_waveform", lambda p, count: None)
    assert not ctrl.open_files([path])
    assert not scope.active
    # ajout d'un CSV Tektronix d'un autre échantillonnage
    monkeypatch.setattr(scope, "choose_waveform", lambda p, count: 1)
    _open_scope(qapp, ctrl, [path])
    ch = _tek_channel(tmp_path / "tek0000CH3.csv", np.ones(5000), dt=1e-6, t0=0.0)
    monkeypatch.setattr(ctrl, "_ask_add_or_replace", lambda paths: "add")
    assert ctrl.open_files([ch])
    assert scope.wait_import()
    assert wait(qapp, lambda: scope.active and len(scope.record.names) == 3)
    wait(qapp, lambda: False, 0.2)
    assert ctrl.tree_ctrl.items[("A", 2)][1].text() == "—"     # CH3 finit avant la fin
    window.grab().save(str(SHOTS / "logger_picoscope.png"))


def test_progress_dialog_cancel(setup, tmp_path):
    """Annuler (bouton ou Échap) pendant la conversion : rien n'est ouvert."""
    qapp, sim, window, ctrl = setup
    scope = ctrl.scope_ctrl
    path = _tek_channel(tmp_path / "long.csv", np.zeros(300_000))
    assert ctrl.open_files([path])
    dialog = scope.progress_dialog
    assert dialog is not None and dialog.isVisible()
    dialog.reject()                                         # Échap
    assert scope.wait_import()
    assert wait(qapp, lambda: scope.progress_dialog is None)
    assert not scope.active and not (tmp_path / "long.h5").exists()
    assert "annulée" in window.statusBar().currentMessage()


# ------------------------------------------------------------------ fichiers récents

def test_recent_files_and_last_directory(setup, tmp_path, monkeypatch):
    qapp, sim, window, ctrl = setup
    recent = ctrl.recent_ctrl
    seen_dirs = []

    def chooser(result):
        def choose(parent, caption, directory, *args, **kwargs):
            seen_dirs.append(directory)
            return result
        return choose

    # enregistrement du logger rouvert depuis un dossier : il devient le dernier répertoire
    logger_dir = tmp_path / "logger"
    logger_dir.mkdir()
    path, _ = _recording(logger_dir, [1, 4, 6, 15], [1, 2])
    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileNames", chooser(([path], "")))
    window.actionOpenRecording.trigger()
    assert recent.entries[0] == {"kind": "logger", "paths": [path]}
    assert recent.last_dir == str(logger_dir)

    # enregistrement d'oscilloscope : le .h5 est retenu, le dossier des CSV est visité
    scope_dir = tmp_path / "dpo"
    scope_dir.mkdir()
    ch1 = _tek_channel(scope_dir / "tek0000CH1.csv", np.zeros(5000))
    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileNames", chooser(([ch1], "")))
    window.actionOpenRecording.trigger()
    assert ctrl.scope_ctrl.wait_import()
    assert wait(qapp, lambda: ctrl.scope_ctrl.active and recent.entries[0]["kind"] == "scope")
    assert seen_dirs[-1] == str(logger_dir)             # ouverte sur le dernier répertoire
    assert recent.entries[0]["paths"] == [str(scope_dir / "tek0000CH1.h5")]
    assert recent.last_dir == str(scope_dir)

    # ajout de voies depuis un autre dossier : la boîte s'ouvre sur le dernier répertoire
    other_dir = tmp_path / "voie2"
    other_dir.mkdir()
    ch2 = _tek_channel(other_dir / "tek0000CH2.csv", np.ones(5000))
    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileNames", chooser(([ch2], "")))
    window.actionAddScopeChannels.trigger()
    assert seen_dirs[-1] == str(scope_dir)
    assert ctrl.scope_ctrl.wait_import()
    assert wait(qapp, lambda: ctrl.scope_ctrl.active and len(ctrl.scope_ctrl.record.names) == 2)
    assert recent.last_dir == str(other_dir)
    assert len([e for e in recent.entries if e["kind"] == "scope"]) == 1   # pas de doublon

    # configuration : boîte d'ouverture sur le dernier répertoire, entrée « configuration »
    cfg_path = str(other_dir / "banc.json")
    ctrl.config_ctrl.read_tree().save(cfg_path)
    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileName", chooser((cfg_path, "")))
    window.actionLoadConfig.trigger()
    assert seen_dirs[-1] == str(other_dir)
    assert recent.entries[0] == {"kind": "config", "paths": [cfg_path]}

    # menu Fichiers récents : rouvre l'enregistrement du logger (dans la mémoire tampon)
    labels = [a.text() for a in window.menuRecent.actions() if not a.isSeparator()]
    assert labels[:3] == ["&1  banc.json    (configuration)",
                          "&2  tek0000CH1.h5    (oscilloscope)",
                          "&3  enr.csv    (logger)"]
    window.menuRecent.actions()[2].trigger()
    assert not ctrl.scope_ctrl.active
    assert [f.index for f in ctrl.buffer_ctrl.buffer] == [1, 2]
    # rouvert : remonte en tête de liste
    labels = [a.text() for a in window.menuRecent.actions() if not a.isSeparator()]
    assert labels[0] == "&1  enr.csv    (logger)"
    # … puis l'enregistrement d'oscilloscope, avec ses deux voies
    [action] = [a for a in window.menuRecent.actions() if "tek0000CH1.h5" in a.text()]
    action.trigger()
    assert wait(qapp, lambda: ctrl.scope_ctrl.active)
    assert ctrl.scope_ctrl.record.names == ["CH1", "CH2"]


def test_recent_file_missing(setup, tmp_path, monkeypatch):
    qapp, sim, window, ctrl = setup
    shown = []
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", lambda *a: shown.append(a[2]))
    path, _ = _recording(tmp_path, [1, 4, 6, 15], [1])
    assert ctrl.open_recording(path)
    os.remove(path)
    window.menuRecent.actions()[0].trigger()
    assert "introuvable" in shown[-1] and path in shown[-1]
    assert ctrl.recent_ctrl.entries == []


# ------------------------------------------------------------------ FFT sur zone

def _two_tone_frame(cfg, f1=1000.0, f2=5000.0):
    """Trame : f1 dans la première moitié, f2 dans la seconde (voie 1)."""
    from model.protocol import encode_payload, make_frame
    n = cfg.samples_per_channel
    t = np.arange(n) / cfg.sample_rate
    y = np.where(t < t[n // 2], np.sin(2 * np.pi * f1 * t), np.sin(2 * np.pi * f2 * t))
    raw = np.zeros((n, cfg.n_channels), dtype=np.int16)
    raw[:, 0] = (y * 8000).astype(np.int16)
    return make_frame(encode_payload(raw), cfg, 1)


def _fft_peak(fft):
    from model import spectrum
    j = fft.signals.index(1)
    return spectrum.find_peaks(fft.freq, fft.amp[:, j], 1, fft.p("Fenêtre").value(),
                               min_frequency=fft.freq[1])[0].frequency


def test_fft_zone_on_logger_frame(setup):
    qapp, sim, window, ctrl = setup
    ctrl.config_ctrl.p("Échantillonnage", "Diviseur").setValue(500)     # 50 kHz, 81,92 ms
    cfg = ctrl.config_ctrl.to_config()
    fft = ctrl.fft_ctrl
    window.actionFFT.setChecked(True)
    fft.p("Voie analysée").setValue(1)
    frame = _two_tone_frame(cfg)
    ctrl.graph_ctrl.show_frame(frame)
    fft.show_frame(frame)
    half = frame.n_samples / 2 / cfg.sample_rate
    peak = _fft_peak(fft)                                    # trame entière : 2 pics
    assert min(abs(peak - 1000), abs(peak - 5000)) < 100
    assert fft.zone not in ctrl.graph_ctrl.analog_plot.items

    # zone sur la première moitié : 1 kHz seulement
    fft.set_zone(0.05 * half, 0.95 * half)
    assert fft.zone_mode and fft.zone in ctrl.graph_ctrl.analog_plot.items
    assert abs(_fft_peak(fft) - 1000) < 60
    assert "zone" in fft.plot.titleLabel.text and "points" in fft.p("Zone").value()
    n_zone = int(round(0.9 * half * cfg.sample_rate)) + 1
    assert fft._points[1] == pytest.approx(n_zone, abs=2)
    # saisie des bornes dans l'arbre : seconde moitié -> 5 kHz
    fft.p("Début de zone").setValue(1.1 * half)
    fft.p("Fin de zone").setValue(1.9 * half)
    assert fft.zone_range() == pytest.approx((1.1 * half, 1.9 * half))   # zone tout de suite
    assert wait(qapp, lambda: abs(_fft_peak(fft) - 5000) < 60, 2)         # calcul après 100 ms
    # zone déplacée à la souris (signal de pyqtgraph) : recalcul regroupé
    fft.zone.setRegion((0.1 * half, 0.6 * half))
    assert fft.p("Début de zone").value() == pytest.approx(0.1 * half)
    assert wait(qapp, lambda: abs(_fft_peak(fft) - 1000) < 60, 2)
    window.grab().save(str(SHOTS / "logger_fft_zone.png"))
    # zone trop étroite
    fft.set_zone(0.1 * half, 0.1 * half + 5 / cfg.sample_rate)
    assert "trop étroite" in fft.plot.titleLabel.text and fft.amp is None
    # « Zone = portion affichée »
    ctrl.graph_ctrl.analog_plot.setXRange(0.2 * half, 0.4 * half, padding=0)
    fft.p("Zone = portion affichée").activate()
    assert fft.zone_range() == pytest.approx((0.2 * half, 0.4 * half), rel=1e-3)
    # retour à la trame affichée : zone retirée du graphique
    fft.p("Zone de calcul").setValue("Trame affichée")
    assert fft.zone not in ctrl.graph_ctrl.analog_plot.items
    assert fft._points[1] == frame.n_samples
    # FFT désactivée : zone masquée
    fft.p("Zone de calcul").setValue("Zone sélectionnée")
    window.actionFFT.setChecked(False)
    assert fft.zone not in ctrl.graph_ctrl.analog_plot.items


def test_fft_zone_live(setup):
    qapp, sim, window, ctrl = setup
    fft = ctrl.fft_ctrl
    window.actionFFT.setChecked(True)
    cfg = ctrl.config_ctrl.to_config()
    fft.set_zone(0.0, cfg.frame_duration / 4)
    window.actionStart.trigger()
    assert wait(qapp, lambda: fft.amp is not None and ctrl.acq_ctrl.next_index > 3)
    window.actionStop.trigger()
    assert wait(qapp, lambda: not ctrl.acq_ctrl.running)
    assert fft._points[1] == pytest.approx(cfg.samples_per_channel / 4, abs=2)


def test_fft_zone_on_scope_record(setup, tmp_path, monkeypatch):
    """Enregistrement long : FFT de la zone lue dans le fichier, quel que soit le zoom."""
    import controller.scope_controller as scope_module
    qapp, sim, window, ctrl = setup
    n, dt = 120_000, 1e-6
    t = -0.01 + np.arange(n) * dt
    y = np.where(np.arange(n) < n // 2, np.sin(2 * np.pi * 1000 * t), np.sin(2 * np.pi * 3000 * t))
    path = _tek_channel(tmp_path / "tek0000CH1.csv", y)
    ctrl.scope_ctrl.max_raw = 20_000                        # affichage : enveloppe
    window.actionFFT.setChecked(True)
    _open_scope(qapp, ctrl, [path])
    fft = ctrl.fft_ctrl
    assert ctrl.graph_ctrl.frame.meta["envelope"]
    assert "zoomer" in fft.plot.titleLabel.text            # trame affichée : enveloppe
    reads = []
    reader = ctrl.scope_ctrl.read_zone
    monkeypatch.setattr(ctrl.scope_ctrl, "read_zone",
                        lambda a, b: reads.append((a, b)) or reader(a, b))
    fft.p("Voie analysée").setValue(0)
    fft.set_zone(t[70_000], t[110_000])                     # seconde moitié, 40 000 points
    assert ctrl.graph_ctrl.frame.meta["envelope"]          # affichage toujours en enveloppe
    from model import spectrum
    peak = spectrum.find_peaks(fft.freq, fft.amp[:, 0], 1, "hann",
                               min_frequency=fft.freq[1])[0].frequency
    assert abs(peak - 3000) < 40 and fft._points[1] == 40_001
    assert fft.plot.titleLabel.text == "Spectre — zone 40 ms, 40 001 points"
    fft.p("Fréquence max (Hz)").setValue(10_000)
    wait(qapp, lambda: False, 0.15)
    window.grab().save(str(SHOTS / "logger_fft_zone_scope.png"))
    count = len(reads)
    # zoom / déplacement : nouvelles portions affichées, FFT de zone inchangée, pas relue
    ctrl.graph_ctrl.analog_plot.setXRange(t[1000], t[5000], padding=0)
    ctrl.scope_ctrl.reload()
    assert len(reads) == count
    # zone trop large
    monkeypatch.setattr(scope_module, "MAX_FFT_ZONE_POINTS", 10_000)
    fft.set_zone(t[0], t[50_000])
    assert "au plus" in fft.plot.titleLabel.text


def test_fft_zone_recalculation_is_throttled(setup, monkeypatch):
    """Glisser : un seul calcul au relâchement ; sinon un calcul 100 ms après le dernier
    changement ; jamais deux calculs pour la même zone."""
    import time
    qapp, sim, window, ctrl = setup
    ctrl.config_ctrl.p("Échantillonnage", "Diviseur").setValue(500)
    cfg = ctrl.config_ctrl.to_config()
    fft = ctrl.fft_ctrl
    window.actionFFT.setChecked(True)
    frame = _two_tone_frame(cfg)
    ctrl.graph_ctrl.show_frame(frame)
    fft.show_frame(frame)
    fft.set_zone(0.005, 0.02)
    computed = []
    original = fft._compute
    monkeypatch.setattr(fft, "_compute", lambda f: computed.append(fft.zone_range()) or original(f))

    def pump(seconds):
        end = time.time() + seconds
        while time.time() < end:
            qapp.processEvents()
            time.sleep(0.005)

    def drag_region(lo, hi):
        """Ce qu'émet LinearRegionItem.mouseDragEvent pendant un glisser de la zone."""
        fft.zone.blockLineSignal = True
        fft.zone.lines[0].setPos(lo)
        fft.zone.lines[1].setPos(hi)
        fft.zone.blockLineSignal = False
        fft.zone.sigRegionChanged.emit(fft.zone)

    # glisser de la zone entière, bouton enfoncé pendant 1 s avec des pauses de 200 ms
    fft.zone.moving = True
    for k in range(5):
        drag_region(0.005 + 0.002 * k, 0.02 + 0.002 * k)
        pump(0.2)
    assert computed == []                                  # rien pendant le glisser
    assert fft.p("Début de zone").value() == pytest.approx(0.013)   # bornes suivies
    fft.zone.sigRegionChangeFinished.emit(fft.zone)        # (ignoré tant que bouton enfoncé)
    assert computed == []
    fft.zone.moving = False                                # relâchement (mouseDragEvent)
    fft.zone.sigRegionChangeFinished.emit(fft.zone)
    pump(0.25)
    assert computed == [pytest.approx((0.013, 0.028))]

    # glisser d'une borne (InfiniteLine.mouseDragEvent) : idem
    computed.clear()
    line = fft.zone.lines[1]
    line.moving = True
    for k in range(4):
        line.setPos(0.03 + 0.002 * k)
        pump(0.15)
    assert computed == []
    line.moving = False
    line.sigPositionChangeFinished.emit(line)
    pump(0.25)
    assert computed == [pytest.approx((0.013, 0.036))]
    # second signal de fin pour la même zone : pas de second calcul
    fft.zone.sigRegionChangeFinished.emit(fft.zone)
    pump(0.15)
    assert len(computed) == 1

    # saisie des bornes au clavier, caractère par caractère : un seul calcul
    computed.clear()
    for value in (0.0, 0.0, 0.01, 0.015):
        fft.p("Début de zone").setValue(value)
        pump(0.03)
    pump(0.25)
    assert computed == [pytest.approx((0.015, 0.036))]


# ------------------------------------------------------------------ limites de zoom

def _wheel(qapp, vb, factor, steps=60):
    for _ in range(steps):
        vb.scaleBy((factor, factor))
        qapp.processEvents()


def test_zoom_limits_all_graphs(setup, monkeypatch):
    """Molette : dézoom borné aux données (+ marge), zoom borné, aucune exception."""
    import sys
    from model.protocol import encode_payload, make_frame
    qapp, sim, window, ctrl = setup
    errors = []
    monkeypatch.setattr(sys, "excepthook", lambda t, v, tb: errors.append(f"{t.__name__}: {v}"))
    ctrl.config_ctrl.p("Échantillonnage", "Diviseur").setValue(500)
    cfg = ctrl.config_ctrl.to_config()
    window.actionFFT.setChecked(True)
    ctrl.math_ctrl.add()
    ctrl.math_ctrl._groups()[0].child("Formule").setValue("[I_HV]*2")
    n = cfg.samples_per_channel
    raw = (np.random.default_rng(0).standard_normal((n, 4)) * 3000).astype(np.int16)
    frame = make_frame(encode_payload(raw), cfg, 1)
    ctrl.graph_ctrl.show_frame(frame)
    ctrl.fft_ctrl.show_frame(frame)
    wait(qapp, lambda: False, 0.15)
    g = ctrl.graph_ctrl
    span = cfg.frame_duration
    y_data = np.abs(frame.analog).max()
    for plot in (g.analog_plot, g.math_plot, g.logic_plot, ctrl.fft_ctrl.plot):
        _wheel(qapp, plot.vb, 3)                       # 60 crans en arrière
        window.grab()
    for plot in (g.analog_plot, g.math_plot, g.logic_plot):
        x0, x1 = plot.vb.viewRange()[0]
        assert x0 >= -0.051 * span and x1 <= 1.051 * span
    y0, y1 = g.analog_plot.vb.viewRange()[1]
    assert max(abs(y0), abs(y1)) < 2 * y_data
    y0, y1 = g.math_plot.vb.viewRange()[1]
    assert max(abs(y0), abs(y1)) < 4 * y_data            # [I_HV]*2
    assert g.logic_plot.vb.viewRange()[1][1] < 17.5
    fx0, fx1 = ctrl.fft_ctrl.plot.vb.viewRange()[0]
    assert fx0 >= -0.051 * cfg.sample_rate / 2 and fx1 <= 1.051 * cfg.sample_rate / 2
    assert ctrl.fft_ctrl.plot.vb.viewRange()[1][1] < 10
    # zoom avant maximal : 10 échantillons en temps, quelques raies en fréquence
    for plot in (g.analog_plot, g.math_plot, ctrl.fft_ctrl.plot):
        _wheel(qapp, plot.vb, 1 / 3)
        window.grab()
    x0, x1 = g.analog_plot.vb.viewRange()[0]
    assert x1 - x0 == pytest.approx(10 / cfg.sample_rate, rel=0.05)
    fx0, fx1 = ctrl.fft_ctrl.plot.vb.viewRange()[0]
    assert fx1 - fx0 == pytest.approx(4 * cfg.sample_rate / n, rel=0.05)
    # FFT en échelle log : limites en décades
    ctrl.fft_ctrl.set_log_x(True)
    _wheel(qapp, ctrl.fft_ctrl.plot.vb, 3)
    window.grab()
    lo, hi = ctrl.fft_ctrl.plot.vb.viewRange()[0]
    assert np.log10(cfg.sample_rate / n) - 0.5 < lo and hi < np.log10(cfg.sample_rate / 2) + 0.5
    ctrl.fft_ctrl.set_log_x(False)
    assert ctrl.fft_ctrl.plot.vb.viewRange()[0][1] == pytest.approx(cfg.sample_rate / 2)
    # courbe masquée : le dézoom vertical suit les courbes visibles
    for sig in (4, 6):
        ctrl.tree_ctrl.items[("A", sig)][0].setCheckState(
            ctrl.tree_ctrl.items[("A", sig)][0].checkState().Unchecked)
    limit = g.analog_plot.vb.state["limits"]["yLimits"][1]
    assert limit == pytest.approx(np.abs(frame.analog[:, 0]).max(), rel=0.5)
    assert errors == []


def test_zoom_limits_scope_record(setup, tmp_path, monkeypatch):
    """Enregistrement d'oscilloscope : dézoom borné à l'enregistrement entier."""
    import sys
    qapp, sim, window, ctrl = setup
    errors = []
    monkeypatch.setattr(sys, "excepthook", lambda t, v, tb: errors.append(f"{t.__name__}: {v}"))
    n = 40_000
    path = _tek_channel(tmp_path / "tek0000CH1.csv", np.sin(np.arange(n) / 50) * 0.002)
    _open_scope(qapp, ctrl, [path])
    vb = ctrl.graph_ctrl.analog_plot.vb
    _wheel(qapp, vb, 3)
    window.grab()
    x0, x1 = vb.viewRange()[0]
    rec = ctrl.scope_ctrl.record
    assert x0 >= rec.t0 - 0.051 * rec.duration and x1 <= rec.t0 + 1.051 * rec.duration
    y0, y1 = vb.viewRange()[1]
    assert max(abs(y0), abs(y1)) < 0.004                  # signal de 2 mV
    _wheel(qapp, vb, 1 / 3)                               # zoom avant : signal en mV
    window.grab()
    assert vb.viewRange()[1][1] - vb.viewRange()[1][0] < 1e-4
    assert errors == []


# ------------------------------------------------------------------ export d'un motif

def _menu_action(plot, text):
    return next(a for a in plot.vb.menu.actions() if a.text() == text)


def test_export_pattern(setup, tmp_path, monkeypatch):
    from model.protocol import encode_payload, make_frame
    qapp, sim, window, ctrl = setup
    pc = ctrl.pattern_ctrl
    ctrl.config_ctrl.p("Échantillonnage", "Diviseur").setValue(500)          # 50 kHz
    cfg = ctrl.config_ctrl.to_config()
    n = cfg.samples_per_channel
    t = np.arange(n) / cfg.sample_rate
    raw = np.zeros((n, 4), dtype=np.int16)
    raw[:, 0] = (np.sin(2 * np.pi * 100 * t) * 8000).astype(np.int16)        # I_HV
    raw[:, 3] = ((t * 1000).astype(int) % 2)                                  # K_HV : 500 Hz
    frame = make_frame(encode_payload(raw), cfg, 1)
    ctrl.math_ctrl.add()
    ctrl.math_ctrl._groups()[0].child("Formule").setValue("[I_HV]*2")
    ctrl.graph_ctrl.show_frame(frame)
    wait(qapp, lambda: False, 0.1)
    plot = ctrl.graph_ctrl.analog_plot
    plot.setXRange(0.01, 0.06, padding=0)

    # clic droit › Exporter un motif...
    _menu_action(plot, "Exporter un motif...").trigger()
    assert pc.active and pc.dialog.isVisible()
    assert pc.region in plot.items and pc.scatter in plot.items
    t0, t1 = pc.zone()
    assert (t0, t1) == pytest.approx((0.025, 0.045))                          # milieu de la vue
    assert pc.dialog.start.value() == pytest.approx(0.025)
    p = pc.pattern
    assert p.points == 1001 and p.step == 1                                   # 1 001 < 2 000
    xs, ys = pc.scatter.getData()
    np.testing.assert_allclose(ys, frame.analog[1250:2251, 0])
    lines = pc.dialog.preview.toPlainText().splitlines()
    assert lines[0] == "t (s)\tI_HV (V)" and lines[1].startswith("0\t")
    assert "1002 lignes" in lines[-1]

    # décimation : 100 points au plus -> 1 point sur 11, bornes gardées
    pc.dialog.max_points.setValue(100)
    assert pc.pattern.points <= 100 and pc.pattern.step == 11
    assert pc.pattern.t[-1] == pytest.approx(0.045)
    assert pc.dialog.info.text().startswith("1 001 échantillons dans la zone, 1 point sur 11 : ")
    assert len(pc.scatter.getData()[0]) == pc.pattern.points

    # zone saisie dans la fenêtre (mise à jour après 100 ms)
    pc.dialog.start.setValue(0.0)
    pc.dialog.stop.setValue(0.01)
    assert wait(qapp, lambda: pc.pattern.t[0] == 0.0 and pc.pattern.t[-1] == pytest.approx(0.01), 2)

    # voie calculée : points marqués sur le panneau des voies calculées
    pc.dialog.channel.setCurrentIndex([c[0] for c in pc.channels].index(("M", "M1")))
    assert pc.scatter in ctrl.graph_ctrl.math_plot.items and pc.scatter not in plot.items
    i = np.round(pc.pattern.t * cfg.sample_rate).astype(int)
    np.testing.assert_allclose(pc.pattern.y, 2 * frame.analog[i, 0], rtol=1e-9)
    # voie logique : créneau 0/1, points au niveau de la voie sur son panneau
    pc.dialog.channel.setCurrentIndex([c[0] for c in pc.channels].index(("L", 0)))
    assert set(np.unique(pc.pattern.y)) == {0.0, 1.0}
    assert pc.scatter in ctrl.graph_ctrl.logic_plot.items
    window.grab().save(str(SHOTS / "logger_motif.png"))

    # formats et copie dans le presse-papiers
    pc.dialog.channel.setCurrentIndex(0)
    pc.dialog.format.setCurrentText("PWL (PSPICE, LTspice)")
    pc.dialog.copy_button.click()
    text = QtWidgets.QApplication.clipboard().text()
    first = text.splitlines()[0].split()
    assert len(first) == 2 and float(first[0]) == 0.0
    assert len(text.splitlines()) == pc.pattern.points
    assert "copié" in window.statusBar().currentMessage()
    pc.dialog.format.setCurrentText("Vecteurs (PLECS, MATLAB)")
    assert pc.text.startswith("t = [0 ") and "\nI_HV = [" in pc.text
    pc.dialog.format.setCurrentText("Colonnes (tabulation)")
    pc.dialog.grab().save(str(SHOTS / "logger_motif_fenetre.png"))
    # enregistrement (dans le dernier répertoire)
    seen = []
    target = tmp_path / "motif.txt"
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName",
                        lambda parent, caption, default, *a: seen.append(default) or (str(target), ""))
    pc.dialog.save_button.click()
    assert target.read_text() == pc.text
    assert seen[0].endswith("motif_I_HV.txt")

    # fermeture : zone et points retirés
    pc.dialog.close()
    assert not pc.active and pc.region not in plot.items
    assert pc.scatter not in ctrl.graph_ctrl.logic_plot.items


def test_export_pattern_scope_record(setup, tmp_path):
    """Enregistrement long : motif lu dans le fichier, même si l'affichage est une enveloppe."""
    qapp, sim, window, ctrl = setup
    pc = ctrl.pattern_ctrl
    n = 200_000
    k = np.arange(n)
    y = np.sin(k / 400.0)
    path = _tek_channel(tmp_path / "tek0000CH1.csv", y)
    ctrl.scope_ctrl.max_raw = 20_000
    _open_scope(qapp, ctrl, [path])
    assert ctrl.graph_ctrl.frame.meta["envelope"]
    plot = ctrl.graph_ctrl.analog_plot
    _menu_action(plot, "Exporter un motif...").trigger()
    rec = ctrl.scope_ctrl.record
    pc.set_zone(rec.time_of(50_000), rec.time_of(150_000))             # 100 001 points bruts
    p = pc.pattern
    assert p.zone_points == 100_001 and p.points <= 2000
    i = np.round((p.t - rec.t0) / rec.dt).astype(int)
    np.testing.assert_allclose(p.y, y[i], atol=1e-6)                   # valeurs brutes
    assert i[0] == 50_000 and i[-1] == 150_000
    window.grab().save(str(SHOTS / "logger_motif_scope.png"))
    # zoom : le motif ne change pas
    before = p.t.copy()
    plot.setXRange(rec.time_of(1000), rec.time_of(3000), padding=0)
    ctrl.scope_ctrl.reload()
    wait(qapp, lambda: False, 0.1)
    np.testing.assert_array_equal(pc.pattern.t, before)
    pc.stop()
