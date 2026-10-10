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
from .vocabulary import Measurement, NoteCode, SpendOutcome, Verdict

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
                 versions=None, redactor=None, thread=None, may_spend=False):
        self.measurement = Measurement(measurement)
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


def _await_turn(session, thread, turn_id, seconds):
    """Follow the session's notifications until the turn completes or `seconds` pass. Returns
    the turn's closed status word, or None when it did not say it ended."""
    deadline = time.monotonic() + seconds
    while True:
        status = _completed_status(session.drain_events(), thread, turn_id)
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


PROBES = {
    Measurement.M1: _m1, Measurement.M2: _m2, Measurement.M2B: _m2b, Measurement.M3: _m3,
    Measurement.M4: _m4, Measurement.M5: _m5, Measurement.M6: _m6, Measurement.M7: _m7,
    Measurement.MH: _mh, Measurement.MA: _ma, Measurement.MW: _mw,
    Measurement.MP1: _mp1, Measurement.MP2: _mp2, Measurement.MP3: _mp3,
    Measurement.MU: _mu, Measurement.MN: _mn, Measurement.MR: _mr,
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
        clock=time.time, directory=None, thread=None, may_spend=False) -> dict:
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
    if thread is not None and not is_uuid(thread):
        raise EvidenceUnavailable("the conversation id is not a Codex thread id")
    versions = dict(versions or _versions(backend))
    if versions.get("codex_version") in (None, "", "unknown"):
        raise EvidenceUnavailable("the Codex version this would measure could not be read")
    ctx = Context(measurement, session_factory=session_factory, launcher=launcher,
                  backend=backend, versions=versions, thread=thread, may_spend=may_spend)
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
    def factory(measurement):
        return Session(backend if backend is not None else live_backend(paths), measurement)

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
