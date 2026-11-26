"""Re-diff car-adv's advanced store (S7.1a) against a tag: the one command the v0.6.26 final is checked with.

    python -X utf8 tests/rustdiff/rediff_advstore.py --reference v0.6.26
    python -X utf8 tests/rustdiff/rediff_advstore.py                      # reference.TAG (v0.6.26-beta.2 until the final)

S7.1a was ported from v0.6.26-beta.2; none of its modules had changed on dev after that tag. This says, in order: which
of the ported Python files differ between v0.6.26-beta.2 and the tag (`git diff --stat`); whether the generated
statements, words and registry facts are still the tag's (`gen_advstore.py` and `gen_advpolicy.py --check --ref TAG`); and then runs every
diff of `diffs_advstore.py` with the tag as the reference (`run.py --build --reference TAG -k diffs_advstore`; the diffs build the
`advstore` example when it is missing; set CODEX_AR_ADVSTORE_EXE to use another build). Exit 0 only when all are clean.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
STATE = ("__init__", "schema", "choices", "resets", "prompts", "continuations", "arming", "session", "journal",
         "records", "chat", "analytics", "steers", "spend", "runs", "meter", "opens", "account", "restarts")
PORTED = (["advanced/src/codex_auto_resume_advanced/state/%s.py" % name for name in STATE]
          + ["advanced/src/codex_auto_resume_advanced/%s.py" % name
             for name in ("profiles", "ledger", "watchlog", "images", "vocabulary", "registry")]
          + ["advanced/src/codex_auto_resume_advanced/engine/hookclaims.py",
             "advanced/src/codex_auto_resume_advanced/control/sendnow.py",
             "advanced/src/codex_auto_resume_advanced/codex/authfile.py",
             "advanced/src/codex_auto_resume_advanced/codex/account.py",
             "src/codex_auto_resume/domain/ids.py", "src/codex_auto_resume/domain/states.py",
             "src/codex_auto_resume/failures.py", "src/codex_auto_resume/domain/plug.py",
             "src/codex_auto_resume/ladder.py", "src/codex_auto_resume/config.py"])
BASE = "v0.6.26-beta.2"
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
    status = max(subprocess.run([sys.executable, "-X", "utf8", str(HERE / script), "--check", "--ref", tag],
                                cwd=ROOT, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW).returncode
                 for script in ("gen_advstore.py", "gen_advpolicy.py"))
    diffs = subprocess.run([sys.executable, "-X", "utf8", str(HERE / "run.py"), "--build", "--reference", tag, "-k",
                            "diffs_advstore"], cwd=ROOT, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW).returncode
    print("rediff against %s: generated files %s, diffs %s" % (tag, "current" if status == 0 else "STALE",
                                                               "equal" if diffs == 0 else "DIFFER"))
    return 0 if status == 0 and diffs == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
