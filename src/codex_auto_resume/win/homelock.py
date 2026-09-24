"""Two locks: the installer's, which is waited for, and our own home's, which is held.

While an installation, a repair or an update holds its lock nothing starts a watcher, and a
watcher holds an exclusive lock on the home it is watching for its whole life, so two of them
cannot run over one state.
"""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import hashlib
import os
from pathlib import Path

from ..domain.errors import AdapterError
from .kernel import _kernel


INSTALL_LOCK = "Local\\CodexAutoResume.Install"


ERROR_FILE_NOT_FOUND = 2
SYNCHRONIZE = 0x00100000


def install_in_progress():
    """True while an installation, repair or update holds its lock; None where it cannot tell.

    The installer creates its named mutex and holds it for as long as it runs, so the mutex existing
    is the answer, and this only opens it: it never waits on it and never owns it, even for an
    instant, because an installer starting at that instant would take an owner it cannot wait out
    for another installation and stop. A name that does not exist is no installation. The one
    thing that also opens it is the Dashboard's own momentary look, which this reads as busy -
    once, until the next start.
    """
    try:
        k = _kernel()
    except AdapterError:
        return None
    k.OpenMutexW.argtypes = [W.DWORD, W.BOOL, W.LPCWSTR]
    k.OpenMutexW.restype = W.HANDLE
    handle = k.OpenMutexW(SYNCHRONIZE, False, INSTALL_LOCK)
    if handle:
        k.CloseHandle(handle)
        return True
    return False if C.get_last_error() == ERROR_FILE_NOT_FOUND else True


# NOTE: no LockFileEx/byte-lock probe exists anywhere in this tool by design.
# Acquiring the thread writer lock -- even for microseconds on a momentarily free
# range -- could make the ChatGPT app's own try_lock fail. Loaded-state ownership is
# determined solely by the Restart Manager inventory in Backend.loaded().


class HomeLock:
    """An exclusive lock, for the watcher's whole life, on our own file for one Codex home.

    The single-instance mutex is per state directory and per logon session. Two
    installations with different state directories - or one in another session of the
    same user - could otherwise both recover the same Codex conversations. The file is
    ours, under the user's local application data, never anything of Codex's.
    """

    def __init__(self, codex_home, base=None):
        resolved = os.path.normcase(str(Path(codex_home).resolve()))
        root = Path(base) if base else Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "codex-auto-resume" / "homes"
        self.path = root / (hashlib.sha256(resolved.encode("utf-8")).hexdigest() + ".lock")
        self._fd = None

    @property
    def held(self) -> bool:
        return self._fd is not None

    def __enter__(self):
        import msvcrt
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        except OSError:
            raise AdapterError("home_lock_unavailable") from None
        try:
            os.lseek(fd, 0, 0)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            os.close(fd)
            raise AdapterError("home_lock_busy") from None
        self._fd = fd
        return self

    def __exit__(self, *unused):
        if self._fd is not None:
            import msvcrt
            try:
                os.lseek(self._fd, 0, 0)
                msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
            os.close(self._fd)
            self._fd = None
