"""Quod Libet-style search.

    beatles                 any of title/artist/album/genre contains "beatles"
    "dark side"             phrase
    artist=bowie            field contains (also artist:bowie)
    artist="queen"          field equals exactly (case-insensitive)
    genre=jazz|blues        either value
    !live  -live            negate any term
    year>1990  rating>=4    numeric comparisons (=, !=, <, <=, >, >=)
    #(plays = 0)            Quod Libet numeric syntax
    #(added < 30 days)      added / lastplayed within a time span
    #(length > 6:00)        durations as m:ss
All terms must match.
"""
from __future__ import annotations

import re
import time

TEXT_FIELDS = {
    "title": "title", "artist": "artist", "album": "album", "albumartist": "albumartist",
    "genre": "genre", "composer": "composer", "format": "format", "codec": "format", "path": "path",
    "file": "path", "filename": "path",
}
NUM_FIELDS = {
    "year": "year", "date": "year", "track": "track", "tracknumber": "track", "disc": "disc",
    "rating": "rating", "plays": "playcount", "playcount": "playcount", "skips": "skipcount",
    "skipcount": "skipcount", "length": "length", "bitrate": "bitrate",
    "samplerate": "samplerate", "added": "added", "lastplayed": "lastplayed",
}
TIME_FIELDS = {"added", "lastplayed"}

# fields plain words search in (Settings -> Search)
PLAIN_CHOICES = [("title", "Title"), ("artist", "Artist"), ("album", "Album"), ("albumartist", "Album artist"),
                 ("genre", "Genre"), ("composer", "Composer"), ("other", "Comment, label, mood, grouping"),
                 ("path", "File name and folder")]
DEFAULT_PLAIN = ["title", "artist", "album", "albumartist", "genre", "composer", "other"]
PLAIN_FIELDS: list | None = None  # None = everything except the file name
_OTHER = ("comment", "label", "mood", "grouping")


def set_plain_fields(keys):
    global PLAIN_FIELDS
    keys = [k for k in (keys or []) if k in dict(PLAIN_CHOICES)]
    PLAIN_FIELDS = None if (not keys or sorted(keys) == sorted(DEFAULT_PLAIN)) else keys


def _plain_text(t) -> str:
    if PLAIN_FIELDS is None:
        return t["_text"]
    out = []
    for k in PLAIN_FIELDS:
        if k == "other":
            out += [str(t.get(x) or "") for x in _OTHER]
        else:
            out.append(str(t.get(k) or ""))
    return " ".join(out).lower()

_TOKEN = re.compile(r'[!-]?#\([^)]*\)|[!-]?[\w]+(?:[:=])"[^"]*"|[!-]?"[^"]*"|\S+')
_NUM_EXPR = re.compile(r"^(\w+)\s*(<=|>=|!=|=|<|>)\s*(.+)$")
_OPS = {
    "=": lambda a, b: a == b, "!=": lambda a, b: a != b, "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b, ">": lambda a, b: a > b, ">=": lambda a, b: a >= b,
}
_UNITS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400, "week": 604800,
          "month": 2592000, "year": 31536000}


def _parse_number(text: str, field: str):
    text = text.strip().lower()
    if field in TIME_FIELDS:
        m = re.match(r"(\d+(?:\.\d+)?)\s*([a-z]+?)s?$", text)
        if m and m.group(2) in _UNITS:
            return float(m.group(1)) * _UNITS[m.group(2)]
    if ":" in text:
        secs = 0.0
        for part in text.split(":"):
            secs = secs * 60 + float(part)
        return secs
    return float(text)


def _find_field(name: str):
    """Find a field by key, custom tag, display name or tag name."""
    from musicwell import fields as F
    f = F.get(name) or F.get("x:" + name)
    if f:
        return f
    for f in F.all_fields():
        if name in (f.name.lower().replace(" ", ""), F.original_name(f.key).lower().replace(" ", "")) \
                or name in f.tags:
            return f
    return None


def _to_float(v) -> float:
    m = re.match(r"\s*([-+]?\d+(?:\.\d+)?)", str(v))
    return float(m.group(1)) if m else 0.0


def _num_getter(name: str):
    """(getter, is_time) for a numeric field, or None."""
    if name in NUM_FIELDS:
        key = NUM_FIELDS[name]
        return (lambda t, k=key: t.get(k) or 0), key in TIME_FIELDS
    f = _find_field(name)
    if f is not None:
        if f.numeric:
            return (lambda t, f=f: f.get(t) or 0), f.kind == "date"
        return (lambda t, f=f: _to_float(f.get(t))), False
    from musicwell.tags import norm_tag
    tag = norm_tag(name)
    return (lambda t, g=tag: _to_float(t.get("_extra", {}).get(g, ""))), False


def _text_getter(name: str):
    if name in TEXT_FIELDS:
        key = TEXT_FIELDS[name]
        return lambda t, k=key: t.get(k) or ""
    f = _find_field(name)
    if f is not None:
        return lambda t, f=f: str(f.get(t) or "")
    from musicwell.tags import norm_tag
    tag = norm_tag(name)  # any tag in the file works, even without a column
    return lambda t, g=tag: t.get("_extra", {}).get(g, "")


def _numeric(field: str, op: str, value: str):
    get, is_time = _num_getter(field)
    n = _parse_number(value, "added" if is_time else field)
    cmp = _OPS[op]
    if is_time:
        # "added < 30 days" means less than 30 days ago
        flipped = {"<": ">", "<=": ">=", ">": "<", ">=": "<="}.get(op, op)
        cmp = _OPS[flipped]
        return lambda t: bool(get(t)) and cmp(get(t), time.time() - n)
    return lambda t: cmp(get(t), n)


def _term(token: str):
    neg = token[:1] in "!-" and len(token) > 1
    if neg:
        token = token[1:]

    # Half-typed terms ("year>", "#(plays") match everything until finished.
    if (token.startswith("#(") and not token.endswith(")")) or re.fullmatch(r"[<>=!]+[\d.:]*|\)", token) \
            or re.fullmatch(r"(\w+)\s*(<=|>=|!=|<|>|=|:)\s*", token):
        return lambda t: True

    pred = None
    if token.startswith("#(") and token.endswith(")"):
        m = _NUM_EXPR.match(token[2:-1].strip())
        if m:
            try:
                pred = _numeric(m.group(1).lower(), m.group(2), m.group(3))
            except ValueError:
                pred = None
    if pred is None:
        m = _NUM_EXPR.match(token)
        # field<number etc. ("=" with a number only for numeric fields)
        if m and m.group(2) != "=" or (m and (m.group(1).lower() in NUM_FIELDS or
                                              (_find_field(m.group(1).lower()) or _NOFIELD).numeric)):
            try:
                pred = _numeric(m.group(1).lower(), m.group(2), m.group(3))
            except ValueError:
                pred = None
    if pred is None:
        m = re.match(r"^(\w+)[:=](.*)$", token)
        if m:
            get = _text_getter(m.group(1).lower())
            raw = m.group(2)
            if len(raw) >= 2 and raw.startswith('"') and raw.endswith('"'):
                exact = {raw[1:-1].lower()}
                pred = lambda t, g=get, e=exact: g(t).lower() in e
            else:
                alts = [a for a in raw.lower().split("|") if a]
                pred = lambda t, g=get, a=alts: any(x in g(t).lower() for x in a) if a else True
    if pred is None:
        text = token.strip('"').lower()
        alts = [a for a in text.split("|") if a] or [""]
        pred = lambda t, a=alts: any(x in _plain_text(t) for x in a)
    return (lambda t: not pred(t)) if neg else pred


class _NoField:
    numeric = False


_NOFIELD = _NoField()


def compile_query(text: str):
    """Return predicate(track) -> bool, or None for an empty query."""
    text = text.strip()
    if not text:
        return None
    preds = []
    for tok in _TOKEN.findall(text):
        try:
            preds.append(_term(tok))
        except (ValueError, ZeroDivisionError):
            continue
    if not preds:
        return None
    return lambda t: all(p(t) for p in preds)
