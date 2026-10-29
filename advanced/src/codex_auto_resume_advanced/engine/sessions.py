# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Other sessions: the conversations of a terminal's Codex CLI and TUI and of VS Code, recovered too (v0.6.16-beta.4,
P18 and P16).

The standard edition looks at the Codex app's own conversations alone (A15), and waits, with its own reason, while
another Codex session holds one (core's held_by_other_session). With this on:

* P18 - core is told to watch both other kinds, `cli` and `ide` (one capability for both, Q10): their failures are
  detected and every check of their records made as the app's are (core's codex/eligibility.py). Turned off, core
  ends the waiting records of those conversations (session_kind_off) and follows what it already sent to its end.
* P16 - for a conversation another Codex session holds (`holder="session"`), TO_SESSION: core's ordinary send through
  `codex queue`, with its marker, for that session to take (M5) - taken back when that session lets go of it or does
  not take it within the delivery window, and given back to waiting (core's engine/tosession.py). A conversation
  nothing holds while Codex is closed is headless_run's to run, never this one's.

What Codex writes to tell these conversations apart (their originators) is what MO measures; until it passes for the
Codex in force its statement carries the UNMEASURED warning, and a wrong word detects nothing. A continuation it sent
that the session did not take within the window trips it (NOT_DISPATCHED_BY_SESSION, runtime.moved): off, or - kept
on (K8, since v0.6.19-beta.3) - a note, with what was sent taken back and given back to waiting either way.
"""
from __future__ import annotations

from codex_auto_resume.domain.plug import DEFER, Alternative

CAPABILITY = "other_sessions"
KINDS = frozenset({"cli", "ide"})
# Where core asks P16 for a conversation another Codex session holds (core's engine/tosession.py).
SESSION = "session"


class OtherSessions:
    """The capability's code: its hooks at P18 and P16. It holds nothing and reads nothing."""
    __slots__ = ("paths",)

    def __init__(self, paths):
        self.paths = paths

    def sessions(self):
        """P18: both other kinds of conversation, watched."""
        return KINDS

    def unloaded(self, record):
        """P16: TO_SESSION for a conversation another Codex session holds; DEFER for everything else - the watch of
        an item queued for opening, which hands no holder, among them."""
        if not isinstance(record, dict) or record.get("holder") != SESSION or "queued_since" in record:
            return DEFER
        return Alternative.TO_SESSION


def make(paths) -> OtherSessions:
    """The capability's factory (registry.CapabilityDef.make): its code for one installation."""
    return OtherSessions(paths)
