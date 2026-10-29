"""Asking the settings window that is already open to come forward on a page (v0.6.20, issue #55).

The window has no single-instance rule of its own, so every open from the notification-area icon, its
popup or a notification's button started one more window beside the one already on screen. Before one
is started now, a window of this same program - the process whose image is the very file the open would
start, whatever the spelling of its path - is asked with WM_COPYDATA, under a mark of ours, to come to the
front on that page; one that takes it answers TAKEN (gui/WindowReopen.cs, TakeOpenRequest) and nothing is
started. A window that does not answer TAKEN - one from before v0.6.20, one closing, one that does not
answer in time - leaves the open as it always was: a new window.

Only top-level, visible, unowned Windows Forms windows of that program are asked, so the mark reaches
nothing else on the desktop. The payload is a page from the window's closed list (machine.PAGES), checked by
the caller and again by the window, or nothing - come forward on the page it shows. Nothing here raises: a
question Windows cannot answer is a window not found.
"""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import os

from .dll import library

WM_COPYDATA = 0x004A
# What marks the message as an open request (COPYDATASTRUCT.dwData), and what a window that took one answers.
OPEN_REQUEST_MARK = 0x43415250          # "CARP"
OPEN_REQUEST_TAKEN = 0x4F50454E         # "OPEN"
# The class every Windows Forms window registers under, the settings window's among them.
FORMS_CLASS = "WindowsForms10."
SMTO_ABORTIFHUNG = 0x0002
GW_OWNER = 4
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
# How long a window may take to answer: it answers at once and comes forward afterwards (BeginInvoke).
ANSWER_MILLISECONDS = 3000

_dll = library()
_ENUM = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)


class _CopyData(C.Structure):
    _fields_ = [("dwData", C.c_size_t), ("cbData", W.DWORD), ("lpData", C.c_void_p)]


def _call(dll, name, result, *arguments):
    function = getattr(_dll(dll), name)
    function.restype = result
    function.argtypes = list(arguments)
    return function


def spelled(path) -> str:
    """One spelling of a file's path, whatever it was written as: long names, the real folder, one case."""
    text = os.path.abspath(str(path))
    try:
        text = os.path.realpath(text)
    except (OSError, ValueError):
        pass
    return os.path.normcase(text)


def _image(pid):
    """The full path of the program process `pid` runs, or None."""
    process = _call("kernel32", "OpenProcess", W.HANDLE, W.DWORD, W.BOOL, W.DWORD)(
        PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not process:
        return None
    try:
        buffer, size = C.create_unicode_buffer(32768), W.DWORD(32768)
        query = _call("kernel32", "QueryFullProcessImageNameW", W.BOOL, W.HANDLE, W.DWORD, W.LPWSTR,
                      C.POINTER(W.DWORD))
        return buffer.value if query(process, 0, buffer, C.byref(size)) else None
    finally:
        _call("kernel32", "CloseHandle", W.BOOL, W.HANDLE)(process)


def windows_of(exe):
    """[(window, pid)] for the top-level, visible, unowned Windows Forms windows of processes running `exe`."""
    user32 = _dll("user32")
    target = spelled(exe)
    name = os.path.normcase(os.path.basename(target))
    visible = _call("user32", "IsWindowVisible", W.BOOL, W.HWND)
    owner = _call("user32", "GetWindow", W.HWND, W.HWND, W.UINT)
    process_of = _call("user32", "GetWindowThreadProcessId", W.DWORD, W.HWND, C.POINTER(W.DWORD))
    class_of = _call("user32", "GetClassNameW", C.c_int, W.HWND, W.LPWSTR, C.c_int)
    images, found = {}, []

    def each(window, _):
        try:
            if not visible(window) or owner(window, GW_OWNER):
                return True
            pid = W.DWORD(0)
            process_of(window, C.byref(pid))
            if not pid.value:
                return True
            kind = C.create_unicode_buffer(256)
            if not class_of(window, kind, 256) or not kind.value.startswith(FORMS_CLASS):
                return True
            if pid.value not in images:
                image = _image(pid.value)
                images[pid.value] = (image is not None and os.path.normcase(os.path.basename(image)) == name
                                     and spelled(image) == target)
            if images[pid.value]:
                found.append((window, pid.value))
        except Exception:
            pass
        return True

    enumerate_windows = user32.EnumWindows
    enumerate_windows.argtypes, enumerate_windows.restype = (_ENUM, W.LPARAM), W.BOOL
    enumerate_windows(_ENUM(each), 0)
    return found


def ask(window, pid, page) -> bool:
    """Ask one window to come forward on `page` (None: where it is). True when it answered TAKEN."""
    data = (page or "").encode("utf-16-le")
    buffer = C.create_string_buffer(data, max(len(data), 1))
    copy = _CopyData(OPEN_REQUEST_MARK, len(data), C.cast(buffer, C.c_void_p) if data else None)
    # This process may bring a window forward - a person just chose the item - and lets the window do it itself.
    try:
        _call("user32", "AllowSetForegroundWindow", W.BOOL, W.DWORD)(pid)
    except Exception:
        pass
    answer = C.c_size_t(0)
    send = _call("user32", "SendMessageTimeoutW", C.c_ssize_t, W.HWND, W.UINT, W.WPARAM, C.c_void_p, W.UINT,
                 W.UINT, C.POINTER(C.c_size_t))
    sent = send(window, WM_COPYDATA, 0, C.cast(C.pointer(copy), C.c_void_p), SMTO_ABORTIFHUNG,
                ANSWER_MILLISECONDS, C.byref(answer))
    return bool(sent) and answer.value == OPEN_REQUEST_TAKEN


def hand_over(exe, page=None) -> bool:
    """True when a window of `exe` that is already open took the request to come forward on `page`."""
    if os.name != "nt":
        return False
    try:
        for window, pid in windows_of(exe):
            if ask(window, pid, page):
                return True
    except Exception:
        pass
    return False
