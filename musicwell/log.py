"""Plain-text log in ~/.local/state/musicwell (Windows: %APPDATA%\\Musicwell\\logs), 1 MB plus two old files."""
from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import threading
import time
from pathlib import Path

log = logging.getLogger("musicwell")
_started = time.monotonic()
_qt_seen: dict[str, int] = {}
_rate: dict[str, float] = {}

# Qt messages that are just noise
_QT_NOISE = ("propagateSizeHints", "This plugin does not support", "QFont::setPointSize",
             "qt.qpa.wayland: Wayland does not support QWindow::requestActivate",
             "Could not find the Qt platform plugin \"wayland\"", "QSocketNotifier: Can only be used",
             "QObject::startTimer: Timers cannot be started from another thread")


def log_dir() -> Path:
    if sys.platform == "win32":
        from musicwell.paths import data_dir
        p = data_dir() / "logs"
    else:
        from musicwell import APP_ID
        base = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
        p = Path(base) / APP_ID
    p.mkdir(parents=True, exist_ok=True)
    return p


def path() -> Path:
    return log_dir() / "musicwell.log"


class _Area(logging.Filter):
    def filter(self, record):
        n = record.name
        record.area = "app" if n == "musicwell" else n.split(".", 1)[1] if n.startswith("musicwell.") else n
        return True


def setup():
    """Start logging (once, early in main)."""
    if getattr(setup, "done", False):
        return
    setup.done = True
    try:
        h = logging.handlers.RotatingFileHandler(path(), maxBytes=1024 * 1024, backupCount=2, encoding="utf-8")
    except OSError:
        return
    h.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-7s %(area)-8s %(message)s", "%Y-%m-%d %H:%M:%S"))
    h.addFilter(_Area())
    log.addHandler(h)
    log.setLevel(logging.INFO)
    logging.getLogger("musicwell.images").propagate = False  # it has its own log
    # errors in background threads
    def thread_hook(args):
        if args.exc_type is SystemExit:
            return
        import traceback
        from musicwell.paths import log_error
        name = args.thread.name if args.thread else "?"
        log_error(f"In the background ({name}):\n" + "".join(
            traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))
    threading.excepthook = thread_hook
    log.info("──────── Musicwell started ────────")


def started(window=None):
    """Log versions and system info."""
    try:
        from musicwell.about import system_info
        for line in system_info(window, problems=False).splitlines():
            if line.strip():
                log.info(line)
    except Exception:
        log.exception("Couldn't describe the system")


def stopped():
    mins = (time.monotonic() - _started) / 60
    log.info("Musicwell closed after %s", f"{mins:.0f} minutes" if mins >= 1 else "less than a minute")
    for h in log.handlers:
        h.flush()


def qt_messages():
    """Send Qt warnings to the log (each once, then counted)."""
    from PySide6.QtCore import QtMsgType, qInstallMessageHandler

    def handler(kind, context, message):
        try:
            if sys.__stderr__ is not None:
                sys.__stderr__.write(message + "\n")
        except Exception:
            pass
        if kind in (QtMsgType.QtDebugMsg, QtMsgType.QtInfoMsg):
            return
        if any(n in message for n in _QT_NOISE):
            return
        n = _qt_seen.get(message, 0) + 1
        _qt_seen[message] = n
        if n == 1:
            level = logging.WARNING if kind == QtMsgType.QtWarningMsg else logging.ERROR
            logging.getLogger("musicwell.qt").log(level, message)
        elif n in (10, 100, 1000):
            logging.getLogger("musicwell.qt").warning("(%d times so far) %s", n, message)
    qInstallMessageHandler(handler)


def now_and_then(key: str, seconds: float = 60.0) -> bool:
    """True at most once every `seconds` for `key`."""
    t = time.monotonic()
    if t - _rate.get(key, -1e9) < seconds:
        return False
    _rate[key] = t
    return True


def tail(lines: int = 200) -> str:
    """The end of the log, e.g. for a bug report."""
    try:
        text = path().read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(text[-lines:])


def song(t: dict | None) -> str:
    """artist – title (format), without folders"""
    if not t:
        return "nothing"
    if t.get("stream"):
        return f"station {t.get('title') or t.get('url')}"
    who = t.get("artist") or "?"
    ext = os.path.splitext(t.get("path") or "")[1].lstrip(".").upper()
    return f"{who} – {t.get('title') or '?'}" + (f" ({ext})" if ext else "")
