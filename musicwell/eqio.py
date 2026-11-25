"""Import and export EQ presets: Musicwell, EqualizerAPO / AutoEq (graphic and parametric), Winamp .eqf and MusicBee .sde. Other band layouts are resampled to ours."""
from __future__ import annotations

import json
import math
import os
import re

from musicwell.eq import BANDS, MAX_DB

FORMAT = "musicwell-eq"
OLD_FORMATS = ("listenwell-eq", "tunewell-eq")  # presets from before the rename
WINAMP_BANDS = [60, 170, 310, 600, 1000, 3000, 6000, 12000, 14000, 16000]


class EqImportError(ValueError):
    pass


def _clamp(gains):
    return [round(max(-MAX_DB, min(MAX_DB, float(g))), 2) for g in gains]


def _interp_log(points: list[tuple[float, float]], freqs) -> list[float]:
    """dB at each frequency, interpolating (Hz, dB) points in log-frequency."""
    pts = sorted((math.log10(max(f, 1.0)), g) for f, g in points if f > 0)
    if not pts:
        return [0.0] * len(freqs)
    out = []
    for f in freqs:
        x = math.log10(f)
        if x <= pts[0][0]:
            out.append(pts[0][1])
            continue
        if x >= pts[-1][0]:
            out.append(pts[-1][1])
            continue
        for (x0, g0), (x1, g1) in zip(pts, pts[1:]):
            if x0 <= x <= x1:
                t = 0 if x1 == x0 else (x - x0) / (x1 - x0)
                out.append(g0 + (g1 - g0) * t)
                break
    return out


def _band_average(points, f):
    """Average over a third of an octave either side, so a narrow notch doesn't decide a whole band."""
    span = [f * 2 ** (k / 12) for k in range(-4, 5)]
    vals = _interp_log(points, span)
    return sum(vals) / len(vals)


def _biquad_db(kind: str, fc: float, gain: float, q: float, f: float, fs: float = 48000.0) -> float:
    """Magnitude (dB) at f of one RBJ-cookbook filter."""
    if fc <= 0 or fc >= fs / 2:
        return 0.0
    A = 10 ** (gain / 40)
    w0 = 2 * math.pi * fc / fs
    cw, sw = math.cos(w0), math.sin(w0)
    q = q if q and q > 0 else 0.707
    alpha = sw / (2 * q)
    if kind in ("PK", "PEQ", "PEAKING", "BELL"):
        b = [1 + alpha * A, -2 * cw, 1 - alpha * A]
        a = [1 + alpha / A, -2 * cw, 1 - alpha / A]
    elif kind in ("LS", "LSC", "LOWSHELF", "LOW_SHELF"):
        sq = 2 * math.sqrt(A) * alpha
        b = [A * ((A + 1) - (A - 1) * cw + sq), 2 * A * ((A - 1) - (A + 1) * cw), A * ((A + 1) - (A - 1) * cw - sq)]
        a = [(A + 1) + (A - 1) * cw + sq, -2 * ((A - 1) + (A + 1) * cw), (A + 1) + (A - 1) * cw - sq]
    elif kind in ("HS", "HSC", "HIGHSHELF", "HIGH_SHELF"):
        sq = 2 * math.sqrt(A) * alpha
        b = [A * ((A + 1) + (A - 1) * cw + sq), -2 * A * ((A - 1) + (A + 1) * cw), A * ((A + 1) + (A - 1) * cw - sq)]
        a = [(A + 1) - (A - 1) * cw + sq, 2 * ((A - 1) - (A + 1) * cw), (A + 1) - (A - 1) * cw - sq]
    else:
        return 0.0
    w = 2 * math.pi * f / fs
    z1, z2 = complex(math.cos(-w), math.sin(-w)), complex(math.cos(-2 * w), math.sin(-2 * w))
    h = (b[0] + b[1] * z1 + b[2] * z2) / (a[0] + a[1] * z1 + a[2] * z2)
    return 20 * math.log10(max(abs(h), 1e-9))


_FILTER = re.compile(r"Filter\s*\d*\s*:\s*ON\s+([A-Z_]+)\s+Fc\s+([\d.]+)\s*Hz"
                     r"(?:\s+Gain\s+([-+\d.]+)\s*dB)?(?:\s+Q\s+([\d.]+))?", re.I)
_PREAMP = re.compile(r"Preamp\s*:\s*([-+\d.]+)\s*dB", re.I)


def _parse_text(text: str, BANDS=BANDS) -> tuple[list[float], float]:
    pre_m = _PREAMP.search(text)
    preamp = float(pre_m.group(1)) if pre_m else 0.0
    g = re.search(r"GraphicEQ\s*:\s*(.+)", text, re.I)
    if g:
        pts = []
        for part in g.group(1).split(";"):
            nums = part.split()
            if len(nums) >= 2:
                try:
                    pts.append((float(nums[0]), float(nums[1])))
                except ValueError:
                    pass
        if len(pts) < 2:
            raise EqImportError("The GraphicEQ line has no frequency / gain pairs.")
        return [_band_average(pts, f) for f in BANDS], preamp
    filters = _FILTER.findall(text)
    if filters:
        gains = []
        for f in BANDS:
            total = 0.0
            for kind, fc, gain, q in filters:
                total += _biquad_db(kind.upper(), float(fc), float(gain or 0), float(q or 0.707), f)
            gains.append(total)
        return gains, preamp
    raise EqImportError("No equalizer settings found in that text file "
                        "(expected GraphicEQ or Filter lines, as EqualizerAPO and AutoEq write them).")


def _parse_eqf(data: bytes, BANDS=BANDS) -> list[tuple[str, list[float], float]]:
    if not data.startswith(b"Winamp EQ library file"):
        raise EqImportError("Not a Winamp equalizer file.")
    body = data[31:]  # header: "Winamp EQ library file v1.1" + \x1a!--
    out = []
    while len(body) >= 257 + 11:
        name = body[:257].split(b"\0", 1)[0].decode("latin-1").strip() or "Winamp preset"
        vals = body[257:268]
        body = body[268:]
        # 0 = +12 dB, 63 = -12 dB, 31.5 = flat
        db = [(31.5 - v) * 12 / 31.5 for v in vals]
        db = [0.0 if abs(d) < 0.3 else d for d in db]  # 31 and 32 both mean flat
        gains = _interp_log(list(zip(WINAMP_BANDS, db[:10])), BANDS)
        out.append((name, gains, db[10]))
    if not out:
        raise EqImportError("That Winamp file has no presets in it.")
    return out


# MusicBee band centres for each EQ size
SDE_BANDS = {
    10: [32, 64, 125, 250, 500, 1000, 2000, 4000, 8000, 16000],
    15: [25, 40, 63, 100, 160, 250, 400, 630, 1000, 1600, 2500, 4000, 6300, 10000, 16000],
    30: [25, 31.5, 40, 50, 63, 80, 100, 125, 160, 200, 250, 315, 400, 500, 630, 800, 1000, 1250, 1600, 2000,
         2500, 3150, 4000, 5000, 6300, 8000, 10000, 12500, 16000, 20000],
}


def _parse_sde(text: str, BANDS=BANDS) -> tuple[list[float], float]:
    """MusicBee preset ([Equalizer] section). Left and right are averaged."""
    vals: dict[str, float] = {}
    for line in text.splitlines():
        k, sep, v = line.partition("=")
        if not sep:
            continue
        try:
            vals[k.strip().lower()] = float(v.strip().replace(",", "."))
        except ValueError:
            continue
    nums = sorted({int(m.group(1)) for k in vals for m in [re.fullmatch(r"(?:left|right)(\d+)", k)] if m})
    if not nums:
        raise EqImportError("No equaliser bands found in that MusicBee file.")
    n = int(vals.get("bands") or len(nums))
    freqs = SDE_BANDS.get(n)
    if freqs is None:  # unusual size: spread from 25 Hz to 16 kHz
        freqs = [25 * (16000 / 25) ** (i / max(1, n - 1)) for i in range(n)]

    def both(name):
        side = [vals[x] for x in (f"left{name}", f"right{name}") if x in vals]
        return sum(side) / len(side) if side else 0.0
    pts = [(freqs[i - 1], both(i)) for i in range(1, n + 1) if i - 1 < len(freqs)]
    pre = both("preamp")
    if len(pts) == len(BANDS) and all(abs(f / b - 1) < 0.06 for (f, _), b in zip(pts, BANDS)):  # 32 Hz ≈ 31 Hz
        return [g for _, g in pts], pre
    return _interp_log(pts, BANDS), pre


def read_file(path: str, BANDS=BANDS) -> list[tuple[str, list[float], float]]:
    """[(name, gains, preamp)] from any supported file. Raises EqImportError."""
    try:
        with open(path, "rb") as fh:
            data = fh.read(4 * 1024 * 1024)
    except OSError as e:
        raise EqImportError(f"Couldn't read the file: {e.strerror}") from e
    stem = os.path.splitext(os.path.basename(path))[0]
    if data.startswith(b"Winamp EQ library file"):
        presets = _parse_eqf(data, BANDS)
        if len(presets) == 1 and presets[0][0] in ("Winamp preset", "Entry1", ""):
            presets = [(stem, presets[0][1], presets[0][2])]
    else:
        text = (data.decode("utf-16", "replace") if data[:2] in (b"\xff\xfe", b"\xfe\xff")
                else data.decode("utf-8", "replace")).lstrip("﻿")
        if text.lstrip().lower().startswith("[equalizer]") or path.lower().endswith(".sde"):
            gains, pre = _parse_sde(text, BANDS)
            presets = [(stem, gains, pre)]
        elif text.lstrip().startswith("{"):
            try:
                d = json.loads(text)
            except ValueError as e:
                raise EqImportError("That file isn't valid JSON.") from e
            if d.get("format") not in (FORMAT, *OLD_FORMATS):
                raise EqImportError("That JSON file isn't a Musicwell equalizer file.")
            presets = []
            for name, p in (d.get("presets") or {}).items():
                g = p.get("gains", [])
                from musicwell.eq import BANDS as TEN
                bands = d.get("bands") or (TEN if len(g) == 10 else BANDS)
                if list(bands) != list(BANDS) and len(g) == len(bands):
                    g = _interp_log(list(zip(bands, g)), BANDS)
                if len(g) == len(BANDS):
                    presets.append((str(name), [float(x) for x in g], float(p.get("preamp", 0.0))))
            if not presets:
                raise EqImportError("That Musicwell file has no presets in it.")
        else:
            gains, pre = _parse_text(text, BANDS)
            presets = [(stem, gains, pre)]
    out = []
    for name, gains, pre in presets:
        g = _clamp(gains)
        out.append((name, g, round(max(-MAX_DB, min(MAX_DB, pre)), 2)))
    return out


def write_musicwell(path: str, presets: dict, n: int = 10):
    """presets: {name: {"gains": [...], "preamp": x}}"""
    from musicwell.eq import bands_for, convert
    data = {"format": FORMAT, "version": 1, "bands": bands_for(n),
            "presets": {name: {"gains": [round(float(g), 2) for g in convert(p["gains"], n)],
                            "preamp": round(float(p.get("preamp", 0.0)), 2)} for name, p in presets.items()}}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def write_graphiceq(path: str, gains, preamp: float):
    """EqualizerAPO GraphicEQ format, sampled from our response curve."""
    from musicwell.eq import target_db
    freqs = [round(20 * (1000 ** (i / 63)), 1) for i in range(64)]  # 20 Hz - 20 kHz
    db = target_db(freqs, gains, 0.0)
    pairs = "; ".join(f"{f:g} {float(d):.1f}" for f, d in zip(freqs, db))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(f"Preamp: {preamp:.1f} dB\nGraphicEQ: {pairs}\n")
