"""Review 4 (branch car-v0627-review4): differences between the reference and the Rust crates that no other diff feeds.

Each class reproduces one finding of outputs/plans/v0627-rust/REVIEW-int4.md and FAILS on car-v0627-rust at 76baf21dd;
a fixer makes it pass by changing the product crate, never this file's expectation (the reference's answer is the
expectation). Scratch folders only; nothing here reads or writes the real install, the real Codex home or the registry.

* LegacySkillLines   - car-legacy (`runtime\\python.exe`) refuses the command lines every published skill tells Codex to
                       run (`plugin_setup.py status`, `enable`, `pending`, `cancel <uuid>`, ...): legacy_lines.py never
                       collects skills/codex-auto-resume/SKILL.md.
* OwnsHomeJson       - car-config's `owns_home()` reads runtime.json with the strict serde reader: a file Python's
                       json.loads takes (NaN, a lone surrogate escape, nesting past 128) is not ours to Rust.
* DisplayNameText    - car-platform's `addremove::display_name` writes a number as its literal and refuses a list,
                       NaN or a lone surrogate, where the reference writes `str(value)`; and trims by Rust's White_Space.
* CodexHomeStrip     - car-platform's `registry_reads::codex_home` trims by Rust's White_Space, the reference by
                       `str.strip()` (U+001C..U+001F are spaces to Python).
* RealpathDangling,
  ConfigRealpathDangling - car-platform's `paths::realpath` (every object name's identity) and car-config's `winpath::realpath`, through a junction
                       whose target is gone: 3.13's `os.path.realpath` follows it (`_readlink_deep`), Rust keeps it.
* HomeLockSharing    - car-platform's `homelock::Held` opens the watcher's lock files sharing delete (std's default), so
                       install.ps1's Remove-HomeLocks deletes them under a running Rust watcher; the reference's cannot be.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from rustdiff import core, reference
from rustdiff.diffs_leaves_config import ENV, ConfigBase
from rustdiff.platform_diffs import Base as PlatformBase, ref
from rustdiff.platform_registry_diffs import REGISTRY_SCRIPT

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
RECORD: list[str] = []


# ------------------------------------------------------------------------------------------ 1. car-legacy and skills

def skill_commands(tag: str) -> list[list[str]]:
    """The `plugin_setup.py <command>` words a tag's skill tells Codex to run (its Commands table)."""
    text = subprocess.run(["git", "-C", str(core.ROOT), "show", "%s:skills/codex-auto-resume/SKILL.md" % tag],
                          capture_output=True, creationflags=NO_WINDOW, check=True).stdout.decode("utf-8")
    words = []
    for line in text.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 2 and cells[1].startswith("`") and cells[1].endswith("`"):
            words.append(cells[1].strip("`").replace("<thread-uuid>", "0a1b2c3d-0001-7000-8000-00000000000a").split())
    return words


class LegacySkillLines(unittest.TestCase):
    """Every published skill says: `%USERPROFILE%\\.codex-auto-resume\\runtime\\python.exe
    %USERPROFILE%\\.codex-auto-resume\\app\\scripts\\plugin_setup.py <command>`. A Codex plugin copy of any earlier
    version keeps that skill, and the Rust archive ships it again (payload/app/skills); car-legacy answers each such
    line with 2 (refused), so "show status" through Codex ends in "not one of the command lines earlier versions used"."""

    def test_every_skill_command_reaches_the_core(self):
        built = core.target_dir() / "release" / "python.exe"
        # The stub core (car-bin's car-core-proof.exe, as build/rust_legacy_bootstraps.py's PROOF_CORE): since S6.2b the
        # release codex-auto-resume.exe is the real core, whose setup and uninstall would act on this PC.
        core_stub = core.target_dir() / "release" / "car-core-proof.exe"
        for program in (built, core_stub):
            if not program.is_file():
                self.skipTest("not built: %s (cargo build --release --manifest-path rust/Cargo.toml)" % program)
        commands = skill_commands(reference.TAG)
        self.assertGreaterEqual(len(commands), 10, "the skill's Commands table was not read")
        with tempfile.TemporaryDirectory(prefix="review4-legacy-") as scratch:
            home = Path(scratch) / "install home"
            (home / "runtime").mkdir(parents=True)
            (home / "app" / "bin").mkdir(parents=True)
            (home / "app" / "scripts").mkdir(parents=True)
            shutil.copy2(built, home / "runtime" / "python.exe")
            # The stub core: it changes nothing and ends with 3, so an accepted line is told from a refused one (2).
            shutil.copy2(core_stub, home / "app" / "bin" / "codex-auto-resume.exe")
            refused = []
            for words in commands:
                done = subprocess.run([str(home / "runtime" / "python.exe"), str(home / "app" / "scripts" / "plugin_setup.py"),
                                       *words], capture_output=True, creationflags=NO_WINDOW, timeout=60,
                                      env=reference.scratch_environment(Path(scratch)), cwd=scratch)
                if done.returncode == 2:
                    refused.append(" ".join(words))
        RECORD.append("car-legacy: %d skill command lines of %s, %d refused" % (len(commands), reference.TAG, len(refused)))
        self.assertEqual(refused, [], "car-legacy refuses the command lines the published skill tells Codex to run")


# ------------------------------------------------------------------------------------------ 2. owns_home's runtime.json

class OwnsHomeJson(ConfigBase):
    """config.Paths.owns_home() reads runtime.json with `json.loads`, which takes NaN, Infinity, a lone surrogate escape
    and any nesting below the recursion limit; car-config reads it with car_machine::json::from_str (serde_json), which
    refuses each, so an installation the reference calls its own is not one to Rust (uninstall and the installer's sweep
    are gated on it)."""

    def test_runtime_json_python_reads(self):
        def tree(root: Path):
            nested = "[" * 200 + "]" * 200
            for name, extra in {"record-nan": "NaN", "record-infinity": "-Infinity",
                                "record-surrogate": '"\\ud800"', "record-deep": nested}.items():
                (root / name).mkdir()
                home = json.dumps(str(root / name))
                (root / name / "runtime.json").write_text('{"home": %s, "x": %s}' % (home, extra), encoding="utf-8")
        template = [["paths.report", "@/" + home, "@/root", ENV, "@/", False, []]
                    for home in ("record-nan", "record-infinity", "record-surrogate", "record-deep")]
        expected = self.pair("owns-json", template, tree=tree)
        self.assertTrue(all(result["ok"]["owns_home"] for result in expected), "the reference owns each of the four")
        RECORD.append("owns_home: runtime.json with NaN, -Infinity, a lone surrogate and 200 levels: equal to the tag's")


# ------------------------------------------------------------------------------------------ 3. display_name

class DisplayNameText(PlatformBase):
    """addremove.display_name is `str(manifest["interface"]["displayName"]).strip()` over `json.loads`."""

    def test_display_name_as_str(self):
        bodies = ['{"interface": {"displayName": 1.50}}', '{"interface": {"displayName": 1e5}}',
                  '{"interface": {"displayName": -0}}', '{"interface": {"displayName": ["Codex"]}}',
                  '{"interface": {"displayName": {"a": 1}}}', '{"interface": {"displayName": NaN}}',
                  '{"interface": {"displayName": "Codex \\ud83d"}}', '{"interface": {"displayName": "Codex\\u001f"}}',
                  '{"interface": {"displayName": "Codex"}, "deep": %s}' % ("[" * 200 + "]" * 200)]
        files = []
        for index, body in enumerate(bodies):
            path = self.scratch / ("manifest-%d.json" % index)
            path.write_text(body, encoding="utf-8")
            files.append(str(path))
        script = ("import json,sys\nfrom pathlib import Path\nfrom codex_auto_resume import addremove\n"
                  "p=json.load(sys.stdin)\nsys.stdout.write(json.dumps([addremove.display_name(Path(x)) for x in p]))")
        want = ref(script, files, self.profile)
        with self.probe() as probe:
            got = [probe.ask("display_name", path=path) for path in files]
        differs = [(body, a, b) for body, a, b in zip(bodies, want, got) if a != b]
        RECORD.append("display_name: %d manifests, %d differ" % (len(bodies), len(differs)))
        self.assertEqual(differs, [], "display_name differs from the tag's str(value).strip()")


# ------------------------------------------------------------------------------------------ 4. CODEX_HOME's strip

class CodexHomeStrip(PlatformBase):
    def test_codex_home_strips_as_python(self):
        for text in ("D:\\codex\x1f", "\x1cD:\\codex", "D:\\codex\x1e\x1d"):
            scenario = {"seed": [["HKCU", "Environment", {"CODEX_HOME": [text, 1]}]], "steps": [["codex_home"]]}
            want = ref(REGISTRY_SCRIPT, scenario, self.profile)["results"]
            with self.probe() as probe:
                got = probe.ask("registry", **scenario)["results"]
            self.assertEqual(got, want, "CODEX_HOME %r" % text)


# ------------------------------------------------------------------------------------------ 5. realpath through a link

class RealpathDangling(PlatformBase):
    def test_realpath_through_a_dangling_junction(self):
        """3.13's `_getfinalpathname_nonstrict` follows a link it cannot open (`_readlink_deep`); car-platform's
        `realpath` strips the name and keeps it as written. A junction needs no privilege (`mklink /J`)."""
        place = self.scratch / "dangling"
        place.mkdir(exist_ok=True)
        subprocess.run(["cmd", "/c", "mklink", "/J", str(place / "link"), str(place / "gone")], capture_output=True,
                       creationflags=NO_WINDOW, check=True)
        cases = [str(place / "link"), str(place / "link" / "below")]
        script = "import json,os,sys\nsys.stdout.write(json.dumps([os.path.realpath(p) for p in json.load(sys.stdin)]))"
        want = ref(script, cases, self.profile)
        with self.probe() as probe:
            got = [probe.ask("realpath", text=case) for case in cases]
        self.assertEqual(got, want)



class ConfigRealpathDangling(ConfigBase):
    """The same through car-config's own `winpath::realpath` (`Paths` resolves every home with it)."""

    def test_a_home_below_a_dangling_junction(self):
        def tree(root: Path):
            subprocess.run(["cmd", "/c", "mklink", "/J", str(root / "link"), str(root / "gone")], capture_output=True,
                           creationflags=NO_WINDOW, check=True)
        template = [["paths.build", "@/link", "@/root", ENV, "@/", False], ["paths.build", "@/link/home", "@/root", ENV, "@/", False]]
        # The junction's target never exists, so the scratch folder's removal has nothing to follow.
        self.pair("dangling", template, tree=tree)


# ------------------------------------------------------------------------------------------ 6. the home lock's sharing

HOLD_AND_DELETE = r'''
import json, os, sys
from pathlib import Path
from codex_auto_resume.win.homelock import HomeLock
request = json.load(sys.stdin)
answers = {}
with HomeLock(request["home"], request["base"]):
    for name in sorted(os.listdir(request["base"])):
        try:
            os.remove(os.path.join(request["base"], name))
            answers[name.split("-")[0] if name.startswith("id-") else "path"] = "deleted"
        except OSError:
            answers[name.split("-")[0] if name.startswith("id-") else "path"] = "held"
sys.stdout.write(json.dumps(answers))
'''


class HomeLockSharing(PlatformBase):
    r"""The watcher's home lock files are held so that they cannot be deleted while held: build/install/install.ps1's
    Remove-HomeLocks (uninstall -Purge) deletes every `homes\*.lock` it can and counts on "a lock another installation's
    watcher holds is open and cannot be deleted". The reference opens them with os.open (the C runtime shares read and
    write, never delete); car-platform's `Held::take` opens with std's OpenOptions, which shares delete too, so the file
    is deleted under a Rust watcher and the next watcher of that home makes a new one and locks it as well."""

    def test_a_held_lock_file_cannot_be_deleted(self):
        home = self.scratch / "codex home"
        home.mkdir(exist_ok=True)
        ours, theirs = self.scratch / "homes-ref", self.scratch / "homes-rust"
        want = ref(HOLD_AND_DELETE, {"home": str(home), "base": str(ours)}, self.profile)
        with self.probe() as probe:
            taken = probe.ask("hold", kind="homelock", action="take", userprofile=str(self.profile), codex_home=str(home), base=str(theirs))
            self.assertEqual(taken["result"], {"ok": True}, taken)
            got = {}
            for name in sorted(os.listdir(theirs)):
                try:
                    os.remove(theirs / name)
                    got["id" if name.startswith("id-") else "path"] = "deleted"
                except OSError:
                    got["id" if name.startswith("id-") else "path"] = "held"
            probe.ask("hold", kind="homelock", action="release", userprofile=str(self.profile))
        self.assertEqual(want, {"id": "held", "path": "held"})
        self.assertEqual(got, want, "a lock file car-platform holds can be deleted")
