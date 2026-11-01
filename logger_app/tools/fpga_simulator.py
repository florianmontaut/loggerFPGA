# tools/fpga_simulator.py
"""
Simulateur du logger FPGA, pour développer et tester l'application sans carte.

Il répond au protocole de logger.m (voir model/protocol.py) :
    - PORT_MSG et trame de configuration : mémorisées ;
    - trigger automatique : START_MSG -> TRIG_MSG après la durée d'une trame ;
    - disjonction : déclenchement aléatoire (0,3 à 1,5 s) ;
    - > seuil / < seuil : la première voie (sinusoïde d'amplitude lentement variable) est
      comparée au seuil, le déclenchement n'a lieu que si elle le franchit ;
    - READ_MSG -> 32 datagrammes DATA_MSG de la dernière trame capturée.

Lancement (même PC que l'application) :
    python -m tools.fpga_simulator --ip 127.0.0.2
puis, dans l'application, IP du FPGA = 127.0.0.2 et IP locale = 127.0.0.1.
Le port de commande 9 est réservé sous Linux : --cmd-port (9009 par exemple), à reporter
dans l'application.
"""
from __future__ import annotations

import argparse
import random
import socket
import sys
import threading
import time
from pathlib import Path

import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from model import protocol                                  # noqa: E402
from model.config import (FULL_SCALE, LOGIC_SIGNAL, WORDS_PER_FRAME,  # noqa: E402
                          LoggerConfig, TriggerType)


class FpgaSimulator(threading.Thread):

    def __init__(self, ip="127.0.0.2", port=2064, cmd_port=9009, drop_rate=0.0, seed=None):
        super().__init__(daemon=True)
        self.ip, self.port, self.cmd_port = ip, port, cmd_port
        self.drop_rate = drop_rate
        self.rng = random.Random(seed)
        self.cfg: dict | None = None
        self.client = None
        self.frame_payload: bytes | None = None
        self.armed = False
        self.next_trip = 0.0
        self.t0 = time.time()
        self.received: list[bytes] = []     # trames reçues (tests)
        self.triggers = 0
        self._halt = threading.Event()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((ip, port))
        self.cmd = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.cmd.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.cmd.bind((ip, cmd_port))

    def stop(self):
        self._halt.set()

    # ------------------------------------------------------------------ signaux
    def _signals(self, start: float) -> np.ndarray:
        """Trame brute (n, n_channels) int16 à partir de l'instant `start`."""
        cfg = self.cfg
        n_ch = cfg["n_channels"]
        n = WORDS_PER_FRAME // n_ch
        fs = 25e6 / max(cfg["divider"], 1)
        t = start + np.arange(n) / fs
        envelope = 0.55 + 0.4 * np.sin(2 * np.pi * (start - self.t0) / 6.0)
        raw = np.zeros((n, n_ch), dtype=np.int16)
        for j, sig in enumerate(cfg["signals"]):
            if sig == LOGIC_SIGNAL:
                word = np.zeros(n, dtype=np.uint16)
                for bit in range(16):
                    period = 2e-3 * (bit + 1)
                    word |= (((t // (period / 2)) % 2).astype(np.uint16) << bit)
                raw[:, j] = word.view(np.int16)
            else:
                f = 50.0 * (sig + 1)
                amp = envelope * (1.0 if j == 0 else 0.3 + 0.05 * sig)
                y = amp * np.sin(2 * np.pi * f * t + sig) + 0.01 * np.random.randn(n)
                raw[:, j] = np.clip(y * FULL_SCALE, -32768, 32767).astype(np.int16)
        return raw

    def _capture(self) -> np.ndarray:
        raw = self._signals(time.time())
        self.frame_payload = protocol.encode_payload(raw)
        return raw

    def _threshold_crossed(self, raw: np.ndarray) -> bool:
        first = raw[:, 0].astype(int)
        if self.cfg["trigger"] == TriggerType.ABOVE:
            return bool((first > self.cfg["threshold"]).any())
        return bool((first < self.cfg["threshold"]).any())

    def _trig(self):
        self.triggers += 1
        self.armed = False
        self.sock.sendto(protocol.TRIG_HEADER + bytes(4), self.client)

    # ------------------------------------------------------------------ boucle
    def run(self):
        self.sock.settimeout(0.02)
        self.cmd.settimeout(0.0)
        while not self._halt.is_set():
            try:
                msg, addr = self.cmd.recvfrom(64)
                if msg == protocol.PORT_MSG:
                    self.client = addr
            except (BlockingIOError, socket.timeout, ConnectionResetError):
                pass
            try:
                msg, addr = self.sock.recvfrom(2048)
            except (socket.timeout, ConnectionResetError):
                msg = None
            if msg is not None:
                self.received.append(msg)
                self.client = addr
                self._on_message(msg)
            self._poll_trigger()
        self.sock.close()
        self.cmd.close()

    def _on_message(self, msg: bytes):
        if msg[:2] == protocol.CONFIG_HEADER:
            self.cfg = protocol.parse_config_msg(msg)
            self.armed = self.cfg["trigger"] != TriggerType.AUTO
            self.next_trip = time.time() + self.rng.uniform(0.3, 1.5)
        elif msg == protocol.START_MSG and self.cfg:
            time.sleep(min(WORDS_PER_FRAME * self.cfg["divider"] / 25e6, 0.5))
            self._capture()
            self._trig()
        elif msg == protocol.READ_MSG and self.frame_payload:
            for packet in protocol.split_payload(self.frame_payload):
                if self.rng.random() >= self.drop_rate:
                    self.sock.sendto(packet, self.client)
            if self.cfg["trigger"] != TriggerType.AUTO:
                self.armed = True
                self.next_trip = time.time() + self.rng.uniform(0.3, 1.5)
        elif msg == protocol.STOP_MSG:
            self.armed = False

    def _poll_trigger(self):
        if not (self.armed and self.cfg and self.client):
            return
        trig = self.cfg["trigger"]
        if trig == TriggerType.TRIP:
            if time.time() >= self.next_trip:
                self._capture()
                self._trig()
        elif trig in (TriggerType.ABOVE, TriggerType.BELOW):
            raw = self._capture()
            if self._threshold_crossed(raw):
                self._trig()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ip", default="127.0.0.2")
    parser.add_argument("--port", type=int, default=LoggerConfig.port_fpga)
    parser.add_argument("--cmd-port", type=int, default=9009)
    parser.add_argument("--drop-rate", type=float, default=0.0,
                        help="probabilité de perte d'un datagramme de données")
    args = parser.parse_args(argv)
    sim = FpgaSimulator(args.ip, args.port, args.cmd_port, args.drop_rate)
    sim.start()
    print(f"Simulateur FPGA sur {args.ip}:{args.port} (commande {args.cmd_port}), Ctrl+C pour quitter")
    try:
        while sim.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        sim.stop()


if __name__ == "__main__":
    main()
