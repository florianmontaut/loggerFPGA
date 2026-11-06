# model/scope_record.py
"""
Enregistrements longs d'oscilloscope (Tektronix DPO7054...) : import CSV -> HDF5 et
lecture de la portion affichée.

Format CSV Tektronix (un ou plusieurs signaux) ; les données commencent dès la ligne 0 :
    col 0, 1, 2 : métadonnées sur les premières lignes (clé, valeur, unité), vides ensuite
    col 3       : temps (s)
    col 4, 5... : signal 1, signal 2...

    "Record Length",25000000,"Points",1.25499980e+000,-4.80000004e-001
    "Sample Interval",2.00000000e-007,s,1.25500000e+000,-6.40000004e-001
    ...
    ,,,1.25500100e+000,-3.20000004e-001

Noms des voies (même règle que csv_to_hdf5.py) : les lignes de métadonnées dont la clé
n'est pas une des KNOWN_KEYS, une par voie dans l'ordre des colonnes 4, 5... ; à défaut
CH1, CH2... Plusieurs fichiers d'un signal chacun : le nom du fichier, ou CHn s'il y
figure (tek0001CH2.csv -> CH2).

Fichier HDF5 « workspace », même structure que csv_to_hdf5.py (projet HDF5_viewer), donc
lisible par les deux outils :
    attrs : format, sample_interval, horizontal_offset, trigger_point, trigger_time,
            record_length_declared, record_length_imported, signal_count, metadata_json,
            time_origin (temps du premier échantillon, ajouté par le logger)
    /signals/<nom>/raw/value                    signal brut (float32)
    /signals/<nom>/overview/min, max            vue d'ensemble (~4096 colonnes)
    /signals/<nom>/pyramid/level_XX/min, max    pyramide min/max (attr samples_per_bin)

Lecture (ScopeRecord.read_window) : données brutes si la portion demandée compte au plus
`max_raw` points par voie, sinon enveloppe min/max tirée du niveau de pyramide adapté.
"""
from __future__ import annotations

import itertools
import json
import math
import os
import re
import shutil
import warnings
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

try:
    import h5py
except ImportError:                       # message clair à l'usage plutôt qu'à l'import
    h5py = None

FORMAT = "scope_hdf5_workspace"
KNOWN_KEYS = ("record_length", "sample_interval", "trigger_point", "trigger_time",
              "horizontal_offset")
CSV_CHUNK_ROWS = 1_000_000
RAW_CHUNK = 1_000_000
PYRAMID_FACTOR = 4
PYRAMID_MIN_BINS = 4096
OVERVIEW_WIDTH = 4096
MAX_RAW_POINTS = 2_000_000          # au-delà : enveloppe min/max
TARGET_BINS = 4000                  # colonnes d'enveloppe visées (~ largeur d'écran x 2)


class ScopeError(ValueError):
    """Fichier d'oscilloscope illisible ou incohérent."""


class ImportCancelled(Exception):
    pass


def _require_h5py():
    if h5py is None:
        raise ScopeError("Le module h5py est nécessaire pour les enregistrements longs "
                         "(pip install h5py)")


# ------------------------------------------------------------------ CSV Tektronix

def _number(text: str):
    try:
        value = float(text)
    except ValueError:
        return text
    return int(value) if value.is_integer() else value


def is_tek_csv(path: str) -> bool:
    """Premier enregistrement : ≥ 5 colonnes, colonnes 3 et 4 numériques."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            cells = [c.strip().strip('"') for c in f.readline().split(",")]
    except OSError:
        return False
    if len(cells) < 5:
        return False
    try:
        float(cells[3]), float(cells[4])
    except ValueError:
        return False
    return True


@dataclass
class TekHeader:
    path: str
    metadata: dict            # clé normalisée -> {"label", "value", "unit"}
    n_signals: int
    first_time: float
    # clés de métadonnées autres que KNOWN_KEYS, dans l'ordre : noms des voies (même règle
    # que csv_to_hdf5.py de HDF5_viewer)
    extra_keys: list = field(default_factory=list)

    def value(self, key, default=None):
        item = self.metadata.get(key)
        return default if item is None else item["value"]


def read_tek_header(path: str, max_lines: int = 100) -> TekHeader:
    metadata = {}
    extra = []
    n_cols = None
    first_time = None
    with open(path, encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f):
            if i >= max_lines:
                break
            cells = [c.strip() for c in line.rstrip("\r\n").split(",")]
            if n_cols is None:
                n_cols = len(cells)
                if n_cols < 5:
                    raise ScopeError(f"{os.path.basename(path)} : {n_cols} colonnes, au moins "
                                     f"5 attendues (métadonnées, temps, signal)")
                try:
                    first_time = float(cells[3])
                except ValueError:
                    raise ScopeError(f"{os.path.basename(path)} : colonne 4 (temps) non "
                                     f"numérique, format Tektronix attendu") from None
            key = cells[0].strip('"') if cells else ""
            if not key:
                continue
            normalized = key.lower().replace(" ", "_").replace("-", "_")
            if normalized not in KNOWN_KEYS:
                extra.append(key)
            metadata[normalized] = {"label": key,
                                    "value": _number(cells[1].strip('"')) if len(cells) > 1 else "",
                                    "unit": cells[2].strip('"') if len(cells) > 2 else ""}
    if n_cols is None:
        raise ScopeError(f"{os.path.basename(path)} : fichier vide")
    return TekHeader(path, metadata, n_cols - 4, first_time, extra)


def default_names(paths: list[str], headers: list[TekHeader],
                  by_file: bool = False) -> list[str]:
    """
    Noms des voies, fichier par fichier :
        1. lignes de métadonnées supplémentaires, une par voie (règle de csv_to_hdf5.py) ;
        2. plusieurs fichiers (ou ajout à un enregistrement : by_file) : CHn du nom de
           fichier, sinon le nom du fichier (tek0000CH2.csv -> CH2) ;
        3. un seul fichier : CH1, CH2... dans l'ordre des colonnes.
    """
    names = []
    for path, header in zip(paths, headers):
        if header.extra_keys and len(header.extra_keys) == header.n_signals:
            names += list(header.extra_keys)
        elif len(paths) == 1 and not by_file:
            names += [f"CH{k + 1}" for k in range(header.n_signals)]
        else:
            stem = os.path.splitext(os.path.basename(path))[0]
            match = re.search(r"(CH\d+|MATH\d+|REF\d+)", stem, re.IGNORECASE)
            base = match.group(1).upper() if match else stem
            names += ([base] if header.n_signals == 1 else
                      [f"{base}_{k + 1}" for k in range(header.n_signals)])
    unique, seen = [], {}
    for name in names:
        seen[name] = seen.get(name, 0) + 1
        unique.append(name if seen[name] == 1 else f"{name}_{seen[name]}")
    return unique


def default_h5_path(paths: list[str]) -> str:
    base = os.path.splitext(paths[0])[0]
    return base + ("_voies.h5" if len(paths) > 1 else ".h5")


def import_tek_csv(paths: list[str], h5_path: str, names: list[str] | None = None,
                   progress: Callable[[float, str], None] | None = None,
                   cancelled: Callable[[], bool] | None = None,
                   chunk_rows: int = CSV_CHUNK_ROWS, dtype=np.float32) -> str:
    """
    Convertit un ou plusieurs CSV Tektronix (mêmes instants) en workspace HDF5.
    progress(fraction, texte) ; cancelled() -> True : import interrompu, fichier effacé.
    """
    _require_h5py()
    paths = [os.path.abspath(p) for p in paths]
    headers = [read_tek_header(p) for p in paths]
    names = list(names) if names else default_names(paths, headers)
    if len(names) != sum(h.n_signals for h in headers):
        raise ScopeError("Nombre de noms différent du nombre de voies")
    ref = headers[0]
    dt = ref.value("sample_interval")
    sizes = [os.path.getsize(p) for p in paths]
    total = float(sum(sizes)) or 1.0
    report = progress or (lambda f, t: None)
    stop = cancelled or (lambda: False)

    tmp_path = h5_path + ".partiel"
    try:
        with h5py.File(tmp_path, "w") as h5:
            _write_attrs(h5, headers, paths)
            signals = h5.create_group("signals")
            length = None
            done = 0.0
            column = 0
            for path, header, size in zip(paths, headers, sizes):
                own = names[column:column + header.n_signals]
                column += header.n_signals
                n, file_dt = _import_file(path, header, own, signals, length, dtype,
                                          chunk_rows, lambda f: report((done + f * size) / total
                                                                       * 0.8, f"Lecture de "
                                                                       f"{os.path.basename(path)}"),
                                          stop)
                if length is None:
                    length = n
                    dt = dt or file_dt
                elif n != length:
                    raise ScopeError(f"{os.path.basename(path)} : {n} points, {length} "
                                     f"attendus (mêmes instants pour tous les fichiers)")
                if abs(header.first_time - ref.first_time) > abs(dt or 0):
                    raise ScopeError(f"{os.path.basename(path)} commence à "
                                     f"{header.first_time} s, {ref.first_time} s attendu")
                done += size
            if not dt or dt <= 0:
                raise ScopeError("Intervalle d'échantillonnage introuvable")
            h5.attrs["sample_interval"] = float(dt)
            h5.attrs["record_length_imported"] = int(length)
            h5.attrs["signal_count"] = len(names)
            for k, name in enumerate(names):
                report(0.8 + 0.2 * k / len(names), f"Pyramide de {name}")
                if stop():
                    raise ImportCancelled()
                _overview(signals[name])
                _pyramid(signals[name], stop)
            report(1.0, "Terminé")
        os.replace(tmp_path, h5_path)
    except BaseException:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
    return h5_path


def _unique(name: str, used: set) -> str:
    candidate, k = name, 1
    while candidate in used:
        k += 1
        candidate = f"{name}_{k}"
    used.add(candidate)
    return candidate


def append_to_workspace(h5_path: str, sources: list[str],
                        progress: Callable[[float, str], None] | None = None,
                        cancelled: Callable[[], bool] | None = None,
                        chunk_rows: int = CSV_CHUNK_ROWS, dtype=np.float32) -> list[str]:
    """
    Ajoute à un workspace HDF5 les voies de CSV Tektronix ou d'autres workspaces .h5
    (un oscilloscope Tektronix écrit un CSV par voie). Les voies ajoutées doivent avoir le
    même intervalle d'échantillonnage, le même nombre de points et commencer au même
    instant. Un nom déjà pris reçoit un suffixe (_2...).

    L'ajout se fait dans une copie, qui remplace le fichier seulement en cas de succès :
    annulation, erreur ou coupure laissent le workspace intact. Renvoie les noms ajoutés.
    """
    _require_h5py()
    h5_path = os.path.abspath(h5_path)
    sources = [os.path.abspath(p) for p in sources]
    report = progress or (lambda f, t: None)
    stop = cancelled or (lambda: False)
    csvs = [p for p in sources if os.path.splitext(p)[1].lower() == ".csv"]
    others = [p for p in sources if p not in csvs]
    for path in csvs:
        if not is_tek_csv(path):
            raise ScopeError(f"{os.path.basename(path)} : format Tektronix non reconnu")
    if os.path.abspath(h5_path) in others:
        raise ScopeError("Un enregistrement ne peut pas être ajouté à lui-même")

    tmp_path = h5_path + ".partiel"
    report(0.0, "Copie de l'enregistrement")
    shutil.copyfile(h5_path, tmp_path)
    added = []
    try:
        with h5py.File(tmp_path, "a") as h5:
            signals = h5["signals"]
            dt = float(h5.attrs.get("sample_interval", 0.0) or 0.0)
            if dt <= 0:
                raise ScopeError("Intervalle d'échantillonnage absent de l'enregistrement")
            present = [n for n in signals if "raw" in signals[n] and "value" in signals[n]["raw"]]
            length = min(signals[n]["raw/value"].shape[0] for n in present)
            t0 = float(h5.attrs["time_origin"]) if "time_origin" in h5.attrs else None
            used = set(signals)

            # CSV Tektronix
            headers = [read_tek_header(p) for p in csvs]
            names = default_names(csvs, headers, by_file=True) if csvs else []
            sizes = [os.path.getsize(p) for p in csvs]
            total = float(sum(sizes)) or 1.0
            done, column = 0.0, 0
            for path, header, size in zip(csvs, headers, sizes):
                label = os.path.basename(path)
                file_dt = header.value("sample_interval")
                if isinstance(file_dt, (int, float)) and abs(file_dt - dt) > 1e-9 * dt:
                    raise ScopeError(f"{label} : échantillonnage {file_dt} s, {dt} s attendu")
                if t0 is not None and abs(header.first_time - t0) > dt:
                    raise ScopeError(f"{label} commence à {header.first_time} s, {t0} s "
                                     f"attendu (même acquisition que l'enregistrement)")
                own = [_unique(n, used) for n in names[column:column + header.n_signals]]
                column += header.n_signals
                n, _ = _import_file(path, header, own, signals, length, dtype, chunk_rows,
                                    lambda f: report((done + f * size) / total * 0.8,
                                                     f"Lecture de {label}"), stop)
                if n != length:
                    raise ScopeError(f"{label} : {n} points, {length} attendus (même "
                                     f"acquisition que l'enregistrement)")
                added += own
                done += size

            # autres workspaces HDF5 : voies copiées avec leur pyramide
            for path in others:
                label = os.path.basename(path)
                try:
                    source = h5py.File(path, "r")
                except OSError as exc:
                    raise ScopeError(f"{label} : HDF5 illisible ({exc})") from None
                with source:
                    if "signals" not in source:
                        raise ScopeError(f"{label} : pas un workspace d'oscilloscope")
                    src_dt = float(source.attrs.get("sample_interval", 0.0) or 0.0)
                    if abs(src_dt - dt) > 1e-9 * dt:
                        raise ScopeError(f"{label} : échantillonnage {src_dt} s, {dt} s attendu")
                    if t0 is not None and "time_origin" in source.attrs and \
                            abs(float(source.attrs["time_origin"]) - t0) > dt:
                        raise ScopeError(f"{label} : ne commence pas au même instant")
                    for name in source["signals"]:
                        group = source[f"signals/{name}"]
                        if "raw/value" not in group:
                            continue
                        if group["raw/value"].shape[0] != length:
                            raise ScopeError(f"{label}, {name} : {group['raw/value'].shape[0]} "
                                             f"points, {length} attendus")
                        if stop():
                            raise ImportCancelled()
                        new = _unique(name, used)
                        source.copy(group, signals, name=new)
                        signals[new].attrs["name"] = new
                        signals[new].attrs["source_file"] = label
                        added.append(new)

            # rang d'affichage après les voies existantes ; pyramides des voies des CSV
            for k, name in enumerate(added):
                signals[name].attrs["index"] = len(present) + k
            csv_names = [n for n in added if "overview" not in signals[n]
                         or "min" not in signals[n]["overview"]]
            for k, name in enumerate(csv_names):
                report(0.8 + 0.2 * k / max(len(csv_names), 1), f"Pyramide de {name}")
                if stop():
                    raise ImportCancelled()
                _overview(signals[name])
                _pyramid(signals[name], stop)
            files = json.loads(h5.attrs.get("source_files", "[]"))
            h5.attrs["source_files"] = json.dumps(files + [os.path.basename(p) for p in sources])
            h5.attrs["signal_count"] = len(present) + len(added)
            report(1.0, "Terminé")
        os.replace(tmp_path, h5_path)
    except BaseException:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
    return added


def _write_attrs(h5, headers: list[TekHeader], paths: list[str]):
    ref = headers[0]
    h5.attrs["format"] = FORMAT
    h5.attrs["format_version"] = "0.1"
    h5.attrs["created_by"] = "loggerFPGA"
    h5.attrs["metadata_json"] = json.dumps(ref.metadata, indent=2)
    h5.attrs["source_files"] = json.dumps([os.path.basename(p) for p in paths])
    h5.attrs["time_origin"] = float(ref.first_time)
    for key, cast, attr in (("horizontal_offset", float, "horizontal_offset"),
                            ("trigger_point", int, "trigger_point"),
                            ("trigger_time", float, "trigger_time"),
                            ("record_length", int, "record_length_declared")):
        value = ref.value(key)
        if isinstance(value, (int, float)):
            h5.attrs[attr] = cast(value)


def _import_file(path, header: TekHeader, names, signals, expected, dtype, chunk_rows,
                 progress, stop) -> tuple[int, float | None]:
    cols = tuple(range(3, 4 + header.n_signals))
    declared = header.value("record_length")
    capacity = expected or (declared if isinstance(declared, int) and declared > 0 else None)
    datasets = []
    for k, name in enumerate(names):
        group = signals.create_group(name)
        group.attrs["index"] = len(signals) - 1
        group.attrs["name"] = name
        group.attrs["source_column"] = 4 + k
        group.attrs["source_file"] = os.path.basename(path)
        group.create_group("overview")
        group.create_group("pyramid")
        raw = group.create_group("raw")
        datasets.append(raw.create_dataset("value", shape=(capacity or 0,), maxshape=(None,),
                                           dtype=dtype, chunks=(min(RAW_CHUNK, max(capacity or RAW_CHUNK, 1)),)))
    size = os.path.getsize(path) or 1
    n = 0
    read_chars = 0                   # avancement (tell() indisponible en itération)
    dt = None
    with open(path, encoding="utf-8", errors="replace") as f:
        while True:
            if stop():
                raise ImportCancelled()
            lines = list(itertools.islice(f, chunk_rows))
            if not lines:
                break
            read_chars += sum(map(len, lines))
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", UserWarning)
                    block = np.loadtxt(lines, delimiter=",", usecols=cols, ndmin=2,
                                       quotechar='"')
            except ValueError as exc:
                raise ScopeError(f"{os.path.basename(path)}, lignes {n + 1} à "
                                 f"{n + len(lines)} : {exc}") from None
            if dt is None and block.shape[0] > 1:
                dt = float(np.median(np.diff(block[: min(1000, block.shape[0]), 0])))
            m = block.shape[0]
            for k, dset in enumerate(datasets):
                if n + m > dset.shape[0]:
                    dset.resize((n + m,))
                dset[n:n + m] = block[:, 1 + k]
            n += m
            progress(min(read_chars / size, 1.0))
    if n == 0:
        raise ScopeError(f"{os.path.basename(path)} : aucune donnée")
    for dset in datasets:
        if dset.shape[0] != n:
            dset.resize((n,))
    return n, dt


def _reduce(values: np.ndarray, factor: int) -> tuple[np.ndarray, np.ndarray]:
    usable = (len(values) // factor) * factor
    mins = values[:usable].reshape(-1, factor).min(axis=1)
    maxs = values[:usable].reshape(-1, factor).max(axis=1)
    if usable < len(values):
        mins = np.append(mins, values[usable:].min())
        maxs = np.append(maxs, values[usable:].max())
    return mins, maxs


def _overview(group):
    """Vue d'ensemble : min / max de ~OVERVIEW_WIDTH tranches, raw lu par blocs."""
    raw = group["raw/value"]
    n = raw.shape[0]
    width = min(OVERVIEW_WIDTH, n)
    edges = np.linspace(0, n, width + 1).astype(np.int64)
    mins = np.full(width, np.inf)
    maxs = np.full(width, -np.inf)
    for start in range(0, n, RAW_CHUNK):
        stop = min(start + RAW_CHUNK, n)
        block = np.asarray(raw[start:stop], dtype=float)
        first = int(np.searchsorted(edges, start, side="right")) - 1
        last = int(np.searchsorted(edges, stop - 1, side="right")) - 1
        offsets = np.concatenate(([0], edges[first + 1:last + 1] - start)).astype(np.int64)
        np.minimum.at(mins, np.arange(first, last + 1), np.minimum.reduceat(block, offsets))
        np.maximum.at(maxs, np.arange(first, last + 1), np.maximum.reduceat(block, offsets))
    out = group["overview"]
    for key, data in (("min", mins), ("max", maxs)):
        if key in out:
            del out[key]
        out.create_dataset(key, data=data.astype(raw.dtype))
    out.attrs["width"] = int(width)
    out.attrs["source_length"] = int(n)


def _pyramid(group, stop):
    pyramid = group["pyramid"]
    source_min = source_max = group["raw/value"]
    spb = 1
    level = 0
    while source_min.shape[0] > PYRAMID_MIN_BINS:
        if stop():
            raise ImportCancelled()
        level += 1
        spb *= PYRAMID_FACTOR
        n = source_min.shape[0]
        out_len = math.ceil(n / PYRAMID_FACTOR)
        lvl = pyramid.create_group(f"level_{level:02d}")
        lvl.attrs.update({"level": level, "samples_per_bin": spb, "source_length": n,
                          "block_size" if level == 1 else "factor_from_previous": PYRAMID_FACTOR,
                          "source": "raw/value" if level == 1 else f"level_{level - 1:02d}"})
        dmin = lvl.create_dataset("min", shape=(out_len,), dtype=source_min.dtype,
                                  chunks=(min(out_len, RAW_CHUNK),))
        dmax = lvl.create_dataset("max", shape=(out_len,), dtype=source_min.dtype,
                                  chunks=(min(out_len, RAW_CHUNK),))
        step = RAW_CHUNK * PYRAMID_FACTOR
        for start in range(0, n, step):
            end = min(start + step, n)
            mins, _ = _reduce(source_min[start:end], PYRAMID_FACTOR)
            _, maxs = _reduce(source_max[start:end], PYRAMID_FACTOR)
            dmin[start // PYRAMID_FACTOR:start // PYRAMID_FACTOR + len(mins)] = mins
            dmax[start // PYRAMID_FACTOR:start // PYRAMID_FACTOR + len(maxs)] = maxs
        source_min, source_max = dmin, dmax
    pyramid.attrs["factor"] = PYRAMID_FACTOR
    pyramid.attrs["levels"] = level


# ------------------------------------------------------------------ lecture

@dataclass
class Window:
    """Portion lue : x(i) = x0 + i * step ; enveloppe : min et max alternés."""
    x0: float
    step: float
    data: dict                     # nom -> np.ndarray (float64)
    envelope: bool
    samples_per_bin: int = 1       # 1 : données brutes
    first_index: int = 0           # premier échantillon brut couvert
    last_index: int = 0


class ScopeRecord:
    """Workspace HDF5 ouvert en lecture (le logger ou csv_to_hdf5.py de HDF5_viewer)."""

    def __init__(self, path: str):
        _require_h5py()
        self.path = os.path.abspath(path)
        try:
            self.h5 = h5py.File(self.path, "r")
        except OSError as exc:
            raise ScopeError(f"Fichier HDF5 illisible : {exc}") from None
        if "signals" not in self.h5:
            self.close()
            raise ScopeError("Groupe /signals absent : pas un workspace d'oscilloscope")
        # ordre des voies : attribut index (HDF5 range les groupes par ordre alphabétique)
        present = [name for name in self.h5["signals"]
                   if f"signals/{name}/raw/value" in self.h5]
        self.names = sorted(present, key=lambda name: (
            int(self.h5[f"signals/{name}"].attrs.get("index", len(present))), name))
        if not self.names:
            self.close()
            raise ScopeError("Aucune voie dans le fichier")
        lengths = {self.raw(name).shape[0] for name in self.names}
        self.length = min(lengths)
        attrs = self.h5.attrs
        self.dt = float(attrs.get("sample_interval", 0.0) or 0.0)
        if self.dt <= 0:
            self.close()
            raise ScopeError("Intervalle d'échantillonnage (sample_interval) absent")
        self.t0 = float(attrs.get("time_origin", attrs.get("horizontal_offset", 0.0)))
        try:
            self.metadata = json.loads(attrs.get("metadata_json", "{}"))
        except ValueError:
            self.metadata = {}
        self.levels = {name: self._levels(name) for name in self.names}

    def close(self):
        if getattr(self, "h5", None) is not None:
            self.h5.close()
            self.h5 = None

    def raw(self, name):
        return self.h5[f"signals/{name}/raw/value"]

    def _levels(self, name) -> list[tuple[int, str]]:
        path = f"signals/{name}/pyramid"
        if path not in self.h5:
            return []
        out = []
        for key, group in self.h5[path].items():
            if key.startswith("level_") and "min" in group and "max" in group:
                out.append((int(group.attrs.get("samples_per_bin", 1)), key))
        return sorted(out)

    @property
    def duration(self) -> float:
        return self.length * self.dt

    @property
    def sample_rate(self) -> float:
        return 1.0 / self.dt

    def time_of(self, index: float) -> float:
        return self.t0 + index * self.dt

    def index_of(self, t: float) -> int:
        return int(min(max(round((t - self.t0) / self.dt), 0), self.length))

    def overview(self) -> Window:
        """Vue d'ensemble de tout l'enregistrement (enveloppe)."""
        return self.read_window(0, self.length, max_raw=OVERVIEW_WIDTH * 2,
                                target_bins=OVERVIEW_WIDTH)

    def read_window(self, start: int, stop: int, max_raw: int = MAX_RAW_POINTS,
                    target_bins: int = TARGET_BINS) -> Window:
        start = max(0, min(int(start), self.length - 1))
        stop = max(start + 1, min(int(stop), self.length))
        n = stop - start
        if n <= max_raw:
            data = {name: np.asarray(self.raw(name)[start:stop], dtype=float)
                    for name in self.names}
            return Window(self.time_of(start), self.dt, data, False, 1, start, stop)
        wanted = n / target_bins
        data = {}
        spb_used = None
        for name in self.names:
            levels = [lv for lv in self.levels[name] if lv[0] <= wanted] or self.levels[name][:1]
            if levels:
                spb, key = levels[-1]
                group = self.h5[f"signals/{name}/pyramid/{key}"]
                b0, b1 = start // spb, math.ceil(stop / spb)
                mins = np.asarray(group["min"][b0:b1], dtype=float)
                maxs = np.asarray(group["max"][b0:b1], dtype=float)
            else:                      # pas de pyramide : sous-échantillonnage min/max
                spb = max(1, int(wanted))
                b0 = start // spb
                block = np.asarray(self.raw(name)[b0 * spb:stop], dtype=float)
                mins, maxs = _reduce(block, spb)
            if spb_used is None:
                spb_used, first = spb, b0
            m = min(len(mins), len(maxs))
            env = np.empty(2 * m)
            env[0::2], env[1::2] = mins[:m], maxs[:m]
            data[name] = env
        common = min(len(v) for v in data.values())
        data = {k: v[:common] for k, v in data.items()}
        return Window(self.time_of(first * spb_used), spb_used * self.dt / 2, data, True,
                      spb_used, first * spb_used, min(self.length, (first + common // 2) * spb_used))
