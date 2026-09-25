"""Reported informs and decides nothing: it never raises a tier and never changes behaviour.

The roadmap's rule for what others report (docs/ROADMAP.md, "Compatibility reports from others"),
held two ways, because a rule only tested once is a rule the next change forgets:

1. By structure. The counts are read by one module, compat/reported.py, and only the view may
   import it - the view shows them. The modules that decide - the engine, the watcher's loop, the
   registry's standing, permits, evaluator and cache, the control layer's policy, the gates, the
   popup and the tray - never import it and never spell its file, its format or its key.
2. By behaviour. Across counts files that are absent, claim 1,000 reports that worked, claim
   1,000 that failed, or are broken, and across every local check result and registry standing,
   every capability's state, the gate's word, every permit and what the watcher writes are the
   same. A version with no evidence of its own stays COMPATIBLE with 1,000 reports that it worked;
   FAILED_HERE and INCOMPATIBLE stay blocked; VERIFIED stays VERIFIED with 1,000 that it failed.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)        # srcscan lives next to this file

import srcscan  # noqa: E402
from codex_auto_resume import compat, compatio, config  # noqa: E402
from codex_auto_resume.compat import files, probes, reported  # noqa: E402

PACKAGE = srcscan.PACKAGE
READER = PACKAGE + ".compat.reported"
# The one module that may read the counts: the view, which shows them.
MAY_IMPORT = {PACKAGE + ".compat.views"}
# The modules that decide, and must never name Reported at all.
DECIDING = ("engine/", "runtime/", "ui/", "compat/standing.py", "compat/permits.py", "compat/evaluator.py",
            "compat/cache.py", "compat/model.py", "control/policy.py", "domain/gates.py")
WORDS = ("reported", "reported.json", reported.FORMAT)

VERIFIED_HERE = "codex-cli 0.153.4"             # VERIFIED by the bundled data
CHECKED_HERE = "codex-cli 0.155.0-alpha.16.4"    # CHECKED by the bundled data
NOTHING_SAID = "codex-cli 0.160.0"              # no evidence of its own
MARKED = "codex-cli 0.161.0"                    # INCOMPATIBLE by a refreshed document
VERSIONS = (VERIFIED_HERE, CHECKED_HERE, NOTHING_SAID, MARKED, None)


def counts(**by_version) -> bytes:
    return json.dumps({"format": reported.FORMAT, "versions": [
        dict(version=version, **entry) for version, entry in sorted(by_version.items())]}).encode("ascii")


def claim(worked=0, failed=0):
    reports = max(worked, failed)
    both = worked + failed - reports
    return {"reports": reports, "worked": worked, "failed": failed, "neither": 0, "both": both}


EVERY = {version: None for version in VERSIONS if version}
VARIANTS = {
    "absent": None,
    "worked": counts(**{version: claim(worked=1000) for version in EVERY}),
    "failed": counts(**{version: claim(failed=1000) for version in EVERY}),
    "broken": b'{"format": "' + reported.FORMAT.encode() + b'", "versions": [{"version": 7}]}',
}
CHECK_SETS = {
    "pass": {name: compat.PASS for name in compat.CHECKS},
    "queue_flags_fail": dict({name: compat.PASS for name in compat.CHECKS}, queue_flags=compat.FAIL),
    "version_unavailable": dict({name: compat.PASS for name in compat.CHECKS}, version_runs=compat.UNAVAILABLE),
    "history_fail": dict({name: compat.PASS for name in compat.CHECKS}, history_schema=compat.FAIL),
}


def refreshed():
    """A refreshed document that marks MARKED incompatible, as a cache in force would hold it."""
    return compat.validate_document({
        "format": compat.FORMAT, "sequence": 99, "published_at": "2026-09-20T00:00:00Z",
        "expires_at": "2026-12-19T00:00:00Z", "min_product": "0.6.5", "requires_signature": False,
        "engines": [{"version": MARKED, "capabilities": {"exact_thread_recovery": {
            "state": "INCOMPATIBLE", "reason": "queue_interface_changed"}}}],
        "advisories": []})


class StructureTests(unittest.TestCase):
    def test_only_the_view_imports_the_reader(self):
        importers = {module for module, targets in srcscan.import_graph(lazy=True).items() if READER in targets}
        self.assertLessEqual(importers, MAY_IMPORT)
        self.assertIn(READER, srcscan.modules(), "the reader is tracked, or this scan proves nothing")

    def test_the_package_does_not_hand_it_on(self):
        """compat/__init__.py does not re-export it, so `compat.X` never reaches it by accident."""
        source = (srcscan.SRC / PACKAGE / "compat" / "__init__.py").read_text(encoding="utf-8")
        self.assertNotIn("reported", source)

    def deciding_files(self):
        found = []
        for path in srcscan.package_files():
            name = srcscan.relative(path)
            inner = name[len(PACKAGE) + 1:] if name.startswith(PACKAGE + "/") else name
            if any(inner == rule or (rule.endswith("/") and inner.startswith(rule)) for rule in DECIDING):
                found.append(path)
        return found

    def test_the_modules_that_decide_never_name_it(self):
        found = self.deciding_files()
        self.assertGreater(len(found), 30, "the scan found too few modules to mean anything")
        for path in found:
            tree = ast.parse(srcscan.read(path))
            with self.subTest(srcscan.relative(path)):
                for _node, value in srcscan.string_constants(tree):
                    self.assertNotIn(value, WORDS)
                    self.assertNotIn(reported.FORMAT, value)
                    self.assertNotIn("reported.json", value)
                for entry in srcscan.imports(path):
                    self.assertNotEqual(entry.target, READER)
                for node in ast.walk(tree):
                    if isinstance(node, (ast.Import, ast.ImportFrom)):
                        self.assertNotIn("reported", [alias.name for alias in node.names])

    def test_the_watchers_report_never_carries_it(self):
        """The report file has one writer, the watcher, and Reported is not in it: a view attaches
        it for a person to read, and the watcher never computes it."""
        source = (srcscan.SRC / PACKAGE / "compat" / "report.py").read_text(encoding="utf-8")
        start = source.index("def build_report")
        end = source.index("\ndef ", source.index("def validate_report") + 1)
        self.assertNotIn("reported", source[start:end])


class BehaviourTests(unittest.TestCase):
    """The grid: every decision, under every counts file."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.bundled, _state = files.load_bundled()
        self.assertIsNotNone(self.bundled)
        self.sources = {
            "bundled": [("bundled", self.bundled, True), ("cache", None, False)],
            "bundled_and_cache": [("bundled", self.bundled, True), ("cache", refreshed(), True)],
            "expired_cache": [("bundled", self.bundled, True), ("cache", refreshed(), False)],
            "none": [("bundled", None, True), ("cache", None, False)],
        }

    def use(self, variant):
        """Put a counts file where the product reads it, or none."""
        path = self.root / variant / "reported.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        if VARIANTS[variant] is not None:
            path.write_bytes(VARIANTS[variant])
        reported._held.clear()
        return patch.object(reported, "BUNDLED", path)

    def decisions(self):
        """Everything the product decides from the registry, for every version, check set and source."""
        said = {}
        for version in VERSIONS:
            for check_name, checks in CHECK_SETS.items():
                for source_name, sources in self.sources.items():
                    capabilities = compat.evaluate(checks, version=version, sources=sources)
                    view = {"capabilities": capabilities, "engine": {"version": version}}
                    permits = {(name, tier, opt_in): compat.permits(view, name, tier=tier, opt_in=opt_in,
                                                                    engine_version=version,
                                                                    acknowledged_version=version)
                               for name in compat.CAPABILITIES for tier in compat.TIERS for opt_in in (False, True)}
                    said[(version, check_name, source_name)] = (
                        json.dumps(capabilities, sort_keys=True), compat.aggregate(capabilities),
                        compat.accepted_word(version, sources), sorted(permits.items(), key=repr))
        return said

    def watcher(self, variant):
        """What the watcher's gate says and writes, for each version it could be driving."""
        said = {}
        with self.use(variant), patch.object(probes, "api_checks", return_value={}):
            for version in (VERIFIED_HERE, CHECKED_HERE, NOTHING_SAID):
                paths = config.Paths(self.root / ("home-%s-%s" % (variant, version.split()[-1])))
                paths.ensure()
                exe = paths.home / "codex.exe"
                exe.write_bytes(b"MZ")
                backend = MagicMock(codex_exe=exe, engine_version=version)
                backend.engine_checks.return_value = {
                    "official_location": compat.PASS, "version_runs": compat.PASS, "queue_flags": compat.PASS,
                    "version": version, "signature": tuple(compatio._stamp(exe))}
                evaluator = compatio.Evaluator(paths, self.root / "codex", clock=lambda: 1790000000.0,
                                               source=MagicMock(home=self.root / "nowhere"))
                word = evaluator.tick(backend)
                written = json.loads(paths.compat_report_file.read_text(encoding="utf-8"))
                for moving in ("checked_at",):
                    written.pop(moving, None)
                written["engine"].pop("signature", None)
                written["engine"].pop("path_digest", None)
                said[version] = (word, json.dumps(written, sort_keys=True))
        return said

    def test_the_variants_do_say_different_things(self):
        """So the grid below compares something: what Reported itself says moves with the file."""
        answers = set()
        for variant in VARIANTS:
            with self.use(variant):
                answers.add(json.dumps(reported.lookup(NOTHING_SAID), sort_keys=True))
        self.assertEqual(len(answers), len(VARIANTS))

    def test_no_decision_moves_whatever_the_counts_say(self):
        found = {}
        for variant in VARIANTS:
            with self.use(variant):
                found[variant] = self.decisions()
        for variant in VARIANTS:
            with self.subTest(variant):
                self.assertEqual(found[variant], found["absent"])

    def test_the_watcher_says_and_writes_the_same_whatever_the_counts_say(self):
        found = {variant: self.watcher(variant) for variant in VARIANTS}
        for variant in VARIANTS:
            with self.subTest(variant):
                self.assertEqual(found[variant], found["absent"])
        self.assertNotIn("reported", found["worked"][NOTHING_SAID][1])

    def test_the_named_cases(self):
        with self.use("worked"):
            nothing = compat.evaluate(CHECK_SETS["pass"], version=NOTHING_SAID, sources=self.sources["bundled"])
            self.assertEqual(reported.lookup(NOTHING_SAID)["worked"], 1000)
            for name in compat.SEND_GATE:
                self.assertEqual(nothing[name]["state"], compat.COMPATIBLE)
            self.assertEqual(compat.accepted_word(NOTHING_SAID, self.sources["bundled"]), "structurally_compatible")
            failed_here = compat.evaluate(CHECK_SETS["queue_flags_fail"], version=VERIFIED_HERE,
                                          sources=self.sources["bundled"])
            self.assertEqual(failed_here["exact_thread_recovery"]["state"], compat.FAILED_HERE)
            self.assertEqual(compat.permits({"capabilities": failed_here}, "exact_thread_recovery",
                                            tier="conservative"), (False, "incompatible"))
            marked = compat.evaluate(CHECK_SETS["pass"], version=MARKED, sources=self.sources["bundled_and_cache"])
            self.assertEqual(marked["exact_thread_recovery"]["state"], compat.INCOMPATIBLE)
            self.assertEqual(compat.accepted_word(MARKED, self.sources["bundled_and_cache"]), "incompatible")
        with self.use("failed"):
            self.assertEqual(reported.lookup(VERIFIED_HERE)["failed"], 1000)
            verified = compat.evaluate(CHECK_SETS["pass"], version=VERIFIED_HERE, sources=self.sources["bundled"])
            self.assertEqual(verified["exact_thread_recovery"]["state"], compat.VERIFIED)
            self.assertEqual(compat.accepted_word(VERIFIED_HERE, self.sources["bundled"]), "verified")


if __name__ == "__main__":
    unittest.main()
