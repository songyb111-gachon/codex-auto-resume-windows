# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Ending the Codex app's main process, for the restart a person agreed to (account_switch, v0.6.20 final).

Two ways, the gentler first (codex/restart.py decides when):

* `ask_close`: Windows' own request to close an application - the Restart Manager's RmShutdown, with no force flag, for
  that one process (registered by its id and creation time, so a reused id is never asked). It is what an installer or
  Windows Update asks a running program with, and it sends the program the messages Windows sends when a person signs
  out: a program that handles them ends as it would then, saving what it saves then. A program that refuses is not
  ended (RmShutdown answers so), and nothing is forced. The Codex app offers no quit of its own to another program -
  no command, and closing its window leaves it running in the background (measured 2026-11-01) - so this is the
  gentlest request that can end it.
* `end_process`: TerminateProcess of that same process, only where its creation time is still the one asked about -
  what the measurement session did on 2026-11-01 (the app's engine went with it, and a fresh start came up signed in
  as the new account). Used only when the request did not end the app.

Nothing else is ended, asked or read: no window is looked at, no message is posted to one, no other process is named.
Every function answers False rather than raise where Windows says no.
"""
from __future__ import annotations

ERROR_SUCCESS = 0
PROCESS_TERMINATE = 0x0001
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SYNCHRONIZE = 0x00100000
WAIT_TIMEOUT = 258


def _structures():
    import ctypes as C
    from ctypes import wintypes as W

    class UniqueProcess(C.Structure):
        _fields_ = [("pid", W.DWORD), ("created", W.FILETIME)]
    return UniqueProcess


def ask_close(pid, created) -> bool:
    """Windows' request to close the process `pid` made at `created` (FILETIME as one integer): whether Windows says
    it was closed. Not forced; a program that will not close stays open and this answers False."""
    import ctypes as C
    from ctypes import wintypes as W
    if type(pid) is not int or pid <= 0 or type(created) is not int or created <= 0:
        return False
    try:
        rm = C.WinDLL("rstrtmgr", use_last_error=True)
    except OSError:
        return False
    unique = _structures()
    rm.RmStartSession.argtypes = [C.POINTER(W.DWORD), W.DWORD, W.LPWSTR]
    rm.RmStartSession.restype = W.DWORD
    rm.RmRegisterResources.argtypes = [W.DWORD, W.UINT, C.c_void_p, W.UINT, C.POINTER(unique), W.UINT, C.c_void_p]
    rm.RmRegisterResources.restype = W.DWORD
    rm.RmShutdown.argtypes = [W.DWORD, W.ULONG, C.c_void_p]
    rm.RmShutdown.restype = W.DWORD
    rm.RmEndSession.argtypes = [W.DWORD]
    rm.RmEndSession.restype = W.DWORD
    session, key = W.DWORD(), C.create_unicode_buffer(33)
    if rm.RmStartSession(C.byref(session), 0, key) != ERROR_SUCCESS:
        return False
    try:
        process = unique()
        process.pid = pid
        process.created.dwLowDateTime = created & 0xFFFFFFFF
        process.created.dwHighDateTime = (created >> 32) & 0xFFFFFFFF
        if rm.RmRegisterResources(session, 0, None, 1, C.byref(process), 0, None) != ERROR_SUCCESS:
            return False
        return rm.RmShutdown(session, 0, None) == ERROR_SUCCESS          # 0: no RmForceShutdown
    finally:
        rm.RmEndSession(session)


def end_process(pid, created) -> bool:
    """TerminateProcess of `pid`, only while it is still the process made at `created`: whether Windows ended it."""
    import ctypes as C
    from ctypes import wintypes as W
    if type(pid) is not int or pid <= 0 or type(created) is not int or created <= 0:
        return False
    kernel = C.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    kernel.OpenProcess.restype = W.HANDLE
    kernel.GetProcessTimes.argtypes = [W.HANDLE] + [C.POINTER(W.FILETIME)] * 4
    kernel.GetProcessTimes.restype = W.BOOL
    kernel.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
    kernel.WaitForSingleObject.restype = W.DWORD
    kernel.TerminateProcess.argtypes = [W.HANDLE, W.UINT]
    kernel.TerminateProcess.restype = W.BOOL
    kernel.CloseHandle.argtypes = [W.HANDLE]
    kernel.CloseHandle.restype = W.BOOL
    handle = kernel.OpenProcess(PROCESS_TERMINATE | PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, pid)
    if not handle:
        return False
    try:
        if kernel.WaitForSingleObject(handle, 0) != WAIT_TIMEOUT:
            return False                                                    # already ended
        times = [W.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle, *(C.byref(time) for time in times)):
            return False
        if ((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime) != created:
            return False                                                    # another process under a reused id
        return bool(kernel.TerminateProcess(handle, 1))
    finally:
        kernel.CloseHandle(handle)
