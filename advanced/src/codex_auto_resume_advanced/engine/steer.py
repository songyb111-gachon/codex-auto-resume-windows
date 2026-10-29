# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Steer the running turn (v0.6.20, issue #50 item 2 - steer_send): a line a person wrote, added at once to the turn
that is running in a conversation the Codex app holds, through the app's own IPC pipe (codex/ipc.steer_turn).

Measured on codex-cli 0.165.0-alpha.1.2 (2026-10-29): turn/steer from the product's own app-server session is refused
(MSTEER); over the pipe the line reaches the exact running turn once and the model obeys it, but the Codex app never
shows it - not live, not after the conversation is opened again (MSTEER2, a fail with the note not_as_expected). The
owner's decision of the same day: built, off until a person turns it on, with that warning, and every steer kept in
this product's own record (state/steers.py) so History shows exactly what went in.

The Dashboard's editor asks (control/steer.py) and the watcher alone sends: at P8 this answers with an errand while a
steer waits, and core runs it last in the tick, with its guards. For each steer still requested, oldest first:

1. asked more than EXPIRES ago - refused `expired`: a steer is for the turn running now, never a later one;
2. its conversation switched off - refused `conversation_off`;
3. Codex's history (its own database, read only) not saying the conversation's latest turn is running - `no_turn`;
4. the app not holding the conversation - `not_held`: first the fast count of who holds its writer lock (Restart
   Manager, as core's loaded check reads it: none is not held), then one identity check, core's own loaded check with
   the app paired by its identity;
5. claimed - `requested -> sending`, in one transaction - before anything is written, so no second errand writes it and
   a watcher stopped after the claim never writes it again (its row is settled `unconfirmed` at the next errand);
6. written once, inside core's errand guard (a Pause, Observe only, an administrator's DisableAutoResume and quiet
   hours refuse it - `held`, nothing written): the app took it (`accepted`); it was written and no answer came, or the
   pipe failed after the writing (`unconfirmed` - it may have been delivered; never written again); the pipe was not
   there (`no_pipe`); the app did not hold the conversation (`not_held`); the app refused it or checks another version
   of the request (`app_refused`).

Nothing here says a steer was seen in the conversation: the app does not show it, so History says accepted, may have
been delivered or refused, never more. Every outcome is journalled as one closed word (registry codes), never the words.
"""
from __future__ import annotations

from pathlib import Path

from codex_auto_resume.domain.plug import DEFER

from ..codex import ipc
from ..vocabulary import SteerReason, SteerState

CAPABILITY = "steer_send"
# How long a steer may wait for the watcher, in seconds, before it is refused as expired.
EXPIRES = 120
# The caps a person's requests are held to (control/steer.py): in any 24 hours, in one conversation and in all.
PER_CONVERSATION = 30
PER_DAY = 60
DAY = 86400
RUNNING = "inProgress"
# What codex/ipc.steer_turn's word comes to: the outcome, and a refusal's reason.
OUTCOMES = {
    ipc.Steer.STEERED: (SteerState.ACCEPTED, None),
    ipc.Stop.UNCONFIRMED: (SteerState.UNCONFIRMED, None),
    ipc.Stop.HELD: (SteerState.REFUSED, SteerReason.HELD),
    ipc.Stop.NO_PIPE: (SteerState.REFUSED, SteerReason.NO_PIPE),
    ipc.Stop.NO_CLIENT: (SteerState.REFUSED, SteerReason.NOT_HELD),
}
# The journal's word for each outcome (registry.STEER_SEND.codes).
CODES = {SteerState.ACCEPTED: "accepted", SteerState.UNCONFIRMED: "unconfirmed", SteerState.REFUSED: "refused"}


def outcome(word) -> tuple:
    """(state, reason) for codex/ipc.steer_turn's `word`: anything else it can say - REFUSED, VERSION_MISMATCH, NO_ANSWER
    before the steer, BROKEN with nothing written - is the app refusing it."""
    return OUTCOMES.get(word, (SteerState.REFUSED, SteerReason.APP_REFUSED))


def holders(home, thread):
    """How many processes hold `thread`'s writer lock open (Restart Manager, core's windows.resource_users): a count,
    never a process; None where it could not be read."""
    from codex_auto_resume.windows import resource_users
    try:
        return len(resource_users(Path(home) / "thread-writer-locks" / (thread + ".lock")))
    except Exception:
        return None


def held_by_app(paths, thread) -> bool:
    """Whether core's loaded check finds the Codex app holding `thread`, the app paired by its identity - one check."""
    from ..codex import inuse
    try:
        backend = inuse.backend(paths)
        identity = backend.app_identity()
        return bool(identity) and backend.loaded(thread, identity) == "loaded"
    except Exception:
        return False


def latest_status(home, thread):
    """The status of `thread`'s latest turn in Codex's history (codex/turns.py, read only), or None."""
    from ..codex.turns import Turns
    try:
        latest = Turns(home).latest(thread)
    except Exception:
        return None
    return None if latest is None else latest.status


class _Errand:
    """P8's errand, run by core last in the tick with its guards (domain/plughands.Errand)."""
    __slots__ = ("code", "view")

    def __init__(self, code, view):
        self.code, self.view = code, view

    def run(self, guard):
        self.code.send(self.view, guard)
        return None


class SteerSend:
    """steer_send's code: its P8 errand. `steer`, `status`, `count_holders`, `app_holds` and `home` are seams a test fills
    (ipc.steer_turn, latest_status, holders, held_by_app, the Codex home)."""
    __slots__ = ("paths", "_scoped", "_steer", "_status", "_holders", "_app_holds", "_home")

    def __init__(self, paths, *, steer=None, status=None, count_holders=None, app_holds=None, home=None):
        self.paths = paths
        self._scoped = None
        self._steer = steer
        self._status = status
        self._holders = count_holders
        self._app_holds = app_holds
        self._home = home

    def bind(self, scoped):
        self._scoped = scoped

    def _codex_home(self):
        if self._home is not None:
            return self._home
        from ..codex import inuse
        return inuse.home(self.paths)

    def tick(self, view):
        """P8: the errand, while a steer waits."""
        scoped = self._scoped
        if scoped is None:
            return DEFER
        try:
            if not scoped.steers.waiting():
                return DEFER
        except Exception:
            return DEFER
        return _Errand(self, view)

    # ------------------------------------------------------------------ the errand
    def send(self, view, guard) -> None:
        """Each steer still requested, checked and - where every check passes - claimed and written once."""
        handle = self._scoped.steers
        try:
            handle.cut_short()                       # a watcher stopped between a claim and its answer
            waiting = [row for row in handle.waiting() if row["state"] == SteerState.REQUESTED]
        except Exception:
            return
        for row in waiting:
            try:
                self._one(view, guard, handle, row)
            except Exception:
                continue                             # the next tick looks again; nothing claimed is written twice

    def _one(self, view, guard, handle, row) -> None:
        steer_id, thread = row["steer_id"], row["thread_id"]
        reason = self._refusal(view, handle, row)
        if reason is not None:
            self._settle(handle, steer_id, SteerState.REFUSED, reason)
            return
        if not handle.claim(steer_id):               # the claim, before the one write
            return
        steer = self._steer or ipc.steer_turn
        try:
            word = steer(thread, row["words"], message=row["client_id"], gate=guard)
        except Exception:
            word = ipc.Stop.UNCONFIRMED              # it may have been written: never written again
        state, why = outcome(word)
        self._settle(handle, steer_id, state, why)

    def _refusal(self, view, handle, row):
        """Why `row` may not be written now, or None."""
        if not handle.on():
            return SteerReason.TURNED_OFF
        now = self._scoped.now()
        if not 0 <= now - row["created_at"] <= EXPIRES:
            return SteerReason.EXPIRED
        thread = row["thread_id"]
        try:
            if view.thread_enabled(thread) is False:
                return SteerReason.CONVERSATION_OFF
        except Exception:
            pass
        home = self._codex_home()
        status = (self._status or latest_status)(home, thread)
        if status != RUNNING:
            return SteerReason.NO_TURN
        count = (self._holders or holders)(home, thread)
        if not count:
            return SteerReason.NOT_HELD              # nothing holds it, or who does cannot be read
        if (self._app_holds or held_by_app)(self.paths, thread) is not True:
            return SteerReason.NOT_HELD
        return None

    def _settle(self, handle, steer_id, state, reason) -> None:
        if handle.settle(steer_id, state, reason, at=self._scoped.now()):
            try:
                self._scoped.count(CODES[state])
            except Exception:
                pass


def make(paths) -> SteerSend:
    """The capability's factory (registry.CapabilityDef.make): its code for one installation."""
    return SteerSend(paths)
