"""
Module contenant des QWidgets et QMainWindow générique pouvant être chargés pour différents projet
"""
import numpy as np
import os,json

from PyQt6.QtWidgets import (QApplication, QMainWindow,QAbstractItemView,QDialog,QColorDialog,QPushButton,
                            QGraphicsItem,QWidget,QFileDialog,QTreeWidget,
                            QMessageBox,QGridLayout,QMenu)

from PyQt6.uic import loadUi
from PyQt6 import QtGui,QtCore

from ressources import CustomFunctions
from views import CustomDialogs
from ressources import CustomParameters,CustomTypes

import pyqtgraph.parametertree as ptree
import pyqtgraph as pg
import pathlib

PATH=pathlib.Path(__file__).parent

class CustomMainWindow(QMainWindow):
    """
    Fenêtre principale du GLviewer

    Class:
        QMainWindow (QMainWindow): _description_
    """
    #Les signaux ne peuvent être déclarés qu'en attributs de classe
    loadFile_signal   = QtCore.pyqtSignal(tuple)
    modifCurve_signal = QtCore.pyqtSignal()
    UIsignals         = QtCore.pyqtSignal(tuple)
    saveFile_signal   = QtCore.pyqtSignal(str)

    def __init__(self,params,**opts):

        super(CustomMainWindow, self).__init__()
        #Load the UI Page
        loadUi(PATH/'DMlogger.ui', self)
        self.setWindowIcon(QtGui.QIcon(str(PATH)+'/icon.ico'))
        self.treefile:QTreeWidget
        self.connectButton:QPushButton
        self.disconnectButton:QPushButton
        self.PauseButton:QPushButton
        self.plotgraph: pg.PlotItem

        self.windows_set = None
        self.sync_time=None
        self.curve_point=None
        self.old_highlight=(None,None)
        self.synchro_files=None

        self.optsDict = {   ("X axis","X axis title")               : "X_title",
                            ("X axis","X axis unit")                : "X_unit" ,
                            ("X axis","X major tick")               : "X_major_t",
                            ("X axis","X minor tick")               : "X_minor_t",
                            ("Y axis","Y axis title")               : "Y_title",
                            ("Y axis","Y axis unit")                : "Y_unit" ,
                            ("Y axis","Y major tick")               : "Y_major_t",
                            ("Y axis","Y minor tick")               : "Y_minor_t",
                            "Update axis when signal selected"      : "update_selected",
                            ("Downsample", "Active")                : "downsample",
                            ("Downsample", "Downsampling factor")   : "downsample_ratio",
                            ("Downsample", "Downsampling type")     : "downsample_type",
                            ("Appearance","Graph Background color") : "background_color",
                            ("Appearance","Dark mode")              : "dark_mode"
                            }

        #options par défaut de l'objet
        self.opts=  {
                    "X_title"              : "Temps",
                    "X_unit"               : "s",
                    "X_major_t"            : 1200,
                    "X_minor_t"            : 300,
                    "Y_title"              : "Temperature",
                    "Y_unit"               : "°C",
                    "Y_major_t"            : 10,
                    "Y_minor_t"            : 2,
                    "update_selected"      : True,
                    "downsample"           : True,
                    "downsample_ratio"     : 10,
                    "downsample_type"      : "peak",
                    "background_color"     :'#FFFFFF',
                    "dark_mode"            : False
                    }
        if opts:
            self.updateOptions(**opts)

        #*Réglage de l'affichage principal*#
        self.initGraph()
        self.initCursorsTab()
        self.initTrigTab()
        self.treefile.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.treefile.customContextMenuRequested.connect(self.treeMenu)
        self.actionQuit.triggered.connect(self.close)
        self.initRecentFiles()
        self.defaultdir=os.path.dirname(__file__)
        #*Réglage de l'arborescence*#
        #configuration de la sélection en mode extended (sélection multiple via shift +singular
        #avec ctrl) dans le treefile
        self.treefile.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        #cache la colonne id
        self.treefile.hideColumn(2)
        #options_params contient les paramètres à afficher lorsque l'utilisateur ouvre la fenêtre
        #des options

        self.option_params=params
        self.toggle_check=True
        self.graphWindows=[]
        self.selected_curve=[None,None]


        #dictionnaire reliant les clés des options de cet objet et le dictionnaire extrait de
        #la fenêtre options

        #################################################? RECENTE FILE SECTION?################################################
    def initRecentFiles(self):

        #on rajoute le menu recent files
        self.recent_files_menu = QMenu("Recent Files", self)
        self.menuFiles.insertMenu(self.actionSave_to,self.recent_files_menu)

        #Création d'un répertoire spécifique au programme dans la racine user de la session Window
        user_config_dir = os.path.expanduser("~") + "/loggerFPGA"
        user_config = user_config_dir + "/settings.json"
        if not os.path.exists(user_config):
            os.makedirs(user_config_dir, exist_ok=True)
            with open(user_config, "w") as f:
                json.dump({"files": []}, f)

        self.user_config=user_config
        self.updateRecentFilesMenu()

    def updateRecentFilesMenu(self):

        self.recent_files_menu.clear()
        if not os.path.exists(self.user_config):
            self.recent_files_menu.setEnabled(False)
            return
        self.recent_files_menu.setEnabled(True)
        with open(self.user_config, "r") as f:
            data = json.load(f)
        files = data.get("files", [])
        if not files:
            self.recent_files_menu.addAction("No recent files").setEnabled(False)
            return
        for fpath in files:
            action = QtGui.QAction(fpath, self)
            action.triggered.connect(lambda checked, path=fpath: self.loadFile_signal.emit((CustomTypes.fileType.JSON,[fpath])))
            self.recent_files_menu.addAction(action)

    def saveRecentFileAdress(self, file_path):
        if not os.path.exists(self.user_config):
            with open(self.user_config, "w") as f:
                json.dump({"files": []}, f)
        with open(self.user_config, "r") as f:
            data = json.load(f)
        files = data.get("files", [])

        #si l'adresse existe déjà dans la liste on la retire
        if file_path in files:
            files.remove(file_path)

        #on ne garde que les 10 fichiers les plus récents
        files.insert(0, file_path)
        files = files[:10]
        with open(self.user_config, "w") as f:
            json.dump({"files": files}, f, indent=4)
        self.updateRecentFilesMenu()
    #################################################? RECENTE FILE SECTION?################################################

    def updateOptions(self,opts):

        self.opts.update({self.optsDict[key]:item for key,item in opts["Graph settings"].items()})

        
        if self.opts["downsample"]:
            self.plotgraph.setDownsampling(mode=self.opts["downsample_type"],
                                            ds=self.opts["downsample_ratio"])
        xp_axis = self.plotgraph.getAxis('bottom')
        xp_axis.setLabel(text=self.opts["X_title"],units=self.opts["X_unit"])
        xticks = [self.opts["X_major_t"],self.opts["X_minor_t"]]
        xp_axis.setTickSpacing(xticks[0],xticks[1])
        yp_axis = self.plotgraph.getAxis('left')
        yp_axis.setLabel(text=self.opts["Y_title"],units=self.opts["Y_unit"])
        yticks = [self.opts["Y_major_t"],self.opts["Y_minor_t"]]
        yp_axis.setTickSpacing(yticks[0],yticks[1])
        self.maingraph.setBackground(self.opts["background_color"])#passage du maingraph en fond blanc

        if opts["Import settings"][('File import setting', 'Use latest files as working folder')]:

            with open(self.user_config, "r") as f:
                data = json.load(f)
                files = data.get("files", [])
            if files:
                self.defaultdir = files[0]
        else:
            self.defaultdir = opts["Import settings"][("File import setting",'Set working folder')]

    def initGraph(self):
        """
        Méthode gérant l'initialisation du graphique maingraph,
        on ajoute un plot en position 0,0: plotgraph
        """
        """
        self.maingraph : pg.RemoteGraphicsView
        #self.maingraph.setBackground('w')#passage du maingraph en fond blanc
        self.maingraph.pg.setConfigOptions(antialias=True)  ## prettier plots at no cost to the main process!
        #self.plotgraph = self.maingraph.addPlot(row = 0, col = 0)
        self.plotgraph = self.maingraph.pg.PlotItem()
        self.plotgraph._setProxyOptions(deferGetattr=True)  ## speeds up access to rplt.plot
        self.maingraph.setCentralItem(self.plotgraph)
        self.vb=self.plotgraph.vb
        self.actionQuit.triggered.connect(self.maingraph.close)
        """

        self.plotgraph = self.maingraph.addPlot(row = 0, col = 0)
        #self.maingraph.setBackground('w')#passage du maingraph en fond blanc
        xp_axis = self.plotgraph.getAxis('bottom')
        xp_axis.setLabel(text=self.opts["X_title"],units=self.opts["X_unit"])
        xp_axis.enableAutoSIPrefix(False)
        xticks = [1200,300]
        xp_axis.setTickSpacing(xticks[0],xticks[1])
        yp_axis = self.plotgraph.getAxis('left')
        yticks = [100,25]
        yp_axis.setTickSpacing(yticks[0],yticks[1])
        yp_axis.setLabel(text=self.opts["Y_title"],units=self.opts["Y_unit"])
        yp_axis.enableAutoSIPrefix(False)
        self.plotgraph.showGrid(x = True, y = True,alpha = 0.3)
        #self.plotgraph.vb.state['aspectLocked'] = yticks[0]/xticks[0]
        #self.plotgraph.setYRange(-500,500)
        #self.plotgraph.setXRange(0,7200)
        self.plotgraph.setMouseEnabled(x = True, y = True)
        self.legend = pg.LegendItem((80,60), offset = (70,20),colCount = 2,verSpacing = -5)
        #la récupération de la viewbox du plotgraph permet l'utilisation du curseur (mouseMoved)
        self.vb = self.plotgraph.vb
        '''self.vb.setLimits(  xMin=-2000,
                            xMax=10**4,
                            yMin=-5*10**2,
                            yMax=5*10**2)'''
        if self.opts["downsample"]:
            self.plotgraph.setDownsampling(mode=self.opts["downsample_type"],
                                            ds=self.opts["downsample_ratio"])


    def initCursorsTab(self):
        """
        Méthode gérant l'initialisation du Widget GraphTree
        """

        children = [{'name':'Get signals','type': 'group','children':
                            [
                                {'name':'Signal name','type':'str',"value":''},
                                {'name':'Search','type':'action'}
                            ]
                    },
                    {'name':'Graphics items','type': 'group','children':
                        [
                            CustomParameters.MouseCursors(name='Mouse cursor',
                                                        graphWidget = self.plotgraph),
                            CustomParameters.LinkedCursors(name = 'Vertical cursors',
                                            graphWidget = self.plotgraph,
                                            cursors_setting = {'angle':90,
                                            'pos':[1200,3600],
                                            'pen':pg.mkPen(color = 'r'),
                                            'label':'{value:0.0f}s',
                                            'labelOpts':{'color': (200,0,0),
                                                        'fill':(200,200,200,100),
                                                        'movable': True}}),
                            CustomParameters.LinkedCursors(name = 'Horizontal cursors',
                                            graphWidget = self.plotgraph,
                                            cursors_setting = {'angle':0,
                                            'pos':[50,100],
                                            'pen':pg.mkPen(color = 'y'),
                                            'label':'T = {value:0.2f}°C',
                                            'labelOpts':{'color': (200,200,100),
                                                        'fill': (200,200,200,50),
                                                        'movable': True}}),
                            {'name':'Legend','type':"bool", 'value':False},
                            {'name':'Add Text','type':'action'},
                        ]
                    }]
        self.graphTree_params = ptree.Parameter.create(name = 'Graphs options', type = 'group',
                                        children = children)
        self.graphTree.setParameters(self.graphTree_params)
        self.graphTree_params.param('Graphics items','Add Text').sigActivated.connect(lambda x :self.addText())
        #mouseCursor sert pour les curseurs (mis à jour ssi les curseurs sont actifs)
        self.mouseCursor=self.graphTree_params.param('Graphics items','Mouse cursor')
        #mousePos est toujours actif et initialisé à 0,0
        self.mousePos=QtCore.QPointF(0,0)


    def initTrigTab(self):
        """
        Méthode gérant l'initialisation du Widget GraphTree
        """

        children = [{'name':'Trigger Channel','type': 'group','children':
                            [
                                {'name':'Signal name','type':'str',"value":''},
                                {'name':'Search','type':'action'}
                            ]
                    },
                    {'name':'Graphics items','type': 'group','children':
                        [
                            CustomParameters.TriggerCursor(name = 'Edge Trigger',
                                            graphWidget = self.plotgraph,
                                            cursors_setting = {'angle':90,
                                            'pos': 0,
                                            'pen':pg.mkPen(color = (223, 109, 20),style=QtCore.Qt.PenStyle.DashLine),
                                            'label':'{value:0.3f}',
                                            'labelOpts':{'color': (223, 109, 20),
                                                        'fill': (200,200,200,50),
                                                        'movable': True}}),
                        ]
                    }]
        self.TriggerTree_params = ptree.Parameter.create(name = 'Graphs options', type = 'group',
                                        children = children)
        self.TriggerTree.setParameters(self.TriggerTree_params)
        #mouseCursor sert pour les curseurs (mis à jour ssi les curseurs sont actifs)

    def closeEvent(self, event):
        """
            Méthode gérant la fermeture de toutes les fenêtres annexes
        Args:
            event (QEvent): Evenement devant provoquer la fermeture de toutes
                            les fenêtres (ex: la fermeture de la MainWindow)
        """
        #ferme toutes les fenêtres annexes qui existent permettant de ferme le GL depuis la MW
        if self.windows_set:
            self.windows_set.close()

        if self.graphWindows:
            for window in self.graphWindows:
                window.close()

    def highlight(self,item,curve):
        """
        Méthode sur évènement (sélection d'un item), permettant de mettre en évidence
        la courbe correspondante
        Arguments:
                item   {QTreeWidgetItem}   -- item sélectionné
                curve  {PlotItem}          -- courbe correspondante
        Returns:
                None                       -- MAJ du graph
        """
        #Augmente la largeur de la courve et la remonte au-dessus des autres plotitems : Zval = 10
        if curve is not None:
            CustomFunctions.updateCurve(curve,width = 3,z_val = 10)
        CustomFunctions.setItemFont(item,bold = True)
        def recursiveExpension(treeItem):
            if treeItem.parent():
                parent_item = treeItem.parent()
                parent_item.setExpanded(True)
                recursiveExpension(parent_item)
        recursiveExpension(item)
        #si l'on vient de sélectionner une nouvelle courbe et que l'ancienne courbe a été définie
        #au moins une fois
        if self.old_highlight != (item,curve):
            if self.old_highlight[1] is not None:
                CustomFunctions.updateCurve(self.old_highlight[1])

            if self.old_highlight[0] is not None:
                CustomFunctions.setItemFont(self.old_highlight[0],bold = False)
                if self.old_highlight[0].type is not CustomTypes.itemType.FILE:
                    self.old_highlight[0].struct.pen.setWidth(1)
                #! écraser la largeur de la courbe sauvegardée dans l'item
                #! afin de ne pas recharger l'ancienne valeur du highlight (3)
        self.old_highlight = (item,curve)

    def treeMenu(self):
        """
        Méthode vide qui sera décrite par la classe héritant de GLWindow
        """
        pass

    def mouseMoved(self,evt):
        """
        Méthode vide qui sera décrite par la classe héritant de GLWindow
        """
        pass

    def updateMessageBar(self,evt):

        self.statusbar.showMessage(evt)

    def loadFileDialog(self,fileType : CustomTypes.fileType.JSON,adress = None):
        """
        Méthode gérant la fenêtre de dialogue permettant de charger des fichiers .VCD
        dans l'appli.

        Arguments:
                adress      --
                fileType    --
        Returns:
                None        --
        """
        load_dict = {CustomTypes.fileType.JSON:("Loading JSON files","json Files (*.JSON)"),
                    CustomTypes.fileType.TXT:("Loading .txt files","txt Files (*.txt)")
                    }

        if adress:
            fnames = adress
        else:
            message,file_extension = load_dict[fileType]
            self.statusbar.showMessage(message)
            fnames,_ = QFileDialog.getOpenFileNames(self,"Open file",self.defaultdir,file_extension)
            if not fnames:
                return
        if isinstance(fnames,list):
            adress=fnames[0]
        else:
            adress=fnames
        self.saveRecentFileAdress(adress)
        for fname in fnames:
            if fname:
                name = fname[fname.rfind('/')+1:len(fname)-4]
                existing_file = [self.treefile.topLevelItem(i).text(0)
                                for i in range(self.treefile.topLevelItemCount())]
                if name in existing_file:
                    self.statusbar.showMessage(f"File: {fname} already loaded")
                    continue
                self.statusbar.showMessage(f"Loading file: {fname}")
                #?ne charge qu'un seul fichier par appel afin de retirer les fichiers
                #?déjà chargés de la liste fnames (la méthode pourrait charger fnames).
                self.loadFile_signal.emit((fileType,[fname]))

    def loadSaveDialog(self):
        """
        Méthode gérant la fenêtre de dialogue permettant de charger des fichiers .CSV
        de type GLviewer dans l'appli.

        Arguments:
                None                --
        Returns:
                Tuple(Adress,name)  --
        """
        default_filename=self.defaultdir+ "/new_project.json"
        filename, _ = QFileDialog.getSaveFileName(
        self, "Save the graphtec viewer model", default_filename, "json File (*.json)")

        self.saveFile_signal.emit(filename)