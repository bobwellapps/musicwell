"""10 or 15 band graphic EQ: a linear-phase FIR filter applied with FFT overlap-add. Filter changes are crossfaded."""
from __future__ import annotations

import numpy as np

BANDS = [31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]  # octaves
BAND_LABELS = ["31", "62", "125", "250", "500", "1k", "2k", "4k", "8k", "16k"]
BANDS_15 = [25, 40, 63, 100, 160, 250, 400, 630, 1000, 1600, 2500, 4000, 6300, 10000, 16000]  # 2/3 octave (ISO)
BAND_LABELS_15 = ["25", "40", "63", "100", "160", "250", "400", "630", "1k", "1.6k", "2.5k", "4k", "6.3k",
                  "10k", "16k"]
BAND_COUNTS = (10, 15)
MAX_DB = 12.0


def bands_for(n: int) -> list[int]:
    return BANDS_15 if n == 15 else BANDS


def labels_for(n: int) -> list[str]:
    return BAND_LABELS_15 if n == 15 else BAND_LABELS


def convert(gains, n: int) -> list[float]:
    """Map a curve to n bands (10 <-> 15)."""
    gains = [float(g) for g in gains]
    if len(gains) == n:
        return gains
    if len(gains) not in BAND_COUNTS:
        return [0.0] * n
    vals = target_db(np.asarray(bands_for(n), float), gains, 0.0)
    return [round(float(max(-MAX_DB, min(MAX_DB, v))), 1) for v in vals]

PRESETS: dict[str, list[float]] = {
    "Flat":         [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    "Bass boost":   [6, 5, 4, 2, 0.5, 0, 0, 0, 0, 0],
    "Bass reducer": [-6, -5, -4, -2, -0.5, 0, 0, 0, 0, 0],
    "Treble boost": [0, 0, 0, 0, 0, 0.5, 2, 4, 5, 6],
    "Rock":         [4.5, 3.5, 2, -0.5, -1.5, -0.5, 1.5, 3, 3.5, 4],
    "Pop":          [-1, 0.5, 2.5, 3.5, 3, 1, -0.5, -0.5, -1, -1],
    "Jazz":         [3, 2, 1, 1.5, -1, -1, 0, 1, 2, 3],
    "Classical":    [3.5, 3, 2.5, 1.5, -0.5, -0.5, 0, 1.5, 2.5, 3],
    "Electronic":   [4.5, 4, 1, 0, -2, 1.5, 0.5, 1, 4, 4.5],
    "Hip-hop":      [5, 4, 1.5, 3, -1, -1, 1, -0.5, 1.5, 2.5],
    "Acoustic":     [4, 3.5, 2.5, 1, 1.5, 1.5, 2.5, 3, 2.5, 1.5],
    "Vocal":        [-2, -2.5, -1, 1.5, 3.5, 3.5, 3, 1.5, 0, -1.5],
    "Loudness":     [5, 3.5, 0, 0, -1.5, 0, -0.5, -4, 4, 1],
    "Late night":   [3, 2.5, 1.5, 0.5, 0, 0, 0.5, 1, 0, -1],
    "Small speakers": [5, 4, 3, 1.5, 0, -0.5, -1, -0.5, 1, 1.5],
    "Headphones":   [3, 2, 0.5, -1, -0.5, 0.5, 2, 3.5, 4.5, 4],
}


def target_db(freqs: np.ndarray, gains, preamp: float = 0.0) -> np.ndarray:
    """Target response in dB at each frequency."""
    logf = np.log10(np.maximum(np.asarray(freqs, float), 1.0))
    g = np.asarray(gains, float)
    bands = bands_for(len(g))
    logb = np.log10(bands)
    # cosine-eased position between neighbouring bands
    k = np.clip(np.searchsorted(logb, logf) - 1, 0, len(bands) - 2)
    t = np.clip((logf - logb[k]) / (logb[k + 1] - logb[k]), 0.0, 1.0)
    t = (1 - np.cos(np.pi * t)) / 2
    return g[k] + (g[k + 1] - g[k]) * t + preamp


class Equalizer:
    def __init__(self, rate: int, channels: int = 2, block: int = 4096, taps: int = 8192):
        self.rate = rate
        self.channels = channels
        self.block = block
        self.taps = taps
        self.nfft = 1 << int(np.ceil(np.log2(block + taps - 1)))
        self.gains = [0.0] * len(BANDS)
        self.preamp = 0.0
        self._H = self._design(self.gains, 0.0)
        self._H_next = None
        self._fade = np.linspace(0.0, 1.0, block, dtype=np.float32)[:, None]
        self.reset()

    def set(self, gains, preamp: float):
        gains = [float(max(-MAX_DB, min(MAX_DB, g))) for g in gains]
        if gains == self.gains and preamp == self.preamp:
            return
        self.gains, self.preamp = gains, float(preamp)
        self._H_next = self._design(self.gains, self.preamp)

    def _design(self, gains, preamp) -> np.ndarray:
        n = self.taps
        freqs = np.fft.rfftfreq(n, 1.0 / self.rate)
        mag = 10.0 ** (target_db(freqs, gains, preamp) / 20.0)
        h = np.fft.irfft(mag, n)  # zero-phase impulse centred on 0
        h = np.roll(h, n // 2) * np.blackman(n)  # causal (linear phase) and windowed
        return np.fft.rfft(h, self.nfft).astype(np.complex64)

    def response_db(self, freqs) -> np.ndarray:
        """Actual response of the current filter, for drawing."""
        H = self._H_next if self._H_next is not None else self._H
        bins = np.fft.rfftfreq(self.nfft, 1.0 / self.rate)
        mag = np.abs(H)
        return 20 * np.log10(np.maximum(np.interp(freqs, bins, mag), 1e-6))

    def reset(self):
        self._in = np.zeros((0, self.channels), np.float32)
        self._tail = np.zeros((self.taps - 1, self.channels), np.float32)

    @property
    def latency_frames(self) -> int:
        return self.block + self.taps // 2

    def process(self, x: np.ndarray) -> np.ndarray:
        """Feed any number of frames; returns the whole blocks that are ready."""
        self._in = np.concatenate((self._in, x.astype(np.float32, copy=False)))
        B, out = self.block, []
        while len(self._in) >= B:
            blk, self._in = self._in[:B], self._in[B:]
            X = np.fft.rfft(blk, self.nfft, axis=0)
            y = np.fft.irfft(X * self._H[:, None], self.nfft, axis=0)
            if self._H_next is not None:
                y_new = np.fft.irfft(X * self._H_next[:, None], self.nfft, axis=0)
                y[:B] = y[:B] * (1 - self._fade) + y_new[:B] * self._fade
                y[B:] = y_new[B:]
                self._H, self._H_next = self._H_next, None
            y = y.astype(np.float32)
            L = self.taps - 1
            y[:L] += self._tail
            self._tail = y[B:B + L].copy()
            out.append(y[:B])
        if not out:
            return np.zeros((0, self.channels), np.float32)
        return np.concatenate(out)


def soft_clip(x: np.ndarray, knee: float = 0.92) -> np.ndarray:
    """Soft-clip peaks above the knee."""
    a = np.abs(x)
    over = a > knee
    if not over.any():
        return x
    room = 1.0 - knee
    y = x.copy()
    y[over] = np.sign(x[over]) * (knee + room * np.tanh((a[over] - knee) / room))
    return y
