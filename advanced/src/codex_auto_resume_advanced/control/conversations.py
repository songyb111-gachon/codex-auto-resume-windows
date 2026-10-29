# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The Dashboard's Find a conversation (v0.6.20, issue #50): the person's own conversations of the Codex home the watcher
drives, with their names, for the pickers to offer beyond the ones Pending and History list.

Read-only and the Dashboard's alone (surfaces.py); no MCP tool reaches it, and nothing it reads reaches a log, the journal,
diagnostics, a notification or the status. A conversation's id and its name (codex/threads.py) - never a word of what it
says. Only the person's own (core's codex/eligibility.row_problem, so a subagent, a review or an archived conversation is
not offered), newest first, at most LIMIT, and not one the person switched off for recovery: that consent is core's
(`switched_off`), and a conversation off is left out before the count is made, so it takes no place of an offered one.
"""
from __future__ import annotations

from ..vocabulary import Refusal
from .resets import _refused

LIMIT = 200


def view(runtime) -> dict:
    """advanced-conversations: [{thread_id, name}], newest first, at most `limit`."""
    from codex_auto_resume.store import Store
    from ..codex import inuse
    from ..codex.threads import Threads
    from ..codex.turns import TurnsUnavailable
    try:
        with Store(runtime.paths.state_dir) as store:
            off = store.disabled_threads()
    except Exception:
        return _refused(Refusal.STATE_UNAVAILABLE)
    try:
        found = Threads(inuse.home(runtime.paths)).own(LIMIT, off)
    except TurnsUnavailable:
        return _refused(Refusal.STATE_UNAVAILABLE)
    return {"done": True, "refusal": None, "limit": LIMIT,
            "conversations": [{"thread_id": thread, "name": name} for thread, name in found]}
