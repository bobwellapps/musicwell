"""All albums as a side panel item, shown as a list or as covers."""
from __future__ import annotations

import random

from PySide6.QtCore import QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QHBoxLayout, QLabel, QLineEdit, QListView, QListWidget,
                               QListWidgetItem, QMenu, QStyle, QStyledItemDelegate, QVBoxLayout, QWidget)

from musicwell.albumsview import SORTS, _album_order, album_groups
from musicwell.artistlist import sort_name
from musicwell.artistview import _rounded
from musicwell.models import fmt_time

KEY, TRACK, LOADED, SUB = Qt.UserRole, Qt.UserRole + 1, Qt.UserRole + 2, Qt.UserRole + 3
VIEWS = {"list": "List", "list_big": "List with bigger covers", "covers": "Covers"}
PIC = {"list": 40, "list_big": 64, "covers": 104}


class _Delegate(QStyledItemDelegate):
    """Album row: cover, title, then artist and year smaller underneath."""

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner

    def paint(self, p: QPainter, opt, index):
        o = self.owner
        th = o.theme
        r = opt.rect
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        if opt.state & QStyle.State_Selected:
            p.setPen(Qt.NoPen)
            p.setBrush(th.color("selected"))
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 5, 5)
        elif opt.state & QStyle.State_MouseOver:
            p.setPen(Qt.NoPen)
            p.setBrush(th.color("hover"))
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 5, 5)
        c = o.pic
        icon = index.data(Qt.DecorationRole)
        title = index.data(Qt.DisplayRole) or ""
        sub = index.data(SUB) or ""
        tf = index.data(Qt.FontRole) or QFont(o.list.font())
        sf = QFont(o.list.font())
        sf.setPointSizeF(max(7.0, sf.pointSizeF() - 1.5))
        fg = index.data(Qt.ForegroundRole)
        tcol = fg.color() if hasattr(fg, "color") else th.color("text")
        tm, sm = QFontMetrics(tf), QFontMetrics(sf)
        if o.view == "covers":
            ir = QRect(r.x() + (r.width() - c) // 2, r.y() + 4, c, c)
            if isinstance(icon, QIcon) and not icon.isNull():
                icon.paint(p, ir)
            w = r.width() - 6
            y = ir.bottom() + 5
            p.setFont(tf)
            p.setPen(tcol)
            p.drawText(QRect(r.x() + 3, y, w, tm.height()), Qt.AlignHCenter, tm.elidedText(title, Qt.ElideRight, w))
            p.setFont(sf)
            p.setPen(th.color("muted"))
            p.drawText(QRect(r.x() + 3, y + tm.height(), w, sm.height()), Qt.AlignHCenter,
                       sm.elidedText(sub, Qt.ElideRight, w))
        else:
            ir = QRect(r.x() + 4, r.y() + (r.height() - c) // 2, c, c)
            if isinstance(icon, QIcon) and not icon.isNull():
                icon.paint(p, ir)
            x = ir.right() + 10
            w = r.right() - x - 4
            block = tm.height() + sm.height()
            y = r.y() + (r.height() - block) // 2
            p.setFont(tf)
            p.setPen(tcol)
            p.drawText(QRect(x, y, w, tm.height()), Qt.AlignLeft | Qt.AlignVCenter, tm.elidedText(title, Qt.ElideRight, w))
            p.setFont(sf)
            p.setPen(th.color("muted"))
            p.drawText(QRect(x, y + tm.height(), w, sm.height()), Qt.AlignLeft | Qt.AlignVCenter,
                       sm.elidedText(sub, Qt.ElideRight, w))
        p.restore()

    def sizeHint(self, opt, index):
        c = self.owner.pic
        if self.owner.view == "covers":
            return QSize(c + 12, c + 44)
        return QSize(opt.rect.width() or 200, max(c + 8, 38))


class AlbumList(QWidget):
    albumPicked = Signal(str, str)  # artist, album
    playRequested = Signal(list, int)  # track ids, start
    queueRequested = Signal(list)
    artistRequested = Signal(str)
    allAlbumsRequested = Signal()
    optionsChanged = Signal()

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.view, self.sort = "list", "artist"
        self.filter_box = True
        self.fill = False
        self.cover_provider = None  # (track, px) -> QImage | None
        self._groups: list[dict] = []
        self._by_key: dict[str, dict] = {}
        self._key_of: dict[int, str] = {}  # track id -> album key
        self.current = ""  # key of the album playing
        self._sig = None
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        head = QHBoxLayout()
        self.label = QLabel("ALBUMS")
        self.label.setObjectName("NowSectionLabel")
        head.addWidget(self.label)
        head.addStretch()
        self.count = QLabel("")
        self.count.setObjectName("NowMeta")
        head.addWidget(self.count)
        v.addLayout(head)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter albums and artists…")
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(lambda _: self._fill())
        v.addWidget(self.filter)
        self.list = QListWidget()
        self.list.setObjectName("UpNext")
        self.list.setFrameShape(QFrame.NoFrame)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.setMouseTracking(True)
        self.list.setItemDelegate(_Delegate(self))
        self.list.setToolTip("Click an album to show it in the library, double-click to play it. "
                             "Right-click for more — view, sorting.")
        self.list.itemClicked.connect(self._clicked)
        self.list.itemDoubleClicked.connect(self._double_clicked)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        self.list.setMinimumHeight(60)
        v.addWidget(self.list, 1)
        self._pic_timer = QTimer(self, singleShot=True, interval=60)
        self._pic_timer.timeout.connect(self._load_visible)
        self.list.verticalScrollBar().valueChanged.connect(lambda _: self._pic_timer.start())
        self._click_timer = QTimer(self, singleShot=True, interval=240)
        self._click_timer.timeout.connect(self._single_click)
        self._click_item = None
        self._apply_view()

    def options(self) -> dict:
        return {"view": self.view, "sort": self.sort, "filter_box": self.filter_box, "fill": self.fill}

    def set_options(self, d):
        d = d if isinstance(d, dict) else {}
        view = d.get("view") if d.get("view") in VIEWS else "list"
        sort = d.get("sort") if d.get("sort") in SORTS else "artist"
        self.filter_box = bool(d.get("filter_box", True))
        self.fill = bool(d.get("fill", False))
        self._apply_filter_box()
        if (view, sort) != (self.view, self.sort):
            self.view, self.sort = view, sort
            self._apply_view()
            self._fill()

    def _apply_filter_box(self):
        self.filter.setVisible(self.filter_box)
        if not self.filter_box and self.filter.text():
            self.filter.clear()

    def _set(self, **kw):
        for k, val in kw.items():
            setattr(self, k, val)
        if "filter_box" in kw:
            self._apply_filter_box()
        if "view" in kw:
            self._apply_view()
        self._fill()
        self.optionsChanged.emit()

    @property
    def pic(self) -> int:
        return PIC.get(self.view, 40)

    def _apply_view(self):
        p = self.pic
        self.list.setIconSize(QSize(p, p))
        if self.view == "covers":
            self.list.setViewMode(QListView.IconMode)
            self.list.setResizeMode(QListView.Adjust)
            self.list.setMovement(QListView.Static)
            self.list.setWrapping(True)
            self.list.setSpacing(4)
            self.list.setGridSize(QSize(p + 18, p + 46))
            self.list.setStyleSheet("QListWidget{background:transparent;} QListWidget::item{background:transparent;}")
        else:
            self.list.setViewMode(QListView.ListMode)
            self.list.setWrapping(False)
            self.list.setSpacing(0)
            self.list.setGridSize(QSize())
            self.list.setStyleSheet("QListWidget{background:transparent;} QListWidget::item{background:transparent;}")
        for i in range(self.list.count()):
            it = self.list.item(i)
            it.setData(LOADED, False)
            it.setIcon(QIcon())
            self._shape(it)
        self._pic_timer.start()

    def _shape(self, it: QListWidgetItem):
        a = self._by_key.get(it.data(KEY))
        if not a:
            return
        title = a["album"] or "Unknown Album"
        sub = " · ".join(b for b in (a["artist"] or "Unknown Artist", str(a["year"]) if a["year"] else "") if b)
        it.setText(title)
        it.setData(SUB, (a["artist"] or "Unknown Artist") if self.view == "covers" else sub)
        it.setSizeHint(QSize(self.pic + 12, self.pic + 44) if self.view == "covers" else QSize(-1, max(self.pic + 8, 38)))

    def set_tracks(self, tracks):
        tracks = [t for t in tracks if not (t.get("stream") or t.get("remote"))]
        sig = (len(tracks), sum(t["id"] for t in tracks), sum(t.get("playcount") or 0 for t in tracks),
               hash(tuple((t.get("album"), t.get("artist_key"), t.get("albumartist")) for t in tracks)))
        if sig == self._sig:
            return  # nothing visible changed
        self._sig = sig
        self._groups = album_groups(tracks)
        self._key_of = {t["id"]: a["key"] for a in self._groups for t in a["tracks"]}
        self._fill()

    def _sorted(self, groups):
        s = self.sort
        if s == "album":
            return sorted(groups, key=lambda a: (sort_name(a["album"] or "~"), sort_name(a["artist"])))
        if s == "year":
            return sorted(groups, key=lambda a: (-(a["year"] or 0), sort_name(a["artist"])))
        if s == "year_old":
            return sorted(groups, key=lambda a: (a["year"] or 9999, sort_name(a["artist"])))
        if s == "added":
            return sorted(groups, key=lambda a: -a["added"])
        if s == "plays":
            return sorted(groups, key=lambda a: (-a["plays"], sort_name(a["artist"])))
        return sorted(groups, key=lambda a: (sort_name(a["artist"] or "~"), a["year"] or 9999, sort_name(a["album"])))

    def _fill(self):
        words = [w for w in self.filter.text().lower().split() if w]
        groups = [a for a in self._groups
                  if all(w in (a["album"] + " " + a["artist"] + " " + " ".join(a["artists"])).lower() for w in words)]
        self._by_key = {a["key"]: a for a in self._groups}
        bar = self.list.verticalScrollBar().value()
        self.list.setUpdatesEnabled(False)
        self.list.clear()
        for a in self._sorted(groups):
            it = QListWidgetItem()
            it.setData(KEY, a["key"])
            it.setData(TRACK, a["track"])
            who = a["artist"] + (f" — {', '.join(a['artists'][:6])}{'…' if len(a['artists']) > 6 else ''}"
                                 if a["various"] else "")
            it.setToolTip(f"{a['album'] or 'Unknown Album'}\n{who}\n{a['songs']} songs · {fmt_time(a['length'])}"
                          + (f" · {a['discs']} CDs" if a.get("discs", 1) > 1 else "")
                          + (f" · {a['year']}" if a["year"] else "") + "\nDouble-click to play")
            self._shape(it)
            self.list.addItem(it)
        self.list.setUpdatesEnabled(True)
        self.list.verticalScrollBar().setValue(bar)
        n, total = len(groups), len(self._groups)
        self.count.setText(f"{n:,} of {total:,}" if words else f"{total:,}")
        self._mark()
        self._pic_timer.start()

    def set_track(self, t):
        key = self._key_of.get(t["id"], "") if (t and not t.get("stream") and not t.get("remote")) else ""
        if key != self.current:
            self.current = key
            self._mark()

    def _mark(self):
        for i in range(self.list.count()):
            it = self.list.item(i)
            playing = bool(self.current) and it.data(KEY) == self.current
            f = QFont(self.list.font())
            f.setBold(playing)
            it.setFont(f)
            it.setForeground(self.theme.color("accent") if playing else self.theme.color("text"))

    def scroll_to_current(self):
        for i in range(self.list.count()):
            if self.list.item(i).data(KEY) == self.current:
                self.list.scrollToItem(self.list.item(i), QAbstractItemView.PositionAtCenter)
                self.list.setCurrentRow(i)
                return

    def _clicked(self, it):
        self._click_item = it
        self._click_timer.start()

    def _single_click(self):
        a = self._by_key.get(self._click_item.data(KEY)) if self._click_item else None
        if a:
            self.albumPicked.emit("" if a["various"] else a["artist"], a["album"])

    def _double_clicked(self, it):
        self._click_timer.stop()
        self._play(it.data(KEY), False)

    def _ids(self, key) -> list[int]:
        a = self._by_key.get(key)
        return [t["id"] for t in sorted(a["tracks"], key=_album_order)] if a else []

    def _play(self, key, shuffle: bool):
        ids = self._ids(key)
        if shuffle:
            random.shuffle(ids)
        if ids:
            self.playRequested.emit(ids, 0)

    picture_actions = None  # (kind, name, track) -> [(label, fn)], set by the window

    def _view_menu(self, m: QMenu):
        from musicwell.menus import check
        vm = m.addMenu("View")
        for k, text in VIEWS.items():
            check(vm, text, self.view == k, lambda k=k: self._set(view=k))
        sm = m.addMenu("Sort by")
        for k, text in SORTS.items():
            check(sm, text, self.sort == k, lambda k=k: self._set(sort=k))
        m.addSeparator()
        check(m, "Filter box", self.filter_box, lambda: self._set(filter_box=not self.filter_box))
        check(m, "Fill the panel", self.fill, lambda: self._set(fill=not self.fill))

    def _menu(self, pos):
        from musicwell.menus import esc, title, tidy
        it = self.list.itemAt(pos)
        m = QMenu(self)
        if it is not None:
            key = it.data(KEY)
            a = self._by_key.get(key)
            title(m, (a["album"] if a else "") or "Unknown Album")
            m.addAction("Play", lambda: self._play(key, False))
            m.addAction("Shuffle", lambda: self._play(key, True))
            m.addAction("Add to queue", lambda: self.queueRequested.emit(self._ids(key)))
            m.addSeparator()
            if a and a["various"]:
                am = m.addMenu("Artists on this album")
                for n in sorted(a["artists"], key=str.lower)[:40]:
                    am.addAction(esc(n), lambda n=n: self.artistRequested.emit(n))
            elif a and a["artist"]:
                m.addAction("Go to artist", lambda: self.artistRequested.emit(a["artist"]))
            if a and self.picture_actions and a.get("track"):
                im = m.addMenu("Image")
                from musicwell.menus import add_actions
                add_actions(im, self.picture_actions("album", a["artist"] or a["album"], a["track"]))
            m.addSeparator()
        if self.current:
            m.addAction("Show the album playing", self.scroll_to_current)
        m.addAction("All albums (big covers)", self.allAlbumsRequested)
        if it is not None:
            self._view_menu(m.addMenu("List options"))
        else:
            m.addSeparator()
            self._view_menu(m)
        tidy(m)
        from musicwell.widgets import add_menu_extras
        add_menu_extras(self, m)
        m.exec(self.list.viewport().mapToGlobal(pos))

    def _load_visible(self):
        if not self.isVisible() or not self.list.count():
            return
        dpr = self.devicePixelRatioF() or 1.0
        c = self.pic
        vp = self.list.viewport().rect().adjusted(0, -c * 2, 0, c * 3)
        from musicwell.artwork import placeholder
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(LOADED) or not self.list.visualItemRect(it).intersects(vp):
                continue
            t = it.data(TRACK)
            img = self.cover_provider(t, int(c * dpr)) if (self.cover_provider and t) else None
            radius = 4 if c < 60 else 6
            if img is not None and not img.isNull():
                it.setIcon(QIcon(_rounded(img, c, dpr, radius)))
                it.setData(LOADED, True)
            elif it.icon().isNull():
                a = self._by_key.get(it.data(KEY))
                ph = placeholder(int(c * dpr), (a and a["album"]) or "?", QColor(self.theme.accent))
                it.setIcon(QIcon(_rounded(ph, c, dpr, radius)))

    def cover_ready(self, key: str):
        from musicwell.artwork import album_key
        hit = False
        for i in range(self.list.count()):
            t = self.list.item(i).data(TRACK)
            if t and album_key(t) == key:
                self.list.item(i).setData(LOADED, False)
                hit = True
        if hit:
            self._pic_timer.start()

    def reload_pictures(self):
        for i in range(self.list.count()):
            self.list.item(i).setData(LOADED, False)
            self.list.item(i).setIcon(QIcon())
        self._pic_timer.start()

    def refresh_theme(self):
        self._mark()
        self.reload_pictures()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._pic_timer.start()

    def showEvent(self, e):
        super().showEvent(e)
        self._pic_timer.start()
