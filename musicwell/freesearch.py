"""Re-rank loose online search results (Internet Archive, Openverse) to fit the query."""
from __future__ import annotations

import math
import re
import unicodedata

FIELDS = [("any", "Anything"), ("artist", "Artist"), ("title", "Song title"), ("album", "Album"),
          ("genre", "Genre")]
STOP = {"the", "a", "an", "and", "of", "feat", "ft", "featuring", "with", "by", "&", "vs", "le", "la", "les",
        "el", "los", "der", "die", "das"}
_PREFIX = re.compile(r"(?i)^\s*(artist|by|title|song|album|genre|tag)\s*:\s*(.+)$")


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode("ascii").lower()
    return " ".join(re.findall(r"[a-z0-9]+", s))


def words(s: str) -> list[str]:
    w = norm(s).split()
    keep = [x for x in w if x not in STOP]
    return keep or w


def parse(text: str, field: str = "any") -> tuple[str, str]:
    """('artist:Kestrel', 'any') -> ('Kestrel', 'artist')"""
    m = _PREFIX.match(text or "")
    if m:
        key = m.group(1).lower()
        field = {"by": "artist", "song": "title", "tag": "genre"}.get(key, key)
        text = m.group(2).strip().strip('"').strip()
    return text.strip(), field if field in dict(FIELDS) else "any"


def _fields(it: dict) -> dict[str, str]:
    title = it.get("title") or ""
    album = it.get("album") or (title if it.get("kind") == "ia" else "")
    return {"artist": norm(it.get("creator") or it.get("artist") or ""),
            "title": norm(title),
            "album": norm(album),
            "genre": norm(" ; ".join(it.get("subjects") or [])
                          + " " + (it.get("genre") or ""))}


def _cover(qw: list[str], text: str) -> float:
    """Share of the query's words found in text (0..1), whole words or prefixes."""
    if not qw or not text:
        return 0.0
    tw = text.split()
    hit = 0
    for w in qw:
        if w in tw or (len(w) >= 4 and any(t.startswith(w) for t in tw)):
            hit += 1
    return hit / len(qw)


def score(it: dict, query: str, field: str = "any") -> tuple[float, float]:
    """(score, coverage). Coverage is the share of query words found in the chosen fields."""
    q = norm(query)
    qw = words(query)
    f = _fields(it)
    weights = {"artist": 1.0, "title": 0.9, "album": 0.75, "genre": 0.6}
    look = [field] if field != "any" else list(weights)
    best = 0.0
    for k in look:
        t = f[k]
        if not t:
            continue
        c = _cover(qw, t)
        s = c * 60
        if q and t == q:
            s += 40  # exact match
        elif q and len(q) > 2 and re.search(r"(^| )" + re.escape(q) + r"( |$)", t):
            s += 25  # whole phrase in order
        best = max(best, s * weights[k] / (1.0 if field != "any" else 1.0))
    # across fields, e.g. artist + title
    joined = " ".join(f[k] for k in look)
    coverage = _cover(qw, joined)
    best = max(best, coverage * 45)
    pop = math.log10(1 + (it.get("downloads") or 0)) * 1.5  # small boost for popular items
    return best + pop, coverage


def rank(items: list[dict], query: str, field: str = "any", strict: bool = True, min_seconds: int = 0,
         no_live: bool = False) -> tuple[list[dict], list[dict]]:
    """(matches best first, the rest set aside)"""
    seen, scored, aside = set(), [], []
    for i, it in enumerate(items):
        # same song from two sources: keep one
        key = (norm(it.get("creator") or ""), norm(it.get("title") or ""), "item" if it.get("kind") == "ia" else "song")
        if key in seen:
            continue
        seen.add(key)
        if min_seconds and it.get("length") and it["length"] < min_seconds:
            aside.append(it)  # short clip, jingle or sound effect
            continue
        if no_live and it.get("live"):
            aside.append(it)
            continue
        s, cov = score(it, query, field)
        if it.get("kind") == "src":
            s += 5
        if strict and cov < 1.0:
            aside.append(it)
            continue
        if not strict and cov < 0.5:
            aside.append(it)
            continue
        scored.append((-s, i, it))
    scored.sort(key=lambda x: (x[0], x[1]))
    return [it for _s, _i, it in scored], aside
