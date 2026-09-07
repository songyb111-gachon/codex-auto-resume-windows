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
from codex_auto_resume.store import Store

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
            store.update(KEY, state="cancelled")
        self.assertEqual(self.control.list_pending(), [])
        self.assertEqual(len(self.control.list_pending(include_terminal=True)), 1)

    def test_listing_never_needs_codex(self):
        self.register()
        listed = self.control.list_pending()
        self.assertIsNone(listed[0]["name"])
        self.assertEqual(listed[0]["interruption_id"], KEY)

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
    def exhaust(self, state="retry_budget_exhausted"):
        self.register()
        with Store(self.paths.state_dir) as store:
            store.update(KEY, state=state, recovery_attempts=4, no_progress_count=3)
            store.set_thread_enabled(THREAD, False)

    def test_reset_returns_a_record_to_the_normal_waiting_state(self):
        self.exhaust()
        self.control.reset_recovery_budget(KEY)
        with Store(self.paths.state_dir) as store:
            record = store.get(KEY)
        self.assertEqual(record["state"], "waiting_backoff")
        self.assertEqual(record["recovery_attempts"], 0)
        self.assertEqual(record["no_progress_count"], 0)

    def test_reset_re_enables_the_thread(self):
        self.exhaust()
        self.control.reset_recovery_budget(KEY)
        with Store(self.paths.state_dir) as store:
            self.assertTrue(store.thread_enabled(THREAD))

    def test_reset_also_covers_the_no_progress_budget(self):
        self.exhaust(state="no_progress_exhausted")
        self.control.reset_recovery_budget(KEY)
        with Store(self.paths.state_dir) as store:
            self.assertEqual(store.get(KEY)["state"], "waiting_backoff")

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
            store.update(KEY, state="resumed")
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
            "reset-budget", "retry-now", "settings", "startup", "status", "update"]))


if __name__ == "__main__":
    unittest.main()
