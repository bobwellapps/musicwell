"""The few things that differ between Linux and Windows."""
from __future__ import annotations

import os
import subprocess
import sys

WINDOWS = sys.platform == "win32"
LINUX = sys.platform.startswith("linux")
APP_USER_MODEL_ID = "Musicwell.MusicPlayer"


def name() -> str:
    """e.g. 'Windows 11 (10.0.22631)', 'Ubuntu 24.04 LTS'"""
    import platform
    if WINDOWS:
        rel, ver = platform.release(), platform.version()
        try:
            if rel == "10" and int(ver.split(".")[2]) >= 22000:
                rel = "11"  # Windows 11 still reports "10"
        except (IndexError, ValueError):
            pass
        return f"Windows {rel} ({ver})"
    try:
        with open("/etc/os-release", encoding="utf-8") as fh:
            info = dict(line.rstrip().split("=", 1) for line in fh if "=" in line)
        return info.get("PRETTY_NAME", "Linux").strip('"')
    except OSError:
        return platform.system()


def windows_setup():
    """Windows only: our own taskbar icon and high-DPI drawing."""
    if not WINDOWS:
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        pass


def show_in_folder(path: str) -> bool:
    """Open the file manager with the file selected, where supported."""
    path = os.path.abspath(path)
    if WINDOWS:
        try:
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)],
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return True
        except OSError:
            pass
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    return QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path) if os.path.isfile(path) else path))


def path_key(p: str) -> str:
    """Normalised path for lookups."""
    return os.path.normcase(os.path.normpath(p)) if p else p
