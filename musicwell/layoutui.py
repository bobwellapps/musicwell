"""The Layouts menu and the Save / Manage layouts dialogs."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox, QPushButton,
                               QVBoxLayout)

from musicwell import layouts as L

EXT = "Musicwell layout (*.musicwell-layout *.listenwell-layout *.tunewell-layout *.json)"


def _small(act):
    """A small bold section heading in a menu."""
    f = act.font()
    f.setPointSizeF(max(7.0, f.pointSizeF() * 0.8))
    f.setBold(True)
    f.setLetterSpacing(f.SpacingType.AbsoluteSpacing, 1)
    act.setFont(f)


def fill_menu(menu: QMenu, w):
    menu.clear()
    menu.setToolTipsVisible(True)
    current = w.settings.value("layout_current", "")
    head = menu.addAction("LAYOUTS")
    head.setEnabled(False)
    _small(head)
    presets = L.all_presets(w.settings)
    n = 0
    for name, desc, _d, builtin in presets:
        if not builtin and n == len(L.BUILTIN):
            menu.addSeparator()
        n += 1
        changed = w.layout_has_changes(name)
        label = name + ("  (changed)" if changed else "") + (f"\tCtrl+Alt+{n}" if n <= 9 else "")
        a = menu.addAction(label, lambda nm=name: w.use_layout(nm))
        a.setCheckable(True)
        a.setChecked(name == current)
        a.setToolTip(desc + ("\n\nYou've changed it — Reset layouts puts it back as it came." if changed else ""))
    rm = menu.addMenu("Reset layouts")
    rm.setToolTipsVisible(True)
    for name, _desc, _d, builtin in presets:
        changed = w.layout_has_changes(name)
        a = rm.addAction(name + ("  (in use)" if name == current else ""), lambda nm=name: w.reset_layout(nm))
        a.setEnabled(changed)
        a.setToolTip("Back as it came — what you changed in it is forgotten" if builtin
                     else "Back as you saved it")
    rm.addSeparator()
    rm.addAction("Radio tab", lambda: w.reset_tab_setup("5")).setToolTip(
        "Its own panels back as they came: just the panel on the right")
    rm.addAction("Lyrics tab", lambda: w.reset_tab_setup("3")).setToolTip(
        "Its own panels back as they came: just the panel on the right")
    rm.addSeparator()
    rm.addAction("Every layout…", w.reset_all_layouts)
    lm = menu.addMenu("Save and manage layouts")
    lm.addAction("New empty layout…", w.new_empty_layout).setToolTip(
        "Start from a blank window — an empty panel and just a play button — and add what you want")
    lm.addAction("Save current layout as…", w.save_layout_as)
    user = L.load_user(w.settings)
    if current in user:
        lm.addAction(f"Update “{current}” with the current layout", lambda: w.update_layout(current))
    lm.addAction("Manage layouts…", w.manage_layouts)
    menu.addSeparator()
    menu.addAction("Undo moving or changing an item\t" + w.shortcut_text("undo"), w.undo_layout).setEnabled(
        bool(w._undo) or w._undo_timer.isActive())
    menu.addAction("Redo\t" + w.shortcut_text("redo"), w.redo_layout).setEnabled(bool(w._redo))
    if getattr(w, "customizing", False):
        menu.addAction("🔒  Lock (nothing moves)\t" + w.shortcut_text("lock"), lambda: w.set_customizing(False))
    else:
        menu.addAction("🔓  Unlock to rearrange\t" + w.shortcut_text("lock"), lambda: w.set_customizing(True))


class SaveLayoutDialog(QDialog):
    def __init__(self, w, name: str = "", parent=None):
        super().__init__(parent or w)
        self.w = w
        self.setWindowTitle("Save layout")
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        intro = QLabel("Saves the panel, the play bar, the column browser, the song list columns, "
                       "the sizes of each area and the visualizer style.")
        self.intro = intro
        intro.setWordWrap(True)
        intro.setObjectName("EmptyText")
        lay.addWidget(intro)
        self.name = QLineEdit(name)
        self.name.setPlaceholderText("Name, e.g. Evening, Party, Big screen")
        self.desc = QLineEdit("")
        self.desc.setPlaceholderText("Description (optional)")
        self.colours = QCheckBox("Include the theme and accent colour")
        for x in (self.name, self.desc, self.colours):
            lay.addWidget(x)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setObjectName("Primary")
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _ok(self):
        name = self.name.text().strip()
        if not name:
            self.name.setFocus()
            return
        if name in L.BUILTIN:
            QMessageBox.information(self, "Save layout", f"“{name}” is one of the built-in layouts. "
                                                         "Please choose another name.")
            return
        if name in L.load_user(self.w.settings) and QMessageBox.question(
                self, "Save layout", f"Replace your layout “{name}”?") != QMessageBox.Yes:
            return
        self.accept()


class ManageLayoutsDialog(QDialog):
    def __init__(self, w, parent=None):
        super().__init__(parent or w)
        self.w = w
        self.setWindowTitle("Layouts")
        self.resize(560, 420)
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        self.list = QListWidget()
        self.list.setObjectName("Pane")
        self.list.itemDoubleClicked.connect(lambda _: self._use())
        self.list.currentItemChanged.connect(lambda *_: self._update())
        row.addWidget(self.list, 1)
        side = QVBoxLayout()
        self.use_btn = QPushButton("Use")
        self.use_btn.setObjectName("Primary")
        self.save_btn = QPushButton("Save current as…")
        self.update_btn = QPushButton("Update with current")
        self.rename_btn = QPushButton("Rename…")
        self.delete_btn = QPushButton("Delete")
        self.export_btn = QPushButton("Export…")
        self.import_btn = QPushButton("Import…")
        for b, fn in ((self.use_btn, self._use), (self.save_btn, self._save_as), (self.update_btn, self._update_one),
                      (self.rename_btn, self._rename), (self.delete_btn, self._delete),
                      (self.export_btn, self._export), (self.import_btn, self._import)):
            b.clicked.connect(fn)
            side.addWidget(b)
        side.addStretch()
        row.addLayout(side)
        lay.addLayout(row)
        self.desc = QLabel("")
        self.desc.setObjectName("EmptyText")
        self.desc.setWordWrap(True)
        lay.addWidget(self.desc)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._fill()

    def _fill(self, select: str | None = None):
        current = self.w.settings.value("layout_current", "")
        select = select or current
        self.list.clear()
        for name, desc, _d, builtin in L.all_presets(self.w.settings):
            it = QListWidgetItem(("✓  " if name == current else "     ") + name + ("   · built in" if builtin else ""))
            it.setData(Qt.UserRole, (name, desc, builtin))
            self.list.addItem(it)
            if name == select:
                self.list.setCurrentItem(it)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self._update()

    def _sel(self):
        it = self.list.currentItem()
        return it.data(Qt.UserRole) if it else (None, "", True)

    def _update(self):
        name, desc, builtin = self._sel()
        for b in (self.update_btn, self.rename_btn, self.delete_btn):
            b.setEnabled(bool(name) and not builtin)
        self.use_btn.setEnabled(bool(name))
        self.export_btn.setEnabled(bool(name))
        self.desc.setText(desc or ("Your layout." if name and not builtin else ""))

    def _use(self):
        name = self._sel()[0]
        if name:
            self.w.use_layout(name)
            self._fill(name)

    def _save_as(self):
        name = self.w.save_layout_as()
        if name:
            self._fill(name)

    def _update_one(self):
        name = self._sel()[0]
        if name and QMessageBox.question(self, "Layouts", f"Replace “{name}” with the current layout?") \
                == QMessageBox.Yes:
            self.w.update_layout(name)
            self._fill(name)

    def _rename(self):
        name = self._sel()[0]
        user = L.load_user(self.w.settings)
        if name not in user:
            return
        dlg = SaveLayoutDialog(self.w, name, self)
        dlg.setWindowTitle("Rename layout")
        dlg.desc.setText(user[name].get("description", ""))
        dlg.colours.hide()
        if dlg.exec():
            new = dlg.name.text().strip()
            d = user.pop(name)
            d["description"] = dlg.desc.text().strip()
            user[new] = d
            L.save_user(self.w.settings, user)
            ch = L.load_changes(self.w.settings)
            if name in ch:
                ch[new] = ch.pop(name)
                L.save_changes(self.w.settings, ch)
            self.w.layout_renamed(name, new)
            if self.w.settings.value("layout_current", "") == name:
                self.w.settings.setValue("layout_current", new)
                self.w._snap_layout()
            self._fill(new)

    def _delete(self):
        name = self._sel()[0]
        user = L.load_user(self.w.settings)
        if name in user and QMessageBox.question(self, "Layouts", f"Delete your layout “{name}”?") \
                == QMessageBox.Yes:
            user.pop(name)
            L.save_user(self.w.settings, user)
            self.w._forget_changes(name)
            if self.w.settings.value("layout_current", "") == name:
                self.w.settings.setValue("layout_current", "")
            self._fill()

    def _export(self):
        name = self._sel()[0]
        d, _ = L.find(self.w.settings, name)
        if d is None:
            return
        f, _ = QFileDialog.getSaveFileName(self, "Export layout",
                                           os.path.join(os.path.expanduser("~"), f"{name}.musicwell-layout"), EXT)
        if f:
            try:
                L.export_file(f, name, d)
            except OSError as e:
                QMessageBox.warning(self, "Export layout", f"Couldn't save the file: {e.strerror}")

    def _import(self):
        f, _ = QFileDialog.getOpenFileName(self, "Import layout", os.path.expanduser("~"), EXT)
        if not f:
            return
        try:
            name, d = L.import_file(f)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Import layout", str(e))
            return
        user = L.load_user(self.w.settings)
        base, n = name, 2
        while name in user or name in L.BUILTIN:
            name = f"{base} ({n})"
            n += 1
        user[name] = d
        L.save_user(self.w.settings, user)
        self._fill(name)
