"""The filed reports, their index and the counts a release carries agree, read from the files up.

docs/evidence/community/<login>/*.json are the reports filed - by the filer
(.github/workflows/community-file.yml) or the maintainer's tool; index.json lists them; README.md
says what the index says; src/codex_auto_resume/data/reported.json is the index's counts, which the
product shows. This holds the chain from the files to what is shown, so a hand edit anywhere along
it fails:

* every filed report is read by the same reader as the pull-request check, and is kept as its
  recomputed reading with our sentences, so a hand-edited conclusion does not survive;
* every index entry's file exists under its own login and re-derives exactly that entry - worked
  and failed from the records, verified and checked from the recomputed levels;
* each version's counts re-derive from its entries, and the counts file equals the index's;
* the folder's README is exactly what build/community_report.py build_readme() writes for the
  index, and withdrawn.json, when there is one, is the list the filer reads it as;
* a report file the index does not list is waiting - in a pull request, or not accepted yet - and
  counts nowhere. So a contributor's pull request that adds one file stays green here, and a
  withdrawal removes the file and its entry together.

Until the folder exists (the maintainer opens it once the check is on main and the release that
reads the counts is out) the only thing to hold is that the counts file names nothing. The rules
are also run on a scratch tree built from the fixtures, so they are tested while the real folder
is still empty.
"""
from __future__ import annotations

import calendar
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "build"))

import community_check as check  # noqa: E402
import community_file as filer  # noqa: E402
import community_report as reader  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "community" / "codex-cli-0.155.0-alpha.9.2.json"
COUNTS = Path("src") / "codex_auto_resume" / "data" / "reported.json"
INDEX_KEYS = {"format", "generated_at", "grade", "grants", "versions"}
NOW = calendar.timegm((2026, 9, 25, 0, 0, 0))


def held(root: Path, *, releases=None, now=None) -> list:
    """Every way the files under `root` disagree, as text; [] when they agree."""
    community = root / reader.COMMUNITY
    problems = []
    index = None
    if community.exists():
        index_path = community / "index.json"
        if not index_path.is_file():
            return ["the folder has no index.json"]
        index = json.loads(index_path.read_text(encoding="utf-8"))
        problems += _index(root, index, releases, now)
        readme = community / "README.md"
        if not readme.is_file() or readme.read_text(encoding="utf-8") != reader.build_readme(index):
            problems.append("README.md is not what build_readme writes for the index")
        problems += _withdrawn(community / "withdrawn.json")
    shipped = json.loads((root / COUNTS).read_text(encoding="utf-8"))
    if shipped != reader.project(index):
        problems.append("data/reported.json is not the index's counts")
    return problems


def _index(root, index, releases, now):
    problems = []
    if set(index) != INDEX_KEYS or index["format"] != reader.INDEX_FORMAT or index["grade"] != "REPORTED" \
            or reader.moment(index["generated_at"]) is None:
        return ["index.json is not the index format"]
    listed = set()
    for version, held_version in index["versions"].items():
        entries = held_version["reports"]
        if set(held_version) != {"reported", "reports"} or not entries:
            problems.append("%s: not a listing of reports" % version)
            continue
        if held_version["reported"] != reader.tally(reader.graded_of_entry(entry) for entry in entries):
            problems.append("%s: its counts are not its entries'" % version)
        if [entry["path"] for entry in entries] != sorted(entry["path"] for entry in entries):
            problems.append("%s: its entries are not in path order" % version)
        for entry in entries:
            path = entry["path"]
            if path in listed:
                problems.append("%s is listed twice" % path)
            listed.add(path)
            if path != reader.canonical_path(entry["reported_by"], version):
                problems.append("%s is not filed under its own login and version" % path)
                continue
            file = root / path
            if not file.is_file():
                problems.append("%s is listed and not there" % path)
                continue
            report, refusals, _changes = reader.inspect(file.read_bytes(), author=entry["reported_by"],
                                                        now=now, releases=releases)
            if refusals:
                problems.append("%s is refused: %s" % (path, "; ".join(refusals)))
                continue
            if report != reader.filed_copy(report):
                problems.append("%s is not kept as its recomputed reading with our sentences" % path)
            if entry != reader.index_entry(path, report):
                problems.append("%s: its entry is not what the file says" % path)
    return problems


def _withdrawn(path):
    """withdrawn.json, when there is one: the filer's own format, each entry an account and a version."""
    if not path.exists():
        return []
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return ["withdrawn.json is not JSON"]
    entries = document.get("withdrawn") if isinstance(document, dict) else None
    if (not isinstance(document, dict) or set(document) != {"format", "withdrawn"}
            or document["format"] != filer.WITHDRAWN_FORMAT or not isinstance(entries, list)):
        return ["withdrawn.json is not the list the filer reads"]
    for entry in entries:
        if (not isinstance(entry, dict) or set(entry) != {"reporter_id", "login", "version", "at"}
                or not isinstance(entry["reporter_id"], int) or isinstance(entry["reporter_id"], bool)
                or not reader.LOGIN.fullmatch(str(entry["login"]))
                or not reader.engine_version("codex-cli " + str(entry["version"]))
                or reader.moment(entry["at"]) is None):
            return ["withdrawn.json holds an entry that is not an account, a version and a time"]
    return []


def releases_here():
    try:
        found = check.Git(ROOT).releases()
    except check.CheckError:
        return None
    return found or None


class RepositoryTests(unittest.TestCase):
    def test_the_filed_reports_the_index_and_the_counts_agree(self):
        self.assertEqual(held(ROOT, releases=releases_here()), [])

    def test_until_the_folder_exists_the_counts_name_nothing(self):
        if (ROOT / reader.COMMUNITY).exists():
            self.skipTest("the folder is open; the test above holds it")
        self.assertEqual(json.loads((ROOT / COUNTS).read_text(encoding="utf-8"))["versions"], [])


class ScratchTests(unittest.TestCase):
    """The same rules on a tree built from the fixtures, and each way to break one."""

    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        base = json.loads(FIXTURE.read_text(encoding="utf-8"))
        second = json.loads(json.dumps(base))
        second["reporter"]["github_login"] = "ExampleUser2"
        second["records"][1]["state"] = "recovery_turn_failed"
        self.reports = {reader.canonical_path(report["reporter"]["github_login"], report["codex_version"]):
                        reader.filed_copy(report) for report in (base, second)}
        self.write()

    def write(self, reports=None, index=None, counts=None):
        reports = self.reports if reports is None else reports
        shutil.rmtree(self.root / reader.COMMUNITY, ignore_errors=True)
        for path, report in reports.items():
            (self.root / path).parent.mkdir(parents=True, exist_ok=True)
            (self.root / path).write_bytes(reader.encode(report))
        index = reader.build_index(reports, generated_at=NOW) if index is None else index
        (self.root / reader.COMMUNITY).mkdir(parents=True, exist_ok=True)
        (self.root / reader.COMMUNITY / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
        (self.root / reader.COMMUNITY / "README.md").write_text(reader.build_readme(index), encoding="utf-8")
        (self.root / COUNTS).parent.mkdir(parents=True, exist_ok=True)
        (self.root / COUNTS).write_text(json.dumps(reader.project(index) if counts is None else counts),
                                        encoding="utf-8")
        return index

    def problems(self):
        return held(self.root, releases={"v0.6.9": NOW - 5 * 86400}, now=NOW)

    def test_a_consistent_tree_holds(self):
        self.assertEqual(self.problems(), [])
        counts = json.loads((self.root / COUNTS).read_text(encoding="utf-8"))
        self.assertEqual(counts["versions"], [{"version": "codex-cli 0.155.0-alpha.9.2", "reports": 2, "worked": 2,
                                               "failed": 1, "neither": 0, "both": 1}])

    def test_a_hand_set_conclusion_does_not_survive(self):
        path = sorted(self.reports)[0]
        edited = json.loads(json.dumps(self.reports[path]))
        edited["capabilities"]["usage_probe"]["level"] = "VERIFIED"
        (self.root / path).write_bytes(reader.encode(edited))
        self.assertIn("%s is not kept as its recomputed reading with our sentences" % path, self.problems())

    def test_a_hand_edited_sentence_does_not_survive(self):
        path = sorted(self.reports)[0]
        edited = json.loads(json.dumps(self.reports[path]))
        edited["note"] = "Verified by me."
        (self.root / path).write_bytes(reader.encode(edited))
        self.assertIn("%s is not kept as its recomputed reading with our sentences" % path, self.problems())

    def test_an_index_that_says_more_than_its_files(self):
        index = reader.build_index(self.reports, generated_at=NOW)
        entry = index["versions"]["codex-cli 0.155.0-alpha.9.2"]["reports"][0]
        entry["failed"] = True
        self.write(index=index, counts=reader.project(reader.build_index(self.reports, generated_at=NOW)))
        found = self.problems()
        self.assertIn("%s: its entry is not what the file says" % entry["path"], found)
        self.assertIn("codex-cli 0.155.0-alpha.9.2: its counts are not its entries'", found)

    def test_counts_that_are_not_the_index(self):
        counts = reader.project(reader.build_index(self.reports, generated_at=NOW))
        counts["versions"][0]["worked"] = 1
        counts["versions"][0]["both"] = 0
        self.write(counts=counts)
        self.assertEqual(self.problems(), ["data/reported.json is not the index's counts"])

    def test_an_entry_whose_file_is_gone_or_elsewhere(self):
        path = sorted(self.reports)[0]
        (self.root / path).unlink()
        self.assertIn("%s is listed and not there" % path, self.problems())
        index = reader.build_index(self.reports, generated_at=NOW)
        index["versions"]["codex-cli 0.155.0-alpha.9.2"]["reports"][0]["reported_by"] = "ExampleUser3"
        self.write(index=index)
        self.assertIn("%s is not filed under its own login and version" % path, self.problems())

    def test_a_file_the_index_does_not_list_counts_nowhere(self):
        """A contributor's pull request adds one file; test.yml runs this suite on it and stays green."""
        index = self.write()
        pending = json.loads(json.dumps(self.reports[sorted(self.reports)[0]]))
        pending["reporter"]["github_login"] = "ExampleUser9"
        path = reader.canonical_path("ExampleUser9", pending["codex_version"])
        (self.root / path).parent.mkdir(parents=True)
        (self.root / path).write_bytes(reader.encode(pending))
        self.assertEqual(self.problems(), [])
        self.assertEqual(json.loads((self.root / COUNTS).read_text(encoding="utf-8")), reader.project(index))

    def test_a_withdrawal_takes_the_file_and_its_entry_together(self):
        kept = dict(self.reports)
        kept.pop(sorted(kept)[0])
        self.write(reports=kept)
        self.assertEqual(self.problems(), [])
        self.write(reports=kept, index=reader.build_index(self.reports, generated_at=NOW))
        self.assertTrue(any("listed and not there" in problem for problem in self.problems()))

    def test_a_hand_edited_readme_does_not_survive(self):
        readme = self.root / reader.COMMUNITY / "README.md"
        readme.write_text(readme.read_text(encoding="utf-8").replace("| 2 |", "| 20 |"), encoding="utf-8")
        self.assertEqual(self.problems(), ["README.md is not what build_readme writes for the index"])

    def test_the_readme_says_what_the_index_says(self):
        text = (self.root / reader.COMMUNITY / "README.md").read_text(encoding="utf-8")
        self.assertIn("| `codex-cli 0.155.0-alpha.9.2` | 2 | 2 | 1 | 0 | 1 |", text)
        self.assertIn("[ExampleUser2](ExampleUser2/)", text)
        self.assertTrue(text.isascii())

    def test_a_withdrawn_list_is_the_one_the_filer_reads(self):
        path = self.root / reader.COMMUNITY / "withdrawn.json"
        entry = {"reporter_id": 7, "login": "ExampleUser", "version": "0.155.0-alpha.9.2", "at": "2026-09-24T00:00:00Z"}
        path.write_text(json.dumps({"format": filer.WITHDRAWN_FORMAT, "withdrawn": [entry]}), encoding="utf-8")
        self.assertEqual(self.problems(), [])
        path.write_text(json.dumps({"format": filer.WITHDRAWN_FORMAT, "withdrawn": [dict(entry, reporter_id="7")]}),
                        encoding="utf-8")
        self.assertEqual(self.problems(), ["withdrawn.json holds an entry that is not an account, a version and a time"])

    def test_an_empty_folder_needs_its_index(self):
        shutil.rmtree(self.root / reader.COMMUNITY)
        (self.root / reader.COMMUNITY).mkdir(parents=True)
        self.assertEqual(self.problems(), ["the folder has no index.json"])


if __name__ == "__main__":
    unittest.main()
