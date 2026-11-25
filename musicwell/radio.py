"""Internet radio: the station directory, your favourite stations, and a small relay that reads
the "now playing" titles stations send along with the music.

Stations come from radio-browser.info — a free, open, community-run directory of internet
radio stations (no account or key). Musicwell plays the station's own stream; nothing is
recorded or saved.

The relay: most stations (Icecast / SHOUTcast) slip the current song's name into the audio
stream every few seconds if asked to ("ICY metadata"). Musicwell's player can't read those,
so the stream goes through a tiny server on this computer (127.0.0.1 only) that takes the
titles out and passes the plain audio on. HLS stations (.m3u8) are played directly.
"""
from __future__ import annotations

import hashlib
import itertools
import logging
import json
import random
import re
import socket
import ssl
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PySide6.QtCore import QObject, Signal

from musicwell import __version__

USER_AGENT = f"Musicwell{'/' + __version__ if __version__ else ''} (Linux desktop music player)"
TIMEOUT = 10

# radio-browser.info runs several mirrors; fetch the list and pick one
SERVER_LIST_URL = "https://all.api.radio-browser.info/json/servers"
FALLBACK_SERVERS = ["de1.api.radio-browser.info", "de2.api.radio-browser.info", "fi1.api.radio-browser.info",
                    "nl1.api.radio-browser.info", "at1.api.radio-browser.info"]
BASE_OVERRIDE = ""  # for tests


class Directory:
    """radio-browser.info client, used from a background thread. Calls may raise on network errors."""

    def __init__(self):
        self._servers: list[str] = []
        self._lock = threading.Lock()

    def _get_servers(self) -> list[str]:
        with self._lock:
            if self._servers:
                return self._servers
            names = []
            try:
                data = _get_json(SERVER_LIST_URL)
                names = sorted({d.get("name", "") for d in data if d.get("name")})
            except Exception:
                pass
            names = names or list(FALLBACK_SERVERS)
            random.shuffle(names)  # spread the load, as the directory asks
            self._servers = names
            return names

    def get(self, path: str, params: dict | None = None):
        query = ("?" + urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v not in (None, "")})
                 if params else "")
        if BASE_OVERRIDE:
            return _get_json(BASE_OVERRIDE + path + query)
        last = None
        servers = self._get_servers()
        for host in list(servers):
            try:
                return _get_json(f"https://{host}{path}{query}")
            except Exception as e:  # server down: try the next
                last = e
                with self._lock:
                    if host in self._servers and len(self._servers) > 1:
                        self._servers.remove(host)
                        self._servers.append(host)
        raise last or OSError("no radio directory server answered")

    def search(self, name: str = "", tag: str = "", countrycode: str = "", language: str = "",
               order: str = "clickcount", limit: int = 80, offset: int = 0) -> list[dict]:
        params = {"name": name.strip(), "tag": tag.strip(), "countrycode": countrycode, "language": language,
                  "order": order, "reverse": "true", "hidebroken": "true", "limit": limit, "offset": offset}
        return [s for s in (station_from(d) for d in self.get("/json/stations/search", params)) if s]

    def popular(self, limit: int = 80) -> list[dict]:
        return self.search(order="clickcount", limit=limit)

    def tags(self, limit: int = 80) -> list[tuple[str, int]]:
        data = self.get("/json/tags", {"order": "stationcount", "reverse": "true", "hidebroken": "true",
                                       "limit": limit})
        return [(d["name"], int(d.get("stationcount", 0))) for d in data if d.get("name")]

    def countries(self) -> list[tuple[str, str, int]]:
        """(code, name, station count), most stations first."""
        data = self.get("/json/countries", {"order": "stationcount", "reverse": "true", "hidebroken": "true"})
        out = []
        for d in data:
            code = d.get("iso_3166_1") or d.get("countrycode") or ""
            if code and d.get("name"):
                out.append((code, short_country(d["name"]), int(d.get("stationcount", 0))))
        return out

    def count_click(self, uuid: str):
        """Report a play so the directory knows what's popular."""
        if uuid and not uuid.startswith("custom:"):
            try:
                self.get(f"/json/url/{urllib.parse.quote(uuid)}")
            except Exception:
                pass


def _get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read(8 * 1024 * 1024).decode("utf-8", "replace"))


def station_from(d: dict) -> dict | None:
    """A directory entry trimmed to what we keep."""
    url = (d.get("url_resolved") or d.get("url") or "").strip()
    if not url or not d.get("name", "").strip():
        return None
    return {
        "uuid": d.get("stationuuid", "") or "custom:" + hashlib.sha1(url.encode()).hexdigest()[:16],
        "name": re.sub(r"\s+", " ", d["name"]).strip(),
        "url": url,
        "homepage": d.get("homepage", "") or "",
        "favicon": d.get("favicon", "") or "",
        "tags": ", ".join(t.strip() for t in (d.get("tags") or "").split(",") if t.strip())[:200],
        "country": short_country(d.get("country", "") or ""),
        "countrycode": d.get("countrycode", "") or "",
        "language": d.get("language", "") or "",
        "codec": (d.get("codec") or "").upper(),
        "bitrate": int(d.get("bitrate") or 0),
        "hls": bool(int(d.get("hls") or 0)) or url.lower().split("?")[0].endswith(".m3u8"),
        "votes": int(d.get("votes") or 0),
    }


_COUNTRIES = {
    "the united kingdom of great britain and northern ireland": "United Kingdom",
    "the united states of america": "United States", "the russian federation": "Russia",
    "the netherlands": "Netherlands", "republic of korea": "South Korea", "korea, republic of": "South Korea",
    "the islamic republic of iran": "Iran", "iran (islamic republic of)": "Iran", "viet nam": "Vietnam",
    "the plurinational state of bolivia": "Bolivia", "the bolivarian republic of venezuela": "Venezuela",
    "taiwan, republic of china": "Taiwan", "the czech republic": "Czechia", "türkiye": "Turkey",
}


def short_country(name: str) -> str:
    """'The United Kingdom Of Great Britain And Northern Ireland' -> 'United Kingdom'"""
    n = re.sub(r"\s+", " ", name or "").strip()
    if n.lower() in _COUNTRIES:
        return _COUNTRIES[n.lower()]
    return n[4:] if n.lower().startswith("the ") and len(n) > 12 else n


def custom_station(name: str, url: str) -> dict:
    url = url.strip()
    return {"uuid": "custom:" + hashlib.sha1(url.encode()).hexdigest()[:16], "name": name.strip() or url,
            "url": url, "homepage": "", "favicon": "", "tags": "", "country": "", "countrycode": "",
            "language": "", "codec": "", "bitrate": 0, "hls": url.lower().split("?")[0].endswith(".m3u8"),
            "votes": 0}


def describe(st: dict) -> str:
    """e.g. 'UK · pop, chart · MP3 128 kbps'"""
    bits = []
    if st.get("country"):
        bits.append(short_country(st["country"]))
    if st.get("tags"):
        bits.append(", ".join(st["tags"].split(", ")[:4]))
    q = " ".join(x for x in (st.get("codec", ""), f"{st['bitrate']} kbps" if st.get("bitrate") else "") if x)
    if q:
        bits.append(q)
    return "  ·  ".join(bits)


class Stations:
    """Favourites (in your order) and recently played, stored in settings."""
    MAX_RECENT = 30

    def __init__(self, settings):
        self.s = settings

    def _load(self, key: str) -> list[dict]:
        try:
            d = json.loads(self.s.value(key, "[]"))
            return [x for x in d if isinstance(x, dict) and x.get("url")]
        except (TypeError, ValueError):
            return []

    def _save(self, key: str, lst: list[dict]):
        self.s.setValue(key, json.dumps(lst))

    # which way round each station sends artist and title
    def load_title_orders(self):
        try:
            d = json.loads(self.s.value("radio_title_order", "{}") or "{}")
        except (TypeError, ValueError):
            d = {}
        TITLE_ORDER.clear()
        TITLE_ORDER.update({k: v for k, v in (d.items() if isinstance(d, dict) else [])
                            if v in ("artist-title", "title-artist")})

    def set_title_order(self, st: dict, order: str):
        uuid = st.get("uuid", "")
        if not uuid:
            return
        if order in ("artist-title", "title-artist"):
            TITLE_ORDER[uuid] = order
        else:
            TITLE_ORDER.pop(uuid, None)
        self.s.setValue("radio_title_order", json.dumps(TITLE_ORDER))

    def favourites(self) -> list[dict]:
        return self._load("radio_favourites")

    def is_favourite(self, st: dict) -> bool:
        return any(x["uuid"] == st.get("uuid") for x in self.favourites())

    def set_favourite(self, st: dict, on: bool):
        favs = [x for x in self.favourites() if x["uuid"] != st["uuid"]]
        if on:
            favs.append(st)
        self._save("radio_favourites", favs)

    def save_favourites(self, favs: list[dict]):
        self._save("radio_favourites", favs)

    def update_station(self, st: dict):
        """Update an edited station in favourites and recents."""
        for key in ("radio_favourites", "radio_recent"):
            lst = self._load(key)
            if any(x["uuid"] == st["uuid"] for x in lst):
                self._save(key, [dict(st) if x["uuid"] == st["uuid"] else x for x in lst])

    def recent(self) -> list[dict]:
        return self._load("radio_recent")

    def played(self, st: dict):
        rec = [st] + [x for x in self.recent() if x["uuid"] != st["uuid"]]
        self._save("radio_recent", rec[:self.MAX_RECENT])

    def clear_recent(self):
        self._save("radio_recent", [])

    def export(self, path: str):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("#EXTM3U\n")
            for st in self.favourites():
                fh.write(f"#EXTINF:-1,{st['name']}\n{st['url']}\n")

    MAX_LIKED = 2000

    @staticmethod
    def liked_key(artist: str, title: str) -> str:
        n = lambda x: re.sub(r"[^a-z0-9]+", "", (x or "").lower())
        return n(artist) + "|" + n(title)

    def liked(self) -> list[dict]:
        """Newest first: {"artist", "title", "station", "station_uuid", "time", "key"}."""
        return self._load_list("radio_liked")

    def _load_list(self, key: str) -> list[dict]:
        try:
            d = json.loads(self.s.value(key, "[]"))
            return [x for x in d if isinstance(x, dict) and x.get("title")]
        except (TypeError, ValueError):
            return []

    def is_liked(self, artist: str, title: str) -> bool:
        k = self.liked_key(artist, title)
        return any(x.get("key") == k for x in self.liked())

    def like(self, artist: str, title: str, st: dict | None) -> bool:
        """Add a liked song at the top. False if it was already there (it moves to the top)."""
        k = self.liked_key(artist, title)
        old = self.liked()
        was = any(x.get("key") == k for x in old)
        entry = {"artist": artist, "title": title, "station": (st or {}).get("name", ""),
                 "station_uuid": (st or {}).get("uuid", ""), "time": time.time(), "key": k}
        self._save("radio_liked", ([entry] + [x for x in old if x.get("key") != k])[:self.MAX_LIKED])
        return not was

    def unlike(self, key: str):
        self._save("radio_liked", [x for x in self.liked() if x.get("key") != key])

    def clear_liked(self):
        self._save("radio_liked", [])

    def export_liked(self, path: str):
        import csv
        with open(path, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["Artist", "Title", "Station", "Heard"])
            for x in self.liked():
                w.writerow([x.get("artist", ""), x["title"], x.get("station", ""),
                            time.strftime("%Y-%m-%d %H:%M", time.localtime(x.get("time", 0)))])

    @staticmethod
    def read_playlist_file(path: str) -> list[dict]:
        """Stations from an .m3u / .pls file."""
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read(2 * 1024 * 1024)
        return [custom_station(n, u) for n, u in parse_playlist(text)]


def split_title(text: str) -> tuple[str, str]:
    """'Artist - Title' -> (artist, title)."""
    text = re.sub(r"\s+", " ", (text or "")).strip().strip("-").strip()
    for sep in (" - ", " – ", " — ", " | "):
        if sep in text:
            a, t = text.split(sep, 1)
            if a.strip() and t.strip():
                return a.strip(), t.strip()
    return "", text


# some stations send "Title - Artist"
TITLE_ORDERS = {"auto": "Automatic", "artist-title": "Artist – Title", "title-artist": "Title – Artist"}
TITLE_ORDER: dict[str, str] = {}  # station uuid -> "artist-title" | "title-artist"
KNOWN_ARTISTS: set[str] = set()  # library artists, lower case, for the automatic guess


def title_order(st: dict | None) -> str:
    return TITLE_ORDER.get((st or {}).get("uuid", ""), "auto")


def _without_station(st: dict | None, text: str) -> tuple[str, bool]:
    """Drop the station's own name from a title ("Artist - The SID Station - Tune")."""
    name = re.sub(r"[^a-z0-9]+", "", ((st or {}).get("name") or "").lower())
    if not name or not text:
        return text or "", False
    parts = [x for x in re.split(r"\s+[-–—|](?:\s+|$)", text.strip()) if x.strip()]
    if len(parts) < 2:
        return text, False
    plain = [re.sub(r"[^a-z0-9]+", "", x.lower()) for x in parts]
    keep = [x for x, q in zip(parts, plain) if q != name]
    if not keep or len(keep) == len(parts):
        return text, False
    only_artist = len(keep) == 1 and plain[0] != name  # "Artist - Station": no song name
    return " - ".join(keep), only_artist


def song_parts(st: dict | None, text: str) -> tuple[str, str]:
    """(artist, title) using the station's order. Automatic assumes "Artist - Title" unless the second part is a known artist."""
    text, only_artist = _without_station(st, text)
    if only_artist:
        return text.strip(), ""
    a, t = split_title(text)
    if not a:
        return a, t
    order = title_order(st)
    if order == "title-artist":
        return t, a
    if order == "artist-title":
        return a, t
    if KNOWN_ARTISTS and t.lower() in KNOWN_ARTISTS and a.lower() not in KNOWN_ARTISTS:
        return t, a
    return a, t


_ids = [0]


def stream_track(st: dict, now_playing: str = "") -> dict:
    """A track-like dict for a station so the panel, bar, lyrics and artist photo work as usual."""
    artist, title = song_parts(st, now_playing)
    _ids[0] -= 1
    return {
        "id": _ids[0], "stream": True, "station": st, "now_playing": now_playing or "",
        "path": st["url"], "title": title or st["name"], "artist": artist, "artist_key": artist,
        "album": st["name"], "albumartist": "", "genre": st.get("tags", "").split(", ")[0] if st.get("tags") else "",
        "composer": "", "year": 0, "track": 0, "disc": 0, "length": 0, "bitrate": (st.get("bitrate") or 0) * 1000,
        "samplerate": 0, "bitdepth": 0, "channels": 2, "format": st.get("codec") or "Stream",
        "rating": 0, "playcount": 0, "skipcount": 0, "lastplayed": 0, "added": 0, "mtime": 0, "filesize": 0,
        "decade": 0, "folder": "", "_extra": {}, "_text": "", "grouping": "", "comment": "", "label": "",
        "mood": "", "song_start": None,
    }


PLAYLIST_TYPES = ("audio/x-scpls", "audio/scpls", "audio/x-mpegurl", "audio/mpegurl", "application/pls+xml",
                  "video/x-ms-asf", "audio/x-ms-wax", "text/html")
HLS_TYPES = ("application/vnd.apple.mpegurl", "application/x-mpegurl")


def parse_playlist(text: str) -> list[tuple[str, str]]:
    """(name, url) entries from .pls, .m3u or .asx text."""
    out, name = [], ""
    files, titles = {}, {}
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r"(?i)file(\d+)\s*=\s*(\S+)", line)
        if m:
            files[m.group(1)] = m.group(2)
            continue
        m = re.match(r"(?i)title(\d+)\s*=\s*(.+)", line)
        if m:
            titles[m.group(1)] = m.group(2).strip()
            continue
        if line.upper().startswith("#EXTINF"):
            name = line.split(",", 1)[1].strip() if "," in line else ""
            continue
        if re.match(r"(?i)^https?://", line):
            out.append((name, line))
            name = ""
    for k in sorted(files, key=lambda x: int(x)):
        out.append((titles.get(k, ""), files[k]))
    for href in re.findall(r'(?i)<ref\s+href\s*=\s*"(https?://[^"]+)"', text):
        out.append(("", href))
    return [(n, u) for n, u in out if u.lower().startswith(("http://", "https://"))]


class _Upstream:
    """Raw HTTP(S) connection to a station, by hand because many servers still answer 'ICY 200 OK'."""

    def __init__(self, url: str, redirects: int = 5):
        self.url = url
        for _ in range(redirects + 1):
            self._open(self.url)
            if self.status in (301, 302, 303, 307, 308) and self.headers.get("location"):
                self.close()
                self.url = urllib.parse.urljoin(self.url, self.headers["location"])
                continue
            break
        if self.status != 200:
            self.close()
            raise OSError(f"the station answered {self.status}")

    def _open(self, url: str):
        u = urllib.parse.urlsplit(url)
        if u.scheme not in ("http", "https"):
            raise OSError("not a web address")
        host = u.hostname or ""
        port = u.port or (443 if u.scheme == "https" else 80)
        sock = socket.create_connection((host, port), timeout=TIMEOUT)
        if u.scheme == "https":
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
        path = (u.path or "/") + (("?" + u.query) if u.query else "")
        hosthdr = host if u.port is None else f"{host}:{u.port}"
        req = (f"GET {path} HTTP/1.0\r\nHost: {hosthdr}\r\nUser-Agent: {USER_AGENT}\r\n"
               "Icy-MetaData: 1\r\nAccept: */*\r\nConnection: close\r\n\r\n")
        sock.sendall(req.encode("latin-1", "replace"))
        self.sock = sock
        self.f = sock.makefile("rb")
        status = self.f.readline(4096).decode("latin-1", "replace").split()
        if len(status) < 2 or not status[0].upper().startswith(("HTTP/", "ICY")):
            raise OSError("not an audio stream")
        self.status = int(status[1]) if status[1].isdigit() else 0
        self.headers = {}
        while True:
            line = self.f.readline(8192).decode("latin-1", "replace").strip()
            if not line:
                break
            if ":" in line:
                k, v = line.split(":", 1)
                self.headers[k.strip().lower()] = v.strip()
        sock.settimeout(30)
        self.sock = sock

    def quick(self, seconds: float = 8.0):
        """Short timeout while relaying: a silent station has stalled."""
        try:
            self.sock.settimeout(seconds)
        except Exception:
            pass

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "").split(";")[0].strip().lower()

    def read(self, n: int) -> bytes:
        return self.f.read(n)

    def read_small(self, limit: int = 256 * 1024, wait: float = 4.0) -> bytes:
        """Read a small file such as a playlist. Many servers never close the connection, so stop when it looks complete."""
        try:
            length = int(self.headers.get("content-length", "0") or 0)
        except ValueError:
            length = 0
        want = min(length, limit) if length > 0 else limit
        self.sock.settimeout(wait)
        data = b""
        try:
            while len(data) < want:
                chunk = self.f.read1(min(65536, want - len(data)))
                if not chunk:
                    break
                data += chunk
                if not length and parse_playlist(data.decode("utf-8", "replace")) and b"\n" in data[-2:]:
                    break  # looks complete
        except (TimeoutError, OSError):
            pass  # keep what arrived
        return data

    def close(self):
        for x in (getattr(self, "f", None), getattr(self, "sock", None)):
            try:
                x and x.close()
            except OSError:
                pass


_TITLE = re.compile(r"StreamTitle='(.*?)';(?=\s*(?:Stream\w*=|$|\x00))", re.S)


def parse_icy(block: bytes) -> str | None:
    """The song title in one ICY metadata block, or None."""
    raw = block.rstrip(b"\x00")
    if not raw:
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1", "replace")
    m = _TITLE.search(text)
    return m.group(1).strip() if m else None


_STREAM_URL = re.compile(r"StreamUrl='(.*?)';(?=\s*(?:Stream\w*=|$|\x00))", re.S)


def looks_like_picture(url: str) -> bool:
    """Is this link probably an image of the song rather than a website?"""
    u = (url or "").strip()
    if not u.lower().startswith(("http://", "https://")):
        return False
    path = urllib.parse.urlsplit(u).path.lower()
    if re.search(r"\.(jpe?g|png|webp|gif|avif)$", path):
        return True
    if re.search(r"\.(html?|php|aspx?)$", path) or path in ("", "/"):
        return False
    return bool(re.search(r"(?i)(art(work)?|cover|image|img|picture|thumb|album)", u))


def parse_icy_picture(block: bytes) -> str:
    """Image URL some stations send with the title (StreamUrl='https://.../cover.jpg')."""
    raw = block.rstrip(b"\x00")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1", "replace")
    m = _STREAM_URL.search(text)
    u = m.group(1).strip() if m else ""
    return u if looks_like_picture(u) else ""


_song_pics = None


def fetch_song_picture(url: str) -> bytes | None:
    """Download a station's song image (kept in memory only: it changes every song)."""
    global _song_pics
    import collections
    if _song_pics is None:
        _song_pics = collections.OrderedDict()
    if url in _song_pics:
        _song_pics.move_to_end(url)
        return _song_pics[url] or None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "image/*"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            data = r.read(4 * 1024 * 1024)
    except Exception:
        data = b""
    from PySide6.QtGui import QImage
    if data and QImage.fromData(data).isNull():
        data = b""
    _song_pics[url] = data
    while len(_song_pics) > 40:
        _song_pics.popitem(last=False)
    return data or None


class _PlayerGone(Exception):
    """The player stopped reading from the relay."""


class StreamRelay(QObject):
    """Relays a station through 127.0.0.1 so the ICY titles can be read from the stream."""
    titleChanged = Signal(int, str)  # session, "Artist - Title"
    pictureChanged = Signal(int, str)  # session, image URL
    reconnecting = Signal(int, bool)  # session, True while reconnecting
    infoChanged = Signal(int, dict)  # session, {"name", "genre", "bitrate", "type"}
    failed = Signal(int, str)  # session, reason

    def __init__(self, parent=None):
        super().__init__(parent)
        self.server = None
        self.session = 0
        self._urls: dict[int, str] = {}
        self._lock = threading.Lock()
        self.bytes_out = 0  # for tests

    def _ensure_server(self):
        if self.server:
            return
        relay = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *a):
                pass

            def do_GET(self):
                relay._serve(self)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, name="musicwell-radio", daemon=True).start()

    def start(self, url: str) -> str:
        """A local URL that plays `url`; the previous station stops."""
        self._ensure_server()
        with self._lock:
            self.session += 1
            s = self.session
            self._urls = {s: url}
        return f"http://127.0.0.1:{self.server.server_port}/station/{s}"

    def stop(self):
        with self._lock:
            self.session += 1
            self._urls = {}

    def _alive(self, s: int) -> bool:
        return s == self.session

    def _serve(self, h: BaseHTTPRequestHandler):
        try:
            s = int(h.path.rstrip("/").rsplit("/", 1)[-1])
        except ValueError:
            s = -1
        url = self._urls.get(s)
        if not url or not self._alive(s):
            h.send_error(404)
            return
        try:
            up = self._open_stream(url)
        except Exception as e:
            self.failed.emit(s, str(e) or type(e).__name__)
            try:
                h.send_error(502)
            except OSError:
                pass
            return
        hd = up.headers
        info = {"name": hd.get("icy-name", ""), "genre": hd.get("icy-genre", ""),
                "bitrate": hd.get("icy-br", ""), "type": up.content_type,
                "server": " ".join(x for x in (hd.get("server", ""), hd.get("icy-notice1", ""),
                                               hd.get("icy-notice2", "")) if x),
                "url": up.url}
        self.infoChanged.emit(s, info)

        def give(data: bytes):
            try:
                h.wfile.write(data)
            except (OSError, ValueError):
                raise _PlayerGone() from None
            self.bytes_out += len(data)

        try:
            h.send_response(200)
            h.send_header("Content-Type", up.content_type or "audio/mpeg")
            h.send_header("Cache-Control", "no-cache")
            h.end_headers()
        except (OSError, ValueError):
            up.close()
            return
        heard = {"icy": 0.0, "last": None}
        last_title = [None]
        metaint = int(hd.get("icy-metaint", "0") or 0)
        # No titles in the stream (many plain MP3 streams): ask the server instead.
        threading.Thread(target=self._ask_server, args=(s, up.url or url, info["server"], heard, metaint > 0),
                         name="musicwell-radio-title", daemon=True).start()
        log = logging.getLogger("musicwell.radio")
        try:
            while self._alive(s):
                why = "the station closed the connection"
                if hasattr(up, "quick"):
                    up.quick(self.STALL_S)
                try:
                    self._pump(s, up, metaint, give, heard, last_title)
                except _PlayerGone:
                    return  # the player let go
                except (OSError, ValueError) as e:
                    why = f"the connection dropped ({e or type(e).__name__})"
                up.close()
                if not self._alive(s):
                    return
                # Stream stopped (network hiccup, server dropping listeners): reconnect without telling the player.
                log.warning("Radio: %s — connecting again", why)
                self.reconnecting.emit(s, True)
                up = self._reconnect(s, url)
                if up is None:
                    return  # gave up: the player sees the end and retries itself
                self.reconnecting.emit(s, False)
                metaint = int(up.headers.get("icy-metaint", "0") or 0)
        finally:
            try:
                up.close()
            except Exception:
                pass

    STALL_S = 6.0  # seconds of silence before a station counts as stalled
    RECONNECT_FOR = 300.0  # seconds to keep reconnecting before telling the player
    RECONNECT_DELAYS = (0.5, 1, 2, 3, 5, 8, 10, 15, 20, 30)

    def _reconnect(self, s: int, url: str):
        start = time.monotonic()
        for k in itertools.count():
            if not self._alive(s):
                return None
            delay = self.RECONNECT_DELAYS[min(k, len(self.RECONNECT_DELAYS) - 1)]
            end = time.monotonic() + delay
            while time.monotonic() < end:
                if not self._alive(s):
                    return None
                time.sleep(0.2)
            try:
                up = self._open_stream(url)
                logging.getLogger("musicwell.radio").info("Radio: connected again (try %d)", k + 1)
                return up
            except Exception as e:
                logging.getLogger("musicwell.radio").info("Radio: not yet (%s)", e or type(e).__name__)
            if time.monotonic() - start > self.RECONNECT_FOR:
                return None
        return None

    def _pump(self, s: int, up: "_Upstream", metaint: int, give, heard: dict, last_title: list):
        """Pass the station's audio to the player, stripping titles, until it stops."""
        while self._alive(s):
            if metaint > 0:
                audio = up.read(metaint)
                if not audio:
                    return
                give(audio)
                n = up.read(1)
                if not n:
                    return
                size = n[0] * 16
                if size:
                    block = up.read(size)
                    title = parse_icy(block)
                    if title and not re.search(r"\s[-–—|]\s*$", title):
                        heard["icy"] = time.monotonic()
                    elif title:
                        heard["now"] = True  # "Artist - Station -": the server may know more
                    if title is not None and title != last_title[0]:
                        last_title[0] = title
                        heard["last"] = title
                        self.titleChanged.emit(s, title)
                        pic = parse_icy_picture(block)
                        if pic:
                            self.pictureChanged.emit(s, pic)  # after its song's title
            else:
                audio = up.read(16384)
                if not audio:
                    return
                give(audio)

    ASK_EVERY = 15.0  # seconds between server status checks

    def watch_hls(self, url: str) -> int:
        """HLS stations play directly; read their titles from the playlist instead."""
        with self._lock:
            self.session += 1
            s = self.session
            self._urls = {}

        def look():
            last, wait = None, 3.0
            while True:
                end = time.monotonic() + wait
                while time.monotonic() < end:
                    if not self._alive(s):
                        return
                    time.sleep(0.5)
                wait = self.ASK_EVERY
                try:
                    t, pic = hls_now(url)
                except Exception:
                    t, pic = "", ""
                if t and t != last and self._alive(s):
                    last = t
                    self.titleChanged.emit(s, t)
                    if pic:
                        self.pictureChanged.emit(s, pic)
        threading.Thread(target=look, name="musicwell-radio-hls", daemon=True).start()
        return s

    def _ask_server(self, s: int, url: str, server: str, heard: dict, has_icy: bool):
        """When the stream has no titles (or they stop), poll the server's status page (Icecast, SHOUTcast, AzuraCast)."""
        wait = 2.0 if not has_icy else 25.0  # with ICY titles, only if they stop
        while True:
            end = time.monotonic() + wait
            while time.monotonic() < end and not heard.pop("now", False):
                if not self._alive(s):
                    return
                time.sleep(0.5)
            wait = self.ASK_EVERY
            if time.monotonic() - heard["icy"] < 45:
                continue  # the stream names its songs itself
            try:
                t, pic = server_now(url, server)
            except Exception:
                t, pic = "", ""
            if t and t != heard["last"] and self._alive(s):
                heard["last"] = t
                self.titleChanged.emit(s, t)
                if pic:
                    self.pictureChanged.emit(s, pic)

    @staticmethod
    def _is_playlist(up: "_Upstream", url: str) -> bool:
        return _is_playlist(up, url)

    def _open_stream(self, url: str, depth: int = 0) -> "_Upstream":
        return open_stream(url, depth)

    def shutdown(self):
        self.stop()
        if self.server:
            try:
                self.server.shutdown()
                self.server.server_close()
            except Exception:
                pass
            self.server = None


def _is_playlist(up: "_Upstream", url: str) -> bool:
    path = url.lower().split("?")[0]
    return up.content_type in PLAYLIST_TYPES or path.endswith((".pls", ".m3u", ".asx", ".xspf"))


def open_stream(url: str, depth: int = 0) -> "_Upstream":
    """Connect to a station. Playlist links (.pls / .m3u) are opened and their streams tried in turn."""
    up = _Upstream(url)
    if not _is_playlist(up, url):
        return up
    text = up.read_small().decode("utf-8", "replace")
    up.close()
    entries = parse_playlist(text)
    if not entries:
        raise OSError("that link is a playlist with no stations in it")
    if depth >= 2:
        raise OSError("that link only leads to more playlists")
    last = None
    for _name, u in entries[:6]:
        try:
            return open_stream(u, depth + 1)
        except Exception as e:  # stream down: try the next
            last = e
    raise last or OSError("none of the playlist's streams answered")


def _peek(url: str, max_bytes: int, timeout: float, max_seconds: float) -> tuple[str | None, int, str, str]:
    """(title, bytes, server name, final stream URL)"""
    up = open_stream(url)
    total = 0
    server = up.headers.get("server", "") + " " + up.headers.get("icy-notice2", "")
    real = up.url
    try:
        metaint = int(up.headers.get("icy-metaint", "0") or 0)
        if metaint <= 0:
            return None, 0, server, real
        up.sock.settimeout(timeout)
        t0 = time.monotonic()
        while total < max_bytes and time.monotonic() - t0 < max_seconds:
            left = metaint
            while left:  # skip the audio before the title
                chunk = up.f.read(min(65536, left))
                if not chunk:
                    return "", total, server, real
                left -= len(chunk)
                total += len(chunk)
            n = up.read(1)
            if not n:
                break
            size = n[0] * 16
            total += 1 + size
            if size:
                title = parse_icy(up.read(size))
                if title:
                    return title, total, server, real
        return "", total, server, real
    finally:
        up.close()


def server_title(url: str, server: str = "") -> str:
    return server_now(url, server)[0]


def server_now(url: str, server: str = "") -> tuple[str, str]:
    """Ask the station's server (AzuraCast API, Icecast or SHOUTcast status) what's playing."""
    u = urllib.parse.urlsplit(url or "")
    if u.scheme not in ("http", "https") or not u.hostname:
        return "", ""
    base = f"{u.scheme}://{u.netloc}"
    tries = []
    m = re.match(r"^/listen/([^/]+)/", u.path or "")
    if m:
        tries.append(("azuracast", f"{base}/api/nowplaying/{m.group(1)}"))
    q = urllib.parse.parse_qs(u.query)
    sid = (q.get("sid") or ["1"])[0]
    sid = sid if sid.isdigit() else "1"
    shout = ("shoutcast", f"{base}/stats?sid={sid}&json=1")
    ice = ("icecast", f"{base}/status-json.xsl")
    tries += [shout, ice] if re.search(r"(?i)shoutcast", server or "") else [ice, shout]
    for kind, link in tries:
        try:
            d = _get_json_small(link, timeout=4.0)
        except Exception:
            continue
        try:
            t = _title_from_status(kind, d, u.path or "/")
        except Exception:
            t = ""
        if t:
            pic = ""
            if kind == "azuracast":
                try:
                    dd = d[0] if isinstance(d, list) and d else d
                    pic = str((((dd or {}).get("now_playing") or {}).get("song") or {}).get("art") or "")
                except Exception:
                    pic = ""
            return t, (pic if looks_like_picture(pic) or pic.lower().startswith(("http://", "https://")) else "")
    return "", ""


def _title_from_status(kind: str, d, path: str) -> str:
    def join(artist, title):
        artist, title = str(artist or "").strip(), str(title or "").strip()
        return f"{artist} - {title}" if artist and title else title or artist
    if kind == "azuracast":
        if isinstance(d, list):
            d = d[0] if d else {}
        song = ((d or {}).get("now_playing") or {}).get("song") or {}
        return str(song.get("text") or join(song.get("artist"), song.get("title")) or "").strip()
    if kind == "shoutcast":
        return str((d or {}).get("songtitle") or "").strip()
    if kind == "icecast":
        src = ((d or {}).get("icestats") or {}).get("source") or []
        if isinstance(src, dict):
            src = [src]
        src = [x for x in src if isinstance(x, dict)]
        mine = [x for x in src if urllib.parse.urlsplit(str(x.get("listenurl") or "")).path.rstrip("/") == path.rstrip("/")]
        pick = mine[0] if mine else (src[0] if len(src) == 1 else None)
        if pick:
            return join(pick.get("artist"), pick.get("title") or pick.get("yp_currently_playing"))
    return ""


_EXTINF = re.compile(r"#EXTINF:[^,\n]*,(.*)")


def hls_title(url: str) -> str:
    return hls_now(url)[0]


_PIC_IN_TEXT = re.compile(r"""(?i)(?:amgArtworkURL|artworkURL|artwork_url|imageURL|image|cover)\\?=\\?["']"""
                          r"""(https?://[^"'\\\s]+)""")
_IMG_LINK = re.compile(r"""(?i)(https?://[^"'\\\s,]+\.(?:jpe?g|png|webp)(?:\?[^"'\\\s,]*)?)""")


def _picture_in(text: str) -> str:
    m = _PIC_IN_TEXT.search(text) or _IMG_LINK.search(text)
    return m.group(1) if m else ""


def hls_now(url: str) -> tuple[str, str]:
    """HLS (.m3u8): read the song from #EXTINF lines, sometimes with an image."""
    def get(link):
        req = urllib.request.Request(link, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=6) as r:
            return r.read(256 * 1024).decode("utf-8", "replace"), r.geturl()
    text, where = get(url)
    for _ in range(2):  # master playlist: follow its first stream
        lines = [x.strip() for x in text.splitlines() if x.strip()]
        if any(x.startswith("#EXT-X-STREAM-INF") for x in lines):
            nxt = next((x for i, x in enumerate(lines) if not x.startswith("#")
                        and i and lines[i - 1].startswith("#EXT-X-STREAM-INF")), None)
            if not nxt:
                return "", ""
            text, where = get(urllib.parse.urljoin(where, nxt))
        else:
            break
    lines = [x for x in text.splitlines() if x.startswith("#EXTINF")]
    for line in reversed(lines):
        m = _EXTINF.match(line)
        raw = (m.group(1) if m else "").strip()
        if not raw:
            continue
        kv = dict(re.findall(r'(\w+)="([^"]*)"', raw))
        if kv:
            artist, title = kv.get("artist", "").strip(), kv.get("title", "").strip()
            t = f"{artist} - {title}" if artist and title else title
        else:
            t = raw
        if t and not re.fullmatch(r"[\d.\s-]*", t):
            return t, _picture_in(line)
    return "", ""


def now_title(st: dict, quick: bool = False) -> tuple[str | None, int]:
    """What a station is playing, from its stream, server or HLS playlist."""
    url = st.get("url") or ""
    if needs_direct(st):
        try:
            t = hls_title(url)
        except Exception:
            t = ""
        return (t or None), 0
    title, n, server, real = _peek(url, *((192 * 1024, 6.0, 6.0) if quick else (512 * 1024, 8.0, 15.0)))
    if not title:
        t = server_title(real or url, server)
        if t:
            return t, n
    return title, n


# adverts, jingles and station IDs
_AD_WORDS = re.compile(
    r"(?i)\b(advert(s|isement|isements|ising)?|commercials?|ad ?breaks?|adverbreak|spot ?block|sponsor(ed|ship)?|"
    r"promo(tion)?s?|jingles?|station ?id|ident|liners?|sweepers?|stingers?|werbung|publicidad|"
    r"pubblicit[aà]|reclame|publicit[eé])\b")


def station_id(st: dict) -> str:
    return (st or {}).get("uuid") or (st or {}).get("url") or ""


def _plain(x: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (x or "").lower())


def is_advert(text: str, st: dict | None, sends_songs: bool, own: list | None = None) -> bool:
    """Does the current title look like an advert, jingle or station ID? sends_songs: the station usually sends "Artist - Title"."""
    t = (text or "").strip()
    if own and _plain(t) and _plain(t) in {_plain(x) for x in own}:
        return True
    if 'song_spot="t"' in t.lower() or 'song_spot="T"' in t:
        return True  # iHeart-style streams mark their adverts
    parts = [x.strip() for x in t.split(" - ", 1)] if " - " in t else []
    if len(parts) == 2 and all(parts):
        # "Artist - Title" is a song unless a side is an advert word or the station name.
        name = _plain((st or {}).get("name", ""))
        for side in parts:
            m = _AD_WORDS.search(side)
            if m and len(_plain(side)) <= len(_plain(m.group(0))) + len("break"):
                return True
        return bool(sends_songs and name and _plain(parts[0]) == name)
    if _AD_WORDS.search(t):
        return True
    if not sends_songs:
        return False  # station never names songs: can't tell
    if not t:
        return True
    name = _plain((st or {}).get("name", ""))
    p = _plain(t)
    if name and (p == name or (p.startswith(name) and " - " not in t)):
        return True  # just the station name or slogan
    if re.match(r"(?i)^(https?://|www\.)\S+$", t):
        return True  # its web address
    return False


# Wider than is_advert: also news, show names and phone-ins, for the radio stats.
_NOT_SONG_WORDS = re.compile(
    r"(?i)\b(news|newsbeat|bulletin|traffic|travel|weather|sport|headlines|breakfast|drivetime|the drive|"
    r"show|podcast|interview|competition|win|call|text|listen|on air|more music|non ?stop|"
    r"break|spots?|ads?|sale|offer|discount|% off|free|book now|terms apply|t&cs?)\b")
_WEB = re.compile(r"(?i)(https?://|www\.|\b[\w-]+\.(com|co\.uk|org\.uk|net|org|fm|io|de|nl|fr|ie|au|ca|radio)\b)")
_PHONE = re.compile(r"(\+?\d[\d ()-]{8,}\d)")


def not_a_song(text: str, st: dict | None, own: list | None = None, sends_songs: bool = True) -> bool:
    """Is the title something other than a song? (advert, jingle, station ID, news, show name...)"""
    t = (text or "").strip()
    if not t:
        return True
    if is_advert(t, st, sends_songs, own):
        return True
    if _WEB.search(t) or _PHONE.search(t):
        return True
    name = _plain((st or {}).get("name", ""))
    p = _plain(t)
    parts = [x.strip() for x in t.split(" - ", 1)] if " - " in t else []
    if len(parts) == 2 and all(parts):
        if name and (_plain(parts[1]) == name or _plain(parts[0]) == name):
            return True  # "Groove FM - The Best Music", "Hits - Groove FM"
        return False
    # without "Artist - Title" it's a song only if the station never uses that form
    if name and len(p) >= 4 and (p in name or name in p):
        return True  # station name, shortened or with a slogan
    if _NOT_SONG_WORDS.search(t):
        return True
    return bool(sends_songs)


# "up next": only some servers report it
def next_source(stream_url: str, server: str = "") -> dict | None:
    """Where to ask what's playing next, if the server supports it (AzuraCast or SHOUTcast 2)."""
    u = urllib.parse.urlsplit(stream_url or "")
    if u.scheme not in ("http", "https") or not u.hostname:
        return None
    base = f"{u.scheme}://{u.netloc}"
    m = re.match(r"^/listen/([^/]+)/", u.path or "")
    if m:
        return {"kind": "azuracast", "url": f"{base}/api/nowplaying/{m.group(1)}"}
    if re.search(r"(?i)shoutcast", server or ""):
        q = urllib.parse.parse_qs(u.query)
        sid = (q.get("sid") or ["1"])[0]
        if not sid.isdigit():
            sid = "1"
        return {"kind": "shoutcast", "url": f"{base}/nextsongs?sid={sid}&json=1",
                "stats": f"{base}/stats?sid={sid}&json=1"}
    return None


def _get_json_small(url: str, timeout: float = 6.0):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read(512 * 1024).decode("utf-8", "replace"))


def fetch_next(src: dict) -> list[str]:
    """Next titles, soonest first; [] if unknown. Raises when the server doesn't answer."""
    if src["kind"] == "azuracast":
        d = _get_json_small(src["url"])
        if isinstance(d, list):
            d = d[0] if d else {}
        nxt = (d or {}).get("playing_next") or {}
        song = nxt.get("song") or {}
        text = song.get("text") or " - ".join(x for x in (song.get("artist"), song.get("title")) if x)
        return [text.strip()] if text and text.strip() else []
    if src["kind"] == "shoutcast":
        try:
            d = _get_json_small(src["url"])
            items = d if isinstance(d, list) else (d.get("nextsongs") or d.get("songs") or [])
            titles = [str(x.get("title", "")).strip() for x in items if isinstance(x, dict)]
            titles = [t for t in titles if t]
            if titles:
                return titles
        except (OSError, ValueError, AttributeError):
            pass
        d = _get_json_small(src["stats"])
        t = str((d or {}).get("nexttitle", "") or "").strip()
        return [t] if t else []
    return []


def needs_direct(st: dict) -> bool:
    """HLS streams (.m3u8) go straight to the player; they carry no ICY titles."""
    return bool(st.get("hls"))


def logo_path(url: str):
    from musicwell.paths import cache_dir
    d = cache_dir() / "radio-logos"
    d.mkdir(parents=True, exist_ok=True)
    return d / (hashlib.sha1(url.encode()).hexdigest()[:20] + ".img")


# Your own station images, kept with the library.

def own_picture_path(st: dict):
    from musicwell.paths import data_dir
    d = data_dir() / "station-pictures"
    d.mkdir(parents=True, exist_ok=True)
    return d / (hashlib.sha1(st.get("uuid", st.get("url", "")).encode()).hexdigest()[:20] + ".png")


def has_own_picture(st: dict) -> bool:
    return own_picture_path(st).exists()


def set_own_picture(st: dict, img) -> bool:
    """Save a station image, padded square and at most 512 px."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QImage, QPainter
    if img is None or img.isNull():
        return False
    side = max(img.width(), img.height())
    sq = QImage(side, side, QImage.Format_ARGB32_Premultiplied)
    sq.fill(QColor(255, 255, 255) if img.hasAlphaChannel() else _edge_colour(img))
    p = QPainter(sq)
    p.drawImage((side - img.width()) // 2, (side - img.height()) // 2, img)
    p.end()
    if side > 512:
        sq = sq.scaled(512, 512, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return sq.save(str(own_picture_path(st)), "PNG")


def _edge_colour(img):
    """Average colour along the edge, so the padding blends in."""
    from PySide6.QtGui import QColor
    w, h = img.width(), img.height()
    pts = [(int(w * i / 20), y) for i in range(20) for y in (0, h - 1)] + \
          [(x, int(h * i / 20)) for i in range(20) for x in (0, w - 1)]
    cs = [img.pixelColor(x, y) for x, y in pts]
    n = len(cs)
    return QColor(sum(c.red() for c in cs) // n, sum(c.green() for c in cs) // n, sum(c.blue() for c in cs) // n)


def remove_own_picture(st: dict):
    try:
        own_picture_path(st).unlink()
    except OSError:
        pass


def fetch_logo(url: str) -> bytes | None:
    """A station's logo (cached for a month), or None."""
    if not url or not url.lower().startswith(("http://", "https://")):
        return None
    p = logo_path(url)
    miss = p.with_suffix(".miss")
    if p.exists() and time.time() - p.stat().st_mtime < 30 * 86400:
        return p.read_bytes()
    if miss.exists() and time.time() - miss.stat().st_mtime < 7 * 86400:
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "image/*"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            data = r.read(3 * 1024 * 1024)
    except Exception:
        data = b""
    from PySide6.QtGui import QImage
    if not data or QImage.fromData(data).isNull():
        try:
            miss.touch()
        except OSError:
            pass
        return None
    try:
        p.write_bytes(data)
    except OSError:
        pass
    return data
