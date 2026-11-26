"""The final re-diff of S7.1b (car-adv's registry, arming, statement, vocabulary and policy).

    python -X utf8 tests/rustdiff/rediff_advpolicy.py --reference v0.6.26

S7.1b was ported from v0.6.26-beta.2 while some advanced modules still moved on dev (PLAN 5.1). This lists which of the
files the port reads changed between beta.2 and the tag, checks the generated tables against the tag
(`gen_advpolicy.py --check --ref TAG`), builds the probe and runs every `diffs_advpolicy_*` diff with the tag as the reference
(CODEX_AR_REFERENCE). Exit 0 only when nothing moved or everything that moved still matches.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
BASE = "v0.6.26-beta.2"
# What the port reads: the seven modules of its scope, the advanced locales (statement), and the core files they lean on.
FILES = [
    "advanced/src/codex_auto_resume_advanced/%s.py" % name
    for name in ("registry", "arming", "statement", "vocabulary", "policy", "standards", "measured")
] + [
    "advanced/src/codex_auto_resume_advanced/locales",
    "advanced/src/codex_auto_resume_advanced/autocheck.py",
    "src/codex_auto_resume/compat/model.py",
    "src/codex_auto_resume/l10n.py",
    "src/codex_auto_resume/domain/plug.py",
]
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def run(*command, env=None) -> int:
    print("$", " ".join(command), flush=True)
    return subprocess.run(command, cwd=str(ROOT), env=env, creationflags=NO_WINDOW).returncode


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--reference", required=True, metavar="TAG", help="the tag to hold the port to (v0.6.26)")
    args = parser.parse_args(argv)
    changed = subprocess.run(["git", "-C", str(ROOT), "diff", "--stat", "%s..%s" % (BASE, args.reference), "--", *FILES],
                             capture_output=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    if changed.returncode != 0:
        print(changed.stderr)
        return 2
    print("files the port reads that changed since %s:" % BASE)
    print(changed.stdout.strip() or "  none")
    status = run(sys.executable, "-X", "utf8", "tests/rustdiff/gen_advpolicy.py", "--check", "--ref", args.reference)
    environment = dict(os.environ, CODEX_AR_REFERENCE=args.reference, PYTHONPATH=os.pathsep.join(
        [str(ROOT / "src"), str(ROOT / "tests")]))
    modules = ("rustdiff.diffs_advpolicy_words", "rustdiff.diffs_advpolicy_pure", "rustdiff.diffs_advpolicy_arming")
    status |= run(sys.executable, "-X", "utf8", "-m", "unittest", *modules, env=environment)
    return 1 if status else 0


if __name__ == "__main__":
    sys.exit(main())
