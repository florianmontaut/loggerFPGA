"""Mémoire tampon des dernières trames."""
import numpy as np

from model.config import LoggerConfig
from model.frame_buffer import FrameBuffer, frame_bytes
from model.protocol import encode_payload, make_frame


def frames(cfg, indexes):
    raw = np.zeros((16384 // cfg.n_channels, cfg.n_channels), dtype=np.int16)
    return [make_frame(encode_payload(raw), cfg, i) for i in indexes]


def test_ring_keeps_latest():
    cfg = LoggerConfig(signals=[0, 1])
    buf = FrameBuffer(capacity=3)
    dropped = []
    for f in frames(cfg, range(1, 6)):
        dropped += buf.add(f, cfg)
    assert [f.index for f in buf] == [3, 4, 5]
    assert [f.index for f in dropped] == [1, 2]
    assert buf.latest.index == 5 and buf.position(buf[1]) == 1
    assert [f.index for f in buf.set_capacity(1)] == [3, 4]
    assert len(buf) == 1


def test_unsaved_and_layout_change():
    cfg = LoggerConfig(signals=[0, 1])
    buf = FrameBuffer()
    a, b = frames(cfg, [1, 2])
    buf.add(a, cfg)
    buf.add(b, cfg)
    buf.mark_saved([a], "x.csv")
    assert buf.unsaved() == [b]
    other = LoggerConfig(signals=[0, 15])
    assert buf.compatible(LoggerConfig(signals=[0, 1], gains=[1.0] * 15))
    assert not buf.compatible(other) and not buf.compatible(LoggerConfig(signals=[0, 1], divider=40))
    (c,) = frames(other, [3])
    assert buf.add(c, other) == [a, b]               # tampon vidé : autre disposition
    assert list(buf) == [c] and buf.cfg.signals == [0, 15]


def test_memory_estimate():
    cfg = LoggerConfig(signals=[3, 15])
    buf = FrameBuffer()
    for f in frames(cfg, [1, 2]):
        buf.add(f, cfg)
    assert buf.memory_bytes() == 2 * frame_bytes(cfg)
