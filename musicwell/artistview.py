"""The artist page in the Library tab: photo, about, albums as covers and songs."""
from __future__ import annotations

import random

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QHBoxLayout, QLabel, QListView, QListWidget,
                               QListWidgetItem, QMenu, QPushButton, QSplitter, QVBoxLayout, QWidget)

from musicwell.models import fmt_time, library_order
from musicwell.widgets import SongTable


def keep_shuffled(old: list, ids: list) -> list:
    """The shuffled order kept for songs still listed; newly added songs go at the end, shuffled."""
    want = set(ids)
    kept = [i for i in old if i in want]
    have = set(kept)
    added = [i for i in ids if i not in have]
    random.shuffle(added)
    return kept + added


def _title(album) -> str:
    from musicwell.tags import album_title
    return album_title(album or "")

COVER_SIZES = {"xs": ("Extra small", 90), "small": ("Small", 120), "medium": ("Medium", 160), "large": ("Large", 210), "xl": ("Extra large", 260)}
PHOTO = 132
ALBUM, TRACK, LOADED = Qt.UserRole, Qt.UserRole + 1, Qt.UserRole + 2
ALL = "\x00all"  # the "All songs" tile


def _rounded(img: QImage, size: int, dpr: float, radius: float, circle: bool = False) -> QPixmap:
    px = int(size * dpr)
    out = QPixmap(px, px)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    path = QPainterPath()
    if circle:
        path.addEllipse(QRectF(0, 0, px, px))
    else:
        path.addRoundedRect(QRectF(0, 0, px, px), radius * dpr, radius * dpr)
    p.setClipPath(path)
    p.drawImage(QRectF(0, 0, px, px), img)
    p.end()
    out.setDevicePixelRatio(dpr)
    return out


class ArtistPage(QWidget):
    """Pick an album by clicking it, or several with +. While they play, + and - change what's playing (same as All albums)."""
    backRequested = Signal()
    playRequested = Signal(list, int)  # track ids, start
    listReplaced = Signal(list)  # the whole playing list after + / -
    queueRequested = Signal(list)
    similarRequested = Signal(str)
    onlineRequested = Signal(str)
    coverSizeChanged = Signal(str)

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.name, self.kind = "", "album"
        self.tracks: list[dict] = []
        self.album = ALL
        self._sel: list = []  # albums picked with +
        # Albums playing from here, in order: the first played on top, each added album underneath.
        self._list: list = []
        self._playing_ids: list = []  # their songs, in play order
        self._playing_keys: set = set()  # their albums (▶ on the covers)
        self._shuffled = False  # played with Shuffle: + and - keep the shuffled order
        self._button_click = None  # the click after + or - isn't "show this album"
        self._current_id = None
        self.cover_size = "medium"
        self.photo_provider = None  # (name, track path, px) -> QImage | None
        self.cover_provider = None  # (track, px) -> QImage | None
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 10, 16, 0)
        v.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(16)
        self.photo = QLabel()
        self.photo.setFixedSize(PHOTO, PHOTO)
        self.picture_actions = None  # (kind, name, track) -> [(label, fn)], set by the window
        self.photo.setContextMenuPolicy(Qt.CustomContextMenu)
        self.photo.customContextMenuRequested.connect(self._photo_menu)
        self.photo.setToolTip("Right-click to search for an artist image or use your own — or drag a picture here "
                              "from your web browser")
        self.image_taker = None  # (kind, name, track, dropped data), set by the window
        from musicwell import webimage as WI
        WI.DropTarget(self.photo, lambda _pos: ("artist", self.name, self.tracks[0] if self.tracks else None)
                      if self.name else None, lambda: self.image_taker)
        head.addWidget(self.photo, 0, Qt.AlignTop)
        info = QVBoxLayout()
        info.setSpacing(4)
        self.back_btn = QPushButton("←  Library")
        self.back_btn.setToolTip("Back to the library (Esc)")
        self.back_btn.setCursor(Qt.PointingHandCursor)
        self.back_btn.clicked.connect(self.backRequested)
        brow = QHBoxLayout()
        brow.addWidget(self.back_btn)
        brow.addStretch()
        info.addLayout(brow)
        kicker = QLabel("ARTIST")
        kicker.setObjectName("NowSectionLabel")
        info.addWidget(kicker)
        self.title = QLabel("")
        self.title.setObjectName("PageTitle")
        self.title.setStyleSheet("font-size: 22pt; font-weight: 700;")
        self.title.setWordWrap(True)
        info.addWidget(self.title)
        self.totals = QLabel("")
        self.totals.setObjectName("EmptyText")
        info.addWidget(self.totals)
        from musicwell.artistinfo import ArtistAbout
        self.about = ArtistAbout(theme)
        self.about.hide()
        info.addWidget(self.about)
        btns = QHBoxLayout()
        self.play_btn = QPushButton("Play")
        self.play_btn.setObjectName("Primary")
        self.play_btn.clicked.connect(lambda: self._play_shown(False))
        self.shuffle_btn = QPushButton("Shuffle")
        self.shuffle_btn.clicked.connect(lambda: self._play_shown(True))
        self.queue_btn = QPushButton("Add to queue")
        self.queue_btn.clicked.connect(lambda: self.queueRequested.emit(self.table.model_.ids()))
        self.similar_btn = QPushButton("Find similar")
        self.similar_btn.clicked.connect(lambda: self.similarRequested.emit(self.name))
        self.online_btn = QPushButton("Search online")
        self.online_btn.setToolTip("Their songs in the free online sources (Internet Archive, Openverse, Audius, "
                                   "your own sources)")
        self.online_btn.clicked.connect(lambda: self.onlineRequested.emit(self.name))
        for b in (self.play_btn, self.shuffle_btn, self.queue_btn, self.similar_btn, self.online_btn):
            btns.addWidget(b)
        btns.addStretch()
        info.addLayout(btns)
        info.addStretch()
        head.addLayout(info, 1)
        v.addLayout(head)

        self.split = QSplitter(Qt.Vertical)
        self.split.setChildrenCollapsible(False)
        top = QWidget()
        tl = QVBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(4)
        self.albums_label = QLabel("ALBUMS")
        self.albums_label.setObjectName("NowSectionLabel")
        tl.addWidget(self.albums_label)
        self.grid = QListWidget()
        self.grid.setObjectName("AlbumGrid")
        self.grid.setViewMode(QListView.IconMode)
        self.grid.setResizeMode(QListView.Adjust)
        self.grid.setMovement(QListView.Static)
        self.grid.setWrapping(True)
        self.grid.setSpacing(10)
        self.grid.setWordWrap(True)
        self.grid.setFrameShape(QFrame.NoFrame)
        self.grid.setSelectionMode(QAbstractItemView.SingleSelection)
        self.grid.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.grid.setToolTip("Click an album to see its songs below, double-click to play it. Right-click for more.")
        self.grid.setToolTip("Click an album for its songs below — + on covers to pick more than one, − to take "
                             "one out; double-click to play. Right-click for more.")
        self.grid.setMouseTracking(True)

        def _cover_at(pos):  # an image dropped on a cover belongs to that album
            it = self.grid.itemAt(pos)
            t = it.data(TRACK) if it is not None else None
            return ("album", self.name, t) if t else None
        WI.DropTarget(self.grid.viewport(), _cover_at, lambda: self.image_taker)
        from musicwell.albumsview import _TickDelegate
        self.grid.setItemDelegate(_TickDelegate(self))
        self.grid.itemClicked.connect(self._clicked)
        self.grid.itemDoubleClicked.connect(self._play_album_item)
        self.grid.setContextMenuPolicy(Qt.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self._grid_menu)
        self.grid.verticalScrollBar().valueChanged.connect(lambda _: self._pic_timer.start())
        tl.addWidget(self.grid, 1)
        self.split.addWidget(top)
        low = QWidget()
        ll = QVBoxLayout(low)
        ll.setContentsMargins(0, 6, 0, 0)
        ll.setSpacing(4)
        self.songs_label = QLabel("SONGS")
        self.songs_label.setObjectName("NowSectionLabel")
        ll.addWidget(self.songs_label)
        self.table = SongTable(theme, hidden_by_default=("artist", "genre", "playcount"))
        self.table.playRequested.connect(self._table_played)
        ll.addWidget(self.table, 1)
        self.split.addWidget(low)
        self._low = low
        self.toast = QLabel(low)  # "Added …" note over the songs
        self.toast.setObjectName("AddedToast")
        self.toast.setAlignment(Qt.AlignCenter)
        self.toast.setCursor(Qt.PointingHandCursor)
        self.toast.setToolTip("Click to hide")
        self.toast.mousePressEvent = lambda e: self.toast.hide()
        self.toast.hide()
        self._toast_timer = QTimer(self, singleShot=True, interval=3500)
        self._toast_timer.timeout.connect(self.toast.hide)
        self.split.setSizes([330, 300])
        v.addWidget(self.split, 1)
        self._pic_timer = QTimer(self, singleShot=True, interval=50)
        self._pic_timer.timeout.connect(self._load_visible)
        self._apply_size()

    @property
    def cover_px(self) -> int:
        return COVER_SIZES[self.cover_size][1]

    def set_cover_size(self, key: str, fit: bool = True):
        if key in COVER_SIZES:
            changed = key != self.cover_size
            self.cover_size = key
            self._apply_size()
            self._reload_covers()
            self.coverSizeChanged.emit(key)
            if fit and changed:  # a new size: fit the covers area
                QTimer.singleShot(0, self._fit_split)

    def _fit_split(self):
        """Fit the covers area to their size (up to two rows)."""
        sizes = self.split.sizes()
        total = sum(sizes)
        if total <= 0:
            return
        cell = self.grid.gridSize()
        per_row = max(1, (self.grid.viewport().width() or 600) // max(1, cell.width() + self.grid.spacing()))
        rows = min(2, max(1, -(-self.grid.count() // per_row)))
        want = self.albums_label.sizeHint().height() + 4 + rows * (cell.height() + self.grid.spacing()) + 12
        want = max(120, min(want, total - 140))
        self.split.setSizes([want, total - want])

    def _tile(self) -> QSize:
        c = self.cover_px
        return QSize(c + 20, c + 54)

    def _apply_size(self):
        c = self.cover_px
        self.grid.setIconSize(QSize(c, c))
        self.grid.setGridSize(QSize(c + 26, c + 62))
        for i in range(self.grid.count()):  # every tile full size
            self.grid.item(i).setSizeHint(self._tile())

    def show_artist(self, name: str, tracks: list[dict], kind: str = "album"):
        new_artist = name != self.name
        if name != self.name:
            self.about.show_info(name, {})
            self._sel = []  # new artist: reset the pick
            self._set_list([])
        self.name, self.kind = name, kind
        self.tracks = sorted(tracks, key=library_order)
        self.title.setText(name)
        albums: dict[str, dict] = {}
        for t in self.tracks:
            key = _title(t.get("album"))  # "Album (Disc 2)" belongs to "Album"
            a = albums.setdefault(key.lower(), {"album": key, "year": 0, "songs": 0, "length": 0, "track": t})
            a["songs"] += 1
            a["length"] += t.get("length") or 0
            y = t.get("origyear") or t.get("year") or 0
            if y and (not a["year"] or y < a["year"]):
                a["year"] = y
        self.albums = sorted(albums.values(), key=lambda a: (a["year"] or 9999, (a["album"] or "~").lower()))
        total = sum(t.get("length") or 0 for t in self.tracks)
        hours = total / 3600
        span = f"{hours:.1f} hours" if hours >= 1 else fmt_time(total)
        na, ns = len(self.albums), len(self.tracks)
        self.totals.setText(f"{na} album{'s' if na != 1 else ''}  ·  {ns:,} song{'s' if ns != 1 else ''}  ·  {span}")
        self.albums_label.setText(f"ALBUMS  ({na})")
        self.grid.blockSignals(True)
        self.grid.clear()
        all_it = QListWidgetItem(f"All songs\n{len(self.tracks):,} song{'s' if len(self.tracks) != 1 else ''}")
        all_it.setData(ALBUM, ALL)
        all_it.setToolTip(f"Every song by {name}")
        all_it.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
        all_it.setSizeHint(self._tile())
        self.grid.addItem(all_it)
        for a in self.albums:
            title = a["album"] or "Unknown Album"
            sub = " · ".join(b for b in (str(a["year"]) if a["year"] else "", f"{a['songs']} songs") if b)
            it = QListWidgetItem(f"{title}\n{sub}")
            it.setData(ALBUM, a["album"])
            it.setData(TRACK, a["track"])
            it.setToolTip(f"{title}\n{sub} · {fmt_time(a['length'])}\nDouble-click to play")
            it.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            it.setSizeHint(self._tile())
            self.grid.addItem(it)
        self.grid.setCurrentRow(0)
        self.grid.blockSignals(False)
        self.album = ALL
        known = {a["album"] for a in self.albums}
        self._sel = [k for k in self._sel if k in known]
        if any(k not in known for k in self._list):
            self._set_list([k for k in self._list if k in known], keep_order=True)
        self._show_songs()
        self._photo()
        self._reload_covers()
        if new_artist:
            self._jumped = False
            self._to_top()
            QTimer.singleShot(0, self._to_top_later)  # again once the list has been laid out

    _jumped = False

    def show_all(self):
        """All songs, nothing picked."""
        self._sel = []
        self._set_list([])
        self._resume = None
        self.album = ALL
        self.grid.blockSignals(True)
        self.grid.setCurrentRow(0)
        self.grid.blockSignals(False)
        self._show_songs()

    def _to_top_later(self):
        if not self._jumped:
            self._to_top()

    def _to_top(self):
        self.table.scrollToTop()
        self.table.horizontalScrollBar().setValue(0)
        self.grid.scrollToTop()

    def refresh(self, tracks: list[dict]):
        """Library changed: show the same artist again, keeping the picked album."""
        keep = self.album
        self.show_artist(self.name, tracks, self.kind)
        for i in range(self.grid.count()):
            if self.grid.item(i).data(ALBUM) == keep:
                self.grid.setCurrentRow(i)

    def _pick(self, it):
        self.album = it.data(ALBUM) if it is not None else ALL
        self._sel = [] if self.album == ALL else [self.album]
        self._show_songs()

    def pick_album(self, t: dict) -> bool:
        """Pick a song's album as if its cover was clicked."""
        want = _title(t.get("album")).lower()
        for i in range(self.grid.count()):
            it = self.grid.item(i)
            k = it.data(ALBUM)
            if k != ALL and (k or "").lower() == want:
                self.grid.setCurrentItem(it)
                self.grid.scrollToItem(it)
                self._pick(it)
                return True
        return False

    def tickable(self, key) -> bool:
        return key != ALL  # "All songs" has no + / -

    def in_target(self, key) -> bool:
        return key in (self._playing_keys if self._list else self._sel)

    def _clicked(self, it):
        key = it.data(ALBUM)
        if self._button_click == key:  # that was + or -, not a click on the album
            self._button_click = None
            return
        self.toast.hide()
        if self._list and key != ALL:  # while playing: + adds, double-click plays
            return
        self._pick(it)

    _resume = None  # song still playing after - removed every album

    def _set_list(self, keys, keep_order: bool = False):
        """Set the playing list (what's listed below, the play order and the ▶ marks)."""
        old = self._playing_ids
        self._list = [k for k in dict.fromkeys(keys) if k != ALL]
        self._playing_keys = set(self._list)
        ids = [i for k in self._list for i in self._album_ids(k)]
        if keep_order and self._shuffled and old:
            ids = keep_shuffled(old, ids)
        elif not keep_order:
            self._shuffled = False
        self._playing_ids = ids

    def add_album(self, key):
        """+ on a cover: add the album to the bottom of the list (playing or not)."""
        if key == ALL:
            return
        if not self._list:
            if self._resume is not None and self._resume == self._current_id:
                # + after removing every album while their song plays: playing from here again
                self._resume = None
                self._sel = [key]
                self._set_list([key])
                self.listReplaced.emit(self._playing_ids)
            elif key not in self._sel:
                self._sel.append(key)
            self._show_songs()
            self._after_add(key)
            return
        if key in self._playing_keys:
            return
        self._set_list(self._list + [key], keep_order=True)
        if key not in self._sel:
            self._sel.append(key)
        self.listReplaced.emit(self._playing_ids)
        self._show_songs()
        self._after_add(key)

    def _after_add(self, key):
        """Keep the list on the playing song (or at the top) and say what was added."""
        cur = self._current_id
        if self._list and cur in set(self._playing_ids):
            QTimer.singleShot(0, lambda: self.table.scroll_to_id(cur))
        else:
            QTimer.singleShot(0, self.table.scrollToTop)
        n = len(self._album_ids(key))
        only = len(self._list or self._sel) <= 1
        self.show_toast(f'✓  Added "{key or "Unknown Album"}" ({n} song{"s" if n != 1 else ""})'
                        + ("" if only else " to bottom of list"))

    def show_toast(self, text: str):
        """A note over the songs below for a few seconds."""
        t = self.toast
        t.setText(text)
        t.adjustSize()
        t.setFixedWidth(min(t.sizeHint().width(), max(200, self._low.width() - 24)))
        self._place_toast()
        t.show()
        t.raise_()
        self._toast_timer.start()

    def _place_toast(self):
        t, low = self.toast, self._low
        y = self.table.mapTo(low, self.table.rect().topLeft()).y() + 40  # just under the column headings
        t.move(max(8, (low.width() - t.width()) // 2), max(4, min(y, low.height() - t.height() - 8)))

    def remove_album(self, key):
        """- on a cover: remove the album. The playing song carries on."""
        if not self._list:
            if key in self._sel:
                self._sel.remove(key)
            self._show_songs()
            return
        if key not in self._playing_keys:
            return
        if key in self._sel:
            self._sel.remove(key)  # so its + shows again
        self._set_list([k for k in self._list if k != key], keep_order=True)
        self.listReplaced.emit(self._playing_ids)
        if not self._list:
            # only the playing song is left: + on its album puts it back
            self._resume = self._current_id
        self._show_songs()

    def jump_to(self, tid) -> bool:
        """Find the playing song in the list below. The listing itself never changes."""
        t = next((t for t in self.tracks if t.get("id") == tid), None)
        if t is None:
            return False
        self._jumped = True
        if self._keys_shown() != [ALL]:
            # bring the picked album's cover into view
            want = _title(t.get("album")).lower()
            keys = {(k or "").lower() for k in self._keys_shown()}
            for i in range(self.grid.count()):
                k = self.grid.item(i).data(ALBUM)
                if k != ALL and (k or "").lower() == want and want in keys:
                    self.grid.scrollToItem(self.grid.item(i), QAbstractItemView.EnsureVisible)
                    break
        QTimer.singleShot(0, lambda: self.table.scroll_to_id(tid))
        return True

    def note_current(self, tid):
        """The playing song changed: if it's not from here, + and - edit the pick again."""
        self._current_id = tid
        if self._resume is not None and tid != self._resume:
            self._resume = None
        if self._list and tid not in set(self._playing_ids):
            self._sel = list(self._list)  # music moved on: the albums stay listed as a selection
            self._set_list([])
            self._show_songs()

    def _table_played(self, _row):
        """Double-clicked song: what's listed plays from there."""
        if self.table.model_.ids() and self._sel:
            if set(self._list) != set(self._sel):
                self._set_list(self._sel)
            QTimer.singleShot(0, self._show_songs)

    def _keys_shown(self) -> list:
        """Albums whose songs are listed, in the order they were added: playing, picked or clicked."""
        if self._list:
            return list(self._list)
        if self._sel:
            return list(dict.fromkeys(self._sel))
        return [ALL] if self.album == ALL else [self.album]

    def _shown(self) -> list[dict]:
        keys = self._keys_shown()
        if keys == [ALL]:
            return self.tracks
        out = []
        for k in keys:
            a = (k or "").lower()
            out += sorted((t for t in self.tracks if _title(t.get("album")).lower() == a),
                          key=lambda t: (t.get("disc") or 0, t.get("track") or 0, t.get("path") or ""))
        return out

    def _show_songs(self):
        rows = self._shown()
        self.table.model_.set_rows(rows, keep_sort=False)
        keys = self._keys_shown()
        if any(it.data(ALBUM) not in keys for it in self.grid.selectedItems()):
            self.grid.clearSelection()
        playing = bool(self._list)
        if keys == [ALL]:
            what = "SONGS"
        elif len(keys) == 1:
            what = (keys[0] or "Unknown Album").upper()
        else:
            what = f"{len(keys)} ALBUMS"
        total = sum(t.get("length") or 0 for t in rows)
        self.songs_label.setText(("PLAYING  ·  " if playing else "") + f"{what}  ·  {len(rows)} songs  ·  "
                                 f"{fmt_time(total)}" + ("  ·  + and − change what's playing" if playing else
                                                          ("" if len(keys) > 1 or keys == [ALL] else
                                                           "  ·  + on another cover adds it")))
        for b in (self.play_btn, self.shuffle_btn, self.queue_btn):
            b.setEnabled(bool(rows))
        n = len([k for k in keys if k != ALL])
        self.play_btn.setText("Play" if n == 0 else "Play album" if n == 1 else f"Play {n} albums")
        self.grid.viewport().update()

    def _play_shown(self, shuffle: bool):
        ids = [t["id"] for t in self._shown()]
        if shuffle:
            random.shuffle(ids)
        if ids:
            keys = [k for k in self._keys_shown() if k != ALL]
            if keys:
                self._sel = list(keys)
                self._set_list(keys)
                if shuffle:
                    self._playing_ids, self._shuffled = list(ids), True
            self._resume = None
            self._show_songs()
            self.playRequested.emit(ids, 0)

    def _album_ids(self, album) -> list[int]:
        if album == ALL:
            return [t["id"] for t in self.tracks]
        a = (album or "").lower()
        return [t["id"] for t in sorted((t for t in self.tracks if _title(t.get("album")).lower() == a),
                                        key=lambda t: (t.get("disc") or 0, t.get("track") or 0, t.get("path") or ""))]

    def _play_album_item(self, it):
        key = it.data(ALBUM)
        ids = self._album_ids(key)
        if ids:
            if key != ALL:
                self._sel = [key]
                self._set_list([key])
            else:
                self._sel = []
                self._set_list([])
            self._button_click = None
            self._resume = None
            self._show_songs()
            self.playRequested.emit(ids, 0)

    def _grid_menu(self, pos):
        it = self.grid.itemAt(pos)
        m = QMenu(self)
        if it is not None:
            album = it.data(ALBUM)
            from musicwell.menus import title
            title(m, "All songs" if album == ALL else (album or "Unknown Album"))
            m.addAction("Play", lambda: self.playRequested.emit(self._album_ids(album), 0))

            def shuffle():
                import random
                ids = self._album_ids(album)
                random.shuffle(ids)
                self.playRequested.emit(ids, 0)
            m.addAction("Shuffle", shuffle)
            m.addAction("Add to queue", lambda: self.queueRequested.emit(self._album_ids(album)))
            t = it.data(TRACK)
            if album != ALL and t and self.picture_actions:
                m.addSeparator()
                im = m.addMenu("Image")
                from musicwell.menus import add_actions
                add_actions(im, self.picture_actions("album", self.name, t))
            m.addSeparator()
        zm = m.addMenu("Cover size")
        for k, (text, _px) in COVER_SIZES.items():
            a = zm.addAction(text, lambda k=k: self.set_cover_size(k))
            a.setCheckable(True)
            a.setChecked(self.cover_size == k)
        m.exec(self.grid.viewport().mapToGlobal(pos))

    def _photo_menu(self, pos):
        if not self.picture_actions or not self.name:
            return
        from PySide6.QtWidgets import QMenu
        m = QMenu(self)
        from musicwell.menus import add_actions
        add_actions(m, self.picture_actions("artist", self.name, self.tracks[0] if self.tracks else None))
        m.exec(self.photo.mapToGlobal(pos))

    def _photo(self):
        dpr = self.devicePixelRatioF() or 1.0
        img = None
        if self.photo_provider and self.tracks:
            img = self.photo_provider(self.name, self.tracks[0].get("path", ""), int(PHOTO * dpr))
        if img is None or img.isNull():
            from musicwell.artwork import placeholder
            img = placeholder(int(PHOTO * dpr), self.name, QColor(self.theme.accent))
        self.photo.setPixmap(_rounded(img, PHOTO, dpr, 8))  # rounded like the covers

    def _all_tile(self, dpr: float) -> tuple[QIcon, bool]:
        """All songs tile: small covers of up to four albums."""
        c = self.cover_px
        px = int(c * dpr)
        img = QImage(px, px, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, px, px), 8 * dpr, 8 * dpr)
        p.setClipPath(path)
        acc = QColor(self.theme.accent)
        from musicwell.artwork import placeholder
        albums = self.albums[:4]
        complete = True
        pics = []
        for a in albums:
            t = a.get("track")
            size = px // 2
            got = self.cover_provider(t, size) if (self.cover_provider and t) else None
            if got is None or got.isNull():
                complete = False
                got = placeholder(size, a.get("album") or "?", acc)
            pics.append(got)
        gap = max(2.0, 3 * dpr)  # small gap, no lines
        h = (px - gap) / 2
        squares = [QRectF((n % 2) * (h + gap), (n // 2) * (h + gap), h, h) for n in range(4)]
        # four squares: each album's cover once, the rest empty
        for n, r in enumerate(squares):
            sq = QPainterPath()
            sq.addRoundedRect(r, 3 * dpr, 3 * dpr)
            if n < len(pics):
                pic = pics[n]
                sw, sh = pic.width(), pic.height()
                s = min(sw, sh)  # centre of a non-square cover
                p.save()
                p.setClipPath(sq, Qt.IntersectClip)
                p.drawImage(r, pic, QRectF((sw - s) / 2, (sh - s) / 2, s, s))
                p.restore()
            else:
                p.fillPath(sq, acc.darker(300))
        p.end()
        out = QPixmap.fromImage(img)
        out.setDevicePixelRatio(dpr)
        return QIcon(out), complete

    def _reload_covers(self):
        for i in range(self.grid.count()):
            self.grid.item(i).setData(LOADED, False)
            self.grid.item(i).setIcon(QIcon())
        self._pic_timer.start()

    def _load_visible(self):
        dpr = self.devicePixelRatioF() or 1.0
        c = self.cover_px
        vp = self.grid.viewport().rect().adjusted(0, -c, 0, c * 2)
        for i in range(self.grid.count()):
            it = self.grid.item(i)
            if it.data(LOADED) or not self.grid.visualItemRect(it).intersects(vp):
                continue
            if it.data(ALBUM) == ALL:
                icon, complete = self._all_tile(dpr)
                it.setIcon(icon)
                it.setData(LOADED, complete)  # redrawn as covers arrive
                continue
            t = it.data(TRACK)
            img = self.cover_provider(t, int(c * dpr)) if (self.cover_provider and t) else None
            if img is not None and not img.isNull():
                it.setIcon(QIcon(_rounded(img, c, dpr, 8)))
                it.setData(LOADED, True)
            elif it.icon().isNull():
                from musicwell.artwork import placeholder
                ph = placeholder(int(c * dpr), it.data(ALBUM) or "?", QColor(self.theme.accent))
                it.setIcon(QIcon(_rounded(ph, c, dpr, 8)))

    def cover_ready(self, key: str):
        from musicwell.artwork import album_key
        for i in range(self.grid.count()):
            t = self.grid.item(i).data(TRACK)
            if t and album_key(t) == key:
                self.grid.item(i).setData(LOADED, False)
                if i <= 4 and self.grid.count():
                    self.grid.item(0).setData(LOADED, False)
        self._pic_timer.start()

    def photo_ready(self, name: str):
        from musicwell.artwork import primary_artist
        if self.name and primary_artist(name).lower() == primary_artist(self.name).lower():
            self._photo()

    def set_current(self, tid):
        self.table.model_.set_current(tid)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._pic_timer.start()

    def showEvent(self, e):
        super().showEvent(e)
        self._pic_timer.start()

    def refresh_theme(self):
        self.table.refresh_theme()
        self._photo()
        self._reload_covers()
