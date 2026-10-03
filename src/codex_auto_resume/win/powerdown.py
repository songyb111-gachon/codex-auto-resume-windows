"""The power action's Windows calls: may this account do it, is anyone here, and doing it (v0.6.12).

poweraction.py says when; this is only how, and every call is a documented Win32 function, made from
the watcher's own process - no program is started, no task or service is made, and nothing needs an
administrator (F15):

* the current process's token, read (OpenProcessToken, GetTokenInformation(TokenPrivileges)): does
  this account hold SeShutdownPrivilege at all? Sleep and hibernate need it as shutting down does
  (SetSuspendState, Remarks), so without it nothing is offered;
* GetPwrCapabilities: does Windows report a sleep state (S1, S2 or S3 - a PC that only has Modern
  Standby is offered no Sleep until it is measured, Q2), and hibernation with its file there? It is
  never turned on here, and no setting of Windows is changed;
* GetLastInputInfo and GetTickCount: how long since anybody used this PC - a time, with no hook and
  nothing of what was typed (B13);
* WTSEnumerateSessionsW: how many other sessions are signed in, active or disconnected - a count,
  and no user name is read;
* and, to act: SeShutdownPrivilege enabled on the process's own token (AdjustTokenPrivileges), then
  SetSuspendState(hibernate, FALSE, FALSE) or ExitWindowsEx(EWX_POWEROFF) with a planned
  application's reason. Never a force flag (E8): any program may refuse a shut down, and Windows then
  does not shut down. The privilege is disabled again and the token closed whatever happened.

powrprof and wtsapi32 are not KnownDLLs, so every library here is loaded from System32 alone
(LOAD_LIBRARY_SEARCH_SYSTEM32), never found on a search path a stranger could write to.

Nothing here raises: an answer that cannot be had is None, and an action not done is False. And
nothing here acts while a test runs: `act` refuses whenever unittest is loaded, which no product
module imports (tests/test_power_action_windows.py holds both).
"""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import os
import sys

LOAD_LIBRARY_SEARCH_SYSTEM32 = 0x00000800
EWX_POWEROFF = 0x00000008
SHTDN_REASON_MAJOR_APPLICATION = 0x00040000
SHTDN_REASON_FLAG_PLANNED = 0x80000000
TOKEN_QUERY, TOKEN_ADJUST_PRIVILEGES = 0x0008, 0x0020
SE_PRIVILEGE_ENABLED = 0x00000002
TOKEN_PRIVILEGES_CLASS = 3                       # TOKEN_INFORMATION_CLASS.TokenPrivileges
ERROR_NOT_ALL_ASSIGNED = 1300
SHUTDOWN_PRIVILEGE = "SeShutdownPrivilege"
WTS_ACTIVE, WTS_DISCONNECTED = 0, 4              # WTS_CONNECTSTATE_CLASS
# The actions, and why one is not offered, as poweraction.ACTIONS and .UNAVAILABLE spell them.
SLEEP, HIBERNATE, SHUT_DOWN = "sleep", "hibernate", "shut_down"
NO_PRIVILEGE, NO_SLEEP_STATE, HIBERNATE_OFF = "no_privilege", "no_sleep_state", "hibernate_off"

_LIBRARIES = {}
_last_error = None


class _Luid(C.Structure):
    _fields_ = [("LowPart", W.DWORD), ("HighPart", W.LONG)]


class _TokenPrivilege(C.Structure):
    """TOKEN_PRIVILEGES holding one LUID_AND_ATTRIBUTES, which is all AdjustTokenPrivileges is given."""
    _fields_ = [("PrivilegeCount", W.DWORD), ("Luid", _Luid), ("Attributes", W.DWORD)]


class _BatteryScale(C.Structure):
    _fields_ = [("Granularity", W.DWORD), ("Capacity", W.DWORD)]


class _PowerCapabilities(C.Structure):
    """SYSTEM_POWER_CAPABILITIES, of which only the sleep states and the hibernation file are read."""
    _fields_ = [(name, C.c_ubyte) for name in (
        "PowerButtonPresent", "SleepButtonPresent", "LidPresent", "SystemS1", "SystemS2", "SystemS3",
        "SystemS4", "SystemS5", "HiberFilePresent", "FullWake", "VideoDimPresent", "ApmPresent",
        "UpsPresent", "ThermalControl", "ProcessorThrottle", "ProcessorMinThrottle",
        "ProcessorMaxThrottle", "FastSystemS4", "Hiberboot", "WakeAlarmPresent", "AoAc", "DiskSpinDown",
        "HiberFileType", "AoAcConnectivitySupported")] + [
        ("spare3", C.c_ubyte * 6), ("SystemBatteriesPresent", C.c_ubyte), ("BatteriesAreShortTerm", C.c_ubyte),
        ("BatteryScale", _BatteryScale * 3), ("AcOnLineWake", C.c_int), ("SoftLidWake", C.c_int),
        ("RtcWake", C.c_int), ("MinDeviceWakeState", C.c_int), ("DefaultLowLatencyWake", C.c_int)]


class _LastInput(C.Structure):
    _fields_ = [("cbSize", W.UINT), ("dwTime", W.DWORD)]


class _Session(C.Structure):
    """WTS_SESSION_INFOW. The station's name is in it, and never read."""
    _fields_ = [("SessionId", W.DWORD), ("pWinStationName", W.LPWSTR), ("State", C.c_int)]


def _load(name):
    """A system DLL of this module's own (win/dll.py says why), from System32 and nowhere else."""
    if name not in _LIBRARIES:
        _LIBRARIES[name] = C.WinDLL(name, use_last_error=True, winmode=LOAD_LIBRARY_SEARCH_SYSTEM32)
    return _LIBRARIES[name]


def _call(dll, name, result, *arguments):
    function = getattr(_load(dll), name)
    function.restype = result
    function.argtypes = list(arguments)
    return function


def _token(access):
    """The current process's own token, opened for `access`, or None."""
    handle = W.HANDLE()
    process = _call("kernel32", "GetCurrentProcess", W.HANDLE)()
    if not _call("advapi32", "OpenProcessToken", W.BOOL, W.HANDLE, W.DWORD, C.POINTER(W.HANDLE))(
            process, access, C.byref(handle)) or not handle.value:
        return None
    return handle


def _close(handle):
    try:
        _call("kernel32", "CloseHandle", W.BOOL, W.HANDLE)(handle)
    except Exception:
        pass


def _shutdown_luid():
    luid = _Luid()
    if not _call("advapi32", "LookupPrivilegeValueW", W.BOOL, W.LPCWSTR, W.LPCWSTR, C.POINTER(_Luid))(
            None, SHUTDOWN_PRIVILEGE, C.byref(luid)):
        return None
    return luid


def holds_shutdown_privilege():
    """Whether this process's token holds SeShutdownPrivilege, enabled or not: True, False, or None."""
    if os.name != "nt":
        return None
    try:
        luid = _shutdown_luid()
        if luid is None:
            return None
        token = _token(TOKEN_QUERY)
        if token is None:
            return None
        try:
            needed = W.DWORD(0)
            information = _call("advapi32", "GetTokenInformation", W.BOOL, W.HANDLE, C.c_int, C.c_void_p,
                                W.DWORD, C.POINTER(W.DWORD))
            information(token, TOKEN_PRIVILEGES_CLASS, None, 0, C.byref(needed))
            if not 4 <= needed.value <= 1 << 20:
                return None
            buffer = C.create_string_buffer(needed.value)
            if not information(token, TOKEN_PRIVILEGES_CLASS, buffer, needed.value, C.byref(needed)):
                return None
        finally:
            _close(token)
        count = W.DWORD.from_buffer_copy(buffer.raw[:4]).value
        entry = C.sizeof(_Luid) + C.sizeof(W.DWORD)
        if 4 + count * entry > len(buffer.raw):
            return None
        for index in range(count):
            found = _Luid.from_buffer_copy(buffer.raw[4 + index * entry:4 + index * entry + C.sizeof(_Luid)])
            if (found.LowPart, found.HighPart) == (luid.LowPart, luid.HighPart):
                return True
        return False
    except Exception:
        return None


def _capabilities():
    try:
        found = _PowerCapabilities()
        if not _call("powrprof", "GetPwrCapabilities", C.c_ubyte, C.POINTER(_PowerCapabilities))(C.byref(found)):
            return None
        return found
    except Exception:
        return None


def available(action):
    """(True, None) when Windows lets this account do `action` on this PC now, else (False, why): no
    SeShutdownPrivilege - for all three, before anything else is asked - no sleep state reported, or
    hibernation off (or its file missing). An answer that cannot be had is not an offer."""
    if action not in (SLEEP, HIBERNATE, SHUT_DOWN):
        return False, None
    if holds_shutdown_privilege() is not True:
        return False, NO_PRIVILEGE
    if action == SHUT_DOWN:
        return True, None
    found = _capabilities()
    if action == SLEEP:
        ok = found is not None and bool(found.SystemS1 or found.SystemS2 or found.SystemS3)
        return (True, None) if ok else (False, NO_SLEEP_STATE)
    ok = found is not None and bool(found.SystemS4 and found.HiberFilePresent)
    return (True, None) if ok else (False, HIBERNATE_OFF)


def idle_seconds():
    """Seconds since anybody last used this PC's keyboard or mouse, or None."""
    if os.name != "nt":
        return None
    try:
        last = _LastInput(C.sizeof(_LastInput), 0)
        if not _call("user32", "GetLastInputInfo", W.BOOL, C.POINTER(_LastInput))(C.byref(last)):
            return None
        now = _call("kernel32", "GetTickCount", W.DWORD)()
        return ((int(now) - int(last.dwTime)) % (1 << 32)) / 1000.0     # both wrap after 49.7 days
    except Exception:
        return None


def other_sessions():
    """How many sessions other than this one, and other than the services' session 0, are signed in -
    active or disconnected - or None."""
    if os.name != "nt":
        return None
    try:
        own = W.DWORD(0)
        process = _call("kernel32", "GetCurrentProcessId", W.DWORD)()
        if not _call("kernel32", "ProcessIdToSessionId", W.BOOL, W.DWORD, C.POINTER(W.DWORD))(
                process, C.byref(own)):
            return None
        listing, count = C.POINTER(_Session)(), W.DWORD(0)
        if not _call("wtsapi32", "WTSEnumerateSessionsW", W.BOOL, W.HANDLE, W.DWORD, W.DWORD,
                     C.POINTER(C.POINTER(_Session)), C.POINTER(W.DWORD))(
                None, 0, 1, C.byref(listing), C.byref(count)):
            return None
        try:
            return sum(1 for index in range(count.value)
                       if listing[index].SessionId not in (0, own.value)
                       and listing[index].State in (WTS_ACTIVE, WTS_DISCONNECTED))
        finally:
            _call("wtsapi32", "WTSFreeMemory", None, C.c_void_p)(listing)
    except Exception:
        return None


def _privilege(token, luid, enabled) -> bool:
    change = _TokenPrivilege(1, luid, SE_PRIVILEGE_ENABLED if enabled else 0)
    C.set_last_error(0)
    done = _call("advapi32", "AdjustTokenPrivileges", W.BOOL, W.HANDLE, W.BOOL, C.POINTER(_TokenPrivilege),
                 W.DWORD, C.c_void_p, C.c_void_p)(token, False, C.byref(change), 0, None, None)
    return bool(done) and C.get_last_error() != ERROR_NOT_ALL_ASSIGNED


def last_error():
    """The Windows error number the last `act` that was refused ended with, or None."""
    return _last_error


def act(action) -> bool:
    """Do `action` now: True when Windows took it. Sleep and hibernate return once this PC wakes;
    a shut down returns at once, before any program has answered - so a refused one looks taken."""
    global _last_error
    if "unittest" in sys.modules:
        return False                                  # a test never puts its machine to sleep
    if os.name != "nt" or action not in (SLEEP, HIBERNATE, SHUT_DOWN):
        return False
    _last_error = None
    try:
        luid = _shutdown_luid()
        token = None if luid is None else _token(TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY)
        if token is None:
            _last_error = C.get_last_error()
            return False
    except Exception:
        return False
    enabled = False
    try:
        enabled = _privilege(token, luid, True)
        if not enabled:
            _last_error = C.get_last_error()
            return False
        if action == SHUT_DOWN:
            done = _call("user32", "ExitWindowsEx", W.BOOL, W.UINT, W.DWORD)(
                EWX_POWEROFF, SHTDN_REASON_MAJOR_APPLICATION | SHTDN_REASON_FLAG_PLANNED)
        else:
            done = _call("powrprof", "SetSuspendState", C.c_ubyte, C.c_ubyte, C.c_ubyte, C.c_ubyte)(
                action == HIBERNATE, False, False)
        if not done:
            _last_error = C.get_last_error()
        return bool(done)
    except Exception:
        return False
    finally:
        try:
            if enabled:
                _privilege(token, luid, False)
        except Exception:
            pass
        _close(token)
