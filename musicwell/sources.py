"""User sources on the Online Sources tab: podcast/RSS feeds, M3U/PLS playlists, audio links and web folders."""
from __future__ import annotations

import hashlib
import html
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from musicwell import ia
from musicwell.paths import cache_dir

KINDS = [("auto", "Detect automatically"), ("feed", "Podcast or RSS / Atom feed"),
         ("playlist", "Playlist (M3U, M3U8 or PLS)"), ("audio", "Link to one audio file"),
         ("folder", "Web folder (a page listing audio files)")]
KIND_NAMES = dict(KINDS)
SHORT = {"feed": "Feed", "playlist": "Playlist", "audio": "Audio link", "folder": "Web folder"}
AUDIO_EXT = (".mp3", ".ogg", ".oga", ".opus", ".flac", ".m4a", ".aac", ".wav", ".webm", ".mka", ".aiff", ".aif",
             ".wv", ".ape", ".mp2")
FMT = {".mp3": "MP3", ".ogg": "Ogg", ".oga": "Ogg", ".opus": "Opus", ".flac": "FLAC", ".m4a": "AAC", ".aac": "AAC",
       ".wav": "WAV", ".webm": "WebM", ".mka": "MKA", ".aiff": "AIFF", ".aif": "AIFF", ".wv": "WavPack",
       ".ape": "APE", ".mp2": "MP2"}
TIMEOUT = 15
MAX_BYTES = 16 * 1024 * 1024
MAX_SONGS = 5000
FOLDER_DEPTH = 3  # folder levels to follow
MAX_FOLDERS = 200


class SourceError(Exception):
    """An error the user can act on."""


def _fetch(url: str, limit: int = MAX_BYTES) -> tuple[bytes, str, str]:
    """(body, content type, final URL)"""
    req = urllib.request.Request(url, headers={"User-Agent": ia.USER_AGENT, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.read(limit), (r.headers.get("Content-Type") or "").lower(), r.geturl()
    except urllib.error.HTTPError as e:
        raise SourceError(f"the site answered “{e.code} {e.reason}”") from e
    except urllib.error.URLError as e:
        raise SourceError(f"couldn't reach it ({getattr(e, 'reason', e)})") from e
    except (TimeoutError, OSError) as e:
        raise SourceError(f"couldn't reach it ({type(e).__name__})") from e


def _ext(url: str) -> str:
    path = urllib.parse.urlsplit(url).path.lower()
    m = re.search(r"\.[a-z0-9]{2,5}$", path)
    return m.group(0) if m else ""


def is_audio_url(url: str) -> bool:
    return _ext(url) in AUDIO_EXT


def _text(body: bytes) -> str:
    for enc in ("utf-8", "latin-1"):
        try:
            return body.decode(enc)
        except UnicodeDecodeError:
            continue
    return body.decode("utf-8", "replace")


def detect(body: bytes, ctype: str, url: str) -> str:
    head = _text(body[:4096]).lstrip("﻿ \t\r\n").lower()
    if "audio/" in ctype and "mpegurl" not in ctype and "scpls" not in ctype:
        return "audio"
    if head.startswith("#extm3u") or "mpegurl" in ctype or _ext(url) in (".m3u", ".m3u8"):
        return "playlist"
    if head.startswith("[playlist]") or "scpls" in ctype or _ext(url) == ".pls":
        return "playlist"
    if "<rss" in head or "<feed" in head or ("xml" in ctype and "<channel" in head):
        return "feed"
    if "<html" in head or "<a " in head or "html" in ctype or "<!doctype" in head:
        return "folder"
    if head.startswith("http://") or head.startswith("https://"):
        return "playlist"  # a plain list of URLs
    raise SourceError("couldn't tell what kind of source this is — choose the type yourself")


def read(src: dict) -> tuple[list[dict], dict]:
    """Songs at a source (kind "src") and what we learned about it ({"kind", "title", "image", "page"})."""
    url = src["url"].strip()
    if not re.match(r"^https?://", url, re.I):
        raise SourceError("the address should start with http:// or https://")
    kind = src.get("kind") or "auto"
    if kind == "audio" or (kind == "auto" and is_audio_url(url)):
        return [_item(src, url, _title_from_url(url), "", "", 0, 1)], {"kind": "audio"}
    body, ctype, final = _fetch(url)
    if kind == "auto":
        kind = detect(body, ctype, final)
    if kind == "audio":
        return [_item(src, final, _title_from_url(final), "", "", 0, 1)], {"kind": "audio"}
    if kind == "feed":
        items, info = _read_feed(src, body, final)
    elif kind == "playlist":
        items, info = _read_playlist(src, _text(body), final)
    else:
        items, info = _read_folder(src, _text(body), final)
    info["kind"] = kind
    if not items:
        raise SourceError({"feed": "the feed has no audio in it",
                           "playlist": "the playlist has no songs in it",
                           "folder": "no audio files found on that page (or in the folders under it)"}.get(kind, "no songs found"))
    return items[:MAX_SONGS], info


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower() if isinstance(tag, str) else ""


def _child(el, name: str):
    for c in el:
        if _local(c.tag) == name:
            return c
    return None


def _child_text(el, *names: str) -> str:
    for name in names:
        c = _child(el, name)
        if c is not None and (c.text or "").strip():
            return html.unescape(c.text.strip())
    return ""


def _duration(v: str) -> float:
    v = (v or "").strip()
    if not v:
        return 0
    try:
        if ":" in v:
            secs = 0.0
            for part in v.split(":"):
                secs = secs * 60 + float(part)
            return secs
        return float(v)
    except ValueError:
        return 0


def _year(date: str) -> int:
    m = re.search(r"\b(19|20)\d\d\b", date or "")
    return int(m.group(0)) if m else 0


def _image_of(el) -> str:
    for c in el:
        name = _local(c.tag)
        if name == "image":
            if c.get("href"):
                return c.get("href")
            u = _child_text(c, "url")
            if u:
                return u
        if name == "thumbnail" and c.get("url"):
            return c.get("url")
    return ""


def _read_feed(src, body: bytes, base: str):
    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        raise SourceError(f"the feed can't be read ({e})") from e
    channel = _child(root, "channel") if _local(root.tag) == "rss" else root
    if channel is None:
        raise SourceError("that isn't a feed Musicwell understands")
    title = _child_text(channel, "title")
    author = _child_text(channel, "author", "creator", "managingeditor") or title
    image = _image_of(channel)
    link = ""
    for c in channel:
        if _local(c.tag) == "link":
            link = (c.text or "").strip() or c.get("href", "")
            if link:
                break
    entries = [c for c in channel if _local(c.tag) in ("item", "entry")]
    items = []
    n = 0
    for e in entries:
        audio = ""
        for c in e:
            name = _local(c.tag)
            if name == "enclosure" and (c.get("url") and ("audio" in (c.get("type") or "") or is_audio_url(c.get("url")))):
                audio = c.get("url")
            elif name == "link" and c.get("rel") == "enclosure" and c.get("href"):
                audio = c.get("href")
            elif name == "content" and c.get("url") and ("audio" in (c.get("type") or "") or is_audio_url(c.get("url"))):
                audio = audio or c.get("url")
            if audio:
                break
        if not audio:
            continue
        n += 1
        audio = urllib.parse.urljoin(base, audio)
        it = _item(src, audio, _child_text(e, "title") or _title_from_url(audio),
                   _child_text(e, "author", "creator") or author, title or src["name"],
                   _duration(_child_text(e, "duration")), n,
                   year=_year(_child_text(e, "pubdate", "published", "updated", "date")),
                   image=_image_of(e) or image, page=_child_text(e, "link") or link)
        items.append(it)
    return items, {"title": title, "image": image, "page": link}


_EXTINF = re.compile(r"#EXTINF:\s*(-?[\d.]+)[^,]*,(.*)$", re.I)


def _read_playlist(src, text: str, base: str):
    items = []
    if text.lstrip("﻿ \r\n").lower().startswith("[playlist]"):
        entries: dict[int, dict] = {}
        for line in text.splitlines():
            m = re.match(r"\s*(file|title|length)(\d+)\s*=\s*(.*)$", line, re.I)
            if m:
                entries.setdefault(int(m.group(2)), {})[m.group(1).lower()] = m.group(3).strip()
        rows = [(e.get("file", ""), e.get("title", ""), _duration(e.get("length", ""))) for _, e in sorted(entries.items())]
    else:
        if "#EXT-X-" in text:
            raise SourceError("this is a live stream (HLS), not a playlist of songs — add it on the Radio page "
                              "instead (Radio → Add a station)")
        rows, extinf = [], None
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            m = _EXTINF.match(line)
            if m:
                extinf = (m.group(2).strip(), _duration(m.group(1)))
                continue
            if line.startswith("#"):
                continue
            title, length = extinf or ("", 0)
            rows.append((line, title, max(0, length)))
            extinf = None
    n = 0
    for file, title, length in rows:
        if not file:
            continue
        url = urllib.parse.urljoin(base, file)
        if not re.match(r"^https?://", url, re.I):
            continue  # a file:// URL on another computer
        artist, name = "", title
        if " - " in title:
            artist, name = title.split(" - ", 1)
        n += 1
        items.append(_item(src, url, name.strip() or _title_from_url(url), artist.strip(), src["name"], length, n))
    return items, {}


_HREF = re.compile(r"""<a\s[^>]*?href\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", re.I)


def _read_folder(src, text: str, base: str):
    """Audio files linked from the page and the folders below it (same site only)."""
    root = base if base.endswith("/") else base.rsplit("/", 1)[0] + "/"
    seen_dirs, seen_files = {base}, set()
    items: list[dict] = []
    queue = [(base, text, 0)]
    while queue:
        url, page, depth = queue.pop(0)
        subdirs = []
        for m in _HREF.finditer(page):
            href = html.unescape(m.group(1) or m.group(2) or m.group(3) or "")
            if not href or href.startswith(("#", "?", "mailto:", "javascript:")):
                continue
            full = urllib.parse.urljoin(url, href).split("#")[0]
            if not full.startswith(root):
                continue
            if is_audio_url(full):
                if full not in seen_files:
                    seen_files.add(full)
                    items.append(_folder_item(src, full, root, len(items) + 1))
            elif full.endswith("/") and "?" not in full and full not in seen_dirs and depth < FOLDER_DEPTH:
                seen_dirs.add(full)
                subdirs.append(full)
        for d in subdirs:
            if len(seen_dirs) > MAX_FOLDERS or len(items) >= MAX_SONGS:
                break
            try:
                body, ctype, final = _fetch(d)
            except SourceError:
                continue
            if "html" in ctype or b"<a " in body[:200000].lower():
                queue.append((final, _text(body), depth + 1))
    # number songs within each folder, by name
    items.sort(key=lambda it: (it["album_path"], it["audio_url"].lower()))
    counts: dict[str, int] = {}
    for it in items:
        counts[it["album_path"]] = counts.get(it["album_path"], 0) + 1
        it["number"] = it.get("number") or counts[it["album_path"]]
    return items, {}


def _folder_item(src, url: str, root: str, n: int) -> dict:
    rel = urllib.parse.unquote(url[len(root):])
    parts = [p for p in rel.split("/") if p]
    folders = parts[:-1]
    artist = folders[-2] if len(folders) >= 2 else ""
    if folders:
        album = folders[-1]
    else:
        top = [p for p in urllib.parse.unquote(urllib.parse.urlsplit(root).path).split("/") if p]
        album = top[-1] if top else src["name"]
    title, number = _clean_name(parts[-1])
    if " - " in title and not artist:
        a, t = title.split(" - ", 1)
        if a.strip() and t.strip():
            artist, title = a.strip(), t.strip()
    it = _item(src, url, title, artist, album, 0, number)
    it["album_path"] = "/".join(folders)
    return it


def _clean_name(filename: str) -> tuple[str, int]:
    name = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", filename).replace("_", " ").strip()
    m = re.match(r"^(?:(\d{1,2})[-.](\d{1,3})|(\d{1,3}))\s*(?:[-.)]\s*|\s+)(.+)$", name)
    if m and m.group(4):
        number = int(m.group(2) or m.group(3))
        return m.group(4).strip(), number
    return name, 0


def _title_from_url(url: str) -> str:
    name = urllib.parse.unquote(urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1]) or url
    return _clean_name(name)[0] or name


def _item(src, audio_url: str, title: str, artist: str, album: str, length: float, number: int,
          year: int = 0, image: str = "", page: str = "") -> dict:
    ident = "src:" + hashlib.sha1(audio_url.encode("utf-8", "replace")).hexdigest()[:16]
    return {"kind": "src", "badge": src["name"], "identifier": ident, "title": title or "Untitled",
            "creator": artist, "album": album or src["name"], "collection": src["name"], "audio_url": audio_url,
            "length": length or 0, "filetype": FMT.get(_ext(audio_url), "MP3"), "year": year, "number": number,
            "image": image or src.get("image", ""), "page": page or src.get("page") or src["url"],
            "license": src.get("note", ""), "source_id": src["id"]}


def to_track(it: dict, number: int = 0) -> dict:
    """A playable online track."""
    return ia.remote_track(url=it["audio_url"], title=it["title"], artist=it.get("creator") or "",
                           album=it.get("album") or it.get("collection", ""), number=number or it.get("number") or 0,
                           length=it.get("length") or 0, fmt=it.get("filetype") or "MP3", year=it.get("year") or 0,
                           item=it)


def describe(it: dict) -> str:
    from musicwell.models import fmt_time
    bits = [it.get("creator") or "", it.get("album") if it.get("album") != it.get("collection") else "",
            it.get("collection", ""), fmt_time(it["length"]) if it.get("length") else ""]
    return "  ·  ".join(b for b in bits if b)


class Sources:
    """Saved sources (in settings) and their songs (in the cache folder)."""

    def __init__(self, settings):
        self.settings = settings
        self._songs: dict[str, list[dict]] = {}
        self._info: dict[str, dict] = {}
        self._lock = threading.Lock()

    def all(self) -> list[dict]:
        try:
            lst = json.loads(self.settings.value("my_sources", "[]") or "[]")
        except (TypeError, ValueError):
            lst = []
        return [s for s in lst if isinstance(s, dict) and s.get("id") and s.get("url")]

    def save(self, lst: list[dict]):
        self.settings.setValue("my_sources", json.dumps(lst))

    def get(self, sid: str) -> dict | None:
        return next((s for s in self.all() if s["id"] == sid), None)

    def add(self, src: dict) -> dict:
        lst = self.all()
        n = 1
        while any(s["id"] == f"s{n}" for s in lst):
            n += 1
        src = dict(src, id=f"s{n}", on=src.get("on", True))
        lst.append(src)
        self.save(lst)
        return src

    def update(self, sid: str, **changes):
        lst = self.all()
        for s in lst:
            if s["id"] == sid:
                url_changed = "url" in changes and changes["url"] != s.get("url") or \
                    "kind" in changes and changes["kind"] != s.get("kind")
                s.update(changes)
                if url_changed:
                    self.forget(sid)
        self.save(lst)

    def remove(self, sid: str):
        self.save([s for s in self.all() if s["id"] != sid])
        self.forget(sid)

    def move(self, sid: str, delta: int):
        lst = self.all()
        i = next((k for k, s in enumerate(lst) if s["id"] == sid), -1)
        j = i + delta
        if i >= 0 and 0 <= j < len(lst):
            lst[i], lst[j] = lst[j], lst[i]
            self.save(lst)

    @staticmethod
    def _file(sid: str) -> Path:
        return cache_dir() / "sources" / f"{sid}.json"

    def forget(self, sid: str):
        with self._lock:
            self._songs.pop(sid, None)
            self._info.pop(sid, None)
        try:
            self._file(sid).unlink(missing_ok=True)
        except OSError:
            pass

    def songs(self, sid: str) -> list[dict] | None:
        """Songs from the last read, or None."""
        with self._lock:
            if sid in self._songs:
                return self._songs[sid]
        try:
            d = json.loads(self._file(sid).read_text("utf-8"))
        except (OSError, ValueError):
            return None
        with self._lock:
            self._songs[sid] = d.get("items") or []
            self._info[sid] = d.get("info") or {}
            self._info[sid]["fetched"] = d.get("fetched", 0)
        return self._songs[sid]

    def info(self, sid: str) -> dict:
        self.songs(sid)
        with self._lock:
            return dict(self._info.get(sid) or {})

    def refresh(self, src: dict) -> list[dict]:
        """Read the source again. Slow: run in a worker thread. Raises SourceError."""
        src = dict(src)
        items, info = read(src)
        # a feed's image and page fill in for songs without one
        for it in items:
            it.setdefault("image", "")
            if not it["image"] and info.get("image"):
                it["image"] = info["image"]
        info["fetched"] = time.time()
        info["count"] = len(items)
        f = self._file(src["id"])
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps({"fetched": info["fetched"], "info": info, "items": items}), "utf-8")
        except OSError:
            pass
        with self._lock:
            self._songs[src["id"]] = items
            self._info[src["id"]] = info
        return items

    def search(self, text: str, limit: int = 200) -> list[dict]:
        """Songs from enabled sources matching every word."""
        words = [w for w in text.lower().split() if w]
        if not words:
            return []
        out = []
        for s in self.all():
            if not s.get("on", True):
                continue
            for it in self.songs(s["id"]) or []:
                hay = " ".join((it.get("title", ""), it.get("creator", ""), it.get("album", ""),
                                it.get("collection", ""))).lower()
                if all(w in hay for w in words):
                    out.append(it)
                    if len(out) >= limit:
                        return out
        return out

    def stale(self, sid: str, max_age: float = 86400) -> bool:
        return time.time() - self.info(sid).get("fetched", 0) > max_age
