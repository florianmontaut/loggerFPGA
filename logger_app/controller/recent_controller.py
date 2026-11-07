# controller/recent_controller.py
"""
Fichiers récents et dernier répertoire visité (comme le menu « Recent files » du GLviewer).

    Fichier › Fichiers récents
        1  enr_I_HV_..._20261104-193948.csv      (logger)
        2  tek0000CH1_voies.h5                   (oscilloscope)
        3  essai_banc.json                       (configuration)
        ...
        Effacer la liste

    - les MAX_RECENT derniers fichiers chargés avec succès, le plus récent en tête, sans
      doublon ; un clic le rouvre comme il avait été chargé (relecture dans la mémoire
      tampon, enregistrement d'oscilloscope, configuration) ;
    - un fichier disparu est signalé et retiré de la liste ;
    - dernier répertoire : celui du dernier fichier chargé ; les boîtes d'ouverture
      (enregistrement, ajout de voies, configuration) s'y ouvrent ;
    - liste et répertoire conservés d'une session à l'autre (QSettings) ; sans QSettings
      (tests), seulement pour la session.

Entrée : {"kind": "logger" | "scope" | "config", "paths": [chemins]}. Pour un
enregistrement d'oscilloscope, c'est le workspace .h5 qui est retenu : il contient les
voies ajoutées et se rouvre sans nouvelle conversion.
"""
from __future__ import annotations

import json
import os
from typing import Callable

from PyQt6 import QtCore, QtGui, QtWidgets

MAX_RECENT = 10
KINDS = {"logger": "logger", "scope": "oscilloscope", "config": "configuration"}
KEY_FILES = "recent/files"
KEY_DIR = "recent/last_dir"


class RecentFilesController(QtCore.QObject):

    open_requested = QtCore.pyqtSignal(dict)      # entrée choisie dans le menu
    missing = QtCore.pyqtSignal(dict)             # entrée dont un fichier a disparu

    def __init__(self, menu: QtWidgets.QMenu, settings: QtCore.QSettings | None,
                 fallback_dir: Callable[[], str]):
        super().__init__()
        self.menu = menu
        self.settings = settings
        self.fallback_dir = fallback_dir
        self.entries: list[dict] = []
        self._last_dir = ""
        self._load()
        self._rebuild()

    # ------------------------------------------------------------------ dernier répertoire
    @property
    def last_dir(self) -> str:
        """Répertoire du dernier fichier chargé (s'il existe encore), sinon celui par défaut."""
        if self._last_dir and os.path.isdir(self._last_dir):
            return self._last_dir
        return self.fallback_dir()

    def set_last_dir(self, path: str):
        """Répertoire visité : celui de `path` (fichier) ou `path` lui-même (dossier)."""
        directory = path if os.path.isdir(path) else os.path.dirname(os.path.abspath(path))
        if directory:
            self._last_dir = directory
            self._save()

    # ------------------------------------------------------------------ liste
    def add(self, kind: str, paths: list[str], visited: str | None = None):
        """
        Fichier chargé avec succès : en tête de liste. `visited` : fichier dont le dossier
        devient le dernier répertoire (par défaut le premier de `paths`).
        """
        if kind not in KINDS or not paths:
            return
        paths = [os.path.abspath(p) for p in paths]
        entry = {"kind": kind, "paths": paths}
        self.entries = [e for e in self.entries
                        if not (e["kind"] == kind and e["paths"] == paths)]
        self.entries.insert(0, entry)
        del self.entries[MAX_RECENT:]
        self.set_last_dir(visited or paths[0])      # enregistre aussi la liste
        self._rebuild()

    def remove(self, entry: dict):
        self.entries = [e for e in self.entries if e != entry]
        self._save()
        self._rebuild()

    def clear(self):
        self.entries = []
        self._save()
        self._rebuild()

    @staticmethod
    def label(entry: dict) -> str:
        names = [os.path.basename(p) for p in entry["paths"]]
        text = names[0] + (f" (+{len(names) - 1})" if len(names) > 1 else "")
        return f"{text}    ({KINDS[entry['kind']]})"

    # ------------------------------------------------------------------ menu
    def _rebuild(self):
        self.menu.clear()
        if not self.entries:
            self.menu.addAction("Aucun fichier récent").setEnabled(False)
            return
        for number, entry in enumerate(self.entries, start=1):
            action = QtGui.QAction(f"&{number % 10}  {self.label(entry)}", self.menu)
            action.setToolTip("\n".join(entry["paths"]))
            action.setStatusTip(entry["paths"][0])
            action.triggered.connect(lambda _=False, e=dict(entry): self.trigger(e))
            self.menu.addAction(action)
        self.menu.setToolTipsVisible(True)
        self.menu.addSeparator()
        self.menu.addAction("Effacer la liste").triggered.connect(self.clear)

    def trigger(self, entry: dict):
        """Entrée choisie : rouverte, ou retirée si un de ses fichiers a disparu."""
        if not all(os.path.exists(p) for p in entry["paths"]):
            self.remove(entry)
            self.missing.emit(entry)
            return
        self.open_requested.emit(entry)

    # ------------------------------------------------------------------ persistance
    def _load(self):
        if self.settings is None:
            return
        try:
            entries = json.loads(self.settings.value(KEY_FILES, "[]") or "[]")
        except (TypeError, ValueError):
            entries = []
        self.entries = [e for e in entries
                        if isinstance(e, dict) and e.get("kind") in KINDS
                        and isinstance(e.get("paths"), list) and e["paths"]][:MAX_RECENT]
        self._last_dir = str(self.settings.value(KEY_DIR, "") or "")
        if not self._last_dir and self.entries:      # comme le GLviewer : le plus récent
            self._last_dir = os.path.dirname(self.entries[0]["paths"][0])

    def _save(self):
        if self.settings is None:
            return
        self.settings.setValue(KEY_FILES, json.dumps(self.entries))
        self.settings.setValue(KEY_DIR, self._last_dir)
        self.settings.sync()
