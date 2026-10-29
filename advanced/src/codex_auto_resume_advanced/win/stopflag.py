# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Whether the watcher's stop event was signalled, seen from the launcher that supervises it (crash_restart, v0.6.19).

The stop event is the watcher's own named, manual-reset event (core's win/sync.StopEvent): uninstall, an upgrade and a
person's Stop signal it to ask the watcher to end. A named event lives only while some process holds a handle to it, so
once the watcher has ended, opening it by name finds nothing, however it ended. The supervisor therefore holds one
handle of its own from the start (`hold`), created by the same name with the default security a watcher creates it
with - the watcher, which creates it next, finds it there, made at this user's own integrity, and resets it, as it
resets a stale signal at every start - and after the watcher ends looks at it without waiting (`signalled`). A stop
asked while the watcher ran is then still there to see; and one asked in the few seconds before a restart is seen by
`wait`, which the supervisor waits on instead of sleeping.

Nothing is signalled or reset here: the event is only held and looked at. The handle is this process's, and Windows
closes it when the launcher ends.
"""
from __future__ import annotations

WAIT_OBJECT_0 = 0
SYNCHRONIZE = 0x00100000


def _kernel():
    import ctypes as C
    from ctypes import wintypes as W
    kernel = C.WinDLL("kernel32", use_last_error=True)
    kernel.CreateEventW.argtypes = [C.c_void_p, W.BOOL, W.BOOL, W.LPCWSTR]
    kernel.CreateEventW.restype = W.HANDLE
    kernel.OpenEventW.argtypes = [W.DWORD, W.BOOL, W.LPCWSTR]
    kernel.OpenEventW.restype = W.HANDLE
    kernel.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
    kernel.WaitForSingleObject.restype = W.DWORD
    kernel.CloseHandle.argtypes = [W.HANDLE]
    kernel.CloseHandle.restype = W.BOOL
    return kernel


def event_name(paths) -> str:
    """The watcher's stop event's name for this installation, as core names it (win/sync.StopEvent)."""
    from codex_auto_resume.win.sync import StopEvent
    return StopEvent(str(paths.state_dir)).name


class StopFlag:
    """The stop event of one installation, held and looked at. `kernel` is the seam a test fills with a fake that
    records its calls; nothing real is opened in a test."""
    __slots__ = ("_name", "_kernel", "_handle")

    def __init__(self, paths, *, kernel=None):
        self._name = event_name(paths)
        self._kernel = kernel
        self._handle = None

    def _api(self):
        if self._kernel is None:
            self._kernel = _kernel()
        return self._kernel

    def hold(self) -> bool:
        """Hold a handle to the event from now on, made where none exists yet. Whether one is held."""
        if self._handle:
            return True
        try:
            self._handle = self._api().CreateEventW(None, True, False, self._name) or None
        except Exception:                              # noqa: BLE001 - not held is all it costs
            self._handle = None
        return self._handle is not None

    def signalled(self) -> bool:
        """Whether a stop was asked: the held handle looked at without waiting - or, where none is held, the event
        opened by name, looked at and closed again (only a watcher still running holds it then)."""
        try:
            kernel = self._api()
            if self._handle:
                return kernel.WaitForSingleObject(self._handle, 0) == WAIT_OBJECT_0
            handle = kernel.OpenEventW(SYNCHRONIZE, False, self._name)
            if not handle:
                return False
            try:
                return kernel.WaitForSingleObject(handle, 0) == WAIT_OBJECT_0
            finally:
                kernel.CloseHandle(handle)
        except Exception:                              # noqa: BLE001 - not known is not signalled
            return False

    def wait(self, seconds) -> bool:
        """Wait up to `seconds` for a stop: True where one was asked by then. With no handle held, the seconds pass
        and what is open by name is looked at once."""
        try:
            if self._handle:
                millis = int(max(0.0, min(float(seconds), 60.0)) * 1000)
                return self._api().WaitForSingleObject(self._handle, millis) == WAIT_OBJECT_0
        except Exception:                              # noqa: BLE001
            pass
        import time
        time.sleep(max(0.0, min(float(seconds), 60.0)))
        return self.signalled()

    def release(self) -> None:
        if self._handle:
            try:
                self._api().CloseHandle(self._handle)
            except Exception:                          # noqa: BLE001
                pass
        self._handle = None
