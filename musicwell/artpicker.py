"""Pick an album cover or artist photo from the free sources or a file."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel,
                               QLineEdit, QListView, QListWidget, QListWidgetItem, QPushButton,
                               QVBoxLayout)

from musicwell import artsources as S

THUMB = 150


class ImagePicker(QDialog):
    _result = Signal(object, bytes)  # Candidate, thumbnail bytes
    _source_done = Signal(str, int)  # source, result count
    _full = Signal(bytes, str)  # image, or b"" and an error

    def __init__(self, kind: str, artist: str, album: str, store, key: str, parent=None):
        super().__init__(parent)
        self.kind, self.store, self.key = kind, store, key
        self.setWindowTitle("Search for album image" if kind == "album" else "Search for artist image")
        self.resize(760, 600)
        self.pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="musicwell-picker")
        self._gen = 0
        self._busy = set()
        self._chosen = None

        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        row = QHBoxLayout()
        self.artist = QLineEdit(artist)
        self.artist.setPlaceholderText("Artist")
        self.album = QLineEdit(album)
        self.album.setPlaceholderText("Album")
        self.album.setVisible(kind == "album")
        go = QPushButton("Search")
        go.clicked.connect(self.search)
        for w in (self.artist, self.album):
            w.returnPressed.connect(self.search)
        row.addWidget(self.artist, 1)
        row.addWidget(self.album, 1)
        row.addWidget(go)
        lay.addLayout(row)
        where = ("the Cover Art Archive (MusicBrainz)" if kind == "album"
                 else "Wikipedia, Wikidata and Wikimedia Commons")
        intro = QLabel(f"Free {'covers' if kind == 'album' else 'photos'} from {where}, free to use. "
                       "For any other picture, use <b>Search the web…</b> below.")
        intro.setObjectName("EmptyText")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.status = QLabel("")
        self.status.setObjectName("EmptyText")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        self.grid = QListWidget()
        self.grid.setViewMode(QListView.IconMode)
        self.grid.setIconSize(QSize(THUMB, THUMB))
        self.grid.setGridSize(QSize(THUMB + 26, THUMB + 54))
        self.grid.setResizeMode(QListView.Adjust)
        self.grid.setMovement(QListView.Static)
        self.grid.setWordWrap(True)
        self.grid.setSpacing(6)
        self._touched = False
        self.grid.itemSelectionChanged.connect(self._update_buttons)
        self.grid.itemPressed.connect(lambda _: setattr(self, "_touched", True))
        self.grid.itemDoubleClicked.connect(lambda _: self._use())
        lay.addWidget(self.grid, 1)

        bottom = QHBoxLayout()
        self.file_btn = QPushButton("Choose a file…")
        self.file_btn.clicked.connect(self._from_file)
        self.web_btn = QPushButton("Search the web…")
        self.web_btn.setToolTip("Opens your web browser on an image search. Drag a picture from it into this "
                                "window, or copy it (right-click → Copy image) and click Paste.")
        self.web_btn.clicked.connect(self._search_web)
        self.paste_btn = QPushButton("Paste")
        self.paste_btn.setToolTip("A picture you copied in your browser (or a picture's web address) — Ctrl+V")
        self.paste_btn.clicked.connect(self._paste)
        QShortcut(QKeySequence.Paste, self, activated=self._paste)
        self.setAcceptDrops(True)
        self.orig_btn = QPushButton("Back to automatic")
        self.orig_btn.setToolTip("Forget your choice and use the file's own image / the first one found online")
        self.orig_btn.clicked.connect(self._original)
        self.orig_btn.setVisible(store.has_override(kind, key))
        bottom.addWidget(self.web_btn)
        bottom.addWidget(self.paste_btn)
        bottom.addWidget(self.file_btn)
        bottom.addWidget(self.orig_btn)
        bottom.addStretch()
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.use_btn = self.buttons.button(QDialogButtonBox.Ok)
        self.use_btn.setText("Use this image")
        self.use_btn.setObjectName("Primary")
        self.use_btn.setEnabled(False)
        self.buttons.accepted.connect(self._use)
        self.buttons.rejected.connect(self.reject)
        bottom.addWidget(self.buttons)
        lay.addLayout(bottom)

        self._result.connect(self._add_result)
        self._source_done.connect(self._on_source_done)
        self._full.connect(self._on_full)
        self.search()

    def _sources(self) -> list[str]:
        names = S.DEFAULT_ALBUM_ORDER if self.kind == "album" else S.DEFAULT_ARTIST_ORDER
        return list(names)

    def search(self):
        if hasattr(self, "web_btn"):
            self._light_web(False)
        self._gen += 1
        gen = self._gen
        self._touched = False
        self.grid.clear()
        artist, album = self.artist.text().strip(), self.album.text().strip()
        if not artist or (self.kind == "album" and not album):
            self.status.setText("Type the artist" + (" and album" if self.kind == "album" else "") + ".")
            return
        sources = self._sources()
        self._busy = set(sources)
        self._counts = {}
        self._problems = {}
        self._show_status()

        for src in sources:
            def work(src=src):
                cands, problem = S.search_verbose(self.kind, src, artist, album)
                if problem:
                    self._problems[src] = problem
                n = 0
                for c in cands[:6]:
                    if gen != self._gen:
                        return
                    try:
                        data = S.get_bytes(c.thumb, limit=4 * 1024 * 1024)
                    except Exception as ex:
                        self._problems.setdefault(src, f"couldn't download the pictures ({ex})")
                        continue
                    if S.is_image(data):
                        n += 1
                        self._result.emit((gen, c), data)
                self._source_done.emit(f"{gen}:{src}", n)
            self.pool.submit(work)

    def _show_status(self):
        names = [S.Candidate("", "", s).source_name.split(" (")[0] for s in self._busy]
        found = self.grid.count()
        if self._busy:
            self.status.setText(f"Searching {', '.join(sorted(names))}…  {found} found so far")
        elif found:
            self.status.setText(f"{found} image{'s' if found != 1 else ''} found. Pick one and press "
                                "“Use this image” (or double-click it).")
        else:
            self.status.setText(self._nothing_found())
        problems = getattr(self, "_problems", {})
        if problems and not self._busy:
            lines = [f"{S.Candidate('', '', k).source_name.split(' (')[0]}: {v}" for k, v in problems.items()]
            note = "Some services didn't answer — " + "; ".join(lines)
            text = self.status.text()
            if text.startswith("<p"):
                from html import escape
                self.status.setText(text + f"<p style='margin-top:6px'>{escape(note)}</p>")
            else:
                self.status.setText(text + "\n" + note)

    def _nothing_found(self) -> str:
        """Nothing found: explain how to use a picture from the web."""
        who = self.artist.text().strip() or "them"
        if self.kind == "album" and self.album.text().strip():
            who = f"{self.album.text().strip()} by {who}"
        what = "cover" if self.kind == "album" else "photo"
        self._light_web(True)
        from html import escape
        spell = ", try a shorter album name" if self.kind == "album" else ""
        return (f"<p style='margin:0'>No free {what} found for <b>{escape(who)}</b>. "
                "<b>Try searching the web:</b></p>"
                "<ol style='margin-top:4px; margin-bottom:4px'>"
                "<li>Click <b>Search the web…</b> below — your web browser opens on an image search.</li>"
                "<li>Find a picture you like and <b>drag it into this window</b>.<br>"
                "Or right-click it → <i>Copy image</i>, come back here and click <b>Paste</b>.</li>"
                "</ol>"
                f"<p style='margin:0'>Or check the spelling{spell}, or <b>Choose a file…</b> of your own.</p>")

    def _light_web(self, on: bool):
        self.web_btn.setObjectName("Primary" if on else "")
        self.web_btn.style().unpolish(self.web_btn)
        self.web_btn.style().polish(self.web_btn)

    def _add_result(self, payload, data: bytes):
        gen, cand = payload
        if gen != self._gen:
            return
        img = QImage.fromData(data)
        if img.isNull():
            return
        for i in range(self.grid.count()):  # Wikipedia and Wikidata often return the same photo
            if self.grid.item(i).data(Qt.UserRole).url == cand.url:
                return
        pm = QPixmap.fromImage(img.scaled(THUMB, THUMB, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        where = cand.source_name.split(" (")[0]
        if cand.source == "wikis":
            lang = cand.label.rsplit("— ", 1)[-1].split(".wikipedia", 1)[0] if ".wikipedia" in cand.label else ""
            where = f"Wikipedia ({lang})" if lang else "Wikipedia"
        it = QListWidgetItem(QIcon(pm), f"{where}\n{img.width()}×{img.height()} preview")
        it.setData(Qt.UserRole, cand)
        tip = f"{cand.label}\nfrom {cand.source_name}"
        if cand.license:
            tip += f"\n{cand.credit} · {cand.license}"
        it.setToolTip(tip)
        it.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
        order = self._sources()
        rank = lambda c: order.index(c.source) if c.source in order else len(order)
        row = self.grid.count()
        while row > 0 and rank(self.grid.item(row - 1).data(Qt.UserRole)) > rank(cand):
            row -= 1
        self.grid.insertItem(row, it)
        if not self._touched:
            self.grid.blockSignals(True)
            self.grid.setCurrentRow(0)  # preselect the best one
            self.grid.blockSignals(False)
            self._update_buttons()
        self._show_status()

    def _on_source_done(self, tag: str, n: int):
        gen, src = tag.split(":", 1)
        if int(gen) != self._gen:
            return
        self._busy.discard(src)
        self._show_status()

    def _update_buttons(self):
        self.use_btn.setEnabled(bool(self.grid.selectedItems()))

    def _use(self):
        items = self.grid.selectedItems()
        if not items:
            return
        cand = items[0].data(Qt.UserRole)
        self._chosen = cand
        self.use_btn.setEnabled(False)
        self.status.setText(f"Downloading the full-size image from {cand.source_name.split(' (')[0]}…")

        def work():
            try:
                data = S.get_bytes(cand.url)
                if not S.is_image(data):
                    raise ValueError("not an image")
                self._full.emit(data, "")
            except Exception as ex:
                self._full.emit(b"", str(ex))
        self.pool.submit(work)

    def _on_full(self, data: bytes, error: str):
        if not data:
            self.status.setText(f"That one couldn't be downloaded ({error}). Try another.")
            self.use_btn.setEnabled(True)
            return
        cand = self._chosen
        self.store.set_override(self.kind, self.key, data, cand.info() if cand else None)
        self.accept()

    def _from_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "Choose an image", "",
                                           "Images (*.jpg *.jpeg *.png *.webp *.bmp *.gif)")
        if not f:
            return
        with open(f, "rb") as fh:
            data = fh.read()
        if QImage.fromData(data).isNull():
            self.status.setText("That file isn't an image Musicwell can read.")
            return
        self.store.set_override(self.kind, self.key, data)
        self.accept()

    def _search_web(self):
        from musicwell import webimage as WI
        from PySide6.QtCore import QSettings
        engine = WI.engine_of(QSettings())
        WI.open_search(self.kind, self.artist.text().strip(), self.album.text().strip(), engine)
        self.status.setText(f"Searching {WI.ENGINES[engine][0]} in your browser. Drag a picture from it into this "
                            "window — or right-click it → Copy image, then Paste here.")

    def _paste(self):
        from musicwell import webimage as WI
        found = WI.extract(QApplication.clipboard().mimeData())
        if not found:
            self.status.setText("There's no picture to paste. In your browser, right-click a picture → Copy image "
                                "(or Copy image address), then Paste.")
            return
        self._take(found)

    def dragEnterEvent(self, e):
        from musicwell import webimage as WI
        if WI.accepts(e.mimeData()):
            e.setDropAction(Qt.CopyAction)
            e.accept()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        self.dragEnterEvent(e)

    def dropEvent(self, e):
        from musicwell import webimage as WI
        found = WI.extract(e.mimeData())
        e.setDropAction(Qt.CopyAction)
        e.accept()
        if found:
            self._take(found)

    def _take(self, found: dict):
        from musicwell import webimage as WI
        self.status.setText("Getting the picture…")
        for b in (self.web_btn, self.paste_btn, self.file_btn):
            b.setEnabled(False)
        t = WI.Taker(found, self)
        t.done.connect(self._taken)
        t.failed.connect(self._not_taken)
        t.start()

    def _taken(self, data: bytes, info: dict, note: str):
        self.store.set_override(self.kind, self.key, data, info)
        self.accept()

    def _not_taken(self, why: str):
        for b in (self.web_btn, self.paste_btn, self.file_btn):
            b.setEnabled(True)
        self.status.setText(f"Couldn't use that picture: {why}.")

    def _original(self):
        self.store.set_override(self.kind, self.key, None)
        self.accept()

    def done(self, r):
        self._gen += 1  # ignore results from older searches
        self.pool.shutdown(wait=False, cancel_futures=True)
        super().done(r)
