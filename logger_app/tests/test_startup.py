"""Démarrage par main.py (qtsocle.app.run) et exécutable (python -m pytest --exe)."""
import os
import pathlib
import subprocess
import sys

import pytest
from qtsocle import app, build, paths

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _env(data_dir, **extra):
    env = dict(os.environ, **{app.ENV_SMOKE_TEST: "1", paths.ENV_DATA_DIR: str(data_dir)})
    env.update(extra)
    return env


def test_main_starts_and_closes(tmp_path):
    """Lancé hors du dossier du projet : démarre, se ferme, aucune erreur au journal."""
    data = tmp_path / "donnees"
    result = subprocess.run([sys.executable, str(ROOT / "main.py")], cwd=tmp_path,
                            env=_env(data, QT_QPA_PLATFORM="offscreen"),
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert data.is_dir() and not (data / "erreurs.log").exists()


def test_main_with_config_file(tmp_path):
    from model.config import LoggerConfig
    path = tmp_path / "config.json"
    LoggerConfig(ip_fpga="127.0.0.2", signals=[0, 1]).save(str(path))
    result = subprocess.run([sys.executable, str(ROOT / "main.py"), str(path)], cwd=tmp_path,
                            env=_env(tmp_path / "donnees", QT_QPA_PLATFORM="offscreen"),
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (tmp_path / "donnees" / "erreurs.log").exists()


def test_unexpected_error_is_logged(tmp_path, monkeypatch):
    """Erreur non prévue : écrite dans erreurs.log (un .exe sans console la perdrait)."""
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    log = tmp_path / "erreurs.log"
    app.install_excepthook("LoggerFPGA", log)
    try:
        raise RuntimeError("trame illisible")
    except RuntimeError:
        sys.excepthook(*sys.exc_info())
    assert "RuntimeError: trame illisible" in log.read_text(encoding="utf-8")


def test_icon_is_where_the_build_expects_it():
    assert (ROOT / "ressources" / "icons" / "icon.ico").is_file()
    script = (ROOT / "build_exe.bat").read_text(encoding="utf-8")
    assert "ressources\\icons\\icon.ico" in script and "--data ressources\\icons" in script


@pytest.mark.exe
def test_executable(tmp_path):
    """Exécutable en un seul fichier : démarre seul, hors du projet, sans erreur."""
    exe = build.build(ROOT / "main.py", "LoggerFPGA", icon="ressources/icons/icon.ico",
                      data=["ressources/icons"])
    assert exe.is_file()
    data = tmp_path / "donnees"
    env = _env(data)
    env.pop("PYTHONPATH", None)
    result = subprocess.run([str(exe)], cwd=tmp_path, env=env, timeout=180)
    assert result.returncode == 0
    assert not (data / "erreurs.log").exists(), (data / "erreurs.log").read_text("utf-8")
