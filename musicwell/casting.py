"""One cast menu for Chromecast and Sonos, sharing one small web server."""
from __future__ import annotations

import time

from PySide6.QtCore import QObject, Signal

from musicwell import cast as cast_mod
from musicwell import sonos as sonos_mod

AVAILABLE = cast_mod.AVAILABLE or sonos_mod.AVAILABLE
SONOS_PREFIX = "sonos:"


class CastHub(QObject):
    devicesChanged = Signal()
    connected = Signal(str)
    disconnected = Signal(str)
    volumeChanged = Signal(float)
    error = Signal(str)
    problem = Signal(str, str)

    def __init__(self, port: int = cast_mod.DEFAULT_PORT, parent=None):
        super().__init__(parent)
        self._port = port
        self.chrome = cast_mod.CastController(port, self) if cast_mod.AVAILABLE else None
        self.sonos = sonos_mod.SonosController(port, self) if sonos_mod.AVAILABLE else None
        self.chrome_on = True
        self.sonos_on = True
        self.active = None  # controller playing now
        self._pending = None  # controller we're connecting to
        self.server = None
        self._cover = None
        self._searched_at = None
        for b in self.backends():
            b.devicesChanged.connect(self.devicesChanged)
            b.connected.connect(lambda name, b=b: self._on_connected(b, name))
            b.disconnected.connect(lambda why, b=b: self._on_disconnected(b, why))
            b.volumeChanged.connect(lambda v, b=b: b is self.active and self.volumeChanged.emit(v))
            b.error.connect(self.error)
            b.problem.connect(self.problem)

    def backends(self):
        return [b for b in (self.chrome, self.sonos) if b is not None]

    @property
    def port(self) -> int:
        return self._port

    @port.setter
    def port(self, p: int):
        self._port = p
        for b in self.backends():
            b.port = p

    @property
    def cover_provider(self):
        return self._cover

    @cover_provider.setter
    def cover_provider(self, fn):
        self._cover = fn
        for b in self.backends():
            b.cover_provider = fn
        if self.server:
            self.server.cover_provider = fn

    def set_sonos_addresses(self, text: str):
        if self.sonos:
            self.sonos.addresses = [a.strip() for a in (text or "").replace(";", ",").split(",") if a.strip()]

    @property
    def log_path(self) -> str:
        return cast_mod._setup_log()

    @property
    def is_connected(self) -> bool:
        return self.active is not None and self.active.is_connected

    @property
    def name(self) -> str:
        return self.active.name if self.active else (self._pending.name if self._pending else "")

    @property
    def volume(self) -> float:
        return self.active.volume if self.active else 1.0

    SEARCH_SECONDS = 10  # seconds a search shows as running

    def start_discovery(self):
        if self._searched_at is None:
            self._searched_at = time.monotonic()
        if self.chrome and self.chrome_on:
            self.chrome.start_discovery()
        if self.sonos and self.sonos_on:
            self.sonos.start_discovery()

    def restart_discovery(self):
        self._searched_at = time.monotonic()
        if self.chrome and self.chrome_on:
            self.chrome.restart_discovery()
        if self.sonos and self.sonos_on:
            self.sonos.restart_discovery()

    @property
    def searching(self) -> bool:
        if self.sonos and self.sonos_on and getattr(self.sonos, "_discovering", False):
            return True
        return self._searched_at is not None and time.monotonic() - self._searched_at < self.SEARCH_SECONDS

    @property
    def finding_off(self) -> bool:
        return not ((self.chrome and self.chrome_on) or (self.sonos and self.sonos_on))

    def stop_discovery(self):
        for b in self.backends():
            b.stop_discovery()

    def device_list(self) -> list[tuple[str, str, str]]:
        out = []
        if self.chrome and self.chrome_on:
            out += self.chrome.device_list()
        if self.sonos and self.sonos_on:
            out += [(SONOS_PREFIX + u, n, k) for u, n, k in self.sonos.device_list()]
        return sorted(out, key=lambda d: d[1].lower())

    def connect_to(self, uid: str):
        b = self.sonos if uid.startswith(SONOS_PREFIX) else self.chrome
        if b is None:
            self.error.emit("That kind of speaker isn't supported here.")
            return
        if not self._share_server():
            return
        self._pending = b
        b.connect_to(uid[len(SONOS_PREFIX):] if b is self.sonos else uid)

    def _share_server(self) -> bool:
        if self.server is not None and self.server.port != self._port and self._port \
                and not (self.active and self.active.is_connected):
            self.server.close()  # port changed in Settings
            self.server = None
        if self.server is None:
            try:
                self.server = cast_mod.MediaServer(self._port)
            except OSError as ex:
                self.error.emit(str(ex))
                return False
            cast_mod.log.info("media server listening on port %s", self.server.port)
        self.server.cover_provider = self._cover
        self.server.on_fetch = self._on_fetch
        for b in self.backends():
            b.server = self.server
            b.port = self.server.port  # the port actually opened
        return True

    def _on_fetch(self, key: str, ip: str):
        b = self.active or self._pending
        if b is not None:
            b._fetched.emit(key, ip)

    def disconnect_device(self, reason: str = ""):
        if self.active is not None:
            self.active.disconnect_device(reason)

    def _on_connected(self, b, name: str):
        if self.active is not None and self.active is not b and self.active.is_connected:
            self.active.disconnect_device("switching")
        self.active, self._pending = b, None
        self.connected.emit(name)

    def _on_disconnected(self, b, why: str):
        if b is self.active:
            self.active = None
        elif b is self._pending:
            self._pending = None
        else:
            return
        self.disconnected.emit(why)

    def shutdown(self):
        for b in self.backends():
            b.server = None
            b.shutdown()
        if self.server:
            self.server.close()
            self.server = None
