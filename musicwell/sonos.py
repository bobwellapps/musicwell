"""Sonos support: play on Sonos speakers the way Musicwell plays on Chromecasts.

* Discovery: SoCo finds the Sonos system on your network (and, if that's blocked, the address you
  give in Settings). Each room or group of rooms is one entry — music goes to the group's
  coordinator and every speaker in the group plays it.
* Streaming: the speaker fetches songs from Musicwell's small web server (the same one used for
  Chromecast, same port). Songs Sonos can't play as they are — above 24-bit/48 kHz, or in a format it
  doesn't know (Opus, WavPack…) — are converted to a CD-quality WAV first. Online songs are passed
  through this computer; radio stations are played by the speaker straight from the station.
* Control: every SoCo call runs on one background thread; the speaker is asked what it's doing
  twice a second and the answers come back as Qt signals.

SoCo is optional. Without it Sonos speakers simply aren't listed.
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
import struct
import time
from concurrent.futures import ThreadPoolExecutor
from xml.sax.saxutils import escape

from PySide6.QtCore import QObject, QTimer, QUrl, Signal

from musicwell import cast as cast_mod
from musicwell.paths import cache_dir

AVAILABLE = importlib.util.find_spec("soco") is not None
WHY_NOT = "" if AVAILABLE else "the soco package is not installed"
soco = None

log = cast_mod.log

LOAD_TIMEOUT_MS = 15000
# formats Sonos plays as-is
NATIVE = {"MP3", "FLAC", "AAC", "ALAC", "Vorbis", "WAV", "AIFF"}
NATIVE_EXT = {".mp3", ".flac", ".m4a", ".m4b", ".mp4", ".aac", ".ogg", ".oga", ".wav", ".aif", ".aiff"}
MAX_RATE = 48000
MAX_BITS = 24


def _load() -> bool:
    global soco, AVAILABLE, WHY_NOT
    if soco is not None:
        return True
    try:
        import soco as _s
    except Exception as ex:
        AVAILABLE, WHY_NOT = False, str(ex)
        return False
    soco = _s
    return True


def needs_conversion(track: dict) -> bool:
    """Sonos can't play this file as-is."""
    ext = os.path.splitext(track.get("path") or "")[1].lower()
    if track.get("format") not in NATIVE or ext not in NATIVE_EXT:
        return True
    return int(track.get("samplerate") or 0) > MAX_RATE or int(track.get("bitdepth") or 0) > MAX_BITS


def can_cast(track: dict) -> bool:
    """Anything we can decode can go to Sonos, converted if needed."""
    return bool(track.get("path")) and os.path.exists(track["path"])


def hms(ms: int) -> str:
    s = max(0, int(ms // 1000))
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}"


def parse_hms(text: str) -> int:
    try:
        parts = [int(float(x)) for x in str(text or "").split(":")]
    except ValueError:
        return 0
    ms = 0
    for p in parts:
        ms = ms * 60 + p
    return ms * 1000 if len(parts) > 1 else 0


def didl(url: str, ctype: str, title: str, artist: str = "", album: str = "", art: str = "",
         length_s: float = 0, radio: bool = False) -> str:
    """DIDL metadata Sonos shows (title, artist, album, cover)."""
    cls = "object.item.audioItem.audioBroadcast" if radio else "object.item.audioItem.musicTrack"
    dur = f' duration="{hms(int(length_s * 1000))}.000"' if length_s and not radio else ""
    parts = [f'<res protocolInfo="http-get:*:{escape(ctype)}:*"{dur}>{escape(url)}</res>']
    if art:
        parts.append(f"<upnp:albumArtURI>{escape(art)}</upnp:albumArtURI>")
    parts.append(f"<dc:title>{escape(title or 'Untitled')}</dc:title>")
    parts.append(f"<upnp:class>{cls}</upnp:class>")
    if artist:
        parts.append(f"<dc:creator>{escape(artist)}</dc:creator>")
    if album:
        parts.append(f"<upnp:album>{escape(album)}</upnp:album>")
    if radio:
        parts.append('<desc id="cdudn" nameSpace="urn:schemas-rinconnetworks-com:metadata-1-0/">'
                     'SA_RINCON65031_</desc>')
    return ('<DIDL-Lite xmlns:dc="http://purl.org/dc/elements/1.1/" '
            'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/" '
            'xmlns:r="urn:schemas-rinconnetworks-com:metadata-1-0/" '
            'xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/">'
            '<item id="-1" parentID="-1" restricted="true">' + "".join(parts) + "</item></DIDL-Lite>")


def _lowpass(taps: int, cutoff: float):
    """Windowed-sinc low-pass (cutoff as a fraction of the input rate)."""
    import numpy as np
    n = np.arange(taps) - (taps - 1) / 2
    h = np.sinc(2 * cutoff * n) * np.blackman(taps)
    return (h / h.sum()).astype(np.float32)


class Converter(QObject):
    """Decode a song and write a 16-bit WAV Sonos can play (resampled to 44.1/48 kHz if higher). One at a time."""
    ready = Signal(str, str)  # source path, WAV path ("" on failure)
    progress = Signal(str, float)  # source path, 0..1

    KEEP = 4

    def __init__(self, parent=None):
        super().__init__(parent)
        self.dir = cache_dir() / "sonos"
        self._dec = None
        self._job = None
        self._queue: list[tuple[str, float]] = []

    @staticmethod
    def target_rate(rate: int) -> int:
        if rate <= MAX_RATE:
            return rate
        for base in (44100, 48000):
            if rate % base == 0:
                return base
        return MAX_RATE

    def out_path(self, path: str) -> str:
        try:
            st = os.stat(path)
            tag = f"{path}|{st.st_size}|{int(st.st_mtime)}"
        except OSError:
            tag = path
        return str(self.dir / (hashlib.sha1(tag.encode("utf-8", "replace")).hexdigest()[:20] + ".wav"))

    def convert(self, path: str, length_s: float = 0):
        out = self.out_path(path)
        if os.path.exists(out) and os.path.getsize(out) > 44:
            self.ready.emit(path, out)
            return
        if self._job and self._job["src"] == path:
            return
        self._queue = [(p, l) for p, l in self._queue if p != path] + [(path, length_s)]
        if self._dec is None:
            QTimer.singleShot(0, self._next)

    def busy_with(self, path: str) -> bool:
        return bool(self._job and self._job["src"] == path) or any(p == path for p, _ in self._queue)

    def cancel(self):
        self._queue.clear()
        if self._dec is not None:
            self._finish(failed=True, quiet=True)

    def _next(self):
        if self._dec is not None or not self._queue:
            return
        try:
            import numpy  # noqa: F401
            from PySide6.QtMultimedia import QAudioDecoder
        except ImportError:
            path, _ = self._queue.pop(0)
            self.ready.emit(path, "")
            return
        path, length = self._queue.pop(0)
        os.makedirs(self.dir, exist_ok=True)
        out = self.out_path(path)
        try:
            fh = open(out + ".part", "wb")
        except OSError:
            self.ready.emit(path, "")
            return
        fh.write(b"\0" * 44)
        self._job = {"src": path, "out": out, "fh": fh, "length_us": max(1, int(length * 1e6)),
                     "rate": 0, "ch": 0, "to": 0, "tail": None, "in": 0, "frames": 0, "h": None,
                     "factor": 1, "last_p": -1.0}
        d = QAudioDecoder(self)
        d.bufferReady.connect(self._on_buffer)
        d.finished.connect(lambda: self._finish())
        d.error.connect(lambda *_: self._finish(failed=True))
        d.setSource(QUrl.fromLocalFile(path))
        self._dec = d
        d.start()

    def _on_buffer(self):
        import numpy as np
        from PySide6.QtMultimedia import QAudioFormat
        d, job = self._dec, self._job
        if d is None or job is None:
            return
        buf = d.read()
        if not buf.isValid():
            return
        fmt = buf.format()
        kind = fmt.sampleFormat()
        raw = buf.constData()
        if kind == QAudioFormat.Float:
            a = np.frombuffer(raw, dtype=np.float32).astype(np.float32)
        elif kind == QAudioFormat.Int16:
            a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        elif kind == QAudioFormat.Int32:
            a = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
        elif kind == QAudioFormat.UInt8:
            a = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
        else:
            return
        ch = max(1, fmt.channelCount())
        rate = fmt.sampleRate() or 44100
        if not job["rate"]:
            job["rate"], job["ch"], job["to"] = rate, ch, self.target_rate(rate)
            if job["to"] != rate and rate % job["to"] == 0:
                job["factor"] = rate // job["to"]
                job["h"] = _lowpass(16 * job["factor"] + 1, 0.45 / job["factor"])
        if ch != job["ch"] or rate != job["rate"]:
            return  # format changed mid-stream: skip the odd buffer
        a = a[: len(a) // ch * ch].reshape(-1, ch)
        a = self._resample(a)
        if len(a):
            tpdf = (np.random.random_sample(a.shape) - np.random.random_sample(a.shape)).astype(np.float32)
            pcm = np.clip(np.round(a * 32767.0 + tpdf), -32768, 32767).astype("<i2")
            job["fh"].write(pcm.tobytes())
            job["frames"] += len(pcm)
        p = min(1.0, buf.startTime() / job["length_us"])
        if p - job["last_p"] >= 0.05:
            job["last_p"] = p
            self.progress.emit(job["src"], p)

    def _resample(self, a):
        import numpy as np
        job = self._job
        rate, to = job["rate"], job["to"]
        if to == rate:
            return a
        if job["h"] is not None:
            h, f = job["h"], job["factor"]
            L = len(h)
            tail = job["tail"] if job["tail"] is not None else np.zeros((L - 1, a.shape[1]), np.float32)
            x = np.concatenate([tail, a])
            job["tail"] = x[-(L - 1):]
            g0 = job["in"] - (L - 1)  # frame number of x[0]
            job["in"] += len(a)
            n_valid = len(x) - L + 1  # y[k] is filtered frame g0 + k + L - 1
            first = (-(g0 + L - 1)) % f
            idx = np.arange(first, n_valid, f)
            if not len(idx):
                return np.zeros((0, a.shape[1]), np.float32)
            out = np.empty((len(idx), a.shape[1]), np.float32)
            for c in range(a.shape[1]):
                out[:, c] = np.convolve(x[:, c], h[::-1], mode="valid")[idx]
            return out
        # uneven ratio (rare): linear resampling per buffer
        n_out = int(round(len(a) * to / rate))
        if n_out <= 0:
            return np.zeros((0, a.shape[1]), np.float32)
        src = np.linspace(0, len(a) - 1, n_out)
        return np.stack([np.interp(src, np.arange(len(a)), a[:, c]) for c in range(a.shape[1])], 1).astype(np.float32)

    def _finish(self, failed: bool = False, quiet: bool = False):
        d, job = self._dec, self._job
        if job is None:
            return
        self._dec, self._job = None, None
        if d is not None:
            try:
                d.stop()
            except RuntimeError:
                pass
            d.deleteLater()
        fh = job["fh"]
        ok = not failed and job["frames"] > 0
        try:
            if ok:
                ch, rate = job["ch"], job["to"]
                data = job["frames"] * ch * 2
                fh.seek(0)
                fh.write(b"RIFF" + struct.pack("<I", 36 + data) + b"WAVEfmt " +
                         struct.pack("<IHHIIHH", 16, 1, ch, rate, rate * ch * 2, ch * 2, 16) +
                         b"data" + struct.pack("<I", data))
            fh.close()
            if ok:
                os.replace(job["out"] + ".part", job["out"])
            else:
                os.remove(job["out"] + ".part")
        except OSError:
            ok = False
        self._tidy()
        if not quiet:
            self.ready.emit(job["src"], job["out"] if ok else "")
        QTimer.singleShot(0, self._next)

    def _tidy(self):
        try:
            files = sorted((os.path.join(self.dir, f) for f in os.listdir(self.dir) if f.endswith(".wav")),
                           key=os.path.getmtime)
            for f in files[:-self.KEEP]:
                os.remove(f)
        except OSError:
            pass


class SonosController(QObject):
    """Plays on a Sonos room or group; same interface as cast.CastController."""
    devicesChanged = Signal()
    connected = Signal(str)
    disconnected = Signal(str)
    stateChanged = Signal(str)
    positionChanged = Signal(int)
    durationChanged = Signal(int)
    trackFinished = Signal()
    volumeChanged = Signal(float)
    error = Signal(str)
    problem = Signal(str, str)
    trackFailed = Signal()

    _found = Signal(object)  # {uid: (coordinator, label, members)}
    _status = Signal(object, int)  # status dict, load number
    _load_result = Signal(bool, str, int)
    _connected_dev = Signal(object, str, str)
    _failed = Signal(str)
    _fetched = Signal(str, str)
    _vol_done = Signal()

    TIMEOUT = 6

    def __init__(self, port: int = cast_mod.DEFAULT_PORT, parent=None):
        super().__init__(parent)
        self.port = port
        self.devices: dict = {}  # uid -> (coordinator SoCo, label, members)
        self.dev = None  # coordinator we play on
        self.name = ""
        self.members = 1
        self.server = None
        self.host_ip = ""
        self.speaker_ip = ""
        self.addresses: list[str] = []  # speaker addresses from Settings
        self.cover_provider = None
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="musicwell-sonos")
        self.disc_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="musicwell-sonos-find")
        self.log_path = cast_mod._setup_log()
        self.player_state = "IDLE"
        self.position_ms = 0
        self.duration_ms = 0
        self.volume = 0.3
        self.muted = False
        self.session_ok = False
        self.want_playing = False
        self.fetched_key = ""
        self._load_n = 0  # which load the answers belong to
        self._loaded_url = ""
        self._match = ""
        self._is_radio = False
        self._last_load = None
        self._load_key = ""
        self._load_title = ""
        self._local_track = None
        self._converted = set()
        self._finished_n = -1
        self._pos_base = (0, time.monotonic())
        self._polling = False
        self._discovering = False
        self._last_discovery = 0.0
        self._vol_pending = None
        self._vol_busy = False
        self._vol_quiet_until = 0.0
        self._stopped_by_us = False
        self._ticks = 0
        self._warned = set()
        self._other = 0
        self.converter = Converter(self)
        self.converter.ready.connect(self._on_converted)
        self.converter.progress.connect(self._on_convert_progress)
        self._found.connect(self._on_found)
        self._status.connect(self._on_status)
        self._load_result.connect(self._on_load_result)
        self._connected_dev.connect(self._on_connected)
        self._failed.connect(lambda msg: (self.error.emit(msg), self.disconnected.emit(msg)))
        self._fetched.connect(self._on_fetched)
        self._vol_done.connect(self._push_volume)
        self.watchdog = QTimer(self, singleShot=True, interval=LOAD_TIMEOUT_MS)
        self.watchdog.timeout.connect(self._load_timed_out)
        self.poll = QTimer(self, interval=500)
        self.poll.timeout.connect(self._tick)

    def start_discovery(self, force: bool = False):
        if not AVAILABLE or self._discovering:
            return
        if not force and self.devices and time.monotonic() - self._last_discovery < 30:
            return
        self._discovering = True
        addresses = list(self.addresses)
        scan = force and not addresses  # "Search again" also probes the network

        def work():
            found = {}
            try:
                if not _load():
                    return
                zones = set(soco.discover(timeout=3, allow_network_scan=scan) or ())
                for ip in addresses:
                    try:
                        z = soco.SoCo(ip)
                        _ = z.uid
                        zones.add(z)
                    except Exception as ex:
                        log.warning("no Sonos speaker answered at %s: %s", ip, ex)
                groups = {}
                for z in zones:
                    try:
                        for g in z.all_groups:  # the whole system from any one speaker
                            groups[g.uid] = g
                    except Exception as ex:
                        log.warning("Sonos speaker %s: %s", getattr(z, "ip_address", "?"), ex)
                for g in groups.values():
                    try:
                        c = g.coordinator
                        if c is None:
                            continue
                        if c.uid in found:
                            continue
                        members = [m for m in g.members if getattr(m, "is_visible", True)]
                        if not members:
                            continue  # Boost / Bridge: nothing to play on
                        found[c.uid] = (c, " + ".join(sorted(m.player_name for m in members)), len(members))
                    except Exception as ex:
                        log.warning("Sonos group %s: %s", getattr(g, "uid", "?"), ex)
            except Exception as ex:
                log.warning("Sonos search failed: %s", ex)
            finally:
                try:
                    self._found.emit(found)
                except RuntimeError:
                    pass
        self.disc_pool.submit(work)

    def restart_discovery(self):
        self.start_discovery(force=True)

    def stop_discovery(self):
        pass

    def _on_found(self, found: dict):
        self._discovering = False
        self._last_discovery = time.monotonic()
        if found or not self.devices:
            self.devices = found
        self.devicesChanged.emit()

    def device_list(self) -> list[tuple[str, str, str]]:
        out = [(uid, label, "sonosgroup" if n > 1 else "sonos") for uid, (_c, label, n) in self.devices.items()]
        return sorted(out, key=lambda d: d[1].lower())

    @property
    def is_connected(self) -> bool:
        return self.dev is not None

    def connect_to(self, uid: str):
        if not _load():
            self.error.emit(f"Sonos isn't available: {WHY_NOT}")
            return
        entry = self.devices.get(uid)
        if entry is None:
            self.error.emit("That speaker has gone away.")
            return
        dev, label, members = entry
        if self.server is None:
            try:
                self.server = cast_mod.MediaServer(self.port)
            except OSError as ex:
                self.error.emit(str(ex))
                return
            self.server.on_fetch = lambda key, ip: self._fetched.emit(key, ip)
            self.server.cover_provider = self.cover_provider
        self.name = label
        self.members = members

        def work():
            try:
                ip = dev.ip_address
                info = dev.get_current_transport_info()  # it answers
                _ = info
                vol = (dev.group.volume if members > 1 else dev.volume)
                self._vol_start = int(vol or 0)
                self._connected_dev.emit(dev, cast_mod.local_ip_for(ip), ip)
            except Exception as ex:
                self._failed.emit(f"Couldn't connect to {label}: {ex}")
        self.pool.submit(work)

    def _on_connected(self, dev, host_ip: str, ip: str):
        self.dev = dev
        self.host_ip, self.speaker_ip = host_ip, ip
        self.volume = getattr(self, "_vol_start", 30) / 100
        log.info("connected to Sonos %s (%s); serving music from %s:%s", self.name, ip, host_ip,
                 self.server.port if self.server else "?")
        self.player_state = "IDLE"
        self._other = 0
        self.poll.start()
        self.volumeChanged.emit(self.volume)
        self.connected.emit(self.name)

    def disconnect_device(self, reason: str = ""):
        dev, self.dev = self.dev, None
        self.poll.stop()
        self.watchdog.stop()
        self.converter.cancel()
        self._loaded_url = ""
        self.session_ok = False
        self._load_n += 1
        log.info("disconnected from Sonos %s %s", self.name, f"({reason})" if reason else "")
        if dev is not None and reason in ("", "switching"):
            self.pool.submit(lambda: _quiet(dev.stop))
        self.disconnected.emit(reason)

    def shutdown(self):
        dev, self.dev = self.dev, None
        self.poll.stop()
        self.converter.cancel()
        if dev is not None:
            _quiet(dev.stop)
        if self.server:
            self.server.close()
            self.server = None
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.disc_pool.shutdown(wait=False, cancel_futures=True)

    def _begin(self, track: dict, start_ms: int, autoplay: bool, key: str, title: str, radio: bool = False):
        self._load_n += 1
        self._sent_at = 0
        self._last_load = (track, start_ms, autoplay)
        self._load_key, self._load_title, self._is_radio = key, title, radio
        self.session_ok = False
        self.fetched_key = ""
        self.want_playing = autoplay
        self.position_ms = start_ms
        self._pos_base = (start_ms, time.monotonic())
        self.duration_ms = 0 if radio else int((track.get("length") or 0) * 1000)
        self._stopped_by_us = False
        self.player_state = "BUFFERING" if autoplay else "PAUSED"
        self.stateChanged.emit(self.player_state)
        self.watchdog.start()

    def load(self, track: dict, start_ms: int = 0, autoplay: bool = True):
        if self.dev is None or self.server is None:
            return
        if track.get("stream"):
            self._load_stream(track, autoplay)
            return
        if track.get("remote"):
            self._load_remote(track, start_ms, autoplay)
            return
        key = str(track["id"])
        self._begin(track, start_ms, autoplay, key, track["title"])
        self._local_track = track
        if needs_conversion(track) or key in self._converted:
            self._convert(track)
            return
        url, art = self.server.register(track, self.host_ip)
        self._send(url, track, art, start_ms, autoplay)

    def _convert(self, track: dict):
        self._converted.add(str(track["id"]))
        self.watchdog.stop()  # converting takes as long as it takes
        log.info("converting %r for Sonos (%s, %s Hz, %s-bit)", track["title"], track.get("format"),
                 track.get("samplerate"), track.get("bitdepth"))
        self.converter.convert(track["path"], float(track.get("length") or 0))

    def _on_convert_progress(self, path: str, p: float):
        t = self._local_track
        if t and t["path"] == path and self._load_key == str(t["id"]) and p < 1:
            self.error.emit(f"Getting “{t['title']}” ready for {self.name}… {int(p * 100)} %")

    def _on_converted(self, path: str, out: str):
        t = self._local_track
        if self.dev is None or not t or t["path"] != path or self._load_key != str(t["id"]):
            return
        if not out:
            self.error.emit(f"“{t['title']}” can't be played on {self.name} — skipping.")
            self.player_state = "IDLE"
            self.stateChanged.emit("IDLE")
            self.trackFailed.emit()
            return
        key = str(t["id"])
        url = self.server.register_path(key, out, self.host_ip)
        _, art = self.server.register(t, self.host_ip)
        self.server.files[key] = out  # register() pointed it back at the original
        _, start_ms, autoplay = self._last_load
        self.watchdog.start()
        self._send(url, t, art, self.position_ms or start_ms, self.want_playing)

    def _send(self, url: str, track: dict, art: str | None, start_ms: int, autoplay: bool,
              ctype: str | None = None, radio: bool = False, title: str = ""):
        self._loaded_url = url
        self._match = url.split("://", 1)[-1]
        ext = os.path.splitext(url.split("?")[0])[1].lower()
        ctype = ctype or cast_mod.CONTENT_TYPES.get(ext, "audio/mpeg")
        meta = didl(url, ctype, title or track["title"], track.get("artist") or "",
                    track.get("album") or "", art or "", float(track.get("length") or 0), radio)
        dev, n = self.dev, self._load_n
        log.info("SONOS LOAD %r %s at %.1fs autoplay=%s", title or track["title"],
                 url.replace(self.server.token, "<token>") if self.server else url, start_ms / 1000, autoplay)

        def work():
            try:
                dev.play_uri(url, meta=meta, start=False, force_radio=radio, timeout=self.TIMEOUT)
                if start_ms and not radio:
                    try:
                        dev.seek(hms(start_ms))
                    except Exception:
                        pass  # needs buffering first: try once more
                if autoplay:
                    dev.play()
                    if start_ms and not radio:
                        _quiet(dev.seek, hms(start_ms))
                self._load_result.emit(True, "", n)
            except Exception as ex:
                self._load_result.emit(False, str(ex), n)
        self.pool.submit(work)

    def _load_remote(self, track: dict, start_ms: int, autoplay: bool):
        url = track["path"]
        ext = os.path.splitext(url.split("?")[0])[1].lower()
        if ext not in cast_mod.CONTENT_TYPES:
            ext = ".mp3"
        key = "r" + hashlib.sha1(url.encode()).hexdigest()[:16]
        self._begin(track, start_ms, autoplay, "remote:" + key, track["title"])
        self._local_track = None
        local = self.server.register_remote(key, url, ext, self.host_ip)
        self._remote_name = (track.get("item") or {}).get("badge") or "online"
        art = (track.get("item") or {}).get("image") or ""
        self._send(local, track, art, start_ms, autoplay)

    def _load_stream(self, track: dict, autoplay: bool):
        st = track["station"]
        self._begin(track, 0, autoplay, "radio:" + str(st.get("uuid")), st["name"], radio=True)
        self._local_track = None
        t = dict(track, artist="", album="", length=0)
        self._send(st["url"], t, st.get("favicon") or "", 0, autoplay,
                   ctype="audio/mpeg", radio=True, title=st["name"])
        self._match = st["url"].split("://", 1)[-1]

    def reload(self, autoplay: bool = True):
        if self._last_load:
            track, start_ms, _ = self._last_load
            self.load(track, max(start_ms, self.position_ms), autoplay)

    def _on_fetched(self, key: str, ip: str):
        if key == self._load_key or "remote:" + key == self._load_key:
            self.fetched_key = self._load_key

    def _on_load_result(self, ok: bool, detail: str, n: int):
        if n != self._load_n:
            return
        if ok:
            self._sent_at = time.monotonic()
            self.poll_now()
            return
        log.warning("Sonos load of %r failed: %s (downloaded: %s)", self._load_title, detail,
                    bool(self.fetched_key))
        self.watchdog.stop()
        self._fail(detail)

    def _load_timed_out(self):
        if self.session_ok or not self._loaded_url:
            return
        log.warning("Sonos didn't start %r within %ss (downloaded: %s)", self._load_title,
                    LOAD_TIMEOUT_MS // 1000, bool(self.fetched_key))
        self._fail("timed out")

    def _fail(self, detail: str = ""):
        downloaded = bool(self.fetched_key)
        self.session_ok = False
        t = self._local_track
        # fetched but refused (e.g. 24-bit on S1): convert and retry
        if t and downloaded and str(t["id"]) not in self._converted and self._load_key == str(t["id"]):
            log.info("%s fetched %r but didn't play it: converting", self.name, t["title"])
            self._convert(t)
            return
        self.player_state = "IDLE"
        self.stateChanged.emit("IDLE")
        if self._is_radio:
            self.error.emit(f"{self.name} couldn't play the station “{self._load_title}”. Some stations use "
                            "a format or address Sonos can't play; it still plays on this computer.")
            return
        port = self.server.port if self.server else self.port
        if not downloaded:
            if self._load_key.startswith("remote:"):
                if "502" in detail or "404" in detail:
                    self.error.emit(f"Couldn't get “{self._load_title}” from {getattr(self, '_remote_name', 'online')} "
                                    "— skipping.")
                    self.trackFailed.emit()
                    return
            if ("net", self.name) in self._warned:
                self.error.emit(f"{self.name} still can't reach Musicwell on port {port}.")
                return
            self._warned.add(("net", self.name))
            addr = f"{cast_mod.url_host(self.host_ip)}:{port}"
            text = (f"{self.name} answered, but it couldn't download the music from this computer "
                    f"(http://{addr}).\n\nSonos speakers fetch each song from Musicwell over your network, "
                    f"so incoming connections on port {port} must be allowed.\n\n"
                    f"{cast_mod.firewall_advice(port)}\n\n")
            if not cast_mod._same_subnet(self.host_ip, self.speaker_ip):
                text += (f"Also check the network: this computer is {self.host_ip} and the speaker is "
                         f"{self.speaker_ip}. A VPN, a guest Wi-Fi network or 'client isolation' on the "
                         f"router can stop them reaching each other.\n\n")
            if detail and detail != "timed out":
                text += f"The speaker said: {detail}\n\n"
            text += f"Then press play again. Details are logged in {self.log_path}"
            self.problem.emit("The Sonos speaker can't reach Musicwell", text)
        else:
            self.error.emit(f"{self.name} downloaded “{self._load_title}” but couldn't play it — skipping.")
            self.trackFailed.emit()

    def _call(self, fn):
        dev = self.dev
        if dev is None:
            return

        def work():
            try:
                fn(dev)
            except Exception as ex:
                log.warning("Sonos call failed: %s", ex)
        self.pool.submit(work)

    def play(self):
        self.want_playing = True
        if not self.session_ok:
            if self.watchdog.isActive() or (self._local_track and
                                            self.converter.busy_with(self._local_track["path"])):
                self.player_state = "BUFFERING"
                self.stateChanged.emit(self.player_state)
            else:
                self.reload(autoplay=True)
            return
        self.player_state = "PLAYING"
        self._pos_base = (self.position_ms, time.monotonic())
        self.stateChanged.emit("PLAYING")
        self._call(lambda d: d.play())

    def pause(self):
        self.want_playing = False
        self.player_state = "PAUSED"
        if self.session_ok:
            radio = self._is_radio
            self._call(lambda d: d.stop() if radio else d.pause())  # Sonos can't pause live radio
        self.stateChanged.emit(self.player_state)

    def stop(self):
        self._loaded_url = ""
        self._load_n += 1
        self.watchdog.stop()
        self._stopped_by_us = True
        if self.session_ok:
            self._call(lambda d: d.stop())
        self.session_ok = False
        self.player_state = "IDLE"

    def seek(self, ms: int):
        self.position_ms = ms
        self._pos_base = (ms, time.monotonic())
        if self.session_ok and not self._is_radio:
            self._call(lambda d: d.seek(hms(ms)))
        elif self._last_load:
            track, _, _ = self._last_load
            self._last_load = (track, ms, self.want_playing)

    def set_volume(self, v: float):
        self.volume = max(0.0, min(1.0, v))
        self._vol_quiet_until = time.monotonic() + 2.5  # don't let a poll undo a volume change in progress
        self._vol_pending = int(round(self.volume * 100))
        if not self._vol_busy:
            self._push_volume()

    def _push_volume(self):
        dev, val, group = self.dev, self._vol_pending, self.members > 1
        self._vol_pending = None
        if dev is None or val is None:
            self._vol_busy = False
            return
        self._vol_busy = True

        def work():
            try:
                if group:
                    dev.group.volume = val
                else:
                    dev.volume = val
            except Exception as ex:
                log.warning("Sonos volume: %s", ex)
            try:
                self._vol_done.emit()
            except RuntimeError:
                pass
        self.pool.submit(work)

    def set_muted(self, muted: bool):
        self.muted = muted
        group = self.members > 1
        self._call(lambda d: setattr(d.group if group else d, "mute", muted))

    def is_playing(self) -> bool:
        return self.player_state in ("PLAYING", "BUFFERING")

    def poll_now(self):
        self._ticks = 0
        self._ask()

    def _tick(self):
        self._ticks += 1
        if self.player_state == "PLAYING" and self.session_ok and not self._is_radio:
            base, at = self._pos_base
            est = int(base + (time.monotonic() - at) * 1000)
            if self.duration_ms:
                est = min(est, self.duration_ms)
            if est != self.position_ms:
                self.position_ms = est
                self.positionChanged.emit(est)
        if self._ticks % 2 == 0:
            self._ask()

    def _ask(self):
        if self._polling or self.dev is None:
            return
        self._polling = True
        dev, n, group, with_vol = self.dev, self._load_n, self.members > 1, self._ticks % 6 == 0

        def work():
            st = {}
            try:
                info = dev.get_current_transport_info()
                st["state"] = info.get("current_transport_state", "")
                tr = dev.get_current_track_info()
                st["uri"] = tr.get("uri", "")
                st["position"] = parse_hms(tr.get("position"))
                st["duration"] = parse_hms(tr.get("duration"))
                if with_vol:
                    st["volume"] = int(dev.group.volume if group else dev.volume)
            except Exception as ex:
                st["error"] = str(ex)
            try:
                self._status.emit(st, n)
            except RuntimeError:
                pass
        fut = self.pool.submit(work)
        fut.add_done_callback(lambda _f: setattr(self, "_polling", False))

    def _ours(self, uri: str) -> bool:
        return bool(self._match) and uri.split("://", 1)[-1] == self._match

    def _on_status(self, st: dict, n: int):
        self._polling = False
        if self.dev is None:
            return
        if "error" in st:
            self._errors_in_row = getattr(self, "_errors_in_row", 0) + 1
            if self._errors_in_row >= 8:  # ~8 s without an answer
                self._lost(f"Lost the connection to {self.name}.")
            return
        self._errors_in_row = 0
        if "volume" in st and time.monotonic() > self._vol_quiet_until and not self._vol_busy:
            v = st["volume"] / 100
            if abs(v - self.volume) > 0.005:
                self.volume = v
                self.volumeChanged.emit(v)
        if n != self._load_n or not self._loaded_url:
            return
        state = {"PLAYING": "PLAYING", "PAUSED_PLAYBACK": "PAUSED", "TRANSITIONING": "BUFFERING",
                 "STOPPED": "IDLE"}.get(st.get("state", ""), "")
        uri = st.get("uri", "")
        if uri and not self._ours(uri):
            if self.session_ok:
                self._other += 1
                if self._other >= 3:  # something else was chosen in the Sonos app
                    self._lost(f"{self.name} is playing something else now.")
            return
        self._other = 0
        if not self.session_ok and state in ("PLAYING", "PAUSED") and uri:
            self.session_ok = True
            self.watchdog.stop()
            log.info("Sonos is %s %r", state.lower(), self._load_title)
            if self.want_playing and state == "PAUSED":
                self._call(lambda d: d.play())
                state = "BUFFERING"
            elif not self.want_playing and state == "PLAYING":
                radio = self._is_radio
                self._call(lambda d: d.stop() if radio else d.pause())
                state = "PAUSED"
        if not self.session_ok:
            # took the song then stopped without playing it
            sent = getattr(self, "_sent_at", 0)
            if state == "IDLE" and sent and self.want_playing and time.monotonic() - sent > 3:
                self._sent_at = 0
                self.watchdog.stop()
                self._fail("stopped")
            return
        if st.get("duration") and not self._is_radio:
            d = st["duration"]
            if abs(d - self.duration_ms) > 1500:
                self.duration_ms = d
                self.durationChanged.emit(d)
        if state in ("PLAYING", "PAUSED") and not self._is_radio:
            pos = st.get("position", 0)
            base, at = self._pos_base
            est = base + ((time.monotonic() - at) * 1000 if self.player_state == "PLAYING" else 0)
            if abs(pos - est) > 1500 or state != "PLAYING":
                self._pos_base = (pos, time.monotonic())
                if pos != self.position_ms:
                    self.position_ms = pos
                    self.positionChanged.emit(pos)
        if state == "IDLE":
            if self._stopped_by_us or self._is_radio and not self.want_playing:
                return
            near_end = self.duration_ms and self.position_ms >= self.duration_ms - 3500
            if not self._is_radio and near_end:
                if self._finished_n != self._load_n:
                    self._finished_n = self._load_n
                    self.player_state = "IDLE"
                    self.stateChanged.emit("IDLE")
                    self.trackFinished.emit()
                return
            if self.player_state != "PAUSED":  # stopped from the Sonos app: show as paused
                self.player_state = "PAUSED"
                self.want_playing = False
                self.session_ok = False if self._is_radio else self.session_ok
                self.stateChanged.emit("PAUSED")
            return
        if state and state != self.player_state:
            if state == "PLAYING":
                self._pos_base = (self.position_ms, time.monotonic())
            self.player_state = state
            self.want_playing = state in ("PLAYING", "BUFFERING")
            self.stateChanged.emit(state)

    def _lost(self, why: str):
        if self.dev is None:
            return
        self.dev = None
        self.poll.stop()
        self.watchdog.stop()
        self.converter.cancel()
        self.session_ok = False
        self._loaded_url = ""
        self._load_n += 1
        log.info("Sonos %s: %s", self.name, why)
        self.disconnected.emit(why)


def _quiet(fn, *args):
    try:
        fn(*args)
    except Exception:
        pass
