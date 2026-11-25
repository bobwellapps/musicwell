"""Chromecast / Google Cast support.

* Discovery: pychromecast's mDNS browser finds Chromecasts, Google/Nest speakers, speaker
  groups and Cast-enabled TVs on the local network.
* Streaming: the speaker fetches the song straight from Musicwell over HTTP. A tiny web
  server on this computer serves only the songs being cast (each behind a random,
  per-session token), with byte ranges so seeking works.
* Control: every pychromecast call runs on one background thread so the window never
  waits on the network; status updates come back as Qt signals.

pychromecast is optional. Without it the cast button is hidden.
"""
from __future__ import annotations

import http.server
import ipaddress
import logging
import logging.handlers
import mimetypes
import os
import secrets
import shutil
import socket
import socketserver
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import unquote

from PySide6.QtCore import QObject, QTimer, Signal

# pychromecast is big, so it's imported in the background on first use.
import importlib.util

AVAILABLE = all(importlib.util.find_spec(m) is not None for m in ("pychromecast", "zeroconf"))
WHY_NOT = "" if AVAILABLE else "pychromecast is not installed"
pychromecast = CastBrowser = SimpleCastListener = zeroconf = None
_LOADED = False


def _load() -> bool:
    """Import pychromecast and zeroconf. Safe from any thread, more than once."""
    global pychromecast, CastBrowser, SimpleCastListener, zeroconf, _LOADED, AVAILABLE, WHY_NOT
    if _LOADED:
        return True
    try:
        import pychromecast as _pc
        from pychromecast.discovery import CastBrowser as _cb, SimpleCastListener as _sl
        import zeroconf as _zc
    except Exception as ex:
        AVAILABLE, WHY_NOT = False, str(ex)
        return False
    pychromecast, CastBrowser, SimpleCastListener, zeroconf = _pc, _cb, _sl, _zc
    _LOADED = True
    return True

from musicwell import tags as tagio
from musicwell.paths import cache_dir

DEFAULT_PORT = 8770
LOAD_TIMEOUT_MS = 12000  # ms for a speaker to start a song before we explain why not

# cast log: ~/.cache/musicwell/cast.log
log = logging.getLogger("musicwell.cast")


def _setup_log() -> str:
    path = str(cache_dir() / "cast.log")
    if not log.handlers:
        try:
            h = logging.handlers.RotatingFileHandler(path, maxBytes=512 * 1024, backupCount=1)
            h.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
            log.addHandler(h)
            log.setLevel(logging.INFO)
            pc = logging.getLogger("pychromecast")
            pc.addHandler(h)
            pc.setLevel(logging.WARNING)
        except OSError:
            pass
    return path


def _service_active(name: str) -> bool:
    if not shutil.which("systemctl"):
        return False
    try:
        r = subprocess.run(["systemctl", "is-active", name], capture_output=True, text=True, timeout=2)
        return r.stdout.strip() == "active"
    except (OSError, subprocess.SubprocessError):
        return False


def firewall_advice(port: int) -> str:
    """A command to open the streaming port for the firewall in use."""
    import sys
    if sys.platform == "win32":
        return ("Windows Firewall may be blocking it. The first time you cast, Windows asks whether Python may "
                "use the network — choose Allow on Private networks. To allow it yourself, open Windows "
                "Security → Firewall & network protection → Allow an app through the firewall, and tick Private "
                f"for Python. Or, in an administrator PowerShell:\n"
                f"    New-NetFirewallRule -DisplayName \"Musicwell casting\" -Direction Inbound -Protocol TCP "
                f"-LocalPort {port} -Action Allow -Profile Private")
    if _service_active("firewalld"):
        return (f"Your computer runs firewalld. Open the port with:\n"
                f"    sudo firewall-cmd --permanent --add-port={port}/tcp && sudo firewall-cmd --reload")
    if _service_active("ufw"):
        return f"Your computer runs ufw. Open the port with:\n    sudo ufw allow {port}/tcp"
    return (f"If you use a firewall, allow incoming TCP connections on port {port}, e.g.\n"
            f"    sudo ufw allow {port}/tcp      or\n"
            f"    sudo firewall-cmd --permanent --add-port={port}/tcp && sudo firewall-cmd --reload")

# formats the Default Media Receiver plays
CASTABLE = {"MP3", "FLAC", "AAC", "Vorbis", "Opus", "WAV"}
CONTENT_TYPES = {
    ".mp3": "audio/mpeg", ".flac": "audio/flac", ".m4a": "audio/mp4", ".m4b": "audio/mp4",
    ".mp4": "audio/mp4", ".aac": "audio/aac", ".ogg": "audio/ogg", ".oga": "audio/ogg",
    ".opus": "audio/ogg", ".wav": "audio/wav", ".aif": "audio/aiff", ".aiff": "audio/aiff",
}


def can_cast(track: dict) -> bool:
    ext = os.path.splitext(track["path"])[1].lower()
    return track.get("format") in CASTABLE and ext in CONTENT_TYPES


def _is_loopback(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip.split("%")[0]).is_loopback
    except ValueError:
        return True


def _route_ip(host: str) -> str | None:
    """Local address used to reach `host` (UDP connect sends nothing)."""
    try:
        infos = socket.getaddrinfo(host, 8009, type=socket.SOCK_DGRAM)
    except OSError:
        return None
    for family, _, _, _, addr in infos:
        s = socket.socket(family, socket.SOCK_DGRAM)
        try:
            s.connect(addr)
            ip = s.getsockname()[0]
            if not _is_loopback(ip):
                return ip
        except OSError:
            continue
        finally:
            s.close()
    return None


def local_ip_for(host: str) -> str:
    """This computer's address on the speaker's network."""
    if host and not _is_loopback(host):
        ip = _route_ip(host)
        if ip:
            return ip
    for probe in ("192.168.0.1", "10.0.0.1", "8.8.8.8"):
        ip = _route_ip(probe)
        if ip:
            return ip
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            ip = info[4][0]
            if not _is_loopback(ip):
                return ip
    except OSError:
        pass
    return "127.0.0.1" if host and _is_loopback(host) else (host and _route_ip(host)) or "127.0.0.1"


def url_host(ip: str) -> str:
    return f"[{ip}]" if ":" in ip else ip


class _Handler(http.server.BaseHTTPRequestHandler):
    server_version = "Musicwell"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _note(self, code: int, key: str | None):
        srv: MediaServer = self.server.media_server
        log.info("speaker %s requested %s → %s (Range: %s)", self.client_address[0],
                 self.path.split("/")[-1], code, self.headers.get("Range"))
        if key and code in (200, 206) and srv.on_fetch:
            srv.on_fetch(key, self.client_address[0])

    def _resolve(self):
        parts = self.path.split("?")[0].strip("/").split("/")
        srv: MediaServer = self.server.media_server
        if len(parts) != 3 or parts[1] != srv.token:
            return None, None
        kind, name = parts[0], unquote(parts[2])
        key = os.path.splitext(name)[0]
        self._key = key if kind == "t" else None
        if kind == "t":
            path = srv.files.get(key)
            if path:
                ctype = CONTENT_TYPES.get(os.path.splitext(path)[1].lower(), "application/octet-stream")
                return ("file", path), ctype
        elif kind == "r":
            url = srv.remote.get(key)
            self._key = key
            if url:
                return ("remote", url), CONTENT_TYPES.get(os.path.splitext(name)[1].lower(), "audio/mpeg")
        elif kind == "a":
            data = srv.art.get(key)
            if data:
                ctype = "image/png" if data[:4] == b"\x89PNG" else "image/jpeg"
                return ("bytes", data), ctype
        return None, None

    def _common_headers(self, ctype: str, length: int):
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")

    def do_HEAD(self):
        self._serve(head=True)

    def do_GET(self):
        self._serve(head=False)

    def _serve(self, head: bool):
        self._key = None
        target, ctype = self._resolve()
        if target is None:
            self._note(404, None)
            self.send_error(404)
            return
        kind, obj = target
        if kind == "remote":
            self._pass_through(obj, ctype, head)
            return
        if kind == "bytes":
            self.send_response(200)
            self._common_headers(ctype, len(obj))
            self.end_headers()
            if not head:
                self.wfile.write(obj)
            return
        try:
            size = os.path.getsize(obj)
            fh = open(obj, "rb")
        except OSError:
            self.send_error(404)
            return
        with fh:
            start, end = 0, size - 1
            rng = self.headers.get("Range")
            if rng and rng.startswith("bytes="):
                a, _, b = rng[6:].split(",")[0].partition("-")
                try:
                    if a:
                        start = int(a)
                        end = int(b) if b else size - 1
                    elif b:  # last N bytes
                        start = max(0, size - int(b))
                    end = min(end, size - 1)
                except ValueError:
                    start, end = 0, size - 1
                if start > end or start >= size:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self._note(206, self._key)
            else:
                self.send_response(200)
                self._note(200, self._key)
            self._common_headers(ctype, end - start + 1)
            self.end_headers()
            if head:
                return
            fh.seek(start)
            left = end - start + 1
            try:
                while left > 0:
                    chunk = fh.read(min(256 * 1024, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass  # speaker closed the connection (seek, skip)


    def _pass_through(self, url: str, ctype: str, head: bool):
        import urllib.request
        import urllib.error
        hdrs = {"User-Agent": "Musicwell"}
        if self.headers.get("Range"):
            hdrs["Range"] = self.headers["Range"]
        try:
            req = urllib.request.Request(url, headers=hdrs, method="HEAD" if head else "GET")
            up = urllib.request.urlopen(req, timeout=15)
        except urllib.error.HTTPError as e:
            self._note(e.code, None)
            self.send_error(e.code if e.code in (404, 416) else 502)
            return
        except Exception:
            self._note(502, None)
            self.send_error(502)
            return
        with up:
            code = up.status
            self.send_response(code)
            self._note(code, self._key)
            utype = (up.headers.get("Content-Type") or "").split(";")[0].strip()
            self.send_header("Content-Type", utype if utype.startswith("audio/") else ctype)
            for h in ("Content-Length", "Content-Range"):
                if up.headers.get(h):
                    self.send_header(h, up.headers[h])
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "no-cache")
            if not up.headers.get("Content-Length"):
                self.send_header("Connection", "close")
                self.close_connection = True
            self.end_headers()
            if head:
                return
            try:
                while True:
                    chunk = up.read(128 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass


class _Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class _Server6(_Server):
    """Listens on IPv6 and IPv4."""
    address_family = socket.AF_INET6

    def server_bind(self):
        try:
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        except (OSError, AttributeError):
            pass
        super().server_bind()


class MediaServer:
    """Serves the songs and covers being cast. Only registered files are reachable."""

    def __init__(self, port: int = DEFAULT_PORT):
        self.token = secrets.token_urlsafe(12)
        self.files: dict[str, str] = {}
        self.art: dict[str, bytes] = {}
        self.remote: dict[str, str] = {}  # key -> online song URL (passed through for Sonos)
        self.on_fetch = None  # callback(key, client_ip), from server threads
        self.cover_provider = None  # callable(track) -> image bytes
        self.httpd = None
        for p in (port, 0):  # fall back to any free port
            for cls, addr in ((_Server6, "::"), (_Server, "0.0.0.0")):
                try:
                    self.httpd = cls((addr, p), _Handler)
                    break
                except OSError:
                    continue
            if self.httpd:
                break
        if self.httpd is None:
            raise OSError("couldn't open a port for casting")
        self.httpd.media_server = self
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, name="musicwell-cast-http", daemon=True)
        self.thread.start()

    def register(self, track: dict, host_ip: str) -> tuple[str, str | None]:
        """(song URL, cover URL or None) for the speaker."""
        key = str(track["id"])
        self.files[key] = track["path"]
        ext = os.path.splitext(track["path"])[1].lower()
        base = f"http://{url_host(host_ip)}:{self.port}"
        url = f"{base}/t/{self.token}/{key}{ext}"
        art = (self.cover_provider(track) if self.cover_provider else None) or tagio.read_artwork(track["path"])
        art_url = None
        if art:
            self.art[key] = art
            art_url = f"{base}/a/{self.token}/{key}.jpg"
        # only the last few songs stay reachable
        for d in (self.files, self.art):
            while len(d) > 8:
                d.pop(next(iter(d)))
        return url, art_url

    def register_path(self, key: str, path: str, host_ip: str) -> str:
        """Serve any file (e.g. a converted copy) under `key`."""
        self.files[key] = path
        while len(self.files) > 8:
            self.files.pop(next(iter(self.files)))
        ext = os.path.splitext(path)[1].lower()
        return f"http://{url_host(host_ip)}:{self.port}/t/{self.token}/{key}{ext}"

    def register_remote(self, key: str, url: str, ext: str, host_ip: str) -> str:
        """Proxy an online song so the speaker gets a local URL with the right extension."""
        self.remote[key] = url
        while len(self.remote) > 8:
            self.remote.pop(next(iter(self.remote)))
        return f"http://{url_host(host_ip)}:{self.port}/r/{self.token}/{key}{ext}"

    def close(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()


class _Listener:
    """pychromecast callbacks (its threads) -> Qt signals (UI thread)."""

    def __init__(self, ctl):
        self.ctl = ctl

    def new_media_status(self, status):
        self.ctl._media_status.emit(status)

    def load_media_failed(self, item, error_code):
        self.ctl._load_result.emit(False, f"error code {error_code}")

    def new_connection_status(self, status):
        self.ctl._conn_status.emit(getattr(status, "status", str(status)))

    def new_cast_status(self, status):
        self.ctl._cast_status.emit(status)


class CastController(QObject):
    devicesChanged = Signal()
    connected = Signal(str)
    disconnected = Signal(str)  # reason ("" when you stopped casting)
    stateChanged = Signal(str)  # PLAYING / PAUSED / BUFFERING / IDLE
    positionChanged = Signal(int)  # ms
    durationChanged = Signal(int)  # ms
    trackFinished = Signal()
    volumeChanged = Signal(float)
    error = Signal(str)
    problem = Signal(str, str)  # title, explanation
    trackFailed = Signal()  # the speaker can't play this file: skip it

    _media_status = Signal(object)
    _conn_status = Signal(str)
    _cast_status = Signal(object)
    _connected_cc = Signal(object, str)
    _failed = Signal(str)
    _devices_signal = Signal()
    _fetched = Signal(str, str)  # track key, speaker address
    _load_result = Signal(bool, str)
    _module_loaded = Signal(bool)

    def __init__(self, port: int = DEFAULT_PORT, parent=None):
        super().__init__(parent)
        self.port = port
        self.devices: dict = {}  # uuid -> CastInfo
        self.zconf = None
        self.browser = None
        self.cc = None
        self.name = ""
        self.server: MediaServer | None = None
        self.host_ip = ""
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="musicwell-cast")
        self.player_state = "IDLE"
        self.position_ms = 0
        self.duration_ms = 0
        self.volume = 1.0
        self._loaded_url = ""
        self._finished_sent = ""
        self._media_status.connect(self._on_media_status)
        self._conn_status.connect(self._on_conn_status)
        self._cast_status.connect(self._on_cast_status)
        self._connected_cc.connect(self._on_connected)
        self._failed.connect(lambda msg: (self.error.emit(msg), self.disconnected.emit(msg)))
        self._devices_signal.connect(self._refresh_devices)
        self._fetched.connect(self._on_fetched)
        self._load_result.connect(self._on_load_result)
        self._loading_module = False
        self._module_loaded.connect(self._on_module_loaded)
        self.log_path = _setup_log()
        self.cover_provider = None
        self.session_ok = False  # the speaker has the current song loaded
        self.fetched_key = ""  # the speaker downloaded the current song
        self.want_playing = False  # applied once the song is loaded
        self._load_title = ""
        self.speaker_ip = ""
        self._last_load = None
        self._load_key = ""
        self._warned = set()
        self.watchdog = QTimer(self)
        self.watchdog.setSingleShot(True)
        self.watchdog.setInterval(LOAD_TIMEOUT_MS)
        self.watchdog.timeout.connect(self._load_timed_out)
        self.poll = QTimer(self)
        self.poll.setInterval(500)
        self.poll.timeout.connect(self._poll)

    def _load_module_thread(self):
        ok = _load()
        try:
            self._module_loaded.emit(ok)
        except RuntimeError:
            pass  # closed while loading

    def start_discovery(self):
        if not AVAILABLE or self.browser is not None:
            return
        if not _LOADED:
            if not self._loading_module:
                self._loading_module = True
                threading.Thread(target=self._load_module_thread, daemon=True,
                                 name="musicwell-cast-import").start()
            return
        try:
            self.zconf = zeroconf.Zeroconf()
            listener = SimpleCastListener(
                add_callback=lambda *a: self._devices_changed(),
                remove_callback=lambda *a: self._devices_changed(),
                update_callback=lambda *a: self._devices_changed())
            self.browser = CastBrowser(listener, self.zconf)
            self.browser.start_discovery()
        except Exception as ex:
            self.error.emit(f"Couldn't search for Cast devices: {ex}")

    def _on_module_loaded(self, ok: bool):
        self._loading_module = False
        if ok:
            self.start_discovery()
        else:
            self.error.emit(f"Casting isn't available: {WHY_NOT}")

    def restart_discovery(self):
        self.stop_discovery()
        self.start_discovery()

    def stop_discovery(self):
        if self.browser is not None:
            try:
                self.browser.stop_discovery()
            except Exception:
                pass
            self.browser = None
        if self.zconf is not None and self.cc is None:
            self.zconf.close()
            self.zconf = None

    def _devices_changed(self):
        # from zeroconf's thread: a queued signal moves to the UI thread
        self._devices_signal.emit()

    def _refresh_devices(self):
        if self.browser is not None:
            self.devices = dict(self.browser.devices)
        self.devicesChanged.emit()

    def device_list(self) -> list[tuple[str, str, str]]:
        """(uuid, name, kind) sorted by name. kind: 'group', 'audio' or 'video'."""
        out = []
        for uuid, info in self.devices.items():
            kind = {"group": "group", "audio": "audio"}.get(info.cast_type or "", "video")
            out.append((str(uuid), info.friendly_name or info.host, kind))
        return sorted(out, key=lambda d: d[1].lower())

    @property
    def is_connected(self) -> bool:
        return self.cc is not None

    def connect_to(self, uuid: str):
        if not _load():
            self.error.emit(f"Casting isn't available: {WHY_NOT}")
            return
        info = next((i for u, i in self.devices.items() if str(u) == uuid), None)
        if info is None:
            self.error.emit("That device has gone away.")
            return
        if self.server is not None and self.server.port != self.port and self.port:
            self.server.close()  # port changed in Settings
            self.server = None
        if self.server is None:
            try:
                self.server = MediaServer(self.port)
            except OSError as ex:
                self.error.emit(str(ex))
                return
            self.server.on_fetch = lambda key, ip: self._fetched.emit(key, ip)
            self.server.cover_provider = self.cover_provider
            log.info("media server listening on port %s", self.server.port)
        name = info.friendly_name or info.host

        def work():
            try:
                cc = pychromecast.get_chromecast_from_cast_info(info, self.zconf, tries=2, timeout=10)
                cc.wait(timeout=15)
                lst = _Listener(self)
                cc.media_controller.register_status_listener(lst)
                cc.register_connection_listener(lst)
                cc.register_status_listener(lst)
                self._connected_cc.emit(cc, local_ip_for(info.host))
            except Exception as ex:
                self._failed.emit(f"Couldn't connect to {name}: {ex}")
        self.name = name
        self.pool.submit(work)

    def _on_connected(self, cc, host_ip):
        self.cc = cc
        self.host_ip = host_ip
        self.speaker_ip = getattr(cc, "cast_info", None) and cc.cast_info.host or ""
        log.info("connected to %s (%s); serving music from %s:%s", self.name, self.speaker_ip,
                 host_ip, self.server.port if self.server else "?")
        status = getattr(cc, "status", None)
        if status is not None and status.volume_level is not None:
            self.volume = float(status.volume_level)
            self.volumeChanged.emit(self.volume)
        self.player_state = "IDLE"
        self.poll.start()
        self.connected.emit(self.name)

    def disconnect_device(self, reason: str = ""):
        cc, self.cc = self.cc, None
        self.poll.stop()
        self.watchdog.stop()
        self._loaded_url = ""
        self.session_ok = False
        log.info("disconnected from %s %s", self.name, f"({reason})" if reason else "")
        if cc is not None:
            def work():
                try:
                    cc.quit_app()
                except Exception:
                    pass
                try:
                    cc.disconnect(timeout=5)
                except Exception:
                    pass
            self.pool.submit(work)
        self.disconnected.emit(reason)

    def shutdown(self):
        if self.cc is not None:
            cc, self.cc = self.cc, None
            try:
                cc.quit_app()
                cc.disconnect(timeout=3)
            except Exception:
                pass
        self.stop_discovery()
        if self.zconf is not None:
            self.zconf.close()
        if self.server:
            self.server.close()
        self.pool.shutdown(wait=False, cancel_futures=True)

    def load(self, track: dict, start_ms: int = 0, autoplay: bool = True):
        if self.cc is None or self.server is None:
            return
        if track.get("stream"):
            self._load_stream(track, autoplay)
            return
        if track.get("remote"):
            self._load_remote(track, start_ms, autoplay)
            return
        url, art_url = self.server.register(track, self.host_ip)
        ext = os.path.splitext(track["path"])[1].lower()
        ctype = CONTENT_TYPES.get(ext) or mimetypes.guess_type(track["path"])[0] or "audio/mpeg"
        metadata = {
            "metadataType": 3,  # MusicTrackMediaMetadata
            "title": track["title"],
            "artist": track["artist"] or "Unknown Artist",
            "albumName": track["album"] or "",
            "albumArtist": track["albumartist"] or track["artist"] or "",
        }
        if track.get("track"):
            metadata["trackNumber"] = track["track"]
        if art_url:
            metadata["images"] = [{"url": art_url}]
        self._loaded_url = url
        self._finished_sent = ""
        self._last_load = (track, start_ms, autoplay)
        self._load_key = str(track["id"])
        self._load_title = track["title"]
        self.session_ok = False
        self.fetched_key = ""
        self.want_playing = autoplay
        self.position_ms = start_ms
        self.duration_ms = int((track.get("length") or 0) * 1000)
        self.player_state = "BUFFERING" if autoplay else "PAUSED"
        self.stateChanged.emit(self.player_state)
        self.watchdog.start()
        mc = self.cc.media_controller
        log.info("LOAD %r (%s) from %s at %.1fs autoplay=%s", track["title"], ctype,
                 url.replace(self.server.token, "<token>"), start_ms / 1000, autoplay)

        def done(ok, response):
            if not ok or (isinstance(response, dict) and response.get("type") in ("LOAD_FAILED", "LOAD_CANCELLED", "INVALID_REQUEST")):
                detail = response.get("type") if isinstance(response, dict) else "no answer"
                self._load_result.emit(False, detail)

        def work():
            try:
                mc.play_media(url, ctype, title=track["title"], thumb=art_url,
                              current_time=start_ms / 1000 if start_ms else None,
                              autoplay=autoplay, stream_type="BUFFERED", metadata=metadata,
                              callback_function=done)
            except Exception as ex:
                self._load_result.emit(False, str(ex))
        self.pool.submit(work)

    STREAM_TYPES = {"MP3": "audio/mpeg", "AAC": "audio/aac", "AAC+": "audio/aac", "OGG": "audio/ogg",
                    "OPUS": "audio/ogg", "FLAC": "audio/flac"}

    def _load_remote(self, track: dict, start_ms: int, autoplay: bool):
        """Online song: the speaker downloads it directly."""
        url = track["path"]
        ext = os.path.splitext(url.split("?")[0])[1].lower()
        ctype = CONTENT_TYPES.get(ext) or "audio/mpeg"
        thumb = (track.get("item") or {}).get("image") or None
        metadata = {"metadataType": 3, "title": track["title"], "artist": track["artist"] or "",
                    "albumName": track["album"] or ""}
        if thumb:
            metadata["images"] = [{"url": thumb}]
        self._loaded_url = url
        self._finished_sent = ""
        self._last_load = (track, start_ms, autoplay)
        self._load_key = "remote:" + url
        self._load_title = track["title"]
        self.session_ok = False
        self.fetched_key = ""
        self.want_playing = autoplay
        self.position_ms = start_ms
        self.duration_ms = int((track.get("length") or 0) * 1000)
        self.player_state = "BUFFERING" if autoplay else "PAUSED"
        self.stateChanged.emit(self.player_state)
        self.watchdog.start()
        mc = self.cc.media_controller

        def done(ok, response):
            if not ok or (isinstance(response, dict) and response.get("type") in ("LOAD_FAILED", "LOAD_CANCELLED", "INVALID_REQUEST")):
                self._load_result.emit(False, response.get("type") if isinstance(response, dict) else "no answer")

        def work():
            try:
                mc.play_media(url, ctype, title=track["title"], thumb=thumb,
                              current_time=start_ms / 1000 if start_ms else None, autoplay=autoplay,
                              stream_type="BUFFERED", metadata=metadata, callback_function=done)
            except Exception as ex:
                self._load_result.emit(False, str(ex))
        self.pool.submit(work)

    def _load_stream(self, track: dict, autoplay: bool):
        """Radio station: the speaker connects to it as a live stream."""
        st = track["station"]
        ctype = "application/x-mpegURL" if st.get("hls") else self.STREAM_TYPES.get(st.get("codec", ""), "audio/mpeg")
        metadata = {"metadataType": 3, "title": track["title"], "artist": track["artist"] or st["name"],
                    "albumName": st["name"]}
        thumb = st.get("favicon") or None
        if thumb:
            metadata["images"] = [{"url": thumb}]
        url = st["url"]
        self._loaded_url = url
        self._finished_sent = ""
        self._last_load = (track, 0, autoplay)
        self._load_key = "radio:" + st["uuid"]
        self._load_title = st["name"]
        self.session_ok = False
        self.fetched_key = ""
        self.want_playing = autoplay
        self.position_ms = 0
        self.duration_ms = 0
        self.player_state = "BUFFERING" if autoplay else "PAUSED"
        self.stateChanged.emit(self.player_state)
        self.watchdog.start()
        mc = self.cc.media_controller
        log.info("LOAD station %r (%s) %s", st["name"], ctype, url)

        def done(ok, response):
            if not ok or (isinstance(response, dict) and response.get("type") in ("LOAD_FAILED", "LOAD_CANCELLED", "INVALID_REQUEST")):
                detail = response.get("type") if isinstance(response, dict) else "no answer"
                self._load_result.emit(False, detail)

        def work():
            try:
                mc.play_media(url, ctype, title=st["name"], thumb=thumb, autoplay=autoplay,
                              stream_type="LIVE", metadata=metadata, callback_function=done)
            except Exception as ex:
                self._load_result.emit(False, str(ex))
        self.pool.submit(work)

    def reload(self, autoplay: bool = True):
        """Send the current song to the speaker again."""
        if self._last_load:
            track, start_ms, _ = self._last_load
            self.load(track, max(start_ms, self.position_ms), autoplay)

    def _on_fetched(self, key: str, ip: str):
        if key == self._load_key:
            self.fetched_key = key

    def _on_load_result(self, ok: bool, detail: str):
        if ok or not self._loaded_url:
            return
        log.warning("load of %r failed: %s (speaker downloaded it: %s)", self._load_title, detail,
                    bool(self.fetched_key))
        self.watchdog.stop()
        self._fail()

    def _load_timed_out(self):
        if self.session_ok or not self._loaded_url:
            return
        log.warning("speaker didn't start %r within %ss (downloaded: %s)", self._load_title,
                    LOAD_TIMEOUT_MS // 1000, bool(self.fetched_key))
        self._fail()

    def _fail(self):
        """The speaker didn't start the song: work out why and report it."""
        downloaded = bool(self.fetched_key)
        self.session_ok = False
        self.player_state = "IDLE"
        self.stateChanged.emit("IDLE")
        if self._load_key.startswith("remote:"):
            self.error.emit(f"{self.name} couldn't play “{self._load_title}” from the Internet Archive. "
                            "It still plays on this computer.")
            return
        if self._load_key.startswith("radio:"):
            self.error.emit(f"{self.name} couldn't play the station “{self._load_title}”. Some stations use "
                            "a format or address speakers can't play; it still plays on this computer.")
            return
        port = self.server.port if self.server else self.port
        if not downloaded:
            if ("net", self.name) in self._warned:
                self.error.emit(f"{self.name} still can't reach Musicwell on port {port}.")
                return
            self._warned.add(("net", self.name))
            addr = f"{url_host(self.host_ip)}:{port}"
            same_net = _same_subnet(self.host_ip, getattr(self, "speaker_ip", ""))
            text = (f"{self.name} connected, but it couldn't download the music from this computer "
                    f"(http://{addr}).\n\nSpeakers fetch each song from Musicwell over your network, "
                    f"so incoming connections on port {port} must be allowed.\n\n{firewall_advice(port)}\n\n")
            if not same_net:
                text += (f"Also check the network: this computer is {self.host_ip} and the speaker is "
                         f"{self.speaker_ip}. A VPN, a guest Wi-Fi network or 'client isolation' on the "
                         f"router can stop them reaching each other.\n\n")
            text += f"Then press play again. Details are logged in {self.log_path}"
            self.problem.emit("The speaker can't reach Musicwell", text)
        else:
            self.error.emit(f"{self.name} downloaded “{self._load_title}” but couldn't play it — skipping.")
            self.trackFailed.emit()

    def _call(self, fn_name: str, *args):
        if self.cc is None:
            return
        mc = self.cc.media_controller

        def work():
            try:
                getattr(mc, fn_name)(*args)
            except Exception as ex:
                self.error.emit(f"The speaker didn't respond: {ex}")
        self.pool.submit(work)

    def play(self):
        self.want_playing = True
        if not self.session_ok:
            # nothing loaded yet: send the song again
            if self.watchdog.isActive():
                self.player_state = "BUFFERING"
                self.stateChanged.emit(self.player_state)
            else:
                self.reload(autoplay=True)
            return
        self.player_state = "PLAYING"
        self._call("play")

    def pause(self):
        self.want_playing = False
        self.player_state = "PAUSED"
        if self.session_ok:
            self._call("pause")
        self.stateChanged.emit(self.player_state)

    def stop(self):
        self._loaded_url = ""
        self.watchdog.stop()
        if self.session_ok:
            self._call("stop")
        self.session_ok = False
        self.player_state = "IDLE"

    def seek(self, ms: int):
        self.position_ms = ms
        if self.session_ok:
            self._call("seek", ms / 1000)
        elif self._last_load:
            track, _, _ = self._last_load
            self._last_load = (track, ms, self.want_playing)

    def set_volume(self, v: float):
        self.volume = max(0.0, min(1.0, v))
        if self.cc is None:
            return
        rc = self.cc.socket_client.receiver_controller
        vol = self.volume
        self.pool.submit(lambda: _quiet(rc.set_volume, vol))

    def set_muted(self, muted: bool):
        if self.cc is None:
            return
        rc = self.cc.socket_client.receiver_controller
        self.pool.submit(lambda: _quiet(rc.set_volume_muted, muted))

    def is_playing(self) -> bool:
        return self.player_state in ("PLAYING", "BUFFERING")

    def _poll(self):
        if self.cc is None:
            return
        st = self.cc.media_controller.status
        if st is None or st.content_id != self._loaded_url or not self._loaded_url:
            return
        if st.player_state in ("PLAYING", "BUFFERING", "PAUSED"):
            ms = int((st.adjusted_current_time or 0) * 1000)
            if ms != self.position_ms:
                self.position_ms = ms
                self.positionChanged.emit(ms)

    def _on_media_status(self, st):
        if not self._loaded_url or st.content_id not in (self._loaded_url, None):
            return
        if (st.content_id == self._loaded_url and st.media_session_id is not None
                and st.player_state in ("PLAYING", "PAUSED", "BUFFERING") and not self.session_ok):
            self.session_ok = True
            self.watchdog.stop()
            log.info("speaker is %s %r", st.player_state.lower(), self._load_title)
            # play/pause pressed while loading: apply it now
            if self.want_playing and st.player_state == "PAUSED":
                self._call("play")
            elif not self.want_playing and st.player_state in ("PLAYING", "BUFFERING"):
                self._call("pause")
        if st.duration:
            d = int(st.duration * 1000)
            if d != self.duration_ms:
                self.duration_ms = d
                self.durationChanged.emit(d)
        state = st.player_state or "IDLE"
        if state == "IDLE" and st.idle_reason == "FINISHED":
            if self._finished_sent != self._loaded_url:
                self._finished_sent = self._loaded_url
                self.player_state = "IDLE"
                self.stateChanged.emit("IDLE")
                self.trackFinished.emit()
            return
        if state == "IDLE" and st.idle_reason == "ERROR" and st.content_id == self._loaded_url:
            self.watchdog.stop()
            self._fail()
            return
        if state != self.player_state and state != "UNKNOWN":
            self.player_state = state
            self.stateChanged.emit(state)

    def _on_cast_status(self, status):
        v = getattr(status, "volume_level", None)
        if v is not None and abs(v - self.volume) > 0.005:
            self.volume = float(v)
            self.volumeChanged.emit(self.volume)

    def _on_conn_status(self, status: str):
        log.info("connection to %s: %s", self.name, status)
        if status in ("LOST", "FAILED", "DISCONNECTED") and self.cc is not None:
            self.cc = None
            self.poll.stop()
            self.watchdog.stop()
            self.session_ok = False
            self._loaded_url = ""
            self.disconnected.emit(f"Lost the connection to {self.name}.")


def _same_subnet(a: str, b: str) -> bool:
    try:
        ia, ib = ipaddress.ip_address(a.split("%")[0]), ipaddress.ip_address(b.split("%")[0])
    except ValueError:
        return True  # unknown: don't raise a false alarm
    if ia.version != ib.version:
        return True
    prefix = 24 if ia.version == 4 else 64
    return ipaddress.ip_network(f"{ia}/{prefix}", strict=False) == ipaddress.ip_network(f"{ib}/{prefix}", strict=False)


def _quiet(fn, *args):
    try:
        fn(*args)
    except Exception:
        pass
