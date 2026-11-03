# view/main_window.py
"""
Fenêtre principale, sur le modèle du GLviewer :

    +-------------------------------------------------------------------+
    | barre d'outils : Démarrer | Trame unique | Arrêter | Pause | Enr. |
    +----------------------+--------------------------------------------+
    | arborescence voies   |                                            |
    |  (Voie|Valeur|Unité) |       graphique temps réel                 |
    +----------------------+   (voies analogiques / voies logiques)     |
    | paramètres logger    |                                            |
    |  (ParameterTree)     +--------------------------------------------+
    |  + réglages FFT      |       spectre (FFT), si activé             |
    |                      |  (chaque graphique peut être déporté dans  |
    |                      |   sa propre fenêtre : menu Fenêtres)       |
    +----------------------+--------------------------------------------+
    | barre d'état : état | trames | erreurs | images/s | messages       |
    +-------------------------------------------------------------------+

La vue ne contient aucune logique : les contrôleurs se connectent à ses widgets et actions.
"""
from __future__ import annotations

import pathlib

import pyqtgraph as pg
import pyqtgraph.parametertree as ptree
from PyQt6 import QtCore, QtGui, QtWidgets

PATH = pathlib.Path(__file__).parent


class MainWindow(QtWidgets.QMainWindow):

    closing = QtCore.pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Logger FPGA")
        self.setWindowIcon(QtGui.QIcon(str(PATH / "icon.ico")))
        self.resize(1400, 850)
        self._init_actions()
        self._init_menus()
        self._init_toolbar()
        self._init_central()
        self._init_status_bar()

    # ------------------------------------------------------------------ actions
    def _action(self, text, tip, shortcut=None, checkable=False, icon=None):
        action = QtGui.QAction(text, self)
        action.setToolTip(tip)
        action.setStatusTip(tip)
        action.setCheckable(checkable)
        if shortcut:
            action.setShortcut(QtGui.QKeySequence(shortcut))
        if icon is not None:
            action.setIcon(self.style().standardIcon(icon))
        return action

    def _init_actions(self):
        sp = QtWidgets.QStyle.StandardPixmap
        self.actionStart = self._action("Démarrer", "Configurer le logger et lancer "
                                        "l'acquisition (F5)", "F5", icon=sp.SP_MediaPlay)
        self.actionSingle = self._action("Trame unique", "Acquérir une seule trame (F6)",
                                         "F6", icon=sp.SP_MediaSeekForward)
        self.actionStop = self._action("Arrêter", "Arrêter l'acquisition (F7)", "F7",
                                       icon=sp.SP_MediaStop)
        self.actionPause = self._action("Figer", "Figer l'affichage, l'acquisition "
                                        "continue (F8)", "F8", checkable=True,
                                        icon=sp.SP_MediaPause)
        self.actionRecord = self._action("Enregistrer", "Enregistrer chaque trame sur disque",
                                         checkable=True, icon=sp.SP_DialogSaveButton)
        self.actionAutoRange = self._action("Échelle auto", "Adapter l'échelle à chaque trame",
                                            checkable=True, icon=sp.SP_BrowserReload)
        self.actionAutoRange.setChecked(True)
        self.actionFFT = self._action("FFT", "Afficher le spectre des voies analogiques (F9)",
                                      "F9", checkable=True, icon=sp.SP_FileDialogContentsView)
        self.actionResetFFT = self._action("Remise à zéro FFT",
                                           "Recommencer la moyenne / le maximum du spectre",
                                           icon=sp.SP_DialogResetButton)
        self.actionLoadConfig = self._action("Ouvrir une configuration...",
                                             "Charger une configuration (.json)",
                                             QtGui.QKeySequence.StandardKey.Open,
                                             icon=sp.SP_DialogOpenButton)
        self.actionSaveConfig = self._action("Enregistrer la configuration...",
                                             "Enregistrer la configuration (.json)",
                                             QtGui.QKeySequence.StandardKey.Save)
        self.actionQuit = self._action("Quitter", "Quitter", QtGui.QKeySequence.StandardKey.Quit)

    def _init_menus(self):
        menu = self.menuBar().addMenu("Fichier")
        menu.addActions([self.actionLoadConfig, self.actionSaveConfig])
        menu.addSeparator()
        menu.addAction(self.actionQuit)
        menu = self.menuBar().addMenu("Acquisition")
        menu.addActions([self.actionStart, self.actionSingle, self.actionStop])
        menu.addSeparator()
        menu.addActions([self.actionRecord])
        menu = self.menuBar().addMenu("Affichage")
        menu.addActions([self.actionPause, self.actionAutoRange])
        menu.addSeparator()
        menu.addActions([self.actionFFT, self.actionResetFFT])
        # rempli par DetachController : un graphique déportable par entrée
        self.menuWindows = self.menuBar().addMenu("Fenêtres")

    def _init_toolbar(self):
        self.toolbar = QtWidgets.QToolBar("Barre d'outils", self)
        self.toolbar.setObjectName("main_toolbar")
        self.toolbar.setMovable(False)
        self.toolbar.setIconSize(QtCore.QSize(20, 20))
        self.toolbar.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toolbar.toggleViewAction().setEnabled(False)
        self.addToolBar(QtCore.Qt.ToolBarArea.TopToolBarArea, self.toolbar)
        self.toolbar.addActions([self.actionStart, self.actionSingle, self.actionStop])
        self.toolbar.addSeparator()
        self.toolbar.addActions([self.actionPause, self.actionAutoRange])
        self.toolbar.addSeparator()
        self.toolbar.addActions([self.actionFFT, self.actionResetFFT])
        self.toolbar.addSeparator()
        self.toolbar.addAction(self.actionRecord)

    # ------------------------------------------------------------------ centre
    def _init_central(self):
        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        self.left_splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)

        self.tree_tabs = QtWidgets.QTabWidget()
        self.treechannels = QtWidgets.QTreeView()
        self.treechannels.setAllColumnsShowFocus(True)
        self.treechannels.setUniformRowHeights(True)
        self.tree_tabs.addTab(self.treechannels, "Voies")

        self.configtree = ptree.ParameterTree(showHeader=False)
        self.left_splitter.addWidget(self.tree_tabs)
        self.left_splitter.addWidget(self.configtree)
        self.left_splitter.setSizes([330, 470])
        self.left_splitter.setMinimumWidth(340)

        # graphiques, chacun déportable dans sa propre fenêtre (controller/detach_controller)
        self.analoggraph = pg.GraphicsLayoutWidget()    # voies analogiques
        self.logicgraph = pg.GraphicsLayoutWidget()     # voies logiques
        self.fftgraph = pg.GraphicsLayoutWidget()       # spectre, si l'action FFT est cochée
        self.fftgraph.hide()
        # affiché quand tous les graphiques sont déportés
        self.graph_placeholder = QtWidgets.QLabel(
            "Graphiques déportés dans leurs fenêtres\n(menu Fenêtres pour les réintégrer)")
        self.graph_placeholder.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.graph_splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        for widget in (self.analoggraph, self.logicgraph, self.fftgraph,
                       self.graph_placeholder):
            self.graph_splitter.addWidget(widget)
        self.graph_splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(self.left_splitter)
        self.splitter.addWidget(self.graph_splitter)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 4)
        self.splitter.setCollapsible(0, False)
        self.setCentralWidget(self.splitter)

    def _init_status_bar(self):
        bar = self.statusBar()
        self.stateLabel = QtWidgets.QLabel("Arrêté")
        self.framesLabel = QtWidgets.QLabel("Trames : 0")
        self.errorsLabel = QtWidgets.QLabel("Erreurs : 0")
        self.fpsLabel = QtWidgets.QLabel("")
        for label in (self.stateLabel, self.framesLabel, self.errorsLabel, self.fpsLabel):
            label.setContentsMargins(8, 0, 8, 0)
            bar.addPermanentWidget(label)
        self.stateLabel.setMinimumWidth(110)

    def show_message(self, text: str, timeout_ms: int = 5000):
        self.statusBar().showMessage(text, timeout_ms)

    def closeEvent(self, event):
        self.closing.emit()
        super().closeEvent(event)
