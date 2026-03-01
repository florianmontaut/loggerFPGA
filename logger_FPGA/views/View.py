import numpy as np
import json

from PyQt6.QtWidgets import QMenu,QApplication,QMenu
from PyQt6 import QtGui,QtCore

import pyqtgraph as pg

from ressources import CustomFunctions
from views import CustomWindows,CustomDialogs
from ressources import CustomTypes
from model.Model import Model
from functools import partial


class MainWindow(CustomWindows.CustomMainWindow):
    """
    Viewer du GLviewer

    Classe parent:
        QMainWindow (CustomWindows.GLWindow): classe ou superclasse contenant les méthodes
                                        générique du viewer (initialisation,options,etc...)
    """

    def __init__(self,model:Model,params,**opts):

        super(MainWindow, self).__init__(params,**opts)
        self._model : Model = model
        self.sessions_opts={}

        #*Ajout des actions du menu principal*# : import_controller
        self.actionLoad_json.triggered.connect(lambda : self.loadFileDialog(
                                                fileType = CustomTypes.fileType.JSON))
        self.actionLoad_txt.triggered.connect(lambda : self.loadFileDialog(
                                                fileType = CustomTypes.fileType.TXT))

        self.actionParameters.triggered.connect(self.openOptionsWindow)

        self._model.MAJ_files.connect(lambda: self.traceGraph(self._model.qitems_dict))
        self._model.MAJ_signal.connect(self.loadSignal)
        self.treefile.itemChanged.connect(self.onItemChecked)

        #self._model.MAJ_curves.connect(lambda x: self.UIsignals.emit([CustomTypes.qSignalType.SELECT,x]))
        #le signal pour mettre à jour tous les objets
        self._model.MAJ_options.connect(self.updateOptions)

        #self.connectButton.clicked.connect(self.connectToCPU)
        #self.disconnectButton.clicked.connect(self.DisconnectCPU)
        #self.PauseButton.clicked.connect(self.PauseCPU)
        self.connectButton.clicked.connect(lambda: self.actionsConcentrator(CustomTypes.qSignalType.CONNECT))
        self.disconnectButton.clicked.connect(lambda: self.actionsConcentrator(CustomTypes.qSignalType.DISCONNECT))
        self.PauseButton.clicked.connect(lambda: self.actionsConcentrator(CustomTypes.qSignalType.PAUSE))
        self.curves=[]
        self.data=[]
        self.n_trames=1

        self.toggleButtons()

        #self.graphMenu()
        #*loadFile_signal(voir CustomWindows) a pour slot ImportController.loaderSelect
        #*UIsignals (voir CustomWindows) a pour slot MainController.filterUIsignals

        '''
                QTreeView {
            background-color: rgb(46, 52, 54);
            alternate-background-color: rgb(39, 44, 45);
            color: rgb(238, 238, 238);
        }
        QLabel {
            color: rgb(238, 238, 238);
        }
        QComboBox {
            background-color: rgb(46, 52, 54);
            color: rgb(0, 0, 238);
        }
        QSpinBox {
            background-color: rgb(46, 52, 54);
            color: rgb(0, 0, 238);
        }
        QPushButton {
            color: rgb(0, 0, 238);
        }
        QTreeView::item:has-children {
            background-color: '#212627';
            color: rgb(233, 185, 110);
        }'''


    def graphMenu(self):

        menu : QMenu = self.vb.menu
        addText_action = QtGui.QAction('Add text', menu)
        addText_action.triggered.connect(lambda x :self.addText())
        isolate_action = QtGui.QAction("Isolate selection", menu)
        isolate_action.triggered.connect(self.isolateItems)
        viewAllAction=menu.actions()[0]
        menu.insertActions(viewAllAction,[addText_action,isolate_action])
        menu.insertSeparator(viewAllAction)
        '''
        res = menu.exec(event.globalPos())
        if res == additionnalAction0:
            if self.mouseCursor.param('snap to selected signal'):
                self.addText(parent=self.mouseCursor.curvePoint)
            else:
                print("non")
        elif res == additionnalAction1:
            self.isolateItems()
        '''

    def toggleButtons(self,state=None):

        if state is None:
            state=self.connectButton.isEnabled()
            state^=1
        self.connectButton.setEnabled(state)
        self.disconnectButton.setEnabled(state)
        self.PauseButton.setEnabled(state)


    def treeMenu(self):
        """
        Méthode gérant le paramétrage des ménus de la MainWindow
        """
        # Show the context menu

        menu = QMenu(self.treefile)
        maj_graph_action = QtGui.QAction("Trace checked", self.treefile)
        maj_graph_action.triggered.connect(lambda: self.traceGraph(self._model.qitems_dict))

        export_action = QtGui.QAction("Export selection", self.treefile)
        export_action.triggered.connect(self.export)

        isolate_action = QtGui.QAction("Isolate selection", self.treefile)
        isolate_action.triggered.connect(self.isolateItems)


        menu.addAction(maj_graph_action)
        menu.addAction(isolate_action)
        menu.addSeparator()
        menu.addAction(export_action)

        if self.treefile.topLevelItemCount()<1:
            menu.setDisabled(True)
        else:
            menu.setEnabled(True)
        menu.exec(QtGui.QCursor.pos())

    def onItemChecked(self,item,col):

        if col!=0 or item.type is CustomTypes.itemType.FILE:
            return
        else:
            if item.state is QtCore.Qt.CheckState.Unchecked:
                if item.curve in self.plotgraph.listDataItems():
                    self.plotgraph.removeItem(item.curve)
            elif item.state is QtCore.Qt.CheckState.Checked and not item.isDisabled():
                if item.curve not in self.plotgraph.listDataItems():
                    self.plotgraph.addItem(item.curve)
                    #self.updateGraphBounds()
            if self.opts["update_selected"]:
                self.vb.autoRange()

    def openOptionsWindow(self):
        """
        Méthode gérant l'éxécution de la fenêtre de dialogue regroupant
        les options du GLViewer
        """

        OptionsWindow = CustomDialogs.OptionsPannel(parameters = self.option_params,
                                            UpdateStates = self._model.settings)
        OptionsWindow.accepted.connect(lambda: self._model.changeSettings(
                                                    OptionsWindow.getOptions()))
        OptionsWindow.show()


    def isolateItems(self,q_items:list=None):
        """
        Méthode permettant de cocher uniquement le(s) élément(s) sélectionné(s)
        Arguments:
                QItems {list[QTreeWidgetItem]} --   Si None la fonction récupère la
                                                    sélection actuelle dans le treefile
        Returns:
                None   --
        """
        trace_dict={}
        q_items=self.treefile.selectedItems()
        for n in range(self.treefile.topLevelItemCount()):
            self.treefile.topLevelItem(n).checkItem(False)
        for item in q_items:
            item.checkItem(True)
            trace_dict[item.absoluteId]=item
        self.traceGraph(trace_dict,TreeMAJ=False)

    def keyPressEvent(self, event):
        if (event.modifiers() & QtCore.Qt.KeyboardModifier.ControlModifier and
                                event.key() == QtCore.Qt.Key.Key_Enter):
            event.accept()
            try:
                Qitem = self.treefile.selectedItems()
                for item in Qitem:
                    if self.state:
                        item.checkItem(False)
                    else:
                        item.checkItem(True)
            except:
                pass
        elif event.key() == QtCore.Qt.Key.Key_Delete :
            print(event.key())
            if self.treefile.hasFocus():
                try:
                    self.removeItems(Qitem)
                except:
                    print("None: erreur treefile sélectionné mais pas de Qitem à supprimer")
                    pass
            elif True:
                pass
        elif event.key() == QtCore.Qt.Key.Key_Space:
            if self.treefile.hasFocus() or self.plotgraph.hasFocus():
                self.isolateItems()
        event.ignore()

    def removeItems(self,it = None):
        if it :
            table_qitems = [it]
        else:
            table_qitems = CustomFunctions.getItems(self.treefile,type_methode = 'selected')
        if table_qitems is not None:
            self.UIsignals.emit([CustomTypes.qSignalType.DEL,table_qitems])

    def export(self):
        # Handle the "Action 1" action

        item = CustomFunctions.getItems(self.treefile,type_methode = 'selected') [0]
        file_id,signal_id=item.file_id
        if item.params.child('Curve modeling','Use vertical cursors as limits').value():
            limits=self.graphTree_params.child('Graphics items','Vertical cursors').getData()[0:2]
            if limits is not None:
                limits=limits.reverse() if limits[1]-limits[0]<0 else limits
        else:
            limits=None
        data=self._model.gl_files[file_id].getXYFromDataFrame(name=item.name,custom_limit=limits)
        """listCoef=[np.format_float_scientific(val, unique=False, precision=3)
                    for val in data]

        coefStr=''.join(['\t'.join(listCoef)])"""
        data=list(zip(data[0],data[1]))
        data=[str(val[0])+'\t'+str(val[1]) for val in data]
        exportData=''.join(['\n'.join(data)])
        QApplication.clipboard().setText(exportData)

    def legendItem(self,state):
        #! faire un custom parameter intégrant la légende: nécessite de passer
        #! les noms des différentes courbes depuis le viewer (passer le model ?)
        pass
        """
        if self._model.curves:
            if state:
                self.legend.setParentItem(self.plotgraph.graphicsItem())
                for item in self.plotgraph.listDataItems():
                    if isinstance(item,pg.PlotDataItem):
                        QItem = [tree_item for curve,tree_item in self._model.curves
                                if curve==item][0]
                        self.legend.addItem(item, QItem.text(0))
            else:
                self.legend.clear()
                self.plotgraph.removeItem(self.legend)
        """


    def mouseMoved(self,evt):
        """
        Méthode permettant de récupérer la valeur des courbes en fonction de la position
        en X du curseur sur le graphe
        Arguments:
                None  --
        Returns:
                None  -- MAJ du champ valeur du Treefile des différents courbes affichées
        """
        pos = evt[0]
        if self.plotgraph.sceneBoundingRect().contains(pos):
            mousePoint = self.vb.mapSceneToView(pos)
            self.mousePos=mousePoint
            index = int(mousePoint.x())
            self.mouseCursor.mouseUpdate(mousePoint)
            if len(self.plotgraph.listDataItems())>0:
                current_sampling = 1
                #méthode compatible avec un treefile widget avec item déplaçable.
                #Car dans ce cas de figure file_ID  = / =  de l'indice i du TreeWidget
                files_id = [self.treefile.topLevelItem(i).file_id[0]
                            for i in range(self.treefile.topLevelItemCount())]
                for n,file_id in enumerate(files_id):
                    # TODO : offset ne fonctionne pas si sampling=!
                    index_sample=self._model.getFileAttribute(file_id,attribute='sampling')
                    if index_sample != current_sampling:
                        current_sampling = index_sample
                    nearest_index = int(np.floor((index-
                                                self._model.getFileAttribute(file_id,
                                                                            attribute='offset'))/
                                                current_sampling))
                    max_x=self._model.getFileAttribute(file_id,attribute='stop_x')
                    if nearest_index>0:
                        #retourne un objet pandas.series
                        curves_values = self._model.getFileAttribute(   file_id,
                                                                        attribute='getYValues',
                                                                        index=nearest_index)
                    else:
                        curves_values = None
                    self.treefile.blockSignals(True)
                    for i in range(self.treefile.topLevelItem(n).childCount()):
                        element = self.treefile.topLevelItem(n).child(i)
                        if curves_values is None or nearest_index<0 or element.isDisabled() \
                            or nearest_index > max_x:
                            element.setText(1,'-')
                        else:
                            if isinstance(curves_values.iloc[i],float):
                                val = str('{:.2f}'.format(curves_values.iloc[i]))
                            else:
                                val = '-'
                            element.setText(1,val)
                    self.treefile.blockSignals(False)
                self.treefile.resizeColumnToContents(1)

    def actionsConcentrator(self,key:CustomTypes.qSignalType)->None:
        """
        Méthode servant d'interface entre l'arborescence des fichiers GL et les méthodes
        de traitements des signaux comme 'filtrer', 'deltaT', etc..
        Args:
            key (str):  key permettant de sélectionner la méthode à appliquer
        """

        #table_qitems = CustomFunctions.getItems(self.treefile,type_methode = 'selected')
        if key is CustomTypes.qSignalType.CONNECT:

            self.UIsignals.emit((CustomTypes.qSignalType.CONNECT,None))
        elif key is CustomTypes.qSignalType.DISCONNECT:
            self.UIsignals.emit((CustomTypes.qSignalType.DISCONNECT,None))
        elif key is CustomTypes.qSignalType.PAUSE:
            self.UIsignals.emit((CustomTypes.qSignalType.PAUSE,None))
        else:
            self.UIsignals.emit((key,None))

    def loadTree(self,item_dictionnary):

        #supression de l'affichage actuel
        self.treefile.invisibleRootItem().takeChildren()
        for key,item in item_dictionnary.items():

            if item.type is CustomTypes.itemType.FILE :
                self.treefile.invisibleRootItem().addChild(item)
                item.setExpanded(True)
                item.checkItem(True)
            else:
                self._model.qitems_dict[item.parentId].addItem(item)
                item.checkItem(True)

        self.treefile.resizeColumnToContents(0)
        self.treefile.resizeColumnToContents(1)

    def loadSignal(self,parent,item):

        parent.addItem(item)
        item.checkItem(True)
        self.treefile.resizeColumnToContents(0)
        self.treefile.resizeColumnToContents(1)
        if item.state is QtCore.Qt.CheckState.Checked and item.type is not CustomTypes.itemType.FILE:
                self.traceItem(item)


    def traceGraph(self,item_dict,TreeMAJ=True):
        """
        Méthode permettant de tracer les courbes sur le graphique
        Arguments:
                None   --
        Returns:
                None   -- MAJ du grahique
        """

        for item in self.plotgraph.listDataItems():
            if isinstance(item,pg.PlotDataItem):
                self.plotgraph.removeItem(item)
                #print(f'removed {item}')
        if TreeMAJ:
            self.loadTree(item_dict)
        #FileItems=[val for key,val in item_dict.items() if val.type is CustomTypes.itemType.FILE]

        for key,item in item_dict.items():

            if item.state is QtCore.Qt.CheckState.Checked and item.type is not CustomTypes.itemType.FILE:
                self.traceItem(item)

        #self.updateGraphBounds()
        #! semble déconner après plusieurs opérations de type troncage/décalage

    def traceItem(self,item):
        """
        Méthode permettant de tracer une courbes sur le graphique
        Arguments:
                item {QTreeWidgetItem}   -- TreeWidgetItem corespondant à la courbe à tracer
        Returns:
                None                     -- MAJ du grahique
        """
        if item.curve is not None:
            self.plotgraph.removeItem(item.curve)
        curve=item.generateCurve()
        if curve is not None:
            self.plotgraph.addItem(curve)

    """
    # TODO : ajouter text dans le menu contextuel du graph => LE TEXT NE MARCHE PLUS
    # TODO : ajouter isolateItem dans ce menu
    def contextMenuEvent(self, event):
        menu = QMenu(self)
        additionnalAction0 = menu.addAction('Add text')
        additionnalAction1 = menu.addAction('Isolate selection')

        res = menu.exec(event.globalPos())
        if res == additionnalAction0:
            if self.mouseCursor.param('snap to selected signal'):
                self.addText(parent=self.mouseCursor.curvePoint)
            else:
                print("non")
        elif res == additionnalAction1:
            self.isolateItems()"""

    def updateGraphBounds(self,margin=0.2):

        self.vb.autoRange()
        #20% margin
        range_ = self.vb.viewRange()
        delta_x=(range_[0][1]-range_[0][0])*(1+margin)
        delta_y=(range_[1][1]-range_[1][0])*(1+margin)
        '''print(range_)
        center_x=(range_[0][1]+range_[0][0])/2
        center_y=(range_[1][1]+range_[1][0])/2
        print(center_x-delta_x/2,center_x+delta_x/2,center_y-delta_y/2,center_y+delta_y/2)
        '''

        self.vb.setLimits(  minXRange=delta_x/1000,
                            maxXRange=delta_x*1.2,
                            minYRange=delta_y/100,
                            maxYRange=delta_y*1.2)

    def traceLiveStream(self,data):

        color=[
                (255,0,0,127),
                (0,255,0,127),
                (0,0,255,127),
                (255,255,0,127),
                (255,0,255,127),
                (0,255,255,127),
                (255,200,100,127),
                (200,255,100,127)
            ]
        #self.plotgraph.clear()
        #self.plotgraph.plot(data, clear=True, _callSync='off')
        print(data.shape)
        if not len(self.curves) == data.shape[1]:
            self.curves=[]
            self.plotgraph.clear()
            for curve_num in range(data.shape[1]):
                self.data.append(np.empty(data.shape[1]))
                self.data[curve_num]=data[:,curve_num]
                self.curves.append(pg.PlotDataItem(pen=pg.mkPen((color[curve_num]))))

                self.plotgraph.addItem(self.curves[curve_num])
                self.n_trames=1



        pos_trig=self.getTrigIndex(data,1,2.35)

        abs_x=np.arange(data.shape[0])
        for curve_num in range(len(self.curves)):
            self.curves[curve_num].setData(x=abs_x,y=data[:,curve_num])
            self.curves[curve_num].setPos(x=pos_trig,y=0)
        self.n_trames+=1
        self.plotgraph.vb.setAutoPan()

    def getTrigIndex(data,channel,thres,type=None):

        if type is None:
            index=np.nonzero(data[channel]==thres)[0][0]
            if index is None:
                index = 0
        else:
            index=0

        return index




        '''
        n_words=int(16384/data.shape[1])
        append= True if n_words*self.n_trames > len(self.data[0]) else False
        for curve_num in range(len(self.curves)):
            print(curve_num)
            if append:
                tmp=self.data[curve_num]
                self.data[curve_num]=np.empty(self.data[curve_num].shape[0]*2)
                self.data[curve_num][:len(tmp)]=tmp
                ptr=int(len(tmp)+n_words-1)
                self.data[curve_num][len(tmp)-1:ptr]=data[:,curve_num]
            else:
                if self.n_trames==1:
                    self.data[curve_num]=data[:,curve_num]
                else:
                    ptr=int(self.n_trames*n_words)

                    ptr=int(n_words*(self.n_trames-1)-1)
                    #print(len(tmp),ptr)
                    self.data[curve_num][ptr:n_words*self.n_trames-1]=data[:,curve_num]
            self.curves[curve_num].setData(x=np.arange(self.data[curve_num].shape[0]),y=self.data[curve_num]/16384)
        self.n_trames+=1
        self.plotgraph.vb.setAutoPan()'''
        """for i in range(data.shape[1]):

            self.plotgraph.plot(x=abs_x, y=data[:,i], clear=False, _callSync='off')"""