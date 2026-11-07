"""Up to eight sends waiting for their receipts at once, one in each conversation (v0.6.15-beta, P12).

Everything a send decides stays on the tick thread: the gates, the words, the sender, the one claim, the pre-send
look (engine/dispatch.py) - and so does what came of it, settled in claim order. What a worker does is the long,
stateless part between: the bound send it was handed, called with a launch guard on a connection of its own -
SQLite's write lock serialises that guard with every other connection, so a Pause, a Cancel or a conversation
switched off that commits first refuses the launch (I6) - and the wait for its receipt, up to the send's own
timeout. One worker per launch, started at the launch and joined, with its store closed, before the pool's `with`
ends: no thread outlives a tick.

This module calls only the callable it is handed and opens only the store it is handed the opener of. It names no
plug, no log, no announcement, no move and no store but the worker's own, of which it uses the launch guard and
`close` alone (tests/test_structural_invariants.py holds it to that).
"""
from __future__ import annotations

import threading
import time

# Core's own bounds, whatever the plug answers (domain/plughands.py MAX_WORKERS caps the answer): one launch begun
# at least this long after the one before it.
LAUNCH_SPACING = 1.0
# How long one look waits for a worker to finish, while every worker is busy: they are bounded by the send's own
# receipt timeout (codex/transport.py, 45 s and 5 more), so this loop always ends.
POLL_SECONDS = 0.05


class _Launch:
    """One send handed to a worker, and what it answered."""

    __slots__ = ("thread", "context", "response")

    def __init__(self, context):
        self.thread, self.context, self.response = None, context, None


class Slot:
    """A worker kept for one send, taken before its claim. Freed if the send does not go to it."""

    __slots__ = ("pool", "used")

    def __init__(self, pool):
        self.pool, self.used = pool, False

    def free(self):
        self.used = True

    def launch(self, call, thread, words, key, carrying, *, settle):
        """Hand `call` - the send - to a worker: called as call(thread, words, launch_guard=<the worker's own
        store's guard for `key`>, **carrying). `settle` is what the pool hands back, with the response, when it
        settles this launch on the tick thread."""
        if self.used:
            raise RuntimeError("a slot launches once")
        self.used = True
        self.pool._launch(call, thread, words, key, dict(carrying), settle)


class LaunchPool:
    """At most `workers` sends waiting for their receipts at once. Used as a context manager, on the tick thread:
    `take` a slot before a claim, `launch` the send through it, and every launch is joined and settled - by
    `settle(context, response)`, in claim order - before the `with` ends."""

    def __init__(self, workers, open_store, settle, *, clock=time.monotonic, sleep=time.sleep):
        self.workers = workers
        self._open_store, self._settle = open_store, settle
        self._clock, self._sleep = clock, sleep
        self._launches = []                  # in claim order, settled from the front
        self._last_start = None

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        for launch in self._launches:
            launch.thread.join()
        self._settle_finished()
        return False

    # ------------------------------------------------------------------ on the tick thread
    def take(self) -> Slot:
        """A free worker for the next send: every finished launch settled first, then - while every worker is
        busy - a wait, outside any transaction, until one is free."""
        self._settle_finished()
        while self._running() >= self.workers:
            self._sleep(POLL_SECONDS)
            self._settle_finished()
        return Slot(self)

    def _running(self) -> int:
        return sum(1 for launch in self._launches if launch.thread.is_alive())

    def _settle_finished(self):
        """Settle, in claim order, every launch from the front that has finished."""
        while self._launches and not self._launches[0].thread.is_alive():
            launch = self._launches.pop(0)
            launch.thread.join()
            self._settle(launch.context, launch.response)

    def _launch(self, call, thread, words, key, carrying, settle):
        if self._last_start is not None:
            wait = self._last_start + LAUNCH_SPACING - self._clock()
            if wait > 0:
                self._sleep(wait)
        self._last_start = self._clock()
        launch = _Launch(settle)
        launch.thread = threading.Thread(target=self._work, args=(launch, call, thread, words, key, carrying),
                                         name="launch", daemon=True)
        self._launches.append(launch)
        launch.thread.start()

    # ------------------------------------------------------------------ on a worker
    def _work(self, launch, call, thread, words, key, carrying):
        """The worker: its own store, its launch guard, the send and its receipt. A store that cannot be opened
        launched nothing (not started); a send that raised, or answered nothing a send answers, may have gone
        (unknown), as the inline send's (engine/dispatch.py)."""
        try:
            store = self._open_store()
        except Exception:
            launch.response = {"outcome": "not_started", "error_code": "worker_store_unavailable"}
            return
        try:
            try:
                response = call(thread, words, launch_guard=store.submission_guard(key), **carrying)
            except Exception:
                response = {"outcome": "unknown"}
            launch.response = response if isinstance(response, dict) else {"outcome": "unknown"}
        finally:
            try:
                store.close()
            except Exception:
                pass
