# controller/scope_controller.py
"""
Mode « enregistrement long » : enregistrements d'oscilloscope (Tektronix...) de plusieurs
millions de points, convertis en workspace HDF5 (model/scope_record.py, format de
HDF5_viewer) et parcourus par zoom.

    - ouverture d'un ou plusieurs CSV Tektronix : conversion en HDF5 dans un thread, avec
      barre de progression (annulable) ; le .h5 produit à côté des CSV est réutilisé tant
      qu'il est plus récent qu'eux ;
    - ouverture directe d'un .h5 (du logger ou de csv_to_hdf5.py) ;
    - vue d'ensemble de tout l'enregistrement au-dessus des graphiques, avec la zone
      affichée (à déplacer ou élargir à la souris) ;
    - à chaque zoom / déplacement, la portion visible est relue : données brutes jusqu'à
      MAX_RAW_POINTS points par voie (curseurs, FFT, voies calculées disponibles), sinon
      enveloppe min/max de la pyramide (affichage seul) ;
    - la portion relue est transmise comme une trame (display_frame) : graphiques,
      arborescence, curseurs, FFT et voies calculées du logger s'appliquent tels quels.
"""
from __future__ import annotations

import os

import numpy as np
import pyqtgraph as pg
from PyQt6 import QtCore, QtWidgets

from model import measures
from model.config import LoggerConfig
from model.protocol import Frame
from model.scope_record import (MAX_RAW_POINTS, ImportCancelled, ScopeError, ScopeRecord,
                                default_h5_path, import_tek_csv, is_tek_csv)
from ressources import pens

RELOAD_DELAY_MS = 60               # regroupe les changements de zoom rapprochés


def is_scope_file(path: str) -> bool:
    ext = os.path.splitext(path)[1].lower()
    return ext in (".h5", ".hdf5") or (ext == ".csv" and is_tek_csv(path))


class ImportWorker(QtCore.QThread):
    progress = QtCore.pyqtSignal(float, str)
    succeeded = QtCore.pyqtSignal(str)
    failed = QtCore.pyqtSignal(str)

    def __init__(self, paths: list[str], h5_path: str):
        super().__init__()
        self.paths, self.h5_path = paths, h5_path
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            path = import_tek_csv(self.paths, self.h5_path,
                                  progress=lambda f, text: self.progress.emit(f, text),
                                  cancelled=lambda: self._cancel)
        except ImportCancelled:
            self.failed.emit("")
        except (ScopeError, OSError, ValueError) as exc:
            self.failed.emit(str(exc))
        else:
            self.succeeded.emit(path)


class ScopeController(QtCore.QObject):

    opened = QtCore.pyqtSignal(object)            # LoggerConfig de l'enregistrement
    closed = QtCore.pyqtSignal()
    display_frame = QtCore.pyqtSignal(object)     # portion relue (Frame)
    message = QtCore.pyqtSignal(str)

    def __init__(self, view, graph_ctrl):
        super().__init__()
        self.view = view
        self.graph = graph_ctrl
        self.record: ScopeRecord | None = None
        self.cfg: LoggerConfig | None = None
        self.worker: ImportWorker | None = None
        self.progress_dialog: QtWidgets.QProgressDialog | None = None
        self._syncing = False
        self._window_key = None
        self.max_raw = MAX_RAW_POINTS     # au-delà : enveloppe min/max

        self.overview_plot = pg.PlotItem()
        self.overview_plot.showGrid(x=True, y=False, alpha=0.2)
        self.overview_plot.setMouseEnabled(x=False, y=False)
        self.overview_plot.hideButtons()
        self.overview_plot.setMenuEnabled(False)
        self.overview_plot.getAxis("left").setWidth(graph_ctrl.AXIS_WIDTH)
        self.overview_plot.setLabel("bottom", "Temps", units="s")
        view.overviewgraph.addItem(self.overview_plot)
        self.overview_curves: list[pg.PlotDataItem] = []
        self.region = pg.LinearRegionItem(brush=pg.mkBrush(90, 160, 255, 50))
        self.region.setZValue(10)
        self.overview_plot.addItem(self.region, ignoreBounds=True)
        self.region.sigRegionChanged.connect(self._on_region_changed)

        self.reload_timer = QtCore.QTimer(self)
        self.reload_timer.setSingleShot(True)
        self.reload_timer.timeout.connect(self.reload)
        graph_ctrl.analog_plot.sigXRangeChanged.connect(self._on_view_changed)

    @property
    def active(self) -> bool:
        return self.record is not None

    # ------------------------------------------------------------------ ouverture
    def open(self, paths: list[str]) -> bool:
        """CSV Tektronix (un ou plusieurs) ou .h5. Import en arrière-plan si besoin."""
        paths = [os.path.abspath(p) for p in paths]
        h5 = [p for p in paths if os.path.splitext(p)[1].lower() in (".h5", ".hdf5")]
        if h5:
            if len(paths) > 1:
                self._error("Ouvrir un seul fichier .h5 à la fois")
                return False
            return self._open_h5(h5[0])
        not_tek = [os.path.basename(p) for p in paths if not is_tek_csv(p)]
        if not_tek:
            self._error("Format Tektronix non reconnu : " + ", ".join(not_tek))
            return False
        h5_path = default_h5_path(paths)
        if os.path.exists(h5_path) and all(os.path.getmtime(h5_path) >= os.path.getmtime(p)
                                           for p in paths):
            self.message.emit(f"Conversion existante réutilisée : {os.path.basename(h5_path)}")
            return self._open_h5(h5_path)
        self._start_import(paths, h5_path)
        return True

    def _start_import(self, paths, h5_path):
        self.worker = ImportWorker(paths, h5_path)
        dialog = QtWidgets.QProgressDialog("Conversion de l'enregistrement...", "Annuler",
                                           0, 1000, self.view)
        dialog.setWindowTitle("Enregistrement d'oscilloscope")
        dialog.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
        dialog.setMinimumDuration(0)
        dialog.canceled.connect(self.worker.cancel)
        self.progress_dialog = dialog
        self.worker.progress.connect(self._on_progress)
        self.worker.succeeded.connect(self._on_imported)
        self.worker.failed.connect(self._on_import_failed)
        self.worker.finished.connect(self._on_worker_finished)
        dialog.show()
        self.worker.start()

    def _on_progress(self, fraction: float, text: str):
        if self.progress_dialog is not None:
            self.progress_dialog.setLabelText(text)
            self.progress_dialog.setValue(int(fraction * 1000))

    def _close_progress(self):
        if self.progress_dialog is not None:
            self.progress_dialog.canceled.disconnect()
            self.progress_dialog.close()
            self.progress_dialog.deleteLater()
            self.progress_dialog = None

    def _on_imported(self, path: str):
        self._close_progress()
        self.message.emit(f"Enregistrement converti : {path}")
        self._open_h5(path)

    def _on_import_failed(self, message: str):
        self._close_progress()
        if message:
            self._error(message)
        else:
            self.message.emit("Conversion annulée")

    def _on_worker_finished(self):
        worker, self.worker = self.worker, None
        if worker is not None:
            worker.deleteLater()

    def wait_import(self, timeout_ms: int = 60000) -> bool:
        """Attend la fin d'une conversion en cours (tests)."""
        if self.worker is None:
            return True
        return self.worker.wait(timeout_ms)

    def _open_h5(self, path: str) -> bool:
        try:
            record = ScopeRecord(path)
        except ScopeError as exc:
            self._error(str(exc))
            return False
        self.close(emit=False)
        self.record = record
        self.cfg = self._config(record)
        self._window_key = None
        self._build_overview()
        self.view.overviewgraph.show()
        self.view.actionCloseScope.setEnabled(True)
        self.opened.emit(self.cfg)            # le contrôleur principal configure l'affichage
        self.reload()
        return True

    def _config(self, record: ScopeRecord) -> LoggerConfig:
        """Configuration d'affichage : une voie analogique par signal, valeurs physiques."""
        n = len(record.names)
        if n > 15:
            raise ScopeError("15 voies au plus")
        cfg = LoggerConfig(signals=list(range(n)), gains=[1.0] * 15)
        cfg.analog_names = record.names + cfg.analog_names[n:]
        unit = (record.metadata.get("vertical_units") or {}).get("value", "")
        cfg.units = [str(unit)] * 15
        cfg.sample_rate_hz = record.sample_rate
        cfg.record_points = record.length
        cfg.time_origin = record.t0
        cfg.source_name = os.path.basename(record.path)
        return cfg

    # ------------------------------------------------------------------ vue d'ensemble
    def _build_overview(self):
        for curve in self.overview_curves:
            self.overview_plot.removeItem(curve)
        self.overview_curves = []
        window = self.record.overview()
        x = window.x0 + np.arange(len(next(iter(window.data.values())))) * window.step
        for k, name in enumerate(self.record.names):
            curve = self.overview_plot.plot(x, window.data[name],
                                            pen=pens.pen(pens.analog_color(k)))
            self.overview_curves.append(curve)
        t0, t1 = self.record.t0, self.record.t0 + self.record.duration
        self.overview_plot.setXRange(t0, t1, padding=0)
        self._syncing = True
        self.region.setBounds((t0, t1))
        self.region.setRegion((t0, t1))
        self._syncing = False

    def _on_region_changed(self):
        if self._syncing or self.record is None:
            return
        lo, hi = self.region.getRegion()
        self._syncing = True
        self.graph.analog_plot.setXRange(lo, hi, padding=0)
        self._syncing = False
        self.reload_timer.start(RELOAD_DELAY_MS)

    def _on_view_changed(self, _vb, x_range):
        if self.record is None:
            return
        if not self._syncing:
            self._syncing = True
            self.region.setRegion(x_range)
            self._syncing = False
        self.reload_timer.start(RELOAD_DELAY_MS)

    # ------------------------------------------------------------------ portion affichée
    def reload(self):
        """Relit la portion visible et la transmet comme une trame."""
        if self.record is None:
            return
        x0, x1 = self.graph.analog_plot.vb.viewRange()[0]
        start, stop = self.record.index_of(x0), self.record.index_of(x1) + 1
        window = self.record.read_window(start, stop, max_raw=self.max_raw)
        key = (window.first_index, window.last_index, window.samples_per_bin)
        if key == self._window_key:
            return
        self._window_key = key
        self.display_frame.emit(self.frame_of(window))

    def frame_of(self, window) -> Frame:
        names = self.record.names
        analog = np.column_stack([window.data[name] for name in names])
        n = analog.shape[0]
        points = window.last_index - window.first_index
        if window.envelope:
            what = (f"enveloppe min/max, {measures.si(points, '', 3)} points "
                    f"(zoomer sous {measures.si(self.max_raw, '', 2)} points pour "
                    f"les mesures)")
        else:
            what = f"{points:,} points".replace(",", " ")
        frame = Frame(index=0, signals=list(range(len(names))),
                      raw=np.empty((n, 0), dtype=np.int16), analog=analog, logic=None,
                      sample_rate=1.0 / window.step, t0=window.x0)
        frame.meta.update({"scope": self.record.path, "envelope": window.envelope,
                           "saved": self.record.path,
                           "title": f"{os.path.basename(self.record.path)} — {what}"})
        return frame

    def show_all(self):
        if self.record is not None:
            self.graph.analog_plot.setXRange(self.record.t0,
                                             self.record.t0 + self.record.duration, padding=0)

    # ------------------------------------------------------------------ fermeture
    def close(self, emit: bool = True):
        if self.record is None:
            return
        self.reload_timer.stop()
        self.record.close()
        self.record = None
        self.cfg = None
        self.view.overviewgraph.hide()
        self.view.actionCloseScope.setEnabled(False)
        if emit:
            self.closed.emit()

    def _error(self, text: str):
        QtWidgets.QMessageBox.warning(self.view, "Enregistrement d'oscilloscope", text)
