"""Seek bar waveforms: decode each song once at low rate and cache its shape."""
from __future__ import annotations

import hashlib
import os

from PySide6.QtCore import QObject, QTimer, QUrl, Signal

from musicwell.paths import cache_dir

try:
    import numpy as np
except ImportError:
    np = None

POINTS = 600
RATE = 8000  # samples per second kept


def _cache_file(path: str):
    try:
        st = os.stat(path)
        sig = f"{path}|{st.st_size}|{int(st.st_mtime)}"
    except OSError:
        sig = path
    d = cache_dir() / "waveforms"
    d.mkdir(parents=True, exist_ok=True)
    return d / (hashlib.sha1(sig.encode()).hexdigest()[:24] + ".wave")


def shape(rms, peaks):
    """Loudness per point -> 0..1 heights, keeping quiet parts visible."""
    a = np.maximum(rms * 1.6, peaks * 0.6)
    top = np.percentile(a, 98) if len(a) else 0
    if top <= 1e-6:
        return np.zeros(len(a), np.float32)
    a = np.clip(a / top, 0, 1) ** 0.8
    return (0.06 + 0.94 * a).astype(np.float32)


class WaveformStore(QObject):
    ready = Signal(str, object)  # path, array of POINTS values 0..1 (or None)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mem: dict[str, object] = {}
        self._decoder = None
        self._path = None
        self._want = None  # (path, length) waiting
        self._sum = self._peak = self._count = None
        self._length_us = 1

    @staticmethod
    def available() -> bool:
        if np is None:
            return False
        try:
            from PySide6.QtMultimedia import QAudioDecoder  # noqa: F401
            return True
        except ImportError:
            return False

    def request(self, path: str, length_s: float):
        """Request a waveform; the answer comes through `ready`."""
        if path in self._mem:
            self.ready.emit(path, self._mem[path])
            return
        f = _cache_file(path)
        if f.exists() and np is not None:
            data = np.frombuffer(f.read_bytes(), dtype=np.uint8).astype(np.float32) / 255.0
            if len(data) == POINTS:
                self._remember(path, data)
                self.ready.emit(path, data)
                return
        if not self.available():
            self.ready.emit(path, None)
            return
        if self._path == path:
            return
        self._want = (path, length_s)
        if self._decoder is None:
            QTimer.singleShot(0, self._next)

    def _remember(self, path, data):
        self._mem[path] = data
        if len(self._mem) > 300:
            self._mem.pop(next(iter(self._mem)))

    def _next(self):
        if self._decoder is not None or self._want is None:
            return
        from PySide6.QtMultimedia import QAudioDecoder
        path, length = self._want
        self._want = None
        self._path = path
        self._length_us = max(1, int((length or 0) * 1_000_000))
        self._sum = np.zeros(POINTS, np.float64)
        self._peak = np.zeros(POINTS, np.float32)
        self._count = np.zeros(POINTS, np.int64)
        self._max_t = 0
        d = QAudioDecoder(self)
        # Keep the source format: asking Qt to resample can stall on some MP3s.
        d.bufferReady.connect(self._on_buffer)
        d.finished.connect(self._on_finished)
        d.error.connect(lambda *_: self._on_finished(failed=True))
        d.setSource(QUrl.fromLocalFile(path))
        self._decoder = d
        d.start()

    def _on_buffer(self):
        d = self._decoder
        if d is None:
            return
        buf = d.read()
        if not buf.isValid():
            return
        from PySide6.QtMultimedia import QAudioFormat
        fmt = buf.format()
        kind = fmt.sampleFormat()
        raw = buf.constData()
        if kind == QAudioFormat.Float:
            a = np.frombuffer(raw, dtype=np.float32)
        elif kind == QAudioFormat.Int16:
            a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        elif kind == QAudioFormat.Int32:
            a = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
        elif kind == QAudioFormat.UInt8:
            a = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
        else:
            return
        if not len(a):
            return
        rate = fmt.sampleRate() or RATE
        ch = max(1, fmt.channelCount())
        if ch > 1:
            a = a[: len(a) // ch * ch].reshape(-1, ch).mean(axis=1)
        step = max(1, rate // RATE)
        if step > 1:
            a = np.abs(a[: len(a) // step * step]).reshape(-1, step).max(axis=1)
            rate = rate / step
        start = buf.startTime()  # µs
        t = start + np.arange(len(a)) * (1_000_000 / rate)
        self._max_t = max(self._max_t, int(t[-1]))
        idx = np.clip((t * POINTS / self._length_us).astype(np.int64), 0, POINTS - 1)
        np.add.at(self._sum, idx, a.astype(np.float64) ** 2)
        np.add.at(self._count, idx, 1)
        np.maximum.at(self._peak, idx, np.abs(a))

    def _on_finished(self, failed: bool = False):
        d, path = self._decoder, self._path
        if d is None or path is None:
            return
        self._decoder, self._path = None, None
        if d is not None:
            d.stop()
            d.deleteLater()
        data = None
        if not failed and self._count is not None and self._count.sum() > 0:
            # If the reported length was wrong, fit to what was decoded.
            if self._max_t and self._max_t < self._length_us * 0.9:
                used = max(1, int(np.ceil(self._max_t * POINTS / self._length_us)))
                src = np.linspace(0, used - 1, POINTS)
                self._sum = np.interp(src, np.arange(used), self._sum[:used])
                self._count = np.maximum(1, np.interp(src, np.arange(used), self._count[:used]))
                self._peak = np.interp(src, np.arange(used), self._peak[:used]).astype(np.float32)
            rms = np.sqrt(self._sum / np.maximum(1, self._count)).astype(np.float32)
            data = shape(rms, self._peak)
            try:
                _cache_file(path).write_bytes((data * 255).round().astype(np.uint8).tobytes())
            except OSError:
                pass
        self._remember(path, data)  # remember failures too so they aren't retried
        self.ready.emit(path, data)
        if self._want is not None:
            QTimer.singleShot(0, self._next)

    @staticmethod
    def cache_files() -> list:
        d = cache_dir() / "waveforms"
        return [p for p in d.iterdir() if p.is_file()] if d.exists() else []

    def clear_cache(self) -> int:
        n = 0
        for p in self.cache_files():
            p.unlink(missing_ok=True)
            n += 1
        self._mem.clear()
        return n

    def shutdown(self):
        self._want = None
        d, self._decoder, self._path = self._decoder, None, None
        if d is not None:
            try:
                d.bufferReady.disconnect()
                d.finished.disconnect()
                d.error.disconnect()
            except (RuntimeError, TypeError):
                pass
            d.stop()
            from shiboken6 import Shiboken
            if Shiboken.isValid(d):
                Shiboken.delete(d)
