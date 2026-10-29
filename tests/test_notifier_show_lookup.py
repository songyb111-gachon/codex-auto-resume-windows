"""`notifier.deliver` and `notifier.complete` find notify.show_content when they are called.

Both once took `show=notify.show_content` as a default argument, bound when `notifier` was imported. A
test that patched notify.show_content (tests/test_downgrade.py) therefore patched nothing `deliver` used,
and the command line's cancel raised a real Windows toast under the product's identity on every run that
included it - the "automatic recovery cancelled" toasts the owner kept seeing (2026-10-22,
plans/notif-check.md section 3). A patch of notify.show_content must mean what it says.

Every test here also patches notify.show, the layer below, so that a regression is a failed assertion
and never a real toast.
"""
from __future__ import annotations

import unittest
from unittest import mock

from codex_auto_resume import notifier, notify

THREAD = "0a1b2c3d-0001-7000-8000-000000000001"


class ShowLookupTests(unittest.TestCase):
    def setUp(self):
        below = mock.patch.object(notify, "show", return_value=True)
        self.below = below.start()
        self.addCleanup(below.stop)

    def notice(self):
        return notifier.build_cancelled(THREAD)

    def test_deliver_raises_the_toast_through_the_patched_show_content(self):
        with mock.patch.object(notify, "show_content", return_value=True) as patched:
            self.assertEqual(notifier.deliver(self.notice(), inbox=None, setting=False), ("toast", True))
        self.assertEqual(patched.call_count, 1)
        self.assertEqual(patched.call_args.args[0]["title"], notify.cancelled_content(THREAD)["title"])
        self.below.assert_not_called()

    def test_complete_raises_the_history_copy_and_the_toast_through_the_patched_show_content(self):
        for shown, silent in ((True, {"silent": True}), (False, {})):
            with self.subTest(card_shown=shown), \
                    mock.patch.object(notify, "show_content", return_value=True) as patched:
                self.assertTrue(notifier.complete(self.notice(), shown))
                self.assertEqual(patched.call_count, 1)
                self.assertEqual(patched.call_args.kwargs, silent)
        self.below.assert_not_called()

    def test_a_show_passed_in_is_still_the_one_used(self):
        given = mock.Mock(return_value=False)
        with mock.patch.object(notify, "show_content", return_value=True) as patched:
            self.assertEqual(notifier.deliver(self.notice(), inbox=None, setting=False, show=given),
                             ("toast", False))
            self.assertFalse(notifier.complete(self.notice(), True, show=given))
        patched.assert_not_called()
        self.assertEqual(given.call_count, 2)

    def test_neither_binds_a_show_at_import(self):
        for function in (notifier.deliver, notifier.complete):
            with self.subTest(function=function.__name__):
                self.assertIsNone((function.__kwdefaults__ or {}).get("show"))


if __name__ == "__main__":
    unittest.main()
