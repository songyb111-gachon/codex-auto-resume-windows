"""Safety tests: never launch Codex, send queues, inspect auth or control the app."""
import ast
from contextlib import contextmanager, nullcontext
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from codex_auto_resume import windows as w
# A patch has to reach the module that looks the name up, and `windows` is the front
# since v0.6.10-alpha: setting a name on it reaches nothing, silently.
from codex_auto_resume.codex import pairing, transport

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)        # srcscan lives next to this file

import srcscan  # noqa: E402
import frozen_registry  # noqa: E402

THREAD = "0a1b2c3d-0001-7000-8000-000000000001"
QUEUE = "0a1b2c3d-0003-7000-8000-000000000003"
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

    def loaded(self, users=None, identities=None):
        if users is None:
            users = [{"pid": 20, "created": 200}]
        with patch.object(self.backend, "app_identity", side_effect=identities or [APP, APP]), \
             patch.object(transport, "resource_users", return_value=users):
            return self.backend.loaded(THREAD, APP)

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

    def test_no_holder_is_not_loaded(self):
        # A stale or absent lock file has no Restart Manager holder.
        self.assertEqual(self.loaded(users=[]), "notLoaded")

    def test_resource_api_unavailable_fails_closed(self):
        with patch.object(self.backend, "app_identity", return_value=APP), \
             patch.object(transport, "resource_users", side_effect=w.AdapterError("resource_inventory_failed")):
            self.assertEqual(self.backend.loaded(THREAD, APP), "unknown")

    def test_tool_never_acquires_the_apps_writer_lock(self):
        # Hard invariant: no byte-lock API may exist anywhere in the adapter, because
        # acquiring a momentarily free range would break the app's own try_lock. Anywhere in
        # the package, in fact, so the adapter being split cannot move one out of sight.
        for forbidden in ("LockFileEx", "UnlockFileEx", "writer_lock_state"):
            self.assertEqual(srcscan.holders(forbidden + "("), set(), forbidden)
        self.assertFalse(hasattr(w, "writer_lock_state"))
        defined = [srcscan.relative(path) for path, tree in srcscan.package_asts().items()
                   for node in ast.walk(tree)
                   if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "writer_lock_state"]
        self.assertEqual(defined, [])

    def test_app_path_uses_native_program_files_under_wow64(self):
        # 32-bit Python sees ProgramFiles=(x86); ProgramW6432 holds the native path.
        native = r"C:\Program Files"
        rows = [{"pid": 10, "parent": 1, "path": native + r"\WindowsApps\OpenAI.Codex_26.901.5280.0_x64__2p2nqsd0c76g0\app\ChatGPT.exe"},
                {"pid": 20, "parent": 10, "path": "codex.exe"}]
        with patch.dict(os.environ, {"ProgramFiles": r"C:\Program Files (x86)", "ProgramW6432": native}), \
             patch.object(pairing, "process_identity", side_effect=[{"pid": 10, "created": 100, "path": rows[0]["path"].lower()},
                                                              {"pid": 20, "created": 200, "path": "codex.exe"}]):
            pair = w.desktop_pair(rows, Path("codex.exe"))
        self.assertEqual(pair["pid"], 10)
        self.assertEqual(pair["server"]["pid"], 20)

    LOCAL_APPDATA = "C:\\FakeLocalAppData"

    def compat(self, version, queue_help_ok=True, queue_rc=0):
        """Drive Backend._compatible() with a fake `--version` / `queue --help`.

        Uses a path that really satisfies the location check, so that guard stays live.
        """
        exe = Path(self.LOCAL_APPDATA) / "OpenAI" / "Codex" / "bin" / "abcdef0123456789" / "codex.exe"
        with patch.dict(os.environ, {"LOCALAPPDATA": self.LOCAL_APPDATA}):
            backend = w.Backend(Path("state"), exe)
            results = {
                ("--version",): MagicMock(returncode=0, stdout=version + "\n"),
                ("queue", "--help"): MagicMock(
                    returncode=queue_rc,
                    stdout=("Usage: codex queue [OPTIONS] --thread <THREAD> --message <TEXT>"
                            if queue_help_ok else "Usage: codex queue [OPTIONS] --session <S>")),
            }

            def fake_run(argv, **kwargs):
                return results[tuple(argv[1:])]

            with patch.object(backend, "_environment", return_value={}), \
                 patch.object(Path, "stat", return_value=MagicMock(st_size=1, st_mtime_ns=1)), \
                 patch.object(subprocess, "run", side_effect=fake_run):
                backend._compatible()
        return backend

    def test_engine_outside_the_official_location_is_refused(self):
        backend = w.Backend(Path("state"), Path("C:\\elsewhere\\codex.exe"))
        with patch.dict(os.environ, {"LOCALAPPDATA": self.LOCAL_APPDATA}), \
             patch.object(subprocess, "run") as run:
            with self.assertRaises(w.AdapterError):
                backend._compatible()
            run.assert_not_called()

    def test_verified_engine_version_is_trusted(self):
        """A version the registry verifies is labelled so - once its checks have passed."""
        with patch.object(transport, "verified_versions", return_value=("codex-cli 0.153.4",)):
            backend = self.compat("codex-cli 0.153.4")
        self.assertEqual(backend.engine_version, "codex-cli 0.153.4")
        self.assertTrue(backend.engine_verified)

    def test_a_verified_version_still_has_to_offer_the_queue_flags(self):
        """The pin used to skip the interface probe. A failed local check always wins now:
        no registry entry, bundled or fetched, can vouch for a build whose `codex queue` no
        longer takes the flags this tool drives."""
        with patch.object(transport, "verified_versions", return_value=("codex-cli 0.153.4",)):
            for kwargs in ({"queue_help_ok": False}, {"queue_rc": 2}):
                with self.subTest(**kwargs), self.assertRaises(w.AdapterError) as caught:
                    self.compat("codex-cli 0.153.4", **kwargs)
                self.assertEqual(str(caught.exception), "unsupported_codex_version")

    def test_the_adapter_verifies_exactly_what_the_bundled_registry_verifies(self):
        """No version string is trusted by itself any more: the adapter's list is the bundled
        document's VERIFIED versions, read once. v0.6.6's bundled document verified none - the
        evidence rule wanted a recording that states its version - and data published since
        may verify some; either way the adapter says what the document says."""
        from codex_auto_resume import compat, compatio
        # The cache lives with the definition (codex/transport.py), so the reset has to
        # reach it there: `w` is the front, and setting a name on a front reaches nothing.
        from codex_auto_resume.codex import transport
        transport._VERIFIED = None
        self.addCleanup(setattr, transport, "_VERIFIED", None)
        live, _state = compatio.load_bundled()
        self.assertEqual(w.verified_versions(), compat.verified_versions(live))
        with frozen_registry.frozen():
            self.assertEqual(w.verified_versions(), ())
            self.assertFalse(self.compat("codex-cli 0.153.4").engine_verified)

    def test_engine_checks_say_which_check_failed_and_never_raise(self):
        exe = Path(self.LOCAL_APPDATA) / "OpenAI" / "Codex" / "bin" / "abcdef0123456789" / "codex.exe"
        with patch.dict(os.environ, {"LOCALAPPDATA": self.LOCAL_APPDATA}):
            outside = w.Backend(Path("state"), Path("C:\\elsewhere\\codex.exe")).engine_checks()
            self.assertEqual((outside["official_location"], outside["version_runs"], outside["queue_flags"]),
                             (w.FAIL, w.UNAVAILABLE, w.UNAVAILABLE))
            with patch.object(Path, "stat", side_effect=OSError("gone")):
                vanished = w.Backend(Path("state"), exe).engine_checks()
            self.assertEqual((vanished["official_location"], vanished["version_runs"]),
                             (w.PASS, w.UNAVAILABLE))
            with patch.object(Path, "stat", return_value=MagicMock(st_size=1, st_mtime_ns=1)), \
                 patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired("codex", 10)):
                slow = w.Backend(Path("state"), exe)
                checks = slow.engine_checks()
            self.assertEqual(checks["version_runs"], w.UNAVAILABLE)
            self.assertIsNone(slow.engine_version, "nothing unproven is accepted")
            with self.assertRaises(w.AdapterError) as caught:
                with patch.object(Path, "stat", return_value=MagicMock(st_size=1, st_mtime_ns=1)), \
                     patch.object(subprocess, "run", side_effect=OSError("no process")):
                    w.Backend(Path("state"), exe)._compatible()
            self.assertEqual(str(caught.exception), "codex_binary_unavailable")

    def test_an_accepted_binary_is_not_probed_again_until_it_changes(self):
        backend = self.compat("codex-cli 0.199.0")
        with patch.dict(os.environ, {"LOCALAPPDATA": self.LOCAL_APPDATA}), \
             patch.object(Path, "stat", return_value=MagicMock(st_size=1, st_mtime_ns=1)), \
             patch.object(subprocess, "run") as run:
            checks = backend.engine_checks()
            backend._compatible()
        run.assert_not_called()
        self.assertEqual(checks["version"], "codex-cli 0.199.0")
        self.assertEqual(checks["signature"], (1, 1))
        self.assertEqual(backend.last_checks()["queue_flags"], w.PASS)

    def test_the_protocol_allowlist_is_the_constant_the_registry_checks(self):
        self.assertEqual(w.PROTOCOL_METHODS,
                         ("initialize", "account/rateLimits/read", "thread/queue/delete"))
        with self.assertRaises(w.AdapterError):
            w.Protocol(self.backend).call("thread/start")

    def test_updated_engine_is_accepted_when_the_queue_interface_survives(self):
        # An app update must not silently disable auto-resume, but it is flagged.
        backend = self.compat("codex-cli 0.199.0")
        self.assertEqual(backend.engine_version, "codex-cli 0.199.0")
        self.assertFalse(backend.engine_verified)

    def test_updated_engine_is_refused_when_the_queue_interface_changed(self):
        for kwargs in ({"queue_help_ok": False}, {"queue_rc": 2}):
            with self.subTest(**kwargs), self.assertRaises(w.AdapterError):
                self.compat("codex-cli 0.199.0", **kwargs)

    def test_invalid_thread_id_never_launches(self):
        with patch.object(subprocess, "Popen") as popen:
            for invalid in ("--last", THREAD + " & echo PWNED", "../state", "", None):
                self.assertEqual(self.backend.send(invalid, "harmless")["outcome"], "not_started")
            popen.assert_not_called()

    def test_queue_argv_exact_id_shell_disabled_and_no_telemetry(self):
        process = MagicMock(returncode=0)
        process.communicate.return_value = (f"Queued message {QUEUE} for thread {THREAD}.\n", None)
        with patch.object(subprocess, "Popen", return_value=process) as popen:
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
        with patch.object(subprocess, "Popen", side_effect=OSError("secret diagnostic")):
            result = self.backend.send(THREAD, "harmless")
        self.assertEqual(result["outcome"], "not_started")
        self.assertNotIn("secret", repr(result))

    def test_final_consent_refusal_never_starts_queue_process(self):
        with patch.object(subprocess, "Popen") as popen:
            result = self.backend.send(THREAD, "harmless", launch_guard=nullcontext(False))
        popen.assert_not_called()
        self.assertEqual(result, {"outcome": "not_started", "error_code": "queue_consent_refused"})

    def test_launch_guard_is_released_before_waiting_for_receipt(self):
        held = []

        @contextmanager
        def guard():
            held.append(True)
            try:
                yield True
            finally:
                held.clear()

        process = MagicMock(returncode=0)

        def launch(*args, **kwargs):
            self.assertEqual(held, [True])
            return process

        def receipt(**kwargs):
            self.assertEqual(held, [])
            return (f"Queued message {QUEUE} for thread {THREAD}.\n", None)

        process.communicate.side_effect = receipt
        with patch.object(subprocess, "Popen", side_effect=launch):
            result = self.backend.send(THREAD, "harmless", launch_guard=guard())
        self.assertEqual(result["outcome"], "accepted")

    def test_guard_exit_failure_after_launch_is_never_not_started(self):
        @contextmanager
        def guard():
            yield True
            raise RuntimeError("transaction exit failed")

        process = MagicMock(returncode=1)
        process.communicate.return_value = ("", None)
        with patch.object(subprocess, "Popen", return_value=process) as popen:
            result = self.backend.send(THREAD, "harmless", launch_guard=guard())
        self.assertEqual(popen.call_count, 1)
        self.assertEqual(result["outcome"], "unknown")

    def test_nonzero_or_mismatched_acceptance_is_unknown_no_retry(self):
        for code, output in ((1, "secret diagnostic"), (0, f"Queued message {QUEUE} for thread {QUEUE}.")):
            process = MagicMock(returncode=code)
            process.communicate.return_value = (output, None)
            with patch.object(subprocess, "Popen", return_value=process):
                result = self.backend.send(THREAD, "harmless")
            self.assertEqual(result["outcome"], "unknown")
            self.assertNotIn("secret", repr(result))

    def test_timeout_after_start_is_unknown_even_if_kill_fails(self):
        process = MagicMock()
        process.communicate.side_effect = subprocess.TimeoutExpired("secret prompt", 45)
        process.kill.side_effect = OSError("already exited")
        with patch.object(subprocess, "Popen", return_value=process):
            result = self.backend.send(THREAD, "harmless")
        self.assertEqual(result, {"outcome": "unknown", "error_code": "queue_timeout"})

    def test_delete_rejects_invalid_identity_before_server_spawn(self):
        with patch.object(transport, "Protocol") as protocol:
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


NATIVE = r"C:\Program Files"
STORE_APP = NATIVE + r"\WindowsApps\OpenAI.Codex_26.930.2377.0_x64__2p2nqsd0c76g0\app\ChatGPT.exe"
ENGINE = r"C:\FakeLocalAppData\OpenAI\Codex\bin\abcdef0123456789\codex.exe"


class SeveralEngineChildrenTests(unittest.TestCase):
    """Codex 26.930's app starts `codex.exe exec-server` beside its app server, from the same
    binary under the same main (measured 2026-10-04), and pairing refused both for ever. The
    one holding Codex's state database open, by the Restart Manager, is the app's server;
    anything short of exactly one fails closed, and one child is paired as it always was."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        for name in ("state_4.sqlite", "state_5.sqlite", "state_5.sqlite-wal", "queue_1.sqlite"):
            (self.home / name).write_bytes(b"")
        self.identities = {10: {"pid": 10, "created": 100, "path": STORE_APP.lower()},
                           20: {"pid": 20, "created": 200, "path": ENGINE.lower()},
                           21: {"pid": 21, "created": 300, "path": ENGINE.lower()}}
        for stub in (patch.dict(os.environ, {"ProgramW6432": NATIVE}),
                     patch.object(pairing, "process_identity",
                                  side_effect=lambda pid: dict(self.identities[pid]))):
            stub.start()
            self.addCleanup(stub.stop)

    @staticmethod
    def rows(*extra, both=True):
        rows = [{"pid": 10, "parent": 1, "path": STORE_APP}, {"pid": 20, "parent": 10, "path": ENGINE}]
        if both:
            rows.append({"pid": 21, "parent": 10, "path": ENGINE})   # the exec-server
        return rows + list(extra)

    def pair(self, rows, holders, home="default"):
        """(the pair or the error's code, the Restart Manager stub)."""
        home = self.home if home == "default" else home
        stub = (dict(side_effect=holders) if isinstance(holders, BaseException)
                else dict(return_value=holders))
        with patch.object(pairing, "resource_users", **stub) as users:
            try:
                return w.desktop_pair(rows, Path(ENGINE), home), users
            except w.AdapterError as error:
                return str(error), users

    def test_the_one_holding_the_state_database_is_the_app_server(self):
        pair, users = self.pair(self.rows(), [{"pid": 77, "created": 1}, {"pid": 20, "created": 200}])
        self.assertEqual(pair, {**self.identities[10], "server": self.identities[20]})
        users.assert_called_once_with(self.home / "state_5.sqlite")

    def test_the_same_server_is_named_every_time_in_any_order(self):
        # What a claim compares with what is about to be sent: the same pid and creation time.
        holders = [{"pid": 20, "created": 200}]
        first, _ = self.pair(self.rows(), holders)
        again, _ = self.pair(list(reversed(self.rows())), holders)
        self.assertEqual(first, again)
        self.assertEqual(first["server"]["pid"], 20)

    def test_both_or_neither_holding_it_fails_closed(self):
        for holders in ([{"pid": 20, "created": 200}, {"pid": 21, "created": 300}], [],
                        [{"pid": 77, "created": 1}], [{"pid": 20, "created": 200}, {"pid": 20, "created": 200}]):
            with self.subTest(holders=holders):
                self.assertEqual(self.pair(self.rows(), holders)[0], "desktop_server_missing_or_ambiguous")

    def test_a_restart_manager_that_cannot_answer_fails_closed(self):
        for error in (w.AdapterError("resource_session_failed"), w.AdapterError("windows_required"),
                      w.AdapterError("resource_inventory_failed"), OSError("rstrtmgr")):
            with self.subTest(error=error):
                self.assertEqual(self.pair(self.rows(), error)[0], "desktop_server_missing_or_ambiguous")

    def test_no_state_database_fails_closed_without_asking(self):
        empty = self.home / "empty"
        empty.mkdir()
        (empty / "state_5.sqlite-wal").write_bytes(b"")
        (empty / "state_6.sqlite").mkdir()          # a folder is not the database
        for home in (empty, self.home / "missing", None):
            with self.subTest(home=home):
                result, users = self.pair(self.rows(), [{"pid": 20, "created": 200}], home=home)
                self.assertEqual(result, "desktop_server_missing_or_ambiguous")
                users.assert_not_called()

    def test_a_reused_pid_fails_closed(self):
        self.assertEqual(self.pair(self.rows(), [{"pid": 20, "created": 199}])[0], "process_identity_changed")

    def test_one_child_is_paired_as_before_without_the_restart_manager(self):
        for home in ("default", None):
            with self.subTest(home=home):
                pair, users = self.pair(self.rows(both=False), [], home=home)
                self.assertEqual(pair, {**self.identities[10], "server": self.identities[20]})
                users.assert_not_called()

    def test_a_same_path_process_under_another_parent_is_ignored(self):
        pair, users = self.pair(self.rows({"pid": 30, "parent": 99, "path": ENGINE}, both=False), [])
        self.assertEqual(pair["server"]["pid"], 20)
        users.assert_not_called()

    def test_a_child_of_another_app_process_is_ignored(self):
        others = ({"pid": 11, "parent": 10, "path": STORE_APP}, {"pid": 31, "parent": 11, "path": ENGINE},
                  {"pid": 40, "parent": 1, "path": r"C:\Elsewhere\ChatGPT.exe"},
                  {"pid": 41, "parent": 40, "path": ENGINE})
        pair, users = self.pair(self.rows(*others, both=False), [])
        self.assertEqual(pair["server"]["pid"], 20)
        users.assert_not_called()

    def test_the_backend_asks_of_its_own_codex_home_and_loaded_holds_it_to_that_server(self):
        backend = w.Backend(self.home, Path(ENGINE))
        rows = [dict(row, path=str(backend.codex_exe)) if row["path"] == ENGINE else row for row in self.rows()]
        with patch.object(backend, "_compatible"), \
             patch.object(transport, "inventory", return_value=rows), \
             patch.object(pairing, "resource_users", return_value=[{"pid": 20, "created": 200}]) as users, \
             patch.object(transport, "resource_users", return_value=[{"pid": 20, "created": 200}]):
            identity = backend.app_identity()
            self.assertEqual(identity["server"]["pid"], 20)
            self.assertEqual(backend.loaded(THREAD, identity), "loaded")
        self.assertEqual({call.args[0] for call in users.call_args_list}, {backend.codex_home / "state_5.sqlite"})


if __name__ == "__main__":
    unittest.main()
