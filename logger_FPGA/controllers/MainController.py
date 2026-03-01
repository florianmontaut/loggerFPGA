import pandas as pd
import datetime
import csv
import numpy as np
import time

from PyQt6 import QtCore,QtGui
from PyQt6.QtWidgets import QFileDialog,QTreeWidgetItem


import pyqtgraph as pg
import pyqtgraph.parametertree as ptree

from ressources import CustomFunctions
from ressources import CustomTypes,CustomItems
from model.Model import Model
from views.View import MainWindow
from controllers.UDPController import acquisition_FPGA



class MainController():

    def __init__(self,model:Model,view: MainWindow,**opts):

        self._model=model
        self._view=view
        self._view.UIsignals.connect(self.filterUIsignals)
        self._view.treefile.itemClicked.connect(self.updateSelectionTree)
        #self._model.MAJ_options.connect(self.updateOptions)
        #self._model.MAJ_files.connect(self.setUDPConfig)
        self.draw_data=True
        self.FPGAcom=acquisition_FPGA()
        #self.FPGAcom.config.fromJson("C:/__projet/__dev/env_2023/env/python 120206/logger_FPGA/ressources/parametres_scope.json")
        self.FPGAcom.started.connect(self.FPGAcom.open)
        self.FPGAcom.data_received.connect(self.update_display)
        self.FPGAcom.status_changed.connect(self._view.updateMessageBar)

        self.optsDict = {
                        "Cut-off frequency"  : "filter_freq"
                        }
        self.opts = {
                    "filter_freq":    0.003
                    }

        if opts:
            self.updateOptions(**opts)

    def updateOptions(self,opts=None):

        self.opts.update({self.optsDict[key]:item for key,item in opts["Filter settings"].items()})

    def setUDPConfig(self,item):
        
        print(item.struct.fpga_config)
        self.FPGAcom.config=item.struct.fpga_config
        

    def UpdateUDPThread(self,newParameters):
        
        self.FPGAcom.close()
        self.FPGAcom.config.fromParameters(newParameters)
        self.FPGAcom.start()

    #@QtCore.pyqtSlot('np.ndarray') => l'utilisation du pyqtSlot est indiqué comme étant plus rapide (utilisation de librairie C++)
    #cepedant data est un np.ndarray qui n'est pas reconnu en C++
    def update_display(self,data):

        if self.draw_data:
            self._view.traceLiveStream(data)

        #print(data)
        '''
        ######################? LOGGER.M ############################
        si voies logiques :
        data_bin = dec2bin(typecast(data_16(:, end), 'uint16'), 16);
        log = [bin2dec(data_bin(:, 16))/2, 1+bin2dec(data_bin(:, 15))/2, 2+bin2dec(data_bin(:, 14))/2, 3+bin2dec(data_bin(:, 13))/2, ...
            4+bin2dec(data_bin(:, 12))/2, 5+bin2dec(data_bin(:, 11))/2, 6+bin2dec(data_bin(:, 10))/2, 7+bin2dec(data_bin(:, 9))/2, ...
            8+bin2dec(data_bin(:, 8))/2, 9+bin2dec(data_bin(:, 7))/2, 10+bin2dec(data_bin(:, 6))/2, 11+bin2dec(data_bin(:, 5))/2, ...
            12+bin2dec(data_bin(:, 4))/2, 13+bin2dec(data_bin(:, 3))/2, 14+bin2dec(data_bin(:, 2))/2, 15+bin2dec(data_bin(:, 1))/2];
        log étant un tableau de 15 colonnes de n échantillons, une colonne étant un signal

        sinon data = double(data_16)/16384;


        data_16 = typecast(uint16(data_8(1:2:length(data_8)-1))*256+uint16(data_8(2:2:length(data_8))), 'int16');
        #printf("%d",length(data_16))
        data_16 = fliplr(reshape(data_16, sd/nch, nch));
        if sig(nch) == 15
            data_bin = dec2bin(typecast(data_16(:, end), 'uint16'), 16);
            log = [bin2dec(data_bin(:, 16))/2, 1+bin2dec(data_bin(:, 15))/2, 2+bin2dec(data_bin(:, 14))/2, 3+bin2dec(data_bin(:, 13))/2, ...
                4+bin2dec(data_bin(:, 12))/2, 5+bin2dec(data_bin(:, 11))/2, 6+bin2dec(data_bin(:, 10))/2, 7+bin2dec(data_bin(:, 9))/2, ...
                8+bin2dec(data_bin(:, 8))/2, 9+bin2dec(data_bin(:, 7))/2, 10+bin2dec(data_bin(:, 6))/2, 11+bin2dec(data_bin(:, 5))/2, ...
                12+bin2dec(data_bin(:, 4))/2, 13+bin2dec(data_bin(:, 3))/2, 14+bin2dec(data_bin(:, 2))/2, 15+bin2dec(data_bin(:, 1))/2];
            if chn != 1
                data = double(data_16(:,1:end-1))/16384;
            endif
        else
            data = double(data_16)/16384;
        endif
        #si affichage actif:
        if pl == 1
            cla(gca, 'reset') #clear des axes
            #si en mode logique
            if chn == 15
                img = subplot(1, 1, 1); #ajout d'un graph
                stairs(log)             #
                % set(img,'Position',[0.05, 0.1, 0.9, 0.9])
                yticks(0:15)
                ylim([-.5, 16])
                xticks([0 .25 .5 .75 1]*sd)
                xlim(vi)
            else
                #?si en mode logique ???
                if sig(nch) == 15
                    img = subplot(2, 1, 2);
                    stairs(log)
                    % set(img,'Position',[0.05, 0.05, 0.9, 0.3])
                    yticks(0:15)
                    ylim([-.5, 16])
                    xticks([0 .25 .5 .75 1]*sd/nch)
                    xlim(vi)
                    grid
                    img = subplot(2, 1, 1);
                    npl=nch-1;
                    else
                    img = subplot(1, 1, 1);
                    npl=nch;
                endif
                plot(data.*ch_gain(sig(1:npl)+1))
                % if sig(nch) == 15
                % set(img,'Position',[0.05, 0.4, 0.9, 0.55])
                % else
                % set(img,'Position',[0.05, 0.05, 0.9, 0.9])
                % endif
                ylim([-1, 1]*(floor(max(abs(ch_gain(sig(1:npl)+1)))/10)+2)*10)
                xticks([0 .25 .5 .75 1]*sd/nch)
                xlim(vi)
            endif
        grid
        title(sprintf('%d  -  %.2f Mo', frame, frame*sd/1048576))
        endif

        #si sauvegarde actif:
        if wr == 1 && frame_nb != inf
            if ~exist('fnum')
                fnum = 1;
            else
                fnum++;
            endif;
            if chn != 15
                if chn == 1
                f_dat = strcat(pre, char(ch_name(sig(1)+1)), sprintf('_div_%d_%d.dat', div, fnum));
                elseif chn == 2
                f_dat = strcat(pre, char(ch_name(sig(1)+1)), char(ch_name(sig(2)+1)), sprintf('_div_%d_%d.dat', div, fnum));
                elseif chn == 4
                f_dat = strcat(pre, char(ch_name(sig(1)+1)), char(ch_name(sig(2)+1)), char(ch_name(sig(3)+1)), ...
                                char(ch_name(sig(4)+1)), sprintf('_div_%d_%d.dat', div, fnum));
                elseif chn == 8
                f_dat = strcat(pre, char(ch_name(sig(1)+1)), char(ch_name(sig(2)+1)), char(ch_name(sig(3)+1)), ...
                                char(ch_name(sig(4)+1)), char(ch_name(sig(5)+1)), char(ch_name(sig(6)+1)), ...
                                char(ch_name(sig(7)+1)), char(ch_name(sig(8)+1)), sprintf('_div_%d_%d.dat', div, fnum));
                endif
                for i = 1:size(data)(2)
                data(:, i) = data(:, i)*ch_gain(sig(i)+1);
                endfor
                save('-binary', f_dat, 'data')
            endif
            if sig(nch) == 15
                log = [bin2dec(data_bin(:, 16)), bin2dec(data_bin(:, 15)), bin2dec(data_bin(:, 14)), bin2dec(data_bin(:, 13)), ...
                    bin2dec(data_bin(:, 12)), bin2dec(data_bin(:, 11)), bin2dec(data_bin(:, 10)), bin2dec(data_bin(:, 9)), ...
                    bin2dec(data_bin(:, 8)), bin2dec(data_bin(:, 7)), bin2dec(data_bin(:, 6)), bin2dec(data_bin(:, 5)), ...
                    bin2dec(data_bin(:, 4)), bin2dec(data_bin(:, 3)), bin2dec(data_bin(:, 1)), bin2dec(data_bin(:, 1))];
                f_log = strcat(pre, sprintf('Logic_div_%d_%d.dat', div, fnum));
                save('-binary', f_log, 'log')
            endif
        endif



        ######################? REMOTE PLOTING PYQTGRAPH ############################


        ######################? Line plot update PYQTGRAPH ############################

            """
            Update a simple plot as rapidly as possible to measure speed.
            """

            import argparse
            import itertools

            import numpy as np
            from utils import FrameCounter

            import pyqtgraph as pg
            import pyqtgraph.functions as fn
            import pyqtgraph.parametertree as ptree
            from pyqtgraph.Qt import QtCore, QtGui, QtWidgets

            # defaults here result in the same configuration as the original PlotSpeedTest
            parser = argparse.ArgumentParser()
            parser.add_argument('--noise', dest='noise', action='store_true')
            parser.add_argument('--no-noise', dest='noise', action='store_false')
            parser.set_defaults(noise=True)
            parser.add_argument('--nsamples', default=5000, type=int)
            parser.add_argument('--frames', default=50, type=int)
            parser.add_argument('--fsample', default=1000, type=float)
            parser.add_argument('--frequency', default=0, type=float)
            parser.add_argument('--amplitude', default=5, type=float)
            parser.add_argument('--opengl', dest='use_opengl', action='store_true')
            parser.add_argument('--no-opengl', dest='use_opengl', action='store_false')
            parser.set_defaults(use_opengl=None)
            parser.add_argument('--allow-opengl-toggle', action='store_true',
                help="""Allow on-the-fly change of OpenGL setting. This may cause unwanted side effects.
                """)
            parser.add_argument('--iterations', default=float('inf'), type=float,
                help="Number of iterations to run before exiting"
            )
            args = parser.parse_args()

            if args.use_opengl is not None:
                pg.setConfigOption('useOpenGL', args.use_opengl)
                pg.setConfigOption('enableExperimental', args.use_opengl)
            use_opengl = pg.getConfigOption('useOpenGL')

            # don't limit frame rate to vsync
            sfmt = QtGui.QSurfaceFormat()
            sfmt.setSwapInterval(0)
            QtGui.QSurfaceFormat.setDefaultFormat(sfmt)


            class MonkeyCurveItem(pg.PlotCurveItem):
                def __init__(self, *args, **kwds):
                    super().__init__(*args, **kwds)
                    self.monkey_mode = ''

                def setMethod(self, value):
                    self.monkey_mode = value

                def paint(self, painter, opt, widget):
                    if self.monkey_mode not in ['drawPolyline']:
                        return super().paint(painter, opt, widget)

                    painter.setRenderHint(painter.RenderHint.Antialiasing, self.opts['antialias'])
                    painter.setPen(pg.mkPen(self.opts['pen']))

                    if self.monkey_mode == 'drawPolyline':
                        painter.drawPolyline(fn.arrayToQPolygonF(self.xData, self.yData))

            app = pg.mkQApp("Plot Speed Test")

            default_pen = pg.mkPen()

            params = ptree.Parameter.create(name='Parameters', type='group')
            pt = ptree.ParameterTree(showHeader=False)
            pt.setParameters(params)
            pw = pg.PlotWidget()
            splitter = QtWidgets.QSplitter()
            splitter.addWidget(pt)
            splitter.addWidget(pw)
            splitter.show()

            interactor = ptree.Interactor(
                parent=params, nest=False, runOptions=ptree.RunOptions.ON_CHANGED
            )

            pw.setWindowTitle('pyqtgraph example: PlotSpeedTest')
            pw.setLabel('bottom', 'Index', units='B')
            curve = MonkeyCurveItem(pen=default_pen, brush='b')
            pw.addItem(curve)
            iterations_counter = itertools.count()

            @interactor.decorate(
                nest=True,
                nsamples={'limits': [0, None]},
                frames={'limits': [1, None]},
                fsample={'units': 'Hz'},
                frequency={'units': 'Hz'}
            )
            def makeData(
                noise=args.noise,
                nsamples=args.nsamples,
                frames=args.frames,
                fsample=args.fsample,
                frequency=args.frequency,
                amplitude=args.amplitude,
            ):
                global data, connect_array, ptr
                ttt = np.arange(frames * nsamples, dtype=np.float64) / fsample
                data = amplitude*np.sin(2*np.pi*frequency*ttt).reshape((frames, nsamples))
                if noise:
                    data += np.random.normal(size=data.shape)
                connect_array = np.ones(data.shape[-1], dtype=bool)
                ptr = 0
                pw.setRange(QtCore.QRectF(0, -10, nsamples, 20))

            params.child('makeData').setOpts(title='Plot Options')


            @interactor.decorate(
                connect={'type': 'list', 'limits': ['all', 'pairs', 'finite', 'array']}
            )
            def update(
                antialias=pg.getConfigOption('antialias'),
                connect='all',
                skipFiniteCheck=False
            ):
                global ptr

                if next(iterations_counter) > args.iterations:
                    # cleanly close down benchmark
                    timer.stop()
                    app.quit()
                    return None

                if connect == 'array':
                    connect = connect_array

                curve.setData(
                    data[ptr],
                    antialias=antialias,
                    connect=connect,
                    skipFiniteCheck=skipFiniteCheck
                )
                ptr = (ptr + 1) % data.shape[0]
                framecnt.update()


            @interactor.decorate(
                useOpenGL={'readonly': not args.allow_opengl_toggle},
                plotMethod={'limits': ['pyqtgraph', 'drawPolyline'], 'type': 'list'},
                curvePen={'type': 'pen'}
            )
            def updateOptions(
                curvePen=pg.mkPen(),
                plotMethod='pyqtgraph',
                fillLevel=False,
                enableExperimental=use_opengl,
                useOpenGL=use_opengl,
            ):
                pg.setConfigOption('enableExperimental', enableExperimental)
                pw.useOpenGL(useOpenGL)
                curve.setPen(curvePen)
                curve.setFillLevel(0.0 if fillLevel else None)
                curve.setMethod(plotMethod)


            makeData()

            timer = QtCore.QTimer()
            timer.timeout.connect(update)
            timer.start(0)

            framecnt = FrameCounter()
            framecnt.sigFpsUpdate.connect(lambda fps: pw.setTitle(f'{fps:.1f} fps'))

            if __name__ == '__main__':
                # Splitter by default gives too small of a width to the parameter tree,
                # so fix that right before the event loop
                pt.setMinimumSize(225,0)
                pg.exec()


        ######################? SCROLL PLOT ############################

        """
        Various methods of drawing scrolling plots.
        """

        from time import perf_counter

        import numpy as np

        import pyqtgraph as pg

        win = pg.GraphicsLayoutWidget(show=True)
        win.setWindowTitle('pyqtgraph example: Scrolling Plots')


        # 1) Simplest approach -- update data in the array such that plot appears to scroll
        #    In these examples, the array size is fixed.
        p1 = win.addPlot()
        p2 = win.addPlot()
        data1 = np.random.normal(size=300)
        curve1 = p1.plot(data1)
        curve2 = p2.plot(data1)
        ptr1 = 0
        def update1():
            global data1, ptr1
            data1[:-1] = data1[1:]  # shift data in the array one sample left
                                    # (see also: np.roll)
            data1[-1] = np.random.normal()
            curve1.setData(data1)

            ptr1 += 1
            curve2.setData(data1)
            curve2.setPos(ptr1, 0)


        # 2) Allow data to accumulate. In these examples, the array doubles in length
        #    whenever it is full.
        win.nextRow()
        p3 = win.addPlot()
        p4 = win.addPlot()
        # Use automatic downsampling and clipping to reduce the drawing load
        p3.setDownsampling(mode='peak')
        p4.setDownsampling(mode='peak')
        p3.setClipToView(True)
        p4.setClipToView(True)
        p3.setRange(xRange=[-100, 0])
        p3.setLimits(xMax=0)
        curve3 = p3.plot()
        curve4 = p4.plot()

        data3 = np.empty(100)
        ptr3 = 0

        def update2():
            global data3, ptr3
            data3[ptr3] = np.random.normal()
            ptr3 += 1
            if ptr3 >= data3.shape[0]:
                tmp = data3
                data3 = np.empty(data3.shape[0] * 2)
                data3[:tmp.shape[0]] = tmp
            curve3.setData(data3[:ptr3])
            curve3.setPos(-ptr3, 0)
            curve4.setData(data3[:ptr3])


        # 3) Plot in chunks, adding one new plot curve for every 100 samples
        chunkSize = 100
        # Remove chunks after we have 10
        maxChunks = 10
        startTime = perf_counter()
        win.nextRow()
        p5 = win.addPlot(colspan=2)
        p5.setLabel('bottom', 'Time', 's')
        p5.setXRange(-10, 0)
        curves = []
        data5 = np.empty((chunkSize+1,2))
        ptr5 = 0

        def update3():
            global p5, data5, ptr5, curves
            now = perf_counter()
            for c in curves:
                c.setPos(-(now-startTime), 0)

            i = ptr5 % chunkSize
            if i == 0:
                curve = p5.plot()
                curves.append(curve)
                last = data5[-1]
                data5 = np.empty((chunkSize+1,2))
                data5[0] = last
                while len(curves) > maxChunks:
                    c = curves.pop(0)
                    p5.removeItem(c)
            else:
                curve = curves[-1]
            data5[i+1,0] = now - startTime
            data5[i+1,1] = np.random.normal()
            curve.setData(x=data5[:i+2, 0], y=data5[:i+2, 1])
            ptr5 += 1


        # update all plots
        def update():
            update1()
            update2()
            update3()
        timer = pg.QtCore.QTimer()
        timer.timeout.connect(update)
        timer.start(50)

        if __name__ == '__main__':
            pg.exec()



        '''


    '''
    def updateSettings(self,dico):
        """_summary_

        Args:
            dico (dict): _description_
        """
        self._model.settings=dico
        print(self._model.settings)
    '''

    def updateSelectionTree(self,item:QTreeWidgetItem):
        """Méthode mettant à jour l'arborescence des options de modifications des signaux
        Args:
            item (QTreeWidgetItem): item sélectionné par l'utilisateur. Si c'est un signal,
                                    la méthode met à disposition les méthodes de filtrage et
                                    de modification du graph. Si c'est un fichier racine, elle
                                    retourne les méthodes de décalage et troncage des données
        """

        #! AVANT DE CHANGER LA SELECTION IL FAUT RECUPERER LES DONNEES DE LA DERNIERE SELECTION ET LES SAUVEGARDER!#
        old_selection=self._view.old_highlight[0]
        self._view.treefile.scrollTo(self._view.treefile.indexFromItem(item))
        #si l'item sélectionné est désactivé on sort de la méthode.
        if item.isDisabled():
            return
        #si item est un signal (il n'a pas de flag ItemIsAutoTristate) on entre dans le if

        #if item.type==(CustomItems.itemType.RAW or CustomItems.itemType.MODIF) :

        if item.type==CustomItems.itemType.FILE:
            self._view.highlight(item,None)
            params=item.getParameters()
            self._view.selectiontree.setParameters(params)
        else:
            if item.curve is not None :
                self._view.highlight(item,item.curve)
                file_id = item.file_id[0]
                file_params=self._model.gl_files[file_id].file_params
                self._view.graphTree_params.param('Graphics items',
                                                    'Mouse cursor').setCurve(item.curve,
                                                                            file_params)
            params=item.getParameters()
            self._view.selectiontree.setParameters(params)
            modelizer = params.param('Curve modeling')
            def update_pen():
                pen = params.child('Curve pen').value()
                item.curve.setPen(pen)
                CustomFunctions.setItemFont(item,brush = pg.mkBrush(pen.color()))

            def filter_curve():
                print('filter action!')
                fc = params.child('Curve modification','Cut-off frequency').value()
                self.filter(items = [item],cut_freq = fc)
            def model_curve():
                selected_model = modelizer.getFunction()
                self.getThermalModel(items = [item], model = selected_model)

            params.sigTreeStateChanged.connect(update_pen)
            params.param('Curve modification', 'Filter curve').sigActivated.connect(filter_curve)
            modelizer.createModel.sigActivated.connect(model_curve)


    def removeSignal(self,it = None):
        if it :
            table_qitems = [it]
        else:
            table_qitems = CustomFunctions.getItems(self.treefile,type_methode = 'selected')
        if table_qitems is not None:
            root = self.treefile.invisibleRootItem()
            for item in table_qitems:
                #print(item)
                if item.flags()& QtCore.Qt.ItemFlag.ItemIsAutoTristate:
                    (item.parent() or root).removeChild(item)
                else:
                    item.setDisabled(True)
                    item.setCheckState(0,QtCore.Qt.CheckState.Unchecked)
                    #item.setFlags(item.flags()& ~QtCore.Qt.ItemFlag.ItemIsUserCheckable)
                    if self._model.curves :
                        try:
                            curve = [curve for curve,tree_item in self._model.curves if
                                    tree_item==item][0]
                            if curve in self._view.plotgraph.listDataItems():
                                self._view.plotgraph.removeItem(curve)
                        except:
                            pass

    def filterUIsignals(self,event:tuple):
        signal,_=event
        if signal==CustomTypes.qSignalType.CONNECT:
            #self.FPGAcom.isrunning
            if self.draw_data==False:
                self.draw_data=True
            if not self.FPGAcom.isConnected :
                if not self.FPGAcom.isRunning():
                    self.FPGAcom.start()
                else:
                    self.FPGAcom.open()
        elif signal==CustomTypes.qSignalType.DISCONNECT:
            self.FPGAcom.close()
        elif signal==CustomTypes.qSignalType.PAUSE:
            self.draw_data^=1
        
        if not self.draw_data and self.FPGAcom.isConnected:
            self._view.updateMessageBar("Graphic is paused")

    def remove(self,table_qitems):

        root = self._view.treefile.invisibleRootItem()
        for item in table_qitems:
            if item.flags()& QtCore.Qt.ItemFlag.ItemIsAutoTristate:
                (item.parent() or root).removeChild(item)
            else:
                item.setDisabled(True)
                item.setCheckState(0,QtCore.Qt.CheckState.Unchecked)
                item.setFlags(item.flags()& ~QtCore.Qt.ItemFlag.ItemIsUserCheckable)
                if self._model.curves :
                    try:
                        curve = [curve for curve,tree_item in self._model.curves if
                                tree_item==item][0]
                        if curve in self._view.plotgraph.listDataItems():
                            self._view.plotgraph.removeItem(curve)
                    except:
                        pass
