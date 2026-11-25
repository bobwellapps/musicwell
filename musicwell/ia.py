"""Internet Archive (archive.org) search and streaming, limited to freely shareable collections."""
from __future__ import annotations

import json
import re
import threading
import urllib.parse
import urllib.request

from musicwell import __version__

USER_AGENT = f"Musicwell{'/' + __version__ if __version__ else ''} (Linux desktop music player)"
TIMEOUT = 12
BASE = "https://archive.org"
BASE_OVERRIDE = ""  # for tests

FREE = ("(collection:etree OR collection:netlabels OR licenseurl:*creativecommons.org* "
        "OR licenseurl:*publicdomain*)")
COLLECTION_NAMES = {"etree": "Live Music Archive", "netlabels": "Netlabels", "opensource_audio": "Community Audio",
                    "78rpm": "Great 78 Project", "audio_music": "Music"}
FIELDS = ["identifier", "title", "creator", "date", "year", "subject", "collection", "downloads", "licenseurl",
          "avg_rating"]
# playable formats, best first
FORMATS = [("VBR MP3", "MP3"), ("MP3", "MP3"), ("320Kbps MP3", "MP3"), ("256Kbps MP3", "MP3"),
           ("128Kbps MP3", "MP3"), ("64Kbps MP3", "MP3"), ("Ogg Vorbis", "Ogg"), ("Flac", "FLAC"),
           ("24bit Flac", "FLAC"), ("Apple Lossless Audio", "ALAC"), ("AAC", "AAC")]


def _url(u: str) -> str:
    return (BASE_OVERRIDE + u[len(BASE):]) if BASE_OVERRIDE and u.startswith(BASE) else u


def _get_json(url: str):
    req = urllib.request.Request(_url(url), headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read(16 * 1024 * 1024).decode("utf-8", "replace"))


def _first(v) -> str:
    if isinstance(v, list):
        return str(v[0]) if v else ""
    return str(v or "")


def _quote(term: str) -> str:
    """Strip the search syntax's special characters."""
    return '"' + re.sub(r'[\\"():\[\]{}^~*?]', " ", term).strip() + '"'


def search(query: str, rows: int = 50, sort: str = "downloads desc") -> list[dict]:
    """Free items matching an archive.org search."""
    q = f"({query}) AND mediatype:audio AND {FREE}"
    params = [("q", q), ("rows", str(rows)), ("page", "1"), ("output", "json")]
    params += [("fl[]", f) for f in FIELDS]
    if sort:
        params.append(("sort[]", sort))
    data = _get_json(f"{BASE}/advancedsearch.php?" + urllib.parse.urlencode(params))
    return [x for x in (item_from(d) for d in (data.get("response") or {}).get("docs", [])) if x]


def search_text(text: str, rows: int = 100, field: str = "any") -> list[dict]:
    """Search creator, title and subject only; descriptions match too loosely."""
    words = [w for w in re.split(r"\s+", text.strip()) if w]
    if not words:
        return []
    phrase = _quote(text.strip())
    all_words = " AND ".join(_quote(w) for w in words)

    def on(name):
        return f"{name}:{phrase} OR {name}:({all_words})"
    if field == "artist":
        q = on("creator")
    elif field in ("title", "album"):
        q = on("title")
    elif field == "genre":
        q = on("subject")
    else:
        q = f"{on('creator')} OR {on('title')} OR {on('subject')}"
    return search(q, rows, sort="")


def item_from(d: dict) -> dict | None:
    ident = d.get("identifier")
    if not ident:
        return None
    colls = d.get("collection") or []
    colls = colls if isinstance(colls, list) else [colls]
    subj = d.get("subject") or []
    subj = subj if isinstance(subj, list) else re.split(r"\s*;\s*", str(subj))
    known = next((COLLECTION_NAMES[c] for c in colls if c in COLLECTION_NAMES), "")
    lic = _first(d.get("licenseurl"))
    return {
        "kind": "ia",
        "badge": "Archive",
        "identifier": ident,
        "title": re.sub(r"\s+", " ", _first(d.get("title")) or ident).strip(),
        "creator": re.sub(r"\s+", " ", _first(d.get("creator"))).strip(),
        "date": (_first(d.get("date")) or _first(d.get("year")))[:10],
        "subjects": [s.strip() for s in subj if s and s.strip()][:12],
        "collection": known or (colls[0] if colls else ""),
        "live": "etree" in colls,
        "downloads": int(d.get("downloads") or 0),
        "license": licence_name(lic) if lic else ("Shared with the band's permission" if "etree" in colls else ""),
        "licenseurl": lic,
        "page": f"https://archive.org/details/{ident}",
        "image": f"https://archive.org/services/img/{ident}",
    }


def licence_name(url: str) -> str:
    u = url.lower()
    if "publicdomain" in u:
        return "Public domain"
    m = re.search(r"licenses/([a-z\-]+)/([\d.]+)", u)
    if m:
        return f"CC {m.group(1).upper()} {m.group(2)}"
    return "Creative Commons" if "creativecommons" in u else ""


def describe(it: dict) -> str:
    """e.g. 'Neon Harbor · 2019-05-04 · Live Music Archive · 12,345 plays'"""
    bits = [it.get("creator") or "", it.get("date") or "", it.get("collection") or ""]
    if it.get("downloads"):
        bits.append(f"{it['downloads']:,} plays")
    return "  ·  ".join(b for b in bits if b)


_tracks_cache: dict[str, list[dict]] = {}
_cache_lock = threading.Lock()


def _seconds(v) -> float:
    s = str(v or "").strip()
    if not s:
        return 0.0
    if ":" in s:
        parts = [float(p) for p in s.split(":") if p.replace(".", "", 1).isdigit()]
        total = 0.0
        for p in parts:
            total = total * 60 + p
        return total
    try:
        return float(s)
    except ValueError:
        return 0.0


def _track_no(v) -> int:
    m = re.match(r"\s*(\d+)", str(v or ""))
    return int(m.group(1)) if m else 0


def item_tracks(it: dict) -> list[dict]:
    """An item's playable tracks, in order, as track dicts."""
    ident = it["identifier"]
    with _cache_lock:
        if ident in _tracks_cache:
            return _tracks_cache[ident]
    data = _get_json(f"{BASE}/metadata/{urllib.parse.quote(ident)}")
    md = data.get("metadata") or {}
    files = [f for f in (data.get("files") or []) if f.get("name") and str(f.get("private", "")).lower() != "true"]
    chosen, label = [], ""
    for fmt, lab in FORMATS:
        chosen = [f for f in files if f.get("format") == fmt]
        if chosen:
            label = lab
            break
    album = _first(md.get("title")) or it.get("title") or ident
    creator = _first(md.get("creator")) or it.get("creator") or ""
    year = int((re.match(r"\d{4}", _first(md.get("date")) or it.get("date") or "") or [0])[0] or 0)
    chosen.sort(key=lambda f: (_track_no(f.get("track")) or 9999, f["name"].lower()))
    tracks = []
    for n, f in enumerate(chosen, 1):
        name = f["name"]
        stem = re.sub(r"\.[a-z0-9]+$", "", name.rsplit("/", 1)[-1], flags=re.I)
        title = f.get("title") or re.sub(r"^\d+[\s._-]+", "", stem).replace("_", " ").strip() or stem
        tracks.append(remote_track(
            url=f"https://archive.org/download/{urllib.parse.quote(ident)}/{urllib.parse.quote(name)}",
            title=title, artist=f.get("creator") or f.get("artist") or creator, album=f.get("album") or album,
            number=_track_no(f.get("track")) or n, length=_seconds(f.get("length")), fmt=label, year=year,
            item=it))
    with _cache_lock:
        _tracks_cache[ident] = tracks
    return tracks


_ids = [-10_000_000]


def remote_track(url: str, title: str, artist: str, album: str, number: int, length: float, fmt: str,
                 year: int, item: dict) -> dict:
    """Track dict for an online song."""
    _ids[0] -= 1
    return {
        "id": _ids[0], "remote": True, "item": item, "path": url, "title": title, "artist": artist,
        "artist_key": artist, "album": album, "albumartist": item.get("creator") or artist,
        "genre": (item.get("subjects") or [""])[0], "composer": "", "year": year, "track": number, "disc": 0,
        "length": length, "bitrate": 0, "samplerate": 0, "bitdepth": 0, "channels": 2, "format": fmt or "MP3",
        "rating": 0, "playcount": 0, "skipcount": 0, "lastplayed": 0, "added": 0, "mtime": 0, "filesize": 0,
        "decade": year // 10 * 10 if year else 0, "folder": "", "_extra": {}, "_text": "", "grouping": "",
        "comment": "", "label": "", "mood": "", "source": "Online",
    }


def similar_items(artist: str, similar_artists: list[str], genres: list[str], limit: int = 40) -> list[dict]:
    """Free items by the artist, similar artists, then genre."""
    return [it for _, it in similar_scored(artist, similar_artists, genres, limit)]


def similar_scored(artist: str, similar_artists: list[str], genres: list[str], limit: int = 40) -> list[tuple]:
    """(score, item), best first: 3 artist, 2 similar artist, 1 genre."""
    found: dict[str, tuple[float, dict]] = {}

    def add(items, base: float, who: list[str] | None = None):
        for it in items:
            score = base
            if who:
                c = it["creator"].lower()
                for i, name in enumerate(who):
                    if name.lower() and name.lower() in c:
                        score = base - i * 0.05
                        break
                else:
                    continue
            score += min(it["downloads"], 200_000) / 2_000_000  # popularity breaks ties
            if it["identifier"] not in found or found[it["identifier"]][0] < score:
                found[it["identifier"]] = (score, it)

    if artist:
        add(search(f"creator:{_quote(artist)}", rows=25), 3.0, [artist])
    others = [a for a in similar_artists if a and a.lower() != (artist or "").lower()][:10]
    if others:
        q = " OR ".join(f"creator:{_quote(a)}" for a in others)
        add(search(q, rows=40), 2.0, others)
    gen = [g for g in genres if g][:4]
    if gen:
        q = " OR ".join(f"subject:{_quote(g)}" for g in gen)
        add(search(q, rows=30), 1.0)
    out = sorted(found.values(), key=lambda x: -x[0])
    # at most three items per artist
    per: dict[str, int] = {}
    picked = []
    for score, it in out:
        k = it["creator"].lower()
        if per.get(k, 0) >= 3:
            continue
        per[k] = per.get(k, 0) + 1
        picked.append((score, it))
        if len(picked) >= limit:
            break
    return picked
