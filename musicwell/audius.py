"""Audius (audius.co) search and streaming. The public API needs no key."""
from __future__ import annotations

import json
import re
import threading
import urllib.parse
import urllib.request

from musicwell import __version__

USER_AGENT = f"Musicwell{'/' + __version__ if __version__ else ''} (Linux desktop music player)"
APP_NAME = "Musicwell"
TIMEOUT = 12
BASE = "https://api.audius.co/v1"
BASE_OVERRIDE = ""  # for tests
LIMIT = 50

# Audius's own genre names; genre search must use one of these
GENRES = ["Electronic", "Rock", "Metal", "Alternative", "Hip-Hop/Rap", "Experimental", "Punk", "Folk", "Pop",
          "Ambient", "Soundtrack", "World", "Jazz", "Acoustic", "Funk", "R&B/Soul", "Devotional", "Classical",
          "Reggae", "Country", "Blues", "Latin", "Lo-Fi", "Hyperpop", "Dancehall", "Techno", "Trap", "House",
          "Tech House", "Deep House", "Disco", "Electro", "Jungle", "Progressive House", "Hardstyle", "Glitch Hop",
          "Trance", "Future Bass", "Future House", "Tropical House", "Downtempo", "Drum & Bass", "Dubstep",
          "Jersey Club", "Vaporwave", "Moombahton"]


def _url(u: str) -> str:
    return (BASE_OVERRIDE + u[len(BASE):]) if BASE_OVERRIDE and u.startswith(BASE) else u


_cache: dict[str, list] = {}
_lock = threading.Lock()


def _get(path: str, params: dict | None = None):
    params = dict(params or {}, app_name=APP_NAME)
    url = f"{BASE}{path}?" + urllib.parse.urlencode(params)
    with _lock:
        if url in _cache:
            return _cache[url]
    req = urllib.request.Request(_url(url), headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        data = json.loads(r.read(8 * 1024 * 1024).decode("utf-8", "replace")).get("data") or []
    with _lock:
        _cache[url] = data
    return data


def _norm(s: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (s or "").lower()))


def item_from(d: dict) -> dict | None:
    """A track in the same shape as an Openverse item."""
    if not isinstance(d, dict) or not d.get("id"):
        return None
    if d.get("is_streamable") is False or d.get("is_stream_gated") or d.get("stream_conditions") \
            or d.get("is_delete") or d.get("is_unlisted"):
        return None  # not streamable or removed
    user = d.get("user") or {}
    art = d.get("artwork") or {}
    tags = [t.strip() for t in str(d.get("tags") or "").split(",") if t.strip()]
    genre = d.get("genre") or ""
    tid = str(d["id"])
    lic = str(d.get("license") or "")
    return {
        "kind": "au",
        "identifier": "au:" + tid,
        "au_id": tid,
        "title": re.sub(r"\s+", " ", d.get("title") or "Untitled").strip(),
        "creator": re.sub(r"\s+", " ", user.get("name") or user.get("handle") or "").strip(),
        "handle": user.get("handle") or "",
        "date": str(d.get("release_date") or "")[:10],
        "subjects": ([genre] if genre else []) + ([d["mood"]] if d.get("mood") else []) + tags[:8],
        "genre": genre,
        "collection": "Audius",
        "badge": "Audius",
        "live": False,
        "downloads": int(d.get("play_count") or 0),
        "license": lic if lic and lic.lower() != "all rights reserved" else "Free to stream on Audius",
        "licenseurl": "",
        "attribution": f"“{d.get('title') or ''}” by {user.get('name') or user.get('handle') or ''} (Audius)",
        "page": "https://audius.co" + (d.get("permalink") or f"/tracks/{tid}"),
        "image": art.get("480x480") or art.get("150x150") or art.get("1000x1000") or "",
        "album": "",
        "audio_url": _url(f"{BASE}/tracks/{urllib.parse.quote(tid)}/stream?app_name={APP_NAME}"),
        "length": float(d.get("duration") or 0),
        "filetype": "MP3",
    }


def _items(rows) -> list[dict]:
    return [x for x in (item_from(d) for d in rows or []) if x]


def genre_name(text: str) -> str:
    """'hip hop' -> 'Hip-Hop/Rap'; '' if Audius has no such genre."""
    t = _norm(text.replace("&", " and "))
    for g in GENRES:
        n = _norm(g.replace("&", " and ").replace("/", " "))
        if t == n or t == _norm(g) or (len(t) > 2 and n.startswith(t)) or t.replace(" ", "") == n.replace(" ", ""):
            return g
    aliases = {"hip hop": "Hip-Hop/Rap", "hiphop": "Hip-Hop/Rap", "rap": "Hip-Hop/Rap", "rnb": "R&B/Soul",
               "r and b": "R&B/Soul", "soul": "R&B/Soul", "dnb": "Drum & Bass", "lofi": "Lo-Fi",
               "chill": "Downtempo", "edm": "Electronic", "dance": "House"}
    return aliases.get(t, "")


def artist_tracks(name: str) -> list[dict]:
    """Tracks by artists with this name, most played first."""
    users = _get("/users/search", {"query": name})
    want = _norm(name)
    picked = [u for u in users if _norm(u.get("name")) == want or _norm(u.get("handle")) == want.replace(" ", "")]
    if not picked:
        picked = [u for u in users if want and all(w in _norm(u.get("name")) for w in want.split())][:2]
    out = []
    for u in picked[:3]:
        out += _items(_get(f"/users/{urllib.parse.quote(str(u['id']))}/tracks",
                           {"limit": LIMIT, "sort_method": "plays", "sort_direction": "desc"}))
    return out


def search_text(text: str, field: str = "any") -> list[dict]:
    """field: any / artist / title / album / genre"""
    text = text.strip()
    if not text:
        return []
    if field == "artist":
        return artist_tracks(text) or [it for it in _items(_get("/tracks/search", {"query": text}))
                                       if _norm(text) in _norm(it["creator"])]
    if field == "genre":
        g = genre_name(text)
        if g:
            return _items(_get("/tracks/trending", {"genre": g, "time": "allTime"}))
        return _items(_get("/tracks/search", {"query": text}))
    found = _items(_get("/tracks/search", {"query": text, "limit": LIMIT}))
    if field == "any":
        try:
            found = artist_tracks(text) + found
        except Exception:
            pass
    return found


def similar_items(artist: str, similar_artists: list[str], genres: list[str]) -> list[tuple[float, dict]]:
    """(score, track) for Find similar: the artist, similar artists, then the genre. Same scale as Openverse (3/2/1)."""
    found: dict[str, tuple[float, dict]] = {}

    def add(items, score):
        for it in items:
            if it["identifier"] not in found or found[it["identifier"]][0] < score:
                found[it["identifier"]] = (score, it)
    if artist:
        add(artist_tracks(artist)[:15], 3.0)
    for i, a in enumerate([a for a in similar_artists if a and _norm(a) != _norm(artist)][:4]):
        try:
            add(artist_tracks(a)[:6], 2.0 - i * 0.05)
        except Exception:
            pass
    for g in genres[:3]:
        name = genre_name(g)
        if name:
            add(_items(_get("/tracks/trending", {"genre": name, "time": "month"}))[:10], 1.0)
            break
    return sorted(found.values(), key=lambda x: -x[0])
