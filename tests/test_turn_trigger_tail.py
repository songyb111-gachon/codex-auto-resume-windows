"""#54's composer rule reads the end of a long conversation's rollout instead of giving up on it (v0.6.23).

The audit of v0.6.23 (C4): codex/rollout.py turn_trigger answered None for every file over RESCAN_BYTES (32 MiB), so a
conversation Codex made for an agent that a person took over and types into (issue #54) was read as agent-made again
once its tool output passed 32 MiB - and its next usage limit or failure was not recovered. Now such a file is read from
its last RESCAN_BYTES on, the line cut there dropped (kept whole when the cut falls on a line's start): the latest turn
is near the end. A turn found only before that stays unknown. RESCAN_BYTES is made small here, so no file is large;
every file is a scratch one.
"""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from codex_auto_resume.codex import rollout

OLD, NEW = "44444444-4444-4444-8444-444444444444", "55555555-5555-4555-8555-555555555555"
LIMIT = 4096


def started(turn, trigger) -> bytes:
    return (json.dumps({"type": "event_msg", "payload": {"type": "task_started", "turn_id": turn,
                                                         "turn_attribution": {"turn_trigger": trigger}}})
            + "\n").encode("utf-8")


def filler(size) -> bytes:
    """One line of tool output `size` bytes long, its newline included."""
    head = b'{"type":"response_item","payload":{"type":"function_call_output","output":"'
    tail = b'"}}\n'
    return head + b"x" * (size - len(head) - len(tail)) + tail


class Case(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="car-trigger-tail-")
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / ("rollout-2026-11-06T10-00-00-%s.jsonl" % OLD)
        for stand_in in (patch.object(rollout, "RESCAN_BYTES", LIMIT), patch.dict(rollout._TRIGGERS, clear=True)):
            stand_in.start()
            self.addCleanup(stand_in.stop)

    def write(self, *parts):
        self.path.write_bytes(b"".join(parts))
        self.assertGreater(self.path.stat().st_size, LIMIT, "the file must be over the limit")


class TailTests(Case):
    def test_a_file_over_the_limit_still_tells_its_latest_turn(self):
        self.write(started(OLD, "agent"), *[filler(1000)] * 8, started(NEW, "composer"))
        self.assertEqual(rollout.turn_trigger(self.path), "composer")
        self.assertEqual(rollout.turn_trigger(self.path, NEW), "composer")

    def test_a_turn_only_before_the_last_part_stays_unknown(self):
        self.write(started(OLD, "composer"), *[filler(1000)] * 8)
        self.assertIsNone(rollout.turn_trigger(self.path, OLD))
        self.assertIsNone(rollout.turn_trigger(self.path))

    def test_a_line_cut_by_the_start_is_dropped_and_never_misread(self):
        # The task_started line straddles the cut: only its end is in the last LIMIT bytes, so it is not read.
        line = started(NEW, "composer")
        body = filler(LIMIT - len(line) // 2)
        self.write(filler(500), line, body)
        self.assertIsNone(rollout.turn_trigger(self.path))

    def test_a_cut_on_a_lines_start_keeps_that_line(self):
        line = started(NEW, "composer")
        self.write(filler(500), line, filler(LIMIT - len(line)))
        self.assertEqual(rollout.turn_trigger(self.path), "composer")

    def test_a_file_under_the_limit_is_read_from_its_start_as_before(self):
        self.path.write_bytes(started(OLD, "composer") + filler(1000))
        self.assertEqual(rollout.turn_trigger(self.path, OLD), "composer")
        self.assertEqual(rollout.turn_trigger(self.path), "composer")


if __name__ == "__main__":
    unittest.main()
