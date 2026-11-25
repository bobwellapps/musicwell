"""Global media keys on Windows (RegisterHotKey)."""
from __future__ import annotations

import sys

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal

WM_HOTKEY = 0x0312
MOD_NOREPEAT = 0x4000
KEYS = {  # virtual-key code -> action
    0xB3: "playpause",
    0xB0: "next",
    0xB1: "previous",
    0xB2: "stop",
}
BASE_ID = 0x4C57  # "LW": hot-key ids are BASE_ID + n


class _Filter(QAbstractNativeEventFilter):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner

    def nativeEventFilter(self, event_type, message):
        try:
            et = event_type.data() if hasattr(event_type, "data") else bytes(event_type)
            if et in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
                from ctypes import wintypes
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY:
                    what = self.owner.by_id.get(int(msg.wParam))
                    if what:
                        self.owner.pressed.emit(what)
                        return True, 0
        except Exception:
            pass
        return False, 0


class MediaKeys(QObject):
    pressed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.by_id: dict[int, str] = {}
        self.taken: list[str] = []  # keys another program already has
        self._filter = None

    @staticmethod
    def supported() -> bool:
        return sys.platform == "win32"

    def start(self) -> bool:
        """Register the keys. True if at least one was registered."""
        if not self.supported() or self.by_id:
            return bool(self.by_id)
        import ctypes
        from PySide6.QtCore import QCoreApplication
        user32 = ctypes.windll.user32
        self.taken = []
        for n, (vk, what) in enumerate(KEYS.items()):
            hid = BASE_ID + n
            # No window: Windows posts WM_HOTKEY to this thread's queue.
            if user32.RegisterHotKey(None, hid, MOD_NOREPEAT, vk):
                self.by_id[hid] = what
            else:
                self.taken.append(what)
        if self.by_id and self._filter is None:
            self._filter = _Filter(self)
            QCoreApplication.instance().installNativeEventFilter(self._filter)
        return bool(self.by_id)

    def stop(self):
        if not self.supported():
            return
        import ctypes
        for hid in list(self.by_id):
            ctypes.windll.user32.UnregisterHotKey(None, hid)
        self.by_id.clear()
        if self._filter is not None:
            from PySide6.QtCore import QCoreApplication
            QCoreApplication.instance().removeNativeEventFilter(self._filter)
            self._filter = None
