# ressources/pens.py
"""Couleurs des voies (palette tab20 du GLviewer, sans dépendre de matplotlib)."""
import pyqtgraph as pg
from PyQt6 import QtCore, QtGui

TAB20 = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2",
         "#7f7f7f", "#bcbd22", "#17becf", "#aec7e8", "#ffbb78", "#98df8a", "#ff9896",
         "#c5b0d5", "#c49c94", "#f7b6d2", "#c7c7c7", "#dbdb8d", "#9edae5"]


def analog_color(sig: int) -> str:
    """Couleur fixe par voie : une voie garde sa couleur quel que soit son rang."""
    return TAB20[sig % len(TAB20)]


def logic_color(bit: int) -> str:
    return TAB20[(2 * bit + 1) % len(TAB20)]


def pen(color: str, width: float = 1.0) -> QtGui.QPen:
    return pg.mkPen(color, width=width)


def swatch(color: str, size: int = 12) -> QtGui.QIcon:
    pix = QtGui.QPixmap(size, size)
    pix.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pix)
    painter.setBrush(QtGui.QColor(color))
    painter.setPen(QtCore.Qt.PenStyle.NoPen)
    painter.drawRoundedRect(1, 1, size - 2, size - 2, 2, 2)
    painter.end()
    return QtGui.QIcon(pix)
