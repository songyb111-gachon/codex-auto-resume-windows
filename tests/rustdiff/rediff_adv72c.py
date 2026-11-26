"""Re-diff S7.2c (car-adv's codex parts, autocheck, compatdata and inuse) against a tag: the final's one command.

    python -X utf8 tests/rustdiff/rediff_adv72c.py --reference v0.6.26
    python -X utf8 tests/rustdiff/rediff_adv72c.py                        # the advcodex diffs' own default, v0.6.26

S7.2c was ported from the v0.6.26 final itself (D17; `codex/inuse.py` is the final's). This says, in order: which of the
ported Python files differ between the final and the tag (`git diff --stat v0.6.26 TAG`); whether car-adv's
str.isalpha table is still the reference interpreter's (`gen_advcodex.py --check`); and then runs every diff of
`diffs_advcodex_*.py` with the tag as the reference (`run.py --build --reference TAG -k AdvCodex -k CompatData -k
Autocheck -k Inuse -k Readers`; the diffs build the `advcodex` and `advfake` examples when they are missing; set
CODEX_AR_ADVCODEX_DIR to use another build). Exit 0 only when all are clean.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CODEX = ("__init__", "protocol", "inuse", "turns", "lineage", "threads", "conversation", "sessions", "goals", "credits")
PORTED = (["advanced/src/codex_auto_resume_advanced/codex/%s.py" % name for name in CODEX]
          + ["advanced/src/codex_auto_resume_advanced/%s.py" % name for name in ("autocheck", "compatdata", "vocabulary",
                                                                                   "measured")]
          + ["src/codex_auto_resume/compat/model.py", "src/codex_auto_resume/compat/files.py",
             "src/codex_auto_resume/codex/transport.py", "src/codex_auto_resume/codex/pairing.py",
             "src/codex_auto_resume/codex/paths.py", "src/codex_auto_resume/codex/values.py",
             "src/codex_auto_resume/codex/eligibility.py", "src/codex_auto_resume/codex/labels.py",
             "src/codex_auto_resume/codex/usage.py", "src/codex_auto_resume/config.py"])
BASE = "v0.6.26"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
FAMILIES = ("CompatData", "Autocheck", "Inuse", "Readers")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--reference", metavar="TAG", default=BASE)
    args = parser.parse_args(argv)
    tag = args.reference
    changed = subprocess.run(["git", "diff", "--stat", BASE, tag, "--", *PORTED], cwd=ROOT, capture_output=True,
                             encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    if changed.returncode != 0:
        print(changed.stderr.strip())
        return 2
    print("ported files changed from %s to %s:\n%s" % (BASE, tag, changed.stdout.strip() or "  none"))
    sys.stdout.flush()
    table = subprocess.run([sys.executable, "-X", "utf8", str(HERE / "gen_advcodex.py"), "--check"], cwd=ROOT,
                           stdin=subprocess.DEVNULL, creationflags=NO_WINDOW).returncode
    command = [sys.executable, "-X", "utf8", str(HERE / "run.py"), "--build", "--reference", tag]
    for family in FAMILIES:
        command += ["-k", family]
    diffs = subprocess.run(command, cwd=ROOT, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW).returncode
    print("rediff against %s: table %s, diffs %s" % (tag, "current" if table == 0 else "STALE",
                                                     "equal" if diffs == 0 else "DIFFER"))
    return 0 if table == 0 and diffs == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
