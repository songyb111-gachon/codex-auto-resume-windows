"""The notification card, the Win32 half: layered windows beside the notification area.

`notice_card.py` decides what a card says, where it goes and how it moves; this file puts it on
the screen. It lives on the icon's thread inside the watcher, as the popup does (B-D1): the
icon's thread creates `CardStack`, attaches it to the notifier's `Inbox`, and from then on a
notice posted from any thread arrives here as one message and is shown by this thread alone.

Each card is two layered windows, both `WS_EX_NOACTIVATE`, so a card never takes the focus
from whatever somebody is doing, whatever they click:

* the **shadow**, `WS_EX_TRANSPARENT` as well: the soft floating shadow, painted with per-pixel
  alpha (`UpdateLayeredWindow`) so it spills over the wallpaper. It lets every click through -
  it reaches past the card and over the taskbar, and a shadow must never eat a click on a tray
  icon or the clock;
* the **card**, owned by its shadow so it always stands above it: the popup's card, drawn by the
  popup's own renderer (`popup.Renderer`) at the monitor's scale and then given its rounded
  corners in alpha. Its two buttons are the toast's two buttons.

A frame is one scaled blit of the card, one stamp of the shadow at its depth and one `UpdateLayeredWindow`
each with its alpha. The face is drawn again only for the status light, which breathes on the table the popup's
breathes on (v0.6.7) - at most every 80 ms, and never under Reduce motion or High Contrast - and the frame timer
runs only while something moves. Nothing here can act: a button click calls `on_action(uri)` on a short worker
thread and the card goes away; what the URI may do is decided in `notifier.activate`.

**Every notice ends once.** Each notice this stack takes from the inbox is ended by exactly one
`on_complete(notice, shown)` call, on a worker thread (the host passes `notifier.complete`): `shown` True
once the card has been on screen whole - its first frame at full strength went through
`UpdateLayeredWindow` - or was clicked, or was replaced by a newer card about the same conversation (which
then speaks for it); False when it broke, was pushed out of the stack or the stack went away before it was
ever seen whole, and for every notice still waiting in the inbox when the stack goes. A card that breaks
after it was seen is only taken down: it has been shown, and its history copy is already on its way.

Since v0.6.10-alpha this is the front of ui/card/: win32.py, surfaces.py, card.py
and stack.py. Every name the module had is re-exported here, so `notice_window.CardStack`
reads as it did - and a patch on `_dll` belongs on ui/card/win32.py, where every part
looks it up.
"""
from __future__ import annotations

from .ui.card.win32 import (ABE_BOTTOM, ABE_LEFT, ABE_RIGHT, ABE_TOP, ABM_GETTASKBARPOS, AC_SRC_ALPHA, AC_SRC_OVER, APPBARDATA, BITMAPINFO, BITMAPINFOHEADER, BLENDFUNCTION, COMPOSITING_HIGH_SPEED, HWND_MESSAGE, HWND_TOPMOST, IDC_ARROW, INTERPOLATION_HIGH_QUALITY_BILINEAR, LRESULT, MA_NOACTIVATE, MONITORINFO, MONITOR_DEFAULTTONEAREST, MONITOR_DEFAULTTOPRIMARY, PIXEL_FORMAT_32BPP_PARGB, PIXEL_OFFSET_HALF, SIZE, SWP_NOACTIVATE, SWP_NOMOVE, SWP_NOSIZE, SW_HIDE, SW_SHOWNOACTIVATE, TIMER_FRAME, TIMER_WAIT, TME_LEAVE, TRACKMOUSEEVENT, ULW_ALPHA, UNIT_PIXEL, WM_APP, WM_DESTROY, WM_LBUTTONDOWN, WM_LBUTTONUP, WM_MOUSEACTIVATE, WM_MOUSELEAVE, WM_MOUSEMOVE, WM_NCDESTROY, WM_NOTICE, WM_RBUTTONUP, WM_SETTINGCHANGE, WM_TIMER, WNDCLASSW, WNDPROC, WS_EX_LAYERED, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW, WS_EX_TOPMOST, WS_EX_TRANSPARENT, WS_POPUP, _DECLARED, _DECLARE_LOCK, _declare, _dll, _on_a_worker_thread, _signature, look, screen, taskbar_corner)  # noqa: F401
from .ui.card.surfaces import (_CardRenderer, _Image, _LIVE, _LIVE_LOCK, _Layer, _Surface, _made, gdiplus_objects)  # noqa: F401
from .ui.card.card import (Card)  # noqa: F401
from .ui.card.stack import (CardStack)  # noqa: F401
