"""
Module dédié aux paramètres complexes personnalisés pouvant servir pour différents projets:
    ¤La classe curveModelizer gère l'affichage de l'utilitaire de modélisation
    ¤La classe curveModelItem gère l'affichage et les stockages des paramètres d'un model
    ¤La classe complementaryElements gère la création de deux champs de float complémentaire
    ¤La classe linkedCursors gère intégralement une paire de curseur pouvant être chargé dans un
    PlotWidget

"""
import numpy as np
from PyQt6 import QtGui,QtWidgets,QtCore


import pyqtgraph as pg
import pyqtgraph.parametertree.parameterTypes as pTypes

import ressources.modelFunctions as mf
from .CustomTypes import modelType

class CurveModelizer(pTypes.GroupParameter):

    model_keys = mf.model.keys()

    def __init__(self,n_max=6, **opts):
        if "keys" in opts:
            self.model_keys.extend(opts.pop('keys'))
        if "curveType" in opts:
            if opts.pop('curveType')=='Thermal':
                self.model_keys=mf.model_thermique.keys()

        pTypes.GroupParameter.__init__(self, **opts)
        params=[
                {'name':'Create model','type':'action'},
                {'name':'Model function','type':"list",'limits':self.model_keys},
                {'name':'Polynomial Degree', 'type': 'int',
                    'limits':[1, n_max], 'value': 3,'visible':False},
                {'name':'Show modeling curve','type':"bool", 'value':True},
                {'name':'Use vertical cursors as limits','type':"bool", 'value':True}
                ]

        self.addChildren(params)
        self.function = self.param('Model function')
        self.polyDegree = self.param('Polynomial Degree')
        self.createModel =self.param('Create model')
        self.function.sigValueChanged.connect(self.functionCheck)

    def functionCheck(self):
        """
        Méthode gérant l'affiche du paramètre "Polynomial Degree"
        """
        if self.function.value() == 'polynomial':
            self.polyDegree.setOpts(visible=True)
        else:
            self.polyDegree.setOpts(visible=False)

    def getFunction(self):
        """
        Méthode retournant la valeur du paramètre function, càd "Model function type"
        """
        return self.function.value()

class CurveModelItem(pTypes.GroupParameter):
    """
    Classe héritant de pyqtgraph.parametertree.parameterTypes. Cette classe regroupe
    la structure de donnéee, la saisie des données et l'affichage des ces dernières

    Args:
        pTypes (_type_): _description_

    Returns:
        _type_: _description_
    """

    model_keys = mf.model.keys()
    def __init__(self,infos,**opts):

        pTypes.GroupParameter.__init__(self, **opts)
        listCoef=[np.format_float_scientific(val, unique=False, precision=5)
                    for val in infos.modelCoef]

        coefStr=''.join(['\t'.join(listCoef)])

        params=[
                {'name':'Model function','type':"str", 'value': infos.modelFunc,
                    'readonly':True},
                {'name':'Polynomial Degree', 'type': 'int','value': infos.polyDeg,
                    'visible':False,'readonly':True},
                {'name':'Model coefficients','type':'text','value':coefStr},
                {'name':'Copy coeff','type':'action'}
                ]

        self.addChildren(params)
        self.param('Copy coeff').sigActivated.connect(lambda: self.exportCoeff())

    def exportCoeff(self,separateur='\t'):
        """
        Méthode gérant l'export des données sous la forme d'une liste de str
        Args:
            separateur (str, optional): séparateur de la liste devant être exportés.
                                        Defaults to '\t'.
        Returns:
            result {list(str)}: liste des coefficients utilisant le séparateur passé
                                en argument
        """
        text=self.param('Model coefficients').value()
        QtWidgets.QApplication.clipboard().setText(text)

class ChannelsSelection(pTypes.GroupParameter):

    def __init__(   self,
                    listNames   : list[str] = ['test'],
                    quantity    : int = 1,
                    idList      : list[int] = [0],
                    **opts):

        pTypes.GroupParameter.__init__(self, **opts)
        self.selectionInitital=[]
        self.listNames=listNames
        params=[
                    {   'name'      : 'Channels quantity',
                        'type'      : 'list',
                        'value'     : 1,
                        'values'    : [1,2,4,8,15]
                    },
                    {
                        'name'      : 'Channel n°1',
                        'type'      : 'list',
                        'value'     : self.listNames[0],
                        'values'    : self.listNames,
                        'enabled'   : False
                    }
                ]
        self.addChildren(params)

        for n in range(2,9):
            Channelname=f'Channel n°{n}'
            self.addChild({
                            'name'      : Channelname,
                            'type'      : 'list',
                            'value'     : self.listNames[n-2],
                            'values'    : self.listNames,
                            'default'   : self.listNames[n-2],
                            'enabled'   : False,
                            'visible'   : False
                        })

        self.param('Channels quantity').sigValueChanged.connect(self.updateChannels)
        self.InitChannelsSelection(quantity,idList)


    def InitChannelsSelection(self,quantity=1,idList=[1]):

        self.param('Channels quantity').setValue(   quantity,
                                                    blockSignal = self.updateChannels)
        for n,id in enumerate(idList,start=1):
            print(f'Ligne 154: {id} {self.listNames[id]}')
            key = f'Channel n°{n}'
            self.param(key).setValue(self.listNames[id])
            self.param(key).setDefault(self.listNames[id])
            self.param(key).setOpts(enabled=True)


    def updateChannels(self,param):

        val=param.value()
        if val==15:
            for n in range(1,9):
                key=f'Channel n°{n}'
                self.param(key).setOpts(enabled=False)
                self.param(key).setOpts(visible=False)
        else:
            self.param('Channels quantity').setOpts(enable=True)
            
            
            for n in range(1,9):
                key=f'Channel n°{n}'
                if n<=val:
                    self.param(key).setOpts(enabled=True)
                    self.param(key).setOpts(visible=True)
                else:
                    self.param(key).setOpts(enabled=False)
                    self.param(key).setOpts(visible=False)
                    

    def getSelection(self):

        out=[]
        for n in range(1,9):
            key=f'Channel n°{n}'
            out.append(self.param(key).value())
        return

    def getFunction(self):
        """
        Méthode retournant la valeur du paramètre function, càd "Model function type"
        """
        pass


class ComplementaryElements(pTypes.GroupParameter):
    """
    Classe héritant de pyqtgraph.parametertree.parameterTypes. Permet de rapidement créer
    des paramètres complémentaires du type A+B=cste.
    """

    def __init__(self,start=0,stop=10000, **opts):

        pTypes.GroupParameter.__init__(self, **opts)
        default_start=opts.get('df_start',start)
        default_stop=opts.get('df_stop',stop)

        self.addChild({ 'name': 'start',
                        'type': 'int',
                        'limits':[0, stop-1],
                        'value': start,
                        'default':default_start})
        self.addChild({ 'name': 'stop',
                        'type': 'int',
                        'limits':[1, default_stop],
                        'value': stop,
                        'default':default_stop})

        self.a = self.param('start')
        self.b = self.param('stop')
        self.a.sigValueChanged.connect(self.aChanged)
        self.b.sigValueChanged.connect(self.bChanged)

    def aChanged(self):
        """
        Méthode gérant la mise à jour du champ "start"
        """
        if self.a.value() >=self.b.value():
            self.a.setValue(self.b.value()-1, blockSignal=self.aChanged)
            
    def bChanged(self):
        """
        Méthode gérant la mise à jour du champ "stop"
        """
        if self.b.value()<=self.a.value():
            self.b.setValue(self.a.value()+1, blockSignal=self.bChanged)

class LinkedCursors(pTypes.GroupParameter):
    """
    Classe héritant de pyqtgraph.parametertree.parameterTypes. Permet de rapidement créer
    des curseurs graphiques dont la valeur est renvoyée dans un parameterTreeItem
    """
    def __init__(self,graphWidget, **opts):

        opts['expanded']=False
        self.linkedojects=[]
        self.cursors=[]
        self.arrows=[]
        self.oldState=[0,0]
        self.graph=graphWidget

        for i,value in enumerate(opts['cursors_setting']['pos']):
            self.cursors.append(pg.InfiniteLine(angle=opts['cursors_setting']['angle'],
                                    movable=True,
                                    pos=value,
                                    pen=opts['cursors_setting']['pen'],
                                    label=opts['cursors_setting']['label'],
                                    labelOpts=opts['cursors_setting']['labelOpts']))
            if opts['cursors_setting']['angle']==90:
                angle=0+180*i
            else:
                angle=90+180*i
            self.arrows.append(pg.ArrowItem(angle=angle,
                                            tipAngle=30,
                                            baseAngle=00,
                                            headLen=10,
                                            tailLen=50,
                                            pos=(value,50)))

        #passages des options à la classe parent GroupParameter
        pTypes.GroupParameter.__init__(self, **opts)

        #création des paramètres :
        if opts['name']=="Vertical cursors":
            values=[self.cursors[0].pos().x(),self.cursors[1].pos().x()]
        else:
            values=[self.cursors[0].pos().y(),self.cursors[1].pos().y()]

        params=[
                    {'name':'show cursors', 'type': 'bool','value':False},
                    {'name':'show delta on graph','type':'bool','value':False},
                    {'name':'cursor 1', 'type': 'float','value':values[0]},
                    {'name':'cursor 2', 'type': 'float','value':values[1]},
                    {'name':'delta','type': 'float','value':values[1]-values[0],'readonly': True}
                ]
        self.addChildren(params)

        #création des paramètres :
        self.newLinkedObjects(field=self.param('cursor 1'),item=self.cursors[0])
        self.newLinkedObjects(field=self.param('cursor 2'),item=self.cursors[1])
        self.sigTreeStateChanged.connect(self.updateGraph)


    def cursorsState(self,state):
        """
        Méthode permettant d'ajouter ou retirer les curseurs
        Args:
            state {bool} -- état logique du paramètre "Show Cursors"
        """
        if state:
            #on recharge les droites représentant le curseur
            self.graph.addItem(self.cursors[0], ignoreBounds=True)
            self.graph.addItem(self.cursors[1], ignoreBounds=True)
        else:
            #on recharge les droites représentant le curseur
            self.graph.removeItem(self.cursors[0])
            self.graph.removeItem(self.cursors[1])

    def arrowsState(self,state):
        """
        Méthode permettant d'ajouter ou retirer les flèches
        Args:
            state {bool} -- état logique du paramètre "Show delta"
        """
        if state:
            #on recharge les droites représentant le curseur
            self.graph.addItem(self.arrows[0], ignoreBounds=True)
            self.graph.addItem(self.arrows[1], ignoreBounds=True)
        else:
            #on recharge les droites représentant le curseur
            self.graph.removeItem(self.arrows[0])
            self.graph.removeItem(self.arrows[1])


    def updateGraph(self,changes):
        """Méthode permettant d'afficher ou non les curseurs en fonction de l'état
        logique du parameterTreeItem associé

        Args:
            field (parameterItem): paramaterItem lié à l'une des coordonnées de l'objet graphique
            item (GraphicsObject): objet graphique lié
        """
        if changes['show cursors']!=self.oldState[0]:
            self.oldState[0]=changes['show cursors']
            self.cursorsState(self.param('show cursors').value())
        elif changes['show delta on graph']!=self.oldState[1]:
            self.arrowsState(self.param('show delta on graph').value())


    def updateDelta(self):
        """
        Méthode permettant de calculer le delta entre deux curseurs
        Args:
            field (parameterItem): paramaterItem lié à l'une des coordonnées de l'objet graphique
            item (GraphicsObject): objet graphique lié
        """

        self.param('delta').setValue(self.param('cursor 2').value()-self.param('cursor 1').value())
        #todo : test si delta vertical/horizontal
        if self.param('show delta on graph').value():
            self.arrows[0].setPos(self.param('cursor 1').value(),50)
            self.arrows[1].setPos(self.param('cursor 2').value(),50)

    def newLinkedObjects(self,field,item,**opts):
        """
        Méthode permettant de relier la position d'un item graphique à un paramaterItem
        de type float
        Args:
            field (parameterItem): paramaterItem lié à l'une des coordonnées de l'objet graphique
            item (GraphicsObject): objet graphique lié
        """

        index=len(self.linkedojects)

        def field_Changed(field,item):
            """
            Méthode interne permettant de relier le changement de la valeur du champ/parameterItem
            à la position (x ou y) de l'objet graphique
            Args:
                f (parameterItem): paramaterItem lié à l'une des coordonnées de l'objet graphique
                it (GraphicsObject): objet graphique lié
            """
            if field.value() !=item.pos():
                item.setPos(field.value())
                self.updateDelta()

        #lambda est nécessaire pour affecter une fonction à l'élément [id][0] de linkedojects.
        #Si field_Changed(field,item) était directement passé, un message d'erreur NoneType
        #apparaitrait
        self.linkedojects.append([lambda :field_Changed(field,item),None])

        def item_Changed(field,item,index:int):
            """
            Méthode interne permettant de relier le changement de position de l'objet graphique
            à la mise à jour du champ/parameterItem
            Args:
                field {parameterItem}   --  paramaterItem lié à l'une des coordonnées
                                            de l'objet graphique
                item {GraphicsObject}   --  objet graphique lié
                index {int}             --  index de la méthode chargée dans linkedobjects
                                            (field_Changed(f,it)) devant être bloquée afin
                                            d'éviter une boucle infinie
            """
            if item.pos() !=field.value():
                if self.opts['name']=="Vertical cursors":
                    val=item.pos().x()
                else:
                    val=item.pos().y()
                field.setValue(val, blockSignal=self.linkedojects[index][0])
                self.updateDelta()

        self.linkedojects[index][1]=lambda :item_Changed(field,item,index)
        field.sigValueChanged.connect(self.linkedojects[index][0])
        item.sigPositionChanged.connect(self.linkedojects[index][1])


    def getData(self):
        """
        Méthode retourant toute les données des deux curseurs: positions 1 & 2 ainsi que le delta
        Returns:
            Lits({float},{float},{float})  --  différence entre les deux curseurs
        """

        return [self.param('cursor 1').value(),
                self.param('cursor 2').value(),
                self.param("delta").value()]

class MouseCursors(pTypes.GroupParameter):
    """
    Classe héritant de pyqtgraph.parametertree.parameterTypes. Permet de rapidement créer
    un curseur de souris dont les valeurs sont renvoyées dans un parameterTreeItem
    """
    def __init__(self,graphWidget,curve=None, **opts):

        opts['expanded']=False
        self.linkedojects=[]
        self.cursors=[]
        self.valtext=pg.TextItem("", anchor=(1.5, -0.5),color=(100,100,100))
        font=QtGui.QFont()
        font.setBold(True)
        self.valtext.setFont(font)
        self.valtext.setZValue(20)
        self.textIndex=-1
        self.graph=graphWidget
        self.curve=curve
        self.curvePoint=None
        self.lastPos=None
        #modif du 05/10, mouseCursors utilisera la méthode MouseUpdate de View
        #afin de limiter le nombre de proxy.
        #self.vb = self.graph.vb


        for i in range(2):
            value=90*(1-i)
            self.cursors.append(pg.InfiniteLine(angle=value,
                                    movable=False,
                                    pos=value,
                                    pen=(100,100,100)))
        #passages des options à la classe parent GroupParameter
        pTypes.GroupParameter.__init__(self, **opts)

        params=[
                    {'name':'show cursors', 'type': 'bool','value':False},
                    {'name':'snap to selected signal','type':'bool','value':False,'enabled':False},
                    {'name':'show X value','type':'bool','value':False,'enabled':False},
                    {'name':'show Y value','type':'bool','value':False,'enabled':False}
                ]
        self.addChildren(params)
        self.itemDict={ 'show cursors':self.cursors,
                        'show X value':1,
                        'show Y value':2}

        #création des paramètres :
        self.sigTreeStateChanged.connect(self.updateGraph)
        """
        self.proxy = pg.SignalProxy(self.graph.scene().sigMouseMoved,rateLimit = 25,
                                    slot = self.mouseUpdate)
        """

    def setCurve(self,curve,file_params):


        self.file_params = file_params

        self.n_points = self.file_params.stop_x - self.file_params.start_x
        self.leftLimit = 0
        self.rightLimit = 1
        self.curve = curve
        self.updateGraph(None,[[self.param('snap to selected signal'),None,
                                self.param('snap to selected signal').value()]])
        if self.lastPos is not None:
            self.mouseUpdate(self.lastPos)


    def mouseUpdate(self,mousePoint):
        """_summary_

        Args:
            evt (_type_): _description_
        """
        #pos = evt[0]

        if self.param('show cursors').value():
            #mousePoint = self.vb.mapSceneToView(pos)
            mouse_x=mousePoint.x()
            if self.curve is not None and self.param('snap to selected signal').value():
                relativePos=((mouse_x-self.file_params.offset-self.file_params.start_x*self.file_params.sampling)/
                            (self.n_points*self.file_params.sampling))

                self.curvePoint.setPos(relativePos)
                #(self.file_params.n_samples*self.file_params.sampling))
                mouse_y=self.curvePoint.pos()[1]

                if relativePos>1:
                    mouse_x=self.file_params.stop_x*self.file_params.sampling + \
                            self.file_params.offset
                elif relativePos<0:
                    mouse_x=self.file_params.start_x*self.file_params.sampling + \
                        self.file_params.offset
            else:
                mouse_y=mousePoint.y()
                self.valtext.setPos(mouse_x,mouse_y)

            self.cursors[0].setPos(mouse_x)
            self.cursors[1].setPos(mouse_y)
            text=[f'X={mouse_x:0.1f}',f'Y={mouse_y:0.1f}',
                    f'X={mouse_x:0.1f}\nY={mouse_y:0.1f}']
            if self.textIndex>=0:
                self.valtext.setText(text[self.textIndex])
            self.lastPos=mousePoint

    def updateSelection(self,item):
        #! passer la courbe à suivre
        pass

    def updateGraph(self,group,modifications):
        """Méthode permettant d'afficher ou non les curseurs en fonction de l'état
        logique du parameterTreeItem associé

        Args:
            changes (GroupParameter): GroupParameter dans lequel est intervenu la modification
            params (GraphicsObject): liste de tuples constitué du paramètre modifié, du type de
            modification et de la nouvelle valeur de ce paramètre
        """

        #on ne considère que la première modification : donc toujours fairee un elif avec cursor en
        #tête car cursor permet d'activer les 3 autres paramètres si un seul évènement provoquant
        #alors l'activation de toutes l'arborescence de if.

        parameter,_,value=modifications[0]
        key=parameter.name()
        if key=='show cursors':

            if value:
                self.blockSignals(True)
                self.param('snap to selected signal').setOpts(enabled=True)
                self.param('show X value').setOpts(enabled=True)
                self.param('show Y value').setOpts(enabled=True)
                self.blockSignals(False)
            else:
                self.blockSignals(True)
                self.param('snap to selected signal').setOpts(enabled=False)
                self.param('show X value').setOpts(enabled=False)
                self.param('show Y value').setOpts(enabled=False)
                self.param('snap to selected signal').setValue(False)
                if self.textIndex>=0:
                    self.param('show X value').setValue(False)
                    self.param('show Y value').setValue(False)
                    #retirer valtext du graph n'écrase pas le texte conservé dans cet objet
                    #ce qui pose problème lorsque celui-ci est de nouveau affiché
                    self.valtext.setText('')
                    self.graph.removeItem(self.valtext)
                    self.textIndex=-1
                self.blockSignals(False)

            plotItems=self.itemDict[key]
            for item in plotItems:
                if value:
                    self.graph.addItem(item, ignoreBounds=True)
                else:
                    self.graph.removeItem(item)

        elif key=='show X value' or key=='show Y value':
            if value:
                if self.textIndex<0:
                    self.graph.addItem(self.valtext)
                    if self.param('snap to selected signal').value() and \
                        self.curvePoint is not None:
                        #setParentItem ne semble fonctionner que si l'objet parent
                        #est chargé dans le graphe\scene
                        self.valtext.setParentItem(self.curvePoint)

                self.textIndex+=self.itemDict[key]
            else:
                self.textIndex-=self.itemDict[key]
                if self.textIndex<0:
                    self.valtext.setText('')
                    self.graph.removeItem(self.valtext)

        elif key=='snap to selected signal':
            if value and self.curve is not None:
                if self.curvePoint is not None :
                    self.valtext.setParentItem(None)
                    self.graph.removeItem(self.curvePoint)

                self.curvePoint=pg.CurvePoint(self.curve)
                self.graph.addItem(self.curvePoint)
                curve_color=self.curve.opts['pen'].color()
                self.valtext.setColor(curve_color)
                self.cursors[0].setPen(curve_color)
                self.cursors[1].setPen(curve_color)
                self.valtext.setParentItem(self.curvePoint)

                #la position étant du texte étant définie par rapport à son parent
                #il faut retirer son ancienne position
                self.valtext.setPos(0,0)

            else:
                if self.curvePoint is not None:
                    self.valtext.setParentItem(None)
                    self.graph.removeItem(self.curvePoint)
                    default_color=(100,100,100)
                    self.valtext.setColor(default_color)
                    self.cursors[0].setPen(default_color)
                    self.cursors[1].setPen(default_color)

class TriggerOldCursor(pTypes.GroupParameter):
    """
    Classe héritant de pyqtgraph.parametertree.parameterTypes. Permet de rapidement créer
    des curseurs graphiques dont la valeur est renvoyée dans un parameterTreeItem
    """
    def __init__(self,graphWidget, **opts):

        opts['expanded']=False
        self.linkedojects=[]
        self.oldState=[0,0]
        self.graph=graphWidget


        self.cursor = pg.InfiniteLine(angle=90,
                                movable=True,
                                pos=0,
                                pen=opts['cursors_setting']['pen'],
                                label=opts['cursors_setting']['label'],
                                labelOpts=opts['cursors_setting']['labelOpts'])
        #! position verticale de la flèche ne se maintient pas en haut de l'écran
        self.arrow = pg.ArrowItem(angle=-90,
                                        tipAngle=30,
                                        headWidth=15,
                                        headLen=20,
                                        tailWidth=5,
                                        tailLen=0,
                                        pos=(0,self.graph.vb.viewRange()[1][1]*0.98),
                                        pen=(223, 109, 20),
                                        brush=(223, 109, 20))

        #passages des options à la classe parent GroupParameter
        pTypes.GroupParameter.__init__(self, **opts)

        #création des paramètres :
        value=self.cursor.pos().x()
        params=[
                    {'name':'Trigger Enabled', 'type': 'bool','value':False},
                    {'name':'Trigger level', 'type': 'float','value':value},
                    {'name':'type', 'type': 'list','value':"posedge",'values':["posedege","negedge"]},
                ]
        self.addChildren(params)

        #création des paramètres :
        self.newLinkedObjects(field=self.param('Trigger level'),item=self.cursor)
        self.sigTreeStateChanged.connect(self.updateGraph)
        self.graph.sigRangeChanged.connect(self.updateArrowHeight)
        self.cursor.sigPositionChanged.connect(self.updateArrowHeight)

    def cursorsState(self,state):
        """
        Méthode permettant d'ajouter ou retirer les curseurs
        Args:
            state {bool} -- état logique du paramètre "Show Cursors"
        """
        if state:
            #on recharge le curseur
            self.graph.addItem(self.cursor, ignoreBounds=True)
        else:
            #on recharge les droites représentant le curseur
            self.graph.removeItem(self.cursor)

    def arrowsState(self,state):
        """
        Méthode permettant d'ajouter ou retirer les flèches
        Args:
            state {bool} -- état logique du paramètre "Show delta"
        """
        if state:
            #on recharge les droites représentant le curseur
            self.graph.addItem(self.arrow, ignoreBounds=True)
        else:
            #on recharge les droites représentant le curseur
            self.graph.removeItem(self.arrow)


    def updateGraph(self,changes):
        """Méthode permettant d'afficher ou non les curseurs en fonction de l'état
        logique du parameterTreeItem associé

        Args:
            field (parameterItem): paramaterItem lié à l'une des coordonnées de l'objet graphique
            item (GraphicsObject): objet graphique lié
        """
        if changes['Trigger Enabled']!=self.oldState[0]:
            self.oldState[0]=changes['Trigger Enabled']
            self.cursorsState(self.param('Trigger Enabled').value())
            self.arrowsState(self.param('Trigger Enabled').value())

    def updateArrowHeight(self):

        self.arrow.setPos(self.cursor.pos().x(),self.graph.vb.viewRange()[1][1]*0.98)


    def newLinkedObjects(self,field,item,**opts):
        """
        Méthode permettant de relier la position d'un item graphique à un paramaterItem
        de type float
        Args:
            field (parameterItem): paramaterItem lié à l'une des coordonnées de l'objet graphique
            item (GraphicsObject): objet graphique lié
        """

        def field_Changed(field,item):
            """
            Méthode interne permettant de relier le changement de la valeur du champ/parameterItem
            à la position (x ou y) de l'objet graphique
            Args:
                f (parameterItem): paramaterItem lié à l'une des coordonnées de l'objet graphique
                it (GraphicsObject): objet graphique lié
            """
            if field.value() !=item.pos():
                item.setPos(field.value())

        #lambda est nécessaire pour affecter une fonction à l'élément [id][0] de linkedojects.
        #Si field_Changed(field,item) était directement passé, un message d'erreur NoneType
        #apparaitrait
        self.linkedojects= [lambda :field_Changed(field,item),None]

        def item_Changed(field,item):
            """
            Méthode interne permettant de relier le changement de position de l'objet graphique
            à la mise à jour du champ/parameterItem
            Args:
                field {parameterItem}   --  paramaterItem lié à l'une des coordonnées
                                            de l'objet graphique
                item {GraphicsObject}   --  objet graphique lié
                index {int}             --  index de la méthode chargée dans linkedobjects
                                            (field_Changed(f,it)) devant être bloquée afin
                                            d'éviter une boucle infinie
            """
            if item.pos() !=field.value():
                val=item.pos().x()
                field.setValue(val, blockSignal=self.linkedojects[0])

        self.linkedojects[1]=lambda :item_Changed(field,item)
        field.sigValueChanged.connect(self.linkedojects[0])
        item.sigPositionChanged.connect(self.linkedojects[1])


    def getData(self):
        """
        Méthode retourant toute les données des deux curseurs: positions 1 & 2 ainsi que le delta
        Returns:
            Lits({float},{float},{float})  --  différence entre les deux curseurs
        """

        return self.param('Trigger level').value()

class TriggerCursor(pTypes.GroupParameter):
    """
    Classe héritant de pyqtgraph.parametertree.parameterTypes. Permet de rapidement créer
    des curseurs graphiques dont la valeur est renvoyée dans un parameterTreeItem
    """
    def __init__(self,graphWidget, **opts):

        opts['expanded']=True
        self.linkedojects=[]
        self.oldState=[0,0]
        self.graph=graphWidget


        self.cursor = pg.InfiniteLine(angle=0,
                                movable=True,
                                pos=0,
                                pen=opts['cursors_setting']['pen'])
        #! position verticale de la flèche ne se maintient pas en haut de l'écran
        self.arrow = pg.ArrowItem(angle=-90,
                                        tipAngle=30,
                                        headWidth=15,
                                        headLen=20,
                                        tailWidth=5,
                                        tailLen=0,
                                        pos=(0,self.graph.vb.viewRange()[1][1]*0.98),
                                        pen=(223, 109, 20),
                                        brush=(223, 109, 20))

        #passages des options à la classe parent GroupParameter
        pTypes.GroupParameter.__init__(self, **opts)

        #création des paramètres :
        value=self.cursor.pos().y()
        params=[
                    {'name':'Trigger Enabled', 'type': 'bool','value':False},
                    {'name':'Trigger level', 'type': 'float','value':value},
                    {'name':'Trigger position', 'type': 'float','value':value},
                    {'name':'type', 'type': 'list','value':"posedge",'values':["posedege","negedge"]},
                ]
        self.addChildren(params)

        #création des paramètres :
        self.newLinkedObjects(field=self.param('Trigger level'),item=self.cursor)
        self.newLinkedObjects(field=self.param('Trigger position'),item=self.arrow)
        self.sigTreeStateChanged.connect(self.updateGraph)
        self.graph.sigRangeChanged.connect(self.updateArrowHeight)

    def cursorsState(self,state):
        """
        Méthode permettant d'ajouter ou retirer les curseurs
        Args:
            state {bool} -- état logique du paramètre "Show Cursors"
        """
        if state:
            #on recharge le curseur
            self.graph.addItem(self.cursor, ignoreBounds=True)
        else:
            #on recharge les droites représentant le curseur
            self.graph.removeItem(self.cursor)

    def arrowsState(self,state):
        """
        Méthode permettant d'ajouter ou retirer les flèches
        Args:
            state {bool} -- état logique du paramètre "Show delta"
        """
        if state:
            #on recharge les droites représentant le curseur
            self.graph.addItem(self.arrow, ignoreBounds=True)
        else:
            #on recharge les droites représentant le curseur
            self.graph.removeItem(self.arrow)


    def updateGraph(self,changes):
        """Méthode permettant d'afficher ou non les curseurs en fonction de l'état
        logique du parameterTreeItem associé

        Args:
            field (parameterItem): paramaterItem lié à l'une des coordonnées de l'objet graphique
            item (GraphicsObject): objet graphique lié
        """
        if changes['Trigger Enabled']!=self.oldState[0]:
            self.oldState[0]=changes['Trigger Enabled']
            self.cursorsState(self.param('Trigger Enabled').value())
            self.arrowsState(self.param('Trigger Enabled').value())

    def updateArrowHeight(self):

        self.arrow.setPos(self.arrow.pos().x(),self.graph.vb.viewRange()[1][1]*0.98)


    def newLinkedObjects(self,field,item,**opts):
        """
        Méthode permettant de relier la position d'un item graphique à un paramaterItem
        de type float
        Args:
            field (parameterItem): paramaterItem lié à l'une des coordonnées de l'objet graphique
            item (GraphicsObject): objet graphique lié
        """
        index=len(self.linkedojects)

        def field_Changed(field,item):
            """
            Méthode interne permettant de relier le changement de la valeur du champ/parameterItem
            à la position (x ou y) de l'objet graphique
            Args:
                f (parameterItem): paramaterItem lié à l'une des coordonnées de l'objet graphique
                it (GraphicsObject): objet graphique lié
            """
            if field.value() !=item.pos():
                item.setPos(field.value())

        #lambda est nécessaire pour affecter une fonction à l'élément [id][0] de linkedojects.
        #Si field_Changed(field,item) était directement passé, un message d'erreur NoneType
        #apparaitrait
        self.linkedojects.append([lambda :field_Changed(field,item),None])

        def item_Changed(field,item):
            """
            Méthode interne permettant de relier le changement de position de l'objet graphique
            à la mise à jour du champ/parameterItem
            Args:
                field {parameterItem}   --  paramaterItem lié à l'une des coordonnées
                                            de l'objet graphique
                item {GraphicsObject}   --  objet graphique lié
                index {int}             --  index de la méthode chargée dans linkedobjects
                                            (field_Changed(f,it)) devant être bloquée afin
                                            d'éviter une boucle infinie
            """
            if item.pos() !=field.value():
                if field.name() == 'Trigger level':
                    val=item.pos().y()
                else:
                    val=item.pos().x()
                field.setValue(val, blockSignal=self.linkedojects[index][0])

        self.linkedojects[index][1]=lambda :item_Changed(field,item)
        field.sigValueChanged.connect(self.linkedojects[index][0])
        if index==0:
            item.sigPositionChanged.connect(self.linkedojects[index][1])


    def getData(self):
        """
        Méthode retourant toute les données des deux curseurs: positions 1 & 2 ainsi que le delta
        Returns:
            Lits({float},{float},{float})  --  différence entre les deux curseurs
        """

        return self.param('Trigger level').value()