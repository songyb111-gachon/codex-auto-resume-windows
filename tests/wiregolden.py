"""The wire goldens: what the bridge and the MCP server answer, for every command and every tool.

The Settings window and the Codex panel read the bridge's (`controlcli`) and the MCP server's
(`mcpserver`) answers by field name, and v0.6.5 moves every module those answers are built in.
A field renamed on the way passes every Python test that reads it back through the same renamed
code, and the window, which reads the old name, draws a blank. So the answers are pinned here,
as files, from the code as it was before anything moved:

* `tests/golden/bridge/<command>.json` - one per bridge command (`controlcli.PLAIN` and
  `WITH_ARGUMENT`), each a few requests in order, valid ones and representative bad ones, and
  the reply to each; `_framing.json` holds whole request lines and the reply lines `serve`
  writes for them: malformed lines, ids, commands and arguments, and a line it does not answer.
* `tests/golden/mcp/<tool>.json` - one per MCP tool, `tools-list.json` for the tool list itself,
  and `_protocol.json` for the JSON-RPC envelope around them.

`tests/test_wire_goldens.py` regenerates every file on each run and compares it byte for byte,
and `tests/test_consumer_fields.py` holds the window's and the panel's reads to them.

How they are made. Each file is asked of a fresh scratch installation - the one the screenshot
envelope asks (`build/make_screenshots.py`, `pinned_installation`): the same settings, the same
records written by the product's own store, the same synthetic Codex home, the same clock, pid
and language, and the same registry stand-in that reads "nothing registered" and refuses every
write. Only what the envelope never needs is added here, and all of it is golden-only:

* one more record, a recovery that ran out of attempts, so "give attempts back" has something
  to give back (`_seed_exhausted`);
* no Codex engine to discover: `LOCALAPPDATA` points into the scratch directory, so a live
  compatibility check finds none on every machine instead of running this machine's `codex`;
* no process at all. `subprocess.Popen` refuses (`ProcessRefused`, a BaseException, so the bridge
  cannot turn it into a polite refusal) for the whole run; the two cases that need one get a
  stand-in instead - a watcher launch whose "process" has already exited, and a registry
  refresh whose bootstrap "printed" its one line;
* the Run key as a dictionary for the `startup` command, through `startup`'s own install,
  uninstall and read, so switching start-at-sign-in on and off is answered without a registry;
* the MCP server can reach neither the registry refresh nor the import (`RefreshReached`).

Nothing here starts a watcher or any other process, writes the registry, or reads the user's own
Codex home, installation or engine.

Canonical where needed, and only there. The answers are the wire's text with the four pinned
directories written as `<scratch>`, `<checkout>`, `<temp>` and `<profile>` (as the envelope writes
them) and the product version as `<version>`, so a release is not a wire change. Every reply line
is checked as it was written before it is parsed: one line, ending in `\\n`, exactly what
`json.dumps(reply, ensure_ascii=False)` writes (so UTF-8 as characters, the default separators,
keys in the order the code built them). The files keep that key order; they are indented so a
changed field reads as a one-line diff.

After a deliberate wire change - never to make a red test green - regenerate them from the
repository root and review the diff:

    python -X utf8 tests/wiregolden.py --write

Without `--write` it only checks, prints the files that differ and exits 1 if any does.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "tests" / "golden"
# The files that are not one command's or one tool's.
BRIDGE_FRAMING = "_framing"
MCP_PROTOCOL = "_protocol"
MCP_TOOL_LIST = "tools-list"

for _entry in (ROOT / "src", ROOT / "build"):
    if str(_entry) not in sys.path:
        sys.path.insert(0, str(_entry))

import make_screenshots as generator  # noqa: E402 - build/, found through the path above

# The records the golden installation has, by the index `seed_window_state` gave them.
THREADS = generator.WINDOW_THREADS + ("55555555-5555-7555-8555-555555555555",)
T1, T2, T3, T4, T5 = THREADS


def key(index: int) -> str:
    """The interruption id `seed_window_state` gives record `index` (and `_seed_exhausted`, 9)."""
    return "%x" % index * 64


WAITING_RESET, WAITING_BACKOFF, RECOVERED, EXHAUSTED = key(7), key(8), key(6), key(9)
NO_SUCH = "f" * 64


class ProcessRefused(BaseException):
    """What starting any process raises while a golden is made. Not an Exception, so the bridge
    cannot turn it into a polite refusal and hide it: it stops the generator and the test."""


class RefreshReached(BaseException):
    """What the MCP server reaching the registry refresh or import would raise."""


class WireChanged(AssertionError):
    """A reply line was not written the way the wire writes it."""


# ------------------------------------------------------------------------------ the cases
class Case:
    """One request of a golden, in order after the ones before it in the same installation.

    `argument` may be a function of the scratch workspace (a path in it). `watching` says whether
    the watcher's mutex is held, as it is in the pictures; a change of it starts a new
    installation. `using` is a function of the workspace returning a context manager for the one
    stand-in the case needs.
    """

    def __init__(self, name, argument=None, *, watching=True, using=None):
        self.name, self.argument, self.watching, self.using = name, argument, watching, using

    def value(self, workspace):
        return self.argument(workspace) if callable(self.argument) else self.argument


@contextmanager
def _startup_in_memory(_workspace):
    """The Run key as a dictionary, behind `startup`'s own writers and reader."""
    from codex_auto_resume import startup

    held = {}

    def install(command):
        changed = held.get("value") != command
        held["value"] = command
        return changed

    with patch.object(startup, "install", side_effect=install), \
            patch.object(startup, "uninstall", side_effect=lambda: held.pop("value", None) is not None), \
            patch.object(startup, "current_value", side_effect=lambda: held.get("value")):
        yield


@contextmanager
def _launch_that_exits(_workspace):
    """The one start `start-watcher` makes, answered by a "process" that has already exited.

    Nothing is started: the watcher's mutex stays free, so the launch is reported the way a
    watcher that stopped again straight away is reported."""
    class Exited:
        def __init__(self, *_args, **_kwargs):
            pass

        def poll(self):
            return 1

    with patch.object(subprocess, "Popen", Exited):
        yield


@contextmanager
def _watcher_does_not_let_go(_workspace):
    """A stop asked of a watcher that holds the mutex through the whole wait, without the wait.

    The mutex is held by the envelope's helper thread, which no stop event reaches, so the
    answer is the one the full ten seconds give; only the waiting is left out."""
    from codex_auto_resume import control

    with patch.object(control, "WATCHER_STOP_TIMEOUT", 0.0):
        yield


def _bootstrap(line: str, code: int):
    """The registry refresh's bootstrap as a stand-in that "printed" `line` and exited `code`.

    `SystemRoot` points at a stand-in PowerShell in the scratch directory, so the answer does
    not depend on where this machine keeps its own - which is never started either way."""
    @contextmanager
    def using(workspace):
        shell = workspace / "windows" / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        shell.parent.mkdir(parents=True, exist_ok=True)
        shell.write_bytes(b"")

        def run(arguments, **_kwargs):
            return subprocess.CompletedProcess(arguments, code, stdout=line, stderr=None)

        with patch.dict(os.environ, {"SystemRoot": str(workspace / "windows")}), \
                patch.object(subprocess, "run", run):
            yield
    return using


def _registry_document(workspace, *, sequence_offset=1, name="codex_compat.json", **changes) -> str:
    """A registry document for `compat-import`: the bundled baseline, one sequence on, in force
    at the pinned clock."""
    from codex_auto_resume import compatio

    document = json.loads(Path(compatio.BUNDLED).read_text(encoding="utf-8"))
    document.update(sequence=document["sequence"] + sequence_offset,
                    published_at="2027-01-01T00:00:00Z", expires_at="2027-03-31T00:00:00Z")
    document.update(changes)
    target = workspace / "downloads" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return str(target)


def _text_file(workspace, name, text) -> str:
    target = workspace / "downloads" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return str(target)


LONG_CUSTOM = "x" * 2001
KOREAN_CUSTOM = "중단된 작업을 이어서 진행해 주세요."

# Every bridge command, and what each golden asks it, in order.
BRIDGE_CASES = {
    "status": [Case("the status line of a watched installation")],
    "settings": [Case("the stored settings")],
    "describe": [Case("the settings schema the Settings page is built from")],
    "defaults": [Case("every setting back to its default")],
    "pending": [Case("what is waiting, with the names Codex gives the conversations")],
    "pending-all": [Case("every record, finished ones too, without names")],
    "start-watcher": [
        Case("a watcher already holds the mutex"),
        Case("launched with no watcher running, and it stopped again straight away",
             watching=False, using=_launch_that_exits)],
    "stop-watcher": [
        Case("no watcher is running", watching=False),
        Case("the watcher does not let go before the wait is over", using=_watcher_does_not_let_go)],
    "strings": [Case("the interface vocabulary, in English")],
    "history": [Case("the history, newest first")],
    "clear-history": [Case("finished recoveries hidden"), Case("nothing left to hide")],
    "dashboard": [Case("the Overview, Pending and History in one round trip")],
    "cancel-all": [Case("every pending recovery cancelled"), Case("nothing left to cancel")],
    "update": [
        Case("one setting changed", {"notifications": False}),
        Case("a Korean Custom message, stored and answered as UTF-8",
             {"continuation_style": "custom", "custom_message_mode": "global",
              "custom_message": KOREAN_CUSTOM}),
        Case("a value out of range is refused", {"max_recovery_attempts": 0}),
        Case("a setting that does not exist is refused", {"no_such_setting": True})],
    "enabled": [
        Case("paused", {"enabled": False}),
        Case("on again", {"enabled": True}),
        Case("the string \"false\" is refused, not read as true", {"enabled": "false"}),
        Case("a missing flag is refused", {})],
    "startup": [
        Case("registered to start at sign-in", {"enabled": True}, using=_startup_in_memory),
        Case("unregistered", {"enabled": False}, using=_startup_in_memory),
        Case("a string is refused", {"enabled": "true"}, using=_startup_in_memory)],
    "cancel": [
        Case("a waiting recovery cancelled", {"interruption_id": WAITING_BACKOFF}),
        Case("the same one again: already finished", {"interruption_id": WAITING_BACKOFF}),
        Case("an id that is not one", {"interruption_id": "not-an-id"}),
        Case("no such interruption", {"interruption_id": NO_SUCH})],
    "reset-budget": [
        Case("an exhausted recovery given its attempts back", {"interruption_id": EXHAUSTED}),
        Case("a recovery still waiting has not been exhausted", {"interruption_id": WAITING_RESET}),
        Case("a recovered one has already finished", {"interruption_id": RECOVERED}),
        Case("an id that is not one", {"interruption_id": 7})],
    "retry-now": [
        Case("a usage limit whose reset is still ahead", {"interruption_id": WAITING_RESET}),
        Case("a backoff brought forward", {"interruption_id": WAITING_BACKOFF}),
        Case("a recovered one has already finished", {"interruption_id": RECOVERED}),
        Case("no such interruption", {"interruption_id": NO_SUCH})],
    "timeline": [
        Case("one recovery, from detection to its outcome", {"interruption_id": RECOVERED}),
        Case("no such interruption", {"interruption_id": NO_SUCH}),
        Case("no id at all", {})],
    "statistics": [
        Case("the week the Statistics page opens on", {"days": 7}),
        Case("all time", {}),
        Case("zero days is refused", {"days": 0}),
        Case("a string is refused", {"days": "7"})],
    "thread-enabled": [
        Case("one conversation switched off", {"thread_id": T1, "enabled": False}),
        Case("and on again", {"thread_id": T1, "enabled": True}),
        Case("an id in capitals is refused", {"thread_id": T1.upper(), "enabled": True}),
        Case("a missing flag is refused", {"thread_id": T1})],
    "cancel-thread": [
        Case("a conversation switched off and what it had waiting cancelled", {"thread_id": T2}),
        Case("not a conversation id", {"thread_id": "not-a-uuid"})],
    "diagnostics": [
        Case("a bundle written", lambda workspace: {"path": str(workspace / "diagnostics.json")}),
        Case("the same name again is refused",
             lambda workspace: {"path": str(workspace / "diagnostics.json")}),
        Case("a name that is not .json is refused",
             lambda workspace: {"path": str(workspace / "diagnostics.txt")})],
    "preview-continuation": [
        Case("the first reason, under the stored settings", {"category": "usage_limit"}),
        Case("a style chosen and not saved", {"category": "network_transient",
                                              "changes": {"continuation_style": "detailed"}}),
        Case("a Custom message that could not be stored is reported beside the preview",
             {"category": "usage_limit",
              "changes": {"continuation_style": "custom", "custom_message_mode": "global",
                          "custom_message": LONG_CUSTOM}}),
        Case("a kind that is never recovered", {"category": "unclassified"}),
        Case("a setting that does not exist", {"category": "usage_limit",
                                               "changes": {"no_such_setting": 1}})],
    "interruption-recovery": [
        Case("one task switched off",
             {"interruption_id": WAITING_RESET, "thread_id": T1, "enabled": False}),
        Case("a task that belongs to another conversation",
             {"interruption_id": WAITING_RESET, "thread_id": T2, "enabled": True}),
        Case("a finished task", {"interruption_id": RECOVERED, "thread_id": T3, "enabled": True}),
        Case("a string flag is refused",
             {"interruption_id": WAITING_RESET, "thread_id": T1, "enabled": "on"})],
    "compatibility": [
        Case("the watcher's report, before any watcher has written one", {}),
        Case("checked live, on a machine with no Codex engine", {"live": True}),
        Case("live must be true or false", {"live": "yes"})],
    "compat-import": [
        Case("a valid document becomes the cache",
             lambda workspace: {"path": _registry_document(workspace), "origin": "file"}),
        Case("an older document is a rollback",
             lambda workspace: {"path": _registry_document(workspace, sequence_offset=0,
                                                           name="older.json")}),
        Case("a document that fails validation",
             lambda workspace: {"path": _text_file(workspace, "broken.json", "{\"format\": 1}")}),
        Case("a file that is not .json",
             lambda workspace: {"path": _text_file(workspace, "registry.txt", "{}")}),
        Case("no file named", {}),
        Case("an origin that is neither main nor file",
             lambda workspace: {"path": _registry_document(workspace), "origin": "web"})],
    "compat-refresh": [
        Case("the bootstrap refreshed the data", {},
             using=_bootstrap("  Asking...\ncompatibility: refreshed 2\n", 0)),
        Case("the bootstrap's line and its exit code disagree", {},
             using=_bootstrap("compatibility: refreshed 2\n", 13))],
}

# What the `serve` loop answers before any command runs: the requests it refuses as requests.
BYTE_ORDER_MARK = chr(0xFEFF)
FRAMING_CASES = [
    ("a line that is not JSON", "{not json"),
    ("a request that is not an object", "[1, 2]"),
    ("an id that is not an integer", '{"id": "1", "command": "status"}'),
    ("a boolean id", '{"id": true, "command": "status"}'),
    ("no id: the reply says null", '{"command": "timeline", "argument": {"interruption_id": "x"}}'),
    ("a command that does not exist", '{"id": 2, "command": "format-disk"}'),
    ("an argument that is not an object", '{"id": 3, "command": "timeline", "argument": [7]}'),
    ("an argument given as JSON text",
     '{"id": 4, "command": "timeline", "argument": "{\\"interruption_id\\": \\"x\\"}"}'),
    ("an argument that is JSON text but not JSON", '{"id": 5, "command": "timeline", "argument": "{"}'),
    ("a byte order mark before the request",
     BYTE_ORDER_MARK + '{"id": 6, "command": "timeline", "argument": {"interruption_id": "x"}}'),
    ("a blank line is not answered", "   "),
]

# Every MCP tool, and what each golden asks it, in order.
MCP_CASES = {
    "open_settings": [Case("the panel's snapshot", {})],
    "get_status": [Case("the status, with the registry's summary under watcher", {})],
    "list_pending": [
        Case("what is waiting", {}),
        Case("finished ones too", {"include_finished": True}),
        Case("a string flag is refused", {"include_finished": "yes"})],
    "update_settings": [
        Case("one setting changed", {"notifications": False}),
        Case("Custom text is not writable from Codex", {"custom_message": KOREAN_CUSTOM}),
        Case("nor a reason's own Custom text", {"custom_message_usage_limit": KOREAN_CUSTOM}),
        Case("the engine's location is not offered", {"codex_exe": "C:\\elsewhere\\codex.exe"}),
        Case("nothing named", {}),
        Case("a value out of range is refused", {"max_recovery_attempts": 0})],
    "restore_default_settings": [Case("every setting back to its default", {})],
    "pause_auto_recovery": [Case("paused", {})],
    "resume_auto_recovery": [Case("on again", {})],
    "cancel_recovery": [
        Case("a waiting recovery cancelled", {"interruption_id": WAITING_BACKOFF}),
        Case("no such interruption", {"interruption_id": NO_SUCH}),
        Case("the id is required", {})],
    "reset_recovery_budget": [
        Case("an exhausted recovery given its attempts back", {"interruption_id": EXHAUSTED}),
        Case("a recovery still waiting has not been exhausted", {"interruption_id": WAITING_RESET})],
    "start_watcher": [Case("a watcher already holds the mutex", {})],
    "retry_now": [
        Case("a usage limit whose reset is still ahead", {"interruption_id": WAITING_RESET}),
        Case("a recovered one has already finished", {"interruption_id": RECOVERED})],
    "disable_conversation_recovery": [
        Case("one conversation switched off", {"thread_id": T1}),
        Case("not a conversation id", {"thread_id": "not-a-uuid"})],
    "enable_conversation_recovery": [Case("one conversation switched back on", {"thread_id": T1})],
    "get_recovery_statistics": [
        Case("the week", {"days": 7}),
        Case("all time", {}),
        Case("zero days is refused", {"days": 0})],
    "get_recovery_timeline": [
        Case("one recovery, from detection to its outcome", {"interruption_id": RECOVERED}),
        Case("no such interruption", {"interruption_id": NO_SUCH})],
    "clear_recovery_history": [Case("finished recoveries hidden", {})],
    "preview_recovery_message": [
        Case("the first reason, under the stored settings", {"category": "usage_limit"}),
        Case("a language and a style for the preview alone",
             {"category": "network_transient",
              "changes": {"continuation_language": "ko", "continuation_style": "detailed"}}),
        Case("Custom text is not previewable from Codex",
             {"category": "usage_limit", "changes": {"custom_message": KOREAN_CUSTOM}}),
        Case("a kind that is never recovered", {"category": "unclassified"})],
}

# The JSON-RPC envelope around the tools.
PROTOCOL_CASES = [
    ("initialize", {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18"}}),
    ("initialize, asking for a protocol it does not speak",
     {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "1999-01-01"}}),
    ("ping", {"jsonrpc": "2.0", "id": 1, "method": "ping"}),
    ("resources/list", {"jsonrpc": "2.0", "id": 1, "method": "resources/list"}),
    ("resources/templates/list", {"jsonrpc": "2.0", "id": 1, "method": "resources/templates/list"}),
    ("prompts/list", {"jsonrpc": "2.0", "id": 1, "method": "prompts/list"}),
    ("a resource that does not exist",
     {"jsonrpc": "2.0", "id": 1, "method": "resources/read", "params": {"uri": "ui://elsewhere"}}),
    ("a tool that does not exist",
     {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "send_message"}}),
    ("arguments that are not an object",
     {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
      "params": {"name": "get_status", "arguments": []}}),
    ("an argument the tool does not take",
     {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
      "params": {"name": "get_status", "arguments": {"force": True}}}),
    ("params that are not an object", {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": []}),
    ("a method that does not exist", {"jsonrpc": "2.0", "id": 1, "method": "tools/run"}),
    ("not JSON-RPC 2.0", {"jsonrpc": "1.0", "id": 1, "method": "ping"}),
    ("a notification is not answered", {"jsonrpc": "2.0", "method": "notifications/initialized"}),
    ("a batch", [{"jsonrpc": "2.0", "id": 1, "method": "ping"},
                 {"jsonrpc": "2.0", "id": 2, "method": "prompts/list"}]),
    ("a line that is not JSON", "{not json"),
]


# ------------------------------------------------------------------------- installation
@contextmanager
def _no_process():
    def refused(*_args, **_kwargs):
        raise ProcessRefused("a wire golden never starts a process")

    with patch.object(subprocess, "Popen", refused):
        yield


def _seed_exhausted(paths) -> None:
    """Record 9: a server error on a conversation of its own that ran out of attempts, and whose
    conversation was switched off - so "give attempts back" has something to give back, with
    the note it gives when the conversation stays off."""
    from codex_auto_resume.store import Store

    now = generator.ENVELOPE_NOW
    detected = now - 2 * 3600
    record = {"thread_id": T5, "turn_id": "0a1b2c3d-0301-7000-8000-%012d" % 9,
              "completed_at": detected - 1, "started_at": detected - 240, "ordinal": 2,
              "interruption_id": EXHAUSTED, "reset_at": None, "limit_type": "server_5xx",
              "uncertain": False, "category": "server_5xx"}
    with Store(paths.state_dir) as store:
        store.register(record, detected, state="waiting_backoff", next_retry_at=detected + 60)
        store.update(EXHAUSTED, at=detected + 120, state="retry_budget_exhausted",
                     recovery_attempts=4, no_progress_count=0)
        store.set_thread_enabled(T5, False, actor="gui", at=detected + 130)


@contextmanager
def installation(*, watching=True, mcp=False):
    """A fresh golden installation: (workspace, the `Control` it answers for, the rewriting)."""
    from codex_auto_resume import l10n

    with tempfile.TemporaryDirectory() as name, ExitStack() as stack:
        workspace = Path(name)
        surface = stack.enter_context(generator.pinned_installation(workspace, watching=watching))
        # Inside the pinned installation's environment, which is put back whole after it.
        os.environ[l10n.ENV_LANG] = "en"
        engines = workspace / "localappdata"
        engines.mkdir()
        os.environ["LOCALAPPDATA"] = str(engines)
        stack.enter_context(_no_process())
        if mcp:
            from codex_auto_resume import compatio

            def reached(*_args, **_kwargs):
                raise RefreshReached("the MCP server reached the registry refresh or import")

            stack.enter_context(patch.object(compatio, "run_refresh", reached))
            stack.enter_context(patch.object(compatio, "import_document", reached))
        _seed_exhausted(surface.paths)
        yield workspace, surface, _rewriting(workspace)


def _rewriting(workspace) -> list:
    from codex_auto_resume import config

    version = config.version()
    marker = re.compile(r"(?<![0-9.])" + re.escape(version) + r"(?!\.?[0-9])")
    return generator.workspace_spellings(workspace) + [(marker, "<version>")]


def canonical(value, rewriting):
    return generator._canonical(value, rewriting)


def _framed(written: str, what: str) -> list:
    """The lines `written` holds, each checked as the wire writes it, parsed."""
    if written and not written.endswith("\n"):
        raise WireChanged("%s: the last reply line does not end in a line feed" % what)
    parsed = []
    for line in written.splitlines(keepends=True):
        value = json.loads(line)
        if json.dumps(value, ensure_ascii=False) + "\n" != line:
            raise WireChanged("%s: a reply line is not what json.dumps(reply, ensure_ascii=False) "
                              "writes - the wire's encoding, separators or escaping changed" % what)
        parsed.append(value)
    return parsed


def _groups(cases):
    """Consecutive cases that share an installation."""
    group = []
    for case in cases:
        if group and case.watching != group[-1].watching:
            yield group
            group = []
        group.append(case)
    if group:
        yield group


def _render(document) -> str:
    return json.dumps(document, ensure_ascii=False, indent=2) + "\n"


# ------------------------------------------------------------------------------- bridge
def _bridge_reply(surface, command, argument, what):
    line = json.dumps({"id": 1, "command": command, "argument": argument}) + "\n"
    lines = _framed(generator.serve_lines(surface, line), what)
    if len(lines) != 1 or list(lines[0]) != ["id", "reply"] or lines[0]["id"] != 1:
        raise WireChanged("%s: the reply is not one {\"id\", \"reply\"} line for the request's id" % what)
    return lines[0]["reply"]


def bridge_document(command: str) -> str:
    cases = []
    for group in _groups(BRIDGE_CASES[command]):
        with installation(watching=group[0].watching) as (workspace, surface, rewriting):
            for case in group:
                argument = case.value(workspace)
                what = "%s: %s" % (command, case.name)
                with (case.using(workspace) if case.using else ExitStack()):
                    reply = _bridge_reply(surface, command, argument, what)
                cases.append({"case": case.name, "argument": canonical(argument, rewriting),
                              "reply": canonical(reply, rewriting)})
    return _render({"command": command, "cases": cases})


def framing_document() -> str:
    cases = []
    with installation() as (_workspace, surface, rewriting):
        for name, line in FRAMING_CASES:
            replies = _framed(generator.serve_lines(surface, line + "\n"), "serve: " + name)
            # The mark is written by name: an invisible character in a file is a trap for
            # whoever edits it next.
            shown = line.replace(BYTE_ORDER_MARK, "<U+FEFF>")
            cases.append({"case": name, "request": shown, "replies": canonical(replies, rewriting)})
    return _render({"cases": cases})


def bridge_commands() -> tuple:
    from codex_auto_resume import controlcli

    return tuple(controlcli.PLAIN) + tuple(controlcli.WITH_ARGUMENT)


# ---------------------------------------------------------------------------------- MCP
def _mcp_responses(surface, message, what) -> list:
    from codex_auto_resume import mcpserver

    line = message if isinstance(message, str) else json.dumps(message)
    out = io.StringIO()
    mcpserver.Server(surface, io.StringIO(line + "\n"), out).serve()
    return _framed(out.getvalue(), what)


def _call(name, arguments) -> dict:
    return {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": name, "arguments": arguments}}


def mcp_document(tool: str) -> str:
    cases = []
    for group in _groups(MCP_CASES[tool]):
        with installation(watching=group[0].watching, mcp=True) as (workspace, surface, rewriting):
            for case in group:
                arguments = case.value(workspace)
                with (case.using(workspace) if case.using else ExitStack()):
                    responses = _mcp_responses(surface, _call(tool, arguments),
                                               "%s: %s" % (tool, case.name))
                if len(responses) != 1:
                    raise WireChanged("%s: %s: not one response" % (tool, case.name))
                cases.append({"case": case.name, "arguments": canonical(arguments, rewriting),
                              "response": canonical(responses[0], rewriting)})
    return _render({"tool": tool, "cases": cases})


def tool_list_document() -> str:
    with installation(mcp=True) as (_workspace, surface, rewriting):
        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        responses = _mcp_responses(surface, request, "tools/list")
        return _render({"method": "tools/list", "request": request,
                        "response": canonical(responses[0], rewriting)})


def protocol_document() -> str:
    cases = []
    with installation(mcp=True) as (_workspace, surface, rewriting):
        for name, message in PROTOCOL_CASES:
            responses = _mcp_responses(surface, message, "MCP: " + name)
            cases.append({"case": name, "request": message,
                          "responses": canonical(responses, rewriting)})
    return _render({"cases": cases})


def mcp_tools() -> tuple:
    from codex_auto_resume import mcpserver

    return tuple(tool["name"] for tool in mcpserver.TOOLS)


# ---------------------------------------------------------------------------------- all
def expected_files() -> dict:
    """Relative path -> how to make it, for every golden there must be."""
    missing = sorted(set(bridge_commands()) - set(BRIDGE_CASES))
    missing += sorted(set(mcp_tools()) - set(MCP_CASES))
    if missing:
        raise LookupError("no golden cases for %s; add them to tests/wiregolden.py" % ", ".join(missing))
    files = {"bridge/%s.json" % BRIDGE_FRAMING: framing_document}
    for command in bridge_commands():
        files["bridge/%s.json" % command] = lambda command=command: bridge_document(command)
    files["mcp/%s.json" % MCP_PROTOCOL] = protocol_document
    files["mcp/%s.json" % MCP_TOOL_LIST] = tool_list_document
    for tool in mcp_tools():
        files["mcp/%s.json" % tool] = lambda tool=tool: mcp_document(tool)
    return files


def generate(names=None) -> dict:
    """Relative path -> the golden text the code makes now, for `names` (default: all)."""
    files = expected_files()
    return {name: files[name]() for name in (names if names is not None else files)}


def recorded(name: str):
    """A golden as committed, line endings aside (the checkout decides those), or None."""
    path = GOLDEN / name
    return path.read_text(encoding="utf-8") if path.is_file() else None


def main(argv=None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    write = "--write" in arguments
    made = generate()
    differ = sorted(name for name, text in made.items() if recorded(name) != text)
    stale = sorted(str(path.relative_to(GOLDEN)).replace(os.sep, "/")
                   for path in GOLDEN.rglob("*.json")
                   if str(path.relative_to(GOLDEN)).replace(os.sep, "/") not in made)
    if write:
        for name in differ:
            target = GOLDEN / name
            target.parent.mkdir(parents=True, exist_ok=True)
            # CRLF, as every text file in this checkout is (.gitattributes); stored as LF.
            with target.open("w", encoding="utf-8", newline="\r\n") as stream:
                stream.write(made[name])
        for name in stale:
            (GOLDEN / name).unlink()
        print("wrote %d, removed %d of %d goldens" % (len(differ), len(stale), len(made)))
        return 0
    for name in differ:
        print("differs: %s" % name)
    for name in stale:
        print("no longer a command or tool: %s" % name)
    return 1 if differ or stale else 0


if __name__ == "__main__":
    sys.exit(main())
