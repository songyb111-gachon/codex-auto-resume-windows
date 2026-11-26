"""S6.1, car-watcher: the launcher's logic (scripts/watcher_launcher.py of the tag) and car-watcher's `launcher`.

`LAUNCHER` loads the tag's own launcher file from a scratch folder beside its runtime.json and runs its `main` with the
scenario's world: the installed edition's plug answering P13 (a script, or NULL), the supervised children's exit codes
(`subprocess.Popen` a recorder: nothing is started), the watcher's own exit code (`cli.main` a stand-in), the stop
probe of AFTER_STOP, the environment's two marks, and a clock of its own. The same scenario goes to `car-harness
serve` as `watcher.launcher`, whose world answers the same way over car-watcher's `launcher::guarded`, the plug's
answers checked by car-policy's own `Guarded`.

Equal: the exit code; every question put to the plug, with its facts; every child started and every relaunch, by their
arguments after the program (the program itself is the host's image in Rust and an interpreter with the remote-debug
option in Python, both retired by D8); every sleep; every watcher run with its command; and the files - launcher.log
and errors.log (each line's time stamp aside), unsupervised.txt.

What D8 retired is not compared: the remote-debug relaunch, and the Python choice (`_on_chosen` and the rest); no
scenario has a chosen.json, so the reference never reaches them.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from rustdiff import core, diffs, reference

LAUNCHER = r'''
import importlib.util, json, os, sys, types
from pathlib import Path
from codex_auto_resume import edition
from codex_auto_resume.domain.plug import DEFER, Alternative, Plug
from codex_auto_resume.runtime import app as app_mod

launcher_source = Path(sys.argv[1])
scenarios = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
real_pid, real_exe = os.getpid, sys.executable
os.getpid = lambda: 4242
out = []
for number, sc in enumerate(scenarios):
    here = Path(sc["here"])
    copy = here / "watcher-launcher.py"
    copy.write_bytes(launcher_source.read_bytes())
    spec = importlib.util.spec_from_file_location("watcher_launcher_%d" % number, copy)
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    calls, asked = [], []
    clock = {"t": 1000.0}

    def sleep(seconds):
        calls.append(["sleep", float(seconds)])
        clock["t"] += seconds
    launcher.time = types.SimpleNamespace(sleep=sleep, monotonic=lambda: clock["t"],
                                          strftime=lambda form: "[0000-00-00 00:00:00] ")
    for name in (launcher.RELAUNCH_MARK, launcher.AFTER_STOP_MARK, "CODEX_HOME"):
        os.environ.pop(name, None)
    os.environ.update(sc.get("env") or {})
    os.environ["CODEX_HOME"] = sc["script"].get("codex_home", "")
    script = sc["script"]
    answers, children, codes, probes = (list(script.get(key, [])) for key in ("answers", "children", "codes", "probes"))

    class ScriptPlug(Plug):
        def supervise(self, facts):
            asked.append(dict(facts))
            word = answers.pop(0) if answers else "defer"
            if word == "raise":
                raise RuntimeError("the plug failed")
            if word == "defer":
                return DEFER
            try:
                return Alternative(word)
            except ValueError:
                return word

        def supervise_held(self):
            return script.get("held")
    plug = None if script.get("plug") == "null" else ScriptPlug()
    edition.plug = lambda paths: plug

    def run_watcher(argv):
        calls.append(["watcher", list(argv[3:])])
        return codes.pop(0) if codes else 0
    sys.modules["codex_auto_resume.cli"] = types.SimpleNamespace(main=run_watcher)

    class Child:
        started = 0

        def __init__(self, argv, **options):
            calls.append(["child", list(argv[4:])])
            answer = children.pop(0) if children else 0
            if answer == "oserror":
                raise OSError("cannot start")
            self.pid, self.code = 4242 + Child.started, answer
            Child.started += 1

        def wait(self, timeout=None):
            return self.code

    def popen(argv, **options):
        if "env" in options:
            calls.append(["relaunch", list(argv[4:])])
            if script.get("relaunch_fails"):
                raise OSError("cannot start")
            return None
        return Child(argv, **options)
    launcher.subprocess = types.SimpleNamespace(Popen=popen, DEVNULL=-3, CREATE_NO_WINDOW=0x08000000,
                                                DETACHED_PROCESS=8, CREATE_NEW_PROCESS_GROUP=0x200)
    sys.modules["subprocess"].Popen = popen
    exe_folder = Path(sc["exe_folder"])
    sys.executable = str(exe_folder / "python.exe")

    if script.get("probe") == "unavailable":
        def no_app(*args, **kwargs):
            raise OSError("no probe")
        app_mod.App = no_app
    else:
        class ProbeApp:
            def __init__(self, *args, **kwargs):
                pass

            def watcher_running(self):
                calls.append(["probe"])
                found = probes.pop(0) if probes else False
                return found if isinstance(found, bool) else None
        app_mod.App = ProbeApp
    code = launcher._guarded(sc["argv"])
    out.append({"code": code, "calls": calls, "asked": asked})
sys.stdout.write(json.dumps(out, ensure_ascii=False))
'''

STAMP = re.compile(r"^\[\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\] ", re.M)


def usable(root: Path) -> None:
    (root / "src" / "codex_auto_resume").mkdir(parents=True)
    (root / "src" / "auto_resume.py").write_text("", encoding="utf-8")
    (root / "src" / "codex_auto_resume" / "cli.py").write_text("", encoding="utf-8")


def text(path: Path):
    return STAMP.sub("", path.read_bytes().decode("utf-8", "replace")) if path.is_file() else None


S = "supervise"
R = "restart"
SCENARIOS = [
    {"name": "standard: runs here", "script": {"plug": "null"}},
    {"name": "a supervised child itself", "argv": ["run", "--supervised-child"], "script": {"plug": "null"}},
    {"name": "another command", "argv": ["activate", "codex-auto-resume:cancel"], "script": {"plug": "null"}},
    {"name": "relaunched", "env": {"CODEX_AUTO_RESUME_RELAUNCHED": "1"}, "script": {"plug": "null"}},
    {"name": "no runtime.json", "config": None, "script": {"plug": "null"}},
    {"name": "runtime.json not JSON", "config": "{nope", "script": {"plug": "null"}},
    {"name": "runtime.json without a home", "config": {"mode": "installed"}, "script": {"plug": "null"}},
    {"name": "no engine found", "root": "none", "script": {"plug": "null"}},
    {"name": "the marketplace copy", "root": "market", "script": {"plug": "null"}},
    {"name": "another marketplace is not ours", "root": "foreign", "script": {"plug": "null"}},
    {"name": "the recorded copy", "root": "recorded", "script": {"plug": "null"}},
    {"name": "after stop: it let go", "env": {"CODEX_AUTO_RESUME_AFTER_STOP": "1"},
     "script": {"plug": "null", "probes": [True, True, False]}},
    {"name": "after stop: still running", "env": {"CODEX_AUTO_RESUME_AFTER_STOP": "1"},
     "script": {"plug": "null", "probes": [True] * 200}},
    {"name": "after stop: not known", "env": {"CODEX_AUTO_RESUME_AFTER_STOP": "1"},
     "script": {"plug": "null", "probes": [None] * 200}},
    {"name": "after stop: no probe", "env": {"CODEX_AUTO_RESUME_AFTER_STOP": "1"},
     "script": {"plug": "null", "probe": "unavailable"}},
    {"name": "supervised, ends", "script": {"answers": [S], "children": [0]}},
    {"name": "supervised, restarted once", "script": {"answers": [S, R, "defer"], "children": [1, 3]}},
    {"name": "supervised, newer state", "script": {"answers": [S], "children": [4]}},
    {"name": "supervised, no program", "script": {"answers": [S], "no_program": True}},
    {"name": "supervised, cannot start", "script": {"answers": [S], "children": ["oserror"]}},
    {"name": "supervised, cannot start again", "script": {"answers": [S, R], "children": [1, "oserror"]}},
    {"name": "held, then supervised after", "script": {"answers": ["defer", "defer", S, R, "defer"],
                                                         "held": "state_busy", "children": [0], "codes": [1]}},
    {"name": "held, a word that is not one", "script": {"answers": ["defer", "defer"], "held": "no way!"}},
    {"name": "held twice, then supervised", "script": {"answers": ["defer", S], "held": "check_failed", "children": [0]}},
    {"name": "plug raises and answers what is not its", "script": {"answers": ["raise", "hold", "early"]}},
    {"name": "newer state: relaunched once", "script": {"plug": "null", "codes": [4]}},
    {"name": "newer state, already relaunched", "env": {"CODEX_AUTO_RESUME_RELAUNCHED": "1"},
     "script": {"plug": "null", "codes": [4]}},
    {"name": "newer state, relaunch fails", "script": {"plug": "null", "codes": [4], "relaunch_fails": True}},
    {"name": "newer state, no program", "script": {"plug": "null", "codes": [4], "no_program": True}},
    {"name": "memory guard's end is not restarted", "script": {"answers": ["defer", "defer"], "codes": [5]}},
    {"name": "a long launcher.log", "log_lines": 260, "script": {"plug": "null"}},
]


class LauncherDiff(diffs.Base):
    def lay_out(self, folder: Path, scenario: dict) -> dict:
        """The scenario's folders: the launcher's own (runtime.json), the home, the roots, an interpreter folder."""
        here, home = folder / "here", folder / "home"
        here.mkdir(parents=True)
        home.mkdir()
        codex = folder / "codex"
        root = scenario.get("root", "home")
        config = {"home": str(home)}
        if root == "home":
            usable(home / "app")
        elif root in ("market", "foreign"):
            config.update(mode="plugin", plugin_name="codex-auto-resume")
            market = "codex-auto-resume-windows" if root == "market" else "someone-else"
            usable(codex / "plugins" / "cache" / market / "codex-auto-resume" / "1.0.0")
        elif root == "recorded":
            usable(folder / "recorded")
            config.update(plugin_root=str(folder / "recorded"))
        given = scenario.get("config", config) if "config" in scenario else config
        if isinstance(given, dict):
            (here / "runtime.json").write_text(json.dumps(given), encoding="utf-8")
        elif isinstance(given, str):
            (here / "runtime.json").write_text(given, encoding="utf-8")
        if scenario.get("log_lines"):
            (here / "logs").mkdir()
            (here / "logs" / "launcher.log").write_text(
                "".join("[2026-01-01 00:00:00] old line %d\n" % n for n in range(scenario["log_lines"])),
                encoding="utf-8")
        exe = folder / "python"
        exe.mkdir()
        (exe / "python.exe").write_bytes(b"")
        if not scenario["script"].get("no_program"):
            (exe / "pythonw.exe").write_bytes(b"")
        script = dict(scenario["script"], codex_home=str(codex))
        return {"here": str(here), "home": str(home), "exe_folder": str(exe), "argv": scenario.get("argv", []),
                "env": scenario.get("env", {}), "script": script}

    def files(self, laid: dict) -> dict:
        here, home = Path(laid["here"]), Path(laid["home"])
        return {"launcher.log": text(here / "logs" / "launcher.log"), "here errors.log": text(here / "logs" / "errors.log"),
                "home errors.log": text(home / "logs" / "errors.log"),
                "unsupervised.txt": text(home / "logs" / "unsupervised.txt")}

    def test_launcher(self):
        base = self.profile("launcher").resolve()
        source = base / "watcher_launcher.py"
        shown = subprocess.run(["git", "show", "%s:scripts/watcher_launcher.py" % reference.TAG], capture_output=True,
                               cwd=str(Path(__file__).resolve().parents[2]),
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(shown.returncode, 0, shown.stderr)
        source.write_bytes(shown.stdout)
        py = [self.lay_out(base / ("py-%d" % n), each) for n, each in enumerate(SCENARIOS)]
        rs = [self.lay_out(base / ("rs-%d" % n), each) for n, each in enumerate(SCENARIOS)]
        listing = base / "scenarios.json"
        listing.write_text(json.dumps(py), encoding="utf-8")
        made = reference.run(LAUNCHER, str(source), str(listing), profile=self.profile("reference"))
        self.assertEqual(made.returncode, 0, made.stderr[-4000:].decode("utf-8", "replace"))
        expected = json.loads(made.stdout.decode("utf-8"))
        with core.Harness(reference.scratch_environment(self.profile("rust"))) as harness:
            for scenario, laid_py, laid_rs, want in zip(SCENARIOS, py, rs, expected):
                _id, line = harness.call("watcher.launcher", here=laid_rs["here"], argv=laid_rs["argv"],
                                         env=laid_rs["env"], script=laid_rs["script"])
                reply = json.loads(line.decode("utf-8"))
                self.assertTrue(reply["reply"].get("ok"), line[:600])
                got = reply["reply"]["value"]
                label = scenario["name"]
                self.assertEqual(want["code"], got["code"], label)
                self.assertEqual(diffs.encode(want["asked"]), diffs.encode(got["asked"]), label)
                self.assertEqual(diffs.encode(want["calls"]), diffs.encode(got["calls"]), label)
                py_files = {k: v.replace(str(Path(laid_py["home"]).parent), "<CASE>") if v else v
                            for k, v in self.files(laid_py).items()}
                rs_files = {k: v.replace(str(Path(laid_rs["home"]).parent), "<CASE>") if v else v
                            for k, v in self.files(laid_rs).items()}
                self.assertEqual(py_files, rs_files, label)
