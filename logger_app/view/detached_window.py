# view/detached_window.py
"""
Fenêtre d'un graphique déporté (écran déporté), sur le modèle de DetachedGraphWindow du
GLviewer : la fermer réintègre le graphique à sa place dans la fenêtre principale.

Différence avec le GLviewer : c'est le widget graphique entier (GraphicsLayoutWidget) qui
change de fenêtre, et non le PlotItem qui change de scène. La scène, les connexions
souris, les curseurs et les textes suivent donc le graphique sans traitement particulier.
"""
from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets


class DetachedGraphWindow(QtWidgets.QWidget):

    closed = QtCore.pyqtSignal(str)          # clé du graphique : à réintégrer

    def __init__(self, key: str, title: str, widget: QtWidgets.QWidget,
                 parent: QtWidgets.QWidget | None = None):
        # parent : fenêtre détruite avec la fenêtre principale ; Qt.Window : fenêtre à part
        super().__init__(parent, QtCore.Qt.WindowType.Window)
        self.key = key
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setWindowTitle(title)
        if parent is not None:
            self.setWindowIcon(parent.windowIcon())
        self._layout = QtWidgets.QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.addWidget(widget)
        self.widget = widget
        self.resize(1000, 550)
        self._silent = False

    def take_widget(self) -> QtWidgets.QWidget:
        """Rend le graphique (avant réintégration)."""
        self._layout.removeWidget(self.widget)
        widget, self.widget = self.widget, None
        return widget

    def close_silently(self):
        """Fermeture demandée par le programme : pas de signal closed."""
        self._silent = True
        self.close()

    def closeEvent(self, event: QtGui.QCloseEvent):
        if not self._silent:
            self.closed.emit(self.key)
        super().closeEvent(event)
