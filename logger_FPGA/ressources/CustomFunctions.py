import pandas as pd
import json


from PyQt6 import QtCore,QtGui
from PyQt6.QtWidgets import QTreeWidget,QTreeWidgetItem,QMessageBox,QTreeWidgetItemIterator

import pyqtgraph as pg
from .CustomTypes import degree,itemType



def setItemFont(tree_item:QTreeWidgetItem,bold:bool=None,brush:pg.mkBrush=None):
    """
    Fontion permettant de modifier les données graphiques d'un PlotDataItem
    Arguments:
            line_item  {PlotDataItem}    -- Courbe à modifier
    Returns:
            pen     {pg.mkPen}           -- Objet pyqtgraph.mkPen définissant l'aspect de la courbe
    """
    if bold is not None:
        font=QtGui.QFont()
        font.setBold(bold)
        tree_item.setData(0,6,font)
    if brush is not None:
        tree_item.setData(0,8,brush)
        tree_item.setData(1,8,brush)

def updateCurve(curve:pg.PlotDataItem,width:int=None,
                z_val:int=None,color:QtCore.Qt.GlobalColor=None):
    """
    Fontion permettant de modifier les données graphiques d'un PlotDataItem
    Arguments:
            curve      {PlotDataItem}       --  Courbe à modifier
            width       {int}               --  Nouvelle épaisseur du tracé courbe
            z_val        {int}              --  Position en Z de la courbe (plus Z est élevé
                                                plus la courbe est mise en avant)
            color       {Qt.GlobalColor}    --  Nouvelle couleur de la courbe
    Returns:
            pen     {pg.mkPen}              --  Objet pyqtgraph.mkPen définissant
                                                l'aspect de la courbe
    """
    pen = curve.opts['pen']
    if not width:
        pen.setWidth(1)
    else:
        pen.setWidth(width)
    if not z_val:
        curve.setZValue(0)
    else:
        curve.setZValue(z_val)
    if color:
        pen.setColor(color)
    curve.setPen(pen)

def export_selected(tittle:str,df:pd.DataFrame,selec:list,export_seperator=0):
    """
        Fontion permettant d'exporter les fichiers ou signaux sélectionnés
        Arguments:
                tittle  {str}          -- Tittle of the export .csv file
                df  {pandas.DataFrame} -- DataFrame contenant les données à exporter
                selec {list(int)}      -- List d'entiers (int) index des colonnes à
                                        exporter\
                format_exp {int}       -- clé permettant de définir les séparateurs:
                                            \n\t 0 : format français (';' , ',')
                                            \n\t 1 : format US (',' , '.')
        Returns:
                None   -- MAJ des données traitées
    """
    format_seperator={0:(';',','),1:(';',',')} # dictionnaire
    #index_signals=[int(id) for id in files_tree2.selection()]
    df.to_csv(f"Filtered_file_{tittle}.csv",
                columns=[df.columns[selec]],
                sep=format_seperator[0][export_seperator],
                decimal=format_seperator[1][export_seperator])
    #filtered_signals.to_excel("export.xlsx",index=False)

def convert_temp(data:pd.DataFrame,new_scale:degree=degree.CELSIUS):
    """
        Fontion de convertion °C vers °F et inversement
    """
    if new_scale is degree.CELSIUS:
        return (data-32)/(5/9)
    elif new_scale is degree.FARENHEIT:
        return data*(9/5)+32


def warning(widget,text:str,title:str='"Error : bad reference"',exception=None):
    if not exception :
        dlg = QMessageBox(widget)
        dlg.setWindowTitle(title)
        dlg.setText(text)
        dlg.show()
    else:
        dlg = QMessageBox(widget)
        dlg.setWindowTitle(f"Unexpected {exception}")
        dlg.setText(text)
        dlg.show()

def mysplit(string:str)->float:
    """
    Fontion permettant de convertir le "sample" obtenu dans les fichiers GL:
    exemple 500ms devient 0.5

    Arguments:
            string {str}   -- string devant être convertie
    Raise:
            MAJ statusbars
    Returns:
            float     -- valeur convertie et rendue exploitable
    """
    unit = string.strip('0123456789')
    value = float(string.replace(unit,''))
    def convert_SI(val, unit_in):
        SI = {'µs':10**-6, 'ms':10**-3, 's':1.0, 'm':60}
        return val*SI[unit_in]
    try:
        return convert_SI(value,unit)
    except:
        #self.statusbar.showMessage("échec conversion de l'échantillonage:
        #utilisation valeur par défaut 1s") => Fontion ssi pas de self
        raise ValueError

def search(tree:QTreeWidget,term:str)->list[QTreeWidget]:
    """
    Sélectionne les items dont le nom contient les lettres, mots recherchés.
    Arguments:
            tree {QTreeWidget}  -- Arborescence devant être examinée
            term {str}          -- Mots ou lettres recherchés
    Returns:
            None                -- Sélection des items repondant à la recherche
    """
    if isinstance(term,str):
        text=term.strip()
        if not text:
            #si text vide => on quitte la Fontion search
            return
    else:
        return
    output=[]
    matchlist = tree.findItems(text,QtCore.Qt.MatchFlag.MatchContains |
                                QtCore.Qt.MatchFlag.MatchRecursive, 0)
    if matchlist:
        for item in matchlist:
            if not item.flags()& QtCore.Qt.ItemFlag.ItemIsAutoTristate:
                item.setSelected(True)
                output.append(item)
    return output

def getItems(tree:QTreeWidget,item:QTreeWidgetItem=None,
            type_methode:str='selected') -> list[QTreeWidgetItem]:
    """
    Retourne une liste de listes d'indices des différents signaux répondant aux paramètres
    recherchés. Fontion à privilégier pour le traitement des données.
    Arguments:
        tree {QTreeWidget} --  Arborescence (TreeWidget) devant être examiner
        type_methode {str} --  Configuration des paramètres de recherche: 'selected' recherche
                                des éléments sélectionnés ; 'checked' recherches des élements
                                cochés sans enfant
    Return:
        it_list {list{QTreeWidgetItems} -- Liste des items répondant à la recherche
    """
    #utilisation d'un dictionnaire afin de simplifier l'appel de la Fontion
    dict_methode={'selected':QTreeWidgetItemIterator.IteratorFlag.Selected|
                    QTreeWidgetItemIterator.IteratorFlag.Enabled|
                    QTreeWidgetItemIterator.IteratorFlag.NoChildren,
                'checked':QTreeWidgetItemIterator.IteratorFlag.Checked|
                        QTreeWidgetItemIterator.IteratorFlag.Enabled|
                        QTreeWidgetItemIterator.IteratorFlag.NoChildren,
                "children":QTreeWidgetItemIterator.IteratorFlag.Enabled|
                        QTreeWidgetItemIterator.IteratorFlag.NoChildren}
    it_list=[]
    if item is None:
        it_tree=QTreeWidgetItemIterator(tree,flags=dict_methode[type_methode])
    else:
        it_tree=QTreeWidgetItemIterator(item,flags=dict_methode[type_methode])

    while it_tree.value():
        current_item=it_tree.value()
        #on ne passe que les items qui ne sont pas tristate (True,False,PartialTrue)
        if current_item.type is not itemType.FILE:
            it_list.append(current_item)
        it_tree+=1
    print(it_list)
    return it_list

def isolateItems(tree,q_items:list):
    """
    Méthode permettant de cocher uniquement le(s) élément(s) sélectionné(s)
    Arguments:
            tree   {QTreeWidget}           --   Arborescence (TreeWidget) devant être examiner
            QItems {list[QTreeWidgetItem]} --   Si None la fonction récupère la
                                                sélection actuelle dans le treefile
    Returns:
            None   --
    """

    try:
        it_tree=QTreeWidgetItemIterator(tree)
        table_item=[]
        while it_tree.value():
            table_item.append(it_tree.value())
            it_tree+=1
        for item in table_item:
            if item in q_items:
                item.setCheckState(0, QtCore.Qt.CheckState.Checked)
            else:
                item.setCheckState(0, QtCore.Qt.CheckState.Unchecked)
    except:
        pass

def getJSONConfig(JSON_file)->dict:
    """
    Méthode permettant de convertir un fichier de config d'un objet CSVStructure
    vers un dictionnaire exploitable par GLviewer
    Args:
        JSON_file (str): fichier JSON stockant les données d'un enregistrement
    Returns:
        dict: dictionnaire contenant les informations relatives à l'enregistrement
        (filtrage/modèles/etc...)
    """
    CSV_params = []
    with open(JSON_file, 'r') as fichier_parametres:
    # Charge le fichier JSON dans une variable config
        config  =  json.load(fichier_parametres)
    for element in config:
        CSV_params.append(element)
    def convertToPyKeyWords(rawInput):
        """
        Méthode assurant la convertion des mots clés JSON en mots clés python
        Args:
            rawInput (_type_): _description_
        Returns:
            dict: dictionnaire nom/valeurs récupérer du parameterTree
        """
        #TODO:Ne prend pas en compte les limitations infinies du type [0,None] (i.e [0,+inf])
        #TODO Il faudrait vérifier que None ne soit pas présent dès que l'option limit
        #TODO est utilisée...
        KeyWords = {"False":False,
                    "false":False,
                    "True":True,
                    "true":True,
                    "None":None,
                    "Null":None,
                    "null":None}
        def recursiveConversion(raw):
            """Conversion récursive
            Args:
                raw (_type_): _description_
            Returns:
                _type_: _description_
            """
            out = []
            for element in raw:
                newParam = {}
                for key,val in element.items():
                    if key=='children':
                        newParam[key] = [recursiveConversion(element[key])]
                    elif isinstance(val,str):
                        if val in KeyWords.keys():
                            newParam[key] = KeyWords[val]
                        else:
                            newParam[key] = val
                    else:
                        newParam[key] = val
                out.append(newParam)
            return out
        return recursiveConversion(rawInput)
    def convertToDict(input_list):
        """
        Méthode interne assurant la conversion de liste à dictionnaire
        Args:
            input_list {list}: liste des paramètres et leur valeurs
        Returns:
            dict: dictionnaire name/valeur extrait du parameterTree
        """
        result = {}
        for element in input_list:
            result.update(element.items())
        return result
    return convertToDict(convertToPyKeyWords(CSV_params))