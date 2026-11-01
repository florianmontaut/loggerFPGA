# model/measures.py
"""
Mesures entre deux curseurs (fonctions pures, sans Qt).

Comme les curseurs « Waveform » du GLviewer : les valeurs sont celles de l'échantillon le
plus proche de chaque curseur (curseur « magnétique ») ; les statistiques portent sur les
échantillons compris entre les deux curseurs, bornes incluses.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def nearest_index(t: float, sample_rate: float, n_samples: int) -> int:
    """Échantillon le plus proche de l'instant t (axe des temps commençant à 0)."""
    return int(min(max(round(t * sample_rate), 0), n_samples - 1))


@dataclass
class SegmentMeasures:
    t1: float           # instants réels des échantillons retenus (s)
    t2: float
    y1: float
    y2: float
    n: int              # échantillons entre les curseurs
    minimum: float
    maximum: float
    mean: float
    rms: float

    @property
    def dt(self) -> float:
        return self.t2 - self.t1

    @property
    def dy(self) -> float:
        return self.y2 - self.y1

    @property
    def peak_to_peak(self) -> float:
        return self.maximum - self.minimum

    @property
    def slope(self) -> float | None:
        """Pente moyenne Δy / Δt (unité/s) ; None si Δt nul."""
        return None if self.dt == 0 else self.dy / self.dt


def segment(y: np.ndarray, sample_rate: float, t1: float, t2: float) -> SegmentMeasures:
    """
    Mesures sur la voie `y` entre les curseurs t1 et t2 (dans n'importe quel ordre :
    Δt et Δy restent signés, t2 - t1 et y(t2) - y(t1)).
    """
    y = np.asarray(y, dtype=float)
    if y.size == 0:
        raise ValueError("Voie vide")
    i1 = nearest_index(t1, sample_rate, y.size)
    i2 = nearest_index(t2, sample_rate, y.size)
    lo, hi = min(i1, i2), max(i1, i2)
    part = y[lo:hi + 1]
    return SegmentMeasures(t1=i1 / sample_rate, t2=i2 / sample_rate,
                           y1=float(y[i1]), y2=float(y[i2]), n=int(part.size),
                           minimum=float(part.min()), maximum=float(part.max()),
                           mean=float(part.mean()), rms=float(np.sqrt(np.mean(part ** 2))))


def deltas(columns: np.ndarray, sample_rate: float, t1: float, t2: float) -> np.ndarray:
    """y(t2) - y(t1) pour chaque colonne d'un tableau (n, voies)."""
    columns = np.asarray(columns)
    n = columns.shape[0]
    i1 = nearest_index(t1, sample_rate, n)
    i2 = nearest_index(t2, sample_rate, n)
    return columns[i2].astype(float) - columns[i1].astype(float)


def si(value: float | None, unit: str = "", digits: int = 5) -> str:
    """Valeur avec préfixe SI (1.25 ms, 400 Hz...)."""
    if value is None or not np.isfinite(value):
        return "-"
    if value == 0:
        return f"0 {unit}".strip()
    for factor, prefix in ((1e9, "G"), (1e6, "M"), (1e3, "k"), (1, ""), (1e-3, "m"),
                           (1e-6, "µ"), (1e-9, "n")):
        if abs(value) >= factor:
            return f"{value / factor:.{digits}g} {prefix}{unit}".strip()
    return f"{value:.{digits}g} {unit}".strip()
