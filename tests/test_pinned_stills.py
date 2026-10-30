"""The window's stills drawn offscreen at a pinned 150 %, whatever display the machine has (v0.6.20).

The owner (2026-10-30): the pictures the same every time, whatever monitor is connected. With the 150 % monitor
unplugged, the laptop's 200 % panel drew every window still at 2000x1386 where the committed set is 1500x1041. Now the
window draws its stills itself, offscreen, at build/make_screenshots.py PINNED_DPI, framed with Windows' title bar kept
from one capture at that scale (build/window_frame.py) - and on the 200 % laptop all 23 stills so drawn were the
committed 150 % captures byte for byte. These hold the pieces that make that so:

- the pin lives in the render mode only (a job's `scale`), and what it pins: the display scale, the text size, the
  screen the window opens on, a list's header;
- the title bar kept is the one every committed window picture shows, and is refused once it stops being this tree's
  window's (title, icon, DPI);
- the setup window's offscreen still is framed by the very code the window's is;
- the generator, its manifest and its staleness speak of the pinned DPI, never the display's.

A live drawing, compared with the committed pictures, runs where CAR_PINNED_STILLS=1 asks for it (it draws with this
machine's fonts and ClearType, which a CI runner does not share): the main session's proof.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "src"), str(ROOT / "build"), str(ROOT / "tests")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import guiscan  # noqa: E402
import make_screenshots as shots  # noqa: E402
import window_frame  # noqa: E402

SHIM = ROOT / "build" / "motion" / "InstallerRender.cs"


def manifest() -> dict:
    return json.loads(shots.MANIFEST.read_text(encoding="utf-8"))


class PinTests(unittest.TestCase):
    def test_the_pinned_scale_is_the_one_every_committed_window_picture_has(self):
        self.assertEqual(shots.PINNED_DPI, 144)
        self.assertEqual(shots.PINNED_SCALE, 1.5)
        recorded = manifest()
        self.assertEqual(recorded.get("window_dpi", recorded.get("system_dpi")), shots.PINNED_DPI)
        self.assertIsNone(shots.stills_dpi_problem(recorded))
        self.assertIn("200", shots.stills_dpi_problem({"window_dpi": 200}) or "")
        opening = re.search(r"internal const int OpeningHeight = (\d+);", guiscan.read("gui/SettingsApp.cs"))
        self.assertEqual(int(opening.group(1)), shots.OPENING_HEIGHT, "the client height under a still's title bar")

    def test_the_render_mode_alone_pins_and_only_when_the_job_names_a_scale(self):
        adopt = guiscan.member_body("SettingsForm", "AdoptRenderScale")
        self.assertIn('job.TryGetValue("scale"', adopt)
        for pinned in ("RenderPinned = true", "AdoptDisplayScale(scale)", "ScaleDefaultFont()", "AdoptTextSize(1.0, 1.0)"):
            self.assertIn(pinned, adopt)
        # Without a scale: this machine's text size and scale, as before.
        self.assertIn("TextScale.Read()", adopt)
        self.assertIn("AdoptRenderScale(job)", guiscan.member_body("SettingsForm", "RenderFrames"))
        # Set nowhere else in the window: a window a person opens is never pinned.
        setters = [name for name in guiscan.manifest() if "RenderPinned = true" in guiscan.read(name)]
        self.assertEqual(setters, ["gui/WindowRender.cs"])
        self.assertIn("if (RenderPinned) return;", guiscan.member_body("SettingsForm", "KeepOnScreen"))
        self.assertIn("RenderPinned ? opened", guiscan.member_body("SettingsForm", "OpenForRender"))
        self.assertIn("if (SettingsForm.RenderPinned) PinnedHeader.Attach(this);",
                      guiscan.member_body("SoftList", "OnHandleCreated"))
        # The setup program's stand-in: never pinned, its factor 1, but in a picture.
        setup = (ROOT / "build" / "setup" / "SetupWindow.cs").read_text(encoding="utf-8")
        self.assertIn("internal static float FontFactor = 1f;", setup)
        self.assertIn("internal static bool RenderPinned;", setup)
        self.assertNotIn("RenderPinned = true", setup)

    def test_the_controls_steps_in_points_follow_the_font_factor(self):
        role = guiscan.member_body("Soft", "RoleFont")
        self.assertIn("* SettingsForm.FontFactor", role)
        self.assertIn("AsideLeast * SettingsForm.FontFactor", guiscan.member_body("Soft", "AsidePoints"))
        # 1 wherever the window is drawn at the scale Windows signed in at, and in the layout audits.
        self.assertIn("displayScale / SystemScale", guiscan.member_body("SettingsForm", "FontFactor"))
        self.assertNotIn("AdoptDisplayScale", guiscan.member_body("SettingsForm", "LayoutAuditAt"))

    def test_the_setup_windows_still_is_framed_by_the_windows_own_code(self):
        shim = SHIM.read_text(encoding="utf-8")
        frame = guiscan.type_body("StillFrame", shim)
        for member in ("LoadCaption", "Argb", "FramedStill", "Rounded"):
            pattern = re.compile(r"(?m)^[ \t]*(?:(?:%s)[ \t]+)*[\w<>,\[\]\.\?]+[ \t]+%s[ \t]*\("
                                 % ("|".join(guiscan.MODIFIERS), member))
            found = pattern.search(frame)
            self.assertIsNotNone(found, member)
            self.assertEqual(guiscan._block(frame, found.start()).strip(),
                             guiscan.member_body("SettingsForm", member).strip(),
                             "%s in the shim is the window's own" % member)

    def test_a_still_is_cut_round_as_the_capture_cuts_it(self):
        rounded = guiscan.member_body("SettingsForm", "Rounded")
        script = (ROOT / "build" / "capture_window.ps1").read_text(encoding="utf-8")
        for step in ("SmoothingMode.AntiAlias", "PixelOffsetMode.HighQuality", "AddArc(0, 0, d, d, 180, 90)",
                     "AddArc(width - d, 0, d, d, 270, 90)", "AddArc(width - d, height - d, d, d, 0, 90)",
                     "AddArc(0, height - d, d, d, 90, 90)", "CloseFigure()", "new TextureBrush(square)", "FillPath("):
            self.assertIn(step, rounded)
        for step in ("AntiAlias", "HighQuality", "AddArc(0, 0, $d, $d, 180, 90)", "AddArc($cut.Width - $d, 0, $d, $d, 270, 90)",
                     "AddArc($cut.Width - $d, $cut.Height - $d, $d, $d, 0, 90)", "AddArc(0, $cut.Height - $d, $d, $d, 90, 90)",
                     "TextureBrush $cut", "FillPath("):
            self.assertIn(step, script)
        self.assertIn("8.0 * $dpi / 96.0", script)
        self.assertEqual(window_frame.radius(shots.PINNED_DPI), 12)


class TitleBarTests(unittest.TestCase):
    def test_the_kept_title_bars_are_this_trees_windows(self):
        for kind in window_frame.KINDS:
            self.assertEqual(window_frame.problems(kind, shots.PINNED_DPI), [], kind)
            job = window_frame.still_job(kind, shots.PINNED_DPI)
            self.assertEqual(job["radius"], 12)
            self.assertEqual((job["left"], job["right"]), (window_frame.LEFT, window_frame.RIGHT))
        for title in ('Text = "%s";' % window_frame.TITLE,):
            self.assertIn(title, guiscan.read("gui/SettingsApp.cs"))
            self.assertIn(title, guiscan.read("gui/InstallerWindow.cs"))

    def test_a_title_bar_of_another_window_is_refused(self):
        self.assertTrue(window_frame.problems("window", 192))
        self.assertTrue(window_frame.problems("window", shots.PINNED_DPI, "dark"))
        with mock.patch.object(window_frame, "TITLE", "Another"):
            self.assertTrue(window_frame.problems("window", shots.PINNED_DPI))
        with mock.patch.object(window_frame, "icon_digest", return_value="0" * 64):
            with self.assertRaises(window_frame.FrameError):
                window_frame.still_job("setup", shots.PINNED_DPI)
        with mock.patch.object(window_frame, "FOLDER", Path(tempfile.gettempdir()) / "car-no-frame-here"):
            self.assertTrue(window_frame.problems("window", shots.PINNED_DPI))

    def test_the_kept_title_bar_is_the_one_every_committed_window_picture_shows(self):
        width, rows, caption, _alpha = shots.read_png(window_frame.caption_path("window"))
        recorded = manifest()
        # Each distinct picture once: the docs/images copies are the same bytes.
        distinct = {}
        for key, record in recorded["lights"].items():
            if record["surface"] == "window":
                distinct.setdefault(recorded["images"][key]["sha256"], key)
        windows = sorted(distinct.values())
        self.assertGreaterEqual(len(windows), 23)
        for key in windows:
            w, _h, rgb, alpha = shots.read_png(ROOT / key)
            for y in range(rows):
                for x in range(w):
                    if alpha is not None and alpha[y * w + x] < 255:
                        continue                     # a corner the capture cut round
                    source = x if x < window_frame.LEFT else (
                        width - (w - x) if x >= w - window_frame.RIGHT else window_frame.LEFT)
                    self.assertEqual(rgb[(y * w + x) * 3:(y * w + x) * 3 + 3],
                                     caption[(y * width + source) * 3:(y * width + source) * 3 + 3],
                                     "%s (%d, %d)" % (key, x, y))

    def test_taking_a_title_bar_fills_the_corners_back_in(self):
        width, height = 6, 5
        rgb = bytes([243] * width * height * 3)
        alpha = bytearray([255] * width * height)
        alpha[0] = 0
        alpha[width - 1] = 40
        rows, rgba = window_frame.caption_rows(width, height, rgb, bytes(alpha), 3)
        self.assertEqual(rows, 2)
        self.assertEqual(rgba[0:4], bytes([243, 243, 243, 255]))
        self.assertEqual(set(rgba[3::4]), {255})
        with self.assertRaises(window_frame.FrameError):
            window_frame.caption_rows(width, height, rgb, bytes(alpha), height)


class GeneratorTests(unittest.TestCase):
    def test_the_window_is_drawn_at_the_pinned_dpi_unless_photographed(self):
        with mock.patch.object(shots, "WINDOW_CAPTURE", False), \
                mock.patch.object(shots, "system_dpi", return_value=192):
            self.assertEqual(shots.window_dpi(), shots.PINNED_DPI)
        with mock.patch.object(shots, "WINDOW_CAPTURE", True), \
                mock.patch.object(shots, "system_dpi", return_value=192):
            self.assertEqual(shots.window_dpi(), 192)

    def test_draw_window_draws_offscreen_and_captures_only_when_asked(self):
        targets = {"overview": Path("x.png")}
        for capture, wanted in ((False, "render_window_offscreen"), (True, "render_window")):
            with mock.patch.object(shots, "WINDOW_CAPTURE", capture), \
                    mock.patch.object(shots, "render_window_offscreen", return_value="drawn") as drawn, \
                    mock.patch.object(shots, "render_window", return_value="captured") as captured:
                shots.draw_window(targets, design=None)
                self.assertEqual((drawn.called, captured.called), (wanted == "render_window_offscreen",
                                                                    wanted == "render_window"))

    def test_a_still_drawn_offscreen_is_the_render_jobs_framed_still(self):
        source = shots.render_window_offscreen.__code__.co_names
        for name in ("answers", "still_job", "render", "window_turn", "window_exe", "copy_file"):
            self.assertIn(name, source)
        import inspect
        text = inspect.getsource(shots.render_window_offscreen)
        self.assertIn('"scale": PINNED_SCALE', text)
        self.assertIn('"section"] = "continuation"', text)
        self.assertIn('"light": 0', text)

    def test_staleness_asks_the_drawn_dpi_and_reads_an_older_manifest(self):
        job = {"kind": "window", "locale": "en", "design": None}
        recorded = manifest()
        inputs = dict(recorded["inputs"])
        for older in (True, False):
            copy = json.loads(json.dumps(recorded))
            dpi = copy.pop("window_dpi", None) or copy.get("system_dpi")
            if older:
                copy.pop("window_dpi", None)
                copy["system_dpi"] = dpi
            else:
                copy.pop("system_dpi", None)
                copy["window_dpi"] = dpi
            self.assertIsNone(shots.stale(job, copy, inputs, shots.PINNED_DPI))
            self.assertEqual(shots.stale(job, copy, inputs, 192), "drawn at 144 DPI")

    def test_the_manifest_says_how_the_window_was_drawn(self):
        import inspect
        text = inspect.getsource(shots.main)
        self.assertIn('"window_dpi": dpi', text)
        self.assertIn('"window_drawn": "captured" if WINDOW_CAPTURE else "offscreen"', text)
        self.assertNotIn('"system_dpi": dpi', text)
        self.assertIn("--capture", text)
        for name in ("build/motion_window.py", "build/window_frame.py", "build/frame/window-caption.png",
                     "build/frame/frame.json"):
            self.assertIn(name, shots.WINDOW_INPUTS)

    def test_every_window_job_is_drawn_at_the_pinned_scale(self):
        import inspect
        import advanced_shots
        import make_install_motion
        import motion_fidelity
        import motion_window
        self.assertIn('"scale": make_screenshots.PINNED_SCALE', inspect.getsource(motion_window.job))
        self.assertIn('"scale": make_screenshots.PINNED_SCALE', inspect.getsource(motion_fidelity.check))
        self.assertIn('"scale": shots.PINNED_SCALE', inspect.getsource(advanced_shots.job))
        self.assertIn('"scale": make_screenshots.PINNED_SCALE', inspect.getsource(make_install_motion.job))
        self.assertIn('"scale": make_screenshots.PINNED_SCALE', inspect.getsource(make_install_motion.check_fidelity))
        self.assertIn('"scale": make_screenshots.PINNED_SCALE', inspect.getsource(make_install_motion.draw_still))
        for module in ("make_motion", "advanced_shots"):
            text = (ROOT / "build" / ("%s.py" % module)).read_text(encoding="utf-8")
            self.assertNotIn("system_dpi()", text, module)
            self.assertIn("stills_dpi_problem(recorded)", text, module)


def fair() -> str | None:
    if os.name != "nt":
        return "Windows only"
    if os.environ.get("CAR_PINNED_STILLS") != "1":
        return "draws with this machine's fonts and ClearType: CAR_PINNED_STILLS=1 asks for it"
    import motion_window
    if not motion_window.CSC.is_file():
        return "the window is built with Windows' C# compiler"
    return None


@unittest.skipIf(fair() is not None, fair() or "")
class LiveTests(unittest.TestCase):
    def test_the_overview_drawn_offscreen_and_breathed_is_the_committed_picture(self):
        import motion_window
        from codex_auto_resume import l10n
        with tempfile.TemporaryDirectory() as name:
            work = Path(name)
            exe = motion_window.compile_window(work / "exe")
            target = work / "screenshot-dashboard.png"
            with mock.patch.object(shots, "WINDOW_EXE", str(exe)), \
                    mock.patch.object(shots, "WINDOW_CAPTURE", False), \
                    mock.patch.dict(os.environ, {l10n.ENV_LANG: "en"}):
                shots.render_window_offscreen({"overview": target})
                record = shots.window_record(target)
            self.assertEqual(record, manifest()["lights"]["assets/screenshot-dashboard.png"])
            shots.breathe_picture(target, record)
            self.assertEqual(target.read_bytes(), (ROOT / "assets" / "screenshot-dashboard.png").read_bytes())


if __name__ == "__main__":
    unittest.main()
