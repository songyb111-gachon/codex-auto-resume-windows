# ADVANCED-EDITION-CODE: in the advanced edition's tree, never the standard one's.
"""Find a conversation's bridge command (v0.6.20, issue #50): advanced-conversations answers the person's own
conversations of the Codex home the watcher drives, with their names, newest first, at most 200 - own sources only,
none archived, none the person switched off for recovery, and nothing of what a conversation says. Read-only, the
Dashboard's alone.

Held against a Codex home of the test's own (tests/codexsim.py) and this edition's real bridge in a home of its own.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from codexsim import CodexHome  # noqa: E402
from codex_auto_resume import control, controlcli  # noqa: E402
from codex_auto_resume.store import Store  # noqa: E402
from codex_auto_resume_advanced import surfaces  # noqa: E402
from codex_auto_resume_advanced.codex import inuse, threads  # noqa: E402
from codex_auto_resume_advanced.control import conversations  # noqa: E402
from codex_auto_resume_advanced.vocabulary import BridgeCommand, Refusal  # noqa: E402

PRIVATE = "SENTINEL-the-blue-heron-plan"


@contextlib.contextmanager
def opened(path):
    """A connection to the simulated Codex home's database, committed and closed (an open file cannot be removed)."""
    connection = sqlite3.connect(path)
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def thread(number) -> str:
    return "0a1b2c3d-%04d-7000-8000-%012d" % (number, number)


class ConversationsCase(ac.AdvancedCase):
    def setUp(self):
        super().setUp()
        self.paths.ensure()
        self.advanced = self.plug()
        self.control = control.Control(self.paths, plug=self.advanced)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.codex = CodexHome(Path(folder.name))
        patcher = patch.object(inuse, "home", lambda paths=None: self.codex.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def bridge(self, command="advanced-conversations", argument=None):
        request = {"id": 1, "command": command, "argument": argument or {}}
        out = io.StringIO()
        controlcli.serve(self.control, io.StringIO(json.dumps(request) + "\n"), out)
        return json.loads(out.getvalue())["reply"]["result"]

    def add(self, number, name, **row):
        """One conversation in the simulated Codex home; `row` changes what its threads row says."""
        self.codex.add_thread(thread(number), name=name, thread_source=row.pop("thread_source", "user"))
        if row:
            with opened(self.codex.root / "state_5.sqlite") as db:
                for column, value in row.items():
                    db.execute("UPDATE threads SET %s=? WHERE id=?" % column, (value, thread(number)))

    def named(self):
        return [(each["thread_id"], each["name"]) for each in self.bridge()["conversations"]]


class AnswerTests(ConversationsCase):
    def test_own_conversations_with_their_names_newest_first(self):
        """Fails with the command reverted: the bridge does not know it."""
        for number, name in ((1, "Release notes"), (2, "Fix the tray"), (3, "Korean words")):
            self.add(number, name)
        answer = self.bridge()
        self.assertEqual((answer["done"], answer["refusal"], answer["limit"]), (True, None, 200))
        self.assertEqual(self.named(), [(thread(3), "Korean words"), (thread(2), "Fix the tray"),
                                        (thread(1), "Release notes")], "the last written first")
        self.assertEqual(sorted(answer["conversations"][0]), ["name", "thread_id"], "an id and a name, nothing more")

    def test_codex_s_last_change_orders_them_when_it_keeps_one(self):
        for number, name in ((1, "Old one"), (2, "Newest one"), (3, "Middle one")):
            self.add(number, name)
        with opened(self.codex.root / "state_5.sqlite") as db:
            db.execute("ALTER TABLE threads ADD COLUMN updated_at_ms INTEGER")
            for number, at in ((1, 10), (2, 30), (3, 20)):
                db.execute("UPDATE threads SET updated_at_ms=? WHERE id=?", (at, thread(number)))
        self.assertEqual([name for _, name in self.named()], ["Newest one", "Middle one", "Old one"])

    def test_only_a_person_s_own_conversations_and_none_archived_or_unnamed(self):
        self.add(1, "Mine")
        self.add(2, "A subagent", thread_source="subagent")
        self.add(3, "A review", thread_source="guardian_review")
        self.add(4, "Archived", archived=1)
        self.add(5, "From the CLI", source="cli")
        self.add(6, None)
        self.add(7, "Handed over", thread_source="chatgpt_handoff")
        self.add(8, "Unlabelled", thread_source=None)
        self.assertEqual({name for _, name in self.named()}, {"Mine", "Handed over", "Unlabelled"})

    def test_a_conversation_switched_off_is_not_offered_and_takes_no_place(self):
        """Per-conversation consent: it is core's, read before the count is made."""
        for number in range(1, 4):
            self.add(number, "Conversation %d" % number)
        with Store(self.paths.state_dir) as store:
            store.set_thread_enabled(thread(2), False)
        self.assertEqual([name for _, name in self.named()], ["Conversation 3", "Conversation 1"])
        with patch.object(conversations, "LIMIT", 2):
            self.assertEqual([name for _, name in self.named()], ["Conversation 3", "Conversation 1"],
                             "the one off took no place of the two offered")

    def test_at_most_two_hundred(self):
        with opened(self.codex.root / "state_5.sqlite") as db:
            for number in range(1, 251):
                db.execute("INSERT INTO threads (id, rollout_path, source, thread_source, archived, history_mode, name) "
                           "VALUES (?, NULL, 'vscode', 'user', 0, 'paginated', ?)", (thread(number), "Name %d" % number))
        found = self.bridge()["conversations"]
        self.assertEqual(len(found), 200)
        self.assertEqual(found[0]["name"], "Name 250")

    def test_nothing_of_a_conversation_s_text_is_read_and_nothing_is_written(self):
        self.add(1, "Named")
        with opened(self.codex.root / "state_5.sqlite") as db:
            db.execute("UPDATE threads SET title=?, first_user_message=?, preview=?, cwd=? WHERE id=?",
                       (PRIVATE, PRIVATE, PRIVATE, PRIVATE, thread(1)))
        before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in self.codex.root.glob("*.sqlite")}
        answer = self.bridge()
        self.assertNotIn(PRIVATE, json.dumps(answer))
        after = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in self.codex.root.glob("*.sqlite")}
        self.assertEqual(after, before, "read-only")

    def test_a_name_that_is_a_paragraph_is_not_offered(self):
        self.add(1, "first line\nsecond line")
        self.add(2, "x" * 500)
        self.assertEqual([name for _, name in self.named()], ["x" * 71 + "…"])

    def test_an_unreadable_codex_home_is_a_refusal_not_a_guess(self):
        (self.codex.root / "state_5.sqlite").unlink()
        answer = self.bridge()
        self.assertEqual((answer["done"], answer["refusal"]), (False, Refusal.STATE_UNAVAILABLE))

    def test_it_takes_no_argument_and_no_mcp_tool_reaches_it(self):
        self.assertEqual(surfaces.ARGUMENTS[BridgeCommand.ADVANCED_CONVERSATIONS], frozenset())
        self.assertEqual(self.bridge("advanced-conversations", {"thread_id": thread(1)})["refusal"],
                         Refusal.INVALID_REQUEST)
        self.assertNotIn("conversations", json.dumps(sorted(str(name) for name in getattr(surfaces, "MCP_TOOLS", ()))))


class StatementTests(unittest.TestCase):
    """The reader's SQL is its STATEMENTS: each selects the id, the name and the four columns that judge whose a
    conversation is - no title, no first message, no preview, no folder - and every execute runs one of them."""

    def test_no_statement_selects_a_content_column(self):
        for statement in threads.STATEMENTS:
            columns = re.match(r"SELECT (.*?) FROM threads", statement).group(1)
            self.assertEqual(columns, "id, name, source, thread_source, archived, history_mode")
            for forbidden in ("title", "first_user_message", "preview", "cwd", "rollout_path", "*"):
                self.assertNotIn(forbidden, columns)

    def test_every_statement_run_is_one_named(self):
        source = Path(threads.__file__).read_text(encoding="utf-8")
        for found in re.findall(r"\.execute\((\w+)", source):
            if found.startswith("BY_"):
                self.assertIn(getattr(threads, found), threads.STATEMENTS, found)
        self.assertEqual(len(re.findall(r"\.execute\(BY_", source)), len(threads.STATEMENTS))

    def test_the_cap_is_two_hundred(self):
        self.assertEqual(conversations.LIMIT, 200)


if __name__ == "__main__":
    unittest.main()
