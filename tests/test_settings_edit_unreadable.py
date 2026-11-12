"""An edit that builds a whole list from the stored settings never builds it on a read that failed just now (v0.6.23).

The audit of v0.6.23 (C2): one conversation's own message, Always or Never for a project, and Not now for a Codex
home each read the stored list, change one entry and save the list whole. The read took the defaults when the file
was held for a moment (an antivirus or a sync tool opening the fresh settings.json: a sharing violation), the save's
own read then saw the file again, and the list built on the defaults was saved over the person's: every other
conversation's message, the Always and Never lists, the folders set aside - gone, and the reply said it was set.
Now such an edit is refused in the save's own words ("try again", request_failed) and the file keeps what it held;
the next click, with the file free, keeps every entry.

Every settings file is a scratch one; the policy keys are a stand-in that holds nothing.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

_HERE = str(Path(__file__).resolve().parent)
for entry in (str(Path(_HERE).parent / "src"), _HERE):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from codex_auto_resume import config, homefind, managed, projects, settings  # noqa: E402
from codex_auto_resume.control import Control, ControlError  # noqa: E402
from codex_auto_resume.control import policy  # noqa: E402

A, B, C = ("11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222",
           "33333333-3333-4333-8333-333333333333")
REAL_READ = Path.read_text


class Case(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        for stand_in in (patch.dict(os.environ, {"CODEX_HOME": str(self.root / "codex")}),
                         patch.object(policy, "managed_policy", lambda: managed.NONE)):
            stand_in.start()
            self.addCleanup(stand_in.stop)
        self.control = Control(config.Paths(self.root / "home"))
        self.failing = 0

    def held_for(self, reads: int):
        """settings.json held by another program for its next `reads` reads (a sharing violation), then free."""
        self.failing = reads
        case = self

        def read_text(path, *args, **kwargs):
            if path.name == "settings.json" and case.failing:
                case.failing -= 1
                raise PermissionError(32, "The process cannot access the file because it is being used "
                                          "by another process")
            return REAL_READ(path, *args, **kwargs)
        return patch.object(Path, "read_text", read_text)

    def stored(self) -> dict:
        return settings.read(self.control.settings_path())

    def assertRefusedToTryAgain(self, call):
        with self.assertRaises(ControlError) as caught:
            call()
        self.assertEqual(caught.exception.code, "request_failed")
        self.assertIn("try again", str(caught.exception))


class ConversationMessageTests(Case):
    def test_a_held_file_refuses_and_keeps_every_other_conversations_message(self):
        self.control.set_conversation_message(A, "keep going on A")
        self.control.set_conversation_message(B, "keep going on B")
        with self.held_for(1):
            self.assertRefusedToTryAgain(lambda: self.control.set_conversation_message(C, "keep going on C"))
        self.assertEqual(sorted(self.stored()[settings.CONVERSATION_MESSAGES]), [A, B])
        answer = self.control.set_conversation_message(C, "keep going on C")
        self.assertEqual(answer["count"], 3)
        self.assertEqual(sorted(self.stored()[settings.CONVERSATION_MESSAGES]), [A, B, C])

    def test_taking_one_away_on_a_held_file_takes_nothing_else_away(self):
        self.control.set_conversation_message(A, "keep going on A")
        self.control.set_conversation_message(B, "keep going on B")
        with self.held_for(1):
            self.assertRefusedToTryAgain(lambda: self.control.set_conversation_message(A, None))
        self.assertEqual(sorted(self.stored()[settings.CONVERSATION_MESSAGES]), [A, B])


class DismissedHomeTests(Case):
    def test_not_now_on_a_held_file_keeps_the_folders_set_aside_before(self):
        first, second = str(self.root / "first"), str(self.root / "second")
        self.control.dismiss_home_suggestion(first)
        before = self.stored()[homefind.DISMISSED]
        self.assertTrue(before)
        with self.held_for(1):
            self.assertRefusedToTryAgain(lambda: self.control.dismiss_home_suggestion(second))
        self.assertEqual(self.stored()[homefind.DISMISSED], before)
        self.control.dismiss_home_suggestion(second)
        self.assertEqual(len(self.stored()[homefind.DISMISSED]), len(before) + 1)


class ProjectRuleTests(Case):
    KEY_ONE, KEY_TWO, KEY_NEW, RECORD = "1" * 64, "2" * 64, "3" * 64, "a" * 64

    def setUp(self):
        super().setUp()
        record = {"interruption_id": self.RECORD, "thread_id": A, "home_key": "", "hold": None, "state": "detected"}
        key = self.KEY_NEW
        for stand_in in (patch.object(Control, "_bound_record", lambda _self, _store, _key, _thread: record),
                         patch.object(Control, "_project_of", lambda _self, _reader, _thread: key)):
            stand_in.start()
            self.addCleanup(stand_in.stop)
        self.assertTrue(projects.is_key(self.KEY_NEW), "the stand-in key must be a project key")

    def test_always_on_a_held_file_keeps_both_lists(self):
        settings.save(self.control.settings_path(), dict(settings.defaults(), **{
            projects.ALWAYS: projects.format_keys({self.KEY_ONE}),
            projects.NEVER: projects.format_keys({self.KEY_TWO})}))
        before = self.stored()
        # The first read is the one that finds the other homes (a view); the second builds the lists.
        with self.held_for(2):
            self.assertRefusedToTryAgain(
                lambda: self.control.set_project_rule(self.RECORD, A, True))
        after = self.stored()
        self.assertEqual(after[projects.ALWAYS], before[projects.ALWAYS])
        self.assertEqual(after[projects.NEVER], before[projects.NEVER])
        self.assertEqual(after["project_policy"], before["project_policy"])


class StoredSettingsTests(Case):
    def test_a_file_that_holds_no_json_is_refused_too_and_kept(self):
        """v0.6.23 (audit K1): a file with no settings in it is no longer repaired by an edit with the defaults over the
        person's choices; the edit is refused and the file kept, and Restore defaults sets it aside first."""
        path = self.control.settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ not json", encoding="utf-8")
        with self.assertRaises(ControlError) as raised:
            self.control.set_conversation_message(A, "keep going on A")
        self.assertEqual(raised.exception.code, "request_failed")
        self.assertEqual(path.read_text(encoding="utf-8"), "{ not json")

    def test_the_view_still_shows_the_defaults_for_a_held_file(self):
        """get_settings is what a surface shows: the defaults for a file held just now, as before."""
        self.control.set_conversation_message(A, "keep going on A")
        with self.held_for(1):
            self.assertEqual(self.control.get_settings()[settings.CONVERSATION_MESSAGES],
                             settings.defaults()[settings.CONVERSATION_MESSAGES])


if __name__ == "__main__":
    unittest.main()
