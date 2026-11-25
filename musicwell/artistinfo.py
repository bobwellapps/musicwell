"""Artist biography from Wikipedia (found via MusicBrainz and Wikidata)."""
from __future__ import annotations

import hashlib
import html
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QLabel, QMenu, QTextBrowser, QVBoxLayout, QWidget

from musicwell import artsources as AS
from musicwell.paths import cache_dir

KEEP_FOUND = 30 * 86400
KEEP_MISSING = 7 * 86400


def _wiki_title_via_wikidata(artist: str) -> str:
    ids = AS._wikidata_ids(artist)
    if not ids:
        return ""
    data = AS.get_json("https://www.wikidata.org/w/api.php?action=wbgetentities&format=json&props=sitelinks"
                       "&sitefilter=enwiki&ids=" + AS.q("|".join(ids)))
    for qid in ids:
        link = (((data.get("entities") or {}).get(qid) or {}).get("sitelinks") or {}).get("enwiki")
        if link and link.get("title"):
            return link["title"]
    return ""


def _wiki_title_by_name(artist: str) -> str:
    titles = [artist] + [f"{artist} ({x})" for x in ("band", "musician", "singer", "rapper", "group")]
    for params in ("titles=" + AS.q("|".join(titles)),
                   "generator=search&gsrlimit=6&gsrsearch=" + AS.q(f"{artist} band OR singer OR musician OR rapper")):
        for pg in AS._wiki_pages(params):
            title = pg.get("title", "")
            base = re.sub(r"\s*\(.*\)$", "", title)
            if not pg.get("missing") and AS._musical(pg.get("description", "")) and AS.good(base, artist):
                return title
    return ""


def wikipedia(artist: str) -> dict | None:
    title = ""
    try:
        title = _wiki_title_via_wikidata(artist)
    except Exception as ex:
        AS.log(f"artist info: Wikidata for {artist!r}: {ex}")
    if not title:
        title = _wiki_title_by_name(artist)
    if not title:
        return None
    data = AS.get_json("https://en.wikipedia.org/w/api.php?action=query&format=json&formatversion=2"
                       "&redirects=1&prop=extracts%7Cinfo%7Cdescription&exintro=1&explaintext=1"
                       "&exsectionformat=plain&inprop=url&titles=" + AS.q(title))
    pages = (data.get("query") or {}).get("pages") or []
    if not pages or pages[0].get("missing"):
        return None
    pg = pages[0]
    text = (pg.get("extract") or "").strip()
    if not text or "may refer to" in text[:300]:
        return None  # disambiguation page
    text = re.sub(r"\n{3,}", "\n\n", text)
    return {"text": text, "source": "Wikipedia", "url": pg.get("fullurl") or
            "https://en.wikipedia.org/wiki/" + AS.q(pg.get("title", title).replace(" ", "_")),
            "title": pg.get("title", title), "description": pg.get("description", "")}


def facts(artist: str) -> list[str]:
    """From MusicBrainz, e.g. "Band from Manchester, England · 1982–1987 · indie pop"."""
    mbid = AS.mb_artist_id(artist)
    if not mbid:
        return []
    d = AS.mb_json(f"artist/{mbid}?inc=genres&fmt=json")
    out = []
    kind = {"Group": "Band", "Person": "", "Orchestra": "Orchestra", "Choir": "Choir"}.get(d.get("type") or "", "")
    place = ((d.get("begin-area") or {}).get("name") or "")
    area = ((d.get("area") or {}).get("name") or "")
    where = ", ".join(x for x in dict.fromkeys([place, area]) if x)
    if kind and where:
        out.append(f"{kind} from {where}")
    elif where:
        out.append(f"From {where}")
    elif kind:
        out.append(kind)
    ls = d.get("life-span") or {}
    b, e = (ls.get("begin") or "")[:4], (ls.get("end") or "")[:4]
    if b:
        if d.get("type") == "Person":
            out.append(f"Born {b}" + (f" · died {e}" if e else ""))
        else:
            out.append(f"{b}–{e if e else ('?' if ls.get('ended') else 'present')}")
    genres = sorted(d.get("genres") or [], key=lambda g: -(g.get("count") or 0))
    if genres:
        out.append(", ".join(g["name"] for g in genres[:4]))
    return out


def look_up(artist: str, source: str = "wikipedia", key: str = "") -> dict:
    info = None
    problem = ""
    try:
        info = wikipedia(artist)
    except Exception as ex:
        problem = f"Wikipedia: {ex}"
    try:
        fl = facts(artist)
    except Exception:
        fl = []
    if info is None:
        info = {"text": "", "source": "", "url": ""}
    if fl:
        info["facts"] = fl
    info["artist"] = artist
    info["fetched"] = time.time()
    if problem and not info.get("text"):
        info["problem"] = problem
    return info


def _file(artist: str, source: str):
    h = hashlib.sha1((AS.norm(artist) or artist.lower()).encode("utf-8")).hexdigest()[:20]
    return cache_dir() / "artistinfo" / f"{source}-{h}.json"


class ArtistInfoStore(QObject):
    """Looks up each artist once in the background and caches it."""
    ready = Signal(str, object)  # artist, info dict ({} while turned off)
    _done = Signal(str, object)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="musicwell-artistinfo")
        self._mem: dict[str, dict] = {}
        self._busy: set[str] = set()
        self._done.connect(self._on_done)

    def enabled(self) -> bool:
        return self.settings.value("artist_info_online", True, bool)

    def source(self) -> tuple[str, str]:
        return "wikipedia", ""

    def cached(self, artist: str) -> dict | None:
        src, _ = self.source()
        k = src + "|" + artist.lower()
        if k in self._mem:
            return self._mem[k]
        try:
            d = json.loads(_file(artist, src).read_text("utf-8"))
        except (OSError, ValueError):
            return None
        age = time.time() - float(d.get("fetched") or 0)
        if age > (KEEP_FOUND if d.get("text") else KEEP_MISSING):
            return None
        self._mem[k] = d
        return d

    def request(self, artist: str, force: bool = False):
        artist = (artist or "").strip()
        if not artist:
            return
        if not self.enabled():
            self.ready.emit(artist, {"off": True, "artist": artist})
            return
        d = None if force else self.cached(artist)
        if d is not None:
            self.ready.emit(artist, d)
            return
        src, key = self.source()
        k = src + "|" + artist.lower()
        if k in self._busy:
            return
        self._busy.add(k)
        self.ready.emit(artist, {"loading": True, "artist": artist})

        def work():
            d = look_up(AS.primary_artist(artist), src, key)
            d["artist"] = artist
            try:
                self._done.emit(k, d)
            except RuntimeError:
                pass
        self.pool.submit(work)

    def _on_done(self, k: str, d: dict):
        self._busy.discard(k)
        src = k.split("|", 1)[0]
        if not d.get("problem") and not d.get("note"):  # don't cache network or key problems
            self._mem[k] = d
            try:
                f = _file(d["artist"], src)
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(json.dumps(d), "utf-8")
            except OSError:
                pass
        AS.log(f"artist info for {d['artist']!r}: {d.get('source') or 'nothing'} {d.get('problem', '')}")
        self.ready.emit(d["artist"], d)

    def forget_all(self):
        self._mem.clear()

    def shutdown(self):
        self.pool.shutdown(wait=False, cancel_futures=True)


def _link(href: str, text: str, colour) -> str:
    """Accent-coloured link without underline (QLabel ignores colours set on <a>)."""
    c = colour.name() if hasattr(colour, "name") else str(colour)
    return (f"<a href='{html.escape(href)}' style='text-decoration:none'>"
            f"<span style='color:{c}'>{html.escape(text)}</span></a>")


class ArtistInfoView(QWidget):
    """"About the artist" side panel item."""
    refreshRequested = Signal(str)
    optionsChanged = Signal()

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.fill = False
        self.can_fill = True  # not in the play bar
        self.artist = ""
        self.info: dict = {}
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        self.label = QLabel("ABOUT THE ARTIST")
        self.label.setObjectName("NowSectionLabel")
        v.addWidget(self.label)
        self.facts = QLabel("")
        self.facts.setObjectName("NowMeta")
        self.facts.setWordWrap(True)
        v.addWidget(self.facts)
        self.text = QTextBrowser()
        self.text.setObjectName("ArtistInfoText")
        self.text.setOpenLinks(False)
        self.text.setFrameShape(QTextBrowser.NoFrame)
        self.text.setStyleSheet("QTextBrowser{background:transparent;}")
        self.text.document().setDocumentMargin(0)
        self.text.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.text.setContextMenuPolicy(Qt.CustomContextMenu)
        self.text.customContextMenuRequested.connect(self._menu)
        v.addWidget(self.text, 1)
        self.credit = QLabel("")
        self.credit.setObjectName("NowMeta")
        self.credit.setOpenExternalLinks(True)
        self.credit.setTextInteractionFlags(Qt.TextBrowserInteraction)
        v.addWidget(self.credit)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.show_info("", {})

    def options(self) -> dict:
        return {"fill": self.fill}

    def set_options(self, d):
        d = d if isinstance(d, dict) else {}
        self.fill = bool(d.get("fill", False))

    def show_info(self, artist: str, info: dict):
        self.artist, self.info = artist, info or {}
        i = self.info
        self.label.setText(f"ABOUT {artist.upper()}" if artist else "ABOUT THE ARTIST")
        self.facts.setText("  ·  ".join(i.get("facts") or []))
        self.facts.setVisible(bool(i.get("facts")))
        self.credit.setText("")
        if not artist:
            self._plain("Information about the artist playing appears here.")
        elif i.get("off"):
            self._plain("Looking up artists online is switched off (Settings → Online).")
        elif i.get("loading"):
            self._plain(f"Looking up {artist}…")
        elif i.get("text"):
            paras = [p.strip() for p in i["text"].split("\n") if p.strip()]
            col = self.theme.color("text").name()
            body = "".join(f"<p style='margin:0 0 8px 0; color:{col}'>{html.escape(p)}</p>"
                           for p in paras)
            self.text.setHtml(body)
            if i.get("url"):
                lic = " · CC BY-SA" if i.get("source") == "Wikipedia" else ""
                self.credit.setText(f"From {_link(i['url'], i.get('source') or 'the web', self.theme.accent)}{lic}"
                                    + (f"<br>({html.escape(i['note'])})" if i.get("note") else ""))
                self.credit.setWordWrap(True)
        elif i.get("problem"):
            self._plain(f"Couldn't look up {artist} just now ({i['problem']}). Right-click → Look up again.")
        else:
            self._plain(f"Nothing found about {artist} on Wikipedia.")

    def _plain(self, text: str):
        col = self.theme.color("muted").name()
        self.text.setHtml(f"<div style='color:{col}'>{html.escape(text)}</div>")

    def refresh_theme(self):
        self.show_info(self.artist, self.info)

    def set_menus(self, on: bool):
        """Off: right-clicks go to the parent."""
        pol = Qt.CustomContextMenu if on else Qt.NoContextMenu
        self.setContextMenuPolicy(pol)
        self.text.setContextMenuPolicy(pol)

    def _menu(self, pos):
        m = QMenu(self)
        if self.info.get("url"):
            m.addAction(f"Open on {self.info.get('source')}", lambda: QDesktopServices.openUrl(QUrl(self.info["url"])))
        if self.artist:
            m.addAction("Look up again", lambda: self.refreshRequested.emit(self.artist))
        sel = self.text.textCursor().selectedText()
        if sel:
            m.addAction("Copy", self.text.copy)
        if self.can_fill:
            m.addSeparator()
            a = m.addAction("Fill the panel", lambda: (setattr(self, "fill", not self.fill), self.optionsChanged.emit()))
            a.setCheckable(True)
            a.setChecked(self.fill)
        from musicwell.widgets import add_menu_extras
        add_menu_extras(self, m)
        w = self.sender()
        m.exec((w if isinstance(w, QWidget) else self).mapToGlobal(pos))


class ArtistAbout(QWidget):
    """A few lines about the artist on the artist page, with More / Less."""
    refreshRequested = Signal(str)

    LINES = 3

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.full = False
        self.artist = ""
        self.info: dict = {}
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 2, 0, 2)
        v.setSpacing(2)
        self.facts = QLabel("")
        self.facts.setObjectName("NowMeta")
        self.facts.setWordWrap(True)
        v.addWidget(self.facts)
        self.text = QLabel("")
        self.text.setWordWrap(True)
        self.text.setTextFormat(Qt.PlainText)
        self.text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(self.text)
        self.more = QLabel("")
        self.more.setObjectName("NowMeta")
        self.more.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.more.linkActivated.connect(self._link)
        v.addWidget(self.more)
        self._resize_timer = QTimer(self, singleShot=True, interval=30)
        self._resize_timer.timeout.connect(self._apply)

    def show_info(self, artist: str, info: dict):
        if artist != self.artist:
            self.full = False
        self.artist, self.info = artist, info or {}
        self._apply()

    def _apply(self):
        i = self.info
        self.facts.setText("  ·  ".join(i.get("facts") or []))
        self.facts.setVisible(bool(i.get("facts")))
        text = (i.get("text") or "").strip()
        self.setVisible(bool(text or i.get("facts")))
        if not text:
            self.text.hide()
            self.more.hide()
            return
        self.text.show()
        self.more.show()
        line = self.text.fontMetrics().lineSpacing()
        paras = [p for p in text.split("\n") if p.strip()]
        shown = "\n\n".join(paras) if self.full else paras[0]
        self.text.setText(shown)
        width = max(200, self.text.width())
        need = self.text.heightForWidth(width)
        short = not self.full and need > line * self.LINES + 2
        self.text.setMaximumHeight(line * self.LINES + 2 if short else 16777215)
        acc = self.theme.accent
        links = []
        if self.full:
            links.append(_link("less", "Less", acc))
        elif short or len(paras) > 1:
            links.append(_link("more", "More…", acc))
        if i.get("url"):
            lic = " (CC BY-SA)" if i.get("source") == "Wikipedia" else ""
            links.append(_link(i["url"], i["source"], acc) + lic)
        self.more.setText("  ·  ".join(links))

    def _link(self, href: str):
        if href in ("more", "less"):
            self.full = href == "more"
            self._apply()
        else:
            QDesktopServices.openUrl(QUrl(href))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._resize_timer.start()
