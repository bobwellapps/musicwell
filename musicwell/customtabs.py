"""User tabs: a playlist or a saved search. Stored in settings as a small dict."""
from __future__ import annotations

import random

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget)

from musicwell import fields as F
from musicwell.models import fmt_time
from musicwell.query import compile_query
from musicwell.widgets import SongTable

# ready-made searches under "Add tab"
PRESETS = [
    {"name": "Favourites", "query": "rating>=4", "sort": ["rating", "desc"],
     "tip": "Songs you rated 4 or 5 stars"},
    {"name": "Recently added", "query": "#(added < 30 days)", "sort": ["added", "desc"],
     "tip": "Songs added in the last 30 days"},
    {"name": "Recently played", "query": "#(lastplayed < 30 days)", "sort": ["lastplayed", "desc"],
     "tip": "Songs played in the last 30 days, latest first"},
    {"name": "Most played", "query": "plays>0", "sort": ["playcount", "desc"], "limit": 100,
     "tip": "Your 100 most played songs"},
    {"name": "Never played", "query": "#(plays = 0)", "sort": None,
     "tip": "Songs you haven't played yet"},
]

SORTABLE = ["artist", "album", "title", "year", "decade", "genre", "rating", "playcount", "lastplayed", "added",
            "length", "track"]


class CustomTabPage(QWidget):
    changed = Signal()  # sort or columns changed: save the tab

    def __init__(self, spec: dict, theme, parent=None):
        super().__init__(parent)
        self.spec = spec
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 6, 12, 0)
        row = QHBoxLayout()
        self.title = QLabel(spec.get("name", ""))
        self.title.setObjectName("PageTitle")
        self.info = QLabel("")
        self.info.setObjectName("EmptyText")
        row.addWidget(self.title)
        row.addWidget(self.info)
        row.addStretch()
        self.play_btn = QPushButton("Play")
        self.play_btn.setObjectName("Primary")
        self.shuffle_btn = QPushButton("Shuffle")
        self.edit_btn = QPushButton("Edit…")
        self.edit_btn.setToolTip("Change this tab's name, search, sort or number of songs")
        row.addWidget(self.play_btn)
        row.addWidget(self.shuffle_btn)
        row.addWidget(self.edit_btn)
        lay.addLayout(row)
        self.hint = QLabel("")
        self.hint.setObjectName("EmptyText")
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)
        self.table = SongTable(theme, hidden_by_default=() if self.is_search else ("genre", "playcount"))
        lay.addWidget(self.table, 1)
        if self.is_playlist:
            self.table.setSortingEnabled(False)
        self.table.restore_column_state(spec.get("columns") or [])
        self._apply_spec_sort()
        self.table.horizontalHeader().sortIndicatorChanged.connect(self._sort_changed)
        self.table.columnsChanged.connect(self._columns_changed)

    @property
    def is_playlist(self) -> bool:
        return self.spec.get("kind") == "playlist"

    @property
    def is_search(self) -> bool:
        return self.spec.get("kind") == "search"

    def _apply_spec_sort(self):
        if not self.is_search:
            return
        sort = self.spec.get("sort")
        col = self.table.model_.column_of(sort[0]) if sort else -1
        h = self.table.horizontalHeader()
        h.blockSignals(True)
        if col >= 0:
            order = Qt.DescendingOrder if sort[1] == "desc" else Qt.AscendingOrder
            h.setSortIndicator(col, order)
            self.table.model_.sort_col, self.table.model_.sort_order = col, order
        else:
            h.setSortIndicator(-1, Qt.AscendingOrder)
            self.table.model_.sort_col = -1
        h.blockSignals(False)

    def _sort_changed(self, col, order):
        m = self.table.model_
        if 0 <= col < len(m.fields):
            self.spec["sort"] = [m.fields[col].key, "desc" if order == Qt.DescendingOrder else "asc"]
        else:
            self.spec["sort"] = None
        self.changed.emit()

    def _columns_changed(self):
        self.spec["columns"] = self.table.column_state()
        self.changed.emit()

    def refresh(self, library, current_id=None):
        """Refill the list."""
        self.title.setText(self.spec.get("name", ""))
        if self.is_playlist:
            pid = self.spec.get("pid")
            names = dict(library.playlists())
            if pid not in names:
                rows = []
                self.hint.setText("This playlist has been deleted. Right-click the tab → Remove tab.")
            else:
                rows = [t for t in (library.get(i) for i in library.playlist_track_ids(pid)) if t]
                self.hint.setText("" if rows else "The playlist is empty. Drag songs here, or right-click songs → "
                                                  f"Add to playlist → {names[pid]}.")
            self.table.model_.set_rows(rows, keep_sort=False)
        else:
            q = self.spec.get("query", "")
            try:
                pred = compile_query(q)
            except Exception:  # invalid search shows nothing
                pred = lambda t: False
            rows = [t for t in library.all_tracks() if pred is None or pred(t)]
            limit = int(self.spec.get("limit") or 0)
            m = self.table.model_
            m.rows = rows
            m._apply_sort()
            rows = m.rows[:limit] if limit else m.rows
            m.set_rows(rows, keep_sort=False)
            self.hint.setText("" if rows else f"No songs match “{q}” yet.")
        self.hint.setVisible(bool(self.hint.text()))
        if current_id is not None:
            self.table.model_.set_current(current_id)
        total = sum(t.get("length") or 0 for t in rows)
        self.info.setText(f"{len(rows):,} song{'s' if len(rows) != 1 else ''} · {fmt_time(total)}" if rows else "")

    def shuffled_ids(self) -> list[int]:
        ids = self.table.model_.ids()
        random.shuffle(ids)
        return ids


class SearchTabDialog(QDialog):

    def __init__(self, spec: dict | None = None, parent=None, current_search: str = ""):
        super().__init__(parent)
        spec = dict(spec or {})
        self.setWindowTitle("Edit tab" if spec.get("id") else "Add a search tab")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        intro = QLabel("The tab shows every song the search finds, and keeps up to date as your library changes. "
                       "It uses the same search as the box at the top, for example:\n"
                       "  genre=jazz      artist=bowie      year>=1970 year<1980\n"
                       "  rating>=4      #(added < 30 days)      #(plays = 0)")
        intro.setObjectName("EmptyText")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        form = QFormLayout()
        self.name = QLineEdit(spec.get("name", ""))
        self.name.setPlaceholderText("e.g. Jazz")
        form.addRow("Tab name", self.name)
        self.query = QLineEdit(spec.get("query", current_search))
        self.query.setPlaceholderText("e.g. genre=jazz")
        self.query.setClearButtonEnabled(True)
        form.addRow("Search", self.query)
        self.sort = QComboBox()
        self.sort.addItem("As in the library (artist, album, track)", None)
        for key in SORTABLE:
            f = F.get(key)
            if f:
                self.sort.addItem(f"{f.name}", key)
        self.order = QComboBox()
        self.order.addItem("Highest / newest / Z first", "desc")
        self.order.addItem("Lowest / oldest / A first", "asc")
        sort = spec.get("sort")
        if sort:
            i = self.sort.findData(sort[0])
            self.sort.setCurrentIndex(max(0, i))
            self.order.setCurrentIndex(0 if sort[1] == "desc" else 1)
        srow = QHBoxLayout()
        srow.addWidget(self.sort, 1)
        srow.addWidget(self.order)
        form.addRow("Sort by", srow)
        self.sort.currentIndexChanged.connect(lambda _: self.order.setEnabled(self.sort.currentData() is not None))
        self.order.setEnabled(self.sort.currentData() is not None)
        self.limit = QSpinBox()
        self.limit.setRange(0, 100000)
        self.limit.setSpecialValueText("All")
        self.limit.setValue(int(spec.get("limit") or 0))
        form.addRow("Show at most", self.limit)
        lay.addLayout(form)
        self.check = QLabel("")
        self.check.setObjectName("EmptyText")
        lay.addWidget(self.check)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)
        self.name.textChanged.connect(self._validate)
        self.query.textChanged.connect(self._validate)
        self._validate()

    def _validate(self):
        ok = bool(self.name.text().strip())
        msg = ""
        try:
            compile_query(self.query.text())
        except Exception:
            ok, msg = False, "That search can't be read — check the quotes and brackets."
        self.check.setText(msg)
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(ok)

    def result_spec(self) -> dict:
        key = self.sort.currentData()
        return {"kind": "search", "name": self.name.text().strip(), "query": self.query.text().strip(),
                "sort": [key, self.order.currentData()] if key else None, "limit": self.limit.value()}
