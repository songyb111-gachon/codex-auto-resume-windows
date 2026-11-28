"""The notification card's two layers on the C# host (S6.4c, P6-DESIGN 3.4 "window"): nothing of its shadow lies under its body.

Twin of tests/test_card_shadow_under_body.py. That test paints the Python card's body and shadow layers settled, with and
without the cut under the body, and holds three rules of their pixels. Here the same three rules - its own helper methods,
inherited unchanged - are held of gui/CardWindow.cs's NoticeCard: the host's probe (tests/rustdiff/HostProbe.cs
`card_layers`) makes the card with no window, paints both layers through PaintLayers at the settled frame and dumps them;
the uncut shadow is the same card's with nothing of its image wholly opaque, so the cut clears nothing. The notice and its
view are the ones the Python test draws (make_screenshots.card_notice, notice_card.view); the subject is the window's layers.

Nothing is shown: the probe runs with CREATE_NO_WINDOW and makes no window.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "src"), str(ROOT / "build"), str(ROOT / "tests"), str(ROOT / "tests" / "rustdiff")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import surfacehost  # noqa: E402
import test_card_shadow_under_body as original  # noqa: E402  (a module name: its class is not collected here)


class HostCard:
    """What the Python test reads of a card - size, margin, shadows - and its layers as the host painted them."""

    def __init__(self, design, contrast, theme):
        import make_screenshots
        from codex_auto_resume import notice_card
        notice = make_screenshots.card_notice("en")
        drawn = {"theme": theme, "design": design, "contrast": contrast, "reduced": False}
        found = surfacehost.SERVE.ask("card_layers", vm=_plain(notice_card.view(notice)), title=notice.title,
                                      stays=getattr(notice, "stays", False) is True, hold=float(notice_card.HOLD_MS),
                                      dpi=144.0, work=[0, 0, 0, 0], drawn=drawn)
        self.size = tuple(int(n) for n in found["size"])
        self.margin = int(found["margin"])
        self.shadows = [None] * int(found["shadows"])
        self.body = base64.b64decode(found["body"])
        self.cut = base64.b64decode(found["cut"])
        self.whole = base64.b64decode(found["whole"])
        width, height = self.size
        assert len(self.body) == width * height * 4
        assert len(self.cut) == len(self.whole) == (width + 2 * self.margin) * (height + 2 * self.margin) * 4
        assert tuple(int(n) for n in found["shadow_size"]) == (width + 2 * self.margin, height + 2 * self.margin)

    def close(self):
        pass


def _plain(value):
    """A view as JSON carries it (tuples as lists)."""
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


@unittest.skipUnless(os.name == "nt" and surfacehost.CSC.is_file(), "the host's surfaces need the in-box C# compiler")
class ShadowUnderBodyOnHostTests(original.ShadowUnderBodyTests):
    def settled(self, card, cut=True):
        return card.body, (card.cut if cut else card.whole)

    def each_look(self, check):
        for design, contrast in original.LOOKS:
            for theme in ("light", "dark"):
                with self.subTest(design=design, contrast=contrast, theme=theme):
                    check(HostCard(design, contrast, theme))

    def test_the_shadow_is_clear_wherever_the_body_is_opaque(self):
        self.each_look(self.clear_under_the_body)

    def test_the_shadow_outside_the_body_is_what_it_was(self):
        self.each_look(self.kept_outside_the_body)

    def test_a_fading_card_shows_no_shadow_through_its_body(self):
        self.each_look(self.fades_clean)


if __name__ == "__main__":
    unittest.main()
