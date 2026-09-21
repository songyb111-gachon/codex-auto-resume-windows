"""The Compatibility Registry's files, its local checks, and the watcher's side of it.

Everything runs against the test's own temporary directories: a fake engine directory under
a fake %LOCALAPPDATA%, a simulated Codex home with the real schema, and a scratch
installation home. `codex --version` and `codex queue --help` are answered from a script;
no Codex process starts, nothing is fetched, and no real per-user state is read.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from codexsim import CodexHome  # noqa: E402
from test_compat_characterization import (HELP_CHANGED, T1, FakeCodex, Fixture)  # noqa: E402
from codex_auto_resume import compat, compatio, config, machine, windows  # noqa: E402
from codex_auto_resume.source import LocalSource  # noqa: E402
from codex_auto_resume.store import Store  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
# Every document here is newer than the bundled baseline, whatever sequence the data on main
# has reached: a literal would turn into a rollback the day the data passed it.
BASE = compatio.load_bundled()[0]["sequence"]


def registry_document(sequence=None, *, engines=(), advisories=(), published="2026-09-18T00:00:00Z",
                      expires="2027-06-01T00:00:00Z", min_product="0.6.4", **extra):
    sequence = BASE + 4 if sequence is None else sequence
    value = {"format": compat.FORMAT, "sequence": sequence, "published_at": published,
             "expires_at": expires, "min_product": min_product, "requires_signature": False,
             "engines": list(engines), "advisories": list(advisories)}
    value.update(extra)
    return value


def advisory(capabilities=("exact_thread_recovery",), low="0.0.0", identifier="CAR-2026-0100"):
    return {"id": identifier, "match": {"version_gte": low}, "capabilities": list(capabilities),
            "state": "INCOMPATIBLE", "reason": "queue_interface_changed"}


class Scratch(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.paths = config.Paths(self.root / "home")
        self.paths.ensure()
        self.now = time.time()

    def write_document(self, value, name="codex_compat.json") -> Path:
        path = self.root / "downloads" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")
        return path


class ImportTests(Scratch):
    def test_a_valid_document_becomes_the_cache(self):
        result = compatio.import_document(self.paths, self.write_document(registry_document()),
                                          origin="main", now=self.now)
        self.assertEqual(result, {"imported": True, "reason": None, "sequence": BASE + 4, "cache": "ok"})
        envelope = json.loads(self.paths.compat_cache_file.read_text(encoding="utf-8"))
        self.assertEqual(envelope["format"], compat.CACHE_FORMAT)
        self.assertEqual(envelope["origin"], "main")
        self.assertNotIn("sha256", envelope, "no digest that would need canonical re-encoding")
        cache = compatio.read_cache(self.paths.compat_cache_file, now=self.now)
        self.assertEqual((cache["state"], cache["sequence"]), ("ok", BASE + 4))

    def test_a_refusal_leaves_the_existing_cache_exactly_as_it_was(self):
        compatio.import_document(self.paths, self.write_document(registry_document(BASE + 6)), now=self.now)
        before = self.paths.compat_cache_file.read_bytes()
        cases = [
            (registry_document(BASE + 5), "rollback"),
            (registry_document(BASE + 7, min_product="9.0.0"), "from_newer_product"),
            (registry_document(BASE + 7, advisories=[dict(advisory(), state="VERIFIED")]), "range_cannot_grant"),
            (registry_document(BASE + 7, requires_signature=True), "signature_required"),
            (registry_document(BASE + 7, published="2031-01-01T00:00:00Z", expires="2032-01-01T00:00:00Z"),
             "from_the_future"),
            ({"format": "codex-auto-resume-compat/2"}, "unknown_format"),
        ]
        for value, reason in cases:
            with self.subTest(reason=reason):
                result = compatio.import_document(self.paths, self.write_document(value), now=self.now)
                self.assertEqual((result["imported"], result["reason"]), (False, reason))
                self.assertEqual(self.paths.compat_cache_file.read_bytes(), before)

    def test_what_is_refused_before_it_is_parsed(self):
        big = self.root / "big.json"
        big.write_bytes(b" " * (compat.MAX_DOCUMENT_BYTES + 1))
        self.assertEqual(compatio.import_document(self.paths, big)["reason"], "too_large")
        text = self.write_document(registry_document(), name="codex_compat.txt")
        self.assertEqual(compatio.import_document(self.paths, text)["reason"], "not_a_json_file")
        self.assertEqual(compatio.import_document(self.paths, self.root / "missing.json")["reason"],
                         "unreadable")
        broken = self.root / "broken.json"
        broken.write_bytes(b'{"format": "codex-auto-resume-compat/1", "format": "again"}')
        self.assertEqual(compatio.import_document(self.paths, broken)["reason"], "duplicate_key")
        self.assertFalse(self.paths.compat_cache_file.exists())

    def test_an_older_document_than_the_bundled_baseline_is_a_rollback(self):
        bundled, _ = compatio.load_bundled()
        older = registry_document(bundled["sequence"] - 1) if bundled["sequence"] > 0 else None
        if older is None:
            self.skipTest("the baseline is at sequence 0")
        self.assertEqual(compatio.import_document(self.paths, self.write_document(older))["reason"],
                         "rollback")

    def test_a_tampered_cache_is_ignored_and_kept(self):
        compatio.import_document(self.paths, self.write_document(registry_document()), now=self.now)
        envelope = json.loads(self.paths.compat_cache_file.read_text(encoding="utf-8"))
        envelope["document"]["advisories"] = [dict(advisory(), state="VERIFIED")]
        self.paths.compat_cache_file.write_text(json.dumps(envelope), encoding="utf-8")
        self.assertEqual(compatio.read_cache(self.paths.compat_cache_file, now=self.now)["state"], "rejected")
        self.assertTrue(self.paths.compat_cache_file.exists(), "never deleted: a person can look at it")
        for garbage in (b"", b"{", b"[]", b'{"format": "codex-auto-resume-compat-cache/1"}'):
            self.paths.compat_cache_file.write_bytes(garbage)
            self.assertEqual(compatio.read_cache(self.paths.compat_cache_file, now=self.now)["state"],
                             "rejected", garbage)

    def test_a_cache_older_than_a_newer_bundled_baseline_is_set_aside(self):
        compatio.import_document(self.paths, self.write_document(registry_document(BASE + 4)), now=self.now)
        newer = compat.validate_document(registry_document(BASE + 8))
        cache = compatio.read_cache(self.paths.compat_cache_file, bundled=newer, now=self.now)
        self.assertEqual(cache["state"], "superseded")
        self.assertIsNone(cache["document"])

    def test_a_crash_mid_write_leaves_the_old_file_and_no_temporary(self):
        compatio.import_document(self.paths, self.write_document(registry_document(BASE + 4)), now=self.now)
        before = self.paths.compat_cache_file.read_bytes()
        with patch.object(compatio.os, "replace", side_effect=OSError("power cut")):
            result = compatio.import_document(self.paths, self.write_document(registry_document(BASE + 5)),
                                              now=self.now)
        self.assertEqual(result["reason"], "write_failed")
        self.assertEqual(self.paths.compat_cache_file.read_bytes(), before)
        self.assertEqual(list(self.paths.state_dir.glob("compat-cache.*.tmp")), [])

    def test_uninstall_owns_both_files(self):
        compatio.import_document(self.paths, self.write_document(registry_document()), now=self.now)
        compatio.write_json_atomic(self.paths.compat_report_file, {"x": 1}, "compatibility.")
        owned = self.paths.owned_state_files()
        self.assertIn(self.paths.compat_cache_file, owned)
        self.assertIn(self.paths.compat_report_file, owned)


class SourceCheckTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.home = CodexHome(Path(folder.name) / "codex")

    def checks(self):
        return compatio.source_checks(LocalSource(self.home.root))

    def test_the_real_schema_passes(self):
        (self.home.root / "thread-writer-locks").mkdir()
        self.assertEqual(set(self.checks().values()), {compat.PASS})

    def test_a_missing_column_is_a_failure_and_a_missing_database_is_not(self):
        with self.home._db("thread_history_1.sqlite") as db:
            db.execute("ALTER TABLE thread_items RENAME COLUMN item_type TO kind")
        checks = self.checks()
        self.assertEqual(checks["history_schema"], compat.FAIL)
        self.assertEqual(checks["state_schema"], compat.PASS)
        (self.home.root / "queue_1.sqlite").unlink()
        self.assertEqual(self.checks()["queue_schema"], compat.UNAVAILABLE)

    def test_a_missing_projection_table(self):
        with self.home._db("thread_history_1.sqlite") as db:
            db.execute("DROP TABLE thread_history_projection_state")
        self.assertEqual(self.checks()["projection_table"], compat.FAIL)

    def test_absent_directories_are_not_failures(self):
        shutil.rmtree(self.home.root / "sessions")
        checks = self.checks()
        self.assertEqual(checks["sessions_directory"], compat.NOT_APPLICABLE)
        self.assertEqual(checks["lock_directory"], compat.NOT_APPLICABLE)

    def test_no_codex_home_at_all(self):
        self.assertEqual(set(compatio.source_checks(LocalSource(self.home.root / "nowhere")).values()),
                         {compat.UNAVAILABLE})
        self.assertEqual(set(compatio.source_checks(MagicMock()).values()), {compat.UNAVAILABLE})

    def test_the_checks_read_and_write_nothing_else(self):
        """Schema only, through the read-only connection: Codex's files are untouched."""
        before = {path.name: (path.read_bytes(), path.stat().st_mtime_ns)
                  for path in self.home.root.glob("*.sqlite")}
        self.checks()
        after = {path.name: (path.read_bytes(), path.stat().st_mtime_ns)
                 for path in self.home.root.glob("*.sqlite")}
        self.assertEqual(before, after)
        self.assertEqual(sorted(p.name for p in self.home.root.iterdir()),
                         sorted(["sessions"] + list(before)))


class EvaluatorTests(unittest.TestCase):
    """The watcher's side, on the characterization fixture."""

    def fixture(self, **codex):
        return Fixture(self, codex=FakeCodex(**codex) if codex else FakeCodex(version="codex-cli 0.155.0"))

    def report(self, fixture):
        return compatio.read_report(fixture.paths)[0]

    def test_the_watcher_writes_a_report_bound_to_its_engine(self):
        fixture = self.fixture()
        fixture.backend()
        report = self.report(fixture)
        self.assertEqual(report["overall"], "structurally_compatible")
        self.assertEqual(report["acting"], "structurally_compatible")
        self.assertEqual(report["engine"]["version"], "codex-cli 0.155.0")
        self.assertEqual(report["engine"]["path_digest"], compatio.path_digest(fixture.exe))
        self.assertEqual(report["engine"]["signature"], list(compatio._stamp(fixture.exe)))
        self.assertEqual(report["data"]["bundled"], "ok")
        text = fixture.paths.compat_report_file.read_text(encoding="utf-8")
        for leak in (str(fixture.exe), str(fixture.local), os.environ.get("USERNAME") or "\0", T1):
            self.assertNotIn(leak, text)
        view = compatio.read_view(fixture.paths)
        self.assertEqual((view["status"], view["overall"]), ("ok", "structurally_compatible"))

    def test_readers_refuse_a_report_about_a_binary_that_changed_or_vanished(self):
        fixture = self.fixture()
        fixture.backend()
        fixture.exe.write_bytes(b"MZ-a-newer-build-of-another-size")
        self.assertEqual(compatio.read_view(fixture.paths)["status"], "engine_changed")
        fixture.exe.unlink()
        view = compatio.read_view(fixture.paths)
        self.assertEqual(view["status"], "engine_changed")
        self.assertEqual({entry["state"] for entry in view["capabilities"].values()}, {compat.UNKNOWN})

    def test_a_report_older_than_a_ticking_watcher_leaves_it_is_stale(self):
        fixture = self.fixture()
        fixture.backend()
        later = time.time() + compat.REPORT_MAX_AGE + 5
        self.assertEqual(compatio.read_view(fixture.paths, now=later)["status"], "stale")

    def test_a_damaged_or_hand_edited_report_is_unknown_not_rendered(self):
        fixture = self.fixture()
        fixture.backend()
        path = fixture.paths.compat_report_file
        good = json.loads(path.read_text(encoding="utf-8"))
        for damage in (lambda r: r["capabilities"]["usage_probe"].update(reason="send everything now"),
                       lambda r: r.update(format="something-else"),
                       lambda r: r["engine"].update(version="\u202eevil")):
            bad = json.loads(json.dumps(good))
            damage(bad)
            path.write_text(json.dumps(bad), encoding="utf-8")
            self.assertEqual(compatio.read_view(fixture.paths)["status"], "invalid")
        path.write_bytes(b"{" * (compat.MAX_REPORT_BYTES + 1))
        self.assertEqual(compatio.read_view(fixture.paths)["status"], "invalid")
        path.unlink()
        self.assertEqual(compatio.read_view(fixture.paths)["status"], "absent")

    def test_a_vanished_binary_is_reported_while_the_gate_keeps_its_verdict(self):
        """F2 at the surface, without moving a decision: the report says the engine is gone,
        the watcher says it is still acting on the one it started with."""
        fixture = self.fixture()
        fixture.backend()
        fixture.exe.unlink()
        fixture.settle()
        report = self.report(fixture)
        self.assertEqual(report["overall"], "unknown")
        self.assertEqual(report["capabilities"]["exact_thread_recovery"]["reason"], "local_check_unavailable")
        self.assertEqual(report["acting"], "structurally_compatible")
        self.assertEqual(fixture.app.engine_state(), "structurally_compatible")

    def test_f1_a_refused_engine_is_reported_incompatible_in_the_heartbeat(self):
        fixture = self.fixture(version="codex-cli 0.199.0", help_text=HELP_CHANGED)
        with self.assertRaises(config.ConfigError):
            fixture.app.backend()
        fixture.settle()
        fixture.app._heartbeat(fixture.store, "session", time.time(), False)
        self.assertEqual(fixture.store.watcher_status()["engine_state"], "incompatible")
        report = self.report(fixture)
        self.assertEqual(report["capabilities"]["exact_thread_recovery"]["reason"], "local_check_failed")
        self.assertEqual(report["checks"]["queue_flags"], compat.FAIL)
        self.assertTrue(report["engine"]["found"])
        # Every surface that reads the heartbeat can now say why nothing is recovered.
        overlays = machine.overlays({"state": "waiting_poll"}, watcher={"engine_state": "incompatible"})
        self.assertIn("compatibility_blocked", overlays)

    def test_remote_verified_never_rescues_an_engine_that_lost_the_queue_flags(self):
        fixture = self.fixture(version="codex-cli 0.199.0", help_text=HELP_CHANGED)
        claim = {"state": "VERIFIED", "evidence": ["docs/evidence/loaded-thread-delivery.json"]}
        compatio.import_document(fixture.paths, self._document_file(fixture, registry_document(
            engines=[{"version": "codex-cli 0.199.0",
                      "capabilities": {"exact_thread_recovery": claim, "engine_present": claim}}])),
            now=time.time())
        with self.assertRaises(config.ConfigError):
            fixture.app.backend()
        fixture.settle()
        # v0.6.7: the data vouches for this exact build, so the failure is this machine's - FAILED_HERE -
        # and it holds every send exactly as INCOMPATIBLE does.
        self.assertEqual(fixture.app.engine_state(), "failed_here")
        self.assertEqual(self.report(fixture)["capabilities"]["exact_thread_recovery"]["state"],
                         compat.FAILED_HERE)

    def _document_file(self, fixture, value):
        path = Path(fixture.folder.name) / "download.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_an_imported_advisory_blocks_new_sends_and_touches_nothing_sent(self):
        """A new case - no cache existed before v0.6.5 - so this is where registry data is
        allowed to change a decision, and only ever towards not sending."""
        fixture = self.fixture()
        backend = fixture.backend()
        engine = fixture.engine(backend)
        fixture.interruption_due(engine)
        result = compatio.import_document(fixture.paths, self._document_file(
            fixture, registry_document(advisories=[advisory()])), now=time.time())
        self.assertTrue(result["imported"])
        fixture.settle()
        self.assertEqual(fixture.app.engine_state(), "incompatible")
        engine.tick()
        self.assertEqual(fixture.sim.send_calls, [])
        row = fixture.record()
        self.assertEqual(row["state"], "waiting_for_app")
        self.assertEqual(machine.decode_gates(row["gate_eval"])["engine_compatible"],
                         ("BLOCK", "engine_incompatible"))

    def test_a_state_change_in_either_direction_never_re_arms_anything(self):
        fixture = self.fixture()
        backend = fixture.backend()
        engine = fixture.engine(backend)
        fixture.interruption_due(engine)
        fixture.sim.default_outcome = "unknown"          # the queue process timed out
        engine.tick()
        self.assertEqual(fixture.record()["state"], "submission_unknown")
        self.assertEqual(len(fixture.sim.send_calls), 1)
        path = self._document_file(fixture, registry_document(advisories=[advisory()]))
        compatio.import_document(fixture.paths, path, now=time.time())
        fixture.settle()
        for _ in range(3):
            fixture.now += 3600
            engine.tick()
        self.assertEqual(fixture.record()["state"], "submission_unknown")
        fixture.paths.compat_cache_file.unlink()          # and back to compatible
        fixture.settle()
        self.assertEqual(fixture.app.engine_state(), "structurally_compatible")
        for _ in range(3):
            fixture.now += 3600
            engine.tick()
        self.assertEqual(fixture.record()["state"], "submission_unknown")
        self.assertEqual(len(fixture.sim.send_calls), 1, "an uncertain submission is never resent")

    def test_a_failing_evaluation_fails_closed_and_never_ends_the_watcher(self):
        fixture = self.fixture()
        fixture.backend()
        with patch.object(compatio.Evaluator, "tick", side_effect=RuntimeError("bug")):
            fixture.app._compatibility_tick()
        self.assertEqual(fixture.app.engine_state(), "unknown")

    def test_it_recomputes_only_when_something_changed(self):
        fixture = self.fixture()
        fixture.backend()
        evaluator = fixture.app._compat
        calls = []
        real = compatio.source_checks
        with patch.object(compatio, "source_checks", side_effect=lambda s: calls.append(1) or real(s)):
            fixture.settle()
            fixture.settle()
            self.assertEqual(calls, [], "nothing changed, nothing re-read")
            fixture.exe.write_bytes(b"MZ-changed")
            fixture.settle()
            self.assertEqual(len(calls), 1)
            evaluator._last_at -= compat.RECOMPUTE_SECONDS + 1
            fixture.settle()
            self.assertEqual(len(calls), 2)

    def test_one_log_line_per_change_and_it_is_content_free(self):
        fixture = self.fixture()
        said = []
        fixture.app.logger = MagicMock(info=lambda *args: said.append(args[0] % args[1:] if len(args) > 1 else args[0]))
        fixture.backend()
        fixture.settle()
        lines = [line for line in said if line.startswith("compatibility:")]
        self.assertEqual(len(lines), 1)
        self.assertIn("codex-cli 0.155.0", lines[0])
        self.assertNotIn(str(fixture.root if hasattr(fixture, "root") else fixture.folder.name), lines[0])


def iso(moment) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(moment))


class AcceptedBackend:
    """A backend the watcher accepted: its three engine checks passed on this binary."""

    def __init__(self, exe: Path, version: str):
        self.codex_exe, self.engine_version = exe, version

    def engine_checks(self):
        return {"official_location": compat.PASS, "version_runs": compat.PASS,
                "queue_flags": compat.PASS, "version": self.engine_version,
                "signature": tuple(compatio._stamp(self.codex_exe))}


class TimeTests(Scratch):
    """Time moves a cache's standing - it expires, or a clock that was behind catches up -
    without the file changing, and a watcher that runs for weeks has to notice. Time may
    only ever withhold trust: no clock, however wrong, lifts a restriction."""

    VERSION = "codex-cli 0.155.0"

    def setUp(self):
        super().setUp()
        self.exe = self.root / "codex.exe"
        self.exe.write_bytes(b"MZ")
        guard = patch.object(compatio, "api_checks", return_value={})
        guard.start()
        self.addCleanup(guard.stop)

    def import_trust(self, *, published, expires, advisories=()):
        claim = {"state": "VERIFIED", "evidence": ["docs/evidence/loaded-thread-delivery.json"]}
        value = registry_document(BASE + 8, published=iso(published), expires=iso(expires),
                                  engines=[{"version": self.VERSION,
                                            "capabilities": {"engine_present": claim,
                                                             "exact_thread_recovery": claim}}],
                                  advisories=list(advisories))
        result = compatio.import_document(self.paths, self.write_document(value), now=self.now)
        self.assertTrue(result["imported"], result)

    def evaluator(self, clock):
        return compatio.Evaluator(self.paths, self.root / "codex", clock=lambda: clock[0],
                                  source=MagicMock(home=self.root / "nowhere"))

    def on_disk(self):
        report, status = compatio.read_report(self.paths, now=self.now + 30 * 86400)
        self.assertEqual(status, "ok")
        return report

    def test_a_running_watcher_stops_trusting_a_cache_the_moment_it_expires(self):
        self.import_trust(published=self.now - 86400, expires=self.now + 3600)
        clock = [self.now]
        evaluator = self.evaluator(clock)
        backend = AcceptedBackend(self.exe, self.VERSION)
        self.assertEqual(evaluator.tick(backend), "verified")
        self.assertEqual(self.on_disk()["data"]["cache"], "ok")
        clock[0] = self.now + 2 * 3600                    # expires_at has passed; the file has not changed
        self.assertEqual(evaluator.tick(backend), "structurally_compatible",
                         "expired VERIFIED data must stop counting in the gate's word")
        report = self.on_disk()
        self.assertEqual((report["data"]["cache"], report["data"]["expired"]), ("expired", True))
        self.assertEqual((report["acting"], report["overall"]),
                         ("structurally_compatible", "structurally_compatible"))
        self.assertEqual(report["capabilities"]["exact_thread_recovery"]["reason"], "local_checks_passed")

    def test_a_clock_behind_keeps_the_restrictions_and_withholds_the_trust(self):
        self.import_trust(published=self.now - 3600, expires=self.now + 90 * 86400,
                          advisories=[advisory(("usage_probe",))])
        clock = [self.now - 3 * 86400]                    # set back after a correct import
        cache = compatio.read_cache(self.paths.compat_cache_file, now=clock[0])
        self.assertEqual(cache["state"], "from_the_future")
        self.assertIsNotNone(cache["document"], "its restrictions are still in force")
        evaluator = self.evaluator(clock)
        backend = AcceptedBackend(self.exe, self.VERSION)
        self.assertEqual(evaluator.tick(backend), "structurally_compatible")
        report = self.on_disk()
        self.assertEqual(report["data"]["cache"], "from_the_future")
        self.assertEqual(report["capabilities"]["usage_probe"]["state"], compat.INCOMPATIBLE)
        self.assertEqual(report["capabilities"]["usage_probe"]["source"], "cache")
        clock[0] = self.now                               # the clock is put right
        self.assertEqual(evaluator.tick(backend), "verified")
        report = self.on_disk()
        self.assertEqual(report["data"]["cache"], "ok")
        self.assertEqual(report["capabilities"]["usage_probe"]["state"], compat.INCOMPATIBLE)

    def test_the_bundled_baseline_ignores_the_clock(self):
        bundled, _ = compatio.load_bundled()
        behind = bundled["published_at"] - 40 * 86400
        document, state = compatio.load_bundled(now=behind)
        self.assertEqual(state, "ok")
        self.assertEqual(document, bundled)
        restricting = self.write_document(registry_document(
            3, published=iso(self.now), engines=[{"version": self.VERSION, "capabilities": {
                "exact_thread_recovery": {"state": "INCOMPATIBLE", "reason": "queue_interface_changed"}}}]))
        document, state = compatio.load_bundled(restricting, now=self.now - 40 * 86400)
        self.assertEqual(state, "ok")
        self.assertEqual(compat.evidence_for("exact_thread_recovery", self.VERSION,
                                             [("bundled", document, True)])[0], compat.INCOMPATIBLE)

    def test_the_gates_word_for_a_verified_build_is_the_same_everywhere(self):
        """What status, doctor and the start-up log say about an accepted engine comes from
        the same data the gate reads - the bundled baseline and the cache in force."""
        self.assertEqual(compatio.engine_word(self.paths, self.VERSION, now=self.now),
                         "structurally_compatible")
        self.import_trust(published=self.now - 86400, expires=self.now + 3600)
        self.assertEqual(compatio.engine_word(self.paths, self.VERSION, now=self.now), "verified")
        self.assertEqual(compatio.engine_word(self.paths, "codex-cli 0.155.1", now=self.now),
                         "structurally_compatible")
        self.assertEqual(compatio.engine_word(self.paths, self.VERSION, now=self.now + 7200),
                         "structurally_compatible", "expired trust is not trust")
        clock = [self.now]
        self.assertEqual(self.evaluator(clock).tick(AcceptedBackend(self.exe, self.VERSION)),
                         compatio.engine_word(self.paths, self.VERSION, now=self.now))


class LiveTests(unittest.TestCase):
    def test_a_live_check_needs_no_watcher_and_writes_nothing(self):
        fixture = Fixture(self, codex=FakeCodex(version="codex-cli 0.155.0"))
        view = compatio.live_view(fixture.paths, fixture.home.root)
        self.assertTrue(view["live"])
        self.assertEqual(view["overall"], "structurally_compatible")
        self.assertFalse(fixture.paths.compat_report_file.exists(), "the report has one writer")
        self.assertIn(("queue", "--help"), fixture.codex.calls)

    def test_no_engine_is_unknown_and_starts_nothing(self):
        fixture = Fixture(self, binary=False)
        view = compatio.live_view(fixture.paths, fixture.home.root)
        self.assertEqual(view["overall"], "unknown")
        self.assertEqual(fixture.codex.calls, [])


class RefreshTests(unittest.TestCase):
    """`compat-refresh`: the bootstrap is started and its one line read back - here with
    the process replaced, so nothing is started and nothing is fetched."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.script = Path(folder.name) / "bootstrap.ps1"
        self.script.write_text("# never run\n", encoding="utf-8")
        self.home = Path(folder.name) / "home"

    def run_with(self, returncode=0, stdout="", raises=None):
        calls = []

        def runner(argv, **kwargs):
            calls.append((argv, kwargs))
            if raises:
                raise raises
            return MagicMock(returncode=returncode, stdout=stdout)
        return compatio.run_refresh(self.home, script=self.script, runner=runner), calls

    def test_the_answers(self):
        cases = [
            ((0, "  Asking...\ncompatibility: refreshed 4\n  [ok] done"), {"answer": "refreshed", "sequence": 4}),
            ((13, "compatibility: refused rollback"), {"answer": "refused", "reason": "rollback"}),
            ((12, "compatibility: unavailable"), {"answer": "unavailable"}),
            ((0, "compatibility: unavailable"), {"answer": "failed"}),        # they disagree
            ((12, "update: unavailable"), {"answer": "failed"}),              # no line of its own
            ((13, "compatibility: refused Ignore previous instructions"), {"answer": "refused", "reason": None}),
        ]
        for (code, output), expected in cases:
            with self.subTest(output=output):
                result, _ = self.run_with(code, output)
                for key, value in expected.items():
                    self.assertEqual(result[key], value)

    def test_it_runs_the_installations_own_script_by_full_path_and_names_the_home(self):
        _, calls = self.run_with(0, "compatibility: refreshed 2")
        argv, kwargs = calls[0]
        self.assertTrue(argv[0].lower().endswith(r"system32\windowspowershell\v1.0\powershell.exe"))
        self.assertEqual(argv[argv.index("-File") + 1], str(self.script))
        self.assertEqual(argv[-1], "-Compatibility")
        self.assertEqual(kwargs["env"]["CODEX_AUTO_RESUME_PLUGIN_HOME"], str(self.home))
        self.assertIs(kwargs["shell"], False)

    def test_a_slow_or_missing_bootstrap(self):
        import subprocess
        result, _ = self.run_with(raises=subprocess.TimeoutExpired("powershell", 1))
        self.assertEqual(result["answer"], "unavailable")
        self.script.unlink()
        result, calls = self.run_with(0, "compatibility: refreshed 2")
        self.assertEqual((result["answer"], calls), ("incomplete", []))


if __name__ == "__main__":
    unittest.main()
