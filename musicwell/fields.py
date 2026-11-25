"""Every field Musicwell can show for a song, used by the song list, browser, search and panel."""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass

# Kinds: text, int, num (shown as written, e.g. "-7.42 dB"), dur (s), date (timestamp), rating, size (bytes), rate (Hz), bitrate.
NUMERIC = {"int", "num", "dur", "date", "rating", "size", "rate", "bitrate"}


@dataclass
class Field:
    key: str
    name: str
    group: str  # Basic / Tags / Audio & file / Library / Custom
    kind: str = "text"
    width: int = 140
    visible: bool = False  # shown in the song list by default
    browsable: bool = False  # can be a browser column
    tags: tuple = ()  # extra tag names to read, in order of preference
    header: str = ""  # defaults to name
    plural: str = ""
    custom: bool = False

    @property
    def title(self) -> str:
        return self.header or self.name

    @property
    def plural_name(self) -> str:
        return self.plural or (self.name[:-1] + "ies" if self.name.endswith("y") and not self.name.endswith("ey")
                               else self.name + "s")

    @property
    def unknown(self) -> str:
        return f"Unknown {self.name}" if self.group in ("Basic",) else f"No {self.name}"

    @property
    def numeric(self) -> bool:
        return self.kind in NUMERIC

    def get(self, t: dict):
        """Raw value for a track ('' or 0 when missing)."""
        if self.tags:
            if self.key in t and not self.custom:
                return t[self.key]
            extra = t.get("_extra") or {}
            for tag in self.tags:
                v = extra.get(tag)
                if v:
                    if self.kind == "int":
                        return _to_int(v)
                    if self.kind == "num":
                        return _to_float(v)
                    return v
            return 0 if self.kind in ("int", "num") else ""
        return t.get(self.key, 0 if self.numeric else "")

    def display(self, t: dict) -> str:
        if self.kind == "num":  # shown as written in the tag
            extra = t.get("_extra") or {}
            return next((extra[g] for g in self.tags if extra.get(g)), "")
        v = self.get(t)
        return format_value(self, v)

    def sort_key(self, t: dict):
        v = self.get(t)
        if self.numeric:
            return (v == 0 or v is None, v or 0)
        return (v == "", str(v).lower())


def _to_float(v) -> float:
    m = re.match(r"\s*([-+]?\d+(?:[.,]\d+)?)", str(v))
    return float(m.group(1).replace(",", ".")) if m else 0.0


def _to_int(v) -> int:
    return int(_to_float(v))


def format_value(f: Field, v) -> str:
    if v in (None, ""):
        return ""
    k = f.kind
    if k == "dur":
        s = int(v or 0)
        h, rem = divmod(s, 3600)
        m, s = divmod(rem, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
    if k == "date":
        return time.strftime("%Y-%m-%d", time.localtime(v)) if v else ""
    if k == "size":
        if not v:
            return ""
        for unit in ("B", "KB", "MB", "GB"):
            if v < 1024 or unit == "GB":
                return f"{v:.0f} {unit}" if unit == "B" else f"{v:.1f} {unit}"
            v /= 1024
    if k == "rate":
        return f"{v / 1000:g} kHz" if v else ""
    if k == "bitrate":
        return f"{v // 1000} kbps" if v else ""
    if k == "rating":
        return "★" * v + "☆" * (5 - v) if v else ""
    if k == "int":
        return str(v) if v else ""
    return str(v)


B, T, A, L = "Basic", "Tags", "Audio & file", "Library"

BUILTIN: list[Field] = [
    Field("playing", "Now playing", B, "special", 30, True, header=" "),
    Field("track", "Track number", B, "int", 44, True, header="#"),
    Field("title", "Title", B, "text", 280, True),
    Field("artist", "Artist", B, "text", 180, True, True),
    Field("album", "Album", B, "text", 200, True, True),
    Field("albumartist", "Album artist", B, "text", 160, False),
    Field("artist_key", "Album artist", B, "text", 160, False, True, header="Album artist (or artist)"),
    Field("composer", "Composer", B, "text", 160, False, True),
    Field("year", "Year", B, "int", 58, True, True),
    Field("decade", "Decade", B, "int", 70, False, True),
    Field("origyear", "Original year", B, "int", 90, False, True, header="Orig. year"),
    Field("genre", "Genre", B, "text", 120, True, True),
    Field("length", "Length", B, "dur", 62, True, header="Time"),
    Field("rating", "Rating", L, "rating", 100, True, True),
    Field("playcount", "Play count", L, "int", 58, True, header="Plays"),
    Field("disc", "Disc number", B, "int", 50, False, header="Disc"),
    Field("totaltracks", "Total tracks", B, "int", 70, False, False, ("totaltracks", "tracktotal"),
          header="Tracks"),
    Field("totaldiscs", "Total discs", B, "int", 62, False, False, ("totaldiscs", "disctotal"),
          header="Discs"),
    # tags most players don't show
    Field("comment", "Comment", T, "text", 220, False, False, ("comment", "description")),
    Field("grouping", "Grouping", T, "text", 140, False, True, ("grouping", "contentgroup")),
    Field("bpm", "BPM", T, "int", 56, False, True, ("bpm", "tempo")),
    Field("initialkey", "Key", T, "text", 56, False, True, ("initialkey", "key"), plural="Keys"),
    Field("mood", "Mood", T, "text", 110, False, True, ("mood",)),
    Field("label", "Label", T, "text", 150, False, True, ("label", "publisher", "organization")),
    Field("catalog", "Catalog number", T, "text", 120, False, False, ("catalognumber", "catalog")),
    Field("conductor", "Conductor", T, "text", 150, False, True, ("conductor",)),
    Field("lyricist", "Lyricist", T, "text", 150, False, True, ("lyricist", "writer")),
    Field("remixer", "Remixer", T, "text", 150, False, True, ("remixer", "mixartist")),
    Field("discsubtitle", "Disc subtitle", T, "text", 150, False, False, ("discsubtitle", "setsubtitle")),
    Field("language", "Language", T, "text", 90, False, True, ("language",)),
    Field("copyright", "Copyright", T, "text", 180, False, False, ("copyright",)),
    Field("isrc", "ISRC", T, "text", 120, False, False, ("isrc",)),
    Field("encodedby", "Encoded by", T, "text", 140, False, False, ("encodedby", "encoder", "encoded_by")),
    # file and audio
    Field("format", "Format", A, "text", 70, False, True),
    Field("source", "Source", A, "text", 74, False, True, header="Source"),
    Field("bitrate", "Bitrate", A, "bitrate", 80, False),
    Field("samplerate", "Sample rate", A, "rate", 84, False, True),
    Field("bitdepth", "Bit depth", A, "int", 64, False, True),
    Field("channels", "Channels", A, "int", 70, False),
    Field("filesize", "File size", A, "size", 80, False),
    Field("filename", "File name", A, "text", 240, False),
    Field("folder", "Folder", A, "text", 180, False, True),
    Field("path", "Full path", A, "text", 320, False, header="File"),
    # library
    Field("added", "Date added", L, "date", 100, False, header="Added"),
    Field("lastplayed", "Last played", L, "date", 110, False),
    Field("skipcount", "Skip count", L, "int", 56, False, header="Skips"),
]

_custom: list[Field] = []

# Renamed columns
_ORIGINAL = {f.key: (f.name, f.header, f.plural) for f in BUILTIN}
_renames: dict[str, str] = {}


def original_name(key: str) -> str:
    return _ORIGINAL[key][0] if key in _ORIGINAL else ""


def renames() -> dict[str, str]:
    return dict(_renames)


def set_renames(names: dict[str, str]):
    """{field key: name}; empty or missing restores the original."""
    _renames.clear()
    for f in BUILTIN:
        f.name, f.header, f.plural = _ORIGINAL[f.key]
        new = (names.get(f.key) or "").strip()
        if new and new != f.name:
            _renames[f.key] = new
            f.name, f.header, f.plural = new, "", ""


def rename(key: str, name: str):
    names = renames()
    names[key] = name
    set_renames(names)


def load_renames(settings):
    try:
        d = json.loads(settings.value("column_names", "{}") or "{}")
        set_renames(d if isinstance(d, dict) else {})
    except (TypeError, ValueError):
        set_renames({})


def save_renames(settings):
    settings.setValue("column_names", json.dumps(_renames))


def custom_fields() -> list[Field]:
    return list(_custom)


def all_fields() -> list[Field]:
    return BUILTIN + _custom


def get(key: str) -> Field | None:
    for f in BUILTIN:
        if f.key == key:
            return f
    for f in _custom:
        if f.key == key:
            return f
    return None


def custom_key(tag: str) -> str:
    return "x:" + tag


def set_custom(defs: list[dict]):
    """defs: [{"tag": "catalognumber", "name": "Catalog #"}, ...]"""
    from musicwell.tags import norm_tag
    _custom.clear()
    seen = set()
    for d in defs:
        tag = norm_tag(d.get("tag", ""))
        if not tag or tag in seen:
            continue
        seen.add(tag)
        name = (d.get("name") or pretty_tag(tag)).strip()
        kind = "num" if d.get("numeric") else "text"
        _custom.append(Field(custom_key(tag), name, "Custom", kind, 140, False, True, (tag,), custom=True))


def custom_defs() -> list[dict]:
    return [{"tag": f.tags[0], "name": f.name, "numeric": f.kind == "num"} for f in _custom]


def load_custom(settings):
    try:
        set_custom(json.loads(settings.value("custom_fields", "[]")))
    except (TypeError, ValueError):
        set_custom([])


def save_custom(settings):
    settings.setValue("custom_fields", json.dumps(custom_defs()))


def pretty_tag(tag: str) -> str:
    small = {"bpm", "isrc", "id", "url", "dj"}
    words = tag.replace("_", " ").split()
    return " ".join(w.upper() if w in small else w.capitalize() for w in words) or tag


def builtin_tag_names() -> set[str]:
    """Tag names already covered by built-in fields."""
    out = set()
    for f in BUILTIN:
        out.update(f.tags)
    return out


def browsable() -> list[Field]:
    return [f for f in all_fields() if f.browsable]


_TAG_FIELDS = None


def derive(t: dict) -> dict:
    """Fill in computed fields on a loaded track (runs for every song at startup)."""
    global _TAG_FIELDS
    if _TAG_FIELDS is None:
        _TAG_FIELDS = [(f.key, tuple(f.tags), f.kind == "int") for f in BUILTIN if f.tags]
    extra = t.get("extra")
    if isinstance(extra, str):
        if extra and extra != "{}":
            try:
                extra = json.loads(extra)
            except ValueError:
                extra = {}
        else:
            extra = {}
    extra = extra or {}
    t["_extra"] = extra
    get = extra.get
    for key, tags, is_int in _TAG_FIELDS:
        v = ""
        if extra:
            for tag in tags:
                x = get(tag)
                if x:
                    v = x
                    break
        t[key] = (_to_int(v) if v else 0) if is_int else v
    t["filename"] = os.path.basename(t["path"])
    return t
