# controller/fft_controller.py
"""
Utilitaire FFT : spectre temps réel des voies analogiques.

Le calcul (model/spectrum.py) est fait à chaque trame reçue, pour que le moyennage porte
sur toutes les trames et pas seulement sur celles qui sont dessinées ; le dessin suit le
même rythme que le graphique temporel (QTimer, REFRESH_HZ).

Réglages (groupe « FFT » de l'arbre des paramètres) : fenêtre, retrait du continu,
échelle (crête / efficace / dB), moyennage (aucun / moyenne de N trames / maximum),
fréquence maximale affichée, axe des fréquences logarithmique, nombre de pics repérés.
Mesures sur la « voie analysée » (choisie dans le groupe FFT ou en cliquant sur une voie de
l'arborescence) : résolution, fondamental, THD, pics. La valeur sous la souris est
affichée au-dessus du graphique.
"""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
import pyqtgraph.parametertree as ptree
from PyQt6 import QtCore, QtGui

from model import spectrum
from model.config import LoggerConfig
from model.protocol import Frame
from ressources import pens

NONE = "(aucune)"
LINEAR, LOG = "Linéaire", "Logarithmique"
AXIS_SCALES = [LINEAR, LOG]
SETTINGS_KEY = "fft/axe_frequences"


class FrequencyAxis(pg.AxisItem):
    """
    Axe des fréquences. En échelle log, graduations aux décades (étiquetées) et à 2 et 5
    fois chaque décade, écrites avec leur unité : 10 Hz, 20 Hz, 50 Hz, 100 Hz, 1 kHz...
    (pyqtgraph mélangerait sinon préfixe SI et puissances de 10).
    """

    def updateAutoSIPrefix(self):
        # bascule en log : la plage est encore en Hz linéaires (10**25000 -> inf, sans
        # effet sur le préfixe calculé) ; avertissement de dépassement inutile
        with np.errstate(over="ignore"):
            super().updateAutoSIPrefix()

    def tickValues(self, minVal, maxVal, size):
        if not self.logMode:
            return super().tickValues(minVal, maxVal, size)
        lo, hi = int(np.floor(minVal)), int(np.ceil(maxVal))
        decades = [float(d) for d in range(lo, hi + 1) if minVal <= d <= maxVal]
        minor = [d + np.log10(m) for d in range(lo, hi + 1) for m in (2, 5)
                 if minVal <= d + np.log10(m) <= maxVal]
        # peu de décades visibles (zoom) : 2 et 5 étiquetés aussi
        if len(decades) <= 2:
            return [(1.0, sorted(decades + minor)),
                    (0.1, [d + np.log10(m) for d in range(lo, hi + 1) for m in range(2, 10)
                           if m not in (2, 5) and minVal <= d + np.log10(m) <= maxVal])]
        return [(1.0, decades), (0.5, minor)]

    def tickStrings(self, values, scale, spacing):
        if not self.logMode:
            return super().tickStrings(values, scale, spacing)
        if spacing < 1.0:                 # graduations secondaires : sans étiquette
            return ["" for _ in values]
        return [_si(10 ** v, "Hz", digits=3) for v in values]


class FFTController(QtCore.QObject):

    REFRESH_HZ = 30

    def __init__(self, widget: pg.GraphicsLayoutWidget, tree: ptree.ParameterTree,
                 settings: QtCore.QSettings | None = None):
        super().__init__()
        self.widget = widget
        self.settings = settings          # choix de l'axe des fréquences mémorisé
        self.cfg: LoggerConfig | None = None
        self.enabled = False
        self.paused = False
        self.hidden: set[tuple] = set()
        self.curves: dict[int, pg.PlotDataItem] = {}
        self.frame: Frame | None = None
        self.freq: np.ndarray | None = None
        self.amp: np.ndarray | None = None         # (raies, voies) amplitudes crête moyennées
        self.signals: list[int] = []
        self.averager = spectrum.SpectrumAverager()
        self._dirty = False

        self.params = ptree.Parameter.create(name="FFT", type="group", children=[
            {"name": "Fenêtre", "type": "list", "limits": list(spectrum.WINDOWS),
             "value": "hann", "tip": "flattop : amplitudes exactes ; hann : bon compromis ; "
                                     "rectangulaire : résolution maximale"},
            {"name": "Retirer le continu", "type": "bool", "value": True},
            {"name": "Échelle", "type": "list", "limits": list(spectrum.SCALES),
             "value": "crête"},
            {"name": "Moyennage", "type": "list", "limits": list(spectrum.SpectrumAverager.MODES),
             "value": "aucun"},
            {"name": "Nombre de trames", "type": "int", "limits": (1, 10000), "value": 8,
             "visible": False},
            {"name": "Fréquence max (Hz)", "type": "float", "limits": (0, None), "value": 0.0,
             "siPrefix": True, "tip": "0 : jusqu'à la moitié de la fréquence d'échantillonnage"},
            {"name": "Axe des fréquences", "type": "list", "limits": AXIS_SCALES,
             "value": LINEAR, "tip": "Aussi par clic droit sur le spectre"},
            {"name": "Voie analysée", "type": "list", "limits": [NONE], "value": NONE},
            {"name": "Pics repérés", "type": "int", "limits": (0, 20), "value": 5},
            {"name": "Harmoniques (THD)", "type": "int", "limits": (1, 50), "value": 10},
            {"name": "Mesures", "type": "group", "children": [
                {"name": "Résolution", "type": "str", "readonly": True, "value": ""},
                {"name": "Trames moyennées", "type": "str", "readonly": True, "value": ""},
                {"name": "Fondamental", "type": "str", "readonly": True, "value": ""},
                {"name": "THD", "type": "str", "readonly": True, "value": ""},
                {"name": "Pics", "type": "text", "readonly": True, "value": ""},
            ]},
        ])
        tree.addParameters(self.params, showTop=True)
        self.params.sigTreeStateChanged.connect(self._on_params_changed)

        self.readout = pg.LabelItem(justify="right")
        self.plot = pg.PlotItem(axisItems={"bottom": FrequencyAxis("bottom")})
        self.plot.showGrid(x=True, y=True, alpha=0.3)
        self.plot.setDownsampling(auto=True, mode="peak")
        self.plot.setClipToView(True)
        self.plot.setTitle("Spectre")
        # échelle des fréquences : un seul réglage, suivi par l'arbre des paramètres, le
        # menu contextuel et l'option Log X de pyqtgraph (Plot Options > Transforms)
        self.log_action = QtGui.QAction("Fréquences en échelle log", self.plot.vb.menu)
        self.log_action.setCheckable(True)
        self.log_action.toggled.connect(self.set_log_x)
        self.plot.vb.menu.insertAction(self.plot.vb.menu.actions()[0], self.log_action)
        self.plot.ctrl.logXCheck.toggled.connect(self.set_log_x)
        # Log Y de pyqtgraph : non géré (marqueurs, mesures) ; l'échelle dB le remplace
        self.plot.ctrl.logYCheck.setEnabled(False)
        self.plot.ctrl.logYCheck.setToolTip("Utiliser l'échelle dB du groupe FFT")
        self.widget.addItem(self.readout, row=0, col=0)
        self.widget.addItem(self.plot, row=1, col=0)
        self.peak_markers = pg.ScatterPlotItem(symbol="t", size=9, brush=pg.mkBrush("#d62728"),
                                               pen=None)
        self.plot.addItem(self.peak_markers, ignoreBounds=True)
        self.peak_labels: list[pg.TextItem] = []
        self.widget.scene().sigMouseMoved.connect(self._on_mouse_moved)

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._redraw)
        self.timer.start(int(1000 / self.REFRESH_HZ))

        saved = self.settings.value(SETTINGS_KEY, LINEAR) if self.settings else LINEAR
        self.set_log_x(saved == LOG)
        self._apply_axis_label()

    # ------------------------------------------------------------------ axe des fréquences
    @property
    def log_x(self) -> bool:
        return self.p("Axe des fréquences").value() == LOG

    def set_log_x(self, log: bool):
        """Échelle des fréquences logarithmique ou linéaire (toutes les commandes)."""
        log = bool(log)
        self.p("Axe des fréquences").setValue(LOG if log else LINEAR)   # -> _on_params_changed

    def _sync_log_x(self):
        """Applique l'échelle choisie au tracé et aux commandes qui la reflètent."""
        log = self.log_x
        self.log_action.blockSignals(True)
        self.log_action.setChecked(log)
        self.log_action.blockSignals(False)
        # coche la case Log X de pyqtgraph : c'est son signal qui convertit courbes et axes
        # (PlotItem.updateLogMode) ; set_log_x, rappelé avec la même valeur, est sans effet
        self.plot.setLogMode(x=log, y=False)
        self._apply_axis_label()
        self._apply_x_range()           # après updateLogMode, qui réactive l'échelle auto
        if self.settings is not None:
            self.settings.setValue(SETTINGS_KEY, LOG if log else LINEAR)

    def _apply_axis_label(self):
        axis = self.plot.getAxis("bottom")
        if self.log_x:
            # graduations déjà écrites avec leur unité (FrequencyAxis)
            axis.enableAutoSIPrefix(False)
            self.plot.setLabel("bottom", "Fréquence (échelle log)", units=None)
        else:
            axis.enableAutoSIPrefix(True)
            self.plot.setLabel("bottom", "Fréquence", units="Hz")

    def p(self, *path):
        return self.params.child(*path)

    def _signal(self) -> int | None:
        """Voie analysée (indice), None tant qu'aucune voie analogique n'est choisie."""
        sig = self.p("Voie analysée").value()
        return sig if isinstance(sig, int) else None

    # ------------------------------------------------------------------ configuration
    def configure(self, cfg: LoggerConfig):
        self.cfg = cfg
        self.frame = None
        self.freq = self.amp = None
        for curve in self.curves.values():
            self.plot.removeItem(curve)
        self.curves.clear()
        self._clear_peaks()
        self.signals = list(cfg.analog_signals)
        for sig in self.signals:
            curve = self.plot.plot(pen=pens.pen(pens.analog_color(sig)),
                                   name=cfg.analog_name(sig))
            curve.setVisible(("A", sig) not in self.hidden)
            self.curves[sig] = curve
        choices = {f"{s:2d}  {cfg.analog_name(s)}": s for s in self.signals} or {NONE: None}
        selector = self.p("Voie analysée")
        current = selector.value()
        selector.setLimits(choices)
        selector.setValue(current if current in choices.values() else next(iter(choices.values())))
        self._apply_x_range()            # en log comme en linéaire
        self._reset_average()
        self._update_labels()

    def set_enabled(self, enabled: bool):
        self.enabled = enabled
        if enabled and self.frame is None and self.cfg is not None:
            self._reset_average()

    def set_paused(self, paused: bool):
        self.paused = paused

    def set_visible(self, key, visible: bool):
        (self.hidden.discard if visible else self.hidden.add)(key)
        if key[0] == "A" and key[1] in self.curves:
            self.curves[key[1]].setVisible(visible)

    def select_channel(self, key):
        """Clic sur une voie de l'arborescence : elle devient la voie analysée."""
        if key[0] == "A" and key[1] in self.signals:
            self.p("Voie analysée").setValue(key[1])

    def reset(self):
        """Recommence la moyenne (ou le maximum) à partir de la dernière trame."""
        self._reset_average()
        if self.frame is not None:
            self._compute(self.frame)

    def _reset_average(self):
        self.averager = spectrum.SpectrumAverager(self.p("Moyennage").value(),
                                                  self.p("Nombre de trames").value())

    # ------------------------------------------------------------------ données
    def on_frame(self, frame: Frame):
        if not self.enabled or self.paused or not frame.analog_signals:
            return
        self.frame = frame
        self._compute(frame)

    def show_frame(self, frame: Frame):
        """Spectre d'une trame donnée (mémoire tampon) : moyenne recommencée."""
        self.frame = frame
        if not self.enabled or not frame.analog_signals:
            return
        self._reset_average()
        self._compute(frame)

    def _compute(self, frame: Frame):
        freq, amp = spectrum.amplitude_spectrum(frame.analog, frame.sample_rate,
                                                self.p("Fenêtre").value(),
                                                self.p("Retirer le continu").value())
        self.freq = freq
        self.amp = self.averager.add(amp)
        self.signals = list(frame.analog_signals)
        self._dirty = True

    def _on_params_changed(self, _param, changes):
        measures = set(self.p("Mesures").children())
        names = {param.name() for param, kind, _ in changes
                 if kind == "value" and param not in measures}
        if not names:
            return                       # mise à jour des mesures affichées
        self.p("Nombre de trames").setOpts(visible=self.p("Moyennage").value() == "moyenne")
        if names & {"Fenêtre", "Retirer le continu", "Moyennage", "Nombre de trames"}:
            self.reset()
        if "Axe des fréquences" in names:
            self._sync_log_x()
        elif "Fréquence max (Hz)" in names:
            self._apply_x_range()
        self._update_labels()
        self._dirty = self.amp is not None

    # ------------------------------------------------------------------ dessin
    def _scaled(self, amp: np.ndarray) -> np.ndarray:
        return spectrum.scale_amplitude(amp, self.p("Échelle").value())

    def _x(self, freq: np.ndarray) -> slice:
        """Raies dessinées : sans la raie 0 en échelle log."""
        return slice(1 if self.log_x else 0, None)

    def _apply_x_range(self):
        if self.cfg is None:
            return
        f_max = self.p("Fréquence max (Hz)").value() or self.cfg.sample_rate / 2
        if self.log_x:
            df = self.cfg.sample_rate / self.cfg.samples_per_channel
            self.plot.setXRange(np.log10(df), np.log10(f_max), padding=0)
        else:
            self.plot.setXRange(0, f_max, padding=0)

    def _redraw(self):
        if not (self._dirty and self.enabled) or self.amp is None:
            return
        self._dirty = False
        keep = self._x(self.freq)
        for j, sig in enumerate(self.signals):
            curve = self.curves.get(sig)
            if curve is not None:
                curve.setData(self.freq[keep], self._scaled(self.amp[keep, j]),
                              skipFiniteCheck=True)
        self._update_measures()

    def _update_labels(self):
        if self.cfg is None:
            return
        sig = self._signal()
        unit = self.cfg.unit(sig) if sig is not None else ""
        scale = self.p("Échelle").value()
        label = {"crête": "Amplitude crête", "efficace": "Amplitude efficace",
                 "dB": f"dB (réf. 1 {unit or 'unité'} crête)"}[scale]
        self.plot.setLabel("left", label, units=None if scale == "dB" else (unit or None))
        df = self.cfg.sample_rate / self.cfg.samples_per_channel
        enbw = spectrum.enbw_bins(self.p("Fenêtre").value()) * df
        self.p("Mesures", "Résolution").setValue(f"{_si(df, 'Hz')} (ENBW {_si(enbw, 'Hz')})")

    def _clear_peaks(self):
        self.peak_markers.setData([], [])
        for label in self.peak_labels:
            self.plot.removeItem(label)
        self.peak_labels.clear()

    def _update_measures(self):
        sig = self._signal()
        self._clear_peaks()
        n_avg = self.averager.n_averaged
        mode = self.p("Moyennage").value()
        self.p("Mesures", "Trames moyennées").setValue(
            "-" if mode == "aucun" else (f"{n_avg}" if mode == "moyenne" else "maximum"))
        if sig not in self.signals or self.amp is None:
            for name in ("Fondamental", "THD", "Pics"):
                self.p("Mesures", name).setValue("")
            return
        j = self.signals.index(sig)
        amp = self.amp[:, j]
        win = self.p("Fenêtre").value()
        unit = self.cfg.unit(sig) if self.cfg else ""
        f_min = 0.0 if not self.p("Retirer le continu").value() else self.freq[1]
        h = spectrum.harmonics(self.freq, amp, win, self.p("Harmoniques (THD)").value(),
                               min_frequency=f_min)
        if h is None:
            self.p("Mesures", "Fondamental").setValue("")
            self.p("Mesures", "THD").setValue("")
        else:
            self.p("Mesures", "Fondamental").setValue(
                f"{_si(h.fundamental.frequency, 'Hz')} — {h.fundamental.amplitude:.5g} {unit}")
            self.p("Mesures", "THD").setValue(f"{100 * h.thd:.3g} %")
        peaks = spectrum.find_peaks(self.freq, amp, self.p("Pics repérés").value(), win,
                                    min_frequency=f_min)
        self.p("Mesures", "Pics").setValue("\n".join(
            f"{_si(pk.frequency, 'Hz'):>12}  {pk.amplitude:.5g} {unit}" for pk in peaks))
        if not peaks or not self.curves[sig].isVisible():
            return
        log_x = self.log_x
        xs = np.array([pk.frequency for pk in peaks])
        xs = np.log10(xs) if log_x else xs
        ys = self._scaled(amp)[[pk.index for pk in peaks]]
        self.peak_markers.setData(xs, ys)
        for x, y, pk in zip(xs, ys, peaks):
            label = pg.TextItem(_si(pk.frequency, "Hz"), anchor=(-0.1, 0.5), color="#d62728")
            label.setPos(x, y)
            self.plot.addItem(label, ignoreBounds=True)
            self.peak_labels.append(label)

    def _on_mouse_moved(self, pos):
        if self.amp is None or not self.plot.sceneBoundingRect().contains(pos):
            return
        x = self.plot.vb.mapSceneToView(pos).x()
        f = 10 ** x if self.log_x else x
        i = int(np.clip(round(f / (self.freq[1] - self.freq[0])), 0, self.freq.size - 1))
        sig = self._signal()
        if sig not in self.signals:
            return
        value = self._scaled(self.amp[:, self.signals.index(sig)])[i]
        unit = "dB" if self.p("Échelle").value() == "dB" else (self.cfg.unit(sig) if self.cfg else "")
        self.readout.setText(f"{self.cfg.analog_name(sig)} : {_si(self.freq[i], 'Hz')}  "
                             f"{value:.5g} {unit}")


def _si(value: float, unit: str, digits: int = 6) -> str:
    for factor, prefix in ((1e6, "M"), (1e3, "k"), (1, ""), (1e-3, "m")):
        if abs(value) >= factor:
            return f"{value / factor:.{digits}g} {prefix}{unit}"
    return f"{value:.{digits}g} {unit}"
