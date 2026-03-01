"""
Module contenant des QWidgets et QMainWindow générique pouvant être chargés pour différents projet
"""

import numpy as np


from PyQt6.QtWidgets import (QApplication, QMainWindow,QAbstractItemView,QDialog,QColorDialog,
                            QGraphicsItem,QWidget,QFileDialog,QMenu)

from PyQt6.uic import loadUi
from PyQt6 import QtGui,QtCore
import CustomDialogs

import pyqtgraph.parametertree as ptree
import pyqtgraph as pg
import sys

PATH='./GLviewer_customItemWidget/views/'



class GraphWindow(QMainWindow):
    """
    Classe héritant de QMainWindow permettant de rapidement créer un interface graphique
    """


    def __init__(self,*args,**kwargs):

        if "allowPaste" in kwargs.keys():
            self.allowPaste=kwargs.pop("allowPaste")
        else:
            self.allowPaste=False
        if "grid" in kwargs.keys():
            self.showGrid=kwargs.pop("grid")
        else:
            self.showGrid=False
        super(GraphWindow, self).__init__(*args,**kwargs)
        self.setWindowIcon(QtGui.QIcon('icon.ico'))
        #Load the UI Page
        loadUi(PATH+'GraphWindow.ui', self)
        self.optsDict = {   "X axis title"                          : "X_title",
                            "X axis unit"                           : "X_unit" ,
                            "Y axis title"                          : "Y_title",
                            "Y axis unit"                           : "Y_unit" ,
                            "Update axis when signal selected"      : "update_selected",
                            ("Downsample", "Active")                 : "downsample",
                            ("Downsample", "Downsampling factor")    : "downsample_ratio",
                            ("Downsample", "Downsampling type")      : "downsample_type",
                            }

        #options de l'objet
        self.opts=  {
                    "X_title"              : "Temps",
                    "X_unit"               : "s",
                    "Y_title"              : "Temperature",
                    "Y_unit"               : "°C",
                    "update_selected"      : True,
                    "downsample"           : True,
                    "downsample_ratio"     : 10,
                    "downsample_type"      : "peak",
                    }


        if self.showGrid:
            self.InitGrid()

        self.file_path=None
        self.setAcceptDrops(self.allowPaste)
        #plotgraph est un graphiclayoutwidget, on ajoute un plot
        #maingraph en position 0,0 du layout plotgraph
        #autodownsampling afin de réduire la contrainte d'affichage des courbes thermiques
        #(rapport échantillon/signal excellent)
        #self.plotgraph.setDownsampling(ds=10,auto=False,mode='peak')
        #self.plotgraph.setMouseEnabled(x=True, y=False)
        self.initGraph()
        self.graphMenu()

        #*loadFile_signal(voir CustomWindows) a pour slot ImportController.loaderSelect
        #*UIsignals (voir CustomWindows) a pour slot MainController.filterUIsignals


    def graphMenu(self):

        menu : QMenu = self.plotgraph.vb.menu

        addText_action = QtGui.QAction('Add text', menu)
        addText_action.triggered.connect(lambda x :self.addText())
        viewAllAction=menu.actions()[0]
        menu.insertAction(viewAllAction,addText_action)
        menu.insertSeparator(viewAllAction)
        '''
        res = menu.exec(event.globalPos())
        if res == additionnalAction0:
            if self.mouseCursor.param('snap to selected signal'):
                self.addText(parent=self.mouseCursor.curvePoint)
            else:
                print("non")
        elif res == additionnalAction1:
            self.isolateItems()'''

    def addText(self,parent=None,pos=None):
        """_summary_
        """
        item_av=self.plotgraph.allChildItems()
        text = CustomDialogs.pgText()
        text.textEditor()
        self.plotgraph.addItem(text)
        if parent is not None:
            text.setParentItem(parent)
        else:
            text.setParentItem(self.plotgraph.vb)
            #remplacer vb par self.plotgraph.graphicsItem()?
        if pos is not None:
            text.setPos(pos)
        else:
            text.setPos(QtCore.QPointF(0,0))

        for item in self.plotgraph.allChildItems():
            if item in item_av:
                continue
            else:
                print(item)
                print(item.text)
                break


    def initGraph(self):
        """
        Méthode gérant l'initialisation du graphique maingraph,
        on ajoute un plot en position 0,0: plotgraph
        """
        self.plotgraph = self.maingraph.addPlot(row = 0, col = 0)
        self.maingraph.setBackground('w')#passage du maingraph en fond blanc

        xp_axis = self.plotgraph.getAxis('bottom')
        xp_axis.setLabel(text=self.opts["X_title"],units=self.opts["X_unit"])
        xp_axis.enableAutoSIPrefix(False)
        xticks = [1200,300]
        xp_axis.setTickSpacing(xticks[0],xticks[1])
        yp_axis = self.plotgraph.getAxis('left')
        yticks = [10,2]
        yp_axis.setTickSpacing(yticks[0],yticks[1])
        yp_axis.setLabel(text=self.opts["Y_title"],units=self.opts["Y_unit"])
        yp_axis.enableAutoSIPrefix(False)
        #self.plotgraph.vb.state['aspectLocked'] = yticks[0]/xticks[0]
        self.plotgraph.setYRange(0,160)
        self.plotgraph.setXRange(0,7200)
        self.plotgraph.setMouseEnabled(x=True, y=False)
        self.plotgraph.showGrid(x=True, y=True,alpha=0.3)
        self.legend = pg.LegendItem((80,60), offset = (70,20),colCount = 2,verSpacing = -5)
        #la récupération de la viewbox du plotgraph permet l'utilisation du curseur (mouseMoved)
        self.vb = self.plotgraph.vb

        if self.opts["downsample"]:
            self.plotgraph.setDownsampling(mode=self.opts["downsample_type"],
                                            ds=self.opts["downsample_ratio"])
        self.plotgraph.plot()

    def keyPressEvent(self, event):
        """
        Méthode dédié à l'apparition d'une entrée du clavier
        Args:
            event (QEvent): entrée clavier
        """

        if event.key() == QtCore.Qt.Key.Key_Delete | self.hasFocus() and self.allowPaste:
            try:
                Qitem=self.modeltree.selectedItems[0]
                id=self.modeltree.indexFromItem(Qitem)
                self.curves[id].graph['data']
                print('RESTE A FAIRE !!')
                #//TODO: utiliser les vrais état retour du messagebox (actuellement .exec
                #//TODO retourne des int)
            except:
                pass
            event.accept()
        elif (  event.key() == QtCore.Qt.Key.Key_V and
                event.modifiers()==QtCore.Qt.KeyboardModifier.ControlModifier):

            self.paste_image()
            event.accept()
        else:
            event.ignore()

    def dragEnterEvent(self, event):
        """
        Méthode gérant l'entrée de l'image dans la fenêtre principale
        Args:
            event (QEvent): entrée clavier
        """
        if event.mimeData().hasImage:
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        """
        Méthode gérant le déplacement d'une image dans la fenêtre principale
        Args:
            event (QEvent): dépose d'une image
        """
        if event.mimeData().hasImage:
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        """
        Méthode gérant la dépose d'une image dans le widget plotgraph
        Args:
            event (QEvent): dépose d'une image
        """
        if event.mimeData().hasImage and self.allowPaste:
            event.setDropAction(QtCore.Qt.DropAction.CopyAction)
            file_path = event.mimeData().urls()[0].toLocalFile()
            self.set_image(file_path)

            event.accept()
        else:
            event.ignore()

    def set_image(self, file_path):
        """
        Méthode gérant le chargement de l'image dans le plotgrah depuis une
        adresse
        Args:
            file_path (str): adress de l'image devant être chargée
        """
        self.file_path=file_path
        self.clearGraph()
        img = QtGui.QImage(QtGui.QPixmap(file_path))
        self.loadGraph(img=img)

    def paste_image(self):
        """
        Méthode gérant la copie d'une image dans l'application : par exemple un ctrl+v
        """

        clipboard = QApplication.clipboard()
        mimeData = clipboard.mimeData()
        if mimeData.hasImage():
            img=QtGui.QImage(mimeData.imageData())
            self.loadGraph(img=img)
        else :
            return

    def clearGraph(self):
        """
        Méthode permettant de supprimer tous les élements graphiques du plotgraph
        """

        self.axis_configured=False
        self.plotgraph.clear()

    def loadGraph(self,img=None):
        """Méthode gérant l'affichage et le chargement de l'image

        Args:
            img (QImage, optional) --   Image devant être chargée. Defaults to None. Si aucunne
                                        image n'est fournie, une fenêtre de dialogue permet de
                                        choisir une image depuis l'explorateur
        """

        self.clearGraph()
        if not img :
            self.statusbar.showMessage("Load graphic picture")
            gname,_=QFileDialog.getOpenFileName(self,"Load graph image","",
                                                "Image Files (*.png *.jpg *.jpeg *.bmp)")
            img = QtGui.QImage(gname)
        #img = img.convertToFormat(QtGui.QImage.Format.Format_ARGB32_Premultiplied)
        imgArray = pg.imageToArray(img, copy=True,transpose=False)
        np_array=np.rot90(np.flip(imgArray,(1,0)))
        self.imgitem = pg.ImageItem(np_array)

        self.plotgraph.addItem(self.imgitem)
        self.imgitem.setZValue(-100)
        #range_ = self.plotgraph.getViewBox().viewRange()
        _shape=self.imgitem.image.shape
        xmin=-_shape[0]*0.1
        ymin=-_shape[1]*0.1
        xmax=_shape[0]*1.1
        ymax=_shape[1]*1.1



#**********************************************************************************************************#
#   WABDigitize est une application permettant de rapidement extraire les données d'un graphique, fichier  #
#   .CSV ou d'un model PLECS (.XML) afin de créer ou modifier un modèle utilisable sous PLECS              #
#**********************************************************************************************************#

def main():
    app = QApplication(sys.argv)
    main = GraphWindow()
    #main.installEventFilter(main)
    #main.openWorkSpace(adress='./parametres_GL.JSON')
    main.show()

    sys.exit(app.exec())


if __name__ == '__main__':
    main()

