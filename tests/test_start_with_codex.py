"""v0.6.9: the watcher starts when Codex starts this plugin's MCP server, if a person asked for that.

What is pinned here is what the switch may and may not do. It is off by default and offered only in
the Dashboard. It starts exactly what Start watcher starts, only while no watcher runs and no
installation holds its lock, and it never raises: a failure in it must never cost Codex the panel.
Every test runs against a scratch home with the launch itself patched out, so nothing here starts a
real watcher or touches the installer's real lock.
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from codex_auto_resume import config, control, l10n, mcpserver, settings, windows


class FakeProcess:
    pid = 4242


class StartForCodexTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.paths = config.Paths(Path(self.temporary.name))
        self.paths.ensure()
        self.control = control.Control(self.paths)
        (self.paths.home / "watcher-launcher.py").write_text("# launcher\n", encoding="utf-8")
        self.launches = []

        def launch(_self, extra_flags=0, *, launcher_only=False):
            self.assertTrue(launcher_only, "a start for Codex goes through the stable launcher only")
            self.launches.append(extra_flags)
            return FakeProcess()

        for target, value in ((control.Control, ("watcher_running", False)),
                              (windows, ("install_in_progress", False)),
                              (windows, ("process_context", {"in_job": False}))):
            patcher = patch.object(target, value[0], return_value=value[1])
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(control.Control, "_launch_watcher", launch)
        patcher.start()
        self.addCleanup(patcher.stop)

    def turn_on(self):
        self.control.update_settings({"start_with_codex": True})

    def logged(self):
        return self.paths.codex_start_log.read_text(encoding="utf-8").splitlines()

    def test_it_is_off_by_default_and_then_starts_nothing(self):
        self.assertIs(settings.FIELDS["start_with_codex"][0], False)
        self.assertTrue(self.control.start_for_codex().endswith("; off"))
        self.assertEqual(self.launches, [])

    def test_on_it_starts_the_watcher_once(self):
        self.turn_on()
        self.assertIn("started pid 4242", self.control.start_for_codex())
        self.assertEqual(self.launches, [0])

    def test_it_never_starts_a_second_watcher(self):
        self.turn_on()
        with patch.object(control.Control, "watcher_running", return_value=True):
            self.assertTrue(self.control.start_for_codex().endswith("already running"))
        self.assertEqual(self.launches, [])

    def test_a_probe_that_cannot_say_starts_nothing(self):
        # Start watcher, pressed by a person, starts on an unknown probe; an automatic start
        # does not guess.
        self.turn_on()
        with patch.object(control.Control, "watcher_running", return_value=None):
            self.assertIn("not started", self.control.start_for_codex())
        self.assertEqual(self.launches, [])

    def test_it_waits_for_an_installation_to_finish(self):
        self.turn_on()
        for busy in (True, None):
            with self.subTest(busy=busy), patch.object(windows, "install_in_progress", return_value=busy):
                self.assertIn("not started", self.control.start_for_codex())
        self.assertEqual(self.launches, [])

    def test_a_job_that_would_end_the_watcher_starts_nothing(self):
        """What Codex 26.915 does, measured: KILL_ON_JOB_CLOSE and no breakaway. Starting a watcher
        there means starting one that is killed when Codex cancels the server a few seconds later, and
        a watcher killed mid-tick cannot say whether it sent anything. So nothing is started."""
        self.turn_on()
        context = {"in_job": True, "kill_on_close": True, "breakaway_ok": False, "silent_breakaway_ok": False}
        with patch.object(windows, "process_context", return_value=context):
            line = self.control.start_for_codex()
        self.assertIn("in a job (kill on close)", line)
        self.assertTrue(line.endswith("not started: this Codex ends what its plugins start"))
        self.assertEqual(self.launches, [])

    def test_it_leaves_a_job_that_lets_it(self):
        self.turn_on()
        cases = (({"in_job": True, "kill_on_close": True, "breakaway_ok": True, "silent_breakaway_ok": False},
                  windows.CREATE_BREAKAWAY_FROM_JOB),
                 # A job whose children leave anyway needs no request, and one that keeps them but does
                 # not end them is a job a watcher can live in.
                 ({"in_job": True, "kill_on_close": True, "breakaway_ok": True, "silent_breakaway_ok": True}, 0),
                 ({"in_job": True, "kill_on_close": False, "breakaway_ok": False, "silent_breakaway_ok": False}, 0),
                 ({"in_job": False}, 0))
        for context, flags in cases:
            with self.subTest(context=context):
                self.launches.clear()
                with patch.object(windows, "process_context", return_value=context):
                    self.control.start_for_codex()
                self.assertEqual(self.launches, [flags])

    def test_without_the_stable_launcher_it_starts_nothing(self):
        # Uninstalling from Codex removes the launcher and keeps the program files: nothing may
        # bring back a watcher through them.
        self.turn_on()
        (self.paths.home / "watcher-launcher.py").unlink()
        self.assertTrue(self.control.start_for_codex().endswith("not started: not installed"))
        self.assertEqual(self.launches, [])

    def test_the_real_launch_refuses_to_fall_back_to_the_entry_script(self):
        (self.paths.home / "watcher-launcher.py").unlink()
        patch.stopall()
        with patch("subprocess.Popen") as popen:
            with self.assertRaises(control.ControlError):
                control.Control._launch_watcher(self.control, launcher_only=True)
        popen.assert_not_called()

    def test_a_refused_breakaway_is_retried_inside_the_job(self):
        self.turn_on()
        attempts = []

        def launch(_self, extra_flags=0, *, launcher_only=False):
            attempts.append(extra_flags)
            if extra_flags:
                raise PermissionError(5, "Access is denied")
            return FakeProcess()

        context = {"in_job": True, "kill_on_close": True, "breakaway_ok": True, "silent_breakaway_ok": False}
        with patch.object(windows, "process_context", return_value=context), \
                patch.object(control.Control, "_launch_watcher", launch):
            line = self.control.start_for_codex()
        self.assertEqual(attempts, [windows.CREATE_BREAKAWAY_FROM_JOB, 0])
        self.assertIn("inside the job", line)

    def test_it_never_raises(self):
        self.turn_on()
        with patch.object(control.Control, "_launch_watcher", side_effect=OSError("no")):
            self.assertTrue(self.control.start_for_codex().endswith("failed: OSError"))
        with patch.object(windows, "process_context", side_effect=RuntimeError("no")):
            self.assertIn("failed: RuntimeError", self.control.start_for_codex())

    def test_each_start_leaves_one_content_free_line_and_the_log_stays_short(self):
        for _ in range(control.CODEX_START_LOG_LINES + 7):
            self.control.start_for_codex()
        lines = self.logged()
        self.assertEqual(len(lines), control.CODEX_START_LOG_LINES)
        self.assertRegex(lines[-1], r"^\[\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\] pid \d+; not in a job; off$")
        self.assertNotIn(str(self.paths.home), "\n".join(lines))

    def test_a_missing_logs_directory_is_not_created_for_it(self):
        self.paths.codex_start_log.parent.joinpath(config.OWNER_MARKER).unlink(missing_ok=True)
        for child in self.paths.logs_dir.iterdir():
            child.unlink()
        self.paths.logs_dir.rmdir()
        self.control.start_for_codex()
        self.assertFalse(self.paths.logs_dir.exists())


class StartWatcherFromCodexTests(unittest.TestCase):
    """v0.6.10: Start watcher, asked of the MCP server, says how long the watcher it starts lasts.

    The server runs in the job Codex puts it in, and Start watcher asks nothing of that job. Codex
    26.915 (measured, v0.6.9-alpha) gives it KILL_ON_JOB_CLOSE and no breakaway, so a watcher started
    from the panel or the tool stops when Codex ends that server; the reply may not report that as a
    lasting start. It reads the job as the start with Codex does (control.ends_with_job)."""

    KILL = {"in_job": True, "kill_on_close": True, "breakaway_ok": False, "silent_breakaway_ok": False}
    STARTS = {"running": {"started": True, "confirmed": True, "state": "running", "reason": None},
              "unconfirmed": {"started": True, "confirmed": False, "state": "unconfirmed",
                              "reason": "unconfirmed"},
              "exited": {"started": True, "confirmed": False, "state": "exited", "reason": "exited"},
              "already-running": {"started": False, "confirmed": True, "state": "already-running",
                                  "reason": "already running"}}

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.control = control.Control(config.Paths(Path(self.temporary.name)))
        self.server = mcpserver.Server(self.control, io.StringIO(), io.StringIO())

    def call(self, context, state="running"):
        """(the reply's text, its structured half, how often the job was asked about), with the start
        itself patched out: what is pinned here is the reply, not the launch."""
        asked = []

        def context_of_this_process():
            asked.append(1)
            if isinstance(context, BaseException):
                raise context
            return dict(context)

        with patch.object(control.Control, "start_watcher", return_value=dict(self.STARTS[state])),                 patch.object(windows, "process_context", side_effect=context_of_this_process):
            reply = self.server._tool_start_watcher({})
        return reply["content"][0]["text"], reply["structuredContent"], len(asked)

    def test_a_start_inside_a_job_that_ends_it_is_not_a_lasting_start(self):
        text, data, _asked = self.call(self.KILL)
        self.assertTrue(text.startswith(mcpserver.Server.START_WORDING["running"] + " "), text)
        self.assertIn("it stops when Codex closes, if not sooner", text)
        # The way out has to be one a person can take. "Start it from the Dashboard" was not: the
        # Dashboard starts a watcher in its own job, and one opened from this watcher's icon is in
        # Codex's; while this watcher runs it has nothing to start. The Start menu's entry, once Codex
        # has closed, and the sign-in start are launched by Windows.
        self.assertIn("Once Codex has closed, open Codex Auto Resume from the Start menu and start it "
                      "there", text)
        self.assertIn("Run at Windows sign-in", text)
        self.assertNotIn("start it from the Dashboard", text)
        self.assertEqual((data["state"], data["ends_with_codex"]), ("running", True))

    def test_the_job_is_read_as_the_start_with_codex_reads_it(self):
        """Start watcher asks nothing of the job, so a job that ends what it holds ends it even where
        the job would have let it leave on request; only a job whose children leave anyway, one
        that ends nobody, or no job at all lets it outlive Codex."""
        cases = ((self.KILL, True),
                 (dict(self.KILL, breakaway_ok=True), True),
                 (dict(self.KILL, silent_breakaway_ok=True), False),
                 (dict(self.KILL, kill_on_close=False), False),
                 ({"in_job": False}, False),
                 (dict(self.KILL, kill_on_close=None), None),
                 ({"in_job": None}, None),
                 ({}, None))
        for context, ends in cases:
            with self.subTest(context=context):
                self.assertIs(control.ends_with_job(context), ends)
                self.assertIs(self.call(context)[1]["ends_with_codex"], ends)
        # The refusal of the start with Codex is the same reading, asked for a start that does ask
        # to leave where the job lets it.
        self.assertIs(control.ends_with_job(dict(self.KILL, breakaway_ok=True), leaving=True), False)

    def test_a_start_that_outlives_codex_is_reported_as_it_always_was(self):
        text, data, _asked = self.call({"in_job": False})
        self.assertEqual(text, mcpserver.Server.START_WORDING["running"])
        self.assertIs(data["ends_with_codex"], False)

    def test_where_windows_would_not_say_it_may_stop(self):
        for context in ({"in_job": None}, RuntimeError("no")):
            with self.subTest(context=repr(context)):
                text, data, _asked = self.call(context)
                self.assertIn("it may stop when Codex closes", text)
                self.assertNotIn("it stops when Codex closes", text)
                self.assertIsNone(data["ends_with_codex"])

    def test_an_unconfirmed_start_says_it_too_and_still_does_not_say_running(self):
        text, data, _asked = self.call(self.KILL, "unconfirmed")
        self.assertEqual(text, mcpserver.Server.START_WORDING["unconfirmed"] + " "
                         + mcpserver.Server.ENDS_WITH_CODEX[True])
        self.assertNotIn("is running", text)
        self.assertIs(data["ends_with_codex"], True)

    def test_nothing_is_said_of_a_watcher_this_start_did_not_leave_running(self):
        # Already running: started elsewhere, and the job is not even asked about.
        text, data, asked = self.call(self.KILL, "already-running")
        self.assertEqual(text, mcpserver.Server.START_WORDING["already-running"])
        self.assertNotIn("ends_with_codex", data)
        self.assertEqual(asked, 0)
        # Exited: nothing is running to stop with Codex; the fact is still carried.
        text, data, _asked = self.call(self.KILL, "exited")
        self.assertEqual(text, mcpserver.Server.START_WORDING["exited"])
        self.assertIs(data["ends_with_codex"], True)

    def test_the_sentences_never_claim_a_running_watcher_and_the_panel_says_them_in_every_language(self):
        english = l10n._read("en")
        sentences = {("server", ends): sentence for ends, sentence in mcpserver.Server.ENDS_WITH_CODEX.items()}
        sentences.update({("panel", key): english[key]
                          for key in ("panel.start_ends_with_codex", "panel.start_may_end_with_codex")})
        for where, sentence in sentences.items():
            with self.subTest(where=where):
                self.assertNotIn("is running", sentence)
                # Nor a start that would not last: every one names the Start menu's entry.
                self.assertIn("Codex Auto Resume from the Start menu", sentence)
                self.assertNotIn("keep it running", sentence)
        script = (Path(__file__).resolve().parents[1] / "src" / "codex_auto_resume" / "mcp" / "assets"
                  / "panel.js").read_text(encoding="utf-8")
        self.assertIn("payload.ends_with_codex", script)
        for key in ("panel.start_ends_with_codex", "panel.start_may_end_with_codex"):
            self.assertIn("'%s'" % key, script)
            for locale in l10n.LOCALES:
                with self.subTest(key=key, locale=locale):
                    self.assertTrue(l10n._read(locale).get(key, "").strip())
                    # The entry keeps its name in every language: it is what the Start menu shows.
                    self.assertIn("Codex Auto Resume", l10n._read(locale)[key])

    def test_the_panel_says_it_after_a_start_running_or_not_yet_confirmed(self):
        """The panel's Start watcher says what the server's reply says, driven through the panel's
        own code: after a start that is running or not yet confirmed, where the job ends it or
        Windows would not say - an unconfirmed start used to say nothing of it - and after nothing
        else."""
        import shutil
        if not shutil.which("node"):
            self.skipTest("needs Node to run the panel's own code")
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from test_mcpui_v064 import run_page, say, snapshot

        def notice(state, ends, locale="en"):
            reply = {"state": state, "started": state != "already-running"}
            if ends != "absent":
                reply["ends_with_codex"] = ends
            # The panel speaks the chosen language, which the snapshot's settings carry.
            data = snapshot(interface_language=locale)
            data["status"]["watcher_running"] = False
            return run_page("""
              window.openai.callTool = HOST.callTool = function (name) {
                if (name === 'start_watcher') return Promise.resolve({structuredContent: %s});
                return new Promise(function () {});
              };
              HERO.start.onclick();
              await settle();
              """ % json.dumps(reply) + say("HERO.message.textContent"), data=data, locale=locale)

        ends, may = "panel.start_ends_with_codex", "panel.start_may_end_with_codex"
        unconfirmed, exited = "panel.start_unconfirmed", "panel.start_exited"
        for locale in ("en", "ko"):
            words = l10n.catalog(locale)
            cases = ((("running", True), words[ends]),
                     (("running", None), words[may]),
                     (("running", False), ""),
                     (("unconfirmed", True), words[unconfirmed] + " " + words[ends]),
                     (("unconfirmed", None), words[unconfirmed] + " " + words[may]),
                     (("unconfirmed", False), words[unconfirmed]),
                     (("exited", True), words[exited]),
                     (("already-running", "absent"), ""))
            for (state, told), expected in cases:
                with self.subTest(locale=locale, state=state, ends=told):
                    self.assertEqual(notice(state, told, locale), expected)


class ContextWordsTests(unittest.TestCase):
    def test_the_words_say_only_fixed_things(self):
        words = control._context_words
        self.assertEqual(words({}), "job unknown")
        self.assertEqual(words({"in_job": False, "packaged": False}), "not in a job")
        self.assertEqual(words({"in_job": True, "kill_on_close": True, "breakaway_ok": True,
                                "silent_breakaway_ok": False, "packaged": True}),
                         "in a job (kill on close, may leave), packaged")
        self.assertEqual(words({"in_job": True, "kill_on_close": None}), "in a job (limits unknown)")
        self.assertEqual(words({"in_job": True, "kill_on_close": False, "breakaway_ok": False,
                                "silent_breakaway_ok": False}), "in a job (no limits read)")


class ProcessContextTests(unittest.TestCase):
    def test_it_answers_with_booleans_or_nothing(self):
        facts = windows.process_context()
        self.assertEqual(set(facts), {"in_job", "kill_on_close", "breakaway_ok",
                                      "silent_breakaway_ok", "packaged"})
        for value in facts.values():
            self.assertIn(value, (True, False, None))
        if os.name == "nt":
            self.assertIsNotNone(facts["in_job"])

    def test_the_installer_lock_is_the_installers(self):
        root = Path(__file__).resolve().parents[1]
        for script in ("build/install/install.ps1", "scripts/bootstrap.ps1"):
            self.assertIn("'%s'" % windows.INSTALL_LOCK, (root / script).read_text(encoding="utf-8"), script)

    @unittest.skipUnless(os.name == "nt", "a Windows named mutex")
    def test_the_installer_lock_is_only_ever_opened(self):
        # A name of the test's own: the real installer lock is never touched. Opened and never
        # created, a name nobody holds stays a name nobody holds.
        name = "Local\\CodexAutoResume.Install.test-%d" % os.getpid()
        # Where install_in_progress reads it: win/homelock.py. On the windows front the name
        # would be replaced and the real installer lock looked at instead.
        with patch("codex_auto_resume.win.homelock.INSTALL_LOCK", name):
            self.assertIs(windows.install_in_progress(), False)
            self.assertIs(windows.install_in_progress(), False, "the first look created it")
            held, release = threading.Event(), threading.Event()

            def hold():
                import ctypes
                kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel.CreateMutexW.restype = ctypes.c_void_p
                handle = kernel.CreateMutexW(None, True, name)
                held.set()
                release.wait(10)
                kernel.ReleaseMutex(ctypes.c_void_p(handle))
                kernel.CloseHandle(ctypes.c_void_p(handle))

            holder = threading.Thread(target=hold)
            holder.start()
            try:
                held.wait(10)
                self.assertIs(windows.install_in_progress(), True)
            finally:
                release.set()
                holder.join(10)


class SurfaceTests(unittest.TestCase):
    def test_no_surface_offers_it(self):
        """Measured on Codex 26.915 (v0.6.9-alpha): a watcher started from the MCP server is killed with
        that server, seconds later, because Codex runs it in a job with KILL_ON_JOB_CLOSE and no
        breakaway. A switch that never leaves a watcher running is not shown, so `describe()` - which
        the Dashboard, the panel and the MCP schema are all drawn from - does not carry it."""
        self.assertIn("start_with_codex", settings.NOT_YET_OFFERED)
        self.assertEqual([entry for entry in settings.describe() if entry["name"] == "start_with_codex"], [])
        self.assertNotIn("start_with_codex", mcpserver.settings_schema()["properties"])
        self.assertIs(settings.DEFAULTS["start_with_codex"], False)

    def test_the_mcp_server_starts_it_only_for_an_installation(self):
        calls = []
        with patch.object(control.Control, "start_for_codex", lambda self: calls.append(self.paths.home)), \
                patch.object(mcpserver.Server, "serve", return_value=0), \
                tempfile.TemporaryDirectory() as home:
            self.assertEqual(mcpserver.main(["--home", home]), 0)
            self.assertEqual(calls, [Path(home).resolve()])
            calls.clear()
            # A source checkout: PROJECT_ROOT is not an installation's app folder.
            with patch.object(config, "PROJECT_ROOT", Path(home) / "checkout"):
                self.assertEqual(mcpserver.main([]), 0)
            self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
