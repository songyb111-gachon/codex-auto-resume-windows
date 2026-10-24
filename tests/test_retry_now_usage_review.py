"""Reviewer's proofs for v0.6.19-beta.2's Retry now usage check (issue #50): each test fails on cf2984b6a.

Held against the writer's own case (tests/test_retry_now_usage.py CheckCase): core's engine, store and simulated
Codex home, the control layer on the harness's clock.
"""
from __future__ import annotations

import unittest

from codexsim import RESET  # noqa: E402
from test_retry_now_usage import CheckCase  # noqa: E402
from test_power import values  # noqa: E402

LIMITED = {"available": False, "reset_at": RESET, "limit_type": "x", "reason": "limited"}


class ReviewTests(CheckCase):
    def test_a_request_not_served_is_never_read_later_without_a_click(self):
        """A click, then a Pause before the watcher looks: the request stays in usage-checks. Half an hour later the
        person resumes recovery - and the watcher reads usage for that old click, with no click now (C4: nothing happens
        on its own; the writer's own rule: a check is asked for now, not for whenever)."""
        key = self.waiting()
        self.assertEqual(self.retry(key)["usage_check"], "asked")
        self.h.store.set_enabled(False, self.h.now)
        self.h.tick(advance=1)
        self.h.now += 1800
        self.h.store.set_enabled(True, self.h.now)
        before = self.reads
        self.h.tick(advance=1)
        self.assertEqual(self.reads, before, "usage read 30 minutes after the click, at no click")

    def test_two_clicks_seconds_apart_read_usage_once(self):
        """C9: a usage read is reused for 30 s. Two Retry now clicks five seconds apart on a still-limited recovery
        start two App Server reads, because the click's look throws the 5-second-old reading away."""
        key = self.waiting()
        self.h.backend.usage_result = dict(LIMITED)
        before = self.reads
        self.retry(key)
        self.h.tick(advance=1)
        self.h.now += 5
        self.retry(key)
        self.h.tick(advance=1)
        self.assertEqual(self.reads - before, 1, "a reading 5 s old read again (C9: reused for 30 s)")

    def test_observe_only_does_not_promise_a_check_it_never_makes(self):
        """Observe only on: the click answers usage_check 'asked' and the Dashboard says "Checking usage now" - but the
        watcher takes the request and reads nothing, so the row never says when it checked (issue #50 reply: "The row
        shows when it checked and what it read")."""
        key = self.waiting()
        self.h.store.set_observe_only(True)
        answer = self.retry(key)
        before = self.reads
        self.h.tick(advance=1)
        read = self.reads - before
        self.assertFalse(answer["usage_check"] == "asked" and read == 0 and self.pending()["usage_check"] is None,
                         "told 'checking usage now', nothing was read and the row shows no check")

    def test_quiet_hours_do_not_promise_a_check_they_never_make(self):
        """Quiet hours now: the control layer does not ask about them, answers 'asked'; the engine's quiet gate drops the
        request unread."""
        key = self.waiting()
        self.h.engine.quiet_until = lambda now: now + 3600
        answer = self.retry(key)
        before = self.reads
        self.h.tick(advance=1)
        read = self.reads - before
        self.assertFalse(answer["usage_check"] == "asked" and read == 0 and self.pending()["usage_check"] is None,
                         "told 'checking usage now', nothing was read and the row shows no check")

    def test_wait_for_an_internet_connection_starts_no_app_server_offline(self):
        """Wait for an internet connection on and Windows reports none: usage is not read, no App Server is started
        (engine/freshness.py _offline, tests/test_power.py). The click's read goes past it."""
        key = self.waiting()
        self.h.engine.apply_policy(values(wait_for_network=True))
        self.h.engine.connectivity = lambda: False
        self.retry(key)
        before = self.reads
        self.h.tick(advance=1)
        self.assertEqual(self.reads, before, "usage read (an App Server started) while Windows reports no internet")


if __name__ == "__main__":
    unittest.main()
