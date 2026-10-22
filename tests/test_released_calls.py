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

A scenario the owner amended (AMENDED) is the one exception to "word for word": its module may differ
from the tag in that test's body and nowhere else. v0.6.10's run takes it from the tag's own module, so
each package runs the scenario it was written for, and the calls v0.6.10's made must begin the calls
this checkout's makes - an amended scenario may ask for more ticks, never for other calls before them.

Where the tag is not in the checkout this is skipped, except on CI, which fetches tags
(tests/released.py). Temporary homes only, and no console window for any worker.
"""
from __future__ import annotations

import ast
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
         "test_engine_children": "v0.6.12's app gate where the app main runs two of the configured engine",
         "test_skip_reasons": "v0.6.16-beta.3's log lines for a failed turn passed over, which v0.6.10 never wrote",
         "test_continuation_split": "v0.6.16-beta.3's conversations Codex records under another id (issue #30)",
         "test_checkup": "v0.6.16-beta.3's Diagnostics check, which v0.6.10 did not have",
         "test_once_words_engine": "v0.6.16-beta.3's words for this time, which v0.6.10 did not have",
         "test_rescan": "v0.6.16's Rescan and reconcile on the Pending page (issue #39), which v0.6.10 did not have"}
# Scenarios the owner amended, each with what it now expects: never a module, never a skip.
AMENDED_ON = "2026-10-21"
AMENDED_BECAUSE = ("owner (standard E6 amended): a recovery turn that made progress and was then cut off - a later turn "
                   "started, or the PC restarted - is recovered, as a failed turn with progress is")
AMENDED = {
    "test_outcomes.T13OutcomeRulesTests.test_T13_a_later_terminal_turn_proves_an_in_progress_row_stale":
        "turn_completed, then recovered (progress_then_turn_cut_off)",
    "test_outcomes.T17StuckObservingTests.test_T17_a_newer_failure_closes_a_stale_observing_record_and_is_recovered":
        "turn_completed, then recovered (progress_then_turn_cut_off); the newer failure is recovered as before",
    "test_engine.OutcomeTests.test_T13_a_later_finished_turn_proves_the_row_is_stale":
        "turn_completed, then recovered (progress_then_turn_cut_off)",
    "test_engine.OutcomeTests.test_T17_a_stuck_observed_record_does_not_block_a_newer_failure":
        "turn_completed, then recovered (progress_then_turn_cut_off); the newer failure is sent as before",
    # 2026-10-22, the owner (rank 1 of plans/notif-check.md): a recovery turn that made progress before a person's
    # message entered it is recovered (progress_then_user_joined) and its next failure recovered; these scenarios keep
    # testing the hand-over, with the person joining before any progress.
    "test_outcomes.T16UserJoinedTests.test_T16_an_extra_user_message_hands_the_turn_over_at_once":
        "the person joins before any progress: handed over as before",
    "test_outcomes.T16UserJoinedTests.test_T16_a_steered_message_from_codexsim_is_seen_the_same_way":
        "the person joins before any progress: handed over as before",
    "test_outcomes.T16UserJoinedTests.test_T16_when_the_handed_over_turn_fails_the_child_is_superseded_and_never_claimed":
        "the person joins before any progress: the child is superseded as before",
    "test_outcomes.T48NotificationTests.test_T48_children_registered_cancelled_or_superseded_are_announced_as_stopped_only":
        "the person joins before any progress: the superseded child is announced as before",
    "test_engine.OutcomeTests.test_T16_a_person_joining_the_turn_hands_it_over_and_blocks_its_child":
        "the person joins before any progress: handed over and its child blocked as before",
}
MARKER = re.compile(r"\[codex-auto-resume:([0-9a-f]{64}|[0-9a-f]{16})\]")


def unchanged(name: str) -> bool:
    """Whether tests/<name>.py is, byte for byte, the file the tag has."""
    tagged = subprocess.run(["git", "-C", str(ROOT), "show", "%s:tests/%s.py" % (TAG, name)],
                            capture_output=True, creationflags=NO_WINDOW)
    if tagged.returncode != 0:
        return False
    return tagged.stdout.replace(b"\r\n", b"\n") == (HERE / (name + ".py")).read_bytes().replace(b"\r\n", b"\n")


def tagged(name: str) -> str | None:
    """tests/<name>.py as the tag has it, or None."""
    found = subprocess.run(["git", "-C", str(ROOT), "show", "%s:tests/%s.py" % (TAG, name)],
                           capture_output=True, creationflags=NO_WINDOW)
    return found.stdout.decode("utf-8").replace("\r\n", "\n") if found.returncode == 0 else None


def without_amended(name: str, text: str):
    """`text`, module `name`, with the lines of each amended test in it taken out - or None when one is missing."""
    lines = text.split("\n")
    wanted = {tuple(test_id.split(".")[1:]) for test_id in AMENDED if test_id.split(".")[0] == name}
    spans = []
    for node in ast.parse(text).body:
        for member in (node.body if isinstance(node, ast.ClassDef) else []):
            if isinstance(member, ast.FunctionDef) and (node.name, member.name) in wanted:
                wanted.discard((node.name, member.name))
                first = min([member.lineno] + [item.lineno for item in member.decorator_list])
                spans.append((first - 1, member.end_lineno))
    if wanted:
        return None
    for start, end in sorted(spans, reverse=True):
        del lines[start:end]
    return "\n".join(lines)


def amended_only(name: str) -> bool:
    """Whether tests/<name>.py differs from the tag's in the bodies of amended tests alone."""
    then = tagged(name)
    if then is None or not any(test_id.split(".")[0] == name for test_id in AMENDED):
        return False
    now = (HERE / (name + ".py")).read_bytes().decode("utf-8").replace("\r\n", "\n")
    kept = without_amended(name, now)
    return now != then and kept is not None and kept == without_amended(name, then)


def short(calls):
    """The calls, with every marker written as the first 16 of its digits."""
    return json.loads(MARKER.sub(lambda found: "[codex-auto-resume:%s]" % found.group(1)[:16], json.dumps(calls)))


def run_all(ids, source: Path, *, count=None, stall=neutral.STALL, modules=None) -> tuple:
    """Every scenario in `ids` under the package in `source`: (the package's file, id -> result). `modules`, a
    folder of test modules found before this one's (the tag's own, for an amended scenario)."""
    pending = queue.Queue()
    for test_id in sorted(ids, key=lambda name: name.split(".", 1)[0] not in neutral.FIRST):
        pending.put(test_id)
    results, packages, lock = {}, set(), threading.Lock()

    def work(home):
        environment = dict(os.environ, PYTHONPATH=os.pathsep.join([str(source)] + ([str(modules)] if modules else []) + [str(HERE)]),
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
        changed = sorted(name for name in neutral.MODULES if not unchanged(name) and not amended_only(name))
        self.assertEqual(changed, sorted(AFTER), "a scenario module changed since %s" % TAG)
        # Each amendment is of a scenario that is there, and that really differs from the tag's.
        for name in {test_id.split(".")[0] for test_id in AMENDED}:
            self.assertTrue(amended_only(name), "%s's amendment is stale or reaches past its tests" % name)

    def test_an_amendment_reaches_its_own_test_and_no_other(self):
        name = "test_engine"
        text = tagged(name)
        self.assertIsNotNone(text)
        self.assertNotEqual(without_amended(name, text + "\n# one more line"),without_amended(name, text))
        self.assertIsNone(without_amended(name, text.replace("def test_T13_a_later_finished_turn_proves_the_row_is_stale",
                                                             "def test_renamed")))
        self.assertTrue(AMENDED_ON and AMENDED_BECAUSE and all(AMENDED.values()))

    def test_at_the_defaults_every_scenario_asks_codex_what_v0_6_10_asked(self):
        source = released.package(TAG)
        ids = neutral.scenarios(tuple(name for name in neutral.MODULES if name not in AFTER))
        self.assertGreater(len(ids), 250, "the listing itself looks wrong")
        plain = [key for key in ids if key not in AMENDED]
        then_packages, then = run_all(plain, source)
        amended = [key for key in ids if key in AMENDED]
        self.assertEqual(sorted(amended), sorted(AMENDED), "an amended scenario is not one of the scenarios")
        with tempfile.TemporaryDirectory(prefix="released-tagged-") as folder:
            for name in {key.split(".")[0] for key in amended}:
                (Path(folder) / (name + ".py")).write_text(tagged(name), encoding="utf-8")
            packages, results = run_all(amended, source, modules=folder)
        then_packages |= packages
        then.update(results)
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
            if key in AMENDED:
                after = after[:len(before)]
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
