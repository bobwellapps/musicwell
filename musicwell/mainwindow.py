"""The main window: connects the library, player and widgets."""
from __future__ import annotations

import json
import html as _html
import time
import os
from time import monotonic as time_now

from PySide6.QtCore import QByteArray, QEvent, QItemSelectionModel, QObject, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QDialog, QFileDialog, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMainWindow, QMenu, QMessageBox, QPushButton, QSizePolicy, QSplitter,
                               QStackedWidget, QVBoxLayout, QWidget, QFrame, QProgressBar)

from musicwell import APP_NAME
from musicwell import theme as th
from musicwell.tags import album_title
from musicwell.artwork import ImageStore, accent_from_image, album_key, palette_from_image, primary_artist
from musicwell.dialogs import (BrowserColumnsDialog, CustomFieldDialog, SettingsDialog, TagEditor,
                              ask_music_folder, music_dir)
from musicwell.library import Library
from musicwell.models import fmt_time
from musicwell.player import Player
from musicwell.query import compile_query
from musicwell import cast as cast_mod
from musicwell import casting
from musicwell import fields as F
from musicwell.eqwindow import EqualizerWindow, load_eq_settings
from musicwell.panel import DEFAULT_ORDER as PANEL_ORDER, BarItem, BarSource, NowPlayingPanel
from musicwell.bar import CONTROLS, PANEL_ITEMS, TOP_ITEMS, PlayBar, _CopyButton, control_name
from musicwell.lyrics import LyricsStore
from musicwell.lyricsview import LyricsPage
from musicwell.waveform import WaveformStore
from musicwell.widgets import (DEFAULT_PANES, PANE_FIELDS, PANE_PRESETS, ColumnBrowser, IconButton,
                              SearchBox, SongTable, scale_text, text_size_menu)

SEL_ROWS = QItemSelectionModel.Select | QItemSelectionModel.Rows


PANEL2_DEFAULTS = {"order": ["lyrics", "upnext", "details", "stats", "fields"], "hidden": []}
# the top panel's default items
PANEL3_DEFAULTS = {"order": ["artwork", "title", "artist", "album", "rating", "upnext"], "hidden": []}


TOP_PANEL_ITEMS = ("title", "artist", "album", "details", "stats", "cast")  # panel items small enough for the top bar


class _DeleteKey(QObject):
    """Unlocked: the Delete key removes the item under the mouse (except while typing)."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win

    def eventFilter(self, obj, e):
        if e.type() == QEvent.KeyPress and e.key() == Qt.Key_Delete and not e.modifiers() \
                and getattr(self.win, "customizing", False) and self.win.isActiveWindow():
            from PySide6.QtWidgets import QLineEdit, QTextEdit, QPlainTextEdit
            fw = QApplication.focusWidget()
            if isinstance(fw, QLineEdit) and fw.text():
                return False  # typing in a box: Delete deletes text
            if isinstance(fw, (QTextEdit, QPlainTextEdit)):
                return False
            if e.isAutoRepeat():
                return True
            try:
                return self.win.delete_under_mouse()
            except Exception:
                return False
        return False


class _UndoKeys(QObject):
    """Ctrl+Z in a text box with nothing of its own to undo undoes the last layout change instead."""

    def eventFilter(self, obj, e):
        if e.type() == QEvent.ShortcutOverride and isinstance(obj, QLineEdit):
            if (e.matches(QKeySequence.Undo) and not obj.isUndoAvailable()) or \
                    (e.matches(QKeySequence.Redo) and not obj.isRedoAvailable()):
                e.ignore()
                return True
        return False


# The Radio and Lyrics tabs' own panel, as it starts.
def tab_panel_defaults() -> dict:
    from musicwell import layouts as layouts_mod
    return layouts_mod._panel(["artist_image", "spacer:1", "artwork", "visualizer", "title", "artist", "album",
                               "like"], hidden=[], align="center", spacers={"spacer:1": {"h": 24, "line": False}},
                              heights={"artist_image": 200, "artwork": 215, "visualizer": 48})


class _LayoutTabPage(QWidget):
    """A layout tab: clicking it switches layout, so the page is empty."""
    is_search = False
    is_playlist = False
    table = None

    def __init__(self, spec: dict):
        super().__init__()
        self.spec = spec
        self.title = QLabel(spec.get("name") or "")

    def refresh(self, *_a):
        pass

class _FitLabel(QLabel):
    """Song count label that elides instead of being clipped."""
    textSet = Signal(str)

    def setText(self, text: str):
        super().setText(text)
        self.textSet.emit(text)

    def paintEvent(self, e):
        text = self.text()
        if not text or self.fontMetrics().horizontalAdvance(text) <= self.contentsRect().width():
            return super().paintEvent(e)
        from PySide6.QtGui import QPainter
        p = QPainter(self)
        r = self.contentsRect()
        self.style().drawItemText(p, r, int(Qt.AlignLeft | Qt.AlignVCenter), self.palette(), self.isEnabled(),
                                  self.fontMetrics().elidedText(text, Qt.ElideRight, r.width()),
                                  self.foregroundRole())

class _StatusCopy(_FitLabel):
    def __init__(self, src: _FitLabel):
        super().__init__(src.text())
        self.setObjectName(src.objectName())
        src.textSet.connect(self.setText)


class _SearchCopy(SearchBox):
    """The search box somewhere else: typing here searches the same way."""

    def __init__(self, src: SearchBox):
        super().__init__(src.theme)
        self.setText(src.text())
        src.textChanged.connect(lambda t: self.setText(t) if t != self.text() else None)
        self.textEdited.connect(lambda t: (src.setText(t), src.textEdited.emit(t)))
        self.returnPressed.connect(src.returnPressed)


class _ToastLabel(QLabel):
    clicked = Signal()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()


class MainWindow(QMainWindow):
    _remote_img_ready = Signal(str, bytes)  # url, data
    _stream_img_ready = Signal(str, bytes)  # url, data
    def __init__(self):
        super().__init__()
        from musicwell.paths import settings as _settings
        self.settings = _settings()
        s = self.settings
        F.load_custom(s)
        F.load_renames(s)
        self._migrate_image_sources(s)
        self.theme = th.Theme(s.value("theme", "dark"), s.value("accent", th.DEFAULT_ACCENT))
        self.theme.bold_headers = s.value("bold_headers", False, bool)
        from musicwell import library as library_mod
        library_mod.DECADE_FROM = s.value("decade_from", "year")
        library_mod.ORIGINAL_YEAR_TAG = s.value("original_year_tag", "") or ""
        self.library = Library(self, load=False)  # songs load in the background
        self.player = Player(self.library, self)
        self.images = ImageStore(self)
        self.images.configure(s)
        self.lyrics = LyricsStore(self)
        from musicwell.artistinfo import ArtistInfoStore
        self.artist_info = ArtistInfoStore(s, self)
        self.artist_info.ready.connect(self._on_artist_info)
        self.lyrics.configure(s)
        self._apply_fade_settings(s)
        from musicwell.similar import SimilarFinder
        self.finder = SimilarFinder(self.library, self)
        self.finder.online = s.value("similar_online", True, bool)
        self.finder.archive = s.value("similar_archive", True, bool)
        self.finder.openverse = s.value("similar_openverse", True, bool)
        self.finder.audius = s.value("similar_audius", True, bool)
        self.finder.station_limit = int(s.value("similar_station_count", 40))
        self.waveforms = WaveformStore(self)
        self.cast_ctl = None
        if casting.AVAILABLE:
            self.cast_ctl = casting.CastHub(int(s.value("cast_port", cast_mod.DEFAULT_PORT)), self)
            self.cast_ctl.chrome_on = s.value("cast_discovery", True, bool)
            self.cast_ctl.sonos_on = s.value("sonos_discovery", True, bool)
            self.cast_ctl.set_sonos_addresses(s.value("sonos_addresses", "") or "")
        self._view_tracks: list[dict] = []
        self._current_art = None
        self._status_msg = ""

        self.setWindowTitle(APP_NAME)
        self.setAcceptDrops(True)
        self.resize(1380, 860)
        self._build()
        self._connect()
        self._build_custom_tabs()
        self._shortcuts()
        self._setup_desktop()
        # built-in layout names changed
        from musicwell import layouts as layouts_mod
        cur = self.settings.value("layout_current", "")
        if cur in layouts_mod.OLD_NAMES:
            self.settings.setValue("layout_current", layouts_mod.OLD_NAMES[cur])
        elif cur and cur not in layouts_mod.BUILTIN and cur not in layouts_mod.load_user(self.settings):
            self.settings.setValue("layout_current", "")  # a built-in that no longer exists
        first_run = not self.settings.contains("geometry") and not self.settings.contains("layout_current")
        self._apply_replaygain_settings(self.settings)
        self.player.modesChanged.connect(lambda: self.now.set_levelling(self._levelling_text(self.player.current))
                                         if self.player.current else None)
        self._restore()
        self.apply_theme()
        self.bar.outlines = self.unlock_outlines()
        for p in self.panels:
            p.outlines = self.bar.outlines
        self.set_customizing(False)  # start locked
        self._refresh_playlists()
        if self.library.folders():
            self._albums_mode = self.settings.value("albums_open", False, bool)
            self.lib_stack.setCurrentIndex(3 if self._albums_mode else 1)
            self._set_status("Loading library…")
        else:
            self._on_library_changed()
        self.library.loaded.connect(self._on_first_load)
        QTimer.singleShot(600, self._apply_tab_panels)  # the starting tab's own panels
        self.library.reload_async()
        if first_run:
            QTimer.singleShot(0, lambda: self.use_layout(layouts_mod.DEFAULT_LAYOUT, quiet=True))
        QTimer.singleShot(700, self._maybe_welcome)
        QTimer.singleShot(1500, lambda: self._undo_last is None and self._record_layout())

    def _on_first_load(self):
        self.library.loaded.disconnect(self._on_first_load)
        self._update_count()
        self._refresh_playlists()
        self._restore_session()
        if self._artist_home():  # Artists layout: open on the artist page
            QTimer.singleShot(0, self.open_artist_home)
        try:
            base = json.loads(self.settings.value("layout_baseline", "{}") or "{}")
        except (TypeError, ValueError):
            base = {}
        if not isinstance(base, dict) or base.get("name") != self.settings.value("layout_current", ""):
            self._snap_layout_soon(3000)
        if self.library.folders() and not self.library.scans:
            # rescan for new and changed files
            QTimer.singleShot(3000, lambda: None if self.library.scans else self.library.scan())
        if self.cast_ctl:
            QTimer.singleShot(4000, self.cast_ctl.start_discovery)

    @staticmethod
    def _migrate_image_sources(s):
        """Version 2 dropped TheAudioDB and fanart.tv; version 3 keeps only sources whose terms allow this use."""
        version = int(s.value("image_sources_version", 1))
        if version >= 6:
            return
        if version >= 3:
            MainWindow._migrate_image_sources_5(s)
            return
        from musicwell import artsources as AS
        for key, default in (("album_sources", AS.DEFAULT_ALBUM_ORDER), ("artist_sources", AS.DEFAULT_ARTIST_ORDER)):
            raw = s.value(key)
            if raw is None:
                continue
            try:
                old = list(json.loads(raw))
            except (TypeError, ValueError):
                s.remove(key)
                continue
            lst = [k for k in old if k not in AS.REMOVED_SOURCES]
            if not lst and old:
                lst = list(default)  # none of their sources remain: use the new defaults
            elif key == "artist_sources" and lst and "wikidata" not in lst:
                lst.append("wikidata")
            s.setValue(key, json.dumps(lst))
        s.remove("fanart_key")
        from musicwell.paths import cache_dir
        for sub in ("artists", "covers"):
            d = cache_dir() / sub
            if d.is_dir():
                for f in d.iterdir():
                    if f.suffix in (".jpg", ".miss", ".credit"):
                        f.unlink(missing_ok=True)
        s.setValue("image_sources_version", 3)
        MainWindow._migrate_image_sources_5(s)

    @staticmethod
    def _migrate_image_sources_5(s):
        """Versions 5-6 added Wikipedia, Wikidata, Commons categories and other-language Wikipedias."""
        from musicwell import artsources as AS
        raw = s.value("artist_sources")
        if raw is not None:
            try:
                lst = [k for k in json.loads(raw) if k in AS.ARTIST_SOURCES]
                was = int(s.value("image_sources_version", 1))
                for new in ("commons", "wikis"):
                    # new sources go after the ones you have ticked
                    if new not in lst and (was < 4 or (new == "wikis" and was == 5)):
                        lst.append(new)
                s.setValue("artist_sources", json.dumps(lst or list(AS.DEFAULT_ARTIST_ORDER)))
            except (TypeError, ValueError):
                s.remove("artist_sources")
        from musicwell.paths import cache_dir
        d = cache_dir() / "artists"
        if d.is_dir():
            for f in list(d.iterdir()):
                if f.suffix == ".miss":
                    f.unlink(missing_ok=True)
                elif f.suffix == ".credit":
                    try:
                        src = (json.loads(f.read_text(encoding="utf-8")) or {}).get("source")
                    except (OSError, ValueError, AttributeError):
                        continue
                    if src == "openverse":
                        f.with_suffix(".jpg").unlink(missing_ok=True)
                        f.unlink(missing_ok=True)
        s.setValue("image_sources_version", 6)

    def _build(self):
        from musicwell.widgets import Backdrop
        central = Backdrop()  # paints the artwork behind everything when enabled
        self.backdrop = central
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        top = QWidget()
        top.setObjectName("TopBar")
        top.setContextMenuPolicy(Qt.CustomContextMenu)
        top.customContextMenuRequested.connect(lambda pos: self._top_menu(top.mapToGlobal(pos)))
        self.top_layout = QHBoxLayout(top)
        top.setMinimumWidth(320)  # the tabs never hold the window wide
        self.top_layout.setContentsMargins(14, 10, 14, 6)
        self.top_layout.setSpacing(4)
        self.panel_btn = IconButton("panel", 20, "Panels — show the left / right panel, or both (F9, Shift+F9)")
        self.nav = QButtonGroup(self)
        self.nav.setExclusive(True)
        self.nav_buttons = []
        for i, name in enumerate(self.TAB_NAMES):
            b = QPushButton(name)
            b.setObjectName("NavButton")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            self.nav.addButton(b, i)
            self.nav_buttons.append(b)
            b.setContextMenuPolicy(Qt.CustomContextMenu)
            b.customContextMenuRequested.connect(lambda pos, i=i: self._tab_menu(i, pos))
            b.installEventFilter(self)  # tabs can be dragged
        self.custom_specs, self.custom_pages = [], []
        self._merge_discover_tabs()
        self._load_custom_tabs()
        QTimer.singleShot(0, self._add_albums_tab_once)
        self._apply_tab_names()
        self.add_tab_btn = IconButton("plus", 16, "Add a tab — put back one you removed, or add a playlist or a "
                                                  "search (Favourites, Recently added…) as a tab of its own")
        self.add_tab_btn.setObjectName("AddTab")
        self.add_tab_btn.clicked.connect(self._show_add_tab_menu)
        # tabs that don't fit go in a » menu
        self.more_tabs_btn = QPushButton("»")
        self.more_tabs_btn.setObjectName("MoreTabs")
        self.more_tabs_btn.setCursor(Qt.PointingHandCursor)
        self.more_tabs_btn.setToolTip("More tabs (the window is too narrow to show them all)")
        self.more_tabs_btn.clicked.connect(self._show_more_tabs)
        self.more_tabs_btn.hide()
        self._overflow_tabs: list = []
        self.status = _FitLabel("")
        self.status.setObjectName("ScanLabel")
        self.search = SearchBox(self.theme)
        self.settings_btn = IconButton("settings", 20, "Settings (Ctrl+,)")
        self.layout_btn = IconButton("layouts", 20, "Layouts — switch, reset, save and manage them")
        # All albums <-> song list toggle
        self.albums_btn = IconButton("albums", 20, "All albums — every album as covers (click again for the song list)")
        self.albums_btn.clicked.connect(self._toggle_albums_page)
        self._top_keys = {}
        self._top_extras: dict = {}  # play bar and panel items put in the top bar
        self._layout_topbar("left")
        self.search.setMouseTracking(True)
        for k in self.TOP_ITEMS:
            w = self.top_widget(k)
            self._top_keys[w] = k
            w.installEventFilter(self)
        root.addWidget(top)
        self.root_lay, self.top_bar = root, top
        # scan progress banner under the top bar
        self.scan_banner = QFrame()
        self.scan_banner.setObjectName("ScanBanner")
        sb = QHBoxLayout(self.scan_banner)
        sb.setContentsMargins(16, 5, 16, 5)
        sb.setSpacing(10)
        self.scan_text = QLabel("")
        self.scan_text.setObjectName("ScanText")
        self.scan_bar = QProgressBar()
        self.scan_bar.setObjectName("ScanBar")
        self.scan_bar.setTextVisible(False)
        self.scan_bar.setFixedSize(220, 6)
        sb.addWidget(self.scan_text)
        sb.addWidget(self.scan_bar)
        sb.addStretch(1)
        self.scan_banner.hide()
        root.addWidget(self.scan_banner)

        self.body = QSplitter(Qt.Horizontal)
        self.body.setChildrenCollapsible(False)
        from musicwell.panelsongs import PanelSongList
        PanelSongList.playlists_fn = lambda: self.library.playlists()
        self.now = NowPlayingPanel(self.theme)
        # second panel on the other side (off by default)
        self.now2 = NowPlayingPanel(self.theme)
        self.now2.defaults = PANEL2_DEFAULTS
        self.now2.restore_state(dict(PANEL2_DEFAULTS, removed=[k for k in PANEL_ORDER
                                                               if k not in PANEL2_DEFAULTS["order"]]))
        # top panel: a strip across the window
        self.now3 = NowPlayingPanel(self.theme)
        self.now3.defaults = PANEL3_DEFAULTS
        self.now3.restore_state(dict(PANEL3_DEFAULTS, removed=[k for k in PANEL_ORDER
                                                               if k not in PANEL3_DEFAULTS["order"]]))
        self.now3.set_horizontal(True)
        # the Radio and Lyrics tabs' own panel
        self.now4 = NowPlayingPanel(self.theme)
        self.now4.defaults = tab_panel_defaults()
        self.now4.restore_state(tab_panel_defaults())
        self.now5 = self.now6 = None  # panel items in the play bar and the top bar, made when first needed
        self.now.mirrors = [self.now2, self.now3, self.now4]
        self.now.header.mirrors = [self.now2.header, self.now3.header, self.now4.header]
        self.now.art.mirrors = [self.now2.art, self.now3.art, self.now4.art]
        self.pages = QStackedWidget()
        self.pages.currentChanged.connect(lambda _: self._update_albums_btn())
        self.pages.currentChanged.connect(self._apply_tab_panels)
        self.middle = QSplitter(Qt.Vertical)  # top panel and pages
        self.middle.setChildrenCollapsible(False)
        self.middle.addWidget(self.now3)
        self.middle.addWidget(self.pages)
        self.middle.setStretchFactor(0, 0)
        self.middle.setStretchFactor(1, 1)
        self.middle.setSizes([170, 700])
        self.body.addWidget(self.now)
        self.body.addWidget(self.middle)
        self.body.addWidget(self.now2)
        self.body.addWidget(self.now4)
        self.now2.hide()
        self.now4.hide()
        self.now3.hide()
        self.body.setStretchFactor(0, 0)
        self.body.setStretchFactor(1, 1)
        self.body.setSizes([330, 1050])
        root.addWidget(self.body, 1)

        self.pages.addWidget(self._build_library_page())
        self.pages.addWidget(self._build_queue_page())
        self.pages.addWidget(self._build_playlists_page())
        self.lyrics_page = LyricsPage(self.theme)
        self.pages.addWidget(self.lyrics_page)
        from musicwell.stats import StatsPage
        self.stats_page = StatsPage(self.library, self.theme)
        self.pages.addWidget(self.stats_page)
        from musicwell import radio as radio_mod
        from musicwell.radioview import RadioPage
        self.stations = radio_mod.Stations(self.settings)
        self.stations.load_title_orders()
        self.radio_page = RadioPage(self.stations, self.theme)
        self.pages.addWidget(self.radio_page)
        from musicwell.similarview import SimilarPage
        self.similar_page = SimilarPage(self.library, self.theme)
        self.pages.addWidget(self.similar_page)
        from musicwell.freemusic import OnlineSourcesPage
        from musicwell.sources import Sources
        self.my_sources = Sources(self.settings)
        self.online_page = OnlineSourcesPage(self.library, self.theme, self.my_sources)
        self.similar_page.free.my = self.my_sources
        self.pages.addWidget(self.online_page)  # page 7; user tabs come after it
        # Discover: one tab for both pages
        from musicwell.widgets import DiscoverSwitch
        self.discover_switches = []
        self._discover_page = 6
        for page in (self.similar_page, self.online_page):
            sw = DiscoverSwitch()
            sw.picked.connect(self.open_discover)
            page.layout().insertWidget(0, sw)
            self.discover_switches.append(sw)
        self.online_page.viewChanged.connect(lambda _i: self._sync_discover())

        self._search_copies: list = []
        self.bar = PlayBar(self.theme)
        NowPlayingPanel.make_control = self._make_copy  # panels can hold copies of play bar and top bar items
        self.bar.make_item = self._make_bar_item
        self.bar.drop_on_top = self.drop_on_top
        self.bar.panelItemsChanged.connect(self._bar_panel_items)
        root.addWidget(self.bar)
        self._layout_topbar(self.settings.value("panel_side", "left"))  # with any play bar or panel items in it

    def _page_text_widgets(self, key: str) -> list:
        if key == "lyrics":
            return [self.lyrics_page.view]
        return [t for t in (self.table, self.queue_table, self.pl_table, getattr(self.artist_page, "table", None),
                            getattr(self.albums_page, "table", None)) if t is not None]

    def _page_text_size(self, key: str) -> float:
        try:
            return min(2.0, max(0.5, float(self.settings.value(f"text_size_{key}", 1.0))))
        except (TypeError, ValueError):
            return 1.0

    def set_page_text_size(self, key: str, scale: float, save: bool = True):
        """Text size for the Lyrics tab or the song lists."""
        if save:
            self.settings.setValue(f"text_size_{key}", scale)
        for w in self._page_text_widgets(key):
            scale_text(w, scale)
            if key == "songs":
                w.verticalHeader().setDefaultSectionSize(round(30 * max(1.0, scale)))

    def _make_copy(self, key: str):
        if key.startswith("bar:"):
            return self.bar.make_copy(key[4:])
        return self._top_copy(key[4:])

    def _make_bar_item(self, key: str):
        if key.startswith("panel:"):
            return BarItem(self._bar_source("now5"), key[6:])
        return self._top_copy(key[4:])

    def _top_copy(self, key: str):
        """A working copy of a top bar item, for a panel or the play bar."""
        if key == "search":
            w = _SearchCopy(self.search)
            self._search_copies.append(w)
            if hasattr(self, "_undo_keys"):
                w.installEventFilter(self._undo_keys)
            return w
        if key == "status":
            return _StatusCopy(self.status)
        return _CopyButton(self.top_widget(key))

    def _menu_pos(self, btn) -> QPoint:
        """Under the button, or under its copy if the menu was opened from one."""
        at = getattr(btn, "copy_pos", None)
        return (at if at is not None else btn.mapToGlobal(QPoint(0, 0))) + QPoint(0, btn.height())

    def show_top_drop(self, gpos):
        """While an item from a panel or the play bar is dragged: a line where it would land along the top."""
        line = getattr(self, "_top_drop_line", None)
        if line is None:
            line = self._top_drop_line = QWidget(self.top_bar)
            line.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        bar = self.top_bar
        if gpos is None or not bar.rect().contains(bar.mapFromGlobal(gpos)):
            line.hide()
            return
        order, hidden = self.top_order(), self.top_hidden()
        after = [k for k in order[self._top_index(gpos, ""):] if k not in hidden]
        if after:
            w = self.top_widget(after[0])
            x = w.mapTo(bar, w.rect().topRight()).x() - 6 if after[0] == "status" else w.mapTo(bar, QPoint(0, 0)).x() - 3
        else:
            x = bar.width() - 14
        colour = self.theme.accent.name()
        if line.property("colour") != colour:
            line.setProperty("colour", colour)
            line.setStyleSheet(f"background: {colour}; border-radius: 1px;")
        line.setGeometry(x - 1, 6, 3, bar.height() - 12)
        line.show()
        line.raise_()

    def drop_on_top(self, key: str, gpos):
        """An item dragged from a panel or the play bar onto the top bar."""
        if not self.top_bar.rect().contains(self.top_bar.mapFromGlobal(gpos)):
            return False
        if key.split(":")[0] in ("spacer", "gap", "stretch"):
            return None  # spaces stay where they were
        if key.startswith("top:"):
            top_key = key[4:]
        elif key in CONTROLS:
            top_key = "bar:" + key
        elif key in TOP_PANEL_ITEMS:
            top_key = "panel:" + key
        else:
            top_key = key  # "bar:eq" from a panel, "panel:title" from the play bar
        if not self._top_key_ok(top_key):
            self._flash("That's too big for the top bar — the panel across the top (Ctrl+F9) can hold it", 5000)
            return None  # stays where it was
        self._show_top(top_key, gpos)
        return True

    def _focus_search(self):
        """Ctrl+F: the search box, or a copy of it if the top bar's one is hidden."""
        from shiboken6 import Shiboken
        self._search_copies = [b for b in self._search_copies if Shiboken.isValid(b)]
        boxes = [self.search] + self._search_copies
        box = next((b for b in boxes if b.isVisible()), self.search)
        box.setFocus()
        box.selectAll()

    def _build_library_page(self) -> QWidget:
        self.lib_stack = QStackedWidget()

        empty = QWidget()
        el = QVBoxLayout(empty)
        el.addStretch(2)
        t = QLabel("Your library is empty")
        t.setObjectName("EmptyTitle")
        t.setAlignment(Qt.AlignCenter)
        el.addWidget(t)
        d = QLabel(f"Add a folder of music to get started. Your music folder is {music_dir()}\n"
                   "You can also drag folders onto this window.")
        d.setObjectName("EmptyText")
        d.setAlignment(Qt.AlignCenter)
        el.addWidget(d)
        el.addSpacing(14)
        row = QHBoxLayout()
        row.addStretch()
        use_music = QPushButton(f"Use {os.path.basename(music_dir()) or 'Home'} folder")
        use_music.setObjectName("Primary")
        use_music.clicked.connect(lambda: self.library.add_folder(music_dir()))
        choose = QPushButton("Choose a folder…")
        choose.clicked.connect(self._choose_folder)
        row.addWidget(use_music)
        row.addWidget(choose)
        row.addStretch()
        el.addLayout(row)
        el.addStretch(3)
        self.lib_stack.addWidget(empty)

        self.lib_split = QSplitter(Qt.Vertical)
        self.lib_split.setChildrenCollapsible(False)
        self.browser = ColumnBrowser()
        self.browser.setMinimumHeight(120)
        self.table = SongTable(self.theme)
        self.lib_split.addWidget(self.browser)
        self.lib_split.addWidget(self.table)
        # while searching the library, the same search online
        from musicwell.freemusic import OnlineStrip
        self.online_strip = OnlineStrip(self.library, self.theme)
        self.lib_split.addWidget(self.online_strip)
        self.lib_split.setStretchFactor(1, 1)
        self.lib_split.setSizes([260, 600, 0])
        self.lib_stack.addWidget(self.lib_split)
        # artist page
        from musicwell.artistview import ArtistPage
        self.artist_page = ArtistPage(self.theme)
        self.artist_page.back_btn.setVisible(self.settings.value("library_home", "") != "artist")
        self.lib_stack.addWidget(self.artist_page)  # index 2
        from musicwell.albumsview import AlbumsPage
        try:
            spec = json.loads(self.settings.value("albums_page", "{}") or "{}")
        except (TypeError, ValueError):
            spec = {}
        self.albums_page = AlbumsPage(self.theme, back=True, spec=spec if isinstance(spec, dict) else {})
        # Albums layout: covers are the library view
        self.albums_page.back_btn.setVisible(self.settings.value("albums_back", True, bool))
        self.albums_page.picture_actions = self._picture_actions
        self.lib_stack.addWidget(self.albums_page)  # index 3
        self.lib_stack.currentChanged.connect(lambda _: self._update_albums_btn())
        return self.lib_stack

    def _build_queue_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 6, 12, 0)
        row = QHBoxLayout()
        title = QLabel("Play queue")
        title.setObjectName("PageTitle")
        self.queue_count = QLabel("")
        self.queue_count.setObjectName("EmptyText")
        row.addWidget(title)
        row.addWidget(self.queue_count)
        row.addStretch()
        self.queue_clear_played = QPushButton("Clear played")
        self.queue_clear_played.setToolTip("Take the greyed songs (already played) off the list")
        self.queue_clear_played.clicked.connect(self.player.clear_played)
        row.addWidget(self.queue_clear_played)
        clear = QPushButton("Clear queue")
        clear.setToolTip("Take every song off the list (the one playing carries on)")
        clear.clicked.connect(self.player.clear_queue)
        row.addWidget(clear)
        lay.addLayout(row)
        hint = QLabel("Queued songs play before the rest of the list. Right-click any song → Add to queue, "
                      "or press Ctrl+Enter. Songs keep their place: played ones turn grey (double-click one to "
                      "hear it again). Delete removes, Alt+Up/Down reorders.")
        hint.setObjectName("EmptyText")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.queue_table = SongTable(self.theme, hidden_by_default=("genre", "playcount"))
        self.queue_table.setSortingEnabled(False)
        self.queue_table.model_.by_row = True  # played rows greyed, playing row marked
        lay.addWidget(self.queue_table, 1)
        return w

    def _build_playlists_page(self) -> QWidget:
        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(6, 6, 8, 8)
        title = QLabel("Playlists")
        title.setObjectName("PageTitle")
        ll.addWidget(title)
        self.pl_list = QListWidget()
        self.pl_list.setObjectName("Pane")
        self.pl_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.pl_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.pl_list.setProperty("ticks", True)  # the theme draws the tick boxes
        self.pl_list.setToolTip("Drag over playlists, Ctrl-click or Shift-click to pick several — then Delete")
        self._pl_selecting = False
        self.pl_list.itemSelectionChanged.connect(self._pl_picks_changed)
        self.pl_list.itemChanged.connect(self._pl_tick_clicked)
        ll.addWidget(self.pl_list, 1)
        btns = QHBoxLayout()
        new = QPushButton("New")
        new.clicked.connect(lambda: self._new_playlist())
        imp = QPushButton("Import M3U…")
        imp.clicked.connect(self._import_m3u)
        btns.addWidget(new)
        btns.addWidget(imp)
        ll.addLayout(btns)
        btns2 = QHBoxLayout()
        self.pl_select_btn = QPushButton("Select…")
        self.pl_select_btn.setToolTip("Show tick boxes to pick playlists by clicking them (Done hides them)")
        self.pl_select_btn.clicked.connect(lambda: self._pl_set_selecting(not self._pl_selecting))
        self.pl_all_btn = QPushButton("Select all")
        self.pl_all_btn.setToolTip("Pick every playlist (click again to pick none) — Ctrl+A")
        self.pl_all_btn.clicked.connect(self._pl_tick_all)
        self.pl_all_btn.hide()
        self.pl_delete_btn = QPushButton("Delete…")
        self.pl_delete_btn.setToolTip("Delete the playlists picked — the songs stay in your library. Or press Delete")
        self.pl_delete_btn.clicked.connect(lambda: self._delete_playlists(self._picked_playlists()))
        btns2.addWidget(self.pl_select_btn)
        btns2.addWidget(self.pl_all_btn)
        btns2.addWidget(self.pl_delete_btn)
        ll.addLayout(btns2)
        sc = QShortcut(QKeySequence.Delete, self.pl_list, context=Qt.WidgetWithChildrenShortcut)
        sc.activated.connect(lambda: self._delete_playlists(self._picked_playlists()))
        sc3 = QShortcut(QKeySequence(Qt.Key_Escape), self.pl_list, context=Qt.WidgetWithChildrenShortcut)
        sc3.activated.connect(lambda: self._pl_selecting and self._pl_set_selecting(False))
        split.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(12, 6, 12, 0)
        row = QHBoxLayout()
        self.pl_title = QLabel("")
        self.pl_title.setObjectName("PageTitle")
        self.pl_info = QLabel("")
        self.pl_info.setObjectName("EmptyText")
        row.addWidget(self.pl_title)
        row.addWidget(self.pl_info)
        row.addStretch()
        play = QPushButton("Play")
        play.setObjectName("Primary")
        play.clicked.connect(lambda: self.player.play_list(self.pl_table.model_.ids(), 0))
        export = QPushButton("Export M3U…")
        export.clicked.connect(self._export_m3u)
        row.addWidget(play)
        row.addWidget(export)
        rl.addLayout(row)
        self.pl_table = SongTable(self.theme, hidden_by_default=("genre", "playcount"))
        self.pl_table.setSortingEnabled(False)
        rl.addWidget(self.pl_table, 1)
        # when a panel's Song list follows the Playlists tab
        self.pl_elsewhere = QLabel("")
        self.pl_elsewhere.setObjectName("EmptyText")
        self.pl_elsewhere.setWordWrap(True)
        self.pl_elsewhere.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.pl_elsewhere.hide()
        rl.addWidget(self.pl_elsewhere, 1)
        split.addWidget(right)
        split.setSizes([200, 930])
        return split

    def _connect(self):
        lib, pl = self.library, self.player
        self.nav.idClicked.connect(self._nav_clicked)
        self.panel_btn.clicked.connect(self._panel_button)
        self.settings_btn.clicked.connect(self._open_settings)
        self.layout_btn.clicked.connect(self._layouts_menu)

        self._search_timer = QTimer(self, singleShot=True, interval=180)
        self._search_timer.timeout.connect(self._refilter)
        self.search.textChanged.connect(self._search_typed)
        self.search.returnPressed.connect(self._search_entered)
        self._online_timer = QTimer(self, singleShot=True, interval=1100)  # pause in typing: search online too
        self._online_timer.timeout.connect(lambda: self._search_online_too(paused=True))
        self.search.textEdited.connect(self._search_edited)
        self.nav.idClicked.connect(lambda i: self._leave_artist_page() if i == 0 and getattr(self, "_lib_was_on", False)
                                   else None)
        self.nav.idPressed.connect(lambda i: setattr(self, "_lib_was_on", self.pages.currentIndex() == 0))
        SongTable.AUTO_FIT = False  # Auto-resize is a one-off action now, not a setting
        for t in (self.table, self.queue_table, self.pl_table, self.similar_page.table,
                  self.artist_page.table, self.albums_page.table):
            t.autoFitToggled.connect(self._on_autofit)
        alp = self.albums_page
        self._wire_albums(alp)
        alp.backRequested.connect(self._leave_artist_page)
        alp.optionsChanged.connect(lambda: self.settings.setValue(
            "albums_page", json.dumps({"sort": alp.sort, "covers": alp.cover_size, "split": alp.split_artists})))
        alt = alp.table
        alt.playRequested.connect(lambda r: self.player.play_list(alt.model_.ids(), r))
        alt.menuRequested.connect(lambda ids, pos: self._track_menu(ids, pos, "library", alt))
        alt.rated.connect(lambda tid, r: self.library.set_rating([tid], r))
        alt.renameRequested.connect(self.rename_column)
        alt.resetNamesRequested.connect(self.reset_column_names)
        try:
            alt.restore_column_state(json.loads(self.settings.value("columns_albums_page", "[]")))
        except (TypeError, ValueError):
            pass
        alt.columnsChanged.connect(lambda: self.settings.setValue("columns_albums_page", json.dumps(alt.column_state())))
        ap = self.artist_page
        ap.backRequested.connect(self._leave_artist_page)
        ap.playRequested.connect(lambda ids, i: self.player.play_list(ids, i))
        ap.listReplaced.connect(self.player.replace_list)
        ap.queueRequested.connect(lambda ids: ids and (self.player.enqueue(ids),
                                                       self._flash(f"Added {len(ids)} songs to the queue", 3000)))
        ap.similarRequested.connect(lambda name: self.find_similar(artist=name))
        ap.onlineRequested.connect(self.songs_by_online)
        ap.photo_provider = lambda name, path, px: self.images.artist_thumb(name, path, px)
        ap.picture_actions = self._picture_actions
        ap.image_taker = self.take_image_for
        ap.cover_provider = lambda track, px: self.images.album_thumb(track, px)
        ap.coverSizeChanged.connect(lambda k: self.settings.setValue("artist_page_covers", k))
        ap.set_cover_size(self.settings.value("artist_page_covers", "medium"), fit=False)
        at = ap.table
        at.playRequested.connect(lambda r: self.player.play_list(at.model_.ids(), r))
        at.menuRequested.connect(lambda ids, pos: self._track_menu(ids, pos, "library", at))
        at.rated.connect(lambda tid, r: self.library.set_rating([tid], r))
        at.renameRequested.connect(self.rename_column)
        at.resetNamesRequested.connect(self.reset_column_names)
        at.customColumnRequested.connect(lambda: self._add_custom_column(at))
        at.customRemoveRequested.connect(self._remove_custom_field)
        at.customManageRequested.connect(lambda: self.manage_custom_fields(at))
        try:
            at.restore_column_state(json.loads(self.settings.value("columns_artist_page", "[]")))
        except (TypeError, ValueError):
            pass
        at.columnsChanged.connect(lambda: self.settings.setValue("columns_artist_page", json.dumps(at.column_state())))
        self.browser.filtered.connect(self._show_view)
        self.browser.fieldsEdited.connect(lambda f: self.set_browser(f, True))
        self.browser.editRequested.connect(self._edit_browser_columns)
        self.browser.renameRequested.connect(lambda k: self.rename_column(k) if k else self.reset_column_names())
        self.browser.hideRequested.connect(lambda: self.set_browser(self.browser.fields(), False))
        SongTable.lock_toggle = lambda lock: self.set_customizing(not lock)
        SongTable.bold_headers = lambda: self.theme.bold_headers
        SongTable.set_bold_headers = self.set_bold_headers
        def browser_menu(m):
            bm = m.addMenu("The column browser")
            bm.addAction("Hide it" if self.browser_visible() else "Show it",
                         lambda: self.set_browser(self.browser.fields(), not self.browser_visible()))
            bm.addAction("Edit its columns…", self._edit_browser_columns)
        self.table.header_extra = browser_menu

        self.table.playRequested.connect(lambda r: pl.play_list(self.table.model_.ids(), r))
        self.queue_table.playRequested.connect(pl.play_queue_row)
        self.pl_table.playRequested.connect(lambda r: pl.play_list(self.pl_table.model_.ids(), r))
        for tbl, src in ((self.table, "library"), (self.queue_table, "queue"), (self.pl_table, "playlist")):
            tbl.menuRequested.connect(lambda ids, pos, s=src, t=tbl: self._track_menu(ids, pos, s, t))
            tbl.rated.connect(lambda tid, r: lib.set_rating([tid], r))
        self.table.deleteRequested.connect(lambda rows: self._remove_from_library(self.table.selected_ids()))
        self._save_cols_timer = QTimer(self, singleShot=True, interval=1500)
        self._save_cols_timer.timeout.connect(self._save_columns)
        for tbl in (self.table, self.queue_table, self.pl_table):
            tbl.customColumnRequested.connect(lambda t=tbl: self._add_custom_column(t))
            tbl.customRemoveRequested.connect(self._remove_custom_field)
            tbl.customManageRequested.connect(lambda t=tbl: self.manage_custom_fields(t))
            tbl.renameRequested.connect(self.rename_column)
            tbl.resetNamesRequested.connect(self.reset_column_names)
            tbl.columnsChanged.connect(self._save_cols_timer.start)
            tbl.columnsChanged.connect(self._layout_touched)
        self.queue_table.deleteRequested.connect(pl.remove_queue_rows)
        self.pl_table.deleteRequested.connect(self._remove_from_playlist)

        self.pl_list.currentItemChanged.connect(lambda *_: (self._show_playlist(), self._pl_picks_changed()))
        self.pl_list.customContextMenuRequested.connect(self._playlist_menu)
        # drag and drop into the queue / a playlist, and reordering
        self.queue_table.enable_drops()
        self.queue_table.tracksDropped.connect(self._drop_on_queue)
        self.pl_table.enable_drops()
        self.pl_table.tracksDropped.connect(self._drop_on_playlist)
        self.pl_list.setAcceptDrops(True)
        self.pl_list.viewport().setAcceptDrops(True)
        self.pl_list.viewport().installEventFilter(self)
        self.nav_buttons[1].setAcceptDrops(True)  # the Queue tab
        self.nav_buttons[1].installEventFilter(self)
        self.nav_buttons[2].setAcceptDrops(True)  # the Playlists tab opens so you can drop on a playlist
        self.nav_buttons[2].installEventFilter(self)
        self.pl_list.itemDoubleClicked.connect(
            lambda it: pl.play_list(lib.playlist_track_ids(it.data(Qt.UserRole)), 0))

        lib.changed.connect(self._on_library_changed)
        lib.trackUpdated.connect(self._on_track_updated)
        lib.playlistsChanged.connect(self._refresh_playlists)
        lib.playlistsChanged.connect(self._panel_playlists_changed)
        self.pl_list.itemClicked.connect(lambda it: self._playlist_picked(it.data(Qt.UserRole)))
        self.pl_list.currentItemChanged.connect(
            lambda it, _p: self.pl_list.hasFocus() and it is not None and self._playlist_picked(it.data(Qt.UserRole)))
        lib.playlistsChanged.connect(lambda: self._refresh_custom_tabs("playlist"))
        lib.scanProgress.connect(self._scan_progress)
        lib.scanFinished.connect(self._on_scan_finished)
        lib.scanSkipped.connect(lambda n: setattr(self, "_scan_skipped", n))

        pl.trackChanged.connect(self._on_track_changed)
        pl.playingChanged.connect(lambda _: self._refresh_bar())
        pl.modesChanged.connect(self._refresh_bar)
        pl.queueChanged.connect(self._on_queue_changed)
        pl.trackChanged.connect(self._on_queue_changed)  # the queue's playing row moves on
        for sig in (pl.trackChanged, pl.queueChanged, pl.modesChanged):
            sig.connect(self._refresh_panel_songs_soon)
        self.table.model_.modelReset.connect(self._refresh_panel_songs_soon)
        pl.positionChanged.connect(self._position_news)
        # The decoder works in bursts, so position updates are smoothed for the seek bar and lyrics.
        self._smooth_timer = QTimer(self, interval=40)
        self._smooth_timer.timeout.connect(self._smooth_position)
        pl.playingChanged.connect(self._smooth_on_off)
        pl.trackChanged.connect(lambda _: (setattr(self, "_shown_pos", -1), setattr(self, "_seek_hold", None),
                                           setattr(self, "_smooth", None)))
        pl.seeked.connect(lambda _: setattr(self, "_shown_pos", -1))
        pl.positionChanged.connect(self._lyrics_position)
        pl.playingChanged.connect(self._lyrics_playing)
        pl.durationChanged.connect(lambda d: self.bar.set_position(pl.position(), d))
        pl.error.connect(lambda msg: self._flash(msg))

        b = self.bar
        b.play.clicked.connect(self._play_pause_jump)
        b.next.clicked.connect(lambda: pl.next())
        b.prev.clicked.connect(pl.previous)
        b.shuffle.clicked.connect(pl.toggle_shuffle)
        b.repeat.clicked.connect(pl.cycle_repeat)
        b.stop_after.clicked.connect(pl.toggle_stop_after)
        b.queue_btn.clicked.connect(lambda: self._go_page(1))
        b.eq_btn.clicked.connect(self._open_eq)
        b.set_available("cast", self.cast_ctl is not None)
        b.lyricsRequested.connect(self._toggle_lyrics_page)
        b.panelRequested.connect(self._toggle_panel)
        b.locateRequested.connect(self.locate_current)
        b.stopRequested.connect(self._stop)
        b.skipRequested.connect(self._skip)
        b.rated.connect(lambda r: pl.current and lib.set_rating([pl.current["id"]], r))
        b.layoutChanged.connect(self._save_bar_layout)
        b.editingChanged.connect(self._part_editing)
        b.lockRequested.connect(lambda lock: self.set_customizing(not lock))
        b.itemRemoved.connect(lambda name: self._flash(f"Removed “{name}” from the play bar — right-click the bar → "
                                                       "Add here to bring it back", 6000))
        self.now.likeRequested.connect(self.like_current)
        self.now2.likeRequested.connect(self.like_current)
        self.now4.likeRequested.connect(self.like_current)
        self.now4.editingChanged.connect(self._part_editing)
        self.now3.likeRequested.connect(self.like_current)
        self.now3.editingChanged.connect(self._part_editing)
        self.now.editingChanged.connect(self._part_editing)
        self.now2.editingChanged.connect(self._part_editing)
        for p in self.panels:
            p.lockRequested.connect(lambda lock: self.set_customizing(not lock))
            p.sideRequested.connect(lambda where, p=p: self._move_panel(p, where))
            p.itemRemoved.connect(lambda name: self._flash(
                f"Removed “{name}” from the panel — right-click the panel → Add here to bring it back" if name
                else "The other panel has that already", 6000))
        b.positionChanged.connect(self._place_bar)
        b.waveformWanted.connect(lambda t: None if (t.get("stream") or t.get("remote")) else
                                 self.waveforms.request(t["path"], t.get("length") or 0))
        self.waveforms.ready.connect(b.set_waveform)
        pl.playingChanged.connect(b.viz.set_playing)
        pl.playingChanged.connect(b.spinner.set_playing)
        b.viz.styleRequested.connect(self._bar_viz_style)
        from musicwell import record as record_mod
        record_mod.set_rpm(float(self.settings.value("record_rpm", 100 / 3)), tell=False)
        record_mod.on_speed_changed.append(lambda r: self.settings.setValue("record_rpm", r))
        self.lyrics.ready.connect(self._on_lyrics)
        # radio: Next / Previous go through favourite stations
        pl.radio_step = self._radio_step
        from musicwell.addim import AdDimmer
        self.ad_dimmer = AdDimmer(pl, self.settings, self)
        self.ad_dimmer.dimmedChanged.connect(self._on_ad_dimmed)
        from musicwell.upnext import UpNext
        self.up_next = UpNext(pl, self)
        self.up_next.nextChanged.connect(self._on_up_next)
        from musicwell.alerts import SongAlerts
        self.song_alerts = SongAlerts(self.stations, self.settings, pl, lib, self)
        self.song_alerts.alert.connect(self._song_alert)
        self.song_alerts.checked.connect(self.radio_page._on_peeked)
        self.status.installEventFilter(self)  # click an alert to listen
        sp = self.stats_page
        from musicwell.radiolog import RadioLog
        self.radio_log = RadioLog(lib.con, pl, self)
        self.radio_log.is_break = self._radio_is_break
        self._apply_playing_style()
        sp.radio_log, sp.stations = self.radio_log, self.stations
        self.radio_log.changed.connect(lambda: sp.mark_dirty() if sp.view != "library" else None)
        sp.playStation.connect(self._play_station_from_stats)
        sp.notASong.connect(self._radio_not_a_song)
        sp.viewChanged.connect(lambda v: self.settings.setValue("stats_view", v))
        sp.set_view(self.settings.value("stats_view", "library") or "library")
        lib.changed.connect(sp.mark_dirty)
        lib.trackUpdated.connect(lambda _tid: sp.mark_dirty())
        sp.showArtist.connect(lambda a: self.open_artist_page(a, "album"))
        sp.showAlbum.connect(self._show_album_from_stats)
        sp.showTrack.connect(self.show_track)
        sp.playTrack.connect(self._play_from_stats)
        for view in (self.lyrics_page.view, self.now.lyrics_view, self.now2.lyrics_view, self.now3.lyrics_view,
                     self.now4.lyrics_view):
            view.seekRequested.connect(self._seek_to)
            view.actions = self._lyrics_actions
        for key in ("lyrics", "songs"):  # Text size for the Lyrics tab and the song lists
            for w in self._page_text_widgets(key):
                w.menu_extras = lambda m, k=key: text_size_menu(
                    m.addMenu("Text size"), self._page_text_size(k), lambda sc: self.set_page_text_size(k, sc))
            if self._page_text_size(key) != 1:
                self.set_page_text_size(key, self._page_text_size(key), save=False)
        self.lyrics_page.offsetChanged.connect(self._set_lyrics_offset)
        self.lyrics_page.more_menu.aboutToShow.connect(self._fill_lyrics_menu)
        b.cast_btn.clicked.connect(self._cast_menu)
        if self.cast_ctl:
            c = self.cast_ctl
            c.connected.connect(self._on_cast_connected)
            c.disconnected.connect(self._on_cast_disconnected)
            c.volumeChanged.connect(self._on_cast_volume)
            c.error.connect(lambda msg: self._flash(msg, 7000))
            c.problem.connect(self._show_problem)
            c.cover_provider = self.images.cached_cover_bytes
        self.bar.panels_menu = self.panels_submenu
        # unlocked: dotted outline and name for every panel
        from musicwell.widgets import EditFrame

        def side_name(p):
            return lambda: ("Left Panel" if self.side_panels()["left"] is p else "Right Panel")

        def panel_empty(p):
            return lambda: not [k for k in p.order if not p.blocks[k].hidden]

        def centre_empty():
            if self.pages.currentIndex() != 0:
                return False
            h = self.table.horizontalHeader()
            return h.count() > 0 and all(h.isSectionHidden(i) for i in range(h.count()))
        self.edit_frames = [EditFrame(self.now, self.theme, side_name(self.now), panel_empty(self.now)),
                            EditFrame(self.now2, self.theme, side_name(self.now2), panel_empty(self.now2)),
                            EditFrame(self.now3, self.theme, "Top Panel", panel_empty(self.now3)),
                            EditFrame(self.pages, self.theme, "Centre Panel", centre_empty,
                                      hint="the tab you're on — right-click here → Columns to show the songs")]
        for p in (self.now, self.now2, self.now3, self.now4):
            p.layoutChanged.connect(lambda: [f.update() for f in self.edit_frames])
        # unlocked: Delete removes the item under the mouse
        self._delete_key = _DeleteKey(self)
        self._undo_keys = _UndoKeys(self)
        for box in self.findChildren(QLineEdit):  # only the text boxes, not every event in the app
            box.installEventFilter(self._undo_keys)
        cw = self.centralWidget()
        cw.setContextMenuPolicy(Qt.CustomContextMenu)
        cw.customContextMenuRequested.connect(self._window_menu)
        for p in self.panels:
            p.panels_menu = self.panels_submenu
            p.disconnectRequested.connect(lambda: self._disconnect_cast(play_here=False))
            p.viz.styleRequested.connect(self._set_visualizer)
            pl.playingChanged.connect(p.viz.set_playing)
            pl.playingChanged.connect(p.art.set_playing)  # records spin while playing
            sl = p.songs
            sl.songActivated.connect(self._panel_song_play)
            sl.menuRequested.connect(lambda src, ids, pos, s=sl: self._panel_song_menu(s, ids, pos))
            sl.table.deleteRequested.connect(lambda rows, s=sl: self._panel_song_delete(s, rows))
            sl.sourceChanged.connect(self._refresh_panel_songs_soon)
            sl.table.rated.connect(lambda tid, r: lib.set_rating([tid], r))
            p.extra_actions = lambda p=p: self._panel_actions(p)
        self.now.layoutChanged.connect(self._save_panel_layout)
        self.now2.layoutChanged.connect(self._save_panel2_layout)
        self.now3.layoutChanged.connect(self._save_panel3_layout)
        self.now4.layoutChanged.connect(self._save_tab_panel)
        self._undo: list = []
        self._redo: list = []
        self._undo_last = None
        self._undo_timer = QTimer(self, singleShot=True, interval=300, timeout=self._record_layout)
        for p in (self.now, self.now2, self.now3, self.now4, self.bar):
            p.layoutChanged.connect(self._layout_touched)
        for divider in (self.body, self.middle, self.lib_split):
            divider.splitterMoved.connect(lambda *_: self._layout_touched())
        for p_ in (self.now, self.now2, self.now3, self.now4):  # the visualizer can be in any panel
            p_.blockVisibilityChanged.connect(self._on_panel_block_visibility)
            p_.coverStyleChanged.connect(self._cover_style_everywhere)
        b.coverStyleChanged.connect(self._cover_style_everywhere)
        b.seek.sliderReleased.connect(lambda: pl.seek(b.seek.value()))
        pl.seeked.connect(self._note_seek)
        b.seek.sliderMoved.connect(lambda v: b.elapsed.setText(fmt_time(v / 1000)))
        b.volume.valueChanged.connect(self._on_volume)
        b.vol_btn.clicked.connect(self._toggle_mute)
        # keep the desktop's per-app mute and ours in sync
        from musicwell.sysmute import SoundSystemMute
        self.sysmute = SoundSystemMute(self)
        self.sysmute.mutedChanged.connect(self._desktop_muted)
        QApplication.instance().aboutToQuit.connect(self.sysmute.shutdown)

        for p in self.panels:
            a = p.artists
            a.picked.connect(self._artist_picked)
            a.browseRequested.connect(self._artist_browse)
            a.allAlbumsRequested.connect(self.open_albums_page)
            a.allSongsRequested.connect(self.open_all_songs)
            a.allSongsPlayRequested.connect(self._play_all_songs)
            a.playRequested.connect(self._play_artist)
            a.queueRequested.connect(lambda name, kind: self._queue_artist(name, kind))
            a.similarRequested.connect(lambda name: self.find_similar(artist=name))
            a.onlineRequested.connect(self.songs_by_online)
            a.image_provider = lambda name, path, px: self.images.artist_thumb(name, path, px)
            a.cover_provider = lambda track, px: self.images.album_thumb(track, px)
            a.picture_actions = self._picture_actions
            a.image_taker = self.take_image_for
            a.albumPicked.connect(self._panel_album)
            a.albumPlayRequested.connect(self._play_album)
            a.albumQueueRequested.connect(lambda name, album, kind: self._queue_album(name, album, kind))
            p.artistsWanted.connect(lambda p=p: self._fill_artist_list(p))
            p.artist_info.refreshRequested.connect(lambda name: self.artist_info.request(name, force=True))
            al = p.albums
            al.cover_provider = lambda track, px: self.images.album_thumb(track, px)
            al.albumPicked.connect(lambda artist, album: self._panel_album(artist, album, "album"))
            al.playRequested.connect(lambda ids, i: self.player.play_list(ids, i))
            al.queueRequested.connect(lambda ids: ids and (self.player.enqueue(ids),
                                                           self._flash(f"Added {len(ids)} songs to the queue", 3000)))
            al.artistRequested.connect(lambda name: self.open_artist_page(name, "album"))
            al.allAlbumsRequested.connect(self.open_albums_page)
            al.picture_actions = self._picture_actions
        self.images.artistReady.connect(lambda name, _img: [p.artists.image_ready(name) for p in self.panels
                                                             if "artists" in p.order])
        self.images.albumReady.connect(lambda key, _img: [p.albums.cover_ready(key) for p in self.panels])
        self.images.albumReady.connect(lambda key, _img: [p.artists.cover_ready(key) for p in self.panels
                                                           if "artists" in p.order])
        self.images.albumReady.connect(lambda key, _img: self.artist_page.cover_ready(key))
        self.images.albumReady.connect(lambda key, _img: [p.cover_ready(key) for p in
                                                           [self.albums_page] + [w for w in self.custom_pages
                                                                                 if w.spec.get("kind") == "albums"]])
        self.images.artistReady.connect(lambda name, _img: self.artist_page.photo_ready(name))
        for p in self.panels:
            p.rated.connect(lambda r: pl.current and lib.set_rating([pl.current["id"]], r))
            p.upNextActivated.connect(self._on_upnext_activated)
            p.image_actions = self._image_actions
            p.header.credit_for = self.images.artist_credit
            p.refreshImagesRequested.connect(self._reload_images)
        self.images.artistReady.connect(self._on_artist_image)
        self.images.albumReady.connect(self._on_album_cover)
        b.refreshImagesRequested.connect(self._reload_images)
        self.images.missed.connect(self._on_image_missed)

        # internet radio
        self.stats_page.clearRequested.connect(self._clear_stats)
        self._remote_img_ready.connect(self._on_remote_img)
        self._stream_img_ready.connect(self._on_stream_img)
        self.player.streamPicture.connect(self._on_stream_picture)
        self.player.radioReconnecting.connect(self._radio_reconnecting)
        rp = self.radio_page
        rp.playStation.connect(self._play_station)
        rp.stopRequested.connect(pl.stop_radio)
        rp.logoReady.connect(self._on_station_logo)
        rp.pictureChanged.connect(self._on_station_picture)
        pl.radioChanged.connect(lambda st: rp.set_playing(st, ""))
        rp.findStation.connect(self._find_like_station)
        rp.library = lib
        rp.likeRequested.connect(self.like_current)
        b.likeRequested.connect(self.like_current)
        b.copyRequested.connect(lambda: self.play_radio_copy())
        b.artist_info.refreshRequested.connect(lambda name: self.artist_info.request(name, force=True))
        b.layoutChanged.connect(lambda: "artist_info" in b.all_placed() and b.artist_info.artist !=
                                self._info_artist(self.player.current) and self._request_artist_info(self.player.current))
        rp.playLibraryTrack.connect(self._play_library_track)
        rp.playCopy.connect(lambda tid, where: self.play_radio_copy(tid, where))
        rp.findInLibrary.connect(self._find_in_library)
        rp.searchFreeMusic.connect(self._search_free_music)
        rp.songsByArtist.connect(self.songs_by_online)
        rp.findSimilarArtist.connect(lambda a: self.find_similar(artist=a))
        rp.titleOrderChanged.connect(self._resplit_current)
        # find similar
        sp2 = self.similar_page
        self.finder.directory = rp.directory
        sp2.sources = self._free_sources()
        sp2.set_radio_page(rp)
        sp2.playStation.connect(self._play_station)
        sp2.findStation.connect(self._find_like_station)
        sp2.cleared.connect(self._similar_cleared)
        pl.radioChanged.connect(lambda _st: sp2.refresh_stations())
        self.finder.ready.connect(self._on_similar)
        self.finder.archiveReady.connect(
            lambda n, res: n == getattr(self, "_similar_req", -1) and not getattr(self, "_similar_auto", False)
            and self.similar_page.set_archive(res))
        sp2.playRemote.connect(lambda tracks, i: pl.play_remote(tracks, i))
        self.finder.stationsReady.connect(
            lambda n, res: n == getattr(self, "_similar_req", -1) and not getattr(self, "_similar_auto", False)
            and self.similar_page.set_stations(res))
        sp2.playIds.connect(lambda ids, i: pl.play_list(ids, i))
        sp2.enqueueIds.connect(lambda ids: (pl.enqueue(ids), self._flash(f"Added {len(ids)} songs to the queue")))
        sp2.findArtist.connect(lambda name: self.find_similar(artist=name))
        sp2.onlineArtist.connect(self.songs_by_online)
        sp2.showArtist.connect(lambda name: self._show_in_browser("artist_key", name))
        sp2.table.menuRequested.connect(lambda ids, pos: self._track_menu(ids, pos, "similar", sp2.table))
        sp2.table.rated.connect(lambda tid, r: lib.set_rating([tid], r))
        pl.ranOut.connect(self._keep_playing_similar)
        sp2.addToPlaylist.connect(self.add_online_to_playlist)
        sp2.findPlaying.connect(self._find_similar_playing)
        pl.trackChanged.connect(lambda t: sp2.set_playing_available(bool(t)))
        sp2.set_playing_available(False)
        # online sources
        fm = self.online_page.free
        fm.sources = self._free_sources()
        fm.artistSearch.connect(lambda _name: self._go_page(7) if fm is self.online_page.free else None)
        self.online_page.show_start()
        from musicwell import query as _Q
        try:
            _Q.set_plain_fields(json.loads(self.settings.value("search_plain_fields", "null") or "null"))
        except (TypeError, ValueError):
            pass
        fm.set_radio_page(rp)
        op = self.online_page
        op.set_radio_page(rp)
        op.station_finder = self._station_search
        op.playStation.connect(self._play_station)
        op.findStation.connect(self._find_like_station)
        fm.playRemote.connect(lambda tracks, i: pl.play_remote(tracks, i))
        fm.addToPlaylist.connect(self.add_online_to_playlist)
        fm.findArtist.connect(lambda name: self.find_similar(artist=name))
        for p_ in (fm, self.similar_page.free, self.online_strip.panel):
            p_.known_artists = self._library_artist_names
        os_ = self.online_strip.panel
        os_.sources = self._free_sources()
        os_.my = self.online_page.free.my
        os_.set_radio_page(rp)
        os_.playRemote.connect(lambda tracks, i: pl.play_remote(tracks, i))
        os_.addToPlaylist.connect(self.add_online_to_playlist)
        os_.findArtist.connect(lambda name: self.find_similar(artist=name))
        os_.search_artist = self.songs_by_online
        self.online_strip.openChanged.connect(lambda _on: self._size_online_strip())
        self.online_page.playRemote.connect(lambda tracks, i: pl.play_remote(tracks, i))
        self.online_page.addToPlaylist.connect(self.add_online_to_playlist)
        pl.trackChanged.connect(self.online_page.set_current_song)

    def shortcut_actions(self) -> list:
        """(id, name, default keys, action) for every shortcut that can be changed in Settings."""
        pl = self.player
        return [
            ("play_pause", "Play / pause", "Space", self._play_pause_jump),
            ("next", "Next song", "Ctrl+Right", lambda: pl.next()),
            ("previous", "Previous song", "Ctrl+Left", pl.previous),
            ("shuffle", "Shuffle on / off", "Ctrl+S", pl.toggle_shuffle),
            ("repeat", "Repeat", "Ctrl+R", pl.cycle_repeat),
            ("undo", "Undo moving or changing an item", "Ctrl+Z", self.undo_layout),
            ("redo", "Redo", "Ctrl+Shift+Z", self.redo_layout),
            ("lock", "Lock / unlock the window", "F2",
             lambda: self.set_customizing(not getattr(self, "customizing", False))),
            ("search", "Search", "Ctrl+F", self._focus_search),
            ("locate", "Go to the playing song", "Ctrl+J", self.locate_current),
            ("edit_tags", "Edit tags", "Ctrl+E", lambda: self._edit_tags(self._focused_table().selected_tracks())),
            ("queue", "Add to queue", "Ctrl+Return", lambda: pl.enqueue(self._focused_table().selected_ids())),
            ("queue_next", "Play next", "Ctrl+Shift+Return",
             lambda: pl.enqueue(self._focused_table().selected_ids(), front=True)),
            ("queue_up", "Move up in the queue", "Alt+Up", lambda: self._move_queue(-1)),
            ("queue_down", "Move down in the queue", "Alt+Down", lambda: self._move_queue(1)),
            ("panel", "Show / hide the side panel", "F9", self._toggle_panel),
            ("panel2", "Show / hide the second panel", "Shift+F9",
             lambda: self.set_panel2_visible(not self.now2.isVisible())),
            ("panel3", "Show / hide the top panel", "Ctrl+F9", lambda: self.set_panel3_visible(not self.now3.isVisible())),
            ("browser", "Show / hide the column browser", "Ctrl+B",
             lambda: self.set_browser(self.browser.fields(), not self.browser_visible())),
            ("rescan", "Rescan music folders for new and changed songs", "F5", self.rescan_library),
            ("reload_images", "Reload cover and artist photo", "Ctrl+F5", self._reload_images),
            ("lyrics", "Lyrics tab", "Ctrl+L", self._toggle_lyrics_page),
            ("like", "♥ Like the playing song", "Ctrl+Shift+L", self.like_current),
            ("similar", "Find music like this", "Ctrl+Shift+F", self._find_similar_playing),
            ("volume_up", "Volume up", "Ctrl+Up", lambda: self.bar.volume.setValue(self.bar.volume.value() + 5)),
            ("volume_down", "Volume down", "Ctrl+Down", lambda: self.bar.volume.setValue(self.bar.volume.value() - 5)),
            ("eq", "Equaliser", "Ctrl+Shift+E", self._open_eq),
            ("settings", "Settings", "Ctrl+,", self._open_settings),
            ("about", "About", "F1", self.open_about),
            ("quit", "Quit", "Ctrl+Q", self.quit_app),
        ]

    def shortcut_keys(self) -> dict:
        """id -> keys, with your changes from Settings ("" = none)."""
        try:
            mine = json.loads(self.settings.value("shortcuts", "{}") or "{}")
        except ValueError:
            mine = {}
        return {i: (mine[i] if isinstance(mine.get(i), str) else d) for i, _n, d, _f in self.shortcut_actions()}

    def apply_shortcuts(self):
        keys = self.shortcut_keys()
        for i, _n, _d, fn in self.shortcut_actions():
            sc = self._named_sc.get(i)
            if sc is None:
                sc = self._named_sc[i] = QShortcut(self)
                sc.activated.connect(fn)
            sc.setKey(QKeySequence(keys[i]))

    def _lock_keys(self, trailing_or: bool = True) -> str:
        """The lock key for messages: "F2 or " / "F2" (or Layouts → Lock when it has none)."""
        k = self.shortcut_text("lock")
        if not k:
            return "" if trailing_or else "Layouts → Lock"
        return f"{k} or " if trailing_or else k

    def shortcut_text(self, i: str) -> str:
        """e.g. "F2", for menus."""
        k = self.shortcut_keys().get(i, "")
        return QKeySequence(k).toString(QKeySequence.NativeText) if k else ""

    def _shortcuts(self):
        def sc(keys, fn):
            s = QShortcut(QKeySequence(keys), self)
            s.activated.connect(fn)
            return s
        self._named_sc = {}
        self.apply_shortcuts()
        sc("Escape", self._escape)
        # media keys while the window has focus
        sc("Media Play", self._play_pause_jump)
        sc("Toggle Media Play/Pause", self._play_pause_jump)
        sc("Media Pause", lambda: self.player.play_pause() if self.player.is_playing() else None)
        sc("Media Next", lambda: self.player.next())
        sc("Media Previous", self.player.previous)
        sc("Media Stop", self._stop)
        for n in range(1, 10):  # Ctrl+1... follow the tab order
            sc(f"Ctrl+{n}", lambda n=n: (lambda v: self._nav_clicked(v[n - 1]) if n <= len(v) else None)(
                self.visible_tab_order()))
        for n in range(1, 10):
            sc(f"Ctrl+Alt+{n}", lambda n=n: self._layout_by_number(n))
        for n in range(6):
            sc(f"Alt+{n}", lambda n=n: self.library.set_rating(self._focused_table().selected_ids(), n))

    def rescan_library(self):
        """Look through the music folders again for new, changed and removed songs."""
        if not self.library.folders() and not self.library.files():
            self._flash("No music folders yet: Settings → Library → Add folder", 4000)
            return
        self._flash("Looking for new and changed music…", 3000)
        self.library.scan()

    def _focused_table(self) -> SongTable:
        i = self.pages.currentIndex()
        if i == 6:
            return self.similar_page.table
        if i >= self.N_BUILTIN and i - self.N_BUILTIN < len(self.custom_pages):
            return getattr(self.custom_pages[i - self.N_BUILTIN], "table", None)
        if i == 0 and self.lib_stack.currentIndex() == 2:
            return self.artist_page.table
        if i == 0 and self.lib_stack.currentIndex() == 3:
            return self.albums_page.table
        return [self.table, self.queue_table, self.pl_table][i] if i < 3 else self.table

    def set_customizing(self, on: bool):
        """Unlock (on) or lock the window. Unlocked, panels, items, the bar and tabs can be dragged."""
        if getattr(self, "_syncing_custom", False):
            return
        self._syncing_custom = True
        was = getattr(self, "customizing", False)
        try:
            self.customizing = on
            dk = getattr(self, "_delete_key", None)
            if dk is not None:
                if on:
                    QApplication.instance().installEventFilter(dk)
                else:
                    QApplication.instance().removeEventFilter(dk)
            self.bar.set_editing(on)
            self.now.set_editing(on and self.now.isVisible())
            self.now2.set_editing(on and self.now2.isVisible())
            self.now3.set_editing(on and self.now3.isVisible())
            self.now4.set_editing(on and self.now4.isVisible())
            for f in getattr(self, "edit_frames", []):
                f.set_on(on)
            SongTable.columns_unlocked = on  # column headers move only while unlocked
            for tbl in self.findChildren(SongTable):
                tbl.horizontalHeader().setSectionsMovable(on)
                if not on:
                    tbl.horizontalHeader().viewport().unsetCursor()
            self.browser.set_unlocked(on)
            for b in getattr(self, "nav_buttons", []):  # open hand on tabs
                b.setCursor(Qt.OpenHandCursor if on else Qt.PointingHandCursor)
            for sp in (self.body, self.lib_split):  # splitter handles
                for i in range(1, sp.count()):
                    sp.handle(i).setEnabled(on)
            self._top_hand(on)
            if on and self.bar.isHidden() and self.settings.value("bar_visible", True, bool):
                self.bar.show()
        finally:
            self._syncing_custom = False
        if on and not was:
            self._flash("Unlocked — drag anything to move it, drag it out to remove it, right-click → Add here "
                        f"to add. Press {self._lock_keys()}Esc (or Layouts → Lock) when you're done.", 9000)
        if not on and was:
            self._flash("Locked", 1500)
            QTimer.singleShot(0, self._save_scratch_layout)

    def _part_editing(self, on: bool):
        """The play bar or a panel entered or left edit mode on its own: everything follows."""
        if not getattr(self, "_syncing_custom", False) and on != getattr(self, "customizing", False):
            self.set_customizing(on)

    def _escape(self):
        if getattr(self, "customizing", False):
            self.set_customizing(False)
            return
        if self.pages.currentIndex() == 0 and self.lib_stack.currentIndex() in (2, 3) and not self.search.text():
            self._leave_artist_page()
            return
        if self.search.hasFocus() or self.search.text():
            self.search.clear()  # the albums' and artists' own filter boxes keep their text
            self.table.setFocus()

    def apply_theme(self):
        # Restyling every widget takes about half a second: only do it when the stylesheet changed.
        css = self.theme.stylesheet()
        if css != getattr(self, "_applied_css", None):
            app = QApplication.instance()
            app.setOverrideCursor(Qt.WaitCursor)  # it takes a moment
            try:
                # Clear the old stylesheet first; switching directly makes Qt re-resolve every widget twice.
                if app.styleSheet():
                    app.setStyleSheet("")
                app.setStyleSheet(css)
            finally:
                app.restoreOverrideCursor()
            self._applied_css = css
            for p in self.panels:
                if p.text_sizes:
                    p.apply_text_sizes()
            if self.bar.text_sizes:
                self.bar.apply_text_sizes()
            for key in ("lyrics", "songs"):
                if self._page_text_size(key) != 1:
                    self.set_page_text_size(key, self._page_text_size(key), save=False)
        self.panel_btn.apply(self.theme, color_key="muted")
        if self.tab_style() != "words":
            self._apply_tab_names()  # tab icons in the new colours
        self.settings_btn.apply(self.theme, color_key="muted")
        self.layout_btn.apply(self.theme, color_key="muted")
        self._update_albums_btn()
        self.add_tab_btn.apply(self.theme, color_key="muted")
        for t in (self.table, self.queue_table, self.pl_table, *self._custom_tables()):
            t.refresh_theme()
        self.now.refresh_theme()
        self.lyrics_page.refresh_theme()
        self.stats_page.refresh_theme()
        self._refresh_bar()
        if getattr(self, "eq_window", None) is not None:
            self.eq_window.refresh_theme()
        self.search.update()
        self._refresh_upnext()
        self.now._fill_fields()

    def artwork_mode(self) -> str:
        """off / accent / full"""
        s = self.settings
        mode = s.value("artwork_colours")
        if mode not in ("off", "accent", "full"):
            mode = "accent" if s.value("accent_follow", True, bool) else "off"
        return mode

    def update_colours(self, art=None, force: bool = False):
        """Work out the window's colours from the theme, settings and the playing song's artwork."""
        s = self.settings
        mode = self.artwork_mode()
        art = self._current_art if art is None else art
        self.theme.mode = s.value("theme", "dark")
        base_dark = th.PALETTES[self.theme.mode]["dark"]
        fixed = th.QColor(s.value("accent", th.PALETTES[self.theme.mode]["accent"]))
        custom, accent = None, fixed
        if art is not None and mode in ("accent", "full"):
            if mode == "full":
                custom = palette_from_image(art, base_dark)
            accent = accent_from_image(art, base_dark) or fixed
        # artwork as the window background
        bg_mode = s.value("artwork_background", "off")
        see = {"soft": 0.22, "strong": 0.42}.get(bg_mode, 0.0) if art is not None else 0.0
        self.backdrop.set_image(art if see else None)
        old = (self.theme.custom, self.theme.accent.name(), self.theme.see_through)
        self.theme.custom = custom
        self.theme.accent = accent
        self.theme.see_through = see
        if force or old != (custom, accent.name(), see):
            self.apply_theme()

    def _refresh_bar(self):
        pl = self.player
        self.bar.shuffle.setChecked(pl.shuffle)
        self.bar.repeat.setChecked(pl.repeat != 0)
        self.bar.repeat.setToolTip(["Repeat: off", "Repeat: all", "Repeat: one"][pl.repeat] + " (Ctrl+R)")
        self.bar.stop_after.setChecked(pl.stop_after_current)
        self.bar.lyrics_on = self.pages.currentIndex() == 3
        self.bar.panel_on = not self.now.isHidden()
        self.bar.apply_theme(self.theme, pl.is_playing(), pl.repeat, pl.is_muted(), pl.volume)

    def _refilter(self):
        tracks = self.library.all_tracks()
        pred = compile_query(self.search.text())
        if pred:
            tracks = [t for t in tracks if pred(t)]
        self.browser.set_tracks(tracks)

    def _show_view(self, tracks: list[dict]):
        self._view_tracks = tracks
        sel = set(self.table.selected_ids())
        self.table.model_.set_rows(tracks)
        if sel:
            sm = self.table.selectionModel()
            for r, t in enumerate(self.table.model_.rows):
                if t["id"] in sel:
                    sm.select(self.table.model_.index(r, 0), SEL_ROWS)
        refollow = self._refollow
        if refollow and time.monotonic() < refollow[1] and not self.search.text().strip():
            QTimer.singleShot(0, refollow[0])  # just after the search was emptied (see _back_after_search)
        self._update_count()

    def _update_count(self):
        if self.library.is_scanning():
            return
        if self._status_msg:
            self.status.setText(self._status_msg)
            return
        n = len(self._view_tracks)
        total = sum(t["length"] or 0 for t in self._view_tracks)
        hours = total / 3600
        span = f"{hours:.1f} hours" if hours >= 1 else fmt_time(total)
        self.status.setText(f"{n:,} song{'s' if n != 1 else ''} · {span}" if n else "")

    def _set_status(self, text: str):
        self.status.setText(text)

    def _scan_progress(self, n: int, text: str):
        """Show scan progress in the top bar once it takes a while."""
        import time as _time
        text = text or f"Scanning… {n:,} files"
        if _time.monotonic() - getattr(self.library, "_scan_t0", 0) < 1.5:
            return  # quick startup scan: nothing to show
        total = getattr(self.library.scanner, "total", 0) if self.library.scanner else 0
        self.scan_text.setText(text + ("  ·  the songs found so far are ready to play" if self.library.tracks and total
                                       else ""))
        if total:
            self.scan_bar.setRange(0, total)
            self.scan_bar.setValue(min(n, total))
        else:
            self.scan_bar.setRange(0, 0)  # still looking: indeterminate
        self.scan_banner.show()

    def _flash(self, text: str, ms: int = 5000):
        """A message in the top bar for a while (a newer one replaces it)."""
        self._status_msg = text
        self.status.show()
        self.status.setText(text)
        self.status.setToolTip(text)
        if not hasattr(self, "_flash_timer"):
            self._flash_timer = QTimer(self, singleShot=True)
            self._flash_timer.timeout.connect(self._clear_flash)
        self._flash_timer.start(ms)

    def _clear_flash(self):
        self._status_msg = ""
        if "status" in self.top_hidden():
            self.status.hide()
        self.status.unsetCursor()
        self.status.setToolTip("")
        self._update_count()

    def _on_library_changed(self):
        has = bool(self.library.tracks)
        from musicwell import radio as radio_mod
        radio_mod.KNOWN_ARTISTS = {n.lower() for t in self.library.tracks.values()
                                   for n in (t.get("artist"), t.get("albumartist")) if n}
        if self.lib_stack.currentIndex() == 2 and has:
            ap = self.artist_page
            self.artist_page.refresh(self._artist_track_dicts(ap.name, ap.kind))
        elif self.lib_stack.currentIndex() == 3 and has:
            self.albums_page.set_tracks(self.library.all_tracks())
        else:
            self.lib_stack.setCurrentIndex(1 if has or self.library.folders() else 0)
        self._refilter()
        # drop queued tracks that no longer exist
        self.player.qlist = [e for e in self.player.qlist if self.library.get(e["id"])]
        self._on_queue_changed()
        self._show_playlist()
        self._refresh_custom_tabs()
        for p in self.panels:
            self._fill_artist_list(p)

    def _bar_source(self, name: str) -> BarSource:
        """The hidden panel that keeps panel items in the play bar ("now5") or the top bar ("now6") up to date."""
        src = getattr(self, name)
        if src is None:
            src = BarSource(self.theme)
            setattr(self, name, src)
            self.now.mirrors.append(src)
            self.now.header.mirrors.append(src.header)
            last = getattr(self.now, "last_calls", {})
            for fn in sorted(last, key=lambda f: f != "set_track"):  # catch up with the song playing
                a, k = last[fn]
                getattr(src, fn)(*a, **k)
            for fn, (a, k) in getattr(self.now.header, "last_calls", {}).items():
                getattr(src.header, fn)(*a, **k)
        return src

    def _bar_panel_items(self, keys: list):
        if self.now5 is None and not keys:
            return
        self._bar_source("now5").set_items(keys)
        if not hasattr(self, "library"):
            return
        self._fill_artist_list(self.now5)
        if "songs" in keys:
            self._refresh_panel_songs_soon()

    def _fill_artist_list(self, p):
        """Fill the panel's artist list and All albums."""
        if "artist_info" in p.order and p.artist_info.artist != self._info_artist(self.player.current):
            self._request_artist_info(self.player.current)
        if "albums" in p.order:
            p.albums.set_tracks(self.library.all_tracks())
            p.albums.set_track(self.player.current)
        if "artists" not in p.order:
            return
        from musicwell.artistlist import artist_rows
        from musicwell.albumsview import album_groups
        tracks = self.library.all_tracks()
        p.artists.album_count = len(album_groups(tracks))
        p.artists.song_count = len(tracks)
        p.artists.set_rows(artist_rows(tracks, p.artists.kind))
        p.artists.set_track(self.player.current)

    def _artist_tracks(self, name: str, kind: str) -> list[int]:
        from musicwell.models import library_order
        key = "artist_key" if kind == "album" else "artist"
        n = name.lower()
        tracks = [t for t in self.library.all_tracks() if (t.get(key) or "").lower() == n]
        return [t["id"] for t in sorted(tracks, key=library_order)]

    def _play_artist(self, name: str, kind: str, shuffle: bool):
        ids = self._artist_tracks(name, kind)
        if not ids:
            return
        if shuffle:
            import random
            random.shuffle(ids)
        # double-click also opens the artist page
        self.open_artist_page(name, kind)
        self.player.play_list(ids, 0)
        self._flash(f"{'Shuffling' if shuffle else 'Playing'} {name} — {len(ids)} song{'s' if len(ids) != 1 else ''}",
                    3000)

    def _queue_artist(self, name: str, kind: str):
        ids = self._artist_tracks(name, kind)
        if ids:
            self.player.enqueue(ids)
            self._flash(f"Added {len(ids)} song{'s' if len(ids) != 1 else ''} by {name} to the queue", 3000)

    def _album_tracks(self, name: str, album: str, kind: str) -> list[int]:
        from musicwell.models import library_order
        key = "artist_key" if kind == "album" else "artist"
        n, a = name.lower(), (album or "").lower()
        tracks = [t for t in self.library.all_tracks()
                  if (t.get(key) or "").lower() == n and album_title(t.get("album") or "").lower() == album_title(a).lower()]
        return [t["id"] for t in sorted(tracks, key=library_order)]

    def _play_album(self, name: str, album: str, kind: str, shuffle: bool):
        ids = self._album_tracks(name, album, kind)
        if not ids:
            return
        if shuffle:
            import random
            random.shuffle(ids)
        self.player.play_list(ids, 0)
        self._flash(f"{'Shuffling' if shuffle else 'Playing'} {album or 'Unknown Album'} — {name}", 3000)

    def _queue_album(self, name: str, album: str, kind: str):
        ids = self._album_tracks(name, album, kind)
        if ids:
            self.player.enqueue(ids)
            self._flash(f"Added {album or 'Unknown Album'} ({len(ids)} songs) to the queue", 3000)

    def _albums_tab_page(self):
        """The Albums tab: (page number, page) or (None, None)."""
        for i, (spec, w) in enumerate(zip(self.custom_specs, self.custom_pages)):
            if spec.get("kind") == "albums" and self._tab_shown(self.N_BUILTIN + i):
                return self.N_BUILTIN + i, w
        return None, None

    def _panel_album(self, name: str, album: str, kind: str):
        """An album clicked in a panel list: shown on All albums while you're using it."""
        page, w = self._albums_tab_page()
        if page is not None and self.pages.currentIndex() == page:
            if w.select_album(name if kind == "album" else "", album):
                return
        if getattr(self, "_albums_mode", False):
            if not self._albums_showing():
                self.open_albums_page(in_library=True)
            if self.albums_page.select_album(name if kind == "album" else "", album):
                return
        self._album_picked(name, album, kind)

    def _album_picked(self, name: str, album: str, kind: str):
        """Show an album from the artist list in the library."""
        if not name:  # compilation: the album on its own
            self._leave_artist_page()
            self._go_page(0)
            self.search.setText(f'album="{album}"')
            return
        if kind == "album":
            self._show_in_browser("artist_key", name)
            if not self.browser.select_value("album", album):
                self.search.setText(f'artist="{name}" album="{album}"')
        else:
            self._go_page(0)
            self.search.setText(f'artist="{name}" album="{album}"')

    def _artist_track_dicts(self, name: str, kind: str) -> list[dict]:
        key = "artist_key" if kind == "album" else "artist"
        n = name.lower()
        return [t for t in self.library.all_tracks() if (t.get(key) or "").lower() == n]

    def open_artist_page(self, name: str, kind: str = "album", fresh: bool = True):
        """Open the artist page: photo, album covers and songs."""
        tracks = self._artist_track_dicts(name, kind)
        if not tracks:
            return
        self.artist_page.show_artist(name, tracks, kind)
        if fresh:
            self.artist_page.show_all()
        if self._artist_home():
            self.settings.setValue("artist_home_name", name)  # the Artists layout opens on them next time
        self.artist_info.request(name)
        cur = self.player.current
        self.artist_page.set_current(cur["id"] if cur else None)
        self._go_page(0)
        self.lib_stack.setCurrentIndex(2)
        if cur and not cur.get("stream") and self.artist_page.jump_to(cur["id"]):
            pass  # their song is playing: found in the list

    def _info_artist(self, t) -> str:
        if not t:
            return ""
        if t.get("stream"):
            return t.get("artist") or ""  # on the radio: the song's artist, not the station
        return t.get("artist") or t.get("albumartist") or ""

    def _info_views(self) -> list:
        """Every About the artist item, in the panels and the play bar."""
        return [p.artist_info for p in self.panels] + [self.bar.artist_info]

    def _request_artist_info(self, t):
        name = self._info_artist(t)
        for v in self._info_views():
            if v.artist != name and not name:
                v.show_info("", {})
        if name and (any("artist_info" in p.order for p in self.panels) or "artist_info" in self.bar.all_placed()):
            self.artist_info.request(name)

    def _on_artist_info(self, artist: str, info):
        for v in self._info_views():
            if self._info_artist(self.player.current).lower() == artist.lower():
                v.show_info(artist, info)
        if self.artist_page.name.lower() == artist.lower():
            self.artist_page.about.show_info(self.artist_page.name, info)

    def _albums_home(self) -> bool:
        """Albums layout: the covers are the Library page."""
        return not self.settings.value("albums_back", True, bool)

    def _artist_home(self) -> bool:
        """Artists layout: the artist page is the Library page."""
        return self.settings.value("library_home", "") == "artist"

    def open_artist_home(self):
        """Artists layout Library page: the last artist, the playing one, or the first."""
        name = self.settings.value("artist_home_name", "") or ""
        cur = self.player.current
        if not name and cur and not cur.get("stream") and not cur.get("remote"):
            name = primary_artist(cur.get("artist_key") or cur.get("artist") or "")
        if not name or not self._artist_track_dicts(name, "album"):
            names = sorted({primary_artist(t.get("artist_key") or t.get("artist") or "")
                            for t in self.library.tracks.values()} - {""}, key=str.lower)
            name = names[0] if names else ""
        if name:
            self.open_artist_page(name, "album", fresh=False)

    def _follow_in_layout(self, prev):
        """A new song started: the Artists / Albums layouts follow it."""
        cur = self.player.current
        if not cur or cur.get("stream") or cur.get("remote") or self.pages.currentIndex() != 0:
            return
        if self._artist_home():
            page = self.artist_page
            if self.lib_stack.currentIndex() == 1:
                return  # showing the song list: stay
            if page.table.recently_used():
                return
            shown = (page.name or "").strip().lower()
            was = {(prev or {}).get(k) or "" for k in ("artist_key", "artist")} if prev else set()
            was = {n.strip().lower() for n in was | {primary_artist(n) for n in was} if n.strip()}
            if shown and prev and shown not in was:
                return  # you went to look at another artist
            self._jump_to_playing()
        elif self._albums_home() and self.lib_stack.currentIndex() == 3:
            page = self.albums_page
            if page.table.recently_used():
                return
            sel = list(getattr(page, "_sel", []) or [])
            prev_key = page.key_of(prev["id"]) if prev and prev.get("id") is not None else None
            if page._playing_ids or not sel or not prev or prev_key in sel:
                self._jump_to_playing()

    def _jump_to_playing(self):
        """Artists layout: show the playing song's artist, album and song."""
        cur = self.player.current
        if not cur or cur.get("stream") or cur.get("remote") or cur.get("id") is None:
            return
        tid = cur["id"]
        if self.lib_stack.currentIndex() == 1 and self.search.text().strip():
            return  # search results showing: they stay
        if self._artist_home():
            name = cur.get("artist_key") or ""
            if not self._artist_track_dicts(name, "album"):
                name = primary_artist(name or cur.get("artist") or "")
            if name and self._artist_track_dicts(name, "album"):
                if (self.artist_page.name or "").lower() != name.lower() or self.lib_stack.currentIndex() != 2:
                    self.open_artist_page(name, "album", fresh=False)
                QTimer.singleShot(0, lambda: self.artist_page.jump_to(tid))
                for p in self.panels:  # select the artist in the artist list
                    if "artists" in p.order and hasattr(p.artists, "show_name"):
                        p.artists.show_name(name)
        elif self._albums_home() and self.lib_stack.currentIndex() == 3:
            self.albums_page.jump_to(tid)

    def _leave_artist_page(self):
        """Back from the artist page or All albums to the column browser."""
        if self._albums_home():
            if self.lib_stack.currentIndex() == 2:
                self.open_albums_page(in_library=True)
            return
        if self._artist_home():
            if self.lib_stack.currentIndex() != 2:
                self.open_artist_home()  # All albums opened from the artist list: back to the artist
            return
        if self.lib_stack.currentIndex() == 3:
            self._albums_mode = False
            self.settings.setValue("albums_open", False)
        if self.lib_stack.currentIndex() in (2, 3):
            self.lib_stack.setCurrentIndex(1)

    def _search_edited(self, text: str):
        """Typing in the search box shows matching songs in the song list, in every layout."""
        if self._albums_home():
            self._go_page(0)
            if text.strip():
                self.lib_stack.setCurrentIndex(1)
            elif self.lib_stack.currentIndex() == 1:
                self.open_albums_page(in_library=True)
            return
        if self._artist_home():
            self._go_page(0)
            if text.strip():
                self.lib_stack.setCurrentIndex(1)
            elif self.lib_stack.currentIndex() == 1:
                self.open_artist_home()
            return
        self._leave_artist_page()
        self._go_page(0)

    _played_in_search = None
    _place_before_search = None
    _refollow = None

    def _top_song_id(self):
        idx = self.table.indexAt(QPoint(2, 2))
        return self.table.model_.rows[idx.row()]["id"] if idx.isValid() else None

    def _put_on_top(self, tid):
        from PySide6.QtWidgets import QAbstractItemView
        r = next((i for i, t in enumerate(self.table.model_.rows) if t["id"] == tid), -1)
        if r >= 0:
            self.table.scrollTo(self.table.model_.index(r, max(0, self.table.model_.column_of("title"))),
                                QAbstractItemView.PositionAtTop)

    def _back_after_search(self):
        """Search emptied: show the song you played from the results, or the one you were on."""
        if self.search.text().strip():
            return
        if self._played_in_search is not None:
            self._place_before_search = None
            self._show_played_after_search()
            return
        tid, self._place_before_search = self._place_before_search, None
        if tid is not None and self.pages.currentIndex() == 0 and self.lib_stack.currentIndex() == 1:
            self._put_on_top(tid)
            # the list may be refilled a moment later
            self._refollow = (lambda: self._put_on_top(tid), time.monotonic() + 2.5)


    def _show_played_after_search(self):
        """The search was emptied after playing a result: show that song."""
        tid, self._played_in_search = self._played_in_search, None
        cur = self.player.current
        if tid is None or not cur or cur.get("id") != tid or self.search.text().strip():
            return  # nothing played from the results, or it has moved on
        if self._artist_home() or (self._albums_home() and self.lib_stack.currentIndex() == 3):
            self._jump_to_playing()
            return
        if self.lib_stack.currentIndex() == 1:
            self.table.follow_id(tid, True)
            # the list may be refilled a moment later
            self._refollow = (lambda: self.table.follow_id(tid, True), time.monotonic() + 2.5)

    def _albums_showing(self) -> bool:
        return self.pages.currentIndex() == 0 and self.lib_stack.currentIndex() == 3

    def _toggle_albums_page(self):
        if self._albums_showing():
            self._leave_artist_page()
        else:
            self.open_albums_page()

    def _update_albums_btn(self):
        if hasattr(self, "albums_btn") and hasattr(self, "lib_stack"):
            on = self._albums_showing()
            self.albums_btn.apply(self.theme, color_key="accent" if on else "muted")
            self.albums_btn.setToolTip("Back to the song list (Esc)" if on else
                                       "All albums — every album as covers (click again for the song list)")

    def open_albums_page(self, in_library: bool = False):
        """Every album as covers: the Albums tab, or All albums in the Library tab."""
        page, _w = self._albums_tab_page()
        if page is not None and not in_library:
            self._go_page(page)
            return
        self.albums_page.set_tracks(self.library.all_tracks())
        cur = self.player.current
        self.albums_page.table.model_.set_current(cur["id"] if cur else None)
        self._go_page(0)
        self._albums_mode = True  # panel album clicks stay here until you go back
        self.settings.setValue("albums_open", True)
        self.lib_stack.setCurrentIndex(3)

    def _wire_albums(self, page):
        """Connect an All albums page (Library tab or a user tab)."""
        page.cover_provider = lambda track, px: self.images.album_thumb(track, px)
        page.playRequested.connect(lambda ids, i: self.player.play_list(ids, i))
        if hasattr(page, "listReplaced"):
            page.listReplaced.connect(self.player.replace_list)
        page.queueRequested.connect(lambda ids: ids and (self.player.enqueue(ids),
                                                         self._flash(f"Added {len(ids)} songs to the queue", 3000)))
        page.artistRequested.connect(lambda name: self.open_artist_page(name, "album"))
        page.browseRequested.connect(lambda artist, album: self._album_picked(artist, album, "album"))

    def _artist_browse(self, name: str, kind: str):
        """Select the artist in the column browser, or search for them."""
        self._leave_artist_page()
        if kind == "album":
            self._show_in_browser("artist_key", name)
        else:
            self._go_page(0)
            self.search.setText(f'artist="{name}"')

    def open_all_songs(self):
        """Every song in the song list (the artist list's "All artists" row)."""
        self._go_page(0)
        if self.search.text():
            self.search.blockSignals(True)  # an emptied box would go back to the artist
            self.search.clear()
            self.search.blockSignals(False)
            self._refilter()
        self.browser.reset()
        if self.lib_stack.currentIndex() == 3:
            self._albums_mode = False
            self.settings.setValue("albums_open", False)
        self.lib_stack.setCurrentIndex(1)
        cur = self.player.current
        if cur and cur.get("id") is not None:
            QTimer.singleShot(0, lambda: self.table.scroll_to_id(cur["id"], select=False))

    def _play_all_songs(self, shuffle: bool = False):
        """Play the whole song list."""
        ids = [t["id"] for t in (self._view_tracks or self.library.all_tracks())]
        if not ids:
            return
        if shuffle:
            import random
            random.shuffle(ids)
        self.player.play_list(ids, 0)
        self._flash(f"{'Shuffling' if shuffle else 'Playing'} all {len(ids):,} songs", 3000)

    def _artist_picked(self, name: str, kind: str):
        self.open_artist_page(name, kind)

    def _on_scan_finished(self, changed: int, removed: int):
        self.scan_banner.hide()
        self._update_count()
        skipped, self._scan_skipped = getattr(self, "_scan_skipped", 0), 0
        if changed or removed or skipped:
            bits = []
            if changed:
                bits.append(f"{changed:,} added or updated")
            if removed:
                bits.append(f"{removed:,} removed")
            if skipped:
                bits.append(f"{skipped:,} file{'s' if skipped != 1 else ''} couldn't be added "
                            "(About → System → Open log lists them)")
            self._flash("Library: " + ", ".join(bits), 9000 if skipped else 4000)

    def _on_track_updated(self, tid: int):
        for t in (self.table, self.queue_table, self.pl_table, *self._custom_tables()):
            t.model_.track_changed(tid)
        if any(("artists" in p.order and p.artists.sort == "plays") or ("albums" in p.order and p.albums.sort == "plays")
               for p in self.panels):
            if not hasattr(self, "_artists_timer"):
                self._artists_timer = QTimer(self, singleShot=True, interval=1500)
                self._artists_timer.timeout.connect(lambda: [self._fill_artist_list(p) for p in self.panels])
            self._artists_timer.start()
        # ratings and play counts can change search tabs (e.g. Favourites)
        if any(w.is_search for w in self.custom_pages):
            if not hasattr(self, "_custom_refresh_timer"):
                self._custom_refresh_timer = QTimer(self, singleShot=True, interval=600)
                self._custom_refresh_timer.timeout.connect(lambda: self._refresh_custom_tabs("search"))
            self._custom_refresh_timer.start()
        if self.player.current and self.player.current["id"] == tid:
            self.now.update_stats(self.player.current)
            self.bar.set_rating(self.player.current["rating"])
            self._update_like_state()

    def _choose_folder(self):
        d = ask_music_folder(self, self.library.folders())
        if d:
            self.library.add_folder(d)
            self.lib_stack.setCurrentIndex(1)

    def locate_current(self):
        cur = self.player.current
        if not cur:
            return
        self._leave_artist_page()
        self._go_page(0)
        if not self.table.scroll_to_id(cur["id"]):
            self.search.clear()
            self.browser.reset()
            self._refilter()
            self.table.scroll_to_id(cur["id"])
        self.table.setFocus()

    def _show_in_browser(self, field: str, value):
        self._leave_artist_page()
        self._go_page(0)
        if self.search.text():
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
            self._refilter()
        for pane in self.browser.panes:
            pane.list.clearSelection()
        self.browser.set_tracks(self.browser.base)
        if not self.browser.select_value(field, value) and field == "artist_key":
            self.search.setText(f'artist="{value}"')

    def _on_track_changed(self, t):
        if t and not t.get("stream"):
            from musicwell import log as mwlog
            mwlog.log.info("Playing %s%s", mwlog.song(t), " on " + self.cast_ctl.name
                           if self.cast_ctl is not None and self.cast_ctl.is_connected else "")
        self._request_artist_info(t)
        for tbl in (self.table, self.queue_table, self.pl_table, self.similar_page.table, *self._custom_tables()):
            tbl.model_.set_current(t["id"] if t else None)
        for ap in [self.albums_page, self.artist_page] + [w for w in self.custom_pages if hasattr(w, "note_current")]:
            ap.note_current(t["id"] if t else None)
        self.similar_page.set_playing_item(t["item"]["identifier"] if t and t.get("remote") else "")
        self.online_page.free.set_playing_item(t["item"]["identifier"] if t and t.get("remote") else "")
        if not (t and t.get("stream")):
            self._update_like_state()
            self.radio_page.update_like_button()
            self._show_radio_copy(None)
        if t is not None and t.get("stream"):
            self._on_stream_changed(t)
            return
        if t is not None and t.get("remote"):
            self._on_remote_changed(t)
            return
        self._request_lyrics(t)
        prev = getattr(self, "_followed_track", None)
        self._followed_track = t
        if t is not None and self.search.text().strip() and self.lib_stack.currentIndex() == 1:
            self._played_in_search = t["id"]  # started from search results: shown when the search is emptied
        if t is not None and self.settings.value("follow_playing", "select") != "off":
            QTimer.singleShot(0, lambda tid=t["id"]: self._follow_playing(tid))
            QTimer.singleShot(0, lambda p=prev: self._follow_in_layout(p))
        if t is None:
            self.now.set_track(None, None, None)
            self.bar.set_track(None, None)
            self.setWindowTitle(APP_NAME)
            return
        art = self.images.album_cover(t)
        self._current_art = art
        artist_img = self.images.artist_image(t["artist_key"] or t["artist"], t["path"])
        self.update_colours(art)
        self.now.levelling = self.now2.levelling = self.now3.levelling = self.now4.levelling = self._levelling_text(t)
        self.now.set_track(t, art, artist_img)
        self.bar.set_track(t, art)
        self._refresh_upnext()
        self.setWindowTitle(f"{t['title']} — {t['artist'] or 'Unknown Artist'} · {APP_NAME}")
        self._mark_from_queue(announce=True)

    def _mark_from_queue(self, announce: bool = False):
        """Mark a queued song: "FROM YOUR QUEUE" over the title and a note."""
        pl = self.player
        tid = pl.queue_playing_id()
        cur = pl.current
        if tid is None or not cur or cur.get("id") != tid:
            self.bar.set_queue_tag("")
            if announce and getattr(self, "_qtoast", None) is not None:
                self._qtoast.hide()  # queue finished: hide its note
            return
        n = len(pl.queue)
        self.bar.set_queue_tag("FROM YOUR QUEUE", f"{n} more queued" if n else "The last song in your queue")
        if announce and self.pages.currentIndex() != 1:  # not when the Queue page is showing
            more = f"{n} more queued" if n else "the last song in your queue"
            self._queue_toast(f"<b>▶ From your queue:</b> {_html.escape(cur.get('title') or '')}"
                              + (f" — {_html.escape(cur['artist'])}" if cur.get("artist") else "")
                              + f"<br><span style='font-size:9pt'>{more}</span>")

    def _queue_toast(self, html: str):
        t = getattr(self, "_qtoast", None)
        if t is None:
            t = self._qtoast = _ToastLabel(self.centralWidget())
            t.setObjectName("QueueToast")
            t.setTextFormat(Qt.RichText)
            t.setCursor(Qt.PointingHandCursor)
            t.setToolTip("Show the queue")
            t.clicked.connect(lambda: (t.hide(), self.nav_buttons[1].click()))
            self._qtoast_timer = QTimer(self, singleShot=True, interval=5000)
            self._qtoast_timer.timeout.connect(t.hide)
        t.setText(html)
        t.adjustSize()
        c = self.centralWidget()
        bar_top = self.bar.mapTo(c, QPoint(0, 0)).y() if self.bar.isVisible() else c.height()
        t.move(max(8, (c.width() - t.width()) // 2), max(8, bar_top - t.height() - 12))
        t.show()
        t.raise_()
        self._qtoast_timer.start()

    def _play_station(self, st: dict):
        self.player.play_station(st)
        self.stations.played(st)
        self._flash(f"Tuning in to {st['name']}…")

    def _station_art(self, st: dict):
        img = self.radio_page.logo_image(st)
        if img is None:
            from musicwell.artwork import placeholder
            img = placeholder(512, st["name"], self.theme.accent, 0)
        return img

    def _on_stream_changed(self, t: dict):
        """A station started or sent a new song title."""
        st = t["station"]
        art = self._station_art(st)
        self._current_art = art
        artist = t["artist"]
        artist_img = self.images.artist_image(artist, "") if artist else None
        self._stream_no_artist_img = artist_img is None
        self.update_colours(art)
        self.now.set_track(t, art, artist_img)
        self.bar.set_track(t, art)
        self._refresh_upnext()
        self.radio_page.set_playing(st, t.get("now_playing", ""))
        self._update_like_state()
        self._note_radio_song(st, t.get("now_playing", ""))
        if artist:
            self._request_lyrics(t)
        else:
            self._lyrics_tid = t["id"]
            self.lyrics_page.set_heading(t)
            self.lyrics_page.view.set_lyrics(None, "Lyrics show here when the station says which song is playing")
            self.now.set_lyrics(None)
        song = t.get("now_playing") or st["name"]
        self.setWindowTitle(f"{song} · {st['name']} · {APP_NAME}" if t.get("now_playing") else f"{st['name']} · {APP_NAME}")

    def _radio_reconnecting(self, on: bool):
        """The station dropped: show a note while reconnecting."""
        st = self.player.station
        if on and st:
            self._queue_toast(f"<b>Connecting to {_html.escape(st.get('name') or 'the station')} again…</b>"
                              "<br><span style='font-size:9pt'>the station stopped sending for a moment</span>")
            self._qtoast_timer.stop()  # shown until it's back
        elif getattr(self, "_qtoast", None) is not None and "again…" in self._qtoast.text():
            self._qtoast.hide()

    def _on_stream_picture(self, url: str):
        """A station sent an image of the song: fetch it in the background."""
        if self.settings.value("radio_song_pictures", "true") != "true":
            return
        from musicwell import radio as radio_mod

        def work(u=url):
            self._stream_img_ready.emit(u, radio_mod.fetch_song_picture(u) or b"")
        self.radio_page.pool.submit(work)

    def _on_stream_img(self, url: str, data: bytes):
        from PySide6.QtGui import QImage
        cur = self.player.current
        if not data or not cur or not cur.get("stream") or cur.get("art_url") != url:
            return  # another song by now, or not an image
        img = QImage.fromData(data)
        if img.isNull():
            return
        self._current_art = img
        self.now.art.set_image(img, cur.get("title") or "")
        self.bar.set_track(cur, img)
        self.update_colours(img)
        if getattr(self, "_stream_no_artist_img", False) and cur.get("artist"):
            self.now.header.set_artist(cur["artist"], img)

    def _remote_art(self, t: dict):
        """The item's image from archive.org (fetched once; a placeholder meanwhile)."""
        url = t["item"].get("image", "")
        cache = self.__dict__.setdefault("_remote_imgs", {})
        if url in cache:
            return cache[url]
        if url and url not in self.__dict__.setdefault("_remote_wanted", set()):
            self._remote_wanted.add(url)
            from musicwell import radio as radio_mod

            def work(u=url):
                data = radio_mod.fetch_logo(u)
                self._remote_img_ready.emit(u, data or b"")
            self.radio_page.pool.submit(work)
        from musicwell.artwork import placeholder
        return placeholder(512, t["album"] or t["title"], self.theme.accent, 0)

    def _on_remote_img(self, url: str, data: bytes):
        from PySide6.QtGui import QImage
        img = QImage.fromData(data) if data else QImage()
        if img.isNull():
            return
        self._remote_imgs[url] = img
        cur = self.player.current
        if cur and cur.get("remote") and cur["item"].get("image") == url:
            self._current_art = img
            self.now.art.set_image(img, cur["album"])
            self.bar.set_track(cur, img)
            self.update_colours(img)
        self.similar_page.refresh_archive()
        self.online_page.free.refresh()

    def _on_remote_changed(self, t: dict):
        art = self._remote_art(t)
        self._current_art = art
        artist = t["artist"]
        artist_img = self.images.artist_image(artist, "") if artist else None
        self.update_colours(art)
        self.now.set_track(t, art, artist_img)
        self.bar.set_track(t, art)
        self._refresh_upnext()
        self._request_lyrics(t)
        self.setWindowTitle(f"{t['title']} — {artist or t['album']} · {APP_NAME}")

    def like_current(self):
        """Like / unlike the playing song. Your own songs go to Favourites (5 stars), radio songs to Liked."""
        t = self.player.current
        if not t:
            return
        if t.get("remote"):
            artist, title = t.get("artist") or "", t.get("title") or ""
            from musicwell.freemusic import where
            src = {"name": f"{where(t.get('item') or {})} (online)", "uuid": ""}
            if self.stations.is_liked(artist, title):
                self.stations.unlike(self.stations.liked_key(artist, title))
                self._flash(f"Took “{title}” out of ♥ Liked")
            else:
                self.stations.like(artist, title, src)
                self._flash(f"♥ Kept “{title}”{' by ' + artist if artist else ''} — Radio → ♥ Liked")
            self._update_like_state()
            if self.radio_page.view == "liked":
                self.radio_page.fill_liked()
            return
        if not t.get("stream"):
            tid = t["id"]
            if (t.get("rating") or 0) >= 4:
                back = self._before_like.pop(tid, 0) if hasattr(self, "_before_like") else 0
                self.library.set_rating([tid], back if back < 4 else 0)
                self._flash(f"Took “{t['title']}” out of your Favourites")
            else:
                self.__dict__.setdefault("_before_like", {})[tid] = t.get("rating") or 0
                self.library.set_rating([tid], 5)
                self._flash(f"♥ “{t['title']}” is in your Favourites (5 stars)"
                            + ("" if any(w.spec.get("name") == "Favourites" for w in self.custom_pages)
                               else " — add the Favourites tab with + at the top"))
            self._update_like_state()
            return
        artist, title = t.get("artist") or "", t.get("title") or ""
        if not artist or not t.get("now_playing"):
            self._flash("The station hasn't said which song is playing")
            return
        if self.stations.is_liked(artist, title):
            self.stations.unlike(self.stations.liked_key(artist, title))
            self._flash(f"Took “{title}” out of ♥ Liked")
        else:
            self.stations.like(artist, title, t["station"])
            self._flash(f"♥ Kept “{title}” by {artist} — Radio → ♥ Liked")
        self._update_like_state()
        if self.radio_page.view == "liked":
            self.radio_page.fill_liked()

    def _radio_copy(self):
        """Library id of the song on the radio now, if you have it."""
        cur = self.player.current
        if not cur or not cur.get("stream") or not cur.get("now_playing"):
            return None
        from musicwell import radio as R
        artist, title = R.song_parts(cur["station"], cur["now_playing"])
        if not (artist and title):
            return None
        return self.radio_page.match_in_library({"artist": artist, "title": title})

    def _note_radio_song(self, st: dict, text: str):
        """Remember when the radio song began, to resume your copy from about there."""
        from musicwell import radio as R
        sid = R.station_id(st)
        last = getattr(self, "_radio_song", None)  # (station id, text, start time or None)
        if last is None or last[0] != sid:
            self._radio_song = (sid, text, None)  # tuned in mid-song: start unknown
        elif last[1] != text:
            self._radio_song = (sid, text, time_now() if text else None)
        tid = self._radio_copy()
        self._show_radio_copy(tid)
        if tid and (last is None or last[1] != text) and self.settings.value("radio_copy_note", False, bool):
            self._copy_note(st, tid)

    def _show_radio_copy(self, tid):
        t = self.library.tracks.get(tid) if tid else None
        tip = (f"“{t.get('title') or ''}” by {t.get('artist') or ''} is in your library"
               + (f" ({t.get('album')})" if t.get("album") else "")) if t else ""
        self.bar.set_copy(bool(t), tip)
        self.radio_page.set_copy(tid if t else None, tip)

    def _copy_note(self, st: dict, tid: int):
        """Tell the user when the station plays a song they have (Settings -> Radio)."""
        t = self.library.tracks[tid]
        msg = f"🎵  “{t.get('title') or ''}” is in your library — click to play your copy"
        self._flash(msg, 30_000)
        self._alert_station = None
        self._copy_msg, self._copy_msg_tid = msg, tid
        self.status.setCursor(Qt.PointingHandCursor)
        if not self.isActiveWindow():
            self.desktop.notify_with(f"{t.get('artist') or ''} – {t.get('title') or ''}",
                                     f"On {st['name']} now — it's in your library",
                                     [("default", "Play your copy"), ("copy", "▶ Play your copy")],
                                     {"copy_tid": tid})

    def play_radio_copy(self, tid=None, where: str = ""):
        """Play your copy of the radio song: from the start, from about where the radio is, or queued."""
        tid = tid or self._radio_copy()
        if not tid or tid not in self.library.tracks:
            return
        t = self.library.tracks[tid]
        if where == "queue":
            self.player.enqueue([tid])
            self._flash(f"Added your copy of “{t.get('title') or ''}” to the queue", 3000)
            return
        where = where or self.settings.value("radio_copy_from", "start")
        offset = 0
        song = getattr(self, "_radio_song", None)
        cur = self.player.current
        if where == "same" and song and song[2] is not None and cur and cur.get("stream") \
                and self._radio_copy() == tid:
            offset = int((time_now() - song[2]) * 1000)
            length = int((t.get("length") or 0) * 1000)
            if length and offset > length - 5000:
                offset = 0  # nearly over: from the start
        self._play_library_track(tid)
        # the first try straight from a stream can fail, so retry once
        self.player.retry_once = (tid, offset if offset > 1500 else 0)
        QTimer.singleShot(5000, lambda: setattr(self.player, "retry_once", None))
        if offset > 1500:
            QTimer.singleShot(350, lambda: self.player.current and self.player.current.get("id") == tid
                              and self.player.seek(offset))
            self._flash(f"Playing your copy of “{t.get('title') or ''}” from {fmt_time(offset / 1000)}", 3500)
        else:
            if where == "same":
                self._flash(f"Playing your copy of “{t.get('title') or ''}” from the start "
                            "(not sure where the radio was in it)", 4000)
            else:
                self._flash(f"Playing your copy of “{t.get('title') or ''}”", 3000)

    def set_like_icon(self, on: bool):
        """Show or hide the ♥ after the title in the play bar."""
        b = self.bar
        if not on:
            b.remove_item("like")
            return
        if "like" in b.all_placed():
            return
        zone = next((z for z, keys in b.zones.items() if "info" in keys), "left")
        keys = b.zones[zone]
        b.place_item("like", zone, keys.index("info") + 1 if "info" in keys else len(keys))

    def _update_like_state(self):
        """Update the ♥ in the play bar and panels."""
        real = self.bar.set_like

        def both(state, where="radio"):
            real(state, where)
            self.now.set_like(state, where)
        self.bar.set_like = both
        try:
            self._update_like_state_inner()
        finally:
            self.bar.set_like = real

    def _update_like_state_inner(self):
        t = self.player.current
        if t and t.get("stream"):
            if t.get("artist") and t.get("now_playing"):
                self.bar.set_like(self.stations.is_liked(t["artist"], t["title"]), "radio")
            else:
                self.bar.set_like(None)
        elif t and t.get("remote"):
            self.bar.set_like(self.stations.is_liked(t.get("artist") or "", t.get("title") or ""), "online")
        elif t:
            self.bar.set_like((t.get("rating") or 0) >= 4, "library")
        else:
            self.bar.set_like(None)
        self.radio_page.update_like_button()

    def _play_library_track(self, tid: int):
        ids = self.table.model_.ids()
        if tid in ids:
            self.player.play_list(ids, ids.index(tid))
        else:
            self.player.play_list([tid], 0)

    def _find_in_library(self, artist: str, title: str):
        self.search.setText(f"{artist} {title}".strip())
        self._go_page(0)
        self._refilter()

    def _station_search(self, text: str):
        """Discover -> Search online -> Radio stations: a background job returning stations."""
        from musicwell import similar as SIM
        from musicwell import freesearch as FS
        words, _field = FS.parse(text, "any")
        words = words.strip()
        tracks = list(self.library.tracks.values())
        directory, online = self.finder.directory, self.finder.online
        limit = int(getattr(self.finder, "station_limit", 40) or 40)

        def job():
            res = SIM.Result()
            SIM.add_stations(res, directory, None, words, tracks, online, limit)
            if not res.stations and words:
                res.stations = SIM.similar_stations(directory, [(words, 1.0)], "", limit)
                if res.stations:
                    res.station_basis, res.station_problem = [words.lower()], ""
            return res.stations, res.station_basis, res.station_problem
        return job

    def _search_free_music(self, text: str):
        """Search free music (Online Sources tab)."""
        self._go_page(7)
        self.online_page.search(text)

    def _online_mode(self) -> str:
        m = self.settings.value("lib_online_mode", "")
        return m if m in ("pause", "enter", "off") else ("pause" if self.settings.value("lib_online", True, bool)
                                                         else "off")

    def _search_typed(self, text: str):
        was = getattr(self, "_search_was", "")
        self._search_was = text
        if text and not was:
            # remember the position before searching
            self._place_before_search = (self._top_song_id() if self.pages.currentIndex() == 0
                                         and self.lib_stack.currentIndex() == 1 else None)
        elif was and not text:
            QTimer.singleShot(350, self._back_after_search)  # once the whole list is back
        if not text and self.pages.currentIndex() == 0 and self.lib_stack.currentIndex() == 1:
            if self._artist_home():
                self.open_artist_home()  # clear button / Esc: back to the artist
            elif self._albums_home():
                self.open_albums_page(in_library=True)  # or to the albums
        if self.settings.value("lib_search_mode", "type") != "enter" or not text:
            self._search_timer.start()  # search as you type
        mode = self._online_mode()
        if mode == "pause" or not text:
            try:
                self._online_timer.setInterval(int(float(self.settings.value("lib_online_delay", 1))) * 1000 + 100)
            except (TypeError, ValueError):
                self._online_timer.setInterval(1100)
            self._online_timer.start()
        elif mode == "off":
            self.online_strip.search("")

    def _search_entered(self):
        self._search_timer.stop()
        self._refilter()
        if self._online_mode() != "off":
            self._online_timer.stop()
            self._search_online_too()

    def apply_search_settings(self):
        """Apply Settings -> Search."""
        s = self.settings
        from musicwell import query as Q
        try:
            Q.set_plain_fields(json.loads(s.value("search_plain_fields", "null") or "null"))
        except (TypeError, ValueError):
            Q.set_plain_fields(None)
        for p in (self.online_page.free, self.similar_page.free, self.online_strip.panel):
            p.sources = self._free_sources()
            p.load_prefs()
        strip = self.online_strip
        want_open = s.value("lib_online_open", False, bool)
        if strip.is_open != want_open:
            strip.set_open(want_open)
        if self._online_mode() == "off":
            strip.search("")
        self._refilter()

    def _search_online_too(self, paused: bool = False):
        """Run the main search against the online sources too."""
        strip = self.online_strip
        mode = self._online_mode()
        if mode == "off" or not self.search.text().strip():
            strip.search("")
            return
        if paused and mode != "pause":
            return
        strip.search(self.search.text())
        self._size_online_strip()

    def _size_online_strip(self, *_):
        strip, sp = self.online_strip, self.lib_split
        if not strip.isVisible():
            return
        sizes = sp.sizes()
        want = 300 if strip.is_open else strip.head.sizeHint().height() + 8
        if abs(sizes[2] - want) > 4 and (not strip.is_open or sizes[2] < 120):
            total = sum(sizes)
            sp.setSizes([sizes[0], max(120, total - sizes[0] - want), want])

    def _library_artist_names(self) -> set:
        """Library artists (normalised), so typing one searches that artist online."""
        lib = self.library
        cache = getattr(self, "_artist_names_cache", None)
        if cache is None or cache[0] != len(lib.tracks):
            from musicwell.freesearch import norm
            names = set()
            for t in lib.tracks.values():
                for x in (t.get("artist"), t.get("albumartist"), t.get("artist_key")):
                    if x:
                        names.add(norm(x))
                        p = norm(primary_artist(x))
                        if p:
                            names.add(p)
            cache = self._artist_names_cache = (len(lib.tracks), names)
        return cache[1]

    def _free_sources(self) -> dict:
        """Which online sources to search."""
        s = self.settings
        return {"ia": s.value("similar_archive", True, bool), "ov": s.value("similar_openverse", True, bool),
                "au": s.value("similar_audius", True, bool), "my": s.value("search_my", True, bool)}

    def songs_by_online(self, artist: str):
        """Songs by this artist from the online sources."""
        if not artist:
            return
        self._go_page(7)
        self.online_page.show_view(0)
        self.online_page.free.search_artist(artist)

    def _on_station_picture(self, uuid: str):
        """Your own station image changed: show it now if it's playing."""
        cur = self.player.current
        if cur and cur.get("stream") and cur["station"].get("uuid") == uuid:
            self._on_station_logo(cur["station"].get("favicon") or "", force=True)

    def _on_station_logo(self, url: str, force: bool = False):
        cur = self.player.current
        if cur and cur.get("stream") and (force or cur["station"].get("favicon") == url):
            art = self._station_art(cur["station"])
            self._current_art = art
            self.now.art.set_image(art, cur["station"]["name"])
            self.bar.set_track(cur, art)
            self.update_colours(art)

    def find_similar(self, track: dict | None = None, artist: str = ""):
        """Open Discover -> Like this for a song or artist."""
        if track is not None and track.get("stream"):
            st = track["station"]
            label = (f"“{track['title']}” on {st['name']}" if track.get("artist") else st["name"])
        else:
            label = artist or (f"“{track['title']}”" if track else "")
        self._similar_auto = False
        self.similar_page.seed_artists = [primary_artist(artist or (track or {}).get("artist_key")
                                                         or (track or {}).get("artist") or "")]
        self._similar_req = self.finder.find(track, artist)
        self.similar_page.show_looking(label)
        self._go_page(6)

    def _find_like_station(self, st: dict):
        """Stations like this one, and songs in its genres."""
        from musicwell import radio as radio_mod
        self.find_similar(radio_mod.stream_track(st))

    def _clear_stats(self):
        from musicwell.stats import ClearStatsDialog
        if ClearStatsDialog(self.library, self, getattr(self, "radio_log", None)).exec():
            self.stats_page.mark_dirty()
            for tbl in (self.table, self.queue_table, self.pl_table, self.similar_page.table, *self._custom_tables()):
                tbl.model_.layoutChanged.emit()
            self._refresh_custom_tabs("search")
            if self.player.current and self.player.current["id"] > 0:
                self.now.update_stats(self.player.current)
            self._flash("Stats cleared")

    def _similar_cleared(self):
        self._similar_req = -1

    def _find_similar_playing(self):
        if self.player.current:
            self.find_similar(self.player.current)

    def _on_similar(self, n: int, res):
        if n != getattr(self, "_similar_req", -1):
            return
        if getattr(self, "_similar_auto", False):
            self._similar_auto = False
            recent = set(self.player.history[-60:])
            ids = [i for i in res.tracks if i not in recent]
            if ids:
                self.player.play_list(ids, 0)
                self._flash(f"Keeping the music going: songs like {res.seed_label}")
            return
        self.similar_page.set_result(res)
        cur = self.player.current
        self.similar_page.set_current(cur["id"] if cur else None)

    def _keep_playing_similar(self, last: dict):
        """The list ended: continue with similar songs if enabled."""
        if not self.settings.value("similar_continue", False, bool):
            return
        self._similar_auto = True
        self._similar_req = self.finder.find(last, stations=False)

    def _apply_playing_style(self):
        """Settings -> Playback -> Jump to the playing song."""
        from musicwell.models import SongModel
        bold = self.settings.value("follow_playing", "select") == "scroll"
        if bold != SongModel.bold_row:
            SongModel.bold_row = bold
            for tbl in (self.table, self.queue_table, self.pl_table, *self._custom_tables()):
                tbl.viewport().update()

    def _play_pause_jump(self):
        """Play / pause; on play the song lists jump to the playing song."""
        starting = not self.player.is_playing()  # it reports playing a moment later
        self.player.play_pause()
        cur = self.player.current
        if starting and cur and not cur.get("stream") and cur.get("id") is not None:
            select = self.settings.value("follow_playing", "select") == "select"
            tables = [self.table, self.queue_table, self.pl_table, *self._custom_tables()]
            tables += [p.songs.table for p in self.panels if "songs" in p.order]
            for tbl in tables:
                tbl.follow_id(cur["id"], select)

    def _follow_playing(self, tid: int):
        """Scroll lists to the song that just started (unless you're using them)."""
        select = self.settings.value("follow_playing", "select") == "select"
        for tbl in (self.table, self.queue_table, self.pl_table, *self._custom_tables()):
            if tbl.recently_used():
                continue  # you're using that list: leave it
            tbl.follow_id(tid, select)

    def _on_artist_image(self, name, img):
        cur = self.player.current
        getattr(self, "_reloading", set()).discard(("artist", name))
        if cur and primary_artist(cur["artist_key"] or cur["artist"]) == name:
            self.now.header.set_artist(cur["artist_key"] or cur["artist"], img)

    def _on_album_cover(self, key, img):
        cur = self.player.current
        getattr(self, "_reloading", set()).discard(("album", key))
        if cur and album_key(cur) == key:
            self._current_art = img
            self.now.art.set_image(img, cur["album"] or cur["title"])
            self.bar.set_track(cur, img)
            self.update_colours(img)

    def _image_actions(self, kind: str) -> list:
        """Right-click items for the panel's cover / artist photo."""
        t = self.player.current
        if t is None:
            return []
        if t.get("remote") and kind == "album":
            it = t["item"]
            from musicwell.freemusic import site
            acts = [(f"Open on {site(it)} (licence, credit, download)", lambda: self._open_url(it["page"]))]
            if it.get("attribution"):
                acts.append(("Copy the credit line", lambda: QApplication.clipboard().setText(it["attribution"])))
            acts.append(("Add this song to a playlist…", lambda: self._ask_playlist_for([t])))
            return acts + [
                    ("Find similar\tCtrl+Shift+F", lambda: self.find_similar(t)),
                    ("Show Discover → Search online", lambda: self.open_discover(1))]
        if t.get("stream") and kind == "album":
            st = t["station"]
            fav = self.stations.is_favourite(st)
            acts = [("Remove from favourite stations" if fav else "Add to favourite stations",
                     lambda: (self.stations.set_favourite(st, not fav), self.radio_page.refresh())),
                    ("Show the Radio page", lambda: self._go_page(5))]
            if st.get("homepage"):
                acts.append(("Open the station's website", lambda: self._open_url(st["homepage"])))
            acts.append(("Find similar (stations and songs)\tCtrl+Shift+F", lambda: self.find_similar(t)))
            acts.append(("Stations like this one", lambda: self._find_like_station(st)))
            if t.get("artist") and t.get("now_playing"):
                acts.append((f"Search Discover for “{t['artist']}”", lambda: self.songs_by_online(t["artist"])))
            if t.get("artist") and t.get("now_playing"):
                liked = self.stations.is_liked(t["artist"], t["title"])
                acts.insert(0, ("♥ Liked — take it out" if liked else "♥ Like this song\tCtrl+Shift+L",
                                self.like_current))
            if t.get("now_playing") and t.get("artist"):
                from musicwell import radio as radio_mod
                swapped = radio_mod.title_order(st) == "title-artist"
                acts.append(("Artist and title the usual way round (Artist – Title)" if swapped else
                             "This station sends Title – Artist (swap them)",
                             lambda: (self.stations.set_title_order(st, "artist-title" if swapped else "title-artist"),
                                      self._resplit_current(st))))
            dim = getattr(self, "ad_dimmer", None)
            if dim is not None and self.settings.value("radio_dim_ads", False, bool):
                if dim.dimmed:
                    acts.append(("Not an advert — turn it back up", dim.mark_not_advert))
                elif dim.text:
                    short = dim.text if len(dim.text) <= 40 else dim.text[:38] + "…"
                    acts.append((f"Turn “{short}” down on this station (an advert or jingle)", dim.mark_advert))
            acts += self.radio_page.picture_actions(st)
            acts.append(("Stop radio", self.player.stop_radio))
            return acts
        if kind == "album":
            key = album_key(t)
            acts = [("Search for album image…", lambda: self._pick_image("album")),
                    ("Use my own image…", lambda: self._pick_image("album", from_file=True))]
            if self.images.has_override("album", key):
                acts.append(("Back to the automatic image", lambda: self._reset_image("album")))
            acts.append(("Reload cover and artist photo\t" + self.shortcut_text("reload_images"), self._reload_images))
        else:
            name = t["artist_key"] or t["artist"]
            key = primary_artist(name)
            fit = self.now.header.fit
            acts = [("Show the whole photo" if fit == "fill" else "Fill the space (crop the photo)",
                     lambda: self._set_artist_fit("fill" if fit == "whole" else "whole")),
                    ("Search for artist image…", lambda: self._pick_image("artist")),
                    ("Use my own image…", lambda: self._pick_image("artist", from_file=True))]
            if self.images.has_override("artist", key):
                acts.append(("Back to the automatic image", lambda: self._reset_image("artist")))
            info = self.images.artist_credit(name)
            if info and info.get("license"):
                label = f"Photo by {info.get('credit') or 'Wikimedia Commons'} ({info['license']})"
                if len(label) > 70:
                    label = label[:69] + "…"
                acts.append((label + "…", lambda u=info.get("page", ""): u and self._open_url(u)))
            acts.append(("Reload cover and artist photo\t" + self.shortcut_text("reload_images"), self._reload_images))
            if name:
                acts.append((f"Search Discover for music like “{primary_artist(name)}”", lambda: self.find_similar(artist=primary_artist(name))))
                acts.append((f"Search Discover for “{primary_artist(name)}”",
                             lambda: self.songs_by_online(primary_artist(name))))
        return acts

    @staticmethod
    def _open_url(url: str):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl(url))

    def _set_artist_fit(self, fit: str):
        self.settings.setValue("artist_photo_fit", fit)
        for p in self.panels:
            p.header.set_fit(fit)
            p.header._fit_height()

    def _image_key(self, kind: str):
        t = self.player.current
        if kind == "album":
            return album_key(t)
        return primary_artist(t["artist_key"] or t["artist"])

    # images for any artist or album
    def _picture_actions(self, kind: str, name: str, track) -> list:
        """Search (free sources or the web), use a file, or go back to automatic."""
        if kind == "album" and not track:
            return []
        key = album_key(track) if kind == "album" else primary_artist(name)
        acts = [(f"Search for {kind} image…", lambda: self._pick_image_for(kind, name, track)),
                ("Use my own image…", lambda: self._pick_image_for(kind, name, track, True))]
        if self.images.has_override(kind, key):
            acts.append(("Back to the automatic image", lambda: self._picture_changed(kind, name, track, None)))
        return acts

    # images picked from the web
    def take_image_for(self, kind: str, name: str, track, found: dict):
        """An image dropped or pasted for an artist or album becomes theirs."""
        from musicwell import webimage as WI
        if kind == "album" and not track:
            return
        key = album_key(track) if kind == "album" else primary_artist(name)
        what = "cover" if kind == "album" else "photo"
        self._flash(f"Getting the {what}…", 15000)
        t = WI.Taker(found, self)

        def done(data, info, note):
            self.images.set_override(kind, key, data, info)
            self._picture_changed(kind, name, track, "shown")
            self._flash(f"New {what} for {name if kind == 'artist' else (track.get('album') or 'the album')}"
                        + (f" — {note}" if note else ""), 5000)

        t.done.connect(done)
        t.failed.connect(lambda why: self._flash(f"Couldn't use that picture: {why}", 9000))
        t.start()

    def _pick_image_for(self, kind: str, name: str, track, from_file: bool = False):
        from musicwell.artpicker import ImagePicker
        if kind == "album":
            artist, album, key = (track.get("albumartist") or track.get("artist") or ""), track.get("album") or "", \
                album_key(track)
        else:
            artist, album, key = name, "", primary_artist(name)
        dlg = ImagePicker(kind, artist, album, self.images, key, self)
        if from_file:
            dlg.show()
            dlg._from_file()
            if dlg.result() != QDialog.Accepted:
                dlg.reject()
        else:
            dlg.exec()
        if dlg.result() == QDialog.Accepted:
            self._picture_changed(kind, name, track, "shown")

    def _picture_changed(self, kind: str, name: str, track, what):
        """After a pick: everything showing it reloads."""
        key = album_key(track) if kind == "album" else primary_artist(name)
        if what is None:
            self.images.set_override(kind, key, None)
            self._flash(f"Back to the automatic {'cover' if kind == 'album' else 'photo'} — looking for it…", 4000)
        elif what == "again":
            self.images.forget(kind, key, keep_override=True)
            self._flash("Looking for an image online…", 3000)
        for p in self.panels:
            if kind == "artist":
                p.artists.image_ready(name)
            else:
                p.artists.cover_ready(key)
                p.albums.cover_ready(key)
        if kind == "artist":
            self.artist_page.photo_ready(name)
        cur = self.player.current
        if cur and ((kind == "artist" and primary_artist(cur.get("artist_key") or cur.get("artist") or "") == key)
                    or (kind == "album" and album_key(cur) == key)):
            self._refresh_images()

    def _pick_image(self, kind: str, from_file: bool = False):
        from musicwell.artpicker import ImagePicker
        t = self.player.current
        if t is None:
            return
        artist = (t["albumartist"] or t["artist"]) if kind == "album" else (t["artist_key"] or t["artist"])
        dlg = ImagePicker(kind, artist, t["album"], self.images, self._image_key(kind), self)
        if from_file:
            dlg.show()
            dlg._from_file()
            if dlg.result() != QDialog.Accepted:
                dlg.reject()
        else:
            dlg.exec()
        self._refresh_images()

    def _reset_image(self, kind: str):
        self.images.set_override(kind, self._image_key(kind), None)
        self._refresh_images()

    def _reload_images(self):
        """Look up the playing song's cover and artist photo again."""
        t = self.player.current
        if t is None:
            self._flash("Play a song to reload its images", 3000)
            return
        album, artist = album_key(t), primary_artist(t["artist_key"] or t["artist"])
        self.images.forget("album", album, keep_override=True)
        self.images.forget("artist", artist, keep_override=True)
        self._reloading = {("album", album), ("artist", artist)}
        self._refresh_images()
        waiting = [k for k in self._reloading if k in self.images._pending]
        self._reloading = set(waiting)
        self._flash("Looking for images…" if waiting else "Images reloaded", 4000)

    def _on_image_missed(self, kind: str, key: str):
        pending = getattr(self, "_reloading", set())
        if (kind, key) not in pending:
            return
        pending.discard((kind, key))
        what = "album cover" if kind == "album" else "artist photo"
        from musicwell.paths import cache_dir
        self._flash(f"No {what} found online — right-click it → Find {what}… to search yourself "
                    f"(details in {cache_dir() / 'images.log'})", 9000)

    def _after_cache_cleared(self):
        """Reload images after the cache was cleared."""
        for p in self.panels:
            p.artists.reload_pictures()
            p.albums.reload_pictures()
        self._current_art = None
        self.bar._track = None  # so the seek bar asks for its waveform again
        self.lyrics._mem.pop(self.player.current["id"], None) if self.player.current else None
        self._refresh_images()

    def _refresh_images(self):
        if self.player.current:
            self._on_track_changed(self.player.current)

    def _on_queue_changed(self, *_):
        """Refresh the Queue page."""
        pl = self.player
        lib = self.library
        pl.qlist = [e for e in pl.qlist if lib.get(e["id"])]
        m = self.queue_table.model_
        m.dimmed = {r for r, e in enumerate(pl.qlist) if e["state"] == "done"}
        m.current_row = next((r for r, e in enumerate(pl.qlist) if e["state"] == "now"), -1)
        m.set_rows([lib.get(e["id"]) for e in pl.qlist], keep_sort=False)
        m.set_current(pl.current["id"] if pl.current else None)
        n = sum(1 for e in pl.qlist if e["state"] == "wait")
        k = len(m.dimmed)
        now_t = m.current_row >= 0
        parts = [f"{n} to come" if n else ("nothing else to come" if (k or now_t) else "Empty")]
        if now_t:
            parts.insert(0, "1 playing")
        if k:
            parts.append(f"{k} played")
        self.queue_count.setText("  ·  ".join(parts))
        self.queue_clear_played.setVisible(bool(k))
        self._mark_from_queue()
        self._apply_tab_names()  # queue count on its tab
        self._refresh_upnext()

    def _refresh_panel_songs_soon(self, *_):
        if not hasattr(self, "_panel_songs_timer"):
            self._panel_songs_timer = QTimer(self, singleShot=True, interval=120)
            self._panel_songs_timer.timeout.connect(self._refresh_panel_songs)
        self._panel_songs_timer.start()

    def _panel_song_ids(self, source: str) -> list[int]:
        pl = self.player
        if source == "library":
            return self.table.model_.ids()
        if source == "picked" and self._follow_library():
            return self.table.model_.ids()
        pid = self._panel_playlist(source)
        if pid is not None or source == "picked":
            return self.library.playlist_track_ids(pid) if pid is not None else []
        if source == "queue":
            return list(pl.queue)
        if pl.station is not None or pl.remote is not None or not pl.order:
            return []
        return [pl.playlist[k] for k in pl.order]

    def _playlist_followers(self) -> list[str]:
        """Panels whose Song list follows the Playlists tab."""
        names = {id(p): n for n, p in self.side_panels().items()}
        out = []
        for p in self.panels:
            if p.isHidden() or "songs" not in p.order or p.blocks["songs"].hidden or p.songs.source != "picked":
                continue
            out.append("Top Panel" if p is self.now3 else f"{names.get(id(p), 'left').title()} Panel")
        return out

    def _sync_playlists_page(self):
        """Playlists tab: its songs show in a panel instead when one follows it."""
        where = self._playlist_followers()
        self.pl_table.setVisible(not where)
        self.pl_elsewhere.setVisible(bool(where))
        if where:
            self.pl_elsewhere.setText(
                f"This playlist's songs are in the {' and the '.join(where)}'s song list. Pick a playlist on the "
                "left to show it there. (To have them here again, set that song list to something else — "
                "click its box, or right-click its column headings → This song list.)")

    def _refresh_panel_songs(self):
        self._sync_playlists_page()
        self._mark_playlist_tabs()
        cur = self.player.current["id"] if self.player.current and not self.player.current.get("stream") else None
        lib = self.library.tracks
        cache = {}
        for p in self.panels:
            if "songs" not in p.order or p.blocks["songs"].hidden:
                continue
            src = p.songs.source
            if src not in cache:
                cache[src] = [lib[i] for i in self._panel_song_ids(src) if i in lib]
            p.songs.set_tracks(cache[src], cur)

    def _follow_library(self) -> bool:
        """Song lists set to Follow the tabs show the library."""
        return self.settings.value("panel_follow", "") == "library"

    def _library_picked(self):
        """Library tab clicked: lists that follow the tabs show the library."""
        self.settings.setValue("panel_follow", "library")
        self._refresh_panel_songs_soon()

    def _playlist_picked(self, pid):
        """A playlist was picked: lists that follow the tabs show it."""
        if pid is None:
            return
        self._picked_pid = pid
        self.settings.setValue("panel_follow", str(pid))
        if self._current_playlist() != pid:  # keep the Playlists tab in sync
            for r in range(self.pl_list.count()):
                if self.pl_list.item(r).data(Qt.UserRole) == pid:
                    self.pl_list.setCurrentRow(r)
                    break
        self._refresh_panel_songs_soon()

    def _mark_playlist_tabs(self):
        """Mark the playlist tab shown in a panel (accent colour)."""
        on = self._playlist_followers()
        lib = bool(on) and self._follow_library()
        pid = self._panel_playlist("picked") if on and not lib else None
        b0 = self.nav_buttons[0] if self.nav_buttons else None
        if b0 is not None and bool(b0.property("inPanel")) != lib:
            b0.setProperty("inPanel", lib)
            b0.style().unpolish(b0)
            b0.style().polish(b0)
        for i, spec in enumerate(self.custom_specs):
            b = self.nav_buttons[self.N_BUILTIN + i] if self.N_BUILTIN + i < len(self.nav_buttons) else None
            if b is None:
                continue
            want = bool(on) and spec.get("kind") == "playlist" and spec.get("pid") == pid
            if bool(b.property("inPanel")) != want:
                b.setProperty("inPanel", want)
                b.style().unpolish(b)
                b.style().polish(b)
                b.setToolTip(f"Its songs are in the {' and the '.join(on)}" if want else "")

    def _panel_playlist(self, source: str):
        """The playlist a Song list shows."""
        if source == "picked":
            if self._follow_library():
                return None
            pid = getattr(self, "_picked_pid", None)
            if pid is None and str(self.settings.value("panel_follow", "")).isdigit():
                pid = int(self.settings.value("panel_follow"))
            if pid is not None and any(p == pid for p, _ in self.library.playlists()):
                return pid
            return self._current_playlist()
        if isinstance(source, str) and source.startswith("playlist:") and source[9:].isdigit():
            return int(source[9:])
        return None

    def _panel_playlists_changed(self):
        for p in self.panels:
            p.songs.refresh_choices()
        self._refresh_panel_songs_soon()

    def _panel_song_menu(self, sl, ids, pos):
        pid = self._panel_playlist(sl.source)
        if pid is not None:
            self._track_menu(ids, pos, "playlist", sl.table, pid=pid)
        else:
            self._track_menu(ids, pos, "library", sl.table)

    def _panel_song_delete(self, sl, rows):
        """Delete in a panel's Song list removes from its playlist."""
        pid = self._panel_playlist(sl.source)
        if pid is not None:
            self._remove_from_playlist(rows, pid=pid)

    def _panel_song_play(self, source: str, tid: int):
        """Double-click in a panel's Song list."""
        pl = self.player
        if source == "queue":
            if tid in pl.queue:
                pl.jump_to_queue(pl.queue.index(tid))
            return
        if source == "playing" and pl.station is None and pl.remote is None and pl.order:
            for k, i in enumerate(pl.order):
                if pl.playlist[i] == tid:
                    pl.pos = k
                    pl._play_id(tid)
                    return
        ids = self._panel_song_ids(source) if source != "playing" else [tid]
        pl.play_list(ids, ids.index(tid) if tid in ids else 0)

    def _refresh_upnext(self):
        pl = self.player
        if pl.remote is not None:
            queued = [t for t in (self.library.get(i) for i in pl.queue_next()[:8]) if t]
            tracks = queued + pl.remote[pl.remote_pos + 1:pl.remote_pos + 9 - len(queued)]
            self.now.set_upnext(tracks, len(queued))
            return
        ids = pl.upcoming(8)
        tracks = [t for t in (self.library.get(i) for i in ids) if t]
        self.now.set_upnext(tracks, min(len(pl.queue_next()), len(tracks)))

    def _on_upnext_activated(self, row: int):
        pl = self.player
        nq = len(pl.queue_next())
        if pl.remote is not None and row >= nq:
            pl.remote_pos = min(len(pl.remote) - 1, pl.remote_pos + 1 + row - nq)
            pl._play_remote()
            return
        if row < nq:
            self.player.jump_to_queue(row)
        else:
            for _ in range(row - nq + 1):
                if self.player.pos + 1 < len(self.player.order):
                    self.player.pos += 1
            if self.player.order:
                self.player._play_id(self.player.playlist[self.player.order[self.player.pos]])

    def _cast_menu(self):
        """The cast menu stays open and updates as speakers are found."""
        c = self.cast_ctl
        if c is None:
            return
        c.start_discovery()
        anchor = getattr(self.bar.cast_btn, "copy_pos", None)  # opened from a copy of the button in a panel
        m = QMenu(self)
        m.setToolTipsVisible(True)
        state = {"search": None, "sig": None}

        def fill():
            m.clear()
            if c.is_connected:
                head = m.addAction(f"Connected to {c.name}")
                head.setEnabled(False)
                m.addAction(f"Disconnect from {c.name}", lambda: self._disconnect_cast(play_here=False))
                m.addAction("Disconnect and keep playing here", lambda: self._disconnect_cast(play_here=True))
                m.addSeparator()
            head = m.addAction("Play on")
            head.setEnabled(False)
            here = m.addAction("This computer", lambda: self._disconnect_cast(play_here=True) if c.is_connected else None)
            here.setCheckable(True)
            here.setChecked(not c.is_connected)
            devices = c.device_list()
            icons = {"group": "Speaker group", "audio": "Speaker", "video": "TV / Chromecast",
                     "sonos": "Sonos", "sonosgroup": "Sonos group"}
            for uuid, name, kind in devices:
                a = m.addAction(f"{name}    ·  {icons[kind]}", lambda u=uuid, n=name: self._cast_to(u, n))
                a.setCheckable(True)
                a.setChecked(c.is_connected and c.name == name)
            searching = c.searching
            if c.finding_off:
                a = m.addAction("Finding speakers is switched off (Settings → Devices & desktop)")
                a.setEnabled(False)
            elif searching:
                a = m.addAction("Searching for speakers and TVs…" if not devices else "Searching for more…")
                a.setEnabled(False)
            elif not devices:
                a = m.addAction("No speakers or TVs found")
                a.setEnabled(False)
                a = m.addAction("Check they're switched on and on the same network as this computer")
                a.setEnabled(False)
            m.addSeparator()
            sa = m.addAction("Searching…" if searching else "Search again")
            sa.setEnabled(not searching and not c.finding_off)
            sa.setToolTip("Look for speakers and TVs on your network again (the menu stays open)")
            state["search"] = sa
            m.addAction("Casting settings…", lambda: self._open_settings("Devices & desktop"))
            state["sig"] = (tuple(devices), c.is_connected, c.name, searching, c.finding_off)
            if m.isVisible():
                m.adjustSize()
                # keep it anchored to the cast button as it grows
                pos = anchor or self.bar.cast_btn.mapToGlobal(self.bar.cast_btn.rect().topLeft())
                m.move(m.x(), pos.y() - m.sizeHint().height())

        def refresh():
            sig = (tuple(c.device_list()), c.is_connected, c.name, c.searching, c.finding_off)
            if sig != state["sig"]:
                fill()

        def search():
            c.restart_discovery()
            fill()

        class _Keep(QObject):  # Search again doesn't close the menu
            def eventFilter(self, o, e):
                if e.type() == QEvent.MouseButtonRelease and m.actionAt(e.position().toPoint()) is state["search"]:
                    if state["search"].isEnabled():
                        search()
                    return True
                if e.type() == QEvent.KeyPress and e.key() in (Qt.Key_Return, Qt.Key_Enter) \
                        and m.activeAction() is state["search"]:
                    if state["search"].isEnabled():
                        search()
                    return True
                return False
        keep = _Keep(m)
        m.installEventFilter(keep)
        c.devicesChanged.connect(refresh)
        tick = QTimer(m)  # the "searching" line ends by itself
        tick.timeout.connect(refresh)
        tick.start(500)
        fill()
        pos = anchor or self.bar.cast_btn.mapToGlobal(self.bar.cast_btn.rect().topLeft())
        try:
            m.exec(pos - QPoint(0, m.sizeHint().height()))
        finally:
            tick.stop()
            try:
                c.devicesChanged.disconnect(refresh)
            except (RuntimeError, TypeError):
                pass

    def _cast_to(self, uuid: str, name: str):
        c = self.cast_ctl
        self._cast_resume = (self.player.position(), self.player.is_playing())
        if c.is_connected:
            if c.name == name:
                return
            self.player.stop_casting(resume_here=False)
            c.disconnect_device("switching")
        self._flash(f"Connecting to {name}…", 10000)
        c.connect_to(uuid)

    def _disconnect_cast(self, play_here: bool = False):
        """Stop casting and return to this computer (paused unless play_here)."""
        c = self.cast_ctl
        if c is None or not c.is_connected:
            return
        if self.player.cast is not None:
            playing = self.player.is_playing() if play_here else False
            self.player.stop_casting(resume_here=True, keep_playing=playing)
        c.disconnect_device("")
        self._flash(f"Disconnected from {c.name}", 4000)

    def _show_problem(self, title: str, text: str):
        box = QMessageBox(QMessageBox.Warning, title, text, QMessageBox.Ok, self)
        box.setTextInteractionFlags(Qt.TextSelectableByMouse)  # so the command can be copied
        box.setAttribute(Qt.WA_DeleteOnClose)
        box.open()

    def _on_cast_connected(self, name: str):
        self._flash(f"Playing on {name}", 4000)
        pos, playing = getattr(self, "_cast_resume", (None, None))
        self._cast_resume = (None, None)
        self.player.start_casting(self.cast_ctl.active, pos, playing)
        self._on_cast_volume(self.cast_ctl.volume)
        self.bar.cast_on = True
        self.now.set_cast_name(name)
        self._connect_visualizer()  # fed by a silent copy that follows the speaker
        self._refresh_bar()

    def _on_cast_disconnected(self, reason: str):
        if reason == "switching":
            return
        if self.player.cast is not None:
            # chose "This computer": carry on here; lost connection: carry on paused
            if reason:
                self.player.cast.player_state = "PAUSED"
            self.player.stop_casting(resume_here=True)
        if reason:
            self._flash(reason, 7000)
        self.bar.volume.blockSignals(True)
        self.bar.volume.setValue(int(round(self.player.volume * 100)))
        self.bar.volume.blockSignals(False)
        self.bar.cast_on = False
        self.now.set_cast_name(None)
        self._connect_visualizer()
        self._refresh_bar()

    def _on_cast_volume(self, v: float):
        if self.player.cast is None:
            return
        self.bar.volume.blockSignals(True)
        self.bar.volume.setValue(int(round(v * 100)))
        self.bar.volume.blockSignals(False)
        self.player._volume = v
        self._refresh_bar()

    def _connect_visualizer(self):
        eng = self.player.engine
        for viz in (self.now.viz, self.now2.viz, self.now3.viz, self.now4.viz, self.bar.viz):
            if eng is not None:
                viz.set_source(eng.samples, eng.rate)
            else:
                viz.set_source(None, 48000)
            viz.set_playing(self.player.is_playing())

    def _cover_style_everywhere(self, style: str):
        """Every album cover (play bar and panels) uses the same style."""
        if getattr(self, "_syncing_cover", False):
            return
        self._syncing_cover = True
        try:
            if self.bar.options.get("cover_style") != style:
                self.bar.set_option("cover_style", style)
            for p in (self.now, self.now2, self.now3, self.now4):
                if p.art.style != style:
                    p.set_cover_style(style)
        finally:
            self._syncing_cover = False

    def _bar_viz_style(self, style: str):
        """Right-click on the play bar's visualizer."""
        if style == "rearrange":
            self.set_customizing(True)
        elif style == "off":
            self.bar.remove_item("viz")  # hide it here only
        else:
            self.settings.setValue("visualizer_style", style)
            if self.settings.value("visualizer", "bars") != "off":
                self.settings.setValue("visualizer", style)
            self._apply_visualizer()

    def _set_visualizer(self, style: str):
        if style == "rearrange":
            self.now.set_editing(True)
            return
        if style != "off":
            self.settings.setValue("visualizer_style", style)
        self.settings.setValue("visualizer", style)
        self._apply_visualizer()

    def _apply_visualizer(self):
        """bars / mirror / wave / off. Off is the same as hiding its panel item."""
        style = self.settings.value("visualizer", "bars")
        viz = self.now.viz
        in_panel2 = any(not p.isHidden() and "visualizer" in p.order for p in (self.now2, self.now3))
        setup = getattr(self, "_in_tab_setup", False)
        if style != "off" and "visualizer" not in self.now.order and not in_panel2 and not setup:
            at = self.now.order.index("artwork") + 1 if "artwork" in self.now.order else 0
            self.now.add_block("visualizer", at)  # chosen in Settings after being removed
        own = [self.now4] + ([self._layout_states["left_panel"], self.now3] if setup else [])
        for p_ in self.panels:  # Radio and Lyrics tabs' own panels
            if "visualizer" in p_.order and p_ not in own:  # keep theirs
                p_.set_block_hidden("visualizer", style == "off")
        if style != "off":
            for v in (viz, self.now2.viz, self.now3.viz, self.now4.viz):
                v.set_style(style)
                v.set_playing(self.player.is_playing())
        # same look in the play bar
        self.bar.viz.set_style(style if style != "off" else self.settings.value("visualizer_style", "bars"))
        if hasattr(self, "now4"):
            self._tab_setup_filled([])

    def _on_panel_block_visibility(self, key: str, visible: bool):
        if key == "songs":
            self._refresh_panel_songs_soon()
            return
        if key != "visualizer":
            return
        current = self.settings.value("visualizer", "bars")
        if visible:
            if current == "off":
                self.settings.setValue("visualizer", self.settings.value("visualizer_style", "bars"))
            self._apply_visualizer()
        elif not visible and current != "off":
            if not any("visualizer" in p.order and not p.blocks["visualizer"].hidden and not p.isHidden()
                       for p in self.panels):
                self.settings.setValue("visualizer", "off")  # no panel shows it now

    def _save_panel_layout(self):
        if self.now._restoring:
            return
        if not self._setup_panel_saved(self.now):
            self.settings.setValue("panel_layout", json.dumps(self.now.state()))

    def _save_panel2_layout(self):
        if self.now2._restoring:
            return
        if not self._setup_panel_saved(self.now2):
            self.settings.setValue("panel2_layout", json.dumps(self.now2.state()))

    def _save_panel3_layout(self):
        if self.now3._restoring:
            return
        if not self._setup_panel_saved(self.now3):
            self.settings.setValue("panel3_layout", json.dumps(self.now3.state()))

    @property
    def panels(self) -> list:
        """Every panel: the side ones, the top one, the Radio and Lyrics one and the play bar's hidden one."""
        return [p for p in (getattr(self, "now", None), getattr(self, "now2", None), getattr(self, "now3", None),
                            getattr(self, "now4", None), getattr(self, "now5", None)) if p]

    def _panel_actions(self, panel) -> list:
        """Extra items at the bottom of a panel's right-click menu."""
        if panel is getattr(self, "now4", None):
            return [("Hide this panel", self._toggle_tab_panel),
                    (f"Reset the {self.TAB_SETUP_NAMES.get(getattr(self, '_setup_key', None) or '', 'Radio')} tab's "
                     "panels", self._reset_tab_panel)]
        if panel is self.now3:
            return [("Hide the Top Panel\tCtrl+F9", lambda: self.set_panel3_visible(False))]
        side = "Left" if self.side_panels()["left"] is panel else "Right"
        return [(f"Hide the {side} Panel", (lambda: self.set_panel2_visible(False)) if panel is self.now2
                 else self._toggle_panel)]

    def set_panel2_visible(self, on: bool, from_menu: bool = False):
        was = self.now2.isVisible()
        # hidden from the panel button's menu
        self._panel2_menu_hidden = (not on) and from_menu
        self.now2.setVisible(on)
        self._layout_touched()
        QTimer.singleShot(0, self._record_tab_panels)
        QTimer.singleShot(0, self._panels_follow_customizing)
        if on and not was:
            # give it room the first time, or if it was squeezed shut
            sizes = self.body.sizes()
            i2, ip = self.body.indexOf(self.now2), self.body.indexOf(self.middle)
            want = int(self.settings.value("panel2_width", 300))
            if sizes[i2] < 120:
                take = min(want, max(0, sizes[ip] - 400))
                sizes[i2], sizes[ip] = take, sizes[ip] - take
                self.body.setSizes(sizes)

    def _place_bar(self, where: str):
        """Play bar at the bottom (default) or top of the window."""
        root = self.root_lay
        root.removeWidget(self.bar)
        if where == "top":
            root.insertWidget(root.indexOf(self.top_bar) + 1, self.bar)
        else:
            root.addWidget(self.bar)

    def _save_bar_layout(self):
        self.settings.setValue("bar_layout", json.dumps(self.bar.state()))
        self._refresh_bar()

    def _request_lyrics(self, t):
        self._lyrics_tid = t["id"] if t else None
        self.lyrics_page.set_heading(t)
        if t is None:
            for v in (self.lyrics_page.view,):
                v.set_lyrics(None, "Play a song to see its lyrics")
            self.now.set_lyrics(None)
            return
        self.lyrics_page.view.set_lyrics(None, "Looking for lyrics…")
        self.now.set_lyrics(None)
        self._update_lyrics_timing()
        self.lyrics.request(t)

    def _resplit_current(self, st: dict):
        """A station's artist/title order changed: re-read the playing song."""
        cur = self.player.current
        if not (cur and cur.get("stream") and cur.get("now_playing")) or cur["station"].get("uuid") != st.get("uuid"):
            return
        from musicwell import radio as radio_mod
        t = radio_mod.stream_track(cur["station"], cur["now_playing"])
        t["song_start"] = cur.get("song_start")
        self.player.current = t
        self.player.trackChanged.emit(t)
        self._flash(f"{st.get('name', 'This station')}: {t['title']} — by {t['artist']}", 4000)

    def _on_lyrics(self, tid: int, ly):
        if tid != getattr(self, "_lyrics_tid", None):
            return
        cur = self.player.current
        if ly is not None and cur and cur.get("stream") and ly.synced and cur.get("song_start") is None:
            # radio: tuned in part-way through the song
            self._flash("Tuned in part-way through the song — click the line being sung to sync the lyrics "
                        "(the next songs sync by themselves)", 7000)
        if ly is None:
            msg = "No lyrics found for this song"
            if not self.lyrics.online:
                msg += "\n\nLooking online is switched off (Settings → Online)"
            msg += "\n\nPut a .lrc file next to the song, or right-click to load one"
        else:
            msg = ""
        self.lyrics_page.view.set_lyrics(ly, msg)
        self.now.set_lyrics(ly, msg)
        self._update_lyrics_timing()
        self._lyrics_position(self.player.position())

    def _lyrics_offsets(self) -> dict:
        try:
            d = json.loads(self.settings.value("lyrics_offsets", "{}"))
            return d if isinstance(d, dict) else {}
        except (TypeError, ValueError):
            return {}

    def heard_position(self, ms: int) -> int:
        """The decoder runs ahead of the speakers by the queued audio (up to ~1.5 s); subtract it to get what's heard."""
        eng = self.player.engine
        if eng is None or self.player.cast is not None:
            return ms
        shown = max(0, ms - eng.latency_ms())
        hold = getattr(self, "_seek_hold", None)
        if hold is not None:
            # After a seek the bar holds where you put it until playback catches up.
            target, since = hold
            caught_up = target <= shown < target + 1500
            if caught_up or time.monotonic() - since > 4:
                self._seek_hold = None
            else:
                shown = target
        else:
            last = getattr(self, "_shown_pos", -1)
            if 0 <= shown < last and last - shown < 1000:
                shown = last
        self._shown_pos = shown
        return shown

    def _smoothing(self) -> bool:
        """The play bar runs on its own smooth clock (local songs, not radio or casting)."""
        pl = self.player
        return (self._smooth_timer.isActive() and pl.is_playing() and pl.engine is not None
                and pl.cast is None and pl.station is None and bool(pl.current))

    def _position_news(self, ms: int):
        if self._smoothing():
            return  # handled by _smooth_position
        self.bar.set_position(self.heard_position(ms), self.player.duration())

    def _smooth_on_off(self, playing: bool):
        self._smooth = None
        if playing:
            self._smooth_timer.start()
        else:
            self._smooth_timer.stop()
            self.bar.set_position(self.heard_position(self.player.position()), self.player.duration())

    def _smooth_position(self):
        """Every 40 ms: advance the bar steadily, gently corrected towards the measured position."""
        if not self._smoothing() or self.bar.seek.isSliderDown():
            return
        pl = self.player
        now = time.monotonic()
        measured = self.heard_position(pl.position())
        last = getattr(self, "_smooth", None)
        if last is None or getattr(self, "_seek_hold", None) is not None:
            shown = measured
        else:
            was, then = last
            guess = was + (now - then) * 1000.0
            off = measured - guess
            shown = measured if abs(off) > 400 else max(was, guess + off * 0.12)  # small corrections never step back
        self._smooth = (shown, now)
        self.bar.set_position(int(shown), pl.duration())
        # lyrics follow the same smooth position
        for v in (self.lyrics_page.view, self.now.lyrics_view, self.now2.lyrics_view, self.now3.lyrics_view,
                  self.now4.lyrics_view):
            v.latency_ms = 0
            v.set_position(int(shown), True)

    def _note_seek(self, ms: int):
        """A seek: the play bar holds there (see heard_position)."""
        self._seek_hold = (max(0, int(ms)), time.monotonic())
        self._smooth = None
        self._shown_pos = max(0, int(ms))

    def _update_lyrics_timing(self):
        cur = self.player.current
        offset = int(self._lyrics_offsets().get(cur["path"], 0)) if cur else 0
        eng = self.player.engine
        latency = eng.latency_ms() if (eng is not None and self.player.cast is None) else 0
        for v in (self.lyrics_page.view, self.now.lyrics_view, self.now2.lyrics_view, self.now3.lyrics_view, self.now4.lyrics_view):
            v.latency_ms = latency
            v.offset_ms = offset
        self.lyrics_page.set_offset(offset)

    def _set_lyrics_offset(self, ms: int):
        cur = self.player.current
        if not cur:
            return
        d = self._lyrics_offsets()
        if ms:
            d[cur["path"]] = ms
        else:
            d.pop(cur["path"], None)
        if len(d) > 2000:
            d = dict(list(d.items())[-2000:])
        self.settings.setValue("lyrics_offsets", json.dumps(d))
        self.now.lyrics_view.offset_ms = ms
        self.now2.lyrics_view.offset_ms = ms
        self.now4.lyrics_view.offset_ms = ms
        self.now3.lyrics_view.offset_ms = ms
        self.lyrics_page.set_offset(ms)

    def _lyrics_position(self, ms: int):
        cur = self.player.current
        if self.player.engine is not None and self.player.cast is None and not (cur and cur.get("stream")):
            # local songs: lyrics follow the play bar's smooth position
            if self._smoothing():
                return  # _smooth_position feeds them
            ms = self.heard_position(ms)
            for v in (self.lyrics_page.view, self.now.lyrics_view, self.now2.lyrics_view, self.now3.lyrics_view,
                      self.now4.lyrics_view):
                v.latency_ms = 0
                v.set_position(ms, self.player.is_playing())
            return
        playing = self.player.is_playing()
        eng = self.player.engine
        if eng is not None and self.player.cast is None and playing:
            lat = eng.latency_ms()
            for v in (self.lyrics_page.view, self.now.lyrics_view, self.now2.lyrics_view, self.now3.lyrics_view, self.now4.lyrics_view):
                # smooth the estimate so the highlight doesn't jitter
                v.latency_ms = int(v.latency_ms * 0.8 + lat * 0.2) if v.latency_ms else lat
        cur = self.player.current
        if cur and cur.get("stream"):
            # radio: position within the song, from when the station said it started
            start = cur.get("song_start")
            ms = ms - start if start is not None else -3_600_000
        for v in (self.lyrics_page.view, self.now.lyrics_view, self.now2.lyrics_view, self.now3.lyrics_view, self.now4.lyrics_view):
            v.set_position(ms, playing)

    def _lyrics_playing(self, playing: bool):
        for v in (self.lyrics_page.view, self.now.lyrics_view, self.now2.lyrics_view, self.now3.lyrics_view, self.now4.lyrics_view):
            v.set_playing(playing)

    def _lyrics_actions(self) -> list:
        t = self.player.current
        if t is None:
            return [("No song playing", None)]
        acts = []
        if self.lyrics_page.view.is_synced():
            off = self.lyrics_page.view.offset_ms
            acts += [("Show lyrics 0.5 s earlier", lambda: self._set_lyrics_offset(off + 500)),
                     ("Show lyrics 0.5 s later", lambda: self._set_lyrics_offset(off - 500))]
            if off:
                acts.append(("Reset timing", lambda: self._set_lyrics_offset(0)))
            acts.append(None)
        acts += [("Load a lyrics file (.lrc / .txt)…", self._load_lyrics_file),
                 ("Search online again", self._retry_lyrics)]
        if self.lyrics_page.view.lyrics is not None:
            acts.append(("Copy lyrics", self._copy_lyrics))
            acts.append(("Save as .lrc next to the song", self._save_lyrics_file))
        if self.pages.currentIndex() != 3:
            acts += [None, ("Open the Lyrics page", lambda: self._go_page(3))]
        return acts

    def _fill_lyrics_menu(self):
        m = self.lyrics_page.more_menu
        m.clear()
        for item in self._lyrics_actions():
            if item is None:
                m.addSeparator()
            else:
                a = m.addAction(item[0], item[1]) if item[1] else m.addAction(item[0])
                a.setEnabled(item[1] is not None)

    def _load_lyrics_file(self):
        t = self.player.current
        if t is None:
            return
        f, _ = QFileDialog.getOpenFileName(self, "Load lyrics", os.path.dirname(t["path"]),
                                           "Lyrics (*.lrc *.txt);;All files (*)")
        if f and self.lyrics.set_from_file(t, f) is None:
            self._flash("That file has no lyrics in it", 4000)

    def _retry_lyrics(self):
        t = self.player.current
        if t is None:
            return
        self.lyrics.forget(t)
        self._request_lyrics(t)

    def _copy_lyrics(self):
        ly = self.lyrics_page.view.lyrics
        if ly is not None:
            QApplication.clipboard().setText("\n".join(text for _, text in ly.lines))
            self._flash("Lyrics copied", 2500)

    def _save_lyrics_file(self):
        t, ly = self.player.current, self.lyrics_page.view.lyrics
        if t is None or ly is None:
            return
        target = os.path.splitext(t["path"])[0] + (".lrc" if ly.synced else ".txt")
        if os.path.exists(target) and QMessageBox.question(
                self, "Save lyrics", f"{os.path.basename(target)} already exists. Replace it?") != QMessageBox.Yes:
            return
        try:
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(ly.to_lrc())
            self._flash(f"Saved {os.path.basename(target)}", 3500)
        except OSError as e:
            self._flash(f"Couldn't save the lyrics: {e.strerror}", 6000)

    def _radio_step(self, d: int):
        """Next (+1) / Previous (-1) while a station plays: the next favourite station, or None."""
        if self.settings.value("radio_next", "stations") != "stations":
            return None
        favs = [st for st in self.radio_page.favourites_in_order() if st.get("url")]  # in display order
        cur = self.player.station or {}
        from musicwell import radio as radio_mod
        ids = [radio_mod.station_id(st) for st in favs]
        k = radio_mod.station_id(cur)
        if k in ids:
            if len(favs) < 2:
                return None
            st = favs[(ids.index(k) + d) % len(favs)]
        elif favs:
            st = favs[0] if d > 0 else favs[-1]
        else:
            return None
        n = favs.index(st) + 1
        self._flash(f"{st['name']}  ({n} of {len(favs)} favourite stations)", 3000)
        return st

    def _on_up_next(self, text: str):
        self.now.set_next(text)
        self.radio_page.next_text = text
        self.radio_page.list.viewport().update()

    def _song_alert(self, st: dict, artist: str, title: str, why: str):
        """A favourite station is playing something you'd like: notify, with a way to tune in."""
        self._alert_station, self._alert_at = st, time_now()
        msg = f"🔔  {artist} – {title} is on {st['name']} now ({why}) — click here to listen"
        self._flash(msg, 60_000)
        self._alert_msg = msg
        self.status.setCursor(Qt.PointingHandCursor)
        body = f"On {st['name']} now — {why}"
        # "default" is clicking the notification itself
        self._tray_alert = None
        if not self.desktop.notify_with(f"{artist} – {title}", body,
                                        [("default", "Listen"), ("listen", "▶ Listen"),
                                         ("show", "What's on now")], st):
            self._tray_alert = (st, time_now())  # fallback: the tray's pop-up, clicking it tunes in
            self.tray.message(f"{artist} – {title}", body + ". Click here to listen.")

    def _alert_listen(self, st: dict | None = None):
        st = st or getattr(self, "_alert_station", None)
        if st:
            self._alert_station = None
            self.status.unsetCursor()
            self._play_station(st)
            if self.settings.value("radio_alert_open", True, bool):  # Settings -> Radio -> When you click Listen
                self._go_page(5)
                self.radio_page.show_view("now")
            self._flash(f"Tuned in to {st['name']}", 3000)

    def _on_ad_dimmed(self, on: bool, text: str):
        if on:
            what = f"“{text}”" if text else "no song title"
            self._flash(f"Advert or jingle ({what}) — turned down until the next song. "
                        "Not an advert? Right-click the station picture.", 6000)
        elif self.player.station is not None and self.settings.value("radio_dim_ads", False, bool):
            self._clear_flash()

    def _play_station_from_stats(self, st: dict):
        """Tune in to a station from the Stats page."""
        uuid = st.get("uuid")
        for known in self.stations.favourites() + self.stations.recent():
            if known.get("uuid") == uuid or (st.get("url") and known.get("url") == st.get("url")):
                st = known
                break
        if not st.get("url"):
            return
        self._play_station(st)

    def _show_album_from_stats(self, artist: str, album: str):
        low_a, low_b = (artist or "").lower(), (album or "").lower()
        t = next((t for t in self.library.all_tracks() if (t.get("album") or "").lower() == low_b and
                  (t.get("albumartist") or t.get("artist_key") or t.get("artist") or "").lower() == low_a), None) or \
            next((t for t in self.library.all_tracks() if (t.get("album") or "").lower() == low_b), None)
        if t is not None:
            self._go_to_album(t)

    def show_track(self, tid: int):
        """Show a song where it is in the library and select it."""
        t = self.library.tracks.get(tid)
        if t is None:
            return
        self._go_page(0)
        if self._albums_home():
            self._go_to_album(t)
            QTimer.singleShot(0, lambda: self.albums_page.table.follow_id(tid, True))
            return
        if self._artist_home():
            self.open_artist_page(t["artist_key"], "album")
            QTimer.singleShot(0, lambda: self.artist_page.table.follow_id(tid, True))
            return
        if self.search.text():
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
            self._search_was = ""
        for pane in self.browser.panes:
            pane.list.clearSelection()
        self.browser.set_tracks(self.browser.base)
        self._refilter()
        self.lib_stack.setCurrentIndex(1)
        self.table.follow_id(tid, True)
        self._refollow = (lambda: self.table.follow_id(tid, True), time.monotonic() + 2.5)

    def _play_from_stats(self, tid: int):
        if tid not in self.library.tracks:
            return
        ids = self.table.model_.ids()
        if tid in ids:
            self.player.play_list(ids, ids.index(tid))
        else:
            self.player.play_list([tid], 0)

    def _toggle_lyrics_page(self):
        if self.pages.currentIndex() == 3:
            self._go_page(getattr(self, "_page_before_lyrics", 0))
        else:
            self._page_before_lyrics = self.pages.currentIndex()
            self._go_page(3)

    def _seek_to(self, ms: int):
        cur = self.player.current
        if cur and cur.get("stream"):
            # a lyric line clicked on the radio: that line is being sung now
            cur["song_start"] = self.player.position() - int(ms)
            self._lyrics_position(self.player.position())
            self._flash("Lyrics synced to the radio — the next songs sync by themselves", 3500)
            return
        self.player.seek(int(ms))
        if not self.player.is_playing():
            self._lyrics_position(int(ms))

    def _skip(self, delta: int):
        if self.player.current is None:
            return
        dur = self.player.duration()
        pos = max(0, self.player.position() + delta)
        if dur:
            pos = min(pos, max(0, dur - 1000))
        self._seek_to(pos)

    def _stop(self):
        """Stop: pause and go back to the start of the song."""
        if self.player.current is None:
            return
        if self.player.is_playing():
            self.player.play_pause()
        self._seek_to(0)

    def _on_volume(self, v: int):
        self.player.set_volume(v / 100)
        if v and self.player.is_muted():
            self.player.set_muted(False)
            self.sysmute.set_muted(False)
        self._refresh_bar()

    def _toggle_mute(self):
        muted = not self.player.is_muted()
        self.player.set_muted(muted)
        self.sysmute.set_muted(muted)
        self._refresh_bar()

    def _desktop_muted(self, muted: bool):
        """The desktop muted / unmuted us: follow it."""
        if self.player.is_muted() != muted:
            self.player.set_muted(muted)
            self._refresh_bar()

    def _move_queue(self, delta: int):
        if self.pages.currentIndex() != 1:
            return
        rows = self.queue_table.selected_rows()
        if not rows:
            return
        now = self.player.move_queue_rows(rows, delta)
        self.queue_table.selectionModel().clearSelection()
        for nr in now:
            if 0 <= nr < self.queue_table.model_.rowCount():
                self.queue_table.selectionModel().select(self.queue_table.model_.index(nr, 0), SEL_ROWS)

    def _track_menu(self, ids: list[int], pos, source: str, table: SongTable, pid=None):
        """Right-click menu for songs in the library, queue or a playlist."""
        if not ids:
            return
        from musicwell.menus import esc, title, tidy
        tracks = [self.library.tracks[i] for i in ids if i in self.library.tracks]
        m = QMenu(self)
        t0 = tracks[0] if tracks else None
        title(m, (t0.get("title") or "Unknown") if len(ids) == 1 and t0 else f"{len(ids)} songs")
        m.addAction("Play", lambda: self.player.play_list(ids, 0))
        m.addAction("Play next", lambda: self.player.enqueue(ids, front=True))
        m.addAction("Add to queue\tCtrl+Enter", lambda: self.player.enqueue(ids))
        add = m.addMenu("Add to playlist")
        add.addAction("New playlist…", lambda: self._new_playlist(ids))
        add.addSeparator()
        for pl, name in self.library.playlists():
            add.addAction(esc(name), lambda p=pl: self.library.add_to_playlist(p, ids))
        m.addSeparator()
        if t0:
            who = primary_artist(t0["artist_key"] or t0["artist"] or "")
            if not t0.get("remote") and t0.get("artist_key"):
                # skip where you already are
                rows = table.model_.rows
                on_artist = table is self.artist_page.table and \
                    (self.artist_page.name or "").lower() == (t0["artist_key"] or "").lower()
                one_album = bool(rows) and len({album_key(r) for r in rows}) == 1 and album_key(rows[0]) == album_key(t0) \
                    and table in (self.albums_page.table, self.artist_page.table)
                if not on_artist:
                    m.addAction("Go to artist", lambda: self.open_artist_page(t0["artist_key"], "album"))
                if t0.get("album") and not one_album:
                    m.addAction("Go to album", lambda: self._go_to_album(t0))
            dm = m.addMenu("Discover")
            dm.addAction("Songs like this one", lambda: self.find_similar(t0))
            if who:
                dm.addAction(esc(f"Music like {who}"), lambda: self.find_similar(artist=who))
                dm.addAction(esc(f"Search for {who}"), lambda: self.songs_by_online(who))
            m.addSeparator()
        rate = m.addMenu("Rating")
        for n in range(5, -1, -1):
            rate.addAction("★" * n + "☆" * (5 - n) if n else "No rating",
                           lambda n=n: self.library.set_rating(ids, n))
        if any(not t.get("remote") and not t.get("stream") for t in tracks):
            m.addAction("Edit tags…\tCtrl+E", lambda: self._edit_tags(tracks))
        if t0 and not t0.get("remote"):
            from musicwell.system import show_in_folder
            m.addAction("Open containing folder", lambda: show_in_folder(t0["path"]))
        online = [t for t in (self.library.get(i) for i in ids) if t and t.get("remote")]
        if online and (online[0].get("item") or {}).get("page"):
            it = online[0]["item"]
            from musicwell.freemusic import site
            m.addAction(f"Open on {site(it)} (licence, credit)", lambda: self._open_url(it["page"]))
        m.addSeparator()
        if source == "queue":
            rows = table.selected_rows()
            m.addAction("Move up\tAlt+Up", lambda: self._move_queue(-1))
            m.addAction("Move down\tAlt+Down", lambda: self._move_queue(1))
            m.addAction("Remove from queue\tDel", lambda: self.player.remove_queue_rows(rows))
        elif source == "playlist":
            m.addAction("Remove from playlist\tDel", lambda: self._remove_from_playlist(table.selected_rows(), pid))
        else:
            m.addAction("Remove from library…", lambda: self._remove_from_library(ids))
        tidy(m)
        from musicwell.widgets import add_menu_extras
        add_menu_extras(table, m)
        m.exec(pos)

    def _go_to_album(self, t: dict):
        """Show a song's album wherever the layout shows albums."""
        if self._albums_home():
            self._go_page(0)
            if self.search.text():
                self.search.blockSignals(True)  # leave the search results
                self.search.clear()
                self.search.blockSignals(False)
                self._search_was = ""
                self._refilter()
            self.open_albums_page(in_library=True)
            self.albums_page.jump_to(t["id"], show=True)
            return
        if self.browser.isVisible():
            self._show_in_browser("artist_key", t["artist_key"])
            self.browser.select_value("album", t["album"])
            return
        self.open_artist_page(t["artist_key"], "album")
        self.artist_page.pick_album(t)
        self.artist_page.jump_to(t["id"])

    def _edit_tags(self, tracks: list[dict]):
        tracks = [t for t in tracks if not t.get("remote") and not t.get("stream")]  # local files only
        if not tracks:
            return
        dlg = TagEditor(tracks, self)
        if dlg.exec():
            self.library.refresh_files([t["id"] for t in tracks])
            cur = self.player.current
            if cur and cur["id"] in self.library.tracks:
                self.player.current = self.library.tracks[cur["id"]]
                self._on_track_changed(self.player.current)

    def _remove_from_library(self, ids: list[int]):
        if not ids:
            return
        r = QMessageBox.question(
            self, "Remove from library",
            f"Remove {len(ids)} song{'s' if len(ids) != 1 else ''} from the library?\n\n"
            "The files stay on disk. They'll come back on the next rescan unless you move them "
            "out of your music folders.")
        if r == QMessageBox.Yes:
            self.library.remove_tracks(ids)

    def _refresh_playlists(self):
        cur = self.pl_list.currentItem()
        cur_id = cur.data(Qt.UserRole) if cur else None
        picked = {p for p, _ in self._ticked_playlists()}
        self.pl_list.blockSignals(True)
        self.pl_list.clear()
        for pid, name in self.library.playlists():
            n = len(self.library.playlist_track_ids(pid))
            it = QListWidgetItem(name)
            it.setData(Qt.UserRole, pid)
            it.setToolTip(f"{n} songs")
            self.pl_list.addItem(it)
            if pid == cur_id:
                self.pl_list.setCurrentItem(it)
            it.setSelected(pid in picked or (pid == cur_id and not picked))
        self._pl_show_ticks()
        if self.pl_list.currentItem() is None and self.pl_list.count():
            self.pl_list.setCurrentRow(0)
        self.pl_list.blockSignals(False)
        self._pl_picks_changed()
        self._show_playlist()

    def _current_playlist(self):
        it = self.pl_list.currentItem()
        return it.data(Qt.UserRole) if it else None

    def _show_playlist(self):
        pid = self._current_playlist()
        if pid is None:
            self.pl_title.setText("No playlists yet" if not self.pl_list.count() else "")
            self.pl_info.setText("Create one, or right-click songs → Add to playlist")
            self.pl_table.model_.set_rows([], keep_sort=False)
            return
        ids = self.library.playlist_track_ids(pid)
        rows = [t for t in (self.library.get(i) for i in ids) if t]
        self.pl_table.model_.set_rows(rows, keep_sort=False)
        if self.player.current:
            self.pl_table.model_.set_current(self.player.current["id"])
        self.pl_title.setText(self.pl_list.currentItem().text())
        total = sum(t["length"] or 0 for t in rows)
        self.pl_info.setText(f"{len(rows)} songs · {fmt_time(total)}")

    def _ask_playlist_for(self, tracks: list[dict]):
        names = [n for _, n in self.library.playlists()]
        new = "New playlist…"
        pick, ok = QInputDialog.getItem(self, "Add to playlist", f"Add “{tracks[0]['title']}” to:",
                                        names + [new], 0, False)
        if ok:
            pid = None if pick == new else dict((n, p) for p, n in self.library.playlists()).get(pick)
            self.add_online_to_playlist(tracks, pid)

    def add_online_to_playlist(self, tracks: list[dict], pid):
        """Add free music to a playlist (pid None = new playlist)."""
        ids = self.library.add_online(tracks)
        if not ids:
            return
        if pid is None:
            self._new_playlist(ids)
            return
        self.library.add_to_playlist(pid, ids)
        name = dict(self.library.playlists()).get(pid, "the playlist")
        n = len(ids)
        self._flash(f"{n} online song{'s' if n != 1 else ''} added to “{name}”")

    def _new_playlist(self, ids=None):
        name, ok = QInputDialog.getText(self, "New playlist", "Name:")
        if ok and name.strip():
            pid = self.library.create_playlist(name.strip())
            if ids:
                self.library.add_to_playlist(pid, ids)
            for i in range(self.pl_list.count()):
                if self.pl_list.item(i).data(Qt.UserRole) == pid:
                    self.pl_list.setCurrentRow(i)

    def _ticked_playlists(self) -> list[tuple[int, str]]:
        """Selected playlists in list order: [(id, name)]."""
        if not hasattr(self, "pl_list"):
            return []
        return [(self.pl_list.item(r).data(Qt.UserRole), self.pl_list.item(r).text())
                for r in range(self.pl_list.count()) if self.pl_list.item(r).isSelected()]

    def _picked_playlists(self) -> list[tuple[int, str]]:
        """What Delete acts on: the selected playlists, or the one showing."""
        picked = self._ticked_playlists()
        if picked:
            return picked
        it = self.pl_list.currentItem()
        return [(it.data(Qt.UserRole), it.text())] if it is not None else []

    def _pl_set_selecting(self, on: bool):
        """Select...: checkboxes on; Done: off (selection stays)."""
        self._pl_selecting = on
        self.pl_list.setSelectionMode(QAbstractItemView.MultiSelection if on else QAbstractItemView.ExtendedSelection)
        self.pl_select_btn.setText("Done" if on else "Select…")
        self.pl_all_btn.setVisible(on)
        self._pl_show_ticks()
        self._pl_picks_changed()

    def _pl_show_ticks(self):
        """Checkboxes only while selecting."""
        self.pl_list.blockSignals(True)
        for r in range(self.pl_list.count()):
            it = self.pl_list.item(r)
            if self._pl_selecting:
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Checked if it.isSelected() else Qt.Unchecked)
            else:
                it.setFlags(it.flags() & ~Qt.ItemIsUserCheckable)
                it.setData(Qt.CheckStateRole, None)
        self.pl_list.blockSignals(False)

    def _pl_tick_clicked(self, it):
        """A checkbox was clicked: sync the selection."""
        if self._pl_selecting and it.isSelected() != (it.checkState() == Qt.Checked):
            it.setSelected(it.checkState() == Qt.Checked)

    def _pl_tick_all(self):
        """Select all, or none if all are selected."""
        if len(self._ticked_playlists()) < self.pl_list.count():
            self.pl_list.selectAll()
        else:
            self.pl_list.clearSelection()

    def _pl_picks_changed(self):
        if self._pl_selecting:
            self._pl_show_ticks()
        n, t = self.pl_list.count(), len(self._ticked_playlists())
        self.pl_all_btn.setText("Select none" if n and t == n else "Select all")
        self.pl_select_btn.setEnabled(n > 0 or self._pl_selecting)
        self.pl_delete_btn.setText(f"Delete {t}…" if t > 1 else "Delete…")
        self.pl_delete_btn.setEnabled(bool(t or self.pl_list.currentItem() is not None))

    def _all_playlists(self) -> list[tuple[int, str]]:
        return [(self.pl_list.item(r).data(Qt.UserRole), self.pl_list.item(r).text())
                for r in range(self.pl_list.count())]

    def _playlist_menu(self, pos):
        """Right-click menu for a playlist."""
        from musicwell.menus import title, tidy
        it = self.pl_list.itemAt(pos)
        m = QMenu(self)
        picked = self._ticked_playlists()
        if it is not None and not it.isSelected():
            picked = [(it.data(Qt.UserRole), it.text())]  # right-click on an unselected playlist: just that one
        if it is not None and len(picked) > 1:
            n = len(picked)
            ids = [tid for p, _ in picked for tid in self.library.playlist_track_ids(p)]
            title(m, f"{n} playlists picked")
            m.addAction("Play them", lambda: ids and self.player.play_list(ids, 0))
            m.addAction("Add them to the queue", lambda: ids and self.player.enqueue(ids))
            m.addSeparator()
            m.addAction(f"Delete the {n} playlists…", lambda: self._delete_playlists(picked))
        elif it is not None:
            pid = it.data(Qt.UserRole)
            title(m, it.text())
            m.addAction("Play", lambda: self.player.play_list(self.library.playlist_track_ids(pid), 0))
            m.addAction("Add to queue", lambda: self.player.enqueue(self.library.playlist_track_ids(pid)))
            m.addSeparator()
            m.addAction("Rename…", lambda: self._rename_playlist(pid, it.text()))
            m.addAction("Export M3U…", self._export_m3u)
            m.addSeparator()
            m.addAction("Delete…\tDel", lambda: self._delete_playlists([(pid, it.text())]))
        else:
            m.addAction("New playlist…", lambda: self._new_playlist())
            m.addAction("Import M3U…", self._import_m3u)
            m.addSeparator()
            if self.pl_list.count():
                m.addAction(("Select none" if len(self._ticked_playlists()) == self.pl_list.count() else "Select all")
                            + "\tCtrl+A", self._pl_tick_all)
        if self.pl_list.count() > 1:
            m.addSeparator()
            m.addAction(f"Delete all {self.pl_list.count()} playlists…", lambda: self._delete_playlists(self._all_playlists()))
        tidy(m)
        m.exec(self.pl_list.viewport().mapToGlobal(pos))

    def _rename_playlist(self, pid, old):
        name, ok = QInputDialog.getText(self, "Rename playlist", "Name:", text=old)
        if ok and name.strip():
            self.library.rename_playlist(pid, name.strip())

    def _delete_playlists(self, picked: list[tuple[int, str]]):
        """Delete playlists after confirming. Their songs stay in the library."""
        if not picked:
            return
        n = len(picked)
        if n == 1:
            q = f"Delete the playlist “{picked[0][1]}”?"
        else:
            names = ", ".join(f"“{nm}”" for _, nm in picked[:6]) + (f" and {n - 6} more" if n > 6 else "")
            every = " — all your playlists" if n == self.pl_list.count() else ""
            q = f"Delete {n} playlists{every}?\n\n{names}"
        q += "\n\nThe songs stay in your library; only the playlists go."
        if QMessageBox.question(self, "Delete playlists" if n > 1 else "Delete playlist", q) != QMessageBox.Yes:
            return
        self.library.delete_playlists([p for p, _ in picked])
        self._flash(f"Deleted {n} playlist{'s' if n != 1 else ''}", 3000)

    def _remove_from_playlist(self, rows: list[int], pid=None):
        pid = self._current_playlist() if pid is None else pid
        if pid is None or not rows:
            return
        ids = self.library.playlist_track_ids(pid)
        visible = [i for i in ids if self.library.get(i)]
        drop = {r for r in rows}
        keep = [tid for r, tid in enumerate(visible) if r not in drop]
        self.library.set_playlist_tracks(pid, keep)

    def _import_m3u(self):
        f, _ = QFileDialog.getOpenFileName(self, "Import playlist", music_dir(), "Playlists (*.m3u *.m3u8)")
        if f:
            self.library.import_m3u(f)

    def _export_m3u(self):
        pid = self._current_playlist()
        if pid is None:
            return
        name = self.pl_list.currentItem().text()
        f, _ = QFileDialog.getSaveFileName(self, "Export playlist",
                                           os.path.join(music_dir(), f"{name}.m3u8"), "Playlists (*.m3u8 *.m3u)")
        if f:
            self.library.export_m3u(pid, f)

    def _nav_clicked(self, i: int):
        """A tab was clicked. Discover opens where you left it."""
        lay = self._layout_tab(i)
        if lay:
            QTimer.singleShot(0, lambda: self.use_layout(lay))
            return
        if i == 0 and self._playlist_followers():
            # Library tab while a panel's song list follows the tabs
            self._library_picked()
            where = " and the ".join(self._playlist_followers())
            if self.pages.isHidden():
                cur = self.pages.currentIndex()
                b = self.nav_buttons[self.MERGED.get(cur, cur)] if self.MERGED.get(cur, cur) < len(self.nav_buttons) else None
                if b is not None and b is not self.nav_buttons[0]:
                    b.setChecked(True)
                self._flash(f"Library — in the {where}", 2500)
                return
            self._go_page(0)
            return
        if i >= self.N_BUILTIN and self._playlist_followers():
            spec = self.custom_specs[i - self.N_BUILTIN] if i - self.N_BUILTIN < len(self.custom_specs) else {}
            if spec.get("kind") == "playlist" and spec.get("pid") is not None:
                cur = self.pages.currentIndex()
                b = self.nav_buttons[self.MERGED.get(cur, cur)] if self.MERGED.get(cur, cur) < len(self.nav_buttons) else None
                if b is not None:
                    b.setChecked(True)  # the main area hasn't changed
                self._playlist_picked(spec["pid"])
                self._flash(f"“{spec.get('name') or 'Playlist'}” — in the {' and the '.join(self._playlist_followers())}",
                            2500)
                return
        if self.pages.isHidden():
            QTimer.singleShot(0, lambda: self.set_centre_visible(True))
        self._go_page(self._discover_page if i == 6 else i)

    def open_discover(self, which: int):
        """0 Like this, 1 Search online, 2 My sources."""
        if which == 0:
            self._go_page(6)
        else:
            self.online_page.show_view(which - 1)
            self._go_page(7)

    def _sync_discover(self):
        cur = self.pages.currentIndex() if hasattr(self, "pages") else 6
        page = cur if cur in (6, 7) else self._discover_page
        which = 0 if page == 6 else 1 + self.online_page.stack.currentIndex()
        for sw in getattr(self, "discover_switches", []):
            sw.set_current(which)

    def _layout_tab(self, page: int):
        """The layout a tab switches to, or None."""
        if page >= self.N_BUILTIN and page - self.N_BUILTIN < len(self.custom_specs):
            spec = self.custom_specs[page - self.N_BUILTIN]
            if spec.get("kind") == "layout":
                return spec.get("layout") or None
        return None

    def _go_page(self, i: int):
        lay = self._layout_tab(i)
        if lay:  # a layout tab has no page
            self.use_layout(lay)
            return
        self.pages.setCurrentIndex(i)
        if getattr(self, "_overflow_tabs", None):
            QTimer.singleShot(0, self._check_tab_room)  # keep the current tab out of the » menu
        if i == 2:
            self._sync_playlists_page()  # a panel may show its songs instead
        if i in (6, 7):
            self._discover_page = i
            self._sync_discover()
        self.nav.button(6 if i == 7 else i).setChecked(True)
        if self.bar.lyrics_on != (i == 3):
            self._refresh_bar()
        if i == 3:
            cur = self.player.current
            if cur and cur.get("stream") and not getattr(self, "_radio_tip_shown", False) \
                    and not self.settings.value("radio_lyrics_tip_hidden", False, type=bool):
                self._radio_tip_shown = True  # once per session
                QTimer.singleShot(0, self._radio_lyrics_tip)

    def _radio_lyrics_tip(self):
        """First time Lyrics is opened on the radio: explain how syncing works there."""
        from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QLabel, QVBoxLayout
        d = QDialog(self)
        d.setWindowTitle("Lyrics on the radio")
        lay = QVBoxLayout(d)
        lay.setContentsMargins(22, 20, 22, 16)
        lay.setSpacing(12)
        head = QLabel("<b style='font-size:15px'>Lyrics on the radio</b>")
        lay.addWidget(head)
        text = QLabel(
            "<p>A station doesn't say how far into a song it is, so Musicwell times the lyrics "
            "from when the station announces each new song.</p>"
            "<ul style='margin-left:-18px'>"
            "<li><b>Tuned in part-way through a song?</b> Click the line that's being sung and the "
            "lyrics will follow from there.</li>"
            "<li><b>The next songs sync by themselves</b>, from the moment the station changes the title.</li>"
            "<li><b>A little early or late?</b> Use the <i>Earlier</i> / <i>Later</i> buttons at the "
            "top right (each moves the lyrics 0.5 s). Musicwell remembers it for each station.</li>"
            "</ul>"
            "<p><b>Not every song can be synced.</b> Some songs only have plain lyrics (no timings), "
            "some have no lyrics at all, and some stations change the title a little before or after "
            "the song really starts, which puts the timing out until you click a line.</p>")
        text.setWordWrap(True)
        text.setTextFormat(Qt.RichText)
        text.setMinimumWidth(440)
        lay.addWidget(text)
        never = QCheckBox("Don't show this again")
        never.setObjectName("radioTipNever")
        lay.addWidget(never)
        bb = QDialogButtonBox(QDialogButtonBox.Ok)
        bb.accepted.connect(d.accept)
        lay.addWidget(bb)
        self._radio_tip_dialog = d
        d.exec()
        if never.isChecked():
            self.settings.setValue("radio_lyrics_tip_hidden", True)
        self._radio_tip_dialog = None

    TAB_NAMES = ["Library", "Queue", "Playlists", "Lyrics", "Stats", "Radio", "Discover", "Online Sources"]
    N_BUILTIN = 8  # pages 0-7 are built in; user tabs come after
    MERGED = {7: 6}  # page 7 has no tab: it's part of Discover

    def tab_names(self) -> dict[int, str]:
        try:
            d = json.loads(self.settings.value("tab_names", "{}") or "{}")
            return {int(k): str(v) for k, v in d.items() if str(v).strip()}
        except (TypeError, ValueError, AttributeError):
            return {}

    def tab_name(self, page: int) -> str:
        if page >= self.N_BUILTIN:
            return self.custom_specs[page - self.N_BUILTIN].get("name") or "Tab"
        return self.tab_names().get(page) or self.TAB_NAMES[page]

    TAB_ICONS = {0: "library", 1: "queue", 2: "playlists", 3: "lyrics", 4: "stats", 5: "radio", 6: "discover",
                 7: "discover"}
    TAB_STYLES = [("words", "Words"), ("icons", "Icons"), ("both", "Icons and words")]

    def tab_style(self) -> str:
        v = self.settings.value("tab_style", "words") or "words"
        return v if v in dict(self.TAB_STYLES) else "words"

    def set_tab_style(self, style: str):
        """Tabs as words, icons, or both."""
        self.settings.setValue("tab_style", style)
        self._tabs_squeezed = False
        self._tab_level = 0
        self._overflow_tabs = []
        self._apply_tab_names()
        self._layout_topbar(self.settings.value("panel_side", "left"))
        QTimer.singleShot(0, self._check_tab_room)

    def _tab_icon_name(self, page: int) -> str:
        if page >= self.N_BUILTIN:
            spec = self.custom_specs[page - self.N_BUILTIN]
            kind = spec.get("kind")
            if kind != "search":
                return {"playlist": "playlists", "albums": "albums", "layout": "layouts"}.get(kind, "search")
            q = (spec.get("query") or "").replace(" ", "").lower()
            if "rating>" in q or "liked" in q or (spec.get("name") or "").lower() == "favourites":
                return "heart_empty"  # Favourites
            if "added<" in q:
                return "sparkle"  # Recently added
            if "lastplayed<" in q:
                return "clock"  # Recently played
            if "plays=0" in q:
                return "play_outline"  # Never played
            if "plays>" in q:
                return "trend"  # Most played
            return "search"
        return self.TAB_ICONS.get(page, "library")

    def _tab_icon(self, page: int):
        """Tab icon: muted colour, text colour when current."""
        from PySide6.QtGui import QIcon, QPixmap
        from musicwell import theme as th
        name = self._tab_icon_name(page)
        ic = QIcon()
        ic.addPixmap(QPixmap.fromImage(th.svg_image(name, self.theme.color("muted"), 24)), QIcon.Normal, QIcon.Off)
        ic.addPixmap(QPixmap.fromImage(th.svg_image(name, self.theme.color("text"), 24)), QIcon.Normal, QIcon.On)
        ic.addPixmap(QPixmap.fromImage(th.svg_image(name, self.theme.color("text"), 24)), QIcon.Active, QIcon.Off)
        return ic

    def _effective_tab_style(self) -> str:
        chosen = self.tab_style() if hasattr(self, "settings") else "words"
        return chosen  # a narrow window packs tabs or uses », never changes this

    def _tabs_tight(self) -> bool:
        """Tabs packed closer (smaller text) before giving up on words."""
        return getattr(self, "_tab_level", 0) >= 1

    def _check_tab_room(self):
        """Do the tabs fit? Try packing closer, then move tabs into the » menu."""
        if not hasattr(self, "nav_buttons") or not hasattr(self, "top_bar") or getattr(self, "_in_tab_check", False):
            return
        self._in_tab_check = True
        try:
            tl, W = self.top_layout, self.top_bar.width()
            vis = self.visible_tab_order()
            cur = self.pages.currentIndex() if hasattr(self, "pages") else 0
            cur = self.MERGED.get(cur, cur)

            def need():
                tl.invalidate()
                return tl.minimumSize().width()

            def apply(level, over):
                self._tab_level, self._overflow_tabs = level, sorted(over, key=vis.index)
                self._apply_tab_names()
                self._apply_tab_visibility_only()

            level = getattr(self, "_tab_level", 0)
            over = [p for p in getattr(self, "_overflow_tabs", []) if p in vis and p != cur]
            if over != getattr(self, "_overflow_tabs", []):
                apply(level, over)
            # too wide: pack closer, then move tabs from the end into » (never Library or the current tab)
            guard = 0
            while need() > W and guard < 40:
                guard += 1
                if level == 0 and self.tab_style() != "icons":
                    level = 1
                else:
                    level = max(level, 1) if self.tab_style() != "icons" else level
                    cand = [p for p in vis if p not in over and p not in (0, cur)]
                    if not cand:
                        break
                    over.append(cand[-1])
                apply(level, over)
            # room to spare: bring tabs back, then unpack
            guard = 0
            while guard < 40:
                guard += 1
                if over:
                    back = sorted(over, key=vis.index)[0]
                    trial = [p for p in over if p != back]
                    apply(level, trial)
                    if need() + 16 <= W:
                        over = trial
                        continue
                    apply(level, over)
                    break
                if level > 0:
                    apply(0, over)
                    if need() + 24 <= W:
                        level = 0
                        continue
                    apply(level, over)
                break
            self._tabs_squeezed = False
        finally:
            self._in_tab_check = False
            if hasattr(self, "top_layout"):
                self.top_layout.invalidate()  # lay out now so intermediate tries never reach the screen
                self.top_layout.activate()

    def _apply_tab_visibility_only(self):
        hidden = self.hidden_tabs()
        over = set(self._overflow_tabs)
        for i, b in enumerate(self.nav_buttons):
            b.setVisible(i not in hidden and i not in self.MERGED and i not in over)
        self.more_tabs_btn.setVisible(bool(over))

    def _show_more_tabs(self):
        m = QMenu(self)
        cur = self.pages.currentIndex()
        cur = self.MERGED.get(cur, cur)
        for p in self._overflow_tabs:
            a = m.addAction(self._tab_icon(p), self.tab_name(p).replace("&", "&&"), lambda p=p: self._nav_clicked(p))
            a.setCheckable(True)
            a.setChecked(p == cur)
        m.exec(self.more_tabs_btn.mapToGlobal(self.more_tabs_btn.rect().bottomLeft()))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if not hasattr(self, "_tab_room_timer"):
            self._tab_room_timer = QTimer(self, singleShot=True, interval=0)
            self._tab_room_timer.timeout.connect(self._check_tab_room)
        self._tab_room_timer.start()

    def _apply_tab_names(self):
        from PySide6.QtCore import QSize
        style = self._effective_tab_style()
        n = len(self.player.queue) if hasattr(self, "player") else 0
        for i, b in enumerate(self.nav_buttons):
            name = self.tab_name(i)
            count = f"{n}" if i == 1 and n else ""
            if style == "icons":
                b.setText(count)  # icon only (plus the queue count)
            else:
                b.setText((" " if style == "both" else "") + (f"{name} ({count})" if count else name))
            if style == "words":
                b.setIcon(__import__("PySide6.QtGui", fromlist=["QIcon"]).QIcon())
            else:
                b.setIcon(self._tab_icon(i))
                tight = self._tabs_tight()
                b.setIconSize(QSize(24, 24) if style == "icons" else QSize(16 if tight else 20, 16 if tight else 20))
            tip = b.property("baseTip")
            if tip is None:
                tip = b.toolTip() or ""
                b.setProperty("baseTip", tip)
            b.setToolTip(name + (f" — {tip}" if tip else "") if style == "icons" else tip)
            tight = self._tabs_tight() and style != "icons"
            if b.property("iconsOnly") != (style == "icons") or bool(b.property("tight")) != tight:
                b.setProperty("iconsOnly", style == "icons")
                b.setProperty("tight", tight)
                b.style().unpolish(b)
                b.style().polish(b)
            b.setMinimumWidth(b.sizeHint().width())  # never squeezed

    def rename_tab(self, page: int):
        if page >= self.N_BUILTIN:
            spec = self.custom_specs[page - self.N_BUILTIN]
            name, ok = QInputDialog.getText(self, "Rename tab", f"New name for the “{spec['name']}” tab:",
                                            text=spec["name"])
            if ok and name.strip():
                spec["name"] = name.strip()
                self._save_custom_tabs()
                self.nav_buttons[page].setText(spec["name"])
                self.custom_pages[page - self.N_BUILTIN].title.setText(spec["name"])
            return
        name, ok = QInputDialog.getText(self, "Rename tab", f"New name for the “{self.tab_name(page)}” tab:"
                                        f"\n\nLeave it empty to go back to “{self.TAB_NAMES[page]}”.",
                                        text=self.tab_name(page))
        if not ok:
            return
        names = self.tab_names()
        name = name.strip()
        if name and name != self.TAB_NAMES[page]:
            names[page] = name
        else:
            names.pop(page, None)
        self.settings.setValue("tab_names", json.dumps({str(k): v for k, v in names.items()}))
        self._apply_tab_names()

    def reset_tab_names(self):
        self.settings.setValue("tab_names", "{}")
        self._apply_tab_names()

    # Pages are numbers at runtime; in settings user tabs are saved by id.
    def _tab_key(self, page: int):
        return page if page < self.N_BUILTIN else self.custom_specs[page - self.N_BUILTIN]["id"]

    def _page_of_key(self, key):
        if isinstance(key, int) or (isinstance(key, str) and key.isdigit()):
            k = int(key)
            return k if 0 <= k < self.N_BUILTIN else None
        for i, spec in enumerate(getattr(self, "custom_specs", [])):
            if spec.get("id") == key:
                return self.N_BUILTIN + i
        return None

    def tab_order(self) -> list[int]:
        try:
            raw = json.loads(self.settings.value("tab_order", "[]") or "[]")
        except (TypeError, ValueError):
            raw = []
        order = []
        for k in raw if isinstance(raw, list) else []:
            p = self._page_of_key(k)
            if p is not None and p < len(self.nav_buttons) and p not in order:
                order.append(p)
        for p in range(self.N_BUILTIN):  # built-in tab added since the order was saved
            if p not in order and p < len(self.nav_buttons):
                prev = [q for q in order if q < self.N_BUILTIN and q < p]
                at = order.index(max(prev)) + 1 if prev else len(order)
                order.insert(at, p)
        order = order + [i for i in range(len(self.nav_buttons)) if i not in order]
        return [p for p in order if p not in self.MERGED]

    def set_tab_order(self, order: list[int]):
        self.settings.setValue("tab_order", json.dumps([self._tab_key(p) for p in order]))
        self._layout_topbar(self.settings.value("panel_side", "left"))

    def hidden_tabs(self) -> set[int]:
        """Tabs you've removed (never Library)."""
        try:
            raw = json.loads(self.settings.value("tabs_hidden", "[]") or "[]")
        except (TypeError, ValueError):
            raw = []
        out = set()
        for k in raw if isinstance(raw, list) else []:
            p = self._page_of_key(k)
            if p is not None and p != 0 and p < len(self.nav_buttons) and p not in self.MERGED:
                out.add(p)
        return out

    def _set_hidden_tabs(self, pages):
        self.settings.setValue("tabs_hidden", json.dumps([self._tab_key(p) for p in sorted(pages) if p != 0]))
        self._apply_tab_visibility()

    def set_tab_hidden(self, page: int, hidden: bool):
        h = self.hidden_tabs()
        (h.add if hidden else h.discard)(page)
        self._set_hidden_tabs(h)
        if hidden:
            self._flash(f"Removed “{self.tab_name(page)}” — + puts it back", 5000)

    def _tab_shown(self, page: int) -> bool:
        return page not in self.hidden_tabs()

    def _apply_tab_visibility(self):
        QTimer.singleShot(0, self._check_tab_room)  # more or fewer tabs: check they fit
        hidden = self.hidden_tabs()
        over = set(getattr(self, "_overflow_tabs", []))
        for i, b in enumerate(self.nav_buttons):
            b.setVisible(i not in hidden and i not in self.MERGED and i not in over)
        if hasattr(self, "more_tabs_btn"):
            self.more_tabs_btn.setVisible(bool(over))
        if hasattr(self, "pages"):
            cur = self.pages.currentIndex()
            if self.MERGED.get(cur, cur) in hidden:
                self._go_page(0)

    def _add_albums_tab_once(self):
        """One-time migration for the Albums tab."""
        if self.settings.value("albums_tab_removed", False, type=bool):
            return
        self.settings.setValue("albums_tab_removed", True)
        self.settings.setValue("albums_tab_added", True)  # never added back
        if any(sp.get("kind") == "albums" for sp in self.custom_specs):
            self.custom_specs = [sp for sp in self.custom_specs if sp.get("kind") != "albums"]
            self._save_custom_tabs()
            self._build_custom_tabs()
            self._layout_topbar(self.settings.value("panel_side", "left"))
            self._apply_tab_visibility()

    def _merge_discover_tabs(self):
        """One-time migration: Similar and Online Sources became Discover."""
        if self.settings.value("discover_merged", False, type=bool):
            return
        try:
            raw = json.loads(self.settings.value("tabs_hidden", "[]") or "[]")
        except (TypeError, ValueError):
            raw = []
        keys = [str(k) for k in raw] if isinstance(raw, list) else []
        if "6" in keys and "7" not in keys:
            keys.remove("6")
        keys = [k for k in keys if k != "7"]
        self.settings.setValue("tabs_hidden", json.dumps([int(k) if k.isdigit() else k for k in keys]))
        names = self.tab_names()
        if names.get(6) == "Similar":
            names.pop(6)
            self.settings.setValue("tab_names", json.dumps({str(k): v for k, v in names.items()}))
        self.settings.setValue("discover_merged", True)

    def tabs_state(self) -> dict:
        """Shown tabs, order, names and user tabs (saved in layouts)."""
        try:
            names = json.loads(self.settings.value("tab_names", "{}") or "{}")
        except (TypeError, ValueError):
            names = {}
        return {"order": [self._tab_key(p) for p in self.tab_order()],
                "hidden": [self._tab_key(p) for p in sorted(self.hidden_tabs())],
                "custom": [dict(s) for s in self.custom_specs],
                "names": names if isinstance(names, dict) else {}}

    def apply_tabs_state(self, d):
        """Apply a layout's tabs. "all" shows every built-in tab."""
        if d == "all":
            self._set_hidden_tabs({p for p in range(self.N_BUILTIN, len(self.nav_buttons))
                                   if not self._layout_tab(p)})
            self._layout_topbar(self.settings.value("panel_side", "left"))
            return
        if not isinstance(d, dict):
            return
        idmap = {}
        changed = False

        def same(a, b):
            return {k: v for k, v in a.items() if k != "id"} == {k: v for k, v in b.items() if k != "id"}
        for spec in d.get("custom") or []:
            if not isinstance(spec, dict) or not spec.get("id") or spec.get("kind") == "layout":
                continue  # layout tabs are in every layout
            # same id and kind: keep its columns
            mine = next((s for s in self.custom_specs if s.get("id") == spec["id"]
                         and s.get("kind") == spec.get("kind")), None) \
                or next((s for s in self.custom_specs if same(s, spec)), None)
            if mine is None:
                if any(s.get("id") == spec["id"] for s in self.custom_specs):  # id used by another tab
                    page = self.add_custom_tab({k: v for k, v in spec.items() if k != "id"}, go=False)
                    idmap[spec["id"]] = self.custom_specs[page - self.N_BUILTIN]["id"]
                else:
                    self.custom_specs.append(dict(spec))
                    idmap[spec["id"]] = spec["id"]
                    changed = True
            else:
                idmap[spec["id"]] = mine["id"]
        if changed:
            self._save_custom_tabs()
            self._build_custom_tabs()

        def page(k):
            if isinstance(k, str) and not k.isdigit():
                k = idmap.get(k, k)
            return self._page_of_key(k)
        known = {p for p in (page(k) for k in d.get("order") or []) if p is not None}
        hidden = {p for p in (page(k) for k in d.get("hidden") or []) if p is not None}
        hidden |= {p for p in range(self.N_BUILTIN, len(self.nav_buttons)) if p not in known  # your newer tabs
                   and not self._layout_tab(p)}
        hidden.discard(0)
        if isinstance(d.get("names"), dict):
            self.settings.setValue("tab_names", json.dumps({str(k): v for k, v in d["names"].items()}))
        order = [p for p in (page(k) for k in d.get("order") or []) if p is not None]
        if order and not d.get("keep_order"):  # a built-in that only hides tabs keeps your order
            self.settings.setValue("tab_order", json.dumps([self._tab_key(p) for p in dict.fromkeys(order)]))
        self._set_hidden_tabs(hidden)
        self._apply_tab_names()
        self._layout_topbar(self.settings.value("panel_side", "left"))

    def visible_tab_order(self) -> list[int]:
        return [p for p in self.tab_order() if self._tab_shown(p)]

    def _tab_menu(self, page: int, pos):
        """Locked: just Unlock. Unlocked: rename, remove, add. Tabs move by dragging."""
        m = QMenu(self)
        m.setToolTipsVisible(True)
        if getattr(self, "customizing", False):
            name = self.tab_name(page).replace("&", "&&")
            m.addAction(f"Rename “{name}” tab…", lambda: self.rename_tab(page))
            if page >= self.N_BUILTIN:
                spec = self.custom_specs[page - self.N_BUILTIN]
                if spec.get("kind") == "search":
                    m.addAction("Edit tab… (search, sort, how many)", lambda: self._edit_custom_tab(page))
            if page == 0:
                a = m.addAction("Remove tab")
                a.setEnabled(False)
                a.setToolTip("The Library tab always stays")
            elif page >= self.N_BUILTIN:
                m.addAction(f"Remove “{name}” tab…", lambda: self.remove_custom_tab(page))
            else:
                m.addAction(f"Remove “{name}” tab", lambda: self.set_tab_hidden(page, True))
            self._fill_add_tab_menu(m.addMenu("Add a tab"))
            tm = m.addMenu("All tabs")
            tm.addAction("Show, remove and order…", self.arrange_tabs)
            sm = tm.addMenu("Show tabs as")
            for key, label in self.TAB_STYLES:
                a = sm.addAction(label, lambda k=key: self.set_tab_style(k))
                a.setCheckable(True)
                a.setChecked(self.tab_style() == key)
            if self.tab_names():
                tm.addAction("Reset tab names", self.reset_tab_names)
            tm.addAction("Reset tab order", lambda: self.set_tab_order(list(range(len(self.nav_buttons)))))
            m.addSeparator()
            m.addAction("🔒  Lock (nothing moves)", lambda: self.set_customizing(False))
        else:
            m.addAction("🔓  Unlock to edit", lambda: self.set_customizing(True))
        m.exec(self.nav_buttons[page].mapToGlobal(pos))

    def _fill_add_tab_menu(self, menu: QMenu, put_back: bool = True, on_added=None):
        """Add tab: removed tabs, a playlist, preset searches or your own search."""
        from musicwell.customtabs import PRESETS
        menu.setToolTipsVisible(True)
        hidden = [p for p in self.tab_order() if p in self.hidden_tabs()] if put_back else []
        for p in hidden:
            a = menu.addAction(f"Put back “{self.tab_name(p)}”".replace("&", "&&"),
                               lambda p=p: self.set_tab_hidden(p, False))
            a.setToolTip("A tab you removed")
        if hidden:
            menu.addSeparator()

        def add(spec):
            page = self.add_custom_tab(spec, go=on_added is None)
            if on_added:
                on_added(page, spec["name"])
        plm = menu.addMenu("A playlist")
        pls = self.library.playlists()
        for pid, pname in pls:
            plm.addAction(pname.replace("&", "&&"),
                          lambda pid=pid, pname=pname: add({"kind": "playlist", "pid": pid, "name": pname}))
        if not pls:
            plm.addAction("No playlists yet").setEnabled(False)
        menu.addSeparator()
        for pr in PRESETS:
            a = menu.addAction(pr["name"], lambda pr=pr: add({"kind": "search", "name": pr["name"], "query": pr["query"],
                                                              "sort": pr.get("sort"), "limit": pr.get("limit", 0)}))
            a.setToolTip(f"{pr['tip']}  ({pr['query']})")
        menu.addSeparator()
        from musicwell import layouts as L
        lm = menu.addMenu("A layout")
        lm.setToolTipsVisible(True)
        have = {sp.get("layout") for sp in self.custom_specs if sp.get("kind") == "layout"}
        for name, desc, _d, _b in L.all_presets(self.settings):
            a = lm.addAction(name.replace("&", "&&"), lambda n=name: add({"kind": "layout", "layout": n, "name": n}))
            a.setToolTip("A tab that switches to this layout")
            a.setEnabled(name not in have)
        menu.addSeparator()
        a = menu.addAction("All albums", lambda: add({"kind": "albums", "name": "Albums"}))
        a.setToolTip("Every album in your library as covers — sort, filter, click for the songs")
        menu.addSeparator()

        def search():
            from musicwell.customtabs import SearchTabDialog
            dlg = SearchTabDialog(None, self, current_search=self.search.text().strip())
            if dlg.exec():
                add(dlg.result_spec())
        menu.addAction("A search of your own…", search)

    def _show_add_tab_menu(self):
        m = QMenu(self)
        self._fill_add_tab_menu(m)
        m.exec(self.add_tab_btn.mapToGlobal(self.add_tab_btn.rect().bottomLeft()))

    def arrange_tabs(self):
        from musicwell.dialogs import ArrangeTabsDialog
        hidden = self.hidden_tabs()
        tabs = [(i, self.tab_name(i), i not in hidden, i == 0) for i in self.tab_order()]
        dlg = ArrangeTabsDialog(tabs, self, removable=lambda p: p >= self.N_BUILTIN,
                                add_menu=lambda m: self._fill_add_tab_menu(m, put_back=False, on_added=dlg.add_item))
        if not dlg.exec():
            return
        keys = {p: self._tab_key(p) for p in dlg.order() + dlg.removed}
        hidden_keys = [keys[p] for p in dlg.hidden()]
        order_keys = [keys[p] for p in dlg.order()]
        if dlg.removed:
            gone = {keys[p] for p in dlg.removed}
            self.custom_specs = [s for s in self.custom_specs if s["id"] not in gone]
            self._save_custom_tabs()
            self._build_custom_tabs()
        self.settings.setValue("tabs_hidden", json.dumps(hidden_keys))
        self.set_tab_order([p for p in (self._page_of_key(k) for k in order_keys) if p is not None])
        self._apply_tab_visibility()

    def _load_custom_tabs(self):
        try:
            specs = json.loads(self.settings.value("custom_tabs", "[]") or "[]")
        except (TypeError, ValueError):
            specs = []
        self.custom_specs = [s for s in specs if isinstance(s, dict) and s.get("id")
                             and s.get("kind") in ("playlist", "search", "albums", "layout")]

    def _save_custom_tabs(self):
        self.settings.setValue("custom_tabs", json.dumps(self.custom_specs))

    def add_custom_tab(self, spec: dict, go: bool = True) -> int:
        n = int(self.settings.value("custom_tab_next", 1)) if self.settings.contains("custom_tab_next") else 1
        while any(s["id"] == f"c{n}" for s in self.custom_specs):
            n += 1
        spec = dict(spec, id=f"c{n}")
        self.settings.setValue("custom_tab_next", n + 1)
        self.custom_specs.append(spec)
        self._save_custom_tabs()
        self._build_custom_tabs()
        page = self.N_BUILTIN + len(self.custom_specs) - 1
        if go:
            self._go_page(page)
            self._flash(f"Added the “{spec['name']}” tab", 4000)
        return page

    def remove_custom_tab(self, page: int):
        spec = self.custom_specs[page - self.N_BUILTIN]
        what = "The playlist stays on the Playlists tab." if spec.get("kind") == "playlist" else \
            "The layout stays in the Layouts menu." if spec.get("kind") == "layout" else \
            "Your songs stay in the library."
        r = QMessageBox.question(self, "Remove tab", f"Remove the “{spec['name']}” tab?\n\n{what}")
        if r != QMessageBox.Yes:
            return
        was = self.pages.currentIndex() == page
        self.custom_specs.remove(spec)
        self._save_custom_tabs()
        self._build_custom_tabs()
        if was:
            self._go_page(0)

    def _edit_custom_tab(self, page: int):
        from musicwell.customtabs import SearchTabDialog
        spec = self.custom_specs[page - self.N_BUILTIN]
        dlg = SearchTabDialog(spec, self)
        if not dlg.exec():
            return
        spec.update(dlg.result_spec())
        self._save_custom_tabs()
        w = self.custom_pages[page - self.N_BUILTIN]
        w._apply_spec_sort()
        self.nav_buttons[page].setText(spec["name"])
        self._refresh_custom_tab(w)

    def _build_custom_tabs(self):
        """Rebuild user tab pages and buttons from self.custom_specs."""
        from musicwell.customtabs import CustomTabPage
        cur = self.pages.currentIndex()
        for w in getattr(self, "custom_pages", []):
            self.pages.removeWidget(w)
            w.deleteLater()
        for b in self.nav_buttons[self.N_BUILTIN:]:
            self.nav.removeButton(b)
            b.setParent(None)
            b.deleteLater()
        del self.nav_buttons[self.N_BUILTIN:]
        self.custom_pages = []
        for i, spec in enumerate(self.custom_specs):
            page = self.N_BUILTIN + i
            b = QPushButton(spec.get("name") or "Tab")
            b.setObjectName("NavButton")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            b.setToolTip(f"Playlist “{dict(self.library.playlists()).get(spec.get('pid'), '?')}”"
                         if spec["kind"] == "playlist" else ("Every album, as covers" if spec["kind"] == "albums"
                                                             else f"Switch to the “{spec.get('layout')}” layout"
                                                             if spec["kind"] == "layout"
                                                             else f"Search: {spec.get('query') or 'all songs'}"))
            self.nav.addButton(b, page)
            self.nav_buttons.append(b)
            b.setContextMenuPolicy(Qt.CustomContextMenu)
            b.customContextMenuRequested.connect(lambda pos, p=page: self._tab_menu(p, pos))
            b.installEventFilter(self)  # tabs can be dragged
            if spec["kind"] == "layout":  # a layout button has no page
                b.setCheckable(False)
                w = _LayoutTabPage(spec)
                self.pages.addWidget(w)
                self.custom_pages.append(w)
                continue
            if spec["kind"] == "albums":
                from musicwell.albumsview import AlbumsPage
                w = AlbumsPage(self.theme, back=False, spec=spec)
                self._wire_albums(w)
            else:
                w = CustomTabPage(spec, self.theme)
            w.table.set_fields(F.all_fields())
            w.table.restore_column_state(spec.get("columns") or [])
            if spec["kind"] == "playlist":
                w.table.show_column("source")
            self.pages.addWidget(w)
            self.custom_pages.append(w)
            self._wire_custom_page(w)
            self._refresh_custom_tab(w)
        self._apply_tab_names()
        self._layout_topbar(self.settings.value("panel_side", "left"))
        self._apply_tab_visibility()
        if cur < self.pages.count():
            self.nav.button(cur) and self.nav.button(cur).setChecked(True)
        else:
            self._go_page(0)

    def _wire_custom_page(self, w):
        t, pl, lib = w.table, self.player, self.library
        playlist = w.is_playlist
        albums = w.spec.get("kind") == "albums"  # its buttons play the selected album
        if not albums:
            w.play_btn.clicked.connect(lambda: pl.play_list(t.model_.ids(), 0))
            w.shuffle_btn.clicked.connect(lambda: pl.play_list(w.shuffled_ids(), 0))
        if albums:
            pass
        elif playlist:
            w.edit_btn.setText("Open in Playlists")
            w.edit_btn.setToolTip("Show this playlist on the Playlists tab (rename, export…)")
            w.edit_btn.clicked.connect(lambda: self._open_playlist(w.spec.get("pid")))
        else:
            w.edit_btn.clicked.connect(lambda: self._edit_custom_tab(self.N_BUILTIN + self.custom_pages.index(w)))
        t.playRequested.connect(lambda r: pl.play_list(t.model_.ids(), r))
        t.menuRequested.connect(lambda ids, pos: self._track_menu(ids, pos, "playlist" if playlist else "library", t,
                                                                 pid=w.spec.get("pid") if playlist else None))
        t.rated.connect(lambda tid, r: lib.set_rating([tid], r))
        t.customColumnRequested.connect(lambda: self._add_custom_column(t))
        t.customRemoveRequested.connect(self._remove_custom_field)
        t.customManageRequested.connect(lambda: self.manage_custom_fields(t))
        t.renameRequested.connect(self.rename_column)
        t.resetNamesRequested.connect(self.reset_column_names)
        t.autoFitToggled.connect(self._on_autofit)
        if not hasattr(self, "_save_custom_timer"):
            self._save_custom_timer = QTimer(self, singleShot=True, interval=1500)
            self._save_custom_timer.timeout.connect(self._save_custom_tabs)
        w.changed.connect(self._save_custom_timer.start)
        if playlist:
            t.enable_drops()
            t.tracksDropped.connect(lambda ids, row, internal, rows:
                                    self._drop_on_playlist(ids, row, internal, rows, pid=w.spec.get("pid"), table=t))
            t.deleteRequested.connect(lambda rows: self._remove_from_playlist(rows, pid=w.spec.get("pid")))
        else:
            t.deleteRequested.connect(lambda rows: self._remove_from_library(t.selected_ids()))

    def _on_autofit(self, on: bool):
        """Auto-resize columns on or off."""
        SongTable.AUTO_FIT = bool(on)
        self.settings.setValue("columns_autofit", bool(on))
        if on:
            for t in (self.table, self.queue_table, self.pl_table, self.similar_page.table, *self._custom_tables()):
                t.fit_all_columns()
        self._flash("Columns resize to fit what's in them" if on else "Auto-resize columns: off", 3000)

    def _open_playlist(self, pid):
        for i in range(self.pl_list.count()):
            if self.pl_list.item(i).data(Qt.UserRole) == pid:
                self.pl_list.setCurrentRow(i)
        self._go_page(2)

    def _refresh_custom_tab(self, w):
        cur = self.player.current["id"] if self.player.current else None
        w.refresh(self.library, cur)

    def _refresh_custom_tabs(self, kind: str | None = None):
        for w in getattr(self, "custom_pages", []):
            if kind is None or w.spec.get("kind") == kind:
                self._refresh_custom_tab(w)

    def _custom_tables(self) -> list:
        """Song tables of user tabs and the artist page."""
        extra = [p.table for p in (getattr(self, "artist_page", None), getattr(self, "albums_page", None)) if p]
        return [w.table for w in getattr(self, "custom_pages", []) if getattr(w, "table", None) is not None] + extra

    def _toggle_panel(self):
        self.now.setVisible(not self.now.isVisible())
        self._layout_touched()
        self._refresh_bar()
        self._panels_follow_customizing()
        self._record_tab_panels()

    # each tab can have its own panels
    def _tab_panels(self) -> dict:
        try:
            d = json.loads(self.settings.value("panels_by_tab", "{}") or "{}")
            return d if isinstance(d, dict) else {}
        except (TypeError, ValueError):
            return {}

    def _current_tab_key(self) -> str:
        page = self.pages.currentIndex() if hasattr(self, "pages") else 0
        page = self.MERGED.get(page, page)
        try:
            return str(self._tab_key(page))
        except (IndexError, KeyError):
            return "0"

    def _panels_now(self) -> dict:
        return {"left": self.now.isVisible(), "right": self.now2.isVisible(), "top": self.now3.isVisible(),
                "centre": not self.pages.isHidden(), "bottom": not self.bar.isHidden()}

    TAB_PANEL_PAGES = (3, 5)  # Lyrics and Radio

    TAB_SETUP_NAMES = {"5": "Radio", "3": "Lyrics"}

    def _on_tab_panel_page(self) -> bool:
        return hasattr(self, "pages") and self.pages.currentIndex() in self.TAB_PANEL_PAGES

    def _all_tab_setups(self) -> dict:
        try:
            d = json.loads(self.settings.value("tab_setup", "{}") or "{}")
        except (TypeError, ValueError):
            d = {}
        d = d if isinstance(d, dict) else {}
        if "left" in d or "top" in d:  # older settings shared one setup: give each tab a copy
            old = d
            if self.settings.contains("tab_panel_layout"):
                try:
                    old["right_state"] = json.loads(self.settings.value("tab_panel_layout"))
                except (TypeError, ValueError):
                    pass
            d = {"3": json.loads(json.dumps(old)), "5": json.loads(json.dumps(old))}
            self.settings.setValue("tab_setup", json.dumps(d))
            self.settings.remove("tab_panel_layout")
        return d

    def _tab_setup(self, key: str | None = None) -> dict:
        key = key or getattr(self, "_setup_key", None) or str(self.pages.currentIndex())
        d = self._all_tab_setups().get(key)
        d = d if isinstance(d, dict) else {}
        for k in ("left", "top"):
            if not isinstance(d.get(k), dict):
                d[k] = {"state": None, "visible": False}
        d.setdefault("right_visible", True)
        if not isinstance(d.get("right_state"), dict):
            d["right_state"] = None
        return d

    def _save_tab_setup(self, d: dict, key: str | None = None):
        key = key or getattr(self, "_setup_key", None)
        if not key:
            return
        allv = self._all_tab_setups()
        allv[key] = d
        self.settings.setValue("tab_setup", json.dumps(allv))

    def _blank_state(self) -> dict:
        from musicwell import layouts as L
        return L._blank_panel()

    def _layout_panel_state(self, p) -> dict:
        """A panel's layout contents (not the Radio/Lyrics contents it may be showing)."""
        saved = getattr(self, "_layout_states", None)
        if getattr(self, "_in_tab_setup", False) and saved:
            if p is saved.get("left_panel"):
                return saved["left"]
            if p is self.now3:
                return saved["top"]
        return p.state()

    def _enter_tab_setup(self):
        key = str(self.pages.currentIndex())
        if getattr(self, "_in_tab_setup", False):
            if key == self._setup_key:
                return
            self._keep_tab_panel_width()  # the tab you're leaving keeps its width
            left = self._layout_states["left_panel"]
        else:
            left = self.side_panels()["left"]
            self._layout_states = {"left_panel": left, "left": left.state(), "top": self.now3.state()}
            self._layout_widths = {w: sz for w, sz in zip([self.body.widget(i) for i in range(self.body.count())],
                                                          self.body.sizes())}
            self._in_tab_setup = True
        self._setup_key = key
        ts = self._tab_setup(key)
        left.restore_state(ts["left"].get("state") or self._blank_state())
        self.now3.restore_state(ts["top"].get("state") or self._blank_state())
        self.now4.restore_state(ts.get("right_state") or tab_panel_defaults())
        self._tab_setup_filled([left, self.now3])
        self._arrange_tab_sides()

    def _leave_tab_setup(self):
        if not getattr(self, "_in_tab_setup", False):
            return
        self._keep_tab_panel_width()
        self._in_tab_setup = False
        self._setup_key = None
        st = self._layout_states
        st["left_panel"].restore_state(st["left"])
        self.now3.restore_state(st["top"])
        self._layout_states = None
        self._tab_setup_filled([st["left_panel"], self.now3])
        self._apply_visualizer()
        if getattr(self, "_tab_reordered", False):
            self._layout_order_back()  # the layout's sides back

    def _tab_setup_filled(self, panels):
        """Panels just given new contents: fill their lists and start the visualizer."""
        for p in panels:
            self._fill_artist_list(p)
        self._refresh_panel_songs_soon()
        style = self.settings.value("visualizer", "bars")
        style = style if style != "off" else self.settings.value("visualizer_style", "bars")
        for p in panels + [self.now4]:
            if "visualizer" in p.order and (p is self.now4 or getattr(self, "_in_tab_setup", False)):
                p.set_block_hidden("visualizer", False)
                p.viz.set_style(style)
                p.viz.set_playing(self.player.is_playing())

    def _setup_panel_saved(self, p) -> bool:
        """A panel changed while showing the Radio or Lyrics contents: save it for that tab."""
        if not getattr(self, "_in_tab_setup", False):
            return False
        st = self._layout_states or {}
        if p is st.get("left_panel"):
            key = "left"
        elif p is self.now3:
            key = "top"
        else:
            return False
        ts = self._tab_setup()
        ts[key]["state"] = p.state()
        self._save_tab_setup(ts)
        return True

    def _save_tab_panel(self):
        """The right-hand panel changed: save it for the current tab."""
        if getattr(self, "_in_tab_setup", False) and not self.now4._restoring:
            ts = self._tab_setup()
            ts["right_state"] = self.now4.state()
            self._save_tab_setup(ts)

    def reset_tab_setup(self, key: str | None = None, quiet: bool = False):
        """Reset a tab's own panels (Radio "5", Lyrics "3", None = both)."""
        keys = [key] if key else ["3", "5"]
        allv = self._all_tab_setups()
        for k in keys:
            allv.pop(k, None)
            self.settings.remove(f"tab_panel_width_{k}")
        self.settings.setValue("tab_setup", json.dumps(allv))
        if getattr(self, "_in_tab_setup", False) and self._setup_key in keys:
            self._setup_key = None  # refill as it came
            self._enter_tab_setup()
            self._apply_tab_panels()
        if not quiet:
            what = " and ".join(self.TAB_SETUP_NAMES[k] for k in sorted(keys, reverse=True))
            self._flash(f"The {what} tab{'s' if len(keys) > 1 else ''}' panels are back as they came", 3000)

    def _reset_tab_panel(self):
        """Right-click the right-hand panel -> Reset."""
        self.reset_tab_setup(getattr(self, "_setup_key", None) or str(self.pages.currentIndex()))

    def _keep_tab_panel_width(self):
        key = getattr(self, "_setup_key", None)
        if key and self.now4.isVisible():
            w = self.body.sizes()[self.body.indexOf(self.now4)]
            if w >= 200:
                self.settings.setValue(f"tab_panel_width_{key}", w)

    def _show_tab_panel(self, on: bool):
        key = getattr(self, "_setup_key", None) or "5"
        if on:
            want = int(self.settings.value(f"tab_panel_width_{key}", self.settings.value("tab_panel_width", 330)))
            was = self.now4.isVisible()
            self.now4.setVisible(True)
            sizes = self.body.sizes()
            i4, ip = self.body.indexOf(self.now4), self.body.indexOf(self.middle)
            if not was or abs(sizes[i4] - want) > 4:
                total = sizes[i4] + sizes[ip]
                take = min(want, max(200, total - 400))
                sizes[i4], sizes[ip] = take, total - take
                self.body.setSizes(sizes)
        elif self.now4.isVisible():
            self._keep_tab_panel_width()
            self.now4.setVisible(False)
        self.now4.set_editing(getattr(self, "customizing", False) and on)

    def _toggle_tab_panel(self):
        self._show_tab_panel(not self.now4.isVisible())
        self._record_tab_panels()

    def _record_tab_panels(self):
        if getattr(self, "_applying_tab_panels", False) or not self.isVisible():
            return
        if self._on_tab_panel_page():  # Radio and Lyrics: kept for them
            if getattr(self, "_in_tab_setup", False) and self._setup_key == str(self.pages.currentIndex()):
                ts = self._tab_setup()
                ts["left"]["visible"] = self._layout_states["left_panel"].isVisible()
                ts["top"]["visible"] = self.now3.isVisible()
                ts["right_visible"] = self.now4.isVisible()
                self._save_tab_setup(ts)
            return
        key = self._current_tab_key()
        state = self._panels_now()
        if key == "0":  # Library tab: the panels every other tab starts with
            self.settings.setValue("panel_visible", state["left"])
            self.settings.setValue("panel2_visible", state["right"])
            self.settings.setValue("panel3_visible", state["top"])
            self.settings.setValue("centre_visible", state["centre"])
            self.settings.setValue("bar_visible", state["bottom"])
            return
        d = self._tab_panels()
        d[key] = state
        self.settings.setValue("panels_by_tab", json.dumps(d))

    def _library_panels(self) -> dict:
        s = self.settings
        return {"left": s.value("panel_visible", True, bool), "right": s.value("panel2_visible", False, bool),
                "top": s.value("panel3_visible", False, bool), "centre": s.value("centre_visible", True, bool),
                "bottom": s.value("bar_visible", True, bool)}

    def _apply_tab_panels(self, _index=None):
        """A tab opened: show its own panels, or the Library tab's."""
        if not hasattr(self, "now3") or not self.isVisible():
            return
        key = self._current_tab_key()
        want = self._tab_panels().get(key) if key != "0" else None
        want = dict(self._library_panels(), **want) if isinstance(want, dict) else self._library_panels()
        special = self._on_tab_panel_page()
        tab_panel = False
        if special:  # Radio / Lyrics
            self._enter_tab_setup()
            ts = self._tab_setup()
            left_is_main = self._layout_states["left_panel"] is self.now
            lv = bool(ts["left"].get("visible"))
            want = dict(want, left=lv and left_is_main, right=lv and not left_is_main,
                        top=bool(ts["top"].get("visible")), centre=True)
            tab_panel = bool(ts.get("right_visible", True))
        else:
            self._leave_tab_setup()
            self._show_tab_panel(False)
        if want == self._panels_now():
            if special:
                self._show_tab_panel(tab_panel)
            self._settle_body()
            return
        self._applying_tab_panels = True
        try:
            self.now.setVisible(bool(want.get("left", True)))
            if bool(want.get("right")) != self.now2.isVisible():
                self.set_panel2_visible(bool(want.get("right")), from_menu=True)
            if bool(want.get("top")) != self.now3.isVisible():
                self.set_panel3_visible(bool(want.get("top")))
            self.pages.setVisible(bool(want.get("centre", True)))
            self.bar.setVisible(bool(want.get("bottom", True)))
            if special:  # last, after the layout's panels are gone, so the page
                self._show_tab_panel(tab_panel)  # doesn't squeeze and jump
            self._refresh_bar()
            self._panels_follow_customizing()
        finally:
            self._applying_tab_panels = False
        self._settle_body()

    def _settle_body(self):
        """Share out the width before anything is drawn, so the page doesn't jump."""
        from PySide6.QtCore import QCoreApplication, QEvent
        QCoreApplication.sendPostedEvents(None, QEvent.LayoutRequest)
        self.body.refresh()
        QCoreApplication.sendPostedEvents(None, QEvent.LayoutRequest)

    def _same_panels_as_library(self):
        d = self._tab_panels()
        d.pop(self._current_tab_key(), None)
        self.settings.setValue("panels_by_tab", json.dumps(d))
        self._apply_tab_panels()

    def _panels_follow_customizing(self):
        """A panel shown while customizing opens for editing too."""
        if getattr(self, "customizing", False):
            self.now.set_editing(self.now.isVisible())
            self.now2.set_editing(self.now2.isVisible())
            self.now3.set_editing(self.now3.isVisible())
            self.now4.set_editing(self.now4.isVisible())

    def _panel_button(self):
        """The panels button is always a menu, so the second panel can be found."""
        m = QMenu(self)
        self._fill_panels_menu(m)
        m.exec(self._menu_pos(self.panel_btn))

    # Top, Centre, Bottom, Left and Right panels
    def side_panels(self) -> dict:
        """{"left": panel, "right": panel}"""
        side = self.settings.value("panel_side", "left")
        return {"left": self.now, "right": self.now2} if side == "left" else {"left": self.now2, "right": self.now}

    def five_panels(self) -> list:
        """(name, shown?, toggle, shortcut) for each panel."""
        sp = self.side_panels()

        def toggle_side(p):
            if p is self.now:
                return self._toggle_panel
            return lambda: self.set_panel2_visible(not self.now2.isVisible(), from_menu=True)
        key = {id(self.now): "F9", id(self.now2): "Shift+F9"}
        if self._on_tab_panel_page() and getattr(self, "_in_tab_setup", False):
            # Radio / Lyrics: their own panel plus the extra one
            extra = self._layout_states["left_panel"]
            mine = ("Right Panel", self.now4.isVisible(), self._toggle_tab_panel, "")
            other = ("Left Panel", extra.isVisible(), toggle_side(extra), key[id(extra)])
            if self._tab_setup().get("flipped"):
                mine, other = (("Left Panel",) + mine[1:]), (("Right Panel",) + other[1:])
            return [("Top Panel", self.now3.isVisible(), lambda: self.set_panel3_visible(not self.now3.isVisible()),
                     "Ctrl+F9"),
                    ("Centre Panel", not self.pages.isHidden(), lambda: self.set_centre_visible(self.pages.isHidden()), ""),
                    ("Bottom Panel", not self.bar.isHidden(), lambda: self.set_bar_visible(self.bar.isHidden()), ""),
                    *sorted([mine, other], key=lambda x: x[0])]
        return [("Top Panel", self.now3.isVisible(), lambda: self.set_panel3_visible(not self.now3.isVisible()),
                 "Ctrl+F9"),
                ("Centre Panel", not self.pages.isHidden(), lambda: self.set_centre_visible(self.pages.isHidden()), ""),
                ("Bottom Panel", not self.bar.isHidden(), lambda: self.set_bar_visible(self.bar.isHidden()), ""),
                ("Left Panel", sp["left"].isVisible(), toggle_side(sp["left"]), key[id(sp["left"])]),
                ("Right Panel", sp["right"].isVisible(), toggle_side(sp["right"]), key[id(sp["right"])])]

    def add_panel_items(self, m: QMenu):
        """Panel toggles, checked when showing."""
        tips = {"Top Panel": "A strip across the top of the window", "Centre Panel": "The tab you're on — the "
                "song list, albums, radio…", "Bottom Panel": "The play bar", "Left Panel": "A panel down the left",
                "Right Panel": "A panel down the right"}
        for name, on, fn, sc in self.five_panels():
            a = m.addAction(f"{name}\t{sc}" if sc else name, fn)
            a.setCheckable(True)
            a.setChecked(on)
            a.setToolTip(tips[name])
        m.setToolTipsVisible(True)

    def panels_submenu(self, m: QMenu):
        sub = m.addMenu("Panels")
        self.add_panel_items(sub)
        return sub

    def _fill_panels_menu(self, m: QMenu):
        """Panels menu: the five panels and their sides."""
        m.clear()
        self.add_panel_items(m)
        m.addSeparator()
        if self._current_tab_key() != "0" and self._current_tab_key() in self._tab_panels():
            m.addAction("Same panels as the Library tab (this tab has its own)", self._same_panels_as_library)
            m.addSeparator()
        side = self.settings.value("panel_side", "left")
        other = "right" if side == "left" else "left"
        m.addAction("Swap the Left and Right Panels",
                    lambda: (self.settings.setValue("panel_side", other), self._place_panel(other)))

    def set_centre_visible(self, on: bool):
        """Show or hide the centre panel (the tab pages)."""
        self.pages.setVisible(on)
        QTimer.singleShot(0, self._record_tab_panels)

    def set_bar_visible(self, on: bool):
        """Show or hide the play bar."""
        self.bar.setVisible(on)
        self.settings.setValue("bar_visible", on)
        QTimer.singleShot(0, self._record_tab_panels)

    def delete_under_mouse(self) -> bool:
        """Unlocked Delete: remove the item under the mouse."""
        from PySide6.QtGui import QCursor
        from musicwell.panel import PanelBlock
        from musicwell import bar as bar_mod
        w = QApplication.widgetAt(QCursor.pos())
        top = {id(x): k for x, k in self._top_keys.items()}
        while w is not None and w is not self:
            if isinstance(w, PanelBlock):
                w.panel.remove_block(w.key)
                self._flash(f"Removed “{w.name}” — right-click the panel → Add here to bring it back", 5000)
                return True
            if isinstance(w, bar_mod._Slot):
                name = bar_mod.item_name(w.key) if hasattr(bar_mod, "item_name") else w.key
                w.bar.remove_item(w.key)
                self._flash(f"Removed “{name}” from the play bar — right-click it → Add here to bring it back", 5000)
                return True
            if id(w) in top:
                self._hide_top(top[id(w)])
                return True
            if w in getattr(self, "nav_buttons", []):
                page = self.nav_buttons.index(w)
                if page == 0:
                    return False  # the Library tab always stays
                if page >= self.N_BUILTIN:
                    self.remove_custom_tab(page)
                else:
                    self.set_tab_hidden(page, True)
                return True
            w = w.parentWidget()
        return False

    def _window_menu(self, pos):
        """Right-click on empty window space: panels to add."""
        m = QMenu(self)
        head = m.addAction("Add a panel")
        head.setEnabled(False)
        self.add_panel_items(m)
        m.addSeparator()
        if getattr(self, "customizing", False):
            m.addAction("🔒  Lock (nothing moves)", lambda: self.set_customizing(False))
        else:
            m.addAction("🔓  Unlock to edit", lambda: self.set_customizing(True))
        m.exec(self.centralWidget().mapToGlobal(pos))

    def _layout_topbar(self, side: str):
        """Tabs on the left; search box, Layouts, panels and Settings on the right."""
        tl = self.top_layout
        while tl.count():
            tl.takeAt(0)
        self.panel_btn.icon_name = "panel" if side == "left" else "panel_right"
        for i in self.tab_order():
            tl.addWidget(self.nav_buttons[i])
        for i in self.MERGED:  # no tab of its own
            tl.addWidget(self.nav_buttons[i])
            self.nav_buttons[i].hide()
        tl.addWidget(self.more_tabs_btn)
        tl.addWidget(self.add_tab_btn)
        # song count / messages take the leftover room
        self.status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        tl.addSpacing(12)
        hidden = self.top_hidden()
        order = [k for k in self.top_order() if k not in hidden or k == "status"]
        if "status" in hidden:
            tl.addStretch(1)
        ready = hasattr(self, "bar")  # play bar and panel items come once the play bar exists
        order = [k for k in order if k in self.TOP_ITEMS or ready]
        for k, w in self._top_extras.items():
            if k not in order:
                w.hide()
        keys = [k[6:] for k in order if k.startswith("panel:")]
        if ready and (keys or self.now6 is not None):
            self._bar_source("now6").set_items(keys)
        for k in order:
            w = self.top_widget(k)
            if k not in self.TOP_ITEMS:
                tl.addWidget(w)
                w.show()
                continue
            if k == "status":
                tl.addWidget(w, 1)  # hidden: no song count, but messages still show
                tl.addSpacing(12)
            else:
                if k == "search":
                    tl.addSpacing(6)
                tl.addWidget(w)
                if k == "search":
                    tl.addSpacing(6)
            w.setVisible(k not in hidden or (k == "status" and bool(getattr(self, "_status_msg", ""))))
        for k in hidden:
            if k != "status":
                self.top_widget(k).hide()
        if hasattr(self, "theme"):
            self.panel_btn.apply(self.theme, color_key="muted")
            self.add_tab_btn.apply(self.theme, color_key="muted")

    # top bar buttons can be moved and hidden
    TOP_ITEMS = TOP_ITEMS
    TOP_DEFAULT = ["status", "search", "albums", "layouts", "panels", "settings"]
    TOP_DEFAULT_HIDDEN = ["albums"]  # All albums is in the artist list and the panels now

    def top_widget(self, key: str):
        if key in self.TOP_ITEMS:
            return {"status": self.status, "search": self.search, "albums": self.albums_btn,
                    "layouts": self.layout_btn, "panels": self.panel_btn, "settings": self.settings_btn}[key]
        w = self._top_extras.get(key)
        if w is None:  # a play bar control or a panel item put in the top bar
            w = self.bar.make_copy(key[4:]) if key.startswith("bar:") else BarItem(self._bar_source("now6"), key[6:])
            self._top_extras[key] = w
            for x in [w] + w.findChildren(QWidget):
                self._top_keys[x] = key
                x.installEventFilter(self)
                x.setMouseTracking(True)  # unlocked, the right edge resizes it
            self._size_top_item(key)
        return w

    TOP_WIDTHS = {"bar:seek": 320, "bar:volume": 110, "bar:time": 90}  # sizes to start with

    def top_sizes(self) -> dict:
        try:
            d = json.loads(self.settings.value("top_sizes", "{}") or "{}")
            return {k: int(v) for k, v in d.items() if isinstance(v, (int, float))} if isinstance(d, dict) else {}
        except (TypeError, ValueError):
            return {}

    def _top_resizable(self, key: str) -> bool:
        return key == "search" or key not in self.TOP_ITEMS

    def _size_top_item(self, key: str):
        w = self.top_widget(key)
        width = self.top_sizes().get(key)
        if isinstance(w, BarItem):
            w.set_size(width, None)
            return
        if width is None and key == "search":
            w.setMinimumWidth(0)
            w.setMaximumWidth(16777215)
            w.setMinimumWidth(190)
            return
        width = width or self.TOP_WIDTHS.get(key) or w.sizeHint().width()
        w.setFixedWidth(max(30, min(1200, width)))

    def set_top_width(self, key: str, width, save: bool = True):
        """Width of an item along the top (None: its own width)."""
        sizes = self.top_sizes()
        if width is None:
            sizes.pop(key, None)
        else:
            sizes[key] = int(max(30, min(1200, width)))
        self.settings.setValue("top_sizes", json.dumps(sizes))
        self._size_top_item(key)
        if save:
            self._layout_touched()
            QTimer.singleShot(0, self._check_tab_room)

    def _top_key_ok(self, key: str) -> bool:
        if key in self.TOP_ITEMS:
            return True
        if key.startswith("bar:"):
            return key[4:] in CONTROLS
        return key.startswith("panel:") and key[6:] in TOP_PANEL_ITEMS

    def top_item_name(self, key: str) -> str:
        if key in self.TOP_ITEMS:
            return self.TOP_ITEMS[key]
        return control_name(key[4:]) if key.startswith("bar:") else PANEL_ITEMS[key[6:]][0]

    def top_order(self) -> list[str]:
        try:
            v = [k for k in json.loads(self.settings.value("top_order", "[]") or "[]")
                 if isinstance(k, str) and self._top_key_ok(k)]
        except (TypeError, ValueError):
            v = []
        return v + [k for k in self.TOP_DEFAULT if k not in v]

    def top_hidden(self) -> list[str]:
        try:
            if not self.settings.value("top_albums_hidden", False, bool):  # once: the button went from the top bar
                self.settings.setValue("top_albums_hidden", True)
                hidden = json.loads(self.settings.value("top_hidden", "[]") or "[]")
                self.settings.setValue("top_hidden", json.dumps(list(dict.fromkeys(hidden + ["albums"]))))
            return [k for k in json.loads(self.settings.value("top_hidden", "[]") or "[]") if k in self.TOP_ITEMS]
        except (TypeError, ValueError):
            return []

    def set_top(self, order: list[str], hidden: list[str], sizes: dict | None = None):
        hidden = [k for k in hidden if k in self.TOP_ITEMS]
        if sizes is not None:
            self.settings.setValue("top_sizes", json.dumps(sizes))
            for k in list(self._top_extras) + ["search"]:
                self._size_top_item(k)
        self.settings.setValue("top_order", json.dumps(order))
        self.settings.setValue("top_hidden", json.dumps(hidden))
        self._layout_topbar(self.settings.value("panel_side", "left"))
        self._top_hand(getattr(self, "customizing", False))
        self._layout_touched()
        QTimer.singleShot(0, self._check_tab_room)  # tabs make room for what's been added

    def _top_hand(self, on: bool):
        from musicwell.widgets import set_hand
        if not on:
            for x in self._top_keys:  # the resize cursor may be left on a part of one
                if x is not self.search:
                    x.unsetCursor()
        for k in list(self.TOP_ITEMS) + list(self._top_extras):
            w = self.top_widget(k)
            if k == "search":
                w.setCursor(Qt.OpenHandCursor) if on else w.unsetCursor()
                continue
            set_hand(w, on)

    def _top_menu(self, gpos, key: str | None = None):
        """Right-click along the top: Unlock, or (unlocked) Remove, Add here, outlines, Lock."""
        m = QMenu(self)
        if not getattr(self, "customizing", False):
            self.panels_submenu(m)
            m.addSeparator()
            m.addAction("🔓  Unlock to edit", lambda: self.set_customizing(True))
            m.exec(gpos)
            return
        self.panels_submenu(m)
        m.addSeparator()
        if key:
            m.addAction(f"Remove “{self.top_item_name(key)}”", lambda: self._hide_top(key))
        hidden = self.top_hidden()
        add = m.addMenu("Add here")
        for k in hidden:
            add.addAction(self.TOP_ITEMS[k], lambda k=k: self._show_top(k, gpos))
        order = self.top_order()
        sub = add.addMenu("From the play bar")
        for k in CONTROLS:
            if "bar:" + k not in order:
                sub.addAction(control_name(k), lambda k=k: self._show_top("bar:" + k, gpos))
        sub = add.addMenu("From the panels")
        for k in TOP_PANEL_ITEMS:
            if "panel:" + k not in order:
                sub.addAction(PANEL_ITEMS[k][0], lambda k=k: self._show_top("panel:" + k, gpos))
        add.addSeparator()
        add.addAction("A tab…", self._show_add_tab_menu)
        m.addSeparator()
        o = m.addAction("Show outlines while unlocked", lambda: self.set_unlock_outlines(not self.unlock_outlines()))
        o.setCheckable(True)
        o.setChecked(self.unlock_outlines())
        m.addAction("Put the top bar back as it was",
                    lambda: self.set_top(list(self.TOP_DEFAULT), list(self.TOP_DEFAULT_HIDDEN), {}))
        m.addSeparator()
        m.addAction("🔒  Lock (nothing moves)", lambda: self.set_customizing(False))
        m.exec(gpos)

    def _hide_top(self, key: str):
        if key not in self.TOP_ITEMS:  # a play bar or panel item: just gone from here
            self.set_top([k for k in self.top_order() if k != key], self.top_hidden())
            return
        hidden = self.top_hidden() + [key]
        self.set_top(self.top_order(), hidden)
        what = self.TOP_ITEMS[key]
        self._flash(f"Removed the {what[0].lower() + what[1:]} — right-click the top bar → Add here to bring it back", 6000)

    def _show_top(self, key: str, gpos=None):
        order = [k for k in self.top_order() if k != key]
        order.insert(self._top_index(gpos, key) if gpos is not None else len(order), key)
        self.set_top(order, [k for k in self.top_hidden() if k != key])

    def _top_index(self, gpos, moving: str) -> int:
        """Index among the shown buttons (without `moving`) for a point."""
        order = [k for k in self.top_order() if k != moving]
        shown = [k for k in order if k not in self.top_hidden()]
        x = self.top_bar.mapFromGlobal(gpos).x()
        for k in shown:
            w = self.top_widget(k)
            if not w.isVisible():
                continue
            mid = w.mapTo(self.top_bar, w.rect().center()).x() if k != "status" else \
                w.mapTo(self.top_bar, w.rect().topRight()).x() - 40
            if x < mid:
                return order.index(k)
        return len(order)

    def _top_drag(self, key: str):
        """Drag a top bar button: drop along the top to move it, anywhere else to hide it."""
        from PySide6.QtCore import QRect
        from musicwell.widgets import MoveSession, drag_label
        session = None
        bar = self.top_bar

        panels = [p for p in self.panels if p.isVisible() and p.editing]
        play_bar = self.bar if self.bar.isVisible() and self.bar.editing else None

        def panel_at(g):
            return next((p for p in panels if p.rect().contains(p.mapFromGlobal(g))), None)

        def move(g):
            if session is None:
                return
            for p in panels:
                p._hide_indicator()
            p = panel_at(g)
            if p is not None:
                p._show_indicator(p.body.mapFromGlobal(g))
            if play_bar is not None:
                play_bar.show_drop_at(g)
            if bar.rect().contains(bar.mapFromGlobal(g)):
                order = [k for k in self.top_order() if k != key]
                i = self._top_index(g, key)
                shown = [k for k in order[i:] if k not in self.top_hidden()]
                if shown:
                    w = self.top_widget(shown[0])
                    x = w.mapTo(self, w.rect().topLeft()).x() - 3
                    if shown[0] == "status":
                        x = w.mapTo(self, w.rect().topRight()).x() - 6
                else:
                    x = bar.mapTo(self, bar.rect().topRight()).x() - 14
                y = bar.mapTo(self, bar.rect().topLeft()).y()
                session.hint = QRect(x - 2, y + 6, 6, bar.height() - 12)
            else:
                session.hint = None

        def done():
            for p in panels:
                p._hide_indicator()
            if play_bar is not None:
                play_bar.show_drop_at(None)
                play_bar._show_empty_zones(False)

        def drop(g):
            done()
            p = panel_at(g)
            if bar.rect().contains(bar.mapFromGlobal(g)):
                order = [k for k in self.top_order() if k != key]
                order.insert(self._top_index(g, key), key)
                self.set_top(order, self.top_hidden())
            elif p is not None or (play_bar is not None and play_bar.zone_at(g)):
                own = key in self.TOP_ITEMS
                if p is not None:
                    p._drop("top:" + key if own else key if key.startswith("bar:") else key[6:],
                            p.body.mapFromGlobal(g))
                else:
                    play_bar.drop_from_panel("top:" + key if own else key[4:] if key.startswith("bar:") else key, g)
                if own:
                    self.set_top(self.top_order(), self.top_hidden() + [key])  # moved, so not here any more
                else:
                    self.set_top([k for k in self.top_order() if k != key], self.top_hidden())
            else:
                self._hide_top(key)

        w = self.top_widget(key)
        if play_bar is not None:
            play_bar._show_empty_zones(True)
        session = MoveSession(w, drag_label(self.top_item_name(key), self.theme, w.grab() if key != "status" else None),
                              move, drop, done, self.theme)
        move(self.cursor().pos())

    def unlock_outlines(self) -> bool:
        return self.settings.value("unlock_outlines", True, bool)

    def set_unlock_outlines(self, on: bool):
        self.settings.setValue("unlock_outlines", on)
        self.bar.outlines = on
        for p in self.panels:
            p.outlines = on
        if getattr(self, "customizing", False):
            self.bar.set_editing(True)
            self.bar._rebuild()
            for p in self.panels:
                if p.isVisible():
                    p._rebuild()

    def _radio_is_break(self, text: str, st, sends_songs: bool = False) -> bool:
        """Advert, jingle, station ID, news... kept out of the radio stats."""
        from musicwell import radio as R
        d = self.ad_dimmer
        if R._plain(text) in {R._plain(x) for x in d.not_ads(st)}:
            return False
        return R.not_a_song(text, st, d.marked(st), sends_songs)

    def _radio_not_a_song(self, artist: str, title: str):
        """Stats -> Not a song: remove from radio stats and mark as an advert on that station."""
        for uuid, text in self.radio_log.forget(artist, title):
            if text:
                self.ad_dimmer._mark("radio_not_ads", {"uuid": uuid}, text, False)
                self.ad_dimmer._mark("radio_ad_titles", {"uuid": uuid}, text, True)
        self._flash(f"“{title}” is no longer counted as a song", 4000)

    def set_bold_headers(self, on: bool):
        self.settings.setValue("bold_headers", on)
        self.theme.bold_headers = on
        self.apply_theme()

    def set_panel3_visible(self, on: bool):
        """Show or hide the top panel."""
        self.now3.setVisible(on)
        self._layout_touched()
        QTimer.singleShot(0, self._record_tab_panels)
        if on:
            sizes = self.middle.sizes()
            i3, ip = self.middle.indexOf(self.now3), self.middle.indexOf(self.pages)
            if sizes[i3] < 100:
                take = min(int(self.settings.value("panel3_height", 170)), max(0, sizes[ip] - 250))
                sizes[i3], sizes[ip] = take, sizes[ip] - take
                self.middle.setSizes(sizes)
        QTimer.singleShot(0, self._panels_follow_customizing)

    def _place_strip(self, where: str):
        """Place the strip panel above or below the pages."""
        where = "top"  # the top panel no longer moves to the bottom
        self.settings.setValue("panel3_where", where)
        sizes = dict(zip([self.middle.widget(i) for i in range(self.middle.count())], self.middle.sizes()))
        order = (self.now3, self.pages) if where == "top" else (self.pages, self.now3)
        for i, w in enumerate(order):
            self.middle.insertWidget(i, w)
        for w in order:
            self.middle.setStretchFactor(self.middle.indexOf(w), 1 if w is self.pages else 0)
        if sizes and all(sizes.get(w, 0) > 0 for w in order):
            self.middle.setSizes([sizes[w] for w in order])

    def _move_panel(self, panel, where):
        """Move a panel to a side (global point) or swap (None)."""
        if panel is self.now3:  # the top panel stays at the top
            return
        if getattr(self, "_in_tab_setup", False) and self._on_tab_panel_page():
            # Radio / Lyrics: their panels swap sides for that tab only
            ts = self._tab_setup()
            if where is None:
                flipped = not ts.get("flipped", False)
            else:
                target = "left" if self.mapFromGlobal(where).x() < self.width() / 2 else "right"
                flipped = (target == "left") if panel is self.now4 else (target == "right")
            if flipped != bool(ts.get("flipped", False)):
                ts["flipped"] = flipped
                self._save_tab_setup(ts)
                self._arrange_tab_sides()
                self._flash(f"The panel is on the {'left' if flipped == (panel is self.now4) else 'right'} now", 2500)
            return
        if panel is getattr(self, "now4", None):
            return
        side = self.settings.value("panel_side", "left")
        other = "right" if side == "left" else "left"
        if where is None:
            new = other
        else:
            target = "left" if self.mapFromGlobal(where).x() < self.width() / 2 else "right"
            new = target if panel is self.now else ("right" if target == "left" else "left")
        if new != side:
            self.settings.setValue("panel_side", new)
            self._place_panel(new)
            self._flash(f"The panel is on the {new} now", 2500)

    def _layout_order_back(self):
        """Restore the layout's panel order, keeping widths."""
        self._tab_reordered = False
        sizes = getattr(self, "_sizes_before_tab", None) or {}
        side = self.settings.value("panel_side", "left")
        order = (self.now, self.middle, self.now2) if side == "left" else (self.now2, self.middle, self.now)
        order += (self.now4,)
        cur = {w: sz for w, sz in zip([self.body.widget(i) for i in range(self.body.count())], self.body.sizes())}
        for i, w in enumerate(order):
            self.body.insertWidget(i, w)
        for w in order:
            self.body.setStretchFactor(self.body.indexOf(w), 1 if w is self.middle else 0)
        self.body.setSizes([sizes.get(w) or cur.get(w, 0) if w is not self.now4 else cur.get(w, 0) for w in order])

    def _arrange_tab_sides(self):
        """Radio / Lyrics: their own panel on the right (or left if moved), the extra one opposite."""
        if not getattr(self, "_in_tab_setup", False):
            return
        extra = self._layout_states["left_panel"]
        rest = self.now2 if extra is self.now else self.now
        flipped = bool(self._tab_setup().get("flipped", False))
        if not flipped:
            if getattr(self, "_tab_reordered", False):
                self._layout_order_back()
            return
        order = (self.now4, rest, self.middle, extra)
        sizes = {w: sz for w, sz in zip([self.body.widget(i) for i in range(self.body.count())], self.body.sizes())}
        if not getattr(self, "_tab_reordered", False):
            self._sizes_before_tab = dict(self._layout_widths)
        self._tab_reordered = True
        for i, w in enumerate(order):
            self.body.insertWidget(i, w)
        for w in order:
            self.body.setStretchFactor(self.body.indexOf(w), 1 if w is self.middle else 0)
        if sizes:
            self.body.setSizes([sizes.get(w, 0) for w in order])

    def _place_panel(self, side: str):
        """The panel on its chosen side; the second panel opposite."""
        self._layout_topbar(side)
        order = (self.now, self.middle, self.now2) if side == "left" else (self.now2, self.middle, self.now)
        order += (self.now4,)  # the Radio/Lyrics panel is always on the right
        sizes = {w: sz for w, sz in zip([self.body.widget(i) for i in range(self.body.count())], self.body.sizes())}
        for i, w in enumerate(order):
            self.body.insertWidget(i, w)
        for w in order:
            self.body.setStretchFactor(self.body.indexOf(w), 1 if w is self.middle else 0)
        # keep each area's width as it moves
        if sizes and all(sizes.get(w, 0) > 0 for w in order if w.isVisibleTo(self)):
            self.body.setSizes([sizes.get(w, 0) for w in order])

    def _maybe_welcome(self, tries: int = 0):
        if self.settings.value("welcome_hide", False, bool) or os.environ.get("MUSICWELL_NO_WELCOME"):
            return
        if not self.isVisible():  # started in the tray
            if tries < 40:
                QTimer.singleShot(500, lambda: self._maybe_welcome(tries + 1))
            return
        self.open_welcome()

    def open_welcome(self):
        """The welcome window: add music, choose a layout and theme."""
        from musicwell.welcome import WelcomeDialog
        if getattr(self, "_welcome", None) is not None and self._welcome.isVisible():
            self._welcome.raise_()
            self._welcome.activateWindow()
            return
        self._welcome = WelcomeDialog(self)
        self._welcome.setAttribute(Qt.WA_DeleteOnClose)
        self._welcome.destroyed.connect(lambda *_: setattr(self, "_welcome", None))
        self._welcome.open()

    def open_about(self):
        from musicwell.about import AboutDialog
        if getattr(self, "_about", None) is not None and self._about.isVisible():
            self._about.raise_()
            self._about.activateWindow()
            return
        self._about = AboutDialog(self)
        self._about.show()

    def _open_settings(self, page: str | None = None):
        dlg = SettingsDialog(self)
        if page:
            dlg.show_page(page)
        if dlg.exec():
            self.apply_settings()

    def apply_settings(self):
        """Apply the settings. Each part is applied separately so one failure doesn't stop the rest."""
        s = self.settings

        def decades():
            from musicwell import library as library_mod
            src, tag = s.value("decade_from", "year") or "year", s.value("original_year_tag", "") or ""
            if src != library_mod.DECADE_FROM or tag != library_mod.ORIGINAL_YEAR_TAG:
                self.library.set_decade_source(src, tag)

        def similar():
            self.finder.online = s.value("similar_online", True, bool)
            self.finder.archive = s.value("similar_archive", True, bool)
            self.finder.openverse = s.value("similar_openverse", True, bool)
            self.finder.audius = s.value("similar_audius", True, bool)
            self.similar_page.sources = self._free_sources()
            self.online_page.free.sources = self._free_sources()
            self.similar_page.free.sources = self._free_sources()
            self.online_strip.panel.sources = self._free_sources()
            self.finder.station_limit = int(s.value("similar_station_count", 40))

        def cast():
            c = self.cast_ctl
            if c:
                c.chrome_on = s.value("cast_discovery", True, bool)
                c.sonos_on = s.value("sonos_discovery", True, bool)
                c.set_sonos_addresses(s.value("sonos_addresses", "") or "")
                if not c.chrome_on and c.chrome and not (c.active is c.chrome):
                    c.chrome.stop_discovery()
                c.port = int(s.value("cast_port", cast_mod.DEFAULT_PORT))
                if c.sonos:
                    c.sonos._last_discovery = 0.0  # search again with the new address
                c.start_discovery()

        def look():
            self.theme.bold_headers = s.value("bold_headers", False, bool)
            self.apply_theme()
            if self.player.current:
                self.now.header.refresh_theme()
        steps = [("decades", decades), ("shortcuts", self.apply_shortcuts), ("theme", self._apply_theme_settings),
                 ("images", lambda: self.images.configure(s)), ("lyrics", lambda: self.lyrics.configure(s)),
                 ("fades", lambda: self._apply_fade_settings(s)), ("find similar", similar),
                 ("artist photo", lambda: self.now.header.set_fit(s.value("artist_photo_fit", "whole"))),
                 ("panel side", lambda: self._place_panel(s.value("panel_side", "left"))),
                 ("visualizer", self._apply_visualizer), ("desktop", lambda: self._apply_desktop_settings(s)),
                 ("volume levelling", lambda: self._apply_replaygain_settings(s)), ("casting", cast),
                 ("artist info", lambda: (self.artist_info.forget_all(),
                                          [v.show_info("", {}) for v in self._info_views()],
                                          self._request_artist_info(self.player.current))),
                 ("song list", self._refilter), ("look", look), ("playing song", self._apply_playing_style),
                 ("radio adverts", lambda: self.ad_dimmer.settings_changed()),
                 ("song alerts", lambda: self.song_alerts.apply_settings()),
                 ("radio list", lambda: self.radio_page.list.viewport().update()),
                 ("search", self.apply_search_settings)]
        failed = []
        for name, step in steps:
            try:
                step()
            except Exception:
                import traceback
                from musicwell.paths import log_error
                log_error(f"Settings — {name}:\n" + traceback.format_exc())
                failed.append(name)
        if failed:
            self._flash(f"Some settings couldn't be applied ({', '.join(failed)}) — see About → System")

    def _apply_fade_settings(self, s=None):
        s = s or self.settings
        self.player.configure_fades(int(float(s.value("fade_in", 0)) * 1000),
                                    int(float(s.value("fade_out", 0)) * 1000),
                                    s.value("fade_within_album", False, bool),
                                    int(s.value("fade_transport", 0)))

    def _apply_theme_settings(self):
        self.update_colours(force=False)

    def set_theme(self, key: str):
        """Switch theme from the Layouts menu; a fixed accent becomes the theme's own."""
        if key not in th.PALETTES:
            return
        s = self.settings
        s.setValue("theme", key)
        s.setValue("accent", th.PALETTES[key]["accent"])
        self.update_colours(force=True)
        self._flash(f"Theme: {th.PALETTES[key]['name']}", 2500)

    def _layouts_menu(self):
        from musicwell.layoutui import fill_menu
        m = QMenu(self)
        fill_menu(m, self)
        m.exec(self._menu_pos(self.layout_btn))

    def use_layout(self, name: str, quiet: bool = False, keep_changes: bool = True):
        from musicwell import layouts as L
        from musicwell import log as mwlog
        mwlog.log.info("Layout: %s", name)
        d, _builtin, _changed = L.effective(self.settings, name)
        if d is None:
            if not quiet:
                self._flash(f"There's no layout called “{name}” any more", 4000)
            return
        if getattr(self, "customizing", False):
            self.set_customizing(False)  # lock first: a new layout always starts locked
        if keep_changes:
            self._remember_layout_changes()  # remember changes to the layout you're leaving
        self._keep_layout_heights()
        if _builtin and name in L.OLD_NAMES:
            name = L.OLD_NAMES[name]  # old built-in name
        self._applying = True
        try:
            L.apply(self, d)
        finally:
            self._applying = False
        self.settings.setValue("layout_current", name)
        if keep_changes:
            self._restore_layout_heights(name)
        self._snap_layout_soon()
        QTimer.singleShot(400, lambda: self._record_layout(fresh=True))  # undo starts again from here
        QTimer.singleShot(150, self._jump_to_playing)  # Artists / Albums: go to what's playing
        QTimer.singleShot(900, self._jump_to_playing)  # again once big lists have filled
        if name == "Empty":  # Empty opens unlocked
            self.set_customizing(True)
            if not quiet:
                self._flash("Empty — right-click the window to add panels, then right-click a panel → Add here to "
                            f"fill it. Press {self._lock_keys(False)} when you're done (and Layouts → Save and manage layouts → Save current layout as… to keep it).",
                            12000)
            return
        if not quiet:
            self._flash(f"Layout: {name}", 3000)

    # Undo / redo for moving items about: snapshots of the panels, the play bar and the top bar
    def _layout_snapshot(self) -> dict:
        snap = {"where": self._setup_key if getattr(self, "_in_tab_setup", False) else "",
                "panels": [p.state() for p in (self.now, self.now2, self.now3, self.now4)],
                "bar": self.bar.state(), "top": [self.top_order(), self.top_hidden(), self.top_sizes()],
                "shown": {"tab": self._current_tab_key(), "panels": [not self.now.isHidden(), not self.now2.isHidden(),
                                                                     not self.now3.isHidden()],
                          "browser": self.browser_visible()},
                "sizes": {"side": [self.now.width(), self.now2.width()], "top": self.now3.height(),
                          "browser": self.lib_split.sizes()[0] if self.lib_split.sizes() else 0},
                "columns": {key: t.column_state() for key, t in self._column_tables()}}
        return json.loads(json.dumps(snap))  # a copy: state() hands back the live lists

    def _layout_touched(self):
        timer = getattr(self, "_undo_timer", None)  # None while the window is being built
        if timer and not (getattr(self, "_applying", False) or getattr(self, "_applying_tab_panels", False)
                          or getattr(self, "_putting_back", False)):
            timer.start()

    def _record_layout(self, fresh: bool = False):
        snap = self._layout_snapshot()
        if fresh or self._undo_last is None or snap["where"] != self._undo_last["where"]:
            self._undo.clear()  # another layout, or the Radio / Lyrics tab's own panels
            self._redo.clear()
        elif snap != self._undo_last:
            self._undo.append(self._undo_last)
            del self._undo[:-50]
            self._redo.clear()
        self._undo_last = snap

    def undo_layout(self):
        self._step_layout(self._undo, self._redo, "Undone", "Nothing to undo")

    def redo_layout(self):
        self._step_layout(self._redo, self._undo, "Redone", "Nothing to redo")

    def _step_layout(self, take: list, give: list, done: str, nothing: str):
        if self._undo_timer.isActive():  # a change not recorded yet
            self._undo_timer.stop()
            self._record_layout()
        if not take:
            self._flash(nothing, 2000)
            return
        give.append(self._undo_last)
        self._put_layout(take.pop())
        self._flash(done, 1500)

    def _put_layout(self, snap: dict):
        self._putting_back = True
        try:
            for p, state in zip((self.now, self.now2, self.now3, self.now4), snap["panels"]):
                p.restore_state(state)
                if getattr(self, "customizing", False) and p.isVisible():
                    p.set_editing(True)
            self._save_panel_layout()
            self._save_panel2_layout()
            self._save_panel3_layout()
            self._save_tab_panel()
            self.bar.restore_state(snap["bar"])
            self._save_bar_layout()
            self.set_top(*snap["top"])
            for p in self.panels:
                self._fill_artist_list(p)
            self._apply_visualizer()
            self._put_back_panels(snap)
        finally:
            self._putting_back = False
        self._undo_last = self._layout_snapshot()

    def _put_back_panels(self, snap: dict):
        """Panels shown or hidden, their sizes, and the song list columns, as in a snapshot."""
        shown = snap.get("shown") or {}
        if shown.get("tab") == self._current_tab_key():  # each tab has its own panels
            on = shown.get("panels") or []
            if len(on) == 3:
                if on[0] != (not self.now.isHidden()):
                    self._toggle_panel()
                if on[1] != (not self.now2.isHidden()):
                    self.set_panel2_visible(on[1])
                if on[2] != (not self.now3.isHidden()):
                    self.set_panel3_visible(on[2])
            if shown.get("browser") != self.browser_visible():
                self.set_browser(self.browser.fields(), bool(shown.get("browser")))
        sizes = snap.get("sizes") or {}
        side = sizes.get("side") or []
        if len(side) == 2:
            new = self.body.sizes()
            for w, want in zip((self.now, self.now2), side):
                i, ip = self.body.indexOf(w), self.body.indexOf(self.middle)
                if not w.isHidden() and want > 0 and i >= 0 and ip >= 0:
                    new[ip] += new[i] - want
                    new[i] = want
            self.body.setSizes(new)
        if sizes.get("top") and not self.now3.isHidden():
            new = self.middle.sizes()
            i3, ip = self.middle.indexOf(self.now3), self.middle.indexOf(self.pages)
            new[ip] += new[i3] - sizes["top"]
            new[i3] = sizes["top"]
            self.middle.setSizes(new)
        if sizes.get("browser") and self.browser_visible():
            total = sum(self.lib_split.sizes())
            self.lib_split.setSizes([sizes["browser"], max(120, total - sizes["browser"])])
        for key, t in self._column_tables():
            state = (snap.get("columns") or {}).get(key)
            if state and state != t.column_state():
                t.restore_column_state(state)
        self._save_columns()

    # changes to a layout are remembered per layout
    def _snap_layout_soon(self, ms: int = 1500):
        """Snapshot the layout once settled, as the "unchanged" reference."""
        self.settings.setValue("layout_baseline", json.dumps({"name": ""}))
        self._snap_token = getattr(self, "_snap_token", 0) + 1
        tok, name = self._snap_token, self.settings.value("layout_current", "")
        QTimer.singleShot(ms, lambda: tok == self._snap_token and
                          self.settings.value("layout_current", "") == name and self._snap_layout())

    def _snap_layout(self):
        from musicwell import layouts as L
        name = self.settings.value("layout_current", "")
        if name:
            self.settings.setValue("layout_baseline", json.dumps({"name": name,
                                                                  "print": L.fingerprint(L.capture(self))}))

    def _layout_changed_now(self) -> bool:
        """Has the current layout changed since it was applied?"""
        from musicwell import layouts as L
        name = self.settings.value("layout_current", "")
        try:
            base = json.loads(self.settings.value("layout_baseline", "{}") or "{}")
        except (TypeError, ValueError):
            base = {}
        if not name or not isinstance(base, dict) or base.get("name") != name:
            return False
        return L.fingerprint(L.capture(self)) != base.get("print")

    # keep the song list height under the browser, covers or artist
    def _keep_layout_heights(self):
        name = self.settings.value("layout_current", "")
        if not name:
            return
        try:
            d = json.loads(self.settings.value("layout_heights", "{}") or "{}")
        except (TypeError, ValueError):
            d = {}
        d = d if isinstance(d, dict) else {}
        d[name] = {"lib": self.lib_split.sizes(), "albums": self.albums_page.split.sizes(),
                   "artist": self.artist_page.split.sizes()}
        self.settings.setValue("layout_heights", json.dumps(d))

    def _forget_layout_heights(self, name: str):
        try:
            d = json.loads(self.settings.value("layout_heights", "{}") or "{}")
        except (TypeError, ValueError):
            d = {}
        if isinstance(d, dict) and d.pop(name, None) is not None:
            self.settings.setValue("layout_heights", json.dumps(d))

    def _restore_layout_heights(self, name: str):
        try:
            d = json.loads(self.settings.value("layout_heights", "{}") or "{}").get(name)
        except (TypeError, ValueError, AttributeError):
            d = None
        if not isinstance(d, dict):
            return
        for key, sp in (("lib", self.lib_split), ("albums", self.albums_page.split),
                        ("artist", self.artist_page.split)):
            sizes = d.get(key)
            if not (isinstance(sizes, list) and len(sizes) == sp.count() and sum(sizes) > 0):
                continue
            if key == "lib" and self.browser.isHidden():
                continue  # no browser in this layout
            if key == "lib" and sizes[0] <= 0:
                continue
            sp.setSizes([int(x) for x in sizes])

    def _remember_layout_changes(self):
        from musicwell import layouts as L
        name = self.settings.value("layout_current", "")
        if not name or name == "Empty" or not self._layout_changed_now():
            return
        _d, builtin = L.find(self.settings, name)
        if _d is None:
            return
        user = L.load_user(self.settings)
        if name in user and user[name].get("scratch"):
            return  # one you're building is saved as itself
        ch = L.load_changes(self.settings)
        ch[name] = L.kept_changes(L.capture(self))
        L.save_changes(self.settings, ch)
        self._snap_layout()

    def layout_has_changes(self, name: str) -> bool:
        from musicwell import layouts as L
        if name == self.settings.value("layout_current", "") and self._layout_changed_now():
            return True
        return name in L.load_changes(self.settings)

    def reset_layout(self, name: str):
        """Reset a layout, forgetting your changes."""
        from musicwell import layouts as L
        ch = L.load_changes(self.settings)
        ch.pop(name, None)
        L.save_changes(self.settings, ch)
        self._forget_layout_heights(name)
        if name == self.settings.value("layout_current", ""):
            self.use_layout(name, quiet=True, keep_changes=False)
            self._forget_layout_heights(name)
        self._flash(f"“{name}” is back as it came", 3000)

    def reset_all_layouts(self):
        from musicwell import layouts as L
        if QMessageBox.question(self, "Reset every layout",
                                "Put every layout back as it came, and the Radio and Lyrics tabs' panels too?\n\n"
                                "(Layouts you saved yourself go back to how you saved them.)") != QMessageBox.Yes:
            return
        L.save_changes(self.settings, {})
        self.settings.remove("layout_heights")
        self.reset_tab_setup(quiet=True)
        cur = self.settings.value("layout_current", "")
        if cur:
            self.use_layout(cur, quiet=True, keep_changes=False)
        self._flash("Every layout is back as it came", 3000)

    def _layout_by_number(self, n: int):
        from musicwell import layouts as L
        presets = L.all_presets(self.settings)
        if n <= len(presets):
            self.use_layout(presets[n - 1][0])

    def save_layout_as(self) -> str | None:
        from musicwell import layouts as L
        from musicwell.layoutui import SaveLayoutDialog
        cur = self.settings.value("layout_current", "")
        dlg = SaveLayoutDialog(self, "" if cur in L.BUILTIN else cur)
        if not dlg.exec():
            return None
        name = dlg.name.text().strip()
        d = L.capture(self, include_theme=dlg.colours.isChecked())
        d["description"] = dlg.desc.text().strip()
        user = L.load_user(self.settings)
        user[name] = d
        L.save_user(self.settings, user)
        self._forget_changes(name)
        self.settings.setValue("layout_current", name)
        self._snap_layout()
        self._flash(f"Saved the layout “{name}”", 3000)
        return name

    def new_empty_layout(self) -> str | None:
        """A blank layout to build: name it, then customize. Locking saves it."""
        from musicwell import layouts as L
        from musicwell.layoutui import SaveLayoutDialog
        dlg = SaveLayoutDialog(self, "My layout")
        dlg.setWindowTitle("New empty layout")
        dlg.intro.setText("A completely empty window — no panels, nothing in the play bar, no song columns — to build "
                          "your own layout in. It opens unlocked: right-click → Add here, and Panels (top right) for "
                          f"the panels. Press {self._lock_keys(False)} (or Layouts → Lock) and it's saved under this name.")
        if not dlg.exec():
            return None
        name = dlg.name.text().strip()
        L.apply(self, L.empty())
        d = L.capture(self, include_theme=dlg.colours.isChecked())
        d["description"] = dlg.desc.text().strip() or "Built from scratch"
        d["scratch"] = True
        user = L.load_user(self.settings)
        user[name] = d
        L.save_user(self.settings, user)
        self._forget_changes(name)
        self.settings.setValue("layout_current", name)
        self._snap_layout()
        self.set_customizing(True)
        self._flash(f"“{name}”: an empty layout, unlocked. Panels (top right) for the panels, right-click the play bar "
                    f"or a panel → Add here, right-click the song area → Columns — press {self._lock_keys(False)} (or Layouts → Lock) to save it.", 14000)
        return name

    def _save_scratch_layout(self):
        """Locked after building a layout from scratch: save it."""
        from musicwell import layouts as L
        name = self.settings.value("layout_current", "")
        user = L.load_user(self.settings)
        if name in user and user[name].get("scratch"):
            old = user[name]
            d = L.capture(self, include_theme="theme" in old)
            d["description"], d["scratch"] = old.get("description", ""), True
            user[name] = d
            L.save_user(self.settings, user)
            self._flash(f"Saved the layout “{name}”", 3000)

    def update_layout(self, name: str):
        from musicwell import layouts as L
        user = L.load_user(self.settings)
        if name not in user:
            return
        old = user[name]
        d = L.capture(self, include_theme="theme" in old)
        d["description"] = old.get("description", "")
        user[name] = d
        L.save_user(self.settings, user)
        self._forget_changes(name)
        self.settings.setValue("layout_current", name)
        self._snap_layout()
        self._flash(f"Updated the layout “{name}”", 3000)

    def layout_renamed(self, old: str, new: str):
        """A layout was renamed: its tab keeps working."""
        hit = False
        for sp in self.custom_specs:
            if sp.get("kind") == "layout" and sp.get("layout") == old:
                sp["layout"] = new
                if sp.get("name") == old:
                    sp["name"] = new
                hit = True
        if hit:
            self._save_custom_tabs()
            self._build_custom_tabs()

    def _forget_changes(self, name: str):
        from musicwell import layouts as L
        ch = L.load_changes(self.settings)
        if ch.pop(name, None) is not None:
            L.save_changes(self.settings, ch)

    def manage_layouts(self):
        from musicwell.layoutui import ManageLayoutsDialog
        ManageLayoutsDialog(self).exec()

    def browser_visible(self) -> bool:
        return not self.browser.isHidden()

    def set_browser(self, fields: list[str], visible: bool):
        if fields != self.browser.fields():
            self.browser.set_fields(fields)
        self.browser.setVisible(visible)
        self._layout_touched()
        self.settings.setValue("pane_fields", json.dumps(self.browser.fields()))
        self.settings.setValue("browser_visible", visible)
        if not visible:
            # a hidden browser shouldn't filter the list
            self.browser.reset()

    def _custom_fields_for_browser(self) -> list[str]:
        """Custom fields from the browser's column editor; returns the new field key."""
        from musicwell import fields as F
        from musicwell.dialogs import CustomFieldsDialog
        before = {f.key for f in F.custom_fields()}
        CustomFieldsDialog(self).exec()
        return [f.key for f in F.custom_fields() if f.key not in before]

    def _edit_browser_columns(self):
        dlg = BrowserColumnsDialog(self.browser.fields(), self.browser_visible(), self,
                                   add_custom=self._custom_fields_for_browser)
        if dlg.exec():
            self.set_browser(dlg.result_fields(), dlg.visible.isChecked())

    def _saved_pane_fields(self) -> list[str]:
        s = self.settings
        try:
            fields = json.loads(s.value("pane_fields", "null"))
        except (TypeError, ValueError):
            fields = None
        if not fields and s.value("panes"):  # setting from the first version
            old = {"Genre | Artist | Album": "Genre | Album artist | Album",
                   "Artist | Album": "Album artist | Album",
                   "Year | Artist | Album": "Year | Album artist | Album",
                   "Genre | Year | Artist | Album": "Genre | Year | Album artist | Album"}
            fields = PANE_PRESETS.get(old.get(s.value("panes"), s.value("panes")))
        fields = [f for f in (fields or []) if f in PANE_FIELDS]
        return fields or list(DEFAULT_PANES)

    def _column_tables(self):
        return (("columns_library", self.table), ("columns_queue", self.queue_table),
                ("columns_playlist", self.pl_table))

    def _save_columns(self):
        for key, t in self._column_tables():
            self.settings.setValue(key, json.dumps(t.column_state()))

    def _add_custom_field(self) -> str | None:
        dlg = CustomFieldDialog(self.library.tag_counts(), self)
        if not dlg.exec():
            return None
        d = dlg.definition()
        F.set_custom(F.custom_defs() + [d])
        F.save_custom(self.settings)
        self._fields_changed()
        self._flash(f"Added the “{d['name']}” column", 4000)
        return F.custom_key(d["tag"])

    def _add_custom_column(self, table):
        key = self._add_custom_field()
        if key:
            table.show_column(key)

    def _remove_custom_field(self, key: str):
        f = F.get(key)
        if f is None:
            return
        F.set_custom([d for d in F.custom_defs() if F.custom_key(d["tag"]) != key])
        F.save_custom(self.settings)
        if key in self.browser.fields():
            self.set_browser([k for k in self.browser.fields() if k != key], self.browser_visible())
        self._fields_changed()

    def manage_custom_fields(self, table=None):
        """Add, rename or delete custom fields."""
        from musicwell.dialogs import CustomFieldsDialog
        CustomFieldsDialog(self, table=table).exec()

    def rename_column(self, key: str):
        """Rename a column."""
        f = F.get(key)
        if f is None:
            return
        orig = f.name if f.custom else F.original_name(key)
        hint = "" if f.custom else (f"\n\nLeave it empty to go back to “{orig}”." if f.name != orig else "")
        tag = f"  (the {f.tags[0].upper()} tag)" if f.tags and (f.custom or len(f.tags) == 1) else ""
        name, ok = QInputDialog.getText(self, "Rename column", f"New name for the “{f.name}” column{tag}:{hint}",
                                        text=f.name)
        if not ok:
            return
        name = name.strip()
        if f.custom:
            if name:
                self._rename_custom_field(key, name)
            return
        F.rename(key, name)
        self._column_names_changed()

    def reset_column_names(self):
        F.set_renames({})
        self._column_names_changed()

    def _column_names_changed(self):
        F.save_renames(self.settings)
        self._fields_changed()
        self.browser.set_fields(self.browser.fields())
        n = len(F.renames())
        self.status.setText(f"{n} renamed column{'s' if n != 1 else ''}" if n else "Column names reset")

    def _rename_custom_field(self, key: str, name: str):
        defs = F.custom_defs()
        for d in defs:
            if F.custom_key(d["tag"]) == key:
                d["name"] = name
        F.set_custom(defs)
        F.save_custom(self.settings)
        self._fields_changed()

    def _fields_changed(self):
        for _, t in self._column_tables():
            t.set_fields(F.all_fields())
        self._save_columns()
        self.artist_page.table.set_fields(F.all_fields())
        self.albums_page.table.set_fields(F.all_fields())
        for w in self.custom_pages:
            if getattr(w, "table", None) is None:
                continue
            w.table.set_fields(F.all_fields())
            w.spec["columns"] = w.table.column_state()
        self._save_custom_tabs()
        self._refilter()
        if hasattr(self.now, "refresh_items"):
            self.now.refresh_items()

    def _open_eq(self):
        if getattr(self, "eq_window", None) is None:
            self.eq_window = EqualizerWindow(self.theme, self.settings, self.player.eq_available,
                                             self.player.eq_error, self)
            self.eq_window.changed.connect(self._on_eq_changed)
            self.eq_window.installEventFilter(self)
        self.eq_window.show()
        self.eq_window.raise_()
        self.eq_window.activateWindow()

    def eventFilter(self, obj, ev):
        t = ev.type()
        if obj is getattr(self, "status", None) and t == QEvent.MouseButtonRelease:
            if getattr(self, "_alert_station", None) and self.status.text() == getattr(self, "_alert_msg", ""):
                self._alert_listen()
                return True
            if getattr(self, "_copy_msg", "") and self.status.text() == self._copy_msg:
                self._copy_msg = ""
                self.status.unsetCursor()
                self.play_radio_copy(self._copy_msg_tid)
                return True
            return False
        if t in (QEvent.MouseButtonPress, QEvent.MouseMove, QEvent.MouseButtonRelease) and \
                obj in getattr(self, "nav_buttons", ()) and self._tab_drag(obj, ev):
            return True
        key = getattr(self, "_top_keys", {}).get(obj)
        if key is not None and getattr(self, "customizing", False) and self._top_resize_event(key, obj, ev):
            return True
        if key is not None and getattr(self, "customizing", False):
            if t == QEvent.ContextMenu:
                self._top_menu(ev.globalPos(), key)
                return True
            if t == QEvent.MouseButtonPress and ev.button() == Qt.LeftButton:
                self._top_press = (key, ev.globalPosition().toPoint())
                return key in ("search", "status")  # unlocked, the search box moves rather than takes text
            if t == QEvent.MouseMove and getattr(self, "_top_press", None) and ev.buttons() & Qt.LeftButton:
                k, p0 = self._top_press
                if k == key and (ev.globalPosition().toPoint() - p0).manhattanLength() > QApplication.startDragDistance() + 2:
                    self._top_press = None
                    if hasattr(obj, "setDown"):
                        obj.setDown(False)
                    self._top_drag(key)
                    return True
                return key == "search"
            if t == QEvent.MouseButtonRelease:
                self._top_press = None
                return key == "search"
        if t in (QEvent.DragEnter, QEvent.DragMove, QEvent.Drop) and self._drag_target(obj):
            return self._song_drag(obj, ev)
        # keep the audio buffer small while the EQ window is open
        if obj is getattr(self, "eq_window", None) and ev.type() in (QEvent.Show, QEvent.Hide):
            eng = self.player.engine
            if eng is not None:
                eng.media.set_responsive(ev.type() == QEvent.Show)
        return super().eventFilter(obj, ev)

    def _top_resize_event(self, key: str, obj, ev) -> bool:
        """Unlocked: drag the right edge of an item along the top to make it wider or narrower."""
        t = ev.type()
        if t not in (QEvent.MouseMove, QEvent.MouseButtonPress, QEvent.MouseButtonRelease, QEvent.MouseButtonDblClick):
            return False
        busy = getattr(self, "_top_resizing", None)
        g = ev.globalPosition().toPoint()
        if busy:
            k, x0, w0 = busy
            if t == QEvent.MouseMove:
                self.set_top_width(k, w0 + g.x() - x0, save=False)
            elif t == QEvent.MouseButtonRelease:
                self._top_resizing = None
                self.set_top_width(k, self.top_widget(k).width())
            return True
        if not self._top_resizable(key):
            return False
        w = self.top_widget(key)
        on_edge = w.width() - 7 <= w.mapFromGlobal(g).x() <= w.width() + 2
        if t == QEvent.MouseMove and not ev.buttons():
            obj.setCursor(Qt.SizeHorCursor if on_edge else Qt.OpenHandCursor)
            return False
        if on_edge and ev.button() == Qt.LeftButton:
            if t == QEvent.MouseButtonDblClick:
                self.set_top_width(key, None)  # back to its own width
            elif t == QEvent.MouseButtonPress:
                self._top_press = None
                self._top_resizing = (key, g.x(), w.width())
            return True
        return False

    def _on_eq_changed(self, enabled: bool, gains: list, preamp: float, preset: str):
        self.player.set_eq(enabled, gains, preamp)
        s = self.settings
        s.setValue("eq_enabled", enabled)
        s.setValue("eq_gains", json.dumps(gains))
        s.setValue("eq_preamp", preamp)
        if self.bar.eq_on != enabled:
            self.bar.eq_on = enabled
            self._refresh_bar()
        if enabled and preset and preset != "Flat":
            self.bar.eq_btn.setToolTip(f"Equalizer: {preset} (Ctrl+Shift+E)")
        else:
            self.bar.eq_btn.setToolTip("Equalizer: off (Ctrl+Shift+E)" if not enabled else "Equalizer (Ctrl+Shift+E)")

    def dragEnterEvent(self, e):
        from musicwell.models import TRACKS_MIME
        if e.mimeData().hasUrls() and not e.mimeData().hasFormat(TRACKS_MIME):
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        from musicwell.models import TRACKS_MIME
        if e.mimeData().hasUrls() and not e.mimeData().hasFormat(TRACKS_MIME):
            e.acceptProposedAction()

    def dropEvent(self, e):
        """Dropped folders join the library; dropped songs already in it go into the queue."""
        from musicwell.tags import AUDIO_EXTS
        folders, songs = [], []
        for url in e.mimeData().urls():
            p = url.toLocalFile()
            if not p:
                continue
            if os.path.isdir(p):
                folders.append(p)
            elif os.path.splitext(p)[1].lower() in AUDIO_EXTS:
                songs.append(os.path.abspath(p))
        for d in dict.fromkeys(folders):
            self.library.add_folder(d)
        msg = []
        if songs:
            # songs already in the library are queued, new ones added first
            by_path = {t["path"]: t["id"] for t in self.library.tracks.values()}
            new = [p for p in songs if p not in by_path]
            new_ids = self.library.add_files(new) if new else {}
            by_path.update(new_ids)
            queue = [by_path[p] for p in songs if p in by_path]
            if queue:
                self.player.enqueue(queue)
                msg.append(f"{len(queue)} song{'s' if len(queue) != 1 else ''} added to the queue"
                           + (f" ({len(new_ids)} new to your library)" if new_ids else ""))
            if len(new_ids) < len(new):
                msg.append(f"{len(new) - len(new_ids)} couldn't be read")
        if folders:
            n = len(dict.fromkeys(folders))
            msg.append(f"added {n} folder{'s' if n != 1 else ''} to the library — scanning…")
            self.lib_stack.setCurrentIndex(1)
        if msg:
            self._flash("; ".join(msg)[0].upper() + "; ".join(msg)[1:])
        e.acceptProposedAction()

    # songs dragged within Musicwell
    @staticmethod
    def _dragged_ids(md) -> list[int]:
        from musicwell.models import TRACKS_MIME
        if not md.hasFormat(TRACKS_MIME):
            return []
        try:
            return [int(i) for i in json.loads(bytes(md.data(TRACKS_MIME)).decode() or "[]")]
        except (TypeError, ValueError):
            return []

    # drag a tab to move it
    def _tab_drag(self, btn, ev) -> bool:
        """True when the event is part of dragging a tab (so it doesn't also click). Only while customizing."""
        t = ev.type()
        if not getattr(self, "customizing", False):
            self._tab_press = None
            return False
        here = btn.mapTo(self.top_bar, ev.position().toPoint())  # top bar coordinates
        if t == QEvent.MouseButtonPress:
            if ev.button() == Qt.LeftButton:
                self._tab_press = (btn, here)
            return False
        press = getattr(self, "_tab_press", None)
        if t == QEvent.MouseMove:
            if not press or press[0] is not btn or not (ev.buttons() & Qt.LeftButton):
                return False
            if getattr(self, "_tab_ghost", None) is None:
                if (here - press[1]).manhattanLength() < QApplication.startDragDistance():
                    return False
                self._start_tab_drag(btn, press[1])
            self._move_tab_drag(here)
            return True
        if t == QEvent.MouseButtonRelease:
            self._tab_press = None
            if getattr(self, "_tab_ghost", None) is not None:
                self._finish_tab_drag(btn, here)
                return True
        return False

    def _start_tab_drag(self, btn, start_global):
        from PySide6.QtWidgets import QFrame, QGraphicsOpacityEffect, QLabel
        btn.setDown(False)
        bar = self.top_bar
        from PySide6.QtGui import QPainter, QPen, QPixmap
        from PySide6.QtCore import QRectF
        shot = btn.grab()
        dpr = shot.devicePixelRatio()
        pm = QPixmap(shot.size())
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.transparent)
        qp = QPainter(pm)
        qp.setRenderHint(QPainter.Antialiasing)
        r = QRectF(1, 3, btn.width() - 2, btn.height() - 6)
        fill = self.theme.color("surface")
        fill.setAlpha(255)
        qp.setBrush(fill)
        qp.setPen(QPen(self.theme.color("accent"), 1.5))
        qp.drawRoundedRect(r, 7, 7)
        qp.drawPixmap(0, 0, shot)
        qp.end()
        ghost = QLabel(bar)
        ghost.setPixmap(pm)
        eff = QGraphicsOpacityEffect(ghost)
        eff.setOpacity(0.97)
        ghost.setGraphicsEffect(eff)
        ghost.resize(btn.size())
        ghost.move(btn.mapTo(bar, btn.rect().topLeft()))
        ghost.show()
        ghost.raise_()
        self._tab_ghost = ghost
        self._tab_grab_dx = start_global.x() - ghost.x()
        line = QFrame(bar)
        line.setStyleSheet(f"background: {self.theme.accent.name()}; border-radius: 1px;")
        line.resize(3, btn.height() - 6)
        line.show()
        self._tab_line = line
        btn.setStyleSheet("color: transparent;")  # its gap shows where it came from

    def _tab_drop_index(self, x: int, dragged: int) -> int:
        """Drop index among the shown tabs (excluding the dragged one)."""
        vis = [p for p in self.visible_tab_order() if p != dragged]
        for k, p in enumerate(vis):
            b = self.nav_buttons[p]
            mid = b.mapTo(self.top_bar, b.rect().center()).x()
            if x < mid:
                return k
        return len(vis)

    def _move_tab_drag(self, gp):
        bar = self.top_bar
        x = gp.x()
        ghost = self._tab_ghost
        ghost.move(x - self._tab_grab_dx, ghost.y())
        btn = self._tab_press[0] if getattr(self, "_tab_press", None) else None
        dragged = self.nav_buttons.index(btn) if btn in self.nav_buttons else -1
        vis = [p for p in self.visible_tab_order() if p != dragged]
        k = self._tab_drop_index(x, dragged)
        if vis:
            if k < len(vis):
                b = self.nav_buttons[vis[k]]
                lx = b.mapTo(bar, b.rect().topLeft()).x() - 3
            else:
                b = self.nav_buttons[vis[-1]]
                lx = b.mapTo(bar, b.rect().topRight()).x() + 1
            self._tab_line.move(lx, b.mapTo(bar, b.rect().topLeft()).y() + 3)

    def _finish_tab_drag(self, btn, gp):
        x = gp.x()
        for w in (self._tab_ghost, self._tab_line):
            w.hide()
            w.deleteLater()
        self._tab_ghost = self._tab_line = None
        btn.setStyleSheet("")
        btn.setDown(False)
        page = self.nav_buttons.index(btn)
        k = self._tab_drop_index(x, page)
        vis = [p for p in self.visible_tab_order() if p != page]
        new_vis = vis[:k] + [page] + vis[k:]
        if new_vis == self.visible_tab_order():
            return
        # removed tabs stay just after the tab they followed
        old = self.tab_order()
        after, prev = {}, None
        for p in old:
            if p in new_vis:
                prev = p
            else:
                after.setdefault(prev, []).append(p)
        order = list(after.get(None, []))
        for p in new_vis:
            order += [p] + after.get(p, [])
        self.set_tab_order(order)
        self._apply_tab_visibility()

    def _drag_target(self, obj) -> str:
        if obj is self.pl_list.viewport():
            return "playlists"
        if obj is self.nav_buttons[1]:
            return "queue_tab"
        if obj is self.nav_buttons[2]:
            return "playlists_tab"
        return ""

    def _song_drag(self, obj, ev) -> bool:
        from musicwell.models import TRACKS_MIME
        if not ev.mimeData().hasFormat(TRACKS_MIME):
            return False
        where = self._drag_target(obj)
        pos = ev.position().toPoint()
        if ev.type() in (QEvent.DragEnter, QEvent.DragMove):
            if where == "playlists_tab":
                self._go_page(2)  # open Playlists so the songs can go on one
            ev.setDropAction(Qt.CopyAction)
            ev.accept()
            if where == "playlists":
                it = self.pl_list.itemAt(pos)
                self.pl_list.setToolTip("")
                self._drop_hint(f"Add to “{it.text()}”" if it else "Drop here to make a new playlist")
            elif where == "queue_tab":
                self._drop_hint("Add to the queue")
            return True
        ids = self._dragged_ids(ev.mimeData())
        ev.setDropAction(Qt.CopyAction)
        ev.accept()
        if not ids:
            return True
        n = f"{len(ids)} song{'s' if len(ids) != 1 else ''}"
        if where == "queue_tab":
            self.player.enqueue(ids)
            self._flash(f"{n} added to the queue")
        elif where == "playlists":
            it = self.pl_list.itemAt(pos)
            if it is None:
                QTimer.singleShot(0, lambda: self._new_playlist(ids))
            else:
                pid, name = it.data(Qt.UserRole), it.text()  # the list is rebuilt by the change
                self.library.add_to_playlist(pid, ids)
                self._flash(f"{n} added to “{name}”")
                self._show_playlist()
        return True

    def _drop_hint(self, text: str):
        if self.status.text() != text:
            self._flash(text, 1500)

    def _drop_on_queue(self, ids: list, row: int, internal: bool, rows: list):
        """Songs dropped on the queue: added from another list, or moved within it."""
        pl = self.player
        pl.qlist = [e for e in pl.qlist if self.library.get(e["id"])]
        items = pl.qlist
        new, first = _place(items, [pl._entry(i) for i in ids], row if row >= 0 else len(items), internal, rows)
        pl.set_queue_rows(new)
        self._select_rows(self.queue_table, first, len(rows) if internal else len(ids))
        if not internal:
            self._flash(f"{len(ids)} song{'s' if len(ids) != 1 else ''} added to the queue")

    def _drop_on_playlist(self, ids: list, row: int, internal: bool, rows: list, pid=None, table=None):
        table = table or self.pl_table
        pid = self._current_playlist() if pid is None else pid
        if pid is None:
            QTimer.singleShot(0, lambda: self._new_playlist(ids))
            return
        visible = [tid for tid in self.library.playlist_track_ids(pid) if self.library.get(tid)]
        rows, row = self._unsort(table, visible, rows, row)
        new, first = _place(visible, ids, row, internal, rows)
        self.library.set_playlist_tracks(pid, new)
        self._show_playlist()
        self._refresh_custom_tabs("playlist")
        self._select_rows(table, first, len(rows) if internal else len(ids))

    @staticmethod
    def _unsort(table, order_ids: list, rows: list, row: int):
        """In a column-sorted list, map visible rows back to the list's own order."""
        m = table.model_
        if m.sort_col < 0:
            return rows, row
        shown = [t["id"] for t in m.rows]
        pos: dict[int, list[int]] = {}
        for i, tid in enumerate(order_ids):
            pos.setdefault(tid, []).append(i)
        def place(r):
            ps = pos.get(shown[r], []) if r < len(shown) else []
            return ps.pop(0) if ps else len(order_ids)
        new_rows = sorted(place(r) for r in rows)
        pos = {}
        for i, tid in enumerate(order_ids):
            pos.setdefault(tid, []).append(i)
        new_row = place(row) if row < len(shown) else len(order_ids)
        table.horizontalHeader().setSortIndicator(-1, Qt.AscendingOrder)
        m.sort_col = -1
        return new_rows, new_row

    @staticmethod
    def _select_rows(table, first: int, n: int):
        sm = table.selectionModel()
        sm.clearSelection()
        for r in range(first, first + n):
            sm.select(table.model_.index(r, 0), SEL_ROWS)

    def _restore(self):
        s = self.settings
        if s.contains("geometry"):
            self.restoreGeometry(s.value("geometry", QByteArray()))
        self._place_panel(s.value("panel_side", "left"))
        try:
            self.browser.widths = {k: list(v) for k, v in json.loads(s.value("pane_widths", "{}")).items()}
        except (TypeError, ValueError, AttributeError):
            self.browser.widths = {}
        self.browser.set_fields(self._saved_pane_fields())
        self.browser.setVisible(s.value("browser_visible", True, bool))
        eq_on, gains, preamp = load_eq_settings(s)
        if self.player.eq_available:
            self.player.set_eq(eq_on, gains, preamp)
            self.bar.eq_on = eq_on
        for key, w in (("body_split", self.body), ("lib_split", self.lib_split),
                       ("albums_split", self.albums_page.split), ("artist_split", self.artist_page.split)):
            if s.contains(key):  # covers / songs split height
                w.restoreState(s.value(key, QByteArray()))
        for key, t in self._column_tables():
            try:
                state = json.loads(s.value(key, "[]"))
                t.restore_column_state(state)
            except (TypeError, ValueError):
                state = []
            # one-time: show the new Source column next to the title
            if key != "columns_library" and not any(c.get("key") == "source" for c in state or []):
                t.show_column("source")
                hh, m = t.horizontalHeader(), t.model_
                src, ttl = m.column_of("source"), m.column_of("title")
                if src >= 0 and ttl >= 0:
                    hh.moveSection(hh.visualIndex(src), hh.visualIndex(ttl) + 1)
        self.now.setVisible(s.value("panel_visible", True, bool))
        vol = int(s.value("volume", 80))
        self.bar.volume.setValue(vol)
        self.player.set_volume(vol / 100)
        self.now.header.set_fit(s.value("artist_photo_fit", "whole"))
        if s.contains("panel_layout"):
            self.now.restore_state(s.value("panel_layout"))
        if s.contains("panel2_layout"):
            self.now2.restore_state(s.value("panel2_layout"))
        self.now2.header.set_fit(s.value("artist_photo_fit", "whole"))
        self.now2.setVisible(s.value("panel2_visible", False, bool))
        if s.contains("panel3_layout"):
            self.now3.restore_state(s.value("panel3_layout"))
        self.now4.header.set_fit(s.value("artist_photo_fit", "whole"))
        self.now3.header.set_fit("fill")
        self._place_strip(s.value("panel3_where", "top"))
        self.now3.setVisible(s.value("panel3_visible", False, bool))
        self.pages.setVisible(s.value("centre_visible", True, bool))
        self.bar.setVisible(s.value("bar_visible", True, bool))
        if s.contains("middle_split"):
            self.middle.restoreState(s.value("middle_split"))
        if s.contains("bar_layout"):
            self.bar.restore_state(s.value("bar_layout"))
        if not s.value("like_icon_added", False, bool):  # one-time: ♥ next to the playing song
            s.setValue("like_icon_added", True)
            self.set_like_icon(True)
        if not s.value("copy_pill_added", False, bool):  # one-time: "▶ Your copy"
            s.setValue("copy_pill_added", True)
            b = self.bar
            if "copy" not in b.all_placed():
                zone = next((z for z, keys in b.zones.items() if "like" in keys or "info" in keys), "left")
                keys = b.zones[zone]
                at = keys.index("like") + 1 if "like" in keys else (keys.index("info") + 1 if "info" in keys
                                                                     else len(keys))
                b.place_item("copy", zone, at)
        self._place_bar(self.bar.options.get("position", "bottom"))
        self._connect_visualizer()
        self._apply_visualizer()
        self.player.shuffle = s.value("shuffle", False, bool)
        self.player.repeat = int(s.value("repeat", 0))
        self._go_page(0)

    def _restore_session(self):
        s = self.settings
        tid = s.value("last_track")
        if tid is None:
            return
        try:
            tid = int(tid)
            ids = [i for i in json.loads(s.value("last_list", "[]")) if i in self.library.tracks]
        except (ValueError, TypeError):
            return
        if tid not in self.library.tracks:
            return
        if tid not in ids:
            ids = [tid]
        self.player.load_paused(ids, ids.index(tid), int(s.value("last_pos", 0)))
        self.table.scroll_to_id(tid, select=False)

    def _setup_desktop(self):
        """Media keys and controls (MPRIS), notifications and the tray icon."""
        from musicwell.desktop import Desktop, Tray
        app = QApplication.instance()
        self._quitting = False
        self._note_key = None
        self._note_art = ""
        self._note_sent_at = 0.0
        self.desktop = Desktop(self)
        self.desktop.requested.connect(self._desktop_request)
        self.tray = Tray(self)
        self.tray.requested.connect(self._desktop_request)
        self.desktop.notifyFailed.connect(self.tray.message)  # no notification service: use the tray
        app.setQuitOnLastWindowClosed(False)  # closing quits or goes to the tray
        app.commitDataRequest.connect(lambda *_: setattr(self, "_quitting", True))  # logging out
        pl = self.player
        pl.playingChanged.connect(lambda _: self._desktop_state())
        pl.modesChanged.connect(self._desktop_state)
        pl.trackChanged.connect(lambda _: self.desktop.track_started(0))
        pl.positionChanged.connect(lambda ms: self.desktop.set_position(self.heard_position(ms)))
        pl.seeked.connect(lambda ms: self.desktop.set_position(ms, seeked=True))
        pl.durationChanged.connect(lambda _: self._desktop_track())
        self.bar.volume.valueChanged.connect(lambda v: self.desktop.update(Volume=round(v / 100, 3)))
        set_track = self.bar.set_track

        def bar_set_track(t, art, _set=set_track):  # every song or image change passes here
            _set(t, art)
            self._desktop_track(t, art)
        self.bar.set_track = bar_set_track
        self._note_timer = QTimer(self, singleShot=True, interval=700)
        self._note_timer.timeout.connect(self._maybe_notify)
        self.desktop.update(Volume=round(self.bar.volume.value() / 100, 3))
        self._apply_desktop_settings(self.settings)

    def _apply_replaygain_settings(self, s):
        self.player.set_replaygain(s.value("replaygain", "off"), float(s.value("replaygain_preamp", 0.0)),
                                   float(s.value("replaygain_untagged", 0.0)), s.value("replaygain_clip", True, bool))
        cur = self.player.current
        if cur is not None:
            self.now.set_levelling(self._levelling_text(cur))

    def _levelling_text(self, t) -> str:
        """e.g. 'ReplayGain -7.4 dB'; empty when off."""
        from musicwell.player import replaygain
        pl = self.player
        if pl.rg_mode == "off" or not t or t.get("stream") or t.get("remote"):
            return ""
        factor, note = replaygain(t, pl.rg_mode, pl.shuffle, pl.rg_preamp, pl.rg_untagged, pl.rg_clip)
        if note.startswith("no ReplayGain") or note.endswith("(no ReplayGain information)"):
            return "No ReplayGain tags" + (f" ({note.split(' ')[0].replace('-', '−')} dB)" if factor != 1.0 else "")
        return "ReplayGain " + note.split(" (")[0].replace("-", "−")

    def _apply_desktop_settings(self, s):
        from musicwell.desktop import Tray
        self.desktop.set_media_controls(s.value("mpris", True, bool))
        tray = s.value("tray", False, bool)
        self.tray.set_visible(tray)
        self._close_to_tray = tray and s.value("close_to_tray", False, bool)
        self._notify_on = s.value("notify", False, bool)
        self._notify_bg = s.value("notify_background_only", True, bool)
        if not tray and not self.isVisible() and getattr(self, "_shown_once", False):
            self.show_window()  # never hide the window without a tray icon
        self._tray_ok = Tray.available()

    def starts_hidden(self) -> bool:
        """Start in the tray (if enabled and a tray exists)."""
        s = self.settings
        from musicwell.desktop import Tray
        return s.value("tray", False, bool) and s.value("start_in_tray", False, bool) and Tray.available()

    def _desktop_state(self):
        pl = self.player
        status = "Stopped" if pl.current is None else ("Playing" if pl.is_playing() else "Paused")
        loop = {0: "None", 1: "Playlist", 2: "Track"}.get(pl.repeat, "None")
        self.desktop.update(PlaybackStatus=status, Shuffle=bool(pl.shuffle), LoopStatus=loop)
        self.tray.set_playing(status == "Playing")
        if status == "Playing" and self._note_key and not self._note_sent_at:
            self._note_timer.start()

    def _desktop_track(self, t=..., art=...):
        if t is ...:
            t, art = self.player.current, self._current_art
        want_art = self.desktop.mpris_on or self._notify_on
        path = self.desktop.art_file(art) if want_art and art is not None else ""
        stream = bool(t and t.get("stream"))
        length = 0 if stream or not t else self.player.duration()
        self.desktop.update(Metadata=self.desktop.metadata(t, path, length), CanSeek=bool(t) and not stream,
                            CanGoNext=bool(t), CanGoPrevious=bool(t) and not stream)
        title, artist, extra = self._song_words(t)
        self.tray.set_song(title, artist)
        key = (title, artist, extra) if t else None
        if key != self._note_key:
            self._note_key, self._note_art, self._note_sent_at = key, path, 0.0
            if key:
                self._note_timer.start()  # delayed so quick skipping doesn't pile up notifications
        elif path and not self._note_art and self._note_sent_at and time_now() - self._note_sent_at < 10:
            self._note_art = path  # the cover arrived after the notification
            self._maybe_notify(replace=True)

    @staticmethod
    def _song_words(t) -> tuple[str, str, str]:
        """(title, artist, album or station) for the tray and notifications."""
        if not t:
            return "", "", ""
        if t.get("stream"):
            st = t.get("station") or {}
            song = t.get("now_playing") or ""
            return (t.get("title") or song or st.get("name", ""), t.get("artist") or "", st.get("name", ""))
        return t.get("title") or "", t.get("artist") or "", t.get("album") or ""

    def _maybe_notify(self, replace: bool = False):
        if not self._notify_on or not self._note_key or not self.player.is_playing():
            return
        if not replace and self._notify_bg and self.isVisible() and not self.isMinimized() and self.isActiveWindow():
            return  # you're already looking at Musicwell
        title, artist, extra = self._note_key
        body = " — ".join(x for x in (artist, extra) if x)
        self.desktop.notify(title or APP_NAME, body, self._note_art, replace=replace,
                            next_button=bool(self.player.current) and not self.player.current.get("stream"))
        self._note_sent_at = time_now()

    def _desktop_request(self, what: str, value=None):
        """Media keys, desktop media controls, the tray menu and notification buttons."""
        pl = self.player
        if what == "playpause":
            pl.play_pause()
        elif what == "play":
            if not pl.is_playing():
                pl.play_pause()
        elif what == "pause":
            if pl.is_playing():
                pl.play_pause()
        elif what == "stop":
            self._stop()
        elif what == "alert" and value and isinstance(value[1], dict) and "copy_tid" in value[1]:
            self.show_window() if value[0] == "default" else None
            self.play_radio_copy(value[1]["copy_tid"])
        elif what == "alert" and value:
            key, st = value
            if key in ("default", "listen"):
                self._alert_listen(st)
            else:
                self.show_window()
                self._go_page(5)
                self.radio_page.show_view("now")
        elif what == "next":
            pl.next()
        elif what == "previous":
            pl.previous()
        elif what == "seek" and pl.current:
            self._seek_to(max(0, min(pl.position() + int(value), max(0, pl.duration() - 500))))
        elif what == "position" and pl.current:
            self._seek_to(int(value))
        elif what == "volume":
            self.bar.volume.setValue(round(float(value) * 100))
        elif what == "shuffle":
            if bool(value) != pl.shuffle:
                pl.toggle_shuffle()
        elif what == "loop":
            pl.repeat = {"None": 0, "Playlist": 1, "Track": 2}[value]
            pl.modesChanged.emit()
        elif what == "message":  # the tray's pop-up was clicked
            ta = getattr(self, "_tray_alert", None)
            if ta and time_now() - ta[1] < 120:
                self._tray_alert = None
                self._alert_listen(ta[0])
            else:
                self.show_window()
        elif what == "raise":
            self.show_window()
        elif what == "toggle":
            if self.isVisible() and not self.isMinimized() and self.isActiveWindow():
                self.hide()
            else:
                self.show_window()
        elif what == "quit":
            self.quit_app()
        elif what == "about":
            self.show_window()
            self.open_about()

    def show_window(self):
        self._shown_once = True
        token = getattr(getattr(self, "desktop", None), "activation_token", "")
        if token:  # from the clicked notification (KDE / Wayland)
            os.environ["XDG_ACTIVATION_TOKEN"] = token
            self.desktop.activation_token = ""
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def showEvent(self, e):
        self._shown_once = True
        super().showEvent(e)

    def quit_app(self):
        """Quit for real (Ctrl+Q, tray menu, desktop controls)."""
        self._quitting = True
        self.close()

    def closeEvent(self, e):
        from musicwell.desktop import Tray
        if (not self._quitting and getattr(self, "_close_to_tray", False) and self.tray.is_visible()
                and Tray.available()):
            e.ignore()
            self.hide()  # keeps playing in the tray
            if not self.settings.value("tray_told", False, bool):
                self.settings.setValue("tray_told", True)
                self.tray.message(f"{APP_NAME} is still playing",
                                  "Click its icon in the tray to bring the window back. "
                                  "Quit from the tray menu, or with Ctrl+Q.")
            return
        self.save_and_stop()
        super().closeEvent(e)
        e.accept()
        QTimer.singleShot(0, QApplication.instance().quit)

    def save_and_stop(self):
        """Save everything and stop playback, threads and network services (once)."""
        if getattr(self, "_stopped", False):
            return
        self._stopped = True
        try:
            if getattr(self, "radio_log", None) is not None:
                self.radio_log.flush()  # the last few seconds of radio
            self.radio_page.now_timer.stop()
            self.song_alerts.shutdown()
            self.up_next.shutdown()
            self.radio_page.peek_pool.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        s = self.settings
        try:
            base = json.loads(s.value("layout_baseline", "{}") or "{}")
            if not isinstance(base, dict) or base.get("name") != s.value("layout_current", ""):
                self._snap_layout()  # quit right after switching
            else:
                self._remember_layout_changes()
        except Exception:
            pass
        s.setValue("geometry", self.saveGeometry())
        s.setValue("body_split", self.body.saveState())
        s.setValue("lib_split", self.lib_split.saveState())
        s.setValue("albums_split", self.albums_page.split.saveState())
        s.setValue("artist_split", self.artist_page.split.saveState())
        self._save_columns()
        self.browser.widths[",".join(self.browser.fields())] = self.browser.split.sizes()
        s.setValue("pane_widths", json.dumps(self.browser.widths))
        if self._on_tab_panel_page():
            pass  # Radio / Lyrics: the others are only hidden
        elif self._current_tab_key() == "0" or self._current_tab_key() not in self._tab_panels():
            s.setValue("panel_visible", self.now.isVisible())
            s.setValue("panel2_visible", self.now2.isVisible())
            s.setValue("panel3_visible", self.now3.isVisible())
            s.setValue("centre_visible", not self.pages.isHidden())
            s.setValue("bar_visible", not self.bar.isHidden())
        s.setValue("middle_split", self.middle.saveState())
        if self.now2.isVisible():
            s.setValue("panel2_width", self.body.sizes()[self.body.indexOf(self.now2)])
        s.setValue("volume", self.bar.volume.value())
        s.setValue("shuffle", self.player.shuffle)
        s.setValue("repeat", self.player.repeat)
        cur = self.player.current
        if cur and cur["id"] > 0:
            s.setValue("last_track", cur["id"])
            s.setValue("last_pos", self.player.position())
            s.setValue("last_list", json.dumps(self.player.playlist[:5000]))
        if self.cast_ctl:
            if self.player.cast is not None:
                self.player.stop_casting(resume_here=False)
            self.cast_ctl.shutdown()
        self.lyrics.shutdown()
        self.artist_info.shutdown()
        self.player.relay.shutdown()
        self.radio_page.shutdown()
        self.similar_page.pool.shutdown(wait=False, cancel_futures=True)
        self.online_page.free.pool.shutdown(wait=False, cancel_futures=True)
        self.finder.shutdown()
        self.waveforms.shutdown()
        self.images.shutdown()
        self.player.shutdown()
        self.library.shutdown()
        self.bar.shutdown()
        self.desktop.shutdown()
        self.tray.set_visible(False)
        s.sync()  # written now: the app exits without further clean-up
        self.hide()
        QApplication.processEvents()
        self.library.save_snapshot()  # can take a moment with a big library, so after the window has gone


def _place(items: list, ids: list, row: int, internal: bool, rows: list) -> tuple[list, int]:
    """The list after a drop and where the dropped songs start."""
    row = max(0, min(row, len(items)))
    if internal:
        move = set(rows)
        moving = [items[r] for r in sorted(move) if r < len(items)]
        rest = [t for i, t in enumerate(items) if i not in move]
        at = row - sum(1 for r in move if r < row)
        return rest[:at] + moving + rest[at:], at
    return items[:row] + list(ids) + items[row:], row

