"""What Windows is asked about the watcher's own process, and about this sign-in (v0.6.11).

Three documented Win32 questions, each about this process or this PC and none about anything a
person has written, read or opened:

* K32GetProcessMemoryInfo, of this process only (GetCurrentProcess) - how much private memory it has
  committed now, and the most it has (PrivateUsage, PeakPagefileUsage). The watcher asks every tick:
  the peak is shown in Diagnostics, and the memory guard compares the first with its limit
  (memguard.py).
* GetTokenInformation(TokenStatistics), of this process's own token (GetCurrentProcessToken) - the
  number Windows gives this sign-in (its AuthenticationId), and nothing else of the answer is kept.
  It names no one: it is a counter, new for every sign-in and started again at every start of
  Windows. A watcher writes it once, and a reader compares it with its own, to tell a watcher that
  stopped unexpectedly in this sign-in from one that ended with an earlier one.
* GetTickCount64 - how long ago Windows started, so the same comparison can tell two starts apart.

Nothing here reads a setting or decides anything, and nothing here raises: an answer that cannot be
had is None.
"""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import os
import time

from .dll import library

TOKEN_STATISTICS = 10
# GetCurrentProcessToken(), which the headers define inline as this pseudo-handle: it needs no
# opening and no closing, and it can only be asked (TOKEN_QUERY).
_CURRENT_PROCESS_TOKEN = -4

_dll = library()


class _MemoryCounters(C.Structure):
    """PROCESS_MEMORY_COUNTERS_EX."""
    _fields_ = [("cb", W.DWORD), ("PageFaultCount", W.DWORD)] + [
        (name, C.c_size_t) for name in (
            "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
            "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage",
            "PeakPagefileUsage", "PrivateUsage")]


class _Luid(C.Structure):
    _fields_ = [("LowPart", W.DWORD), ("HighPart", W.LONG)]


class _TokenStatistics(C.Structure):
    _fields_ = [("TokenId", _Luid), ("AuthenticationId", _Luid), ("ExpirationTime", C.c_longlong),
                ("TokenType", C.c_int), ("ImpersonationLevel", C.c_int), ("DynamicCharged", W.DWORD),
                ("DynamicAvailable", W.DWORD), ("GroupCount", W.DWORD), ("PrivilegeCount", W.DWORD),
                ("ModifiedId", _Luid)]


def _call(dll, name, result, *arguments):
    function = getattr(_dll(dll), name)
    function.restype = result
    function.argtypes = list(arguments)
    return function


def memory():
    """(private bytes now, the most private bytes so far) of this process, or None."""
    if os.name != "nt":
        return None
    try:
        counters = _MemoryCounters()
        counters.cb = C.sizeof(_MemoryCounters)
        process = _call("kernel32", "GetCurrentProcess", W.HANDLE)()
        asked = _call("kernel32", "K32GetProcessMemoryInfo", W.BOOL, W.HANDLE, C.POINTER(_MemoryCounters), W.DWORD)
        if not asked(process, C.byref(counters), counters.cb):
            return None
        private = int(counters.PrivateUsage)
        return private, max(private, int(counters.PeakPagefileUsage))
    except Exception:
        return None


def sign_in():
    """The number Windows gives this sign-in, as 16 hex digits, or None."""
    if os.name != "nt":
        return None
    try:
        statistics, needed = _TokenStatistics(), W.DWORD(0)
        asked = _call("advapi32", "GetTokenInformation", W.BOOL, W.HANDLE, C.c_int, C.c_void_p, W.DWORD,
                      C.POINTER(W.DWORD))
        if not asked(W.HANDLE(_CURRENT_PROCESS_TOKEN), TOKEN_STATISTICS, C.byref(statistics),
                     C.sizeof(statistics), C.byref(needed)):
            return None
        luid = statistics.AuthenticationId
        return "%08x%08x" % (luid.HighPart & 0xFFFFFFFF, luid.LowPart)
    except Exception:
        return None


def booted_at():
    """When Windows started, by the wall clock, in seconds - or None."""
    if os.name != "nt":
        return None
    try:
        since = _call("kernel32", "GetTickCount64", C.c_ulonglong)()
        return time.time() - since / 1000.0
    except Exception:
        return None
