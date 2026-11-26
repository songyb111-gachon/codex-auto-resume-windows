"""The advanced tests of seat S7.2e1's modules and what each waits for (P7-DESIGN 3.1, the owner's Q3 (c)).

    python -X utf8 tests/rustdiff/advledger_s72e1.py [--tag v0.6.26]

For every `advanced/tests` file that imports one of S7.2e1's twenty `engine/` modules (directly or through the tests'
own helpers, `advledger_s72a.imported`): the S7.2e1 modules it reaches, which of them are ported here, and what it waits
for before it can run unedited on Rust - the advanced proxy (S7.2a3, being built in car-v0627-s72a), S7.2e1 modules
not yet ported, and the other seats it also reaches. Until the proxy lands every file waits; each module's behaviour
is held meanwhile by `diffs_advturns_*.py` against the tag. The list only shrinks.
"""
from __future__ import annotations

import argparse
import sys

from rustdiff import advledger_s72a as base

MINE = ("headless compact fallback silent retries emptyreply keepgoing goal subagent markerfree foropen opentarget "
        "steer promptqueue chat oncemore everyconversation parallel sessions admitted").split()
# Ported and diffed in this seat (diffs_advturns_small.py, diffs_advturns_runs.py).
PORTED = {"silent", "everyconversation", "parallel", "sessions", "oncemore", "headless", "compact", "fallback",
          "retries"}
DONE_SEATS = {"S7.1", "S7.2a", "S7.2c", "S7.3c", "S7.2e1"}


def rows(tag: str) -> list:
    source = base.subprocess.run(["git", "ls-tree", "-r", "--name-only", tag, "advanced/src/" + base.PACKAGE],
                                 capture_output=True, creationflags=base.NO_WINDOW, check=True,
                                 text=True).stdout.split()
    known = {""}
    for path in source:
        if path.endswith(".py"):
            dotted = path[len("advanced/src/" + base.PACKAGE) + 1:-3].replace("/", ".")
            known.add(dotted[:-9] if dotted.endswith(".__init__") else dotted)
    tests = base.files(tag)
    found = []
    for name in sorted(tests):
        if not name.startswith("test_"):
            continue
        modules = {base.real(each, known) for each in base.imported(tests[name], tests)}
        mine = sorted({each.split(".")[1] for each in modules if each.startswith("engine.")
                       and len(each.split(".")) > 1 and each.split(".")[1] in MINE})
        if not mine:
            continue
        others = sorted({base.seat(each) for each in modules} - DONE_SEATS)
        waits = ["proxy (S7.2a3)"] + ["S7.2e1:" + each for each in mine if each not in PORTED] + others
        found.append({"file": name, "mine": mine, "ported": [each for each in mine if each in PORTED],
                      "waits": waits})
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default="v0.6.26")
    args = parser.parse_args()
    found = rows(args.tag)
    for row in found:
        print("%-52s %-40s waits: %s" % (row["file"], ",".join(row["mine"]), ", ".join(row["waits"])))
    print("%d files; %d reach only ported S7.2e1 modules" % (
        len(found), sum(1 for row in found if len(row["ported"]) == len(row["mine"]))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
