# model/recorder.py
"""
Enregistrement des trames sur disque (équivalent de `wr = 1` dans logger.m).

Un fichier par trame, nommé comme dans logger.m :
    <préfixe>_<voie1>_<voie2>..._div_<diviseur>_<numéro>.<ext>
La numérotation reprend après le plus grand numéro déjà présent dans le dossier : une
nouvelle acquisition n'écrase jamais les fichiers d'une précédente.
Formats :
    - csv : colonne de temps (s) puis une colonne par voie (valeurs physiques) et, si la
            voie logique est enregistrée, une colonne 0/1 par voie logique ;
    - npz : tableaux numpy (temps, analog, logic, raw) + configuration, plus compact.
"""
from __future__ import annotations

import json
import os
import re

import numpy as np

from .config import LoggerConfig
from .protocol import Frame

FORMATS = ("csv", "npz")


class FrameRecorder:

    def __init__(self, cfg: LoggerConfig, fmt: str = "csv"):
        if fmt not in FORMATS:
            raise ValueError(f"Format d'enregistrement inconnu : {fmt}")
        self.cfg = cfg
        self.fmt = fmt
        self.directory = os.path.abspath(cfg.record_dir or ".")
        self.last_path: str | None = None
        self.written = 0
        os.makedirs(self.directory, exist_ok=True)
        if not os.access(self.directory, os.W_OK):
            raise PermissionError(f"Dossier non accessible en écriture : {self.directory}")
        # numérotation reprise après les fichiers déjà présents : une nouvelle acquisition
        # n'écrase pas la précédente (logger.m conservait fnum d'un lancement à l'autre)
        self.count = self._last_number()

    def _stem(self) -> str:
        names = [self.cfg.analog_name(s) for s in self.cfg.analog_signals]
        if self.cfg.has_logic:
            names.append("Logic")
        return "_".join([self.cfg.record_prefix, *names, f"div_{self.cfg.divider}"])

    def _last_number(self) -> int:
        pattern = re.compile(re.escape(self._stem()) + r"_(\d+)\." + re.escape(self.fmt) + "$")
        numbers = [int(m.group(1)) for name in os.listdir(self.directory)
                   if (m := pattern.match(name))]
        return max(numbers, default=0)

    def file_name(self, number: int) -> str:
        return os.path.join(self.directory, f"{self._stem()}_{number}.{self.fmt}")

    def columns(self) -> list[str]:
        cols = ["time_s"]
        for s in self.cfg.analog_signals:
            unit = self.cfg.unit(s)
            cols.append(f"{self.cfg.analog_name(s)} ({unit})" if unit else self.cfg.analog_name(s))
        if self.cfg.has_logic:
            cols += [self.cfg.logic_name(b) for b in range(16)]
        return cols

    def write(self, frame: Frame) -> str:
        self.count += 1
        path = self.file_name(self.count)
        t = frame.time()
        if self.fmt == "csv":
            parts = [t[:, None], frame.analog]
            if frame.logic is not None:
                parts.append(frame.logic)
            table = np.hstack(parts)
            n_float = 1 + frame.analog.shape[1]
            fmt = ["%.9g"] * n_float + ["%d"] * (table.shape[1] - n_float)
            np.savetxt(path, table, delimiter=",", fmt=fmt, header=",".join(self.columns()),
                       comments="")
        else:
            np.savez_compressed(path, time=t, analog=frame.analog, raw=frame.raw,
                                logic=frame.logic if frame.logic is not None else np.empty(0),
                                signals=np.array(frame.signals),
                                config=json.dumps(self.cfg.to_dict()))
        self.last_path = path
        self.written += 1
        return path
