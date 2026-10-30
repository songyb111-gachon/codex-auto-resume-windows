"""The advanced edition's compatibility data (compatdata.py): validated whole, trusted only as far as its rules let it.

Each rule of the module's docstring has a test here that fails with that rule reverted: a fail in the build's table wins,
only the exact engine counts, data can narrow, a data pass stands in only for an unmeasured verdict, and an expired,
malformed, too-new or rolled-back document is ignored whole. The bundled file is valid and cites only what exists, and
the one seam (Arming's default `measured`, compatdata.table_for) moves a statement's warnings with an adopted document.

Run from the repository root:

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from codex_auto_resume_advanced import compatdata, evidence, measured  # noqa: E402
from codex_auto_resume_advanced.arming import warnings_for  # noqa: E402
from codex_auto_resume_advanced.vocabulary import ArmingWarning, Measurement, Verdict  # noqa: E402

ENGINE = "codex-cli 0.165.0-alpha.9"          # an engine the build's table names nowhere
OLD = "codex-cli 0.162.0-alpha.17.2"
PRODUCT = (0, 6, 20)
NOW = time.time()


def iso(seconds) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(seconds))


def entry(version, measurement, verdict="pass", recorded=None):
    return {"verdict": verdict, "recorded_at": recorded or time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime(NOW - 7200)),
            "evidence": compatdata.evidence_path(version, measurement)}


def document(engines=None, *, sequence=2, published=None, expires=None, minimum="0.6.20", **changes):
    published = NOW - 3600 if published is None else published
    made = {"format": compatdata.FORMAT, "sequence": sequence, "published_at": iso(published),
            "expires_at": iso(published + 90 * 86400 if expires is None else expires), "min_product": minimum,
            "engines": [{"version": version, "measurements": dict(found)}
                        for version, found in (engines or {}).items()]}
    made.update(changes)
    return made


def raw(made) -> bytes:
    return json.dumps(made).encode("utf-8")


def read(made):
    return compatdata.validate(raw(made), product=PRODUCT)


class ValidationTests(unittest.TestCase):
    def test_a_good_document_is_read(self):
        found = read(document({ENGINE: {"mopen": entry(ENGINE, "mopen")}}))
        self.assertEqual(found["engines"][ENGINE][Measurement.MOPEN][0], Verdict.PASS)

    def test_one_bad_part_refuses_the_whole_document(self):
        good = {"mopen": entry(ENGINE, "mopen")}
        cases = {
            "an unknown verdict": {ENGINE: dict(good, mx=entry(ENGINE, "mx", verdict="blocked"))},
            "evidence elsewhere": {ENGINE: dict(good, mx=dict(entry(ENGINE, "mx"), evidence="docs/evidence/live/x.json"))},
            "an extra key": {ENGINE: dict(good, mx=dict(entry(ENGINE, "mx"), note="hello"))},
            "a bad id": {ENGINE: dict(good, **{"M X": entry(ENGINE, "mx")})},
            "a bad engine": {"0.165.0": good},
        }
        for name, engines in cases.items():
            with self.subTest(name):
                with self.assertRaises(compatdata.Refused):
                    read(document(engines))
        twice = document({ENGINE: good})
        twice["engines"].append(dict(twice["engines"][0]))
        for name, made in (("a duplicate engine", twice), ("another format", document(format="x/1")),
                           ("an extra top key", document(advisories=[])),
                           ("another edition line", document(_edition="anything")),
                           ("a newer product", document(minimum="9.0.0")),
                           ("expiry before publication", document(expires=NOW - 7200)),
                           ("a sequence of 0", document(sequence=0))):
            with self.subTest(name):
                with self.assertRaises(compatdata.Refused):
                    read(made)
        with self.assertRaises(compatdata.Refused):
            compatdata.validate(b" " * (compatdata.MAX_BYTES + 1), product=PRODUCT)

    def test_the_edition_line_may_lead_it(self):
        self.assertEqual(read(document({}, _edition=compatdata.EDITION_MARK))["sequence"], 2)

    def test_a_measurement_this_build_does_not_know_is_passed_over(self):
        found = read(document({ENGINE: {"mzzz": entry(ENGINE, "mzzz"), "mopen": entry(ENGINE, "mopen")}}))
        self.assertEqual(set(found["engines"][ENGINE]), {Measurement.MOPEN})


class TrustTests(unittest.TestCase):
    """compatdata.overlay: the trust rules, one test each."""

    def data(self, verdicts, engine=ENGINE):
        return read(document({engine: {str(m): entry(engine, str(m), str(v)) for m, v in verdicts.items()}}))

    def test_a_fail_in_the_builds_table_always_wins(self):
        table = {Measurement.M2: (Verdict.FAIL, OLD)}
        found = compatdata.overlay(table, self.data({Measurement.M2: Verdict.PASS}), ENGINE)
        self.assertEqual(found[Measurement.M2], (Verdict.FAIL, OLD))

    def test_only_the_exact_engine_in_force_counts(self):
        data = self.data({Measurement.MOPEN: Verdict.PASS}, engine="codex-cli 0.165.0-alpha.10")
        self.assertEqual(compatdata.overlay({}, data, ENGINE), {})

    def test_a_data_fail_narrows(self):
        table = {Measurement.MOPEN: (Verdict.PASS, ENGINE)}
        found = compatdata.overlay(table, self.data({Measurement.MOPEN: Verdict.FAIL}), ENGINE)
        self.assertEqual(found[Measurement.MOPEN], (Verdict.FAIL, ENGINE))

    def test_a_data_pass_stands_in_only_for_an_unmeasured_verdict(self):
        data = self.data({Measurement.MOPEN: Verdict.PASS, Measurement.MIMG: Verdict.PASS})
        table = {Measurement.MOPEN: (Verdict.PASS, OLD)}
        found = compatdata.overlay(table, data, ENGINE)
        self.assertEqual(found[Measurement.MOPEN], (Verdict.PASS, ENGINE))      # measured on another engine
        self.assertEqual(found[Measurement.MIMG], (Verdict.PASS, ENGINE))       # never measured
        self.assertEqual(compatdata.overlay({}, data, None), {})                  # no engine known: nothing

    def test_any_verdict_the_build_made_on_that_engine_stands_against_a_data_pass(self):
        """Rule 4 (the W7 review): a build verdict made on the exact engine - a pass, and a blocked one too - is a
        verdict there, so a data pass does not stand in for it; on another engine it does."""
        data = self.data({Measurement.MOPEN: Verdict.PASS})
        self.assertEqual(compatdata.overlay({Measurement.MOPEN: (Verdict.BLOCKED, ENGINE)}, data, ENGINE)[Measurement.MOPEN],
                         (Verdict.BLOCKED, ENGINE))
        self.assertEqual(compatdata.overlay({Measurement.MOPEN: (Verdict.BLOCKED, OLD)}, data, ENGINE)[Measurement.MOPEN],
                         (Verdict.PASS, ENGINE))
        failed = self.data({Measurement.MOPEN: Verdict.FAIL})
        self.assertEqual(compatdata.overlay({Measurement.MOPEN: (Verdict.BLOCKED, ENGINE)}, failed, ENGINE)[Measurement.MOPEN],
                         (Verdict.FAIL, ENGINE))

    def test_the_warnings_follow(self):
        definition = ac.definition(measurements=(Measurement.MOPEN,), compat=None)
        view = {"status": "ok", "engine": {"found": True, "version": ENGINE}, "capabilities": {}}
        self.assertIn(ArmingWarning.UNMEASURED, warnings_for(definition, view, {}))
        stood = compatdata.overlay({}, self.data({Measurement.MOPEN: Verdict.PASS}), ENGINE)
        self.assertNotIn(ArmingWarning.UNMEASURED, warnings_for(definition, view, stood))
        failed = compatdata.overlay({}, self.data({Measurement.MOPEN: Verdict.FAIL}), ENGINE)
        self.assertIn(ArmingWarning.MEASUREMENT_FAILED, warnings_for(definition, view, failed))


class InForceTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.state = self.root / "config"
        self.state.mkdir()
        self.bundled = self.root / "bundled.json"
        self.bundled.write_bytes(raw(document({}, sequence=3)))

    def put(self, name, made):
        (self.state / name).write_bytes(made if isinstance(made, bytes) else raw(made))

    def force(self, now=NOW):
        return compatdata.in_force(self.state, bundled=self.bundled, now=now, product=PRODUCT)

    def test_a_newer_valid_download_is_adopted_and_removed(self):
        self.put(compatdata.DOWNLOAD, document({ENGINE: {"mopen": entry(ENGINE, "mopen")}}, sequence=4))
        self.assertEqual(self.force()["sequence"], 4)
        self.assertFalse((self.state / compatdata.DOWNLOAD).exists())
        self.assertTrue((self.state / compatdata.ADOPTED).exists())

    def test_a_rolled_back_or_broken_download_is_never_adopted_and_still_removed(self):
        for name, made in (("older", document({}, sequence=3)), ("broken", b"{"),
                           ("one bad engine", document({ENGINE: {"mopen": entry(ENGINE, "mopen", "maybe")}},
                                                       sequence=9))):
            with self.subTest(name):
                self.put(compatdata.DOWNLOAD, made)
                self.assertEqual(self.force()["sequence"], 3)
                self.assertFalse((self.state / compatdata.DOWNLOAD).exists())
                self.assertFalse((self.state / compatdata.ADOPTED).exists())

    def test_an_expired_document_is_ignored_whole(self):
        self.put(compatdata.ADOPTED, document({ENGINE: {"mopen": entry(ENGINE, "mopen", "fail")}}, sequence=5,
                                              published=NOW - 100 * 86400, expires=NOW - 86400))
        self.assertEqual(self.force()["sequence"], 3)
        self.bundled.write_bytes(raw(document({}, sequence=3, published=NOW - 100 * 86400, expires=NOW - 86400)))
        self.assertIsNone(self.force())
        self.assertEqual(compatdata.overlay(measured.MEASURED, self.force(), ENGINE), measured.MEASURED)

    def test_a_file_rewritten_inside_one_tick_of_the_file_clock_is_read_again(self):
        """CI's runners keep a file's modified time coarse: a document rewritten with as many bytes keeps its size and
        its time. It is still read as what it now says (the 3-of-7 red of test_an_expired_document_is_ignored_whole)."""
        self.assertEqual(self.force()["sequence"], 3)
        before = os.stat(self.bundled)
        expired = raw(document({}, sequence=3, published=NOW - 100 * 86400, expires=NOW - 86400))
        self.assertEqual(len(expired), before.st_size)
        self.bundled.write_bytes(expired)
        os.utime(self.bundled, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertIsNone(self.force())

    def test_nothing_is_fetched_here(self):
        """This module reads files and never the network: the fetch is the bootstrap's, at a person's request."""
        text = Path(compatdata.__file__).read_text(encoding="utf-8")
        for word in ("urllib", "http.client", "socket", "requests", "urlopen"):
            self.assertNotIn(word, text)


class SeamTests(ac.AdvancedCase):
    def test_the_default_reading_lays_the_adopted_data_over_the_table(self):
        definition = ac.definition(measurements=(Measurement.MOPEN,))
        made = ac.Runtime(self.paths, **dict(self.options(definition), measured=None))
        self.addCleanup(made.state.close)
        self.compat = ac.view(version=ENGINE)
        self.assertIn(ArmingWarning.UNMEASURED, made.arming.warnings(definition))
        self.paths.state_dir.mkdir(parents=True, exist_ok=True)
        (self.paths.state_dir / compatdata.DOWNLOAD).write_bytes(
            raw(document({ENGINE: {"mopen": entry(ENGINE, "mopen")}}, sequence=99, minimum="0.6.0")))
        self.assertNotIn(ArmingWarning.UNMEASURED, made.arming.warnings(definition))
        self.assertEqual(made.arming.verdict(Measurement.MOPEN), "pass")


class BundledTests(unittest.TestCase):
    def test_the_bundled_file_is_valid_unexpired_and_cites_only_what_exists(self):
        found = compatdata.validate(compatdata.BUNDLED.read_bytes())
        self.assertGreater(found["expires_at"], time.time())
        document_ = json.loads(compatdata.BUNDLED.read_text(encoding="utf-8"))
        for engine in document_["engines"]:
            for name, said in engine["measurements"].items():
                with self.subTest(engine=engine["version"], measurement=name):
                    record = json.loads((ac.ROOT / said["evidence"]).read_text(encoding="utf-8"))
                    self.assertEqual(evidence.outcome(record), (Verdict(said["verdict"]), engine["version"]))

    def test_it_is_not_the_standard_data(self):
        standard = ac.ROOT / "src" / "codex_auto_resume" / "data" / "codex_compat.json"
        self.assertNotEqual(json.loads(standard.read_text(encoding="utf-8"))["format"], compatdata.FORMAT)
        self.assertNotIn("codex_auto_resume" + os.sep + "data", str(compatdata.BUNDLED))


if __name__ == "__main__":
    unittest.main()
