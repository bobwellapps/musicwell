"""Song alerts: tell you when a favourite station plays something you'd like (off by default)."""
from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, QTimer, Signal

from musicwell import radio as R

EVERY = [(1, "minute"), (2, "2 minutes"), (5, "5 minutes"), (10, "10 minutes")]
PEEK_KB = 16  # KB downloaded per check
REPEAT_AFTER = 3600  # seconds before the same song on the same station is mentioned again


def norm(x: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (x or "").lower())


def artist_list(text: str) -> list[str]:
    return [a.strip() for a in re.split(r"[,;\n]", text or "") if a.strip()]


def data_per_hour(stations: int, minutes: float) -> float:
    """MB per hour for checking this many stations this often."""
    return stations * PEEK_KB * (60 / max(1.0, minutes)) / 1024


class SongAlerts(QObject):
    alert = Signal(dict, str, str, str)  # station, artist, title, why
    checked = Signal(str, object, int, str)  # station id, title (None if it never sends one), bytes, problem

    def __init__(self, stations, settings, player, library=None, parent=None):
        super().__init__(parent)
        self.stations, self.settings, self.player, self.library = stations, settings, player, library
        self.pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="musicwell-alerts")
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check)
        self._busy: set[str] = set()
        self._last: dict[str, str] = {}  # station id -> last title
        self._told: dict[tuple, float] = {}  # (station id, song) -> time we told you
        self.bytes = 0
        self.checks = 0
        self.checked.connect(self._on_checked)
        self.apply_settings()

    def enabled(self) -> bool:
        return self.settings.value("radio_alerts", False, type=bool)

    def every_min(self) -> float:
        try:
            return max(1.0, float(self.settings.value("radio_alert_every", 2)))
        except (TypeError, ValueError):
            return 2.0

    def chosen_ids(self) -> list[str]:
        try:
            v = json.loads(self.settings.value("radio_alert_stations", "[]") or "[]")
            return [str(x) for x in v] if isinstance(v, list) else []
        except (TypeError, ValueError):
            return []

    def watched_stations(self) -> list[dict]:
        favs = [st for st in self.stations.favourites() if st.get("url")]
        ids = self.chosen_ids()
        if self.settings.value("radio_alert_which", "all") == "chosen":
            favs = [st for st in favs if R.station_id(st) in ids]
        return favs

    def apply_settings(self):
        if self.enabled():
            ms = int(self.every_min() * 60_000)
            if not self.timer.isActive() or self.timer.interval() != ms:
                self.timer.start(ms)
                QTimer.singleShot(3000, self.check)
        else:
            self.timer.stop()

    def check(self):
        if not self.enabled():
            return
        if self.player.station is not None and self.settings.value("radio_alert_when", "always") == "not_radio":
            return  # no alerts while you listen to the radio
        playing = R.station_id(self.player.station) if self.player.station else ""
        self.checks += 1
        for st in self.watched_stations():
            k = R.station_id(st)
            if not k or k == playing or k in self._busy:
                continue
            self._busy.add(k)

            def work(k=k, st=dict(st)):
                try:
                    title, n = R.now_title(st)
                    self.checked.emit(k, title, n, "")
                except Exception as e:
                    self.checked.emit(k, "", 0, str(e) or type(e).__name__)
            self.pool.submit(work)

    def _on_checked(self, k: str, title, n: int, problem: str):
        self._busy.discard(k)
        self.bytes += n
        if problem or not title or not title.strip():
            return
        title = title.strip()
        if self._last.get(k) == title:
            return
        self._last[k] = title
        st = next((s for s in self.stations.favourites() if R.station_id(s) == k), None)
        if st is None or not self.enabled():
            return
        artist, song = R.song_parts(st, title)
        if not artist or not song:
            return
        why = self.reason(artist, song)
        if not why:
            return
        key = (k, norm(artist) + "|" + norm(song))
        now = time.time()
        if now - self._told.get(key, 0) < REPEAT_AFTER:
            return
        self._told[key] = now
        self.alert.emit(st, artist, song, why)

    def reason(self, artist: str, song: str) -> str:
        """Why you'd want to hear this, or ""."""
        s = self.settings
        a = norm(artist)
        liked = self.stations.liked()
        if s.value("radio_alert_liked", True, type=bool):
            if self.stations.is_liked(artist, song):
                return "a song you ♥ Liked"
        if s.value("radio_alert_liked_artists", True, type=bool):
            if a and any(norm(x.get("artist", "")) == a for x in liked):
                return "an artist you ♥ Liked a song by"
        mine = {norm(x) for x in artist_list(s.value("radio_alert_artists", "") or "")}
        if a and a in mine:
            return "an artist you're watching for"
        if s.value("radio_alert_library", False, type=bool) and self.library is not None:
            if a and a in self._library_artists():
                return "an artist in your library"
        return ""

    def _library_artists(self) -> set:
        lib = self.library
        cache = getattr(self, "_lib_cache", None)
        if cache is None or cache[0] != len(lib.tracks):
            names = set()
            for t in lib.tracks.values():
                for x in (t.get("artist"), t.get("albumartist")):
                    if x:
                        names.add(norm(x))
            cache = self._lib_cache = (len(lib.tracks), names)
        return cache[1]

    def shutdown(self):
        self.timer.stop()
        self.pool.shutdown(wait=False, cancel_futures=True)
