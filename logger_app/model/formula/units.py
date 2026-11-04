# model/formula/units.py
"""
Analyse dimensionnelle des formules (homogénéité), pour la relecture :
    parse_unit("L/min")          -> Unit (dimensions SI + facteur vers le SI)
    analyse(tree, {"[T]": "°C"}) -> UnitReport : unité du résultat, incohérences, remarques
Seules les dimensions sont vérifiées : les nombres de la formule (/60, *1000...) n'ont pas
d'unité, le facteur d'échelle n'est donc pas suivi (les unités d'entrée hors SI sont
signalées à part). °C et K ont la même dimension : une différence de températures divisée
par une puissance donne des K/W.
"""
from dataclasses import dataclass, field
from fractions import Fraction

import numpy as np

from .nodes import (AddNode, AssignmentNode, ChannelNode, DivideNode, FuncNode, MinusNode,
                    MultiplyNode, NumberNode, PlusNode, PowerNode, SubtractNode, VariableNode)
from . import fluids, lut

# dimensions : exposants de (m, kg, s, A, K, mol)
BASE_SYMBOLS = ("m", "kg", "s", "A", "K", "mol")
NO_DIM = (Fraction(0),) * 6


def _dims(m=0, kg=0, s=0, A=0, K=0, mol=0):
    return tuple(Fraction(v) for v in (m, kg, s, A, K, mol))


@dataclass(frozen=True)
class Unit:
    dims: tuple
    scale: float = 1.0          # valeur SI = scale * valeur (L/min : 1e-3/60)
    text: str = ""              # unité affichée
    literal: bool = False       # nombre de la formule : s'ajoute à toute grandeur (T + 273.15)

    @property
    def dimensionless(self):
        return self.dims == NO_DIM


DIMENSIONLESS = Unit(NO_DIM)
LITERAL = Unit(NO_DIM, literal=True)

# symbole -> (dimensions, facteur vers le SI, préfixe autorisé)
_UNITS = {
    "m":    (_dims(m=1), 1.0, True),
    "g":    (_dims(kg=1), 1e-3, True),
    "t":    (_dims(kg=1), 1e3, False),
    "s":    (_dims(s=1), 1.0, True),
    "min":  (_dims(s=1), 60.0, False),
    "h":    (_dims(s=1), 3600.0, False),
    "A":    (_dims(A=1), 1.0, True),
    "K":    (_dims(K=1), 1.0, True),
    "°C":   (_dims(K=1), 1.0, False),
    "mol":  (_dims(mol=1), 1.0, True),
    "Hz":   (_dims(s=-1), 1.0, True),
    "N":    (_dims(m=1, kg=1, s=-2), 1.0, True),
    "Pa":   (_dims(m=-1, kg=1, s=-2), 1.0, True),
    "bar":  (_dims(m=-1, kg=1, s=-2), 1e5, True),
    "J":    (_dims(m=2, kg=1, s=-2), 1.0, True),
    "Wh":   (_dims(m=2, kg=1, s=-2), 3600.0, True),
    "W":    (_dims(m=2, kg=1, s=-3), 1.0, True),
    "VA":   (_dims(m=2, kg=1, s=-3), 1.0, True),
    "var":  (_dims(m=2, kg=1, s=-3), 1.0, True),
    "V":    (_dims(m=2, kg=1, s=-3, A=-1), 1.0, True),
    "Ω":    (_dims(m=2, kg=1, s=-3, A=-2), 1.0, True),
    "S":    (_dims(m=-2, kg=-1, s=3, A=2), 1.0, True),
    "C":    (_dims(s=1, A=1), 1.0, True),
    "F":    (_dims(m=-2, kg=-1, s=4, A=2), 1.0, True),
    "H":    (_dims(m=2, kg=1, s=-2, A=-2), 1.0, True),
    "T":    (_dims(kg=1, s=-2, A=-1), 1.0, True),
    "Wb":   (_dims(m=2, kg=1, s=-2, A=-1), 1.0, True),
    "L":    (_dims(m=3), 1e-3, True),
    "%":    (NO_DIM, 1e-2, False),
}
_PREFIXES = {"G": 1e9, "M": 1e6, "k": 1e3, "c": 1e-2, "m": 1e-3, "µ": 1e-6, "n": 1e-9}

# écritures courantes ramenées aux symboles ci-dessus
_ALIASES = {
    "degc": "°C", "deg c": "°C", "℃": "°C", "ºc": "°C", "�c": "°C",
    "ohm": "Ω", "ohms": "Ω", "Ω": "Ω", "l": "L", "u": "µ", "μ": "µ",
    "%rh": "%", "rh": "%", "sec": "s", "lpm": "L/min",
}

# unités nommées, pour l'affichage d'un produit ou d'un quotient (ordre : préférence)
NAMED = [
    ("W", "puissance"), ("J", "énergie"), ("V", "tension"), ("A", "courant"),
    ("Ω", "résistance électrique"), ("Pa", "pression"), ("N", "force"),
    ("K/W", "résistance thermique"), ("W/K", "conductance thermique"),
    ("W/(m·K)", "conductivité thermique"), ("W/(m²·K)", "coefficient d'échange"),
    ("W/m²", "densité de flux"), ("J/K", "capacité thermique"),
    ("J/(kg·K)", "capacité thermique massique"), ("J/kg", "énergie massique"),
    ("kg/m³", "masse volumique"), ("m³/s", "débit volumique"), ("kg/s", "débit massique"),
    ("Pa·s", "viscosité dynamique"), ("m²/s", "viscosité cinématique"),
    ("m/s", "vitesse"), ("K", "température"), ("s", "temps"), ("m", "longueur"),
    ("m²", "surface"), ("m³", "volume"), ("kg", "masse"), ("C", "charge"),
    ("F", "capacité"), ("H", "inductance"), ("Hz", "fréquence"), ("S", "conductance"),
]


class UnitError(ValueError):
    """Unité non reconnue."""


# ---------------- lecture d'une unité ----------------

_SUPERSCRIPTS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻", "0123456789-")
_SYMBOL_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ°%Ωµ")


def _normalise(text: str) -> str:
    text = text.strip()
    for alias, symbol in _ALIASES.items():
        if text.casefold() == alias:
            return symbol
    # °C, Ω, µ écrits autrement au milieu d'une unité composée (°C/W, uV)
    text = (text.replace("℃", "°C").replace("ºC", "°C").replace("�C", "°C")
            .replace("degC", "°C").replace("μ", "µ").replace("Ohm", "Ω").replace("ohm", "Ω"))
    return text


def _symbol(sym: str) -> tuple:
    """(dimensions, facteur) d'un symbole simple éventuellement préfixé (kW, mbar, µs)."""
    if sym in _UNITS:
        return _UNITS[sym][:2]
    alias = _ALIASES.get(sym.casefold())
    if alias in _UNITS:
        return _UNITS[alias][:2]
    prefix = "µ" if sym[:1] in ("u", "µ") else sym[:1]
    base = sym[1:]
    if prefix in _PREFIXES and base in _UNITS and _UNITS[base][2]:
        dims, factor, _ = _UNITS[base]
        return dims, factor * _PREFIXES[prefix]
    if base.casefold() in ("l", "ohm") and prefix in _PREFIXES:
        dims, factor, _ = _UNITS[_ALIASES[base.casefold()]]
        return dims, factor * _PREFIXES[prefix]
    raise UnitError(f"unité non reconnue « {sym} »")


class _UnitParser:
    # expr : factor (('*' | '·' | '.' | ' ' | '/') factor)*   ; factor : atom exposant?
    def __init__(self, text):
        self.text, self.pos = text, 0

    def peek(self):
        return self.text[self.pos] if self.pos < len(self.text) else None

    def parse(self):
        dims, scale = self.expr()
        if self.peek() is not None:
            raise UnitError(f"caractère inattendu « {self.peek()} »")
        return dims, scale

    def expr(self):
        dims, scale = self.factor()
        while self.peek() is not None and self.peek() in "*·./ ":
            divide = self.peek() == "/"
            self.pos += 1
            while self.peek() == " ":
                self.pos += 1
            other_dims, other_scale = self.factor()
            sign = -1 if divide else 1
            dims = tuple(a + sign * b for a, b in zip(dims, other_dims))
            scale = scale / other_scale if divide else scale * other_scale
        return dims, scale

    def factor(self):
        if self.peek() == "(":
            self.pos += 1
            dims, scale = self.expr()
            if self.peek() != ")":
                raise UnitError("« ) » manquante")
            self.pos += 1
        elif self.peek() == "1":            # 1/s
            self.pos += 1
            dims, scale = NO_DIM, 1.0
        else:
            start = self.pos
            while self.peek() is not None and self.peek() in _SYMBOL_CHARS:
                self.pos += 1
            if start == self.pos:
                raise UnitError(f"caractère inattendu « {self.peek() or 'fin'} »")
            dims, scale = _symbol(self.text[start:self.pos])
        power = self.exponent()
        return tuple(d * power for d in dims), scale ** float(power)

    def exponent(self):
        if self.peek() == "^":
            self.pos += 1
        start = self.pos
        if self.peek() == "-":
            self.pos += 1
        while self.peek() is not None and self.peek().isdigit():
            self.pos += 1
        digits = self.text[start:self.pos]
        if digits in ("", "-"):
            self.pos = start
            return Fraction(1)
        return Fraction(int(digits))


def parse_unit(text: str) -> Unit:
    """Unité d'une voie ou saisie (« °C », « L/min », « W/(m²·K) ») ; UnitError sinon."""
    text = (text or "").strip()
    if not text:
        raise UnitError("pas d'unité")
    normalised = _normalise(text).translate(_SUPERSCRIPTS)
    dims, scale = _UnitParser(normalised).parse()
    return Unit(dims, scale, text)


# ---------------- affichage ----------------

_NAMED_DIMS = None


def _named_dims():
    global _NAMED_DIMS
    if _NAMED_DIMS is None:
        _NAMED_DIMS = {}
        for symbol, quantity in NAMED:
            _NAMED_DIMS.setdefault(_UnitParser(symbol.translate(_SUPERSCRIPTS)).parse()[0],
                                   (symbol, quantity))
    return _NAMED_DIMS


def _power_text(symbol, power):
    if power == 1:
        return symbol
    sup = {2: "²", 3: "³"}.get(power)
    return symbol + (sup if sup else f"^{power}")


def dims_text(dims) -> str:
    """Unité SI d'un jeu de dimensions : nom usuel (K/W) ou unités de base (kg·m²·s⁻³)."""
    if dims == NO_DIM:
        return "sans dimension"
    named = _named_dims().get(dims)
    if named:
        return named[0]
    num = [_power_text(s, p) for s, p in zip(BASE_SYMBOLS, dims) if p > 0]
    den = [_power_text(s, -p) for s, p in zip(BASE_SYMBOLS, dims) if p < 0]
    text = "·".join(num) or "1"
    if den:
        text += "/" + (den[0] if len(den) == 1 else "(" + "·".join(den) + ")")
    return text


def quantity(dims) -> str:
    """Grandeur physique usuelle (« résistance thermique ») ou ""."""
    named = _named_dims().get(dims)
    return named[1] if named else ""


def describe(unit: Unit) -> str:
    """« K/W (résistance thermique) », « °C (température) »."""
    text = unit.text or dims_text(unit.dims)
    name = quantity(unit.dims)
    return f"{text} ({name})" if name else text


def same_dimension(text: str, unit: Unit) -> bool | None:
    """L'unité saisie text a-t-elle la dimension de unit ? None si text est illisible."""
    try:
        return parse_unit(text).dims == unit.dims
    except UnitError:
        return None


# ---------------- analyse d'une formule ----------------

@dataclass
class UnitReport:
    unit: Unit | None                               # None : unité non déterminée
    issues: list = field(default_factory=list)      # incohérences (formule à relire)
    notes: list = field(default_factory=list)       # remarques (unité inconnue, hors SI)


_SAME_UNIT_FUNCS = ("abs", "max", "min", "sum", "avg")
_DIMENSIONLESS_FUNCS = ("sin", "cos", "tan", "exp", "log", "log10")


class _Analyser:
    def __init__(self, units: dict):
        self.units = units
        self.issues, self.notes = [], []
        self.parsed = {}

    def note(self, text):
        if text not in self.notes:
            self.notes.append(text)

    def issue(self, text):
        if text not in self.issues:
            self.issues.append(text)

    def input_unit(self, key):
        if key in self.parsed:
            return self.parsed[key]
        text = (self.units.get(key) or "").strip()
        unit = None
        if not text:
            self.note(f"{key} n'a pas d'unité : unité du résultat non déterminée")
        else:
            try:
                unit = parse_unit(text)
            except UnitError:
                self.note(f"unité « {text} » de {key} non reconnue : unité du résultat "
                          f"non déterminée")
            else:
                if unit.scale != 1 and not unit.dimensionless:
                    self.note(f"{key} est en {text}, hors SI : 1 {text} = {unit.scale:.4g} "
                              f"{dims_text(unit.dims)}")
        self.parsed[key] = unit
        return unit

    def visit(self, node):
        if isinstance(node, NumberNode):
            return LITERAL
        if isinstance(node, VariableNode):
            if node.name in ("pi", "e"):
                return LITERAL
            if node.name == "time":
                return Unit(_dims(s=1), text="s")
            return self.input_unit(node.name)
        if isinstance(node, ChannelNode):
            return self.input_unit(f"[{node.name}]")
        if isinstance(node, AssignmentNode):
            return self.visit(node.expr)
        if isinstance(node, (PlusNode, MinusNode)):
            return self.visit(node.node)
        if isinstance(node, (AddNode, SubtractNode)):
            op = "+" if isinstance(node, AddNode) else "-"
            return self.same(op, [self.visit(node.node_a), self.visit(node.node_b)])
        if isinstance(node, (MultiplyNode, DivideNode)):
            return self.product(self.visit(node.node_a), self.visit(node.node_b),
                                isinstance(node, DivideNode))
        if isinstance(node, PowerNode):
            return self.power(node)
        if isinstance(node, FuncNode):
            return self.function(node)
        return None

    def same(self, op, units):
        """Somme, différence, max... : grandeurs de même dimension (les nombres s'ajoutent)."""
        if any(u is None for u in units):
            return None
        measured = [u for u in units if not u.literal]
        if not measured:
            return LITERAL
        first = measured[0]
        for other in measured[1:]:
            if other.dims != first.dims:
                self.issue(f"{op} entre {describe(first)} et {describe(other)} : "
                           f"unités incompatibles")
                return None
        return first

    def product(self, a, b, divide):
        if a is None or b is None:
            return None
        if b.literal and b.dimensionless:
            return a
        if a.literal and a.dimensionless and not divide:
            return b
        sign = -1 if divide else 1
        dims = tuple(x + sign * y for x, y in zip(a.dims, b.dims))
        return Unit(dims, text="" if dims == NO_DIM else dims_text(dims))

    def power(self, node):
        base, exponent = self.visit(node.node_a), self.visit(node.node_b)
        if base is None:
            return None
        if exponent is not None and not exponent.dimensionless:
            self.issue(f"exposant avec unité ({describe(exponent)})")
            return None
        if base.dimensionless:
            return DIMENSIONLESS if not base.literal else LITERAL
        value = _constant(node.node_b)
        if value is None:
            self.issue(f"puissance non constante d'une grandeur ({describe(base)})")
            return None
        power = Fraction(value).limit_denominator(12)
        dims = tuple(d * power for d in base.dims)
        return Unit(dims, text=dims_text(dims))

    def function(self, node):
        name = node.func.lower()
        args = [self.visit(a) for a in node.args]
        if name in ("pi", "e") and not args:
            return LITERAL
        if name in fluids.PROPERTIES:
            prop = fluids.PROPERTIES[name]
            if args and args[0] is not None and not args[0].literal \
                    and args[0].dims != _dims(K=1):
                self.issue(f"{name} attend une température en °C, pas {describe(args[0])}")
            return parse_unit(prop.unit)
        if name in lut.LUT_FUNCTIONS:
            self.note(f"{name}(...) : la table n'a pas d'unité, unité du résultat "
                      f"non déterminée")
            return None
        if name in _SAME_UNIT_FUNCS:
            return self.same(f"{name}(...)", args) if args else None
        if name == "sqrt" and args:
            if args[0] is None:
                return None
            dims = tuple(d / 2 for d in args[0].dims)
            return args[0] if args[0].dimensionless else Unit(dims, text=dims_text(dims))
        if name in _DIMENSIONLESS_FUNCS and args:
            if args[0] is not None and not args[0].dimensionless:
                self.issue(f"{name} d'une grandeur avec unité ({describe(args[0])})")
            return DIMENSIONLESS
        return None


def _constant(node):
    """Valeur d'une expression sans voie (exposant) ; None sinon."""
    from . import evaluate, references
    names, channels = references(node)
    if channels or names - {"pi", "e"}:
        return None
    try:
        value = evaluate(node, {})
    except ValueError:
        return None
    return float(value) if np.ndim(value) == 0 and np.isfinite(value) else None


def analyse(tree, units: dict) -> UnitReport:
    """
    Unité du résultat de la formule.
    Args:
        units : {clé de la formule : unité} ; « [T AMB] » ou identifiant (CH3)
    """
    analyser = _Analyser(units)
    unit = analyser.visit(tree)
    if unit is not None and unit.literal:
        unit = DIMENSIONLESS
    if analyser.issues:
        unit = None
    return UnitReport(unit, analyser.issues, analyser.notes)
