"""Re-diff the Rust payload's installer (seat S8.2) against a tag: the command a later reference is checked with.

    python -X utf8 tests/rustdiff/rediff_package.py --reference v0.6.26

build/rust_install/install.ps1 is v0.6.26's build/install/install.ps1 with the core's program where that one ran
plugin_setup.py and the migration added (rust/GROUNDWORK.md, S8.2); the bootstrap's PLAN 6.10 step is in
scripts/bootstrap.ps1. This says, in order: which of the files the installer follows differ between v0.6.26 and the
tag (`git diff --stat`) - a change there is one to carry into the Rust installer by hand; whether the tag's
install.ps1 is still the one the Rust installer was derived from (its SHA-256, LF); then runs the installer's proofs
(test_rust_install: v0.6.26's own installer, from the tag, and the Rust one on scratch homes, both editions) and the
archive's (test_rust_release), and every published updater's runtime\\python.exe lines against the cargo build
(rust_legacy_bootstraps.py --entry-from). Exit 0 only when all are clean; a file that changed is printed, not failed
on - the proofs decide.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = "v0.6.26"
FOLLOWED = ("build/install/install.ps1", "build/install/Install.cmd", "build/install/Uninstall.cmd",
            "scripts/bootstrap.ps1", "scripts/plugin_setup.py", "scripts/watcher_launcher.py",
            "src/codex_auto_resume/startup.py", "src/codex_auto_resume/config.py",
            "src/codex_auto_resume/addremove.py", "src/codex_auto_resume/win/homelock.py")
# v0.6.26's build/install/install.ps1 as git stores it (LF): what build/rust_install/install.ps1 was derived from.
DERIVED_FROM = "4154bed18c80a91ed481f909a95093ab7541d4fc8826b11acac5b77eadf4e8ae"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def run(*argv, env=None) -> int:
    return subprocess.run([sys.executable, "-X", "utf8", *map(str, argv)], cwd=ROOT, stdin=subprocess.DEVNULL,
                          creationflags=NO_WINDOW, env=env).returncode


def installer_digest(tag: str) -> str | None:
    shown = subprocess.run(["git", "show", tag + ":build/install/install.ps1"], cwd=ROOT, capture_output=True,
                           creationflags=NO_WINDOW)
    if shown.returncode != 0:
        return None
    return hashlib.sha256(shown.stdout.replace(b"\r\n", b"\n")).hexdigest()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--reference", metavar="TAG", default=BASE)
    args = parser.parse_args(argv)
    tag = args.reference
    changed = subprocess.run(["git", "diff", "--stat", BASE, tag, "--", *FOLLOWED], cwd=ROOT, capture_output=True,
                             encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    if changed.returncode != 0:
        print(changed.stderr.strip())
        return 2
    print("followed files changed from %s to %s:\n%s" % (BASE, tag, changed.stdout.strip() or "  none"))
    digest = installer_digest(tag)
    derived = digest == DERIVED_FROM
    print("%s's install.ps1 %s the one the Rust installer was derived from" % (tag, "is" if derived else "IS NOT"))
    sys.stdout.flush()
    tests = dict(os.environ, PYTHONPATH=os.pathsep.join((str(ROOT / "src"), str(ROOT / "tests"))))
    answers = {
        "derivation": 0 if derived else 1,
        "installer proofs": run("-m", "unittest", "test_rust_install", "test_rust_release", env=tests),
        "entry lines": run(ROOT / "build" / "rust_legacy_bootstraps.py", "--entry-from",
                           ROOT / "rust" / "target" / "release", "--version", "0.6.27-alpha"),
    }
    print("rediff against %s: %s" % (tag, ", ".join("%s %s" % (name, "clean" if code == 0 else "DIFFERS")
                                                    for name, code in answers.items())))
    return 0 if not any(answers.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
