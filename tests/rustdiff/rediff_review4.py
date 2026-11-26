"""Re-diff what review 4 and review 5's S2 fixed (seat fix4) against a tag: the command the v0.6.26 final is checked with.

    python -X utf8 tests/rustdiff/rediff_review4.py --reference v0.6.26
    python -X utf8 tests/rustdiff/rediff_review4.py                      # reference.TAG (v0.6.26-beta.2 until the final)

The fixes were made against v0.6.26-beta.2. This says, in order: which of the Python files they follow differ between
v0.6.26-beta.2 and the tag (`git diff --stat`); whether car-legacy's published lines are still what the tags say
(`legacy_lines.py --check`, the tag included once it exists); whether the str.isprintable table is current
(`gen_codex.py --check`); then runs the review's diffs and the policy hive with the tag as the reference
(`run.py --build --reference TAG -k diffs_review4` and `-k diffs_policy_hive`). The bootstrap proof's (c) on the cargo
build is `python build/rust_legacy_bootstraps.py --entry-from rust/target/release --version 0.6.27-alpha`. Exit 0 only
when all are clean; a file that changed is printed, not failed on - the diffs decide.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FOLLOWED = ("scripts/plugin_setup.py", "skills/codex-auto-resume/SKILL.md", "scripts/bootstrap.ps1",
            "src/codex_auto_resume/commands/install.py", "src/codex_auto_resume/win/homelock.py",
            "src/codex_auto_resume/config.py", "src/codex_auto_resume/win/powerdown.py",
            "src/codex_auto_resume/win/policykeys.py", "src/codex_auto_resume/managed.py",
            "src/codex_auto_resume/addremove.py", "src/codex_auto_resume/win/typeface.py",
            "src/codex_auto_resume/settings.py", "src/codex_auto_resume/statusfile.py",
            "src/codex_auto_resume/codex/chains.py", "src/codex_auto_resume/logbook.py")
BASE = "v0.6.26-beta.2"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def run(*argv) -> int:
    return subprocess.run([sys.executable, "-X", "utf8", *map(str, argv)], cwd=ROOT, stdin=subprocess.DEVNULL,
                          creationflags=NO_WINDOW).returncode


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--reference", metavar="TAG", default=None)
    args = parser.parse_args(argv)
    tag = args.reference
    if tag is None:
        sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
        from rustdiff import reference
        tag = reference.TAG
    changed = subprocess.run(["git", "diff", "--stat", BASE, tag, "--", *FOLLOWED], cwd=ROOT, capture_output=True,
                             encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    if changed.returncode != 0:
        print(changed.stderr.strip())
        return 2
    print("followed files changed from %s to %s:\n%s" % (BASE, tag, changed.stdout.strip() or "  none"))
    sys.stdout.flush()
    answers = {
        "published lines": run(ROOT / "rust" / "tools" / "legacy_lines.py", "--check"),
        "printable table": run(HERE / "gen_codex.py", "--check"),
        "review 4 diffs": run(HERE / "run.py", "--build", "--reference", tag, "-k", "diffs_review4"),
        "policy hive": run(HERE / "run.py", "--reference", tag, "-k", "diffs_policy_hive"),
    }
    print("rediff against %s: %s" % (tag, ", ".join("%s %s" % (name, "clean" if code == 0 else "DIFFERS")
                                                    for name, code in answers.items())))
    return 0 if not any(answers.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
