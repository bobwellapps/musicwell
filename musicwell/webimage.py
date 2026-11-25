"""Pictures you drag or paste from a web browser, used as artist photos or album covers."""
from __future__ import annotations

import base64
import re
import threading
import urllib.parse
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QEvent, QIODevice, QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QImage

ENGINES = {
    "duckduckgo": ("DuckDuckGo", "https://duckduckgo.com/?iax=images&ia=images&q={q}"),
    "google": ("Google", "https://www.google.com/search?tbm=isch&q={q}"),
    "bing": ("Bing", "https://www.bing.com/images/search?q={q}"),
}
DEFAULT_ENGINE = "duckduckgo"
MAX_BYTES = 15 * 1024 * 1024
MAX_SIDE = 1600  # larger images are scaled down
SMALL = 200  # below this we warn that it's small


def engine_of(settings) -> str:
    e = str(settings.value("web_image_engine", DEFAULT_ENGINE) or DEFAULT_ENGINE)
    return e if e in ENGINES else DEFAULT_ENGINE


def search_url(kind: str, artist: str, album: str = "", engine: str = DEFAULT_ENGINE) -> str:
    words = f"{artist} {album} album cover" if kind == "album" else f"{artist} musician"
    return ENGINES.get(engine, ENGINES[DEFAULT_ENGINE])[1].format(q=urllib.parse.quote_plus(words.strip()))


def open_search(kind: str, artist: str, album: str = "", engine: str = DEFAULT_ENGINE) -> bool:
    return QDesktopServices.openUrl(QUrl(search_url(kind, artist, album, engine)))


def accepts(mime) -> bool:
    """Does this drag or clipboard hold an image or an image URL?"""
    if mime is None:
        return False
    if mime.hasImage():
        return True
    if mime.hasUrls() and any(u.scheme() in ("http", "https", "file", "data") for u in mime.urls()):
        return True
    if mime.hasHtml() and "<img" in mime.html().lower():
        return True
    if mime.hasText() and re.match(r"\s*(https?://|data:image/)\S+\s*$", mime.text() or ""):
        return True
    return False


def _unwrap(url: str) -> str:
    """Search result link -> the image itself (Google imgres, Bing mediaurl, DDG iu)."""
    try:
        parts = urllib.parse.urlsplit(url)
        qs = urllib.parse.parse_qs(parts.query)
    except ValueError:
        return url
    for k in ("imgurl", "mediaurl", "u", "img_url", "image_url"):
        v = qs.get(k)
        if v and v[0].lower().startswith(("http://", "https://")):
            if k != "u" or "duckduckgo" in (parts.hostname or ""):
                return v[0]
    return url


def _looks_like_image(url: str) -> bool:
    return bool(re.search(r"\.(jpe?g|png|webp|gif|bmp|avif)(\?|#|$)", url, re.I))


def extract(mime) -> dict | None:
    """Read everything usable from a drop or the clipboard right away (drag data is gone afterwards). Returns {"urls", "files", "data"}."""
    if not accepts(mime):
        return None
    urls, files = [], []
    if mime.hasUrls():
        for u in mime.urls():
            if u.isLocalFile():
                files.append(u.toLocalFile())
            elif u.scheme() in ("http", "https", "data"):
                urls.append(u.toString())
    if mime.hasHtml():
        for src in re.findall(r"""<img[^>]+src\s*=\s*["']([^"']+)["']""", mime.html(), re.I):
            urls.append(src.replace("&amp;", "&"))
    if mime.hasText():
        t = (mime.text() or "").strip()
        if re.match(r"(https?://|data:image/)\S+$", t):
            urls.append(t)
    full = [_unwrap(u) for u in urls]
    # full-size image behind a search result first, then image URLs, then pages
    ranked = sorted(dict.fromkeys(full), key=lambda u: (0 if u not in urls else 1 if _looks_like_image(u)
                                                         else 3 if u.startswith("data:") else 2))
    data = b""
    if mime.hasImage():
        img = mime.imageData()
        if isinstance(img, QImage) and not img.isNull():
            data = _encode(img, "PNG")
    return {"urls": ranked, "files": files, "data": data}


def _encode(img: QImage, fmt: str = "JPEG") -> bytes:
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, fmt, 92 if fmt == "JPEG" else -1)
    buf.close()
    return bytes(ba)


def tidy(data: bytes) -> tuple[bytes, QImage] | None:
    """Decode the image and re-encode as JPEG (PNG if transparent), scaled down if needed."""
    img = QImage.fromData(data)
    if img.isNull():
        return None
    if max(img.width(), img.height()) > MAX_SIDE:
        img = img.scaled(MAX_SIDE, MAX_SIDE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    elif data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n":
        return data, img
    return _encode(img, "PNG" if img.hasAlphaChannel() else "JPEG"), img


def _page_picture(html: str, base: str) -> str:
    """A web page was dropped: use its og:image."""
    for pat in (r"""<meta[^>]+(?:property|name)\s*=\s*["'](?:og:image|og:image:url|twitter:image)["'][^>]*content\s*=\s*["']([^"']+)""",
                r"""<meta[^>]+content\s*=\s*["']([^"']+)["'][^>]*(?:property|name)\s*=\s*["'](?:og:image|twitter:image)["']"""):
        m = re.search(pat, html, re.I)
        if m:
            return urllib.parse.urljoin(base, m.group(1).replace("&amp;", "&"))
    return ""


def fetch(found: dict) -> tuple[bytes, dict, str]:
    """(bytes, info, "") or (b"", {}, error). Runs in a background thread."""
    from musicwell import artsources as S
    why = ""
    for f in found.get("files", []):
        try:
            data = Path(f).read_bytes()[:MAX_BYTES]
        except OSError as e:
            why = f"couldn't read {Path(f).name}: {e.strerror or e}"
            continue
        t = tidy(data)
        if t:
            return t[0], {"source": "file"}, ""
        why = f"{Path(f).name} isn't a picture Musicwell can read"
    for url in found.get("urls", [])[:6]:
        if url.startswith("data:"):
            m = re.match(r"data:image/[\w.+-]+;base64,(.*)$", url, re.S)
            if not m:
                continue
            try:
                t = tidy(base64.b64decode(m.group(1)))
            except (ValueError, TypeError):
                continue
            if t:
                return t[0], {"source": "web"}, ""
            continue
        try:
            data = S.get_bytes(url, MAX_BYTES)
        except Exception as e:
            why = f"the picture couldn't be downloaded ({e})"
            continue
        t = tidy(data)
        if t:
            return t[0], {"source": "web", "page": url}, ""
        head = data[:400000].decode("utf-8", "replace")
        if "<html" in head.lower() or "<meta" in head.lower():
            pic = _page_picture(head, url)
            if pic:
                try:
                    t = tidy(S.get_bytes(pic, MAX_BYTES))
                except Exception:
                    t = None
                if t:
                    return t[0], {"source": "web", "page": url}, ""
            why = "that's a web page, not a picture — open the picture itself (right-click it → Open image in new tab) and drag or copy that"
        else:
            why = "that isn't a picture Musicwell can read"
    if found.get("data"):
        t = tidy(found["data"])
        if t:
            return t[0], {"source": "web"}, ""
    return b"", {}, why or "there's no picture in it"


class Taker(QObject):
    """Fetch a dropped or pasted image in the background."""
    done = Signal(bytes, dict, str)  # image, info, note (e.g. "it's small: 120 × 90")
    failed = Signal(str)

    _live: set = set()

    def __init__(self, found: dict, parent=None):
        super().__init__(parent)
        Taker._live.add(self)
        self.found = found

    def start(self):
        def work():
            data, info, why = fetch(self.found)
            if data:
                img = QImage.fromData(data)
                note = f"it's quite small ({img.width()} × {img.height()})" \
                    if not img.isNull() and max(img.width(), img.height()) < SMALL else ""
                self.done.emit(data, info, note)
            else:
                self.failed.emit(why)
            Taker._live.discard(self)
        threading.Thread(target=work, name="musicwell-webimage", daemon=True).start()
        return self


_INTERNAL = ("application/x-qabstractitemmodeldatalist", "application/x-musicwell-tracks")


class DropTarget(QObject):
    """Accept image drops. target_at(pos) says whose picture it would be, take() is set by the window."""

    def __init__(self, widget, target_at, take):
        super().__init__(widget)
        self.widget, self.target_at, self.take = widget, target_at, take
        widget.setAcceptDrops(True)
        widget.installEventFilter(self)

    def _ok(self, ev) -> bool:
        mime = ev.mimeData()
        if any(mime.hasFormat(f) for f in _INTERNAL) or not accepts(mime) or not self.take():
            return False
        pos = ev.position().toPoint() if hasattr(ev, "position") else ev.pos()
        return self.target_at(pos) is not None

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t in (QEvent.DragEnter, QEvent.DragMove, QEvent.Drop):
            mime = ev.mimeData()
            if any(mime.hasFormat(f) for f in _INTERNAL):
                return False  # our own drags are the widget's business
        if t in (QEvent.DragEnter, QEvent.DragMove):
            if self._ok(ev):
                ev.setDropAction(Qt.CopyAction)
                ev.accept()
            else:
                ev.ignore()
            if t == QEvent.DragEnter:
                ev.accept()
            return True
        if t == QEvent.Drop and self._ok(ev):
            pos = ev.position().toPoint()
            target = self.target_at(pos)
            found = extract(ev.mimeData())
            ev.setDropAction(Qt.CopyAction)
            ev.accept()
            if found and target:
                self.take()(*target, found)
            return True
        return False

