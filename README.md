# Musicwell

Musicwell is a music player and organiser, simple or fully customisable, with lyrics, radio,
Chromecast and Sonos. It plays your own music collection on Linux (MP3, FLAC, Ogg, Opus, M4A/AAC,
WAV and more), with album art, artist photos, synced lyrics and a visualizer.

Play it straight away: add your music folder and everything is there. Or unlock the window and put
the items where you want them — the album cover, the lyrics, the playback buttons, the seek bar,
the up next list — in the side panels, the panel across the top, the play bar or the top bar, at
any size. Switch between ready-made layouts (song list, albums, artists, vinyl record and more) or
save your own.

**Your music library**
- Song list with a column browser by artist, album, genre and year, like a classic jukebox
- Artist pages and all your albums as covers
- Ratings, likes, play counts and listening stats
- Smart search (for example artist=bowie year>1990) and custom columns from any tag
- Playlists, a play queue, shuffle and repeat

**Sound**
- 10- or 15-band equalizer with presets, gapless playback, crossfades
- Volume levelling with ReplayGain
- Media keys, the tray icon and your desktop's media controls (MPRIS)

**More than your own music**
- Internet radio with thousands of stations and what's playing now
- Lyrics, artist biographies, album covers and artist photos looked up for you
- Discover music like the song playing, and free music to stream
- Cast to Chromecast and play on Sonos speakers

Music on another drive (under /media or /mnt)? Allow it once with:
sudo snap connect musicwell:removable-media

Free software under the GPL (version 3 or later).

## Get it

**Snap Store:**

```bash
sudo snap install musicwell
```

or search for Musicwell in your software centre. For music on other drives (under `/media` or `/mnt`), allow
it once with `sudo snap connect musicwell:removable-media`. The snap keeps its own settings and library
(in `~/snap/musicwell`), separate from the AppImage's.

**AppImage** (no install): download `Musicwell-x86_64.AppImage` from the
[releases page](https://github.com/bobwellapps/musicwell/releases), then:

```bash
chmod +x Musicwell-x86_64.AppImage
./Musicwell-x86_64.AppImage
```

**From source** (Python 3.10+):

```bash
pip install --user .          # installs Musicwell and what it needs (PySide6, mutagen, numpy, ...)
musicwell                     # or: python3 -m musicwell
musicwell ~/Music             # adds a folder on first launch
```

**Windows** (Windows 10 or 11, 64-bit; no .exe — Musicwell runs from its Python files):

1. Install Python 3.12 or 3.13 (64-bit) from [python.org](https://www.python.org/downloads/windows/), ticking
   **Add python.exe to PATH**.
2. Unzip the Windows download anywhere (e.g. `Documents\Musicwell`).
3. Double-click **Install Musicwell.bat**. It puts Musicwell's Python packages (about 150 MB) in a folder of
   its own there (`.venv`) — nothing else on the PC is changed — and makes **Start-menu and desktop shortcuts**.
4. Start Musicwell from the shortcut (or double-click `Musicwell.pyw`). No console window opens.

Updates: copy the changed files over the old ones, as on Linux. Run *Install Musicwell.bat* again to update the
packages or remake the shortcuts. *Musicwell (show messages).bat* starts it with a console that shows any
error messages; *Remove Musicwell shortcuts.bat* removes the shortcuts (delete the folder to remove Musicwell).

On Windows, the library, playlists and settings are in `%APPDATA%\Musicwell` (settings in `musicwell.ini`),
downloaded covers, photos, lyrics and waveforms in `%LOCALAPPDATA%\Musicwell\Cache`. Everything works as on
Linux, except:
- **Media keys** work in the background too (Settings → Devices & desktop). If another program already has a key, that
  key works while Musicwell's window is active. Windows' own media pop-up (the volume flyout / lock screen)
  doesn't show Musicwell yet.
- **Notifications** are Windows notifications from the tray icon (the icon shows for a moment if it's off).
- **Chromecast:** the first time you cast, Windows asks whether Python may use the network — choose *Allow*
  (Private networks).
- *Open containing folder* opens File Explorer with the song selected.

## Welcome and setup

The first time Musicwell starts, a welcome window walks you through four steps:

1. **Welcome** — what Musicwell is.
2. **Your music** — *Use my Music folder*, or *Choose a folder…* (as many as you like; *Remove* takes one off).
   It shows how many songs it has found as it looks. You can also skip this and drag folders onto the window later.
3. **Layout** — a little picture of each layout: click one and the window behind changes to it, so you can see it.
4. **Theme** — every theme with a preview: click one to see it.

**Skip setup** closes it at any step (what you've picked so far stays), and *Start listening* finishes. Tick
**Don't show this again** to stop it opening when Musicwell starts — until you do, it opens each time. Open it
again any time from **Settings → Library → Welcome and setup…**.

## Layout

- **Top bar** — the tabs on the left; the search box, **Layouts**, **show / hide the panel** and **Settings** on the
  right, wherever the panel is (the panel button's icon shows which side it's on).
- **Right-click menus** all have the same shape: the song's, album's, artist's or station's name in bold at the
  top; then what you'd do with it (*Play*, *Shuffle*, *Add to queue*…); where to go from it (*Go to artist*,
  *Go to album*, **Discover ▸**); changing it (**Rating ▸**, **Image ▸**, *Edit tags…*); how the list looks in
  one **… options ▸** submenu; and anything that removes or deletes last. Right-click the empty space in a list
  for just its options.
- **Search, play, clear** — play a song from the search results and empty the box, and you're taken to that song:
  picked in the whole list, or (Albums, Artists layouts) its album or artist's page with the song found. Empty it
  (or click its ✕) without playing anything and you're back where you were — in the song list, at the same place
  you'd scrolled to, not the top.
- **Left panel** — the artist photo at the top (the whole photo, or right-click → *Fill the space*
  for a cropped banner), then the album artwork, an audio
  visualizer (bars, mirrored bars or wave — right-click it, or Settings; on by default), and track
  details (format, sample rate, bit depth, bitrate), star rating, play count and an *Up next* list.
  Switch it to the right side in Settings, or hide it with **F9**.
- **Column browser** — your choice of up to 6 columns from Genre, Artist, Album artist, Album,
  Composer, Year, Decade, Rating, Format and Folder, in any order (Ctrl/Shift-click for several values).
  Right-click a column header to change, add, move or remove it, or pick a ready-made layout;
  *Edit columns…* opens a full editor. Drag the dividers to resize — widths are remembered per layout.
  Hide the browser with **Ctrl+B** to use search alone.
- **Follows the music** — when a song starts, the song list (and the queue and playlist lists)
  jump to it and select it. It doesn't jump if the song is already on screen, and leaves a list
  alone for a few seconds after you've scrolled or clicked in it, and keeps your selection when
  you've picked several songs. Settings → Playback → *Scroll to the playing song*:
  **Highlight it** (its row is selected), **Show it in bold** (its whole row in bold) or **Off**. **Ctrl+J** jumps there any time. Pressing **Play** (the button, Space or the media key) also
  jumps the lists to the song — even one you've just been scrolling.
- **Song list** — sortable columns (click a header; third click returns to album order).
  Right-click a header to show or hide columns (Album artist, Format, Bitrate, Added,
  Last played, File…). Click the stars to rate.
- **Bottom bar** — shuffle, previous, play/pause, next, repeat (off / all / one), stop after
  this track, Chromecast, equalizer, queue, volume. Fully customizable — see below.
- **Colours from the album artwork** (Settings → **Theme**):
  - **Accent colour only** (the default) — the theme's colours, with highlights taken from the cover.
  - **The whole player** — backgrounds, panels, lists and text are tinted from the cover too, and
    change with every album. It stays light or dark like the theme you picked, so the text is
    always easy to read.
  - **Off** — just the theme's own colours.
- **Album artwork as the background** (Settings → **Theme**): the playing
  song's cover, softly blurred, behind the whole window. **Soft** gives a hint of the cover,
  **Strong** shows it clearly. Works with any theme and with the artwork colours above.
- **23 colour themes** — Dark, Light, OLED Black, Midnight, Nord, Dracula, Tokyo Night,
  Catppuccin Mocha and Latte, Rosé Pine, Gruvbox, Forest, Ember, Solarized Dark and Light, Paper, and the bright Daylight, Sky, Mint, Sunrise, Lilac, Bubblegum and Lemon.
  Settings → **Theme** shows a preview of each and switches as you click (Cancel puts the old one
  back); or use the layouts button → **Colour theme**. Each theme has its own accent colour, used
  when the colours don't come from the artwork. A saved layout can carry its theme and artwork
  colour setting too.

## Stats

The **Stats** tab (**Ctrl+5**) has three views — **Library**, **Radio** and **Library + Radio** — and
the period for all of them: **All time**, **This year**, **Last 30 days** or **Last 7 days**. The view
you used last is remembered.

**Library:** plays, listening time and your listening streak; songs, artists and albums in your library;
listening over time; top artists, albums and songs (click an artist for their page, an album to show it,
a song to show it picked where it is in your library — in every layout — and double-click a song to play it;
what's playing carries on); genres; the time of day and day of the week you listen; your library by decade and file format;
and the songs you skip most. "All time" uses the play counts every song already has; the charts by day
and hour use the listening history. The radio never changes your songs' play counts.

**Radio:** time listened, how many stations (and how often you tuned in), songs heard, **New to you**
(artists the radio played that aren't in your library), songs you ♥ Liked and your radio streak; radio
listening over time; **Top stations** (click one to tune in); the artists and songs you heard (marked
when they're in your library: click to show or play them); station genres; the countries the stations
are in; time of day and day of the week; and the songs you heard most recently, with the station.
Only time actually playing counts (paused or reconnecting doesn't), and anything heard for less than
30 seconds isn't counted as a song, and neither are advert breaks, jingles and station IDs however long they
run, the news, show names, the station's own name or slogan, phone numbers and web addresses. If something
still gets through (an advert sent as "Sofology - Sofa Sale" looks just like a song), right-click it in
*Songs you heard* or *Recently heard* → **Not a song**: every time it was heard comes out of the stats, and
it's remembered as an advert on that station.

**Library + Radio:** both together by listening time — the total, how it splits between your music
and the radio, the streak and days with any music, listening over time, time of day and day of the week
(library and radio stacked, in two colours), top artists (plays of your songs plus songs heard on the
radio) and genres.

**Clear stats…** (top right of the Stats page) starts again: choose the listening history, every song's
play count, skip count and "last played", and/or the radio listening. Ratings, playlists, favourite
stations, ♥ Liked songs and your music are kept. It asks once more before clearing, as it can't be undone.

## Volume levelling (ReplayGain)

Settings → **Playback → ReplayGain** uses the ReplayGain tags in your files, so a quiet 1970s
album and a loud modern one play at a similar volume. Your files aren't changed.

- **Track** — every song at the same loudness.
- **Album** — the album as a whole is levelled, so its quiet songs stay quiet.
- **Auto** — Album while playing in order, Track while shuffling.
- **Pre-amp** — ReplayGain usually makes music a bit quieter; raise this if everything sounds too quiet.
- **Songs without tags** — play them this much quieter (or louder); about −6 dB often matches tagged
  songs. Settings shows how many of your songs have ReplayGain tags.
- **Prevent clipping** uses the peak tags, so a song is never raised so far that it distorts.

(Pre-amp, Songs without tags and Prevent clipping show once ReplayGain is on.)

Opus files' own R128 gain tags are used too. The level applied to the playing song shows with its
audio details in the now playing panel (e.g. *ReplayGain −6.0 dB*). Radio and online songs aren't
changed, and neither is the sound sent to a Chromecast. The level switches exactly where songs meet,
so gapless albums stay gapless.

## Fades

Settings → **Playback → Crossfade**:

- **Fade in** at the start of each song and **Fade out** at the end (Off, or 1–12 seconds).
- Songs of the **same album** flow straight into each other unless you tick *Fade between songs on
  the same album* — so live albums, DJ mixes and gapless albums stay seamless.
- **Fade on pause and skip**: a short fade (0.15–1 s) instead of a quick cut. Even when it's off, pausing,
  skipping and seeking never click: the sound is taken down over a few hundredths of a second (too short to
  hear as a fade) and what comes next starts from silence. **Next** on the last song stops straight away.
  Starting another song while paused (double-clicking an artist, an album or a song) plays it at full volume.

Note: fades don't work while casting.

**Albums on more than one CD** are one album everywhere — the All albums covers, the artist page, the
column browser's Album column and the covers: an album tag like *Abbey Road (Disc 1)*, *The Wall CD2* or
*Summer Hits [CD 2 of 2]*, and folders like `Album/CD1` or `Album CD2`, all count as the one album, shown
with "2 CDs" under its cover; the cover can sit in the album's folder above the CD folders. (*Greatest Hits
Vol. 2* or *… Part 2* stay albums of their own.) The song list's Album column still shows each file's tag.

## Layouts, Settings and edit mode: where things are

- **The Layouts button** (top right) — switch layouts, *Reset layouts* (one, the Radio or Lyrics tab, or every
  layout), and *Save and manage layouts*: New empty layout, Save, Update, Manage. Unlock is there too.
- **How the window looks** — panels, the play bar and its look, the visualizer, tabs, outlines — is changed in
  the window itself: unlock it (**F2**, or Layouts → Unlock) and right-click what you want to change. Panels are also
  in the panels button. Colours are in Settings → **Theme**.

**Settings** (the cog) has seven pages, each in short sections with the names other music players use (hover
over a setting for more about it; choices that only matter once something is switched on appear when you
switch it on): **Library** (music folders, years), **Playback** (crossfade, volume, while playing), **Radio**
(stations, songs in your library, adverts, song alerts), **Search** (library, online results, online sources,
radio), **Online** (covers and artist photos, artist information, lyrics), **Devices & desktop** (casting,
desktop) and **Theme** (every theme with a preview, album art colours, accent colour). How the window looks — panels,
play bar, tabs, the cover, the visualizer, the song list's columns, the column browser, custom fields, bold
column headers — is set in the window itself: right-click things while it's unlocked. **Library** also has
**Welcome and setup…**, which opens the welcome window again. The **Search Settings** box at the top finds any option by a word ("fade", "tray",
"port"…): the results fill the window, and clicking one goes straight to it.

**Panels for each tab:** showing or hiding a panel (any of the five) while you're on a tab is kept for
that tab — the Radio tab can have the top panel while the Library doesn't. Tabs you haven't changed have the
Library tab's panels. The panels menu → **Same panels as the Library tab** puts a tab back.

## The five panels

The window is made of five panels, and each can be added or taken away:

| Panel | What it is |
|---|---|
| **Top Panel** | A strip across the top of the window (Ctrl+F9) — the same items as the side panels, side by side |
| **Centre Panel** | The tab you're on — the song list, albums, radio, Discover… |
| **Bottom Panel** | The play bar |
| **Left Panel** | A panel down the left (F9 or Shift+F9, whichever side panel it is) |
| **Right Panel** | A panel down the right |

Add or remove them from the **panels button** (top right), or by right-clicking: the play
bar, any panel and the top bar have a **Panels** list, and right-clicking an empty part of the window lists them
straight away (handy in the **Empty** layout). Clicking a tab while the Centre Panel is hidden brings it back.
*Swap the Left and Right Panels* is in the panels button's menu.

**The Top Panel** holds the same items as the side panels — cover, title, artist, album, rating, up next, lyrics,
the artist list… — side by side, scrolling sideways when they don't all fit. Unlock to drag items into it, along
it and out of it, or right-click → **Add here**. Drag its lower edge to make it taller or shorter. Unlocked, each
item in it has a grip on its **right edge**: drag it to make the item wider or narrower (double-click: back to its
own width). In the side panels items fill the panel's width — drag the panel's own edge to change that.

**Unlocked, every panel shows:** a dotted outline with its name (Left Panel, Top Panel, Centre Panel…) — and, if
it's empty, how to fill it — just as the play bar (the Bottom Panel) shows its areas. The **Empty** layout opens
unlocked, ready to build in.

**Removing things with Delete:** while unlocked, point at an item — in a panel, in the play bar, a button along
the top, or a tab — and press **Delete** to remove it (the same as right-click → Remove). Typing in a box isn't
affected: there Delete deletes text.

## Layouts

Click the **Layouts** button next to Settings to switch
the whole window between arrangements — the now playing panel, the bottom bar, the column browser,
the song list columns, the size of each area and the visualizer style. **Ctrl+Alt+1…9** switches
straight to the first nine.

Built in (a new set that shows what Musicwell can do — the panel across the top, two side panels, the Albums
tab, tabs as icons):

| Layout | What it is |
|---|---|
| **Default** | The song list (Artist, Title, Genre, Album, Year, Time — sorted by album, no column browser) with the panel on the right: the artist photo, the cover, the title, artist, album and year, the rating, a wave visualizer and ♥ Like, all centred; the tabs with icons and words. The play bar has the cover, the song, the usual buttons, a waveform seek bar and, on the right, stop after this song, cast, equalizer, queue, mute and volume. A new Musicwell starts with this one |
| **Albums** | Switch to it while a song plays and it goes to that album and finds the song in the list below. The Library tab is every album as small covers (albums list in the order you pick them — the first at the top, each one you add underneath — and play in that order; + on a cover while music plays adds its songs to the end of what's playing — always under the albums already there, whatever's playing and however short the first album is — and the list below stays on the song playing (or at its top, with nothing playing from here) while a note in the accent colour pops up over the songs for a few seconds — *Added "Album name" (4 songs) to bottom of list* (just *Added "Album name" (4 songs)* when it's the only album in the list) (click it to hide it); **Clear all** empties the list below (the song playing finishes, then nothing more plays from here); − takes an album out but never stops the song that's playing; the list and its order come back after a restart; click one for its songs below (it has + on it, so you can add it straight away) — once you've added albums with + (or while an album plays), that's just to look and your list stays as it is: the blue **↩ Back to your list** button, or clicking one of your albums, brings it back; the blue **▶ Show what's playing** button or clicking the playing album (▶) brings back what's playing, with its cover picked again; + and − on the covers pick what plays) — it's the Library page here, so there's no ← Library button: clicking Library, Esc and leaving an artist's page all come back to the covers, and the search box at the top finds songs as in every layout (the covers have their own filter box for albums and artists; empty the search and you're back on the covers — on the album of a song you played from the results). The same panel on the right and play bar as Default; tabs with icons and words |
| **Artists** | Switch to it while a song plays and it opens on that song's artist, with *All songs* listed and the song found in it. The Library tab is an artist's page — their photo, name, Play / Shuffle / Add to queue, their albums as covers, with *All songs* first showing four small squares with a small gap between: the covers of the first four albums (oldest first), each once, and empty squares when there are fewer (click one for its songs below; + and − on the covers pick several albums and change what's playing — albums list and play in the order you add them, each new one at the bottom, with the same *Added …* note as the Albums layout; after **Shuffle**, + and − keep the shuffled order and new songs go at the end) and the songs. Every album artist is down the left with their photo and a filter box; click one to open their page. It's the Library page here, so there's no ← Library button: clicking Library, Esc and leaving an album page come back to the artist you were on (the one playing, or the first, the first time), and the search box at the top finds songs as in every layout (the artist list has its own filter box; empty the search and you're back on the artist — or on the artist of a song you played from the results, with the song found). On the right, centred: the lyrics, the title, artist, album and year, the rating, a bars visualizer, ♥ Like and up next. The play bar like Default's with a slider seek bar; tabs with icons and words |
| **Overload** | Everything at once: the artist's photo, about the artist and up next on the left; a big visualizer across the top; the column browser (genre, artist, album) and a full song list in the middle; the cover, the song, the rating and the lyrics on the right; tabs as words |
| **Minimal** | Tabs as icons, a slim Top Panel with the cover, artist, title and rating, the song list (Artist, Title, Album, Year, Time), and a slim bar: a thin seek line across the top, previous / play / next in the middle, shuffle, repeat, mute and volume on the right |
| **Organiser** | Library first: five browser columns (artist, album, genre, year, decade) over lots of song columns (artist, #, title, genre, album, disc, year, time, plays, format, bitrate, rating), no side panels, and a play bar with a big cover, previous / play / next / stop, a waveform seek bar, and shuffle, repeat, stop after, equalizer, queue, mute and volume; tabs as words |
| **Vinyl** | A record player: the cover as a spinning record with the title, artist and album under it, kept in the middle of the panel; a plain song list on the left (Artist, Title) set to *Follow the tabs* — it starts on your library, and Library or a playlist tab shows there; just the Library and Playlists tabs, with icons and words; the play bar with a big cover, the usual buttons, a waveform seek bar with the time left, and cast, equalizer, volume and mute |
| **Empty** | Nothing at all — none of the five panels, just the tabs. Right-click the window to add panels, unlock to fill them: right-click the play bar or a panel → Add here, right-click the song area → Columns; then *Save current layout as…* |

(Musicwell Default became **Default**, Track List and Compact **Minimal**, Full Monty and Everything **Overload**, Album Gallery **Albums** and Organizer **Organiser**; Stage, Radio Lounge, Discover and
Karaoke are set aside for now. Layouts change the arrangement — including the top panel and whether the tabs are words or icons
— not your theme or colours. Switching layout gives every tab the layout's panels — except the **Radio** and **Lyrics** tabs, which
have panels of their own (below).)

**Panels a layout doesn't use start empty:** show one (the panels button, top right, or right-click the window)
and it's blank, ready for you to unlock and fill — nothing is carried over from another layout.

**Your changes are remembered for each layout:** add a panel, fill it, move things, change the play bar, the
columns or the tabs, and that layout keeps it — switch to another layout and back (or quit and start again) and
it's as you left it. The built-in layouts come with just their own tabs: a playlist (or search, or All albums) tab you add
shows only in the layout you added it to — that layout is then *changed* — or in a layout you save yourself.
The Layouts menu shows *(changed)* next to a layout you've changed. The song list's height — under the column browser, the
album covers or the artist — stays where you drag it, for each layout and after you quit and start again. **Layouts → Reset layouts** puts one
back as it came (a layout of yours goes back to how you saved it), puts back the Radio or Lyrics tab's panels,
or — **Every layout…** — all of them at once.

**The Radio and Lyrics tabs' panels:** whatever the layout, these two tabs have their own panel on the right —
the artist's photo, the station's logo (or the cover), the visualizer, the song (*Live on* the station) and
♥ Like — and, if you add them, their own Left Panel and Top Panel, which start empty. Each tab has its own: what you
change on the Radio tab (items, panels, the panel's width) doesn't change the Lyrics tab, and the other way
round — and neither changes the layouts (the layout's panels come back when you leave those tabs). Right-click a panel → This panel → *Move it to the other side* (or drag it) to swap the
tab's own panel and its extra one — each tab keeps its own sides. Right-click the
panel on the right → *Reset the Radio tab's panels* (or Lyrics), or Layouts → Reset layouts → *Radio tab* /
*Lyrics tab*.

**Tabs in layouts:** a layout you save remembers which tabs are shown, their order and their names, and
your own tabs. Using it again puts them back as they were: a tab of your own that you've deleted since comes
back, and tabs you've made since are hidden (not deleted — + or *Arrange tabs* shows them again). The
built-in layouts show every tab and leave the order as it is. Layouts saved before this keep the tabs as
they are.

**Search history:** Discover → Search online keeps your searches — **Recent** (next to Filters) lists them, newest
first, with where you looked (Artist, Genre…) and when; click one to search it again. As you type, earlier
searches that match are offered too. **Clear the search history** is at the bottom of the list.

**Save current layout as…** keeps your own (optionally with the theme and accent colour);
**Update “…”** saves changes into the layout you're using. **Manage layouts…** renames, deletes,
and **exports** / **imports** layouts as `.musicwell-layout` files to back up or share.

**New empty layout…** (in the Layouts menu) starts from the **Empty** layout — no panels, nothing in the play bar, no song columns —
under a name you choose. It opens **unlocked**: Panels (top right) for the panels, right-click the play bar or a
panel → **Add here**, right-click the song area → **Columns**, and drag things where you want them. Press F2 (or Layouts → Lock) and
it's saved; while it's the layout in use, every later lock saves it again. Want a **second panel**? The
panels button at the top right (or Shift+F9) shows the left and right panels.

## Lyrics

Open the **Lyrics** tab (or **Ctrl+L**, or the microphone button if you add it to the bottom bar).
Synced lyrics highlight the line being sung and scroll with the song; **click a line to jump
there**. Scroll with the mouse wheel to look ahead — following resumes after a few seconds.
Plain lyrics (words without timings) show as text with a **Not synced** label above them, so it's clear they won't move with the song. The now playing panel has a smaller **Lyrics** item too (move or remove
it like any other item); it only appears when the song has lyrics.

**Synced lyrics on the radio:** a station says which song is playing but not how far into it you are, so
Musicwell times the lyrics from the moment the song changes. The song you **tune in to** is already
part-way through. Its lyrics show without a highlight until you **click the line being sung**, and then
they follow along. From the next song on, they sync by themselves. If a station's songs always run a
little early or late, use *Show lyrics 0.5 s earlier / later* (right-click the lyrics). That is
remembered for the station.
The first time you open the Lyrics tab while a station plays, a short note explains this (and that
not every song can be synced: some only have plain lyrics, some have none, and some stations change the
title a little early or late). Tick **Don't show this again** to stop it appearing.

Where they come from, in order:

1. a `.lrc` or `.txt` file next to the song with the same name (`03 Song.flac` → `03 Song.lrc`)
2. lyrics saved inside the file (MP3 USLT/SYLT, FLAC/Ogg `LYRICS`, M4A, WMA, APE)
3. **LRCLIB** (lrclib.net) — a free, open lyrics database, no account needed. Found lyrics are
   cached in `~/.cache/musicwell/lyrics`; switch this off or have them saved as `.lrc` files next to
   your songs in Settings → **Lyrics**.

If the timing is off, use **Earlier** / **Later** on the Lyrics page (0.5 s steps, remembered per
song). Musicwell already allows for the delay of your sound card. The **⋯** menu (or right-click the
lyrics) has *Load a lyrics file…*, *Search online again*, *Copy lyrics* and *Save as .lrc next to
the song*.

## Customize the window: unlock it

Press **F2**, or click the **Layouts** button → **Unlock** (the song list's column headers offer it too when
right-clicked). Musicwell starts **locked**: nothing can be moved by accident.

Once **unlocked**, Everything you can arrange gets a **faint outline** and an **open hand** under the
mouse (a closed hand while you carry it), and the window still works as normal — play, click, scroll:
- **Drag** a panel item, a play bar item, a tab, a song list column header, a column browser column (by its
  title) or a **button along the top** (the song count, search box, All albums, Layouts, Panels,
  Settings) to move it. Items in a list (the artist list, lyrics…) and sliders show a small **⠿** grip to drag
  by when the mouse is over them. Panel items can go into the other panel too.
- **Drag something out** (off the panel, the play bar or the top bar) to remove it.
- **Right-click → Add here** puts it back where you clicked — in a panel (also a **Space** or a **Divider
  line**), in the play bar (also a **Flexible space** or a **Gap**) or along the top.
- **The whole play bar:** drag it by an empty part of it to the top or the bottom of the window.
- **A whole panel:** drag **⠿ Move panel** (at the top of the panel while the mouse is over it) to the other
  side of the window — or right-click → This panel → Move it to the other side.
- Drag the **bottom edge** of a panel item to make it taller or shorter (double-click it: back to its own
  size), and the edges between the panel, the song list and the column browser.
- Right-click anything for its options, then **Remove**; the panel's and the play bar's own options are under
  **This panel** and **The play bar's look**.
- Prefer the window to look exactly the same while unlocked? Right-click the top bar → untick **Show outlines
  while unlocked** (the open hand still shows what can move).
- Hiding the song count keeps messages: they still show there for a moment.

Press **F2** or **Esc** again (or Layouts → Lock, or right-click the top bar → Lock) to lock. A layout you started with **New empty layout…** is saved each time you lock. Switching to another layout while unlocked locks first, so every layout starts locked.

**Keyboard shortcuts:** Settings → **Keyboard** lists every shortcut (play/pause, next, lock/unlock, search, the panels, **F5** to rescan your music folders for new and changed songs, **Ctrl+F5** to reload the cover and artist photo…). Click a box and press the keys you want, **Clear** removes one, and **Reset all** goes back to the usual keys. Keys used twice are kept for the first and removed from the other.

**♥ next to the playing song** (an empty outline, solid once liked; in the play bar, just after the title; unlock to drag it elsewhere or off the bar — and it can go in either panel too: unlock, right-click the panel →
**Add here** → *♥ Like*): for your own songs, ♥ puts the song in your **Favourites** — it
rates it 5 stars, so the Favourites tab (+ → Favourites) lists it; ♥ again takes it out and puts back the
rating it had. For songs on the radio and online songs, ♥ keeps the song in **Radio → ♥ Liked**.
**Ctrl+Shift+L** does the same.

## Moving things around

Everything in the window is an item you can put where you like — in the side panels, the panel across the
top, the play bar or the top bar. Unlock first (F2).

**Moving:** drag an item to where you want it. It can go from one panel to another, from a panel into the
play bar, from the play bar into a panel, and to and from the top bar. Dragging moves it; drag it off
everything to remove it.

**Adding:** right-click where you want it → **Add here**. Besides the items that belong there, the menu has
*From the play bar*, *From the panels* and *From the top bar*. *Add here* adds another one, so an item can be
in more than one place at once — say a small cover in the play bar and a big one in a panel. Each keeps its
own size; the style (square cover or spinning record, bars or wave) is the same everywhere.

**What can go where:**
- **Play bar controls** (play / pause, next, shuffle, the seek bar, the time, volume, Stop after this song,
  cast, equalizer, queue and the rest, all the **Playback buttons** as one item, and **Title and artist**)
  can go in any panel or along the top bar. A control works and looks the same wherever it is, and copies
  stay in step (the volume, shuffle and repeat, the seek bar's position).
- **Panel items** (artist photo, song title, artist, album, audio details, play count, extra fields, up next,
  lyrics, Playing on, the artist list, All albums, the song list) can go in the play bar. There each starts
  small; drag its corners to resize it. Lyrics and *Playing on* only show while there's something to show.
- **The top bar** takes its own items (the search box, the song count, the All albums, Layouts, Panels and
  Settings buttons), play bar controls, and the small panel items — song title, artist, album, audio details,
  play count and Playing on. Bigger ones belong in the panel across the top (Ctrl+F9). A search box in a
  panel searches like the one at the top, and Ctrl+F goes to it if the top one isn't there.
- **The visualizer, album cover, rating, ♥ Like and About the artist** go anywhere.
- **Spaces:** a play bar gap dragged into a panel becomes a panel space, and a panel space dragged into the
  play bar becomes a gap.

**Sizes:** every item that can be resized has handles on both sides. In a side panel, drag an item's top or
bottom edge (the visualizer's left or right edge sets its width); in the top panel, its left or right edge;
in the play bar, a grip in each corner; along the top bar, the right edge of anything you've added there (and
of the search box). Double-click a handle for the item's own size.

**Removing:** drag it off, right-click → Remove, or point at it and press **Delete** — in the panels, the
play bar and the top bar alike.

**Text size:** right-click an item with text → **Text size** → *Smallest* to *Largest*. That's the song
title, artist, album, audio details, play count, extra fields, lyrics, up next, the lists, About the artist,
the artist's name on the artist photo, Title and artist, the time and the search box — and the Lyrics tab
and the song lists too. Each item keeps its own size in each place, and layouts keep it.

**Undo:** **Ctrl+Z** puts back the last change and **Ctrl+Shift+Z** does it again, up to 50 steps (also in
the **Layouts** menu). It covers items moved, added or removed, sizes, text sizes, alignment, panels shown or
hidden, the edges between the panels, and the song list's columns. Switching to another layout starts
afresh. In a box you're typing in, Ctrl+Z undoes your typing first.

**Layouts remember it all,** the top bar included (what's on it, in what order, and the sizes). The built-in
layouts, and layouts saved before they kept the top bar, have the top bar as it comes — so **Reset layouts**
puts the top bar back too. While you drag an item over the top bar, a line shows where it will go.

## Customizing the play bar

**At the top or the bottom:** the play bar (play, seek, volume…) sits at the bottom of the window,
or at the top, under the tabs — drag it there while unlocked, or right-click the play bar while unlocked → *The play bar's look* → *Position*.
A full-width seek line in the top strip moves to the bar's lower edge when the bar is at the top, so
it always borders the music. Saved layouts remember where you put it; the built-in layouts leave it
where it is.

Unlock (F2) and the bar shows its five areas — **top strip**, **left**, **centre**,
**under the centre** and **right**. Drag items between areas, drag one out of the bar to remove it,
right-click → **Add here** to bring one in. Right-click → **The play bar's look** → **Reset the play bar**
for the original bar.

**The visualizer** can go in any area of the play bar (empty ones show while you drag) or any panel. In the play bar, drag any of its four corners to make it longer or shorter, or right-click it (unlocked) → **Fill the width** to stretch it across its area; in the **top strip** that's the whole width of the window.

Items: album cover, title and artist, shuffle, previous, back 10 s, play/pause, stop, forward 10 s,
next, repeat, seek bar, time (`1:23 / 4:56`), stop after this song, rating stars, lyrics, show
playing song, Chromecast, equalizer, queue, panel toggle, mute, volume, visualizer, plus as
many **flexible spaces** and **gaps** as you like (right-click a gap → Wider / Narrower).
**The Bottom Panel's height:** drag its top edge (the edge facing the music — the bottom edge when the play
bar is at the top of the window) to make it taller or shorter, like the Top Panel's edge; the items stay in
the middle. It never gets shorter than what's in it. Double-click the edge for its own height. The height is
saved with the play bar and in layouts.

**The album cover in the Bottom Panel:** unlock and drag any of its **corners** to make it bigger or
smaller (it stays square; the play bar grows to fit). Double-click the corner for its own size, which
follows the play bar's icon size. Saved with the play bar and in layouts.

**About the artist** can go in the Bottom Panel too (unlock, right-click the play bar → Add here → About the
artist): the same text from Wikipedia as in the side panels, in a box. Drag any of its **corners** while
unlocked to make it wider, narrower, taller or shorter (double-click: its own size); the seek bar makes room.
Right-click it (locked) for *Open on Wikipedia*, *Look up again* and *Copy*.

The **visualizer** in the Bottom Panel is the full one — bars, mirrored bars or wave, the same style as the
other panels (right-click it to change the style, or *Hide visualizer* to take it out of the play bar).
While unlocked it has a grip in each **corner**: drag one to make it wider, narrower, taller or
shorter (double-click: its own size).

**The play bar's look** (right-click the bar while unlocked):

| Option | Choices |
|---|---|
| Icon size | Small, Medium, Large |
| Icon style | Filled, Outline, Thin, Bold |
| Play button | Filled circle, Outlined circle, Plain icon |
| Seek bar | Slider, Thin line, Thick bar, Dotted, Segments, Waveform, Waveform bars, Waveform bars growing up |
| Seek bar handle | Always shown, When the mouse is over it, Never |
| Times beside the seek bar | Elapsed and total, Elapsed and time left, Elapsed only, None |

The three **waveform** styles draw the real shape of each song — loud and quiet parts — so you can
see where the chorus or the quiet bridge is and click straight to it; hovering shows where you'd
land. Each song is measured once in the background (a second or two) and remembered in
`~/.cache/musicwell/waveforms`. With a waveform seek bar the volume slider becomes a wedge.

Click the total time to switch it to time left. Put the seek bar in the top strip for a
full-width bar along the top edge.

## Smooth playback

About 2.5 seconds of music is prepared ahead and handed to the sound system, which plays it on by
itself — so the music doesn't stop when the window is busy for a moment (opening Settings, switching
theme), and the sound output gets a turn every millisecond even while the window is working. Switching
theme takes about a quarter of a second; clicking or arrowing through several themes in
Settings quickly only shows the one you stop on. Files are prepared at double speed until that cushion is full; the sound itself isn't changed.
Volume, mute and pause still act at once, and skipping or seeking clears the cushion, so you never hear
the old song. While the Equalizer window is open the cushion shrinks to about half a second, so the
sliders are heard straight away. The play bar, lyrics and the desktop's media controls show what you're
actually hearing, and the window moves on to the next song when it starts to play.

## Equalizer

**Ctrl+Shift+E** or the slider icon in the play bar. **10 or 15 bands** (±12 dB) plus a preamp, with a
live response curve. **Bands** (top of the window) switches between 10 bands an octave apart (31 Hz – 16 kHz)
and 15 bands ⅔ of an octave apart (25, 40, 63, 100, 160, 250, 400, 630 Hz, 1, 1.6, 2.5, 4, 6.3, 10, 16 kHz)
for finer control. Switching keeps the sound the same: the new sliders are set from the curve you had.
Every preset works with both, including your own and imported ones. 16 built-in presets (Rock, Jazz, Bass boost, Vocal,
Headphones, Late night…) and your own: set the sliders, then **Save…**. Double-click a slider
to reset it.

**Import/Export** (top right of the Equalizer window) moves presets in and out:
- **Import presets…** — pick one file or several. Reads Musicwell preset files
  (`.musicwell-eq`), EqualizerAPO / AutoEq text (both the `GraphicEQ:` line and parametric
  `Filter …` lines — so AutoEq headphone corrections work directly), Winamp `.eqf` / `.q1`
  files and **MusicBee** `.sde` presets (found in `%AppData%\MusicBee\Equaliser` on Windows, or the
  `Equaliser` folder of a portable MusicBee; pick a whole folder's worth at once). A 15-band MusicBee preset
  comes across exactly with Musicwell on 15 bands, and a 10-band one on 10; MusicBee's left and right
  settings are averaged, as Musicwell's equalizer is the same on both sides. Other EQs use different bands, so the curve is measured at Musicwell's bands (10 or 15, whichever
  you're using).
  Imported presets join your own in the Preset list and the first one starts playing.
- **Export “current”…** / **Export all my presets…** — a `.musicwell-eq` file to back up or share (with the
  10 or 15 bands you're using; either kind imports into both).
- **Export for EqualizerAPO / EasyEffects (GraphicEQ)…** — the current curve as a GraphicEQ
  text file, for EqualizerAPO, EasyEffects, Wavelet and others.

How it works: the decoded audio runs through a linear-phase FFT filter and a soft limiter on
its own thread, then to the sound card. Because that output stays open between songs, albums
also play **gapless** now. The EQ needs numpy (bundled in the AppImage); without it Musicwell
plays normally with the EQ greyed out. `MUSICWELL_NO_EQ=1` switches back to Qt's plain output.

## Chromecast

Click the cast icon in the play bar and pick a speaker, speaker group or TV (Chromecast,
Google/Nest speakers, Cast-enabled TVs on the same network). The song carries on there from
the same point; play/pause, seek, next, the queue, ratings and play counts all keep working, and
the volume slider controls the speaker.

The cast menu stays open while it looks: speakers and TVs appear as they're found ("Searching…" shows
while it's looking), and **Search again** looks again without closing the menu. Nothing found? It says
so, with a reminder to check they're on and on the same network; **Casting settings…** opens Settings →
Devices & desktop (finding Chromecast / Sonos, a Sonos address, the port).

To stop casting, click **Disconnect** next to "Playing on …" in the left panel, or open the cast
menu: **Disconnect from …** stops the speaker and leaves the song paused here at the same point;
**Disconnect and keep playing here** carries straight on through this computer's speakers.

- The speaker fetches each song from Musicwell over your network (port **8770**, changeable in
  Settings). If you run a firewall: `sudo ufw allow 8770/tcp` (or the firewalld equivalent).
- MP3, FLAC, AAC (M4A), Ogg Vorbis, Opus and WAV can be cast. ALAC, AIFF, WMA, APE, WavPack and
  DSD can't be played by Cast devices, so those songs are skipped with a message.
- The EQ only applies to this computer's speakers. The visualizer keeps going while casting:
  Musicwell decodes the song silently in step with the speaker.

**If a speaker connects but won't play:** the speaker couldn't download the song from your
computer — almost always a firewall blocking port 8770, or the two being on different networks
(VPN, guest Wi-Fi, router "client isolation"). Musicwell detects this and tells you the exact
command for your firewall. Everything about casting is logged to `~/.cache/musicwell/cast.log`.

## Sonos

Sonos speakers are in the same cast menu as Chromecasts — one entry per room, or per group of
rooms (e.g. *Kitchen + Lounge · Sonos group*: every speaker in the group plays). Pick one and the
song carries on there from the same point, exactly like casting to a Chromecast: play/pause, seek,
Next/Previous, media keys, the queue, ratings and play counts keep working, and the volume slider
controls the room's (or the whole group's) volume. The title, artist, album and cover show in the
Sonos app.

- **What plays as it is:** MP3, FLAC and ALAC up to 24-bit/48 kHz, AAC (M4A), Ogg Vorbis, WAV and
  AIFF. **Hi-res** files (above 48 kHz, e.g. 24/96 or 24/192) and formats Sonos doesn't know (Opus,
  WavPack, APE…) are converted to CD-quality WAV on this computer first — a moment's wait before the
  song starts ("Getting … ready"). An older **S1** system that won't play a 24-bit file is spotted
  and the song converted automatically.
- **Radio** stations are played by the speaker straight from the station (shown as radio in the
  Sonos app; Pause stops the stream and Play tunes in again). **Online songs** (Internet Archive,
  Openverse, Audius, your sources) are passed through this computer.
- If someone picks something else in the Sonos app, Musicwell notices, stops casting and carries
  on here, paused.
- Same limits as Chromecast: the EQ, volume fades and levelling only apply to this computer's
  speakers; there's a short gap between songs; this computer must stay on while it plays; and the
  speaker fetches the music from port **8770** — allow it in your firewall
  (`sudo ufw allow 8770/tcp`).
- **Speakers not found?** Some networks block the way Sonos speakers are found (multicast). Type the
  address of any one of your speakers (Sonos app → Settings → System → About my system) in
  **Settings → Devices & desktop → Sonos address** and every room appears.
- Settings → Devices & desktop: switch Chromecast or Sonos searching off if you don't have them.

## Desktop: media keys, tray icon and notifications

Settings → **Devices & desktop → Desktop**:

- **Media keys and desktop media controls** (on by default). Your keyboard's play/pause, next and
  previous keys work even when Musicwell is in the background. The desktop's own media controls —
  the GNOME clock menu, the KDE media widget, Cinnamon/XFCE panels, the lock screen — show the song,
  artist and cover and work as remote controls, and so do `playerctl` and phone remotes such as KDE
  Connect. Seeking, volume, shuffle and repeat from there all work too. (This is the standard MPRIS
  interface on D-Bus.)
- **Show an icon in the system tray**: click it to show or hide the window, middle-click to play or
  pause, right-click for the song, the buttons and Quit.
  - **Keep playing when the window is closed**: closing the window hides it in the tray; bring it back
    from there.
    **Ctrl+Q** or **Quit** in the tray menu really quits.
  - **Start hidden in the tray**: Musicwell opens with the window hidden.
  - GNOME has no tray of its own; the *AppIndicator and KStatusNotifierItem Support* extension adds
    one. Without a tray, closing the window always quits, so it can't get lost.
- **Notify me when the song changes**: the desktop's own pop-up, with the cover, song,
  artist and album (or the radio station), and a **Next** button where the desktop supports one.
  By default *Only when Musicwell is in the background*. Quick skipping doesn't pile them up.

## Playlists

The **Playlists** tab: your playlists on the left, the songs of the one you click on the right (**Play**,
**Export M3U…**; drag songs to reorder them; Delete takes songs out). Under the list: **New**, **Import M3U…**,
**Select…** and **Delete…**.

- **Pick several:** drag over them with the mouse, Ctrl-click or Shift-click (Ctrl+A for all). Then press
  **Delete**, click **Delete 3…**, or right-click one of them → *Delete the 3 playlists…* (also *Play them*,
  *Add them to the queue*). With none picked, Delete acts on the playlist showing.
- **Select…** shows round tick boxes: a click then ticks or unticks a playlist (no Ctrl needed), and **Select
  all** / **Select none** appear. The ticks and the picked playlists are the same thing — dragging still works.
  **Done** (or Esc) hides the boxes; what's picked stays picked.
- Right-click also has **Delete all playlists…**. Musicwell asks first, naming them, and deleting a playlist
  never deletes its songs: they stay in your library.

## Drag and drop

- **Songs → a playlist:** drag songs from any list onto a playlist's name on the Playlists page (hold
  them over the *Playlists* tab to open it). Drop on the empty space below the names for a new playlist.
- **Songs → the queue:** drop them on the *Queue* tab, or into the queue at the spot you want.
- **The Queue page works like a "Now playing" list:** every song keeps its place. A song that has
  played turns grey; the one playing is marked with the speaker. Double-click any song to play it now —
  the songs above it stay as they are, still to come — or a greyed one to hear it again; the playing one
  starts over. Next plays the songs still to come from the top down. **Previous** goes back to the song
  the queue played before (never to one you've taken off with Clear played or Delete). **Clear played** takes the greyed songs off; **Clear queue** empties it.
  Delete removes songs (not the one playing); Alt+Up/Down and dragging move them.
- **Playing a song from another list** (the library, an album, a playlist) while there are songs in the queue:
  that song plays now, and the queue still plays straight after it, before the rest of that list — as in
  other music apps. When the queue has played, the list carries on.
- **You can see when a queued song plays:** *FROM YOUR QUEUE* shows over its title in the play bar (point at
  it for how many more are queued), and when the music switches to a queued song a note pops up above the
  play bar for a few seconds — *▶ From your queue: song — artist · 2 more queued* (click it for the Queue).
- **Reorder** the queue or a playlist by dragging songs up or down (a playlist sorted by a column goes
  back to its own order first, so songs land where you drop them).
- **From your file manager:** drop folders to add them to the library. Drop music files to queue them:
  a file from outside your music folders is added on its own — just that song, not the rest of its
  folder. It stays in your library (and is kept up to date) until you remove it or delete the file.
- **To other programs:** dragging songs out gives their files (e.g. to copy them to a USB stick).

## Adding folders

Settings → **Add folder…** (or the button on the empty library page): type or paste a path
— `~/Music`, `/mnt/nas/Music`, `$HOME/Music` or a `file://` link all work — with folder
suggestions as you type, or click **Browse…**. You can also drag folders onto the window or run
`musicwell ~/Music`.

## Radio

**Artist and title the wrong way round?** Some stations send "Title - Artist" instead of "Artist - Title".
Musicwell notices when the second part is an artist in your library and the first isn't, and swaps them.
For a station that always does it, right-click the station → **Station options** → **Song titles** → **Title – Artist** (or
*Artist – Title*, or *Automatic*), or right-click the station picture in the panel → *This station sends
Title – Artist*. It's remembered for the station and corrects the song playing straight away, including the
lyrics look-up, the artist photo and ♥ Like.

The **Radio** page (**Ctrl+6**) plays internet radio stations — tens of thousands of them, from
[radio-browser.info](https://www.radio-browser.info), a free community-run directory (no account).

- **Search** by name, pick a **genre** and/or a **country**, or browse **Popular**. Both lists open below their box,
  twenty long, starting at *All genres* / *All countries*; the **✕** beside the country (and inside the genre box)
  goes straight back to them.
- Click **☆** to keep a station in **Favourites**; **Recently played** remembers the last 30.
  Right-click a station: favourite, move up / down, open its website, copy its stream address,
  more stations of the same genre.
- **Add a stream…** — paste any stream address (or a `.pls` / `.m3u` / `.m3u8` link from a station's
  website). **More** → import stations from a playlist file, export your favourites as `.m3u`.
- **Edit stream…** (right-click a favourite) — change its name, stream address, website or genres, for a
  station that has moved, say. It stays the same station: its place in your favourites, its picture and its
  settings are kept. *Add a stream* asks for the same (website and genres are optional).
- **Now playing:** most stations send the name of the song; Musicwell shows it in the panel and the
  bar, finds the **artist photo** and the **lyrics** (synced where they can be — see *Synced lyrics on the radio*
  under Lyrics), and **Find similar** works from it.
- **Streams with no song titles in them** (many plain `.mp3` streams you add yourself): Musicwell asks the
  station's server what's on instead (Icecast, SHOUTcast and AzuraCast say), every 15 seconds, so the panel
  and the play bar show the song as the station list does. HLS (`.m3u8`) stations: read from their playlist.
- **Stations that put their own name in the song** (*Matt Furniss - The SID Station - Shadow of the Beast*):
  the station's name is left out, so the panel shows the song. When the stream gives only the artist
  (*Matt Furniss - The SID Station -*), the station's server is asked for the song's name straight away.
- **Stations keep playing:** when a station drops the connection or stops sending for a few seconds (a
  network hiccup, a server that drops listeners now and then), Musicwell connects again on its own — the
  sound carries on after a moment, and a note says *Connecting to … again* while it does. A station that's
  down for longer is tried again for a few minutes before Musicwell says it can't be reached.
- **The stations' own pictures:** many stations send a picture of the song or artist with its title (in the
  stream, from an AzuraCast server, or in an HLS playlist, as iHeart does). Musicwell shows it in place of the
  station's logo — in the panel and the play bar, and as the artist's picture when there's no photo of them.
  Turn it off in Radio → More → *Show the stations' own pictures of their songs*.
- The EQ, visualizer, volume fades and **Chromecast** work as usual (the speaker connects to the
  station itself). Live radio can't be paused: pause stops the stream and play tunes in again. If a
  station drops, Musicwell reconnects (three tries) before saying it's offline.
- **Next** / **Previous** (the buttons and your media keys) move through your **favourite stations**, in
  the order you keep them (the top bar says which one, e.g. "Night Jazz (3 of 8)"). Playing anything from
  your library goes back to your music, and so does **Stop radio** (on the Radio page and in the station
  logo's right-click menu). Rather have Next / Previous go back to your music? Settings → Radio →
  *Next and Previous buttons* → *Back to my music*.

**Next: …** — what a station plays next, under *Live on …* in the panel and next to the station on the
Radio page. Only some stations can say: those on **AzuraCast** (a free platform many smaller stations
use) and on **SHOUTcast 2** servers whose playout software sends the next titles. Musicwell asks them
when the song changes and every 45 seconds (a tiny request). Other stations — Icecast, HLS streams such
as the BBC's — only send the song playing now, so they have no Next line. A server that doesn't answer
three times running isn't asked again until you tune in again.

**Favourites by genre:** in Favourites (and What's on now), **List:** at the right switches between
**All stations** (in your order) and **By genre** — a heading for each genre, A–Z (stations without a genre
under *Other* at the end). Click a heading to fold that genre away (remembered); right-click it to fold or
show them all. A station goes under its first genre: right-click it → **Station options** → **Genre to list it under** to pick
another of its genres, type your own (*Another genre…*), or go back to its own. Spellings are merged
(hip-hop, HipHop and Hip Hop are one genre). *Move up / down* moves a station within its genre, and Next /
Previous on the radio go through your favourites in the order shown.

As soon as you open the Radio tab, Musicwell looks up what each station in **Favourites**, **Recently
played**, **Popular** and **Search results** is playing and shows the song under its name (♪ Artist – Title),
and looks again every minute while the list is showing. In Popular and Search results (long lists) it asks
the stations on screen, and the next ones as you scroll.

**What's on now** (next to Favourites): every favourite station with the song it's playing right now —
pick a song rather than a station, and click to tune in. Rather have the song in bold with the station under
it? Settings → Radio → *What's on now* → *Song first*, or More → *What's on now: the song first*. Songs you have are marked *in your library*,
songs you've ♥ Liked are marked too. It looks again every minute while the list is showing (or click
**Look again**), and not at all when it isn't. To find out, Musicwell connects to each station for a
moment and reads up to its first song title — about 16 KB per station for most (more for a station that
only sends its title a little later), so 10 favourites cost about 10 MB an hour while you have the list
open. A station that doesn't put the song in its stream is asked its server instead (Icecast, SHOUTcast
and AzuraCast servers publish what's playing), and HLS stations (.m3u8) are read from their playlist.
Stations that don't say anywhere (some stream formats, talk stations) say so.

**Turning adverts and jingles down** *(experimental — it guesses from what each station sends, so it
won't always be right)* (off unless you switch it on: Settings → Radio → *Turn down adverts and jingles*): between songs
many stations send no title, their own name or web address, or words like *Advert*, *Ad break* or
*Jingle*. Musicwell then fades the sound down (**Advert volume**: 25 % of your volume, or Silent / 10 % / 40 %)
and back up as soon as the next song is named — or after 4 minutes at most (**Turn back up after**:
2–15 minutes), in case it's a programme rather than a break. Songs that merely have such a word in them ("Jingle Bell Rock") play as
usual. Your volume setting is never moved. Got one wrong? Right-click the station picture → **Not an
advert — turn it back up** (remembered for that station), or **Turn “…” down on this station** to mark
a break it missed.

**Song alerts** (off unless you switch them on: Settings → Radio → *Notify me when a favourite station plays…*): a
notification when one of your favourite stations plays **Songs I've liked**, **Artists I've liked songs
by**, **Any artist in my library** (if you tick it — that can be a lot), or other artists you list. Click the notification, its **▶ Listen** button, or the message at the top of Musicwell to tune in
(**What's on now** opens that list instead). Without a notification service (some desktops, Windows),
the tray's pop-up is used, and clicking it tunes in too. Tuning in from an alert also takes you to the
**Radio** tab — or, with Settings → Radio → **Notification action** → *Current layout*, keeps the layout you're
in.
Song alerts work in the background, even when the Radio page isn't open. Choose **Check every**
(1, 2, 5 or 10 minutes), the **Stations to check** (*All favourites*, or *Chosen stations* → *Choose…*),
and **While listening**: *Keep checking* your other stations, or *Pause checking* until you stop the radio. Each look is the same small one
as What's on now (about 16 KB a station), so 10 stations every 2 minutes is about 5 MB an hour; the
settings show the figure for your choices. It uses hardly any memory. The station you're listening to
isn't asked, and each song is mentioned once an hour at most.

**Settings → Radio** has everything for the radio in one place, in four sections: **Stations**
(*Next and Previous buttons*, *What's on now*, *Similar stations to show*), **Songs in your library**,
**Adverts** and **Song alerts**. The extra choices for adverts and song alerts show once you switch them on.

**Songs you have:** when the station you're listening to plays a song that's in your library, a
**▶ Play your copy** button shows next to *♥ Like this song* on the Radio page, and a **▶ Your copy**
pill shows in the play bar beside the playing song (only while it's useful — unlock to move or remove it).
Click it to play your own copy. Right-click the button — or any station whose current song you have —
for *Play your copy*, *Play your copy from about where the radio is* (from when the station named the
song, if you heard it start; stations don't say exactly, so it can be a few seconds out) and *Add your
copy to the queue*. Settings → Radio → **Songs in your library**: **Play your copy** *From the start* or *From the same
point*, and **Notify me when the station plays a song I have** (off unless you switch it on): a note at the top of the window — click it to play your copy —
and a desktop notification with a ▶ Play your copy button when Musicwell isn't in front.

**♥ Liked on the radio:** hear something you like? **♥ Like this song** (next to *Stop radio*, in the
station logo's right-click menu, **Ctrl+Shift+L**, or add the ♥ item to the play bar) keeps its name —
artist, title, the station and when you heard it — in **Radio → ♥ Liked**. Click again to take it out.
Songs you already have are marked *In your library*: double-click to play them. For the others,
double-click looks for the song in **Discover → Search online**; right-click for *Search your library*,
**Discover ▸** (*Search for…*, *Music like…*), **Buy it from** Bandcamp, Qobuz or 7digital (opens a search for the song in your web browser), *Search the web*, *Copy* and *Remove*.
**More → Export ♥ Liked songs** saves the list as a spreadsheet (.csv). Only the names are kept — nothing
is recorded.

How the song titles are read: stations slip them into the stream every few seconds; Musicwell plays
the station through a tiny relay on this computer (`127.0.0.1` only) that takes them out. Nothing is
recorded, and radio isn't counted in your library's plays (it has its own Radio stats).

**Stations like this one** lists the 40 best matches; Settings → Radio → *Similar stations to show*
changes that (20, 40, 80, 150 or 300).

**Clear:** on *Recently played* and *Search results* a **Clear** button empties the list (and the search).

**Your own station pictures:** right-click a station → **Choose a picture for this station…** (or
right-click the big picture while it plays). **Paste a picture** appears when you've copied an image,
e.g. a logo from the station's website. Wide or tall pictures are made square without cutting anything
off. Your picture is used instead of the station's logo everywhere; **Remove my picture** goes back to
it. They're kept with your library (`~/.local/share/musicwell/station-pictures/`), so clearing the
image cache doesn't remove them.

## Discover

The **Discover** tab is for finding music you don't have yet, and music like what you're playing. A switch
along its top has three parts:
- **Like this** — music like a song or an artist: from your library, similar artists, radio stations, and
  free music online (Find similar, below).
- **Search online** — search free music on the Internet Archive, Openverse, Audius and your own sources.
- **My sources** — the podcast feeds, online playlists and web folders you've added.

Clicking the Discover tab opens the part you used last. (Discover used to be two tabs, Similar and Online
Sources; if you'd removed Similar but kept Online Sources, Discover stays.)

### Like this (Find similar)

Right-click a song → **Discover ▸ Songs like this one** (or **Music like *artist***), or press **Ctrl+Shift+F**
for the song playing — it opens Discover → **Like this**. Before you've looked for anything, it offers
**Find similar to the song playing** and a box to type an artist (press Enter). It shows songs from your
library that go with it — **Play**,
**Shuffle** or **Add to queue** — the similar artists you have (double-click one to explore from
there), and similar artists you *don't* have as suggestions with a link to their ListenBrainz page.

How it decides:
- **ListenBrainz** — which artists listeners play together (open data, no account or key). The artist
  is identified by the MusicBrainz ID in your tags when there is one (e.g. tagged with Picard),
  otherwise by a MusicBrainz search. Results are cached for a month.
- **Your library** — shared genres, a similar era, and artists you play in the same listening sessions.
- No more than four songs per artist, and never the same artist twice in a row.

**Similar stations** (**Stations**, in Like this — each with the song it's playing now) — radio stations from the directory
playing that kind of music: matched on the station's own genre tags (**Stations like this one**:
right-click a station, or the station logo while it plays) and on the genres of the artist playing
(from MusicBrainz). On the radio, Find similar (Ctrl+Shift+F) opens on Stations; it also works when the
station hasn't said which song is on. Double-click to tune in, ☆ to keep one.

**Clear** (top right of Like this) clears the results; the tab stays, ready for the next search.
The similar-artist and genre answers are kept for a month; Settings → Library → Storage → **Clear cache…**
→ *Find similar data* deletes them.

Settings → Playback: **"Keep playing similar songs when the queue ends"** carries on with songs like
the last one instead of stopping; and *Use ListenBrainz to find similar artists* can be switched off
(then only your library is used).

### Search online and My sources

**Free music | Radio stations:** under the search box, *Radio stations* lists stations playing that kind of
music — matched on the artist's genres (as *Like this* does), or on the words you searched for as a genre
("jazz") — each with the song it's playing now. Double-click to tune in, ☆ to keep one, right-click for
*Stations like this one*.

**Search online** — type an artist, a genre or a title and press Enter, or click one of the words under **Try:**
(Jazz, Classical, Electronic, Ambient, Folk, Rock, Blues, Live concert). It searches the Internet Archive,
Openverse and your own sources together (your own come first, with their name as the badge). Double-click a
result to play it. Right-click it to **Add to playlist**, **Show the tracks…** of a concert or release, open
its page (licence, credit, download), or **Search Discover for music like** the artist. **Clear** empties the search. On the
Radio page, *Search Discover for “…”* (right-click a ♥ Liked song) searches here. Settings →
Playback switches the Internet Archive and Openverse on or off.

**Where the music comes from:** the **Internet Archive** (concerts, netlabels, Creative Commons and
public-domain recordings), **Openverse** (Creative Commons music from Jamendo, Wikimedia Commons, ccMixter…),
**Audius** (an open platform where independent artists share songs to stream free — no account needed; only
songs that are free to stream are listed) and your own sources. Settings → Search switches each one on or off.

**From the main search box too:** a pause in typing in the search box at the top also looks in the free
online sources and your own sources. If they have something, a line appears under your songs — *Free online:
8 songs or albums for "Kestrel"* — click it to open the list (drag the divider above it to make it taller),
click again to fold it. `artist=Kestrel`, `album=`, `title=` and `genre=` searches look in the same place
online; searches that only make sense in your library (`year>1990`, ratings, play counts…) don't look online.
Settings → Search → *Search online too*: as you type, only when you press Enter, or never.

**The same results everywhere:** typing the name of an artist you have (in the search box at the top, or in
Search online with *Anything*), right-click → *Search Discover for “…”* and *More by …* all search the
same way, so they list the same songs. Settings → Search → **Artist searches** picks the way:
*Everything with the name* (more results — the default: their songs plus anything with the name in its title
or genre) or *Only songs by the artist* (closer matches). A link under the results switches the other way
for one search.

**Songs by an artist:** right-click any song (library, queue, playlists, Like this…) → **Discover ▸
Search for …**, next to *Songs like this one* and *Music like…*. It's also on the artist photo's
right-click menu, the artist list, the artist page (**Search online**), the station picture while the
radio names a song, ♥ Liked songs, and any online result (**More by …**). It opens Discover → Search online
with **Artist** chosen. Find similar looks on Audius too.

**Better matches.** Results are ranked best match first, and things that don't really match are set aside:
- **Where to look** (the menu before the search box): *Anything* (the artist, the song or album title, or
  the genres — not long descriptions, where a word turns up in all sorts of things), *Artist*, *Song title*,
  *Album* or *Genre*. Or type it in the box: `artist:Kestrel`, `title:Paper Moon`, `album:Night Lines`,
  `genre:jazz` (the menu follows).
- **Filters** (next to Search): *Only close matches* — every word you typed must be where you asked (on
  unless you switch it off; a link under the box shows the looser matches set aside); *Leave out clips
  under a minute* — loops, jingles and sound effects (on); *Leave out live concert recordings* (off).
  Your choices are remembered.
- These sites only have music that's free to share, so well-known artists are rarely there. When nothing
  matches, try a genre, or **Find similar** for free music like the artist.

**My sources** — places online that you add yourself:
- a **podcast or RSS / Atom feed** (a netlabel's or a band's feed, for example);
- an **online playlist** — an `.m3u`, `.m3u8` or `.pls` address (`#EXTINF` titles are used; "Artist - Title"
  is split into artist and title);
- a **link to one audio file** (`.mp3`, `.ogg`, `.opus`, `.flac`, `.m4a`, `.wav`…);
- a **web folder** — a web page that lists audio files, such as a folder shared from your NAS or a server's
  file listing. The folders under it are read too (three levels down): *Artist / Album / 01 - Title.mp3*
  gives the artist, album, track number and title.

Click **Add source…**, paste the address and give it a name. **Type** is normally *Detect automatically*.
**Check** reads it there and then and says what it found. The **Note** (a licence, for example) is shown with
its songs. Musicwell reads the list of songs and plays them from there; nothing is downloaded. Only add
sources you're allowed to listen to.

Pick a source on the left to see its songs: double-click to play (the songs after it follow), **Shuffle**,
filter them, or right-click songs → **Add to a playlist** (they show as *Online* in the Source column, with
the source's name in the tooltip). **Refresh** reads a source again for new songs. Sources are read when you
add them, and again once a day when you use the tab. Untick a source to leave it out of searches. Right-click a
source to refresh, edit, move, copy its address or remove it. Removing a source doesn't take its songs out of
your playlists. A live stream (an HLS `.m3u8` or a radio station) belongs on the Radio page instead.

**Free music in Like this** (its third part) — music like the song or artist you looked for from
online sources: songs in your own sources by that artist or the similar ones (first), then free music from the
Internet Archive and Openverse. It has its own search box too. The two free sources are: Releases and
songs are mixed together, each with a badge for where it's from.

[Openverse](https://openverse.org) (run by WordPress.org) — Creative Commons and public-domain *songs* from
Jamendo, Wikimedia Commons and other sources; no account needed. Double-click a song to play it — Musicwell
carries on with the Openverse songs listed after it. Each song shows its licence; right-click → **Open
on Jamendo / Wikimedia Commons…** for its page and download, or **Copy the credit line** (the attribution
the licence asks for, e.g. *"Harbor Lights" by Neon Harbor is licensed under CC BY-SA 3.0*). Openverse
limits searches made without an account; if you search a lot in a short time it says it's busy — wait a
minute. Find similar makes at most three Openverse searches.

The [Internet Archive](https://archive.org/details/audio) — *releases and concerts*:
recordings by the artist, by similar artists and in the same genres, from the **Live Music Archive**
(concerts by bands that allow their shows to be shared), **netlabels**, and anything marked with a
**Creative Commons** or **public-domain** licence — nothing else is searched. Double-click to play a
concert or release (Next / Previous, seeking, fades and Chromecast work; the panel shows its picture,
collection and licence), right-click → **Show the tracks…** to start from a song, or **Open on
archive.org** for its page, licence and download links. The **search box** on that tab searches both. Musicwell plays the files from archive.org and doesn't keep them; Archive songs aren't
added to your library or counted in your stats. Settings → Search switches each source (Internet
Archive, Openverse, Audius, My sources) on or off.

**Online music in playlists** — right-click a release, concert or song in Search online (or Like this → Free music) → **Add to
playlist** → a playlist (or **New playlist…**) adds it. For a release or concert, every song in it is added. To add only some
songs, choose **Show the tracks…**, select them (Ctrl/Shift-click) and use the **Add to playlist** button. While
a free song plays you can also right-click its picture in the panel → **Add this song to a playlist…**. Free songs then
sit in the playlist with your own songs: drag to reorder, Play, Shuffle and Export M3U all work. They still
play from the Internet. Musicwell keeps only the song's details (title, artist, link, licence), not the file. When
no playlist uses a free song any more, its details are removed the next time Musicwell starts.

**Source column (Local / Online)** — playlists and the queue show a **Source** column: **Local** (muted) for a
file in your library, **Online** (in the accent colour) for music played from the Internet (free music or your own sources). Hover it for
where the song comes from and its licence. Like any column, hide it, move it or rename it from the header's right-click
menu, or add it to the library song list.

## Covers and artist photos online

Free sources, no account needed (Settings → **Online images**: tick/untick, drag to change the order).
Only services whose terms allow a music player to use their images are included:

| Album covers | Artist photos |
|---|---|
| Cover Art Archive (MusicBrainz) | Wikipedia — the article's photo, **free licences only** |
| | Wikidata — the artist's photo, found via MusicBrainz |
| | Wikimedia Commons — photos from the artist's own photo category |
| | Wikipedia in other languages — e.g. German, French, Japanese articles' photos |

- **Cover Art Archive** is the open MusicBrainz / Internet Archive project built for this
  (MusicBrainz Picard, Kodi and beets use it too).
- **Artist photos come only from Wikimedia Commons**, where every photo has a free licence (CC BY,
  CC BY-SA, public domain…). Wikipedia's non-free images are never used. Those licences ask for the
  photographer to be credited, so Musicwell keeps the author and licence with each photo: hover over
  the artist photo to see them in the corner (click to open the photo's page), or right-click it.
- **Wikimedia Commons category** helps artists whose Wikipedia article has no photo: it's found through
  the artist's Wikidata entry, so it's as sure a match as Wikidata's own photo, and logos, sleeves and
  posters in it are skipped. Updating adds it after the sources you have ticked.
- **Wikipedia in other languages** helps artists better known in their own country: the photo at the top
  of their German, French, Japanese… article (free photos only), found through Wikidata the same way.
  It's tried last, asks at most four Wikipedias per artist, and is labelled e.g. "Wikipedia (de)" in
  **Search for artist image…**.
- **Retry missing** (Settings → Online): a cover or photo that wasn't found isn't looked for again for a week.
  Retry missing forgets that, so each is looked for again as it's needed — when it scrolls into view, its page
  opens or its song plays — a few at a time, at the pace you browse and listen.
- **Too many requests:** if a service says Musicwell is asking too often, it isn't asked again for as long as
  it asks (or 30 seconds, doubling up to 10 minutes only if it keeps asking), and the artists or albums it couldn't answer for are looked up again later (not counted as
  "no image"). Musicwell tells Wikimedia and MusicBrainz who it is, as they ask every app to.
- **Not used:** Apple Music / iTunes and Deezer (their terms limit their images to promoting their
  own stores), TheAudioDB and fanart.tv (they need registered keys). Openverse was tried and taken out
  again: it searches by name, and its photos were mostly someone else. Updating from an older
  Musicwell drops the images downloaded from those services and looks them up again; images you
  picked yourself, the covers inside your files and `cover.jpg` files in your folders are kept.

Found images are cached in `~/.cache/musicwell` (fetched once). Optionally they're saved into the
album folder as `cover.jpg`. **Right-click the cover or the artist photo** in the panel for
**Search for album image… / Search for artist image…** — a window with what every free source found side by
side (freely licensed pictures from Wikipedia, Wikidata, Wikimedia Commons and the Cover Art Archive); pick
one — or **Search the web…** for any other picture, **Paste**, **Choose a file…** — plus **Use my own image…**
and **Back to the automatic image**.

The same works for **any artist or album**, not just the one playing: right-click an artist in the album
artist list → **Image ▸** (or an album under them → **Image ▸**) → **Search for artist image…** (**Search for
album image…**), **Use my own image…** or **Back to the automatic image** — and right-click the photo on an
artist's page for the same. The new picture shows straight away everywhere that artist or album appears.

**Pictures from the web, picked by you.** Musicwell doesn't search image sites itself (there's no free,
reliable way, and most pictures on the web belong to someone), but it makes picking one easy:

- **Search the web…** (in the **Search for artist image / Search for album image** window) opens your own web browser on
  an image search for the artist or album — DuckDuckGo, Google or Bing (Settings → Online → *Search the web
  with*). When no free picture is found, the window says so, lights the button up and shows the steps.
- **Drag** a picture from the browser onto the artist's photo on their page, onto them (or an album under
  them) in the artist list, onto an album cover on the artist's page, or into the Search for … image window.
- **Or copy it** (right-click it in the browser → *Copy image*, or *Copy image address*) and choose
  **Paste** in the Search for … image window (or press Ctrl+V there).

Musicwell takes the full-size picture behind a search result (not the small preview), and if a web page
was dropped instead, the picture that page shares itself with. Very big pictures are made smaller; a very
small one is used but you're told. What you pick is kept like a file of your own: only on this computer,
for showing in Musicwell, never replaced automatically and never shared. (Pictures on the web usually
belong to whoever took them, so keep them to your own library rather than passing them on.)

**Reload images:** hover over the artist photo or the album cover and click the round ↻ button
(or press **Ctrl+F5**, or add *Reload images* to the bottom bar). Musicwell looks again — your folders
first, then online — and tells you if nothing was found. Images you picked yourself are kept.
If a source stops working, `~/.cache/musicwell/images.log` shows what each service answered, and
the Search for … image window shows which services didn't answer.

**Start fresh:** Settings → Library → Storage → **Clear cache…** deletes the covers and artist photos
Musicwell has downloaded (and, if you tick them, the images you picked yourself, lyrics found online
and seek bar waveforms), so everything is looked up again. Your music files, the covers inside
them and `cover.jpg` files in your folders are never touched.

## Arranging the now playing panel

**Song list:** unlock, right-click the Left, Right or Top Panel → **Add here** → **Song list**. The box at its
top picks what it shows: **Playing now** (the songs playing, in the order they'll play — shuffled order when
shuffling), **Your library** (the Library tab's list: it follows the search box and the column browser),
**The queue**, any one of **your playlists** (♫ in the box — or ⋯ → A playlist), or **Follow the tabs**: the
playlist you pick on the Playlists tab shows in the panel **instead of** on the tab (the tab then keeps just
the list of playlists, with Play and Export; set the song list to something else to have the songs on the tab
again). **Playlist tabs along the top** work the same way, and so does **Library**: while a panel's song list is set
to Follow the tabs, clicking a playlist tab (+ → a playlist) opens its songs in that song list, and clicking
Library puts the library back in it (following the search box). The tab whose songs are showing has its name
in the accent colour. Playlist tabs leave the main area as it is; Library also opens in the main area — unless
you've hidden the Centre Panel, which then stays hidden, so the side panel's song list can be your main list.
Other tabs open as usual (and bring the Centre Panel back). With no song list set to Follow the tabs, playlist
tabs open in the main area as before. It remembers whether it was showing the library or which playlist.
In a playlist, Delete or right-click → *Remove from playlist* takes songs out of it. Double-click a song to play it (Playing now jumps to it without changing the order);
right-click for the usual song menu; right-click the column headings for other columns (it starts with
title, artist and time; title and artist share the panel's width). **⋯** → **Fill the panel** lets it take
all the height the other items leave; **⋯** → **Show the box at the top** (untick) hides the SONGS heading,
the box and ⋯ for a plain list — its options are then on the column headings' right-click menu (**This song
list**) and, unlocked, the panel's right-click menu (**Song list**). The list takes the panel's colour. Each panel's list keeps its own choice, and layouts keep it.

**Spinning record:** right-click the album cover in any panel → **Show the cover as** → *Square (the
cover)*, *Spinning record (the cover as its label)* or *Spinning picture disc (the whole cover)*. The
record turns while a song plays, slows to a stop when you pause and stays where it stopped.
**Record speed** (in the same menu, or the play bar's look): **33⅓ rpm** (an LP,
the usual), **45 rpm** (a single), **78 rpm** (an old shellac record) or a slow **16⅔ rpm**. One speed for
every record.
Each panel keeps its own choice (and layouts keep it). The play bar's cover has the same choice
(unlock, right-click the play bar → **The play bar's look** → **Album cover**).

**Adding items:** unlock (F2), right-click the left or right panel → **Add here**.

**Artist list:** unlock, right-click the left or right panel → **Add here** → **Artist list**.
It lists every artist in your library with their **photo**, a **filter** box and the number of songs. Photos come
from the same places as the big artist photo — your own pick, an `artist.jpg` next to the music, then the free
online sources (Settings → Online) — and only for the artists you scroll to, so a big library isn't
looked up all at once. Artists without a photo show their initials. Right-click → **Picture size** (Small, Medium,
Large, Extra large) makes the photos bigger; **Pictures** switches them off.

**Artist page:** clicking an artist in the artist list (or right-clicking a song → **Go to *artist*'s page**) opens
it in the Library tab. At the top are the artist's photo, name and totals, with **Play**, **Shuffle**, **Add to
queue** and **Find similar**. Below are their **albums as covers**, oldest first, then the songs. Click an album
to list just its songs (Play becomes *Play album*), or *All songs* for everything. Picking an artist (clicking or
double-clicking them in the list — a double-click opens their page and plays them) always opens on *All songs*, and it stays that way as the songs change — only
an album you pick yourself changes it. Hover a cover for **+** to add
that album too — pick as many as you like (Play becomes *Play 3 albums*), **−** takes one off. While your pick is
playing, + and − change what's playing without stopping the song. Double-click an album to play
it, or right-click it for Play, Shuffle and Add to queue. Right-click → **Cover size** (Extra small, Small, Medium,
Large, Extra large) is remembered. Go back to the column browser with **← Library**, **Esc**, by clicking the Library
tab again, or by typing a search. (In the **Artists** layout the artist page *is* the Library page: no ← Library,
and the search box works as everywhere else — the matching songs, in the song list; empty it, or press Esc, and
you're back on the artist. The artist list has its own box for finding an artist.)

**All albums:** every album in your library as covers, in the Library tab — in the **Albums** layout it *is* the Library page
(elsewhere, **← Library** goes back to the song list). The **All albums** row at the top of the artist list, and *Open All
albums* in a panel, open it too. (There used to be an Albums tab; it's gone — **+** after the tabs → **All
albums** still adds one if you'd like it back.) (It used to be a button at the
top right — unlock, right-click the top bar → **Add here** → *All albums button* puts that back.) Use the **filter** to find an album or artist, and **Sort** by artist, album title, year
(newest or oldest first), recently added or most played. Right-click → **Cover size** (Extra small to Extra large).
Click an album to list its songs below, and **Play** / **Shuffle** play it; double-click an album to play it
straight away. Right-click an album for *Play*, *Shuffle*, *Add to queue*, *Go to the artist's page* and *Show in
the library browser*. Covers are only looked up for the albums on screen.

Each album is **one tile**, even when its songs are by different artists. A compilation without an album artist tag
shows as *Various Artists*; right-click it → **Artists on this album** to go to any of them. Songs with the same
album name belong together when they share an album artist tag or, without one, the same folder (a CD1 / Disc 2
folder counts as the album's folder). So two different *Greatest Hits* by different bands stay apart. An album's
songs are listed in disc and track order. Tick **Split by artist** (top of the page, or right-click) for one tile
per artist on each album instead. The choice is remembered. The artist playing is in
the accent colour. **Click** an artist to open their **artist page** in the main window (below);
**double-click** to play all their songs. The filter finds album names too.

**All artists**, the first row, lists every song in your library in the song list (the search box and
the column browser's picks are cleared, so it really is all of them); double-click it to play them all.
While it's open the song list stays put as the songs change; click an artist to go back to their page.

**Right-click** an artist: their name at the top, then *Play*, *Shuffle*, *Add to queue*; **Image ▸** (search for
one, use your own); **Discover ▸** (*Music like…*, *Search for…*); *Go to the artist playing*;
and **List options ▸**. An album row has the same shape: *Play album*, *Shuffle album*, *Add to queue*,
**Image ▸**. *All artists* has *Play all songs*, *Shuffle all songs* and *Show all songs*. Right-click the
empty space below the list for just the list options.

**List options** are how the list looks: **Show** (album artists, or track artists), **Sort by** (A–Z, most
songs, most played, recently added; "The" and "A" are ignored for A–Z), **Pictures** and **Picture size**,
**Album and song counts** (a small line under each name: *3 albums · 42 songs*, plus plays when sorted by most
played; under an album, its year and songs), **Filter box**, **“All artists” row** and **“All albums” row**
(untick to hide them),
and **Fill the panel** to use all the space below the other items instead of a box of its own height.
Each panel keeps its own choices. Drag its bottom edge while rearranging, or use **Height of "Artist list"**,
to make it taller.

**About the artist:** unlock, right-click the left or right panel → **Add here** → **About the artist**. A few paragraphs about the artist playing — from their **Wikipedia** article (the opening section,
found through MusicBrainz so it's the right band, with a link to the article) — and a line from
**MusicBrainz**: where they're from, the years they've been active, their genres. It scrolls; drag its bottom
edge while unlocked, or right-click → **Fill the panel**. For radio it's the artist of the song on air. The
**artist page** shows the same under the artist's name (the first paragraph, **More…** for the rest). Each
artist is looked up once and kept for a month. Settings → **Artist info** switches it off.

**Picking albums:** click an album for its songs below. Point at another album and click the **+** in the bottom
right corner of its cover to add it to your selection; an album in your selection has an outline and a **−** in
the bottom left corner to take it out. **Play**, **Shuffle** and **Add to queue** play your selection (with none,
every album showing). **Add all** adds every album showing; **Clear selection** empties it.

**While they play,** the list below says *PLAYING* and those albums have ▶ on their covers (top right). Then
**+** (bottom right of a cover, when you point at it) adds that album to what's playing — at the end, or among the
songs to come when shuffling — and **−** (bottom left) takes it out (the song playing carries on). Clicking another cover doesn't change the list — double-click it to play it. Your selection, and what's playing from here, are still there next time you start Musicwell.

**All albums in a panel:** unlock, right-click the left or right panel → **Add here** → **All albums**. Every album with its cover, a **filter** box and the number of albums; the album playing is in the
accent colour. **Click** an album to show it in the library — or, while you're on the **Albums** tab or using the Albums
layout, to pick it there: Musicwell stays on All albums until you go back to the song list (← Library,
the button again, or Esc), even after a restart. **Double-click** to play it. Right-click
for *Play*, *Shuffle*, *Add to queue*, *Go to the artist's page*, *Show the album playing*, **View** (List, List
with bigger covers, or Covers), **Sort by** (artist, album title, year, recently added, most played) and **Filter box** (untick to
hide it), **Fill the panel** (all the space below the other items; with the artist list filling too, they
share it) and *All albums (big covers)* for the big page. Each panel keeps its own choices; drag its bottom edge while unlocked to make it
taller. Switching layouts keeps it.

**Heights:** unlock, right-click the artist photo, cover, visualizer, lyrics, up next, extra fields or the
"Playing on…" (Chromecast) box → **Height** → *Taller*, *Shorter* or *Its own size* — or drag the
bottom edge.

Unlock (F2) to move items about (see **Moving things around**). Panel items: artist photo, album cover, visualizer, "Playing on…" (casting), song title, artist, album,
rating, audio details, play count, **extra fields**, up next, lyrics, ♥ Like, artist list, All albums,
About the artist and **Song list**. Right-click → Add here → **Space** or **Divider line** adds a gap; right-click it for
*Taller*, *Shorter*, *Draw a line*. Right-click the panel → **Line up the items** (locked or unlocked) sets the title,
artist, album, rating, details, extra fields, up next, lyrics, the artist's name, the album cover and the
visualizer to left, centre or right. In the same menu, **In the middle, up and down** puts a side panel's
items in the middle of its height, and they stay there as the window is made taller or shorter (Vinyl uses it
for the record).
**Sizes:** drag the **bottom edge** of the artist photo, album cover, visualizer, lyrics, up next or extra
fields (spacers too) to make it taller or shorter; double-clicking the edge goes back to its own size.
The **visualizer** also has a grip on its **right edge**: drag it to make the visualizer wider or
narrower (double-click: back to its own width). It can go in any panel — Left, Right or Top
(right-click → Add here → Visualizer); in the Top Panel, dragging the item's right edge widens it.
Sizes are saved with the panel and in layouts. The cover grows up to the panel's width — widen
the panel for a bigger one.
**Extra fields** shows any fields you pick — Comment, Label, BPM, Mood, your custom columns…
(right-click → Extra fields). **Reset** puts everything back.


**A second panel on the other side:** right-click the panel → **Show a second panel on the other side**
(or **Shift+F9**, or the panels button). It shows the same song with its own set of items — it
starts with the lyrics, up next and the song's details, so you can have the artwork on one side and the
lyrics on the other. Right-click it to rearrange it, add or remove items, resize them, or **Hide this
panel**; it has its own **Reset panel layout**. It always sits opposite the main panel (if you move the
main panel to the right, it moves to the left). Saved layouts remember it.

**Hiding one of the two panels:** with both panels showing, the **show / hide panel** button (top right) opens
a menu: *Hide the left panel*, *Hide the right panel* or *Hide both panels*. The same menu brings them back.
With only one panel in use, the button simply shows or hides it (as **F9** does).

## Columns

**Column widths:** right-click a column header → **Resize “Artist” to fit** (just that column) or **Auto-resize
columns** — one click: each column becomes as wide as what's in it (at most 520 px), all of them inside the
window — if they don't all fit, the wide text columns give up room first (a long column title gets "…"), so no
column ends up off to the right — and the Title column takes the room that's left. It doesn't stay switched on:
drag the edges afterwards if you like.

Right-click any song list header. The basics include **Disc number**, **Total tracks** and **Total
discs**. The totals are read however a file stores them: TOTALTRACKS / TRACKTOTAL and TOTALDISCS /
DISCTOTAL (FLAC, Ogg, Opus), "3/12" in the track or disc number (MP3, APE, WMA) and the track pair in
M4A files. Besides the basics there are three groups:

- **Tags** — Comment, Grouping, BPM, Key, Mood, Label, Catalog number, Conductor, Lyricist,
  Remixer, Disc subtitle, Language, Copyright, ISRC, Encoded by.
- **Audio & file** — Format, Bitrate, Sample rate, Bit depth, Channels, File size, File name,
  Folder, Full path.
- **Library** — Rating, Play count, Skips, Date added, Last played.

**Original year and decades:** the *Original year* column shows a song's original release year
(ORIGINALDATE / ORIGINALYEAR, or TDOR / TORY in MP3s — what MusicBrainz Picard writes). Settings →
**Library → Decades from** chooses whether the Decade (browser, column, search and stats) uses the
year tag or the original year tag; with the original year a 2011 remaster of a 1977 album counts as the
1970s. Songs without an original year use their year tag. Search with `origyear<1980` or
`originalyear=1977`.

Which tag holds the original year: **Original year tag** under it is *Find it automatically* — the usual
names, plus any tag whose name has "orig" with "year", "date" or "release" in it (e.g. ORIGINAL RELEASE,
ORIG_YEAR) — or pick any tag found in your music from the list (the likeliest ones come first). Below it,
Settings shows how many of your songs have an original year in that tag.

**Rename a browser column** (Genre, Album artist… at the top): right-click it → **Rename “Album artist”…**
— the same names are used everywhere, so renaming it in the browser or in the song list is the same thing.

**Bold headers:** unlock, right-click a column header → **Bold column headers** shows the column headers and browser titles in
strong, bright type.

**Tab names:** right-click a tab → *Rename “Library” tab…* (leave it empty for the original name;
*Reset tab names* puts them all back).

**Tab order:** unlock (F2), then drag a tab along the top to a new place, just like a column header (a line shows where
it will go; tabs you've removed keep their places for when you put them back). Or right-click a tab →
*All tabs* → *Show, remove and order…*. Ctrl+1, Ctrl+2… follow the tabs shown.

**Words or icons:** right-click a tab while unlocked → *All
tabs* → *Show tabs as* shows the tabs as **Words**, **Icons** (one for each: a note for Library, covers for
Albums, a list for the Queue, a microphone for Lyrics, a chart for Stats, a radio, a compass for Discover; your
own tabs get their own: a heart for Favourites, a sparkle for Recently added, a clock for Recently
played, a rising line for Most played, a play button for Never played, and the playlist, search or albums icon) or **Icons and words**. With icons only, point at a tab to
see its name; the Queue tab keeps its number. When the window is made too narrow for the tabs, they first
pack closer together (slightly smaller), and if that isn't enough the last tabs move behind a **»** button
at the end of the row — click it for a menu of them (the tab you're on always stays showing). They come
back as the window is widened. A layout's tab style (words, icons, or both) is never changed by this — the tabs never stop the window getting narrower. (The
Albums and Radio tabs' rows of buttons wrap onto a second line in a narrow window for the same reason.)

**Remove a tab:** right-click it → **Remove “Stats” tab**. To bring it back, click **+** (just after the
tabs) → **Put back “Stats”**. The Library tab always stays; every other tab can be removed,
Discover included.

**Add a tab:** click **+**, or right-click a tab → **Add tab**:
- **A playlist** — the playlist gets a tab of its own. Play, Shuffle, drag to reorder and Delete all work
  as on the Playlists tab, and **Open in Playlists** takes you there.
- **Favourites** (rated 4★ or more), **Recently added** (last 30 days), **Recently played**, **Most
  played** (your top 100) and **Never played** — ready-made searches.
- **A layout** — a tab that switches to that layout: click it and the whole window changes. Layouts' tabs
  are in every layout (a layout with fewer tabs, like Vinyl, still shows them), so you can hop between your
  favourite layouts from the tabs.
- **A search of your own…** — a name and a search, written the same way as in the search box (`genre=jazz`,
  `artist=bowie`, `year>=1970 year<1980`, `#(added < 30 days)`), with an optional sort and number of songs.
  It starts with whatever is in the search box.

A search tab keeps up to date as your library changes: rating a song puts it into Favourites, for example.
Click a column header to sort, or use **Edit…** to change the search. Right-click a tab you added to
rename it, edit it, move it or remove it. Removing it doesn't delete any songs or playlists.

**Tabs…** (right-click a tab while unlocked → *All tabs* → *Show, remove and order…*) shows every tab in one window. Tick or untick
to show or remove a tab, drag to reorder, and use **Add tab** or **Delete tab** for tabs you've added.

**Rename a column:** right-click its header → **Rename “Title” column…** and type a name of your
own ("Song", "Performer", "No."…). The new name shows in the header, the column menu, the browser and
the now playing panel. Searches work with both names (`performer=bowie` and `artist=bowie`). Leave the
name empty to go back to the original one, or use **Reset column names** to undo them all.

**Custom fields** turn *any* tag in your files into a column — unlock, right-click a column header →
**Columns** → **Custom fields…** → **Add a tag…**: type the name of a tag, or pick one of the tags
found in your library (with how many songs have it). Nothing in the Custom fields window is picked when it
opens — click one of your fields to rename or delete it. Custom columns work in the
song list, the browser, the panel's extra fields and search. Drag headers to reorder, drag edges to
resize; the layout is remembered. The library re-reads all tags once after this update.

Comments can be edited in the tag editor (Ctrl+E).


The same **Custom fields…** window manages them (a new one shows in the song list you opened it from;
show or hide one like any other column, under **Columns** → **Custom**). **Rename…** changes the column's name; **Delete…** removes the
field from the song list, the browser, the panel and searches. Musicwell only reads these tags — your
music files are never changed from here.

## Search

| Type                     | Finds                                               |
|--------------------------|-----------------------------------------------------|
| `bowie`                  | title, artist, album or genre contains "bowie"      |
| `"dark side"`            | a phrase                                            |
| `artist=queen`           | artist contains (also `artist:queen`)               |
| `composer=bach`          | any field: `label=xl`, `mood=happy`, `comment=live`, `bpm>120` |
| `catalognumber=XL`       | any tag in the files, even without a column        |
| `artist="queen"`         | artist is exactly Queen                             |
| `genre=jazz\|blues`      | either                                              |
| `!live` or `-live`       | excludes                                            |
| `year>1990` `rating>=4`  | numbers: `= != < <= > >=`                           |
| `#(plays = 0)`           | Quod Libet syntax works too                         |
| `#(added < 30 days)`     | added (or `lastplayed`) within a time span          |
| `#(length > 6:00)`       | durations as m:ss                                   |

Terms combine (all must match): `genre=rock year<1980 !live #(rating >= 4)`.

**Settings → Search** sets how searching works:
- **Your library:** search *as you type* or only *when you press Enter* (handy for a big library); and where
  plain words (not `artist=` or `year>`) look — title, artist, album, album artist, genre, composer, the
  comment / label / mood / grouping tags, and (off at first) the file name and folder.
- **Online results:** *Search online too* as you type (after a 1, 2 or 3 second pause), only when you press
  Enter, or never; and whether the line under your songs starts folded or open.
- **Online sources:** which to search — the Internet Archive, Openverse, Audius and your own sources (for the
  Discover tab, Find similar and the library's online line); where the menu by the Search online box
  starts (Anything, Artist, Song title, Album, Genre); and the filters it starts with.
- **Radio stations:** how many stations a search on the Radio page lists (50, 150 or 300).

## Storage

Settings → Library → **Storage** shows how much space Musicwell's saved data takes — covers and artist photos,
lyrics found online, seek bar waveforms, similar artists and genres — and altogether. **Clear cache…** lets you
choose which to delete (it's all looked up again as it's needed; your music files, `cover.jpg` files and the
covers inside your songs are never touched). **Open folder** shows where it's kept (`~/.cache/musicwell`).

## When something goes wrong

Musicwell keeps a **log**: a plain text diary of what happened — when it started and closed (with the versions
of everything, the desktop and the sound system), each song and station played, library scans, layouts
switched, casting, and every problem: songs that wouldn't play, stations that dropped, the sound running dry,
Qt's warnings and anything that went wrong inside Musicwell, with the details needed to fix it.

**About (F1) → System → Open log** opens it. It's `~/.local/state/musicwell/musicwell.log` (on Windows
`%APPDATA%\Musicwell\logs\musicwell.log`), up to 1 MB plus the two before it (`musicwell.log.1`, `.2`).
Attach it to a bug report together with the System details (**Copy**). It never leaves your computer unless
you share it. Casting also keeps its own, more detailed `~/.cache/musicwell/cast.log`, and image look-ups
`~/.cache/musicwell/images.log`.

## Licence

Musicwell is free software: you can redistribute it and/or modify it under the terms of the **GNU General
Public License, version 3 or (at your option) any later version** (`GPL-3.0-or-later`), as published by the Free
Software Foundation. It comes with **no warranty**. The full text is in [`LICENSE`](LICENSE).

The **Musicwell name and icon** are not covered by that licence: they may not be used for other projects,
including modified versions (forks). If you publish your own version, give it a different name and icon.

Musicwell is built on free software — Python, Qt and PySide6, FFmpeg, Mutagen, NumPy, PyChromecast, SoCo and
others — each under its own licence. **About (F1) → Credits** lists them; **Licences…** there opens
[`licenses/THIRD-PARTY-NOTICES.md`](licenses/THIRD-PARTY-NOTICES.md), with every component, its licence and
where to get the source, and the full licence texts beside it (in the AppImage: `opt/musicwell/licenses`).

## In the applications menu

The AppImage is just a file, so at first your desktop doesn't know about it. Tick Settings → Devices & desktop →
**Show Musicwell in the applications menu** and Musicwell, with its icon, appears in the menu (to start or pin
it) and the desktop shows its icon on the window. It's `~/.local/share/applications/musicwell.desktop`; it follows
the AppImage if you move or rename it, and unticking removes it. (Installed from the Snap Store, as a package or with a tool like
Gear Lever, the menu entry is theirs and the tick box doesn't appear.)

## Startup

The window opens straight away and your songs load in the background (about a second for 30,000
songs); the library check for new and changed files runs after that. Chromecast support loads
the first time it's needed.

## Library

- Reads MP3, FLAC, Ogg Vorbis, Opus, M4A/AAC/ALAC, WAV, AIFF, WavPack, APE, WMA, Musepack.
- Rescans are incremental and run in the background; ratings and play counts survive retagging.
- **Big collections (20,000+ songs) load quickly and smoothly.** A scan first looks through the folders
  for new or changed songs (names and dates only — quick), then reads their tags in helper processes on
  your computer's other cores (up to 6), so the window and the music stay smooth. A bar under the top bar
  shows how far it's got (*Reading songs… 9,985 of 22,000*), and the songs found so far appear and can be
  played while it carries on. Each file is read once (not twice, as before). A song that won't finish
  reading (a stuck network share) is skipped after a while instead of stopping the scan; folder links
  that lead back into themselves are followed only once.
- **Covers stay light:** big embedded pictures (3000 × 3000) are read at a sensible size, the covers kept
  in memory have a limit, and the Albums page lets go of covers far off screen — so thousands of albums
  don't fill the memory.
- A file that can't be added (damaged, not really audio, a name that isn't valid text, an odd tag) is skipped
  and the scan carries on; the message at the end says how many, and the log (About → System → Open log)
  lists each one with the reason.
- A play counts once you've heard half the track (or 4 minutes); skips are tracked too.
- **Mute works from the taskbar too:** the speaker KDE Plasma puts on Musicwell's taskbar button mutes and
  unmutes it, and Musicwell's own mute button follows (and the other way round — muting in Musicwell shows
  on the taskbar). The mute stays on for the next song. (Uses `pactl`, part of PipeWire and PulseAudio.)
- **Long song names show in full** in the side panel (they wrap onto as many lines as they need — radio
  stations' long titles too); the play bar shortens them with "…" and shows the whole name when you point at it.
- **The seek bar moves steadily** with what you hear. Click or drag to a spot and the line stays there
  until the sound from that spot is heard, then carries on — it doesn't jump back to where it was, or about
  while the sound catches up.
- **Edit tags** (Ctrl+E) on one or many songs; fields that differ are left alone unless you type in them.
- **Play queue** plays before the rest of the list (Ctrl+Enter to add, Ctrl+Shift+Enter to play next).
- **Playlists** with M3U import/export.
- **Album covers**: your own pick, then the file's embedded cover, then `cover.jpg` / `folder.jpg` /
  `front.jpg`, then free online sources.
- **Artist photos**: your own pick, then `artist.jpg` in the artist's folder
  (`Music/Artist/artist.jpg`; `.png` and `.webp` work too, and so do `band`, `artistimage`, `folder`,
  and Kodi's `fanart` and `thumb`), then free online sources.
- Remembers the last song and position, window layout and column setup.

Data lives in `~/.local/share/musicwell/library.db`, artist photos in `~/.cache/musicwell/`.

## Keys

| Key | Action | Key | Action |
|---|---|---|---|
| Space | Play / pause | Ctrl+F | Search |
| Ctrl+→ / Ctrl+← | Next / previous | Esc | Clear search |
| Ctrl+S | Shuffle | Ctrl+J | Jump to the playing song |
| Ctrl+R | Repeat mode | Ctrl+E | Edit tags |
| Ctrl+↑ / Ctrl+↓ | Volume | Alt+0…5 | Rate selected songs |
| Ctrl+Enter | Add to queue | Alt+↑ / Alt+↓ | Reorder queue |
| Ctrl+1…9 | the tabs, in the order shown | F9 | Toggle the left panel |
| Ctrl+L | Lyrics page on / off | Ctrl+F5 | Reload cover and artist photo |
| F1 | About Musicwell | Ctrl+F9 | The panel across the top (or bottom) |
| Ctrl+Alt+1…9 | Switch layout | F5 | Rescan music folders for new and changed songs |
| Ctrl+Shift+E | Equalizer | Ctrl+B | Show / hide the column browser |
| Ctrl+Shift+F | Find similar to the playing song | Ctrl+Shift+L | ♥ Like the song on the radio |
| Ctrl+, | Settings | Ctrl+Q | Quit |
| F2 | Lock / unlock the window | Ctrl+Z / Ctrl+Shift+Z | Undo / redo moving or changing an item |

Every shortcut can be changed in Settings → **Keyboard**.

## Project layout

```
musicwell/
  app.py         startup
  log.py         the log (About → System → Open log)
  menuentry.py   the applications menu entry (Settings → Devices & desktop)
  mainwindow.py  wires everything together
  widgets.py     column browser, song table, small pieces
  bar.py         the customizable bottom bar and seek bar
  lyrics.py      lyrics sources (files, tags, LRCLIB) and LRC parsing
  lyricsview.py  the scrolling lyrics view and the Lyrics page
  waveform.py    song waveforms for the seek bar
  stats.py       the Stats page
  layouts.py     saving, applying and the built-in layout presets
  layoutui.py    the Layouts menu and windows
  artistlist.py  the artist list (an item for either panel)
  albumlist.py   All albums for either panel
  artistinfo.py  About the artist (Wikipedia, MusicBrainz)
  artistview.py  the artist page: photo, albums and songs, in the Library tab
  albumsview.py  All albums: every album as covers (Library tab, or a tab of its own)
  customtabs.py  tabs of your own: a playlist or a search (Favourites, Recently added…)
  freemusic.py   Discover → Search online and My sources (also Like this → Free music)
  sources.py     your own sources: feeds, M3U/PLS playlists, audio links and web folders
  system.py      what differs between Linux and Windows
  winkeys.py     media keys on Windows
  models.py      song table model, star rating delegate
  library.py     SQLite library, background scanner, playlists
  tagworker.py   helper processes that read songs' tags for a scan (big collections)
  sysmute.py     Musicwell's mute and the desktop's (the taskbar speaker) kept as one
  player.py      playback, shuffle/repeat, queue, play counting
  desktop.py     media keys and desktop media controls (MPRIS), notifications, the tray icon
  audio.py       threaded audio output (decoder → EQ → sound card), gapless
  eq.py          10-band equalizer and presets
  eqwindow.py    equalizer window
  eqio.py        equalizer preset import / export
  radio.py       internet radio: station directory, favourites, song-title relay
  radioview.py   the Radio page
  similar.py     Find similar (your library + ListenBrainz)
  similarview.py Discover → Like this (Find similar)
  ia.py          the Internet Archive: free music search and playable tracks
  ov.py          Openverse: Creative Commons music search
  visualizer.py  spectrum visualizer
  panel.py       the rearrangeable now playing panel
  fields.py      every column/field, including custom ones
  cast.py        Chromecast discovery, control and the small media server
  sonos.py       Sonos speakers (SoCo): discovery, control, converting hi-res for them
  casting.py     one cast menu for Chromecast and Sonos
  artsources.py  free online cover / artist photo sources
  artpicker.py   the Find image window
  query.py       search syntax
  tags.py        tag reading/writing and artwork (mutagen)
  artwork.py     album art cache, artist photos, accent colour
  theme.py       colours, stylesheet, icons
  dialogs.py     settings, tag editor, browser column editor
Musicwell.pyw                    starts Musicwell on Windows (no console window)
Install Musicwell.bat            Windows set-up: packages in .venv, Start-menu and desktop shortcuts
Musicwell (show messages).bat    Windows: start with a console that shows error messages
Remove Musicwell shortcuts.bat   Windows: remove the shortcuts
requirements-windows.txt          the Python packages on Windows
windows/                          the set-up's helpers (Python check, shortcuts, the .ico maker)
```
