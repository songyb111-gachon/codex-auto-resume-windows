"""P19, which conversations of the Codex app core takes up (v0.6.16-beta.3): a person's own alone (A15) unless the
edition's plug widens it to every desktop conversation but the kinds Codex makes for itself.

The standard edition's plug, NULL, answers the empty set, so what is detected is exactly what it was - issue #27's
widening to the handed-over and the unlabelled conversations included (test_source holds those). Widened, a label
Codex adds tomorrow is taken up; a subagent, a review, a memory pass and an agent-made conversation never are, and
every other check of a conversation stands: the app's own originator, the state row and the rollout saying the same.

    PYTHONPATH=src;tests python -m unittest test_eligibility
"""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import codexsim
from codex_auto_resume.codex import LocalSource
from codex_auto_resume.codex.values import INTERNAL_THREAD_SOURCES, OWN_THREAD_SOURCES, taken_thread_source
from codex_auto_resume.domain.plug import NULL, Plug, Point, guard
from codex_auto_resume.domain.plughands import Widening, widening_of
from test_plug_points import PluggedCase
from test_source import closing_db

WIDE = frozenset({Widening.EVERY_DESKTOP})


class PredicateTests(unittest.TestCase):
    def test_unwidened_it_is_a_persons_own_and_nothing_else(self):
        for value in OWN_THREAD_SOURCES:
            self.assertTrue(taken_thread_source(value))
        for value in ("subagent", "guardian_review", "agent_created_thread", "a_label_from_tomorrow", ""):
            self.assertFalse(taken_thread_source(value), value)

    def test_widened_every_label_but_codexs_own_kinds(self):
        self.assertEqual(INTERNAL_THREAD_SOURCES,
                         {"subagent", "guardian_review", "memory_consolidation", "agent_created_thread"})
        for value in INTERNAL_THREAD_SOURCES:
            self.assertFalse(taken_thread_source(value, WIDE), value)
        for value in (*OWN_THREAD_SOURCES, "a_label_from_tomorrow"):
            self.assertTrue(taken_thread_source(value, WIDE), value)
        for value in ("", "x" * 65, 7):
            self.assertFalse(taken_thread_source(value, WIDE), value)


class WidenedSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = codexsim.CodexHome(Path(self.temp.name))
        self.source = LocalSource(self.home.root)
        self.since = codexsim.BASE - 1000

    def failing(self, thread_source, **meta):
        thread = codexsim.new_id()
        self.home.add_thread(thread, thread_source=thread_source, **meta)
        self.home.fail_usage(thread)
        return thread

    def detected(self):
        return [row["thread_id"] for row in self.source.latest_failures(self.since)]

    def test_a_new_label_is_taken_up_only_while_widened(self):
        thread = self.failing("a_label_from_tomorrow")
        self.assertNotIn(thread, self.detected(), "a person's own alone, as the standard edition does")
        self.source.widened = WIDE
        self.assertIn(thread, self.detected())
        self.assertIsNotNone(self.source.latest(thread))
        self.source.widened = frozenset()
        self.assertNotIn(thread, self.detected(), "not taken up once the widening is gone")

    def test_codexs_own_kinds_are_never_taken_up_however_wide(self):
        self.source.widened = WIDE
        for value in sorted(INTERNAL_THREAD_SOURCES):
            with self.subTest(value):
                self.assertNotIn(self.failing(value), self.detected())

    def test_every_other_check_of_a_conversation_still_stands(self):
        """Widened, a conversation of another originator, or whose state row and rollout disagree, is not taken up."""
        self.source.widened = WIDE
        foreign = self.failing("a_label_from_tomorrow", originator="codex_vscode")
        split = codexsim.new_id()
        self.home.add_thread(split, thread_source="a_label_from_tomorrow")
        with closing_db(self.home.root / "state_5.sqlite") as db:
            db.execute("UPDATE threads SET thread_source=? WHERE id=?", ("another_label", split))
        self.home.fail_usage(split)
        found = self.detected()
        self.assertNotIn(foreign, found)
        self.assertNotIn(split, found)


class Answers(Plug):
    """A plug whose P19 answer a test sets, and which counts how often it was asked."""
    __slots__ = ("answer", "asked")

    def __init__(self, answer):
        self.answer, self.asked = answer, 0

    def eligibility(self):
        self.asked += 1
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


class PointTests(PluggedCase):
    def test_the_standard_editions_plug_widens_nothing(self):
        self.assertEqual(guard(NULL).eligibility(), frozenset())
        self.due()
        self.h.tick()
        self.assertEqual(self.h.source.widened, frozenset())

    def test_what_core_takes_of_an_answer_is_widening_words_alone(self):
        for answer in ("every_desktop", ["every_desktop"], {"every_desktop", "everything"}, None, 3, object()):
            with self.subTest(answer=answer):
                self.assertEqual(widening_of(answer), frozenset())
        self.assertEqual(widening_of({"every_desktop"}), WIDE)
        self.assertEqual(widening_of((Widening.EVERY_DESKTOP,)), WIDE)

    def test_the_engine_asks_once_a_tick_and_reads_conversations_by_the_answer(self):
        plug = Answers(frozenset({"every_desktop"}))
        self.plugged(plug)
        self.h.tick()
        self.assertEqual((plug.asked, self.h.source.widened), (1, WIDE))

    def test_a_hook_that_raises_widens_nothing(self):
        plug = Answers(RuntimeError("no"))
        engine = self.plugged(plug)
        self.h.tick()
        self.assertEqual(self.h.source.widened, frozenset())
        self.assertGreaterEqual(engine.plug.failures, 1)

    def test_a_paused_watcher_asks_nothing_and_keeps_what_it_had(self):
        plug = Answers(frozenset({"every_desktop"}))
        self.plugged(plug)
        self.h.store.set_enabled(False, self.h.now)
        self.h.tick()
        self.assertEqual((plug.asked, self.h.source.widened), (0, frozenset()))

    def test_p19_is_the_last_point_core_asks_and_its_hook_is_eligibility(self):
        # P19 is the last question; after it comes only P20 (v0.6.19), which tells and is not asked.
        points = list(Point)
        self.assertEqual(points[points.index(Point.ELIGIBILITY) + 1:], [Point.NOTICE])
        self.assertEqual(Point.ELIGIBILITY.value, "eligibility")
        self.assertEqual(json.dumps(sorted(widening_of({"every_desktop"}))), '["every_desktop"]')


if __name__ == "__main__":
    unittest.main()
