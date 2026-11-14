@echo off
rem Construit dist\LoggerFPGA.exe (un seul fichier). A lancer dans l'environnement Python
rem du projet, depuis ce dossier (pip install -r requirements-dev.txt).
python -m qtsocle.build main.py --name LoggerFPGA --icon ressources\icons\icon.ico --data ressources\icons
