"""Radio listening history for the Stats page, stored in the library database."""
from __future__ import annotations

import time

from PySide6.QtCore import QObject, QTimer, Signal

SCHEMA = """
CREATE TABLE IF NOT EXISTS radio_stations (
    uuid TEXT PRIMARY KEY, name TEXT, tags TEXT, country TEXT, url TEXT, codec TEXT, bitrate INTEGER
);
CREATE TABLE IF NOT EXISTS radio_tunes (at REAL, uuid TEXT);
CREATE INDEX IF NOT EXISTS radio_tunes_at ON radio_tunes (at);
CREATE TABLE IF NOT EXISTS radio_time (hour INTEGER, uuid TEXT, seconds REAL, PRIMARY KEY (hour, uuid));
CREATE TABLE IF NOT EXISTS radio_songs (
    at REAL, uuid TEXT, station TEXT, artist TEXT, title TEXT, text TEXT, seconds REAL
);
CREATE INDEX IF NOT EXISTS radio_songs_at ON radio_songs (at);
"""

SONG_MIN_SECONDS = 30  # shorter is a jingle, advert or station ID


def station_key(st: dict) -> str:
    return st.get("uuid") or st.get("url") or st.get("name") or "?"


class RadioLog(QObject):
    changed = Signal()

    TICK_MS = 1000
    SAVE_EVERY = 30.0  # seconds between writes

    def __init__(self, con, player=None, parent=None):
        super().__init__(parent)
        self.con = con
        con.executescript(SCHEMA)
        con.commit()
        self.player = player
        self._station: dict | None = None
        self._pending: dict = {}  # (hour, uuid) -> unsaved seconds
        self._song: dict | None = None
        self._unsaved = 0.0
        self._last = None
        # is_break(text, station, sends_songs) -> True for adverts, jingles, news etc. Set by the main window.
        self.is_break = None
        self._names_songs: dict = {}  # station -> sends "Artist - Title" (learned)
        self.timer = QTimer(self)
        self.timer.setInterval(self.TICK_MS)
        self.timer.timeout.connect(self._tick)
        if player is not None:
            player.radioChanged.connect(self.station_changed)
            player.trackChanged.connect(self.track_changed)

    def station_changed(self, st):
        self.flush()
        self._song = None
        self._station = st
        if st is None:
            self.timer.stop()
            self._last = None
            return
        k = station_key(st)
        self.con.execute("INSERT OR REPLACE INTO radio_stations VALUES (?,?,?,?,?,?,?)",
                         (k, st.get("name") or "", st.get("tags") or "", st.get("country") or "",
                          st.get("url") or "", st.get("codec") or "", int(st.get("bitrate") or 0)))
        self.con.execute("INSERT INTO radio_tunes VALUES (?,?)", (time.time(), k))
        self.con.commit()
        self._last = time.monotonic()
        self.timer.start()
        self.changed.emit()

    def track_changed(self, t):
        if not t or not t.get("stream") or self._station is None:
            return
        text = t.get("now_playing") or ""
        if not text:
            return
        if self._song and self._song["text"] == text:
            # same song with artist and title swapped: keep one row
            self._song["artist"], self._song["title"] = t.get("artist") or "", t.get("title") or ""
            if self._song.get("rowid"):
                self.con.execute("UPDATE radio_songs SET artist=?, title=? WHERE rowid=?",
                                 (self._song["artist"], self._song["title"], self._song["rowid"]))
                self.con.commit()
            return
        self.flush()
        if self._break(text, self._station, self.names_songs(station_key(self._station))):
            self._song = None  # advert break: not a song, but the time still counts
            return
        self._song = {"rowid": None, "text": text, "artist": t.get("artist") or "",
                      "title": t.get("title") or "", "seconds": 0.0, "saved": 0.0, "at": time.time()}

    def _break(self, text: str, st, sends_songs: bool = False) -> bool:
        if self.is_break is None:
            return False
        try:
            return bool(self.is_break(text, st, sends_songs))
        except Exception:
            return False

    def names_songs(self, uuid: str) -> bool:
        """Whether this station usually sends "Artist - Title"."""
        if uuid not in self._names_songs:
            r = self.con.execute("SELECT COUNT(*), SUM(text LIKE '% - %') FROM radio_songs WHERE uuid=?",
                                 (uuid,)).fetchone()
            n, named = (r[0] or 0), (r[1] or 0)
            self._names_songs[uuid] = n >= 5 and named >= n * 0.6
        return self._names_songs[uuid]

    def forget(self, artist: str, title: str) -> list[tuple[str, str]]:
        """Remove a title from the radio stats. Returns (station, title) pairs so they can be marked as adverts."""
        def norm(x):
            return " ".join((x or "").lower().split())
        found = [(r["rowid"], r["uuid"], r["text"]) for r in self.con.execute(
            "SELECT rowid, uuid, text, artist, title FROM radio_songs")
            if norm(r["artist"]) == norm(artist) and norm(r["title"]) == norm(title)]
        for rowid, _u, _t in found:
            self.con.execute("DELETE FROM radio_songs WHERE rowid=?", (rowid,))
        self.con.commit()
        s = self._song
        if s is not None and norm(s["artist"]) == norm(artist) and norm(s["title"]) == norm(title):
            self._song = None
        self.changed.emit()
        out = list(dict.fromkeys((u, t) for _r, u, t in found))
        if s is not None and self._station is not None and not found:
            out.append((station_key(self._station), s["text"]))
        return out

    def _playing(self) -> bool:
        p = self.player
        if p is None or p.station is None:
            return False
        if getattr(p, "_radio_stopped", False):
            return False
        try:
            return bool(p.is_playing())
        except Exception:
            return False

    def _tick(self):
        now = time.monotonic()
        dt = 0.0 if self._last is None else now - self._last
        self._last = now
        if dt <= 0 or dt > 5 or not self._playing():  # a long gap means sleep or a stall
            return
        self.add(dt)

    def add(self, seconds: float, at: float | None = None):
        """Add seconds of listening to the current station."""
        if self._station is None:
            return
        at = time.time() if at is None else at
        key = (int(at // 3600) * 3600, station_key(self._station))
        self._pending[key] = self._pending.get(key, 0.0) + seconds
        if self._song is not None:
            self._song["seconds"] += seconds
        self._unsaved += seconds
        if self._unsaved >= self.SAVE_EVERY:
            self.flush()

    def flush(self):
        """Write the pending counts."""
        wrote = False
        for (hour, uuid), s in self._pending.items():
            self.con.execute("INSERT INTO radio_time VALUES (?,?,?) ON CONFLICT(hour, uuid) "
                             "DO UPDATE SET seconds = seconds + excluded.seconds", (hour, uuid, s))
            wrote = True
        self._pending.clear()
        song = self._song
        if song is not None and self._station is not None and song["seconds"] > song["saved"]:
            if song["rowid"] is None:
                cur = self.con.execute("INSERT INTO radio_songs VALUES (?,?,?,?,?,?,?)",
                                       (song["at"], station_key(self._station), self._station.get("name") or "",
                                        song["artist"], song["title"], song["text"], song["seconds"]))
                song["rowid"] = cur.lastrowid
            else:
                self.con.execute("UPDATE radio_songs SET seconds=? WHERE rowid=?", (song["seconds"], song["rowid"]))
            song["saved"] = song["seconds"]
            wrote = True
        self._unsaved = 0.0
        if wrote:
            self.con.commit()
            self.changed.emit()

    def clear(self):
        self.flush()
        for table in ("radio_tunes", "radio_time", "radio_songs", "radio_stations"):
            self.con.execute(f"DELETE FROM {table}")
        self.con.commit()
        if self._song is not None:
            self._song["rowid"], self._song["saved"], self._song["seconds"] = None, 0.0, 0.0
        if self._station is not None:
            st = self._station
            self.con.execute("INSERT OR REPLACE INTO radio_stations VALUES (?,?,?,?,?,?,?)",
                             (station_key(st), st.get("name") or "", st.get("tags") or "", st.get("country") or "",
                              st.get("url") or "", st.get("codec") or "", int(st.get("bitrate") or 0)))
            self.con.commit()
        self.changed.emit()

    def stations(self) -> dict:
        return {r["uuid"]: dict(r) for r in self.con.execute("SELECT * FROM radio_stations")}

    def time_since(self, since: float) -> list[dict]:
        """[{hour, uuid, seconds}] including unsaved time."""
        rows = [dict(r) for r in self.con.execute("SELECT * FROM radio_time WHERE hour >= ?",
                                                  (int(since // 3600) * 3600,))]
        for (hour, uuid), s in self._pending.items():
            if hour >= int(since // 3600) * 3600:
                rows.append({"hour": hour, "uuid": uuid, "seconds": s})
        return rows

    def tunes_since(self, since: float) -> list[dict]:
        return [dict(r) for r in self.con.execute("SELECT * FROM radio_tunes WHERE at >= ? ORDER BY at", (since,))]

    def songs_since(self, since: float, min_seconds: float = SONG_MIN_SECONDS) -> list[dict]:
        rows = [dict(r) for r in self.con.execute(
            "SELECT * FROM radio_songs WHERE at >= ? ORDER BY at", (since,))]
        s = self._song
        if s is not None and s["rowid"] is None and s["at"] >= since and self._station is not None:
            rows.append({"at": s["at"], "uuid": station_key(self._station), "station": self._station.get("name") or "",
                         "artist": s["artist"], "title": s["title"], "text": s["text"], "seconds": s["seconds"]})
        elif s is not None and s["rowid"] is not None:
            for r in rows:
                if r.get("text") == s["text"] and abs(r["at"] - s["at"]) < 1:
                    r["seconds"] = s["seconds"]
        rows = [r for r in rows if (r["seconds"] or 0) >= min_seconds and r.get("title")]
        if self.is_break is not None and rows:
            # skip known adverts
            known = self.stations()
            def st_for(r):
                d = dict(known.get(r["uuid"]) or {})
                d.setdefault("uuid", r["uuid"])
                d["name"] = d.get("name") or r.get("station") or ""
                return d
            self._names_songs.clear()
            rows = [r for r in rows if not self._break(r.get("text") or "", st_for(r), self.names_songs(r["uuid"]))]
        return rows

    def first_logged(self) -> float | None:
        r = self.con.execute("SELECT MIN(at) FROM radio_tunes").fetchone()
        return r[0] if r and r[0] else None
