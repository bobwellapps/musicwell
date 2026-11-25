"""Colours, stylesheet and icons."""
from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

DEFAULT_ACCENT = "#5aa9ff"

# Colour themes: window colours, dark or light, and a default accent.
def _pal(name, dark, accent, bg, panel, surface, hover, border, text, muted, faint, selected):
    return {"name": name, "dark": dark, "accent": accent, "bg": bg, "panel": panel, "surface": surface,
            "hover": hover, "border": border, "text": text, "muted": muted, "faint": faint,
            "selected": selected}


PALETTES = {
    "dark": _pal("Dark", True, "#5aa9ff", "#111215", "#16181c", "#1d2025", "#252930", "#24272d",
                 "#ecedf0", "#8d939c", "#5d636c", "#2a2f37"),
    "light": _pal("Light", False, "#2f7de1", "#f6f6f8", "#ececf0", "#ffffff", "#e4e5ea", "#dcdde3",
                  "#17181b", "#60656d", "#9aa0a8", "#dfe3ea"),
    "black": _pal("OLED Black", True, "#7c9cff", "#000000", "#070708", "#101012", "#1a1a1d", "#16161a",
                  "#f2f2f4", "#8e8e96", "#5a5a62", "#1f2128"),
    "midnight": _pal("Midnight", True, "#6c8cff", "#0d1220", "#111829", "#172036", "#1f2a45", "#1c253c",
                     "#e6ebf7", "#8a97b5", "#5a6683", "#24304f"),
    "nord": _pal("Nord", True, "#88c0d0", "#2e3440", "#323946", "#3b4252", "#434c5e", "#3b4252",
                 "#eceff4", "#a3adc2", "#7b869c", "#4c566a"),
    "dracula": _pal("Dracula", True, "#bd93f9", "#21222c", "#262834", "#2c2e3b", "#363848", "#313341",
                    "#f8f8f2", "#a4a8c4", "#6f748f", "#44475a"),
    "tokyo": _pal("Tokyo Night", True, "#7aa2f7", "#16161e", "#1a1b26", "#20212e", "#292e42", "#232433",
                  "#c0caf5", "#8089b3", "#565f89", "#2c324a"),
    "catppuccin": _pal("Catppuccin Mocha", True, "#cba6f7", "#11111b", "#181825", "#1e1e2e", "#313244",
                       "#262637", "#cdd6f4", "#a6adc8", "#6c7086", "#313244"),
    "rosepine": _pal("Rosé Pine", True, "#ebbcba", "#191724", "#1f1d2e", "#26233a", "#2f2b45", "#2a273f",
                     "#e0def4", "#908caa", "#6e6a86", "#393552"),
    "gruvbox": _pal("Gruvbox", True, "#fabd2f", "#1d2021", "#232627", "#282828", "#3c3836", "#32302f",
                    "#ebdbb2", "#a89984", "#7c6f64", "#3c3836"),
    "forest": _pal("Forest", True, "#7fd18b", "#0f1712", "#131d17", "#19251e", "#213128", "#1d2b23",
                   "#e3efe6", "#8fa699", "#5e7468", "#24382c"),
    "ember": _pal("Ember", True, "#ff8a50", "#171210", "#1d1714", "#241c18", "#30251f", "#2a201b",
                  "#f3e9e3", "#a8968b", "#75655c", "#3a2c24"),
    "solarized": _pal("Solarized Dark", True, "#2aa198", "#002b36", "#03303c", "#073642", "#0d4351",
                      "#0a3c49", "#eee8d5", "#93a1a1", "#657b83", "#0f4a59"),
    "solarized_light": _pal("Solarized Light", False, "#268bd2", "#fdf6e3", "#f5eedb", "#fffbef", "#eee8d5",
                            "#e4dcc5", "#073642", "#586e75", "#93a1a1", "#e8e1cb"),
    "latte": _pal("Catppuccin Latte", False, "#8839ef", "#eff1f5", "#e6e9ef", "#ffffff", "#dce0e8",
                  "#ccd0da", "#4c4f69", "#6c6f85", "#9ca0b0", "#dfe2ea"),
    "paper": _pal("Paper", False, "#c0563b", "#f7f3ec", "#efe9df", "#fffdf8", "#e7e0d4", "#e0d8ca",
                  "#2b2621", "#6d655b", "#a59c8f", "#e8dfd0"),
    "daylight": _pal("Daylight", False, "#0a84ff", "#ffffff", "#f4f7fb", "#ffffff", "#e9f1fc", "#dfe5ee",
                     "#101418", "#4f5b6b", "#8792a2", "#d8e8ff"),
    "sky": _pal("Sky", False, "#0284c7", "#eef7fd", "#e1f0fa", "#f9fcff", "#d3e9f8", "#c8e0f1",
                "#0b2233", "#40627b", "#7895ab", "#c5e3f8"),
    "mint": _pal("Mint", False, "#059669", "#effaf5", "#e1f4eb", "#f9fffc", "#d1eee0", "#c6e6d7",
                 "#0a2a1f", "#406b59", "#7b9f90", "#c1ebd7"),
    "sunrise": _pal("Sunrise", False, "#ea580c", "#fff7ed", "#ffeedb", "#fffbf6", "#fde1c4", "#f4d9bc",
                    "#2b1505", "#764f31", "#a68167", "#fed4a6"),
    "lilac": _pal("Lilac", False, "#7c3aed", "#f6f3ff", "#ece5ff", "#fcfaff", "#e0d7fd", "#dbd1f6",
                  "#1d1138", "#5a4c7e", "#9084b1", "#dccfff"),
    "bubblegum": _pal("Bubblegum", False, "#db2777", "#fff1f6", "#fde3ed", "#fffafc", "#fad3e3", "#f3ccdb",
                      "#32101e", "#7a475d", "#a97f92", "#fbcde0"),
    "lemon": _pal("Lemon", False, "#a16207", "#fffde8", "#fdf8d2", "#fffef5", "#f8efb5", "#efe6b0",
                  "#2a2305", "#6c5f2a", "#9d9163", "#fbeea0"),
}
ARTWORK_BACKGROUNDS = [("off", "Off"), ("soft", "Soft — a hint of the cover"),
                       ("strong", "Strong — the cover shows clearly")]
ARTWORK_MODES = [("off", "Off — use the theme's own colours"),
                 ("accent", "Accent colour only"),
                 ("full", "The whole player")]
COLOR_KEYS = ("bg", "panel", "surface", "hover", "border", "text", "muted", "faint", "selected")


def theme_names() -> list[tuple[str, str]]:
    return [(k, v["name"]) for k, v in PALETTES.items()]


class Theme:
    def __init__(self, mode: str = "dark", accent: str = DEFAULT_ACCENT):
        self._mode = "dark"
        self.mode = mode
        self.accent = QColor(accent)
        self.custom: dict | None = None  # colours taken from the album art
        self.see_through = 0.0  # opacity of the album art behind the window, 0 = off
        self.bold_headers = False

    @property
    def mode(self) -> str:
        return self._mode

    @mode.setter
    def mode(self, value):
        self._mode = value if value in PALETTES else "dark"

    @property
    def dark(self) -> bool:
        return self.p["dark"]

    @property
    def p(self) -> dict:
        return self.custom or PALETTES[self._mode]

    def color(self, key: str) -> QColor:
        if key == "accent":
            return QColor(self.accent)
        if key.endswith("_t"):  # see-through variant
            c = QColor(self.p[key[:-2]])
            c.setAlphaF(self._alpha(key[:-2]))
            return c
        return QColor(self.p[key])

    def _alpha(self, key: str) -> float:
        if not self.see_through:
            return 1.0
        return min(1.0, 1.0 - self.see_through + {"bg": 0.0, "panel": 0.10, "surface": 0.16}.get(key, 0.0))

    def _rgba(self, key: str) -> str:
        c = QColor(self.p[key])
        a = self._alpha(key)
        return c.name() if a >= 1.0 else f"rgba({c.red()},{c.green()},{c.blue()},{a:.3f})"

    def accent_text(self) -> str:
        """Black or white, whichever reads better on the accent."""
        a = self.accent
        lum = 0.299 * a.red() + 0.587 * a.green() + 0.114 * a.blue()
        return "#101114" if lum > 150 else "#ffffff"

    def stylesheet(self) -> str:
        p = {k: self.p[k] for k in COLOR_KEYS}
        a = self.accent
        p["accent"] = a.name()
        p["accent_soft"] = f"rgba({a.red()},{a.green()},{a.blue()},0.18)"
        p["accent_text"] = self.accent_text()
        p["bgt"], p["panelt"], p["surfacet"] = self._rgba("bg"), self._rgba("panel"), self._rgba("surface")
        p["tick_img"] = _tick_image(p["accent_text"])
        return (QSS.format(**p) + (SEE_THROUGH_QSS if self.see_through else "")
                + (BOLD_HEADERS_QSS.format(**p) if self.bold_headers else ""))


def _tick_image(color: str) -> str:
    """A tick image file for checkbox styling."""
    try:
        from musicwell.paths import cache_dir
        d = cache_dir() / "ui"
        d.mkdir(parents=True, exist_ok=True)
        f = d / f"tick-{color.lstrip('#')}.svg"
        if not f.exists():
            f.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">'
                         f'<path d="M4.2 8.4 L6.9 11 L11.9 5.4" fill="none" stroke="{color}" stroke-width="1.9" '
                         'stroke-linecap="round" stroke-linejoin="round"/></svg>', encoding="utf-8")
        return f.as_posix()
    except OSError:
        return ""


BOLD_HEADERS_QSS = """
QHeaderView::section {{ color: {text}; font-size: 9.5pt; font-weight: 900; }}
#PaneHeader {{ color: {text}; font-size: 9pt; font-weight: 900; }}
#LikedList QHeaderView::section {{ font-weight: 900; }}
"""

QSS = """
* {{ outline: 0; }}
QMainWindow, QDialog {{ background: {bg}; }}
QWidget {{ color: {text}; font-size: 10pt; }}
QToolTip {{ background: {surface}; color: {text}; border: 1px solid {border}; padding: 4px 6px; }}

#TopBar {{ background: {bgt}; }}
#NavButton {{
    background: transparent; border: none; color: {muted};
    font-size: 14pt; font-weight: 600; padding: 4px 10px 6px 10px;
}}
#NavButton:hover {{ color: {text}; }}
#NavButton:checked {{ color: {text}; border-bottom: 3px solid {accent}; }}
#NavButton[iconsOnly="true"] {{ padding: 4px 8px 6px 8px; }}
#NavButton[tight="true"] {{ font-size: 12pt; padding: 4px 5px 6px 5px; }}
QPushButton#MoreTabs {{ background: transparent; border: none; color: {muted}; font-size: 15pt; font-weight: 700;
    padding: 2px 8px 6px 8px; }}
QPushButton#MoreTabs:hover {{ color: {text}; }}
#NavButton[inPanel="true"] {{ color: {accent}; }}
#ScanLabel {{ color: {muted}; font-size: 9pt; }}
#ScanBanner {{ background: {hover}; border: none; border-radius: 0; }}
#ScanText {{ color: {text}; font-size: 9pt; background: transparent; }}
QProgressBar#ScanBar {{ background: {border}; border: none; border-radius: 3px; }}
QProgressBar#ScanBar::chunk {{ background: {accent}; border-radius: 3px; }}

#SearchBox {{
    background: {surface}; border: 1px solid {border}; border-radius: 17px;
    padding: 6px 12px 6px 32px; min-height: 22px; selection-background-color: {accent};
}}
#SearchBox:focus {{ border: 1px solid {accent}; }}

#NowPanel {{ background: {panelt}; }}
#NowTitle {{ font-size: 15pt; font-weight: 700; }}
#NowArtist {{ color: {accent}; font-size: 11pt; font-weight: 600; }}
#NowAlbum {{ color: {muted}; font-size: 10pt; }}
#NowMeta {{ color: {faint}; font-size: 8.5pt; }}
#NowSectionLabel {{ color: {faint}; font-size: 8pt; font-weight: 700; letter-spacing: 1px; }}

#PlayBar {{ background: {panelt}; border-top: 1px solid {border}; }}
#PlayBar[atTop="true"] {{ border-top: none; border-bottom: 1px solid {border}; }}
#BarTitle {{ font-weight: 600; }}
#BarTag {{ color: {accent}; font-size: 7.5pt; font-weight: 700; letter-spacing: 1px; }}
#AddedToast {{ background: {accent}; color: {accent_text}; border-radius: 10px; padding: 10px 20px;
               font-size: 11.5pt; font-weight: 700; }}
#QueueToast {{ background: {surface}; color: {text}; border: 1px solid {accent}; border-radius: 10px;
               padding: 8px 14px; font-size: 10pt; }}
#BarArtist, #TimeLabel {{ color: {muted}; font-size: 9pt; }}
#BarTray {{ background: {bgt}; border-top: 1px solid {border}; }}
#BarChip {{ background: {surface}; border: 1px solid {border}; border-radius: 12px; padding: 4px 11px; }}
#BarChip:hover {{ border: 1px solid {accent}; }}

QToolButton {{ background: transparent; border: none; border-radius: 6px; padding: 4px; }}
QToolButton:hover {{ background: {hover}; }}
QToolButton:checked {{ background: transparent; }}
QToolButton:checked:hover {{ background: {hover}; }}
#PlayButton {{ background: {accent}; border-radius: 22px; }}
#PlayButton:hover {{ background: {accent}; border: 2px solid {text}; }}

QPushButton {{
    background: {surface}; border: 1px solid {border}; border-radius: 6px;
    padding: 6px 14px;
}}
QPushButton:hover {{ background: {hover}; }}
QPushButton#Primary {{ background: {accent}; color: {accent_text}; border: none; font-weight: 600; }}
QPushButton:disabled {{ color: {faint}; }}
QPushButton#Primary:disabled {{ background: {hover}; color: {faint}; }}
QPushButton#CopyPill {{ background: {accent}; color: {accent_text}; border: none; border-radius: 11px;
    padding: 0px 11px; font-weight: 600; font-size: 8.5pt; }}
QPushButton#CopyPill:hover {{ background: {accent}; border: 1px solid {text}; }}

QSlider::groove:horizontal {{ height: 4px; background: {hover}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {accent}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: {text}; width: 12px; height: 12px; margin: -4px 0; border-radius: 6px;
}}
QSlider::handle:horizontal:hover {{ background: {accent}; }}
QSlider::groove:vertical {{ width: 4px; background: {hover}; border-radius: 2px; }}
QSlider::add-page:vertical {{ background: {accent}; border-radius: 2px; }}
QSlider::sub-page:vertical {{ background: {hover}; border-radius: 2px; }}
QSlider::handle:vertical {{
    background: {text}; width: 14px; height: 14px; margin: 0 -5px; border-radius: 7px;
}}
QSlider::handle:vertical:hover {{ background: {accent}; }}
QSlider::add-page:vertical:disabled {{ background: {faint}; }}

QTableView, QListView, QListWidget, QTreeView {{
    background: {bgt}; border: none; alternate-background-color: {bgt};
    selection-background-color: {selected}; selection-color: {text};
}}
#Pane {{ background: {bgt}; border-right: 1px solid {border}; }}
#Pane::item {{ padding: 5px 10px; border-radius: 5px; margin: 1px 6px; }}
#Pane::item:hover {{ background: {hover}; }}
#Pane::item:selected {{ background: {accent_soft}; color: {text}; }}
#PaneHeader {{ color: {faint}; font-size: 8pt; font-weight: 700; letter-spacing: 1px; padding: 8px 16px 4px 16px; }}
#BrowserArea {{ border-bottom: 1px solid {border}; }}

QTableView::item {{ padding: 0 6px; border: none; }}
QTableView::item:hover {{ background: {hover}; }}
QHeaderView {{ background: {bgt}; border: none; }}
QHeaderView::section {{
    background: {bgt}; color: {faint}; border: none; border-bottom: 1px solid {border};
    padding: 6px 8px; font-size: 8.5pt; font-weight: 700;
}}
QHeaderView::section:hover {{ color: {text}; }}
/* the Song list in a panel: the panel's own colour shows through (like the artist list and up next) */
#PanelSongs, #PanelSongs QWidget#qt_scrollarea_viewport, #PanelSongs QHeaderView,
#PanelSongs QHeaderView::section, #PanelSongs QTableCornerButton::section {{ background: transparent; }}
#PanelSongs {{ border: none; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {hover}; border-radius: 4px; min-height: 30px; margin: 2px; }}
QScrollBar::handle:vertical:hover {{ background: {faint}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {hover}; border-radius: 4px; min-width: 30px; margin: 2px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

QSplitter::handle {{ background: {border}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}

QMenu {{ background: {surface}; border: 1px solid {border}; padding: 4px; border-radius: 8px; }}
QMenu::item {{ padding: 6px 22px 6px 14px; border-radius: 5px; }}
QMenu::item:selected {{ background: {hover}; }}
QMenu::item:disabled {{ color: {faint}; background: transparent; }}
QMenu::separator {{ height: 1px; background: {border}; margin: 4px 8px; }}

QLineEdit, QSpinBox, QComboBox {{
    background: {surface}; border: 1px solid {border}; border-radius: 6px; padding: 5px 8px;
    selection-background-color: {accent};
}}
QLineEdit:focus, QComboBox:focus {{ border: 1px solid {accent}; }}
QComboBox QAbstractItemView {{ background: {surface}; border: 1px solid {border}; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid {faint}; background: {surface}; }}
QCheckBox::indicator:checked {{ background: {accent}; border: 1px solid {accent}; }}
QListWidget[ticks="true"]::indicator {{ width: 16px; height: 16px; border-radius: 8px; border: 1.5px solid {faint}; background: transparent; margin-right: 4px; }}
QListWidget[ticks="true"]::indicator:checked {{ background: {accent}; border: 1.5px solid {accent}; image: url({tick_img}); }}
QGroupBox {{ border: 1px solid {border}; border-radius: 8px; margin-top: 14px; padding: 10px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; color: {muted}; }}
#EmptyTitle {{ font-size: 18pt; font-weight: 700; }}
QTabWidget::pane {{ border: 1px solid {border}; border-radius: 8px; top: -1px; background: {bg}; }}
QTabBar::tab {{ background: transparent; color: {muted}; padding: 8px 14px; border: none;
               border-bottom: 2px solid transparent; font-weight: 600; }}
QTabBar::tab:hover {{ color: {text}; }}
QTabBar::tab:selected {{ color: {text}; border-bottom: 2px solid {accent}; }}
#EmptyText {{ color: {muted}; }}
#StatsPage, #StatsBody {{ background: {bgt}; border: none; }}
#StatCard {{ background: {surfacet}; border: 1px solid {border}; border-radius: 10px; }}
#StatLabel {{ color: {faint}; font-size: 8pt; font-weight: 700; letter-spacing: 1px; background: transparent; }}
#StatValue {{ font-size: 20pt; font-weight: 700; background: transparent; }}
#StatCard QLabel {{ background: transparent; border: none; }}
QPushButton#Segment {{ background: transparent; border: 1px solid {border}; border-radius: 14px;
                       padding: 4px 12px; color: {muted}; }}
QPushButton#Segment:hover {{ color: {text}; }}
QPushButton#Segment:checked {{ background: {accent_soft}; border: 1px solid {accent}; color: {text}; }}
QPushButton#DiscoverSeg {{ background: {surface}; border: 1px solid {border}; border-radius: 16px;
                           padding: 6px 18px; color: {muted}; font-weight: 600; }}
QPushButton#DiscoverSeg:hover {{ color: {text}; border: 1px solid {accent}; }}
QPushButton#DiscoverSeg:checked {{ background: {accent}; border: 1px solid {accent}; color: {accent_text}; }}
#PageTitle {{ font-size: 13pt; font-weight: 700; padding: 6px 4px; }}
#FieldLabel {{ font-weight: 600; padding-top: 2px; }}
#AlbumGrid::item:selected {{ background: {accent_soft}; border: 2px solid {accent}; border-radius: 8px; color: {text}; }}
#SettingsSide {{ background: transparent; border: none; outline: none; }}
#SettingsSide::item {{ padding: 8px 10px; border-radius: 7px; color: {muted}; }}
#SettingsSide::item:hover {{ background: {hover}; color: {text}; }}
#SettingsSide::item:selected {{ background: {accent_soft}; color: {text}; }}
#SectionTitle {{ color: {faint}; font-size: 8pt; font-weight: 700; letter-spacing: 1px; padding-top: 4px; }}
#StationList {{ background: {panelt}; border: 1px solid {border}; border-radius: 10px; outline: none; }}
#ArtistChips {{ background: transparent; border: none; outline: none; }}
#LikedList {{ background: {panelt}; border: 1px solid {border}; border-radius: 10px; outline: none; }}
#LikedList::item {{ padding: 8px 6px; border: none; }}
#LikedList::item:hover {{ background: {hover}; }}
#LikedList::item:selected {{ background: {selected}; color: {text}; }}
#LikedList QHeaderView::section {{ padding: 6px; }}
#ArtistChips::item {{ background: {surface}; border: 1px solid {border}; border-radius: 13px; padding: 2px 10px;
                      color: {text}; }}
#ArtistChips::item:hover {{ border: 1px solid {accent}; }}
#ArtistChips::item:selected {{ background: {accent_soft}; border: 1px solid {accent}; color: {text}; }}
"""

# With the artwork behind the window, scroll areas must not paint over it.
SEE_THROUGH_QSS = """
#NowPanel QWidget#qt_scrollarea_viewport, #StatsPage QWidget#qt_scrollarea_viewport { background: transparent; }
#StatsPage, #StatsBody { background: transparent; }
"""


_F = 'fill="{c}"'
_S = 'fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"'
_S1 = 'fill="none" stroke="{c}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"'

ICONS = {
    "play": f'<path {_F} d="M8 5.2v13.6c0 .8.9 1.3 1.6.9l10.6-6.8c.6-.4.6-1.4 0-1.8L9.6 4.3C8.9 3.9 8 4.4 8 5.2z"/>',
    "pause": f'<rect {_F} x="6" y="5" width="4" height="14" rx="1.2"/><rect {_F} x="14" y="5" width="4" height="14" rx="1.2"/>',
    "next": f'<path {_F} d="M5.5 6.6v10.8c0 .8.9 1.2 1.5.8l7.8-5.4c.5-.4.5-1.2 0-1.6L7 5.8c-.6-.4-1.5 0-1.5.8z"/><rect {_F} x="16" y="5.5" width="2.5" height="13" rx="1"/>',
    "prev": f'<path {_F} d="M18.5 6.6v10.8c0 .8-.9 1.2-1.5.8l-7.8-5.4c-.5-.4-.5-1.2 0-1.6L17 5.8c.6-.4 1.5 0 1.5.8z"/><rect {_F} x="5.5" y="5.5" width="2.5" height="13" rx="1"/>',
    "shuffle": f'<path {_S} d="M3 7h3.5c4.5 0 6.5 10 11 10H21M3 17h3.5c4.5 0 6.5-10 11-10H21M18 4l3 3-3 3M18 14l3 3-3 3"/>',
    "repeat": f'<path {_S} d="M4 11V9.5A3.5 3.5 0 0 1 7.5 6H20M17 3l3 3-3 3M20 13v1.5a3.5 3.5 0 0 1-3.5 3.5H4M7 21l-3-3 3-3"/>',
    "repeat1": f'<path {_S} d="M4 11V9.5A3.5 3.5 0 0 1 7.5 6H20M17 3l3 3-3 3M20 13v1.5a3.5 3.5 0 0 1-3.5 3.5H4M7 21l-3-3 3-3"/><path {_S1} d="M11 10.5l1.4-1v5"/>',
    "volume": f'<path {_F} d="M4 9.2h3.3L12 5.4v13.2l-4.7-3.8H4z"/><path {_S} d="M15.5 9a4.2 4.2 0 0 1 0 6M18 6.5a7.8 7.8 0 0 1 0 11"/>',
    "volume_low": f'<path {_F} d="M4 9.2h3.3L12 5.4v13.2l-4.7-3.8H4z"/><path {_S} d="M15.5 9a4.2 4.2 0 0 1 0 6"/>',
    "mute": f'<path {_F} d="M4 9.2h3.3L12 5.4v13.2l-4.7-3.8H4z"/><path {_S} d="M15.5 9.5l5 5M20.5 9.5l-5 5"/>',
    "search": f'<circle {_S} cx="10.5" cy="10.5" r="6"/><path {_S} d="M20 20l-5-5"/>',
    "queue": f'<path {_S} d="M4 6h13M4 11h13M4 16h7"/><path {_F} d="M15 13.5v6.4c0 .5.5.8.9.5l4.6-3.2c.4-.3.4-.8 0-1.1l-4.6-3.2c-.4-.2-.9.1-.9.6z"/>',
    "settings": f'<path {_S} d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle {_S} cx="15" cy="7" r="2.2"/><circle {_S} cx="9" cy="17" r="2.2"/>',
    "panel": f'<rect {_S} x="3.5" y="4.5" width="17" height="15" rx="2.5"/><path {_S} d="M9.5 4.5v15"/>',
"panel_right": f'<rect {_S} x="3.5" y="4.5" width="17" height="15" rx="2.5"/><path {_S} d="M14.5 4.5v15"/>',
    "plus": f'<path {_S} d="M12 5v14M5 12h14"/>',
    "folder": f'<path {_S} d="M3.5 7.5a2 2 0 0 1 2-2h4l2 2.5h7a2 2 0 0 1 2 2v7.5a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/>',
    "star": f'<path {_F} d="M12 3.2l2.6 5.6 6.1.7-4.5 4.2 1.2 6.1L12 16.8l-5.4 3 1.2-6.1-4.5-4.2 6.1-.7z"/>',
    "star_empty": f'<path {_S1} d="M12 3.2l2.6 5.6 6.1.7-4.5 4.2 1.2 6.1L12 16.8l-5.4 3 1.2-6.1-4.5-4.2 6.1-.7z"/>',
    "speaker": f'<path {_F} d="M4 9.2h3.3L12 5.4v13.2l-4.7-3.8H4z"/><path {_S} d="M15.5 9a4.2 4.2 0 0 1 0 6"/>',
"eq": f'<path {_S} d="M6 4v16M12 4v16M18 4v16"/><rect {_F} x="3.5" y="13" width="5" height="3" rx="1.2"/><rect {_F} x="9.5" y="7" width="5" height="3" rx="1.2"/><rect {_F} x="15.5" y="11" width="5" height="3" rx="1.2"/>',
"cast": f'<path {_S} d="M3.5 9V6.5a2 2 0 0 1 2-2h13a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H14"/><path {_S} d="M3.5 13a6.5 6.5 0 0 1 6.5 6.5M3.5 16.5a3 3 0 0 1 3 3"/><circle {_F} cx="3.8" cy="19.4" r="1.2"/>',
    "cast_on": f'<path {_S} d="M3.5 9V6.5a2 2 0 0 1 2-2h13a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H14"/><path {_F} d="M7 8h10v8h-3.4A9.6 9.6 0 0 0 7 9.4z" opacity=".55"/><path {_S} d="M3.5 13a6.5 6.5 0 0 1 6.5 6.5M3.5 16.5a3 3 0 0 1 3 3"/><circle {_F} cx="3.8" cy="19.4" r="1.2"/>',
    "stop_after": f'<rect {_F} x="5" y="5" width="9" height="14" rx="1.5"/><path {_S} d="M18 7v10"/>',
    "stop": f'<rect {_F} x="6" y="6" width="12" height="12" rx="2"/>',
    "lyrics": f'<rect {_S} x="9" y="2.8" width="6" height="11" rx="3"/><path {_S} d="M5.8 11.2a6.2 6.2 0 0 0 12.4 0M12 17.4v3.6M8.8 21h6.4"/>',
    "back10": f'<path {_S} d="M4.5 12a7.5 7.5 0 1 0 2.2-5.3"/><path {_F} d="M3.6 3.6v5.2h5.2z"/><text {_F} x="12.2" y="15.4" font-size="7.6" font-family="sans-serif" font-weight="700" text-anchor="middle">10</text>',
    "fwd10": f'<path {_S} d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3"/><path {_F} d="M20.4 3.6v5.2h-5.2z"/><text {_F} x="11.8" y="15.4" font-size="7.6" font-family="sans-serif" font-weight="700" text-anchor="middle">10</text>',
    "heart": f'<path {_F} d="M12 20.3S3.5 15 3.5 9.2A4.4 4.4 0 0 1 12 7a4.4 4.4 0 0 1 8.5 2.2C20.5 15 12 20.3 12 20.3z"/>',
    "heart_empty": f'<path {_S} d="M12 19.6S4.3 14.8 4.3 9.3A3.9 3.9 0 0 1 12 7.6a3.9 3.9 0 0 1 7.7 1.7C19.7 14.8 12 19.6 12 19.6z"/>',
    "heart_full": '<path fill="{c}" fill-rule="nonzero" d="M12 20.3S3.5 15 3.5 9.2A4.4 4.4 0 0 1 12 7a4.4 4.4 0 0 1 8.5 2.2C20.5 15 12 20.3 12 20.3z"/>',
    "wave": f'<path {_S} d="M4 10v4M8 7v10M12 4v16M16 8v8M20 11v2"/>',
    "locate": f'<circle {_S} cx="12" cy="12" r="6.5"/><circle {_F} cx="12" cy="12" r="2.2"/><path {_S} d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3"/>',
    "refresh": f'<path {_S} d="M19.5 12a7.5 7.5 0 0 1-13.2 4.9M4.5 12a7.5 7.5 0 0 1 13.2-4.9"/><path {_F} d="M19.8 3.8v5.4h-5.4zM4.2 20.2v-5.4h5.4z"/>',
    "layouts": f'<rect {_S} x="3.5" y="4.5" width="17" height="15" rx="2.5"/><path {_S} d="M9.5 4.5v15M9.5 12h11"/>',
    "lock": f'<rect {_S} x="5" y="10.5" width="14" height="10" rx="2"/><path {_S} d="M8 10.5V7.5a4 4 0 0 1 8 0v3"/>',
    "unlock": f'<rect {_S} x="5" y="10.5" width="14" height="10" rx="2"/><path {_S} d="M8 10.5V7.5a4 4 0 0 1 7.6-1.7"/>',
    "albums": f'<rect {_S} x="4" y="4" width="7" height="7" rx="1.5"/><rect {_S} x="13" y="4" width="7" height="7" rx="1.5"/><rect {_S} x="4" y="13" width="7" height="7" rx="1.5"/><rect {_S} x="13" y="13" width="7" height="7" rx="1.5"/>',
    "edit": f'<path {_S} d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16v4z"/><path {_S} d="M13.5 6.5l4 4"/>',
    # tab icons
    "library": f'<path {_S} d="M9 17.5V6.2l10-2.2v11.5"/><circle {_S} cx="6.6" cy="17.6" r="2.4"/><circle {_S} cx="16.6" cy="15.6" r="2.4"/>',
    "playlists": f'<path {_S} d="M4 6h11M4 10.5h11M4 15h6"/><path {_S} d="M17.5 18V8.6l3-.9"/><circle {_S} cx="15.6" cy="18.1" r="1.9"/>',
    "stats": f'<path {_S} d="M4 20h16"/><rect {_S} x="5.5" y="11.5" width="3" height="5.5" rx=".8"/><rect {_S} x="10.5" y="5.5" width="3" height="11.5" rx=".8"/><rect {_S} x="15.5" y="9" width="3" height="8" rx=".8"/>',
    "radio": f'<rect {_S} x="3.5" y="9" width="17" height="11" rx="2"/><path {_S} d="M7.5 9l9-5"/><circle {_S} cx="15.5" cy="14.5" r="2.6"/><path {_S} d="M6.8 12.8h3.2M6.8 16.2h3.2"/>',
    "clock": f'<circle {_S} cx="12" cy="12" r="8.5"/><path {_S} d="M12 7.5V12l3 2"/>',
    "sparkle": f'<path {_S} d="M12 3.5l1.9 5.6 5.6 1.9-5.6 1.9L12 18.5l-1.9-5.6-5.6-1.9 5.6-1.9z"/><path {_S} d="M18.5 16v4M16.5 18h4"/>',
    "trend": f'<path {_S} d="M4 17.5l5-5 4 4 7-7"/><path {_S} d="M15 9.5h5v5"/>',
    "play_outline": f'<circle {_S} cx="12" cy="12" r="8.5"/><path {_S} d="M10 8.6v6.8l5.4-3.4z"/>',
    "discover": f'<circle {_S} cx="12" cy="12" r="8.5"/><path {_F} d="M15.8 8.2l-2.2 5.4-5.4 2.2 2.2-5.4z"/>',
    "more": f'<circle {_F} cx="5.5" cy="12" r="1.8"/><circle {_F} cx="12" cy="12" r="1.8"/><circle {_F} cx="18.5" cy="12" r="1.8"/>',
}

ICON_STYLES = {"filled": "Filled", "outline": "Outline", "thin": "Thin", "bold": "Bold"}


def _styled(body: str, style: str) -> str:
    if style == "outline":
        body = body.replace('fill="{c}" x=', 'fill="none" stroke="{c}" stroke-width="1.7" x=') \
                   .replace('fill="{c}" d=', 'fill="none" stroke="{c}" stroke-width="1.7" stroke-linejoin="round" d=') \
                   .replace('fill="{c}" cx=', 'fill="none" stroke="{c}" stroke-width="1.5" cx=')
    elif style == "thin":
        body = body.replace('stroke-width="2"', 'stroke-width="1.25"').replace('stroke-width="1.7"', 'stroke-width="1.15"')
        body = body.replace('fill="{c}" x=', 'fill="none" stroke="{c}" stroke-width="1.2" x=') \
                   .replace('fill="{c}" d=', 'fill="none" stroke="{c}" stroke-width="1.2" stroke-linejoin="round" d=') \
                   .replace('fill="{c}" cx=', 'fill="none" stroke="{c}" stroke-width="1.1" cx=')
    elif style == "bold":
        body = body.replace('stroke-width="2"', 'stroke-width="2.7"').replace('stroke-width="1.7"', 'stroke-width="2.3"')
    # numbers inside icons stay solid
    return body.replace('fill="none" stroke="{c}" stroke-width="1.7" x="12', 'fill="{c}" x="12') \
               .replace('fill="none" stroke="{c}" stroke-width="1.2" x="12', 'fill="{c}" x="12') \
               .replace('fill="none" stroke="{c}" stroke-width="1.7" x="11', 'fill="{c}" x="11') \
               .replace('fill="none" stroke="{c}" stroke-width="1.2" x="11', 'fill="{c}" x="11')


_SVG_CACHE: dict = {}


def svg_image(name: str, color, size: int, scale: float = 2.0, style: str = "filled") -> QImage:
    qc = QColor(color)
    c = qc.name() if qc.alpha() == 255 else f"rgba({qc.red()},{qc.green()},{qc.blue()},{qc.alphaF():.3f})"
    key = (name, c, size, scale, style)
    img = _SVG_CACHE.get(key)
    if img is None:
        if len(_SVG_CACHE) > 600:
            _SVG_CACHE.clear()
        img = _SVG_CACHE[key] = _render_svg(name, c, size, scale, style)
    return QImage(img)


def _render_svg(name: str, c: str, size: int, scale: float, style: str) -> QImage:
    body = _styled(ICONS[name], style).replace("{c}", c)
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">{body}</svg>'
    px = int(size * scale)
    img = QImage(px, px, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing)
    QSvgRenderer(QByteArray(svg.encode())).render(painter, QRectF(0, 0, px, px))
    painter.end()
    img.setDevicePixelRatio(scale)
    return img


def icon(name: str, color, size: int = 20, style: str = "filled") -> QIcon:
    return QIcon(QPixmap.fromImage(svg_image(name, color, size, style=style)))


def theme_preview(key: str, w: int = 132, h: int = 84, accent: str | None = None) -> QPixmap:
    """A small preview of the window in a theme."""
    from PySide6.QtCore import QRectF as R
    p_ = PALETTES[key]
    acc = QColor(accent or p_["accent"])
    pm = QPixmap(w * 2, h * 2)
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    clip = __import__("PySide6.QtGui", fromlist=["QPainterPath"]).QPainterPath()
    clip.addRoundedRect(R(0, 0, w, h), 8, 8)
    p.setClipPath(clip)
    p.fillRect(R(0, 0, w, h), QColor(p_["bg"]))
    p.fillRect(R(0, 0, w * 0.32, h), QColor(p_["panel"]))
    p.fillRect(R(w * 0.06, h * 0.10, w * 0.20, w * 0.20), acc.darker(140))
    p.fillRect(R(w * 0.06, h * 0.50, w * 0.18, 3), QColor(p_["text"]))
    p.fillRect(R(w * 0.06, h * 0.58, w * 0.13, 3), acc)
    for i in range(4):
        y = h * 0.12 + i * h * 0.14
        if i == 1:
            p.fillRect(R(w * 0.34, y - 3, w * 0.64, 9), QColor(p_["selected"]))
        p.fillRect(R(w * 0.38, y, w * 0.30, 3), acc if i == 1 else QColor(p_["text"]))
        p.fillRect(R(w * 0.74, y, w * 0.18, 3), QColor(p_["muted"]))
    p.fillRect(R(0, h * 0.74, w, h * 0.26), QColor(p_["panel"]))
    p.fillRect(R(0, h * 0.74, w, 1), QColor(p_["border"]))
    p.setPen(Qt.NoPen)
    p.setBrush(acc)
    p.drawEllipse(R(w / 2 - 7, h * 0.80, 14, 14))
    p.fillRect(R(w * 0.62, h * 0.86, w * 0.30, 3), QColor(p_["hover"]))
    p.fillRect(R(w * 0.62, h * 0.86, w * 0.18, 3), acc)
    p.end()
    return pm
