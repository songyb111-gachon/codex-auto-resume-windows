"""Re-diff S6.2a against a tag: the window's switch from Python to the Rust core, and the Stop hook launcher.

    python -X utf8 tests/rustdiff/rediff_window.py --reference v0.6.26
    python -X utf8 tests/rustdiff/rediff_window.py                    # reference.TAG

S6.2a moved every start of the window's (the one-shot bridge, `bridge serve`, Repair's setup, the Desktop shortcut) from
the bundled Python to `app\\bin\\codex-auto-resume.exe`, keyed the strings cache on the core, spared the host beside
car-legacy's pythonw.exe, and ported gui/HookLauncher.cs to car-adv-bin's codex-auto-resume-hook.exe (P6-DESIGN 1.7), all
from the v0.6.26 final. This says, in order: which of the window's ported files and the bridge's wire differ between the
final and the tag (`git diff --stat`, so a change is seen even where no test reaches it - a new start of a Python program
in a window source, a new word of the bridge, a change to the C# hook launcher's bounds); then runs the seat's tests:
tests/test_window_core.py, tests/test_hook_launcher.py and tests/test_consumer_fields.py (the wire, D12), and car-adv-bin's
own (`cargo test --locked -p car-adv-bin` in advanced/rust). Exit 0 only when they pass; a changed file is printed, not
failed on - the tests decide, and a changed start or bound is ported by hand to gui/CoreExe.cs's users or the launcher.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PORTED = ("gui/SettingsApp.cs", "gui/Dashboard.cs", "gui/DashboardMaintenance.cs", "gui/InstallerFlow.cs",
          "gui/WindowJson.cs", "gui/ChildTree.cs", "gui/RuntimeChoice.cs", "gui/McpLauncher.cs", "gui/HookLauncher.cs",
          "gui/window.sources", "build/make_gui.ps1", "src/codex_auto_resume/controlcli.py",
          "src/codex_auto_resume/interface.py", "src/codex_auto_resume/l10n.py", "scripts/plugin_setup.py",
          "advanced/src/codex_auto_resume_advanced/hook/__init__.py",
          "advanced/src/codex_auto_resume_advanced/control/hookplugin.py")
BASE = "v0.6.26"
MODULES = ("test_window_core", "test_hook_launcher", "test_consumer_fields")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--reference", metavar="TAG", default=None)
    args = parser.parse_args(argv)
    tag = args.reference
    if tag is None:
        sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
        from rustdiff import reference
        tag = reference.TAG
    changed = subprocess.run(["git", "diff", "--stat", BASE, tag, "--", *PORTED], cwd=ROOT, capture_output=True,
                             encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    if changed.returncode != 0:
        print(changed.stderr.strip())
        return 2
    print("ported files changed from %s to %s:\n%s" % (BASE, tag, changed.stdout.strip() or "  none"))
    sys.stdout.flush()
    environment = {key: value for key, value in os.environ.items() if key != "CODEX_AR_EDITION"}
    environment["PYTHONPATH"] = os.pathsep.join((str(ROOT / "src"), str(ROOT / "tests")))
    tests = subprocess.run([sys.executable, "-X", "utf8", "-m", "unittest", *MODULES], cwd=ROOT, env=environment,
                           stdin=subprocess.DEVNULL, creationflags=NO_WINDOW).returncode
    cargo = subprocess.run(["cargo", "test", "--locked", "-p", "car-adv-bin"], cwd=ROOT / "advanced" / "rust",
                           stdin=subprocess.DEVNULL, creationflags=NO_WINDOW).returncode
    print("rediff against %s: window tests %s; hook launcher %s" % (tag, "pass" if tests == 0 else "FAIL",
                                                                   "pass" if cargo == 0 else "FAIL"))
    return 0 if tests == 0 and cargo == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
