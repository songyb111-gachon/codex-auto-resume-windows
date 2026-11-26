"""S7.2c remainder: `codex/turns.booted_of` as the v0.6.26 final has it, held equal to car-adv's `turns::booted_of`.

The boot time core's store keeps in its watcher heartbeat (`watcher_status.booted_at`), read by opening the store as
the reference does - which makes and migrates a state folder that has none yet, so the files left are compared too.
Homes: no state folder, an empty one, a store with a heartbeat with and without a boot time (whole and fractional, 0,
negative, huge), no heartbeat, a damaged database, a state "folder" that is a file.

Alone: `cd tests && PYTHONPATH="../src;." python -X utf8 -m unittest rustdiff.diffs_advcodex_booted`.
"""
from __future__ import annotations

from pathlib import Path

from rustdiff import advref
from rustdiff.advcodexd import TAG, AdvCodexRestDiff

SEED = r'''
import sys
from pathlib import Path
from codex_auto_resume.store import Store
state, booted, beat = Path(sys.argv[1]), sys.argv[2], sys.argv[3] == "1"
with Store(state) as store:
    if beat:
        store.heartbeat(1767225600.0, pid=4242, session_id="s", started_at=1767225500.0, ok=True, engine_state="idle",
                        code_version="0.6.26", booted_at=None if booted == "none" else float(booted))
'''


class BootedDiff(AdvCodexRestDiff):
    def test_booted_of(self):
        root = self.fresh("booted")
        homes = {"missing": None, "empty": "empty", "whole": ("1767200000", True), "fraction": ("1767200000.125", True),
                 "zero": ("0", True), "negative": ("-5", True), "huge": ("1e300", True), "none": ("none", True),
                 "nobeat": ("1", False), "damaged": "damaged", "file": "file"}

        def setup():
            for name, how in homes.items():
                folder = root / name
                if how == "empty":
                    folder.mkdir(parents=True)
                elif how == "damaged":
                    folder.mkdir(parents=True)
                    (folder / "state.sqlite").write_bytes(b"not a database at all" * 50)
                elif how == "file":
                    folder.parent.mkdir(parents=True, exist_ok=True)
                    folder.write_bytes(b"x")
                elif isinstance(how, tuple):
                    done = advref.run(SEED, str(folder), how[0], "1" if how[1] else "0", profile=root, tag=TAG)
                    self.assertEqual(done.returncode, 0, done.stderr[-2000:])

        cases = [["bt.booted_of", str(root / name)] for name in homes]
        cases += [["bt.booted_of", str(root / name)] for name in homes]
        want, _ = self.scene("booted", cases, setup, [root])
        self.assertIn(1767200000.125, [one.get("ok") for one in want])
