# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Another model when one is at capacity (v0.6.16-beta.4, P16 and P8; headless only).

Codex's queue carries input only, so a conversation the app holds keeps its model, and nothing here touches one: the
standard edition retries the same model at its own pace. With this on, for a record of a server error whose failed
turn Codex coded `serverOverloaded`, once its task has had the person's Attempts (1 to 3, 2 by default) of
continuations, and only where nothing holds the conversation while Codex is closed, P16 answers the headless route
in fallback mode (codex/headless.py): thread/resume reads the conversation's own model, model/list Codex's default
(`isDefault`) - nothing is stored, Q5 - and only where the two differ is one turn started with `model` on it; the
follower puts the conversation's own model back with thread/settings/update before letting go, on every way the
turn ends. Which of that and a resume-only override is the route is MF's to settle; until it passes for the Codex in
force the statement carries the UNMEASURED warning. A restore Codex refused is journalled `model_not_restored`, a
closed word with no model's name, which Pending and History say in words (D4: the journal keeps codes only).

The conversation's own model is stored as owed back (state/runs.py, `restore_model`) before the turn/start, and
cleared only once it reads back put back. A debt left - a watcher stopped mid-turn, a restore Codex refused - is
P8's errand: with no run live, Codex closed and nothing holding the conversation, it is put back, the one write
inside core's errand guard, and read back.

Never for a usage, rate, sign-in or billing failure: only server_5xx with Codex's capacity code.
"""
from __future__ import annotations

from codex_auto_resume.domain import ids
from codex_auto_resume.domain.plug import DEFER

from ..codex import headless, inuse
from ..codex.headless import _close, _model
from ..codex.turns import Turns
from ..vocabulary import OptionKey
from .headless import HOUR, _app_running, follow_up, unheld

CAPABILITY = "model_fallback"
KIND = "server_5xx"
CODE = "serverOverloaded"
ATTEMPTS = (1, 2, 3)
DEFAULT_ATTEMPTS = 2
NOT_RESTORED = "model_not_restored"
# How often a model still owed back is tried again, in seconds: a restore Codex refuses is not asked every tick.
RESTORE_EVERY = 600


class ModelFallback:
    """The capability's code: its hooks at P16 and P8. `bind` gives it its view of the state (state.Scoped)."""
    __slots__ = ("paths", "_scoped", "_turns", "_open", "follower", "_app", "_routes", "_unheld", "_tried")

    def __init__(self, paths, *, turns=None, session=None, follower=None, app_running=None, unheld_now=None):
        self.paths, self._scoped, self._turns = paths, None, turns
        self._open = session if session is not None else headless.live_session(paths)
        self.follower = follower or headless.FOLLOWER
        self._app = app_running if app_running is not None else _app_running(paths)
        self._routes = {}
        self._unheld = unheld_now if unheld_now is not None else _unheld_now(paths)
        self._tried = {}

    def bind(self, scoped):
        self._scoped = scoped

    def _attempts(self) -> int:
        try:
            chosen = self._scoped.options().get(OptionKey.ATTEMPTS, DEFAULT_ATTEMPTS)
        except Exception:
            chosen = DEFAULT_ATTEMPTS
        return chosen if chosen in ATTEMPTS else DEFAULT_ATTEMPTS

    def _overloaded(self, record) -> bool:
        """Whether the record's failed turn is Codex's capacity code (codex/turns.turn_code - a code, never words)."""
        try:
            turns = self._turns if self._turns is not None else Turns(inuse.home(self.paths))
            return turns.turn_code(record["thread_id"], record["turn_id"]) == CODE
        except Exception:
            return False

    def unloaded(self, record):
        """P16: the fallback route, for an unheld conversation at capacity after the Attempts chosen."""
        key = record.get("interruption_id") if isinstance(record, dict) else None
        if (not unheld(record) or record.get("category") != KIND or not ids.is_interruption_id(key)
                or self._scoped is None or self.follower.live() is not None
                or (record.get("chain_continuations") or 0) < self._attempts() or not self._overloaded(record)):
            return DEFER
        route = headless.HeadlessRun(CAPABILITY, key=key, session=self._open, follower=self.follower,
                                     seconds=HOUR, mode=headless.FALLBACK, app_running=self._app,
                                     owe=lambda thread_id, model, seconds: self._owe(key, thread_id, model, seconds))
        self._routes = {key: route}
        return route

    def _owe(self, key, thread_id, model, seconds) -> bool:
        now = self._scoped.now()
        self._scoped.runs.owe(key, thread_id, model, started_at=now, ends_by=now + seconds)
        return True

    def tick(self, view):
        """P8: the run kinds' one path (engine/headless.follow_up) - a Stop handed on, a row no thread follows ended
        LOST - a model put back cleared from the debt, one Codex would not put back journalled; then, while a debt is
        left and no run is live, the errand that puts it back."""
        scoped = self._scoped

        def told(ended):
            if ended.get("model_restored") is True:
                scoped.runs.restored(ended["key"])
            elif ended.get("model_restored") is False:
                scoped.count(NOT_RESTORED)
        follow_up(scoped, self.follower, CAPABILITY, self._routes.values(), on_end=told)
        try:
            owed = [row for row in (scoped.runs.owed() if scoped is not None and self.follower.live() is None else ())
                    if scoped.now() - self._tried.get(row["interruption_id"], float("-inf")) >= RESTORE_EVERY]
        except Exception:
            owed = []
        return _Restore(self, owed[0]) if owed else DEFER

    # v0.6.18: turned off - by the person, a tripwire, All off or an edition's entry - or watched, a model still owed
    # back is put back all the same (runtime.Runtime.tick): a clean-up of its own turn, never a turn of its own; and a
    # Stop still reaches a live run.
    tend = tick


class _Restore:
    """P8's errand: the model a fallback turn still owes its conversation put back - only while no run is live, Codex
    is closed and nothing holds the conversation; the one write inside core's errand guard, read back outside it."""
    __slots__ = ("code", "row")

    def __init__(self, code, row):
        self.code, self.row = code, row

    def run(self, guard):
        code, thread, model = self.code, self.row["thread_id"], self.row["restore_model"]
        try:
            if code.follower.live() is not None or code._unheld(thread) is not True:
                return
            code._tried[self.row["interruption_id"]] = code._scoped.now()
            session = code._open(CAPABILITY)
            session.__enter__()
        except Exception:
            return
        restored, asked = False, False
        try:
            session.call("thread/resume", {"threadId": thread, "excludeTurns": True})
            with guard() as permitted:
                if permitted is not True:
                    return
                asked = True
                session.call("thread/settings/update", {"threadId": thread, "model": model})
            resumed = session.call("thread/resume", {"threadId": thread, "excludeTurns": True})
            restored = _model(resumed) == model
        except Exception:
            restored = False
        finally:
            _close(session)
        if restored:
            code._scoped.runs.restored(self.row["interruption_id"])
        elif asked:
            code._scoped.count(NOT_RESTORED)


def _unheld_now(paths):
    """The look at a thread before its model is put back: the Codex app not running and nothing holding it (core's
    Backend.holder), on a backend made for the look."""
    def look(thread_id) -> bool:
        backend = inuse.backend(paths)
        return backend.app_identity() is None and backend.holder(thread_id) == "none"
    return look


def make(paths) -> ModelFallback:
    """The capability's factory (registry.CapabilityDef.make): its code for one installation."""
    return ModelFallback(paths)
