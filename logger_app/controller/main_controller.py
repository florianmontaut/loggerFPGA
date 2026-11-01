# controller/main_controller.py
"""
Relie la vue et les contrôleurs (rôle du MainController du GLviewer) :

    ConfigController ──config_changed──> ChannelTree / LiveGraph (aperçu de la config)
    actions Démarrer / Trame unique ──> AcquisitionController.start(config)
    AcquisitionController ──frame_ready──> LiveGraphController.on_frame
    LiveGraphController ──cursor_values──> ChannelTreeController.set_values
    ChannelTreeController ──visibility_changed──> LiveGraphController.set_visible

La dernière configuration est conservée entre deux sessions (fichier JSON dans le dossier de
configuration de l'utilisateur).
"""
from __future__ import annotations

import os

from PyQt6 import QtCore, QtWidgets

from controller.acquisition_controller import AcquisitionController
from controller.channel_tree_controller import ChannelTreeController
from controller.config_controller import ConfigController
from controller.graph_controller import LiveGraphController
from model.config import ConfigError, LoggerConfig
from view.main_window import MainWindow

STATE_LABELS = {"IDLE": "Arrêté", "CONFIG": "Configuration", "WAIT_TRIG": "Armé",
                "READING": "Lecture"}


def last_config_path() -> str:
    folder = QtCore.QStandardPaths.writableLocation(
        QtCore.QStandardPaths.StandardLocation.AppConfigLocation) or os.path.expanduser("~")
    return os.path.join(folder, "logger_fpga_last_config.json")


class MainController(QtCore.QObject):

    def __init__(self, view: MainWindow, cfg: LoggerConfig | None = None,
                 remember: bool = True):
        super().__init__()
        self.view = view
        self.remember = remember
        if cfg is None:
            cfg = self._load_last_config() if remember else LoggerConfig()

        self.config_ctrl = ConfigController(view.configtree, cfg)
        self.tree_ctrl = ChannelTreeController(view.treechannels)
        self.graph_ctrl = LiveGraphController(view.maingraph)
        self.acq_ctrl = AcquisitionController()

        self._connect()
        self._apply_preview(self.config_ctrl.cfg)
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

        self.acq_ctrl.frame_ready.connect(self.graph_ctrl.on_frame)
        self.acq_ctrl.status.connect(v.show_message)
        self.acq_ctrl.error.connect(lambda msg: v.show_message(f"⚠ {msg}", 8000))
        self.acq_ctrl.state_changed.connect(
            lambda s: v.stateLabel.setText(STATE_LABELS.get(s, s)))
        self.acq_ctrl.stats_changed.connect(self._on_stats)
        self.acq_ctrl.running_changed.connect(self._on_running)
        self.acq_ctrl.started_with.connect(lambda cfg: self._apply_preview(cfg, force=True))

        self.graph_ctrl.cursor_values.connect(self.tree_ctrl.set_values)
        self.graph_ctrl.fps_changed.connect(lambda fps: v.fpsLabel.setText(f"{fps:.0f} img/s"))
        self.tree_ctrl.visibility_changed.connect(self.graph_ctrl.set_visible)

    # ------------------------------------------------------------------ acquisition
    def start(self, single: bool = False):
        try:
            cfg = self.config_ctrl.to_config()
        except ConfigError as exc:
            QtWidgets.QMessageBox.warning(self.view, "Configuration invalide", str(exc))
            return
        cfg.record = self.view.actionRecord.isChecked()
        self.view.actionPause.setChecked(False)
        self.acq_ctrl.start(cfg, single=single)

    def _on_config_changed(self, cfg: LoggerConfig):
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
        self.view.actionRecord.setEnabled(not running)
        self.view.actionStart.setText("Relancer" if running else "Démarrer")
        if not running:
            self.view.stateLabel.setText(STATE_LABELS["IDLE"])

    # ------------------------------------------------------------------ fichiers
    def load_config_dialog(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self.view, "Ouvrir une configuration",
                                                        "", "Configuration (*.json)")
        if path:
            self.load_config(path)

    def load_config(self, path: str):
        try:
            cfg = LoggerConfig.load(path)
        except (OSError, ValueError, TypeError) as exc:
            QtWidgets.QMessageBox.warning(self.view, "Ouverture impossible", str(exc))
            return
        self.config_ctrl.set_config(cfg)
        self._apply_preview(cfg)
        self.view.show_message(f"Configuration chargée : {path}")

    def save_config_dialog(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self.view,
                                                        "Enregistrer la configuration",
                                                        "logger_config.json",
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
        if self.remember:
            try:
                path = last_config_path()
                os.makedirs(os.path.dirname(path), exist_ok=True)
                self.config_ctrl.read_tree().save(path)
            except (OSError, ConfigError):
                pass
