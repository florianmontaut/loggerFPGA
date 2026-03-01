import pandas as pd
import numpy as np
import datetime
import csv
import re

from PyQt6.QtWidgets import QFileDialog
from ressources import CustomFunctions,CustomItems,CustomTypes
from model.Model import Model,Capture
from views.View import MainWindow




class ImportController():

    def __init__(self,model:Model,view: MainWindow,**opts):

        self._model = model
        self._view=view
        self._view.loadFile_signal.connect(self.loaderSelect)
        self._model.MAJ_options.connect(self.updateOptions)
        default_time=datetime.datetime.now()
        self.optsDict={
                        "Remove old viewer data when importing new file"            : "remove_old_graph"  ,
                        "Remove overrange channels"                                 : "remove_overrange"  ,
                        "Auto filter"                                               : "auto_filter"       ,
                        "Use the file datetime to synchronize log files"            : "datetime_active"   ,
                        ("Downsample at import","Active")                           : "downsample_signals",
                        ("Downsample at import","Downsampling factor")              : "downsample_ratio"  ,
                        ("Downsample at import","Downsampling type")                : "downsample_type"   ,
                        ("Downsample at import","Downsampling threshold")           : "downsample_thres",
                        "Default sampling for imported generic .csv file"           : "default_sampling_txt",
                        "Default sampling for imported .txt file"                   : "default_time",
                        ("File import setting","Use latest files as working folder"): "latest_import",
                        ("File import setting","Set working folder")                : "custom_folder"
                    }
        self.opts={
                            "remove_old_graph"          : False,
                            "remove_overrange"          : True,
                            "auto_filter"               : False,
                            "datetime_active"           : False,
                            "downsample_signals"        : False,
                            "downsample_ratio"          : 10,
                            "downsample_type"           : "Peak",
                            "downsample_thres"          : 10,
                            "default_sampling_txt"      : 20*10**-3,
                            "default_sampling_csv"      : 1,
                            "default_time"              : default_time,
                            "custom_folder"             :  "",
                            "latest_import"             : True,
                            "default_delimitor"         : ";",
                            "default_unit_separator"    : ","
                    }
        if opts:
            self.updateOptions(**opts)

    def updateOptions(self,opts):

        self.opts.update({self.optsDict[key]:item for key,item in opts["Import settings"].items()})


    def openTxt(self,fname):
        """
        Méthode permettant de charger un fichier .txt (exemple enregistrement des NTCs via matis)
        Arguments:
                None   --
        Returns:
                None   --
        """
        with open(fname, 'r') as csvfile:

            dialect = csv.Sniffer().sniff(csvfile.read(4096), delimiters=';,\t')
            csvfile.seek(0) #! SNIFFER PLANTE avec un .txt
            rawtxt = list(csv.reader(csvfile, dialect))
            n_points=len(rawtxt)-1
            sampling=self.opts["default_sampling_txt"]
            start_time=self.opts["default_time"]
            channels=[]
            check_table=[]
            for val in rawtxt.pop(0):
                if val:
                    channels.append(val)
            channels.pop(0)

            df=pd.DataFrame([line[1:-1] for line in rawtxt],columns=channels)
            for signal in channels:
                df[signal]=pd.to_numeric(df[signal],errors='coerce')
                # TODO channels span: faut-il vérifier la validité des données sur un fichier csv?
                channels_span=1000
                check_table.append(self.isChannelValid(df[signal],
                                                            channels_span,
                                                            active=self.opts["remove_overrange"]))

            df.insert(loc=0,
                        column='Time',
                        value=np.linspace(0,(n_points-1)*sampling,
                                        n_points))
            data=df.set_index('Time',append=True)
            n_files=len(self._model.gl_files)
            file_caracs=CustomItems.FileStruct(
                                                file_id=[n_files,0],
                                                _absolute_id=self._model.cpt_id,
                                                adress=fname,
                                                sampling=sampling,
                                                n_samples=n_points,
                                                recordDate=start_time,
                                                validTable=check_table
                                            )

    @staticmethod
    def convertDate(date):

        date_str =' '.join(date)
        if '-'in date_str:
            date_format = '%d-%m-%Y %H:%M:%S'
            try:
                date_obj = datetime.datetime.strptime(date_str, date_format)
            except ValueError:
                date_format = '%Y-%m-%d %H:%M:%S'
                try:
                    date_obj = datetime.datetime.strptime(date_str, date_format)
                except ValueError:
                    return "Failed date conversionn with '-' separator"
        elif '/'in date_str:
            date_format = '%d/%m/%Y %H:%M:%S'
            try:
                date_obj = datetime.datetime.strptime(date_str, date_format)
            except ValueError:
                date_format = '%Y/%m/%d %H:%M:%S'
                try:
                    date_obj = datetime.datetime.strptime(date_str, date_format)
                except ValueError:
                    return "Failed date conversionn with '-' separator"
        else:
            return None

        return date_obj
        #On remplace "Trigger time" par sa valeur. "Start time" ne correspond
        #pas au début de l'enregistrement


    def loaderSelect(self,loadStruct:tuple[CustomTypes.fileType,list[str]]):
        """
        Méthode gérant la réception des données du viewer. Cette dernière utilise la méthode
        liée à l'extension du(es) fichier(s) à charger. Seul plusieurs fichiers du même type
        (GL/CSV/TXT) peuvent être chargés par la méthode loaderSelect.

        Arguments:
                fname      --
                fileType   --
        Returns:
                None        --
        """
        load_dict = {
                    CustomTypes.fileType.JSON:self.openJson,
                    CustomTypes.fileType.TXT:self.openTxt}

        fileType,fnames=loadStruct

        for fname in fnames:
            load_dict[fileType](fname)

    def openJson(self,fname):
        """
        Méthode permettant de charger un fichier .txt (exemple enregistrement des NTCs via matis)
        Arguments:
                None   --
        Returns:
                None   --
        """
        #on récupère le nom du fichier config en supprimant l'extension .json
        title=fname.split('/')[-1][:-5]
        newCapture=CustomItems.CaptureStruct(
                                                name=title,
                                                file_id=[0,0],
                                                address=str(fname),
                                                _absolute_id=0
                                            )
        self._model.newFile(Capture(newCapture))
        self._view.toggleButtons()