"""Data locations: XDG directories on Linux, %APPDATA%\\Musicwell on Windows."""
import os
import sys
from pathlib import Path

from musicwell import APP_ID, APP_NAME

WINDOWS = sys.platform == "win32"


def _xdg(var: str, fallback: str) -> Path:
    base = os.environ.get(var) or os.path.join(os.path.expanduser("~"), fallback)
    p = Path(base) / APP_ID
    p.mkdir(parents=True, exist_ok=True)
    return p


def _windows(var: str, fallback: str, *sub: str) -> Path:
    base = os.environ.get(var) or os.path.join(os.path.expanduser("~"), "AppData", fallback)
    p = Path(base, APP_NAME, *sub)
    p.mkdir(parents=True, exist_ok=True)
    return p


def data_dir() -> Path:
    if WINDOWS:
        return _windows("APPDATA", "Roaming")
    return _xdg("XDG_DATA_HOME", ".local/share")


def cache_dir() -> Path:
    if WINDOWS:
        return _windows("LOCALAPPDATA", "Local", "Cache")
    return _xdg("XDG_CACHE_HOME", ".cache")


def settings():
    """Settings: ~/.config/musicwell/musicwell.conf on Linux, an .ini file in %APPDATA%\\Musicwell on Windows (not the Registry)."""
    from PySide6.QtCore import QSettings
    if WINDOWS:
        return QSettings(str(data_dir() / f"{APP_ID}.ini"), QSettings.IniFormat)
    return QSettings(APP_ID, APP_ID)


def db_path() -> Path:
    return data_dir() / "library.db"


OLD_IDS = ("listenwell", "tunewell")  # previous names of the app
OLD_NAMES = ("Listenwell",)  # Windows only had Listenwell


def move_from_old_name():
    """On first start, move data over from the old app name."""
    import shutil
    if WINDOWS:
        return _move_on_windows()
    home = os.path.expanduser("~")
    bases = {
        "config": os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config"),
        "data": os.environ.get("XDG_DATA_HOME") or os.path.join(home, ".local/share"),
        "cache": os.environ.get("XDG_CACHE_HOME") or os.path.join(home, ".cache"),
    }
    moved = {}
    marks = {"config": APP_ID + ".conf", "data": "library.db", "cache": None}
    for kind, base in bases.items():
        new = os.path.join(base, APP_ID)
        if os.path.exists(new):  # already exists, unless it's only an empty start
            mark = marks[kind]
            if (mark and os.path.exists(os.path.join(new, mark))) or (not mark and os.listdir(new)):
                continue
        old = next((os.path.join(base, o) for o in OLD_IDS if os.path.isdir(os.path.join(base, o))), None)
        if old is None:
            continue
        try:
            if kind == "cache" and not os.path.exists(new):
                shutil.move(old, new)
            else:
                shutil.copytree(old, new, dirs_exist_ok=True)
            moved[old] = new
        except OSError:
            continue
    conf_dir = os.path.join(bases["config"], APP_ID)
    for old_id in OLD_IDS:
        old_conf = os.path.join(conf_dir, old_id + ".conf")
        new_conf = os.path.join(conf_dir, APP_ID + ".conf")
        if os.path.join(bases["config"], old_id) in moved and os.path.exists(old_conf):
            try:
                with open(old_conf, encoding="utf-8", errors="surrogateescape") as fh:
                    text = fh.read()
                for old, new in moved.items():  # update saved paths that point to the old folders
                    text = text.replace(old + "/", new + "/")
                with open(new_conf, "w", encoding="utf-8", errors="surrogateescape") as fh:
                    fh.write(text)
                os.remove(old_conf)
            except OSError:
                pass
    return moved


def _move_on_windows():
    import shutil
    moved = {}
    for var, fallback in (("APPDATA", "Roaming"), ("LOCALAPPDATA", "Local")):
        base = os.environ.get(var) or os.path.join(os.path.expanduser("~"), "AppData", fallback)
        new = os.path.join(base, APP_NAME)
        if os.path.exists(new):
            continue
        old = next((os.path.join(base, o) for o in OLD_NAMES if os.path.isdir(os.path.join(base, o))), None)
        if old is None:
            continue
        try:
            if var == "LOCALAPPDATA":
                shutil.move(old, new)
            else:
                shutil.copytree(old, new)
                for o in OLD_IDS:
                    ini = os.path.join(new, o + ".ini")
                    if os.path.exists(ini):
                        os.replace(ini, os.path.join(new, APP_ID + ".ini"))
                        break
            moved[old] = new
        except OSError:
            continue
    return moved


def error_log_path() -> Path:
    return cache_dir() / "errors.log"


def log_error(text: str):
    """Keep the last few hundred error lines (About -> System) and write them to the main log."""
    import logging
    import time
    logging.getLogger("musicwell").error(text.rstrip())
    try:
        p = error_log_path()
        old = p.read_text(encoding="utf-8", errors="replace").splitlines()[-300:] if p.exists() else []
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        new = old + [f"[{stamp}] {line}" for line in text.rstrip().splitlines()]
        p.write_text("\n".join(new[-400:]) + "\n", encoding="utf-8")
    except OSError:
        pass


def recent_errors(n: int = 25) -> list[str]:
    try:
        return error_log_path().read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    except OSError:
        return []


def install_error_log():
    """Log any uncaught exception, including ones in slots."""
    import sys
    import traceback
    previous = sys.excepthook

    def hook(kind, value, tb):
        log_error("".join(traceback.format_exception(kind, value, tb)))
        previous(kind, value, tb)
    sys.excepthook = hook

