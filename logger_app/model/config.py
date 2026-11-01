# model/config.py
"""
Configuration du logger FPGA (équivalent de l'en-tête de logger.m).

Une seule structure regroupe :
    - la liaison réseau (IP du FPGA, ports) ;
    - l'acquisition : voies, diviseur, délai, trigger, masque de disjonction, seuil ;
    - le déroulé : nombre de trames (0 = infini), enregistrement ;
    - la description des voies (noms, gains, unités) pour l'affichage et l'enregistrement.

Voies (comme logger.m) : `signals` est la liste des indices des voies à enregistrer
(0 à 14 : voies analogiques, 15 : mot des 16 voies logiques). Sa longueur donne le nombre
de canaux envoyé au FPGA (1, 2, 4 ou 8). La voie logique (15) ne peut être qu'en dernière
position. Le seuil (trigger > seuil / < seuil) porte sur la PREMIÈRE voie de la liste.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from enum import IntEnum

CLOCK_HZ = 25e6         # horloge du FPGA : fréquence d'échantillonnage = 25 MHz / diviseur
WORDS_PER_FRAME = 16384 # mots de 16 bits dans une trame de données (sd dans logger.m)
WORDS_PER_PACKET = 512  # mots de 16 bits par datagramme de données
FULL_SCALE = 16384      # 1 pu = 16384 points (data/16384 dans logger.m)
LOGIC_SIGNAL = 15       # indice du mot des voies logiques
VALID_CHANNEL_COUNTS = (1, 2, 4, 8)


class TriggerType(IntEnum):
    AUTO = 0            # enregistrement relancé par le PC (start_msg)
    TRIP = 1            # sur disjonction (masque `trip`)
    ABOVE = 2           # première voie > seuil
    BELOW = 4           # première voie < seuil

    @property
    def label(self) -> str:
        return TRIGGER_LABELS[self]


TRIGGER_LABELS = {
    TriggerType.AUTO:  "Automatique",
    TriggerType.TRIP:  "Disjonction",
    TriggerType.ABOVE: "> seuil",
    TriggerType.BELOW: "< seuil",
}

DEFAULT_ANALOG_NAMES = ["V_HV", "I_HV", "V_PH1_INV1", "I_PH1_INV1", "V_PH1_INV2",
                        "I_PH1_INV2", "V_PH1_INV1_RMS", "I_PH1_INV1_RMS", "V_PH1_INV2_RMS",
                        "I_PH1_INV2_RMS", "TEMP_AMB_PLS", "INV_MODUL_A", "INV_MODUL_B",
                        "INV_FREQ_A", "INV_FREQ_B"]
DEFAULT_LOGIC_NAMES = ["K_HV", "K_PRE"] + [f"L{i}" for i in range(2, 16)]


class ConfigError(ValueError):
    """Configuration incohérente (message affichable tel quel)."""


@dataclass
class LoggerConfig:
    # --- liaison ---
    ip_fpga:        str = "172.16.0.1"
    port_cmd:       int = 9          # port de sélection du port/IP du PC (port_msg)
    port_fpga:      int = 2064       # port des échanges avec le logger
    local_ip:       str = ""         # "" : toutes les interfaces
    local_port:     int = 2064
    # --- acquisition ---
    signals:        list[int] = field(default_factory=lambda: [0])
    divider:        int = 20         # 1 à 65535
    delay:          int = 0          # 0 à 65535
    trigger:        int = TriggerType.AUTO
    trip_mask:      int = 0x00010000 # masque des disjonctions (32 bits)
    threshold:      int = 0          # seuil brut, -32768 à 32767, sur signals[0]
    # --- déroulé ---
    max_frames:     int = 0          # 0 : infini
    record:         bool = False
    record_dir:     str = "."
    record_prefix:  str = "enr"
    record_format:  str = "csv"      # "csv" ou "npz"
    # --- description des voies ---
    analog_names:   list[str] = field(default_factory=lambda: list(DEFAULT_ANALOG_NAMES))
    logic_names:    list[str] = field(default_factory=lambda: list(DEFAULT_LOGIC_NAMES))
    # valeur physique d'une mesure à 1 pu (16384 points) : ch_gain dans logger.m
    gains:          list[float] = field(default_factory=lambda: [100.0] * 15)
    units:          list[str] = field(default_factory=lambda: [""] * 15)

    # ------------------------------------------------------------------ dérivées
    @property
    def n_channels(self) -> int:
        return len(self.signals)

    @property
    def has_logic(self) -> bool:
        return bool(self.signals) and self.signals[-1] == LOGIC_SIGNAL

    @property
    def analog_signals(self) -> list[int]:
        return [s for s in self.signals if s != LOGIC_SIGNAL]

    @property
    def samples_per_channel(self) -> int:
        return WORDS_PER_FRAME // self.n_channels

    @property
    def packets_per_frame(self) -> int:
        return WORDS_PER_FRAME // WORDS_PER_PACKET

    @property
    def sample_rate(self) -> float:
        return CLOCK_HZ / self.divider

    @property
    def frame_duration(self) -> float:
        """Durée d'une trame (s), par canal."""
        return self.samples_per_channel / self.sample_rate

    @property
    def tempo(self) -> float:
        """Pause entre deux trames (s) : tempo = sd*div/25e6 + 1 ms dans logger.m."""
        return WORDS_PER_FRAME * self.divider / CLOCK_HZ + 1e-3

    @property
    def trigger_type(self) -> TriggerType:
        return TriggerType(self.trigger)

    @property
    def threshold_signal(self) -> int | None:
        """Voie sur laquelle porte le seuil (première de la liste) ; None si logique."""
        first = self.signals[0] if self.signals else None
        return None if first in (None, LOGIC_SIGNAL) else first

    def analog_name(self, sig: int) -> str:
        return self.analog_names[sig] if sig < len(self.analog_names) else f"A{sig}"

    def logic_name(self, bit: int) -> str:
        return self.logic_names[bit] if bit < len(self.logic_names) else f"L{bit}"

    def gain(self, sig: int) -> float:
        return float(self.gains[sig]) if sig < len(self.gains) else 1.0

    def unit(self, sig: int) -> str:
        return self.units[sig] if sig < len(self.units) else ""

    def threshold_physical(self) -> float | None:
        sig = self.threshold_signal
        return None if sig is None else self.threshold * self.gain(sig) / FULL_SCALE

    def threshold_from_physical(self, value: float) -> int:
        """Seuil brut correspondant à une valeur physique sur la voie de seuil."""
        sig = self.threshold_signal
        if sig is None or self.gain(sig) == 0:
            raise ConfigError("Le seuil doit porter sur une voie analogique")
        raw = round(value * FULL_SCALE / self.gain(sig))
        return max(-32768, min(32767, raw))

    def set_threshold_signal(self, sig: int) -> None:
        """
        Place `sig` en première position de la liste des voies (le FPGA compare la
        première voie au seuil), l'ordre des autres voies étant conservé.
        """
        if sig not in self.signals:
            raise ConfigError(f"La voie {sig} n'est pas enregistrée")
        if sig == LOGIC_SIGNAL:
            raise ConfigError("Le seuil ne peut pas porter sur les voies logiques")
        rest = [s for s in self.signals if s != sig]
        self.signals = [sig] + rest

    # ------------------------------------------------------------------ contrôle
    def validate(self) -> None:
        n = self.n_channels
        if n not in VALID_CHANNEL_COUNTS:
            raise ConfigError("Le nombre de voies doit être de 1, 2, 4 ou 8 "
                              f"(actuellement {n})")
        if any(not 0 <= s <= LOGIC_SIGNAL for s in self.signals):
            raise ConfigError("Les indices de voies doivent être compris entre 0 et 15")
        if LOGIC_SIGNAL in self.signals[:-1]:
            raise ConfigError("La voie logique (15) doit être en dernière position")
        if len(set(self.signals)) != n:
            raise ConfigError("Une même voie est sélectionnée plusieurs fois")
        if not 1 <= self.divider <= 65535:
            raise ConfigError("Le diviseur doit être compris entre 1 et 65535")
        if not 0 <= self.delay <= 65535:
            raise ConfigError("Le délai doit être compris entre 0 et 65535")
        try:
            trig = TriggerType(self.trigger)
        except ValueError:
            raise ConfigError(f"Type de trigger inconnu : {self.trigger}") from None
        if not 0 <= self.trip_mask <= 0xFFFFFFFF:
            raise ConfigError("Le masque de disjonction doit tenir sur 32 bits")
        if not -32768 <= self.threshold <= 32767:
            raise ConfigError("Le seuil doit être compris entre -32768 et 32767")
        if trig in (TriggerType.ABOVE, TriggerType.BELOW) and self.threshold_signal is None:
            raise ConfigError("Trigger sur seuil : la première voie doit être analogique")
        if self.max_frames < 0:
            raise ConfigError("Le nombre de trames doit être positif (0 = infini)")

    # ------------------------------------------------------------------ JSON
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "LoggerConfig":
        names = {f.name for f in fields(cls)}
        # compatibilité avec ressources/parametres_scope.json de logger_FPGA
        legacy = {"remote_port_fpga": "port_fpga", "target_port_fpga": "port_cmd",
                  "channels_config": "signals", "type_trigger": "trigger",
                  "trigger_thres": "threshold", "ana_channel_names": "analog_names",
                  "digi_channel_names": "logic_names"}
        kwargs = {}
        for key, value in data.items():
            key = legacy.get(key, key)
            if key in names:
                kwargs[key] = value
        if isinstance(data.get("trip"), str):
            kwargs["trip_mask"] = int(data["trip"], 16)
        if "channels_config" in data and "gains" in data:
            # l'ancien format donne le gain par point : ramené à la valeur à 1 pu
            kwargs["gains"] = [g * FULL_SCALE for g in data["gains"]][:15]
        if data.get("n_ana_channels") == LOGIC_SIGNAL:
            kwargs["signals"] = [LOGIC_SIGNAL]
        cfg = cls(**kwargs)
        cfg.analog_names = list(cfg.analog_names)[:15]
        cfg.signals = [int(s) for s in cfg.signals]
        return cfg

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls, path: str) -> "LoggerConfig":
        with open(path, encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

    def copy(self) -> "LoggerConfig":
        return LoggerConfig.from_dict(json.loads(json.dumps(self.to_dict())))
