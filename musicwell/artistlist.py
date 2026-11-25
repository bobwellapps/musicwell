"""The artist list panel item: every artist with photo and counts; expand one to see their albums."""
from __future__ import annotations

import re

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QImage, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu,
                               QStyle, QStyledItemDelegate, QStyleOptionViewItem, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

KINDS = {"album": "Album artists (or artist)", "track": "Track artists"}
SORTS = {"name": "A–Z", "songs": "Most songs", "plays": "Most played", "recent": "Recently added"}
SIZES = {"small": ("Small", 34), "medium": ("Medium", 48), "large": ("Large", 64), "xl": ("Extra large", 96)}


def _n(count: int, word: str) -> str:
    return f"{count:,} {word}{'' if count == 1 else 's'}"


class _TwoLines(QStyledItemDelegate):
    """Name with a smaller second line ("3 albums · 42 songs")."""

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner

    def _fonts(self, font: QFont):
        small = QFont(font)
        small.setPointSizeF(max(6.0, font.pointSizeF() * 0.86))
        small.setBold(False)
        return small

    def sizeHint(self, opt, idx):
        s = super().sizeHint(opt, idx)
        if idx.data(SUB):
            o = QStyleOptionViewItem(opt)
            self.initStyleOption(o, idx)
            h = QFontMetrics(o.font).height() + QFontMetrics(self._fonts(o.font)).height() + 8
            s.setHeight(max(s.height(), h))
        return s

    def paint(self, p, opt, idx):
        sub = idx.data(SUB)
        if not sub:
            return super().paint(p, opt, idx)
        o = QStyleOptionViewItem(opt)
        self.initStyleOption(o, idx)
        name = o.text
        o.text = ""
        style = o.widget.style() if o.widget else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, o, p, o.widget)
        r = style.subElementRect(QStyle.SE_ItemViewItemText, o, o.widget)
        small = self._fonts(o.font)
        fm, fm2 = QFontMetrics(o.font), QFontMetrics(small)
        top = r.top() + (r.height() - fm.height() - fm2.height()) // 2
        fg = idx.data(Qt.ForegroundRole)
        main = fg.color() if hasattr(fg, "color") else QColor(fg) if fg is not None else o.palette.text().color()
        if o.state & QStyle.State_Selected:
            main = o.palette.highlightedText().color()
        theme = getattr(self.owner, "theme", None)
        dim = QColor(theme.color("muted")) if theme is not None else QColor(main)
        if o.state & QStyle.State_Selected:
            dim = QColor(main)
            dim.setAlphaF(0.75)
        p.save()
        p.setFont(o.font)
        p.setPen(main)
        p.drawText(QRect(r.left(), top, r.width(), fm.height()), Qt.AlignLeft | Qt.AlignVCenter,
                   fm.elidedText(name, Qt.ElideRight, r.width()))
        p.setFont(small)
        p.setPen(dim)
        p.drawText(QRect(r.left(), top + fm.height(), r.width(), fm2.height()), Qt.AlignLeft | Qt.AlignVCenter,
                   fm2.elidedText(sub, Qt.ElideRight, r.width()))
        p.restore()


def sort_name(name: str) -> str:
    """'The Beatles' sorts under B; case and accents are ignored."""
    import unicodedata
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower().strip() or name.lower()
    return re.sub(r"^(the|a|an|les|la|le|die|der|das)\s+", "", n)


def artist_rows(tracks, kind: str = "album") -> list[dict]:
    """One row per artist: {name, songs, plays, added, path, albums: {album: {...}}}. Songs without an artist are skipped."""
    rows: dict[str, dict] = {}
    key = "artist_key" if kind == "album" else "artist"
    for t in tracks:
        name = (t.get(key) or "").strip()
        if not name:
            continue
        r = rows.get(name.lower())
        if r is None:
            r = rows[name.lower()] = {"name": name, "songs": 0, "plays": 0, "added": 0, "path": t.get("path", ""),
                                      "albums": {}}
        r["songs"] += 1
        r["plays"] += t.get("playcount") or 0
        r["added"] = max(r["added"], t.get("added") or 0)
        album = (t.get("album") or "").strip()
        a = r["albums"].get(album.lower())
        if a is None:
            a = r["albums"][album.lower()] = {"album": album, "year": 0, "songs": 0, "plays": 0, "track": t}
        a["songs"] += 1
        a["plays"] += t.get("playcount") or 0
        y = t.get("origyear") or t.get("year") or 0
        if y and (not a["year"] or y < a["year"]):
            a["year"] = y
    return list(rows.values())


ALL_ALBUMS = "\x00albums"  # the "All albums" row
ALL_SONGS = "\x00songs"  # the "All artists" row: every song
TOP_ROWS = (ALL_SONGS, ALL_ALBUMS)
NAME = Qt.UserRole  # artist name (artist and album rows)
LOADED = Qt.UserRole + 1  # picture loaded
PATH = Qt.UserRole + 2  # one of the artist's songs, for artist.jpg next to the music
ALBUM = Qt.UserRole + 3  # album name ("" for songs without one)
TRACK = Qt.UserRole + 4  # one of the album's songs, for the cover
FILLED = Qt.UserRole + 5  # album rows added
SUB = Qt.UserRole + 7  # second line text
HOLDER = Qt.UserRole + 6  # showing initials while the picture loads


def _icon(img: QImage, size: int, dpr: float, round_: bool) -> QIcon:
    px = int(size * dpr)
    out = QPixmap(px, px)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    path = QPainterPath()
    if round_:
        path.addEllipse(QRectF(0, 0, px, px))
    else:
        r = max(3.0, px * 0.08)
        path.addRoundedRect(QRectF(0, 0, px, px), r, r)
    p.setClipPath(path)
    p.drawImage(QRectF(0, 0, px, px), img)
    p.end()
    out.setDevicePixelRatio(dpr)
    return QIcon(out)


class ArtistList(QWidget):
    picked = Signal(str, str)  # name, kind ("album" | "track")
    playRequested = Signal(str, str, bool)  # name, kind, shuffle
    queueRequested = Signal(str, str)
    similarRequested = Signal(str)
    onlineRequested = Signal(str)
    browseRequested = Signal(str, str)  # name, kind
    allAlbumsRequested = Signal()
    allSongsRequested = Signal()
    allSongsPlayRequested = Signal(bool)  # shuffle
    albumPicked = Signal(str, str, str)  # artist, album, kind
    albumPlayRequested = Signal(str, str, str, bool)  # artist, album, kind, shuffle
    albumQueueRequested = Signal(str, str, str)
    optionsChanged = Signal()

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.kind, self.sort, self.counts, self.pictures, self.size = "album", "name", True, True, "small"
        self.filter_box, self.all_albums = True, True
        self.all_songs = True
        self.song_count = None  # set by the window
        self.fill = False
        self.image_provider = None  # (name, track path, px) -> QImage | None
        self.cover_provider = None  # (track, px) -> QImage | None
        self.picture_actions = None  # (kind, name, track) -> [(label, fn)]
        self._placeholders: dict[tuple, QIcon] = {}
        self.album_count = None  # set by the window
        self._expanded: set[str] = set()
        self.current = ""
        self.current_album = ""
        self._rows: list[dict] = []
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        head = QHBoxLayout()
        self.label = QLabel("ARTISTS")
        self.label.setObjectName("NowSectionLabel")
        head.addWidget(self.label)
        head.addStretch()
        self.count = QLabel("")
        self.count.setObjectName("NowMeta")
        head.addWidget(self.count)
        v.addLayout(head)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter artists and albums…")
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(lambda _: self._fill())
        v.addWidget(self.filter)
        self.list = QTreeWidget()
        self.list.setObjectName("UpNext")
        self.list.setHeaderHidden(True)
        self.list.setColumnCount(1)
        self.list.setFrameShape(QFrame.NoFrame)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setUniformRowHeights(False)
        self.list.setIndentation(16)
        self.list.setItemDelegate(_TwoLines(self))
        self.list.setRootIsDecorated(False)
        self.list.setExpandsOnDoubleClick(False)
        self.list.setAnimated(True)
        self.list.setToolTip("Click an artist to open their page (albums and songs) in the main window, "
                             "double-click to play them. Right-click for more — sorting, which artists, picture size.")
        self.list.itemClicked.connect(self._clicked)
        self.list.itemDoubleClicked.connect(self._double_clicked)
        self.list.itemExpanded.connect(self._on_expanded)
        self.list.itemCollapsed.connect(lambda it: self._expanded.discard(it.data(0, NAME).lower())
                                        if not it.data(0, ALBUM) and it.parent() is None else None)
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
        self._apply_pictures()
        self.image_taker = None  # (kind, name, track, dropped data)

        def _row_at(pos):  # an image dropped on an artist or album row
            it = self.list.itemAt(pos)
            if it is None or it.data(0, NAME) in TOP_ROWS:
                return None
            if it.parent() is not None:
                return ("album", it.data(0, NAME), it.data(0, TRACK)) if it.data(0, TRACK) else None
            return ("artist", it.data(0, NAME), self._a_song(it.data(0, NAME)))
        from musicwell import webimage as WI
        WI.DropTarget(self.list.viewport(), _row_at, lambda: self.image_taker)

    def options(self) -> dict:
        return {"kind": self.kind, "sort": self.sort, "counts": self.counts, "pictures": self.pictures,
                "size": self.size, "filter_box": self.filter_box, "all_albums": self.all_albums,
                "all_songs": self.all_songs, "fill": self.fill}

    def set_options(self, d):
        if not isinstance(d, dict):
            return
        self.kind = d.get("kind") if d.get("kind") in KINDS else "album"
        self.sort = d.get("sort") if d.get("sort") in SORTS else "name"
        self.counts = bool(d.get("counts", True))
        self.pictures = bool(d.get("pictures", True))
        self.size = d.get("size") if d.get("size") in SIZES else "small"
        self.filter_box = bool(d.get("filter_box", True))
        self.all_albums = bool(d.get("all_albums", True))
        self.all_songs = bool(d.get("all_songs", True))
        self.fill = bool(d.get("fill", False))
        self._apply_filter_box()
        self._apply_pictures()
        self._fill()

    def _apply_filter_box(self):
        self.filter.setVisible(self.filter_box)
        if not self.filter_box and self.filter.text():
            self.filter.clear()

    @property
    def pic(self) -> int:
        return SIZES[self.size][1]

    def _apply_pictures(self):
        px = self.pic if self.pictures else 0
        self.list.setIconSize(QSize(px, px))
        pad = "2px 2px" if self.pictures else "3px 2px"
        self.list.setStyleSheet("QTreeWidget{background:transparent;} "
                                f"QTreeWidget::item{{padding:{pad};}}")
        f = QFont(self.list.font())
        if self.pictures and self.pic >= 64:
            f.setPointSizeF(max(f.pointSizeF(), 10.5))
        self.list.setFont(f)

    def _set(self, **kw):
        for k, val in kw.items():
            setattr(self, k, val)
        if "filter_box" in kw:
            self._apply_filter_box()
        if "all_albums" in kw or "all_songs" in kw:
            self._fill()
        if "pictures" in kw or "size" in kw:
            self._placeholders.clear()
            self._apply_pictures()
            self._fill()
        self.optionsChanged.emit()
        self.set_track(self._track)

    def _artists(self) -> list[QTreeWidgetItem]:
        return [self.list.topLevelItem(i) for i in range(self.list.topLevelItemCount())]

    def _all_items(self):
        for it in self._artists():
            yield it
            for j in range(it.childCount()):
                yield it.child(j)

    def set_rows(self, rows: list[dict]):
        self._rows = rows
        self._fill()

    def set_current(self, name: str, album: str = ""):
        self.current = name or ""
        self.current_album = album or ""
        self._mark()

    def show_name(self, name: str):
        """Select an artist's row and scroll to it."""
        self._wanted = name or ""  # remembered so a refill (often after a layout switch)
        want = self._wanted.lower()  # selects it again
        for it in self._artists():
            if (it.data(0, NAME) or "").strip().lower() == want.strip():
                self.list.setCurrentItem(it)
                it.setSelected(True)
                self._scroll_to(it)
                return True
        return False

    _wanted = ""

    def _scroll_to(self, it):
        """Scroll the artist to the top, now and again after layout."""
        def go():
            try:
                self.list.scrollToItem(it, QAbstractItemView.PositionAtTop)
            except RuntimeError:  # row replaced by a refill
                return
        go()
        QTimer.singleShot(0, go)
        QTimer.singleShot(250, go)

    _track = None

    def set_track(self, t):
        """Mark the playing song's artist and album."""
        self._track = t
        if not t or t.get("stream"):
            self.set_current("")
            return
        self.set_current((t.get("artist_key") if self.kind == "album" else t.get("artist")) or "",
                         (t.get("album") or "") if not t.get("remote") else "")

    def _sorted(self, rows):
        if self.sort == "songs":
            return sorted(rows, key=lambda r: (-r["songs"], sort_name(r["name"])))
        if self.sort == "plays":
            return sorted(rows, key=lambda r: (-r["plays"], sort_name(r["name"])))
        if self.sort == "recent":
            return sorted(rows, key=lambda r: (-r["added"], sort_name(r["name"])))
        return sorted(rows, key=lambda r: sort_name(r["name"]))

    def _count_text(self, songs: int, plays: int, albums: int | None = None) -> str:
        """Second line text under a name."""
        if not self.counts:
            return ""
        bits = []
        if albums is not None:
            bits.append(_n(albums, "album"))
        bits.append(_n(songs, "song"))
        if self.sort == "plays":
            bits.append(_n(plays, "play"))
        return " · ".join(bits)

    def _fill(self):
        words = [w for w in self.filter.text().lower().split() if w]

        def matches(r):
            if all(w in r["name"].lower() for w in words):
                return "artist"
            hay = r["name"].lower() + " " + " ".join(a["album"].lower() for a in r.get("albums", {}).values())
            return "album" if all(w in hay for w in words) else ""
        found = [(r, matches(r)) for r in self._rows] if words else [(r, "artist") for r in self._rows]
        found = [(r, m) for r, m in found if m]
        cur = self.list.currentItem()
        sel = (cur.data(0, NAME), cur.data(0, ALBUM)) if cur else None
        if self._wanted:
            sel = (next((r["name"] for r in self._rows if r["name"].lower() == self._wanted.lower()), self._wanted),
                   None)
        self.list.setUpdatesEnabled(False)
        self.list.clear()
        if not words and self.all_songs:
            n_songs = self.song_count if self.song_count is not None else sum(r["songs"] for r in self._rows)
            top = QTreeWidgetItem(["All artists"])
            if self.counts:
                top.setData(0, SUB, _n(n_songs, "song"))
            top.setData(0, NAME, ALL_SONGS)
            top.setData(0, ALBUM, None)
            top.setToolTip(0, "Every song in your library, in the song list (double-click to play them all)")
            f = QFont(self.list.font())
            f.setBold(True)
            top.setFont(0, f)
            self.list.addTopLevelItem(top)
        if not words and self.all_albums:
            n_albums = self.album_count if self.album_count is not None else \
                len({(r["name"].lower(), k) for r in self._rows for k in r.get("albums", {})})
            top = QTreeWidgetItem(["All albums"])
            if self.counts:
                top.setData(0, SUB, _n(n_albums, "album"))
            top.setData(0, NAME, ALL_ALBUMS)
            top.setData(0, ALBUM, None)
            top.setToolTip(0, "Every album in your library, as covers, in the main window")
            f = QFont(self.list.font())
            f.setBold(True)
            top.setFont(0, f)
            self.list.addTopLevelItem(top)
        picked = None
        blank = self._blank_icon() if self.pictures else None
        for r in self._sorted([r for r, _ in found]):
            n = r["songs"]
            it = QTreeWidgetItem([r["name"]])
            it.setData(0, SUB, self._count_text(n, r["plays"], len(r.get("albums", {}))))
            it.setData(0, NAME, r["name"])
            it.setData(0, PATH, r.get("path", ""))
            it.setData(0, ALBUM, None)
            na = len(r.get("albums", {}))
            it.setToolTip(0, f"{r['name']}\n{n:,} song{'s' if n != 1 else ''} on {na} album{'s' if na != 1 else ''}"
                             f" · played {r['plays']:,} time{'s' if r['plays'] != 1 else ''}")
            it.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.DontShowIndicator)
            if blank is not None:
                it.setIcon(0, blank)  # give every row its full height now
            self.list.addTopLevelItem(it)
            if sel and sel == (r["name"], None):
                self.list.setCurrentItem(it)
                it.setSelected(True)
                picked = it
        self.list.setUpdatesEnabled(True)
        if picked is not None:
            self._scroll_to(picked)
        total = len(self._rows)
        self.count.setText(f"{len(found):,} of {_n(total, 'artist')}" if words else (_n(total, "artist") if total else ""))
        self.label.setText("ALBUM ARTISTS" if self.kind == "album" else "ARTISTS")
        self._mark()
        if self.pictures:
            self._pic_timer.start()

    def _row(self, name: str) -> dict | None:
        n = name.lower()
        return next((r for r in self._rows if r["name"].lower() == n), None)

    def _fill_albums(self, it: QTreeWidgetItem):
        if it.data(0, FILLED):
            return
        it.setData(0, FILLED, True)
        r = self._row(it.data(0, NAME))
        if not r:
            return
        albums = sorted(r.get("albums", {}).values(),
                        key=lambda a: (a["year"] or 9999, sort_name(a["album"] or "~")))
        for a in albums:
            title = a["album"] or "Unknown Album"
            year = f"  ·  {a['year']}" if a["year"] else ""
            ch = QTreeWidgetItem([title])
            sub = self._count_text(a["songs"], a["plays"])
            ch.setData(0, SUB, (f"{a['year']} · " if a["year"] and sub else f"{a['year']}" if a["year"] else "") + sub)
            ch.setData(0, NAME, r["name"])
            ch.setData(0, ALBUM, a["album"])
            ch.setData(0, TRACK, a["track"])
            n = a["songs"]
            ch.setToolTip(0, f"{title}{year}\n{n} song{'s' if n != 1 else ''} · double-click to play")
            if self.pictures:
                ch.setIcon(0, self._blank_icon())
            it.addChild(ch)
        self._mark()

    def _on_expanded(self, it):
        if it.parent() is None:
            self._expanded.add(it.data(0, NAME).lower())
            self._fill_albums(it)
            self._pic_timer.start()

    # A single click waits briefly in case it's a double-click.
    def _clicked(self, it, _col=0):
        self._click_item = it
        self._click_timer.start()

    def _single_click(self):
        it, self._click_item = self._click_item, None
        if it is not None and it.parent() is None:
            self._wanted = it.data(0, NAME) if it.data(0, NAME) not in TOP_ROWS else ""
        if it is None:
            return
        name = it.data(0, NAME)
        if name == ALL_SONGS:
            self.allSongsRequested.emit()
        elif name == ALL_ALBUMS:
            self.allAlbumsRequested.emit()
        elif it.parent() is None:
            self.picked.emit(name, self.kind)
        else:
            self.albumPicked.emit(name, it.data(0, ALBUM) or "", self.kind)

    def _double_clicked(self, it, _col=0):
        self._click_timer.stop()
        self._click_item = None
        name = it.data(0, NAME)
        if it.parent() is None:
            self._wanted = name if name not in TOP_ROWS else ""
        if name == ALL_SONGS:
            self.allSongsRequested.emit()
            self.allSongsPlayRequested.emit(False)
        elif name == ALL_ALBUMS:
            self.allAlbumsRequested.emit()
        elif it.parent() is None:
            self.playRequested.emit(name, self.kind, False)
        else:
            self.albumPlayRequested.emit(name, it.data(0, ALBUM) or "", self.kind, False)

    def _mark(self):
        """Show the playing artist and album in the accent colour."""
        cur, alb = self.current.lower(), self.current_album.lower()
        for it in self._all_items():
            if it.data(0, NAME) in TOP_ROWS:
                continue
            is_album = it.parent() is not None
            playing = bool(cur) and it.data(0, NAME).lower() == cur and (
                not is_album or (it.data(0, ALBUM) or "").lower() == alb)
            f = QFont(self.list.font())
            f.setBold(playing)
            it.setFont(0, f)
            it.setForeground(0, self.theme.color("accent") if playing else
                             self.theme.color("muted" if is_album else "text"))

    def _blank_icon(self) -> QIcon:
        """Empty icon the size of real ones, so row heights don't change as pictures load."""
        dpr = self.devicePixelRatioF() or 1.0
        key = (self.pic, dpr)
        if getattr(self, "_blank", (None, None))[0] != key:
            px = QPixmap(int(self.pic * dpr), int(self.pic * dpr))
            px.fill(Qt.transparent)
            px.setDevicePixelRatio(dpr)
            self._blank = (key, QIcon(px))
        return self._blank[1]

    def _placeholder(self, text: str, round_: bool) -> QIcon:
        key = (text, round_)
        ic = self._placeholders.get(key)
        if ic is None:
            from musicwell.artwork import placeholder
            dpr = self.devicePixelRatioF() or 1.0
            ic = _icon(placeholder(int(self.pic * dpr), text, QColor(self.theme.accent)), self.pic, dpr, round_)
            self._placeholders[key] = ic
        return ic

    def _visible_items(self):
        vp = self.list.viewport().rect()
        it = self.list.itemAt(QPoint(4, 2))
        if it is None:
            it = self.list.topLevelItem(0)
        before = it
        for _ in range(4):
            up = self.list.itemAbove(before) if before is not None else None
            if up is None:
                break
            before = up
        it, n = before, 0
        while it is not None:
            yield it
            r = self.list.visualItemRect(it)
            if r.top() > vp.bottom():
                n += 1
                if n > 6:
                    break
            it = self.list.itemBelow(it)

    def _picture_menu(self, m, kind: str, name: str, track):
        """Image menu: search, use your own, or back to automatic."""
        if not self.picture_actions:
            return
        acts = self.picture_actions(kind, name, track)
        if acts:
            from musicwell.menus import add_actions
            add_actions(m.addMenu("Image"), acts)

    def _a_song(self, name: str):
        """One of the artist's songs (their photo can come from its folder)."""
        r = next((r for r in self._rows if r["name"] == name), None)
        if not r or not r.get("albums"):
            return None
        return next(iter(r["albums"].values()))["track"]

    def _load_visible(self):
        """Load pictures for the rows on screen and a few either side."""
        if not self.pictures or not self.list.topLevelItemCount():
            return
        dpr = self.devicePixelRatioF() or 1.0
        px = int(self.pic * dpr)
        for it in self._visible_items():
            if it.data(0, LOADED):
                continue
            is_album = it.parent() is not None
            if it.data(0, NAME) in TOP_ROWS:
                it.setIcon(0, self._songs_icon(dpr) if it.data(0, NAME) == ALL_SONGS else self._albums_icon(dpr))
                it.setData(0, LOADED, True)
                continue
            if is_album:
                img = self.cover_provider(it.data(0, TRACK), px) if self.cover_provider and it.data(0, TRACK) else None
                text = it.data(0, ALBUM) or "?"
            else:
                img = self.image_provider(it.data(0, NAME), it.data(0, PATH) or "", px) if self.image_provider else None
                text = it.data(0, NAME)
            if img is not None and not img.isNull():
                it.setIcon(0, _icon(img, self.pic, dpr, False))
                it.setData(0, LOADED, True)
            elif not it.data(0, HOLDER):
                it.setIcon(0, self._placeholder(text, False))
                it.setData(0, HOLDER, True)

    def _albums_icon(self, dpr: float) -> QIcon:
        """2x2 grid icon for the All albums row."""
        px = int(self.pic * dpr)
        pm = QPixmap(px, px)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        acc = QColor(self.theme.accent)
        gap = max(2.0, px * 0.08)
        side = (px - gap) / 2
        for i, (x, y) in enumerate(((0, 0), (1, 0), (0, 1), (1, 1))):
            c = QColor(acc) if i in (0, 3) else acc.darker(180)
            p.setBrush(c)
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRectF(x * (side + gap), y * (side + gap), side, side), px * 0.06, px * 0.06)
        p.end()
        pm.setDevicePixelRatio(dpr)
        return QIcon(pm)

    def _songs_icon(self, dpr: float) -> QIcon:
        """Three-figure icon for the All artists row."""
        px = int(self.pic * dpr)
        pm = QPixmap(px, px)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        acc = QColor(self.theme.accent)
        p.setPen(Qt.NoPen)
        p.setBrush(acc.darker(260))
        p.drawRoundedRect(QRectF(0, 0, px, px), px * 0.1, px * 0.1)
        p.setClipRect(QRectF(0, 0, px, px))
        for cx, cy, r, c in ((0.30, 0.40, 0.095, acc.darker(150)), (0.70, 0.40, 0.095, acc.darker(150)),
                             (0.50, 0.46, 0.12, acc)):
            head = r * px
            p.setBrush(c)
            p.drawEllipse(QRectF(cx * px - head, cy * px - head * 2.1, head * 2, head * 2))
            w = head * 1.75
            p.drawRoundedRect(QRectF(cx * px - w, cy * px + head * 0.15, w * 2, px), w * 0.8, w * 0.8)
        p.end()
        pm.setDevicePixelRatio(dpr)
        return QIcon(pm)

    def image_ready(self, name: str):
        from musicwell.artwork import primary_artist
        n = primary_artist(name).lower()
        hit = False
        for it in self._artists():
            if it.data(0, NAME) not in TOP_ROWS and primary_artist(it.data(0, NAME)).lower() == n:
                it.setData(0, LOADED, False)
                hit = True
        if hit:
            self._pic_timer.start()

    def cover_ready(self, key: str):
        from musicwell.artwork import album_key
        hit = False
        for it in self._all_items():
            t = it.data(0, TRACK)
            if t and album_key(t) == key:
                it.setData(0, LOADED, False)
                hit = True
        if hit:
            self._pic_timer.start()

    def reload_pictures(self):
        """Pictures changed (cache cleared, sources changed): reload."""
        self._placeholders.clear()
        blank = self._blank_icon() if self.pictures else QIcon()
        for it in self._all_items():
            it.setData(0, LOADED, False)
            it.setData(0, HOLDER, False)
            it.setIcon(0, blank)
        self._pic_timer.start()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._pic_timer.start()

    def showEvent(self, e):
        super().showEvent(e)
        self._pic_timer.start()

    def scroll_to_current(self):
        cur = self.current.lower()
        for it in self._artists():
            if it.data(0, NAME).lower() == cur:
                self.list.setCurrentItem(it)
                self.list.scrollToItem(it, QAbstractItemView.ScrollHint.PositionAtCenter)
                return True
        return False

    def _menu_title(self, m: QMenu, text: str):
        from musicwell.menus import title
        title(m, text)

    def _view_menu(self, m: QMenu):
        """View options: content, order, pictures, counts."""
        km = m.addMenu("Show")
        for k, text in KINDS.items():
            a = km.addAction(text, lambda k=k: self._set(kind=k))
            a.setCheckable(True)
            a.setChecked(self.kind == k)
        sm = m.addMenu("Sort by")
        for k, text in SORTS.items():
            a = sm.addAction(text, lambda k=k: self._set(sort=k))
            a.setCheckable(True)
            a.setChecked(self.sort == k)
        m.addSeparator()
        a = m.addAction("Pictures", lambda: self._set(pictures=not self.pictures))
        a.setCheckable(True)
        a.setChecked(self.pictures)
        zm = m.addMenu("Picture size")
        zm.setEnabled(self.pictures)
        for k, (text, px) in SIZES.items():
            a = zm.addAction(f"{text}", lambda k=k: self._set(size=k))
            a.setCheckable(True)
            a.setChecked(self.size == k)
        a = m.addAction("Album and song counts", lambda: self._set(counts=not self.counts))
        a.setCheckable(True)
        a.setChecked(self.counts)
        m.addSeparator()
        a = m.addAction("Filter box", lambda: self._set(filter_box=not self.filter_box))
        a.setCheckable(True)
        a.setChecked(self.filter_box)
        a = m.addAction("“All artists” row", lambda: self._set(all_songs=not self.all_songs))
        a.setCheckable(True)
        a.setChecked(self.all_songs)
        a.setToolTip("A row at the top for every song in your library")
        a = m.addAction("“All albums” row", lambda: self._set(all_albums=not self.all_albums))
        a.setCheckable(True)
        a.setChecked(self.all_albums)
        a = m.addAction("Fill the panel", lambda: self._set(fill=not self.fill))
        a.setCheckable(True)
        a.setChecked(self.fill)
        a.setToolTip("Use all the space below the other items instead of a box of its own height")
        m.setToolTipsVisible(True)


    def _menu(self, pos):
        """Right-click: actions for the artist or album first, then view options."""
        it = self.list.itemAt(pos)
        m = QMenu(self)
        m.setToolTipsVisible(True)
        if it is not None and it.data(0, NAME) == ALL_SONGS:
            self._menu_title(m, "All artists")
            m.addAction("Play all songs", lambda: (self.allSongsRequested.emit(), self.allSongsPlayRequested.emit(False)))
            m.addAction("Shuffle all songs", lambda: (self.allSongsRequested.emit(), self.allSongsPlayRequested.emit(True)))
            m.addAction("Show all songs", self.allSongsRequested.emit)
            m.addSeparator()
        elif it is not None and it.data(0, NAME) == ALL_ALBUMS:
            self._menu_title(m, "All albums")
            m.addAction("Show all albums", self.allAlbumsRequested.emit)
            m.addSeparator()
        elif it is not None and it.parent() is not None:  # an album
            name, album = it.data(0, NAME), it.data(0, ALBUM) or ""
            self._menu_title(m, album or "Unknown Album")
            m.addAction("Play album", lambda: self.albumPlayRequested.emit(name, album, self.kind, False))
            m.addAction("Shuffle album", lambda: self.albumPlayRequested.emit(name, album, self.kind, True))
            m.addAction("Add to queue", lambda: self.albumQueueRequested.emit(name, album, self.kind))
            m.addSeparator()
            self._picture_menu(m, "album", name, it.data(0, TRACK))
            m.addSeparator()
        elif it is not None:  # an artist
            name = it.data(0, NAME)
            label = name.replace("&", "&&")
            self._menu_title(m, name)
            m.addAction("Play", lambda: self.playRequested.emit(name, self.kind, False))
            m.addAction("Shuffle", lambda: self.playRequested.emit(name, self.kind, True))
            m.addAction("Add to queue", lambda: self.queueRequested.emit(name, self.kind))
            m.addSeparator()
            self._picture_menu(m, "artist", name, self._a_song(name))
            m.addSeparator()
            dm = m.addMenu("Discover")
            dm.addAction(f"Music like {label}", lambda: self.similarRequested.emit(name))
            dm.addAction(f"Search for {label}", lambda: self.onlineRequested.emit(name))
            m.addSeparator()
        if it is None:
            # empty space: view options only
            if self.current:
                m.addAction("Go to the artist playing", self.scroll_to_current)
                m.addSeparator()
            self._view_menu(m)
        else:
            if self.current:
                m.addAction("Go to the artist playing", self.scroll_to_current)
            self._view_menu(m.addMenu("List options"))
        from musicwell.widgets import add_menu_extras
        add_menu_extras(self, m)
        m.exec(self.list.viewport().mapToGlobal(pos))

    def refresh_theme(self):
        self._mark()
        if self._placeholders:  # initials in the new accent colour
            self._placeholders.clear()
            blank = self._blank_icon() if self.pictures else QIcon()
            for it in self._all_items():
                if not it.data(0, LOADED):
                    it.setIcon(0, blank)
                    it.setData(0, HOLDER, False)
            self._pic_timer.start()
