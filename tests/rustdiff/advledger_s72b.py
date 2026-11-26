"""S7.2b's ledger of the advanced tests (P7-DESIGN 3.1, the owner's Q3 (c)): every `advanced/tests/test_*.py` of the
reference tag that imports one of this seat's modules (`codex/authfile`, `codex/account`, `codex/swap`,
`codex/restart`, `win/appclose`, `engine/account`, `engine/autoswitch`), what it waits for before it can run unedited on
Rust - the advanced proxy S7.2a3 is building in `car-v0627-s72a`, and the latest other seat whose modules it imports -
and the differential family that holds its subject meanwhile.

    python -X utf8 tests/rustdiff/advledger_s72b.py [--tag v0.6.26] [--markdown]

Only shrinks: a file moves out when it runs green through the proxy. Reads the tag out of git; runs nothing of it.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advledger_s72a  # noqa: E402

FAMILIES = {
    "codex.authfile": "diffs_advaccount_files (AuthFileActsDiff), diffs_advaccount_pure (StoreModeDiff)",
    "codex.account": "diffs_advaccount_pure (AccountPureDiff)",
    "codex.swap": "diffs_advaccount_swap (SwitchDiff, RecoverDiff, ReadAndSaveDiff), diffs_advaccount_pure (SwapPureDiff)",
    "codex.restart": "diffs_advaccount_pure (RestartDiff)",
    "win.appclose": "diffs_advaccount_pure (AppCloseDiff)",
    "engine.account": "diffs_advaccount_engines (AccountWatchDiff)",
    "engine.autoswitch": "diffs_advaccount_engines (AutoSwitchDiff)",
}


def rows(tag: str) -> list:
    found = []
    for row in advledger_s72a.ledger(tag):
        if "S7.2b" not in row["seats"]:
            continue
        others = [seat for seat in advledger_s72a.ORDER if seat in row["seats"] and seat not in ("S7.2b",)
                  and seat not in advledger_s72a.DONE and seat != "S7.1"]
        waits = ["the advanced proxy (S7.2a3)"] + [seat for seat in others if seat != "S7.2a"]
        if row["reason"] != "proxy":
            waits.append(row["reason"])
        found.append({"file": row["file"], "advancedcase": row["advancedcase"], "waits": waits})
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default="v0.6.26")
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args()
    found = rows(args.tag)
    if args.markdown:
        print("| test file | advancedcase | waits for |")
        print("|---|---|---|")
        for row in found:
            print("| %s | %s | %s |" % (row["file"], "yes" if row["advancedcase"] else "", ", ".join(row["waits"])))
        print("\nHeld meanwhile by: %s" % "; ".join("%s: %s" % item for item in FAMILIES.items()))
    else:
        for row in found:
            print("%-52s %-5s %s" % (row["file"], "case" if row["advancedcase"] else "", ", ".join(row["waits"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
