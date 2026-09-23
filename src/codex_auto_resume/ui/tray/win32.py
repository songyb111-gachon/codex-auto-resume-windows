"""The Win32 this icon calls: the numbers, the two structures, and a handle cache of its own.

`_dll` is `win.library()`, so the argument types declared on a function here reach no other
module - the popup's `win32.py` holds its own for the same reason.
"""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W

from ... import win
from ...win.dll import GUID
from .words import TIP_CHARS



WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_COMMAND = 0x0111
WM_TIMER = 0x0113
WM_NULL = 0x0000
WM_WTSSESSION_CHANGE = 0x02B1
WTS_CONSOLE_CONNECT, WTS_CONSOLE_DISCONNECT, WTS_REMOTE_CONNECT, WTS_REMOTE_DISCONNECT = 1, 2, 3, 4
WTS_SESSION_LOCK, WTS_SESSION_UNLOCK = 7, 8
NOTIFY_FOR_THIS_SESSION = 0
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_CONTEXTMENU = 0x007B
WM_USER = 0x0400
WM_APP = 0x8000
CALLBACK = WM_APP + 1
WM_TRAY_FRAMES = WM_APP + 2         # the frame table's building thread has finished
# The icon window's timers: the one-second tick (tooltip, state, what may move) and, only while
# the icon moves, the frame timer.
TIMER_TICK, TIMER_FRAME = 1, 2
# With NOTIFYICON_VERSION_4 the shell reports a click or Enter on the icon as a select,
# and a right click or the menu key as WM_CONTEXTMENU, instead of raw mouse messages.
NIN_SELECT = WM_USER + 0
NIN_KEYSELECT = WM_USER + 1
NIM_ADD, NIM_MODIFY, NIM_DELETE, NIM_SETVERSION = 0, 1, 2, 4
NOTIFYICON_VERSION_4 = 4
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_SHOWTIP = 0x1, 0x2, 0x4, 0x80
MF_STRING, MF_GRAYED, MF_SEPARATOR = 0x0, 0x1, 0x800
TPM_RIGHTBUTTON, TPM_RETURNCMD, TPM_NONOTIFY = 0x2, 0x100, 0x80
IMAGE_ICON, LR_LOADFROMFILE = 1, 0x10
SM_CXSMICON, SM_CYSMICON = 49, 50
IDI_APPLICATION = 32512


_dll = win.library()      # handles of this module's own
class NOTIFYICONDATAW(C.Structure):
    _fields_ = [("cbSize", W.DWORD), ("hWnd", W.HWND), ("uID", W.UINT), ("uFlags", W.UINT),
                ("uCallbackMessage", W.UINT), ("hIcon", W.HICON), ("szTip", W.WCHAR * TIP_CHARS),
                ("dwState", W.DWORD), ("dwStateMask", W.DWORD), ("szInfo", W.WCHAR * 256),
                ("uVersion", W.UINT), ("szInfoTitle", W.WCHAR * 64), ("dwInfoFlags", W.DWORD),
                ("guidItem", GUID), ("hBalloonIcon", W.HICON)]


class MSG(C.Structure):
    _fields_ = [("hwnd", W.HWND), ("message", W.UINT), ("wParam", W.WPARAM), ("lParam", W.LPARAM),
                ("time", W.DWORD), ("pt", W.POINT)]
