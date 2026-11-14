# main.py
"""
Logger FPGA : configuration du logger d'une carte UC par UDP et affichage temps réel.

    python main.py                     dernière configuration utilisée
    python main.py config.json         configuration donnée (format logger_app ou
                                       ressources/parametres_scope.json de logger_FPGA)

Démarrage, fermeture ordonnée, journal des erreurs et exécutable : paquet qtsocle
(https://github.com/florianmontaut/qtsocle). Exécutable : build_exe.bat.
"""
import sys

import pyqtgraph as pg
from qtsocle import app, paths

ROOT = paths.bundle_root(__file__)
sys.path.insert(0, str(ROOT))

from controller.main_controller import MainController      # noqa: E402
from model.config import LoggerConfig                      # noqa: E402
from version import __version__                            # noqa: E402
from view.main_window import MainWindow                    # noqa: E402

APP_NAME = "LoggerFPGA"
ICON = ROOT / "ressources" / "icons" / "icon.ico"


def make_window() -> MainWindow:
    # graphiques sur fond noir, comme un oscilloscope : les couleurs des voies, des
    # curseurs et des repères sont choisies pour ce fond (le thème de qtsocle, appliqué
    # par app.run, les mettrait sur fond clair avec un Windows en thème clair)
    pg.setConfigOption("background", "k")
    pg.setConfigOption("foreground", "d")
    return MainWindow()


def main(argv=None) -> int:
    argv = sys.argv if argv is None else argv
    # depuis les sources : donnees_locales/ (ignoré par git) ; exécutable : %APPDATA%
    data_dir = paths.user_data_dir(APP_NAME, dev_root=ROOT / "donnees_locales")
    # lue avant l'ouverture de la fenêtre : un fichier illisible s'affiche dans la console
    cfg = LoggerConfig.load(argv[1]) if len(argv) > 1 else None
    return app.run(make_window, lambda window: MainController(window, cfg),
                   name=APP_NAME, version=__version__, icon=ICON,
                   log_file=data_dir / "erreurs.log", argv=argv)


if __name__ == "__main__":
    sys.exit(main())
