"""Discover -> Like this: similar songs, artists, radio stations and free music."""
from __future__ import annotations

import html
import random


from PySide6.QtCore import QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QHBoxLayout, QLabel, QLineEdit, QListView,
                               QListWidget, QListWidgetItem, QMenu, QPushButton, QStackedWidget, QVBoxLayout,
                               QWidget)

from musicwell import radio as R
from musicwell.widgets import SongTable


from musicwell.freemusic import FreeMusicPanel


class SimilarPage(QWidget):
    playIds = Signal(list, int)  # ids, start
    enqueueIds = Signal(list)
    findArtist = Signal(str)
    onlineArtist = Signal(str)
    showArtist = Signal(str)
    playStation = Signal(dict)
    findStation = Signal(dict)
    cleared = Signal()
    findPlaying = Signal()
    playRemote = Signal(list, int)  # online tracks, start
    addToPlaylist = Signal(list, object)  # online tracks, playlist id (None = new playlist)

    def __init__(self, library, theme, parent=None):
        super().__init__(parent)
        self.setObjectName("SimilarPage")
        self.library, self.theme = library, theme
        self.result = None
        self.radio_page = None  # set by the window
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 8, 16, 8)
        v.setSpacing(8)

        head = QHBoxLayout()
        self.title = QLabel("Similar")
        self.title.setObjectName("PageTitle")
        self.title.setWordWrap(True)
        head.addWidget(self.title, 1)
        self.play_btn = QPushButton("Play")
        self.play_btn.setObjectName("Primary")
        self.play_btn.clicked.connect(lambda: self._play(shuffle=False))
        self.shuffle_btn = QPushButton("Shuffle")
        self.shuffle_btn.clicked.connect(lambda: self._play(shuffle=True))
        self.queue_btn = QPushButton("Add to queue")
        self.queue_btn.clicked.connect(lambda: self.result and self.enqueueIds.emit(list(self.result.tracks)))
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setToolTip("Clear these results")
        self.clear_btn.clicked.connect(self.clear)
        for b in (self.play_btn, self.shuffle_btn, self.queue_btn, self.clear_btn):
            head.addWidget(b)
        v.addLayout(head)

        seg = QHBoxLayout()
        self.group = QButtonGroup(self)
        self.songs_seg = QPushButton("Songs")
        self.stations_seg = QPushButton("Stations")
        self.archive_seg = QPushButton("Free music")
        for i, b in enumerate((self.songs_seg, self.stations_seg, self.archive_seg)):
            b.setCheckable(True)
            b.setObjectName("Segment")
            b.setCursor(Qt.PointingHandCursor)
            self.group.addButton(b, i)
            seg.addWidget(b)
        self.group.idClicked.connect(self._picked)
        self._user_picked = False
        seg.addStretch()
        v.addLayout(seg)
        self.note = QLabel("")
        self.note.setObjectName("EmptyText")
        self.note.setWordWrap(True)
        v.addWidget(self.note)

        # shown when nothing has been searched yet
        self.start_box = QWidget()
        sb = QHBoxLayout(self.start_box)
        sb.setContentsMargins(0, 4, 0, 4)
        self.playing_btn = QPushButton("Find similar to the song playing")
        self.playing_btn.setObjectName("Primary")
        self.playing_btn.clicked.connect(self.findPlaying)
        sb.addWidget(self.playing_btn)
        sb.addSpacing(12)
        self.artist_box = QLineEdit()
        self.artist_box.setPlaceholderText("…or find music like an artist (type a name, press Enter)")
        self.artist_box.setClearButtonEnabled(True)
        self.artist_box.returnPressed.connect(
            lambda: self.artist_box.text().strip() and self.findArtist.emit(self.artist_box.text().strip()))
        sb.addWidget(self.artist_box, 1)
        v.addWidget(self.start_box)
        v.addStretch(0)

        self.stack = QStackedWidget()
        v.addWidget(self.stack, 1)

        songs = QWidget()
        sv = QVBoxLayout(songs)
        sv.setContentsMargins(0, 0, 0, 0)
        sv.setSpacing(8)
        self.artists_label = QLabel("Similar artists in your library")
        self.artists_label.setObjectName("SectionTitle")
        sv.addWidget(self.artists_label)
        self.artists = QListWidget()
        self.artists.setObjectName("ArtistChips")
        self.artists.setFlow(QListView.LeftToRight)
        self.artists.setWrapping(True)
        self.artists.setResizeMode(QListView.Adjust)
        self.artists.setSpacing(4)
        self.artists.setUniformItemSizes(False)
        self.artists.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.artists.itemActivated.connect(lambda it: self.findArtist.emit(it.data(Qt.UserRole)))
        self.artists.setContextMenuPolicy(Qt.CustomContextMenu)
        self.artists.customContextMenuRequested.connect(self._artist_menu)
        self.artists.setToolTip("Double-click an artist to find music like theirs. Right-click for more.")
        sv.addWidget(self.artists)
        self.songs_label = QLabel("Songs")
        self.songs_label.setObjectName("SectionTitle")
        sv.addWidget(self.songs_label)
        self.table = SongTable(theme, hidden_by_default=("genre", "playcount", "year"))
        self.table.playRequested.connect(lambda row: self.playIds.emit(self.table.model_.ids(), row))
        sv.addWidget(self.table, 1)
        self.suggest = QLabel("")
        self.suggest.setObjectName("EmptyText")
        self.suggest.setWordWrap(True)
        self.suggest.setOpenExternalLinks(True)
        self.suggest.setTextFormat(Qt.RichText)
        sv.addWidget(self.suggest)
        self.stack.addWidget(songs)

        stations = QWidget()
        tv = QVBoxLayout(stations)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(8)
        self.basis = QLabel("")
        self.basis.setObjectName("EmptyText")
        self.basis.setWordWrap(True)
        tv.addWidget(self.basis)
        self.stations = QListWidget()
        self.stations.setObjectName("StationList")
        self.stations.setMouseTracking(True)
        self.stations.setUniformItemSizes(True)
        self.stations.setSelectionMode(QAbstractItemView.SingleSelection)
        self.stations.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.stations.itemActivated.connect(lambda it: self.playStation.emit(it.data(Qt.UserRole)))
        self.stations.setContextMenuPolicy(Qt.CustomContextMenu)
        self.stations.customContextMenuRequested.connect(self._station_menu)
        self.stations.verticalScrollBar().valueChanged.connect(lambda _: self._want_logos())
        tv.addWidget(self.stations, 1)
        self.stack.addWidget(stations)

        self.free = FreeMusicPanel(library, theme, self)
        self.archive, self.ia_query, self.ia_note = self.free.archive, self.free.ia_query, self.free.ia_note
        self.free.playRemote.connect(self.playRemote)
        self.free.addToPlaylist.connect(self.addToPlaylist)
        self.free.findArtist.connect(self.findArtist)
        self.free.searchStarted.connect(self._free_search_started)
        self.free.countChanged.connect(lambda n, waiting: self.archive_seg.setText(f"Free music ({n})"))
        self.free.emptySearch.connect(lambda: self.result is not None and self.set_archive(self.result))
        self.stack.addWidget(self.free)
        self.show_empty()

    def set_radio_page(self, rp):
        from musicwell.radioview import StationDelegate
        self.radio_page = rp
        self.stations.setItemDelegate(StationDelegate(rp, always_song=True))
        self.free.set_radio_page(rp)
        rp.logoReady.connect(lambda _url: self.stations.viewport().update())
        rp.songsChanged.connect(lambda: self.stations.isVisible() and self.stations.viewport().update())
        # ask what each station is playing when shown, while scrolling, and every minute
        self._song_timer = QTimer(self)
        self._song_timer.setInterval(60_000)
        self._song_timer.timeout.connect(self._want_logos)
        self._song_timer.start()

    # aliases from before the free-music part became FreeMusicPanel
    @property
    def sources(self):
        return self.free.sources

    @sources.setter
    def sources(self, value):
        self.free.sources = value

    @property
    def pool(self):
        return self.free.pool

    @property
    def playing_item(self):
        return self.free.playing_item

    def _fill_archive(self, items: list[dict]):
        self.free.fill(items)

    def _free_search_started(self, text: str):
        if self.result is None:
            self.title.setText("Free music")
            self.clear_btn.setEnabled(True)
            self.start_box.hide()
        self.archive_seg.show()
        self.stack.show()
        self.show_view(2)

    def show_empty(self):
        self.result = None
        self.title.setText("Music like…")
        self.note.setText("Right-click a song and choose Find similar (or press Ctrl+Shift+F while one is "
                          "playing, including on the radio). Musicwell finds songs in your library that go with "
                          "it — from your genres, your listening history and ListenBrainz — and radio stations "
                          "playing that kind of music.")
        self.note.show()
        self.start_box.show()
        for w in (self.songs_seg, self.stations_seg, self.archive_seg, self.stack):
            w.hide()
        for b in (self.play_btn, self.shuffle_btn, self.queue_btn, self.clear_btn):
            b.setEnabled(False)
            b.setVisible(True)

    def show_looking(self, label: str):
        self.title.setText(f"Similar to {label}")
        self.note.setText("Looking…")
        self.note.show()
        self.start_box.hide()
        self.clear_btn.setEnabled(True)

    def clear(self):
        self.table.model_.set_rows([], keep_sort=False)
        self.artists.clear()
        self.stations.clear()
        self.free.clear()
        self.artist_box.clear()
        self.show_empty()
        self.cleared.emit()

    def _picked(self, i: int):
        self._user_picked = True  # don't switch tabs when results arrive
        self.show_view(i)

    def show_view(self, i: int):
        self.group.button(i).setChecked(True)
        self.stack.setCurrentIndex(i)
        for b in (self.play_btn, self.shuffle_btn, self.queue_btn):
            b.setVisible(i == 0)
        self._update_note()
        if i in (1, 2):
            QTimer.singleShot(0, self._want_logos)
        else:
            QTimer.singleShot(0, self._fit_chips)

    def set_result(self, res):
        self.result = res
        self.title.setText(f"Similar to {res.seed_label}")
        self.start_box.hide()
        for w in (self.songs_seg, self.stations_seg, self.archive_seg, self.stack):
            w.show()
        self.clear_btn.setEnabled(True)
        self.ia_query.clear()
        self.songs_seg.setText(f"Songs ({len(res.tracks)})")
        self.stations_seg.setText(f"Stations ({len(res.stations)})")
        self.artists.clear()
        for name, score, n in res.artists[:30]:
            it = QListWidgetItem(f"{name}  ·  {n}")
            it.setData(Qt.UserRole, name)
            it.setToolTip(f"{name}: {n} similar song{'s' if n != 1 else ''} · {int(score * 100)}% alike")
            self.artists.addItem(it)
            it.setSizeHint(QSize(self.artists.fontMetrics().horizontalAdvance(it.text()) + 48, 30))
        self.artists_label.setVisible(bool(res.artists))
        self.artists.setVisible(bool(res.artists))
        rows = [self.library.tracks[i] for i in res.tracks if i in self.library.tracks]
        self.table.model_.set_rows(rows, keep_sort=False)
        self.songs_label.setVisible(bool(rows))
        self.table.setVisible(bool(rows))
        for b in (self.play_btn, self.shuffle_btn, self.queue_btn):
            b.setEnabled(bool(rows))
        if res.suggestions:
            links = []
            for name, mbid, score in res.suggestions[:15]:
                url = f"https://listenbrainz.org/artist/{mbid}/" if mbid else ""
                links.append(f'<a style="color:{self.theme.accent.name()}; text-decoration:none" '
                             f'href="{html.escape(url)}">{html.escape(name)}</a>' if url else html.escape(name))
            self.suggest.setText("<b>Not in your library — you might like:</b> " + ", ".join(links)
                                 + " &nbsp;<span>(from ListenBrainz)</span>")
            self.suggest.show()
        else:
            self.suggest.hide()
        self._user_picked = False
        self.set_stations(res)
        self.set_archive(res)
        # on the radio, stations come first
        self.show_view(1 if (res.seed_kind == "radio" or not res.tracks) and
                       (res.stations or res.stations_pending) else 0)

    def set_stations(self, res):
        if res is not self.result:
            return
        self.stations_seg.setText("Stations (…)" if res.stations_pending else f"Stations ({len(res.stations)})")
        self.stations.clear()
        for st in res.stations:
            it = QListWidgetItem()
            it.setData(Qt.UserRole, st)
            it.setToolTip(f"{st['name']}\n{R.describe(st)}")
            self.stations.addItem(it)
        if res.stations_pending:
            self.basis.setText("Looking for stations…")
        elif res.station_basis:
            self.basis.setText("Stations playing " + ", ".join(res.station_basis)
                               + ("  ·  " + res.station_problem if res.station_problem else ""))
        else:
            self.basis.setText(res.station_problem or "")
        if self.stack.currentIndex() == 1:
            self._update_note()
            QTimer.singleShot(0, self._want_logos)
        elif self.stack.currentIndex() == 0 and not res.tracks and res.stations and not self._user_picked:
            self.show_view(1)  # nothing in the library: show stations

    def set_archive(self, res):
        if res is not self.result:
            return
        mine = self._mine_like(res)
        items = mine + list(res.archive)
        self.archive_seg.setText("Free music (…)" if res.archive_pending else f"Free music ({len(items)})")
        self._fill_archive(items)
        if res.archive_pending:
            self.free._plain_note("Looking in online sources…")
        else:
            note = (f"From online sources, like {res.seed_label}"
                    + (f" ({len(mine)} from your own sources)" if mine else "")
                    + ": double-click to play, right-click to add to a playlist and more")
            if res.archive_problem and not (mine and not res.archive
                                            and res.archive_problem.startswith("Nothing matched")):
                note = res.archive_problem if not items else note + "  ·  " + res.archive_problem
            self.free._plain_note(note)
        if self.stack.currentIndex() == 2:
            QTimer.singleShot(0, self._want_logos)
        elif (not res.archive_pending and items and not res.tracks and not res.stations
              and not res.stations_pending and not self._user_picked):
            self.show_view(2)  # only Archive results

    def _mine_like(self, res) -> list[dict]:
        """Songs from your own sources by the artist and similar artists."""
        my = self.free.my
        if my is None:
            return []
        names = list(getattr(self, "seed_artists", [])) + [a[0] for a in res.artists[:10]]
        out, seen = [], set()
        for name in names:
            if not name:
                continue
            for it in my.search(name, limit=50):
                if it["identifier"] not in seen and name.lower() in (it.get("creator") or "").lower():
                    seen.add(it["identifier"])
                    out.append(it)
            if len(out) >= 60:
                break
        return out

    def set_playing_item(self, ident: str):
        self.free.set_playing_item(ident)

    def refresh_archive(self):
        self.free.refresh()

    def set_playing_available(self, on: bool):
        self.playing_btn.setEnabled(on)

    def _update_note(self):
        res = self.result
        if self.stack.currentIndex() == 2:
            self.note.setText("")
            self.note.hide()
            return
        self.note.show()
        if res is None:
            return
        if self.stack.currentIndex() == 1:
            if res.stations_pending:
                self.note.setText("Looking for stations…")
                return
            n = len(res.stations)
            self.note.setText(f"{n} station{'s' if n != 1 else ''} from radio-browser.info — double-click to "
                              "tune in, ☆ to keep one" if n else "No similar stations found.")
            return
        notes = []
        if not res.tracks:
            notes.append("Nothing in your library is close enough yet. Songs with genre tags, a bigger library "
                         "and a bit of listening history all help.")
        else:
            notes.append(f"{len(res.tracks)} song{'s' if len(res.tracks) != 1 else ''} from your library")
        if res.problem:
            notes.append(res.problem)
        elif not res.used_online and res.seed_kind != "radio":
            notes.append("ListenBrainz is switched off (Settings → Playback), so this uses your library only.")
        self.note.setText(" · ".join(notes))

    def _fit_chips(self):
        """Height for the chips (up to three rows)."""
        if not self.artists.isVisible():
            return
        self.artists.doItemsLayout()
        bottom = 0
        for i in range(self.artists.count()):
            r = self.artists.visualItemRect(self.artists.item(i))
            bottom = max(bottom, r.bottom() + self.artists.verticalScrollBar().value())
        self.artists.setFixedHeight(max(36, min(bottom + 10, 3 * 38 + 10)))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        QTimer.singleShot(0, self._fit_chips)

    def _want_logos(self):
        rp = self.radio_page
        if rp is None:
            return
        self.free.want_logos()
        lst = self.stations
        if not lst.isVisible():
            return
        vp = lst.viewport().rect()
        showing = []
        for i in range(lst.count()):
            it = lst.item(i)
            if lst.visualItemRect(it).intersects(vp.adjusted(0, 0, 0, 3 * 58)):
                rp.logo_image(it.data(Qt.UserRole))  # starts loading the logo if needed
                showing.append(it.data(Qt.UserRole))
        rp.look_up([s for s in showing if isinstance(s, dict) and s.get("url")][:30])

    def refresh_stations(self):
        self.stations.viewport().update()

    def set_current(self, tid):
        self.table.model_.set_current(tid)

    def _play(self, shuffle: bool):
        if not self.result or not self.result.tracks:
            return
        ids = [i for i in self.result.tracks if i in self.library.tracks]
        if shuffle:
            ids = ids[:]
            random.shuffle(ids)
        self.playIds.emit(ids, 0)

    def _artist_menu(self, pos):
        it = self.artists.itemAt(pos)
        if not it:
            return
        name = it.data(Qt.UserRole)
        from musicwell.menus import title
        m = QMenu(self)
        title(m, name)
        m.addAction("Music like them", lambda: self.findArtist.emit(name))
        m.addAction("Search for them", lambda: self.onlineArtist.emit(name))
        m.addSeparator()
        m.addAction("Show in your library", lambda: self.showArtist.emit(name))
        m.exec(self.artists.viewport().mapToGlobal(pos))

    def _station_menu(self, pos):
        it = self.stations.itemAt(pos)
        if not it or self.radio_page is None:
            return
        st = it.data(Qt.UserRole)
        rp = self.radio_page
        from musicwell.menus import title
        m = QMenu(self)
        title(m, st.get("name") or "Station")
        m.addAction("Play", lambda: self.playStation.emit(st))
        fav = rp.is_favourite(st)
        m.addAction("Remove from favourites" if fav else "Add to favourites",
                    lambda: (rp.toggle_favourite(st), self.refresh_stations()))
        m.addSeparator()
        m.addAction("Stations like this one", lambda: self.findStation.emit(st))
        if st.get("homepage"):
            m.addAction("Open the station's website", lambda: QDesktopServices.openUrl(QUrl(st["homepage"])))
        m.exec(self.stations.viewport().mapToGlobal(pos))
