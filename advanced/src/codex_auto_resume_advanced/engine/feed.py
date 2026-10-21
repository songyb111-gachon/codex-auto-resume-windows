# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Show OpenAI's service status (status_feed, v0.6.19, plans/v0619-design/D-courier.md).

At P8, while a recovery core holds waits in a usage limit or a connection failure (USAGE_LIMIT and failures.TRANSIENT),
the courier is started with `--feed` once the last reading is FEED_MINUTES old (10, 30 or 60, the person's choice) -
and the Dashboard asks for one reading when it opens (advanced-feed-refresh). The courier reads the page and keeps two
words and a count (courier/feed.py); surfaces.py shows the words while they say degraded or an outage.

A word to show, never a reason: nothing here answers at a gate or decides anything, and no plug answer reads the
`feed` table (a test greps them). Paused, P8 is not asked, so nothing is read.
"""
from __future__ import annotations

from codex_auto_resume import failures
from codex_auto_resume.domain.plug import DEFER

from ..vocabulary import OptionKey

CAPABILITY = "status_feed"
MINUTES = (10, 30, 60)
DEFAULT_MINUTES = 10
# The categories of a waiting record a reading is made for: a usage limit and the connection failures.
CATEGORIES = frozenset({failures.USAGE_LIMIT}) | failures.TRANSIENT


class _Errand:
    __slots__ = ("code", "now")

    def __init__(self, code, now):
        self.code, self.now = code, now

    def run(self, guard):
        self.code._launch(self.code.paths, self.now)
        return None


class StatusFeed:
    """status_feed's code: its P8 errand. `launch` is the seam a test fills: how the courier is started."""
    __slots__ = ("paths", "_scoped", "_launch")

    def __init__(self, paths, *, launch=None):
        self.paths = paths
        self._scoped = None
        self._launch = launch or _start

    def bind(self, scoped):
        self._scoped = scoped

    def tick(self, view):
        scoped = self._scoped
        if scoped is None:
            return DEFER
        try:
            now = scoped.now()
            minutes = scoped.options().get(OptionKey.FEED_MINUTES, DEFAULT_MINUTES)
            last = (scoped.feed() or {}).get("checked_at")
            if isinstance(last, (int, float)) and 0 <= now - last < minutes * 60:
                return DEFER
            return _Errand(self, now) if _waiting(view) else DEFER
        except Exception:
            return DEFER


def _waiting(view) -> bool:
    """Whether core holds a recovery waiting in a usage limit or a connection failure."""
    from codex_auto_resume.domain import states
    try:
        return any(row.get("category") in CATEGORIES for row in view.records_in(states.WAITING))
    except Exception:
        return False


def _start(paths, now):
    from ..courier import launch
    return launch.start_due(paths, now, "--feed")


def make(paths) -> StatusFeed:
    return StatusFeed(paths)
