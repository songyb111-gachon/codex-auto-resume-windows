"""The popup is one module, however many files it is written in.

v0.6.10-alpha split `tray_popup.py` - 2,851 lines, the largest file there was - into
`tray_popup/`. The store and the engine were split by composition, where the class holds the
shape; a module has no class, so its shape is held here.

Two ways a split module goes wrong, both silent:

*A name stops being there.* Twelve files re-exported through one `__init__` is twelve chances
to leave one out, and `tray_popup._icon_from_pixels` - which the notification-area icon calls
for every frame it draws - was left out exactly that way. The icon caught it and drew itself
the old way for the rest of its life, logging one line nobody reads.

*A name is still there, but nobody reads it any more.* Before the split, `tray_popup.<name>`
was the one place a test could replace what the popup asks Windows. After it, the module that
asks holds its own reference, and patching the package changes nothing - the test passes,
having tested the machine it meant to replace. Nineteen lines in this suite replaced something
as `tray_popup.<name>`; eight of them, in seven places, reached the popup's own code and had
quietly stopped working.

Both of those happen to every module that becomes a package, so both rules are held for all of
them in `tests/test_names.py` and `tests/test_reexports.py`. What is here is what is the
popup's own: the surface it gives, the order its files are layered in, and the six of them
that may not touch Windows.
"""
from __future__ import annotations

import ast
from pathlib import Path
import re
import sys
import unittest

_HERE = str(Path(__file__).resolve().parent)
for entry in (str(Path(_HERE).parent / "src"), _HERE):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import srcscan  # noqa: E402
from codex_auto_resume import tray_popup  # noqa: E402

ROOT = Path(_HERE).parent
PACKAGE = "codex_auto_resume.tray_popup"

# The twelve files, in the order `__init__` re-exports them: the six that ask Windows nothing,
# then Windows and what is drawn with it. It is a dependency order, and the test below holds it
# that way - so the list reads as the layering it is, rather than as twelve names.
MODULES = ("words", "model", "placement", "motion", "elevation", "layout",
           "win32", "fonts", "theme", "gdiplus", "renderer", "window")
ASKS_WINDOWS_NOTHING = MODULES[:6]

# What `tray_popup.<name>` gave before the split, name for name. `countdown` is the one public
# name not carried over: it was `from .ui.words import countdown`, re-exported by accident, and
# nothing outside ever read it there.
SURFACE = {
    "APP_MODE_VALUE", "ATTENTION_OVERLAYS", "BITMAP", "BITMAPINFO", "BITMAPINFOHEADER",
    "CHIP_ALPHA", "CLICK_AWAY_SECONDS", "CONTRAST_COLOURS", "CONTROL_CALLS", "CS_DROPSHADOW",
    "DEPTH", "DOT_FILL", "DOUBLE_CLICK_SECONDS", "DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2",
    "DT_CALCRECT", "DT_CENTER", "DT_EDITCONTROL", "DT_END_ELLIPSIS", "DT_NOPREFIX",
    "DT_SINGLELINE", "DT_VCENTER", "DT_WORDBREAK", "DWMWA_USE_IMMERSIVE_DARK_MODE",
    "DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_20H1", "DWMWA_WINDOW_CORNER_PREFERENCE",
    "DWMWCP_ROUND", "FIRST_READ_WAIT_MS", "FRAME_MS", "GR_GDIOBJECTS", "GR_USEROBJECTS",
    "GdiplusStartupInput", "HCF_HIGHCONTRASTON", "HIGHCONTRASTW", "HKEY_CURRENT_USER",
    "HWND_TOPMOST", "ICONINFO", "IDC_ARROW", "INTERPOLATION_NEAREST", "KEY_REPEAT_SECONDS",
    "KEY_WAS_DOWN", "LOGFONTW", "MARK", "MAX_TASKS", "MONITORINFO",
    "MONITOR_DEFAULTTONEAREST", "NONCLIENTMETRICSW", "NOTICE_SECONDS", "NOTIFYICONIDENTIFIER",
    "PAINTSTRUCT", "PERSONALIZE_KEY", "PIXEL_FORMAT_32BPP_PARGB", "PIXEL_FORMAT_32BPP_RGB",
    "PointF", "Popup", "PopupModel", "REFRESH_TICKS", "ROLES", "RRF_RT_REG_DWORD", "Renderer",
    "SHADOW_MARGIN", "SPI_GETCLIENTAREAANIMATION", "SPI_GETHIGHCONTRAST",
    "SPI_GETNONCLIENTMETRICS", "STALE_CODES", "STATES", "STATE_INK", "SWITCH_GAP",
    "SWP_NOACTIVATE", "SW_HIDE", "SW_SHOW", "SW_SHOWNOACTIVATE", "SYSTEM_COLOURS",
    "THEME_CHOICES", "THEME_SYSTEM", "TIMER_FIRST", "TIMER_FRAME", "TIMER_TICK", "TME_LEAVE",
    "TRACKMOUSEEVENT", "UNIT_PIXEL", "VK_DOWN", "VK_ESCAPE", "VK_RETURN", "VK_SHIFT",
    "VK_SPACE", "VK_TAB", "VK_UP", "WA_INACTIVE", "WIDTH", "WM_ACTIVATE", "WM_APP", "WM_CLOSE",
    "WM_DPICHANGED", "WM_ERASEBKGND", "WM_KEYDOWN", "WM_LBUTTONDOWN", "WM_LBUTTONUP",
    "WM_MOUSELEAVE", "WM_MOUSEMOVE", "WM_PAINT", "WM_POPUP_RESULT", "WM_POPUP_STRINGS",
    "WM_SETTINGCHANGE", "WM_SYSCOLORCHANGE", "WM_TIMER", "WS_EX_TOOLWINDOW", "WS_EX_TOPMOST",
    "WS_POPUP", "_Canvas", "_Fonts", "_Painter", "_PerMonitorDpi", "_ShadowImage", "_declare",
    "_dll", "_gdiplus_acquire", "_gdiplus_release", "_icon_from_pixels", "_pack", "activity",
    "adopt_settings", "animates", "appearance", "apps_use_light_theme", "busy_key",
    "contrast_colour", "effective_theme", "focus_order", "font_candidates", "font_faces",
    "gdiplus_objects", "glide_amount", "gui_resources", "halo", "high_contrast", "hit_test",
    "icon_rect", "is_waiting", "layout", "lift_coverage", "locale_of", "message_face",
    "next_focus", "next_glides", "one_line", "perform", "place", "recipe_shadows",
    "reduced_motion", "role_size", "say", "select_action", "set_reduce_motion", "set_theme",
    "shadow_step", "share_columns", "snapshot_activity", "system_rgb", "task_item",
    "taskbar_edge", "theme_choice", "theme_setting", "tile_ground", "unbroken", "urgency",
    "view_model", "vocabulary", "well_coverage",
}





class SurfaceTests(unittest.TestCase):
    def test_the_package_gives_every_name_the_module_gave(self):
        self.assertEqual(SURFACE - set(dir(tray_popup)), set(), "re-export it from __init__")

    def test_nothing_was_added_to_the_surface_without_being_written_down(self):
        public = {name for name in dir(tray_popup)
                  if not name.startswith("__") and name not in MODULES
                  and name != "annotations"}          # `from __future__ import`
        self.assertEqual(public - SURFACE, set(), "a new name on the popup is a decision: add it above")

    def test_the_twelve_modules_are_all_there_and_nothing_else_is(self):
        listed = {srcscan.module_name(path).split(".")[-1] for path in srcscan.files_of(PACKAGE)}
        self.assertEqual(listed, set(MODULES) | {"tray_popup"})

    def inside(self):
        """{module: the modules of the popup it imports from}."""
        found = {}
        for path in srcscan.files_of(PACKAGE):
            module = srcscan.module_name(path).split(".")[-1]
            if module == "tray_popup":
                continue
            uses = set()
            for node in ast.walk(srcscan.package_asts()[path]):
                if isinstance(node, ast.ImportFrom) and node.level == 1:
                    if node.module in MODULES:
                        uses.add(node.module)
                    elif node.module is None:      # from . import theme as look
                        uses |= {alias.name for alias in node.names if alias.name in MODULES}
            found[module] = uses
        return found

    def test_each_file_uses_only_what_is_above_it(self):
        """MODULES is a dependency order, and `__init__` imports in it. Not decoration: it is
        what says the popup has no cycle in it, and it is how a reader knows that opening
        `words.py` will not send them to `window.py`."""
        inside, above = self.inside(), set()
        for module in MODULES:
            with self.subTest(module):
                self.assertLessEqual(inside[module], above, "it uses a file below it")
            above.add(module)

    def test_the_order_in_the_file_is_the_order_here(self):
        source = srcscan.read(srcscan.modules()[PACKAGE])
        self.assertEqual(re.findall(r"^from \.(\w+) import", source, re.M), list(MODULES))

    def test_the_six_that_ask_windows_nothing_ask_it_nothing(self):
        """The half the documentation's pictures are drawn by: no win32, no registry, no DLL."""
        for module in ASKS_WINDOWS_NOTHING:
            with self.subTest(module):
                self.assertNotIn("win32", self.inside()[module])
                self.assertNotIn("ctypes", srcscan.read(
                    srcscan.modules()[PACKAGE + "." + module]))

    def test_no_two_modules_define_the_same_name(self):
        """`__init__` re-exports twelve files in order, so a name in two of them would resolve
        to whichever is imported last - and moving a line between files would change it."""
        owners: dict[str, list[str]] = {}
        for path in srcscan.files_of(PACKAGE):
            module = srcscan.module_name(path).split(".")[-1]
            if module == "tray_popup":
                continue
            for node in srcscan.package_asts()[path].body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    owners.setdefault(node.name, []).append(module)
                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            owners.setdefault(target.id, []).append(module)
        self.assertEqual({name: where for name, where in owners.items() if len(where) > 1}, {})


if __name__ == "__main__":
    unittest.main()
