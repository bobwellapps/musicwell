"""Reads tags in helper processes so big collections load faster. Started by library.Scanner."""
from __future__ import annotations

import json
import os
import signal
import sys


def read_many(paths: list[str]) -> list[list]:
    """[path, tags or None, error] for each path."""
    from musicwell import tags
    out = []
    for p in paths:
        try:
            out.append([p, tags.read_track(p), ""])
        except Exception as e:
            out.append([p, None, f"{type(e).__name__}: {e}"])
    return out


def main():
    try:
        os.nice(10)  # lower priority than playback and the UI
    except (OSError, AttributeError):
        pass
    try:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
    except (ValueError, OSError):
        pass
    inp, out = sys.stdin.buffer, sys.stdout.buffer
    for line in inp:
        if not line.strip():
            continue
        try:
            paths = json.loads(line)
            result = read_many(paths)
        except Exception as e:
            result = [[None, None, f"{type(e).__name__}: {e}"]]
        out.write(json.dumps(result, ensure_ascii=True, default=str).encode("ascii") + b"\n")
        out.flush()


if __name__ == "__main__":
    main()
