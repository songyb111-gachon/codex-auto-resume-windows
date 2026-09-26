# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The measurement harness: what the owner runs by hand to find whether a capability can work.

Nine of this edition's capabilities depend on a fact only a live machine can give - that a
queued message reaches a notLoaded thread when it is opened, that a headless turn behaves when
its approvals are declined, that the WMI escape still leaves a process outside Codex's job. An
agent never learns these: it never touches the real install (the whole product turns on that
rule). So the owner runs `measure <id>` on a throwaway conversation, once per Codex version, and
each run writes one content-free record to docs/evidence/live/ (evidence.py). A capability whose
measurement has not passed for the Codex in force ships built but unavailable (decision C7).

Nothing here runs unless a person asks for it. A measurement opens a one-turn session
(codex/protocol.Session) restricted to the methods it declared, reads what it can, and records a
verdict and a content-free observation; the M-list that only a person can set up (a second
server running, an account signed out and back in) records what the harness could see and leaves
the verdict blocked, with a note, for the person to complete. `run` is driven through injected
factories, so the tests give it a fake session and a fake launcher and no test opens a real
Codex or starts a real process.
"""
from __future__ import annotations

import sys
import time

from codex_auto_resume import config
from codex_auto_resume.codex.errors import AdapterError
from codex_auto_resume.diagnostics import Redactor
from codex_auto_resume.domain.ids import is_uuid

from . import evidence
from .codex.protocol import Session, SessionRefused, methods_for
from .vocabulary import Measurement, NoteCode, Verdict

MEASUREMENTS = tuple(Measurement)


def _iso(now) -> str:
    """The moment as the record keeps it: an ISO-8601 minute in UTC, no finer, so nothing about
    when a person ran it beyond the day and minute is written."""
    return time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime(now))


class Context:
    """What one measurement is run with: a way to open its session, a launcher for the one that
    starts a process, the aliases for any id it records, and the versions the record carries.

    The factories are injected. In production `live` wires the real ones; a test wires fakes, so
    no test opens a real Codex or starts a real process.
    """
    def __init__(self, measurement, *, session_factory=None, launcher=None, backend=None,
                 versions=None, redactor=None, thread=None):
        self.measurement = Measurement(measurement)
        self._session_factory = session_factory
        self.launcher = launcher
        self.backend = backend
        self.versions = versions or {}
        self.redactor = redactor or Redactor()
        # An optional real throwaway conversation the owner pointed this measurement at. It is
        # validated as a Codex thread id and used in the calls the probe makes, so a measurement
        # can run against a real conversation instead of the placeholder. It is never written
        # into the record: the record holds only that one was given (`thread_given`), because a
        # conversation id is exactly the kind of content this whole edition keeps out of state.
        self.thread_given = bool(thread)
        self.probe_thread = thread if thread else _SAMPLE_THREAD

    def open(self):
        """The one-turn session for this measurement, restricted to the methods it declared. A
        measurement that declares none (MW works from the launcher) has no session to open."""
        if not methods_for(self.measurement) - {"initialize", "initialized"}:
            raise EvidenceUnavailable("this measurement opens no session")
        if self._session_factory is None:
            raise EvidenceUnavailable("no session was provided")
        return self._session_factory(self.measurement)

    def given(self, observed) -> dict:
        """The probe's observation, with whether a real thread was given added - a boolean, and
        never the id itself."""
        return dict(observed, thread_given=self.thread_given)


class EvidenceUnavailable(RuntimeError):
    """A measurement could not be reached to be measured - no session, no launcher, or the
    protocol was unavailable. It becomes a blocked verdict with a coded note, never a pass."""


# --------------------------------------------------------------------------- the probes
# Each probe reads what it can and returns (verdict, observed, note). Its observation is closed
# words, counts, booleans and aliases only (evidence.build refuses anything else). A probe that
# needs a person to set the world up first - a second server running, an account signed out -
# records what the harness saw and leaves the verdict blocked, saying what is left to do.
def _blocked(note, **observed):
    return Verdict.BLOCKED, observed, note


def _m1(ctx):
    """A notLoaded queue item is delivered on open. The harness sees the thread is notLoaded and
    a queue item is waiting; whether opening it delivers the item is what the person then does."""
    with ctx.open() as session:
        loaded = session.call("thread/loaded/list")
        queued = session.call("thread/queue/list", {"threadId": ctx.probe_thread})
    observed = {"loaded_listed": isinstance(loaded, dict),
                "queue_listed": isinstance(queued, dict)}
    return _blocked("open the notLoaded thread in the Desktop and confirm the queued item is "
                    "delivered, then set the verdict", **observed)


def _m2(ctx):
    """thread/goal/set reaches a Desktop-loaded goal."""
    with ctx.open() as session:
        before = session.call("thread/goal/get", {"threadId": ctx.probe_thread})
        session.call("thread/goal/set", {"threadId": ctx.probe_thread, "objective": None,
                                         "status": "active"})
        after = session.call("thread/goal/get", {"threadId": ctx.probe_thread})
    observed = {"goal_read": isinstance(before, dict), "goal_set": isinstance(after, dict)}
    return _blocked("confirm the Desktop continued the goal at its next idle, then set the "
                    "verdict", **observed)


def _m3(ctx):
    """An empty thread/queue/add is dispatched and correlatable."""
    with ctx.open() as session:
        added = session.call("thread/queue/add", {"threadId": ctx.probe_thread,
                                                  "clientUserMessageId": _SAMPLE_CLIENT_ID,
                                                  "input": []})
        listed = session.call("thread/queue/list", {"threadId": ctx.probe_thread})
    observed = {"queue_add_accepted": isinstance(added, dict),
                "correlatable": isinstance(listed, dict)}
    verdict = Verdict.PASS if all(observed.values()) else Verdict.FAIL
    note = None if verdict == Verdict.PASS else "the empty queue add was not accepted or not listed"
    return verdict, observed, note


def _m4(ctx):
    """Plugin Stop hooks run after a failed turn. The harness reads whether a Stop hook is
    declared; that it runs after a failed turn is what the person confirms."""
    with ctx.open() as session:
        hooks = session.call("hooks/list", {"cwds": []})
    observed = {"hooks_listed": isinstance(hooks, (dict, list))}
    return _blocked("cause a turn to fail and confirm the plugin Stop hook ran and the failed "
                    "row was persisted by then, then set the verdict", **observed)


def _m5(ctx):
    """TUI and IDE servers dispatch codex queue items. The two servers are the person's to
    start; the harness only confirms the queue is readable from here."""
    with ctx.open() as session:
        listed = session.call("thread/queue/list", {"threadId": ctx.probe_thread})
    observed = {"queue_listed": isinstance(listed, dict)}
    return _blocked("with a TUI server and an IDE server each holding a thread, confirm each "
                    "dispatches a codex queue item, then set the verdict", **observed)


def _m6(ctx):
    """A headless turn with declined approvals. The session declines every request Codex makes;
    the harness records how many it declined and how the turn ended."""
    with ctx.open() as session:
        session.call("thread/resume", {"threadId": ctx.probe_thread})
        session.call("turn/start", {"threadId": ctx.probe_thread})
        time.sleep(0)                      # the reader thread collects notifications as they come
        events = session.drain_events()
        session.call("turn/interrupt", {"threadId": ctx.probe_thread})
        declined = len(session.declined)
    status = _turn_status(events)
    observed = {"approvals_declined": declined}
    if status is not None:
        observed["turn_status"] = status
    return _blocked("confirm the headless turn behaved as expected with its approvals declined, "
                    "then set the verdict", **observed)


def _m7(ctx):
    """Queued '/compact' text stays plain text (it is not run as a command)."""
    with ctx.open() as session:
        added = session.call("thread/queue/add", {"threadId": ctx.probe_thread,
                                                  "clientUserMessageId": _SAMPLE_CLIENT_ID,
                                                  "input": [{"type": "text", "text": "/compact"}]})
    observed = {"queue_add_accepted": isinstance(added, dict)}
    return _blocked("confirm the queued '/compact' was delivered as plain text, not run as a "
                    "command, then set the verdict", **observed)


def _mh(ctx):
    """The Desktop runs on a second CODEX_HOME. The harness confirms it can reach the second
    home's server; that the Desktop uses it is the person's to arrange."""
    with ctx.open() as session:
        loaded = session.call("thread/loaded/list")
    observed = {"second_home_reached": isinstance(loaded, dict)}
    return _blocked("point the Desktop at a second CODEX_HOME and confirm it runs there, then "
                    "set the verdict", **observed)


def _ma(ctx):
    """The running app picks up an account logout+login. The harness reads the account state;
    the logout and login are the person's to perform in the app."""
    with ctx.open() as session:
        account = session.call("account/read", {})
    observed = {"account_read": isinstance(account, dict)}
    return _blocked("sign out and back in in the app, then confirm the running app picked it up "
                    "and set the verdict", **observed)


def _mw(ctx):
    """Re-proof of the WMI escape, with the heartbeat's job words. The launcher starts a watcher
    outside Codex's job through WMI and hands back the job words its heartbeat recorded."""
    if ctx.launcher is None:
        return _blocked("wire the WMI launcher and run this from the source tree", wmi_started=False)
    facts = ctx.launcher()
    if not isinstance(facts, dict):
        return _blocked("the launcher reported nothing", wmi_started=False)
    observed = {"wmi_started": bool(facts.get("started")),
                "in_job": bool(facts.get("in_job")),
                "kill_on_close": bool(facts.get("kill_on_close")),
                "survived_codex_close": bool(facts.get("survived"))}
    escaped = observed["wmi_started"] and not observed["in_job"] and observed["survived_codex_close"]
    if escaped:
        return Verdict.PASS, observed, None
    return _blocked("the WMI-started watcher did not leave Codex's job or did not survive its "
                    "close; re-measure before offering start-with-Codex", **observed)


PROBES = {
    Measurement.M1: _m1, Measurement.M2: _m2, Measurement.M3: _m3, Measurement.M4: _m4,
    Measurement.M5: _m5, Measurement.M6: _m6, Measurement.M7: _m7, Measurement.MH: _mh,
    Measurement.MA: _ma, Measurement.MW: _mw,
}

# A conversation and a message id of no one's: the shape a call takes, never a real id. A probe
# that reaches a live Codex is run by the owner against a throwaway conversation whose id they
# put here; on their machine this constant is what a call carries when they have not.
_SAMPLE_THREAD = "00000000-0000-7000-8000-000000000000"
_SAMPLE_CLIENT_ID = "00000000-0000-7000-8000-000000000001"


def _turn_status(events) -> str | None:
    """The turn status the notifications reported, if any, in the engine's own word - never any
    text a turn carried."""
    from codex_auto_resume.codex.values import _turn_status as core_status
    for event in reversed(events):
        if isinstance(event, dict) and event.get("method") in ("turn/completed", "turn/failed",
                                                                "thread/status/changed"):
            params = event.get("params")
            status = params.get("status") if isinstance(params, dict) else None
            word = core_status(status) if isinstance(status, str) else None
            if word is not None:
                return word
    return None


def probe(ctx) -> tuple:
    """Run one measurement's probe, turning a protocol that could not be reached into a blocked
    verdict with a coded note rather than an exception. Whether the owner pointed it at a real
    conversation is added to the observation here, as a boolean, so every probe records it the
    same way and none has to carry the thread through."""
    try:
        verdict, observed, note = PROBES[ctx.measurement](ctx)
    except (EvidenceUnavailable, SessionRefused, AdapterError) as exc:
        return Verdict.BLOCKED, {"thread_given": ctx.thread_given}, "not reached: %s" % type(exc).__name__
    return verdict, ctx.given(observed), note


def run(measurement, *, session_factory=None, launcher=None, backend=None, versions=None,
        clock=time.time, directory=None, thread=None) -> dict:
    """Run one measurement and write its record. Returns a small summary of what was recorded.

    `versions` is the build, Codex and Windows the record belongs to; when it is not given they
    are read here (the product's manifest, the backend's engine version, this Windows). Every
    external effect is a factory the caller passes, so a test drives this with fakes.

    `thread` is an optional real throwaway conversation the owner points the measurement at. It
    is validated as a Codex thread id and used in the calls the probe makes; it is never written
    into the record, which keeps only whether one was given.

    A record that cannot say which Codex it measured is not written, and nothing is run for it:
    a measurement decides, per Codex version, whether a capability ships (C7), and "unknown"
    would decide it for every version at once.
    """
    measurement = Measurement(measurement)
    if thread is not None and not is_uuid(thread):
        raise EvidenceUnavailable("the conversation id is not a Codex thread id")
    versions = dict(versions or _versions(backend))
    if versions.get("codex_version") in (None, "", "unknown"):
        raise EvidenceUnavailable("the Codex version this would measure could not be read")
    ctx = Context(measurement, session_factory=session_factory, launcher=launcher,
                  backend=backend, versions=versions, thread=thread)
    verdict, observed, note = probe(ctx)
    record = evidence.build(measurement, verdict, observed,
                            product_version=versions.get("product_version", "0.0.0"),
                            codex_version=versions.get("codex_version", "unknown"),
                            windows_build=versions.get("windows_build", "10.0.0"),
                            recorded_at=_iso(clock()), note=note)
    written = evidence.write(record, directory=directory)
    return {"measurement": str(measurement), "verdict": str(verdict),
            "recorded": str(written), "observed": dict(observed)}


def _versions(backend) -> dict:
    """The build, Codex and Windows a record belongs to, read here when the caller gave none."""
    codex_version = "unknown"
    try:
        if backend is not None and backend.engine_version:
            codex_version = str(backend.engine_version)
    except Exception:
        pass
    # The build Windows reports to this process, as diagnostics reads it: platform.version() would
    # ask WMI and, if that failed, run `cmd /c ver` - a program started to answer a question this
    # process already knows (tests/test_no_console_windows.py).
    getter = getattr(sys, "getwindowsversion", None)
    build = None
    if getter is not None:
        running = getter()
        build = "%d.%d.%d" % (running.major, running.minor, running.build)
    return {"product_version": config.version(), "codex_version": codex_version,
            "windows_build": build or "10.0.0"}


def live_backend():
    """The installed Codex, found as core finds it and checked, so its `engine_version` is the
    version a record says it measured."""
    from codex_auto_resume.codex.transport import Backend
    exe = config.discover_codex_exe(None, lambda path: Backend(config.codex_home(), path)._compatible())
    backend = Backend(config.codex_home(), exe)
    backend._compatible()
    return backend


def live_session_factory(paths, backend=None):
    """A factory that opens a real one-turn session against the installed Codex, restricted to a
    measurement's own methods. Wired by the bridge; never reached by a test.

    Its correctness against a live engine is what the owner proves by running the measurements -
    the alpha exists for that - so it is thin and does the discovery core already does. `backend`
    is the one the run's record reads its Codex version from, so the session and the record are
    of the same Codex."""
    def factory(measurement):
        return Session(backend if backend is not None else live_backend(), measurement)

    return factory


def live_launcher(paths):
    """The real MW launcher: the WMI job-escape chain (codex/wmi_escape.py), wired for the owner's
    own run. It starts a helper inside a kill-on-close job with no breakaway - the shape Codex
    gives its MCP servers - has it start a heartbeat through WMI that lands outside the job, closes
    the job, and reports whether the heartbeat survived and stood outside a job. Every process it
    starts is windowless (the console rules). A test wires a fake instead and this is never
    reached."""
    from .codex import wmi_escape

    def launcher():
        return wmi_escape.probe(paths)

    return launcher


def complete(measurement, verdict, note, *, backend=None, versions=None, clock=time.time,
             directory=None) -> dict:
    """Append a person's completion to the blocked record of `measurement` (measure-verdict).

    The completion is a pass or a fail and one closed note code (vocabulary.NoteCode), added to
    the newest blocked record for this same Codex version and refused when there is none. The
    Codex version is read the same way `run` reads it, so a completion and the record it completes
    are of the same Codex; a run that cannot say which Codex it is on completes nothing.
    """
    measurement = Measurement(measurement)
    verdict = Verdict(verdict)
    note = NoteCode(note)
    versions = dict(versions or _versions(backend))
    codex_version = versions.get("codex_version")
    if codex_version in (None, "", "unknown"):
        raise EvidenceUnavailable("the Codex version this would complete could not be read")
    written = evidence.complete(measurement, verdict, note, codex_version=codex_version,
                                recorded_at=_iso(clock()), directory=directory)
    return {"measurement": str(measurement), "verdict": str(verdict), "note": str(note),
            "recorded": str(written)}
