# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The measurement harness: what the owner runs by hand to find whether a capability can work.

Several of this edition's capabilities depend on a fact only a live machine can give - that a
queued message reaches a notLoaded thread when it is opened, that a headless turn behaves when
its approvals are declined, that the WMI escape still leaves a process outside Codex's job, that a
goal set active beside a queued turn carries on while the app holds the conversation (M2b). An
agent never learns these: it never touches the real install (the whole product turns on that
rule). So the owner runs `measure <id>` on a throwaway conversation, once per Codex version, and
each run writes one content-free record to docs/evidence/live/ (evidence.py), and what a release
carries of them is measured.py. A capability whose measurement failed, or has not passed for the
Codex in force, says so as a warning in its statement, which the person confirms by turning it on
(arming.warnings_for; the owner's rule of 2026-09-26, which replaced decision C7).

Nothing here runs unless a person asks for it. A measurement opens a one-turn session
(codex/protocol.Session) restricted to the methods it declared, reads what it can, and records a
verdict and a content-free observation; the M-list that only a person can set up (a second
server running, an account signed out and back in) records what the harness could see and leaves
the verdict blocked, with a note, for the person to complete. `run` is driven through injected
factories, so the tests give it a fake session and a fake launcher and no test opens a real
Codex or starts a real process.
"""
from __future__ import annotations

from pathlib import Path
import sys
import time
import uuid

from codex_auto_resume import config
from codex_auto_resume.codex.errors import AdapterError
from codex_auto_resume.diagnostics import Redactor
from codex_auto_resume.domain.ids import is_uuid

from . import evidence
from .codex import credits, inuse
from .codex.protocol import Session, SessionRefused, methods_for
from .vocabulary import Measurement, NoteCode, ObservedWord, PlanWord, SpendOutcome, Verdict

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
                 versions=None, redactor=None, thread=None, may_spend=False, cli=None, ipc=None, hands=None):
        self.measurement = Measurement(measurement)
        # v0.6.19: the run's other hands, each a callable by name - `open_link` (a conversation's link opened),
        # `power` (the power settings read), `wake_after` (a wake timer set and waited for) and `scratch_cli` (the
        # engine run on a scratch Codex home). Production wires live_hands; a test wires fakes; one not given does
        # nothing, so no test reaches the real one.
        self._hands = dict(hands or {})
        # v0.6.16-beta.3, the read-only probes: `cli` runs the engine's own CLI help (a callable given a
        # tuple of arguments, answering its stdout text or None), and `ipc` looks at the Desktop's IPC pipe
        # (a callable answering a dict of booleans). Both are seams: production wires the real ones
        # (live_cli, live_ipc), and a test wires fakes, so no test runs the CLI or touches the pipe.
        self._cli = cli
        self._ipc = ipc
        # The person's second, explicit yes that MR may spend one real reset credit (v0.6.14): False
        # unless the Dashboard's request said so in as many words (surfaces.measure), and nothing
        # else is ever spent by a measurement.
        self.may_spend = may_spend is True
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
        # v0.6.17: MQP's two to four throwaway conversations, named comma-separated; every other measurement one.
        self.probe_threads = tuple(thread.split(",")) if thread else (_SAMPLE_THREAD,)
        self.probe_thread = self.probe_threads[0]

    def open(self):
        """The one-turn session for this measurement, restricted to the methods it declared. A
        measurement that declares none (MW works from the launcher) has no session to open."""
        if not methods_for(self.measurement) - {"initialize", "initialized"}:
            raise EvidenceUnavailable("this measurement opens no session")
        if self._session_factory is None:
            raise EvidenceUnavailable("no session was provided")
        return self._session_factory(self.measurement)

    def open_scratch(self, home):
        """MB's session (v0.6.16-beta.4): one opened on the Codex home `home` the harness made, never the person's -
        only through a factory that takes one (its `home` argument); any other is refused, so MB never writes a
        configuration it did not make."""
        import inspect
        if self._session_factory is None:
            raise EvidenceUnavailable("no session was provided")
        try:
            takes = "home" in inspect.signature(self._session_factory).parameters
        except (TypeError, ValueError):
            takes = False
        if not takes:
            raise EvidenceUnavailable("this session cannot be opened on a scratch Codex home")
        return self._session_factory(self.measurement, home=home)

    def given(self, observed) -> dict:
        """The probe's observation, with whether a real thread was given added - a boolean, and
        never the id itself."""
        return dict(observed, thread_given=self.thread_given)

    def cli_help(self, arguments) -> str | None:
        """The stdout of the engine's own CLI run with `arguments` (v0.6.16-beta.3, MAWS/MCLOUD), or None
        where there is no runner, the command could not be run, or it exited non-zero. Read-only: a help
        text, never a turn. The text is read for whether a word is in it and never recorded."""
        if self._cli is None:
            return None
        try:
            found = self._cli(tuple(arguments))
        except Exception:
            return None
        return found if isinstance(found, str) else None

    def _hand(self, name, *arguments):
        hand = self._hands.get(name)
        if not callable(hand):
            return None
        try:
            return hand(*arguments)
        except Exception:
            return None

    def open_link(self, thread) -> bool:
        """Whether the conversation's link was handed to Windows (MOPEN)."""
        return self._hand("open_link", thread) is True

    def power_look(self) -> dict:
        """The power settings read (MWAKE): a dict, empty where there is no hand or it failed."""
        found = self._hand("power")
        return found if isinstance(found, dict) else {}

    def wake_after(self, seconds, bound) -> dict:
        """A wake timer set `seconds` on and waited for at most `bound` seconds (MWAKE): what came of it, a dict."""
        found = self._hand("wake_after", seconds, bound)
        return found if isinstance(found, dict) else {}

    def scratch_cli(self, home, arguments) -> str | None:
        """The engine's stdout, run with `arguments` on the scratch Codex home `home` (MTOK, MHK), or None."""
        found = self._hand("scratch_cli", home, tuple(arguments))
        return found if isinstance(found, str) else None

    def stop_hook(self) -> dict:
        """What this installation's Stop hook declaration is (M4B, v0.6.20): {"declared": whether one of ours stands in
        our plugin copies, "commands": the commands one of ours runs}, or {} where there is no hand."""
        found = self._hand("stop_hook")
        return found if isinstance(found, dict) else {}

    def ipc_look(self) -> dict:
        """What a read-only look at the Desktop's own IPC pipe found (v0.6.16-beta.3, MIPC): a dict of
        booleans, or empty where there is no seam or the look raised. Nothing is ever written to the pipe."""
        if self._ipc is None:
            return {}
        try:
            found = self._ipc()
        except Exception:
            return {}
        return found if isinstance(found, dict) else {}


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


def _m2b(ctx):
    """A goal set active and a turn queued while the Desktop holds the conversation: does the turn
    run, and does the goal stay active and carry on after it? (the owner, 2026-09-28)

    M2 found a goal set from another app server is not seen while the app holds the conversation.
    The goal continuation therefore sets a goal only where the app does not hold it - and on one the
    app holds only if this passes. The harness does what the capability would do there: it reads
    the goal (its status alone - never its words, which no record holds), sets that existing goal
    active - never creating one - adds one short turn to the conversation's queue, follows the queue
    for up to _M2B_QUEUE_SECONDS to see the Desktop take the item, and reads the goal's status again.
    That the turn ran, and that the goal stayed active and carried on after it, is what the person
    watching confirms.

    How the owner runs it, on a throwaway conversation only: give it a goal in the Codex app and
    let it pause (a usage limit, or pause it by hand), keep it open in the Desktop, then run
    `measure m2b <thread-uuid>` from the long-lived bridge; watch the conversation, and record what
    was seen with `measure-verdict m2b pass as_expected` - or `fail not_as_expected` where the turn
    did not run, `fail partial` where it ran and the goal did not carry on after it."""
    with ctx.open() as session:
        before = _goal_status(session.call("thread/goal/get", {"threadId": ctx.probe_thread}))
        if before is None:
            return _blocked("give the throwaway conversation a goal, pause it, keep the conversation "
                            "open in the Desktop, then run m2b again", goal_found=False)
        session.call("thread/goal/set", {"threadId": ctx.probe_thread, "status": "active"})
        set_active = _goal_status(session.call("thread/goal/get", {"threadId": ctx.probe_thread}))
        added = session.call("thread/queue/add", {"threadId": ctx.probe_thread,
                                                  "clientUserMessageId": _SAMPLE_M2B_CLIENT_ID,
                                                  "input": [{"type": "text", "text": _M2B_PROMPT}]})
        taken = _await_taken(session, ctx.probe_thread, _SAMPLE_M2B_CLIENT_ID, _M2B_QUEUE_SECONDS)
        after = _goal_status(session.call("thread/goal/get", {"threadId": ctx.probe_thread}))
    observed = {"goal_found": True, "goal_was_active": before == "active",
                "goal_set_active": set_active == "active",
                "queue_add_accepted": isinstance(added, dict), "queued_turn_taken": taken,
                "goal_active_after": after == "active"}
    return _blocked("watch the conversation: confirm the queued turn ran and the goal stayed active "
                    "and carried on after it, then set the verdict", **observed)


# M2b's turn: one short, harmless message. What the turn answers is never read.
_M2B_PROMPT = "Reply with the single word: ok."
_M2B_QUEUE_SECONDS = 60.0        # how long the harness follows the queue for the Desktop to take it
_M2B_POLL_SECONDS = 1.0


def _goal_status(result):
    """The status a thread/goal/get answered, as the protocol words it - or None for no goal. Only
    the status is looked at; the goal's objective is in the answer and is never read."""
    goal = result.get("goal") if isinstance(result, dict) else None
    status = goal.get("status") if isinstance(goal, dict) else None
    return status if isinstance(status, str) else None


def _await_taken(session, thread, client_id, seconds) -> bool:
    """Whether the queued item under `client_id` left the conversation's queue within `seconds` -
    the Desktop took it to run. False when it is still there, or the queue could not be read."""
    deadline = time.monotonic() + seconds
    while True:
        try:
            listed = session.call("thread/queue/list", {"threadId": thread})
        except AdapterError:
            return False
        items = listed.get("data") if isinstance(listed, dict) else None
        if isinstance(items, list) and not any(
                isinstance(item, dict) and item.get("clientUserMessageId") == client_id for item in items):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(_M2B_POLL_SECONDS)


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
    """A headless turn with declined approvals. The thread is resumed without its history, one
    turn is started that asks for a harmless command under the strictest approval policy and a
    read-only sandbox, and the harness follows it until Codex says it completed - declining, in
    the session's reader, every approval it asks for with that request's own refusal - or until
    the bound, when it interrupts the turn itself. It records how many it declined, the turn's
    closed status word, and whether the turn ended by itself; whether any window or prompt
    appeared is what the person watching confirms."""
    with ctx.open() as session:
        session.call("thread/resume", {"threadId": ctx.probe_thread, "excludeTurns": True})
        started = session.call("turn/start", {
            "threadId": ctx.probe_thread,
            "input": [{"type": "text", "text": _M6_PROMPT}],
            "approvalPolicy": "untrusted",
            # Approvals come to this client, not to an automatic reviewer that might grant them.
            "approvalsReviewer": "user",
            "sandboxPolicy": {"type": "readOnly", "networkAccess": False},
        })
        turn = started.get("turn") if isinstance(started, dict) else None
        turn_id = turn.get("id") if isinstance(turn, dict) and isinstance(turn.get("id"), str) else None
        status = _await_turn(session, ctx.probe_thread, turn_id, _M6_TURN_SECONDS)
        ended = status is not None
        if not ended and turn_id is not None:
            # It did not end within the bound: stop it, and read how it ended if it says so.
            try:
                session.call("turn/interrupt", {"threadId": ctx.probe_thread, "turnId": turn_id})
                status = _await_turn(session, ctx.probe_thread, turn_id, _M6_INTERRUPT_SECONDS)
            except AdapterError:
                pass
        try:
            session.call("thread/unsubscribe", {"threadId": ctx.probe_thread})
            unsubscribed = True
        except AdapterError:
            unsubscribed = False              # the session's exit tries once more
        declined = session.declined_count()
    observed = {"approvals_declined": declined, "turn_ended_by_itself": ended,
                "unsubscribed": unsubscribed}
    if status is not None:
        observed["turn_status"] = status
    return _blocked("confirm no window or prompt appeared and the headless turn behaved as "
                    "expected with its approvals declined, then set the verdict", **observed)


# M6's turn: one harmless command, so a turn under the "untrusted" policy has something to ask
# approval for. What it prints is never read: the harness follows only the turn's status.
_M6_PROMPT = ("Run the harmless command `whoami` and report what it prints. If running it is "
              "not approved, say so and stop.")
_M6_TURN_SECONDS = 180.0         # how long the turn may take before the harness interrupts it
_M6_INTERRUPT_SECONDS = 15.0     # how long an interrupted turn has to say how it ended
_M6_POLL_SECONDS = 0.25


def _await_turn(session, thread, turn_id, seconds, seen=None):
    """Follow the session's notifications until the turn completes or `seconds` pass. Returns
    the turn's closed status word, or None when it did not say it ended. `seen` (v0.6.16-beta.4), a
    list, is given every notification drained on the way, for a probe that reads an item's kind."""
    deadline = time.monotonic() + seconds
    while True:
        events = session.drain_events()
        if seen is not None:
            seen.extend(events)
        status = _completed_status(events, thread, turn_id)
        if status is not None:
            return status
        if time.monotonic() >= deadline:
            return None
        time.sleep(_M6_POLL_SECONDS)


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


def _mq(ctx):
    """Several conversations at once (parallel_dispatch): the owner names two to four throwaway conversations the app
    holds, and core's backend sends one short message to each at once; that each receipt is matched and each marker is
    in its own conversation's history once, and nowhere else, is the person's to confirm."""
    with ctx.open() as session:
        loaded = session.call("thread/loaded/list")
    observed = {"loaded_listed": isinstance(loaded, dict)}
    return _blocked("send one short message to each of two to four throwaway conversations at once, confirm each "
                    "receipt is matched and each marker is in its own history once, then set the verdict", **observed)


def _me(ctx):
    """An empty reply (empty_response): the owner names a conversation whose last turn Codex ended with no reply, when
    Codex produces one; whether that turn's items are only the person's message and reasoning, and whether a final
    agent item is recorded, are read from the history of the Codex home the backend drives (codex/turns.py) - booleans and a closed word, never a word of
    the turn's. That this is a turn with no reply is the person's to say."""
    from .codex import turns
    from .engine.emptyreply import EMPTY_KINDS
    home = getattr(ctx.backend, "codex_home", None)
    if not ctx.thread_given or home is None:
        return _blocked("name a conversation whose last turn ended with no reply", history_read=False)
    try:
        found = turns.Turns(home).latest(ctx.probe_thread)
    except Exception:
        return _blocked("the turn history could not be read", history_read=False)
    observed = {"history_read": True, "turn_found": found is not None}
    if found is not None:
        observed.update(completed=found.status == "completed", final_agent=found.final_agent,
                        empty_kinds_only=set(found.kinds) <= EMPTY_KINDS)
    return _blocked("confirm the turn ended with no reply, then set the verdict", **observed)


def _ms(ctx):
    """A subagent's stop told to its parent (subagent_parent): the owner names a throwaway parent whose subagent failed;
    whether a spawn edge is there and the subagent's latest turn can be told as one of the closed kinds are read from
    the databases of the Codex home the backend drives (codex/lineage.py) - booleans and a closed word, never an id."""
    from .codex import lineage
    from .engine.subagent import kind_of
    home = getattr(ctx.backend, "codex_home", None)
    if not ctx.thread_given or home is None:
        return _blocked("name a throwaway parent whose subagent failed", edges_read=False)
    try:
        children = lineage.Lineage(home).children(ctx.probe_thread)
    except Exception:
        return _blocked("the spawn edges could not be read", edges_read=False)
    kinds = [kind_of(child) for child in children]
    observed = {"edges_read": True, "edge_present": bool(children),
                "child_classified": any(kind is not None for kind in kinds)}
    if any(kind is not None for kind in kinds):
        observed["child_kind"] = next(kind for kind in kinds if kind is not None)
    return _blocked("confirm the parent was told which subagent stopped, then set the verdict", **observed)


def _mk(ctx):
    """A plan's steps (keep_going): the owner names a throwaway conversation with a plan; whether its newest plan item
    is found and how many of its steps read as each status are read from the history of the Codex home the backend
    drives (codex/turns.plan_statuses) - counts of closed words, never a step's words."""
    from .codex import turns
    home = getattr(ctx.backend, "codex_home", None)
    if not ctx.thread_given or home is None:
        return _blocked("name a throwaway conversation with a plan", plan_read=False)
    try:
        statuses = turns.Turns(home).plan_statuses(ctx.probe_thread)
    except Exception:
        return _blocked("the plan's steps could not be read", plan_read=False)
    observed = {"plan_read": True, "plan_found": statuses is not None}
    for word in sorted(turns.STEP_STATUSES | {turns.UNKNOWN}):
        observed["steps_" + word] = sum(status == word for status in statuses or ())
    return _blocked("confirm the counts match the plan Codex shows, then set the verdict", **observed)


def _mt(ctx):
    """A message queued while a turn runs (prompt_queue's after_turn): the owner names a throwaway conversation with a
    turn running, and core's backend queues one short message there; that it was delivered once, after that turn
    ended, is the person's to confirm."""
    with ctx.open() as session:
        loaded = session.call("thread/loaded/list")
    observed = {"loaded_listed": isinstance(loaded, dict)}
    return _blocked("queue one short message while a turn runs in a throwaway conversation, confirm it was delivered "
                    "once after that turn ended, then set the verdict", **observed)


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
                "job_kills_on_close": bool(facts.get("job_kills_on_close")),
                "kill_on_close": bool(facts.get("kill_on_close")),
                "survived_codex_close": bool(facts.get("survived"))}
    # What decides it is whether anything can still end the watcher, not whether Windows keeps it
    # in some job: a process WMI starts sits in a large job of Windows' own, with BREAKAWAY_OK and
    # SILENT_BREAKAWAY_OK and no KILL_ON_JOB_CLOSE (measured 2026-09-26 on Windows 11 26200), and
    # the first version of this asked for no job at all and left a working escape blocked. So: it
    # started, the job built in Codex's shape did end its own member (the shape held), the
    # heartbeat outlived that, and the job it is in now would not end it when it closes.
    escaped = (observed["wmi_started"] and observed["kill_on_close"] and observed["survived_codex_close"]
               and not observed["job_kills_on_close"])
    if escaped:
        return Verdict.PASS, observed, None
    return _blocked("the WMI-started watcher did not leave Codex's job, sits in a job that would "
                    "end it, or did not survive; re-measure before offering start-with-Codex", **observed)


def _mp1(ctx):
    """The side panel's New tab lists the settings panel and opens it (v0.6.14). The harness reads
    whether the engine kept what the app builds the entry from - the panel tool's template and its
    `{"type": "thread"}` entrypoint - in the Codex home's MCP listing; that the New tab shows it and
    opens it is what the person then confirms.

    One read, `mcpServerStatus/list`, and nothing else: no tool is called, no resource read. It asks
    first for this product's server by the name the plugin gives it (`_MP1_SERVER`), so only that
    server is started; where Codex lists it under another name, it lists the home's servers - tools
    only, a few at a time, so no page outgrows the session's one-megabyte line - and starts each of
    them, as the app does when it starts. Starting this product's installed server runs its own
    start-with-Codex step: a line in the installation's codex-start log, and where Start with Codex
    is on and no watcher runs, the watcher started. Run it with the watcher running."""
    with ctx.open() as session:
        try:
            servers = _mcp_servers(session, {"serverName": _MP1_SERVER, "detail": "full"}, pages=1)
        except AdapterError as exc:
            if not hasattr(exc, "method"):
                raise
            servers = []                              # Codex would not look it up by that name
        tool = _settings_tool(servers)
        named = tool is not None
        if not named:
            servers = _mcp_servers(session, {"detail": "toolsAndAuthOnly", "limit": _MP1_PAGE},
                                   pages=_MP1_PAGES)
            tool = _settings_tool(servers)
    meta = tool.get("_meta") if isinstance(tool, dict) else None
    meta = meta if isinstance(meta, dict) else {}
    ui = meta.get("openai/ui") if isinstance(meta.get("openai/ui"), dict) else {}
    entrypoints = ui.get("entrypoints") if isinstance(ui.get("entrypoints"), list) else []
    from codex_auto_resume.mcp.tools import SETTINGS_UI
    observed = {"servers": len(servers), "named_lookup": named, "server_listed": tool is not None,
                "template_kept": meta.get("openai/outputTemplate") == SETTINGS_UI,
                "entrypoint_kept": _THREAD_ENTRYPOINT in entrypoints}
    if not observed["server_listed"]:
        return _blocked("Codex lists no server with the settings panel's tool: is the plugin installed "
                        "and enabled in this Codex home? Then run mp1 again", **observed)
    if observed["template_kept"] and not observed["entrypoint_kept"]:
        return Verdict.FAIL, observed, "the engine keeps the panel's template and drops its side-panel entrypoint"
    if not observed["template_kept"]:
        return _blocked("the listing carries no template for the panel's tool, so the harness cannot "
                        "tell whether the engine keeps the entrypoint; confirm in the app as below, "
                        "then set the verdict", **observed)
    return _blocked("open a throwaway conversation's right side panel, New tab, More tools...: "
                    "confirm Open Auto Resume settings is under Plugins and MCPs and opens the panel "
                    "with the state the Dashboard shows, then set the verdict", **observed)


def _mcp_servers(session, params, *, pages) -> list:
    """The servers `mcpServerStatus/list` answers with `params`, following its cursor for at most
    `pages` pages. Only what each server is is kept here, for `_settings_tool`; nothing of it is
    recorded but a count and what that tool carries."""
    servers, cursor = [], None
    for _page in range(pages):
        asked = dict(params, cursor=cursor) if cursor is not None else dict(params)
        answer = session.call("mcpServerStatus/list", asked)
        data = answer.get("data") if isinstance(answer, dict) else None
        servers += [server for server in (data if isinstance(data, list) else []) if isinstance(server, dict)]
        cursor = answer.get("nextCursor") if isinstance(answer, dict) else None
        if not isinstance(cursor, str) or not cursor:
            break
    return servers


def _settings_tool(servers):
    """The settings panel's tool, as the listing carries it: `open_settings` with this product's
    template where some server has one, else the first `open_settings` listed, else None. The
    listing gives a server's tools by name (McpServerStatus.tools); a list is read as well."""
    from codex_auto_resume.mcp.tools import SETTINGS_UI
    found = []
    for server in servers:
        tools = server.get("tools")
        tools = tools.values() if isinstance(tools, dict) else tools if isinstance(tools, list) else ()
        found += [tool for tool in tools if isinstance(tool, dict) and tool.get("name") == "open_settings"]
    for tool in found:
        meta = tool.get("_meta")
        if isinstance(meta, dict) and meta.get("openai/outputTemplate") == SETTINGS_UI:
            return tool
    return found[0] if found else None


def _mp2(_ctx):
    """Open beside the chat moves the panel into a right side panel tab, and closing the tab brings
    it back (v0.6.14). Nothing for the harness to read: no session is opened."""
    return _blocked("in a throwaway conversation ask Codex to open auto resume settings and press Open "
                    "beside the chat: confirm a right side panel tab shows the panel, scrollable to Save, "
                    "with the same state, and that closing the tab puts it back in the conversation with "
                    "the button; then set the verdict", session_opened=False)


def _mp3(_ctx):
    """Beside the chat the panel calls its tools and reads again on return, and nothing appears in the
    conversation (v0.6.14). Nothing for the harness to read: no session is opened."""
    return _blocked("in that side panel tab press Preview, click away for 15 seconds and back (the panel "
                    "redraws), set Theme to Dark and Save, then back and Save: confirm each works and no "
                    "new item appears in the conversation, note whether an approval prompt appeared, then "
                    "set the verdict", session_opened=False)


# MP1's lookups: the name the plugin gives this product's server in Codex (build/plugin-mcp.json,
# `mcpServers`), and how much of the home's listing it reads where Codex lists the server under
# another name - ten servers to a page, at most ten pages.
_MP1_SERVER = "codex-auto-resume"
_MP1_PAGE = 10
_MP1_PAGES = 10
# The entrypoint the panel's tool declares for a conversation's side panel (mcp/tools.py).
_THREAD_ENTRYPOINT = {"type": "thread"}


def _read(session, params):
    """One usage read, as the reset actions keep it (codex/credits.parse), and the reply itself for
    the one question parse does not answer - whether the credits' details came with it."""
    reply = session.call(credits.READ, dict(params))
    return reply, credits.parse(reply)


def _running(windows) -> dict:
    """{(bucket, minutes): reset time} of each window that is running: used, with a reset ahead."""
    return {(window["bucket"], window["window_minutes"]): window["reset_at"] for window in windows or ()
            if window["used_percent"] > 0 and window["reset_at"] is not None}


def _mu(ctx):
    """Codex's usage read as the reset actions read it (v0.6.14). The harness reads usage in full, then
    without the credits' details, then again a minute apart, and records whether the count of reset
    credits is there, whether the details come with the first read and not with the second - the param
    taken, not refused - and how far a running window's reset time moved. What the harness cannot see is
    the person's: across one 5-hour reset with no Codex use, that the window then opens with the first
    message and resets about five hours after it.

    How the owner runs it: with a 5-hour window running, `measure mu`; then use no Codex from ten
    minutes before the reset /usage shows until after it, send one short message in a throwaway
    conversation, and record with `measure-verdict mu pass as_expected` - or a fail."""
    with ctx.open() as session:
        detailed, first = _read(session, credits.DETAILED)
        light, second = _read(session, credits.LIGHT)
        seen = [first, second]
        for _again in range(_MU_READS - 1):
            time.sleep(_MU_SPACING)
            seen.append(_read(session, credits.LIGHT)[1])
    running = _running(first["windows"])
    drift = 0
    for family, reset_at in running.items():
        for reading in seen[1:]:
            later = _running(reading["windows"]).get(family)
            if later is not None:
                drift = max(drift, abs(later - reset_at))
    observed = {"windows_read": first["windows"] is not None, "count_read": first["credits"] is not None,
                "details_with_full_read": credits.details_listed(detailed),
                "details_left_out": not credits.details_listed(light) and second["credits"] is not None,
                "running_windows": len(running), "max_drift_seconds": int(drift)}
    if not (observed["windows_read"] and observed["count_read"] and observed["details_with_full_read"]
            and observed["details_left_out"]):
        return Verdict.FAIL, observed, "the usage read does not carry the reset credits as the schema says"
    if not running:
        return _blocked("use Codex until a 5-hour window is running, then run mu again", **observed)
    if drift > _MU_TOLERANCE:
        return Verdict.FAIL, observed, "a running window's reset time moved between reads"
    return _blocked("use no Codex from ten minutes before the 5-hour reset /usage shows until after it, then "
                    "send one short message in a throwaway conversation: confirm /usage shows the 5-hour "
                    "window reset about five hours after that message, then set the verdict", **observed)


def _mn(ctx):
    """A consume with no reset credit to spend spends nothing (v0.6.14). Only where a read shows no
    credit at all: the harness asks for one under a key of its own, reads the count again, asks again
    with the same key, and records what each came to - `no_credit`, or `nothing_to_reset`, which Codex's
    schema allows as well where no window is full - and whether the count stayed where it was. With a
    credit there, it calls nothing: that is MR's, at a limit."""
    with ctx.open() as session:
        before = _read(session, credits.DETAILED)[1]
        if before["credits"] is None:
            return Verdict.FAIL, {"count_read": False}, "the usage read carries no count of reset credits"
        if before["credits"] != 0:
            return _blocked("this account has reset credits: measure mr at a limit instead",
                            count_read=True, has_credits=True)
        key = str(uuid.uuid4())                       # never recorded
        first = credits.outcome(session.call(credits.CONSUME, {"idempotencyKey": key}))
        after = _read(session, credits.DETAILED)[1]
        second = credits.outcome(session.call(credits.CONSUME, {"idempotencyKey": key}))
    observed = {"count_read": True, "has_credits": False, "first_outcome": str(first),
                "second_outcome": str(second), "count_unchanged": after["credits"] == 0}
    refused = (SpendOutcome.NO_CREDIT, SpendOutcome.NOTHING_TO_RESET)
    if first in refused and second in refused and observed["count_unchanged"]:
        return Verdict.PASS, observed, None
    return Verdict.FAIL, observed, "a consume with no credit did not refuse, or the count moved"


def _mr(ctx):
    """At a real limit one consume resets it, spends exactly one credit, and asked again with the same
    key spends no second one (v0.6.14). It spends one real reset credit, so it runs only with the
    person's second, explicit yes (`may_spend`) - without it no session is opened -, only while a window
    is full and only while a credit is there - otherwise it calls nothing more and says what is missing. It records what each consume came
    to, whether the count went down by exactly one and then stayed, which windows changed, and whether
    Codex then allows ordinary usage; that the limit lifted in the app is the person's to confirm.

    How the owner runs it: when Codex says a limit is reached and /usage shows a reset credit, `measure
    mr` with may_spend; then send a message in Codex and see it run, and record with `measure-verdict mr
    pass as_expected` - or a fail."""
    if not ctx.may_spend:
        return _blocked("mr spends one real reset credit: run it again with may_spend", may_spend=False)
    with ctx.open() as session:
        before = _read(session, credits.DETAILED)[1]
        full = credits.full(before["windows"])
        if not full:
            return _blocked("no usage window is full now: run mr when Codex says a limit is reached",
                            may_spend=True, limit_reached=False)
        if not before["credits"]:
            return _blocked("no reset credit is there to spend: run mr when /usage shows one", may_spend=True,
                            limit_reached=True, has_credits=False)
        key = str(uuid.uuid4())                       # never recorded
        first = credits.outcome(session.call(credits.CONSUME, {"idempotencyKey": key}))
        after = _read(session, credits.DETAILED)[1]
        second = credits.outcome(session.call(credits.CONSUME, {"idempotencyKey": key}))
        last = _read(session, credits.DETAILED)[1]
    changed = _changed(before["windows"], after["windows"])
    observed = {"may_spend": True, "limit_reached": True, "has_credits": True, "first_outcome": str(first),
                "count_down_by_one": after["credits"] == before["credits"] - 1,
                "five_hour_changed": changed.get(_FIVE_HOURS, False), "weekly_changed": changed.get(_WEEK, False),
                "ordinary_usage_allowed": after["ordinary_usage_allowed"] is True,
                "second_outcome": str(second), "count_unchanged_on_retry": last["credits"] == after["credits"]}
    if not (first == SpendOutcome.RESET and observed["count_down_by_one"]
            and second == SpendOutcome.ALREADY_REDEEMED and observed["count_unchanged_on_retry"]):
        return Verdict.FAIL, observed, "the consume did not reset, spent other than one credit, or spent again"
    return _blocked("send a message in Codex and confirm it runs - the limit lifted -, then set the verdict",
                    **observed)


def _changed(before, after) -> dict:
    """{window length in minutes: whether it changed} between two readings: a full window no longer
    full, or a window whose reset time moved."""
    found = {}
    old = {(window["bucket"], window["window_minutes"]): window for window in before or ()}
    for window in after or ():
        earlier = old.get((window["bucket"], window["window_minutes"]))
        if earlier is None:
            continue
        moved = ((earlier["used_percent"] >= 100 > window["used_percent"])
                 or earlier["reset_at"] != window["reset_at"])
        found[window["window_minutes"]] = found.get(window["window_minutes"], False) or moved
    return found


# MU's reads: how many light reads after the first, a minute apart, and how far a running window's
# reset time may move between them before the count it rests on is not believed (engine/resetwatch.TOL).
_MU_READS = 3
_MU_SPACING = 60.0
_MU_TOLERANCE = 600
_FIVE_HOURS = 300
_WEEK = 10080


# --------------------------------------------------------------------------- the read-only probes (v0.6.16-beta.3)
# Three for what stop-now and send-now would need, each read-only and each running no live step from this product.
# MIPC never writes to the pipe; MAWS and MCLOUD read the engine's own CLI help. What each must answer is in its
# blocked note, for the owner to complete on a real machine, and nothing stop-now / send-now needs is built until
# MIPC's answer is in. Every observation is a boolean - never a path, a name, or a line of help text.
_WS_URL = "CODEX_APP_SERVER_WS_URL"
# The words the engine's help might name a shared-backend switch with (membership only; never recorded).
_SHARED_SWITCH_WORDS = ("shared app-server", "shared-app-server", "shared backend", "shared-backend",
                        "app-server-ws", "app_server_ws",
                        # 2026-10-16 (MAWS): the words a later help may use for one the Desktop app shares locally.
                        "shared local app-server")
# The words that would say a `codex cloud` help offers a state/status read (membership only).
_CLOUD_STATE_WORDS = ("status", "state", "show", "list", "watch", "logs")


def _mipc(ctx):
    """The Desktop's own IPC pipe \\.\\pipe\\codex-ipc (sybxxx/codex-auto-retry: 4-byte little-endian framing,
    owner-routed thread-follower-start-turn). A read-only look (ctx.ipc_look): whether the pipe exists, whether it
    opens, and whether a 4-byte frame header reads - and NOTHING written to it, no start, no interrupt, no message.

    It must answer: can this product start a turn, interrupt one, or put a message into a running turn of a
    conversation the app holds, through this pipe? The look only sees the pipe is reachable; driving a turn is what
    stop-now and send-now would need and is not built here, so the person confirms the rest."""
    look = ctx.ipc_look()
    observed = {"pipe_exists": bool(look.get("exists")), "pipe_opened": bool(look.get("opened")),
                "frame_read": bool(look.get("frame_read")), "no_answer": bool(look.get("no_answer"))}
    return _blocked("a read-only look at the Desktop's IPC pipe: it is never written to. Confirm whether a turn of "
                    "a conversation the app holds can be started, interrupted, or added to through it - stop-now "
                    "and send-now wait on this answer - then set the verdict", **observed)


def _maws(ctx):
    """Whether a shared app-server is a setting Codex documents (CODEX_APP_SERVER_WS_URL or a shared-backend switch):
    a read-only look at the engine's own help (ctx.cli_help, `app-server --help`), no launcher and no endpoint of
    ours. It records only whether the help read and whether each word is in it - never the help text.

    It must answer: could we join a shared app-server Codex itself runs, rather than own Codex's transport? The
    competitor (sybxxx) starts the Desktop against its own loopback server; this asks whether Codex documents one."""
    text = ctx.cli_help(("app-server", "--help"))
    read = text is not None
    lowered = text.lower() if read else ""
    observed = {"help_read": read,
                "ws_url_documented": read and _WS_URL in text,
                "shared_switch_documented": read and any(word in lowered for word in _SHARED_SWITCH_WORDS)}
    return _blocked("a read-only look at the engine's help for a documented shared app-server. Confirm against "
                    "Codex's own documentation, then set the verdict", **observed)


def _mcloud(ctx):
    """Whether a `codex cloud` command offers a supported, read-only way to read a cloud task's state: a read-only
    look at the engine's own help (ctx.cli_help, `cloud --help`), never UI automation and never a GitHub credential.
    It records only whether the help read, whether a cloud command is there, and whether it names a state read.

    It must answer: is there a supported way to read a Codex cloud task's state, and later to continue it? A cloud
    task leaves no local record (v0615-stage4 survey), so without this the watcher cannot see a limit there."""
    text = ctx.cli_help(("cloud", "--help"))
    read = text is not None
    lowered = text.lower() if read else ""
    # `codex <unknown> --help` exits 0 with the top-level help, so a cloud command is there only where its help is not
    # the top-level one and has a usage line of its own that names it.
    top = ctx.cli_help(("--help",)) if read else None
    own_usage = any(line.strip().startswith("usage:") and " cloud" in line for line in lowered.splitlines())
    present = (read and own_usage and (top is None or text.strip() != top.strip())
               and "unrecognized" not in lowered and "unknown" not in lowered and "no such" not in lowered)
    observed = {"cloud_help_read": read, "cloud_command_present": bool(present),
                "state_read_present": bool(present) and any(word in lowered for word in _CLOUD_STATE_WORDS)}
    return _blocked("a read-only look for a `codex cloud` command and a supported way to read a cloud task's state. "
                    "Confirm against Codex, then set the verdict", **observed)
# --------------------------------------------------------------------------- stage 4 (v0.6.16-beta.4)
# Nine more, each what a stage-4 capability's route rests on. Two sittings: Codex closed (M6B, MX, MF, M3B; MB on
# a scratch Codex home of the harness's own) and Codex open (MO with a TUI and VS Code, MXA, MC1, MC2). Every
# observation is a boolean, a count, a bucket or a closed word (vocabulary.ObservedWord), never a name, a model, a
# path or anything a turn said.
def _word(value, known) -> str:
    """`value` as an observation may hold it: one of `known`, or "other" - never the value itself."""
    return value if isinstance(value, str) and value in known else str(ObservedWord.OTHER)


SANDBOXES = frozenset({"readOnly", "workspaceWrite", "externalSandbox", "dangerFullAccess"})
POLICIES = frozenset({"untrusted", "on-failure", "on-request", "never"})


def _settings(resumed) -> dict:
    """The saved settings a thread/resume answered, as closed words: its sandbox's kind, its approval policy (a
    word, or "granular" for an object), its approvals' reviewer, and whether a permission profile is in force -
    never the profile, a folder or a model."""
    resumed = resumed if isinstance(resumed, dict) else {}
    sandbox = resumed.get("sandbox")
    policy = resumed.get("approvalPolicy")
    return {"sandbox": _word(sandbox.get("type") if isinstance(sandbox, dict) else None, SANDBOXES),
            "approval_policy": str(ObservedWord.GRANULAR) if isinstance(policy, dict) else _word(policy, POLICIES),
            "reviewer": _word(resumed.get("approvalsReviewer"), {"user"}),
            "permission_profile_set": resumed.get("activePermissionProfile") is not None}


def _turn_id(started):
    turn = started.get("turn") if isinstance(started, dict) else None
    return turn.get("id") if isinstance(turn, dict) and isinstance(turn.get("id"), str) else None


def _follow(session, thread, turn_id, seconds):
    """A turn followed to its end, or interrupted at `seconds`: (its status or None, whether it ended by itself)."""
    status = _await_turn(session, thread, turn_id, seconds)
    ended = status is not None
    if not ended and turn_id is not None:
        try:
            session.call("turn/interrupt", {"threadId": thread, "turnId": turn_id})
            status = _await_turn(session, thread, turn_id, _M6_INTERRUPT_SECONDS)
        except AdapterError:
            pass
    return status, ended


def _unsubscribed(session, thread) -> bool:
    try:
        session.call("thread/unsubscribe", {"threadId": thread})
        return True
    except AdapterError:
        return False                          # the session's exit tries once more


def _app_running(ctx) -> bool:
    """Whether the Codex app is running now, as core's pairing reads it - False where it cannot say."""
    try:
        return ctx.backend is not None and ctx.backend.app_identity() is not None
    except Exception:
        return False


def _m6b(ctx):
    """A headless turn on the thread's own saved settings (headless_run, and every route that stands on it): Codex
    closed, the owner names a throwaway conversation saved with workspace-write and on-request (or never) approvals.
    The thread is resumed with no override at all - the model, sandbox, approvals and folder Codex saved apply - and
    one turn asks for `whoami`, which those settings may run; every approval it asks is declined, and the turn is
    followed to its end or interrupted at the bound, then let go. It records the saved settings' closed words, how
    many it declined, the status, whether it ended by itself - and whether the Codex app was running at the end, for
    an owner who starts it during a second run to say what the app showed (Q3, decided again on it)."""
    with ctx.open() as session:
        resumed = session.call("thread/resume", {"threadId": ctx.probe_thread, "excludeTurns": True})
        started = session.call("turn/start", {"threadId": ctx.probe_thread,
                                              "input": [{"type": "text", "text": _M6_PROMPT}]})
        status, ended = _follow(session, ctx.probe_thread, _turn_id(started), _M6_TURN_SECONDS)
        unsubscribed = _unsubscribed(session, ctx.probe_thread)
        declined = session.declined_count()
    observed = dict(_settings(resumed), approvals_declined=declined, turn_ended_by_itself=ended,
                    unsubscribed=unsubscribed, app_running_after=_app_running(ctx))
    if status is not None:
        observed["turn_status"] = status
    return _blocked("confirm no window or console appeared and the turn shows in Codex afterwards; start the Codex "
                    "app during a second run, open the conversation and say what it showed, then set the verdict",
                    **observed)


# MO's words: the sources a `threads` row says, and the originators the edition takes a terminal's and VS Code's
# conversations by (core's codex/eligibility.ORIGINATORS) - as MO first recorded them on codex-cli 0.162.0-alpha.17.2
# (2026-10-16): the TUI writes codex-tui, the VS Code extension codex_vscode.
SOURCES = frozenset({"cli", "vscode", "exec", "mcp"})
ORIGINATOR_WORDS = {"codex-tui": ObservedWord.CLI_ORIGINATOR, "codex_vscode": ObservedWord.IDE_ORIGINATOR,
                    "Codex Desktop": ObservedWord.DESKTOP}


def _holder(ctx, home):
    """Who holds the conversation's writer lock, as core's pairing tells it: none, the app, another session, or
    unknown - a word, never a process."""
    from codex_auto_resume.codex import pairing
    from codex_auto_resume.win.inventory import resource_users
    try:
        users = resource_users(Path(home) / "thread-writer-locks" / (ctx.probe_thread + ".lock"))
        if not users:
            return str(ObservedWord.NONE)
        app = ctx.backend.app_identity()
        server = app.get("server") if isinstance(app, dict) else None
        if isinstance(server, dict) and users == [{key: server.get(key) for key in ("pid", "created")}]:
            return str(ObservedWord.APP)
        if len(users) == 1 and pairing.session_kind(pairing.inventory(), users[0], ctx.backend.codex_exe):
            return str(ObservedWord.SESSION)
    except Exception:
        pass
    return str(ObservedWord.UNKNOWN)


def _mo(ctx):
    """CLI, TUI and VS Code conversations (other_sessions): the owner runs one TUI (`codex --no-daemon` from the
    app's engine) and opens one VS Code extension conversation, each a throwaway, idle, and names one of them - then
    the other. Nothing is asked over the protocol: the conversation's `threads` row (its source, thread source and
    history mode), its rollout's first line (its originator and source, and whether it names a CLI version) and who
    holds its writer lock (codex/sessions.py, core's pairing) - each recorded as a closed word."""
    from .codex import sessions
    home = getattr(ctx.backend, "codex_home", None)
    if not ctx.thread_given or home is None:
        return _blocked("run one TUI and open one VS Code conversation, then name one of them", row_read=False)
    try:
        row, first = sessions.Origins(home).origin(ctx.probe_thread)
    except Exception:
        return _blocked("the conversation's row or its first line could not be read", row_read=False)
    observed = {"row_read": row is not None, "first_line_read": first is not None}
    if row is not None:
        observed.update(source=_word(row.get("source"), SOURCES),
                        thread_source=_word(row.get("thread_source"), {"user"}),
                        history_mode=_word(row.get("history_mode"), {"paginated"}))
    if first is not None:
        originator = first.get("originator")
        observed.update(originator=str(ORIGINATOR_WORDS.get(originator, ObservedWord.OTHER)
                                       if isinstance(originator, str) else ObservedWord.OTHER),
                        meta_source=_word(first.get("source"), SOURCES),
                        cli_version_present=isinstance(first.get("cli_version"), str))
    observed["holder"] = _holder(ctx, home)
    return _blocked("run it for the TUI's conversation and for VS Code's, confirm each is held by a session, then "
                    "set the verdict", **observed)


def _seconds(span) -> str:
    """A span in seconds as a bucket, never the number."""
    if span < 10:
        return str(ObservedWord.UNDER_10S)
    if span < 60:
        return str(ObservedWord.UNDER_60S)
    return str(ObservedWord.UNDER_600S if span < 600 else ObservedWord.OVER_600S)


# The item kinds a compaction turn leaves, counted per kind (B9's list; no content): the compaction and the reasoning
# around it, and no message of a person's.
COMPACTION_KINDS = frozenset({"contextCompaction", "reasoning"})


def _latest_kinds(ctx):
    """The conversation's latest turn from Codex's history (codex/turns.py): (its status or None, whether its kinds
    are only compaction and reasoning, whether it holds a person's message) - by kind alone, never a word."""
    from .codex import turns
    home = getattr(ctx.backend, "codex_home", None)
    found = turns.Turns(home).latest(ctx.probe_thread) if home is not None else None
    if found is None:
        return None, False, False
    kinds = {kind for kind, count in found.kinds.items() if count}
    return found.status, bool(kinds) and kinds <= COMPACTION_KINDS, "userMessage" in kinds


def _item_kind(event):
    """The kind of the item an item/started or item/completed notification names, or None - never its words."""
    if not isinstance(event, dict) or event.get("method") not in ("item/started", "item/completed"):
        return None
    params = event.get("params")
    item = params.get("item") if isinstance(params, dict) else None
    kind = item.get("type") if isinstance(item, dict) else None
    return kind if isinstance(kind, str) else None


def _mx(ctx):
    """A full conversation compacted here (compact_continue's headless half): Codex closed, a throwaway conversation
    with some history. The thread is resumed, thread/compact/start asked, the compaction's turn followed to its end
    or the bound, and the thread let go. It records whether the compaction was accepted, whether a contextCompaction
    item was seen, the turn's status, how long it took (a bucket), and whether the history's latest turn then holds
    compaction and reasoning only."""
    began = time.monotonic()
    seen = []
    with ctx.open() as session:
        session.call("thread/resume", {"threadId": ctx.probe_thread, "excludeTurns": True})
        accepted = session.call("thread/compact/start", {"threadId": ctx.probe_thread})
        status = _await_turn(session, ctx.probe_thread, None, _M6_TURN_SECONDS, seen=seen)
        unsubscribed = _unsubscribed(session, ctx.probe_thread)
    span = time.monotonic() - began
    try:
        only = _latest_kinds(ctx)[1]
    except Exception:
        only = False
    observed = {"compact_accepted": isinstance(accepted, dict),
                "compaction_item_seen": any(_item_kind(event) == "contextCompaction" for event in seen),
                "turn_ended": status is not None, "seconds": _seconds(span), "latest_compaction_only": only,
                "unsubscribed": unsubscribed}
    if status is not None:
        observed["turn_status"] = status
    return _blocked("confirm the conversation shows as compacted in Codex afterwards, then set the verdict", **observed)


def _mxa(ctx):
    """A person's own /compact (compact_continue's app half): in a throwaway the app holds, the owner runs /compact in
    Codex and names the conversation. No call: the latest turn's item kinds, counted, and whether it holds a person's
    message - whether Codex records the command as one decides whether core's ordinary send may follow it."""
    if not ctx.thread_given:
        return _blocked("run /compact in a throwaway conversation the app holds, then name it", history_read=False)
    try:
        status, only, user = _latest_kinds(ctx)
    except Exception:
        return _blocked("the turn history could not be read", history_read=False)
    observed = {"history_read": True, "compaction_only": only, "user_item_present": user}
    if status is not None:
        observed["turn_status"] = status
    return _blocked("confirm the latest turn is the /compact you ran, then set the verdict", **observed)


def _model_of(resumed):
    model = resumed.get("model") if isinstance(resumed, dict) else None
    return model if isinstance(model, str) and model else None


def _default_model(listed):
    """The model Codex marks its default (model/list's `isDefault`), or None - used here, never recorded."""
    data = listed.get("data") if isinstance(listed, dict) else None
    for entry in data if isinstance(data, list) else ():
        if isinstance(entry, dict) and entry.get("isDefault") is True:
            model = entry.get("model") or entry.get("id")
            return model if isinstance(model, str) and model else None
    return None


def _one_turn(ctx, resume, start):
    """One session: the thread resumed with `resume`, one short turn started with `start` followed, and let go."""
    with ctx.open() as session:
        session.call("thread/resume", dict(resume, threadId=ctx.probe_thread, excludeTurns=True))
        started = session.call("turn/start", dict(start, threadId=ctx.probe_thread,
                                                  input=[{"type": "text", "text": _M2B_PROMPT}]))
        status, _ended = _follow(session, ctx.probe_thread, _turn_id(started), _M6_TURN_SECONDS)
        _unsubscribed(session, ctx.probe_thread)
    return status, session


def _resumed_model(ctx):
    with ctx.open() as session:
        model = _model_of(session.call("thread/resume", {"threadId": ctx.probe_thread, "excludeTurns": True}))
        _unsubscribed(session, ctx.probe_thread)
    return model


def _mf(ctx):
    """Another model at capacity (model_fallback): Codex closed, a throwaway conversation not on Codex's default model.
    Which of two routes leaves nothing to put back: a `model` override at thread/resume, for that session only
    (resumed again without one, the thread's own model is back), or `model` on turn/start restored after the turn by
    thread/settings/update and read back. Booleans only: never a model's name."""
    with ctx.open() as session:
        original = _model_of(session.call("thread/resume", {"threadId": ctx.probe_thread, "excludeTurns": True}))
        default = _default_model(session.call("model/list", {}))
        _unsubscribed(session, ctx.probe_thread)
    observed = {"default_found": default is not None,
                "default_differs": default is not None and original is not None and default != original}
    if not observed["default_differs"]:
        return _blocked("name a throwaway conversation that is not on Codex's default model", **observed)
    status, _session = _one_turn(ctx, {"model": default}, {})
    observed["resume_override_session_only"] = _resumed_model(ctx) == original
    with ctx.open() as session:
        session.call("thread/resume", {"threadId": ctx.probe_thread, "excludeTurns": True})
        started = session.call("turn/start", {"threadId": ctx.probe_thread, "model": default,
                                              "input": [{"type": "text", "text": _M2B_PROMPT}]})
        _follow(session, ctx.probe_thread, _turn_id(started), _M6_TURN_SECONDS)
        session.call("thread/settings/update", {"threadId": ctx.probe_thread, "model": original})
        _unsubscribed(session, ctx.probe_thread)
    observed["restore_read_back"] = _resumed_model(ctx) == original
    if status is not None:
        observed["turn_status"] = status
    passed = observed["resume_override_session_only"] or observed["restore_read_back"]
    return (Verdict.PASS if passed else Verdict.FAIL, observed,
            None if passed else "neither route left the conversation on its own model")


def _client_recorded(ctx, client_id) -> bool:
    """Whether Codex's history keeps `client_id` on a person's message of the conversation (core's own read)."""
    from codex_auto_resume.codex import LocalSource
    home = getattr(ctx.backend, "codex_home", None)
    try:
        return home is not None and bool(LocalSource(home).marker_rows(ctx.probe_thread, client_id))
    except Exception:
        return False


def _m3b(ctx):
    """A turn with no words (silent_continuation): Codex closed, a throwaway conversation. The thread is resumed and a
    turn started with no input under a client id of no one's, followed, and let go; Codex refusing it is the probe's
    fail with its code (probe). It records whether a turn started, its status, and whether Codex's history keeps that
    client id on a message - which is what would prove a continuation with no words."""
    with ctx.open() as session:
        session.call("thread/resume", {"threadId": ctx.probe_thread, "excludeTurns": True})
        started = session.call("turn/start", {"threadId": ctx.probe_thread, "input": [],
                                              "clientUserMessageId": _SAMPLE_M3B_CLIENT_ID})
        status, ended = _follow(session, ctx.probe_thread, _turn_id(started), _M6_TURN_SECONDS)
        unsubscribed = _unsubscribed(session, ctx.probe_thread)
    observed = {"turn_started": _turn_id(started) is not None, "turn_ended_by_itself": ended,
                "client_id_recorded": _client_recorded(ctx, _SAMPLE_M3B_CLIENT_ID), "unsubscribed": unsubscribed,
                "turn_in_history": _turn_in_history(ctx, _turn_id(started))}
    if status is not None:
        observed["turn_status"] = status
    # v0.6.16-beta.4: the turn id turn/start returned, found in Codex's history, is the proof (the route correlates it
    # at once); no client id is kept on a turn with no words (2026-10-16).
    passed = observed["turn_started"] and observed["turn_in_history"]
    return (Verdict.PASS if passed else Verdict.FAIL, observed,
            None if passed else "no turn started, or none in the history by the id it was started under")


def _turn_in_history(ctx, turn_id) -> bool:
    """Whether Codex's history says the turn `turn_id` is the probe's conversation's latest (ids only)."""
    from .codex.turns import Turns
    home = getattr(ctx.backend, "codex_home", None)
    if home is None or turn_id is None:
        return False
    try:
        latest = Turns(home).latest(ctx.probe_thread)
    except Exception:
        return False
    return latest is not None and latest.turn_id == turn_id


# Codex's own retry settings (codex_retry_settings): the two keys, as config/value/write names them.
RETRY_KEYS = ("model_providers.openai.request_max_retries", "model_providers.openai.stream_max_retries")


def _config_value(read, key):
    """The value `key` has in the configuration a config/read answered, or None."""
    value = read.get("config") if isinstance(read, dict) else None
    for part in key.split("."):
        value = value.get(part) if isinstance(value, dict) else None
    return value


def _version_of(read):
    found = read.get("version") if isinstance(read, dict) else None
    return found if isinstance(found, (str, int)) and not isinstance(found, bool) else None


def _mb(ctx):
    """Codex's own config writes (codex_retry_settings), on a scratch Codex home the harness makes and removes - no
    config of the person's is ever opened or written: config/read with its layers, both keys written (upsert) and read
    back, the first one removed and read back, and a write against a stale version refused. Booleans only."""
    import shutil
    import tempfile
    scratch = Path(tempfile.mkdtemp(prefix="car-mb-"))
    conflict = False
    try:
        with ctx.open_scratch(scratch) as session:
            before = back = session.call("config/read", {"includeLayers": True})
            written = []
            for key in RETRY_KEYS:
                written.append(session.call("config/value/write", {"keyPath": key, "value": _MB_VALUE,
                                                                   "mergeStrategy": "upsert",
                                                                   "expectedVersion": _version_of(back)}))
                back = session.call("config/read", {"includeLayers": True})
            session.call("config/value/write", {"keyPath": RETRY_KEYS[0], "value": None, "mergeStrategy": "replace",
                                                "expectedVersion": _version_of(back)})
            removed = session.call("config/read", {"includeLayers": True})
            try:
                session.call("config/value/write", {"keyPath": RETRY_KEYS[1], "value": _MB_VALUE + 1,
                                                    "mergeStrategy": "upsert", "expectedVersion": _version_of(before)})
            except AdapterError as exc:
                conflict = hasattr(exc, "method")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    observed = {"write_accepted": all(isinstance(answer, dict) for answer in written),
                "read_back": all(_config_value(back, key) == _MB_VALUE for key in RETRY_KEYS),
                "removal_restores": (_config_value(removed, RETRY_KEYS[0]) is None
                                     and _config_value(before, RETRY_KEYS[0]) is None),
                "version_conflict_refused": conflict}
    passed = all(observed.values())
    return (Verdict.PASS if passed else Verdict.FAIL, dict(observed, scratch_home=True),
            None if passed else "a write, its read back, its removal or the stale version did not hold")


def _mc1(ctx):
    """A person's message from the Dashboard (codex_chat): the owner names a throwaway conversation the app holds,
    idle. One short message is added to its queue under a client id of no one's - thread/queue/add, M7's call, with
    no marker - and the queue followed until the app takes it; then whether Codex's history shows a turn within ten
    seconds, and the client id on its message. That it showed at once as the person's own, with nothing to say a
    program sent it, is what the person watching confirms."""
    with ctx.open() as session:
        added = session.call("thread/queue/add", {"threadId": ctx.probe_thread,
                                                  "clientUserMessageId": _SAMPLE_MC1_CLIENT_ID,
                                                  "input": [{"type": "text", "text": _M2B_PROMPT}]})
        began = time.monotonic()
        taken = _await_taken(session, ctx.probe_thread, _SAMPLE_MC1_CLIENT_ID, _MC1_QUEUE_SECONDS)
    waited = time.monotonic() - began
    started = False
    deadline = time.monotonic() + _MC1_START_SECONDS
    while taken:
        try:
            started = _latest_kinds(ctx)[0] in ("inProgress", "completed")
        except Exception:
            started = False
        if started or time.monotonic() >= deadline:
            break
        time.sleep(_M2B_POLL_SECONDS)
    observed = {"add_accepted": isinstance(added, dict), "taken": taken, "taken_seconds": _seconds(waited),
                "turn_started": started, "client_id_on_user_item": _client_recorded(ctx, _SAMPLE_MC1_CLIENT_ID)}
    return _blocked("confirm the message showed at once as your own, nothing marked it as sent by a program, and the "
                    "turn ran as one you typed, then set the verdict", **observed)


def _mqo(ctx):
    """A continuation queued for opening, with no marker (v0.6.17, issue #42): the owner names a throwaway conversation
    the Desktop does not hold. The harness lists what the app holds - and stops there if it holds this one - then adds
    one short message to its queue under a client id of no one's, with no marker (thread/queue/add, M7's call, as
    marker-free continuation sends), looks that it stays queued, and follows the queue for up to _MQO_OPEN_SECONDS
    while the person opens the conversation in the Desktop. Taken, it reads Codex's history for that client id on a
    person's message the way core proves a marker-free continuation delivered (LocalSource.marker_rows: the history
    database's userMessage items, placed by the rollout - engine/reconcile.py reads exactly this). That the message
    ran there once, as the person's own, is what the person watching confirms."""
    with ctx.open() as session:
        loaded = session.call("thread/loaded/list")
        held = loaded.get("data") if isinstance(loaded, dict) else None
        if not isinstance(held, list):
            return _blocked("the conversations the app holds could not be listed", loaded_listed=False)
        if ctx.probe_thread in held:
            return _blocked("the app holds the throwaway conversation: quit and reopen the Codex app without opening "
                            "it, then run mqo again", loaded_listed=True, held_before=True)
        added = session.call("thread/queue/add", {"threadId": ctx.probe_thread,
                                                  "clientUserMessageId": _SAMPLE_MQO_CLIENT_ID,
                                                  "input": [{"type": "text", "text": _M2B_PROMPT}]})
        listed = session.call("thread/queue/list", {"threadId": ctx.probe_thread})
        items = listed.get("data") if isinstance(listed, dict) else None
        waiting = isinstance(items, list) and any(
            isinstance(item, dict) and item.get("clientUserMessageId") == _SAMPLE_MQO_CLIENT_ID for item in items)
        began = time.monotonic()
        taken = waiting and _await_taken(session, ctx.probe_thread, _SAMPLE_MQO_CLIENT_ID, _MQO_OPEN_SECONDS)
    waited = time.monotonic() - began
    found = False
    deadline = time.monotonic() + _MQO_FIND_SECONDS
    while taken:
        found = _client_recorded(ctx, _SAMPLE_MQO_CLIENT_ID)
        if found or time.monotonic() >= deadline:
            break
        time.sleep(_M2B_POLL_SECONDS)
    observed = {"loaded_listed": True, "held_before": False, "add_accepted": isinstance(added, dict),
                "queued_while_not_held": waiting, "taken": taken, "taken_seconds": _seconds(waited),
                "client_id_on_user_item": found}
    return _blocked("open the throwaway conversation in the Desktop within five minutes of starting this; confirm the "
                    "message ran there once, as your own, with no marker, then set the verdict", **observed)


def _held(session, threads):
    """Which of `threads` the app holds now (thread/loaded/list), or None where that could not be listed."""
    loaded = session.call("thread/loaded/list")
    held = loaded.get("data") if isinstance(loaded, dict) else None
    return None if not isinstance(held, list) else [thread for thread in threads if thread in held]


def _queued_ids(session, thread):
    """The client ids of the items in `thread`'s queue now, or None where it could not be listed."""
    listed = session.call("thread/queue/list", {"threadId": thread})
    items = listed.get("data") if isinstance(listed, dict) else None
    if not isinstance(items, list):
        return None
    return [item.get("clientUserMessageId") for item in items if isinstance(item, dict)]


def _recorded_in(ctx, thread, client_id) -> bool:
    """Whether Codex's history keeps `client_id` on a person's message of `thread` - core's own read, as
    _client_recorded makes it for the measurement's one conversation."""
    from codex_auto_resume.codex import LocalSource
    home = getattr(ctx.backend, "codex_home", None)
    try:
        return home is not None and bool(LocalSource(home).marker_rows(thread, client_id))
    except Exception:
        return False


def _mqp(ctx):
    """Several sends at once (v0.6.17): the owner names two to four throwaway conversations the Desktop does not hold,
    comma-separated. The harness stops if the app holds any of them; otherwise it adds one short message with no marker
    to each at once - each add in a session of its own, on a thread of its own, under a client id of its own - then
    lists each queue: every add accepted, and each conversation's queue holding its own item and none of the others'.
    It follows the queues for up to _MQO_OPEN_SECONDS while the person opens each conversation in the Desktop, and
    reads Codex's history for each client id in its own conversation and in the others (core's read, as MQO's). That
    each message ran once, in its own conversation only, is what the person watching confirms."""
    import threading
    threads = ctx.probe_threads
    if len(threads) < 2:
        return _blocked("name two to four throwaway conversations the Desktop does not hold, comma-separated, then run "
                        "mqp again", conversations=len(threads))
    ids = _SAMPLE_MQP_CLIENT_IDS[:len(threads)]
    with ctx.open() as session:
        held = _held(session, threads)
    if held is None:
        return _blocked("the conversations the app holds could not be listed", loaded_listed=False)
    if held:
        return _blocked("the app holds one of the throwaway conversations: quit and reopen the Codex app without "
                        "opening them, then run mqp again", loaded_listed=True, held_before=len(held))
    accepted = [False] * len(threads)

    def add(index):
        try:
            with ctx.open() as own:
                answer = own.call("thread/queue/add", {"threadId": threads[index], "clientUserMessageId": ids[index],
                                                       "input": [{"type": "text", "text": _M2B_PROMPT}]})
            accepted[index] = isinstance(answer, dict)
        except Exception:
            accepted[index] = False
    workers = [threading.Thread(target=add, args=(index,), daemon=True) for index in range(len(threads))]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(_MQP_ADD_SECONDS)
    own_queued = misplaced = taken = 0
    with ctx.open() as session:
        for index, thread in enumerate(threads):
            found = _queued_ids(session, thread) or []
            own_queued += ids[index] in found
            misplaced += sum(1 for other in ids if other != ids[index] and other in found)
        began = time.monotonic()
        for index, thread in enumerate(threads):
            left = max(0.0, _MQO_OPEN_SECONDS - (time.monotonic() - began))
            taken += _await_taken(session, thread, ids[index], left)
    # As MQO: the history is read again until each conversation's own message is found there, _MQO_FIND_SECONDS at
    # most - a message taken a moment ago may not be written yet (the owner's run of 2026-10-20 read 1 of 2 at once).
    found = set()
    deadline = time.monotonic() + _MQO_FIND_SECONDS
    while taken:
        found |= {index for index, thread in enumerate(threads)
                  if index not in found and _recorded_in(ctx, thread, ids[index])}
        if len(found) == len(threads) or time.monotonic() >= deadline:
            break
        time.sleep(_M2B_POLL_SECONDS)
    found_own = len(found)
    found_elsewhere = sum(_recorded_in(ctx, thread, other) for thread in threads for other in ids
                          if other != ids[threads.index(thread)]) if taken else 0
    observed = {"conversations": len(threads), "held_before": 0, "accepted": sum(accepted),
                "queued_in_own": own_queued, "queued_elsewhere": misplaced, "taken": taken,
                "found_in_own": found_own, "found_elsewhere": found_elsewhere}
    return _blocked("open each of the throwaway conversations in the Desktop within five minutes of starting this; "
                    "confirm each message ran once, in its own conversation only, then set the verdict", **observed)


def _mqg(ctx):
    """A goal and a continuation queued for opening, together (v0.6.17): the owner names a throwaway conversation the
    Desktop does not hold, with a goal it paused. The harness stops if the app holds it or it has no goal; otherwise it
    sets that existing goal active (M2's call - never creating one) and adds one short message with no marker to its
    queue under a client id of its own (MQO's), notes the conversation's latest turn, and follows the queue for up to
    _MQO_OPEN_SECONDS while the person opens it in the Desktop; taken, it watches the history for _MQG_SETTLE_SECONDS
    and counts the turns that ran after the one it noted - two where the goal and the queued message each ran one, one
    where they ran as one - and reads the goal's status again. What ran is what the person watching confirms."""
    from .codex import turns
    home = getattr(ctx.backend, "codex_home", None)
    with ctx.open() as session:
        held = _held(session, (ctx.probe_thread,))
        if held is None:
            return _blocked("the conversations the app holds could not be listed", loaded_listed=False)
        if held:
            return _blocked("the app holds the throwaway conversation: quit and reopen the Codex app without opening "
                            "it, then run mqg again", loaded_listed=True, held_before=True)
        before = _goal_status(session.call("thread/goal/get", {"threadId": ctx.probe_thread}))
        if before is None:
            return _blocked("give the throwaway conversation a goal and pause it, close the conversation, then run mqg "
                            "again", loaded_listed=True, held_before=False, goal_found=False)
        session.call("thread/goal/set", {"threadId": ctx.probe_thread, "status": "active"})
        set_active = _goal_status(session.call("thread/goal/get", {"threadId": ctx.probe_thread}))
        try:
            first = turns.Turns(home).latest(ctx.probe_thread) if home is not None else None
        except Exception:
            first = None
        added = session.call("thread/queue/add", {"threadId": ctx.probe_thread,
                                                  "clientUserMessageId": _SAMPLE_MQG_CLIENT_ID,
                                                  "input": [{"type": "text", "text": _M2B_PROMPT}]})
        waiting = _SAMPLE_MQG_CLIENT_ID in (_queued_ids(session, ctx.probe_thread) or [])
        taken = waiting and _await_taken(session, ctx.probe_thread, _SAMPLE_MQG_CLIENT_ID, _MQO_OPEN_SECONDS)
        ran = 0
        deadline = time.monotonic() + _MQG_SETTLE_SECONDS
        while taken:
            ran = _turns_after(home, ctx.probe_thread, first)
            if time.monotonic() >= deadline:
                break
            time.sleep(_M2B_POLL_SECONDS)
        after = _goal_status(session.call("thread/goal/get", {"threadId": ctx.probe_thread}))
    observed = {"loaded_listed": True, "held_before": False, "goal_found": True,
                "goal_set_active": set_active == "active", "add_accepted": isinstance(added, dict),
                "queued_while_not_held": waiting, "taken": taken, "turns_after_open": ran,
                "client_id_on_user_item": taken and _client_recorded(ctx, _SAMPLE_MQG_CLIENT_ID),
                "goal_active_after": after == "active"}
    return _blocked("open the throwaway conversation in the Desktop within five minutes of starting this and watch it "
                    "for two more; say whether two turns ran (the goal's and the queued message) or one, then set the "
                    "verdict", **observed)


def _turns_after(home, thread, first) -> int:
    """How many turns of `thread` ran after the turn `first` (codex/turns.py), 0 where none or it cannot be read."""
    from .codex import turns
    try:
        reader = turns.Turns(home)
        latest = reader.latest(thread)
        if latest is None or (first is not None and latest.turn_id == first.turn_id):
            return 0
        if first is None:
            return 1
        return reader.between(thread, first.ordinal, latest.ordinal) + 1
    except Exception:
        return 0


class _Watch:
    """What MC2 sees of one conversation, look after look: when the history first said a new latest turn was in
    progress and when it ended, when the rollout's newest event first said a task started and ended, whether the
    reply's item was there when the history said it ended, and whether either showed a wait for an approval. The
    times are the harness's own clock, in memory, and recorded only as which came first and a bucket."""
    STARTED = frozenset({"task_started"})
    ENDED = frozenset({"task_complete", "turn_aborted"})
    APPROVAL = frozenset({"exec_approval_request", "apply_patch_approval_request", "request_permissions"})

    def __init__(self, home, thread):
        from .codex import sessions, turns
        self.turns, self.origins, self.thread = turns.Turns(home), sessions.Origins(home), thread
        self.first_turn = self.first_event = None
        self.db_start = self.db_end = self.rollout_start = self.rollout_end = None
        self.reply_ready = self.waited_db = self.waited_rollout = False
        self._looked, self._offset = False, None

    def look(self, now):
        found = self.turns.latest(self.thread)
        # v0.6.16-beta.4: every event the rollout gained since the last look, in order - a task that started and
        # ended between two looks was missed by its newest alone.
        kinds, self._offset = self.origins.events_since(self.thread, self._offset)
        kind = kinds[-1] if kinds else None
        if not self._looked:
            self._looked = True
            self.first_turn, self.first_event = (found.turn_id if found is not None else None), kind
            return
        for seen in kinds[:-1]:
            self._event(seen, now)
        fresh = found is not None and found.turn_id != self.first_turn
        if fresh and found.status == "inProgress" and self.db_start is None:
            self.db_start = now
        if fresh and found.status in ("completed", "failed", "interrupted") and self.db_end is None:
            self.db_start = self.db_start if self.db_start is not None else now
            self.db_end = now
            self.reply_ready = found.kinds.get("agentMessage", 0) > 0
        if fresh and found.status == "other":
            self.waited_db = True
        self._event(kind, now)

    def _event(self, kind, now):
        if kind in self.STARTED and self.rollout_start is None:
            self.rollout_start = now
        if kind in self.ENDED and self.rollout_start is not None and self.rollout_end is None:
            self.rollout_end = now
        if kind in self.APPROVAL:
            self.waited_rollout = True

    def settled(self) -> bool:
        return self.db_end is not None and self.rollout_end is not None

    @staticmethod
    def _first(db, rollout) -> str:
        if db is None and rollout is None:
            return str(ObservedWord.NEITHER)
        if rollout is None or (db is not None and db < rollout):
            return str(ObservedWord.DB)
        if db is None or rollout < db:
            return str(ObservedWord.ROLLOUT)
        return str(ObservedWord.SAME)

    def observed(self) -> dict:
        found = {"started_first": self._first(self.db_start, self.rollout_start),
                 "finished_first": self._first(self.db_end, self.rollout_end),
                 "reply_item_ready_at_final": self.reply_ready,
                 "approval_wait_seen_db": self.waited_db, "approval_wait_seen_rollout": self.waited_rollout}
        if self.settled():
            lag = abs(self.db_end - self.rollout_end)
            found["finished_lag"] = str(ObservedWord.UNDER_1S if lag < 1 else ObservedWord.S1_TO_5 if lag <= 5
                                        else ObservedWord.OVER_5S)
        return found


def _mc2(ctx):
    """Where chat reads "in progress" from (codex_chat): the owner names a throwaway conversation, then sends one short
    prompt in the app and one that asks for an approval. No call: every quarter second for five minutes, the latest
    turn's status from Codex's history (codex/turns.py) and the kind of the rollout's newest event (codex/sessions.py
    - its type, never a payload). It records which said first that a turn started and that it ended, the lag between
    them (a bucket), whether the reply's item was there when the history said it ended, and whether either showed
    the turn waiting for an approval."""
    home = getattr(ctx.backend, "codex_home", None)
    if not ctx.thread_given or home is None:
        return _blocked("name a throwaway conversation, then send a prompt in it", history_read=False)
    watch = _Watch(home, ctx.probe_thread)
    deadline = time.monotonic() + _MC2_SECONDS
    try:
        while True:
            watch.look(time.monotonic())
            if watch.settled() or time.monotonic() >= deadline:
                break
            time.sleep(_MC2_POLL_SECONDS)
    except Exception:
        return _blocked("the history or the rollout could not be read", history_read=False)
    return _blocked("confirm the two prompts were sent while this ran, then set the verdict",
                    history_read=True, **watch.observed())


_SAMPLE_M3B_CLIENT_ID = "00000000-0000-7000-8000-000000000003"
_SAMPLE_MC1_CLIENT_ID = "00000000-0000-7000-8000-000000000004"
_MB_VALUE = 8                    # the value MB writes: the retry settings' default (codex_retry_settings)
_MC1_QUEUE_SECONDS = 60.0        # how long MC1 follows the queue for the app to take its item
_MC1_START_SECONDS = 10.0        # and then the history for the turn it starts
_MC2_SECONDS = 300.0
_SAMPLE_MQO_CLIENT_ID = "00000000-0000-7000-8000-000000000005"
_SAMPLE_MQP_CLIENT_IDS = ("00000000-0000-7000-8000-000000000006", "00000000-0000-7000-8000-000000000007",
                          "00000000-0000-7000-8000-000000000008", "00000000-0000-7000-8000-000000000009")
_SAMPLE_MQG_CLIENT_ID = "00000000-0000-7000-8000-00000000000a"
_MQP_MOST = 4                    # the most conversations MQP sends to at once
_MQP_ADD_SECONDS = 60.0          # how long MQP waits for each add it started
_MQG_SETTLE_SECONDS = 120.0      # how long MQG watches the history for turns once the queued message is taken
_MQO_OPEN_SECONDS = 300.0        # how long MQO follows the queue for the person to open the conversation
_MQO_FIND_SECONDS = 30.0         # and then the history for the message under its client id
_MC2_POLL_SECONDS = 0.25


# --------------------------------------------------------------------------- v0.6.19 (the groundwork)
# Five probes the measurement session runs while the stage's capabilities are built (plans/v0619-design/
# D-groundwork.md section 5), and M4B's start, which the Stop hook's writer finishes. Each is content-free: booleans,
# counts, buckets and closed words, never a path, an address, a name or anything a turn said. What a person must do is
# left to them, the verdict blocked. Every effect beyond a session is one of the run's hands (Context._hands), which the
# Dashboard's runtime wires to live_hands and a test to fakes: a link opened, a power read, a wake timer, the engine run
# on a scratch Codex home.
_TOKEN_KEYS = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens", "total_tokens")
_TOKEN_SCAN_BYTES = 16 * 1024 * 1024          # how much of a rollout MTOK reads, at most
_TOKENS_USED = "SELECT tokens_used FROM threads WHERE id=?"
_SCHEMA_FILES = 2000                          # how many generated schema files a probe reads, at most
_SCHEMA_FILE_BYTES = 4 * 1024 * 1024          # and how much of each
_SCHEMA_ARGUMENTS = ("app-server", "generate-json-schema", "--out")
_MOPEN_SECONDS = 30.0                         # how long MOPEN looks for the conversation to load after its link opened
_MOPEN_POLL_SECONDS = 0.5
_MAL_SECONDS = 300.0                          # how long MAL follows the account while the person signs out and in
_MAL_POLL_SECONDS = 2.0
_MWAKE_SECONDS = 180                          # the wake timer MWAKE sets, from when it starts
_MWAKE_BOUND = 900                            # how long it waits for that timer, at most
_MWAKE_SLEPT = 60                             # how long the PC must have slept for the wake to count
_MWAKE_LATE = 120                             # and how soon after the timer it must have woken
# The Stop hook input's keys MHK looks for, by their letters alone (case and separators set aside). Membership only;
# no word of the schema is recorded.
_HOOK_INPUT_KEYS = ("session_id", "turn_id", "hook_event_name", "transcript_path", "stop_hook_active")


def _letters(word) -> str:
    return "".join(character for character in word.lower() if character.isalnum()) if isinstance(word, str) else ""


def _schema_documents(folder) -> list:
    """The JSON documents a schema generation wrote under `folder`, each a (file stem, document) pair: at most
    _SCHEMA_FILES files of at most _SCHEMA_FILE_BYTES, a link never followed, anything unreadable passed over."""
    import json
    found = []
    for path in sorted(Path(folder).rglob("*.json"))[:_SCHEMA_FILES]:
        try:
            if path.is_symlink() or path.stat().st_size > _SCHEMA_FILE_BYTES:
                continue
            found.append((path.stem, json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, ValueError, UnicodeError):
            continue
    return found


def _definitions(documents):
    """Every (name, schema) the documents define: each file as its stem, and each entry of its definitions."""
    for stem, document in documents:
        if not isinstance(document, dict):
            continue
        yield stem, document
        for key in ("definitions", "$defs"):
            table = document.get(key)
            if isinstance(table, dict):
                for name, schema in table.items():
                    if isinstance(schema, dict):
                        yield name, schema


def _enum_words(schema) -> set:
    """The words a schema's value may be: its enum, or its alternatives' consts and enums - by their letters."""
    words = set()
    if not isinstance(schema, dict):
        return words
    for word in schema.get("enum") or ():
        words.add(_letters(word))
    if "const" in schema:
        words.add(_letters(schema["const"]))
    for key in ("oneOf", "anyOf"):
        for item in schema.get(key) or ():
            words |= _enum_words(item)
    return words - {""}


def _strings(value):
    """Every string in a JSON value, keys and values alike."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _generated_schema(ctx, scratch):
    """The documents Codex's own schema generation wrote, run on a scratch Codex home inside `scratch` - [] where it
    could not be run or wrote nothing."""
    home, out = scratch / "codex-home", scratch / "schema"
    home.mkdir(exist_ok=True)
    out.mkdir(exist_ok=True)
    if ctx.scratch_cli(home, _SCHEMA_ARGUMENTS + (str(out),)) is None:
        return []
    return _schema_documents(out)


def _token_events(path):
    """(how many token_count events with totals the rollout at `path` holds, whether every one has the five kinds as
    whole numbers, whether the totals never decreased, the last total) - the first _TOKEN_SCAN_BYTES read, numbers
    alone kept."""
    import json
    with path.open("rb") as stream:
        data = stream.read(_TOKEN_SCAN_BYTES)
    count, keyed, monotone, last = 0, True, True, None
    for line in data.split(b"\n"):
        if b'"token_count"' not in line:
            continue
        try:
            event = json.loads(line.decode("utf-8"))
        except (ValueError, UnicodeError):
            continue
        payload = event.get("payload") if isinstance(event, dict) else None
        info = payload.get("info") if isinstance(payload, dict) and payload.get("type") == "token_count" else None
        totals = info.get("total_token_usage") if isinstance(info, dict) else None
        if not isinstance(totals, dict):
            continue
        count += 1
        keyed = keyed and all(type(totals.get(key)) is int for key in _TOKEN_KEYS)
        total = totals.get("total_tokens")
        if type(total) is int:
            monotone = monotone and (last is None or total >= last)
            last = total
    return count, keyed and count > 0, monotone, last


def _tokens_used(home, thread):
    """(whether the history's `threads` has tokens_used to read, the conversation's value there or None)."""
    import sqlite3
    from .codex.turns import TurnsUnavailable, connect
    try:
        connection = connect(home, "state", {"threads": frozenset({"id", "tokens_used"})})
    except TurnsUnavailable:
        return False, None
    try:
        row = connection.execute(_TOKENS_USED, (thread,)).fetchone()
    except sqlite3.Error:
        row = None
    finally:
        connection.close()
    return True, (row[0] if row is not None and type(row[0]) is int else None)


def _mtok(ctx):
    """Per-day token analytics (usage_analytics): the owner names a throwaway conversation with at least two finished
    turns. Its rollout's token_count events are read - how many carry totals, whether each has the five kinds as whole
    numbers, whether the totals never decrease - and the history's tokens_used for it compared with the last total; and
    Codex's own generated schema (on a scratch Codex home) is searched for a thread token read. Numbers are compared,
    never recorded. Pass where the keys are there and the totals never decrease, over two counts at least."""
    import shutil
    import tempfile
    from .codex import sessions
    home = getattr(ctx.backend, "codex_home", None)
    if not ctx.thread_given or home is None:
        return _blocked("name a throwaway conversation with at least two finished turns", rollout_read=False)
    try:
        path = sessions.Origins(home).rollout(ctx.probe_thread)
        count, keyed, monotone, last = _token_events(path) if path is not None else (0, False, True, None)
    except Exception:
        path, count, keyed, monotone, last = None, 0, False, True, None
    column, used = _tokens_used(home, ctx.probe_thread)
    scratch = Path(tempfile.mkdtemp(prefix="car-mtok-"))
    try:
        documents = _generated_schema(ctx, scratch)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    methods = {text for _stem, document in documents for text in _strings(document) if text.startswith("thread/")}
    observed = {"rollout_read": path is not None, "token_events": count, "keys_present": keyed,
                "totals_monotone": monotone, "tokens_used_column": column,
                "tokens_used_matches": column and used is not None and used == last,
                "schema_read": bool(documents),
                "thread_token_read_listed": any("token" in method.lower() for method in methods)}
    if path is None or count < 2:
        return _blocked("the conversation's rollout holds fewer than two token counts: finish two turns in it, then "
                        "run mtok again", **observed)
    if keyed and monotone:
        return Verdict.PASS, observed, None
    return Verdict.FAIL, observed, "the token counts lack a kind or their totals decreased"


def _loaded_bucket(seconds) -> str:
    if seconds is None:
        return str(ObservedWord.NEVER)
    if seconds < 2:
        return str(ObservedWord.UNDER_2S)
    return str(ObservedWord.S2_TO_10 if seconds <= 10 else ObservedWord.OVER_10S)


def _mopen(ctx):
    """Opening a conversation for a message to be sent (open_to_send): the owner names a throwaway conversation the app
    does not hold. The harness lists what the app holds - and stops there if it holds this one - then opens the
    conversation's link once (codex_link.open_in_codex, one of the run's hands) and looks for it among what the app
    holds for up to _MOPEN_SECONDS. It records whether Codex was running, whether the link was handed over, and how long
    the load took as a bucket. Not loaded within ten seconds is a fail; within them, whether the window came to the
    front is the person's to confirm."""
    if not ctx.thread_given:
        return _blocked("name a throwaway conversation the app does not hold", loaded_listed=False)
    running = _app_running(ctx)
    with ctx.open() as session:
        held = _held(session, [ctx.probe_thread])
        if held is None:
            return _blocked("the conversations the app holds could not be listed", loaded_listed=False)
        if held:
            return _blocked("the app holds the throwaway conversation: quit and reopen the Codex app without opening "
                            "it, then run mopen again", loaded_listed=True, held_before=True)
        began = time.monotonic()
        opened = ctx.open_link(ctx.probe_thread)
        loaded = None
        while opened:
            if _held(session, [ctx.probe_thread]):
                loaded = time.monotonic() - began
                break
            if time.monotonic() - began >= _MOPEN_SECONDS:
                break
            time.sleep(_MOPEN_POLL_SECONDS)
    observed = {"loaded_listed": True, "held_before": False, "codex_running": running, "link_opened": opened,
                "loaded_seconds": _loaded_bucket(loaded)}
    if not opened:
        return _blocked("the conversation's link could not be handed to Windows", **observed)
    if loaded is None or loaded > 10:
        return Verdict.FAIL, observed, "the conversation was not loaded within ten seconds of opening its link"
    return _blocked("it loaded within ten seconds: confirm whether the Codex window came to the front, then set the "
                    "verdict", **observed)


def _account(reply):
    """(whether account/read names a signed-in account - None where it did not answer as one - and its plan word)."""
    if not isinstance(reply, dict) or "account" not in reply:
        return None, None
    account = reply.get("account")
    if not isinstance(account, dict):
        return False, None
    plan = account.get("planType", account.get("plan_type"))
    if not isinstance(plan, str):
        return True, None
    return True, plan.lower() if plan.lower() in {str(word) for word in PlanWord} else str(PlanWord.OTHER)


def _mal(ctx):
    """An account switch made outside the app (account_switch): with the app open and signed in, the person signs out
    with `codex logout` and back in with `codex login` in a terminal, with their own account. The harness reads the
    account (account/read: whether one is signed in, and its plan word - never the address) before, then every
    _MAL_POLL_SECONDS for up to _MAL_SECONDS, and records whether it saw the sign-out and the sign-in after it. That
    the running app shows the new sign-in without a restart is the person's to confirm."""
    with ctx.open() as session:
        present, plan = _account(session.call("account/read", {}))
        if not present:
            return _blocked("sign in to Codex first, then run mal again", account_read=present is not None,
                            signed_in_before=False)
        out = back = False
        after = None
        deadline = time.monotonic() + _MAL_SECONDS
        while time.monotonic() < deadline:
            time.sleep(_MAL_POLL_SECONDS)
            now, found = _account(session.call("account/read", {}))
            if now is False:
                out = True
            elif now and out:
                back, after = True, found
                break
    observed = {"account_read": True, "signed_in_before": True, "plan_before": plan, "signed_out_seen": out,
                "signed_in_again_seen": back, "plan_after": after}
    return _blocked("run `codex logout` and then `codex login` in a terminal within five minutes of starting this; "
                    "confirm the running app shows the new sign-in without a restart, then set the verdict",
                    **observed)


def _power_source(on_battery) -> str:
    if on_battery is None:
        return str(ObservedWord.UNKNOWN)
    return str(ObservedWord.BATTERY if on_battery else ObservedWord.AC)


def _kept(found, key, kind):
    value = found.get(key)
    return value if type(value) is kind else None


def _mwake(ctx):
    """Waking this PC for a reset (wake_for_reset): the harness reads - never writes - whether wake timers are allowed
    on mains and on battery (the active power plan's Allow wake timers: 0 off, 1 on, 2 important ones only), what powers
    the PC now, whether it has a lid and whether it sleeps in Modern Standby; then it sets one wake timer _MWAKE_SECONDS
    on (a waitable timer with resume) and waits for it while the person puts the PC to sleep. Its own process notes how
    long the PC slept and how late after the timer it woke. Pass where it slept and woke within _MWAKE_LATE seconds of
    the timer."""
    power = ctx.power_look()
    woke = ctx.wake_after(_MWAKE_SECONDS, _MWAKE_BOUND)
    slept, late = woke.get("slept_seconds"), woke.get("late_seconds")
    asleep = type(slept) in (int, float) and slept >= _MWAKE_SLEPT
    fired = woke.get("fired") is True
    observed = {"wake_timers_ac": _kept(power, "wake_ac", int), "wake_timers_dc": _kept(power, "wake_dc", int),
                "power_source": _power_source(_kept(power, "on_battery", bool)),
                "modern_standby": _kept(power, "modern_standby", bool), "lid_present": _kept(power, "lid_present", bool),
                "timer_set": woke.get("set") is True, "timer_fired": fired, "slept": asleep,
                "woke_on_time": fired and asleep and type(late) in (int, float) and late <= _MWAKE_LATE}
    if not observed["timer_set"]:
        return _blocked("the wake timer could not be set", **observed)
    if not asleep:
        return _blocked("put the PC to sleep within three minutes of starting this, then run mwake again", **observed)
    if observed["woke_on_time"]:
        return Verdict.PASS, observed, None
    return Verdict.FAIL, observed, "the PC slept and did not wake within two minutes of its wake timer"


def _feature(text, name):
    """(whether `codex features list` lists `name`, whether it is on - None where its line says neither)."""
    if not isinstance(text, str):
        return False, None
    for line in text.splitlines():
        words = line.replace("|", " ").split()
        if words and words[0] == name:
            states = {word.lower() for word in words[1:]}
            if states & {"true", "enabled", "on", "yes"}:
                return True, True
            if states & {"false", "disabled", "off", "no"}:
                return True, False
            return True, None
    return False, None


def _hook_words(documents) -> dict:
    """What Codex's generated schema says of hooks, as counts and memberships: the hook event names and whether Stop is
    one, the hook sources and whether a plugin is one, the Stop hook input's keys and which of _HOOK_INPUT_KEYS it has,
    and the decision words its output takes and whether block is one."""
    events, sources, keys, decisions = set(), set(), set(), set()
    for name, schema in _definitions(documents):
        letters = _letters(name)
        properties = schema.get("properties")
        properties = properties if isinstance(properties, dict) else {}
        if letters == "hookeventname":
            events |= _enum_words(schema)
        elif letters == "hooksource":
            sources |= _enum_words(schema)
        elif "stop" in letters and ("input" in letters or "payload" in letters):
            keys |= {_letters(key) for key in properties}
        elif "stop" in letters and "output" in letters:
            decisions |= _enum_words(properties.get("decision"))
    found = {"hook_event_names": len(events), "stop_event": "stop" in events, "hook_sources": len(sources),
             "plugin_source": "plugin" in sources, "stop_input_keys": len(keys),
             "decision_words": len(decisions), "decision_block": "block" in decisions}
    found.update({"input_" + key: _letters(key) in keys for key in _HOOK_INPUT_KEYS})
    return found


def _mhk(ctx):
    """The Stop hook's declaration (stop_hook_continuation), with Codex closed and nothing of the person's touched: on a
    scratch Codex home the harness makes and removes, `codex features list` (is plugin_hooks there, and on) and Codex's
    own generated schema (`codex app-server generate-json-schema`): the hook event names, the hook sources, the Stop
    hook input's keys and its output's decision words - counts and memberships, never a word of the schema. Pass where
    plugin hooks are a feature and Stop is one of their events."""
    import shutil
    import tempfile
    scratch = Path(tempfile.mkdtemp(prefix="car-mhk-"))
    try:
        documents = _generated_schema(ctx, scratch)
        features = ctx.scratch_cli(scratch / "codex-home", ("features", "list"))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    listed, on = _feature(features, "plugin_hooks")
    observed = dict({"features_read": features is not None, "plugin_hooks_listed": listed, "plugin_hooks_on": on,
                     "schema_read": bool(documents), "scratch_home": True}, **_hook_words(documents))
    if features is None or not documents:
        return _blocked("the engine could not be run on a scratch Codex home: check the Codex in force, then run mhk "
                        "again", **observed)
    if listed and observed["stop_event"]:
        return Verdict.PASS, observed, None
    return Verdict.FAIL, observed, "plugin hooks are not a feature, or Stop is not one of their events"


def _m4b(ctx):
    """A block from this edition's Stop hook (stop_hook_continuation's M4B, D-stop-hook.md), run by the person on a
    throwaway with the capability on - its declaration is written only then (control/hookplugin.py). The harness reads
    whether our declaration stands, whether the hooks Codex lists can be read and whether one of them runs our
    launcher - booleans only, no command or path recorded; that a failed turn's block continued it, where the history
    keeps the reason, that no console window appeared and that the trust prompt appeared once is the person's to see."""
    with ctx.open() as session:
        hooks = session.call("hooks/list", {"cwds": []})
    ours = ctx.stop_hook()
    commands = {command for command in (ours.get("commands") or ()) if isinstance(command, str)}
    observed = {"hooks_listed": isinstance(hooks, (dict, list)), "declared": ours.get("declared") is True,
                "ours_listed": bool(commands) and any(word in commands for word in _strings(hooks))}
    if not observed["declared"]:
        return _blocked("turn Continue inside the turn on in a throwaway installation, so its Stop hook is declared, "
                        "then run m4b again", **observed)
    return _blocked("with this edition's Stop hook declared, fail a turn: confirm the hook's block continued the turn, "
                    "where the history keeps its reason, that no console window appeared and the trust prompt appeared "
                    "once, then set the verdict", **observed)


PROBES = {
    Measurement.M1: _m1, Measurement.M2: _m2, Measurement.M2B: _m2b, Measurement.M3: _m3,
    Measurement.M4: _m4, Measurement.M5: _m5, Measurement.M6: _m6, Measurement.M7: _m7,
    Measurement.MH: _mh, Measurement.MA: _ma, Measurement.MW: _mw,
    Measurement.MP1: _mp1, Measurement.MP2: _mp2, Measurement.MP3: _mp3,
    Measurement.MU: _mu, Measurement.MN: _mn, Measurement.MR: _mr,
    Measurement.MQ: _mq, Measurement.ME: _me, Measurement.MS: _ms, Measurement.MK: _mk,
    Measurement.MT: _mt,
    Measurement.MIPC: _mipc, Measurement.MAWS: _maws, Measurement.MCLOUD: _mcloud,
    Measurement.M6B: _m6b, Measurement.MO: _mo, Measurement.MX: _mx, Measurement.MXA: _mxa, Measurement.MF: _mf,
    Measurement.M3B: _m3b, Measurement.MB: _mb, Measurement.MC1: _mc1, Measurement.MC2: _mc2,
    Measurement.MQO: _mqo, Measurement.MQP: _mqp, Measurement.MQG: _mqg,
    Measurement.MTOK: _mtok, Measurement.MOPEN: _mopen, Measurement.MAL: _mal, Measurement.MWAKE: _mwake,
    Measurement.MHK: _mhk, Measurement.M4B: _m4b,
}

# A conversation and a message id of no one's: the shape a call takes, never a real id. A probe
# that reaches a live Codex is run by the owner against a throwaway conversation whose id they
# put here; on their machine this constant is what a call carries when they have not.
_SAMPLE_THREAD = "00000000-0000-7000-8000-000000000000"
_SAMPLE_CLIENT_ID = "00000000-0000-7000-8000-000000000001"
_SAMPLE_M2B_CLIENT_ID = "00000000-0000-7000-8000-000000000002"


def _completed_status(events, thread, turn_id) -> str | None:
    """The status a `turn/completed` for this thread's turn reported, if one is among `events`,
    in the engine's own closed word (TurnCompletedNotification: `params.turn.status`) - never any
    text the turn carried. With no turn id known, any turn of this thread counts."""
    from codex_auto_resume.codex.values import _turn_status as core_status
    for event in events:
        if not isinstance(event, dict) or event.get("method") != "turn/completed":
            continue
        params = event.get("params")
        if not isinstance(params, dict) or params.get("threadId") != thread:
            continue
        turn = params.get("turn")
        if not isinstance(turn, dict) or (turn_id is not None and turn.get("id") != turn_id):
            continue
        status = turn.get("status")
        return core_status(status) if isinstance(status, str) else "other"
    return None


def probe(ctx) -> tuple:
    """Run one measurement's probe, turning a protocol that could not be reached into a blocked
    verdict with a coded note rather than an exception. Whether the owner pointed it at a real
    conversation is added to the observation here, as a boolean, so every probe records it the
    same way and none has to carry the thread through."""
    try:
        verdict, observed, note = PROBES[ctx.measurement](ctx)
    except AdapterError as exc:
        if hasattr(exc, "method"):
            # Codex was reached and said no to a call this measurement needs: the capability's
            # premise does not hold on this Codex, which is a fail, not a measurement that could
            # not run. The method and Codex's error code are recorded; its words never are.
            return (Verdict.FAIL, ctx.given({"refused_method": exc.method, "refusal_code": exc.code}),
                    "Codex refused a call this measurement needs")
        return Verdict.BLOCKED, {"thread_given": ctx.thread_given}, "not reached: %s" % type(exc).__name__
    except (EvidenceUnavailable, SessionRefused) as exc:
        return Verdict.BLOCKED, {"thread_given": ctx.thread_given}, "not reached: %s" % type(exc).__name__
    return verdict, ctx.given(observed), note


def run(measurement, *, session_factory=None, launcher=None, backend=None, versions=None,
        clock=time.time, directory=None, thread=None, may_spend=False, cli=None, ipc=None, hands=None) -> dict:
    """Run one measurement and write its record. Returns a small summary of what was recorded.

    `versions` is the build, Codex and Windows the record belongs to; when it is not given they
    are read here (the product's manifest, the backend's engine version, this Windows). Every
    external effect is a factory the caller passes, so a test drives this with fakes.

    `thread` is an optional real throwaway conversation the owner points the measurement at. It
    is validated as a Codex thread id and used in the calls the probe makes; it is never written
    into the record, which keeps only whether one was given. `may_spend` is the person's second yes
    that MR may spend one real reset credit (v0.6.14); no other measurement reads it.

    A record that cannot say which Codex it measured is not written, and nothing is run for it:
    a measurement speaks for one Codex version - a pass counts only there, as the statement's
    warnings read it (arming.warnings_for) - and "unknown" would speak for every version at once.
    """
    measurement = Measurement(measurement)
    if thread is not None and not _threads_valid(measurement, thread):
        raise EvidenceUnavailable("the conversation id is not a Codex thread id")
    versions = dict(versions or _versions(backend))
    if versions.get("codex_version") in (None, "", "unknown"):
        raise EvidenceUnavailable("the Codex version this would measure could not be read")
    ctx = Context(measurement, session_factory=session_factory, launcher=launcher,
                  backend=backend, versions=versions, thread=thread, may_spend=may_spend, cli=cli, ipc=ipc,
                  hands=hands)
    verdict, observed, note = probe(ctx)
    record = evidence.build(measurement, verdict, observed,
                            product_version=versions.get("product_version", "0.0.0"),
                            codex_version=versions.get("codex_version", "unknown"),
                            windows_build=versions.get("windows_build", "10.0.0"),
                            recorded_at=_iso(clock()), note=note)
    written = evidence.write(record, directory=directory)
    return {"measurement": str(measurement), "verdict": str(verdict),
            "recorded": str(written), "observed": dict(observed)}


def _threads_valid(measurement, thread) -> bool:
    """Whether `thread` names what `measurement` takes: one Codex thread id - or, for MQP (v0.6.17), two to four
    different ones, comma-separated."""
    if not isinstance(thread, str):
        return False
    if measurement != Measurement.MQP:
        return is_uuid(thread)
    parts = thread.split(",")
    return 2 <= len(parts) <= _MQP_MOST and len(set(parts)) == len(parts) and all(is_uuid(part) for part in parts)


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


def live_backend(paths=None):
    """The Codex the installation at `paths` drives, checked, so its `engine_version` is the
    version a record says it measured: the one its watcher told the plug, else the one the
    watcher would find - the `codex_exe` setting, or discovery (codex/inuse.py)."""
    return inuse.backend(paths)


def live_session_factory(paths, backend=None):
    """A factory that opens a real one-turn session against the installed Codex, restricted to a
    measurement's own methods. Wired by the bridge; never reached by a test.

    Its correctness against a live engine is what the owner proves by running the measurements -
    the alpha exists for that - so it is thin and does the discovery core already does. `backend`
    is the one the run's record reads its Codex version from, so the session and the record are
    of the same Codex."""
    def factory(measurement, home=None):
        used = backend if backend is not None else live_backend(paths)
        if home is not None:
            # MB (v0.6.16-beta.4): the same Codex on a scratch home the harness made, never the person's.
            from codex_auto_resume.codex.transport import Backend
            used = Backend(home, used.codex_exe)
        # M6B (v0.6.16-beta.4): the headless turn's server starts as the route starts it (codex/headless.py).
        from .codex.headless import HEADLESS_CONFIG
        if measurement == Measurement.M6B:
            return Session(used, measurement, config=HEADLESS_CONFIG)
        return Session(used, measurement)

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


# MAWS/MCLOUD run the engine's own help; MIPC opens the Desktop's pipe. Both bounds are its own.
_CLI_HELP_SECONDS = 20
_IPC_PIPE = r"\\.\pipe\codex-ipc"
_IPC_FRAME_HEADER = 4            # the 4-byte little-endian length prefix (sybxxx/codex-auto-retry)
# How long the look waits for that header: a server that answers only once a client has written its first frame
# writes nothing to one that never writes, so the read is cancelled after this and the look says no_answer.
_IPC_WAIT_MS = 2000


def live_cli(backend=None, paths=None):
    """The real CLI-help runner (v0.6.16-beta.3, MAWS/MCLOUD): the installed Codex run with the given
    arguments, read-only, windowless, its stdout answered or None where it could not run or exited
    non-zero. Never a turn, never a write. A test wires a fake and this is never reached."""
    import subprocess as S
    from codex_auto_resume.win.kernel import NO_WINDOW

    def cli(arguments):
        used = backend if backend is not None else live_backend(paths)
        try:
            result = S.run([str(used.codex_exe), *arguments], stdout=S.PIPE, stderr=S.DEVNULL,
                           text=True, encoding="utf-8", errors="replace", timeout=_CLI_HELP_SECONDS,
                           creationflags=NO_WINDOW, shell=False)
        except Exception:
            return None
        return result.stdout if result.returncode == 0 else None

    return cli


def live_ipc():
    """The real IPC-pipe look (v0.6.16-beta.3, MIPC): it opens the Desktop's own named pipe for reading
    only (GENERIC_READ, overlapped), waits at most _IPC_WAIT_MS for the 4-byte frame header, cancels the read
    if none came, and closes the pipe - it writes nothing, starts nothing, interrupts nothing.
    {exists, opened, frame_read, no_answer}, each a boolean. A test wires a fake instead."""
    def ipc():
        found = {"exists": False, "opened": False, "frame_read": False, "no_answer": False}
        try:
            return _ipc_look(found)
        except Exception:
            return found
    return ipc


def _ipc_look(found):
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                wintypes.DWORD, wintypes.HANDLE]
    k32.CreateEventW.restype = wintypes.HANDLE
    k32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    k32.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p]
    k32.GetOverlappedResult.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD),
                                        wintypes.BOOL]
    k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k32.WaitForSingleObject.restype = wintypes.DWORD
    k32.CancelIoEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]

    class OVERLAPPED(ctypes.Structure):
        _fields_ = [("Internal", ctypes.c_void_p), ("InternalHigh", ctypes.c_void_p), ("Offset", wintypes.DWORD),
                    ("OffsetHigh", wintypes.DWORD), ("hEvent", wintypes.HANDLE)]

    GENERIC_READ, OPEN_EXISTING, FILE_FLAG_OVERLAPPED = 0x80000000, 3, 0x40000000
    NOT_FOUND, IO_PENDING, WAIT_OBJECT_0 = (2, 3), 997, 0
    invalid = wintypes.HANDLE(-1).value
    # Opened for reading alone; closed below whatever happens. Nothing is ever written to the pipe.
    from .codex import ipc as channel
    pipe = k32.CreateFileW(_IPC_PIPE, GENERIC_READ, 0, None, OPEN_EXISTING,
                           FILE_FLAG_OVERLAPPED | channel.SECURITY_SQOS, None)
    if pipe in (None, invalid):
        if ctypes.get_last_error() not in NOT_FOUND:
            found["exists"] = True              # the pipe is there but could not be opened now
        return found
    if not channel.server_trusted(channel.server_pid(k32, pipe)):
        # v0.6.18 (S5): served by a process that is not this account's own - looked at no further.
        k32.CloseHandle(pipe)
        found["exists"] = True
        return found
    found["exists"] = found["opened"] = True
    event = k32.CreateEventW(None, True, False, None)
    try:
        if not event:
            return found
        overlapped = OVERLAPPED(hEvent=event)
        header = ctypes.create_string_buffer(_IPC_FRAME_HEADER)
        count = wintypes.DWORD(0)
        started = k32.ReadFile(pipe, header, _IPC_FRAME_HEADER, None, ctypes.byref(overlapped))
        if not started and ctypes.get_last_error() != IO_PENDING:
            return found
        if k32.WaitForSingleObject(event, _IPC_WAIT_MS) != WAIT_OBJECT_0:
            # Nothing came: the read is cancelled, and waited out, before its buffer goes.
            k32.CancelIoEx(pipe, ctypes.byref(overlapped))
            k32.GetOverlappedResult(pipe, ctypes.byref(overlapped), ctypes.byref(count), True)
            found["no_answer"] = True
            return found
        if k32.GetOverlappedResult(pipe, ctypes.byref(overlapped), ctypes.byref(count), False):
            found["frame_read"] = count.value == _IPC_FRAME_HEADER
        return found
    finally:
        if event:
            k32.CloseHandle(event)
        k32.CloseHandle(pipe)


# The v0.6.19 probes' hands (MOPEN, MWAKE, MTOK, MHK). The engine on a scratch home is given this long to answer.
_SCRATCH_CLI_SECONDS = 60
# The active power plan's Allow wake timers: the sleep subgroup and the setting, as powercfg names them.
_SUB_SLEEP = "238c9fa8-0aad-41ed-83f4-97be242c8f20"
_RTC_WAKE = "bd3b718a-0680-4d9d-8ab2-e1d2b4ac806d"
# SYSTEM_POWER_CAPABILITIES (GetPwrCapabilities): the byte that says the PC has a lid, and the one for Modern Standby.
_LID_PRESENT_BYTE, _AOAC_BYTE = 2, 20


def live_hands(backend=None, paths=None) -> dict:
    """The real hands of the v0.6.19 probes, built from the Codex the record names: a conversation's link opened
    (MOPEN, codex_link.open_in_codex - the app's own link, handed to Windows' handler), the power settings read and a
    wake timer set and waited for (MWAKE), and the engine run on a scratch Codex home the probe made (MTOK, MHK) -
    windowless, its stdout answered, never the person's home. Each is called only by its probe, when a person runs it;
    a test wires fakes, and never reaches these."""
    def open_link(thread):
        from codex_auto_resume import codex_link
        link = codex_link.codex_thread_uri(thread)
        return link is not None and codex_link.open_in_codex(link) is True

    def scratch_cli(home, arguments):
        import os
        import subprocess as S
        from codex_auto_resume.win.kernel import NO_WINDOW
        used = backend if backend is not None else live_backend(paths)
        try:
            result = S.run([str(used.codex_exe), *arguments], stdin=S.DEVNULL, stdout=S.PIPE, stderr=S.DEVNULL,
                           text=True, encoding="utf-8", errors="replace", timeout=_SCRATCH_CLI_SECONDS,
                           creationflags=NO_WINDOW, shell=False, env=dict(os.environ, CODEX_HOME=str(home)))
        except Exception:
            return None
        return result.stdout if result.returncode == 0 else None

    def stop_hook():
        from .codex import inuse
        from .control import hookplugin
        if paths is None:
            return {}
        return {"declared": hookplugin.present(paths, inuse.home(paths)),
                "commands": sorted(hookplugin.ours(paths))}

    return {"open_link": open_link, "power": _power_look, "wake_after": _wake_after, "scratch_cli": scratch_cli,
            "stop_hook": stop_hook}


def _guid(text):
    import ctypes

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort), ("Data3", ctypes.c_ushort),
                    ("Data4", ctypes.c_ubyte * 8)]
    value = uuid.UUID(text)
    found = GUID(value.time_low, value.time_mid, value.time_hi_version)
    found.Data4[:] = list(value.bytes[8:])
    return found


def _power_look() -> dict:
    """What MWAKE reads of this PC's power, read-only: Allow wake timers on mains and on battery (the active plan's
    index, 0, 1 or 2), whether it runs on battery now, whether it has a lid, and whether it sleeps in Modern Standby.
    A value it cannot read is left out."""
    import ctypes
    from ctypes import wintypes
    found = {}
    powrprof = ctypes.WinDLL("powrprof")
    kernel = ctypes.WinDLL("kernel32")
    scheme = ctypes.c_void_p()
    if powrprof.PowerGetActiveScheme(None, ctypes.byref(scheme)) == 0:
        try:
            sub, setting = _guid(_SUB_SLEEP), _guid(_RTC_WAKE)
            for key, read in (("wake_ac", powrprof.PowerReadACValueIndex), ("wake_dc", powrprof.PowerReadDCValueIndex)):
                value = wintypes.DWORD()
                if read(None, scheme, ctypes.byref(sub), ctypes.byref(setting), ctypes.byref(value)) == 0:
                    found[key] = int(value.value)
        finally:
            kernel.LocalFree(scheme)

    class SYSTEM_POWER_STATUS(ctypes.Structure):
        _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                    ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                    ("BatteryLifeTime", wintypes.DWORD), ("BatteryFullLifeTime", wintypes.DWORD)]
    status = SYSTEM_POWER_STATUS()
    if kernel.GetSystemPowerStatus(ctypes.byref(status)) and status.ACLineStatus in (0, 1):
        found["on_battery"] = status.ACLineStatus == 0
    capabilities = ctypes.create_string_buffer(256)
    if powrprof.GetPwrCapabilities(capabilities):
        found["lid_present"] = capabilities.raw[_LID_PRESENT_BYTE] != 0
        found["modern_standby"] = capabilities.raw[_AOAC_BYTE] != 0
    return found


def _wake_after(seconds, bound) -> dict:
    """MWAKE's one wake timer: a waitable timer `seconds` on with resume (SetWaitableTimer's fResume), waited for at
    most `bound` seconds, then cancelled and closed. Whether it was set and fired, how long the PC slept meanwhile - the
    wall clock's time less the interrupt time, which stands still while it sleeps - and how late after its time it
    fired. Nothing else is changed."""
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateWaitableTimerW.restype = wintypes.HANDLE
    kernel.CreateWaitableTimerW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.SetWaitableTimer.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_longlong), wintypes.LONG,
                                        ctypes.c_void_p, ctypes.c_void_p, wintypes.BOOL]
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CancelWaitableTimer.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]

    def unbiased():
        value = ctypes.c_ulonglong()
        kernel.QueryUnbiasedInterruptTime(ctypes.byref(value))
        return value.value / 10_000_000

    found = {"set": False, "fired": False, "slept_seconds": 0.0, "late_seconds": None}
    timer = kernel.CreateWaitableTimerW(None, True, None)
    if not timer:
        return found
    try:
        due = ctypes.c_longlong(-int(seconds * 10_000_000))      # relative, in 100-nanosecond steps
        wall, interrupt = time.time(), unbiased()
        found["set"] = bool(kernel.SetWaitableTimer(timer, ctypes.byref(due), 0, None, None, True))
        if not found["set"]:
            return found
        found["fired"] = kernel.WaitForSingleObject(timer, int(bound * 1000)) == 0
        spent_wall, spent_interrupt = time.time() - wall, unbiased() - interrupt
        found["slept_seconds"] = max(0.0, spent_wall - spent_interrupt)
        found["late_seconds"] = spent_wall - seconds if found["fired"] else None
        return found
    finally:
        kernel.CancelWaitableTimer(timer)
        kernel.CloseHandle(timer)


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
