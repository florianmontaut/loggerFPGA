# controller/scale_controller.py
"""
Groupe « Échelle de l'axe » de l'arbre des paramètres : réglage direct d'un axe
d'ordonnées du graphique des voies analogiques (controller/y_axes.py), en plus de la
molette et du glissement sur l'axe.

    Axe               axe réglé ; choisir une voie dans l'arborescence choisit son axe
    Automatique       axe ajusté à ses courbes
    Min / Max         plage, en unité de l'axe ; saisir une borne tient l'axe
    Graduation        pas des graduations principales (0 : automatique)
    Sous-graduations  intervalles entre deux graduations principales (0 : automatique)
    Grille            lignes horizontales aux graduations de l'axe (axe principal seul,
                      par défaut : toutes ensemble, les grilles sont illisibles)

Seulement pour les enregistrements d'oscilloscope pour l'instant (le groupe est masqué
pour le logger en temps réel).

Réglages rangés par clé d'axe (LiveGraphController.axis_key : voie seule, unité, axe
unique) : retrouvés quand les axes sont recréés (autre répartition) ou qu'un autre
enregistrement est ouvert. Graduations et grille sont gardées dans le projet ; les
plages le sont déjà, par voie, dans la disposition du projet.
"""
from __future__ import annotations

import pyqtgraph.parametertree as ptree
from PyQt6 import QtCore

NONE = "—"


class ScaleController(QtCore.QObject):

    def __init__(self, graph, tree: ptree.ParameterTree):
        super().__init__()
        self.graph = graph
        self.tree = tree
        # {clé d'axe : {"major", "minor", "grid" (None : défaut), "range" (plage tenue)}}
        self.settings: dict[str, dict] = {}
        self.group = 0                      # axe réglé
        self.enabled = False                # enregistrement d'oscilloscope affiché
        self._cfg = None                    # configuration des axes actuels
        self._loading = False               # arbre rempli par le programme

        self.params = ptree.Parameter.create(name="Échelle de l'axe", type="group",
                                             visible=False, children=[
            {"name": "Axe", "type": "list", "limits": [NONE], "value": NONE},
            {"name": "Automatique", "type": "bool", "value": True,
             "tip": "Axe ajusté à ses courbes ; décoché : l'axe garde sa plage"},
            {"name": "Min", "type": "float", "value": 0.0, "siPrefix": True,
             "decimals": 6, "tip": "Bas de l'axe ; saisi, il tient l'axe"},
            {"name": "Max", "type": "float", "value": 1.0, "siPrefix": True,
             "decimals": 6, "tip": "Haut de l'axe ; saisi, il tient l'axe"},
            {"name": "Graduation", "type": "float", "value": 0.0, "limits": (0, None),
             "siPrefix": True, "decimals": 6,
             "tip": "Pas des graduations principales (0 : automatique)"},
            {"name": "Sous-graduations", "type": "int", "value": 0, "limits": (0, 20),
             "tip": "Intervalles entre deux graduations principales (0 : automatique) ; "
                    "avec un pas de graduation choisi"},
            {"name": "Grille", "type": "bool", "value": True,
             "tip": "Lignes horizontales aux graduations de cet axe"},
        ])
        # en tête de l'arbre : c'est le réglage le plus utilisé en dépouillement
        item = self.params.makeTreeItem(depth=0)
        tree.invisibleRootItem().insertChild(0, item)
        item.treeWidgetChanged()
        for child in self.params:
            tree.addParameters(child, root=item, depth=1)
        item.setExpanded(True)
        self.params.sigTreeStateChanged.connect(self._on_params_changed)
        graph.axes_changed.connect(self._on_axes_rebuilt)
        graph.y_scales_changed.connect(self._on_ranges_changed)

    def p(self, name: str):
        return self.params.child(name)

    # ------------------------------------------------------------------ état
    def set_enabled(self, enabled: bool):
        """Groupe montré pour un enregistrement d'oscilloscope seulement."""
        self.enabled = enabled
        self.params.setOpts(visible=enabled)
        if enabled:
            self._fill()

    def select_channel(self, key):
        """Voie choisie dans l'arborescence : son axe devient l'axe réglé."""
        if key is None or key[0] != "A":
            return
        g = self.graph.axis_of(key[1])
        if g is not None:
            self.select_axis(g)

    def select_axis(self, g: int):
        if 0 <= g < len(self.graph.groups):
            self.group = g
            self._fill()

    def _settings(self, g: int) -> dict:
        return self.settings.setdefault(self.graph.axis_key(g),
                                        {"major": 0.0, "minor": 0, "grid": None})

    def _grid(self, g: int) -> bool:
        grid = self._settings(g)["grid"]
        return g == 0 if grid is None else bool(grid)

    # ------------------------------------------------------------------ axes
    def _on_axes_rebuilt(self, *_):
        """
        Axes recréés : graduations et grille retrouvées par clé ; pour une autre
        répartition des mêmes voies (même configuration), plages tenues aussi. Un autre
        enregistrement prend les plages de son projet (controller/project_controller.py).
        """
        same = self.graph.cfg is self._cfg
        self._cfg = self.graph.cfg
        self.set_enabled(self.graph.hold_scales)
        ranges = {}
        for g in range(len(self.graph.groups)):
            if not self.enabled:            # logger en temps réel : axes par défaut
                self.graph.set_axis_ticks(g)
                self.graph.set_axis_grid(g, g == 0)
                continue
            settings = self._settings(g)
            self.graph.set_axis_ticks(g, settings["major"], settings["minor"])
            self.graph.set_axis_grid(g, self._grid(g))
            if same and settings.get("range"):
                ranges[g] = settings["range"]
        if ranges:
            self.graph._set_axis_ranges(ranges)
        if self.group >= len(self.graph.groups):
            self.group = 0
        self._fill()

    def _on_ranges_changed(self):
        """Plage d'un axe changée (souris, programme) : réglages et arbre à jour."""
        graph = self.graph
        if not self.enabled:
            return
        for g in range(len(graph.groups)):
            settings = self._settings(g)
            if graph.axis_auto(g):
                settings.pop("range", None)
            else:
                settings["range"] = tuple(graph.axis_view(g).viewRange()[1])
        graph.refresh_ticks()
        self._fill(values_only=True)

    # ------------------------------------------------------------------ arbre
    def _fill(self, values_only: bool = False, ranges: bool = True):
        if not self.enabled or self._loading:
            return
        graph = self.graph
        if not graph.groups:
            return
        g = min(self.group, len(graph.groups) - 1)
        self._loading = True
        try:
            if not values_only:
                labels = {graph.axis_label(k): k for k in range(len(graph.groups))}
                self.p("Axe").setLimits(labels)
                self.p("Axe").setValue(g)
                unit = graph.axis_unit(g) or None
                for name in ("Min", "Max", "Graduation"):
                    self.p(name).setOpts(suffix=unit)
                settings = self._settings(g)
                self.p("Graduation").setValue(settings["major"])
                self.p("Sous-graduations").setValue(settings["minor"])
                self.p("Grille").setValue(self._grid(g))
            if ranges:
                lo, hi = graph.axis_view(g).viewRange()[1]
                self.p("Min").setValue(lo)
                self.p("Max").setValue(hi)
            self.p("Automatique").setValue(graph.axis_auto(g))
        finally:
            self._loading = False

    def _on_params_changed(self, _param, changes):
        if self._loading or not self.enabled or not self.graph.groups:
            return
        graph = self.graph
        pending = False                     # Min >= Max : saisie de l'autre borne attendue
        for param, change, value in changes:
            if change != "value":
                continue
            name = param.name()
            if name == "Axe":
                self.select_axis(int(value))
                continue
            g = min(self.group, len(graph.groups) - 1)
            settings = self._settings(g)
            if name == "Automatique":
                graph.set_axis_auto(g, bool(value))
            elif name in ("Min", "Max"):
                lo, hi = self.p("Min").value(), self.p("Max").value()
                if lo < hi:
                    graph.set_axis_range(g, lo, hi)
                    pending = False
                else:                       # bornes saisies laissées telles quelles
                    pending = True
            elif name in ("Graduation", "Sous-graduations"):
                settings["major"] = float(self.p("Graduation").value())
                settings["minor"] = int(self.p("Sous-graduations").value())
                graph.set_axis_ticks(g, settings["major"], settings["minor"])
            elif name == "Grille":
                settings["grid"] = bool(value)
                graph.set_axis_grid(g, bool(value))
        self._fill(values_only=True, ranges=not pending)

    # ------------------------------------------------------------------ tests, projet
    def set_scale(self, g: int, **values):
        """Réglage d'un axe comme depuis l'arbre (tests) : Min=..., Grille=..."""
        self.select_axis(g)
        for name, value in values.items():
            self.p(name.replace("_", "-")).setValue(value)

    def display_settings(self) -> dict:
        """Graduations et grille choisies, par clé d'axe (projet)."""
        return {key: {"major": s["major"], "minor": s["minor"], "grid": s["grid"]}
                for key, s in self.settings.items()
                if s["major"] or s["minor"] or s["grid"] is not None}

    def set_display_settings(self, values: dict):
        """Graduations et grille d'un projet (appliquées aux axes recréés ensuite)."""
        for key, value in values.items():
            settings = self.settings.setdefault(key, {"major": 0.0, "minor": 0, "grid": None})
            settings["major"] = float(value.get("major") or 0.0)
            settings["minor"] = int(value.get("minor") or 0)
            grid = value.get("grid")
            settings["grid"] = None if grid is None else bool(grid)
        if self.enabled and self.graph.groups:
            for g in range(len(self.graph.groups)):
                s = self._settings(g)
                self.graph.set_axis_ticks(g, s["major"], s["minor"])
                self.graph.set_axis_grid(g, self._grid(g))
            self._fill()
