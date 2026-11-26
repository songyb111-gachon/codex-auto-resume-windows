"""S7.2d's ledger of the advanced tests (P7-DESIGN 3.1, the owner's Q3 (c)): every `advanced/tests/test_*.py` of the
reference tag that imports one of S7.2d's modules (engine/usage, usagestop, resetmessage, resetwatch, credits, earlyreset,
wrapwords, continued, capacity), what holds its subject now and what it still waits for to run unedited on Rust.

    python -X utf8 tests/rustdiff/advledger_s72d.py [--tag v0.6.26] [--markdown]

The subjects are held now by `diffs_advusage_pure.py` and `diffs_advusage_codes.py` (the codes' hooks over a scripted
world, against the tag's own classes). No file runs unedited on Rust yet: that is the advanced proxy's (S7.2a3, being
built beside this seat in car-v0627-s72a) - its serve loop, then forwarders for each S7.2d class. A file that also
needs a later seat waits for it too (`unlock`, S7.2a's rule: the latest seat in the waves). The table only shrinks.
Reads the tag out of git; runs nothing of it.
"""
from __future__ import annotations

import argparse
import sys

from advledger_s72a import ORDER, ledger  # noqa: E402 - run as a script beside it

OWN = ("usage", "usagestop", "resetmessage", "resetwatch", "credits", "earlyreset", "wrapwords", "continued", "capacity")
FAMILY = {"usage": "diffs_advusage_codes (MeterDiff, WrapUpDiff, StopDiff), diffs_advusage_pure (UsageStagesDiff)",
          "usagestop": "diffs_advusage_codes (StopDiff), diffs_advusage_pure (GuardsDiff)",
          "resetmessage": "diffs_advusage_codes (MessageDiff), diffs_advusage_pure (GuardsDiff)",
          "resetwatch": "diffs_advusage_pure (ResetWatchDiff), diffs_advusage_codes (CreditDiff, MessageDiff)",
          "credits": "diffs_advusage_codes (CreditDiff)", "earlyreset": "diffs_advusage_codes (EarlyDiff)",
          "wrapwords": "diffs_advusage_pure (WrapWordsDiff)", "continued": "diffs_advusage_pure (ContinuedDiff)",
          "capacity": "diffs_advusage_codes (CapacityDiff)"}


def own_rows(tag: str) -> list:
    import subprocess
    found = []
    for row in ledger(tag):
        if "S7.2d" not in row["seats"]:
            continue
        text = subprocess.run(["git", "show", "%s:advanced/tests/%s" % (tag, row["file"])], capture_output=True,
                              text=True, encoding="utf-8", errors="replace").stdout
        modules = [name for name in OWN if ("engine." + name) in text or ("engine import " + name) in text
                   or (" %s," % name) in text or ("import %s\n" % name) in text]
        later = [seat for seat in ORDER if seat in row["seats"] and ORDER.index(seat) > ORDER.index("S7.2d")]
        waits = ["the advanced proxy (S7.2a3)"] + later + (["S6.2a (C# page)"] if row["unlock"] == "S6.2a" else [])
        found.append({"file": row["file"], "modules": modules or ["(by a helper)"],
                      "held": "; ".join(FAMILY[name] for name in modules) or "diffs_advusage_codes",
                      "waits": ", ".join(waits), "advancedcase": row["advancedcase"]})
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default="v0.6.26")
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args()
    rows = own_rows(args.tag)
    if args.markdown:
        print("| file | S7.2d modules | held now by | waits for |")
        print("|---|---|---|---|")
        for row in rows:
            print("| %s | %s | %s | %s |" % (row["file"], " ".join(row["modules"]), row["held"], row["waits"]))
        print("| **%d files** | | | |" % len(rows))
    else:
        for row in rows:
            print("%-56s %-28s waits: %s" % (row["file"], ",".join(row["modules"]), row["waits"]))
        print("%d files; green through the proxy: 0" % len(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
