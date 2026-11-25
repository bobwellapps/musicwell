"""Album covers, artist photos and accent colours."""
from __future__ import annotations

import colorsys
import math
import hashlib
import json
import os
import re
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QObject, QRectF, Qt, Signal
from PySide6.QtGui import (QColor, QFont, QImage, QLinearGradient, QPainter,
                           QPainterPath, QPen)

from musicwell import artsources as S
from musicwell import tags as tagio
from musicwell.paths import cache_dir


def accent_from_image(img: QImage, dark: bool = True) -> QColor | None:
    """Pick a vivid colour from the artwork that reads well on the theme."""
    if img is None or img.isNull():
        return None
    small = img.scaled(40, 40, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    buckets: dict[int, list] = {}
    for y in range(small.height()):
        for x in range(small.width()):
            c = small.pixelColor(x, y)
            h, l, s = colorsys.rgb_to_hls(c.redF(), c.greenF(), c.blueF())
            if s < 0.25 or l < 0.12 or l > 0.92:
                continue
            b = int(h * 18) % 18
            w = s * (1 - abs(l - 0.5))
            acc = buckets.setdefault(b, [0.0, 0.0, 0.0, 0.0, 0.0])
            acc[0] += w
            acc[1] += h * w
            acc[2] += l * w
            acc[3] += s * w
            acc[4] += 1
    if not buckets:
        return None
    best = max(buckets.values(), key=lambda a: a[0])
    if best[4] < 12:
        return None
    h, l, s = best[1] / best[0], best[2] / best[0], best[3] / best[0]
    s = max(0.5, min(0.9, s * 1.15))
    l = max(0.58, min(0.72, l)) if dark else max(0.38, min(0.48, l))
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return QColor.fromRgbF(r, g, b)


def dominant_colour(img: QImage) -> tuple[float, float, float]:
    """(hue, saturation, colourfulness), each 0-1, of the artwork's main colour."""
    small = img.scaled(36, 36, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    buckets: dict[int, list] = {}
    colourful, total = 0, 0
    for y in range(small.height()):
        for x in range(small.width()):
            c = small.pixelColor(x, y)
            h, l, s = colorsys.rgb_to_hls(c.redF(), c.greenF(), c.blueF())
            total += 1
            if s < 0.15 or l < 0.07 or l > 0.93:
                continue
            colourful += 1
            w = s * (1 - abs(l - 0.5) * 0.8)
            acc = buckets.setdefault(int(h * 24) % 24, [0.0, 0.0, 0.0, 0.0])
            acc[0] += w
            acc[1] += w * math.cos(h * 2 * math.pi)  # hue is circular: average it as an angle
            acc[2] += w * math.sin(h * 2 * math.pi)
            acc[3] += w * s
    if not buckets:
        return 0.0, 0.0, 0.0
    w, cx, sy, ss = max(buckets.values(), key=lambda a: a[0])
    hue = (math.atan2(sy, cx) / (2 * math.pi)) % 1.0
    return hue, ss / w, colourful / max(1, total)


def palette_from_image(img: QImage, dark: bool = True) -> dict | None:
    """A colour theme made from the artwork."""
    if img is None or img.isNull():
        return None
    hue, sat, colourful = dominant_colour(img)
    acc = accent_from_image(img, dark)
    if acc is not None:
        hue = acc.hslHueF() if acc.hslHueF() >= 0 else hue
    tint = 0.05 if colourful < 0.12 else max(0.18, min(0.5, sat * 0.6))

    def c(l, s_mul=1.0):
        r, g, b = colorsys.hls_to_rgb(hue, l, min(1.0, tint * s_mul))
        return QColor.fromRgbF(r, g, b).name()

    if dark:
        pal = {"bg": c(0.085), "panel": c(0.115), "surface": c(0.145, 0.9), "hover": c(0.19, 0.85),
               "border": c(0.17, 0.8), "selected": c(0.24, 1.1), "text": c(0.94, 0.35),
               "muted": c(0.71, 0.3), "faint": c(0.52, 0.3)}
    else:
        pal = {"bg": c(0.955, 0.9), "panel": c(0.925, 0.9), "surface": c(0.985, 0.7), "hover": c(0.885, 0.9),
               "border": c(0.86, 0.8), "selected": c(0.86, 1.1), "text": c(0.11, 0.5),
               "muted": c(0.36, 0.35), "faint": c(0.58, 0.3)}
    pal.update({"name": "From the artwork", "dark": dark, "accent": acc.name() if acc else pal["muted"]})
    return pal


def placeholder(size: int, text: str, accent: QColor, rounded: float = 0.0) -> QImage:
    """Gradient tile with initials, for when there's no image."""
    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size, size), rounded, rounded)
    g = QLinearGradient(0, 0, size, size)
    g.setColorAt(0, accent.darker(170))
    g.setColorAt(1, accent.darker(320))
    p.fillPath(path, g)
    words = [w for w in re.split(r"\s+", text.strip()) if w and w[0].isalnum()]
    initials = "".join(w[0] for w in words[:2]).upper() or "♪"
    f = QFont()
    f.setPixelSize(int(size * 0.34))
    f.setBold(True)
    p.setFont(f)
    p.setPen(QPen(QColor(255, 255, 255, 200)))
    p.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, initials)
    p.end()
    return img


def primary_artist(name: str) -> str:
    """'A feat. B' / 'A; B' -> 'A' (keeps names like AC/DC)."""
    name = re.split(r"\s+(?:feat\.?|ft\.?|featuring)\s+|;", name, flags=re.I)[0]
    return name.strip()


def _square(img: QImage, size: int, top: float = 0.3) -> QImage:
    """Square crop, slightly above centre where faces usually are."""
    w, h = img.width(), img.height()
    side = min(w, h)
    x = (w - side) // 2
    y = int((h - side) * top)
    return img.copy(x, y, side, side).scaled(size, size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)


def _hash(text: str) -> str:
    return hashlib.sha1(text.lower().encode("utf-8")).hexdigest()[:20]


def album_key(track: dict) -> str:
    """Album artist + album name, with the folder as a tie-breaker for untagged files."""
    artist = track.get("albumartist") or track.get("artist") or ""
    from musicwell.tags import album_title
    album = album_title(track.get("album") or "")  # all discs share one cover
    if not album:
        return "folder:" + os.path.dirname(track["path"])
    return f"{artist}|{album}"


class ImageStore(QObject):
    """Covers and artist photos: your pick > embedded > folder image > online sources."""
    albumReady = Signal(str, QImage)  # album key, image
    artistReady = Signal(str, QImage)  # artist name, image
    _found = Signal(str, str, bytes, object)  # kind, key, data, info (from worker threads)
    _missed = Signal(str, str)
    missed = Signal(str, str)  # kind, key: nothing found online

    # image file names looked for in the artist's folder
    LOCAL_ARTIST_NAMES = ("artist", "band", "artistimage", "folder", "fanart", "thumb", "artist-fanart")
    MISS_DAYS = 7

    def __init__(self, parent=None):
        super().__init__(parent)
        self.album_online = True
        self.artist_online = True
        self.album_order = list(S.DEFAULT_ALBUM_ORDER)
        self.artist_order = list(S.DEFAULT_ARTIST_ORDER)
        self.save_to_folder = False
        self._retry_at: dict[tuple[str, str], float] = {}  # retry later: the service was busy
        self._albums: OrderedDict[str, QImage | None] = OrderedDict()
        self._artists: OrderedDict[str, QImage | None] = OrderedDict()  # full photos, last few only
        self._thumbs: OrderedDict[tuple, QImage] = OrderedDict()
        self._artist_info: dict[str, dict | None] = {}  # photographer and licence of the photo shown
        self._pending: set[tuple[str, str]] = set()
        self._album_dirs: dict[str, str] = {}
        self.pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="musicwell-art")
        self._found.connect(self._on_found)
        self._missed.connect(self._on_missed)

    def configure(self, settings):
        s = settings
        self.artist_online = s.value("artist_online", True, bool)
        self.album_online = s.value("album_online", True, bool)
        self.save_to_folder = s.value("save_covers", False, bool)
        self.album_order = _order(s.value("album_sources"), S.DEFAULT_ALBUM_ORDER, S.ALBUM_SOURCES)
        self.artist_order = _order(s.value("artist_sources"), S.DEFAULT_ARTIST_ORDER, S.ARTIST_SOURCES)

    def _dir(self, kind: str) -> Path:
        d = cache_dir() / {"album": "covers", "artist": "artists"}[kind]
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _path(self, kind: str, key: str, suffix: str = ".jpg") -> Path:
        return self._dir(kind) / f"{_hash(key)}{suffix}"

    def _override(self, kind: str, key: str) -> Path:
        return self._dir(kind) / f"{_hash(key)}.mine"

    def has_override(self, kind: str, key: str) -> bool:
        return self._override(kind, key).exists()

    # Free licences require showing the photographer and licence.
    def _info_path(self, kind: str, key: str, mine: bool = False) -> Path:
        return self._dir(kind) / f"{_hash(key)}{'.minecredit' if mine else '.credit'}"

    def _read_info(self, kind: str, key: str, mine: bool = False) -> dict | None:
        try:
            d = json.loads(self._info_path(kind, key, mine).read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else None
        except (OSError, ValueError):
            return None

    def _write_info(self, kind: str, key: str, info: dict | None, mine: bool = False):
        p = self._info_path(kind, key, mine)
        try:
            if info and (info.get("credit") or info.get("license")):
                p.write_text(json.dumps(info), encoding="utf-8")
            else:
                p.unlink(missing_ok=True)
        except OSError:
            pass

    def artist_credit(self, artist: str) -> dict | None:
        """{"credit", "license", "page", "source"} for the artist photo shown, if needed."""
        return self._artist_info.get(primary_artist(artist or ""))

    def album_cover(self, track: dict) -> QImage | None:
        key = album_key(track)
        self._album_dirs[key] = os.path.dirname(track["path"])
        if key in self._albums:
            self._albums.move_to_end(key)
            img = self._albums[key]
            if img is not None:
                return img
        img = self._load(self._override("album", key))
        if img is None:
            data = tagio.read_artwork(track["path"])
            img = _image(data)
        if img is None:
            img = self._load(self._path("album", key))
        self._remember_album(key, img)
        if img is None and self.album_online and track.get("album"):
            self._fetch("album", key, track.get("albumartist") or track.get("artist") or "", track["album"])
        return img

    def cached_cover_bytes(self, track: dict) -> bytes | None:
        """The cover a cast device should show."""
        key = album_key(track)
        for p in (self._override("album", key),):
            if p.exists():
                return p.read_bytes()
        data = tagio.read_artwork(track["path"])
        if data:
            return data
        p = self._path("album", key)
        return p.read_bytes() if p.exists() else None

    def _remember_album(self, key, img):
        self._albums[key] = img
        _trim(self._albums, 96 << 20, 96)  # max 96 MB

    def artist_image(self, artist: str, track_path: str = "") -> QImage | None:
        name = primary_artist(artist)
        if not name:
            return None
        if self._artists.get(name) is not None:
            self._artists.move_to_end(name)
            return self._artists[name]
        img = self._load(self._override("artist", name))
        info = self._read_info("artist", name, mine=True) if img is not None else None
        if img is None and track_path:
            img = self._local_artist(track_path)
        if img is None:
            img = self._load(self._path("artist", name))
            info = self._read_info("artist", name) if img is not None else None
        self._artist_info[name] = info
        if img is not None:
            self._remember_artist(name, img)
            return img
        if self.artist_online:
            self._fetch("artist", name, name, "")
        return None

    def _remember_artist(self, name: str, img):
        self._artists[name] = img
        self._artists.move_to_end(name)
        _trim(self._artists, 64 << 20, 48)  # max 64 MB

    def artist_thumb(self, artist: str, track_path: str = "", size: int = 64) -> QImage | None:
        """Small square artist photo, or None while it's being looked up (artistReady follows)."""
        name = primary_artist(artist)
        if not name:
            return None
        key = (name.lower(), size)
        t = self._thumbs.get(key)
        if t is not None:
            self._thumbs.move_to_end(key)
            return t
        img = self._artists.get(name)
        if img is None:
            img = self._load(self._override("artist", name))
        if img is None and track_path:
            img = self._local_artist(track_path)
        if img is None:
            img = self._load(self._path("artist", name))
        if img is None:
            if self.artist_online:
                self._fetch("artist", name, name, "")
            return None
        t = _square(img, size)
        self._thumbs[key] = t
        self._trim_thumbs()
        return t

    def album_thumb(self, track: dict, size: int = 64) -> QImage | None:
        """Small square cover, or None while it's being looked up (albumReady follows)."""
        key = album_key(track)
        tk = ("album:" + key, size)
        t = self._thumbs.get(tk)
        if t is not None:
            self._thumbs.move_to_end(tk)
            return t
        img = self.album_cover(track)
        if img is None or img.isNull():
            return None
        t = _square(img, size, top=0.5)
        self._thumbs[tk] = t
        self._trim_thumbs()
        return t

    def _trim_thumbs(self):
        """Thumbnail cache: 160 MB at most."""
        self._thumb_bytes = getattr(self, "_thumb_bytes", 0) + _bytes(next(reversed(self._thumbs.values())))
        if self._thumb_bytes > (160 << 20) or len(self._thumbs) > 3000:
            _trim(self._thumbs, 140 << 20, 2800)
            self._thumb_bytes = sum(_bytes(v) for v in self._thumbs.values())

    def _drop_thumbs(self, name: str):
        n = primary_artist(name).lower()
        for k in [k for k in self._thumbs if k[0] == n]:
            del self._thumbs[k]

    def _local_artist(self, track_path: str) -> QImage | None:
        album_dir = os.path.dirname(track_path)
        artist_dir = os.path.dirname(album_dir)
        for d, names in ((artist_dir, self.LOCAL_ARTIST_NAMES), (album_dir, ("artist", "band", "artistimage"))):
            p = tagio.folder_image(d, names)
            if p:
                img = _read_image(p)
                if img is not None:
                    return img
        return None

    def _fetch(self, kind: str, key: str, artist: str, album: str):
        if (kind, key) in self._pending:
            return
        miss = self._path(kind, key, ".miss")
        if miss.exists() and time.time() - miss.stat().st_mtime < self.MISS_DAYS * 86400:
            return
        order = self.album_order if kind == "album" else self.artist_order
        if not order:
            return

        if time.time() < self._retry_at.get((kind, key), 0):
            return  # service busy or offline: not yet
        self._pending.add((kind, key))

        def work():
            problems = []
            found = S.find_first(kind, order, artist, album, problems=problems)
            if found:
                self._found.emit(kind, key, found[0], found[1].info())
            else:
                if problems:
                    # Busy or offline: retry later instead of caching "no image" for a week.
                    self._retry_at[(kind, key)] = time.time() + S.BUSY_DEFAULT
                else:
                    try:
                        miss.touch()
                    except OSError:
                        pass
                self._missed.emit(kind, key)
        self.pool.submit(work)

    def _on_missed(self, kind: str, key: str):
        if (kind, key) in self._pending:
            self._pending.discard((kind, key))
            self.missed.emit(kind, key)

    def _on_found(self, kind: str, key: str, data: bytes, info=None):
        if (kind, key) not in self._pending:  # cache was cleared meanwhile
            return
        self._pending.discard((kind, key))
        img = _image(data)
        if img is None:
            return
        try:
            self._path(kind, key).write_bytes(data)
        except OSError:
            pass
        self._write_info(kind, key, info)
        if kind == "album":
            self._remember_album(key, img)
            folder = self._album_dirs.get(key)
            if self.save_to_folder and folder and not key.startswith("folder:"):
                target = os.path.join(folder, "cover.jpg")
                if not os.path.exists(target):
                    try:
                        with open(target, "wb") as fh:
                            fh.write(data)
                    except OSError:
                        pass
            for k in [k for k in self._thumbs if k[0] == "album:" + key]:
                del self._thumbs[k]
            self.albumReady.emit(key, img)
        else:
            self._drop_thumbs(key)
            self._remember_artist(key, img)
            self._artist_info[key] = info if info and info.get("license") else None
            self.artistReady.emit(key, img)

    def set_override(self, kind: str, key: str, data: bytes | None, info: dict | None = None):
        """Use these bytes for an album/artist (None = automatic). `info` holds photographer and licence."""
        if kind == "artist":
            key = primary_artist(key)
        p = self._override(kind, key)
        if data is None:
            p.unlink(missing_ok=True)
        else:
            p.write_bytes(data)
        self._write_info(kind, key, info if data is not None else None, mine=True)
        self.forget(kind, key, keep_override=True)
        img = _image(data) if data else None
        if kind == "album":
            self._albums.pop(key, None)
            for k in [k for k in self._thumbs if k[0] == "album:" + key]:
                del self._thumbs[k]
            if img is not None:
                self._remember_album(key, img)
                self.albumReady.emit(key, img)
        else:
            self._artists.pop(key, None)
            self._drop_thumbs(key)
            if img is not None:
                self._remember_artist(key, img)
                self._artist_info[key] = info if info and info.get("license") else None
                self.artistReady.emit(key, img)

    def forget(self, kind: str, key: str, keep_override: bool = False):
        """Drop the cache so the next lookup searches again."""
        if kind == "artist":
            key = primary_artist(key)
        self._retry_at.pop((kind, key), None)
        for suffix in (".jpg", ".miss", ".credit"):
            self._path(kind, key, suffix).unlink(missing_ok=True)
        if not keep_override:
            self._override(kind, key).unlink(missing_ok=True)
            self._info_path(kind, key, mine=True).unlink(missing_ok=True)
        (self._albums if kind == "album" else self._artists).pop(key, None)
        if kind == "artist":
            self._artist_info.pop(key, None)
            self._drop_thumbs(key)

    def cache_files(self, include_mine: bool = False) -> list[Path]:
        """Downloaded images, "not found" notes and optionally your own picks."""
        suffixes = {".jpg", ".miss", ".credit"} | ({".mine", ".minecredit"} if include_mine else set())
        out = []
        for kind in ("album", "artist"):
            out += [p for p in self._dir(kind).iterdir() if p.suffix in suffixes]
        return out

    def clear_cache(self, include_mine: bool = False) -> int:
        """Clear everything so it's looked up again when needed."""
        self._retry_at.clear()
        n = 0
        for p in self.cache_files(include_mine):
            try:
                p.unlink()
                n += 1
            except OSError:
                pass
        self._albums.clear()
        self._artists.clear()
        self._thumbs.clear()
        self._artist_info.clear()
        self._pending.clear()
        return n

    def shutdown(self):
        self.pool.shutdown(wait=False, cancel_futures=True)

    @staticmethod
    def _load(p: Path) -> QImage | None:
        if p.exists():
            return _read_image(str(p))
        return None


# Images are decoded at most this big; a 3000px cover is 36 MB in memory.
MAX_SIDE = 1200


def _read_image(source) -> QImage | None:
    """File name or bytes -> QImage, scaled down while reading if over MAX_SIDE."""
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QImageReader
    buf = None
    if isinstance(source, (bytes, bytearray)):
        buf = QBuffer()
        buf.setData(QByteArray(bytes(source)))
        buf.open(QIODevice.ReadOnly)
        reader = QImageReader(buf)
    else:
        reader = QImageReader(source)
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid() and max(size.width(), size.height()) > MAX_SIDE:
        size.scale(MAX_SIDE, MAX_SIDE, Qt.KeepAspectRatio)
        reader.setScaledSize(size)
    img = reader.read()
    if buf is not None:
        buf.close()
    if img.isNull() and isinstance(source, (bytes, bytearray)):
        img = QImage.fromData(bytes(source))  # unknown format
    return None if img.isNull() else img


def _image(data: bytes | None) -> QImage | None:
    if not data:
        return None
    return _read_image(data)


def _bytes(img) -> int:
    return img.sizeInBytes() if img is not None and not img.isNull() else 0


def _trim(cache: OrderedDict, budget: int, most: int):
    """Drop the oldest entries until within the memory budget."""
    total = sum(_bytes(v) for v in cache.values())
    while cache and (total > budget or len(cache) > most):
        _k, v = cache.popitem(last=False)
        total -= _bytes(v)


def _order(value, default: list[str], known: dict) -> list[str]:
    """JSON list of enabled sources, in order."""
    if value is None:
        return list(default)
    try:
        lst = json.loads(value) if isinstance(value, str) else list(value)
    except (TypeError, ValueError):
        return list(default)
    return [k for k in lst if k in known]
