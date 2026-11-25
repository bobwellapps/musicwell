"""All albums: every album as a cover, with its songs listed below."""
from __future__ import annotations

import os
import random

from PySide6.QtCore import QPointF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QListView,
                               QListWidget, QListWidgetItem, QMenu, QPushButton, QSplitter, QVBoxLayout, QWidget)

from musicwell.artistlist import sort_name
from musicwell.artistview import COVER_SIZES, _rounded, keep_shuffled
from musicwell.models import fmt_time
from musicwell.widgets import SongTable
from musicwell.tags import album_title

SORTS = {"artist": "Artist", "album": "Album title", "year": "Year (newest first)", "year_old": "Year (oldest first)",
         "added": "Recently added", "plays": "Most played"}
KEY, TRACK, LOADED = Qt.UserRole, Qt.UserRole + 1, Qt.UserRole + 2


from PySide6.QtWidgets import QStyle, QStyledItemDelegate

from musicwell.widgets import WrapRow as _HeadRow


class _TickDelegate(QStyledItemDelegate):
    """Album tile controls: - (bottom left) and + (bottom right) remove or add the album, ▶ marks albums playing from here."""
    SIZE = 24

    def __init__(self, page):
        super().__init__(page.grid)
        self.page = page

    def _cover(self, option):
        from PySide6.QtCore import QRect
        icon = self.page.grid.iconSize().width()
        left = option.rect.left() + (option.rect.width() - icon) // 2
        return QRect(left, option.rect.top() + 2, icon, icon)

    def minus_rect(self, option):
        from PySide6.QtCore import QRect
        c = self._cover(option)
        return QRect(c.left() + 6, c.bottom() - 6 - self.SIZE, self.SIZE, self.SIZE)

    def plus_rect(self, option):
        from PySide6.QtCore import QRect
        c = self._cover(option)
        return QRect(c.right() - 6 - self.SIZE, c.bottom() - 6 - self.SIZE, self.SIZE, self.SIZE)

    def paint(self, p, option, index):
        super().paint(p, option, index)
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QPen, QPolygonF
        t = self.page.theme
        key = index.data(KEY)
        if not getattr(self.page, "tickable", lambda k: True)(key):
            return
        inside = self.page.in_target(key)  # can + / - change it
        hover = bool(option.state & QStyle.State_MouseOver)
        p.save()
        p.setRenderHint(p.RenderHint.Antialiasing)
        if inside:
            p.setPen(QPen(t.accent, 3))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(self._cover(option)).adjusted(1.5, 1.5, -1.5, -1.5), 8, 8)
        if key in self.page._playing_keys:
            c = self._cover(option)
            r = QRectF(c.right() - 6 - self.SIZE, c.top() + 6, self.SIZE, self.SIZE)
            p.setPen(Qt.NoPen)
            p.setBrush(t.accent)
            p.drawEllipse(r)
            p.setBrush(QColor(t.accent_text()))
            m = r.center()
            p.drawPolygon(QPolygonF([m + QPointF(-3, -5), m + QPointF(-3, 5), m + QPointF(5, 0)]))

        def circle(rect, on):
            r = QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5)
            p.setPen(QPen(t.accent.lighter(130) if on else QColor(255, 255, 255, 230), 1.6))
            p.setBrush(t.accent if on else QColor(0, 0, 0, 140))
            p.drawEllipse(r)
            pen = QPen(QColor(t.accent_text()) if on else QColor(255, 255, 255), 2.2)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen)
            return r.center()
        # - when it's in the list, + otherwise (on hover)
        if inside:
            m = circle(self.minus_rect(option), hover)
            p.drawLine(m + QPointF(-5, 0), m + QPointF(5, 0))
        elif hover or key == getattr(self.page, "looking_at", lambda: None)():
            # always shown on the album being looked at, not just on hover
            m = circle(self.plus_rect(option), False)
            p.drawLine(m + QPointF(-5, 0), m + QPointF(5, 0))
            p.drawLine(m + QPointF(0, -5), m + QPointF(0, 5))
        p.restore()

    def editorEvent(self, event, model, option, index):
        from PySide6.QtCore import QEvent
        if event.type() in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick, QEvent.MouseButtonRelease) \
                and event.button() == Qt.LeftButton:
            pos = event.position().toPoint()
            key = index.data(KEY)
            if not getattr(self.page, "tickable", lambda k: True)(key):
                return super().editorEvent(event, model, option, index)
            inside = self.page.in_target(key)
            hit = None
            if inside and self.minus_rect(option).adjusted(-3, -3, 3, 3).contains(pos):
                hit = "-"
            elif not inside and self.plus_rect(option).adjusted(-3, -3, 3, 3).contains(pos):
                hit = "+"
            if hit or (event.type() != QEvent.MouseButtonPress and self.page._button_click == key):
                if event.type() == QEvent.MouseButtonPress:
                    self.page._button_click = key  # the click that follows isn't "show this album"
                    (self.page.add_album if hit == "+" else self.page.remove_album)(key)
                return True
        return super().editorEvent(event, model, option, index)


def _album_dir(path: str) -> str:
    """The album's folder (one up from a CD1 / Disc 2 folder)."""
    from musicwell.tags import album_folder
    return os.path.normcase(album_folder(path))


def _album_order(t: dict):
    """Disc, track number, then file name."""
    return (t.get("disc") or 0, t.get("track") or 0, os.path.normcase(t.get("path") or ""))


def album_groups(tracks, split: bool = False) -> list[dict]:
    """One dict per album. split=True splits albums by artist."""
    out: dict[str, dict] = {}
    for t in tracks:
        if t.get("stream") or t.get("remote"):
            continue
        artist = (t.get("artist_key") or t.get("artist") or "").strip()
        album = album_title(t.get("album") or "")  # "Album (Disc 2)" belongs to "Album"
        albumartist = (t.get("albumartist") or "").strip()
        if split:
            k = artist.lower() + "\x1f" + album.lower()
        elif albumartist:
            k = "aa:" + albumartist.lower() + "\x1f" + album.lower()
        else:
            k = "dir:" + _album_dir(t.get("path", "")) + "\x1f" + album.lower()
        a = out.get(k)
        if a is None:
            a = out[k] = {"key": k, "album": album, "artist": albumartist if (albumartist and not split) else artist,
                          "artists": [], "various": False, "year": 0, "songs": 0, "length": 0, "plays": 0,
                          "added": 0, "track": t, "tracks": []}
        if artist and artist not in a["artists"]:
            a["artists"].append(artist)
        a["songs"] += 1
        a["length"] += t.get("length") or 0
        a["plays"] += t.get("playcount") or 0
        a["added"] = max(a["added"], t.get("added") or 0)
        a["tracks"].append(t)
        y = t.get("origyear") or t.get("year") or 0
        if y and (not a["year"] or y < a["year"]):
            a["year"] = y
    groups = list(out.values())
    for a in groups:  # the tile shows the first song (disc 1, track 1)
        a["tracks"].sort(key=_album_order)
        a["track"] = a["tracks"][0]
        a["discs"] = len({t.get("disc") or 0 for t in a["tracks"]} - {0}) or 1
    if not split:
        for a in groups:  # several artists and no album artist: a compilation
            if len(a["artists"]) > 1 and not (a["tracks"][0].get("albumartist") or "").strip():
                a["artist"], a["various"] = "Various Artists", True
            elif len(a["artists"]) > 1:
                a["various"] = a["artist"].lower() in ("various artists", "various", "va", "verschiedene")
    return groups


class AlbumsPage(QWidget):
    playRequested = Signal(list, int)  # track ids, start
    queueRequested = Signal(list)
    listReplaced = Signal(list)  # the whole playing list after + / -
    artistRequested = Signal(str)
    browseRequested = Signal(str, str)  # artist, album
    backRequested = Signal()
    optionsChanged = Signal()
    changed = Signal()  # as a user tab: the window saves it

    def __init__(self, theme, parent=None, back: bool = True, spec: dict | None = None):
        super().__init__(parent)
        self.theme = theme
        self.spec = spec if spec is not None else {}
        self.cover_provider = None  # (track, px) -> QImage | None
        self.sort = self.spec.get("sort") if self.spec.get("sort") in SORTS else "artist"
        self.cover_size = self.spec.get("covers") if self.spec.get("covers") in COVER_SIZES else "medium"
        self.split_artists = bool(self.spec.get("split", False))
        self._groups: list[dict] = []
        self._picked = None
        self._sel: list = []  # albums listed below
        self._restored = False  # last session's state loaded yet?
        self._current_id = None  # playing song, set by the window
        self._button_click = None
        # Albums playing from here, in order: the first played on top, each added album underneath. _set_list keeps _playing_ids and _playing_keys in sync.
        self._list: list = []
        self._playing_ids: list[int] = []  # their songs, in order
        self._playing_keys: set = set()  # their albums (▶ on the covers)
        self._viewing = None  # album shown just to look at; the list stays as it is
        self._click_pick = False  # _sel is a single clicked album, not added with +
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 8, 16, 0)
        v.setSpacing(8)
        g1, g2, g3 = QHBoxLayout(), QHBoxLayout(), QHBoxLayout()
        head = g1
        self.back_btn = QPushButton("←  Library")
        self.back_btn.setToolTip("Back to the library (Esc)")
        self.back_btn.clicked.connect(self.backRequested)
        self.back_btn.setVisible(back)
        head.addWidget(self.back_btn)
        self.title = QLabel(self.spec.get("name") or "All albums")
        self.title.setObjectName("PageTitle")
        head.addWidget(self.title)
        self.info = QLabel("")
        self.info.setObjectName("EmptyText")
        head.addWidget(self.info)
        head = g2
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter albums and artists…")
        self.filter.setClearButtonEnabled(True)
        self.filter.setMinimumWidth(150)
        self.filter.textChanged.connect(lambda _: self._fill())
        head.addWidget(self.filter)
        self.split_box = QCheckBox("Split by artist")
        self.split_box.setChecked(self.split_artists)
        self.split_box.setToolTip("Off: each album once, even when its songs are by different artists (a compilation "
                                  "shows as Various Artists).\nOn: one tile for each artist on an album.")
        self.split_box.toggled.connect(self._set_split)
        self.split_box.hide()
        head.addSpacing(6)
        head.addWidget(QLabel("Sort"))
        self.sort_box = QComboBox()
        for k, text in SORTS.items():
            self.sort_box.addItem(text, k)
        self.sort_box.setCurrentIndex(max(0, self.sort_box.findData(self.sort)))
        self.sort_box.activated.connect(lambda _: self._set_sort(self.sort_box.currentData()))
        head.addWidget(self.sort_box)
        self.select_btn = QPushButton("Add all")
        self.select_btn.setToolTip("Add every album showing to your selection — or clear the selection")
        self.select_btn.clicked.connect(self._select_all_or_none)
        self.play_btn = QPushButton("Play")
        self.play_btn.setObjectName("Primary")
        self.play_btn.clicked.connect(lambda: self._play_keys(self._chosen_keys(), False))
        self.shuffle_btn = QPushButton("Shuffle")
        self.shuffle_btn.clicked.connect(lambda: self._play_keys(self._chosen_keys(), True))
        self.queue_btn = QPushButton("Add to queue")
        self.queue_btn.clicked.connect(lambda: self._queue_keys(self._chosen_keys()))
        self.edit_btn = QPushButton("")
        self.edit_btn.hide()
        head = g3
        head.addWidget(self.select_btn)
        head.addWidget(self.play_btn)
        head.addWidget(self.shuffle_btn)
        head.addWidget(self.queue_btn)
        v.addWidget(_HeadRow([g1, g2, g3]))

        self.split = QSplitter(Qt.Vertical)
        self.split.setChildrenCollapsible(False)
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
        self.grid.itemClicked.connect(self._clicked)
        self.grid.setMouseTracking(True)
        self.grid.setItemDelegate(_TickDelegate(self))
        self.grid.setToolTip("")
        self.grid.itemDoubleClicked.connect(lambda it: self._play(it.data(KEY), False))
        self.grid.setContextMenuPolicy(Qt.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self._menu)
        self.grid.verticalScrollBar().valueChanged.connect(lambda _: self._pic_timer.start())
        self.split.addWidget(self.grid)
        low = QWidget()
        ll = QVBoxLayout(low)
        ll.setContentsMargins(0, 6, 0, 0)
        ll.setSpacing(4)
        lrow = QHBoxLayout()
        lrow.setSpacing(6)
        self.songs_label = QLabel("")
        self.songs_label.setObjectName("NowSectionLabel")
        lrow.addWidget(self.songs_label, 1)
        self.clear_btn = QPushButton("Clear all")
        self.clear_btn.setObjectName("Segment")
        self.clear_btn.setCursor(Qt.PointingHandCursor)
        self.clear_btn.setToolTip("Empty the list below (the song playing finishes; nothing plays after it)")
        self.clear_btn.clicked.connect(self.clear_all)
        lrow.addWidget(self.clear_btn)
        self.playing_btn = QPushButton("▶  Show what's playing")
        self.playing_btn.setObjectName("Primary")
        self.playing_btn.setCursor(Qt.PointingHandCursor)
        self.playing_btn.setToolTip("Back to the songs playing from here")
        self.playing_btn.clicked.connect(self.show_playing)
        self.playing_btn.hide()
        lrow.addWidget(self.playing_btn)
        ll.addLayout(lrow)
        self.table = SongTable(theme, hidden_by_default=("genre", "playcount"))
        self.table.playRequested.connect(self._table_played)
        ll.addWidget(self.table, 1)
        self.split.addWidget(low)
        self._low = low
        self.toast = QLabel(low)
        self.toast.setObjectName("AddedToast")
        self.toast.setAlignment(Qt.AlignCenter)
        self.toast.setCursor(Qt.PointingHandCursor)
        self.toast.setToolTip("Click to hide")
        self.toast.mousePressEvent = lambda e: self.toast.hide()
        self.toast.hide()
        self._toast_timer = QTimer(self, singleShot=True, interval=3500)
        self._toast_timer.timeout.connect(self.toast.hide)
        self.split.setSizes([480, 220])
        v.addWidget(self.split, 1)
        self._pic_timer = QTimer(self, singleShot=True, interval=50)
        self._pic_timer.timeout.connect(self._load_visible)
        self._apply_size()
        self._update_buttons()

    is_playlist = False
    is_search = False

    def _apply_spec_sort(self):
        pass

    def shuffled_ids(self) -> list[int]:
        ids = self.table.model_.ids()
        random.shuffle(ids)
        return ids

    def refresh(self, library, current_id=None):
        self.title.setText(self.spec.get("name") or "All albums")
        self.set_tracks(library.all_tracks())
        if current_id is not None:
            self.table.model_.set_current(current_id)

    def _set_sort(self, key):
        self.sort = key
        self.spec["sort"] = key
        self._fill()
        self.optionsChanged.emit()
        self.changed.emit()

    def _set_split(self, on: bool):
        if bool(on) == self.split_artists:
            return
        self.split_artists = bool(on)
        self.spec["split"] = self.split_artists
        if self.split_box.isChecked() != self.split_artists:
            self.split_box.blockSignals(True)
            self.split_box.setChecked(self.split_artists)
            self.split_box.blockSignals(False)
        self._picked = None
        self._groups = album_groups(self._tracks, self.split_artists)
        self._fill()
        self.optionsChanged.emit()
        self.changed.emit()

    def set_cover_size(self, key: str):
        if key in COVER_SIZES:
            self.cover_size = key
            self.spec["covers"] = key
            self._apply_size()
            self._reload_covers()
            self.optionsChanged.emit()
            self.changed.emit()

    def _tile(self) -> QSize:
        c = COVER_SIZES[self.cover_size][1]
        return QSize(c + 20, c + 54)

    def _apply_size(self):
        c = COVER_SIZES[self.cover_size][1]
        self.grid.setIconSize(QSize(c, c))
        self.grid.setGridSize(QSize(c + 26, c + 62))
        for i in range(self.grid.count()):
            self.grid.item(i).setSizeHint(self._tile())

    _tracks: list = []

    def set_tracks(self, tracks):
        self._tracks = list(tracks)
        self._groups = album_groups(self._tracks, self.split_artists)
        self._fill()
        if self._list and any(not self._group(k) for k in self._list):
            self._set_list(self._list, keep_order=True)  # drop albums that no longer exist
        if not self._restored and self._groups:
            self._restore_memory()

    # Saved between sessions: the selection and what was playing.
    def _memory_key(self) -> str:
        return "albums_memory_" + str(self.spec.get("id") or "library")

    def _remember(self):
        if not self._restored:
            return
        import json
        from musicwell.paths import settings
        settings().setValue(self._memory_key(), json.dumps({
            "sel": list(self._sel), "list": list(self._list), "playing_ids": self._playing_ids,
            "click": self._click_pick}))

    def _restore_memory(self):
        import json
        from musicwell.paths import settings
        self._restored = True
        try:
            d = json.loads(settings().value(self._memory_key(), "{}") or "{}")
        except (TypeError, ValueError):
            d = {}
        if not isinstance(d, dict):
            return
        known = {a["key"] for a in self._groups}
        ids_known = {t["id"] for a in self._groups for t in a["tracks"]}
        self._sel = [k for k in d.get("sel", []) if k in known]
        self._click_pick = bool(d.get("click")) and len(self._sel) == 1
        playing = [i for i in d.get("playing_ids", []) if i in ids_known]
        # Restore the playing list only if the player is still on one of its songs.
        if playing and (self._current_id is None or self._current_id in set(playing)):
            order = [k for k in d.get("list", []) if k in known]
            if not order:  # older format: derive the order from playing_ids
                of = {t["id"]: a["key"] for a in self._groups for t in a["tracks"]}
                order = list(dict.fromkeys(of[i] for i in playing if i in of))
            self._set_list(order)
            if sorted(playing) == sorted(self._playing_ids) and playing != self._playing_ids:
                self._playing_ids, self._shuffled = playing, True
        self._show_songs()

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
        return sorted(groups, key=lambda a: (sort_name(a["artist"] or "~"), a["year"] or 9999,
                                             sort_name(a["album"])))

    def _fill(self):
        words = [w for w in self.filter.text().lower().split() if w]
        groups = [a for a in self._groups
                  if all(w in (a["album"] + " " + a["artist"] + " " + " ".join(a["artists"])).lower() for w in words)]
        keep = self._picked
        self.grid.blockSignals(True)
        self.grid.clear()
        self._by_key = {}
        for a in self._sorted(groups):
            title = a["album"] or "Unknown Album"
            discs = f"{a['discs']} CDs" if a.get("discs", 1) > 1 else ""
            sub = " · ".join(b for b in (a["artist"] or "Unknown Artist", str(a["year"]) if a["year"] else "", discs)
                             if b)
            it = QListWidgetItem(f"{title}\n{sub}")
            it.setData(KEY, a["key"])
            it.setData(TRACK, a["track"])
            who = a["artist"] + (f" — {', '.join(a['artists'][:6])}{'…' if len(a['artists']) > 6 else ''}"
                                 if a["various"] else "")
            it.setToolTip(f"{title}\n{who}\n{a['songs']} songs · {fmt_time(a['length'])}"
                          + (f" · {a['discs']} discs" if a.get("discs", 1) > 1 else "")
                          + (f" · {a['year']}" if a["year"] else "") + "\nDouble-click to play")
            it.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            it.setSizeHint(self._tile())
            self.grid.addItem(it)
            self._by_key[a["key"]] = a
            if a["key"] == keep:
                self.grid.setCurrentItem(it)
        self.grid.blockSignals(False)
        n, total = len(groups), len(self._groups)
        self.info.setText(f"{n:,} of {total:,}" if words else f"{total:,} album{'s' if total != 1 else ''}")
        if keep not in self._by_key:
            self._picked = None
        self._show_songs()
        self._pic_timer.start()

    def select_album(self, artist: str, album: str) -> bool:
        """Select this album and scroll to it; artist "" for a compilation."""
        from musicwell.tags import album_title
        want = album_title(album or "").lower()
        who = (artist or "").lower()

        def fits(a):
            if a["album"].lower() != want:
                return False
            return not who or a["artist"].lower() == who or who in (x.lower() for x in a["artists"])
        if not any(fits(a) for a in self._groups):
            return False
        if self.filter.text() and not any(fits(self._by_key.get(self.grid.item(i).data(KEY)) or {"album": "", "artist": "", "artists": []})
                                          for i in range(self.grid.count())):
            self.filter.clear()
        for i in range(self.grid.count()):
            it = self.grid.item(i)
            a = self._by_key.get(it.data(KEY))
            if a and fits(a):
                self.grid.setCurrentItem(it)
                self._clicked(it)
                self.grid.scrollToItem(it, QAbstractItemView.PositionAtCenter)
                return True
        return False

    def jump_to(self, tid, show: bool = False) -> bool:
        """Select the playing song's album and scroll the list to the song. show=True also marks the cover while a list plays."""
        a = next((a for a in self._groups if any(t.get("id") == tid for t in a["tracks"])), None)
        if a is None:
            return False
        if self.filter.text() and a["key"] not in self.shown_keys():
            self.filter.clear()
        for i in range(self.grid.count()):
            it = self.grid.item(i)
            if it.data(KEY) == a["key"]:
                if not self._playing_ids:  # don't touch a list that is playing
                    self.grid.setCurrentItem(it)
                    self._clicked(it)
                elif show:
                    self.grid.setCurrentItem(it)
                    self.show_playing()
                self.grid.scrollToItem(it, QAbstractItemView.EnsureVisible)
                break
        QTimer.singleShot(0, lambda: self.table.scroll_to_id(tid))
        return True

    def key_of(self, tid):
        """The album key of a song, or None."""
        a = next((a for a in self._groups if any(t.get("id") == tid for t in a["tracks"])), None)
        return a["key"] if a else None

    def _group(self, key):
        return getattr(self, "_by_key", {}).get(key) or next((a for a in self._groups if a["key"] == key), None)

    def _pick(self, it):
        self._picked = it.data(KEY) if it is not None else None

    def _clicked(self, it):
        """A cover was clicked: show its songs. Albums already added stay listed; others are just viewed."""
        key = it.data(KEY)
        if self._button_click == key:  # that was + or -, not a click on the album
            self._button_click = None
            return
        self.toast.hide()  # the note was about the list
        if self._playing_ids:
            view = None if key in self._playing_keys else key
            if view != self._viewing:
                self._viewing = view
                self._show_songs()
                if view is None:
                    self._show_current()
            return
        if not self._sel or self._click_pick:
            # nothing added yet: the clicked album is the selection
            self._viewing = None
            if self._sel != [key]:
                self._sel, self._click_pick = [key], True
                self._show_songs()
            return
        # albums added: just view this one
        view = None if key in self._sel else key
        if view != self._viewing:
            self._viewing = view
            self._show_songs()

    def show_playing(self):
        """Back from viewing another album to the playing list."""
        if self._viewing is not None:
            self._viewing = None
            self._show_songs()
            self._mark_playing()
            self._show_current()

    def _show_current(self):
        """Scroll the list below to the playing song."""
        cur = getattr(self, "_current_id", None)
        if cur is not None:
            QTimer.singleShot(0, lambda: self.table.scroll_to_id(cur))

    def _mark_playing(self):
        """Select the playing album's cover."""
        key = self.key_of(self._current_id) if self._current_id is not None else None
        if key not in self._playing_keys:
            keys = [k for k in self.shown_keys() if k in self._playing_keys]
            key = keys[0] if keys else None
        for i in range(self.grid.count()):
            it = self.grid.item(i)
            if it.data(KEY) == key:
                self.grid.setCurrentItem(it)
                self.grid.scrollToItem(it, QAbstractItemView.EnsureVisible)
                break

    def selected_keys(self) -> list:
        """The selection in the order the albums were added."""
        return list(dict.fromkeys(self._sel))

    def shown_keys(self) -> list:
        return [self.grid.item(i).data(KEY) for i in range(self.grid.count())] if hasattr(self, "grid") else []

    def _chosen_keys(self) -> list:
        """What Play / Shuffle / Add to queue act on: the viewed album, the selection, or every album shown."""
        if self._viewing is not None:
            return [self._viewing]
        return self.selected_keys() or self.shown_keys()

    def in_target(self, key) -> bool:
        if self._playing_ids:
            return key in self._playing_keys
        # a clicked album isn't in the list yet, so it shows +
        return key in self._sel and not self._click_pick

    def looking_at(self):
        """The album shown just to look at (+ always drawn on it)."""
        if self._viewing is not None:
            return self._viewing
        if self._click_pick and not self._playing_ids and self._sel:
            return self._sel[0]
        return None

    _resume = None  # song still playing after - removed every album

    def _ids_to_add(self, key) -> list[int]:
        """Songs to add: if the playing song is on this album, only the ones after it."""
        ids = self._ids(key)
        cur = getattr(self, "_current_id", None)
        if cur in ids:
            ids = ids[ids.index(cur) + 1:]
        return ids

    def add_album(self, key, announce: bool = True):
        """+ on a cover: add the album to the bottom of the list (playing or not)."""
        if self._list and key in self._playing_keys:
            return
        self._viewing = None
        if not self._playing_ids:
            cur = getattr(self, "_current_id", None)
            if self._resume is not None and self._resume == cur:
                # + after every album was removed while their song plays: playing from here again
                self._resume = None
                self._set_list([key])
                self._sel = [key]
                self.listReplaced.emit(self._playing_ids)
                self._show_songs()
                self._after_add(key, announce)
                return
            if key not in self._sel:
                self._sel.append(key)
            self._click_pick = False
            self.grid.viewport().update()
            self._show_songs()
            self._after_add(key, announce)
            return
        if key in self._playing_keys:
            return
        self._set_list(self._list + [key], keep_order=True)
        if key not in self._sel:
            self._sel.append(key)
        self.listReplaced.emit(self._playing_ids)
        self._show_songs()
        self._after_add(key, announce)

    def _after_add(self, key, announce: bool = True):
        """Keep the list on the playing song (or at the top) and show what was added."""
        self._show_current() if self._list else QTimer.singleShot(0, self.table.scrollToTop)
        a = self._group(key)
        if announce and a:
            n = len(a["tracks"])
            name = a["album"] or "Unknown Album"
            only = len(self._list if self._list else self._sel) <= 1  # first album: no "bottom" yet
            self.show_toast(f'✓  Added "{name}" ({n} song{"s" if n != 1 else ""})' + ("" if only else " to bottom of list"))

    def show_toast(self, text: str):
        """Show a note over the song list for a few seconds."""
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
        if self._list and key not in self._playing_keys:
            return
        self._viewing = None
        if not self._playing_ids:
            if key in self._sel:
                self._sel.remove(key)
            self._show_songs()
            return
        if key not in self._playing_keys:
            return
        self._set_list([k for k in self._list if k != key], keep_order=True)
        if key in self._sel:
            self._sel.remove(key)  # so its + shows again
        self.listReplaced.emit(self._playing_ids)
        if not self._list:
            # only the playing song is left: + on its album puts it back
            self._resume = getattr(self, "_current_id", None)
        self._show_songs()

    def clear_selection(self):
        self._sel, self._viewing, self._click_pick = [], None, False
        self._show_songs()

    def clear_all(self):
        """Empty the list. The playing song finishes, then nothing more plays from here."""
        had = len(self._list)
        if self._list:
            self._set_list([])
            self.listReplaced.emit([])
            self._resume = getattr(self, "_current_id", None)
        self._sel, self._viewing, self._click_pick = [], None, False
        self._show_songs()
        if had:
            self.show_toast("✓  List cleared — the song playing finishes, then nothing more plays")

    def _select_all_or_none(self):
        shown = self.shown_keys()
        if shown and all(k in self._sel for k in shown):
            self.clear_selection()
        else:
            for k in shown:
                if k not in self._sel:
                    self.add_album(k, announce=False) if self._playing_ids else self._sel.append(k)
            self._show_songs()
            QTimer.singleShot(0, self.table.scrollToTop) if not self._list else self._show_current()

    def _table_played(self, _row):
        """A song was double-clicked: play the list from there."""
        ids = self.table.model_.ids()
        if ids:
            if self._viewing is not None:  # a song of the viewed album: play that album
                self._sel, self._viewing = [self._viewing], None
                self._set_list(list(self._sel))
            elif not self._list:  # the selection, in its order
                self._set_list(self.selected_keys())
            # already playing from here: same list, from this song
            QTimer.singleShot(0, self._show_songs)

    def note_current(self, tid):
        """The playing song changed. If it isn't from here, the list becomes a normal selection again."""
        self._current_id = tid
        if self._resume is not None and tid != self._resume:
            self._resume = None
        if self._list and tid not in set(self._playing_ids):
            # music moved on: the albums stay listed as a selection
            self._sel = list(self._list)
            self._set_list([])
            self._show_songs()

    def _show_songs(self):
        playing = bool(self._playing_ids)
        if self._viewing is not None and not playing and not self._sel:
            self._sel, self._viewing, self._click_pick = [self._viewing], None, True  # no list to go back to
        viewing = self._viewing
        self.playing_btn.setVisible(viewing is not None)
        if viewing is not None:
            self.playing_btn.setText("▶  Show what's playing" if playing else "↩  Back to your list")
            self.playing_btn.setToolTip("Back to the songs playing from here" if playing
                                     else "Back to the albums you've added")
        if viewing is not None:
            keys = [viewing]
            playing = False
        elif playing:
            # in play order, added albums at the bottom
            keys = list(self._list)
        else:
            keys = self.selected_keys()
        groups = [a for a in (self._group(k) for k in keys) if a]
        self.grid.viewport().update()
        self.clear_btn.setVisible(bool(groups) and viewing is None)
        if not groups:
            self.table.model_.set_rows([], keep_sort=False)
            self.songs_label.setText("Click an album to see its songs  ·  + on a cover adds it to your selection, "
                                     "− takes it out")
            self._remember()
        else:
            rows = [t for a in groups for t in sorted(a["tracks"], key=_album_order)]
            self.table.model_.set_rows(rows, keep_sort=False)
            length = sum(a["length"] or 0 for a in groups)
            what = ((groups[0]["album"] or "Unknown Album").upper() + "  ·  " + (groups[0]["artist"] or "")
                    if len(groups) == 1 else f"{len(groups)} ALBUMS")
            self.songs_label.setText(("PLAYING  ·  " if playing else "") + f"{what}  ·  {len(rows):,} songs  ·  "
                                     f"{fmt_time(length)}" + ("  ·  + and − change what's playing" if playing else ""))
        self._update_buttons()
        self._remember()

    def _update_buttons(self):
        if not hasattr(self, "grid"):
            return
        n_sel, n_all = len(self._sel), self.grid.count()
        if self._viewing is not None:
            n_sel = 1  # the buttons act on the viewed album
        for b in (self.play_btn, self.shuffle_btn, self.queue_btn):
            b.setEnabled(n_all > 0)
        if n_sel == 0:
            what, tip = ("all", "every album showing")
        elif n_sel == 1:
            what, tip = ("", "the album in your selection")
        else:
            what, tip = (f"{n_sel} albums", f"the {n_sel} albums in your selection")
        self.play_btn.setText(f"Play {what}".strip())
        self.shuffle_btn.setText(f"Shuffle {what}".strip())
        self.play_btn.setToolTip(f"Play {tip}, album by album")
        self.shuffle_btn.setToolTip(f"Play the songs of {tip} in a random order")
        self.queue_btn.setToolTip(f"Add {tip} to the queue")
        shown = self.shown_keys()
        self.select_btn.setText("Clear" if shown and all(k in self._sel for k in shown) else "Add all")

    def _ids(self, key) -> list[int]:
        a = self._group(key)
        return [t["id"] for t in sorted(a["tracks"], key=_album_order)] if a else []

    def _ids_of(self, keys) -> list[int]:
        return [i for k in keys for i in self._ids(k)]

    def _play(self, key, shuffle: bool):
        """Play one album (double-click or Play)."""
        self._sel = [key]
        self._play_keys([key], shuffle)

    def _play_keys(self, keys, shuffle: bool, album_order: str = ""):
        """Play these albums in order, with songs shuffled, or (album_order="random") as whole albums in random order."""
        keys = list(dict.fromkeys(keys))
        self._viewing = None
        if album_order == "random":
            random.shuffle(keys)
        ids = self._ids_of(keys)
        if not ids:
            return
        self._sel = list(keys)
        self._click_pick = False
        self._resume = None
        self._set_list(keys)
        if shuffle:
            ids = list(ids)
            random.shuffle(ids)
            self._playing_ids = ids  # shuffled songs; albums listed as picked
            self._shuffled = True
        self._show_songs()
        self.playRequested.emit(list(self._playing_ids), 0)

    _shuffled = False  # played with Shuffle: + and - keep the shuffled order

    def _set_list(self, keys, keep_order: bool = False):
        """Set the playing list (the single source for the list below, play order and ▶ marks)."""
        old = self._playing_ids
        self._list = [k for k in dict.fromkeys(keys) if self._group(k)]
        self._playing_keys = set(self._list)
        ids = self._ids_of(self._list)
        if keep_order and self._shuffled and old:
            ids = keep_shuffled(old, ids)
        elif not keep_order:
            self._shuffled = False
        self._playing_ids = ids

    def _queue_keys(self, keys):
        ids = self._ids_of(keys)
        if ids:
            self.queueRequested.emit(ids)

    picture_actions = None  # (kind, name, track) -> [(label, fn)], set by the window

    def _view_menu(self, m: QMenu):
        """View options: split by artist, order and cover size."""
        from musicwell.menus import check
        check(m, "Split by artist", self.split_artists, lambda: self._set_split(not self.split_artists))
        sm = m.addMenu("Sort by")
        for k, text in SORTS.items():
            check(sm, text, self.sort == k, lambda k=k: (self.sort_box.setCurrentIndex(self.sort_box.findData(k)),
                                                         self._set_sort(k)))
        zm = m.addMenu("Cover size")
        for k, (text, _px) in COVER_SIZES.items():
            check(zm, text, self.cover_size == k, lambda k=k: self.set_cover_size(k))

    def _menu(self, pos):
        """Right-click menu for one album or a multi-selection."""
        from musicwell.menus import esc, title, tidy
        it = self.grid.itemAt(pos)
        m = QMenu(self)
        sel = self.selected_keys()
        if it is not None and len(sel) > 1 and it.data(KEY) in self._sel:
            n = len(sel)  # right-click on one album of a selection
            title(m, f"{n} albums picked")
            m.addAction("Play", lambda: self._play_keys(sel, False))
            m.addAction("Shuffle the songs", lambda: self._play_keys(sel, True))
            m.addAction("Play the albums in a random order", lambda: self._play_keys(sel, False, "random"))
            m.addAction("Add to queue", lambda: self._queue_keys(sel))
            m.addSeparator()
            m.addAction("Clear the selection", self.clear_selection)
            m.addSeparator()
            self._view_menu(m.addMenu("Cover options"))
        elif it is not None:
            key = it.data(KEY)
            a = self._group(key)
            title(m, (a["album"] if a else "") or "Unknown Album")
            m.addAction("Play", lambda: self._play(key, False))
            m.addAction("Shuffle", lambda: self._play(key, True))
            m.addAction("Add to queue", lambda: self.queueRequested.emit(self._ids(key)))
            where = "what's playing" if self._playing_ids else "your selection"
            if self.in_target(key):
                m.addAction(f"−  Take it out of {where}", lambda: self.remove_album(key))
            else:
                m.addAction(f"+  Add it to {where}", lambda: self.add_album(key))
            m.addSeparator()
            if a and a["various"]:
                am = m.addMenu("Artists on this album")
                for name in sorted(a["artists"], key=str.lower)[:40]:
                    am.addAction(esc(name), lambda n=name: self.artistRequested.emit(n))
            elif a and a["artist"]:
                m.addAction("Go to artist", lambda: self.artistRequested.emit(a["artist"]))
            if a and self.picture_actions and a.get("track"):
                im = m.addMenu("Image")
                from musicwell.menus import add_actions
                add_actions(im, self.picture_actions("album", a["artist"] or a["album"], a["track"]))
            m.addSeparator()
            self._all_menu(m.addMenu("All albums"))
            self._view_menu(m.addMenu("Cover options"))
        else:
            self._all_menu(m)
            m.addSeparator()
            self._view_menu(m)
        tidy(m)
        m.exec(self.grid.viewport().mapToGlobal(pos))

    def _all_menu(self, m: QMenu):
        shown = self.shown_keys()
        if not shown:
            return
        m.addAction(f"Play all {len(shown)} albums", lambda: self._play_keys(shown, False))
        m.addAction("Play them in a random order", lambda: self._play_keys(shown, False, "random"))
        m.addAction("Add them all to your selection", self._select_all_or_none)

    # Only covers near the screen are loaded.
    def _reload_covers(self):
        for i in range(self.grid.count()):
            self.grid.item(i).setData(LOADED, False)
            self.grid.item(i).setIcon(QIcon())
        self._pic_timer.start()

    def _load_visible(self):
        if not self.isVisible():
            return
        dpr = self.devicePixelRatioF() or 1.0
        c = COVER_SIZES[self.cover_size][1]
        vp = self.grid.viewport().rect().adjusted(0, -c, 0, c * 2)
        h = self.grid.viewport().height()
        keep = self.grid.viewport().rect().adjusted(0, -3 * h, 0, 3 * h)  # keep covers within three rows of the screen
        from musicwell.artwork import placeholder
        import time as _time
        t_end = _time.monotonic() + 0.06  # work in slices so the UI stays responsive
        more = False
        for i in range(self.grid.count()):
            it = self.grid.item(i)
            r = self.grid.visualItemRect(it)
            if not r.intersects(vp):
                if it.data(LOADED) and not r.intersects(keep):
                    it.setIcon(QIcon())  # far off-screen: release the image
                    it.setData(LOADED, False)
                continue
            if it.data(LOADED):
                continue
            if _time.monotonic() > t_end:
                more = True
                continue
            t = it.data(TRACK)
            img = self.cover_provider(t, int(c * dpr)) if (self.cover_provider and t) else None
            if img is not None and not img.isNull():
                it.setIcon(QIcon(_rounded(img, c, dpr, 8)))
                it.setData(LOADED, True)
            elif it.icon().isNull():
                k = it.data(KEY)
                ph = placeholder(int(c * dpr), (k.split("\x1f", 1)[-1] if k else "") or "?", QColor(self.theme.accent))
                it.setIcon(QIcon(_rounded(ph, c, dpr, 8)))
        if more:
            self._pic_timer.start()  # continue with the rest

    def cover_ready(self, key: str):
        from musicwell.artwork import album_key
        hit = False
        for i in range(self.grid.count()):
            t = self.grid.item(i).data(TRACK)
            if t and album_key(t) == key:
                self.grid.item(i).setData(LOADED, False)
                hit = True
        if hit:
            self._pic_timer.start()

    def resizeEvent(self, e):
        if self.toast.isVisible():
            self._place_toast()
        super().resizeEvent(e)
        self._pic_timer.start()

    def showEvent(self, e):
        super().showEvent(e)
        self._pic_timer.start()
