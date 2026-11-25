"""v0.6.26 final, live acceptance S5: the usage meter reads while the app serves from another official engine.

On 2026-11-24 the owner's advanced watcher drove the official engine in Codex's bin folder while the ChatGPT app ran its
app server from its own package (signed by OpenAI), and nothing waited for recovery. Core asks the app which engine it
runs only through its own pairing, which it looks at only while a record waits; so it never looked, never discovered
again, and kept telling the plug the bin engine. The meter's own look (UsageMeter._running) found the app open and
unmatched on every look for 3 h 14 min, and threw away what that look had seen: the engine the app served from.

Now the meter's look keeps what it saw for the plug (codex/inuse.py saw), core's next tick reads it from the plug
(runtime/app.py _served_elsewhere) and alone decides: an official engine that was not named is discovered again, every
engine check on it, the plug is told it, and the meter's next look pairs and reads through it. A named engine is never
second-guessed, and the back-off of engine_moved holds.

The watcher, the backend, the pairing, discovery and the plug are real; the process list, the identities the pairing
confirms, Windows' signature answer, codex.exe's own answers and the meter's session are stubs (test_signed_engine).

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src;tests" python -m unittest test_advanced_meter_engine_elsewhere
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

for _entry in (Path(__file__).resolve().parents[2] / "tests", Path(__file__).resolve().parent):
    if str(_entry) not in sys.path:
        sys.path.insert(0, str(_entry))

from test_engine_moved import key  # noqa: E402
from test_signed_engine import SignedEngineCase  # noqa: E402
from codex_auto_resume import config  # noqa: E402
from codex_auto_resume.domain.plug import guard  # noqa: E402
from codex_auto_resume.runtime import app as runtime_app  # noqa: E402
from codex_auto_resume_advanced import plug as advanced_plug  # noqa: E402
from codex_auto_resume_advanced.codex import inuse, protocol  # noqa: E402
from codex_auto_resume_advanced.engine import usage  # noqa: E402

NOW = 1_700_000_000


def reply():
    """An account/rateLimits/read answer as Codex gives one: a five-hour and a weekly window."""
    return {"rateLimitsByLimitId": {"codex": {
        "primary": {"usedPercent": 40.0, "windowDurationMins": 300, "resetsAt": NOW + 3600},
        "secondary": {"usedPercent": 20.0, "windowDurationMins": 10080, "resetsAt": NOW + 86400}}}}


class Handle:
    def __init__(self):
        self.saved = []

    def on(self):
        return True

    def rows(self):
        return {}

    def save(self, found):
        self.saved.append(found)


class Scoped:
    def __init__(self):
        self.counted, self.meter = [], Handle()

    def now(self):
        return float(NOW)

    def options(self):
        return {}

    def armed(self, _name):
        return False

    def count(self, code):
        self.counted.append(code)


class MeterCase(SignedEngineCase):
    """The watcher holding bin's engine, its plug the advanced edition's and told that engine, and the meter of the same
    installation, whose session records the engine each one was opened with."""

    def setUp(self):
        super().setUp()
        paths = self.fixture.paths
        self.app._plug = guard(advanced_plug.create(paths))
        self.addCleanup(inuse.forget, paths)
        self.app.plug.codex(self.first.codex_exe, self.first.codex_home)
        self.meter = usage.UsageMeter(paths)
        self.scoped = Scoped()
        self.meter.bind(self.scoped)
        self.opened = []
        case = self

        class Session:
            def __init__(self, backend, capability=None, **_kwargs):
                case.opened.append(Path(backend.codex_exe))

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

            def call(self, _method, _params):
                return reply()
        stub = patch.object(protocol, "Session", Session)
        stub.start()
        self.addCleanup(stub.stop)

    def tick(self, at):
        """Core's turn of a tick that holds an engine (runtime/loop.py): the engine looked for again where it moved."""
        if self.moved(at):
            self.app.backend()
            return True
        return False

    def told(self):
        return inuse.told(self.fixture.paths)[0]


class LiveCaseTests(MeterCase):
    def test_the_meter_reads_through_the_engine_the_app_serves_from_with_nothing_waiting(self):
        """Fails with the fix reverted: core never moves, the plug keeps bin's engine, every look says unmatched."""
        self.serve(self.package)
        self.meter.look()
        self.assertEqual(self.scoped.counted, ["unmatched"])
        self.assertEqual({key(path) for path in self.app.plug.plug.served_elsewhere}, {key(self.package)})
        self.assertEqual(self.opened, [], "a session through an engine core has not taken up")
        asked = len(self.codex.builds)
        self.assertTrue(self.tick(0), "core did not look for its engine again")
        self.assertEqual(self.app.backend().codex_exe, self.package)
        self.assertIn(key(self.package), self.codex.builds[asked:], "the engine checks did not run on it")
        self.assertEqual(self.told(), self.package, "the plug was not told the engine taken up")
        self.assertEqual(self.app.plug.plug.served_elsewhere, frozenset(), "what was seen outlives the telling")
        self.meter.look()
        self.assertEqual(self.scoped.counted, ["unmatched", "read"])
        self.assertEqual(len(self.scoped.meter.saved), 1)
        self.assertEqual(self.opened, [self.package])
        self.assertFalse(self.tick(1), "a paired engine is looked for again")

    def test_a_package_engine_that_fails_its_checks_is_looked_for_less_and_less_often(self):
        """engine_moved's back-off holds for what the meter saw as for what core's pairing saw."""
        self.codex.failing.add(key(self.package))
        self.serve(self.package)
        self.meter.look()
        self.assertTrue(self.tick(0))
        self.assertEqual(self.told(), self.first.codex_exe, "the build that passes is kept")
        wait = runtime_app.ELSEWHERE_FIRST_WAIT
        for at in (5, 30, wait - 1):
            self.meter.look()
            self.assertFalse(self.tick(at), "looked for again on every tick")
        self.meter.look()
        self.codex.failing.clear()
        self.assertTrue(self.tick(wait + 1))
        self.assertEqual(self.told(), self.package)
        self.meter.look()
        self.assertEqual(self.opened, [self.package])
        self.assertEqual(self.scoped.counted, ["unmatched", "read"])

    def test_an_engine_that_is_not_signed_by_openai_is_never_taken_up(self):
        self.signed.clear()
        self.serve(self.package)
        self.meter.look()
        self.assertFalse(self.tick(0))
        self.assertEqual(self.told(), self.first.codex_exe)
        self.assertEqual(self.opened, [])

    def test_the_app_closed_or_serving_the_held_engine_moves_nothing(self):
        self.rows = []
        self.meter.look()
        self.assertFalse(self.tick(0))
        self.serve(self.first.codex_exe)
        self.meter.look()
        self.assertFalse(self.tick(1))
        self.assertEqual(self.opened, [self.first.codex_exe])


class NamedEngineTests(MeterCase):
    def test_a_named_engine_keeps_the_meter_unmatched_and_core_where_it_is(self):
        for named in ({config.ENV_CODEX_EXE: str(self.first.codex_exe)}, None):
            with self.subTest("the environment" if named else "--codex-exe or the setting"):
                if named:
                    stub = patch.dict(os.environ, named)
                else:
                    stub = patch.object(self.app, "_codex_exe_override", str(self.first.codex_exe))
                with stub:
                    self.serve(self.package)
                    for at in (0, 1, runtime_app.ELSEWHERE_LONGEST_WAIT + 1):
                        self.meter.look()
                        self.assertFalse(self.tick(at), "a named engine was second-guessed")
                    self.assertEqual(self.told(), self.first.codex_exe)
                    self.assertEqual(self.opened, [])
                    self.assertEqual(self.scoped.counted, ["unmatched"])


if __name__ == "__main__":
    unittest.main()
