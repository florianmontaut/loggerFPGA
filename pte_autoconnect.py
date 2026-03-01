
import sys
import re
import json
import platform
import subprocess
from dataclasses import dataclass

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QTextEdit, QLineEdit, QGroupBox, QMessageBox
)

# Scapy: ARP via srp (couche 2) [1](https://mibs.observium.org/mib/LLDP-MIB/)[2](https://www.h3c.com/en/d_202506/2543643_294551_0.htm)
from scapy.all import ARP, Ether, srp, get_if_list  # type: ignore

TARGET_IP_DEFAULT = "172.16.0.1"
LOCAL_IP_DEFAULT  = "172.16.0.3"
NETMASK_DEFAULT   = "255.255.255.0"


@dataclass
class DetectionResult:
    scapy_iface: str | None = None   # ex: \Device\NPF_{GUID} ou nom Scapy
    remote_mac: str | None = None
    netsh_name: str | None = None    # ex: "Ethernet 2"


def run_cmd(cmd: list[str], timeout=10) -> tuple[int, str, str]:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def append_log(log_cb, s: str):
    log_cb(s)


# ---------- Mapping Npcap/Scapy iface -> Windows netsh "Name" ----------

_GUID_RE = re.compile(r"\{[0-9A-Fa-f-]{36}\}")

def extract_guid_from_scapy_iface(s: str) -> str | None:
    """
    Extrait un GUID {xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx} depuis une string Scapy/Npcap
    typiquement: \\Device\\NPF_{GUID}
    """
    m = _GUID_RE.search(s)
    return m.group(0) if m else None


def get_netadapters_name_by_guid() -> dict[str, str]:
    """
    Récupère la table {InterfaceGuid -> Name} via PowerShell Get-NetAdapter.
    On convertit en JSON pour parsing fiable.
    """
    ps = (
        "Get-NetAdapter | "
        "Select-Object -Property Name, InterfaceGuid | "
        "ConvertTo-Json -Compress"
    )
    rc, out, err = run_cmd(["powershell", "-NoProfile", "-Command", ps], timeout=10)
    if rc != 0 or not out:
        raise RuntimeError(f"Get-NetAdapter a échoué: {err or out}")

    data = json.loads(out)
    # ConvertTo-Json renvoie un objet si un seul adapter, sinon une liste
    if isinstance(data, dict):
        data = [data]

    mapping = {}
    for item in data:
        guid = str(item.get("InterfaceGuid", "")).strip()
        name = str(item.get("Name", "")).strip()
        if guid and name:
            # guid peut être sans accolades selon versions PS, on normalise:
            guid_norm = guid if guid.startswith("{") else "{" + guid + "}"
            mapping[guid_norm.lower()] = name
    return mapping


def scapy_iface_to_netsh_name(log_cb, scapy_iface: str) -> str | None:
    """
    Tente de convertir une interface Scapy/Npcap vers le nom d'interface Windows utilisé par netsh.
    Stratégie:
      1) Si scapy_iface contient un GUID, on mappe via Get-NetAdapter (InterfaceGuid -> Name).
      2) Sinon, on tente de l'utiliser tel quel (parfois Scapy retourne déjà un nom exploitable).
    """
    guid = extract_guid_from_scapy_iface(scapy_iface)
    if guid:
        append_log(log_cb, f"GUID détecté dans l'interface Scapy: {guid}")
        mapping = get_netadapters_name_by_guid()
        netsh_name = mapping.get(guid.lower())
        if netsh_name:
            append_log(log_cb, f"Mapping GUID -> netsh Name: {netsh_name}")
            return netsh_name
        append_log(log_cb, "GUID non trouvé dans Get-NetAdapter (mapping impossible).")

    # fallback : parfois ça marche si name correspond déjà
    append_log(log_cb, "Fallback: utilisation directe du nom d'interface Scapy pour netsh.")
    return scapy_iface


# ---------- Détection ARP sur une interface ----------

def is_loopback(iface: str) -> bool:
    return iface.lower() in {"lo", "loopback"}


def arp_probe_on_interface(iface: str, target_ip: str, timeout_s: float = 1.0) -> str | None:
    """
    Envoie Ethernet broadcast + ARP who-has(target_ip) sur `iface`,
    retourne la MAC distante si réponse.
    Utilise srp() (send/receive L2) recommandé pour ARP. [1](https://mibs.observium.org/mib/LLDP-MIB/)[2](https://www.h3c.com/en/d_202506/2543643_294551_0.htm)
    """
    pkt = Ether(dst="ff:ff:ff:ff:ff:ff") / ARP(pdst=target_ip)
    ans, _ = srp(pkt, iface=iface, timeout=timeout_s, retry=0, verbose=False)
    for _, rcv in ans:
        if rcv and rcv.haslayer(ARP):
            return rcv[ARP].hwsrc
    return None


# ---------- Configuration IP Windows via netsh ----------

def set_ip_windows_netsh(log_cb, netsh_if_name: str, ip: str, mask: str) -> bool:
    """
    Configure une IP statique via netsh:
      netsh interface ipv4 set address name="IF" static IP MASK GATEWAY
    (Syntaxe documentée et largement utilisée.) [3](https://community.cisco.com/t5/switches-small-business/getting-mac-address-table-through-snmp-on-cisco-switch/td-p/4537136)[4](https://irp.nain-t.net/doku.php/215snmp:70_exercice-pratique)
    """
    # Essai sans gateway (none), puis fallback 0.0.0.0.
    cmd1 = [
        "netsh", "interface", "ipv4", "set", "address",
        f'name="{netsh_if_name}"', "static", ip, mask, "none"
    ]
    append_log(log_cb, "$ " + " ".join(cmd1))
    rc, out, err = run_cmd(cmd1, timeout=10)
    if out:
        append_log(log_cb, out)
    if err:
        append_log(log_cb, err)
    if rc == 0:
        return True

    cmd2 = [
        "netsh", "interface", "ipv4", "set", "address",
        f'name="{netsh_if_name}"', "static", ip, mask, "0.0.0.0"
    ]
    append_log(log_cb, "$ " + " ".join(cmd2))
    rc, out, err = run_cmd(cmd2, timeout=10)
    if out:
        append_log(log_cb, out)
    if err:
        append_log(log_cb, err)
    return rc == 0


# ---------- Worker thread ----------

class DetectorThread(QThread):
    progress = pyqtSignal(str)
    finished_ok = pyqtSignal(object)   # DetectionResult
    finished_fail = pyqtSignal(str)

    def __init__(self, target_ip: str):
        super().__init__()
        self.target_ip = target_ip

    def run(self):
        try:
            if platform.system().lower() != "windows":
                self.finished_fail.emit("Ce script est prévu uniquement pour Windows.")
                return

            ifaces = [i for i in get_if_list() if not is_loopback(i)]
            if not ifaces:
                self.finished_fail.emit("Aucune interface réseau détectée.")
                return

            self.progress.emit(f"Interfaces candidates (Scapy): {', '.join(ifaces)}")

            for iface in ifaces:
                self.progress.emit(f"ARP probe sur {iface} -> {self.target_ip} ...")
                mac = arp_probe_on_interface(iface, self.target_ip, timeout_s=1.0)
                if mac:
                    self.progress.emit(f"Réponse ARP reçue sur {iface} (MAC distante: {mac})")

                    # mapping netsh name
                    def _log(s): self.progress.emit(s)
                    netsh_name = scapy_iface_to_netsh_name(_log, iface)

                    self.finished_ok.emit(DetectionResult(
                        scapy_iface=iface,
                        remote_mac=mac,
                        netsh_name=netsh_name
                    ))
                    return

            self.finished_fail.emit(
                "Aucune réponse ARP reçue.\n"
                "Vérifie le câble, que l'équipement est alimenté et que son IP est bien 172.16.0.1."
            )
        except PermissionError:
            self.finished_fail.emit(
                "Permissions insuffisantes.\n"
                "Lance l'application en Administrateur (Scapy ARP + netsh nécessitent des droits)."
            )
        except Exception as e:
            self.finished_fail.emit(f"Erreur détection: {e}")


# ---------- GUI ----------

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PTE Windows - Détection interface (ARP) + Auto-IP (netsh)")
        self.resize(900, 540)

        self.detected: DetectionResult | None = None

        # Inputs
        self.target_ip = QLineEdit(TARGET_IP_DEFAULT)
        self.local_ip  = QLineEdit(LOCAL_IP_DEFAULT)
        self.netmask   = QLineEdit(NETMASK_DEFAULT)

        # Status + log
        self.status = QLabel("Statut: prêt")
        self.status.setStyleSheet("font-weight: 600;")
        self.log = QTextEdit()
        self.log.setReadOnly(True)

        # Buttons
        self.btn_detect = QPushButton("1) Détecter le port connecté (ARP)")
        self.btn_cfg    = QPushButton("2) Configurer 172.16.0.3/24 via netsh")
        self.btn_cfg.setEnabled(False)

        self.btn_detect.clicked.connect(self.on_detect)
        self.btn_cfg.clicked.connect(self.on_configure)

        # Layout
        root = QVBoxLayout(self)

        params = QGroupBox("Paramètres")
        pl = QHBoxLayout(params)
        pl.addWidget(QLabel("IP équipement:"))
        pl.addWidget(self.target_ip)
        pl.addSpacing(15)
        pl.addWidget(QLabel("IP PTE:"))
        pl.addWidget(self.local_ip)
        pl.addSpacing(15)
        pl.addWidget(QLabel("Masque:"))
        pl.addWidget(self.netmask)

        root.addWidget(params)

        hl = QHBoxLayout()
        hl.addWidget(self.btn_detect)
        hl.addWidget(self.btn_cfg)
        root.addLayout(hl)

        root.addWidget(self.status)
        root.addWidget(self.log, stretch=1)

    def append_log(self, s: str):
        self.log.append(s)

    def set_status(self, s: str):
        self.status.setText(f"Statut: {s}")

    def on_detect(self):
        self.btn_detect.setEnabled(False)
        self.btn_cfg.setEnabled(False)
        self.detected = None

        t_ip = self.target_ip.text().strip()
        self.append_log(f"--- Détection ARP vers {t_ip} ---")
        self.set_status("détection en cours...")

        self.th = DetectorThread(t_ip)
        self.th.progress.connect(self.append_log)
        self.th.finished_ok.connect(self.on_detect_ok)
        self.th.finished_fail.connect(self.on_detect_fail)
        self.th.start()

    def on_detect_ok(self, res: DetectionResult):
        self.detected = res
        self.append_log("")
        self.append_log("=== Résultat détection ===")
        self.append_log(f"Interface Scapy/Npcap : {res.scapy_iface}")
        self.append_log(f"Nom netsh Windows     : {res.netsh_name}")
        self.append_log(f"MAC équipement        : {res.remote_mac}")
        self.append_log("=========================")
        self.append_log("")

        self.set_status(f"interface trouvée: {res.netsh_name}")
        self.btn_detect.setEnabled(True)
        self.btn_cfg.setEnabled(True)

    def on_detect_fail(self, err: str):
        self.append_log(f"[ERREUR] {err}")
        self.set_status("échec détection")
        self.btn_detect.setEnabled(True)
        QMessageBox.warning(self, "Détection échouée", err)

    def on_configure(self):
        if not self.detected or not self.detected.netsh_name:
            QMessageBox.information(self, "Info", "Aucune interface netsh détectée.")
            return

        ip = self.local_ip.text().strip()
        mask = self.netmask.text().strip()
        name = self.detected.netsh_name

        self.append_log(f"--- Configuration IP sur '{name}' ---")
        self.set_status("configuration IP en cours...")

        ok = set_ip_windows_netsh(self.append_log, name, ip, mask)  # [3](https://community.cisco.com/t5/switches-small-business/getting-mac-address-table-through-snmp-on-cisco-switch/td-p/4537136)[4](https://irp.nain-t.net/doku.php/215snmp:70_exercice-pratique)
        if ok:
            self.append_log("OK: IP configurée.")
            self.set_status("configuration OK")
        else:
            self.append_log("[ERREUR] Échec netsh (droits admin ? interface introuvable ?).")
            self.set_status("configuration KO")
            QMessageBox.critical(
                self, "Configuration échouée",
                "Impossible de configurer l'IP via netsh.\n"
                "Vérifie: exécution en Administrateur, et que l'interface existe."
            )


def main():
    if platform.system().lower() != "windows":
        print("Ce script est prévu uniquement pour Windows.")
        sys.exit(1)

    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
