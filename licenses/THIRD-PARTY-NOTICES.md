# Third-party software in Musicwell

Musicwell itself is licensed under the GNU General Public License, version 3 or later (`LICENSE` in the
project, `GPL-3.0.txt` here). The Musicwell name and icon may not be used for other projects, including
modified versions.

Musicwell is built on the free software below. The Linux AppImage includes all of it; run from the
source folder (or on Windows), the Python packages are installed separately but are the same.

Each component keeps its own licence. The licence texts are in this folder; the Python packages'
own licence files (with their copyright notices) are kept with each package in the AppImage
(`opt/python3.12/lib/python3.12/site-packages/<package>.dist-info/`), and Python's is
`opt/python3.12/LICENSE`.

| Component | What it does in Musicwell | Licence |
|---|---|---|
| [Python](https://www.python.org) 3.12 | runs Musicwell | PSF License 2.0 |
| [Qt](https://www.qt.io) 6 and [PySide6](https://www.qt.io/qt-for-python) / Shiboken6 | the window, sound output, networking | LGPL 3.0 (`LGPL-3.0.txt`, `GPL-3.0.txt`) |
| [FFmpeg](https://ffmpeg.org) (libavcodec, libavformat, libavutil, libswresample, libswscale), as built by Qt | decoding songs and streams | LGPL 2.1 or later (`LGPL-2.1.txt`) |
| [ICU](https://icu.unicode.org) | text handling inside Qt | Unicode / MIT-style (`ICU.txt`) |
| [Mutagen](https://github.com/quodlibet/mutagen) | reading and writing tags | GPL 2.0 or later (`GPL-2.0.txt`) |
| [NumPy](https://numpy.org) | the equalizer, fades, visualizer, album-art colours | BSD 3-Clause (with 0BSD, MIT, Zlib, CC0 parts) |
| [OpenBLAS](https://www.openblas.net), libgfortran, libquadmath (inside NumPy) | maths routines NumPy is built with | BSD 3-Clause; GPL 3.0 with the GCC Runtime Library Exception; LGPL 2.1 — notices in NumPy's licence file |
| [PyChromecast](https://github.com/home-assistant-libs/pychromecast), casttube | casting to Chromecast | MIT |
| [protobuf](https://protobuf.dev) | talking to Chromecasts | BSD 3-Clause |
| [zeroconf](https://github.com/python-zeroconf/python-zeroconf), ifaddr | finding speakers on your network | LGPL 2.1 or later (`LGPL-2.1.txt`); MIT |
| [SoCo](https://github.com/SoCo/soco), xmltodict, appdirs | playing on Sonos | MIT |
| [lxml](https://lxml.de) with libxml2 and libxslt | reading Sonos replies | BSD 3-Clause; MIT |
| [requests](https://requests.readthedocs.io) | web requests for Sonos | Apache 2.0 (`Apache-2.0.txt`) |
| urllib3, charset-normalizer, idna | used by requests | MIT; MIT; BSD 3-Clause |
| [certifi](https://github.com/certifi/python-certifi) | trusted certificates for secure connections | MPL 2.0 (`MPL-2.0.txt`) |
| [dbus-next](https://github.com/altdesktop/python-dbus-next) | media keys, desktop media controls, notifications | MIT |
| OpenSSL 1.1, SQLite, libffi, bzip2, xz (from the portable Python) | secure connections, the library database, Python itself | OpenSSL/SSLeay; public domain; MIT; BSD-style; public domain / 0BSD |
| xcb-util, xcb-util-cursor, -image, -renderutil (fallback only) | X11 support when the system lacks them | MIT (`xcb-util.txt`) |

## LGPL components (Qt, FFmpeg, zeroconf)

These are used as separate, unmodified shared libraries (Qt and FFmpeg in
`opt/python3.12/lib/python3.12/site-packages/PySide6/Qt/lib/`), so you can replace them with your own
builds: extract the AppImage (`./Musicwell-x86_64.AppImage --appimage-extract`), swap the files and
run `squashfs-root/AppRun`. Their source code is available from the projects:

- Qt: <https://download.qt.io/official_releases/qt/> and <https://code.qt.io>
- PySide6 / Shiboken6: <https://code.qt.io/cgit/pyside/pyside-setup.git>
- FFmpeg: <https://ffmpeg.org/download.html> (Qt's build: <https://code.qt.io/cgit/qt/qtmultimedia.git>)
- zeroconf: <https://github.com/python-zeroconf/python-zeroconf>

If you can't get the source from those, ask through Musicwell's project page and it will be provided.

## Online services

Musicwell looks things up on MusicBrainz, the Cover Art Archive, Wikidata, Wikimedia Commons,
Wikipedia, LRCLIB, ListenBrainz, radio-browser.info, the Internet Archive and Openverse. Their data
keeps its own terms (listed in About → Credits); nothing from them is bundled.
