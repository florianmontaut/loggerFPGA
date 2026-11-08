# controller/channel_tree_controller.py
"""
Arborescence des voies (comme l'arbre « Par voie » du GLviewer, simplifiée) :

    Logger 172.16.0.1  (25 MHz / 20 = 1,25 MHz)
      ├─ Voies analogiques
      │    ├─ [x] V_PH1_INV2      12.3   V      <- case : courbe visible
      │    └─ ...
      └─ Voies logiques
           ├─ [x] K_HV            1
           └─ ...

La colonne « Valeur » affiche la valeur sous le curseur du graphique (ou, sans curseur, la
dernière valeur de la trame). La clé d'une voie est ("A", indice) ou ("L", bit).
"""
from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets

from model.config import LoggerConfig
from model import measures
from ressources import pens

KEY_ROLE = QtCore.Qt.ItemDataRole.UserRole + 1


class ChannelTreeController(QtCore.QObject):

    visibility_changed = QtCore.pyqtSignal(object, bool)   # clé, visible
    channel_selected = QtCore.pyqtSignal(object)            # clé

    COLUMNS = ["Voie", "Valeur", "Unité", "Δ t2−t1"]
    DELTA = 3

    def __init__(self, view: QtWidgets.QTreeView):
        super().__init__()
        self.view = view
        self.model = QtGui.QStandardItemModel()
        self.model.setHorizontalHeaderLabels(self.COLUMNS)
        self.view.setModel(self.model)
        self.items: dict[tuple, list[QtGui.QStandardItem]] = {}
        self.hidden: set[tuple] = set()      # conservé d'une configuration à l'autre
        self.model.itemChanged.connect(self._on_item_changed)
        self.view.selectionModel().currentChanged.connect(self._on_current_changed)
        header = self.view.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.view.setColumnHidden(self.DELTA, True)   # visible avec les curseurs verticaux

    def build(self, cfg: LoggerConfig):
        self._building = True
        self.model.removeRows(0, self.model.rowCount())
        self.items.clear()
        fs = cfg.sample_rate
        if cfg.source_name:                     # enregistrement long d'oscilloscope
            root = self._row(cfg.source_name, measures.si(fs, "Hz", 4), "")
        else:
            root = self._row(f"Logger {cfg.ip_fpga}", f"{fs / 1e3:.6g} kHz", "")
        if cfg.source_name:
            root[0].setToolTip(f"{cfg.samples_per_channel:,} points par voie "
                               f"({measures.si(cfg.frame_duration, 's')})".replace(",", " "))
        else:
            root[0].setToolTip(f"25 MHz / {cfg.divider} — {cfg.samples_per_channel} points "
                               f"par voie ({cfg.frame_duration * 1e3:.4g} ms)")
        self.model.appendRow(root)
        if cfg.analog_signals:
            group = self._row("Voies analogiques", "", "")
            root[0].appendRow(group)
            for rank, sig in enumerate(cfg.analog_signals):
                name = cfg.analog_name(sig)
                if rank == 0 and cfg.trigger_type in (cfg.trigger_type.ABOVE,
                                                      cfg.trigger_type.BELOW):
                    name += "  (seuil)"
                self._channel(group[0], ("A", sig), name, cfg.unit(sig), pens.analog_color(sig))
                if rank < len(cfg.channel_tips) and ("A", sig) in self.items:
                    self.items[("A", sig)][0].setToolTip(cfg.channel_tips[rank])
        if cfg.has_logic:
            group = self._row("Voies logiques", "", "")
            root[0].appendRow(group)
            for bit in range(16):
                self._channel(group[0], ("L", bit), cfg.logic_name(bit), "",
                              pens.logic_color(bit))
        self._math_group = None
        self._building = False
        self.view.expandAll()

    def set_math_channels(self, channels: list[tuple[str, str]]):
        """Groupe « Voies calculées » : [(nom, unité)], sous les voies analogiques."""
        root = self.model.item(0)
        if root is None:
            return
        self._building = True
        group = getattr(self, "_math_group", None)
        if group is not None:
            for key in [k for k in self.items if k[0] == "M"]:
                del self.items[key]
            root.removeRow(group.row())
            self._math_group = None
        if channels:
            row = self._row("Voies calculées", "", "")
            has_analog = root.rowCount() and root.child(0).text() == "Voies analogiques"
            root.insertRow(1 if has_analog else 0, row)
            self._math_group = row[0]
            for i, (name, unit) in enumerate(channels):
                self._channel(row[0], ("M", name), name, unit, pens.math_color(i))
        self._building = False
        if channels:
            self.view.expand(self._math_group.index())

    def _row(self, *texts):
        row = [QtGui.QStandardItem(t) for t in texts]
        for item in row:
            item.setEditable(False)
        return row

    def _channel(self, parent, key, name, unit, color):
        row = self._row(name, "", unit, "")
        row[0].setCheckable(True)
        row[0].setCheckState(QtCore.Qt.CheckState.Unchecked if key in self.hidden
                             else QtCore.Qt.CheckState.Checked)
        row[0].setIcon(pens.swatch(color))
        row[0].setData(key, KEY_ROLE)
        for item in (row[1], row[self.DELTA]):
            item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignRight
                                  | QtCore.Qt.AlignmentFlag.AlignVCenter)
        parent.appendRow(row)
        self.items[key] = row

    def is_visible(self, key) -> bool:
        return key not in self.hidden

    def set_values(self, values: dict, column: int = 1):
        """values : clé -> valeur (float) ; les autres voies sont vidées."""
        for key, row in self.items.items():
            value = values.get(key)
            if value is None:
                text = ""
            elif value != value:                # NaN : hors de l'étendue de la voie
                text = "—"
            elif key[0] == "L":
                text = f"{int(value):+d}" if column == self.DELTA else f"{int(value)}"
            else:
                text = f"{value:+.5g}" if column == self.DELTA else f"{value:.5g}"
            if row[column].text() != text:
                row[column].setText(text)

    def set_cursor_values(self, values: dict | None, deltas: dict | None):
        """
        Curseurs verticaux : valeur de chaque voie en t1 et Δ = y(t2) - y(t1) ;
        None : curseurs masqués, colonne Δ cachée.
        """
        active = values is not None
        self.view.setColumnHidden(self.DELTA, not active)
        self.model.setHeaderData(1, QtCore.Qt.Orientation.Horizontal,
                                 "Valeur (t1)" if active else "Valeur")
        if active:
            self.set_values(values)
            self.set_values(deltas or {}, self.DELTA)

    def _on_item_changed(self, item: QtGui.QStandardItem):
        # construction en cours : cases cochées par le programme, pas par l'utilisateur.
        # (Les signaux du modèle ne sont pas bloqués : la vue doit être prévenue des
        # lignes ajoutées et retirées, sinon elle garde des index périmés et plante.)
        if getattr(self, "_building", False):
            return
        key = item.data(KEY_ROLE)
        if key is None or not item.isCheckable():
            return
        visible = item.checkState() == QtCore.Qt.CheckState.Checked
        (self.hidden.discard if visible else self.hidden.add)(key)
        self.visibility_changed.emit(key, visible)

    def _on_current_changed(self, current: QtCore.QModelIndex, _previous):
        key = current.siblingAtColumn(0).data(KEY_ROLE)
        if key is not None:
            self.channel_selected.emit(key)
