# model/loader.py
"""
Relecture d'un enregistrement du logger (model/recorder.py) : trames et configuration.

    load_recording("enr_..._20261103-143012.csv") -> Recording(cfg, frames, ...)

Formats reconnus :
    - csv avec colonne `trame` (un fichier par enregistrement) ;
    - csv de l'ancien format (un fichier par trame : `time_s` en première colonne) ;
    - npz (tableaux par trame).

Configuration (voies, noms, gains, unités, diviseur) : celle du fichier .json écrit à côté
de l'enregistrement. Sans lui, elle est reconstituée depuis l'en-tête du CSV : noms et
unités des colonnes, fréquence d'échantillonnage d'après la colonne des temps ; les
voies analogiques sont alors numérotées 0, 1, 2... et l'heure de capture est inconnue.

Les trames relues sont marquées « enregistrées » (elles sont déjà sur disque) et
« chargées » (frame.meta["loaded"] = chemin du fichier).
"""
from __future__ import annotations

import json
import os
import re
import warnings
from dataclasses import dataclass, field

import numpy as np

from .config import CLOCK_HZ, FULL_SCALE, LOGIC_SIGNAL, LoggerConfig
from .protocol import Frame

_UNIT = re.compile(r"^(?P<name>.*?)\s*\((?P<unit>[^()]*)\)\s*$")


class RecordingError(ValueError):
    """Fichier illisible ou qui n'est pas un enregistrement du logger."""


@dataclass
class Recording:
    path: str
    cfg: LoggerConfig
    frames: list[Frame]
    from_metadata: bool                     # configuration lue dans le .json
    notes: list[str] = field(default_factory=list)


def load_recording(path: str) -> Recording:
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise RecordingError(f"Fichier introuvable : {path}")
    meta = _read_meta(path)
    ext = os.path.splitext(path)[1].lower()
    if ext == ".npz":
        recording = _load_npz(path, meta)
    elif ext in (".csv", ".txt"):
        recording = _load_csv(path, meta)
    else:
        raise RecordingError(f"Format non reconnu : {ext} (attendu : .csv ou .npz)")
    for frame in recording.frames:
        frame.meta["saved"] = path
        frame.meta["loaded"] = path
    return recording


# ------------------------------------------------------------------ métadonnées

def _read_meta(path: str) -> dict | None:
    meta_path = os.path.splitext(path)[0] + ".json"
    if not os.path.isfile(meta_path):
        return None
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, ValueError):
        return None
    return meta if isinstance(meta.get("configuration"), dict) else None


def _timestamps(meta: dict | None) -> dict[int, float]:
    if not meta:
        return {}
    return {int(t["trame"]): float(t.get("timestamp") or 0.0)
            for t in meta.get("trames", []) if "trame" in t}


# ------------------------------------------------------------------ csv

def _load_csv(path: str, meta: dict | None) -> Recording:
    with open(path, encoding="utf-8") as f:
        header = [c.strip() for c in f.readline().strip().split(",")]
    if len(header) < 2:
        raise RecordingError("En-tête CSV absent ou incomplet")
    if header[0] == "trame" and header[1] == "temps_s":
        first_data = 2
        legacy = False
    elif header[0] == "time_s":
        first_data = 1
        legacy = True                     # ancien format : une trame par fichier
    else:
        raise RecordingError("Ce fichier n'est pas un enregistrement du logger : "
                             "colonnes « trame,temps_s,... » attendues")
    try:
        with warnings.catch_warnings():      # fichier sans données : signalé plus bas
            warnings.simplefilter("ignore", UserWarning)
            table = np.loadtxt(path, delimiter=",", skiprows=1, ndmin=2)
    except ValueError as exc:
        raise RecordingError(f"Données illisibles : {exc}") from None
    if table.size == 0:
        raise RecordingError("Aucune donnée dans le fichier")
    if table.shape[1] != len(header):
        raise RecordingError(f"{table.shape[1]} colonnes de données pour "
                             f"{len(header)} colonnes d'en-tête")

    columns = header[first_data:]
    cfg, n_analog, notes = _config_for(columns, table, first_data, meta)
    if legacy:
        index = _legacy_index(path)
        groups = [(index, table)]
    else:
        numbers = table[:, 0].astype(np.int64)
        breaks = np.flatnonzero(np.diff(numbers)) + 1
        groups = [(int(chunk[0, 0]), chunk) for chunk in np.split(table, breaks)]

    stamps = _timestamps(meta)
    frames = []
    for number, chunk in groups:
        data = chunk[:, first_data:]
        analog = np.ascontiguousarray(data[:, :n_analog], dtype=float)
        logic = (np.ascontiguousarray(data[:, n_analog:n_analog + 16]).astype(np.uint8)
                 if cfg.has_logic else None)
        frames.append(_frame(cfg, number, analog, logic, stamps.get(number, 0.0)))
    _check_lengths(frames)
    return Recording(path, cfg, frames, meta is not None, notes)


def _legacy_index(path: str) -> int:
    match = re.search(r"_(\d+)\.[^.]+$", os.path.basename(path))
    return int(match.group(1)) if match else 1


def _config_for(columns: list[str], table: np.ndarray, first_data: int,
                meta: dict | None) -> tuple[LoggerConfig, int, list[str]]:
    """Configuration de l'enregistrement et nombre de colonnes analogiques."""
    notes = []
    if meta is not None:
        cfg = LoggerConfig.from_dict(meta["configuration"])
        n_analog = len(cfg.analog_signals)
        expected = n_analog + (16 if cfg.has_logic else 0)
        if expected != len(columns):
            raise RecordingError(f"Le fichier .json décrit {expected} voies, le CSV en "
                                 f"contient {len(columns)}")
        return cfg, n_analog, notes

    # pas de .json : en-tête du CSV
    has_logic = len(columns) >= 16 and _looks_logic(table[:, first_data + len(columns) - 16:])
    n_analog = len(columns) - (16 if has_logic else 0)
    if n_analog > 15:
        raise RecordingError(f"{n_analog} voies analogiques : 15 au plus")
    cfg = LoggerConfig()
    names, units = list(cfg.analog_names), list(cfg.units)
    signals = list(range(n_analog))
    for i, column in enumerate(columns[:n_analog]):
        match = _UNIT.match(column)
        names[i] = match.group("name") if match else column
        units[i] = match.group("unit") if match else ""
    cfg.analog_names, cfg.units = names, units
    cfg.gains = [1.0] * 15            # valeurs physiques relues telles quelles
    if has_logic:
        cfg.logic_names = columns[n_analog:]
        signals.append(LOGIC_SIGNAL)
    cfg.signals = signals
    t = table[:, first_data - 1]
    steps = np.diff(t)
    dt = float(np.median(steps[steps > 0])) if np.any(steps > 0) else 1.0 / CLOCK_HZ
    cfg.divider = max(1, int(round(CLOCK_HZ * dt)))
    notes.append("pas de fichier .json : configuration reconstituée depuis l'en-tête "
                 "(voies numérotées 0, 1, 2..., heure de capture inconnue)")
    return cfg, n_analog, notes


def _looks_logic(block: np.ndarray) -> bool:
    return block.size > 0 and bool(np.all((block == 0) | (block == 1)))


# ------------------------------------------------------------------ npz

def _load_npz(path: str, meta: dict | None) -> Recording:
    try:
        data = np.load(path, allow_pickle=False)
        cfg = LoggerConfig.from_dict(json.loads(str(data["config"])))
        numbers = data["trame"].astype(np.int64)
        analog = data["analog"]
        logic = data["logic"] if data["logic"].size else None
        stamps = data["timestamp"] if "timestamp" in data else np.zeros(len(numbers))
    except (OSError, KeyError, ValueError) as exc:
        raise RecordingError(f"Fichier npz illisible : {exc}") from None
    frames = [_frame(cfg, int(numbers[k]), np.asarray(analog[k], dtype=float),
                     None if logic is None else np.asarray(logic[k], dtype=np.uint8),
                     float(stamps[k]))
              for k in range(len(numbers))]
    if not frames:
        raise RecordingError("Aucune trame dans le fichier")
    _check_lengths(frames)
    return Recording(path, cfg, frames, True)


# ------------------------------------------------------------------ trames

def _frame(cfg: LoggerConfig, number: int, analog: np.ndarray, logic: np.ndarray | None,
           timestamp: float) -> Frame:
    """Trame reconstituée ; `raw` recalculé depuis les valeurs physiques et les gains."""
    n = analog.shape[0]
    raw = np.zeros((n, cfg.n_channels), dtype=np.int16)
    for j, s in enumerate(cfg.analog_signals):
        gain = cfg.gain(s) or 1.0
        raw[:, j] = np.clip(np.round(analog[:, j] / gain * FULL_SCALE), -32768, 32767)
    if logic is not None:
        word = (logic.astype(np.uint16) << np.arange(16, dtype=np.uint16)).sum(axis=1)
        raw[:, -1] = word.astype(np.uint16).view(np.int16)
    return Frame(index=number, signals=list(cfg.signals), raw=raw, analog=analog,
                 logic=logic, sample_rate=cfg.sample_rate, timestamp=timestamp)


def _check_lengths(frames: list[Frame]):
    lengths = {f.n_samples for f in frames}
    if len(lengths) > 1:
        raise RecordingError(f"Trames de longueurs différentes : {sorted(lengths)}")
