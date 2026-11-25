"""Shared widgets: panel pieces, column browser, song table and helpers."""
from __future__ import annotations

import json

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QLinearGradient, QPainter,
                           QPainterPath, QPixmap)
from PySide6.QtWidgets import (QApplication, QAbstractItemView, QFrame, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QPushButton,
                               QSizePolicy, QSplitter, QTableView, QToolButton, QVBoxLayout, QWidget)

from musicwell import theme as th
from musicwell.artwork import placeholder
from musicwell import fields as F
from musicwell.models import RatingDelegate, SongModel


class IconButton(QToolButton):
    looksChanged = Signal()  # icon, size or tooltip changed (copies of the button follow)

    def __init__(self, name: str, size: int = 20, tip: str = "", parent=None):
        super().__init__(parent)
        self.icon_name = name
        self.icon_px = size
        self.setIconSize(QSize(size, size))
        self.setToolTip(tip)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.color_key = "text"
        self.icon_style = "filled"

    def set_icon_px(self, px: int):
        self.icon_px = px
        self.setIconSize(QSize(px, px))
        self.looksChanged.emit()

    def setToolTip(self, tip: str):
        super().setToolTip(tip)
        self.looksChanged.emit()

    def setIcon(self, icon):
        super().setIcon(icon)
        self.looksChanged.emit()

    def setStyleSheet(self, css: str):
        super().setStyleSheet(css)
        self.looksChanged.emit()

    def setFixedSize(self, *size):
        super().setFixedSize(*size)
        self.looksChanged.emit()

    def apply(self, theme: th.Theme, name: str | None = None, color_key: str | None = None):
        if name:
            self.icon_name = name
        if color_key:
            self.color_key = color_key
        self.setIcon(th.icon(self.icon_name, theme.color(self.color_key), self.icon_px, self.icon_style))
        self.looksChanged.emit()


class StarRow(QWidget):
    rated = Signal(int)

    def __init__(self, theme: th.Theme, size: int = 16, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.size_px = size
        self.rating = 0
        self._hover = -1
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(5 * (size + 4), size + 4)
        self._pm = {}

    def refresh_theme(self):
        self._pm = {}
        self.update()

    def _pix(self, kind, color_key):
        k = (kind, color_key)
        if k not in self._pm:
            self._pm[k] = QPixmap.fromImage(th.svg_image(kind, self.theme.color(color_key), self.size_px))
        return self._pm[k]

    def set_rating(self, r: int):
        self.rating = r or 0
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        shown = self._hover + 1 if self._hover >= 0 else self.rating
        for i in range(5):
            if i < shown:
                pm = self._pix("star", "accent")
            else:
                pm = self._pix("star_empty", "faint")
            p.drawPixmap(i * (self.size_px + 4), 2, pm)

    def mouseMoveEvent(self, e):
        self._hover = min(4, int(e.position().x() // (self.size_px + 4)))
        self.update()

    def leaveEvent(self, _):
        self._hover = -1
        self.update()

    def mouseReleaseEvent(self, e):
        star = min(4, int(e.position().x() // (self.size_px + 4))) + 1
        self.rated.emit(0 if star == self.rating else star)


class SearchBox(QLineEdit):
    def __init__(self, theme: th.Theme, parent=None):
        super().__init__(parent)
        self.setObjectName("SearchBox")
        self.setPlaceholderText("Search  —  try  artist=bowie   year>1990   #(plays = 0)   !live")
        self.setClearButtonEnabled(True)
        self.setMinimumWidth(190)  # shrinks when there are many tabs
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.theme = theme

    def sizeHint(self):
        h = super().sizeHint()
        return QSize(320, h.height())

    def contextMenuEvent(self, e):
        m = self.createStandardContextMenu()
        add_menu_extras(self, m)
        m.exec(e.globalPos())

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        img = th.svg_image("search", self.theme.color("muted"), 16)
        p.drawImage(QPointF(11, (self.height() - 16) / 2), img)


TEXT_SIZES = [("Smallest", 0.7), ("Smaller", 0.85), ("Normal", 1.0), ("Larger", 1.2), ("Larger still", 1.45),
              ("Largest", 1.75)]
_SIZED = "/*text size*/"


def scale_text(root: QWidget, scale: float):
    """Make the text in a widget bigger or smaller than the theme has it."""
    if hasattr(root, "set_text_scale"):
        root.set_text_scale(scale)
        return
    # not its menus (they are its children while open, and after)
    widgets = [root] + [w for w in root.findChildren(QWidget) if not w.isWindow()]
    for w in widgets:  # back to the theme's size first
        sheet = w.styleSheet()
        if _SIZED in sheet:
            w.setStyleSheet(w.property("ownStyle") or "")
        elif scale != 1:
            w.setProperty("ownStyle", sheet)
        if scale == 1 and hasattr(w, "set_text_scale"):
            w.set_text_scale(1.0)
    if scale == 1:
        return
    sizes = []
    for w in widgets:
        w.ensurePolished()
        f = w.font()
        sizes.append((w, f.pointSizeF(), f.pixelSize()))
    for w, pt, px in sizes:
        if hasattr(w, "set_text_scale"):
            w.set_text_scale(scale)
            continue
        size = f"{pt * scale:.1f}pt" if pt > 0 else f"{max(6, round(px * scale))}px"
        own = w.property("ownStyle") or ""
        if own.strip() and "{" not in own:
            own = f"* {{ {own} }}"
        # only the widget itself: its right-click menus keep the normal size
        w.setProperty("textSized", True)
        w.setStyleSheet(f'{own}\n[textSized="true"] {{ font-size: {size}; }}' + _SIZED)


def add_menu_extras(widget, menu):
    """Options a panel or the play bar adds to an item's own right-click menu (Text size)."""
    w = widget
    while w is not None:
        extra = getattr(w, "menu_extras", None)
        if extra:
            menu.addSeparator()
            extra(menu)
            return
        w = w.parentWidget()


def copy_action(menu, label):
    """Copy for a text item whose right-click goes to the panel's menu."""
    from PySide6.QtGui import QTextDocumentFragment
    text = label.selectedText() or QTextDocumentFragment.fromHtml(label.text()).toPlainText()
    if text.strip():
        menu.addAction("Copy", lambda: QApplication.clipboard().setText(text))


def text_size_menu(menu, current: float, apply):
    """Text size choices; apply(scale) is called with the one picked."""
    for label, scale in TEXT_SIZES:
        a = menu.addAction(label, lambda s=scale: QTimer.singleShot(0, lambda: apply(s)))  # once the menu has closed
        a.setCheckable(True)
        a.setChecked(abs(current - scale) < 0.01)


def mirrored(fn):
    """Repeat the call on each of the object's `mirrors` (keeps the second side panel in step)."""
    def wrap(self, *a, **k):
        r = fn(self, *a, **k)
        mirrors = getattr(self, "mirrors", None)
        if mirrors is not None:
            self.__dict__.setdefault("last_calls", {})[fn.__name__] = (a, k)  # for a mirror added later
            for m in mirrors:
                getattr(m, fn.__name__)(*a, **k)
        return r
    wrap.__name__ = fn.__name__
    wrap.__doc__ = fn.__doc__
    return wrap


def _cover_rect(img_w, img_h, w, h, top_bias=0.5) -> QRectF:
    """Source rect that fills (w, h) without distortion."""
    s = max(w / img_w, h / img_h)
    sw, sh = w / s, h / s
    return QRectF((img_w - sw) / 2, (img_h - sh) * top_bias, sw, sh)


class Backdrop(QWidget):
    """Window background: the playing song's artwork, blurred."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Backdrop")
        self._img = None
        self._blur = None
        self._cache = None

    def set_image(self, img):
        img = img if (img is not None and not img.isNull()) else None
        if img is self._img:
            return
        self._img = img
        self._blur = None
        self._cache = None
        if img is not None:
            # strong blur: shrink to a few pixels, then let smooth scaling spread it
            small = img.scaled(18, 18, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            mid = small.scaled(small.width() * 4, small.height() * 4, Qt.IgnoreAspectRatio,
                               Qt.SmoothTransformation)
            self._blur = mid.scaled(mid.width() * 4, mid.height() * 4, Qt.IgnoreAspectRatio,
                                    Qt.SmoothTransformation)
        self.update()

    def resizeEvent(self, e):
        self._cache = None
        super().resizeEvent(e)

    def paintEvent(self, _):
        if self._blur is None:
            return
        if self._cache is None or self._cache.size() != self.size():
            w, h = max(1, self.width()), max(1, self.height())
            pm = QPixmap(w, h)
            p = QPainter(pm)
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            p.drawImage(QRectF(0, 0, w, h), self._blur, _cover_rect(self._blur.width(), self._blur.height(), w, h))
            p.end()
            self._cache = pm
        QPainter(self).drawPixmap(0, 0, self._cache)


class _RefreshButton(QToolButton):
    """Small round button shown over an image on hover."""

    def __init__(self, owner: QWidget, tip: str):
        super().__init__(owner)
        self.setToolTip(tip)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedSize(30, 30)
        self.setIconSize(QSize(16, 16))
        self.setStyleSheet("QToolButton { background: rgba(0,0,0,150); border-radius: 15px; border: none; }"
                           "QToolButton:hover { background: rgba(0,0,0,215); }")
        self.setIcon(th.icon("refresh", QColor("#ffffff"), 16))
        self.hide()


class _HoverRefresh:
    """Mixin: show the refresh button on hover."""
    def enterEvent(self, e):
        self.refresh_btn.show()
        self.refresh_btn.raise_()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.refresh_btn.hide()
        super().leaveEvent(e)


class _CreditLabel(QLabel):
    """Photographer and licence in the corner of a free photo; click to open its page."""

    def __init__(self, owner: QWidget):
        super().__init__(owner)
        self.page = ""
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("QLabel { background: rgba(0,0,0,140); color: rgba(255,255,255,225); "
                           "border-radius: 4px; padding: 1px 6px; font-size: 10px; }")
        self.hide()

    def set_info(self, info: dict | None):
        info = info or {}
        self.page = info.get("page", "")
        if info.get("license"):
            who = info.get("credit") or "Wikimedia Commons"
            self.setText(f"Photo: {who} · {info['license']}")
            self.setToolTip(f"Photo: {who}\nLicence: {info['license']}\nFrom Wikimedia Commons"
                            + ("\nClick to open the photo's page" if self.page else ""))
        else:
            self.setText("")
            self.setToolTip("")

    def has_text(self) -> bool:
        return bool(self.text())

    def mousePressEvent(self, e):
        if self.page and e.button() == Qt.LeftButton:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl(self.page))
            e.accept()
            return
        super().mousePressEvent(e)


class ArtistHeader(_HoverRefresh, QWidget):
    """Large artist photo that fades into the panel, with the name on top."""
    refreshRequested = Signal()

    def __init__(self, theme: th.Theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.name = ""
        self.img = None
        self._scaled: QPixmap | None = None
        self.fit = "whole"  # "whole" = full photo, "fill" = crop to a banner
        self.custom_height = None  # height set in the panel (None = from the photo's shape)
        self.text_scale = 1.0
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.refresh_btn = _RefreshButton(self, "Reload the artist photo and album cover (Ctrl+F5)")
        self.refresh_btn.clicked.connect(self.refreshRequested)
        self.credit_for = None  # callable: artist -> {"credit", "license", "page"} or None
        self.credit = _CreditLabel(self)

    @mirrored
    def set_artist(self, name: str, img):
        self.name = name
        self.img = img if (img is not None and not img.isNull()) else None
        self._scaled = None
        info = self.credit_for(name) if (self.credit_for and self.img is not None) else None
        self.credit.set_info(info)
        self.credit.adjustSize()
        self._place_credit()
        self.credit.setVisible(self.credit.has_text() and self.underMouse())
        self._fit_height()
        self.update()

    @mirrored
    def set_fit(self, fit: str):
        self.fit = fit if fit in ("whole", "fill") else "whole"
        self._scaled = None
        self._fit_height()
        self.update()

    def height_for(self, w: int) -> int:
        """Photo height for this width."""
        w = max(1, w)
        banner = max(170, min(int(w * 0.66), 280))
        if self.fit == "fill" or self.img is None:
            return banner
        return self._photo_height(w) + self.NAME_STRIP

    NAME_STRIP = 66  # in "whole" mode the name sits below the photo

    def _photo_height(self, w: int) -> int:
        """Full photo at the panel's width; very tall ones are capped over a blurred copy."""
        aspect = self.img.width() / max(1, self.img.height())
        return int(max(90, min(w / aspect, w * 1.4)))

    @mirrored
    def _fit_height(self):
        if self.custom_height:
            return
        if self.width() > 1:
            h = self.height_for(self.width())
            if h != self.height():
                self.setFixedHeight(h)

    @mirrored
    def refresh_theme(self):
        self._scaled = None
        self.update()

    def resizeEvent(self, e):
        self._scaled = None
        self.refresh_btn.move(self.width() - self.refresh_btn.width() - 10, 10)
        self._place_credit()
        super().resizeEvent(e)

    def _place_credit(self):
        c = self.credit
        c.setMaximumWidth(max(60, self.width() - 16))
        c.adjustSize()
        bottom = self.height() - (self.NAME_STRIP if (self.img is not None and self.fit == "whole") else 0)
        c.move(self.width() - c.width() - 8, max(4, bottom - c.height() - 22))

    def enterEvent(self, e):
        if self.credit.has_text():
            self._place_credit()
            self.credit.show()
            self.credit.raise_()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.credit.hide()
        super().leaveEvent(e)

    def _render(self) -> QPixmap:
        """The photo on a transparent background, fading out at the bottom."""
        w, h = max(1, self.width()), max(1, self.height())
        dpr = self.devicePixelRatioF()
        pm = QPixmap(int(w * dpr), int(h * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.transparent)
        panel = self.theme.color("panel")
        p = QPainter(pm)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setRenderHint(QPainter.Antialiasing)
        if self.img is not None and self.fit == "whole":
            ph = max(40, h - self.NAME_STRIP)
            s = min(w / self.img.width(), ph / self.img.height())
            dw, dh = self.img.width() * s, self.img.height() * s
            if dw < w - 1 or dh < ph - 1:
                # very tall or wide photo: blurred copy fills the space around it
                tiny = self.img.scaled(24, 24, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                p.drawImage(QRectF(0, 0, w, ph), tiny, _cover_rect(tiny.width(), tiny.height(), w, ph))
                veil = QColor(panel)
                veil.setAlpha(110)
                p.fillRect(QRectF(0, 0, w, ph), veil)
            p.drawImage(QRectF((w - dw) / 2, (ph - dh) / 2, dw, dh), self.img)
            # only the last few pixels fade
            fade_from, fade_to = ph - 18, ph
            keep = 255
        else:
            if self.img is not None:
                src = _cover_rect(self.img.width(), self.img.height(), w, h, top_bias=0.22)
                p.drawImage(QRectF(0, 0, w, h), self.img, src)
            else:
                ph_img = placeholder(256, self.name or "?", self.theme.accent)
                p.drawImage(QRectF(0, 0, w, h), ph_img, _cover_rect(256, 256, w, h))
            fade_from, fade_to = h * 0.30, h
            keep = 20
        p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        g = QLinearGradient(0, fade_from, 0, fade_to)
        g.setColorAt(0, QColor(0, 0, 0, 255))
        if keep < 255:
            g.setColorAt(0.72, QColor(0, 0, 0, keep))
        g.setColorAt(1, QColor(0, 0, 0, 0))
        p.fillRect(QRectF(0, fade_from, w, h - fade_from), g)
        p.end()
        return pm

    def paintEvent(self, _):
        if self._scaled is None:
            self._scaled = self._render()
        p = QPainter(self)
        p.drawPixmap(0, 0, self._scaled)
        w, h, s = self.width(), self.height(), self.text_scale
        small = QFont(self.font())
        small.setPointSizeF(8 * s)
        small.setBold(True)
        small.setLetterSpacing(QFont.AbsoluteSpacing, 1.2)
        p.setFont(small)
        p.setPen(self.theme.color("muted"))
        ha = {"center": Qt.AlignHCenter, "right": Qt.AlignRight}.get(getattr(self, "align", "left"), Qt.AlignLeft)
        p.drawText(QRectF(20, h - 12 - 50 * s, w - 40, 16 * s), ha | Qt.AlignVCenter, "ARTIST")
        big = QFont(self.font())
        big.setPointSizeF(19 * s)
        big.setBold(True)
        p.setFont(big)
        p.setPen(self.theme.color("text"))
        text = QFontMetrics(big).elidedText(self.name or "Nothing playing", Qt.ElideRight, w - 40)
        p.drawText(QRectF(20, h - 12 - 34 * s, w - 40, 34 * s), ha | Qt.AlignVCenter, text)

    def set_text_scale(self, scale: float):
        self.text_scale = scale
        self.update()

    def set_alignment(self, align: str):
        self.align = align
        self.update()


class ArtView(_HoverRefresh, QWidget):
    """Album cover with rounded corners and a shadow, or a spinning record."""
    refreshRequested = Signal()

    def __init__(self, theme: th.Theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.img = None
        self.label = ""
        from musicwell.record import Disc, Spinner
        self.style = "square"  # square / record / picture
        self.align = "center"  # left / center / right
        self.disc = Disc()
        self.spinner = Spinner(self)
        self.spinner.changed.connect(self.update)
        self.refresh_btn = _RefreshButton(self, "Reload the album cover and artist photo (Ctrl+F5)")
        self.refresh_btn.clicked.connect(self.refreshRequested)

    def _square_x(self, side: float) -> float:
        if self.align == "left":
            return 1.0
        if self.align == "right":
            return self.width() - side - 1.0
        return (self.width() - side) / 2

    def set_alignment(self, align: str):
        self.align = align if align in ("left", "center", "right") else "center"
        self.resizeEvent(None)
        self.update()

    def resizeEvent(self, e):
        side = min(self.width(), self.height()) - 12
        x = self._square_x(side)
        y = max(2.0, (self.height() - 12 - side) / 2 + 2)
        self.refresh_btn.move(int(x + side - self.refresh_btn.width() - 8), int(y + 8))
        if e is not None:
            super().resizeEvent(e)

    @mirrored
    def set_image(self, img, label: str = ""):
        self.img = img if (img is not None and not img.isNull()) else None
        self.label = label
        self.disc.set_image(self.img if self.img is not None else placeholder(256, label or "♪", self.theme.accent))
        self.update()

    def set_style(self, style: str):
        """square: the cover; record: spinning vinyl with the cover as label; picture: spinning picture disc."""
        from musicwell.record import STYLE_KEYS
        self.style = style if style in STYLE_KEYS else "square"
        self.disc.set_style(self.style)
        self.spinner.set_active(self.style != "square" and self.isVisible())
        self.update()

    def set_playing(self, playing: bool):
        self.spinner.set_playing(playing)

    def showEvent(self, e):
        super().showEvent(e)
        self.spinner.set_active(self.style != "square")

    def hideEvent(self, e):
        super().hideEvent(e)
        self.spinner.set_active(False)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        side = min(self.width(), self.height()) - 12
        x = self._square_x(side)
        y = max(2.0, (self.height() - 12 - side) / 2 + 2)  # centred when given extra height
        rect = QRectF(x, y, side, side)
        if self.style != "square":
            if self.disc.img is None:
                self.disc.set_image(placeholder(256, self.label or "♪", self.theme.accent))
            self.disc.paint(p, rect, self.spinner.angle, self.devicePixelRatioF())
            return
        for i in range(8, 0, -1):  # cheap shadow
            sh = QPainterPath()
            sh.addRoundedRect(rect.adjusted(-i * 0.6, i * 0.5, i * 0.6, i * 0.9), 10 + i, 10 + i)
            p.fillPath(sh, QColor(0, 0, 0, 7))
        path = QPainterPath()
        path.addRoundedRect(rect, 10, 10)
        p.setClipPath(path)
        if self.img is not None:
            p.drawImage(rect, self.img, _cover_rect(self.img.width(), self.img.height(), side, side))
        else:
            p.drawImage(rect, placeholder(256, self.label or "♪", self.theme.accent))


class _PaneFields:
    """Browsable fields as {key: (name, plural, label for empty values)}."""

    def _fields(self):
        return {f.key: f for f in F.browsable()}

    def __contains__(self, key):
        return key in self._fields()

    def __getitem__(self, key):
        f = self._fields()[key]
        unknown = {"rating": "Unrated", "decade": "Unknown Decade", "year": "Unknown Year"}.get(
            key, f"Unknown {f.name}" if f.group == "Basic" else f"No {f.name}")
        return (f.name, f.plural_name, unknown)

    def keys(self):
        return list(self._fields())

    def items(self):
        return [(k, self[k]) for k in self.keys()]

    def __iter__(self):
        return iter(self.keys())


PANE_FIELDS = _PaneFields()


def field_value(key: str):
    f = F.get(key)
    if key == "album" and f is not None:  # one Album entry for every disc
        from musicwell.tags import album_title
        return lambda t, g=f.get: album_title(g(t) or "")
    if f is None:
        return lambda t: t.get(key, "")
    if f.kind == "num":  # group by the text as written ("-7.42 dB")
        return f.display
    return f.get


NUMERIC_FIELDS = {"year", "decade", "rating", "bpm", "bitdepth", "samplerate"}
MAX_PANES = 6

PANE_PRESETS = {
    "Genre | Album artist | Album": ["genre", "artist_key", "album"],
    "Album artist | Album": ["artist_key", "album"],
    "Artist | Album": ["artist", "album"],
    "Genre | Album": ["genre", "album"],
    "Decade | Album artist | Album": ["decade", "artist_key", "album"],
    "Year | Album artist | Album": ["year", "artist_key", "album"],
    "Genre | Year | Album artist | Album": ["genre", "year", "artist_key", "album"],
    "Composer | Album": ["composer", "album"],
    "Folder": ["folder"],
}
DEFAULT_PANES = PANE_PRESETS["Genre | Album artist | Album"]


def pane_label(field: str, value) -> str:
    if value in ("", 0, None):
        return PANE_FIELDS[field][2]
    if field == "decade":
        return f"{value}s"
    if field == "rating":
        return "★" * value + "☆" * (5 - value)
    f = F.get(field)
    if f and f.kind in ("rate", "size", "bitrate"):
        return F.format_value(f, value)
    return str(value)


def _sort_key(field: str):
    f = F.get(field)
    if f and f.kind == "num":
        return lambda v: (not v, -F._to_float(v))
    if field in NUMERIC_FIELDS or (f and f.numeric):  # newest / best first, unknown last
        return lambda v: (not v, -(v or 0))
    return lambda v: (v == "", str(v).lower().removeprefix("the "))


class Pane(QWidget):
    changed = Signal()
    menuRequested = Signal(object, object)  # pane, global pos

    def __init__(self, field: str, parent=None):
        super().__init__(parent)
        self.field = field
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.header = QLabel(PANE_FIELDS[field][0].upper())
        self.header.setObjectName("PaneHeader")
        self.header.setToolTip("Right-click to change, add or remove columns")
        self.header.setContextMenuPolicy(Qt.CustomContextMenu)
        self.header.customContextMenuRequested.connect(
            lambda pos: self.menuRequested.emit(self, self.header.mapToGlobal(pos)))
        lay.addWidget(self.header)
        self.list = QListWidget()
        self.list.setObjectName("Pane")
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setFrameShape(QFrame.NoFrame)
        self.list.setUniformItemSizes(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setTextElideMode(Qt.ElideRight)
        self.list.itemSelectionChanged.connect(self._on_select)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(
            lambda pos: self.menuRequested.emit(self, self.list.viewport().mapToGlobal(pos)))
        lay.addWidget(self.list)
        self.setMinimumWidth(110)
        self._building = False

    def selected_values(self) -> set | None:
        """None means 'All'."""
        items = self.list.selectedItems()
        vals = [i.data(Qt.UserRole) for i in items]
        if not items or any(v is None for v in vals):
            return None
        return set(vals)

    def populate(self, tracks: list[dict], keep: set | None):
        f = self.field
        get = field_value(f)
        counts: dict = {}
        for t in tracks:
            v = get(t)
            counts[v] = counts.get(v, 0) + 1
        values = sorted(counts, key=_sort_key(f))
        self._building = True
        self.list.setUpdatesEnabled(False)
        self.list.clear()
        all_item = QListWidgetItem(f"All {PANE_FIELDS[f][1].lower()}  ({len(values)})")
        all_item.setData(Qt.UserRole, None)
        f_bold = all_item.font()
        f_bold.setBold(True)
        all_item.setFont(f_bold)
        self.list.addItem(all_item)
        reselect = []
        for v in values:
            label = pane_label(f, v)
            it = QListWidgetItem(label)
            it.setData(Qt.UserRole, v)
            it.setToolTip(f"{label} — {counts[v]} track{'s' if counts[v] != 1 else ''}")
            self.list.addItem(it)
            if keep and v in keep:
                reselect.append(it)
        if reselect:
            for it in reselect:
                it.setSelected(True)
            self.list.scrollToItem(reselect[0])
        else:
            all_item.setSelected(True)
        self.list.setUpdatesEnabled(True)
        self._building = False

    def _on_select(self):
        if self._building:
            return
        items = self.list.selectedItems()
        # picking a value while "All" is selected drops "All"
        if len(items) > 1 and any(i.data(Qt.UserRole) is None for i in items):
            self._building = True
            self.list.item(0).setSelected(False)
            self._building = False
        self.changed.emit()


class ColumnBrowser(QWidget):
    filtered = Signal(object)  # tracks passing every pane
    fieldsEdited = Signal(list)  # columns changed from the right-click menu
    editRequested = Signal()
    hideRequested = Signal()
    renameRequested = Signal(str)  # field key

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("BrowserArea")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.split = QSplitter(Qt.Horizontal)
        self.split.setChildrenCollapsible(False)
        self.split.setHandleWidth(1)
        lay.addWidget(self.split)
        self.panes: list[Pane] = []
        self.base: list[dict] = []
        self.widths: dict[str, list[int]] = {}  # pane widths per layout

    def fields(self) -> list[str]:
        return [p.field for p in self.panes]

    # Drag a column by its title to move it (only while unlocked).
    unlocked = False

    def set_unlocked(self, on: bool):
        ColumnBrowser.unlocked = on
        for p in self.panes:
            p.header.setCursor(Qt.OpenHandCursor if on else Qt.ArrowCursor)
            p.header.setToolTip("Drag to move this column; right-click to change, add or remove columns" if on
                                else "Right-click to change, add or remove columns")

    def eventFilter(self, obj, ev):
        from PySide6.QtCore import QEvent
        pane = next((p for p in self.panes if p.header is obj), None)
        if pane is None:
            return super().eventFilter(obj, ev)
        t = ev.type()
        if t not in (QEvent.MouseButtonPress, QEvent.MouseMove, QEvent.MouseButtonRelease):
            return super().eventFilter(obj, ev)
        if not ColumnBrowser.unlocked:
            self._press = None
            return False
        here = obj.mapTo(self, ev.position().toPoint())  # browser coordinates
        if t == QEvent.MouseButtonPress and ev.button() == Qt.LeftButton:
            self._press = (pane, here)
            obj.setCursor(Qt.ClosedHandCursor)
            return True
        press = getattr(self, "_press", None)
        if t == QEvent.MouseMove and press and press[0] is pane and (ev.buttons() & Qt.LeftButton):
            if getattr(self, "_ghost", None) is None:
                if (here - press[1]).manhattanLength() < QApplication.startDragDistance():
                    return True
                self._start_drag(pane, press[1])
            self._drag_to(here)
            return True
        if t == QEvent.MouseButtonRelease and press:
            self._press = None
            obj.setCursor(Qt.OpenHandCursor)
            if getattr(self, "_ghost", None) is not None:
                self._drop(pane, here)
            return True
        return False

    def _start_drag(self, pane, start):
        hdr = pane.header
        ghost = QLabel(self)
        pm = hdr.grab()
        ghost.setPixmap(pm)
        ghost.setStyleSheet("background: palette(highlight); border-radius: 4px;")
        ghost.resize(hdr.size())
        top_left = hdr.mapTo(self, hdr.rect().topLeft())
        ghost.move(top_left)
        ghost.show()
        ghost.raise_()
        self._ghost, self._grab_dx = ghost, start.x() - top_left.x()
        line = QFrame(self)
        line.setStyleSheet("background: palette(highlight); border-radius: 1px;")
        line.resize(3, self.height())
        line.show()
        line.raise_()
        self._line = line

    def _drop_index(self, x: int, dragged) -> int:
        others = [p for p in self.panes if p is not dragged]
        for k, p in enumerate(others):
            mid = p.mapTo(self, p.rect().center()).x()
            if x < mid:
                return k
        return len(others)

    def _drag_to(self, here):
        self._ghost.move(here.x() - self._grab_dx, self._ghost.y())
        dragged = self._press[0] if getattr(self, "_press", None) else None
        others = [p for p in self.panes if p is not dragged]
        k = self._drop_index(here.x(), dragged)
        if others:
            if k < len(others):
                x = others[k].mapTo(self, others[k].rect().topLeft()).x() - 2
            else:
                x = others[-1].mapTo(self, others[-1].rect().topRight()).x() - 1
            self._line.move(max(0, x), 0)

    def _drop(self, pane, here):
        for w in (self._ghost, self._line):
            w.hide()
            w.deleteLater()
        self._ghost = self._line = None
        fields = [p.field for p in self.panes if p is not pane]
        k = self._drop_index(here.x(), pane)
        fields.insert(k, pane.field)
        if fields != self.fields():
            self._apply(fields)

    def set_fields(self, fields: list[str]):
        fields = [f for f in fields if f in PANE_FIELDS][:MAX_PANES] or list(DEFAULT_PANES)
        if self.panes:
            self.widths[",".join(self.fields())] = self.split.sizes()
        old = {p.field: p.selected_values() for p in self.panes}
        for p in self.panes:
            p.setParent(None)
            p.deleteLater()
        self.panes = []
        for f in fields:
            pane = Pane(f)
            pane.changed.connect(lambda p=pane: self._cascade(self.panes.index(p) + 1))
            pane.menuRequested.connect(self._pane_menu)
            pane.header.installEventFilter(self)
            pane.header.setCursor(Qt.OpenHandCursor if ColumnBrowser.unlocked else Qt.ArrowCursor)
            self.split.addWidget(pane)
            self.panes.append(pane)
        sizes = self.widths.get(",".join(fields))
        if sizes and len(sizes) == len(fields):
            self.split.setSizes(sizes)
        else:
            self.split.setSizes([1000] * len(fields))
        # keep selections in fields that are still shown
        tracks = self.base
        for pane in self.panes:
            pane.populate(tracks, old.get(pane.field))
            sel = pane.selected_values()
            if sel is not None:
                get = field_value(pane.field)
                tracks = [t for t in tracks if get(t) in sel]
        self.filtered.emit(tracks)

    def set_tracks(self, tracks: list[dict]):
        self.base = tracks
        self._cascade(0)

    def _cascade(self, start: int):
        tracks = self.base
        for i, pane in enumerate(self.panes):
            if i >= start:
                pane.populate(tracks, pane.selected_values() if pane.list.count() else None)
            sel = pane.selected_values()
            if sel is not None:
                get = field_value(pane.field)
                tracks = [t for t in tracks if get(t) in sel]
        self.filtered.emit(tracks)

    def select_value(self, field: str, value):
        """Jump the browser to a value."""
        if field == "album":
            from musicwell.tags import album_title
            value = album_title(value or "")  # one Album entry for every disc
        for i, pane in enumerate(self.panes):
            if pane.field == field:
                for r in range(pane.list.count()):
                    it = pane.list.item(r)
                    it.setSelected(it.data(Qt.UserRole) == value)
                    if it.data(Qt.UserRole) == value:
                        pane.list.scrollToItem(it, QAbstractItemView.PositionAtCenter)
                self._cascade(i + 1)
                return True
        return False

    def reset(self):
        for p in self.panes:
            p.list.clearSelection()
        self._cascade(0)

    def _pane_menu(self, pane: Pane, pos):
        """Locked: just Unlock. Unlocked: change, add or remove columns."""
        m = QMenu(self)
        if not self.unlocked:
            if SongTable.lock_toggle:
                m.addAction("🔓  Unlock to edit", lambda: SongTable.lock_toggle(False))
                m.exec(pos)
            return
        i = self.panes.index(pane)
        fields = self.fields()
        name = PANE_FIELDS[pane.field][0]
        change = m.addMenu(f"Change “{name}” to".replace("&", "&&"))
        _field_menu(change, lambda k: self._apply(fields[:i] + [k] + fields[i + 1:]),
                    current=pane.field, used=set(fields))
        m.addAction(f"Rename “{name}”…".replace("&", "&&"), lambda k=pane.field: self.renameRequested.emit(k))
        rem = m.addAction(f"Remove “{name}”".replace("&", "&&"), lambda: self._apply(fields[:i] + fields[i + 1:]))
        rem.setEnabled(len(fields) > 1)
        add = m.addMenu("Add a column here")
        add.setEnabled(len(fields) < MAX_PANES)
        _field_menu(add, lambda k: self._apply(fields[:i + 1] + [k] + fields[i + 1:]), used=set(fields))
        m.addSeparator()
        bm = m.addMenu("The column browser")
        for pname, pf in PANE_PRESETS.items():
            a = bm.addAction(pname, lambda pf=pf: self._apply(list(pf)))
            a.setCheckable(True)
            a.setChecked(pf == fields)
        bm.addSeparator()
        bm.addAction("Edit columns…", lambda: self.editRequested.emit())
        if F.renames():
            bm.addAction("Reset column names", lambda: self.renameRequested.emit(""))
        bm.addAction("Hide the column browser", lambda: self.hideRequested.emit())
        m.addSeparator()
        if SongTable.lock_toggle:
            m.addAction("🔒  Lock (nothing moves)", lambda: SongTable.lock_toggle(True))
        m.exec(pos)

    def _apply(self, fields: list[str]):
        self.set_fields(fields)
        self.fieldsEdited.emit(self.fields())


def _field_menu(menu: QMenu, pick, current: str | None = None, used: set = frozenset()):
    """Browsable fields, common ones first, the rest in submenus."""
    groups: dict[str, QMenu] = {}
    for f in F.browsable():
        target = menu
        if f.group != "Basic" and f.key not in ("rating", "format", "folder"):
            if f.group not in groups:
                groups[f.group] = QMenu(f.group.replace("&", "&&"), menu)
            target = groups[f.group]
        a = target.addAction(f.name, lambda k=f.key: pick(k))
        a.setCheckable(True)
        a.setChecked(f.key == current)
        a.setEnabled(f.key == current or f.key not in used)
    if groups:
        menu.addSeparator()
        for name in ("Tags", "Audio & file", "Library", "Custom"):
            if name in groups:
                menu.addMenu(groups[name])


class _HeaderHand(QObject):
    """Unlocked: open-hand cursor over column headers (closed while dragging). Resize arrows stay at the edges."""

    def __init__(self, header):
        super().__init__(header)
        self.h = header
        self.pressed = False

    def _on_edge(self, x: int) -> bool:
        h = self.h
        for v in range(h.count()):
            lg = h.logicalIndex(v)
            if h.isSectionHidden(lg):
                continue
            right = h.sectionViewportPosition(lg) + h.sectionSize(lg)
            if abs(x - right) <= 5:
                return True
        return False

    def eventFilter(self, obj, ev):
        if not SongTable.columns_unlocked:
            if getattr(self, "touched", False):
                self.touched = False
                obj.unsetCursor()
            return False
        self.touched = True
        t = ev.type()
        if t == QEvent.MouseButtonPress and ev.button() == Qt.LeftButton:
            if not self._on_edge(int(ev.position().x())):
                self.pressed = True
                obj.setCursor(Qt.ClosedHandCursor)
        elif t == QEvent.MouseButtonRelease:
            self.pressed = False
            QTimer.singleShot(0, lambda: obj.setCursor(Qt.OpenHandCursor))
        elif t == QEvent.MouseMove:
            if self.pressed:
                obj.setCursor(Qt.ClosedHandCursor)
            elif not ev.buttons():
                if self._on_edge(int(ev.position().x())):
                    obj.setCursor(Qt.SplitHCursor)
                else:
                    obj.setCursor(Qt.OpenHandCursor)
        elif t == QEvent.Leave:
            obj.unsetCursor()
        return False


class SongTable(QTableView):
    columns_unlocked = False  # True while customizing: headers can be dragged
    playRequested = Signal(int)  # row
    menuRequested = Signal(list, object)  # track ids, global pos
    deleteRequested = Signal(list)  # rows
    rated = Signal(int, int)
    customColumnRequested = Signal()  # no longer in the menu
    customRemoveRequested = Signal(str)  # field key
    customManageRequested = Signal()
    renameRequested = Signal(str)  # field key
    tracksDropped = Signal(list, int, bool, list)  # song ids, row to insert before, from this list?, its rows
    resetNamesRequested = Signal()
    columnsChanged = Signal()  # shown/hidden/moved/resized
    autoFitToggled = Signal(bool)

    def __init__(self, theme: th.Theme, parent=None, hidden_by_default: tuple = ()):
        super().__init__(parent)
        self.theme = theme
        self.model_ = SongModel(theme, self)
        from PySide6.QtCore import QTimer as _T
        self._fit_timer = _T(self, singleShot=True, interval=0)
        self._fit_timer.timeout.connect(self._auto_fit)
        self.model_.modelReset.connect(lambda: SongTable.AUTO_FIT and self._fit_timer.start())
        self.header_extra = None  # callable(menu) adding header menu items while unlocked
        self.header_always = None  # the same, locked or not
        self.hidden_by_default = set(hidden_by_default)
        self.setModel(self.model_)
        self.rating_delegate = RatingDelegate(theme, self)
        self.rating_delegate.rated.connect(self.rated)

        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setMouseTracking(True)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        # Songs can be dragged out to playlists, the queue or other apps.
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setDefaultDropAction(Qt.CopyAction)
        self.drops_ok = False
        self.setFrameShape(QFrame.NoFrame)
        self.setTextElideMode(Qt.ElideRight)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(30)
        self.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        h = self.horizontalHeader()
        h.setSortIndicatorClearable(True)
        h.setSortIndicator(-1, Qt.AscendingOrder)
        self.setSortingEnabled(True)
        self.model_.sort_col = -1
        h.setHighlightSections(False)
        h.setSectionsMovable(SongTable.columns_unlocked)  # column dragging only while customizing
        self._hand = _HeaderHand(h)
        h.viewport().installEventFilter(self._hand)
        h.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        h.setMinimumSectionSize(28)
        h.setContextMenuPolicy(Qt.CustomContextMenu)
        h.customContextMenuRequested.connect(self._header_menu)
        h.sortIndicatorChanged.connect(self._on_sort_indicator)
        h.sectionMoved.connect(lambda *a: self.columnsChanged.emit())
        h.sectionResized.connect(self._on_section_resized)
        self._apply_defaults()

        self.doubleClicked.connect(lambda idx: self.playRequested.emit(idx.row()))
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._body_menu)

    def _on_sort_indicator(self, col, order):
        if col < 0:  # sort cleared: back to library order
            self.model_.sort_col = -1
            self.model_.sort(-1)

    def _setup_column(self, i: int, f):
        h = self.horizontalHeader()
        if f.key == "rating":
            self.setItemDelegateForColumn(i, self.rating_delegate)
        else:
            self.setItemDelegateForColumn(i, None)
        if f.key == "playing":
            h.setSectionResizeMode(i, QHeaderView.Fixed)
        else:
            h.setSectionResizeMode(i, QHeaderView.Interactive)

    def _apply_defaults(self):
        h = self.horizontalHeader()
        h.blockSignals(True)  # fit the title once at the end, not after every column
        for i, f in enumerate(self.model_.fields):
            self._setup_column(i, f)
            self.setColumnWidth(i, f.width)
            self.setColumnHidden(i, not f.visible or f.key in self.hidden_by_default)
        h.blockSignals(False)
        self._fit_title()

    TITLE_MIN = 150

    def _fit_title(self):
        """Title takes the remaining width, at least TITLE_MIN (the list scrolls sideways if needed)."""
        i = self.model_.column_of("title")
        if i < 0 or self.isColumnHidden(i):
            return
        others = sum(self.columnWidth(c) for c in range(self.model_.columnCount())
                     if c != i and not self.isColumnHidden(c))
        want = max(self.TITLE_MIN, self.viewport().width() - others - 2)
        if abs(self.columnWidth(i) - want) > 1:
            h = self.horizontalHeader()
            h.blockSignals(True)
            self.setColumnWidth(i, want)
            h.blockSignals(False)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit_title()

    def set_fields(self, fields: list):
        """Custom fields added or removed; keep the current layout."""
        state = self.column_state()
        self.model_.set_fields(fields)
        self._apply_defaults()
        self.restore_column_state(state)

    def _on_section_resized(self, logical, old, new):
        if self.model_.fields[logical].key != "title":
            self._fit_title()
        self.columnsChanged.emit()

    def column_state(self) -> list[dict]:
        """Visible columns in order with widths, plus hidden ones (for saving)."""
        h = self.horizontalHeader()
        out = []
        for visual in range(h.count()):
            i = h.logicalIndex(visual)
            f = self.model_.fields[i]
            out.append({"key": f.key, "shown": not self.isColumnHidden(i), "width": self.columnWidth(i)})
        return out

    def restore_column_state(self, state: list[dict]):
        if not state:
            return
        h = self.horizontalHeader()
        h.blockSignals(True)
        known = {d["key"]: d for d in state if isinstance(d, dict) and "key" in d}
        order = [d["key"] for d in state if d.get("key") in known]
        for target, key in enumerate(order):
            i = self.model_.column_of(key)
            if i < 0:
                continue
            d = known[key]
            self.setColumnHidden(i, not d.get("shown", True))
            if d.get("width") and key != "title":
                self.setColumnWidth(i, int(d["width"]))
            cur = h.visualIndex(i)
            if cur != target and target < h.count():
                h.moveSection(cur, target)
        h.blockSignals(False)
        self._fit_title()

    def show_column(self, key: str, shown: bool = True):
        i = self.model_.column_of(key)
        if i >= 0:
            self.setColumnHidden(i, not shown)
            if shown and self.columnWidth(i) < 30:
                self.setColumnWidth(i, self.model_.fields[i].width)
            if shown and SongTable.AUTO_FIT:
                self.fit_column(i)
            self._fit_title()
            self.columnsChanged.emit()

    AUTO_FIT = False  # set by the window from settings
    FIT_MAX = 520  # max width of a fitted column

    def fit_column(self, i: int) -> bool:
        """Size one column to its header and contents."""
        if not (0 <= i < len(self.model_.fields)) or self.isColumnHidden(i):
            return False
        key = self.model_.fields[i].key
        if key in ("playing", "title"):
            return False  # the title column takes what's left
        h = self.horizontalHeader()
        h.blockSignals(True)
        self.resizeColumnToContents(i)
        w = max(self.columnWidth(i), h.sectionSizeHint(i))
        self.setColumnWidth(i, min(self.FIT_MAX, w + 6))
        h.blockSignals(False)
        return True

    def fit_all_columns(self, save: bool = True):
        """Size every column to its contents, keeping them all inside the window."""
        h = self.horizontalHeader()
        fields = self.model_.fields
        cols = [i for i, f in enumerate(fields) if not self.isColumnHidden(i) and f.key not in ("playing", "title")]
        want, least = {}, {}
        h.blockSignals(True)
        for i in cols:
            self.resizeColumnToContents(i)
            head = h.sectionSizeHint(i) + 6
            want[i] = min(self.FIT_MAX, max(self.columnWidth(i), head) + 6)
            least[i] = min(want[i], 46 if fields[i].numeric else 64)  # long titles get "..."
        fixed = sum(self.columnWidth(i) for i, f in enumerate(fields)
                    if f.key == "playing" and not self.isColumnHidden(i))
        ti = self.model_.column_of("title")
        title_room = self.TITLE_MIN if ti >= 0 and not self.isColumnHidden(ti) else 0
        # shrink the wide text columns first, then everything evenly
        avail = self.viewport().width() - fixed - title_room - 4
        total = sum(want.values())
        if avail > 0 and total > avail:
            give = {i: want[i] - least[i] for i in cols if want[i] > least[i]}
            room = sum(give.values())
            if room > 0:
                share = min(1.0, (total - avail) / room)
                for i, g in give.items():
                    want[i] -= int(g * share + 0.999)
        for i in cols:
            self.setColumnWidth(i, want[i])
        h.blockSignals(False)
        self._fit_title()
        self.viewport().update()
        if save:
            self.columnsChanged.emit()

    def _auto_fit(self):
        if SongTable.AUTO_FIT and self.model_.rowCount():
            self.fit_all_columns(save=False)

    lock_toggle = None  # callable(lock: bool), set by the window
    bold_headers = None  # callable() -> bool, set by the window
    set_bold_headers = None

    def _header_menu(self, pos):
        """Sizing always works; column choice, names and browser only while unlocked."""
        m = QMenu(self)
        m.setToolTipsVisible(True)
        clicked = self.horizontalHeader().logicalIndexAt(pos)
        cf = self.model_.fields[clicked] if 0 <= clicked < len(self.model_.fields) else None
        if cf is not None and cf.key not in ("playing", "title"):
            m.addAction(f"Resize “{cf.name}” to fit".replace("&", "&&"),
                        lambda i=clicked: (self.fit_column(i), self._fit_title(), self.columnsChanged.emit()))
        auto = m.addAction("Auto-resize columns", self.fit_all_columns)
        auto.setToolTip("Make every column as wide as what's in it, all within the window (once — drag the edges "
                        "afterwards if you like)")
        if self.header_always:
            m.addSeparator()
            self.header_always(m)
        unlocked = SongTable.columns_unlocked
        if unlocked:
            m.addSeparator()
            if cf is not None and cf.key != "playing":
                m.addAction(f"Rename “{cf.name}” column…".replace("&", "&&"),
                            lambda k=cf.key: self.renameRequested.emit(k))
            cm = m.addMenu("Columns")
            cm.setToolTipsVisible(True)
            self._columns_menu(cm)
            if self.header_extra:
                self.header_extra(m)
            if SongTable.bold_headers is not None:
                b = m.addAction("Bold column headers")
                b.setCheckable(True)
                b.setChecked(SongTable.bold_headers())
                b.setToolTip("Column headers and browser titles in strong, bright type")
                b.toggled.connect(lambda on: SongTable.set_bold_headers(on))
        if SongTable.lock_toggle:
            m.addSeparator()
            if unlocked:
                m.addAction("🔒  Lock (nothing moves)", lambda: SongTable.lock_toggle(True))
            else:
                m.addAction("🔓  Unlock to edit", lambda: SongTable.lock_toggle(False))
        m.exec(self.horizontalHeader().mapToGlobal(pos))

    def _body_menu(self, pos):
        """The songs menu, or Columns when no columns are shown."""
        hdr = self.horizontalHeader()
        if hdr.count() and all(hdr.isSectionHidden(i) for i in range(hdr.count())):
            m = QMenu(self)
            if SongTable.columns_unlocked:
                self._columns_menu(m.addMenu("Columns"))
            elif SongTable.lock_toggle:
                m.addAction("🔓  Unlock to add columns", lambda: SongTable.lock_toggle(False))
            m.exec(self.viewport().mapToGlobal(pos))
            return
        self.menuRequested.emit(self.selected_ids(), self.viewport().mapToGlobal(pos))

    def _columns_menu(self, m: QMenu):
        """Column choices: common ones, then by group, custom columns, resets."""
        groups: dict[str, QMenu] = {}
        for i, f in enumerate(self.model_.fields):
            if f.key in ("playing", "artist_key"):
                continue
            if f.group == "Basic":
                menu = m
            else:
                if f.group not in groups:
                    groups[f.group] = QMenu(f.group.replace("&", "&&"), m)
                menu = groups[f.group]
            a = menu.addAction(f.name)
            a.setCheckable(True)
            a.setChecked(not self.isColumnHidden(i))
            a.toggled.connect(lambda on, k=f.key: self.show_column(k, on))
        m.addSeparator()
        for name in ("Tags", "Audio & file", "Library", "Custom"):
            if name in groups:
                m.addMenu(groups[name])
        m.addSeparator()
        cf = m.addAction("Custom fields…", lambda: self.customManageRequested.emit())
        cf.setToolTip("Make any tag in your files into a column — add, rename or delete them")
        m.addSeparator()
        if F.renames():
            m.addAction("Reset column names", lambda: self.resetNamesRequested.emit())
        m.addAction("Reset columns", self._reset_columns)

    def _reset_columns(self):
        h = self.horizontalHeader()
        for logical in range(h.count()):
            h.moveSection(h.visualIndex(logical), logical)
        self._apply_defaults()
        self.columnsChanged.emit()

    def refresh_theme(self):
        self.model_.refresh_theme()
        self.rating_delegate.refresh_theme()
        self.viewport().update()

    def selected_rows(self) -> list[int]:
        return sorted({i.row() for i in self.selectionModel().selectedRows()})

    def selected_ids(self) -> list[int]:
        rows = self.model_.rows
        return [rows[r]["id"] for r in self.selected_rows()]

    def selected_tracks(self) -> list[dict]:
        return [self.model_.rows[r] for r in self.selected_rows()]

    last_used = 0.0  # last scroll, click or keypress in this list

    def _touched(self):
        import time as _t
        self.last_used = _t.monotonic()

    def recently_used(self, seconds: float = 8.0) -> bool:
        import time as _t
        return _t.monotonic() - self.last_used < seconds

    def wheelEvent(self, e):
        self._touched()
        super().wheelEvent(e)

    def mousePressEvent(self, e):
        self._touched()
        super().mousePressEvent(e)

    def enable_drops(self, on: bool = True):
        self.drops_ok = on
        self.setAcceptDrops(on)
        self.setDropIndicatorShown(on)
        self.setDragDropMode(QAbstractItemView.DragDrop if on else QAbstractItemView.DragOnly)

    def _drop_row(self, pos) -> int:
        idx = self.indexAt(pos)
        if not idx.isValid():
            return self.model_.rowCount()
        r = self.visualRect(idx)
        return idx.row() + (1 if pos.y() > r.center().y() else 0)

    def dragEnterEvent(self, e):
        from musicwell.models import TRACKS_MIME
        if self.drops_ok and e.mimeData().hasFormat(TRACKS_MIME):
            e.setDropAction(Qt.MoveAction if e.source() is self else Qt.CopyAction)
            e.accept()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        from musicwell.models import TRACKS_MIME
        if not (self.drops_ok and e.mimeData().hasFormat(TRACKS_MIME)):
            e.ignore()
            return
        super().dragMoveEvent(e)  # scrolls and draws the drop indicator
        e.setDropAction(Qt.MoveAction if e.source() is self else Qt.CopyAction)
        e.accept()

    def dropEvent(self, e):
        from musicwell.models import TRACKS_MIME
        if not (self.drops_ok and e.mimeData().hasFormat(TRACKS_MIME)):
            e.ignore()
            return
        try:
            ids = [int(i) for i in json.loads(bytes(e.mimeData().data(TRACKS_MIME)).decode() or "[]")]
        except (ValueError, TypeError):
            ids = []
        row = self._drop_row(e.position().toPoint())
        internal = e.source() is self
        rows = self.selected_rows() if internal else []
        e.setDropAction(Qt.CopyAction)  # we do the move ourselves, not Qt
        e.accept()
        self.stopAutoScroll()
        if ids:
            self.tracksDropped.emit(ids, row, internal, rows)

    def follow_id(self, tid: int, select: bool = True) -> bool:
        """Scroll the playing song into view if it isn't already, without touching the selection while you're using the list."""
        m = self.model_
        if m.by_row:  # Queue page: its playing row, or none
            r = m.current_row if 0 <= m.current_row < len(m.rows) and m.rows[m.current_row]["id"] == tid else -1
        else:
            r = next((i for i, t in enumerate(m.rows) if t["id"] == tid), -1)
        if r < 0:
            return False
        idx = self.model_.index(r, max(0, self.model_.column_of("title")))
        rect = self.visualRect(idx)
        if not (rect.isValid() and self.viewport().rect().contains(rect)):
            self.scrollTo(idx, QAbstractItemView.PositionAtCenter)
        if select and len(self.selected_rows()) <= 1:
            from PySide6.QtCore import QItemSelectionModel as SM
            self.selectionModel().setCurrentIndex(idx, SM.ClearAndSelect | SM.Rows)
        return True

    def scroll_to_id(self, tid: int, select: bool = True):
        for r, t in enumerate(self.model_.rows):
            if t["id"] == tid:
                idx = self.model_.index(r, max(0, self.model_.column_of("title")))
                self.scrollTo(idx, QAbstractItemView.PositionAtCenter)
                if select:
                    self.selectRow(r)
                return True
        return False

    def keyPressEvent(self, e):
        self._touched()
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and not e.modifiers():
            rows = self.selected_rows()
            if rows:
                self.playRequested.emit(rows[0])
                return
        if e.key() == Qt.Key_Delete:
            self.deleteRequested.emit(self.selected_rows())
            return
        super().keyPressEvent(e)


# Moving things while unlocked

HAND_PROP = "_lw_cursor"


def set_hand(widget, on: bool, skip=()):
    """Unlocked: open-hand cursor over draggable parts of `widget` (widgets in `skip` keep their own)."""
    for w in [widget] + widget.findChildren(QWidget):
        if any(isinstance(w, k) for k in skip) or any(isinstance(p, k) for k in skip
                                                       for p in _parents(w, widget)):
            continue
        if on:
            if w.property(HAND_PROP) is None:
                w.setProperty(HAND_PROP, w.cursor().shape().value if w.testAttribute(Qt.WA_SetCursor) else -1)
            w.setCursor(Qt.OpenHandCursor)
        else:
            old = w.property(HAND_PROP)
            if old is None:
                continue
            w.setProperty(HAND_PROP, None)
            if old == -1:
                w.unsetCursor()
            else:
                w.setCursor(Qt.CursorShape(old))


def _parents(w, stop):
    out = []
    p = w.parentWidget()
    while p is not None and p is not stop:
        out.append(p)
        p = p.parentWidget()
    return out


def drag_label(name: str, theme, picture=None):
    """The strip that follows the mouse while dragging."""
    from PySide6.QtGui import QPixmap, QPen
    w = 190 if picture is not None else max(110, QFontMetrics(QFont()).horizontalAdvance(name) + 40)
    out = QPixmap(w, 40)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    bg = QColor(theme.color("surface"))
    bg.setAlpha(240)
    p.setBrush(bg)
    p.setPen(QPen(theme.color("accent"), 1.2))
    p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, 39), 8, 8)
    x = 12
    if picture is not None and picture.width() > 0:
        thumb = picture.scaled(48, 28, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        p.drawPixmap(8, (40 - thumb.height()) // 2, thumb)
        x = 64
    p.setPen(theme.color("text"))
    f = QFont()
    f.setPointSizeF(9)
    f.setBold(True)
    p.setFont(f)
    p.drawText(QRectF(x, 0, w - x - 6, 40), Qt.AlignVCenter | Qt.AlignLeft,
               QFontMetrics(f).elidedText(name, Qt.ElideRight, int(w - x - 8)))
    p.end()
    return out


class MoveSession(QWidget):
    """Mouse-driven move of a button, the play bar or a panel. The window grabs the mouse so it works anywhere."""

    def __init__(self, source, label_pixmap, on_move, on_drop, on_cancel=None, theme=None):
        win = source.window()
        super().__init__(win)
        self.win, self.theme = win, theme
        self.on_move, self.on_drop, self.on_cancel = on_move, on_drop, on_cancel
        self.hint = None
        self.setGeometry(win.rect())
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setMouseTracking(True)
        self.setCursor(Qt.ClosedHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.pic = QLabel(self)
        self.pic.setPixmap(label_pixmap)
        self.pic.adjustSize()
        self.pic.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.show()
        self.raise_()
        self.grabMouse(Qt.ClosedHandCursor)
        self.grabKeyboard()
        self._move(self.mapFromGlobal(self.cursor().pos()))

    def _move(self, pos):
        self.pic.move(pos + QPointF(16, 16).toPoint())
        old = self.hint
        self.on_move(self.mapToGlobal(pos))
        if self.hint != old:  # repaint just the hint, not the whole window under this overlay
            for r in (old, self.hint):
                if r is not None:
                    self.update(r.adjusted(-2, -2, 2, 2))

    def paintEvent(self, _):
        if self.hint is None or self.theme is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QColor(self.theme.color("accent"))
        c.setAlpha(60)
        p.setBrush(c)
        from PySide6.QtGui import QPen
        pen = QPen(self.theme.color("accent"), 2)
        p.setPen(pen)
        p.drawRoundedRect(QRectF(self.hint).adjusted(2, 2, -2, -2), 8, 8)

    def mouseMoveEvent(self, e):
        self._move(e.position().toPoint())

    def mouseReleaseEvent(self, e):
        g = e.globalPosition().toPoint()
        self._end()
        self.on_drop(g)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self._end()
            if self.on_cancel:
                self.on_cancel()

    def _end(self):
        self.releaseMouse()
        self.releaseKeyboard()
        self.hide()
        self.deleteLater()


class DiscoverSwitch(QWidget):
    """Like this | Search online | My sources, at the top of the Discover tab."""
    picked = Signal(int)  # 0 like this, 1 search online, 2 my sources

    NAMES = [("Like this", "Music like a song or an artist: from your library, similar artists, radio "
                           "stations and free music online (right-click a song → Find similar)"),
             ("Search online", "Search free music online: the Internet Archive, Openverse, Audius and your "
                               "own sources"),
             ("My sources", "Places online you've added yourself: podcast feeds, online playlists, web folders")]

    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QButtonGroup
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 4)
        h.setSpacing(6)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        for i, (name, tip) in enumerate(self.NAMES):
            b = QPushButton(name)
            b.setObjectName("DiscoverSeg")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(tip)
            self.group.addButton(b, i)
            h.addWidget(b)
        h.addStretch()
        self.group.idClicked.connect(self.picked.emit)

    def set_current(self, i: int):
        b = self.group.button(i)
        if b is not None and not b.isChecked():
            b.setChecked(True)


class EditFrame(QWidget):
    """Unlocked: dotted outline around a panel with its name, and a hint when empty."""

    def __init__(self, target: QWidget, theme, name_fn, empty_fn=None, hint: str = ""):
        super().__init__(target)
        self.target, self.theme = target, theme
        self.name_fn, self.empty_fn, self.hint = name_fn, empty_fn, hint
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        target.installEventFilter(self)
        self.hide()

    def eventFilter(self, obj, e):
        if obj is self.target and e.type() in (QEvent.Resize, QEvent.Show, QEvent.LayoutRequest):
            self.setGeometry(self.target.rect())
            self.raise_()
        return False

    def set_on(self, on: bool):
        self.setGeometry(self.target.rect())
        self.setVisible(on)
        if on:
            self.raise_()
            self.update()

    def paintEvent(self, _):
        from PySide6.QtGui import QColor, QFont, QPainter, QPen
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        t = self.theme
        c = QColor(t.color("faint"))
        c.setAlpha(130)
        pen = QPen(c, 1.2)
        pen.setStyle(Qt.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(self.rect()).adjusted(2.5, 2.5, -2.5, -2.5), 9, 9)
        name = self.name_fn() if callable(self.name_fn) else str(self.name_fn)
        f = QFont(self.font())
        f.setPointSizeF(8)
        f.setBold(True)
        p.setFont(f)
        fm = p.fontMetrics()
        w = fm.horizontalAdvance(name) + 14
        tag = QRectF(10, 6, w, fm.height() + 4)
        bg = QColor(t.color("surface"))
        bg.setAlpha(230)
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(tag, 6, 6)
        p.setPen(t.color("muted"))
        p.drawText(tag, Qt.AlignCenter, name)
        if self.empty_fn is not None and self.empty_fn():
            f.setBold(False)
            f.setPointSizeF(9)
            p.setFont(f)
            p.setPen(t.color("faint"))
            p.drawText(QRectF(self.rect()).adjusted(16, 28, -16, -16), Qt.AlignCenter | Qt.TextWordWrap,
                       f"{name} — {self.hint or 'drag items here, or right-click → Add here'}")


class WrapRow(QWidget):
    """Controls in 2-3 groups on one line when there's room, wrapping when narrow."""

    def __init__(self, layouts):
        super().__init__()
        self.groups = []
        for lay in layouts:
            lay.setContentsMargins(0, 0, 0, 0)
            g = QWidget()
            g.setLayout(lay)
            self.groups.append(g)
        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(0, 0, 0, 0)
        self.v.setSpacing(6)
        self.mode = None
        self._arrange(1)

    def minimumSizeHint(self):
        return QSize(max(g.minimumSizeHint().width() for g in self.groups), super().minimumSizeHint().height())

    def _arrange(self, lines: int):
        if lines == self.mode:
            return
        self.mode = lines
        while self.v.count():
            it = self.v.takeAt(0)
            if it.layout() is not None:
                while it.layout().count():
                    it.layout().takeAt(0)
                it.layout().deleteLater()
        if len(self.groups) == 2:
            g1, g2 = self.groups
            rows = {1: [[g1, None, g2]]}.get(lines, [[g1, None], [None, g2]])
        else:
            g1, g2, g3 = self.groups
            rows = {1: [[g1, None, g2, g3]], 2: [[g1, None, g2], [None, g3]],
                    3: [[g1, None], [g2, None], [g3, None]]}[lines]
        for row in rows:
            h = QHBoxLayout()
            h.setContentsMargins(0, 0, 0, 0)
            for w in row:
                if w is None:
                    h.addStretch(1)
                else:
                    h.addWidget(w)
            self.v.addLayout(h)

    def _lines_for(self, w: int) -> int:
        ws = [g.sizeHint().width() for g in self.groups]
        if len(ws) == 2:
            return 1 if sum(ws) + 20 <= w else 2
        return 1 if sum(ws) + 40 <= w else 2 if max(ws[0] + ws[1] + 20, ws[2]) <= w else 3

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._lines_for(e.size().width()) != self.mode and not getattr(self, "_pending", False):
            self._pending = True
            QTimer.singleShot(0, self._settle)

    def _settle(self):
        """Decide once the window has settled, not on a width it had briefly while panels were appearing."""
        self._pending = False
        self._arrange(self._lines_for(self.width()))
