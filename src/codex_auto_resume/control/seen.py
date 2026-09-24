"""A certain failure stays red until a person has seen it, and where that is written.

v0.6.8. The acknowledgement is one number in a file of its own, out of the store because it is
a display's business and out of settings.json because it is not policy.
"""
from __future__ import annotations

import json
import math
import os
import time

from ..store import LegacyStore
from ..windows import Mutex


# v0.6.8: a certain failure stays on the notification-area icon and the window's taskbar button - red, sweeping - until
# a person has seen it or a new recovery has started since (the user: "확인할 때까지 빨강"). Seeing it is the popup
# opened from the icon, or the Dashboard in front. When that last happened is config/failure-seen.json, one number
# that only moves forward: a display's acknowledgement, kept out of the store, whose schema is exact and fails closed,
# and out of settings.json, which is policy and has watchers of its own. A missing or unreadable file shows nothing,
# and the watcher writes its start as the baseline when there is none, so a failure from before an upgrade never
# lights the icon.
SEEN_LIMIT = 4096          # bytes; the file holds one number
# A seen time more than this past now was written while the clock was ahead: it is not believed beyond now, or every
# failure until the clock caught up would stay dark.
SEEN_SKEW = 300.0


def _replace_seen(path, value) -> bool:
    """Write {"seen_at": value} to `path` whole: a temporary file of a name nobody can plant a link at, flushed to
    disk, then moved over it. False where Windows refused, with nothing left behind."""
    import tempfile
    try:
        descriptor, temporary = tempfile.mkstemp(dir=str(path.parent), prefix="failure-seen.", suffix=".tmp")
    except OSError:
        return False
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump({"seen_at": value}, handle, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        return True
    except OSError:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        return False


def unseen_failure(marks, seen_at):
    """The failure time the icon should still show, or None: the newest certain failure (Store.failure_marks), if no
    recovery was on its way after it - one at the same moment is the failed record's own - and nobody has seen it."""
    if not isinstance(marks, dict) or seen_at is None:
        return None
    failed, started = marks.get("failed_at"), marks.get("started_at")
    if failed is None or (started is not None and started > failed):
        return None
    return failed if failed > seen_at else None


class SeenMixin:
    """Reading and writing the moment a failure was last seen."""

    # ------------------------------------------------------------ a failure seen
    def _seen_file(self):
        """(time, why): when a person last saw a failure and "ok"; or None and "missing" (no file), "invalid" (one that
        cannot be believed) or "unreadable" (one that could not be read just now). Read again only when the file
        changed - a replace is a new file, so its id is part of that - and so the icon can ask every second."""
        path = self.paths.failure_seen_file
        try:
            if path.is_symlink():
                return None, "invalid"
            info = path.stat()
        except FileNotFoundError:
            return None, "missing"
        except OSError:
            return None, "unreadable"
        stamp = (info.st_ino, info.st_mtime_ns, info.st_size)
        if self._seen is not None and self._seen[0] == stamp:
            return self._seen[1]
        value = None
        if info.st_size <= SEEN_LIMIT:
            try:
                value = json.loads(path.read_text(encoding="utf-8")).get("seen_at")
                value = None if isinstance(value, bool) or not isinstance(value, (int, float)) else float(value)
            except OSError:
                return None, "unreadable"
            except (ValueError, AttributeError, OverflowError, TypeError):
                value = None
        answer = (value, "ok") if value is not None and math.isfinite(value) and value >= 0 else (None, "invalid")
        self._seen = (stamp, answer)
        return answer

    def failure_seen_at(self):
        """When a person last saw a failure, or None when nothing says: no file, or one that cannot be believed."""
        return self._seen_file()[0]

    def failure_unseen(self, marks) -> bool:
        """Whether a failure the store's marks name is still to be shown (unseen_failure), for the icon."""
        return unseen_failure(marks, self.failure_seen_at()) is not None

    def _newest_failure(self):
        try:
            with self._open(legacy_ok=True) as store:
                return None if isinstance(store, LegacyStore) else store.failure_marks()["failed_at"]
        except Exception:
            return None

    def acknowledge_failure(self, now=None, *, baseline=False) -> dict:
        """Record that a person has seen every failure so far: the popup opened, or the Dashboard in front.

        The time only moves forward, and both processes that write it - the watcher's icon and the window's bridge -
        take one named lock to read, decide and replace it. It covers the newest failure there is even where the clock
        that stamped it was ahead, and a seen time written while the clock was ahead is not believed beyond now.
        `baseline` (the watcher, as it starts and at every tick) writes only where there is no file or one that cannot
        be believed - never over one that just could not be read. A write Windows refuses is a miss, never an error:
        the next tick or acknowledgement makes it good."""
        now = time.time() if now is None else float(now)
        path = self.paths.failure_seen_file
        seen, why = self._seen_file()
        if baseline and (why == "unreadable" or (why == "ok" and seen <= now + SEEN_SKEW)):
            return {"seen_at": seen, "written": False}
        if not path.parent.is_dir():
            return {"seen_at": seen, "written": False}
        newest = None if baseline else self._newest_failure()
        try:
            lock = Mutex(str(path), timeout=2.0)
            lock.__enter__()
        except Exception:
            lock = None
        try:
            self._seen = None
            seen, why = self._seen_file()
            if baseline and (why == "unreadable" or (why == "ok" and seen <= now + SEEN_SKEW)):
                return {"seen_at": seen, "written": False}
            believed = None if seen is None or seen > now + SEEN_SKEW else seen
            value = max(value for value in (believed, now, newest) if value is not None)
            if not _replace_seen(path, value):
                return {"seen_at": seen, "written": False}
            self._seen = None
            return {"seen_at": value, "written": True}
        finally:
            if lock is not None:
                lock.__exit__(None, None, None)
