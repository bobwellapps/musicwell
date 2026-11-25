"""Table model for song lists, and the star rating delegate."""
from __future__ import annotations

import time

import json

from PySide6.QtCore import QAbstractTableModel, QEvent, QMimeData, QModelIndex, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

from musicwell import theme as th

from musicwell import fields as F

TrackIdRole = Qt.UserRole + 1


def fmt_time(seconds: float) -> str:
    seconds = int(seconds or 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_date(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts)) if ts else ""


def library_order(t: dict):
    return (t["artist_key"].lower(), t["year"] or 0, t["album"].lower(),
            t["disc"] or 0, t["track"] or 0, t["title"].lower())


# columns sorted in album order rather than by value
_SORT_KEYS = {
    "track": lambda t: (t["disc"] or 0, t["track"] or 0),
    "title": lambda t: t["title"].lower(),
    "artist": lambda t: (t["artist"].lower(), t["year"] or 0, t["album"].lower(), t["disc"] or 0, t["track"] or 0),
    "albumartist": library_order,
    "artist_key": library_order,
    "album": lambda t: (t["album"].lower(), t["disc"] or 0, t["track"] or 0),
    "year": lambda t: (t["year"] or 0, t["album"].lower(), t["disc"] or 0, t["track"] or 0),
    "genre": lambda t: (t["genre"].lower(),) + library_order(t),
    "disc": lambda t: (t["disc"] or 0, t["track"] or 0),
}
_MUTED = {"track", "year", "length", "playcount", "format", "bitrate", "added", "lastplayed", "path",
          "samplerate", "bitdepth", "channels", "filesize", "skipcount", "disc", "bpm", "filename",
          "decade", "origyear", "isrc", "catalog", "encodedby"}


TRACKS_MIME = "application/x-musicwell-tracks"


class SongModel(QAbstractTableModel):
    bold_row = False  # playing song bold in every column

    def __init__(self, theme: th.Theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.rows: list[dict] = []
        self.fields: list[F.Field] = F.all_fields()
        self.current_id: int | None = None
        # Queue page: only the playing row is marked and played rows are greyed.
        self.by_row = False
        self.current_row = -1
        self.dimmed: set = set()
        self.sort_col = -1
        self.sort_order = Qt.AscendingOrder
        self._speaker = None
        self._bold = QFont()
        self._bold.setBold(True)

    def refresh_theme(self):
        self._speaker = None
        self.layoutChanged.emit()

    def set_fields(self, fields: list):
        sort_key = self.fields[self.sort_col].key if 0 <= self.sort_col < len(self.fields) else None
        self.beginResetModel()
        self.fields = list(fields)
        keys = [f.key for f in self.fields]
        self.sort_col = keys.index(sort_key) if sort_key in keys else -1
        self.endResetModel()

    def column_of(self, key: str) -> int:
        for i, f in enumerate(self.fields):
            if f.key == key:
                return i
        return -1

    def set_rows(self, rows: list[dict], keep_sort: bool = True):
        self.beginResetModel()
        self.rows = list(rows)
        if keep_sort and self.sort_col >= 0:
            self._apply_sort()
        self.endResetModel()

    def ids(self) -> list[int]:
        return [t["id"] for t in self.rows]

    def set_current(self, tid: int | None):
        self.current_id = tid
        if self.rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.rows) - 1, len(self.fields) - 1))

    def track_changed(self, tid: int):
        for r, t in enumerate(self.rows):
            if t["id"] == tid:
                self.dataChanged.emit(self.index(r, 0), self.index(r, len(self.fields) - 1))

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.fields)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and 0 <= section < len(self.fields):
            f = self.fields[section]
            if role == Qt.DisplayRole:
                return "" if f.key == "playing" else f.title.upper()
            if role == Qt.ToolTipRole:
                return f.name + (f"  (tag: {f.tags[0].upper()})" if f.custom else "")
            if role == Qt.TextAlignmentRole:
                return int((Qt.AlignRight if f.numeric and f.kind != "rating" else Qt.AlignLeft) | Qt.AlignVCenter)
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        t = self.rows[index.row()]
        f = self.fields[index.column()]
        key = f.key
        cur = index.row() == self.current_row if self.by_row else t["id"] == self.current_id
        if role == Qt.DisplayRole:
            if key in ("playing", "rating"):
                return None
            if key == "lastplayed" and not t.get("lastplayed"):
                return "Never"
            if key in ("artist", "album") and not t.get(key):
                return "Unknown " + key.capitalize()
            return f.display(t)
        if role == Qt.DecorationRole and key == "playing" and cur:
            if self._speaker is None:
                self._speaker = QPixmap.fromImage(th.svg_image("speaker", self.theme.accent, 16))
            return self._speaker
        if role == Qt.ForegroundRole:
            if cur:
                return self.theme.color("accent")
            if index.row() in self.dimmed:
                return self.theme.color("faint")
            if key == "source":
                return self.theme.color("accent" if t.get("remote") else "muted")
            if key in _MUTED or f.custom:
                return self.theme.color("muted")
        if role == Qt.FontRole and cur and (key == "title" or SongModel.bold_row):
            return self._bold
        if role == Qt.TextAlignmentRole:
            if key == "playing":
                return int(Qt.AlignCenter)
            if f.numeric and f.kind != "rating":
                return int(Qt.AlignRight | Qt.AlignVCenter)
            return int(Qt.AlignLeft | Qt.AlignVCenter)
        if role == Qt.ToolTipRole:
            if key == "source":
                if t.get("remote"):
                    it = t.get("item") or {}
                    from musicwell.freemusic import where as _where
                    where = _where(it)
                    lic = f" — {it['license']}" if it.get("license") else ""
                    return f"Online: played from {where}{lic}"
                return "Local: a file in your music library"
            if key == "title":
                return t["path"]
            if key == "comment" or (f.kind == "text" and len(str(f.get(t))) > 30):
                return str(f.get(t)) or None
        if role == TrackIdRole:
            return t["id"]
        return None

    def flags(self, index):
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled

    # Drag and drop carries library ids, plus file URLs for other apps.
    def mimeTypes(self):
        return [TRACKS_MIME, "text/uri-list"]

    def supportedDragActions(self):
        return Qt.CopyAction | Qt.MoveAction

    def supportedDropActions(self):
        return Qt.CopyAction | Qt.MoveAction

    def mimeData(self, indexes):
        rows = sorted({i.row() for i in indexes if i.isValid()})
        tracks = [self.rows[r] for r in rows if 0 <= r < len(self.rows)]
        md = QMimeData()
        from musicwell.library import is_online_id
        md.setData(TRACKS_MIME, json.dumps([t["id"] for t in tracks
                                            if t.get("id", 0) > 0 or is_online_id(t.get("id", 0))]).encode())
        md.setUrls([QUrl.fromLocalFile(t["path"]) for t in tracks
                    if t.get("path") and not t.get("stream") and not t.get("remote")])
        return md

    def sort(self, column, order=Qt.AscendingOrder):
        self.sort_col, self.sort_order = column, order
        self.layoutAboutToBeChanged.emit()
        self._apply_sort()
        self.layoutChanged.emit()

    def _apply_sort(self):
        if not 0 <= self.sort_col < len(self.fields):
            self.rows.sort(key=library_order)
            return
        f = self.fields[self.sort_col]
        fn = _SORT_KEYS.get(f.key) or f.sort_key
        self.rows.sort(key=fn, reverse=self.sort_order == Qt.DescendingOrder)


class RatingDelegate(QStyledItemDelegate):
    """Five stars; clicking the current rating clears it."""
    rated = Signal(int, int)  # track id, rating

    STAR = 14

    def __init__(self, theme: th.Theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self._cache = {}

    def refresh_theme(self):
        self._cache = {}

    def _star(self, kind: str, hover=False):
        key = (kind, hover)
        if key not in self._cache:
            color = self.theme.color("accent") if kind == "star" else self.theme.color("faint")
            if hover and kind == "star_empty":
                color = self.theme.color("muted")
            self._cache[key] = QPixmap.fromImage(th.svg_image(kind, color, self.STAR))
        return self._cache[key]

    def paint(self, painter, option, index):
        self.initStyleOption(option, index)
        option.text = ""
        style = option.widget.style() if option.widget else None
        if style:
            style.drawControl(QStyle.CE_ItemViewItem, option, painter, option.widget)
        model = index.model()
        t = model.rows[index.row()]
        rating = t.get("rating") or 0
        hover = bool(option.state & QStyle.State_MouseOver)
        if rating == 0 and not (hover or option.state & QStyle.State_Selected):
            return
        x = option.rect.x() + 6
        y = option.rect.y() + (option.rect.height() - self.STAR) // 2
        for i in range(5):
            pm = self._star("star" if i < rating else "star_empty", hover)
            painter.drawPixmap(x + i * (self.STAR + 3), y, pm)

    def sizeHint(self, option, index):
        return QSize(5 * (self.STAR + 3) + 12, 28)

    def editorEvent(self, event, model, option, index):
        if event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            x = event.position().x() - option.rect.x() - 6
            star = int(x // (self.STAR + 3)) + 1
            if 1 <= star <= 5 and x >= 0:
                t = model.rows[index.row()]
                new = 0 if t.get("rating") == star else star
                self.rated.emit(t["id"], new)
                return True
        return super().editorEvent(event, model, option, index)
