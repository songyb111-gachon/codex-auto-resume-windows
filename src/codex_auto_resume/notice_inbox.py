"""The handover of a notice from any thread to the card host on the icon's thread."""
from __future__ import annotations

import collections
import threading


class Inbox:
    """Notices on their way from any thread to the card host on the icon's thread.

    The icon's thread owns every window it draws, so nothing else may touch the card. A
    notice is put here and the host is woken - `wake` posts one message to a window on the
    icon's thread, which then calls `take`. `post` says whether the host has it: False when
    no host is attached, when it has fallen `LIMIT` notices behind, or when it could not be
    woken, and the caller then raises the toast instead. Nothing waits on the icon's thread.
    A notice `post` accepted is the host's to end (`complete`), including when the host goes
    away before taking it: `detach` hands those back rather than dropping them.
    """

    LIMIT = 8

    def __init__(self):
        self._lock = threading.Lock()
        self._waiting = collections.deque()
        self._wake = None

    def attach(self, wake) -> None:
        """Called on the icon's thread once its host window exists. `wake()` returns a bool."""
        with self._lock:
            self._wake = wake

    def detach(self) -> list:
        """The host is going away: nothing more is accepted, and what was waiting - accepted,
        never taken - is handed back, oldest first, for the host to end as today's toast."""
        with self._lock:
            self._wake = None
            left = list(self._waiting)
            self._waiting.clear()
        return left

    @property
    def attached(self) -> bool:
        return self._wake is not None

    def post(self, notice) -> bool:
        with self._lock:
            wake = self._wake
            if wake is None or len(self._waiting) >= self.LIMIT:
                return False
            self._waiting.append(notice)
        try:
            woken = bool(wake())
        except Exception:
            woken = False
        if woken:
            return True
        with self._lock:
            try:
                self._waiting.remove(notice)
            except ValueError:
                return True            # the host took it anyway, woken by an earlier message
        return False

    def take(self) -> list:
        """Everything posted since the last call, oldest first. Called on the icon's thread."""
        with self._lock:
            taken = list(self._waiting)
            self._waiting.clear()
        return taken
