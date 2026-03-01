import sys
from PyQt6.QtWidgets import QApplication

from views.View import MainWindow
from model.Model import Model
from controllers import MainController,ImportController
from ressources import CustomSettings
import qdarktheme
import os


#**********************************************************************************************************#
#   DMLogger est une application permettant de se connecter au FPGA d'une carte UC standard R211           #
#**********************************************************************************************************#

class App(QApplication):


    def __init__(self,sys_argv):
        super(App,self).__init__(sys_argv)
        qdarktheme.setup_theme("auto")
        if os.path.isfile('GLprofile.json'):
            print('File exists')
        else:
            print('File does not exist')

        params=None
        if params is None:
            session_params = CustomSettings.params
        self.model = Model() #! Model(session_params['Model'])
        self.main_view          = MainWindow(self.model,session_params)
        self.main_controller    = MainController.MainController(self.model,self.main_view)
        self.import_contoller   = ImportController.ImportController(self.model,self.main_view)
        self.model.MAJ_options.connect(self.toggle_theme)
        self.main_view.show()

    def toggle_theme(self,opts) -> None:

        dark=opts["Graph settings"].get(("Appearance","Dark mode"),False)

        if dark :
            palette = qdarktheme.load_palette(theme="dark")
            stylesheet = qdarktheme.load_stylesheet(theme="dark")
        else:
            palette = qdarktheme.load_palette(theme="auto")
            stylesheet = qdarktheme.load_stylesheet(theme="auto")

        self.setPalette(palette)
        self.setStyleSheet(stylesheet)


if __name__ == '__main__':
    app = App(sys.argv)

    sys.exit(app.exec())
