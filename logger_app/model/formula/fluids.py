# model/formula/fluids.py
"""
Propriétés des caloporteurs dans les formules, en fonction de la température en °C
(scalaire ou voie) :
    rho_water(T)  masse volumique (kg/m³)       rho_air(T)
    cp_water(T)   capacité thermique massique (J/(kg·K))   cp_air(T)
    k_water(T)    conductivité thermique (W/(m·K))         k_air(T)
    mu_water(T)   viscosité dynamique (Pa·s)               mu_air(T)
Eau liquide à pression atmosphérique (0 à 100 °C), air sec à 101 325 Pa (-73 à 226 °C) :
interpolation linéaire des tables ; hors plage, valeur manquante (nan).
Ex : puissance absorbée par une plaque froide, débit en L/min :
    [Débit]/60000*rho_water([T entrée])*cp_water([T entrée])*([T sortie]-[T entrée])
"""
from dataclasses import dataclass

import numpy as np

from .errors import FormulaError

# eau liquide, 1 atm : T (°C), ρ (kg/m³), cp (J/(kg·K)), k (W/(m·K)), μ (mPa·s)
_WATER = np.array([
    (0,   999.84, 4219.9, 0.5610, 1.7914),
    (10,  999.70, 4195.5, 0.5800, 1.3060),
    (20,  998.21, 4184.1, 0.5984, 1.0016),
    (30,  995.65, 4180.1, 0.6154, 0.7972),
    (40,  992.22, 4179.6, 0.6305, 0.6527),
    (50,  988.03, 4181.3, 0.6435, 0.5465),
    (60,  983.20, 4184.9, 0.6543, 0.4660),
    (70,  977.76, 4190.3, 0.6631, 0.4035),
    (80,  971.79, 4197.5, 0.6700, 0.3540),
    (90,  965.31, 4206.6, 0.6753, 0.3145),
    (100, 958.35, 4217.0, 0.6791, 0.2818),
])

# air sec, 1 atm : T (K), cp (J/(kg·K)), k (mW/(m·K)), μ (µPa·s) ; ρ : gaz parfait
_AIR = np.array([
    (200, 1007, 18.1, 13.25),
    (250, 1006, 22.3, 15.96),
    (300, 1007, 26.3, 18.46),
    (350, 1009, 30.0, 20.82),
    (400, 1014, 33.8, 23.01),
    (450, 1021, 37.3, 25.07),
    (500, 1030, 40.7, 27.01),
])
_AIR_T = _AIR[:, 0] - 273.15
ATMOSPHERE = 101325.0       # Pa
R_AIR = 287.05              # J/(kg·K)


@dataclass(frozen=True)
class FluidProperty:
    fluid: str          # « Eau », « Air »
    label: str          # « Masse volumique »
    symbol: str         # « ρ »
    unit: str
    t_min: float        # plage de la table (°C)
    t_max: float
    temperatures: np.ndarray
    values: np.ndarray


def _water(column, factor=1.0):
    return _WATER[:, 0], _WATER[:, column] * factor


def _air(column, factor=1.0):
    return _AIR_T, _AIR[:, column] * factor


def _property(fluid, label, symbol, unit, table):
    ts, vs = table
    return FluidProperty(fluid, label, symbol, unit, float(ts[0]), float(ts[-1]), ts, vs)


_air_t = np.linspace(_AIR_T[0], _AIR_T[-1], 61)

PROPERTIES = {
    "rho_water": _property("Eau", "Masse volumique", "ρ", "kg/m³", _water(1)),
    "cp_water":  _property("Eau", "Capacité thermique massique", "cp", "J/(kg·K)", _water(2)),
    "k_water":   _property("Eau", "Conductivité thermique", "λ", "W/(m·K)", _water(3)),
    "mu_water":  _property("Eau", "Viscosité dynamique", "μ", "Pa·s", _water(4, 1e-3)),
    "rho_air":   _property("Air", "Masse volumique", "ρ", "kg/m³",
                           (_air_t, ATMOSPHERE / (R_AIR * (_air_t + 273.15)))),
    "cp_air":    _property("Air", "Capacité thermique massique", "cp", "J/(kg·K)", _air(1)),
    "k_air":     _property("Air", "Conductivité thermique", "λ", "W/(m·K)", _air(2, 1e-3)),
    "mu_air":    _property("Air", "Viscosité dynamique", "μ", "Pa·s", _air(3, 1e-6)),
}

FLUIDS = ("Eau", "Air")
SUFFIX = {"Eau": "water", "Air": "air"}


def function_name(fluid: str, prefix: str) -> str:
    """function_name("Eau", "rho") -> "rho_water"."""
    return f"{prefix}_{SUFFIX[fluid]}"


def evaluate(name: str, t):
    """Propriété name à la température t (°C) ; nan hors plage pour une voie."""
    prop = PROPERTIES[name]
    t = np.asarray(t, dtype=float)
    if t.ndim == 0 and np.isfinite(t) and not prop.t_min <= t <= prop.t_max:
        raise FormulaError(f"'{name}': {float(t):g} °C is outside the table "
                           f"({prop.t_min:g} to {prop.t_max:g} °C)")
    return np.interp(t, prop.temperatures, prop.values, left=np.nan, right=np.nan)
