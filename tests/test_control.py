"""The shared control surface and the JSON bridge the front ends drive it through.

Two things are being protected here.

The first is that every interface means the same thing. The command line, the Codex
skill, the MCP server and the standalone settings window all call this layer, so a
value written by one has to be exactly what the others read back.

The second is that control stays control. Nothing in this layer may recover: no action
here sends a continuation, resolves a thread by anything but its exact id, or hands a
record a shortcut past the watcher's gates. "Retry now" in particular only moves a
schedule forward - the tests assert on the state it leaves behind, because a version
that quietly submitted would still look like it worked from the outside.
"""
from __future__ import annotations

import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from codex_auto_resume import config, control, controlcli, settings
from codex_auto_resume.store import Store, StoreError

THREAD = "0a1b2c3d-0001-7000-8000-000000000001"
TURN = "0a1b2c3d-0002-7000-8000-000000000002"
KEY = "a" * 64
OTHER_KEY = "b" * 64


def detection(key=KEY, thread_id=THREAD, category="usage_limit"):
    return {"thread_id": thread_id, "turn_id": TURN, "completed_at": 110.0,
            "started_at": 105.0, "ordinal": 2, "interruption_id": key,
            "reset_at": 150.0, "limit_type": "codex.primary", "uncertain": False,
            "category": category}


class ControlTestCase(unittest.TestCase):
    """Every test runs against an isolated home; nothing touches the real install."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name)
        self.paths = config.Paths(self.home)
        self.paths.ensure()
        self.control = control.Control(self.paths)
        # The watcher probe and the registry are the only Codex/Windows dependencies in
        # this layer; both are patched so the tests describe the layer, not the machine.
        self.running = patch.object(control.Control, "watcher_running", return_value=False)
        self.startup = patch.object(control.Control, "startup_enabled", return_value=False)
        self.running.start()
        self.startup.start()

    def tearDown(self):
        self.startup.stop()
        self.running.stop()
        self.temporary.cleanup()

    def register(self, **kwargs):
        with Store(self.paths.state_dir) as store:
            store.register(detection(**kwargs), 100.0)


class SettingsSurfaceTests(ControlTestCase):
    def test_reads_defaults_before_anything_is_written(self):
        self.assertEqual(self.control.get_settings(), settings.defaults())

    def test_settings_file_is_not_created_by_reading(self):
        self.control.get_settings()
        self.assertFalse(self.paths.settings_file.exists())

    def test_update_persists_and_reads_back(self):
        self.control.update_settings({"max_recovery_attempts": 9})
        self.assertEqual(self.control.get_settings()["max_recovery_attempts"], 9)

    def test_invalid_update_is_refused_with_a_showable_message(self):
        with self.assertRaises(control.ControlError) as caught:
            self.control.update_settings({"max_recovery_attempts": 999})
        self.assertIn("max_recovery_attempts", str(caught.exception))

    def test_unknown_setting_is_refused(self):
        with self.assertRaises(control.ControlError):
            self.control.update_settings({"retry_unknown_failures": True})

    def test_restore_defaults_writes_a_complete_file(self):
        self.control.update_settings({"max_recovery_attempts": 9})
        self.control.restore_defaults()
        self.assertEqual(self.control.get_settings(), settings.defaults())

    def test_describe_matches_what_update_accepts(self):
        for entry in self.control.describe_settings():
            if entry["type"] == "boolean":
                self.control.update_settings({entry["name"]: False})
                self.assertIs(self.control.get_settings()[entry["name"]], False)

    def test_settings_work_with_no_state_database(self):
        # Configuration must never depend on the store, Codex or the watcher: a user
        # changes policy exactly when the thing it governs is unavailable.
        for path in sorted(self.paths.state_dir.glob("state.sqlite*")):
            path.unlink()
        self.control.update_settings({"notifications": False})
        self.assertIs(self.control.get_settings()["notifications"], False)


class StatusTests(ControlTestCase):
    def test_status_reports_the_shared_settings(self):
        self.control.update_settings({"max_no_progress": 6})
        self.assertEqual(self.control.get_status()["settings"]["max_no_progress"], 6)

    def test_status_counts_pending(self):
        self.register()
        self.assertEqual(self.control.get_status()["pending"], 1)

    def test_status_reports_the_global_switch(self):
        self.control.set_enabled(False)
        self.assertIs(self.control.get_status()["enabled"], False)
        self.control.set_enabled(True)
        self.assertIs(self.control.get_status()["enabled"], True)

    def test_pause_preserves_pending_records(self):
        self.register()
        self.control.set_enabled(False)
        self.assertEqual(len(self.control.list_pending()), 1)

    def test_enabled_must_be_a_boolean(self):
        for value in ("true", 1, None):
            with self.assertRaises(control.ControlError):
                self.control.set_enabled(value)


class PendingTests(ControlTestCase):
    def test_pending_excludes_terminal_records_by_default(self):
        self.register()
        with Store(self.paths.state_dir) as store:
            store.update(KEY, state="superseded")
        self.assertEqual(self.control.list_pending(), [])
        self.assertEqual(len(self.control.list_pending(include_terminal=True)), 1)

    def test_listing_never_needs_codex(self):
        self.register()
        listed = self.control.list_pending()
        self.assertIsNone(listed[0]["name"])
        self.assertEqual(listed[0]["interruption_id"], KEY)
        # A record that was never reset has every reset still available.
        self.assertEqual(listed[0]["budget_resets_left"], control.MAX_BUDGET_RESETS)

    def test_a_failing_identity_lookup_does_not_break_the_listing(self):
        # Labels are decoration. A source that raises must cost a name, not the list.
        class Broken:
            def identity(self, _thread_id):
                raise RuntimeError("codex is not running")

        self.register()
        listed = self.control.list_pending(source=Broken())
        self.assertEqual(len(listed), 1)
        self.assertIsNone(listed[0]["name"])


class IdentifierTests(ControlTestCase):
    def test_actions_reject_anything_but_an_exact_interruption_id(self):
        self.register()
        for bad in ("", None, "latest", KEY[:-1], KEY + "0", "g" * 64, "../" + KEY[3:]):
            for action in (self.control.cancel_interruption,
                           self.control.reset_recovery_budget,
                           self.control.request_retry_now):
                with self.assertRaises(control.ControlError):
                    action(bad)

    def test_thread_actions_require_canonical_lowercase_uuid_text(self):
        for bad in ("", None, "last", THREAD.upper(), THREAD.replace("-", ""), THREAD + " "):
            with self.assertRaises(control.ControlError):
                self.control.cancel_thread(bad)

    def test_unknown_interruption_is_reported_not_invented(self):
        with self.assertRaises(control.ControlError):
            self.control.cancel_interruption(OTHER_KEY)


class CancelTests(ControlTestCase):
    def test_cancel_marks_the_record_cancelled(self):
        self.register()
        result = self.control.cancel_interruption(KEY)
        self.assertEqual(result["thread_id"], THREAD)
        with Store(self.paths.state_dir) as store:
            self.assertEqual(store.get(KEY)["state"], "cancelled")

    def test_cancel_disables_the_thread(self):
        self.register()
        self.control.cancel_thread(THREAD)
        with Store(self.paths.state_dir) as store:
            self.assertFalse(store.thread_enabled(THREAD))


class BudgetTests(ControlTestCase):
    def exhaust(self, state="retry_budget_exhausted", category="usage_limit"):
        self.register(category=category)
        with Store(self.paths.state_dir) as store:
            store.update(KEY, state=state, recovery_attempts=4, no_progress_count=3)
            store.set_thread_enabled(THREAD, False)

    def test_reset_returns_a_record_to_the_wait_its_kind_of_failure_needs(self):
        # A usage limit whose reset has passed polls for usage; a temporary failure
        # waits out its backoff. Neither is sent by the reset itself.
        self.exhaust()
        self.control.reset_recovery_budget(KEY)
        with Store(self.paths.state_dir) as store:
            record = store.get(KEY)
        self.assertEqual(record["state"], "waiting_poll")
        self.assertEqual(record["recovery_attempts"], 0)
        self.assertEqual(record["no_progress_count"], 0)

    def test_a_transient_record_returns_to_its_backoff(self):
        self.exhaust(category="server_5xx")
        self.control.reset_recovery_budget(KEY)
        with Store(self.paths.state_dir) as store:
            self.assertEqual(store.get(KEY)["state"], "waiting_backoff")

    def test_reset_leaves_a_switched_off_conversation_off(self):
        # Switching recovery back on for a conversation is its own decision; a reset
        # that did it too would undo a cancel the user never took back.
        self.exhaust()
        result = self.control.reset_recovery_budget(KEY)
        with Store(self.paths.state_dir) as store:
            self.assertFalse(store.thread_enabled(THREAD))
        self.assertIn("switch it on", result["note"])

    def test_reset_also_covers_the_no_progress_budget(self):
        self.exhaust(state="no_progress_exhausted", category="timeout")
        self.control.reset_recovery_budget(KEY)
        with Store(self.paths.state_dir) as store:
            self.assertEqual(store.get(KEY)["state"], "waiting_backoff")

    def test_reset_is_bounded_per_task(self):
        self.exhaust(category="timeout")
        for _ in range(3):
            self.control.reset_recovery_budget(KEY)
            with Store(self.paths.state_dir) as store:
                store.update(KEY, state="retry_budget_exhausted")
        with self.assertRaises(control.ControlError) as caught:
            self.control.reset_recovery_budget(KEY)
        self.assertIn("yourself", str(caught.exception))
        # The listing says so in advance, so a front end can disable the button rather
        # than offer one whose only answer is this refusal.
        listed = self.control.list_pending(include_terminal=True)
        self.assertEqual(listed[0]["budget_resets_left"], 0)

    def test_reset_refuses_a_record_that_is_not_exhausted(self):
        self.register()
        with self.assertRaises(control.ControlError):
            self.control.reset_recovery_budget(KEY)

    def test_reset_does_not_submit(self):
        # It restores a budget; the watcher still has to earn the send.
        self.exhaust()
        self.control.reset_recovery_budget(KEY)
        with Store(self.paths.state_dir) as store:
            record = store.get(KEY)
        self.assertIsNone(record["submitted_at"])
        self.assertIsNone(record["queue_id"])
        self.assertEqual(record["attempt_count"], 0)


class RetryNowTests(ControlTestCase):
    def test_retry_now_only_moves_the_schedule(self):
        self.register()
        with Store(self.paths.state_dir) as store:
            before = store.get(KEY)
        self.control.request_retry_now(KEY)
        with Store(self.paths.state_dir) as store:
            after = store.get(KEY)
        self.assertLessEqual(after["next_retry_at"], time.time())
        # Everything that would constitute a send is untouched.
        for field in ("state", "attempt_count", "submitted_at", "queue_id",
                      "recovery_attempts", "resumed_at"):
            self.assertEqual(after[field], before[field], field)

    def test_retry_now_refuses_a_finished_recovery(self):
        self.register()
        with Store(self.paths.state_dir) as store:
            store.update(KEY, state="superseded")
        with self.assertRaises(control.ControlError):
            self.control.request_retry_now(KEY)

    def test_retry_now_refuses_a_cancelled_recovery(self):
        self.register()
        self.control.cancel_thread(THREAD)
        with Store(self.paths.state_dir) as store:
            store.update(KEY, cancel_requested=True)
        with self.assertRaises(control.ControlError):
            self.control.request_retry_now(KEY)

    def test_retry_now_says_the_checks_still_apply(self):
        self.register()
        self.assertIn("safety check", self.control.request_retry_now(KEY)["note"])


class NotARecoveryEngineTests(ControlTestCase):
    def test_the_control_layer_exposes_no_send(self):
        # A second path to submission is the failure mode this whole layer is designed
        # to avoid, so the absence is asserted rather than assumed.
        forbidden = ("submit", "send", "resume", "reserve", "continue")
        for name in dir(control.Control):
            if name.startswith("_"):
                continue
            self.assertFalse(any(word in name for word in forbidden), name)

    def test_the_module_never_imports_the_engine_or_the_source(self):
        text = Path(control.__file__).read_text(encoding="utf-8")
        for module in ("engine", "source", "messages"):
            self.assertNotIn("from .%s import" % module, text)
            self.assertNotIn("from . import %s" % module, text)


class BridgeTests(ControlTestCase):
    """The JSON bridge: one object out, no tracebacks, no paths in error text."""

    def run_bridge(self, *argv):
        stream = io.StringIO()
        with patch("sys.stdout", stream):
            code = controlcli.main(["--home", str(self.home), *argv])
        return code, json.loads(stream.getvalue())

    def test_status_is_a_single_json_object(self):
        code, payload = self.run_bridge("status")
        self.assertEqual(code, 0)
        self.assertIs(payload["ok"], True)
        self.assertIn("version", payload["status"])

    def test_describe_matches_the_shared_schema(self):
        _code, payload = self.run_bridge("describe")
        self.assertEqual([entry["name"] for entry in payload["schema"]],
                         [entry["name"] for entry in settings.describe()])

    def test_update_round_trips_through_the_bridge(self):
        code, payload = self.run_bridge("update", json.dumps({"max_no_progress": 8}))
        self.assertEqual(code, 0)
        self.assertEqual(payload["settings"]["max_no_progress"], 8)
        self.assertEqual(self.control.get_settings()["max_no_progress"], 8)

    def test_a_value_written_by_the_bridge_is_what_the_control_layer_reads(self):
        # The cross-interface guarantee, stated as a test: one authoritative layer.
        self.control.update_settings({"retry_timing": "conservative"})
        _code, payload = self.run_bridge("settings")
        self.assertEqual(payload["settings"]["retry_timing"], "conservative")

    def test_rejected_update_reports_a_clean_failure(self):
        code, payload = self.run_bridge("update", json.dumps({"max_no_progress": 99}))
        self.assertEqual(code, 1)
        self.assertIs(payload["ok"], False)
        self.assertNotIn("Traceback", payload["error"])

    def test_malformed_json_argument_is_refused(self):
        code, payload = self.run_bridge("update", "{not json")
        self.assertEqual(code, 1)
        self.assertIn("JSON", payload["error"])

    def test_internal_failure_leaks_neither_traceback_nor_path(self):
        with patch.object(control.Control, "get_status", side_effect=RuntimeError(str(self.home))):
            code, payload = self.run_bridge("status")
        self.assertEqual(code, 1)
        self.assertNotIn(str(self.home), payload["error"])
        self.assertNotIn("Traceback", payload["error"])

    def test_pending_listing_is_available_through_the_bridge(self):
        self.register()
        _code, payload = self.run_bridge("pending")
        self.assertEqual(payload["pending"][0]["interruption_id"], KEY)

    def test_bridge_rejects_a_bad_interruption_id(self):
        code, payload = self.run_bridge("cancel", json.dumps({"interruption_id": "latest"}))
        self.assertEqual(code, 1)
        self.assertIs(payload["ok"], False)

    def test_bridge_exposes_no_command_that_sends(self):
        parser = controlcli.build_parser()
        actions = [action for action in parser._actions if action.dest == "command"]
        names = sorted(actions[0].choices)
        self.assertEqual(names, sorted([
            "cancel", "defaults", "describe", "enabled", "pending", "pending-all",
            "reset-budget", "retry-now", "settings", "start-watcher", "startup",
            # `strings` is a read like `describe`: it returns the interface vocabulary
            # for the resolved language and touches nothing.
            "status", "strings", "update",
            # Reads, and switches that only reduce automation or hide history. Turning a
            # conversation back on sends nothing; the watcher's gates still decide.
            "history", "timeline", "statistics", "clear-history", "thread-enabled",
            "cancel-thread",
            # Writes a redacted local file the user chose; it sends nothing anywhere.
            "diagnostics",
            # A read of several of the above at once, and the long-lived form of this
            # same command table - not a command of its own.
            "dashboard", "serve"]))

    def test_serve_answers_every_line_with_exactly_one_line(self):
        requests = "\n".join([
            json.dumps({"id": 1, "command": "settings"}),
            "not json",
            json.dumps({"id": 3, "command": "no-such-command"}),
            json.dumps({"id": 4, "command": "retry-now", "argument": {"interruption_id": "latest"}}),
            json.dumps({"id": 5, "command": "dashboard"}),
        ]) + "\n"
        out = io.StringIO()
        controlcli.serve(self.control, io.StringIO(requests), out)
        replies = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual([reply["id"] for reply in replies], [1, None, 3, 4, 5])
        self.assertTrue(replies[0]["reply"]["ok"])
        self.assertEqual(replies[0]["reply"]["settings"], self.control.get_settings())
        self.assertFalse(replies[1]["reply"]["ok"])
        self.assertEqual(replies[2]["reply"]["error"], "unknown command")
        self.assertIn("invalid interruption id", replies[3]["reply"]["error"])
        self.assertTrue(replies[4]["reply"]["ok"])
        for key in ("status", "pending", "history", "week"):
            self.assertIn(key, replies[4]["reply"])

    def serve_lines(self, lines):
        out = io.StringIO()
        self.assertEqual(controlcli.serve(self.control, io.StringIO("\n".join(lines) + "\n"), out), 0)
        return [json.loads(line) for line in out.getvalue().splitlines()]

    def test_a_dashboard_part_that_fails_costs_only_that_part(self):
        # Not a ControlError: a store failure used to escape the per-part handler and
        # take the whole Overview down with it, status included.
        with patch.object(Store, "history", side_effect=StoreError(str(self.home))):
            code, payload = self.run_bridge("dashboard")
        self.assertEqual(code, 0)
        self.assertIs(payload["ok"], True)
        for key in ("status", "pending", "week"):
            self.assertIn(key, payload)
        self.assertNotIn("history", payload)
        self.assertEqual(payload["history_error"], "the request could not be completed")
        self.assertNotIn(str(self.home), json.dumps(payload))

    def test_serve_answers_an_argument_of_the_wrong_type_and_keeps_going(self):
        # Each of these reached `json.loads` as a non-string and raised TypeError, which
        # ended the loop and left the window waiting for a reply that never came.
        lines = []
        for number, argument in ((1, [1]), (3, 5), (5, True)):
            lines.append(json.dumps({"id": number, "command": "statistics", "argument": argument}))
            lines.append(json.dumps({"id": number + 1, "command": "settings"}))
        replies = self.serve_lines(lines)
        self.assertEqual([reply["id"] for reply in replies], [1, 2, 3, 4, 5, 6])
        for reply in replies[0::2]:
            self.assertEqual(reply["reply"], {"ok": False, "error": "argument must be a JSON object"})
        for reply in replies[1::2]:
            self.assertIs(reply["reply"]["ok"], True)

    def test_serve_framing_edge_cases_each_get_the_answer_they_should(self):
        replies = self.serve_lines([
            # A byte-order mark in front of the first request is not part of it.
            "\ufeff" + json.dumps({"id": 1, "command": "settings"}),
            # Blank and whitespace-only lines are not requests, so they get no reply.
            "",
            "   \t ",
            json.dumps({"id": True, "command": "settings"}),
            "x" * (controlcli.MAX_LINE + 1),
            # Nested past the parser's recursion limit while still under MAX_LINE: this
            # raises RecursionError, not ValueError, and used to end the loop.
            "[" * 50000,
            json.dumps({"id": 7, "command": "settings"}),
        ])
        self.assertEqual([(reply["reply"]["ok"], reply["reply"].get("error")) for reply in replies], [
            (True, None),
            (False, "id must be an integer"),
            (False, "request too large"),
            (False, "request must be JSON"),
            (True, None),
        ])
        self.assertEqual([replies[index]["id"] for index in (0, 2, 3, 4)], [1, None, None, 7])

    def test_serve_cannot_reach_anything_the_one_shot_form_cannot(self):
        # The same table: a command the parser does not offer is not reachable over
        # the long-lived pipe either.
        parser = controlcli.build_parser()
        offered = set([action for action in parser._actions if action.dest == "command"][0].choices)
        self.assertEqual(set(controlcli.PLAIN + controlcli.WITH_ARGUMENT) | {"serve"}, offered)


class StartWatcherTests(ControlTestCase):
    """Starting the watcher is control, not recovery.

    It launches the same process the installer launches and then has nothing more to do
    with it. The tests below pin that down: it decides nothing about any interruption,
    and it never runs a second watcher alongside a live one.
    """

    def test_it_launches_the_stable_launcher_when_one_is_installed(self):
        (self.home / "watcher-launcher.py").write_text("# launcher" + chr(10), encoding="utf-8")
        with patch("subprocess.Popen") as popen:
            result = self.control.start_watcher()
        self.assertIs(result["started"], True)
        argv = popen.call_args.args[0]
        self.assertEqual(Path(argv[1]).name, "watcher-launcher.py")
        self.assertEqual(argv[-1], "run")

    def test_it_refuses_to_start_a_second_watcher(self):
        # Two watchers with the same state could each resume the same interruption.
        with patch.object(control.Control, "watcher_running", return_value=True),              patch("subprocess.Popen") as popen:
            result = self.control.start_watcher()
        self.assertIs(result["started"], False)
        popen.assert_not_called()

    def test_an_unknown_probe_result_still_allows_a_start(self):
        # None means the probe failed, not that a watcher is running; the single-instance
        # mutex is what actually prevents a second one, and it is checked by the watcher.
        (self.home / "watcher-launcher.py").write_text("# launcher" + chr(10), encoding="utf-8")
        with patch.object(control.Control, "watcher_running", return_value=None),              patch("subprocess.Popen") as popen:
            self.assertIs(self.control.start_watcher()["started"], True)
        popen.assert_called_once()

    def test_it_reports_a_missing_installation_rather_than_failing_silently(self):
        self.paths.entry_script = self.home / "nowhere.py"
        with patch.object(control.Control, "watcher_running", return_value=False):
            with self.assertRaises(control.ControlError):
                self.control.start_watcher()

    def test_starting_touches_no_interruption(self):
        self.register()
        (self.home / "watcher-launcher.py").write_text("# launcher" + chr(10), encoding="utf-8")
        with Store(self.paths.state_dir) as store:
            before = store.get(KEY)
        with patch("subprocess.Popen"):
            self.control.start_watcher()
        with Store(self.paths.state_dir) as store:
            self.assertEqual(store.get(KEY), before)

    def run_bridge(self, *argv):
        stream = io.StringIO()
        with patch("sys.stdout", stream):
            code = controlcli.main(["--home", str(self.home), *argv])
        return code, json.loads(stream.getvalue())

    def test_the_bridge_exposes_it(self):
        (self.home / "watcher-launcher.py").write_text("# launcher" + chr(10), encoding="utf-8")
        with patch("subprocess.Popen"):
            code, payload = self.run_bridge("start-watcher")
        self.assertEqual(code, 0)
        self.assertIs(payload["result"]["started"], True)


class FakeProcess:
    """A `Popen` stand-in whose exit is scheduled rather than raced.

    `poll()` returns None until it has been asked `exits_after` times. Nothing here
    sleeps or depends on wall-clock ordering, so these tests cannot flake.
    """

    def __init__(self, exits_after=None, code=0):
        self.polls = 0
        self.exits_after = exits_after
        self.code = code

    def poll(self):
        self.polls += 1
        if self.exits_after is None:
            return None
        return self.code if self.polls > self.exits_after else None


def scripted(*answers):
    """A `watcher_running` that gives each answer in turn, then repeats the last."""
    remaining = list(answers)

    def probe():
        return remaining.pop(0) if len(remaining) > 1 else remaining[0]
    return probe


class WatcherConfirmationTests(unittest.TestCase):
    """`await_watcher` is the whole difference between launching and running.

    `Popen` returning proves Windows made a process. Every one of these cases is a way
    for that process not to be a working watcher, and before v0.5.5 all of them were
    reported to the user as "The watcher is running."
    """

    def wait(self, probe, process, timeout=0.05):
        return control.await_watcher(probe, process, timeout=timeout, interval=0)

    def test_a_watcher_that_comes_up_is_confirmed(self):
        result = self.wait(scripted(True), FakeProcess())
        self.assertEqual(result["state"], "running")
        self.assertIs(result["confirmed"], True)

    def test_a_watcher_that_takes_a_moment_is_still_confirmed(self):
        # The ordinary case: the mutex is taken after an interpreter has started.
        result = self.wait(scripted(False, False, False, True), FakeProcess())
        self.assertEqual(result["state"], "running")

    def test_a_watcher_that_never_appears_is_not_reported_as_running(self):
        result = self.wait(scripted(False), FakeProcess())
        self.assertEqual(result["state"], "unconfirmed")
        self.assertIs(result["confirmed"], False)

    def test_a_probe_that_stops_working_is_unknown_rather_than_success(self):
        # None means the probe failed, which is not evidence either way - and must
        # never be rounded up to running.
        result = self.wait(scripted(None), FakeProcess())
        self.assertEqual(result["state"], "unconfirmed")
        self.assertIs(result["confirmed"], False)

    def test_a_child_that_exits_is_reported_as_exited(self):
        result = self.wait(scripted(False), FakeProcess(exits_after=1))
        self.assertEqual(result["state"], "exited")
        self.assertIs(result["confirmed"], False)

    def test_a_watcher_seen_running_wins_over_a_child_that_exited(self):
        # A second watcher may already hold the mutex, in which case ours exits and
        # the correct answer is still "a watcher is running".
        result = self.wait(scripted(True), FakeProcess(exits_after=0))
        self.assertEqual(result["state"], "running")

    def test_it_gives_up_rather_than_waiting_for_ever(self):
        started = time.monotonic()
        self.wait(scripted(False), FakeProcess(), timeout=0.05)
        self.assertLess(time.monotonic() - started, 5.0)

    def test_it_works_without_a_process_handle(self):
        # `plugin_setup` has a handle; a future caller might not.
        self.assertEqual(self.wait(scripted(True), None)["state"], "running")


class StartWatcherReportingTests(ControlTestCase):
    """What `start_watcher` tells its four front ends."""

    def setUp(self):
        super().setUp()
        (self.home / "watcher-launcher.py").write_text("# launcher" + chr(10), encoding="utf-8")
        patcher = patch.object(control, "WATCHER_START_TIMEOUT", 0.05)
        patcher.start()
        self.addCleanup(patcher.stop)
        interval = patch.object(control, "WATCHER_START_INTERVAL", 0)
        interval.start()
        self.addCleanup(interval.stop)

    def start(self, *answers, exits_after=None):
        with patch.object(control.Control, "watcher_running", side_effect=scripted(*answers)),              patch("subprocess.Popen", return_value=FakeProcess(exits_after=exits_after)):
            return self.control.start_watcher()

    def test_a_confirmed_start_says_so(self):
        result = self.start(False, True)
        self.assertEqual(result["state"], "running")
        self.assertIs(result["started"], True)
        self.assertIs(result["confirmed"], True)

    def test_an_unconfirmed_start_does_not_claim_running(self):
        result = self.start(False)
        self.assertEqual(result["state"], "unconfirmed")
        self.assertIs(result["confirmed"], False)

    def test_a_watcher_that_exits_is_not_a_started_watcher(self):
        result = self.start(False, exits_after=0)
        self.assertEqual(result["state"], "exited")
        self.assertIs(result["confirmed"], False)

    def test_an_already_running_watcher_is_confirmed_without_launching(self):
        with patch.object(control.Control, "watcher_running", return_value=True),              patch("subprocess.Popen") as popen:
            result = self.control.start_watcher()
        popen.assert_not_called()
        self.assertEqual(result["state"], "already-running")
        self.assertIs(result["confirmed"], True)

    def test_a_launch_that_cannot_happen_raises_rather_than_reporting_success(self):
        with patch.object(control.Control, "watcher_running", return_value=False),              patch("subprocess.Popen", side_effect=OSError("no")):
            with self.assertRaises(control.ControlError):
                self.control.start_watcher()

    def test_every_outcome_has_wording_that_does_not_overclaim(self):
        """The MCP tool must have a sentence for each state, and only one may say running."""
        from codex_auto_resume.mcpserver import Server
        wording = Server.START_WORDING
        for state in ("running", "already-running", "exited", "unconfirmed"):
            self.assertIn(state, wording, state)
        claims = [state for state, text in wording.items()
                  if "is running" in text and state not in ("running", "already-running")]
        self.assertEqual(claims, [], "a state that is not running must not say it is")
        for state in ("exited", "unconfirmed"):
            self.assertNotIn("is running", wording[state])


if __name__ == "__main__":
    unittest.main()
