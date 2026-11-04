# model/math_channels.py
"""
Voies calculées (« MATH » des oscilloscopes) : formules sur les voies de chaque trame,
évaluées en temps réel avec le moteur de formules du GLviewer (model/formula).

    P_INV1       = [V_PH1_INV1]*[I_PH1_INV1]
    I_moy        = movavg([I_HV]; 64)
    dV/dt        = deriv([V_HV])
    Commande ET  = [K_HV]*[K_PRE]

Désignation des voies (celles de la trame affichée) :
    [V_HV], [K_HV]      voie analogique ou logique par son nom (espaces admis)
    A0 ... A14          voie analogique par son numéro
    L0 ... L15          voie logique par son bit (0 ou 1)
    [P_INV1]            voie calculée définie plus haut dans la liste
    time                temps depuis le début de la trame (s)

Fonctions du GLviewer : sin cos tan exp log (népérien) log10 sqrt abs, max min sum avg
(1 argument : valeur sur la trame ; plusieurs : point par point), steps / interp (tables),
propriétés des caloporteurs. Arguments séparés par « ; ».
Ajoutées pour les signaux d'une trame (fréquence d'échantillonnage connue) :
    deriv(x)        dérivée (unité/s)
    integ(x)        intégrale depuis le début de la trame (unité.s)
    movavg(x; n)    moyenne glissante centrée sur n points
    rms(x)          valeur efficace sur la trame
    pkpk(x)         valeur crête-crête sur la trame
Un résultat scalaire (rms, max...) est tracé comme une droite horizontale.

L'unité est celle saisie, ou à défaut celle déduite de la formule (analyse dimensionnelle
du GLviewer : [V]*[A] donne W) quand les voies utilisées ont une unité.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np

from . import formula
from .config import LoggerConfig
from .formula import FormulaError, units
from .formula.interpreter import Interpreter
from .formula.nodes import FuncNode
from .protocol import Frame

TIME = "time"
MAX_MATH = 8

# nom -> (nombre d'arguments, description)
EXTRA_FUNCTIONS = {
    "deriv":  (1, "dérivée"),
    "integ":  (1, "intégrale depuis le début de la trame"),
    "movavg": (2, "moyenne glissante sur n points"),
    "rms":    (1, "valeur efficace sur la trame"),
    "pkpk":   (1, "valeur crête-crête sur la trame"),
}


@dataclass
class MathDefinition:
    name: str = "M1"
    formula: str = ""
    unit: str = ""              # vide : unité déduite de la formule
    enabled: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "MathDefinition":
        return cls(**{k: data[k] for k in ("name", "formula", "unit", "enabled") if k in data})


# ------------------------------------------------------------------ calcul

class FrameInterpreter(Interpreter):
    """Interpréteur du GLviewer + fonctions qui ont besoin de la fréquence d'échantillonnage."""

    def __init__(self, sample_rate: float):
        super().__init__()
        self.sample_rate = sample_rate

    def visit_FuncNode(self, node: FuncNode):
        name = node.func.lower()
        if name not in EXTRA_FUNCTIONS:
            return super().visit_FuncNode(node)
        arity, _ = EXTRA_FUNCTIONS[name]
        args = [self.visit(a).value for a in node.args]
        if len(args) != arity:
            raise FormulaError(f"La fonction '{name}' attend {arity} argument(s), "
                               f"{len(args)} donné(s)")
        if np.ndim(args[0]) == 0:
            raise FormulaError(f"La fonction '{name}' s'applique à une voie, pas à un nombre")
        fs = self.sample_rate
        if name == "deriv":
            fn = lambda x: np.gradient(x[0]) * fs
        elif name == "integ":
            fn = lambda x: np.concatenate(([0.0], np.cumsum((x[0][1:] + x[0][:-1]) / 2))) / fs
        elif name == "movavg":
            n = args[1]
            if np.ndim(n) != 0 or n < 1 or n != int(n):
                raise FormulaError("movavg(x; n) : n doit être un entier >= 1")
            n = int(n)
            kernel = np.ones(n)
            # bords : moyenne sur les seuls points disponibles
            fn = lambda x: (np.convolve(x[0], kernel, "same")
                            / np.convolve(np.ones_like(x[0]), kernel, "same"))
        elif name == "rms":
            fn = lambda x: np.sqrt(np.nanmean(np.square(x[0])))
        else:  # pkpk
            fn = lambda x: np.nanmax(x[0]) - np.nanmin(x[0])
        return self.compute(name, fn, args)


# ------------------------------------------------------------------ unités

class _FrameAnalyser(units._Analyser):
    """Analyse des unités du GLviewer + fonctions ajoutées et voies sans dimension."""

    def __init__(self, input_units: dict, dimensionless: set):
        super().__init__(input_units)
        self.dimensionless_keys = dimensionless

    def input_unit(self, key):
        if key in self.dimensionless_keys:
            return units.DIMENSIONLESS
        return super().input_unit(key)

    def product(self, a, b, divide):
        """Comme le GLviewer, avec une unité lisible : W (nom usuel), V², V·A, V/A..."""
        unit = super().product(a, b, divide)
        if (unit is None or unit.literal or unit.dimensionless or a.literal or b.literal
                or units._named_dims().get(unit.dims)):
            return unit
        ta = a.text or units.dims_text(a.dims)
        tb = b.text or units.dims_text(b.dims)
        if ta == tb and not divide:
            text = f"{ta}²" if not any(c in ta for c in "/·²") else f"({ta})²"
        else:
            wrap = lambda t: f"({t})" if any(c in t for c in "/·") else t
            text = f"{wrap(ta)}{'/' if divide else '·'}{wrap(tb)}"
        return units.Unit(unit.dims, text=text)

    def function(self, node):
        name = node.func.lower()
        if name not in EXTRA_FUNCTIONS:
            return super().function(node)
        arg = self.visit(node.args[0]) if node.args else None
        if arg is None:
            return None
        if name in ("deriv", "integ"):
            sign = -1 if name == "deriv" else 1
            dims = list(arg.dims)
            dims[units.BASE_SYMBOLS.index("s")] += sign
            dims = tuple(dims)
            if dims == units.NO_DIM:
                return units.Unit(dims)
            named = units._named_dims().get(dims)
            if named:                                       # A·s -> C
                text = named[0]
            elif arg.text or not arg.dimensionless:         # V -> V/s, V·s
                base = arg.text or units.dims_text(arg.dims)
                base = f"({base})" if any(c in base for c in "/·") else base
                text = f"{base}/s" if name == "deriv" else f"{base}·s"
            else:                                           # sans dimension
                text = "1/s" if name == "deriv" else "s"
            return units.Unit(dims, text=text)
        return arg if not arg.literal else units.DIMENSIONLESS


def analyse_units(tree, input_units: dict, dimensionless: set) -> units.UnitReport:
    analyser = _FrameAnalyser(input_units, dimensionless)
    unit = analyser.visit(tree)
    if unit is not None and unit.literal:
        unit = units.DIMENSIONLESS
    if analyser.issues:
        unit = None
    return units.UnitReport(unit, analyser.issues, analyser.notes)


def unit_text(unit) -> str:
    """Texte d'une unité calculée : symbole nommé (W, V...) si possible."""
    if unit is None or unit.dimensionless:
        return ""
    return unit.text or units.dims_text(unit.dims)


# ------------------------------------------------------------------ voies disponibles

def channel_keys(cfg: LoggerConfig) -> dict[str, tuple[str, int]]:
    """Clé de formule -> ("A", voie) / ("L", bit), pour les voies de la configuration."""
    keys = {}
    for s in cfg.analog_signals:
        keys[f"[{cfg.analog_name(s)}]"] = ("A", s)
        keys[f"A{s}"] = ("A", s)
    if cfg.has_logic:
        for b in range(16):
            keys[f"[{cfg.logic_name(b)}]"] = ("L", b)
            keys[f"L{b}"] = ("L", b)
    return keys


def insertable_channels(cfg: LoggerConfig) -> list[str]:
    """Textes à insérer dans une formule (aide de saisie)."""
    names = [f"[{cfg.analog_name(s)}]" for s in cfg.analog_signals]
    if cfg.has_logic:
        names += [f"[{cfg.logic_name(b)}]" for b in range(16)]
    return names + [TIME]


def _is_identifier(name: str) -> bool:
    return name.isidentifier() and name.isascii()


@dataclass
class CompiledMath:
    definition: MathDefinition
    tree: object = None
    error: str | None = None           # formule invalide (syntaxe, voie inconnue...)
    computed_unit: str = ""            # unité déduite de la formule
    unit_issues: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.tree is not None and self.error is None

    @property
    def name(self) -> str:
        return self.definition.name

    @property
    def unit(self) -> str:
        return self.definition.unit or self.computed_unit


class MathEngine:
    """
    Voies calculées d'une configuration : compilées une fois (à chaque changement de
    formule ou de configuration), évaluées pour chaque trame affichée. Les résultats sont
    gardés dans la trame (frame.meta) : un redessin ou un déplacement de curseur ne
    recalcule pas.
    """

    def __init__(self):
        self.definitions: list[MathDefinition] = []
        self.cfg: LoggerConfig | None = None
        self.compiled: list[CompiledMath] = []
        self.version = 0

    def set_definitions(self, definitions: list[MathDefinition]):
        self.definitions = [MathDefinition(**asdict(d)) for d in definitions][:MAX_MATH]
        self._compile()

    def set_config(self, cfg: LoggerConfig):
        self.cfg = cfg.copy()
        self._compile()

    @property
    def active(self) -> list[CompiledMath]:
        """Voies calculées affichées : activées et valides."""
        return [c for c in self.compiled if c.definition.enabled and c.ok]

    def _compile(self):
        self.version += 1
        self.compiled = []
        if self.cfg is None:
            return
        available = channel_keys(self.cfg)
        unit_of = {k: self.cfg.unit(v[1]) for k, v in available.items() if v[0] == "A"}
        dimensionless = {k for k, v in available.items() if v[0] == "L"}
        known = set(available) | {TIME}
        names = set()
        for definition in self.definitions:
            item = CompiledMath(definition)
            self.compiled.append(item)
            name = definition.name.strip()
            if not name:
                item.error = "nom vide"
                continue
            if name in names or f"[{name}]" in available:
                item.error = f"le nom « {name} » est déjà utilisé"
                continue
            names.add(name)
            if not definition.formula.strip():
                item.error = "formule vide"
                continue
            try:
                tree = formula.parse(definition.formula)
                used_names, used_channels = formula.references(tree)
            except FormulaError as exc:
                item.error = str(exc)
                continue
            unknown = sorted({f"[{c}]" for c in used_channels if f"[{c}]" not in known}
                             | {n for n in used_names if n not in known})
            if unknown:
                item.error = (f"voie inconnue : {', '.join(unknown)} "
                              f"(voies : {', '.join(insertable_channels(self.cfg))})")
                continue
            item.tree = tree
            report = analyse_units(tree, {**unit_of, TIME: "s"}, dimensionless)
            item.computed_unit = unit_text(report.unit)
            item.unit_issues = list(report.issues)
            # utilisable par les voies calculées suivantes
            if definition.enabled:
                known.add(f"[{name}]")
                unit_of[f"[{name}]"] = item.unit
                if _is_identifier(name):
                    known.add(name)
                    unit_of[name] = item.unit

    # ------------------------------------------------------------------ évaluation
    def inputs(self, frame: Frame) -> dict:
        cfg = self.cfg
        values = {TIME: frame.time()}
        for j, s in enumerate(frame.analog_signals):
            values[f"[{cfg.analog_name(s)}]"] = values[f"A{s}"] = frame.analog[:, j]
        if frame.logic is not None:
            for b in range(16):
                bit = frame.logic[:, b].astype(float)
                values[f"[{cfg.logic_name(b)}]"] = values[f"L{b}"] = bit
        return values

    def evaluate(self, frame: Frame) -> tuple[dict, dict]:
        """
        ({nom : tableau}, {nom : erreur}) des voies calculées actives pour cette trame
        (mis en cache dans la trame tant que les formules ne changent pas).
        """
        cached = frame.meta.get("math")
        if cached is not None and cached[0] == self.version:
            return cached[1], cached[2]
        results, errors = {}, {}
        if self.cfg is not None and list(frame.signals) == list(self.cfg.signals):
            values = self.inputs(frame)
            for item in self.active:
                try:
                    interpreter = FrameInterpreter(frame.sample_rate)
                    interpreter.vars.update(values)
                    value = interpreter.visit(item.tree).value
                except (FormulaError, ValueError, TypeError) as exc:
                    errors[item.name] = str(exc)
                    continue
                array = np.broadcast_to(np.asarray(value, dtype=float), (frame.n_samples,))
                results[item.name] = np.array(array)
                values[f"[{item.name}]"] = results[item.name]
                if _is_identifier(item.name):
                    values[item.name] = results[item.name]
        frame.meta["math"] = (self.version, results, errors)
        return results, errors


def definitions_from_config(cfg: LoggerConfig) -> list[MathDefinition]:
    return [MathDefinition.from_dict(d) for d in getattr(cfg, "math_channels", [])]
