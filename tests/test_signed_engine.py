"""v0.6.21 (#58): the Codex app running its engine from its own package, signed by OpenAI, is recovered with.

The reporter's app ran codex.exe from WindowsApps\\OpenAI.Codex_...\\app\\resources while a copy in bin passed every
check: discovery held the bin copy, the pairing found no server at it, every recovery waited and the watcher never
looked again, because the engine the app served from was not in bin. Here the watcher, the backend, the pairing and
discovery are real; the process list, the identities the pairing confirms and Windows' signature answer are stubs.
"""
from __future__ import annotations

from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import patch

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from test_engine_moved import TwoBuildsCase, key  # noqa: E402
from codex_auto_resume import config  # noqa: E402
from codex_auto_resume.codex import pairing, transport  # noqa: E402
from codex_auto_resume.compat import files, probes, views  # noqa: E402
from codex_auto_resume.domain.errors import AdapterError  # noqa: E402
from codex_auto_resume.runtime import app as runtime_app  # noqa: E402
from codex_auto_resume.win import authenticode  # noqa: E402


def package_engine(root, version):
    path = Path(root) / "WindowsApps" / ("OpenAI.Codex_%s_x64__2p2nqsd0c76g0" % version) / "app" / "resources" / "codex.exe"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"MZ-package-" + version.encode())
    return path.resolve()


class SignedEngineCase(TwoBuildsCase):
    """A watcher holding the one build in bin, which passes every check, and the app's package engine beside it,
    signed by OpenAI; every other file is unsigned, and `refused` maps a path to the refusal Windows gives it."""

    def setUp(self):
        super().setUp()
        shutil.rmtree(self.other.parent)
        self.package = package_engine(self.fixture.root, "26.1027.3384.0")
        self.signed, self.refused, self.signatures_read = {key(self.package)}, {}, []
        stub = patch.object(authenticode, "signer", side_effect=self.signer)
        stub.start()
        self.addCleanup(stub.stop)
        pairing._OFFICIAL.clear()
        self.addCleanup(pairing._OFFICIAL.clear)

    def compatible(self, path):
        transport.Backend(self.fixture.home.root, path)._compatible()

    def signer(self, path):
        self.signatures_read.append(key(path))
        if key(path) in self.refused:
            raise AdapterError(self.refused[key(path)])
        if key(path) in self.signed:
            return pairing.OPENAI_SIGNER
        raise AdapterError("unsigned")


class ReporterCaseTests(SignedEngineCase):
    def test_the_app_serving_from_its_signed_package_is_found_and_paired_with_no_restart(self):
        self.serve(self.package)
        self.assertIsNone(self.paired(), "the bin copy is no server of the app's")
        self.assertEqual({key(path) for path in self.first.served_elsewhere}, {key(self.package)})
        with self.assertLogs(self.app.logger, "INFO"):
            self.assertTrue(self.moved(0), "the watcher never looked again")
        self.assertEqual(self.app.backend().codex_exe, self.package)
        identity = self.paired()
        self.assertIsNotNone(identity, "the app's own server is not paired")
        self.assertEqual(identity["server"]["path"], str(self.package).lower())
        self.assertFalse(self.moved(1))
        self.assertIsNotNone(self.paired())

    def test_a_signed_build_that_fails_its_checks_is_looked_for_less_and_less_often(self):
        self.codex.failing.add(key(self.package))
        self.serve(self.package)
        self.assertIsNone(self.paired())
        self.assertTrue(self.moved(0))
        self.assertEqual(self.app.backend().codex_exe, self.first.codex_exe, "the build that passes is kept")
        self.assertIsNone(self.paired())
        self.assertFalse(self.moved(30), "looked for again on every tick")
        wait = runtime_app.ELSEWHERE_FIRST_WAIT
        self.assertTrue(self.moved(wait + 1))
        self.assertEqual(self.app.backend().codex_exe, self.first.codex_exe)
        self.assertIsNone(self.paired())
        self.codex.failing.clear()
        self.assertFalse(self.moved(wait + 2), "the wait did not grow")
        self.assertFalse(self.moved(wait * 3))
        self.assertTrue(self.moved(wait * 3 + 2))
        self.assertEqual(self.app.backend().codex_exe, self.package)
        self.assertIsNotNone(self.paired())

    def test_after_a_codex_update_the_new_package_folder_is_found(self):
        self.serve(self.package)
        self.paired()
        self.assertTrue(self.moved(0))
        self.assertEqual(self.app.backend().codex_exe, self.package)
        newer = package_engine(self.fixture.root, "26.1104.1000.0")
        self.signed.add(key(newer))
        shutil.rmtree(self.package.parent.parent.parent)
        self.serve(newer)
        self.assertTrue(self.moved(1), "the file gone is not looked for")
        self.assertEqual(self.app.backend().codex_exe, newer)
        self.assertIsNotNone(self.paired())


class EmptyBinTests(SignedEngineCase):
    def test_with_nothing_in_bin_the_engine_the_app_runs_is_driven(self):
        self.serve(self.package)
        self.first.codex_exe.unlink()
        self.assertTrue(self.moved(0))
        self.assertEqual(self.app.backend().codex_exe, self.package)
        self.assertIsNotNone(self.paired())
        backend, record = probes.discover(self.fixture.home.root)
        self.assertEqual(backend.codex_exe, self.package, "a reader with no watcher chooses as the watcher does")
        self.assertEqual({key(path) for path in record}, {key(self.package)})

    def test_with_the_app_closed_and_nothing_in_bin_nothing_is_found_as_before(self):
        self.first.codex_exe.unlink()
        for rows in ([], AdapterError("process_inventory_unavailable")):
            with self.subTest(rows=rows):
                self.rows = rows
                with self.assertRaisesRegex(config.ConfigError, "No official Codex desktop engine found"):
                    config.discover_codex_exe(None, lambda path: None, running=pairing.app_engines)


class NothingChangesTests(SignedEngineCase):
    def test_an_app_serving_from_bin_reads_no_signature(self):
        self.serve(self.first.codex_exe)
        self.assertIsNotNone(self.paired())
        self.assertFalse(self.moved(0))
        self.app._backend = None
        self.app.backend()
        self.assertIsNotNone(self.paired())
        self.assertEqual(self.signatures_read, [])

    def test_a_build_in_bin_that_passes_asks_nothing_more_when_nothing_was_seen(self):
        asked = []

        def running():
            asked.append(True)
            return [str(self.package)]
        self.assertEqual(config.discover_codex_exe(None, lambda path: None, running=running), self.first.codex_exe)
        self.assertEqual(asked, [])
        self.assertEqual(config.discover_codex_exe(None, lambda path: None, running=running, ask_app=True),
                         self.package)
        self.assertEqual(asked, [True], "one process list, not a second")


class NeverDrivenTests(SignedEngineCase):
    def test_a_child_that_is_not_signed_by_openai_is_never_driven(self):
        for refusal in ("unsigned", "wrong", "signature_invalid", "signature_untrusted", "signature_unreadable"):
            pairing._OFFICIAL.clear()
            self.signed.discard(key(self.package))
            if refusal == "wrong":
                self.refused.pop(key(self.package), None)
                stub = patch.object(authenticode, "signer", return_value="Microsoft Windows")
            else:
                self.refused[key(self.package)] = refusal
                stub = patch.object(authenticode, "signer", side_effect=self.signer)
            with self.subTest(refusal), stub:
                self.serve(self.package)
                self.assertIsNone(self.paired())
                self.assertEqual(self.app._served_elsewhere(), frozenset())
                self.assertFalse(self.moved(0))
                self.first.codex_exe.rename(self.first.codex_exe.with_suffix(".away"))
                try:
                    with self.assertRaises(config.ConfigError):
                        config.discover_codex_exe(None, self.compatible, running=pairing.app_engines)
                finally:
                    self.first.codex_exe.with_suffix(".away").rename(self.first.codex_exe)
        self.assertIs(self.app.backend(), self.first)

    def test_a_named_engine_passes_by_its_signature_and_is_refused_without_it(self):
        self.assertEqual(config.discover_codex_exe(str(self.package), self.compatible), self.package)
        unsigned = self.fixture.root / "named" / "codex.exe"
        unsigned.parent.mkdir()
        unsigned.write_bytes(b"MZ")
        with self.assertRaisesRegex(AdapterError, "unsupported_codex_location"):
            config.discover_codex_exe(str(unsigned), self.compatible)


class ReaderTests(SignedEngineCase):
    """The watcher's report names the engine it drives by a digest of its path: a reader binds it to the app's
    signed engine too, so compatibility reads as it did in bin rather than "engine changed"."""

    def report_on(self, path):
        return {"engine": {"found": True, "path_digest": files.path_digest(path), "signature": files._signature(path)}}

    def test_a_report_on_the_apps_signed_engine_still_binds(self):
        self.serve(self.package)
        self.assertTrue(views._binding_holds(self.report_on(self.package)))
        self.rows = []
        self.assertFalse(views._binding_holds(self.report_on(self.package)), "bound with no app to say so")
        self.serve(self.package)
        unsigned = self.fixture.root / "unsigned" / "codex.exe"
        unsigned.parent.mkdir()
        unsigned.write_bytes(b"MZ")
        self.serve(unsigned)
        self.assertFalse(views._binding_holds(self.report_on(unsigned)))

    def test_a_report_on_a_build_in_bin_reads_no_process_list(self):
        self.serve(self.package)
        listed = self.listings
        self.assertTrue(views._binding_holds(self.report_on(self.first.codex_exe)))
        self.assertEqual(self.listings, listed)
        self.assertEqual(self.signatures_read, [])


if __name__ == "__main__":
    unittest.main()
