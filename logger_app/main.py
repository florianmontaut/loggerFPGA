# main.py
"""
Logger FPGA : configuration du logger d'une carte UC par UDP et affichage temps réel.

    python main.py                     dernière configuration utilisée
    python main.py config.json         configuration donnée (format logger_app ou
                                       ressources/parametres_scope.json de logger_FPGA)
"""
import sys

from PyQt6.QtWidgets import QApplication

from controller.main_controller import MainController
from model.config import LoggerConfig
from view.main_window import MainWindow


def main(argv=None):
    argv = sys.argv if argv is None else argv
    app = QApplication(argv)
    app.setApplicationName("LoggerFPGA")
    try:                                    # même thème que le GLviewer, s'il est installé
        import qdarktheme
        qdarktheme.setup_theme("auto")
    except Exception:
        pass
    cfg = LoggerConfig.load(argv[1]) if len(argv) > 1 else None
    window = MainWindow()
    controller = MainController(window, cfg)   # noqa: F841 (gardé en vie par la boucle)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
