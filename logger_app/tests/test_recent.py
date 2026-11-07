"""Fichiers récents et dernier répertoire visité."""
import os

import pytest
from PyQt6 import QtCore, QtWidgets

from controller.recent_controller import MAX_RECENT, RecentFilesController


@pytest.fixture(scope="module")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def files(tmp_path, *names):
    out = []
    for name in names:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x")
        out.append(str(path))
    return out


def texts(menu):
    return [a.text() for a in menu.actions() if not a.isSeparator()]


def test_order_dedupe_limit_and_menu(qapp, tmp_path):
    menu = QtWidgets.QMenu()
    recent = RecentFilesController(menu, None, lambda: str(tmp_path))
    assert texts(menu) == ["Aucun fichier récent"] and not menu.actions()[0].isEnabled()
    a, b, c = files(tmp_path, "a.csv", "sous/b.h5", "c.json")
    recent.add("logger", [a])
    recent.add("scope", [b])
    recent.add("config", [c])
    recent.add("logger", [a])                          # déjà présent : remonte en tête
    assert [e["paths"][0] for e in recent.entries] == [a, c, b]
    assert texts(menu)[:3] == ["&1  a.csv    (logger)", "&2  c.json    (configuration)",
                               "&3  b.h5    (oscilloscope)"]
    assert texts(menu)[-1] == "Effacer la liste"
    assert recent.last_dir == str(tmp_path)
    for i in range(15):
        recent.add("logger", files(tmp_path, f"f{i}.csv"))
    assert len(recent.entries) == MAX_RECENT and recent.entries[0]["paths"][0].endswith("f14.csv")
    menu.actions()[-1].trigger()                        # Effacer la liste
    assert recent.entries == [] and texts(menu) == ["Aucun fichier récent"]


def test_trigger_and_missing_file(qapp, tmp_path):
    menu = QtWidgets.QMenu()
    recent = RecentFilesController(menu, None, lambda: str(tmp_path))
    a, b = files(tmp_path, "a.csv", "b.csv")
    recent.add("logger", [a])
    recent.add("logger", [b])
    opened, missing = [], []
    recent.open_requested.connect(opened.append)
    recent.missing.connect(missing.append)
    menu.actions()[1].trigger()                         # a.csv
    assert opened == [{"kind": "logger", "paths": [a]}]
    os.remove(b)
    menu.actions()[0].trigger()                         # b.csv : disparu
    assert missing == [{"kind": "logger", "paths": [b]}]
    assert [e["paths"] for e in recent.entries] == [[a]]


def test_persistence_and_last_dir(qapp, tmp_path):
    ini = str(tmp_path / "s.ini")
    settings = QtCore.QSettings(ini, QtCore.QSettings.Format.IniFormat)
    recent = RecentFilesController(QtWidgets.QMenu(), settings, lambda: "/defaut")
    assert recent.last_dir == "/defaut"                 # rien encore chargé
    (a,) = files(tmp_path, "mesures/a.csv")
    (src,) = files(tmp_path, "scope/tek0000CH1.csv")
    recent.add("logger", [a])
    recent.add("scope", files(tmp_path, "scope/rec.h5"), visited=src)
    assert recent.last_dir == str(tmp_path / "scope")
    # nouvelle session
    again = RecentFilesController(QtWidgets.QMenu(),
                                  QtCore.QSettings(ini, QtCore.QSettings.Format.IniFormat),
                                  lambda: "/defaut")
    assert [e["kind"] for e in again.entries] == ["scope", "logger"]
    assert again.last_dir == str(tmp_path / "scope")
    # dossier supprimé : retour au dossier par défaut
    for name in os.listdir(tmp_path / "scope"):
        os.remove(tmp_path / "scope" / name)
    os.rmdir(tmp_path / "scope")
    assert again.last_dir == "/defaut"
