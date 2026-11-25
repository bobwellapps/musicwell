"""The Radio page: search the station directory, keep favourites, see what's playing."""
from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QEvent, QRect, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QGuiApplication, QImage, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu,
                               QMessageBox, QPushButton, QStyle, QStyledItemDelegate, QToolButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from musicwell import radio as R
from musicwell.artwork import placeholder

LIVE_VIEWS = ("favourites", "now", "recent", "popular", "search")  # lists that show what each station plays
VIEWS = [("favourites", "Favourites"), ("now", "What's on now"), ("recent", "Recently played"), ("popular", "Popular"),
         ("search", "Search results"), ("liked", "♥ Liked")]
ROW_H = 58
HEAD_H = 34  # genre heading height in grouped favourites
HEAD = Qt.UserRole + 1  # heading data: (genre, count)
LOGO = 42
STAR_W = 40


# download shops: (name, search URL, what they sell)
BUY_STORES = [
    ("Bandcamp", "https://bandcamp.com/search?q=", "Straight from the artists and labels — MP3, FLAC and more"),
    ("Qobuz", "https://www.qobuz.com/gb-en/search?q=", "Downloads in CD quality and Hi-Res (FLAC)"),
    ("7digital", "https://uk.7digital.com/search?q=", "MP3 and FLAC downloads"),
]


class _TopFirstCombo(QComboBox):
    """Combo box whose list opens below it, 20 rows, scrolled to the top."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMaxVisibleItems(20)
        # plain drop-down, not centred on the current item
        self.setStyleSheet("QComboBox { combobox-popup: 0; }"
                           "QComboBox QAbstractItemView::item { min-height: 24px; padding: 0 8px; }")

    def showPopup(self):
        super().showPopup()
        self.view().scrollToTop()

class StationDelegate(QStyledItemDelegate):
    """Logo, name, description and a favourite star."""

    def __init__(self, page, always_song: bool = False):
        super().__init__(page)
        self.page = page
        self.always_song = always_song  # lists elsewhere (Discover) always show each station's song

    def sizeHint(self, option, index):
        return QSize(200, HEAD_H if index.data(HEAD) else ROW_H)

    def paint(self, p: QPainter, option, index):
        head = index.data(HEAD)
        if head:
            self._paint_heading(p, option, head)
            return
        st = index.data(Qt.UserRole)
        if not st:
            return
        theme = self.page.theme
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = option.rect
        if option.state & QStyle.State_Selected:
            p.fillRect(r, theme.color("selected"))
        elif option.state & QStyle.State_MouseOver:
            p.fillRect(r, theme.color("hover"))
        lr = QRectF(r.left() + 10, r.top() + (ROW_H - LOGO) / 2, LOGO, LOGO)
        pm = self.page.logo_pixmap(st)
        path = QPainterPath()
        path.addRoundedRect(lr, 7, 7)
        p.setClipPath(path)
        p.drawPixmap(lr.toRect(), pm)
        p.setClipping(False)
        playing = self.page.playing_uuid == st["uuid"]
        x = int(lr.right()) + 12
        w = r.right() - x - STAR_W - 8
        f = QFont(option.font)
        f.setBold(True)
        p.setFont(f)
        p.setPen(theme.accent if playing else theme.color("text"))
        name = ("▶  " if playing else "") + st["name"]
        view = "list" if self.always_song else self.page.view
        song_first = view == "now" and self.page.song_first()
        if view == "now" and not song_first:
            line_now = self.page.now_line(st, playing)  # station in bold, its song below
            if playing and self.page.next_text:
                line_now += "   ·   Next: " + self.page.next_text
        if song_first:
            # What's on now: the song is the main line, the station below
            top, bottom = self.page.now_lines(st, playing)
            name = ("▶  " if playing else "") + top
        p.drawText(QRect(x, r.top() + 9, w, 20), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(name, Qt.ElideRight, w))
        f.setBold(False)
        f.setPointSizeF(max(7.0, option.font.pointSizeF() - 1))
        p.setFont(f)
        p.setPen(theme.color("muted"))
        line = R.describe(st) or st["url"]
        if playing and self.page.now_text:
            line = "Now: " + self.page.now_text
        if playing and self.page.next_text:
            line += "   ·   Next: " + self.page.next_text
        if song_first:
            line = bottom
        elif view == "now":
            line = line_now
        elif not playing and (self.always_song or view in LIVE_VIEWS):
            song = self.page.song_line(st)
            if song:
                line = song + "   ·   " + line
        p.drawText(QRect(x, r.top() + 30, w, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(line, Qt.ElideRight, w))
        fav = self.page.is_favourite(st)
        sf = QFont(option.font)
        sf.setPointSizeF(option.font.pointSizeF() + 4)
        p.setFont(sf)
        p.setPen(theme.accent if fav else theme.color("faint"))
        p.drawText(self.star_rect(r), Qt.AlignCenter, "★" if fav else "☆")
        p.restore()

    def _paint_heading(self, p: QPainter, option, head):
        """Genre heading row; clicking folds the group."""
        genre, count = head
        theme = self.page.theme
        folded = genre in self.page.folded
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = option.rect
        if option.state & QStyle.State_MouseOver:
            p.fillRect(r, theme.color("hover"))
        f = QFont(option.font)
        f.setBold(True)
        f.setPointSizeF(option.font.pointSizeF() + 0.5)
        p.setFont(f)
        p.setPen(theme.color("muted"))
        p.drawText(QRect(r.left() + 10, r.top(), 18, r.height()), Qt.AlignCenter, "▸" if folded else "▾")
        p.setPen(theme.color("text"))
        fm = p.fontMetrics()
        p.drawText(QRect(r.left() + 30, r.top(), r.width() - 40, r.height()), Qt.AlignLeft | Qt.AlignVCenter, genre)
        x = r.left() + 30 + fm.horizontalAdvance(genre) + 10
        f.setBold(False)
        f.setPointSizeF(max(7.0, option.font.pointSizeF() - 1))
        p.setFont(f)
        p.setPen(theme.color("faint"))
        p.drawText(QRect(x, r.top(), 200, r.height()), Qt.AlignLeft | Qt.AlignVCenter,
                   f"{count} station{'s' if count != 1 else ''}")
        p.fillRect(QRect(r.left() + 10, r.bottom(), r.width() - 20, 1), theme.color("border"))
        p.restore()

    @staticmethod
    def star_rect(r: QRect) -> QRect:
        return QRect(r.right() - STAR_W - 4, r.top(), STAR_W, r.height())

    def editorEvent(self, event, model, option, index):
        if event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            if index.data(HEAD):
                return False
            if self.star_rect(option.rect).contains(event.position().toPoint()):
                st = index.data(Qt.UserRole)
                if st:
                    self.page.toggle_favourite(st)
                return True
        return super().editorEvent(event, model, option, index)


class AddStreamDialog(QDialog):
    """Add a stream, or edit one."""

    def __init__(self, parent=None, station: dict | None = None):
        super().__init__(parent)
        editing = station is not None
        self.setWindowTitle("Edit stream" if editing else "Add a stream")
        self.setMinimumWidth(540)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(6)
        head = QLabel("Edit stream" if editing else "Add a stream")
        head.setObjectName("PageTitle")
        lay.addWidget(head)
        intro = QLabel("Change the station's name or address — for a station that has moved, say."
                       if editing else
                       "Paste the address of an internet radio stream — a direct stream link, or a .pls / "
                       ".m3u / .m3u8 link from the station's website. It's added to your favourites.")
        intro.setWordWrap(True)
        intro.setObjectName("EmptyText")
        lay.addWidget(intro)
        lay.addSpacing(10)

        def field(label: str, edit: QLineEdit, hint: str = ""):
            lbl = QLabel(label)
            lbl.setObjectName("FieldLabel")
            lay.addWidget(lbl)
            edit.setMinimumHeight(32)
            lay.addWidget(edit)
            if hint:
                h = QLabel(hint)
                h.setObjectName("EmptyText")
                h.setWordWrap(True)
                lay.addWidget(h)
            lay.addSpacing(8)

        self.name = QLineEdit()
        self.name.setPlaceholderText("e.g. My local station")
        self.url = QLineEdit()
        self.url.setPlaceholderText("https://…")
        self.homepage = QLineEdit()
        self.homepage.setPlaceholderText("https://… (optional)")
        self.tags = QLineEdit()
        self.tags.setPlaceholderText("e.g. jazz, soul (optional)")
        field("Name", self.name)
        field("Stream address", self.url)
        self.problem = QLabel("")
        self.problem.setObjectName("ErrorText")
        self.problem.setStyleSheet("color: #e5534b;")
        self.problem.hide()
        lay.addWidget(self.problem)
        field("Website", self.homepage)
        field("Genres", self.tags, "Separate them with commas — the first one is the genre it's listed under.")
        if editing:
            self.name.setText(station.get("name", ""))
            self.url.setText(station.get("url", ""))
            self.homepage.setText(station.get("homepage", ""))
            self.tags.setText(station.get("tags", ""))
        lay.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Save" if editing else "Add")
        bb.button(QDialogButtonBox.Ok).setObjectName("Primary")
        for b in bb.buttons():
            b.setMinimumWidth(90)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        (self.name if not editing else self.url).setFocus()

    def _ok(self):
        u = self.url.text().strip()
        if not u.lower().startswith(("http://", "https://")):
            self.problem.setText("The address must start with http:// or https://")
            self.problem.show()
            self.url.setFocus()
            self.url.selectAll()
            return
        h = self.homepage.text().strip()
        if h and not h.lower().startswith(("http://", "https://")):
            self.homepage.setText("https://" + h)
        self.accept()

    def values(self) -> dict:
        tags = ", ".join(t.strip() for t in self.tags.text().split(",") if t.strip())
        return {"name": self.name.text().strip(), "url": self.url.text().strip(),
                "homepage": self.homepage.text().strip(), "tags": tags}


class RadioPage(QWidget):
    playStation = Signal(dict)
    stopRequested = Signal()
    findStation = Signal(dict)
    likeRequested = Signal()  # like the playing song
    playLibraryTrack = Signal(int)  # play a liked song you have
    findInLibrary = Signal(str, str)  # artist, title
    playCopy = Signal(int, str)  # track id, "start" / "same" / "queue"
    titleOrderChanged = Signal(dict)  # a station's artist/title order changed
    searchFreeMusic = Signal(str)  # "artist title" on the Online Sources tab
    songsByArtist = Signal(str)
    findSimilarArtist = Signal(str)
    _results = Signal(int, str, object, str)  # generation, view, stations, problem
    _lists = Signal(object, object)  # genres, countries
    _logo = Signal(str, bytes)
    _peeked = Signal(str, object, int, str)  # station id, title (None if it never sends one), bytes, problem
    songsChanged = Signal()  # a station reported its song: lists elsewhere redraw

    NOW_EVERY_MS = 60_000  # What's on now refresh interval while visible

    def __init__(self, stations: R.Stations, theme, parent=None):
        super().__init__(parent)
        self.setObjectName("RadioPage")
        self.stations, self.theme = stations, theme
        self.directory = R.Directory()
        self.pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="musicwell-radio")
        self._gen = 0
        self._logos: dict[str, QPixmap] = {}
        self._logo_wanted: set[str] = set()
        self.playing_uuid = ""
        self.now_text = ""
        self.next_text = ""  # "up next" on the playing station, if known
        self.view = "favourites"
        self._cache: dict[str, list] = {}
        self._loaded_lists = False
        self.folded: set[str] = self._load_folded()  # genres folded in grouped favourites
        self.now_titles: dict[str, tuple] = {}  # station id -> (state, text, time)
        self._peeking: set[str] = set()
        self.peek_bytes = 0
        self.peek_pool = ThreadPoolExecutor(max_workers=6, thread_name_prefix="musicwell-whatson")
        self.now_timer = QTimer(self)
        self.now_timer.setInterval(self.NOW_EVERY_MS)
        self.now_timer.timeout.connect(self.refresh_now)

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 8, 16, 8)
        v.setSpacing(8)
        head = QHBoxLayout()
        title = QLabel("Radio")
        title.setObjectName("PageTitle")
        head.addWidget(title)
        head.addStretch()
        self.more_btn = QPushButton("More")
        self.more_menu = QMenu(self.more_btn)
        self.more_btn.setMenu(self.more_menu)
        self.more_menu.aboutToShow.connect(self._fill_more)
        add = QPushButton("Add a stream…")
        add.clicked.connect(self.add_stream)
        head.addWidget(add)
        head.addWidget(self.more_btn)
        v.addLayout(head)

        srow = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("Search stations by name…")
        self.query.setClearButtonEnabled(True)
        self.query.returnPressed.connect(self.search)
        self.genre = _TopFirstCombo()
        self.genre.setEditable(True)
        self.genre.setInsertPolicy(QComboBox.NoInsert)
        if self.genre.completer() is not None:
            self.genre.completer().setMaxVisibleItems(20)
        self.genre.lineEdit().setPlaceholderText("All genres")
        self.genre.lineEdit().setClearButtonEnabled(True)
        self.genre.setMinimumWidth(170)
        self.genre.activated.connect(lambda _: self.search())
        self.genre.lineEdit().returnPressed.connect(self.search)
        self.country = _TopFirstCombo()
        self.country.setMinimumWidth(170)
        self.country.addItem("All countries", "")
        self.country.activated.connect(lambda _: self.search())
        self.country_clear = QToolButton()
        self.country_clear.setText("✕")
        self.country_clear.setAutoRaise(True)
        self.country_clear.setCursor(Qt.PointingHandCursor)
        self.country_clear.setToolTip("Back to all countries")
        self.country_clear.hide()
        self.country_clear.clicked.connect(self._all_countries)
        self.country.currentIndexChanged.connect(lambda i: self.country_clear.setVisible(i > 0))
        go = QPushButton("Search")
        go.setObjectName("Primary")
        go.clicked.connect(self.search)
        srow.addWidget(self.query, 1)
        srow.addWidget(self.genre)
        srow.addWidget(self.country)
        srow.addWidget(self.country_clear)
        srow.addWidget(go)
        v.addLayout(srow)

        seg = QHBoxLayout()
        seg_left = seg
        self.group = QButtonGroup(self)
        self.seg_buttons = {}
        for i, (key, name) in enumerate(VIEWS):
            b = QPushButton(name)
            b.setCheckable(True)
            b.setObjectName("Segment")
            b.setCursor(Qt.PointingHandCursor)
            self.group.addButton(b, i)
            self.seg_buttons[key] = b
            seg.addWidget(b)
        self.group.idClicked.connect(lambda i: self.show_view(VIEWS[i][0]))
        seg = QHBoxLayout()
        self.group_box = QComboBox()
        self.group_box.addItems(["All stations", "By genre"])
        self.group_box.setToolTip("List your favourite stations one after another, or grouped by genre "
                                  "(click a genre to fold it away; right-click a station to put it under "
                                  "another genre)")
        self.group_box.setCurrentIndex(1 if self.stations.s.value("radio_fav_group", "all") == "genre" else 0)
        self.group_box.currentIndexChanged.connect(self._group_changed)
        self.group_label = QLabel("List:")
        self.group_label.setObjectName("EmptyText")
        seg.addWidget(self.group_label)
        seg.addWidget(self.group_box)
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setToolTip("Empty this list")
        self.clear_btn.clicked.connect(self.clear_view)
        self.clear_btn.hide()
        seg.addWidget(self.clear_btn)
        self.like_btn = QPushButton("♥  Like this song")
        self.like_btn.setToolTip("Keep the name of the song playing in your ♥ Liked list (Ctrl+Shift+L)")
        self.like_btn.clicked.connect(self.likeRequested)
        self.like_btn.hide()
        seg.addWidget(self.like_btn)
        # the song on air is in your library
        self.copy_btn = QPushButton("▶  Play your copy")
        self.copy_btn.setObjectName("Primary")
        self.copy_btn.clicked.connect(lambda: self.copy_tid and self.playCopy.emit(self.copy_tid, ""))
        self.copy_btn.setContextMenuPolicy(Qt.CustomContextMenu)
        self.copy_btn.customContextMenuRequested.connect(
            lambda pos: self._copy_menu(self.copy_tid, True, self.copy_btn.mapToGlobal(pos)))
        self.copy_btn.hide()
        self.copy_tid = None
        seg.addWidget(self.copy_btn)
        self.stop_btn = QPushButton("Stop radio")
        self.stop_btn.clicked.connect(self.stopRequested)
        self.stop_btn.hide()
        seg.addWidget(self.stop_btn)
        from musicwell.widgets import WrapRow
        v.addWidget(WrapRow([seg_left, seg]))

        self.list = QListWidget()
        self.list.setObjectName("StationList")
        self.list.setItemDelegate(StationDelegate(self))
        self.list.setMouseTracking(True)
        self.list.setUniformItemSizes(False)  # genre headings are shorter than station rows
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.itemClicked.connect(self._heading_clicked)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list.itemActivated.connect(lambda it: self.play(it.data(Qt.UserRole)))
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        self.list.verticalScrollBar().valueChanged.connect(lambda _: self._want_visible_logos())
        self._scroll_look = QTimer(self, singleShot=True, interval=500)  # after scrolling, ask the stations now visible
        self._scroll_look.timeout.connect(self.refresh_now)
        self.list.verticalScrollBar().valueChanged.connect(lambda _: self._scroll_look.start())
        v.addWidget(self.list, 1)
        self.library = None  # set by the window, to find liked songs you have
        self.liked = QTreeWidget()
        self.liked.setObjectName("LikedList")
        self.liked.setRootIsDecorated(False)
        self.liked.setIndentation(0)
        self.liked.setUniformRowHeights(True)
        self.liked.setAlternatingRowColors(False)
        self.liked.setHeaderLabels(["Song", "Artist", "Heard on", "When", "In your library"])
        self.liked.setSortingEnabled(True)
        h = self.liked.header()
        h.setStretchLastSection(False)
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        h.setSectionResizeMode(1, QHeaderView.Stretch)
        for c in (2, 3, 4):
            h.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.liked.itemActivated.connect(lambda it, _c: self._liked_default(it.data(0, Qt.UserRole)))
        self.liked.setContextMenuPolicy(Qt.CustomContextMenu)
        self.liked.customContextMenuRequested.connect(self._liked_menu)
        self.liked.hide()
        v.addWidget(self.liked, 1)
        self.empty = QLabel("")
        self.empty.setObjectName("EmptyText")
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignCenter)
        v.addWidget(self.empty)
        credit = QLabel(f'Stations from <a style="color:{theme.accent.name()}; text-decoration:none" '
                        'href="https://www.radio-browser.info">radio-browser.info</a>, '
                        "the free community directory. Musicwell plays each station's own stream.")
        credit.setObjectName("EmptyText")
        credit.setOpenExternalLinks(True)
        credit.setWordWrap(True)  # don't hold the window wide
        v.addWidget(credit)

        self._results.connect(self._on_results)
        self._lists.connect(self._on_lists)
        self._logo.connect(self._on_logo)
        self._peeked.connect(self._on_peeked)
        self.show_view("favourites" if self.stations.favourites() else "popular")

    def hideEvent(self, e):
        super().hideEvent(e)
        self.now_timer.stop()

    def showEvent(self, e):
        super().showEvent(e)
        if getattr(self, "_popular_pending", False) and self.view == "popular":
            self._popular_pending = False
            self.show_view("popular")
        if self.view in LIVE_VIEWS:
            self.refresh_now()  # right away when the tab opens
            self.now_timer.start()
        if not self._loaded_lists:
            self._loaded_lists = True
            self._load_lists()
        QTimer.singleShot(0, self._want_visible_logos)

    def clear_view(self):
        """Clear Recently played, or the search results."""
        if self.view == "now":
            self.refresh_now(force=True)
            return
        if self.view == "recent":
            self.stations.clear_recent()
        elif self.view == "search":
            self._cache.pop("search", None)
            self.query.clear()
            self.genre.setCurrentText("")
            self.country.setCurrentIndex(0)
        self.show_view(self.view)

    def show_view(self, key: str):
        self.view = key
        self.seg_buttons[key].setChecked(True)
        for w in (self.group_label, self.group_box):
            w.setVisible(key in ("favourites", "now"))
        self.clear_btn.setVisible(key in ("recent", "search", "now"))
        self.clear_btn.setText({"recent": "Clear recently played", "search": "Clear search"}.get(key, "Look again"))
        self.clear_btn.setToolTip("Check what every favourite station is playing now (it also looks every "
                                  "minute while this list is showing)" if key == "now" else "Empty this list")
        if key in LIVE_VIEWS and self.isVisible():
            self.now_timer.start()
        elif key not in LIVE_VIEWS:
            self.now_timer.stop()
        self.list.setVisible(key != "liked")
        self.liked.setVisible(key == "liked")
        if key == "liked":
            self.fill_liked()
            return
        if key == "now":
            self._fill(self.stations.favourites(),
                       "What's on now shows the song each of your favourite stations is playing.\n"
                       "Search or browse Popular, then click ☆ to keep a station here.")
            self.refresh_now()
        elif key == "favourites":
            self._fill(self.stations.favourites(),
                       "No favourite stations yet.\nSearch or browse Popular, then click ☆ to keep a station here.")
            self.refresh_now()
        elif key == "recent":
            self._fill(self.stations.recent(), "Stations you play will be listed here.")
            self.refresh_now()
        elif key == "popular":
            if "popular" in self._cache:
                self._fill(self._cache["popular"], "")
            elif self.isVisible():
                self._run("popular", lambda: self.directory.popular(100))
            else:
                self._popular_pending = True  # fetched when the tab is first opened
        elif key == "search":
            self._fill(self._cache.get("search", []), "Type a name, pick a genre or a country, then Search.")

    def _all_countries(self):
        """Back to all countries and search again."""
        self.country.setCurrentIndex(0)
        if self.view == "search":
            self.search()

    def search(self):
        name = self.query.text().strip()
        genre = self.genre.currentText().strip()
        if genre.lower().startswith(("any genre", "all genres")):
            genre = ""
        cc = self.country.currentData() or ""
        if not (name or genre or cc):
            self.show_view("popular")
            return
        self.view = "search"
        self.seg_buttons["search"].setChecked(True)
        try:
            limit = int(self.stations.s.value("radio_search_limit", 150))
        except (TypeError, ValueError):
            limit = 150
        self._run("search", lambda: self.directory.search(name=name, tag=genre.lower(), countrycode=cc, limit=limit))

    def _run(self, view: str, fn):
        self._gen += 1
        gen = self._gen
        self.list.clear()
        self.empty.setText("Looking…")
        self.empty.show()

        def work():
            try:
                self._results.emit(gen, view, fn(), "")
            except Exception as e:
                self._results.emit(gen, view, [], str(e) or type(e).__name__)
        self.pool.submit(work)

    def _on_results(self, gen: int, view: str, stations, problem: str):
        if gen != self._gen:
            return
        if problem:
            self._fill([], "Couldn't reach the radio directory (radio-browser.info).\n"
                           "Check your internet connection and try again.\n\n" + problem[:200])
            return
        self._cache[view] = stations
        if self.view == view:
            self._fill(stations, "No stations found. Try fewer words, another genre or All countries.")

    def _fill(self, stations: list[dict], empty_text: str):
        self.list.clear()
        grouped = self.view in ("favourites", "now") and self.grouping()
        groups = self.genre_groups(stations) if grouped else [("", stations)]
        for genre, members in groups:
            if grouped:
                h = QListWidgetItem()
                h.setData(HEAD, (genre, len(members)))
                h.setFlags(Qt.ItemIsEnabled)
                h.setToolTip(f"{genre}: click to {'show' if genre in self.folded else 'fold away'} these stations")
                self.list.addItem(h)
                if genre in self.folded:
                    continue
            for st in members:
                it = QListWidgetItem()
                it.setData(Qt.UserRole, st)
                it.setToolTip(f"{st['name']}\n{R.describe(st)}\n{st['url']}")
                self.list.addItem(it)
        self.empty.setText(empty_text)
        self.empty.setVisible(not stations and bool(empty_text))
        QTimer.singleShot(0, self._want_visible_logos)
        QTimer.singleShot(0, self.refresh_now)

    def refresh(self):
        """Redraw and refill the views built from your own lists."""
        if self.view in ("favourites", "recent", "now"):
            cur = self.list.currentRow()
            self.show_view(self.view)
            if 0 <= cur < self.list.count():
                self.list.setCurrentRow(cur)
        else:
            self.list.viewport().update()

    GENRE_NAMES = {"hiphop": "Hip Hop", "hip hop": "Hip Hop", "hip-hop": "Hip Hop", "rnb": "R&B", "r&b": "R&B",
                   "r'n'b": "R&B", "rhythm and blues": "R&B", "drum and bass": "Drum & Bass", "dnb": "Drum & Bass",
                   "drum'n'bass": "Drum & Bass", "edm": "EDM", "top 40": "Top 40", "top40": "Top 40", "80s": "80s",
                   "70s": "70s", "90s": "90s", "60s": "60s", "00s": "00s", "lofi": "Lo-fi", "lo-fi": "Lo-fi",
                   "news": "News", "talk": "Talk", "classic rock": "Classic Rock", "oldies": "Oldies"}

    def grouping(self) -> bool:
        return self.group_box.currentIndex() == 1

    def _group_changed(self, i: int):
        self.stations.s.setValue("radio_fav_group", "genre" if i == 1 else "all")
        self.show_view(self.view)

    def _load_folded(self) -> set:
        import json as _json
        try:
            v = _json.loads(self.stations.s.value("radio_fav_folded", "[]") or "[]")
            return set(v) if isinstance(v, list) else set()
        except (TypeError, ValueError):
            return set()

    def _save_folded(self):
        import json as _json
        self.stations.s.setValue("radio_fav_folded", _json.dumps(sorted(self.folded)))

    def _own_genres(self) -> dict:
        import json as _json
        try:
            v = _json.loads(self.stations.s.value("radio_fav_genre", "{}") or "{}")
            return v if isinstance(v, dict) else {}
        except (TypeError, ValueError):
            return {}

    def nice_genre(self, tag: str) -> str:
        t = " ".join((tag or "").strip().split())
        if not t:
            return ""
        k = t.lower()
        if k in self.GENRE_NAMES:
            return self.GENRE_NAMES[k]
        if t.isupper() and len(t) <= 4:
            return t  # EDM, UK, ...
        return " ".join(w if (w.isupper() and len(w) <= 4) else w[:1].upper() + w[1:].lower() for w in t.split())

    def station_genres(self, st: dict) -> list[str]:
        out = []
        for tag in (st.get("tags") or "").split(","):
            g = self.nice_genre(tag)
            if g and g not in out:
                out.append(g)
        return out

    def station_genre(self, st: dict) -> str:
        """A favourite's genre: your choice, else its first tag, else "Other"."""
        own = self._own_genres().get(R.station_id(st))
        if own:
            return own
        g = self.station_genres(st)
        return g[0] if g else "Other"

    def genre_groups(self, stations: list[dict]) -> list[tuple[str, list[dict]]]:
        """[(genre, stations in your order)], genres A–Z with Other last."""
        groups: dict[str, list] = {}
        for st in stations:
            groups.setdefault(self.station_genre(st), []).append(st)
        names = sorted(groups, key=lambda g: (g == "Other", g.lower()))
        return [(g, groups[g]) for g in names]

    def favourites_in_order(self) -> list[dict]:
        """Favourites in display order; Next / Previous follow it."""
        favs = self.stations.favourites()
        if not self.grouping():
            return favs
        return [st for _g, members in self.genre_groups(favs) for st in members]

    def set_station_genre(self, st: dict, genre: str | None):
        """Move a favourite to another genre (None = its own first tag)."""
        import json as _json
        d = self._own_genres()
        k = R.station_id(st)
        if genre:
            d[k] = genre
        else:
            d.pop(k, None)
        self.stations.s.setValue("radio_fav_genre", _json.dumps(d))
        self.refresh()

    def _ask_station_genre(self, st: dict):
        from PySide6.QtWidgets import QInputDialog
        known = sorted({self.station_genre(x) for x in self.stations.favourites()} - {"Other"})
        g, ok = QInputDialog.getItem(self, "Genre", f"List “{st['name']}” under:", known, 0, True)
        if ok and g.strip():
            self.set_station_genre(st, self.nice_genre(g))

    def _heading_clicked(self, it):
        head = it.data(HEAD) if it is not None else None
        if not head:
            return
        g = head[0]
        (self.folded.discard if g in self.folded else self.folded.add)(g)
        self._save_folded()
        top = self.list.verticalScrollBar().value()
        self.show_view(self.view)
        self.list.verticalScrollBar().setValue(top)

    def fold_all(self, fold: bool):
        self.folded = {g for g, _m in self.genre_groups(self.stations.favourites())} if fold else set()
        self._save_folded()
        self.show_view(self.view)

    def _live_stations(self) -> list[dict]:
        """Stations in the current list whose songs are looked up. Long lists only check the visible part."""
        if self.view == "recent":
            return self.stations.recent()[:40]
        if self.view in ("popular", "search"):
            vp = self.list.viewport().rect().adjusted(0, 0, 0, 3 * 58)
            out = []
            for i in range(self.list.count()):
                it = self.list.item(i)
                st = it.data(Qt.UserRole)
                if isinstance(st, dict) and st.get("url") and self.list.visualItemRect(it).intersects(vp):
                    out.append(st)
            return out[:30]
        return self.stations.favourites()

    def song_line(self, st: dict) -> str:
        """"♪ Artist – Title" once known, else ""."""
        state, text, _when = self.now_titles.get(R.station_id(st), ("", "", 0))
        if state != "ok" or not text:
            return ""
        artist, title = R.song_parts(st, text)
        line = f"♪  {artist} – {title}" if artist else f"♪  {title}"
        if artist and title and self.stations.is_liked(artist, title):
            line += "  ♥"
        return line

    def refresh_now(self, force: bool = False):
        """Ask each listed station what it's playing (except the one playing)."""
        if self.view not in LIVE_VIEWS or not self.isVisible():
            return
        self.look_up(self._live_stations(), force=force, quick=self.view in ("popular", "search"))

    def look_up(self, stations: list[dict], force: bool = False, quick: bool = True):
        """Ask these stations what they're playing. Stations asked within the last minute are skipped."""
        now = time.time()
        for st in stations:
            k = R.station_id(st)
            if not k or k in self._peeking or st.get("uuid") == self.playing_uuid:
                continue
            state = self.now_titles.get(k)
            if not force and state and now - state[2] < self.NOW_EVERY_MS / 1000 - 5:
                continue
            if state is None:
                self.now_titles[k] = ("checking", "", now)
            self._peeking.add(k)

            def work(k=k, st=dict(st), quick=quick):
                try:
                    title, n = R.now_title(st, quick=quick)
                    self._peeked.emit(k, title, n, "")
                except Exception as e:
                    self._peeked.emit(k, "", 0, str(e) or type(e).__name__)
            self.peek_pool.submit(work)
        self.list.viewport().update()

    def _on_peeked(self, k: str, title, n: int, problem: str):
        self._peeking.discard(k)
        self.peek_bytes += n
        if problem:
            self.now_titles[k] = ("error", problem, time.time())
        elif title is None:
            self.now_titles[k] = ("never", "", time.time())
        elif not title.strip():
            self.now_titles[k] = ("quiet", "", time.time())
        else:
            self.now_titles[k] = ("ok", title.strip(), time.time())
        if self.view in LIVE_VIEWS:
            self.list.viewport().update()
        self.songsChanged.emit()

    def song_first(self) -> bool:
        """Show the song first and the station below it (default: station first)."""
        try:
            return self.stations.s.value("radio_now_song_first", False, type=bool)
        except Exception:
            return False

    def set_song_first(self, on: bool):
        self.stations.s.setValue("radio_now_song_first", bool(on))
        self.list.viewport().update()

    def now_lines(self, st: dict, playing: bool) -> tuple[str, str]:
        """(bold line, line below) for What's on now."""
        station = st["name"]
        if playing:
            text = self.now_text
            state = "ok" if text else "waiting"
        else:
            state, text, _when = self.now_titles.get(R.station_id(st), ("checking", "", 0))
        status = {"checking": "Checking…", "never": "Doesn't say what it's playing",
                  "quiet": "Between songs", "error": "Not answering right now",
                  "waiting": "Waiting for the station to say which song"}
        if state != "ok" or not text:
            return station, status.get(state, "…")  # no song known: the station and why
        artist, title = R.song_parts(st, text)
        top = f"{title} — {artist}" if artist else title
        notes = [f"on {station}"]
        if artist and title:
            if self.stations.is_liked(artist, title):
                notes.append("♥ Liked")
            if self.match_in_library({"artist": artist, "title": title}):
                notes.append("in your library")
        if playing and self.next_text:
            notes.append("Next: " + self.next_text)
        return top, "   ·   ".join(notes)

    def now_line(self, st: dict, playing: bool) -> str:
        """Second line of a station in What's on now."""
        if playing:
            text = self.now_text
            if not text:
                return "▶ Playing now — waiting for the station to say which song"
        else:
            state, text, _when = self.now_titles.get(R.station_id(st), ("checking", "", 0))
            if state == "checking":
                return "Checking…"
            if state == "never":
                return "This station doesn't say what it's playing"
            if state == "quiet":
                return "Between songs (no title right now)"
            if state == "error":
                return "Not answering right now"
        artist, title = R.song_parts(st, text)
        line = f"♪  {artist} – {title}" if artist else f"♪  {title}"
        if artist and title:
            extra = []
            if self.stations.is_liked(artist, title):
                extra.append("♥ Liked")
            if self.match_in_library({"artist": artist, "title": title}):
                extra.append("in your library")
            if extra:
                line += "   ·   " + " · ".join(extra)
        return line

    def _load_lists(self):
        def work():
            try:
                genres = self.directory.tags(120)
            except Exception:
                genres = []
            try:
                countries = self.directory.countries()
            except Exception:
                countries = []
            self._lists.emit(genres, countries)
        self.pool.submit(work)

    def _on_lists(self, genres, countries):
        keep = self.genre.currentText()
        self.genre.clear()
        self.genre.addItem("All genres")
        for name, n in sorted(genres[:120], key=lambda g: g[0].lower()):
            self.genre.addItem(name)
        self.genre.setCurrentText(keep if keep and keep not in ("Any genre", "All genres") else "")
        keep_cc = self.country.currentData() or ""
        self.country.blockSignals(True)
        self.country.clear()
        self.country.addItem("All countries", "")
        for code, name, n in sorted(countries, key=lambda c: c[1].lower()):
            if n >= 3:
                self.country.addItem(name, code)
        self.country.setCurrentIndex(max(0, self.country.findData(keep_cc)))  # keep the previous choice
        self.country.blockSignals(False)
        self.country_clear.setVisible(self.country.currentIndex() > 0)

    def own_pixmap(self, st: dict) -> QPixmap | None:
        """Your own image for this station, if any."""
        cache = self.__dict__.setdefault("_own", {})
        uid = st.get("uuid", "")
        if uid not in cache:
            p = R.own_picture_path(st)
            img = QImage(str(p)) if p.exists() else QImage()
            cache[uid] = None if img.isNull() else QPixmap.fromImage(img)
        return cache[uid]

    pictureChanged = Signal(str)  # station uuid

    def choose_picture(self, st: dict):
        f, _ = QFileDialog.getOpenFileName(self, f"Picture for {st['name']}", os.path.join(os.path.expanduser("~"), "Pictures"),
                                           "Images (*.png *.jpg *.jpeg *.webp *.gif *.bmp *.svg);;All files (*)")
        if f:
            self._set_picture(st, QImage(f))

    def paste_picture(self, st: dict):
        self._set_picture(st, QGuiApplication.clipboard().image())

    def _set_picture(self, st: dict, img: QImage):
        if img.isNull() or not R.set_own_picture(st, img):
            QMessageBox.warning(self, "Station picture", "That picture couldn't be read.")
            return
        self.__dict__.setdefault("_own", {}).pop(st.get("uuid", ""), None)
        self.list.viewport().update()
        self.pictureChanged.emit(st.get("uuid", ""))

    def remove_picture(self, st: dict):
        R.remove_own_picture(st)
        self.__dict__.setdefault("_own", {}).pop(st.get("uuid", ""), None)
        self.list.viewport().update()
        self.pictureChanged.emit(st.get("uuid", ""))

    def picture_actions(self, st: dict) -> list:
        """Menu items for choosing your own station image."""
        own = R.has_own_picture(st)
        acts = [("Change my picture for this station…" if own else "Choose a picture for this station…",
                 lambda: self.choose_picture(st))]
        if not QGuiApplication.clipboard().image().isNull():
            acts.append(("Paste a picture for this station", lambda: self.paste_picture(st)))
        if own:
            acts.append(("Remove my picture" + (" (back to the station's logo)" if st.get("favicon") else ""),
                         lambda: self.remove_picture(st)))
        return acts

    def logo_pixmap(self, st: dict) -> QPixmap:
        own = self.own_pixmap(st)
        if own is not None:
            return own
        url = st.get("favicon") or ""
        if url in self._logos:
            return self._logos[url]
        key = "ph:" + st["name"][:2]
        if key not in self._logos:
            self._logos[key] = QPixmap.fromImage(placeholder(LOGO * 2, st["name"], self.theme.accent, 10))
        return self._logos[key]

    def _want_visible_logos(self):
        if not self.isVisible():
            return
        vp = self.list.viewport().rect()
        for i in range(self.list.count()):
            it = self.list.item(i)
            if not self.list.visualItemRect(it).intersects(vp):
                continue
            url = (it.data(Qt.UserRole) or {}).get("favicon") or ""
            if url and url not in self._logos and url not in self._logo_wanted:
                self._logo_wanted.add(url)
                self.pool.submit(lambda u=url: self._logo.emit(u, R.fetch_logo(u) or b""))

    def logo_image(self, st: dict) -> QImage | None:
        """Station logo for the now playing panel, or None while loading."""
        own = self.own_pixmap(st)
        if own is not None:
            return own.toImage()
        url = st.get("favicon") or ""
        pm = self._logos.get(url)
        if pm is None and url and url not in self._logo_wanted:
            self._logo_wanted.add(url)
            self.pool.submit(lambda u=url: self._logo.emit(u, R.fetch_logo(u) or b""))
        return pm.toImage() if pm is not None and url else None

    logoReady = Signal(str)

    def _on_logo(self, url: str, data: bytes):
        img = QImage.fromData(data) if data else QImage()
        if img.isNull():
            return  # keeps showing the initials
        side = max(img.width(), img.height())
        sq = QImage(side, side, QImage.Format_ARGB32_Premultiplied)
        sq.fill(QColor(255, 255, 255) if img.hasAlphaChannel() else Qt.black)
        p = QPainter(sq)
        p.drawImage((side - img.width()) // 2, (side - img.height()) // 2, img)
        p.end()
        self._logos[url] = QPixmap.fromImage(sq.scaled(256, 256, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.list.viewport().update()
        self.logoReady.emit(url)

    def is_favourite(self, st: dict) -> bool:
        return self.stations.is_favourite(st)

    def toggle_favourite(self, st: dict):
        self.stations.set_favourite(st, not self.stations.is_favourite(st))
        self.refresh()

    def _move_fav(self, st: dict, delta: int):
        """Move a favourite up or down (within its genre when grouped)."""
        favs = self.stations.favourites()
        i = next((k for k, x in enumerate(favs) if x["uuid"] == st["uuid"]), -1)
        if i < 0:
            return
        if self.grouping():
            g = self.station_genre(st)
            same = [k for k, x in enumerate(favs) if self.station_genre(x) == g]
            pos = same.index(i) + delta
            j = same[pos] if 0 <= pos < len(same) else -1
        else:
            j = i + delta
        if 0 <= j < len(favs):
            favs[i], favs[j] = favs[j], favs[i]
            self.stations.save_favourites(favs)
            self.show_view("favourites")
            for r in range(self.list.count()):
                x = self.list.item(r).data(Qt.UserRole)
                if x and x.get("uuid") == st["uuid"]:
                    self.list.setCurrentRow(r)
                    break

    def play(self, st: dict | None):
        if st:
            self.playStation.emit(st)
            self.pool.submit(lambda: self.directory.count_click(st["uuid"]))

    def set_playing(self, st: dict | None, now_text: str = ""):
        old = getattr(self, "playing_station", None)
        if old and self.now_text and (not st or R.station_id(st) != R.station_id(old)):
            # remember what the previous station was playing
            self.now_titles[R.station_id(old)] = ("ok", self.now_text, time.time())
        self.playing_uuid = st["uuid"] if st else ""
        self.playing_station = st
        self.now_text = now_text
        self.stop_btn.setVisible(st is not None)
        self.like_btn.setVisible(st is not None)
        if st is None:
            self.set_copy(None)
        self.update_like_button()
        if self.view == "recent":
            self.refresh()
        else:
            self.list.viewport().update()

    def _menu(self, pos):
        it = self.list.itemAt(pos)
        if it is None:
            return
        if it.data(HEAD):
            g = it.data(HEAD)[0]
            from musicwell.menus import title
            m = QMenu(self)
            title(m, g)
            m.addAction("Show it" if g in self.folded else "Fold it away", lambda: self._heading_clicked(it))
            m.addSeparator()
            m.addAction("Fold all genres away", lambda: self.fold_all(True))
            m.addAction("Show all genres", lambda: self.fold_all(False))
            m.addAction("List all stations (no genres)", lambda: self.group_box.setCurrentIndex(0))
            m.exec(self.list.viewport().mapToGlobal(pos))
            return
        st = it.data(Qt.UserRole)
        if not st:
            return
        from musicwell.menus import esc, title, tidy
        m = QMenu(self)
        m.setToolTipsVisible(True)
        title(m, st.get("name") or "Station")
        tid, on_air = self.song_you_have(st)
        if tid:
            self._copy_actions(m, tid, on_air)
            m.addSeparator()
        m.addAction("Play", lambda: self.play(st))
        fav = self.is_favourite(st)
        m.addAction("Remove from favourites" if fav else "Add to favourites", lambda: self.toggle_favourite(st))
        if fav and self.view == "favourites":
            m.addAction("Move up", lambda: self._move_fav(st, -1))
            m.addAction("Move down", lambda: self._move_fav(st, 1))
        if fav:
            m.addAction("Edit stream…", lambda: self.edit_stream(st))
        m.addSeparator()
        m.addAction("Stations like this one", lambda: self.findStation.emit(st))
        if st.get("tags"):
            first = st["tags"].split(", ")[0]
            m.addAction(esc(f"More “{first}” stations"), lambda: (self.genre.setCurrentText(first), self.query.clear(),
                                                                 self.search()))
        m.addSeparator()
        pics = self.picture_actions(st)
        im = m.addMenu("Image") if len(pics) > 1 else m  # just one: no submenu
        for label, fn in pics:
            im.addAction(label, fn)
        om = m.addMenu("Station options")
        om.setToolTipsVisible(True)
        if fav:
            gm = om.addMenu("Genre to list it under")
            cur = self.station_genre(st)
            own = self._own_genres().get(R.station_id(st))
            for g in self.station_genres(st)[:8] or ["Other"]:
                a = gm.addAction(esc(g), lambda g=g: self.set_station_genre(st, g))
                a.setCheckable(True)
                a.setChecked(g == cur)
            gm.addSeparator()
            gm.addAction("Another genre…", lambda: self._ask_station_genre(st))
            if own:
                gm.addAction("Back to its own genre", lambda: self.set_station_genre(st, None))
        tm = om.addMenu("Song titles")
        tm.setToolTipsVisible(True)
        cur = R.title_order(st)
        for k, text in R.TITLE_ORDERS.items():
            a = tm.addAction(text, lambda k=k: self.set_title_order(st, k))
            a.setCheckable(True)
            a.setChecked(cur == k)
        tm.menuAction().setToolTip("Which way round this station sends the artist and the song title")
        m.addSeparator()
        if st.get("homepage"):
            m.addAction("Open the station's website", lambda: QDesktopServices.openUrl(QUrl(st["homepage"])))
        m.addAction("Copy stream address", lambda: QGuiApplication.clipboard().setText(st["url"]))
        tidy(m)
        m.exec(self.list.viewport().mapToGlobal(pos))

    def song_you_have(self, st: dict) -> tuple:
        """(id, on air) for the song this station is playing if you have it, else (None, False)."""
        playing = bool(self.playing_uuid) and R.station_id(st) == R.station_id(self.playing_station or {})
        if playing:
            text = self.now_text
        else:
            state, text, _when = self.now_titles.get(R.station_id(st), ("checking", "", 0))
            if state != "ok":
                return None, False
        artist, title = R.song_parts(st, text or "")
        if not (artist and title):
            return None, False
        return self.match_in_library({"artist": artist, "title": title}), playing

    def _copy_actions(self, m: QMenu, tid: int, on_air: bool):
        name = ""
        if self.library is not None and tid in self.library.tracks:
            t = self.library.tracks[tid]
            name = f" (“{t.get('title') or ''}”)".replace("&", "&&")
        m.addAction(f"▶  Play your copy{name}", lambda: self.playCopy.emit(tid, "start"))
        if on_air:
            m.addAction("▶  Play your copy from about where the radio is", lambda: self.playCopy.emit(tid, "same"))
        m.addAction("Add your copy to the queue", lambda: self.playCopy.emit(tid, "queue"))

    def _copy_menu(self, tid, on_air: bool, at):
        if not tid:
            return
        m = QMenu(self)
        self._copy_actions(m, tid, on_air)
        m.exec(at)

    def set_copy(self, tid, tip: str = ""):
        """Show or hide "Play your copy"."""
        self.copy_tid = tid
        self.copy_btn.setVisible(bool(tid))
        if tid:
            self.copy_btn.setToolTip((tip or "This song is in your library") +
                                     " — click to play your own copy (right-click for more)")

    def set_title_order(self, st: dict, order: str):
        """Set whether this station sends "Title - Artist", "Artist - Title" or auto."""
        self.stations.set_title_order(st, order)
        self.titleOrderChanged.emit(st)
        self.update_like_button()

    def update_like_button(self):
        artist, title = R.song_parts(getattr(self, "playing_station", None), self.now_text)
        if not self.playing_uuid or not title or not artist:
            self.like_btn.setText("♥  Like this song")
            self.like_btn.setEnabled(False)
            self.like_btn.setToolTip("Waiting for the station to say which song is playing")
            return
        liked = self.stations.is_liked(artist, title)
        self.like_btn.setEnabled(True)
        self.like_btn.setText("♥  Liked" if liked else "♥  Like this song")
        self.like_btn.setObjectName("Primary" if liked else "")
        self.like_btn.style().unpolish(self.like_btn)
        self.like_btn.style().polish(self.like_btn)
        self.like_btn.setToolTip(f"“{title}” by {artist} is in your ♥ Liked list (click to take it out)" if liked
                                 else f"Keep “{title}” by {artist} in your ♥ Liked list (Ctrl+Shift+L)")

    def match_in_library(self, x: dict) -> int | None:
        """Library id of a liked song, if you have it."""
        lib = self.library
        if lib is None:
            return None
        k = R.Stations.liked_key(x.get("artist", ""), x["title"])
        cache = getattr(self, "_lib_index", None)
        if cache is None or cache[0] != len(lib.tracks):
            idx = {}
            for t in lib.tracks.values():
                for a in {t.get("artist") or "", t.get("albumartist") or ""}:
                    if a:
                        idx.setdefault(R.Stations.liked_key(a, t.get("title") or ""), t["id"])
            cache = self._lib_index = (len(lib.tracks), idx)
        return cache[1].get(k)

    def fill_liked(self):
        import time as _t
        self.liked.setSortingEnabled(False)
        self.liked.clear()
        items = self.stations.liked()
        for x in items:
            tid = self.match_in_library(x)
            when = _t.strftime("%d %b %Y, %H:%M", _t.localtime(x.get("time", 0)))
            it = QTreeWidgetItem([x["title"], x.get("artist", ""), x.get("station", ""), when,
                                  "✓  Yes" if tid else ""])
            it.setData(0, Qt.UserRole, x)
            it.setData(3, Qt.UserRole, x.get("time", 0))
            it.setToolTip(0, "Double-click to play it from your library" if tid else
                          "Double-click to look for it in Discover → Search online (free music). Right-click for more.")
            self.liked.addTopLevelItem(it)
        self.liked.setSortingEnabled(True)
        self.liked.sortItems(3, Qt.DescendingOrder)
        n = len(items)
        self.seg_buttons["liked"].setText(f"♥ Liked ({n})" if n else "♥ Liked")
        self.empty.setText("" if n else "Songs you ♥ while listening to the radio are kept here — with the "
                                        "station and when you heard them — so you can find them later.")
        self.empty.setVisible(not n)

    def _liked_default(self, x: dict):
        tid = self.match_in_library(x)
        if tid:
            self.playLibraryTrack.emit(tid)
        else:
            self.searchFreeMusic.emit(f"{x.get('artist', '')} {x['title']}".strip())

    def _liked_menu(self, pos):
        it = self.liked.itemAt(pos)
        if it is None:
            return
        x = it.data(0, Qt.UserRole)
        artist, title = x.get("artist", ""), x["title"]
        q = f"{artist} {title}".strip()
        tid = self.match_in_library(x)
        from musicwell.menus import esc, tidy, title as title_menu
        m = QMenu(self)
        title_menu(m, f"{artist} – {title}" if artist else title)
        if tid:
            m.addAction("Play it from your library", lambda: self.playLibraryTrack.emit(tid))
        m.addAction("Search your library", lambda: self.findInLibrary.emit(artist, title))
        dm = m.addMenu("Discover")
        if artist:
            dm.addAction(esc(f"Search for {artist}"), lambda: self.songsByArtist.emit(artist))
            dm.addAction(esc(f"Music like {artist}"), lambda: self.findSimilarArtist.emit(artist))
        else:
            dm.addAction(esc(f"Search for “{title}”"), lambda: self.searchFreeMusic.emit(q))
        m.addSeparator()
        buy = m.addMenu("Buy it from")
        for name, url, note in BUY_STORES:
            act = buy.addAction(name, lambda u=url: QDesktopServices.openUrl(
                QUrl(u + QUrl.toPercentEncoding(q).data().decode())))
            act.setToolTip(note)
        buy.setToolTipsVisible(True)
        m.addAction("Search the web", lambda: QDesktopServices.openUrl(
            QUrl("https://duckduckgo.com/?q=" + QUrl.toPercentEncoding(q).data().decode())))
        m.addAction("Copy “artist – title”", lambda: QGuiApplication.clipboard().setText(
            f"{artist} – {title}" if artist else title))
        m.addSeparator()
        m.addAction("Remove from ♥ Liked", lambda: (self.stations.unlike(x["key"]), self.fill_liked(),
                                                    self.update_like_button()))
        tidy(m)
        m.exec(self.liked.viewport().mapToGlobal(pos))

    def export_liked(self):
        f, _ = QFileDialog.getSaveFileName(self, "Export liked songs",
                                           os.path.join(os.path.expanduser("~"), "Liked on the radio.csv"),
                                           "Spreadsheet (*.csv)")
        if f:
            try:
                self.stations.export_liked(f)
            except OSError as e:
                QMessageBox.warning(self, "Export liked songs", f"Couldn't save the file: {e.strerror}")

    def clear_liked(self):
        if QMessageBox.question(self, "♥ Liked", "Clear your whole ♥ Liked list?") == QMessageBox.Yes:
            self.stations.clear_liked()
            self.fill_liked()
            self.update_like_button()

    def _fill_more(self):
        m = self.more_menu
        m.clear()
        m.addAction("Add a stream…", self.add_stream)
        m.addAction("Import stations from a playlist file (.m3u / .pls)…", self.import_file)
        m.addAction("Export favourites as a playlist (.m3u)…", self.export_file)
        m.addSeparator()
        m.addAction("Clear recently played", lambda: (self.stations.clear_recent(),
                                                      self.view == "recent" and self.show_view("recent")))
        m.addSeparator()
        m.addAction("Export ♥ Liked songs (.csv)…", self.export_liked)
        m.addSeparator()
        a = m.addAction("What's on now: the song first, the station under it")
        a.setCheckable(True)
        a.setChecked(self.song_first())
        a.toggled.connect(self.set_song_first)
        s = self.stations.s
        b = m.addAction("Show the stations' own pictures of their songs")
        b.setCheckable(True)
        b.setChecked(s.value("radio_song_pictures", "true") == "true")
        b.setToolTip("Some stations send a picture of the song or artist with its title — shown in place of "
                     "the station's logo")
        b.toggled.connect(lambda on: s.setValue("radio_song_pictures", "true" if on else "false"))
        m.addAction("Clear ♥ Liked…", self.clear_liked)

    def add_stream(self):
        dlg = AddStreamDialog(self)
        if dlg.exec():
            v = dlg.values()
            st = R.custom_station(v["name"], v["url"])
            st["homepage"], st["tags"] = v["homepage"], v["tags"]
            self.stations.set_favourite(st, True)
            self.show_view("favourites")

    def edit_stream(self, st: dict):
        """Edit a station's name, URL, website or genres. It keeps its place and image."""
        dlg = AddStreamDialog(self, st)
        if not dlg.exec():
            return
        v = dlg.values()
        new = dict(st)
        new.update(v)
        new["name"] = v["name"] or v["url"]
        if v["url"] != st.get("url"):
            new["hls"] = v["url"].lower().split("?")[0].endswith(".m3u8")
        self.stations.update_station(new)
        self.refresh()

    def import_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "Import stations", os.path.expanduser("~"),
                                           "Playlists (*.m3u *.m3u8 *.pls *.txt)")
        if not f:
            return
        try:
            found = R.Stations.read_playlist_file(f)
        except OSError as e:
            QMessageBox.warning(self, "Import stations", f"Couldn't read the file: {e.strerror}")
            return
        for st in found:
            if not self.stations.is_favourite(st):
                self.stations.set_favourite(st, True)
        QMessageBox.information(self, "Import stations",
                                f"Added {len(found)} station{'s' if len(found) != 1 else ''} to your favourites."
                                if found else "No stream addresses were found in that file.")
        self.show_view("favourites")

    def export_file(self):
        f, _ = QFileDialog.getSaveFileName(self, "Export favourites",
                                           os.path.join(os.path.expanduser("~"), "Radio stations.m3u"),
                                           "Playlist (*.m3u)")
        if f:
            try:
                self.stations.export(f)
            except OSError as e:
                QMessageBox.warning(self, "Export favourites", f"Couldn't save the file: {e.strerror}")

    def refresh_theme(self):
        self._logos = {k: v for k, v in self._logos.items() if not k.startswith("ph:")}
        self.list.viewport().update()

    def shutdown(self):
        self.pool.shutdown(wait=False, cancel_futures=True)
