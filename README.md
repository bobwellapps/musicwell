# Musicwell

Musicwell is a music player and organiser, simple or fully customisable, with lyrics, radio,
Chromecast and Sonos. It plays your own music collection on Linux (MP3, FLAC, Ogg, Opus, M4A/AAC,
WAV and more), with album art, artist photos, synced lyrics and a visualizer.

<img width="1920" height="1080" alt="Albums" src="https://github.com/user-attachments/assets/c9dbe70d-e9ab-429a-b1da-4599444c1925" />
<img width="1920" height="1080" alt="Artists" src="https://github.com/user-attachments/assets/0a7a3d36-bbe9-458f-84de-64cea210c3db" />
<img width="1920" height="1080" alt="Lyrics" src="https://github.com/user-attachments/assets/0af8c1fa-4cf2-4ed1-b12e-6ec990beba3a" />
<img width="1920" height="1080" alt="Unlocked" src="https://github.com/user-attachments/assets/1aa2639c-04bc-408e-b758-5168c7a40045" />


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


