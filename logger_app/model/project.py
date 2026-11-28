# model/project.py
"""
Projet d'enregistrements d'oscilloscope (.lfproj) : ce que l'utilisateur ajoute par-dessus
des workspaces HDF5, sans les mesures (comme le projet .json du GLviewer).

    {
      "format": "loggerfpga_project", "version": 1,
      "records": [{"path": "essai_A.h5", "absolute": "D:/essais/essai_A.h5"}, ...],
      "current": 0,                         // enregistrement affiché à l'enregistrement
      "view": [t0, t1],                     // portion affichée (s)
      "axis_mode": "auto",                  // répartition des axes (controller/y_axes.py)
      "channels": {"CH1": {"y": [lo, hi], "visible": true}, ...},
      "highlighted": "CH1",
      "math_channels": [{"name", "formula", "unit", "enabled"}],
      "axes": {"voie:CH1": {"major": 100.0, "minor": 4, "grid": true}},   // graduations
      "bookmarks": [{"name": "Balise 1", "x": [t0, t1], "y": {"CH1": [lo, hi]},
                     "thumbnail": "<PNG en base64>"}]
    }

Disposition et balises sont rangées par NOM de voie : elles s'appliquent à un autre
enregistrement qui n'a pas les mêmes voies dans le même ordre (une voie absente est
ignorée). Les temps sont en secondes : sur deux enregistrements déclenchés de la même
façon, un événement est au même instant, quelle que soit leur durée.

Chemins des enregistrements : relatifs au dossier du projet (dossier d'essais déplacé ou
copié), avec le chemin absolu en secours. Le décalage dans le temps d'une voie
(recalage) touche aux données : il reste dans le workspace HDF5, pas dans le projet.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from qtsocle import settings

FORMAT = "loggerfpga_project"
VERSION = 1
EXTENSION = ".lfproj"
DIGITS = 10                 # chiffres significatifs gardés pour les plages


class ProjectError(ValueError):
    """Projet illisible (message affichable tel quel)."""


def is_project_file(path: str) -> bool:
    return os.path.splitext(path)[1].lower() == EXTENSION


def _num(value) -> float:
    return float(f"{float(value):.{DIGITS}g}")


def _span(value) -> list[float] | None:
    """[lo, hi] valide (lo < hi, finis), sinon None."""
    try:
        lo, hi = (_num(v) for v in value)
    except (TypeError, ValueError):
        return None
    if not (lo < hi) or lo != lo or hi != hi or abs(lo) == float("inf") \
            or abs(hi) == float("inf"):
        return None
    return [lo, hi]


@dataclass
class Bookmark:
    """Zone d'intérêt : portion de temps et plages verticales des voies."""
    name: str
    x: list[float]
    y: dict[str, list[float]] = field(default_factory=dict)
    thumbnail: str = ""         # PNG en base64 (vignette prise à la création)

    def zoom(self, duration: float) -> float:
        """Grossissement par rapport à l'enregistrement entier."""
        width = self.x[1] - self.x[0]
        return duration / width if width > 0 else 0.0

    def position(self, t0: float, duration: float) -> float:
        """Centre de la zone, en part de l'enregistrement (0 à 1)."""
        return ((self.x[0] + self.x[1]) / 2 - t0) / duration if duration > 0 else 0.0

    def to_dict(self) -> dict:
        return {"name": self.name, "x": [_num(v) for v in self.x],
                "y": {name: [_num(v) for v in span] for name, span in self.y.items()},
                "thumbnail": self.thumbnail}

    @classmethod
    def from_dict(cls, data: dict) -> "Bookmark":
        x = _span(data.get("x"))
        if x is None:
            raise ProjectError(f"Balise « {data.get('name', '?')} » : portion de temps "
                               f"invalide")
        y = {}
        for name, span in dict(data.get("y") or {}).items():
            span = _span(span)
            if span is not None:
                y[str(name)] = span
        return cls(name=str(data.get("name") or "Balise"), x=x, y=y,
                   thumbnail=str(data.get("thumbnail") or ""))


@dataclass
class Project:
    records: list[str] = field(default_factory=list)       # chemins absolus
    current: str | None = None
    view: list[float] | None = None
    axis_mode: str = "auto"
    channels: dict[str, dict] = field(default_factory=dict)
    highlighted: str | None = None
    math_channels: list[dict] = field(default_factory=list)
    bookmarks: list[Bookmark] = field(default_factory=list)
    # graduations et grille par clé d'axe (controller/scale_controller.py)
    axes: dict[str, dict] = field(default_factory=dict)

    # ------------------------------------------------------------------ enregistrements
    def add_record(self, path: str) -> bool:
        """Enregistrement ajouté au projet (une seule fois) ; vrai s'il est nouveau."""
        path = os.path.abspath(path)
        if any(os.path.normcase(p) == os.path.normcase(path) for p in self.records):
            return False
        self.records.append(path)
        return True

    def remove_record(self, path: str):
        key = os.path.normcase(os.path.abspath(path))
        self.records = [p for p in self.records if os.path.normcase(p) != key]

    # ------------------------------------------------------------------ disposition
    def merge_channels(self, channels: dict[str, dict]):
        """Disposition des voies affichées ; celles des autres enregistrements gardées."""
        for name, layout in channels.items():
            self.channels[name] = dict(layout)

    # ------------------------------------------------------------------ fichier
    def to_dict(self, base_dir: str) -> dict:
        records = []
        for path in self.records:
            try:
                relative = os.path.relpath(path, base_dir)
            except ValueError:              # Windows : autre lecteur
                relative = path
            records.append({"path": relative.replace(os.sep, "/"),
                            "absolute": path.replace(os.sep, "/")})
        current = None
        if self.current is not None:
            key = os.path.normcase(os.path.abspath(self.current))
            current = next((k for k, p in enumerate(self.records)
                            if os.path.normcase(p) == key), None)
        channels = {}
        for name, layout in self.channels.items():
            entry = {"visible": bool(layout.get("visible", True))}
            span = _span(layout.get("y"))
            if span is not None:
                entry["y"] = span
            channels[name] = entry
        return {"format": FORMAT, "version": VERSION, "records": records,
                "current": current, "view": _span(self.view) if self.view else None,
                "axis_mode": self.axis_mode, "channels": channels,
                "highlighted": self.highlighted,
                "math_channels": [dict(d) for d in self.math_channels],
                "bookmarks": [b.to_dict() for b in self.bookmarks],
                "axes": {key: {"major": _num(v.get("major") or 0.0),
                               "minor": int(v.get("minor") or 0), "grid": v.get("grid")}
                         for key, v in self.axes.items()}}

    @classmethod
    def from_dict(cls, data: dict, base_dir: str) -> "Project":
        if not isinstance(data, dict) or data.get("format") != FORMAT:
            raise ProjectError("Ce fichier n'est pas un projet du logger FPGA")
        version = data.get("version", 0)
        if not isinstance(version, int) or version > VERSION:
            raise ProjectError(f"Projet de version {version} : mettre à jour le logger "
                               f"(version {VERSION} reconnue)")
        records = []
        for entry in data.get("records") or []:
            if isinstance(entry, str):
                entry = {"path": entry}
            relative = str(entry.get("path") or "")
            absolute = str(entry.get("absolute") or "")
            path = os.path.normpath(os.path.join(base_dir, relative)) if relative else ""
            if (not path or not os.path.exists(path)) and absolute:
                path = os.path.normpath(absolute)       # projet déplacé seul
            if path:
                records.append(path)
        current = data.get("current")
        current = records[current] if isinstance(current, int) \
            and 0 <= current < len(records) else None
        channels = {}
        for name, layout in dict(data.get("channels") or {}).items():
            if not isinstance(layout, dict):
                continue
            entry = {"visible": bool(layout.get("visible", True))}
            span = _span(layout.get("y"))
            if span is not None:
                entry["y"] = span
            channels[str(name)] = entry
        highlighted = data.get("highlighted")
        axes = {}
        for key, value in dict(data.get("axes") or {}).items():
            if not isinstance(value, dict):
                continue
            try:
                major, minor = abs(float(value.get("major") or 0.0)), int(value.get("minor") or 0)
            except (TypeError, ValueError):
                continue
            grid = value.get("grid")
            axes[str(key)] = {"major": major, "minor": max(0, min(minor, 20)),
                              "grid": None if grid is None else bool(grid)}
        return cls(records=records, current=current,
                   view=_span(data.get("view")) if data.get("view") else None,
                   axis_mode=str(data.get("axis_mode") or "auto"), channels=channels,
                   highlighted=str(highlighted) if highlighted else None,
                   math_channels=[dict(d) for d in data.get("math_channels") or []
                                  if isinstance(d, dict)],
                   bookmarks=[Bookmark.from_dict(b) for b in data.get("bookmarks") or []
                              if isinstance(b, dict)],
                   axes=axes)

    def save(self, path: str):
        """Écriture sûre (fichier voisin puis remplacement, qtsocle.settings)."""
        path = os.path.abspath(path)
        try:
            settings.save(path, self.to_dict(os.path.dirname(path)))
        except OSError as exc:
            raise ProjectError(f"Projet non enregistré : {exc}") from None

    @classmethod
    def load(cls, path: str) -> "Project":
        path = os.path.abspath(path)
        try:
            with open(path, encoding="utf-8") as stream:
                data = json.load(stream)
        except OSError as exc:
            raise ProjectError(f"Projet illisible : {exc}") from None
        except ValueError:
            raise ProjectError(f"Projet illisible : {os.path.basename(path)} n'est pas "
                               f"un fichier JSON valide") from None
        return cls.from_dict(data, os.path.dirname(path))
