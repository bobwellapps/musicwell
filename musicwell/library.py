"""The music library: SQLite database, in-memory track list and a background scanner."""
from __future__ import annotations

import json
import os
import pickle
import re
import sqlite3
import threading
import time

from PySide6.QtCore import QObject, QThread, Signal

from musicwell import fields
from musicwell import tags as tagio
from musicwell.paths import cache_dir, db_path

TRACK_FIELDS = [
    "path", "mtime", "filesize", "title", "artist", "album", "albumartist", "genre", "composer",
    "year", "track", "disc", "length", "bitrate", "samplerate", "bitdepth", "channels", "format",
    "extra",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    mtime REAL, filesize INTEGER,
    title TEXT, artist TEXT, album TEXT, albumartist TEXT, genre TEXT, composer TEXT DEFAULT '',
    year INTEGER, track INTEGER, disc INTEGER,
    length REAL, bitrate INTEGER, samplerate INTEGER, bitdepth INTEGER, channels INTEGER,
    format TEXT,
    extra TEXT DEFAULT '{}',
    added REAL,
    rating INTEGER DEFAULT 0,
    playcount INTEGER DEFAULT 0,
    skipcount INTEGER DEFAULT 0,
    lastplayed REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS folders (path TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY);     -- single songs added on their own (dropped)
CREATE TABLE IF NOT EXISTS online (id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT UNIQUE, data TEXT);  -- free music in playlists
CREATE TABLE IF NOT EXISTS plays (
    played_at REAL, track_id INTEGER, seconds REAL,
    title TEXT, artist TEXT, album TEXT, albumartist TEXT, genre TEXT, path TEXT
);
CREATE INDEX IF NOT EXISTS plays_time ON plays (played_at);
CREATE TABLE IF NOT EXISTS playlists (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS playlist_tracks (
    playlist_id INTEGER, pos INTEGER, track_id INTEGER,
    PRIMARY KEY (playlist_id, pos)
);
-- tracks_gen goes up on every change to tracks, so the startup snapshot knows when it's out of date
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value INTEGER);
INSERT OR IGNORE INTO meta VALUES ('tracks_gen', 0);
CREATE TRIGGER IF NOT EXISTS tracks_gen_ins AFTER INSERT ON tracks
    BEGIN UPDATE meta SET value = value + 1 WHERE key = 'tracks_gen'; END;
CREATE TRIGGER IF NOT EXISTS tracks_gen_upd AFTER UPDATE ON tracks
    BEGIN UPDATE meta SET value = value + 1 WHERE key = 'tracks_gen'; END;
CREATE TRIGGER IF NOT EXISTS tracks_gen_del AFTER DELETE ON tracks
    BEGIN UPDATE meta SET value = value + 1 WHERE key = 'tracks_gen'; END;
"""


def connect(path=None) -> sqlite3.Connection:
    con = sqlite3.connect(str(path or db_path()), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.executescript(SCHEMA)
    _migrate(con)
    return con


def _migrate(con: sqlite3.Connection):
    cols = {r[1] for r in con.execute("PRAGMA table_info(tracks)")}
    rescan = False
    if "composer" not in cols:
        con.execute("ALTER TABLE tracks ADD COLUMN composer TEXT DEFAULT ''")
        rescan = True
    if "extra" not in cols:
        con.execute("ALTER TABLE tracks ADD COLUMN extra TEXT DEFAULT '{}'")
        rescan = True
    # Schema versions force a full tag re-read when new tags are read (1: totals, 2: MP3 original dates).
    if con.execute("PRAGMA user_version").fetchone()[0] < 2:
        con.execute("PRAGMA user_version = 2")
        rescan = True
    if rescan:
        con.execute("UPDATE tracks SET mtime = 0")  # next scan re-reads every file
        con.commit()


def upsert_track(con: sqlite3.Connection, t: dict) -> None:
    """Insert or update a track, keeping ratings and play counts."""
    cols = ", ".join(TRACK_FIELDS)
    marks = ", ".join("?" for _ in TRACK_FIELDS)
    updates = ", ".join(f"{f}=excluded.{f}" for f in TRACK_FIELDS if f != "path")
    con.execute(
        f"INSERT INTO tracks ({cols}, added) VALUES ({marks}, ?) "
        f"ON CONFLICT(path) DO UPDATE SET {updates}",
        [t[f] for f in TRACK_FIELDS] + [time.time()],
    )


# "year" or "original" (original year tag when present, e.g. a remaster)
DECADE_FROM = "year"

# original release date/year tags, as named by read_extra_tags
ORIGINAL_YEAR_TAGS = ("originaldate", "originalyear", "original_date", "original_year", "tory", "tdor",
                      "origyear", "original_release_date", "original_release_year", "originalreleasedate")


# tag chosen in Settings ("" = automatic)
ORIGINAL_YEAR_TAG = ""

_YEAR = re.compile(r"(?<!\d)(1[89]\d\d|20\d\d|21\d\d)(?!\d)")


def _year_in(v) -> int:
    m = _YEAR.search(str(v or ""))
    return int(m.group(1)) if m else 0


def looks_like_original_year(tag: str) -> bool:
    """Hand-made tag names, e.g. ORIGINAL RELEASE, ORIG_YR."""
    k = tag.lower()
    return "orig" in k and any(w in k for w in ("year", "yr", "date", "release"))


def original_year(extra: dict, tag: str | None = None) -> int:
    """tag: the one to read ("" = automatic, None = the Settings choice)."""
    tag = ORIGINAL_YEAR_TAG if tag is None else tag
    if tag:
        return _year_in(extra.get(tag))
    for k in ORIGINAL_YEAR_TAGS:
        y = _year_in(extra.get(k))
        if y:
            return y
    for k, v in extra.items():
        if looks_like_original_year(k):
            y = _year_in(v)
            if y:
                return y
    return 0


def set_decades(tracks, source: str, tag: str | None = None):
    """Recompute every song's original year and decade."""
    global DECADE_FROM, ORIGINAL_YEAR_TAG
    DECADE_FROM = source
    if tag is not None:
        ORIGINAL_YEAR_TAG = tag
    for t in tracks:
        if not t.get("stream") and not t.get("remote"):
            t["origyear"] = original_year(t.get("_extra") or {})
        _decade(t)


def _decade(t: dict):
    y = t["origyear"] if DECADE_FROM == "original" and t.get("origyear") else t["year"]
    t["decade"] = (y // 10 * 10) if y else 0


# Online songs kept in playlists live in their own table with ids from here up.
ONLINE_BASE = 1_000_000_000


def online_id(rowid: int) -> int:
    return -(ONLINE_BASE + int(rowid))


def is_online_id(tid: int) -> bool:
    return tid <= -ONLINE_BASE


def with_derived(t: dict) -> dict:
    """Add the precomputed fields the UI and search use."""
    t["source"] = "Local"
    t["composer"] = t.get("composer") or ""
    t["artist_key"] = t["albumartist"] or t["artist"]
    t["folder"] = os.path.basename(os.path.dirname(t["path"]))
    fields.derive(t)
    t["origyear"] = original_year(t["_extra"])
    _decade(t)
    t["_text"] = " ".join(
        (t["title"], t["artist"], t["album"], t["albumartist"], t["genre"], t["composer"],
         t["grouping"], t["comment"], t["label"], t["mood"])
    ).lower()
    return t


def load_tracks(con: sqlite3.Connection) -> dict[int, dict]:
    cur = con.execute("SELECT * FROM tracks")
    cur.row_factory = None  # plain tuples are much faster than sqlite3.Row
    names = [d[0] for d in cur.description]
    out = {}
    for row in cur:
        t = with_derived(dict(zip(names, row)))
        out[t["id"]] = t
    return out


# Startup snapshot: the loaded tracks pickled, about 4x faster than reading and deriving every row.
SNAPSHOT_VERSION = 1


def _snapshot_path():
    return cache_dir() / "library.snapshot"


def _code_stamp() -> tuple:
    """Changes when the code that builds tracks changes (e.g. after an update)."""
    out = []
    for mod in (__file__, fields.__file__):
        try:
            st = os.stat(mod)
            out.append((st.st_mtime_ns, st.st_size))
        except OSError:
            out.append(None)
    return tuple(out)


def _snapshot_key(con: sqlite3.Connection) -> tuple:
    gen = con.execute("SELECT value FROM meta WHERE key = 'tracks_gen'").fetchone()[0]
    return (SNAPSHOT_VERSION, str(db_path()), gen, DECADE_FROM, ORIGINAL_YEAR_TAG, _code_stamp())


def load_tracks_keyed(con: sqlite3.Connection) -> tuple[tuple, dict]:
    """(snapshot key, tracks), read in one transaction so they match."""
    in_tx = con.in_transaction
    if not in_tx:
        con.execute("BEGIN")
    try:
        return _snapshot_key(con), load_tracks(con)
    finally:
        if not in_tx:
            con.execute("COMMIT")


def read_snapshot(con: sqlite3.Connection):
    """(key, tracks) from the snapshot if it's still up to date, else None."""
    try:
        with open(_snapshot_path(), "rb") as f:
            key = pickle.load(f)
            if key != _snapshot_key(con):
                return None
            return key, pickle.load(f)
    except Exception:
        return None


def write_snapshot(key: tuple, tracks):
    """tracks: the dict, or it already pickled."""
    if not isinstance(tracks, bytes):
        tracks = pickle.dumps(tracks, protocol=pickle.HIGHEST_PROTOCOL)
    path = _snapshot_path()
    tmp = path.with_suffix(".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "wb") as f:
            pickle.dump(key, f, protocol=pickle.HIGHEST_PROTOCOL)
            f.write(tracks)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass


UPSERT_SQL = None


def _upsert_sql() -> str:
    global UPSERT_SQL
    if UPSERT_SQL is None:
        cols = ", ".join(TRACK_FIELDS)
        marks = ", ".join("?" for _ in TRACK_FIELDS)
        updates = ", ".join(f"{f}=excluded.{f}" for f in TRACK_FIELDS if f != "path")
        UPSERT_SQL = (f"INSERT INTO tracks ({cols}, added) VALUES ({marks}, ?) "
                      f"ON CONFLICT(path) DO UPDATE SET {updates}")
    return UPSERT_SQL


def _helpers_wanted(n_files: int) -> int:
    """Tag reader processes: none for small jobs or one core, otherwise cores - 1."""
    if n_files < 150:
        return 0
    try:
        cores = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        cores = os.cpu_count() or 1
    return 0 if cores < 2 else max(1, min(cores - 1, 6))


class Scanner(QThread):
    """Finds new or changed songs in your folders, then reads their tags (in helper processes when worth it)."""
    progress = Signal(int, str)  # songs so far, status text
    done = Signal(int, int)  # added/updated, removed
    skipped = Signal(int)  # files that couldn't be added (listed in the log)
    partial = Signal(int)  # saved so far

    CHUNK = 24  # songs per helper job
    CHUNK_TIMEOUT = 180  # seconds per job before giving up (slow network shares)
    SINGLE_TIMEOUT = 60  # seconds per song when retried alone
    SAVE_EVERY = 400  # songs per save
    SHOW_EVERY = (3000, 8.0)  # show progress after this many songs and seconds

    def __init__(self, folders: list[str], files: list[str] | None = None, parent=None):
        super().__init__(parent)
        self.folders = folders
        self.files = list(files or [])  # single files added outside the folders
        self._stop = False
        self.total = 0  # songs to read

    def stop(self):
        self._stop = True

    def run(self):
        # One bad file must never stop the scan; the library is always told when it ends.
        import logging
        self._log = logging.getLogger("musicwell.library")
        self._skipped = 0
        changed = removed = 0
        try:
            changed, removed = self._scan()
        except Exception:
            self._log.exception("The scan stopped early")
        if self._skipped:
            self._log.warning("%d file(s) couldn't be added (see above)", self._skipped)
            self.skipped.emit(self._skipped)
        self.done.emit(changed, removed)

    def _say(self, n: int, text: str, force: bool = False):
        now = time.monotonic()
        if force or now - getattr(self, "_said", 0) >= 0.25:  # a few times a second is enough
            self._said = now
            self.progress.emit(n, text)

    def _walk(self, root_folder: str, out: list, seen: set, known: dict):
        """Every song under the folder via os.scandir, visiting each folder once even with link loops."""
        stack = [root_folder]
        visited = set()
        while stack and not self._stop:
            d = stack.pop()
            try:
                st = os.stat(d)
                key = (st.st_dev, st.st_ino)
                if key in visited:
                    continue
                visited.add(key)
                with os.scandir(d) as it:
                    entries = sorted(it, key=lambda e: e.name)
            except OSError:
                continue
            subdirs = []
            for e in entries:
                name = e.name
                if name.startswith("."):
                    continue
                try:
                    if e.is_dir():
                        subdirs.append(e.path)
                        continue
                    if os.path.splitext(name)[1].lower() not in tagio.AUDIO_EXTS:
                        continue
                    if not e.is_file():  # skip pipes and devices
                        continue
                    mtime = e.stat().st_mtime
                except OSError:
                    continue
                path = e.path
                seen.add(path)
                if known.get(path) != mtime:
                    out.append(path)
            stack.extend(reversed(subdirs))
            self._say(len(seen), f"Looking for songs… {len(seen):,} found")

    def _read_here(self, paths):
        for p in paths:
            if self._stop:
                return
            try:
                yield p, tagio.read_track(p), ""
            except Exception as e:
                yield p, None, f"{type(e).__name__}: {e}"

    def _start_helper(self):
        """Start a helper process (tagworker.py) with the same Python and package."""
        import subprocess
        import sys
        env = dict(os.environ)
        here = os.path.dirname(os.path.dirname(os.path.abspath(tagio.__file__)))  # folder containing musicwell
        env["PYTHONPATH"] = here + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        return subprocess.Popen([sys.executable, "-s", "-m", "musicwell.tagworker"], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env, close_fds=True,
                                start_new_session=True)  # own process group so it can be stopped with its children

    @staticmethod
    def _end_helper(proc, kill: bool = False):
        import signal

        def hard():
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (OSError, AttributeError):
                proc.kill()
            proc.wait(timeout=2)
        try:
            if kill:
                hard()
            else:
                proc.stdin.close()
                proc.wait(timeout=2)
        except Exception:
            try:
                hard()
            except Exception:
                pass

    def _read_all(self, paths: list[str]):
        """(path, tags or None, error) for every path, using helpers when worth it."""
        n = _helpers_wanted(len(paths))
        helpers = []
        if n:
            try:
                helpers = [self._start_helper() for _ in range(n)]
            except Exception as e:
                self._log.warning("Reading tags in this process (helpers couldn't start: %s)", e)
                for h in helpers:
                    self._end_helper(h, kill=True)
                helpers = []
        if not helpers:
            yield from self._read_here(paths)
            return
        self._log.info("Reading %d songs' tags with %d helper process(es)", len(paths), len(helpers))
        import json
        import selectors
        from collections import deque
        jobs = deque((paths[i:i + self.CHUNK], self.CHUNK_TIMEOUT) for i in range(0, len(paths), self.CHUNK))
        busy = {}  # helper -> (job songs, time limit, start time)
        sel = selectors.DefaultSelector()
        fallback = False
        try:
            while (jobs or busy) and not self._stop:
                for h in helpers:
                    if h not in busy and jobs:
                        chunk, limit = jobs.popleft()
                        try:
                            h.stdin.write(json.dumps(chunk, ensure_ascii=True).encode("ascii") + b"\n")
                            h.stdin.flush()
                        except Exception:
                            jobs.appendleft((chunk, limit))
                            fallback = True  # can't talk to a helper: do the rest here
                            break
                        busy[h] = (chunk, limit, time.monotonic())
                        sel.register(h.stdout, selectors.EVENT_READ, h)
                if fallback:
                    break
                for key, _ in sel.select(timeout=0.25):
                    h = key.data
                    chunk, limit, _t = busy.pop(h)
                    sel.unregister(h.stdout)
                    line = h.stdout.readline()
                    try:
                        out = json.loads(line) if line else None
                    except ValueError:
                        out = None
                    if out is None or (out and out[0][0] is None):
                        # helper died or got confused: replace it and retry this job one song at a time
                        helpers[helpers.index(h)] = self._replace_helper(h)
                        yield from self._retry(chunk, jobs, "the helper reading it stopped")
                        continue
                    for p, t, why in out:
                        yield p, t, why
                now = time.monotonic()
                for h, (chunk, limit, t0) in list(busy.items()):
                    if now - t0 > limit:  # a song that never finishes (stuck network share)
                        busy.pop(h)
                        sel.unregister(h.stdout)
                        helpers[helpers.index(h)] = self._replace_helper(h)
                        yield from self._retry(chunk, jobs, "it took too long to read")
        finally:
            sel.close()
            for h in helpers:
                self._end_helper(h, kill=self._stop or bool(busy))
        if fallback and not self._stop:
            rest = [p for chunk, _ in jobs for p in chunk] + [p for chunk, _, _ in busy.values() for p in chunk]
            self._log.warning("Reading the last %d songs in this process (a helper stopped answering)", len(rest))
            yield from self._read_here(rest)

    def _replace_helper(self, h):
        self._end_helper(h, kill=True)
        return self._start_helper()

    def _retry(self, chunk, jobs, why: str):
        """Retry a failed job one song at a time; a single song that fails is skipped."""
        if len(chunk) > 1:
            for p in reversed(chunk):
                jobs.appendleft(([p], self.SINGLE_TIMEOUT))
        else:
            yield chunk[0], None, why

    def _scan(self):
        con = connect()
        known = {r["path"]: r["mtime"] for r in con.execute("SELECT path, mtime FROM tracks")}
        seen: set[str] = set()
        todo: list[str] = []
        self._say(0, "Looking for songs…", force=True)
        for root_folder in self.folders:
            self._walk(root_folder, todo, seen, known)
        for path in self.files:
            if self._stop or not os.path.isfile(path):
                continue
            seen.add(path)
            try:
                if known.get(path) != os.stat(path).st_mtime:
                    todo.append(path)
            except OSError:
                continue
        changed = 0
        total = self.total = len(todo)
        if total:
            self._log.info("%d song(s) to read (%d in the folders)", total, len(seen))
            sql = _upsert_sql()
            rows, t_save = [], time.monotonic()
            shown, t_shown = 0, time.monotonic()
            done = 0
            reader = self._read_all(todo)
            for path, t, why in reader:
                done += 1
                if t is None:
                    self._skipped += 1
                    self._log.warning("Skipped (%s): %s", why or "not a song Musicwell can read, or damaged", path)
                else:
                    try:
                        path.encode("utf-8")
                        rows.append([t[f] for f in TRACK_FIELDS] + [time.time()])
                    except UnicodeEncodeError:
                        self._skipped += 1
                        self._log.warning("Skipped (its name isn't valid UTF-8 text — rename the file to add it): "
                                          "%r", path)
                    except Exception as e:
                        self._skipped += 1
                        self._log.warning("Skipped (%s: %s): %s", type(e).__name__, e, path)
                now = time.monotonic()
                if len(rows) >= self.SAVE_EVERY or (rows and now - t_save > 1.0):
                    changed += self._save(con, sql, rows)
                    rows, t_save = [], now
                    first = shown == 0  # show the first batch soon
                    if (changed - shown >= (1000 if first else self.SHOW_EVERY[0])
                            and now - t_shown >= (2.0 if first else self.SHOW_EVERY[1])):
                        shown, t_shown = changed, now
                        self.partial.emit(changed)
                self._say(done, f"Reading songs… {done:,} of {total:,} ({done * 100 // total}%)")
                if self._stop:
                    break
            reader.close()  # helpers stop now, even mid-scan
            changed += self._save(con, sql, rows)
        removed = 0
        if not self._stop:
            roots = [os.path.join(f, "") for f in self.folders]
            singles = set(self.files)
            gone = [p for p in known if p not in seen]
            # Remove tracks whose files vanished or whose folder left the library.
            gone = [p for p in gone if not os.path.exists(p)
                    or not (any(p.startswith(r) for r in roots) or p in singles)]
            for p in gone:
                con.execute(
                    "DELETE FROM playlist_tracks WHERE track_id IN (SELECT id FROM tracks WHERE path=?)", (p,))
                con.execute("DELETE FROM tracks WHERE path=?", (p,))
            removed = len(gone)
        con.commit()
        con.close()
        return changed, removed

    def _save(self, con, sql: str, rows: list) -> int:
        """Save a batch in one transaction."""
        if not rows:
            return 0
        try:
            con.executemany(sql, rows)
            con.commit()
            return len(rows)
        except Exception:
            con.rollback()
            n = 0
            for r in rows:  # one at a time so one bad row doesn't lose the rest
                try:
                    con.execute(sql, r)
                    n += 1
                except Exception as e:
                    self._skipped += 1
                    self._log.warning("Skipped (couldn't be saved: %s): %s", e, r[0])
            con.commit()
            return n


class Library(QObject):
    changed = Signal()  # tracks added, removed or retagged
    trackUpdated = Signal(int)  # rating or play count of one track
    playlistsChanged = Signal()
    scanProgress = Signal(int, str)
    scanFinished = Signal(int, int)
    scanSkipped = Signal(int)  # files that couldn't be added in the last scan
    loaded = Signal()  # first background load finished
    _bg_loaded = Signal(int, object, str)

    def __init__(self, parent=None, load: bool = True):
        super().__init__(parent)
        self.con = connect()
        self.tracks: dict[int, dict] = {}
        self.scanner: Scanner | None = None
        self._rescan_again = False
        self._gen = 0
        self.scans = 0
        self._bg_loaded.connect(self._on_bg_loaded)
        self._prune_online()
        self._load_online()
        if load:
            self.reload()

    def set_decade_source(self, source: str, tag: str | None = None):
        """'year' or 'original', plus which tag holds the original year."""
        set_decades(self.tracks.values(), source, tag)
        self.changed.emit()

    def reload(self):
        self._gen += 1
        self.tracks = load_tracks(self.con)
        self.changed.emit()

    def reload_async(self, partial: bool = False, kind: str = "start"):
        """Load songs on a background thread: at startup, after a scan ("scan") and during it ("partial")."""
        if partial:
            kind = "partial"
            if getattr(self, "_partial_busy", False):
                return  # a load is still running; the next one covers it
            self._partial_busy = True
        gen = self._gen
        partial = kind

        def work():
            snap = None
            try:
                con = connect()
                got = read_snapshot(con) if partial == "start" else None
                if got is None:
                    key, tracks = load_tracks_keyed(con)
                    if partial != "partial":
                        snap = pickle.dumps(tracks, protocol=pickle.HIGHEST_PROTOCOL)  # before the UI uses them
                else:
                    key, tracks = got
                con.close()
            except Exception:
                key, tracks = None, None
            if partial != "partial":
                self._snap_key = key
            self._bg_loaded.emit(gen, tracks, partial)
            if snap is not None:
                write_snapshot(key, snap)
        threading.Thread(target=work, daemon=True, name="musicwell-load").start()

    def _on_bg_loaded(self, gen: int, tracks, kind: str = "start"):
        if kind == "partial":
            self._partial_busy = False
            if tracks is not None and gen == self._gen and self.is_scanning():
                self.tracks = tracks
                self.changed.emit()
            return
        if kind == "scan":
            if gen == self._gen:
                if tracks is None:
                    self.reload()
                else:
                    self.tracks = tracks
                    self.changed.emit()
                self.playlistsChanged.emit()
            self._scan_finished(*getattr(self, "_scan_result", (0, 0)))
            return
        if tracks is None:  # background read failed: do it here
            self.reload()
        elif gen == self._gen:  # not superseded meanwhile
            self.tracks = tracks
            self.changed.emit()
        self.loaded.emit()

    def all_tracks(self) -> list[dict]:
        return list(self.tracks.values())

    def get(self, tid: int) -> dict | None:
        t = self.tracks.get(tid)
        if t is None and tid < 0:
            t = self.online.get(tid)
        return t

    def _load_online(self):
        self.online: dict[int, dict] = {}
        for rowid, data in self.con.execute("SELECT id, data FROM online"):
            try:
                t = json.loads(data)
            except ValueError:
                continue
            t.update({"id": online_id(rowid), "remote": True, "source": "Online"})
            t.setdefault("_extra", {})
            t.setdefault("_text", " ".join(str(t.get(k) or "") for k in ("title", "artist", "album")).lower())
            self.online[t["id"]] = t

    def add_online(self, tracks: list[dict]) -> list[int]:
        """Store these online songs (for playlists) and return their ids in order."""
        ids = []
        for t in tracks:
            url = t.get("path") or ""
            if not url:
                continue
            keep = {k: v for k, v in t.items() if k not in ("id", "_extra", "_text") and not k.startswith("_")}
            self.con.execute("INSERT OR IGNORE INTO online (url, data) VALUES (?, ?)", (url, json.dumps(keep)))
            rowid = self.con.execute("SELECT id FROM online WHERE url=?", (url,)).fetchone()[0]
            ids.append(online_id(rowid))
        self.con.commit()
        self._load_online()
        return ids

    def _prune_online(self):
        """Forget online songs that are no longer in any playlist."""
        used = {tid for (tid,) in self.con.execute("SELECT track_id FROM playlist_tracks") if is_online_id(tid)}
        for rowid, in self.con.execute("SELECT id FROM online").fetchall():
            if online_id(rowid) not in used:
                self.con.execute("DELETE FROM online WHERE id=?", (rowid,))
        self.con.commit()

    def tag_counts(self) -> dict[str, int]:
        """How many songs have each extra tag (for custom columns)."""
        counts: dict[str, int] = {}
        for t in self.tracks.values():
            for k in t.get("_extra", {}):
                counts[k] = counts.get(k, 0) + 1
        return counts

    def folders(self) -> list[str]:
        return [r[0] for r in self.con.execute("SELECT path FROM folders ORDER BY path")]

    def files(self) -> list[str]:
        """Single songs added outside your music folders."""
        return [r[0] for r in self.con.execute("SELECT path FROM files ORDER BY path")]

    def in_folders(self, path: str) -> bool:
        from musicwell.system import path_key
        p = path_key(path)
        return any(p == path_key(f) or p.startswith(os.path.join(path_key(f), "")) for f in self.folders())

    def add_files(self, paths: list[str]) -> dict[str, int]:
        """Add only these files. Returns {path: id} for those that could be read."""
        added = []
        for p in paths:
            p = os.path.abspath(p)
            t = tagio.read_track(p)
            if t is None:
                continue
            if not self.in_folders(p):
                self.con.execute("INSERT OR IGNORE INTO files VALUES (?)", (p,))
            upsert_track(self.con, t)
            added.append(p)
        self.con.commit()
        if not added:
            return {}
        self.reload()
        by_path = {t["path"]: tid for tid, t in self.tracks.items()}
        return {p: by_path[p] for p in added if p in by_path}

    def add_folder(self, path: str):
        path = os.path.abspath(os.path.expanduser(path))
        self.con.execute("INSERT OR IGNORE INTO folders VALUES (?)", (path,))
        self.con.commit()
        self.scan()

    def remove_folder(self, path: str):
        self.con.execute("DELETE FROM folders WHERE path=?", (path,))
        self.con.commit()
        self.scan()

    def scan(self):
        self.scans += 1
        if self.scanner and self.scanner.isRunning():
            self._rescan_again = True
            return
        self.scanner = Scanner(self.folders(), self.files())
        import logging
        import time
        self._scan_t0 = time.monotonic()
        logging.getLogger("musicwell.library").info("Scanning %d folder(s)", len(self.folders()))
        self.scanner.progress.connect(self.scanProgress)
        self.scanner.partial.connect(lambda n: self.reload_async(partial=True))  # songs appear as the scan goes
        self.scanner.done.connect(self._scan_done)
        self.scanner.skipped.connect(self.scanSkipped)
        self.scanner.start()

    def is_scanning(self) -> bool:
        return bool(self.scanner and self.scanner.isRunning())

    def _scan_done(self, changed: int, removed: int):
        import logging
        import time
        logging.getLogger("musicwell.library").info(
            "Scan finished in %.1f s: %d new or changed, %d gone", time.monotonic() - getattr(self, "_scan_t0", 0),
            changed, removed)
        if changed or removed:
            # reload in the background; 20,000+ songs take about a second
            self._gen += 1  # drop a partial load still in flight
            self._scan_result = (changed, removed)
            self.reload_async(kind="scan")
            return
        self._scan_finished(changed, removed)

    def _scan_finished(self, changed: int, removed: int):
        self.scanFinished.emit(changed, removed)
        if self._rescan_again:
            self._rescan_again = False
            self.scan()

    def shutdown(self):
        if self.scanner and self.scanner.isRunning():
            self.scanner.stop()
            self.scanner.wait(3000)

    def save_snapshot(self):
        """At quit: refresh the startup snapshot if the library changed this session."""
        try:
            if getattr(self, "_snap_key", None) == _snapshot_key(self.con):
                return
            write_snapshot(*load_tracks_keyed(self.con))
        except Exception:
            pass

    def set_rating(self, ids: list[int], rating: int):
        for tid in ids:
            if tid in self.tracks:
                self.tracks[tid]["rating"] = rating
                self.con.execute("UPDATE tracks SET rating=? WHERE id=?", (rating, tid))
        self.con.commit()
        for tid in ids:
            self.trackUpdated.emit(tid)

    def record_play(self, tid: int):
        t = self.tracks.get(tid)
        if not t:
            return
        t["playcount"] += 1
        t["lastplayed"] = time.time()
        self.con.execute("UPDATE tracks SET playcount=?, lastplayed=? WHERE id=?",
                         (t["playcount"], t["lastplayed"], tid))
        # The play history behind the Stats page stores names too, so it survives retagging.
        self.con.execute("INSERT INTO plays VALUES (?,?,?,?,?,?,?,?,?)",
                         (t["lastplayed"], tid, t["length"] or 0, t["title"], t["artist"], t["album"],
                          t["albumartist"], t["genre"], t["path"]))
        self.con.commit()
        self.trackUpdated.emit(tid)

    def clear_stats(self, history: bool = True, counts: bool = True):
        """Reset stats. history: the play history; counts: play/skip counts and last played."""
        if history:
            self.con.execute("DELETE FROM plays")
        if counts:
            self.con.execute("UPDATE tracks SET playcount=0, skipcount=0, lastplayed=0")
            for t in self.tracks.values():
                t["playcount"] = t["skipcount"] = 0
                t["lastplayed"] = 0
        self.con.commit()
        if counts:
            self.changed.emit()

    def plays_since(self, since: float) -> list[dict]:
        cur = self.con.execute("SELECT * FROM plays WHERE played_at >= ? ORDER BY played_at", (since,))
        return [dict(r) for r in cur.fetchall()]

    def first_play_logged(self) -> float | None:
        r = self.con.execute("SELECT MIN(played_at) FROM plays").fetchone()
        return r[0] if r and r[0] else None

    def record_skip(self, tid: int):
        t = self.tracks.get(tid)
        if not t:
            return
        t["skipcount"] += 1
        self.con.execute("UPDATE tracks SET skipcount=? WHERE id=?", (t["skipcount"], tid))
        self.con.commit()

    def refresh_files(self, ids: list[int]):
        """Re-read tags for these tracks (after editing)."""
        for tid in ids:
            t = self.tracks.get(tid)
            if not t:
                continue
            new = tagio.read_track(t["path"])
            if new:
                upsert_track(self.con, new)
        self.con.commit()
        self.reload()

    def remove_tracks(self, ids: list[int]):
        for tid in ids:
            t = self.tracks.get(tid)
            if t:  # a single added song: forget it too
                self.con.execute("DELETE FROM files WHERE path=?", (t["path"],))
            self.con.execute("DELETE FROM playlist_tracks WHERE track_id=?", (tid,))
            self.con.execute("DELETE FROM tracks WHERE id=?", (tid,))
        self.con.commit()
        self.reload()
        self.playlistsChanged.emit()

    def playlists(self) -> list[tuple[int, str]]:
        return [(r[0], r[1]) for r in
                self.con.execute("SELECT id, name FROM playlists ORDER BY name COLLATE NOCASE")]

    def create_playlist(self, name: str) -> int:
        cur = self.con.execute("INSERT INTO playlists (name) VALUES (?)", (name,))
        self.con.commit()
        self.playlistsChanged.emit()
        return cur.lastrowid

    def rename_playlist(self, pid: int, name: str):
        self.con.execute("UPDATE playlists SET name=? WHERE id=?", (name, pid))
        self.con.commit()
        self.playlistsChanged.emit()

    def delete_playlists(self, pids: list[int]):
        """Delete several playlists with one change signal."""
        pids = [int(p) for p in pids]
        if not pids:
            return
        for pid in pids:
            self.con.execute("DELETE FROM playlist_tracks WHERE playlist_id=?", (pid,))
            self.con.execute("DELETE FROM playlists WHERE id=?", (pid,))
        self.con.commit()
        self.playlistsChanged.emit()

    def playlist_track_ids(self, pid: int) -> list[int]:
        return [r[0] for r in self.con.execute(
            "SELECT track_id FROM playlist_tracks WHERE playlist_id=? ORDER BY pos", (pid,))]

    def set_playlist_tracks(self, pid: int, ids: list[int]):
        self.con.execute("DELETE FROM playlist_tracks WHERE playlist_id=?", (pid,))
        self.con.executemany("INSERT INTO playlist_tracks VALUES (?, ?, ?)",
                             [(pid, i, tid) for i, tid in enumerate(ids)])
        self.con.commit()
        self.playlistsChanged.emit()

    def add_to_playlist(self, pid: int, ids: list[int]):
        self.set_playlist_tracks(pid, self.playlist_track_ids(pid) + list(ids))

    def import_m3u(self, file: str) -> int:
        from musicwell.system import path_key
        base = os.path.dirname(file)
        by_path = {path_key(t["path"]): tid for tid, t in self.tracks.items()}
        ids = []
        with open(file, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("file://"):
                    from urllib.parse import urlsplit
                    from urllib.request import url2pathname
                    line = url2pathname(urlsplit(line).path)  # file:///C:/Music/... on Windows
                if os.sep == "\\":
                    line = line.replace("/", "\\")  # playlists made on Linux or a phone
                p = path_key(os.path.join(base, line))
                if p in by_path:
                    ids.append(by_path[p])
        name = os.path.splitext(os.path.basename(file))[0]
        pid = self.create_playlist(name)
        self.set_playlist_tracks(pid, ids)
        return pid

    def export_m3u(self, pid: int, file: str):
        with open(file, "w", encoding="utf-8") as fh:
            fh.write("#EXTM3U\n")
            for tid in self.playlist_track_ids(pid):
                t = self.get(tid)
                if t:
                    fh.write(f"#EXTINF:{int(t['length'])},{t['artist']} - {t['title']}\n{t['path']}\n")
