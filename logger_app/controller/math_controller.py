# controller/math_controller.py
"""
Voies calculées (MATH) : groupe « Voies calculées » de l'arbre des paramètres.

    [Ajouter une voie calculée]
    Voies et fonctions        aide : voies de la configuration, fonctions disponibles
    M1 - P_INV1
        Nom        P_INV1
        Formule    [V_PH1_INV1]*[I_PH1_INV1]
        Unité      (vide : déduite de la formule, ici W)
        Affichée   [x]
        État       ✓ W   |   ⚠ voie inconnue : [X] ...
        [Supprimer]

Chaque modification est appliquée tout de suite, pendant l'acquisition comme en
relecture : le moteur (model/math_channels.MathEngine) recompile les formules et le
graphique « Voies calculées » se met à jour à la trame suivante.
"""
from __future__ import annotations

import pyqtgraph.parametertree as ptree
from PyQt6 import QtCore

from model.config import LoggerConfig
from model.math_channels import (EXTRA_FUNCTIONS, MAX_MATH, MathDefinition, MathEngine,
                                 insertable_channels)

FUNCTIONS_HELP = (
    "Fonctions : sin cos tan exp log(népérien) log10 sqrt abs ; max min sum avg "
    "(1 argument : sur la trame) ; " +
    " ; ".join(f"{name} ({text})" for name, (_, text) in EXTRA_FUNCTIONS.items()) +
    ". Arguments séparés par « ; », voies entre crochets, time = temps (s).")


class MathController(QtCore.QObject):

    changed = QtCore.pyqtSignal()                  # formules ou voies calculées modifiées
    definitions_changed = QtCore.pyqtSignal(list)  # [dict] à garder dans la configuration

    def __init__(self, tree: ptree.ParameterTree, definitions: list[MathDefinition] = ()):
        super().__init__()
        self.engine = MathEngine()
        self._updating = False
        self._runtime_errors: dict[str, str] = {}
        self.params = ptree.Parameter.create(name="Voies calculées", type="group", children=[
            {"name": "Ajouter une voie calculée", "type": "action"},
            {"name": "Voies et fonctions", "type": "text", "readonly": True, "value": "",
             "expanded": False},
        ])
        tree.addParameters(self.params, showTop=True)
        self.params.child("Ajouter une voie calculée").sigActivated.connect(self.add)
        self.params.sigTreeStateChanged.connect(self._on_changed)
        self.set_definitions(list(definitions))

    # ------------------------------------------------------------------ définitions
    def _groups(self) -> list:
        return [c for c in self.params.children() if c.type() == "group"]

    def definitions(self) -> list[MathDefinition]:
        return [MathDefinition(name=g.child("Nom").value().strip(),
                               formula=g.child("Formule").value(),
                               unit=g.child("Unité").value().strip(),
                               enabled=g.child("Affichée").value())
                for g in self._groups()]

    def set_definitions(self, definitions: list[MathDefinition]):
        """Remplace toutes les voies calculées (configuration chargée)."""
        self._updating = True
        try:
            for group in self._groups():
                self.params.removeChild(group)
            for definition in definitions[:MAX_MATH]:
                self._add_group(definition)
        finally:
            self._updating = False
        self._apply()

    def add(self):
        if len(self._groups()) >= MAX_MATH:
            return
        used = {d.name for d in self.definitions()}
        n = next(i for i in range(1, MAX_MATH + 2) if f"M{i}" not in used)
        cfg = self.engine.cfg
        first = insertable_channels(cfg)[0] if cfg is not None else "time"
        self._updating = True
        try:
            group = self._add_group(MathDefinition(f"M{n}", first))
        finally:
            self._updating = False
        group.setOpts(expanded=True)
        self._apply()

    def _add_group(self, d: MathDefinition):
        index = len(self._groups())
        group = ptree.Parameter.create(name=f"math{id(d)}_{index}", type="group",
                                       title=d.name, children=[
            {"name": "Nom", "type": "str", "value": d.name},
            {"name": "Formule", "type": "str", "value": d.formula, "tip": FUNCTIONS_HELP},
            {"name": "Unité", "type": "str", "value": d.unit,
             "tip": "Vide : unité déduite de la formule (si les voies utilisées ont une unité)"},
            {"name": "Affichée", "type": "bool", "value": d.enabled},
            {"name": "État", "type": "str", "readonly": True, "value": ""},
            {"name": "Supprimer", "type": "action"},
        ])
        group.child("Supprimer").sigActivated.connect(lambda _=None, g=group: self.remove(g))
        self.params.addChild(group)
        return group

    def remove(self, group):
        self.params.removeChild(group)
        self._apply()

    # ------------------------------------------------------------------ configuration
    def set_config(self, cfg: LoggerConfig):
        """Configuration affichée (voies disponibles dans les formules)."""
        self.engine.set_config(cfg)
        self.params.child("Voies et fonctions").setValue(
            "Voies : " + "  ".join(insertable_channels(cfg)) + "\n"
            "Par numéro : A0…A14 (analogiques), L0…L15 (logiques).\n" + FUNCTIONS_HELP)
        self._refresh_states()
        self.changed.emit()

    def _on_changed(self, _param, changes):
        if self._updating:
            return
        kinds = {(param.name(), kind) for param, kind, _ in changes}
        relevant = {("Nom", "value"), ("Formule", "value"), ("Unité", "value"),
                    ("Affichée", "value")}
        if kinds & relevant:
            self._apply()

    def _apply(self):
        definitions = self.definitions()
        self.engine.set_definitions(definitions)
        self._runtime_errors = {}
        self._refresh_states()
        self.definitions_changed.emit([d.to_dict() for d in definitions])
        self.changed.emit()

    # ------------------------------------------------------------------ état
    def show_runtime_errors(self, errors: dict):
        """Erreurs de calcul sur la trame affichée (ex : division par zéro)."""
        if errors != self._runtime_errors:
            self._runtime_errors = dict(errors)
            self._refresh_states()

    def _refresh_states(self):
        self._updating = True
        try:
            for group, item in zip(self._groups(), self.engine.compiled):
                group.setOpts(title=item.name or "(sans nom)")
                if item.error:
                    state = f"⚠ {item.error}"
                elif item.name in self._runtime_errors:
                    state = f"⚠ {self._runtime_errors[item.name]}"
                else:
                    unit = item.unit or "sans unité"
                    state = f"✓ {unit}" + ("" if item.definition.enabled else " (masquée)")
                    if item.definition.unit and item.computed_unit and \
                            item.computed_unit != item.definition.unit:
                        state += f" — formule : {item.computed_unit}"
                    if item.unit_issues:
                        state += " — " + "; ".join(item.unit_issues)
                group.child("État").setValue(state)
                group.child("Unité").setOpts(
                    tip=f"Vide : unité déduite de la formule ({item.computed_unit or 'non déterminée'})")
        finally:
            self._updating = False
        self.params.child("Ajouter une voie calculée").setOpts(
            enabled=len(self._groups()) < MAX_MATH)
