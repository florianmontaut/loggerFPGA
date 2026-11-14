import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def pytest_addoption(parser):
    parser.addoption("--exe", action="store_true",
                     help="construit aussi l'exécutable et le lance (plusieurs minutes)")


def pytest_configure(config):
    config.addinivalue_line("markers", "exe: construit l'exécutable PyInstaller (--exe)")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--exe"):
        return
    skip = pytest.mark.skip(reason="exécutable : lancer avec --exe")
    for item in items:
        if "exe" in item.keywords:
            item.add_marker(skip)
