"""The window the README's motion is drawn from is the window the captured pictures show (build/motion_fidelity.py),
and the motion pictures are made from what the working tree holds (assets/motion.json).

`CompareTests` holds the comparison itself to the rule on tiny synthetic pictures. `LiveTests` draws every page at
rest in the render mode now and holds it to today's committed still - only where that is a fair question: on Windows
with the C# compiler, at the display scale the stills were captured at, and while the stills are the window's of
this working tree (or when CAR_MOTION_FIDELITY=1 asks for it anyway). `MadeTests` hold a made motion picture to its
manifest: its bytes, its inputs, and the fidelity recorded when it was made.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "src"), str(ROOT / "build"), str(ROOT / "tests")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import make_motion  # noqa: E402
import motion_fidelity  # noqa: E402
import motion_plan  # noqa: E402
import motion_window  # noqa: E402

WIDTH, CAPTION, CLIENT = 12, 2, 8
PAPER, INK = (246, 248, 251), (20, 22, 26)


def still():
    """(width, height, RGB, alpha) of a window 12 wide: two caption rows, a word of ink at (6, 5), its bottom corners
    clear, and nothing else."""
    height = CAPTION + CLIENT
    rgb = bytearray(bytes(PAPER) * (WIDTH * height))
    rgb[((CAPTION + 5) * WIDTH + 6) * 3:((CAPTION + 5) * WIDTH + 6) * 3 + 3] = bytes(INK)
    alpha = bytearray(b"\xff" * (WIDTH * height))
    alpha[(height - 1) * WIDTH] = alpha[(height - 1) * WIDTH + WIDTH - 1] = 0
    return WIDTH, height, bytes(rgb), bytes(alpha)


def client_of(picture):
    width, height, rgb, _alpha = picture
    return bytearray(rgb[CAPTION * width * 3:])


def poke(picture, x, y, colour):
    picture[(y * WIDTH + x) * 3:(y * WIDTH + x) * 3 + 3] = bytes(colour)


class CompareTests(unittest.TestCase):
    def compare(self, rendered, light=None):
        return motion_fidelity.compare(bytes(rendered), still(), (WIDTH, CLIENT), light)

    def test_the_same_picture_passes_exactly(self):
        result = self.compare(client_of(still()))
        self.assertEqual((result["exact"], result["outside"], result["passed"]), (1.0, 0, True))

    def test_a_text_edge_a_few_levels_off_passes_and_a_fill_does_not(self):
        edge = client_of(still())
        poke(edge, 7, 5, (PAPER[0] - 15,) * 3)
        result = self.compare(edge)
        self.assertEqual((result["outside"], result["worst"]), (0, PAPER[2] - (PAPER[0] - 15)))
        fill = client_of(still())
        poke(fill, 1, 1, (PAPER[0] - 3, PAPER[1], PAPER[2]))
        self.assertEqual(self.compare(fill)["outside"], 1)
        self.assertFalse(self.compare(fill)["passed"], "a fill that moved is not a text edge, however little")
        heavy = client_of(still())
        poke(heavy, 7, 5, (0, 0, 0))
        self.assertFalse(self.compare(heavy)["passed"], "more than TEXT_LEVELS off is not an edge's antialiasing")

    def test_under_the_share_of_exact_pixels_fails_even_at_text_edges(self):
        with mock.patch.object(motion_fidelity, "MIN_EXACT", 0.999):
            edge = client_of(still())
            poke(edge, 7, 5, (PAPER[0] - 15,) * 3)
            self.assertFalse(self.compare(edge)["passed"])

    def test_the_clear_corners_and_the_light_are_left_out(self):
        corners = client_of(still())
        poke(corners, 0, CLIENT - 1, (0, 0, 0))
        self.assertTrue(self.compare(corners)["passed"])
        light = {"x": 3.0, "y": CAPTION + 3.0, "radius": 0.5, "scale": 1.0, "state": "waiting"}
        lit = client_of(still())
        poke(lit, 3, 3, (0, 180, 220))
        result = self.compare(lit, light)
        self.assertEqual((result["light"], result["outside"], result["passed"]), (1, 0, True))

    def test_a_still_of_another_size_fails(self):
        self.assertFalse(motion_fidelity.compare(bytes(9), still(), (WIDTH + 1, CLIENT))["passed"])

    def test_every_still_the_pages_are_held_to_exists(self):
        for locale in ("en", "ko"):
            for page, _section in motion_fidelity.PAGES:
                self.assertTrue(motion_fidelity.still_path(page, locale).is_file())


def fair() -> str | None:
    """Why the live comparison would not be a fair one here, or None."""
    if os.name != "nt" or not motion_window.CSC.is_file():
        return "the window is built with Windows' C# compiler"
    if os.environ.get("CAR_MOTION_FIDELITY") == "1":
        return None
    import make_screenshots as shots
    recorded = json.loads(shots.MANIFEST.read_text(encoding="utf-8"))
    if shots.stills_dpi_problem(recorded):
        return "the stills are not at the scale the window is drawn at (%s)" % shots.stills_dpi_problem(recorded)
    if recorded["inputs"].get("<window sources>") != shots.window_digest():
        return "the stills are not of this working tree's window yet (CAR_MOTION_FIDELITY=1 compares anyway)"
    return None


@unittest.skipIf(fair() is not None, fair() or "")
class LiveTests(unittest.TestCase):
    def test_every_page_at_rest_is_its_still_in_both_readme_languages(self):
        with tempfile.TemporaryDirectory() as name:
            work = Path(name)
            results = motion_fidelity.check(motion_window.compile_window(work), work)
        # Each page, and the Timeline dialog over Pending (held to the stills of what it is made of), in each language.
        self.assertEqual(len(results), 2 * (len(motion_fidelity.PAGES) + 1))
        failed = {key: result for key, result in results.items() if not result["passed"]}
        self.assertEqual(failed, {})


class MadeTests(unittest.TestCase):
    def test_a_made_picture_is_the_bytes_its_manifest_records_from_the_inputs_it_records(self):
        manifest = make_motion.read_manifest()
        for name in make_motion.ALL_PLANS:
            plan = make_motion.load(name)
            output = ROOT / plan["output"]
            with self.subTest(name):
                if not output.exists():
                    self.assertNotIn(plan["output"], manifest["images"])
                    continue
                recorded = manifest["images"].get(plan["output"])
                self.assertIsNotNone(recorded, "%s is not in assets/motion.json" % plan["output"])
                self.assertEqual(recorded["sha256"], hashlib.sha256(output.read_bytes()).hexdigest(),
                                 "the picture is not the one made: run build/make_motion.py")
                self.assertEqual(manifest["inputs"].get("<motion:%s>" % name), make_motion.render_input(plan),
                                 "what %s is made from moved: run build/make_motion.py" % plan["output"])
                self.assertLessEqual(recorded["bytes"], plan["budget"]["cap"])
                if "window" in plan:
                    self.assertTrue(manifest["fidelity"] and all(result["passed"] for key, result in
                                                                 manifest["fidelity"].items() if key != "window"),
                                    "it was made from a window that is not the captured one")

    def test_what_a_picture_is_made_from_moves_with_its_plan_its_code_and_its_drawing(self):
        import make_screenshots as shots
        plan = motion_plan.load(make_motion.plan_path("readme-en"))
        before = make_motion.render_input(plan)
        self.assertEqual(make_motion.render_input(copy.deepcopy(plan)), before)
        moved = copy.deepcopy(plan)
        moved["scenes"][0]["steps"][0]["hold"] += 100
        self.assertNotEqual(make_motion.render_input(moved), before)
        for name in ("window_digest", "card_drawing"):
            with self.subTest(name), mock.patch.object(shots, name, return_value="moved"):
                self.assertNotEqual(make_motion.render_input(plan), before)
        real = shots.input_digest
        for path in ("src/codex_auto_resume/locales/ko.json", "build/motion_compose.py",
                     "assets/screenshot-dashboard.png"):
            with self.subTest(path), mock.patch.object(
                    shots, "input_digest", side_effect=lambda p, path=path: "moved" if Path(p) == ROOT / path else real(p)):
                self.assertNotEqual(make_motion.render_input(plan), before)


if __name__ == "__main__":
    unittest.main()
