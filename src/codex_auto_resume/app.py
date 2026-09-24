"""Composition root and the watcher loop (single instance, stoppable, crash-tolerant).

Since v0.6.10-alpha this is the front, and the two things `App` was are apart:

    runtime/app.py     the composition root - what is built, and handed to what
    runtime/loop.py    the tick, the interval, and what wakes it early
    runtime/toasts.py  notifications raised from the loop's own thread

They were one class, which made the watcher - one of the eight parts `docs/ROADMAP.md` says the
Rust core is built from - the same file as the wiring of everything else.
`tests/test_stack.py` is what says so. Everything is re-exported here, so nothing that imports
`app` changes.
"""
from __future__ import annotations

from .runtime.app import App
from .runtime.loop import (DEFAULT_POLL, EXIT_BUSY, EXIT_ERROR, EXIT_OK, EXIT_SCHEMA_NEWER, MAX_POLL, MIN_POLL, MUTEX_RETRY_SECONDS,
                           OPEN_RETRY_MAX_SECONDS, WAKE_COALESCE_SECONDS, WATCH_SECONDS,
                           WatchLoop)
from .runtime.toasts import Toasts

__all__ = ["App", "DEFAULT_POLL", "EXIT_BUSY", "EXIT_ERROR", "EXIT_OK", "EXIT_SCHEMA_NEWER",
           "MAX_POLL", "MIN_POLL", "MUTEX_RETRY_SECONDS", "OPEN_RETRY_MAX_SECONDS", "Toasts",
           "WAKE_COALESCE_SECONDS", "WATCH_SECONDS", "WatchLoop"]
