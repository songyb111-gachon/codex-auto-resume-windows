"""What Windows is asked about power, and the one request made of it (v0.6.11; power.py says why).

Each is a documented Win32 call, and each is made only while a setting that needs it is on - at the
defaults, none is:

* QueryUnbiasedInterruptTime - how long this PC has been awake, time asleep or hibernating not
  counted; beside the wall clock it says how long it slept;
* GetSystemPowerStatus - whether it runs on mains power (its ACLineStatus, and nothing else);
* RegisterSuspendResumeNotification, with a callback rather than a window, so it is heard whether
  or not the icon runs - that it has just woken; UnregisterSuspendResumeNotification ends it;
* SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED) - a request, held by the calling
  thread, that the PC not sleep on its own; ES_CONTINUOUS alone takes it back, and it ends with the
  thread or the process in any case. It shows in `powercfg /requests`, and no setting of Windows is
  changed (F1). The watcher makes it and takes it back from the thread that ticks.

Nothing here reads a setting or decides anything, and nothing here raises: an answer that cannot be
had is None, and a request Windows did not take is False.
"""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import os

from .dll import library

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
DEVICE_NOTIFY_CALLBACK = 2
# What a suspend-resume callback is told: the PC is going to sleep, woke with a person present, woke.
PBT_APMSUSPEND, PBT_APMRESUMESUSPEND, PBT_APMRESUMEAUTOMATIC = 0x0004, 0x0007, 0x0012
WOKE = frozenset({PBT_APMRESUMESUSPEND, PBT_APMRESUMEAUTOMATIC})
_AC_OFFLINE, _AC_ONLINE = 0, 1

_dll = library()
# ULONG CALLBACK DeviceNotifyCallbackRoutine(PVOID Context, ULONG Type, PVOID Setting)
CALLBACK = C.WINFUNCTYPE(W.ULONG, C.c_void_p, W.ULONG, C.c_void_p)


class _PowerStatus(C.Structure):
    _fields_ = [("ACLineStatus", C.c_ubyte), ("BatteryFlag", C.c_ubyte),
                ("BatteryLifePercent", C.c_ubyte), ("SystemStatusFlag", C.c_ubyte),
                ("BatteryLifeTime", W.DWORD), ("BatteryFullLifeTime", W.DWORD)]


class _Subscribe(C.Structure):
    """DEVICE_NOTIFY_SUBSCRIBE_PARAMETERS."""
    _fields_ = [("Callback", CALLBACK), ("Context", C.c_void_p)]


def _call(dll, name, result, *arguments):
    function = getattr(_dll(dll), name)
    function.restype = result
    function.argtypes = list(arguments)
    return function


def awake_seconds():
    """Seconds this PC has been awake since it started - sleep and hibernation not counted - or None."""
    if os.name != "nt":
        return None
    try:
        value = C.c_ulonglong(0)
        if not _call("kernel32", "QueryUnbiasedInterruptTime", W.BOOL, C.POINTER(C.c_ulonglong))(C.byref(value)):
            return None
        return value.value / 10_000_000.0          # in units of 100 nanoseconds
    except Exception:
        return None


def on_mains():
    """True on mains power, False on battery, None when Windows cannot say."""
    if os.name != "nt":
        return None
    try:
        status = _PowerStatus()
        if not _call("kernel32", "GetSystemPowerStatus", W.BOOL, C.POINTER(_PowerStatus))(C.byref(status)):
            return None
        return {_AC_ONLINE: True, _AC_OFFLINE: False}.get(status.ACLineStatus)
    except Exception:
        return None


def keep_awake(on: bool) -> bool:
    """Ask that this PC not sleep on its own (`on`), or take that back. Held by the calling thread:
    made and taken back on the thread that ticks. Whether Windows took it."""
    if os.name != "nt":
        return False
    try:
        flags = ES_CONTINUOUS | ES_SYSTEM_REQUIRED if on is True else ES_CONTINUOUS
        return _call("kernel32", "SetThreadExecutionState", W.DWORD, W.DWORD)(flags) != 0
    except Exception:
        return False


class WakeListener:
    """Told that this PC has woken, while it is open.

    `on_wake()` is called on a thread of Windows' own, so it must do no more than set a flag and
    signal an event - the watcher's tick does the rest on its own thread. The callback and its
    parameters are kept here for as long as Windows may call them.
    """

    def __init__(self, on_wake):
        self._on_wake = on_wake
        self._handle = None
        self._callback = CALLBACK(self._told)
        self._parameters = _Subscribe(self._callback, None)

    def _told(self, _context, kind, _setting):
        if kind in WOKE:
            try:
                self._on_wake()
            except Exception:
                pass                    # a thread of Windows' own: nothing may escape to it
        return 0

    @property
    def open(self) -> bool:
        return self._handle is not None

    def start(self) -> bool:
        """Listen. Whether Windows took it."""
        if self._handle is not None:
            return True
        if os.name != "nt":
            return False
        try:
            register = _call("user32", "RegisterSuspendResumeNotification", C.c_void_p,
                             C.POINTER(_Subscribe), W.DWORD)
            handle = register(C.byref(self._parameters), DEVICE_NOTIFY_CALLBACK)
        except Exception:
            return False
        self._handle = handle or None
        return self._handle is not None

    def stop(self) -> None:
        """Stop listening; nothing is called after this returns."""
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            _call("user32", "UnregisterSuspendResumeNotification", W.BOOL, C.c_void_p)(handle)
        except Exception:
            pass
