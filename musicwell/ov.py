"""Openverse (openverse.org) search for Creative Commons and public-domain music."""
from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.parse
import urllib.request

from musicwell import __version__

USER_AGENT = f"Musicwell{'/' + __version__ if __version__ else ''} (Linux desktop music player)"
TIMEOUT = 12
BASE = "https://api.openverse.org/v1"
BASE_OVERRIDE = ""  # for tests
PAGE = 20  # max results per anonymous request

PROVIDERS = {"jamendo": "Jamendo", "wikimedia_audio": "Wikimedia Commons", "freesound": "Freesound",
             "ccmixter": "ccMixter"}


class Busy(Exception):
    """Openverse rate-limited us."""


def _url(u: str) -> str:
    return (BASE_OVERRIDE + u[len(BASE):]) if BASE_OVERRIDE and u.startswith(BASE) else u


_cache: dict[str, list[dict]] = {}
_lock = threading.Lock()


def _search(params: dict) -> list[dict]:
    params = dict(params, category="music", page_size=str(PAGE), mature="false")
    key = json.dumps(params, sort_keys=True)
    with _lock:
        if key in _cache:
            return _cache[key]
    req = urllib.request.Request(_url(f"{BASE}/audio/?" + urllib.parse.urlencode(params)),
                                 headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            data = json.loads(r.read(8 * 1024 * 1024).decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise Busy() from e
        raise
    out = [x for x in (item_from(d) for d in data.get("results", [])) if x]
    with _lock:
        _cache[key] = out
    return out


def licence_name(lic: str, version: str) -> str:
    lic = (lic or "").lower()
    if lic in ("cc0", "pdm"):
        return "Public domain" if lic == "pdm" else "CC0 (public domain)"
    return f"CC {lic.upper()} {version}".strip() if lic else ""


def item_from(d: dict) -> dict | None:
    """A result in the same shape as an Internet Archive item."""
    url = d.get("url") or ""
    if not d.get("id") or not url.lower().startswith(("http://", "https://")):
        return None
    provider = d.get("provider") or d.get("source") or ""
    aset = d.get("audio_set") or {}
    genres = [g for g in (d.get("genres") or []) if g]
    tags = [t.get("name", "") for t in (d.get("tags") or []) if isinstance(t, dict) and t.get("name")]
    return {
        "kind": "ov",
        "identifier": "ov:" + str(d["id"]),
        "ov_id": str(d["id"]),
        "title": re.sub(r"\s+", " ", d.get("title") or "Untitled").strip(),
        "creator": re.sub(r"\s+", " ", d.get("creator") or "").strip(),
        "date": "",
        "subjects": (genres + tags)[:10],
        "collection": PROVIDERS.get(provider, provider.replace("_", " ").title()),
        "badge": PROVIDERS.get(provider, "Openverse"),
        "live": False,
        "downloads": 0,
        "license": licence_name(d.get("license", ""), d.get("license_version", "")),
        "licenseurl": d.get("license_url") or "",
        "attribution": d.get("attribution") or "",
        "page": d.get("foreign_landing_url") or f"https://openverse.org/audio/{d['id']}",
        "image": d.get("thumbnail") or (aset.get("thumbnail") if isinstance(aset, dict) else "") or "",
        "album": (aset.get("title") if isinstance(aset, dict) else "") or "",
        "audio_url": url,
        "length": (d.get("duration") or 0) / 1000.0,
        "filetype": (d.get("filetype") or "mp3").upper(),
    }


def search_text(text: str, field: str = "any") -> list[dict]:
    """The general search ignores the artist, so "any" also runs an artist search. field: any / artist / title / album / genre"""
    text = text.strip()
    if not text:
        return []
    if field == "artist":
        return _search({"creator": text})
    if field == "title":
        return _search({"title": text})
    if field == "genre":
        return _search({"tags": text})
    out = _search({"q": text})
    if field == "any":
        try:
            out = _search({"creator": text}) + out
        except Busy:
            pass
    return out


def describe(it: dict) -> str:
    """e.g. 'Neon Harbor · Jamendo · 3:12'"""
    from musicwell.models import fmt_time
    bits = [it.get("creator") or "", it.get("album") or "", it.get("collection") or "",
            fmt_time(it["length"]) if it.get("length") else ""]
    return "  ·  ".join(b for b in bits if b)


def to_track(it: dict, number: int = 0) -> dict:
    """A playable online track."""
    from musicwell import ia
    return ia.remote_track(url=it["audio_url"], title=it["title"], artist=it["creator"],
                           album=it.get("album") or it["collection"], number=number, length=it.get("length") or 0,
                           fmt=it.get("filetype") or "MP3", year=0, item=it)


def _q(name: str) -> str:
    return '"' + re.sub(r'["|+\-*()~]', " ", name).strip() + '"'


def similar_items(artist: str, similar_artists: list[str], genres: list[str]) -> list[tuple[float, dict]]:
    """(score, track) for the artist, similar artists, then genre. At most three requests."""
    found: dict[str, tuple[float, dict]] = {}

    def add(items, base, who=None):
        for it in items:
            score = base
            if who:
                c = it["creator"].lower()
                for i, name in enumerate(who):
                    if name and name.lower() in c:
                        score = base - i * 0.05
                        break
                else:
                    continue
            if it["identifier"] not in found or found[it["identifier"]][0] < score:
                found[it["identifier"]] = (score, it)

    if artist:
        add(_search({"creator": artist}), 3.0, [artist])
    others = [a for a in similar_artists if a and a.lower() != (artist or "").lower()][:8]
    if others:
        add(_search({"q": " | ".join(_q(a) for a in others)}), 2.0, others)
    gen = [g for g in genres if g][:4]
    if gen:
        add(_search({"q": " | ".join(_q(g) for g in gen)}), 1.0)
    return sorted(found.values(), key=lambda x: -x[0])
