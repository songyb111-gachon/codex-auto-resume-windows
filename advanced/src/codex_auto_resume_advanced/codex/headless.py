# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""One turn of a conversation nothing holds, run here on our own app server, every approval declined (v0.6.16-beta.4).

The standard edition waits for the Codex app to hold a conversation before anything is sent there (A11), and only
through `codex queue` (A2). A route of this module (`HeadlessRun`) is what core calls instead, at P16, for a record
whose conversation nothing holds while Codex is closed: core has made its one claim, its pre-send look and its launch
guard, and decided the words (core's engine/dispatch.py) - this starts the one turn they ask for, and nothing else.

`resume`, inside the guard core entered:

1. a session of our own, `codex app-server --stdio`, under the asking capability's own methods
   (protocol.CAPABILITY_METHODS) - headless_run's cannot compact or change a model;
2. thread/resume with no override at all: the model, sandbox, approvals and folder Codex saved for the thread apply;
3. those settings read from the answer as closed words, against an allow-list - a readOnly or workspaceWrite sandbox,
   approvals that go to the person (`user`), an approval policy that is a word, no permission profile or only Codex's
   built-in workspace or read-only one (PROFILES) -
   and anything else (full access, an outside sandbox, another reviewer, a word this does not know) refused before
   anything starts (Q4: `refused_settings`);
4. core's look - consent still given, the conversation still unheld and the app still closed - asked again: the lock
   our own server took at thread/resume counted as no other holder (core's pairing.own_server, by the pid and
   creation time of the spawn), any other holder still a no;
5. turn/start with core's words (or none, SILENT) under the client id core derived - or, in compact mode,
   thread/compact/start; a refusal Codex answered is "not started", no answer is "unknown" (A6);
6. "ran" (or "accepted" for a compaction) with the turn's id, and the open session handed to the follower. A
   fallback turn's model is stored as owed back before its turn/start, and put back here on every path that does
   not hand the session over.

The follower - one daemon thread, at most one run in the whole process - follows that one turn to its end and never
starts another: it answers every request Codex makes with that request's refusal (protocol.reply_to), interrupts the
turn at its cap (the person's Hours), at a person's Stop and at once when the Codex app starts (Q3, until a
measurement says what the app does then), puts back a model it changed (fallback mode), always unsubscribes and
closes the process (ended after four seconds only if it hangs). It writes nothing: the end it came to is one closed
word on an in-memory queue, which the capability's P8 tick takes and journals (engine/headless.py). The watcher
leaving interrupts and lets go first (`stop_all`, at exit).
"""
from __future__ import annotations

import atexit
from collections import deque
import threading
import time

from codex_auto_resume.domain import ids

from ..vocabulary import RunEnd
from .protocol import Session, SessionRefused

# The saved settings a headless turn may run under: an allow-list (Q4).
SANDBOXES = frozenset({"readOnly", "workspaceWrite"})
POLICIES = frozenset({"untrusted", "on-failure", "on-request", "never"})
REVIEWERS = frozenset({"user"})
# The permission profiles a headless turn may run under. 0.162's ActivePermissionProfile carries only an `id` - Codex's
# built-in `:workspace`, or a profile of the person's own (`[permissions.<id>]`) - and the `extends` of a profile of
# their own; M6B found one set (permission_profile_set) on an ordinary conversation saved workspaceWrite / on-request /
# user. Codex's built-in workspace and read-only profiles, extending nothing, grant no more than the sandbox word
# beside them says; a profile of the person's own may grant anything, so it is refused, as any other id or shape.
PROFILES = frozenset({":workspace", ":read-only"})
# How long an interrupted turn has to end, how long a compaction may take, how often the follower looks.
INTERRUPT_SECONDS = 15.0
COMPACT_SECONDS = 600.0
POLL_SECONDS = 0.5
# How often the follower asks whether the Codex app has started, in seconds.
APP_LOOK_SECONDS = 10.0
# Modes: one turn of words, a compaction, one turn on another model.
TURN, COMPACT, FALLBACK = "turn", "compact", "fallback"
# How the Codex app starts its engine on Windows, and so how a turn run here starts its own (M6B, 2026-10-16): without
# these the sandbox's setup helper asked for elevation and the turn's command never ran. Never anything that elevates.
HEADLESS_CONFIG = (("windows.sandbox", '"mxc"'), ("features.prefer_mxc", "true"))
# Whether Codex refused a turn with no input in this process (silent_continuation, M3B): from then on the capability
# answers DEFER, so the next attempt carries words, and it trips (REFUSED_BY_CODEX, runtime.moved).
EMPTY_REFUSED = False

PREFLIGHT = {"outcome": "not_started", "error_code": "queue_preflight_failed"}
SPAWN_FAILED = {"outcome": "not_started", "error_code": "queue_spawn_failed"}


def settings_allowed(resumed) -> bool:
    """Whether the settings a thread/resume answered are ones a headless turn may run under (the allow-list above):
    anything absent, unreadable or not on the list is no."""
    if not isinstance(resumed, dict):
        return False
    sandbox = resumed.get("sandbox")
    policy = resumed.get("approvalPolicy")
    return (isinstance(sandbox, dict) and sandbox.get("type") in SANDBOXES
            and isinstance(policy, str) and policy in POLICIES
            and resumed.get("approvalsReviewer") in REVIEWERS
            and _profile_allowed(resumed.get("activePermissionProfile")))


def _profile_allowed(profile) -> bool:
    """None (no profile reported), or one of Codex's built-in PROFILES extending nothing, with no other field."""
    if profile is None:
        return True
    return (isinstance(profile, dict) and set(profile) <= {"id", "extends"} and profile.get("id") in PROFILES
            and profile.get("extends") is None)


def _model(resumed):
    model = resumed.get("model") if isinstance(resumed, dict) else None
    return model if isinstance(model, str) and 0 < len(model) <= 128 else None


def _default_model(listed):
    """The model Codex marks its default in a model/list answer, or None."""
    data = listed.get("data") if isinstance(listed, dict) else None
    for entry in data if isinstance(data, list) else ():
        if isinstance(entry, dict) and entry.get("isDefault") is True:
            model = entry.get("model") or entry.get("id")
            return model if isinstance(model, str) and 0 < len(model) <= 128 else None
    return None


def _turn_id(started):
    turn = started.get("turn") if isinstance(started, dict) else None
    found = turn.get("id") if isinstance(turn, dict) else None
    return found if isinstance(found, str) and found else None


def _completed(events, thread, turn_id):
    """The status of the `turn/completed` among `events` for `thread`'s turn `turn_id` (any of its turns where None),
    or None - a closed word, never anything the turn carried."""
    for event in events:
        if not isinstance(event, dict) or event.get("method") != "turn/completed":
            continue
        params = event.get("params")
        turn = params.get("turn") if isinstance(params, dict) else None
        if (not isinstance(params, dict) or params.get("threadId") != thread or not isinstance(turn, dict)
                or (turn_id is not None and turn.get("id") != turn_id)):
            continue
        status = turn.get("status")
        return status if status in ("completed", "failed", "interrupted") else "other"
    return None


def _close(session):
    try:
        session.__exit__(None, None, None)
    except Exception:
        pass


class Follower:
    """The one run a process may have, followed to its end on a daemon thread. Every field it shares is under
    `lock`; `ends` holds what each run came to, for the P8 tick to take (`drain`)."""

    def __init__(self, clock=time.monotonic, poll=POLL_SECONDS):
        self.lock = threading.Lock()
        self.clock, self.poll = clock, poll
        self.ends = deque(maxlen=64)
        self._run = None

    # ---------------------------------------------------------------- what others ask
    def live(self):
        """What the live run is - {key, capability, thread_id, started_at, ends_by} - or None."""
        with self.lock:
            return dict(self._run["shown"]) if self._run is not None else None

    def stop(self, key=None, reason=RunEnd.INTERRUPTED) -> bool:
        """Ask the live run (only `key`'s, where given) to be interrupted: a person's Stop, the app starting, the
        watcher leaving. Whether one was asked."""
        with self.lock:
            run = self._run
            if run is None or (key is not None and run["shown"]["key"] != key):
                return False
            if run["stop"] is None:
                run["stop"] = RunEnd(reason)
            return True

    def told(self, key, capability, end, model_restored=None) -> None:
        """How a run ended, for the capability's P8 tick to take (`drain`): the follower's own end, or a fallback turn
        the route never handed over, whose model it put back itself (HeadlessRun.resume)."""
        with self.lock:
            self.ends.append({"key": key, "capability": capability, "end": str(end), "model_restored": model_restored})

    def drain(self, capability) -> list:
        """What every run of `capability` that ended came to since its last drain: [{key, capability, end,
        model_restored}] - another capability's left for its own tick."""
        with self.lock:
            taken = [end for end in self.ends if end["capability"] == capability]
            kept = [end for end in self.ends if end["capability"] != capability]
            self.ends.clear()
            self.ends.extend(kept)
        return taken

    # ---------------------------------------------------------------- the run
    def start(self, session, *, key, capability, thread_id, turn_id, seconds, mode, restore=None,
              app_running=None, wall=time.time) -> bool:
        """Follow `session`'s turn on a thread of its own; False where a run is live already (one at a time)."""
        with self.lock:
            if self._run is not None:
                return False
            now = wall()
            self._run = {"stop": None, "shown": {"key": key, "capability": capability, "thread_id": thread_id,
                                                 "started_at": now, "ends_by": now + seconds}}
        worker = threading.Thread(target=self._follow, daemon=True, name="car-headless",
                                  args=(session, key, capability, thread_id, turn_id, seconds, mode, restore,
                                        app_running))
        try:
            worker.start()
        except RuntimeError:
            with self.lock:
                self._run = None
            raise
        return True

    def _stopping(self):
        with self.lock:
            return self._run["stop"] if self._run is not None else None

    def _follow(self, session, key, capability, thread_id, turn_id, seconds, mode, restore, app_running):
        end, restored = RunEnd.LOST, None
        try:
            end = self._until_end(session, thread_id, turn_id, seconds, mode, app_running)
        except Exception:
            end = RunEnd.LOST
        finally:
            if restore is not None:
                restored = self._restore(session, thread_id, restore)
            try:
                session.call("thread/unsubscribe", {"threadId": thread_id})
            except Exception:
                pass                                   # the session's exit tries once more
            _close(session)
            with self.lock:
                self._run = None
            self.told(key, capability, end, restored)

    def _until_end(self, session, thread_id, turn_id, seconds, mode, app_running):
        deadline = self.clock() + seconds
        next_app = self.clock()
        while True:
            status = _completed(session.drain_events(), thread_id, turn_id)
            if status is not None:
                return RunEnd.COMPLETED if status == "completed" else (
                    RunEnd.FAILED if status == "failed" else RunEnd.INTERRUPTED)
            stop = self._stopping()
            if stop is None and app_running is not None and self.clock() >= next_app:
                next_app = self.clock() + APP_LOOK_SECONDS
                try:
                    if app_running():
                        stop = RunEnd.YIELDED
                except Exception:
                    pass
            if stop is None and self.clock() >= deadline:
                stop = RunEnd.CAPPED
            if stop is not None:
                return self._interrupt(session, thread_id, turn_id, stop, mode)
            time.sleep(self.poll)

    def _interrupt(self, session, thread_id, turn_id, why, mode):
        """The turn interrupted, and `INTERRUPT_SECONDS` for it to say it ended; `why` either way - or LOST where
        the interrupt could not be asked. A compaction has no turn of ours to interrupt: it is let go."""
        if mode == COMPACT or turn_id is None:
            return why
        try:
            session.call("turn/interrupt", {"threadId": thread_id, "turnId": turn_id})
        except Exception:
            return RunEnd.LOST
        deadline = self.clock() + INTERRUPT_SECONDS
        while self.clock() < deadline:
            if _completed(session.drain_events(), thread_id, turn_id) is not None:
                return why
            time.sleep(self.poll)
        return why

    @staticmethod
    def _restore(session, thread_id, model) -> bool:
        """The conversation's own model put back (fallback mode) and read back on a plain resume - MF's route 2, never
        a model given at thread/resume, which the thread keeps: whether the conversation is on its own model again."""
        try:
            session.call("thread/settings/update", {"threadId": thread_id, "model": model})
            resumed = session.call("thread/resume", {"threadId": thread_id, "excludeTurns": True})
        except Exception:
            return False
        return _model(resumed) == model


# The one follower of this process, and the watcher leaving stops what it follows first.
FOLLOWER = Follower()


def stop_all(follower=None, seconds=INTERRUPT_SECONDS + 5) -> None:
    """At exit: the live run interrupted and let go, waited for at most `seconds`."""
    follower = follower or FOLLOWER
    if not follower.stop(reason=RunEnd.INTERRUPTED):
        return
    deadline = time.monotonic() + seconds
    while follower.live() is not None and time.monotonic() < deadline:
        time.sleep(0.1)


atexit.register(stop_all)


class HeadlessRun:
    """The route core calls (P16): `resume`, once, inside core's launch guard. `takes_words` says core decides its
    words before the claim and hands them over (core's domain/plughands.Route).

    `session` opens the session (a factory of none, given the capability's id; None: a live one against the Codex
    the watcher drives - codex/inuse.py); `follower` is the process's one (FOLLOWER); `seconds` the cap of the
    turn; `mode` TURN, COMPACT or FALLBACK, with `model` the one a FALLBACK turn runs on; `app_running` the look
    at whether the Codex app has started (None: never asked); `key` the interruption the run is for; `owe` - a
    FALLBACK turn's - writes the conversation's own model down as owed back, given (thread_id, model, seconds), True
    once it is stored: asked before turn/start, and no turn starts where it is not (engine/fallback.py)."""
    takes_words = True

    def __init__(self, capability, *, key, session, follower=None, seconds=3600, mode=TURN, model=None,
                 app_running=None, owe=None):
        self.capability, self.key, self._open, self.owe = capability, key, session, owe
        self.follower = follower or FOLLOWER
        self.seconds, self.mode, self.model, self.app_running = seconds, mode, model, app_running
        # What the last resume came to before a turn started, for the capability's journal: refused_settings, or None.
        self.refused = None
        # v0.6.20 (the pair audit, V20-1): a FALLBACK route's conversation found on Codex's default model already -
        # nothing to fall back to - its thread id, for model_fallback to leave that conversation to the others.
        self.on_default = None

    def resume(self, thread_id, *, launch_guard=None, still_unloaded=None, words=None, client_id=None):
        """Run the one turn core asked for - see the module's steps. Never raises."""
        if not ids.is_uuid(thread_id) or self.follower.live() is not None:
            return dict(PREFLIGHT)
        if self.mode != COMPACT and (not isinstance(words, str) or len(words) > 8192
                                     or not (client_id is None or ids.is_client_id(client_id))):
            return dict(PREFLIGHT)
        try:
            from contextlib import nullcontext
            with launch_guard if launch_guard is not None else nullcontext(True) as permitted:
                if permitted is not True:
                    return {"outcome": "not_started", "error_code": "queue_consent_refused"}
            session = self._open(self.capability)
            session.__enter__()
        except Exception:
            return dict(SPAWN_FAILED)
        handed, owing, answered = False, None, None
        try:
            try:
                resumed = session.call("thread/resume", {"threadId": thread_id, "excludeTurns": True})
            except Exception:
                return dict(PREFLIGHT)               # nothing started: the session's exit lets the thread go
            if not settings_allowed(resumed):
                self.refused = RunEnd.REFUSED_SETTINGS
                return dict(PREFLIGHT)
            original = _model(resumed)
            if self.mode == FALLBACK:
                # Codex's own default (model/list's isDefault), only where the conversation is on another - read
                # here, never stored (Q5).
                try:
                    self.model = _default_model(session.call("model/list", {}))
                except Exception:
                    self.model = None
                if self.model is not None and self.model == original:
                    self.on_default = thread_id
                if self.model is None or original is None or self.model == original:
                    return dict(PREFLIGHT)
            if still_unloaded is not None and not _yes(still_unloaded):
                return dict(PREFLIGHT)
            if self.mode == FALLBACK:
                # The conversation's own model stored as owed back before anything can change it: a watcher stopped
                # mid-turn puts it back after a restart (engine/fallback.py). Not stored, nothing starts.
                if self.owe is not None and not _yes(lambda: self.owe(thread_id, original, self.seconds)):
                    return dict(PREFLIGHT)
                owing = original
            answered = self._start(session, thread_id, words, client_id)
            if answered.get("outcome") not in ("ran", "accepted"):
                return answered
            turn = answered.get("turn_id")
            handed = self.follower.start(
                session, key=self.key, capability=self.capability, thread_id=thread_id, turn_id=turn,
                seconds=COMPACT_SECONDS if self.mode == COMPACT else self.seconds, mode=self.mode,
                restore=original if self.mode == FALLBACK else None, app_running=self.app_running)
            if not handed:
                return {"outcome": "unknown", "error_code": "queue_result_unknown"}
            return answered
        except Exception:
            return {"outcome": "unknown", "error_code": "queue_result_unknown"}
        finally:
            if not handed:
                if owing is not None:
                    # A fallback turn/start asked and never handed over - refused, unanswered, a turn id not a turn's,
                    # or a run already live: the model put back here, on every one of those paths.
                    refused = isinstance(answered, dict) and answered.get("outcome") == "not_started"
                    self.follower.told(self.key, self.capability, RunEnd.FAILED if refused else RunEnd.LOST,
                                       Follower._restore(session, thread_id, owing))
                _close(session)

    def _start(self, session, thread_id, words, client_id):
        """The one request that changes Codex: turn/start, or thread/compact/start - Codex's refusal is not started,
        anything else that did not answer is unknown (A6)."""
        if self.mode == COMPACT:
            method, params = "thread/compact/start", {"threadId": thread_id}
        else:
            method = "turn/start"
            params = {"threadId": thread_id,
                      "input": [{"type": "text", "text": words}] if words else []}
            if client_id is not None:
                params["clientUserMessageId"] = client_id
            if self.mode == FALLBACK:
                params["model"] = self.model
        try:
            answer = session.call(method, params)
        except SessionRefused:
            return dict(PREFLIGHT)
        except Exception as exc:
            if getattr(exc, "method", None) == method:
                if method == "turn/start" and not words:
                    global EMPTY_REFUSED
                    EMPTY_REFUSED = True
                return {"outcome": "not_started", "error_code": "queue_preflight_failed",
                        "refused_by_codex": True}
            return {"outcome": "unknown",
                    "error_code": "queue_timeout" if str(exc) == "protocol_timeout" else "queue_result_unknown"}
        if self.mode == COMPACT:
            return {"outcome": "accepted", "queue_id": None, "turn_id": None}
        turn = _turn_id(answer)
        if turn is None or not ids.is_uuid(turn):
            return {"outcome": "unknown", "error_code": "queue_result_unknown"}
        return {"outcome": "ran", "turn_id": turn}


def _yes(look) -> bool:
    try:
        return look() is True
    except Exception:
        return False


def live_session(paths):
    """A factory of live sessions against the Codex the watcher drives, each restricted to the asking capability's
    methods (protocol.CAPABILITY_METHODS). Never reached by a test."""
    def factory(capability):
        from . import inuse
        return Session(inuse.backend(paths), capability=capability, config=HEADLESS_CONFIG)
    return factory
