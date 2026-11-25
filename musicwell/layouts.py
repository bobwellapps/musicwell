"""Layouts: named arrangements of the window. Built-ins are small recipes where anything unmentioned is the default; user layouts live in settings under `layout_presets` and can be exported to .musicwell-layout files."""
from __future__ import annotations

import copy
import json

from musicwell import bar as bar_mod
from musicwell import panel as panel_mod

FORMAT = "musicwell-layout"
OLD_FORMATS = ("listenwell-layout", "tunewell-layout")  # layouts from before the rename
VERSION = 1

_DEFAULT_COLS = ["playing", "track", "title", "artist", "album", "year", "genre", "length", "rating",
                 "playcount"]


def _panel(order=None, hidden=None, align="left", fields=None, spacers=None, heights=None, widths=None):
    order = list(order or panel_mod.DEFAULT_ORDER)
    hidden = panel_mod.DEFAULT_HIDDEN if hidden is None else hidden
    # Items the layout doesn't list are removed, including ones you added yourself.
    removed = [k for k in panel_mod.ALL_KEYS if k not in order]
    return {"order": order, "hidden": list(hidden), "removed": removed,
            "fields": list(fields or panel_mod.DEFAULT_FIELDS), "align": align, "spacers": spacers or {},
            "heights": dict(heights or {}), "widths": dict(widths or {})}


def _bar(zones=None, **options):
    z = copy.deepcopy(bar_mod.DEFAULT_ZONES)
    z.update(zones or {})
    o = dict(bar_mod.DEFAULT_OPTIONS)
    o.pop("position")  # built-ins leave the bar where you put it
    o.update(options)
    return {"zones": z, "options": o, "gaps": {}}


# name: (description, recipe)
DEFAULT_LAYOUT = "Default"
OLD_NAMES = {"Musicwell": "Default", "Musicwell Default": "Default", "Dopamine": "Minimal", "Compact": "Minimal", "Quod Libet": "Organiser", "Organizer": "Organiser",
             "Track List": "Minimal", "Full Monty": "Overload", "Album Gallery": "Albums", "Everything": "Overload"}
# Built-ins keep the second and top panels closed unless they use them.
_NO_PANEL2 = {"panel2_visible": False, "panel3_visible": False, "panel3_where": "top", "tab_style": "words",
              "centre_visible": True, "bar_visible": True}


def _with(**kw) -> dict:
    return dict(_NO_PANEL2, **kw)


BUILTIN = {
    "Default": (
        "The song list (sorted by album) with the artist photo, the cover, the song's title, artist, album and "
        "rating, a wave visualizer and ♥ Like, all lined up in the middle of the panel on the right; tabs with icons "
        "and words.",
        _with(panel_side="right", panel_visible=True, panel_width=360, browser_visible=False, page=0,
              tab_style="both",
              panel=_panel(["artist_image", "spacer:1", "artwork", "cast", "title", "artist", "album", "rating",
                            "visualizer", "like"],
                           hidden=[], align="center", spacers={"spacer:1": {"h": 24, "line": False}},
                           heights={"artist_image": 160, "artwork": 215, "visualizer": 48}),
              visualizer="wave",
              bar=_bar({"left": ["cover", "info"], "center": ["shuffle", "prev", "play", "next", "repeat"],
                        "below": ["seek"], "right": ["stopafter", "cast", "eq", "queue", "mute", "volume"]},
                       icon_size="medium", icon_style="filled", play_style="circle", seek_style="bars",
                       seek_handle="always", seek_times="both"),
              columns=["playing", "artist", "title", "genre", "album", "year", "length"], sort=("album", "asc"))),
    "Albums": (
        "Every album as covers in the Library tab — click one for its songs below, + and − on the covers to pick "
        "what plays — with the artist photo, the cover, the song, its rating, a wave visualizer and ♥ Like in the "
        "panel on the right; tabs with icons and words.",
        _with(panel_side="right", panel_visible=True, panel_width=360, browser_visible=False, page=0,
              tab_style="both", library_view="albums", album_covers="small", albums_back=False,
              panel=_panel(["artist_image", "spacer:1", "artwork", "cast", "title", "artist", "album", "rating",
                            "visualizer", "like"],
                           hidden=[], align="center", spacers={"spacer:1": {"h": 24, "line": False}},
                           heights={"artist_image": 160, "artwork": 215, "visualizer": 48}),
              visualizer="wave",
              bar=_bar({"left": ["cover", "info"], "center": ["shuffle", "prev", "play", "next", "repeat"],
                        "below": ["seek"], "right": ["stopafter", "cast", "eq", "queue", "mute", "volume"]},
                       icon_size="medium", icon_style="filled", play_style="circle", seek_style="bars",
                       seek_handle="always", seek_times="both"),
              columns=["playing", "artist", "title", "genre", "album", "year", "length"], sort=("album", "asc"))),
    "Artists": (
        "The Library tab is an artist's page — their photo, about them, their albums as covers (pick one, or several "
        "with +) and the songs — with every album artist down the left to pick from, and the lyrics, the song, its "
        "rating, a visualizer, ♥ Like and what's up next on the right; tabs with icons and words.",
        _with(panel_side="right", panel_visible=True, panel_width=340, browser_visible=False, page=0,
              tab_style="both", library_view="artist", library_home="artist", artist_covers="xs",
              panel=_panel(["lyrics", "spacer:1", "title", "artist", "album", "rating", "visualizer", "like",
                            "spacer:2", "upnext"],
                           hidden=[], align="center", heights={"lyrics": 220, "visualizer": 48},
                           spacers={"spacer:1": {"h": 24, "line": False}, "spacer:2": {"h": 24, "line": False}}),
              panel2=dict(_panel(["artists"], hidden=[]),
                          artists={"kind": "album", "sort": "name", "counts": True, "pictures": True,
                                   "size": "medium", "filter_box": True, "all_albums": False, "fill": True}),
              panel2_visible=True, panel2_width=300,
              visualizer="bars",
              bar=_bar({"left": ["cover", "info"], "center": ["shuffle", "prev", "play", "next", "repeat"],
                        "below": ["seek"], "right": ["stopafter", "cast", "eq", "queue", "mute", "volume"]},
                       icon_size="medium", icon_style="filled", play_style="circle", seek_style="slider",
                       seek_handle="always", seek_times="both"),
              columns=["playing", "artist", "title", "genre", "album", "year", "length"], sort=("album", "asc"))),
    "Overload": (
        "Everything at once: the artist's photo, about the artist and up next on the left, a big visualizer "
        "across the top, the column browser and a full song list in the middle, and the cover, the song and its "
        "lyrics on the right.",
        _with(panel_side="left", panel_visible=True, panel_width=290, browser_visible=True, page=0,
              tab_style="words",
              browser=["genre", "artist", "album"], browser_height=230,
              panel=_panel(["artist_image", "artist_info", "upnext"], hidden=[],
                           heights={"artist_image": 220, "artist_info": 250}),
              panel2=_panel(["artwork", "title", "artist", "album", "rating", "lyrics"], hidden=[],
                            heights={"artwork": 250, "lyrics": 220}),
              panel2_visible=True, panel2_width=290,
              panel3=_panel(["visualizer"], hidden=[]),
              panel3_visible=True, panel3_where="top", panel3_height=160,
              visualizer="bars", bar=_bar(),
              columns=["playing", "track", "title", "artist", "album", "year", "genre", "length", "rating",
                       "playcount"], sort=None)),
    "Minimal": (
        "Small and tidy: the tabs as icons, a slim Top Panel with the cover, artist, title and rating, the song "
        "list, and a slim bar with a thin seek line across the top.",
        _with(panel_visible=False, browser_visible=False, page=0, tab_style="icons",
              panel3=_panel(["artwork", "artist", "title", "rating"], hidden=[],
                            widths={"artwork": 140, "artist": 220, "title": 260}),
              panel3_visible=True, panel3_where="top", panel3_height=118,
              visualizer="off",
              bar=_bar({"top": ["seek"], "left": [], "center": ["prev", "play", "next"],
                        "below": [], "right": ["shuffle", "repeat", "mute", "volume"]},
                       icon_size="small", icon_style="outline", play_style="plain", seek_style="line",
                       seek_handle="hover", seek_times="none"),
              columns=["playing", "artist", "title", "album", "year", "length"], sort=None)),
    "Organiser": (
        "Library first: five browser columns (artist, album, genre, year, decade) over lots of song details, "
        "no side panels, and a big cover with a waveform seek bar in the play bar.",
        _with(panel_side="right", panel_visible=False, panel_width=300, browser_visible=True, page=0,
              tab_style="words",
              browser=["artist", "album", "genre", "year", "decade"], browser_height=300,
              panel=_panel(["artwork", "title", "artist", "album", "details", "stats", "artist_info"], hidden=[]),
              visualizer="off",
              bar=dict(_bar({"left": ["cover", "info"], "center": ["prev", "play", "next", "stop"],
                             "below": ["seek"], "right": ["shuffle", "repeat", "stopafter", "eq", "queue", "mute",
                                                          "volume"]},
                            icon_size="small", icon_style="thin", play_style="plain", seek_style="bars",
                            seek_handle="always", seek_times="both"), cover_size=84),
              columns=["playing", "artist", "track", "title", "genre", "album", "disc", "year", "length",
                       "playcount", "format", "bitrate", "rating"],
              sort=None)),
    "Vinyl": (
        "A record player: the cover as a spinning record with the song under it, a plain song list on the left "
        "that follows the Library and playlist tabs, just the Library and Playlists tabs with icons and words, and a big cover "
        "in the play bar.",
        _with(panel_side="right", panel_visible=True, panel_width=1050, browser_visible=False, page=0,
              tab_style="both", centre_visible=False,
              tabs={"order": [0, 2], "hidden": [1, 3, 4, 5, 6], "custom": [], "keep_order": True},
              follow="library",
              panel=dict(_panel(["artwork", "title", "artist", "album"], hidden=[], align="center",
                                heights={"artwork": 290}), cover_style="record", middle=True),
              panel2=dict(_panel(["songs"], hidden=[]),
                          songs={"source": "picked", "fill": True, "top_bar": False,
                                 "columns": [{"key": "artist", "shown": True, "width": 170},
                                             {"key": "playing", "shown": True, "width": 30},
                                             {"key": "title", "shown": True, "width": 200},
                                             {"key": "length", "shown": False, "width": 52}]}),
              panel2_visible=True, panel2_width=430,
              visualizer="off",
              bar=dict(_bar({"left": ["cover"], "center": ["shuffle", "prev", "play", "next", "repeat"],
                             "below": ["seek"], "right": ["cast", "eq", "volume", "mute"]},
                            icon_size="medium", icon_style="filled", play_style="circle", seek_style="bars",
                            seek_handle="always", seek_times="remaining"), cover_size=100),
              columns=["playing", "artist", "title", "album", "year", "length"], sort=None)),
    "Empty": (
        "Completely empty: no panels at all — not even the Centre or Bottom Panel — just the tabs. Right-click to "
        "add the panels you want, unlock to fill them, then save it as a layout of your own.",
        None),
}


def _blank_panel() -> dict:
    return {"order": [], "hidden": [], "removed": list(panel_mod.ALL_KEYS), "fields": [], "align": "left",
            "spacers": {}, "heights": {}, "widths": {}}


def empty() -> dict:
    """An empty window to build a layout from scratch: just the tabs."""
    return dict(_NO_PANEL2, **{
        "panel_side": "left", "panel_visible": False, "panel_width": 320, "browser_visible": False,
        "panel": _blank_panel(), "panel2": _blank_panel(), "panel3": _blank_panel(),
        "panel3_visible": False, "panel3_where": "top", "centre_visible": False, "bar_visible": False,
        "page": 0, "library_view": "list", "visualizer": "off",
        "bar": _bar({"top": [], "left": [], "center": [], "below": [], "right": []}),
        "columns": [], "sort": None})


# not offered in the Layouts menu for now
SET_ASIDE = {
    "Stage": (
        "The playing song across the top of the window — cover, title, artist, album, rating, lyrics and "
        "what's up next side by side — over the whole song list.",
        _with(panel_visible=False, browser_visible=False, page=0, tab_style="both",
              panel3=_panel(["artwork", "title", "artist", "album", "rating", "lyrics", "upnext"], hidden=[]),
              panel3_visible=True, panel3_where="top", panel3_height=190,
              visualizer="off",
              bar=_bar({"left": ["cover", "info", "like"], "center": ["shuffle", "prev", "play", "next", "repeat"],
                        "below": ["seek"], "right": ["lyrics", "cast", "eq", "queue", "mute", "volume"]},
                       icon_size="medium", icon_style="outline", play_style="circle", seek_style="bars",
                       seek_handle="hover", seek_times="both"),
              columns=["playing", "track", "title", "artist", "album", "year", "genre", "length", "rating"],
              sort=None)),
    "Album Gallery": (
        "The Albums tab as big covers, with the playing album, its details and what's up next across the "
        "top. + and − on the covers add albums to what's playing.",
        _with(panel_visible=False, browser_visible=False, page="albums", album_covers="large",
              panel3=_panel(["artwork", "title", "artist", "album", "rating", "upnext"], hidden=[]),
              panel3_visible=True, panel3_where="top", panel3_height=170,
              visualizer="off",
              bar=_bar({"left": ["cover", "info", "like"], "center": ["shuffle", "prev", "play", "next", "repeat"],
                        "below": ["seek"], "right": ["lyrics", "cast", "eq", "queue", "mute", "volume"]},
                       icon_size="medium", icon_style="outline", play_style="circle", seek_style="bars",
                       seek_handle="hover", seek_times="both"))),
    "Radio Lounge": (
        "The Radio tab — every favourite with the song it's playing — and the station's picture, the song "
        "and its lyrics on the right. ♥ in the bar to keep a song you hear.",
        _with(panel_side="right", panel_visible=True, panel_width=340, browser_visible=False, page="radio",
              panel=_panel(["artwork", "title", "artist", "album", "visualizer", "lyrics"], hidden=[],
                           align="center", heights={"artwork": 220}),
              visualizer="mirror",
              bar=_bar({"left": ["cover", "info", "like"], "center": ["prev", "play", "next"],
                        "below": [], "right": ["lyrics", "cast", "eq", "mute", "volume"]},
                       icon_size="large", icon_style="filled", play_style="circle", seek_style="line",
                       seek_handle="never", seek_times="none"))),
    "Discover": (
        "Discover — music like what you play, free music online, radio stations — with the artist's photo, "
        "their story and your artist list on the left.",
        _with(panel_side="left", panel_visible=True, panel_width=330, browser_visible=False, page="discover",
              panel=_panel(["artist_image", "title", "artist", "artist_info", "artists"], hidden=[],
                           heights={"artist_image": 170}),
              visualizer="off", bar=_bar())),
    "Karaoke": (
        "Sing along: the Lyrics tab full-size, with the cover, the song and what's next in a strip across "
        "the top.",
        _with(panel_visible=False, browser_visible=False, page=3,
              panel3=_panel(["artwork", "title", "artist", "album", "upnext"], hidden=[]),
              panel3_visible=True, panel3_where="top", panel3_height=150,
              visualizer="off",
              bar=_bar({"top": ["seek"], "left": ["cover", "info"],
                        "center": ["back10", "prev", "play", "next", "fwd10"], "below": ["time"],
                        "right": ["lyrics", "cast", "mute", "volume"]},
                       icon_size="medium", icon_style="filled", play_style="ring", seek_style="cloud",
                       seek_handle="always", seek_times="none"))),
}

BUILTIN["Empty"] = (BUILTIN["Empty"][0], empty())
for _name, (_desc, _d) in BUILTIN.items():
    _d.setdefault("tabs", "all")  # built-ins show every tab


def capture(w, include_theme: bool = False) -> dict:
    """The window's current arrangement."""
    s = w.settings
    lib = w._library_panels() if w._on_tab_panel_page() else None  # Radio / Lyrics temporarily hide the others
    d = {
        "format": FORMAT, "version": VERSION,
        "panel": w._layout_panel_state(w.now),
        "panel_side": s.value("panel_side", "left"),
        "panel_visible": lib["left"] if lib else not w.now.isHidden(),
        "panel_width": _panel_width(w),
        "panel2": w._layout_panel_state(w.now2),
        "panel2_visible": lib["right"] if lib else not w.now2.isHidden(),
        "panel2_width": _panel_width(w, w.now2),
        "panel3": w._layout_panel_state(w.now3),
        "panel3_visible": lib["top"] if lib else not w.now3.isHidden(),
        "panel3_where": s.value("panel3_where", "top"),
        "panel3_height": w.now3.height() if not w.now3.isHidden() else int(s.value("panel3_height", 170)),
        "tab_style": w.tab_style(),
        "tabs": w.tabs_state(),
        "centre_visible": lib["centre"] if lib else not w.pages.isHidden(),
        "bar_visible": lib["bottom"] if lib else not w.bar.isHidden(),
        "bar": w.bar.state(),
        "browser": w.browser.fields(),
        "browser_visible": w.browser_visible(),
        "browser_height": w.lib_split.sizes()[0] if w.lib_split.sizes() else 260,
        "browser_widths": w.browser.split.sizes(),
        "columns_state": {key: t.column_state() for key, t in w._column_tables()},
        "visualizer": s.value("visualizer", "bars"),
        "library_view": ("artist" if w._artist_home() else
                         "albums" if w.lib_stack.currentIndex() == 3 else "list"),
        "library_home": "artist" if w._artist_home() else "",
        "album_covers": getattr(w.albums_page, "cover_size", "medium"),
        "artist_covers": getattr(w.artist_page, "cover_size", "medium"),
        "top": {"order": w.top_order(), "hidden": w.top_hidden(), "sizes": w.top_sizes()},
    }
    if include_theme:
        d["theme"] = {"mode": w.theme.mode, "accent": s.value("accent", "#5aa9ff"),
                      "accent_follow": s.value("accent_follow", True, bool),
                      "artwork_colours": w.artwork_mode(),
                      "artwork_background": s.value("artwork_background", "off")}
    return d


def _panel_width(w, panel=None) -> int:
    sizes = w.body.sizes()
    i = w.body.indexOf(panel or w.now)
    return sizes[i] if 0 <= i < len(sizes) and sizes[i] > 0 else (300 if panel else 330)


def apply(w, d: dict):
    """Arrange the window as `d` says; anything missing goes back to the default."""
    s = w.settings
    w._leave_tab_setup()  # on Radio or Lyrics, restore the layout's panels first
    # a panel the layout doesn't use starts empty
    panel = d.get("panel") if isinstance(d.get("panel"), dict) else _blank_panel()
    kept = {k: (w.now.order.index(k), w.now.heights.get(k)) for k in ("artists", "albums", "artist_info", "songs")
            if k in w.now.order}
    w.now.restore_state(panel)
    # The artist list and All albums are user-added: keep them unless the layout mentions them.
    for key, (at, h) in kept.items():
        mentioned = isinstance(panel, dict) and (key in (panel.get("order") or []) or key in (panel.get("removed") or []))
        if not mentioned and key not in w.now.order:
            w.now.add_block(key, min(at, len(w.now.order)))
            if h:
                w.now.set_block_height(key, h, save=False)
    w._save_panel_layout()
    side = d.get("panel_side", "left")
    s.setValue("panel_side", side if side in ("left", "right") else "left")
    w._place_panel(s.value("panel_side"))
    w.now.setVisible(bool(d.get("panel_visible", True)))
    w.bar.restore_state(d.get("bar") or _bar())
    w._save_bar_layout()
    fields = d.get("browser") or list(_default_panes())
    w.set_browser(fields, bool(d.get("browser_visible", True)))
    if d.get("browser_widths"):
        w.browser.split.setSizes([int(x) for x in d["browser_widths"]])
    states = d.get("columns_state")
    cols = d.get("columns")
    for key, t in w._column_tables():
        t._reset_columns()
        if isinstance(states, dict) and states.get(key):
            t.restore_column_state(states[key])
        elif key == "columns_library":
            t.restore_column_state(columns_state(t, cols if cols is not None else _DEFAULT_COLS))
    # None = the library's own order
    if "sort" in d:
        srt = d.get("sort")
        t = w.table
        col = t.model_.column_of(srt[0]) if isinstance(srt, (list, tuple)) and srt else -1
        if col >= 0:
            from PySide6.QtCore import Qt
            t.sortByColumn(col, Qt.DescendingOrder if len(srt) > 1 and srt[1] == "desc" else Qt.AscendingOrder)
        else:
            from PySide6.QtCore import Qt
            t.horizontalHeader().setSortIndicator(-1, Qt.AscendingOrder)
            t.model_.sort_col = -1
            t.model_.sort(-1)
    w._save_columns()
    # second panel: empty if the layout doesn't use it
    w.now2.restore_state(d["panel2"] if isinstance(d.get("panel2"), dict) else _blank_panel())
    w._save_panel2_layout()
    if "panel2_visible" in d:
        w.set_panel2_visible(bool(d["panel2_visible"]))
    # top panel: built-ins say whether it's on
    w.now3.restore_state(d["panel3"] if isinstance(d.get("panel3"), dict) else _blank_panel())
    w.settings.setValue("panel3_layout", json.dumps(w.now3.state()))
    if d.get("panel3_where") in ("top", "bottom"):
        w._place_strip(d["panel3_where"])
    if "panel3_visible" in d:
        w.set_panel3_visible(bool(d["panel3_visible"]))
        if d["panel3_visible"] and d.get("panel3_height"):
            h = int(d["panel3_height"])
            sizes = w.middle.sizes()
            i3, ip = w.middle.indexOf(w.now3), w.middle.indexOf(w.pages)
            tot = sum(sizes)
            sizes[i3], sizes[ip] = h, max(200, tot - h)
            w.middle.setSizes(sizes)
            s.setValue("panel3_height", h)
    if d.get("tab_style") in ("words", "icons", "both"):
        w.set_tab_style(d["tab_style"])
    if "tabs" in d:  # tabs shown, their order and names
        w.apply_tabs_state(d["tabs"])
    if d.get("follow") == "library":  # "Follow the tabs" song lists start on the library
        w._library_picked()
    # a layout can leave out the centre and bottom panels
    w.pages.setVisible(bool(d.get("centre_visible", True)))
    w.bar.setVisible(bool(d.get("bar_visible", True)))
    s.setValue("centre_visible", bool(d.get("centre_visible", True)))
    s.setValue("bar_visible", bool(d.get("bar_visible", True)))
    # A layout covers the whole window, so per-tab panels are reset.
    s.setValue("panels_by_tab", "{}")
    s.setValue("panel_visible", not w.now.isHidden())
    s.setValue("panel2_visible", not w.now2.isHidden())
    s.setValue("panel3_visible", not w.now3.isHidden())
    total = max(1, sum(w.body.sizes()) or w.body.width())
    pw = int(d.get("panel_width", 330))
    pw2 = int(d.get("panel2_width", 300)) if not w.now2.isHidden() else 0
    sizes = []
    for i in range(w.body.count()):
        x = w.body.widget(i)
        sizes.append(pw if x is w.now else pw2 if x is w.now2 else 0 if x is getattr(w, "now4", None)
                     else max(200, total - pw - pw2))
    w.body.setSizes(sizes)
    lib_total = max(1, sum(w.lib_split.sizes()) or w.lib_split.height())
    bh = int(d.get("browser_height", 260))
    w.lib_split.setSizes([bh, max(120, lib_total - bh)])
    viz = d.get("visualizer") or s.value("visualizer_style", "bars")
    in_panel2 = any(not p.isHidden() and "visualizer" in p.order for p in (w.now2, w.now3))  # or the top panel
    if "visualizer" not in w.now.order and not in_panel2:
        viz = "off"  # this layout leaves it out of the panels
    s.setValue("visualizer", viz)
    if viz != "off":
        s.setValue("visualizer_style", viz)
    w._apply_visualizer()
    # theme, if the layout includes one
    t = d.get("theme")
    if isinstance(t, dict):
        s.setValue("theme", t.get("mode", "dark"))
        s.setValue("accent", t.get("accent", "#5aa9ff"))
        s.setValue("accent_follow", bool(t.get("accent_follow", True)))
        mode = t.get("artwork_colours") or ("accent" if t.get("accent_follow", True) else "off")
        s.setValue("artwork_colours", mode)
        s.setValue("artwork_background", t.get("artwork_background", "off"))
        w.update_colours(force=True)
    page = d.get("page")
    if page == "albums":  # the Albums tab, or All albums in the Library if that tab was removed
        tab, ap = w._albums_tab_page()
        if tab is not None:
            if d.get("album_covers"):
                try:
                    ap.set_cover_size(d["album_covers"])
                except Exception:
                    pass
            w._go_page(tab)
            page = None
        else:
            d = dict(d, library_view="albums")
            page = 0
    elif page == "radio":
        page = 5
    elif page == "discover":
        w.open_discover(0)
        page = None
    elif page == "lyrics":
        page = 3
    if not isinstance(page, int) and page is not None and w.pages.currentIndex() == 3:
        page = 0  # leave the Lyrics page another layout opened
    if page is None and "page" not in d and w.pages.currentIndex() == 3:
        page = 0
    if isinstance(page, int):
        w._go_page(page)
    if d.get("library_view") == "albums":
        if d.get("album_covers"):
            try:
                w.albums_page.set_cover_size(d["album_covers"])
            except Exception:
                pass
        w.open_albums_page(in_library=True)
    back = bool(d.get("albums_back", True))  # the Albums layout has no "← Library" button
    s.setValue("albums_back", back)
    w.albums_page.back_btn.setVisible(back)
    for p in w.panels:
        w._fill_artist_list(p)
    home = d.get("library_home", "")  # the Artists layout uses the artist page as the Library
    s.setValue("library_home", home if home in ("artist",) else "")
    w.artist_page.back_btn.setVisible(home != "artist")
    if d.get("library_view") == "albums":
        pass
    elif d.get("library_view") == "artist":
        if d.get("artist_covers"):
            w.artist_page.set_cover_size(d["artist_covers"])
        w._go_page(0)
        w.open_artist_home()
        w._albums_mode = False
        s.setValue("albums_open", False)
    else:
        if w.lib_stack.currentIndex() in (2, 3):
            w._leave_artist_page()
        w._albums_mode = False
        s.setValue("albums_open", False)
    if d.get("library_view") in ("albums", "artist") and w.search.text().strip():
        w.lib_stack.setCurrentIndex(1)  # a search in the box shows its results
    top = d.get("top")
    if isinstance(top, dict) and isinstance(top.get("order"), list) and isinstance(top.get("hidden"), list):
        sizes = top.get("sizes") if isinstance(top.get("sizes"), dict) else {}
        w.set_top(top["order"], top["hidden"], sizes)
    else:  # the built-in layouts, and ones saved before layouts kept the top bar: the top bar as it comes
        w.set_top(list(w.TOP_DEFAULT), list(w.TOP_DEFAULT_HIDDEN), {})
    w._apply_tab_panels()
    w.apply_theme()


def _default_panes():
    from musicwell.widgets import DEFAULT_PANES
    return DEFAULT_PANES


def columns_state(table, keys: list[str]) -> list[dict]:
    """A column state showing `keys` in that order and hiding the rest."""
    known = [f.key for f in table.model_.fields]
    shown = [k for k in keys if k in known]
    return [{"key": k, "shown": True} for k in shown] + \
           [{"key": k, "shown": False} for k in known if k not in shown]


def load_user(settings) -> dict:
    try:
        d = json.loads(settings.value("layout_presets", "{}"))
        return d if isinstance(d, dict) else {}
    except (TypeError, ValueError):
        return {}


def save_user(settings, presets: dict):
    settings.setValue("layout_presets", json.dumps(presets))


_NOT_KEPT = ("format", "version", "library_view", "library_home", "description", "scratch")
_SIZES = ("panel_width", "panel2_width", "panel3_height", "browser_height", "browser_widths")


def load_changes(settings) -> dict:
    try:
        d = json.loads(settings.value("layout_changes", "{}") or "{}")
        return d if isinstance(d, dict) else {}
    except (TypeError, ValueError):
        return {}


def save_changes(settings, d: dict):
    settings.setValue("layout_changes", json.dumps(d))


def kept_changes(captured: dict) -> dict:
    """What's saved from the current window (not the page you're on)."""
    return {k: v for k, v in captured.items() if k not in _NOT_KEPT}


def fingerprint(captured: dict) -> str:
    """The arrangement without sizes that settle by themselves; equal means unchanged."""
    def strip(x):
        if isinstance(x, dict):
            return {k: strip(v) for k, v in x.items()
                    if k not in _SIZES and not (k == "width" and "key" in x)}
        if isinstance(x, list):
            return [strip(v) for v in x]
        return x
    d = kept_changes(captured)
    tabs = d.get("tabs")
    if isinstance(tabs, dict):  # layout tabs belong to every layout
        lay = {sp.get("id") for sp in tabs.get("custom") or [] if isinstance(sp, dict) and sp.get("kind") == "layout"}
        if lay:
            tabs = dict(tabs, custom=[sp for sp in tabs.get("custom") or [] if sp.get("id") not in lay],
                        order=[k for k in tabs.get("order") or [] if k not in lay],
                        hidden=[k for k in tabs.get("hidden") or [] if k not in lay])
            d = dict(d, tabs=tabs)
    return json.dumps(strip(d), sort_keys=True, default=str)


def effective(settings, name: str):
    """(layout, built in?, changed?) with your changes applied on top."""
    d, builtin = find(settings, name)
    if d is None:
        return None, builtin, False
    ch = load_changes(settings).get(OLD_NAMES.get(name, name) if builtin else name)
    if isinstance(ch, dict):
        return dict(d, **ch), builtin, True
    return d, builtin, False


def all_presets(settings) -> list[tuple[str, str, dict, bool]]:
    """(name, description, layout, built in?): built-ins first, then yours A–Z."""
    out = [(n, desc, d, True) for n, (desc, d) in BUILTIN.items()]
    for n, d in sorted(load_user(settings).items(), key=lambda kv: kv[0].lower()):
        out.append((n, d.get("description", ""), d, False))
    return out


def find(settings, name: str):
    for n, desc, d, builtin in all_presets(settings):
        if n == name:
            return d, builtin
    if name in OLD_NAMES:  # old built-in name
        return find(settings, OLD_NAMES[name])
    return None, False


def export_file(path: str, name: str, d: dict):
    data = dict(d)
    data.update({"format": FORMAT, "version": VERSION, "name": name})
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def import_file(path: str) -> tuple[str, dict]:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict) or data.get("format") not in (FORMAT, *OLD_FORMATS):
        raise ValueError("That isn't a Musicwell layout file.")
    name = str(data.pop("name", "") or "Imported layout")
    return name, data
