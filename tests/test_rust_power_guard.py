"""No test can sleep or shut down this PC through the Rust core (review 4, S3).

The reference refuses a power action whenever "unittest" is in sys.modules (win/powerdown.py `act`). A Rust process
the suite starts has no sys.modules: car-platform's `powerdown::act` refuses where CAR_NO_POWER_ACTION is set
(rust/crates/car-platform/tests/power_guard.rs holds that side without acting). This holds the other side: every way
the suite runs sets the variable before it can start a child, so the core, the harness, a probe or the shim's binary
inherit it - tests/sitecustomize.py (every interpreter with tests/ on its path), scripts/test_parts.py (its lanes put
only src there) and tests/rustdiff/core.py (every diff). Nothing here acts on power: children only print what they see.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
GUARD = "CAR_NO_POWER_ACTION"
SHOW = "import os, sys; sys.stdout.write(repr(os.environ.get(%r)))" % GUARD


def without_guard(**extra) -> dict:
    environment = {name: value for name, value in os.environ.items() if name.upper() != GUARD}
    environment.update(extra)
    return environment


def seen(code: str, environment: dict) -> str:
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, encoding="utf-8", errors="replace", env=environment,
                          cwd=str(ROOT), creationflags=NO_WINDOW, timeout=120)
    if done.returncode != 0:
        raise AssertionError(done.stderr)
    return done.stdout.strip().splitlines()[-1]


class PowerGuardTests(unittest.TestCase):
    def test_this_interpreter_has_it(self):
        # This module runs with tests/ on the path (rule 5's PYTHONPATH="src;tests") or under test_parts' worker.
        self.assertEqual(os.environ.get(GUARD), "1")

    def test_an_interpreter_with_tests_on_its_path_sets_it_for_its_children(self):
        code = SHOW + "; import subprocess; subprocess.run([sys.executable, '-c', %r])" % SHOW
        environment = without_guard(PYTHONPATH=os.pathsep.join([str(ROOT / "src"), str(ROOT / "tests")]))
        done = subprocess.run([sys.executable, "-c", code], capture_output=True, encoding="utf-8", errors="replace", env=environment,
                              cwd=str(ROOT), creationflags=NO_WINDOW, timeout=120)
        self.assertEqual(done.stdout, "'1''1'", done.stderr)

    def test_the_parts_runner_sets_it_for_its_workers(self):
        code = ("import runpy, sys; sys.argv = ['test_parts']; runpy.run_path(%r, run_name='not_main'); " % str(
            ROOT / "scripts" / "test_parts.py")) + SHOW
        self.assertEqual(seen(code, without_guard(PYTHONPATH=str(ROOT / "src"))), "'1'")

    def test_every_diff_and_the_reference_environment_have_it(self):
        code = ("import sys; sys.path.insert(0, %r); from rustdiff import core, reference; from pathlib import Path; "
                "sys.stdout.write(repr(reference.scratch_environment(Path(%r)).get(%r)))"
                % (str(ROOT / "tests"), tempfile.gettempdir(), GUARD))
        self.assertEqual(seen(code, without_guard(PYTHONPATH=str(ROOT / "src"))), "'1'")


if __name__ == "__main__":
    unittest.main()
