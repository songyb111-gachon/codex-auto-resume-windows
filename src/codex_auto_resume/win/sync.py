"""The named objects the watcher is one of, and the two it is woken by.

One mutex says a watcher is running; a manual-reset event asks it to stop and an auto-reset
event asks it to look now. Each is created at this process's own integrity level and refused
if something lower got there first (`_refuse_if_squatted`), because a named object is a name
anyone in the session can take.
"""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import hashlib
import os
from pathlib import Path
import time

from ..domain.errors import AdapterError
from .kernel import ERROR_ALREADY_EXISTS, NO_WINDOW, _kernel, _refuse_if_squatted


class Mutex:
    """Current-session named mutex, default user DACL, unique per user + state path.

    Abandonment grants the lock; the engine must reconcile its durable dispatch
    journal before sending. No PID-file inference or force-unlocking.
    """
    def __init__(self, name: str, timeout: float = 5.0):
        identity = os.path.normcase(str(Path.home().resolve())) + "\0" + str(name)
        self.name = "Local\\codex-auto-resume-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()
        self.timeout = max(0.0, min(float(timeout), 60.0))
        self.handle = None
        self.abandoned = False

    def __enter__(self):
        k = _kernel()
        k.CreateMutexW.argtypes = [C.c_void_p, W.BOOL, W.LPCWSTR]
        k.CreateMutexW.restype = W.HANDLE
        self.handle = k.CreateMutexW(None, False, self.name)
        existed = C.get_last_error() == ERROR_ALREADY_EXISTS
        if not self.handle:
            raise AdapterError("mutex_creation_failed")
        try:
            _refuse_if_squatted(self.handle, existed)
        except AdapterError:
            self.handle = None
            raise
        result = k.WaitForSingleObject(self.handle, int(self.timeout * 1000))
        if result not in (0, 128):
            k.CloseHandle(self.handle)
            self.handle = None
            raise AdapterError("mutex_busy" if result == 258 else "mutex_wait_failed")
        self.abandoned = result == 128
        return self

    def __exit__(self, *unused):
        if self.handle is not None:
            k = _kernel()
            k.ReleaseMutex.argtypes = [W.HANDLE]
            k.ReleaseMutex.restype = W.BOOL
            k.ReleaseMutex(self.handle)
            k.CloseHandle(self.handle)
            self.handle = None


class StopEvent:
    """Manual-reset named event so `stop` can wake the watcher without killing it."""

    def __init__(self, name: str):
        identity = os.path.normcase(str(Path.home().resolve())) + "::stop::" + str(name)
        self.name = "Local\\codex-auto-resume-stop-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()
        self.handle = None

    @staticmethod
    def _api():
        k = _kernel()
        k.CreateEventW.argtypes = [C.c_void_p, W.BOOL, W.BOOL, W.LPCWSTR]
        k.CreateEventW.restype = W.HANDLE
        k.OpenEventW.argtypes = [W.DWORD, W.BOOL, W.LPCWSTR]
        k.OpenEventW.restype = W.HANDLE
        k.SetEvent.argtypes = [W.HANDLE]
        k.SetEvent.restype = W.BOOL
        k.ResetEvent.argtypes = [W.HANDLE]
        k.ResetEvent.restype = W.BOOL
        return k

    def __enter__(self):
        k = self._api()
        self.handle = k.CreateEventW(None, True, False, self.name)
        existed = C.get_last_error() == ERROR_ALREADY_EXISTS
        if not self.handle:
            raise AdapterError("stop_event_creation_failed")
        try:
            _refuse_if_squatted(self.handle, existed)
        except AdapterError:
            self.handle = None
            raise
        k.ResetEvent(self.handle)  # a stale signal must not stop a fresh watcher
        return self

    def wait(self, seconds: float) -> bool:
        """True when a stop was requested; False after the timeout elapsed."""
        k = self._api()
        millis = int(max(0.0, min(float(seconds), 3600.0)) * 1000)
        return k.WaitForSingleObject(self.handle, millis) == 0

    def __exit__(self, *unused):
        if self.handle is not None:
            _kernel().CloseHandle(self.handle)
            self.handle = None

    def signal(self) -> bool:
        """Signal a running watcher. False when no watcher currently holds the event."""
        k = self._api()
        handle = k.OpenEventW(0x0002, False, self.name)  # EVENT_MODIFY_STATE
        if not handle:
            return False
        try:
            return bool(k.SetEvent(handle))
        finally:
            k.CloseHandle(handle)


class WakeEvent:
    """Auto-reset named event: "look now", sent by Retry Now.

    Only the watcher creates it, and it refuses one a lower-integrity process created
    first, exactly like the stop event. A client can only open it and set it. It is
    never an instruction to send: a wake runs the ordinary tick, every gate included,
    and the stored schedule stays the authority, so a lost wake only delays.
    """

    def __init__(self, name: str):
        identity = os.path.normcase(str(Path.home().resolve())) + "::wake::" + str(name)
        self.name = "Local\\codex-auto-resume-wake-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()
        self.handle = None

    def __enter__(self):
        k = StopEvent._api()
        self.handle = k.CreateEventW(None, False, False, self.name)
        existed = C.get_last_error() == ERROR_ALREADY_EXISTS
        if not self.handle:
            raise AdapterError("wake_event_creation_failed")
        try:
            _refuse_if_squatted(self.handle, existed)
        except AdapterError:
            self.handle = None
            raise
        return self

    def __exit__(self, *unused):
        if self.handle is not None:
            _kernel().CloseHandle(self.handle)
            self.handle = None

    def signal(self) -> bool:
        """Ask a running watcher to look now. False when none holds the event."""
        k = StopEvent._api()
        handle = k.OpenEventW(0x0002, False, self.name)  # EVENT_MODIFY_STATE
        if not handle:
            return False
        try:
            return bool(k.SetEvent(handle))
        finally:
            k.CloseHandle(handle)


def wait_any(handles, seconds: float):
    """Wait on several events. Returns the index of the one signalled, or None on timeout."""
    live = [handle for handle in handles if handle]
    if not live:
        time.sleep(max(0.0, min(float(seconds), 3600.0)))
        return None
    k = _kernel()
    k.WaitForMultipleObjects.argtypes = [W.DWORD, C.POINTER(W.HANDLE), W.BOOL, W.DWORD]
    k.WaitForMultipleObjects.restype = W.DWORD
    array = (W.HANDLE * len(live))(*live)
    millis = int(max(0.0, min(float(seconds), 3600.0)) * 1000)
    result = k.WaitForMultipleObjects(len(live), array, False, millis)
    if result < len(live):
        return handles.index(live[result])
    return None
