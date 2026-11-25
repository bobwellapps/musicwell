"""Song list panel item (playing now, the library, the queue or a playlist)."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QMenu, QPushButton, QVBoxLayout, QWidget

from musicwell import fields as F

SOURCES = [("playing", "Playing now"), ("library", "Your library"), ("queue", "The queue"),
           ("picked", "Follow the tabs")]
SOURCE_TIPS = {"picked": "The Library tab, a playlist tab at the top or a playlist picked on the Playlists tab "
                         "shows here (instead of in the main area)"}


def is_source(key) -> bool:
    return isinstance(key, str) and (key in dict(SOURCES) or
                                     (key.startswith("playlist:") and key[9:].isdigit()))
SHOWN = ("playing", "title", "artist", "length")  # starting columns for narrow panels


class PanelSongList(QWidget):
    optionsChanged = Signal()
    sourceChanged = Signal()
    songActivated = Signal(str, int)  # source, track id
    menuRequested = Signal(str, list, object)  # source, track ids, global pos

    playlists_fn = None  # -> [(id, name)]

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.source = "playing"
        self._choices: list[str] = []
        self.fill = False  # take the rest of the panel's height
        self.top_bar = True
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        self.top_box = QWidget()
        top = QHBoxLayout(self.top_box)
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)
        self.heading = QLabel("SONGS")
        self.heading.setObjectName("SectionTitle")
        top.addWidget(self.heading)
        self.pick = QComboBox()
        self.pick.setToolTip("Which songs this list shows — the songs playing, your library, the queue or "
                             "one of your playlists")
        self.pick.currentIndexChanged.connect(self._picked)
        self.pick.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.pick.setMinimumContentsLength(6)
        self.refresh_choices()
        top.addWidget(self.pick, 1)
        self.count = QLabel("")
        self.count.setObjectName("EmptyText")
        top.addWidget(self.count)
        self.more = QPushButton("⋯")
        self.more.setFixedSize(30, 26)
        self.more.setStyleSheet("QPushButton{padding:0px; font-weight:700;}")
        self.more.setToolTip("Options for this list")
        self.more.clicked.connect(lambda: self._options_menu(self.more.mapToGlobal(self.more.rect().bottomLeft())))
        top.addWidget(self.more)
        v.addWidget(self.top_box)

        from musicwell.widgets import SongTable
        hidden = tuple(f.key for f in F.all_fields() if f.key not in SHOWN)
        self.table = SongTable(theme, self, hidden_by_default=hidden)
        self.table._apply_defaults()
        self.table.setObjectName("PanelSongs")
        self.table.TITLE_MIN = 60
        self.table.playRequested.connect(self._activated)
        self.table.menuRequested.connect(lambda ids, pos: self.menuRequested.emit(self.source, ids, pos))
        self.table.columnsChanged.connect(self.optionsChanged)
        self.table.header_always = lambda m: self.fill_menu(m.addMenu("This song list"), columns=False)
        v.addWidget(self.table, 1)
        self.setMinimumHeight(110)
        self.table.horizontalHeader().sectionResized.connect(self._user_resized)
        self._fitting = False
        self._fixed_by_you: set[str] = set()  # columns the user resized

    # Title and artist share the width the other columns leave.
    def _user_resized(self, logical, _old, _new):
        if not self._fitting:
            f = self.table.model_.fields[logical]
            if f.key in ("title", "artist"):
                self._fixed_by_you.add(f.key)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()

    def _fit(self):
        t = self.table
        flex = [k for k in ("title", "artist") if k not in self._fixed_by_you]
        cols = {f.key: i for i, f in enumerate(t.model_.fields) if not t.isColumnHidden(i)}
        flex = [k for k in flex if k in cols]
        if not flex:
            return
        others = sum(t.columnWidth(i) for k, i in cols.items() if k not in flex)
        room = t.viewport().width() - others - 2
        share = {"title": 0.58, "artist": 0.42} if len(flex) == 2 else {flex[0]: 1.0}
        self._fitting = True
        for k in flex:
            t.setColumnWidth(cols[k], max(50, int(room * share[k])))
        self._fitting = False

    def options(self) -> dict:
        return {"source": self.source, "fill": self.fill, "top_bar": self.top_bar,
                "columns": self.table.column_state()}

    def set_options(self, d):
        if not isinstance(d, dict):
            d = {}
        src = d.get("source") if is_source(d.get("source")) else "playing"
        self.fill = bool(d.get("fill", False))
        self._show_top(bool(d.get("top_bar", True)), save=False)
        cols = d.get("columns")
        self._fitting = True  # so _user_resized ignores these
        self.table._apply_defaults()
        if isinstance(cols, list) and cols:
            self.table.restore_column_state(cols)
        else:
            i = self.table.model_.column_of("length")
            if i >= 0:
                self.table.setColumnWidth(i, 52)
        self._fitting = False
        self._fixed_by_you.clear()
        self._fit()
        self.set_source(src, emit=False)
        self.sourceChanged.emit()

    def _playlists(self) -> list:
        try:
            return list(PanelSongList.playlists_fn()) if PanelSongList.playlists_fn else []
        except Exception:
            return []

    def refresh_choices(self):
        """Fixed choices, then the playlists."""
        self.pick.blockSignals(True)
        self.pick.clear()
        self._choices = []
        for k, n in SOURCES:
            self.pick.addItem(n if k != "picked" else "Follow the tabs")
            self._choices.append(k)
        pls = self._playlists()
        if pls:
            self.pick.insertSeparator(self.pick.count())
            self._choices.append("")
            for pid, name in pls:
                self.pick.addItem(f"♫  {name}")
                self._choices.append(f"playlist:{pid}")
        cur = self.source
        if cur not in self._choices and cur.startswith("playlist:"):
            self.pick.addItem("(a deleted playlist)")  # it's gone: say so rather than pick another
            self._choices.append(cur)
        self.pick.setCurrentIndex(self._choices.index(cur) if cur in self._choices else 0)
        self.pick.blockSignals(False)

    def _picked(self, i: int):
        if 0 <= i < len(self._choices) and self._choices[i]:
            self.set_source(self._choices[i])

    def set_source(self, source: str, emit: bool = True):
        if not is_source(source):
            return
        changed = source != self.source
        self.source = source
        if source not in self._choices:
            self.refresh_choices()
        i = self._choices.index(source)
        if self.pick.currentIndex() != i:
            self.pick.blockSignals(True)
            self.pick.setCurrentIndex(i)
            self.pick.blockSignals(False)
        if changed and emit:
            self.sourceChanged.emit()
            self.optionsChanged.emit()

    def _set_fill(self, on: bool):
        self.fill = on
        self.optionsChanged.emit()

    def _show_top(self, on: bool, save: bool = True):
        self.top_bar = on
        self.top_box.setVisible(on)
        if save:
            self.optionsChanged.emit()

    def _options_menu(self, at):
        m = QMenu(self)
        self.fill_menu(m)
        m.exec(at)

    def fill_menu(self, m: QMenu, columns: bool = True):
        for key, name in SOURCES:
            a = m.addAction(name, lambda k=key: self.set_source(k))
            a.setCheckable(True)
            a.setChecked(key == self.source)
            if key in SOURCE_TIPS:
                a.setToolTip(SOURCE_TIPS[key])
                m.setToolTipsVisible(True)
        pls = self._playlists()
        if pls:
            pm = m.addMenu("A playlist")
            for pid, name in pls:
                a = pm.addAction(name.replace("&", "&&"), lambda p=pid: self.set_source(f"playlist:{p}"))
                a.setCheckable(True)
                a.setChecked(self.source == f"playlist:{pid}")
        m.addSeparator()
        a = m.addAction("Fill the panel", lambda: self._set_fill(not self.fill))
        a.setCheckable(True)
        a.setChecked(self.fill)
        a = m.addAction("Show the box at the top", lambda: self._show_top(not self.top_bar))
        a.setCheckable(True)
        a.setChecked(self.top_bar)
        a.setToolTip("The SONGS heading, the Playing now / Your library / The queue box and ⋯ — without it, "
                     "right-click the list's column headings (or the panel) for these options")
        m.setToolTipsVisible(True)
        from musicwell.widgets import SongTable
        if columns and SongTable.columns_unlocked:
            m.addAction("Columns…", lambda: self.table._header_menu(self.table.horizontalHeader().rect().center()))

    def set_tracks(self, tracks: list[dict], current: int | None):
        self.table.model_.set_rows(tracks)
        self.table.model_.set_current(current)
        n = len(tracks)
        self.count.setText(f"{n:,}" if n else "")
        self.table.setToolTip("" if n else {"playing": "Nothing playing", "library": "No songs",
                                            "queue": "Nothing queued — right-click a song → Add to queue",
                                            "picked": "Click Library or a playlist tab"}.get(
                                                self.source, "This playlist is empty"))

    def set_current(self, tid):
        self.table.model_.set_current(tid)

    def _activated(self, row: int):
        rows = self.table.model_.rows
        if 0 <= row < len(rows):
            self.songActivated.emit(self.source, rows[row]["id"])
