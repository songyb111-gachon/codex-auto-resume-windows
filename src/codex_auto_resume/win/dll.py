"""A private handle on a system DLL, and the window declarations more than one module needs.

`ctypes.windll` is shared by the whole process, so the argument types one module sets on a
function would silently change how every other module's calls into the same DLL convert theirs.
Five modules had the same five-line cache written out to avoid that, each with its own comment
explaining why. `library()` is that rule, once: it hands back a *fresh* cache, so every caller
still gets handles of its own and nothing here is shared between them.

The window class declarations below are the exception, and they are shared on purpose: the
notification-area icon, the popup and the notification card all register real windows, and a
`WNDPROC` that is not the same ctypes type on both sides of a call is a crash rather than a
mistake. They lived in `tray.py` and were imported back out of it by the two modules that draw,
which is the import cycle `tests/test_layers.py` has listed since v0.6.5.
"""
from __future__ import annotations

import ctypes as C
import ctypes.wintypes as W


def library():
    """A `dll(name)` of one's own: every module that calls it gets a separate cache.

        _dll = library()
        user32 = _dll("user32")

    Two modules asking for "user32" get two `WinDLL` objects, so the `argtypes` one declares
    are invisible to the other.
    """
    cache = {}

    def dll(name):
        if name not in cache:
            cache[name] = C.WinDLL(name, use_last_error=True)
        return cache[name]

    return dll


LRESULT = C.c_ssize_t
WNDPROC = C.WINFUNCTYPE(LRESULT, W.HWND, W.UINT, W.WPARAM, W.LPARAM)


class WNDCLASSW(C.Structure):
    _fields_ = [("style", W.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", C.c_int),
                ("cbWndExtra", C.c_int), ("hInstance", W.HINSTANCE), ("hIcon", W.HICON),
                ("hCursor", W.HANDLE), ("hbrBackground", W.HBRUSH), ("lpszMenuName", W.LPCWSTR),
                ("lpszClassName", W.LPCWSTR)]


class GUID(C.Structure):
    _fields_ = [("Data1", W.DWORD), ("Data2", W.WORD), ("Data3", W.WORD), ("Data4", C.c_ubyte * 8)]
