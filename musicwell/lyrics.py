"""Lyrics: where they come from, and LRC parsing.

Order of preference for each song:
  1. a .lrc (or .txt) file next to the song with the same name     "song.flac" -> "song.lrc"
  2. lyrics stored inside the file (ID3 USLT/SYLT, Vorbis LYRICS, MP4 ©lyr, APE/WMA lyrics)
  3. LRCLIB (lrclib.net) — a free, open lyrics database; no account or key needed
Synced lyrics (with [mm:ss.xx] times) scroll with the song; plain lyrics are shown as text.
Lyrics found online are cached in ~/.cache/musicwell/lyrics and can also be saved as .lrc files.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Signal

from musicwell import __version__
from musicwell.paths import cache_dir

USER_AGENT = f"Musicwell{'/' + __version__ if __version__ else ''} (Linux desktop music player)"
LRCLIB = "https://lrclib.net"
BASE_OVERRIDES: dict[str, str] = {}  # for tests
MISS_DAYS = 7

_TIME = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")
_WORD_TIME = re.compile(r"<\d{1,3}:\d{1,2}(?:[.:]\d{1,3})?>")
_META = re.compile(r"^\[(ar|ti|al|au|by|length|re|ve|#|offset|tool|la|lang):?(.*)\]\s*$", re.I)


@dataclass
class Lyrics:
    lines: list = field(default_factory=list)  # [(time_ms or None, text)]
    synced: bool = False
    source: str = ""  # "file", "embedded", "LRCLIB"
    instrumental: bool = False

    @property
    def empty(self) -> bool:
        return not self.instrumental and not any(t.strip() for _, t in self.lines)

    def index_at(self, ms: int) -> int:
        """Index of the line at `ms` (-1 before the first)."""
        if not self.synced:
            return -1
        lo, hi, ans = 0, len(self.lines) - 1, -1
        while lo <= hi:
            mid = (lo + hi) // 2
            if self.lines[mid][0] <= ms:
                ans, lo = mid, mid + 1
            else:
                hi = mid - 1
        return ans

    def to_lrc(self) -> str:
        if not self.synced:
            return "\n".join(t for _, t in self.lines)
        out = []
        for ms, text in self.lines:
            m, s = divmod(ms / 1000.0, 60)
            out.append(f"[{int(m):02d}:{s:05.2f}]{text}")
        return "\n".join(out)


def parse(text: str, source: str = "") -> Lyrics:
    """Parse LRC (synced) or plain text."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    offset = 0
    timed, plain = [], []
    for raw in text.split("\n"):
        line = raw.strip()
        meta = _META.match(line)
        if meta:
            if meta.group(1).lower() == "offset":
                try:
                    offset = int(meta.group(2).strip())
                except ValueError:
                    pass
            continue
        stamps = list(_TIME.finditer(line))
        if stamps and stamps[0].start() == 0:
            body = _WORD_TIME.sub("", line[stamps[-1].end():]).strip()
            for st in stamps:
                mm, ss, frac = st.group(1), st.group(2), st.group(3) or "0"
                ms = (int(mm) * 60 + int(ss)) * 1000 + int(frac.ljust(3, "0")[:3])
                timed.append((ms, body))
        else:
            plain.append(_WORD_TIME.sub("", raw).rstrip())
    if timed:
        # [offset:+500] means lyrics 0.5 s earlier
        lines = sorted(((max(0, ms - offset), t) for ms, t in timed), key=lambda x: x[0])
        return Lyrics(lines, True, source)
    while plain and not plain[0].strip():
        plain.pop(0)
    while plain and not plain[-1].strip():
        plain.pop()
    return Lyrics([(None, t) for t in plain], False, source)


def sidecar(path: str) -> Lyrics | None:
    base = os.path.splitext(path)[0]
    for ext in (".lrc", ".LRC", ".txt"):
        p = base + ext
        if os.path.isfile(p):
            try:
                with open(p, encoding="utf-8", errors="replace") as fh:
                    ly = parse(fh.read(), "file")
                if not ly.empty:
                    return ly
            except OSError:
                pass
    return None


def embedded(path: str) -> Lyrics | None:
    try:
        import mutagen
        f = mutagen.File(path)
    except Exception:
        return None
    if f is None or f.tags is None:
        return None
    tags = f.tags
    try:
        if hasattr(tags, "getall"):  # ID3
            for fr in tags.getall("SYLT"):
                if fr.format == 2 and fr.text:  # times in ms
                    lines = sorted(((int(t), str(s).strip()) for s, t in fr.text), key=lambda x: x[0])
                    return Lyrics(lines, True, "embedded")
            for fr in tags.getall("USLT"):
                if fr.text and fr.text.strip():
                    return parse(fr.text, "embedded")
            return None
        name = type(f).__name__
        if name in ("MP4", "M4A"):
            v = tags.get("\xa9lyr")
            return parse(v[0], "embedded") if v else None
        if name == "ASF":
            v = tags.get("WM/Lyrics")
            return parse(str(v[0].value), "embedded") if v else None
        for key in ("SYNCEDLYRICS", "LYRICS", "UNSYNCEDLYRICS", "Lyrics"):
            for k in tags.keys():
                if k.upper() == key.upper():
                    v = tags[k]
                    v = v[0] if isinstance(v, list) else getattr(v, "value", v)
                    if str(v).strip():
                        return parse(str(v), "embedded")
    except Exception:
        return None
    return None


def _url(url: str) -> str:
    for base, repl in BASE_OVERRIDES.items():
        if url.startswith(base):
            return repl + url[len(base):]
    return url


def _get(url: str):
    req = urllib.request.Request(_url(url), headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def lrclib(artist: str, title: str, album: str = "", duration: float = 0) -> Lyrics | None:
    """Exact match by artist/title/album/length first, then a search."""
    def from_item(d) -> Lyrics | None:
        if not d:
            return None
        if d.get("instrumental"):
            return Lyrics([], False, "LRCLIB", instrumental=True)
        if d.get("syncedLyrics"):
            return parse(d["syncedLyrics"], "LRCLIB")
        if d.get("plainLyrics"):
            return parse(d["plainLyrics"], "LRCLIB")
        return None

    q = {"artist_name": artist, "track_name": title}
    if album:
        q["album_name"] = album
    if duration:
        q["duration"] = str(int(round(duration)))
    ly = from_item(_get(f"{LRCLIB}/api/get?{urllib.parse.urlencode(q)}"))
    if ly:
        return ly
    found = _get(f"{LRCLIB}/api/search?{urllib.parse.urlencode({'artist_name': artist, 'track_name': title})}") or []
    # prefer synced, and a length close to ours
    def score(d):
        dd = abs((d.get("duration") or 0) - duration) if duration else 0
        return (not d.get("syncedLyrics"), dd > 3, dd)
    for d in sorted(found, key=score):
        if duration and d.get("duration") and abs(d["duration"] - duration) > 8:
            continue
        ly = from_item(d)
        if ly:
            return ly
    return None


def _key(t: dict) -> str:
    return hashlib.sha1(f"{t.get('artist','')}|{t.get('title','')}|{t.get('album','')}".lower()
                        .encode()).hexdigest()[:20]


class LyricsStore(QObject):
    """Finds lyrics (file > embedded > LRCLIB) without blocking the UI."""
    ready = Signal(int, object)  # track id, Lyrics or None
    _done = Signal(int, object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.online = True
        self.save_lrc = False
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="musicwell-lyrics")
        self._mem: dict[int, Lyrics | None] = {}
        self._pending: set[int] = set()
        self._done.connect(self._on_done)

    def configure(self, settings):
        self.online = settings.value("lyrics_online", True, bool)
        self.save_lrc = settings.value("lyrics_save_lrc", False, bool)

    def _dir(self):
        d = cache_dir() / "lyrics"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def request(self, t: dict):
        """Look up lyrics; the answer comes through `ready`."""
        tid = t["id"]
        if tid in self._mem:
            self.ready.emit(tid, self._mem[tid])
            return
        if tid in self._pending:
            return
        self._pending.add(tid)
        track = dict(t)
        online, cache = self.online, self._dir()

        if track.get("stream"):
            track["album"] = ""  # the station name would spoil the lookup
            track["length"] = 0
        online_file = str(track.get("path", "")).startswith(("http://", "https://"))

        def work():
            ly = None if online_file else (sidecar(track["path"]) or embedded(track["path"]))
            fetched = False
            if ly is None:
                k = _key(track)
                lrc, inst, miss = cache / f"{k}.lrc", cache / f"{k}.instrumental", cache / f"{k}.miss"
                if lrc.exists():
                    ly = parse(lrc.read_text(encoding="utf-8", errors="replace"), "LRCLIB")
                elif inst.exists():
                    ly = Lyrics([], False, "LRCLIB", instrumental=True)
                elif online and track.get("title") and track.get("artist") and not (
                        miss.exists() and time.time() - miss.stat().st_mtime < MISS_DAYS * 86400):
                    try:
                        ly = lrclib(track["artist"], track["title"], track.get("album", ""),
                                    track.get("length") or 0)
                        fetched = True
                        if ly is None:
                            miss.touch()
                        elif ly.instrumental:
                            inst.touch()
                        else:
                            lrc.write_text(ly.to_lrc(), encoding="utf-8")
                    except Exception:
                        ly = None  # offline: try again next time
            self._done.emit(tid, ly, (track["path"], fetched))
        self.pool.submit(work)

    def _on_done(self, tid: int, ly, info):
        self._pending.discard(tid)
        self._mem[tid] = ly
        path, fetched = info
        if fetched and ly is not None and not ly.instrumental and self.save_lrc and os.path.isabs(path):
            target = os.path.splitext(path)[0] + (".lrc" if ly.synced else ".txt")
            if not os.path.exists(target):
                try:
                    with open(target, "w", encoding="utf-8") as fh:
                        fh.write(ly.to_lrc())
                except OSError:
                    pass
        self.ready.emit(tid, ly)

    def forget(self, t: dict):
        """Drop the cached result and search again."""
        self._mem.pop(t["id"], None)
        k = _key(t)
        for suffix in (".lrc", ".instrumental", ".miss"):
            (self._dir() / f"{k}{suffix}").unlink(missing_ok=True)

    def set_from_file(self, t: dict, file: str) -> Lyrics | None:
        with open(file, encoding="utf-8", errors="replace") as fh:
            ly = parse(fh.read(), "file")
        if ly.empty:
            return None
        (self._dir() / f"{_key(t)}.lrc").write_text(ly.to_lrc(), encoding="utf-8")
        self._mem[t["id"]] = ly
        self.ready.emit(t["id"], ly)
        return ly

    def cache_files(self) -> list:
        return [p for p in self._dir().iterdir() if p.is_file()]

    def clear_cache(self) -> int:
        n = 0
        for p in self.cache_files():
            p.unlink(missing_ok=True)
            n += 1
        self._mem.clear()
        return n

    def shutdown(self):
        self.pool.shutdown(wait=False, cancel_futures=True)
