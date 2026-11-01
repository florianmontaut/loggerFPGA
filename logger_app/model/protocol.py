# model/protocol.py
"""
Trames UDP échangées avec le logger du FPGA (traduction directe de logger.m).

Fonctions pures, sans Qt ni socket : testables seules et réutilisées par le simulateur.

Déroulé d'une acquisition :
    1. PORT_MSG  -> port 9      sélection du port UDP et de l'IP du PC de commande
    2. config    -> port 2064   configuration du logger (32 octets)
    3. pause `tempo`
    4. boucle sur les trames :
         START_MSG              uniquement en trigger automatique
         <- TRIG_MSG            le logger est déclenché
         READ_MSG               demande des données
         <- 32 x DATA_MSG       6 octets d'en-tête + 512 mots de 16 bits (big endian)
         pause `tempo`
    5. STOP_MSG                 arrêt du logger
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .config import FULL_SCALE, LOGIC_SIGNAL, WORDS_PER_PACKET, LoggerConfig

PORT_MSG  = bytes([0x80, 0x05, 0x55, 0xAA, 0x00, 0x00])
START_MSG = bytes([0x80, 0x01, 0xAA, 0x55, 0x00, 0x00])
READ_MSG  = bytes([0x80, 0x03, 0x55, 0x55, 0x00, 0x00])
STOP_MSG  = bytes([0x80, 0x06, 0xAA, 0xAA, 0x00, 0x00])
CONFIG_HEADER = bytes([0x80, 0x00])
TRIG_HEADER   = bytes([0x80, 0x02])
DATA_HEADER   = bytes([0x80, 0x04])

HEADER_SIZE = 6
DATA_PACKET_SIZE = HEADER_SIZE + 2 * WORDS_PER_PACKET   # 1030 octets


def _u16(value: int) -> tuple[int, int]:
    """(octet de poids fort, octet de poids faible) d'un entier 16 bits."""
    value &= 0xFFFF
    return value >> 8, value & 0xFF


def build_config_msg(cfg: LoggerConfig) -> bytes:
    """Trame de configuration du logger (conf_msg de logger.m)."""
    cfg.validate()
    sig = list(cfg.signals) + [0] * (8 - cfg.n_channels)
    div_h, div_l = _u16(cfg.divider)
    del_h, del_l = _u16(cfg.delay)
    trip_h, trip_l = (cfg.trip_mask >> 16) & 0xFFFF, cfg.trip_mask & 0xFFFF
    trip_hh, trip_hl = _u16(trip_h)
    trip_lh, trip_ll = _u16(trip_l)
    thr_h, thr_l = _u16(cfg.threshold)      # complément à 2 (65536 + seuil si négatif)
    return bytes([
        0x80, 0x00,                                  # entête trame réseau
        0x55, 0xAA,
        0x00, 0x1A,
        0x00, cfg.n_channels,                        # nombre de canaux
        16 * sig[3] + sig[2], 16 * sig[1] + sig[0],  # sélection des signaux
        16 * sig[7] + sig[6], 16 * sig[5] + sig[4],
        0x00, 0x00,
        0x00, 0x00,
        div_h, div_l,                                # diviseur
        0x00, 0x00,
        del_h, del_l,                                # délai
        0x00, 0x00,
        0x00, int(cfg.trigger),                      # trigger
        trip_lh, trip_ll,                            # masque des disjonctions
        trip_hh, trip_hl,
        thr_h, thr_l,                                # seuil
    ])


def parse_config_msg(msg: bytes) -> dict:
    """Décodage d'une trame de configuration (simulateur et tests)."""
    if len(msg) != 32 or msg[:2] != CONFIG_HEADER:
        raise ValueError("Trame de configuration invalide")
    n = msg[7]
    nibbles = [msg[9] & 0xF, msg[9] >> 4, msg[8] & 0xF, msg[8] >> 4,
               msg[11] & 0xF, msg[11] >> 4, msg[10] & 0xF, msg[10] >> 4]
    threshold = (msg[30] << 8) | msg[31]
    if threshold >= 32768:
        threshold -= 65536
    return {
        "n_channels": n,
        "signals": nibbles[:n],
        "divider": (msg[16] << 8) | msg[17],
        "delay": (msg[20] << 8) | msg[21],
        "trigger": msg[25],
        "trip_mask": (msg[28] << 24) | (msg[29] << 16) | (msg[26] << 8) | msg[27],
        "threshold": threshold,
    }


def is_trig(msg: bytes) -> bool:
    return msg[:2] == TRIG_HEADER


def is_data(msg: bytes) -> bool:
    return msg[:2] == DATA_HEADER


@dataclass
class Frame:
    """Une trame décodée : `samples_per_channel` échantillons pour chaque voie."""
    index:      int                     # numéro de la trame (1, 2, ...)
    signals:    list[int]               # voies dans l'ordre de cfg.signals
    raw:        np.ndarray              # (n, n_channels) int16, colonnes = signals
    analog:     np.ndarray              # (n, n_analog) float, valeurs physiques
    logic:      np.ndarray | None       # (n, 16) uint8, bit k = voie logique k
    sample_rate: float
    timestamp:  float = 0.0             # time.time() à la réception
    meta:       dict = field(default_factory=dict)

    @property
    def n_samples(self) -> int:
        return self.raw.shape[0]

    @property
    def analog_signals(self) -> list[int]:
        return [s for s in self.signals if s != LOGIC_SIGNAL]

    def time(self) -> np.ndarray:
        return np.arange(self.n_samples) / self.sample_rate


def decode_payload(payload: bytes, cfg: LoggerConfig) -> np.ndarray:
    """
    Mots bruts d'une trame -> tableau (n, n_channels) int16, colonne j = cfg.signals[j].

    logger.m : reshape(data_16, sd/nch, nch) puis fliplr : les voies arrivent par blocs
    consécutifs, la dernière voie de la liste en premier.
    """
    words = np.frombuffer(payload, dtype=">i2").astype(np.int16)
    n = cfg.n_channels
    if words.size % n:
        raise ValueError(f"{words.size} mots ne se répartissent pas sur {n} voies")
    blocks = words.reshape(n, -1)           # bloc k = voie n-1-k
    return np.ascontiguousarray(blocks[::-1].T)


def encode_payload(raw: np.ndarray) -> bytes:
    """Opération inverse de decode_payload (simulateur)."""
    blocks = np.asarray(raw, dtype=np.int16).T[::-1]
    return blocks.astype(">i2").tobytes()


def logic_bits(word: np.ndarray) -> np.ndarray:
    """Mot des voies logiques -> (n, 16) bits, colonne k = bit k (voie logique k)."""
    w = np.asarray(word).astype(np.uint16)
    return ((w[:, None] >> np.arange(16, dtype=np.uint16)) & 1).astype(np.uint8)


def make_frame(payload: bytes, cfg: LoggerConfig, index: int, timestamp: float = 0.0) -> Frame:
    raw = decode_payload(payload, cfg)
    analog_cols = [j for j, s in enumerate(cfg.signals) if s != LOGIC_SIGNAL]
    gains = np.array([cfg.gain(cfg.signals[j]) for j in analog_cols], dtype=float)
    analog = raw[:, analog_cols].astype(float) / FULL_SCALE * gains
    logic = logic_bits(raw[:, -1]) if cfg.has_logic else None
    return Frame(index=index, signals=list(cfg.signals), raw=raw, analog=analog,
                 logic=logic, sample_rate=cfg.sample_rate, timestamp=timestamp)


def split_payload(payload: bytes) -> list[bytes]:
    """Découpe une trame en datagrammes DATA_MSG de 1030 octets (simulateur)."""
    size = 2 * WORDS_PER_PACKET
    return [DATA_HEADER + bytes([0x00, 0x00, 0x00, 0x00]) + payload[i:i + size]
            for i in range(0, len(payload), size)]
