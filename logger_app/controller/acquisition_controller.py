# controller/acquisition_controller.py
"""
Cycle de vie de l'acquisition : un AcquisitionWorker (thread) par lancement.

    start(cfg)           acquisition continue ou limitée à cfg.max_frames trames
    start(cfg, single)   une seule trame
    stop()               arrêt demandé au thread (STOP_MSG envoyé à la fin)

Les signaux du worker sont relayés tels quels : les contrôleurs de l'interface n'ont pas à
connaître le thread courant.
"""
from __future__ import annotations

from PyQt6 import QtCore

from controller.udp_worker import AcquisitionWorker
from model.config import LoggerConfig


class AcquisitionController(QtCore.QObject):

    frame_ready = QtCore.pyqtSignal(object)
    status = QtCore.pyqtSignal(str)
    error = QtCore.pyqtSignal(str)
    state_changed = QtCore.pyqtSignal(str)
    stats_changed = QtCore.pyqtSignal(dict)
    running_changed = QtCore.pyqtSignal(bool)
    started_with = QtCore.pyqtSignal(object)     # configuration du worker lancé
    recording_changed = QtCore.pyqtSignal(bool, str)
    recording_failed = QtCore.pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.worker: AcquisitionWorker | None = None
        self._pending: tuple[LoggerConfig, bool] | None = None

    @property
    def running(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    def start(self, cfg: LoggerConfig, single: bool = False):
        """Lance l'acquisition ; si elle tourne déjà, elle est relancée avec `cfg`."""
        cfg = cfg.copy()
        if single:
            cfg.max_frames = 1
        if self.running:
            self._pending = (cfg, False)
            self.stop()
            return
        self.worker = AcquisitionWorker(cfg)
        self.worker.frame_ready.connect(self.frame_ready)
        self.worker.status.connect(self.status)
        self.worker.error.connect(self.error)
        self.worker.state_changed.connect(self.state_changed)
        self.worker.stats_changed.connect(self.stats_changed)
        self.worker.recording_changed.connect(self.recording_changed)
        self.worker.recording_failed.connect(self.recording_failed)
        self.worker.finished.connect(self._on_finished)
        self.started_with.emit(cfg.copy())
        self.worker.start()
        self.running_changed.emit(True)

    def set_recording(self, enabled: bool, record_dir: str, prefix: str, fmt: str) -> bool:
        """Enregistrement démarré / arrêté pendant l'acquisition ; False si elle est arrêtée."""
        if not self.running:
            return False
        self.worker.set_recording(enabled, record_dir, prefix, fmt)
        return True

    def stop(self):
        if self.worker is not None:
            self.worker.request_stop()

    def shutdown(self, timeout_ms: int = 3000):
        self._pending = None
        if self.worker is not None:
            self.worker.request_stop()
            self.worker.wait(timeout_ms)

    def _on_finished(self):
        worker, self.worker = self.worker, None
        if worker is not None:
            worker.deleteLater()
        self.running_changed.emit(False)
        if self._pending is not None:
            cfg, single = self._pending
            self._pending = None
            self.start(cfg, single)
