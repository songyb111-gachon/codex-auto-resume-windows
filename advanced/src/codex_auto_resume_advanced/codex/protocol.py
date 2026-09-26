# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Which App Server methods each measurement may call, and the one-turn session that calls them.

Core's finite helper (codex/appserver.py) may call three methods and no others, and
tests/test_privacy_claims.py holds it to that list. A measurement needs more - to read the
loaded threads, set a goal, add a queue item, resume a thread for one headless turn - so those
method names are here, in the advanced package, and never in core. `MEASUREMENT_METHODS` says
which measurement may call which, and a session opened for a measurement refuses every method
that measurement did not declare, even one another measurement is allowed. `ADVANCED_METHODS`
is their union, the whole of what this edition may ever ask beyond core's three.

`Session` is the helper the design calls SessionProtocol: opened for one turn against a Codex
whose thread no process is holding, it follows that turn's notifications, answers every request
Codex makes of it - approvals, elicitations, input - with that request's own refusal from Codex's
schema (`DECLINE_ANSWERS`), never an accepting one, answers the requests that touch
authentication or attestation with an error and never with what they ask, refuses to call those
methods whatever the allow-list says, and always ends with `thread/unsubscribe`. It is a thin
client over `codex app-server --stdio`; the harness drives it through an injected factory, so
the tests use a fake and no test opens a real Codex.
Its own correctness against a live engine is what the owner proves by running the measurements
(that is what M6 records) - the alpha exists for exactly that.
"""
from __future__ import annotations

from collections import Counter
import copy
import json
from pathlib import Path
import queue
import subprocess as S
import threading
import time

from codex_auto_resume.codex.appserver import PROTOCOL_METHODS
from codex_auto_resume.win.kernel import NO_WINDOW

from ..vocabulary import Measurement

# The methods each measurement is allowed to call, beyond `initialize`. A measurement that reads
# nothing over the protocol - MW proves the WMI escape, and works from the launcher and the
# heartbeat - declares none, so its session (if one is ever opened) may call nothing.
MEASUREMENT_METHODS = {
    Measurement.M1: ("thread/loaded/list", "thread/queue/list"),
    Measurement.M2: ("thread/loaded/list", "thread/goal/get", "thread/goal/set"),
    Measurement.M3: ("thread/queue/add", "thread/queue/list"),
    Measurement.M4: ("hooks/list",),
    Measurement.M5: ("thread/loaded/list", "thread/queue/list"),
    Measurement.M6: ("thread/resume", "turn/start", "turn/interrupt", "thread/unsubscribe"),
    Measurement.M7: ("thread/queue/add", "thread/queue/list"),
    Measurement.MH: ("thread/loaded/list",),
    Measurement.MA: ("account/read",),
    Measurement.MW: (),
}

# Everything this edition may ever ask beyond core's three. A method not here is one no
# measurement declared, and a session refuses it whatever it was asked for.
ADVANCED_METHODS = frozenset(method for methods in MEASUREMENT_METHODS.values()
                             for method in methods)

# Never asked, whatever the allow-list says: the account's own routes and attestation. The
# product never authenticates by a route of its own and never mints an attestation (B11); a
# measurement that reads the account (MA) reads its state and no more.
FORBIDDEN_METHODS = frozenset({
    "account/login/start", "account/login", "account/logout",
    "account/chatgptAuthTokens/refresh", "chatgptAuthTokens/refresh", "attestation/generate",
    "item/tool/call",
})

# The requests Codex may make of a client that this session answers, each with the refusal Codex's
# own schema gives it (codex-cli 0.158.0-alpha.2.1, `app-server generate-json-schema`: the
# ServerRequest methods and each one's *Response type). Answering one with a JSON-RPC error, as the
# first version did, is not a decline Codex knows - and the method names it listed
# ("commandExecution/approval", ...) were never ones Codex sends, so M6 counted nothing.
# A refusal is a constant: nothing Codex sends chooses it or shapes it, and `_grants_nothing` is
# checked again before one is written.
_REJECTION = "declined by codex-auto-resume"
DECLINE_ANSWERS = {
    # v2 CommandExecutionApprovalDecision / FileChangeApprovalDecision: "decline" - the agent is
    # told no and continues the turn ("cancel" would also interrupt it).
    "item/commandExecution/requestApproval": {"decision": "decline"},
    "item/fileChange/requestApproval": {"decision": "decline"},
    # v2 PermissionsRequestApprovalResponse: a GrantedPermissionProfile - granting nothing, for
    # this turn only, is the refusal (the schema has no decision word for it).
    "item/permissions/requestApproval": {"permissions": {}, "scope": "turn"},
    # v1 ReviewDecision: "denied" - not run, and the session continues and tries something else.
    "execCommandApproval": {"decision": {"denied": {"rejection": _REJECTION}}},
    "applyPatchApproval": {"decision": {"denied": {"rejection": _REJECTION}}},
    # ToolRequestUserInputResponse: no answer to any question.
    "item/tool/requestUserInput": {"answers": {}},
    # McpServerElicitationAction: "decline", with no content.
    "mcpServer/elicitation/request": {"action": "decline", "content": None},
}
DECLINED_REQUESTS = frozenset(DECLINE_ANSWERS)

# Every word the schema's response types grant something with: a decision that runs, allows,
# persists a rule or widens a policy. None of them is ever in anything this session sends.
ACCEPTING_WORDS = frozenset({
    "accept", "acceptForSession", "acceptWithExecpolicyAmendment", "applyNetworkPolicyAmendment",
    "approved", "approved_for_session", "approved_execpolicy_amendment",
    "approved_mcp_policy_amendment", "network_policy_amendment", "allow", "session",
})

# A request this session answers with nothing but an error: every method not named above, and
# above all those it must never answer - a token refresh, an attestation, a dynamic tool call -
# which stay refused as they always were.
_NOT_ANSWERED = {"code": -32601, "message": "declined by codex-auto-resume"}


def _words(value):
    """Every key and every string inside `value`."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _words(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _words(item)
    elif isinstance(value, str):
        yield value


def _grants_nothing(refusal) -> bool:
    """Whether a reply grants nothing: no accepting word anywhere in it, no permission, no answer,
    no elicited content, and no scope wider than this turn."""
    if not isinstance(refusal, dict):
        return False
    if any(word in ACCEPTING_WORDS for word in _words(refusal)):
        return False
    return (refusal.get("permissions", {}) == {} and refusal.get("answers", {}) == {}
            and refusal.get("content") is None and refusal.get("scope", "turn") == "turn")


def reply_to(request) -> dict:
    """The one reply this client sends to a request Codex makes of it: the schema's own refusal
    for an approval, a permission, an input or an elicitation request, and an error for anything
    else. Only the method's name chooses between them; nothing else in the request is read."""
    ident = request.get("id") if isinstance(request, dict) else None
    method = request.get("method") if isinstance(request, dict) else None
    if isinstance(method, str) and method not in FORBIDDEN_METHODS and method in DECLINE_ANSWERS:
        refusal = copy.deepcopy(DECLINE_ANSWERS[method])
        if _grants_nothing(refusal):
            return {"id": ident, "result": refusal}
    return {"id": ident, "error": dict(_NOT_ANSWERED)}


class SessionRefused(RuntimeError):
    """A method a session was asked for that its measurement did not declare, or that is
    forbidden outright. A static reason only - never a value, a path or a conversation."""


def _refused_by_codex(method, code):
    """Codex answered, and its answer was no: a measurement's result, not a failure to reach it.
    Raised as core's AdapterError, so a caller that knows only that still stops, and carrying the
    method and Codex's numeric error code - nothing Codex wrote in words. M3 on codex-cli
    0.158.0-alpha.2.1 (2026-09-26) was the case: an empty thread/queue/add is refused with -32600,
    and the harness first recorded that as "not reached"."""
    from codex_auto_resume.codex.errors import AdapterError

    class RefusedByCodex(AdapterError):
        pass
    refusal = RefusedByCodex("protocol_request_failed")
    refusal.method = method
    refusal.code = code if isinstance(code, int) and not isinstance(code, bool) else None
    return refusal


def methods_for(measurement) -> frozenset:
    """The methods `measurement` may call, `initialize` always among them and a forbidden method
    never, whatever the table says."""
    allowed = set(MEASUREMENT_METHODS[Measurement(measurement)]) - FORBIDDEN_METHODS
    return frozenset(allowed | {"initialize", "initialized"})


class Session:
    """A one-turn App Server helper for one measurement, over `codex app-server --stdio`.

    `backend` is core's `codex.transport.Backend`, for the argv and the environment core uses
    (analytics and telemetry off); `measurement` fixes the methods this session may call. It is
    a context manager: it initialises, checks the home and platform as core's helper does, and
    on exit unsubscribes from anything it subscribed to and shuts the process. Nothing here
    sends a continuation - only core does (A1); a session reads, sets a goal or adds a queue
    item, and observes.
    """
    def __init__(self, backend, measurement):
        self.backend = backend
        self.measurement = Measurement(measurement)
        self.allowed = methods_for(self.measurement)
        self.process = None
        self.sequence = 0
        self.responses = queue.Queue(maxsize=128)
        self.events = queue.Queue(maxsize=1024)
        # What was declined with a refusal and what was refused with an error, counted by the
        # method Codex asked - in memory only; a record keeps the total and never the names.
        self.declined = Counter()
        self.refused = Counter()
        self._subscribed = []
        self.write_lock = threading.Lock()
        self.count_lock = threading.Lock()

    def __enter__(self):
        self.backend._compatible()
        self.process = S.Popen(self.backend._argv() + ["app-server", "--stdio"],
                               stdin=S.PIPE, stdout=S.PIPE, stderr=S.DEVNULL, text=True,
                               encoding="utf-8", errors="replace", bufsize=1,
                               creationflags=NO_WINDOW, close_fds=True, shell=False,
                               cwd=str(self.backend.codex_home), env=self.backend._environment())
        try:
            self.reader = threading.Thread(target=self._read, daemon=True)
            self.reader.start()
            from codex_auto_resume.config import version as product_version
            from codex_auto_resume.codex.errors import AdapterError
            response = self.call("initialize", {"clientInfo": {"name": "codex_auto_resume",
                                                               "version": product_version()},
                                                "capabilities": {"experimentalApi": True}})
            if not isinstance(response, dict) or Path(response.get("codexHome", "")).resolve() != self.backend.codex_home:
                raise AdapterError("protocol_home_mismatch")
            self._write({"method": "initialized"})
            return self
        except BaseException:
            self.__exit__()
            raise

    def _write(self, payload):
        with self.write_lock:
            self.process.stdin.write(json.dumps(payload, ensure_ascii=False, allow_nan=False) + "\n")
            self.process.stdin.flush()

    def _read(self):
        try:
            while True:
                line = self.process.stdout.readline(1024 * 1024 + 1)
                if not line or len(line) > 1024 * 1024:
                    return
                try:
                    value = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(value, dict):
                    continue
                if "id" in value and "method" in value:
                    # A request from Codex: answer it with its refusal (or an error), then count
                    # it by what it asked.
                    reply = reply_to(value)
                    self._write(reply)
                    method = value.get("method")
                    with self.count_lock:
                        (self.declined if "result" in reply else self.refused)[
                            method if isinstance(method, str) else "?"] += 1
                elif "id" in value and ("result" in value or "error" in value):
                    try:
                        self.responses.put_nowait(value)
                    except queue.Full:
                        return
                elif "method" in value:
                    try:
                        self.events.put_nowait(value)
                    except queue.Full:
                        pass
        except (OSError, ValueError):
            return

    def call(self, method, params=None):
        if method not in self.allowed:
            raise SessionRefused("method not permitted for this measurement")
        from codex_auto_resume.codex.errors import AdapterError
        self.sequence += 1
        sequence = self.sequence
        # Every request carries `params`, an empty object where there are none: codex-cli
        # 0.158.0-alpha.2.1 refuses thread/loaded/list without it ("missing field `params`",
        # -32600), which made M1's probe fail on its own malformed call (2026-09-26).
        request = {"id": sequence, "method": method, "params": {} if params is None else params}
        if method == "thread/resume" and isinstance(params, dict) and params.get("threadId"):
            self._subscribed.append(params["threadId"])
        try:
            self._write(request)
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                response = self.responses.get(timeout=max(0.01, deadline - time.monotonic()))
                if response.get("id") != sequence:
                    continue
                if "error" in response:
                    error = response.get("error")
                    raise _refused_by_codex(method, error.get("code") if isinstance(error, dict) else None)
                if method == "thread/unsubscribe" and isinstance(params, dict):
                    # Unsubscribed by the caller: the exit need not do it again.
                    self._subscribed = [thread for thread in self._subscribed
                                        if thread != params.get("threadId")]
                return response.get("result")
        except (queue.Empty, OSError, ValueError):
            raise AdapterError("protocol_unavailable") from None
        raise AdapterError("protocol_timeout")

    def declined_count(self) -> int:
        """How many requests were answered with their refusal so far."""
        with self.count_lock:
            return sum(self.declined.values())

    def drain_events(self) -> list:
        """Every notification seen so far, taken from the queue. Codes and shapes only - the
        caller reads whether a status changed or a turn ended, never any text they carried."""
        seen = []
        while True:
            try:
                seen.append(self.events.get_nowait())
            except queue.Empty:
                return seen

    def __exit__(self, *unused):
        process = self.process
        if process is None:
            return
        try:
            for thread_id in self._subscribed:
                if "thread/unsubscribe" in self.allowed:
                    try:
                        self.call("thread/unsubscribe", {"threadId": thread_id})
                    except Exception:
                        pass
            if process.stdin:
                try:
                    process.stdin.close()
                except OSError:
                    pass
            try:
                process.wait(timeout=4)
            except S.TimeoutExpired:
                process.terminate()      # only our own one-turn helper
                process.wait(timeout=4)
        finally:
            if getattr(self, "reader", None) is not None:
                self.reader.join(timeout=1)
            if process.stdout:
                process.stdout.close()
