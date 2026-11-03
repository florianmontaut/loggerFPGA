# controller/detach_controller.py
"""
Graphiques déportables dans leur propre fenêtre (deuxième écran), pour tout graphique
enregistré : mesures analogiques, voies logiques, spectre (FFT)...

    register(key, titre, widget, plots, poids)   graphique géré
    detach(key) / attach(key) / toggle(key)       déporter / réintégrer
    set_available(key, bool)                      graphique utile ou non (FFT désactivée,
                                                  pas de voie logique...) : masque le widget
                                                  ou sa fenêtre déportée

Commandes : menu contextuel de chaque graphique (« Déporter dans une fenêtre » /
« Réintégrer ») et menu Fenêtres de la fenêtre principale. Fermer une fenêtre déportée
réintègre son graphique (comme dans le GLviewer). Les raccourcis de la fenêtre principale
(F5 à F9...) restent actifs dans les fenêtres déportées.

Avec `settings` (QSettings), la position des fenêtres et l'état déporté sont conservés
d'une session à l'autre (restore()).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pyqtgraph as pg
from PyQt6 import QtCore, QtGui, QtWidgets

from view.detached_window import DetachedGraphWindow

DETACH_TEXT = "Déporter dans une fenêtre"
ATTACH_TEXT = "Réintégrer dans la fenêtre principale"


@dataclass
class _Graph:
    key: str
    title: str
    widget: QtWidgets.QWidget
    weight: int
    available: bool = True
    window: DetachedGraphWindow | None = None
    geometry: QtCore.QByteArray | None = None
    actions: list = field(default_factory=list)       # menus contextuels des graphiques
    menu_action: QtGui.QAction | None = None          # menu Fenêtres (case à cocher)


class DetachController(QtCore.QObject):

    detached_changed = QtCore.pyqtSignal(str, bool)

    def __init__(self, main_window: QtWidgets.QMainWindow, splitter: QtWidgets.QSplitter,
                 placeholder: QtWidgets.QWidget, menu: QtWidgets.QMenu | None = None,
                 settings: QtCore.QSettings | None = None):
        super().__init__()
        self.main_window = main_window
        self.splitter = splitter
        self.placeholder = placeholder
        self.menu = menu
        self.settings = settings
        self.graphs: dict[str, _Graph] = {}       # dans l'ordre d'affichage
        if menu is not None:
            self.attach_all_action = QtGui.QAction("Tout réintégrer", main_window)
            self.attach_all_action.triggered.connect(self.attach_all)
        self._update_placeholder()

    # ------------------------------------------------------------------ enregistrement
    def register(self, key: str, title: str, widget: QtWidgets.QWidget,
                 plots: list[pg.PlotItem] = (), weight: int = 1):
        graph = _Graph(key, title, widget, weight)
        self.graphs[key] = graph
        for plot in plots:
            self.add_plot(key, plot)
        if self.menu is not None:
            action = QtGui.QAction(f"Déporter « {title} »", self.main_window)
            action.setCheckable(True)
            action.toggled.connect(lambda on, k=key: self.detach(k) if on else self.attach(k))
            graph.menu_action = action
            self.menu.removeAction(self.attach_all_action)
            self.menu.addAction(action)
            self.menu.addSeparator()
            self.menu.addAction(self.attach_all_action)
        self._update_placeholder()

    def add_plot(self, key: str, plot: pg.PlotItem):
        """Entrée « Déporter / Réintégrer » dans le menu contextuel d'un tracé du graphique."""
        menu = plot.vb.menu
        menu.addSeparator()
        action = QtGui.QAction(DETACH_TEXT, menu)
        action.triggered.connect(lambda _=False, k=key: self.toggle(k))
        menu.addAction(action)
        self.graphs[key].actions.append(action)

    def is_detached(self, key: str) -> bool:
        return self.graphs[key].window is not None

    def window_of(self, key: str) -> DetachedGraphWindow | None:
        return self.graphs[key].window

    # ------------------------------------------------------------------ déporter / réintégrer
    def toggle(self, key: str):
        (self.attach if self.is_detached(key) else self.detach)(key)

    def detach(self, key: str):
        graph = self.graphs[key]
        if graph.window is not None:
            return
        window = DetachedGraphWindow(key, f"{graph.title} - Logger FPGA", graph.widget,
                                     self.main_window)
        # raccourcis de la fenêtre principale (Démarrer, Arrêter, Figer, FFT...)
        window.addActions([a for a in self.main_window.findChildren(QtGui.QAction)
                           if not a.shortcut().isEmpty()])
        window.closed.connect(self.attach)
        graph.window = window
        if graph.geometry is not None:
            window.restoreGeometry(graph.geometry)
        graph.widget.setVisible(True)
        window.setVisible(graph.available)
        self._set_texts(graph, True)
        self._update_placeholder()
        self._redistribute()
        self.detached_changed.emit(key, True)

    def attach(self, key: str):
        graph = self.graphs[key]
        window = graph.window
        if window is None:
            return
        graph.geometry = window.saveGeometry()
        graph.window = None
        window.closed.disconnect(self.attach)
        widget = window.take_widget()
        self.splitter.insertWidget(self._splitter_index(key), widget)
        widget.setVisible(graph.available)
        window.close_silently()
        window.deleteLater()
        self._set_texts(graph, False)
        self._update_placeholder()
        self._redistribute()
        self.detached_changed.emit(key, False)

    def attach_all(self):
        for key in self.graphs:
            self.attach(key)

    def _splitter_index(self, key: str) -> int:
        """Place d'origine : après les graphiques intégrés qui le précèdent."""
        index = 0
        for other in self.graphs.values():
            if other.key == key:
                break
            if other.window is None:
                index = max(index, self.splitter.indexOf(other.widget) + 1)
        return index

    def _set_texts(self, graph: _Graph, detached: bool):
        for action in graph.actions:
            action.setText(ATTACH_TEXT if detached else DETACH_TEXT)
        if graph.menu_action is not None:
            graph.menu_action.blockSignals(True)
            graph.menu_action.setChecked(detached)
            graph.menu_action.blockSignals(False)

    # ------------------------------------------------------------------ disponibilité
    def set_available(self, key: str, available: bool):
        """Graphique utile ou non : son widget, ou sa fenêtre déportée, est masqué."""
        graph = self.graphs[key]
        if graph.available == available:
            return
        graph.available = available
        if graph.window is not None:
            graph.window.setVisible(available)
            if available:
                graph.window.raise_()
        else:
            graph.widget.setVisible(available)
            self._redistribute()
        if graph.menu_action is not None:
            graph.menu_action.setEnabled(available or graph.window is not None)
        self._update_placeholder()

    def _attached_visible(self) -> list[_Graph]:
        return [g for g in self.graphs.values() if g.window is None and g.available]

    def _update_placeholder(self):
        self.placeholder.setVisible(not self._attached_visible())

    def _redistribute(self):
        """Hauteurs des graphiques intégrés et visibles, au prorata de leur poids."""
        shown = self._attached_visible()
        if not shown:
            return
        total = max(sum(self.splitter.sizes()), 1)
        weights = sum(g.weight for g in shown)
        sizes = [0] * self.splitter.count()
        for g in shown:
            sizes[self.splitter.indexOf(g.widget)] = int(total * g.weight / weights)
        self.splitter.setSizes(sizes)

    # ------------------------------------------------------------------ persistance
    def restore(self):
        """Position des fenêtres et état déporté de la session précédente."""
        if self.settings is None:
            return
        for key, graph in self.graphs.items():
            geometry = self.settings.value(f"detached/{key}/geometry")
            if isinstance(geometry, QtCore.QByteArray) and not geometry.isEmpty():
                graph.geometry = geometry
            if str(self.settings.value(f"detached/{key}/on", "false")).lower() == "true":
                self.detach(key)

    def save(self):
        if self.settings is None:
            return
        for key, graph in self.graphs.items():
            if graph.window is not None:
                graph.geometry = graph.window.saveGeometry()
            if graph.geometry is not None:
                self.settings.setValue(f"detached/{key}/geometry", graph.geometry)
            self.settings.setValue(f"detached/{key}/on", graph.window is not None)
        self.settings.sync()

    def shutdown(self):
        """Fermeture de l'application : état mémorisé puis graphiques réintégrés."""
        self.save()
        self.attach_all()
