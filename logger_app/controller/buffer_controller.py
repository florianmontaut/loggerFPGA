# controller/buffer_controller.py
"""
Mémoire tampon des dernières trames et navigation (onglet « Trames »).

    - chaque trame reçue entre dans la mémoire tampon (model/frame_buffer.py) et dans la
      liste de l'onglet Trames : vignette de la première voie, numéro, heure, ✓ si elle
      est enregistrée sur disque ;
    - « direct » : le graphique, la FFT et les curseurs suivent les trames reçues ;
      « relecture » : un clic sur une trame (ou Alt+← / Alt+→) l'affiche, l'acquisition
      continue de remplir la mémoire tampon ; « Direct » (Alt+Fin) revient au flux ;
    - « Enregistrer la mémoire tampon... » : toutes les trames (ou la sélection, menu
      contextuel de la liste) dans un seul fichier ;
    - avant de quitter, et avant une acquisition qui viderait la mémoire tampon (autre
      disposition de voies), les trames non enregistrées sont proposées à l'enregistrement.

Signal display_frame(trame, mode) : mode "live" (flux direct), "review" (trame choisie) ou
"resume" (retour au direct : dernière trame réaffichée).
"""
from __future__ import annotations

import datetime
import os
from typing import Callable

from PyQt6 import QtCore, QtGui, QtWidgets

from model.config import LoggerConfig
from model.frame_buffer import FrameBuffer
from model.protocol import Frame
from model.recorder import layout_key, save_frames
from ressources import pens

FRAME_ROLE = QtCore.Qt.ItemDataRole.UserRole + 1
THUMB_W, THUMB_H = 120, 34


def thumbnail(frame: Frame, cfg: LoggerConfig | None) -> QtGui.QIcon:
    """Vignette de la première voie (min / max par colonne de pixels)."""
    pix = QtGui.QPixmap(THUMB_W, THUMB_H)
    pix.fill(QtGui.QColor("#16181c"))
    if frame.analog.shape[1]:
        y = frame.analog[:, 0]
        color = pens.analog_color(frame.analog_signals[0])
    elif frame.logic is not None:
        y = frame.logic[:, 0].astype(float)
        color = pens.logic_color(0)
    else:
        return QtGui.QIcon(pix)
    n = (y.size // THUMB_W) * THUMB_W
    cols = y[:n].reshape(THUMB_W, -1)
    lo, hi = cols.min(axis=1), cols.max(axis=1)
    ymin, ymax = float(lo.min()), float(hi.max())
    span = (ymax - ymin) or 1.0
    to_px = lambda v: (THUMB_H - 3) - (v - ymin) / span * (THUMB_H - 6)
    painter = QtGui.QPainter(pix)
    painter.setPen(QtGui.QPen(QtGui.QColor(color), 1))
    for x, (a, b) in enumerate(zip(to_px(lo), to_px(hi))):
        painter.drawLine(QtCore.QPointF(x + 0.5, a), QtCore.QPointF(x + 0.5, b))
    painter.end()
    return QtGui.QIcon(pix)


def _clock(timestamp: float) -> str:
    if not timestamp:
        return ""
    return datetime.datetime.fromtimestamp(timestamp).strftime("%H:%M:%S.%f")[:-3]


class BufferController(QtCore.QObject):

    display_frame = QtCore.pyqtSignal(object, str)     # trame, "live" / "review" / "resume"
    message = QtCore.pyqtSignal(str)

    def __init__(self, view, capacity: int,
                 record_settings: Callable[[], tuple[str, str, str]]):
        super().__init__()
        self.view = view
        self.list: QtWidgets.QListWidget = view.framesList
        self.record_settings = record_settings      # () -> (dossier, préfixe, format)
        self.buffer = FrameBuffer(capacity)
        self.cfg: LoggerConfig | None = None          # configuration de l'acquisition
        self.reviewing: Frame | None = None

        self.list.currentRowChanged.connect(self._on_row_changed)
        self.save_selection_action = QtGui.QAction("Enregistrer la sélection...", self.list)
        self.save_selection_action.triggered.connect(
            lambda: self.save_dialog(self.selected_frames()))
        self.list.addAction(self.save_selection_action)
        self._update_label()

    # ------------------------------------------------------------------ état
    @property
    def live(self) -> bool:
        return self.reviewing is None

    def selected_frames(self) -> list[Frame]:
        rows = sorted(self.list.row(item) for item in self.list.selectedItems())
        return [self.buffer[r] for r in rows] or self.buffer.frames

    # ------------------------------------------------------------------ trames reçues
    def on_acquisition_started(self, cfg: LoggerConfig):
        self.cfg = cfg.copy()
        self.go_live(show=False)

    def on_frame(self, frame: Frame):
        cfg = self.cfg or self.buffer.cfg
        if cfg is None:
            return
        dropped = self.buffer.add(frame, cfg)
        self._remove_rows(dropped)
        self.list.addItem(self._make_item(frame))
        if self.live:
            self.display_frame.emit(frame, "live")
            self.list.scrollToBottom()
        self._update_label()

    def _make_item(self, frame: Frame) -> QtWidgets.QListWidgetItem:
        item = QtWidgets.QListWidgetItem(thumbnail(frame, self.cfg), "")
        item.setData(FRAME_ROLE, frame.index)
        self._label_item(item, frame)
        return item

    def _label_item(self, item: QtWidgets.QListWidgetItem, frame: Frame):
        saved = FrameBuffer.is_saved(frame)
        item.setText(f"Trame {frame.index}{'  ✓' if saved else ''}\n{_clock(frame.timestamp)}")
        tip = f"Trame {frame.index} — {_clock(frame.timestamp)}"
        if saved:
            tip += f"\nEnregistrée : {frame.meta['saved']}" if isinstance(
                frame.meta["saved"], str) else "\nEnregistrée"
        item.setToolTip(tip)

    def _remove_rows(self, dropped: list[Frame]):
        if not dropped:
            return
        # trame en relecture sortie de la mémoire tampon : elle reste affichée (l'affichage
        # ne repart pas en direct sans que l'utilisateur le demande)
        self.list.blockSignals(True)
        if len(dropped) >= self.list.count():
            self.list.clear()
        else:
            for _ in dropped:                 # toujours les plus anciennes, en tête
                self.list.takeItem(0)
        self.list.blockSignals(False)

    # ------------------------------------------------------------------ navigation
    def _on_row_changed(self, row: int):
        if 0 <= row < len(self.buffer):
            self.review(row)

    def review(self, position: int):
        """Affiche la trame de rang `position` (0 = la plus ancienne)."""
        if not 0 <= position < len(self.buffer):
            return
        frame = self.buffer[position]
        self.reviewing = frame
        self.list.blockSignals(True)
        self.list.setCurrentRow(position)
        self.list.blockSignals(False)
        self.list.scrollToItem(self.list.item(position))
        self.display_frame.emit(frame, "review")
        self._update_label()

    def previous(self):
        if not len(self.buffer):
            return
        if self.live:
            # en direct, la dernière trame est affichée : on remonte d'une trame
            self.review(max(len(self.buffer) - 2, 0))
        else:
            # trame sortie de la mémoire tampon (position -1) : la plus ancienne
            self.review(max(self.buffer.position(self.reviewing) - 1, 0))

    def next(self):
        if self.live:
            return
        position = self.buffer.position(self.reviewing) + 1
        if position >= len(self.buffer):
            self.go_live()
        else:
            self.review(position)

    def go_live(self, show: bool = True):
        was_reviewing = self.reviewing is not None
        self.reviewing = None
        self.list.blockSignals(True)
        self.list.setCurrentRow(-1)
        self.list.clearSelection()
        self.list.blockSignals(False)
        if show and was_reviewing and self.buffer.latest is not None:
            self.display_frame.emit(self.buffer.latest, "resume")
        self.list.scrollToBottom()
        self._update_label()

    # ------------------------------------------------------------------ taille
    def set_capacity(self, capacity: int):
        self._remove_rows(self.buffer.set_capacity(capacity))
        self._update_label()

    def clear(self):
        self._remove_rows(self.buffer.clear())
        self.reviewing = None
        self._update_label()

    # ------------------------------------------------------------------ enregistrement
    def save_dialog(self, frames: list[Frame] | None = None) -> bool:
        """Enregistre des trames (toutes par défaut) dans un fichier choisi ; True si fait."""
        frames = list(frames) if frames is not None else self.buffer.frames
        if not frames or self.buffer.cfg is None:
            self.message.emit("Mémoire tampon vide : rien à enregistrer")
            return False
        directory, prefix, fmt = self.record_settings()
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        default = os.path.join(directory, f"{prefix}_tampon_{stamp}.{fmt}")
        filters = "CSV (*.csv);;NumPy (*.npz)" if fmt == "csv" else "NumPy (*.npz);;CSV (*.csv)"
        path, selected = QtWidgets.QFileDialog.getSaveFileName(
            self.view, f"Enregistrer {len(frames)} trame(s)", default, filters)
        if not path:
            return False
        if not os.path.splitext(path)[1]:
            path += ".npz" if selected.startswith("NumPy") else ".csv"
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            path = save_frames(frames, self.buffer.cfg, path)
        except (OSError, ValueError) as exc:
            QtWidgets.QMessageBox.warning(self.view, "Enregistrement impossible", str(exc))
            return False
        FrameBuffer.mark_saved(frames, path)
        for row in range(self.list.count()):
            self._label_item(self.list.item(row), self.buffer[row])
        self._update_label()
        self.message.emit(f"{len(frames)} trame(s) enregistrée(s) dans {path}")
        return True

    def confirm_unsaved(self, action: str) -> bool:
        """
        Trames non enregistrées : proposer de les enregistrer avant `action`.
        True : on peut continuer (enregistrées ou abandonnées) ; False : annulé.
        """
        unsaved = self.buffer.unsaved()
        if not unsaved:
            return True
        answer = self._ask(f"{len(unsaved)} trame(s) de la mémoire tampon n'ont pas été "
                           f"enregistrées.\nLes enregistrer avant de {action} ?")
        if answer == "save":
            return self.save_dialog()
        return answer == "discard"

    def _ask(self, text: str) -> str:
        """Enregistrer / Ne pas enregistrer / Annuler -> "save", "discard", "cancel"."""
        box = QtWidgets.QMessageBox(self.view)
        box.setIcon(QtWidgets.QMessageBox.Icon.Question)
        box.setWindowTitle("Trames non enregistrées")
        box.setText(text)
        buttons = QtWidgets.QMessageBox.StandardButton
        box.setStandardButtons(buttons.Save | buttons.Discard | buttons.Cancel)
        box.setDefaultButton(buttons.Save)
        box.exec()
        # bouton cliqué (Échap : Annuler) ; exec() renvoie un entier, pas un StandardButton
        clicked = box.standardButton(box.clickedButton())
        return {buttons.Save: "save", buttons.Discard: "discard"}.get(clicked, "cancel")

    def confirm_quit(self) -> bool:
        return self.confirm_unsaved("quitter")

    def prepare_start(self, cfg: LoggerConfig) -> bool:
        """
        Avant une acquisition : une autre disposition de voies vide la mémoire tampon
        (après proposition d'enregistrer). False : démarrage annulé.
        """
        if self.buffer.compatible(cfg):
            return True
        if not self.confirm_unsaved("changer de configuration de voies (la mémoire "
                                    "tampon sera vidée)"):
            return False
        self.clear()
        return True

    # ------------------------------------------------------------------ affichage
    def _update_label(self):
        n, cap = len(self.buffer), self.buffer.capacity
        text = f"{n} / {cap} trames en mémoire ({self.buffer.memory_bytes() / 1e6:.1f} Mo)"
        unsaved = len(self.buffer.unsaved())
        if unsaved:
            text += f" — {unsaved} non enregistrée(s)"
        if self.reviewing is not None:
            position = self.buffer.position(self.reviewing)
            where = (f"{position + 1}/{n}" if position >= 0
                     else "n'est plus en mémoire tampon")
            text += (f"\nRelecture : trame {self.reviewing.index} ({where}) — "
                     f"Alt+Fin : direct")
        self.view.bufferLabel.setText(text)
        self.view.actionLiveFrame.setEnabled(self.reviewing is not None)
        self.view.actionPrevFrame.setEnabled(n > 1 or (n == 1 and self.live))
        self.view.actionNextFrame.setEnabled(self.reviewing is not None)
        self.view.actionSaveBuffer.setEnabled(n > 0)


def layout_differs(a: LoggerConfig | None, b: LoggerConfig | None) -> bool:
    return a is None or b is None or layout_key(a) != layout_key(b)
