# controller/config_controller.py
"""
Paramètres du logger dans un ParameterTree (comme l'arbre des paramètres du GLviewer).

Le contrôleur fait le lien entre l'arbre et LoggerConfig :
    - to_config() : lit l'arbre et renvoie une configuration validée (ou ConfigError) ;
    - set_config() : remplit l'arbre ;
    - choix de la « voie de seuil » : la voie est déplacée en première position de la liste
      des voies (le FPGA compare la première voie au seuil, voir logger.m) ;
    - grandeurs dérivées affichées en lecture seule (fréquence, durée de trame, seuil en
      valeur physique).
"""
from __future__ import annotations

import pyqtgraph.parametertree as ptree
from PyQt6 import QtCore

from model.config import (LOGIC_SIGNAL, TRIGGER_LABELS, VALID_CHANNEL_COUNTS, ConfigError,
                          LoggerConfig, TriggerType)

NONE = "(aucune)"


class ConfigController(QtCore.QObject):

    config_changed = QtCore.pyqtSignal(object)     # LoggerConfig valide
    invalid = QtCore.pyqtSignal(str)

    def __init__(self, tree: ptree.ParameterTree, cfg: LoggerConfig):
        super().__init__()
        self.tree = tree
        self.cfg = cfg.copy()
        self._updating = False
        self.params = ptree.Parameter.create(name="Logger", type="group",
                                             children=self._structure(self.cfg))
        self.tree.setParameters(self.params, showTop=False)
        self.params.sigTreeStateChanged.connect(self._on_changed)
        self.set_config(self.cfg)

    # ------------------------------------------------------------------ structure
    def _signal_limits(self, cfg: LoggerConfig, logic: bool) -> dict:
        limits = {f"{s:2d}  {cfg.analog_name(s)}": s for s in range(15)}
        if logic:
            limits[f"15  Voies logiques"] = LOGIC_SIGNAL
        return limits

    def _structure(self, cfg: LoggerConfig) -> list:
        channels = [{"name": "Nombre de voies", "type": "list",
                     "limits": list(VALID_CHANNEL_COUNTS), "value": 1}]
        for i in range(8):
            channels.append({"name": f"Voie {i + 1}", "type": "list",
                             "limits": self._signal_limits(cfg, logic=True), "value": 0})
        descriptions = [{"name": f"{s:2d}", "type": "group", "expanded": False,
                         "title": f"{s:2d}  {cfg.analog_name(s)}", "children": [
                             {"name": "Nom", "type": "str", "value": cfg.analog_name(s)},
                             {"name": "Gain (valeur à 1 pu)", "type": "float",
                              "value": cfg.gain(s)},
                             {"name": "Unité", "type": "str", "value": cfg.unit(s)}]}
                        for s in range(15)]
        return [
            {"name": "Liaison", "type": "group", "children": [
                {"name": "IP du FPGA", "type": "str", "value": cfg.ip_fpga},
                {"name": "Port de commande", "type": "int", "limits": (1, 65535),
                 "value": cfg.port_cmd},
                {"name": "Port du logger", "type": "int", "limits": (1, 65535),
                 "value": cfg.port_fpga},
                {"name": "IP locale", "type": "str", "value": cfg.local_ip,
                 "tip": "Vide : toutes les interfaces"},
                {"name": "Port local", "type": "int", "limits": (1, 65535),
                 "value": cfg.local_port},
            ]},
            {"name": "Voies", "type": "group", "children": channels},
            {"name": "Échantillonnage", "type": "group", "children": [
                {"name": "Diviseur", "type": "int", "limits": (1, 65535), "value": cfg.divider,
                 "tip": "Fréquence d'échantillonnage = 25 MHz / diviseur"},
                {"name": "Fréquence", "type": "str", "readonly": True, "value": ""},
                {"name": "Durée d'une trame", "type": "str", "readonly": True, "value": ""},
                {"name": "Délai", "type": "int", "limits": (0, 65535), "value": cfg.delay},
            ]},
            {"name": "Trigger", "type": "group", "children": [
                {"name": "Type", "type": "list",
                 "limits": {label: int(t) for t, label in TRIGGER_LABELS.items()},
                 "value": int(cfg.trigger)},
                {"name": "Voie de seuil", "type": "list", "limits": [NONE], "value": NONE,
                 "tip": "Voie comparée au seuil : elle est placée en tête de la liste des voies"},
                {"name": "Seuil (brut)", "type": "int", "limits": (-32768, 32767),
                 "value": cfg.threshold},
                {"name": "Seuil (physique)", "type": "float", "value": 0.0,
                 "tip": "Seuil en valeur physique (gain de la voie de seuil)"},
                {"name": "Masque disjonction", "type": "str",
                 "value": f"0x{cfg.trip_mask:08X}"},
            ]},
            {"name": "Acquisition", "type": "group", "children": [
                {"name": "Nombre de trames", "type": "int", "limits": (0, 10**9),
                 "value": cfg.max_frames, "tip": "0 : acquisition continue"},
            ]},
            {"name": "Enregistrement", "type": "group", "children": [
                {"name": "Dossier", "type": "file", "fileMode": "Directory",
                 "value": cfg.record_dir},
                {"name": "Préfixe", "type": "str", "value": cfg.record_prefix},
                {"name": "Format", "type": "list", "limits": ["csv", "npz"],
                 "value": cfg.record_format},
            ]},
            {"name": "Description des voies", "type": "group", "expanded": False,
             "children": descriptions},
        ]

    # ------------------------------------------------------------------ arbre <-> config
    def p(self, *path):
        return self.params.child(*path)

    def set_config(self, cfg: LoggerConfig):
        self._updating = True
        try:
            with self.params.treeChangeBlocker():
                self.p("Liaison", "IP du FPGA").setValue(cfg.ip_fpga)
                self.p("Liaison", "Port de commande").setValue(cfg.port_cmd)
                self.p("Liaison", "Port du logger").setValue(cfg.port_fpga)
                self.p("Liaison", "IP locale").setValue(cfg.local_ip)
                self.p("Liaison", "Port local").setValue(cfg.local_port)
                for s in range(15):
                    group = self.p("Description des voies", f"{s:2d}")
                    group.child("Nom").setValue(cfg.analog_name(s))
                    group.child("Gain (valeur à 1 pu)").setValue(cfg.gain(s))
                    group.child("Unité").setValue(cfg.unit(s))
                self.p("Voies", "Nombre de voies").setValue(cfg.n_channels)
                for i in range(8):
                    self.p("Voies", f"Voie {i + 1}").setLimits(
                        self._signal_limits(cfg, logic=(i == cfg.n_channels - 1)))
                    if i < cfg.n_channels:
                        self.p("Voies", f"Voie {i + 1}").setValue(cfg.signals[i])
                self.p("Échantillonnage", "Diviseur").setValue(cfg.divider)
                self.p("Échantillonnage", "Délai").setValue(cfg.delay)
                self.p("Trigger", "Type").setValue(int(cfg.trigger))
                self.p("Trigger", "Seuil (brut)").setValue(cfg.threshold)
                self.p("Trigger", "Masque disjonction").setValue(f"0x{cfg.trip_mask:08X}")
                self.p("Acquisition", "Nombre de trames").setValue(cfg.max_frames)
                self.p("Enregistrement", "Dossier").setValue(cfg.record_dir)
                self.p("Enregistrement", "Préfixe").setValue(cfg.record_prefix)
                self.p("Enregistrement", "Format").setValue(cfg.record_format)
            self.cfg = cfg.copy()
            self._refresh_derived(cfg)
        finally:
            self._updating = False

    def read_tree(self) -> LoggerConfig:
        """Configuration lue dans l'arbre, sans validation."""
        cfg = self.cfg.copy()
        cfg.ip_fpga = self.p("Liaison", "IP du FPGA").value().strip()
        cfg.port_cmd = self.p("Liaison", "Port de commande").value()
        cfg.port_fpga = self.p("Liaison", "Port du logger").value()
        cfg.local_ip = self.p("Liaison", "IP locale").value().strip()
        cfg.local_port = self.p("Liaison", "Port local").value()
        n = self.p("Voies", "Nombre de voies").value()
        cfg.signals = [self.p("Voies", f"Voie {i + 1}").value() for i in range(n)]
        cfg.divider = self.p("Échantillonnage", "Diviseur").value()
        cfg.delay = self.p("Échantillonnage", "Délai").value()
        cfg.trigger = self.p("Trigger", "Type").value()
        cfg.threshold = self.p("Trigger", "Seuil (brut)").value()
        mask = self.p("Trigger", "Masque disjonction").value().strip()
        try:
            cfg.trip_mask = int(mask, 16)
        except ValueError:
            raise ConfigError(f"Masque de disjonction invalide : {mask}") from None
        cfg.max_frames = self.p("Acquisition", "Nombre de trames").value()
        cfg.record_dir = self.p("Enregistrement", "Dossier").value() or "."
        cfg.record_prefix = self.p("Enregistrement", "Préfixe").value()
        cfg.record_format = self.p("Enregistrement", "Format").value()
        cfg.analog_names, cfg.gains, cfg.units = [], [], []
        for s in range(15):
            group = self.p("Description des voies", f"{s:2d}")
            cfg.analog_names.append(group.child("Nom").value())
            cfg.gains.append(group.child("Gain (valeur à 1 pu)").value())
            cfg.units.append(group.child("Unité").value())
        return cfg

    def to_config(self) -> LoggerConfig:
        cfg = self.read_tree()
        cfg.validate()
        return cfg

    # ------------------------------------------------------------------ réactions
    def _on_changed(self, _param, changes):
        if self._updating:
            return
        names = {change[0].name() for change in changes}
        try:
            cfg = self.read_tree()
            if "Voie de seuil" in names:
                choice = self.p("Trigger", "Voie de seuil").value()
                if choice != NONE:
                    cfg.set_threshold_signal(int(choice.split()[0]))
                    self.set_config(cfg)
            elif "Seuil (physique)" in names:
                cfg.threshold = cfg.threshold_from_physical(
                    self.p("Trigger", "Seuil (physique)").value())
                self.set_config(cfg)
            cfg.validate()
        except ConfigError as exc:
            self._refresh_derived(None)
            self.invalid.emit(str(exc))
            return
        self.cfg = cfg
        self._refresh_derived(cfg)
        self.config_changed.emit(cfg.copy())

    def _refresh_derived(self, cfg: LoggerConfig | None):
        """Visibilité des voies, voie de seuil, fréquence, seuil physique."""
        self._updating, was = True, self._updating
        try:
            if cfg is None:
                try:
                    cfg = self.read_tree()
                except ConfigError:
                    return
            n = cfg.n_channels
            for i in range(8):
                param = self.p("Voies", f"Voie {i + 1}")
                param.setOpts(visible=i < n)
                # la voie logique n'est proposée qu'en dernière position
                param.setLimits(self._signal_limits(cfg, logic=(i == n - 1)))
            if cfg.sample_rate:
                self.p("Échantillonnage", "Fréquence").setValue(_si(cfg.sample_rate, "Hz"))
                self.p("Échantillonnage", "Durée d'une trame").setValue(
                    f"{_si(cfg.frame_duration, 's')}  ({cfg.samples_per_channel} points/voie)")
            trig = cfg.trigger_type if cfg.trigger in TriggerType._value2member_map_ else None
            on_threshold = trig in (TriggerType.ABOVE, TriggerType.BELOW)
            choices = [f"{s:2d}  {cfg.analog_name(s)}" for s in cfg.analog_signals] or [NONE]
            sel = self.p("Trigger", "Voie de seuil")
            sel.setLimits(choices)
            sel.setValue(choices[0] if cfg.threshold_signal is not None else NONE)
            for name in ("Voie de seuil", "Seuil (brut)", "Seuil (physique)"):
                self.p("Trigger", name).setOpts(visible=on_threshold)
            self.p("Trigger", "Masque disjonction").setOpts(visible=trig == TriggerType.TRIP)
            phys = cfg.threshold_physical()
            if phys is not None:
                self.p("Trigger", "Seuil (physique)").setValue(phys)
        finally:
            self._updating = was


def _si(value: float, unit: str) -> str:
    for factor, prefix in ((1e6, "M"), (1e3, "k"), (1, ""), (1e-3, "m"), (1e-6, "µ")):
        if abs(value) >= factor:
            return f"{value / factor:.6g} {prefix}{unit}"
    return f"{value:.6g} {unit}"
