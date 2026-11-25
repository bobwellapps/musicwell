"""The About window: release notes, credits and system details."""
from __future__ import annotations

import html
import os
import sys
import platform

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication, QIcon
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QPushButton, QTabWidget,
                               QTextBrowser, QVBoxLayout, QWidget)

from musicwell import APP_NAME, __version__

# (version, date, headline, details), newest first. Empty until numbered releases start.
RELEASES: list = [
    ("1.0", "2026-11-25", "First release",
     "A music player for Linux that can be as simple or as arranged as you like: every item can go in any panel, "
     "the play bar or the top bar."),
]

CREDITS = [
    ("Made with", [
        ("Python", "https://www.python.org", "PSF License 2.0"),
        ("Qt 6 and PySide6", "https://www.qt.io/qt-for-python", "LGPL 3.0 — the window and sound output"),
        ("FFmpeg", "https://ffmpeg.org", "LGPL 2.1 or later — decoding songs and streams (as built by Qt)"),
        ("ICU", "https://icu.unicode.org", "Unicode / MIT-style — text handling inside Qt"),
        ("Mutagen", "https://github.com/quodlibet/mutagen", "GPL 2.0 or later — reads and writes tags"),
        ("NumPy", "https://numpy.org", "BSD 3-Clause — the equalizer, fades and visualizer (with OpenBLAS, BSD)"),
        ("PyChromecast", "https://github.com/home-assistant-libs/pychromecast", "MIT — casting"),
        ("zeroconf", "https://github.com/python-zeroconf/python-zeroconf", "LGPL 2.1 or later — finding speakers"),
        ("SoCo", "https://github.com/SoCo/soco", "MIT — playing on Sonos speakers"),
        ("lxml", "https://lxml.de", "BSD 3-Clause — reading Sonos replies"),
        ("requests", "https://requests.readthedocs.io", "Apache 2.0 — web requests for Sonos"),
        ("certifi", "https://github.com/certifi/python-certifi", "MPL 2.0 — trusted certificates"),
        ("dbus-next", "https://github.com/altdesktop/python-dbus-next", "MIT — media keys and notifications on Linux"),
    ]),
    ("Information and images from", [
        ("MusicBrainz", "https://musicbrainz.org", "artist and album information (CC0)"),
        ("Cover Art Archive", "https://coverartarchive.org", "album covers"),
        ("Wikimedia Commons and Wikidata", "https://commons.wikimedia.org", "freely licensed artist photos"),
        ("Wikipedia", "https://en.wikipedia.org", "About the artist (text under CC BY-SA, linked to each article)"),
        ("LRCLIB", "https://lrclib.net", "lyrics"),
        ("ListenBrainz", "https://listenbrainz.org", "similar artists"),
        ("radio-browser.info", "https://www.radio-browser.info", "the radio station directory"),
        ("Internet Archive", "https://archive.org", "free music to stream"),
        ("Openverse", "https://openverse.org", "Creative Commons music"),
    ]),
]


def licences_dir():
    """The licences folder next to the musicwell package."""
    from pathlib import Path
    d = Path(__file__).resolve().parent.parent / "licenses"
    if not d.is_dir() and os.environ.get("SNAP"):
        d = Path(os.environ["SNAP"]) / "licenses"
    return d if d.is_dir() else None


def version_text() -> str:
    if not __version__:
        return ""
    date = next((d for v, d, *_ in RELEASES if v == __version__), "")
    if date:
        import datetime
        d = datetime.date.fromisoformat(date)
        return f"Version {__version__}  ·  {d.day} {d.strftime('%B %Y')}"
    return f"Version {__version__}"


def system_info(window=None, problems: bool = True) -> str:
    """Plain text for a bug report (problems=False: just the system, for the log)."""
    from PySide6 import __version__ as pyside_version
    from PySide6.QtCore import qVersion
    lines = [f"{APP_NAME} {__version__}".strip(),
             f"Python {platform.python_version()}  ·  Qt {qVersion()}  ·  PySide6 {pyside_version}"]
    try:
        import mutagen
        lines.append(f"Mutagen {mutagen.version_string}")
    except Exception:
        pass
    lines.append(f"System: {_os_name()}  ·  {platform.machine()}")
    if sys.platform == "win32":
        lines.append(f"Qt platform: {QGuiApplication.platformName()}")
        lines.append(f"Running as: Python files in {os.path.dirname(os.path.dirname(os.path.abspath(__file__)))}"
                     f" (Python at {sys.executable})")
    else:
        desktop = os.environ.get("XDG_CURRENT_DESKTOP") or os.environ.get("DESKTOP_SESSION") or "unknown"
        session = os.environ.get("XDG_SESSION_TYPE") or ("wayland" if os.environ.get("WAYLAND_DISPLAY") else "x11")
        lines.append(f"Desktop: {desktop} ({session})  ·  Qt platform: {QGuiApplication.platformName()}")
        lines.append("Running as: " + ("AppImage" if os.environ.get("APPIMAGE") else
                                       f"snap (revision {os.environ.get('SNAP_REVISION', '?')})"
                                       if os.environ.get("SNAP") else "from the source folder"))
    if window is not None:
        pl = window.player
        if pl.engine is not None:
            lines.append(f"Audio: Musicwell's own output with equalizer ({pl.engine.rate} Hz)")
        else:
            lines.append(f"Audio: plain Qt output — {pl.eq_error or 'equalizer unavailable'}")
        d = getattr(window, "desktop", None)
        if d is not None:
            lines.append("Media keys and desktop controls: " + ("on" if d.mpris_on else (d.error or "off")))
        lines.append(f"Library: {len(window.library.all_tracks()):,} songs in "
                     f"{len(window.library.folders())} folder(s)")
    from musicwell.paths import cache_dir, data_dir, recent_errors
    lines.append(f"Data: {data_dir()}")
    lines.append(f"Cache: {cache_dir()}")
    if not problems:
        lines.append(f"Log: {_log_path()}")
        return "\n".join(lines)
    lines.append(f"Log: {_log_path()}")
    if window is not None:
        lines += [""] + _decade_info(window)
    errs = recent_errors()
    lines += ["", "Recent problems:" if errs else "Recent problems: none"] + ["  " + e for e in errs]
    return "\n".join(lines)


def _log_path() -> str:
    from musicwell import log as mwlog
    return str(mwlog.path())


def _decade_info(window) -> list[str]:
    """How decades are worked out, and what we see for the selected song."""
    from musicwell import library as L
    s = window.settings
    tracks = window.library.all_tracks()
    n = sum(1 for t in tracks if t.get("origyear"))
    out = [f"Decades: setting = {s.value('decade_from', 'year')!s}, in use = {L.DECADE_FROM}; "
           f"original year tag = {L.ORIGINAL_YEAR_TAG.upper() or 'automatic'}; "
           f"{n:,} of {len(tracks):,} songs have an original year"]
    song = None
    try:
        sel = window._focused_table().selected_tracks()
        song = sel[0] if sel else None
    except Exception:
        pass
    song = song or window.player.current
    if song and not song.get("stream") and not song.get("remote"):
        ex = song.get("_extra") or {}
        dates = {k: v for k, v in ex.items() if any(w in k for w in ("orig", "date", "year", "release", "tory", "tdor"))}
        out.append(f"Selected song: {song.get('title')!r} — year {song.get('year')}, original year "
                   f"{song.get('origyear')}, decade {song.get('decade')}")
        out.append(f"  its date tags: {dates or 'none besides the year'}")
        out.append(f"  file: {os.path.basename(song.get('path', ''))}")
    return out


def _os_name() -> str:
    from musicwell.system import name
    return name()


def _history_html(muted: str = "gray") -> str:
    out = []
    for v, d, title, text in RELEASES:
        cur = " &nbsp;<i>— this version</i>" if v == __version__ else ""
        out.append(f"<p style='margin: 0 0 10px 0'><b>{v}</b> &nbsp;<span style='color: {muted}'>{d}</span>"
                   f" &nbsp;<b>{html.escape(title)}</b>{cur}<br>{html.escape(text)}</p>")
    return "".join(out)


def _credits_html(muted: str = "gray") -> str:
    out = [f"<p style='margin: 4px 0 4px 0'><b>Licence</b></p>"
           f"<p style='margin: 0 0 3px 12px'>Musicwell is free software under the "
           f"<a href='https://www.gnu.org/licenses/gpl-3.0.html'>GNU General Public License, version 3 or later</a>"
           f" <span style='color: {muted}'>— you may share and change it under the same licence. "
           f"It comes with no warranty.</span></p>"
           f"<p style='margin: 0 0 3px 12px; color: {muted}'>The Musicwell name and icon may not be used for "
           f"other projects, including modified versions.</p>"]
    for group, items in CREDITS:
        out.append(f"<p style='margin: 8px 0 4px 0'><b>{html.escape(group)}</b></p>")
        for name, url, note in items:
            out.append(f"<p style='margin: 0 0 3px 12px'><a href='{url}'>{html.escape(name)}</a>"
                       f" <span style='color: {muted}'>— {html.escape(note)}</span></p>")
    out.append(f"<p style='margin: 12px 0 0 0; color: {muted}'>Smaller libraries these use (urllib3, protobuf, "
               "idna and others) and every licence text are listed in the Licences folder (the button below). "
               "Qt, FFmpeg and zeroconf are used as separate libraries that you can replace; their source is "
               "at the links above.</p>")
    out.append(f"<p style='margin: 8px 0 0 0; color: {muted}'>Musicwell plays radio stations' and archives' own "
               "streams and keeps nothing from them. Images found online follow the licences of their sources; "
               "photo credits show under the photo.</p>")
    return "".join(out)


class AboutDialog(QDialog):
    def __init__(self, window=None, parent=None):
        super().__init__(parent or window)
        self.window = window
        self.setWindowTitle(f"About {APP_NAME}")
        self.setMinimumSize(560, 520)
        lay = QVBoxLayout(self)
        lay.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(16)
        icon = QLabel()
        p = os.path.join(os.path.dirname(__file__), "icon.png")
        icon.setPixmap(QIcon(p).pixmap(QSize(84, 84)) if os.path.exists(p) else self.windowIcon().pixmap(84, 84))
        head.addWidget(icon, 0, Qt.AlignTop)
        words = QVBoxLayout()
        words.setSpacing(2)
        name = QLabel(APP_NAME)
        name.setStyleSheet("font-size: 22pt; font-weight: 700;")
        self.version = QLabel(version_text())
        self.version.setTextInteractionFlags(Qt.TextSelectableByMouse)
        tag = QLabel("A simple or fully customisable music player for Linux, for those who either want a straightforward player or those who like to fully arrange and customise, with full control over layouts and music management.")
        tag.setWordWrap(True)
        tag.setObjectName("EmptyText")
        words.addWidget(name)
        if self.version.text():
            words.addWidget(self.version)
        words.addSpacing(4)
        words.addWidget(tag)
        if window is not None:
            tracks = window.library.all_tracks()
            albums = {(t.get("albumartist") or t.get("artist"), t.get("album")) for t in tracks if t.get("album")}
            artists = {t.get("artist_key") or t.get("artist") for t in tracks if t.get("artist")}
            lib = QLabel(f"Your library: {len(tracks):,} songs  ·  {len(albums):,} albums  ·  {len(artists):,} artists")
            lib.setObjectName("EmptyText")
            words.addWidget(lib)
        head.addLayout(words, 1)
        lay.addLayout(head)

        # the theme stylesheet doesn't cover these text boxes
        th = getattr(window, "theme", None)
        c = (lambda k: th.color(k).name()) if th is not None else (lambda k: {
            "surface": "palette(base)", "text": "palette(text)", "border": "palette(mid)", "muted": "gray",
            "accent": "palette(link)"}[k])
        box_style = (f"QTextBrowser {{ background: {c('surface')}; color: {c('text')}; "
                     f"border: 1px solid {c('border')}; border-radius: 8px; padding: 6px 8px; }}")
        muted = c("muted") if th is not None else "gray"

        def browser(text_html: str) -> QTextBrowser:
            b = QTextBrowser()
            b.setStyleSheet(box_style)
            b.setOpenExternalLinks(True)
            if th is not None:
                b.document().setDefaultStyleSheet(f"a {{ color: {c('accent')}; text-decoration: none; }}")
            b.setHtml(text_html)
            return b

        self.tabs = QTabWidget()
        if RELEASES:
            self.tabs.addTab(browser(_history_html(muted)), "What's new")
        cred = browser(_credits_html(muted))
        credw = QWidget()
        cl = QVBoxLayout(credw)
        cl.setContentsMargins(0, 6, 0, 0)
        cl.addWidget(cred)
        crow = QHBoxLayout()
        crow.addStretch()
        lic = QPushButton("Licences…")
        lic.setToolTip("The licence of everything Musicwell is built with, and their full texts")
        lic.clicked.connect(self._open_licences)
        lic.setEnabled(licences_dir() is not None)
        crow.addWidget(lic)
        cl.addLayout(crow)
        self.tabs.addTab(credw, "Credits")
        sysw = QWidget()
        sl = QVBoxLayout(sysw)
        sl.setContentsMargins(0, 6, 0, 0)
        self.info = QTextBrowser()
        self.info.setStyleSheet(box_style)
        self.info.setPlainText(system_info(window))
        sl.addWidget(self.info)
        row = QHBoxLayout()
        copy = QPushButton("Copy")
        copy.setToolTip("Copy these details, e.g. to paste into a bug report")
        copy.clicked.connect(self._copy)
        self.copied = QLabel("")
        self.copied.setObjectName("EmptyText")
        folder = QPushButton("Open data folder")
        folder.clicked.connect(self._open_data)
        logb = QPushButton("Open log")
        logb.setToolTip("Musicwell's diary of what happened — songs played, problems, casting. Attach it to "
                        "a bug report (it stays on this computer unless you share it)")
        logb.clicked.connect(self._open_log)
        row.addWidget(copy)
        row.addWidget(self.copied)
        row.addStretch()
        row.addWidget(logb)
        row.addWidget(folder)
        sl.addLayout(row)
        self.tabs.addTab(sysw, "System")
        lay.addWidget(self.tabs, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _copy(self):
        QGuiApplication.clipboard().setText(self.info.toPlainText())
        self.copied.setText("Copied")

    def _open_licences(self):
        d = licences_dir()
        if d is None:
            return
        notes = d / "THIRD-PARTY-NOTICES.md"
        if not (notes.exists() and QDesktopServices.openUrl(QUrl.fromLocalFile(str(notes)))):
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))

    def _open_log(self):
        from musicwell import log as mwlog
        p = mwlog.path()
        for h in mwlog.log.handlers:
            h.flush()
        if not (p.exists() and QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))):
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(p.parent)))

    def _open_data(self):
        from musicwell.paths import data_dir
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(data_dir())))
