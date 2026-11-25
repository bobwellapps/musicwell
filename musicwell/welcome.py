"""First-run welcome window: add music, pick a layout and a theme."""
from __future__ import annotations

import os

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QDialog, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QScrollArea,
                               QStackedWidget, QToolButton, QVBoxLayout, QWidget)

from musicwell import APP_NAME
from musicwell import layouts as L
from musicwell import theme as th
from musicwell.dialogs import ask_music_folder, music_dir

STEPS = ["Welcome", "Your music", "Layout", "Theme"]


def layout_picture(d: dict, theme, w: int = 170, h: int = 106) -> QPixmap:
    """A small drawing of a layout."""
    pm = QPixmap(w * 2, h * 2)
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    c = theme.color
    acc = QColor(theme.accent)
    p.setPen(QColor(c("border")))
    p.setBrush(QColor(c("bg")))
    p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 7, 7)
    p.setPen(Qt.NoPen)
    x0, x1, y0, y1 = 4.0, w - 4.0, 4.0, h - 4.0
    tabs = 10.0
    for i in range(4):
        p.setBrush(acc if i == 0 else QColor(c("muted")))
        p.drawRoundedRect(QRectF(x0 + 4 + i * 20, y0 + 3, 15, 3.5), 1.5, 1.5)
    y0 += tabs
    bar = d.get("bar") if isinstance(d.get("bar"), dict) else {}
    if d.get("bar_visible", True):
        bh = 15.0
        at_top = bar.get("position") == "top"
        r = QRectF(x0, y0 if at_top else y1 - bh, x1 - x0, bh)
        p.setBrush(QColor(c("panel")))
        p.drawRoundedRect(r, 3, 3)
        p.setBrush(acc)
        p.drawEllipse(r.center(), 4.2, 4.2)
        p.setBrush(QColor(c("faint")))
        p.drawRoundedRect(QRectF(r.left() + 4, r.top() + 4, 7, 7), 1.5, 1.5)
        if at_top:
            y0 += bh + 3
        else:
            y1 -= bh + 3
    if d.get("panel3_visible") and isinstance(d.get("panel3"), dict) and d["panel3"].get("order"):
        th_ = 18.0
        p.setBrush(QColor(c("panel")))
        p.drawRoundedRect(QRectF(x0, y0, x1 - x0, th_), 3, 3)
        y0 += th_ + 3
    total = 1400.0
    span = x1 - x0

    def side_panel(left: bool, width: float, state: dict):
        nonlocal x0, x1
        pw = max(26.0, span * width / total)
        r = QRectF(x0 if left else x1 - pw, y0, pw, y1 - y0)
        p.setBrush(QColor(c("panel")))
        p.drawRoundedRect(r, 3, 3)
        order = [k for k in (state.get("order") or []) if k not in (state.get("hidden") or [])]
        yy = r.top() + 5
        for k in order[:7]:
            if yy > r.bottom() - 4:
                break
            if k in ("artwork", "artist_image"):
                s = min(r.width() - 10, (r.bottom() - yy) - 4, 40)
                p.setBrush(acc.darker(150) if k == "artwork" else QColor(c("hover")))
                box = QRectF(r.center().x() - s / 2, yy, s, s)
                if k == "artwork" and state.get("cover_style") in ("record", "picture"):
                    p.setBrush(QColor(20, 20, 22))
                    p.drawEllipse(box)
                    p.setBrush(acc.darker(130))
                    p.drawEllipse(box.center(), s * 0.18, s * 0.18)
                else:
                    p.drawRoundedRect(box, 2, 2)
                yy += s + 4
            elif k in ("songs", "upnext", "artists", "lyrics", "queue"):
                p.setBrush(QColor(c("hover")))
                while yy < r.bottom() - 6:
                    p.drawRoundedRect(QRectF(r.left() + 5, yy, r.width() - 10, 2.5), 1, 1)
                    yy += 5.5
            elif k == "visualizer":
                p.setBrush(acc)
                n = int((r.width() - 10) // 4)
                for i in range(n):
                    bh = 2 + (i * 7 % 9)
                    p.drawRect(QRectF(r.left() + 5 + i * 4, yy + 10 - bh, 2.5, bh))
                yy += 13
            elif not k.startswith("spacer"):
                p.setBrush(QColor(c("faint")))
                p.drawRoundedRect(QRectF(r.left() + 5, yy, (r.width() - 10) * 0.7, 2.5), 1, 1)
                yy += 5.5
            else:
                yy += 4
        if left:
            x0 += pw + 3
        else:
            x1 -= pw + 3

    side = d.get("panel_side", "left")
    panel = d.get("panel") if isinstance(d.get("panel"), dict) else {}
    if d.get("panel_visible", True) and panel.get("order"):
        side_panel(side == "left", float(d.get("panel_width", 330)), panel)
    p2 = d.get("panel2") if isinstance(d.get("panel2"), dict) else {}
    if d.get("panel2_visible") and p2.get("order"):
        side_panel(side != "left", float(d.get("panel2_width", 300)), p2)
    if d.get("centre_visible", True) and x1 - x0 > 10:
        r = QRectF(x0, y0, x1 - x0, y1 - y0)
        view = d.get("library_view")
        if view in ("albums", "artist"):
            top = r.top() + 2
            if view == "artist":
                p.setBrush(QColor(c("hover")))
                p.drawEllipse(QRectF(r.left() + 3, top, 14, 14))
                top += 18
            s = 13.0 if d.get("album_covers") in ("small", "xs") or view == "artist" else 17.0
            n = max(1, int((r.width() - 4) // (s + 4)))
            for row in range(2 if view == "artist" else 3):
                for i in range(n):
                    p.setBrush(acc.darker(120 + (i * 37 + row * 53) % 90))
                    p.drawRoundedRect(QRectF(r.left() + 3 + i * (s + 4), top + row * (s + 4), s, s), 2, 2)
            top += (2 if view == "artist" else 3) * (s + 4)
            p.setBrush(QColor(c("hover")))
            yy = top + 2
            while yy < r.bottom() - 3:
                p.drawRoundedRect(QRectF(r.left() + 3, yy, r.width() - 6, 2.5), 1, 1)
                yy += 5.5
        else:
            yy = r.top() + 2
            if d.get("browser_visible"):
                bw = (r.width() - 8) / 3
                for i in range(3):
                    p.setBrush(QColor(c("surface")))
                    p.drawRoundedRect(QRectF(r.left() + i * (bw + 4), yy, bw, 22), 2, 2)
                yy += 26
            p.setBrush(QColor(c("faint")))
            p.drawRoundedRect(QRectF(r.left() + 3, yy, r.width() - 6, 3), 1, 1)
            yy += 7
            i = 0
            while yy < r.bottom() - 3:
                p.setBrush(acc if i == 2 else QColor(c("hover")))
                p.drawRoundedRect(QRectF(r.left() + 3, yy, r.width() - 6, 2.5), 1, 1)
                yy += 5.5
                i += 1
    p.end()
    return pm


class WelcomeDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.w = win
        self.setWindowTitle(f"Welcome to {APP_NAME}")
        self.setMinimumSize(760, 560)
        self.resize(820, 600)
        v = QVBoxLayout(self)
        v.setContentsMargins(26, 20, 26, 18)
        v.setSpacing(14)

        steps = QHBoxLayout()
        steps.setSpacing(6)
        self.step_labels = []
        for i, name in enumerate(STEPS):
            lab = QLabel(f"{i + 1}  {name}")
            lab.setObjectName("EmptyText")
            steps.addWidget(lab)
            self.step_labels.append(lab)
            if i < len(STEPS) - 1:
                dash = QLabel("—")
                dash.setObjectName("EmptyText")
                steps.addWidget(dash)
        steps.addStretch()
        v.addLayout(steps)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._welcome_page())
        self.pages.addWidget(self._music_page())
        self.pages.addWidget(self._layout_page())
        self.pages.addWidget(self._theme_page())
        v.addWidget(self.pages, 1)

        self.line = QFrame()
        self.line.setFixedHeight(1)
        v.addWidget(self.line)
        row = QHBoxLayout()
        self.dont_show = QCheckBox("Don't show this again")
        self.dont_show.setToolTip("You can open it again from Settings → Library → Welcome and setup…")
        self.dont_show.setChecked(win.settings.value("welcome_hide", False, bool))
        row.addWidget(self.dont_show)
        row.addStretch()
        self.skip_btn = QPushButton("Skip setup")
        self.skip_btn.clicked.connect(self.close)
        row.addWidget(self.skip_btn)
        self.back_btn = QPushButton("Back")
        self.back_btn.clicked.connect(lambda: self.go(self.pages.currentIndex() - 1))
        row.addWidget(self.back_btn)
        self.next_btn = QPushButton("Next")
        self.next_btn.setObjectName("Primary")
        self.next_btn.setDefault(True)
        self.next_btn.clicked.connect(self._next)
        row.addWidget(self.next_btn)
        v.addLayout(row)
        self._colours()
        self.go(0)
        win.library.changed.connect(self._update_music)
        win.library.scanProgress.connect(self._scanning)
        win.library.scanFinished.connect(self._update_music)

    def _colours(self):
        """Redraw in the current theme's colours."""
        t = self.w.theme
        self.line.setStyleSheet(f"background: {t.color('border').name()}; border: none;")
        if hasattr(self, "theme_holder"):
            self.theme_holder.setStyleSheet(
                "QWidget#ThemeHolder { background: transparent; }"
                "QToolButton { border: 2px solid transparent; border-radius: 10px; padding: 2px; }"
                f"QToolButton:hover {{ background: {t.color('hover').name()}; }}"
                f"QToolButton:checked {{ border-color: {t.accent.name()}; background: {t.color('selected').name()}; }}")

    def go(self, i: int):
        i = max(0, min(len(STEPS) - 1, i))
        self.pages.setCurrentIndex(i)
        for n, lab in enumerate(self.step_labels):
            lab.setStyleSheet("font-weight: 700;" if n == i else "")
            lab.setObjectName("" if n == i else "EmptyText")
            lab.style().unpolish(lab)
            lab.style().polish(lab)
        self.back_btn.setVisible(i > 0)
        self.next_btn.setText("Start listening" if i == len(STEPS) - 1 else
                              "Get started" if i == 0 else "Next")
        self.skip_btn.setVisible(i < len(STEPS) - 1)
        if i == 1:
            self._update_music()
        elif i == 2:
            self._mark_layout()
        elif i == 3:
            self._mark_theme()

    def _next(self):
        if self.pages.currentIndex() == len(STEPS) - 1:
            self.close()
        else:
            self.go(self.pages.currentIndex() + 1)

    def closeEvent(self, e):
        self._keep_choice()
        super().closeEvent(e)

    def done(self, r):
        self._keep_choice()
        super().done(r)

    def _keep_choice(self):
        self.w.settings.setValue("welcome_hide", self.dont_show.isChecked())
        self.w.settings.setValue("welcome_seen", True)
        if getattr(self, "_unhooked", False):  # done and close can both get here
            return
        self._unhooked = True
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            for sig, slot in ((self.w.library.changed, self._update_music),
                              (self.w.library.scanProgress, self._scanning),
                              (self.w.library.scanFinished, self._update_music)):
                try:
                    sig.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass

    @staticmethod
    def _page(title: str, text: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 6, 0, 0)
        v.setSpacing(8)
        t = QLabel(title)
        t.setObjectName("EmptyTitle")
        v.addWidget(t)
        d = QLabel(text)
        d.setObjectName("EmptyText")
        d.setWordWrap(True)
        v.addWidget(d)
        v.addSpacing(6)
        return page, v

    def _welcome_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.addStretch(2)
        logo = QLabel()
        icon = os.path.join(os.path.dirname(__file__), "icon.png")
        logo.setPixmap(QIcon(icon).pixmap(QSize(96, 96)))
        logo.setAlignment(Qt.AlignCenter)
        v.addWidget(logo)
        v.addSpacing(10)
        t = QLabel(f"Welcome to {APP_NAME}")
        t.setObjectName("EmptyTitle")
        t.setAlignment(Qt.AlignCenter)
        v.addWidget(t)
        d = QLabel("A music player for your own music — and internet radio, lyrics and more.\n\n"
                   "Let's get you set up in three quick steps: add your music, pick how the window is laid out, "
                   "and choose your colours. You can change any of it later.")
        d.setObjectName("EmptyText")
        d.setWordWrap(True)
        d.setAlignment(Qt.AlignCenter)
        d.setMaximumWidth(560)
        hold = QHBoxLayout()
        hold.addStretch()
        hold.addWidget(d)
        hold.addStretch()
        v.addLayout(hold)
        v.addStretch(3)
        return page

    def _music_page(self) -> QWidget:
        page, v = self._page("Add your music",
                             "Pick the folders your music is in — Musicwell finds every song in them (and in the "
                             "folders inside) and keeps up as you add more. You can also drag folders onto the "
                             "window, or skip this and add them later.")
        row = QHBoxLayout()
        base = os.path.basename(music_dir()) or "Home"
        self.use_music = QPushButton(f"Use my {base} folder")
        self.use_music.setObjectName("Primary")
        self.use_music.setToolTip(music_dir())
        self.use_music.clicked.connect(lambda: self._add(music_dir()))
        row.addWidget(self.use_music)
        choose = QPushButton("Choose a folder…")
        choose.clicked.connect(self._choose)
        row.addWidget(choose)
        self.remove_btn = QPushButton("Remove")
        self.remove_btn.clicked.connect(self._remove)
        row.addWidget(self.remove_btn)
        row.addStretch()
        v.addLayout(row)
        sec = QLabel("YOUR MUSIC FOLDERS")
        sec.setObjectName("SectionTitle")
        v.addWidget(sec)
        self.folders = QListWidget()
        self.folders.itemSelectionChanged.connect(self._update_buttons)
        v.addWidget(self.folders, 1)
        self.found = QLabel("")
        self.found.setObjectName("EmptyText")
        v.addWidget(self.found)
        return page

    def _add(self, path: str):
        if path and path not in self.w.library.folders():
            self.w.library.add_folder(path)
        self._update_music()

    def _choose(self):
        d = ask_music_folder(self, self.w.library.folders())
        if d:
            self._add(d)

    def _remove(self):
        it = self.folders.currentItem()
        if it is not None:
            self.w.library.remove_folder(it.data(Qt.UserRole))
            self._update_music()

    def _update_buttons(self):
        self.remove_btn.setEnabled(self.folders.currentItem() is not None)

    def _update_music(self, *_a):
        if not hasattr(self, "folders"):
            return
        fs = self.w.library.folders()
        self.folders.clear()
        for f in fs:
            it = QListWidgetItem(f)
            it.setData(Qt.UserRole, f)
            self.folders.addItem(it)
        if not fs:
            self.folders.addItem(QListWidgetItem("No folders yet"))
            self.folders.item(0).setFlags(Qt.NoItemFlags)
        self.use_music.setEnabled(music_dir() not in fs)
        n = len(getattr(self.w.library, "tracks", {}) or {})
        scanning = bool(getattr(self.w.library, "scanner", None) and self.w.library.scanner.isRunning())
        self.found.setText("Looking for songs…" if scanning and not n else
                           f"{n:,} song{'s' if n != 1 else ''} in your library" if n else
                           ("No songs found in these folders yet" if fs else ""))
        self._update_buttons()

    def _scanning(self, seen: int, text: str):
        if hasattr(self, "found") and seen:
            self.found.setText(text or f"Looking for songs… {seen:,} files so far")

    def _layout_page(self) -> QWidget:
        page, v = self._page("Choose a layout",
                             "How the window is arranged — click one to try it in the window behind. You can "
                             "change it any time from the Layouts button at the top right, and change anything in it "
                             "(it remembers).")
        self.layout_list = QListWidget()
        self.layout_list.setViewMode(QListWidget.IconMode)
        self.layout_list.setResizeMode(QListWidget.Adjust)
        self.layout_list.setMovement(QListWidget.Static)
        self.layout_list.setIconSize(QSize(170, 106))
        self.layout_list.setGridSize(QSize(184, 140))
        self.layout_list.setSpacing(6)
        self.layout_list.setWordWrap(True)
        self.layout_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.layout_list.setObjectName("WelcomeGrid")
        for name, desc, d, builtin in L.all_presets(self.w.settings):
            if name == "Empty":
                continue
            eff, _b, _c = L.effective(self.w.settings, name)
            it = QListWidgetItem(QIcon(layout_picture(eff or d, self.w.theme)), name)
            it.setData(Qt.UserRole, name)
            it.setToolTip(desc)
            it.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            self.layout_list.addItem(it)
        self.layout_list.itemClicked.connect(self._layout_picked)
        self.layout_list.currentItemChanged.connect(lambda it, _old: self._describe_layout(it))
        v.addWidget(self.layout_list, 1)
        self.layout_desc = QLabel("")
        self.layout_desc.setObjectName("EmptyText")
        self.layout_desc.setWordWrap(True)
        self.layout_desc.setMinimumHeight(52)
        self.layout_desc.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        v.addWidget(self.layout_desc)
        return page

    def _describe_layout(self, it):
        if it is not None:
            self.layout_desc.setText(f"<b>{it.text()}</b> — {it.toolTip()}")

    def _mark_layout(self):
        cur = self.w.settings.value("layout_current", "")
        for i in range(self.layout_list.count()):
            it = self.layout_list.item(i)
            if it.data(Qt.UserRole) == cur:
                self.layout_list.setCurrentItem(it)
                self._describe_layout(it)
                return

    def _layout_picked(self, it):
        name = it.data(Qt.UserRole)
        self._describe_layout(it)
        if name and name != self.w.settings.value("layout_current", ""):
            QTimer.singleShot(0, lambda: self.w.use_layout(name, quiet=True))

    def _theme_page(self) -> QWidget:
        page, v = self._page("Choose a theme",
                             "The colours — click one to see it. Settings → Theme has more: your own "
                             "accent colour, and colours that follow the album artwork.")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        holder = QWidget()
        holder.setObjectName("ThemeHolder")
        self.theme_holder = holder
        scroll.viewport().setAutoFillBackground(False)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")
        self.theme_scroll = scroll
        grid = QGridLayout(holder)
        grid.setSpacing(6)
        grid.setContentsMargins(0, 0, 0, 0)
        self.theme_group = QButtonGroup(self)
        self.theme_group.setExclusive(True)
        self.theme_buttons = {}
        cols = 5
        for n, (key, name) in enumerate(th.theme_names()):
            b = QToolButton()
            b.setCheckable(True)
            b.setIcon(QIcon(th.theme_preview(key, 120, 76)))
            b.setIconSize(QSize(120, 76))
            b.setText(name)
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setAutoRaise(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _c=False, k=key: self._theme_picked(k))
            self.theme_group.addButton(b)
            self.theme_buttons[key] = b
            grid.addWidget(b, n // cols, n % cols)
        grid.setRowStretch(len(self.theme_buttons) // cols + 1, 1)
        scroll.setWidget(holder)
        v.addWidget(scroll, 1)
        return page

    def _mark_theme(self):
        b = self.theme_buttons.get(self.w.settings.value("theme", "dark"))
        if b is not None:
            b.setChecked(True)
            QTimer.singleShot(0, lambda: self.theme_scroll.ensureWidgetVisible(b, 10, 10))

    def _theme_picked(self, key: str):
        self.w.set_theme(key)
        self._colours()
        # redraw the layout previews in the new colours
        for i in range(self.layout_list.count()):
            it = self.layout_list.item(i)
            eff, _b, _c = L.effective(self.w.settings, it.data(Qt.UserRole))
            if eff:
                it.setIcon(QIcon(layout_picture(eff, self.w.theme)))
