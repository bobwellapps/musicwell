"""Helpers for building right-click menus in a consistent layout."""
from __future__ import annotations

from PySide6.QtWidgets import QMenu

MAX_TITLE = 46


def esc(text: str) -> str:
    """Escape "&" for menu text."""
    return (text or "").replace("&", "&&")


def title(m: QMenu, text: str):
    text = (text or "").strip() or "Unknown"
    if len(text) > MAX_TITLE:
        text = text[:MAX_TITLE - 1].rstrip() + "…"
    a = m.addAction(esc(text))
    f = a.font()
    f.setBold(True)
    a.setFont(f)
    a.setEnabled(False)
    return a


def check(m: QMenu, text: str, on: bool, fn, tip: str = ""):
    a = m.addAction(text, fn)
    a.setCheckable(True)
    a.setChecked(bool(on))
    if tip:
        a.setToolTip(tip)
        m.setToolTipsVisible(True)
    return a


def tidy(m: QMenu):
    """Remove leading, trailing and doubled separators."""
    prev_sep = True
    acts = m.actions()
    for a in acts:
        if a.isSeparator():
            if prev_sep:
                m.removeAction(a)
                continue
            prev_sep = True
        else:
            prev_sep = False
    acts = m.actions()
    while acts and acts[-1].isSeparator():
        m.removeAction(acts.pop())


def add_actions(m: QMenu, acts):
    """[(label, fn)] into a menu; ("", None) is a separator."""
    for label, fn in acts:
        if fn is None:
            m.addSeparator()
        else:
            m.addAction(label, fn)
    tidy(m)
