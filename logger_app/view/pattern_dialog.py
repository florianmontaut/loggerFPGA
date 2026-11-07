# view/pattern_dialog.py
"""
Fenêtre « Exporter un motif » (non modale : la zone se règle sur le graphique pendant
qu'elle est ouverte). Logique : controller/pattern_controller.py.
"""
from __future__ import annotations

import pyqtgraph as pg
from PyQt6 import QtCore, QtWidgets

from model.pattern import FORMATS, MAX_POINTS


class PatternDialog(QtWidgets.QDialog):

    closed = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent, QtCore.Qt.WindowType.Tool)
        self.setWindowTitle("Exporter un motif")
        self.setModal(False)
        self.channel = QtWidgets.QComboBox()
        self.start = pg.SpinBox(suffix="s", siPrefix=True, decimals=6, compactHeight=False)
        self.stop = pg.SpinBox(suffix="s", siPrefix=True, decimals=6, compactHeight=False)
        self.max_points = QtWidgets.QSpinBox()
        self.max_points.setRange(2, MAX_POINTS)
        self.max_points.setValue(MAX_POINTS)
        self.max_points.setToolTip(f"Lignes exportées au plus ({MAX_POINTS} maximum) : "
                                   f"au-delà, 1 point sur N")
        self.info = QtWidgets.QLabel()
        self.info.setWordWrap(True)
        self.relative = QtWidgets.QCheckBox("Temps relatif au début du motif")
        self.relative.setChecked(True)
        self.format = QtWidgets.QComboBox()
        self.format.addItems(FORMATS)
        self.decimal_comma = QtWidgets.QCheckBox("Virgule décimale (tableur)")
        self.preview = QtWidgets.QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        self.preview.setMinimumHeight(140)
        self.copy_button = QtWidgets.QPushButton("Copier")
        self.copy_button.setDefault(True)
        self.save_button = QtWidgets.QPushButton("Enregistrer...")
        close_button = QtWidgets.QPushButton("Fermer")
        close_button.clicked.connect(self.close)

        form = QtWidgets.QFormLayout()
        form.addRow("Voie", self.channel)
        form.addRow("Début", self.start)
        form.addRow("Fin", self.stop)
        form.addRow("Points max", self.max_points)
        form.addRow("", self.info)
        form.addRow("Format", self.format)
        form.addRow("", self.relative)
        form.addRow("", self.decimal_comma)
        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch()
        for button in (self.copy_button, self.save_button, close_button):
            buttons.addWidget(button)
        layout = QtWidgets.QVBoxLayout(self)
        hint = QtWidgets.QLabel("Déplacez la zone orange sur le graphique ou ses bornes ; "
                                "les points exportés sont marqués sur la courbe.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addLayout(form)
        layout.addWidget(QtWidgets.QLabel("Aperçu"))
        layout.addWidget(self.preview)
        layout.addLayout(buttons)
        self.resize(430, 520)

    def closeEvent(self, event):
        self.closed.emit()
        super().closeEvent(event)
