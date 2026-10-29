# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""A waitable timer that wakes this PC, and whether Windows allows one to (wake_for_reset, v0.6.19).

`WakeTimer.set` makes one unnamed waitable timer of this process's own (CreateWaitableTimerExW) and sets it for an
absolute time with fResume (SetWaitableTimer): where Windows allows wake timers, a PC asleep then wakes. `cancel`
takes it back (CancelWaitableTimer); `close` closes its handle, and with it the timer - as Windows does when this
process ends, so a timer never outlives the watcher that set it.

`allowed` asks Windows the active power scheme's *Allow wake timers* value for the power source in use now
(GetSystemPowerStatus's ACLineStatus; PowerGetActiveScheme, then PowerReadACValueIndex or PowerReadDCValueIndex for
GUID_SLEEP_SUBGROUP / GUID_ALLOW_RTC_WAKE; the scheme's GUID freed with LocalFree). Only 1, Enable, allows this timer:
0 is Disable and 2 is "Important wake timers only", which a timer of an application's own is not. Read, never written:
the product changes no setting of the machine (F1).

`kernel` and `power` are the seams a test fills with fakes that record their calls: no real timer is ever set, and no
power setting read, in a test.
"""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import uuid

TIMER_ALL_ACCESS = 0x1F0003
# 100-nanosecond intervals from 1601-01-01 to the Unix epoch.
EPOCH_AS_FILETIME = 116444736000000000
GUID_SLEEP_SUBGROUP = uuid.UUID("238c9fa8-0aad-41ed-83f4-97be242c8f20")
GUID_ALLOW_RTC_WAKE = uuid.UUID("bd3b718a-0680-4d9d-8ab2-e1d2b4ac806d")
ENABLE = 1
# ACLineStatus: 0 on battery, 1 on mains, 255 not known (read as mains, the source a desktop has).
ON_BATTERY = 0


class GUID(C.Structure):
    _fields_ = [("Data1", W.DWORD), ("Data2", W.WORD), ("Data3", W.WORD), ("Data4", C.c_ubyte * 8)]

    @classmethod
    def of(cls, value):
        return cls.from_buffer_copy(value.bytes_le)


class SYSTEM_POWER_STATUS(C.Structure):
    _fields_ = [("ACLineStatus", C.c_ubyte), ("BatteryFlag", C.c_ubyte), ("BatteryLifePercent", C.c_ubyte),
                ("SystemStatusFlag", C.c_ubyte), ("BatteryLifeTime", W.DWORD), ("BatteryFullLifeTime", W.DWORD)]


def filetime(epoch_seconds) -> int:
    """An absolute due time as SetWaitableTimer takes one: positive, in 100-nanosecond intervals since 1601, UTC."""
    return EPOCH_AS_FILETIME + int(round(float(epoch_seconds) * 10_000_000))


def _kernel():
    kernel = C.WinDLL("kernel32", use_last_error=True)
    kernel.CreateWaitableTimerExW.argtypes = [C.c_void_p, W.LPCWSTR, W.DWORD, W.DWORD]
    kernel.CreateWaitableTimerExW.restype = W.HANDLE
    kernel.SetWaitableTimer.argtypes = [W.HANDLE, C.POINTER(C.c_longlong), W.LONG, C.c_void_p, C.c_void_p, W.BOOL]
    kernel.SetWaitableTimer.restype = W.BOOL
    kernel.CancelWaitableTimer.argtypes = [W.HANDLE]
    kernel.CancelWaitableTimer.restype = W.BOOL
    kernel.CloseHandle.argtypes = [W.HANDLE]
    kernel.CloseHandle.restype = W.BOOL
    kernel.GetSystemPowerStatus.argtypes = [C.POINTER(SYSTEM_POWER_STATUS)]
    kernel.GetSystemPowerStatus.restype = W.BOOL
    kernel.LocalFree.argtypes = [C.c_void_p]
    kernel.LocalFree.restype = C.c_void_p
    return kernel


def _power():
    power = C.WinDLL("powrprof", use_last_error=True)
    power.PowerGetActiveScheme.argtypes = [C.c_void_p, C.POINTER(C.POINTER(GUID))]
    power.PowerGetActiveScheme.restype = W.DWORD
    for name in ("PowerReadACValueIndex", "PowerReadDCValueIndex"):
        function = getattr(power, name)
        function.argtypes = [C.c_void_p, C.POINTER(GUID), C.POINTER(GUID), C.POINTER(GUID), C.POINTER(W.DWORD)]
        function.restype = W.DWORD
    return power


class WakeTimer:
    """One waitable timer of this process's own, set to wake the PC, and the question whether Windows allows it."""
    __slots__ = ("_kernel", "_power", "_handle", "due")

    def __init__(self, *, kernel=None, power=None):
        self._kernel, self._power = kernel, power
        self._handle = None
        self.due = None                     # the time it is set for, in Unix seconds, or None

    def _k(self):
        if self._kernel is None:
            self._kernel = _kernel()
        return self._kernel

    def _p(self):
        if self._power is None:
            self._power = _power()
        return self._power

    def on_battery(self) -> bool:
        status = SYSTEM_POWER_STATUS()
        if not self._k().GetSystemPowerStatus(C.byref(status)):
            return False
        return status.ACLineStatus == ON_BATTERY

    def allowed(self) -> bool:
        """Whether Windows' Allow wake timers is Enable for the power source in use now. Anything that cannot be read
        is not allowed: nothing is set on a guess."""
        try:
            battery = self.on_battery()
            power = self._p()
            scheme = C.POINTER(GUID)()
            if power.PowerGetActiveScheme(None, C.byref(scheme)) != 0 or not scheme:
                return False
            try:
                value = W.DWORD(0)
                read = power.PowerReadDCValueIndex if battery else power.PowerReadACValueIndex
                found = read(None, scheme, C.byref(GUID.of(GUID_SLEEP_SUBGROUP)), C.byref(GUID.of(GUID_ALLOW_RTC_WAKE)),
                             C.byref(value))
            finally:
                self._k().LocalFree(scheme)
            return found == 0 and value.value == ENABLE
        except Exception:                              # noqa: BLE001 - not known is not allowed
            return False

    def set(self, epoch_seconds) -> bool:
        """The timer set, or moved, to wake the PC at `epoch_seconds`. Whether Windows took it."""
        try:
            kernel = self._k()
            if not self._handle:
                self._handle = kernel.CreateWaitableTimerExW(None, None, 0, TIMER_ALL_ACCESS) or None
                if self._handle is None:
                    return False
            due = C.c_longlong(filetime(epoch_seconds))
            if not kernel.SetWaitableTimer(self._handle, C.byref(due), 0, None, None, True):
                return False
        except Exception:                              # noqa: BLE001
            return False
        self.due = float(epoch_seconds)
        return True

    def cancel(self) -> bool:
        """The timer taken back, where one is set. Whether one was."""
        if self.due is None:
            return False
        try:
            if self._handle:
                self._k().CancelWaitableTimer(self._handle)
        except Exception:                              # noqa: BLE001
            pass
        self.due = None
        return True

    def close(self) -> None:
        """Its handle closed, and with it the timer, as when this process ends."""
        try:
            if self._handle:
                self._k().CloseHandle(self._handle)
        except Exception:                              # noqa: BLE001
            pass
        self._handle, self.due = None, None
