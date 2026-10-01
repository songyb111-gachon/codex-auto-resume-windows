# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Goal continuation: the advanced edition's answer at P16, P3 and P5.

Codex pauses a conversation's goal when a usage limit stops it (status usage_limited) and does
not resume it after the reset. The standard edition never touches a goal (standard 0.5): it waits
until the app has the conversation open (A11) and queues its continuation through `codex queue`
(A2). With this capability on, and only for an interruption that is a usage limit:

* P16 - a conversation the app does not hold. Where core would wait for the app to open it and
  the conversation's goal is paused by the usage limit, this names itself as the route. Core then
  runs every gate a send passes, claims the record - this capability paying one unit there, before
  anything is asked of Codex - makes its pre-send look, and calls `resume` once inside the launch
  guard. `resume` sets that existing goal active through Codex's own app server - thread/goal/set
  with the thread and the status alone: never a goal created, never its words touched - and reads
  it back. Measurement M2 found a goal set so is not seen while the app holds the conversation
  and is live once the app loads it again, so this is where it is set: when the app next opens the
  conversation Codex carries the goal on, and that turn supersedes the record by core's own rule.
  The app may open the conversation while the session starts, so the set is made only once core's
  own look, asked again after the session is up, still finds it not held; where it does not, the
  goal is left as it was and the answer is "not started", so core gives its claim back and the
  standard continuation follows once the app holds the conversation.
* P3 - thread_available, once the app holds the conversation. While its goal is active - Codex's
  own goal runtime is carrying the conversation on - the standard continuation is held back, for
  at most HOLD_SECONDS from the first time it was found so, so the two never both run.
* P5 - a conversation the app holds, whose goal is paused by the usage limit, and only where
  measurement M2b's recorded verdict is a pass for the Codex in force (a goal set active and a turn
  queued while the app holds the conversation: the turn runs, and the goal stays active and
  carries on). There this is the channel: it sets the goal active and then adds the continuation
  to the conversation's queue, in that order, as M2b did. Anywhere else it answers nothing, and
  core sends through `codex queue`, as the standard edition does.

What this code does not do is decide: every gate, the claim, the pre-send look and the launch
guard are core's, and so is what follows. The goal is read from Codex's goals database - which
goal, its status, when it changed (codex/goals.py) - and its words are never read, stored or
logged. A goal that cannot be read is no goal: the answer is the standard edition's.

No test opens a real Codex: the tests give it a goals database of their own and a session over a
fake app server, and a live session is opened only by a watcher that has this capability armed.
"""
from __future__ import annotations

from contextlib import nullcontext
import time

from codex_auto_resume import failures
from codex_auto_resume.domain import ids
from codex_auto_resume.domain.plug import DEFER, Alternative

from ..codex import inuse
from ..codex.goals import Goals
from ..codex.protocol import Session, SessionRefused
from ..measured import MEASURED
from ..vocabulary import GoalStatus, Measurement, Verdict
from .markerfree import MAX_PROMPT, _close, _queue_id

CAPABILITY = "goal_continuation"
SET = "thread/goal/set"
ADD = "thread/queue/add"
# How long the standard continuation is held back while a conversation's goal is active, from the
# first time the app was found holding it so: Codex's goal runtime continues an active goal as
# soon as the conversation is idle, and one that has not in ten minutes is not going to.
HOLD_SECONDS = 600
# Records remembered for that, forgotten all at once past this many.
SEEN_LIMIT = 4096


def _usage_record(record) -> bool:
    return (isinstance(record, dict) and record.get("category") == failures.USAGE_LIMIT
            and ids.is_uuid(record.get("thread_id")))


def m2b_passed(view, measured) -> bool:
    """Whether M2b's recorded verdict is a pass for the Codex in force: a pass on the very version
    the Compatibility Registry's view names. No verdict, a fail, or a pass on another Codex is not
    - a measurement speaks for the one Codex it was made on."""
    engine = view.get("engine") if isinstance(view, dict) else None
    version = engine.get("version") if isinstance(engine, dict) else None
    entry = measured.get(Measurement.M2B) if isinstance(measured, dict) else None
    return (isinstance(version, str) and isinstance(entry, tuple) and len(entry) == 2
            and entry[0] == Verdict.PASS and entry[1] == version)


def _yes(look) -> bool:
    """What a look core hands answers, where it is a plain yes; a look that raises is no."""
    try:
        return look() is True
    except Exception:
        return False


def _view_of(paths):
    """The Compatibility Registry's view as every front end reads it (arming._view_of)."""
    from codex_auto_resume import compatio, settings
    return compatio.reader_view(paths, settings=settings.load(paths.settings_file))


class GoalContinuation:
    """The capability's code: its hooks at P16, P3 and P5, the route core calls and the channel
    core sends through.

    Its seams are the tests': `session` opens the app-server session the calls are made in (None:
    a live one against the Codex the watcher drives, restricted to this capability's methods,
    codex/protocol.CAPABILITY_METHODS); `home` is the Codex home whose goals are read (None: the
    watcher's, the one core reads - codex/inuse.py); `view` and `measured` give the Compatibility
    Registry's view and the measurements (None: the watcher's view, and measured.py)."""
    __slots__ = ("paths", "clock", "_open", "_home", "_view", "_measured", "_seen")

    def __init__(self, paths, *, session=None, home=None, view=None, measured=None, clock=time.time):
        self.paths = paths
        self.clock = clock
        self._open, self._home, self._view, self._measured = session, home, view, measured
        self._seen = {}

    # ------------------------------------------------------------------ reading
    def _goal(self, thread_id):
        """The conversation's goal, or None where it has none - or it cannot be read, which is
        the standard edition's answer, never a reason to act."""
        try:
            return Goals(self._home if self._home is not None else inuse.home(self.paths)).read(thread_id)
        except Exception:
            return None

    def _limited(self, record):
        """The goal of `record`'s conversation where it is paused by the usage limit, else None."""
        if not _usage_record(record):
            return None
        goal = self._goal(record["thread_id"])
        return goal if goal is not None and goal.status == GoalStatus.USAGE_LIMITED else None

    def _m2b(self) -> bool:
        try:
            view = self._view() if self._view is not None else _view_of(self.paths)
            measured = self._measured() if self._measured is not None else MEASURED
            return m2b_passed(view, measured)
        except Exception:
            return False

    # ------------------------------------------------------------------ the plug's points
    def unloaded(self, record):
        """P16: this is the route for a conversation the app does not hold, where its goal is
        paused by the usage limit; DEFER - the standard edition's wait - anywhere else."""
        return self if self._limited(record) is not None else DEFER

    def gate(self, name, record, facts):
        """P3, at thread_available alone: HOLD while the conversation's goal is active - Codex is
        carrying it on - for at most HOLD_SECONDS from the first time it was found so."""
        if name != "thread_available" or not _usage_record(record):
            return DEFER
        key = record.get("interruption_id")
        goal = self._goal(record["thread_id"])
        if goal is None or goal.status != GoalStatus.ACTIVE:
            self._seen.pop(key, None)
            return DEFER
        now = self.clock()
        if key not in self._seen and len(self._seen) >= SEEN_LIMIT:
            self._seen.clear()
        first = self._seen.setdefault(key, now)
        return Alternative.HOLD if 0 <= now - first < HOLD_SECONDS else DEFER

    def sender(self, record, backend):
        """P5: this is the channel only where M2b passed for the Codex in force and the goal is
        paused by the usage limit. `backend` is core's stand-in, never core's backend."""
        if not self._m2b() or self._limited(record) is None:
            return DEFER
        return self

    # ------------------------------------------------------------------ what core calls
    def resume(self, thread_id, *, launch_guard=None, still_unloaded=None):
        """Set `thread_id`'s goal, paused by the usage limit, active again - and say what came of it
        the way core's backend says what came of a send. Never raises.

        `still_unloaded` is core's look at whether the app still does not hold the conversation
        (engine/delivery.py in core). It is asked once the session is up, at the last moment
        before the set: seconds after core last looked, in which the app may have opened the
        conversation - and M2 found a goal set while the app holds it is not seen. Anything but
        yes leaves the goal as it was, and nothing was asked of Codex that changes it.

        Accepted only when the goal reads back active and the same goal. Not started where nothing
        was asked of Codex, or Codex said no and the goal is not active, so nothing will carry the
        conversation on. Anything else - no answer, or an answer the goal does not bear out - is
        unknown, and core never tries it again."""
        if not ids.is_uuid(thread_id):
            return {"outcome": "not_started", "error_code": "queue_preflight_failed"}
        before = self._goal(thread_id)
        if before is None or before.status != GoalStatus.USAGE_LIMITED:
            # Resumed, paused or cleared by a person since it was asked: nothing to do, and
            # nothing asked of Codex.
            return {"outcome": "not_started", "error_code": "queue_preflight_failed"}
        session, refused = self._opened(launch_guard)
        if refused is not None:
            return refused
        try:
            if still_unloaded is not None and not _yes(still_unloaded):
                return {"outcome": "not_started", "error_code": "queue_preflight_failed"}
            session.call(SET, {"threadId": thread_id, "status": str(GoalStatus.ACTIVE)})
        except SessionRefused:
            return {"outcome": "not_started", "error_code": "queue_preflight_failed"}
        except Exception as exc:
            if getattr(exc, "method", None) == SET:
                # Codex answered, and its answer was no. A goal that is not active carries nothing
                # on, so nothing was started.
                after = self._goal(thread_id)
                if after is None or after.status != GoalStatus.ACTIVE:
                    return {"outcome": "not_started", "error_code": "queue_preflight_failed"}
            timed_out = str(exc) == "protocol_timeout"
            return {"outcome": "unknown",
                    "error_code": "queue_timeout" if timed_out else "queue_result_unknown"}
        finally:
            _close(session)
        after = self._goal(thread_id)
        if after is not None and after.goal_id == before.goal_id and after.status == GoalStatus.ACTIVE:
            return {"outcome": "accepted", "queue_id": None}
        return {"outcome": "unknown", "error_code": "queue_result_unknown"}

    def send(self, thread_id, prompt, *, launch_guard=None, client_id=None):
        """The channel (P5, where M2b passed): the goal set active, then `prompt` added to the
        conversation's queue - under `client_id` where core hands one (the marker-free
        continuation's P15), with the marker in the words otherwise, as always. What came of it is
        what came of the add: the queued message is the continuation, and the goal is set before
        it only so that it carries on after it. Never raises."""
        if (not ids.is_uuid(thread_id) or not isinstance(prompt, str) or not prompt
                or len(prompt) > MAX_PROMPT or "\0" in prompt
                or not (client_id is None or ids.is_uuid(client_id))):
            return {"outcome": "not_started", "error_code": "queue_preflight_failed"}
        params = {"threadId": thread_id, "input": [{"type": "text", "text": prompt}]}
        if client_id is not None:
            params["clientUserMessageId"] = client_id
        before = self._goal(thread_id)
        session, refused = self._opened(launch_guard)
        if refused is not None:
            return refused
        try:
            if before is not None and before.status == GoalStatus.USAGE_LIMITED:
                try:
                    session.call(SET, {"threadId": thread_id, "status": str(GoalStatus.ACTIVE)})
                except Exception:
                    pass                  # the queued turn still continues the conversation
            result = session.call(ADD, params)
        except SessionRefused:
            return {"outcome": "not_started", "error_code": "queue_preflight_failed"}
        except Exception as exc:
            timed_out = str(exc) == "protocol_timeout"
            return {"outcome": "unknown",
                    "error_code": "queue_timeout" if timed_out else "queue_result_unknown"}
        finally:
            _close(session)
        return {"outcome": "accepted", "queue_id": _queue_id(result)}

    # ------------------------------------------------------------------ the session
    def _opened(self, launch_guard):
        """(the session, None) once consent held and one was opened, or (None, what core is
        told): consent refused at the guard, or no session - nothing was asked of Codex."""
        session, opened = None, False
        try:
            with launch_guard if launch_guard is not None else nullcontext(True) as permitted:
                if permitted is not True:
                    return None, {"outcome": "not_started", "error_code": "queue_consent_refused"}
                session = self._session()
                session.__enter__()
                opened = True
        except Exception:
            if opened:
                _close(session)
            return None, {"outcome": "not_started", "error_code": "queue_spawn_failed"}
        return session, None

    def _session(self):
        if self._open is not None:
            return self._open()
        return Session(inuse.backend(self.paths), capability=CAPABILITY)


def make(paths) -> GoalContinuation:
    """The capability's factory (registry.CapabilityDef.make): its code for one installation."""
    return GoalContinuation(paths)
