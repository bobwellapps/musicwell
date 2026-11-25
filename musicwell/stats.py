"""The Stats page. "All time" uses per-song play counts; shorter periods use the play history."""
from __future__ import annotations

import datetime as dt
import time
from collections import Counter, defaultdict

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QDialog, QDialogButtonBox, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QMessageBox, QPushButton, QScrollArea, QSizePolicy,
                               QToolTip, QVBoxLayout, QWidget)

from musicwell.radiolog import SONG_MIN_SECONDS

PERIODS = [("all", "All time"), ("year", "This year"), ("30d", "Last 30 days"), ("7d", "Last 7 days")]
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def hours_text(seconds: float) -> str:
    h = seconds / 3600
    if h >= 48:
        return f"{h / 24:,.1f} days"
    if h >= 1:
        return f"{h:,.1f} hours"
    return f"{seconds / 60:,.0f} min"


def plays_text(n: int) -> str:
    return f"{n:,} play{'s' if n != 1 else ''}"


def compute(lib, period: str = "all", now: float | None = None) -> dict:
    now = now or time.time()
    tracks = list(lib.tracks.values())
    today = dt.date.fromtimestamp(now)
    out: dict = {"period": period}

    artists = {t["artist_key"] or t["artist"] for t in tracks if (t["artist_key"] or t["artist"])}
    albums = {((t["albumartist"] or t["artist"]), t["album"]) for t in tracks if t["album"]}
    out["library"] = {
        "songs": len(tracks), "artists": len(artists), "albums": len(albums),
        "length": sum(t["length"] or 0 for t in tracks),
        "size": sum(t["filesize"] or 0 for t in tracks),
        "never": sum(1 for t in tracks if not t["playcount"]),
        "rated": sum(1 for t in tracks if t["rating"]),
    }
    decades = Counter(t["decade"] for t in tracks if t["decade"])
    out["decades"] = sorted(decades.items())
    out["formats"] = Counter(t["format"] or "?" for t in tracks).most_common(8)
    out["skipped"] = sorted((t for t in tracks if t["skipcount"]), key=lambda t: -t["skipcount"])[:8]

    if period == "all":
        since = 0.0
    elif period == "year":
        since = time.mktime(dt.date(today.year, 1, 1).timetuple())
    else:
        days = 30 if period == "30d" else 7
        since = time.mktime((today - dt.timedelta(days=days - 1)).timetuple())
    history = lib.plays_since(since)
    out["history_start"] = lib.first_play_logged()

    by_artist, by_album, by_song, by_genre = Counter(), Counter(), Counter(), Counter()
    secs_artist: dict = defaultdict(float)
    album_track: dict = {}
    if period == "all":
        plays, seconds = 0, 0.0
        for t in tracks:
            n = t["playcount"] or 0
            if not n:
                continue
            plays += n
            s = n * (t["length"] or 0)
            seconds += s
            a = t["artist_key"] or t["artist"] or "Unknown Artist"
            by_artist[a] += n
            secs_artist[a] += s
            if t["album"]:
                key = (t["albumartist"] or t["artist"] or "", t["album"])
                by_album[key] += n
                album_track.setdefault(key, t)
            by_song[t["id"]] += n
            by_genre[t["genre"] or "No genre"] += n
    else:
        plays, seconds = len(history), sum(h["seconds"] or 0 for h in history)
        ids_by_path = {t["path"]: t["id"] for t in tracks}
        for h in history:
            a = h["albumartist"] or h["artist"] or "Unknown Artist"
            by_artist[a] += 1
            secs_artist[a] += h["seconds"] or 0
            if h["album"]:
                key = (h["albumartist"] or h["artist"] or "", h["album"])
                by_album[key] += 1
                tid = ids_by_path.get(h["path"]) or h["track_id"]
                if tid in lib.tracks:
                    album_track.setdefault(key, lib.tracks[tid])
            tid = ids_by_path.get(h["path"]) or h["track_id"]
            by_song[tid if tid in lib.tracks else ("gone", h["title"], h["artist"])] += 1
            by_genre[h["genre"] or "No genre"] += 1
    out["plays"], out["seconds"] = plays, seconds
    out["top_artists"] = [(a, n, secs_artist[a]) for a, n in by_artist.most_common(10)]
    out["top_albums"] = [(k, n, album_track.get(k)) for k, n in by_album.most_common(10)]
    out["top_songs"] = [(k, n) for k, n in by_song.most_common(10)]
    out["genres"] = by_genre.most_common(10)

    hist_all = history if period != "all" else lib.plays_since(0)
    stamps = [dt.datetime.fromtimestamp(h["played_at"]) for h in hist_all]
    hours = [0] * 24
    week = [0] * 7
    for s in stamps:
        hours[s.hour] += 1
        week[s.weekday()] += 1
    out["hours"], out["weekdays"] = hours, week
    out["timeline"] = _timeline(period, stamps, today)
    # streak: consecutive days with a play, up to today or yesterday
    days = {s.date() for s in stamps} if period == "all" else {s.date() for s in
                                                               (dt.datetime.fromtimestamp(h["played_at"])
                                                                for h in lib.plays_since(0))}
    streak, d = 0, today if today in days else today - dt.timedelta(days=1)
    while d in days:
        streak += 1
        d -= dt.timedelta(days=1)
    out["streak"] = streak
    out["active_days"] = len({s.date() for s in stamps})
    return out


def period_start(period: str, now: float | None = None) -> float:
    today = dt.date.fromtimestamp(now or time.time())
    if period == "all":
        return 0.0
    if period == "year":
        return time.mktime(dt.date(today.year, 1, 1).timetuple())
    days = 30 if period == "30d" else 7
    return time.mktime((today - dt.timedelta(days=days - 1)).timetuple())


def _norm(x: str) -> str:
    return " ".join((x or "").lower().split())


def _streak(days: set, today: dt.date) -> int:
    streak, d = 0, today if today in days else today - dt.timedelta(days=1)
    while d in days:
        streak += 1
        d -= dt.timedelta(days=1)
    return streak


def _time_buckets(period: str, items: list[tuple[dt.datetime, float]], today: dt.date) -> list[tuple[str, float, str]]:
    """Like _timeline, but sums a value (seconds) per (time, value)."""
    stamps = [w for w, _v in items]
    shape = _timeline(period, stamps, today)
    if period in ("7d", "30d"):
        n = len(shape)
        sums = defaultdict(float)
        for w, v in items:
            sums[w.date()] += v
        return [(short, sums.get(today - dt.timedelta(days=n - 1 - i), 0.0), long)
                for i, (short, _c, long) in enumerate(shape)]
    sums = defaultdict(float)
    for w, v in items:
        sums[(w.year, w.month)] += v
    out = []
    for short, _c, long in shape:
        mon, year = long.split()
        out.append((short, sums.get((int(year), MONTHS.index(mon) + 1), 0.0), long))
    return out


def library_index(lib) -> tuple[dict, dict]:
    """Library artists and songs by normalised name: {artist: shown name}, {(artist, title): id}."""
    artists, songs = {}, {}
    for t in lib.tracks.values():
        for a in {t["artist"], t["albumartist"], t["artist_key"]}:
            if a:
                artists.setdefault(_norm(a), t["artist_key"] or t["artist"] or a)
        if t["artist"] and t["title"]:
            songs.setdefault((_norm(t["artist"]), _norm(t["title"])), t["id"])
    return artists, songs


def compute_radio(log, lib, period: str = "all", liked: list | None = None, now: float | None = None) -> dict:
    """Radio stats from what was logged while listening."""
    now = now or time.time()
    today = dt.date.fromtimestamp(now)
    since = period_start(period, now)
    stations = log.stations()
    time_rows = [r for r in log.time_since(since) if (r["seconds"] or 0) > 0]
    tunes = log.tunes_since(since)
    songs = log.songs_since(since)
    lib_artists, lib_songs = library_index(lib)
    out: dict = {"period": period, "first": log.first_logged()}

    secs_station, tunes_station = defaultdict(float), Counter(r["uuid"] for r in tunes)
    by_genre, by_country = defaultdict(float), defaultdict(float)
    hours, week = [0.0] * 24, [0.0] * 7
    when = []
    for r in time_rows:
        s = r["seconds"]
        secs_station[r["uuid"]] += s
        w = dt.datetime.fromtimestamp(r["hour"])
        hours[w.hour] += s
        week[w.weekday()] += s
        when.append((w, s))
        st = stations.get(r["uuid"], {})
        for tag in [x.strip() for x in (st.get("tags") or "").split(",") if x.strip()][:4]:
            by_genre[tag.title() if tag.islower() else tag] += s
        by_country[st.get("country") or "Unknown country"] += s
    out["seconds"] = sum(secs_station.values())
    out["tunes"] = len(tunes)
    out["stations"] = len(secs_station)
    out["hours"], out["weekdays"] = hours, week
    out["timeline"] = _time_buckets(period, when, today)
    out["when"] = when
    days_all = {dt.datetime.fromtimestamp(r["hour"]).date() for r in log.time_since(0) if (r["seconds"] or 0) >= 60}
    out["days"] = days_all
    out["streak"] = _streak(days_all, today)
    out["active_days"] = len({w.date() for w, s in when if s >= 60})
    out["top_stations"] = [(stations.get(u) or {"uuid": u, "name": "?"}, s, tunes_station.get(u, 0))
                           for u, s in sorted(secs_station.items(), key=lambda kv: -kv[1])[:10]]
    out["genres"] = sorted(by_genre.items(), key=lambda kv: -kv[1])[:10]
    out["countries"] = sorted(by_country.items(), key=lambda kv: -kv[1])[:10]

    by_artist, secs_artist, by_song, song_station = Counter(), defaultdict(float), Counter(), {}
    names = {}
    for r in songs:
        a = r["artist"] or ""
        if a:
            k = _norm(a)
            names.setdefault(k, a)
            by_artist[k] += 1
            secs_artist[k] += r["seconds"] or 0
        sk = (_norm(a), _norm(r["title"]))
        names.setdefault(sk, (r["title"], a))
        by_song[sk] += 1
        song_station.setdefault(sk, Counter())[r["station"] or ""] += 1
    out["songs"] = len(songs)
    out["artists"] = len(by_artist)
    out["top_artists"] = [(names[k], n, secs_artist[k], lib_artists.get(k)) for k, n in by_artist.most_common(10)]
    out["top_songs"] = [(names[k][0], names[k][1], n, song_station[k].most_common(1)[0][0], lib_songs.get(k))
                        for k, n in by_song.most_common(10)]
    out["new_artists"] = [(names[k], n) for k, n in by_artist.most_common() if k not in lib_artists][:10]
    out["new_artist_count"] = sum(1 for k in by_artist if k not in lib_artists)
    out["in_library"] = sum(1 for r in songs if (_norm(r["artist"]), _norm(r["title"])) in lib_songs)
    out["recent"] = [(r["title"], r["artist"] or "", r["station"] or "", r["at"],
                      lib_songs.get((_norm(r["artist"]), _norm(r["title"]))))
                     for r in reversed(songs[-10:])]
    out["liked"] = sum(1 for x in (liked or []) if (x.get("time") or 0) >= since)
    out["longest"] = max((s for _w, s in when), default=0)
    return out


def compute_both(lib, log, period: str = "all", liked: list | None = None, now: float | None = None) -> dict:
    """Library and radio together, by listening time."""
    now = now or time.time()
    today = dt.date.fromtimestamp(now)
    L = compute(lib, period, now)
    R = compute_radio(log, lib, period, liked, now)
    since = period_start(period, now)
    hist = lib.plays_since(since)
    lw = [(dt.datetime.fromtimestamp(h["played_at"]), h["seconds"] or 0) for h in hist]
    out: dict = {"period": period, "lib_seconds": L["seconds"], "radio_seconds": R["seconds"],
                 "lib_plays": L["plays"], "radio_songs": R["songs"], "radio": R, "library": L}
    out["seconds"] = L["seconds"] + R["seconds"]
    lt, rt = _time_buckets(period, lw, today), R["timeline"]
    out["timeline"] = [(s, a, long, b) for (s, a, long), (_s2, b, _l2) in zip(lt, rt)]
    lh, lwk = [0.0] * 24, [0.0] * 7
    for w, s in lw:
        lh[w.hour] += s
        lwk[w.weekday()] += s
    out["hours"] = list(zip(lh, R["hours"]))
    out["weekdays"] = list(zip(lwk, R["weekdays"]))
    lib_days = {dt.datetime.fromtimestamp(h["played_at"]).date() for h in lib.plays_since(0)}
    days = lib_days | R["days"]
    out["streak"] = _streak(days, today)
    out["active_days"] = len({w.date() for w, _s in lw} | {w.date() for w, s in R["when"] if s >= 60})

    lib_artists, _songs = library_index(lib)
    total, parts, shown = Counter(), defaultdict(lambda: [0, 0]), {}
    for a, n, _s in (_all_lib_artists(lib) if period == "all" else _hist_artists(hist)):
        k = _norm(a)
        shown.setdefault(k, a)
        total[k] += n
        parts[k][0] += n
    for name, n, _s, _lib in _radio_artist_counts(log, since):
        k = _norm(name)
        shown.setdefault(k, lib_artists.get(k) or name)
        total[k] += n
        parts[k][1] += n
    out["top_artists"] = [(shown[k], n, parts[k][0], parts[k][1], lib_artists.get(k)) for k, n in total.most_common(10)]
    out["artists"] = len(total)
    g = defaultdict(lambda: [0.0, 0.0])
    for h in hist:
        g[h["genre"] or "No genre"][0] += h["seconds"] or 0
    if period == "all" and not hist:
        for t in lib.tracks.values():
            if t["playcount"]:
                g[t["genre"] or "No genre"][0] += t["playcount"] * (t["length"] or 0)
    for tag, s in R["genres"]:
        g[tag][1] += s
    merged = {}
    for k, (a, b) in g.items():  # "rock" and "Rock" are one genre
        m = merged.setdefault(_norm(k), [k, 0.0, 0.0])
        m[1] += a
        m[2] += b
    out["genres"] = sorted(((n, a, b) for n, a, b in merged.values()), key=lambda x: -(x[1] + x[2]))[:10]
    return out


def _all_lib_artists(lib):
    by, secs = Counter(), defaultdict(float)
    for t in lib.tracks.values():
        n = t["playcount"] or 0
        if n:
            a = t["artist_key"] or t["artist"] or "Unknown Artist"
            by[a] += n
            secs[a] += n * (t["length"] or 0)
    return [(a, n, secs[a]) for a, n in by.items()]


def _hist_artists(hist):
    by = Counter(h["albumartist"] or h["artist"] or "Unknown Artist" for h in hist)
    return [(a, n, 0) for a, n in by.items()]


def _radio_artist_counts(log, since):
    by, names = Counter(), {}
    for r in log.songs_since(since):
        if r["artist"]:
            k = _norm(r["artist"])
            names.setdefault(k, r["artist"])
            by[k] += 1
    return [(names[k], n, 0, None) for k, n in by.items()]


def _timeline(period: str, stamps: list, today: dt.date) -> list[tuple[str, int, str]]:
    """(short label, plays, long label) per day or month."""
    if period in ("7d", "30d"):
        n = 7 if period == "7d" else 30
        counts = Counter(s.date() for s in stamps)
        out = []
        for i in range(n - 1, -1, -1):
            d = today - dt.timedelta(days=i)
            short = WEEKDAYS[d.weekday()] if n == 7 else (str(d.day) if d.day in (1, 10, 20) or i == 0 else "")
            out.append((short, counts.get(d, 0), d.strftime("%a %d %b")))
        return out
    counts = Counter((s.year, s.month) for s in stamps)
    if period == "year":
        months = [(today.year, m) for m in range(1, today.month + 1)]
    else:
        first = min(counts) if counts else (today.year, today.month)
        y, m = first
        months = []
        while (y, m) <= (today.year, today.month):
            months.append((y, m))
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        months = months[-24:]
    return [(MONTHS[m - 1][:1] if len(months) > 12 else MONTHS[m - 1], counts.get((y, m), 0),
             f"{MONTHS[m - 1]} {y}") for y, m in months]


# radio colour beside the library's accent: the furthest categorical hue
_SECOND = {True: ["#3987e5", "#d95926", "#199e70", "#d55181", "#9085e9"],
           False: ["#2a78d6", "#eb6834", "#1baf7a", "#e87ba4", "#6250d6"]}


def radio_color(theme) -> QColor:
    acc = theme.color("accent")
    dark = theme.color("bg").lightness() < 128
    ah = acc.hslHue() if acc.hslHue() >= 0 else 210

    def dist(hexc):
        h = QColor(hexc).hslHue()
        d = abs(h - ah) % 360
        return min(d, 360 - d)
    return QColor(max(_SECOND[dark], key=dist))


def _seg_colors(theme):
    return theme.color("accent"), radio_color(theme)


class Legend(QWidget):
    """Shows which colour is library and which is radio."""

    def __init__(self, theme, names=("Library", "Radio")):
        super().__init__()
        self.theme, self.names = theme, names
        self.setFixedHeight(18)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        f = QFont(self.font())
        f.setPointSizeF(8.5)
        p.setFont(f)
        fm = QFontMetrics(f)
        x = 0
        for name, col in zip(self.names, _seg_colors(self.theme)):
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            p.drawRoundedRect(QRectF(x, 4, 10, 10), 3, 3)
            p.setPen(self.theme.color("muted"))
            p.drawText(QRectF(x + 15, 0, fm.horizontalAdvance(name) + 4, 18), Qt.AlignLeft | Qt.AlignVCenter, name)
            x += 15 + fm.horizontalAdvance(name) + 18

class Card(QFrame):
    def __init__(self, title: str, note: str = ""):
        super().__init__()
        self.setObjectName("StatCard")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(16, 12, 16, 14)
        self.lay.setSpacing(8)
        head = QLabel(title.upper())
        head.setObjectName("StatLabel")
        self.lay.addWidget(head)
        self.note = QLabel(note)
        self.note.setObjectName("EmptyText")
        self.note.setWordWrap(True)
        self.note.setVisible(bool(note))
        self.lay.addWidget(self.note)

    def set_note(self, text: str):
        self.note.setText(text)
        self.note.setVisible(bool(text))


class Tile(QFrame):
    def __init__(self, label: str):
        super().__init__()
        self.setObjectName("StatCard")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(2)
        self.label = QLabel(label.upper())
        self.label.setObjectName("StatLabel")
        self.value = QLabel("—")
        self.value.setObjectName("StatValue")
        self.sub = QLabel("")
        self.sub.setObjectName("EmptyText")
        self.sub.setWordWrap(True)
        for w in (self.label, self.value, self.sub):
            w.setMinimumWidth(1)
            lay.addWidget(w)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set(self, value: str, sub: str = ""):
        self.value.setText(value)
        self.sub.setText(sub)


class BarList(QWidget):
    """Ranked rows with a bar: label, second line, value on the right."""
    activated = Signal(object)
    doubleActivated = Signal(object)  # double-clicking a song plays it

    ROW = 34

    def __init__(self, theme):
        super().__init__()
        self.theme = theme
        self.rows: list = []  # (label, sub, value, value text, payload[, radio part])
        self.click_hint = "(click to show it in the library)"
        self.empty_text = "Nothing yet"
        self.bars = True
        self.keys: list = []  # what a right-click acts on per row
        self.row_menu = None  # callable(key, QMenu) or None
        self._hover = -1
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_rows(self, rows: list):
        self.rows = rows
        self.setFixedHeight(max(1, len(rows)) * self.ROW)
        self.update()

    def _row_at(self, y) -> int:
        i = int(y // self.ROW)
        return i if 0 <= i < len(self.rows) else -1

    def mouseMoveEvent(self, e):
        i = self._row_at(e.position().y())
        if i != self._hover:
            self._hover = i
            self.setCursor(Qt.PointingHandCursor if i >= 0 and self.rows[i][4] is not None else Qt.ArrowCursor)
            self.update()
        if i >= 0:
            label, sub, _v, vt, payload = self.rows[i][:5]
            tip = f"{label}\n{sub}\n{vt}" if sub else f"{label}\n{vt}"
            if payload is not None and self.click_hint:
                tip += "\n" + self.click_hint
            QToolTip.showText(e.globalPosition().toPoint() + QPoint(12, 12), tip, self)

    def leaveEvent(self, e):
        self._hover = -1
        self.update()

    def contextMenuEvent(self, e):
        i = self._row_at(e.pos().y())
        if i < 0 or self.row_menu is None or i >= len(self.keys) or self.keys[i] is None:
            return
        from PySide6.QtWidgets import QMenu
        m = QMenu(self)
        self.row_menu(self.keys[i], m)
        if m.actions():
            m.exec(e.globalPos())

    def mouseReleaseEvent(self, e):
        i = self._row_at(e.position().y())
        if i >= 0 and e.button() == Qt.LeftButton and self.rows[i][4] is not None:
            self.activated.emit(self.rows[i][4])

    def mouseDoubleClickEvent(self, e):
        i = self._row_at(e.position().y())
        if i >= 0 and e.button() == Qt.LeftButton and self.rows[i][4] is not None:
            self.doubleActivated.emit(self.rows[i][4])

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        t = self.theme
        if not self.rows:
            p.setPen(t.color("faint"))
            p.drawText(self.rect(), Qt.AlignLeft | Qt.AlignVCenter, self.empty_text)
            return
        top = max((r[2] for r in self.rows), default=1) or 1
        w = self.width()
        fnt = QFont(self.font())
        fnt.setPointSizeF(9.5)
        small = QFont(self.font())
        small.setPointSizeF(8)
        fm, fms = QFontMetrics(fnt), QFontMetrics(small)
        val_w = min(w // 2, max(fm.horizontalAdvance(r[3]) for r in self.rows) + 10)
        num_w = 22
        bar_w = w - num_w - val_w
        c_lib, c_radio = _seg_colors(t)
        if getattr(self, "radio", False):
            c_lib = c_radio  # Radio tab: one series in the radio colour
        for i, row in enumerate(self.rows):
            label, sub, value, vtext = row[:4]
            part2 = row[5] if len(row) > 5 else None
            y = i * self.ROW
            if i == self._hover:
                p.fillRect(QRectF(0, y, w, self.ROW - 2), t.color("hover"))
            p.setFont(small)
            p.setPen(t.color("faint"))
            p.drawText(QRectF(0, y, num_w, self.ROW - 8), Qt.AlignLeft | Qt.AlignVCenter, str(i + 1))
            track = QRectF(num_w, y + self.ROW - 9, bar_w, 4)
            if self.bars:
                p.setPen(Qt.NoPen)
                p.setBrush(t.color("hover"))
                p.drawRoundedRect(track, 2, 2)
                full = max(4.0, bar_w * value / top)
                if part2 is None:
                    p.setBrush(c_lib)
                    p.drawRoundedRect(QRectF(num_w, y + self.ROW - 9, full, 4), 2, 2)
                else:
                    # library then radio, 2 px apart
                    a = full * (value - part2) / value if value else 0
                    b = full - a
                    if a > 0.5:
                        p.setBrush(c_lib)
                        p.drawRoundedRect(QRectF(num_w, y + self.ROW - 9, max(3.0, a - (2 if b > 0.5 else 0)), 4), 2, 2)
                    if b > 0.5:
                        p.setBrush(c_radio)
                        p.drawRoundedRect(QRectF(num_w + a, y + self.ROW - 9, max(3.0, b), 4), 2, 2)
            # text never uses the bar colour
            p.setFont(fnt)
            p.setPen(t.color("text"))
            room = bar_w - 8
            name = fm.elidedText(label, Qt.ElideRight, int(room * (0.62 if sub else 1.0)))
            p.drawText(QRectF(num_w, y + 1, room, self.ROW - 12), Qt.AlignLeft | Qt.AlignVCenter, name)
            if sub:
                p.setFont(small)
                p.setPen(t.color("muted"))
                x = num_w + fm.horizontalAdvance(name) + 8
                p.drawText(QRectF(x, y + 1, max(0, num_w + room - x), self.ROW - 12),
                           Qt.AlignLeft | Qt.AlignVCenter, fms.elidedText(sub, Qt.ElideRight, int(num_w + room - x)))
            p.setFont(fnt)
            p.setPen(t.color("muted"))
            p.drawText(QRectF(w - val_w, y + 1, val_w, self.ROW - 4), Qt.AlignRight | Qt.AlignVCenter, vtext)


class Columns(QWidget):
    """A series of columns (days, months, hours) with hover tooltips."""

    def __init__(self, theme, height: int = 150):
        super().__init__()
        self.theme = theme
        self.items: list = []  # (short label, value, long label[, stacked second value])
        self.unit = "plays"
        self.fmt = None  # value -> tooltip text
        self.names = ("Library", "Radio")
        self.empty_text = "No plays in this period yet"
        self._hover = -1
        self.setMouseTracking(True)
        self.setFixedHeight(height)

    def set_items(self, items: list, unit: str = "plays", fmt=None):
        self.items, self.unit, self.fmt = items, unit, fmt
        self.update()

    def _vtext(self, v) -> str:
        if self.fmt:
            return self.fmt(v)
        v = int(v)
        return f"{v:,} {self.unit if v != 1 else self.unit.rstrip('s')}"

    def _geom(self):
        n = max(1, len(self.items))
        left, bottom = 4, 20
        slot = (self.width() - left) / n
        return n, left, bottom, slot

    def _index_at(self, x) -> int:
        n, left, _b, slot = self._geom()
        i = int((x - left) // slot)
        return i if 0 <= i < len(self.items) else -1

    def mouseMoveEvent(self, e):
        i = self._index_at(e.position().x())
        if i != self._hover:
            self._hover = i
            self.update()
        if i >= 0:
            it = self.items[i]
            if len(it) > 3:
                tip = (f"{it[2]}\n{self.names[0]}: {self._vtext(it[1])}\n{self.names[1]}: {self._vtext(it[3])}"
                       f"\nTogether: {self._vtext(it[1] + it[3])}")
            else:
                tip = f"{it[2]}\n{self._vtext(it[1])}"
            QToolTip.showText(e.globalPosition().toPoint() + QPoint(12, 12), tip, self)

    def leaveEvent(self, e):
        self._hover = -1
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        t = self.theme
        n, left, bottom, slot = self._geom()
        h = self.height() - bottom - 6
        top = max((it[1] + (it[3] if len(it) > 3 else 0) for it in self.items), default=0)
        c_lib, c_radio = _seg_colors(t)
        if getattr(self, "radio", False):
            c_lib = c_radio  # Radio tab: one series in the radio colour
        p.fillRect(QRectF(left, h + 6, self.width() - left, 1), t.color("border"))
        if not top:
            p.setPen(t.color("faint"))
            p.drawText(QRectF(0, 0, self.width(), h), Qt.AlignCenter, self.empty_text)
        bw = max(2.0, min(22.0, slot * 0.62))
        small = QFont(self.font())
        small.setPointSizeF(7.5)
        p.setFont(small)
        for i, it in enumerate(self.items):
            short, v = it[0], it[1]
            v2 = it[3] if len(it) > 3 else 0
            x = left + i * slot + (slot - bw) / 2
            if i == self._hover:
                p.fillRect(QRectF(left + i * slot, 0, slot, h + 6), t.color("hover"))
            if top and (v or v2):
                p.setPen(Qt.NoPen)
                total = max(3.0, h * (v + v2) / top)
                bh = total * v / (v + v2) if v2 else total
                base = h + 6
                if v2:
                    # radio stacked on library, 2 px apart; only the top is rounded
                    rh = total - bh
                    gap = 2 if v and rh > 2 and bh > 2 else 0
                    rh2 = max(2.0, rh - gap)
                    r = min(4.0, bw / 2, rh2 / 2)
                    p.setBrush(c_radio)
                    p.drawRoundedRect(QRectF(x, base - total, bw, rh2), r, r)
                    p.drawRect(QRectF(x, base - total + rh2 - min(rh2, r), bw, min(rh2, r)))
                    if v:
                        p.setBrush(c_lib)
                        p.drawRect(QRectF(x, base - bh, bw, bh))
                else:
                    r = min(4.0, bw / 2, bh / 2)
                    p.setBrush(c_lib)
                    p.drawRoundedRect(QRectF(x, base - bh, bw, bh), r, r)
                    p.drawRect(QRectF(x, base - min(bh, r), bw, min(bh, r)))
            if short:
                p.setPen(t.color("faint"))
                p.drawText(QRectF(left + i * slot - 20, h + 8, slot + 40, bottom - 4),
                           Qt.AlignHCenter | Qt.AlignTop, short)


def ago_text(ts: float, now: float | None = None) -> str:
    s = max(0, (now or time.time()) - ts)
    if s < 90:
        return "just now"
    if s < 3600:
        return f"{s / 60:.0f} min ago"
    if s < 86400:
        h = s / 3600
        return f"{h:.0f} hour{'s' if round(h) != 1 else ''} ago"
    d = dt.datetime.fromtimestamp(ts)
    return d.strftime("%a %d %b")


def pct(a: float, total: float) -> str:
    return f"{a * 100 / total:.0f}%" if total else "0%"


class StatsPage(QScrollArea):
    clearRequested = Signal()
    showArtist = Signal(str)
    showAlbum = Signal(str, str)  # album artist, album
    playTrack = Signal(int)
    showTrack = Signal(int)
    playStation = Signal(object)
    notASong = Signal(str, str)  # artist, title: mark a radio "song" as not a song
    viewChanged = Signal(str)

    VIEWS = [("library", "Library"), ("radio", "Radio"), ("both", "Library + Radio")]

    def __init__(self, lib, theme, parent=None):
        super().__init__(parent)
        self.lib, self.theme = lib, theme
        self.radio_log = None  # set by the main window
        self.stations = None  # for liked radio songs
        self.period = "all"
        self.view = "library"
        self._tile_grids = []
        self.dirty = True
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        body.setObjectName("StatsBody")
        self.setObjectName("StatsPage")
        self.setWidget(body)
        v = QVBoxLayout(body)
        v.setContentsMargins(16, 8, 16, 20)
        v.setSpacing(14)

        head = QHBoxLayout()
        title = QLabel("Stats")
        title.setObjectName("PageTitle")
        head.addWidget(title)
        head.addSpacing(14)
        self.vgroup = QButtonGroup(self)
        self.view_buttons = {}
        for i, (key, name) in enumerate(self.VIEWS):
            b = QPushButton(name)
            b.setCheckable(True)
            b.setObjectName("Segment")
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip({"library": "Your own music: plays, artists, albums, songs",
                          "radio": "Internet radio: stations, time listened, songs heard",
                          "both": "Your music and the radio together, by listening time"}[key])
            self.vgroup.addButton(b, i)
            self.view_buttons[key] = b
            head.addWidget(b)
        self.view_buttons["library"].setChecked(True)
        self.vgroup.idClicked.connect(lambda i: self.set_view(self.VIEWS[i][0]))
        head.addStretch()
        self.clear_btn = QPushButton("Clear stats…")
        self.clear_btn.setToolTip("Start your stats again: listening history, play counts and/or radio listening")
        self.clear_btn.clicked.connect(self.clearRequested)
        head.addWidget(self.clear_btn)
        v.addLayout(head)
        # period on its own row so the page fits beside the panels
        prow = QHBoxLayout()
        prow.setSpacing(6)
        self.group = QButtonGroup(self)
        for i, (key, name) in enumerate(PERIODS):
            b = QPushButton(name)
            b.setCheckable(True)
            b.setObjectName("Segment")
            b.setCursor(Qt.PointingHandCursor)
            self.group.addButton(b, i)
            prow.addWidget(b)
            if key == self.period:
                b.setChecked(True)
        self.group.idClicked.connect(lambda i: self.set_period(PERIODS[i][0]))
        prow.addStretch()
        v.addLayout(prow)
        self.history_note = QLabel("")
        self.history_note.setObjectName("EmptyText")
        self.history_note.setWordWrap(True)
        v.addWidget(self.history_note)

        # only the visible view takes up room
        self.bodies = {"library": self._build_library(), "radio": self._build_radio(), "both": self._build_both()}
        for key, b in self.bodies.items():
            v.addWidget(b)
            b.setVisible(key == self.view)
        v.addStretch()

    def _body(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        return w, lay

    def _tiles(self, lay, names):
        g = QGridLayout()
        g.setSpacing(12)
        tiles = [Tile(n) for n in names]
        self._tile_grids.append((g, tiles))
        self._place_tiles(g, tiles, 6)
        lay.addLayout(g)
        return tiles

    @staticmethod
    def _place_tiles(g, tiles, cols):
        for t in tiles:
            g.removeWidget(t)
        for c in range(6):
            g.setColumnStretch(c, 1 if c < cols else 0)
        for i, t in enumerate(tiles):
            g.addWidget(t, i // cols, i % cols)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        cols = 6 if self.viewport().width() >= 1060 else 3  # two rows of three when narrow
        if cols != getattr(self, "_tile_cols", 6):
            self._tile_cols = cols
            for g, tiles in self._tile_grids:
                self._place_tiles(g, tiles, cols)

    def _grid(self, lay, cards):
        grid = QGridLayout()
        grid.setSpacing(14)
        for i, c in enumerate(cards):
            grid.addWidget(c, i // 2, i % 2, Qt.AlignTop)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)

    def _chart_card(self, title, height=130, legend=False, radio=False):
        c = Card(title)
        if legend:
            c.lay.addWidget(Legend(self.theme))
        ch = Columns(self.theme, height)
        ch.radio = radio
        c.lay.addWidget(ch)
        return c, ch

    def _build_library(self):
        w, v = self._body()
        (self.t_plays, self.t_time, self.t_streak, self.t_songs, self.t_artists,
         self.t_albums) = self._tiles(v, ["Plays", "Listening time", "Streak", "Songs", "Artists", "Albums"])
        self.c_time, self.timeline = self._chart_card("Listening over time", 160)
        v.addWidget(self.c_time)
        self.c_artists, self.l_artists = self._list_card("Top artists")
        self.c_albums, self.l_albums = self._list_card("Top albums")
        self.c_songs, self.l_songs = self._list_card("Top songs")
        self.c_genres, self.l_genres = self._list_card("Genres")
        self.c_hours, self.hours = self._chart_card("Time of day")
        self.c_week, self.week = self._chart_card("Day of the week")
        self.c_decades, self.decades = self._chart_card("Your library by decade")
        self.c_formats, self.l_formats = self._list_card("File formats")
        self.c_skips, self.l_skips = self._list_card("Most skipped", "Songs you often skip — all time")
        self._grid(v, [self.c_artists, self.c_albums, self.c_songs, self.c_genres, self.c_hours, self.c_week,
                       self.c_decades, self.c_formats, self.c_skips])
        self.l_artists.activated.connect(lambda a: self.showArtist.emit(str(a)))
        self.l_albums.activated.connect(lambda k: self.showAlbum.emit(*k))
        for lst in (self.l_songs, self.l_skips):
            lst.activated.connect(lambda tid: self.showTrack.emit(int(tid)))
            lst.doubleActivated.connect(lambda tid: self.playTrack.emit(int(tid)))
            lst.click_hint = "(click to show it in your library — double-click to play it)"
        self.l_artists.click_hint = "(click for their page)"
        self.l_albums.click_hint = "(click to show the album)"
        for lst in (self.l_genres, self.l_formats):
            lst.click_hint = ""
        return w

    def _build_radio(self):
        w, v = self._body()
        (self.r_time, self.r_stations, self.r_songs, self.r_new, self.r_liked,
         self.r_streak) = self._tiles(v, ["Radio time", "Stations", "Songs heard", "New to you", "♥ Liked",
                                          "Streak"])
        self.rc_time, self.r_timeline = self._chart_card("Radio listening over time", 160, radio=True)
        v.addWidget(self.rc_time)
        self.rc_stations, self.rl_stations = self._list_card("Top stations", radio=True)
        self.rc_artists, self.rl_artists = self._list_card("Artists you heard", radio=True)
        self.rc_songs, self.rl_songs = self._list_card("Songs you heard", radio=True)
        self.rc_new, self.rl_new = self._list_card("New to you", "Artists the radio played that aren't in your "
                                                                 "library", radio=True)
        self.rc_genres, self.rl_genres = self._list_card("Station genres", radio=True)
        self.rc_countries, self.rl_countries = self._list_card("Where the stations are", radio=True)
        self.rc_hours, self.r_hours = self._chart_card("Time of day", radio=True)
        self.rc_week, self.r_week = self._chart_card("Day of the week", radio=True)
        self.rc_recent, self.rl_recent = self._list_card("Recently heard", radio=True)
        self.rl_recent.bars = False
        self._grid(v, [self.rc_stations, self.rc_artists, self.rc_songs, self.rc_new, self.rc_genres,
                       self.rc_countries, self.rc_hours, self.rc_week, self.rc_recent])
        self.rl_stations.click_hint = "(click to tune in)"
        self.rl_stations.activated.connect(self.playStation)
        self.rl_artists.activated.connect(lambda a: self.showArtist.emit(str(a)))
        for lst in (self.rl_songs, self.rl_recent):
            lst.click_hint = "(in your library — click to play it)"
            lst.activated.connect(lambda tid: self.playTrack.emit(int(tid)))
        for lst in (self.rl_new, self.rl_genres, self.rl_countries):
            lst.click_hint = ""
        return w

    def _build_both(self):
        w, v = self._body()
        (self.b_time, self.b_lib, self.b_radio, self.b_streak, self.b_days,
         self.b_artists) = self._tiles(v, ["Listening time", "Library", "Radio", "Streak", "Days with music",
                                           "Artists heard"])
        self.bc_time, self.b_timeline = self._chart_card("Listening over time", 160, legend=True)
        v.addWidget(self.bc_time)
        self.bc_artists, self.bl_artists = self._list_card("Top artists", "Plays of your songs and songs heard on "
                                                                          "the radio", legend=True)
        self.bc_genres, self.bl_genres = self._list_card("Genres", "By listening time", legend=True)
        self.bc_hours, self.b_hours = self._chart_card("Time of day", legend=True)
        self.bc_week, self.b_week = self._chart_card("Day of the week", legend=True)
        self._grid(v, [self.bc_artists, self.bc_genres, self.bc_hours, self.bc_week])
        self.bl_artists.activated.connect(lambda a: self.showArtist.emit(str(a)))
        self.bl_genres.click_hint = ""
        return w

    def _list_card(self, title: str, note: str = "", radio=False, legend=False):
        c = Card(title, note)
        if legend:
            c.lay.addWidget(Legend(self.theme))
        lst = BarList(self.theme)
        lst.radio = radio
        if radio:
            lst.row_menu = self._radio_song_menu
        c.lay.addWidget(lst)
        return c, lst

    def _radio_song_menu(self, key, m):
        artist, title = key
        what = f"“{title}”" + (f" by {artist}" if artist else "")
        act = m.addAction(f"Not a song — take {what} out of the radio stats",
                          lambda: self.notASong.emit(artist, title))
        act.setToolTip("For an advert, a jingle, a station ID or the news. It's remembered for that station.")
        m.setToolTipsVisible(True)

    def set_view(self, view: str):
        if view not in dict(self.VIEWS):
            view = "library"
        changed = view != self.view
        self.view = view
        self.view_buttons[view].setChecked(True)
        for key, b in self.bodies.items():
            b.setVisible(key == view)
        self.refresh()
        if changed:
            self.viewChanged.emit(view)

    def set_period(self, period: str):
        self.period = period
        keys = [k for k, _ in PERIODS]
        if period in keys:
            self.group.button(keys.index(period)).setChecked(True)
        self.refresh()

    def mark_dirty(self):
        self.dirty = True
        if self.isVisible():
            self.refresh()

    def showEvent(self, e):
        super().showEvent(e)
        if self.dirty:
            self.refresh()

    def refresh_theme(self):
        for w in self.findChildren(QWidget):
            if isinstance(w, (BarList, Columns, Legend)):
                w.update()

    def refresh(self):
        self.dirty = False
        if self.view == "radio":
            self._refresh_radio()
        elif self.view == "both":
            self._refresh_both()
        else:
            self._refresh_library()

    def _liked(self):
        try:
            return self.stations.liked() if self.stations is not None else []
        except Exception:
            return []

    def _refresh_library(self):
        d = compute(self.lib, self.period)
        name = dict(PERIODS)[self.period].lower()
        L = d["library"]
        self.t_plays.set(f"{d['plays']:,}", name)
        self.t_time.set(hours_text(d["seconds"]), name)
        self.t_streak.set(f"{d['streak']} day{'s' if d['streak'] != 1 else ''}",
                          "in a row with music" if d["streak"] else "play something today")
        self.t_songs.set(f"{L['songs']:,}", f"{hours_text(L['length'])} · {L['never']:,} never played")
        self.t_artists.set(f"{L['artists']:,}", "in your library")
        self.t_albums.set(f"{L['albums']:,}", f"{L['size'] / 1e9:,.1f} GB of music" if L["size"] else "")
        start = d["history_start"]
        if start is None:
            self.history_note.setText("Musicwell has started keeping a listening history. “All time” uses the play "
                                      "counts you already have; the charts by day, hour and the shorter periods "
                                      "fill in as you listen.")
        elif self.period == "all":
            self.history_note.setText(f"Top lists count every play. The charts by day and hour use the listening "
                                      f"history, kept since {dt.date.fromtimestamp(start).strftime('%d %B %Y')}. "
                                      f"The radio isn't counted here — see Radio.")
        else:
            self.history_note.setText("")
        self.timeline.set_items(d["timeline"])
        self.l_artists.set_rows([(a, "", n, f"{plays_text(n)} · {hours_text(s)}", a) for a, n, s in d["top_artists"]])
        rows = []
        for (artist, album), n, _t in d["top_albums"]:
            rows.append((album, artist, n, plays_text(n), (artist, album)))
        self.l_albums.set_rows(rows)
        rows = []
        for key, n in d["top_songs"]:
            if isinstance(key, tuple):
                rows.append((key[1] or "?", key[2] or "", n, plays_text(n), None))
            else:
                t = self.lib.tracks.get(key)
                if t:
                    rows.append((t["title"], t["artist"] or "", n, plays_text(n), key))
        self.l_songs.set_rows(rows)
        total = sum(n for _g, n in d["genres"]) or 1
        self.l_genres.set_rows([(g, "", n, f"{n * 100 / total:.0f}%", None) for g, n in d["genres"]])
        self.hours.set_items([(str(h) if h % 3 == 0 else "", n, f"{h:02d}:00–{h:02d}:59")
                              for h, n in enumerate(d["hours"])])
        self.week.set_items([(WEEKDAYS[i], n, WEEKDAYS[i]) for i, n in enumerate(d["weekdays"])])
        self.decades.set_items([(f"{dec % 100:02d}s", n, f"{dec}s") for dec, n in d["decades"]], "songs")
        self.l_formats.set_rows([(f, "", n, f"{n:,} songs", None) for f, n in d["formats"]])
        self.l_skips.set_rows([(t["title"], t["artist"] or "", t["skipcount"],
                                f"skipped {t['skipcount']}×", t["id"]) for t in d["skipped"]])
        for c, lst in ((self.c_artists, self.l_artists), (self.c_albums, self.l_albums),
                       (self.c_songs, self.l_songs), (self.c_genres, self.l_genres)):
            c.set_note("" if lst.rows else ("Play some music and your favourites show up here."
                                            if self.period == "all" else "Nothing played in this period yet."))

    def _refresh_radio(self):
        if self.radio_log is None:
            return
        d = compute_radio(self.radio_log, self.lib, self.period, self._liked())
        name = dict(PERIODS)[self.period].lower()
        self.r_time.set(hours_text(d["seconds"]), name)
        self.r_stations.set(f"{d['stations']:,}", f"tuned in {d['tunes']:,} time{'s' if d['tunes'] != 1 else ''}")
        self.r_songs.set(f"{d['songs']:,}", f"by {d['artists']:,} artist{'s' if d['artists'] != 1 else ''}"
                         + (f" · {d['in_library']:,} in your library" if d["in_library"] else ""))
        self.r_new.set(f"{d['new_artist_count']:,}", "artists not in your library")
        self.r_liked.set(f"{d['liked']:,}", name)
        self.r_streak.set(f"{d['streak']} day{'s' if d['streak'] != 1 else ''}",
                          "in a row with radio" if d["streak"] else "tune in today")
        if d["first"] is None:
            self.history_note.setText("Musicwell keeps track of your radio listening from now on: the stations, "
                                      "how long you listen and the songs they play. Tune in on the Radio tab and "
                                      "this fills in. (Radio never changes your library's play counts.)")
        else:
            self.history_note.setText(f"Only time actually playing counts. Songs heard for less than "
                                      f"{SONG_MIN_SECONDS} s (jingles, adverts, station IDs) are left out. Kept since "
                                      f"{dt.date.fromtimestamp(d['first']).strftime('%d %B %Y')}.")
        hrs = hours_text
        self.r_timeline.empty_text = "No radio in this period yet"
        self.r_timeline.set_items(d["timeline"], fmt=hrs)
        self.rl_stations.set_rows([(st.get("name") or "?", ", ".join((st.get("tags") or "").split(",")[:2]).strip(),
                                    s, f"{hrs(s)} · {n}×" if n else hrs(s), st) for st, s, n in d["top_stations"]])
        self.rl_artists.set_rows([(a, "in your library" if lib_a else "", n,
                                   f"{n} song{'s' if n != 1 else ''} · {hrs(s)}", lib_a)
                                  for a, n, s, lib_a in d["top_artists"]])
        self.rl_songs.set_rows([(t, f"{a} · {st}" if a else st, n, f"heard {n}×", tid)
                                for t, a, n, st, tid in d["top_songs"]])
        self.rl_songs.keys = [(a, t) for t, a, n, st, tid in d["top_songs"]]
        self.rl_new.set_rows([(a, "", n, f"heard {n}×", None) for a, n in d["new_artists"]])
        self.rl_genres.set_rows([(g, "", s, hrs(s), None) for g, s in d["genres"]])
        self.rl_countries.set_rows([(c, "", s, hrs(s), None) for c, s in d["countries"]])
        self.r_hours.empty_text = self.r_week.empty_text = "No radio in this period yet"
        self.r_hours.set_items([(str(h) if h % 3 == 0 else "", s, f"{h:02d}:00–{h:02d}:59")
                                for h, s in enumerate(d["hours"])], fmt=hrs)
        self.r_week.set_items([(WEEKDAYS[i], s, WEEKDAYS[i]) for i, s in enumerate(d["weekdays"])], fmt=hrs)
        self.rl_recent.set_rows([(t, " · ".join(x for x in (a, st) if x), 1, ago_text(at), tid)
                                 for t, a, st, at, tid in d["recent"]])
        self.rl_recent.keys = [(a, t) for t, a, st, at, tid in d["recent"]]
        empty = "Nothing on the radio in this period yet." if self.period != "all" else \
            "Listen to a station and this fills in."
        for c, lst in ((self.rc_stations, self.rl_stations), (self.rc_artists, self.rl_artists),
                       (self.rc_songs, self.rl_songs), (self.rc_genres, self.rl_genres),
                       (self.rc_countries, self.rl_countries), (self.rc_recent, self.rl_recent)):
            lst.empty_text = ""
            c.set_note("" if lst.rows else empty)
        self.rl_new.empty_text = ""
        self.rc_new.set_note("Artists the radio played that aren't in your library" +
                             ("" if self.rl_new.rows else " — none yet."))
        self.rl_songs.empty_text = ""

    def _refresh_both(self):
        if self.radio_log is None:
            return
        d = compute_both(self.lib, self.radio_log, self.period, self._liked())
        name = dict(PERIODS)[self.period].lower()
        tot, ls, rs = d["seconds"], d["lib_seconds"], d["radio_seconds"]
        hrs = hours_text
        self.b_time.set(hrs(tot), name)
        self.b_lib.set(hrs(ls), f"{pct(ls, tot)} · {plays_text(d['lib_plays'])}")
        self.b_radio.set(hrs(rs), f"{pct(rs, tot)} · {d['radio_songs']:,} song{'s' if d['radio_songs'] != 1 else ''} heard")
        self.b_streak.set(f"{d['streak']} day{'s' if d['streak'] != 1 else ''}",
                          "in a row with music or radio" if d["streak"] else "listen to something today")
        self.b_days.set(f"{d['active_days']:,}", name)
        self.b_artists.set(f"{d['artists']:,}", "played or heard")
        self.history_note.setText("Your music and the radio together. "
                                  + ("“All time” library time counts every play; the charts by day and hour use "
                                     "the listening history." if self.period == "all" else ""))
        for ch in (self.b_timeline, self.b_hours, self.b_week):
            ch.empty_text = "Nothing in this period yet"
        self.b_timeline.set_items(d["timeline"], fmt=hrs)
        self.b_hours.set_items([(str(h) if h % 3 == 0 else "", a, f"{h:02d}:00–{h:02d}:59", b)
                                for h, (a, b) in enumerate(d["hours"])], fmt=hrs)
        self.b_week.set_items([(WEEKDAYS[i], a, WEEKDAYS[i], b) for i, (a, b) in enumerate(d["weekdays"])], fmt=hrs)

        def parts(a, b):
            out = []
            if a:
                out.append(plays_text(a))
            if b:
                out.append(f"{b} on the radio")
            return " · ".join(out)
        self.bl_artists.set_rows([(name_, "", n, parts(a, b), lib_a, b) for name_, n, a, b, lib_a in d["top_artists"]])
        self.bl_genres.set_rows([(g, "", a + b, hrs(a + b), None, b) for g, a, b in d["genres"]])
        for c, lst, note in ((self.bc_artists, self.bl_artists, "Plays of your songs and songs heard on the radio"),
                             (self.bc_genres, self.bl_genres, "By listening time")):
            c.set_note(note if lst.rows else note + " — nothing in this period yet.")


class ClearStatsDialog(QDialog):
    """Reset stats. Ratings, playlists and music are never touched."""

    def __init__(self, lib, parent=None, radio_log=None):
        super().__init__(parent)
        self.lib = lib
        self.radio_log = radio_log
        self.setWindowTitle("Clear stats")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        intro = QLabel("Choose what to clear. Your ratings, playlists and music files are kept. "
                       "This can't be undone.")
        intro.setWordWrap(True)
        intro.setObjectName("EmptyText")
        lay.addWidget(intro)
        n_plays = len(lib.plays_since(0))
        n_counted = sum(1 for t in lib.tracks.values() if t.get("playcount") or t.get("skipcount") or t.get("lastplayed"))
        self.history = QCheckBox(f"Listening history — everything on this Stats page  ({n_plays:,} plays)")
        self.counts = QCheckBox(f"Play counts, skip counts and “last played” on every song  ({n_counted:,} songs)")
        self.counts.setToolTip("The Plays, Skips and Last played columns, and smart searches such as #(plays > 5)")
        self.history.setChecked(True)
        self.counts.setChecked(True)
        lay.addWidget(self.history)
        lay.addWidget(self.counts)
        self.radio = QCheckBox("Radio listening — the Radio stats (stations, time listened, songs heard)")
        if radio_log is not None:
            secs = sum(r["seconds"] or 0 for r in radio_log.time_since(0))
            n = len(radio_log.songs_since(0))
            self.radio.setText(f"Radio listening — stations, time and songs heard  ({hours_text(secs)}, "
                               f"{n:,} song{'s' if n != 1 else ''})")
            self.radio.setToolTip("Your favourite stations and ♥ Liked songs are kept")
            self.radio.setChecked(True)
            lay.addWidget(self.radio)
        else:
            self.radio.hide()
        bb = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.go = bb.addButton("Clear", QDialogButtonBox.AcceptRole)
        self.go.setObjectName("Primary")
        bb.accepted.connect(self._clear)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        for c in (self.history, self.counts, self.radio):
            c.toggled.connect(lambda _: self.go.setEnabled(self.history.isChecked() or self.counts.isChecked()
                                                           or self.radio.isChecked()))

    def _clear(self):
        if QMessageBox.question(self, "Clear stats", "Clear the selected stats? This can't be undone.") \
                != QMessageBox.Yes:
            return
        if self.history.isChecked() or self.counts.isChecked():
            self.lib.clear_stats(history=self.history.isChecked(), counts=self.counts.isChecked())
        if self.radio_log is not None and self.radio.isChecked():
            self.radio_log.clear()
        self.accept()
