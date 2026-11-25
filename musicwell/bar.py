"""The play bar, built from items you can move while the window is unlocked."""
from __future__ import annotations

import copy
import json

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import (QAbstractSlider, QApplication, QHBoxLayout, QLabel, QLayout, QMenu, QPushButton,
                               QSizePolicy, QToolButton, QToolTip, QVBoxLayout, QWidget)

from musicwell import theme as th
from musicwell.artwork import placeholder
from musicwell.models import fmt_time
from musicwell.widgets import IconButton, StarRow, _cover_rect, copy_action, scale_text, text_size_menu

MIME = "application/x-musicwell-bar-item"
ZONES = ["top", "left", "center", "below", "right"]
ZONE_NAMES = {"top": "Top strip", "left": "Left", "center": "Centre", "below": "Under the centre",
              "right": "Right"}

# key: (name, description)
ITEMS = {
    "cover": ("Album cover", "click it to show the song in the library — drag its corner to resize it"),
    "info": ("Title and artist", ""),
    "shuffle": ("Shuffle", ""),
    "prev": ("Previous", ""),
    "back10": ("Back 10 s", ""),
    "play": ("Play / pause", ""),
    "stop": ("Stop", ""),
    "fwd10": ("Forward 10 s", ""),
    "next": ("Next", ""),
    "repeat": ("Repeat", ""),
    "seek": ("Seek bar", "with the times either side"),
    "time": ("Time", "1:23 / 4:56 on its own"),
    "stopafter": ("Stop after this song", ""),
    "rating": ("Rating", "stars for the playing song"),
    "lyrics": ("Lyrics", "opens the Lyrics page"),
    "like": ("♥ Like", "your songs: into your Favourites (5 stars); radio and online songs: Radio → ♥ Liked"),
    "copy": ("Play your copy", "shows while the radio plays a song you have"),
    "locate": ("Show playing song", "jumps to it in the library"),
    "refresh": ("Reload images", "looks for the album cover and artist photo again"),
    "cast": ("Cast (Chromecast / Sonos)", ""),
    "eq": ("Equalizer", ""),
    "queue": ("Queue", ""),
    "panel": ("Panel toggle", "show / hide the now playing panel"),
    "mute": ("Mute", "volume icon"),
    "volume": ("Volume slider", ""),
    "viz": ("Visualizer", "bars, mirrored bars or wave — drag its corner to resize it"),
    "artist_info": ("About the artist", "what Wikipedia says about the artist playing — drag its corner to resize it"),
}
# Panel items the bar can hold ("panel:<key>" in the bar), with their size in the bar.
PANEL_ITEMS = {
    "artist_image": ("Artist photo", (160, 56)),
    "title": ("Song title", (220, 28)),
    "artist": ("Artist", (200, 24)),
    "album": ("Album and year", (220, 22)),
    "details": ("Audio details", (240, 20)),
    "stats": ("Play count", (200, 20)),
    "fields": ("Extra fields", (240, 40)),
    "cast": ("Playing on (casting)", (260, 32)),
    "lyrics": ("Lyrics", (320, 60)),
    "upnext": ("Up next", (260, 64)),
    "artists": ("Artist list", (260, 110)),
    "albums": ("All albums", (280, 110)),
    "songs": ("Song list", (300, 110)),
}
ITEMS.update({"panel:" + k: (name, "drag its corner to resize it") for k, (name, _) in PANEL_ITEMS.items()})
TOP_ITEMS = {"status": "Song count and messages", "search": "Search box", "albums": "All albums button",
             "layouts": "Layouts button", "panels": "Panels button", "settings": "Settings button"}
ITEMS.update({"top:" + k: (name, "") for k, name in TOP_ITEMS.items()})
TEXT_ITEMS = {"info", "time", "artist_info", "top:status", "top:search"} | {
    "panel:" + k for k in ("artist_image", "title", "artist", "album", "details", "stats", "fields", "cast", "lyrics", "upnext",
                           "artists", "albums", "songs")}
# Play bar items a panel can hold a copy of ("bar:<key>" in the panel), plus all the playback buttons as one.
CONTROLS = ["info", "buttons", "shuffle", "prev", "back10", "play", "stop", "fwd10", "next", "repeat", "seek", "time",
            "stopafter", "lyrics", "locate", "refresh", "copy", "cast", "eq", "queue", "panel", "mute", "volume"]
PLAY_BUTTONS = ["shuffle", "prev", "play", "next", "repeat"]


def control_name(key: str) -> str:
    if key == "buttons":
        return "Playback buttons"
    return {"lyrics": "Lyrics button", "cast": "Cast button", "panel": "Panel toggle"}.get(key, item_name(key))


def panel_key(bar_key: str):
    """The key a play bar item has in a panel, or None if it can't go there."""
    if bar_key in SHARED:
        return SHARED[bar_key]
    if bar_key.startswith("panel:"):
        return bar_key[6:]
    if bar_key.startswith("top:"):
        return bar_key
    if bar_key.split(":")[0] in ("gap", "stretch"):
        return "spacer:new"  # a gap becomes a panel spacer
    return "bar:" + bar_key if bar_key in CONTROLS else None


def bar_key(key: str):
    """The play bar key for a panel item, or None if the bar can't hold it."""
    if key in FROM_PANEL:
        return FROM_PANEL[key]
    if key in PANEL_ITEMS:
        return "panel:" + key
    if key.startswith("top:") and key in ITEMS:
        return key
    if key.startswith("spacer:"):
        return "new:gap"  # a panel spacer becomes a gap
    k = key[4:] if key.startswith("bar:") else None
    return k if k in ITEMS else None


# Items that can be in the play bar and the panels (bar key: panel key). Dragging moves them.
SHARED = {"viz": "visualizer", "cover": "artwork", "rating": "rating", "like": "like", "artist_info": "artist_info"}
FROM_PANEL = {v: k for k, v in SHARED.items()}
SPACER_NAMES = {"stretch": "Flexible space", "gap": "Gap"}
SIZEABLE = {"viz", "artist_info", "cover"}  # items with a corner grip for width and height (unlocked)

DEFAULT_ZONES = {
    "top": [],
    "left": ["cover", "info", "like", "copy"],
    "center": ["shuffle", "prev", "play", "next", "repeat"],
    "below": ["seek"],
    "right": ["stopafter", "cast", "eq", "queue", "mute", "volume"],
}
DEFAULT_OPTIONS = {
    "icon_size": "medium",  # small / medium / large
    "icon_style": "filled",  # filled / outline / thin / bold
    "play_style": "circle",  # circle / ring / plain
    "seek_style": "slider",  # see SEEK_STYLES
    "seek_handle": "always",  # always / hover / never
    "seek_times": "both",  # both / remaining / elapsed / none
    "position": "bottom",  # bottom / top
    "cover_style": "square",  # square / record / picture
}
OPTION_CHOICES = {
    "icon_size": ("Icon size", [("small", "Small"), ("medium", "Medium"), ("large", "Large")]),
    "icon_style": ("Icon style", [("filled", "Filled"), ("outline", "Outline"), ("thin", "Thin"),
                                  ("bold", "Bold")]),
    "play_style": ("Play button", [("circle", "Filled circle"), ("ring", "Outlined circle"),
                                   ("plain", "Plain icon")]),
    "seek_style": ("Seek bar", [("slider", "Slider"), ("line", "Thin line"), ("thick", "Thick bar"),
                                ("dots", "Dotted"), ("segments", "Segments"),
                                ("wave", "Waveform"), ("bars", "Waveform bars"),
                                ("cloud", "Waveform bars, growing up")]),
    "seek_handle": ("Seek bar handle", [("always", "Always shown"), ("hover", "When the mouse is over it"),
                                        ("never", "Never")]),
    "seek_times": ("Times beside the seek bar", [("both", "Elapsed and total"),
                                                 ("remaining", "Elapsed and time left"),
                                                 ("elapsed", "Elapsed only"), ("none", "None")]),
    "position": ("Position", [("bottom", "At the bottom of the window"), ("top", "At the top of the window")]),
    "cover_style": ("Album cover", [("square", "Square (the cover)"), ("record", "Spinning record"),
                                    ("picture", "Spinning picture disc")]),
}
# small icon, transport icon, play button box, cover size
SIZES = {"small": (15, 18, 34, 40), "medium": (18, 22, 44, 52), "large": (22, 27, 54, 62)}
EXPANDING = {"seek", "stretch"}
WAVE_STYLES = {"wave", "bars", "cloud"}  # drawn from the song's real waveform
# seek bar height per style
SEEK_HEIGHT = {"slider": 18, "line": 14, "thick": 20, "dots": 16, "segments": 16,
               "wave": 34, "bars": 34, "cloud": 38}


def item_name(key: str) -> str:
    base = key.split(":")[0]
    if base in SPACER_NAMES:
        return SPACER_NAMES[base]
    return ITEMS.get(key, (key, ""))[0]


class SeekBar(QWidget):
    """A painted slider with the QSlider calls the window uses."""
    sliderMoved = Signal(int)
    sliderReleased = Signal()
    valueChanged = Signal(int)
    changed = Signal()  # range, look or waveform (copies follow)

    def __init__(self, theme, parent=None, time_tips: bool = True):
        super().__init__(parent)
        self.theme = theme
        self._min, self._max, self._value = 0, 0, 0
        self._down = False
        self._hover = False
        self.style_name = "slider"
        self.handle = "always"
        self.time_tips = time_tips
        self.wave = None  # array of 0..1 loudness values, or None
        self.wave_loading = False
        self._hover_x = None
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(18)

    # QSlider-like API
    def setRange(self, lo: int, hi: int):
        self._min, self._max = int(lo), max(int(lo), int(hi))
        self.setValue(self._value)
        self.changed.emit()

    def setMaximum(self, hi: int):
        self.setRange(self._min, hi)

    def setMinimum(self, lo: int):
        self.setRange(lo, self._max)

    def maximum(self) -> int:
        return self._max

    def minimum(self) -> int:
        return self._min

    def value(self) -> int:
        return self._value

    def setValue(self, v: int):
        v = max(self._min, min(self._max, int(v)))
        if v != self._value:
            self._value = v
            self.update()
            self.valueChanged.emit(v)

    def isSliderDown(self) -> bool:
        return self._down

    def set_look(self, style: str, handle: str):
        self.style_name, self.handle = style, handle
        self.update()
        self.changed.emit()

    def set_waveform(self, data, loading: bool = False):
        self.wave = data
        self.wave_loading = loading
        self.update()
        self.changed.emit()

    def _value_at(self, x: float) -> int:
        m = self._margin()
        w = max(1.0, self.width() - 2 * m)
        frac = min(1.0, max(0.0, (x - m) / w))
        return int(round(self._min + frac * (self._max - self._min)))

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton or self._max <= self._min:
            return
        self._down = True
        self.setValue(self._value_at(e.position().x()))
        self.sliderMoved.emit(self._value)
        self.update()

    def mouseMoveEvent(self, e):
        if self._down:
            self.setValue(self._value_at(e.position().x()))
            self.sliderMoved.emit(self._value)
        if self.style_name in WAVE_STYLES:
            self._hover_x = e.position().x()
            self.update()
        if self.time_tips and self._max > self._min:
            v = self._value_at(e.position().x())
            QToolTip.showText(e.globalPosition().toPoint() - QPoint(0, 34), fmt_time(v / 1000), self)

    def mouseReleaseEvent(self, e):
        if self._down and e.button() == Qt.LeftButton:
            self._down = False
            self.sliderReleased.emit()
            self.update()

    def wheelEvent(self, e):
        if self.time_tips:  # only the volume slider uses the wheel
            return e.ignore()
        step = 5 if e.angleDelta().y() > 0 else -5
        self.setValue(self._value + step)
        e.accept()

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self._hover_x = None
        self.update()

    def _thickness(self) -> float:
        base = {"slider": 4.0, "line": 2.0, "thick": 8.0}.get(self.style_name, 4.0)
        if self.style_name == "line" and (self._hover or self._down):
            base = 4.0
        return base

    def _handle_r(self) -> float:
        return {"slider": 6.0, "line": 5.0, "thick": 7.0, "dots": 5.0, "segments": 5.0}.get(self.style_name, 6.0)

    def _margin(self) -> float:
        if self._wave_like():
            return 2.0
        return self._handle_r() + 1

    def _wave_like(self) -> bool:
        return self.style_name in WAVE_STYLES

    def _show_handle(self) -> bool:
        if self.handle == "never":
            return False
        if self.handle == "hover":
            return self._hover or self._down
        return True

    def _frac(self) -> float:
        return 0.0 if self._max <= self._min else (self._value - self._min) / (self._max - self._min)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        style = self.style_name
        if style in WAVE_STYLES:
            if self.time_tips:
                self._paint_wave(p, style)
            else:
                self._paint_ramp(p)  # volume: a wedge that fills up
        elif style == "dots":
            self._paint_dots(p)
        elif style == "segments":
            self._paint_segments(p)
        else:
            self._paint_bar(p)

    def _colors(self):
        t = self.theme
        rest = QColor(t.color("text"))
        rest.setAlphaF(0.22 if t.dark else 0.18)
        return t.color("accent"), rest

    def _paint_handle(self, p, x, cy):
        if self._show_handle() and self._max > self._min:
            r = self._handle_r()
            p.setPen(Qt.NoPen)
            p.setBrush(self.theme.color("accent") if (self._hover or self._down) and self.style_name == "slider"
                       else self.theme.color("text"))
            p.drawEllipse(QRectF(x - r, cy - r, 2 * r, 2 * r))

    def _paint_bar(self, p):
        t = self.theme
        m = self._margin()
        th_ = self._thickness()
        cy = self.height() / 2
        w = self.width() - 2 * m
        p.setPen(Qt.NoPen)
        p.setBrush(t.color("hover"))
        p.drawRoundedRect(QRectF(m, cy - th_ / 2, w, th_), th_ / 2, th_ / 2)
        frac = self._frac()
        done = QRectF(m, cy - th_ / 2, w * frac, th_)
        p.setBrush(t.color("accent"))
        if done.width() > 0:
            p.drawRoundedRect(done, th_ / 2, th_ / 2)
        self._paint_handle(p, m + w * frac, cy)

    def _paint_dots(self, p):
        acc, rest = self._colors()
        m = self._margin()
        w = self.width() - 2 * m
        cy = self.height() / 2
        x_now = m + w * self._frac()
        step = 6.0
        n = max(2, int(w // step))
        p.setPen(Qt.NoPen)
        big = 1.9 if not (self._hover or self._down) else 2.2
        for i in range(n + 1):
            x = m + i * w / n
            p.setBrush(acc if x <= x_now else rest)
            r = big if x <= x_now else 1.5
            p.drawEllipse(QRectF(x - r, cy - r, 2 * r, 2 * r))
        self._paint_handle(p, x_now, cy)

    def _paint_segments(self, p):
        acc, rest = self._colors()
        m = self._margin()
        w = self.width() - 2 * m
        cy = self.height() / 2
        h = 7.0 if not (self._hover or self._down) else 9.0
        seg, gap = 9.0, 3.0
        n = max(1, int((w + gap) // (seg + gap)))
        seg = (w - gap * (n - 1)) / n
        x_now = m + w * self._frac()
        p.setPen(Qt.NoPen)
        for i in range(n):
            x = m + i * (seg + gap)
            r = QRectF(x, cy - h / 2, seg, h)
            p.setBrush(rest)
            p.drawRoundedRect(r, 2, 2)
            if x_now > x:
                part = QRectF(x, cy - h / 2, min(seg, x_now - x), h)
                p.setBrush(acc)
                p.drawRoundedRect(part, 2, 2)
        self._paint_handle(p, x_now, cy)

    def _values(self, n: int):
        """Waveform resampled to n columns; a flat placeholder while loading."""
        wave = self.wave
        if wave is None or len(wave) == 0:
            if self.wave_loading:
                import math
                return [0.18 + 0.06 * math.sin(i * 0.45) for i in range(n)]
            return [0.16] * n
        L = len(wave)
        out = []
        for i in range(n):
            a = int(i * L / n)
            b = max(a + 1, int((i + 1) * L / n))
            out.append(float(max(wave[a:b])))
        return out

    def _paint_wave(self, p, style):
        acc, rest = self._colors()
        m = self._margin()
        w = self.width() - 2 * m
        H = self.height()
        x_now = m + w * self._frac()
        hover = self._hover_x if (self._hover_x is not None and not self._down) else None
        soft = QColor(acc)
        soft.setAlphaF(0.45)
        if style == "wave":
            n = max(8, int(w // 2))
            vals = self._values(n)
            half = (H - 4) / 2
            cy = H / 2
            path = QPainterPath()
            xs = [m + i * w / (n - 1) for i in range(n)]
            path.moveTo(xs[0], cy - vals[0] * half)
            for x, v in zip(xs[1:], vals[1:]):
                path.lineTo(x, cy - v * half)
            for x, v in zip(reversed(xs), reversed(vals)):
                path.lineTo(x, cy + v * half)
            path.closeSubpath()
            p.setPen(Qt.NoPen)
            p.fillPath(path, rest)
            if hover is not None and hover > x_now:
                p.save()
                p.setClipRect(QRectF(x_now, 0, hover - x_now, H))
                p.fillPath(path, soft)
                p.restore()
            p.save()
            p.setClipRect(QRectF(0, 0, x_now, H))
            p.fillPath(path, acc)
            p.restore()
        else:
            bw, gap = 2.0, 1.0
            n = max(8, int((w + gap) // (bw + gap)))
            vals = self._values(n)
            p.setPen(Qt.NoPen)
            if style == "bars":  # mirrored around the middle
                cy, half = H / 2, (H - 2) / 2
                for i, v in enumerate(vals):
                    x = m + i * (bw + gap)
                    hh = max(1.0, v * half)
                    p.setBrush(acc if x + bw / 2 <= x_now else
                               soft if hover is not None and x <= hover else rest)
                    p.drawRoundedRect(QRectF(x, cy - hh, bw, hh * 2), 1, 1)
            else:  # "cloud": grows up with a faint reflection
                base = H * 0.7
                up, down = base - 1, H - base - 1
                for i, v in enumerate(vals):
                    x = m + i * (bw + gap)
                    played = x + bw / 2 <= x_now
                    c = acc if played else soft if hover is not None and x <= hover else rest
                    p.setBrush(c)
                    p.drawRect(QRectF(x, base - max(1.0, v * up), bw, max(1.0, v * up)))
                    r = QColor(c)
                    r.setAlphaF(r.alphaF() * 0.4)
                    p.setBrush(r)
                    p.drawRect(QRectF(x, base + 1, bw, max(1.0, v * down)))
        if self._show_handle() and self._max > self._min:
            p.fillRect(QRectF(x_now - 1, 1, 2, H - 2), self.theme.color("text"))
        if hover is not None:
            c = QColor(self.theme.color("text"))
            c.setAlphaF(0.5)
            p.fillRect(QRectF(hover - 0.5, 1, 1, H - 2), c)

    def _paint_ramp(self, p):
        acc, rest = self._colors()
        m = self._margin()
        w = self.width() - 2 * m
        H = self.height()
        top, bottom = 2.0, H - 2.0
        path = QPainterPath()
        path.moveTo(m, bottom)
        path.lineTo(m + w, top)
        path.lineTo(m + w, bottom)
        path.closeSubpath()
        p.setPen(Qt.NoPen)
        p.fillPath(path, rest)
        p.save()
        p.setClipRect(QRectF(0, 0, m + w * self._frac(), H))
        p.fillPath(path, acc)
        p.restore()


class _Info(QWidget):
    """Title over artist, elided to fit."""
    textsChanged = Signal(str, str)
    tagChanged = Signal(str)

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        lay.addStretch()
        self.tag = QLabel("")  # "From your queue" while a queued song plays
        self.tag.setObjectName("BarTag")
        self.tag.hide()
        lay.addWidget(self.tag)
        self.title = QLabel("")
        self.title.setObjectName("BarTitle")
        self.artist = QLabel("")
        self.artist.setObjectName("BarArtist")
        lay.addWidget(self.title)
        lay.addWidget(self.artist)
        lay.addStretch()
        self._texts = ("", "")
        self.setMinimumWidth(90)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)

    def sizeHint(self):
        return QSize(210, 40)

    def set_text(self, title: str, artist: str):
        self._texts = (title, artist)
        self._elide()
        self.textsChanged.emit(title, artist)

    def set_tag(self, text: str):
        self.tag.setText(text)
        self.tag.setVisible(bool(text))
        self.tagChanged.emit(text)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._elide()

    def _elide(self):
        w = max(40, self.width())
        for lbl, text in zip((self.title, self.artist), self._texts):
            lbl.setText(QFontMetrics(lbl.font()).elidedText(text, Qt.ElideRight, w))
            lbl.setToolTip(text if lbl.text() != text else "")


class _Label(QLabel):
    """A label whose copies in the panels follow its text."""
    textSet = Signal(str)

    def setText(self, text: str):
        super().setText(text)
        self.textSet.emit(text)


class _Clickable(_Label):
    clicked = Signal()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()


class _Spacer(QWidget):
    def __init__(self, kind: str, width: int = 16):
        super().__init__()
        self.kind = kind
        self.gap = width
        if kind == "stretch":
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
            self.setMinimumWidth(8)
        else:
            self.setFixedWidth(width)

    def set_gap(self, w: int):
        self.gap = max(4, min(160, w))
        self.setFixedWidth(self.gap)


class _CopyButton(IconButton):
    """A button in a panel that works like one in the play bar."""

    def __init__(self, src: IconButton):
        super().__init__(src.icon_name, src.icon_px, src.toolTip())
        self.src = src
        self.setObjectName(src.objectName())
        self.setCheckable(src.isCheckable())
        src.looksChanged.connect(self.follow)
        src.toggled.connect(self.setChecked)
        self.clicked.connect(self._click)
        self.follow()

    def follow(self):
        s = self.src
        self.icon_name, self.color_key, self.icon_style = s.icon_name, s.color_key, s.icon_style
        if self.icon_px != s.icon_px:
            self.icon_px = s.icon_px
            self.setIconSize(s.iconSize())
        QToolButton.setIcon(self, s.icon())
        QToolButton.setToolTip(self, s.toolTip())
        QToolButton.setStyleSheet(self, s.styleSheet())
        if s.minimumSize() == s.maximumSize():
            QToolButton.setFixedSize(self, s.minimumSize())
        self.setChecked(s.isChecked())

    def _click(self):
        self.src.copy_pos = self.mapToGlobal(self.rect().topLeft())  # menus open by this copy
        self.src.click()
        self.src.copy_pos = None
        self.setChecked(self.src.isChecked())


class _CopyLabel(QLabel):
    def __init__(self, src: QLabel):
        super().__init__(src.text())
        self.setObjectName(src.objectName())
        src.textSet.connect(self.setText)


class _CopyInfo(_Info):
    def __init__(self, src: _Info):
        super().__init__()
        self.set_text(*src._texts)
        self.set_tag(src.tag.text())
        src.textsChanged.connect(self.set_text)
        src.tagChanged.connect(self.set_tag)


class _CopyPill(QPushButton):
    """ "▶ Your copy", shown while the radio plays a song you have."""
    activeChanged = Signal(bool)

    def __init__(self, bar):
        src = bar.copy_btn
        super().__init__(src.text())
        self.bar = bar
        self.setObjectName(src.objectName())
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(22)
        self.setToolTip(src.toolTip())
        self.clicked.connect(src.click)
        bar.copyShown.connect(self.activeChanged)

    def active(self) -> bool:
        return self.bar.copy_shown


class _CopySlider(SeekBar):
    """A slider that follows another one; dragging it moves the original."""

    def __init__(self, src: SeekBar, time_tips: bool):
        super().__init__(src.theme, time_tips=time_tips)
        self.src = src
        src.changed.connect(self.follow)
        src.valueChanged.connect(self._src_value)
        self.follow()

    def follow(self):
        s = self.src
        self._min, self._max = s.minimum(), s.maximum()
        self.style_name, self.handle = s.style_name, s.handle
        self.wave, self.wave_loading = s.wave, s.wave_loading
        self._src_value(s.value())
        self.update()

    def _src_value(self, v: int):
        if not self.isSliderDown() and v != self._value:
            self._value = v
            self.update()


class _CopyVolume(_CopySlider):
    def __init__(self, src: SeekBar):
        super().__init__(src, time_tips=False)
        self.setFixedWidth(110)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.valueChanged.connect(src.setValue)


class _CopySeek(QWidget):
    """The seek bar with its times, for a panel."""

    def __init__(self, bar):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.elapsed = _CopyLabel(bar.elapsed)
        self.elapsed.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.seek = _CopySlider(bar.seek, time_tips=True)
        self.total = _CopyLabel(bar.total)
        self.total.setCursor(Qt.PointingHandCursor)
        self.total.setToolTip(bar.total.toolTip())
        self.total.mouseReleaseEvent = lambda e: bar.total.clicked.emit()
        for w in (self.elapsed, self.total):
            w.setFixedWidth(46)
        lay.addWidget(self.elapsed)
        lay.addWidget(self.seek, 1)
        lay.addWidget(self.total)
        src = bar.seek
        self.seek.sliderMoved.connect(lambda v: (src.setValue(v), src.sliderMoved.emit(v)))
        self.seek.sliderReleased.connect(lambda: (src.setValue(self.seek.value()), src.sliderReleased.emit()))
        self.setMinimumWidth(180)


def _panels(widget) -> list:
    from musicwell.panel import NowPlayingPanel
    return [p for p in widget.window().findChildren(NowPlayingPanel) if p.isVisible() and p.editing]


def _panel_at(widget, g):
    for p in _panels(widget):
        if p.rect().contains(p.mapFromGlobal(g)):
            return p
    return None


class _SlotOverlay(QWidget):
    """Unlocked: a faint outline around an item (clicks pass through)."""

    def __init__(self, slot):
        super().__init__(slot)
        self.slot = slot
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.hot = False

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        t = self.slot.bar.theme
        c = QColor(t.color("accent") if self.hot else t.color("faint"))
        c.setAlpha(210 if self.hot else 120)
        pen = QPen(c)
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
        if self.slot.key.split(":")[0] in SPACER_NAMES:
            p.setPen(t.color("muted"))
            f = QFont(self.font())
            f.setPointSizeF(7.5)
            p.setFont(f)
            p.drawText(self.rect(), Qt.AlignCenter, "↔" if self.slot.key.startswith("stretch") else "␣")


class _SlotHandle(QLabel):
    """Unlocked: a grip for items that are themselves draggable (the volume slider)."""

    def __init__(self, slot):
        super().__init__("⠿", slot)
        self.slot = slot
        self.setFixedSize(14, 20)
        self.setAlignment(Qt.AlignCenter)
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip(f"Drag to move “{item_name(slot.key)}”")
        self._press = None
        self.hide()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press = e.position().toPoint()

    def mouseMoveEvent(self, e):
        if self._press is not None and (e.position().toPoint() - self._press).manhattanLength() \
                >= QApplication.startDragDistance():
            self._press = None
            self.slot.bar._start_drag(self.slot.key, self.slot)

    def mouseReleaseEvent(self, e):
        self._press = None


class _SizeGrip(QWidget):
    """Unlocked: a corner grip for resizing an item. corner: "tl", "tr", "bl" or "br"."""

    def __init__(self, slot, corner: str = "br"):
        super().__init__(slot)
        self.slot = slot
        self.corner = corner
        self.sx = -1 if corner[1] == "l" else 1  # dragging a left corner left makes it wider
        self.sy = -1 if corner[0] == "t" else 1
        self.setFixedSize(12, 12)
        self.setCursor(Qt.SizeFDiagCursor if corner in ("tl", "br") else Qt.SizeBDiagCursor)
        self.setToolTip(f"Drag to resize “{item_name(slot.key)}” (double-click: its own size)")
        self._start = None
        self.hide()

    def place(self):
        sw, sh = self.slot.width(), self.slot.height()
        self.move(0 if self.sx < 0 else sw - self.width(), 0 if self.sy < 0 else sh - self.height())

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = self.slot.bar.theme.color("accent")
        p.setPen(QPen(c, 1.4))
        for d in (3, 7, 11):
            a = QPointF(d, 11.5)
            b = QPointF(11.5, d)
            if self.sx < 0:
                a, b = QPointF(11.5 - a.x(), a.y()), QPointF(11.5 - b.x(), b.y())
            if self.sy < 0:
                a, b = QPointF(a.x(), 11.5 - a.y()), QPointF(b.x(), 11.5 - b.y())
            p.drawLine(a, b)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            v = self.slot.widget
            self._start = (e.globalPosition(), v.width(), v.height())
            if self.slot.key == "viz" and self.slot.bar.viz_fill:
                self.slot.bar.set_viz_fill(False, save=False)  # dragging sets its own width again

    def mouseMoveEvent(self, e):
        if self._start is not None:
            g0, w0, h0 = self._start
            d = e.globalPosition() - g0
            self.slot.bar.set_item_size(self.slot.key, int(w0 + self.sx * d.x()), int(h0 + self.sy * d.y()), save=False)

    def mouseReleaseEvent(self, e):
        if self._start is not None:
            self._start = None
            self.slot.bar.layoutChanged.emit()

    def mouseDoubleClickEvent(self, e):
        self.slot.bar.set_item_size(self.slot.key, None, None)


class _HeightGrip(QWidget):
    """Edge facing the music: drag to resize the bottom panel."""

    def __init__(self, bar):
        super().__init__(bar)
        self.bar = bar
        self.setCursor(Qt.SizeVerCursor)
        self.setToolTip("Drag to make the play bar taller or shorter · double-click: its own height")
        self._start = None
        self._hot = False

    def enterEvent(self, e):
        self._hot = True
        self.update()

    def leaveEvent(self, e):
        self._hot = False
        self.update()

    def paintEvent(self, _):
        if not (self._hot or self._start is not None):
            return
        p = QPainter(self)
        c = QColor(self.bar.theme.color("accent"))
        c.setAlpha(160)
        y = 0 if self.bar.options.get("position") != "top" else self.height() - 2
        p.fillRect(0, y, self.width(), 2, c)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._start = (e.globalPosition().y(), self.bar.height())

    def mouseMoveEvent(self, e):
        if self._start is not None:
            y0, h0 = self._start
            dy = int(e.globalPosition().y() - y0)
            up = self.bar.options.get("position") != "top"  # at the bottom, dragging up makes it taller
            self.bar.set_bar_height(h0 - dy if up else h0 + dy, save=False)

    def mouseReleaseEvent(self, e):
        if self._start is not None:
            self._start = None
            self.update()
            self.bar.layoutChanged.emit()

    def mouseDoubleClickEvent(self, e):
        self.bar.set_bar_height(None)


class _Slot(QWidget):
    """Holds one bar item so it can be outlined and dragged while unlocked."""

    def __init__(self, bar, key: str, widget: QWidget):
        super().__init__()
        self.bar = bar
        self.key = key
        self.widget = widget
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.handle = _SlotHandle(self)
        lay.addWidget(widget)
        sizeable = key in SIZEABLE or key.startswith("panel:")
        self.sizers = [_SizeGrip(self, c) for c in ("tl", "tr", "bl", "br")] if sizeable else []
        self.overlay = _SlotOverlay(self)
        self.overlay.hide()
        self._press = None
        self._watched: set = set()
        if key in EXPANDING or key.startswith("stretch"):
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        elif key == "info":
            self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        else:
            self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.overlay.setGeometry(self.rect())
        self._place_handle()

    def _place_handle(self):
        self.handle.move(-2, max(0, (self.height() - self.handle.height()) // 2))
        self.handle.raise_()
        for g in self.sizers:
            g.place()
            g.raise_()

    def set_editing(self, on: bool, outlines: bool = True):
        self.overlay.setVisible(on and outlines)
        self._grippy = on and isinstance(self.widget, (QAbstractSlider, SeekBar))
        t = self.bar.theme
        self.handle.setStyleSheet(f"QLabel{{color:{t.color('muted').name()}; background:{t.color('surface').name()};"
                                  f"border-radius:4px; font-size:9pt;}}")
        self.handle.setVisible(self._grippy and (outlines or self.underMouse()))
        for g in self.sizers:
            g.setVisible(on)
        self._place_handle()
        self.layout().setContentsMargins(*((3, 2, 3, 2) if (on and outlines) else (0, 0, 0, 0)))
        if on:
            for c in [self, self.widget] + self.widget.findChildren(QWidget):
                if c not in self._watched:
                    c.installEventFilter(self)
                    self._watched.add(c)
            self.overlay.setGeometry(self.rect())
            self.overlay.raise_()
            if self.key.split(":")[0] in SPACER_NAMES and outlines:
                self.setMinimumWidth(18)
        elif self.key.split(":")[0] in SPACER_NAMES and self.key.startswith("gap"):
            self.setMinimumWidth(0)

    def eventFilter(self, obj, e):
        """Unlocked: dragging the item moves it (clicks still click, sliders still slide)."""
        if not self.bar.editing or isinstance(obj, _SizeGrip):
            return False
        t = e.type()
        if t in (QEvent.Enter, QEvent.Leave):
            hot = t == QEvent.Enter or self.rect().contains(self.mapFromGlobal(self.cursor().pos()))
            if hot != self.overlay.hot:
                self.overlay.hot = hot
                self.overlay.update()
            if getattr(self, "_grippy", False):
                self.handle.setVisible(hot or self.bar.outlines)
                self._place_handle()
        elif t == QEvent.MouseButtonPress and e.button() == Qt.LeftButton \
                and not isinstance(obj, (QAbstractSlider, SeekBar)):
            self._press = e.globalPosition().toPoint()
        elif t == QEvent.MouseMove and self._press is not None and e.buttons() & Qt.LeftButton:
            if (e.globalPosition().toPoint() - self._press).manhattanLength() >= QApplication.startDragDistance() + 3:
                self._press = None
                obj.setDown(False) if hasattr(obj, "setDown") else None
                self.bar._start_drag(self.key, self)
                return True
        elif t == QEvent.MouseButtonRelease:
            self._press = None
        return False


class _Zone(QWidget):
    """One area of the bar. Accepts drops while customizing."""

    def __init__(self, bar, name: str):
        super().__init__()
        self.bar = bar
        self.name = name
        self.setAcceptDrops(True)
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(6)
        self._indicator_x = None

    def slots(self) -> list:
        out = []
        for i in range(self.row.count()):
            w = self.row.itemAt(i).widget()
            if isinstance(w, _Slot):
                out.append(w)
        return out

    def drop_index(self, x: float) -> int:
        slots = [s for s in self.slots() if s.isVisible()]
        keys = self.bar.zones[self.name]
        for s in slots:
            if x < s.geometry().center().x():
                return keys.index(s.key) if s.key in keys else len(keys)
        return len(keys)

    def _indicator_at(self, x: float):
        slots = [s for s in self.slots() if s.isVisible()]
        for s in slots:
            if x < s.geometry().center().x():
                return s.geometry().left() - 4
        if slots:
            return slots[-1].geometry().right() + 3
        return self.width() // 2

    def dragEnterEvent(self, e):
        if self.bar.editing and e.mimeData().hasFormat(MIME):
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasFormat(MIME):
            e.acceptProposedAction()
            self._indicator_x = self._indicator_at(e.position().x())
            self.update()

    def dragLeaveEvent(self, e):
        self._indicator_x = None
        self.update()

    def dropEvent(self, e):
        key = bytes(e.mimeData().data(MIME)).decode()
        i = self.drop_index(e.position().x())
        self._indicator_x = None
        self.update()
        e.acceptProposedAction()
        QTimer.singleShot(0, lambda: self.bar.place_item(key, self.name, i))

    def paintEvent(self, _):
        if not self.bar.editing:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        t = self.bar.theme
        if not (self.bar.outlines or self.bar._dragging_item):
            if self._indicator_x is not None:
                p.fillRect(QRectF(self._indicator_x, 3, 3, self.height() - 6), t.color("accent"))
            return
        c = QColor(t.color("faint"))
        c.setAlpha(90)
        pen = QPen(c)
        pen.setStyle(Qt.DotLine)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        if not self.bar.zones[self.name]:
            p.setPen(t.color("faint"))
            f = QFont(self.font())
            f.setPointSizeF(8)
            p.setFont(f)
            p.drawText(self.rect(), Qt.AlignCenter,
                       f"Bottom Panel · {ZONE_NAMES[self.name].lower()} — drag items here, or right-click → Add here")
        if self._indicator_x is not None:
            p.fillRect(QRectF(self._indicator_x, 3, 3, self.height() - 6), t.color("accent"))


class _FlowLayout(QLayout):
    """Left-to-right layout that wraps."""

    def __init__(self, parent=None, spacing: int = 6):
        super().__init__(parent)
        self._items = []
        self._sp = spacing

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._do(QRect(0, 0, w, 0), True)

    def setGeometry(self, r):
        super().setGeometry(r)
        self._do(r, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize()
        for it in self._items:
            s = s.expandedTo(it.widget().sizeHint() if it.widget() is not None else it.sizeHint())
        m = self.contentsMargins()
        return s + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do(self, r, test):
        m = self.contentsMargins()
        x, y, line = r.x() + m.left(), r.y() + m.top(), 0
        right = r.right() - m.right()
        for it in self._items:
            sz = it.widget().sizeHint() if it.widget() is not None else it.sizeHint()
            if x + sz.width() > right and line > 0:
                x, y, line = r.x() + m.left(), y + line + self._sp, 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), sz))
            x += sz.width() + self._sp
            line = max(line, sz.height())
        return y + line - r.y() + m.bottom()


class _Tray(QWidget):
    """Edit strip: unused items, options, Reset and Done. Dropping an item here removes it."""

    def __init__(self, bar):
        super().__init__()
        self.bar = bar
        self.setAcceptDrops(True)
        self.setObjectName("BarTray")
        self.setAttribute(Qt.WA_StyledBackground, True)
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(6)
        head = QHBoxLayout()
        msg = QLabel("Drag items to move them. Drag here to remove; drag from here to add. "
                     "Right-click a gap to resize it.")
        msg.setObjectName("BarArtist")
        msg.setWordWrap(True)
        head.addWidget(msg, 1)
        self.options_btn = QPushButton("Options")
        self.options_btn.setToolTip("Icon size and style, play button, seek bar")
        self.options_menu = QMenu(self.options_btn)
        self.options_menu.aboutToShow.connect(lambda: bar.fill_options_menu(self.options_menu))
        self.options_btn.setMenu(self.options_menu)
        reset = QPushButton("Reset")
        reset.setToolTip("Back to the original play bar")
        reset.clicked.connect(bar.reset_layout)
        done = QPushButton("Done")
        done.setObjectName("Primary")
        done.clicked.connect(lambda: bar.set_editing(False))
        for w in (self.options_btn, reset, done):
            head.addWidget(w)
        v.addLayout(head)
        self.chips_box = QWidget()
        self.flow = _FlowLayout(self.chips_box)
        self.flow.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self.chips_box)
        self._hot = False

    def _fit(self):
        w = self.chips_box.width() if self.chips_box.width() > 50 else self.width() - 20
        self.chips_box.setFixedHeight(self.flow.heightForWidth(max(200, w)))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(MIME):
            key = bytes(e.mimeData().data(MIME)).decode()
            if not key.startswith("new:"):
                e.acceptProposedAction()
                self._hot = True
                self.update()

    def dragLeaveEvent(self, e):
        self._hot = False
        self.update()

    def dropEvent(self, e):
        key = bytes(e.mimeData().data(MIME)).decode()
        self._hot = False
        e.acceptProposedAction()
        QTimer.singleShot(0, lambda: self.bar.remove_item(key))

    def paintEvent(self, e):
        super().paintEvent(e)
        if self._hot:
            p = QPainter(self)
            pen = QPen(self.bar.theme.color("accent"))
            pen.setWidth(2)
            p.setPen(pen)
            p.drawRect(self.rect().adjusted(1, 1, -1, -1))


class PlayBar(QWidget):
    layoutChanged = Signal()
    coverStyleChanged = Signal(str)  # every album cover follows
    copyShown = Signal(bool)
    panelItemsChanged = Signal(list)  # panel items now in the bar  # "▶ Your copy" shown or hidden
    editingChanged = Signal(bool)
    lockRequested = Signal(bool)
    itemRemoved = Signal(str)  # dragged out of the bar
    positionChanged = Signal(str)  # "top" / "bottom"
    lyricsRequested = Signal()
    panelRequested = Signal()
    locateRequested = Signal()
    skipRequested = Signal(int)  # ms, + or -
    stopRequested = Signal()
    rated = Signal(int)
    refreshImagesRequested = Signal()
    likeRequested = Signal()
    copyRequested = Signal()  # play your copy of the radio song
    waveformWanted = Signal(object)  # track whose waveform is needed

    def __init__(self, theme: th.Theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.setObjectName("PlayBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.editing = False
        self.outlines = True  # unlocked: faint outlines around items
        self._dragging_item = False
        self.eq_on = False
        self.cast_on = False
        self.lyrics_on = False
        self.panel_on = True
        self.zones = copy.deepcopy(DEFAULT_ZONES)
        self.options = dict(DEFAULT_OPTIONS)
        self.gaps: dict[str, int] = {}
        self.viz_size: list | None = None  # [width, height] once set
        self.viz_fill = False  # the visualizer takes the whole width of its row
        self.info_size: list | None = None  # same, for About the artist
        self.cover_size: int | None = None  # cover side once resized
        self.item_sizes: dict[str, list] = {}  # panel items' sizes in the bar
        self.text_sizes: dict[str, float] = {}  # bigger or smaller text than the theme's
        self.panel_items: list[str] = []
        self.unavailable: set[str] = set()
        self._playing, self._repeat, self._muted, self._volume = False, 0, False, 1.0
        self._last_ms, self._last_dur = 0, 0
        self._track = None
        self._art = None
        self._graveyard = []  # widgets removed mid-drag; dropped when editing ends

        # every item exists even when not placed
        self.thumb = _Clickable()
        self.thumb.setCursor(Qt.PointingHandCursor)
        self.thumb.setToolTip("Show the playing song in the library (Ctrl+J)")
        self.thumb.clicked.connect(self.locateRequested)
        from musicwell.record import Disc, Spinner
        self.disc = Disc()
        self.spinner = Spinner(self)
        self.spinner.changed.connect(self._spin_thumb)
        self.info = _Info()
        self.title, self.artist = self.info.title, self.info.artist
        self.shuffle = IconButton("shuffle", 18, "Shuffle (Ctrl+S)")
        self.shuffle.setCheckable(True)
        self.prev = IconButton("prev", 22, "Previous (Ctrl+Left)")
        self.back10 = IconButton("back10", 22, "Back 10 seconds")
        self.back10.clicked.connect(lambda: self.skipRequested.emit(-10000))
        self.play = IconButton("play", 22, "Play / pause (Space)")
        self.play.setObjectName("PlayButton")
        self.stop_btn = IconButton("stop", 20, "Stop")
        self.stop_btn.clicked.connect(self.stopRequested)
        self.fwd10 = IconButton("fwd10", 22, "Forward 10 seconds")
        self.fwd10.clicked.connect(lambda: self.skipRequested.emit(10000))
        self.next = IconButton("next", 22, "Next (Ctrl+Right)")
        self.repeat = IconButton("repeat", 18, "Repeat: off (Ctrl+R)")
        self.repeat.setCheckable(True)

        self.seek_box = QWidget()
        sr = QHBoxLayout(self.seek_box)
        sr.setContentsMargins(0, 0, 0, 0)
        sr.setSpacing(8)
        self.elapsed = _Label("0:00")
        self.elapsed.setObjectName("TimeLabel")
        self.elapsed.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.seek = SeekBar(theme)
        self.total = _Clickable("0:00")
        self.total.setObjectName("TimeLabel")
        self.total.setToolTip("Click to switch between the length and the time left")
        self.total.setCursor(Qt.PointingHandCursor)
        self.total.clicked.connect(self._toggle_remaining)
        for w in (self.elapsed, self.total):
            w.setFixedWidth(46)
        sr.addWidget(self.elapsed)
        sr.addWidget(self.seek, 1)
        sr.addWidget(self.total)
        self.seek_box.setMinimumWidth(180)
        self.time_label = _Label("0:00 / 0:00")
        self.time_label.setObjectName("TimeLabel")
        self.seek.sliderMoved.connect(self._on_seek_moved)

        self.stop_after = IconButton("stop_after", 18, "Stop after this song")
        self.stop_after.setCheckable(True)
        self.stars = StarRow(theme, 14)
        self.stars.rated.connect(self.rated)
        self.lyrics_btn = IconButton("lyrics", 18, "Lyrics")
        self.lyrics_btn.clicked.connect(self.lyricsRequested)
        self.locate_btn = IconButton("locate", 18, "Show the playing song in the library (Ctrl+J)")
        self.locate_btn.clicked.connect(self.locateRequested)
        self.refresh_btn = IconButton("refresh", 18, "Reload the album cover and artist photo (Ctrl+F5)")
        self.refresh_btn.clicked.connect(self.refreshImagesRequested)
        self.like_btn = IconButton("heart_empty", 18, "♥ Like this song — Ctrl+Shift+L")
        self.like_btn.clicked.connect(self.likeRequested)
        self.like_state = None  # None / False / True
        self.copy_btn = QPushButton("▶ Your copy")
        self.copy_btn.setObjectName("CopyPill")
        self.copy_btn.setCursor(Qt.PointingHandCursor)
        self.copy_btn.setFixedHeight(22)  # rounded ends need a fixed height
        self.copy_btn.setToolTip("The radio is playing a song you have — click to play your own copy")
        self.copy_btn.clicked.connect(self.copyRequested)
        self.copy_shown = False
        self.cast_btn = IconButton("cast", 18, "Play on a speaker or TV (Chromecast or Sonos)")
        self.eq_btn = IconButton("eq", 18, "Equalizer (Ctrl+Shift+E)")
        self.queue_btn = IconButton("queue", 18, "Show queue")
        self.panel_btn = IconButton("panel", 18, "Show / hide the now playing panel (F9)")
        self.panel_btn.clicked.connect(self.panelRequested)
        self.vol_btn = IconButton("volume", 18, "Mute")
        self.volume = SeekBar(theme, time_tips=False)
        self.volume.setRange(0, 100)
        self.volume.setFixedWidth(110)
        self.volume.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.volume.valueChanged.connect(lambda v: self.volume.setToolTip(f"Volume {v}%"))
        from musicwell.visualizer import Visualizer
        self.viz = Visualizer(theme)
        self.viz.setMinimumHeight(0)
        self.viz.setFixedSize(*self.VIZ_SIZE)
        self.viz.menu_blocked = lambda: self.editing  # unlocked: the bar's own menu
        from musicwell.artistinfo import ArtistInfoView
        self.artist_info = ArtistInfoView(theme)
        self.artist_info.can_fill = False
        self.artist_info.setFixedSize(*self.INFO_SIZE)

        self.widgets = {
            "cover": self.thumb, "info": self.info, "shuffle": self.shuffle, "prev": self.prev,
            "back10": self.back10, "play": self.play, "stop": self.stop_btn, "fwd10": self.fwd10,
            "next": self.next, "repeat": self.repeat, "seek": self.seek_box, "time": self.time_label,
            "stopafter": self.stop_after, "rating": self.stars, "lyrics": self.lyrics_btn,
            "locate": self.locate_btn, "refresh": self.refresh_btn, "like": self.like_btn,
            "copy": self.copy_btn,
            "cast": self.cast_btn, "eq": self.eq_btn,
            "queue": self.queue_btn, "panel": self.panel_btn, "mute": self.vol_btn,
            "volume": self.volume, "viz": self.viz, "artist_info": self.artist_info,
        }
        self.slots: dict[str, _Slot] = {k: _Slot(self, k, w) for k, w in self.widgets.items()}
        for k in TEXT_ITEMS & set(self.slots):
            self._text_widget(k).menu_extras = lambda m, k=k: self._add_text_size(m, k)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.main = QWidget()
        self.main_lay = QVBoxLayout(self.main)
        self.main_lay.setSpacing(4)
        self.zone_w = {z: _Zone(self, z) for z in ZONES}
        self.main_lay.addWidget(self.zone_w["top"])
        row = QHBoxLayout()
        row.setSpacing(12)
        self.row = row
        mid = QVBoxLayout()
        mid.setSpacing(2)
        mid.addWidget(self.zone_w["center"])
        mid.addWidget(self.zone_w["below"])
        row.addWidget(self.zone_w["left"], 1)
        row.addLayout(mid, 2)
        row.addWidget(self.zone_w["right"], 1)
        self.main_lay.addLayout(row)
        outer.addWidget(self.main, 0, Qt.AlignVCenter)  # stay vertically centred when taller
        self.bar_height: int | None = None  # height you dragged it to (None = natural)
        self.height_grip = _HeightGrip(self)
        self.tray = _Tray(self)
        self.tray.hide()
        outer.addWidget(self.tray)
        self.setAcceptDrops(True)
        self._rebuild()

    # dropped between areas: nothing changes
    def dragEnterEvent(self, e):
        if self.editing and e.mimeData().hasFormat(MIME):
            e.acceptProposedAction()

    def dropEvent(self, e):
        e.acceptProposedAction()

    def all_placed(self) -> list[str]:
        return [k for z in ZONES for k in self.zones[z]]

    def unused(self) -> list[str]:
        placed = set(self.all_placed())
        return [k for k in ITEMS if k not in placed and k not in self.unavailable]

    def _slot(self, key: str) -> _Slot:
        if key not in self.slots:
            kind = key.split(":")[0]
            if kind == "panel":
                w = self.make_item(key)
                w.set_size(*self.item_sizes.get(key, (None, None)))
                w.activeChanged.connect(lambda _on: self._rebuild())
            elif kind == "top":
                w = self.make_item(key)
            else:
                w = _Spacer(kind, self.gaps.get(key, 16))
            self.slots[key] = _Slot(self, key, w)
            if key in TEXT_ITEMS:
                self._text_widget(key).menu_extras = lambda m, k=key: self._add_text_size(m, k)
            if key in self.text_sizes:
                scale_text(self._text_widget(key), self.text_sizes[key])
        return self.slots[key]

    make_item = None  # callable(key) -> widget for "panel:" and "top:" items, set by the window
    drop_on_top = None  # callable(key, global point) -> True: moved to the top bar, None: it can't go there

    def _shown(self, key: str) -> bool:
        """Whether an item shows while locked (some only have something to show some of the time)."""
        if key in self.unavailable or (key == "copy" and not self.copy_shown):
            return False
        s = self.slots.get(key)
        return not (key.startswith("panel:") and s is not None and not s.widget.active())

    def _rebuild(self):
        cover_px = self.cover_size or SIZES[self.options["icon_size"]][3]
        self.thumb.setFixedSize(cover_px, cover_px)
        style = self.options.get("cover_style", "square")
        if style != self.disc.style or (style == "square") == self.spinner.active:
            self.disc.set_style(style)
            self.spinner.set_active(style != "square")
            if getattr(self, "_track", None) is not None:
                self._paint_thumb()
        for z in ZONES:
            zw = self.zone_w[z]
            while zw.row.count():
                it = zw.row.takeAt(0)
                w = it.widget()
                if w is not None:
                    w.setParent(None)
            keys = self.zones[z]
            expanding = any(k in EXPANDING or k.startswith("stretch") or (k == "viz" and self.viz_fill) for k in keys)
            if z == "left":
                lead, trail = False, not expanding
            elif z == "right":
                lead, trail = not expanding, False
            else:
                lead = trail = not expanding
            if lead:
                zw.row.addStretch(1)
            for k in keys:
                s = self._slot(k)
                zw.row.addWidget(s)
                s.setVisible(self.editing or self._shown(k))
                s.set_editing(self.editing, self.outlines)
                if k == "info":
                    zw.row.setStretchFactor(s, 1 if z in ("left", "right") and not expanding else 0)
            if trail:
                zw.row.addStretch(1)
            filled = any(self._shown(k) for k in keys)
            show_empty = self.editing and (self.outlines or self._dragging_item)
            zw.setVisible(filled or show_empty)
            zw.setMinimumHeight(30 if show_empty else 0)
        # slots not in the bar
        placed = set(self.all_placed())
        for k, s in list(self.slots.items()):
            if k not in placed:
                s.setParent(None)
                s.hide()
                if k.split(":")[0] in SPACER_NAMES:  # a removed spacer
                    self._graveyard.append(self.slots.pop(k))
                    self.gaps.pop(k, None)
        self._balance_sides()
        self.row.setStretchFactor(self.zone_w["left"], 1)
        self.row.setStretchFactor(self.zone_w["right"], 1)
        m = 8 if self.options["icon_size"] != "large" else 10
        at_top = self.options.get("position") == "top"
        # the full-width strip sits on the edge facing the music
        strip = self.zone_w["top"]
        self.main_lay.removeWidget(strip)
        self.main_lay.insertWidget(self.main_lay.count() if at_top else 0, strip)
        if at_top:
            self.main_lay.setContentsMargins(16, m, 20, m if not self.zones["top"] else 6)
        else:
            self.main_lay.setContentsMargins(16, m if not self.zones["top"] else 6, 20, m)
        self._place_height_grip()
        if self.property("atTop") != at_top:
            self.setProperty("atTop", at_top)
            self.style().unpolish(self)
            self.style().polish(self)
            self.update()
        if getattr(self, "_placed", None) != self.options.get("position"):
            self._placed = self.options.get("position")
            self.positionChanged.emit(self._placed)
        self.tray.hide()  # old tray: right-click -> Add here replaced it
        self.main_lay.setSpacing(6 if (self.editing and self.outlines) else 4)
        self.apply_theme(self.theme, self._playing, self._repeat, self._muted, self._volume)
        self._apply_seek_look()
        self.set_position(self._last_ms, self._last_dur)
        keys = [k[6:] for k in self.all_placed() if k.startswith("panel:")]
        if keys != self.panel_items:
            self.panel_items = keys
            self.panelItemsChanged.emit(keys)

    def state(self) -> dict:
        return {"zones": self.zones, "options": self.options, "gaps": self.gaps, "viz_size": self.viz_size,
                "viz_fill": self.viz_fill,
                "info_size": self.info_size, "height": self.bar_height, "cover_size": self.cover_size,
                "item_sizes": self.item_sizes, "text_sizes": self.text_sizes}

    def restore_state(self, data):
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except ValueError:
                data = None
        if not isinstance(data, dict):
            return
        zones = data.get("zones")
        if isinstance(zones, dict):
            seen = set()
            new = {}
            for z in ZONES:
                keep = []
                for k in zones.get(z, []) if isinstance(zones.get(z), list) else []:
                    if not isinstance(k, str) or k in seen:
                        continue
                    if k.startswith(("panel:", "top:")) and not self.make_item:
                        continue
                    if k in ITEMS or (k.split(":")[0] in SPACER_NAMES and ":" in k):
                        keep.append(k)
                        seen.add(k)
                new[z] = keep
            self.zones = new
        opts = data.get("options")
        if isinstance(opts, dict):
            for k, v in opts.items():
                if k in OPTION_CHOICES and v in dict(OPTION_CHOICES[k][1]):
                    self.options[k] = v
        gaps = data.get("gaps")
        if isinstance(gaps, dict):
            self.gaps = {k: int(v) for k, v in gaps.items() if isinstance(v, (int, float))}
        self.viz_fill = bool(data.get("viz_fill"))
        vs = data.get("viz_size")
        if isinstance(vs, list) and len(vs) == 2 and all(isinstance(v, (int, float)) for v in vs):
            self.set_viz_size(int(vs[0]), int(vs[1]), save=False)
        else:
            self.set_viz_size(None, None, save=False)
        bh = data.get("height")
        self.set_bar_height(int(bh) if isinstance(bh, (int, float)) and bh else None, save=False)
        cs = data.get("cover_size")
        self.set_item_size("cover", int(cs) if isinstance(cs, (int, float)) and cs else None, None, save=False)
        vs = data.get("info_size")
        if isinstance(vs, list) and len(vs) == 2 and all(isinstance(v, (int, float)) for v in vs):
            self.set_item_size("artist_info", int(vs[0]), int(vs[1]), save=False)
        else:
            self.set_item_size("artist_info", None, None, save=False)
        ts = data.get("text_sizes")
        self.text_sizes = {k: float(v) for k, v in ts.items() if k in ITEMS and isinstance(v, (int, float))
                           and 0.5 <= v <= 2} if isinstance(ts, dict) else {}
        self.apply_text_sizes()
        sizes = data.get("item_sizes")
        self.item_sizes = {k: v for k, v in sizes.items() if k in ITEMS and isinstance(v, list) and len(v) == 2
                           and all(isinstance(x, (int, float)) for x in v)} if isinstance(sizes, dict) else {}
        for k, s in list(self.slots.items()):
            if k.split(":")[0] in SPACER_NAMES:
                s.setParent(None)
                self._graveyard.append(self.slots.pop(k))
            elif k.startswith("panel:"):
                s.widget.set_size(*self.item_sizes.get(k, (None, None)))
        self._rebuild()

    def reset_layout(self):
        self.zones = copy.deepcopy(DEFAULT_ZONES)
        self.options = dict(DEFAULT_OPTIONS, position=self.options.get("position", "bottom"))
        self.gaps = {}
        self.viz_fill = False
        self.set_viz_size(None, None, save=False)
        self.set_item_size("artist_info", None, None, save=False)
        self.set_item_size("cover", None, None, save=False)
        self.item_sizes = {}
        self.text_sizes = {}
        self.apply_text_sizes()
        for k, s in self.slots.items():
            if k.startswith("panel:"):
                s.widget.set_size(None, None)
        self.set_bar_height(None, save=False)
        self._rebuild()
        self.layoutChanged.emit()

    def shutdown(self):
        """Parent every unplaced item so it's destroyed with the window."""
        for s in list(self.slots.values()) + self._graveyard:
            if s.parent() is None:
                s.hide()
                s.setParent(self)
        self.viz.timer.stop()

    def set_available(self, key: str, available: bool):
        """Hide items that can't work here (e.g. no Chromecast support)."""
        if available:
            self.unavailable.discard(key)
        else:
            self.unavailable.add(key)
        self._rebuild()

    def set_editing(self, on: bool):
        was = self.editing
        self.editing = on
        self.artist_info.set_menus(not on)
        self._rebuild()
        from musicwell.widgets import set_hand
        set_hand(self, on, skip=(SeekBar, QAbstractSlider))
        if was != on:
            self.editingChanged.emit(on)
        if not on:
            QTimer.singleShot(0, self._graveyard.clear)

    def _new_key(self, kind: str) -> str:
        n = 1
        while f"{kind}:{n}" in self.slots or f"{kind}:{n}" in self.all_placed():
            n += 1
        return f"{kind}:{n}"

    def place_item(self, key: str, zone: str, index: int | None):
        if zone not in ZONES:
            return
        if key.startswith("new:"):
            key = self._new_key(key.split(":")[1])
        elif key not in ITEMS and key.split(":")[0] not in SPACER_NAMES:
            return
        if key.startswith(("panel:", "top:")) and not self.make_item:
            return
        for z in ZONES:
            if key in self.zones[z]:
                old = self.zones[z].index(key)
                self.zones[z].remove(key)
                if z == zone and index is not None and old < index:
                    index -= 1
        keys = self.zones[zone]
        keys.insert(len(keys) if index is None else max(0, min(index, len(keys))), key)
        self._rebuild()
        self.layoutChanged.emit()

    def remove_item(self, key: str):
        for z in ZONES:
            if key in self.zones[z]:
                self.zones[z].remove(key)
        self._rebuild()
        self.layoutChanged.emit()

    def _balance_sides(self):
        """Keep the centre centred: both sides the same width."""
        lw, rw = self.zone_w["left"], self.zone_w["right"]
        for w in (lw, rw):
            w.setMinimumWidth(0)
        side = max(lw.sizeHint().width() if lw.isVisibleTo(self) else 0,
                   rw.sizeHint().width() if rw.isVisibleTo(self) else 0)
        center_used = bool(self.zones["center"] or self.zones["below"])
        if center_used and side:
            for w in (lw, rw):  # an empty side keeps its width
                if not w.isVisibleTo(self):
                    w.setVisible(True)
        for w in (lw, rw):
            own = w.sizeHint().width() if w.isVisibleTo(self) else 0
            w.setMinimumWidth(max(own, min(side, 420)) if center_used else own)

    def set_bar_height(self, h, save: bool = True):
        """Bottom panel height (None = natural). Never smaller than its contents."""
        if h is None:
            self.bar_height = None
            self.setMinimumHeight(0)
        else:
            natural = self.main.sizeHint().height() + (self.tray.sizeHint().height() if self.tray.isVisible() else 0)
            self.bar_height = max(natural, min(600, int(h)))
            if self.bar_height <= natural + 1:
                self.bar_height = None
            self.setMinimumHeight(self.bar_height or 0)
        if save:
            self.layoutChanged.emit()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_height_grip()

    def _place_height_grip(self):
        if not hasattr(self, "height_grip"):
            return
        g = 6
        top = self.options.get("position") != "top"
        self.height_grip.setGeometry(0, 0 if top else self.height() - g, self.width(), g)
        self.height_grip.raise_()

    VIZ_SIZE = (150, 36)
    INFO_SIZE = (340, 64)

    def set_item_size(self, key: str, w, h, save: bool = True):
        """Width and height for a resizable item."""
        if key == "viz":
            self.set_viz_size(w, h, save)
            return
        if key == "cover":  # square: the larger of the two
            if w is None:
                self.cover_size = None
                side = SIZES[self.options["icon_size"]][3]
            else:
                side = max(28, min(400, max(int(w), int(h if h is not None else w))))
                self.cover_size = side
            self.thumb.setFixedSize(side, side)
            if getattr(self, "_track", None) is not None:
                self._paint_thumb()
            s = self.slots.get(key)
            if s is not None:
                s.updateGeometry()
                s._place_handle()
                s.overlay.update()
            if hasattr(self, "zone_w"):
                self._balance_sides()
            if save:
                self.layoutChanged.emit()
            return
        if key.startswith("panel:"):
            if w is None:
                self.item_sizes.pop(key, None)
            else:
                self.item_sizes[key] = [int(w), int(h if h is not None else w)]
            s = self.slots.get(key)
            if s is not None:
                s.widget.set_size(*self.item_sizes.get(key, (None, None)))
                s.updateGeometry()
                s._place_handle()
                s.overlay.update()
            self._balance_sides()
            if save:
                self.layoutChanged.emit()
            return
        if key != "artist_info":
            return
        if w is None or h is None:
            self.info_size = None
            w, h = self.INFO_SIZE
        else:
            w, h = max(160, min(1400, w)), max(40, min(400, h))
            self.info_size = [w, h]
        self.artist_info.setFixedSize(w, h)
        s = self.slots.get(key)
        if s is not None:
            s.updateGeometry()
            s._place_handle()
            s.overlay.update()
        self._balance_sides()
        if save:
            self.layoutChanged.emit()

    def set_viz_size(self, w: int | None, h: int | None, save: bool = True):
        """Visualizer size (None = natural)."""
        if w is None or h is None:
            self.viz_size = None
            w, h = self.VIZ_SIZE
        else:
            w, h = max(40, min(3000, w)), max(14, min(140, h))
            self.viz_size = [w, h]
        if self.viz_fill:
            self.viz.setMinimumSize(40, h)
            self.viz.setMaximumSize(16777215, h)
        else:
            self.viz.setFixedSize(w, h)
        s = self.slots.get("viz")
        if s is not None:
            s.setSizePolicy(QSizePolicy.Expanding if self.viz_fill else QSizePolicy.Fixed, QSizePolicy.Preferred)
            s.updateGeometry()
            s._place_handle()
            s.overlay.update()
        if hasattr(self, "zone_w"):
            self._balance_sides()
        if save:
            self.layoutChanged.emit()

    def set_viz_fill(self, on: bool, save: bool = True):
        """Stretch the visualizer across its row (the whole window in the full-width row)."""
        self.viz_fill = on
        vs = self.viz_size
        self.set_viz_size(vs[0] if vs else None, vs[1] if vs else None, save=False)
        self._rebuild()
        if save:
            self.layoutChanged.emit()

    def set_gap(self, key: str, width: int):
        s = self.slots.get(key)
        if s is None:
            return
        s.widget.set_gap(width)
        self.gaps[key] = s.widget.gap
        self._rebuild()
        self.layoutChanged.emit()

    def _start_drag(self, key: str, source: QWidget):
        """Pick an item up; drop it on an area of the bar, or anywhere else to remove it."""
        from musicwell.widgets import MoveSession, drag_label
        self._dragging_item = True
        self._show_empty_zones(True)
        panels = _panels(self) if panel_key(key) else []  # looked up once, not on every mouse move

        top_line = getattr(self.window(), "show_top_drop", None)

        def move(g):
            self.show_drop_at(g)
            if top_line:
                top_line(g)
            if panels:  # it can go into a panel too
                for p in panels:
                    p._hide_indicator()
                panel = next((p for p in panels if p.rect().contains(p.mapFromGlobal(g))), None)
                if panel is not None:
                    panel._show_indicator(panel.body.mapFromGlobal(g))

        def finish():
            self._dragging_item = False
            self.show_drop_at(None)
            if top_line:
                top_line(None)
            for p in panels:
                p._hide_indicator()

        def drop(g):
            z = self.zone_at(g)
            index = self.zone_w[z].drop_index(self.zone_w[z].mapFromGlobal(g).x()) if z else None
            panel = _panel_at(self, g) if panel_key(key) and not z else None
            finish()
            if z:
                self.place_item(key, z, index)
            elif panel is not None:
                panel._drop(panel_key(key), panel.body.mapFromGlobal(g))
                self.remove_item(key)
                self._show_empty_zones(False)
            elif self.drop_on_top and (moved := self.drop_on_top(key, g)) is not False:
                if moved:
                    self.remove_item(key)
                self._show_empty_zones(False)
            elif not self.rect().contains(self.mapFromGlobal(g)) and key in self.all_placed():
                name = item_name(key)
                self.remove_item(key)  # dropped outside the bar: remove it
                self.itemRemoved.emit(name)
            else:
                self._show_empty_zones(False)

        MoveSession(self, drag_label(item_name(key), self.theme, source.grab()), move, drop,
                    lambda: (finish(), self._show_empty_zones(False)), self.theme)

    def control(self, key: str):
        """The bar's own widget for a button or slider that panels can hold a copy of."""
        return {"shuffle": self.shuffle, "prev": self.prev, "back10": self.back10, "play": self.play,
                "stop": self.stop_btn, "fwd10": self.fwd10, "next": self.next, "repeat": self.repeat,
                "stopafter": self.stop_after, "lyrics": self.lyrics_btn, "locate": self.locate_btn,
                "refresh": self.refresh_btn, "cast": self.cast_btn, "eq": self.eq_btn,
                "queue": self.queue_btn, "panel": self.panel_btn, "mute": self.vol_btn}.get(key)

    def make_copy(self, key: str):
        """A working copy of a play bar item for a panel: it shows the same state and does the same thing."""
        if key == "buttons":
            w = QWidget()
            lay = QHBoxLayout(w)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(6)
            for k in PLAY_BUTTONS:
                lay.addWidget(_CopyButton(self.control(k)))
            return w
        if self.control(key) is not None:
            return _CopyButton(self.control(key))
        if key == "seek":
            return _CopySeek(self)
        if key == "volume":
            return _CopyVolume(self.volume)
        if key == "time":
            return _CopyLabel(self.time_label)
        if key == "copy":
            return _CopyPill(self)
        if key == "info":
            return _CopyInfo(self.info)
        return None

    def zone_at(self, g):
        """The bar's area under a global point, or None."""
        for z in ZONES:
            zw = self.zone_w[z]
            if zw.isVisible() and zw.rect().adjusted(-4, -6, 4, 6).contains(zw.mapFromGlobal(g)):
                return z
        return None

    def show_drop_at(self, g):
        """Show where an item would land (None hides it)."""
        z = self.zone_at(g) if g is not None else None
        for name, zw in self.zone_w.items():
            x = zw._indicator_at(zw.mapFromGlobal(g).x()) if name == z else None
            if x != zw._indicator_x:
                zw._indicator_x = x
                zw.update()

    def drop_from_panel(self, key: str, g) -> bool:
        """A panel item dropped on the bar (only items that exist in both)."""
        z = self.zone_at(g)
        if not bar_key(key) or not z:
            return False
        self.place_item(bar_key(key), z, self.zone_w[z].drop_index(self.zone_w[z].mapFromGlobal(g).x()))
        return True

    def _show_empty_zones(self, on: bool):
        """Show empty areas while dragging (or always, with outlines on)."""
        show = on or (self.editing and self.outlines)
        for z, zw in self.zone_w.items():
            if not [k for k in self.zones[z] if k not in self.unavailable]:
                zw.setVisible(self.editing and show)
                zw.setMinimumHeight(30 if (self.editing and show) else 0)
                zw.update()

    # Unlocked: drag the background to move the bar to the top or bottom.
    def mousePressEvent(self, e):
        if self.editing and e.button() == Qt.LeftButton and not self._item_at(e.globalPosition().toPoint()):
            self._bar_press = e.globalPosition().toPoint()
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        press = getattr(self, "_bar_press", None)
        if press is not None and e.buttons() & Qt.LeftButton and \
                (e.globalPosition().toPoint() - press).manhattanLength() > QApplication.startDragDistance() + 3:
            self._bar_press = None
            self._move_bar()
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._bar_press = None
        super().mouseReleaseEvent(e)

    def _move_bar(self):
        from musicwell.widgets import MoveSession, drag_label
        win = self.window()
        session = None

        def target(g):
            return "top" if win.mapFromGlobal(g).y() < win.height() / 2 else "bottom"

        def move(g):
            if session is None:
                return
            h = max(60, self.height())
            r = win.rect()
            session.hint = r.adjusted(0, 0, 0, -(r.height() - h)) if target(g) == "top" else \
                r.adjusted(0, r.height() - h, 0, 0)

        def drop(g):
            self.set_option("position", target(g))

        session = MoveSession(self, drag_label("Play bar — top or bottom", self.theme), move, drop, None, self.theme)
        move(self.cursor().pos())
        session.update()

    def set_option(self, name: str, value: str):
        if name in OPTION_CHOICES and value in dict(OPTION_CHOICES[name][1]):
            self.options[name] = value
            self._rebuild()
            self.layoutChanged.emit()
            if name == "cover_style":
                self.coverStyleChanged.emit(value)

    def fill_options_menu(self, menu: QMenu):
        menu.clear()
        for name, (title, choices) in OPTION_CHOICES.items():
            sub = menu.addMenu(title)
            for value, label in choices:
                a = sub.addAction(label, lambda n=name, v=value: self.set_option(n, v))
                a.setCheckable(True)
                a.setChecked(self.options[name] == value)

    def contextMenuEvent(self, e):
        """Unlocked: item options, Add here, the bar's look and Reset. Locked: Unlock."""
        m = QMenu(self)
        under = self._item_at(e.globalPos())
        if self.editing:
            if under:
                if under.startswith("gap:"):
                    m.addAction("Wider", lambda: self.set_gap(under, self.gaps.get(under, 16) + 8))
                    m.addAction("Narrower", lambda: self.set_gap(under, self.gaps.get(under, 16) - 8))
                if under in TEXT_ITEMS:
                    self._add_text_size(m, under)
                if under == "viz":
                    a = m.addAction("Fill the width", lambda: self.set_viz_fill(not self.viz_fill))
                    a.setCheckable(True)
                    a.setChecked(self.viz_fill)
                m.addAction(f"Remove “{item_name(under)}”", lambda k=under: self.remove_item(k))
            zone, index = self._zone_at(e.globalPos())
            add = m.addMenu("Add here")
            free = self.unused()
            for k in free:
                if not k.startswith(("panel:", "top:")):
                    add.addAction(item_name(k), lambda k=k: self.place_item(k, zone, index))
            for prefix, title in (("panel:", "From the panels"), ("top:", "From the top bar")):
                if any(k.startswith(prefix) for k in free) and self.make_item:
                    sub = add.addMenu(title)
                    for k in free:
                        if k.startswith(prefix):
                            sub.addAction(item_name(k), lambda k=k: self.place_item(k, zone, index))
            if not free:
                a = add.addAction("Everything is in the bar")
                a.setEnabled(False)
            add.addSeparator()
            add.addAction("Flexible space", lambda: self.place_item("new:stretch", zone, index))
            add.addAction("Gap", lambda: self.place_item("new:gap", zone, index))
            m.addSeparator()
            look = m.addMenu("The play bar's look")
            self.fill_options_submenus(look)
            from musicwell.record import speed_menu
            speed_menu(look.addMenu("Record speed"))
            look.addSeparator()
            look.addAction("Reset the play bar", self.reset_layout)
            m.addSeparator()
            if self.panels_menu:
                self.panels_menu(m)
                m.addSeparator()
            m.addAction("🔒  Lock (nothing moves)", lambda: self.lockRequested.emit(True))
        else:
            if under in TEXT_ITEMS:
                w = self._text_widget(under)
                if isinstance(w, QLabel):
                    copy_action(m, w)
                self._add_text_size(m, under)
                m.addSeparator()
            if self.panels_menu:
                self.panels_menu(m)
                m.addSeparator()
            m.addAction("🔓  Unlock to edit", lambda: self.lockRequested.emit(False))
        m.exec(e.globalPos())

    panels_menu = None  # callable(menu) adding the Panels submenu

    def _text_widget(self, key: str):
        w = self.slots[key].widget if key in self.slots else self.widgets.get(key)
        return w.content if key.startswith("panel:") else w

    def _add_text_size(self, m: QMenu, key: str):
        text_size_menu(m.addMenu("Text size"), self.text_sizes.get(key, 1.0), lambda sc: self.set_text_size(key, sc))

    def set_text_size(self, key: str, scale: float, save: bool = True):
        if scale == 1:
            self.text_sizes.pop(key, None)
        else:
            self.text_sizes[key] = scale
        if key in self.slots:
            scale_text(self._text_widget(key), scale)
            self.slots[key].updateGeometry()
        if save:
            self.layoutChanged.emit()

    def apply_text_sizes(self):
        for k in TEXT_ITEMS:
            if k in self.slots:
                scale_text(self._text_widget(k), self.text_sizes.get(k, 1.0))

    def _zone_at(self, gpos) -> tuple[str, int | None]:
        """Area and position under the mouse (for Add here), else the right-hand area."""
        for z in ZONES:
            zw = self.zone_w[z]
            if zw.isVisible() and zw.rect().contains(zw.mapFromGlobal(gpos)):
                return z, zw.drop_index(zw.mapFromGlobal(gpos).x())
        return "right", None

    def fill_options_submenus(self, m: QMenu):
        for name, (title, choices) in OPTION_CHOICES.items():
            sub = m.addMenu(title)
            for value, label in choices:
                a = sub.addAction(label, lambda n=name, v=value: self.set_option(n, v))
                a.setCheckable(True)
                a.setChecked(self.options[name] == value)

    def _item_at(self, gpos) -> str | None:
        for k in self.all_placed():
            s = self.slots.get(k)
            if s is not None and s.isVisible() and s.rect().contains(s.mapFromGlobal(gpos)):
                return k
        return None

    def _apply_seek_look(self):
        o = self.options
        self.seek.set_look(o["seek_style"], o["seek_handle"])
        self.volume.set_look(o["seek_style"], o["seek_handle"])
        times = o["seek_times"]
        self.elapsed.setVisible(times != "none")
        self.total.setVisible(times in ("both", "remaining"))
        self.seek.setFixedHeight(SEEK_HEIGHT.get(o["seek_style"], 18))
        self.volume.setFixedHeight(18 if o["seek_style"] not in WAVE_STYLES else 20)
        if o["seek_style"] in WAVE_STYLES and self.seek.wave is None and self._track is not None:
            self.seek.wave_loading = True
            self.waveformWanted.emit(self._track)

    def apply_theme(self, theme: th.Theme, playing: bool, repeat_mode: int, muted: bool, volume: float):
        self.theme = theme
        self._playing, self._repeat, self._muted, self._volume = playing, repeat_mode, muted, volume
        for w in (self.seek, self.volume, self.viz, self.stars):
            w.theme = theme
        self.stars.refresh_theme()
        self.artist_info.theme = theme
        self.artist_info.refresh_theme()
        self.seek.update()
        self.volume.update()
        o = self.options
        small, big, play_box, _cover = SIZES[o["icon_size"]]
        style = o["icon_style"]
        buttons = {
            self.prev: big, self.next: big, self.back10: big, self.fwd10: big, self.stop_btn: big - 2,
            self.shuffle: small, self.repeat: small, self.stop_after: small, self.lyrics_btn: small,
            self.locate_btn: small, self.refresh_btn: small, self.like_btn: small, self.cast_btn: small,
            self.eq_btn: small, self.queue_btn: small,
            self.panel_btn: small, self.vol_btn: small,
        }
        for b, px in buttons.items():
            b.icon_style = style
            b.set_icon_px(px)
        for b in (self.prev, self.next, self.queue_btn, self.back10, self.fwd10, self.stop_btn, self.locate_btn,
                  self.refresh_btn):
            b.apply(theme)
        self.shuffle.apply(theme, color_key="accent" if self.shuffle.isChecked() else "muted")
        self.repeat.apply(theme, "repeat1" if repeat_mode == 2 else "repeat",
                          "accent" if repeat_mode else "muted")
        self.stop_after.apply(theme, color_key="accent" if self.stop_after.isChecked() else "muted")
        self.eq_btn.apply(theme, color_key="accent" if self.eq_on else "muted")
        self.cast_btn.apply(theme, "cast_on" if self.cast_on else "cast",
                            "accent" if self.cast_on else "muted")
        self.lyrics_btn.apply(theme, color_key="accent" if self.lyrics_on else "muted")
        self.like_btn.apply(theme, "heart_full" if self.like_state else "heart_empty", "accent" if self.like_state else "muted")
        self.like_btn.setEnabled(self.like_state is not None)
        self.panel_btn.apply(theme, color_key="accent" if self.panel_on else "muted")
        vol_icon = "mute" if muted or volume == 0 else ("volume_low" if volume < 0.5 else "volume")
        self.vol_btn.apply(theme, vol_icon, "muted")
        # play button
        ps = o["play_style"]
        self.play.icon_style = style if ps == "plain" else "filled"
        name = "pause" if playing else "play"
        r = play_box // 2
        acc = theme.accent.name()
        if ps == "circle":
            self.play.set_icon_px(big)
            self.play.setFixedSize(play_box, play_box)
            self.play.setIcon(th.icon(name, QColor(theme.accent_text()), big))
            self.play.setStyleSheet(f"#PlayButton {{ background: {acc}; border-radius: {r}px; border: none; }}"
                                    f"#PlayButton:hover {{ border: 2px solid {theme.p['text']}; }}")
        elif ps == "ring":
            self.play.set_icon_px(big)
            self.play.setFixedSize(play_box, play_box)
            self.play.setIcon(th.icon(name, theme.color("accent"), big, "filled"))
            self.play.setStyleSheet(f"#PlayButton {{ background: transparent; border-radius: {r}px;"
                                    f" border: 2px solid {acc}; }}"
                                    f"#PlayButton:hover {{ background: {theme.p['hover']}; }}")
        else:
            px = int(big * 1.35)
            self.play.set_icon_px(px)
            self.play.setFixedSize(px + 10, px + 10)
            self.play.setIcon(th.icon(name, theme.color("text"), px, style))
            self.play.setStyleSheet(f"#PlayButton {{ background: transparent; border: none; border-radius: 6px; }}"
                                    f"#PlayButton:hover {{ background: {theme.p['hover']}; }}")
        if self._track is not None:
            self._paint_thumb()

    def set_queue_tag(self, text: str, tip: str = ""):
        """Accent line over the title while a queued song plays."""
        self.info.set_tag(text)
        self.info.tag.setToolTip(tip)

    def set_track(self, t: dict | None, art):
        same = t is not None and self._track is not None and t["path"] == self._track["path"]
        self._track, self._art = t, art
        self.live = bool(t and t.get("stream"))
        self.seek.setEnabled(not self.live)
        self.stars.setEnabled(not self.live and not (t and t.get("remote")))
        if not same:
            wave = (t is not None and not self.live and not t.get("remote")
                    and self.options["seek_style"] in WAVE_STYLES)
            self.seek.set_waveform(None, loading=wave)
            if wave:
                self.waveformWanted.emit(t)
        if t is None:
            self.info.set_text("", "")
            self.thumb.clear()
            self.stars.set_rating(0)
            return
        self.info.set_text(t["title"], t["artist"] or (t["station"]["name"] if t.get("stream") else "Unknown Artist"))
        self.stars.set_rating(t.get("rating") or 0)
        self._paint_thumb()

    def _spin_thumb(self):
        if getattr(self, "_track", None) is not None and self.thumb.isVisible():
            self._paint_thumb()

    def _paint_thumb(self):
        t, art = self._track, self._art
        side = self.thumb.width()
        dpr = self.devicePixelRatioF()
        size = int(side * dpr)
        img = art if art is not None else placeholder(128, t["album"] or t["title"], self.theme.accent)
        if self.options.get("cover_style", "square") != "square":  # a small spinning record
            self.disc.set_image(img)
            pm = QPixmap(size, size)
            pm.fill(Qt.transparent)
            pm.setDevicePixelRatio(dpr)
            p = QPainter(pm)
            p.setRenderHint(QPainter.Antialiasing)
            self.disc.paint(p, QRectF(1, 1, side - 2, side - 2), self.spinner.angle, dpr, shadow=False)
            p.end()
            self.thumb.setPixmap(pm)
            return
        src = _cover_rect(img.width(), img.height(), side, side)
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, size, size), 6 * dpr, 6 * dpr)
        p.setClipPath(path)
        p.drawImage(QRectF(0, 0, size, size), img, src)
        p.end()
        pm.setDevicePixelRatio(dpr)
        self.thumb.setPixmap(pm)

    def set_waveform(self, path: str, data):
        """Use the waveform only if `path` is still the song in the bar."""
        if self._track is not None and self._track["path"] == path:
            self.seek.set_waveform(data, loading=False)

    def set_copy(self, shown: bool, tip: str = ""):
        """Show "▶ Your copy" when the radio plays a song you have."""
        if tip:
            self.copy_btn.setToolTip(tip + " — click to play your own copy")
        if shown != self.copy_shown:
            self.copy_shown = shown
            self.copyShown.emit(shown)
            s = self.slots.get("copy")
            if s is not None and "copy" in self.all_placed():
                self._rebuild()

    def set_like(self, state, where: str = "radio"):
        """None: nothing to like; False / True: not liked / liked."""
        self.like_state = state
        self.like_btn.apply(self.theme, "heart_full" if state else "heart_empty", "accent" if state else "muted")
        self.like_btn.setEnabled(state is not None)
        if where == "library":
            tip = ("In your Favourites — click to take it out" if state else
                   "♥ Add to your Favourites (5 stars) — Ctrl+Shift+L")
        else:
            tip = ("In ♥ Liked — click to take it out" if state else
                   "♥ Like this song (Radio → ♥ Liked) — Ctrl+Shift+L")
        self.like_btn.setToolTip(tip if state is not None else "♥ Like the playing song")

    def set_rating(self, r: int):
        self.stars.set_rating(r)

    def _toggle_remaining(self):
        cur = self.options["seek_times"]
        if cur in ("both", "remaining"):
            self.set_option("seek_times", "remaining" if cur == "both" else "both")

    def _on_seek_moved(self, v: int):
        self.elapsed.setText(fmt_time(v / 1000))
        self._set_total_text(v, self.seek.maximum())

    def _set_total_text(self, ms: int, duration: int):
        if self.options["seek_times"] == "remaining":
            self.total.setText("-" + fmt_time(max(0, duration - ms) / 1000))
        else:
            self.total.setText(fmt_time(duration / 1000))

    def set_position(self, ms: int, duration: int):
        self._last_ms, self._last_dur = ms, duration
        if getattr(self, "live", False):
            self.seek.setMaximum(1)
            self.seek.setValue(1)  # full line: live stream
            self.elapsed.setText(fmt_time(ms / 1000))
            self.total.setText("LIVE")
            self.time_label.setText(f"{fmt_time(ms / 1000)} · LIVE")
            return
        if not self.seek.isSliderDown():
            self.seek.setMaximum(max(0, duration))
            self.seek.setValue(ms)
            self.elapsed.setText(fmt_time(ms / 1000))
            self._set_total_text(ms, duration)
        self.time_label.setText(f"{fmt_time(ms / 1000)} / {fmt_time(duration / 1000)}")
