# ADVANCED-EDITION-CODE: in the advanced edition's tree, never the standard one's.
"""The edition's own Pending buttons are said again when the bridge's words come (v0.6.19's live acceptance).

Pending can be built before the words arrive; Schedule..., Edit..., Go on and Cancel were then made in English and never
said again, so the Korean Dashboard showed "Schedule..." (the owner: "왜 스케쥴이라고 뜨지, 영어로?"). The page tests
adopt the words before Pending is built, so this holds the wiring itself: adopting the words rewords the four buttons.
"""
from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


def body(path: Path, signature: str) -> str:
    text = path.read_text(encoding="utf-8")
    start = text.index(signature)
    return text[start:text.index("\n        }\n", start)]


class LateWordsTests(unittest.TestCase):
    def test_adopting_the_words_rewords_the_editions_pending_buttons(self):
        adopt = body(ROOT / "advanced" / "gui" / "AdvancedPage.cs", "private void AdoptAdvancedWords(")
        self.assertIn("RewordPendingButtons();", adopt)
        self.assertLess(adopt.index("RewordPendingButtons();"), adopt.index("if (advancedTab == null) return;"),
                        "reworded whether or not the tab exists yet")
        reword = body(ROOT / "advanced" / "gui" / "AdvancedSchedule.cs", "private void RewordPendingButtons()")
        for button, key in (("scheduleAddButton", "page.scheduled.add"), ("scheduleEditButton", "page.queue.edit"),
                            ("scheduleGoOnButton", "page.queue.go_on"), ("scheduleCancelButton", "page.resets.cancel")):
            with self.subTest(button=button):
                self.assertIn('%s.Text = Word("%s"' % (button, key), reword)


if __name__ == "__main__":
    unittest.main()
