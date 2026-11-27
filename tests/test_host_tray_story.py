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


# Only the twins run here: the rest of StoryTests is the original module's.
for _name in [name for name in dir(original.StoryTests) if name.startswith("test_")]:
    if _name not in StoryOnHostTests.__dict__:
        setattr(StoryOnHostTests, _name, None)
del _name


if __name__ == "__main__":
    unittest.main()
