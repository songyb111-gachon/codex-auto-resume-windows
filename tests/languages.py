"""Which languages this checkout holds, asked in one place.

Three branches carry the documents three ways (docs/CONTRIBUTING.md, "Branches and languages"):

* **dev** has every English document and its Korean sibling side by side - `X.md` beside
  `X.ko.md` - because that is where both are written, reviewed in the same commit, and held to
  every rule about them.
* **main** is English only. A promotion from dev deletes every `*.ko.md`
  (`scripts/promote.py`), so the repository's front page reads in one language.
* **ko** is generated: each Korean text is written over its English sibling's name and the
  `.ko.md` file is removed (`scripts/ko_sync.py`), so `PRIVACY.md` there *is* the Korean text.

A test about a Korean document must know which of the three it is looking at, and six test
files used to ask a narrower question each on their own - "is this the generated branch?" -
which main answers "no" while holding no Korean at all. This asks once.

A tree that holds some Korean sources and not others is none of the three: it is a
half-deleted checkout, and a test that skipped there would be excused by the damage it should
report. `english_only()` refuses it rather than answering.
"""
from __future__ import annotations

from functools import lru_cache
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
MAPPING = ROOT / "scripts" / "ko_branch.json"
NOTICE = ".github/GENERATED-BRANCH.md"

# Where each Korean text is checked when this checkout does not hold it.
ON_DEV = "the Korean sources live on dev, and their checks run there; main is English only"


@lru_cache(maxsize=None)
def generated_ko_branch() -> bool:
    """The generated ko branch: its notice is *tracked*. A bare file on disk is what a stray
    local run of the generator leaves behind, and must never disarm anything on dev or main."""
    if not (ROOT / NOTICE).is_file():
        return False
    listed = subprocess.run(["git", "-C", str(ROOT), "ls-files", "--", NOTICE],
                            capture_output=True, text=True, encoding="utf-8")
    return bool(listed.returncode == 0 and listed.stdout.strip())


def korean_sources() -> list[str]:
    """Every `*.ko.md` the mapping names, as repository-relative paths."""
    return sorted(json.loads(MAPPING.read_text(encoding="utf-8"))["documents"])


def english_of(korean: str) -> str:
    """The English document a Korean source translates."""
    return json.loads(MAPPING.read_text(encoding="utf-8"))["documents"][korean]


def korean_present() -> list[str]:
    return [name for name in korean_sources() if (ROOT / name).is_file()]


def english_only() -> bool:
    """main: not the generated branch, and not one Korean source here.

    Raises on a partial set, which is a damaged tree rather than a branch."""
    if generated_ko_branch():
        return False
    present, wanted = korean_present(), korean_sources()
    if present and len(present) != len(wanted):
        missing = sorted(set(wanted) - set(present))
        raise AssertionError("this checkout holds some Korean sources and not others - "
                             "neither dev (all) nor main (none). Missing: " + ", ".join(missing))
    return not present


def both_languages() -> bool:
    """dev, or any checkout of it: every Korean source beside its English sibling."""
    return not generated_ko_branch() and not english_only()


def branch_rule() -> str | None:
    """What CI says this checkout must hold: "english" for main, "both" for dev, None when CI
    names no branch this tree is (a tag, a dispatch, the ko sync, a local run).

    Asked of the tree actually checked out, not of the branch a workflow happens to run on:
    `release.yml` dispatched from main can check out dev (`inputs.ref`), and holding that tree to
    main's rule was a false red. So on a push the rule applies only when HEAD is the pushed commit,
    and on a pull request it is the base's rule - the tree tested is the merge into that base, so
    a pull request that would take Korean off dev, or put it back on main, fails before it lands.
    """
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    if event == "pull_request":
        name = os.environ.get("GITHUB_BASE_REF", "")
    elif event == "push":
        head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True,
                              text=True, encoding="utf-8").stdout.strip()
        if not head or head != os.environ.get("GITHUB_SHA", ""):
            return None
        name = os.environ.get("GITHUB_REF_NAME", "")
    else:
        return None
    return {"main": "english", "dev": "both"}.get(name)
