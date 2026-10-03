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
  compatibility check finds none on every machine instead of running this machine's `codex`.
  The one exception is a case marked `engine=True`, which reads - never checks live - the
  watcher's report the envelope writes for the pictures' Codex (`seed_compatibility`, with its
  stand-in engine that answers two questions and starts nothing). It is there so the reply the
  Dashboard draws Reported's counts from (v0.6.10) is held byte for byte, counts and all;
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
# The wire's goldens are in these two folders. A file directly in tests/golden is another
# test's - tests/golden/defaults-v0.6.10.json is tests/test_defaults_golden.py's - and is never
# this script's to rewrite or remove.
WIRE_FOLDERS = ("bridge", "mcp")


def wire_goldens() -> set:
    """Every wire golden on disk, as a path relative to GOLDEN with forward slashes."""
    return {str(path.relative_to(GOLDEN)).replace(os.sep, "/")
            for folder in WIRE_FOLDERS for path in (GOLDEN / folder).rglob("*.json")}

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
    the watcher's mutex is held, as it is in the pictures; `engine` whether the installation has
    the envelope's stand-in Codex and the watcher's report about it; a change of either starts a
    new installation. `using` is a function of the workspace returning a context manager for the
    one stand-in the case needs.
    """

    def __init__(self, name, argument=None, *, watching=True, engine=False, using=None):
        self.name, self.argument, self.watching, self.using = name, argument, watching, using
        self.engine = engine

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


def _held(thread):
    """A conversation that asks first (v0.6.11), so what it has waiting is held for a person and
    "let it continue" has something to let go. Written by the product's own store, as the rest of
    the installation is, and left as it is for the cases after it."""
    @contextmanager
    def using(workspace):
        from codex_auto_resume import config
        from codex_auto_resume.store import Store

        with Store(config.Paths(workspace / "home").state_dir) as store:
            store.set_thread_tier(thread, "ask_first", generator.ENVELOPE_NOW, actor="gui")
        yield
    return using


def _filed(thread, folder):
    """A conversation the synthetic Codex home files under a folder (v0.6.11), so Let this project
    resume and Hold this project for me have a project to read. The home's own table, written as
    Codex writes it, and left as it is for the cases after it."""
    @contextmanager
    def using(workspace):
        import sqlite3

        connection = sqlite3.connect(workspace / "codex" / "state_5.sqlite")
        try:
            with connection:
                connection.execute("UPDATE threads SET cwd=? WHERE id=?", (folder, thread))
        finally:
            connection.close()
        yield
    return using


def _managed(**values):
    """An administrator's policy keys in force for this one case (v0.6.11, managed.py): a stand-in for
    the one function that asks Windows for them, so what the window is sent while they are set is held
    here too. Nothing is read from the registry."""
    @contextmanager
    def using(_workspace):
        from codex_auto_resume import managed
        from codex_auto_resume.control import policy

        with patch.object(policy, "managed_policy", return_value=managed.Managed(**values)):
            yield
    return using


NIGHT = {"quiet_hours_start": "22:00", "quiet_hours_end": "07:00", "quiet_hours_days": "weekdays"}


def _state_access(word):
    """What Windows says of the state folder's access list, for this one case (v0.6.11, win/acl.py): a
    stand-in for the one function that asks, so the answer is the same on every machine."""
    @contextmanager
    def using(_workspace):
        from codex_auto_resume.win import acl

        with patch.object(acl, "state_access", return_value=word):
            yield
    return using


def _postponed(key, thread):
    """A task a person postponed by an hour (v0.6.11), so Don't postpone has something to take away.
    Through the product's own store, and left as it is for the cases after it."""
    @contextmanager
    def using(workspace):
        from codex_auto_resume import config
        from codex_auto_resume.store import Store

        with Store(config.Paths(workspace / "home").state_dir) as store:
            store.postpone(key, thread, generator.ENVELOPE_NOW + 3600, generator.ENVELOPE_NOW, actor="gui")
        yield
    return using


def _logged(workspace):
    """A few lines of this product's own log, as logbook's formatter writes them, and one it does not."""
    from codex_auto_resume import config

    paths = config.Paths(workspace / "home")
    paths.logs_dir.mkdir(parents=True, exist_ok=True)
    paths.log_file.write_text("[2026-09-27 10:00:00] auto-resume is enabled\n"
                              "[2026-09-27 10:01:00] thread %s: waiting for reset\n"
                              "a line the formatter never writes\n"
                              "[2026-09-27 10:02:00] watcher stopped\n" % T1, encoding="utf-8")
    return {"query": "thread"}


def _plugin_copy(edition_word):
    """A copy of this plugin in the scratch Codex home's plugin cache, of `edition_word` - as `codex
    plugin add` leaves one - for this one case (v0.6.11, edition.cached_copy). Written under the
    envelope's own CODEX_HOME and removed after, so no real Codex home is ever read."""
    @contextmanager
    def using(_workspace):
        import shutil
        from codex_auto_resume import edition

        root = Path(os.environ["CODEX_HOME"]) / "plugins" / "cache" / edition.MARKETPLACE / edition.PLUGIN
        copy = root / "0.0.0"
        (copy / "src" / "codex_auto_resume").mkdir(parents=True)
        if edition_word == "advanced":
            (copy / "src" / edition.ADVANCED_PACKAGE).mkdir()
            (copy / "src" / edition.ADVANCED_PACKAGE / "__init__.py").write_text("", encoding="utf-8")
        try:
            yield
        finally:
            shutil.rmtree(root.parent, ignore_errors=True)
    return using


def _launch_that_comes_up(context):
    """The one start `start_watcher` makes, answered by a "process" that holds the scratch
    installation's watcher mutex from the moment it is made - as a watcher that came up does - with
    this process in the job `context` describes (windows.process_context), so the reply never
    depends on what the machine making the golden runs it in. Nothing is started: the mutex is held
    by the envelope's helper thread (`_watcher_mutex_held`), and let go when the case is done."""
    @contextmanager
    def using(workspace):
        from codex_auto_resume import config, windows

        paths = config.Paths(workspace / "home")
        with ExitStack() as held:
            class CameUp:
                pid = 4242

                def __init__(self, *_args, **_kwargs):
                    held.enter_context(generator._watcher_mutex_held(paths))

                def poll(self):
                    return None

            with patch.object(subprocess, "Popen", CameUp), \
                    patch.object(windows, "process_context", return_value=dict(context)):
                yield
    return using


# What `windows.process_context` said of the MCP server on Codex 26.915 (v0.6.9-alpha), and what it
# says of a process in no job at all.
KILL_ON_CLOSE_JOB = {"in_job": True, "kill_on_close": True, "breakaway_ok": False,
                     "silent_breakaway_ok": False, "packaged": False}
NO_JOB = {"in_job": False, "kill_on_close": False, "breakaway_ok": False,
          "silent_breakaway_ok": False, "packaged": False}


@contextmanager
def _watcher_does_not_let_go(_workspace):
    """A stop asked of a watcher that holds the mutex through the whole wait, without the wait.

    The mutex is held by the envelope's helper thread, which no stop event reaches, so the
    answer is the one the full ten seconds give; only the waiting is left out."""
    # `control/watcher.py` is where `await_stopped` reads the wait; the front re-exports the
    # name but nothing reads it there, so patching the front would wait the full ten seconds.
    from codex_auto_resume.control import watcher as control_watcher

    with patch.object(control_watcher, "WATCHER_STOP_TIMEOUT", 0.0):
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
    at the pinned clock.

    The frozen baseline, not the live file. The installation these answers are recorded in
    already reads the frozen one (`pinned_installation`), and this read the live file beside it
    - so each import's sequence was the live sequence plus one, and publishing compatibility data
    moved the golden. On 2026-09-25 that refused the first publish since the goldens were made:
    sequence 3 made `compat-import` answer 4 where 3 was recorded."""
    import frozen_registry

    document = json.loads(Path(frozen_registry.FROZEN).read_text(encoding="utf-8"))
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


class _PowerPort:
    """win/powerdown.py as a golden needs it: whether each action is offered - `reasons` maps an action
    to why it is not - and never an action. So `power-action` answers the same on every machine."""

    def __init__(self, reasons):
        self.reasons = dict(reasons)

    def available(self, action):
        reason = self.reasons.get(action)
        return (True, None) if reason is None else (False, reason)

    def act(self, action):
        raise ProcessRefused("a wire golden never puts its machine to sleep")


def _power(reasons=(), *, arm=None, end=None, show=None, **managed_values):
    """The power action's port stood in for, for this one case (v0.6.12), and - in this order, through the
    product's own control layer, and left as they are for the cases after it - an arming, the end of its
    first batch, and what the watcher shows of the next. `managed_values` are an administrator's keys."""
    @contextmanager
    def using(workspace):
        from codex_auto_resume import config, control, managed
        from codex_auto_resume.control import policy, poweraction

        with ExitStack() as stack:
            stack.enter_context(patch.object(poweraction.PowerActionMixin, "power_port", _PowerPort(reasons)))
            if managed_values:
                stack.enter_context(patch.object(policy, "managed_policy",
                                                 return_value=managed.Managed(**managed_values)))
            layer = control.Control(config.Paths(workspace / "home"))
            if arm is not None:
                layer.arm_power_action(dict(arm))
            if end is not None:
                layer.power_batch_end(layer.read_power_action()[1]["armed"]["nonce"], end)
            if show is not None:
                layer.power_show(layer.read_power_action()[1]["armed"]["nonce"], dict(show))
            yield
    return using


SLEEP_ONCE = {"action": "sleep", "after": "all_recovered", "repeat": "once", "grace_minutes": 5}
SHUT_DOWN_ALWAYS = {"action": "shut_down", "after": "any_end", "repeat": "always", "grace_minutes": 30}
NO_HIBERNATION = {"hibernate": "hibernate_off"}
NONE_FOR_THIS_ACCOUNT = {action: "no_privilege" for action in ("sleep", "hibernate", "shut_down")}

LONG_CUSTOM = "x" * 2001
KOREAN_CUSTOM = "중단된 작업을 이어서 진행해 주세요."

# Every bridge command, and what each golden asks it, in order.
BRIDGE_CASES = {
    "status": [Case("the status line of a watched installation"),
               # v0.6.11: paused by an administrator, with the keys in force named.
               Case("while an administrator's policy keys pause recovery and hold two settings",
                    using=_managed(disable_auto_resume=True, disable_update_check=True,
                                   max_recovery_attempts=2, quiet_hours=(NIGHT,))),
               # v0.6.12: the power action, said only while its file exists - here armed every time,
               # after a batch a person stopped, and counting down.
               Case("the power action counting down, after a batch a person stopped",
                    using=_power(arm=SHUT_DOWN_ALWAYS, end="skipped",
                                 show={"phase": "grace", "waiting_for": None,
                                       "grace_until": generator.ENVELOPE_NOW + 1800}))],
    "settings": [Case("the stored settings")],
    "describe": [Case("the settings schema the Settings page is built from"),
                 Case("greyed where an administrator's policy key decides",
                      using=_managed(max_recovery_attempts=2, force_observe_only=True, quiet_hours=(NIGHT,)))],
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
    # v0.6.8: the Dashboard in front says a person has seen every failure so far. Twice, because
    # the second call is the one that must not move the mark backwards or write the file again.
    "failure-seen": [
        Case("every failure so far marked as seen"),
        Case("again, with nothing new to see")],
    "cancel-all": [Case("every pending recovery cancelled"), Case("nothing left to cancel")],
    # v0.6.11: Diagnostics - who Windows lets open the state folder, read only; and Show me what happens,
    # whose rows are made up and whose card is asked of a watcher that is not there to draw it.
    "state-access": [
        Case("only this account and Windows", using=_state_access("owner_only")),
        Case("other accounts too", using=_state_access("shared"))],
    "demo": [Case("the made-up rows, and no watcher's icon to ask for the card")],
    # v0.6.11: Diagnostics compares the edition installed with Codex's copy of the plugin, read only.
    "plugin-copy": [
        Case("Codex keeps no copy of the plugin"),
        Case("Codex's copy is the same edition", using=_plugin_copy("standard")),
        Case("Codex's copy is still the other edition's", using=_plugin_copy("advanced"))],
    "update": [
        Case("one setting changed", {"notifications": False}),
        Case("a Korean Custom message, stored and answered as UTF-8",
             {"continuation_style": "custom", "custom_message_mode": "global",
              "custom_message": KOREAN_CUSTOM}),
        Case("a value out of range is refused", {"max_recovery_attempts": 0}),
        Case("a setting that does not exist is refused", {"no_such_setting": True}),
        # v0.6.11: what a policy key already says is kept out of the file; a loosening is refused.
        Case("what an administrator's key already says is answered and not written",
             {"observe_only": True, "notifications": True}, using=_managed(force_observe_only=True)),
        Case("a change an administrator's key forbids is refused", {"max_recovery_attempts": 9},
             using=_managed(max_recovery_attempts=2))],
    "enabled": [
        Case("paused", {"enabled": False}),
        Case("on again", {"enabled": True}),
        Case("the string \"false\" is refused, not read as true", {"enabled": "false"}),
        Case("a missing flag is refused", {}),
        # v0.6.11: a pause an administrator's DisableAutoResume holds is not lifted here.
        Case("an administrator's pause cannot be resumed", {"enabled": True},
             using=_managed(disable_auto_resume=True))],
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
        Case("live must be true or false", {"live": "yes"}),
        Case("the watcher's report on the pictures' Codex, with what others report of it", {},
             engine=True)],
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
    # v0.6.11: a task's row menu.
    "postpone": [
        Case("a waiting recovery postponed by an hour",
             {"interruption_id": WAITING_RESET, "thread_id": T1, "preset": "1_hour"}),
        Case("half an hour is earlier than the hour it already waits for",
             {"interruption_id": WAITING_RESET, "thread_id": T1, "preset": "30_minutes"}),
        Case("a number of minutes, later still",
             {"interruption_id": WAITING_RESET, "thread_id": T1, "minutes": 180}),
        Case("two ways to say the time at once",
             {"interruption_id": WAITING_RESET, "thread_id": T1, "preset": "3_hours", "minutes": 240}),
        Case("more than a week ahead", {"interruption_id": WAITING_RESET, "thread_id": T1, "minutes": 10081}),
        Case("a task that belongs to another conversation",
             {"interruption_id": WAITING_RESET, "thread_id": T2, "preset": "3_hours"}),
        Case("a finished task", {"interruption_id": RECOVERED, "thread_id": T3, "preset": "3_hours"})],
    # v0.6.11: Don't postpone - a person's own postponement taken away, bound to the row.
    "unpostpone": [
        Case("a person's postponement taken away", {"interruption_id": WAITING_RESET, "thread_id": T1},
             using=_postponed(WAITING_RESET, T1)),
        Case("the same task again: nothing to take away", {"interruption_id": WAITING_RESET, "thread_id": T1}),
        Case("a task that belongs to another conversation",
             {"interruption_id": WAITING_RESET, "thread_id": T2}),
        Case("a finished task", {"interruption_id": RECOVERED, "thread_id": T3})],
    # v0.6.11: one conversation's own message, from its row in the Dashboard only.
    "conversation-message": [
        Case("a message for one conversation", {"thread_id": T1, "text": "Carry on with the plan, please."}),
        Case("a placeholder that would leak the conversation is refused", {"thread_id": T1, "text": "{prompt}"}),
        Case("the text must be named, even to take it away", {"thread_id": T1}),
        Case("taken away", {"thread_id": T1, "text": None}),
        Case("not a conversation id", {"thread_id": "latest", "text": "go"})],
    # v0.6.11: whether a setting takes a value of the person's own (Custom...): the validator's answer, and
    # the value as it would be stored; nothing is written.
    "check-setting": [
        Case("a stall of the person's own, in its one spelling", {"name": "stall_after", "value": "m60"}),
        Case("any days quiet hours start on", {"name": "quiet_hours_days", "value": "fri,mon"}),
        Case("keeping this PC awake without a limit", {"name": "keep_awake_hours", "value": "unlimited"}),
        Case("a retry wait under the engine's floor is refused", {"name": "retry_wait_2", "value": "m5"}),
        Case("a setting that does not exist is refused", {"name": "no_such_setting", "value": "h1"})],
    # v0.6.11: the log searched, newest last.
    "logs": [
        Case("no log yet", {}),
        Case("the lines that hold a word", _logged),
        Case("a search with a line break in it is refused", {"query": "a\nb"})],
    "release-hold": [
        Case("a held task let continue", {"interruption_id": WAITING_RESET, "thread_id": T1},
             using=_held(T1)),
        Case("the same task again: it is not held", {"interruption_id": WAITING_RESET, "thread_id": T1}),
        Case("a task that belongs to another conversation",
             {"interruption_id": WAITING_RESET, "thread_id": T2}),
        Case("no such interruption", {"interruption_id": NO_SUCH, "thread_id": T1})],
    "thread-tier": [
        Case("a conversation that asks first holds what it has waiting",
             {"thread_id": T1, "tier": "ask_first", "interruption_id": WAITING_RESET}),
        Case("back to the default in Settings", {"thread_id": T1, "tier": None}),
        Case("a tier that is not one", {"thread_id": T1, "tier": "sometimes"}),
        Case("a row whose task is another conversation's",
             {"thread_id": T2, "tier": "ask_first", "interruption_id": WAITING_RESET}),
        Case("the tier must be named, even to take it away", {"thread_id": T1})],
    "project-rule": [
        Case("a project held for a person, with what it has waiting",
             {"interruption_id": WAITING_RESET, "thread_id": T1, "always": False},
             using=_filed(T1, r"C:\work\alpha")),
        Case("the same project let resume again",
             {"interruption_id": WAITING_RESET, "thread_id": T1, "always": True}),
        Case("a conversation whose project cannot be read",
             {"interruption_id": WAITING_BACKOFF, "thread_id": T2, "always": False}),
        Case("always must be true or false",
             {"interruption_id": WAITING_RESET, "thread_id": T1, "always": "yes"}),
        Case("a task that belongs to another conversation",
             {"interruption_id": WAITING_RESET, "thread_id": T2, "always": False}),
        Case("a finished task", {"interruption_id": RECOVERED, "thread_id": T3, "always": False})],
    # v0.6.12: the power action after usage-limit recoveries - what Windows offers here (a stand-in port),
    # armed only from the Dashboard, and turned off.
    "power-action": [
        Case("nothing armed, and every action offered", using=_power()),
        Case("hibernation off in Windows", using=_power(NO_HIBERNATION)),
        Case("an account Windows lets do none of them", using=_power(NONE_FOR_THIS_ACCOUNT)),
        Case("while an administrator's DisablePowerAction is set", using=_power(disable_power_action=True)),
        Case("armed to shut down every time", using=_power(arm=SHUT_DOWN_ALWAYS))],
    "power-arm": [
        Case("armed to sleep once, after every recovery succeeded", SLEEP_ONCE, using=_power()),
        Case("a second arming replaces the first", SHUT_DOWN_ALWAYS, using=_power()),
        Case("an action Windows does not offer here is refused", dict(SLEEP_ONCE, action="hibernate"),
             using=_power(NO_HIBERNATION)),
        Case("an action that is not one is refused", dict(SLEEP_ONCE, action="restart"), using=_power()),
        Case("minutes as text are refused", dict(SLEEP_ONCE, grace_minutes="5"), using=_power()),
        Case("a warning this does not offer is refused", dict(SLEEP_ONCE, grace_minutes=7), using=_power()),
        Case("a key it does not take is refused", dict(SLEEP_ONCE, nonce="0123456789abcdef"), using=_power()),
        Case("while an administrator's DisablePowerAction is set", SLEEP_ONCE,
             using=_power(disable_power_action=True))],
    "power-disarm": [
        Case("nothing armed: nothing changes", {}, using=_power()),
        Case("armed, then turned off", {}, using=_power(arm=SLEEP_ONCE)),
        Case("again: nothing left to turn off", {}, using=_power()),
        Case("an argument it does not take is refused", {"actor": "mcp"}, using=_power())],
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
    "get_status": [Case("the status, with the registry's summary under watcher", {}),
                   # v0.6.11: an administrator's policy keys in force, named.
                   Case("while an administrator's policy keys force observe only and cap the attempts", {},
                        using=_managed(force_observe_only=True, max_recovery_attempts=2))],
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
    # v0.6.12: the power action turned off from Codex - never on; there is no tool for that.
    "turn_off_power_action": [
        Case("nothing armed: nothing changes", {}, using=_power()),
        Case("armed in the Dashboard, then turned off from Codex", {}, using=_power(arm=SLEEP_ONCE)),
        Case("an argument it does not take is refused", {"action": "sleep"}, using=_power())],
    "cancel_recovery": [
        Case("a waiting recovery cancelled", {"interruption_id": WAITING_BACKOFF}),
        Case("no such interruption", {"interruption_id": NO_SUCH}),
        Case("the id is required", {})],
    "reset_recovery_budget": [
        Case("an exhausted recovery given its attempts back", {"interruption_id": EXHAUSTED}),
        Case("a recovery still waiting has not been exhausted", {"interruption_id": WAITING_RESET})],
    "start_watcher": [
        Case("a watcher already holds the mutex", {}),
        # v0.6.10: a start made from inside Codex says how long it lasts (`ends_with_codex`).
        Case("started inside a job that ends what it holds, as Codex 26.915 runs this server", {},
             watching=False, using=_launch_that_comes_up(KILL_ON_CLOSE_JOB)),
        Case("started in no job, so it outlives Codex", {},
             watching=False, using=_launch_that_comes_up(NO_JOB))],
    "retry_now": [
        Case("a usage limit whose reset is still ahead", {"interruption_id": WAITING_RESET}),
        Case("a recovered one has already finished", {"interruption_id": RECOVERED})],
    # v0.6.11: postpone one recovery (never marked destructive), and let a held one continue.
    "postpone_recovery": [
        Case("a waiting recovery postponed by an hour",
             {"interruption_id": WAITING_RESET, "thread_id": T1, "preset": "1_hour"}),
        Case("half an hour is earlier than the hour it already waits for",
             {"interruption_id": WAITING_RESET, "thread_id": T1, "minutes": 30}),
        Case("the conversation is required", {"interruption_id": WAITING_RESET, "preset": "1_hour"})],
    "release_hold": [
        Case("a held recovery let continue", {"interruption_id": WAITING_RESET, "thread_id": T1},
             using=_held(T1)),
        Case("the same one again: it is not held", {"interruption_id": WAITING_RESET, "thread_id": T1})],
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
def installation(*, watching=True, mcp=False, engine=False):
    """A fresh golden installation: (workspace, the `Control` it answers for, the rewriting).

    `engine=True` keeps the envelope's stand-in Codex and the watcher's report about it, for a
    case that reads that report. The stand-in answers its two questions only while the report is
    written; a live check afterwards would start a process, which `_no_process` refuses."""
    from codex_auto_resume import l10n

    with tempfile.TemporaryDirectory() as name, ExitStack() as stack:
        workspace = Path(name)
        # Before anything is built, so the building cannot start a process either.
        stack.enter_context(_no_process())
        surface = stack.enter_context(
            generator.pinned_installation(workspace, watching=watching, engine=engine))
        # Inside the pinned installation's environment, which is put back whole after it.
        os.environ[l10n.ENV_LANG] = "en"
        if not engine:
            # A LOCALAPPDATA of its own, with no engine in it, so a live compatibility check finds
            # none on every machine. Named apart from the `LocalAppData` the envelope seeds an
            # engine into (`pinned_installation`), because Windows would otherwise call them the
            # same folder.
            engines = workspace / "no-engines"
            engines.mkdir(exist_ok=True)
            os.environ["LOCALAPPDATA"] = str(engines)
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
    # Split where the wire splits, at line feeds only: `splitlines` would also break a reply at
    # a U+2028 that `ensure_ascii=False` writes as itself, where neither reader breaks it.
    for line in written.split("\n")[:-1]:
        value = json.loads(line)
        if json.dumps(value, ensure_ascii=False) != line:
            raise WireChanged("%s: a reply line is not what json.dumps(reply, ensure_ascii=False) "
                              "writes - the wire's encoding, separators or escaping changed" % what)
        parsed.append(value)
    return parsed


def _groups(cases):
    """Consecutive cases that share an installation."""
    group = []
    for case in cases:
        if group and (case.watching, case.engine) != (group[-1].watching, group[-1].engine):
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
        with installation(watching=group[0].watching, engine=group[0].engine) as (
                workspace, surface, rewriting):
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
        with installation(watching=group[0].watching, mcp=True, engine=group[0].engine) as (
                workspace, surface, rewriting):
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
    stale = sorted(name for name in wire_goldens() if name not in made)
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
