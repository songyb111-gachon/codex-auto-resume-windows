"""#58's follow-up: a compatibility report that passes while no server of the Codex app's can be matched.

The reporter's report read all PASS while every recovery waited. The check app_server_matched says so, where it knows: PASS only
on a look that paired a server, FAIL on a look that found the app open and none, and otherwise UNAVAILABLE, shown as
"not checked" - the app not running, or nothing having looked. It is read off the look the watcher already took: it starts no
process and a per-call reader asks the app nothing (commit 5286990d3, tests/test_compat_io.py). No capability stands on
it, so no decision moves; and no report sends it.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch

_HERE = str(Path(__file__).resolve().parent)
for entry in (str(Path(_HERE).parent / "src"), _HERE):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import released  # noqa: E402
from codex_auto_resume import compat, compatio, config  # noqa: E402
from codex_auto_resume.codex import pairing, transport  # noqa: E402
from codex_auto_resume.compat import probes, views  # noqa: E402
from codex_auto_resume.ownreport import document, evidence  # noqa: E402

CHECK = "app_server_matched"
NOW = 1_800_000_000.0


def looked(word, *, ago=0.0):
    """A stand-in for a backend, with what its last look found."""
    return types.SimpleNamespace(app_look=word, app_looked_at=None if word is None else time.monotonic() - ago)


class Driven:
    """A backend the watcher could be driving: its engine checks pass, and its look is what a test says."""
    engine_version = "codex-cli 0.166.0"
    engine_verified = False

    def __init__(self, exe, look):
        self.codex_exe = exe
        self.app_look, self.app_looked_at = look, time.monotonic()

    def engine_checks(self):
        status = self.codex_exe.stat()
        return {"official_location": compat.PASS, "version_runs": compat.PASS, "queue_flags": compat.PASS,
                "version": self.engine_version, "signature": (status.st_size, status.st_mtime_ns)}


class Source:
    """A source whose home does not exist: the schema checks cannot run, as with no Codex home."""
    home = "does-not-exist"


class CheckTests(unittest.TestCase):
    def test_its_three_answers(self):
        self.assertEqual(probes.server_check(looked("matched")), compat.PASS)
        self.assertEqual(probes.server_check(looked("unmatched")), compat.FAIL)
        for word in ("closed", None, "anything else"):
            self.assertEqual(probes.server_check(looked(word)), compat.UNAVAILABLE, word)

    def test_a_backend_that_never_looked_is_not_checked(self):
        self.assertEqual(probes.server_check(object()), compat.UNAVAILABLE)
        self.assertEqual(probes.server_check(transport.Backend(Path("home"), Path("codex.exe"))), compat.UNAVAILABLE)

    def test_a_look_older_than_a_report_may_be_is_no_evidence(self):
        """Fails with the age left out: a pass from yesterday would stand for today's app."""
        self.assertEqual(probes.server_check(looked("matched", ago=compat.REPORT_MAX_AGE - 60)), compat.PASS)
        self.assertEqual(probes.server_check(looked("matched", ago=compat.REPORT_MAX_AGE + 60)), compat.UNAVAILABLE)
        self.assertEqual(probes.server_check(looked("unmatched", ago=compat.REPORT_MAX_AGE + 60)), compat.UNAVAILABLE)

    def test_it_is_a_check_of_the_registry_and_no_capability_stands_on_it(self):
        self.assertIn(CHECK, compat.CHECKS)
        for name, (needed, _tier) in compat.CAPABILITIES.items():
            self.assertNotIn(CHECK, needed, name)
        passing = {name: compat.PASS for name in compat.CHECKS}
        self.assertEqual(compat.evaluate(passing, version=None, sources=[]),
                         compat.evaluate(dict(passing, **{CHECK: compat.FAIL}), version=None, sources=[]),
                         "a failed look must move no capability, and so no gate")
        self.assertEqual(compat.accepted_word("codex-cli 0.166.0", []), "structurally_compatible")

    def test_a_report_from_before_it_reads_as_not_checked(self):
        report = compat.build_report(checked_at=NOW, product="unknown", engine={"found": False}, data=_data(),
                                     checks={}, capabilities={})
        old = {key: value for key, value in report.items()}
        old["checks"] = {name: result for name, result in report["checks"].items() if name != CHECK}
        self.assertEqual(compat.validate_report(old)["checks"][CHECK], compat.UNAVAILABLE)

    def test_a_result_of_no_vocabulary_is_refused_as_every_check_s(self):
        report = compat.build_report(checked_at=NOW, product="unknown", engine={"found": False}, data=_data(),
                                     checks={}, capabilities={})
        self.assertIsNone(compat.validate_report(dict(report, checks=dict(report["checks"], **{CHECK: "YES"}))))


def _data():
    return {"bundled": "ok", "bundled_sequence": 1, "cache": "absent", "cache_sequence": None, "cache_origin": None,
            "fetched_at": None, "source": "bundled", "expired": False}


class WatcherTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.paths = config.Paths(root / "home")
        self.paths.ensure()
        self.exe = root / "codex.exe"
        self.exe.write_bytes(b"MZ")
        self.clock = [time.time()]
        self.logs = []
        self.evaluator = compatio.Evaluator(self.paths, root / "codex-home", source=Source(), clock=lambda: self.clock[0],
                                            product="0.6.21", log=lambda line, *_: self.logs.append(line))
        self.backend = Driven(self.exe, "unmatched")
        for stub in (patch.object(probes, "_served_engines", lambda: iter(())),
                     patch.object(views, "_candidate_paths", lambda explicit=None: [self.exe])):
            stub.start()
            self.addCleanup(stub.stop)

    def written(self):
        return json.loads(Path(self.paths.compat_report_file).read_text(encoding="utf-8"))

    def test_the_report_says_no_server_was_matched_where_the_engine_s_own_checks_pass(self):
        """The reverse-applied product writes UNAVAILABLE here: nothing beside the passes said what #58's reporter saw."""
        self.evaluator.tick(self.backend)
        checks = self.written()["checks"]
        self.assertEqual(checks[CHECK], compat.FAIL)
        for name in ("official_location", "version_runs", "queue_flags", "single_candidate"):
            self.assertEqual(checks[name], compat.PASS, name)
        self.assertEqual(self.evaluator.acting, "structurally_compatible", "the gate's word stands on what it stood on")
        self.assertTrue(any("no Codex server of its could be matched" in line for line in self.logs))

    def test_a_look_that_changes_writes_the_report_at_the_next_tick_not_at_the_next_interval(self):
        self.evaluator.tick(self.backend)
        self.backend.app_look = "matched"
        self.clock[0] += 1
        self.evaluator.tick(self.backend)
        self.assertEqual(self.written()["checks"][CHECK], compat.PASS)
        self.backend.app_look = "closed"
        self.clock[0] += 1
        self.evaluator.tick(self.backend)
        self.assertEqual(self.written()["checks"][CHECK], compat.UNAVAILABLE)

    def test_it_reaches_every_reader_and_not_the_summary_a_model_reads(self):
        self.evaluator.tick(self.backend)
        view = compatio.read_view(self.paths, now=self.clock[0])
        self.assertEqual(view["status"], "ok")
        self.assertEqual(view["checks"][CHECK], compat.FAIL)
        self.assertFalse({CHECK, "checks"} & set(compat.mcp_view(view)), "a model is handed nothing new for it")

    def test_nothing_of_this_pc_is_in_it(self):
        self.evaluator.tick(self.backend)
        self.assertIn(self.written()["checks"][CHECK], compat.RESULTS)
        self.assertNotIn(str(self.exe), json.dumps(compatio.read_view(self.paths, now=self.clock[0])["checks"]))

    def test_a_live_check_keeps_what_the_watcher_found_and_starts_no_process(self):
        """A person's Refresh is a per-call reader. It lists no process, and must not say "not checked" over a server the
        watcher could not match. Fails with `_watchers_server_check` gone, or with the reader taking a look of its own."""
        self.evaluator.tick(self.backend)
        with patch.object(pairing, "inventory", side_effect=AssertionError("a process was started")), \
             patch.object(transport, "inventory", side_effect=AssertionError("a process was started")):
            view = compatio.live_view(self.paths, self.paths.state_dir, discovery={}, source=Source(),
                                      now=self.clock[0])
        self.assertEqual(view["checks"][CHECK], compat.FAIL)

    def test_a_live_check_with_no_watcher_is_not_checked(self):
        view = compatio.live_view(self.paths, self.paths.state_dir, discovery={}, source=Source(), now=self.clock[0])
        self.assertEqual(view["checks"][CHECK], compat.UNAVAILABLE)

    def test_a_report_too_old_to_rely_on_vouches_for_no_live_check(self):
        self.evaluator.tick(self.backend)
        view = compatio.live_view(self.paths, self.paths.state_dir, discovery={}, source=Source(),
                                  now=self.clock[0] + compat.REPORT_MAX_AGE + 60)
        self.assertEqual(view["checks"][CHECK], compat.UNAVAILABLE)


_OLDER_READS = r"""
import json, sys
from codex_auto_resume import compat
report = json.loads(sys.argv[1])
clean = compat.validate_report(report)
print(json.dumps({"read": clean is not None, "check": "app_server_matched" in (clean or {}).get("checks", {})}))
"""


class OlderReaderTests(unittest.TestCase):
    def test_an_older_version_reads_this_report_and_drops_the_key_it_does_not_know(self):
        report = compat.build_report(checked_at=time.time(), product="0.6.21", engine={"found": False}, data=_data(),
                                     checks={CHECK: compat.FAIL}, capabilities={})
        self.assertEqual(released.run("v0.6.21", _OLDER_READS, json.dumps(report)), {"read": True, "check": False})


class CommunityReportTests(unittest.TestCase):
    """It stays local: a report is `local_checks`, `records` and `capabilities` of closed keys, and no check is one."""

    def test_no_report_key_names_it(self):
        self.assertNotIn(CHECK, evidence.REPORTABLE)
        self.assertFalse({CHECK, "app_server"} & set(document.BODY_KEYS))


if __name__ == "__main__":
    unittest.main()
