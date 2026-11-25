"""Playback: play order, shuffle, repeat, the queue and play counts."""
from __future__ import annotations

import os
import random
import time

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

from musicwell import audio as audio_mod
from musicwell import cast as cast_mod
from musicwell import radio as radio_mod

REPEAT_OFF, REPEAT_ALL, REPEAT_ONE = 0, 1, 2


class Player(QObject):
    trackChanged = Signal(object)  # track dict or None
    playingChanged = Signal(bool)
    positionChanged = Signal(int)  # ms
    durationChanged = Signal(int)  # ms
    queueChanged = Signal()
    modesChanged = Signal()
    error = Signal(str)
    radioChanged = Signal(object)
    radioText = Signal(str)
    streamPicture = Signal(str)
    radioReconnecting = Signal(bool)
    streamInfo = Signal(dict)
    ranOut = Signal(object)  # the list ended
    seeked = Signal(int)

    def __init__(self, library, parent=None):
        super().__init__(parent)
        self.library = library
        self.cast = None
        self.engine = None
        self.audio = None
        self.eq_error = ""
        if audio_mod.AVAILABLE and os.environ.get("MUSICWELL_NO_EQ") != "1":
            try:
                self.engine = audio_mod.AudioEngine(self)
            except Exception as ex:
                self.eq_error = str(ex)
        else:
            self.eq_error = audio_mod.WHY_NOT or "turned off with MUSICWELL_NO_EQ"
        if self.engine is not None:
            self.media = self.engine.media
        else:
            self.media = QMediaPlayer(self)
            self.audio = QAudioOutput(self)
            self.media.setAudioOutput(self.audio)

        self.playlist: list[int] = []  # track ids
        self.order: list[int] = []  # indices into playlist
        self.pos = -1  # index into order
        # Queue entries keep their place with a state: "wait", "now" or "done".
        self.qlist: list[dict] = []
        self._qseq = 0
        self._q_pending = None
        self.history: list[int] = []  # track ids, for Previous after queue songs
        self._hist_entry: list = []  # queue entry each history item came from, or None
        self.current: dict | None = None

        self.shuffle = False
        self.repeat = REPEAT_OFF
        self.stop_after_current = False
        self._volume = 0.8
        self._apply_volume()

        self._listened = 0
        self._last_pos = 0
        self._counted = False
        self._errors = 0
        self._pending_seek = 0
        self._muted = False
        self.rg_mode = "off"  # off | track | album | auto
        self.rg_preamp = 0.0  # dB
        self.rg_untagged = 0.0  # dB for songs without tags
        self.rg_clip = True
        self.rg_now = 1.0
        self.duck = 1.0  # 1.0 = normal
        self.radio_step = None
        self.rg_info = ""
        self.fade_in_ms = 0
        self.fade_out_ms = 0
        self.fade_within_album = False
        self.transport_fade_ms = 0
        self._prev_track = None
        self.queueChanged.connect(self._update_fade_out)
        self.modesChanged.connect(self._update_fade_out)

        self.station: dict | None = None
        self.relay = radio_mod.StreamRelay(self)
        self.relay.titleChanged.connect(self._on_stream_title)
        self.relay.reconnecting.connect(self._on_reconnecting)
        self._radio_progress = 0.0
        self._radio_reconnecting = False
        self._radio_watch = QTimer(self, interval=5000)
        self._radio_watch.timeout.connect(self._watch_radio)
        self._radio_watch.start()
        self.relay.pictureChanged.connect(self._on_stream_picture)
        self.relay.infoChanged.connect(lambda s, info: self.streamInfo.emit(info)
                                       if self.station is not None and s == self._radio_session else None)
        self.relay.failed.connect(self._on_stream_failed)
        self._radio_session = 0
        self._radio_retries = 0
        self._radio_stopped = False
        self.remote: list[dict] | None = None
        self.remote_pos = 0

        m = self.media
        m.positionChanged.connect(lambda ms: None if self.cast else self._on_position(int(ms)))
        m.durationChanged.connect(lambda d: None if self.cast else self.durationChanged.emit(int(d)))
        m.playbackStateChanged.connect(lambda st: None if self.cast else self._on_state(st))
        m.mediaStatusChanged.connect(lambda st: None if self.cast else self._on_status(st))
        m.errorOccurred.connect(lambda e, msg: None if self.cast else self._on_error(e, msg))

    @staticmethod
    def _perceptual(v: float) -> float:
        return max(0.0, min(1.0, v)) ** 3

    @property
    def volume(self) -> float:
        return self._volume

    def set_volume(self, v: float):
        self._volume = max(0.0, min(1.0, v))
        self._apply_volume()

    def set_duck(self, f: float):
        f = max(0.0, min(1.0, f))
        if abs(f - getattr(self, "duck", 1.0)) > 1e-4:
            self.duck = f
            self._apply_volume()

    def _apply_volume(self):
        duck = getattr(self, "duck", 1.0)
        if self.cast:
            self.cast.set_volume(self._volume * duck ** (1 / 3))
        elif self.engine:
            self.engine.set_volume(self._perceptual(self._volume) * duck)
        else:
            self.audio.setVolume(self._perceptual(self._volume) * duck * min(1.0, getattr(self, "rg_now", 1.0)))

    def set_replaygain(self, mode: str, preamp: float = 0.0, untagged: float = 0.0, clip: bool = True):
        self.rg_mode, self.rg_preamp, self.rg_untagged, self.rg_clip = mode, float(preamp), float(untagged), clip
        self._apply_replaygain()

    def _apply_replaygain(self):
        self.rg_now, self.rg_info = replaygain(self.current, self.rg_mode, self.shuffle, self.rg_preamp,
                                               self.rg_untagged, self.rg_clip)
        if self.engine and not self.cast:
            self.media.set_replaygain(self.rg_now)
        elif not self.cast:
            self._apply_volume()

    def set_muted(self, muted: bool):
        self._muted = muted
        if self.cast:
            self.cast.set_muted(muted)
            return
        if self.engine:
            self.engine.set_muted(muted)
        else:
            self.audio.setMuted(muted)

    def is_muted(self) -> bool:
        if self.cast:
            return self._muted
        return self.engine.is_muted() if self.engine else self.audio.isMuted()

    @property
    def eq_available(self) -> bool:
        return self.engine is not None

    def set_eq(self, enabled: bool, gains, preamp: float):
        if self.engine:
            self.engine.set_eq(enabled, gains, preamp)

    def shutdown(self):
        if self.engine:
            self.engine.shutdown()

    def is_playing(self) -> bool:
        if self.cast:
            return self.cast.is_playing()
        return self.media.playbackState() == QMediaPlayer.PlayingState

    def position(self) -> int:
        return self.cast.position_ms if self.cast else self.media.position()

    def duration(self) -> int:
        return self.cast.duration_ms if self.cast else self.media.duration()

    def start_casting(self, ctl, pos: int | None = None, playing: bool | None = None):
        if pos is None:
            pos, playing = self.position(), self.is_playing()
        if self.cast is not None:
            self._detach_cast()
        self._stop(flush=True)
        self.cast = ctl
        if self.engine:
            self.engine.set_shadow(True)  # keeps decoding silently so the visualizer has audio
        ctl.stateChanged.connect(self._on_cast_state)
        ctl.positionChanged.connect(self._on_cast_position)
        ctl.durationChanged.connect(self.durationChanged)
        ctl.trackFinished.connect(self._on_cast_finished)
        ctl.error.connect(self.error)
        ctl.trackFailed.connect(self._on_cast_track_failed)
        self._local_volume = self._volume
        self._volume = ctl.volume
        if self.current:
            self._cast_load(self.current, pos, autoplay=bool(playing))
        self.playingChanged.emit(self.is_playing())

    def stop_casting(self, resume_here: bool = True, keep_playing: bool | None = None):
        if self.cast is None:
            return
        pos, playing = self.cast.position_ms, self.cast.is_playing()
        if keep_playing is not None:
            playing = keep_playing
        self._detach_cast()
        if self.engine:
            self.engine.set_shadow(False)
        self._volume = getattr(self, "_local_volume", self._volume)
        self._apply_volume()
        if self.station is not None and resume_here:
            if playing:
                self.play_station(self.station, keep_title=True)
            self.playingChanged.emit(self.is_playing())
            return
        if self.current and resume_here:
            self._pending_seek = pos
            self._last_pos = pos
            self._load(self.current["path"], True, playing)
        self.playingChanged.emit(self.is_playing())

    def _detach_cast(self):
        ctl, self.cast = self.cast, None
        for sig, slot in ((ctl.stateChanged, self._on_cast_state), (ctl.positionChanged, self._on_cast_position),
                          (ctl.durationChanged, self.durationChanged),
                          (ctl.trackFinished, self._on_cast_finished), (ctl.error, self.error),
                          (ctl.trackFailed, self._on_cast_track_failed)):
            try:
                sig.disconnect(slot)
            except (RuntimeError, TypeError):
                pass

    def _cast_load(self, track: dict, start_ms: int = 0, autoplay: bool = True):
        if track.get("stream") or track.get("remote"):
            self.cast.load(track, start_ms, autoplay)
            return
        if not getattr(self.cast, "can_cast", cast_mod.can_cast)(track):
            self.error.emit(f"{track['format']} files can't be played on Cast devices — skipped "
                            f"“{track['title']}”.")
            self._errors += 1
            if self._errors < 25:
                QTimer.singleShot(300, lambda: self.next(manual=False))
            return
        self.cast.load(track, start_ms, autoplay)
        self._shadow_load(track, start_ms)

    SHADOW_LEAD_MS = 350  # our decoder runs this far ahead of the tap's "now"
    SHADOW_DRIFT_MS = 900

    def _shadow_load(self, track: dict, start_ms: int):
        if not self.engine or track.get("stream") or track.get("remote"):
            return
        self.media.load(QUrl.fromLocalFile(track["path"]), True, False)
        self._shadow_target = start_ms
        if start_ms:
            self.media.setPosition(int(start_ms), True)

    def _shadow_follow(self, state: str):
        if not self.engine or self.cast is None:
            return
        if state == "PLAYING":
            self.media.setPosition(int(self.cast.position_ms + self.SHADOW_LEAD_MS), True)
            self.media.play()
        else:
            self.media.pause()

    def _shadow_resync(self, cast_ms: int):
        if not self.engine or self.cast is None or self.cast.player_state != "PLAYING":
            return
        want = cast_ms + self.SHADOW_LEAD_MS
        if abs(self.media.position() - want) > self.SHADOW_DRIFT_MS:
            self.media.setPosition(int(want), True)
            if self.media.playbackState() != QMediaPlayer.PlayingState:
                self.media.play()

    def _on_cast_state(self, state: str):
        self._shadow_follow(state)
        self.playingChanged.emit(self.is_playing())

    def _on_cast_position(self, ms: int):
        self._shadow_resync(ms)
        self._on_position(ms)

    def _on_cast_track_failed(self):
        self._errors += 1
        if self._errors < 25:
            QTimer.singleShot(300, lambda: self.next(manual=False))

    def _on_cast_finished(self):
        self._errors = 0
        self._on_status(QMediaPlayer.EndOfMedia)

    def play_list(self, ids: list[int], start: int = 0):
        if not ids:
            return
        self._leave_radio()
        self.remote = None
        self.playlist = list(ids)
        self._build_order(start)
        self._play_id(self.playlist[self.order[self.pos]])

    def _build_order(self, start: int):
        n = len(self.playlist)
        start = max(0, min(start, n - 1))
        if self.shuffle:
            rest = [i for i in range(n) if i != start]
            random.shuffle(rest)
            self.order = [start] + rest
            self.pos = 0
        else:
            self.order = list(range(n))
            self.pos = start

    def replace_list(self, ids: list[int]):
        """Replace the playing list. The current song keeps playing even if it was removed."""
        ids = list(dict.fromkeys(ids))
        cur = self.current["id"] if (self.current and self.station is None and not self.current.get("stream")
                                     and self.remote is None) else None
        if cur is None or not self.playlist:
            return
        old = [self.playlist[i] for i in self.order] if self.order else list(self.playlist)
        pos = self.pos if 0 <= self.pos < len(old) else 0
        keep = set(ids)
        new = list(ids)
        if cur not in keep:
            after = next((t for t in old[pos + 1:] if t in keep), None)
            new.insert(new.index(after) if after is not None else len(new), cur)
        index = {t: i for i, t in enumerate(new)}
        self.playlist = new
        if self.shuffle:
            done = [t for t in old[:pos] if t in index and t != cur]
            known = set(old)
            rest = [t for t in old[pos + 1:] if t in index and t != cur]
            for t in new:
                if t not in known and t != cur:
                    rest.insert(random.randint(0, len(rest)), t)
            self.order = [index[t] for t in done] + [index[cur]] + [index[t] for t in rest]
            self.pos = len(done)
        else:
            self.order = list(range(len(new)))
            self.pos = index[cur]
        self.queueChanged.emit()

    def load_paused(self, ids: list[int], start: int, position_ms: int = 0):
        if not ids:
            return
        self.playlist = list(ids)
        self._build_order(start)
        tid = self.playlist[self.order[self.pos]]
        t = self.library.get(tid)
        if t is None:
            return
        self.current = t
        self._remember(tid, None)
        self._pending_seek = position_ms
        self._last_pos = position_ms
        self._load(t["path"], True, False)
        self.trackChanged.emit(t)

    def toggle_shuffle(self):
        self.shuffle = not self.shuffle
        if self.playlist:
            cur = self.order[self.pos] if 0 <= self.pos < len(self.order) else 0
            self._build_order(cur)
        if self.rg_mode == "auto":
            self._apply_replaygain()
        self.modesChanged.emit()

    def cycle_repeat(self):
        self.repeat = (self.repeat + 1) % 3
        self.modesChanged.emit()

    def toggle_stop_after(self):
        self.stop_after_current = not self.stop_after_current
        self.modesChanged.emit()

    def play_pause(self):
        if self.current is None:
            if self.queue:
                self.next()
            return
        if self.station is not None and not self.cast:
            # Live radio can't pause: pausing stops the stream.
            if self.is_playing():
                self._radio_stopped = True
                self.relay.stop()
                self._stop(flush=True)
            else:
                self.play_station(self.station, keep_title=True)
            return
        if self.cast:
            if self.cast.is_playing():
                self.cast.pause()
            elif self.cast.player_state == "IDLE":
                self._cast_load(self.current, self._last_pos, True)
            else:
                self.cast.play()
            self.playingChanged.emit(self.is_playing())
            return
        if self.is_playing():
            self.media.pause()
        else:
            self.media.play()

    def stop(self):
        if self.station is not None:
            self._radio_stopped = True
            self.relay.stop()
        if self.cast:
            self.cast.stop()
            if self.engine:
                self.media.stop()
            return
        self.media.stop()

    # "flush" drops audio already queued in the EQ engine.
    def _load(self, path: str, flush: bool, play: bool):
        self._holding = False
        if self.cast:
            if self.current:
                self._cast_load(self.current, self._pending_seek, play)
                self._pending_seek = 0
            return
        url = QUrl(path) if path.startswith(("http://", "https://")) else QUrl.fromLocalFile(path)
        t = self.current if self.current and self.current.get("path") == path else None
        self.rg_now, self.rg_info = replaygain(t, self.rg_mode, self.shuffle, self.rg_preamp,
                                               self.rg_untagged, self.rg_clip)
        if self.engine:
            self.media.load(url, flush, play, self.rg_now)
        else:
            self._apply_volume()
            self.media.setSource(url)
            if play:
                self.media.play()

    def _seek(self, ms: int, flush: bool = True):
        if self.cast:
            self.cast.seek(ms)
            return
        if self.engine:
            self.media.setPosition(ms, flush)
        else:
            self.media.setPosition(ms)

    def _stop(self, flush: bool):
        if self.cast:
            self.cast.stop()
            if self.engine:
                self.media.stop()
            return
        if self.engine:
            self.media.stop(flush)
        else:
            self.media.stop()

    def seek(self, ms: int):
        if self.station is not None:
            return
        self._seek(max(0, int(ms)))
        self._last_pos = int(ms)
        self.seeked.emit(max(0, int(ms)))

    def next(self, manual: bool = True):
        if self.station is not None and self.radio_step:
            st = self.radio_step(+1)
            if st:
                self.play_station(st)
                return
        if self.remote is not None and not self.queue_next():
            if self.remote_pos + 1 < len(self.remote):
                self.remote_pos += 1
            elif self.repeat == REPEAT_ALL:
                self.remote_pos = 0
            else:
                self._finish()
                return
            self._play_remote(flush=manual)
            return
        if self.station is not None:
            if not (self.queue_next() or self.order):
                return
            self._leave_radio()
            if not self.queue_next() and self.pos + 1 >= len(self.order):
                self._play_id(self.playlist[self.order[self.pos]])
                return
        elif manual and self.current and not self._counted and self.current["id"] > 0:
            self.library.record_skip(self.current["id"])
        if self.queue_next():
            self._play_entry(next(e for e in self.qlist if e["state"] == "wait"), flush=manual)
            return
        if not self.order:
            self._stop(flush=True) if manual else self._finish()
            if not manual:
                self._ran_out()
            return
        if self.pos + 1 < len(self.order):
            self.pos += 1
        elif self.repeat == REPEAT_ALL:
            if self.shuffle:
                self._build_order(random.randrange(len(self.playlist)))
            else:
                self.pos = 0
        else:
            # Pressing Next on the last song stops now; running out on its own lets the end play.
            self._stop(flush=True) if manual else self._finish()
            if not manual:
                self._ran_out()
            return
        self._play_id(self.playlist[self.order[self.pos]], flush=manual)

    def previous(self):
        if self.station is not None and self.radio_step:
            st = self.radio_step(-1)
            if st:
                self.play_station(st)
                return
        if self.remote is not None:
            if self.position() > 3000 or self.remote_pos == 0:
                self.seek(0)
            else:
                self.remote_pos -= 1
                self._play_remote()
            return
        if self.station is not None:
            if self.history:
                self._leave_radio()
                self._play_id(self.history[-1])
            return
        if self.position() > 3000 or not self.current:
            self.seek(0)
            return
        now = self._q_now()
        done = [e for e in self.qlist if e["state"] == "done"]
        if now is not None and done:
            prev_e = max(done, key=lambda e: e["seq"])
            self._q_pending = prev_e
            now["state"] = "wait"
            self.queueChanged.emit()
            self._play_id(prev_e["id"])
            return
        if len(self.history) >= 2:
            if now is not None:
                now["state"] = "wait"
                self.queueChanged.emit()
            self.history.pop()
            self._hist_entry.pop()
            tid = self.history.pop()
            self._hist_entry.pop()
            if tid in self.playlist:
                idx = self.playlist.index(tid)
                if idx in self.order:
                    self.pos = self.order.index(idx)
            self._play_id(tid)
        else:
            self.seek(0)

    def _finish(self):
        self._stop(flush=False)

    def _ran_out(self):
        if self.current is not None and self.current.get("id", 0) > 0:
            self.ranOut.emit(self.current)

    QUEUE_DONE_MAX = 500

    @property
    def queue(self) -> list[int]:
        return [e["id"] for e in self.qlist if e["state"] == "wait"]

    @queue.setter
    def queue(self, ids):
        ids = list(ids)
        out = []
        for e in self.qlist:
            if e["state"] != "wait":
                out.append(e)
            elif ids:
                out.append(self._entry(ids.pop(0)))
        out += [self._entry(i) for i in ids]
        self.qlist = out

    @staticmethod
    def _entry(tid: int, state: str = "wait") -> dict:
        return {"id": tid, "state": state, "seq": 0}

    def _q_now(self):
        return next((e for e in self.qlist if e["state"] == "now"), None)

    def _queue_played(self, prev=None):
        e = self._q_now()
        if e is not None:
            self._qseq += 1
            e["state"], e["seq"] = "done", self._qseq
            done = [x for x in self.qlist if x["state"] == "done"]
            if len(done) > self.QUEUE_DONE_MAX:
                oldest = min(done, key=lambda x: x["seq"])
                self.qlist.remove(oldest)

    def queue_playing_id(self) -> int | None:
        e = self._q_now()
        return e["id"] if e is not None else None

    def _remember(self, tid: int, entry):
        self.history.append(tid)
        self._hist_entry.append(entry)
        while len(self._hist_entry) < len(self.history):
            self._hist_entry.insert(0, None)
        del self.history[:-200]
        del self._hist_entry[:-200]

    def _forget(self, gone: list[dict]):
        ids = {id(e) for e in gone}
        if not ids:
            return
        keep = [k for k, e in enumerate(self._hist_entry)
                if e is None or id(e) not in ids or k == len(self.history) - 1]
        self.history = [self.history[k] for k in keep]
        self._hist_entry = [self._hist_entry[k] for k in keep]

    def queue_next(self) -> list[int]:
        """Queued songs always play next, then the previous list carries on."""
        return self.queue

    def _play_entry(self, e: dict, flush: bool = True):
        self._q_pending = e
        self._play_id(e["id"], flush=flush)
        self._q_pending = None
        self.queueChanged.emit()

    def jump_to_queue(self, index: int):
        waiting = [e for e in self.qlist if e["state"] == "wait"]
        if 0 <= index < len(waiting):
            self._play_entry(waiting[index])

    def play_queue_row(self, row: int):
        if not 0 <= row < len(self.qlist):
            return
        e = self.qlist[row]
        if e["state"] == "now":
            self.seek(0)
            if not self.is_playing():
                self.play_pause()
            return
        self._play_entry(e)

    def remove_queue_rows(self, rows: list[int]):
        gone = []
        for r in sorted(set(rows), reverse=True):
            if 0 <= r < len(self.qlist) and self.qlist[r]["state"] != "now":
                gone.append(self.qlist.pop(r))
        self._forget(gone)
        self.queueChanged.emit()

    def move_queue_rows(self, rows: list[int], delta: int) -> list[int]:
        rows = sorted(set(rows), reverse=delta > 0)
        if not rows or not all(0 <= r + delta < len(self.qlist) for r in rows):
            return rows
        for r in rows:
            self.qlist[r], self.qlist[r + delta] = self.qlist[r + delta], self.qlist[r]
        self.queueChanged.emit()
        return [r + delta for r in rows]

    def set_queue_rows(self, entries: list[dict]):
        self.qlist = list(entries)
        self.queueChanged.emit()

    def clear_played(self):
        self._forget([e for e in self.qlist if e["state"] == "done"])
        self.qlist = [e for e in self.qlist if e["state"] != "done"]
        self.queueChanged.emit()

    def enqueue(self, ids: list[int], front: bool = False):
        new = [self._entry(i) for i in ids]
        if front:
            at = next((k for k, e in enumerate(self.qlist) if e["state"] == "wait"), None)
            if at is None:
                now = self._q_now()
                at = self.qlist.index(now) + 1 if now is not None else len(self.qlist)
            self.qlist[at:at] = new
        else:
            self.qlist.extend(new)
        self.queueChanged.emit()

    def clear_queue(self):
        self._forget(list(self.qlist))
        self.qlist.clear()
        self.queueChanged.emit()

    def upcoming(self, limit: int = 50) -> list[int]:
        """Queue first, then the rest of the current list."""
        ids = self.queue_next()
        if self.order:
            for k in range(self.pos + 1, len(self.order)):
                if len(ids) >= limit:
                    break
                ids.append(self.playlist[self.order[k]])
        return ids[:limit]

    def configure_fades(self, fade_in_ms: int, fade_out_ms: int, within_album: bool, transport_ms: int):
        self.fade_in_ms, self.fade_out_ms = int(fade_in_ms), int(fade_out_ms)
        self.fade_within_album = bool(within_album)
        self.transport_fade_ms = int(transport_ms)
        if self.engine:
            self.media.set_transport_fade(self.transport_fade_ms)
            self._update_fade_out()

    @staticmethod
    def _same_album(a: dict | None, b: dict | None) -> bool:
        if not a or not b or not a.get("album"):
            return False
        return a["album"] == b["album"] and (a.get("albumartist") or a.get("artist")) == \
            (b.get("albumartist") or b.get("artist"))

    def _next_track(self) -> dict | None:
        if self.station is not None:
            return None
        if self.remote is not None and not self.queue_next() and self.repeat != REPEAT_ONE:
            return self.remote[self.remote_pos + 1] if self.remote_pos + 1 < len(self.remote) else None
        if self.repeat == REPEAT_ONE:
            return self.current
        ids = self.upcoming(1)
        return self.library.get(ids[0]) if ids else None

    def _fade_out_for_current(self) -> int:
        if not self.fade_out_ms or self.current is None or self.station is not None:
            return 0
        if not self.fade_within_album and self._same_album(self.current, self._next_track()):
            return 0  # keep albums gapless
        return self.fade_out_ms

    def _update_fade_out(self):
        if self.engine and self.current is not None:
            self.media.set_fade_out(self._fade_out_for_current())

    def _play_id(self, tid: int, flush: bool = True):
        t = self.library.get(tid)
        if t is None:
            return
        self._leave_radio()
        self.remote = None
        prev = self.current
        self.current = t
        self._queue_played(prev)
        e, self._q_pending = self._q_pending, None
        if e is not None and e in self.qlist:
            e["state"] = "now"
        if self.engine:
            fade_in = self.fade_in_ms
            if not flush and not self.fade_within_album and self._same_album(prev, t):
                fade_in = 0
            self.media.set_fades(fade_in, self._fade_out_for_current())
        self._remember(tid, e if (e is not None and e in self.qlist) else None)
        self._listened = 0
        self._last_pos = 0
        self._counted = False
        # When a song runs into the next, the old one is still queued for the speakers, so switch when it's actually heard.
        lag = self.engine.latency_ms() if (self.engine and not flush and not self.cast) else 0
        self._load(t["path"], flush, True)
        self._announce(t, lag)

    def _announce(self, t: dict, lag_ms: int = 0):
        self._announce_token = getattr(self, "_announce_token", 0) + 1
        if lag_ms < 80:
            self._holding = False
            self.trackChanged.emit(t)
            return
        self._holding = True
        token = self._announce_token

        def now():
            if token == self._announce_token and self.current is t:
                self._holding = False
                self.trackChanged.emit(t)
        QTimer.singleShot(int(lag_ms), now)

    def _on_position(self, ms: int):
        delta = ms - self._last_pos
        if 0 < delta < 1500:
            self._listened += delta
        self._last_pos = ms
        if self.station is not None:
            if delta:
                self._radio_progress = time.monotonic()
                if getattr(self, "_radio_note", False) and not self._radio_reconnecting:
                    self._radio_note = False
                    self.radioReconnecting.emit(False)
            if ms > 15000:
                self._radio_retries = 0
            self.positionChanged.emit(ms)
            return
        if self.current and not self._counted:
            length_ms = (self.current["length"] or 0) * 1000
            if length_ms and self._listened >= min(length_ms * 0.5, 240_000):
                self._counted = True
                self._errors = 0
                self.library.record_play(self.current["id"])
        if getattr(self, "_holding", False):
            return
        self.positionChanged.emit(ms)

    def _on_state(self, state):
        self.playingChanged.emit(state == QMediaPlayer.PlayingState)

    def _on_status(self, status):
        if status == QMediaPlayer.LoadedMedia and self._pending_seek:
            self._seek(self._pending_seek)
            self._pending_seek = 0
        if status == QMediaPlayer.EndOfMedia and self.station is not None:
            self._radio_lost("the station stopped sending")
            return
        if status == QMediaPlayer.EndOfMedia:
            if self.stop_after_current:
                self.stop_after_current = False
                self.modesChanged.emit()
                self._finish()
            elif self.repeat == REPEAT_ONE:
                if self.cast:
                    self._play_id(self.current["id"])
                    return
                self._seek(0, flush=False)
                self._listened = 0
                self._counted = False
                self.media.play()
            else:
                self.next(manual=False)

    def _on_error(self, _err, message):
        if self.station is not None:
            self._radio_lost(message)
            return
        retry = getattr(self, "retry_once", None)
        if retry and self.current and self.current.get("id") == retry[0]:
            self.retry_once = None
            tid, ms = retry

            def again():
                self._play_id(tid)
                if ms:
                    QTimer.singleShot(350, lambda: self.seek(ms))
            QTimer.singleShot(300, again)
            return
        name = self.current["title"] if self.current else "track"
        import logging
        logging.getLogger("musicwell.player").warning("Couldn't play %s: %s", (self.current or {}).get("path") or name,
                                                      message)
        self.error.emit(f"Couldn't play {name}: {message}")
        self._errors += 1
        if self._errors < 5:
            QTimer.singleShot(400, lambda: self.next(manual=False))

    def play_station(self, st: dict, keep_title: bool = False):
        new_station = self.station is None or self.station.get("uuid") != st.get("uuid")
        import logging
        logging.getLogger("musicwell.radio").info("%s %s (%s)", "Tuning in to" if new_station else "Tuning in again to",
                                                  st.get("name"), st.get("url_resolved") or st.get("url"))
        title = self.current.get("now_playing", "") if (keep_title and self.current and not new_station) else ""
        self._queue_played(self.current)
        self.station = st
        self._radio_stopped = False
        self._radio_progress = time.monotonic()
        self._radio_reconnecting = False
        self._radio_retry_due = False
        if new_station:
            self._radio_retries = 0
            self._radio_why = ""
        t = radio_mod.stream_track(st, title)
        self.current = t
        self._listened = self._last_pos = 0
        self._counted = True
        if self.engine:
            self.media.set_fades(self.fade_in_ms, 0)
        if self.cast:
            self.relay.stop()
            self._cast_load(t, 0, True)
        else:
            if radio_mod.needs_direct(st):
                self.relay.watch_hls(st["url"])
                url = st["url"]
            else:
                url = self.relay.start(st["url"])
            self._radio_session = self.relay.session
            self._load(url, True, True)
        self.trackChanged.emit(t)
        if new_station:
            self.radioChanged.emit(st)

    def _end_radio_note(self):
        if getattr(self, "_radio_note", False):
            self._radio_note = False
            self.radioReconnecting.emit(False)

    def _leave_radio(self):
        if self.station is None:
            return
        self._end_radio_note()
        self.station = None
        self.relay.stop()
        self.radioChanged.emit(None)

    def stop_radio(self):
        if self.station is None:
            return
        self._leave_radio()
        self._stop(flush=True)
        self.current = None
        self.trackChanged.emit(None)

    def _on_stream_title(self, session: int, title: str):
        if self.station is None or session != self._radio_session:
            return
        self.radioText.emit(title or "")
        if not title:
            return
        if self.current and self.current.get("now_playing") == title:
            return
        prev = self.current
        t = radio_mod.stream_track(self.station, title)
        # The first title after tuning in is already part-way through.
        if prev and prev.get("stream") and prev.get("now_playing") and not self.cast:
            t["song_start"] = self.position()
        self.current = t
        self.trackChanged.emit(t)

    def _on_stream_picture(self, session: int, url: str):
        if self.station is None or session != self._radio_session or not self.current \
                or not self.current.get("stream") or not url:
            return
        self.current["art_url"] = url
        self.streamPicture.emit(url)

    def _on_reconnecting(self, session: int, on: bool):
        if self.station is not None and session == self._radio_session:
            self._radio_reconnecting = on
            if not on:
                self._radio_progress = time.monotonic()
            self._radio_note = on
            self.radioReconnecting.emit(on)

    STALL_S = 25

    def _watch_radio(self):
        if (self.station is None or self._radio_stopped or self.cast or self._radio_reconnecting
                or self.media.playbackState() != QMediaPlayer.PlayingState):
            return
        if self._radio_progress and time.monotonic() - self._radio_progress > self.STALL_S:
            self._radio_progress = time.monotonic()
            self._radio_lost("the sound stopped coming")

    def _on_stream_failed(self, session: int, why: str):
        if self.station is not None and session == self._radio_session:
            self._radio_why = why

    RADIO_RETRY_S = (1.5, 3, 5, 10, 20, 30)  # seconds between reconnect attempts

    def _radio_lost(self, why: str):
        if self.station is None or self._radio_stopped or self.cast:
            return
        if getattr(self, "_radio_retry_due", False):
            return
        self._radio_retries += 1
        if self._radio_retries <= len(self.RADIO_RETRY_S) and not getattr(self, "_radio_note", False):
            self._radio_note = True
            self.radioReconnecting.emit(True)
        import logging
        logging.getLogger("musicwell.radio").warning("Lost %s (try %d): %s", self.station.get("name"),
                                                     self._radio_retries, why)
        if self._radio_retries <= len(self.RADIO_RETRY_S):
            st = self.station
            self._radio_retry_due = True
            QTimer.singleShot(int(1000 * self.RADIO_RETRY_S[self._radio_retries - 1]),
                              lambda: self.station is st and not self._radio_stopped
                              and self.play_station(st, keep_title=True))
            return
        self._radio_stopped = True
        self._end_radio_note()
        self.relay.stop()
        self._stop(flush=True)
        self.playingChanged.emit(False)
        why = getattr(self, "_radio_why", "") or why or "the station is not answering"
        self._radio_why = ""
        self.error.emit(f"Couldn't play {self.station['name']} — {why}. The station may be offline; "
                        "try again later or pick another.")

    def play_remote(self, tracks: list[dict], start: int = 0):
        if not tracks:
            return
        self._leave_radio()
        self.remote = list(tracks)
        self.remote_pos = max(0, min(start, len(tracks) - 1))
        self._errors = 0
        self._play_remote()

    def _play_remote(self, flush: bool = True):
        t = self.remote[self.remote_pos]
        prev = self.current
        self._queue_played(prev)
        self.current = t
        if self.engine:
            fade_in = self.fade_in_ms
            if not flush and not self.fade_within_album and self._same_album(prev, t):
                fade_in = 0
            self.media.set_fades(fade_in, self._fade_out_for_current())
        self._listened = self._last_pos = 0
        self._counted = True
        self._load(t["path"], flush, True)
        self.trackChanged.emit(t)
        self.queueChanged.emit()


def _db(text) -> float | None:
    import re
    m = re.search(r"[-+]?\d+(?:[.,]\d+)?", str(text or ""))
    return float(m.group(0).replace(",", ".")) if m else None


def replaygain(t: dict | None, mode: str, shuffle: bool, preamp: float = 0.0, untagged: float = 0.0,
               clip: bool = True) -> tuple[float, str]:
    """(factor, description) for a song. Modes: track, album, or auto (album in order, track when shuffling). Opus R128 tags count too."""
    if mode == "off" or not t or t.get("stream") or t.get("remote"):
        return 1.0, ""
    ex = t.get("_extra") or {}
    tg, ag = _db(ex.get("replaygain_track_gain")), _db(ex.get("replaygain_album_gain"))
    tp, ap = _db(ex.get("replaygain_track_peak")), _db(ex.get("replaygain_album_peak"))
    if tg is None and ex.get("r128_track_gain") is not None:  # Opus: Q7.8, -23 LUFS
        v = _db(ex.get("r128_track_gain"))
        tg = None if v is None else v / 256 + 5
    if ag is None and ex.get("r128_album_gain") is not None:
        v = _db(ex.get("r128_album_gain"))
        ag = None if v is None else v / 256 + 5
    want_album = mode == "album" or (mode == "auto" and not shuffle)
    if want_album and ag is not None:
        gain, peak, kind = ag, ap or tp, "album"
    elif tg is not None:
        gain, peak, kind = tg, tp, "track"
    elif ag is not None:
        gain, peak, kind = ag, ap, "album"
    else:
        if not untagged:
            return 1.0, "no ReplayGain information"
        return 10 ** (untagged / 20), f"{untagged:+.1f} dB (no ReplayGain information)"
    db = gain + preamp
    factor = 10 ** (db / 20)
    note = f"{db:+.1f} dB ({kind})"
    if clip and peak and peak > 0 and factor * peak > 1.0:
        factor = 1.0 / peak
        note = f"{20 * __import__('math').log10(factor):+.1f} dB ({kind}, held back to avoid clipping)"
    return factor, note

