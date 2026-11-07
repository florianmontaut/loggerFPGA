# model/pattern.py
"""
Export d'un motif : table (temps, valeur) d'une voie sur une zone, à copier-coller dans un
logiciel de simulation (PLECS, PSPICE, LTspice...) ou un tableur.

    select(t, y, t0, t1, max_points) -> Pattern
        échantillons de [t0, t1], décimés (1 point sur N) pour ne pas dépasser max_points ;
        le premier et le dernier échantillon de la zone sont toujours gardés
    format_pattern(pattern, fmt, ...) -> texte

Formats :
    Colonnes (tabulation)   t<TAB>y par ligne, en-tête : tableur, PLECS (copier-coller)
    CSV (;)                 t;y par ligne, en-tête
    PWL (PSPICE, LTspice)   « t y » par ligne, sans en-tête : source PWL(file=...)
    Vecteurs (PLECS, MATLAB) t = [...]; y = [...];  : champs d'une 1D Look-Up Table
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

MAX_POINTS = 2000
FORMATS = ("Colonnes (tabulation)", "CSV (;)", "PWL (PSPICE, LTspice)",
           "Vecteurs (PLECS, MATLAB)")


@dataclass
class Pattern:
    t: np.ndarray                 # instants des points exportés (s)
    y: np.ndarray                 # valeurs
    step: int                     # 1 point sur `step`
    zone_points: int              # échantillons dans la zone, avant décimation
    t_start: float                # premier instant de la zone (origine du temps relatif)

    @property
    def points(self) -> int:
        return int(self.t.size)


def decimation_step(n: int, max_points: int) -> int:
    """Pas de décimation : au plus max_points points, dernier point compris."""
    if n <= max_points:
        return 1
    # n points -> ceil((n - 1) / step) + 1 points (dernier ajouté s'il manque)
    return max(1, math.ceil((n - 1) / (max_points - 1)))


def select(t: np.ndarray, y: np.ndarray, t0: float, t1: float,
           max_points: int = MAX_POINTS) -> Pattern:
    """
    Échantillons de [t0, t1] (bornes comprises, à une demi-période près), décimés à
    max_points au plus.
    """
    if max_points < 2:
        raise ValueError("Au moins 2 points")
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    lo, hi = min(t0, t1), max(t0, t1)
    # bornes à une demi-période près : une borne posée sur un échantillon le garde
    # malgré les arrondis du calcul des temps (comme l'échantillon le plus proche des
    # curseurs)
    tol = 0.5 * (t[-1] - t[0]) / (t.size - 1) if t.size > 1 else 0.0
    i0 = int(np.searchsorted(t, lo - tol, side="left"))
    i1 = int(np.searchsorted(t, hi + tol, side="left")) - 1
    if i1 < i0:
        empty = np.empty(0)
        return Pattern(empty, empty, 1, 0, lo)
    n = i1 - i0 + 1
    step = decimation_step(n, max_points)
    index = np.arange(i0, i1 + 1, step)
    if index[-1] != i1:
        index = np.append(index, i1)              # dernier échantillon de la zone
    return Pattern(t[index], y[index], step, n, float(t[i0]))


def _number(value: float, decimal_comma: bool, digits: int) -> str:
    text = f"{value:.{digits}g}"
    return text.replace(".", ",") if decimal_comma else text


def format_pattern(pattern: Pattern, fmt: str = FORMATS[0], name: str = "y",
                   unit: str = "", relative: bool = True,
                   decimal_comma: bool = False) -> str:
    """
    Texte du motif. relative : temps compté depuis le début de la zone (un motif
    commence à 0 dans un simulateur). decimal_comma : virgule décimale (tableur
    français) ; sans effet sur PWL et Vecteurs, qui exigent le point.
    """
    if fmt not in FORMATS:
        raise ValueError(f"Format inconnu : {fmt}")
    t = pattern.t - pattern.t_start if relative else pattern.t
    comma = decimal_comma and fmt in FORMATS[:2]
    ts = [_number(v, comma, 10) for v in t]
    ys = [_number(v, comma, 8) for v in pattern.y]
    label = f"{name} ({unit})" if unit else name
    if fmt == FORMATS[0]:
        return "\n".join([f"t (s)\t{label}"] + [f"{a}\t{b}" for a, b in zip(ts, ys)]) + "\n"
    if fmt == FORMATS[1]:
        return "\n".join([f"t (s);{label}"] + [f"{a};{b}" for a, b in zip(ts, ys)]) + "\n"
    if fmt == FORMATS[2]:
        return "\n".join(f"{a} {b}" for a, b in zip(ts, ys)) + "\n"
    var = "".join(c if c.isalnum() else "_" for c in name) or "y"
    if var[0].isdigit():
        var = "y_" + var
    return (f"t = [{' '.join(ts)}];\n"
            f"{var} = [{' '.join(ys)}];\n")
