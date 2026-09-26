"""A report someone else sends, read as the untrusted document it is (build/community_report.py).

The same reader judges a report as its pull request arrives (build/community_check.py) and holds
the reports already filed (tests/test_reported_data.py), so what it refuses is tested here once:
one case for every rule, each refused with fixed text that never repeats a value from the file.
What it only recomputes - the levels and the verdict a sender claims - is tested as a property:
recomputing never raises a level and changes nothing the second time.

The counting rule is a truth table in tests/fixtures/reported_cases.json: worked, failed, neither
(which includes nothing delivered) and both. graded() is the one function that counts; the filer
(build/community_file.py) and the maintainer's tool, which imports this file from main, both use it.
"""
from __future__ import annotations

import calendar
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "build"))

import community_report as reader  # noqa: E402
from codex_auto_resume import compat  # noqa: E402
from codex_auto_resume.compat import reported as product_reported  # noqa: E402
from codex_auto_resume.domain import vocabulary as words  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
SAMPLE = FIXTURES / "community" / "codex-cli-0.155.0-alpha.9.2.json"
CASES = json.loads((FIXTURES / "reported_cases.json").read_text(encoding="utf-8"))["cases"]
NOW = calendar.timegm((2026, 9, 25, 0, 0, 0))
RELEASES = {"v0.6.0": calendar.timegm((2026, 9, 12, 0, 0, 0)), "v0.6.9": calendar.timegm((2026, 9, 22, 20, 27, 0)),
            "v0.6.10-alpha": calendar.timegm((2026, 9, 24, 20, 55, 0))}
HOSTILE = "::error::pwned%0A\r\n<script>"


def sample() -> dict:
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


def inspect(report, *, raw=None, author="ExampleUser", releases=RELEASES):
    data = raw if raw is not None else reader.encode(report)
    return reader.inspect(data, author=author, now=NOW, releases=releases)


def refusals(change, **options):
    report = sample()
    change(report)
    return inspect(report, **options)[1]


def with_records(records) -> dict:
    """The sample, carrying exactly these records and nothing that counts them."""
    report = sample()
    start = calendar.timegm((2026, 9, 21, 0, 0, 0))
    report["records"] = []
    for number, (delivered, state) in enumerate(records):
        detected = start + number * 3600
        report["records"].append({
            "detected_at": reader.iso(detected),
            "delivered_at": reader.iso(detected + 60) if delivered else None,
            "outcome_at": reader.iso(detected + 120) if delivered else None,
            "category": "usage_limit", "state": state, "reason": None, "turn_status": None,
            "gates_passed": 13, "progress_items": None})
    for entry in report["capabilities"].values():
        entry.update(confirmed=0, missed=0, last_confirmed=None, level=None)
    report["verdict"] = "NONE"
    return report


class SampleTests(unittest.TestCase):
    def test_what_the_reporter_writes_is_read_as_it_is(self):
        report, refused, recomputed = inspect(sample())
        self.assertEqual(refused, [])
        self.assertEqual(recomputed, [])
        self.assertEqual(reader.recompute(report), report)

    def test_the_filed_copy_is_read_too_and_carries_only_our_sentences(self):
        kept = reader.filed_copy(sample())
        self.assertEqual(inspect(kept)[1], [])
        self.assertEqual(kept["note"], reader.OURS["note"])
        self.assertEqual(kept["attribution"]["rule"], reader.OURS["rule"])
        self.assertEqual(kept["recorded_by"], reader.OURS["recorded_by"] % ("codex-compat-reporter", "1.1.0"))
        self.assertEqual(reader.filed_copy(kept), kept)

    def test_the_words_are_the_products_own_and_other(self):
        self.assertEqual(reader.STATES, frozenset(words.RecordState) | {"other"})
        self.assertEqual(reader.REASONS, frozenset(words.ReasonCode) | {"other"})
        self.assertEqual(reader.CATEGORIES, frozenset(words.FailureCategory) | {"other"})
        self.assertEqual(reader.TURN_STATUSES, frozenset(words.TurnStatus))
        self.assertLessEqual(set(reader.REPORTABLE), set(compat.CAPABILITIES))
        self.assertEqual(len(reader.REPORTABLE), 10)
        self.assertLessEqual(set(reader.GATE), set(reader.REPORTABLE))
        self.assertLessEqual(reader.WORKED | reader.FAILED, reader.STATES)


class CountingTests(unittest.TestCase):
    """docs/ROADMAP.md's rule, as the table every tool runs."""

    def test_the_truth_table(self):
        for case in CASES:
            with self.subTest(case["name"]):
                report = with_records([(record["delivered"], record["state"]) for record in case["records"]])
                self.assertEqual(inspect(report)[1], [], "the table's reports must be readable ones")
                self.assertEqual(reader.graded(report), {word: case[word] for word in ("worked", "failed",
                                                                                       "neither", "both")})

    def test_every_report_has_exactly_one_place(self):
        """worked-only, failed-only, both or neither: so worked + failed - both + neither = reports."""
        said = [reader.graded(with_records([(r["delivered"], r["state"]) for r in case["records"]]))
                for case in CASES]
        counts = reader.tally(said)
        self.assertEqual(counts["reports"], len(CASES))
        self.assertEqual(counts["worked"] + counts["failed"] - counts["both"] + counts["neither"], counts["reports"])
        for one in said:
            self.assertEqual(sum([one["worked"] and not one["failed"], one["failed"] and not one["worked"],
                                  one["both"], one["neither"]]), 1)

    def test_the_table_covers_every_rule(self):
        names = {case["name"] for case in CASES}
        for needed in ("no records at all", "nothing delivered", "delivered and recovered",
                       "delivered and recovery_turn_failed", "delivered and failed", "delivered and terminal_failure",
                       "recovered and failed in one report", "delivered, completed_no_progress only",
                       "an undelivered record whose state is recovered"):
            self.assertIn(needed, names)

    def test_levels_and_verdict_never_enter_the_counts(self):
        plain = with_records([(True, "recovered")])
        claimed = copy.deepcopy(plain)
        claimed["verdict"] = "PASS"
        for entry in claimed["capabilities"].values():
            entry["level"] = "VERIFIED"
        self.assertEqual(reader.graded(claimed), reader.graded(plain))


class RefusalTests(unittest.TestCase):
    """One case for each rule the reader refuses a file for."""

    def assertRefused(self, found, *fragments):
        self.assertTrue(found, "expected a refusal")
        for fragment in fragments:
            self.assertTrue(any(fragment in line for line in found), (fragment, found))

    def test_the_bytes(self):
        raw = reader.encode(sample())
        self.assertRefused(inspect(None, raw=b"\xef\xbb\xbf" + raw)[1], "byte-order mark")
        self.assertRefused(inspect(None, raw=raw.replace(b"ExampleUser", b"Exampl\xffUser"))[1], "not UTF-8")
        self.assertRefused(inspect(None, raw=raw[:-1] + b" " * (reader.MAX_BYTES - len(raw) + 2))[1], "larger than 1 MB")
        self.assertRefused(inspect(None, raw=raw.replace(b'"format"', b'"format": "x", "format"', 1))[1], "duplicate_key")
        self.assertRefused(inspect(None, raw=raw.replace(b'"gates_passed": 13', b'"gates_passed": NaN', 1))[1],
                           "not_finite")
        self.assertRefused(inspect(None, raw=b"[" * 100000 + b"]" * 100000)[1], "not JSON")
        self.assertRefused(inspect(None, raw=b"[]")[1], "not one JSON object")
        self.assertRefused(inspect(None, raw=b"{")[1], "not_json")

    def test_the_keys(self):
        self.assertRefused(refusals(lambda r: r.update(extra=1)), "keys: 1 the format does not have")
        self.assertRefused(refusals(lambda r: r.pop("note")), "keys: missing note")
        self.assertRefused(refusals(lambda r: r["reporter"].update(extra=1)), "reporter: its keys")
        self.assertRefused(refusals(lambda r: r["records"][0].pop("state")), "records[1]: its keys")
        self.assertRefused(refusals(lambda r: r["capabilities"]["usage_probe"].update(x=1)),
                           "capabilities.usage_probe: its keys")
        self.assertRefused(refusals(lambda r: r["local_checks"].pop("covers")), "local_checks: its keys")
        self.assertRefused(refusals(lambda r: r.update(format="codex-auto-resume-compat-evidence/2")), "format is not")

    def test_only_the_ten_capabilities(self):
        """A report names the ten a record can exercise and no other (codex-compat-reporter 1.0.0 once
        wrote queue_withdraw and transient_classification)."""
        def extra(report):
            report["capabilities"]["queue_withdraw"] = dict(report["capabilities"]["usage_probe"])
        self.assertRefused(refusals(extra), "not the ten capabilities")
        self.assertRefused(refusals(lambda r: r["capabilities"].pop("usage_probe")), "not the ten capabilities")
        self.assertRefused(refusals(lambda r: r["local_checks"]["covers"].append("transient_classification")),
                           "local_checks.covers")
        self.assertRefused(refusals(lambda r: r["local_checks"]["covers"].append("engine_present")), "or twice")

    def test_the_words(self):
        self.assertRefused(refusals(lambda r: r["records"][0].update(state="exploded")), "records[1].state")
        self.assertRefused(refusals(lambda r: r["records"][0].update(reason=7)), "records[1].reason")
        self.assertRefused(refusals(lambda r: r["records"][0].update(category="usage limit")), "records[1].category")
        self.assertRefused(refusals(lambda r: r.update(verdict="GREAT")), "verdict")
        self.assertRefused(refusals(lambda r: r["capabilities"]["usage_probe"].update(level="REPORTED")),
                           "usage_probe.level")
        self.assertRefused(refusals(lambda r: r["records"][0].update(progress_items={"x": 1})), "progress_items")
        self.assertEqual(refusals(lambda r: r["records"][0].update(state="other", reason="other")), [])

    def test_the_times(self):
        self.assertRefused(refusals(lambda r: r.update(recorded_at="2026-09-22 21:33:35")), "recorded_at is not")
        self.assertRefused(refusals(lambda r: r.update(recorded_at="2026-9-22T21:33:35Z")), "recorded_at is not")
        self.assertRefused(refusals(lambda r: r.update(recorded_at="2026-09-27T00:00:00Z")), "recorded_at is in the future")
        self.assertRefused(refusals(lambda r: r["records"][0].update(detected_at="2026-09-01T00:00:00Z")),
                           "before this project existed")
        self.assertRefused(refusals(lambda r: r["records"][0].update(outcome_at="2026-09-21T05:00:00Z")),
                           "records[1]: detected_at, outcome_at are out of order")
        self.assertRefused(refusals(lambda r: r["records"][0].update(delivered_at="2026-09-21T05:00:00Z")),
                           "records[1]: detected_at, delivered_at are out of order")
        self.assertRefused(refusals(lambda r: r["records"][0].update(outcome_at="2026-09-21T09:00:00Z")),
                           "records[1]: delivered_at, outcome_at are out of order")
        self.assertRefused(refusals(lambda r: r["records"][3].update(detected_at="2026-09-23T00:00:00Z")),
                           "records[4].detected_at is after the report was written")
        self.assertRefused(refusals(lambda r: r["local_checks"].update(last="2026-09-23T00:00:00Z")),
                           "local_checks.last is after the report was written")
        self.assertRefused(refusals(lambda r: r["local_checks"].update(first="2026-09-21T18:00:00Z")),
                           "first is after last")
        self.assertRefused(refusals(lambda r: r["local_checks"].update(reports=0)), "exactly when a check passed")
        self.assertRefused(refusals(lambda r: r["local_checks"].update(first=None)), "exactly when a check passed")
        self.assertRefused(refusals(lambda r: r["capabilities"]["usage_probe"].update(
            last_confirmed="2026-09-24T00:00:00Z")), "last_confirmed is after the report was written")

    def test_the_counts(self):
        self.assertRefused(refusals(lambda r: r["local_checks"].update(reports=-1)), "local_checks.reports")
        self.assertRefused(refusals(lambda r: r["local_checks"].update(reports=True)), "local_checks.reports")
        self.assertRefused(refusals(lambda r: r["capabilities"]["usage_probe"].update(confirmed=True)), "not counts")
        self.assertRefused(refusals(lambda r: r["capabilities"]["usage_probe"].update(missed=-2)), "not counts")
        self.assertRefused(refusals(lambda r: r["capabilities"]["usage_probe"].update(confirmed=4, missed=1)),
                           "more judgements than the report has records")
        self.assertRefused(refusals(lambda r: r["records"][0].update(gates_passed=14)), "gates_passed")
        self.assertRefused(refusals(lambda r: r["records"][0].update(progress_items={"fileChange": 1.5})),
                           "progress_items")

    def test_at_most_500_records(self):
        def many(report):
            report["records"] = [copy.deepcopy(report["records"][2]) for _ in range(reader.MAX_RECORDS + 1)]
        self.assertRefused(refusals(many), "records is not a list of at most 500")

    def test_the_sender(self):
        self.assertRefused(refusals(lambda r: None, author="SomeoneElse"), "not the login that opened")
        self.assertRefused(refusals(lambda r: r["reporter"].update(github_login="-bad-")), "github_login")
        self.assertRefused(refusals(lambda r: r["attribution"].update(window=["a", "b"])), "attribution.window")
        self.assertRefused(refusals(lambda r: r.update(note="x" * 1001)), "note is not a sentence")

    def test_the_fingerprint(self):
        """The setup that measured, each part one that could have written this file."""
        cases = {
            "codex_version is not a Codex version": [
                lambda r: r.update(codex_version="codex-cli 0.155.0-beta.1"),
                lambda r: r.update(codex_version="0.155.0"),
                lambda r: r.update(codex_version="codex-cli 0.155.0.lock")],
            "reporter.tool is not": [lambda r: r["reporter"].update(tool="my-own-tool")],
            "reporter.tool_version": [lambda r: r["reporter"].update(tool_version="1.1"),
                                      lambda r: r["reporter"].update(tool_version="0.9.0")],
            "v0.6.0 or later": [lambda r: r["reporter"].update(product_version="0.5.7"),
                                lambda r: r["reporter"].update(product_version="v0.6.9")],
            "not one of this repository's releases": [lambda r: r["reporter"].update(product_version="0.6.99")],
            "not released yet when the report was written": [
                lambda r: r["reporter"].update(product_version="0.6.10-alpha")],
            "reporter.windows": [lambda r: r["reporter"].update(windows="6.1.7601"),
                                 lambda r: r["reporter"].update(windows="10.0.9200"),
                                 lambda r: r["reporter"].update(windows="10.0.26200.1")],
        }
        for fragment, changes in cases.items():
            for change in changes:
                with self.subTest(fragment):
                    self.assertRefused(refusals(change), fragment)

    def test_a_version_has_one_spelling(self):
        """The product orders these as the version on the right, so each would file it again under
        another name: 0.1.0 three times from one login, beside the one-per-version rule."""
        for spelling, canonical in (("codex-cli 00.155.0", "codex-cli 0.155.0"),
                                    ("codex-cli 0.0155.0", "codex-cli 0.155.0"),
                                    ("codex-cli 0.155.0-alpha.09.2", "codex-cli 0.155.0-alpha.9.2"),
                                    ("codex-cli 0.155.0-alpha.9.0", "codex-cli 0.155.0-alpha.9")):
            with self.subTest(spelling):
                self.assertEqual(reader.canonical_version(spelling), canonical)
                self.assertFalse(reader.engine_version(spelling))
                self.assertTrue(reader.engine_version(canonical))
                self.assertRefused(refusals(lambda r: r.update(codex_version=spelling)), "no leading zero")
        self.assertIsNone(reader.canonical_version("codex-cli latest"))
        self.assertEqual(reader.canonical_version("codex-cli 0.155.0-alpha.0"), "codex-cli 0.155.0-alpha.0")

    def test_a_login_windows_keeps_for_a_device_is_refused(self):
        for login in ("nul", "NUL", "Con", "aux", "prn", "com0", "COM9", "lpt1"):
            with self.subTest(login):
                self.assertFalse(reader.login_name(login))
                self.assertRefused(refusals(lambda r: r["reporter"].update(github_login=login), author=login),
                                   "a name Windows keeps for a device")
        for login in ("com10", "nul0", "console", "lpt", "ExampleUser"):
            self.assertTrue(reader.login_name(login), login)

    def test_the_release_rule_is_only_skipped_when_no_releases_are_given(self):
        change = lambda r: r["reporter"].update(product_version="0.6.99")  # noqa: E731
        self.assertEqual(refusals(change, releases=None), [])
        self.assertTrue(refusals(change, releases={}))

    def test_nothing_the_file_says_is_repeated(self):
        """A refusal names a field of the format, never a value from the file: a hostile value is not
        echoed, so it cannot become a workflow command in the check's output."""
        changes = [lambda r: r.update(codex_version=HOSTILE), lambda r: r.update(verdict=HOSTILE),
                   lambda r: r.update(recorded_at=HOSTILE), lambda r: r["reporter"].update(windows=HOSTILE),
                   lambda r: r["reporter"].update(github_login=HOSTILE),
                   lambda r: r["reporter"].update(product_version=HOSTILE),
                   lambda r: r["records"][0].update(state=HOSTILE), lambda r: r.update(**{HOSTILE: 1}),
                   lambda r: r["capabilities"].update(**{HOSTILE: {}})]
        for change in changes:
            found = refusals(change)
            self.assertTrue(found)
            for line in found:
                self.assertNotIn("pwned", line)
                self.assertNotIn("::", line)
                self.assertNotIn("\n", line)


class RecomputeTests(unittest.TestCase):
    RANK = {None: 0, "CHECKED": 1, "VERIFIED": 2}

    def variants(self):
        yield sample()
        for case in CASES:
            yield with_records([(record["delivered"], record["state"]) for record in case["records"]])
        hand = sample()
        for entry in hand["capabilities"].values():
            entry["level"] = "VERIFIED"
        yield hand
        ungated = sample()
        ungated["capabilities"]["exact_thread_recovery"].update(missed=1, level="VERIFIED")
        yield ungated

    def test_it_never_raises_a_level_and_is_idempotent(self):
        for report in self.variants():
            again = reader.recompute(report)
            self.assertEqual(reader.recompute(again), again)
            for name, entry in again["capabilities"].items():
                self.assertLessEqual(self.RANK[entry["level"]], self.RANK[report["capabilities"][name]["level"]])

    def test_a_hand_set_verified_falls_to_what_the_records_show(self):
        hand = sample()
        hand["capabilities"]["usage_probe"]["level"] = "VERIFIED"       # one of its records missed
        hand["capabilities"]["usage_reset_hint"]["level"] = "CHECKED"   # the local checks do not cover it
        again = reader.recompute(hand)
        self.assertIsNone(again["capabilities"]["usage_probe"]["level"])
        self.assertIsNone(again["capabilities"]["usage_reset_hint"]["level"])
        self.assertEqual(again["capabilities"]["engine_present"]["level"], "VERIFIED")
        self.assertEqual(len(reader.changes(hand)), 2)
        self.assertEqual(inspect(hand)[1], [], "recomputed, not refused")
        self.assertEqual(inspect(hand)[2], reader.changes(hand))

    def test_a_covered_capability_falls_to_checked(self):
        hand = sample()
        hand["capabilities"]["engine_present"]["missed"] = 1
        again = reader.recompute(hand)
        # engine_present is covered, so it keeps CHECKED - and it is a gate, so nothing else stays VERIFIED.
        self.assertEqual(again["capabilities"]["engine_present"]["level"], "CHECKED")
        self.assertEqual(again["capabilities"]["exact_thread_recovery"]["level"], "CHECKED")
        self.assertIsNone(again["capabilities"]["loaded_state_detection"]["level"])
        self.assertEqual(again["verdict"], "CHECKED")

    def test_nothing_delivered_verifies_nothing(self):
        report = sample()
        for record in report["records"]:
            record["delivered_at"] = None
        again = reader.recompute(report)
        self.assertNotIn("VERIFIED", [entry["level"] for entry in again["capabilities"].values()])
        self.assertEqual(again["verdict"], "CHECKED")

    def test_a_claimed_verdict_is_derived_again(self):
        report = with_records([])
        report["verdict"] = "PASS"
        self.assertEqual(reader.recompute(report)["verdict"], "NONE")


class IndexTests(unittest.TestCase):
    """What the filed reports add up to: the index, and the counts file a release carries."""

    def reports(self):
        worked = reader.filed_copy(sample())
        failed = with_records([(True, "recovery_turn_failed"), (True, "recovered")])
        failed["reporter"]["github_login"] = "ExampleUser2"
        nothing = with_records([])
        nothing["reporter"]["github_login"] = "ExampleUser3"
        other = with_records([(True, "failed")])
        other["codex_version"] = "codex-cli 0.153.4"
        return {reader.canonical_path(r["reporter"]["github_login"], r["codex_version"]): r
                for r in (worked, failed, nothing, other)}

    def test_the_index_counts_per_version(self):
        index = reader.build_index(self.reports(), generated_at=NOW)
        self.assertEqual(index["format"], reader.INDEX_FORMAT)
        self.assertEqual(index["generated_at"], "2026-09-25T00:00:00Z")
        self.assertEqual(index["versions"]["codex-cli 0.155.0-alpha.9.2"]["reported"],
                         {"reports": 3, "worked": 2, "failed": 1, "neither": 1, "both": 1})
        self.assertEqual(index["versions"]["codex-cli 0.153.4"]["reported"],
                         {"reports": 1, "worked": 0, "failed": 1, "neither": 0, "both": 0})
        entry = index["versions"]["codex-cli 0.155.0-alpha.9.2"]["reports"][0]
        self.assertEqual((entry["reported_by"], entry["verified"], entry["checked"], entry["worked"]),
                         ("ExampleUser", 8, 0, True))

    def test_the_counts_file_is_the_index_projected_and_the_product_reads_it(self):
        projected = reader.project(reader.build_index(self.reports(), generated_at=NOW))
        table = product_reported.parse(json.dumps(projected).encode("ascii"))
        self.assertEqual(table["codex-cli 0.153.4"], {"reports": 1, "worked": 0, "failed": 1, "neither": 0, "both": 0})
        self.assertEqual(list(projected), ["_comment", "format", "versions"])
        self.assertEqual(reader.project(None)["versions"], [])
        self.assertEqual(product_reported.parse(json.dumps(reader.project(None)).encode("ascii")), {})

    def test_the_readme_is_written_from_the_index_alone(self):
        index = reader.build_index(self.reports(), generated_at=NOW)
        text = reader.build_readme(index)
        self.assertEqual(text, reader.build_readme(json.loads(json.dumps(index))))
        self.assertTrue(text.isascii() and text.endswith("\n"))
        self.assertIn("| `codex-cli 0.153.4` | 1 | 0 | 1 | 0 | 0 |", text)
        self.assertIn("| `codex-cli 0.155.0-alpha.9.2` | 3 | 2 | 1 | 1 | 1 |", text)
        self.assertIn("| `codex-cli 0.155.0-alpha.9.2` | [ExampleUser3](ExampleUser3/) | neither | 0 | 0 |", text)
        self.assertNotIn("machine ", text.split("|", 1)[1], "reports are counted, not machines")
        self.assertIn("| - | none yet | - | - | - | - |", reader.build_readme(reader.build_index({}, generated_at=NOW)))

    def test_a_report_path_is_its_login_and_version(self):
        self.assertEqual(reader.canonical_path("ExampleUser", "codex-cli 0.155.0-alpha.9.2"),
                         "docs/evidence/community/ExampleUser/codex-cli-0.155.0-alpha.9.2.json")


if __name__ == "__main__":
    unittest.main()
