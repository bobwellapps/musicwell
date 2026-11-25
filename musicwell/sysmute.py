"""Keep Musicwell's mute in sync with the desktop's per-app mute (pactl)."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading

from PySide6.QtCore import QObject, Signal


def _env() -> dict:
    """Environment for pactl without the AppImage's bundled libraries."""
    env = dict(os.environ)
    for k in ("LD_LIBRARY_PATH", "PYTHONHOME", "PYTHONPATH", "QT_PLUGIN_PATH", "QML2_IMPORT_PATH"):
        env.pop(k, None)
    for k, v in list(env.items()):
        if k.startswith("APPIMAGE_ORIGINAL_") and v:
            env[k[len("APPIMAGE_ORIGINAL_"):]] = v
    env["LC_ALL"] = "C"
    return env


class SoundSystemMute(QObject):
    mutedChanged = Signal(bool)  # muted or unmuted from the desktop

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pactl = shutil.which("pactl")
        self.pid = str(os.getpid())
        self._state: dict[str, bool] = {}  # sink input -> muted
        self._want: bool | None = None  # last value we set
        self._lock = threading.Lock()
        self._proc = None
        if self.pactl:
            threading.Thread(target=self._watch, name="musicwell-sysmute", daemon=True).start()

    def _run(self, *args, timeout=3.0) -> str:
        try:
            return subprocess.run([self.pactl, *args], capture_output=True, text=True, timeout=timeout,
                                  env=_env()).stdout
        except Exception:
            return ""

    def _our_clients(self) -> set[str]:
        """Qt's PipeWire output names the process on its client, not its stream."""
        out = self._run("list", "clients")
        mine = set()
        for blk in out.split("Client #")[1:]:
            idx = blk.split("\n", 1)[0].strip()
            if re.search(r'(?:application\.process\.id|pipewire\.sec\.pid) = "%s"' % self.pid, blk):
                mine.add(idx)
        return mine

    def _ours(self) -> dict[str, bool]:
        """Our sink inputs -> muted."""
        out = self._run("list", "sink-inputs")
        clients = None
        found = {}
        for blk in out.split("Sink Input #")[1:]:
            idx = blk.split("\n", 1)[0].strip()
            m = re.search(r'application\.process\.id = "(\d+)"', blk)
            if m:
                ours = m.group(1) == self.pid
            else:
                c = re.search(r"^\s*Client:\s*(\d+)", blk, re.M)
                if clients is None:
                    clients = self._our_clients()
                ours = bool(c and c.group(1) in clients)
            if ours:
                found[idx] = bool(re.search(r"^\s*Mute:\s*yes", blk, re.M))
        return found

    def _watch(self):
        try:
            self._proc = subprocess.Popen([self.pactl, "subscribe"], stdout=subprocess.PIPE,
                                          stderr=subprocess.DEVNULL, text=True, env=_env())
        except Exception:
            return
        self._check()
        for line in self._proc.stdout:
            if "sink-input" in line:
                self._check()

    def _check(self):
        ours = self._ours()
        with self._lock:
            before = self._state
            self._state = ours
            want = self._want
        if not ours:
            return
        new = [i for i in ours if i not in before]
        if want is None and new:
            # The sound server may start the stream muted (it remembers per app); follow it.
            muted = any(ours[i] for i in new)
            with self._lock:
                self._want = muted
            if muted:
                self.mutedChanged.emit(True)
            return
        if want is not None and new:
            # new streams (next song, seek) keep our mute
            for i in new:
                if ours[i] != want:
                    self._run("set-sink-input-mute", i, "1" if want else "0")
            return
        changed = [i for i in ours if i in before and ours[i] != before[i]]
        if changed:
            muted = ours[changed[0]]
            if muted != want:
                with self._lock:
                    self._want = muted
                self.mutedChanged.emit(muted)

    def set_muted(self, muted: bool):
        if not self.pactl:
            return
        with self._lock:
            if self._want == muted:
                return
            self._want = muted

        def work():
            for i, m in self._ours().items():
                if m != muted:
                    self._run("set-sink-input-mute", i, "1" if muted else "0")
        threading.Thread(target=work, name="musicwell-sysmute-set", daemon=True).start()

    def shutdown(self):
        try:
            if self._proc:
                self._proc.kill()
        except Exception:
            pass
