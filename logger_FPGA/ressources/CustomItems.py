import json
from dataclasses import dataclass,field

from PyQt6.QtWidgets import  QTreeWidgetItem
from PyQt6 import QtGui,QtCore

import pyqtgraph as pg
import pyqtgraph.parametertree as ptree
import pyqtgraph.parametertree.parameterTypes as pTypes

from .CustomParameters import ChannelsSelection
from .CustomTypes import itemType,qSignalType




#dataclass contenant l'ensemble des caractéristiques nécessaires pour se connecter au FPGA via l'UDP
@dataclass
class FGPAconfigStruct():

    n_ana_channels          :   int         = field(default=1)
    channels_config         :   list[int]   = field(default_factory=lambda:[0])
    divider                 :   int         = field(default=2800)
    ip_fpga                 :   str         = field(default='172.16.0.1')
    target_port_fpga        :   int         = field(default=9)
    remote_port_fpga        :   int         = field(default=2064)
    local_ip                :   str         = field(default='172.16.0.2')
    local_port              :   int         = field(default=2064)
    timeout                 :   int         = field(default=2)
    trip                    :   int         = field(default='01000000')
    delay                   :   int         = field(default=0)
    type_trigger            :   int         = field(default=0)
    trigger_thres           :   int         = field(default=0)
    n_words                 :   int         = field(default=16384)



    def __post_init__(self,**kwargs):
        if kwargs is not None:
            for key, value in kwargs.items():
                if hasattr(self,key):
                    setattr(self, key, value)

        if (self.n_ana_channels != len(self.channels_config)) and self.n_ana_channels!=15 :
            raise ValueError("Le nombre de voies analogiques listées doit être égal au nombre de voies indiquées")
        if  self.n_ana_channels not in [1,2,4,8,15] or len(self.channels_config) not in [1,2,4,8] :
            raise ValueError("Le nombre de voies sélectionnées doit être de 1, 2, 4, ou 8 voies analogiques ou 15 voies logiques")
        if  self.divider <2 or self.divider>65535:
            raise ValueError("Le diviseur doit être défini entre 2 et 65535")

    def fromJson(self,json_file:str):

        with open(json_file, 'r') as fichier_parametres:
            # Charge le fichier JSON dans une variable config
            config = json.load(fichier_parametres)

            for key,item in config.items():
                if hasattr(self,key):
                    setattr(self,key,item)

    def fromParameters(self,parameters:pTypes.GroupParameter):

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
                if parameters.child(*parent_item).hasChildren():
                    for key in parameters.child(*parent_item).keys():
                        new_key=(*parent_item,key)
                        val=parameters.child(*new_key).value()
                        if val is not None:
                            params_dict[*new_key]=val
                        if parameters.child(*new_key).hasChildren():
                            recursive_search(new_key)
                else:
                    params_dict[parent_item]=parameters.child(parent_item).value()
            else:
                if parameters.child(parent_item).hasChildren():
                    for key in parameters.child(parent_item).keys():
                        if isinstance(parent_item,str):
                            new_key=(parent_item,key)
                        else:
                            new_key=(*parent_item,key)
                        val=parameters.child(*new_key).value()
                        if val is not None:
                            params_dict[*new_key]=val
                        if parameters.child(*new_key).hasChildren():
                            recursive_search(new_key)
                else:
                    params_dict[parent_item]=parameters.child(parent_item).value()
            return params_dict
        #le dictionnaire params_dict ajoute les (keys/values) à chaque recursive_search
        for val in parameters.keys():
            recursive_search(val)

        for key, value in params_dict.items():
            if hasattr(self,key):
                setattr(self, key, value)


    def __repr__(self):

        return '\n'.join([f'{key}: {item}' for key,item in self.__dict__.items()])


@dataclass
class StandardStruct():

    name         :   str
    file_id      :   list[int]
    item_type    :   itemType = field(init = False)
    _absolute_id :   int

#dataclass contenant l'ensemble des caractéristiques nécessaires d'une capture
@dataclass
class CaptureStruct(StandardStruct):

    address             :   str
    fpga_config         :   FGPAconfigStruct = field(init=False)
    ana_channel_names   :   list[str]        = field(default_factory=lambda:[f'ANA_CH{n}' for n in range(15)])
    digi_channel_names  :   list[str]        = field(default_factory=lambda:[f'DIGI_CH{n}' for n in range(15)])
    gains               :   float            = field(default_factory=lambda:[1]*15)
    offsets             :   float            = field(default_factory=lambda:[0]*15)
    n_frames            :   int              = field(default = 1000)


    def __post_init__(self):

        #self.name : str =self.adress[self.adress.rfind('/')+1:len(self.adress)-4]
        self.item_type=itemType.FILE
        self.fpga_config=FGPAconfigStruct()
        self.fromJson(self.address)

    def fromJson(self,target:str=None):

        with open(target, 'r') as fichier_parametres:
            # Charge le fichier JSON dans une variable config
            self.fpga_config.fromJson(target)
            config = json.load(fichier_parametres)

            for key,item in config.items():
                if hasattr(self,key):
                    print(f'setting Attribute {key}: {item}')
                    setattr(self,key,item)

    def ToJson(self,target:str):

        with open(target, 'w', encoding='utf-8') as f:

            for item in self.__dict__.items():
                json.dump(item)

@dataclass
class SignalStruct(StandardStruct):

    pen          :   QtGui.QPen
    color        :   QtGui.QColor = field(init=False)
    gain         :   float = field(init=False)
    offset       :   float = field(init=False)

    def __post_init__(self):
        self.item_type=itemType.RAW
        self.color=self.pen.color()

class MetaTreeItem(QTreeWidgetItem):
    """
    Classe générique héritant de QTreeWidgetItem.
    """

    def __init__(self,struct:StandardStruct | CaptureStruct | SignalStruct,
                 *args,**kwargs):

        #l'item aura une checkbox à trois états si aucun flag n'est passé
        self._highlited=False
        self._parentId=None
        self._oldState=QtCore.Qt.CheckState.Unchecked
        self.struct=struct
        QTreeWidgetItem.__init__(self)
        self.setFlags(self.flags() |QtCore.Qt.ItemFlag.ItemIsUserCheckable |
                                QtCore.Qt.ItemFlag.ItemIsAutoTristate)
        self.setText(0, self.struct.name)
        self.setData(0,10,QtCore.Qt.CheckState.Unchecked)
        #self.setCheckState(0,QtCore.Qt.CheckState.Unchecked)

    #*Propriétés*#
    @property
    def absoluteId(self):
        """
        Reçoit (si un argument est passé) ou retourne l'index absolu du TreeWidgetItem.
        Cet index est donné par la méthode gérant l'affichage dans le treewidget parent.
        Returns:
            _absoluteIndex {int} : index
        """
        return self.struct._absolute_id

    @absoluteId.setter
    def absoluteId(self,index):
        self.struct._absolute_id=index

    @property
    def type(self)->itemType:
        """
        Retourne le itemType TreeWidgetItem :
        Returns:
            {itemType} : type de l'objet, RAW signal brut, FILE fichier, MODIF signal obtenue par
                        en modifiant un signal brut et MODEL un signal d'un modèle mathématique
        """
        return self.struct.item_type

    @type.setter
    def type(self,Itype:itemType)->None:
        self.struct.item_type=Itype

    @property
    def state(self)->QtCore.Qt.CheckState:
        """
        Retourne l'état logique du TreeWidgetItem :
            ¤ QtCore.Qt.CheckState.Checked
            ¤ QtCore.Qt.CheckState.PartiallyChecked
            ¤ QtCore.Qt.CheckState.UnChecked
        Returns:
            {QtCore.Qt.CheckState} : état logique de l'item
        """
        return self.checkState(0)

    @property
    def parentId(self):
        return self._parentId

    @parentId.setter
    def parentId(self,id:int):
        self._parentId=id

    @property
    def file_id(self):
        return self.struct.file_id

    @file_id.setter
    def file_id(self,id:list[int]):
        self.struct.file_id=id

    @property
    def name(self):
        return self.struct.name

    @name.setter
    def name(self,name:str):
        self.struct.name=name
        self.setText(0, self.struct.name)

    #*Méthodes*#
    def setItemFont(self,bold:bool=False,brush:pg.mkBrush=None):
        """
        Méthode permettant de modifier les données graphiques d'un TreeWidgetItem
        Arguments:
                bold    {bool,optional}  -- Le texte est-il en gras
                                            Defaults to None
                brush   {pg.mkBrush}     -- Objet pyqtgraph.mkPen définissant
                                            l'aspect de la courbe
        Returns:
        """

        font=QtGui.QFont()
        font.setBold(bold)
        self.setData(0,6,font)

        if brush is not None:
            self.setData(0,8,brush)
            self.setData(1,8,brush)
            self.brush=brush

    def disableItem(self,state:bool=True):

        def recursivedisable(item,disable_status):
            """Méthode interne permettant de désactiver les éléments
            dépendant de cet objet.
            Return:
                None
            Args:
                item (TreeWidgetItem): item venant d'être sélectionné
            """
            for n in range (item.childCount()):
                current_item = item.child(n)
                current_item.setDisabled(disable_status)
                if current_item.childCount()>0 :
                    recursivedisable(current_item,disable_status)

        if state:
            self.setDisabled(True)
            self.setCheckState(0,QtCore.Qt.CheckState.Unchecked)
            self.setFlags(self.flags()& ~QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            if self.childCount()>0:
                recursivedisable(self,True)
        else:
            self.setDisabled(False)
            self.setCheckState(0,QtCore.Qt.CheckState.Unchecked)
            self.setFlags(self.flags()& QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            if self.childCount()>0:
                recursivedisable(self,False)

    def checkItem(self,state):
        """
        Super Méthode surchargée par toute classe héritant de l'objet CustomTreeItem
        """
        tree=self.treeWidget()
        tree.blockSignals(True)
        def recursivetoggle(item,check_status):
            """Méthode interne permettant de cocher/décocher les éléments
            dépendant de cet objet.
            Return:
                None
            Args:
                item (TreeWidgetItem): item venant d'être sélectionné
            """
            for n in range (item.childCount()):
                current_item = item.child(n)
                current_item.setCheckState(0,check_status)
                if current_item.childCount()>0 :
                    recursivetoggle(current_item,check_status)

        if not state :
            self.setCheckState(0,QtCore.Qt.CheckState.Unchecked)
            if self.childCount()>0:
                recursivetoggle(self,QtCore.Qt.CheckState.Unchecked)
        else:
            self.setCheckState(0,QtCore.Qt.CheckState.Checked)
            if self.childCount()>0:
                recursivetoggle(self,QtCore.Qt.CheckState.Checked)
        tree.blockSignals(False)

    def emitItemID(self,qsignal:qSignalType):
        """
        Méthode utilisant le signal "itemActivated" pour renvoyer cet objet à la méthode connectée
        """
        #! le signal qSignalType.Check ne marche pas car pas d'objet pouvant le déclencher
        #! (TreeWidgetItem n'hérite pas de QObjet)
        tree=self.treeWidget()
        if qsignal is qSignalType.CHECK:
            tree.itemActivated.emit(self,0)

        elif qsignal is qSignalType.SELECT:
            #on efface la sélection existante, on défini que l'item est sélectionné puis
            #on forece itemClicked afin que la méthode updateSelectionTree du MainController
            #soit appelée.
            tree.selectionModel().clear()
            self.setSelected(True)
            tree.itemClicked.emit(self,0)

    def generateCurve(self):
        """
        Super Méthode surchargée par toute classe héritant de l'objet CustomTreeItem
        """
        pass

    def getStructure(self):

        return self.struct

    def toggleCurve(self):
        """
        Super Méthode surchargée par toute classe héritant de l'objet CustomTreeItem
        """
        pass

    def saveParam(self):
        """
        Super Méthode surchargée par toute classe héritant de l'objet CustomTreeItem
        """
        pass

    def addItem(self,item):
        """
        Super Méthode surchargée par toute classe héritant de l'objet CustomTreeItem
        """
        self.addChild(item)

class CaptureTreeItem(MetaTreeItem):
    """
    TreeItem incorporant les interfaces et méthodes d'un capture File
    """
    def __init__(self,struct: CaptureStruct | StandardStruct,*args,**kwargs):

        MetaTreeItem.__init__(self,struct,*args,**kwargs)
        self.ItemType(1)#Item type différent d'un QTreeWidgetItem standard
        self.initParameters()

    def initParameters(self):

        """{'name':'Name','type':'str',
                                            'value':self.struct.name
                                            },
                                            ,
                    {
                        ChannelsSelection(
                                            name        = "Configure channels selection",
                                            listNames   = self.struct.ana_channel_names,
                                            quantity    = self.struct.fpga_config.n_ana_channels,
                                            idList      = self.struct.fpga_config.channels_config
                                        )
                    }
        """

        children=[
                    {'name':'Frames quantity',
                                        'type':'int',
                                        'value':self.struct.n_frames,
                                        'default':1000,
                                        'limits':[1,2000]},
                    {'name':'Frame number',
                                        'type':'int',
                                        'value':0,
                                        'default':-1,
                                        'limits':[-1,1000]},
                    {'name':'Diviseur',
                                        'type':'int',
                                        'value':self.struct.fpga_config.divider,
                                        "default":28,
                                        'limits':[2,65535],
                                        },
                    ChannelsSelection(  name = "Configure channels selection",
                                            listNames = self.struct.ana_channel_names,
                                            quantity = self.struct.fpga_config.n_ana_channels,
                                            idList = self.struct.fpga_config.channels_config
                                        )

                ]
        self.params=ptree.Parameter.create( name = 'Data Parameters',
                                            type = 'group',
                                            children = children)
        self.params.sigTreeStateChanged.connect(self.saveParam)
        self.params.param('Frame number').sigValueChanged.connect(self.MAJ_Maxnumber)

    def getParameters(self):

        return self.params

    def MAJ_Maxnumber(self):

        return self.params

    def saveParam(self):

        pass

class SignalTreeItem(MetaTreeItem):
    """
    TreeItem incorporant les interfaces et méthodes permettant de gérer l'affichage d'une courbe
    Args:
        CustomTreeItem (_type_): _description_
    """
    def __init__(self,struct: CaptureTreeItem,
                    *args,**kwargs):

        MetaTreeItem.__init__(self,struct,*args,**kwargs)
        self.ItemType(2)#Item type différent d'un QTreeWidgetItem standard
        self.curve=None
        self.InitParameters()

        if self.struct.color:
            self.setItemFont(False,brush=pg.mkBrush(color=self.struct.color))

    def InitParameters(self):
        #l'item garde les valeurs de création de l'item comme valeur par défauts
        children = [
                    {'name':'Signal name','type':'str',"value":self.name,'default':self.name},
                    {'name':'Curve pen', 'type':'pen', 'value':self.struct.pen,'expanded':False}
                    ]
        self.params=ptree.Parameter.create(name = 'Curve Parameters', type = 'group',
                                        children = children)
        self.params.sigTreeStateChanged.connect(self.saveParam)

    def getParameters(self):

        return self.params

    def generateCurve(self)->pg.PlotDataItem:
        """
        Méthode gérant la création et le paramétrage de l'objet graphique PlotDataItem curve
        """
        if not self.isDisabled():
            self.curve=pg.PlotDataItem(*self.signal_data(self.struct.file_id[1]),pen = self.struct.pen)
            self.curve.setCurveClickable(True)
            #NE PAS CHANGER ! Voir emitItemID
            self.curve.sigClicked.connect(lambda : self.emitItemID(qSignalType.SELECT))
            return self.curve
        else:
            return None

    def saveParam(self):
        self.name=self.params.child('Curve name').value()
        self.struct.pen=self.params.child('Curve pen').value()
        if self.curve is not None:
            self.curve.setPen(self.struct.pen)


