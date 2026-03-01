import json
import pathlib
from dataclasses import dataclass,field

from PyQt6.QtWidgets import  QTreeWidgetItem
from PyQt6 import QtGui,QtCore

import pyqtgraph as pg
import pyqtgraph.parametertree as ptree
import pyqtgraph.parametertree.parameterTypes as pTypes

PATH=pathlib.Path(__file__).parent




#dataclass contenant l'ensemble des caractéristiques nécessaires pour se connecter au FPGA via l'UDP
@dataclass
class FGPAconfigStruct():

    n_ana_channels          :   int         = field(default=1)
    channels_config         :   list[int]   = field(default_factory=lambda:[0])
    divider                 :   int         = field(default=28)
    ip_fpga                 :   str         = field(default='172.16.0.1')
    target_port_fpga        :   int         = field(default=9)
    remote_port_fpga        :   int         = field(default=2064)
    local_ip                :   str         = field(default='172.16.0.2')
    local_port              :   int         = field(default=2064)
    timeout                 :   int         = field(default=2)
    trip                    :   str         = field(default='0x01000000')
    delay                   :   int         = field(default=0)
    type_trigger            :   int         = field(default=0)
    trigger_thres           :   int         = field(default=0)
    n_words                 :   int         = field(default=16384)



    def __post_init__(self):

        if (self.n_ana_channels != len(self.channels_config)) and self.n_ana_channels!=15 :
            raise ValueError("Le nombre de voies analogiques listées doit être égal au nombre de voies indiquées")
        if  self.n_ana_channels not in [1,2,4,8,15] or len(self.channels_config) not in [1,2,4,8] :
            raise ValueError("Le nombre de voies sélectionnées doit être de 1, 2, 4, ou 8 voies analogiques ou 15 voies logiques")
        if  self.divider <2 or self.divider>65535:
            raise ValueError("Le diviseur doit être défini entre 2 et 65535")
        
    def __repr__(self):
        
        return '\n'.join([f'{key}: {item}' for key,item in self.__dict__.items()])


    def fromJson(self,json_file:str):
        
        with open(PATH/json_file, 'r') as fichier_parametres:
            # Charge le fichier JSON dans une variable config
            config = json.load(fichier_parametres)

            for key,item in config.items():
                if hasattr(self,key):
                    setattr(self,key,item)



if __name__ == '__main__':
    test=FGPAconfigStruct()
    test.fromJson(json_file='parametres_scope.json')
    print(test)
