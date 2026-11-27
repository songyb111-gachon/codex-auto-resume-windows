"""The tray story's motion picture held to the C# host's timing (S6.4f2, P6-DESIGN 3.4 "drawn").

Twin of tests/test_motion_tray_story.py StoryTests: two of its tests hold the picture's plan (build/motion_plan.py's frames)
to the popup's one-shot glide frame, `GLIDE_FRAME_MS` of the Python popup - the hover card fades in and the popup opens a
frame every 16 ms, as the product's own timers tick. On the host that number is gui/PopupMotion.cs GlideFrameMs, the
interval the C# popup's and menu's fade timers are set to. Here the same tests - their own bodies, through `super()` - run
with the Python module's constant replaced, for the length of each test, by the host's own value, asked of the C# through
the plan probe (tests/rustdiff/PlanProbe.cs `constant`), so the plan is held to what the host does.

Nothing is drawn and no window is made: the probe answers a constant.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "src"), str(ROOT / "tests"), str(ROOT / "tests" / "rustdiff")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import planproxy  # noqa: E402
import test_motion_tray_story as original  # noqa: E402  (a module name: its classes are not collected here)


def host_glide_frame_ms() -> int:
    found = planproxy.PROBE.ask("constant", name="glide_frame_ms")
    if os.environ.get("CAR_PLAN_MUTATE") == "constant":     # the mutation check: a host one millisecond off
        found += 1
    return int(found)


@unittest.skipUnless(os.name == "nt" and planproxy.CSC.is_file(), "the host's surfaces need the in-box C# compiler")
class StoryOnHostTests(original.StoryTests):
    def setUp(self):
        from codex_auto_resume.ui.popup import motion
        patcher = mock.patch.object(motion, "GLIDE_FRAME_MS", host_glide_frame_ms())
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_card_fades_in_over_brands_transition_and_goes_at_once_where_the_popup_comes(self):
        super().test_the_card_fades_in_over_brands_transition_and_goes_at_once_where_the_popup_comes()

    def test_the_popup_opens_with_the_products_fade_and_rise_in_frames_of_16_ms(self):
        super().test_the_popup_opens_with_the_products_fade_and_rise_in_frames_of_16_ms()

    def test_the_constant_is_the_host_s(self):
        """What the two tests above read is the C#'s own value, not the Python module's."""
        from codex_auto_resume.ui.popup import motion
        self.assertEqual(motion.GLIDE_FRAME_MS, host_glide_frame_ms())


def host_tip_gap() -> int:
    """The hover card's gap from the taskbar and the icon on the host: gui/TipPlan.cs TipGap (PlanProbe `constant`)."""
    found = planproxy.PROBE.ask("constant", name="tip_gap")
    if os.environ.get("CAR_PLAN_MUTATE") == "constant":
        found += 1
    return int(found)


@unittest.skipUnless(os.name == "nt" and planproxy.CSC.is_file(), "the host's surfaces need the in-box C# compiler")
class DrawnOnHostTests(original.DrawnTests):
    """Twin of DrawnTests' hover-card placement (S6.4f3): the picture's card (build/motion_tip.py TipFrames.reading) laid
    out by the host's own renderer (gui/SurfaceDrawn.cs TipLayout, through planproxy.HostTipRenderer), placed by the
    host's TipCard.TipPlace, and held to the host's TipGap - the test's own body, through `super()`, with those three
    standing where the Python's TipRenderer, tip_place and TIP_GAP stood, for the length of the test. Nothing is shown:
    the probe lays the card out in memory."""

    def test_the_hover_card_stands_beside_the_icon_on_the_taskbar_s_side_as_the_product_places_it(self):
        from codex_auto_resume.ui.tray import tipcard, tipplan
        with mock.patch.object(tipcard, "TipRenderer", lambda: planproxy.host_tip_renderer(tipcard)),                 mock.patch.object(tipcard, "tip_place", planproxy.host_tip_place),                 mock.patch.object(tipplan, "TIP_GAP", host_tip_gap()):
            super().test_the_hover_card_stands_beside_the_icon_on_the_taskbar_s_side_as_the_product_places_it()

    def test_the_card_and_the_place_are_the_host_s(self):
        """What the test above reads is the C#'s: the renderer TipFrames makes, the place and the gap."""
        from codex_auto_resume.ui.tray import tipcard, tipplan
        import motion_tip
        with mock.patch.object(tipcard, "TipRenderer", lambda: planproxy.host_tip_renderer(tipcard)),                 mock.patch.object(tipcard, "tip_place", planproxy.host_tip_place),                 mock.patch.object(tipplan, "TIP_GAP", host_tip_gap()):
            tip = motion_tip.TipFrames("en", scale=2.0, work=self.work, monitor=self.monitor, box=self.anchor)
            try:
                self.assertIsInstance(tip.renderer, planproxy.HostTipRenderer)
                plan, _light, _where = tip.reading(0)
                self.assertIsInstance(plan, planproxy.HostPlan)
            finally:
                tip.close()
            self.assertEqual(tipplan.TIP_GAP, host_tip_gap())


# Only the twins run here: the rest of StoryTests and DrawnTests is the original module's.
for _twin, _first in ((StoryOnHostTests, original.StoryTests), (DrawnOnHostTests, original.DrawnTests)):
    for _name in [name for name in dir(_first) if name.startswith("test_")]:
        if _name not in _twin.__dict__:
            setattr(_twin, _name, None)
del _twin, _first, _name


if __name__ == "__main__":
    unittest.main()
