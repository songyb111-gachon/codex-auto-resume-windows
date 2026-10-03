"""At the defaults, the standard edition asks of Codex exactly what v0.6.10 asked.

Every scenario that drives the engine (tests/neutral.py, MODULES) and is word for word the one
v0.6.10 was tested with runs twice, in worker processes of its own: once against the tagged
v0.6.10 package, taken out of git by tests/released.py, and once against this checkout. Each run
writes down every call an engine made of its Codex backend - `send`, `usage`, `loaded`,
`delete_queue`, `app_identity` - in order, with its arguments (tests/callrecord.py). The two lists
must be the same, scenario by scenario, and every scenario must pass both times.

The scenarios set only what v0.6.10 had to set, so everything v0.6.11 added is at its default -
which is the claim: at the defaults nothing new asks Codex anything, sends anything or reads usage
at another moment. One difference is expected and is the one the owner asked for: the marker a
continuation carries is the first 16 of its interruption id's 64 hex digits (domain/ids.py). So
v0.6.10's whole-id marker is written as its first 16 digits before the two are compared, and
this checkout's text must carry only the short one - every other character of every message, and
every other argument of every call, is compared as it is.

Where the tag is not in the checkout this is skipped, except on CI, which fetches tags
(tests/released.py). Temporary homes only, and no console window for any worker.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import tempfile
import threading
import unittest

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import neutral  # noqa: E402
import released  # noqa: E402

HERE = Path(_HERE)
ROOT = HERE.parent
TAG = released.V0610
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# The modules the scenarios run in, and the helpers they are written with: each must be the file
# v0.6.10 had, or the two runs would not be of one scenario.
HELPERS = ("codexsim", "frozen_registry", "srcscan")
# What came after v0.6.10 and so has no v0.6.10 run to be compared with.
AFTER = {"test_ladder_and_guards": "v0.6.11's Custom waits, time ceiling and guards, at their own settings",
         "test_engine_children": "v0.6.12's app gate where the app main runs two of the configured engine"}
MARKER = re.compile(r"\[codex-auto-resume:([0-9a-f]{64}|[0-9a-f]{16})\]")


def unchanged(name: str) -> bool:
    """Whether tests/<name>.py is, byte for byte, the file the tag has."""
    tagged = subprocess.run(["git", "-C", str(ROOT), "show", "%s:tests/%s.py" % (TAG, name)],
                            capture_output=True, creationflags=NO_WINDOW)
    if tagged.returncode != 0:
        return False
    return tagged.stdout.replace(b"\r\n", b"\n") == (HERE / (name + ".py")).read_bytes().replace(b"\r\n", b"\n")


def short(calls):
    """The calls, with every marker written as the first 16 of its digits."""
    return json.loads(MARKER.sub(lambda found: "[codex-auto-resume:%s]" % found.group(1)[:16], json.dumps(calls)))


def run_all(ids, source: Path, *, count=None, stall=neutral.STALL) -> tuple:
    """Every scenario in `ids` under the package in `source`: (the package's file, id -> result)."""
    pending = queue.Queue()
    for test_id in sorted(ids, key=lambda name: name.split(".", 1)[0] not in neutral.FIRST):
        pending.put(test_id)
    results, packages, lock = {}, set(), threading.Lock()

    def work(home):
        environment = dict(os.environ, PYTHONPATH=os.pathsep.join([str(source), str(HERE)]),
                           PYTHONIOENCODING="utf-8",
                           **{name: home for name in ("USERPROFILE", "HOME", "LOCALAPPDATA", "APPDATA",
                                                       "CODEX_HOME", "CODEX_AUTO_RESUME_HOME")})
        environment.pop(neutral.LEG, None)
        with open(Path(home) / "worker.log", "w", encoding="utf-8") as log, subprocess.Popen(
                [sys.executable, "-c", "import callrecord; callrecord.serve()"], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=log, text=True, encoding="utf-8", cwd=home, env=environment,
                creationflags=NO_WINDOW) as process:
            first = process.stdout.readline()
            with lock:
                packages.add(json.loads(first)["package"] if first else None)
            while first:
                try:
                    test_id = pending.get_nowait()
                except queue.Empty:
                    break
                line, stalled = neutral.answer(process, test_id, stall)
                if line and not stalled:
                    result = json.loads(line)
                else:
                    result = {"id": test_id, "error": ("no answer in %d seconds; the worker was stopped" % stall)
                              if stalled else "the worker ended"}
                with lock:
                    results[test_id] = result
                if stalled or not line:
                    break
            if process.poll() is None:
                process.stdin.close()

    homes = [tempfile.TemporaryDirectory(prefix="released-calls-") for _ in range(count or neutral.workers())]
    try:
        threads = [threading.Thread(target=work, args=(home.name,), daemon=True) for home in homes]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    finally:
        for home in homes:
            home.cleanup()
    return packages, results


class ReleasedCallsTests(unittest.TestCase):
    def test_the_scenarios_are_the_ones_v0_6_10_was_tested_with(self):
        released.package(TAG)
        for name in HELPERS:
            self.assertTrue(unchanged(name), "tests/%s.py is not the file %s has" % (name, TAG))
        changed = sorted(name for name in neutral.MODULES if not unchanged(name))
        self.assertEqual(changed, sorted(AFTER), "a scenario module changed since %s" % TAG)

    def test_at_the_defaults_every_scenario_asks_codex_what_v0_6_10_asked(self):
        source = released.package(TAG)
        ids = neutral.scenarios(tuple(name for name in neutral.MODULES if name not in AFTER))
        self.assertGreater(len(ids), 250, "the listing itself looks wrong")
        then_packages, then = run_all(ids, source)
        now_packages, now = run_all(ids, ROOT / "src")
        self.assertEqual([Path(path).resolve().parent.parent for path in then_packages], [source.resolve()],
                         "the v0.6.10 run imported the tag's package and nothing else")
        self.assertEqual([Path(path).resolve().parent.parent for path in now_packages], [(ROOT / "src").resolve()])
        for results in (then, now):
            self.assertEqual(sorted(set(ids) - set(results)), [], "scenarios that never ran")
            self.assertEqual({key: result["error"] for key, result in results.items() if "error" in result}, {})
        self.assertEqual({key: then[key]["problems"] for key in ids if not then[key]["ok"]}, {},
                         "a scenario fails against v0.6.10's own package: the comparison is of nothing")
        self.assertEqual({key: now[key]["problems"] for key in ids if not now[key]["ok"]}, {})
        differ = {}
        for key in ids:
            before, after = short(then[key]["calls"]), now[key]["calls"]
            if before != after:
                index = next((i for i, (a, b) in enumerate(zip(before, after)) if a != b),
                             min(len(before), len(after)))
                differ[key] = "call %d: %s then, %s now" % (index, (before[index:index + 1] or [["nothing"]])[0],
                                                            (after[index:index + 1] or [["nothing"]])[0])
        self.assertEqual(differ, {}, "a scenario asks Codex something v0.6.10 did not, or not as it did")
        # The one difference, said the other way round: now only the short marker goes out.
        sent = [call[1][1] for key in ids for call in now[key]["calls"] if call[0] == "send"]
        self.assertGreater(len(sent), 100, "the scenarios send")
        self.assertTrue(all(len(found) == 16 for text in sent for found in MARKER.findall(text)))
        before_sent = [call[1][1] for key in ids for call in then[key]["calls"] if call[0] == "send"]
        self.assertTrue(all(len(found) == 64 for text in before_sent for found in MARKER.findall(text)))
        asked = {call[0] for key in ids for call in now[key]["calls"]}
        self.assertLessEqual({"send", "usage", "loaded", "delete_queue"}, asked,
                             "every kind of call is compared somewhere")
        driven = [key for key in ids if now[key]["engines"]]
        self.assertGreater(len(driven), 200)

    def test_the_comparison_sees_a_call_that_differs(self):
        call = ["send", ["0a1b2c3d-0001-7000-8000-000000000001",
                         "Continue. [codex-auto-resume:%s]" % ("ab" * 32)], ["launch_guard"]]
        self.assertEqual(short([call])[0][1][1], "Continue. [codex-auto-resume:%s]" % ("ab" * 8))
        self.assertNotEqual(short([call]), [["send", [call[1][0], "Continue! [codex-auto-resume:%s]"
                                                      % ("ab" * 8)], ["launch_guard"]]])


if __name__ == "__main__":
    unittest.main()
