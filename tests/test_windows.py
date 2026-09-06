"""Safety tests: never launch Codex, send queues, inspect auth or control the app."""
from pathlib import Path
import subprocess
import unittest
from unittest.mock import MagicMock, patch

from codex_auto_resume import windows as w

THREAD = "0a1b2c3d-0101-7000-8000-000000000101"
QUEUE = "0a1b2c3d-0103-7000-8000-000000000103"
APP = {"pid": 10, "created": 100, "path": "app", "server": {"pid": 20, "created": 200, "path": "codex"}}


class UsageTests(unittest.TestCase):
    def snapshot(self, primary=20, secondary=40, first_reset=1788645827, second_reset=1789108889):
        return {"rateLimitsByLimitId": {"codex": {
            "primary": {"usedPercent": primary, "windowDurationMins": 300, "resetsAt": first_reset},
            "secondary": {"usedPercent": secondary, "windowDurationMins": 10080, "resetsAt": second_reset}}}}

    def test_available_windows(self):
        result = w.parse_usage(self.snapshot())
        self.assertIs(result["available"], True)

    def test_exhausted_five_hour_uses_exact_seconds(self):
        result = w.parse_usage(self.snapshot(primary=100))
        self.assertIs(result["available"], False)
        self.assertEqual(result["reset_at"], 1788645827)

    def test_exhausted_weekly_waits_for_weekly(self):
        self.assertEqual(w.parse_usage(self.snapshot(secondary=100))["reset_at"], 1789108889)

    def test_both_blocked_wait_for_later_actual_reset(self):
        self.assertEqual(w.parse_usage(self.snapshot(primary=100, secondary=100))["reset_at"], 1789108889)

    def test_no_timestamp_does_not_guess(self):
        result = w.parse_usage(self.snapshot(primary=100, first_reset=None))
        self.assertIs(result["available"], False)
        self.assertIsNone(result["reset_at"])

    def test_explicit_quota_and_spend_flags_block(self):
        for flag in ("rate_limit_reached", "workspace_owner_credits_depleted"):
            value = self.snapshot()
            value["rateLimitsByLimitId"]["codex"]["rateLimitReachedType"] = flag
            self.assertIs(w.parse_usage(value)["available"], False)

    def test_missing_or_malformed_safe_unknown(self):
        for value in (None, [], {}, {"rateLimits": {}}, self.snapshot(primary=True),
                      self.snapshot(primary=float("nan")), self.snapshot(first_reset="1788645827"),
                      self.snapshot(first_reset=1788645827000)):
            with self.subTest(value=value):
                self.assertIsNone(w.parse_usage(value)["available"])

    def test_private_response_fields_are_discarded(self):
        value = self.snapshot()
        value.update(accountId="secret-account", rateLimitUpsell={"token": "secret-token"})
        result = repr(w.parse_usage(value))
        self.assertNotIn("secret", result)
        self.assertNotIn("accountId", result)

    def test_unknown_bucket_ids_do_not_become_log_text(self):
        value = self.snapshot()
        value["rateLimitsByLimitId"]["arbitrary\nlog-text"] = value["rateLimitsByLimitId"].pop("codex")
        result = repr(w.parse_usage(value))
        self.assertNotIn("arbitrary", result)
        self.assertIn("other", result)


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.backend = w.Backend(Path("state"), Path("codex.exe"))
        self.compatible = patch.object(self.backend, "_compatible")
        self.compatible.start()
        self.addCleanup(self.compatible.stop)

    def loaded(self, lock="held", users=None, identities=None):
        if users is None:
            users = [{"pid": 20, "created": 200}]
        lock_probe = MagicMock(return_value=lock)
        with patch.object(self.backend, "app_identity", side_effect=identities or [APP, APP]), \
             patch.object(w, "writer_lock_state", lock_probe), \
             patch.object(w, "resource_users", return_value=users):
            result = self.backend.loaded(THREAD, APP)
        self.last_lock_probe = lock_probe
        return result

    def test_loaded_requires_exact_app_owned_writer(self):
        self.assertEqual(self.loaded(), "loaded")

    def test_other_cli_owner_does_not_count_as_app_loaded(self):
        self.assertEqual(self.loaded(users=[{"pid": 99, "created": 200}]), "unknown")

    def test_pid_reuse_fails_closed(self):
        self.assertEqual(self.loaded(users=[{"pid": 20, "created": 201}]), "unknown")

    def test_app_restart_during_probe_fails_closed(self):
        self.assertEqual(self.loaded(identities=[APP, {**APP, "created": 101}]), "unknown")

    def test_ambiguous_resource_users_fail_closed(self):
        self.assertEqual(self.loaded(users=[{"pid": 20, "created": 200}, {"pid": 30, "created": 300}]), "unknown")

    def test_no_holder_is_not_loaded_without_ever_locking(self):
        # A stale or absent lock file has no Restart Manager holder; we must never
        # acquire a byte lock on the app's own file to decide this.
        self.assertEqual(self.loaded(users=[]), "notLoaded")
        self.last_lock_probe.assert_not_called()

    def test_free_or_absent_lock_after_holder_is_unknown(self):
        # Server holds the file open per RM, but the lock reads free/absent: a race -> unknown.
        self.assertEqual(self.loaded(lock="free"), "unknown")
        self.assertEqual(self.loaded(lock="absent"), "unknown")

    def test_resource_api_unavailable_does_not_use_lock_only(self):
        with patch.object(self.backend, "app_identity", return_value=APP), \
             patch.object(w, "writer_lock_state") as lock_probe, \
             patch.object(w, "resource_users", side_effect=w.AdapterError("resource_inventory_failed")):
            self.assertEqual(self.backend.loaded(THREAD, APP), "unknown")
            lock_probe.assert_not_called()

    def test_invalid_thread_id_never_launches(self):
        with patch.object(w.S, "Popen") as popen:
            for invalid in ("--last", THREAD + " & echo PWNED", "../state", "", None):
                self.assertEqual(self.backend.send(invalid, "harmless")["outcome"], "not_started")
            popen.assert_not_called()

    def test_queue_argv_exact_id_shell_disabled_and_no_telemetry(self):
        process = MagicMock(returncode=0)
        process.communicate.return_value = (f"Queued message {QUEUE} for thread {THREAD}.\n", None)
        with patch.object(w.S, "Popen", return_value=process) as popen:
            prompt = 'Harmless "quoted" ; $(no shell) & text'
            result = self.backend.send(THREAD, prompt)
        self.assertEqual(result, {"outcome": "accepted", "queue_id": QUEUE})
        argv = popen.call_args.args[0]
        self.assertEqual(argv[-5:], ["queue", "--thread", THREAD, "--message", prompt])
        self.assertIs(popen.call_args.kwargs["shell"], False)
        self.assertEqual(popen.call_args.kwargs["stderr"], subprocess.DEVNULL)
        self.assertNotIn("--last", argv)
        self.assertIn("analytics.enabled=false", argv)
        self.assertIn('otel.metrics_exporter="none"', argv)

    def test_spawn_failure_is_only_retryable_send_failure(self):
        with patch.object(w.S, "Popen", side_effect=OSError("secret diagnostic")):
            result = self.backend.send(THREAD, "harmless")
        self.assertEqual(result["outcome"], "not_started")
        self.assertNotIn("secret", repr(result))

    def test_nonzero_or_mismatched_acceptance_is_unknown_no_retry(self):
        for code, output in ((1, "secret diagnostic"), (0, f"Queued message {QUEUE} for thread {QUEUE}.")):
            process = MagicMock(returncode=code)
            process.communicate.return_value = (output, None)
            with patch.object(w.S, "Popen", return_value=process):
                result = self.backend.send(THREAD, "harmless")
            self.assertEqual(result["outcome"], "unknown")
            self.assertNotIn("secret", repr(result))

    def test_timeout_after_start_is_unknown_even_if_kill_fails(self):
        process = MagicMock()
        process.communicate.side_effect = subprocess.TimeoutExpired("secret prompt", 45)
        process.kill.side_effect = OSError("already exited")
        with patch.object(w.S, "Popen", return_value=process):
            result = self.backend.send(THREAD, "harmless")
        self.assertEqual(result, {"outcome": "unknown", "error_code": "queue_timeout"})

    def test_delete_rejects_invalid_identity_before_server_spawn(self):
        with patch.object(w, "Protocol") as protocol:
            self.assertFalse(self.backend.delete_queue(THREAD, "--last"))
            protocol.assert_not_called()

    def test_protocol_cannot_start_or_resume_threads(self):
        protocol = w.Protocol(self.backend)
        with self.assertRaises(w.AdapterError):
            protocol.call("thread/resume", {"threadId": THREAD})
        with self.assertRaises(w.AdapterError):
            protocol.call("turn/start", {"threadId": THREAD})
        with self.assertRaises(w.AdapterError):
            protocol.call("account/login/start", {})


if __name__ == "__main__":
    unittest.main()
