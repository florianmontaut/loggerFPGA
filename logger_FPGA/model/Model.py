"""
Méthode définissant la structure de données receuillant les informations nécessaires
au fonctionnement du GLViewer
"""
from collections import deque
import pandas as pd
import numpy as np

from scipy import signal
from scipy.optimize import curve_fit

from PyQt6.QtCore import QObject,pyqtSignal,Qt
from PyQt6.QtWidgets import QTreeWidgetItem
#import pyqtgraph.parametertree.parameterTypes as pTypes
import pyqtgraph.parametertree as ptree
import pyqtgraph as pg

from ressources.CustomParameters import ComplementaryElements
import ressources.modelFunctions as mf
import ressources.CustomItems as CI
from ressources.CustomFunctions import getJSONConfig

#['#08F7FE', '#FE53BB', '#F5D300', '#00ff41', '#FF0000', '#9467bd', ]
class signal():
    """
    L'objet signal contient l'ensemble des données faisant référence à une voie de mesure donnée
    => valeur du signal (sur n_trames),
    """
    n_colors = 20

    def __init__(self, struct : CI.SignalStruct) -> None:

        #colormap découpée en n_colors
        self.colormap = pg.colormap.getFromMatplotlib('tab20')#mpl.colormaps['Dark2'])
        self.colors = self.colormap.getLookupTable(0,1,self.n_colors)
        #+ 4 styles de pinceaux, soit 4*n_colors combinaisons
        self.penStyle = [Qt.PenStyle.SolidLine,
                        Qt.PenStyle.DashLine,
                        Qt.PenStyle.DotLine,
                        Qt.PenStyle.DashDotLine]
        self.models_param = ""
        self.plotCurve=pg.PlotDataItem()

    def getTreeItem(self):

        return CI.SignalTreeItem(struct=self.file_params)

    def getDefaultPen(self,index):
        """Méthode retournant le pinceau (couleur + type de trace) par défaut du signal
        Args:
            index {int}       -- index de la courbe
        Returns:
            {pyqtGraph.mkPen} -- pinceau de type pg.mkPen
        """

        if index >= self.n_colors:
            id_style = index//self.n_colors
            id_color = index%20
        else:
            id_style = 0
            id_color = index

        return pg.mkPen(color = self.colors[id_color],style = self.penStyle[id_style])

    def getYValues(self,index:int):
        """
        Méthode ne retourant que toutes les valeur en ordonnées des signaux passés par index.
        Args:
            index (int): index des channels devant être récupérés
        Returns:
            pandas.dataframe: données
        """

        if index>=self.n_samples:
            return None
        else:
            try:
                return self.data.iloc[index,:]
            except:
                print(f'{self.name} getYValues(): {index} / {self.n_samples}')

    def subscribe_update_func(self, func):
        if func not in self._update_funcs:
            self._update_funcs.append(func)

    def update(self,settings:dict):
        """
        Méthode permettant de mettre à jour l'ensemble des paramètres passés dans settings
        Args:
            settings {dict}  -- dictionnaire contenant le nom des paramètres à mettre à jour et
                                leur valeur.
        """
        for key,value in settings.items():
            print(key,value)
            setattr(self,key,value)

    def saveToJSONConfig(self)->str:
        """
        Méthode permettant de sauvegarder les paramètres de l'objet CSVStructure
        dans un fichier de config au format .JSON
        Returns:
            str: fichier JSON contenant les données de l'objet
        """

        exported_params = ['adress','operations']
        CSVsettings = {k: v for k, v in self.__dict__.items() if k in exported_params }

        return CSVsettings

#l'objet Capture contient l'ensemble des données générées/chargées dans le script. C'est un conteneur
#d'un seule capture, i.e 1 seule connection au FPGA. Cette connexion

class Capture(object):

    n_colors = 20
    def __init__(self, capture_config:CI.CaptureStruct) -> None:

        self.struct=capture_config
        #self.capture_item=CI.CaptureTreeItem(self)
        self.current_frame=-1
        self.current_ch_config=[] #configuration actuelle des voies de l'affichage temps réel
        self.current_trig_config=[] #configuration actuelle du trigger de l'affichage temps réel
        self.data=[[]*1000]

            #colormap découpée en n_colors
        self.colormap = pg.colormap.getFromMatplotlib('tab20')#mpl.colormaps['Dark2'])
        self.colors = self.colormap.getLookupTable(0,1,self.n_colors)
        #+ 4 styles de pinceaux, soit 4*n_colors combinaisons
        self.penStyle = [Qt.PenStyle.SolidLine,
                        Qt.PenStyle.DashLine,
                        Qt.PenStyle.DotLine,
                        Qt.PenStyle.DashDotLine]
        self.models_param = ""
        self.plotCurve=pg.PlotDataItem()

    @property
    def FPGA_config(self):
        return self.struct.fpga_config

    @property
    def names_table(self):
        return self.struct.ana_channel_names

    @property
    def gain_table(self):
        return self.struct.gains

    @property
    def offset_table(self):
        return self.struct.offsets

    def getTreeItem(self):

        return CI.CaptureTreeItem(struct=self.struct)
    
    def append(self,buffer):
        
        self.data

    def getDefaultPen(self,index):
        """Méthode retournant le pinceau (couleur + type de trace) par défaut du signal
        Args:
            index {int}       -- index de la courbe
        Returns:
            {pyqtGraph.mkPen} -- pinceau de type pg.mkPen
        """

        if index >= self.n_colors:
            id_style = index//self.n_colors
            id_color = index%20
        else:
            id_style = 0
            id_color = index

        return pg.mkPen(color = self.colors[id_color],style = self.penStyle[id_style])







#l'objet model contient l'ensemble des données générées/chargées dans le script. C'est un conteneur
#des différentes captures, i.e connexion au FPGA
class Model(QObject):

    MAJ_curves=pyqtSignal(QTreeWidgetItem)
    MAJ_files=pyqtSignal(CI.CaptureTreeItem)
    MAJ_signal=pyqtSignal(CI.SignalTreeItem)
    MAJ_options=pyqtSignal(dict)

    def __init__(self,captures:list[Capture]=None,session_settings=None):

        super(Model,self).__init__()

        if captures is not None:

            for capture in captures:
                self.newFile(capture)

        else :
            self.captures = []


        self._update_funcs = []
        #affection treefile au type QTreeWidget afin de bénificier de l'autocomplétion
        self.qitems_dict = {}
        self.cpt_id = 0
        self.settings = {} if session_settings is not None else session_settings

    def getFileAttribute(self,id_file,attribute,**kwargs):
        """
        Méthode facilitant l'accés au données des fichiers CSV
        Args:
            id_file (int): id du fichier GL
            attribute (str): str de l'attribut à récupérer
            kwargs () : données supplémentaires pouvant être nécessaire à certains attributs
        Returns:
            _type_: _description_
        """
        if 'index' in kwargs:
            return getattr(self.waveforms[id_file],attribute)(kwargs['index'])
        else:
            return getattr(self.waveforms[id_file],attribute)

    def sortTableQitems(self,tab)->list:
        """
        Méthode interne renvoyant une liste des items sélectionnés groupés en listes
        en fonction de leur fichier d'origine
        Arguments:
            tab (list(QTreeWidgetItems)): items sélectionnés
        Returns:
            list:   structure contenant les listes des ids des signaux et de leur
                    nom groupés par fichier d'origine
        """
        #tri les id en fonction de l'id du fichier, chaque élément de sorted_id est composé
        #d'un tuple (id,Qitem) càd l'id et nom du signal
        sorted_id=sorted([(item.file_id,item) for item in tab],
                            key = lambda x: x[0][0])
        #création d'une liste de n listes (n étant le nombre de fichiers
        #chargés, i.e le nombre de GL_files
        tab = [[] for _ in range(len(self.gl_files))]
        #on charge le ieme élément du tableau avec les ids ayant id[0]==i,
        #val[0]=(i le number,signal number)
        [tab[val[0][0]].append(val[1]) for val in sorted_id]
        return [id_list for id_list in tab if id_list] #on retire toutes les listes id vides

    def newFile(self,capture:Capture):
        """_summary_
        Args:
            file (CsvFile): _description_
        """
        #stockage de l'objet capture
        self.captures.append(capture)

        #récupération du TreeItem correspondant <=> un peu boublon ?
        root=self.captures[-1].getTreeItem()
        #MAJ des compteurs d'items
        self.appendItemsDict(root,None)
        #id de la racine (la racine d'un signal est une capture)
        root_num=root.file_id[0]

        #Pour noms de signals de l'objet capture on créer un item dans le treeWidget
        for n,channel in enumerate(capture.names_table):
            itemStruct=CI.SignalStruct(
                            name=channel,
                            file_id=[root_num,n],
                            _absolute_id=self.cpt_id,
                            pen=self.captures[root_num].getDefaultPen(n))
            #utilisation de la fonction générique lambda comme pointeur afin de
            #stocker de données inutile.
            #! remplacer la fonction trançant la fonction par un signal/slot: => envoi d'un signal au changement d'état
            #! de la case du signal => envoi du numéro du signal au viewer qui charge le graph correspondant correspondant
            child=CI.SignalTreeItem(struct=itemStruct)
            self.appendItemsDict(item=child,parent=root)
        #return root car ImportController utilise la racine pour peupler le tableau
        self.MAJ_files.emit(root)

    def appendItemsDict(self,item,parent=None):
        """_summary_
        Args:
            file (CsvFile): _description_
        """

        if parent is not None:
            item.parentId=parent.absoluteId
        else:
            item.parentId=0
        self.qitems_dict[self.cpt_id]=item
        self.cpt_id+=1

    def changeSettings(self,settings):

        self.settings = settings
        self.MAJ_options.emit(settings)

    def saveItem(self,id,item):
        self.qitems_dict[id]=item



