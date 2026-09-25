"""The engine is one class, however many files it is written in.

The same check the store gets (`tests/test_store_shape.py`), for the same reason: composition
is the one way to split a class without touching a call site, and its way to go wrong is two
mixins defining the same method, where which one answers depends on the order they are named
in - which no test would otherwise notice.
"""
from __future__ import annotations

import inspect
from pathlib import Path
import sys
import unittest

_HERE = str(Path(__file__).resolve().parent)
for entry in (str(Path(_HERE).parent / "src"), _HERE):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from codex_auto_resume import engine as package  # noqa: E402
from codex_auto_resume.engine import Engine  # noqa: E402

MIXINS = (package.OptionsMixin, package.AnnounceMixin, package.FreshnessMixin,
          package.DetectMixin, package.ReconcileMixin, package.OutcomeMixin,
          package.DispatchMixin)

# The forty-one methods the one class had, counted the day it was split.
METHODS = {
    "__init__", "_after_send", "_delete", "_legacy_carry", "_owner", "_projection_now",
    "_refused", "_stop_for_budget", "_usage_wait", "_wait", "allowed", "announce",
    "apply_policy", "attempt", "collect", "correlate", "delay_for", "dispatch",
    "first_delay", "fresh_throughout", "guard_queued", "limits", "loaded", "observe",
    "observe_all", "observe_projections", "presend_problem", "projection_fresh", "recovers",
    "settle", "supersede_reason", "tick", "transition", "usage", "valid_interruption",
    "waiting_state", "watch", "watch_needed", "watch_record", "withdraw", "withdraw_reason",
    # v0.6.11: the edition's plug asked at a gate core has passed (P3, P7), and for the words
    # before the claim (P4).
    "_held", "_plugged", "_plugged_text",
}

# What `from codex_auto_resume.engine import ...` has to keep answering (app.py, the tests).
SURFACE = {"Engine", "BACKOFF_LADDER", "TRANSIENT_BACKOFF", "NOTIFY_ON_STATE", "SETTLED",
           "UNSENT", "backoff_delay", "transient_delay"}


def own(mixin) -> set:
    return {name for name, value in vars(mixin).items()
            if inspect.isfunction(value) or isinstance(value, (staticmethod, classmethod))}


class ShapeTests(unittest.TestCase):
    def test_no_two_mixins_define_the_same_method(self):
        seen = {}
        for mixin in MIXINS:
            for name in own(mixin):
                with self.subTest(name=name):
                    self.assertNotIn(name, seen, "%s is defined by both %s and %s"
                                     % (name, seen.get(name), mixin.__name__))
                seen[name] = mixin.__name__

    def test_the_class_has_the_methods_it_had(self):
        found = {name for name in vars(Engine) if not name.startswith("__")}
        for mixin in MIXINS:
            found |= {name for name in own(mixin) if not name.startswith("__")}
        expected = {name for name in METHODS if not name.startswith("__")}
        self.assertEqual(sorted(found - expected), [], "a method appeared; name it in METHODS")
        self.assertEqual(sorted(expected - found), [], "a method is gone; take it out of METHODS")

    def test_every_method_is_callable_on_the_class(self):
        for name in sorted(METHODS):
            with self.subTest(name):
                self.assertTrue(hasattr(Engine, name), "Engine lost %s in the split" % name)

    def test_the_loop_stayed_on_the_front_page(self):
        """`tick` is what the package does; it is not hidden in one of the seven."""
        self.assertIn("tick", vars(Engine))

    def test_everything_reachable_through_the_module_still_is(self):
        for name in sorted(SURFACE):
            with self.subTest(name):
                self.assertTrue(hasattr(package, name),
                                "%s was reachable as engine.%s before the split" % (name, name))

    def test_each_part_is_small_enough_to_read(self):
        folder = Path(package.__file__).parent
        for path in sorted(folder.glob("*.py")):
            with self.subTest(path.name):
                length = len(path.read_text(encoding="utf-8").splitlines())
                self.assertLess(length, 350, "%s is growing back" % path.name)


if __name__ == "__main__":
    unittest.main()
