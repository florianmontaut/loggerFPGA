# controller/main_controller.py
"""
Relie la vue et les contrôleurs (rôle du MainController du GLviewer) :

    ConfigController ──config_changed──> ChannelTree / LiveGraph (aperçu de la config)
    actions Démarrer / Trame unique ──> AcquisitionController.start(config)
    AcquisitionController ──frame_ready──> BufferController (mémoire tampon, onglet Trames)
    BufferController ──display_frame──> LiveGraphController / FFTController (direct ou relecture)
    LiveGraphController ──cursor_values──> ChannelTreeController.set_values
    CursorController (t1, t2, y1, y2) ──channel_values──> ChannelTreeController (Valeur, Δ)
    DetachController : graphiques analogique / logique / FFT déportables dans une fenêtre
    ChannelTreeController ──visibility_changed──> LiveGraphController.set_visible

La dernière configuration est conservée entre deux sessions (fichier JSON dans le dossier de
configuration de l'utilisateur).
"""
from __future__ import annotations

import os

from PyQt6 import QtCore, QtGui, QtWidgets

from controller.acquisition_controller import AcquisitionController
from controller.buffer_controller import BufferController, layout_differs
from controller.channel_tree_controller import ChannelTreeController
from controller.config_controller import ConfigController
from controller.cursor_controller import CursorController
from controller.detach_controller import DetachController
from controller.fft_controller import FFTController
from controller.graph_controller import LiveGraphController
from controller.math_controller import MathController
from controller.pattern_controller import PatternController
from controller.recent_controller import RecentFilesController
from controller.scope_controller import ScopeController, is_scope_file
from model.config import ConfigError, LoggerConfig
from model.frame_buffer import MAX_CAPACITY
from model.loader import RecordingError, load_recording
from model.math_channels import definitions_from_config
from view.main_window import MainWindow

STATE_LABELS = {"IDLE": "Arrêté", "CONFIG": "Configuration", "WAIT_TRIG": "Armé",
                "READING": "Lecture"}


def default_record_dir() -> str:
    """Dossier d'enregistrement par défaut : Documents/LoggerFPGA."""
    docs = QtCore.QStandardPaths.writableLocation(
        QtCore.QStandardPaths.StandardLocation.DocumentsLocation) or os.path.expanduser("~")
    return os.path.join(docs, "LoggerFPGA")


def resolve_record_dir(cfg: LoggerConfig) -> LoggerConfig:
    """
    Dossier « . » ou vide (dossier courant du programme, qui dépend de la façon dont il est
    lancé) remplacé par le dossier par défaut ; chemin relatif rendu absolu.
    """
    if cfg.record_dir in ("", "."):
        cfg.record_dir = default_record_dir()
    cfg.record_dir = os.path.abspath(cfg.record_dir)
    return cfg


def last_config_path() -> str:
    folder = QtCore.QStandardPaths.writableLocation(
        QtCore.QStandardPaths.StandardLocation.AppConfigLocation) or os.path.expanduser("~")
    return os.path.join(folder, "logger_fpga_last_config.json")


class MainController(QtCore.QObject):

    def __init__(self, view: MainWindow, cfg: LoggerConfig | None = None,
                 remember: bool = True, confirm_quit: bool = True):
        super().__init__()
        self.view = view
        self.remember = remember
        if cfg is None:
            cfg = self._load_last_config() if remember else LoggerConfig()

        self.config_ctrl = ConfigController(view.configtree, resolve_record_dir(cfg))
        self.tree_ctrl = ChannelTreeController(view.treechannels)
        self.graph_ctrl = LiveGraphController(view.analoggraph, view.logicgraph, view.mathgraph)
        self.cursor_ctrl = CursorController(self.graph_ctrl, view.configtree)
        # réglages de l'interface conservés d'une session à l'autre (fenêtres déportées,
        # axe des fréquences de la FFT)
        self.settings = QtCore.QSettings("LoggerFPGA", "logger_app") if remember else None
        # fichiers récents et dernier répertoire visité (boîtes d'ouverture)
        self.recent_ctrl = RecentFilesController(view.menuRecent, self.settings,
                                                 lambda: self._record_settings()[0])
        # voies calculées (MATH) : formules sur les voies de chaque trame
        self.math_ctrl = MathController(view.configtree,
                                        definitions_from_config(self.config_ctrl.cfg))
        self.graph_ctrl.set_math_engine(self.math_ctrl.engine)
        self.fft_ctrl = FFTController(view.fftgraph, view.configtree, self.settings)
        # graphiques déportables (écran déporté) ; position des fenêtres mémorisée
        self.detach_ctrl = DetachController(
            view, view.graph_splitter, view.graph_placeholder, view.menuWindows,
            self.settings)
        self.detach_ctrl.register("analog", "Voies analogiques", view.analoggraph,
                                  [self.graph_ctrl.analog_plot], weight=3)
        self.detach_ctrl.register("math", "Voies calculées", view.mathgraph,
                                  [self.graph_ctrl.math_plot], weight=2)
        self.detach_ctrl.register("logic", "Voies logiques", view.logicgraph,
                                  [self.graph_ctrl.logic_plot], weight=2)
        self.detach_ctrl.register("fft", "Spectre (FFT)", view.fftgraph,
                                  [self.fft_ctrl.plot], weight=2)
        self.detach_ctrl.set_available("fft", False)
        self.detach_ctrl.set_available("math", False)
        self.graph_ctrl.availability_changed.connect(self.detach_ctrl.set_available)
        self.acq_ctrl = AcquisitionController()
        # mémoire tampon des dernières trames, onglet Trames
        self.buffer_ctrl = BufferController(view, self.config_ctrl.cfg.buffer_frames,
                                            self._record_settings)
        if confirm_quit:
            view.close_guard = self.buffer_ctrl.confirm_quit
        # enregistrements longs d'oscilloscope (CSV Tektronix, HDF5)
        self.scope_ctrl = ScopeController(view, self.graph_ctrl)
        # FFT sur zone : zone posée sur les voies analogiques ; enregistrement
        # d'oscilloscope : données brutes de la zone lues dans le fichier
        self.fft_ctrl.set_zone_plot(self.graph_ctrl.analog_plot)
        self.fft_ctrl.zone_reader_provider = (
            lambda: self.scope_ctrl.read_zone if self.scope_ctrl.active else None)
        # export d'un motif (clic droit sur un graphique) : table de points d'une voie
        self.pattern_ctrl = PatternController(
            view, self.graph_ctrl,
            lambda: self.scope_ctrl.read_zone_frame if self.scope_ctrl.active else None,
            lambda: self.recent_ctrl.last_dir)
        self.pattern_ctrl.message.connect(view.show_message)
        # trame affichée renouvelée (direct, relecture) : motif recalculé
        self.graph_ctrl.redrawn.connect(self._on_redrawn_for_pattern)

        self._connect()
        self._apply_preview(self.config_ctrl.cfg)
        # fenêtres déportées de la session précédente, une fois la fenêtre principale ouverte
        QtCore.QTimer.singleShot(0, self.detach_ctrl.restore)
        self._on_running(False)

    # ------------------------------------------------------------------ connexions
    def _connect(self):
        v = self.view
        v.actionStart.triggered.connect(lambda: self.start(single=False))
        v.actionSingle.triggered.connect(lambda: self.start(single=True))
        v.actionStop.triggered.connect(self.acq_ctrl.stop)
        v.actionPause.toggled.connect(self.graph_ctrl.set_paused)
        v.actionAutoRange.toggled.connect(self.graph_ctrl.set_auto_range)
        v.actionLoadConfig.triggered.connect(self.load_config_dialog)
        v.actionSaveConfig.triggered.connect(self.save_config_dialog)
        v.actionQuit.triggered.connect(v.close)
        v.closing.connect(self.quit)

        self.config_ctrl.config_changed.connect(self._on_config_changed)
        self.config_ctrl.invalid.connect(lambda msg: v.show_message(f"⚠ {msg}", 8000))

        # trames : mémoire tampon, qui transmet à l'affichage (direct ou relecture)
        self.acq_ctrl.frame_ready.connect(self.buffer_ctrl.on_frame)
        self.buffer_ctrl.display_frame.connect(self._display_frame)
        self.buffer_ctrl.message.connect(v.show_message)
        # lambdas : triggered transmet `checked`, qui serait pris pour un argument
        v.actionPrevFrame.triggered.connect(lambda: self.buffer_ctrl.previous())
        v.actionNextFrame.triggered.connect(lambda: self.buffer_ctrl.next())
        v.actionLiveFrame.triggered.connect(lambda: self.buffer_ctrl.go_live())
        v.actionSaveBuffer.triggered.connect(lambda: self.buffer_ctrl.save_dialog())
        v.actionOpenRecording.triggered.connect(self.open_recording_dialog)
        v.actionCloseScope.triggered.connect(lambda: self.scope_ctrl.close())
        v.actionAddScopeChannels.triggered.connect(self.add_scope_channels_dialog)
        self.recent_ctrl.open_requested.connect(self._open_recent)
        self.recent_ctrl.missing.connect(self._recent_missing)
        self.scope_ctrl.loaded.connect(
            lambda h5, sources: self.recent_ctrl.add("scope", [h5], visited=sources[0]))
        self.scope_ctrl.opened.connect(self._on_scope_opened)
        self.scope_ctrl.closed.connect(self._on_scope_closed)
        self.scope_ctrl.display_frame.connect(lambda frame: self._display_frame(frame, "scope"))
        self.scope_ctrl.message.connect(v.show_message)
        self.acq_ctrl.status.connect(v.show_message)
        self.acq_ctrl.error.connect(lambda msg: v.show_message(f"⚠ {msg}", 8000))
        self.acq_ctrl.state_changed.connect(
            lambda s: v.stateLabel.setText(STATE_LABELS.get(s, s)))
        self.acq_ctrl.stats_changed.connect(self._on_stats)
        self.acq_ctrl.running_changed.connect(self._on_running)
        # enregistrement : démarrable / arrêtable à tout moment
        v.actionRecord.toggled.connect(self._on_record_toggled)
        v.actionOpenRecordDir.triggered.connect(self.open_record_dir)
        self.acq_ctrl.recording_changed.connect(self._on_recording_changed)
        self.acq_ctrl.recording_failed.connect(self._on_recording_failed)
        self.acq_ctrl.started_with.connect(self.buffer_ctrl.on_acquisition_started)
        self.acq_ctrl.started_with.connect(lambda cfg: self._apply_preview(cfg, force=True))

        self.graph_ctrl.cursor_values.connect(self._on_graph_values)
        # curseurs de mesure : valeurs en t1 et Δy dans l'arborescence
        self.cursor_ctrl.channel_values.connect(self.tree_ctrl.set_cursor_values)
        self.tree_ctrl.channel_selected.connect(self.cursor_ctrl.select_channel)
        self.graph_ctrl.fps_changed.connect(lambda fps: v.fpsLabel.setText(f"{fps:.0f} img/s"))
        self.tree_ctrl.visibility_changed.connect(self.graph_ctrl.set_visible)

        # voies calculées : appliquées tout de suite, gardées dans la configuration
        self.math_ctrl.changed.connect(self._on_math_changed)
        self.math_ctrl.definitions_changed.connect(
            lambda defs: setattr(self.config_ctrl.cfg, "math_channels", defs))
        self.graph_ctrl.math_errors.connect(self.math_ctrl.show_runtime_errors)

        # FFT : mêmes trames, même pause, mêmes voies visibles que le graphique temporel
        v.actionFFT.toggled.connect(self.fft_ctrl.set_enabled)
        v.actionFFT.toggled.connect(lambda on: self.detach_ctrl.set_available("fft", on))
        v.actionResetFFT.triggered.connect(self.fft_ctrl.reset)
        v.actionPause.toggled.connect(self.fft_ctrl.set_paused)
        self.tree_ctrl.visibility_changed.connect(self.fft_ctrl.set_visible)
        self.tree_ctrl.channel_selected.connect(self.fft_ctrl.select_channel)

    # ------------------------------------------------------------------ acquisition
    def start(self, single: bool = False):
        if self.scope_ctrl.active:
            self.scope_ctrl.close()
        try:
            cfg = self.config_ctrl.to_config()
        except ConfigError as exc:
            QtWidgets.QMessageBox.warning(self.view, "Configuration invalide", str(exc))
            return
        if not self.buffer_ctrl.prepare_start(cfg):
            return
        cfg.record = self.view.actionRecord.isChecked()
        self.view.actionPause.setChecked(False)
        self.acq_ctrl.start(cfg, single=single)

    def _display_frame(self, frame, mode: str):
        """
        Trame à afficher : flux direct (respecte Figer et le moyennage FFT) ou trame de la
        mémoire tampon (relecture, retour au direct).
        """
        if mode == "scope":                 # portion d'un enregistrement d'oscilloscope
            self.graph_ctrl.show_frame(frame)
            self.fft_ctrl.show_frame(frame)
            return
        if self.scope_ctrl.active:
            # trame du logger demandée (direct, mémoire tampon) : fin du mode oscilloscope
            self.scope_ctrl.close(emit=False)
            self._apply_preview(self.buffer_ctrl.buffer.cfg or self.config_ctrl.cfg, force=True)
        if mode == "live":
            self.graph_ctrl.on_frame(frame)
            self.fft_ctrl.on_frame(frame)
            return
        buffer_cfg = self.buffer_ctrl.buffer.cfg
        if buffer_cfg is not None and layout_differs(self.graph_ctrl.cfg, buffer_cfg):
            # configuration modifiée depuis : affichage remis à celle de la trame
            self._apply_preview(buffer_cfg, force=True)
        suffix = "  —  mémoire tampon" if mode == "review" else ""
        if frame.meta.get("loaded"):
            suffix = f"  —  {os.path.basename(frame.meta['loaded'])}"
        self.graph_ctrl.show_frame(frame, suffix)
        self.fft_ctrl.show_frame(frame)

    # ------------------------------------------------------------------ relecture d'un fichier
    def open_recording_dialog(self):
        if self.acq_ctrl.running:
            QtWidgets.QMessageBox.information(
                self.view, "Ouvrir un enregistrement",
                "Arrêtez l'acquisition (F7) avant d'ouvrir un enregistrement.")
            return
        directory = self.recent_ctrl.last_dir         # dossier du dernier fichier chargé
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self.view, "Ouvrir un enregistrement — un CSV par voie d'oscilloscope : "
            "Ctrl+clic pour les choisir ensemble", directory,
            "Enregistrements (*.csv *.npz *.h5 *.hdf5);;Logger FPGA (*.csv *.npz);;"
            "Oscilloscope : CSV Tektronix, HDF5 (*.csv *.h5 *.hdf5);;Tous les fichiers (*)")
        if paths:
            self.open_files(paths)

    def open_files(self, paths: list[str]) -> bool:
        """
        Aiguillage : enregistrement du logger (un fichier .csv / .npz -> mémoire tampon) ou
        enregistrement long d'oscilloscope (CSV Tektronix, plusieurs possibles, ou .h5).
        """
        if self.acq_ctrl.running:
            return False
        scope = [is_scope_file(p) for p in paths]
        if all(scope):
            if self.scope_ctrl.active:
                # enregistrement déjà affiché : un CSV par voie chez Tektronix, on peut
                # cumuler les chargements
                choice = self._ask_add_or_replace(paths)
                if choice == "add":
                    return self.scope_ctrl.append(paths)
                if choice != "replace":
                    return False
            return self.scope_ctrl.open(paths)
        if len(paths) == 1:
            return self.open_recording(paths[0])
        QtWidgets.QMessageBox.warning(
            self.view, "Ouvrir un enregistrement",
            "Plusieurs fichiers : seulement des CSV d'oscilloscope (une voie par fichier).")
        return False

    def add_scope_channels_dialog(self):
        if not self.scope_ctrl.active:
            return
        directory = self.recent_ctrl.last_dir
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self.view, "Ajouter des voies — Ctrl+clic pour en choisir plusieurs", directory,
            "Oscilloscope : CSV Tektronix, HDF5 (*.csv *.h5 *.hdf5);;Tous les fichiers (*)")
        if paths:
            self.scope_ctrl.append(paths)

    def _ask_add_or_replace(self, paths: list[str]) -> str:
        """Fichiers d'oscilloscope ouverts sur un enregistrement affiché : "add",
        "replace" ou "cancel"."""
        box = QtWidgets.QMessageBox(self.view)
        box.setIcon(QtWidgets.QMessageBox.Icon.Question)
        box.setWindowTitle("Enregistrement d'oscilloscope")
        names = ", ".join(os.path.basename(p) for p in paths[:4]) + ("…" if len(paths) > 4 else "")
        box.setText(f"Un enregistrement est affiché ({self.scope_ctrl.cfg.source_name}).\n"
                    f"Ajouter les voies de {names} à cet enregistrement, ou le remplacer ?")
        add = box.addButton("Ajouter les voies", QtWidgets.QMessageBox.ButtonRole.AcceptRole)
        replace = box.addButton("Remplacer", QtWidgets.QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(QtWidgets.QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(add)
        box.exec()
        clicked = box.clickedButton()
        return "add" if clicked is add else "replace" if clicked is replace else "cancel"

    # ------------------------------------------------------------------ oscilloscope
    def _on_scope_opened(self, cfg: LoggerConfig):
        """Affichage configuré pour l'enregistrement (la mémoire tampon est conservée)."""
        self.buffer_ctrl.go_live(show=False)
        self.view.actionPause.setChecked(False)
        self._apply_preview(cfg, force=True)

    def _on_scope_closed(self):
        """Retour à l'affichage du logger (configuration de l'arbre, mémoire tampon)."""
        try:
            cfg = self.config_ctrl.read_tree()
        except ConfigError:
            cfg = self.config_ctrl.cfg
        self._apply_preview(cfg, force=True)
        latest = self.buffer_ctrl.buffer.latest
        if latest is not None:
            self._display_frame(latest, "resume")

    def open_recording(self, path: str) -> bool:
        """Trames d'un enregistrement chargées dans la mémoire tampon, en relecture."""
        if self.acq_ctrl.running:
            return False
        if self.scope_ctrl.active:
            self.scope_ctrl.close(emit=False)
        # fichier lu d'abord : on ne propose d'abandonner la mémoire tampon que si le
        # fichier est valide
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        try:
            recording = load_recording(path)
        except RecordingError as exc:
            QtWidgets.QMessageBox.warning(self.view, "Enregistrement illisible", str(exc))
            return False
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        if not self.buffer_ctrl.confirm_unsaved("ouvrir un enregistrement (la mémoire "
                                                "tampon sera remplacée)"):
            return False
        frames = recording.frames
        notes = list(recording.notes)
        if len(frames) > MAX_CAPACITY:
            notes.append(f"{len(frames)} trames : seules les {MAX_CAPACITY} dernières sont "
                         f"chargées (taille maximale de la mémoire tampon)")
            frames = frames[-MAX_CAPACITY:]
        if len(frames) > self.buffer_ctrl.buffer.capacity:
            # mémoire tampon agrandie pour contenir tout le fichier
            self.buffer_ctrl.set_capacity(len(frames))
            self.config_ctrl.p("Mémoire tampon", "Trames gardées").setValue(len(frames))
            notes.append(f"mémoire tampon portée à {len(frames)} trames")
        self.buffer_ctrl.load(frames, recording.cfg)
        # numéros des prochaines trames acquises : après ceux du fichier
        self.acq_ctrl.next_index = max(self.acq_ctrl.next_index,
                                       max(f.index for f in frames) + 1)
        self.view.tree_tabs.setCurrentIndex(1)              # onglet Trames
        message = f"{len(frames)} trame(s) relue(s) depuis {os.path.basename(path)}"
        if notes:
            message += " — " + " ; ".join(notes)
        self.view.show_message(message, 12000)
        self.recent_ctrl.add("logger", [path])
        return True

    # ------------------------------------------------------------------ fichiers récents
    def _open_recent(self, entry: dict):
        if entry["kind"] == "config":
            self.load_config(entry["paths"][0])
            return
        if self.acq_ctrl.running:
            QtWidgets.QMessageBox.information(
                self.view, "Fichiers récents",
                "Arrêtez l'acquisition (F7) avant d'ouvrir un enregistrement.")
            return
        self.open_files(entry["paths"])

    def _recent_missing(self, entry: dict):
        QtWidgets.QMessageBox.warning(
            self.view, "Fichiers récents",
            "Fichier introuvable, retiré de la liste :\n" + "\n".join(
                p for p in entry["paths"] if not os.path.exists(p)))

    def _on_math_changed(self):
        """Voies calculées modifiées : courbes, arborescence et curseurs mis à jour."""
        self.graph_ctrl.configure_math()
        self.tree_ctrl.set_math_channels(
            [(item.name, item.unit) for item in self.math_ctrl.engine.active])
        self.cursor_ctrl.refresh()
        if getattr(self, "pattern_ctrl", None) is not None and self.pattern_ctrl.active:
            self.pattern_ctrl.refresh_channels()
            self.pattern_ctrl.update()

    def _on_redrawn_for_pattern(self):
        # enregistrement d'oscilloscope : le motif est lu dans le fichier, pas dans la
        # portion affichée ; inutile de le recalculer à chaque zoom
        if self.pattern_ctrl.active and not self.scope_ctrl.active:
            self.pattern_ctrl.update()

    def _on_config_changed(self, cfg: LoggerConfig):
        self.buffer_ctrl.set_capacity(cfg.buffer_frames)
        if self.scope_ctrl.active:
            return                  # affichage de l'enregistrement conservé
        self._apply_preview(cfg)
        if self.acq_ctrl.running:
            self.view.show_message("Configuration modifiée : appliquée au prochain démarrage "
                                   "(F5 relance l'acquisition)", 8000)

    def _apply_preview(self, cfg: LoggerConfig, force: bool = False):
        """Arborescence et graphique préparés pour la configuration (courbes vides)."""
        if self.acq_ctrl.running and not force:
            return
        self.tree_ctrl.build(cfg)
        self.graph_ctrl.configure(cfg)
        self.cursor_ctrl.configure(cfg)
        self.fft_ctrl.configure(cfg)
        self.math_ctrl.set_config(cfg)          # -> _on_math_changed
        if self.pattern_ctrl.active:
            self.pattern_ctrl.refresh_channels()
            self.pattern_ctrl.update()

    def _on_graph_values(self, values: dict):
        """Valeurs sous le curseur simple (double-clic), sauf si les curseurs t1/t2 sont actifs."""
        if not self.cursor_ctrl.vertical:
            self.tree_ctrl.set_values(values)

    # ------------------------------------------------------------------ enregistrement
    def _record_settings(self) -> tuple[str, str, str]:
        try:
            cfg = self.config_ctrl.read_tree()
        except ConfigError:
            cfg = self.config_ctrl.cfg.copy()
        cfg = resolve_record_dir(cfg)
        return cfg.record_dir, cfg.record_prefix, cfg.record_format

    def _on_record_toggled(self, enabled: bool):
        try:
            settings = self._record_settings()
        except ConfigError as exc:
            self.view.show_message(f"⚠ {exc}", 8000)
            return
        if self.acq_ctrl.set_recording(enabled, *settings):
            return                      # appliqué par le thread dès la trame suivante
        if enabled:
            self.view.show_message(f"Enregistrement armé : il démarrera avec l'acquisition "
                                   f"(F5), dans {settings[0]}", 8000)
        else:
            self.view.show_message("Enregistrement désarmé")

    def _on_recording_changed(self, recording: bool, directory: str):
        self.view.recordLabel.setText("● REC" if recording else "")
        self.view.recordLabel.setToolTip(directory if recording else "")
        self.view.actionRecord.setToolTip(
            f"Enregistrement en cours dans {directory}" if recording
            else "Enregistrer chaque trame sur disque")
        if recording:
            self.view.show_message(f"Enregistrement des trames dans {directory}", 8000)
        elif directory:
            self.view.show_message(f"Enregistrement arrêté — fichiers dans {directory}", 8000)

    def _on_recording_failed(self, message: str):
        self.view.recordLabel.setText("")
        self.view.actionRecord.blockSignals(True)
        self.view.actionRecord.setChecked(False)
        self.view.actionRecord.blockSignals(False)
        QtWidgets.QMessageBox.warning(self.view, "Enregistrement", message)

    def open_record_dir(self):
        directory = self._record_settings()[0]
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError as exc:
            QtWidgets.QMessageBox.warning(self.view, "Dossier d'enregistrement", str(exc))
            return
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(directory))

    def _on_stats(self, stats: dict):
        self.view.framesLabel.setText(f"Trames : {stats['frames']}")
        text = f"Erreurs : {stats['errors']}"
        if stats.get("timeouts"):
            text += f"  (sans réponse : {stats['timeouts']})"
        if stats.get("recorded"):
            text += f"  |  Enregistrées : {stats['recorded']}"
        self.view.errorsLabel.setText(text)

    def _on_running(self, running: bool):
        self.view.actionStop.setEnabled(running)
        self.view.actionStart.setText("Relancer" if running else "Démarrer")
        if not running:
            self.view.stateLabel.setText(STATE_LABELS["IDLE"])

    # ------------------------------------------------------------------ fichiers
    def load_config_dialog(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self.view, "Ouvrir une configuration",
                                                        self.recent_ctrl.last_dir,
                                                        "Configuration (*.json)")
        if path:
            self.load_config(path)

    def load_config(self, path: str):
        if self.scope_ctrl.active:
            self.scope_ctrl.close()
        try:
            cfg = LoggerConfig.load(path)
        except (OSError, ValueError, TypeError) as exc:
            QtWidgets.QMessageBox.warning(self.view, "Ouverture impossible", str(exc))
            return
        self.config_ctrl.set_config(resolve_record_dir(cfg))
        self.math_ctrl.set_definitions(definitions_from_config(cfg))
        self._apply_preview(cfg)
        self.view.show_message(f"Configuration chargée : {path}")
        self.recent_ctrl.add("config", [path])

    def save_config_dialog(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self.view,
                                                        "Enregistrer la configuration",
                                                        os.path.join(self.recent_ctrl.last_dir,
                                                                     "logger_config.json"),
                                                        "Configuration (*.json)")
        if path:
            try:
                self.config_ctrl.read_tree().save(path)
                self.view.show_message(f"Configuration enregistrée : {path}")
            except (OSError, ConfigError) as exc:
                QtWidgets.QMessageBox.warning(self.view, "Enregistrement impossible", str(exc))

    def _load_last_config(self) -> LoggerConfig:
        path = last_config_path()
        if os.path.isfile(path):
            try:
                return LoggerConfig.load(path)
            except (OSError, ValueError, TypeError):
                pass
        return LoggerConfig()

    def quit(self):
        self.acq_ctrl.shutdown()
        self.pattern_ctrl.stop()
        self.scope_ctrl.close(emit=False)
        self.detach_ctrl.shutdown()
        if self.remember:
            try:
                path = last_config_path()
                os.makedirs(os.path.dirname(path), exist_ok=True)
                self.config_ctrl.read_tree().save(path)
            except (OSError, ConfigError):
                pass
