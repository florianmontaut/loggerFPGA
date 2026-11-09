# view/align_panel.py
"""Recalage de voies dans le temps : choix des voies et barre du recalage."""
from __future__ import annotations

import pyqtgraph as pg
from PyQt6 import QtCore, QtWidgets

from model import measures


def signed(seconds: float, digits: int = 5) -> str:
    """Écart lisible et signé : « +4.5 µs », « -120 ns », « 0 s »."""
    if not seconds:
        return "0 s"
    return ("+" if seconds > 0 else "-") + measures.si(abs(seconds), "s", digits)


class AlignChannelsDialog(QtWidgets.QDialog):
    """
    Voies à recaler ensemble (celles d'un même appareil), cochées. `action` après
    exec() : "shift" (recalage interactif) ou "reset" (décalage des voies remis à zéro).
    """

    def __init__(self, names: list[str], sources: dict, shifts: dict, checked: set,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("Recaler des voies dans le temps")
        self.action = None
        self._shifts = shifts
        layout = QtWidgets.QVBoxLayout(self)
        text = QtWidgets.QLabel(
            "Voies à décaler ensemble (celles d'un même appareil) ; les autres servent de "
            "référence. Les échantillons ne sont pas modifiés : seul le décalage est "
            "enregistré dans le workspace.")
        text.setWordWrap(True)
        layout.addWidget(text)
        self.list = QtWidgets.QListWidget()
        for name in names:
            parts = [name]
            if sources.get(name):
                parts.append(sources[name])
            if shifts.get(name):
                parts.append(f"décalage {signed(shifts[name])}")
            item = QtWidgets.QListWidgetItem(" — ".join(parts))
            item.setData(QtCore.Qt.ItemDataRole.UserRole, name)
            item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.CheckState.Checked if name in checked
                               else QtCore.Qt.CheckState.Unchecked)
            self.list.addItem(item)
        layout.addWidget(self.list)
        buttons = QtWidgets.QDialogButtonBox()
        role = QtWidgets.QDialogButtonBox.ButtonRole
        self.shift_button = buttons.addButton("Recaler...", role.AcceptRole)
        self.reset_button = buttons.addButton("Remettre à zéro", role.ActionRole)
        self.reset_button.setToolTip("Supprimer le décalage des voies cochées")
        buttons.addButton("Annuler", role.RejectRole)
        self.shift_button.clicked.connect(lambda: self._done("shift"))
        self.reset_button.clicked.connect(lambda: self._done("reset"))
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.list.itemChanged.connect(self._update_buttons)
        self._update_buttons()
        self.resize(460, 320)

    def names(self) -> list[str]:
        items = (self.list.item(i) for i in range(self.list.count()))
        return [item.data(QtCore.Qt.ItemDataRole.UserRole) for item in items
                if item.checkState() == QtCore.Qt.CheckState.Checked]

    def _update_buttons(self, *_):
        names = self.names()
        self.shift_button.setEnabled(bool(names))
        self.reset_button.setEnabled(any(self._shifts.get(n) for n in names))

    def _done(self, action: str):
        self.action = action
        self.accept()


class AlignPanel(QtWidgets.QFrame):
    """Barre du recalage (barre d'état de la fenêtre principale)."""

    STEPS = (-10, -1, 1, 10)            # pas, en échantillons de la voie recalée

    def __init__(self, title: str, sample: float, parent=None):
        super().__init__(parent)
        self.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(6, 0, 6, 0)
        layout.addWidget(QtWidgets.QLabel(f"Recalage de {title} — écart :"))
        self.offset = pg.SpinBox(suffix="s", siPrefix=True, decimals=6, step=sample,
                                 compactHeight=False)
        self.offset.setMinimumWidth(120)
        layout.addWidget(self.offset)
        self.readable = QtWidgets.QLabel()
        self.readable.setMinimumWidth(150)
        layout.addWidget(self.readable)
        self.step_buttons = {}
        for step in self.STEPS:
            button = QtWidgets.QToolButton(text=f"{step:+d} éch.")
            button.setToolTip(f"{step:+d} échantillon(s) : {signed(step * sample)}")
            layout.addWidget(button)
            self.step_buttons[step] = button
        self.align_button = QtWidgets.QPushButton("Aligner A sur B")
        self.align_button.setToolTip("Place l'événement A des voies recalées sur "
                                     "l'événement B de la référence (lignes A et B)")
        self.validate_button = QtWidgets.QPushButton("Valider")
        self.cancel_button = QtWidgets.QPushButton("Annuler")
        for button in (self.align_button, self.validate_button, self.cancel_button):
            layout.addWidget(button)
