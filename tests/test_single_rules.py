"""Rules the product states once, and what every caller gets from each of them.

Before the v0.6.5 split the same rule was written in two, three or four places: which wait
a record goes back to, what a claim costs its budgets, whether a record may be sitting in
Codex's queue, how a per-call command opens the state, which settings are the user's own
words, what a number of days may be, where an installation keeps its home, how a front end
states UTF-8, which pages the window opens, and what counts as a plausible time - and, in
nine modules, how a conversation id, an interruption id, a marker and a client id are read.
Two copies of a rule are a rule that can be changed in one place and not the other - a budget
restored onto the old wait, an in-flight record one gate sees and the other does not, Custom
text a second surface lets a model write, an id one reader takes and another refuses.

The tests here pin what each caller gets, call site by call site, so that gathering a rule
into one implementation changes nothing any caller can see. They are behaviour, not layout:
every one of them passes against the copies as they were and against the one rule that
replaces them.
"""
from __future__ import annotations

import ast
from contextlib import closing, contextmanager
import io
import math
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)        # the store and control fixtures live next to this file

import srcscan  # noqa: E402
from test_control_v3 import detection, legacy_store_module  # noqa: E402
from test_store import QUEUE, _StoreCase  # noqa: E402

from codex_auto_resume import (cli, compat, config, continuation, control, controlcli,  # noqa: E402
                               codex, mcpserver, notify, reasons, settings, store as store_module,
                               tray, windows)
from codex_auto_resume.app import App  # noqa: E402
from codex_auto_resume.engine import Engine  # noqa: E402
from codex_auto_resume.mcp import server as mcp_server  # noqa: E402
from codex_auto_resume.machine import STATES, WATCHED  # noqa: E402
from codex_auto_resume.store import (LegacyStore, StateFromNewerVersion, Store, StoreError,  # noqa: E402
                                     UpgradePending)

NOW = 1_000_000.0


# ------------------------------------------------------------------------ which wait
# (category, stored reset) -> the wait a record goes back to at NOW. A usage limit waits for a
# reset that is still ahead and polls once it has passed - including the very moment it is
# reached; every other failure backs off.
WAITS = (
    ("usage_limit", None, "waiting_poll"),
    ("usage_limit", NOW - 1, "waiting_poll"),
    ("usage_limit", NOW, "waiting_poll"),
    ("usage_limit", NOW + 1, "waiting_reset"),
    ("server_5xx", None, "waiting_backoff"),
    ("server_5xx", NOW + 3600, "waiting_backoff"),
)


class WaitingStateTests(_StoreCase):
    def test_the_engine_sends_a_record_back_to_this_wait(self):
        engine = Engine(None, None, None, clock=lambda: NOW)
        for category, reset, expected in WAITS:
            with self.subTest(category=category, reset=reset):
                self.assertEqual(engine.waiting_state({"category": category, "reset_at": reset}), expected)

    def test_a_restored_budget_goes_back_to_the_same_wait(self):
        for category, reset, expected in WAITS:
            with self.subTest(category=category, reset=reset):
                key = self.make("retry_budget_exhausted", thread_id=str(uuid.uuid4()),
                                category=category, reset_at=reset)
                self.assertEqual(self.store.restore_budget_detailed(key, NOW), (True, expected))
                self.assertEqual(self.store.get(key)["state"], expected)


# ------------------------------------------------------------------ what a claim costs
class ClaimCostTests(_StoreCase):
    def counters(self, key):
        row = self.store.get(key)
        return row["recovery_attempts"], row["chain_continuations"]

    def test_a_claim_spends_an_attempt_unless_it_is_a_usage_limit_and_one_link_always(self):
        self.store.set_enabled(True, 100)
        for category, attempt in ((None, 0), ("server_5xx", 1)):
            with self.subTest(category=category):
                key = self.make("waiting_retry", thread_id=str(uuid.uuid4()), category=category,
                                recovery_attempts=2, chain_continuations=3, next_retry_at=100.0)
                self.assertTrue(self.store.reserve(key, 200))
                self.assertEqual(self.counters(key), (2 + attempt, 4))
                # Undone before anything could start: both are given back.
                self.assertTrue(self.store.release_claim(key, "waiting_retry", "released_before_send", 201))
                self.assertEqual(self.counters(key), (2, 3))
                # Withdrawn after a Pause, proven never to have run: given back as well.
                self.assertTrue(self.store.reserve(key, 300))
                self.assertEqual(self.counters(key), (2 + attempt, 4))
                self.store.update(key, state="withdrawn_unconfirmed", withdraw_reason="paused",
                                  withdrawn_at=301.0, withdraw_deleted=True)
                self.assertTrue(self.store.release_withdrawn(
                    key, 400.0, window=10.0, later_turn=False, marker_rows=0, row_present=False,
                    fresh=True, target="waiting_poll"))
                self.assertEqual(self.counters(key), (2, 3))

    def test_giving_a_claim_back_never_takes_a_budget_below_zero(self):
        self.store.set_enabled(True, 100)
        for category in (None, "server_5xx"):
            with self.subTest(category=category):
                key = self.make("waiting_retry", thread_id=str(uuid.uuid4()), category=category,
                                next_retry_at=100.0)
                self.assertTrue(self.store.reserve(key, 200))
                self.db.execute("UPDATE interruptions SET recovery_attempts=0, chain_continuations=0 "
                                "WHERE interruption_id=?", (key,))
                self.assertTrue(self.store.release_claim(key, "waiting_retry", "released_before_send", 201))
                self.assertEqual(self.counters(key), (0, 0))


# ---------------------------------------------------------- may it be in Codex's queue
def in_codex_queue(state, queue_id):
    """The rule, as a table: sent or being sent, taken back without proof, or an uncertain
    submission that still owns a row in the queue."""
    return state in {"submitting", "queued", "withdrawn_unconfirmed"} or (
        state == "submission_unknown" and queue_id is not None)


class _OneRecord:
    """A store holding one record, for the engine's watch."""

    def __init__(self, row):
        self.row = row

    def records_in(self, states):
        return [dict(self.row)] if self.row["state"] in states else []


class InFlightTests(_StoreCase):
    def cases(self):
        for state in sorted(STATES):
            for queue_id in (None, QUEUE):
                yield state, queue_id

    def test_the_store_counts_another_record_that_may_be_in_the_queue(self):
        for state, queue_id in self.cases():
            with self.subTest(state=state, queue_id=queue_id):
                thread = str(uuid.uuid4())
                self.make(state, thread_id=thread, queue_id=queue_id)
                self.assertEqual(self.store.others_in_flight(thread, "not-this-one"),
                                 1 if in_codex_queue(state, queue_id) else 0)

    def test_the_engine_watches_every_second_for_the_same_records(self):
        for state, queue_id in self.cases():
            with self.subTest(state=state, queue_id=queue_id):
                engine = Engine(_OneRecord({"state": state, "queue_id": queue_id}), None, None)
                self.assertIs(engine.watch_needed(), in_codex_queue(state, queue_id))


# ------------------------------------------------------------------ opening the state
@contextmanager
def an_older_watcher(state_dir):
    """The single-instance mutex, held by another thread as an older watcher holds it."""
    held, done = threading.Event(), threading.Event()

    def hold():
        with windows.Mutex(str(state_dir), timeout=0):
            held.set()
            done.wait(30)

    thread = threading.Thread(target=hold, daemon=True)
    thread.start()
    if not held.wait(10):
        raise AssertionError("the mutex was not taken")
    try:
        yield
    finally:
        done.set()
        thread.join(10)


@unittest.skipUnless(sys.platform == "win32", "Windows named objects")
class OpeningTests(unittest.TestCase):
    """The three per-call openers, each with its own policy for an older state (M3 in the
    plan): the watcher's App never offers the older store, the control layer offers it only
    to the actions that reduce automation, and the command line always does."""

    def home(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        paths = config.Paths(Path(temporary.name) / "home")
        paths.ensure()
        return paths

    def older_state(self):
        paths = self.home()
        with legacy_store_module("v0.5.7").Store(paths.state_dir) as old:
            old.register(detection("a" * 64, "0a1b2c3d-0002-7000-8000-00000000000a"), 100.0)
        self.assertEqual(self.version(paths), 2)
        return paths

    def current_state(self, user_version=None):
        paths = self.home()
        with Store(paths.state_dir):
            pass
        if user_version is not None:
            with closing(sqlite3.connect(paths.state_dir / "state.sqlite")) as db:
                db.execute("PRAGMA user_version=%d" % user_version)
        return paths

    def damaged_state(self):
        paths = self.home()
        (paths.state_dir / "state.sqlite").write_bytes(b"not a sqlite file")
        return paths

    @staticmethod
    def version(paths):
        db = sqlite3.connect(paths.state_dir / "state.sqlite")
        try:
            return db.execute("PRAGMA user_version").fetchone()[0]
        finally:
            db.close()

    def app(self, paths):
        scratch = {"LOCALAPPDATA": str(paths.home / "none"), "CODEX_HOME": str(paths.home / "codex")}
        with patch.dict(os.environ, scratch):
            return App(paths, enable_logging=False)

    def openers(self):
        """name -> a function of the paths that opens the state and returns what it got."""
        return {
            "app": lambda paths: self.app(paths).open_store(),
            "cli": lambda paths: cli._open_state(self.app(paths)),
            "control": lambda paths: control.Control(paths)._open(),
            "control, reducing": lambda paths: control.Control(paths)._open(legacy_ok=True),
        }

    def opened(self, opener, paths):
        opened = opener(paths)
        self.addCleanup(opened.close)
        return opened

    def test_a_current_state_opens_as_it_is_everywhere(self):
        for name, opener in self.openers().items():
            with self.subTest(name):
                opened = self.opened(opener, self.current_state())
                self.assertIsInstance(opened, Store)

    def test_an_older_state_is_upgraded_by_whoever_opens_it_while_no_watcher_holds_it(self):
        for name, opener in self.openers().items():
            with self.subTest(name):
                paths = self.older_state()
                self.assertIsInstance(self.opened(opener, paths), Store)
                self.assertEqual(self.version(paths), 3)

    def test_an_older_state_under_an_older_watcher_is_opened_as_each_caller_decides(self):
        answers = {}
        for name, opener in self.openers().items():
            paths = self.older_state()
            with an_older_watcher(paths.state_dir):
                try:
                    opened = self.opened(opener, paths)
                    answers[name] = type(opened).__name__
                except UpgradePending as exc:
                    answers[name] = "UpgradePending: " + str(exc)[:15]
                except control.ControlError as exc:
                    answers[name] = "ControlError: " + exc.code
            self.assertEqual(self.version(paths), 2, "nothing migrates under an older watcher")
        self.assertEqual(answers, {
            "app": "UpgradePending: Upgrade pending",
            "cli": LegacyStore.__name__,
            "control": "ControlError: upgrade_pending",
            "control, reducing": LegacyStore.__name__,
        })

    def test_a_newer_or_damaged_state_is_refused_the_same_way_whatever_the_policy(self):
        for state, app_error, code in ((lambda: self.current_state(user_version=4), StateFromNewerVersion,
                                        "newer_state"),
                                       (self.damaged_state, StoreError, "store_unavailable")):
            for name, opener in self.openers().items():
                with self.subTest(name=name, code=code):
                    paths = state()
                    if name.startswith("control"):
                        with self.assertRaises(control.ControlError) as caught:
                            opener(paths)
                        self.assertEqual(caught.exception.code, code)
                    else:
                        with self.assertRaises(app_error) as caught:
                            opener(paths)
                        if app_error is StoreError:
                            self.assertNotIsInstance(caught.exception, (StateFromNewerVersion, UpgradePending))


# ---------------------------------------------------------- the user's own words
CUSTOM_TEXT = frozenset({"custom_message"} | {"custom_message_" + category for category in reasons.RECOVERABLE})


class CustomTextTests(unittest.TestCase):
    """Custom continuation text is sent into the user's conversations on their behalf, so
    every surface has to know which fields hold it: the settings layer explains a refusal of
    it, the window draws it as free text, the MCP server never offers it to a model, the
    Preview validates it, and the diagnostics bundle never quotes it (asserted in
    test_diagnostics). `custom_message_mode` is not text: it chooses which message is used."""

    def test_the_settings_layer_explains_and_describes_exactly_these_fields(self):
        self.assertEqual(set(settings.EXPLAIN), CUSTOM_TEXT)
        described = {entry["name"]: entry for entry in settings.describe()}
        self.assertEqual({name for name, entry in described.items() if entry.get("multiline")}, CUSTOM_TEXT)
        self.assertEqual(described["custom_message_mode"]["group"], "continuation")
        self.assertNotIn("multiline", described["custom_message_mode"])

    def test_the_mcp_server_offers_none_of_them_to_a_model(self):
        offered = set(mcpserver.settings_schema()["properties"])
        self.assertEqual(offered & CUSTOM_TEXT, set())
        self.assertIn("custom_message_mode", offered)

    def test_the_preview_validates_them_and_only_them_as_text(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        facade = control.Control(Path(temporary.name))
        too_long = "x" * (continuation.MAX_CUSTOM_LENGTH + 1)
        for name in sorted(CUSTOM_TEXT):
            with self.subTest(name):
                preview = facade.preview_continuation("server_5xx", {name: too_long}, now=NOW)
                self.assertEqual(preview["refusal_code"], "too_long")
                blank = facade.preview_continuation("server_5xx", {name: "   "}, now=NOW)
                self.assertIsNone(blank["refusal"], "blank text is no message, not a refusal")
        preview = facade.preview_continuation("server_5xx", {"custom_message_mode": too_long}, now=NOW)
        self.assertIsNone(preview["refusal"])


# -------------------------------------------------------------------- how many days
DAYS = ((None, True), (1, True), (7, True), (1.5, True), (3650, True), (0, False), (0.5, False),
        (3650.5, False), (3651, False), (-1, False), (True, False), (False, False), ("7", False),
        ([7], False), (float("nan"), False), (float("inf"), False))


class DaysTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.control = control.Control(Path(temporary.name))
        for name, value in (("watcher_running", False), ("startup_enabled", False)):
            guard = patch.object(control.Control, name, return_value=value)
            guard.start()
            self.addCleanup(guard.stop)

    def test_the_bridge_and_the_mcp_server_take_the_same_days(self):
        server = mcpserver.Server(self.control, io.StringIO(), io.StringIO())
        for days, accepted in DAYS:
            with self.subTest(days=days):
                reply = controlcli.dispatch(self.control, "statistics", {"days": days})
                self.assertEqual(reply["ok"], accepted)
                try:
                    server._call_tool({"name": "get_recovery_statistics", "arguments": {"days": days}})
                    answered = True
                except control.ControlError as exc:
                    answered = False
                    self.assertEqual(str(exc), "days must be a number from 1 to 3650")
                self.assertEqual(answered, accepted)
                if not accepted:
                    self.assertEqual(reply["error"], "days must be a number from 1 to 3650")


# ----------------------------------------------------------------- the installed home
class InstalledHomeTests(unittest.TestCase):
    """An installed copy keeps its state one level above `app/`; a checkout is its own home."""

    def homes(self, run):
        found = []
        installed = Path(tempfile.gettempdir()) / "someone" / ".codex-auto-resume" / "app"
        for root, expected in ((installed, str(installed.parent)), (installed.parent / "checkout", None)):
            with self.subTest(root=str(root)), patch.object(config, "PROJECT_ROOT", root), \
                    patch.object(sys, "stdout", io.StringIO()), patch.object(sys, "stdin", io.StringIO()):
                found.append((run(), expected))
        return found

    def test_the_bridge_and_the_mcp_server_find_the_same_home(self):
        def bridge():
            with patch.object(controlcli, "Control") as made, \
                    patch.object(controlcli, "dispatch", return_value={"ok": True}):
                controlcli.main(["status"])
            return made.call_args.args[0]

        def server():
            # `main` reads both from `mcp/server.py`; the module named here re-exports them.
            with patch.object(mcp_server, "Control") as made, patch.object(mcp_server, "Server"):
                mcpserver.main([])
            return made.call_args.args[0]

        for run in (bridge, server):
            for home, expected in self.homes(run):
                self.assertEqual(home, expected)


# ------------------------------------------------------------------------ UTF-8
class _Stream:
    def __init__(self, failure=None):
        self.calls, self.failure = [], failure

    def reconfigure(self, **arguments):
        self.calls.append(arguments)
        if self.failure is not None:
            raise self.failure


class Utf8Tests(unittest.TestCase):
    """Both front ends state UTF-8 on their streams, each in its own way, and each keeps it."""

    def test_the_bridge_states_it_on_both_streams_and_survives_either_refusing(self):
        for failure in (None, AttributeError("no"), ValueError("no"), OSError("no")):
            with self.subTest(failure=failure):
                out, into = _Stream(failure), _Stream()
                with patch.object(sys, "stdout", out), patch.object(sys, "stdin", into):
                    controlcli._use_utf8()
                wanted = [{"encoding": "utf-8", "newline": "\n"}]
                self.assertEqual((out.calls, into.calls), (wanted, wanted))

    def test_the_mcp_server_states_it_on_both_streams_and_tolerates_only_a_missing_method(self):
        def run(out, into):
            with patch.object(sys, "stdout", out), patch.object(sys, "stdin", into), \
                    patch.object(mcp_server, "Control"), patch.object(mcp_server, "Server"):
                mcpserver.main(["--home", "x"])

        out, into = _Stream(), _Stream()
        run(out, into)
        self.assertEqual(out.calls, [{"encoding": "utf-8", "newline": "\n"}])
        self.assertEqual(into.calls, [{"encoding": "utf-8"}], "input keeps its own newline handling")
        # One guard around both: an output with no reconfigure leaves the input alone.
        out, into = _Stream(AttributeError("no")), _Stream()
        run(out, into)
        self.assertEqual(into.calls, [])
        for failure in (ValueError("no"), OSError("no")):
            with self.subTest(failure=failure), self.assertRaises(type(failure)):
                run(_Stream(failure), _Stream())


# -------------------------------------------------------------------------- pages
PAGES = ("overview", "pending", "history", "statistics", "diagnostics", "settings")


class PageTests(unittest.TestCase):
    """A notification's Open button and the icon open the window on one of these pages, and on
    nothing else: the page reaches a command line."""

    def test_the_icon_and_a_notification_know_the_same_pages(self):
        self.assertEqual(tray.PAGES, PAGES)
        for page in PAGES:
            with self.subTest(page):
                self.assertEqual(notify.parse_open_uri(notify.open_uri(page)), page)
                self.assertEqual(notify.parse_open_uri(notify.open_uri(page.upper())), page)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        for page in ("", "overview2", "Overview", "pending;x", "--exec", "timeline"):
            with self.subTest(page):
                if page.lower() not in PAGES:
                    self.assertIsNone(notify.parse_open_uri(notify.open_uri(page)))
                with self.assertRaises(ValueError):
                    tray.open_dashboard(Path(temporary.name), page)


# ------------------------------------------------------------------ a plausible time
class Stamp(int):
    """An int that is not exactly `int`: the callers disagree about it."""


EPOCHS = (-1, 0, 1, 946684799, 946684800, 1700000000, 1.7e9, 1700000000.5, 4102444800, 4102444801,
          253402300799, 253402300800, True, False, math.nan, math.inf, -math.inf, "1700000000",
          None, Stamp(1700000000))


def accepted_by(check):
    found = []
    for value in EPOCHS:
        try:
            ok = check(value)
        except (StoreError, ValueError):
            ok = False
        if ok:
            found.append(value)
    return found


class EpochTests(unittest.TestCase):
    """Four windows of "a plausible time", and they do not agree - which is recorded as
    known drift for v0.6.8 rather than unified here, because unifying would change what some
    caller accepts. The store takes anything from the epoch to the year 9999; Codex's history
    and the registry take 2000 to 2100; the App Server's usage windows take whole seconds only,
    from 1 to 2100. The store and the registry take a subclass of int, the history and the App
    Server do not."""

    def test_the_store_accepts_the_epoch_to_the_year_9999(self):
        self.assertEqual(accepted_by(lambda value: store_module._timestamp(value, "at") is not None),
                         [0, 1, 946684799, 946684800, 1700000000, 1.7e9, 1700000000.5, 4102444800,
                          4102444801, 253402300799, Stamp(1700000000)])

    def test_codex_history_accepts_2000_to_2100(self):
        self.assertEqual(accepted_by(codex.epoch),
                         [946684800, 1700000000, 1.7e9, 1700000000.5, 4102444800])

    def test_the_app_servers_usage_windows_accept_whole_seconds_to_2100(self):
        """Read where the App Server's answer is read: a window's reset time outside this makes
        the whole snapshot unknown, and one inside it is kept exactly as it came."""
        def usage(value):
            return windows.parse_usage({"rateLimitsByLimitId": {"codex": {"primary": {
                "usedPercent": 100, "windowDurationMins": 300, "resetsAt": value}}}})

        self.assertEqual(accepted_by(lambda value: value is not None
                                     and usage(value)["reason"] != "usage_snapshot_unknown"),
                         [1, 946684799, 946684800, 1700000000, 4102444800])
        self.assertIs(type(usage(1700000000)["reset_at"]), int)
        self.assertEqual(usage(1700000000)["windows"][0]["reset_at"], 1700000000)
        self.assertIsNone(usage(None)["reset_at"], "no reset time is allowed, and stays none")

    def test_an_int_too_large_to_be_a_float_is_read_as_it_always_was(self):
        """Also drift, and kept: the callers that ask math.isfinite raise its OverflowError
        for a whole number past float range, where the App Server's reading only says no."""
        huge = 2 ** 1100
        for check in (lambda: store_module._timestamp(huge, "at"), lambda: codex.epoch(huge),
                      lambda: compat._epoch_or_none(huge)):
            with self.assertRaises(OverflowError):
                check()
        self.assertEqual(windows.parse_usage({"rateLimitsByLimitId": {"codex": {"primary": {
            "usedPercent": 100, "windowDurationMins": 300, "resetsAt": huge}}}})["reason"],
            "usage_snapshot_unknown")

    def test_the_registry_accepts_2000_to_2100(self):
        self.assertEqual(accepted_by(lambda value: value is not None and compat._epoch_or_none(value) is not None),
                         [946684800, 1700000000, 1.7e9, 1700000000.5, 4102444800, Stamp(1700000000)])
        self.assertIsNone(compat._epoch_or_none(None))
        self.assertIs(type(compat._epoch_or_none(1700000000)), float)


# ---------------------------------------------------------------- one implementation each
def sites(match):
    """(file, qualified name) of every node in the package that `match` accepts."""
    found = set()
    for path, tree in srcscan.package_asts().items():
        names = srcscan.qualnames(tree)
        for node in ast.walk(tree):
            if match(node):
                found.add((srcscan.relative(path), names.get(node, "")))
    return found


def constant(node, *values):
    return isinstance(node, ast.Constant) and any(type(node.value) is type(value) and node.value == value
                                                  for value in values)


def compares(node, operator):
    return any(isinstance(child, ast.Compare) and any(isinstance(op, operator) for op in child.ops)
               for child in ast.walk(node))


def literal(node):
    """The constants a tuple, list or set literal spells, or None for any other node."""
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return {element.value for element in node.elts if isinstance(element, ast.Constant)}
    return None


def listed(node):
    """The words a literal spells, or an enum class assigns to its members; None otherwise."""
    if isinstance(node, ast.ClassDef):
        return {statement.value.value for statement in node.body
                if isinstance(statement, ast.Assign) and isinstance(statement.value, ast.Constant)}
    return literal(node)


def calls(name):
    return lambda node: isinstance(node, ast.Call) and getattr(node.func, "attr", getattr(node.func, "id", None)) == name


def names_unknown(node, operator):
    return (isinstance(node, ast.Compare) and isinstance(node.ops[0], operator)
            and any(constant(c, "submission_unknown") for c in node.comparators))


def owns_a_queue_row(node):
    return (isinstance(node, ast.Compare) and isinstance(node.ops[0], ast.IsNot)
            and constant(node.comparators[0], None) and "queue_id" in ast.unparse(node.left))


def may_be_queued_shape(node):
    """"Claimed, queued or taken back - or an uncertain submission that owns a queue row",
    spelled either way round: `... or (state == unknown and queue_id is not None)` as the
    store's gate had it, or `state != unknown or queue_id is not None` over the watched
    states, as the engine's watch did; or as SQL."""
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
        if any(isinstance(value, ast.BoolOp) and isinstance(value.op, ast.And)
               and any(names_unknown(part, ast.Eq) for part in value.values)
               and any(owns_a_queue_row(part) for part in value.values) for value in node.values):
            return True
        return (any(names_unknown(value, ast.NotEq) for value in node.values)
                and any(owns_a_queue_row(value) for value in node.values))
    return (isinstance(node, ast.Constant) and isinstance(node.value, str)
            and "submission_unknown" in node.value and "queue_id IS NOT NULL" in node.value)


def spells(*needles):
    """A string constant that holds any of `needles`: a pattern or a word written out."""
    return lambda node: (isinstance(node, ast.Constant) and isinstance(node.value, str)
                         and any(needle in node.value for needle in needles))


PACKAGE = "codex_auto_resume/"
# Each rule steps 2 and 3 gathered, the shape its implementation has, and the one place that
# has it. A second place is a copy that can drift; moving the rule moves the entry, on purpose.
RULES = {
    "which wait a record goes back to": (
        lambda node: isinstance(node, ast.IfExp) and constant(node.body, "waiting_reset")
        and constant(node.orelse, "waiting_poll") and compares(node.test, ast.Gt),
        {"machine.py": "waiting_state"}),
    "what a claim costs": (
        lambda node: isinstance(node, ast.IfExp) and constant(node.body, 0) and constant(node.orelse, 1)
        and any(calls("is_usage")(child) for child in ast.walk(node.test)),
        {"store/validate.py": "_claim_cost"}),
    "a budget counter charged or refunded in SQL by hand": (
        lambda node: isinstance(node, ast.Constant) and isinstance(node.value, str) and bool(re.search(
            r"(recovery_attempts|chain_continuations)\s*=\s*(max\(0,\s*)?\1\s*[-+]", node.value)),
        {}),
    "whether a record may be in Codex's queue": (
        may_be_queued_shape,
        {"machine.py": "may_be_queued"}),
    "the states the watch follows, written out": (
        lambda node: listed(node) == set(WATCHED),
        {}),
    "opening the state for a command, older store and all": (
        calls("LegacyStore"),
        {"openstate.py": "open_state"}),
    "upgrading the state": (
        lambda node: calls("Store")(node) and any(keyword.arg == "migrate" and constant(keyword.value, True)
                                                   for keyword in node.keywords),
        # The watcher's own opening holds the mutex already and upgrades at start.
        {"openstate.py": "open_state", "app.py": "App._open_for_watcher"}),
    "which settings are the user's own words": (
        lambda node: calls("startswith")(node) and bool(node.args) and isinstance(node.args[0], ast.Constant)
        and str(node.args[0].value).startswith("custom_message"),
        {"settings.py": "is_custom_text"}),
    "how many days a statistics request may cover": (
        lambda node: constant(node, 3650),
        {"controlcli.py": ""}),
    "where an installed copy keeps its home": (
        lambda node: isinstance(node, ast.Compare) and any(constant(c, "app") for c in node.comparators)
        and isinstance(node.left, ast.Attribute) and node.left.attr == "name",
        {"config.py": "installed_home"}),
    "how a front end states UTF-8": (
        calls("reconfigure"),
        {"controlcli.py": "use_utf8"}),
    "the window's pages": (
        lambda node: (listed(node) or set()) >= {"overview", "statistics", "diagnostics"},
        {"domain/vocabulary.py": "Page"}),
    "a plausible time's bounds": (
        lambda node: constant(node, 253402300799, 946684800, 4102444800),
        {"machine.py": ""}),
    # Step 3: every identifier is read in domain/ids.py.
    "parsing a UUID": (
        calls("UUID"),
        {"domain/ids.py": "uuid_problem"}),
    "a UUID's pattern": (
        lambda node: spells("{8}-")(node) or (isinstance(node, ast.Tuple)
                                              and [getattr(e, "value", None) for e in node.elts] == [8, 4, 4, 4, 12]),
        {"domain/ids.py": ""}),
    "an interruption id's hex digits": (
        # The registry's evidence digest (compat.HEX64_RE) is spelled alike and is another kind
        # of thing: the SHA-256 of a document the registry cites, never a record's id.
        spells("0123456789abcdef", "[0-9a-f]{64}", "[0-9a-fA-F]{64}"),
        {"domain/ids.py": "", "compat.py": ""}),
    "an interruption's identity": (
        lambda node: calls("hex")(node) and isinstance(node.func.value, ast.Call)
        and getattr(node.func.value.func, "id", None) == "float",
        {"domain/ids.py": "interruption_id"}),
    "the marker": (
        spells("[codex-auto-resume:"),
        {"domain/ids.py": ""}),
    "a client id's pattern": (
        spells("[A-Za-z0-9-]{1,64}"),
        {"domain/ids.py": ""}),
    "a stored record key's pattern": (
        spells("[A-Za-z0-9_-]{1,128}"),
        {"domain/ids.py": ""}),
}


class OneImplementationTests(unittest.TestCase):
    """Each rule above has exactly one implementation in the package, found by its shape
    wherever it is - so a copy written into another module, or back into the one it left, is a
    failure, and a rule that moves takes its entry here with it."""

    def test_each_rule_has_exactly_one_implementation(self):
        for rule, (match, expected) in RULES.items():
            with self.subTest(rule):
                self.assertEqual(sites(match), {(PACKAGE + where, name) for where, name in expected.items()})

    def test_the_shapes_would_see_a_copy(self):
        """A copy of each rule, the way the old ones were written, is found by its shape."""
        copies = {
            "which wait a record goes back to":
                'x = "waiting_reset" if row["reset_at"] is not None and row["reset_at"] > now else "waiting_poll"',
            "what a claim costs": "x = 0 if is_usage(row) else 1",
            "a budget counter charged or refunded in SQL by hand":
                'x = "recovery_attempts=max(0, recovery_attempts-?), chain_continuations=chain_continuations+1"',
            "whether a record may be in Codex's queue":
                'x = row["state"] != "submission_unknown" or row["queue_id"] is not None',
            "the states the watch follows, written out":
                'x = {"submitting", "queued", "withdrawn_unconfirmed", "submission_unknown"}',
            "opening the state for a command, older store and all": "x = LegacyStore(d)",
            "upgrading the state": "x = Store(d, migrate=True)",
            "which settings are the user's own words": 'x = name.startswith("custom_message")',
            "how many days a statistics request may cover": "x = 1 <= days <= 3650",
            "where an installed copy keeps its home": 'x = root.parent if root.name == "app" else None',
            "how a front end states UTF-8": 'sys.stdout.reconfigure(encoding="utf-8")',
            "the window's pages": 'x = ("overview", "pending", "history", "statistics", "diagnostics", "settings")',
            "a plausible time's bounds": "x = 0 <= v <= 253402300799",
            "parsing a UUID": "x = str(uuid.UUID(value)) == value",
            "a UUID's pattern": 'x = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")',
            "an interruption id's hex digits": 'x = any(c not in "0123456789abcdef" for c in text)',
            "an interruption's identity": "x = float(identity[2]).hex()",
            "the marker": 'x = f"[codex-auto-resume:{key}]"',
            "a client id's pattern": 'x = re.compile(r"[A-Za-z0-9-]{1,64}")',
            "a stored record key's pattern": 'x = re.compile(r"[A-Za-z0-9_-]{1,128}")',
        }
        self.assertEqual(set(copies), set(RULES))
        copies["the other spelling of whether a record may be in Codex's queue"] = (
            'x = state in S or (state == "submission_unknown" and row["queue_id"] is not None)')
        copies["the same, as SQL"] = "x = 'OR (state=submission_unknown AND queue_id IS NOT NULL)'"
        copies["an interruption id, as a pattern"] = 'x = re.compile(r"[codex-auto-resume:[0-9a-f]{64}]")'
        for rule, source in copies.items():
            with self.subTest(rule):
                match = RULES[rule][0] if rule in RULES else RULES[{
                    "an interruption id, as a pattern": "an interruption id's hex digits"}.get(
                        rule, "whether a record may be in Codex's queue")][0]
                self.assertTrue(any(match(node) for node in ast.walk(ast.parse(source))), source)


if __name__ == "__main__":
    unittest.main()
