"""The Lyrics tab and its scrolling view, which follows the song."""
from __future__ import annotations

import time

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QMenu, QPushButton, QToolButton, QVBoxLayout,
                               QWidget)

from musicwell import theme as th

FOLLOW_PAUSE = 4.0  # seconds without auto-scroll after you scroll
ALIGN = {"left": Qt.AlignLeft, "center": Qt.AlignHCenter, "right": Qt.AlignRight}


class LyricsView(QWidget):
    seekRequested = Signal(int)  # ms

    def __init__(self, theme, compact: bool = False, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.compact = compact
        self.align = "left" if compact else "center"
        self.text_scale = 1.0
        self.lyrics = None
        self.message = ""
        self.offset_ms = 0  # per-song nudge (+ = lyrics earlier)
        self.latency_ms = 0  # how far the decoder runs ahead of the speakers
        self._pos, self._stamp, self._playing = 0, time.monotonic(), False
        self._layout: list[QRect] = []
        self._note = QRect()
        self._layout_w = -1
        self._scroll = 0.0
        self._manual_until = 0.0
        self._hover = -1
        self._current = -1
        self.actions = None  # callable() -> [(label, fn) | None]
        self.setMouseTracking(True)
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._tick)
        if compact:
            self.setFixedHeight(170)
        self.setMinimumWidth(120)

    def _font(self, bold=False) -> QFont:
        f = QFont(self.font())
        f.setPointSizeF((10.5 if self.compact else 17) * self.text_scale)
        f.setWeight(QFont.Bold if bold else (QFont.DemiBold if not self.compact else QFont.Normal))
        return f

    def _gap(self) -> int:
        return 6 if self.compact else 16

    def _pad(self) -> int:
        return 0 if self.compact else 48

    def _note_font(self) -> QFont:
        f = QFont(self.font())
        f.setPointSizeF((8.5 if self.compact else 9.5) * self.text_scale)
        f.setWeight(QFont.DemiBold)
        return f

    def _note_text(self) -> str:
        if self.compact:
            return "Not synced: scroll to read"
        return "Not synced: these lyrics have no timings, so they won't follow the song"

    def _relayout(self):
        w = max(40, self.width() - 2 * self._pad())
        self._layout_w = self.width()
        self._layout = []
        self._note = QRect()
        if not self.lyrics:
            return
        fm = QFontMetrics(self._font(True))
        y = 0
        if not self.lyrics.synced:
            # plain lyrics: say so above them, so it doesn't look broken when they don't move
            nf = QFontMetrics(self._note_font())
            nw = min(w, nf.horizontalAdvance(self._note_text()) + 20)
            nh = nf.height() + 8
            x = {"left": self._pad(), "right": self._pad() + w - nw}.get(self.align, self._pad() + (w - nw) // 2)
            self._note = QRect(x, 2, nw, nh)
            y = nh + self._gap() + 4
        for _ms, text in self.lyrics.lines:
            t = text if text.strip() else ("♪" if self.lyrics.synced else " ")
            r = fm.boundingRect(QRect(0, 0, w, 100000), Qt.TextWordWrap | ALIGN[self.align], t)
            h = max(r.height(), fm.height())
            if not self.lyrics.synced and not text.strip():
                h = fm.height() // 2  # paragraph breaks in plain lyrics
            self._layout.append(QRect(self._pad(), y, w, h))
            y += h + self._gap()

    def _content_height(self) -> int:
        return self._layout[-1].bottom() if self._layout else 0

    def set_lyrics(self, lyrics, message: str = ""):
        self.lyrics = lyrics if lyrics is not None and not lyrics.empty and not lyrics.instrumental else None
        self.message = message
        if lyrics is not None and lyrics.instrumental:
            self.message = "Instrumental"
        self._current = -1
        self._hover = -1
        self._manual_until = 0.0
        self._layout_w = -1
        self._scroll = 0.0
        self.setCursor(Qt.ArrowCursor)
        self._update_running()
        self.update()
        if self.lyrics and self.lyrics.synced:
            self._scroll = self._target()

    def set_alignment(self, align: str):
        self.align = align if align in ALIGN else "left"
        self._layout_w = -1
        self.update()

    def set_position(self, ms: int, playing: bool | None = None):
        if self._playing and playing is not False and 0 < self.now_ms(raw=True) - ms < 600:
            return  # never step back for a slightly late position
        self._pos, self._stamp = ms, time.monotonic()
        if playing is not None and playing != self._playing:
            self._playing = playing
            self._update_running()
        if not self.timer.isActive():
            self._tick()

    def set_playing(self, playing: bool):
        self._pos = self.now_ms(raw=True)
        self._stamp = time.monotonic()
        self._playing = playing
        self._update_running()

    def now_ms(self, raw: bool = False) -> int:
        ms = self._pos
        if self._playing:
            ms += int((time.monotonic() - self._stamp) * 1000)
        if raw:
            return ms
        return ms - self.latency_ms + self.offset_ms

    def is_synced(self) -> bool:
        return bool(self.lyrics and self.lyrics.synced)

    def _update_running(self):
        want = self.isVisible() and self.is_synced()
        if want and not self.timer.isActive():
            self.timer.start()
        elif not want and self.timer.isActive():
            self.timer.stop()

    def showEvent(self, e):
        super().showEvent(e)
        self._layout_w = -1
        self._update_running()
        if self.is_synced():
            self._scroll = self._target()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._update_running()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._layout_w = -1

    def set_text_scale(self, scale: float):
        self.text_scale = scale
        self._layout_w = -1
        self.update()

    def _anchor(self) -> float:
        return self.height() * (0.42 if not self.compact else 0.38)

    def _target(self) -> float:
        if self._layout_w != self.width():
            self._relayout()
        if not self._layout:
            return 0.0
        i = max(0, self._current)
        r = self._layout[i]
        return r.center().y() - self._anchor()

    def _clamp(self, v: float) -> float:
        if self.is_synced():
            lo = self._layout[0].center().y() - self._anchor() if self._layout else 0
            hi = self._layout[-1].center().y() - self._anchor() if self._layout else 0
            return max(lo, min(hi, v))
        top = -self._top_margin()
        return max(top, min(max(top, self._content_height() - self.height() + 24), v))

    def _top_margin(self) -> int:
        return 4 if self.compact else 28

    def _tick(self):
        if not self.is_synced():
            return
        cur = self.lyrics.index_at(self.now_ms())
        changed = cur != self._current
        self._current = cur
        if time.monotonic() >= self._manual_until:
            target = self._target()
            d = target - self._scroll
            if abs(d) > 0.5:
                self._scroll += d * 0.18 if abs(d) < self.height() * 1.5 else d
                changed = True
        if changed:
            self.update()

    def wheelEvent(self, e):
        if not self.lyrics:
            return
        if self._layout_w != self.width():
            self._relayout()
        dy = e.angleDelta().y()
        self._scroll = self._clamp(self._scroll - dy * (0.6 if self.compact else 1.0))
        if self.is_synced():
            self._manual_until = time.monotonic() + FOLLOW_PAUSE
        self.update()
        e.accept()

    def _line_at(self, pos) -> int:
        if not self.lyrics or not self._layout:
            return -1
        y = pos.y() + self._scroll
        for i, r in enumerate(self._layout):
            if r.top() - self._gap() / 2 <= y <= r.bottom() + self._gap() / 2:
                return i
        return -1

    def mouseMoveEvent(self, e):
        on_note = self._note.contains(e.position().toPoint() + QPoint(0, int(self._scroll)))
        self.setToolTip("These lyrics only have the words, not when each line is sung, so they can't "
                        "scroll along with the song. Lyrics with timings (synced) follow the music."
                        if on_note else "")
        i = self._line_at(e.position()) if self.is_synced() else -1
        if i != self._hover:
            self._hover = i
            self.setCursor(Qt.PointingHandCursor if i >= 0 else Qt.ArrowCursor)
            self.update()

    def leaveEvent(self, e):
        if self._hover != -1:
            self._hover = -1
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or not self.is_synced():
            return
        i = self._line_at(e.position())
        if i >= 0:
            ms = self.lyrics.lines[i][0]
            self._manual_until = 0.0
            # land just before the line, allowing for the offset and output delay
            self.seekRequested.emit(max(0, ms - self.offset_ms + self.latency_ms + 30))

    def contextMenuEvent(self, e):
        if not self.actions:
            return super().contextMenuEvent(e)
        m = QMenu(self)
        for item in self.actions():
            if item is None:
                m.addSeparator()
            elif len(item) == 3:  # (label, fn, checked)
                a = m.addAction(item[0], item[1])
                a.setCheckable(True)
                a.setChecked(bool(item[2]))
            else:
                a = m.addAction(item[0], item[1]) if item[1] else m.addAction(item[0])
                a.setEnabled(item[1] is not None)
        from musicwell.widgets import add_menu_extras
        add_menu_extras(self, m)
        m.exec(e.globalPos())

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        t = self.theme
        if not self.lyrics:
            p.setPen(t.color("faint" if self.compact else "muted"))
            f = self._font()
            f.setPointSizeF((9.5 if self.compact else 13) * self.text_scale)
            f.setWeight(QFont.Normal)
            p.setFont(f)
            flags = (ALIGN[self.align] | Qt.AlignTop) if self.compact else Qt.AlignCenter
            p.drawText(self.rect().adjusted(0, 6, 0, 0), flags | Qt.TextWordWrap, self.message)
            return
        if self._layout_w != self.width():
            self._relayout()
            if self.is_synced():
                self._scroll = self._target()
            else:
                self._scroll = self._clamp(self._scroll)
        synced = self.is_synced()
        h = self.height()
        fade = min(48.0, h * 0.22) if synced or self.compact else 28.0
        if not self._note.isNull() and self._note.bottom() - self._scroll > 0:
            r = QRectF(self._note).translated(0, -self._scroll)
            bg = QColor(t.color("faint"))
            bg.setAlphaF(0.18)
            p.setPen(Qt.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
            p.setPen(t.color("muted"))
            p.setFont(self._note_font())
            p.drawText(r, Qt.AlignCenter, QFontMetrics(self._note_font()).elidedText(
                self._note_text(), Qt.ElideRight, int(r.width()) - 16))
        bold, normal = self._font(True), self._font(False)
        text_c, muted, faint, accent = t.color("text"), t.color("muted"), t.color("faint"), t.color("accent")
        for i, r in enumerate(self._layout):
            y = r.top() - self._scroll
            if y > h or y + r.height() < 0:
                continue
            ms, text = self.lyrics.lines[i]
            label = text if text.strip() else ("♪" if synced else "")
            if not label:
                continue
            if synced:
                if i == self._current:
                    c, f = QColor(text_c), bold
                elif i == self._hover:
                    c, f = QColor(accent), normal
                elif i < self._current:
                    c, f = QColor(faint), normal
                else:
                    c, f = QColor(muted), normal
            else:
                c, f = QColor(text_c if not self.compact else muted), normal
            # fade towards the edges
            mid = y + r.height() / 2
            edge = min(mid, h - mid)
            if edge < fade:
                c.setAlphaF(c.alphaF() * max(0.0, edge / fade) ** 1.2)
            if synced and i == self._current and not self.compact:
                bar = QRectF(r.left() - 22 if self.align == "left" else r.left(), y + 4, 4, r.height() - 8)
                if self.align == "left":
                    p.fillRect(bar, accent)
            p.setFont(f)
            p.setPen(c)
            p.drawText(QRect(r.left(), int(y), r.width(), r.height() + 8),
                       Qt.TextWordWrap | ALIGN[self.align] | Qt.AlignTop, label)
        if not self.compact and self.lyrics.source:
            p.setPen(t.color("faint"))
            f = QFont(self.font())
            f.setPointSizeF(8)
            p.setFont(f)
            p.drawText(self.rect().adjusted(0, 0, -12, -6), Qt.AlignRight | Qt.AlignBottom,
                       {"LRCLIB": "Lyrics from LRCLIB", "embedded": "Lyrics from the file's tags",
                        "file": "Lyrics from a .lrc file"}.get(self.lyrics.source, "")
                       + ("" if synced else " (not synced)"))


class LyricsPage(QWidget):
    """The Lyrics tab: heading, timing buttons and the lyrics view."""
    offsetChanged = Signal(int)

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 6, 12, 0)
        lay.setSpacing(4)
        row = QHBoxLayout()
        self.heading = QLabel("Lyrics")
        self.heading.setObjectName("PageTitle")
        self.sub = QLabel("")
        self.sub.setObjectName("EmptyText")
        row.addWidget(self.heading)
        row.addWidget(self.sub)
        row.addStretch()
        self.offset_label = QLabel("")
        self.offset_label.setObjectName("EmptyText")
        self.offset_label.setToolTip("Timing adjustment for this song")
        self.earlier = QPushButton("Earlier")
        self.earlier.setToolTip("Lyrics too late? Show them 0.5 s earlier")
        self.later = QPushButton("Later")
        self.later.setToolTip("Lyrics too early? Show them 0.5 s later")
        self.earlier.clicked.connect(lambda: self._nudge(+500))
        self.later.clicked.connect(lambda: self._nudge(-500))
        self.more = QToolButton()
        self.more.setPopupMode(QToolButton.InstantPopup)
        self.more.setToolTip("More")
        self.more.setStyleSheet("QToolButton::menu-indicator { image: none; width: 0; }")
        self.more_menu = QMenu(self.more)
        self.more.setMenu(self.more_menu)
        for w in (self.offset_label, self.earlier, self.later, self.more):
            row.addWidget(w)
        lay.addLayout(row)
        self.view = LyricsView(theme, compact=False)
        lay.addWidget(self.view, 1)

    def refresh_theme(self):
        self.more.setIcon(th.icon("more", self.theme.color("muted"), 18))
        self.view.update()

    def set_heading(self, t: dict | None):
        if t is None:
            self.heading.setText("Lyrics")
            self.sub.setText("")
        else:
            self.heading.setText(t["title"] or "Lyrics")
            self.sub.setText(t["artist"] or "")

    def set_offset(self, ms: int):
        self.view.offset_ms = ms
        synced = self.view.is_synced()
        for w in (self.earlier, self.later, self.offset_label):
            w.setVisible(synced)
        self.offset_label.setText("" if not ms else
                                  f"{abs(ms) / 1000:.1f} s {'earlier' if ms > 0 else 'later'}")
        self.view.update()

    def _nudge(self, delta: int):
        self.set_offset(self.view.offset_ms + delta)
        self.offsetChanged.emit(self.view.offset_ms)
