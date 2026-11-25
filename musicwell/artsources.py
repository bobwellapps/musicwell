"""Online sources for covers and artist photos, limited to ones whose terms allow use in a music player. Covers come from the Cover Art Archive; artist photos only from Wikimedia Commons (via Wikipedia, Wikidata and Commons categories), with photographer and licence kept for display. Every lookup is logged to ~/.cache/musicwell/images.log."""
from __future__ import annotations

import difflib
import json
import os
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from musicwell import __version__

# Wikimedia and MusicBrainz want a descriptive user agent; vague ones get rate-limited sooner
USER_AGENT = (f"Musicwell{'/' + __version__ if __version__ else ''} "
              "(https://github.com/bobwellapps; Linux desktop music player) Python-urllib")
TIMEOUT = 10

# for tests, e.g. {"https://musicbrainz.org": "http://127.0.0.1:9999/mb"}
BASE_OVERRIDES: dict[str, str] = {}

ALBUM_SOURCES = {
    "caa": "Cover Art Archive (MusicBrainz)",
}
ARTIST_SOURCES = {
    "wikipedia": "Wikipedia (free photos)",
    "wikidata": "Wikidata (via MusicBrainz)",
    "commons": "Wikimedia Commons (the artist's photo category)",
    "wikis": "Wikipedia in other languages",
}
DEFAULT_ALBUM_ORDER = ["caa"]
DEFAULT_ARTIST_ORDER = ["wikipedia", "wikidata", "commons", "wikis"]
REMOVED_SOURCES = ("itunes", "deezer", "apple", "audiodb", "fanarttv", "openverse")


@dataclass
class Candidate:
    url: str  # full-size image
    thumb: str  # small preview (may equal url)
    source: str
    label: str = ""  # e.g. "Radiohead — OK Computer"
    credit: str = ""  # e.g. "Photo: Jane Doe", for licences that require credit
    license: str = ""  # e.g. "CC BY-SA 4.0"
    page: str = ""  # page describing the image and its licence

    def info(self) -> dict:
        return {"source": self.source, "credit": self.credit, "license": self.license, "page": self.page,
                "label": self.label}

    @property
    def source_name(self) -> str:
        return ALBUM_SOURCES.get(self.source) or ARTIST_SOURCES.get(self.source) or self.source


def _url(url: str) -> str:
    for base, repl in BASE_OVERRIDES.items():
        if url.startswith(base):
            return repl + url[len(base):]
    return url


_log = None


def log(msg: str):
    """One line in ~/.cache/musicwell/images.log (kept small)."""
    global _log
    if _log is None:
        import logging
        import logging.handlers
        from musicwell.paths import cache_dir
        _log = logging.getLogger("musicwell.images")
        _log.propagate = False
        _log.setLevel(logging.INFO)
        try:
            d = cache_dir()
            d.mkdir(parents=True, exist_ok=True)
            h = logging.handlers.RotatingFileHandler(d / "images.log", maxBytes=300_000, backupCount=1,
                                                     encoding="utf-8")
            h.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%Y-%m-%d %H:%M:%S"))
            _log.addHandler(h)
        except OSError:
            pass
    _log.info(msg)


def _headers(accept: str) -> dict:
    return {"User-Agent": USER_AGENT, "Accept": accept, "Accept-Language": "en"}


class Busy(Exception):
    """A service replied "too many requests"."""


_busy_until: dict[str, float] = {}
BUSY_DEFAULT, BUSY_MIN, BUSY_MAX = 30, 15, 600  # seconds
# steady pace so a full library rescan doesn't trip Wikimedia's rate limit
MIN_GAP = {"Wikimedia": 0.25}
_pace_lock = threading.Lock()
_last_sent: dict[str, float] = {}
_strikes: dict[str, tuple[int, float]] = {}  # group -> (times asked to slow down, last time)


def _pace(group: str):
    gap = MIN_GAP.get(group)
    if not gap:
        return
    with _pace_lock:
        wait = _last_sent.get(group, 0.0) + gap - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_sent[group] = time.monotonic()


def _group(url: str) -> str:
    host = urllib.parse.urlsplit(url).hostname or ""
    if host.endswith(("wikipedia.org", "wikidata.org", "wikimedia.org")):
        return "Wikimedia"  # one limit for all Wikimedia sites
    return host


def busy_for(url: str) -> float:
    """Seconds until the service may be asked again (0 = now)."""
    return max(0.0, _busy_until.get(_group(url), 0.0) - time.time())


def _open(url: str, accept: str):
    group = _group(url)
    if busy_for(url) > 0:
        raise Busy(f"{group} asked Musicwell to slow down")
    req = urllib.request.Request(_url(url), headers=_headers(accept))
    _pace(group)
    try:
        r = urllib.request.urlopen(req, timeout=TIMEOUT)
    except urllib.error.HTTPError as e:
        if e.code == 429 or (e.code == 503 and e.headers.get("Retry-After")):
            # Retry-After if given, else 30 s doubling up to 10 min
            n, last = _strikes.get(group, (0, 0.0))
            n = n + 1 if time.time() - last < 900 else 1
            _strikes[group] = (n, time.time())
            ra = (e.headers.get("Retry-After") or "").strip()
            secs = int(ra) if ra.isdigit() else BUSY_DEFAULT * (2 ** (n - 1))
            secs = min(max(secs, BUSY_MIN), BUSY_MAX)
            _busy_until[group] = time.time() + secs
            log(f"{group}: {e.code} too many requests — waiting {secs} s")
            import logging
            logging.getLogger("musicwell").warning("%s asked Musicwell to slow down (%s) — waiting %d s",
                                                   group, e.code, secs)
            raise Busy(f"{group} asked Musicwell to slow down") from e
        raise
    if group in _strikes:
        _strikes.pop(group, None)  # answering again: reset the backoff
    return r


def get_bytes(url: str, limit: int = 15 * 1024 * 1024) -> bytes:
    with _open(url, "*/*") as r:
        return r.read(limit)


def get_json(url: str):
    with _open(url, "application/json") as r:
        return json.loads(r.read().decode("utf-8", "replace"))


_mb_lock = threading.Lock()
_mb_last = [0.0]


def mb_json(path: str):
    """MusicBrainz allows one request per second."""
    with _mb_lock:
        wait = 1.1 - (time.time() - _mb_last[0])
        if wait > 0:
            time.sleep(wait)
        _mb_last[0] = time.time()
    return get_json("https://musicbrainz.org/ws/2/" + path)


def q(s: str) -> str:
    return urllib.parse.quote(s, safe="")


_PAREN = re.compile(r"\s*[\(\[][^\)\]]*(remaster|deluxe|edition|version|anniversary|expanded|bonus|mono|stereo)[^\)\]]*[\)\]]", re.I)


def norm(s: str) -> str:
    s = _PAREN.sub("", s or "")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = s.lower().replace("&", "and")
    s = re.sub(r"^the\s+", "", s)
    return re.sub(r"[^a-z0-9]+", "", s)


def clean(s: str) -> str:
    """Album name without '(Remastered)', '[Deluxe Edition]' etc., for searching."""
    return re.sub(r"\s+", " ", _PAREN.sub("", s or "")).strip()


def similar(a: str, b: str) -> float:
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def good(a: str, b: str, threshold: float = 0.82) -> bool:
    return similar(a, b) >= threshold


def primary_artist(name: str) -> str:
    return re.split(r"\s+(?:feat\.?|ft\.?|featuring)\s+|;", name or "", flags=re.I)[0].strip()


_mb_ids: dict[str, str | None] = {}


def mb_artist_id(artist: str) -> str | None:
    key = norm(artist)
    if key in _mb_ids:
        return _mb_ids[key]
    _mb_ids[key] = found = _mb_artist_id(artist)
    return found


def _mb_artist_id(artist: str) -> str | None:
    data = mb_json(f"artist/?query=artist:{q(chr(34) + artist + chr(34))}&fmt=json&limit=5")
    for a in data.get("artists", []):
        if good(a.get("name", ""), artist) or any(good(x.get("name", ""), artist) for x in a.get("aliases", []) or []):
            return a["id"]
    return None


def mb_release_groups(artist: str, album: str) -> list[str]:
    query = f'releasegroup:"{album}" AND artist:"{artist}"'
    data = mb_json(f"release-group/?query={q(query)}&fmt=json&limit=8")
    out = []
    for rg in data.get("release-groups", []):
        credit = " ".join(c.get("name", "") + c.get("joinphrase", "") for c in rg.get("artist-credit", []))
        if good(rg.get("title", ""), album) and (good(credit, artist, 0.7) or norm(artist) in norm(credit)):
            out.append(rg["id"])
    return out


def mb_release_groups_via_releases(artist: str, album: str) -> list[str]:
    """Fallback when the album isn't found as a release group."""
    query = f'release:"{album}" AND artist:"{artist}"'
    data = mb_json(f"release/?query={q(query)}&fmt=json&limit=10")
    out = []
    for r in data.get("releases", []):
        credit = " ".join(c.get("name", "") + c.get("joinphrase", "") for c in r.get("artist-credit", []))
        rg = (r.get("release-group") or {}).get("id")
        if rg and rg not in out and good(r.get("title", ""), album) and \
                (good(credit, artist, 0.7) or norm(artist) in norm(credit)):
            out.append(rg)
    return out


def album_caa(artist: str, album: str, **_) -> list[Candidate]:
    groups = mb_release_groups(artist, album) or mb_release_groups_via_releases(artist, album)
    out = []
    for mbid in groups[:4]:
        base = f"https://coverartarchive.org/release-group/{mbid}/front"
        out.append(Candidate(base + "-1200", base + "-250", "caa", f"{artist} — {album}",
                             page=f"https://musicbrainz.org/release-group/{mbid}"))
    return out


# Artist sources: Wikimedia Commons only (all files are freely licensed).

_MUSIC_WORDS = ("band", "singer", "musician", "rapper", "songwriter", "composer", "group", "duo",
                "trio", "dj", "producer", "orchestra", "ensemble", "vocalist", "guitarist", "pianist",
                "music", "artist", "choir", "quartet", "drummer")


def _musical(desc: str) -> bool:
    d = (desc or "").lower()
    return any(re.search(rf"\b{w}", d) for w in _MUSIC_WORDS)


def _plain(html_text: str, limit: int = 90) -> str:
    """Commons gives the author as HTML; keep the text."""
    import html
    t = html.unescape(re.sub(r"<[^>]+>", " ", html_text or ""))
    t = re.sub(r"\s+", " ", t).strip()
    return t if len(t) <= limit else t[:limit - 1].rstrip() + "…"


COMMONS_BIG, COMMONS_SMALL = 1280, 330  # Wikimedia's standard thumbnail widths


def commons_files(names: list[str], label: str) -> list[Candidate]:
    """Candidates for Commons files with author and licence. Files not on Commons (non-free) are skipped."""
    names = [n for n in dict.fromkeys(n.replace("_", " ") for n in names if n)
             if not n.lower().endswith((".svg", ".tif", ".tiff", ".pdf", ".webm", ".ogv"))]
    if not names:
        return []
    titles = "|".join("File:" + n for n in names[:20])
    data = get_json("https://commons.wikimedia.org/w/api.php?action=query&format=json&formatversion=2"
                    f"&prop=imageinfo&iiprop=url%7Cextmetadata&iiurlwidth={COMMONS_BIG}"
                    "&iiextmetadatafilter=Artist%7CLicenseShortName%7CNonFree%7CUsageTerms"
                    "&titles=" + q(titles))
    q_ = data.get("query") or {}
    renamed = {n.get("to"): n.get("from") for n in q_.get("normalized", []) or []}
    by_title = {}
    for pg in q_.get("pages", []) or []:
        info = (pg.get("imageinfo") or [None])[0]
        if pg.get("missing") or not info:
            continue  # not on Commons: not freely licensed
        meta = info.get("extmetadata") or {}
        lic = _plain((meta.get("LicenseShortName") or {}).get("value", ""), 40)
        if str((meta.get("NonFree") or {}).get("value", "")).lower() in ("true", "1") or not lic:
            continue
        big = info.get("thumburl") or info.get("url")
        if not big:
            continue
        small = big.replace(f"/{COMMONS_BIG}px-", f"/{COMMONS_SMALL}px-")
        author = _plain((meta.get("Artist") or {}).get("value", "")) or "Wikimedia Commons contributor"
        by_title[pg.get("title")] = Candidate(big, small, "", label, credit=author, license=lic,
                                              page=info.get("descriptionurl", ""))
        by_title[renamed.get(pg.get("title"))] = by_title[pg.get("title")]
    return [by_title["File:" + n] for n in names if ("File:" + n) in by_title]


def _wiki_pages(params: str) -> list[dict]:
    data = get_json("https://en.wikipedia.org/w/api.php?action=query&format=json&formatversion=2"
                    "&redirects=1&prop=pageimages%7Cdescription&piprop=name&pilicense=free&" + params)
    return (data.get("query") or {}).get("pages") or []


def artist_wikipedia(artist: str, **_) -> list[Candidate]:
    """The photo at the top of the artist's Wikipedia article, if it's a free Commons file."""
    found: list[tuple[str, str]] = []  # (file name, article title)

    def take(pages):
        for pg in pages:
            title = pg.get("title", "")
            base = re.sub(r"\s*\(.*\)$", "", title)  # "Bush (British band)" -> "Bush"
            if pg.get("missing") or not _musical(pg.get("description", "")) or not good(base, artist):
                continue
            if pg.get("pageimage") and pg["pageimage"] not in [f for f, _ in found]:
                found.append((pg["pageimage"], title))

    # 1. exact title and the usual "(band)" / "(musician)" pages
    titles = [artist] + [f"{artist} ({x})" for x in ("band", "musician", "singer", "rapper", "group")]
    take(_wiki_pages("titles=" + q("|".join(titles))))
    # 2. a search
    if not found:
        query = f"{artist} band OR singer OR musician OR rapper OR group"
        take(_wiki_pages(f"generator=search&gsrlimit=6&gsrsearch={q(query)}"))
    out = []
    for fname, title in found[:3]:
        for c in commons_files([fname], title):
            c.source = "wikipedia"
            out.append(c)
    return out


def _wikidata_ids(artist: str) -> list[str]:
    """The artist's Wikidata item: via MusicBrainz, else Wikidata search."""
    ids = []
    try:
        mbid = mb_artist_id(artist)
    except Exception:
        mbid = None
    if mbid:
        data = mb_json(f"artist/{mbid}?inc=url-rels&fmt=json")
        for rel in data.get("relations", []):
            res = (rel.get("url") or {}).get("resource", "")
            if rel.get("type") == "wikidata" and "/wiki/Q" in res:
                ids.append(res.rsplit("/", 1)[-1])
    if not ids:
        data = get_json("https://www.wikidata.org/w/api.php?action=wbsearchentities&format=json"
                        f"&language=en&uselang=en&type=item&limit=7&search={q(artist)}")
        for r in data.get("search", []):
            if good(r.get("label", ""), artist) and _musical(r.get("description", "")):
                ids.append(r["id"])
    return ids[:3]


_wd_cache: dict[str, tuple[float, list]] = {}
_wd_lock = threading.Lock()


def _wikidata_items(artist: str) -> list[tuple[str, dict]]:
    """[(Q-id, entity)] best first, cached for ten minutes."""
    key = norm(artist)
    with _wd_lock:
        hit = _wd_cache.get(key)
        if hit and time.monotonic() - hit[0] < 600:
            return hit[1]
    ids = _wikidata_ids(artist)
    items = []
    if ids:
        data = get_json("https://www.wikidata.org/w/api.php?action=wbgetentities&format=json"
                        "&props=claims%7Csitelinks&ids=" + q("|".join(ids)))
        ents = data.get("entities") or {}
        items = [(i, ents.get(i) or {}) for i in ids]
    with _wd_lock:
        if len(_wd_cache) > 200:
            _wd_cache.clear()
        _wd_cache[key] = (time.monotonic(), items)
    return items


def _claims(entity: dict, prop: str) -> list[str]:
    out = []
    for c in (entity.get("claims") or {}).get(prop, []) or []:
        v = ((c.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if isinstance(v, str) and v:
            out.append(v)
    return out


def artist_wikidata(artist: str, **_) -> list[Candidate]:
    """The artist's Wikidata photo (P18), always a free Commons file."""
    names = [n for _qid, ent in _wikidata_items(artist) for n in _claims(ent, "P18")]
    out = commons_files(names[:4], artist)
    for c in out:
        c.source = "wikidata"
    return out


_PHOTO_EXTS = (".jpg", ".jpeg", ".png", ".webp")
# files in an artist's category that aren't photos of them
_NOT_A_PHOTO = re.compile(r"\b(logo|signature|autograph|poster|flyer|ticket|setlist|set list|map|flag|stamp|"
                          r"cover|sleeve|vinyl|cd|cassette|album|single|record|plaque|grave|tomb|memorial|"
                          r"house|building|street|sign|graffiti|mural|banner|t shirt|merch)\b", re.I)


def _words(s: str) -> list[str]:
    """"The Beach Boys & Friends" -> ["beach", "boys", "and", "friends"]"""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower().replace("&", " and ")
    w = re.findall(r"[a-z0-9]+", s)
    return w[1:] if len(w) > 1 and w[0] == "the" else w


def _not_a_photo(text: str, artist: str) -> bool:
    """A logo, sleeve, poster etc. The artist's own name doesn't count ("Beach House")."""
    text = " ".join(_words(text))
    name = " ".join(_words(artist))
    if name:
        text = text.replace(name, " ")
    return bool(_NOT_A_PHOTO.search(text))


def _category_members(cat: str, artist: str = "") -> tuple[list[str], list[str]]:
    """(photo file names, subcategory names) in a Commons category."""
    data = get_json("https://commons.wikimedia.org/w/api.php?action=query&format=json&formatversion=2"
                    "&list=categorymembers&cmtype=file%7Csubcat&cmlimit=60&cmtitle=" + q("Category:" + cat))
    files, subs = [], []
    for m in (data.get("query") or {}).get("categorymembers", []) or []:
        title = m.get("title") or ""
        if title.startswith("File:"):
            name = title[5:]
            stem = os.path.splitext(name)[0].replace("_", " ")
            if name.lower().endswith(_PHOTO_EXTS) and not _not_a_photo(stem, artist):
                files.append(name)
        elif title.startswith("Category:"):
            subs.append(title[9:])
    return files, subs


def _named_first(names: list[str], artist: str) -> list[str]:
    """Files naming the artist first."""
    want = norm(artist)
    return sorted(names, key=lambda n: 0 if want and want in norm(n) else 1)


def artist_commons(artist: str, **_) -> list[Candidate]:
    """Photos from the artist's Commons category (from Wikidata), for when Wikipedia has none."""
    cats = []
    for _qid, ent in _wikidata_items(artist):
        cats += _claims(ent, "P373")  # "Commons category"
        link = (((ent.get("sitelinks") or {}).get("commonswiki") or {}).get("title") or "")
        if link.startswith("Category:"):
            cats.append(link[9:])
    cats = list(dict.fromkeys(c.replace("_", " ") for c in cats))[:2]
    files: list[str] = []
    for cat in cats:
        found, subs = _category_members(cat, artist)
        files += found
        if len(files) < 4:
            # e.g. "Radiohead in concert": one level down
            subs = sorted(subs, key=lambda c: 0 if re.search(r"concert|live|perform|portrait|photo", c, re.I) else 1)
            for sub in subs[:3]:
                files += _category_members(sub, artist)[0][:8]
                if len(files) >= 8:
                    break
    files = _named_first(list(dict.fromkeys(files)), artist)
    out = commons_files(files[:10], f"{artist} — Wikimedia Commons")
    for c in out:
        c.source = "commons"
    return out[:6]


# tried first; local artists often have a photo only in their own language
WIKI_LANGS = ("de", "fr", "es", "it", "nl", "sv", "pt", "pl", "ja", "ru", "no", "fi", "da", "ko", "zh",
              "ca", "cs", "hu", "tr", "uk", "el", "he", "id", "ro", "simple")
_NOT_WIKIPEDIA = {"en", "commons", "species", "meta", "wikidata", "mediawiki", "sources", "incubator", "outreach"}
MAX_WIKIS = 4  # Wikipedias asked per artist
ENOUGH_PHOTOS = 2


def artist_wikis(artist: str, **_) -> list[Candidate]:
    """Lead photos from other-language Wikipedias, found via Wikidata."""
    links: list[tuple[str, str]] = []
    for _qid, ent in _wikidata_items(artist):
        for site, v in ((ent.get("sitelinks") or {}).items()):
            m = re.fullmatch(r"([a-z_]+)wiki", site or "")
            if not m or m.group(1) in _NOT_WIKIPEDIA or not (v or {}).get("title"):
                continue
            links.append((m.group(1).replace("_", "-"), v["title"]))
    rank = {lang: i for i, lang in enumerate(WIKI_LANGS)}
    links.sort(key=lambda lt: rank.get(lt[0], len(rank)))
    names: list[str] = []
    langs: dict[str, str] = {}
    for lang, title in links[:MAX_WIKIS]:
        try:
            data = get_json(f"https://{lang}.wikipedia.org/w/api.php?action=query&format=json&formatversion=2"
                            "&redirects=1&prop=pageimages&piprop=name&pilicense=free&titles=" + q(title))
        except Busy:
            raise  # Wikimedia wants a rest
        except Exception as e:  # one wiki failing doesn't stop the others
            log(f"artist wikis: {lang} failed — {e}")
            continue
        for pg in (data.get("query") or {}).get("pages", []) or []:
            img = pg.get("pageimage")
            if img and img not in names:
                names.append(img)
                langs[img.replace("_", " ")] = lang
        if len(names) >= ENOUGH_PHOTOS:
            break
    out = commons_files(names, artist)
    for c in out:
        c.source = "wikis"
        name = urllib.parse.unquote(c.page.rsplit("File:", 1)[-1]).replace("_", " ") if "File:" in c.page else ""
        if langs.get(name):
            c.label = f"{artist} — {langs[name]}.wikipedia.org"
    return out


ALBUM_FUNCS = {"caa": album_caa}
ARTIST_FUNCS = {"wikipedia": artist_wikipedia, "wikidata": artist_wikidata, "commons": artist_commons,
                "wikis": artist_wikis}


def search_verbose(kind: str, source: str, artist: str, album: str = "") -> tuple[list[Candidate], str]:
    """One source -> (candidates, problem). Never raises; problem is "" on success."""
    artist, album = primary_artist(artist), clean(album)
    what = f"{kind} {source}: {artist}" + (f" — {album}" if album else "")
    try:
        funcs = ALBUM_FUNCS if kind == "album" else ARTIST_FUNCS
        if source not in funcs:
            return [], "unknown source"
        found = funcs[source](artist, album) if kind == "album" else funcs[source](artist)
        log(f"{what}: {len(found)} found")
        return found, ""
    except Busy:
        problem = "busy (too many requests) — Musicwell will try again in a few minutes"
    except urllib.error.HTTPError as e:
        problem = f"the service answered {e.code} {e.reason}"
    except urllib.error.URLError as e:
        problem = f"couldn't connect ({e.reason})"
    except TimeoutError:
        problem = "no answer (timed out)"
    except Exception as e:  # e.g. a changed reply format
        problem = f"{type(e).__name__}: {e}"
    log(f"{what}: FAILED — {problem}")
    return [], problem


def search(kind: str, source: str, artist: str, album: str = "") -> list[Candidate]:
    """One source; never raises."""
    return search_verbose(kind, source, artist, album)[0]


def is_image(data: bytes) -> bool:
    return data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n" or data[:4] == b"RIFF" \
        or data[:6] in (b"GIF87a", b"GIF89a")


def find_first(kind: str, order: list[str], artist: str, album: str = "",
               problems: list | None = None) -> tuple[bytes, Candidate] | None:
    """Try sources in order and return the first image that downloads. Sources that couldn't be asked go into `problems`."""
    for source in order:
        cands, problem = search_verbose(kind, source, artist, album)
        if problem and problems is not None:
            problems.append(f"{source}: {problem}")
        for cand in cands[:3]:
            try:
                data = get_bytes(cand.url)
            except Exception as e:
                log(f"{kind} {source}: download failed {cand.url} — {e}")
                if problems is not None:
                    problems.append(f"{source}: download failed")
                continue
            if is_image(data) and len(data) > 1000:
                return data, cand
            log(f"{kind} {source}: not an image {cand.url}")
    log(f"{kind}: nothing found for {artist}" + (f" — {album}" if album else ""))
    return None
