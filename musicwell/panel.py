"""The now playing panel, built from items you can rearrange while the window is unlocked."""
from __future__ import annotations

import html
import json

from PySide6.QtCore import QEvent, QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (QAbstractScrollArea, QAbstractSlider, QApplication, QFrame, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMenu, QPushButton, QScrollArea, QScrollBar, QSizePolicy,
                               QVBoxLayout, QWidget)

from musicwell import fields as F
from musicwell.bar import CONTROLS, PANEL_ITEMS, TOP_ITEMS, bar_key, control_name
from musicwell.models import fmt_date, fmt_time
from musicwell.lyricsview import LyricsView
from musicwell.visualizer import Visualizer
from musicwell.widgets import (ArtistHeader, ArtView, StarRow, copy_action, mirrored, scale_text,
                               text_size_menu)

MIME = "application/x-musicwell-panel-block"

# key, name, shown by default, full width, space above
BLOCKS = [
    ("artist_image", "Artist photo", True, True, 0),
    ("artwork", "Album cover", True, False, 8),
    ("visualizer", "Visualizer", True, False, 6),
    ("cast", "Playing on (casting)", True, False, 8),
    ("title", "Song title", True, False, 8),
    ("artist", "Artist", True, False, 2),
    ("album", "Album and year", True, False, 0),
    ("rating", "Rating", True, False, 6),
    ("like", "♥ Like", False, False, 6),
    ("details", "Audio details", True, False, 6),
    ("stats", "Play count", True, False, 2),
    ("fields", "Extra fields", False, False, 10),
    ("lyrics", "Lyrics", True, False, 14),
    ("upnext", "Up next", True, False, 18),
    ("artists", "Artist list", False, False, 14),
    ("albums", "All albums", False, False, 14),
    ("artist_info", "About the artist", False, False, 14),
    ("songs", "Song list", False, False, 14),
]
# items you add yourself; not in a new panel
OPT_IN = {"artists", "albums", "artist_info", "like", "songs"}
BLOCK_NAMES = {b[0]: b[1] for b in BLOCKS}
ALL_KEYS = [b[0] for b in BLOCKS]
DEFAULT_ORDER = [b[0] for b in BLOCKS if b[0] not in OPT_IN]
DEFAULT_HIDDEN = [b[0] for b in BLOCKS if not b[2]]
DEFAULT_FIELDS = ["comment", "label", "bpm"]
ALIGNMENTS = {"left": Qt.AlignLeft, "center": Qt.AlignHCenter, "right": Qt.AlignRight}
SPACER_STEP, SPACER_MIN, SPACER_MAX = 8, 4, 240
# key: (min, max) height for items you can resize
RESIZABLE = {"artist_image": (90, 900), "artwork": (60, 900), "visualizer": (24, 400),
             "lyrics": (60, 1200), "upnext": (40, 900), "fields": (30, 900), "cast": (24, 400),
             "artists": (110, 1600), "albums": (110, 1600),
             "artist_info": (80, 1600), "songs": (110, 1600)}
ARTISTS_HEIGHT = 330
FILLABLE = ("artists", "albums", "artist_info", "songs")  # items that can fill the rest of the panel's height
GRIP = 10  # px along the bottom edge that resizes
COPIES = ("bar:", "top:")  # copies of play bar and top bar items
TEXT_ITEMS = {"artist_image", "title", "artist", "album", "details", "stats", "fields", "cast", "lyrics", "upnext", "artists",
              "albums", "artist_info", "songs", "bar:info", "bar:time", "top:status", "top:search"}


class SpacerWidget(QWidget):
    """Empty space, optionally with a divider line."""

    def __init__(self, panel, height: int = 24, line: bool = False):
        super().__init__()
        self.panel = panel
        self.line = line
        self.set_height(height)

    def set_height(self, h: int):
        self.h = max(SPACER_MIN, min(SPACER_MAX, int(h)))
        self.setFixedHeight(self.h)
        self.update()

    def paintEvent(self, _):
        if not self.line:
            return
        p = QPainter(self)
        c = QColor(self.panel.theme.color("faint"))
        c.setAlpha(120)
        y = self.height() // 2
        p.fillRect(0, y, self.width(), 1, c)


class _Outline(QWidget):
    """Unlocked: a faint outline around the item (clicks pass through)."""

    def __init__(self, block):
        super().__init__(block)
        self.block = block
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.hot = False

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        th = self.block.panel.theme
        c = QColor(th.color("accent") if self.hot else th.color("faint"))
        c.setAlpha(200 if self.hot else 110)
        pen = QPen(c)
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(self.rect()).adjusted(3.5, 1.5, -3.5, -1.5), 6, 6)
        if self.block.resizable():
            p.setPen(Qt.NoPen)
            p.setBrush(c)
            if self.block.panel.horizontal:  # top panel: the left and right edges set the width
                cy = self.height() / 2
                p.drawRoundedRect(QRectF(self.width() - 6.5, cy - 16, 2.5, 32), 1.2, 1.2)
                p.drawRoundedRect(QRectF(4, cy - 16, 2.5, 32), 1.2, 1.2)
            else:
                cx = self.width() / 2
                p.drawRoundedRect(QRectF(cx - 16, self.height() - 4.5, 32, 2.5), 1.2, 1.2)
                p.drawRoundedRect(QRectF(cx - 16, 2, 32, 2.5), 1.2, 1.2)
                for g2 in getattr(self.block, "viz_grips", []):  # the visualizer's own width
                    gx = g2.geometry().center().x()
                    cy = g2.geometry().center().y()
                    p.drawRoundedRect(QRectF(gx - 1.2, cy - 12, 2.5, 24), 1.2, 1.2)


class _Handle(QLabel):
    """Unlocked: a grip in the item's corner that always drags."""

    def __init__(self, block):
        super().__init__("⠿", block)
        self.block = block
        self.setAlignment(Qt.AlignCenter)
        self.setFixedSize(22, 18)
        self.setCursor(Qt.OpenHandCursor)
        self._press = None

    def refresh_look(self):
        th = self.block.panel.theme
        self.setStyleSheet(f"QLabel{{color:{th.color('muted').name()}; background:{th.color('surface').name()};"
                           f"border-radius:5px; font-size:10pt;}}")
        self.setToolTip(f"Drag to move “{self.block.name}” (drag it out of the panel to remove it)")

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press = e.position().toPoint()
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        if self._press is not None and (e.position().toPoint() - self._press).manhattanLength() \
                >= QApplication.startDragDistance():
            self._press = None
            self.setCursor(Qt.OpenHandCursor)
            self.block.start_drag()

    def mouseReleaseEvent(self, e):
        self._press = None
        self.setCursor(Qt.OpenHandCursor)


class _Grip(QWidget):
    """Unlocked: an edge that resizes the item."""

    def __init__(self, block, sideways: bool = False, start: bool = False):
        super().__init__(block)
        self.block = block
        self.force_sideways = sideways
        self.sign = -1 if start else 1  # the top or left edge: dragging outwards makes it bigger
        self.setCursor(Qt.SizeVerCursor)
        self.setToolTip("Drag to make it taller or shorter · double-click: back to its own size")
        self._resize = None

    def sideways(self) -> bool:
        return self.force_sideways or self.block.panel.horizontal

    def refresh_look(self):
        if self.sideways():
            self.setCursor(Qt.SizeHorCursor)
            self.setToolTip("Drag to make it wider or narrower · double-click: back to its own width")
        else:
            self.setCursor(Qt.SizeVerCursor)
            self.setToolTip("Drag to make it taller or shorter · double-click: back to its own size")

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            if self.force_sideways and not self.block.panel.horizontal:
                self._resize = (e.globalPosition().x(), self.block.panel.viz.width())
            elif self.sideways():
                self._resize = (e.globalPosition().x(), self.block.width())
            else:
                self._resize = (e.globalPosition().y(), self.block.panel.block_height(self.block.key))

    def mouseMoveEvent(self, e):
        if self._resize is not None:
            k = self.sign
            if self.force_sideways and not self.block.panel.horizontal:
                x0, w0 = self._resize  # centred: both edges move
                self.block.panel.set_block_width(self.block.key, w0 + 2 * k * int(e.globalPosition().x() - x0),
                                                 save=False)
                return
            if self.sideways():
                x0, w0 = self._resize
                self.block.panel.set_block_width(self.block.key, w0 + k * int(e.globalPosition().x() - x0), save=False)
                return
            y0, h0 = self._resize
            self.block.panel.set_block_height(self.block.key, h0 + k * int(e.globalPosition().y() - y0), save=False)

    def mouseReleaseEvent(self, e):
        if self._resize is not None:
            self._resize = None
            self.block.panel.layoutChanged.emit()

    def mouseDoubleClickEvent(self, e):
        if self.sideways():
            self.block.panel.set_block_width(self.block.key, None)
        else:
            self.block.panel.set_block_height(self.block.key, None)


def _interactive(w, stop) -> bool:
    """Widgets where dragging already means something (lists, sliders, text boxes)."""
    while w is not None and w is not stop:
        if isinstance(w, (QAbstractScrollArea, QAbstractSlider, QLineEdit)):
            return True
        w = w.parentWidget()
    return False


def item_name(key: str) -> str:
    if key.startswith("bar:"):
        return control_name(key[4:])
    if key.startswith("top:"):
        return TOP_ITEMS[key[4:]]
    return BLOCK_NAMES[key]


class PanelBlock(QWidget):
    def __init__(self, panel, key: str, content: QWidget, full_width: bool, space_above: int,
                 placeholder: str):
        super().__init__()
        self.panel = panel
        self.key = key
        self.is_spacer = key.startswith("spacer:")
        self.name = "Spacer" if self.is_spacer else item_name(key)
        self.content = content
        self.hidden = False  # hidden by you
        self.active = True  # has something to show now
        lay = QVBoxLayout(self)
        self._side, self._space = (0 if full_width else 20), space_above
        lay.setContentsMargins(self._side, space_above, self._side, 0)
        lay.setSpacing(0)
        self._lay = lay
        lay.addWidget(content)
        self.placeholder = QLabel(placeholder)
        self.placeholder.setObjectName("NowMeta")
        self.placeholder.setWordWrap(True)
        self.placeholder.setMinimumHeight(42)
        self.placeholder.setAlignment(Qt.AlignLeft | Qt.AlignBottom)
        self.placeholder.hide()
        lay.addWidget(self.placeholder)
        self.overlay = _Outline(self)
        self.overlay.hide()
        self.handle = _Handle(self)
        self.handle.hide()
        # edges that resize it: bottom and top (or right and left in the top panel)
        self.grip = _Grip(self)
        self.grip_start = _Grip(self, start=True)
        self.grips = [self.grip, self.grip_start]
        # the visualizer's width can be changed too, from either side
        self.grip2 = _Grip(self, sideways=True) if key == "visualizer" else None
        self.grip2_start = _Grip(self, sideways=True, start=True) if key == "visualizer" else None
        self.viz_grips = [g for g in (self.grip2, self.grip2_start) if g is not None]
        for g in self.grips + self.viz_grips:
            g.hide()
        self._press = None
        self._watched: set = set()
        # never taller than the content
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_edit_pieces()

    def _place_edit_pieces(self):
        self.overlay.setGeometry(self.rect())
        self.handle.move(self.width() - self.handle.width() - 6, 3)
        if self.panel.horizontal:
            self.grip.setGeometry(self.width() - GRIP, 0, GRIP, self.height())
            self.grip_start.setGeometry(0, 0, GRIP, self.height())
        else:
            self.grip.setGeometry(0, self.height() - GRIP, self.width(), GRIP)
            self.grip_start.setGeometry(0, 0, self.width(), GRIP)
        for g in self.grips:
            g.refresh_look()
        if self.grip2 is not None:
            vz = self.panel.viz
            r = vz.geometry() if vz.isVisible() else None
            right = vz.mapTo(self, vz.rect().topRight()).x() if r else self.width() - GRIP
            left = vz.mapTo(self, vz.rect().topLeft()).x() if r else 0
            h = max(GRIP, self.height() - 2 * GRIP)
            self.grip2.setGeometry(min(self.width() - GRIP, right + 2), GRIP, GRIP, h)
            self.grip2_start.setGeometry(max(0, left - GRIP - 2), GRIP, GRIP, h)
            for g in self.viz_grips:
                g.refresh_look()

    # unlocked: dragging the item (outside lists and sliders) moves it
    def _watch(self, w):
        for c in [w] + w.findChildren(QWidget):
            if c not in self._watched:
                c.installEventFilter(self)
                self._watched.add(c)

    def eventFilter(self, obj, e):
        if not self.panel.editing:
            return False
        t = e.type()
        if t == QEvent.Enter:
            self._hover(True)
        elif t == QEvent.Leave and not self.rect().contains(self.mapFromGlobal(self.cursor().pos())):
            self._hover(False)
        elif t == QEvent.MouseButtonPress and e.button() == Qt.LeftButton and not _interactive(obj, self) \
                and not isinstance(obj, _Grip):  # dragging an edge resizes instead
            self._press = e.globalPosition().toPoint()
        elif t == QEvent.MouseMove and self._press is not None and e.buttons() & Qt.LeftButton:
            if (e.globalPosition().toPoint() - self._press).manhattanLength() >= QApplication.startDragDistance() + 3:
                self._press = None
                self.start_drag()
                return True
        elif t == QEvent.MouseButtonRelease:
            self._press = None
        return False

    def _hover(self, on: bool):
        self.overlay.hot = on
        self.overlay.update()
        if on:
            self.panel._pill_hover(True)
        if self.panel.editing and not self.panel.outlines:
            self.handle.setVisible(on)
            if on:
                self.handle.raise_()

    def enterEvent(self, e):
        if self.panel.editing:
            self._hover(True)

    def leaveEvent(self, e):
        self._hover(False)

    def resizable(self) -> bool:
        return self.panel.horizontal or self.is_spacer or self.key in RESIZABLE

    def title(self) -> str:
        if self.is_spacer:
            return f"{'Divider' if self.content.line else 'Spacer'} · {self.content.h}px"
        h = self.panel.heights.get(self.key)
        return f"{self.name} · {h}px" if h else self.name

    def refresh(self):
        if self.key not in self.panel.order:
            self.hide()  # removed from the panel
            return
        unlocked = self.panel.editing
        outlines = unlocked and self.panel.outlines
        strip = self.panel.horizontal
        self._lay.setContentsMargins(self._side, self._space + (2 if outlines else 0),
                                     self._side + ((GRIP - 2) if (strip and outlines) else 0),
                                     (GRIP - 2) if (outlines and self.resizable() and not strip) else (3 if outlines else 0))
        if unlocked and not self.hidden:
            self.setVisible(True)
            empty = not self.active  # nothing to show: say what it is
            self.content.setVisible(not empty)
            self.placeholder.setVisible(empty)
            self._watch(self)
            self._place_edit_pieces()
            self.handle.refresh_look()
            self.overlay.setVisible(outlines)
            # grip: always with outlines, otherwise on hover
            self.handle.setVisible(outlines or self.underMouse())
            self.overlay.raise_()
            for g in self.grips:
                g.setVisible(self.resizable())
                g.raise_()
            for g in self.viz_grips:
                g.setVisible(not self.panel.horizontal)
                g.raise_()
            self.handle.raise_()  # the move handle stays on top of the edges
            self.overlay.update()
            from musicwell.widgets import set_hand
            set_hand(self, True, skip=(QAbstractScrollArea, QAbstractSlider, QLineEdit, _Grip))
        else:
            for w in [self.overlay, self.handle] + self.grips + self.viz_grips:
                w.hide()
            self.placeholder.hide()
            self.content.setVisible(True)
            self.setVisible(self.active and not self.hidden)
            from musicwell.widgets import set_hand
            set_hand(self, False, skip=(_Grip,))

    def start_drag(self):
        """Pick the item up; drop it on a panel to move it, anywhere else to remove it."""
        _DragSession(self)


class _DragSession(QWidget):
    """Moving a panel item with the mouse, handled by the window instead of desktop drag and drop."""

    def __init__(self, block):
        win = block.window()
        super().__init__(win)
        self.block, self.win = block, win
        self.setGeometry(win.rect())
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setMouseTracking(True)
        self.setCursor(Qt.ClosedHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.pic = QLabel(self)
        self.pic.setPixmap(_drag_picture(block.grab(), block.name, block.panel.theme))
        self.pic.adjustSize()
        self.pic.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        block.panel._dragging = block.key
        from musicwell.bar import PlayBar
        self._panel_list = [p for p in win.findChildren(NowPlayingPanel) if p.isVisible() and p.editing]
        bars = [b for b in win.findChildren(PlayBar) if b.isVisible() and b.editing] if bar_key(block.key) else []
        self._play_bar = bars[0] if bars else None  # looked up once, not on every mouse move
        bar = self._bar()
        if bar is not None:
            bar._show_empty_zones(True)  # empty areas of the bar can take the visualizer too
        self.show()
        self.raise_()
        self.grabMouse(Qt.ClosedHandCursor)
        self.grabKeyboard()
        self._follow(self.mapFromGlobal(self.cursor().pos()))

    def _panels(self):
        return self._panel_list

    def _over(self, gpos):
        for p in self._panels():
            if p.rect().contains(p.mapFromGlobal(gpos)):
                return p
        return None

    def _bar(self):
        """The play bar, while unlocked, if this item can be dropped on it."""
        return self._play_bar

    def _follow(self, pos):
        self.pic.move(pos + QPoint(16, 16))
        gpos = self.mapToGlobal(pos)
        for p in self._panels():
            p._hide_indicator()
        p = self._over(gpos)
        if p is not None:
            bpos = p.body.mapFromGlobal(gpos)
            p._show_indicator(bpos)
            p._autoscroll(bpos)
        bar = self._bar()
        if bar is not None:
            bar.show_drop_at(gpos)
        if hasattr(self.win, "show_top_drop"):
            self.win.show_top_drop(gpos)

    def mouseMoveEvent(self, e):
        self._follow(e.position().toPoint())

    def mouseReleaseEvent(self, e):
        gpos = e.globalPosition().toPoint()
        self._finish(self._over(gpos), gpos)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self._finish(None, None, cancel=True)

    def _finish(self, target, gpos, cancel: bool = False):
        self.releaseMouse()
        self.releaseKeyboard()
        block, src = self.block, self.block.panel
        src._dragging = None
        for p in self._panels():
            p._hide_indicator()
        bar = self._bar()
        if bar is not None:
            bar.show_drop_at(None)
        if hasattr(self.win, "show_top_drop"):
            self.win.show_top_drop(None)
        self.hide()
        self.deleteLater()
        key = block.key
        if cancel:
            if bar is not None:
                bar._show_empty_zones(False)
            return
        drop_on_top = getattr(self.win, "drop_on_top", None)
        if target is None and bar is not None and gpos is not None and bar.drop_from_panel(key, gpos):
            src.remove_block(key)  # moved into the play bar
        elif target is None and gpos is not None and drop_on_top and (moved := drop_on_top(key, gpos)) is not False:
            if moved:
                src.remove_block(key)  # into the top bar
        elif target is None:
            src.remove_block(key)  # dropped outside the panels: remove it
            src.itemRemoved.emit(block.name)
        elif target is src:
            src._drop(key, src.body.mapFromGlobal(gpos))
        elif key in target.order:
            src.itemRemoved.emit("")  # the other panel already has one
        else:
            target._drop(key, target.body.mapFromGlobal(gpos))
            src.remove_block(key)
        if bar is not None:
            bar._show_empty_zones(False)


def _drag_picture(pm, name: str, theme):
    """A small strip that follows the mouse (a big image could hide where it lands)."""
    from PySide6.QtGui import QPixmap
    w = 200
    out = QPixmap(w, 44)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    bg = QColor(theme.color("surface"))
    bg.setAlpha(235)
    p.setBrush(bg)
    p.setPen(QPen(theme.color("accent"), 1.2))
    p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, 43), 8, 8)
    if pm is not None and pm.width() > 0:
        thumb = pm.scaled(52, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        p.drawPixmap(8, (44 - thumb.height()) // 2, thumb)
    p.setPen(theme.color("text"))
    f = QFont()
    f.setPointSizeF(9)
    f.setBold(True)
    p.setFont(f)
    p.drawText(QRectF(68, 0, w - 74, 44), Qt.AlignVCenter | Qt.AlignLeft,
               QFontMetrics(f).elidedText(name, Qt.ElideRight, w - 76))
    p.end()
    return out


class _MovePill(QLabel):
    """Unlocked: a "Move panel" handle at the top for dragging the panel to the other side."""

    def __init__(self, panel):
        super().__init__("⠿  Move panel", panel.viewport())
        self.panel = panel
        self.setAlignment(Qt.AlignCenter)
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip("Drag to move the whole panel to the other side of the window")
        self._press = None
        self.hide()

    def refresh_look(self):
        th = self.panel.theme
        self.setStyleSheet(f"QLabel{{color:{th.accent_text()}; background:{th.accent.name()}; border-radius:9px;"
                           f"padding:1px 10px; font-size:8.5pt; font-weight:600;}}")
        self.adjustSize()
        self.move((self.panel.viewport().width() - self.width()) // 2, 4)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press = e.globalPosition().toPoint()

    def mouseMoveEvent(self, e):
        if self._press is not None and (e.globalPosition().toPoint() - self._press).manhattanLength() \
                >= QApplication.startDragDistance():
            self._press = None
            self.hide()
            self.panel.move_whole()

    def mouseReleaseEvent(self, e):
        self._press = None


class _LinesLabel(QLabel):
    """Song title, artist and album wrapped onto as many lines as needed."""

    def hasHeightForWidth(self) -> bool:
        return False

    def heightForWidth(self, w: int) -> int:
        return -1


class _Body(QWidget):
    """Scrolling content; accepts drops while rearranging."""

    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        self.setObjectName("NowPanel")
        self.setAcceptDrops(True)

    # unlocked: dragging an empty part moves the whole panel
    def mousePressEvent(self, e):
        if self.panel.editing and e.button() == Qt.LeftButton and self.panel._block_at(e.globalPosition().toPoint()) is None:
            self._press = e.globalPosition().toPoint()
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        press = getattr(self, "_press", None)
        if press is not None and e.buttons() & Qt.LeftButton and \
                (e.globalPosition().toPoint() - press).manhattanLength() > QApplication.startDragDistance() + 3:
            self._press = None
            self.panel.move_whole()
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._press = None
        super().mouseReleaseEvent(e)

    def dragEnterEvent(self, e):
        if self.panel.editing and e.mimeData().hasFormat(MIME):
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if not e.mimeData().hasFormat(MIME):
            return
        e.acceptProposedAction()
        self.panel._show_indicator(e.position().toPoint())
        self.panel._autoscroll(e.position().toPoint())

    def dragLeaveEvent(self, e):
        self.panel._hide_indicator()

    def dropEvent(self, e):
        key = bytes(e.mimeData().data(MIME)).decode()
        src = bytes(e.mimeData().data(MIME + "-from")).decode()
        e.acceptProposedAction()
        if src and src != str(id(self.panel)) and key in self.panel.order:
            NowPlayingPanel._dropped_on = "refused"  # this panel already has one: nothing changes
            self.panel._hide_indicator()
            return
        NowPlayingPanel._dropped_on = self.panel
        self.panel._drop(key, e.position().toPoint())


class NowPlayingPanel(QScrollArea):
    _dropped_on = None  # panel an item was just dropped on
    rated = Signal(int)
    upNextActivated = Signal(int)
    disconnectRequested = Signal()
    layoutChanged = Signal()  # order / hidden / fields changed
    coverStyleChanged = Signal(str)  # picked in this panel: every album cover follows
    blockVisibilityChanged = Signal(str, bool)
    likeRequested = Signal()
    editingChanged = Signal(bool)
    lockRequested = Signal(bool)
    sideRequested = Signal(object)  # global point, or None to swap sides
    itemRemoved = Signal(str)  # dragged out of the panel
    refreshImagesRequested = Signal()
    artistsWanted = Signal()
    activeChanged = Signal(str, bool)  # an item has something to show now, or not

    # top panel: items side by side, default widths
    STRIP_WIDTHS = {"artwork": 0, "artist_image": 0, "title": 240, "artist": 220, "album": 220, "rating": 170,
                    "like": 60, "lyrics": 340, "upnext": 320, "artists": 280, "albums": 300, "artist_info": 360,
                    "details": 260, "stats": 220, "fields": 260, "visualizer": 260, "cast": 220}

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.horizontal = False  # strip across the window, items side by side
        self.widths: dict[str, int] = {}  # strip widths you set
        self.editing = False
        self.outlines = True  # unlocked: faint outlines around items
        self._dragging = None
        self.setObjectName("NowPanel")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMinimumWidth(250)

        self.body = _Body(self)
        self.setWidget(self.body)
        self.vbox = QVBoxLayout(self.body)
        self.vbox.setContentsMargins(0, 0, 0, 16)
        self.vbox.setSpacing(0)
        # lists set to fill take the rest of the height
        self._fill_timer = QTimer(self, singleShot=True, interval=0)
        self._fill_timer.timeout.connect(self._fill_lists)
        self.body.installEventFilter(self)
        # The scroll bar floats over the items instead of taking width from them. When it took width, the
        # photo and cover got smaller, the items then fitted, the bar went away and they grew again: a loop.
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._vbar = QScrollBar(Qt.Vertical, self)
        self._vbar.hide()
        real = self.verticalScrollBar()
        real.rangeChanged.connect(lambda lo, hi: self._sync_vbar())
        real.valueChanged.connect(self._vbar.setValue)
        self._vbar.valueChanged.connect(real.setValue)

        self.move_pill = _MovePill(self)
        self._pill_timer = QTimer(self, interval=150)  # unlocked: is the mouse over the panel?
        self._pill_timer.timeout.connect(lambda: self._pill_hover(
            self.rect().contains(self.mapFromGlobal(self.cursor().pos())) and self.isVisible()))
        self.viewport().installEventFilter(self)
        self.edit_bar = QLabel("")  # kept for older code that shows / hides it
        self.edit_bar.setObjectName("NowMeta")
        self.edit_bar.setWordWrap(True)
        self.edit_bar.setAlignment(Qt.AlignCenter)
        self.edit_bar.setContentsMargins(16, 24, 16, 8)
        self.edit_bar.hide()

        self.header = ArtistHeader(theme)
        self.art = ArtView(theme)
        self.header.refreshRequested.connect(self.refreshImagesRequested)
        self.art.refreshRequested.connect(self.refreshImagesRequested)
        self.viz = Visualizer(theme)
        self.viz.setFixedHeight(54)
        viz_box = QWidget()
        vb = QHBoxLayout(viz_box)
        vb.setContentsMargins(0, 0, 0, 0)
        vb.addWidget(self.viz, 0, Qt.AlignHCenter)
        self._viz_lay = vb

        self.cast_row = QWidget()
        cr = QHBoxLayout(self.cast_row)
        cr.setContentsMargins(0, 0, 0, 0)
        cr.setSpacing(8)
        self.cast_label = QLabel("")
        self.cast_label.setObjectName("NowArtist")
        self.cast_label.setWordWrap(True)
        self.disconnect_btn = QPushButton("Disconnect")
        self.disconnect_btn.setCursor(Qt.PointingHandCursor)
        self.disconnect_btn.setToolTip("Stop playing on the speaker and come back to this computer")
        self.disconnect_btn.clicked.connect(self.disconnectRequested)
        cr.addWidget(self.cast_label, 1)
        cr.addWidget(self.disconnect_btn, 0, Qt.AlignVCenter)

        self.title = _LinesLabel("Nothing playing")
        self.title.setObjectName("NowTitle")
        self.artist = _LinesLabel("")
        self.artist.setObjectName("NowArtist")
        self.album = _LinesLabel("")
        self.album.setObjectName("NowAlbum")
        for w in (self.title, self.artist, self.album):
            w.setWordWrap(True)
            w.setTextInteractionFlags(Qt.TextSelectableByMouse)
            w.setContextMenuPolicy(Qt.NoContextMenu)  # the panel's menu has Copy and Text size
        self.stars = StarRow(theme)
        self.stars.rated.connect(self.rated)
        # Like item: songs go to Favourites, radio songs to Liked.
        from musicwell.widgets import IconButton
        self.like_row = QWidget()
        lr = QHBoxLayout(self.like_row)
        lr.setContentsMargins(0, 0, 0, 0)
        lr.setSpacing(6)
        self.like_btn = IconButton("heart_empty", 20, "♥ Like the playing song — Ctrl+Shift+L")
        self.like_btn.clicked.connect(self.likeRequested)
        self.like_text = QLabel("Like")
        self.like_text.setObjectName("NowMeta")
        self.like_text.setCursor(Qt.PointingHandCursor)
        self.like_text.mouseReleaseEvent = lambda e: self.likeRequested.emit() if e.button() == Qt.LeftButton else None
        lr.addWidget(self.like_btn)
        lr.addWidget(self.like_text)
        lr.addStretch(1)
        self.like_state = None
        self.like_btn.apply(theme, "heart_empty", "muted")
        self.meta = QLabel("")
        self.meta.setObjectName("NowMeta")
        self.meta.setWordWrap(True)
        self.stats = QLabel("")
        self.stats.setObjectName("NowMeta")
        self.stats.setWordWrap(True)  # long lines mustn't widen the panel
        self.fields_label = QLabel("")
        self.fields_label.setObjectName("NowMeta")
        self.fields_label.setWordWrap(True)
        self.fields_label.setTextFormat(Qt.RichText)
        self.fields_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.fields_label.setContextMenuPolicy(Qt.NoContextMenu)

        self.lyrics_view = LyricsView(theme, compact=True)

        up_box = QWidget()
        ul = QVBoxLayout(up_box)
        ul.setContentsMargins(0, 0, 0, 0)
        ul.setSpacing(4)
        up = QLabel("UP NEXT")
        up.setObjectName("NowSectionLabel")
        self.up_label = up
        ul.addWidget(up)
        self.upnext = QListWidget()
        self.upnext.setObjectName("UpNext")
        self.upnext.setFocusPolicy(Qt.NoFocus)
        self.upnext.setFrameShape(QFrame.NoFrame)
        self.upnext.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.upnext.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.upnext.setStyleSheet("QListWidget{background:transparent;} QListWidget::item{padding:3px 0;}")
        self.upnext.itemDoubleClicked.connect(lambda it: self.upNextActivated.emit(self.upnext.row(it)))
        ul.addWidget(self.upnext)

        from musicwell.artistlist import ArtistList
        self.artists = ArtistList(theme)
        self.artists.optionsChanged.connect(lambda: (self.artistsWanted.emit(), self.layoutChanged.emit()))
        from musicwell.albumlist import AlbumList
        self.albums = AlbumList(theme)
        self.albums.optionsChanged.connect(lambda: (self._apply_sizes(), self.layoutChanged.emit()))
        from musicwell.artistinfo import ArtistInfoView
        self.artist_info = ArtistInfoView(theme)
        self.artist_info.optionsChanged.connect(lambda: (self._apply_sizes(), self.layoutChanged.emit()))
        self.artists.optionsChanged.connect(self._apply_sizes)
        from musicwell.panelsongs import PanelSongList
        self.songs = PanelSongList(theme)
        self.songs.optionsChanged.connect(lambda: (self._apply_sizes(), self.layoutChanged.emit()))

        contents = {
            "artists": (self.artists, ""),
            "albums": (self.albums, ""),
            "artist_info": (self.artist_info, ""),
            "songs": (self.songs, ""),
            "artist_image": (self.header, "Artist photo"),
            "artwork": (self.art, ""),
            "visualizer": (viz_box, ""),
            "cast": (self.cast_row, "“Playing on …” appears here while casting"),
            "title": (self.title, ""),
            "artist": (self.artist, ""),
            "album": (self.album, ""),
            "rating": (self.stars, "Rating stars appear here while a song is loaded"),
            "like": (self.like_row, "♥ Like the playing song"),
            "details": (self.meta, "Format · sample rate · bit depth · bitrate"),
            "stats": (self.stats, "Play count"),
            "fields": (self.fields_label, "Extra fields — right-click the panel → Extra fields to choose "
                                          "(Comment, Label, BPM, your custom columns…)"),
            "lyrics": (self.lyrics_view, "Lyrics for the playing song — synced lyrics scroll along"),
            "upnext": (up_box, ""),
        }
        self.blocks: dict[str, PanelBlock] = {}
        for key, name, _shown, full, space in BLOCKS:
            w, ph = contents[key]
            self.blocks[key] = PanelBlock(self, key, w, full, space, ph or name)
        self.order = list(DEFAULT_ORDER)
        self.heights: dict[str, int] = {}  # heights you set by dragging
        self.text_sizes: dict[str, float] = {}  # bigger or smaller text than the theme's
        for key in TEXT_ITEMS & set(self.blocks):
            self._text_menu_for(key)
        self.field_keys = list(DEFAULT_FIELDS)
        self.align = "left"
        self.middle = False  # centre the items vertically
        for key in DEFAULT_HIDDEN:
            self.blocks[key].hidden = True

        self.indicator = QFrame(self.body)
        self.indicator.setFixedHeight(3)
        self.indicator.hide()

        self._track = None
        self.set_cast_name(None)
        self.set_track(None, None, None)
        self.set_lyrics(None)
        self._rebuild()

    def set_horizontal(self, on: bool):
        """Items side by side (a strip) or stacked (a side panel)."""
        from PySide6.QtWidgets import QBoxLayout
        self.horizontal = on
        self.vbox.setDirection(QBoxLayout.LeftToRight if on else QBoxLayout.TopToBottom)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded if on else Qt.ScrollBarAlwaysOff)
        self.setMinimumWidth(0 if on else 250)
        self.setMinimumHeight(110 if on else 0)
        self.vbox.setContentsMargins(8, 4, 8, 4) if on else self.vbox.setContentsMargins(0, 0, 0, 16)
        self._rebuild()
        self._sync_vbar()

    def set_block_width(self, key: str, w: int | None, save: bool = True):
        """Top panel: an item's width (None = default)."""
        if w is None:
            self.widths.pop(key, None)
        else:
            self.widths[key] = max(50, min(1600, int(w)))
        if not self.horizontal:  # side panel: the visualizer's own width
            self._apply_sizes()
            if key in self.blocks:
                self.blocks[key]._place_edit_pieces()
                self.blocks[key].overlay.update()
        elif key in self.blocks:
            self.blocks[key].setFixedWidth(self._strip_width(key))
            if key == "visualizer":
                self.viz.setFixedWidth(max(60, self._strip_width("visualizer") - 24))
            self.blocks[key].overlay.update()
        if save:
            self.layoutChanged.emit()

    def _strip_width(self, key: str) -> int:
        if self.widths.get(key):
            return self.widths[key]
        if key == "visualizer" and [k for k in self.order if not self.blocks[k].hidden] == ["visualizer"]:
            return max(120, self.viewport().width() - 8)  # whole strip unless sized by you
        if key in ("bar:seek", "top:search", "top:status"):
            return 320 if key == "bar:seek" else 260
        if key.startswith(COPIES):
            return max(48, self.blocks[key].content.sizeHint().width() + 24)
        base = key.split(":")[0]
        w = self.STRIP_WIDTHS.get(base, 240)
        if base == "spacer" or key.startswith("spacer"):
            return 24
        if w == 0:  # images: square, strip height
            return max(80, self.viewport().height() - 8)
        return w

    def _rebuild(self):
        while self.vbox.count():
            item = self.vbox.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        self.vbox.addWidget(self.edit_bar)
        if self.middle and not self.horizontal:
            self.vbox.addStretch(1)  # and one below, to centre vertically
        for key in self.order:
            self.vbox.addWidget(self.blocks[key])
            b = self.blocks[key]
            if self.horizontal:
                b.setFixedWidth(self._strip_width(key))
            elif b.maximumWidth() < 16777215 or b.minimumWidth() > 0:
                b.setMinimumWidth(0)
                b.setMaximumWidth(16777215)
                b.setMinimumHeight(0)
                b.setMaximumHeight(16777215)
        self.vbox.addStretch(1)
        for k, b in self.blocks.items():
            b.setParent(self.body)
            if k in self.order:
                b.refresh()
            else:
                b.hide()  # removed from the panel
        empty = not [k for k in self.order if not self.blocks[k].hidden]
        self.edit_bar.setText("An empty panel. Right-click here → Add here to put things in it."
                              if self.editing else "An empty panel. Press F2 (or Layouts → Unlock), then "
                              "right-click here → Add here to put things in it.")
        self.edit_bar.setVisible(empty and not self.editing)  # unlocked: the outline says it instead
        self.indicator.raise_()

    def state(self) -> dict:
        return {"order": list(self.order), "hidden": [k for k, b in self.blocks.items() if b.hidden],
                "removed": self.removed(),
                "fields": list(self.field_keys), "align": self.align,
                "spacers": {k: {"h": b.content.h, "line": b.content.line}
                            for k, b in self.blocks.items() if b.is_spacer},
                "heights": dict(self.heights), "widths": dict(self.widths), "artists": self.artists.options(),
                "albums": self.albums.options(), "artist_info": self.artist_info.options(),
                "cover_style": self.art.style, "songs": self.songs.options(), "middle": self.middle,
                "text_sizes": dict(self.text_sizes)}

    def removed(self) -> list[str]:
        return [k for k in ALL_KEYS if k not in self.order]

    def remove_block(self, key: str):
        if key.startswith(("spacer:",) + COPIES):
            self.remove_spacer(key)
            return
        if key not in self.order:
            return
        self.order.remove(key)
        self.blocks[key].hide()
        if key == "visualizer":
            self.blockVisibilityChanged.emit(key, False)
        self._rebuild()
        self.layoutChanged.emit()

    make_control = None  # callable(key) -> a working copy of a play bar or top bar item, set by the window

    def _make_control(self, key: str):
        """A block holding a copy of a play bar or top bar item ("bar:play", "top:search")."""
        content = self.make_control(key) if self.make_control else None
        if content is None:
            return None
        tip = "“▶ Your copy” shows here while the radio plays a song you have" if key == "bar:copy" else ""
        wide = key in ("bar:seek", "top:search", "top:status")
        b = PanelBlock(self, key, content, wide, 6, tip)
        if not wide:
            b._lay.setAlignment(content, ALIGNMENTS.get(self.align, Qt.AlignLeft))
        if hasattr(content, "activeChanged"):  # only shown some of the time
            b.active = content.active()
            content.activeChanged.connect(lambda on, k=key: self._set_active(k, on) if k in self.blocks else None)
        self.blocks[key] = b
        if key in TEXT_ITEMS:
            self._text_menu_for(key)
        if key in self.text_sizes:
            scale_text(content, self.text_sizes[key])
        return b

    def add_block(self, key: str, index: int = 0):
        if key.startswith(COPIES) and key not in self.blocks and self._make_control(key) is None:
            return
        if key in self.order or key not in self.blocks:
            return
        self.order.insert(max(0, min(index, len(self.order))), key)
        b = self.blocks[key]
        if b.hidden:
            b.hidden = False
        if key == "visualizer":
            self.blockVisibilityChanged.emit(key, True)
        self._rebuild()
        self._apply_sizes()
        if key in ("artists", "albums", "artist_info"):
            self.artistsWanted.emit()
        if key == "songs":
            self.blockVisibilityChanged.emit(key, True)  # the window fills it
        self.layoutChanged.emit()

    def _fill_add_menu(self, menu: QMenu, index: int):
        """Everything not in this panel, in the usual order, then a space or a line."""
        menu.clear()
        out = [k for k in ALL_KEYS if k not in self.order or self.blocks[k].hidden]
        for k in out:
            menu.addAction(BLOCK_NAMES[k], lambda k=k: self._bring_in(k, index))
        if not out:
            a = menu.addAction("Everything is in this panel")
            a.setEnabled(False)
        bar = menu.addMenu("From the play bar")
        for k in CONTROLS:
            if "bar:" + k not in self.order:
                bar.addAction(control_name(k), lambda k=k: self.add_block("bar:" + k, index))
        top = menu.addMenu("From the top bar")
        for k, name in TOP_ITEMS.items():
            if "top:" + k not in self.order:
                top.addAction(name, lambda k=k: self.add_block("top:" + k, index))
        menu.addSeparator()
        menu.addAction("Space", lambda: self.add_spacer(index))
        menu.addAction("Divider line", lambda: self.add_spacer(index, 20, True))

    def _bring_in(self, key: str, index: int):
        if key in self.order:  # hidden in older layouts: show it here
            self.blocks[key].hidden = False
            self.blockVisibilityChanged.emit(key, True)
            self.move_block(key, index)
        else:
            self.add_block(key, index)

    _graveyard: list = []  # Removed spacers stay referenced until Qt deletes them.
                                # If Python collected them first, Qt could crash while restyling every widget.

    def _bury(self, b):
        b.hide()
        b.setParent(None)
        grave = NowPlayingPanel._graveyard
        if len(grave) > 200:
            del grave[:100]  # long gone by now
        grave.append(b)
        b.deleteLater()

    def _new_spacer_key(self) -> str:
        n = 1
        while f"spacer:{n}" in self.blocks:
            n += 1
        return f"spacer:{n}"

    def _make_spacer(self, key: str, height: int, line: bool) -> PanelBlock:
        b = PanelBlock(self, key, SpacerWidget(self, height, line), False, 0, "")
        self.blocks[key] = b
        return b

    def add_spacer(self, index: int | None = None, height: int = 24, line: bool = False) -> str:
        key = self._new_spacer_key()
        self._make_spacer(key, height, line)
        if index is None:
            index = len(self.order)
        self.order.insert(max(0, min(index, len(self.order))), key)
        self._rebuild()
        self.layoutChanged.emit()
        return key

    def set_spacer(self, key: str, height: int | None = None, line: bool | None = None):
        b = self.blocks.get(key)
        if b is None or not b.is_spacer:
            return
        if height is not None:
            b.content.set_height(height)
        if line is not None:
            b.content.line = line
            b.content.update()
        b.overlay.update()
        self.layoutChanged.emit()

    def remove_spacer(self, key: str):
        b = self.blocks.pop(key, None)
        if b is None:
            return
        if key in self.order:
            self.order.remove(key)
        self._bury(b)
        self._rebuild()
        self.layoutChanged.emit()

    def set_alignment(self, align: str, emit: bool = True):
        self.align = align if align in ALIGNMENTS else "left"
        h = ALIGNMENTS[self.align]
        for w in (self.title, self.artist, self.album, self.meta, self.stats, self.cast_label,
                  self.fields_label, self.up_label):
            w.setAlignment(h | Qt.AlignVCenter)
        for key in ["rating", "like"] + [k for k in self.blocks if k.startswith(COPIES) and self.blocks[k]._side]:
            blk = self.blocks[key]
            blk._lay.setAlignment(blk.content, h)
        for b in self.blocks.values():
            b.placeholder.setAlignment(h | Qt.AlignBottom)
        self.header.set_alignment(self.align)
        self.lyrics_view.set_alignment(self.align)
        self.art.set_alignment(self.align)  # the cover and visualizer line up too
        self._viz_lay.setAlignment(self.viz, h)
        for i in range(self.upnext.count()):
            self.upnext.item(i).setTextAlignment(h | Qt.AlignVCenter)
        self._fill_fields()
        if emit:
            self.layoutChanged.emit()

    _restoring = False

    def restore_state(self, data):
        """Nothing is saved while the panel is being filled."""
        self._restoring = True
        try:
            self._restore_state(data)
        finally:
            self._restoring = False

    def _restore_state(self, data):
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except ValueError:
                data = None
        if not isinstance(data, dict):
            return
        # spacers first, so the order can refer to them
        for k in [k for k in self.blocks if k.startswith(("spacer:",) + COPIES)]:
            self._bury(self.blocks.pop(k))
        ts = data.get("text_sizes") if isinstance(data.get("text_sizes"), dict) else {}
        self.text_sizes = {k: float(v) for k, v in ts.items() if isinstance(v, (int, float)) and 0.5 <= v <= 2}
        spacers = data.get("spacers") if isinstance(data.get("spacers"), dict) else {}
        for k, d in spacers.items():
            if k.startswith("spacer:") and isinstance(d, dict):
                self._make_spacer(k, int(d.get("h", 24)), bool(d.get("line", False)))
        for k in data.get("order", []):
            if isinstance(k, str) and k.startswith(COPIES) and k not in self.blocks:
                self._make_control(k)
        order = [k for k in data.get("order", []) if k in self.blocks]
        removed = set(data.get("removed", []))
        # blocks added in newer versions appear; ones you removed stay removed
        for i, k in enumerate(DEFAULT_ORDER):
            if k in order or k in removed:
                continue
            after = [n for n in DEFAULT_ORDER[i + 1:] if n in order]  # its usual place
            order.insert(order.index(after[0]) if after else len(order), k)
        self.order = order
        hidden = set(data.get("hidden", DEFAULT_HIDDEN))
        for k, b in self.blocks.items():
            b.hidden = k in hidden
        if isinstance(data.get("fields"), list):
            self.field_keys = [k for k in data["fields"] if isinstance(k, str)]
        hs = data.get("heights") if isinstance(data.get("heights"), dict) else {}
        self.heights = {k: int(v) for k, v in hs.items() if k in RESIZABLE and isinstance(v, (int, float))}
        ws = data.get("widths") if isinstance(data.get("widths"), dict) else {}
        self.widths = {k: int(v) for k, v in ws.items() if isinstance(v, (int, float))}
        self.artists.set_options(data.get("artists"))
        self.albums.set_options(data.get("albums"))
        self.artist_info.set_options(data.get("artist_info"))
        self.art.set_style(data.get("cover_style") or "square")
        self.middle = bool(data.get("middle", False))
        self.songs.set_options(data.get("songs"))
        self.apply_text_sizes()
        self._rebuild()
        self._apply_sizes()
        self.set_alignment(data.get("align", "left"), emit=False)

    defaults = None  # {"order": [...], "hidden": [...]} for the second panel's starting items

    def reset_layout(self):
        if self.defaults:
            self.restore_state(dict(self.defaults, removed=[k for k in DEFAULT_ORDER
                                                             if k not in self.defaults["order"]]))
            self.layoutChanged.emit()
            return
        for k in [k for k in self.blocks if k.startswith(("spacer:",) + COPIES)]:
            self._bury(self.blocks.pop(k))
        self.order = list(DEFAULT_ORDER)
        self.heights = {}
        self.text_sizes = {}
        self.apply_text_sizes()
        self._apply_sizes()
        for k, b in self.blocks.items():
            was = b.hidden
            b.hidden = k in DEFAULT_HIDDEN
            if was != b.hidden:
                self.blockVisibilityChanged.emit(k, not b.hidden)
        self._rebuild()
        self.set_alignment("left")

    def _pill_hover(self, inside: bool):
        if self.editing and inside:
            if not self.move_pill.isVisible():
                self.move_pill.refresh_look()
                self.move_pill.show()
            self.move_pill.raise_()
        elif not self.rect().contains(self.mapFromGlobal(self.cursor().pos())):
            self.move_pill.hide()

    def move_whole(self):
        """Move the whole panel to the other side; the other panel swaps over."""
        from musicwell.widgets import MoveSession, drag_label
        win = self.window()
        session = None

        def side(g):
            if self.horizontal:
                return "top" if win.mapFromGlobal(g).y() < win.height() / 2 else "bottom"
            return "left" if win.mapFromGlobal(g).x() < win.width() / 2 else "right"

        def move(g):
            if session is None:
                return
            r = self.parentWidget().geometry() if self.parentWidget() else win.rect()
            top = self.parentWidget().mapTo(win, r.topLeft()) if self.parentWidget() else r.topLeft()
            from PySide6.QtCore import QRect
            if self.horizontal:
                h = max(self.height(), 110)
                y = top.y() if side(g) == "top" else top.y() + r.height() - h
                session.hint = QRect(top.x(), y, r.width(), h)
                return
            w = max(self.width(), 200)
            x = top.x() if side(g) == "left" else top.x() + r.width() - w
            session.hint = QRect(x, top.y(), w, r.height())

        session = MoveSession(self, drag_label("Panel — top or bottom" if self.horizontal else
                                               "Panel — left or right side", self.theme), move,
                              lambda g: self.sideRequested.emit(g), None, self.theme)
        move(self.cursor().pos())

    def set_editing(self, on: bool):
        """Unlocked (on) or locked."""
        was = self.editing
        self.editing = on
        self.vbox.setSpacing(2 if (on and self.outlines) else 0)
        self.body.setCursor(Qt.OpenHandCursor) if on else self.body.unsetCursor()
        if on:
            self._pill_timer.start()
        else:
            self._pill_timer.stop()
            self.move_pill.hide()
        self._rebuild()
        if was != on:
            self.editingChanged.emit(on)

    def set_block_hidden(self, key: str, hidden: bool):
        b = self.blocks[key]
        if b.hidden == hidden:
            return
        b.hidden = hidden
        b.refresh()
        self.blockVisibilityChanged.emit(key, not hidden)
        self.layoutChanged.emit()

    def _set_active(self, key: str, active: bool):
        b = self.blocks[key]
        if b.active != active:
            b.active = active
            b.refresh()
            self.activeChanged.emit(key, active)

    def _drop_index(self, pos: QPoint) -> int:
        """Where in self.order a block dropped at `pos` goes."""
        for i, key in enumerate(self.order):
            b = self.blocks[key]
            if not b.isVisible():
                continue
            if (pos.x() < b.geometry().center().x()) if self.horizontal else (pos.y() < b.geometry().center().y()):
                return i
        return len(self.order)

    def _show_indicator(self, pos: QPoint):
        i = self._drop_index(pos)
        visible = [k for k in self.order if self.blocks[k].isVisible()]
        if self.horizontal:  # strip: vertical drop line between items
            if i < len(self.order):
                x = self.blocks[self.order[i]].geometry().left()
            elif visible:
                x = self.blocks[visible[-1]].geometry().right() + 2
            else:
                x = 0
            self.indicator.setStyleSheet(f"background: {self.theme.accent.name()}; border-radius: 1px;")
            self.indicator.setGeometry(max(0, x - 2), 6, 3, self.body.height() - 12)
            self.indicator.show()
            self.indicator.raise_()
            return
        if i < len(self.order):
            y = self.blocks[self.order[i]].geometry().top()
        elif visible:
            y = self.blocks[visible[-1]].geometry().bottom() + 2
        else:
            y = 0
        self.indicator.setStyleSheet(f"background: {self.theme.accent.name()}; border-radius: 1px;")
        self.indicator.setGeometry(10, max(0, y - 2), self.body.width() - 20, 3)
        self.indicator.show()
        self.indicator.raise_()

    def _hide_indicator(self):
        self.indicator.hide()

    def _autoscroll(self, pos: QPoint):
        if self.horizontal:
            bar = self.horizontalScrollBar()
            vp_x = pos.x() - bar.value()
            if vp_x < 40:
                bar.setValue(bar.value() - 18)
            elif vp_x > self.viewport().width() - 40:
                bar.setValue(bar.value() + 18)
            return
        vp_y = pos.y() - self.verticalScrollBar().value()
        bar = self.verticalScrollBar()
        if vp_y < 40:
            bar.setValue(bar.value() - 18)
        elif vp_y > self.viewport().height() - 40:
            bar.setValue(bar.value() + 18)

    def _drop(self, key: str, pos: QPoint):
        self._hide_indicator()
        i = self._drop_index(pos)
        if key not in self.order:  # from the other panel
            if key.startswith("spacer:"):
                self.add_spacer(i)
            else:
                self.add_block(key, i)
            return
        old = self.order.index(key)
        order = list(self.order)
        order.pop(old)
        if i > old:
            i -= 1
        order.insert(i, key)
        if order != self.order:
            self.order = order
            self._rebuild()
            self.layoutChanged.emit()

    def move_block(self, key: str, new_index: int):
        """Move a block programmatically."""
        order = [k for k in self.order if k != key]
        order.insert(max(0, min(new_index, len(order))), key)
        self.order = order
        self._rebuild()
        self.layoutChanged.emit()

    def _block_at(self, global_pos) -> str | None:
        pos = self.body.mapFromGlobal(global_pos)
        for key in self.order:
            b = self.blocks[key]
            if b.isVisible() and b.geometry().contains(pos):
                return key
        return None

    def _index_at(self, global_pos) -> int:
        """Order index just after the block under the mouse."""
        pos = self.body.mapFromGlobal(global_pos)
        for i, key in enumerate(self.order):
            b = self.blocks[key]
            probe = QPoint(pos.x(), b.geometry().center().y()) if self.horizontal else \
                QPoint(b.geometry().center().x(), pos.y())
            if b.isVisible() and b.geometry().contains(probe):
                return i + 1
        return len(self.order)

    image_actions = None  # callable(kind) -> [(label, fn), ...], set by the window
    extra_actions = None  # callable() -> [(label, fn), ...], set by the window
    panels_menu = None  # callable(menu) adding the Panels submenu

    def contextMenuEvent(self, e):
        """Item actions first, then (unlocked) its options, Add here, Remove and the panel options."""
        m = QMenu(self)
        under = self._block_at(e.globalPos())
        name = self.blocks[under].name if under else ""
        if self.image_actions and under in ("artwork", "artist_image"):
            for label, fn in self.image_actions("album" if under == "artwork" else "artist"):
                m.addAction(label, fn)
        if under == "artwork":
            self._cover_style_menu(m.addMenu("Show the cover as"))
        if under in TEXT_ITEMS:
            content = self.blocks[under].content
            if isinstance(content, QLabel):
                copy_action(m, content)
            self._add_text_size(m, under)
        if self.editing:
            if under is not None:
                if m.actions():
                    m.addSeparator()
                self._item_options(m, under)
                m.addAction(f"Remove “{name}”", lambda k=under: self.remove_block(k))
            add = m.addMenu("Add here")
            self._fill_add_menu(add, self._index_at(e.globalPos()))
            self._align_menu(m.addMenu("Line up the items"))
            m.addSeparator()
            pm = m.addMenu("This panel")
            pm.addAction("Move it to the other side", lambda: self.sideRequested.emit(None))
            pm.addAction("Reset this panel", self.reset_layout)
            if self.extra_actions:
                pm.addSeparator()
                for label, fn in self.extra_actions():
                    pm.addAction(label, fn)
        if not self.editing:  # alignment is a look, not a move: allowed when locked
            if m.actions():
                m.addSeparator()
            self._align_menu(m.addMenu("Line up the items"))
        if m.actions():
            m.addSeparator()
        if self.panels_menu:
            self.panels_menu(m)
            m.addSeparator()
        if self.editing:
            m.addAction("🔒  Lock (nothing moves)", lambda: self.lockRequested.emit(True))
        else:
            m.addAction("🔓  Unlock to edit", lambda: self.lockRequested.emit(False))
        m.exec(e.globalPos())

    def _add_text_size(self, m: QMenu, key: str):
        text_size_menu(m.addMenu("Text size"), self.text_sizes.get(key, 1.0), lambda s: self.set_text_size(key, s))

    def _text_menu_for(self, key: str):
        """Items with a menu of their own (lists, lyrics) get Text size in it."""
        self.blocks[key].content.menu_extras = lambda m: self._add_text_size(m, key)

    def set_text_size(self, key: str, scale: float):
        if scale == 1:
            self.text_sizes.pop(key, None)
        else:
            self.text_sizes[key] = scale
        scale_text(self.blocks[key].content, scale)
        self._apply_sizes()
        self.layoutChanged.emit()

    def apply_text_sizes(self):
        """Text sizes again (after the theme changed, or a layout was loaded)."""
        for k, b in self.blocks.items():
            if k in TEXT_ITEMS:
                scale_text(b.content, self.text_sizes.get(k, 1.0))

    def _align_menu(self, menu: QMenu):
        """Left / Centre / Right alignment for the panel's contents."""
        for key, label in (("left", "Left"), ("center", "Centre"), ("right", "Right")):
            a = menu.addAction(label, lambda k=key: self.set_alignment(k))
            a.setCheckable(True)
            a.setChecked(self.align == key)
        if not self.horizontal:
            menu.addSeparator()
            a = menu.addAction("In the middle, up and down", lambda: self.set_middle(not self.middle))
            a.setCheckable(True)
            a.setChecked(self.middle)

    def set_middle(self, on: bool):
        """Keep items centred vertically as the panel resizes."""
        self.middle = bool(on)
        self._rebuild()
        self._apply_sizes()
        self.layoutChanged.emit()

    def _cover_style_menu(self, menu: QMenu):
        from musicwell.record import STYLES, speed_menu
        for key, label in STYLES:
            a = menu.addAction(label, lambda k=key: self.set_cover_style(k))
            a.setCheckable(True)
            a.setChecked(self.art.style == key)
        menu.addSeparator()
        speed_menu(menu.addMenu("Record speed"))

    def set_cover_style(self, style: str):
        """Album cover style: square, spinning record or picture disc."""
        self.art.set_style(style)
        self.layoutChanged.emit()
        self.coverStyleChanged.emit(style)

    def _item_options(self, m: QMenu, key: str):
        """The item's own options, straight in the menu."""
        b = self.blocks[key]
        if b.is_spacer:
            m.addAction("Taller", lambda: self.set_spacer(key, height=b.content.h + SPACER_STEP))
            m.addAction("Shorter", lambda: self.set_spacer(key, height=b.content.h - SPACER_STEP))
            m.addAction("Hide the line" if b.content.line else "Draw a line",
                        lambda: self.set_spacer(key, line=not b.content.line))
            return
        if key == "fields":
            self._fields_menu(m.addMenu("Which fields"))
        if key == "songs":
            self.songs.fill_menu(m.addMenu("Song list"))
        if key == "visualizer":
            from musicwell.visualizer import STYLES as VIZ_STYLES
            vm = m.addMenu("Style")
            for vk, vname in VIZ_STYLES.items():
                a = vm.addAction(vname, lambda k=vk: self.viz.styleRequested.emit(k))
                a.setCheckable(True)
                a.setChecked(vk == self.viz.style_name)
        if key in RESIZABLE:
            hm = m.addMenu("Height")
            cur = self.block_height(key)
            for label, delta in (("Taller", 40), ("A little taller", 12), ("A little shorter", -12), ("Shorter", -40)):
                hm.addAction(label, lambda d=delta, c=cur: self.set_block_height(key, c + d))
            hm.addSeparator()
            auto = hm.addAction("Its own size", lambda: self.set_block_height(key, None))
            auto.setEnabled(key in self.heights)

    def _fields_menu(self, menu: QMenu):
        groups: dict[str, QMenu] = {}
        for f in F.all_fields():
            if f.key in ("playing", "title", "artist", "album", "artist_key", "rating", "length",
                         "track"):
                continue
            target = menu if f.group in ("Basic",) else groups.setdefault(f.group, QMenu(f.group.replace("&", "&&"), menu))
            a = target.addAction(f.name, lambda k=f.key: self.toggle_field(k))
            a.setCheckable(True)
            a.setChecked(f.key in self.field_keys)
        menu.addSeparator()
        for name in ("Tags", "Audio & file", "Library", "Custom"):
            if name in groups:
                menu.addMenu(groups[name])

    def toggle_field(self, key: str):
        if key in self.field_keys:
            self.field_keys.remove(key)
        else:
            self.field_keys.append(key)
            if self.blocks["fields"].hidden:
                self.set_block_hidden("fields", False)
        self._fill_fields()
        self.layoutChanged.emit()

    @mirrored
    def refresh_items(self):
        """Custom fields changed: drop ones that no longer exist."""
        self.field_keys = [k for k in self.field_keys if F.get(k)]
        self._fill_fields()

    def _filling(self, key: str) -> bool:
        return key in self.order and not self.blocks[key].hidden and getattr(self, key).fill

    def eventFilter(self, obj, e):
        if obj is self.viewport() and e.type() in (QEvent.Enter, QEvent.Leave):
            self._pill_hover(e.type() == QEvent.Enter)
        if obj is self.body and e.type() == QEvent.LayoutRequest and not self._fill_timer.isActive():
            if any(self._filling(k) for k in FILLABLE):
                self._fill_timer.start()
        return super().eventFilter(obj, e)

    def _fill_lists(self):
        """Lists set to fill share whatever height the other items leave."""
        keys = [k for k in FILLABLE if self._filling(k)]
        if not keys or self.horizontal:
            return
        lists = [getattr(self, k) for k in keys]
        self.vbox.activate()
        used = self.vbox.sizeHint().height() - sum(w.minimumHeight() for w in lists)
        free = self.viewport().height() - used
        each = max(RESIZABLE["artists"][0], free // len(lists))
        for w in lists:
            if abs(w.minimumHeight() - each) > 1:
                w.setFixedHeight(each)

    def _sync_vbar(self):
        real, bar = self.verticalScrollBar(), self._vbar
        bar.setRange(real.minimum(), real.maximum())
        bar.setPageStep(real.pageStep())
        bar.setSingleStep(real.singleStep())
        bar.setValue(real.value())
        vp = self.viewport().geometry()
        bar.setGeometry(vp.right() - 9, vp.top(), 10, vp.height())
        bar.setVisible(not self.horizontal and real.maximum() > 0)
        bar.raise_()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._sync_vbar()
        QTimer.singleShot(0, self._fit_texts)  # rewrap song names for the new width
        if self.horizontal:  # images stay square as the strip resizes
            for key in self.order:
                if (self.STRIP_WIDTHS.get(key) == 0 or key == "visualizer") and not self.widths.get(key):
                    self.blocks[key].setFixedWidth(self._strip_width(key))
        self._apply_sizes()

    def _auto_height(self, key: str) -> int:
        w = self.viewport().width()
        if key == "artist_image":
            return self.header.height_for(w)
        if key == "artwork":
            return min(w - 40, 250) + 14
        if key == "visualizer":
            return 54
        if key == "lyrics":
            return 170
        if key == "upnext":
            rows = max(1, self.upnext.count())
            return rows * (self.upnext.sizeHintForRow(0) + 1) + 4 + 22
        if key == "fields":
            return self.fields_label.sizeHint().height()
        if key == "cast":
            return self.cast_row.sizeHint().height()
        if key in ("artists", "albums", "songs"):
            return ARTISTS_HEIGHT
        if key == "artist_info":
            return 240
        return 0

    def _apply_strip_sizes(self):
        """Strip: every item as tall as the strip, images square."""
        H = max(70, self.viewport().height() - 8)  # item including outline
        h = H - 16  # contents
        self.header.custom_height = h
        self.header.setFixedHeight(h)
        self.header._scaled = None
        self.art.setFixedHeight(h)
        self.viz.setFixedWidth(max(60, self._strip_width("visualizer") - 24))
        self.viz.setFixedHeight(max(30, h - 6))
        self.lyrics_view.setFixedHeight(max(40, h))
        for k in FILLABLE:
            getattr(self, k).setFixedHeight(max(40, h - 22))
        self.upnext.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.upnext.setFixedHeight(max(30, h - 22))
        self.cast_row.setMinimumHeight(0)
        self.cast_row.setMaximumHeight(16777215)
        for k in self.order:
            b = self.blocks.get(k)
            if b is None:
                continue
            b.setFixedHeight(H)
            if self.STRIP_WIDTHS.get(k) == 0 and not self.widths.get(k):
                b.setFixedWidth(self._strip_width(k))
            b.overlay.update()

    def block_height(self, key: str) -> int:
        if self.horizontal and not key.startswith("spacer:"):
            return max(60, self.viewport().height() - 10)  # strip: every item as tall as the strip
        if key.startswith("spacer:"):
            return self.blocks[key].content.h
        return self.heights.get(key) or self._auto_height(key)

    def set_block_height(self, key: str, h: int | None, save: bool = True):
        """Set an item's height (None = automatic)."""
        if key.startswith("spacer:"):
            if h is not None:
                self.set_spacer(key, height=h) if save else self.blocks[key].content.set_height(h)
                self.blocks[key].overlay.update()
            return
        if key not in RESIZABLE:
            return
        if h is None:
            self.heights.pop(key, None)
        else:
            lo, hi = RESIZABLE[key]
            self.heights[key] = max(lo, min(hi, int(h)))
        self._apply_sizes()
        self.blocks[key].overlay.update()
        if save:
            self.layoutChanged.emit()

    def _apply_sizes(self):
        if self.horizontal:
            self._apply_strip_sizes()
            return
        w = self.viewport().width()
        hs = self.heights
        self.header.custom_height = hs.get("artist_image")
        self.header.setFixedHeight(hs.get("artist_image") or self.header.height_for(w))
        self.header._scaled = None
        self.art.setFixedHeight(hs.get("artwork") or self._auto_height("artwork"))
        side = min(w - 40, 250)
        vw = self.widths.get("visualizer")
        self.viz.setFixedWidth(max(60, min(w - 8, vw)) if vw else max(60, side - 12))  # the cover's width
        self.viz.setFixedHeight(hs.get("visualizer") or 54)
        self.lyrics_view.setFixedHeight(hs.get("lyrics") or 170)
        for k in FILLABLE:
            lst = getattr(self, k)
            if not self._filling(k):
                lst.setFixedHeight(hs.get(k) or self._auto_height(k))
        self._fill_timer.start()
        if hs.get("upnext"):
            self.upnext.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            self.upnext.setFixedHeight(max(20, hs["upnext"] - 22))
        else:
            self.upnext.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            rows = max(1, self.upnext.count())
            self.upnext.setFixedHeight(rows * (self.upnext.sizeHintForRow(0) + 1) + 4)
        if hs.get("cast"):
            self.cast_row.setFixedHeight(hs["cast"])
        else:
            self.cast_row.setMinimumHeight(0)
            self.cast_row.setMaximumHeight(16777215)
        if hs.get("fields"):
            self.fields_label.setFixedHeight(hs["fields"])
            self.fields_label.setAlignment(ALIGNMENTS.get(self.align, Qt.AlignLeft) | Qt.AlignTop)
        else:
            self.fields_label.setMinimumHeight(0)
            self.fields_label.setMaximumHeight(16777215)

    @mirrored
    def refresh_theme(self):
        self.header.refresh_theme()
        self.artists.refresh_theme()
        self.albums.refresh_theme()
        self.artist_info.refresh_theme()
        self.stars.refresh_theme()
        self.like_btn.apply(self.theme, "heart_full" if self.like_state else "heart_empty", "accent" if self.like_state else "muted")
        self.art.update()
        self.viz.update()
        self.lyrics_view.update()
        for b in self.blocks.values():
            b.overlay.update()

    @mirrored
    def set_track(self, t: dict | None, art, artist_img):
        self._track = t
        if t is None:
            self.artists.set_track(None)
            self.albums.set_track(None)
            self.header.set_artist("", None)
            self.art.set_image(None)
            self.title.setText("Nothing playing")
            for w in (self.artist, self.album, self.meta, self.stats):
                w.setText("")
            for k in ("rating", "details", "stats", "artist", "album"):
                self._set_active(k, False)
            self._fill_fields()
            return
        artist_name = t["artist"] or t["albumartist"] or "Unknown Artist"
        if t.get("stream"):
            artist_name = t["artist"] or t["station"]["name"]
        self.artists.set_track(t)
        self.albums.set_track(t)
        self.header.set_artist(t["artist_key"] or artist_name, artist_img)
        self.art.set_image(art, t["album"] or t["title"])
        self.title.setText(t["title"])
        self.artist.setText(artist_name)
        album = t["album"] or "Unknown Album"
        if t.get("stream"):
            self.album.setText(f"Live on {t['station']['name']}" +
                               (f"\nNext: {self.next_text}" if getattr(self, "next_text", "") else ""))
        else:
            self.album.setText(f"{album}  ·  {t['year']}" if t["year"] else album)
        for k in ("rating", "details", "stats", "artist", "album"):
            self._set_active(k, True)
        if t.get("stream") or t.get("remote"):
            self._set_active("rating", False)  # not in your library
        self.update_stats(t)
        QTimer.singleShot(0, self._fit_texts)

    def _fit_texts(self):
        """Wrap long song names fully. The scroll area doesn't ask labels for height-for-width, so set each height by hand."""
        from PySide6.QtCore import QRect
        from PySide6.QtGui import QFontMetrics
        for w in (self.title, self.artist, self.album):
            if self.horizontal or w.width() <= 0 or not w.text():
                w.setMinimumHeight(0)
                w.setMaximumHeight(16777215)
                continue
            extra = w.height() - w.contentsRect().height() + 2 * w.margin()  # padding
            inner = max(10, w.contentsRect().width() - 2 * w.margin())
            text_h = QFontMetrics(w.font()).boundingRect(QRect(0, 0, inner, 100000),
                                                          int(Qt.TextWordWrap | w.alignment()), w.text()).height()
            want = text_h + extra
            if w.minimumHeight() != want or w.maximumHeight() != want:
                w.setFixedHeight(want)  # exactly its lines

    @mirrored
    def set_like(self, state, where: str = "radio"):
        """None (nothing to like), False / True."""
        self.like_state = state
        self.like_btn.apply(self.theme, "heart_full" if state else "heart_empty", "accent" if state else "muted")
        self.like_btn.setEnabled(state is not None)
        if where == "library":
            text = "In your Favourites" if state else "Add to Favourites"
        else:
            text = "In ♥ Liked" if state else "Like"
        self.like_text.setText(text if state is not None else "Like")
        self.like_text.setEnabled(state is not None)

    @mirrored
    def set_next(self, text: str):
        """What the station plays next, under "Live on ..."."""
        self.next_text = text
        t = getattr(self, "_track", None)
        if t is not None and t.get("stream"):
            self.album.setText(f"Live on {t['station']['name']}" + (f"\nNext: {text}" if text else ""))
            self.album.setToolTip(f"Coming up next on {t['station']['name']}: {text}" if text else "")

    @mirrored
    def set_levelling(self, text: str):
        """ReplayGain applied to the playing song, shown with the audio details."""
        self.levelling = text
        t = getattr(self, "_track", None)
        if t is not None and not t.get("stream") and not t.get("remote"):
            self.update_stats(t)

    @mirrored
    def set_lyrics(self, lyrics, message: str = ""):
        self.lyrics_view.set_lyrics(lyrics, message)
        self._set_active("lyrics", self.lyrics_view.lyrics is not None)

    @mirrored
    def set_cast_name(self, name: str | None):
        if name:
            self.cast_label.setText(f"▶  Playing on {name}")
            self.cast_label.setToolTip("The equalizer only works on this computer's speakers.")
        self._set_active("cast", bool(name))

    @mirrored
    def update_stats(self, t: dict):
        self._track = t
        self.stars.set_rating(t["rating"])
        if t.get("remote"):
            it = t["item"]
            src = {"ov": "Openverse", "src": it.get("collection") or "Your source"}.get(it.get("kind"), "Internet Archive")
            self.meta.setText("  ·  ".join(b for b in (t["format"], fmt_time(t["length"]) if t["length"] else "",
                                                       src) if b))
            self.stats.setText("  ·  ".join(b for b in (it.get("collection", ""), it.get("license", "")) if b))
            self._fill_fields()
            return
        if t.get("stream"):
            st = t["station"]
            bits = [st.get("codec") or "", f"{st['bitrate']} kbps" if st.get("bitrate") else "", "Internet radio"]
            self.meta.setText("  ·  ".join(b for b in bits if b))
            from musicwell.radio import short_country
            self.stats.setText("  ·  ".join(x for x in (short_country(st.get("country", "")), ", ".join(st.get("tags", "").split(", ")[:3])) if x))
            self._fill_fields()
            return
        bits = [t["format"]]
        if t["samplerate"]:
            bits.append(f"{t['samplerate'] / 1000:g} kHz")
        if t["bitdepth"]:
            bits.append(f"{t['bitdepth']}-bit")
        if t["bitrate"]:
            bits.append(f"{t['bitrate'] // 1000} kbps")
        bits.append(fmt_time(t["length"]))
        lev = getattr(self, "levelling", "")
        if lev:
            bits.append(lev)
        self.meta.setText("  ·  ".join(b for b in bits if b))
        n = t["playcount"]
        last = f" · last {fmt_date(t['lastplayed'])}" if t["lastplayed"] else ""
        self.stats.setText(("Never played" if not n else f"Played {n} time{'s' if n != 1 else ''}{last}"))
        self._fill_fields()

    @mirrored
    def _fill_fields(self):
        t = self._track
        rows = []
        if t is not None:
            for key in self.field_keys:
                f = F.get(key)
                if f is None:
                    continue
                v = f.display(t) if key != "lastplayed" or t.get("lastplayed") else "Never"
                if v:
                    rows.append(f"<tr><td align='{self.align}' style='padding-bottom:7px'>"
                                f"<span style='color:{self.theme.p['faint']}; font-size:7.5pt; font-weight:700'>"
                                f"{html.escape(f.name.upper())}</span><br>"
                                f"<span style='color:{self.theme.p['text']}; font-size:9.5pt'>"
                                f"{html.escape(str(v))}</span></td></tr>")
        self.fields_label.setText("<table width='100%' cellspacing='0' cellpadding='0'>" + "".join(rows)
                                  + "</table>" if rows else "")
        self._set_active("fields", bool(rows))

    @mirrored
    def set_upnext(self, tracks: list[dict], queued: int):
        self.upnext.clear()
        for i, t in enumerate(tracks[:8]):
            mark = "⏵ " if i < queued else ""
            it = QListWidgetItem(f"{mark}{t['title']}  —  {t['artist'] or 'Unknown Artist'}")
            it.setToolTip("In your queue" if i < queued else "Next in the list")
            if i >= queued:
                it.setForeground(self.theme.color("muted"))
            it.setTextAlignment(ALIGNMENTS.get(self.align, Qt.AlignLeft) | Qt.AlignVCenter)
            self.upnext.addItem(it)
        if not tracks:
            it = QListWidgetItem("Nothing queued")
            it.setForeground(self.theme.color("faint"))
            it.setTextAlignment(ALIGNMENTS.get(self.align, Qt.AlignLeft) | Qt.AlignVCenter)
            self.upnext.addItem(it)
        self._apply_sizes()


class BarSource(NowPlayingPanel):
    """Never shown: keeps the panel items that sit in the play bar up to date."""

    def __init__(self, theme):
        super().__init__(theme)
        self.set_horizontal(True)
        for b in self.blocks.values():
            b.hidden = False
        self.set_items([])

    def set_items(self, keys: list[str]):
        self.order = list(keys)
        self._rebuild()

    def _apply_sizes(self):
        pass  # the play bar sizes them


class BarItem(QWidget):
    """A panel item in the play bar."""
    activeChanged = Signal(bool)

    def __init__(self, source: BarSource, key: str):
        super().__init__()
        self.source = source
        self.key = key
        self.content = source.blocks[key].content
        self.content.setMinimumSize(0, 0)  # the bar item's own size decides
        self.content.setMaximumSize(16777215, 16777215)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.content)
        self.content.show()
        if isinstance(self.content, QLabel):
            self.content.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self.content.setWordWrap(False)  # one line in its small box
        if key == "upnext":
            source.upnext.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        source.activeChanged.connect(lambda k, on: self.activeChanged.emit(on) if k == key else None)

    def active(self) -> bool:
        return self.source.blocks[self.key].active

    def set_size(self, w, h):
        dw, dh = PANEL_ITEMS[self.key][1]
        w, h = max(40, min(1400, w or dw)), max(16, min(500, h or dh))
        self.setFixedSize(w, h)
        if self.key == "artist_image":
            header = self.source.header
            header.custom_height = h
            header.setFixedHeight(h)
            header._scaled = None
