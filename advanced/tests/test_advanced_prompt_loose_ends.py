"""Three loose ends of the prompt queue (v0.6.23, findings M1, M2 and M3 of the second round's advanced audit).

* M1: a recurring message whose pictures cannot go (MIMG failed on the Codex in force, or a copy gone) moved nowhere and
  held its conversation's queue for good; a day after its occurrence fell due it is used as expired, as any occurrence,
  and the series goes on to its next.
* M2: a message added or edited with pictures was written before its pictures were placed, so a watcher tick between
  the two could send it without them, or with the old ones; it is held while they are placed and waits only then.
* M3: an expired occurrence left its record waiting for ever, which pruning never removes; it is dropped (cancelled).

Held against the shipped definition and core's own engine, store and simulated Codex home, as
test_advanced_prompt_images is (its ImagesCase).
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_advanced_prompt_images as images_case  # noqa: E402
from codex_auto_resume_advanced import images as copies  # noqa: E402
from codex_auto_resume_advanced import surfaces  # noqa: E402
from codex_auto_resume_advanced.vocabulary import PromptReason, PromptState, RecordState  # noqa: E402
from test_engine import T1  # noqa: E402

DAY = 86400


class LooseEndTests(images_case.ImagesCase):
    def sent_texts(self):
        return [params["input"][0]["text"] for method, params in self.calls if method == "thread/queue/add"]

    def test_m1_a_recurring_message_whose_pictures_cannot_go_moves_to_its_next_occurrence(self):
        """Fails with the recurring exemption kept: the series would wait on its first occurrence for good."""
        plug = self.on()
        answer = self.add_with(plug, [self.picture()], trigger="recurring", every="day", occurrences=3,
                               at=self.h.now + 60)
        self.assertTrue(answer["done"], answer)
        prompt = answer["prompt"]
        first = plug.runtime.state.prompt(prompt)["due_at"]
        with self.mimg_failed(plug):
            for _ in range(26):
                self.h.tick(advance=3600)
        row = plug.runtime.state.prompt(prompt)
        self.assertEqual((row["state"], row["reason"], row["sent_count"]),
                         (PromptState.WAITING, PromptReason.EXPIRED, 1))
        self.assertEqual(row["due_at"], first + DAY, "on to its next occurrence")
        self.assertEqual(self.calls, [], "never sent without its pictures")


if __name__ == "__main__":
    unittest.main()
