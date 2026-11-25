"""Reading and writing tags and artwork with mutagen."""
from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path

import mutagen

try:  # mutagen's simple MP4 interface lacks composer and comment
    from mutagen.easymp4 import EasyMP4Tags
    if "composer" not in EasyMP4Tags.Set:
        EasyMP4Tags.RegisterTextKey("composer", "\xa9wrt")
    if "comment" not in EasyMP4Tags.Set:
        EasyMP4Tags.RegisterTextKey("comment", "\xa9cmt")
except Exception:
    pass

AUDIO_EXTS = {
    ".mp3", ".flac", ".ogg", ".oga", ".opus", ".m4a", ".m4b", ".mp4", ".aac",
    ".wav", ".aiff", ".aif", ".wv", ".ape", ".wma", ".mpc", ".dsf",
}

COVER_NAMES = ("cover", "folder", "front", "album", "albumart", "albumartsmall")
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")

# fallback keys where mutagen's easy interface doesn't apply
_ID3_KEYS = {
    "title": "TIT2", "artist": "TPE1", "album": "TALB", "albumartist": "TPE2", "composer": "TCOM",
    "genre": "TCON", "date": "TDRC", "tracknumber": "TRCK", "discnumber": "TPOS",
}
_APE_KEYS = {
    "title": "Title", "artist": "Artist", "album": "Album", "albumartist": "Album Artist",
    "composer": "Composer",
    "genre": "Genre", "date": "Year", "tracknumber": "Track", "discnumber": "Disc",
}
_ASF_KEYS = {
    "title": "Title", "artist": "Author", "album": "WM/AlbumTitle",
    "albumartist": "WM/AlbumArtist", "genre": "WM/Genre", "date": "WM/Year",
    "composer": "WM/Composer",
    "tracknumber": "WM/TrackNumber", "discnumber": "WM/PartOfSet",
}

_FORMAT_NAMES = {
    "EasyMP3": "MP3", "MP3": "MP3", "FLAC": "FLAC", "OggVorbis": "Vorbis",
    "OggOpus": "Opus", "OggFLAC": "FLAC", "OggSpeex": "Speex", "WAVE": "WAV",
    "AIFF": "AIFF", "WavPack": "WavPack", "MonkeysAudio": "APE", "ASF": "WMA",
    "Musepack": "Musepack", "DSF": "DSD", "AAC": "AAC",
}


def _first(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ""
    if hasattr(value, "text"):  # ID3 frame
        value = value.text[0] if value.text else ""
    if hasattr(value, "value"):  # APE / ASF value
        value = value.value
    return str(value).strip().replace("\x00", "")


def _get(tags, key: str) -> str:
    if tags is None:
        return ""
    for k in (key, _ID3_KEYS.get(key), _APE_KEYS.get(key), _ASF_KEYS.get(key)):
        if not k:
            continue
        try:
            if k in tags:
                return _first(tags[k])
        except (KeyError, ValueError, TypeError):
            pass
    return ""


def _int(text: str) -> int:
    m = re.match(r"\s*(\d{1,9})", text or "")  # limit digits: huge numbers can't be stored
    return int(m.group(1)) if m else 0


def _year(text: str) -> int:
    m = re.search(r"(\d{4})", text or "")
    return int(m.group(1)) if m else 0


def _format_name(f) -> str:
    name = type(f).__name__
    if name in ("MP4", "EasyMP4"):
        codec = getattr(f.info, "codec", "") or ""
        return "ALAC" if codec.startswith("alac") else "AAC"
    return _FORMAT_NAMES.get(name, name.replace("Easy", ""))


def _easy_view(f):
    """Easy tag names over an already opened file, so it isn't read twice."""
    tags = f.tags
    if tags is None:
        return None
    try:
        from mutagen.id3 import ID3
        if type(f).__name__ in ("MP3", "TrueAudio") and isinstance(tags, ID3):
            from mutagen.easyid3 import EasyID3
            e = EasyID3()
            e._EasyID3__id3 = tags
            return e
        if type(f).__name__ == "MP4":
            from mutagen.easymp4 import EasyMP4Tags
            from mutagen.mp4 import MP4Tags
            if isinstance(tags, MP4Tags):
                e = EasyMP4Tags()
                e._EasyMP4Tags__mp4 = tags
                return e
    except Exception:
        pass
    return tags


def read_track(path: str) -> dict | None:
    """Tag and stream info for one file, or None if unreadable."""
    try:
        f = mutagen.File(path)
    except Exception:
        f = None
    if f is None:
        return None
    tags = _easy_view(f)
    info = f.info
    st = os.stat(path)
    length = float(getattr(info, "length", 0) or 0)
    bitrate = int(getattr(info, "bitrate", 0) or 0)
    if not bitrate and length > 0:
        bitrate = int(st.st_size * 8 / length)
    title = _get(tags, "title") or Path(path).stem
    return {
        "path": path,
        "mtime": st.st_mtime,
        "filesize": st.st_size,
        "title": title,
        "artist": _get(tags, "artist"),
        "album": _get(tags, "album"),
        "albumartist": _get(tags, "albumartist"),
        "genre": _get(tags, "genre"),
        "composer": _get(tags, "composer"),
        "year": _year(_get(tags, "date") or _get(tags, "year")),
        "track": _int(_get(tags, "tracknumber")),
        "disc": _int(_get(tags, "discnumber")),
        "length": length,
        "bitrate": bitrate,
        "samplerate": int(getattr(info, "sample_rate", 0) or 0),
        "bitdepth": int(getattr(info, "bits_per_sample", 0) or 0),
        "channels": int(getattr(info, "channels", 0) or 0),
        "format": _format_name(f),
        "extra": json.dumps(_extra_tags_of(f), ensure_ascii=False, default=str),
    }


def norm_tag(name: str) -> str:
    """'MusicBrainz Album Id' -> 'musicbrainz_album_id'"""
    return re.sub(r"[\s\-]+", "_", name.strip().lower())


# tags with their own columns, or binary/huge: not stored again
_CORE = {"title", "artist", "album", "albumartist", "album_artist", "genre", "date", "year",
         "tracknumber", "track", "discnumber", "disc", "composer", "totaltracks", "tracktotal",
         "totaldiscs", "disctotal", "metadata_block_picture", "coverart", "coverartmime",
         "cover_art_(front)", "cover_art_(back)", "lyrics", "unsyncedlyrics", "picture"}
_ID3_NAMES = {
    "TBPM": "bpm", "TKEY": "initialkey", "TPUB": "label", "TIT1": "grouping", "TIT3": "subtitle",
    "TMOO": "mood", "TPE3": "conductor", "TPE4": "remixer", "TEXT": "lyricist", "TCOP": "copyright",
    "TSRC": "isrc", "TENC": "encodedby", "TSSE": "encoder", "TSST": "discsubtitle", "TLAN": "language",
    "TCMP": "compilation", "TOPE": "originalartist", "TOAL": "originalalbum", "TDOR": "originaldate",
    "TMED": "media", "TSOP": "artistsort", "TSOA": "albumsort", "TSOT": "titlesort",
    "TSO2": "albumartistsort", "TDRL": "releasedate", "WOAR": "website", "TPOS": None, "TRCK": None,
    "TIT2": None, "TPE1": None, "TALB": None, "TPE2": None, "TCON": None, "TDRC": None, "TYER": None,
    "TCOM": None, "APIC": None, "USLT": None, "PRIV": None, "GEOB": None, "MCDI": None, "UFID": None,
    "POPM": None, "PCNT": None, "RVA2": None,
}
_MP4_NAMES = {
    "\xa9cmt": "comment", "\xa9grp": "grouping", "tmpo": "bpm", "cprt": "copyright", "\xa9too": "encoder",
    "\xa9lyr": None, "covr": None, "\xa9nam": None, "\xa9ART": None, "\xa9alb": None, "aART": None,
    "\xa9gen": None, "\xa9day": None, "trkn": None, "disk": None, "\xa9wrt": None, "cpil": "compilation",
    "desc": "description", "soar": "artistsort", "soal": "albumsort", "sonm": "titlesort",
}
MAX_TAG_LEN = 400


def _text(v) -> str | None:
    if isinstance(v, (bytes, bytearray)):
        return None
    if isinstance(v, (list, tuple)):
        parts = [_text(x) for x in v]
        parts = [x for x in parts if x]
        return "; ".join(parts) if parts else None
    if hasattr(v, "text"):  # ID3 frame (dates have plain-string .text)
        return _text(v.text if isinstance(v.text, str) else list(v.text))
    if hasattr(v, "value"):  # APE / ASF
        return _text(v.value)
    if isinstance(v, tuple):
        return None
    s = str(v).replace("\x00", " ").strip()
    return s or None


def _extra_tags_of(f) -> dict[str, str]:
    if f is None or f.tags is None:
        return {}
    out: dict[str, str] = {}

    def put(name, value):
        if not name:
            return
        key = norm_tag(name)
        if key in _CORE or key in out:
            return
        val = _text(value)
        if val and len(val) <= MAX_TAG_LEN:
            out[key] = val

    tags = f.tags
    try:
        if hasattr(tags, "getall"):  # ID3 (MP3, AIFF, WAV)
            for frame in tags.values():
                fid = frame.FrameID
                if fid == "TXXX":
                    put(frame.desc, frame)
                elif fid == "COMM":
                    if frame.desc and frame.desc.lower().startswith(("itun", "musicmatch")):
                        continue
                    put("comment" if not frame.desc or frame.desc.lower() in ("comment", "description")
                        else frame.desc, frame)
                elif fid in _ID3_NAMES:
                    put(_ID3_NAMES[fid], frame)
                elif fid.startswith("T"):
                    put(fid.lower(), frame)
        elif type(f).__name__ in ("MP4", "M4A"):
            for k, v in tags.items():
                if k.startswith("----:"):
                    name = k.split(":", 2)[-1]
                    vals = [bytes(x).decode("utf-8", "replace") for x in v]
                    put(name, vals)
                elif k in _MP4_NAMES:
                    put(_MP4_NAMES[k], v)
        elif type(f).__name__ == "ASF":
            for k, v in tags.items():
                name = k[3:] if k.startswith("WM/") else k
                if name.lower() in ("picture", "albumtitle", "albumartist", "genre", "year",
                                    "tracknumber", "partofset", "composer", "author", "title"):
                    continue
                put("comment" if name.lower() in ("description", "comments") else name, v)
        else:  # Vorbis, FLAC, Opus, APE
            for k, v in tags.items():
                if k.lower() == "description":
                    put("comment", v)
                put(k, v)
    except Exception:
        pass
    try:
        out.update(_totals(f))
    except Exception:
        pass
    return out


def _of(text) -> int:
    """The total in '3/12', or 0."""
    m = re.search(r"/\s*(\d+)", _text(text) or "")
    return int(m.group(1)) if m else 0


def _totals(f) -> dict[str, str]:
    """Total tracks and discs, however the format stores them."""
    tags = f.tags
    tracks = discs = 0
    if hasattr(tags, "getall"):  # ID3
        tracks = _of(tags.get("TRCK"))
        discs = _of(tags.get("TPOS"))
    elif type(f).__name__ in ("MP4", "M4A"):
        for key in ("trkn", "disk"):
            v = tags.get(key)
            n = int(v[0][1]) if v and isinstance(v[0], tuple) and len(v[0]) > 1 else 0
            if key == "trkn":
                tracks = n
            else:
                discs = n
    else:  # Vorbis, APE, ASF
        low = {norm_tag(k): v for k, v in tags.items()}

        def num(*names):
            for n in names:
                if n in low:
                    m = re.match(r"\s*(\d+)", _text(low[n]) or "")
                    if m:
                        return int(m.group(1))
            return 0
        tracks = (num("totaltracks", "tracktotal", "wm/totaltracks")
                  or _of(low.get("tracknumber") or low.get("track") or low.get("wm/tracknumber")))
        discs = (num("totaldiscs", "disctotal", "wm/totaldiscs")
                 or _of(low.get("discnumber") or low.get("disc") or low.get("wm/partofset")))
    out = {}
    if tracks:
        out["totaltracks"] = str(tracks)
    if discs:
        out["totaldiscs"] = str(discs)
    return out


def _embedded_art(path: str) -> bytes | None:
    try:
        f = mutagen.File(path)
    except Exception:
        return None
    if f is None:
        return None
    pics = getattr(f, "pictures", None)  # FLAC
    if pics:
        front = [p for p in pics if p.type == 3]
        return (front or pics)[0].data
    tags = f.tags
    if tags is None:
        return None
    try:
        if hasattr(tags, "getall"):  # ID3
            apic = tags.getall("APIC")
            if apic:
                front = [p for p in apic if p.type == 3]
                return (front or apic)[0].data
        if "covr" in tags:  # MP4
            return bytes(tags["covr"][0])
        if "metadata_block_picture" in tags:  # Ogg
            from mutagen.flac import Picture
            return Picture(base64.b64decode(tags["metadata_block_picture"][0])).data
        for key in ("Cover Art (Front)", "Cover Art (front)"):  # APE
            if key in tags:
                data = tags[key].value
                return data.split(b"\x00", 1)[1] if b"\x00" in data else data
        if "WM/Picture" in tags:  # ASF: skip the header
            raw = tags["WM/Picture"][0].value
            for sig in (b"\xff\xd8\xff", b"\x89PNG"):
                i = raw.find(sig)
                if i >= 0:
                    return raw[i:]
    except Exception:
        return None
    return None


# albums on more than one disc
_NUMS = r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten|i{1,3}|iv|vi{0,3}|ix|x|[a-d])"
_DISC_WORD = r"(?:cd|disc|disk)"  # not Vol./Part: "Greatest Hits Vol. 2" is its own album
_DISC_WORD_BR = r"(?:cd|disc|disk|disque|disco|scheibe)"  # only in brackets: "(Disco 2)", not "Best of Disco 2"
_DISC_SUFFIX = [
    re.compile(r"\s*[\(\[\{]\s*" + _DISC_WORD_BR + r"\s*\.?\s*" + _NUMS + r"(?:\s*(?:of|/)\s*\d+)?"
               r"(?:\s*[:\-–]\s*[^\)\]\}]*)?\s*[\)\]\}]\s*$", re.I),  # Album (Disc 1), [CD 2 of 3]
    re.compile(r"\s*[-–:,_/]\s*" + _DISC_WORD + r"\s*\.?\s*" + _NUMS + r"(?:\s*(?:of|/)\s*\d+)?\s*$", re.I),
    re.compile(r"\s+" + _DISC_WORD + r"\s*\.?\s*" + _NUMS + r"(?:\s*(?:of|/)\s*\d+)?\s*$", re.I),  # Album CD2
]
_DISC_FOLDER = re.compile(r"^" + _DISC_WORD + r"[\s._-]*" + _NUMS + r"\b", re.I)  # CD1, Disc 2 - Live, disk_3


def album_title(name: str) -> str:
    """Album name without the disc: "The Wall CD2" -> "The Wall". A name that is only a disc is kept."""
    n = (name or "").strip()
    for rx in _DISC_SUFFIX:
        m = rx.search(n)
        if m and m.start() > 0:
            return n[:m.start()].rstrip(" -–:,_/")
    return n


def is_disc_folder(name: str) -> bool:
    """e.g. CD1, Disc 2, Disk_03, Album CD2, Album (Disc 1)"""
    n = (name or "").strip()
    return bool(_DISC_FOLDER.match(n)) or album_title(n) != n


def album_folder(path: str) -> str:
    """The album's folder: one up from a CD1 / Disc 2 folder."""
    d = os.path.dirname(path or "")
    base = os.path.basename(d)
    if _DISC_FOLDER.match(base.strip()):
        return os.path.dirname(d)
    t = album_title(base)
    if t != base.strip():
        return os.path.join(os.path.dirname(d), t)
    return d


def folder_image(folder: str, names=COVER_NAMES) -> str | None:
    try:
        entries = os.listdir(folder)
    except OSError:
        return None
    images = [e for e in entries if e.lower().endswith(IMAGE_EXTS)]
    for name in names:
        for e in images:
            if os.path.splitext(e)[0].lower() == name:
                return os.path.join(folder, e)
    return None


def read_artwork(path: str) -> bytes | None:
    """Embedded art first, then a cover image in the folder."""
    data = _embedded_art(path)
    if data:
        return data
    img = folder_image(os.path.dirname(path))
    if not img and is_disc_folder(os.path.basename(os.path.dirname(path))):
        img = folder_image(os.path.dirname(os.path.dirname(path)))  # cover above CD1 / CD2
    if not img:
        folder = os.path.dirname(path)
        try:
            imgs = sorted(e for e in os.listdir(folder) if e.lower().endswith(IMAGE_EXTS))
        except OSError:
            imgs = []
        img = os.path.join(folder, imgs[0]) if imgs else None
    if img:
        try:
            with open(img, "rb") as fh:
                return fh.read()
        except OSError:
            return None
    return None


EDITABLE = ["title", "artist", "album", "albumartist", "composer", "genre", "date", "tracknumber",
            "discnumber", "comment"]


def _write_comment(path: str, value: str):
    """Comments need format-specific handling."""
    f = mutagen.File(path)
    if f is None:
        raise ValueError("Unsupported file")
    if f.tags is None:
        f.add_tags()
    tags = f.tags
    name = type(f).__name__
    if hasattr(tags, "getall"):
        from mutagen.id3 import COMM
        tags.delall("COMM::eng")
        for fr in list(tags.getall("COMM")):
            if not fr.desc:
                tags.delall(fr.HashKey)
        if value:
            tags.add(COMM(encoding=3, lang="eng", desc="", text=[value]))
    elif name in ("MP4", "M4A"):
        if value:
            tags["\xa9cmt"] = [value]
        elif "\xa9cmt" in tags:
            del tags["\xa9cmt"]
    elif name == "ASF":
        if value:
            tags["Description"] = value
        elif "Description" in tags:
            del tags["Description"]
    else:
        key = "Comment" if name in ("MonkeysAudio", "WavPack", "Musepack") else "comment"
        for k in list(tags.keys()):
            if k.lower() in ("comment", "description"):
                del tags[k]
        if value:
            tags[key] = [value] if key == "comment" else value
    f.save()


def write_tags(path: str, changes: dict[str, str]) -> None:
    """Write changed tags. An empty string removes the tag."""
    changes = dict(changes)
    if "comment" in changes:
        _write_comment(path, changes.pop("comment"))
        if not changes:
            return
    f = mutagen.File(path, easy=True)
    if f is None:
        raise ValueError("Unsupported file")
    if f.tags is None:
        f.add_tags()
    tags = f.tags
    easy = type(f).__name__.startswith("Easy") or type(f).__name__ in (
        "FLAC", "OggVorbis", "OggOpus", "OggFLAC", "OggSpeex")
    for key, value in changes.items():
        if easy:
            real = key
        elif hasattr(tags, "getall"):
            real = None  # raw ID3 (WAV/AIFF) handled below
        elif type(f).__name__ == "ASF":
            real = _ASF_KEYS[key]
        else:
            real = _APE_KEYS[key]
        if real is None:
            from mutagen import id3
            frame_id = _ID3_KEYS[key]
            tags.delall(frame_id)
            if value:
                tags.add(getattr(id3, frame_id)(encoding=3, text=[value]))
            continue
        if value:
            tags[real] = [value] if easy else value
        elif real in tags:
            del tags[real]
    f.save()
