"""Where a source-run watcher or bridge spends its time, by Python 3.15's sampling profiler (Tachyon, PEP 799). For the lag and
CPU work; a maintainer's tool, not shipped (build/ never is).

    python build/profile_tachyon.py --python <a 3.15 python.exe> --home <scratch folder> bridge
    python build/profile_tachyon.py --python <a 3.15 python.exe> --home <scratch folder> watcher --flamegraph -o out.html
    python build/profile_tachyon.py --python <a 3.15 python.exe> --pid 1234 --duration 30

Only ever a source run. The profiler reads another process through remote debugging, which every interpreter the product
starts has off (startup.NO_REMOTE_DEBUG) and has to stay off, so an installed product cannot be attached to and this does not
try: a target starts here from its module in src/, because src/auto_resume.py would start itself again with remote debugging off
and leave the profiler watching a process that only waits. --home has to be a scratch folder, and the target gets a profile
and a Codex home inside it, so what it finds is a machine of its own.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# Each target's module and arguments after --home: one start of the bridge, or one tick of the watcher.
TARGETS = {"bridge": ("codex_auto_resume.controlcli", ("status",)), "watcher": ("codex_auto_resume.cli", ("run", "--once"))}
FORMATS = ("pstats", "collapsed", "flamegraph", "gecko", "heatmap")


def real_home() -> Path:
    return Path.home() / ".codex-auto-resume"


def scratch_world(home: Path) -> dict:
    """The environment of a target whose every per-user folder is inside `home`, made here."""
    world = home / "machine"
    folders = {"USERPROFILE": world, "HOME": world, "LOCALAPPDATA": world / "AppData" / "Local",
               "APPDATA": world / "AppData" / "Roaming", "CODEX_HOME": world / "codex"}
    for folder in folders.values():
        folder.mkdir(parents=True, exist_ok=True)
    environment = {name: value for name, value in os.environ.items() if name not in ("CODEX_AR_EDITION", "PYTHONPATH")}
    environment.update({name: str(folder) for name, folder in folders.items()})
    return environment


def starter(home: Path, module: str) -> Path:
    """A script in the scratch folder that runs the target's module from src/: a script and not `run -m`, because the embeddable
    Python, the one a maintainer has beside the bundled one, ignores PYTHONPATH."""
    script = home / "profile_target.py"
    script.write_text('import runpy, sys\nsys.path.insert(0, %r)\nrunpy.run_module(%r, run_name="__main__", alter_sys=True)\n'
                      % (str(ROOT / "src"), module), encoding="utf-8")
    return script


def command(python: str, profiler: list, script, home, arguments) -> list:
    return [python, "-m", "profiling.sampling", "run", *profiler, str(script), "--home", str(home), *arguments]


def profiler_options(args) -> list:
    options = ["--all-threads", "--mode", args.mode, "--sampling-rate", str(args.rate)]
    if args.duration:
        options += ["--duration", str(args.duration)]
    options.append("--" + args.format)
    if args.output:
        options += ["-o", str(args.output)]
    return options


def is_315(python: str) -> bool:
    done = subprocess.run([python, "-c", "import sys; print(sys.version_info >= (3, 15))"], capture_output=True, encoding="utf-8",
                          errors="replace", creationflags=NO_WINDOW, timeout=60)
    return done.returncode == 0 and done.stdout.strip() == "True"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("target", nargs="?", choices=sorted(TARGETS))
    parser.add_argument("--python", default=sys.executable, help="a Python 3.15 or later (the bundled one is not it)")
    parser.add_argument("--home", type=Path, help="a scratch folder: the target's whole world")
    parser.add_argument("--pid", type=int, help="attach to a source-run process started with remote debugging on")
    parser.add_argument("--duration", type=int, help="seconds to sample (with --pid, or to cut a target short)")
    parser.add_argument("--mode", choices=("wall", "cpu", "gil", "exception"), default="cpu")
    parser.add_argument("--rate", default="1khz")
    parser.add_argument("--format", choices=FORMATS, default="pstats")
    parser.add_argument("--flamegraph", dest="format", action="store_const", const="flamegraph", help="same as --format flamegraph")
    parser.add_argument("-o", "--output", type=Path)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if bool(args.target) == bool(args.pid):
        parser.error("give a target (bridge, watcher) or --pid, one of them")
    if not is_315(args.python):
        parser.error("%s is older than Python 3.15, which is where the profiler is" % args.python)
    if args.pid:
        return subprocess.run([args.python, "-m", "profiling.sampling", "attach", *profiler_options(args), str(args.pid)],
                              creationflags=NO_WINDOW).returncode
    if args.home is None:
        parser.error("a target needs --home, a scratch folder")
    home = args.home.resolve()
    if home == real_home().resolve():
        parser.error("that is the real installation: --home has to be a scratch folder")
    home.mkdir(parents=True, exist_ok=True)
    module, arguments = TARGETS[args.target]
    return subprocess.run(command(args.python, profiler_options(args), starter(home, module), home, arguments), env=scratch_world(home),
                          creationflags=NO_WINDOW).returncode


if __name__ == "__main__":
    sys.exit(main())
