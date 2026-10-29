"""A subagent's stop is told once when the parent's words carrying it go (v0.6.18, the advanced audit's R5): P4 builds
the words before the claim, so a claim held after it (a ceiling, the cooldown, a gate, the ledger) or core's own words
sent instead used to leave every child marked told - and none was ever mentioned. Now each is marked only once the claim
that carries the lines commits.
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from codex_auto_resume.domain.plug import Alternative  # noqa: E402
from test_advanced_subagent import CHILDREN, SubagentCase  # noqa: E402
from test_engine import T1  # noqa: E402


class ToldAtSendTests(SubagentCase):
    def mentioned(self, plug):
        return [row for row in plug.runtime.state.continuations(pending=None) if row["reason"] == "mentioned"]

    def test_a_claim_held_after_p4_leaves_the_lines_for_the_next_send(self):
        """Fails with the mark at P4 restored: the held claim marked both told, and the send after carried none."""
        plug = self.on()
        self.spawned(CHILDREN[:2])
        ledger = plug.runtime.ledger
        claim, held = ledger.claim, []

        def holding_once(*arguments, **keywords):
            if not held:
                held.append(True)
                return Alternative.HOLD
            return claim(*arguments, **keywords)
        ledger.claim = holding_once
        self.due()
        self.h.tick()
        self.assertEqual(held, [True], "the first claim was held")
        self.assertEqual(self.h.backend.send_calls, [])
        self.assertEqual(self.mentioned(plug), [], "nothing told by a send that did not go")
        for _ in range(30):
            if self.h.backend.send_calls:
                break
            self.h.tick(advance=61)
        self.assertEqual([call[0] for call in self.h.backend.send_calls], [T1])
        self.assertEqual(len(self.lines(self.h.backend.send_calls[0][1])), 2)
        self.assertEqual(len(self.mentioned(plug)), 2, "told once, with the send that carried them")


if __name__ == "__main__":
    unittest.main()
