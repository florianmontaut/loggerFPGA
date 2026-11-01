# model/spectrum.py
"""
Analyse spectrale (FFT) des trames du logger.

Reprend le principe de model/analysis/fft.py du GLviewer (fenêtrage puis demi-spectre),
en fonctions pures sans dépendance au modèle du GLviewer, avec en plus :
    - des amplitudes calibrées : une sinusoïde d'amplitude A donne un pic de hauteur A
      (correction du gain cohérent de la fenêtre), en crête, en efficace ou en dB ;
    - le retrait de la composante continue ;
    - le moyennage sur plusieurs trames (moyenne des puissances) et le maintien du maximum ;
    - la recherche des pics (fréquence affinée par interpolation) et le calcul du THD.

Fenêtres « périodiques » (adaptées à la FFT) définies par leurs coefficients de cosinus.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# coefficients a_k de w[n] = Σ (-1)^k a_k cos(2πkn/N)
WINDOWS = {
    "rectangulaire":    (1.0,),
    "hann":             (0.5, 0.5),
    "hamming":          (0.54, 0.46),
    "blackman":         (0.42, 0.5, 0.08),
    "blackman-harris":  (0.35875, 0.48829, 0.14128, 0.01168),
    "flattop":          (0.21557895, 0.41663158, 0.277263158, 0.083578947, 0.006947368),
}
# demi-largeur du lobe principal, en raies (séparation minimale entre deux pics)
LOBE_BINS = {"rectangulaire": 1, "hann": 2, "hamming": 2, "blackman": 3,
             "blackman-harris": 4, "flattop": 5}

SCALES = ("crête", "efficace", "dB")


def window(name: str, n: int) -> np.ndarray:
    try:
        coefs = WINDOWS[name]
    except KeyError:
        raise ValueError(f"Fenêtre inconnue : {name}") from None
    phase = 2 * np.pi * np.arange(n) / n
    w = np.zeros(n)
    for k, a in enumerate(coefs):
        w += (-1) ** k * a * np.cos(k * phase)
    return w


def enbw_bins(name: str, n: int = 4096) -> float:
    """Bande équivalente de bruit de la fenêtre, en raies."""
    w = window(name, n)
    return n * np.sum(w ** 2) / np.sum(w) ** 2


def amplitude_spectrum(y: np.ndarray, fs: float, win: str = "hann",
                       remove_dc: bool = True) -> tuple[np.ndarray, np.ndarray]:
    """
    Spectre d'amplitude crête de `y` (une voie ou un tableau (n, voies)).

    Renvoie (fréquences, amplitudes) ; amplitudes de même forme que y, sur n//2 + 1 raies.
    """
    y = np.asarray(y, dtype=float)
    n = y.shape[0]
    if n < 2:
        raise ValueError("Il faut au moins deux points pour une FFT")
    if remove_dc:
        y = y - y.mean(axis=0)
    w = window(win, n)
    w_shaped = w if y.ndim == 1 else w[:, None]
    spec = np.abs(np.fft.rfft(y * w_shaped, axis=0)) * 2 / w.sum()
    spec[0] /= 2                          # composante continue : pas de raie symétrique
    if n % 2 == 0:
        spec[-1] /= 2                     # raie de Nyquist
    return np.fft.rfftfreq(n, 1 / fs), spec


def scale_amplitude(amp: np.ndarray, scale: str, floor_db: float = -200.0) -> np.ndarray:
    """Amplitude crête -> échelle d'affichage (crête, efficace ou dB réf. 1 unité crête)."""
    if scale == "crête":
        return amp
    if scale == "efficace":
        rms = amp / np.sqrt(2)
        rms[0] = amp[0]                   # la composante continue est sa propre valeur efficace
        return rms
    if scale == "dB":
        return np.maximum(20 * np.log10(np.maximum(amp, 1e-300)), floor_db)
    raise ValueError(f"Échelle inconnue : {scale}")


class SpectrumAverager:
    """
    Moyennage des spectres successifs :
        "aucun"   : dernier spectre ;
        "moyenne" : moyenne des puissances sur les `count` derniers spectres ;
        "max"     : maximum depuis la dernière remise à zéro.
    """
    MODES = ("aucun", "moyenne", "max")

    def __init__(self, mode: str = "aucun", count: int = 8):
        if mode not in self.MODES:
            raise ValueError(f"Moyennage inconnu : {mode}")
        self.mode = mode
        self.count = max(1, int(count))
        self.reset()

    def reset(self):
        self._history: list[np.ndarray] = []
        self._power_sum: np.ndarray | None = None
        self._max: np.ndarray | None = None

    @property
    def n_averaged(self) -> int:
        if self.mode == "moyenne":
            return len(self._history)
        return 0 if self._max is None and self.mode == "max" else 1

    def add(self, amp: np.ndarray) -> np.ndarray:
        """Ajoute un spectre (amplitudes crête) et renvoie le spectre moyenné."""
        if self.mode == "aucun":
            return amp
        shape = (self._history[0].shape if self._history else
                 self._max.shape if self._max is not None else None)
        if shape is not None and shape != amp.shape:
            self.reset()                  # changement de nombre de points ou de voies
        if self.mode == "max":
            self._max = amp.copy() if self._max is None else np.maximum(self._max, amp)
            return self._max
        power = amp ** 2
        self._history.append(power)
        self._power_sum = power.copy() if self._power_sum is None else self._power_sum + power
        while len(self._history) > self.count:
            self._power_sum -= self._history.pop(0)
        return np.sqrt(np.maximum(self._power_sum, 0) / len(self._history))


@dataclass
class Peak:
    frequency: float      # Hz, affinée par interpolation parabolique
    amplitude: float      # amplitude crête de la raie
    index: int            # raie du maximum


def find_peaks(freq: np.ndarray, amp: np.ndarray, count: int = 5, win: str = "hann",
               min_frequency: float = 0.0, rel_floor: float = 1e-4,
               noise_factor: float = 10.0) -> list[Peak]:
    """
    Les `count` pics les plus hauts (maxima locaux), séparés d'au moins un lobe principal.
    Sont ignorées : les raies sous `min_frequency`, celles plus faibles que rel_floor x le
    maximum et celles qui ne dépassent pas noise_factor x le plancher de bruit (médiane du
    spectre ; 10 = 20 dB au-dessus du bruit).
    """
    amp = np.asarray(amp, dtype=float)
    if amp.size < 3:
        return []
    df = freq[1] - freq[0]
    lobe = LOBE_BINS.get(win, 2)
    first = max(1, int(np.ceil(min_frequency / df)))
    mid = amp[1:-1]
    local = np.nonzero((mid > amp[:-2]) & (mid >= amp[2:]))[0] + 1
    local = local[local >= first]
    if local.size == 0:
        return []
    floor = max(rel_floor * amp[local].max(), noise_factor * float(np.median(amp[first:])))
    local = local[amp[local] >= floor]
    peaks: list[Peak] = []
    for i in local[np.argsort(amp[local])[::-1]]:
        if any(abs(int(i) - p.index) <= lobe for p in peaks):
            continue
        peaks.append(Peak(_interpolate_frequency(freq, amp, int(i)), float(amp[i]), int(i)))
        if len(peaks) >= count:
            break
    return peaks


def _interpolate_frequency(freq, amp, i) -> float:
    """Sommet de la parabole passant par les log-amplitudes des raies i-1, i, i+1."""
    if not 0 < i < amp.size - 1:
        return float(freq[i])
    a, b, c = np.log(np.maximum(amp[i - 1:i + 2], 1e-300))
    denom = a - 2 * b + c
    delta = 0.0 if denom == 0 else 0.5 * (a - c) / denom
    return float(freq[i] + np.clip(delta, -0.5, 0.5) * (freq[1] - freq[0]))


@dataclass
class Harmonics:
    fundamental: Peak
    amplitudes: list[float]   # amplitudes crête des harmoniques 2, 3, ...
    thd: float                # sqrt(Σ h_k²) / h_1 (rapport, pas en %)


def harmonics(freq: np.ndarray, amp: np.ndarray, win: str = "hann", n_harmonics: int = 10,
              min_frequency: float = 0.0) -> Harmonics | None:
    """Fondamental (pic le plus haut) et taux de distorsion harmonique."""
    peaks = find_peaks(freq, amp, count=1, win=win, min_frequency=min_frequency)
    if not peaks:
        return None
    f0 = peaks[0]
    df = freq[1] - freq[0]
    lobe = LOBE_BINS.get(win, 2)
    values = []
    for k in range(2, n_harmonics + 2):
        center = int(round(k * f0.frequency / df))
        if center + lobe >= amp.size:
            break
        values.append(float(amp[max(center - lobe, 0):center + lobe + 1].max()))
    thd = float(np.sqrt(np.sum(np.square(values))) / f0.amplitude) if values else 0.0
    return Harmonics(f0, values, thd)
