# model/recorder.py
"""
Enregistrement des trames sur disque (équivalent de `wr = 1` dans logger.m).

Un seul fichier par enregistrement, toutes trames confondues :

    <préfixe>_<voie1>_<voie2>..._div_<diviseur>_<AAAAMMJJ-HHMMSS>.csv
    trame,temps_s,V_HV (V),I_HV (A),...,K_HV,K_PRE,...
    12,0,1.25,...
    12,8e-07,1.31,...
    ...
    13,0,...

    - colonne `trame` : numéro de la trame (le même que dans le titre du graphique et
      dans l'onglet Trames), `temps_s` : temps depuis le début de la trame ;
    - une colonne par voie analogique (valeurs physiques), puis une colonne 0/1 par voie
      logique si la voie logique est enregistrée ;
    - le CSV est écrit au fil de l'eau : il reste lisible même si l'application s'arrête
      brutalement.

À côté, <même nom>.json décrit l'enregistrement : configuration du logger (voies, gains,
diviseur, trigger...) et, pour chaque trame, son numéro et son heure de capture.

Format npz : mêmes données en tableaux numpy (trame, timestamp, time, analog
(trames, points, voies), logic, raw), écrit à la fermeture.

Un fichier existant n'est jamais écrasé (suffixe _2, _3...).
"""
from __future__ import annotations

import datetime
import json
import os

import numpy as np

from .config import LoggerConfig
from .protocol import Frame

FORMATS = ("csv", "npz")


def layout_key(cfg: LoggerConfig) -> tuple:
    """Trames compatibles dans un même fichier : mêmes voies, même échantillonnage."""
    return tuple(cfg.signals), cfg.divider


class FrameRecorder:
    """
    Fichier d'enregistrement ouvert : write(frame) pour chaque trame, puis close().
    Utilisable comme gestionnaire de contexte.
    """

    def __init__(self, cfg: LoggerConfig, fmt: str = "csv", path: str | None = None):
        if fmt not in FORMATS:
            raise ValueError(f"Format d'enregistrement inconnu : {fmt}")
        self.cfg = cfg.copy()
        self.fmt = fmt
        self.started = datetime.datetime.now()
        if path is None:
            self.directory = os.path.abspath(cfg.record_dir or ".")
            os.makedirs(self.directory, exist_ok=True)
            if not os.access(self.directory, os.W_OK):
                raise PermissionError(f"Dossier non accessible en écriture : {self.directory}")
            path = self._free_path(os.path.join(self.directory, self._stem() + "." + fmt))
        else:
            path = os.path.abspath(path)
            self.directory = os.path.dirname(path)
            os.makedirs(self.directory, exist_ok=True)
        self.path = path
        self.meta_path = os.path.splitext(path)[0] + ".json"
        self.frames: list[dict] = []          # numéro et heure de chaque trame écrite
        self._pending: list[Frame] = []       # npz : trames écrites à la fermeture
        self._file = None
        self.closed = False
        if fmt == "csv":
            self._file = open(path, "w", encoding="utf-8", newline="")
            self._file.write(",".join(self.columns()) + "\n")
            self._file.flush()
        self._write_meta()

    # ------------------------------------------------------------------ noms
    def _stem(self) -> str:
        names = [self.cfg.analog_name(s) for s in self.cfg.analog_signals]
        if self.cfg.has_logic:
            names.append("Logic")
        return "_".join([self.cfg.record_prefix, *names, f"div_{self.cfg.divider}",
                         self.started.strftime("%Y%m%d-%H%M%S")])

    @staticmethod
    def _free_path(path: str) -> str:
        base, ext = os.path.splitext(path)
        candidate, n = path, 1
        while os.path.exists(candidate) or os.path.exists(os.path.splitext(candidate)[0] + ".json"):
            n += 1
            candidate = f"{base}_{n}{ext}"
        return candidate

    def columns(self) -> list[str]:
        cols = ["trame", "temps_s"]
        for s in self.cfg.analog_signals:
            unit = self.cfg.unit(s)
            cols.append(f"{self.cfg.analog_name(s)} ({unit})" if unit else self.cfg.analog_name(s))
        if self.cfg.has_logic:
            cols += [self.cfg.logic_name(b) for b in range(16)]
        return cols

    @property
    def written(self) -> int:
        return len(self.frames)

    # ------------------------------------------------------------------ écriture
    def write(self, frame: Frame) -> str:
        if self.closed:
            raise ValueError("Enregistrement déjà fermé")
        if list(frame.signals) != list(self.cfg.signals):
            raise ValueError("Trame d'une autre configuration de voies")
        if self.fmt == "csv":
            n = frame.n_samples
            parts = [np.full((n, 1), frame.index), frame.time()[:, None], frame.analog]
            if frame.logic is not None:
                parts.append(frame.logic)
            table = np.hstack(parts)
            n_float = 1 + frame.analog.shape[1]
            fmt = ["%d"] + ["%.9g"] * n_float + ["%d"] * (table.shape[1] - n_float - 1)
            np.savetxt(self._file, table, delimiter=",", fmt=fmt)
            self._file.flush()
        else:
            self._pending.append(frame)
        self.frames.append({"trame": frame.index, "timestamp": frame.timestamp,
                            "heure": _iso(frame.timestamp)})
        return self.path

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self._file is not None:
            self._file.close()
        if self.fmt == "npz":
            self._write_npz()
        self._write_meta()

    def _write_npz(self):
        frames = self._pending
        first = frames[0] if frames else None
        np.savez_compressed(
            self.path,
            trame=np.array([f.index for f in frames], dtype=np.int64),
            timestamp=np.array([f.timestamp for f in frames]),
            time=first.time() if first else np.empty(0),
            analog=np.stack([f.analog for f in frames]) if frames else np.empty(0),
            logic=(np.stack([f.logic for f in frames])
                   if first is not None and first.logic is not None else np.empty(0)),
            raw=np.stack([f.raw for f in frames]) if frames else np.empty(0),
            signals=np.array(self.cfg.signals),
            config=json.dumps(self.cfg.to_dict()))
        self._pending = []

    def _write_meta(self):
        meta = {
            "fichier": os.path.basename(self.path),
            "format": self.fmt,
            "debut": self.started.isoformat(timespec="seconds"),
            "frequence_echantillonnage_hz": self.cfg.sample_rate,
            "points_par_voie": self.cfg.samples_per_channel,
            "colonnes": self.columns(),
            "nombre_de_trames": len(self.frames),
            "trames": self.frames,
            "configuration": self.cfg.to_dict(),
        }
        with open(self.meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=1, ensure_ascii=False)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def save_frames(frames: list[Frame], cfg: LoggerConfig, path: str, fmt: str | None = None) -> str:
    """Enregistre une liste de trames (mémoire tampon) dans un seul fichier."""
    if not frames:
        raise ValueError("Aucune trame à enregistrer")
    fmt = fmt or (os.path.splitext(path)[1].lstrip(".").lower() or "csv")
    with FrameRecorder(cfg, fmt, path) as recorder:
        for frame in frames:
            recorder.write(frame)
    return recorder.path


def _iso(timestamp: float) -> str:
    if not timestamp:
        return ""
    return datetime.datetime.fromtimestamp(timestamp).isoformat(timespec="milliseconds")
