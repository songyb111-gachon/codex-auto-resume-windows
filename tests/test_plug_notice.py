"""P20 (v0.6.19, plans/v0619-design/D-groundwork.md section 3): each notice core raises is told to the edition's plug as
it goes to the card or the toast - its kind, its category word, its record's place in Pending and when, closed words
and numbers only - and only while the plug wants it. The standard edition's NULL plug is told nothing, and its notices
go exactly as they did. Told, not asked: the answer is never read, and a hook that raises costs nothing.

    PYTHONPATH="src;tests" python -m unittest test_plug_notice
"""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for entry in (str(ROOT / "src"), str(ROOT / "tests")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from codex_auto_resume import config, notifier  # noqa: E402
from codex_auto_resume.domain import plug  # noqa: E402
from codex_auto_resume.domain.plug import DEFER, NULL, Plug, Point, guard  # noqa: E402

THREAD = "0a1b2c3d-0001-7000-8000-0000000000aa"
OTHER = "0a1b2c3d-0001-7000-8000-0000000000bb"
KEY = "%064x" % 9
LABELS = {"title": "A conversation of a person's", "project": "C:/Users/ExampleUser/project"}


class Told(Plug):
    """A plug that wants P20 (or not) and keeps what it was told."""
    __slots__ = ("told", "wanted", "raises")

    def __init__(self, wanted=True, raises=False):
        self.told, self.wanted, self.raises = [], wanted, raises

    def notice(self, facts):
        self.told.append(facts)
        if self.raises:
            raise RuntimeError("broken")
        facts["kind"] = "rewritten"                     # a copy: core's facts are not this
        return "an answer nobody reads"

    def wants(self, point):
        return self.wanted and point == Point.NOTICE


def notice(kind="interruption"):
    return types.SimpleNamespace(kind=kind)


def opened(records, closed=None):
    """A store opener as notifier.told takes one: a store whose Pending is `records`, noting when it is closed."""
    def store():
        return types.SimpleNamespace(pending=lambda: list(records),
                                     close=lambda: closed.append(True) if closed is not None else None)
    return store


class GuardTests(unittest.TestCase):
    def test_null_is_told_nothing_and_wants_nothing(self):
        with patch.object(Plug, "notice", side_effect=AssertionError("NULL was told")):
            self.assertIsNone(guard(NULL).notice({"kind": "resumed"}))
        self.assertIs(guard(NULL).wants(Point.NOTICE), False)

    def test_a_plug_that_wants_it_is_told_a_copy_and_its_answer_is_not_read(self):
        """Fails with P20 reverted: no point, no hook, nothing told."""
        told = Told()
        facts = {"kind": "resumed", "category": None, "alias_index": 2, "at": 1.0}
        self.assertIsNone(guard(told).notice(facts))
        self.assertEqual(told.told, [dict(facts, kind="rewritten")])
        self.assertEqual(facts["kind"], "resumed")
        self.assertEqual(plug.HOOKS[Point.NOTICE], "notice")
        self.assertNotIn(Point.NOTICE, plug.ALTERNATIVES, "told, not a decision")

    def test_a_plug_that_wants_nothing_is_told_nothing(self):
        told = Told(wanted=False)
        guard(told).notice({"kind": "resumed"})
        self.assertEqual(told.told, [])

    def test_a_hook_that_raises_costs_nothing_but_its_count(self):
        held = guard(Told(raises=True))
        self.assertIsNone(held.notice({"kind": "failed"}))
        self.assertEqual(held.failures, 1)

    def test_null_answers_defer(self):
        self.assertIs(NULL.notice({}), DEFER)
        self.assertIs(plug.consult(NULL, Point.NOTICE, {}), DEFER)


class FactsTests(unittest.TestCase):
    def test_closed_words_and_numbers_only(self):
        detail = dict(LABELS, thread_id=THREAD, interruption_id=KEY, category="network_transient", reset_at=5)
        closed = []
        pending = opened([{"interruption_id": "%064x" % 1, "thread_id": OTHER}, {"interruption_id": KEY,
                                                                                "thread_id": THREAD}], closed)
        facts = notifier.told(notice(), detail, pending, at=7.0)
        self.assertEqual(closed, [True], "the store it opened is closed")
        self.assertEqual(facts, {"kind": "interruption", "category": "network_transient", "alias_index": 2, "at": 7.0})
        for value in facts.values():
            self.assertNotIn(THREAD, str(value))
            self.assertNotIn(KEY, str(value))
            self.assertNotIn("ExampleUser", str(value))

    def test_an_interruption_with_no_category_is_a_usage_limit_as_its_notice_says(self):
        self.assertEqual(notifier.told(notice(), {"thread_id": THREAD})["category"], "usage_limit")
        self.assertIsNone(notifier.told(notice("resumed"), {"thread_id": THREAD})["category"])

    def test_a_word_that_is_no_failure_category_is_none(self):
        for word in ("approval", "C:/x", 5, "usage limit"):
            with self.subTest(word=word):
                self.assertIsNone(notifier.told(notice("needs_you"), {"category": word})["category"])

    def test_the_place_is_found_by_the_interruption_else_the_conversation_else_none(self):
        pending = opened([{"interruption_id": KEY, "thread_id": OTHER}, {"interruption_id": "%064x" % 2,
                                                                         "thread_id": THREAD}])
        self.assertEqual(notifier.told(notice("resumed"), {"thread_id": THREAD}, pending)["alias_index"], 2)
        self.assertEqual(notifier.told(notice(), {"interruption_id": KEY}, pending)["alias_index"], 1)
        self.assertIsNone(notifier.told(notice(), {"interruption_id": "%064x" % 3}, pending)["alias_index"])
        self.assertIsNone(notifier.told(notice("memory_warning"), {"used": 1}, pending)["alias_index"])

    def test_pending_is_not_read_for_a_notice_about_no_conversation_and_a_failing_read_is_none(self):
        unread = lambda: self.fail("pending was read")
        self.assertIsNone(notifier.told(notice("update_offered"), {"version": "0.6.19"}, unread)["alias_index"])

        def broken():
            raise RuntimeError("the state cannot be read")
        self.assertIsNone(notifier.told(notice(), {"thread_id": THREAD}, broken)["alias_index"])


class AppTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.codex = Path(folder.name) / "codex"
        self.codex.mkdir()
        self.paths = config.Paths(Path(folder.name) / "home")

    def app(self, plugged=NULL):
        from codex_auto_resume import app
        instance = app.App(self.paths, codex_home=self.codex, enable_logging=False)
        instance._plug = guard(plugged)
        return instance

    def announce(self, instance, event, detail):
        delivered = []
        with patch.object(notifier, "deliver", lambda shown, **route: delivered.append((shown.kind, route))
                          or ("toast", True)):
            instance._notifier(types.SimpleNamespace(identity=lambda thread: None))(event, detail)
            instance._show_watcher_notice("memory_warning", {"used": 2, "limit": 1})
        return delivered

    def test_the_standard_edition_delivers_as_before_and_tells_nothing(self):
        """NULL: every notice delivered by its one route, with the arguments it had, and Pending never read."""
        instance = self.app()
        with patch.object(type(instance), "worker_store", side_effect=AssertionError("Pending was read")):
            delivered = self.announce(instance, "starting", {"thread_id": THREAD})
        self.assertEqual([kind for kind, _ in delivered], ["starting", "memory_warning"])
        self.assertEqual(sorted(delivered[0][1]), ["inbox", "setting"])

    def test_a_plug_that_wants_it_is_told_each_notice_before_it_goes(self):
        told = Told()
        instance = self.app(told)
        with patch.object(type(instance), "worker_store",
                          lambda self: opened([{"interruption_id": KEY, "thread_id": THREAD}])()):
            delivered = self.announce(instance, "starting", {"thread_id": THREAD})
        self.assertEqual([kind for kind, _ in delivered], ["starting", "memory_warning"])
        self.assertEqual([(facts["category"], facts["alias_index"]) for facts in told.told], [(None, 1), (None, None)])
        self.assertTrue(all(set(facts) == {"kind", "category", "alias_index", "at"} for facts in told.told))

    def test_a_plug_that_wants_nothing_costs_no_read(self):
        told = Told(wanted=False)
        instance = self.app(told)
        with patch.object(type(instance), "worker_store", side_effect=AssertionError("Pending was read")):
            self.announce(instance, "starting", {"thread_id": THREAD})
        self.assertEqual(told.told, [])

    def test_a_hook_that_raises_never_stops_the_notice(self):
        instance = self.app(Told(raises=True))
        with patch.object(type(instance), "worker_store", lambda self: opened([])()):
            delivered = self.announce(instance, "starting", {"thread_id": THREAD})
        self.assertEqual(len(delivered), 2)

    def test_pending_is_read_from_the_watchers_state(self):
        """The place is read from the watcher's own state, on a connection of its own (App.worker_store)."""
        from codex_auto_resume.store import Store
        store = Store(self.paths.state_dir, migrate=True)
        store.close()
        facts = notifier.told(notice(), {"thread_id": THREAD}, self.app().worker_store)
        self.assertIsNone(facts["alias_index"], "an empty Pending has no place")

    def test_facts_that_cannot_be_made_tell_nothing(self):
        told = Told()

        def broken():
            raise RuntimeError("no facts")
        self.assertIsNone(guard(told).notice(broken))
        self.assertEqual(told.told, [])


if __name__ == "__main__":
    unittest.main()
