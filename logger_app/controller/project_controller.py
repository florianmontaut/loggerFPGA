# controller/project_controller.py
"""
Projet d'enregistrements d'oscilloscope (model/project.py) : disposition des voies et
balises, pour passer d'un enregistrement à l'autre en gardant la même vue.

    - Un projet est toujours ouvert, « sans titre » tant qu'il n'est pas enregistré. Tout
      enregistrement d'oscilloscope ouvert s'ajoute à sa liste (barre du projet).
    - Disposition : plage verticale de l'axe de chaque voie (gain / offset), voies
      masquées, voie mise en évidence, répartition des axes, portion affichée, voies
      calculées. Rangée par nom de voie.
    - Choisir un autre enregistrement dans la barre l'ouvre avec la disposition et la
      portion de temps de celui qui était affiché. Rouvrir l'enregistrement qu'on vient de
      fermer (ajout de voies, recalage) lui rend sa disposition. Un enregistrement ouvert
      autrement prend la disposition du projet si celui-ci est enregistré ; dans un projet
      sans titre, il garde l'échelle automatique.
    - Balise : portion de temps et échelles des voies, avec une vignette du graphique.
      Clic (ou Ctrl+1 à Ctrl+9) : la balise est affichée.
"""
from __future__ import annotations

import base64
import os

import numpy as np
from PyQt6 import QtCore, QtGui, QtWidgets

from model import measures
from model.math_channels import MathDefinition
from model.project import EXTENSION, Bookmark, Project, ProjectError
from view.project_bar import THUMBNAIL_SIZE

THUMBNAIL_IMAGE = (320, 160)    # vignette d'une balise (px), montrée dans son info-bulle


def _rounded(value, digits: int = 6):
    """Copie aux flottants arrondis : comparaison d'états sans bruit numérique."""
    if isinstance(value, float):
        return float(f"{value:.{digits}g}")
    if isinstance(value, dict):
        return {k: _rounded(v, digits) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_rounded(v, digits) for v in value]
    return value


class ProjectController(QtCore.QObject):

    message = QtCore.pyqtSignal(str)
    saved = QtCore.pyqtSignal(str)              # projet enregistré ou ouvert (récents)
    axis_mode_requested = QtCore.pyqtSignal(str)

    def __init__(self, view, graph_ctrl, scope_ctrl, tree_ctrl, math_ctrl, last_dir,
                 scale_ctrl=None):
        super().__init__()
        self.view = view
        self.graph = graph_ctrl
        self.scope = scope_ctrl
        self.tree = tree_ctrl
        self.math = math_ctrl
        self.scale = scale_ctrl                 # graduations et grille des axes
        self.last_dir = last_dir                # callable() -> dossier des boîtes de fichiers
        self.project = Project()
        self.path: str | None = None            # fichier du projet, None : sans titre
        self._saved = None                      # état enregistré (comparaison)
        self._dirty = False                     # balises ou enregistrements modifiés
        self._pending = None                    # disposition de la prochaine ouverture
        self._last_closed = None                # (chemin, disposition) du dernier fermé
        # boîtes de dialogue, remplaçables (tests)
        self.ask_save_path = self._ask_save_path
        self.ask_name = self._ask_name
        self.ask_discard = self._ask_discard
        self.bar = view.projectBar

        scope_ctrl.opened.connect(self._on_opened)
        scope_ctrl.closing.connect(self._on_closing)
        self.bar.record_chosen.connect(self.switch_to)
        self.bar.remove_record.connect(self.remove_current_record)
        self.bar.add_bookmark.connect(self.add_bookmark)
        self.bar.bookmark_clicked.connect(self.apply_bookmark)
        self.bar.bookmark_menu.connect(self._on_bookmark_menu)
        view.actionAddBookmark.triggered.connect(lambda: self.add_bookmark())
        self._shortcuts = []
        for k in range(1, 10):
            shortcut = QtGui.QShortcut(QtGui.QKeySequence(f"Ctrl+{k}"), view)
            shortcut.activated.connect(lambda i=k - 1: self.apply_bookmark(i))
            self._shortcuts.append(shortcut)
        self._refresh()

    # ------------------------------------------------------------------ disposition
    def capture(self) -> dict:
        """Disposition affichée : voies par nom, voie en évidence, axes, portion."""
        cfg = self.graph.cfg
        if not self.scope.active or cfg is None:
            return {}
        ranges = self.graph.y_ranges()
        channels = {cfg.analog_name(sig): {"y": [float(v) for v in ranges[sig]],
                                           "visible": ("A", sig) not in self.tree.hidden}
                    for sig in cfg.analog_signals if sig in ranges}
        key = self.graph.highlighted
        highlighted = None
        if key is not None and key[0] == "A" and key[1] in cfg.analog_signals:
            highlighted = cfg.analog_name(key[1])
        elif key is not None and key[0] == "M":
            highlighted = key[1]
        return {"channels": channels, "highlighted": highlighted,
                "view": [float(v) for v in self.graph.analog_plot.vb.viewRange()[0]],
                "axis_mode": self.graph.axis_mode}

    def apply_layout(self, layout: dict, view: bool = True, report: bool = False):
        """Disposition appliquée à l'enregistrement affiché (voies absentes ignorées)."""
        cfg = self.graph.cfg
        if not layout or not self.scope.active or cfg is None:
            return
        mode = layout.get("axis_mode")
        if mode and mode != self.graph.axis_mode:
            self.axis_mode_requested.emit(mode)         # axes recréés avant les plages
        by_name = {cfg.analog_name(sig): sig for sig in cfg.analog_signals}
        channels = layout.get("channels") or {}
        for name, entry in channels.items():
            sig = by_name.get(name)
            item = self.tree.items.get(("A", sig)) if sig is not None else None
            if item is not None and "visible" in entry:     # balise : échelles seules
                state = QtCore.Qt.CheckState.Checked if entry.get("visible", True) \
                    else QtCore.Qt.CheckState.Unchecked
                if item[0].checkState() != state:
                    item[0].setCheckState(state)
        self.graph.set_y_ranges({by_name[name]: tuple(entry["y"])
                                 for name, entry in channels.items()
                                 if name in by_name and entry.get("y")})
        name = layout.get("highlighted")
        if name:
            key = ("A", by_name[name]) if name in by_name else ("M", name)
            row = self.tree.items.get(key)
            if row is not None:
                self.tree.view.setCurrentIndex(row[0].index())
        if view and layout.get("view"):
            self.graph.analog_plot.setXRange(*layout["view"], padding=0)
        if report and channels:
            missing = sorted(set(by_name) - set(channels))
            if missing:
                self.message.emit("Voies sans disposition enregistrée (échelle automatique) : "
                                  + ", ".join(missing))

    def _sync(self):
        """Projet mis à jour avec l'affichage (avant enregistrement ou comparaison)."""
        layout = self.capture()
        if layout:
            self.project.merge_channels(layout["channels"])
            self.project.highlighted = layout["highlighted"]
            self.project.view = layout["view"]
            self.project.axis_mode = layout["axis_mode"]
            self.project.current = self.scope.record.path
        else:
            self.project.axis_mode = self.graph.axis_mode
        self.project.math_channels = [d.to_dict() for d in self.math.definitions()]
        if self.scale is not None:
            self.project.axes = self.scale.display_settings()

    def _project_layout(self) -> dict:
        """Disposition du projet (toutes les voies connues), à appliquer à l'ouverture."""
        return {"channels": self.project.channels, "highlighted": self.project.highlighted,
                "view": self.project.view, "axis_mode": self.project.axis_mode}

    # ------------------------------------------------------------------ enregistrements
    def _on_opened(self, _cfg):
        record = self.scope.record
        if self.project.add_record(record.path):
            self._dirty = True
        pending, self._pending = self._pending, None
        if pending is not None:
            self.apply_layout(pending, report=True)
        elif self._last_closed is not None and os.path.normcase(self._last_closed[0]) \
                == os.path.normcase(record.path):
            # même enregistrement rouvert (voies ajoutées, recalage) : sa disposition ;
            # la portion affichée est rétablie par le contrôleur de l'enregistrement
            self.apply_layout(self._last_closed[1], view=False)
        elif self.path is not None and self.project.channels:
            # projet enregistré : sa disposition vaut pour tous ses enregistrements (un
            # projet sans titre n'impose rien à un enregistrement ouvert par Fichier)
            self.apply_layout(self._project_layout(), view=False)
        self.view.actionAddBookmark.setEnabled(True)
        self.bar.show()
        self._refresh()

    def _on_closing(self):
        layout = self.capture()
        if layout:
            self.project.merge_channels(layout["channels"])
            self._last_closed = (self.scope.record.path, layout)
        self.view.actionAddBookmark.setEnabled(False)
        self.bar.hide()

    def switch_to(self, path: str) -> bool:
        """Autre enregistrement du projet, avec la disposition et la portion affichées."""
        record = self.scope.record
        if record is not None and os.path.normcase(record.path) == os.path.normcase(path):
            return True
        if not os.path.exists(path):
            self.message.emit(f"Enregistrement introuvable : {path}")
            self._refresh()
            return False
        layout = self.capture()
        if layout:
            self.project.merge_channels(layout["channels"])
            layout["channels"] = dict(self.project.channels)
        else:
            layout = self._project_layout()
        self._pending = layout
        try:
            done = self.scope.open([path])
        finally:
            self._pending = None
        self._refresh()
        return done

    def remove_current_record(self):
        """Enregistrement affiché retiré de la liste (il reste affiché, fichier intact)."""
        if self.scope.record is None:
            return
        self.project.remove_record(self.scope.record.path)
        self._dirty = True
        self._refresh()
        self.message.emit(f"{os.path.basename(self.scope.record.path)} retiré du projet")

    # ------------------------------------------------------------------ balises
    def _thumbnail(self) -> str:
        """
        Vignette des courbes analogiques affichées (PNG en base64). Dessinée à partir des
        courbes, en traits épais, et non par capture de l'écran : réduite, une capture
        ne garde rien des traits d'un pixel (et un graphique déporté n'y est pas).
        """
        width, height = THUMBNAIL_IMAGE
        pixmap = QtGui.QPixmap(width, height)
        pixmap.fill(QtGui.QColor("#000000"))
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        x0, x1 = self.graph.analog_plot.vb.viewRange()[0]
        keys = [k for k in self.graph.curves if k[0] == "A"]
        # voie en évidence dessinée en dernier, au premier plan
        keys.sort(key=lambda k: k == self.graph.highlighted)
        for key in keys:
            curve = self.graph.curves[key]
            x, y = curve.getData()
            if not curve.isVisible() or x is None or len(x) < 2 or x1 <= x0:
                continue
            lo, hi = self.graph.analog_view(key[1]).viewRange()[1]
            if hi <= lo:
                continue
            px = (np.asarray(x, float) - x0) / (x1 - x0) * width
            py = height - (np.asarray(y, float) - lo) / (hi - lo) * height
            inside = np.isfinite(py) & (px >= -1) & (px <= width + 1)
            px, py = px[inside], np.clip(py[inside], -2, height + 2)
            if px.size < 2:
                continue
            if px.size > 4 * width:         # enveloppe min/max par colonne de pixels
                column = np.clip(px.astype(int), 0, width)
                starts = np.flatnonzero(np.r_[True, np.diff(column) != 0])
                low = np.minimum.reduceat(py, starts)
                high = np.maximum.reduceat(py, starts)
                px = np.repeat(column[starts].astype(float), 2)
                py = np.column_stack([low, high]).ravel()
            color = curve.opts["pen"].color() if curve.opts.get("pen") is not None \
                else QtGui.QColor("#ffffff")
            painter.setPen(QtGui.QPen(color, 3.0 if key == self.graph.highlighted else 2.0))
            painter.drawPolyline(QtGui.QPolygonF(
                [QtCore.QPointF(a, b) for a, b in zip(px.tolist(), py.tolist())]))
        painter.end()
        buffer = QtCore.QBuffer()
        buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
        pixmap.save(buffer, "PNG")
        return base64.b64encode(bytes(buffer.data())).decode("ascii")

    def _bookmark_of_view(self, name: str) -> Bookmark | None:
        layout = self.capture()
        if not layout:
            return None
        return Bookmark(name=name, x=layout["view"],
                        y={n: e["y"] for n, e in layout["channels"].items()},
                        thumbnail=self._thumbnail())

    def add_bookmark(self) -> Bookmark | None:
        names = {b.name for b in self.project.bookmarks}
        number = len(self.project.bookmarks) + 1
        while f"Balise {number}" in names:
            number += 1
        bookmark = self._bookmark_of_view(f"Balise {number}")
        if bookmark is None:
            return None
        self.project.bookmarks.append(bookmark)
        self._dirty = True
        self._refresh()
        self.message.emit(f"{bookmark.name} créée : {self._describe(bookmark)}")
        return bookmark

    def apply_bookmark(self, index: int) -> bool:
        record = self.scope.record
        if record is None or not 0 <= index < len(self.project.bookmarks):
            return False
        bookmark = self.project.bookmarks[index]
        t0, t1 = record.t0, record.t0 + record.duration
        if bookmark.x[1] <= t0 or bookmark.x[0] >= t1:
            self.message.emit(f"{bookmark.name} : hors de cet enregistrement "
                              f"({measures.si(t0, 's', 4)} à {measures.si(t1, 's', 4)})")
            return False
        self.apply_layout({"channels": {n: {"y": span} for n, span in bookmark.y.items()},
                           "view": bookmark.x})
        self.message.emit(f"{bookmark.name} : {self._describe(bookmark)}")
        return True

    def _on_bookmark_menu(self, index: int, action: str):
        if not 0 <= index < len(self.project.bookmarks):
            return
        bookmark = self.project.bookmarks[index]
        if action == "rename":
            name = self.ask_name(bookmark.name)
            if not name or name == bookmark.name:
                return
            bookmark.name = name
        elif action == "update":
            new = self._bookmark_of_view(bookmark.name)
            if new is None:
                return
            self.project.bookmarks[index] = new
        elif action == "delete":
            del self.project.bookmarks[index]
        self._dirty = True
        self._refresh()

    def _describe(self, bookmark: Bookmark) -> str:
        record = self.scope.record
        text = f"{measures.si(bookmark.x[0], 's', 5)} à {measures.si(bookmark.x[1], 's', 5)}"
        if record is not None and record.duration > 0:
            zoom = bookmark.zoom(record.duration)
            position = bookmark.position(record.t0, record.duration)
            text = f"×{zoom:.3g} à {position:.1%} de l'enregistrement ({text})"
        return text

    # ------------------------------------------------------------------ barre
    def _refresh(self):
        name = os.path.basename(self.path) if self.path else "sans titre"
        self.bar.set_title(f"Projet : {name}{' *' if self._dirty else ''}")
        records = []
        for path in self.project.records:
            text = os.path.basename(path)
            if not os.path.exists(path):
                text += " (introuvable)"
            records.append((path, text, path))
        current = self.scope.record.path if self.scope.record is not None else None
        self.bar.set_records(records, current)
        self.bar.remove_action.setEnabled(current is not None and bool(records))
        items = []
        for k, bookmark in enumerate(self.project.bookmarks, start=1):
            pixmap = QtGui.QPixmap()
            if bookmark.thumbnail:
                pixmap.loadFromData(base64.b64decode(bookmark.thumbnail), "PNG")
            icon = QtGui.QIcon(pixmap.scaled(
                THUMBNAIL_SIZE, QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation)) if not pixmap.isNull() \
                else QtGui.QIcon()
            text = str(k) if bookmark.name == f"Balise {k}" else f"{k} · {bookmark.name[:18]}"
            tip = f"<b>{bookmark.name}</b>"
            if k <= 9:
                tip += f" (Ctrl+{k})"
            tip += f"<br>{self._describe(bookmark)}"
            if bookmark.thumbnail:
                tip += f'<br><img src="data:image/png;base64,{bookmark.thumbnail}">'
            items.append((text, icon, tip))
        self.bar.set_bookmarks(items)

    # ------------------------------------------------------------------ fichier
    def _state(self) -> dict:
        """État comparable du projet (sans portion affichée ni enregistrement courant)."""
        state = self.project.to_dict(os.path.dirname(self.path or os.getcwd()))
        state.pop("view", None)
        state.pop("current", None)
        return _rounded(state)

    def is_modified(self) -> bool:
        if self.path is None:
            return bool(self.project.bookmarks)     # rien d'autre ne vaut la question
        self._sync()
        return self._dirty or self._state() != self._saved

    def open(self, path: str) -> bool:
        if not self.confirm_discard("ouvrir un autre projet"):
            return False
        try:
            project = Project.load(path)
        except ProjectError as exc:
            QtWidgets.QMessageBox.warning(self.view, "Projet", str(exc))
            return False
        self.project, self.path = project, os.path.abspath(path)
        self._saved = self._state()                 # tel que lu
        self._dirty = False
        self._last_closed = None
        if project.math_channels:
            self.math.set_definitions([MathDefinition.from_dict(d)
                                       for d in project.math_channels])
        if self.scale is not None and project.axes:
            self.scale.set_display_settings(project.axes)
        missing = [p for p in project.records if not os.path.exists(p)]
        target = project.current if project.current and os.path.exists(project.current) \
            else next((p for p in project.records if os.path.exists(p)), None)
        if target is not None:
            self._pending = self._project_layout()
            try:
                self.scope.open([target])
            finally:
                self._pending = None
        elif self.scope.active:
            self.apply_layout(self._project_layout(), report=True)
        self._refresh()
        text = f"Projet ouvert : {os.path.basename(path)}"
        if missing:
            text += " — introuvable(s) : " + ", ".join(os.path.basename(p) for p in missing)
        self.message.emit(text)
        self.saved.emit(self.path)
        return True

    def save(self) -> bool:
        if self.path is None:
            return self.save_as()
        return self._write(self.path)

    def save_as(self) -> bool:
        if self.path:
            default = self.path
        else:
            stem = "projet"
            if self.scope.record is not None:
                stem = os.path.splitext(os.path.basename(self.scope.record.path))[0]
                stem = stem.removesuffix(".workspace")
            default = os.path.join(self.last_dir() or "", stem + EXTENSION)
        path = self.ask_save_path(default)
        if not path:
            return False
        if not path.lower().endswith(EXTENSION):
            path += EXTENSION
        return self._write(path)

    def _write(self, path: str) -> bool:
        self._sync()
        try:
            self.project.save(path)
        except ProjectError as exc:
            QtWidgets.QMessageBox.warning(self.view, "Projet", str(exc))
            return False
        self.path = os.path.abspath(path)
        self._saved = self._state()
        self._dirty = False
        self._refresh()
        self.message.emit(f"Projet enregistré : {path}")
        self.saved.emit(self.path)
        return True

    def new(self) -> bool:
        """Projet vide ; l'enregistrement affiché y entre."""
        if not self.confirm_discard("commencer un nouveau projet"):
            return False
        self.project = Project()
        if self.scope.record is not None:
            self.project.add_record(self.scope.record.path)
        self.path, self._saved, self._dirty, self._last_closed = None, None, False, None
        self._refresh()
        self.message.emit("Nouveau projet")
        return True

    def confirm_discard(self, action: str) -> bool:
        """Projet modifié : l'enregistrer, l'abandonner ou annuler `action`."""
        if not self.is_modified():
            return True
        answer = self.ask_discard(action)
        if answer == "save":
            return self.save()
        return answer == "discard"

    # ------------------------------------------------------------------ boîtes
    def _ask_save_path(self, default: str) -> str:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self.view, "Enregistrer le projet", default, f"Projet (*{EXTENSION})")
        return path

    def _ask_name(self, current: str) -> str:
        name, ok = QtWidgets.QInputDialog.getText(self.view, "Renommer la balise", "Nom :",
                                                  text=current)
        return name.strip() if ok else ""

    def _ask_discard(self, action: str) -> str:
        name = os.path.basename(self.path) if self.path else "sans titre"
        box = QtWidgets.QMessageBox(self.view)
        box.setIcon(QtWidgets.QMessageBox.Icon.Question)
        box.setWindowTitle("Projet modifié")
        box.setText(f"Le projet « {name} » a été modifié (disposition, balises ou "
                    f"enregistrements).\nL'enregistrer avant de {action} ?")
        buttons = QtWidgets.QMessageBox.StandardButton
        box.setStandardButtons(buttons.Save | buttons.Discard | buttons.Cancel)
        box.setDefaultButton(buttons.Save)
        answer = box.exec()
        return {buttons.Save: "save", buttons.Discard: "discard"}.get(
            buttons(answer), "cancel")
