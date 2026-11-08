# controller/pattern_controller.py
"""
Export d'un motif (clic droit sur un graphique › « Exporter un motif... ») : table de
points d'une voie sur une zone, à copier-coller dans un simulateur (PLECS, PSPICE...).

    - une zone orange (LinearRegionItem, comme la zone FFT) apparaît sur le graphique, à
      déplacer ou redimensionner ; ses bornes sont aussi réglables dans la fenêtre ;
    - les points exportés sont marqués sur la courbe de la voie choisie (ScatterPlotItem) :
      la décimation (1 point sur N, MAX_POINTS au plus) se voit ;
    - voies : analogiques, calculées et logiques de la trame affichée ;
    - enregistrement d'oscilloscope : la zone est lue en données brutes dans le fichier,
      quel que soit le zoom (voies calculées évaluées sur la zone) ;
    - mise à jour : regroupée pendant un glisser (au relâchement), sinon immédiate.
"""
from __future__ import annotations

import os
from typing import Callable

import numpy as np
import pyqtgraph as pg
from PyQt6 import QtCore, QtWidgets

from model import measures, pattern
from view.pattern_dialog import PatternDialog

ORANGE = "#f0883e"
PREVIEW_LINES = 25
UPDATE_DELAY_MS = 100


class PatternController(QtCore.QObject):

    message = QtCore.pyqtSignal(str)

    def __init__(self, view, graph_ctrl,
                 zone_frame_provider: Callable[[], Callable | None] = lambda: None,
                 last_dir: Callable[[], str] = lambda: ""):
        super().__init__()
        self.view = view
        self.graph = graph_ctrl
        # () -> lecteur(t0, t1) -> Frame de la zone (enregistrement d'oscilloscope) ou None
        self.zone_frame_provider = zone_frame_provider
        self.last_dir = last_dir
        self.dialog: PatternDialog | None = None
        self.plot: pg.PlotItem | None = None
        self.channels: list[tuple] = []           # (clé, nom, unité)
        self.pattern: pattern.Pattern | None = None
        self.text = ""
        self._syncing = False

        self.region = pg.LinearRegionItem(orientation="vertical", swapMode="sort",
                                          brush=pg.mkBrush(240, 136, 62, 40),
                                          hoverBrush=pg.mkBrush(240, 136, 62, 75))
        self.region.setZValue(16)
        self.labels = []
        for line in self.region.lines:
            line.setPen(pg.mkPen(ORANGE, width=2))
            line.setHoverPen(pg.mkPen("#ffa657", width=3))
            self.labels.append(pg.InfLineLabel(line, text="motif", position=0.94,
                                               color=ORANGE, fill=(20, 20, 20, 160)))
        self.region.sigRegionChanged.connect(self._on_region_moved)
        self.region.sigRegionChangeFinished.connect(self._on_region_released)
        self.scatter = pg.ScatterPlotItem(size=6, symbol="o", pen=pg.mkPen("#ffffff", width=0.6),
                                          brush=pg.mkBrush(ORANGE))
        self.scatter.setZValue(17)
        self.scatter_plot: pg.PlotItem | None = None
        self.timer = QtCore.QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.update)

        for plot in (graph_ctrl.analog_plot, graph_ctrl.math_plot):
            action = plot.vb.menu.addAction("Exporter un motif...")
            action.triggered.connect(lambda _=False, p=plot: self.start(p))

    @property
    def active(self) -> bool:
        return self.dialog is not None

    # ------------------------------------------------------------------ ouverture
    def start(self, plot: pg.PlotItem | None = None):
        """Zone sur `plot` (portion affichée, au milieu) et fenêtre d'options."""
        plot = plot or self.graph.analog_plot
        if self.graph.cfg is None:
            return
        if self.dialog is None:
            self.dialog = PatternDialog(self.view)
            d = self.dialog
            d.channel.currentIndexChanged.connect(self.update)
            d.max_points.valueChanged.connect(self.update)
            d.format.currentIndexChanged.connect(self._render)
            d.relative.toggled.connect(self._render)
            d.decimal_comma.toggled.connect(self._render)
            d.start.sigValueChanged.connect(self._on_spin_changed)
            d.stop.sigValueChanged.connect(self._on_spin_changed)
            d.copy_button.clicked.connect(self.copy)
            d.save_button.clicked.connect(self.save_dialog)
            d.closed.connect(self.stop)
        self._move_region_to(plot)
        x0, x1 = plot.vb.viewRange()[0]
        width = x1 - x0
        self._set_region(x0 + 0.3 * width, x0 + 0.7 * width)
        self.refresh_channels(prefer=plot)
        self.dialog.show()
        self.dialog.raise_()
        self.update()

    def _move_region_to(self, plot: pg.PlotItem):
        if self.plot is not None and self.region in self.plot.items:
            self.plot.removeItem(self.region)
        self.plot = plot
        plot.addItem(self.region, ignoreBounds=True)
        cfg = self.graph.cfg
        self.region.setBounds((cfg.time_origin, cfg.time_origin + cfg.frame_duration))

    def refresh_channels(self, prefer: pg.PlotItem | None = None):
        """Voies proposées (configuration affichée, voies calculées actives)."""
        if self.dialog is None:
            return
        cfg = self.graph.cfg
        current = self.selected_key()
        channels = [(("A", s), cfg.analog_name(s), cfg.unit(s)) for s in cfg.analog_signals]
        engine = self.graph.math_engine
        math = [(("M", c.name), c.name, c.unit) for c in (engine.active if engine else [])]
        logic = ([(("L", b), cfg.logic_name(b), "") for b in range(16)]
                 if cfg.has_logic else [])
        channels += math + logic
        self.channels = channels
        combo = self.dialog.channel
        combo.blockSignals(True)
        combo.clear()
        kinds = {"A": "analogique", "M": "calculée", "L": "logique"}
        for key, name, unit in channels:
            combo.addItem(f"{name}" + (f" ({unit})" if unit else "") + f"   — {kinds[key[0]]}")
        keys = [c[0] for c in channels]
        if current in keys:
            combo.setCurrentIndex(keys.index(current))
        elif prefer is self.graph.math_plot and math:
            combo.setCurrentIndex(keys.index(math[0][0]))
        combo.blockSignals(False)
        if self.plot is not None:
            self.region.setBounds((cfg.time_origin, cfg.time_origin + cfg.frame_duration))

    def selected_key(self):
        if self.dialog is None or not self.channels:
            return None
        index = self.dialog.channel.currentIndex()
        return self.channels[index][0] if 0 <= index < len(self.channels) else None

    # ------------------------------------------------------------------ zone
    def zone(self) -> tuple[float, float]:
        t0, t1 = self.region.getRegion()
        return float(t0), float(t1)

    def set_zone(self, t0: float, t1: float):
        self._set_region(t0, t1)
        self.update()

    def _set_region(self, t0, t1):
        self._syncing = True
        try:
            self.region.setRegion((t0, t1))
        finally:
            self._syncing = False
        self._sync_fields()

    def _sync_fields(self):
        t0, t1 = self.zone()
        for label, value in zip(self.labels, (t0, t1)):
            label.setFormat(f"motif {measures.si(value, 's', 4)}")
        if self.dialog is None:
            return
        self._syncing = True
        try:
            self.dialog.start.setValue(t0)
            self.dialog.stop.setValue(t1)
        finally:
            self._syncing = False

    def _dragging(self) -> bool:
        return bool(getattr(self.region, "moving", False)
                    or any(getattr(line, "moving", False) for line in self.region.lines))

    def _on_region_moved(self):
        if self._syncing:
            return
        self._sync_fields()
        if self._dragging():
            self.timer.stop()               # mise à jour au relâchement
        else:
            self.timer.start(UPDATE_DELAY_MS)

    def _on_region_released(self):
        if self._syncing or self._dragging():
            return
        self.update()

    def _on_spin_changed(self, *_):
        if self._syncing or self.dialog is None:
            return
        t0, t1 = self.dialog.start.value(), self.dialog.stop.value()
        if t1 > t0:
            self._syncing = True
            try:
                self.region.setRegion((t0, t1))
            finally:
                self._syncing = False
            for label, value in zip(self.labels, self.zone()):
                label.setFormat(f"motif {measures.si(value, 's', 4)}")
            self.timer.start(UPDATE_DELAY_MS)

    # ------------------------------------------------------------------ données
    def _series(self, key, t0: float, t1: float):
        """(temps, valeurs) de la voie sur une zone couvrant [t0, t1], ou un message."""
        reader = self.zone_frame_provider()
        if reader is not None:                      # enregistrement d'oscilloscope
            try:
                frame = reader(t0, t1)
            except ValueError as exc:
                return str(exc)
            math = (self.graph.math_engine.evaluate(frame)[0]
                    if key[0] == "M" and self.graph.math_engine else {})
        else:
            frame = self.graph.frame
            if frame is None:
                return "aucune trame affichée"
            math = self.graph.math_results(frame) if key[0] == "M" else {}
        t = frame.time()
        if key[0] == "A":
            if key[1] not in frame.analog_signals:
                return "voie absente de la trame"
            j = frame.analog_signals.index(key[1])
            native = frame.meta.get("native") or {}
            if j in native:                 # bases de temps différentes : ses instants
                t, y = native[j]
                return (t, y) if t.size else "voie sans échantillon dans la zone"
            y = frame.analog[:, j]
        elif key[0] == "L":
            if frame.logic is None:
                return "pas de voie logique dans la trame"
            y = frame.logic[:, key[1]].astype(float)
        else:
            if key[1] not in math:
                return "voie calculée indisponible (formule invalide ou enveloppe)"
            y = math[key[1]]
        finite = np.isfinite(y)
        if not finite.all():                # hors de l'étendue d'une voie (NaN)
            t, y = t[finite], y[finite]
            if not t.size:
                return "voie sans échantillon dans la zone"
        return t, y

    def update(self):
        """Sélection (décimée), points marqués, texte et aperçu."""
        self.timer.stop()
        if self.dialog is None:
            return
        key = self.selected_key()
        if key is None:
            return self._show_error("aucune voie")
        t0, t1 = self.zone()
        series = self._series(key, t0, t1)
        if isinstance(series, str):
            return self._show_error(series)
        t, y = series
        self.pattern = pattern.select(t, y, t0, t1, self.dialog.max_points.value())
        if self.pattern.points < 2:
            return self._show_error("moins de 2 échantillons dans la zone")
        self._show_points(key)
        p = self.pattern
        count = f"{p.zone_points:,}".replace(",", " ")
        info = (f"{count} échantillons dans la zone, " +
                (f"1 point sur {p.step} : " if p.step > 1 else "") +
                f"{p.points} points exportés, sur {measures.si(p.t[-1] - p.t[0], 's', 4)}")
        self.dialog.info.setText(info)
        self.dialog.copy_button.setEnabled(True)
        self.dialog.save_button.setEnabled(True)
        self._render()

    def _show_points(self, key):
        plot = self.graph._plot_of(key)
        if self.scatter_plot is not plot:
            if self.scatter_plot is not None and self.scatter in self.scatter_plot.items:
                self.scatter_plot.removeItem(self.scatter)
            plot.addItem(self.scatter, ignoreBounds=True)
            self.scatter_plot = plot
        y = self.pattern.y
        if key[0] == "L":                           # tracé décalé des voies logiques
            y = key[1] + self.graph.LOGIC_HEIGHT * y
        self.scatter.setData(self.pattern.t, y)

    def _show_error(self, text: str):
        self.pattern = None
        self.text = ""
        self.scatter.setData([], [])
        self.dialog.info.setText(f"⚠ {text}")
        self.dialog.preview.setPlainText("")
        self.dialog.copy_button.setEnabled(False)
        self.dialog.save_button.setEnabled(False)

    def _render(self, *_):
        if self.dialog is None or self.pattern is None:
            return
        d = self.dialog
        key = self.selected_key()
        name, unit = next(((n, u) for k, n, u in self.channels if k == key), ("y", ""))
        self.text = pattern.format_pattern(self.pattern, d.format.currentText(), name, unit,
                                           relative=d.relative.isChecked(),
                                           decimal_comma=d.decimal_comma.isChecked())
        lines = self.text.splitlines()
        preview = "\n".join(lines[:PREVIEW_LINES])
        if len(lines) > PREVIEW_LINES:
            preview += f"\n… ({len(lines)} lignes)"
        d.preview.setPlainText(preview)

    # ------------------------------------------------------------------ sortie
    def copy(self):
        if not self.text:
            return
        QtWidgets.QApplication.clipboard().setText(self.text)
        self.message.emit(f"Motif copié dans le presse-papiers : {self.pattern.points} points")

    def save_dialog(self):
        if not self.text:
            return
        fmt = self.dialog.format.currentText()
        ext = ".csv" if fmt == pattern.FORMATS[1] else ".txt"
        key = self.selected_key()
        name = next((n for k, n, u in self.channels if k == key), "motif")
        default = os.path.join(self.last_dir(), f"motif_{name}{ext}")
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self.dialog, "Enregistrer le motif", default,
            "Texte (*.txt);;CSV (*.csv);;Tous les fichiers (*)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(self.text)
        except OSError as exc:
            QtWidgets.QMessageBox.warning(self.dialog, "Exporter un motif", str(exc))
            return
        self.message.emit(f"Motif enregistré : {path}")

    # ------------------------------------------------------------------ fermeture
    def stop(self):
        """Fenêtre fermée : zone et points retirés du graphique."""
        self.timer.stop()
        if self.plot is not None and self.region in self.plot.items:
            self.plot.removeItem(self.region)
        if self.scatter_plot is not None and self.scatter in self.scatter_plot.items:
            self.scatter_plot.removeItem(self.scatter)
        self.plot = self.scatter_plot = None
        dialog, self.dialog = self.dialog, None
        if dialog is not None:
            dialog.closed.disconnect(self.stop)
            dialog.hide()
            dialog.deleteLater()
