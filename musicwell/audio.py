"""Playback with an equaliser on its own thread. The decoder, EQ and QAudioSink run in a worker thread so the UI can't interrupt the music. Path: QMediaPlayer -> QAudioBufferOutput -> Equalizer -> soft clip -> QAudioSink. Falls back to a plain QAudioOutput without numpy or a recent Qt."""
from __future__ import annotations

import threading
import time

from PySide6.QtCore import QObject, QThread, QTimer, QUrl, Qt, Signal, Slot
from PySide6.QtMultimedia import QAudioFormat, QMediaDevices, QMediaPlayer

try:  # Qt 6.7+ moved the audio state enums to QtAudio
    from PySide6.QtMultimedia import QtAudio as _QA
except ImportError:
    from PySide6.QtMultimedia import QAudio as _QA
STOPPED, SUSPENDED, IDLE = _QA.State.StoppedState, _QA.State.SuspendedState, _QA.State.IdleState
NO_ERROR = _QA.Error.NoError

try:
    import numpy as np
    from PySide6.QtMultimedia import QAudioBufferOutput, QAudioSink
    from musicwell.eq import Equalizer, soft_clip
    AVAILABLE = True
    WHY_NOT = ""
except Exception as ex:
    AVAILABLE = False
    WHY_NOT = str(ex)

# Audio queued in the sound system so playback survives a busy UI thread (PipeWire ran dry at 1 s). Skips and seeks clear it (_flush).
SINK_BUFFER_MS = 2000
FEED_MS = 10
# decoder pauses itself above HIGH
HIGH_MS, LOW_MS = 500, 300
# Decode files at 2x so the buffer fills; network streams can't go faster.
DECODE_SPEED = 2.0
# Smaller buffer while the EQ window is open so slider changes are heard at once.
RESPONSIVE_SINK_MS, RESPONSIVE_HIGH_MS, RESPONSIVE_LOW_MS = 150, 250, 150
# Audio gathered before (re)starting output.
PREBUFFER_MS = 150


# Short ramp on skip/seek/pause/stop to avoid clicks, even with fades turned off.
CUT_MS = 40
DECLICK_IN_MS = 8
# Wait this long at silence before dropping old audio; volume changes take a moment to apply.
SETTLE_MS = 35


def _pick_rate() -> int:
    dev = QMediaDevices.defaultAudioOutput()
    rate = dev.preferredFormat().sampleRate() if not dev.isNull() else 0
    return rate if rate in (44100, 48000, 88200, 96000, 176400, 192000) else 48000


def _format(rate: int, sample_format) -> QAudioFormat:
    f = QAudioFormat()
    f.setSampleRate(rate)
    f.setChannelCount(2)
    f.setChannelConfig(QAudioFormat.ChannelConfigStereo)
    f.setSampleFormat(sample_format)
    return f


class AudioTap:
    """The last few seconds sent to the sound card, for the visualizer. Written by the audio thread, read by the UI."""

    def __init__(self, rate: int, seconds: float = 2.0):
        self.rate = rate
        self.ring = np.zeros(int(rate * seconds), np.float32)
        self.total = 0  # frames written
        self.buffered = 0  # frames still in the sound card
        self.pending = 0  # frames decoded but not yet handed to the sound card
        self.stamp = 0.0
        self.active = False
        self.lock = threading.Lock()

    def write(self, mono: np.ndarray):
        n, size = len(mono), len(self.ring)
        if n >= size:
            mono, n = mono[-size:], size
        with self.lock:
            i = self.total % size
            first = min(n, size - i)
            self.ring[i:i + first] = mono[:first]
            self.ring[:n - first] = mono[first:]
            self.total += n

    def mark(self, buffered: int, active: bool):
        with self.lock:
            self.buffered, self.active, self.stamp = buffered, active, time.monotonic()

    def reset(self):
        with self.lock:
            self.buffered = 0
            self.ring[:] = 0

    def latest(self, n: int = 2048):
        with self.lock:
            if not self.active or self.total < n:
                return None
            ahead = int((time.monotonic() - self.stamp) * self.rate)
            play = min(self.total, self.total - self.buffered + ahead)
            start = play - n
            size = len(self.ring)
            if start < self.total - size or start < 0:
                return None
            idx = (np.arange(start, play) % size)
            return self.ring[idx].copy()


class _Worker(QObject):
    """Lives in the audio thread; every slot runs there."""
    positionChanged = Signal("qint64")
    durationChanged = Signal("qint64")
    stateChanged = Signal(int)
    statusChanged = Signal(int)
    errorOccurred = Signal(int, str)

    def __init__(self, rate: int):
        super().__init__()
        self.rate = rate
        self.media = None
        self.sink = None
        self.io = None
        self.int16 = False
        self.pending = bytearray()
        self.eq = None
        self.volume = 0.512
        self.muted = False
        self.paused = False
        self.fade_in_ms = 0  # ms
        self.fade_out_ms = 0  # ms
        self.transport_ms = 0  # ms, for pause/skip/seek/stop
        self._declick_total = self._declick_left = 0  # frames of fade-in after a skip or seek
        self._settling = None
        self._expect = None  # after a skip or seek: (from, to) µs; buffers outside are dropped
        self._expect_dropped = 0
        self.level = 1.0
        self.rg = 1.0  # ReplayGain factor for the song being decoded
        self._ramp_state = None  # (start level, target, start time, length, then)
        self.throttled = False  # decoder paused by us because enough is queued
        self.prebuffering = True  # holding output until PREBUFFER_MS is queued
        self.sink_target = None  # bytes the sound system may hold (None = SINK_BUFFER_MS)

    @Slot()
    def start(self):
        self.eq = Equalizer(self.rate)
        # hold everything in the sound card plus a margin, or the visualizer stops once the buffer is full
        self.tap = AudioTap(self.rate, seconds=SINK_BUFFER_MS / 1000 + 2.0)
        self.media = QMediaPlayer(self)
        self.output = QAudioBufferOutput(_format(self.rate, QAudioFormat.Float), self.media)
        self.media.setAudioBufferOutput(self.output)
        self.output.audioBufferReceived.connect(self._on_buffer)
        m = self.media
        m.positionChanged.connect(lambda ms: self.positionChanged.emit(int(ms)))
        m.durationChanged.connect(lambda ms: self.durationChanged.emit(int(ms)))
        m.playbackStateChanged.connect(self._on_state)
        m.mediaStatusChanged.connect(lambda s: self.statusChanged.emit(int(s.value)))
        m.errorOccurred.connect(lambda e, msg: self.errorOccurred.emit(int(e.value), msg))
        self.devices = QMediaDevices(self)
        self.devices.audioOutputsChanged.connect(self._reopen)
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self._feed)
        self.timer.start(FEED_MS)
        self.ramp_timer = QTimer(self)
        self.ramp_timer.setTimerType(Qt.PreciseTimer)
        self.ramp_timer.setInterval(10)
        self.ramp_timer.timeout.connect(self._ramp_step)
        bpf = 8  # float32 stereo
        self.high = self.rate * bpf * HIGH_MS // 1000
        self.low = self.rate * bpf * LOW_MS // 1000
        self.prebuffer = self.rate * bpf * PREBUFFER_MS // 1000
        self._open_sink()

    def _open_sink(self):
        if self.sink is not None:
            self.sink.stop()
            self.sink.deleteLater()
        dev = QMediaDevices.defaultAudioOutput()
        fmt = _format(self.rate, QAudioFormat.Float)
        self.int16 = not dev.isFormatSupported(fmt)
        if self.int16:
            fmt = _format(self.rate, QAudioFormat.Int16)
        self.sink = QAudioSink(dev, fmt, self)
        self.sink.setBufferSize(fmt.bytesForDuration(SINK_BUFFER_MS * 1000))
        self._apply_volume()
        self.io = self.sink.start()
        if self.paused:
            self.sink.suspend()

    def _reopen(self):
        """The default output changed (e.g. headphones plugged in)."""
        self.pending.clear()
        self._open_sink()

    @Slot(QUrl, bool, bool, float)
    def load(self, url: QUrl, flush: bool, play: bool, gain: float = 1.0):
        if flush and self._audible():
            # fade the old song out first; the new one starts from silence anyway
            self._ramp(0.0, self._cut_ms(),
                       lambda: (self._load_now(url, flush, play, gain), self._ramp(1.0, 60 if self.transport_ms else 0)))
            return
        self._finish_ramp()
        if play and self.level < 1.0:
            # the pause faded the level to zero; restore it
            self.level = 1.0
            self._apply_volume()
        self._load_now(url, flush, play, gain)

    def _load_now(self, url: QUrl, flush: bool, play: bool, gain: float = 1.0):
        self.throttled = False
        if flush:
            self._flush()
        # Set with the new song so a gapless change switches level exactly at the join.
        self.rg = float(gain)
        if flush and url.isLocalFile():  # streams keep their own clock
            self._expect = (0, 40_000)
                                               # allow a slightly wider window for a song skipped just after it started
            self._expect_dropped = 0
        self.media.setSource(url)
        self.media.setPlaybackRate(DECODE_SPEED if url.isLocalFile() else 1.0)
        if play:
            self.media.play()

    @Slot(bool)
    def set_responsive(self, on: bool):
        """Small buffer while the EQ window is open, full one otherwise."""
        bpf = 8
        if on:
            self.high = self.rate * bpf * RESPONSIVE_HIGH_MS // 1000
            self.low = self.rate * bpf * RESPONSIVE_LOW_MS // 1000
            frame = self.sink.format().bytesPerFrame() if self.sink is not None else bpf
            self.sink_target = self.rate * max(frame, 1) * RESPONSIVE_SINK_MS // 1000
        else:
            self.high = self.rate * bpf * HIGH_MS // 1000
            self.low = self.rate * bpf * LOW_MS // 1000
            self.sink_target = None

    @Slot()
    def play(self):
        self._finish_ramp()
        if self.level < 1.0:
            self.media.play()
            self._ramp(1.0, max(60, self._cut_ms()))
            return
        self.level = 1.0
        self._apply_volume()
        self.media.play()

    @Slot()
    def pause(self):
        if self._audible():
            self._ramp(0.0, self._cut_ms(), self._pause_now)
            return
        self._pause_now()

    def _pause_now(self):
        if self.throttled:
            # decoder is already paused; make it the user's pause
            self.throttled = False
            self._set_paused(True)
            self.stateChanged.emit(int(QMediaPlayer.PausedState.value))
        else:
            self.media.pause()

    @Slot(bool)
    def stop(self, flush: bool):
        if flush and self._audible():
            self._ramp(0.0, self._cut_ms(), lambda: self._stop_now(flush))
            return
        self._stop_now(flush)

    def _stop_now(self, flush: bool):
        self.throttled = False
        if flush:
            self._flush()
        else:
            self._drain_eq()  # end of list: let the last moments play
        self.media.stop()
        self.level = 1.0
        self._apply_volume()

    @Slot("qint64", bool)
    def seek(self, ms: int, flush: bool):
        if flush and self._audible():
            fast = min(self._cut_ms(), 150)  # seeking should still feel instant
            self._ramp(0.0, fast, lambda: (self._seek_now(ms, flush), self._ramp(1.0, fast)))
            return
        self._seek_now(ms, flush)

    def _seek_now(self, ms: int, flush: bool):
        if flush:
            self._flush()
            if self.media.source().isLocalFile():
                self._expect = (max(0, ms - 400) * 1000, (ms + 400) * 1000)
                self._expect_dropped = 0
        self.media.setPosition(ms)

    @Slot(int, int)
    def set_fades(self, fade_in_ms: int, fade_out_ms: int):
        self.fade_in_ms, self.fade_out_ms = max(0, fade_in_ms), max(0, fade_out_ms)

    @Slot(int)
    def set_fade_out(self, fade_out_ms: int):
        self.fade_out_ms = max(0, fade_out_ms)

    @Slot(int)
    def set_transport_fade(self, ms: int):
        self.transport_ms = max(0, ms)

    def _cut_ms(self) -> int:
        """Length of the fade for skip/pause: the transport fade or a short de-click."""
        return self.transport_ms if self.transport_ms > 0 else CUT_MS

    def _audible(self) -> bool:
        return (not self.paused and self.sink is not None
                and self.sink.state() not in (STOPPED, SUSPENDED) and bool(self.pending or
                                                                        self.sink.bytesFree() < self.sink.bufferSize()))

    def _ramp(self, target: float, ms: int, then=None):
        self._finish_ramp()
        if ms <= 0 or self.sink is None:
            self.level = target
            self._apply_volume()
            if then:
                then()
            return
        self._ramp_state = (self.level, target, time.monotonic(), ms / 1000.0, then)
        self.ramp_timer.setInterval(2 if ms < 100 else 10)  # a de-click needs fine steps
        self.ramp_timer.start()

    def _ramp_step(self):
        if self._ramp_state is None:
            self.ramp_timer.stop()
            return
        start, target, t0, length, then = self._ramp_state
        k = min(1.0, (time.monotonic() - t0) / length)
        if length >= 0.1:
            k = k * k * (3 - 2 * k)  # smoothstep
        self.level = start + (target - start) * k
        self._apply_volume()
        if k >= 1.0:
            self._ramp_state = None
            self.ramp_timer.stop()
            if then:
                if target == 0.0:
                    # wait for the silence to reach the speakers before dropping the old audio
                    self._settling = then
                    QTimer.singleShot(SETTLE_MS, self._settled)
                else:
                    then()

    def _settled(self):
        then, self._settling = self._settling, None
        if then:
            then()

    def _finish_ramp(self):
        """A new command arrived mid-fade: finish it now."""
        if self._settling is not None:
            self._settled()
        if self._ramp_state is not None:
            _start, target, _t0, _len, then = self._ramp_state
            self._ramp_state = None
            self.ramp_timer.stop()
            self.level = target
            self._apply_volume()
            if then:
                then()

    def _track_gain(self, buf, frames: int):
        """Fade-in / fade-out gain per frame, or None."""
        fi, fo = self.fade_in_ms, self.fade_out_ms
        if not fi and not fo:
            return None
        start_ms = buf.startTime() / 1000.0
        length_ms = frames * 1000.0 / self.rate
        dur = self.media.duration()
        need_in = fi and start_ms < fi
        need_out = fo and dur > 0 and start_ms + length_ms > dur - fo
        if not need_in and not need_out:
            return None
        t = start_ms + np.arange(frames, dtype=np.float32) * (1000.0 / self.rate)
        g = np.ones(frames, np.float32)
        if need_in:
            g = np.minimum(g, np.clip(t / fi, 0.0, 1.0))
        if need_out:
            g = np.minimum(g, np.clip((dur - t) / fo, 0.0, 1.0))
        return np.sin(g * (np.pi / 2)).astype(np.float32)

    def _drain_eq(self):
        """Push out the few ms the EQ holds back."""
        if self.eq is None:
            return
        y = self.eq.process(np.zeros((self.eq.latency_frames + self.eq.block, 2), np.float32))
        if len(y):
            y = soft_clip(y)
            if self.int16:
                self.pending += (np.clip(y, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
            else:
                self.pending += y.tobytes()
        self.eq.reset()

    def _on_buffer(self, buf):
        if not buf.isValid() or buf.frameCount() == 0:
            return
        if self._expect is not None:
            lo, hi = self._expect
            if not (lo <= buf.startTime() <= hi) and self._expect_dropped < 25:
                self._expect_dropped += 1
                return  # still the old song or position
            self._expect = None  # after 25 stray buffers, play whatever comes rather than stay silent
        x = np.frombuffer(buf.constData(), np.float32).reshape(-1, 2)
        gain = self._track_gain(buf, len(x))
        if gain is not None:
            x = x * gain[:, None]
        if self._declick_left > 0:  # just skipped or seeked: start from silence
            total = self._declick_total
            n = min(len(x), self._declick_left)
            done = total - self._declick_left
            ramp = (np.arange(done, done + n, dtype=np.float32) + 1.0) / total
            x = np.array(x, copy=True)
            x[:n] *= ramp[:, None]
            self._declick_left -= n
        if self.rg != 1.0:
            x = x * np.float32(self.rg)
        y = self.eq.process(x)
        if not len(y):
            return
        y = soft_clip(y)
        if self.int16:
            self.pending += (np.clip(y, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
        else:
            self.pending += y.tobytes()
        self._feed()
        if (len(self.pending) > self.high and not self.throttled and not self.paused
                and self.media.playbackState() == QMediaPlayer.PlayingState):
            self.throttled = True
            self.media.pause()

    def _feed(self):
        if self.throttled and len(self.pending) < self.low:
            self.throttled = False
            self.media.play()
        self._mark()
        if not self.pending or self.io is None or self.paused:
            return
        if self.prebuffering:
            if len(self.pending) < self.prebuffer and self.media.playbackState() == QMediaPlayer.PlayingState:
                return
            self.prebuffering = False
        elif self.sink.state() == IDLE and len(self.pending) < self.prebuffer:
            # the sound card ran dry: rebuild the buffer first
            self.prebuffering = True
            if self.media.playbackState() == QMediaPlayer.PlayingState:
                from musicwell import log as mwlog
                if mwlog.now_and_then("ran dry"):
                    mwlog.log.warning("The sound ran dry for a moment (the computer was busy?)")
            return
        free = self.sink.bytesFree()
        frame = self.sink.format().bytesPerFrame()
        if frame <= 0:
            self.pending.clear()  # no output: don't let it pile up
            return
        if self.sink_target is not None:
            free = min(free, max(0, self.sink_target - (self.sink.bufferSize() - free)))
        n = min(free, len(self.pending)) // frame * frame
        if n > 0:
            written = self.io.write(bytes(self.pending[:n]))
            if written > 0:
                chunk = bytes(self.pending[:written])
                del self.pending[:written]
                if self.int16:
                    x = np.frombuffer(chunk, np.int16).astype(np.float32) / 32768.0
                else:
                    x = np.frombuffer(chunk, np.float32)
                self.tap.write(x.reshape(-1, 2).mean(axis=1))
                self._mark()
        if self.sink.state() == STOPPED and self.sink.error() != NO_ERROR:
            from musicwell import log as mwlog
            if mwlog.now_and_then("sink error"):
                mwlog.log.warning("The sound output stopped (%s); opening it again", self.sink.error())
            self._open_sink()

    def _mark(self):
        if self.sink is None:
            return
        frame = self.sink.format().bytesPerFrame()
        if frame <= 0:  # no usable sound device
            self.tap.mark(0, False)
            return
        buffered = max(0, self.sink.bufferSize() - self.sink.bytesFree()) // frame
        self.tap.pending = len(self.pending) // frame
        active = not self.paused and self.sink.state() not in (STOPPED, SUSPENDED)
        self.tap.mark(buffered, active and (buffered > 0 or bool(self.pending)))

    def _flush(self):
        """Drop audio queued here and in the sound system so nothing of the old position is heard."""
        self.pending.clear()
        self.eq.reset()
        self.prebuffering = True
        self._declick_total = self._declick_left = max(1, self.rate * DECLICK_IN_MS // 1000)
        if self.sink is not None and self.sink.state() != STOPPED:
            self.sink.reset()
            self.io = self.sink.start()
            if self.paused:
                self.sink.suspend()
        self.tap.reset()

    def _on_state(self, state):
        if self.throttled and state == QMediaPlayer.PausedState:
            return  # our own pause; the queued audio is still playing
        self._set_paused(state == QMediaPlayer.PausedState)
        self.stateChanged.emit(int(state.value))

    def _set_paused(self, paused: bool):
        self.paused = paused
        if self.sink is None:
            return
        if paused:
            self.sink.suspend()
        elif self.sink.state() == SUSPENDED:
            self.sink.resume()
            self._feed()

    @Slot(list, float)
    def set_eq(self, gains: list, preamp: float):
        self.eq.set(gains, preamp)

    @Slot(float)
    def set_replaygain(self, gain: float):
        """ReplayGain settings changed: apply to the playing song now."""
        self.rg = float(gain)

    @Slot(float, bool)
    def set_volume(self, volume: float, muted: bool):
        self.volume, self.muted = volume, muted
        self._apply_volume()

    def _apply_volume(self):
        if self.sink is not None:
            self.sink.setVolume(0.0 if self.muted else self.volume * self.level)

    @Slot()
    def shutdown(self):
        """Destroy everything made on this thread here. Left to Python at exit, the sink would be torn down from the wrong thread and crash (seen with PipeWire)."""
        from shiboken6 import Shiboken
        if getattr(self, "timer", None) is not None:
            self.timer.stop()
        if getattr(self, "ramp_timer", None) is not None:
            self.ramp_timer.stop()
        self._ramp_state = None
        if self.media is not None:
            try:
                self.output.audioBufferReceived.disconnect()
            except (RuntimeError, TypeError):
                pass
            self.media.stop()
        if self.sink is not None:
            self.sink.stop()
        self.io = None
        for name in ("sink", "media", "devices", "timer", "ramp_timer"):  # media also owns its buffer output
            obj = getattr(self, name, None)
            if obj is not None and Shiboken.isValid(obj):
                Shiboken.delete(obj)
            setattr(self, name, None)
        self.output = None


class ThreadedMedia(QObject):
    """Stand-in for QMediaPlayer, used from the UI thread."""
    positionChanged = Signal("qint64")
    durationChanged = Signal("qint64")
    playbackStateChanged = Signal(object)
    mediaStatusChanged = Signal(object)
    errorOccurred = Signal(object, str)

    _load = Signal(QUrl, bool, bool, float)
    _rg = Signal(float)
    _responsive = Signal(bool)
    _play = Signal()
    _pause = Signal()
    _stop = Signal(bool)
    _seek = Signal("qint64", bool)
    _fades = Signal(int, int)
    _fade_out = Signal(int)
    _transport_fade = Signal(int)

    def __init__(self, worker: _Worker, parent=None):
        super().__init__(parent)
        self._position = 0
        self._duration = 0
        self._state = QMediaPlayer.StoppedState
        self._error = ""
        w = worker
        self._load.connect(w.load)
        self._rg.connect(w.set_replaygain)
        self._responsive.connect(w.set_responsive)
        self._play.connect(w.play)
        self._pause.connect(w.pause)
        self._stop.connect(w.stop)
        self._seek.connect(w.seek)
        self._fades.connect(w.set_fades)
        self._fade_out.connect(w.set_fade_out)
        self._transport_fade.connect(w.set_transport_fade)
        w.positionChanged.connect(self._on_pos)
        w.durationChanged.connect(self._on_dur)
        w.stateChanged.connect(self._on_state)
        w.statusChanged.connect(lambda s: self.mediaStatusChanged.emit(QMediaPlayer.MediaStatus(s)))
        w.errorOccurred.connect(self._on_error)

    # QMediaPlayer-like API
    def load(self, url: QUrl, flush: bool = True, play: bool = True, gain: float = 1.0):
        self._position = 0
        if play:
            self._state = QMediaPlayer.PlayingState
        self._load.emit(url, flush, play, float(gain))

    def set_replaygain(self, gain: float):
        self._rg.emit(float(gain))

    def set_responsive(self, on: bool):
        self._responsive.emit(bool(on))

    def set_fades(self, fade_in_ms: int, fade_out_ms: int):
        self._fades.emit(int(fade_in_ms), int(fade_out_ms))

    def set_fade_out(self, fade_out_ms: int):
        self._fade_out.emit(int(fade_out_ms))

    def set_transport_fade(self, ms: int):
        self._transport_fade.emit(int(ms))

    def setSource(self, url: QUrl):
        self.load(url, True, False)

    def play(self):
        self._play.emit()

    def pause(self):
        self._pause.emit()

    def stop(self, flush: bool = True):
        self._position = 0
        self._stop.emit(flush)
        if self._state != QMediaPlayer.StoppedState:
            # The player may have stopped on its own (a stream that failed to open) without reporting a change.
            self._state = QMediaPlayer.StoppedState
            self.playbackStateChanged.emit(self._state)

    def setPosition(self, ms: int, flush: bool = True):
        self._position = int(ms)
        self._seek.emit(int(ms), flush)

    def position(self) -> int:
        return self._position

    def duration(self) -> int:
        return self._duration

    def playbackState(self):
        return self._state

    def errorString(self) -> str:
        return self._error

    # updates from the audio thread
    def _on_pos(self, ms):
        self._position = int(ms)
        self.positionChanged.emit(ms)

    def _on_dur(self, ms):
        self._duration = int(ms)
        self.durationChanged.emit(ms)

    def _on_state(self, s):
        self._state = QMediaPlayer.PlaybackState(s)
        self.playbackStateChanged.emit(self._state)

    def _on_error(self, e, msg):
        self._error = msg
        self.errorOccurred.emit(QMediaPlayer.Error(e), msg)


class AudioEngine(QObject):
    _eq = Signal(list, float)
    _volume = Signal(float, bool)
    _shutdown = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rate = _pick_rate()
        self.tap = None
        self.thread = QThread(self)
        self.thread.setObjectName("musicwell-audio")
        self.worker = _Worker(self.rate)
        self.worker.moveToThread(self.thread)
        self.media = ThreadedMedia(self.worker, self)
        self._eq.connect(self.worker.set_eq)
        self._volume.connect(self.worker.set_volume)
        self._shutdown.connect(self.worker.shutdown, Qt.BlockingQueuedConnection)
        self.thread.started.connect(self.worker.start)
        self.thread.start(QThread.TimeCriticalPriority)


        self.eq_enabled = False
        self.gains = [0.0] * 10
        self.preamp = 0.0
        self._vol = 0.512
        self._muted = False
        self._shadow = False  # silent playback for the visualizer while casting

    def latency_ms(self) -> int:
        """How far the reported position runs ahead of what you hear."""
        tap = getattr(self.worker, "tap", None)
        eq = getattr(self.worker, "eq", None)
        if tap is None or not self.rate:
            return 0
        frames = tap.buffered + tap.pending + (eq.latency_frames if eq is not None else 0)
        return int(frames * 1000 / self.rate)

    def samples(self, n: int = 2048):
        """Mono samples playing through the speakers now, or None."""
        tap = getattr(self.worker, "tap", None)
        return tap.latest(n) if tap is not None else None

    def set_eq(self, enabled: bool, gains, preamp: float):
        """EQ off is a flat filter, so switching never causes a gap."""
        self.eq_enabled, self.gains, self.preamp = enabled, list(gains), float(preamp)
        if enabled:
            self._eq.emit([float(g) for g in gains], float(preamp))
        else:
            self._eq.emit([0.0] * len(self.gains), 0.0)

    def set_volume(self, linear: float):
        self._vol = linear
        self._volume.emit(self._vol, self._muted or self._shadow)

    def set_muted(self, muted: bool):
        self._muted = muted
        self._volume.emit(self._vol, self._muted or self._shadow)

    def set_shadow(self, on: bool):
        """Decode and analyse, but send nothing to the speakers."""
        self._shadow = on
        self._volume.emit(self._vol, self._muted or self._shadow)

    def is_muted(self) -> bool:
        return self._muted

    def shutdown(self):
        if self.thread.isRunning():
            self._shutdown.emit()
            self.thread.quit()
            self.thread.wait(3000)
        if not self.thread.isRunning():
            from shiboken6 import Shiboken
            if Shiboken.isValid(self.worker):
                Shiboken.delete(self.worker)
