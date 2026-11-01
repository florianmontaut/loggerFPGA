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
from ressources import pens

KEY_ROLE = QtCore.Qt.ItemDataRole.UserRole + 1


class ChannelTreeController(QtCore.QObject):

    visibility_changed = QtCore.pyqtSignal(object, bool)   # clé, visible
    channel_selected = QtCore.pyqtSignal(object)            # clé

    COLUMNS = ["Voie", "Valeur", "Unité"]

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

    def build(self, cfg: LoggerConfig):
        self.model.blockSignals(True)
        self.model.removeRows(0, self.model.rowCount())
        self.items.clear()
        fs = cfg.sample_rate
        root = self._row(f"Logger {cfg.ip_fpga}", f"{fs / 1e3:.6g} kHz", "")
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
        if cfg.has_logic:
            group = self._row("Voies logiques", "", "")
            root[0].appendRow(group)
            for bit in range(16):
                self._channel(group[0], ("L", bit), cfg.logic_name(bit), "",
                              pens.logic_color(bit))
        self.model.blockSignals(False)
        self.view.expandAll()

    def _row(self, *texts):
        row = [QtGui.QStandardItem(t) for t in texts]
        for item in row:
            item.setEditable(False)
        return row

    def _channel(self, parent, key, name, unit, color):
        row = self._row(name, "", unit)
        row[0].setCheckable(True)
        row[0].setCheckState(QtCore.Qt.CheckState.Unchecked if key in self.hidden
                             else QtCore.Qt.CheckState.Checked)
        row[0].setIcon(pens.swatch(color))
        row[0].setData(key, KEY_ROLE)
        row[1].setTextAlignment(QtCore.Qt.AlignmentFlag.AlignRight
                                | QtCore.Qt.AlignmentFlag.AlignVCenter)
        parent.appendRow(row)
        self.items[key] = row

    def is_visible(self, key) -> bool:
        return key not in self.hidden

    def set_values(self, values: dict):
        """values : clé -> valeur (float) ; les autres voies sont vidées."""
        for key, row in self.items.items():
            value = values.get(key)
            if value is None:
                text = ""
            elif key[0] == "L":
                text = f"{int(value)}"
            else:
                text = f"{value:.5g}"
            if row[1].text() != text:
                row[1].setText(text)

    def _on_item_changed(self, item: QtGui.QStandardItem):
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
