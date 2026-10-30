"""Start the 5-hour window early (window_anchor, v0.6.20): one near-free request from the watcher when the 5-hour window
is idle, at the times a person picks or right after a reset it saw - held against MANCHOR's measured rule (an idle
window reports a reset of now + 5 h that does not count down) and the measured request.

Every usage read is a fake session and every request a stub process: no test opens a Codex session or starts codex.exe,
and every home is a temporary folder.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src;tests" python -m unittest test_advanced_window_anchor
"""
from __future__ import annotations

from contextlib import nullcontext
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from codex_auto_resume.codex.transport import Backend  # noqa: E402
from codex_auto_resume.domain.plug import DEFER, Point  # noqa: E402
from codex_auto_resume.win.kernel import NO_WINDOW  # noqa: E402
from codex_auto_resume_advanced import measure, measured, registry, statement, surfaces  # noqa: E402
from codex_auto_resume_advanced.codex import protocol  # noqa: E402
from codex_auto_resume_advanced.engine import anchor  # noqa: E402
from codex_auto_resume_advanced.registry import WINDOW_ANCHOR  # noqa: E402
from codex_auto_resume_advanced.vocabulary import Actor, CapabilityKind, Measurement, OptionKey, Verdict  # noqa: E402

CAP = "window_anchor"
FIVE = anchor.WINDOW_SECONDS
# What the measured request is, word for word (plans/v0620-window-anchor-measure-result.md, Q2 (a)).
MEASURED = ["exec", "--skip-git-repo-check", "--ephemeral", "--json", "-s", "read-only", "-c",
            'model_reasoning_effort="low"', "Reply with OK"]
# What `codex exec --json` printed in the measurement, with a reply whose words must never be kept.
PRINTED = (b'{"type":"thread.started","thread_id":"00000000-0000-7000-8000-00000000abcd"}\n'
           b'{"type":"turn.started"}\n'
           b'{"type":"item.completed","item":{"type":"agent_message","text":"OK SECRET-REPLY-WORDS"}}\n'
           b'{"type":"turn.completed","usage":{"input_tokens":24138,"cached_input_tokens":12416,"output_tokens":5}}\n')


def reading(at, five, reset, week=48.0):
    """One reading as the capability keeps one: {"at", "windows"} with a codex 5-hour and weekly window."""
    return {"at": at, "windows": [
        {"bucket": "codex", "window": "primary", "used_percent": five, "window_minutes": 300, "reset_at": reset},
        {"bucket": "codex", "window": "secondary", "used_percent": week, "window_minutes": 10080,
         "reset_at": int(at) + 500000}]}


class JudgeTests(unittest.TestCase):
    """MANCHOR's rule: idle is 0 % and a ~5 h offset that moves with the clock between two reads."""
    T = 1_800_000_000

    def test_zero_percent_and_a_steady_five_hour_offset_is_idle(self):
        first, second = reading(self.T, 0, self.T + FIVE - 2), reading(self.T + 20, 0, self.T + 20 + FIVE - 1)
        self.assertEqual(anchor.judge(first, second), anchor.IDLE)
        # The measured reads: 17,998 s, 17,999 s fourteen seconds apart (and 20 s here, the gap).
        self.assertEqual(anchor.judge(reading(self.T, 0, self.T + 17998), reading(self.T + 47, 0, self.T + 47 + 17998)),
                         anchor.IDLE)

    def test_an_offset_that_counts_down_is_running_even_at_zero_percent(self):
        """Right after a request the window still reads 0 % (MANCHOR Q1) - but its reset stays put."""
        reset = self.T + FIVE - 7
        self.assertEqual(anchor.judge(reading(self.T, 0, reset), reading(self.T + 20, 0, reset)), anchor.RUNNING)
        self.assertEqual(anchor.judge(reading(self.T, 0, self.T + 3600), reading(self.T + 20, 0, self.T + 3620)),
                         anchor.RUNNING, "moving, but not five hours ahead: not what an idle window reports")

    def test_any_use_is_running(self):
        self.assertEqual(anchor.judge(reading(self.T, 1, self.T + FIVE), reading(self.T + 20, 0, self.T + 20 + FIVE)),
                         anchor.RUNNING)
        self.assertEqual(anchor.judge(reading(self.T, 0, self.T + FIVE), reading(self.T + 20, 0.4, self.T + 20 + FIVE)),
                         anchor.RUNNING)

    def test_a_full_weekly_window_and_what_cannot_be_read(self):
        idle = reading(self.T + 20, 0, self.T + 20 + FIVE)
        self.assertEqual(anchor.judge(reading(self.T, 0, self.T + FIVE, week=100), idle), anchor.WEEKLY_FULL)
        for broken in (None, {"at": self.T, "windows": None}, {"at": self.T, "windows": []},
                       reading(self.T, 0, None)):
            with self.subTest(broken=broken):
                self.assertEqual(anchor.judge(broken, idle), anchor.UNREADABLE)
        self.assertEqual(anchor.judge(reading(self.T + 10, 0, self.T + 10 + FIVE), idle), anchor.UNREADABLE,
                         "two reads closer than STEADY_GAP tell nothing")


class PureTests(unittest.TestCase):
    def test_a_time_is_held_as_its_minute_plus_two_and_said_as_hh_mm(self):
        self.assertEqual(anchor.encode_time(7, 0), 422)
        self.assertEqual(anchor.decode_time(422), 420)
        self.assertEqual(anchor.clock_text(anchor.encode_time(23, 59)), "23:59")
        self.assertEqual(anchor.clock_text(anchor.TIME_OFF), "")
        for wrong in ((24, 0), (7, 60), (-1, 0), ("7", 0)):
            self.assertIsNone(anchor.encode_time(*wrong))
        self.assertIsNone(anchor.decode_time(anchor.TIME_OFF))
        self.assertEqual(anchor.TIME_RANGE, (1, 1441))

    def test_only_the_turn_completed_counts_are_read_from_what_it_printed(self):
        self.assertEqual(anchor.tokens_of(PRINTED), {"input": 24138, "cached": 12416, "output": 5})
        self.assertEqual(anchor.tokens_of(b"not json\n"), {"input": None, "cached": None, "output": None})

    def test_signed_in_is_an_account_named(self):
        self.assertTrue(anchor.signed_in({"account": {"type": "chatgpt"}, "requiresOpenaiAuth": True}))
        self.assertFalse(anchor.signed_in({"account": None, "requiresOpenaiAuth": True}))
        self.assertIsNone(anchor.signed_in({"error": "x"}))


class DefinitionTests(unittest.TestCase):
    def test_a_route_at_p8_that_rests_on_manchor_and_names_what_it_departs_from(self):
        self.assertEqual((WINDOW_ANCHOR.kind, WINDOW_ANCHOR.points, WINDOW_ANCHOR.compat),
                         (CapabilityKind.ROUTE, frozenset({Point.TICK}), "usage_probe"))
        self.assertEqual(WINDOW_ANCHOR.departs_from, ("A1", "A2", "A13", "A25", "A26", "B3", "B4", "C4", "C9", "F6"))
        self.assertEqual(WINDOW_ANCHOR.measurements, (Measurement.MANCHOR,))
        self.assertEqual(measured.MEASURED[Measurement.MANCHOR], (Verdict.PASS, "codex-cli 0.165.0-alpha.1.2"))
        self.assertEqual(statement.CATALOGS.missing(WINDOW_ANCHOR), [])
        self.assertEqual([option.key for option in WINDOW_ANCHOR.options],
                         [OptionKey.ANCHOR_AT_1, OptionKey.ANCHOR_AT_2, OptionKey.ANCHOR_AT_3,
                          OptionKey.ANCHOR_AFTER_RESET])
        self.assertEqual(WINDOW_ANCHOR.option(OptionKey.ANCHOR_AT_1).default, anchor.TIME_OFF)
        order = registry.SHOWN_ORDER
        self.assertEqual(order[order.index(CAP) - 1], "usage_pause")

    def test_its_session_reads_usage_and_whether_an_account_is_signed_in_and_nothing_more(self):
        self.assertEqual(protocol.methods_for_capability(CAP),
                         frozenset({"initialize", "initialized", "account/rateLimits/read", "account/read"}))


# ---------------------------------------------------------------------------- the capability, end to end
class World:
    """Codex as this capability sees it: a 5-hour window idle (its reset now + 5 h, read after read) or running (a
    fixed reset), the weekly window, an account signed in or not, and a request that starts the window."""

    def __init__(self, case):
        self.case = case
        self.running_until = None
        self.used = 0.0
        self.week = 48.0
        self.signed = True
        self.broken = False
        self.calls = []
        self.started = []
        self.code, self.printed, self.slow = 0, PRINTED, False

    def now(self):
        return int(self.case.now)

    def reply(self):
        now = self.now()
        running = self.running_until is not None and self.running_until > now
        reset = self.running_until if running else now + FIVE - 1
        return {"rateLimitsByLimitId": {"codex": {
            "primary": {"usedPercent": self.used if running else 0.0, "windowDurationMins": 300, "resetsAt": reset},
            "secondary": {"usedPercent": self.week, "windowDurationMins": 10080, "resetsAt": now + 500000}}}}

    def session(self):
        world = self

        class Session:
            def __enter__(self):
                return self

            def __exit__(self, *unused):
                return False

            def call(self, method, params=None):
                world.calls.append(method)
                if world.broken:
                    raise RuntimeError("no answer")
                if method == "account/read":
                    return {"account": {"type": "chatgpt"} if world.signed else None, "requiresOpenaiAuth": True}
                return world.reply()
        return Session()

    def popen(self, argv, **options):
        world = self

        class Process:
            returncode = None
            killed = False

            def communicate(self, timeout=None):
                if world.slow and timeout is not None and timeout > anchor.KILL_WAIT:
                    raise subprocess.TimeoutExpired(argv, timeout)
                if world.code == 0 and not world.slow:
                    world.running_until = world.now() + FIVE
                self.returncode = world.code
                return world.printed, None

            def kill(self):
                self.killed = True
        made = Process()
        self.started.append((argv, options, made))
        return made


class View:
    """What core shows a plug at P8, as far as this capability reads it: core's settings."""

    def __init__(self):
        self.enabled, self.observe_only = True, False

    def settings(self):
        return {"enabled": self.enabled, "armed_at": 1, "poll_seconds": 30, "observe_only": self.observe_only}

    def records_in(self, states):
        return []


class AnchorCase(ac.AdvancedCase):
    def setUp(self):
        super().setUp()
        self.compat = ac.view(capability="usage_probe")
        self.measured = dict(measured.MEASURED)
        # A morning at 06:59:30 local time, a few seconds after the last look.
        self.now = float(anchor.midnight(ac.NOW) + 7 * 3600 - 30)
        self.world = World(self)
        self.view = View()
        self.permitted = True
        self.lines = []
        self.told = (Path("C:/fake/codex.exe"), self.home / "codex")
        self.rt = self.runtime(WINDOW_ANCHOR)
        self.rt.arming.catalogs = statement.CATALOGS
        # The one start of the request is subprocess.Popen's (test_no_console_windows follows every start): a stub here.
        patched = patch.object(subprocess, "Popen", self.world.popen)
        patched.start()
        self.addCleanup(patched.stop)
        self.wire()

    def wire(self):
        code = self.rt._code_of(WINDOW_ANCHOR)
        code._session = self.world.session
        code._told = lambda: self.told
        code._make_backend = lambda: Backend(self.home / "codex", Path("C:/fake/codex.exe"))
        code._begin = lambda target: target()
        code._log = self.lines.append
        self.code = code

    def restart(self):
        self.rt.state.close()
        self.rt = self.runtime(WINDOW_ANCHOR)
        self.rt.arming.catalogs = statement.CATALOGS
        self.rt.states(fresh=True)
        self.wire()

    def on(self, state="armed", **options):
        result = self.rt.arming.arm(CAP, state=state, revision=WINDOW_ANCHOR.revision,
                                    generation=self.rt.state.meta()["generation"], acknowledged_version=ac.ENGINE,
                                    warnings=[str(w) for w in self.rt.arming.warnings(WINDOW_ANCHOR)],
                                    actor=Actor.DASHBOARD)
        self.assertTrue(result["done"], result)
        for key, value in options.items():
            self.rt.state.set_option(CAP, OptionKey(key), value, generation=self.rt.state.meta()["generation"],
                                     actor=Actor.DASHBOARD)
        self.rt.states(fresh=True)

    def look(self, after=anchor.LOOK_EVERY):
        """Time passes, then one tick, its errand run inside a guard that says what core's says."""
        self.now += after
        answer = self.rt.tick(self.view)
        if answer is not DEFER:
            answer.run(lambda: nullcontext(self.permitted))

    def run_through(self, looks=8):
        """Enough looks, STEADY_GAP apart, for an occasion's two reads, its request and the two reads after."""
        for _look in range(looks):
            self.look(anchor.STEADY_GAP)

    def codes(self):
        with self.rt.state._read() as connection:
            return [row[0] for row in connection.execute("SELECT code FROM journal")
                    if str(row[0]).startswith("anchor.")]

    def stamped(self, key):
        return self.rt.state.stamped(CAP, key)


class OffTests(AnchorCase):
    def test_off_nothing_is_read_and_nothing_started(self):
        self.on(state="armed", anchor_at_1=anchor.encode_time(7, 0))
        self.rt.arming.disarm(CAP, actor=Actor.DASHBOARD)
        self.rt.states(fresh=True)
        self.run_through()
        self.assertEqual((self.world.calls, self.world.started), ([], []))

    def test_watched_it_is_only_journalled_never_read_or_started(self):
        self.on(state="shadow", anchor_at_1=anchor.encode_time(7, 0))
        self.run_through()
        self.assertEqual((self.world.calls, self.world.started), ([], []))


class AtTimesTests(AnchorCase):
    def test_at_a_time_picked_an_idle_window_is_started_once_and_its_reset_kept(self):
        self.on(anchor_at_1=anchor.encode_time(7, 0), anchor_after_reset=2)
        self.look(10)
        self.assertEqual(self.world.calls, [], "06:59:40: not yet")
        self.run_through()
        self.assertEqual(len(self.world.started), 1)
        fixed = self.stamped(OptionKey.ANCHOR_FIXED_AT)
        started = self.stamped(OptionKey.ANCHOR_STARTED_AT)
        self.assertEqual(fixed, self.world.running_until)
        self.assertTrue(0 < fixed - started <= FIVE + anchor.STEADY_GAP)
        self.assertEqual(self.codes()[-2:], ["anchor.started", "anchor.fixed"])
        self.assertEqual((self.stamped(OptionKey.ANCHOR_INPUT_TOKENS), self.stamped(OptionKey.ANCHOR_OUTPUT_TOKENS)),
                         (24138, 5))
        self.assertEqual(surfaces.status(self.rt)[CAP], {"started_at": started, "fixed_at": fixed})
        self.assertEqual(len(self.lines), 1)
        self.assertIn("next reset is fixed at", self.lines[0])
        # The rest of the day, and that time again within its grace: nothing more.
        self.run_through(20)
        self.look(anchor.SLOT_GRACE)
        self.assertEqual(len(self.world.started), 1)

    def test_a_time_picked_is_taken_once_a_day_and_again_the_next(self):
        self.on(anchor_at_1=anchor.encode_time(7, 0), anchor_after_reset=2)
        self.run_through()
        self.assertEqual(len(self.world.started), 1)
        self.now = float(anchor.midnight(self.now) + 86400 + 7 * 3600 - 30)
        self.world.running_until = None
        self.run_through()
        self.assertEqual(len(self.world.started), 2)

    def test_at_a_time_picked_a_window_that_runs_is_left_alone(self):
        self.on(anchor_at_1=anchor.encode_time(7, 0), anchor_after_reset=2)
        self.world.running_until, self.world.used = int(self.now) + 3600, 12.0
        self.run_through()
        self.assertEqual(self.world.started, [])
        self.assertEqual(self.codes(), ["anchor.skip_running"])

    def test_a_window_at_zero_percent_whose_reset_counts_down_is_running_too(self):
        self.on(anchor_at_1=anchor.encode_time(7, 0), anchor_after_reset=2)
        self.world.running_until, self.world.used = int(self.now) + FIVE - 40, 0.0
        self.run_through()
        self.assertEqual(self.world.started, [])
        self.assertEqual(self.codes(), ["anchor.skip_running"])

    def test_a_time_missed_by_more_than_its_grace_is_not_taken(self):
        self.on(anchor_at_1=anchor.encode_time(6, 0), anchor_after_reset=2)
        self.run_through()
        self.assertEqual((self.world.calls, self.world.started), ([], []))


class AfterResetTests(AnchorCase):
    def test_right_after_a_reset_it_saw_an_idle_window_is_started(self):
        self.on()                                               # Start right after a reset: on by default
        self.world.running_until, self.world.used = int(self.now) + 600, 30.0
        self.look()
        self.assertEqual(self.stamped(OptionKey.ANCHOR_SEEN_RESET), self.world.running_until, "learned")
        self.run_through()
        self.assertEqual(self.world.started, [], "not before that reset")
        self.now = float(self.world.running_until + anchor.AFTER_RESET)
        self.run_through()
        self.assertEqual(len(self.world.started), 1)
        # Its own start fixed the next reset: the window is kept back to back.
        self.assertEqual(self.stamped(OptionKey.ANCHOR_SEEN_RESET), self.world.running_until)
        self.now = float(self.world.running_until + anchor.AFTER_RESET)
        self.run_through()
        self.assertEqual(len(self.world.started), 2)

    def test_an_idle_window_with_no_reset_seen_is_never_started_by_it(self):
        self.on()
        self.run_through(10)
        self.look(anchor.LEARN_EVERY)
        self.run_through(10)
        self.assertEqual(self.world.started, [])
        self.assertEqual(set(self.world.calls), {"account/rateLimits/read"}, "it only reads, to learn a reset")

    def test_after_a_reset_a_window_the_person_already_started_is_left_alone(self):
        self.on()
        self.world.running_until, self.world.used = int(self.now) + 600, 30.0
        self.look()
        self.now = float(self.world.running_until + anchor.AFTER_RESET)
        self.world.running_until, self.world.used = int(self.now) + FIVE - 120, 2.0
        self.run_through()
        self.assertEqual(self.world.started, [])
        self.assertEqual(self.codes(), ["anchor.skip_running"])


class CapTests(AnchorCase):
    def test_never_while_the_weekly_window_is_full(self):
        self.on(anchor_at_1=anchor.encode_time(7, 0), anchor_after_reset=2)
        self.world.week = 100.0
        self.run_through()
        self.assertEqual((self.world.started, self.codes()), ([], ["anchor.skip_weekly"]))

    def test_never_while_recovery_is_paused_or_only_observed_and_nothing_is_read(self):
        for field in ("enabled", "observe_only"):
            with self.subTest(field=field):
                self.restart()
                self.now = float(anchor.midnight(self.now) + 86400 + 7 * 3600 - 30)
                self.on(anchor_at_1=anchor.encode_time(7, 0), anchor_after_reset=2)
                self.view = View()
                setattr(self.view, field, field == "observe_only")
                self.world.calls = []
                self.run_through()
                self.assertEqual((self.world.calls, self.world.started), ([], []))
                self.assertEqual(self.codes()[-1], "anchor.skip_paused")

    def test_a_pause_that_core_s_guard_holds_at_the_start_starts_nothing(self):
        self.on(anchor_at_1=anchor.encode_time(7, 0), anchor_after_reset=2)
        self.permitted = False
        self.run_through()
        self.assertEqual(self.world.started, [])
        self.assertEqual(self.codes(), ["anchor.skip_paused"])
        self.assertIsNone(self.stamped(OptionKey.ANCHOR_STARTED_AT))

    def test_never_when_no_account_is_signed_in_or_usage_cannot_be_read(self):
        self.on(anchor_at_1=anchor.encode_time(7, 0), anchor_at_2=anchor.encode_time(8, 0), anchor_after_reset=2)
        self.world.signed = False
        self.run_through()
        self.now = float(anchor.midnight(self.now) + 8 * 3600 - 30)
        self.world.signed, self.world.broken = True, True
        self.run_through()
        self.assertEqual(self.world.started, [])
        self.assertEqual(self.codes(), ["anchor.skip_signed_out", "anchor.skip_unreadable"])

    def test_a_second_start_in_one_window_is_refused(self):
        self.on(anchor_at_1=anchor.encode_time(7, 0), anchor_at_2=anchor.encode_time(8, 0), anchor_after_reset=2)
        self.run_through()
        self.assertEqual(len(self.world.started), 1)
        self.world.running_until = None                      # whatever the reads say an hour on
        self.now = float(anchor.midnight(self.now) + 8 * 3600 - 30)
        self.run_through()
        self.assertEqual(len(self.world.started), 1)
        self.assertEqual(self.codes()[-1], "anchor.skip_once")
        self.assertNotIn("account/read", self.world.calls[-1:], "refused before anything is read")

    def test_never_for_a_codex_the_watcher_did_not_tell_or_from_a_folder_not_empty(self):
        self.on(anchor_at_1=anchor.encode_time(7, 0), anchor_at_2=anchor.encode_time(8, 0), anchor_after_reset=2)
        self.told = None
        self.run_through()
        self.assertEqual((self.world.calls, self.world.started), ([], []))
        self.told = (Path("C:/fake/codex.exe"), self.home / "codex")
        folder = anchor.folder_of(self.paths)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "left.txt").write_text("x", encoding="utf-8")
        self.now = float(anchor.midnight(self.now) + 8 * 3600 - 30)
        self.run_through()
        self.assertEqual(self.world.started, [])
        self.assertEqual(self.codes(), ["anchor.skip_home", "anchor.skip_folder"])


class RequestTests(AnchorCase):
    def test_the_request_is_the_measured_one_windowless_in_its_own_empty_folder(self):
        self.on(anchor_at_1=anchor.encode_time(7, 0), anchor_after_reset=2)
        self.run_through()
        (argv, options, _process), = self.world.started
        backend = Backend(self.home / "codex", Path("C:/fake/codex.exe"))
        self.assertEqual(argv, backend._argv() + MEASURED)
        self.assertEqual(argv[len(backend._argv()):], MEASURED)
        self.assertEqual(argv[0], str(Path("C:/fake/codex.exe").resolve()))
        self.assertEqual(options["creationflags"], NO_WINDOW)
        self.assertNotEqual(NO_WINDOW, 0)
        self.assertIs(options["shell"], False)
        self.assertEqual(options["stdin"], subprocess.DEVNULL)
        self.assertEqual(Path(options["cwd"]), anchor.folder_of(self.paths))
        self.assertTrue(Path(options["cwd"]).is_relative_to(self.paths.advanced_dir))
        self.assertEqual(options["env"]["CODEX_HOME"], str((self.home / "codex").resolve()))
        self.assertEqual(options["env"]["OTEL_SDK_DISABLED"], "true")

    def test_nothing_it_printed_is_kept_or_logged(self):
        self.on(anchor_at_1=anchor.encode_time(7, 0), anchor_after_reset=2)
        self.run_through()
        self.assertEqual(len(self.world.started), 1)
        found = []
        for path in self.home.rglob("*"):
            if path.is_file():
                data = path.read_bytes()
                found += [path.name for word in (b"SECRET-REPLY-WORDS", b"Reply with OK", b"abcd")
                          if word in data]
        self.assertEqual(found, [])
        self.assertFalse([line for line in self.lines if "SECRET" in line or "OK" in line.split(":", 1)[0]])
        with self.rt.state._read() as connection:
            values = [row[0] for row in connection.execute("SELECT value FROM options WHERE capability=?", (CAP,))]
        self.assertTrue(all(type(value) is int for value in values))

    def test_a_request_that_fails_or_hangs_is_counted_and_never_sent_again_in_that_window(self):
        self.on(anchor_at_1=anchor.encode_time(7, 0), anchor_at_2=anchor.encode_time(8, 0), anchor_after_reset=2)
        self.world.code = 1
        self.run_through()
        self.assertEqual(self.codes(), ["anchor.started", "anchor.failed"])
        self.world.code, self.world.slow = 0, True
        self.now = float(anchor.midnight(self.now) + 8 * 3600 - 30)
        self.run_through()
        self.assertEqual(len(self.world.started), 1, "one start a window, whatever came of it")
        self.assertEqual(self.codes()[-1], "anchor.skip_once")

    def test_a_request_past_its_bound_is_ended_and_said(self):
        self.on(anchor_at_1=anchor.encode_time(7, 0), anchor_after_reset=2)
        self.world.slow = True
        self.run_through()
        (_argv, _options, process), = self.world.started
        self.assertTrue(process.killed)
        self.assertEqual(self.codes(), ["anchor.started", "anchor.timed_out"])
        self.assertIn("did not finish", self.lines[-1])
        self.assertEqual(anchor.TIMEOUT, 120)

    def test_a_watcher_started_again_keeps_what_it_handled(self):
        self.on(anchor_at_1=anchor.encode_time(7, 0), anchor_after_reset=2)
        self.run_through()
        self.restart()
        self.world.running_until = None
        self.run_through()
        self.assertEqual(len(self.world.started), 1)


class ProbeTests(unittest.TestCase):
    """MANCHOR's probe: two reads that find the window idle, the capability's own request once (a hand, faked here),
    and two reads that find it started with its reset five hours on - left blocked for the person's /usage look."""

    def setUp(self):
        self.now = 1_800_000_000.0
        self.world = World(self)
        self.asked = []
        for patched in (patch.object(measure.time, "time", lambda: self.now),
                        patch.object(measure.time, "sleep", self.sleep)):
            patched.start()
            self.addCleanup(patched.stop)

    def sleep(self, seconds):
        self.now += seconds

    def request(self):
        self.asked.append(self.now)
        process = self.world.popen(["codex"])
        printed, _ = process.communicate(timeout=anchor.TIMEOUT)
        return dict(anchor.tokens_of(printed), code=process.returncode, folder_empty_after=True)

    def run_probe(self):
        ctx = measure.Context(Measurement.MANCHOR, session_factory=lambda _measurement: self.world.session(),
                              hands={"anchor_request": self.request})
        return measure.probe(ctx)

    def test_an_idle_window_started_by_the_request_is_left_for_the_person_to_confirm(self):
        verdict, observed, note = self.run_probe()
        self.assertEqual(verdict, Verdict.BLOCKED)
        self.assertEqual({key: observed[key] for key in ("idle_before", "request_exit_zero", "window_started",
                                                          "reset_near_five_hours", "folder_empty_after")},
                         dict.fromkeys(("idle_before", "request_exit_zero", "window_started", "reset_near_five_hours",
                                        "folder_empty_after"), True))
        self.assertEqual((observed["input_tokens"], observed["cached_tokens"], observed["output_tokens"]),
                         (24138, 12416, 5))
        self.assertIn("/usage", note)
        self.assertEqual(len(self.asked), 1)

    def test_a_window_that_runs_is_not_started_and_the_probe_asks_to_wait(self):
        self.world.running_until, self.world.used = int(self.now) + 3600, 5.0
        verdict, observed, note = self.run_probe()
        self.assertEqual((verdict, observed["idle_before"], self.asked), (Verdict.BLOCKED, False, []))
        self.assertIn("idle", note)

    def test_a_request_that_leaves_the_window_idle_fails(self):
        self.world.code = 1
        verdict, observed, _note = self.run_probe()
        self.assertEqual((verdict, observed["request_exit_zero"], observed["window_started"]),
                         (Verdict.FAIL, False, False))

    def test_its_session_reads_usage_and_nothing_else(self):
        self.assertEqual(protocol.methods_for(Measurement.MANCHOR) - {"initialize", "initialized"},
                         frozenset({"account/rateLimits/read"}))


class OnlyTheWatcherStartsItTests(unittest.TestCase):
    """The request is the watcher's errand: no front end - the bridge, the panel, the window, MCP - reaches it."""

    def test_only_the_engine_module_and_the_measurement_name_the_request(self):
        root = Path(anchor.__file__).resolve().parents[1]
        users = sorted(str(path.relative_to(root)).replace("\\", "/") for path in root.rglob("*.py")
                       if path.name != "anchor.py" and "start_request" in path.read_text(encoding="utf-8"))
        self.assertEqual(users, ["measure.py"])
        source = Path(anchor.__file__).read_text(encoding="utf-8")
        self.assertEqual(source.count("= start_request(backend, folder)"), 1)


if __name__ == "__main__":
    unittest.main()
