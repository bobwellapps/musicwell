"""The cover drawn as a spinning vinyl record or picture disc."""
from __future__ import annotations

from time import monotonic

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QImage, QPainter, QPainterPath, QPen, QPixmap,
                           QRadialGradient)

STYLES = [("square", "Square (the cover)"), ("record", "Spinning record (the cover as its label)"),
          ("picture", "Spinning picture disc (the whole cover)")]
STYLE_KEYS = {k for k, _ in STYLES}
SPEEDS = [(50 / 3, "16⅔ rpm (slow)"), (100 / 3, "33⅓ rpm (LP)"), (45.0, "45 rpm (single)"),
          (78.0, "78 rpm (shellac)")]
SLOW_DOWN = 1.2  # seconds to stop when paused
_rpm = 100 / 3  # rpm
on_speed_changed = []  # callbacks(rpm)


def set_rpm(value: float, tell: bool = True):
    global _rpm
    value = float(value)
    best = min(SPEEDS, key=lambda s: abs(s[0] - value))[0]
    _rpm = best
    if tell:
        for fn in on_speed_changed:
            fn(best)


def speed_menu(menu):
    for value, label in SPEEDS:
        a = menu.addAction(label, lambda v=value: set_rpm(v))
        a.setCheckable(True)
        a.setChecked(abs(value - _rpm) < 0.01)


def _fill_rect(iw: int, ih: int) -> QRectF:
    s = min(iw, ih)
    return QRectF((iw - s) / 2, (ih - s) / 2, s, s)


def render_disc(img: QImage | None, side: int, style: str, dpr: float = 1.0) -> QPixmap:
    """The disc at `side` px, not rotated, on a transparent background."""
    px = max(8, int(side * dpr))
    pm = QPixmap(px, px)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    c = QPointF(px / 2, px / 2)
    R = px / 2 - 0.5
    disc = QPainterPath()
    disc.addEllipse(c, R, R)

    if style == "picture" and img is not None and not img.isNull():
        p.save()
        p.setClipPath(disc)
        p.drawImage(QRectF(0, 0, px, px), img, _fill_rect(img.width(), img.height()))
        p.restore()
        groove_alpha = (10, 18)
        label_r = R * 0.12
    else:
        g = QRadialGradient(c, R)
        g.setColorAt(0.0, QColor(30, 30, 32))
        g.setColorAt(0.7, QColor(18, 18, 20))
        g.setColorAt(1.0, QColor(10, 10, 11))
        p.fillPath(disc, g)
        groove_alpha = (14, 30)
        label_r = R * 0.36

    p.setBrush(Qt.NoBrush)
    step = max(1.2, 1.6 * dpr)
    r = label_r + R * 0.05
    i = 0
    gaps = [label_r + (R * 0.94 - label_r) * f for f in (0.18, 0.37, 0.55, 0.71, 0.86)]
    while r < R * 0.955:
        a = groove_alpha[i % 2]
        if any(abs(r - gp) < step * 1.2 for gp in gaps):
            p.setPen(QPen(QColor(0, 0, 0, 60), step * 0.8))
        else:
            p.setPen(QPen(QColor(255, 255, 255, a), 0.6 * dpr))
        p.drawEllipse(c, r, r)
        r += step
        i += 1
    p.setPen(QPen(QColor(255, 255, 255, 36), 1.2 * dpr))
    p.drawEllipse(c, R - 0.8 * dpr, R - 0.8 * dpr)
    p.setPen(QPen(QColor(0, 0, 0, 160), 1.0 * dpr))
    p.drawEllipse(c, R, R)

    lab = QPainterPath()
    lab.addEllipse(c, label_r, label_r)
    if style == "picture":
        p.fillPath(lab, QColor(235, 235, 235, 60))
    elif img is not None and not img.isNull():
        p.save()
        p.setClipPath(lab)
        p.drawImage(QRectF(c.x() - label_r, c.y() - label_r, 2 * label_r, 2 * label_r), img,
                    _fill_rect(img.width(), img.height()))
        p.restore()
    else:
        p.fillPath(lab, QColor(120, 120, 128))
    p.setPen(QPen(QColor(0, 0, 0, 120), 1.2 * dpr))
    p.drawEllipse(c, label_r, label_r)

    hole = max(2.0 * dpr, R * 0.035)
    p.setPen(QPen(QColor(255, 255, 255, 60), 0.8 * dpr))
    p.setBrush(QColor(8, 8, 9))
    p.drawEllipse(c, hole, hole)
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def _sheen(p: QPainter, c: QPointF, R: float):
    """Two still highlights on the grooves."""
    g = QConicalGradient(c, 0)
    clear = QColor(255, 255, 255, 0)
    soft = QColor(255, 255, 255, 34)
    for at, col in ((0.00, clear), (0.10, clear), (0.14, soft), (0.18, clear), (0.60, clear),
                    (0.64, soft), (0.68, clear), (1.00, clear)):
        g.setColorAt(at, col)
    ring = QPainterPath()
    ring.addEllipse(c, R, R)
    p.fillPath(ring, QBrush(g))


class Spinner(QObject):
    """Disc rotation: 33 1/3 rpm while playing, slowing down when paused."""
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.angle = 0.0
        self.speed = 0.0  # 0..1 of full speed
        self.playing = False
        self.active = False
        self._last = None
        self.timer = QTimer(self)
        self.timer.setInterval(16)  # ~60 fps
        self.timer.timeout.connect(self._tick)

    def set_playing(self, playing: bool):
        self.playing = bool(playing)
        self._run()

    def set_active(self, active: bool):
        self.active = bool(active)
        self._run()

    def _run(self):
        want = self.active and (self.playing or self.speed > 0)
        if want and not self.timer.isActive():
            self._last = monotonic()
            self.timer.start()
        elif not want and self.timer.isActive():
            self.timer.stop()

    def _tick(self):
        now = monotonic()
        dt = min(0.2, now - (self._last or now))
        self._last = now
        if self.playing:
            self.speed = min(1.0, self.speed + dt / 0.6)
        else:
            self.speed = max(0.0, self.speed - dt / SLOW_DOWN)
        self.angle = (self.angle + _rpm * 6 * self.speed * dt) % 360  # rpm * 360 / 60
        self.changed.emit()
        if not self.playing and self.speed <= 0:
            self.timer.stop()


class Disc:
    """Renders a disc once per size, then rotates it."""

    def __init__(self):
        self.img = None
        self.style = "record"
        self._cache = None  # (key, pixmap)

    def set_image(self, img):
        if img is not self.img:
            self.img = img
            self._cache = None

    def set_style(self, style: str):
        if style != self.style:
            self.style = style
            self._cache = None

    def pixmap(self, side: int, dpr: float) -> QPixmap:
        key = (int(side), round(dpr, 2), self.style, id(self.img))
        if self._cache is None or self._cache[0] != key:
            self._cache = (key, render_disc(self.img, int(side), self.style, dpr))
        return self._cache[1]

    def paint(self, p: QPainter, rect: QRectF, angle: float, dpr: float, shadow: bool = True):
        side = min(rect.width(), rect.height())
        c = rect.center()
        R = side / 2
        if shadow:
            for i in range(6, 0, -1):
                sh = QPainterPath()
                sh.addEllipse(QPointF(c.x(), c.y() + i * 0.6), R + i * 0.5, R + i * 0.5)
                p.fillPath(sh, QColor(0, 0, 0, 9))
        pm = self.pixmap(int(side), dpr)
        p.save()
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.translate(c)
        p.rotate(angle)
        p.drawPixmap(QRectF(-R, -R, side, side), pm, QRectF(0, 0, pm.width(), pm.height()))
        p.restore()
        _sheen(p, c, R - 1)
