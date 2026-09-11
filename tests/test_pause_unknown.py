"""A Pause never turns an uncertain submission back into a waiting one.

An uncertain submission is never sent again. A continuation withdrawn because of a
Pause, on the other hand, can be released back to waiting once it is proven never to
have run - which, if the two met, would be a path to sending an uncertain submission a
second time. So a Pause still takes an uncertain submission out of Codex's queue, but
under its own reason, and that withdrawal ends as final.
"""
from __future__ import annotations

import unittest

try:
    from tests.codexsim import new_id
except ImportError:
    from codexsim import new_id

from test_correlation import Scenario


class PausedUnknownTests(unittest.TestCase):
    def unknown_with_row(self):
        sim = Scenario(self, after_accept="queue")
        sim.backend.default_outcome = "timeout"
        sim.backend.on_send = lambda thread, prompt: sim.home.enqueue(thread, prompt, client_id=new_id())
        sim.send()
        sim.watch()
        row = sim.record()
        self.assertEqual(row["state"], "submission_unknown")
        self.assertIsNotNone(row["queue_id"])
        return sim

    def test_a_pause_withdraws_it_and_it_ends_final(self):
        sim = self.unknown_with_row()
        sim.store.set_enabled(False, sim.now)
        sim.watch()
        row = sim.record()
        self.assertEqual((row["state"], row["withdraw_reason"]), ("withdrawn_unconfirmed", "paused_unknown"))
        self.assertEqual(sim.home.queued(sim.thread), [])
        row = sim.through_window()
        self.assertEqual(row["state"], "failed")
        self.assertIsNotNone(row["submitted_at"], "it may have been sent; that is never forgotten")
        # Resuming changes nothing about it: it is never claimed or sent again.
        sim.store.set_enabled(True, sim.now)
        for _ in range(5):
            sim.advance(3600)
            sim.engine.tick()
        self.assertEqual(len(sim.backend.send_calls), 1)
        self.assertEqual(sim.record()["state"], "failed")


if __name__ == "__main__":
    unittest.main()
