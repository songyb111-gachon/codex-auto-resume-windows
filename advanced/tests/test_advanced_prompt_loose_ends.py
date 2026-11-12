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

    def test_m2_a_tick_between_the_write_and_the_pictures_sends_nothing(self):
        """Fails with the prompt written waiting: the tick would send its words without its pictures."""
        plug = self.on()
        place = copies.place
        during = []

        def placed_late(paths, prompt, images):
            self.h.tick(advance=1)                     # the watcher's tick, between the write and the pictures
            during.append((list(self.h.backend.send_calls), list(self.calls)))
            return place(paths, prompt, images)
        with patch.object(copies, "place", placed_late):
            prompt = self.queued(plug, [self.picture()])
        self.assertEqual(during, [([], [])], "nothing went before its pictures were placed")
        self.assertEqual(plug.runtime.state.prompt(prompt)["state"], PromptState.WAITING)
        self.h.tick(advance=1)
        (method, params), = self.calls
        self.assertEqual([item["type"] for item in params["input"]], ["text", "localImage"], "with its picture")
        self.assertEqual(self.h.backend.send_calls, [])

    def test_m2_an_edit_s_tick_before_its_new_pictures_sends_nothing(self):
        """Fails with the edit written waiting: the tick would send the new words with the old picture."""
        plug = self.on()
        answer = self.add_with(plug, [self.picture()])          # at a time two hours on
        prompt = answer["prompt"]
        place = copies.place
        during = []

        def placed_late(paths, prompt_id, images):
            self.h.tick(advance=1)
            during.append((list(self.h.backend.send_calls), list(self.calls)))
            return place(paths, prompt_id, images)
        with patch.object(copies, "place", placed_late):
            edited = surfaces.bridge(plug.runtime, "advanced-prompt-edit",
                                     dict(prompt=prompt, words="New words, new picture.", trigger="after_turn",
                                          images=[{"path": self.picture(name=images_case.OWN_NAME + "-2.png")}],
                                          generation=plug.runtime.state.meta()["generation"]))
        self.assertTrue(edited["done"], edited)
        self.assertEqual(during, [([], [])], "nothing went with the old picture")
        self.assertEqual(plug.runtime.state.prompt(prompt)["state"], PromptState.WAITING)

    def test_m3_an_expired_occurrence_drops_its_record(self):
        """Fails with `_expired` leaving the record: it would stay waiting, never pruned."""
        plug = self.on()
        self.h.backend.loaded_map[T1] = "notLoaded"
        self.assertTrue(self.add(plug, trigger="at_time", at=self.h.now + 60)["done"])
        for _ in range(26):
            self.h.tick(advance=3600)
        row = self.prompts(plug)[0]
        self.assertEqual((row["state"], row["reason"]), (PromptState.DONE, PromptReason.EXPIRED))
        records = plug.runtime.state.records_on(T1)
        self.assertEqual([record["state"] for record in records], [RecordState.CANCELLED])


if __name__ == "__main__":
    unittest.main()
