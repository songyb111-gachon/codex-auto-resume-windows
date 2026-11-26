"""Comparison A (P6-DESIGN 3.3): the C# host's surfaces laid out exactly as the Python reference lays them out.

The host (CodexAutoResume.exe, v0.6.27) draws the popup, the icon's menu, the tip card, the notification cards and the
icon itself in C# (gui/host.sources, [surface]), ported call for call from src/codex_auto_resume/ui. Each plan the C#
makes - every rectangle, text run, colour word, target and frame - must be the reference's, exactly, over a fixed matrix:
four scales (1, 1.25, 1.5, 2) by five languages (en, ko, ja, de, and ar for right to left) by the states the surfaces
and their motion plans name.

Fonts drop out. Every measure the layouts make comes down to one DrawTextW(DT_CALCRECT) question (and the tip's two
font questions); here the reference asks a stand-in for GDI that answers by arithmetic, every question and answer is
recorded into the job's table, and the C# answers from that table (TableTextCalc) and from nothing else. So the plans
agree exactly when the layout arithmetic does, on any machine, CI included. Comparison B (the pixels, byte for byte with
the committed pictures) and C (the motion pictures) are the main session's, on the picture machine.

The C# is compiled with the in-box csc into a temporary folder with a small driver, and run once as a console program
with CREATE_NO_WINDOW: it reads the job and writes the plans. Nothing here makes a window, draws on the screen or
captures anything.
"""
from __future__ import annotations

import contextlib
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "build"))

import guiscan  # noqa: E402

CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
CREATE_NO_WINDOW = 0x08000000
SCALES = (1.0, 1.25, 1.5, 2.0)
LOCALES = ("en", "ko", "ja", "de", "ar")
JOB_FORMAT = "car-surface-job/1"

DRIVER = """
namespace CodexAutoResume
{
    internal static class SurfaceParityDriver
    {
        private static int Main(string[] args)
        {
            return SurfaceRender.RunJob(args[0], args[1]);
        }
    }
}
"""


# ------------------------------------------------------------------------------------------- a stand-in for GDI
def _advance(char: str, size: float) -> float:
    code = ord(char)
    if char == " ":
        return size * 0.3
    if 0x1100 <= code <= 0x11FF or 0x2E80 <= code <= 0x9FFF or 0xAC00 <= code <= 0xD7AF or 0xF900 <= code <= 0xFAFF \
            or 0xFF00 <= code <= 0xFFEF:
        return size * 1.0
    if char.isdigit():
        return size * 0.55
    if char.isupper():
        return size * 0.62
    return size * 0.5


class StandIn:
    """What DrawTextW(DT_CALCRECT) answers, by arithmetic: a role's size at the scale, an advance per character, lines
    broken at spaces as GDI's word break breaks them (a word wider than the line on its own line, cut where it must be),
    and a line height. Every question and its answer is kept, as the job's table."""

    DT_WORDBREAK, DT_SINGLELINE = 0x10, 0x20

    def __init__(self):
        self.tables = {}
        self.metric_tables = {}
        self.ink_tables = {}
        self.where = None          # (locale, scale) of the fonts being asked
        self.role = None

    @property
    def name(self) -> str:
        return "%s@%r" % self.where

    def size(self, role) -> float:
        from codex_auto_resume.ui.popup import fonts
        return fonts.role_size(role, self.where[0]) * self.where[1]

    def width_of(self, text, size) -> int:
        return int(sum(_advance(char, size) for char in text))

    def answer(self, role, text, width, flags):
        size = self.size(role)
        line_h = int(round(size * 1.33))
        if flags & self.DT_SINGLELINE or not flags & self.DT_WORDBREAK:
            w, h = self.width_of(text.replace("\n", ""), size), line_h
        else:
            lines = []
            for paragraph in text.split("\n"):
                line = ""
                for word in paragraph.split(" "):
                    candidate = word if not line else line + " " + word
                    if not line or self.width_of(candidate, size) <= width:
                        line = candidate
                    else:
                        lines.append(line)
                        line = word
                    while self.width_of(line, size) > width and len(line) > 1:
                        cut = len(line)
                        while cut > 1 and self.width_of(line[:cut], size) > width:
                            cut -= 1
                        lines.append(line[:cut])
                        line = line[cut:]
                lines.append(line)
            w, h = max(self.width_of(line, size) for line in lines), line_h * len(lines)
        self.tables.setdefault(self.name, {})[(role, text, width, flags)] = (w, h)
        return w, h

    def metrics(self, role):
        size = self.size(role)
        found = (float(int(round(size * 0.92))), float(int(round(size * 0.48))))
        self.metric_tables.setdefault(self.name, {})[role] = found
        return found

    def ink(self, role, text):
        stripped = (text or "").strip()
        found = (0, 0) if not stripped else (len(stripped) % 3, (len(stripped) * 7) % 4)
        self.ink_tables.setdefault(self.name, {})[(role, text)] = found
        return found

    def job_tables(self) -> dict:
        names = set(self.tables) | set(self.metric_tables) | set(self.ink_tables)
        return {name: {"measure": [[role, text, width, flags, w, h]
                                   for (role, text, width, flags), (w, h) in sorted(self.tables.get(name, {}).items())],
                       "metrics": {role: list(found) for role, found in self.metric_tables.get(name, {}).items()},
                       "ink": [[role, text, first, last]
                               for (role, text), (first, last) in sorted(self.ink_tables.get(name, {}).items())]}
                for name in sorted(names)}


class _User32:
    def __init__(self, stand_in):
        self.stand_in = stand_in

    def DrawTextW(self, dc, text, count, rect_ref, flags):
        rect = rect_ref._obj
        w, h = self.stand_in.answer(self.stand_in.role, text, rect.right, flags)
        rect.right, rect.bottom = rect.left + w, rect.top + h
        return h


class _Gdi32:
    def __init__(self, stand_in):
        self.stand_in = stand_in

    def SelectObject(self, dc, handle):
        previous, self.stand_in.role = self.stand_in.role, handle
        return previous


class _Fonts:
    def __init__(self, locale, scale):
        from codex_auto_resume.ui.popup import fonts
        self.key = (locale, scale)
        self.handles = {role: role for role in fonts.ROLES}


class _Canvas:
    dc = 0


@contextlib.contextmanager
def standing_in(stand_in, *modules):
    """Every `_dll` the reference's measures go through answers with the stand-in."""
    fakes = {"user32": _User32(stand_in), "gdi32": _Gdi32(stand_in)}
    saved = [(module, module._dll) for module in modules]
    try:
        for module in modules:
            module._dll = lambda name: fakes[name]
        yield
    finally:
        for module, value in saved:
            module._dll = value


def renderer_for(cls, stand_in, locale, scale):
    """A reference renderer of `cls` that measures through the stand-in and owns no GDI object."""
    renderer = object.__new__(cls)
    renderer.fonts = _Fonts(locale, scale)
    renderer.canvas = _Canvas()
    stand_in.where = (locale, scale)
    return renderer


def plain(value):
    """A plan as JSON gives it back: tuples as lists, nothing the C# could not say."""
    return json.loads(json.dumps(value, ensure_ascii=False))


# ------------------------------------------------------------------------------------------- the matrix
def popup_views(locale) -> list:
    """(name, view model) for the popup: the pictures' own view in `locale`, and variations that reach every branch of
    the layout - no task, the quiet well, the notes, the notice, more, a special day, a busy toggle, labels that wrap."""
    import make_screenshots
    _, base = make_screenshots.popup_view(locale)
    views = [("picture", base)]
    views.append(("empty", dict(base, tasks=[], empty=base["state_text"] + " - " + base["dashboard_text"],
                                counts=[[label, "0"] for label, _ in base["counts"]])))
    views.append(("error", dict(base, tasks=base["tasks"][:1], error=base["toggle_text"] * 3, more=base["dashboard_text"],
                                zero_note=base["state_text"] * 4, observe_note=base["toggle_text"], usage_note="42%",
                                notice=base["dashboard_text"] * 3, toggle_busy=True)))
    views.append(("scene", dict(base, scene="birthday")))
    views.append(("narrow-scene", dict(base, scene="seollal", title=base["title"] * 3)))
    views.append(("long", dict(base, toggle_text=base["toggle_text"] * 3, dashboard_text=base["dashboard_text"] * 2,
                               tasks=[dict(task, name=task["name"] * 6, reason=task["reason"] * 4, status=task["status"] * 5,
                                           check_label=task["check_label"] * 7, checked=index % 2 == 0, busy=index == 1)
                                      for index, task in enumerate(base["tasks"] * 2)])))
    return views


class SurfaceJob:
    """The cases, the reference's plans and the tables, built together."""

    def __init__(self):
        self.stand_in = StandIn()
        self.cases = []
        self.expected = {}

    def add(self, case_id, case, plan):
        self.cases.append(dict(case, id=case_id))
        self.expected[case_id] = plain(plan)

    def popup(self):
        from codex_auto_resume.ui.popup import renderer as renderer_module
        for scale in SCALES:
            for locale in LOCALES:
                for name, vm in popup_views(locale):
                    renderer = renderer_for(renderer_module.Renderer, self.stand_in, locale, scale)
                    with standing_in(self.stand_in, renderer_module):
                        plan = renderer.layout(vm, scale, locale)
                    self.add("popup/%s/%s/%r" % (name, locale, scale),
                             {"surface": "popup", "vm": plain(vm), "scale": scale, "locale": locale,
                              "table": self.stand_in.name}, plan)

    def menu(self):
        from codex_auto_resume import interface
        from codex_auto_resume.ui import popup
        from codex_auto_resume.ui.popup import menuwindow, model as popup_model, renderer as renderer_module
        from codex_auto_resume.ui.tray import menu as tray_menu
        import make_screenshots
        now = make_screenshots.POPUP_NOW
        for scale in SCALES:
            for locale in LOCALES:
                strings = interface.STRINGS[locale]
                _, vm = make_screenshots.popup_view(locale)
                lists = [("icon", tray_menu.menu_items({"enabled": True, "waiting": 2, "running": 1, "next_at": now + 200},
                                                       strings, now, pending=True, armed=sorted(tray_menu.POWER_OFF_WORDS)[0],
                                                       popup=True), False, None),
                         ("paused", tray_menu.menu_items({"enabled": False, "waiting": 0}, strings, now), False,
                          int(300 * scale)),
                         ("row", popup_model.row_menu(dict(vm["tasks"][0], postponed=True, once_words=True), strings,
                                                      "automatic"), True, None)]
                for name, raw, numbered, most in lists:
                    entries = raw
                    result = {}
                    if numbered:
                        entries, actions = popup.menu_numbered(raw)
                        result["numbered"] = entries
                        result["actions"] = [[number, action] for number, action in actions.items()]
                    first = next(entry["text"] for entry in entries if entry and entry.get("enabled"))
                    case = {"surface": "menu", "entries": plain(raw), "numbered": numbered, "scale": scale,
                            "locale": locale, "max_width": most, "table": None,
                            "places": [[[100, 100], [0, 0, 1920, 1080]], [[1900, 1070], [0, 0, 1920, 1040]],
                                       [[-500, 20], [-1920, 0, 0, 1080]], [[10, 10], [0, 0, 100, 100]]],
                            "besides": [[[100, 100, 300, 130], [0, 0, 1920, 1080]],
                                        [[1700, 500, 1900, 530], [0, 0, 1920, 1080]], [[0, 0, 50, 20], [0, 0, 60, 60]]],
                            "currents": [None, 0, 2, 5, 99], "selected": 2, "strings": strings,
                            "letters": [[None, first[:1]], [2, first[:1].upper()], [None, " "], [None, "ß"],
                                        [3, "Z"]]}
                    renderer = renderer_for(menuwindow.MenuRenderer, self.stand_in, locale, scale)
                    with standing_in(self.stand_in, renderer_module):
                        plan = renderer.menu_layout(entries, scale, locale, most)
                    case["table"] = self.stand_in.name
                    result["plan"] = plan
                    result["places"] = [popup.menu_place(plan, point, work) for point, work in case["places"]]
                    result["besides"] = [popup.menu_beside(plan, box, work) for box, work in case["besides"]]
                    result["steps"] = [[popup.menu_step(entries, current), popup.menu_step(entries, current, True)]
                                       for current in case["currents"]]
                    result["ends"] = [popup.menu_end(entries), popup.menu_end(entries, True)]
                    result["letters"] = [list(popup.menu_letter(entries, current, char)) for current, char in case["letters"]]
                    result["accessible"] = popup.menu_accessible_items(plan, 2, strings)
                    self.add("menu/%s/%s/%r" % (name, locale, scale), case, result)

    def tip(self):
        from codex_auto_resume import interface
        from codex_auto_resume.ui.popup import renderer as renderer_module
        from codex_auto_resume.ui.tray import tipcard, tipplan, words
        import test_tray_tipcard as fixtures
        anchors = [[[100, 1040, 124, 1064], [110, 1050], [112, 1052]], [[100, 1040, 124, 1064], [5, 5], None],
                   [None, None, [7, 9]], [[1, 2, 3, 4], None, None], [None, None, None]]
        for scale in SCALES:
            for locale in LOCALES:
                strings = interface.STRINGS[locale]
                for name, edition, day in (("waiting", None, None), ("metered", "advanced", None), ("held", None, "christmas"),
                                           ("failed", "advanced", "birthday"), ("empty", None, None), ("paused", None, None)):
                    snapshot = fixtures.FIXTURES[name]
                    parts = words.tooltip_parts(snapshot, strings, fixtures.NOW, edition)
                    light = tipcard.tip_light(snapshot, fixtures.NOW)
                    renderer = renderer_for(tipcard.TipRenderer, self.stand_in, locale, scale)
                    renderer.metrics, renderer.ink = self.stand_in.metrics, self.stand_in.ink
                    with standing_in(self.stand_in, renderer_module):
                        plan = renderer.tip_layout(parts, light, scale, locale, day)
                    result = {"plan": plan, "text": tipplan.tip_text(plan),
                              "anchors": [tipplan.tip_anchor(*three) for three in anchors]}
                    self.add("tip/%s/%s/%r" % (name, locale, scale),
                             {"surface": "tip", "parts": plain(parts), "light": light, "scale": scale, "locale": locale,
                              "day": day, "anchors": anchors, "table": self.stand_in.name}, result)

    def place(self):
        from codex_auto_resume.ui import popup
        screens = [((0, 0, 1920, 1040), (0, 0, 1920, 1080)), ((0, 40, 1920, 1080), (0, 0, 1920, 1080)),
                   ((60, 0, 1920, 1080), (0, 0, 1920, 1080)), ((0, 0, 1860, 1080), (0, 0, 1920, 1080)),
                   ((0, 0, 1920, 1080), (0, 0, 1920, 1080)), ((-1920, 0, 0, 1040), (-1920, 0, 0, 1080))]
        anchors = [(1800, 1045, 1824, 1069), (5, 500, 29, 524), (900, 3, 924, 27), (-3, -3, 1, 1), None]
        places = []
        for work, monitor in screens:
            for icon in anchors:
                for cursor in (None, (1700, 1050), (3, 3), (-7, -7)):
                    for size in ((688, 900), (2000, 300), (101, 99), (3, 3)):
                        places.append([list(size), list(work), list(monitor), list(icon) if icon else None,
                                       list(cursor) if cursor else None, 12])
        targets = [[["check", "k1"], [10, 10, 100, 40]], [["check", "k2"], [10, 50, 100, 80]], [["toggle"], [10, 90, 50, 120]],
                   [["dashboard"], [60, 90, 100, 120]]]
        points = [[10, 10], [99, 39], [100, 40], [55, 95], [59, 119], [60, 119], [0, 0], [-1, 50]]
        currents = [None, ["check", "k1"], ["dashboard"], ["toggle"], ["nothing"]]
        found_places = []
        for size, work, monitor, icon, cursor, gap in places:
            x, y, edge = popup.place(tuple(size), tuple(work), tuple(monitor), tuple(icon) if icon else None,
                                     tuple(cursor) if cursor else None, gap=gap)
            found_places.append([x, y, edge])
        as_targets = [(tuple(target), tuple(rect)) for target, rect in targets]
        order = popup.focus_order(as_targets)
        result = {"places": found_places, "hits": [popup.hit_test(as_targets, x, y) for x, y in points], "order": order,
                  "focus": [[popup.next_focus(order, tuple(current) if current else None),
                             popup.next_focus(order, tuple(current) if current else None, True)] for current in currents]}
        self.add("place/popup", {"surface": "place", "places": places, "targets": targets, "points": points,
                                 "currents": currents}, result)

    def popup_motion(self):
        from codex_auto_resume.ui.popup import motion
        moments = [0.0, 1.0, 16.0, 40.0, 79.9, 80.0, 120.0, 159.0, 160.0, 400.0, 1234.5, 2200.0, 4399.0, 4400.0, 10000.0,
                   123456.789]
        states = ["monitoring", "waiting", "checking", "recovering", "paused", "idle", "attention", "failed", "unknown"]
        designs = ["soft", "classic", "plain"]
        halos = [motion.halo(state, moment, moment, reduced=reduced, design=design)
                 for state in states for design in designs for reduced in (False, True) for moment in moments]
        seen = {"a": True, "b": False, "c": True, "d": False}
        previous = {"a": False, "b": False, "c": True}
        running = {"a": (0.0, 0.0, 1.0), "c": (0.0, 1.0, 0.0)}
        result = {"halos": halos,
                  "openings": [list(motion.opening(moment, 8)) for moment in moments],
                  "closings": [list(motion.closing(moment, 200)) for moment in moments],
                  "faces": [list(motion.face_amount((5.0, None, 80), moment)) for moment in moments],
                  "glides": [list(motion.glide_amount((10.0, 0.25, 1.0), moment)) for moment in moments],
                  "next": [motion.next_glides(seen, previous if opened else None, running, moment, animate=animate)
                           for moment in moments for animate in (True, False) for opened in (True, False)],
                  "lengths": [motion.face_length(before, after) for before in ("rest", "hover", "pressed", "busy")
                              for after in ("rest", "hover", "pressed", "busy")]}
        self.add("motion/popup", {"surface": "popup_motion", "moments": moments, "states": states, "designs": designs},
                 result)

    def job(self) -> dict:
        return {"format": JOB_FORMAT, "tables": self.stand_in.job_tables(), "cases": self.cases}


def first_difference(expected, found, path="plan"):
    """Where two plans first differ, as a path and the two values; None when they are equal."""
    if isinstance(expected, dict) and isinstance(found, dict):
        for key in list(expected) + [key for key in found if key not in expected]:
            if key not in found or key not in expected:
                return "%s: key %r only in %s" % (path, key, "the reference" if key in expected else "the C#")
            difference = first_difference(expected[key], found[key], "%s.%s" % (path, key))
            if difference:
                return difference
        return None
    if isinstance(expected, list) and isinstance(found, list):
        if len(expected) != len(found):
            return "%s: %d items in the reference, %d in the C#" % (path, len(expected), len(found))
        for index, (one, other) in enumerate(zip(expected, found)):
            difference = first_difference(one, other, "%s[%d]" % (path, index))
            if difference:
                return difference
        return None
    if isinstance(expected, bool) or isinstance(found, bool):
        same = type(expected) is type(found) and expected == found
    else:
        same = expected == found
    return None if same else "%s: reference %r, C# %r" % (path, expected, found)


@unittest.skipUnless(CSC.is_file(), "needs the in-box C# compiler")
class SurfaceParityTests(unittest.TestCase):
    """Every case of the matrix: the C#'s plan is the reference's, exactly."""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory(prefix="car-surface-parity-")
        folder = Path(cls.folder.name)
        driver = folder / "SurfaceParityDriver.cs"
        driver.write_text(DRIVER, encoding="utf-8")
        sources = [ROOT / name for name in guiscan.host_group("surface") + guiscan.host_group("generated")]
        exe = folder / "surface-parity.exe"
        built = subprocess.run([str(CSC), "-nologo", "-target:exe", "-platform:x64", "-warnaserror", "-optimize+",
                                "-out:%s" % exe, "-r:System.dll", "-r:System.Drawing.dll"]
                               + [str(path) for path in sources] + [str(driver)],
                               capture_output=True, timeout=600, creationflags=CREATE_NO_WINDOW)
        if built.returncode != 0:
            raise AssertionError("the surfaces do not compile:\n%s" % built.stdout.decode("utf-8", "replace"))
        job = SurfaceJob()
        job.popup()
        job.menu()
        job.tip()
        job.place()
        job.popup_motion()
        cls.expected = job.expected
        job_path, out_path = folder / "job.json", folder / "job.out.json"
        job_path.write_text(json.dumps(job.job(), ensure_ascii=False), encoding="utf-8")
        ran = subprocess.run([str(exe), str(job_path), str(out_path)], capture_output=True, timeout=600,
                             creationflags=CREATE_NO_WINDOW)
        if not out_path.is_file():
            raise AssertionError("the render mode wrote nothing (exit %d):\n%s"
                                 % (ran.returncode, ran.stdout.decode("utf-8", "replace")))
        answer = json.loads(out_path.read_text(encoding="utf-8"))
        cls.exit_code = ran.returncode
        cls.found = {case["id"]: case for case in answer["cases"]}

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def compare(self, prefix):
        ids = [case_id for case_id in self.expected if case_id.startswith(prefix)]
        self.assertTrue(ids, "no case for %s" % prefix)
        wrong = []
        for case_id in ids:
            found = self.found.get(case_id, {})
            if "error" in found:
                wrong.append("%s: %s" % (case_id, found["error"]))
                continue
            difference = first_difference(self.expected[case_id], found.get("plan"))
            if difference:
                wrong.append("%s: %s" % (case_id, difference))
        self.assertEqual(wrong[:10], [], "%d of %d cases differ" % (len(wrong), len(ids)))

    def test_the_popup_is_laid_out_as_the_reference_lays_it_out(self):
        self.compare("popup/")

    def test_the_menu_is_laid_out_placed_and_keyed_as_the_reference_does_it(self):
        self.compare("menu/")

    def test_the_tip_card_is_laid_out_as_the_reference_lays_it_out(self):
        self.compare("tip/")

    def test_the_popup_is_placed_hit_and_focused_as_the_reference_does_it(self):
        self.compare("place/")

    def test_the_popups_motion_is_the_references_frame_for_frame(self):
        self.compare("motion/popup")


class SurfaceSourceTests(unittest.TestCase):
    def test_the_hosts_json_is_the_windows_json_byte_for_byte(self):
        def body(path):
            text = (ROOT / path).read_text(encoding="utf-8").replace("\r\n", "\n")
            start = text.index("    internal static class Json\n")
            end = text.index("\n    }\n", start) + len("\n    }\n")
            return text[start:end]
        self.assertEqual(body("gui/SurfaceJson.cs"), body("gui/WindowJson.cs"))

    def test_the_surfaces_are_on_the_hosts_list_and_not_the_windows(self):
        surface = set(guiscan.host_group("surface"))
        self.assertIn("gui/SurfaceRender.cs", surface)
        self.assertEqual(surface & set(guiscan.manifest()), set())
