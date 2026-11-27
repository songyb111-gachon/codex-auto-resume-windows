"""The advanced surfaces' family (seat S7.3a, P7-DESIGN 3.2 `diffs_advsurface_*`): one scenario script, run twice on the
reference tag's own trees and on the reference's Python (advref.run): once as the tag ships (every answer the tag's),
once with tests/rustdiff/shim.py installed under CODEX_AR_CORE=rust, so the runtime, its state and arming and every
`surfaces.*` name advproxy/table.py forwards are car-adv's (advserve). What the script prints - every answer of
`surfaces.answer` and of the arming steps that set each scenario up, one JSON line each, DEFER as its own word - is
compared line by line.

The scenarios are the advanced tests' (test_advanced_surfaces, _rows, _prompt_queue, _keep_going, _send_now, _steer_send,
_chat, _fleet, _early_check, _conversations, _feed, _usage) cut to their requests, plus the edges: an unknown command,
a non-dict argument, an argument a command does not take, every wrong type a card checks, empty and huge words, a
marker, unicode, the MCP tools' every refusal. Every home is the scratch profile; CODEX_HOME is that profile too, so
no Codex of this PC is read; no watcher holds the wake event, so a wake answers "no watcher".

Scenario 6 and on (seat S7.3a2) add the cards ported last - power after tasks, the saved accounts, analytics - over a
Codex home of the script's own written into the scratch profile (CODEX_HOME, which advserve was started with).
"""
from __future__ import annotations

from pathlib import Path

from rustdiff import advref

ROOT = Path(__file__).resolve().parents[2]
SHIM = ROOT / "tests" / "rustdiff" / "shim.py"

PRELUDE_RUST = r'''
import importlib.util, os, sys
os.environ["CODEX_AR_CORE"] = "rust"
os.environ["CODEX_AR_ADVSERVE_EXE"] = sys.argv[2]
spec = importlib.util.spec_from_file_location("rustdiff_shim", sys.argv[1])
shim = importlib.util.module_from_spec(spec)
sys.modules["rustdiff_shim"] = shim
spec.loader.exec_module(shim)
assert shim.install()
'''

SCRIPT = r'''
import enum, json, os, sys, tempfile
# `system` resolves to what this variable says on both sides: car-platform reads no Windows UI language yet (the
# surfaces' World.windows_languages, as core's host), and the reference would read this PC's.
os.environ["CODEX_AUTO_RESUME_LANG"] = os.environ.get("CAR_SURFACE_LANGUAGE", "de")
from pathlib import Path

from codex_auto_resume import config
from codex_auto_resume.domain.plug import DEFER, Surface
from codex_auto_resume_advanced import policy, registry, statement, surfaces
from codex_auto_resume_advanced.registry import Registry
from codex_auto_resume_advanced.runtime import Runtime

NOW = 1_800_000_000.0
ENGINE = "0.155.0"
THREAD = "0a1b2c3d-0001-7000-8000-000000000001"
OTHER = "0a1b2c3d-0001-7000-8000-000000000002"
KEY = "a" * 64


def plain(value):
    if value is DEFER:
        return "DEFER"
    if isinstance(value, enum.Enum):
        return plain(value.value)
    if isinstance(value, dict):
        return {plain(key) if not isinstance(key, str) else key: plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(plain(item) for item in value)
    return value


def say(label, value):
    try:
        text = json.dumps(plain(value), ensure_ascii=False, sort_keys=False)
    except (TypeError, ValueError) as error:
        text = "UNPRINTABLE " + type(error).__name__
    print(label + " " + text, flush=True)


def ask(label, runtime, name, facts):
    try:
        found = surfaces.answer(runtime, name, facts)
    except Exception as error:
        print(label + " RAISED " + type(error).__name__, flush=True)
        return None
    say(label, found)
    return found


def bridge(label, runtime, command, argument):
    return ask(label, runtime, Surface.BRIDGE, {"command": command, "argument": argument})


SHIPPED = {each.id: each for each in registry.REGISTRY}
NAMES = ["reset_credit", "reset_message", "long_reset_message", "prompt_queue", "steer_send", "keep_going",
         "codex_chat", "send_now", "early_reset", "fleet_view", "open_codex_button", "status_feed", "usage_meter",
         "usage_wrap_up", "usage_pause", "headless_run", "compact_continue", "model_fallback", "other_sessions"]
DEFINITIONS = tuple(SHIPPED[name] for name in NAMES if name in SHIPPED)


def view():
    return {"status": "ok", "engine": {"found": True, "version": ENGINE},
            "capabilities": {each.compat: {"state": "COMPATIBLE", "reason": "local_checks_passed"}
                             for each in DEFINITIONS if each.compat}}


def make(home):
    paths = config.Paths(home)
    paths.ensure()
    runtime = Runtime(paths, registry=Registry(DEFINITIONS), clock=lambda: NOW, policy=lambda: policy.NONE,
                      view=view, measured=lambda: {}, catalogs=statement.CATALOGS)
    return paths, runtime


def arm(label, runtime, capability, state="armed"):
    definition = runtime.registry.get(capability)
    if definition is None:
        print(label + " ABSENT", flush=True)
        return
    try:
        found = runtime.arming.arm(capability, state=state, revision=definition.revision,
                                   generation=runtime.state.meta()["generation"], acknowledged_version=ENGINE,
                                   warnings=list(runtime.arming.warnings(definition)),
                                   also=[each for each in definition.requires
                                         if runtime.states(fresh=True).get(each) != "armed"],
                                   actor="dashboard")
    except Exception as error:
        print(label + " RAISED " + type(error).__name__, flush=True)
        return
    say(label, found)
    runtime.states(fresh=True)


def generation(runtime):
    return runtime.state.meta()["generation"]


profile = Path(os.environ["CODEX_HOME"])

# ---------------------------------------------------------------- 1. nothing on: every surface, every edge
paths, runtime = make(profile / "one")
for name in (Surface.STATUS, Surface.TRAY, Surface.DIAGNOSTICS):
    ask("1.%s" % name, runtime, name, {})
for facts in (None, [], "x", 5):
    ask("1.bridge-facts-%r" % (facts,), runtime, Surface.BRIDGE, facts)
for command, argument in (("advanced-nothing", {}), (5, {}), (None, {}), ("advanced-list", None),
                          ("advanced-list", []), ("advanced-list", {"extra": 1}), ("advanced-list", {}),
                          ("advanced-words", {"locale": "en"}), ("advanced-words", {"locale": "ko"}),
                          ("advanced-words", {"locale": ""}), ("advanced-words", {"locale": 5}),
                          ("advanced-words", {"locale": "zz-ZZ"}),
                          ("advanced-statement", {"capability": "no_such"}), ("advanced-statement", {"capability": 5}),
                          ("advanced-statement", {"capability": "reset_credit", "locale": "en"}),
                          ("advanced-resets", {}), ("advanced-prompts", {}), ("advanced-keep-going", {}),
                          ("advanced-rules", {}), ("advanced-samples", {}), ("advanced-wordings", {"capability": "fleet_view"}),
                          ("advanced-chat-read", {"thread_id": "nope"}), ("advanced-chat-read", {"thread_id": THREAD}),
                          ("advanced-conversations", {}), ("advanced-early-check", {}),
                          ("advanced-send-now", {"interruption_id": "short"}), ("advanced-send-now", {"interruption_id": KEY}),
                          ("advanced-headless-stop", {"interruption_id": 5}), ("advanced-headless-stop", {"interruption_id": KEY}),
                          ("advanced-python", {}), ("advanced-python-use", {"version": "3.14"}), ("advanced-python-back", {}),
                          ("advanced-fleet", {}), ("advanced-fleet-save", {"alias": "a", "folder": "b", "generation": 1}),
                          ("advanced-watch-log", {"capability": "reset_credit"}), ("advanced-watch-log", {"capability": 5}),
                          ("measure", {"measurement": "MZ"}), ("measure", {"measurement": "MU", "thread": 5}),
                          ("measure", {"measurement": "MU", "may_spend": 1}),
                          ("measure-verdict", {"measurement": "MU", "verdict": "blocked", "note": "as_expected"}),
                          ("measure-verdict", {"measurement": "MU", "verdict": "pass", "note": "nope"}),
                          ("advanced-ceiling", {"global_hourly": 3, "generation": 0}),
                          ("advanced-ceiling", {"global_hourly": "3", "generation": 0}),
                          ("advanced-disarm", {"capability": "no_such"}), ("advanced-disarm", {"capability": "reset_credit"}),
                          ("advanced-disarm-all", {}), ("advanced-prompt-follow", {"prompt": "1"}),
                          ("advanced-prompt-follow", {"prompt": 1}), ("advanced-steer", {"thread_id": THREAD}),
                          ("advanced-report-build", {}), ("advanced-report-job", {"job": "x"})):
    bridge("1.%s %s" % (command, json.dumps(argument)), runtime, command, argument)
for facts in ({"request": "tools"}, {"request": "call", "tool": "list_advanced_capabilities", "arguments": {}},
              {"request": "call", "tool": "list_advanced_capabilities", "arguments": {"x": 1}},
              {"request": "call", "tool": "disarm_advanced_capability", "arguments": {"capability": "no_such"}},
              {"request": "call", "tool": "disarm_advanced_capability", "arguments": {"capability": "reset_credit"}},
              {"request": "call", "tool": "disarm_all_advanced", "arguments": {}},
              {"request": "call", "tool": "arm_advanced_capability", "arguments": {}},
              {"request": "call", "tool": "disarm_all_advanced", "arguments": []},
              {"request": "list", "tool": "disarm_all_advanced", "arguments": {}}, {}):
    ask("1.mcp %s" % json.dumps(facts), runtime, Surface.MCP, facts)
ask("1.other", runtime, "nonsense", {})

# ---------------------------------------------------------------- 2. the reset actions
paths, runtime = make(profile / "two")
bridge("2.add before on", runtime, "advanced-reset-add", {"kind": "credit", "bucket": "codex", "minutes": 300,
                                                          "ordinal": 1, "generation": generation(runtime)})
for capability in ("reset_message", "reset_credit"):
    arm("2.arm " + capability, runtime, capability)
words = "SENTINEL-reset: carry on with the tests."
for label, argument in (
        ("stale", {"kind": "credit", "bucket": "codex", "minutes": 300, "ordinal": 1, "generation": -1}),
        ("kind", {"kind": "other", "bucket": "codex", "minutes": 300, "ordinal": 1, "generation": 0}),
        ("bucket", {"kind": "credit", "bucket": "nope", "minutes": 300, "ordinal": 1}),
        ("minutes0", {"kind": "credit", "bucket": "codex", "minutes": 0, "ordinal": 1}),
        ("minutesbool", {"kind": "credit", "bucket": "codex", "minutes": True, "ordinal": 1}),
        ("weekly2", {"kind": "credit", "bucket": "codex", "minutes": 10080, "ordinal": 2}),
        ("ordinal10", {"kind": "credit", "bucket": "codex", "minutes": 300, "ordinal": 10}),
        ("repeat-type", {"kind": "credit", "bucket": "codex", "minutes": 300, "ordinal": 1, "repeat": 1}),
        ("credit-words", {"kind": "credit", "bucket": "codex", "minutes": 300, "ordinal": 1, "words": "x"}),
        ("credit", {"kind": "credit", "bucket": "codex", "minutes": 300, "ordinal": 2, "repeat": True}),
        ("credit2", {"kind": "credit", "bucket": "premium", "minutes": 60, "ordinal": 3, "ask_first": True}),
        ("message-uuid", {"kind": "message", "bucket": "codex", "minutes": 300, "ordinal": 1, "thread_id": "x", "words": words}),
        ("message-empty", {"kind": "message", "bucket": "codex", "minutes": 300, "ordinal": 1, "thread_id": THREAD, "words": "  "}),
        ("message-marker", {"kind": "message", "bucket": "codex", "minutes": 300, "ordinal": 1, "thread_id": THREAD,
                            "words": "car-auto-resume:" + KEY}),
        ("message-long", {"kind": "message", "bucket": "codex", "minutes": 300, "ordinal": 1, "thread_id": THREAD,
                          "words": "x" * 2001}),
        ("message-repeat", {"kind": "message", "bucket": "codex", "minutes": 300, "ordinal": 1, "thread_id": THREAD,
                            "words": words, "repeat": False}),
        ("message", {"kind": "message", "bucket": "codex", "minutes": 300, "ordinal": 1, "thread_id": THREAD,
                     "words": words + " é中"}),
        ("message-again", {"kind": "message", "bucket": "codex", "minutes": 300, "ordinal": 2, "thread_id": THREAD,
                           "words": words})):
    argument = dict(argument)
    argument.setdefault("generation", generation(runtime))
    bridge("2.add " + label, runtime, "advanced-reset-add", argument)
bridge("2.view", runtime, "advanced-resets", {})
for rule, gen in (("1", 0), (1, -1), (99, None), (1, None)):
    bridge("2.cancel %r" % (rule,), runtime, "advanced-reset-cancel",
           {"rule": rule, "generation": generation(runtime) if gen is None else gen})
for rule in ("2", 2, 99):
    bridge("2.go-on %r" % (rule,), runtime, "advanced-reset-go-on", {"rule": rule, "generation": generation(runtime)})
for argument in ({}, {"rule": 2}, {"rule": "x"}, {"bucket": "codex", "minutes": 300}, {"bucket": "codex"},
                 {"bucket": "nope", "minutes": 300}):
    argument = dict(argument, generation=generation(runtime))
    bridge("2.credit-now %s" % json.dumps(argument), runtime, "advanced-credit-now", argument)
bridge("2.view after", runtime, "advanced-resets", {})
ask("2.status", runtime, Surface.STATUS, {})
arm("2.arm long", runtime, "long_reset_message")
bridge("2.add long", runtime, "advanced-reset-add", {"kind": "message", "bucket": "codex", "minutes": 300, "ordinal": 3,
                                                       "thread_id": OTHER, "words": "y" * 2001,
                                                       "generation": generation(runtime)})
bridge("2.view long", runtime, "advanced-resets", {})

# ---------------------------------------------------------------- 3. the prompt queue, steer, follow
paths, runtime = make(profile / "three")
bridge("3.add before", runtime, "advanced-prompt-add", {"thread_id": THREAD, "words": "hello", "trigger": "at_time",
                                                         "at": NOW + 600, "generation": generation(runtime)})
arm("3.arm queue", runtime, "prompt_queue")
for label, argument in (
        ("uuid", {"thread_id": "x", "words": "hello", "trigger": "at_time", "at": NOW + 600}),
        ("empty", {"thread_id": THREAD, "words": "", "trigger": "at_time", "at": NOW + 600}),
        ("words-type", {"thread_id": THREAD, "words": 5, "trigger": "at_time", "at": NOW + 600}),
        ("long", {"thread_id": THREAD, "words": "z" * 2001, "trigger": "at_time", "at": NOW + 600}),
        ("images-type", {"thread_id": THREAD, "words": "hello", "trigger": "at_time", "at": NOW + 600, "images": "x"}),
        ("images-shape", {"thread_id": THREAD, "words": "hello", "trigger": "at_time", "at": NOW + 600, "images": [{}]}),
        ("images-missing", {"thread_id": THREAD, "words": "hello", "trigger": "at_time", "at": NOW + 600,
                            "images": [{"path": str(profile / "missing.png")}]}),
        ("images-id", {"thread_id": THREAD, "words": "hello", "trigger": "at_time", "at": NOW + 600, "images": [{"id": "abc"}]}),
        ("images-many", {"thread_id": THREAD, "words": "hello", "trigger": "at_time", "at": NOW + 600, "images": [{}] * 11}),
        ("at", {"thread_id": THREAD, "words": "hello ü", "trigger": "at_time", "at": NOW + 600}),
        ("after", {"thread_id": THREAD, "words": "after the turn", "trigger": "after_turn", "depends": True,
                   "while_running": "wait"}),
        ("bad-trigger", {"thread_id": THREAD, "words": "x", "trigger": "never"}),
        ("every", {"thread_id": OTHER, "words": "again", "trigger": "recurring", "at": NOW + 60, "every": 3600,
                   "occurrences": 3}),
        ("every-bad", {"thread_id": OTHER, "words": "again", "trigger": "recurring", "at": NOW + 60, "every": -1})):
    bridge("3.add " + label, runtime, "advanced-prompt-add", dict(argument, generation=generation(runtime)))
bridge("3.view", runtime, "advanced-prompts", {})
bridge("3.cancel str", runtime, "advanced-prompt-cancel", {"prompt": "1", "generation": generation(runtime)})
bridge("3.cancel stale", runtime, "advanced-prompt-cancel", {"prompt": 1, "generation": -5})
bridge("3.cancel", runtime, "advanced-prompt-cancel", {"prompt": 1, "generation": generation(runtime)})
bridge("3.cancel gone", runtime, "advanced-prompt-cancel", {"prompt": 999, "generation": generation(runtime)})
bridge("3.go-on", runtime, "advanced-prompt-go-on", {"prompt": 2, "generation": generation(runtime)})
bridge("3.edit", runtime, "advanced-prompt-edit", {"prompt": 2, "words": "edited", "trigger": "after_turn",
                                                   "generation": generation(runtime)})
bridge("3.edit gone", runtime, "advanced-prompt-edit", {"prompt": 77, "words": "edited", "trigger": "after_turn",
                                                        "generation": generation(runtime)})
bridge("3.edit words", runtime, "advanced-prompt-edit", {"prompt": 2, "words": "", "trigger": "after_turn",
                                                         "generation": generation(runtime)})
bridge("3.clear-done", runtime, "advanced-prompts-clear-done", {"prompts": [1, 2], "generation": generation(runtime)})
bridge("3.clear-done type", runtime, "advanced-prompts-clear-done", {"prompts": "1", "generation": generation(runtime)})
bridge("3.follow waiting", runtime, "advanced-prompt-follow", {"prompt": 2})
arm("3.arm steer", runtime, "steer_send")
for label, argument in (("uuid", {"thread_id": "x", "words": "go"}), ("words", {"thread_id": THREAD, "words": ""}),
                        ("no-turn", {"thread_id": THREAD, "words": "go on"})):
    bridge("3.steer " + label, runtime, "advanced-steer", dict(argument, generation=generation(runtime)))
ask("3.status", runtime, Surface.STATUS, {})

# ---------------------------------------------------------------- 4. keep going, chat, send now, headless stop
paths, runtime = make(profile / "four")
for capability in ("keep_going", "codex_chat", "send_now"):
    arm("4.arm " + capability, runtime, capability)
for count in (0, 11, True, "3", 3.0, 3, 10):
    bridge("4.set %r" % (count,), runtime, "advanced-keep-going-set",
           {"thread_id": THREAD, "count": count, "generation": generation(runtime)})
bridge("4.keep view", runtime, "advanced-keep-going", {})
bridge("4.stop other", runtime, "advanced-keep-going-stop", {"thread_id": OTHER, "generation": generation(runtime)})
bridge("4.stop", runtime, "advanced-keep-going-stop", {"thread_id": THREAD, "generation": generation(runtime)})
bridge("4.stop again", runtime, "advanced-keep-going-stop", {"thread_id": THREAD, "generation": generation(runtime)})
bridge("4.chat read", runtime, "advanced-chat-read", {"thread_id": THREAD})
bridge("4.chat send", runtime, "advanced-chat-send", {"thread_id": THREAD, "words": "hi", "generation": generation(runtime)})
bridge("4.chat cancel", runtime, "advanced-chat-cancel", {"thread_id": THREAD, "generation": generation(runtime)})
bridge("4.send-now", runtime, "advanced-send-now", {"interruption_id": KEY})
bridge("4.send-now upper", runtime, "advanced-send-now", {"interruption_id": KEY.upper()})
bridge("4.headless-stop", runtime, "advanced-headless-stop", {"interruption_id": KEY})
for name in (Surface.STATUS, Surface.TRAY, Surface.DIAGNOSTICS):
    ask("4.%s" % name, runtime, name, {})
ask("4.mcp list", runtime, Surface.MCP, {"request": "call", "tool": "list_advanced_capabilities", "arguments": {}})
ask("4.mcp off", runtime, Surface.MCP, {"request": "call", "tool": "disarm_advanced_capability",
                                        "arguments": {"capability": "keep_going"}})
ask("4.mcp all", runtime, Surface.MCP, {"request": "call", "tool": "disarm_all_advanced", "arguments": {}})
ask("4.status off", runtime, Surface.STATUS, {})

# ---------------------------------------------------------------- 5. fleet, early check, the feed, open codex
paths, runtime = make(profile / "five")
for capability in ("fleet_view", "early_reset", "status_feed", "open_codex_button"):
    arm("5.arm " + capability, runtime, capability)
bridge("5.fleet", runtime, "advanced-fleet", {})
import shutil
shared = Path(tempfile.gettempdir()) / "car-surface-fleet-s73a"      # one name on both lanes, which run one at a time
shutil.rmtree(shared, ignore_errors=True)
shared.mkdir()
for alias, folder in (("", str(shared)), ("a" * 80, str(shared)), ("laptop", "rel"), ("laptop", str(profile / "nope")),
                      ("laptop", 5), ("laptop", str(shared))):
    bridge("5.fleet-save %r" % (alias[:8],), runtime, "advanced-fleet-save",
           {"alias": alias, "folder": folder, "generation": generation(runtime)})
bridge("5.fleet after", runtime, "advanced-fleet", {})
bridge("5.early", runtime, "advanced-early-check", {})
for name in (Surface.STATUS, Surface.TRAY):
    ask("5.%s" % name, runtime, name, {})
shutil.rmtree(shared, ignore_errors=True)

# ---------------------------------------------------------------- 6. power after tasks (S7.3a2)
import sqlite3
EXTRA = tuple(SHIPPED[name] for name in ("power_after_tasks",) if name in SHIPPED)


def make_more(home):
    paths = config.Paths(home)
    paths.ensure()
    definitions = DEFINITIONS + EXTRA
    compat = lambda: {"status": "ok", "engine": {"found": True, "version": ENGINE},
                      "capabilities": {each.compat: {"state": "COMPATIBLE", "reason": "local_checks_passed"}
                                       for each in definitions if each.compat}}
    runtime = Runtime(paths, registry=Registry(definitions), clock=lambda: NOW, policy=lambda: policy.NONE,
                      view=compat, measured=lambda: {}, catalogs=statement.CATALOGS)
    return paths, runtime


paths, runtime = make_more(profile / "six")
TURN = "0a1b2c3d-0001-7000-8000-0000000000a1"
DONE_TURN = "0a1b2c3d-0001-7000-8000-0000000000a2"
bridge("6.view before", runtime, "advanced-power-tasks", {})
good = {"threads": [THREAD], "action": "sleep", "grace_minutes": 5, "failed": False, "interrupted": False}
for label, change in (("threads-empty", {"threads": []}), ("threads-str", {"threads": THREAD}),
                      ("threads-int", {"threads": [5]}), ("threads-uuid", {"threads": ["x"]}),
                      ("threads-dup", {"threads": [THREAD, THREAD]}), ("threads-many", {"threads": [THREAD] * 17}),
                      ("threads-17", {"threads": ["0a1b2c3d-0001-7000-8000-%012d" % n for n in range(17)]}),
                      ("threads-16", {"threads": ["0a1b2c3d-0001-7000-8000-%012d" % n for n in range(16)]}),
                      ("action", {"action": "restart"}), ("action-int", {"action": 1}), ("grace", {"grace_minutes": 7}),
                      ("grace-bool", {"grace_minutes": True}), ("grace-float", {"grace_minutes": 5.0}),
                      ("failed", {"failed": 1}), ("interrupted", {"interrupted": None}), ("stale", {"generation": -1}),
                      ("off", {})):
    argument = dict(good, generation=generation(runtime))
    argument.update(change)
    bridge("6.arm " + label, runtime, "advanced-power-tasks-arm", argument)
bridge("6.arm extra", runtime, "advanced-power-tasks-arm", dict(good, generation=generation(runtime), extra=1))
arm("6.arm capability", runtime, "power_after_tasks")
bridge("6.arm no codex", runtime, "advanced-power-tasks-arm", dict(good, generation=generation(runtime)))
codex = profile       # CODEX_HOME, which advserve was started with too
(codex / "sessions").mkdir(parents=True, exist_ok=True)
with sqlite3.connect(codex / "state_5.sqlite") as db:
    db.execute("CREATE TABLE threads (id TEXT PRIMARY KEY, rollout_path TEXT, source TEXT, thread_source TEXT, "
               "archived INTEGER, history_mode TEXT, name TEXT, cwd TEXT, project_id TEXT, title TEXT, "
               "first_user_message TEXT, preview TEXT)")
    for number, (thread, name) in enumerate(((THREAD, "example-project é"), (OTHER, "example-service"),
                                             ("0a1b2c3d-0001-7000-8000-000000000003", None))):
        rollout = codex / "sessions" / ("rollout-%d.jsonl" % number)
        rollout.write_text(json.dumps({"type": "session_meta", "payload": {"id": thread, "originator": "Codex Desktop",
                                                                         "source": "vscode", "thread_source": "user"}})
                           + "\n", encoding="utf-8")
        db.execute("INSERT INTO threads (id, rollout_path, source, thread_source, archived, history_mode, name) "
                   "VALUES (?,?,?,?,?,?,?)", (thread, str(rollout), "vscode", "user", 0, "paginated", name))
with sqlite3.connect(codex / "thread_history_1.sqlite") as db:
    db.execute("CREATE TABLE thread_turns (thread_id TEXT, turn_id TEXT, rollout_ordinal INTEGER, status TEXT, "
               "error_json TEXT, started_at INTEGER, completed_at INTEGER, duration_ms INTEGER, first_user_item_id TEXT, "
               "final_agent_item_id TEXT, rollout_byte_offset INTEGER, rollout_end_ordinal INTEGER, "
               "rollout_end_byte_offset INTEGER, PRIMARY KEY (thread_id, turn_id))")
    db.execute("CREATE TABLE thread_items (thread_id TEXT, turn_id TEXT, item_id TEXT, rollout_ordinal INTEGER, "
               "created_at_ms INTEGER, item_json TEXT, item_type TEXT, updated_at_ordinal INTEGER, "
               "PRIMARY KEY (thread_id, item_id))")
    db.execute("CREATE TABLE thread_history_projection_state (thread_id TEXT PRIMARY KEY, "
               "next_rollout_byte_offset INTEGER, next_rollout_ordinal INTEGER)")
    db.execute("INSERT INTO thread_turns (thread_id, turn_id, rollout_ordinal, status, started_at) VALUES (?,?,?,?,?)",
               (THREAD, TURN, 3, "inProgress", int(NOW) - 60))
    db.execute("INSERT INTO thread_turns (thread_id, turn_id, rollout_ordinal, status, started_at, completed_at) "
               "VALUES (?,?,?,?,?,?)", (OTHER, DONE_TURN, 2, "completed", int(NOW) - 600, int(NOW) - 500))
bridge("6.view codex", runtime, "advanced-power-tasks", {})
for label, threads in (("done", [OTHER]), ("unlisted", ["0a1b2c3d-0001-7000-8000-000000000009"]),
                       ("both", [THREAD, OTHER])):
    bridge("6.arm " + label, runtime, "advanced-power-tasks-arm",
           dict(good, threads=threads, generation=generation(runtime)))
for action, grace in (("sleep", 5), ("hibernate", 30)):
    bridge("6.arm %s" % action, runtime, "advanced-power-tasks-arm",
           dict(good, action=action, grace_minutes=grace, failed=True, generation=generation(runtime)))
    bridge("6.view %s" % action, runtime, "advanced-power-tasks", {})
say("6.list", json.loads((Path(paths.advanced_dir) / "power-tasks.json").read_text(encoding="utf-8"))["tasks"])
say("6.armed", {key: (json.loads(paths.power_action_file.read_text(encoding="utf-8"))["armed"] or {}).get(key)
                for key in ("action", "after", "repeat", "grace_seconds", "carried", "tasks")})
runtime.arming.disarm("power_after_tasks", actor="dashboard")
say("6.armed after off", json.loads(paths.power_action_file.read_text(encoding="utf-8"))["armed"])
bridge("6.view off", runtime, "advanced-power-tasks", {})

# ---------------------------------------------------------------- 7. the saved accounts (S7.3a2)
EXTRA = tuple(SHIPPED[name] for name in ("account_switch", "account_auto_switch", "usage_analytics") if name in SHIPPED)
paths, runtime = make_more(profile / "seven")
bridge("7.accounts off", runtime, "advanced-accounts", {})
for command in ("advanced-accounts-add", "advanced-accounts-save", "advanced-accounts-read"):
    bridge("7.%s off" % command, runtime, command, {})
for argument in ({}, {"id": 5}, {"id": "nope"}, {"id": None}, {"extra": 1}):
    bridge("7.switch %s" % json.dumps(argument), runtime, "advanced-accounts-switch", argument)
for argument in ({}, {"id": "nope"}, {"id": 5}, {"all": 1}, {"all": False}, {"all": True}, {"all": True, "id": "x"},
                 {"other": 1}):
    bridge("7.delete %s" % json.dumps(argument), runtime, "advanced-accounts-delete", argument)
arm("7.arm account_switch", runtime, "account_switch")
bridge("7.accounts standing", runtime, "advanced-accounts", {})
bridge("7.save standing", runtime, "advanced-accounts-save", {})
bridge("7.switch standing", runtime, "advanced-accounts-switch", {"id": "0" * 32})
arm("7.arm auto", runtime, "account_auto_switch")
bridge("7.accounts auto", runtime, "advanced-accounts", {})
runtime.arming.disarm("account_switch", actor="dashboard")
runtime.arming.disarm("account_auto_switch", actor="dashboard")
bridge("7.accounts after", runtime, "advanced-accounts", {})

# ---------------------------------------------------------------- 8. analytics (S7.3a2)
with sqlite3.connect(codex / "state_5.sqlite") as db:
    db.execute("ALTER TABLE threads ADD COLUMN tokens_used INTEGER")
    db.execute("UPDATE threads SET tokens_used = 4321, cwd = ? WHERE id = ?", (r"C:\ExampleUser\example-service", OTHER))   # one folder on both lanes: the key is its digest
paths, runtime = make_more(profile / "eight")
bridge("8.view off", runtime, "advanced-analytics", {})
for days in (8, True, "7", 7.0, None):
    bridge("8.view days %r" % (days,), runtime, "advanced-analytics", {"days": days} if days is not None else {})
arm("8.arm meter", runtime, "usage_meter")
arm("8.arm", runtime, "usage_analytics")
import time as clock_module
day = lambda back: clock_module.strftime("%Y-%m-%d", clock_module.localtime(NOW - back * 86400))
THIRD = "0a1b2c3d-0001-7000-8000-000000000003"
for file_key, thread, project, days in (("1" * 16, THREAD, "b" * 16, {day(0): [10, 2, 5, 1, 1], day(3): [3, 0, 4, 0, 2]}),
                                        ("2" * 16, THREAD, "b" * 16, {day(0): [1, 1, 1, 1, 1]}),
                                        ("3" * 16, THIRD, None, {day(40): [100, 0, 1, 0, 1]}),
                                        ("4" * 16, "0a1b2c3d-0001-7000-8000-000000000004", "c" * 16,
                                         {day(1): [7, 0, 9, 0, 1]})):
    try:
        say("8.ingest", runtime.state.ingest_file(file_key, thread, size=10, offset=10, changed_ns=1, days=days,
                                                  project_key=project, at=NOW))
    except Exception as error:
        print("8.ingest RAISED " + type(error).__name__, flush=True)
for argument in ({}, {"days": 30}, {"days": 90}, {"days": 1}):
    bridge("8.view %s" % json.dumps(argument), runtime, "advanced-analytics", argument)
target = profile / "eight" / "usage é.csv"
for label, argument in (("relative", {"path": "usage.csv"}), ("empty", {"path": ""}), ("nul", {"path": str(target) + "\x00"}),
                        ("type", {"path": 5}), ("replace-type", {"path": str(target), "replace": "yes"}),
                        ("days", {"path": str(target), "days": 3}), ("first", {"path": str(target)}),
                        ("again", {"path": str(target)}), ("replace", {"path": str(target), "replace": True, "days": 90}),
                        ("folder", {"path": str(profile / "eight"), "replace": True}),
                        ("missing", {"path": str(profile / "nope" / "x.csv")})):
    bridge("8.csv " + label, runtime, "advanced-analytics-csv", argument)
say("8.csv bytes", target.read_bytes().hex() if target.exists() else None)
'''


def scenario_script(rust: bool) -> str:
    return (PRELUDE_RUST if rust else "") + SCRIPT


def advserve() -> Path:
    named = __import__("os").environ.get("CODEX_AR_ADVSERVE_EXE")
    if named:
        return Path(named)
    target = advref.target_dir()
    release = target / "release" / "examples" / "advserve.exe"
    debug = target / "debug" / "examples" / "advserve.exe"
    return release if release.is_file() or not debug.is_file() else debug


def run(rust: bool) -> tuple:
    """(the lines printed, stderr's tail, the exit code) of one lane."""
    arguments = (str(SHIM), str(advserve())) if rust else ()
    done = advref.run(scenario_script(rust), *arguments, timeout=1800)
    return (done.stdout.decode("utf-8", "replace").splitlines(), done.stderr.decode("utf-8", "replace")[-4000:],
            done.returncode)
