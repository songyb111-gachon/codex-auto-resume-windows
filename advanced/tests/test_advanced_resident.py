"""The resident courier (v0.6.22, plans/v0619-design/D-remote.md; engine/remote.py, courier/resident.py): started by the
watcher only while what needs it stands on, at most three more times in an hour and then the card says stopped, with no
console window, and closing what was turned off. Nothing is started while off: no process, no socket, no thread.

A process is never started and no real port is taken but where a test says so (a real socket on a port the system picks,
and a real named mutex under the test's own temporary home).

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import socket
from pathlib import Path
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from codex_auto_resume.domain.plug import DEFER, Point  # noqa: E402
from codex_auto_resume.win.kernel import NO_WINDOW  # noqa: E402
from codex_auto_resume_advanced import courier as _package, registry, statement  # noqa: E402,F401
from codex_auto_resume_advanced.control import remote as card  # noqa: E402
from codex_auto_resume_advanced.courier import __main__ as courier, launch, resident  # noqa: E402
from codex_auto_resume_advanced.engine import remote  # noqa: E402
from codex_auto_resume_advanced.registry import LOCAL_API, LOCAL_API_ACTIONS  # noqa: E402
from codex_auto_resume_advanced.vocabulary import ArmingState, Refusal  # noqa: E402


class ResidentCase(ac.AdvancedCase):
    DEFINITIONS = (LOCAL_API, LOCAL_API_ACTIONS)

    def setUp(self):
        super().setUp()
        self.compat = ac.view(capability="engine_present")
        self.catalogs = statement.CATALOGS
        self.rt = self.runtime(*self.DEFINITIONS)
        self.rt.arming.catalogs = statement.CATALOGS
        self.alive = False
        self.started = []

    def code(self):
        made = self.rt._code_of(self.rt.registry.get("local_api"))
        made._running = lambda paths: self.alive
        made._launch = lambda paths: self.started.append(paths) or True
        return made

    def tick(self):
        """One P8, as core asks it, and its errand run as core runs it."""
        self.code()
        answer = self.rt.tick({})
        if answer is not DEFER:
            answer.run(None)
        return answer


class ArmedTests(ResidentCase):
    def test_off_it_is_not_asked_and_nothing_starts(self):
        """Fails where the errand is made whatever it stands at."""
        self.assertIs(self.tick(), DEFER)
        self.assertEqual(self.started, [])

    def test_watched_nothing_starts_and_it_says_it_would_have(self):
        """Fails where a watched capability's errand runs: a watched server would listen."""
        self.assertTrue(self.arm(self.rt, "local_api", state="shadow")["done"])
        self.assertIs(self.tick(), DEFER)
        self.assertEqual(self.started, [])
        self.assertEqual([line["code"] for line in self.rt.state.journal(capability="local_api")
                          if line["code"].startswith("api.")], [])

    def test_on_a_resident_is_started_and_journalled_and_one_that_runs_is_left(self):
        self.assertTrue(self.arm(self.rt, "local_api")["done"])
        self.tick()
        self.assertEqual(len(self.started), 1)
        self.assertEqual(len(self.rt.state.journal_times("local_api", remote.START_WORD, 0)), 1)
        self.alive = True
        self.now += 100
        self.assertIs(self.tick(), DEFER)
        self.assertEqual(len(self.started), 1)

    def test_a_start_is_given_time_to_take_its_mutex(self):
        self.assertTrue(self.arm(self.rt, "local_api")["done"])
        self.tick()
        self.now += remote.STARTING - 1
        self.tick()
        self.assertEqual(len(self.started), 1)
        self.now += 1
        self.tick()
        self.assertEqual(len(self.started), 2)

    def test_a_start_that_failed_is_not_counted(self):
        self.assertTrue(self.arm(self.rt, "local_api")["done"])
        made = self.code()
        made._launch = lambda paths: False
        answer = self.rt.tick({})
        answer.run(None)
        self.assertEqual(self.rt.state.journal_times("local_api", remote.START_WORD, 0), [])

    def test_a_paused_watcher_asks_nothing_core_s_rule(self):
        """Core asks P8 only after its consent gate (K5): nothing here starts anything of its own accord."""
        self.assertEqual(self.rt.registry.get("local_api").points, frozenset({Point.TICK}))
        self.assertEqual(self.rt.registry.get("local_api_actions").points, frozenset())


class CapTests(ResidentCase):
    def setUp(self):
        super().setUp()
        self.assertTrue(self.arm(self.rt, "local_api")["done"])

    def run_out(self):
        for _ in range(1 + remote.RESTARTS):
            self.tick()
            self.now += remote.STARTING

    def test_the_first_and_three_restarts_in_an_hour_then_no_more_and_the_card_says_stopped(self):
        """Fails with the cap reverted: a resident that dies at once is restarted every tick for ever."""
        self.run_out()
        self.assertEqual(len(self.started), 1 + remote.RESTARTS)
        for _ in range(5):
            self.tick()
            self.now += remote.STARTING
        self.assertEqual(len(self.started), 1 + remote.RESTARTS)
        view = card.api_view(self.rt, running=lambda runtime: False, secrets=_NoToken())
        self.assertEqual(view["state"], "stopped")
        said = [line["code"] for line in self.rt.state.journal(capability="local_api")]
        self.assertEqual(said.count("api.gave_up"), 1, "said once, not every tick")

    def test_past_the_hour_it_is_tried_again(self):
        self.run_out()
        self.now += remote.HOUR
        self.tick()
        self.assertEqual(len(self.started), 2 + remote.RESTARTS)
        self.assertEqual(card.api_view(self.rt, running=lambda runtime: False, secrets=_NoToken())["state"], "starting")

    def test_the_count_outlives_the_watcher_that_made_it(self):
        """Fails with the starts kept in a module's memory, as the draft had them: the Dashboard's process and a watcher
        that restarted would each see none."""
        self.run_out()
        again = self.runtime(*self.DEFINITIONS)
        again.arming.catalogs = statement.CATALOGS
        self.rt = again
        self.tick()
        self.assertEqual(len(self.started), 1 + remote.RESTARTS)
        self.assertEqual(card.api_view(again, running=lambda runtime: False, secrets=_NoToken())["state"], "stopped")


class _NoToken:
    def read(self, capability, name):
        return None


class LaunchTests(ResidentCase):
    def test_the_child_has_no_console_and_is_this_program_with_serve(self):
        """Fails where CREATE_NO_WINDOW is dropped from the start."""
        seen = {}

        class Process:
            pid = 1

            def poll(self):
                return None

        def popen(command, **keywords):
            seen.update(command=command, **keywords)
            return Process()
        self.assertTrue(launch.start(self.paths, "--serve", popen=popen, adopt_it=lambda process: None))
        self.addCleanup(launch._CHILDREN.clear)
        self.assertEqual(seen["creationflags"] & NO_WINDOW, NO_WINDOW)
        self.assertIs(seen["shell"], False)
        self.assertEqual(seen["command"][-1], "--serve")
        self.assertIn("pythonw", Path(seen["command"][0]).name.lower())
        self.assertIn("codex_auto_resume_advanced.courier", seen["command"])

    def test_serve_is_the_only_new_argument(self):
        self.assertEqual(courier.parse(["--home", "H", "--serve"]), {"home": "H", "mode": "serve", "channel": None})
        self.assertIsNone(courier.parse(["--home", "H", "--serve", "--pair"]))
        self.assertIsNone(courier.parse(["--home", "H", "--serve", "1"]))


class _Server:
    def __init__(self):
        self.closed = 0

    def close(self):
        self.closed += 1


class RolesTests(ResidentCase):
    def setUp(self):
        super().setUp()
        self.made, self.servers = [], []

    def server(self, runtime, port, lan):
        self.made.append((port, lan))
        self.servers.append(_Server())
        return self.servers[-1]

    def test_off_nothing_is_served_and_the_process_ends(self):
        """Nothing is started while off: `serve` returns at its first look."""
        self.assertEqual(resident.serve(self.rt, server=self.server, sleep=self.fail), courier.EXIT_DONE)
        self.assertEqual(self.made, [])

    def test_watched_nothing_is_served(self):
        self.assertTrue(self.arm(self.rt, "local_api", state="shadow")["done"])
        self.assertEqual(resident.serve(self.rt, server=self.server, sleep=self.fail), courier.EXIT_DONE)
        self.assertEqual(self.made, [])

    def test_on_it_serves_on_loopback_on_the_port_chosen(self):
        self.assertTrue(self.arm(self.rt, "local_api")["done"])
        roles = resident.Roles(self.rt, server=self.server)
        self.assertTrue(roles.follow())
        self.assertEqual(self.made, [(remote.DEFAULT_PORT, False)])
        self.assertTrue(roles.follow())
        self.assertEqual(len(self.made), 1, "not started twice")
        generation = self.rt.state.meta()["generation"]
        self.assertTrue(self.rt.arming.set_option("local_api", "api_port", 8123, generation=generation,
                                                  actor="dashboard")["done"])
        self.assertTrue(roles.follow())
        self.assertEqual(self.made[-1], (8123, False))
        self.assertEqual(self.servers[0].closed, 1, "the old one closed first")

    def test_turned_off_it_closes_and_the_process_ends(self):
        """Fails with the check of the states reverted: a person's Turn off would leave it listening."""
        self.assertTrue(self.arm(self.rt, "local_api")["done"])
        roles = resident.Roles(self.rt, server=self.server)
        self.assertTrue(roles.follow())
        self.rt.arming.disarm("local_api", actor="dashboard")
        self.assertFalse(roles.follow())
        self.assertEqual(self.servers[0].closed, 1)
        lines = [line["code"] for line in self.rt.state.journal(capability="local_api")]
        self.assertLess(lines.index("api.started"), lines.index("api.stopped"))

    def test_what_cannot_be_read_serves_nothing(self):
        self.assertTrue(self.arm(self.rt, "local_api")["done"])
        roles = resident.Roles(self.rt, server=self.server)
        roles.follow()
        with patch.object(self.rt, "states", side_effect=RuntimeError("no")):
            self.assertFalse(roles.follow())
        self.assertEqual(self.servers[0].closed, 1)

    def test_a_port_taken_is_journalled_once_said_on_the_card_and_tried_again(self):
        self.assertTrue(self.arm(self.rt, "local_api")["done"])
        attempts = []

        def taken(runtime, port, lan):
            attempts.append(port)
            raise OSError("in use")
        roles = resident.Roles(self.rt, server=taken)
        self.assertTrue(roles.follow())
        self.assertTrue(roles.follow())
        self.assertEqual(len(attempts), 2)
        said = [line["code"] for line in self.rt.state.journal(capability="local_api")]
        self.assertEqual(said.count("api.port_taken"), 1)
        self.assertEqual(card.api_view(self.rt, running=lambda runtime: True, secrets=_NoToken())["state"], "port_taken")
        self.now += 1
        roles._server_factory = self.server
        self.assertTrue(roles.follow())
        self.assertEqual(card.api_view(self.rt, running=lambda runtime: True, secrets=_NoToken())["state"], "running")

    def test_a_real_server_binds_loopback_alone_and_really_closes(self):
        """A real socket: what the resident's server holds is 127.0.0.1, and once closed nothing answers there."""
        from codex_auto_resume_advanced.courier import api
        self.assertTrue(self.arm(self.rt, "local_api")["done"])
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            free = probe.getsockname()[1]
        generation = self.rt.state.meta()["generation"]
        self.assertTrue(self.rt.arming.set_option("local_api", "api_port", free, generation=generation,
                                                  actor="dashboard")["done"])
        roles = resident.Roles(self.rt)
        self.assertTrue(roles.follow())
        self.assertEqual(roles.server.server.server_address, ("127.0.0.1", free))
        self.assertIsInstance(roles.server, api.Running)
        with socket.create_connection(("127.0.0.1", free), timeout=5):
            pass
        self.rt.arming.disarm("local_api", actor="dashboard")
        self.assertFalse(roles.follow())
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", free), timeout=2).close()

    def test_a_second_one_on_a_held_port_is_refused_not_shared(self):
        """SO_EXCLUSIVEADDRUSE: no other program may share the port and hear a token. Fails with it reverted only where
        Windows would have allowed a shared bind."""
        from codex_auto_resume_advanced.courier import api
        self.assertTrue(self.arm(self.rt, "local_api")["done"])
        first = api.start(self.rt, 0, False, service=api.Service(self.rt, 0, False))
        self.addCleanup(first.close)
        with self.assertRaises(OSError):
            api.start(self.rt, first.port, False, service=api.Service(self.rt, first.port, False))


class NothingWhileOffTests(ResidentCase):
    def test_while_off_no_process_no_socket_and_no_thread(self):
        """Every way something could start is made to fail the test, and the watcher's tick and the card are asked."""
        before = set(threading.enumerate())

        def no(*unused, **keywords):
            raise AssertionError("something was started while off")
        with patch.object(subprocess, "Popen", no), patch.object(socket, "socket", no), \
                patch.object(threading.Thread, "start", no), patch.object(launch, "start", no):
            self.assertIs(self.rt.tick({}), DEFER)
            self.assertEqual(card.api_view(self.rt, secrets=_NoToken())["state"], "off")
            self.assertEqual(card.api_token_new(self.rt, secrets=_NoToken())["refusal"], Refusal.NOT_ON)
            for definition in self.DEFINITIONS:
                self.rt._code_of(definition)
            self.assertEqual(resident.serve(self.rt, sleep=self.fail), courier.EXIT_DONE)
        self.assertEqual(set(threading.enumerate()) - before, set())

    def test_importing_the_edition_loads_no_networking_code(self):
        """The registry names the errand: taking the package must not take the server. In a process of its own, as what is
        already imported here would hide it."""
        code = ("import sys\n"
                "import codex_auto_resume_advanced.registry\n"
                "import codex_auto_resume_advanced.engine.remote\n"
                "import codex_auto_resume_advanced.control.remote\n"
                "bad = [m for m in ('http.server', 'socketserver', 'codex_auto_resume_advanced.courier.api',\n"
                "                   'codex_auto_resume_advanced.courier.page') if m in sys.modules]\n"
                "sys.exit(repr(bad) if bad else 0)\n")
        root = Path(__file__).resolve().parents[2]
        found = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120,
                               env=dict(_environment(), PYTHONPATH="%s;%s" % (root / "src", root / "advanced" / "src")),
                               creationflags=NO_WINDOW)
        self.assertEqual((found.returncode, found.stderr), (0, ""))


def _environment():
    import os
    return dict(os.environ, CODEX_AR_EDITION="advanced")


class MutexTests(ac.AdvancedCase):
    def test_running_opens_the_mutex_and_never_takes_it(self):
        """A real named mutex under this test's own home: not there, there, and gone. Fails where the probe creates it -
        a resident starting at that moment would be turned away."""
        self.assertFalse(resident.running(self.paths))
        self.assertFalse(resident.running(self.paths), "probing did not make it")
        with resident.mutex(self.paths):
            self.assertTrue(resident.running(self.paths))
        self.assertFalse(resident.running(self.paths))

    def test_the_resident_s_mutex_is_not_the_short_courier_s(self):
        """So a resident that runs for hours never holds a notice or a pairing back."""
        self.assertNotEqual(resident.mutex(self.paths).name, courier.mutex(self.paths).name)
        with resident.mutex(self.paths):
            with courier.mutex(self.paths):
                pass

    def test_a_second_resident_exits_busy(self):
        """A mutex is its owner thread's: another thread holds it here, as another process would."""
        taken, finish = threading.Event(), threading.Event()

        def hold():
            with resident.mutex(self.paths):
                taken.set()
                finish.wait(30)
        holder = threading.Thread(target=hold)
        holder.start()
        self.addCleanup(holder.join)
        self.addCleanup(finish.set)
        self.assertTrue(taken.wait(10))
        self.assertEqual(courier.main(["--home", str(self.paths.home), "--serve"], runtime=lambda paths: self.fail()),
                         courier.EXIT_BUSY)


class MainTests(ResidentCase):
    def test_main_serves_under_its_mutex_and_returns_when_nothing_is_wanted(self):
        self.assertEqual(courier.main(["--home", str(self.paths.home), "--serve"], runtime=lambda paths: self.rt,
                                      sleep=self.fail), courier.EXIT_DONE)

    def test_rounds_keep_it_for_a_test(self):
        self.assertTrue(self.arm(self.rt, "local_api")["done"])
        servers = []

        def server(runtime, port, lan):
            servers.append(_Server())
            return servers[-1]
        self.assertEqual(courier.main(["--home", str(self.paths.home), "--serve"], runtime=lambda paths: self.rt,
                                      server=server, sleep=lambda seconds: None, rounds=2), courier.EXIT_DONE)
        self.assertEqual((len(servers), servers[0].closed), (1, 1), "closed on the way out")


class ArmingTests(ResidentCase):
    def also(self, capability="local_api"):
        return [{"capability": capability, "revision": 1, "warnings": [], "engine_version": ac.ENGINE}]

    def test_both_are_off_until_a_person_turns_them_on(self):
        states = self.rt.states(fresh=True)
        self.assertEqual((states.get("local_api", ArmingState.OFF), states.get("local_api_actions", ArmingState.OFF)),
                         (ArmingState.OFF, ArmingState.OFF))

    def test_the_second_arming_needs_the_first_in_the_same_confirmation(self):
        """Fails with `requires` dropped: the actions could stand on with no server, and turn on without a word about it."""
        refused = self.arm(self.rt, "local_api_actions")
        self.assertFalse(refused["done"])
        self.assertEqual(refused["refusal"], Refusal.REQUIREMENT_REFUSED)
        self.assertNotEqual(self.rt.states(fresh=True).get("local_api"), ArmingState.ARMED)
        both = self.arm(self.rt, "local_api_actions", also=self.also())
        self.assertTrue(both["done"], both)
        states = self.rt.states(fresh=True)
        self.assertEqual((states["local_api"], states["local_api_actions"]), (ArmingState.ARMED, ArmingState.ARMED))

    def test_turning_the_first_off_turns_off_what_requires_it(self):
        self.assertTrue(self.arm(self.rt, "local_api_actions", also=self.also())["done"])
        self.rt.arming.disarm("local_api", actor="dashboard")
        states = self.rt.states(fresh=True)
        self.assertEqual(states.get("local_api", ArmingState.OFF), ArmingState.OFF)
        self.assertEqual(states.get("local_api_actions", ArmingState.OFF), ArmingState.OFF)

    def test_turning_the_second_off_leaves_the_first(self):
        self.assertTrue(self.arm(self.rt, "local_api_actions", also=self.also())["done"])
        self.rt.arming.disarm("local_api_actions", actor="dashboard")
        self.assertEqual(self.rt.states(fresh=True)["local_api"], ArmingState.ARMED)


class ShippedTests(unittest.TestCase):
    def test_each_says_the_standards_it_departs_from(self):
        self.assertEqual(registry.LOCAL_API.departs_from, ("C1", "C2", "B14", "F8", "F6", "D1", "C12"))
        self.assertEqual(registry.LOCAL_API_ACTIONS.departs_from, ("H3", "H8"))

    def test_the_mcp_tools_reach_neither_the_token_nor_a_command(self):
        from codex_auto_resume_advanced import surfaces
        names = {tool["name"] for tool in surfaces.TOOLS}
        for word in ("api", "token", "remote", "telegram"):
            self.assertEqual([name for name in names if word in name], [], word)


if __name__ == "__main__":
    unittest.main()
