# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Open a waiting conversation in Codex (v0.6.19, issue #50): a recovery or a scheduled message that waits only because
the Codex app does not have its conversation open gets that exact conversation opened, once, through Codex's own link.

The standard edition waits for a person to open a conversation the app does not hold (A11), and never wakes one (0.5).
With this on, at P8 - as an errand, last in the tick, after core's own gates were looked at this tick - it looks for a
candidate, and opens at most one conversation a tick through core's codex_link (`codex://threads/<id>`, handed to
explorer.exe, as a click on Open Codex is). It never decides anything else: nothing is sent here, and the ordinary
next check finds the conversation loaded and sends as always - opening is never taken as proof of loading (A11 kept,
#50's own boundary).

A candidate is
* a record of core's whose last gate vector - core's own validated column - fails thread_available alone, the app
  running and the conversation known not loaded (`notLoaded`, which the Restart Manager's or the loaded list's answer
  gives; unknown or ambiguous never opens, E1), every other gate passed or not reached; with Also start Codex on, also
  one that fails it because the app is closed (nothing is loaded then);
* or one queue_for_open already queued in Codex for when its conversation is opened (core's for_open): opening delivers
  it - the open is the trigger, as M1 and MQO measured, and nothing is sent a second time (they compose);
* or a message of the edition's own - a queued prompt or a reset message - whose record waits at core's
  thread_available gate for the same reasons (state/prompts, state/resets keep the gate core named), and not one held
  for a running turn.

And it opens only while the person has been away from the PC for the minutes they chose (GetLastInputInfo, a time and
nothing of what was typed - unknown never opens), Windows has a handler for `codex:` (control/opencodex.py's reader),
and the Codex app is running - unless Also start Codex is on. Recovery paused, Observe only, an administrator's
DisableAutoResume and quiet hours hold it: the open is made inside core's errand guard. The caps are kept in the state
(`opens`, written before the link is opened): ten minutes between any two opens, an hour between two of one
conversation, three for one record, twelve a day. The next look settles each open: loaded where the record no longer
waits for its conversation to be opened, not_loaded where it still does after two looks.
"""
from __future__ import annotations

import hashlib

from codex_auto_resume import machine
from codex_auto_resume.domain import states
from codex_auto_resume.domain.plug import DEFER
from codex_auto_resume.engine.foropen import ForOpenMixin

from ..vocabulary import OpenOutcome, OptionKey, PromptReason, PromptState, RecordState, RuleState

CAPABILITY = "open_to_send"
# The person's choices: how long the PC has been idle first, in minutes, and whether Codex is started to open one.
IDLE_MINUTES = (2, 5, 15)
DEFAULT_IDLE = 5
ON, OFF = 1, 2
# The caps, each read from the opens kept in the state.
GAP = 600
PER_CONVERSATION = 3600
PER_RECORD = 3
PER_DAY = 12
DAY = 86400
# How many looks after an open still find its record waiting for the conversation before it is not_loaded.
LOOKS = 2
# Why core's thread_available gate waits: the app does not hold the conversation, or the app is closed.
NOT_LOADED = "notLoaded"
APP_CLOSED = "desktop_app_unavailable"
GATE = "thread_available"
# Core's records that may be candidates: waiting, and those a queue item holds (queue_for_open's).
LOOKED_AT = states.WAITING | states.IN_FLIGHT | states.OBSERVING | states.CLAIMED
RESET_MESSAGE = "reset_message"


def record_of(kind, identity) -> str:
    """The 64-hex record id an open is kept under: the edition's own record id as it is, and a digest of core's interruption
    id - never the id itself."""
    if kind != "core" and isinstance(identity, str) and len(identity) == 64:
        return identity
    return hashlib.sha256(("%s:%s" % (kind, identity)).encode("utf-8")).hexdigest()


def core_candidate(row, start_codex):
    """Whether core's record `row` is a candidate (see the module's text), and how: "for_open", "waiting", or None."""
    try:
        if ForOpenMixin.for_open(row):
            return "for_open"
    except Exception:
        return None
    if row.get("state") not in states.WAITING:
        return None
    gates = machine.decode_gates(row.get("gate_eval"))
    wanted = {(machine.WAIT, NOT_LOADED)} | ({(machine.WAIT, APP_CLOSED)} if start_codex else set())
    if gates.get(GATE) not in wanted:
        return None
    for name, (result, reason) in gates.items():
        if name != GATE and result != machine.PASS and not (result == machine.UNKNOWN and reason == machine.NOT_CHECKED):
            return None
    return "waiting"


def own_candidate(row, start_codex) -> bool:
    """Whether a message of the edition's own - a prompt's or a reset message's row, with its record's state - waits for
    its conversation to be opened alone."""
    reasons = (NOT_LOADED, APP_CLOSED) if start_codex else (NOT_LOADED,)
    return (row.get("record_state") == RecordState.WAITING and row.get("gate") == GATE
            and row.get("gate_reason") in reasons and row.get("reason") != PromptReason.TURN_RUNNING)


def idle_seconds():
    """Seconds since anybody last used this PC's keyboard or mouse, or None (core's win/powerdown.py)."""
    from codex_auto_resume.win import powerdown
    return powerdown.idle_seconds()


def handler_registered() -> bool:
    """Whether Windows has a handler for `codex:` links (control/opencodex.py, read and never written)."""
    from ..control.opencodex import handler_registered as registered
    return registered()


def app_running():
    """Whether the Codex app runs now - True, False, or None where the process list cannot be read (core's
    codex/pairing.py, the one PowerShell look core makes, with no window)."""
    from codex_auto_resume.codex.errors import AdapterError
    from codex_auto_resume.codex.pairing import app_running as running, inventory
    try:
        return running(inventory())
    except (AdapterError, OSError):
        return None


def open_link(thread_id) -> bool:
    """Codex's own link to `thread_id`, handed to Windows (core's codex_link.open_in_codex): whether it was handed."""
    from codex_auto_resume import codex_link
    link = codex_link.codex_thread_uri(thread_id)
    return link is not None and codex_link.open_in_codex(link) is True


class _Errand:
    __slots__ = ("code", "view")

    def __init__(self, code, view):
        self.code, self.view = code, view

    def run(self, guard):
        return self.code.look(self.view, guard)


class OpenTarget:
    """open_to_send's code: its P8 errand. What it opened and has not settled yet is kept in memory (`_pending`, open id:
    [kind, identity, looks]); after a restart such an open stays `opened` and still counts toward every cap."""
    __slots__ = ("paths", "_scoped", "_pending")

    def __init__(self, paths):
        self.paths = paths
        self._scoped = None
        self._pending = {}

    def bind(self, scoped):
        self._scoped = scoped

    def tick(self, view):
        """P8: the errand, where there is an open to settle or - as the last tick's gates left them - a candidate."""
        scoped = self._scoped
        if scoped is None:
            return DEFER
        try:
            start_codex = scoped.options().get(OptionKey.OPEN_START_CODEX) == ON
            if not self._pending and not self.candidates(view, start_codex):
                return DEFER
        except Exception:
            return DEFER
        return _Errand(self, view)

    # ------------------------------------------------------------------ the errand
    def look(self, view, guard):
        scoped = self._scoped
        handle = scoped.opens
        if not handle.on():
            return None
        options = scoped.options()
        start_codex = options.get(OptionKey.OPEN_START_CODEX) == ON
        found = self.candidates(view, start_codex)
        now = scoped.now()
        self._settle(handle, found)
        # Every open kept (seven days of them, state/journal.py) but those never made.
        made = [row for row in handle.opens(0) if row["outcome"] != OpenOutcome.REFUSED]
        if (sum(row["at"] > now - DAY for row in made) >= PER_DAY
                or any(now - row["at"] < GAP for row in made)):
            return None
        chosen = None
        for kind, identity, thread in found:
            record = record_of(kind, identity)
            if (sum(row["record_id"] == record for row in made) >= PER_RECORD
                    or any(row["thread_id"] == thread and now - row["at"] < PER_CONVERSATION for row in made)):
                continue
            chosen = (kind, identity, thread, record)
            break
        if chosen is None:
            return None
        idle = idle_seconds()
        minutes = options.get(OptionKey.OPEN_IDLE_MINUTES, DEFAULT_IDLE)
        if idle is None or idle < 60 * minutes or handler_registered() is not True:
            return None
        if not start_codex and app_running() is not True:
            return None
        kind, identity, thread, record = chosen
        opened = handle.add_open(thread, record, at=now)            # the claim, before the link is opened
        with guard() as permitted:
            handed = bool(permitted) and self._open(thread)
        if not handed:
            handle.settle_open(opened, OpenOutcome.REFUSED)
            return None
        self._pending[opened] = [kind, identity, 0]
        self._count("opened")
        return None

    def candidates(self, view, start_codex) -> list:
        """Every candidate now, oldest first: (kind, identity, thread) - core's records first, then the queued prompts and
        the reset messages."""
        found = []
        try:
            for row in view.records_in(LOOKED_AT):
                kind = core_candidate(row, start_codex)
                if kind is not None:
                    found.append(("core", row["interruption_id"], row["thread_id"]))
        except Exception:
            pass
        scoped = self._scoped
        try:
            for row in scoped.prompts.prompts(pending=True):
                if row["state"] == PromptState.READY and row["record_id"] and own_candidate(row, start_codex):
                    found.append(("prompt", row["record_id"], row["thread_id"]))
        except Exception:
            pass
        try:
            for row in scoped.resets.reset_rules(capability=RESET_MESSAGE):
                if row["state"] == RuleState.READY and row.get("record_id") and own_candidate(row, start_codex):
                    found.append(("reset", row["record_id"], row["thread_id"]))
        except Exception:
            pass
        return found

    def _settle(self, handle, found) -> None:
        """Each open not settled yet, looked at again: loaded where its record no longer waits for its conversation to
        be opened, not_loaded where it still does after LOOKS looks."""
        waiting = {(kind, identity) for kind, identity, _thread in found}
        for opened, entry in list(self._pending.items()):
            kind, identity, looks = entry
            if (kind, identity) not in waiting:
                outcome, code = OpenOutcome.LOADED, "loaded"
            elif looks + 1 >= LOOKS:
                outcome, code = OpenOutcome.NOT_LOADED, "not_loaded"
            else:
                entry[2] = looks + 1
                continue
            self._pending.pop(opened, None)
            try:
                handle.settle_open(opened, outcome)
            except Exception:
                continue
            self._count(code)

    @staticmethod
    def _open(thread) -> bool:
        try:
            return open_link(thread) is True
        except Exception:
            return False

    def _count(self, code) -> None:
        try:
            self._scoped.count(code)
        except Exception:
            pass


def make(paths) -> OpenTarget:
    """The capability's factory (registry.CapabilityDef.make): its code for one installation."""
    return OpenTarget(paths)
