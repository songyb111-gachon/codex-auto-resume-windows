"""v0.6.26 final (live acceptance R2b): a report on the Codex app's package engine stays bound while the app is closed.

The watcher takes up the engine the app runs from its own package (`WindowsApps\\OpenAI.Codex_...\\app\\resources\\
codex.exe`, outside bin, signed by OpenAI; #58) and keeps driving it after the app closes, since the file is still
there. Every reader bound the watcher's report to an engine it could name: one in bin, or one the app main runs now
(compat/views.py `_binding_holds`). With the app closed the package engine was neither, so every reader - the
Dashboard, the doctor, the advanced edition's arming read the watcher itself makes - read every capability UNKNOWN
("engine_changed"), and every capability kept on that stands on Codex was held off until the app opened again.

A reader now also names the engines in the folders of the app's package installed for this user, as Windows' package
manager names those folders (win/kernel.py `package_roots`, codex/pairing.py `package_engines`): no process is started,
and the app need not run. The binding's other rules stand: the same file (path digest and stamp), an official engine
(signed by OpenAI), and UNKNOWN for a file replaced, gone, or not official.

Every package folder, process list and signature here is a stand-in.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

_HERE = str(Path(__file__).resolve().parent)
for entry in (str(Path(_HERE).parent / "src"), _HERE):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from codex_auto_resume import compat, compatio, config  # noqa: E402
from codex_auto_resume.codex import pairing  # noqa: E402
from codex_auto_resume.compat import probes, views  # noqa: E402
from codex_auto_resume.domain.errors import AdapterError  # noqa: E402
from codex_auto_resume.domain.ids import CODEX_APP_FAMILY  # noqa: E402
from codex_auto_resume.win import authenticode, kernel  # noqa: E402

PACKAGE_VERSION = "codex-cli 0.171.0-alpha.13"
BIN_VERSION = "codex-cli 0.167.0-alpha.4.1"


class Driven:
    """A backend the watcher drives: its engine checks pass and the app is closed (its last look found none)."""
    engine_verified = False

    def __init__(self, exe, version):
        self.codex_exe, self.engine_version = exe, version
        self.app_look, self.app_looked_at = "closed", time.monotonic()

    def engine_checks(self):
        status = self.codex_exe.stat()
        return {"official_location": compat.PASS, "version_runs": compat.PASS, "queue_flags": compat.PASS,
                "version": self.engine_version, "signature": (status.st_size, status.st_mtime_ns)}


class Source:
    """A source whose home does not exist: the schema checks cannot run."""
    home = "does-not-exist"


class PackageCase(unittest.TestCase):
    """A machine of stand-ins: bin holds one engine, the app's package (installed for this user) holds its own, signed
    by OpenAI; the app is closed (no process of it is listed). The watcher wrote its report on the package engine."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        local, native = self.root / "local", self.root / "pf"
        self.bin_exe = local / "OpenAI" / "Codex" / "bin" / "0123abcd" / "codex.exe"
        self.bin_exe.parent.mkdir(parents=True)
        self.bin_exe.write_bytes(b"MZ-bin")
        self.package_root = native / "WindowsApps" / ("OpenAI.Codex_26.1120.0.0_x64__" + pairing.CODEX_APP_PUBLISHER)
        self.package = self.package_root / "app" / "resources" / "codex.exe"
        self.package.parent.mkdir(parents=True)
        self.package.write_bytes(b"MZ-package-0.171")
        self.trampoline = self.package_root / "app" / "Codex.exe"
        self.trampoline.write_bytes(b"MZ-trampoline")
        self.signed = {os.path.normcase(str(self.package))}
        self.roots = [str(self.package_root)]
        self.rows = []
        self.processes_started = []
        environment = {"LOCALAPPDATA": str(local), "ProgramW6432": str(native)}
        stubs = [patch.dict(os.environ, environment),
                 patch.object(authenticode, "signer", side_effect=self.signer),
                 patch.object(pairing, "inventory", side_effect=lambda: [dict(row) for row in self.rows]),
                 patch.object(pairing, "package_roots", side_effect=self.package_roots, create=True),
                 patch("subprocess.Popen", side_effect=self.no_process)]
        for stub in stubs:
            stub.start()
            self.addCleanup(stub.stop)
        os.environ.pop(config.ENV_CODEX_EXE, None)
        pairing._OFFICIAL.clear()
        self.addCleanup(pairing._OFFICIAL.clear)
        self.paths = config.Paths(self.root / "home")
        self.paths.ensure()
        self.clock = [time.time()]
        self.evaluator = compatio.Evaluator(self.paths, self.root / "codex-home", source=Source(),
                                            clock=lambda: self.clock[0], product="0.6.26", log=lambda *_: None)

    def no_process(self, *args, **kwargs):
        self.processes_started.append(args)
        raise AssertionError("a reader started a process")

    def signer(self, path):
        if os.path.normcase(str(path)) in self.signed:
            return pairing.OPENAI_SIGNER
        raise AdapterError("unsigned")

    def package_roots(self, family):
        self.assertEqual(family, CODEX_APP_FAMILY)
        return list(self.roots)

    def written_on(self, exe):
        """The watcher's report on the engine at `exe`, as it writes it."""
        self.evaluator.tick(Driven(exe, BIN_VERSION if exe == self.bin_exe else PACKAGE_VERSION))
        return json.loads(Path(self.paths.compat_report_file).read_text(encoding="utf-8"))

    def read(self):
        return compatio.reader_view(self.paths, now=self.clock[0], settings={})

    def app_open(self, *engines):
        self.rows = [{"pid": 10, "parent": 1, "path": str(self.package_root / "app" / "ChatGPT.exe")}]
        self.rows += [{"pid": 20 + n, "parent": 10, "path": str(engine)} for n, engine in enumerate(engines)]


class AppClosedTests(PackageCase):
    def test_a_report_on_the_package_engine_reads_as_written_with_the_app_closed(self):
        report = self.written_on(self.package)
        self.assertEqual(report["engine"]["version"], PACKAGE_VERSION)
        view = self.read()
        self.assertEqual(view["status"], "ok", "the report on the package engine is unbound with the app closed")
        self.assertEqual(view["engine"]["version"], PACKAGE_VERSION)
        self.assertEqual(view["capabilities"], report["capabilities"])
        self.assertEqual(compatio.read_view(self.paths, now=self.clock[0])["status"], "ok")
        self.assertEqual(self.processes_started, [])

    def test_it_reads_the_same_with_the_app_open_and_after_it_closes_again(self):
        self.written_on(self.package)
        for running in (True, False, True, False):
            with self.subTest(running=running):
                if running:
                    self.app_open(self.package)
                else:
                    self.rows = []
                self.assertEqual(self.read()["status"], "ok")

    def test_a_report_on_bin_asks_nothing_of_the_package(self):
        self.written_on(self.bin_exe)
        asked = []
        with patch.object(pairing, "package_roots", side_effect=lambda family: asked.append(family) or [],
                          create=True):
            self.assertEqual(self.read()["status"], "ok")
        self.assertEqual(asked, [], "a report bound in bin looks no further")


class StillUnknownTests(PackageCase):
    """What the binding refused before, it refuses still: the report reads `engine_changed`, UNKNOWN for everything."""

    def assertUnbound(self, why):
        view = self.read()
        self.assertEqual(view["status"], "engine_changed", why)
        self.assertTrue(all(entry["state"] == compat.UNKNOWN for entry in view["capabilities"].values()), why)

    def test_the_file_replaced(self):
        self.written_on(self.package)
        self.package.write_bytes(b"MZ-package-0.172-and-longer")
        self.assertUnbound("a replaced engine still bound")

    def test_the_file_gone(self):
        self.written_on(self.package)
        self.package.unlink()
        self.assertUnbound("a vanished engine still bound")

    def test_the_package_uninstalled(self):
        self.written_on(self.package)
        self.roots = []
        self.assertUnbound("an engine of no installed package still bound")

    def test_a_signature_that_is_not_openai_s(self):
        self.written_on(self.package)
        self.signed = set()
        pairing._OFFICIAL.clear()
        self.assertUnbound("an engine not signed by OpenAI bound")

    def test_a_folder_the_package_manager_names_outside_windows_apps(self):
        elsewhere = self.root / "elsewhere" / ("OpenAI.Codex_26.1120.0.0_x64__" + pairing.CODEX_APP_PUBLISHER)
        exe = elsewhere / "app" / "resources" / "codex.exe"
        exe.parent.mkdir(parents=True)
        exe.write_bytes(b"MZ-elsewhere")
        self.signed.add(os.path.normcase(str(exe)))
        self.roots = [str(elsewhere)]
        self.written_on(exe)
        self.assertUnbound("an engine outside WindowsApps bound by the package's name")

    def test_the_package_s_update_trampoline_is_no_engine(self):
        self.signed.add(os.path.normcase(str(self.trampoline)))
        self.written_on(self.trampoline)
        self.assertUnbound("the app's Codex.exe in its main folder bound as an engine")

    def test_a_program_beside_the_engine_that_is_not_codex(self):
        other = self.package.parent / "node.exe"
        other.write_bytes(b"MZ-node")
        self.signed.add(os.path.normcase(str(other)))
        self.written_on(other)
        self.assertUnbound("a package program that is not codex.exe bound")


class PackageEnginesTests(PackageCase):
    def test_the_package_engines_are_named_from_the_folders_without_the_app(self):
        self.assertEqual([os.path.normcase(str(path)) for path in pairing.package_engines()],
                         [os.path.normcase(str(self.package))])

    def test_the_package_manager_is_asked_by_windows_own_calls_and_an_unknown_family_has_no_folder(self):
        """The real call, for a family no PC has: nothing, and no process."""
        self.assertEqual(kernel.package_roots("NoSuch.Package_0000000000000"), [])
        self.assertEqual(self.processes_started, [])

    def test_no_test_sees_this_pc_s_codex_package(self):
        """The guard every test run has (tests/no_real_codex.py) hides the app's package folders, as CI has none."""
        try:
            import no_real_codex
        except ImportError:
            self.skipTest("the guard is not installed in this run")
        if not no_real_codex.active():
            self.skipTest("the guard is not installed in this run")
        self.assertEqual(kernel.package_roots(CODEX_APP_FAMILY), [])
        self.assertEqual(kernel.package_roots(CODEX_APP_FAMILY.upper()), [])

    def test_a_package_manager_that_cannot_answer_names_nothing(self):
        with patch.object(pairing, "package_roots", side_effect=AdapterError("windows_required"), create=True):
            self.assertEqual(list(probes._package_engines()), [])


if __name__ == "__main__":
    unittest.main()
