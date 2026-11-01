"""MGAVE: which code a turn records when its model stays at capacity through Codex's own retries (v0.6.20).

The question of plans/v0620-capability-pairs.md: a turn whose model stays serverOverloaded while Codex retries - does
the failed turn record serverOverloaded, or responseTooManyFailedAttempts (codex_gave_up's terminal_failure)? A real
overload cannot be made on demand, so the probe reads what a Codex home kept: each failed turn's code in the history's
database, and in its rollout the stream_error events - Codex's retries - before the failure, with the last one's code.

Every home here is synthetic, in a temporary folder: a history database, a state database and rollouts written by the
test. No Codex runs and no real home is read.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import contextlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_advanced_measure_stage4 import VERSIONS, Backend  # noqa: E402
from codex_auto_resume_advanced import measure  # noqa: E402
from codex_auto_resume_advanced.codex import protocol  # noqa: E402
from codex_auto_resume_advanced.vocabulary import Measurement  # noqa: E402

SENTINEL = "PRIVATE-WORDS-9d2a"


def uuid(index):
    return "%08x-0000-7000-8000-%012x" % (index, index)


def event(kind, **payload):
    return {"timestamp": "2026-10-31T00:00:00.000Z", "type": "event_msg", "payload": dict(type=kind, **payload)}


class Home:
    """A synthetic Codex home: each conversation's rollout and its turns in the history's database."""

    def __init__(self, root):
        self.root = root
        (root / "sessions").mkdir(parents=True)
        self.turns = []
        self.threads = []

    def conversation(self, index, *turns, folder="sessions", split=None, offset=True):
        """`turns`: each (turn index, its retries' codes, the code it failed with or None for a completed turn, how many
        days ago it ended). `folder`: sessions, or archived_sessions where Codex moves an archived conversation's
        rollout; `split`: the index of the id Codex split the conversation's turns under (issue #30) - its file
        `..._A_B.jsonl`, its turns under B, and no row of B's; `offset`: whether the history kept each failure's end
        byte."""
        thread = uuid(index)
        recorded = thread if split is None else uuid(split)
        name = thread if split is None else "%s_%s" % (thread, recorded)
        path = self.root / folder / ("rollout-2026-10-31T00-00-00-%s.jsonl" % name)
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [{"type": "session_meta", "payload": {"id": thread, "originator": "codex_desktop"}}]
        data = b""
        for turn_index, retries, code, days in turns:
            turn = uuid(1000 + turn_index)
            lines.append(event("task_started", turn_id=turn))
            lines.append({"type": "response_item", "payload": {"type": "message", "content": SENTINEL}})
            for retry in retries:
                lines.append(event("stream_error", message="Reconnecting... " + SENTINEL, codex_error_info=retry))
            if code is not None:
                lines.append(event("error", message=SENTINEL, codex_error_info=code))
                lines.append(event("task_complete", turn_id=turn, last_agent_message=None,
                                   error={"codex_error_info": code, "message": SENTINEL}))
            else:
                lines.append(event("task_complete", turn_id=turn, last_agent_message=SENTINEL))
            data = b"".join(json.dumps(line).encode("utf-8") + b"\n" for line in lines)
            if code is not None:
                camel = measure._code_word(code)
                info = camel if isinstance(code, str) else {camel: {"httpStatusCode": 529}}
                self.turns.append((recorded, turn, "failed",
                                   json.dumps({"message": SENTINEL, "codexErrorInfo": info}),
                                   int(time.time()) - days * 86400, len(data) if offset else None))
        path.write_bytes(data)
        self.threads.append((thread, str(path)))
        return self

    def write(self):
        with contextlib.closing(sqlite3.connect(self.root / "thread_history_1.sqlite")) as db:
            db.execute("CREATE TABLE thread_turns (thread_id TEXT, turn_id TEXT, status TEXT, error_json TEXT, "
                       "started_at INTEGER, completed_at INTEGER, rollout_ordinal INTEGER, "
                       "rollout_end_byte_offset INTEGER, first_user_item_id TEXT)")
            db.executemany("INSERT INTO thread_turns VALUES (?, ?, ?, ?, 1, ?, 0, ?, NULL)", self.turns)
            db.commit()
        with contextlib.closing(sqlite3.connect(self.root / "state_5.sqlite")) as db:
            db.execute("CREATE TABLE threads (id TEXT, rollout_path TEXT, source TEXT, thread_source TEXT, "
                       "history_mode TEXT, title TEXT)")
            db.executemany("INSERT INTO threads VALUES (?, ?, 'vscode', 'user', 'paginated', ?)",
                           [(thread, path, SENTINEL) for thread, path in self.threads])
            db.commit()
        return self.root


class MgaveCase(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.dir, ignore_errors=True))
        self.home = Home((self.dir / "codex").resolve())

    def run_mgave(self, home=None):
        home = self.home.write() if home is None else home
        summary = measure.run(Measurement.MGAVE, backend=Backend(home), versions=VERSIONS,
                              clock=lambda: 1_800_000_000.0, directory=self.dir)
        text = Path(summary["recorded"]).read_text(encoding="utf-8")
        self.assertNotIn(SENTINEL, text)
        for thread, _path in self.home.threads:
            self.assertNotIn(thread, text)
        for turn in self.home.turns:
            self.assertNotIn(turn[0], text)
            self.assertNotIn(turn[1], text)
        self.assertNotIn(str(self.dir), text)
        return json.loads(text)


class VerdictTests(MgaveCase):
    def test_capacity_retries_then_server_overloaded_is_a_pass(self):
        self.home.conversation(1, (1, ["server_overloaded"] * 3, "server_overloaded", 2),
                               (2, [], None, 1))
        self.home.conversation(2, (3, [], "server_overloaded", 5))
        record = self.run_mgave()
        self.assertEqual(record["verdict"], "pass", record)
        observed = record["observed"]
        self.assertEqual((observed["failed_turns"], observed["overloaded_turns"],
                          observed["overloaded_after_capacity_retries"], observed["overloaded_without_retries"],
                          observed["gave_up_turns"], observed["retries_seen"], observed["days_read"]),
                         (2, 2, 1, 1, 0, 3, 90))

    def test_capacity_retries_then_too_many_failed_attempts_is_a_fail(self):
        """The answer that makes model_fallback also answer codex_gave_up's kind - in the rollout's snake_case, with
        the tagged form the history writes."""
        self.home.conversation(1, (1, ["server_overloaded"] * 5, "server_overloaded", 3))
        self.home.conversation(2, (2, ["response_stream_disconnected", "server_overloaded"],
                                   {"response_too_many_failed_attempts": {"http_status_code": 529}}, 1))
        record = self.run_mgave()
        self.assertEqual(record["verdict"], "fail", record)
        observed = record["observed"]
        self.assertEqual((observed["gave_up_turns"], observed["gave_up_after_capacity_retries"],
                          observed["overloaded_after_capacity_retries"]), (1, 1, 1))
        self.assertIn("responseTooManyFailedAttempts", record["note"])

    def test_a_give_up_whose_last_retry_was_not_capacity_answers_nothing(self):
        self.home.conversation(1, (1, ["server_overloaded", "response_stream_disconnected"],
                                   {"response_too_many_failed_attempts": {"http_status_code": None}}, 1))
        record = self.run_mgave()
        self.assertEqual((record["verdict"], record["observed"]["gave_up_after_other_retries"]), ("blocked", 1))

    def test_retries_of_an_earlier_turn_are_never_this_ones(self):
        self.home.conversation(1, (1, ["server_overloaded"] * 4, None, 2),
                               (2, [], {"response_too_many_failed_attempts": {"http_status_code": 529}}, 1))
        observed = self.run_mgave()["observed"]
        self.assertEqual((observed["gave_up_without_retries"], observed["gave_up_after_capacity_retries"]), (1, 0))

    def test_turns_older_than_ninety_days_are_not_read(self):
        self.home.conversation(1, (1, ["server_overloaded"], "server_overloaded", 120))
        record = self.run_mgave()
        self.assertEqual((record["verdict"], record["observed"]["failed_turns"]), ("blocked", 0))


class BlockedTests(MgaveCase):
    def test_no_history_is_blocked(self):
        record = self.run_mgave(home=self.dir / "empty")
        self.assertEqual((record["verdict"], record["observed"]["history_read"]), ("blocked", False))

    def test_failed_turns_whose_rollouts_kept_no_retry_say_so(self):
        self.home.conversation(1, (1, [], "server_overloaded", 1))
        self.home.conversation(2, (2, [], {"response_too_many_failed_attempts": {"http_status_code": 529}}, 1))
        record = self.run_mgave()
        self.assertEqual(record["verdict"], "blocked")
        self.assertIn("may not write its retries", record["note"])

    def test_a_rollout_outside_the_codex_home_is_never_opened(self):
        """The row names a file outside the home: it is not opened, and with no file of that id left in the home the
        turn's rollout counts as missing - though the file outside holds a capacity retry."""
        self.home.conversation(1, (1, ["server_overloaded"], "server_overloaded", 1))
        thread, path = self.home.threads[0]
        moved = self.dir / ("rollout-%s.jsonl" % thread)
        shutil.move(path, moved)
        self.home.threads[0] = (thread, str(moved))
        record = self.run_mgave()
        observed = record["observed"]
        self.assertEqual((record["verdict"], observed["rollouts_missing"], observed["rollouts_read"],
                          observed["retries_seen"]), ("blocked", 1, 0, 0))

    def test_a_rollout_that_is_gone_counts_as_missing_not_unread(self):
        self.home.conversation(1, (1, ["server_overloaded"], "server_overloaded", 1))
        Path(self.home.threads[0][1]).unlink()
        observed = self.run_mgave()["observed"]
        self.assertEqual((observed["rollouts_missing"], observed["rollouts_unread"], observed["rollouts_read"]),
                         (1, 0, 0))

    def test_a_linked_rollout_is_never_followed(self):
        self.home.conversation(1, (1, ["server_overloaded"], "server_overloaded", 1))
        thread, path = self.home.threads[0]
        outside = self.dir / "elsewhere.jsonl"
        shutil.move(path, outside)
        try:
            Path(path).symlink_to(outside)
        except OSError:
            self.skipTest("this account cannot make a symbolic link")
        observed = self.run_mgave()["observed"]
        self.assertEqual((observed["rollouts_missing"], observed["rollouts_read"]), (1, 0))


class FoundTests(MgaveCase):
    """v0.6.20 final: the first run on a real home left 24 of 30 overloaded turns' rollouts unread - each was looked for
    only where its `threads` row named it inside the sessions folder, and only with the history's end byte."""

    def assert_read(self, observed, **counts):
        self.assertEqual((observed["overloaded_after_capacity_retries"], observed["retries_seen"],
                          observed["rollouts_read"], observed["rollouts_unread"], observed["rollouts_missing"]),
                         (1, 2, 1, 0, 0), observed)
        for key, value in counts.items():
            self.assertEqual(observed[key], value, key)

    def test_an_archived_conversations_rollout_is_read(self):
        self.home.conversation(1, (1, ["server_overloaded"] * 2, "server_overloaded", 3), folder="archived_sessions")
        record = self.run_mgave()
        self.assertEqual(record["verdict"], "pass", record)
        self.assert_read(record["observed"], rollouts_archived=1, rollouts_found_by_name=0)

    def test_a_split_ids_turns_are_read_from_its_file_by_name(self):
        """Codex records a split conversation's turns under B, which has no `threads` row; its file is ..._A_B.jsonl."""
        self.home.conversation(1, (1, ["server_overloaded"] * 2, "server_overloaded", 3), split=7)
        record = self.run_mgave()
        self.assertEqual(record["verdict"], "pass", record)
        self.assert_read(record["observed"], rollouts_found_by_name=1, rollouts_archived=0)

    def test_a_rollout_moved_to_archived_sessions_behind_its_row_is_found_by_name(self):
        self.home.conversation(1, (1, ["server_overloaded"] * 2, "server_overloaded", 3))
        thread, path = self.home.threads[0]
        archived = self.home.root / "archived_sessions"
        archived.mkdir()
        shutil.move(path, archived / Path(path).name)
        self.assert_read(self.run_mgave()["observed"], rollouts_found_by_name=1)

    def test_a_turn_with_no_end_byte_is_read_to_its_own_end(self):
        self.home.conversation(1, (1, ["server_overloaded"] * 2, "server_overloaded", 3),
                               (2, ["response_stream_disconnected"], None, 1), offset=False)
        self.assert_read(self.run_mgave()["observed"], offsets_missing=1)

    def test_a_turn_that_began_before_the_look_back_is_read_from_its_start(self):
        """Its retries stand early, its failure far later: the look-back alone sees neither its start nor a retry."""
        self.home.conversation(1, (1, ["server_overloaded"] * 2, "server_overloaded", 3))
        path = Path(self.home.threads[0][1])
        lines = path.read_bytes().split(b"\n")
        error_at = next(i for i, line in enumerate(lines) if b'"type": "error"' in line)
        filler = [json.dumps(event("token_count", info=SENTINEL * 40)).encode("utf-8")] * 200
        data = b"\n".join(lines[:error_at] + filler + lines[error_at:])
        path.write_bytes(data)
        self.home.turns[0] = self.home.turns[0][:5] + (len(data),)
        original = measure._MGAVE_SCAN_BYTES
        measure._MGAVE_SCAN_BYTES = 4096
        self.addCleanup(setattr, measure, "_MGAVE_SCAN_BYTES", original)
        self.assert_read(self.run_mgave()["observed"], turn_starts_unseen=0)

    def test_a_turn_whose_start_is_not_in_its_rollout_is_counted_apart(self):
        self.home.conversation(1, (1, ["server_overloaded"] * 2, "server_overloaded", 3))
        path = Path(self.home.threads[0][1])
        path.write_bytes(path.read_bytes().replace(b'"task_started"', b'"task_begun"'))
        record = self.run_mgave()
        observed = record["observed"]
        self.assertEqual((record["verdict"], observed["rollouts_read"], observed["turn_starts_unseen"],
                          observed["retries_seen"]), ("blocked", 1, 1, 0))
        self.assertNotIn("may not write its retries", record["note"])


class ShapeTests(unittest.TestCase):
    def test_it_has_a_probe_and_calls_no_method(self):
        self.assertIn(Measurement.MGAVE, measure.PROBES)
        self.assertEqual(protocol.methods_for(Measurement.MGAVE), {"initialize", "initialized"})

    def test_a_code_is_read_in_either_case_and_either_form(self):
        self.assertEqual(measure._code_word("server_overloaded"), "serverOverloaded")
        self.assertEqual(measure._code_word("serverOverloaded"), "serverOverloaded")
        self.assertEqual(measure._code_word({"response_too_many_failed_attempts": {}}),
                         "responseTooManyFailedAttempts")
        self.assertIsNone(measure._code_word({"a": 1, "b": 2}))
        self.assertIsNone(measure._code_word("words with spaces"))


if __name__ == "__main__":
    unittest.main()
