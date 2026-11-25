"""Free music search (Internet Archive, Openverse, Audius) and the Online Sources page."""
from __future__ import annotations

import html

from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QRect, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMenu, QPushButton, QStyle,
                               QStyledItemDelegate, QToolButton, QVBoxLayout, QWidget)

from musicwell import audius, ia, ov

SONGS = ("ov", "src", "au")  # single songs (an Archive item is an album or concert)
SITE_NAMES = {"ov": "Openverse", "au": "Audius"}


def describe(it: dict) -> str:
    if it.get("kind") == "src":
        from musicwell import sources
        return sources.describe(it)
    return ov.describe(it) if it.get("kind") in ("ov", "au") else ia.describe(it)


def where(it: dict) -> str:
    """Source of an online song, for "played from ..."."""
    k = (it or {}).get("kind")
    if k in SITE_NAMES:
        return SITE_NAMES[k]
    if k == "src":
        return it.get("collection") or "your own source"
    return "the Internet Archive"


def site(it: dict) -> str:
    """Site name for "Open on ..."."""
    k = (it or {}).get("kind")
    if k in ("ov", "au"):
        return it.get("badge") or SITE_NAMES[k]
    if k == "src":
        import urllib.parse
        host = urllib.parse.urlsplit(it.get("page") or "").hostname or ""
        return host.removeprefix("www.") or "its website"
    return "archive.org"


def to_track(it: dict, number: int = 0) -> dict:
    if it.get("kind") == "src":
        from musicwell import sources
        return sources.to_track(it, number)
    return ov.to_track(it, number)


def as_logo(it: dict) -> dict:
    """An item in the shape the Radio page's image loader takes."""
    return {"favicon": it.get("image", ""), "name": it.get("title", "?"), "uuid": it["identifier"]}


class ArchiveDelegate(QStyledItemDelegate):
    """Free-music row: image, title, details and licence."""
    ROW_H, PIC = 58, 42

    def __init__(self, panel):
        super().__init__(panel)
        self.page = panel

    def sizeHint(self, option, index):
        return QSize(200, self.ROW_H)

    def paint(self, p: QPainter, option, index):
        it = index.data(Qt.UserRole)
        if not it:
            return
        theme, rp = self.page.theme, self.page.radio_page
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = option.rect
        if option.state & QStyle.State_Selected:
            p.fillRect(r, theme.color("selected"))
        elif option.state & QStyle.State_MouseOver:
            p.fillRect(r, theme.color("hover"))
        pr = QRectF(r.left() + 10, r.top() + (self.ROW_H - self.PIC) / 2, self.PIC, self.PIC)
        if rp is not None:
            path = QPainterPath()
            path.addRoundedRect(pr, 7, 7)
            p.setClipPath(path)
            p.drawPixmap(pr.toRect(), rp.logo_pixmap(as_logo(it)))
            p.setClipping(False)
        playing = self.page.playing_item == it["identifier"]
        tag = "LIVE" if it.get("live") else it.get("badge", "")
        tag_w = p.fontMetrics().horizontalAdvance(tag) + 16 if tag else 0
        x = int(pr.right()) + 12
        w = r.right() - x - 12 - tag_w
        f = QFont(option.font)
        f.setBold(True)
        p.setFont(f)
        p.setPen(theme.accent if playing else theme.color("text"))
        p.drawText(QRect(x, r.top() + 9, w, 20), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(("▶  " if playing else "") + it["title"], Qt.ElideRight, w))
        f.setBold(False)
        f.setPointSizeF(max(7.0, option.font.pointSizeF() - 1))
        p.setFont(f)
        p.setPen(theme.color("muted"))
        line = describe(it) + (f"  ·  {it['license']}" if it.get("license") else "")
        p.drawText(QRect(x, r.top() + 30, w, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(line, Qt.ElideRight, w))
        if tag:
            tr = QRect(r.right() - tag_w - 8, r.top() + (self.ROW_H - 20) // 2, tag_w, 20)
            p.setPen(theme.accent if it.get("live") else theme.color("muted"))
            p.drawRoundedRect(QRectF(tr), 10, 10)
            p.drawText(tr, Qt.AlignCenter, tag)
        p.restore()


class TracksDialog(QDialog):
    """An Internet Archive item's tracks; double-click to play from there."""

    def __init__(self, item: dict, tracks: list[dict], parent=None, playlists=None):
        super().__init__(parent)
        self.setWindowTitle(item["title"])
        self.resize(520, 480)
        self.start = -1
        self.add_to = False  # playlist id (None = new) once "Add to playlist" is used
        self.picked: list[int] = []
        lay = QVBoxLayout(self)
        head = QLabel(f"<b>{html.escape(item['title'])}</b><br>{html.escape(ia.describe(item))}"
                      + (f"<br>{html.escape(item['license'])}" if item.get("license") else ""))
        head.setWordWrap(True)
        lay.addWidget(head)
        self.list = QListWidget()
        self.list.setObjectName("Pane")
        from musicwell.models import fmt_time
        for i, t in enumerate(tracks):
            ln = f"   {fmt_time(t['length'])}" if t.get("length") else ""
            self.list.addItem(f"{t['track'] or i + 1:>2}.  {t['title']}{ln}")
        self.list.itemActivated.connect(lambda _: self._play())
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        lay.addWidget(self.list, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        if playlists is not None:
            add = bb.addButton("Add to playlist", QDialogButtonBox.ActionRole)
            add.setToolTip("Add the selected tracks (all of them, if none are selected) to a playlist")
            menu = QMenu(add)
            menu.addAction("New playlist…", lambda: self._add(None))
            if playlists:
                menu.addSeparator()
            for pid, name in playlists:
                menu.addAction(name, lambda p=pid: self._add(p))
            add.setMenu(menu)
        play = bb.addButton("Play from here", QDialogButtonBox.AcceptRole)
        play.setObjectName("Primary")
        bb.accepted.connect(self._play)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        if tracks:
            self.list.setCurrentRow(0)

    def _play(self):
        self.start = max(0, self.list.currentRow())
        self.accept()

    def _add(self, pid):
        rows = sorted(self.list.row(i) for i in self.list.selectedItems())
        self.picked = rows if len(rows) > 1 else list(range(self.list.count()))
        self.add_to = pid
        self.accept()


class FreeMusicPanel(QWidget):
    """Search box and results for the free sources."""
    playRemote = Signal(list, int)  # online tracks, start
    addToPlaylist = Signal(list, object)  # online tracks, playlist id (None = new playlist)
    findArtist = Signal(str)
    searchStarted = Signal(str)
    countChanged = Signal(int, bool)  # results so far, still searching?
    emptySearch = Signal()  # empty search: the owner may show its own list again
    artistSearch = Signal(str)  # "More by ...": the owner shows the search
    _found = Signal(int, object, str)  # search number, (source, items), problem
    _tracks_found = Signal(object, object, str, str)  # item, tracks, problem, action

    def __init__(self, library, theme, parent=None, placeholder: str = "", credit: bool = True):
        super().__init__(parent)
        self.library, self.theme = library, theme
        self.radio_page = None  # set by the window; images come from the Radio page's loader
        self.playing_item = ""  # item playing, if any
        self.sources = {"ia": True, "ov": True, "au": True}
        self.my = None  # your own sources, searched too
        self.pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="musicwell-archive")
        self._search_n = 0
        self.last_query = ""
        self.known_artists = None  # fn -> library artists (normalised), set by the window
        self.auto_artist = False
        self.query_words, self.query_field = "", "any"
        av = QVBoxLayout(self)
        av.setContentsMargins(0, 0, 0, 0)
        av.setSpacing(8)
        srow = QHBoxLayout()
        self.ia_query = QLineEdit()
        self.ia_query.setPlaceholderText(placeholder or "Search online sources (Internet Archive, Openverse and your "
                                                        "own sources) — an artist, a genre, a title…")
        self.ia_query.setClearButtonEnabled(True)
        self.ia_query.returnPressed.connect(self.search)
        self.go_btn = QPushButton("Search")
        self.go_btn.clicked.connect(lambda: self.search())  # clicked passes "checked", not the text
        # where to look and what to filter out
        from musicwell import freesearch as FS
        from musicwell.paths import settings as _settings
        self.settings = _settings()
        self.field = QComboBox()
        for key, name in FS.FIELDS:
            self.field.addItem(name, key)
        self.field.setToolTip("Where your words must be: anywhere (artist, title, album or genre), or only in the "
                              "artist, the song title, the album or the genre.\nYou can also type it: "
                              "artist:Kestrel   title:Paper Moon   genre:jazz   album:Night Lines")
        cur = self.settings.value("free_search_field", "any") or "any"
        self.field.setCurrentIndex(max(0, self.field.findData(cur)))
        self.field.currentIndexChanged.connect(self._field_changed)
        self.filter_btn = QToolButton()
        self.filter_btn.setText("Filters")
        self.filter_btn.setPopupMode(QToolButton.InstantPopup)
        self.filter_btn.setToolTip("Leave out results that don't really match, short clips, live concerts")
        fm = QMenu(self.filter_btn)
        self.f_strict = fm.addAction("Only close matches (every word where you asked)")
        self.f_short = fm.addAction("Leave out clips under a minute")
        self.f_live = fm.addAction("Leave out live concert recordings")
        for a, key, default in ((self.f_strict, "free_strict", True), (self.f_short, "free_no_short", True),
                                (self.f_live, "free_no_live", False)):
            a.setCheckable(True)
            a.setChecked(self.settings.value(key, default, type=bool))
            a.toggled.connect(lambda on, key=key: (self.settings.setValue(key, on), self._refilter()))
        self.filter_btn.setMenu(fm)
        srow.addWidget(self.field)
        srow.addWidget(self.ia_query, 1)
        srow.addWidget(self.filter_btn)
        # search history (newest first)
        self.history_btn = QToolButton()
        self.history_btn.setText("Recent")
        self.history_btn.setPopupMode(QToolButton.InstantPopup)
        self.history_btn.setToolTip("Your recent searches — click one to search again")
        self.history_menu = QMenu(self.history_btn)
        self.history_menu.aboutToShow.connect(self._fill_history)
        self.history_btn.setMenu(self.history_menu)
        srow.addWidget(self.history_btn)
        srow.addWidget(self.go_btn)
        from PySide6.QtWidgets import QCompleter
        from PySide6.QtCore import QStringListModel
        self._history_model = QStringListModel(self.history(), self)
        comp = QCompleter(self._history_model, self)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        comp.activated.connect(lambda text: self.search(text))
        self.ia_query.setCompleter(comp)
        av.addLayout(srow)
        self.ia_note = QLabel("")
        self.ia_note.setObjectName("EmptyText")
        self.ia_note.setWordWrap(True)
        self.ia_note.linkActivated.connect(self._note_link)
        self._show_loose = False
        av.addWidget(self.ia_note)
        self.archive = QListWidget()
        self.archive.setObjectName("StationList")
        self.archive.setItemDelegate(ArchiveDelegate(self))
        self.archive.setMouseTracking(True)
        self.archive.setUniformItemSizes(True)
        self.archive.setSelectionMode(QAbstractItemView.SingleSelection)
        self.archive.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.archive.itemActivated.connect(lambda it: self.open_item(it.data(Qt.UserRole), "play"))
        self.archive.setContextMenuPolicy(Qt.CustomContextMenu)
        self.archive.customContextMenuRequested.connect(self.menu)
        self.archive.verticalScrollBar().valueChanged.connect(lambda _: self.want_logos())
        av.addWidget(self.archive, 1)
        if credit:
            a = f'style="color:{theme.accent.name()}; text-decoration:none"'
            c = QLabel(f'Free music from the <a {a} href="https://archive.org/details/audio">Internet Archive</a> '
                       "(the Live Music Archive, netlabels, Creative Commons and public-domain recordings) and "
                       f'<a {a} href="https://openverse.org">Openverse</a> (Creative Commons music from Jamendo, '
                       f'Wikimedia Commons and more), <a {a} href="https://audius.co">Audius</a> (independent artists, '
                       "free to stream) and the sources you've added yourself. It plays from those sites; each one's page has the "
                       "licence and the credit.")
            c.setObjectName("EmptyText")
            c.setWordWrap(True)
            c.setOpenExternalLinks(True)
            av.addWidget(c)
        self._found.connect(self._on_found)
        self._tracks_found.connect(self._on_tracks_found)

    def set_radio_page(self, rp):
        self.radio_page = rp
        rp.logoReady.connect(lambda _url: self.archive.viewport().update())

    def fill(self, items: list[dict]):
        self.archive.clear()
        for it in items:
            li = QListWidgetItem()
            li.setData(Qt.UserRole, it)
            tip = f"{it['title']}\n{describe(it)}\n{it.get('license', '')}"
            if it.get("attribution"):
                tip += "\n" + it["attribution"]
            li.setToolTip(tip)
            self.archive.addItem(li)
        QTimer.singleShot(0, self.want_logos)

    def items(self) -> list[dict]:
        return [self.archive.item(i).data(Qt.UserRole) for i in range(self.archive.count())]

    def clear(self):
        self.archive.clear()
        self.ia_query.clear()
        self._plain_note("")
        self._search_n += 1

    def search(self, text: str | None = None):
        if text is not None:
            self.ia_query.setText(text)
        text = self.ia_query.text().strip()
        if not text:
            self.emptySearch.emit()
            return
        from musicwell import freesearch as FS
        words, field = FS.parse(text, self.field.currentData() or "any")
        if words != text:
            # "genre:jazz" typed: set the menu to Genre and the box to jazz
            self.field.blockSignals(True)
            self.field.setCurrentIndex(max(0, self.field.findData(field)))
            self.field.blockSignals(False)
            self.settings.setValue("free_search_field", field)
            self.ia_query.setText(words)
            text = words
        # An artist you have typed with "Anything": search for the artist.
        self.auto_artist = False
        self.name_is_artist = False
        just_artist = self.settings.value("artist_search_mode", "all") == "artist"
        if field in ("any", "artist") and self.known_artists is not None:
            try:
                self.name_is_artist = bool(FS.norm(words)) and FS.norm(words) in self.known_artists()
            except Exception:
                pass
        if getattr(self, "_force_any", False):
            field = "any"
        elif getattr(self, "_force_artist", False):
            field = "artist"
        elif field == "any" and just_artist and self.name_is_artist:
            field, self.auto_artist = "artist", True
        self._force_any = self._force_artist = False
        self._search_n += 1
        n = self._search_n
        self.last_query = text
        self._add_history(text, field)
        self.query_words, self.query_field = words, field
        self._show_loose = False
        text = words
        self.archive.clear()
        self._plain_note(f"Searching online sources: “{text}”…")
        self.searchStarted.emit(text)
        self._results = {"my": None, "ia": None, "ov": None, "au": None}
        self._problems = []
        mine = self.my is not None and self.sources.get("my", True) and any(s.get("on", True) for s in self.my.all())
        if not mine:
            self._results["my"] = []
        else:
            def work_my(n=n):
                try:
                    self._found.emit(n, ("my", self.my.search(text, 400)), "")
                except Exception as e:
                    self._found.emit(n, ("my", []), f"couldn't search your sources ({type(e).__name__})")
            self.pool.submit(work_my)
        if not mine and not any(self.sources.get(k, True) for k in ("ia", "ov", "au")):
            self._plain_note("All the online sources are switched off (Settings → Playback), "
                                 "and you haven't added sources of your own (My sources).")
            return
        for key, fn, name in (("ia", ia.search_text, "the Internet Archive"), ("ov", ov.search_text, "Openverse"),
                              ("au", audius.search_text, "Audius")):
            if not self.sources.get(key, True):
                self._results[key] = []
                continue

            def work(key=key, fn=fn, name=name):
                try:
                    self._found.emit(n, (key, fn(text, field=field)), "")
                except ov.Busy:
                    self._found.emit(n, (key, []), "Openverse is busy (too many searches just now)")
                except Exception as e:
                    self._found.emit(n, (key, []), f"couldn't reach {name} ({type(e).__name__})")
            self.pool.submit(work)

    # search history, kept between sessions
    HISTORY_MAX = 30

    def history(self) -> list[dict]:
        import json
        try:
            v = json.loads(self.settings.value("free_search_history", "[]") or "[]")
        except (TypeError, ValueError):
            return []
        out = []
        for x in v if isinstance(v, list) else []:
            if isinstance(x, dict) and str(x.get("text", "")).strip():
                out.append(x)
            elif isinstance(x, str) and x.strip():
                out.append({"text": x, "field": "any"})
        return out

    def _add_history(self, text: str, field: str):
        import json
        import time as _time
        text = text.strip()
        if not text:
            return
        h = [x for x in self.history() if x["text"].lower() != text.lower()]
        h.insert(0, {"text": text, "field": field or "any", "at": int(_time.time())})
        h = h[:self.HISTORY_MAX]
        self.settings.setValue("free_search_history", json.dumps(h))
        self._history_model.setStringList([x["text"] for x in h])

    def clear_history(self):
        self.settings.setValue("free_search_history", "[]")
        self._history_model.setStringList([])

    def _fill_history(self):
        import datetime as _dt
        from musicwell import freesearch as FS
        m = self.history_menu
        m.clear()
        h = self.history()
        if not h:
            a = m.addAction("No searches yet")
            a.setEnabled(False)
            return
        names = dict(FS.FIELDS)
        for x in h:
            where = names.get(x.get("field", "any"), "")
            when = ""
            if x.get("at"):
                d = _dt.datetime.fromtimestamp(x["at"])
                when = d.strftime("%H:%M") if d.date() == _dt.date.today() else d.strftime("%d %b")
            label = x["text"] + (f"   ·   {where}" if where and x.get("field") != "any" else "")
            act = m.addAction(f"{label}\t{when}".replace("&", "&&"),
                              lambda t=x["text"], f=x.get("field", "any"): self._search_again(t, f))
            act.setToolTip(f"Search for “{x['text']}” again")
        m.addSeparator()
        m.addAction("Clear the search history", self.clear_history)

    def _search_again(self, text: str, field: str):
        i = self.field.findData(field or "any")
        if i >= 0 and i != self.field.currentIndex():
            self.field.blockSignals(True)
            self.field.setCurrentIndex(i)
            self.field.blockSignals(False)
            self.settings.setValue("free_search_field", field)
        self.search(text)

    def _on_found(self, n: int, part, problem: str):
        if n != self._search_n:
            return
        key, items = part
        self._results[key] = items
        if problem:
            self._problems.append(problem)
        self._refilter()

    def load_prefs(self):
        """Settings -> Search changed: reload filters and sources."""
        for a, key, default in ((self.f_strict, "free_strict", True), (self.f_short, "free_no_short", True),
                                (self.f_live, "free_no_live", False)):
            a.blockSignals(True)
            a.setChecked(self.settings.value(key, default, type=bool))
            a.blockSignals(False)
        if self.field.isVisible() or not self.last_query:
            self.field.blockSignals(True)
            self.field.setCurrentIndex(max(0, self.field.findData(self.settings.value("free_search_field", "any"))))
            self.field.blockSignals(False)
        self._refilter()

    def _plain_note(self, text: str):
        self.ia_note.setTextFormat(Qt.PlainText)
        self.ia_note.setText(text)

    def _field_changed(self, _i=None):
        self.settings.setValue("free_search_field", self.field.currentData() or "any")
        if self.ia_query.text().strip() and self.last_query:
            self.search()

    def _note_link(self, link: str):
        if link == "loose":
            self._show_loose = True
            self._refilter()
        elif link == "artist":
            self.field.setCurrentIndex(self.field.findData("artist"))
        elif link == "anything":
            self._force_any = True  # search titles and genres too, this once
            self.search(self.last_query)
        elif link == "justartist":
            self._force_artist = True  # only the artist's songs, this once
            self.search(self.last_query)

    def _refilter(self):
        """Rank results best first and set aside what doesn't fit."""
        results = getattr(self, "_results", None)
        if not results or not self.last_query:
            return
        from musicwell import freesearch as FS
        found = []
        for k in ("my", "au", "ia", "ov"):
            found += list(results.get(k) or [])
        strict = self.f_strict.isChecked() and not self._show_loose
        merged, aside = FS.rank(found, self.query_words, self.query_field, strict=strict,
                                min_seconds=60 if self.f_short.isChecked() else 0,
                                no_live=self.f_live.isChecked())
        if self._show_loose:
            # loose matches after the close ones
            loose, _rest = FS.rank(aside, self.query_words, self.query_field, strict=False,
                                   min_seconds=60 if self.f_short.isChecked() else 0, no_live=self.f_live.isChecked())
            merged += [x for x in loose if x not in merged]
        self.fill(merged)
        import html as _html
        text = _html.escape(self.last_query)
        where = {"artist": " as an artist", "title": " in song titles", "album": " in album titles",
                 "genre": " as a genre"}.get(self.query_field, "")
        waiting = any(v is None for v in results.values())
        n_loose = 0
        if strict:
            loose, _r = FS.rank(aside, self.query_words, self.query_field, strict=False,
                                min_seconds=60 if self.f_short.isChecked() else 0, no_live=self.f_live.isChecked())
            n_loose = len(loose)
        more = (f'  ·  <a href="loose">show {n_loose} looser match{"es" if n_loose != 1 else ""}</a>'
                if n_loose and not waiting else "")
        if self.auto_artist and not waiting:
            more += f'  ·  <a href="anything">also songs with “{text}” in the title or genre</a>'
        elif self.name_is_artist and self.query_field == "any" and not waiting:
            more += f'  ·  <a href="justartist">just songs by {text}</a>'
        if waiting:
            note = f"{len(merged)} so far for “{text}”{where}, still looking…"
        elif merged:
            mine = len([x for x in merged if x.get("kind") == "src"])
            note = (f"{len(merged)} result{'s' if len(merged) != 1 else ''} for “{text}”{where}, best match first"
                    + (f" ({mine} from your own sources)" if mine else "")
                    + " — double-click to play, right-click for more")
        else:
            note = (f"Nothing free matches “{text}”{where}. These sites only have music that's free to share, so "
                    "well-known artists are rarely there — try a genre, or Find similar for free music like them.")
        if self._problems and not waiting:
            note += "  ·  " + _html.escape("; ".join(self._problems))
        self.ia_note.setTextFormat(Qt.RichText)
        a = self.theme.accent.name()
        self.ia_note.setText((note + more).replace('<a href=', f'<a style="color:{a}; text-decoration:none" href='))
        self.countChanged.emit(len(merged), waiting)

    def open_item(self, it: dict, what: str):
        """Fetch the item's track list in the background, then play or show it."""
        if it.get("kind") in SONGS:
            if what.startswith("playlist:"):
                pid = what.split(":", 1)[1]
                self.addToPlaylist.emit([to_track(it, 1)], int(pid) if pid else None)
                return
            # single song: play it, then continue with the listed songs of the same kind
            songs = [r for r in self.items() if r.get("kind") == it["kind"]] or [it]
            start = next((i for i, r in enumerate(songs) if r["identifier"] == it["identifier"]), 0)
            self.playRemote.emit([to_track(r, i + 1) for i, r in enumerate(songs)], start)
            return
        self._plain_note(f"Opening “{it['title']}”…")

        def work():
            try:
                tracks = ia.item_tracks(it)
                self._tracks_found.emit(it, tracks, "" if tracks else "no playable audio files", what)
            except Exception as e:
                self._tracks_found.emit(it, [], f"couldn't reach the Internet Archive ({type(e).__name__})", what)
        self.pool.submit(work)

    def _on_tracks_found(self, it: dict, tracks, problem: str, what: str):
        if problem:
            self._plain_note(f"Couldn't open “{it['title']}”: {problem}.")
            return
        self._plain_note(f"“{it['title']}” — {len(tracks)} track{'s' if len(tracks) != 1 else ''}")
        if what == "tracks":
            dlg = TracksDialog(it, tracks, self, playlists=self.library.playlists())
            if dlg.exec():
                if dlg.add_to is not False:
                    self.addToPlaylist.emit([tracks[r] for r in dlg.picked], dlg.add_to)
                elif dlg.start >= 0:
                    self.playRemote.emit(tracks, dlg.start)
        elif what.startswith("playlist:"):
            pid = what.split(":", 1)[1]
            self.addToPlaylist.emit(tracks, int(pid) if pid else None)
        else:
            self.playRemote.emit(tracks, 0)

    def add_item(self, it: dict, pid):
        """Add an Openverse song, or every track of an Archive item, to a playlist."""
        self.open_item(it, f"playlist:{'' if pid is None else pid}")

    def set_playing_item(self, ident: str):
        self.playing_item = ident
        self.archive.viewport().update()

    def refresh(self):
        self.archive.viewport().update()

    def menu(self, pos):
        li = self.archive.itemAt(pos)
        if not li:
            return
        it = li.data(Qt.UserRole)
        from PySide6.QtGui import QGuiApplication
        from musicwell.menus import esc, title, tidy
        m = QMenu(self)
        title(m, it.get("title") or "")
        m.addAction("Play", lambda: self.open_item(it, "play"))
        if it.get("kind") not in ("src", "ov", "au"):
            m.addAction("Show the tracks…", lambda: self.open_item(it, "tracks"))
        add = m.addMenu("Add to playlist")
        add.addAction("New playlist…", lambda: self.add_item(it, None))
        lists = self.library.playlists()
        if lists:
            add.addSeparator()
        for pid, name in lists:
            add.addAction(esc(name), lambda p=pid: self.add_item(it, p))
        if it.get("creator"):
            m.addSeparator()
            m.addAction(esc(f"More by {it['creator']}"), lambda: self.search_artist(it["creator"]))
            m.addAction(esc(f"Music like {it['creator']}"), lambda: self.findArtist.emit(it["creator"]))
        m.addSeparator()
        if it.get("kind") == "src":
            m.addAction(f"Open its page ({site(it)})", lambda: QDesktopServices.openUrl(QUrl(it["page"])))
            m.addAction("Copy the song's address", lambda: QGuiApplication.clipboard().setText(it["audio_url"]))
        elif it.get("kind") in ("ov", "au"):
            where = it.get("badge") or SITE_NAMES[it["kind"]]
            m.addAction(f"Open on {where} (licence, credit{', download' if it['kind'] != 'au' else ''})",
                        lambda: QDesktopServices.openUrl(QUrl(it["page"])))
            if it.get("attribution"):
                m.addAction("Copy the credit line", lambda: QGuiApplication.clipboard().setText(it["attribution"]))
        else:
            m.addAction("Open on archive.org (licence, download)", lambda: QDesktopServices.openUrl(QUrl(it["page"])))
        tidy(m)
        m.exec(self.archive.viewport().mapToGlobal(pos))

    def search_artist(self, name: str):
        """Songs by this artist from every online source (or anything with the name, per Settings)."""
        field = "artist" if self.settings.value("artist_search_mode", "all") == "artist" else "any"
        self.field.blockSignals(True)
        self.field.setCurrentIndex(max(0, self.field.findData(field)))
        self.field.blockSignals(False)
        self.artistSearch.emit(name)
        self.search(name)

    def want_logos(self):
        rp = self.radio_page
        if rp is None or not self.archive.isVisible():
            return
        vp = self.archive.viewport().rect()
        for i in range(self.archive.count()):
            it = self.archive.item(i)
            if self.archive.visualItemRect(it).intersects(vp):
                rp.logo_image(as_logo(it.data(Qt.UserRole)))  # starts loading the image if needed

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, self.want_logos)


# starter searches on the Online Sources tab
QUICK = ["Jazz", "Classical", "Electronic", "Ambient", "Folk", "Rock", "Blues", "Live concert"]


class SourceDialog(QDialog):
    """Add or edit a source: a feed, online playlist, audio link or web folder."""
    _checked = Signal(object, str)  # songs (or None), message

    def __init__(self, src: dict | None = None, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QComboBox, QFormLayout
        from musicwell import sources as S
        src = dict(src or {})
        self.setWindowTitle("Edit source" if src.get("id") else "Add a music source")
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        intro = QLabel("Add a place online that has music for you to play:\n"
                       "•  a podcast or RSS / Atom feed (a netlabel's or a band's feed, for example)\n"
                       "•  an online playlist — an .m3u, .m3u8 or .pls address\n"
                       "•  a link to one audio file (.mp3, .ogg, .flac, .opus, .m4a…)\n"
                       "•  a web folder — a web page that lists audio files, such as a folder shared from your "
                       "NAS or a server's file listing (the folders under it are read too)\n\n"
                       "Musicwell reads the list of songs and plays them from there; nothing is downloaded. Only "
                       "add sources you're allowed to listen to.")
        intro.setObjectName("EmptyText")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        form = QFormLayout()
        self.name = QLineEdit(src.get("name", ""))
        self.name.setPlaceholderText("e.g. My NAS, Netlabel feed")
        form.addRow("Name", self.name)
        self.url = QLineEdit(src.get("url", ""))
        self.url.setPlaceholderText("https://…")
        self.url.setClearButtonEnabled(True)
        form.addRow("Address", self.url)
        self.kind = QComboBox()
        for k, label in S.KINDS:
            self.kind.addItem(label, k)
        self.kind.setCurrentIndex(max(0, self.kind.findData(src.get("kind", "auto"))))
        form.addRow("Type", self.kind)
        self.note = QLineEdit(src.get("note", ""))
        self.note.setPlaceholderText("Optional: the licence, or a note (shown with its songs)")
        form.addRow("Note", self.note)
        lay.addLayout(form)
        row = QHBoxLayout()
        self.check_btn = QPushButton("Check")
        self.check_btn.setToolTip("Read the source now and say what's there")
        self.check_btn.clicked.connect(self._check)
        row.addWidget(self.check_btn)
        self.result = QLabel("")
        self.result.setObjectName("EmptyText")
        self.result.setWordWrap(True)
        row.addWidget(self.result, 1)
        lay.addLayout(row)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)
        self.name.textChanged.connect(self._validate)
        self.url.textChanged.connect(self._validate)
        self.url.textEdited.connect(self._suggest_name)
        self._checked.connect(self._on_checked)
        self._validate()

    def _suggest_name(self, text: str):
        if not self.name.isModified():
            import urllib.parse
            host = urllib.parse.urlsplit(text.strip()).hostname or ""
            self.name.setText(host.removeprefix("www."))

    def _validate(self):
        import re
        ok = bool(self.name.text().strip()) and bool(re.match(r"^https?://\S+", self.url.text().strip(), re.I))
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(ok)
        self.check_btn.setEnabled(bool(re.match(r"^https?://\S+", self.url.text().strip(), re.I)))

    def _check(self):
        import threading
        from musicwell import sources as S
        spec = dict(self.spec(), id="check")
        self.result.setText("Reading it…")
        self.check_btn.setEnabled(False)

        def work():
            try:
                items, info = S.read(spec)
                kind = S.SHORT.get(info.get("kind"), "")
                self._checked.emit(items, f"Found {len(items)} song{'s' if len(items) != 1 else ''}"
                                          + (f" ({kind.lower()})" if kind else "")
                                          + (f" — “{info['title']}”" if info.get("title") else ""))
            except S.SourceError as e:
                self._checked.emit(None, f"Couldn't use it: {e}.")
            except Exception as e:
                self._checked.emit(None, f"Couldn't use it ({type(e).__name__}: {e}).")
        threading.Thread(target=work, daemon=True).start()

    def _on_checked(self, items, msg: str):
        self.result.setText(msg)
        self.check_btn.setEnabled(True)
        if items and not self.name.text().strip():
            self.name.setText(items[0].get("collection") or "")

    def spec(self) -> dict:
        return {"name": self.name.text().strip(), "url": self.url.text().strip(),
                "kind": self.kind.currentData(), "note": self.note.text().strip()}


class OnlineSourcesPage(QWidget):
    """Discover -> Search online and My sources."""
    viewChanged = Signal(int)  # 0 search, 1 my sources
    playStation = Signal(dict)
    findStation = Signal(dict)
    _stationsFound = Signal(int, object)  # search number, (stations, genres matched on, problem)
    playRemote = Signal(list, int)  # online songs, start
    addToPlaylist = Signal(list, object)  # online songs, playlist id (None = new)
    _refreshed = Signal(str, bool, str)  # source id, ok, message

    def __init__(self, library, theme, my_sources=None, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QButtonGroup, QSplitter, QStackedWidget
        from musicwell.widgets import SongTable
        self.setObjectName("OnlineSourcesPage")
        self.library, self.theme, self.my = library, theme, my_sources
        self._refreshing: set[str] = set()
        self._checked_once = False
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 8, 16, 8)
        v.setSpacing(8)
        head = QHBoxLayout()
        self.title = QLabel("Search online")
        self.title.setObjectName("PageTitle")
        head.addWidget(self.title)
        self.sub = QLabel("Music to play from the Internet Archive, Openverse, Audius and your own sources")
        self.sub.setObjectName("EmptyText")
        self.sub.setWordWrap(True)  # wrap instead of holding the window wide
        head.addWidget(self.sub, 1)
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setToolTip("Clear the search and the results")
        head.addWidget(self.clear_btn)
        v.addLayout(head)

        seg = QHBoxLayout()
        self.group = QButtonGroup(self)
        self.search_seg = QPushButton("Search")
        self.mine_seg = QPushButton("My sources")
        for i, b in enumerate((self.search_seg, self.mine_seg)):
            b.setCheckable(True)
            b.setObjectName("Segment")
            b.setCursor(Qt.PointingHandCursor)
            self.group.addButton(b, i)
            seg.addWidget(b)
            b.hide()  # the Discover switch picks the view
        self.chips = QWidget()
        chips = QHBoxLayout(self.chips)
        chips.setContentsMargins(0, 0, 0, 0)
        chips.setSpacing(6)
        lab = QLabel("Try:")
        lab.setObjectName("EmptyText")
        chips.addWidget(lab)
        self.quick = []
        for word in QUICK:
            b = QPushButton(word)
            b.setObjectName("Segment")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, w=word: (self.show_view(0), self.free.search(w.lower())))
            chips.addWidget(b)
            self.quick.append(b)
        from PySide6.QtWidgets import QSizePolicy
        self.chips.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)  # narrow: the last chips are cut off
        self.chips.setMinimumWidth(0)
        seg.addWidget(self.chips, 1)
        v.addLayout(seg)

        self.stack = QStackedWidget()
        v.addWidget(self.stack, 1)
        self.free = FreeMusicPanel(library, theme, self,
                                   placeholder="Search online sources — an artist, a genre, a title, a band's concerts…")
        self.free.my = my_sources
        # free music, or stations playing that kind of music
        search_view = QWidget()
        sv = QVBoxLayout(search_view)
        sv.setContentsMargins(0, 0, 0, 0)
        sv.setSpacing(6)
        srow = QHBoxLayout()
        self.part_group = QButtonGroup(self)
        self.music_seg = QPushButton("Free music")
        self.stations_seg = QPushButton("Radio stations")
        self.stations_seg.setToolTip("Radio stations playing this kind of music (from the artist's genres, or the "
                                     "words you searched for) — with what each is playing now")
        for i, b in enumerate((self.music_seg, self.stations_seg)):
            b.setCheckable(True)
            b.setObjectName("Segment")
            b.setCursor(Qt.PointingHandCursor)
            self.part_group.addButton(b, i)
            srow.addWidget(b)
        self.music_seg.setChecked(True)
        self.station_basis = QLabel("")
        self.station_basis.setObjectName("EmptyText")
        srow.addWidget(self.station_basis, 1)
        sv.addLayout(srow)
        self.part_stack = QStackedWidget()
        self.part_stack.addWidget(self.free)
        self.station_list = QListWidget()
        self.station_list.setObjectName("StationList")
        self.station_list.setMouseTracking(True)
        self.station_list.setUniformItemSizes(True)
        self.station_list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.station_list.itemActivated.connect(lambda it: self.playStation.emit(it.data(Qt.UserRole)))
        self.station_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.station_list.customContextMenuRequested.connect(self._station_menu)
        self.station_list.verticalScrollBar().valueChanged.connect(lambda _: self._want_station_info())
        self.part_stack.addWidget(self.station_list)
        sv.addWidget(self.part_stack, 1)
        self.part_group.idClicked.connect(self._show_part)
        self.station_finder = None  # set by the window: text -> job returning (stations, genres, problem)
        self.radio_page = None
        self._station_n = 0
        self._stationsFound.connect(self._on_stations)
        self.free.searchStarted.connect(self._find_stations)
        self.stack.addWidget(search_view)
        mine = QSplitter(Qt.Horizontal)
        mine.setChildrenCollapsible(False)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.src_list = QListWidget()
        self.src_list.setObjectName("Pane")
        self.src_list.setToolTip("Untick a source to leave it out of searches. Double-click to change it.")
        acc = theme.accent
        self.src_list.setStyleSheet(
            "QListWidget::item { padding: 6px 4px; }"
            "QListWidget::indicator { width: 14px; height: 14px; border: 1px solid rgba(128,128,128,0.8); "
            "border-radius: 3px; margin-right: 4px; }"
            f"QListWidget::indicator:checked {{ background: {acc.name()}; border-color: {acc.name()}; }}")
        self.src_list.currentItemChanged.connect(lambda *_: self._show_source())
        self.src_list.itemChanged.connect(self._ticked)
        self.src_list.itemDoubleClicked.connect(lambda _: self.edit_source())
        self.src_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.src_list.customContextMenuRequested.connect(self._source_menu)
        ll.addWidget(self.src_list, 1)
        brow = QHBoxLayout()
        self.add_btn = QPushButton("Add source…")
        self.add_btn.setObjectName("Primary")
        self.add_btn.clicked.connect(lambda: self.add_source())
        self.edit_btn = QPushButton("Edit…")
        self.edit_btn.clicked.connect(self.edit_source)
        self.remove_btn = QPushButton("Remove")
        self.remove_btn.clicked.connect(self.remove_source)
        for b in (self.add_btn, self.edit_btn, self.remove_btn):
            brow.addWidget(b)
        ll.addLayout(brow)
        mine.addWidget(left)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 0, 0, 0)
        rh = QHBoxLayout()
        self.src_title = QLabel("")
        self.src_title.setObjectName("SectionTitle")
        rh.addWidget(self.src_title)
        self.src_info = QLabel("")
        self.src_info.setObjectName("EmptyText")
        rh.addWidget(self.src_info, 1)
        self.play_btn = QPushButton("Play")
        self.play_btn.setObjectName("Primary")
        self.play_btn.clicked.connect(lambda: self._play(0))
        self.shuffle_btn = QPushButton("Shuffle")
        self.shuffle_btn.clicked.connect(lambda: self._play(0, shuffle=True))
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setToolTip("Read the source again, for new songs")
        self.refresh_btn.clicked.connect(lambda: self._current() and self.refresh_source(self._current()))
        for b in (self.play_btn, self.shuffle_btn, self.refresh_btn):
            rh.addWidget(b)
        rl.addLayout(rh)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter these songs…")
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(lambda _: self._fill_songs())
        rl.addWidget(self.filter)
        self.src_note = QLabel("")
        self.src_note.setObjectName("EmptyText")
        self.src_note.setWordWrap(True)
        rl.addWidget(self.src_note)
        self.table = SongTable(theme, hidden_by_default=("genre", "playcount", "rating", "year"))
        self.table.playRequested.connect(lambda r: self._play(r))
        self.table.menuRequested.connect(self._song_menu)
        rl.addWidget(self.table, 1)
        mine.addWidget(right)
        mine.setSizes([260, 800])
        self.stack.addWidget(mine)
        self._tracks: list[dict] = []

        self.group.idClicked.connect(self.show_view)
        self.clear_btn.clicked.connect(self.clear)
        self.free.emptySearch.connect(self.show_start)
        self.free.searchStarted.connect(lambda _t: self.show_view(0) if self.stack.currentIndex() != 0 else None)
        self.free.searchStarted.connect(lambda _t: self.refresh_due())
        self._refreshed.connect(self._on_refreshed)
        self.reload_sources()
        self.show_view(0)
        self.show_start()

    def set_radio_page(self, rp):
        from musicwell.radioview import StationDelegate
        self.radio_page = rp
        self.station_list.setItemDelegate(StationDelegate(rp, always_song=True))
        rp.logoReady.connect(lambda _url: self.station_list.viewport().update())
        rp.songsChanged.connect(lambda: self.station_list.isVisible() and self.station_list.viewport().update())
        t = QTimer(self)
        t.setInterval(60_000)
        t.timeout.connect(self._want_station_info)
        t.start()
        self._station_timer = t

    def _show_part(self, i: int):
        self.part_group.button(i).setChecked(True)
        self.part_stack.setCurrentIndex(i)
        self.station_basis.setVisible(i == 1)
        if i == 1:
            QTimer.singleShot(0, self._want_station_info)

    def _find_stations(self, text: str):
        self._station_n += 1
        n = self._station_n
        self.station_list.clear()
        if self.station_finder is None or not text.strip():
            return
        self.stations_seg.setText("Radio stations (…)")
        self.station_basis.setText("Looking for stations…")
        job = self.station_finder(text)

        def work():
            try:
                self._stationsFound.emit(n, job())
            except Exception as e:
                self._stationsFound.emit(n, ([], [], f"Couldn't reach the radio directory ({type(e).__name__})."))
        self.free.pool.submit(work)

    def _on_stations(self, n: int, found):
        if n != self._station_n:
            return
        stations, basis, problem = found
        self.station_list.clear()
        for st in stations:
            it = QListWidgetItem()
            it.setData(Qt.UserRole, st)
            it.setToolTip(f"{st.get('name', '')}\n{st.get('url', '')}")
            self.station_list.addItem(it)
        self.stations_seg.setText(f"Radio stations ({len(stations)})")
        self.station_basis.setText(("Stations playing " + ", ".join(basis) if basis and stations else problem or
                                    "No stations found for this search.") +
                                   ("  ·  double-click to tune in, ☆ to keep one" if stations else ""))
        QTimer.singleShot(0, self._want_station_info)

    def _want_station_info(self):
        """Logos and current songs for the stations on screen."""
        rp, lst = self.radio_page, self.station_list
        if rp is None or not lst.isVisible():
            return
        vp = lst.viewport().rect().adjusted(0, 0, 0, 3 * 58)
        showing = []
        for i in range(lst.count()):
            it = lst.item(i)
            if lst.visualItemRect(it).intersects(vp):
                st = it.data(Qt.UserRole)
                rp.logo_image(st)
                showing.append(st)
        rp.look_up([s for s in showing if isinstance(s, dict) and s.get("url")][:30])

    def _station_menu(self, pos):
        it = self.station_list.itemAt(pos)
        if it is None:
            return
        st = it.data(Qt.UserRole)
        from musicwell.menus import title
        m = QMenu(self)
        title(m, st.get("name") or "Station")
        m.addAction("Play", lambda: self.playStation.emit(st))
        if self.radio_page is not None:
            fav = self.radio_page.is_favourite(st)
            m.addAction("Remove from favourites" if fav else "Add to favourites",
                        lambda: (self.radio_page.toggle_favourite(st), self.station_list.viewport().update()))
        m.addSeparator()
        m.addAction("Stations like this one", lambda: self.findStation.emit(st))
        m.exec(self.station_list.viewport().mapToGlobal(pos))

    def show_view(self, i: int):
        self.group.button(i).setChecked(True)
        self.stack.setCurrentIndex(i)
        self.chips.setVisible(i == 0)
        self.clear_btn.setVisible(i == 0)
        self.title.setText("Search online" if i == 0 else "My sources")
        self.sub.setText("Free music from the Internet Archive, Openverse, Audius and your own sources" if i == 0
                         else "Podcast feeds, online playlists and web folders you've added")
        self.viewChanged.emit(i)
        if i == 1:
            self.refresh_due()
            if self.src_list.currentRow() < 0 and self.src_list.count():
                self.src_list.setCurrentRow(0)
            self._show_source()

    def showEvent(self, e):
        super().showEvent(e)
        if not self._checked_once:
            self._checked_once = True
            QTimer.singleShot(0, self.refresh_due)

    def show_start(self):
        on = [n for k, n in (("ia", "the Internet Archive"), ("ov", "Openverse"), ("au", "Audius"))
              if self.free.sources.get(k, True)]
        n_mine = len([s for s in self.my.all() if s.get("on", True)]) if self.my else 0
        if n_mine:
            on.insert(0, f"your {n_mine} source{'s' if n_mine != 1 else ''}")
        self.free._plain_note(
            "Type an artist, a genre or a title and press Enter, or pick one of the words above. Double-click a "
            "result to play it; right-click to add it to a playlist, see its tracks, or open its page. "
            "Searching: " + (", ".join(on[:-1]) + " and " + on[-1] if len(on) > 1 else (on[0] if on else "nothing"))
            + ". Add your own feeds, playlists and web folders under My sources.")

    def clear(self):
        self.free.clear()
        self._station_n += 1  # a station search still running is dropped
        self.station_list.clear()
        self.stations_seg.setText("Radio stations")
        self.station_basis.setText("Search above to find stations playing that kind of music")
        self.show_start()

    def search(self, text: str):
        self.show_view(0)
        self.free.search(text)

    def reload_sources(self):
        cur = self._current()
        self.src_list.blockSignals(True)
        self.src_list.clear()
        from musicwell import sources as S
        for src in (self.my.all() if self.my else []):
            info = self.my.info(src["id"])
            songs = self.my.songs(src["id"])
            kind = S.SHORT.get(info.get("kind") or src.get("kind"), "")
            n = f"{len(songs)} song{'s' if len(songs) != 1 else ''}" if songs is not None else "not read yet"
            if src["id"] in self._refreshing:
                n = "reading…"
            li = QListWidgetItem(f"{src['name']}\n{kind + ' · ' if kind else ''}{n}")
            li.setData(Qt.UserRole, src["id"])
            li.setFlags(li.flags() | Qt.ItemIsUserCheckable)
            li.setCheckState(Qt.Checked if src.get("on", True) else Qt.Unchecked)
            li.setToolTip(f"{src['url']}\n{src.get('note') or ''}".strip())
            self.src_list.addItem(li)
            if src["id"] == cur:
                self.src_list.setCurrentItem(li)
        self.src_list.blockSignals(False)
        n = self.src_list.count()
        self.mine_seg.setText(f"My sources ({n})" if n else "My sources")
        for b in (self.edit_btn, self.remove_btn):
            b.setEnabled(n > 0)
        if self.stack.currentIndex() == 1:
            self._show_source()

    def _current(self) -> str | None:
        li = self.src_list.currentItem()
        return li.data(Qt.UserRole) if li else None

    def _ticked(self, li):
        if self.my:
            self.my.update(li.data(Qt.UserRole), on=li.checkState() == Qt.Checked)
            self.show_start()

    def add_source(self, url: str = ""):
        if not self.my:
            return
        dlg = SourceDialog({"url": url} if url else None, self)
        if not dlg.exec():
            return
        src = self.my.add(dlg.spec())
        self.reload_sources()
        for i in range(self.src_list.count()):
            if self.src_list.item(i).data(Qt.UserRole) == src["id"]:
                self.src_list.setCurrentRow(i)
        self.show_view(1)
        self.refresh_source(src["id"])

    def edit_source(self):
        sid = self._current()
        src = self.my.get(sid) if (sid and self.my) else None
        if not src:
            return
        dlg = SourceDialog(src, self)
        if not dlg.exec():
            return
        before = (src.get("url"), src.get("kind"))
        spec = dlg.spec()
        self.my.update(sid, **spec)
        self.reload_sources()
        if (spec["url"], spec["kind"]) != before:
            self.refresh_source(sid)

    def remove_source(self):
        from PySide6.QtWidgets import QMessageBox
        sid = self._current()
        src = self.my.get(sid) if (sid and self.my) else None
        if not src:
            return
        r = QMessageBox.question(self, "Remove source", f"Remove “{src['name']}” from your sources?\n\n"
                                 "Songs from it that you've added to playlists stay in them.")
        if r == QMessageBox.Yes:
            self.my.remove(sid)
            self.reload_sources()
            self._show_source()
            self.show_start()

    def refresh_source(self, sid: str):
        src = self.my.get(sid) if self.my else None
        if not src or sid in self._refreshing:
            return
        self._refreshing.add(sid)
        self.reload_sources()
        from musicwell import sources as S

        def work():
            try:
                items = self.my.refresh(src)
                self._refreshed.emit(sid, True, f"{len(items)} songs")
            except S.SourceError as e:
                self._refreshed.emit(sid, False, str(e))
            except Exception as e:
                self._refreshed.emit(sid, False, f"{type(e).__name__}: {e}")
        self.free.pool.submit(work)

    def refresh_due(self):
        """Read sources never read or not read for a day."""
        for src in (self.my.all() if self.my else []):
            if src.get("on", True) and (self.my.songs(src["id"]) is None or self.my.stale(src["id"])):
                self.refresh_source(src["id"])

    def _on_refreshed(self, sid: str, ok: bool, msg: str):
        self._refreshing.discard(sid)
        if not ok:
            self._problems = getattr(self, "_problems", {})
            self._problems[sid] = msg
        else:
            getattr(self, "_problems", {}).pop(sid, None)
        self.reload_sources()
        if sid == self._current():
            self._show_source()

    def _show_source(self):
        sid = self._current()
        src = self.my.get(sid) if (sid and self.my) else None
        has = src is not None
        for w in (self.play_btn, self.shuffle_btn, self.refresh_btn, self.filter):
            w.setEnabled(has)
        if not has:
            self.src_title.setText("No sources yet" if not self.src_list.count() else "")
            self.src_info.setText("")
            self.src_note.setText("Add a source of your own: a podcast or RSS feed, an online playlist (.m3u, .pls), "
                                  "a link to an audio file, or a web folder that lists audio files (a NAS share, a "
                                  "server's file listing). Its songs then show here and in searches.")
            self._tracks = []
            self.table.model_.set_rows([], keep_sort=False)
            return
        self.src_title.setText(src["name"])
        info = self.my.info(sid)
        songs = self.my.songs(sid) or []
        import time as _t
        when = ""
        if info.get("fetched"):
            age = _t.time() - info["fetched"]
            when = "read just now" if age < 120 else (f"read {int(age // 3600)} h ago" if age < 86400 * 2
                                                      else f"read {int(age // 86400)} days ago")
        self.src_info.setText("  ·  ".join(b for b in (f"{len(songs)} songs" if songs else "", when) if b))
        problem = getattr(self, "_problems", {}).get(sid)
        if sid in self._refreshing:
            note = "Reading the source…"
        elif problem:
            note = f"Couldn't read it: {problem}." + (" Showing the songs from last time." if songs else "")
        elif self.my.songs(sid) is None:
            note = "Not read yet — press Refresh."
        else:
            note = ("Double-click a song to play it (and the songs after it). Right-click to add songs to a "
                    "playlist. " + (f"Note: {src['note']}" if src.get("note") else ""))
        self.src_note.setText(note)
        self._source_songs = songs
        self._fill_songs()

    def _fill_songs(self):
        from musicwell import sources as S
        words = [w for w in self.filter.text().lower().split() if w]
        songs = getattr(self, "_source_songs", [])
        if words:
            songs = [it for it in songs if all(w in " ".join((it.get("title", ""), it.get("creator", ""),
                                                               it.get("album", ""))).lower() for w in words)]
        self._tracks = [S.to_track(it, it.get("number") or 0) for it in songs]
        self.table.model_.set_rows(self._tracks, keep_sort=False)
        cur = getattr(self, "_current_id", None)
        if cur is not None:
            self.table.model_.set_current(cur)

    def set_current_song(self, track):
        """Mark the playing song (by URL, since each list makes its own copies)."""
        url = track.get("path") if track and track.get("remote") else None
        self._current_id = next((t["id"] for t in self._tracks if url and t["path"] == url), None)
        self.table.model_.set_current(self._current_id)

    def _play(self, row: int, shuffle: bool = False):
        tracks = list(self.table.model_.rows)
        if not tracks:
            return
        if shuffle:
            import random
            random.shuffle(tracks)
            row = 0
        self.playRemote.emit(tracks, row)

    def _song_menu(self, ids, pos):
        rows = [t for t in self.table.model_.rows if t["id"] in set(ids)]
        if not rows:
            return
        from musicwell.menus import title
        m = QMenu(self)
        title(m, rows[0].get("title") or "" if len(rows) == 1 else f"{len(rows)} songs")
        first = self.table.model_.rows.index(rows[0])
        m.addAction("Play from here", lambda: self._play(first))
        add = m.addMenu("Add to playlist")
        add.addAction("New playlist…", lambda: self.addToPlaylist.emit(rows, None))
        lists = self.library.playlists()
        if lists:
            add.addSeparator()
        for pid, name in lists:
            add.addAction(name, lambda p=pid: self.addToPlaylist.emit(rows, p))
        it = rows[0]["item"]
        from PySide6.QtGui import QGuiApplication
        m.addSeparator()
        if it.get("page"):
            m.addAction(f"Open its page ({site(it)})", lambda: QDesktopServices.openUrl(QUrl(it["page"])))
        m.addAction("Copy the song's address", lambda: QGuiApplication.clipboard().setText(rows[0]["path"]))
        m.exec(pos)

    def _source_menu(self, pos):
        li = self.src_list.itemAt(pos)
        m = QMenu(self)
        if li:
            sid = li.data(Qt.UserRole)
            self.src_list.setCurrentItem(li)
            from musicwell.menus import title
            title(m, li.text())
            m.addAction("Refresh (read it again)", lambda: self.refresh_source(sid))
            m.addAction("Edit…", self.edit_source)
            m.addAction("Move up", lambda: (self.my.move(sid, -1), self.reload_sources()))
            m.addAction("Move down", lambda: (self.my.move(sid, 1), self.reload_sources()))
            src = self.my.get(sid)
            if src:
                from PySide6.QtGui import QGuiApplication
                m.addAction("Copy its address", lambda: QGuiApplication.clipboard().setText(src["url"]))
            m.addSeparator()
            m.addAction("Remove…", self.remove_source)
            m.addSeparator()
        m.addAction("Add source…", lambda: self.add_source())
        m.addAction("Refresh all", lambda: [self.refresh_source(s["id"]) for s in self.my.all()])
        m.exec(self.src_list.viewport().mapToGlobal(pos))


def from_library_search(text: str) -> tuple[str, str] | None:
    """The main search as an online search: artist=bowie -> ('bowie', 'artist')."""
    import re as _re
    q = (text or "").strip()
    m = _re.fullmatch(r'(?i)(artist|albumartist|album|title|genre)\s*[=:~]\s*"?([^"]+?)"?', q)
    if m:
        field = {"albumartist": "artist"}.get(m.group(1).lower(), m.group(1).lower())
        q, f = m.group(2).strip(), field
    else:
        if _re.search(r"[<>#()=!|&]", q) or _re.search(r"\b\w+:", q):
            return None
        f = "any"
    return (q, f) if len(q) >= 3 else None


class OnlineStrip(QWidget):
    """Strip under the library's song list showing the same search in online sources."""
    openChanged = Signal(bool)

    def __init__(self, library, theme, parent=None):
        super().__init__(parent)
        from musicwell.paths import settings as _settings
        self.settings = _settings()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(4)
        self.head = QPushButton("")
        self.head.setObjectName("OnlineStripHead")
        self.head.setFlat(True)
        self.head.setCursor(Qt.PointingHandCursor)
        self.head.setStyleSheet("QPushButton#OnlineStripHead { text-align: left; padding: 4px 8px; }")
        self.head.clicked.connect(lambda: self.set_open(not self.is_open))
        lay.addWidget(self.head)
        self.panel = FreeMusicPanel(library, theme, self, credit=False)
        for w in (self.panel.field, self.panel.ia_query, self.panel.filter_btn, self.panel.go_btn):
            w.hide()
        lay.addWidget(self.panel, 1)
        self.is_open = self.settings.value("lib_online_open", False, type=bool)
        self.panel.setVisible(self.is_open)
        self.query = ""
        self.n, self.waiting = 0, False
        self.panel.countChanged.connect(self._count)
        self.hide()

    def search(self, text: str):
        """Search online for the main search box's words, or hide."""
        asked = from_library_search(text)
        if not asked:
            self.query = ""
            self.panel.clear()
            self.hide()
            return
        q, field = asked
        key = (q, field, self.settings.value("artist_search_mode", "all"))
        if key == getattr(self, "_last", None):
            return
        self._last = key
        self.query = q
        self.panel.field.blockSignals(True)
        self.panel.field.setCurrentIndex(max(0, self.panel.field.findData(field)))
        self.panel.field.blockSignals(False)
        self.n, self.waiting = 0, True
        self._head()
        self.show()
        self.panel.search(q)

    def _count(self, n: int, waiting: bool):
        self.n, self.waiting = n, waiting
        if not waiting and not n:
            self.hide()  # nothing found online: no strip
            return
        self._head()

    def _head(self):
        arrow = "▾" if self.is_open else "▸"
        what = f"“{self.query}”"
        if self.waiting and not self.n:
            text = f"{arrow}  Looking in free online sources for {what}…"
        else:
            by = self.panel.query_field == "artist"
            text = (f"{arrow}  Free online: {self.n} song{'s' if self.n != 1 else ''} or album"
                    f"{'s' if self.n != 1 else ''} {'by' if by else 'for'} {what}"
                    + ("  (still looking…)" if self.waiting else "")
                    + ("" if self.is_open else "  — click to show"))
        self.head.setText(text)

    def set_open(self, on: bool):
        self.is_open = on
        self.settings.setValue("lib_online_open", on)
        self.panel.setVisible(on)
        self._head()
        self.openChanged.emit(on)
