"""P22 (v0.6.22, the owner's word of 2026-11-06): while recovery is paused, core asks one question - and only of a plug
that wants it - for the errand that keeps a resident running which sends nothing to Codex. Every other point stays
unasked, so a Pause still beats every send. The standard edition's plug wants nothing and is asked nothing, as before.

    PYTHONPATH="src;tests" python -m unittest test_paused_residents
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from codex_auto_resume.domain.plug import DEFER, NULL, Plug, Point, guard  # noqa: E402
from test_plug_points import Asked, PluggedCase  # noqa: E402


class Errand:
    def __init__(self):
        self.ran = 0

    def run(self, guard):
        self.ran += 1


class Resident(Asked):
    """A plug with a resident: it wants P22 (and, unless told otherwise, P8), answers an errand at each, and notes every
    question it is asked."""
    __slots__ = ("wanted", "errands")

    def __init__(self, wanted=(Point.RESIDENT, Point.TICK), **answers):
        super().__init__(**answers)
        self.wanted = frozenset(wanted)
        self.errands = {"resident": Errand(), "tick": Errand()}

    def wants(self, point):
        return point in self.wanted

    def resident(self, view):
        return self._answer("resident", view) if "resident" in self.answers else self._noted("resident")

    def tick(self, view):
        return self._answer("tick", view) if "tick" in self.answers else self._noted("tick")

    def _noted(self, hook):
        self.asked.append((hook, ()))
        return self.errands[hook]


class PausedTests(PluggedCase):
    def asked(self, plug):
        return [hook for hook, _arguments in plug.asked]

    def test_while_paused_the_resident_is_asked_and_its_errand_run_and_nothing_else_is_asked(self):
        """Fails with P22 reverse-applied: a watcher that restarted while paused would never start the courier again."""
        self.due()
        plug = Resident()
        self.plugged(plug)
        self.h.store.set_enabled(False, self.h.now)
        self.h.tick()
        self.assertEqual(self.asked(plug), ["resident"])
        self.assertEqual((plug.errands["resident"].ran, plug.errands["tick"].ran), (1, 0))
        self.assert_no_send()

    def test_not_paused_it_is_not_asked_and_p8_is(self):
        self.due()
        plug = Resident()
        self.plugged(plug)
        self.h.tick()
        self.assertNotIn("resident", self.asked(plug))
        self.assertIn("tick", self.asked(plug))
        self.assertEqual(plug.errands["resident"].ran, 0)

    def test_a_plug_that_does_not_want_it_is_asked_nothing_while_paused(self):
        """Fails where core asks P22 of every plug: nothing undeclared is started while paused."""
        self.due()
        plug = Resident(wanted=(Point.TICK,))
        self.plugged(plug)
        self.h.store.set_enabled(False, self.h.now)
        self.h.tick()
        self.assertEqual(self.asked(plug), [])
        self.assert_no_send()

    def test_the_administrator_s_pause_is_a_pause_here_too(self):
        self.due()
        plug = Resident()
        self.plugged(plug)
        import dataclasses
        from codex_auto_resume import managed
        self.h.engine.managed = dataclasses.replace(managed.NONE, disable_auto_resume=True)
        self.h.tick()
        self.assertEqual(self.asked(plug), ["resident"])
        self.assert_no_send()

    def test_one_that_raises_costs_itself_and_the_tick_goes_on(self):
        self.due()
        plug = Resident(resident=RuntimeError("no"))
        engine = self.plugged(plug)
        self.h.store.set_enabled(False, self.h.now)
        self.h.tick()
        self.assertGreaterEqual(engine.plug.failures, 1)
        self.assert_no_send()

    def test_an_answer_with_no_run_is_no_errand(self):
        for answer in (None, 3, "run", object(), DEFER):
            with self.subTest(answer=answer):
                self.assertIs(guard(Resident(resident=answer)).resident(object()), DEFER)

    def test_the_standard_edition_s_plug_keeps_none(self):
        self.assertIs(NULL.resident(object()), DEFER)
        self.assertIs(guard(NULL).resident(object()), DEFER)
        self.assertFalse(guard(NULL).wants(Point.RESIDENT))
        self.assertIs(Plug().resident(object()), DEFER)


if __name__ == "__main__":
    unittest.main()
