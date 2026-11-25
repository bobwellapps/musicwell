"""Applications menu entry for the AppImage (Linux)."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from musicwell import APP_ID, APP_NAME

ICON_SIZE = 512


def _data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def entry_path() -> Path:
    return _data_home() / "applications" / f"{APP_ID}.desktop"


def icon_path() -> Path:
    return _data_home() / "icons" / "hicolor" / f"{ICON_SIZE}x{ICON_SIZE}" / "apps" / f"{APP_ID}.png"


def known_to_desktop() -> bool:
    """Is there a musicwell.desktop anywhere the desktop looks?"""
    dirs = [_data_home()] + [Path(d) for d in (os.environ.get("XDG_DATA_DIRS")
                                                  or "/usr/local/share:/usr/share").split(":") if d]
    return any((d / "applications" / f"{APP_ID}.desktop").is_file() for d in dirs)


def installed() -> bool:
    return entry_path().is_file()


def _q(arg: str) -> str:
    """Quote an argument for a desktop file."""
    if arg and not any(c in arg for c in ' \t\n"\'\\><~|&;$*?#()`%'):
        return arg
    out = "".join("\\" + c if c in '"`$\\' else c for c in arg)
    out = out.replace("\\", "\\\\")  # the file format escapes backslashes again
    return '"' + out.replace("%", "%%") + '"'


def _exec_line() -> str:
    appimage = os.environ.get("APPIMAGE")
    if appimage:
        return f"{_q(appimage)} %F"
    # Running from source: this Python plus the package's parent folder.
    src = str(Path(__file__).resolve().parent.parent)
    return f"env {_q('PYTHONPATH=' + src)} {_q(sys.executable)} -m musicwell %F"


def _text() -> str:
    return "\n".join([
        "[Desktop Entry]",
        "Type=Application",
        f"Name={APP_NAME}",
        "GenericName=Music Player",
        "Comment=Play and organise your music library",
        f"Exec={_exec_line()}",
        f"Icon={APP_ID}",
        "Terminal=false",
        "Categories=AudioVideo;Audio;Player;Qt;",
        "Keywords=music;audio;player;library;playlist;radio;",
        f"StartupWMClass={APP_ID}",
        "X-Musicwell-Entry=1",
        "",
    ])


def _refresh_menus():
    for cmd in (["update-desktop-database", str(entry_path().parent)], ["kbuildsycoca6"], ["kbuildsycoca5"]):
        if shutil.which(cmd[0]):
            try:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError:
                pass


def install() -> bool:
    import logging
    try:
        entry_path().parent.mkdir(parents=True, exist_ok=True)
        icon_path().parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(__file__).parent / "icon.png", icon_path())
        entry_path().write_text(_text(), encoding="utf-8")
        os.chmod(entry_path(), 0o755)
    except OSError as e:
        logging.getLogger("musicwell").warning("Couldn't add Musicwell to the applications menu: %s", e)
        return False
    logging.getLogger("musicwell").info("Added to the applications menu: %s", entry_path())
    _refresh_menus()
    return True


def remove():
    for p in (entry_path(), icon_path()):
        try:
            p.unlink()
        except OSError:
            pass
    _refresh_menus()


def keep_up_to_date():
    """Update our entry if the AppImage has moved or been renamed."""
    p = entry_path()
    try:
        if p.is_file() and "X-Musicwell-Entry=1" in p.read_text(encoding="utf-8"):
            icon = Path(__file__).parent / "icon.png"
            if p.read_text(encoding="utf-8") != _text() or not icon_path().is_file() \
                    or icon_path().read_bytes() != icon.read_bytes():  # new icon after an update
                install()
    except OSError:
        pass
