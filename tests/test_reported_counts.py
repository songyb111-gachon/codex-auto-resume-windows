"""The counts of other people's reports that a release carries (src/codex_auto_resume/compat/reported.py).

Reported is a grade beside the ladder, never on it, and its counts arrive in a file of their own,
data/reported.json - never inside the compatibility data, which the reporter promises a report
never reaches, and never by a request: the refresh a person asks for fetches the registry and
nothing else. So beside the reader's own rules, this holds the two files apart: each refuses the
other whole, the registry names no counts, and bootstrap.ps1 still knows one data address.

The reader is held the way the registry's is: a byte cap before parsing, the hardened decoder,
exact keys, and counts that add up, or the whole file reads as `rejected` - which only ever
changes what Reported says, and never what the registry is.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest import mock

from codex_auto_resume import compat
from codex_auto_resume.compat import reported

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "src" / "codex_auto_resume" / "data"
VERSION = "codex-cli 0.155.0-alpha.9.2"


def entry(version=VERSION, reports=3, worked=2, failed=1, neither=1, both=1):
    return {"version": version, "reports": reports, "worked": worked, "failed": failed, "neither": neither,
            "both": both}


def counts(*entries, **overrides):
    document = {"format": reported.FORMAT, "versions": list(entries)}
    document.update(overrides)
    return json.dumps(document).encode("utf-8")


def refused(raw):
    try:
        reported.parse(raw)
    except compat.DocumentError as error:
        return error.code
    return None


class ParseTests(unittest.TestCase):
    def test_the_shipped_file_reads(self):
        standing, table = reported.read(DATA / "reported.json")
        self.assertEqual(standing, "ok")
        self.assertIsInstance(table, dict)
        (DATA / "reported.json").read_bytes().decode("ascii")

    def test_a_well_formed_file_reads(self):
        table = reported.parse(counts(entry(), entry("codex-cli 0.153.4", 1, 0, 0, 1, 0)))
        self.assertEqual(table[VERSION], {"reports": 3, "worked": 2, "failed": 1, "neither": 1, "both": 1})
        self.assertEqual(table["codex-cli 0.153.4"]["neither"], 1)
        self.assertEqual(reported.parse(counts()), {}, "open, and nothing filed yet")

    def test_the_counts_have_to_add_up(self):
        """Each report is in exactly one of worked only, failed only, both, or neither."""
        for bad in (entry(reports=0, worked=0, failed=0, neither=0, both=0),
                    entry(worked=4), entry(neither=4),
                    entry(both=0),                                   # 2 + 1 + 1 - 3 is 1
                    entry(reports=3, worked=1, failed=1, neither=3, both=2)):  # both over min(worked, failed)
            with self.subTest(bad):
                self.assertEqual(refused(counts(bad)), "invalid_field")
        self.assertIsNone(refused(counts(entry(reports=2, worked=2, failed=2, neither=0, both=2))),
                          "two reports that each said both")

    def test_every_count_is_a_count(self):
        for name in reported.COUNTS:
            for value in (True, -1, 1.0, "1", None, reported.MAX_COUNT + 1):
                with self.subTest(name=name, value=value):
                    self.assertEqual(refused(counts(dict(entry(), **{name: value}))), "invalid_field")

    def test_versions_are_the_products_own_and_named_once(self):
        for version in ("0.155.0", "codex-cli 0.155.0-beta.1", "codex-cli", "", 7, None, "codex-cli 0.155.0\n"):
            with self.subTest(version=version):
                self.assertEqual(refused(counts(entry(version=version))), "invalid_field")
        self.assertEqual(refused(counts(entry(), entry())), "invalid_field")

    def test_the_file_is_refused_whole(self):
        self.assertEqual(refused(counts(format="codex-auto-resume-reported/2")), "unknown_format")
        self.assertEqual(refused(counts(extra=1)), "invalid_field")
        self.assertEqual(refused(json.dumps({"format": reported.FORMAT}).encode()), "invalid_field")
        self.assertEqual(refused(counts(versions={})), "invalid_field")
        self.assertEqual(refused(counts(dict(entry(), extra=1))), "invalid_field")
        self.assertEqual(refused(counts(_comment="one line")), "invalid_field")
        self.assertEqual(refused(counts(_comment=["x" * 201])), "invalid_field")
        self.assertEqual(refused(b"[]"), "not_an_object")
        self.assertEqual(refused(counts().replace(b'"format"', b'"format": "x", "format"', 1)), "duplicate_key")
        self.assertEqual(refused(counts(entry()).replace(b'"reports": 3', b'"reports": NaN')), "not_finite")
        self.assertEqual(refused(b"[" * 60000 + b"]" * 60000), "too_deep")
        self.assertEqual(refused(b" " * (reported.MAX_BYTES + 1)), "too_large")

    def test_five_hundred_versions_fit_and_one_more_does_not(self):
        many = [entry("codex-cli 0.%d.0" % number, 100000, 100000, 100000, 0, 100000)
                for number in range(reported.MAX_VERSIONS)]
        raw = counts(*many)
        self.assertLess(len(raw), reported.MAX_BYTES)
        self.assertEqual(len(reported.parse(raw)), reported.MAX_VERSIONS)
        self.assertEqual(refused(counts(*many, entry("codex-cli 1.0.0"))), "too_many")


class LookupTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.path = Path(scratch.name) / "reported.json"

    def lookup(self, version, raw=None):
        if raw is not None:
            self.path.write_bytes(raw)
        return reported.lookup(version, path=self.path)

    def test_each_state(self):
        raw = counts(entry())
        self.assertEqual(self.lookup(VERSION, raw), {"state": "reported", "reports": 3, "worked": 2, "failed": 1,
                                                     "neither": 1, "both": 1})
        self.assertEqual(self.lookup("0.155.0-alpha.9.2")["state"], "reported", "named with or without its prefix")
        self.assertEqual(self.lookup("codex-cli 0.153.4")["state"], "none_yet")
        for nothing in (None, "", "codex-cli nonsense", 7):
            self.assertEqual(self.lookup(nothing)["state"], "unavailable")
        self.path.unlink()
        self.assertEqual(self.lookup(VERSION)["state"], "unavailable")
        self.assertEqual(self.lookup(VERSION, b"{")["state"], "rejected")

    def test_always_the_same_keys_and_no_count_without_reports(self):
        for version, raw in ((VERSION, counts(entry())), ("codex-cli 0.153.4", None), (None, None),
                             (VERSION, b"not json")):
            answer = self.lookup(version, raw)
            self.assertEqual(list(answer), ["state"] + list(reported.COUNTS))
            self.assertIn(answer["state"], reported.STATES)
            if answer["state"] != "reported":
                self.assertEqual([answer[name] for name in reported.COUNTS], [0] * 5)

    def test_no_state_is_a_word_of_the_ladder(self):
        ladder = {word.lower() for word in compat.STATES} | set(compat.ENGINE_STATES)
        self.assertFalse(set(reported.STATES) & ladder)

    def test_it_is_parsed_once_per_version_of_the_file(self):
        """The Diagnostics page asks on every poll: that costs a stat, not a parse (the v0.6.9 lag work)."""
        self.path.write_bytes(counts(entry()))
        with mock.patch.object(reported, "parse", wraps=reported.parse) as parse:
            for _ in range(1000):
                reported.lookup(VERSION, path=self.path)
            self.assertEqual(parse.call_count, 1)
            self.path.write_bytes(counts(entry(reports=4, neither=2)))
            self.assertEqual(reported.lookup(VERSION, path=self.path)["reports"], 4)
            self.assertEqual(parse.call_count, 2)


class KeptApartTests(unittest.TestCase):
    """Two files, two readers, one fetch."""

    def test_the_registry_refuses_the_counts_and_the_counts_refuse_the_registry(self):
        with self.assertRaises(compat.DocumentError):
            compat.parse_document((DATA / "reported.json").read_bytes())
        self.assertEqual(refused((DATA / "codex_compat.json").read_bytes()), "unknown_format")

    def test_the_compatibility_data_carries_no_counts(self):
        registry = json.loads((DATA / "codex_compat.json").read_text(encoding="utf-8"))
        self.assertNotIn("reported", registry)
        self.assertNotIn("community", json.dumps(registry).lower())

    def test_the_refresh_still_knows_one_address_and_it_is_the_registrys(self):
        script = (ROOT / "scripts" / "bootstrap.ps1").read_text(encoding="utf-8")
        addresses = re.findall(r"https://raw\.githubusercontent\.com/[^\s'\"]+", script)
        self.assertEqual(addresses, ["https://raw.githubusercontent.com/songyb111-gachon/codex-auto-resume-windows/"
                                     "main/src/codex_auto_resume/data/codex_compat.json"])
        self.assertNotIn("reported.json", script)
        self.assertNotIn("evidence/community", script)

    def test_nothing_shipped_names_the_counts_as_an_address(self):
        for folder in ("src", "scripts"):
            for path in (ROOT / folder).rglob("*"):
                if path.suffix in (".py", ".ps1", ".js", ".json", ".cs") and path.is_file():
                    text = path.read_text(encoding="utf-8", errors="replace")
                    with self.subTest(str(path.relative_to(ROOT))):
                        self.assertIsNone(re.search(r"https?://\S*(reported\.json|evidence/community)", text))


if __name__ == "__main__":
    unittest.main()
