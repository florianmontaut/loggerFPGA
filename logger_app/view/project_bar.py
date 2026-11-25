# view/project_bar.py
"""
Barre du projet, au-dessus de la vue d'ensemble d'un enregistrement d'oscilloscope :

    Projet : essais.lfproj *   [essai_A.h5 ▾] [−]  |  Balises : [1 ▭] [2 ▭] [3 ▭]  [+]

Liste des enregistrements du projet (on passe de l'un à l'autre en gardant la même
disposition), et une vignette numérotée par balise : clic = afficher la balise, clic
droit = renommer, mettre à jour, supprimer.
"""
from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets

THUMBNAIL_SIZE = QtCore.QSize(80, 40)


class ProjectBar(QtWidgets.QToolBar):

    record_chosen = QtCore.pyqtSignal(str)          # chemin d'un enregistrement du projet
    remove_record = QtCore.pyqtSignal()
    add_bookmark = QtCore.pyqtSignal()
    bookmark_clicked = QtCore.pyqtSignal(int)
    bookmark_menu = QtCore.pyqtSignal(int, str)     # indice, "rename" | "update" | "delete"

    def __init__(self, parent=None):
        super().__init__("Projet", parent)
        self.setIconSize(THUMBNAIL_SIZE)
        self.setMovable(False)
        self.setFloatable(False)
        self.title = QtWidgets.QLabel()
        self.title.setContentsMargins(4, 0, 8, 0)
        self.addWidget(self.title)
        self.records = QtWidgets.QComboBox()
        self.records.setMinimumContentsLength(18)
        self.records.setSizeAdjustPolicy(
            QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.records.setToolTip("Enregistrements du projet : en choisir un l'affiche avec la "
                                "même disposition et la même portion de temps")
        self.records.activated.connect(self._on_record_activated)
        self.addWidget(self.records)
        self.remove_action = self.addAction("Retirer")
        self.remove_action.setToolTip("Retirer l'enregistrement affiché de la liste du projet "
                                      "(le fichier n'est pas touché)")
        self.remove_action.triggered.connect(self.remove_record)
        self.addSeparator()
        label = QtWidgets.QLabel("Balises :")
        label.setContentsMargins(4, 0, 4, 0)
        self.addWidget(label)
        self._bookmark_actions: list[QtGui.QAction] = []
        self.add_action = self.addAction("+ Balise")
        self.add_action.setToolTip("Nouvelle balise : portion affichée et échelles des voies "
                                   "(Ctrl+B)")
        self.add_action.triggered.connect(self.add_bookmark)

    # ------------------------------------------------------------------ projet
    def set_title(self, text: str):
        self.title.setText(text)

    def set_records(self, records: list[tuple[str, str, str]], current: str | None):
        """records : [(chemin, texte, info-bulle)] ; current : chemin affiché."""
        self.records.blockSignals(True)
        self.records.clear()
        for path, text, tip in records:
            self.records.addItem(text, path)
            self.records.setItemData(self.records.count() - 1, tip,
                                     QtCore.Qt.ItemDataRole.ToolTipRole)
        index = self.records.findData(current) if current else -1
        self.records.setCurrentIndex(index)
        self.records.blockSignals(False)

    def _on_record_activated(self, index: int):
        path = self.records.itemData(index)
        if path:
            self.record_chosen.emit(path)

    # ------------------------------------------------------------------ balises
    def set_bookmarks(self, items: list[tuple[str, QtGui.QIcon, str]]):
        """items : [(texte, vignette, info-bulle)], dans l'ordre des balises."""
        for action in self._bookmark_actions:
            self.removeAction(action)
            action.deleteLater()
        self._bookmark_actions = []
        for k, (text, icon, tip) in enumerate(items):
            action = QtGui.QAction(icon, text, self)
            action.setToolTip(tip)
            action.triggered.connect(lambda _=False, i=k: self.bookmark_clicked.emit(i))
            self.insertAction(self.add_action, action)
            button = self.widgetForAction(action)
            if button is not None:
                button.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
                button.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
                button.customContextMenuRequested.connect(
                    lambda pos, i=k, b=button: self._context_menu(i, b.mapToGlobal(pos)))
            self._bookmark_actions.append(action)

    def bookmark_button(self, index: int) -> QtWidgets.QToolButton | None:
        if 0 <= index < len(self._bookmark_actions):
            return self.widgetForAction(self._bookmark_actions[index])
        return None

    def _context_menu(self, index: int, pos: QtCore.QPoint):
        menu = QtWidgets.QMenu(self)
        for key, text in (("rename", "Renommer..."),
                          ("update", "Remplacer par la vue actuelle"),
                          ("delete", "Supprimer")):
            menu.addAction(text).setData(key)
        chosen = menu.exec(pos)
        if chosen is not None:
            self.bookmark_menu.emit(index, chosen.data())
