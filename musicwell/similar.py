"""Find similar: songs, artists, stations and free music like the one you pick, from your library and ListenBrainz."""
from __future__ import annotations

import hashlib
import json
import re
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Signal

from musicwell import artsources as S
from musicwell.paths import cache_dir

LABS_URL = "https://labs.api.listenbrainz.org/similar-artists/json"
# ListenBrainz Labs data versions, longest history first. Later ones are fallbacks if one is retired.
ALGORITHMS = [
    "session_based_days_7500_session_300_contribution_5_threshold_10_limit_100_filter_True_skip_30",
    "session_based_days_7500_session_300_contribution_3_threshold_10_limit_100_filter_True_skip_30",
    "session_based_days_1825_session_300_contribution_3_threshold_10_limit_100_filter_True_skip_30",
]
CACHE_DAYS = 30
SESSION_GAP = 45 * 60  # plays further apart than this are separate sessions


@dataclass
class Result:
    seed_label: str = ""
    seed_kind: str = "track"
    tracks: list = field(default_factory=list)  # track ids, best first, artists spread out
    artists: list = field(default_factory=list)  # (name, similarity 0-1, songs you have)
    suggestions: list = field(default_factory=list)  # (name, musicbrainz id, similarity 0-1)
    used_online: bool = False
    problem: str = ""  # why ListenBrainz couldn't help
    stations: list = field(default_factory=list)  # station dicts, best first
    station_basis: list = field(default_factory=list)  # genres they were matched on
    station_problem: str = ""
    stations_pending: bool = False
    archive: list = field(default_factory=list)  # Internet Archive items
    archive_pending: bool = False
    archive_problem: str = ""


def _tagkey(g: str) -> str:
    """'Synth-Pop' / 'synth pop' -> 'synthpop'"""
    return re.sub(r"[^a-z0-9]+", "", (g or "").lower())


def _genres(text: str) -> set[str]:
    return {k for k in (_tagkey(g) for g in re.split(r"[;,/|]", text or "")) if k}


def _artist_of(t: dict) -> str:
    return S.primary_artist(t.get("artist_key") or t.get("artist") or "")


def _mbid_from_tags(t: dict) -> str:
    extra = t.get("_extra") or {}
    for k in ("musicbrainz_artistid", "musicbrainz_artist_id", "musicbrainz_albumartistid",
              "musicbrainz_album_artist_id"):
        v = extra.get(k)
        if v:
            m = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", str(v).lower())
            if m:
                return m.group(0)
    return ""


def similar_artists_online(artist: str, mbid: str = "") -> list[tuple[str, str, float]]:
    """[(name, mbid, 0-1)] from ListenBrainz, cached for a month. Raises on network errors."""
    key = hashlib.sha1((mbid or S.norm(artist)).encode()).hexdigest()[:20]
    d = cache_dir() / "similar"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{key}.json"
    if p.exists() and time.time() - p.stat().st_mtime < CACHE_DAYS * 86400:
        try:
            return [tuple(x) for x in json.loads(p.read_text(encoding="utf-8"))]
        except (OSError, ValueError):
            pass
    if not mbid:
        mbid = S.mb_artist_id(artist) or ""
    out: list[tuple[str, str, float]] = []
    if mbid:
        rows, last = None, None
        for algo in ALGORITHMS:
            try:
                rows = S.get_json(f"{LABS_URL}?artist_mbids={mbid}&algorithm={algo}")
                break
            except Exception as e:  # 400: that data version is gone, try the next
                last = e
                if getattr(e, "code", 0) != 400:
                    raise
        if rows is None and last:
            raise last
        out = _parse_labs(rows, mbid)
    try:
        p.write_text(json.dumps(out), encoding="utf-8")
    except OSError:
        pass
    S.log(f"similar {artist}: {len(out)} similar artists from ListenBrainz" + ("" if mbid else " (no MusicBrainz ID)"))
    return out


def artist_genres(artist: str, mbid: str = "") -> list[str]:
    """The artist's MusicBrainz genres, most votes first (cached for a month)."""
    key = hashlib.sha1(("genres|" + (mbid or S.norm(artist))).encode()).hexdigest()[:20]
    d = cache_dir() / "similar"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{key}.json"
    if p.exists() and time.time() - p.stat().st_mtime < CACHE_DAYS * 86400:
        try:
            return list(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
    if not mbid:
        mbid = S.mb_artist_id(artist) or ""
    out: list[str] = []
    if mbid:
        data = S.mb_json(f"artist/{mbid}?inc=genres+tags&fmt=json")
        found: dict[str, int] = {}
        for g in (data.get("genres") or []):
            if g.get("name"):
                found[g["name"].lower()] = found.get(g["name"].lower(), 0) + int(g.get("count") or 1)
        if not found:  # free-form tags only when there are no genres
            for t in (data.get("tags") or []):
                name = (t.get("name") or "").lower()
                if name and int(t.get("count") or 0) > 0 and len(name) < 30 and name not in _NOT_GENRES:
                    found[name] = found.get(name, 0) + int(t.get("count") or 1)
        out = [n for n, _ in sorted(found.items(), key=lambda kv: -kv[1])][:8]
    try:
        p.write_text(json.dumps(out), encoding="utf-8")
    except OSError:
        pass
    return out


_NOT_GENRES = {"seen live", "favorite", "favorites", "favourite", "favourites", "awesome", "love", "beautiful",
               "male vocalists", "female vocalists", "check out", "under 2000 listeners", "spotify"}


def similar_stations(directory, tags: list[tuple[str, float]], exclude: str = "", limit: int = 40) -> list[dict]:
    """Stations whose tags best match [(tag, weight)], popular first among equals."""
    want: dict[str, float] = {}
    order = []
    for t, wgt in tags:
        k = _tagkey(t)
        if k and k not in want:
            want[k] = wgt
            order.append(t.strip().lower())
        elif k:
            want[k] = max(want[k], wgt)
    if not want:
        return []
    found: dict[str, tuple[float, int, dict]] = {}
    rank = 0
    per_tag = max(60, limit + limit // 2)  # enough to fill the list after duplicates
    for t in order[:4]:
        for st in directory.search(tag=t, order="clickcount", limit=per_tag):
            rank += 1
            if st["uuid"] == exclude or st["uuid"] in found:
                continue
            st_tags = {_tagkey(x) for x in st.get("tags", "").split(",")}
            score = sum(w for k, w in want.items() if k in st_tags or any(k in x and len(k) >= 4 for x in st_tags))
            if score > 0:
                found[st["uuid"]] = (score, rank, st)
    seen_names = set()
    out = []
    for score, rank, st in sorted(found.values(), key=lambda x: (-x[0], x[1])):
        key = S.norm(st["name"])
        if key in seen_names:  # same station listed twice
            continue
        seen_names.add(key)
        out.append(st)
        if len(out) >= limit:
            break
    return out


def cache_files() -> list:
    d = cache_dir() / "similar"
    return [p for p in d.iterdir() if p.suffix == ".json"] if d.is_dir() else []


def clear_cache() -> int:
    n = 0
    for p in cache_files():
        try:
            p.unlink()
            n += 1
        except OSError:
            pass
    return n


def _parse_labs(rows, seed_mbid: str) -> list[tuple[str, str, float]]:
    """Some Labs versions wrap the rows as {"data": [...]}."""
    flat = []

    def walk(x):
        if isinstance(x, list):
            for y in x:
                walk(y)
        elif isinstance(x, dict):
            if "artist_mbid" in x and "name" in x:
                flat.append(x)
            elif isinstance(x.get("data"), list):
                walk(x["data"])
    walk(rows)
    flat = [r for r in flat if r.get("artist_mbid") != seed_mbid]
    if not flat:
        return []
    top = max(float(r.get("score") or 0) for r in flat) or 1.0
    return [(r["name"], r["artist_mbid"], round(float(r.get("score") or 0) / top, 4)) for r in flat]


class SimilarFinder(QObject):
    ready = Signal(int, object)  # request number, Result
    stationsReady = Signal(int, object)  # same Result with stations
    archiveReady = Signal(int, object)  # same Result with Internet Archive items

    def __init__(self, library, parent=None):
        super().__init__(parent)
        self.library = library
        self.online = True
        self.directory = None  # radio directory, for similar stations
        self.archive = True
        self.openverse = True
        self.audius = True
        self.station_limit = 40
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="musicwell-similar")
        self._n = 0

    def find(self, track: dict | None = None, artist: str = "", stations: bool = True) -> int:
        """Find music like this song or artist. Answers through `ready`."""
        self._n += 1
        n = self._n
        tracks = list(self.library.tracks.values())
        plays = self._sessions_with(artist or (_artist_of(track) if track else ""))
        online = self.online
        seed = dict(track) if track else None
        directory = self.directory if stations else None
        sources = [x for x, on in (("ia", self.archive), ("ov", self.openverse), ("au", self.audius))
                   if on] if stations else []
        archive = bool(sources)

        def work():
            res = compute(tracks, seed, artist, plays, online)
            res.stations_pending = directory is not None
            res.archive_pending = archive
            self.ready.emit(n, res)  # songs first, they're quick
            if directory is not None:
                add_stations(res, directory, seed, artist, tracks, online, self.station_limit)
                res.stations_pending = False
                self.stationsReady.emit(n, res)
            if archive:
                add_archive(res, seed, artist, sources)
                res.archive_pending = False
                self.archiveReady.emit(n, res)
        self.pool.submit(work)
        return n

    def _sessions_with(self, artist: str) -> dict[str, int]:
        """How often each artist was played in the same session as `artist`."""
        key = S.norm(artist)
        if not key:
            return {}
        try:
            history = self.library.plays_since(0)
        except Exception:
            return {}
        sessions, cur, last = [], [], 0.0
        for h in history:
            if cur and h["played_at"] - last > SESSION_GAP:
                sessions.append(cur)
                cur = []
            cur.append(S.norm(S.primary_artist(h.get("albumartist") or h.get("artist") or "")))
            last = h["played_at"]
        if cur:
            sessions.append(cur)
        together: dict[str, int] = defaultdict(int)
        for sess in sessions:
            if key in sess:
                for a in set(sess):
                    if a and a != key:
                        together[a] += 1
        return dict(together)

    def shutdown(self):
        self.pool.shutdown(wait=False, cancel_futures=True)


def compute(tracks: list[dict], seed: dict | None, artist: str, together: dict[str, int],
            online: bool) -> Result:
    """Score every song in the library against the seed. Runs in a background thread."""
    seed_artist = S.primary_artist(artist) if artist else (_artist_of(seed) if seed else "")
    stream = bool(seed and seed.get("stream"))
    res = Result(seed_kind="radio" if stream else "artist" if (artist and not seed) else "track")
    if stream:
        st = seed["station"]
        res.seed_label = (f"“{seed['title']}” by {seed_artist} on {st['name']}" if seed_artist else st["name"])
    else:
        res.seed_label = (f"“{seed['title']}” by {seed_artist or 'Unknown Artist'}" if seed and not artist
                          else seed_artist or "this artist")
    seed_key = S.norm(seed_artist)
    by_artist: dict[str, list[dict]] = defaultdict(list)
    names: dict[str, str] = {}
    for t in tracks:
        a = _artist_of(t)
        k = S.norm(a)
        if k:
            by_artist[k].append(t)
            names.setdefault(k, a)
    seed_tracks = by_artist.get(seed_key, [])
    # seed genres: the song's, or the artist's most common
    if stream:
        seed_genres = _genres(seed["station"].get("tags", ""))
        seed_year = 0
        if seed_tracks:
            for t in seed_tracks:
                seed_genres |= _genres(t.get("genre", ""))
    elif seed and not artist:
        seed_genres = _genres(seed.get("genre", ""))
        seed_year = seed.get("year") or 0
    else:
        counts: dict[str, int] = defaultdict(int)
        years = []
        for t in seed_tracks:
            for g in _genres(t.get("genre", "")):
                counts[g] += 1
            if t.get("year"):
                years.append(t["year"])
        seed_genres = {g for g, c in counts.items() if c >= max(1, len(seed_tracks) // 4)}
        seed_year = sorted(years)[len(years) // 2] if years else 0

    # ListenBrainz: artists people play with this one
    lb: dict[str, float] = {}
    if online and seed_artist:
        mbid = _mbid_from_tags(seed) if seed else ""
        if not mbid and seed_tracks:
            mbid = next((m for m in (_mbid_from_tags(t) for t in seed_tracks[:20]) if m), "")
        try:
            sims = similar_artists_online(seed_artist, mbid)
            res.used_online = True
            for name, amb, score in sims:
                k = S.norm(name)
                lb[k] = max(lb.get(k, 0.0), score)
                if k not in by_artist and k != seed_key:
                    res.suggestions.append((name, amb, score))
            if not sims:
                res.problem = "ListenBrainz doesn't know this artist well enough yet."
        except Exception as e:
            res.problem = f"Couldn't reach ListenBrainz ({type(e).__name__}); using your library only."
    res.suggestions = res.suggestions[:30]

    top_together = max(together.values()) if together else 0
    scored = []
    for k, ts in by_artist.items():
        a_lb = lb.get(k, 0.0)
        a_tog = (together.get(k, 0) / top_together) if top_together else 0.0
        same = k == seed_key
        for t in ts:
            if seed and t.get("id") == seed.get("id"):
                continue
            if not seed_artist and not seed_genres:
                continue
            g = _genres(t.get("genre", ""))
            genre = (len(g & seed_genres) / len(g | seed_genres)) if (g and seed_genres) else 0.0
            era = 0.0
            if seed_year and t.get("year"):
                era = max(0.0, 1.0 - abs(t["year"] - seed_year) / 15.0)
            score = (1.0 * a_lb + 0.45 * genre + 0.35 * a_tog + 0.12 * era
                     + (0.5 if same and res.seed_kind == "track" else 0.25 if same else 0.0)
                     + 0.02 * (t.get("rating") or 0) / 5)
            if score >= 0.2 or (a_lb > 0 and score >= 0.12):
                scored.append((score, t))
    scored.sort(key=lambda x: -x[0])

    # similar artists you have
    best: dict[str, tuple[float, int]] = {}
    for score, t in scored:
        k = S.norm(_artist_of(t))
        if k == seed_key:
            continue
        s0, n0 = best.get(k, (0.0, 0))
        best[k] = (max(s0, score), n0 + 1)
    top = max((s for s, _ in best.values()), default=1.0) or 1.0
    res.artists = sorted(((names[k], round(min(1.0, s / top), 3), n) for k, (s, n) in best.items()),
                         key=lambda x: -x[1])[:40]

    # at most 4 songs per artist, never two in a row
    per: dict[str, int] = defaultdict(int)
    picked = []
    for score, t in scored:
        k = S.norm(_artist_of(t))
        if per[k] >= 4:
            continue
        per[k] += 1
        picked.append(t)
        if len(picked) >= 120:
            break
    res.tracks = [t["id"] for t in _spread(picked)]
    return res


def _spread(tracks: list[dict]) -> list[dict]:
    """Keep the order roughly, but avoid the same artist twice in a row."""
    out, rest = [], list(tracks)
    while rest:
        last = S.norm(_artist_of(out[-1])) if out else None
        i = next((k for k, t in enumerate(rest[:12]) if S.norm(_artist_of(t)) != last), 0)
        out.append(rest.pop(i))
    return out


def add_stations(res: Result, directory, seed: dict | None, artist: str, tracks: list[dict], online: bool,
                 limit: int = 40):
    """Fill res.stations: like the station playing, or playing music like the seed."""
    tags: list[tuple[str, float]] = []
    exclude = ""
    name = S.primary_artist(artist) if artist else (_artist_of(seed) if seed else "")
    if seed and seed.get("stream"):
        st = seed["station"]
        exclude = st["uuid"]
        for i, t in enumerate(x for x in st.get("tags", "").split(", ") if x):
            if i < 5:
                tags.append((t, 1.0 - i * 0.1))  # the first tags matter most
    elif seed:
        for t in re.split(r"[;,/|]", seed.get("genre", "") or ""):
            if t.strip():
                tags.append((t.strip(), 0.9))
    elif name:
        key = S.norm(name)
        counts: dict[str, int] = defaultdict(int)
        for t in tracks:
            if S.norm(_artist_of(t)) == key:
                for g in re.split(r"[;,/|]", t.get("genre", "") or ""):
                    if g.strip():
                        counts[g.strip()] += 1
        tags += [(g, 0.9) for g, _ in sorted(counts.items(), key=lambda kv: -kv[1])[:3]]
    if online and name:
        mbid = _mbid_from_tags(seed) if (seed and not seed.get("stream")) else ""
        try:
            genres = artist_genres(name, mbid)
            # the artist's own genres lead
            tags = [(g, 1.2 - i * 0.08) for i, g in enumerate(genres[:5])] + tags
        except Exception:
            pass
    try:
        res.stations = similar_stations(directory, tags, exclude, limit)
        res.station_basis = list(dict.fromkeys(t.lower() for t, _ in tags))[:6]
        if not res.stations:
            res.station_problem = ("No stations matched — this artist has no genres on MusicBrainz yet."
                                   if not tags else "No stations with these genres were found.")
    except Exception as e:
        res.station_problem = f"Couldn't reach the radio directory ({type(e).__name__})."


def add_archive(res: Result, seed: dict | None, artist: str, sources=("ia", "ov")):
    """Fill res.archive with free music by the artist, similar artists and genre."""
    from musicwell import ia, ov
    name = S.primary_artist(artist) if artist else (_artist_of(seed) if seed else "")
    others = [a for a, _, _ in res.artists[:6]] + [a for a, _, _ in res.suggestions[:8]]
    genres = list(res.station_basis)
    if not genres and seed:
        src = seed["station"].get("tags", "") if seed.get("stream") else seed.get("genre", "")
        genres = [g.strip() for g in re.split(r"[;,/|]", src or "") if g.strip()]
    scored, problems = [], []
    if "ia" in sources:
        try:
            scored += ia.similar_scored(name, others, genres)
        except Exception as e:
            problems.append(f"couldn't reach the Internet Archive ({type(e).__name__})")
    if "ov" in sources:
        try:
            scored += ov.similar_items(name, others, genres)
        except ov.Busy:
            problems.append("Openverse is busy (too many searches just now) — try again in a minute")
        except Exception as e:
            problems.append(f"couldn't reach Openverse ({type(e).__name__})")
    if "au" in sources:
        from musicwell import audius
        try:
            scored += audius.similar_items(name, others, genres)
        except Exception as e:
            problems.append(f"couldn't reach Audius ({type(e).__name__})")
    # best first; alternate sources among equals
    scored.sort(key=lambda x: -x[0])
    per: dict[str, int] = defaultdict(int)
    out = []
    playing = seed["item"]["identifier"] if (seed and seed.get("remote")) else ""
    for score, it in scored:
        k = (it.get("creator") or "").lower()
        if it["identifier"] == playing or per[k] >= 5:  # skip the one playing
            continue
        per[k] += 1
        out.append(it)
    res.archive = out[:60]
    if problems:
        res.archive_problem = "Online sources: " + "; ".join(problems) + "."
    elif not res.archive:
        res.archive_problem = "Nothing matched in online sources — try the search above."
