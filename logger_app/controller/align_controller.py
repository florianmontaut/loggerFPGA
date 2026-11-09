# controller/align_controller.py
"""
Recalage de voies dans le temps (comme « Align in time » du GLviewer,
controller/alignment_controller.py) : deux appareils déclenchés l'un par l'autre (un
PicoScope par son entrée auxiliaire reliée au Tektronix...) ne sont pas synchronisés à
mieux que quelques microsecondes. Les voies d'un appareil sont décalées à vue sur un
événement commun.

Pendant le recalage, les courbes des voies choisies suivent l'écart en direct (elles sont
tracées décalées, rien n'est relu ni écrit) ; les autres sont estompées :

    - poignée ⇔ : glisser pour décaler les courbes ;
    - barre : écart saisi, pas de ±1 et ±10 échantillons ;
    - lignes A (événement des voies recalées) et B (même événement sur la référence) :
      « Aligner A sur B » ajoute l'écart B - A.

À la validation, l'écart est ajouté au décalage des voies dans le workspace (attribut
time_shift, model/scope_record.py) : les échantillons ne sont pas modifiés, et le
décalage se retire (« Remettre à zéro »).
"""
from __future__ import annotations

import pyqtgraph as pg
from PyQt6 import QtCore, QtGui, QtWidgets

from view.align_panel import AlignChannelsDialog, AlignPanel, signed

ORANGE, BLUE, GREEN = (230, 120, 0), (0, 150, 220), (40, 170, 60)


class AlignController(QtCore.QObject):

    message = QtCore.pyqtSignal(str)

    HINT = ("Recalage : glissez la poignée ⇔ (ou saisissez l'écart), ou placez A sur un "
            "événement des voies recalées et B sur le même événement de la référence puis "
            "« Aligner A sur B ». Entrée : valider, Échap : annuler.")

    def __init__(self, view, graph_ctrl, scope_ctrl):
        super().__init__()
        self.view = view
        self.graph = graph_ctrl
        self.scope = scope_ctrl
        self.names: list[str] = []          # voies en cours de recalage
        self.delta = 0.0
        self.sample = 0.0
        self.panel: AlignPanel | None = None
        self._items = []
        self._shortcuts = []
        # choix des voies : (enregistrement) -> (voies, "shift" | "reset") ou None
        self.choose = self._ask
        scope_ctrl.closing.connect(self.cancel)

    @property
    def active(self) -> bool:
        return bool(self.names)

    # ------------------------------------------------------------------ choix des voies
    @staticmethod
    def default_names(record) -> set:
        """Voies du dernier fichier ajouté, s'il y a plusieurs fichiers d'origine."""
        sources = [record.sources.get(name, "") for name in record.names]
        if len(set(sources)) < 2:
            return set()
        return {name for name, source in zip(record.names, sources) if source == sources[-1]}

    def _ask(self, record):
        dialog = AlignChannelsDialog(record.names, record.sources, record.shifts,
                                     self.default_names(record), self.view)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted or not dialog.names():
            return None
        return dialog.names(), dialog.action

    def start_dialog(self):
        """Action « Recaler des voies dans le temps... »."""
        record = self.scope.record
        if record is None:
            return
        self.cancel()
        choice = self.choose(record)
        if not choice:
            return
        names, action = choice
        if action == "reset":
            if self.scope.apply_time_shifts({name: 0.0 for name in names}):
                self.message.emit(f"Décalage remis à zéro : {', '.join(names)}")
        else:
            self.start(names)

    # ------------------------------------------------------------------ début / fin
    def start(self, names: list[str]) -> bool:
        record = self.scope.record
        names = [n for n in names if record is not None and n in record.names]
        if not names:
            return False
        self.cancel()
        self.names = names
        self.delta = 0.0
        self.sample = min(record.timebases[n].dt for n in names)
        self._keys = [("A", record.names.index(n)) for n in names]
        self.graph.set_faded(set(self.graph.curves) - set(self._keys))
        plot = self.graph.analog_plot
        x0, x1 = plot.vb.viewRange()[0]
        span = x1 - x0
        self.handle = pg.InfiniteLine(
            pos=x0 + span / 2, movable=True,
            pen=pg.mkPen(ORANGE, width=2, style=QtCore.Qt.PenStyle.DashLine),
            label="⇔ décaler", labelOpts={"position": 0.95, "color": ORANGE,
                                           "movable": False})
        self._handle_origin = self.handle.value()
        self.handle.sigPositionChanged.connect(self._on_handle_moved)
        self.point_a = pg.InfiniteLine(
            pos=x0 + span / 3, movable=True, pen=pg.mkPen(BLUE, width=2),
            label="A : voie recalée", labelOpts={"position": 0.85, "color": BLUE})
        self._a = self.point_a.value()      # instant A avant écart
        self.point_a.sigPositionChanged.connect(self._on_a_moved)
        self.point_b = pg.InfiniteLine(
            pos=x0 + 2 * span / 3, movable=True, pen=pg.mkPen(GREEN, width=2),
            label="B : référence", labelOpts={"position": 0.78, "color": GREEN})
        self._items = [self.handle, self.point_a, self.point_b]
        for item in self._items:
            item.setZValue(30)
            plot.addItem(item, ignoreBounds=True)

        self.panel = AlignPanel(", ".join(names), self.sample)
        self.panel.offset.sigValueChanging.connect(lambda _sb, value: self.set_delta(value))
        for step, button in self.panel.step_buttons.items():
            button.clicked.connect(
                lambda _=False, s=step: self.set_delta(self.delta + s * self.sample))
        self.panel.align_button.clicked.connect(self.align_points)
        self.panel.validate_button.clicked.connect(self.validate)
        self.panel.cancel_button.clicked.connect(self.cancel)
        bar = self.view.statusBar()
        self.panel.setToolTip(self.HINT)       # la barre ne laisse pas la place du message
        bar.addPermanentWidget(self.panel)
        for key, slot in ((QtCore.Qt.Key.Key_Return, self.validate),
                          (QtCore.Qt.Key.Key_Enter, self.validate),
                          (QtCore.Qt.Key.Key_Escape, self.cancel)):
            shortcut = QtGui.QShortcut(QtGui.QKeySequence(key), self.view)
            shortcut.setContext(QtCore.Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(slot)
            self._shortcuts.append(shortcut)
        self._show_delta()
        return True

    def validate(self):
        """Écart ajouté au décalage des voies, dans le workspace."""
        if not self.active:
            return
        names, delta = self.names, self.delta
        record = self.scope.record
        self._finish()
        if not delta or record is None:
            self.message.emit("Recalage : écart nul, rien n'est modifié")
            return
        shifts = {name: record.shifts.get(name, 0.0) + delta for name in names}
        if self.scope.apply_time_shifts(shifts):
            self.message.emit(f"Voies recalées de {signed(delta)} : {', '.join(names)}")

    def cancel(self):
        if self.active:
            self._finish()

    def _finish(self):
        self.names = []
        self.graph.set_x_shift({})
        self.graph.set_faded(())
        for item in self._items:
            self.graph.analog_plot.removeItem(item)
        self._items = []
        for shortcut in self._shortcuts:
            shortcut.setEnabled(False)
            shortcut.deleteLater()
        self._shortcuts = []
        if self.panel is not None:
            self.view.statusBar().removeWidget(self.panel)
            self.panel.deleteLater()
            self.panel = None

    # ------------------------------------------------------------------ écart
    def set_delta(self, delta: float):
        if not self.active:
            return
        self.delta = float(delta)
        self._show_delta()
        self.graph.set_x_shift({key: self.delta for key in self._keys})

    def _show_delta(self):
        with QtCore.QSignalBlocker(self.panel.offset):
            self.panel.offset.setValue(self.delta)
        samples = self.delta / self.sample if self.sample else 0.0
        self.panel.readable.setText(f"{signed(self.delta)} ({samples:+.4g} éch.)")
        with QtCore.QSignalBlocker(self.handle):
            self.handle.setValue(self._handle_origin + self.delta)
        with QtCore.QSignalBlocker(self.point_a):
            self.point_a.setValue(self._a + self.delta)     # A reste sur son événement

    def _on_handle_moved(self, line):
        self.set_delta(line.value() - self._handle_origin)

    def _on_a_moved(self, line):
        self._a = line.value() - self.delta

    def align_points(self):
        """A (événement des voies recalées) placé sur B (même événement de la référence)."""
        self.set_delta(self.delta + self.point_b.value() - self.point_a.value())
