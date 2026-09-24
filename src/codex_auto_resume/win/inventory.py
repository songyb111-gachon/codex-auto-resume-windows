"""The Restart Manager, read and never used to restart anything.

It answers one question - which processes hold a file open - and this product only ever asks
it. Nothing here shuts down, restarts or registers a restart.
"""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import os

from ..domain.errors import AdapterError


class _UniqueProcess(C.Structure):
    _fields_ = [("pid", W.DWORD), ("created", W.FILETIME)]


class _ProcessInfo(C.Structure):
    _fields_ = [("process", _UniqueProcess), ("name", W.WCHAR * 256),
                ("service", W.WCHAR * 64), ("type", C.c_int),
                ("status", W.ULONG), ("session", W.DWORD), ("restartable", W.BOOL)]


def resource_users(path):
    """Documented Restart Manager inventory ONLY. Never shutdown/restart APIs.

    Windows creates temporary session metadata; EndSession always releases it.
    Return PID + creation time only. Resource names/content are not logged.
    """
    if os.name != "nt":
        raise AdapterError("windows_required")
    rm = C.WinDLL("rstrtmgr", use_last_error=True)
    rm.RmStartSession.argtypes = [C.POINTER(W.DWORD), W.DWORD, W.LPWSTR]
    rm.RmStartSession.restype = W.DWORD
    rm.RmRegisterResources.argtypes = [W.DWORD, W.UINT, C.POINTER(W.LPCWSTR), W.UINT,
                                      C.POINTER(_UniqueProcess), W.UINT, C.POINTER(W.LPCWSTR)]
    rm.RmRegisterResources.restype = W.DWORD
    rm.RmGetList.argtypes = [W.DWORD, C.POINTER(W.UINT), C.POINTER(W.UINT),
                           C.POINTER(_ProcessInfo), C.POINTER(W.DWORD)]
    rm.RmGetList.restype = W.DWORD
    rm.RmEndSession.argtypes = [W.DWORD]
    rm.RmEndSession.restype = W.DWORD
    session, key = W.DWORD(), C.create_unicode_buffer(33)
    if rm.RmStartSession(C.byref(session), 0, key):
        raise AdapterError("resource_session_failed")
    try:
        files = (W.LPCWSTR * 1)(str(path))
        if rm.RmRegisterResources(session, 1, files, 0, None, 0, None):
            raise AdapterError("resource_registration_failed")
        needed, count, reason = W.UINT(), W.UINT(), W.DWORD()
        result = rm.RmGetList(session, C.byref(needed), C.byref(count), None, C.byref(reason))
        if result == 0:
            return []
        for _ in range(3):
            if result != 234 or needed.value > 1024:
                raise AdapterError("resource_inventory_failed")
            array = (_ProcessInfo * needed.value)()
            count.value = needed.value
            result = rm.RmGetList(session, C.byref(needed), C.byref(count), array, C.byref(reason))
            if result == 0:
                return [{"pid": p.process.pid,
                         "created": (p.process.created.dwHighDateTime << 32) | p.process.created.dwLowDateTime}
                        for p in array[:count.value]]
        raise AdapterError("resource_inventory_unstable")
    finally:
        rm.RmEndSession(session)


def restart_manager_available() -> bool:
    """Whether the Restart Manager functions `resource_users` calls can be resolved.

    A structural check for the Compatibility Registry: it loads the library and looks the
    four functions up, and starts no session and registers no resource.
    """
    if os.name != "nt":
        return False
    try:
        rm = C.WinDLL("rstrtmgr", use_last_error=True)
        return all(hasattr(rm, name) for name in
                   ("RmStartSession", "RmRegisterResources", "RmGetList", "RmEndSession"))
    except OSError:
        return False
