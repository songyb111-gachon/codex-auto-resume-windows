"""A weekly update check while idle (v0.6.18): the Dashboard's Check for updates, run by the watcher at most once in
seven days and only while no recovery waits or runs; a notice of its own kind only where a newer version is offered,
exactly as a pressed check offers one; nothing downloaded; off, no request at all.

Held against the shipped definition and statement, the edition's own runtime and surface, core's notifier and the
watcher's handling of what the surface says. No check reaches the network or runs PowerShell: every one is a fake.

    PYTHONPATH=src python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from codex_auto_resume import l10n, notice_kinds, notifier, notify  # noqa: E402
from codex_auto_resume.domain.plug import DEFER, Point, Surface  # noqa: E402
from codex_auto_resume.runtime.app import App  # noqa: E402
from codex_auto_resume_advanced import plug as advanced, registry, statement, surfaces  # noqa: E402
from codex_auto_resume_advanced.engine import updatecheck  # noqa: E402
from codex_auto_resume_advanced.registry import IDLE_UPDATE_CHECK  # noqa: E402
from codex_auto_resume_advanced.vocabulary import Actor, CapabilityKind, OptionKey  # noqa: E402

CAP = "idle_update_check"
ENGINE = ac.ENGINE
AVAILABLE = (10, "  checking\nupdate: available 0.6.18 0.6.19\n")
CURRENT = (0, "update: current 0.6.18 0.6.18\n")
PRERELEASE = (0, "update: current 0.6.18 0.6.18\nprerelease: v0.6.19-beta.2\n")


class View:
    """What core shows a plug at P8, as far as this capability reads it: the records in some states."""

    def __init__(self, rows=()):
        self.rows, self.asked = rows if isinstance(rows, Exception) else list(rows), []

    def records_in(self, states):
        self.asked.append(frozenset(states))
        if isinstance(self.rows, Exception):
            raise self.rows
        return [row for row in self.rows if row["state"] in states]


class DefinitionTests(unittest.TestCase):
    def test_a_route_at_p8_departing_from_c4_c5_and_c7_shown_right_before_structured_rules(self):
        self.assertEqual((IDLE_UPDATE_CHECK.kind, IDLE_UPDATE_CHECK.points, IDLE_UPDATE_CHECK.compat),
                         (CapabilityKind.ROUTE, frozenset({Point.TICK}), "engine_present"))
        self.assertEqual(IDLE_UPDATE_CHECK.departs_from, ("C4", "C5", "C7"))
        self.assertEqual((IDLE_UPDATE_CHECK.measurements, IDLE_UPDATE_CHECK.options, IDLE_UPDATE_CHECK.requires),
                         ((), (), ()))
        self.assertIn(CAP, registry.REGISTRY.ids)
        order = registry.SHOWN_ORDER
        # v0.6.20: switching the Codex account comes between it and structured_rules (the order the owner approved).
        self.assertEqual(order[order.index("structured_rules") - 2:order.index("structured_rules")], (CAP, "account_switch"))
        self.assertEqual(statement.CATALOGS.missing(IDLE_UPDATE_CHECK), [])


class OfferTests(unittest.TestCase):
    """What a check offers is what the Dashboard would offer for the same output (DashboardMaintenance.RunBootstrap)."""

    def test_a_newer_release_and_a_newer_pre_release_are_offered(self):
        self.assertEqual(updatecheck.offer(*AVAILABLE), ("0.6.19", False))
        self.assertEqual(updatecheck.offer(*PRERELEASE), ("0.6.19-beta.2", True))
        self.assertEqual(updatecheck.offer(11, "update: newer-local 0.6.20 0.6.19\nprerelease: v0.6.21-alpha\n"),
                         ("0.6.21-alpha", True))

    def test_nothing_newer_no_answer_or_a_disagreement_offers_nothing(self):
        for code, printed in (CURRENT, (11, "update: newer-local 0.6.20 0.6.19\n"),
                              (12, "update: unavailable 0.6.18\n"), (0, "update: available 0.6.18 0.6.19\n"),
                              (10, "update: current 0.6.18 0.6.18\n"), (10, ""), (-1, "boom"),
                              (10, "update: available 0.6.18 0.6.19; Remove-Item x\n"),
                              (10, "update: available 0.6.18 v0.6.19\n"),
                              (0, "update: current 0.6.18 0.6.18\nprerelease: v0.6.19-gamma\n"),
                              (0, "update: current 0.6.18 0.6.18\nprerelease: 0.6.19-beta.2\n"),
                              (12, "update: unavailable 0.6.18\nprerelease: v0.6.19-beta.2\n")):
            with self.subTest(code=code, printed=printed):
                self.assertIsNone(updatecheck.offer(code, printed))

    def test_the_last_line_counts_as_the_window_reads_it(self):
        self.assertEqual(updatecheck.offer(10, "update: current 0.6.18 0.6.18\nupdate: available 0.6.18 0.6.20\n"),
                         ("0.6.20", False))


class RunTests(unittest.TestCase):
    """The check is the Dashboard's, switch for switch: never anything that downloads or installs."""

    class Process:
        def __init__(self, argv, **options):
            self.argv, self.options = argv, options
            self.returncode = 10
            self.killed = False
            RunTests.started.append(self)

        def communicate(self, timeout=None):
            if RunTests.slow and timeout is not None:
                raise subprocess.TimeoutExpired(self.argv, timeout)
            return b"update: available 0.6.18 0.6.19\n", b""

        def kill(self):
            self.killed = True

        terminate = kill

    def setUp(self):
        RunTests.started, RunTests.slow = [], False
        import tempfile
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.script = Path(folder.name) / "app" / "scripts" / "bootstrap.ps1"
        self.script.parent.mkdir(parents=True)
        self.script.write_text("# not run\n", encoding="utf-8")
        for patched in (patch.object(subprocess, "Popen", self.Process),
                        patch("codex_auto_resume.pwsh.executable", lambda: r"C:\Windows\System32\psh.exe"),
                        patch.dict("os.environ", {"CODEX_AUTO_RESUME_UPDATING_DASHBOARD": "1",
                                                  "CODEX_AUTO_RESUME_PROGRESS_LINES": "1"})):
            patched.start()
            self.addCleanup(patched.stop)

    def test_it_runs_the_installed_bootstrap_with_check_only_and_no_console(self):
        self.assertEqual(updatecheck.run_check(self.script, Path("C:/home")), (10, "update: available 0.6.18 0.6.19\n"))
        process, = self.started
        self.assertEqual(process.argv, [r"C:\Windows\System32\psh.exe", "-NoProfile", "-NonInteractive",
                                        "-ExecutionPolicy", "Bypass", "-File", str(self.script), "-CheckOnly"])
        for switch in ("-Update", "-Version", "-Pick", "-Versions", "-Compatibility", "-Force", "-AskFirst"):
            self.assertNotIn(switch, process.argv)
        self.assertEqual(process.options["creationflags"], getattr(subprocess, "CREATE_NO_WINDOW", 0))
        environment = process.options["env"]
        self.assertEqual(environment[updatecheck.HOME_VARIABLE], str(Path("C:/home")))
        for name in updatecheck.INSTALL_VARIABLES:
            self.assertNotIn(name, environment)

    def test_one_not_finished_in_the_window_s_time_is_left_to_finish_and_says_nothing(self):
        RunTests.slow = True
        self.assertIsNone(updatecheck.run_check(self.script, Path("C:/home"), seconds=1))
        self.assertFalse(self.started[0].killed)
        self.assertEqual(updatecheck.CHECK_SECONDS, 120, "the Dashboard's CheckMilliseconds")

    def test_no_script_or_no_powershell_runs_nothing(self):
        self.assertIsNone(updatecheck.run_check(self.script.with_name("missing.ps1"), Path("C:/home")))
        with patch("codex_auto_resume.pwsh.executable", lambda: None):
            self.assertIsNone(updatecheck.run_check(self.script, Path("C:/home")))
        self.assertEqual(self.started, [])


class CheckCase(ac.AdvancedCase):
    def setUp(self):
        super().setUp()
        self.compat = ac.view(capability="engine_present")
        self.rt = self.runtime(IDLE_UPDATE_CHECK)
        self.rt.arming.catalogs = statement.CATALOGS
        script = updatecheck.script_of(self.paths)
        script.parent.mkdir(parents=True)
        script.write_text("# not run\n", encoding="utf-8")
        self.checks, self.answer, self.managed, self.view = [], AVAILABLE, False, View()
        code = self.rt._code_of(IDLE_UPDATE_CHECK)
        code._run = lambda script, home: self.checks.append((script, home)) or self.answer
        code._managed = lambda: self.managed
        code._start = lambda target: target()
        self.installed = "0.6.18"
        code._installed = lambda: self.installed
        self.code = code

    def restart(self):
        """The watcher started again on the same home: a runtime of its own, the same state."""
        self.rt.state.close()
        self.rt = self.runtime(IDLE_UPDATE_CHECK)
        self.rt.arming.catalogs = statement.CATALOGS
        code = self.rt._code_of(IDLE_UPDATE_CHECK)
        code._run = lambda script, home: self.checks.append((script, home)) or self.answer
        code._managed = lambda: self.managed
        code._start = lambda target: target()
        code._installed = lambda: self.installed
        self.rt.states(fresh=True)
        self.code = code

    def on(self, state="armed"):
        definition = IDLE_UPDATE_CHECK
        result = self.rt.arming.arm(CAP, state=state, revision=definition.revision,
                                    generation=self.rt.state.meta()["generation"], acknowledged_version=ENGINE,
                                    warnings=[str(w) for w in self.rt.arming.warnings(definition)],
                                    actor=Actor.DASHBOARD)
        self.assertTrue(result["done"], result)
        self.rt.states(fresh=True)

    def look(self, after=updatecheck.LOOK_EVERY):
        """Time passes, then one tick, its errand run - what core does with the answer at P8."""
        self.now += after
        answer = self.rt.tick(self.view)
        if answer is not DEFER:
            answer.run(lambda: None)

    def notices(self):
        return surfaces.update_view(self.rt).get("update", {}).get("notices", [])


class OffTests(CheckCase):
    def test_off_no_check_is_ever_made(self):
        for _week in range(3):
            self.look(updatecheck.WEEK)
        self.assertEqual(self.checks, [])
        self.assertEqual(self.notices(), [])
        self.assertNotIn("update", surfaces.answer(self.rt, Surface.TRAY, {}))

    def test_watched_it_is_only_journalled_and_no_check_is_made(self):
        self.on(state="shadow")
        self.look(updatecheck.WEEK)
        self.assertEqual(self.checks, [])


class OnTests(CheckCase):
    def test_on_and_idle_the_installed_check_runs_once_and_its_offer_is_one_notice(self):
        self.on()
        self.look()
        self.assertEqual(self.checks, [(updatecheck.script_of(self.paths), self.paths.home)])
        self.assertEqual(self.notices(), [{"key": "update:0.6.19", "version": "0.6.19", "prerelease": False}])
        self.look()
        self.assertEqual(len(self.checks), 1)
        self.assertEqual(self.rt.state.stamped(CAP, OptionKey.LAST_CHECK), int(ac.NOW + updatecheck.LOOK_EVERY))

    def test_at_most_once_in_seven_days_whatever_the_check_answered(self):
        self.on()
        self.answer = None                       # failed, refused by GitHub, or still running at the time limit
        self.look()
        self.assertEqual(len(self.checks), 1)
        self.look(updatecheck.WEEK - updatecheck.LOOK_EVERY)
        self.assertEqual(len(self.checks), 1, "six days and more later: still waits")
        self.look(updatecheck.LOOK_EVERY)
        self.assertEqual(len(self.checks), 2, "a week on, the next one")
        self.assertEqual(self.notices(), [])

    def test_never_while_a_recovery_waits_or_runs(self):
        self.on()
        for state in ("waiting_reset", "waiting_retry", "submitting", "queued", "turn_started"):
            with self.subTest(state=state):
                self.view = View([{"state": state}])
                self.look(updatecheck.WEEK)
                self.assertEqual(self.checks, [])
        self.view = View(RuntimeError("unreadable"))
        self.look(updatecheck.WEEK)
        self.assertEqual(self.checks, [], "records that cannot be read are not idle")
        self.view = View([{"state": "recovered"}, {"state": "cancelled"}])
        self.look(updatecheck.WEEK)
        self.assertEqual(len(self.checks), 1, "only ended ones left: idle")

    def test_a_notice_only_where_a_newer_version_is_offered(self):
        self.on()
        self.answer = CURRENT
        self.look()
        self.assertEqual((len(self.checks), self.notices()), (1, []))
        self.answer = PRERELEASE
        self.look(updatecheck.WEEK)
        self.assertEqual(self.notices(), [{"key": "update:0.6.19-beta.2", "version": "0.6.19-beta.2",
                                           "prerelease": True}])

    def test_an_administrator_s_disable_update_check_means_no_check(self):
        self.on()
        self.managed = True
        self.look(updatecheck.WEEK)
        self.assertEqual(self.checks, [])

    def test_its_words_are_counted_and_turned_off_its_notice_is_gone(self):
        self.on()
        self.look()
        self.look()
        with self.rt.state._read() as connection:
            codes = [row[0] for row in connection.execute("SELECT code FROM journal")]
        self.assertIn("update.offered", codes)
        self.rt.arming.disarm(CAP, actor=Actor.DASHBOARD)
        self.rt.states(fresh=True)
        self.assertEqual(self.notices(), [])


class KeptOfferTests(CheckCase):
    """The offer is kept beside the last check's time, so a watcher that starts again shows it until that version is
    installed, a later check finds nothing newer, or the person turns the capability off."""

    def test_a_version_is_kept_as_one_whole_number_that_keeps_its_order(self):
        versions = ["0.6.18-alpha", "0.6.18-alpha.2", "0.6.18-beta", "0.6.18-beta.3", "0.6.18", "0.6.19-alpha",
                    "0.7.0", "1.0.0"]
        codes = [updatecheck.encode(version) for version in versions]
        self.assertEqual(codes, sorted(codes))
        self.assertEqual(len(set(codes)), len(codes))
        for version in versions:
            with self.subTest(version=version):
                self.assertEqual(updatecheck.decode(updatecheck.encode(version)),
                                 (version, "-" in version))
        for odd in ("0.6", "1000.0.0", "0.6.18-gamma", None):
            self.assertIsNone(updatecheck.encode(odd))
        for odd in (0, -1, 15000, 10_000_000_000_000_000, "1", 1.5):
            self.assertIsNone(updatecheck.decode(odd))

    def test_a_watcher_that_starts_again_still_shows_the_offer(self):
        self.on()
        self.look()
        self.look()
        self.restart()
        self.look()
        self.assertEqual(self.notices(), [{"key": "update:0.6.19", "version": "0.6.19", "prerelease": False}])
        self.assertEqual(len(self.checks), 1, "no new check for it")
        self.assertEqual(updatecheck.decode(self.rt.state.stamped(CAP, OptionKey.OFFERED_VERSION)), ("0.6.19", False))

    def test_installing_that_version_puts_it_away(self):
        self.on()
        self.look()
        self.look()
        self.installed = "0.6.19"
        self.restart()
        self.look()
        self.assertEqual(self.notices(), [])
        self.assertIsNone(self.rt.state.stamped(CAP, OptionKey.OFFERED_VERSION))
        self.assertIsNone(self.rt.state.stamped(CAP, OptionKey.OFFERED_AT))

    def test_a_pre_release_is_put_away_by_its_release_too(self):
        self.on()
        self.answer = PRERELEASE
        self.look()
        self.look()
        self.installed = "0.6.19-beta"
        self.look()
        self.assertEqual(len(self.notices()), 1, "an earlier beta does not reach beta.2")
        self.installed = "0.6.19"
        self.look()
        self.assertEqual(self.notices(), [])

    def test_turning_it_off_and_on_again_puts_the_offer_away(self):
        self.on()
        self.look()
        self.look()
        self.rt.arming.disarm(CAP, actor=Actor.DASHBOARD)
        self.now += 60
        self.on()
        self.restart()
        self.look()
        self.assertEqual(self.notices(), [])
        self.assertIsNone(self.rt.state.stamped(CAP, OptionKey.OFFERED_VERSION))

    def test_a_later_check_that_finds_nothing_newer_puts_it_away(self):
        self.on()
        self.look()
        self.look()
        self.answer = CURRENT
        self.look(updatecheck.WEEK)
        self.look()
        self.assertEqual(len(self.checks), 2)
        self.assertEqual(self.notices(), [])
        self.restart()
        self.look()
        self.assertEqual(self.notices(), [])


class NoticeTests(unittest.TestCase):
    def setUp(self):
        held = patch.dict(notice_kinds._registered, clear=True)
        held.start()
        self.addCleanup(held.stop)

    def test_its_notice_is_a_kind_of_its_own_listed_with_the_others(self):
        self.assertIsNone(notice_kinds.kind_of("update_offered"))
        import tempfile
        from codex_auto_resume import config
        with tempfile.TemporaryDirectory() as folder:
            advanced.create(config.Paths(Path(folder) / "home"))
        kind = notice_kinds.kind_of("update_offered")
        self.assertEqual((kind.id, kind.notices), ("update_offered", ("update_offered",)))
        for locale in l10n.LOCALES:
            with self.subTest(locale=locale):
                self.assertEqual(kind.label(locale), l10n.text("msg.toast_update_offered", locale))

    def test_its_one_button_opens_the_diagnostics_page_and_it_names_no_conversation(self):
        for version, prerelease in (("0.6.19", False), ("0.6.19-beta.2", True)):
            with self.subTest(version=version):
                notice = notifier.build("update_offered", {"version": version, "prerelease": prerelease})
                self.assertEqual((notice.kind, notice.key), ("update_offered", None))
                self.assertEqual([uri for _label, uri in notice.actions], [notify.open_uri("diagnostics")])
                self.assertIn(version, notice.toast_content()["body"])
                self.assertEqual(notifier.with_open_codex(notice, True), notice)
        for odd in ("", "0.6", "0.6.19; x", None, 7):
            with self.subTest(odd=odd):
                self.assertIsNone(notifier.build("update_offered", {"version": odd, "prerelease": False}))

    def test_the_watcher_shows_each_offer_once_in_its_life(self):
        class Watcher:
            def __init__(self):
                self.shown = []

            def _watcher_notice(self, event, detail):
                self.shown.append((event, detail))
        watcher = Watcher()
        added = {"update": {"notices": [{"key": "update:0.6.19", "version": "0.6.19", "prerelease": False}]}}
        for _tick in range(3):
            App._update_offered(watcher, added)
        self.assertEqual(watcher.shown, [("update_offered", {"version": "0.6.19", "prerelease": False})])
        for said in ({}, {"update": "x"}, DEFER, None):
            App._update_offered(watcher, said)
        self.assertEqual(len(watcher.shown), 1)


if __name__ == "__main__":
    unittest.main()
