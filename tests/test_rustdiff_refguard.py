"""No reference run reaches this PC's Codex or its processes (tests/rustdiff/refguard.py, Integration 10).

Twice on 2026-11-27 a Rust-port seat's reference run (the v0.6.26 tag's own Python) fell into core's real engine discovery
and started this PC's installed codex.exe. Every harness that starts a tag's package - refpython.command / script_command
(and so reference.run, advref.run and popen), tests/released.py's run - now runs refguard's program first. Held here by
running the tag's own code through each of them: core's process lookups, pairing's engine lookups and the advanced
edition's engine discovery refuse, the engine's path points where no codex.exe is, discovery asks no engine at all, a
test's own stand-in still wins, and only the file whose subject is the live process table may lift the lookups. And by
the source: no harness file starts a tag's package on `sys.executable` by hand.

Nothing here reaches the network, the registry, a real home or a real process: every lookup is refused before it runs
(the live-processes case only checks that the lookup is not the refusal; it calls nothing).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tests")]

import released  # noqa: E402
from rustdiff import advref, refguard, reference, refpython  # noqa: E402

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
RUSTDIFF = ROOT / "tests" / "rustdiff"
TAG = "v0.6.26"

# What the reference's own code does with every lookup and with discovery; one JSON line.
PROBE = r'''
import json, os, sys
from codex_auto_resume import config
from codex_auto_resume.win import inventory, kernel
from codex_auto_resume.codex import pairing, transport
from codex_auto_resume import windows
out = {"engine": os.environ.get("CODEX_AUTO_RESUME_CODEX_EXE"), "refused": {}, "asked": []}
out["engine_exists"] = bool(out["engine"]) and os.path.exists(out["engine"])
def refused(name, call):
    try:
        call()
    except Exception as exc:
        out["refused"][name] = [type(exc).__name__, "refused" in str(exc)]
    else:
        out["refused"][name] = None
refused("kernel.processes_named", lambda: kernel.processes_named(["codex.exe"]))
refused("kernel.process_identity", lambda: kernel.process_identity(os.getpid()))
refused("inventory.resource_users", lambda: inventory.resource_users(sys.executable))
refused("pairing.processes_named", lambda: pairing.processes_named(["codex.exe"]))
refused("pairing.process_identity", lambda: pairing.process_identity(os.getpid()))
refused("pairing.resource_users", lambda: pairing.resource_users(sys.executable))
refused("pairing.app_engines", lambda: pairing.app_engines())
refused("transport.resource_users", lambda: transport.resource_users(sys.executable))
refused("windows.resource_users", lambda: windows.resource_users(sys.executable))
def compatible(path):
    out["asked"].append(str(path))
refused("discover", lambda: config.discover_codex_exe(None, compatible, running=pairing.app_engines, ask_app=True,
                                                       ask_app_if_none=True))
os.environ.pop("CODEX_AUTO_RESUME_CODEX_EXE")
refused("discover_unset", lambda: config.discover_codex_exe(None, compatible, running=pairing.app_engines, ask_app=True,
                                                             ask_app_if_none=True))
if "advanced" in sys.argv[1:]:
    from codex_auto_resume_advanced.codex import inuse
    refused("inuse.backend", lambda: inuse.backend(None))
pairing.processes_named = lambda names, families=(): ["a stand-in"]
out["stand_in"] = pairing.processes_named(["codex.exe"])
print(json.dumps(out))
'''

# A stand-in set on core's kernel before a module that imports it by name is loaded is kept, not refused.
EARLY = r'''
import json
from codex_auto_resume.win import kernel
kernel.processes_named = lambda names, families=(): ["early stand-in"]
from codex_auto_resume.codex import pairing
print(json.dumps({"pairing": pairing.processes_named(["codex.exe"])}))
'''

# The live process table asked for by name: the lookups are the tag's own (not called here), discovery still refuses.
LIVE = r'''
import json, sys
from codex_auto_resume.win import kernel
from codex_auto_resume.codex import pairing
out = {"kernel": getattr(kernel.processes_named, "__car_refguard__", None),
       "pairing": getattr(pairing.processes_named, "__car_refguard__", None)}
if "advanced" in sys.argv[1:]:
    from codex_auto_resume_advanced.codex import inuse
    out["inuse"] = getattr(inuse.backend, "__car_refguard__", None)
print(json.dumps(out))
'''

LOOKED_UP = ("kernel.processes_named", "kernel.process_identity", "inventory.resource_users", "pairing.processes_named",
             "pairing.process_identity", "pairing.resource_users", "pairing.app_engines", "transport.resource_users",
             "windows.resource_users")


def have_tag() -> bool:
    return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "-q", "--verify", "refs/tags/%s" % TAG],
                          capture_output=True, creationflags=NO_WINDOW).returncode == 0


def have_zip() -> bool:
    saved = os.environ.pop("CI", None)
    try:
        refpython.bundled_zip()
        return True
    except RuntimeError:
        return False
    finally:
        if saved is not None:
            os.environ["CI"] = saved


class Guarded:
    """What every harness's reference process must answer; `start(script, *arguments)` is the harness's."""

    def check_probe(self, answer: dict, advanced: bool):
        self.assertEqual(answer["engine"], refguard.NO_CODEX)
        self.assertFalse(answer["engine_exists"])
        for name in LOOKED_UP:
            with self.subTest(lookup=name):
                # app_engines re-raises the inventory's failure in its own words (process_inventory_unavailable)
                self.assertEqual(answer["refused"][name], ["AdapterError", name != "pairing.app_engines"])
        # discovery with the engine's path pointing nowhere: ConfigError, and no engine was ever asked about
        self.assertEqual(answer["refused"]["discover"][0], "ConfigError")
        # and with no path at all (a scratch LOCALAPPDATA, the app's engines refused): still none asked
        self.assertEqual(answer["refused"]["discover_unset"][0], "ConfigError")
        self.assertEqual(answer["asked"], [])
        if advanced:
            self.assertEqual(answer["refused"]["inuse.backend"], ["AdapterError", True])
        self.assertEqual(answer["stand_in"], ["a stand-in"])


@unittest.skipUnless(have_tag(), "%s is not in this checkout" % TAG)
class ReferenceRuns(Guarded, unittest.TestCase):
    """reference.run and advref.run on this interpreter (`system`) and, where a build cache has it, the bundled runtime."""

    def setUp(self):
        patcher = mock.patch.dict(os.environ, {refguard.ENGINE_VARIABLE: r"C:\a-runner's-own\codex.exe"})
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in (refpython.VARIABLE, refpython.RESOLVED_VARIABLE, refguard.VARIABLE):
            os.environ.pop(name, None)
        refpython._CACHE.clear()
        self.addCleanup(refpython._CACHE.clear)
        old = reference.TAG
        reference.TAG = TAG
        self.addCleanup(setattr, reference, "TAG", old)

    def runtimes(self):
        yield "system"
        if have_zip():
            yield "bundled"

    def answer(self, done) -> dict:
        self.assertEqual(done.returncode, 0, done.stderr[-3000:])
        return json.loads(done.stdout.decode("utf-8").strip().splitlines()[-1])

    def test_core_reference_refuses_every_lookup_and_finds_no_engine(self):
        for runtime in self.runtimes():
            with self.subTest(runtime=runtime):
                refpython.select(runtime)
                self.check_probe(self.answer(reference.run(PROBE, tag=TAG)), advanced=False)

    def test_advanced_reference_refuses_the_engine_discovery_too(self):
        for runtime in self.runtimes():
            with self.subTest(runtime=runtime):
                refpython.select(runtime)
                self.check_probe(self.answer(advref.run(PROBE, "advanced", tag=TAG)), advanced=True)

    def test_a_long_script_through_script_command_is_guarded_too(self):
        refpython.select("system")
        padded = PROBE + "\n" + "#" * 9000 + "\n"
        self.check_probe(self.answer(advref.run(padded, "advanced", tag=TAG)), advanced=True)

    def test_a_stand_in_set_before_a_later_import_is_kept(self):
        refpython.select("system")
        self.assertEqual(self.answer(reference.run(EARLY, tag=TAG)), {"pairing": ["early stand-in"]})

    def test_only_the_named_variable_lifts_the_lookups_and_never_the_engine_discovery(self):
        refpython.select("system")
        with tempfile.TemporaryDirectory(prefix="refguard-live-") as profile:
            environment = advref.environment(Path(profile), TAG)
            environment[refguard.VARIABLE] = refguard.LIVE
            done = subprocess.run(reference.command(LIVE, "advanced", paths=advref.trees(TAG)), capture_output=True,
                                  env=environment, cwd=profile, creationflags=NO_WINDOW, timeout=300)
        self.assertEqual(self.answer(done), {"kernel": None, "pairing": None, "inuse": "inuse.backend"})

    def test_the_runners_own_engine_path_never_reaches_the_reference_and_a_test_may_hand_one(self):
        with tempfile.TemporaryDirectory(prefix="refguard-env-") as profile:
            self.assertEqual(reference.scratch_environment(Path(profile))[refguard.ENGINE_VARIABLE], refguard.NO_CODEX)
            handed = reference.scratch_environment(Path(profile), CODEX_AUTO_RESUME_CODEX_EXE=r"C:\stand-in\codex.exe")
            self.assertEqual(handed[refguard.ENGINE_VARIABLE], r"C:\stand-in\codex.exe")
            unset = reference.scratch_environment(Path(profile), CODEX_AUTO_RESUME_CODEX_EXE=None)
            self.assertNotIn(refguard.ENGINE_VARIABLE, unset)


@unittest.skipUnless(have_tag(), "%s is not in this checkout" % TAG)
class ReleasedRuns(unittest.TestCase):
    """tests/released.py's run (the released-tree tests' harness, on this interpreter)."""

    def test_released_run_refuses_every_lookup_and_finds_no_engine(self):
        with mock.patch.dict(os.environ, {refguard.ENGINE_VARIABLE: r"C:\a-runner's-own\codex.exe"}):
            answer = released.run(TAG, PROBE)
        Guarded.check_probe(self, answer, advanced=False)


class TheSource(unittest.TestCase):
    """Every start of a tag's package goes through the guarded harness."""

    def test_every_reference_argv_runs_the_guard_first(self):
        with mock.patch.dict(os.environ):
            refpython.select("system")
            try:
                for argv in (refpython.command("print(1)", paths=["x"]), refpython.script_command("x.py", paths=["x"]),
                             reference.command("print(1)", paths=["x"])):
                    self.assertTrue(refguard.guarded(argv), argv)
                    self.assertEqual(argv[1:4], ["-X", "utf8", "-c"])
                    self.assertTrue(argv[4].startswith(refguard.PROGRAM), argv[4][:200])
            finally:
                refpython._CACHE.clear()

    def test_no_harness_file_starts_a_tags_package_on_sys_executable(self):
        offenders = []
        for path in sorted(list(RUSTDIFF.rglob("*.py")) + [ROOT / "tests" / "released.py"]):
            text = path.read_text(encoding="utf-8")
            if not re.search(r"released\.package\(|advref\.package\(|advref\.trees\(|\btrees\(", text):
                continue
            # docstrings and scripts in triple quotes blanked line for line, so the numbers stay the file's
            code = re.sub(r'(?s)("""|\'\'\').*?\1', lambda found: "\n" * found.group(0).count("\n"), text)
            for number, line in enumerate(code.splitlines(), 1):
                if line.lstrip().startswith("#"):
                    continue
                # a stand-in process that never imports the product (a sleeper, a file holder) is not a reference
                if re.search(r'sys\.executable,\s*"-c",\s*"import (time|sys,\s*time)', line):
                    continue
                if re.search(r"(run|Popen)\(\s*\[\s*sys\.executable", line):
                    offenders.append("%s:%d" % (path.relative_to(ROOT).as_posix(), number))
        # released.run starts this interpreter on purpose (the released-tree tests' own Python) - with the guard's boot
        allowed = {"tests/released.py"}
        self.assertEqual(sorted(each for each in offenders if each.split(":")[0] not in allowed), [])
        self.assertIn("refguard.boot(", (ROOT / "tests" / "released.py").read_text(encoding="utf-8"))

    def test_only_the_advanced_proxys_test_lanes_start_without_the_guard(self):
        users = sorted(path.relative_to(ROOT).as_posix() for path in RUSTDIFF.rglob("*.py")
                       if path.name not in ("refguard.py", "refpython.py")
                       and re.search(r"(?s)\b(script_command|command|boot)\((?:[^()]|\([^()]*\))*\bguard\s*=\s*False",
                                     path.read_text(encoding="utf-8")))
        self.assertEqual(users, ["tests/rustdiff/advproxy/ledger.py"])

    def test_only_the_live_process_diff_lifts_the_lookups(self):
        users = sorted(path.relative_to(ROOT).as_posix() for path in list(RUSTDIFF.rglob("*.py")) + list((ROOT / "tests").glob("*.py"))
                       if path.name not in ("refguard.py", "test_rustdiff_refguard.py")
                       and re.search(r"refguard\.LIVE|live-processes|CODEX_AR_REFGUARD", path.read_text(encoding="utf-8")))
        self.assertEqual(users, ["tests/rustdiff/platform_live_diffs.py"])


if __name__ == "__main__":
    unittest.main()
