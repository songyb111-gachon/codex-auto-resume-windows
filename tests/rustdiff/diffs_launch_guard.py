"""Review 6, S2: car-harness's engine session - "the model" a product Backend is written after - launches inside the
launch guard, as codex/transport.py does (`with launch_guard as permitted: Popen(... queue ...)`), never after it.

Not a difference between two sides (the reference's codexsim stand-in launches outside its guard, so a trace of both
would differ by construction): the Rust side alone, its stand-in asked at the moment of the launch whether car-store's
write lock is held on the engine's state - a second connection's `BEGIN IMMEDIATE` with no wait must be refused as
busy. Before the fix the harness entered the guard, let it go, and only then asked the stand-in to launch.
"""
from __future__ import annotations

from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest import mock

from rustdiff import core, diffs_engine, enginerun, reference

RECORD = diffs_engine.RECORD


def write_lock_held(path: Path) -> bool:
    connection = sqlite3.connect(str(path), timeout=0, isolation_level=None)
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("ROLLBACK")
        return False
    except sqlite3.OperationalError:
        return True
    finally:
        connection.close()


class LaunchGuardHeld(unittest.TestCase):
    def test_the_harness_launches_inside_the_launch_guard(self):
        seen = []
        state = {}

        class Probe(enginerun.Recorder):
            def send(self, thread_id, prompt, *, launch_guard=None, permitted=None, noted=False):
                seen.append((permitted, write_lock_held(state["path"])))
                return super().send(thread_id, prompt, launch_guard=launch_guard, permitted=permitted, noted=noted)

        s = diffs_engine.Scenario("s2_launch_inside_the_guard").enable()
        diffs_engine.ready_after_reset(s).tick()
        name, spec = s.done()
        codexsim = diffs_engine.load(Path(__file__).resolve().parents[1] / "codexsim.py", "rustdiff_codexsim_s2")
        with tempfile.TemporaryDirectory(prefix="rustdiff-s2-") as scratch:
            root = Path(scratch) / name
            state["path"] = root / "state" / "state.sqlite"
            profile = Path(scratch) / "profile"
            profile.mkdir()
            harness = subprocess.Popen([str(core.binary("car-harness")), "serve"], stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       env=reference.scratch_environment(profile), creationflags=core.NO_WINDOW)
            try:
                with mock.patch.object(enginerun, "Recorder", Probe):
                    enginerun.run(spec, codexsim, root, enginerun.RustSide, harness=harness, session=1)
            finally:
                harness.stdin.close()
                harness.wait(timeout=60)
        self.assertEqual(seen, [(True, True)], "the stand-in launched outside car-store's write lock")
        RECORD.append("launch guard: the harness's stand-in launched inside car-store's write lock (%d send)" % len(seen))


if __name__ == "__main__":
    unittest.main()
