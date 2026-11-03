# controller/udp_worker.py
"""
Dialogue UDP avec le logger, dans un thread dédié.

Choix : socket Python bloquante (avec délais d'attente) dans QThread.run(), qui suit pas à
pas la boucle de logger.m. L'interface n'est jamais bloquée : les trames décodées sont
transmises par signal Qt (connexion en file d'attente vers le thread de l'interface) et
l'arrêt est demandé par un drapeau vérifié au plus toutes les POLL_S secondes.

Les écarts volontaires avec logger.m :
    - trigger automatique : START_MSG est renvoyé si le déclenchement n'arrive pas sous
      TRIG_TIMEOUT_S (logger.m attendait indéfiniment) ;
    - lecture des données : une trame incomplète est comptée en erreur, sans bloquer ;
    - pas d'arp-ping : l'absence de réponse est signalée dans la barre d'état.
"""
from __future__ import annotations

import socket
import threading
import time

from PyQt6 import QtCore

from model import protocol
from model.config import LoggerConfig
from model.recorder import FrameRecorder


class AcquisitionWorker(QtCore.QThread):

    frame_ready = QtCore.pyqtSignal(object)        # protocol.Frame
    status = QtCore.pyqtSignal(str)                # message pour la barre d'état
    state_changed = QtCore.pyqtSignal(str)         # IDLE, CONFIG, WAIT_TRIG, READING, ...
    error = QtCore.pyqtSignal(str)
    stats_changed = QtCore.pyqtSignal(dict)        # frames, errors, timeouts, recorded
    # enregistrement démarré (True, dossier) ou arrêté (False, dossier)
    recording_changed = QtCore.pyqtSignal(bool, str)
    recording_failed = QtCore.pyqtSignal(str)      # enregistrement impossible : message

    POLL_S = 0.2              # réactivité à la demande d'arrêt
    TRIG_TIMEOUT_S = 2.0      # udp_read(udp_com, 6, 2000) dans logger.m
    FIRST_PACKET_TIMEOUT_S = 1.0
    PACKET_TIMEOUT_S = 0.02   # udp_read(udp_com, 1030, 20) dans logger.m
    RCVBUF = 4 * 1024 * 1024

    def __init__(self, cfg: LoggerConfig, parent=None, first_index: int = 1):
        super().__init__(parent)
        # numéro de la première trame : la numérotation continue d'une acquisition à
        # l'autre (numéro unique dans la mémoire tampon et dans les fichiers)
        self.first_index = first_index
        self.cfg = cfg.copy()
        self.cfg.validate()
        self._stop = threading.Event()
        self.sock: socket.socket | None = None
        self.stats = {"frames": 0, "errors": 0, "timeouts": 0, "recorded": 0}
        # enregistrement demandé depuis l'interface, appliqué par le thread à la trame
        # suivante : (actif, dossier, préfixe, format) ; affectation atomique en Python
        self._record_request = (cfg.record, cfg.record_dir, cfg.record_prefix,
                                cfg.record_format)
        self._recorder: FrameRecorder | None = None
        self._record_state = None

    # ------------------------------------------------------------------ commande
    def set_recording(self, enabled: bool, record_dir: str, prefix: str, fmt: str):
        """Démarre / arrête l'enregistrement en cours d'acquisition (appel depuis l'interface)."""
        self._record_request = (enabled, record_dir, prefix, fmt)

    def _apply_record_request(self):
        """Dans le thread d'acquisition : (re)crée ou ferme l'enregistreur si demandé."""
        request = self._record_request
        if request == self._record_state:
            return
        self._record_state = request
        enabled, record_dir, prefix, fmt = request
        directory = self._recorder.directory if self._recorder else record_dir
        self._close_recorder()
        if enabled:
            cfg = self.cfg.copy()
            cfg.record_dir, cfg.record_prefix, cfg.record_format = record_dir, prefix, fmt
            try:
                self._recorder = FrameRecorder(cfg, fmt)
                directory = self._recorder.path
            except (OSError, ValueError) as exc:
                self.recording_failed.emit(f"Enregistrement impossible : {exc}")
                return
        self.recording_changed.emit(enabled, directory)

    def _close_recorder(self):
        recorder, self._recorder = self._recorder, None
        if recorder is not None:
            try:
                recorder.close()
            except OSError as exc:
                self.error.emit(f"Fermeture de l'enregistrement impossible : {exc}")

    def request_stop(self):
        self._stop.set()

    @property
    def stopping(self) -> bool:
        return self._stop.is_set()

    # ------------------------------------------------------------------ thread
    def run(self):
        cfg = self.cfg
        try:
            self._open()
            # datagrammes restés d'une session précédente : vidés AVANT la configuration.
            # Après, le logger est armé (trigger disjonction / seuil) et peut se déclencher
            # pendant la pause `tempo` : son TRIG_MSG ne doit pas être perdu.
            self._flush()
            self.state_changed.emit("CONFIG")
            self.status.emit(f"Configuration du logger {cfg.ip_fpga}")
            self._send(protocol.PORT_MSG, cfg.port_cmd)
            if self._sleep(0.1):
                return
            self._send(protocol.build_config_msg(cfg))
            if self._sleep(cfg.tempo):
                return

            while not self.stopping and not self._frames_done():
                if cfg.trigger_type == cfg.trigger_type.AUTO:
                    self._send(protocol.START_MSG)
                self.state_changed.emit("WAIT_TRIG")
                if not self._wait_trig():
                    break
                self.state_changed.emit("READING")
                self._send(protocol.READ_MSG)
                payload, missing = self._read_data()
                if self.stopping and payload is None:
                    break
                self.stats["frames"] += 1
                if missing:
                    self.stats["errors"] += 1
                    self.error.emit(f"Trame {self.first_index + self.stats['frames'] - 1} incomplète : "
                                    f"{missing} paquet(s) manquant(s)")
                else:
                    index = self.first_index + self.stats["frames"] - 1
                    frame = protocol.make_frame(payload, cfg, index, time.time())
                    # écrite avant d'être transmise : la mémoire tampon la sait enregistrée
                    self._apply_record_request()
                    if self._recorder is not None:
                        try:
                            frame.meta["saved"] = self._recorder.write(frame)
                            self.stats["recorded"] += 1
                        except OSError as exc:
                            self._close_recorder()
                            self.recording_failed.emit(f"Enregistrement impossible : {exc}")
                    self.frame_ready.emit(frame)
                self.stats_changed.emit(dict(self.stats))
                if self._sleep(cfg.tempo):
                    break
        except OSError as exc:
            self.error.emit(f"Erreur réseau : {exc}")
        except Exception as exc:              # remonté à l'interface plutôt que perdu
            self.error.emit(f"Erreur d'acquisition : {exc!r}")
        finally:
            if self._recorder is not None:
                path = self._recorder.path
                self._close_recorder()
                self.recording_changed.emit(False, path)
            self._close()
            self.stats_changed.emit(dict(self.stats))
            self.state_changed.emit("IDLE")
            self.status.emit(f"Acquisition arrêtée : {self.stats['frames']} trame(s), "
                             f"{self.stats['errors']} erreur(s)")

    # ------------------------------------------------------------------ étapes
    def _frames_done(self) -> bool:
        return self.cfg.max_frames > 0 and self.stats["frames"] >= self.cfg.max_frames

    def _wait_trig(self) -> bool:
        """Attend TRIG_MSG ; False si l'arrêt a été demandé."""
        auto = self.cfg.trigger_type == self.cfg.trigger_type.AUTO
        waited = 0.0
        if not auto:
            self.status.emit(f"En attente du déclenchement ({self.cfg.trigger_type.label})")
        while not self.stopping:
            msg = self._recv(self.POLL_S)
            if msg is None:
                waited += self.POLL_S
                if auto and waited >= self.TRIG_TIMEOUT_S:
                    self.stats["timeouts"] += 1
                    self.status.emit(f"Pas de réponse du logger ({self.stats['timeouts']})")
                    self.stats_changed.emit(dict(self.stats))
                    self._send(protocol.START_MSG)
                    waited = 0.0
                continue
            if protocol.is_trig(msg):
                return True
        return False

    def _read_data(self) -> tuple[bytes | None, int]:
        """Lit les datagrammes d'une trame ; renvoie (données, paquets manquants)."""
        expected = self.cfg.packets_per_frame
        chunks: list[bytes] = []
        timeout = self.FIRST_PACKET_TIMEOUT_S
        while len(chunks) < expected:
            msg = self._recv(timeout)
            if msg is None:
                break
            if protocol.is_data(msg):
                chunks.append(msg[protocol.HEADER_SIZE:])
                timeout = self.PACKET_TIMEOUT_S
        missing = expected - len(chunks)
        return (b"".join(chunks) if not missing else None), missing

    # ------------------------------------------------------------------ socket
    def _open(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, self.RCVBUF)
        except OSError:
            pass
        # Windows : un ICMP « port injoignable » fait échouer le recvfrom suivant
        # (WSAECONNRESET) ; on désactive ce comportement
        if hasattr(socket, "SIO_UDP_CONNRESET"):
            try:
                sock.ioctl(socket.SIO_UDP_CONNRESET, False)
            except OSError:
                pass
        sock.bind((self.cfg.local_ip, self.cfg.local_port))
        self.sock = sock

    def _close(self):
        if self.sock is None:
            return
        try:
            self._send(protocol.STOP_MSG)
        except OSError:
            pass
        self.sock.close()
        self.sock = None

    def _send(self, msg: bytes, port: int | None = None):
        self.sock.sendto(msg, (self.cfg.ip_fpga, port or self.cfg.port_fpga))

    def _recv(self, timeout: float) -> bytes | None:
        self.sock.settimeout(timeout)
        try:
            data, _ = self.sock.recvfrom(protocol.DATA_PACKET_SIZE + 64)
        except (socket.timeout, ConnectionResetError):
            return None
        return data

    def _flush(self):
        """Vide les datagrammes reçus avant le début des trames."""
        self.sock.setblocking(False)
        try:
            while True:
                self.sock.recvfrom(protocol.DATA_PACKET_SIZE + 64)
        except (BlockingIOError, ConnectionResetError, socket.timeout):
            pass
        finally:
            self.sock.setblocking(True)

    def _sleep(self, seconds: float) -> bool:
        """Pause interruptible ; True si l'arrêt a été demandé."""
        return self._stop.wait(seconds)
