"""Analyse spectrale : calibration des amplitudes, moyennage, pics, THD."""
import numpy as np
import pytest

from model import spectrum

FS = 25e6 / 20          # 1,25 MHz
N = 8192


def sine(f, a=1.0, phase=0.3, n=N):
    return a * np.sin(2 * np.pi * f * np.arange(n) / FS + phase)


@pytest.mark.parametrize("win", list(spectrum.WINDOWS))
def test_bin_centered_amplitude(win):
    f = 100 * FS / N                          # tombe sur la raie 100
    freq, amp = spectrum.amplitude_spectrum(sine(f, 3.0) + 2.0, FS, win, remove_dc=False)
    assert freq[100] == pytest.approx(f)
    assert amp[100] == pytest.approx(3.0, rel=1e-9)
    if win == "rectangulaire":
        assert amp[0] == pytest.approx(2.0, abs=1e-9)


def test_flattop_between_bins_and_interpolated_frequency():
    f = 100.37 * FS / N
    freq, amp = spectrum.amplitude_spectrum(sine(f, 1.5), FS, "flattop")
    peak = spectrum.find_peaks(freq, amp, 1, "flattop")[0]
    assert peak.amplitude == pytest.approx(1.5, rel=2e-3)
    freq, amp = spectrum.amplitude_spectrum(sine(f, 1.5), FS, "hann")
    assert spectrum.find_peaks(freq, amp, 1, "hann")[0].frequency == pytest.approx(f, rel=1e-3)


def test_remove_dc_and_multichannel():
    y = np.column_stack([sine(5000) + 10, sine(20000, 0.5)])
    freq, amp = spectrum.amplitude_spectrum(y, FS, "hann")
    assert amp.shape == (N // 2 + 1, 2)
    assert amp[0, 0] < 0.01                   # offset de 10 retiré (reste : fuite du sinus)
    assert freq[np.argmax(amp[:, 1])] == pytest.approx(20000, abs=FS / N)


def test_scales():
    amp = np.array([2.0, 1.0, 0.1])
    np.testing.assert_allclose(spectrum.scale_amplitude(amp, "efficace"),
                               [2.0, 1 / np.sqrt(2), 0.1 / np.sqrt(2)])
    np.testing.assert_allclose(spectrum.scale_amplitude(amp, "dB"), [6.0206, 0, -20], atol=1e-4)
    assert spectrum.scale_amplitude(np.zeros(2), "dB").min() == -200


def test_averaging_modes():
    avg = spectrum.SpectrumAverager("moyenne", count=2)
    avg.add(np.array([3.0, 0.0]))
    out = avg.add(np.array([4.0, 0.0]))
    np.testing.assert_allclose(out, [np.sqrt((9 + 16) / 2), 0])
    out = avg.add(np.array([0.0, 0.0]))       # la plus ancienne est oubliée
    np.testing.assert_allclose(out, [np.sqrt(16 / 2), 0])
    assert avg.n_averaged == 2
    out = avg.add(np.zeros(3))                 # autre taille : remise à zéro
    assert avg.n_averaged == 1 and out.shape == (3,)
    mx = spectrum.SpectrumAverager("max")
    mx.add(np.array([1.0, 5.0]))
    np.testing.assert_allclose(mx.add(np.array([2.0, 1.0])), [2.0, 5.0])


def test_peaks_sorted_and_separated():
    y = sine(10000, 1.0) + sine(30000, 0.25) + sine(50000, 0.5)
    freq, amp = spectrum.amplitude_spectrum(y, FS, "hann")
    peaks = spectrum.find_peaks(freq, amp, 3, "hann")
    assert [round(p.frequency, -2) for p in peaks] == [10000, 50000, 30000]
    assert all(abs(a.index - b.index) > 2 for a in peaks for b in peaks if a is not b)


def test_thd():
    f0 = 50 * FS / N * 4                      # fondamental sur une raie
    y = sine(f0, 1.0) + sine(2 * f0, 0.03) + sine(3 * f0, 0.04, 1.0)
    freq, amp = spectrum.amplitude_spectrum(y, FS, "hann")
    h = spectrum.harmonics(freq, amp, "hann", n_harmonics=5)
    assert h.fundamental.frequency == pytest.approx(f0, rel=1e-4)
    assert h.amplitudes[:2] == pytest.approx([0.03, 0.04], rel=1e-6)
    assert h.thd == pytest.approx(0.05, rel=1e-3)


def test_unknown_window():
    with pytest.raises(ValueError):
        spectrum.window("kaiser", 16)


def test_noise_peaks_ignored():
    rng = np.random.default_rng(0)
    y = sine(10000, 1.0) + sine(25000, 0.05) + 0.01 * rng.standard_normal(N)
    freq, amp = spectrum.amplitude_spectrum(y, FS, "hann")
    peaks = spectrum.find_peaks(freq, amp, 10, "hann")
    assert [round(p.frequency, -3) for p in peaks] == [10000, 25000]


def test_fast_length_and_awkward_sizes():
    assert spectrum.fast_length(8192) == 8192
    assert 1_990_001 <= spectrum.fast_length(1_990_001) <= 2_000_000
    for n in (7, 97, 1001, 12_289):
        m = spectrum.fast_length(n)
        assert m >= n
        k = m
        for p in (2, 3, 5):
            while k % p == 0:
                k //= p
        assert k == 1
    # longueur première : amplitude toujours calibrée (flattop), fréquence retrouvée
    n = 10_007
    f = 1234.5
    y = 2.0 * np.sin(2 * np.pi * f * np.arange(n) / FS)
    freq, amp = spectrum.amplitude_spectrum(y, FS, "flattop")
    peak = spectrum.find_peaks(freq, amp, 1, "flattop")[0]
    assert peak.amplitude == pytest.approx(2.0, rel=3e-3)
    assert peak.frequency == pytest.approx(f, rel=2e-3)


def test_large_window_single_precision_close_to_exact():
    n = 200_000
    exact = 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(n) / n)
    np.testing.assert_allclose(spectrum.window("hann", n), exact, atol=2e-6)
    assert spectrum.window("hann", n).sum() == pytest.approx(n / 2, rel=1e-6)
