"""Musicwell on the desktop (Linux; on Windows see the end of this note).

* Media keys and desktop media controls (MPRIS): your keyboard's play/pause/next/previous keys,
  the media controls of GNOME, KDE, Cinnamon, XFCE…, the lock screen, `playerctl`, and phone
  remotes such as KDE Connect all talk to a music player through this one D-Bus interface.
* Notifications when the song changes (the desktop's own notification pop-ups), with a Next button
  where the desktop supports one.
* The tray icon, with "close to tray".

The D-Bus side runs on its own thread with dbus-next; everything it asks for arrives on the Qt
thread through the `requested` signal: ("playpause" | "play" | "pause" | "stop" | "next" |
"previous" | "raise" | "quit", None), ("seek", offset ms), ("position", ms), ("volume", 0..1),
("shuffle", bool), ("loop", "None" | "Track" | "Playlist").

On Windows there's no D-Bus: the media keys come through winkeys.MediaKeys (they work in the
background too), and the song-change pop-ups are the tray icon's notifications.

No `from __future__ import annotations` here: dbus-next reads the D-Bus types ('s', 'x', 'a{sv}')
from the methods' annotations.
"""
import asyncio
import html
import os
import shutil
import sys
import threading
import time

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QIcon, QImage
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from musicwell import APP_ID, APP_NAME

WINDOWS = sys.platform == "win32"
try:
    if WINDOWS:
        raise ImportError("D-Bus is Linux only")
    from dbus_next import BusType, Message, MessageType, PropertyAccess, Variant
    from dbus_next.aio import MessageBus
    from dbus_next.constants import NameFlag, RequestNameReply
    from dbus_next.service import ServiceInterface, dbus_property, method, signal as dbus_signal
    AVAILABLE = True
    WHY_NOT = ""
except Exception as _ex:                 # pragma: no cover - dbus-next missing
    AVAILABLE = False
    WHY_NOT = f"dbus-next isn't installed ({_ex})"

MPRIS_PATH = "/org/mpris/MediaPlayer2"
NOTIFY_NAME = "org.freedesktop.Notifications"
NOTIFY_PATH = "/org/freedesktop/Notifications"


def _icon_path() -> str:
    p = os.path.join(os.path.dirname(__file__), "icon.png")
    return p if os.path.exists(p) else ""


if AVAILABLE:
    class _Root(ServiceInterface):
        """org.mpris.MediaPlayer2: identity, Raise and Quit."""

        def __init__(self, hub):
            super().__init__("org.mpris.MediaPlayer2")
            self.hub = hub

        @method()
        def Raise(self):
            self.hub.ask("raise")

        @method()
        def Quit(self):
            self.hub.ask("quit")

        @dbus_property(access=PropertyAccess.READ)
        def CanQuit(self) -> "b":
            return True

        @dbus_property(access=PropertyAccess.READ)
        def CanRaise(self) -> "b":
            return True

        @dbus_property(access=PropertyAccess.READ)
        def HasTrackList(self) -> "b":
            return False

        @dbus_property(access=PropertyAccess.READ)
        def Identity(self) -> "s":
            return APP_NAME

        @dbus_property(access=PropertyAccess.READ)
        def DesktopEntry(self) -> "s":
            return APP_ID

        @dbus_property(access=PropertyAccess.READ)
        def SupportedUriSchemes(self) -> "as":
            return []

        @dbus_property(access=PropertyAccess.READ)
        def SupportedMimeTypes(self) -> "as":
            return []

    class _Player(ServiceInterface):
        """org.mpris.MediaPlayer2.Player: what's playing and the controls."""

        def __init__(self, hub):
            super().__init__("org.mpris.MediaPlayer2.Player")
            self.hub = hub
            self.st = {"PlaybackStatus": "Stopped", "LoopStatus": "None", "Shuffle": False, "Volume": 0.8,
                       "Metadata": {}, "CanGoNext": False, "CanGoPrevious": False, "CanPlay": True,
                       "CanPause": True, "CanSeek": False}

        @method()
        def Next(self):
            self.hub.ask("next")

        @method()
        def Previous(self):
            self.hub.ask("previous")

        @method()
        def Pause(self):
            self.hub.ask("pause")

        @method()
        def PlayPause(self):
            self.hub.ask("playpause")

        @method()
        def Stop(self):
            self.hub.ask("stop")

        @method()
        def Play(self):
            self.hub.ask("play")

        @method()
        def Seek(self, offset: "x"):
            self.hub.ask("seek", int(offset // 1000))

        @method()
        def SetPosition(self, track_id: "o", position: "x"):
            md = self.st["Metadata"]
            if "mpris:trackid" in md and md["mpris:trackid"].value == track_id:
                self.hub.ask("position", int(position // 1000))

        @method()
        def OpenUri(self, uri: "s"):
            pass  # no URI schemes

        @dbus_signal()
        def Seeked(self, position) -> "x":
            return position

        @dbus_property(access=PropertyAccess.READ)
        def PlaybackStatus(self) -> "s":
            return self.st["PlaybackStatus"]

        @dbus_property()
        def LoopStatus(self) -> "s":
            return self.st["LoopStatus"]

        @LoopStatus.setter
        def LoopStatus(self, value: "s"):
            if value in ("None", "Track", "Playlist"):
                self.hub.ask("loop", value)

        @dbus_property()
        def Rate(self) -> "d":
            return 1.0

        @Rate.setter
        def Rate(self, value: "d"):
            pass  # always normal speed

        @dbus_property()
        def Shuffle(self) -> "b":
            return self.st["Shuffle"]

        @Shuffle.setter
        def Shuffle(self, value: "b"):
            self.hub.ask("shuffle", bool(value))

        @dbus_property(access=PropertyAccess.READ)
        def Metadata(self) -> "a{sv}":
            return self.st["Metadata"]

        @dbus_property()
        def Volume(self) -> "d":
            return self.st["Volume"]

        @Volume.setter
        def Volume(self, value: "d"):
            self.hub.ask("volume", max(0.0, min(1.0, float(value))))

        @dbus_property(access=PropertyAccess.READ)
        def Position(self) -> "x":
            return int(self.hub.position_ms() * 1000)

        @dbus_property(access=PropertyAccess.READ)
        def MinimumRate(self) -> "d":
            return 1.0

        @dbus_property(access=PropertyAccess.READ)
        def MaximumRate(self) -> "d":
            return 1.0

        @dbus_property(access=PropertyAccess.READ)
        def CanGoNext(self) -> "b":
            return self.st["CanGoNext"]

        @dbus_property(access=PropertyAccess.READ)
        def CanGoPrevious(self) -> "b":
            return self.st["CanGoPrevious"]

        @dbus_property(access=PropertyAccess.READ)
        def CanPlay(self) -> "b":
            return self.st["CanPlay"]

        @dbus_property(access=PropertyAccess.READ)
        def CanPause(self) -> "b":
            return self.st["CanPause"]

        @dbus_property(access=PropertyAccess.READ)
        def CanSeek(self) -> "b":
            return self.st["CanSeek"]

        @dbus_property(access=PropertyAccess.READ)
        def CanControl(self) -> "b":
            return True

        def apply(self, changes: dict):
            """On the D-Bus thread: store the new values and emit PropertiesChanged."""
            changed = {k: v for k, v in changes.items() if self.st.get(k) != v}
            if changed:
                self.st.update(changed)
                self.emit_properties_changed(changed)


class Desktop(QObject):
    """Media controls and notifications. Create once; call updates from the Qt thread."""
    requested = Signal(str, object)
    notifyFailed = Signal(str, str)  # summary, body: no notification service (use the tray)
    statusChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.loop: asyncio.AbstractEventLoop | None = None
        self.bus = None
        self.player_iface = None
        self.bus_name = ""
        self.error = "" if AVAILABLE else WHY_NOT
        self.mpris_wanted = False
        self.mpris_on = False
        self.note_caps: set[str] = set()
        self.note_id = 0
        self._tagged: dict[int, object] = {}
        self.activation_token = ""
        self._pos_ms = 0
        self._pos_at = time.monotonic()
        self._playing = False
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self._art_dir = ""
        self._art_files: dict[int, str] = {}
        self.keys = None
        if WINDOWS:
            from musicwell.winkeys import MediaKeys
            self.error = ""
            self.keys = MediaKeys(self)
            self.keys.pressed.connect(lambda what: self.requested.emit(what, None))
            self._ready.set()
        if AVAILABLE:
            threading.Thread(target=self._run, name=f"{APP_ID}-dbus", daemon=True).start()

    def _run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._connect())
        except Exception as ex:
            self.error = f"no desktop session bus ({ex})"
            self.bus = None
        with self._lock:
            self._ready.set()
            want = self.mpris_wanted
        if self.bus is not None and want:
            try:
                self.loop.run_until_complete(self._mpris(True))
            except Exception as ex:
                self.error = f"couldn't offer the media controls ({ex})"
        self.statusChanged.emit()
        if self.bus is not None:
            self.loop.run_forever()

    async def _connect(self):
        self.bus = await MessageBus(bus_type=BusType.SESSION).connect()
        self.bus.add_message_handler(self._on_message)
        try:
            reply = await self.bus.call(Message(destination=NOTIFY_NAME, path=NOTIFY_PATH, interface=NOTIFY_NAME,
                                                member="GetCapabilities"))
            if reply.message_type == MessageType.METHOD_RETURN:
                self.note_caps = set(reply.body[0])
            await self.bus.call(Message(destination="org.freedesktop.DBus", path="/org/freedesktop/DBus",
                                        interface="org.freedesktop.DBus", member="AddMatch", signature="s",
                                        body=[f"type='signal',interface='{NOTIFY_NAME}'"]))
        except Exception:
            pass

    def _on_message(self, msg):
        if (msg.message_type == MessageType.SIGNAL and msg.interface == NOTIFY_NAME
                and msg.member == "ActivationToken" and len(msg.body) >= 2
                and (msg.body[0] in self._tagged or msg.body[0] == self.note_id)):
            self.activation_token = msg.body[1]  # lets Wayland raise our window
            return None
        if (msg.message_type == MessageType.SIGNAL and msg.interface == NOTIFY_NAME
                and msg.member == "ActionInvoked" and msg.body and msg.body[0] in self._tagged):
            self.requested.emit("alert", (msg.body[1], self._tagged[msg.body[0]]))
            return None
        if (msg.message_type == MessageType.SIGNAL and msg.interface == NOTIFY_NAME
                and msg.member == "ActionInvoked" and msg.body and msg.body[0] == self.note_id and self.note_id):
            key = msg.body[1]
            self.requested.emit("next" if key == "next" else "raise", None)
        return None

    def ask(self, what: str, value=None):
        """Called from the D-Bus thread; handled on the Qt thread."""
        self.requested.emit(what, value)

    def position_ms(self) -> int:
        if self._playing:
            return int(self._pos_ms + (time.monotonic() - self._pos_at) * 1000)
        return self._pos_ms

    def _soon(self, fn, *args):
        if self.loop is not None and self.bus is not None:
            self.loop.call_soon_threadsafe(fn, *args)

    def _task(self, coro):
        if self.loop is not None and self.bus is not None:
            return asyncio.run_coroutine_threadsafe(coro, self.loop)
        coro.close()
        return None

    def set_media_controls(self, on: bool):
        if WINDOWS:
            self.mpris_wanted = on
            if on:
                self.mpris_on = self.keys.start()
                taken = self.keys.taken
                self.error = ("" if not taken else
                              ("another program is using the media keys, so they only work while Musicwell's "
                               "window is active" if not self.mpris_on else
                               f"another program is using the {', '.join(taken)} key(s)"))
            else:
                self.keys.stop()
                self.mpris_on, self.error = False, ""
            self.statusChanged.emit()
            return
        with self._lock:
            self.mpris_wanted = on
            if not AVAILABLE or not self._ready.is_set() or self.bus is None:
                return  # still connecting: enabled once connected
        self._task(self._mpris(on))

    async def _mpris(self, on: bool):
        if on and not self.mpris_on:
            root, self.player_iface = _Root(self), _Player(self)
            self.bus.export(MPRIS_PATH, root)
            self.bus.export(MPRIS_PATH, self.player_iface)
            name = f"org.mpris.MediaPlayer2.{APP_ID}"
            reply = await self.bus.request_name(name, NameFlag.DO_NOT_QUEUE)
            if reply not in (RequestNameReply.PRIMARY_OWNER, RequestNameReply.ALREADY_OWNER):
                name = f"{name}.instance{os.getpid()}"  # another Musicwell is running
                await self.bus.request_name(name, NameFlag.DO_NOT_QUEUE)
            self.bus_name = name
            self.mpris_on = True
            self._push_all()
        elif not on and self.mpris_on:
            try:
                await self.bus.release_name(self.bus_name)
            except Exception:
                pass
            self.bus.unexport(MPRIS_PATH)
            self.mpris_on, self.player_iface, self.bus_name = False, None, ""
        self.statusChanged.emit()

    _last: dict = {}

    def update(self, **changes):
        """PlaybackStatus, Metadata, Volume, Shuffle, LoopStatus, CanSeek, CanGoNext..."""
        self._last = {**self._last, **changes}
        if "PlaybackStatus" in changes:
            self.set_position(self.position_ms(), seeked=False)
            self._playing = changes["PlaybackStatus"] == "Playing"
        if self.mpris_on and self.player_iface is not None:
            self._soon(self.player_iface.apply, changes)

    def _push_all(self):
        if self.player_iface is not None and self._last:
            self.player_iface.apply(dict(self._last))

    def set_position(self, ms: int, seeked: bool = False):
        """Called as the song plays; seeked=True when the user jumped."""
        self._pos_ms, self._pos_at = int(ms), time.monotonic()
        if seeked and self.mpris_on and self.player_iface is not None:
            self._soon(self.player_iface.Seeked, int(ms * 1000))

    def track_started(self, ms: int = 0):
        """A new song: reset the position without a Seeked signal."""
        self._pos_ms, self._pos_at = int(ms), time.monotonic()

    def metadata(self, t: dict | None, art_path: str = "", length_ms: int = 0) -> dict:
        if not t:
            return {"mpris:trackid": Variant("o", "/org/mpris/MediaPlayer2/TrackList/NoTrack")}
        tid = t.get("id", 0)
        md = {"mpris:trackid": Variant("o", f"/org/{APP_ID}/track/{'n' if tid < 0 else ''}{abs(tid)}")}
        length = length_ms or int((t.get("length") or 0) * 1000)
        if length > 0:
            md["mpris:length"] = Variant("x", length * 1000)
        if t.get("stream"):
            st = t.get("station") or {}
            md["xesam:title"] = Variant("s", t.get("title") or st.get("name", ""))
            if t.get("artist"):
                md["xesam:artist"] = Variant("as", [t["artist"]])
            md["xesam:album"] = Variant("s", st.get("name", ""))
        else:
            md["xesam:title"] = Variant("s", t.get("title") or "")
            if t.get("artist"):
                md["xesam:artist"] = Variant("as", [t["artist"]])
            if t.get("album"):
                md["xesam:album"] = Variant("s", t["album"])
            if t.get("albumartist"):
                md["xesam:albumArtist"] = Variant("as", [t["albumartist"]])
            if t.get("genre"):
                md["xesam:genre"] = Variant("as", [t["genre"]])
            if t.get("composer"):
                md["xesam:composer"] = Variant("as", [t["composer"]])
            if t.get("track"):
                md["xesam:trackNumber"] = Variant("i", int(t["track"]))
            if t.get("disc"):
                md["xesam:discNumber"] = Variant("i", int(t["disc"]))
            if t.get("rating"):
                md["xesam:userRating"] = Variant("d", int(t["rating"]) / 5)
            if t.get("playcount"):
                md["xesam:useCount"] = Variant("i", int(t["playcount"]))
            path = t.get("path") or ""
            if path:
                from pathlib import Path
                url = path if "://" in path else Path(path).as_uri()
                md["xesam:url"] = Variant("s", url)
        if art_path:
            from pathlib import Path
            md["mpris:artUrl"] = Variant("s", Path(art_path).as_uri())
        return md

    def art_file(self, img) -> str:
        """Desktops show images from files: write the cover once (max 512 px)."""
        if img is None or (isinstance(img, QImage) and img.isNull()):
            return ""
        if not isinstance(img, QImage):
            try:
                img = img.toImage()
            except Exception:
                return ""
        key = img.cacheKey()
        if key in self._art_files and os.path.exists(self._art_files[key]):
            return self._art_files[key]
        if not self._art_dir:
            from musicwell.paths import cache_dir
            self._art_dir = str(cache_dir() / "nowplaying")
            shutil.rmtree(self._art_dir, ignore_errors=True)
            os.makedirs(self._art_dir, exist_ok=True)
        if len(self._art_files) > 30:  # keep the folder small
            for k, p in list(self._art_files.items())[:15]:
                try:
                    os.remove(p)
                except OSError:
                    pass
                del self._art_files[k]
        small = img if max(img.width(), img.height()) <= 512 else img.scaled(512, 512, Qt.KeepAspectRatio,
                                                                              Qt.SmoothTransformation)
        path = os.path.join(self._art_dir, f"{key & 0xFFFFFFFFFFFF:x}.png")
        return path if small.save(path, "PNG") else ""

    def notify(self, summary: str, body: str, image_path: str = "", replace: bool = False, next_button=True):
        if not (AVAILABLE and self._ready.wait(2) and self.bus is not None):
            self.notifyFailed.emit(summary, body)
            return
        self._task(self._notify(summary, body, image_path, replace, next_button))

    def notify_with(self, summary: str, body: str, buttons: list, tag, image_path: str = "") -> bool:
        """A separate notification with buttons [(key, label)]; a click emits requested("alert", (key, tag))."""
        if not (AVAILABLE and self._ready.wait(2) and self.bus is not None):
            return False
        self._task(self._notify_with(summary, body, buttons, tag, image_path))
        return True

    async def _notify_with(self, summary, body, buttons, tag, image_path):
        if "body-markup" in self.note_caps:
            body = html.escape(body, quote=False)
        actions = []
        if "actions" in self.note_caps:
            for key, label in buttons:
                actions += [key, label]
        hints = {"desktop-entry": Variant("s", APP_ID), "category": Variant("s", "x-gnome.music")}
        if image_path:
            hints["image-path"] = Variant("s", image_path)
        msg = Message(destination=NOTIFY_NAME, path=NOTIFY_PATH, interface=NOTIFY_NAME, member="Notify",
                      signature="susssasa{sv}i",
                      body=[APP_NAME, 0, _icon_path(), summary, body, actions, hints, 20000])
        try:
            reply = await self.bus.call(msg)
            if reply.message_type == MessageType.METHOD_RETURN:
                self._tagged[reply.body[0]] = tag
                if len(self._tagged) > 50:
                    self._tagged.pop(next(iter(self._tagged)))
                return
        except Exception:
            pass
        self.notifyFailed.emit(summary, body)

    async def _notify(self, summary, body, image_path, replace, next_button):
        if "body-markup" in self.note_caps:
            body = html.escape(body, quote=False)
        actions = []
        if "actions" in self.note_caps:
            actions = ["default", "Show Musicwell"] + (["next", "Next"] if next_button else [])
        hints = {"desktop-entry": Variant("s", APP_ID), "category": Variant("s", "x-gnome.music"),
                 "transient": Variant("b", True)}
        if image_path:
            hints["image-path"] = Variant("s", image_path)
        msg = Message(destination=NOTIFY_NAME, path=NOTIFY_PATH, interface=NOTIFY_NAME, member="Notify",
                      signature="susssasa{sv}i",
                      body=[APP_NAME, self.note_id if replace or self.note_id else 0, _icon_path(),
                            summary, body, actions, hints, 6000])
        try:
            reply = await self.bus.call(msg)
            if reply.message_type == MessageType.METHOD_RETURN:
                self.note_id = reply.body[0]
                return
        except Exception:
            pass
        self.notifyFailed.emit(summary, body)

    def shutdown(self):
        if self.keys is not None:
            self.keys.stop()
        if self.loop is not None and self.bus is not None:
            def stop():
                try:
                    self.bus.disconnect()
                finally:
                    self.loop.stop()
            self.loop.call_soon_threadsafe(stop)


class Tray(QObject):
    """Tray icon: click shows/hides the window, middle-click plays/pauses."""
    requested = Signal(str, object)

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        ico = os.path.join(os.path.dirname(__file__), "icon.ico")
        if WINDOWS and os.path.exists(ico):
            icon = QIcon(ico)  # Windows' tray wants a bitmap icon
        else:
            icon = QIcon(_icon_path()) if _icon_path() else window.windowIcon()
        self.icon = QSystemTrayIcon(icon, window)
        self.icon.setToolTip(APP_NAME)
        m = QMenu()
        self.menu = m
        self.song = m.addAction("Nothing playing")
        self.song.setEnabled(False)
        m.addSeparator()
        self.play = m.addAction("Play", lambda: self.requested.emit("playpause", None))
        m.addAction("Next", lambda: self.requested.emit("next", None))
        m.addAction("Previous", lambda: self.requested.emit("previous", None))
        m.addSeparator()
        self.show_act = m.addAction("Hide Musicwell", lambda: self.requested.emit("toggle", None))
        m.addSeparator()
        m.addAction(f"About {APP_NAME}", lambda: self.requested.emit("about", None))
        m.addAction(f"Quit {APP_NAME}", lambda: self.requested.emit("quit", None))
        m.aboutToShow.connect(self._refresh_show)
        self.icon.setContextMenu(m)
        self.icon.activated.connect(self._activated)
        self.icon.messageClicked.connect(lambda: self.requested.emit("message", None))

    @staticmethod
    def available() -> bool:
        return QSystemTrayIcon.isSystemTrayAvailable()

    wanted = False

    def set_visible(self, on: bool):
        self.wanted = on
        self.icon.setVisible(on)

    def is_visible(self) -> bool:
        return self.icon.isVisible()

    def set_song(self, title: str, artist: str):
        text = f"{title} — {artist}" if title and artist else (title or "Nothing playing")
        short = text if len(text) <= 60 else text[:57] + "…"
        self.song.setText(short.replace("&", "&&"))
        self.icon.setToolTip(f"{APP_NAME}\n{text}" if title else APP_NAME)

    def set_playing(self, playing: bool):
        self.play.setText("Pause" if playing else "Play")

    def _refresh_show(self):
        shown = self.window.isVisible() and not self.window.isMinimized()
        self.show_act.setText(f"Hide {APP_NAME}" if shown else f"Show {APP_NAME}")

    def _activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self.requested.emit("toggle", None)
        elif reason == QSystemTrayIcon.MiddleClick:
            self.requested.emit("playpause", None)

    def message(self, title: str, text: str):
        if not QSystemTrayIcon.supportsMessages():
            return
        if self.icon.isVisible():
            self.icon.showMessage(title, text, self.icon.icon(), 5000)
        elif WINDOWS:
            # Windows shows pop-ups through a tray icon: show it briefly.
            from PySide6.QtCore import QTimer
            self.icon.setVisible(True)
            self.icon.showMessage(title, text, self.icon.icon(), 5000)
            if getattr(self, "_hide_after", None) is None:
                self._hide_after = QTimer(self, singleShot=True, interval=6000)
                self._hide_after.timeout.connect(lambda: None if self.wanted else self.icon.setVisible(False))
            self._hide_after.start()
