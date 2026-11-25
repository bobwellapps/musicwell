"""Turn radio adverts and jingles down, based on what the station sends as the title (off by default)."""
from __future__ import annotations

import json
import time

from PySide6.QtCore import QObject, QTimer, Signal

from musicwell import radio as R

LEVELS = [(0.0, "Silent"), (0.1, "10 %"), (0.25, "25 %"), (0.4, "40 %")]
LONGEST = [(2, "2 minutes"), (4, "4 minutes"), (8, "8 minutes"), (15, "15 minutes")]


class AdDimmer(QObject):
    dimmedChanged = Signal(bool, str)  # dimmed, title

    FADE_MS = 1200
    STEP_MS = 40

    def __init__(self, player, settings, parent=None):
        super().__init__(parent)
        self.player, self.settings = player, settings
        self.dimmed = False
        self.text = ""
        self._sends_songs = False
        self._since = 0.0
        self._target = 1.0
        self._fade = QTimer(self)
        self._fade.setInterval(self.STEP_MS)
        self._fade.timeout.connect(self._step)
        self._limit = QTimer(self, singleShot=True)
        self._limit.timeout.connect(self._too_long)
        self._held_off = ""  # break ran too long: stay up until the title changes
        player.radioText.connect(self.on_text)
        player.radioChanged.connect(self.on_station)

    def enabled(self) -> bool:
        return self.settings.value("radio_dim_ads", False, type=bool)

    def level(self) -> float:
        try:
            return float(self.settings.value("radio_dim_level", 0.25))
        except (TypeError, ValueError):
            return 0.25

    def longest_ms(self) -> int:
        try:
            return int(float(self.settings.value("radio_dim_longest", 4)) * 60_000)
        except (TypeError, ValueError):
            return 240_000

    def _marks(self, key: str) -> dict:
        try:
            d = json.loads(self.settings.value(key, "{}") or "{}")
            return d if isinstance(d, dict) else {}
        except (TypeError, ValueError):
            return {}

    def marked(self, st) -> list:
        return self._marks("radio_ad_titles").get(R.station_id(st), []) if st else []

    def not_ads(self, st) -> list:
        return self._marks("radio_not_ads").get(R.station_id(st), []) if st else []

    def _mark(self, key: str, st, text: str, on: bool):
        d = self._marks(key)
        k = R.station_id(st)
        lst = [x for x in d.get(k, []) if R._plain(x) != R._plain(text)]
        if on:
            lst = (lst + [text])[-50:]
        if lst:
            d[k] = lst
        else:
            d.pop(k, None)
        self.settings.setValue(key, json.dumps(d))

    def mark_advert(self, text: str | None = None):
        """The current title is an advert: turn it down now and next time."""
        st = self.player.station
        text = self.text if text is None else text
        if not st or not text:
            return
        self._mark("radio_not_ads", st, text, False)
        self._mark("radio_ad_titles", st, text, True)
        if self.enabled():
            self._held_off = ""
            self._dim(True)

    def mark_not_advert(self, text: str | None = None):
        """Not an advert: turn back up and remember."""
        st = self.player.station
        text = self.text if text is None else text
        if st and text:
            self._mark("radio_ad_titles", st, text, False)
            self._mark("radio_not_ads", st, text, True)
        self._held_off = text or "\0"
        self._dim(False)

    def on_station(self, st):
        self._sends_songs = False
        self._held_off = ""
        self.text = ""
        self._dim(False, fade=st is not None)

    def on_text(self, text: str):
        text = text or ""
        self.text = text
        st = self.player.station
        if text and " - " in text and not R.is_advert(text, st, True, self.marked(st)):
            self._sends_songs = True  # station sends "Artist - Title"
        if (text or "\0") != self._held_off:
            self._held_off = ""
        if not self.enabled() or self._held_off:
            self._dim(False)
            return
        own_not = {R._plain(x) for x in self.not_ads(st)}
        ad = R.is_advert(text, st, self._sends_songs, self.marked(st)) and R._plain(text) not in own_not
        if not text and not self._sends_songs:
            ad = False
        self._dim(ad)

    def settings_changed(self):
        if not self.enabled():
            self._dim(False)
        else:
            self.on_text(self.text)

    def _dim(self, on: bool, fade: bool = True):
        was = self.dimmed
        self.dimmed = on
        self._target = self.level() if on else 1.0
        if on and not was:
            self._since = time.monotonic()
            self._limit.start(self.longest_ms())
        elif not on:
            self._limit.stop()
        if fade:
            self._fade.start()
        else:
            self._fade.stop()
            self.player.set_duck(self._target)
        if on != was:
            self.dimmedChanged.emit(on, self.text)

    def _step(self):
        cur = getattr(self.player, "duck", 1.0)
        step = self.STEP_MS / self.FADE_MS
        nxt = max(self._target, cur - step) if cur > self._target else min(self._target, cur + step)
        self.player.set_duck(nxt)
        if abs(nxt - self._target) < 1e-4:
            self._fade.stop()

    def _too_long(self):
        """Silent longer than allowed, so probably not a break."""
        if self.dimmed:
            self._held_off = self.text or "\0"
            self._dim(False)
