"""Re-diff car-surface (S6.0) against a tag: the one command its port is checked with again.

    python -X utf8 tests/rustdiff/rediff_surface.py --reference v0.6.26
    python -X utf8 tests/rustdiff/rediff_surface.py --reference <a later tag of the archived repository>

S6.0 was ported from the v0.6.26 final itself (D17; ui/popup/model.py changed after beta.2 and the final's
`domain/usage.newest` is new), so its diffs need the final or a later tag: where run.py's reference is still the beta.2
stand-in they read v0.6.26 (`surface.surface_tag`). This says which of the ten ported modules - and the Python they read
that another crate holds (the words, the catalogs, the brand's tables, the reasons, the notice kinds, the demo, the ids,
the usage reading) - differ between v0.6.26 and the tag (`git diff --stat`, so a change is seen even where no diff
reaches it), and then runs every `diffs_surface_*` diff with the tag as the reference (`run.py --build --reference TAG
-k diffs_surface`). Exit 0 only when the diffs are equal; a changed file is printed, not failed on - the diffs decide.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PORTED = ("codex_link.py", "notice_card.py", "notice_inbox.py", "notice_presence.py", "notice_uris.py", "notifier.py",
          "notify.py", "ui/popup/model.py", "ui/tray/model.py", "ui/tray/stored.py")
READ = ("ui/popup/words.py", "ui/popup/placement.py", "ui/popup/layout.py", "ui/popup/window.py", "ui/words.py",
        "l10n.py", "locales", "brand", "reasons.py", "failures.py", "needsyou.py", "notice_kinds.py", "demo.py",
        "settings.py", "domain/ids.py", "domain/public.py", "domain/states.py", "domain/usage.py", "domain/vocabulary.py",
        "domain/plug.py", "domain/gates.py", "ownvalues.py", "machine.py",
        "pwsh.py", "startup.py")
BASE = "v0.6.26"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--reference", metavar="TAG", default=BASE)
    args = parser.parse_args(argv)
    tag = args.reference
    for title, files in (("ported", PORTED), ("read", READ)):
        paths = ["src/codex_auto_resume/" + each for each in files]
        changed = subprocess.run(["git", "diff", "--stat", BASE, tag, "--", *paths], cwd=ROOT, capture_output=True,
                                 encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
        if changed.returncode != 0:
            print(changed.stderr.strip())
            return 2
        print("%s files changed from %s to %s:\n%s" % (title, BASE, tag, changed.stdout.strip() or "  none"))
    sys.stdout.flush()
    diffs = subprocess.run([sys.executable, "-X", "utf8", str(HERE / "run.py"), "--build", "--reference", tag,
                            "-k", "diffs_surface"], cwd=ROOT, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW).returncode
    print("rediff against %s: diffs %s" % (tag, "equal" if diffs == 0 else "DIFFER"))
    return 0 if diffs == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
