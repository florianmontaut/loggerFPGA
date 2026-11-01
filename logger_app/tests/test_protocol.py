"""Trames UDP : comparaison octet par octet avec logger.m."""
import numpy as np
import pytest

from model import protocol
from model.config import ConfigError, LoggerConfig, TriggerType


def octave_conf_msg(nch, sig, div, dl, trig, trip, thres):
    """Transcription littérale du calcul de conf_msg dans logger.m."""
    sig = list(sig) + [0] * (8 - len(sig))
    div_h, div_l = div // 256, div % 256
    del_h, del_l = dl // 256, dl % 256
    trip_Hh = trip // 16777216
    trip_Hl = (trip - trip_Hh * 16777216) // 65536
    trip_Lh = (trip - trip_Hh * 16777216 - trip_Hl * 65536) // 256
    trip_Ll = trip - trip_Hh * 16777216 - trip_Hl * 65536 - trip_Lh * 256
    if thres < 0:
        thres = 65536 + thres
    thres_h, thres_l = thres // 256, thres % 256
    return bytes([0x80, 0x00, 0x55, 0xAA, 0x00, 0x1A, 0x00, nch,
                  16 * sig[3] + sig[2], 16 * sig[1] + sig[0],
                  16 * sig[7] + sig[6], 16 * sig[5] + sig[4],
                  0, 0, 0, 0, div_h, div_l, 0, 0, del_h, del_l, 0, 0, 0, trig,
                  trip_Lh, trip_Ll, trip_Hh, trip_Hl, thres_h, thres_l])


@pytest.mark.parametrize("sig,div,dl,trig,trip,thres", [
    ([5], 20, 5000, 0, 0x00010000, -553),
    ([3, 15], 2800, 0, 2, 0x01000000, 1200),
    ([0, 1, 2, 3], 1, 65535, 4, 0xFFFFFFFF, -32768),
    ([7, 6, 5, 4, 3, 2, 1, 15], 65535, 1, 1, 0x12345678, 32767),
    ([15], 500, 0, 0, 0, 0),
])
def test_config_msg_matches_octave(sig, div, dl, trig, trip, thres):
    cfg = LoggerConfig(signals=sig, divider=div, delay=dl, trigger=trig, trip_mask=trip,
                       threshold=thres)
    msg = protocol.build_config_msg(cfg)
    assert msg == octave_conf_msg(len(sig), sig, div, dl, trig, trip, thres)
    assert len(msg) == 32
    parsed = protocol.parse_config_msg(msg)
    assert parsed["signals"] == sig
    assert parsed["divider"] == div and parsed["delay"] == dl
    assert parsed["trigger"] == trig and parsed["trip_mask"] == trip
    assert parsed["threshold"] == thres


@pytest.mark.parametrize("sig", [[0, 1, 2], [15, 1], [1, 1], [16], []])
def test_invalid_signals(sig):
    with pytest.raises(ConfigError):
        LoggerConfig(signals=sig).validate()


def test_threshold_needs_analog_first_channel():
    with pytest.raises(ConfigError):
        LoggerConfig(signals=[15], trigger=TriggerType.ABOVE).validate()


def test_decode_matches_octave_reshape():
    """reshape(data_16, sd/nch, nch) (colonnes) puis fliplr."""
    cfg = LoggerConfig(signals=[2, 7, 9, 15])
    words = np.arange(16384, dtype=np.int16) - 8000
    payload = words.astype(">i2").tobytes()
    raw = protocol.decode_payload(payload, cfg)
    octave = np.fliplr(words.reshape(4, -1).T)        # reshape Octave = ordre colonne
    np.testing.assert_array_equal(raw, octave)
    assert protocol.encode_payload(raw) == payload


def test_make_frame_scaling_and_logic():
    cfg = LoggerConfig(signals=[4, 15], gains=[100.0] * 15)
    n = 8192
    raw = np.zeros((n, 2), dtype=np.int16)
    raw[:, 0] = 8192                                   # 0,5 pu
    raw[:, 1] = np.int16(0b1000_0000_0000_0101 - 65536)  # bits 0, 2 et 15
    frame = protocol.make_frame(protocol.encode_payload(raw), cfg, 1)
    np.testing.assert_allclose(frame.analog[:, 0], 50.0)
    assert frame.logic.shape == (n, 16)
    assert list(np.nonzero(frame.logic[0])[0]) == [0, 2, 15]
    assert frame.time()[1] == pytest.approx(20 / 25e6)


def test_split_payload_packets():
    payload = bytes(range(256)) * 128
    packets = protocol.split_payload(payload)
    assert len(packets) == 32 and all(len(p) == 1030 for p in packets)
    assert b"".join(p[6:] for p in packets) == payload


def test_set_threshold_signal_moves_channel_first():
    cfg = LoggerConfig(signals=[1, 4, 6, 15])
    cfg.set_threshold_signal(6)
    assert cfg.signals == [6, 1, 4, 15]
    with pytest.raises(ConfigError):
        cfg.set_threshold_signal(15)


def test_threshold_physical_roundtrip():
    cfg = LoggerConfig(signals=[0], gains=[100.0] * 15)
    cfg.threshold = cfg.threshold_from_physical(-3.375)
    assert cfg.threshold == -553
    assert cfg.threshold_physical() == pytest.approx(-553 * 100 / 16384)


def test_legacy_json(tmp_path):
    import json
    legacy = {"ip_fpga": "172.16.0.1", "target_port_fpga": 9, "remote_port_fpga": 2064,
              "trip": "01000000", "n_ana_channels": 2, "channels_config": [0, 1],
              "divider": 2800, "type_trigger": 0, "trigger_thres": 0,
              "ana_channel_names": [f"A{i}" for i in range(16)],
              "gains": [0.5] * 16}
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps(legacy))
    cfg = LoggerConfig.load(str(path))
    assert cfg.signals == [0, 1] and cfg.trip_mask == 0x01000000
    assert cfg.gains[0] == 0.5 * 16384 and len(cfg.analog_names) == 15
    cfg.save(str(tmp_path / "new.json"))
    assert LoggerConfig.load(str(tmp_path / "new.json")) == cfg
