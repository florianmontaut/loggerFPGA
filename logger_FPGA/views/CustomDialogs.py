"""
Module contenant des QWidgets et QDialog générique pouvant être chargés pour différents projet
"""
import sys  # We need sys so that we can pass argv to QApplication
from collections import namedtuple
import numpy as np
from PyQt6.QtWidgets import (QApplication, QMainWindow,QFontDialog,QDialog,QColorDialog,
                            QGraphicsItem,QWidget,QFileDialog,
                            QMessageBox,QGridLayout,QDialogButtonBox)
from PyQt6.uic import loadUi
from PyQt6 import QtGui,QtCore

import pyqtgraph.parametertree as ptree
import pyqtgraph as pg
import pathlib

PATH=pathlib.Path(__file__).parent

class OptionsPannel(QDialog):
    """
    Objet Options Pannel héritant de QDialog. Permet de facilement créer une interface de
    contrôlant les options d'une application.
    """
    def __init__(self,*args,**kwargs):
        params=None
        if 'parameters' in kwargs:
            params=kwargs.pop('parameters')
        else:
            return -1
        if "UpdateStates" in kwargs:
            newStates=kwargs.pop('UpdateStates')
        else:
            newStates=0

        super(OptionsPannel, self).__init__(*args,**kwargs)
        self.setWindowIcon(QtGui.QIcon(str(PATH.absolute())+'\icon.ico')) #! ligne modifiée et non testée 05/09/2025
        #Load the UI Page
        loadUi(PATH/'GL_options.ui', self)
        self.tab_dict={}
        self.CreatePannels(params)
        self.buttonBox:QDialogButtonBox
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)

        #Dès que la fenêtre est ouverte, le programme bloque tout autre processus
        #self.setModal(QtCore.Qt.Windowity.ApplicationModal)

        if newStates is not None:
            self.setOptions(newStates)

    def CreatePannels(self,config):
        """
        Méthode générique permettant de créer n tabulation/panneaux selon le fichier de config
        Args:
            config {list(dict)} --  liste de dictionnaires où l'on retrouve deux arguments "name"
                                    et "params". "name" permet de donner un nom à la tabulation et
                                    "params" est un dictionnaire qui sera chargé dans le
                                    parameterTree de cette tabulation nouvellement créée.
                                    Ex: [dict("name":"toto",
                                    "params":{"name":"Arg1","type":"bool","value":"True"})
                                    ,dict(...]
        Returns:
            namedtuple --
        """
        tabItem=namedtuple('tabItem',['widget','parameters'])
        def addPannel(name,data,pannelFrame):
            """
            Méthode interne gérant la création de la tabulation
            Args:
                data {dict}     --  dictionnaire où l'on retrouve les deux arguments "name"
                                    et "params". Ex:dict("name":"toto","params":
                                    {"name":"Arg1","type":"bool","value":"True"})
                pannelFrame {QTabWidget} -- Widget parent dans lequel sera créer la tabulation
            Returns:
                tab  {QTabWidgetItem}        -- objet tabulation
                params {PyQtgraph.Parameter} -- groupe des "paramètres"
                                                du parametrerTree de la tabulation
            """

            tab=QWidget()
            gridLayout = QGridLayout(tab)
            gridLayout.setContentsMargins(5, 5, 5, 5)
            pannelWidget = ptree.ParameterTree(parent=tab)
            pannelWidget.setIndentation(20)
            pannelWidget.setObjectName("PannelWidget")
            pannelWidget.headerItem().setText(0, "1")
            pannelWidget.header().setVisible(False)
            gridLayout.addWidget(pannelWidget, 0, 0, 1, 1)

            params=ptree.Parameter.create(name='Parameters', type='group',children=data)
            pannelWidget.setParameters(params)
            pannelFrame.addTab(tab, "")
            pannelFrame.setTabText(pannelFrame.indexOf(tab),name)

            return tabItem(tab,params)

        #on distingue le chargement via un import JSON (sous forme de liste de dict),
        #d'un chargement direct (sous forme de dictionnaire de dictionnaire)
        if isinstance(config,list):
            for tab in config:
                #on créé un dictinnaire chargé de : "name"=[Widget,params]
                name=tab["name"]
                self.tab_dict[name]=addPannel(name,data=tab["params"],pannelFrame=self.tabWidget)
        else:
            for key,val in config.items():
                self.tab_dict[key]=addPannel(name=key,data=val,pannelFrame=self.tabWidget)

    def getOptions(self):
        """Méthode retournant les valeurs des paramètres des différentes tabulations
        Args:
            None
        Returns:
            dict(dict): dictionnaire contenant la valeur des paramètres des différentes tabulations
        """
        DictOptions={}
        for key,item in self.tab_dict.items():
            DictOptions[key]=self.GetParamsValues(item.parameters)
        return DictOptions

    def setOptions(self,states):
        """Méthode affectant les valeurs des paramètres des différentes tabulations
        Args:
            states {list(dict)} --  liste de dictionnaires où l'on retrouve deux arguments "name"
                                    et "params". "name" permet retrouver la tabulation et
                                    "params" est un dictionnaire qui sera chargé.
                                    Ex: [dict("name":"toto","params":
                                    {"name":"Arg1","type":"bool","value":"True"}),dict(...]
        Returns:
            None
        """
        for key,val in states.items():
            self.SetParamsValues(data=self.tab_dict[key].parameters,newSettings=val)

    @staticmethod
    def GetParamsValues(data):
        """
        Méthode permettant d'envoyer les données entrées par l'utilisateur dans le parametrerTree
        Args:
            data (PyQtgraph.Parameter): groupe de "paramètres" du parametrerTree
        Returns:
            list(dict): dictionnaire contenant les informations relatives à l'enregistrement
            (filtrage/modèles/etc...)
        """
        params_dict=dict()

        def recursive_search(parent_item):
            """
            Méthode permettant de récupérer l'ensemble des champs d'un parameter tree et de les
            renvoyer sous forme de liste (les champs dont la valeur est nulle sont ignorés)
            Arguments:
                    parent_item {str or tuple}  --  clés permettant de scrupter les
                                                    valeurs des champs correspondants
            Returns:
                    user_data {dict}   --   Dictionnaire contenant les informations nécessaire
                                            pour paramétrer l'objet HVAC
            """
            if isinstance(parent_item,tuple):
                if data.child(*parent_item).hasChildren():
                    for key in data.child(*parent_item).keys():
                        new_key=(*parent_item,key)
                        val=data.child(*new_key).value()
                        if val is not None:
                            params_dict[*new_key]=val
                        if data.child(*new_key).hasChildren():
                            recursive_search(new_key)
                else:
                    params_dict[parent_item]=data.child(parent_item).value()
            else:
                if data.child(parent_item).hasChildren():
                    for key in data.child(parent_item).keys():
                        if isinstance(parent_item,str):
                            new_key=(parent_item,key)
                        else:
                            new_key=(*parent_item,key)
                        val=data.child(*new_key).value()
                        if val is not None:
                            params_dict[*new_key]=val
                        if data.child(*new_key).hasChildren():
                            recursive_search(new_key)
                else:
                    params_dict[parent_item]=data.child(parent_item).value()
            return params_dict
        #le dictionnaire params_dict ajoute les (keys/values) à chaque recursive_search
        for val in data.keys():
            recursive_search(val)
        return params_dict

    @staticmethod
    def SetParamsValues(data,newSettings,default=True):
        """
        Méthode permettant d'envoyer les données entrées par l'utilisateur dans le parametrerTree
        Args:
            data        {PyQtgraph.Parameter} -- groupe de "paramètres" du parametrerTree
            newSettings {dict}                -- dictionnaire des nouvelles valeurs des paramètres
            default     {bool}                -- modifie également la valeur de défaut du paramètre
        Returns:
            list        {dict}           -- dictionnaire contenant les informations
                                            relatives à l'enregistrement (filtrage/modèles/etc...)
        """

        def SearchParam(parent_item):
            """
            Méthode permettant de retrouver le paramètre avec son nom pour
            lui affecter sa nouvelle valeur
            Arguments:
                    parent_item {str or tuple}  -- clés du champs à modifier
            """
            if isinstance(parent_item,tuple):
                data.child(*parent_item).setValue(newSettings[*parent_item])
                if default:
                    data.child(*parent_item).setDefault(newSettings[*parent_item])
            else:
                data.child(parent_item).setValue(newSettings[parent_item])
                if default:
                    data.child(parent_item).setDefault(newSettings[parent_item])
        #le dictionnaire params_dict ajoute les (keys/values) à chaque recursive_search
        for key in newSettings.keys():
            SearchParam(key)


class TextDialog(QDialog):
    """
    Classe héritant de QDialog, permettant d'avoir un utilitaire de mise en forme de texte
    """
    def __init__(self,text=None,font=None,color=None,*args,**kwargs):
        QDialog.__init__(self,*args,**kwargs)
        self.setWindowIcon(QtGui.QIcon('icon.ico'))
        #Load the UI Page
        loadUi(PATH/'TextWindow.ui', self)
        self.fontB.clicked.connect(self.fontChoice)
        self.colorB.clicked.connect(self.colorChoice)
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)
        self.setModal(True)

        #si font précisé, on le charge (tout cela est nécesaire car le chargement du code html
        #ne semble pas être compatible avec l'éditeur de font :
        #le taille du caractère n'est plus modifiable)
        if font is not None:
            self.textEdit.setFont(font)
        if color is not None:#si color précisé, on le charge
            self.textEdit.setTextColor(color)
            self.color=color
        if text is not None:#si text précisé, on le charge
            self.textEdit.setText(text)

    def fontChoice(self):
        """
        Méthode gérant la police du texte
        """
        
        initial_font = self.textEdit.currentFont()        
        font, valid =QFontDialog.getFont(initial_font)
        if valid:
            self.textEdit.setFont(font)

    def colorChoice(self):
        """
        Méthode gérant le choix de la couleur du texte
        """
        color =QColorDialog.getColor(self.textEdit.textColor())
        if color.isValid():
            self.textEdit.setTextColor(color)

    def getText(self):
        """Méthode retournant le texte en html, sa police et sa couleur

        Returns:
            _type_: _description_
        """

        return self.textEdit.toHtml(),self.textEdit.font(),self.textEdit.textColor()

    #en plus du html qui contient tout les éléments nécessaire, on envoie également le font
    #et la couleur afin de faciliter le renvoie de ces mêmes
    #information au prochaine chargement de la fenêtre


class ScaleDialog(QDialog):
    """
    Classe héritant de QDialog, permettant d'avoir un utilitaire récupérant les paramètres
    d'un repère orthonormé
    """

    def __init__(self,Xmin=None,Xmax=None,Ymin=None,Ymax=None,logX=None,logY=None,*args,**kwargs):

        QDialog.__init__(self,*args,**kwargs)
        self.setWindowIcon(QtGui.QIcon('icon.ico'))
        #Load the UI Page
        loadUi(PATH/'ScaleDialog.ui', self)
        if Xmin is not None:
            self.XminEdit.setText(str(Xmin))
        if Xmax is not None:
            self.XmaxEdit.setText(str(Xmax))
        if Ymin is not None:
            self.YminEdit.setText(str(Ymin))
        if Ymax is not None:
            self.YmaxEdit.setText(str(Ymax))
        if logX is not None:
            if logX:
                self.XAxisLog.setChecked(True)
        if logY is not None:
            if logY:
                self.YAxisLog.setChecked(True)

        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)
        #sélection le champ complet XminEdit lors de l'ouverture de la fenêtre ScaleDialog
        #(plus pratique pour réécrire directement la valeur souhaitée)
        self.XminEdit.selectAll()

    def getValues(self):
        """
        Méthode assurant la mise en forme des entrées de l'utilisateur
        Returns:
            {float,float,float,bool,bool} --    structure contenant les informations du repère
                                                orthonormé
        """
        #remplace le séparateur décimal par un point
        #(compatiblité avec le float, on pourrait modifier la variable global "locale"
        xmin=self.XminEdit.text().replace(',', '.')
        xmax=self.XmaxEdit.text().replace(',', '.')
        ymin=self.YminEdit.text().replace(',', '.')
        ymax=self.YmaxEdit.text().replace(',', '.')

        return (float(xmin),float(xmax),
                float(ymin),float(ymax),
                self.XAxisLog.isChecked(),self.YAxisLog.isChecked())
    #en plus du html qui contient tout les éléments nécessaire,
    #on envoie également le font et la couleur afin de faciliter le renvoie de ces mêmes
    #information au prochaine chargement de la fenêtre


class pgText(pg.TextItem):

    def __init__(self,text=None,*args,**kwargs):
        
        pg.TextItem.__init__(self,*args,**kwargs)
        #ItemIsMovable remplace la fonction MouseDragEvent
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsFocusable|
                        QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        if text is not None:
            self.setText(text)
        #flag ne permettant l'ouverture que d'une seule fenêtre par pgTextitem en même temps
        self.Onflag=False
        self.font=QtGui.QFont("Times", 8)
        self.color=kwargs.get("color",QtGui.QColor("black"))
        self.setZValue(10)

    def keyPressEvent(self, event):
        """
        Méthode dédié à l'apparition d'une entrée du clavier
        Args:
            event (QEvent): entrée clavier
        """

        if event.key() == QtCore.Qt.Key.Key_Delete | self.hasFocus():
            #//TODO : l'élément est caché pour l'instant (il devrait être
            #//TODO détruit mais je ne sais l'implémenter)
            self.hide()
        event.accept()

    def mousePressEvent(self,ev):
        """Méthode dédié à l'apparition d'un clic de la souris
        Args:
            event (QEvent): entrée clic souris
        """
        if ev.button() != QtCore.Qt.MouseButton.LeftButton :
            ev.ignore()
        else:
            ev.accept()

    def mouseDoubleClickEvent(self,ev):
        """
        Méthode dédié à l'apparition d'un double-clic de la souris
        Args:
            event (QEvent): entrée double-clic souris
        """
        if not self.Onflag: #si fenêtre déjà ouverte on sort de la fonction
            self.Onflag=True #mise à 1 du flag éditeur ouvert
            self.textEditor()
            self.Onflag=False #on est sorti de l'éditeur, mise à 0 du flag
        ev.accept()

    def textEditor(self):
        """
        Méthode gérant l'apparition de la fenêtre de modification du texte
        """
        if self.toPlainText() is not None:
            self.window=TextDialog(text=self.toPlainText(),font=self.font,color=self.color)
        else:
            self.window=TextDialog()
        self.window.show()
        #si OK est pressé dans la dialogBox, on récupère les données
        def updateText():
            html,self.font,self.color=self.window.getText()
            self.setHtml(html)
        self.window.accepted.connect(updateText)

    def addArrow(self):
        """
        #! A CODER
        Méthode gérant la création d'une flêche reliant le text à la courbe parent
        """
        g = pg.GraphItem()
        ## Define positions of nodes: 
        # 1er point = position x,y sur la courbe 
        # 2eme point = position x,y du texte
        pos = np.array([ [0,0], [10,0]])
        ## Define the set of connections in the graph
        adj = np.array([[0,1]])
            
        ## Define the symbol to use for each node (this is optional)


        ## Define the line style for each connection (this is optional)
        lines = (255,0,0,255)

        ## Update the graph
        g.setData(pos=pos, adj=adj, pen=lines, size=0,  pxMode=False)


            
    