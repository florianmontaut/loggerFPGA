# model/frame_buffer.py
"""
Mémoire tampon des dernières trames (comme le tampon de captures de PicoScope 7).

Les `capacity` dernières trames reçues sont gardées en mémoire, même sans enregistrement :
on peut y revenir (onglet Trames) et les enregistrer après coup. Une trame est
« enregistrée » si elle a été écrite sur disque (bouton Enregistrer pendant l'acquisition
ou sauvegarde de la mémoire tampon) ; les autres sont proposées à l'enregistrement avant de
quitter l'application.

Toutes les trames du tampon ont la même disposition de voies (mêmes voies, même
diviseur), pour pouvoir être affichées par le même graphique et enregistrées dans un même
fichier : une acquisition avec une autre disposition vide d'abord le tampon.
"""
from __future__ import annotations

from collections import deque

from .config import LoggerConfig
from .protocol import Frame
from .recorder import layout_key

DEFAULT_CAPACITY = 64
MAX_CAPACITY = 5000


class FrameBuffer:

    def __init__(self, capacity: int = DEFAULT_CAPACITY):
        self._frames: deque[Frame] = deque()
        self._capacity = DEFAULT_CAPACITY
        self.cfg: LoggerConfig | None = None    # configuration des trames du tampon
        self.capacity = capacity

    # ------------------------------------------------------------------ taille
    @property
    def capacity(self) -> int:
        return self._capacity

    @capacity.setter
    def capacity(self, value: int):
        self._capacity = int(min(max(value, 1), MAX_CAPACITY))
        self._trim()

    def set_capacity(self, value: int) -> list[Frame]:
        """Change la taille ; renvoie les trames les plus anciennes retirées."""
        before = list(self._frames)
        self.capacity = value
        return before[:len(before) - len(self._frames)]

    def _trim(self) -> list[Frame]:
        dropped = []
        while len(self._frames) > self._capacity:
            dropped.append(self._frames.popleft())
        return dropped

    # ------------------------------------------------------------------ contenu
    def __len__(self) -> int:
        return len(self._frames)

    def __iter__(self):
        return iter(self._frames)

    def __getitem__(self, position: int) -> Frame:
        return self._frames[position]

    @property
    def frames(self) -> list[Frame]:
        return list(self._frames)

    @property
    def latest(self) -> Frame | None:
        return self._frames[-1] if self._frames else None

    def position(self, frame: Frame) -> int:
        """Rang de la trame dans le tampon (0 = la plus ancienne), -1 si absente."""
        for i, f in enumerate(self._frames):
            if f is frame:
                return i
        return -1

    def compatible(self, cfg: LoggerConfig) -> bool:
        """Les trames de `cfg` peuvent rejoindre le tampon sans le vider."""
        return self.cfg is None or not self._frames or layout_key(cfg) == layout_key(self.cfg)

    def add(self, frame: Frame, cfg: LoggerConfig) -> list[Frame]:
        """
        Ajoute une trame ; renvoie les trames retirées (les plus anciennes, ou tout le
        tampon si la disposition des voies a changé).
        """
        dropped = []
        if not self.compatible(cfg):
            dropped = self.clear()
        if self.cfg is None or not self._frames or dropped:
            self.cfg = cfg.copy()
        self._frames.append(frame)
        return dropped + self._trim()

    def clear(self) -> list[Frame]:
        dropped = list(self._frames)
        self._frames.clear()
        return dropped

    # ------------------------------------------------------------------ enregistrement
    @staticmethod
    def is_saved(frame: Frame) -> bool:
        return bool(frame.meta.get("saved"))

    @staticmethod
    def mark_saved(frames, path: str = ""):
        for frame in frames:
            frame.meta["saved"] = path or True

    def unsaved(self) -> list[Frame]:
        return [f for f in self._frames if not self.is_saved(f)]

    def memory_bytes(self) -> int:
        total = 0
        for f in self._frames:
            total += f.raw.nbytes + f.analog.nbytes + (f.logic.nbytes if f.logic is not None else 0)
        return total


def frame_bytes(cfg: LoggerConfig) -> int:
    """Taille en mémoire d'une trame de `cfg` (brut int16, analogique float64, logique)."""
    n = cfg.samples_per_channel
    size = n * cfg.n_channels * 2 + n * len(cfg.analog_signals) * 8
    if cfg.has_logic:
        size += n * 16
    return size
