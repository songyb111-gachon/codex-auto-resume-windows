"""The icon's tooltip card's own decisions and what a screen reader is handed, on the C# host (S6.4d, P6-DESIGN 3.4 "window").

Twins of tests/test_tray_tipcard.py AccessibleTests and two of CardStateTests:

* AccessibleTests: the object the host's SurfaceAccess hands a screen reader for the card (its TipSource in an
  AccessObject, HostProbe.cs `tip_access`), asked through its own table at the slots the original asks the reference's
  object at; the same assertions over what it answers.
* CardStateTests: the originals' own bodies, through `super()`, with only the card changed - tests/rustdiff/hosttip.py's
  HostTip, the host's TipCard (`tip_steps`, its window a message-only window of the probe's, never shown) handed every
  step the test makes and asked what the test reads.

Not here, and why: CardStateTests' hide at once and the backstop's hide count the card's ShowWindow(SW_HIDE) calls, which
the host's TipCard makes of user32 directly (not through SurfaceScreen), so nothing records them; they wait for that seam
(gui/, seat S6.3d). DrawTests and PlaceTests are the drawing's (seat S6.4f).
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "tests"), str(ROOT / "tests" / "rustdiff")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import hosttip  # noqa: E402
import surfacehost  # noqa: E402
import test_tray_tipcard as original  # noqa: E402  (a module name: its classes are not collected here)

ON_HOST = unittest.skipUnless(os.name == "nt" and surfacehost.CSC.is_file(), "the host's surfaces need the in-box C# compiler")


@ON_HOST
class AccessibleOnHostTests(original.AccessibleTests):
    def test_it_is_a_read_only_tooltip_named_with_the_whole_text_and_no_children(self):
        from codex_auto_resume.ui.tray import tipcard
        found = surfacehost.SERVE.ask("tip_access", text=self.Card.text)
        self.assertEqual(found["name"], [0, self.Card.text])
        for key, expected in (("role", tipcard.ROLE_SYSTEM_TOOLTIP), ("state", tipcard.STATE_SYSTEM_READONLY)):
            self.assertEqual(found[key], [0, expected])
        self.assertEqual(found["count"], [0, 0])


@ON_HOST
class CardStateOnHostTests(original.CardStateTests):
    def setUp(self):
        super().setUp()
        self.card = hosttip.HostTip(self.tipcard)
        self.card.hwnd, self.card.visible = 0x99, True
        self.card._moves = lambda: True

    def test_the_backstop_keeps_it_while_the_pointer_is_on_the_icon_near_it_or_on_the_card(self):
        super().test_the_backstop_keeps_it_while_the_pointer_is_on_the_icon_near_it_or_on_the_card()

    def test_a_suspend_or_a_resume_hides_it(self):
        super().test_a_suspend_or_a_resume_hides_it()

    # these count the card's ShowWindow(SW_HIDE), which the host's TipCard makes unrecorded (see the module's head)
    test_a_hide_at_once_ends_a_fade_out_on_its_way = None
    test_the_backstop_hides_it_a_second_after_the_pointer_went_elsewhere = None


if __name__ == "__main__":
    unittest.main()
