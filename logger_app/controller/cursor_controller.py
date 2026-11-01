# controller/cursor_controller.py
"""
Curseurs de mesure, sur le modèle des « Cursors menu » du GLviewer (LinkedCursors) :

    Type : Aucun | Verticaux (t1, t2) | Horizontaux (y1, y2) | Verticaux + horizontaux

    - curseurs verticaux : deux lignes déplaçables, sur le panneau analogique et sur le
      panneau logique (positions liées). Les champs t1 / t2 du groupe « Curseurs » sont
      liés aux lignes dans les deux sens ; Δt et 1/Δt sont affichés. L'arborescence des
      voies donne la valeur de chaque voie en t1 et son Δy = y(t2) - y(t1) ;
    - curseurs horizontaux : deux niveaux y1 / y2 sur le panneau analogique, et Δy ;
    - « Mesures » : pour la voie de mesure (choisie dans le groupe ou en cliquant sur une
      voie de l'arborescence) : y(t1), y(t2), Δy, pente, min, max, crête-crête, moyenne,
      valeur efficace entre t1 et t2.

Les mesures suivent les trames (signal `redrawn` du graphique) et restent figées avec
l'affichage (bouton Figer).
"""
from __future__ import annotations

import pyqtgraph as pg
import pyqtgraph.parametertree as ptree
from PyQt6 import QtCore

from controller.graph_controller import LiveGraphController
from model import measures
from model.config import LoggerConfig

NONE = "(aucune)"
TYPES = ["Aucun", "Verticaux", "Horizontaux", "Verticaux + horizontaux"]
V_PEN = pg.mkPen("#e8b100", width=1.5)
H_PEN = pg.mkPen("#00b7c7", width=1.5)
LABEL_OPTS = {"position": 0.96, "color": (230, 230, 230), "fill": (40, 40, 40, 170),
              "movable": True}


class CursorController(QtCore.QObject):

    # valeurs en t1 et Δy par voie (clé -> float) ; None : curseurs verticaux masqués
    channel_values = QtCore.pyqtSignal(object, object)

    def __init__(self, graph: LiveGraphController, tree: ptree.ParameterTree):
        super().__init__()
        self.graph = graph
        self.cfg: LoggerConfig | None = None
        self._syncing = False

        self.params = ptree.Parameter.create(name="Curseurs", type="group", children=[
            {"name": "Type", "type": "list", "limits": TYPES, "value": "Aucun"},
            {"name": "Verticaux", "type": "group", "visible": False, "children": [
                {"name": "t1", "type": "float", "value": 0.0, "suffix": "s", "siPrefix": True,
                 "decimals": 6},
                {"name": "t2", "type": "float", "value": 0.0, "suffix": "s", "siPrefix": True,
                 "decimals": 6},
                {"name": "Δt", "type": "str", "readonly": True, "value": ""},
                {"name": "1/Δt", "type": "str", "readonly": True, "value": ""},
            ]},
            {"name": "Horizontaux", "type": "group", "visible": False, "children": [
                {"name": "y1", "type": "float", "value": 0.0, "decimals": 6},
                {"name": "y2", "type": "float", "value": 0.0, "decimals": 6},
                {"name": "Δy", "type": "str", "readonly": True, "value": ""},
            ]},
            {"name": "Voie de mesure", "type": "list", "limits": [NONE], "value": NONE},
            {"name": "Mesures", "type": "group", "visible": False, "children": [
                {"name": name, "type": "str", "readonly": True, "value": ""}
                for name in ("y(t1)", "y(t2)", "Δy", "Pente", "Min", "Max", "Crête-crête",
                             "Moyenne", "Efficace", "Échantillons")
            ]},
        ])
        tree.addParameters(self.params, showTop=True)
        self.params.sigTreeStateChanged.connect(self._on_params_changed)

        # curseurs verticaux : une paire sur chaque panneau, positions liées
        self.v_lines = {
            "analog": [self._line(90, V_PEN, label) for label in ("t1", "t2")],
            "logic": [self._line(90, V_PEN, None) for _ in range(2)],
        }
        self.h_lines = [self._line(0, H_PEN, label) for label in ("y1", "y2")]
        for panel, lines in self.v_lines.items():
            for i, line in enumerate(lines):
                line.sigPositionChanged.connect(
                    lambda ln, i=i, panel=panel: self._on_v_line_moved(panel, i, ln))
        for i, line in enumerate(self.h_lines):
            line.sigPositionChanged.connect(lambda ln, i=i: self._on_h_line_moved(i, ln))

        # résumé dans le coin du panneau analogique
        self.readout = pg.LabelItem(justify="left")
        self.readout.setParentItem(self.graph.analog_plot.vb)
        self.readout.anchor(itemPos=(0, 0), parentPos=(0, 0), offset=(8, 4))
        self.readout.hide()

        self.graph.redrawn.connect(self.refresh)

    @staticmethod
    def _line(angle, pen, label):
        opts = dict(angle=angle, movable=True, pen=pen,
                    hoverPen=pg.mkPen(pen.color(), width=3))
        if label:
            opts.update(label=label, labelOpts=LABEL_OPTS)
        return pg.InfiniteLine(**opts)

    def p(self, *path):
        return self.params.child(*path)

    # ------------------------------------------------------------------ état
    @property
    def vertical(self) -> bool:
        return self.p("Type").value() in ("Verticaux", "Verticaux + horizontaux")

    @property
    def horizontal(self) -> bool:
        return self.p("Type").value() in ("Horizontaux", "Verticaux + horizontaux")

    def set_type(self, kind: str):
        self.p("Type").setValue(kind)

    def set_vertical(self, t1: float, t2: float):
        with self.params.treeChangeBlocker():
            self.p("Verticaux", "t1").setValue(t1)
            self.p("Verticaux", "t2").setValue(t2)

    def set_horizontal(self, y1: float, y2: float):
        with self.params.treeChangeBlocker():
            self.p("Horizontaux", "y1").setValue(y1)
            self.p("Horizontaux", "y2").setValue(y2)

    # ------------------------------------------------------------------ configuration
    def configure(self, cfg: LoggerConfig):
        """Nouvelle configuration : bornes des curseurs, voie de mesure, panneaux."""
        self.cfg = cfg
        span = cfg.frame_duration
        for lines in self.v_lines.values():
            for line in lines:
                line.setBounds((0, span))
        t1, t2 = self.p("Verticaux", "t1").value(), self.p("Verticaux", "t2").value()
        if not (0 <= t1 <= span and 0 <= t2 <= span) or t1 == t2:
            self.set_vertical(0.25 * span, 0.75 * span)
        choices = {f"{s:2d}  {cfg.analog_name(s)}": s for s in cfg.analog_signals} or {NONE: None}
        selector = self.p("Voie de mesure")
        current = selector.value()
        selector.setLimits(choices)
        selector.setValue(current if current in choices.values()
                          else next(iter(choices.values())))
        self.p("Horizontaux", "y1").setOpts(suffix=self._unit())
        self.p("Horizontaux", "y2").setOpts(suffix=self._unit())
        self._place_lines()
        self.refresh()

    def select_channel(self, key):
        """Clic sur une voie de l'arborescence : elle devient la voie de mesure."""
        if self.cfg is not None and key[0] == "A" and key[1] in self.cfg.analog_signals:
            self.p("Voie de mesure").setValue(key[1])

    def _signal(self) -> int | None:
        """Voie de mesure (indice), None tant qu'aucune voie analogique n'est choisie."""
        sig = self.p("Voie de mesure").value()
        return sig if isinstance(sig, int) else None

    def _unit(self) -> str:
        sig = self._signal()
        return self.cfg.unit(sig) if self.cfg is not None and sig is not None else ""

    # ------------------------------------------------------------------ lignes <-> champs
    def _place_lines(self):
        """Affiche / masque les lignes et les place aux valeurs des champs."""
        self._syncing = True
        try:
            plots = {"analog": self.graph.analog_plot, "logic": self.graph.logic_plot}
            t = (self.p("Verticaux", "t1").value(), self.p("Verticaux", "t2").value())
            for panel, lines in self.v_lines.items():
                for line, value in zip(lines, t):
                    self._show(plots[panel], line, self.vertical)
                    line.setValue(value)
            y = (self.p("Horizontaux", "y1").value(), self.p("Horizontaux", "y2").value())
            for line, value in zip(self.h_lines, y):
                self._show(self.graph.analog_plot, line, self.horizontal)
                line.setValue(value)
        finally:
            self._syncing = False

    @staticmethod
    def _show(plot: pg.PlotItem, line: pg.InfiniteLine, show: bool):
        present = line in plot.items
        if show and not present:
            plot.addItem(line, ignoreBounds=True)
        elif not show and present:
            plot.removeItem(line)

    def _on_v_line_moved(self, panel, i, line):
        if self._syncing:
            return
        self._syncing = True
        try:
            value = line.value()
            for other, lines in self.v_lines.items():
                if other != panel:
                    lines[i].setValue(value)
            self.p("Verticaux", f"t{i + 1}").setValue(value)
        finally:
            self._syncing = False
        self.refresh()

    def _on_h_line_moved(self, i, line):
        if self._syncing:
            return
        self._syncing = True
        try:
            self.p("Horizontaux", f"y{i + 1}").setValue(line.value())
        finally:
            self._syncing = False
        self.refresh()

    def _on_params_changed(self, _param, changes):
        if self._syncing:
            return
        readonly = set(self.p("Mesures").children()) | {
            self.p("Verticaux", "Δt"), self.p("Verticaux", "1/Δt"), self.p("Horizontaux", "Δy")}
        names = {param.name() for param, kind, _ in changes
                 if kind == "value" and param not in readonly}
        if not names:
            return
        if "Type" in names:
            self._on_type_changed()
        if "Voie de mesure" in names:
            self.p("Horizontaux", "y1").setOpts(suffix=self._unit())
            self.p("Horizontaux", "y2").setOpts(suffix=self._unit())
        self._place_lines()
        self.refresh()

    def _on_type_changed(self):
        self.p("Verticaux").setOpts(visible=self.vertical)
        self.p("Horizontaux").setOpts(visible=self.horizontal)
        if self.horizontal and self.p("Horizontaux", "y1").value() == \
                self.p("Horizontaux", "y2").value():
            # première activation : niveaux au tiers et aux deux tiers de l'échelle affichée
            lo, hi = self.graph.analog_plot.vb.viewRange()[1]
            self.set_horizontal(lo + (hi - lo) / 3, lo + 2 * (hi - lo) / 3)

    # ------------------------------------------------------------------ mesures
    def refresh(self):
        """Recalcule les mesures (nouvelle trame, curseur déplacé, réglage modifié)."""
        t1, t2 = self.p("Verticaux", "t1").value(), self.p("Verticaux", "t2").value()
        y1, y2 = self.p("Horizontaux", "y1").value(), self.p("Horizontaux", "y2").value()
        unit = self._unit()
        lines = []
        with self.params.treeChangeBlocker():
            dt = t2 - t1
            self.p("Verticaux", "Δt").setValue(measures.si(dt, "s"))
            self.p("Verticaux", "1/Δt").setValue(measures.si(1 / dt, "Hz") if dt else "-")
            self.p("Horizontaux", "Δy").setValue(measures.si(y2 - y1, unit))
            if self.vertical:
                lines.append(f"Δt = {measures.si(dt, 's')} | 1/Δt = "
                             f"{measures.si(1 / dt, 'Hz') if dt else '-'}")
            if self.horizontal:
                lines.append(f"Δy (curseurs) = {measures.si(y2 - y1, unit)}")
            seg = self._segment(t1, t2)
            self.p("Mesures").setOpts(visible=self.vertical and seg is not None)
            if seg is not None:
                values = {
                    "y(t1)": seg.y1, "y(t2)": seg.y2, "Δy": seg.dy, "Min": seg.minimum,
                    "Max": seg.maximum, "Crête-crête": seg.peak_to_peak, "Moyenne": seg.mean,
                    "Efficace": seg.rms}
                for name, value in values.items():
                    self.p("Mesures", name).setValue(measures.si(value, unit))
                self.p("Mesures", "Pente").setValue(
                    measures.si(seg.slope, f"{unit}/s" if unit else "/s"))
                self.p("Mesures", "Échantillons").setValue(f"{seg.n}")
                if self.vertical:
                    name = self.cfg.analog_name(self._signal())
                    lines.append(f"{name} : Δy = {measures.si(seg.dy, unit)} | "
                                 f"crête-crête = {measures.si(seg.peak_to_peak, unit)} | "
                                 f"eff. = {measures.si(seg.rms, unit)}")
        self.readout.setText("<br>".join(lines), size="9pt")
        self.readout.setVisible(bool(lines))
        self._emit_channel_values(t1, t2)

    def _segment(self, t1, t2) -> measures.SegmentMeasures | None:
        frame = self.graph.frame
        sig = self._signal()
        if frame is None or sig not in frame.analog_signals:
            return None
        j = frame.analog_signals.index(sig)
        return measures.segment(frame.analog[:, j], frame.sample_rate, t1, t2)

    def _emit_channel_values(self, t1, t2):
        if not self.vertical:
            self.channel_values.emit(None, None)
            return
        frame = self.graph.frame
        if frame is None:
            self.channel_values.emit({}, {})
            return
        values = self.graph.values_at(t1)
        d = measures.deltas(frame.analog, frame.sample_rate, t1, t2)
        dys = {("A", s): float(v) for s, v in zip(frame.analog_signals, d)}
        if frame.logic is not None:
            dl = measures.deltas(frame.logic, frame.sample_rate, t1, t2)
            dys.update({("L", b): int(v) for b, v in enumerate(dl)})
        self.channel_values.emit(values, dys)
