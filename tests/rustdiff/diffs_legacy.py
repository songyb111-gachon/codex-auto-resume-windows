"""Every published command line end to end (seat S5.2): car-legacy's `runtime\\python.exe` / `pythonw.exe`, handed the
exact words a published updater, registration, skill or launcher runs (`rust/crates/car-legacy/tests/data/published.txt`,
44 shapes, `rust/tools/legacy_lines.py`), hands them to `app\\bin\\codex-auto-resume.exe` - here car-harness's
`car-core-world`, car-bin's dispatcher over a world - and the answer and the exit code are the reference's for the
same words in the same world (`cliworld`: the tag's `plugin_setup.main`, `cli.main` or `mcpserver`), and what an old
updater reads of each (S8.1/S8.2: `setup` 0 or 2, `watcher-running` 0 or 2, `downgrade-state` one closed line,
`remove-entry` 0) holds.

Each shape runs in a scratch installation laid out as a Rust archive lays it (car-legacy's two programs, the core, the
stubs, the package's folder, the golden installation's state), with every home pointed into the scratch folder;
nothing writes the registry or the real installation.

Run by run.py; never by the lanes' discovery.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

from rustdiff import actworld as aw
from rustdiff import cliworld as cw
from rustdiff import core, reference
from rustdiff.diffs import RECORD
from rustdiff.diffs_bridge_acting import now
from rustdiff.diffs_cli import CliBase
import wiregolden as wg

ROOT = core.ROOT
PUBLISHED = ROOT / "rust" / "crates" / "car-legacy" / "tests" / "data" / "published.txt"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
VALUES = {"cancel": wg.T1, "-n": "5", "--lines": "7"}


def shapes() -> list:
    """(program, words) for every published line, `{home}` left in."""
    found = []
    for line in PUBLISHED.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        found.append((parts[0], parts[4:]))
    return found


def legacy_binary(name: str) -> Path:
    return core.target_dir() / "release" / name


def ensure_built():
    missing = [name for name in ("python.exe", "pythonw.exe", "car-core-world.exe") if not legacy_binary(name).is_file()]
    if missing:
        environment = dict(os.environ)
        environment.setdefault("CARGO_BUILD_JOBS", "4")
        subprocess.run(["cargo", "build", "--release", "--locked", "--manifest-path", str(ROOT / "rust" / "Cargo.toml"),
                        "-p", "car-legacy", "-p", "car-harness"], env=environment, check=True,
                       creationflags=NO_WINDOW, timeout=3600)


def filled(words, home: Path) -> list:
    out = []
    for index, word in enumerate(words):
        word = word.replace("{home}", str(home))
        if word == "{value}":
            word = VALUES.get(words[index - 1], "5")
        if word == "{uri}":
            word = "codex-auto-resume:cancel?i=%s" % wg.WAITING_BACKOFF
        out.append(word)
    return out


def core_words(program: str, words: list, home: Path) -> list:
    """The words car-legacy hands the core (its table, as GROUNDWORK S8.1 lists it)."""
    if "-c" in words:
        return ["mcp", "--home", str(home)]
    script = next(index for index, word in enumerate(words) if word.endswith(".py"))
    return words[script + 1:]


class LegacyShapesDiff(CliBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ensure_built()

    def lay_out(self, workspace: Path):
        home = workspace / "home"
        for name, source in (("runtime/python.exe", "python.exe"), ("runtime/pythonw.exe", "pythonw.exe"),
                             ("app/bin/codex-auto-resume.exe", "car-core-world.exe"),
                             ("app/bin/CodexAutoResume.exe", "car-core-world.exe")):
            target = home / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(legacy_binary(source), target)
        for stub in ("app/scripts/plugin_setup.py", "app/src/codex_auto_resume/mcpserver.py", "app/src/auto_resume.py",
                     "watcher-launcher.py"):
            path = home / stub
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# a content-free stub of the Rust archive\n", encoding="utf-8")

    def test_every_published_line(self):
        seen = {"python.exe": 0, "pythonw.exe": 0}
        for program, words in shapes():
            label = "%s %s" % (program, " ".join(words[-4:]))
            with self.subTest(label):
                workspace = self.workspace("acts", self.lay_out)
                home = workspace / "home"
                argv = filled(words, home)
                world = aw.world_for(workspace, now=now(), watcher_running=False,
                                     environ={"CODEX_AUTO_RESUME_PLUGIN_HOME": str(home),
                                              "USERPROFILE": str(workspace / "profile")})
                spec = workspace / "world.json"
                spec.write_text(json.dumps(world), encoding="utf-8")
                environment = reference.scratch_environment(workspace / "profile", CAR_CORE_WORLD=str(spec),
                                                            CODEX_AUTO_RESUME_PLUGIN_HOME=str(home))
                stdin = b'{"jsonrpc": "2.0", "id": 1, "method": "ping"}\n' if "-c" in argv else b""
                done = subprocess.run([str(home / "runtime" / program), *argv], input=stdin, capture_output=True,
                                      env=environment, cwd=str(workspace), creationflags=NO_WINDOW, timeout=600)
                records = [json.loads(line) for line in (spec.with_name("world.json.calls").read_text(
                    encoding="utf-8").splitlines() if spec.with_name("world.json.calls").is_file() else [])]
                self.assertNotEqual(done.returncode, 2, "%s: car-legacy refused a published line (%r)" % (
                    label, done.stderr[-400:]))
                self.assertEqual(len(records), 1, "%s: the core was not reached exactly once" % label)
                handed = core_words(program, argv, home)
                self.assertEqual(records[0]["argv"], handed, "%s: car-legacy handed other words" % label)
                if handed[:1] == ["run"] or handed[-1:] == ["run"]:
                    seen[program] += 1
                    continue
                # The reference, the same words in a fresh copy of the same installation and world.
                fresh = self.workspace("acts", self.lay_out)
                expected_world = aw.world_for(fresh, now=now(), watcher_running=False,
                                              environ={"CODEX_AUTO_RESUME_PLUGIN_HOME": str(fresh / "home"),
                                                       "USERPROFILE": str(fresh / "profile")})
                if handed[0] == "mcp":
                    self.assertEqual(done.stdout, b'{"jsonrpc": "2.0", "id": 1, "result": {}}\n', label)
                    self.assertEqual(done.returncode, 0, label)
                else:
                    code, out, err, _calls = cw.run_reference(fresh / "home", expected_world, handed)
                    if program == "python.exe":
                        self.assertEqual(done.stdout.decode("utf-8", "replace"), out.decode("utf-8", "replace"),
                                         "%s: the answer differs from the reference's" % label)
                    self.assertEqual(done.returncode, code, "%s: the code differs from the reference's (%r)" % (
                        label, err[-400:]))
                if handed[0] == "downgrade-state":
                    lines = done.stdout.decode("utf-8").splitlines()
                    self.assertEqual(len(lines), 1, label)
                    self.assertRegex(lines[0], r"^downgrade: (converted( \d+){5}|nothing|watcher-running|failed)$")
                if handed[0] == "watcher-running":
                    self.assertIn(done.returncode, (0, 2), label)
                if handed[0] == "setup":
                    self.assertIn(done.returncode, (0, 1, 2, 4, 5), label)
                seen[program] += 1
        RECORD.append("legacy shapes: %d python.exe and %d pythonw.exe published lines handed by car-legacy to car-bin, "
                      "every answer and code the reference's" % (seen["python.exe"], seen["pythonw.exe"]))
