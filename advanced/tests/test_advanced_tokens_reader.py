"""The rollout reader of usage_analytics (v0.6.19, codex/tokens.py): four numbers and a turn count from each rollout,
read from where the last pass stopped, within its byte caps - never a word of a prompt, a tool's output or reasoning.

    PYTHONPATH=src;advanced/src python -m unittest discover -s advanced/tests -p test_advanced_tokens_reader.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

from codex_auto_resume_advanced.codex import tokens

THREAD = "0199a000-0000-7000-8000-00000000000a"
OTHER = "0199a000-0000-7000-8000-00000000000b"
SECRET = "SECRET-PROMPT-WORDS"


def utc(at):
    return time.gmtime(at)


def stamp(at):
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(at))


def meta(thread=THREAD, cwd="C:\\work\\ExampleProject"):
    return {"timestamp": stamp(1_800_000_000), "type": "session_meta",
            "payload": {"id": thread, "cwd": cwd, "instructions": SECRET}}


def counts(at, last, total, words=True):
    """A token_count event - with words beside the numbers, as a test of what is kept."""
    usage = lambda numbers: dict(zip(tokens.KINDS + ("total_tokens",), numbers + [sum(numbers)]))
    info = {"total_token_usage": usage(total), "model_context_window": 400000}
    if last is not None:
        info["last_token_usage"] = usage(last)
    payload = {"type": "token_count", "info": info, "rate_limits": {"primary": {"used_percent": 12.0}}}
    if words:
        payload["note"] = SECRET + " tool output and reasoning text"
    return {"timestamp": stamp(at), "type": "event_msg", "payload": payload}


def started(at):
    return {"timestamp": stamp(at), "type": "event_msg", "payload": {"type": "task_started", "turn_id": OTHER}}


def message(at):
    """A line of words alone, which holds the bytes "token_count" in what a person wrote."""
    return {"timestamp": stamp(at), "type": "response_item",
            "payload": {"type": "message", "content": [{"text": SECRET + ' about "token_count" events'}]}}


def lines(*events) -> bytes:
    return b"".join(json.dumps(event).encode("utf-8") + b"\n" for event in events)


class ReaderCase(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.home = Path(self.folder.name) / "codex-home"
        self.day = self.home / "sessions" / "2027" / "01" / "15"
        self.day.mkdir(parents=True)
        self.now = 1_800_000_000 + 3600

    def tearDown(self):
        self.folder.cleanup()

    def write(self, data, name="rollout-2027-01-15T00-00-00-%s.jsonl" % THREAD, mode="wb"):
        path = self.day / name
        with path.open(mode) as stream:
            stream.write(data)
        return path

    def found(self):
        return {rollout.path.name: rollout for rollout in tokens.rollouts([self.home], self.now)}

    def one(self, known=None, budget=tokens.PASS_BYTES, name=None):
        rollouts = self.found()
        rollout = rollouts[name] if name else next(iter(rollouts.values()))
        return tokens.read(rollout, known, budget, local=utc)


class NumbersTests(ReaderCase):
    def test_only_the_four_numbers_and_the_turns_survive_of_lines_full_of_words(self):
        at = 1_800_000_000
        self.write(lines(meta(), started(at + 1), message(at + 2), counts(at + 3, [100, 40, 20, 5], [100, 40, 20, 5]),
                         counts(at + 4, [10, 4, 2, 1], [110, 44, 22, 6]), started(at + 5)))
        read = self.one()
        day = time.strftime("%Y-%m-%d", utc(at))
        self.assertEqual(read.thread_id, THREAD)
        self.assertEqual(read.days, {day: [110, 44, 22, 6, 2]})
        self.assertEqual(read.outcome, tokens.READ)
        self.assertNotIn(SECRET, repr(read))
        self.assertNotIn("ExampleProject", repr(read))
        self.assertRegex(read.project_key, r"\A[0-9a-f]{16}\Z")

    def test_totals_are_differenced_where_codex_writes_no_last_usage_and_a_repeat_counts_once(self):
        at = 1_800_000_000
        self.write(lines(meta(), counts(at, None, [100, 0, 10, 0]), counts(at + 1, None, [100, 0, 10, 0]),
                         counts(at + 2, None, [150, 20, 30, 5])))
        read = self.one()
        self.assertEqual(list(read.days.values()), [[150, 20, 30, 5, 0]])

    def test_each_event_counts_on_the_local_day_it_fell_on(self):
        midnight = 1_800_000_000 - 1_800_000_000 % 86400 + 86400
        self.write(lines(meta(), counts(midnight - 1, [1, 0, 1, 0], [1, 0, 1, 0]),
                         counts(midnight + 1, [2, 0, 2, 0], [3, 0, 3, 0])))
        self.now = midnight + 3600
        read = self.one()
        self.assertEqual(read.days, {time.strftime("%Y-%m-%d", utc(midnight - 1)): [1, 0, 1, 0, 0],
                                     time.strftime("%Y-%m-%d", utc(midnight + 1)): [2, 0, 2, 0, 0]})
        # Nine hours east, both fall on the later day.
        east = lambda at: time.gmtime(at + 9 * 3600)
        rollout = next(iter(self.found().values()))
        self.assertEqual(list(tokens.read(rollout, None, tokens.PASS_BYTES, local=east).days.values()),
                         [[3, 0, 3, 0, 0]])

    def test_a_line_longer_than_the_cap_or_malformed_skips_itself(self):
        at = 1_800_000_000
        long_one = counts(at + 1, [9, 9, 9, 9], [9, 9, 9, 9])
        long_one["payload"]["padding"] = "x" * tokens.LINE_BYTES
        data = lines(meta(), long_one) + b'{"type": "event_msg", "token_count" broken\n' + lines(
            counts(at + 2, [1, 0, 0, 0], [1, 0, 0, 0]))
        self.write(data)
        self.assertEqual(list(self.one().days.values()), [[1, 0, 0, 0, 0]])

    def test_a_file_whose_first_line_names_no_conversation_is_passed_over(self):
        self.write(lines({"type": "event_msg", "payload": {"type": "task_started"}}, counts(1_800_000_000, [1, 1, 1, 1],
                                                                                              [1, 1, 1, 1])))
        read = self.one()
        self.assertEqual((read.outcome, read.days, read.thread_id), (tokens.UNREADABLE, {}, None))
        self.assertEqual(read.offset, read.size)


class ResumeTests(ReaderCase):
    def test_a_pass_reads_from_where_the_last_stopped_and_waits_for_a_line_still_being_written(self):
        at = 1_800_000_000
        path = self.write(lines(meta(), counts(at, [5, 0, 5, 0], [5, 0, 5, 0])) + b'{"timestamp": "2027')
        first = self.one()
        self.assertEqual(list(first.days.values()), [[5, 0, 5, 0, 0]])
        self.assertLess(first.offset, first.size)       # the half-written line waits
        known = {"thread_id": THREAD, "offset": first.offset, "size": first.size, "mtime_ns": first.mtime_ns}
        with path.open("ab") as stream:
            stream.write(b'-01-15T00:00:00.000Z"}\n' + lines(counts(at + 9, [7, 1, 2, 0], [12, 1, 7, 0])))
        second = self.one(known)
        self.assertEqual(list(second.days.values()), [[7, 1, 2, 0, 0]])
        self.assertEqual(second.offset, path.stat().st_size)
        self.assertTrue(tokens.unchanged(next(iter(self.found().values())),
                                         {"thread_id": THREAD, "offset": second.offset, "size": second.size,
                                          "mtime_ns": second.mtime_ns}))

    def test_a_shrunk_file_or_one_of_another_conversation_is_read_again_from_its_start(self):
        at = 1_800_000_000
        self.write(lines(meta(), counts(at, [3, 0, 3, 0], [3, 0, 3, 0])))
        read = self.one({"thread_id": THREAD, "offset": 10 ** 9, "size": 10 ** 9, "mtime_ns": 1})
        self.assertEqual(list(read.days.values()), [[3, 0, 3, 0, 0]])
        size = read.size
        read = self.one({"thread_id": OTHER, "offset": size, "size": size, "mtime_ns": 1})
        self.assertEqual(list(read.days.values()), [[3, 0, 3, 0, 0]])
        self.assertEqual(read.offset, size)


class CapTests(ReaderCase):
    def test_one_file_is_read_no_further_than_its_cap_and_the_rest_waits_for_the_next_pass(self):
        at = 1_800_000_000
        event = counts(at, [1, 0, 0, 0], [1, 0, 0, 0], words=False)
        many = lines(*([meta()] + [event] * 4000))
        self.write(many)
        with mock.patch.object(tokens, "FILE_BYTES", 64 * 1024):
            read = self.one()
            self.assertEqual(read.outcome, tokens.CAPPED)
            self.assertLessEqual(read.consumed, 64 * 1024)
            self.assertLess(read.offset, read.size)
            # A smaller budget left in the pass is the cap.
            smaller = self.one(budget=1000)
            self.assertLessEqual(smaller.consumed, 1000)
            # Pass after pass, the whole file is read once.
            known, total = None, 0
            for _ in range(200):
                read = self.one(known)
                total += sum(numbers[0] for numbers in read.days.values())
                known = {"thread_id": read.thread_id, "offset": read.offset, "size": read.size,
                         "mtime_ns": read.mtime_ns}
                if read.offset >= read.size:
                    break
        # The first line's own totals are counted once, each repeat of them never again.
        self.assertEqual(total, 1)

    def test_a_line_longer_than_a_whole_read_is_skipped_past(self):
        with mock.patch.object(tokens, "FILE_BYTES", 4096):
            self.write(lines(meta()) + b"x" * 10000 + b"\n" + lines(counts(1_800_000_000, [2, 0, 0, 0], [2, 0, 0, 0])))
            known, found = None, []
            for _ in range(10):
                read = self.one(known)
                found.extend(read.days.values())
                known = {"thread_id": read.thread_id, "offset": read.offset, "size": read.size,
                         "mtime_ns": read.mtime_ns}
                if read.offset >= read.size:
                    break
        self.assertEqual(found, [[2, 0, 0, 0, 0]])


class WhichFilesTests(ReaderCase):
    def test_only_jsonl_files_changed_in_the_kept_days_are_read_and_the_newest_first(self):
        old = self.write(lines(meta()), name="rollout-old-%s.jsonl" % THREAD)
        os.utime(old, (self.now - 100 * 86400, self.now - 100 * 86400))
        newer = self.write(lines(meta(OTHER)), name="rollout-new-%s.jsonl" % OTHER)
        os.utime(newer, (self.now - 10, self.now - 10))
        middle = self.write(lines(meta()), name="rollout-mid-%s.jsonl" % THREAD)
        os.utime(middle, (self.now - 100, self.now - 100))
        self.write(b"{}", name="notes.txt")
        self.assertEqual([rollout.path.name for rollout in tokens.rollouts([self.home], self.now)],
                         [newer.name, middle.name])

    def test_a_link_to_a_folder_outside_the_home_is_never_followed(self):
        import _winapi
        outside = Path(self.folder.name) / "elsewhere"
        outside.mkdir()
        (outside / ("rollout-x-%s.jsonl" % THREAD)).write_bytes(lines(meta()))
        try:
            _winapi.CreateJunction(str(outside), str(self.home / "sessions" / "linked"))
        except OSError as error:                         # pragma: no cover - a file system with no junctions
            self.skipTest("no junction: %s" % error)
        self.write(lines(meta()))
        names = [rollout.path.name for rollout in tokens.rollouts([self.home], self.now)]
        self.assertEqual(names, ["rollout-2027-01-15T00-00-00-%s.jsonl" % THREAD])

    def test_the_key_is_a_digest_of_the_full_path_and_never_the_path(self):
        path = self.write(lines(meta()))
        key = tokens.file_key(path)
        self.assertRegex(key, r"\A[0-9a-f]{16}\Z")
        self.assertNotEqual(key, tokens.file_key(path.with_name("other.jsonl")))
        self.assertEqual(key, tokens.file_key(str(path).upper()))


if __name__ == "__main__":
    unittest.main()
