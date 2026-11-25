"""Audio visualizer: a live spectrum drawn as bars or a wave."""
from __future__ import annotations


from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath
from PySide6.QtWidgets import QMenu, QWidget

try:
    import numpy as np
except ImportError:  # no numpy: the visualizer stays empty
    np = None

STYLES = {"bars": "Bars", "wave": "Wave", "mirror": "Mirrored bars"}
FPS = 40
FFT_SIZE = 2048
F_LO, F_HI = 40.0, 16000.0
RANGE_DB = 46.0  # dB below the loudest band that still shows
SILENCE_DB = -75.0


class Visualizer(QWidget):
    styleRequested = Signal(str)  # "bars" / "wave" / "mirror" / "off"

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.style_name = "bars"
        self.source = None  # callable(n) -> mono samples or None
        self.rate = 48000
        self.levels = None  # smoothed bar heights 0..1
        self.peaks = None
        self.peak_hold = None
        self._edges = None
        self._n_bars = 0
        self.playing = False
        self.timer = QTimer(self)
        self.timer.setInterval(1000 // FPS)
        self.timer.timeout.connect(self._tick)
        self.setMinimumHeight(48)
        self.setToolTip("Right-click for visualizer styles")

    def set_source(self, source, rate: int):
        self.source, self.rate = source, rate
        self._edges = None
        self._update_running()

    def set_style(self, name: str):
        self.style_name = name if name in STYLES else "bars"
        self._edges = None
        self.update()

    def set_playing(self, playing: bool):
        self.playing = playing
        if playing:
            self._update_running()
        # Keep the timer running until the bars have fallen, then it stops itself.

    def clear(self):
        if self.levels is not None:
            self.levels[:] = 0
            self.peaks[:] = 0
        self.update()

    def _update_running(self):
        want = (self.isVisible() and self.source is not None and np is not None and self.playing)
        if want and not self.timer.isActive():
            self.timer.start()
        elif not want and self.timer.isActive():
            self.timer.stop()

    def showEvent(self, e):
        super().showEvent(e)
        self._update_running()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._update_running()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._edges = None

    def _bar_count(self) -> int:
        w = max(60, self.width())
        if self.style_name == "wave":
            return max(24, min(96, w // 5))
        return max(12, min(72, w // 9))

    def _make_edges(self):
        n = self._bar_count()
        self._n_bars = n
        freqs = np.fft.rfftfreq(FFT_SIZE, 1.0 / self.rate)
        edges = F_LO * (F_HI / F_LO) ** (np.arange(n + 1) / n)
        idx = np.searchsorted(freqs, edges)
        idx = np.maximum.accumulate(np.maximum(idx, 1))
        for i in range(1, len(idx)):  # at least one FFT bin per bar
            if idx[i] <= idx[i - 1]:
                idx[i] = idx[i - 1] + 1
        self._edges = np.minimum(idx, len(freqs) - 1)
        centres = np.sqrt(edges[:-1] * edges[1:])
        self._tilt = 3.0 * np.log2(centres / 1000.0)  # +3 dB/octave so treble isn't lost
        self._window = np.hanning(FFT_SIZE).astype(np.float32)
        self._norm = 2.0 / self._window.sum()
        self.levels = np.zeros(n)
        self.ref_db = -20.0  # follows the loudest band so quiet and loud songs both fill the space
        self.peaks = np.zeros(n)
        self.peak_hold = np.zeros(n)

    def _tick(self):
        if self._edges is None or self._bar_count() != self._n_bars:
            self._make_edges()
        x = self.source(FFT_SIZE) if self.source else None
        if x is None or len(x) < FFT_SIZE:
            target = np.zeros(self._n_bars)
        else:
            mag = np.abs(np.fft.rfft(x * self._window)) * self._norm
            e = self._edges
            band = np.maximum.reduceat(mag, e[:-1])[: self._n_bars]
            db = 20 * np.log10(band + 1e-9) + self._tilt
            loudest = float(db.max())
            if loudest < SILENCE_DB:
                target = np.zeros(self._n_bars)
            else:
                # rise at once, fall about 6 dB/s
                self.ref_db = max(loudest, self.ref_db - 6.0 / FPS, SILENCE_DB + RANGE_DB / 2)
                target = np.clip((db - (self.ref_db - RANGE_DB)) / RANGE_DB, 0.0, 1.0) ** 1.4
        rising = target > self.levels
        self.levels = np.where(rising, self.levels + (target - self.levels) * 0.65, self.levels * 0.86)
        # peak caps hold briefly, then fall
        bump = self.levels >= self.peaks
        self.peaks = np.where(bump, self.levels, self.peaks)
        self.peak_hold = np.where(bump, 12, self.peak_hold - 1)
        self.peaks = np.where(self.peak_hold <= 0, np.maximum(self.levels, self.peaks - 0.025), self.peaks)
        quiet = not self.levels.any() or self.levels.max() < 0.002
        if quiet and x is None:
            self.levels[:] = 0
            self.peaks[:] = 0
        self.update()
        if quiet and not self.playing:
            self.timer.stop()

    def paintEvent(self, _):
        if self.levels is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        accent = self.theme.color("accent")
        if float(self.levels.max()) < 0.01 and float(self.peaks.max()) < 0.02:
            line = QColor(self.theme.color("faint"))
            line.setAlpha(90)
            y = h / 2 if self.style_name in ("wave", "mirror") else h - 1
            p.fillRect(QRectF(0, y - 0.5, w, 1), line)
            return
        top_c = QColor(accent).lighter(135)
        g = QLinearGradient(0, 0, 0, h)
        g.setColorAt(0, top_c)
        g.setColorAt(1, QColor(accent.red(), accent.green(), accent.blue(), 110))
        n = len(self.levels)
        if self.style_name == "wave":
            self._paint_wave(p, w, h, accent)
            return
        gap = 3 if w / n > 7 else 2
        bw = (w - gap * (n - 1)) / n
        mirror = self.style_name == "mirror"
        mid = h / 2
        cap = QColor(self.theme.color("text"))
        cap.setAlpha(150)
        for i in range(n):
            v = float(self.levels[i])
            x = i * (bw + gap)
            if mirror:
                bh = max(1.5, v * (h - 4) / 2)
                p.setPen(Qt.NoPen)
                p.setBrush(g)
                p.drawRoundedRect(QRectF(x, mid - bh, bw, bh * 2), bw / 3, bw / 3)
            else:
                bh = max(2.0, v * (h - 4))
                p.setPen(Qt.NoPen)
                p.setBrush(g)
                p.drawRoundedRect(QRectF(x, h - bh, bw, bh), min(bw / 3, 3), min(bw / 3, 3))
                pk = float(self.peaks[i])
                if pk > 0.02:
                    p.setBrush(cap)
                    p.drawRoundedRect(QRectF(x, h - 2 - pk * (h - 4) - 2, bw, 2), 1, 1)

    def _paint_wave(self, p, w, h, accent):
        n = len(self.levels)
        mid = h / 2
        pts_top = [QPointF(i / (n - 1) * w, mid - float(self.levels[i]) * (mid - 2)) for i in range(n)]

        def smooth(points):
            path = QPainterPath(points[0])
            for a, b in zip(points, points[1:]):
                cx = (a.x() + b.x()) / 2
                path.cubicTo(QPointF(cx, a.y()), QPointF(cx, b.y()), b)
            return path

        top = smooth(pts_top)
        bottom = smooth([QPointF(pt.x(), 2 * mid - pt.y()) for pt in reversed(pts_top)])
        shape = QPainterPath(top)
        shape.connectPath(bottom)
        shape.closeSubpath()
        g = QLinearGradient(0, 0, 0, h)
        c_edge = QColor(accent)
        c_edge.setAlpha(150)
        c_mid = QColor(accent).lighter(130)
        g.setColorAt(0, c_edge)
        g.setColorAt(0.5, c_mid)
        g.setColorAt(1, c_edge)
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawPath(shape)

    menu_blocked = None  # fn -> True to pass right-clicks to the parent

    def contextMenuEvent(self, e):
        if self.menu_blocked is not None and self.menu_blocked():
            e.ignore()
            return
        m = QMenu(self)
        for key, name in STYLES.items():
            a = m.addAction(name, lambda k=key: self.styleRequested.emit(k))
            a.setCheckable(True)
            a.setChecked(key == self.style_name)
        m.addSeparator()
        m.addAction("Hide visualizer", lambda: self.styleRequested.emit("off"))
        m.addAction("🔓  Unlock to edit", lambda: self.styleRequested.emit("rearrange"))
        m.exec(e.globalPos())
