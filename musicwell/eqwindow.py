"""The equaliser window: response curve, preamp, band sliders and presets."""
from __future__ import annotations

import json
import os
import re

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout,
                               QInputDialog, QLabel, QMenu, QMessageBox, QPushButton, QSlider,
                               QVBoxLayout, QWidget)

from musicwell.eq import BAND_COUNTS, BANDS, MAX_DB, PRESETS, bands_for, convert, labels_for

STEP = 10  # slider units per dB
CUSTOM = "Custom"

try:
    import numpy as np
    from musicwell.eq import Equalizer
    _CURVE_EQ = Equalizer(48000)
except Exception:  # no numpy: the curve is drawn from the sliders instead
    np = None
    _CURVE_EQ = None


class ResponseCurve(QWidget):
    """Draws the EQ's actual frequency response."""

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.gains = [0.0] * len(BANDS)
        self.preamp = 0.0
        self.enabled = True
        self.setMinimumHeight(150)

    def set_values(self, gains, preamp, enabled):
        self.gains, self.preamp, self.enabled = list(gains), preamp, enabled
        self.update()

    def _x(self, f, left, width):
        import math
        lo, hi = math.log10(20), math.log10(20000)
        return left + (math.log10(f) - lo) / (hi - lo) * width

    def _curve(self, n):
        import math
        freqs = [10 ** (math.log10(20) + i / (n - 1) * 3) for i in range(n)]
        if _CURVE_EQ is not None:
            _CURVE_EQ.set(self.gains, self.preamp)
            dbs = list(_CURVE_EQ.response_db(np.array(freqs)))
        else:
            logs = [math.log10(b) for b in bands_for(len(self.gains))]
            dbs = []
            for f in freqs:
                lf = math.log10(f)
                if lf <= logs[0]:
                    d = self.gains[0]
                elif lf >= logs[-1]:
                    d = self.gains[-1]
                else:
                    k = max(i for i in range(len(logs)) if logs[i] <= lf)
                    t = (lf - logs[k]) / (logs[k + 1] - logs[k])
                    d = self.gains[k] * (1 - t) + self.gains[k + 1] * t
                dbs.append(d + self.preamp)
        return freqs, dbs

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        th = self.theme
        w, h = self.width(), self.height()
        left, right, top, bottom = 38, 10, 8, 20
        pw, ph = w - left - right, h - top - bottom
        rng = MAX_DB + 3  # room for the preamp

        def y(db):
            db = max(-rng, min(rng, db))
            return top + (1 - (db + rng) / (2 * rng)) * ph

        small = QFont(self.font())
        small.setPointSizeF(7.5)
        p.setFont(small)
        for db in (-12, -6, 0, 6, 12):
            yy = y(db)
            pen = QPen(th.color("border" if db else "faint"))
            pen.setWidthF(1)
            if db:
                pen.setStyle(Qt.DotLine)
            p.setPen(pen)
            p.drawLine(QPointF(left, yy), QPointF(w - right, yy))
            p.setPen(th.color("faint"))
            p.drawText(QRectF(0, yy - 7, left - 6, 14), Qt.AlignRight | Qt.AlignVCenter, f"{db:+d}" if db else "0")
        n = len(self.gains)
        for i, (f, lab) in enumerate(zip(bands_for(n), labels_for(n))):
            if n == 15 and pw < 520 and i % 2:
                continue  # too narrow for every label
            xx = self._x(f, left, pw)
            p.setPen(th.color("faint"))
            p.drawText(QRectF(xx - 20, h - bottom + 4, 40, 14), Qt.AlignCenter, lab)

        freqs, dbs = self._curve(160)
        path = QPainterPath()
        for i, (f, d) in enumerate(zip(freqs, dbs)):
            pt = QPointF(self._x(f, left, pw), y(d))
            path.moveTo(pt) if i == 0 else path.lineTo(pt)
        accent = th.color("accent") if self.enabled else th.color("faint")
        fill = QPainterPath(path)
        fill.lineTo(QPointF(left + pw, y(0)))
        fill.lineTo(QPointF(left, y(0)))
        fill.closeSubpath()
        g = QLinearGradient(0, top, 0, top + ph)
        c1, c2 = QColor(accent), QColor(accent)
        c1.setAlpha(70 if self.enabled else 30)
        c2.setAlpha(10)
        g.setColorAt(0, c1)
        g.setColorAt(0.5, c2)
        g.setColorAt(1, c1)
        p.fillPath(fill, g)
        pen = QPen(accent)
        pen.setWidthF(2.2)
        p.setPen(pen)
        p.drawPath(path)


class BandSlider(QSlider):
    """Vertical slider filled from 0 dB. Double-click resets it."""
    MARGIN = 10
    KNOB = 7

    def __init__(self, theme, parent=None):
        super().__init__(Qt.Vertical, parent)
        self.theme = theme
        self.setRange(int(-MAX_DB * STEP), int(MAX_DB * STEP))
        self.setSingleStep(5)
        self.setPageStep(10)
        self.setMinimumSize(30, 180)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Drag, scroll or use the arrow keys. Double-click to reset.")
        self._hover = False

    def _y(self, v: float) -> float:
        span = self.height() - 2 * self.MARGIN
        return self.MARGIN + (self.maximum() - v) / (self.maximum() - self.minimum()) * span

    def _value_at(self, y: float) -> int:
        span = max(1, self.height() - 2 * self.MARGIN)
        frac = min(1.0, max(0.0, (y - self.MARGIN) / span))
        v = self.maximum() - frac * (self.maximum() - self.minimum())
        return int(round(v / 5) * 5)  # 0.5 dB steps when dragging

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        th = self.theme
        x = self.width() / 2
        top, bottom = self._y(self.maximum()), self._y(self.minimum())
        p.setPen(Qt.NoPen)
        p.setBrush(th.color("hover"))
        p.drawRoundedRect(QRectF(x - 2, top, 4, bottom - top), 2, 2)
        y0, yv = self._y(0), self._y(self.value())
        pen = QPen(th.color("faint"))
        pen.setWidthF(1.5)
        p.setPen(pen)
        p.drawLine(QPointF(x - 7, y0), QPointF(x + 7, y0))
        accent = th.color("accent") if self.isEnabled() else th.color("faint")
        p.setPen(Qt.NoPen)
        p.setBrush(accent)
        p.drawRoundedRect(QRectF(x - 2, min(y0, yv), 4, abs(yv - y0)), 2, 2)
        knob = accent if (self._hover or self.isSliderDown()) else th.color("text")
        if not self.isEnabled():
            knob = th.color("faint")
        p.setBrush(knob)
        p.drawEllipse(QPointF(x, yv), self.KNOB, self.KNOB)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.setSliderDown(True)
            self.setValue(self._value_at(e.position().y()))
            e.accept()

    def mouseMoveEvent(self, e):
        if self.isSliderDown():
            self.setValue(self._value_at(e.position().y()))
            e.accept()

    def mouseReleaseEvent(self, e):
        if self.isSliderDown():
            self.setSliderDown(False)
            self.update()

    def mouseDoubleClickEvent(self, e):
        self.setValue(0)

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()


def _fmt_db(v: float) -> str:
    return "0" if abs(v) < 0.05 else f"{v:+.1f}"


class EqualizerWindow(QDialog):
    changed = Signal(bool, list, float, str)  # enabled, gains, preamp, preset name

    def __init__(self, theme, settings, available: bool, why_not: str = "", parent=None):
        super().__init__(parent)
        self.theme = theme
        self.settings = settings
        self.setWindowTitle("Equalizer")
        self.setMinimumWidth(780)
        self._loading = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 16)
        lay.setSpacing(10)

        top = QHBoxLayout()
        title = QLabel("Equalizer")
        title.setObjectName("PageTitle")
        top.addWidget(title)
        self.on = QCheckBox("On")
        self.on.toggled.connect(self._emit)
        top.addSpacing(8)
        top.addWidget(self.on)
        top.addSpacing(14)
        top.addWidget(QLabel("Bands"))
        self.band_count = QComboBox()
        for n in BAND_COUNTS:
            self.band_count.addItem(f"{n}", n)
        self.band_count.setToolTip("10 bands, an octave apart (31 Hz … 16 kHz), or 15 bands, ⅔ of an octave apart "
                                   "(25 Hz … 16 kHz) for finer control. Switching keeps the sound the same.")
        self.band_count.activated.connect(lambda _: self.set_band_count(self.band_count.currentData()))
        top.addWidget(self.band_count)
        top.addStretch()
        top.addWidget(QLabel("Preset"))
        self.preset = QComboBox()
        self.preset.setMinimumWidth(170)
        self.preset.activated.connect(lambda _: self._pick_preset(self.preset.currentText()))
        top.addWidget(self.preset)
        self.save_btn = QPushButton("Save…")
        self.save_btn.clicked.connect(self._save_preset)
        self.del_btn = QPushButton("Delete")
        self.del_btn.clicked.connect(self._delete_preset)
        reset = QPushButton("Reset")
        reset.setToolTip("Set every band and the preamp to 0 dB")
        reset.clicked.connect(lambda: self._pick_preset("Flat"))
        self.io_btn = QPushButton("Import/Export")
        self.io_btn.setToolTip("Bring in presets from a file (Musicwell, EqualizerAPO, AutoEq, Winamp) "
                               "or save them to one")
        self.io_menu = QMenu(self.io_btn)
        self.io_menu.aboutToShow.connect(self._fill_io_menu)
        self.io_btn.setMenu(self.io_menu)
        for b in (self.save_btn, self.del_btn, reset, self.io_btn):
            top.addWidget(b)
        lay.addLayout(top)

        self.curve = ResponseCurve(theme)
        lay.addWidget(self.curve)

        sliders = QHBoxLayout()
        sliders.setSpacing(4)
        self.preamp, self.preamp_val = self._column(sliders, "Preamp")
        line = QFrame()
        line.setFrameShape(QFrame.VLine)
        line.setStyleSheet(f"color: {theme.p['border']};")
        sliders.addSpacing(6)
        sliders.addWidget(line)
        sliders.addSpacing(6)
        self.band_box = QHBoxLayout()
        self.band_box.setSpacing(4)
        sliders.addLayout(self.band_box, 10)
        self._sliders = sliders
        self.bands, self.band_vals = [], []
        try:
            self.n = int(settings.value("eq_bands", 10))
        except (TypeError, ValueError):
            self.n = 10
        if self.n not in BAND_COUNTS:
            self.n = 10
        self._make_bands(self.n)
        lay.addLayout(sliders)

        self.hint = QLabel("")
        self.hint.setObjectName("EmptyText")
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)

        if not available:
            for w in [self.on, self.preset, self.save_btn, self.del_btn, reset, self.io_btn, self.preamp,
                      self.band_count] + self.bands:
                w.setEnabled(False)
            self.hint.setText(f"The equalizer isn't available on this system ({why_not}). "
                              "Musicwell needs Qt 6.8 or newer and numpy for it.")
            self.available = False
        else:
            self.available = True
        self._restore()

    def _make_bands(self, n: int):
        while self.band_box.count():
            item = self.band_box.takeAt(0)
            lay = item.layout()
            if lay is not None:
                while lay.count():
                    w = lay.takeAt(0).widget()
                    if w is not None:
                        w.hide()  # hide now; deleteLater waits for the event loop
                        w.setParent(None)
                        w.deleteLater()
                lay.deleteLater()
        self.bands, self.band_vals = [], []
        for lab in labels_for(n):
            s, v = self._column(self.band_box, lab, narrow=n > 10)
            self.bands.append(s)
            self.band_vals.append(v)
        self.n = n
        if hasattr(self, "_sliders"):
            self._sliders.setStretch(self._sliders.indexOf(self.band_box), n)
        self.setMinimumWidth(780 if n <= 10 else 960)
        if hasattr(self, "band_count"):
            self.band_count.setCurrentIndex(max(0, self.band_count.findData(n)))

    def set_band_count(self, n: int):
        """Switch between 10 and 15 bands, keeping the curve."""
        if n == self.n or n not in BAND_COUNTS:
            return
        gains, pre = convert(self.gains(), n), self.preamp_db()
        enabled = self.bands[0].isEnabled() if self.bands else True
        self._make_bands(n)
        for sl in self.bands:
            sl.setEnabled(enabled)
        self.settings.setValue("eq_bands", n)
        self._set_values(gains, pre)
        self._fill_presets(self._matching_preset())
        self._emit()

    def _column(self, parent_layout, label, narrow: bool = False):
        col = QVBoxLayout()
        col.setSpacing(4)
        val = QLabel("0")
        val.setAlignment(Qt.AlignCenter)
        val.setObjectName("NowMeta")
        val.setMinimumWidth(36 if narrow else 44)
        s = BandSlider(self.theme)
        if narrow:
            s.setMinimumSize(26, 180)
        s.valueChanged.connect(lambda v, lab=val: (lab.setText(_fmt_db(v / STEP)), self._on_slider()))
        name = QLabel(label)
        name.setAlignment(Qt.AlignCenter)
        name.setObjectName("NowSectionLabel")
        col.addWidget(val)
        col.addWidget(s, 1, Qt.AlignHCenter)
        col.addWidget(name)
        parent_layout.addLayout(col, 1)
        return s, val

    def gains(self) -> list[float]:
        return [s.value() / STEP for s in self.bands]

    def preamp_db(self) -> float:
        return self.preamp.value() / STEP

    def _set_values(self, gains, preamp):
        self._loading = True
        for s, g in zip(self.bands, gains):
            s.setValue(int(round(g * STEP)))
        self.preamp.setValue(int(round(preamp * STEP)))
        self._loading = False

    def _custom_presets(self) -> dict:
        try:
            return json.loads(self.settings.value("eq_custom_presets", "{}"))
        except (TypeError, ValueError):
            return {}

    def _all_presets(self) -> dict:
        """Every preset, converted to the current band count."""
        out = {k: {"gains": convert(v, self.n), "preamp": 0.0} for k, v in PRESETS.items()}
        for k, p in self._custom_presets().items():
            try:
                out[k] = {"gains": convert(p.get("gains", []), self.n), "preamp": float(p.get("preamp", 0.0))}
            except (TypeError, ValueError, AttributeError):
                continue
        return out

    def _fill_presets(self, current: str):
        self.preset.blockSignals(True)
        self.preset.clear()
        self.preset.addItems(list(PRESETS))
        custom = self._custom_presets()
        if custom:
            self.preset.insertSeparator(self.preset.count())
            self.preset.addItems(sorted(custom, key=str.lower))
        if current not in self._all_presets():
            self.preset.insertSeparator(self.preset.count())
            self.preset.addItem(CUSTOM)
            current = CUSTOM
        self.preset.setCurrentText(current)
        self.preset.blockSignals(False)
        self.del_btn.setEnabled(self.available and current in custom)

    def _pick_preset(self, name: str):
        p = self._all_presets().get(name)
        if p is None:
            return
        self._set_values(p["gains"], p.get("preamp", 0.0))
        self._fill_presets(name)
        if not self.on.isChecked() and name != "Flat":
            self.on.setChecked(True)  # picking a preset turns the EQ on
        self._emit()

    def _matching_preset(self) -> str:
        g, pre = self.gains(), self.preamp_db()
        for name, p in self._all_presets().items():
            if all(abs(a - b) < 0.05 for a, b in zip(g, p["gains"])) and abs(pre - p.get("preamp", 0)) < 0.05:
                return name
        return CUSTOM

    def _save_preset(self):
        current = self.preset.currentText()
        suggestion = current if current in self._custom_presets() else ""
        name, ok = QInputDialog.getText(self, "Save preset", "Preset name:", text=suggestion)
        name = name.strip()
        if not ok or not name:
            return
        if name in PRESETS or name == CUSTOM:
            QMessageBox.information(self, "Save preset", f"“{name}” is a built-in name. Pick another one.")
            return
        custom = self._custom_presets()
        custom[name] = {"gains": self.gains(), "preamp": self.preamp_db()}
        self.settings.setValue("eq_custom_presets", json.dumps(custom))
        self._fill_presets(name)
        self._emit()

    def _delete_preset(self):
        name = self.preset.currentText()
        custom = self._custom_presets()
        if name in custom and QMessageBox.question(self, "Delete preset", f"Delete “{name}”?") == QMessageBox.Yes:
            del custom[name]
            self.settings.setValue("eq_custom_presets", json.dumps(custom))
            self._fill_presets(self._matching_preset())
            self._emit()

    def _fill_io_menu(self):
        m = self.io_menu
        m.clear()
        m.addAction("Import presets…", self._import)
        m.addSeparator()
        current = self.preset.currentText()
        m.addAction(f"Export “{current}”…", self._export_current)
        a = m.addAction("Export all my presets…", self._export_all)
        a.setEnabled(bool(self._custom_presets()))
        m.addAction("Export for EqualizerAPO / EasyEffects (GraphicEQ)…", self._export_graphiceq)

    def _start_dir(self) -> str:
        return self.settings.value("eq_io_dir", os.path.expanduser("~"))

    def _remember_dir(self, path: str):
        self.settings.setValue("eq_io_dir", os.path.dirname(path))

    def _import(self):
        from musicwell import eqio
        files, _ = QFileDialog.getOpenFileNames(
            self, "Import equalizer presets", self._start_dir(),
            "Equalizer presets (*.musicwell-eq *.listenwell-eq *.tunewell-eq *.json *.txt *.eqf *.q1 *.EQF *.sde *.SDE);;All files (*)")
        if not files:
            return
        self._remember_dir(files[0])
        custom = self._custom_presets()
        added, problems = [], []
        for f in files:
            try:
                presets = eqio.read_file(f, bands_for(self.n))
            except eqio.EqImportError as e:
                problems.append(f"{os.path.basename(f)}: {e}")
                continue
            for name, gains, pre in presets:
                base, n = name.strip() or "Imported", 2
                name = base
                while name in custom or name in PRESETS or name == CUSTOM:
                    name = f"{base} ({n})"
                    n += 1
                custom[name] = {"gains": gains, "preamp": pre}
                added.append(name)
        if added:
            self.settings.setValue("eq_custom_presets", json.dumps(custom))
            self._pick_preset(added[0])
        text = ""
        if added:
            text = (f"Added {len(added)} preset{'s' if len(added) != 1 else ''}: " + ", ".join(added[:8])
                    + ("…" if len(added) > 8 else "") + ".")
            if len(added) > 1:
                text += "\nThey're in the Preset list; the first one is playing now."
        if problems:
            text += ("\n\n" if text else "") + "Couldn't import:\n" + "\n".join(problems)
        QMessageBox.information(self, "Import presets", text)

    def _ask_save(self, title: str, name: str, ext: str, filt: str) -> str:
        safe = re.sub(r'[\\/:*?"<>|]+', "_", name).strip() or "equalizer"
        f, _ = QFileDialog.getSaveFileName(self, title, os.path.join(self._start_dir(), safe + ext), filt)
        if f and not os.path.splitext(f)[1]:
            f += ext
        if f:
            self._remember_dir(f)
        return f

    def _export_current(self):
        from musicwell import eqio
        name = self.preset.currentText()
        if name == CUSTOM:
            name = "My equalizer"
        f = self._ask_save("Export preset", name, ".musicwell-eq", "Musicwell equalizer (*.musicwell-eq)")
        if f:
            self._write(lambda: eqio.write_musicwell(f, {name: {"gains": self.gains(), "preamp": self.preamp_db()}},
                                                      self.n), f)

    def _export_all(self):
        from musicwell import eqio
        f = self._ask_save("Export my presets", "Musicwell presets", ".musicwell-eq", "Musicwell equalizer (*.musicwell-eq)")
        if f:
            self._write(lambda: eqio.write_musicwell(f, self._custom_presets(), self.n), f)

    def _export_graphiceq(self):
        from musicwell import eqio
        name = self.preset.currentText()
        f = self._ask_save("Export for EqualizerAPO", name if name != CUSTOM else "My equalizer", ".txt",
                           "GraphicEQ text (*.txt)")
        if f:
            self._write(lambda: eqio.write_graphiceq(f, self.gains(), self.preamp_db()), f)

    def _write(self, fn, path: str):
        try:
            fn()
            self.hint.setText(f"Saved {os.path.basename(path)}")
        except OSError as e:
            QMessageBox.warning(self, "Export", f"Couldn't save the file: {e.strerror}")

    def _on_slider(self):
        if self._loading:
            return
        self._fill_presets(self._matching_preset())
        self._emit()

    def _emit(self, *_):
        gains, pre, on = self.gains(), self.preamp_db(), self.on.isChecked()
        self.curve.set_values(gains, pre, on)
        peak = max(gains) + pre
        if self.available:
            if on and peak > 1.0:
                self.hint.setText(f"Loud parts may be softened: the boost peaks at {peak:+.1f} dB. "
                                  f"Lower the preamp to {pre - peak:+.1f} dB for a clean sound.")
            else:
                self.hint.setText("Double-click a slider to reset it. Changes are heard within a moment.")
        if not self._loading:
            self.changed.emit(on, gains, pre, self.preset.currentText())

    def _restore(self):
        s = self.settings
        try:
            gains = [float(g) for g in json.loads(s.value("eq_gains", "[]"))]
        except (TypeError, ValueError):
            gains = []
        gains = convert(gains, self.n) if len(gains) in BAND_COUNTS else [0.0] * self.n
        self._set_values(gains, float(s.value("eq_preamp", 0.0)))
        self._loading = True
        self.on.setChecked(s.value("eq_enabled", False, bool) and self.available)
        self._loading = False
        self._fill_presets(self._matching_preset())
        self.curve.set_values(gains, self.preamp_db(), self.on.isChecked())
        self._emit()

    def refresh_theme(self):
        self.curve.update()
        for sl in [self.preamp] + self.bands:
            sl.update()


def load_eq_settings(settings) -> tuple[bool, list[float], float]:
    try:
        gains = [float(g) for g in json.loads(settings.value("eq_gains", "[]"))]
    except (TypeError, ValueError):
        gains = []
    try:
        n = int(settings.value("eq_bands", 10))
    except (TypeError, ValueError):
        n = 10
    n = n if n in BAND_COUNTS else 10
    gains = convert(gains, n) if len(gains) in BAND_COUNTS else [0.0] * n
    return settings.value("eq_enabled", False, bool), gains, float(settings.value("eq_preamp", 0.0))
