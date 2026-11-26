"""Seat S7.2e2's ledger (P7-DESIGN 3.1, owner Q3 (c)): every `advanced/tests` file whose subject is one of this seat's
modules, what holds that subject equal now, and what the file waits for before it runs unedited on Rust.

The subjects are ported (car-adv `engine::{supervise, powertasks, wake, analytics, updatecheck, fleet, anchor}`) and
held to the v0.6.26 tag by `diffs_advtime_*.py`; the files themselves drive the Python classes directly (a test's own
fakes bound to `state.scoped(...)`, or a `Runtime` over `advancedcase`), so they run on Rust only through the advanced
proxy S7.2a3 builds (forwarders for these classes' constructors and seams). This ledger only shrinks.

    python -X utf8 tests/rustdiff/advledger_s72e2.py            # the table
    python -X utf8 tests/rustdiff/advledger_s72e2.py --check    # every file named is in the tag's advanced/tests
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
PROXY = "the advanced proxy (S7.2a3): forwarders for the class and its seams"

# file -> (the family that holds its subject now, what the file waits for)
LEDGER = {
    "test_advanced_supervise.py": ("diffs_advtime_supervise", PROXY),
    "test_advanced_chosen_restart.py": ("diffs_advtime_supervise", PROXY),
    "test_advanced_power_tasks.py": ("diffs_advtime_power", PROXY + "; control/powertasks (S7.3a)"),
    "test_advanced_wake.py": ("diffs_advtime_wake", PROXY),
    "test_advanced_analytics.py": ("diffs_advtime_analytics", PROXY + "; control/analytics (S7.3a)"),
    "test_advanced_pace.py": ("diffs_advtime_analytics", PROXY),
    "test_advanced_idle_update_check.py": ("diffs_advtime_update", PROXY + "; surfaces.update_view (S7.3a)"),
    "test_advanced_update_check_log.py": ("diffs_advtime_update", PROXY),
    "test_advanced_fleet.py": ("diffs_advtime_fleet", PROXY + "; control/fleet (S7.3a)"),
    "test_advanced_anchor_default.py": ("diffs_advtime_anchor_code", PROXY),
    "test_advanced_window_anchor.py": ("diffs_advtime_anchor_code", PROXY + "; measure (S7.4)"),
    "test_advanced_window_anchor_config_read.py": ("diffs_advtime_anchor_code", PROXY),
    "test_advanced_window_anchor_quiet.py": ("diffs_advtime_anchor_code", PROXY),
    "test_advanced_window_anchor_retry.py": ("diffs_advtime_anchor_code", PROXY + "; surfaces (S7.3a)"),
    "test_advanced_window_anchor_state.py": ("diffs_advtime_anchor_code", PROXY),
    "test_advanced_window_anchor_wake_times.py": ("diffs_advtime_anchor_code + diffs_advtime_wake", PROXY),
    "test_advanced_window_anchor_weekly_looks.py": ("diffs_advtime_anchor_code", PROXY),
    "test_advanced_window_anchor_weekly_sleep.py": ("diffs_advtime_anchor_code", PROXY),
    "test_advanced_narrowing_parts.py": ("diffs_advtime_anchor (pure)", PROXY + "; S7.2e1's capabilities"),
    "test_advanced_rule_copies.py": ("diffs_advtime_* (each module's constants)", PROXY),
    "test_advanced_resident.py": ("diffs_advplug (P22, S7.2a)", PROXY + "; P22 errands of S7.3b"),
    "test_advanced_resident_state_busy.py": ("diffs_advplug (P22, S7.2a)", PROXY),
    "test_advanced_resident_unreadable.py": ("diffs_advplug (P22, S7.2a)", PROXY),
    "test_advanced_two_residents.py": ("diffs_advplug (P22, S7.2a)", PROXY),
}


def check() -> int:
    listed = subprocess.run(["git", "-C", str(ROOT), "ls-tree", "--name-only", "v0.6.26", "advanced/tests/"],
                            capture_output=True, encoding="utf-8", creationflags=NO_WINDOW)
    present = {line.rsplit("/", 1)[-1] for line in listed.stdout.splitlines()}
    missing = sorted(name for name in LEDGER if name not in present)
    for name in missing:
        print("not in the tag:", name)
    return 1 if missing else 0


def main(argv) -> int:
    if "--check" in argv:
        return check()
    for name, (family, waits) in sorted(LEDGER.items()):
        print("%-46s %-48s waits for %s" % (name, family, waits))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
