"""Settings, tag editor and other dialogs."""
from __future__ import annotations

import json
import os
import sys

from PySide6.QtCore import QDir, QSize, QStandardPaths, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QIcon, QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QColorDialog, QComboBox, QDialog,
                               QDialogButtonBox, QFileDialog, QFormLayout, QGridLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListView, QListWidgetItem, QMenu, QMessageBox, QPushButton, QVBoxLayout, QWidget, QCompleter, QFileSystemModel,
                               QFrame, QStackedWidget)

from musicwell import fields as F
from musicwell import tags as tagio
from musicwell.widgets import (DEFAULT_PANES, MAX_PANES, PANE_FIELDS, PANE_PRESETS)


def music_dir() -> str:
    d = QStandardPaths.writableLocation(QStandardPaths.MusicLocation)
    return d if d and os.path.isdir(d) else os.path.expanduser("~")


def normalise_path(text: str) -> str:
    """Accept ~, $VARS, quotes and file:// URLs as well as plain paths."""
    text = text.strip().strip('"').strip("'")
    if text.startswith("file://"):
        text = QUrl(text).toLocalFile()
    if not text:
        return ""
    return os.path.normpath(os.path.abspath(os.path.expanduser(os.path.expandvars(text))))


class AddFolderDialog(QDialog):
    """Type, paste or browse for a folder."""

    def __init__(self, existing: list[str], parent=None, start: str = ""):
        super().__init__(parent)
        self.existing = [os.path.normpath(e) for e in existing]
        self.setWindowTitle("Add music folder")
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.addWidget(QLabel("Folder path"))
        row = QHBoxLayout()
        self.path = QLineEdit()
        self.path.setPlaceholderText(r"e.g. C:\Users\You\Music  or  D:\Music" if sys.platform == "win32"
                                     else "e.g. ~/Music  or  /mnt/storage/Music")
        self.path.setClearButtonEnabled(True)
        self.path.setText(start or music_dir())
        self.path.selectAll()
        model = QFileSystemModel(self)
        model.setFilter(QDir.AllDirs | QDir.NoDotAndDotDot | QDir.Drives)
        model.setRootPath("")
        comp = QCompleter(model, self)
        comp.setCompletionMode(QCompleter.PopupCompletion)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        self.path.setCompleter(comp)
        self.path.textChanged.connect(self._check)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        row.addWidget(self.path, 1)
        row.addWidget(browse)
        lay.addLayout(row)
        self.status = QLabel("")
        self.status.setObjectName("EmptyText")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.ok = self.buttons.button(QDialogButtonBox.Ok)
        self.ok.setText("Add folder")
        self.ok.setObjectName("Primary")
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)
        self._check()

    def folder(self) -> str:
        return normalise_path(self.path.text())

    def _check(self):
        p = self.folder()
        ok, msg = False, ""
        if not p:
            msg = "Type or paste a path, or click Browse…"
        elif not os.path.exists(p):
            msg = "That folder doesn't exist."
        elif not os.path.isdir(p):
            msg = "That's a file, not a folder."
        elif not os.access(p, os.R_OK | os.X_OK):
            msg = "Musicwell isn't allowed to read that folder."
        elif p in self.existing:
            msg = "That folder is already in your library."
        else:
            ok = True
            parent = next((e for e in self.existing if p.startswith(os.path.join(e, ""))), None)
            msg = (f"Already covered by {parent}, so adding it changes nothing."
                   if parent else f"Will add {p}")
        self.ok.setEnabled(ok)
        self.status.setText(msg)

    def _browse(self):
        start = self.folder() if os.path.isdir(self.folder()) else music_dir()
        d = QFileDialog.getExistingDirectory(self, "Choose a music folder", start)
        if d:
            self.path.setText(d)

    def _accept(self):
        if self.ok.isEnabled():
            self.accept()


def ask_music_folder(parent, existing: list[str]) -> str | None:
    dlg = AddFolderDialog(existing, parent)
    return dlg.folder() if dlg.exec() else None


def _size_text(paths) -> str:
    total = 0
    for p in paths:
        try:
            total += p.stat().st_size
        except OSError:
            pass
    n = len(paths)
    mb = total / 1_000_000
    size = f"{mb:.1f} MB" if mb >= 0.1 else f"{total // 1000} KB"
    return f"{n:,} file{'s' if n != 1 else ''}, {size}"


class ClearCacheDialog(QDialog):
    """Delete downloaded covers and artist photos (optionally more)."""

    def __init__(self, window, parent=None):
        super().__init__(parent or window)
        self.window = window
        self.setWindowTitle("Clear cache")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        intro = QLabel("Choose what to delete. Everything is looked up again from scratch the next time "
                       "it's needed. Your music files, cover.jpg files in your folders and the covers "
                       "inside your songs are never touched.")
        intro.setWordWrap(True)
        intro.setObjectName("EmptyText")
        lay.addWidget(intro)
        img, lyr, wav = window.images, getattr(window, "lyrics", None), getattr(window, "waveforms", None)
        self.covers = QCheckBox(f"Album covers and artist photos downloaded online  ({_size_text(img.cache_files())})")
        self.covers.setChecked(True)
        mine = [p for p in img.cache_files(True) if p.suffix == ".mine"]
        self.mine = QCheckBox(f"Images I picked myself  ({_size_text(mine)})")
        self.mine.setToolTip("Images you chose yourself (Search for artist image…, Use my own image…, or dropped from the web)")
        self.lyrics = QCheckBox(f"Lyrics found online  ({_size_text(lyr.cache_files()) if lyr else '0 files'})")
        self.waves = QCheckBox(f"Seek bar waveforms  ({_size_text(wav.cache_files()) if wav else '0 files'})")
        from musicwell import similar as similar_mod
        self.similar = QCheckBox(f"Find similar data — similar artists and genres  "
                                 f"({_size_text(similar_mod.cache_files())})")
        self.similar.setToolTip("What ListenBrainz and MusicBrainz said about each artist (kept for a month)")
        for w in (self.covers, self.mine, self.lyrics, self.waves, self.similar):
            lay.addWidget(w)
        self.lyrics.setEnabled(lyr is not None)
        self.waves.setEnabled(wav is not None)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        go = buttons.addButton("Clear", QDialogButtonBox.AcceptRole)
        go.setObjectName("Primary")
        buttons.accepted.connect(self._clear)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _clear(self):
        w = self.window
        if self.covers.isChecked() or self.mine.isChecked():
            if self.covers.isChecked():
                w.images.clear_cache(include_mine=self.mine.isChecked())
            else:  # only your own picks
                for p in w.images.cache_files(True):
                    if p.suffix == ".mine":
                        p.unlink(missing_ok=True)
                w.images._albums.clear()
                w.images._artists.clear()
                w.images._thumbs.clear()
        if self.lyrics.isChecked() and getattr(w, "lyrics", None):
            w.lyrics.clear_cache()
        if self.waves.isChecked() and getattr(w, "waveforms", None):
            w.waveforms.clear_cache()
        if self.similar.isChecked():
            from musicwell import similar as similar_mod
            similar_mod.clear_cache()
        if hasattr(w, "_after_cache_cleared"):
            w._after_cache_cleared()
        self.accept()


# settings pages
PAGES = ["Library", "Playback", "Radio", "Search", "Online", "Devices & desktop", "Theme", "Keyboard"]
PAGE_OF = {"Library": "Library", "Playback": "Playback", "Radio": "Radio", "Search": "Search",
           "Online images": "Online", "Artist info": "Online", "Lyrics": "Online",
           "Casting": "Devices & desktop", "Desktop": "Devices & desktop",
           "Theme": "Theme", "Shortcuts": "Keyboard"}
SECTION_NAMES = {"Online images": "Covers and artist photos", "Artist info": "Artist information",
                 "Lyrics": "Lyrics", "Casting": "Casting", "Desktop": "Desktop"}


from PySide6.QtWidgets import QStyledItemDelegate, QStyle


class _ResultDelegate(QStyledItemDelegate):
    """Search result: the setting's text with its page below."""

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self.theme = theme

    def _parts(self, index):
        text = index.data() or ""
        return (text.split("\n", 1) + [""])[:2]

    def sizeHint(self, option, index):
        from PySide6.QtCore import QSize
        label, page = self._parts(index)
        fm = option.fontMetrics
        w = max(200, (option.rect.width() or 600) - 24)
        h = fm.boundingRect(0, 0, w, 1000, Qt.TextWordWrap, label).height()
        return QSize(w, h + (fm.height() if page else 0) + 14)

    def paint(self, p, option, index):
        from PySide6.QtCore import QRect
        from PySide6.QtGui import QFont
        label, page = self._parts(index)
        p.save()
        r = option.rect
        if option.state & QStyle.State_MouseOver and index.flags() & Qt.ItemIsEnabled:
            p.setPen(Qt.NoPen)
            p.setBrush(self.theme.color("hover"))
            p.drawRoundedRect(r.adjusted(0, 0, 0, -1), 7, 7)
        fm = option.fontMetrics
        inner = r.adjusted(12, 6, -12, -6)
        p.setFont(option.font)
        p.setPen(self.theme.color("text" if index.flags() & Qt.ItemIsEnabled else "faint"))
        lh = fm.boundingRect(0, 0, inner.width(), 1000, Qt.TextWordWrap, label).height()
        p.drawText(QRect(inner.left(), inner.top(), inner.width(), lh), Qt.TextWordWrap, label)
        if page:
            f = QFont(option.font)
            f.setPointSizeF(max(7.0, f.pointSizeF() * 0.85))
            p.setFont(f)
            p.setPen(self.theme.color("muted"))
            p.drawText(QRect(inner.left(), inner.top() + lh, inner.width(), fm.height()), Qt.AlignLeft, page)
        p.restore()


def _heading(text: str, first: bool = False) -> QLabel:
    """Small section heading on a settings page."""
    h = QLabel(text.upper())
    h.setObjectName("SectionTitle")
    h.setContentsMargins(0, 0 if first else 10, 0, 0)
    return h


def _note(text: str) -> QLabel:
    """Short grey note under a setting."""
    n = QLabel(text)
    n.setObjectName("EmptyText")
    n.setWordWrap(True)
    return n


def _row(*widgets, stretch=True, indent=0) -> QWidget:
    """Several widgets side by side in one form row."""
    box = QWidget()
    h = QHBoxLayout(box)
    h.setContentsMargins(indent, 0, 0, 0)
    for w in widgets:
        h.addWidget(w)
    if stretch:
        h.addStretch()
    return box

class _DbBox(QComboBox):
    """-12 dB to +12 dB in 1 dB steps."""

    def __init__(self, value: float, lo: int, hi: int):
        super().__init__()
        vals = [float(v) for v in range(lo, hi + 1)]
        if value not in vals:
            vals = sorted(vals + [value])  # keep a value set before
        self._vals = vals
        for v in vals:
            self.addItem("0 dB" if not v else f"{v:+g} dB".replace("-", "−"))
        self.setCurrentIndex(vals.index(value))
        self.setMaximumWidth(140)

    def value(self) -> float:
        return self._vals[self.currentIndex()]


class _SecondsBox(QComboBox):
    """Fade length choices: Off, 1 s, 2 s..."""
    CHOICES = [0, 1, 2, 3, 4, 5, 6, 8, 10, 12]

    def __init__(self, value: float):
        super().__init__()
        vals = list(self.CHOICES)
        if value and value not in vals:
            vals = sorted(vals + [value])  # keep a value set before
        self._vals = vals
        for v in vals:
            self.addItem("Off" if not v else f"{v:g} s")
        self.setCurrentIndex(vals.index(value) if value in vals else 0)
        self.setMaximumWidth(140)

    def value(self) -> float:
        return float(self._vals[self.currentIndex()])

class SettingsDialog(QDialog):
    def __init__(self, window, parent=None, colours: bool = False):
        """colours=True shows only the colour settings (for the welcome window)."""
        super().__init__(parent or window)
        self.window = window
        self.lib = window.library
        self.colours_only = colours
        self.setWindowTitle("Colours" if colours else "Settings")
        self.setMinimumWidth(560 if colours else 760)
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        self._groups: list[tuple[str, QGroupBox]] = []
        self.find = QLineEdit()
        self.find.setPlaceholderText("Search Settings")
        self.find.setToolTip("Type a word (fade, tray, lyrics, port…) to find every setting about it")
        self.find.setClearButtonEnabled(True)
        self.find.textChanged.connect(self._find_changed)
        lay.addWidget(self.find)
        body = QHBoxLayout()
        body.setSpacing(12)
        self.side = QListWidget()
        self.side.setObjectName("SettingsSide")
        self.side.setFixedWidth(190)
        self.side.setFrameShape(QFrame.NoFrame)
        self.side.currentRowChanged.connect(self._side_picked)
        # search results replace the page
        self.results_page = QWidget()
        rl = QVBoxLayout(self.results_page)
        rl.setContentsMargins(4, 4, 4, 4)
        self.results_title = QLabel("")
        self.results_title.setObjectName("PageTitle")
        rl.addWidget(self.results_title)
        self.results = QListWidget()
        self.results.setFrameShape(QFrame.NoFrame)
        self.results.setWordWrap(True)
        self.results.setObjectName("SettingsSide")
        self.results.setSpacing(2)
        self.results.itemClicked.connect(self._result_picked)
        self.results.itemActivated.connect(self._result_picked)
        self.results.setItemDelegate(_ResultDelegate(window.theme, self.results))
        self.results.setMouseTracking(True)
        self.results.setCursor(Qt.PointingHandCursor)
        rl.addWidget(self.results, 1)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.results_page)
        body.addWidget(self.side)
        body.addWidget(self.stack, 1)
        lay.addLayout(body, 1)
        if colours:
            self.find.hide()
            self.side.hide()

        box = QGroupBox("Music folders")
        bl = QFormLayout(box)
        bl.setVerticalSpacing(9)
        bl.addRow(_heading("Music folders", first=True))
        self.folders = QListWidget()
        self.folders.setObjectName("Pane")
        self.folders.setFixedHeight(130)
        bl.addRow(self.folders)
        add = QPushButton("Add folder…")
        add.setObjectName("Primary")
        add.clicked.connect(self._add)
        rem = QPushButton("Remove")
        rem.clicked.connect(self._remove)
        rescan = QPushButton("Rescan")
        rescan.setToolTip("Look through your music folders again for new, changed and removed songs")
        rescan.clicked.connect(lambda: self.lib.scan())
        bl.addRow(_row(add, rem, rescan))
        bl.addRow(_heading("Years"))
        self.decade_from = QComboBox()
        self._decade_keys = ["year", "original"]
        self.decade_from.addItems(["Year", "Original year"])
        cur_d = window.settings.value("decade_from", "year")
        self.decade_from.setCurrentIndex(self._decade_keys.index(cur_d) if cur_d in self._decade_keys else 0)
        self.decade_from.setToolTip("Original year: a 2011 remaster of a 1977 album counts as the 1970s "
                                    "(songs without one use their year)")
        self.decade_from.setMaximumWidth(180)
        from musicwell import library as library_mod
        self.orig_tag = QComboBox()
        self.orig_tag.addItem("Automatic", "")
        counts = self.lib.tag_counts()
        likely = sorted((k for k in counts if library_mod.looks_like_original_year(k) or k in library_mod.ORIGINAL_YEAR_TAGS),
                        key=lambda k: -counts[k])
        rest = sorted((k for k in counts if k not in likely), key=str.lower)
        for k in likely + rest:
            self.orig_tag.addItem(f"{k.upper()}  ({counts[k]:,} song{'s' if counts[k] != 1 else ''})", k)
        if likely and rest:
            self.orig_tag.insertSeparator(1 + len(likely))
        cur_tag = window.settings.value("original_year_tag", "") or ""
        i = self.orig_tag.findData(cur_tag)
        if i < 0 and cur_tag:
            self.orig_tag.addItem(f"{cur_tag.upper()}  (not in your songs now)", cur_tag)
            i = self.orig_tag.count() - 1
        self.orig_tag.setCurrentIndex(max(0, i))
        self.orig_tag.setToolTip("The tag your music keeps the original release year in. Automatic looks for "
                                 "ORIGINALDATE, ORIGINALYEAR, TDOR and TORY; every tag in your music is listed.")
        self.orig_tag.setMaximumWidth(260)
        self.orig_note = _note("")

        def count_orig():
            tag = self.orig_tag.currentData() or ""
            n = sum(1 for t in self.lib.all_tracks() if library_mod.original_year(t.get("_extra") or {}, tag))
            total = len(self.lib.all_tracks())
            self.orig_note.setText(f"{n:,} of {total:,} songs have an original year.")
        self.orig_tag.currentIndexChanged.connect(count_orig)
        count_orig()
        bl.addRow("Decades from", self.decade_from)
        bl.addRow("Original year tag", self.orig_tag)
        bl.addRow("", self.orig_note)
        bl.addRow(_heading("Storage"))
        self.storage = QLabel("Working out…")
        self.storage.setObjectName("EmptyText")
        self.storage.setTextFormat(Qt.RichText)
        bl.addRow("", self.storage)
        clear = QPushButton("Clear cache…")
        clear.setToolTip("Choose what to delete — covers and artist photos, lyrics, seek bar waveforms, similar "
                         "artists — so it's looked up again from scratch. Your music files are never touched.")
        clear.clicked.connect(self._clear_cache)
        opencache = QPushButton("Open folder")
        opencache.setToolTip("The folder these are kept in")
        opencache.clicked.connect(self._open_cache_folder)
        bl.addRow("", _row(clear, opencache))
        QTimer.singleShot(0, self._show_storage)  # counting files can take a moment
        bl.addRow(_heading("Setup"))
        welcome = QPushButton("Welcome and setup…")
        welcome.setToolTip("The welcome window again: add your music, choose a layout and a theme")
        welcome.clicked.connect(lambda: (self.reject(), self.window.open_welcome()))
        bl.addRow("", _row(welcome))
        self._page("Library", box)
        self._fill_folders()

        s = window.settings
        from musicwell import theme as th
        themebox = QGroupBox("Theme")
        tl = QVBoxLayout(themebox)
        self.theme = QListWidget()
        self.theme.setViewMode(QListView.IconMode)
        self.theme.setIconSize(QSize(132, 84))
        self.theme.setGridSize(QSize(150, 114))
        self.theme.setResizeMode(QListView.Adjust)
        self.theme.setMovement(QListView.Static)
        self.theme.setMinimumHeight(400)
        self._orig_mode = window.theme.mode
        for key, name in th.theme_names():
            it = QListWidgetItem(QIcon(th.theme_preview(key)), name)
            it.setData(Qt.UserRole, key)
            it.setToolTip(f"{name} — {'dark' if th.PALETTES[key]['dark'] else 'light'} theme")
            self.theme.addItem(it)
            if key == window.theme.mode:
                self.theme.setCurrentItem(it)
        self.theme.currentItemChanged.connect(self._theme_picked)
        tl.addWidget(self.theme, 1)
        aform = QFormLayout()
        self.artmode = QComboBox()
        self._art_keys = [k for k, _ in th.ARTWORK_MODES]
        self.artmode.addItems({"off": "Off", "accent": "Accent colour only", "full": "Whole window"}.get(k, n)
                              for k, n in th.ARTWORK_MODES)
        self.artmode.setMaximumWidth(220)
        self.artmode.setCurrentIndex(self._art_keys.index(window.artwork_mode()))
        self.artmode.setToolTip("Accent colour only: the theme's colours with highlights from the cover.\n"
                                "The whole player: backgrounds, panels and text tinted from the cover too, "
                                "changing with every album (light or dark, as the theme above).")
        self.artmode.currentIndexChanged.connect(lambda _: self._preview())
        aform.addRow("Album art colours", self.artmode)
        self.artbg = QComboBox()
        self._artbg_keys = [k for k, _ in th.ARTWORK_BACKGROUNDS]
        self.artbg.addItems({"off": "Off", "soft": "Soft", "strong": "Strong"}.get(k, n)
                            for k, n in th.ARTWORK_BACKGROUNDS)
        self.artbg.setMaximumWidth(220)
        cur_bg = s.value("artwork_background", "off")
        self.artbg.setCurrentIndex(self._artbg_keys.index(cur_bg) if cur_bg in self._artbg_keys else 0)
        self.artbg.setToolTip("The playing song's cover, softly blurred, behind the whole window")
        self.artbg.currentIndexChanged.connect(lambda _: self._preview())
        aform.addRow("Album art background", self.artbg)
        # restored on Cancel
        self._orig = {k: s.value(k) for k in ("theme", "accent", "artwork_colours", "accent_follow",
                                              "artwork_background")}
        self.accent_btn = QPushButton()
        self._accent = QColor(s.value("accent", "#5aa9ff"))
        self._paint_accent()
        self.accent_btn.clicked.connect(self._pick_accent)
        self.accent_btn.setMaximumWidth(220)
        self.accent_btn.setToolTip("Used when the colours don't come from the artwork (and while a song "
                                   "has no cover). Picking a theme sets it to that theme's own colour; "
                                   "click to choose another.")
        aform.addRow("Accent colour", self.accent_btn)
        tl.addLayout(aform)
        self._page("Theme", themebox)


        castbox = QGroupBox("Chromecast and Sonos")
        cf = QFormLayout(castbox)
        cf.setVerticalSpacing(9)
        self.cast_disc = QCheckBox("Find Chromecast devices")
        self.cast_disc.setToolTip("Chromecasts, Google / Nest speakers and Cast TVs on your network")
        self.cast_disc.setChecked(s.value("cast_discovery", True, bool))
        cf.addRow("", self.cast_disc)
        self.sonos_disc = QCheckBox("Find Sonos speakers")
        self.sonos_disc.setToolTip("Sonos speakers on your network. Songs above 24-bit/48 kHz, and formats Sonos "
                                   "doesn't know (such as Opus), are converted to CD quality first.")
        self.sonos_disc.setChecked(s.value("sonos_discovery", True, bool))
        cf.addRow("", self.sonos_disc)
        self.sonos_addr = QLineEdit(s.value("sonos_addresses", "") or "")
        self.sonos_addr.setPlaceholderText("Optional, e.g. 192.168.1.40")
        self.sonos_addr.setToolTip("Only needed if your speakers aren't found: the address of any one of them "
                                   "(the Sonos app shows it in Settings → System → About my system). "
                                   "Separate several with commas.")
        self.sonos_addr.setMaximumWidth(260)
        cf.addRow("Sonos address", self.sonos_addr)
        from musicwell import sonos as _sonos
        from musicwell import cast as _cast
        if not _sonos.AVAILABLE:
            self.sonos_disc.setEnabled(False)
            self.sonos_disc.setText("Find Sonos speakers (needs the soco package)")
            self.sonos_addr.setEnabled(False)
        if not _cast.AVAILABLE:
            self.cast_disc.setEnabled(False)
        self.cast_port = QLineEdit(str(s.value("cast_port", 8770)))
        self.cast_port.setMaximumWidth(90)
        self.cast_port.setToolTip("Speakers fetch the music from this port on your computer. "
                                  "If you use a firewall (ufw, firewalld), allow it: e.g. sudo ufw allow 8770/tcp")
        cf.addRow("Streaming port", self.cast_port)
        if getattr(window, "cast_ctl", None) is None:
            castbox.setEnabled(False)
            self.cast_disc.setText("Casting needs the pychromecast or soco package")
        self._page("Casting", castbox)

        net = QGroupBox("Online images")
        nf = QFormLayout(net)
        nf.setVerticalSpacing(9)
        from musicwell import artsources as AS
        from musicwell.artwork import _order
        self.album_on = QCheckBox("Download missing album covers")
        self.album_on.setChecked(s.value("album_online", True, bool))
        self.album_on.setToolTip("When a song has no cover, look it up from the services below, in their order "
                                 "(drag to reorder, untick to skip). Right-click a cover to pick one yourself.")
        self.artist_on = QCheckBox("Download artist photos")
        self.artist_on.setChecked(s.value("artist_online", True, bool))
        self.artist_on.setToolTip("When an artist has no artist.jpg in their folder, look one up. Photos are "
                                  "freely licensed (Wikimedia Commons); the photographer shows on the photo.")
        self.album_src = self._source_list(AS.ALBUM_SOURCES, _order(s.value("album_sources"), AS.DEFAULT_ALBUM_ORDER, AS.ALBUM_SOURCES))
        self.artist_src = self._source_list(AS.ARTIST_SOURCES, _order(s.value("artist_sources"), AS.DEFAULT_ARTIST_ORDER, AS.ARTIST_SOURCES))
        for lst in (self.album_src, self.artist_src):  # just as tall as the list
            lst.setFixedHeight(min(150, 8 + 28 * max(1, lst.count())))
            lst.setToolTip("Drag to change the order, untick to skip one")
        nf.addRow("", self.album_on)
        nf.addRow("Cover sources", self.album_src)
        nf.addRow("", self.artist_on)
        nf.addRow("Photo sources", self.artist_src)
        nf.setRowVisible(self.album_src, self.album_on.isChecked())
        nf.setRowVisible(self.artist_src, self.artist_on.isChecked())
        self.album_on.toggled.connect(lambda on: nf.setRowVisible(self.album_src, on))
        self.artist_on.toggled.connect(lambda on: nf.setRowVisible(self.artist_src, on))
        self.save_covers = QCheckBox("Save downloaded covers in the album folder")
        self.save_covers.setToolTip("As cover.jpg, so other apps can use them too")
        self.save_covers.setChecked(s.value("save_covers", False, bool))
        nf.addRow("", self.save_covers)
        from musicwell import webimage as WI
        self.web_engine = QComboBox()
        for k, (label, _url) in WI.ENGINES.items():
            self.web_engine.addItem(label, k)
        self.web_engine.setCurrentIndex(max(0, self.web_engine.findData(WI.engine_of(s))))
        self.web_engine.setToolTip("Right-click a photo or cover → Search the web… opens your browser on this "
                                   "image search. Drag a picture from it onto the artist (or album), or copy it "
                                   "and use Paste. Pictures you pick stay on this computer.")
        nf.addRow("Search the web with", self.web_engine)
        retry = QPushButton("Retry missing")
        retry.setToolTip("Look again for the covers and photos that weren't found")
        retry.clicked.connect(self._retry_missing)
        nf.addRow("", _row(retry))
        self._page("Online images", net)

        about = QGroupBox("About the artist")
        af = QFormLayout(about)
        self.info_on = QCheckBox("Download artist information")
        self.info_on.setToolTip("A few paragraphs about the artist from Wikipedia (with where they're from, "
                                "their years and genres from MusicBrainz), for the artist page and the panel's "
                                "About the artist item. Each artist is looked up once a month.")
        self.info_on.setChecked(s.value("artist_info_online", True, bool))
        af.addRow("", self.info_on)
        self._page("Artist info", about)

        play = QGroupBox("Playback")
        pf = QFormLayout(play)
        pf.setVerticalSpacing(9)

        def heading(text):
            h = QLabel(text)
            h.setObjectName("SectionTitle")
            h.setContentsMargins(0, 10, 0, 0)
            pf.addRow(h)

        def note(text):
            n = QLabel(text)
            n.setObjectName("EmptyText")
            n.setWordWrap(True)
            pf.addRow("", n)
            return n

        heading("CROSSFADE")
        self.fade_in = _SecondsBox(float(s.value("fade_in", 0)))
        self.fade_in.setToolTip("Each song starts quietly and rises to full volume")
        self.fade_out = _SecondsBox(float(s.value("fade_out", 0)))
        self.fade_out.setToolTip("Each song fades away at the end")
        pf.addRow("Fade in", self.fade_in)
        pf.addRow("Fade out", self.fade_out)
        self.fade_album = QCheckBox("Fade between songs on the same album")
        self.fade_album.setToolTip("Leave this off for gapless albums, live albums and DJ mixes")
        self.fade_album.setChecked(s.value("fade_within_album", False, bool))
        pf.addRow("", self.fade_album)
        self.fade_transport = QComboBox()
        self._transport_ms = [0, 150, 300, 600, 1000]
        self.fade_transport.addItems(["Off", "0.15 s", "0.3 s", "0.6 s", "1 s"])
        cur_t = int(s.value("fade_transport", 0))
        self.fade_transport.setCurrentIndex(min(range(len(self._transport_ms)),
                                                key=lambda i: abs(self._transport_ms[i] - cur_t)))
        self.fade_transport.setToolTip("A short fade instead of a sudden cut when you pause, skip or seek")
        self.fade_transport.setMaximumWidth(140)
        pf.addRow("Fade on pause and skip", self.fade_transport)
        note("Fades don't work while casting.")

        heading("VOLUME")
        self.rg_mode = QComboBox()
        self._rg_keys = ["off", "track", "album", "auto"]
        self.rg_mode.addItems(["Off", "Track", "Album", "Auto"])
        cur_rg = s.value("replaygain", "off")
        self.rg_mode.setCurrentIndex(self._rg_keys.index(cur_rg) if cur_rg in self._rg_keys else 0)
        self.rg_mode.setToolTip("Plays songs at a similar loudness, using the ReplayGain tags in your files "
                                "(your files aren't changed).\n"
                                "Track: every song at the same loudness.\n"
                                "Album: keeps the quiet and loud songs of an album as they are.\n"
                                "Auto: Album when playing an album in order, Track when shuffling.")
        self.rg_mode.setMaximumWidth(140)
        self.rg_preamp = _DbBox(float(s.value("replaygain_preamp", 0.0)), -12, 12)
        self.rg_preamp.setToolTip("Raise this if levelled songs sound too quiet")
        self.rg_untagged = _DbBox(float(s.value("replaygain_untagged", 0.0)), -12, 6)
        self.rg_untagged.setToolTip("For songs without ReplayGain tags — −6 dB usually matches the rest")
        self.rg_clip = QCheckBox("Prevent clipping")
        self.rg_clip.setChecked(s.value("replaygain_clip", True, bool))
        self.rg_clip.setToolTip("Never raise a song so far that its loudest moments distort")
        tracks = self.lib.all_tracks()
        tagged = sum(1 for t in tracks if any(k in (t.get("_extra") or {}) for k in
                                              ("replaygain_track_gain", "replaygain_album_gain", "r128_track_gain")))
        pf.addRow("ReplayGain", self.rg_mode)
        pf.addRow("Pre-amp", self.rg_preamp)
        pf.addRow("Songs without tags", self.rg_untagged)
        pf.addRow("", self.rg_clip)
        self.rg_count = note(f"{tagged:,} of {len(tracks):,} songs have ReplayGain tags." if tracks else "")
        rg_rows = (self.rg_preamp, self.rg_untagged, self.rg_clip, self.rg_count)

        def rg_enable():
            on = self.rg_mode.currentIndex() != 0
            for w in rg_rows:  # details only when enabled
                pf.setRowVisible(w, on)
        self.rg_mode.currentIndexChanged.connect(rg_enable)
        rg_enable()

        heading("WHILE PLAYING")
        self.follow_playing = QComboBox()
        self._follow_keys = ["select", "scroll", "off"]
        self.follow_playing.addItems(["Highlight it", "Show it in bold", "Off"])
        cur_f = s.value("follow_playing", "select")
        self.follow_playing.setCurrentIndex(self._follow_keys.index(cur_f) if cur_f in self._follow_keys else 0)
        self.follow_playing.setToolTip("When a new song starts, the song list scrolls to it (unless you're using "
                                       "the list)")
        self.follow_playing.setMaximumWidth(180)
        pf.addRow("Scroll to the playing song", self.follow_playing)
        self.similar_continue = QCheckBox("Keep playing similar songs when the queue ends")
        self.similar_continue.setChecked(s.value("similar_continue", False, bool))
        self.similar_continue.setToolTip("Like autoplay: instead of stopping after the last song, carry on with "
                                         "songs like it from your library")
        pf.addRow("", self.similar_continue)
        self.similar_online = QCheckBox("Use ListenBrainz to find similar artists")
        self.similar_online.setChecked(s.value("similar_online", True, bool))
        self.similar_online.setToolTip("Sends the artist's name to ListenBrainz (open data, no account). "
                                       "Off: uses your genres and listening history only.")
        pf.addRow("", self.similar_online)
        self.similar_archive = QCheckBox("Also look for free music on the Internet Archive")
        self.similar_archive.setChecked(s.value("similar_archive", True, bool))
        self.similar_archive.setToolTip("Live Music Archive concerts, netlabel releases and Creative Commons / "
                                        "public-domain music, played from archive.org")
        self.similar_openverse = QCheckBox("Also look for free music on Openverse (Jamendo, Wikimedia Commons…)")
        self.similar_openverse.setChecked(s.value("similar_openverse", True, bool))
        self.similar_openverse.setToolTip("Creative Commons and public-domain music from openverse.org")
        self.similar_audius = QCheckBox("Also look for free music on Audius (independent artists, free to stream)")
        self.similar_audius.setChecked(s.value("similar_audius", True, bool))
        self.similar_audius.setToolTip("audius.co — an open music platform where artists share their songs to stream "
                                       "for free; no account needed")
        self._page("Playback", play)

        radio = QGroupBox("Radio")
        rf = QFormLayout(radio)
        rf.setVerticalSpacing(9)

        def section(title):
            head = QLabel(title.upper())
            head.setObjectName("SectionTitle")
            head.setContentsMargins(0, 10, 0, 0)
            rf.addRow(head)

        def rnote(text):
            n = QLabel(text)
            n.setObjectName("EmptyText")
            n.setWordWrap(True)
            rf.addRow("", n)
            return n

        def wrow(*ws):
            h = QHBoxLayout()
            h.setContentsMargins(0, 0, 0, 0)
            for x in ws:
                h.addWidget(x)
            h.addStretch()
            box = QWidget()
            box.setLayout(h)
            return box

        def indent(x):
            b = wrow(x)
            b.layout().setContentsMargins(26, 0, 0, 0)
            if isinstance(x, QLineEdit):
                b.layout().setStretch(0, 1)
            return b

        section("Stations")
        from musicwell.addim import LEVELS, LONGEST
        self.radio_next = QComboBox()
        self.radio_next.addItems(["Next favourite station", "Back to my music"])
        self.radio_next.setCurrentIndex(0 if s.value("radio_next", "stations") == "stations" else 1)
        self.radio_next.setToolTip("What Next and Previous (and the media keys) do while a station plays")
        self.radio_next.setMaximumWidth(220)
        rf.addRow("Next and Previous buttons", self.radio_next)
        self.now_order = QComboBox()
        self.now_order.addItems(["Station first", "Song first"])
        self.now_order.setCurrentIndex(1 if s.value("radio_now_song_first", False, bool) else 0)
        self.now_order.setToolTip("How the What's on now list on the Radio page is laid out")
        self.now_order.setMaximumWidth(220)
        rf.addRow("What's on now", self.now_order)
        self.station_count = QComboBox()
        self._station_counts = [20, 40, 80, 150, 300]
        self.station_count.addItems([str(n) for n in self._station_counts])
        cur_n = int(s.value("similar_station_count", 40))
        self.station_count.setCurrentIndex(min(range(len(self._station_counts)),
                                               key=lambda i: abs(self._station_counts[i] - cur_n)))
        self.station_count.setMaximumWidth(110)
        self.station_count.setToolTip("How many stations “Stations like this one” shows, best matches first")
        rf.addRow("Similar stations to show", self.station_count)

        section("Songs in your library")
        self.copy_from = QComboBox()
        self.copy_from.addItems(["From the start", "From the same point"])
        self.copy_from.setCurrentIndex(1 if s.value("radio_copy_from", "start") == "same" else 0)
        self.copy_from.setToolTip("When the station plays a song you have, ▶ Play your copy plays it from your "
                                  "library — from the start, or from about where the radio was (stations don't "
                                  "say exactly, so it can be a few seconds out)")
        self.copy_from.setMaximumWidth(220)
        rf.addRow("Play your copy", self.copy_from)
        self.copy_note = QCheckBox("Notify me when the station plays a song I have")
        self.copy_note.setChecked(s.value("radio_copy_note", False, bool))
        self.copy_note.setToolTip("A note at the top of the window (or a desktop notification) with a button "
                                  "to play your own copy")
        rf.addRow("", self.copy_note)

        section("Adverts")
        self.dim_ads = QCheckBox("Turn down adverts and jingles (experimental)")
        self.dim_ads.setChecked(s.value("radio_dim_ads", False, bool))
        self.dim_ads.setToolTip("When a station shows no song between songs — or says Advert, Jingle and so "
                                "on — the sound goes down until the next song. Right-click the station picture "
                                "to mark a break yourself.")
        rf.addRow("", self.dim_ads)
        self.dim_level = QComboBox()
        self._dim_levels = [v for v, _ in LEVELS]
        self.dim_level.addItems([t for _, t in LEVELS])
        cur_l = float(s.value("radio_dim_level", 0.25))
        self.dim_level.setCurrentIndex(min(range(len(self._dim_levels)), key=lambda i: abs(self._dim_levels[i] - cur_l)))
        self.dim_level.setToolTip("How loud adverts play (of your volume)")
        self.dim_level.setMaximumWidth(140)
        self.dim_longest = QComboBox()
        self._dim_longest = [v for v, _ in LONGEST]
        self.dim_longest.addItems([t for _, t in LONGEST])
        cur_m = float(s.value("radio_dim_longest", 4))
        self.dim_longest.setCurrentIndex(min(range(len(self._dim_longest)),
                                             key=lambda i: abs(self._dim_longest[i] - cur_m)))
        self.dim_longest.setToolTip("A break longer than this is probably a programme, not adverts: "
                                    "the sound comes back up")
        self.dim_longest.setMaximumWidth(140)
        rf.addRow("Advert volume", self.dim_level)
        rf.addRow("Turn back up after", self.dim_longest)

        def dim_show(*_):
            for w in (self.dim_level, self.dim_longest):
                rf.setRowVisible(w, self.dim_ads.isChecked())
        self.dim_ads.toggled.connect(dim_show)
        dim_show()

        from musicwell.alerts import EVERY, data_per_hour
        section("Song alerts")
        self.alerts_on = QCheckBox("Notify me when a favourite station plays…")
        self.alerts_on.setChecked(s.value("radio_alerts", False, bool))
        self.alerts_on.setToolTip("Every few minutes Musicwell checks what your favourite stations are playing "
                                  "— even when the Radio page isn't open — and shows a notification with a "
                                  "Listen button")
        self.alert_liked = QCheckBox("Songs I've liked")
        self.alert_liked.setChecked(s.value("radio_alert_liked", True, bool))
        self.alert_liked_artists = QCheckBox("Artists I've liked songs by")
        self.alert_liked_artists.setChecked(s.value("radio_alert_liked_artists", True, bool))
        self.alert_library = QCheckBox("Any artist in my library (can be a lot)")
        self.alert_library.setChecked(s.value("radio_alert_library", False, bool))
        self.alert_artists = QLineEdit(s.value("radio_alert_artists", "") or "")
        self.alert_artists.setPlaceholderText("Other artists, separated by commas")
        self.alert_artists.setToolTip("Artists to watch for, separated by commas")
        self.alert_every = QComboBox()
        self._alert_every = [m for m, _ in EVERY]
        self.alert_every.addItems(["1 minute" if t == "minute" else t for _, t in EVERY])
        self.alert_every.setToolTip("How often each station is checked. More often catches short songs sooner, "
                                    "and uses a little more data.")
        cur_e = float(s.value("radio_alert_every", 2))
        self.alert_every.setCurrentIndex(min(range(len(self._alert_every)),
                                             key=lambda i: abs(self._alert_every[i] - cur_e)))
        self.alert_every.setMaximumWidth(140)
        self.alert_which = QComboBox()
        self.alert_which.addItems(["All favourites", "Chosen stations"])
        self.alert_which.setToolTip("Which of your favourite stations to check")
        self.alert_which.setCurrentIndex(1 if s.value("radio_alert_which", "all") == "chosen" else 0)
        self._alert_ids = []
        try:
            self._alert_ids = list(json.loads(s.value("radio_alert_stations", "[]") or "[]"))
        except (TypeError, ValueError):
            pass
        self.alert_pick = QPushButton("Choose…")
        self.alert_pick.clicked.connect(self._pick_alert_stations)
        self.alert_when = QComboBox()
        self.alert_when.addItems(["Keep checking", "Pause checking"])
        self.alert_when.setToolTip("While you're listening to a station, keep checking your other stations "
                                   "(to hear about something you like elsewhere), or pause until you stop the radio")
        self.alert_when.setCurrentIndex(1 if s.value("radio_alert_when", "always") == "not_radio" else 0)
        self.alert_when.setMaximumWidth(220)
        self.alert_open = QComboBox()
        self.alert_open.addItems(["Radio tab", "Current layout"])
        self.alert_open.setToolTip("Clicking Listen on an alert tunes in to the station — and shows the Radio tab, "
                                   "or keeps the layout you're in")
        self.alert_open.setCurrentIndex(0 if s.value("radio_alert_open", True, bool) else 1)
        self.alert_open.setMaximumWidth(220)
        rf.addRow("", self.alerts_on)
        alert_rows = []
        for c in (self.alert_liked, self.alert_liked_artists, self.alert_library, self.alert_artists):
            box = indent(c)
            rf.addRow("", box)
            alert_rows.append(box)
        rf.addRow("Notification action", self.alert_open)
        stations_row = wrow(self.alert_which, self.alert_pick)
        rf.addRow("Check every", self.alert_every)
        rf.addRow("Stations to check", stations_row)
        rf.addRow("While listening", self.alert_when)
        self.alert_data = rnote("")
        alert_rows += [self.alert_every, stations_row, self.alert_when, self.alert_open, self.alert_data]
        self._alert_widgets = [self.alert_liked, self.alert_liked_artists, self.alert_library, self.alert_artists,
                               self.alert_every, self.alert_which, self.alert_pick, self.alert_when, self.alert_open]

        def alerts_enable(*_):
            on = self.alerts_on.isChecked()
            for row in alert_rows:  # details only when enabled
                rf.setRowVisible(row, on)
            self.alert_pick.setVisible(self.alert_which.currentIndex() == 1)
            n = self._alert_station_count()
            mins = self._alert_every[self.alert_every.currentIndex()]
            mb = data_per_hour(n, mins)
            self.alert_data.setText(f"About {mb:.0f} MB of data an hour, only while Musicwell is open."
                                    if mb >= 1 else "Under 1 MB of data an hour, only while Musicwell is open.")
        self._alerts_enable = alerts_enable
        for sig in (self.alerts_on.toggled, self.alert_every.currentIndexChanged,
                    self.alert_which.currentIndexChanged):
            sig.connect(alerts_enable)
        alerts_enable()
        self._page("Radio", radio)
        self._build_search_page(s)

        from musicwell.desktop import Tray
        dk = QGroupBox("Desktop")
        df = QFormLayout(dk)
        df.setVerticalSpacing(9)
        win = sys.platform == "win32"
        self.menu_entry = None
        if sys.platform.startswith("linux") and not os.environ.get("SNAP"):  # a snap has its own menu entry
            from musicwell import menuentry
            # installed by a package or another tool: leave it alone
            if menuentry.installed() or not menuentry.known_to_desktop():
                self.menu_entry = QCheckBox("Show Musicwell in the applications menu")
                self.menu_entry.setChecked(menuentry.installed())
                self.menu_entry.setToolTip("Adds Musicwell, with its icon, to your applications menu so you can "
                                           "start it from there and pin it — and the desktop shows its icon on "
                                           "the window. Follows the AppImage if you move it.")
                df.addRow("", self.menu_entry)
        self.mpris = QCheckBox("Media keys" if win else "Media keys and desktop media controls")
        self.mpris.setChecked(s.value("mpris", True, bool))
        self.mpris.setToolTip("Your keyboard's play/pause, next and previous keys work even when Musicwell is in "
                              "the background." if win else
                              "Your keyboard's play/pause, next and previous keys, the desktop's media controls "
                              "(the KDE media widget, the GNOME clock menu…), the lock screen and phone remotes "
                              "such as KDE Connect control Musicwell (MPRIS).")
        df.addRow("", self.mpris)
        why = getattr(getattr(self.window, "desktop", None), "error", "")
        if why:
            bad = _note("Not available right now.")
            bad.setToolTip(why)
            df.addRow("", bad)
        self.tray = QCheckBox("Show an icon in the system tray")
        self.tray.setChecked(s.value("tray", False, bool))
        self.tray.setToolTip("Click the icon to show or hide the window, middle-click to play or pause; "
                             "right-click for the song, the buttons and Quit.")
        self.close_to_tray = QCheckBox("Keep playing when the window is closed")
        self.close_to_tray.setToolTip("Closing the window hides it in the tray instead of quitting")
        self.close_to_tray.setChecked(s.value("close_to_tray", False, bool))
        self.start_in_tray = QCheckBox("Start hidden in the tray")
        self.start_in_tray.setChecked(s.value("start_in_tray", False, bool))
        df.addRow("", self.tray)
        tray_rows = [_row(cb, indent=26) for cb in (self.close_to_tray, self.start_in_tray)]
        for r in tray_rows:
            df.addRow("", r)
        if not Tray.available() and not win:
            tnote = _note("No system tray on this desktop.")
            tnote.setToolTip("On GNOME, the “AppIndicator and KStatusNotifierItem Support” extension adds one. "
                             "Until then, closing the window quits Musicwell as usual.")
            df.addRow("", tnote)

        def tray_show(on):
            for r in tray_rows:
                df.setRowVisible(r, on)
        self.tray.toggled.connect(tray_show)
        tray_show(self.tray.isChecked())
        self.notify = QCheckBox("Notify me when the song changes")
        self.notify.setChecked(s.value("notify", False, bool))
        self.notify.setToolTip("A Windows notification with the song and the artist." if win else
                               "The desktop's own pop-up, with the cover, the song and the artist — and a "
                               "Next button where the desktop supports one.")
        self.notify_bg = QCheckBox("Only when Musicwell is in the background")
        self.notify_bg.setChecked(s.value("notify_background_only", True, bool))
        df.addRow("", self.notify)
        nb = _row(self.notify_bg, indent=26)
        df.addRow("", nb)
        df.setRowVisible(nb, self.notify.isChecked())
        self.notify.toggled.connect(lambda on: df.setRowVisible(nb, on))
        self._page("Desktop", dk)

        lyr = QGroupBox("Lyrics")
        lf = QFormLayout(lyr)
        lf.setVerticalSpacing(9)
        self.lyrics_online = QCheckBox("Download missing lyrics")
        self.lyrics_online.setToolTip("Lyrics come from a .lrc or .txt file next to the song, then the song's own "
                                      "tags, then LRCLIB (lrclib.net) — a free lyrics database, no account needed")
        self.lyrics_online.setChecked(s.value("lyrics_online", True, bool))
        lf.addRow("", self.lyrics_online)
        self.lyrics_save = QCheckBox("Save downloaded lyrics next to the song")
        self.lyrics_save.setToolTip("As a .lrc file with the song's name, so other apps can use them too")
        self.lyrics_save.setChecked(s.value("lyrics_save_lrc", False, bool))
        lf.addRow("", self.lyrics_save)
        lretry = QPushButton("Retry missing")
        lretry.setToolTip("Look again for the lyrics that weren't found")
        lretry.clicked.connect(self._retry_lyrics)
        lf.addRow("", _row(lretry))
        self._page("Lyrics", lyr)
        self._build_shortcuts_page()

        self._build_pages()
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        from musicwell import APP_NAME, __version__
        about = buttons.addButton(f"About {APP_NAME} {__version__}".strip(), QDialogButtonBox.HelpRole)
        about.setToolTip("Version, what's new, credits and system details (F1)")
        about.clicked.connect(self._about)
        lay.addWidget(buttons)

    def _build_shortcuts_page(self):
        from PySide6.QtWidgets import QKeySequenceEdit
        box = QGroupBox("Shortcuts")
        f = QFormLayout(box)
        f.setVerticalSpacing(7)
        note = QLabel("Click a box and press the keys you want. Clear removes a shortcut.")
        note.setObjectName("NowMeta")
        note.setWordWrap(True)
        f.addRow(note)
        self._sc_edits = {}
        keys = self.window.shortcut_keys() if hasattr(self.window, "shortcut_keys") else {}
        for i, name, default, _fn in (self.window.shortcut_actions() if hasattr(self.window, "shortcut_actions") else []):
            ed = QKeySequenceEdit(QKeySequence(keys.get(i, default)))
            ed.setMaximumSequenceLength(1)
            ed.setToolTip(f"Usually {default}" if default else "")
            clear = QPushButton("Clear")
            clear.setToolTip("No shortcut")
            clear.clicked.connect(ed.clear)
            f.addRow(name, _row(ed, clear))
            self._sc_edits[i] = (ed, default)
        reset = QPushButton("Reset all to the usual keys")
        reset.clicked.connect(lambda: [ed.setKeySequence(QKeySequence(d)) for ed, d in self._sc_edits.values()])
        f.addRow("", _row(reset))
        self._page("Shortcuts", box)

    def _save_shortcuts(self, s):
        if not getattr(self, "_sc_edits", None):
            return
        mine, used, clashes = {}, {}, []
        names = {i: n for i, n, _d, _f in self.window.shortcut_actions()}
        for i, (ed, default) in self._sc_edits.items():
            k = ed.keySequence().toString(QKeySequence.PortableText)
            if k and k in used:  # the same keys twice: the first one keeps them
                clashes.append(f"{k}: kept for “{names[used[k]]}”, removed from “{names[i]}”")
                k = ""
            elif k:
                used[k] = i
            if k != default:
                mine[i] = k
        s.setValue("shortcuts", json.dumps(mine))
        if clashes:
            QMessageBox.information(self, "Shortcuts", "Some keys were used twice:\n\n" + "\n".join(clashes))

    def _about(self):
        from musicwell.about import AboutDialog
        AboutDialog(self.window, self).exec()  # on top of Settings

    def _build_search_page(self, s):
        from musicwell import freesearch as FS
        page = QGroupBox("Search")
        f = QFormLayout(page)
        f.setVerticalSpacing(9)

        def combo(items, cur, tip="", width=220):
            c = QComboBox()
            for key, text in items:
                c.addItem(text, key)
            c.setCurrentIndex(max(0, c.findData(cur)))
            if tip:
                c.setToolTip(tip)
            c.setMaximumWidth(width)
            return c

        f.addRow(_heading("Library", first=True))
        self.lib_mode = combo([("type", "As I type"), ("enter", "When I press Enter")],
                              s.value("lib_search_mode", "type") or "type",
                              "As I type: the list follows every letter. When I press Enter: handy for a big "
                              "library")
        f.addRow("Search", self.lib_mode)
        from musicwell import query as Q
        cur_fields = Q.PLAIN_FIELDS or Q.DEFAULT_PLAIN
        self.plain_boxes = {}
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        short = {"other": "Comment, label, mood", "path": "File name"}
        for i, (key, text) in enumerate(Q.PLAIN_CHOICES):
            cb = QCheckBox(short.get(key, text))
            cb.setToolTip(text)
            cb.setChecked(key in cur_fields)
            self.plain_boxes[key] = cb
            grid.addWidget(cb, i // 3, i % 3)
        gw = QWidget()
        gw.setLayout(grid)
        gw.setToolTip("Where your words are looked for (not artist=… or year>…, which look where they say)")
        f.addRow("Search in", gw)
        f.addRow(_heading("Online results"))
        mode = s.value("lib_online_mode", "")
        if not mode:
            mode = "pause" if s.value("lib_online", True, bool) else "off"
        self.online_mode = combo([("pause", "As I type"), ("enter", "When I press Enter"),
                                  ("off", "Never")], mode,
                                 "A search of your library can also look in the free online sources below; what "
                                 "they have shows in a line under your songs")
        f.addRow("Search online too", self.online_mode)
        self.online_delay = combo([("1", "1 second"), ("2", "2 seconds"), ("3", "3 seconds")],
                                  str(s.value("lib_online_delay", "1") or "1"),
                                  "How long a pause in typing before looking online", width=180)
        f.addRow("Wait before looking", self.online_delay)
        self.online_open = combo([("closed", "Folded"), ("open", "Open")],
                                 "open" if s.value("lib_online_open", False, bool) else "closed",
                                 "Folded: click the line under your songs to see them", width=180)
        f.addRow("Show online results", self.online_open)

        def online_enable(*_):
            on = self.online_mode.currentData() != "off"
            f.setRowVisible(self.online_delay, on and self.online_mode.currentData() == "pause")
            f.setRowVisible(self.online_open, on)
        self.online_mode.currentIndexChanged.connect(online_enable)
        online_enable()
        f.addRow(_heading("Online sources"))
        self.similar_archive.setText("Internet Archive")
        self.similar_openverse.setText("Openverse")
        self.similar_audius.setText("Audius")
        self.search_my = QCheckBox("My sources")
        self.search_my.setToolTip("The feeds, playlists and folders you've added in Discover")
        self.search_my.setChecked(s.value("search_my", True, bool))
        src = QGridLayout()
        src.setContentsMargins(0, 0, 0, 0)
        for n, w in enumerate((self.similar_archive, self.similar_openverse, self.similar_audius, self.search_my)):
            src.addWidget(w, n // 2, n % 2)
        sw = QWidget()
        sw.setLayout(src)
        sw.setToolTip("Free music to search in Discover, Find similar and under your library's search")
        f.addRow("Search in", sw)
        self.def_field = combo(FS.FIELDS, s.value("free_search_field", "any") or "any",
                               "What Discover → Search online looks for your words in to start with", width=180)
        f.addRow("Match words in", self.def_field)
        self.artist_mode = combo([("all", "Everything with the name"),
                                  ("artist", "Only songs by the artist")],
                                 s.value("artist_search_mode", "all") or "all",
                                 "When you search for an artist you have: everything with their name (more "
                                 "results), or just their songs (closer matches)")
        f.addRow("Artist searches", self.artist_mode)
        self.f_strict_s = QCheckBox("Close matches only")
        self.f_strict_s.setToolTip("Every word has to be where you asked")
        self.f_strict_s.setChecked(s.value("free_strict", True, bool))
        self.f_short_s = QCheckBox("Hide clips under a minute")
        self.f_short_s.setToolTip("Loops, jingles and sound effects")
        self.f_short_s.setChecked(s.value("free_no_short", True, bool))
        self.f_live_s = QCheckBox("Hide live recordings")
        self.f_live_s.setChecked(s.value("free_no_live", False, bool))
        f.addRow("Filters", self.f_strict_s)
        f.addRow("", self.f_short_s)
        f.addRow("", self.f_live_s)
        f.addRow(_heading("Radio"))
        self.radio_limit = combo([("50", "50"), ("150", "150"), ("300", "300")],
                                 str(s.value("radio_search_limit", "150") or "150"),
                                 "How many stations a search on the Radio page shows, most popular first", width=110)
        f.addRow("Stations to show", self.radio_limit)
        self._page("Search", page)

    def _save_search(self, s):
        s.setValue("lib_search_mode", self.lib_mode.currentData())
        picked = [k for k, cb in self.plain_boxes.items() if cb.isChecked()]
        s.setValue("search_plain_fields", json.dumps(picked or ["title", "artist", "album"]))
        s.setValue("lib_online_mode", self.online_mode.currentData())
        s.setValue("lib_online", self.online_mode.currentData() != "off")
        s.setValue("lib_online_delay", self.online_delay.currentData())
        s.setValue("lib_online_open", self.online_open.currentData() == "open")
        s.setValue("search_my", self.search_my.isChecked())
        s.setValue("free_search_field", self.def_field.currentData())
        s.setValue("artist_search_mode", self.artist_mode.currentData())
        s.setValue("free_strict", self.f_strict_s.isChecked())
        s.setValue("free_no_short", self.f_short_s.isChecked())
        s.setValue("free_no_live", self.f_live_s.isChecked())
        s.setValue("radio_search_limit", self.radio_limit.currentData())

    def _alert_station_count(self) -> int:
        from musicwell import radio as R
        favs = [st for st in self.window.stations.favourites() if st.get("url") and not R.needs_direct(st)]
        if self.alert_which.currentIndex() == 1:
            favs = [st for st in favs if R.station_id(st) in self._alert_ids]
        return len(favs)

    def _pick_alert_stations(self):
        """Choose which favourite stations to watch for song alerts."""
        from musicwell import radio as R
        d = QDialog(self)
        d.setWindowTitle("Stations for song alerts")
        lay = QVBoxLayout(d)
        lay.addWidget(QLabel("Tell me what these stations play:"))
        lst = QListWidget()
        favs = [st for st in self.window.stations.favourites() if st.get("url")]
        for st in favs:
            it = QListWidgetItem(st["name"])
            k = R.station_id(st)
            it.setData(Qt.UserRole, k)
            if R.needs_direct(st):
                it.setFlags(it.flags() & ~Qt.ItemIsEnabled)
                it.setText(st["name"] + "  (doesn't say what it's playing)")
                it.setCheckState(Qt.Unchecked)
            else:
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Checked if k in self._alert_ids else Qt.Unchecked)
            lst.addItem(it)
        if not favs:
            lay.addWidget(QLabel("No favourite stations yet: click ☆ next to a station on the Radio page."))
        lay.addWidget(lst)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        lay.addWidget(bb)
        d.resize(420, 420)
        self._alert_dialog = d
        if d.exec():
            self._alert_ids = [lst.item(i).data(Qt.UserRole) for i in range(lst.count())
                               if lst.item(i).checkState() == Qt.Checked]
            self._alerts_enable()

    def _page(self, title: str, group: QGroupBox):
        self._groups.append((title, group))

    def _build_pages(self):
        """Build the pages, each a scrolling column of sections."""
        from PySide6.QtWidgets import QScrollArea
        wanted = ["Theme"] if self.colours_only else PAGES
        self._page_widgets = {}
        for name in wanted:
            parts = [(t, g) for t, g in self._groups if PAGE_OF.get(t) == name]
            page = QWidget()
            pl = QVBoxLayout(page)
            pl.setContentsMargins(4, 4, 12, 4)
            pl.setSpacing(6)
            for t, g in parts:
                if len(parts) > 1:
                    pl.addWidget(_heading(SECTION_NAMES.get(t, t), first=(t, g) == parts[0]))
                g.setTitle("")
                g.setFlat(True)
                g.setStyleSheet("QGroupBox { border: none; margin-top: 0; padding: 0; }")
                pl.addWidget(g)
            pl.addStretch(1)
            sc = QScrollArea()
            sc.setWidgetResizable(True)
            sc.setFrameShape(QFrame.NoFrame)
            page.setObjectName("SettingsPage")
            sc.setStyleSheet("QScrollArea { background: transparent; } "
                             "QWidget#SettingsPage { background: transparent; }")
            sc.setWidget(page)
            sc.viewport().setAutoFillBackground(False)
            page.setAutoFillBackground(False)
            self.stack.addWidget(sc)
            self._page_widgets[name] = sc
            if not self.colours_only:
                self.side.addItem(name)
        # sections that moved out of Settings are still built so their values save unchanged
        for t, g in self._groups:
            if PAGE_OF.get(t) not in wanted:
                g.hide()
                g.setParent(self)
        last = self.window.settings.value("settings_page", "Library")
        self.side.setCurrentRow(PAGES.index(last) if last in PAGES else 0)
        # wide enough for the widest page
        widest = max((sc.widget().sizeHint().width() for sc in self._page_widgets.values()), default=600)
        avail = self.screen().availableGeometry().width() if self.screen() else 1400
        extra = 0 if self.colours_only else 190 + 40
        for sc in self._page_widgets.values():
            sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.resize(min(max(widest + extra + 40, 640 if self.colours_only else 820), avail - 80), 660)

    def _side_picked(self, row: int):
        if 0 <= row < len(PAGES):
            self.stack.setCurrentWidget(self._page_widgets[PAGES[row]])
            self.window.settings.setValue("settings_page", PAGES[row])

    def _searchable(self):
        """(page, widget, text) for every labelled setting."""
        out = []
        for name in PAGES:
            sc = self._page_widgets.get(name)
            if sc is None:
                continue
            for w in sc.widget().findChildren(QWidget):
                texts = []
                if isinstance(w, (QCheckBox, QPushButton, QLabel)):
                    texts.append(w.text())
                if w.toolTip():
                    texts.append(w.toolTip())
                if isinstance(w, QComboBox):
                    texts += [w.itemText(i) for i in range(w.count())]
                text = " ".join(t for t in texts if t)
                if text.strip():
                    out.append((name, w, text))
        return out

    def _find_changed(self, text: str):
        import re as _re
        words = [x for x in text.lower().split() if x]
        self.results.clear()
        if not words:
            self._side_picked(self.side.currentRow())
            return
        self.results_title.setText(f"Settings for “{text.strip()}”")
        self.stack.setCurrentWidget(self.results_page)
        seen = set()
        for name, w, t in self._searchable():
            plain = _re.sub(r"<[^>]+>", "", t).replace("&&", "&")
            if all(x in plain.lower() for x in words):
                label = self._label_for(w) or plain.split("\n")[0]
                label = label.strip()
                if len(label) > 140:
                    label = label[:138].rsplit(" ", 1)[0] + "…"
                if (name, label.rstrip("…")) in seen:
                    continue
                seen.add((name, label.rstrip("…")))
                it = QListWidgetItem(f"{label}\n{name}")
                it.setData(Qt.UserRole, (name, w))
                self.results.addItem(it)
        if not self.results.count():
            it = QListWidgetItem("Nothing matches — try another word")
            it.setFlags(Qt.NoItemFlags)
            self.results.addItem(it)

    @staticmethod
    def _label_for(w) -> str:
        """The visible text for a setting: its own, or its form row label."""
        if isinstance(w, QCheckBox) and w.text():
            return w.text()
        p = w.parentWidget()
        if p is not None:
            forms = ([p.layout()] if isinstance(p.layout(), QFormLayout) else []) + p.findChildren(QFormLayout)
            for lay in forms:
                lab = lay.labelForField(w)
                if lab is not None and lab.text():
                    return lab.text()
        if isinstance(w, QPushButton) and w.text():
            return w.text()
        if isinstance(w, QLabel):
            return w.text()
        return ""

    def show_page(self, name: str):
        """Open on one page."""
        if name in PAGES:
            self.side.setCurrentRow(PAGES.index(name))
            self._side_picked(PAGES.index(name))

    def _result_picked(self, it):
        data = it.data(Qt.UserRole)
        if not data:
            return
        name, w = data
        self.find.blockSignals(True)
        self.find.clear()
        self.find.blockSignals(False)
        self.side.setCurrentRow(PAGES.index(name))
        self._side_picked(PAGES.index(name))
        sc = self._page_widgets[name]
        sc.ensureWidgetVisible(w, 40, 80)
        target = w
        if isinstance(w, QLabel):  # a form label: point at its setting
            p = w.parentWidget()
            if isinstance(p.layout() if p else None, QFormLayout):
                for r in range(p.layout().rowCount()):
                    li = p.layout().itemAt(r, QFormLayout.LabelRole)
                    fi = p.layout().itemAt(r, QFormLayout.FieldRole)
                    if li is not None and li.widget() is w and fi is not None and fi.widget() is not None:
                        target = fi.widget()
        self._flash_widget(target)

    def _flash_widget(self, w):
        """Highlight a setting briefly and focus it."""
        acc = self.window.theme.accent.name()
        old = w.styleSheet()
        w.setStyleSheet(old + f"; border: 2px solid {acc}; border-radius: 6px;")
        w.setFocus()
        QTimer.singleShot(1600, lambda: w.setStyleSheet(old))

    def _theme_picked(self, it, _prev=None):
        """Preview the theme now (Cancel restores the old one)."""
        if it is None:
            return
        from musicwell import theme as th
        key = it.data(Qt.UserRole)
        self._accent = QColor(th.PALETTES[key]["accent"])
        self._paint_accent()
        self._preview()

    def _write_colours(self):
        s = self.window.settings
        it = self.theme.currentItem()
        mode = self._art_keys[self.artmode.currentIndex()]
        s.setValue("theme", it.data(Qt.UserRole) if it else "dark")
        s.setValue("accent", self._accent.name())
        s.setValue("artwork_colours", mode)
        s.setValue("accent_follow", mode != "off")
        s.setValue("artwork_background", self._artbg_keys[self.artbg.currentIndex()])

    def _preview(self):
        """Preview colours now (Cancel restores them). Restyling takes a moment, so changes are debounced."""
        t = getattr(self, "_preview_timer", None)
        if t is None:
            t = self._preview_timer = QTimer(self)
            t.setSingleShot(True)
            t.setInterval(180)
            t.timeout.connect(self._preview_now)
        t.start()

    def _preview_now(self):
        self._write_colours()
        self.window.update_colours(force=True)

    def reject(self):
        if getattr(self, "_preview_timer", None) is not None:
            self._preview_timer.stop()  # drop a pending preview
        s = self.window.settings
        for k, v in self._orig.items():
            if v is None:
                s.remove(k)
            else:
                s.setValue(k, v)
        self.window.update_colours(force=True)
        super().reject()

    def _paint_accent(self):
        c = self._accent
        fg = "#000" if c.lightness() > 140 else "#fff"
        self.accent_btn.setText(c.name())
        self.accent_btn.setStyleSheet(f"background:{c.name()}; color:{fg}; border:none;")

    def _pick_accent(self):
        c = QColorDialog.getColor(self._accent, self, "Accent colour")
        if c.isValid():
            self._accent = c
            self._paint_accent()
            self._preview()

    @staticmethod
    def _source_list(names: dict, enabled: list[str]) -> QListWidget:
        lst = QListWidget()
        lst.setObjectName("Pane")
        lst.setDragDropMode(QAbstractItemView.InternalMove)
        lst.setDefaultDropAction(Qt.MoveAction)
        lst.setMaximumHeight(150)
        order = list(enabled) + [k for k in names if k not in enabled]
        for k in order:
            it = QListWidgetItem(names[k])
            it.setData(Qt.UserRole, k)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsDragEnabled)
            it.setCheckState(Qt.Checked if k in enabled else Qt.Unchecked)
            lst.addItem(it)
        return lst

    @staticmethod
    def _checked_sources(lst: QListWidget) -> list[str]:
        return [lst.item(i).data(Qt.UserRole) for i in range(lst.count())
                if lst.item(i).checkState() == Qt.Checked]

    def _retry_missing(self):
        from musicwell.paths import cache_dir
        n = 0
        for sub in ("covers", "artists"):
            for f in (cache_dir() / sub).glob("*.miss"):
                f.unlink(missing_ok=True)
                n += 1
        QMessageBox.information(self, "Online images", f"Musicwell will look again for {n} missing image"
                                f"{'s' if n != 1 else ''} as songs play.")

    def _clear_cache(self):
        if ClearCacheDialog(self.window, self).exec():
            self.window._flash("Cache cleared — it will be looked up again as it's needed", 5000)
            self._show_storage()

    def _show_storage(self):
        """Library -> Storage: space used by each kind of data."""
        w = self.window

        def size(paths) -> int:
            total = 0
            for p in paths:
                try:
                    total += p.stat().st_size
                except OSError:
                    pass
            return total

        def mb(n: int) -> str:
            return f"{n / 1_000_000:.1f} MB" if n >= 100_000 else f"{n // 1000} KB"
        rows = []
        try:
            img = w.images.cache_files(True)
            rows.append(("Covers and artist photos", size(img)))
            lyr = getattr(w, "lyrics", None)
            rows.append(("Lyrics found online", size(lyr.cache_files()) if lyr else 0))
            wav = getattr(w, "waveforms", None)
            rows.append(("Seek bar waveforms", size(wav.cache_files()) if wav else 0))
            from musicwell import similar as similar_mod
            rows.append(("Similar artists and genres", size(similar_mod.cache_files())))
        except Exception:
            self.storage.setText("Couldn't work out the sizes")
            return
        total = sum(n for _, n in rows)
        cells = "".join(f"<tr><td>{name}</td><td align='right' style='padding-left: 18px'>{mb(n)}</td></tr>"
                        for name, n in rows)
        cells += (f"<tr><td style='padding-top: 4px'><b>Altogether</b></td>"
                  f"<td align='right' style='padding-left: 18px; padding-top: 4px'><b>{mb(total)}</b></td></tr>")
        self.storage.setText(f"<table cellspacing='0' cellpadding='1'>{cells}</table>")

    def _open_cache_folder(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        from musicwell.paths import cache_dir
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(cache_dir())))

    def _retry_lyrics(self):
        from musicwell.paths import cache_dir
        n = 0
        for f in (cache_dir() / "lyrics").glob("*.miss"):
            f.unlink(missing_ok=True)
            n += 1
        lyr = getattr(self.window, "lyrics", None)
        if lyr is not None:
            lyr._mem = {k: v for k, v in lyr._mem.items() if v is not None}
        QMessageBox.information(self, "Lyrics", f"Musicwell will look again for lyrics for {n} song"
                                f"{'s' if n != 1 else ''} as they play.")

    def _fill_folders(self):
        self.folders.clear()
        self.folders.addItems(self.lib.folders())

    def _add(self):
        d = ask_music_folder(self, self.lib.folders())
        if d:
            self.lib.add_folder(d)
            self._fill_folders()

    def _remove(self):
        it = self.folders.currentItem()
        if it:
            self.lib.remove_folder(it.text())
            self._fill_folders()

    def _save(self):
        s = self.window.settings
        if getattr(self, "_preview_timer", None) is not None:
            self._preview_timer.stop()  # apply_settings shows the chosen colours
        self._write_colours()
        s.setValue("artist_online", self.artist_on.isChecked())
        s.setValue("album_online", self.album_on.isChecked())
        s.setValue("album_sources", json.dumps(self._checked_sources(self.album_src)))
        s.setValue("artist_sources", json.dumps(self._checked_sources(self.artist_src)))
        s.setValue("save_covers", self.save_covers.isChecked())
        s.setValue("web_image_engine", self.web_engine.currentData())
        s.setValue("follow_playing", self._follow_keys[self.follow_playing.currentIndex()])
        s.setValue("fade_in", self.fade_in.value())
        s.setValue("fade_out", self.fade_out.value())
        s.setValue("fade_within_album", self.fade_album.isChecked())
        s.setValue("similar_continue", self.similar_continue.isChecked())
        s.setValue("decade_from", self._decade_keys[self.decade_from.currentIndex()])
        s.setValue("original_year_tag", self.orig_tag.currentData() or "")
        s.setValue("replaygain", self._rg_keys[self.rg_mode.currentIndex()])
        s.setValue("replaygain_preamp", self.rg_preamp.value())
        s.setValue("replaygain_untagged", self.rg_untagged.value())
        s.setValue("replaygain_clip", self.rg_clip.isChecked())
        s.setValue("mpris", self.mpris.isChecked())
        s.setValue("tray", self.tray.isChecked())
        if self.menu_entry is not None:
            from musicwell import menuentry
            if self.menu_entry.isChecked() and not menuentry.installed():
                if menuentry.install():
                    self.window._flash("Musicwell is in the applications menu", 4000)
            elif not self.menu_entry.isChecked() and menuentry.installed():
                menuentry.remove()
        s.setValue("close_to_tray", self.close_to_tray.isChecked())
        s.setValue("start_in_tray", self.start_in_tray.isChecked())
        s.setValue("notify", self.notify.isChecked())
        self._save_shortcuts(s)
        s.setValue("notify_background_only", self.notify_bg.isChecked())
        s.setValue("similar_online", self.similar_online.isChecked())
        s.setValue("similar_archive", self.similar_archive.isChecked())
        s.setValue("similar_openverse", self.similar_openverse.isChecked())
        s.setValue("similar_audius", self.similar_audius.isChecked())
        self._save_search(s)
        s.setValue("similar_station_count", self._station_counts[self.station_count.currentIndex()])
        s.setValue("radio_next", "stations" if self.radio_next.currentIndex() == 0 else "music")
        s.setValue("radio_now_song_first", self.now_order.currentIndex() == 1)
        s.setValue("radio_dim_ads", self.dim_ads.isChecked())
        s.setValue("radio_dim_level", self._dim_levels[self.dim_level.currentIndex()])
        s.setValue("radio_dim_longest", self._dim_longest[self.dim_longest.currentIndex()])
        s.setValue("radio_alerts", self.alerts_on.isChecked())
        s.setValue("radio_copy_from", "same" if self.copy_from.currentIndex() == 1 else "start")
        s.setValue("radio_copy_note", self.copy_note.isChecked())
        s.setValue("radio_alert_liked", self.alert_liked.isChecked())
        s.setValue("radio_alert_liked_artists", self.alert_liked_artists.isChecked())
        s.setValue("radio_alert_library", self.alert_library.isChecked())
        s.setValue("radio_alert_artists", self.alert_artists.text().strip())
        s.setValue("radio_alert_every", self._alert_every[self.alert_every.currentIndex()])
        s.setValue("radio_alert_which", "chosen" if self.alert_which.currentIndex() == 1 else "all")
        s.setValue("radio_alert_stations", json.dumps(self._alert_ids))
        s.setValue("radio_alert_when", "not_radio" if self.alert_when.currentIndex() == 1 else "always")
        s.setValue("radio_alert_open", self.alert_open.currentIndex() == 0)
        s.setValue("fade_transport", self._transport_ms[self.fade_transport.currentIndex()])
        s.setValue("lyrics_online", self.lyrics_online.isChecked())
        s.setValue("lyrics_save_lrc", self.lyrics_save.isChecked())
        s.setValue("cast_discovery", self.cast_disc.isChecked())
        s.setValue("artist_info_online", self.info_on.isChecked())
        s.setValue("sonos_discovery", self.sonos_disc.isChecked())
        s.setValue("sonos_addresses", self.sonos_addr.text().strip())
        try:
            port = int(self.cast_port.text())
            if 1024 <= port <= 65535:
                s.setValue("cast_port", port)
        except ValueError:
            pass
        self.accept()


class TagEditor(QDialog):
    """Edit tags on one or many tracks. Fields that differ are left alone unless typed in."""

    LABELS = {
        "title": "Title", "artist": "Artist", "album": "Album", "albumartist": "Album artist",
        "genre": "Genre", "date": "Year", "tracknumber": "Track", "discnumber": "Disc",
        "composer": "Composer", "comment": "Comment",
    }
    FROM_TRACK = {
        "title": "title", "artist": "artist", "album": "album", "albumartist": "albumartist",
        "composer": "composer", "comment": "comment",
        "genre": "genre", "date": "year", "tracknumber": "track", "discnumber": "disc",
    }

    def __init__(self, tracks: list[dict], parent=None):
        super().__init__(parent)
        self.tracks = tracks
        n = len(tracks)
        self.setWindowTitle("Edit tags" if n == 1 else f"Edit tags — {n} tracks")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        if n == 1:
            path = QLabel(tracks[0]["path"])
        else:
            path = QLabel(f"{n} tracks selected. Fields showing “(multiple values)” are kept as they are unless you type something.")
        path.setObjectName("EmptyText")
        path.setWordWrap(True)
        lay.addWidget(path)
        form = QFormLayout()
        self.edits: dict[str, QLineEdit] = {}
        self.originals: dict[str, str | None] = {}
        for key in tagio.EDITABLE:
            if n > 1 and key == "title":
                continue
            vals = {self._val(t, key) for t in tracks}
            e = QLineEdit()
            if len(vals) == 1:
                v = vals.pop()
                e.setText(v)
                self.originals[key] = v
            else:
                e.setPlaceholderText("(multiple values)")
                self.originals[key] = None
            self.edits[key] = e
            form.addRow(self.LABELS[key], e)
        lay.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setObjectName("Primary")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _val(self, t: dict, key: str) -> str:
        v = t[self.FROM_TRACK[key]]
        return str(v) if v not in (0, None) else ""

    def changes(self) -> dict[str, str]:
        out = {}
        for key, e in self.edits.items():
            orig = self.originals[key]
            text = e.text().strip()
            if orig is None:
                if text:
                    out[key] = text
            elif text != orig:
                out[key] = text
        return out

    def _save(self):
        changes = self.changes()
        if not changes:
            self.accept()
            return
        failed = []
        for t in self.tracks:
            try:
                tagio.write_tags(t["path"], changes)
            except Exception as ex:
                failed.append(f"{os.path.basename(t['path'])}: {ex}")
        if failed:
            QMessageBox.warning(self, "Some files weren't saved",
                                "\n".join(failed[:12]) + ("\n…" if len(failed) > 12 else ""))
        self.accept()


class CustomFieldsDialog(QDialog):
    """Custom fields (tags shown as columns): add, rename, delete."""

    def __init__(self, window, parent=None, table=None):
        super().__init__(parent or window)
        self.window = window
        self.table = table  # opened from a song list: new fields show there right away
        self.setWindowTitle("Custom fields")
        self.resize(560, 420)
        lay = QVBoxLayout(self)
        intro = QLabel("Custom fields show any tag from your music files as a column — in the song list, the "
                       "browser, the panel and searching. To make one, click <b>Add a tag…</b> and pick one of "
                       "the tags in your library, or type the name of a new one.")
        intro.setWordWrap(True)
        intro.setObjectName("EmptyText")
        lay.addWidget(intro)
        head = QLabel("YOUR CUSTOM FIELDS")
        head.setObjectName("PaneHeader")
        lay.addWidget(head)
        row = QHBoxLayout()
        self.list = QListWidget()
        self.list.setObjectName("Pane")
        self.list.setToolTip("Click one to rename or delete it")
        self.list.itemSelectionChanged.connect(self._update)
        self.list.currentItemChanged.connect(lambda *_: self._update())
        self.list.itemDoubleClicked.connect(lambda _: self._rename())
        row.addWidget(self.list, 1)
        side = QVBoxLayout()
        self.add_btn = QPushButton("Add a tag…")
        self.add_btn.setObjectName("Primary")
        self.add_btn.setToolTip("Pick one of the tags in your library, or type a new tag name")
        self.rename_btn = QPushButton("Rename…")
        self.delete_btn = QPushButton("Delete…")
        self.delete_btn.setToolTip("Removes the column from Musicwell — your music files keep the tag")
        for b, fn in ((self.add_btn, self._add), (self.rename_btn, self._rename), (self.delete_btn, self._delete)):
            b.clicked.connect(fn)
            side.addWidget(b)
        side.addStretch()
        row.addLayout(side)
        lay.addLayout(row, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._fill()

    def _fill(self, select: str | None = None):
        counts = self.window.library.tag_counts()
        self.list.clear()
        for f in F.custom_fields():
            tag = f.tags[0]
            n = counts.get(tag, 0)
            it = QListWidgetItem(f"{f.name}    ·  tag {tag.upper()}  ·  in {n:,} song{'s' if n != 1 else ''}")
            it.setData(Qt.UserRole, f.key)
            self.list.addItem(it)
            if f.key == select:
                self.list.setCurrentItem(it)
        if not self.list.count():
            it = QListWidgetItem("None yet — click Add a tag… to make one")
            it.setFlags(Qt.NoItemFlags)
            self.list.addItem(it)
        self._update()

    def _sel(self):
        it = self.list.currentItem()
        key = it.data(Qt.UserRole) if it and it.isSelected() else None
        return F.get(key) if key else None

    def _update(self):
        f = self._sel()
        for b in (self.rename_btn, self.delete_btn):
            b.setEnabled(f is not None)

    def _add(self):
        key = self.window._add_custom_field()
        if key:
            if self.table is not None:
                self.table.show_column(key)
            self._fill(key)

    def _rename(self):
        f = self._sel()
        if f is None:
            return
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "Rename custom field", "Column name:", text=f.name)
        if ok and name.strip():
            self.window._rename_custom_field(f.key, name.strip())
            self._fill(f.key)

    def _delete(self):
        f = self._sel()
        if f is None:
            return
        if QMessageBox.question(self, "Delete custom field",
                                f"Delete the custom field “{f.name}”?\n\nIt disappears from the song list, the "
                                "browser, the panel and searches. Your music files keep the tag.") != QMessageBox.Yes:
            return
        self.window._remove_custom_field(f.key)
        self._fill()


class BrowserColumnsDialog(QDialog):
    """Choose and order the browser's columns."""

    def __init__(self, fields: list[str], visible: bool = True, parent=None, add_custom=None):
        super().__init__(parent)
        self.add_custom = add_custom  # callable() -> new field key or None
        self.setWindowTitle("Browser columns")
        self.setMinimumSize(560, 420)
        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        top = QHBoxLayout()
        top.addWidget(QLabel("Start from a layout"))
        self.presets = QComboBox()
        self.presets.addItem("—")
        self.presets.addItems(list(PANE_PRESETS))
        self.presets.currentTextChanged.connect(self._load_preset)
        top.addWidget(self.presets, 1)
        lay.addLayout(top)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        a = QLabel("AVAILABLE")
        a.setObjectName("PaneHeader")
        b = QLabel(f"SHOWN, LEFT TO RIGHT  (up to {MAX_PANES})")
        b.setObjectName("PaneHeader")
        grid.addWidget(a, 0, 0)
        grid.addWidget(b, 0, 2)
        self.available = QListWidget()
        self.shown = QListWidget()
        self.shown.setDragDropMode(QAbstractItemView.InternalMove)
        self.shown.setDefaultDropAction(Qt.MoveAction)
        for w in (self.available, self.shown):
            w.setObjectName("Pane")
            w.setAlternatingRowColors(False)
        self.available.itemDoubleClicked.connect(lambda _: self._add())
        self.shown.itemDoubleClicked.connect(lambda _: self._remove())
        grid.addWidget(self.available, 1, 0)
        grid.addWidget(self.shown, 1, 2)

        mid = QVBoxLayout()
        mid.addStretch()
        self.add_btn = QPushButton("Add  →")
        self.add_btn.clicked.connect(self._add)
        self.rem_btn = QPushButton("←  Remove")
        self.rem_btn.clicked.connect(self._remove)
        self.up_btn = QPushButton("Move up")
        self.up_btn.clicked.connect(lambda: self._move(-1))
        self.down_btn = QPushButton("Move down")
        self.down_btn.clicked.connect(lambda: self._move(1))
        for w in (self.add_btn, self.rem_btn):
            mid.addWidget(w)
        mid.addSpacing(16)
        for w in (self.up_btn, self.down_btn):
            mid.addWidget(w)
        if self.add_custom:
            mid.addSpacing(16)
            custom = QPushButton("Custom fields…")
            custom.setToolTip("The Custom fields window: make any tag from your files a column (a new one is "
                              "added to the browser here), rename or delete them")
            custom.clicked.connect(self._new_custom)
            mid.addWidget(custom)
        mid.addStretch()
        grid.addLayout(mid, 1, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(2, 1)
        lay.addLayout(grid, 1)

        hint = QLabel("Double-click to add or remove; drag to reorder. Tip: right-click a column "
                      "header in the browser to change it on the spot.")
        hint.setObjectName("EmptyText")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.visible = QCheckBox("Show the column browser above the song list")
        self.visible.setChecked(visible)
        lay.addWidget(self.visible)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setObjectName("Primary")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        self._fill(fields)
        for w in (self.available, self.shown):
            w.itemSelectionChanged.connect(self._update_buttons)
        self.shown.model().rowsMoved.connect(lambda *a: self._update_buttons())

    def _item(self, key: str) -> QListWidgetItem:
        it = QListWidgetItem(PANE_FIELDS[key][0])
        it.setData(Qt.UserRole, key)
        return it

    def _fill(self, fields: list[str]):
        self.available.clear()
        self.shown.clear()
        for f in fields:
            self.shown.addItem(self._item(f))
        for key in PANE_FIELDS:
            if key not in fields:
                self.available.addItem(self._item(key))
        self._update_buttons()

    def _new_custom(self):
        """Open the Custom fields dialog; new fields join the browser list."""
        new = self.add_custom() or []
        shown = [k for k in self.result_fields() if k in PANE_FIELDS]
        self._fill(shown)
        for key in new:
            if key not in PANE_FIELDS:
                continue
            for i in range(self.available.count()):
                if self.available.item(i).data(Qt.UserRole) == key:
                    self.available.clearSelection()
                    self.available.setCurrentRow(i)
                    self.available.item(i).setSelected(True)
                    self._add()
                    break

    def _load_preset(self, name: str):
        if name in PANE_PRESETS:
            self._fill(PANE_PRESETS[name])

    def result_fields(self) -> list[str]:
        fields = [self.shown.item(i).data(Qt.UserRole) for i in range(self.shown.count())]
        return fields or list(DEFAULT_PANES)

    def _add(self):
        if self.shown.count() >= MAX_PANES:
            return
        for it in self.available.selectedItems():
            if self.shown.count() >= MAX_PANES:
                break
            self.available.takeItem(self.available.row(it))
            self.shown.addItem(it)
            self.shown.setCurrentItem(it)
        self._update_buttons()

    def _remove(self):
        for it in self.shown.selectedItems():
            if self.shown.count() <= 1:
                break
            self.shown.takeItem(self.shown.row(it))
            self.available.addItem(it)
        self._update_buttons()

    def _move(self, delta: int):
        row = self.shown.currentRow()
        new = row + delta
        if row < 0 or not 0 <= new < self.shown.count():
            return
        it = self.shown.takeItem(row)
        self.shown.insertItem(new, it)
        self.shown.setCurrentRow(new)
        self._update_buttons()

    def _update_buttons(self):
        n = self.shown.count()
        self.add_btn.setEnabled(bool(self.available.selectedItems()) and n < MAX_PANES)
        self.rem_btn.setEnabled(bool(self.shown.selectedItems()) and n > 1)
        row = self.shown.currentRow() if self.shown.selectedItems() else -1
        self.up_btn.setEnabled(row > 0)
        self.down_btn.setEnabled(0 <= row < n - 1)
        if self.presets.currentText() != "—" and PANE_PRESETS.get(self.presets.currentText()) != self.result_fields():
            self.presets.blockSignals(True)
            self.presets.setCurrentIndex(0)
            self.presets.blockSignals(False)


class CustomFieldDialog(QDialog):
    """Make any tag into a column."""

    def __init__(self, tag_counts: dict[str, int], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add a custom column")
        self.setMinimumSize(520, 480)
        taken = F.builtin_tag_names() | {f.tags[0] for f in F.custom_fields()}
        self.counts = {k: v for k, v in tag_counts.items() if k not in taken}
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        intro = QLabel("Type the name of a tag, or pick one of the tags found in your library below. It becomes "
                       "a column you can show in the song list, use in the browser and search for (e.g. "
                       "<i>catalognumber=XL</i>).")
        intro.setWordWrap(True)
        intro.setObjectName("EmptyText")
        lay.addWidget(intro)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Tag name — e.g. CATALOGNUMBER, MOOD, REPLAYGAIN_TRACK_GAIN")
        self.filter.textChanged.connect(self._refill)
        lay.addWidget(self.filter)
        head = QLabel("OR PICK ONE OF THE TAGS IN YOUR LIBRARY" if self.counts else
                      "No other tags were found in your files yet")
        head.setObjectName("PaneHeader")
        lay.addWidget(head)
        self.list = QListWidget()
        self.list.setObjectName("Pane")
        self.list.currentItemChanged.connect(self._picked)
        self.list.itemDoubleClicked.connect(lambda _: self._accept())
        lay.addWidget(self.list, 1)
        form = QFormLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("Shown as the column title")
        form.addRow("Column name", self.name)
        self.numeric = QCheckBox("Sort as numbers (e.g. for BPM-like values)")
        form.addRow("", self.numeric)
        lay.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.ok = buttons.button(QDialogButtonBox.Ok)
        self.ok.setText("Add column")
        self.ok.setObjectName("Primary")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self._auto_name = True
        self.name.textEdited.connect(lambda _: setattr(self, "_auto_name", False))
        self._refill()

    def _refill(self):
        q = tagio.norm_tag(self.filter.text())
        self.list.clear()
        for tag, n in sorted(self.counts.items(), key=lambda kv: (-kv[1], kv[0])):
            if q and q not in tag:
                continue
            it = QListWidgetItem(f"{tag.upper()}    —  {n:,} song{'s' if n != 1 else ''}")
            it.setData(Qt.UserRole, tag)
            self.list.addItem(it)
        if self._auto_name:
            self.name.setText(F.pretty_tag(q) if q else "")
        self.ok.setEnabled(bool(q))

    def _picked(self, it, _prev=None):
        if it is None:
            return
        tag = it.data(Qt.UserRole)
        self.filter.blockSignals(True)
        self.filter.setText(tag.upper())
        self.filter.blockSignals(False)
        if self._auto_name:
            self.name.setText(F.pretty_tag(tag))
        self.ok.setEnabled(True)

    def tag(self) -> str:
        return tagio.norm_tag(self.filter.text())

    def _accept(self):
        if self.tag():
            self.accept()

    def definition(self) -> dict:
        return {"tag": self.tag(), "name": self.name.text().strip() or F.pretty_tag(self.tag()),
                "numeric": self.numeric.isChecked()}


class ArrangeTabsDialog(QDialog):
    """Choose, order and add tabs."""

    def __init__(self, tabs: list[tuple], parent=None, add_menu=None, removable=None):
        """tabs: (page, name, shown, locked); locked tabs can't be hidden."""
        super().__init__(parent)
        self.setWindowTitle("Tabs")
        self.setMinimumSize(420, 560)
        self.removed: list[int] = []
        self._removable = removable or (lambda page: False)
        lay = QVBoxLayout(self)
        intro = QLabel("Untick a tab to remove it from the top (tick it to bring it back). Drag the tabs into the "
                       "order you'd like, or use the buttons. Add tab makes a tab of your own: a playlist, or a "
                       "search such as Favourites or genre=jazz. Ctrl+1, Ctrl+2… follow the tabs shown.")
        intro.setWordWrap(True)
        intro.setObjectName("EmptyText")
        lay.addWidget(intro)
        row = QHBoxLayout()
        self.list = QListWidget()
        self.list.setDragDropMode(QAbstractItemView.InternalMove)
        self.list.setDefaultDropAction(Qt.MoveAction)
        th_ = getattr(parent, "theme", None)
        acc = th_.accent if th_ is not None else self.palette().highlight().color()
        self.list.setStyleSheet(
            "QListWidget { padding: 4px; } QListWidget::item { padding: 7px 10px; border-radius: 5px; font-size: 11pt; }"
            f"QListWidget::item:selected {{ background: rgba({acc.red()},{acc.green()},{acc.blue()},0.25); }}"
            "QListWidget::indicator { width: 15px; height: 15px; border: 1px solid rgba(128,128,128,0.8); "
            "border-radius: 3px; margin-right: 6px; }"
            f"QListWidget::indicator:checked {{ background: {acc.name()}; border-color: {acc.name()}; }}")
        for tab in tabs:
            page, name = tab[0], tab[1]
            shown = tab[2] if len(tab) > 2 else True
            locked = tab[3] if len(tab) > 3 else False
            it = QListWidgetItem(name)
            it.setData(Qt.UserRole, page)
            flags = it.flags() | Qt.ItemIsUserCheckable
            if locked:
                flags &= ~Qt.ItemIsUserCheckable
                it.setToolTip("The Library tab always stays")
            it.setFlags(flags)
            it.setCheckState(Qt.Checked if shown else Qt.Unchecked)
            self.list.addItem(it)
        self.list.setCurrentRow(0)
        row.addWidget(self.list, 1)
        col = QVBoxLayout()
        for label, fn in (("Move up", lambda: self._move(-1)), ("Move down", lambda: self._move(1)),
                          ("To the start", lambda: self._move(-99)), ("To the end", lambda: self._move(99))):
            b = QPushButton(label)
            b.clicked.connect(fn)
            col.addWidget(b)
        col.addSpacing(10)
        if add_menu is not None:
            self.add_btn = QPushButton("Add tab")
            m = QMenu(self.add_btn)
            m.aboutToShow.connect(lambda: (m.clear(), add_menu(m)))
            self.add_btn.setMenu(m)
            col.addWidget(self.add_btn)
        self.del_btn = QPushButton("Delete tab")
        self.del_btn.setToolTip("Delete a tab you added (the playlist or songs stay)")
        self.del_btn.clicked.connect(self._delete)
        col.addWidget(self.del_btn)
        self.list.currentRowChanged.connect(self._row_changed)
        self._row_changed(0)
        col.addStretch()
        reset = QPushButton("Reset")
        reset.setToolTip("Back to Library, Queue, Playlists, Lyrics, Stats, Radio, Discover, all shown")
        reset.clicked.connect(self._reset)
        col.addWidget(reset)
        row.addLayout(col)
        lay.addLayout(row, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def add_item(self, page: int, name: str):
        """Add a tab while the dialog is open."""
        it = QListWidgetItem(name)
        it.setData(Qt.UserRole, page)
        it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
        it.setCheckState(Qt.Checked)
        self.list.addItem(it)
        self.list.setCurrentItem(it)

    def _row_changed(self, r):
        it = self.list.item(r) if r >= 0 else None
        self.del_btn.setEnabled(bool(it) and self._removable(it.data(Qt.UserRole)))

    def _delete(self):
        r = self.list.currentRow()
        it = self.list.item(r) if r >= 0 else None
        if it and self._removable(it.data(Qt.UserRole)):
            self.removed.append(it.data(Qt.UserRole))
            self.list.takeItem(r)

    def _move(self, delta: int):
        r = self.list.currentRow()
        if r < 0:
            return
        to = max(0, min(self.list.count() - 1, r + delta))
        if to != r:
            it = self.list.takeItem(r)
            self.list.insertItem(to, it)
            self.list.setCurrentRow(to)

    def _reset(self):
        items = sorted((self.list.takeItem(0) for _ in range(self.list.count())), key=lambda i: i.data(Qt.UserRole))
        for it in items:
            if it.flags() & Qt.ItemIsUserCheckable:
                it.setCheckState(Qt.Checked)
            self.list.addItem(it)
        self.list.setCurrentRow(0)

    def order(self) -> list[int]:
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())]

    def hidden(self) -> list[int]:
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())
                if (self.list.item(i).flags() & Qt.ItemIsUserCheckable)
                and self.list.item(i).checkState() != Qt.Checked]

