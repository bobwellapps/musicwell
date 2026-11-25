""""Up next" for radio stations whose server reports it (AzuraCast, SHOUTcast 2)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, QTimer, Signal

from musicwell import radio as R


class UpNext(QObject):
    nextChanged = Signal(str)  # "Artist – Title", or "" if unknown
    _got = Signal(int, object, str)  # generation, titles, problem

    POLL_MS = 45_000
    AFTER_CHANGE_MS = 4_000  # the server updates shortly after a song change
    GIVE_UP = 3

    def __init__(self, player, parent=None):
        super().__init__(parent)
        self.player = player
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="musicwell-upnext")
        self.src: dict | None = None
        self.text = ""
        self.titles: list[str] = []
        self._gen = 0
        self._fails = 0
        self._busy = False
        self.poll = QTimer(self)
        self.poll.setInterval(self.POLL_MS)
        self.poll.timeout.connect(self.fetch)
        self._soon = QTimer(self, singleShot=True)
        self._soon.timeout.connect(self.fetch)
        self._got.connect(self._on_got)
        player.radioChanged.connect(self.on_station)
        if hasattr(player, "streamInfo"):
            player.streamInfo.connect(self.on_info)
        player.radioText.connect(self.on_text)

    def on_station(self, st):
        self._gen += 1
        self._fails = 0
        self._busy = False
        self.titles = []
        self._set("")
        self.src = R.next_source(st["url"]) if st else None
        if self.src:
            self._start()
        else:
            self.poll.stop()
            self._soon.stop()

    def on_info(self, info: dict):
        st = self.player.station
        if st is None or self.src is not None:
            return
        self.src = R.next_source(info.get("url") or st["url"], info.get("server", "")) or \
            R.next_source(st["url"], info.get("server", ""))
        if self.src:
            self._start()

    def on_text(self, text: str):
        if not self.src:
            return
        # The song we called "next" has started.
        if self.titles and R._plain(self.titles[0]) == R._plain(text):
            self.titles = self.titles[1:]
            self._show()
        self._soon.start(self.AFTER_CHANGE_MS)

    def _start(self):
        self._soon.start(300)
        self.poll.start()

    def fetch(self):
        if not self.src or self._busy or self.player.station is None:
            return
        self._busy = True
        gen, src = self._gen, dict(self.src)

        def work():
            try:
                self._got.emit(gen, R.fetch_next(src), "")
            except Exception as e:
                self._got.emit(gen, [], str(e) or type(e).__name__)
        self.pool.submit(work)

    def _on_got(self, gen: int, titles, problem: str):
        if gen != self._gen:
            return
        self._busy = False
        if problem:
            self._fails += 1
            if self._fails >= self.GIVE_UP:  # this server doesn't report it
                self.src = None
                self.poll.stop()
                self._set("")
            return
        self._fails = 0
        cur = (self.player.current or {}).get("now_playing", "")
        self.titles = [t for t in titles if R._plain(t) != R._plain(cur)]
        self._show()

    def _show(self):
        if not self.titles:
            self._set("")
            return
        artist, title = R.song_parts(self.player.station, self.titles[0])
        self._set(f"{artist} – {title}" if artist else title)

    def _set(self, text: str):
        if text != self.text:
            self.text = text
            self.nextChanged.emit(text)

    def shutdown(self):
        self.poll.stop()
        self._soon.stop()
        self.pool.shutdown(wait=False, cancel_futures=True)
