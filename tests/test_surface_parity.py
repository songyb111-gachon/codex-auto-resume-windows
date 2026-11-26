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
        anchors = [(1800, 1045, 1824, 1069), (5, 500, 29, 524), (900, 3, 924, 27), (-3, -3, 1, 1), (-1001, 1045, -1000, 1046),
                   None]
        places = []
        for work, monitor in screens:
            for icon in anchors:
                for cursor in (None, (1700, 1050), (3, 3), (-7, -7), (-1001, 1050)):
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

    def card(self):
        from codex_auto_resume import notice_card
        from codex_auto_resume.ui.card import card as card_module
        from codex_auto_resume.ui.popup import renderer as renderer_module
        import make_screenshots
        for scale in SCALES:
            for locale in LOCALES:
                base = make_screenshots.card_view(locale)
                one = [dict(base["actions"][1], target=["action", 0])]
                three = base["actions"] + [dict(base["actions"][0], label=base["actions"][0]["label"] * 2,
                                                target=["action", 2])]
                views = [("picture", base), ("no-chip", dict(base, chip="", actions=one)),
                         ("three", dict(base, actions=three, line="", origin="")),
                         ("long", dict(base, chip=base["chip"] * 5, title=base["title"] * 4, line=base["line"] * 3,
                                       actions=[dict(action, label=action["label"] * 4) for action in base["actions"]])),
                         ("scene", dict(base, scene="chuseok")), ("bare", dict(base, actions=[], chip=None))]
                for name, vm in views:
                    renderer = renderer_for(renderer_module.Renderer, self.stand_in, vm["locale"], scale)
                    with standing_in(self.stand_in, renderer_module):
                        plan = notice_card.layout(vm, scale, renderer.measure)
                    self.add("card/%s/%s/%r" % (name, locale, scale),
                             {"surface": "card", "vm": plain(vm), "scale": scale, "locale": vm["locale"],
                              "table": self.stand_in.name}, {"plan": plan})
        depths = [0.0, 0.1, 0.5, 0.77, 1.0, 1.5, -0.2]
        themes, designs = ["light", "dark"], ["soft", "classic", "plain"]
        stacks = [[[[320, 200], [320, 260], [320, 180]], [0, 0, 1920, 1040], [0, 0, 1920, 1080], [1800, 1045, 1824, 1069]],
                  [[[320, 500], [320, 500], [320, 500]], [0, 0, 1366, 728], [0, 0, 1366, 768], None],
                  [[[300, 200], [310, 220]], [0, 40, 1920, 1080], [0, 0, 1920, 1080], [900, 3, 924, 27]],
                  [[[300, 200], [310, 220], [290, 100]], [60, 0, 1920, 1080], [0, 0, 1920, 1080], [5, 100, 29, 124]],
                  [[[300, 200], [310, 220]], [0, 0, 1860, 1080], [0, 0, 1920, 1080], [1880, 900, 1904, 924]],
                  [[], [0, 0, 1920, 1040], [0, 0, 1920, 1080], None]]
        fits = [[96.0, [0, 0, 1920, 1040], 1.5], [192.0, [0, 0, 1366, 728], 2.25], [144.0, None, 2.0], [96.0, [0, 0, 800, 600], 1.0],
                [96.0, [0, 0, 800, 600], None]]
        holds = [None, 100.0, 6000.0, 25000.0, True]
        edges = ["bottom", "top", "left", "right", None, "middle"]
        result = {"shadows": [], "levels": [notice_card.depth_level(depth) for depth in depths]}
        for theme in themes:
            for design in designs:
                found = notice_card.float_shadows(theme, design)
                result["shadows"].append({"shadows": [list(s) for s in found],
                                          "at": [[list(s) for s in notice_card.shadow_at(found, depth)] for depth in depths],
                                          "margins": [notice_card.shadow_margin(found, scale) for scale in SCALES]})
        result["stacks"] = []
        for sizes, work, monitor, anchor in stacks:
            positions, edge = notice_card.stack_positions([tuple(size) for size in sizes], tuple(work), tuple(monitor),
                                                          tuple(anchor) if anchor else None, gap=12, spacing=10)
            result["stacks"].append([positions, edge])
        result["fits"] = [card_module.Card.fitting({"dpi": dpi, "work": tuple(work) if work else None}, {"text": text})
                          for dpi, work, text in fits]
        result["holds"] = [notice_card.hold_ms(value) for value in holds]
        result["rises"] = [notice_card.rise_vector(edge) for edge in edges]
        self.add("cardroom/all", {"surface": "card_room", "themes": themes, "designs": designs, "depths": depths,
                                  "scales": list(SCALES), "stacks": stacks, "fits": fits, "holds": holds, "edges": edges},
                 result)
        lives = {
            "plain": [["new", 1000.0, 6000.0, False, None], ["frame", 1000.0], ["frame", 1100.0], ["frame", 1340.0],
                      ["frame", 4000.0], ["wait", 4000.0], ["pause", 4500.0, True], ["frame", 9000.0], ["wait", 9000.0],
                      ["pause", 9100.0, False], ["wait", 9200.0], ["frame", 11000.0], ["frame", 11100.0],
                      ["pause", 11150.0, True], ["frame", 11200.0], ["frame", 11400.0], ["pause", 11500.0, False],
                      ["frame", 13500.0], ["frame", 13600.0], ["frame", 14000.0], ["moving", 14000.0]],
            "retire": [["new", 0.0, 6000.0, False, [10, 20]], ["delay", 120.0], ["frame", 50.0], ["retire", 60.0, False],
                       ["frame", 100.0], ["frame", 400.0], ["new", 0.0, 6000.0, False, [10, 20]], ["frame", 200.0],
                       ["retire", 200.0, True], ["frame", 250.0], ["retire", 260.0, True], ["frame", 300.0]],
            "slide": [["new", 0.0, 6000.0, False, [100, 900]], ["move", 10.0, [100, 600], 120.0], ["place", 50.0],
                      ["moving", 50.0], ["place", 200.0], ["place", 300.0], ["place", 409.0], ["place", 410.0],
                      ["move", 500.0, [100, 600], 0.0], ["place", 500.0], ["move", 600.0, [80, 300], 0.0],
                      ["move", 700.0, [80, 100], 0.0], ["place", 800.0], ["place", 2000.0]],
            "reduced": [["new", 0.0, 2000.0, True, [5, 5]], ["frame", 0.0], ["move", 10.0, [9, 9], 0.0], ["place", 11.0],
                        ["moving", 20.0], ["wait", 30.0], ["frame", 2500.0], ["pause", 2600.0, True], ["retire", 2700.0, False],
                        ["frame", 2800.0]],
            "forever": [["new", 0.0, "inf", False, None], ["frame", 400.0], ["wait", 400.0], ["restart", 500.0],
                        ["frame", 600.0], ["frame", 1e9], ["entrance", 100.0, False], ["entrance", 100.0, True],
                        ["leaving", 50.0, 0.8, False, 220.0], ["leaving", 300.0, 0.8, False, 220.0],
                        ["leaving", 50.0, 0.8, True, 220.0]],
        }
        for name, steps in lives.items():
            self.add("cardlife/%s" % name, {"surface": "card_life", "steps": steps}, self.replay(steps))

    @staticmethod
    def replay(steps):
        from codex_auto_resume import notice_card
        motion, answers = None, []
        for step in steps:
            verb, now = step[0], step[1] if len(step) > 1 and isinstance(step[1], float) else 0.0
            answer = None
            if verb == "new":
                motion = notice_card.CardMotion(now, hold_ms=float(step[2]), reduced=step[3],
                                                position=tuple(step[4]) if step[4] else None)
            elif verb == "frame":
                answer = motion.frame(now)._asdict()
            elif verb == "pause":
                motion.pause(now, step[2])
            elif verb == "retire":
                motion.retire(now, quick=step[2])
            elif verb == "move":
                motion.move_to(now, step[2], step[3])
            elif verb == "place":
                answer = motion.place(now)
            elif verb == "moving":
                answer = motion.moving(now)
            elif verb == "wait":
                answer = motion.wait_ms(now)
            elif verb == "restart":
                motion.restart(now)
            elif verb == "delay":
                motion.delay(now)
            elif verb == "entrance":
                answer = notice_card.entrance(now, reduced=step[2])._asdict()
            elif verb == "leaving":
                answer = notice_card.leaving(now, step[2], reduced=step[3], duration=step[4])
            state = [None] * 7 if motion is None else [motion.phase, motion.since, motion.hold_left, motion.from_alpha,
                                                       motion.exit_ms, motion.paused, motion.final]
            answers.append([answer] + state)
        return answers

    def icon(self):
        import hashlib
        from codex_auto_resume.ui.tray import motion
        states = ["watching", "recovering", "idle", "attention", "failed", "unknown"]
        fines = [1, 4]
        moments = [0.0, 1.0, 999.0, 4400.0, 13199.0, 13200.0, 13300.5, 14960.0, 16000.0, 17000.0, 17600.0, 20000.0,
                   21999.0, 22000.0, 1000.0 * 3.3, 123456.7, 7777777.7]
        frames = [[list(motion.icon_frame(state, moment, None, reduced=reduced, fine=fine)),
                   motion.icon_frame_ms(state, moment, None, reduced=reduced, fine=fine), motion.icon_turn(state, moment)]
                  for state in states for fine in fines for reduced in (False, True) for moment in moments]
        colours = []
        for state in states:
            head = motion.icon_head_colour(state)
            colours.append([list(head), [list(motion.icon_level_colour(head, level))
                                         for level in range(-1, motion.ICON_MOTION["levels"] + 1)],
                            motion.icon_brand_state(state)])
        sizes, stride = [16, 20, 24, 32], 5
        pictures = []
        for size in sizes:
            for fine in fines:
                made = motion.IconFrames(size, fine)
                composed = [hashlib.sha256(made.compose(position, motion.icon_level_colour(motion.icon_head_colour(state),
                                                                                           position % 24))).hexdigest()
                            for state in states for position in range(0, len(made.heads), stride)]
                pictures.append([hashlib.sha256(made.ground).hexdigest(), composed])
        allowed = [motion.icon_motion_allowed(reduced=bool(bits & 1), contrast=bool(bits & 2), battery_saver=bool(bits & 4),
                                              locked=bool(bits & 8), hidden=bool(bits & 16), frames=not bits & 32)
                   for bits in range(64)]
        words = ["monitoring", "waiting", "checking", "recovering", "paused", "idle", "attention", "failed", "", None, "x"]
        result = {"frames": frames, "colours": colours, "pictures": pictures, "allowed": allowed,
                  "lights": [motion.ICON_FOR_LIGHT.get(word, "idle") for word in words]}
        self.add("icon/all", {"surface": "icon", "states": states, "fines": fines, "moments": moments, "sizes": sizes,
                              "stride": stride, "words": words}, result)
        for look in ("birthday", "new_year", "christmas", "seollal", "chuseok"):
            pictures = []
            for size in (16, 24, 32, 48):
                made = motion.IconFrames(size, 1, look)
                composed = [hashlib.sha256(made.compose(position, motion.icon_level_colour(motion.icon_head_colour(state),
                                                                                           position % 24))).hexdigest()
                            for state in states for position in range(0, len(made.heads), stride)]
                pictures.append([hashlib.sha256(made.ground).hexdigest(), composed])
            shown = {"surface": "icon", "states": states, "fines": [1], "moments": [0.0], "sizes": [16, 24, 32, 48],
                     "stride": stride, "words": words, "look": look}
            frames_here = [[list(motion.icon_frame(state, 0.0, None, reduced=reduced, fine=1)),
                            motion.icon_frame_ms(state, 0.0, None, reduced=reduced, fine=1), motion.icon_turn(state, 0.0)]
                           for state in states for reduced in (False, True)]
            self.add("icon/" + look, shown, dict(result, frames=frames_here, pictures=pictures))

    # High Contrast's system colours, fixed so the paint is the same on every machine (a black scheme's).
    SYSTEM = {"Window": [0, 0, 0], "WindowFrame": [255, 255, 255], "WindowText": [255, 255, 255],
              "Highlight": [26, 235, 255], "HighlightText": [0, 0, 0], "Control": [0, 0, 0], "GrayText": [63, 242, 63]}
    LOOKS = [[theme, design, contrast] for contrast in (False, True) for theme in ("light", "dark")
             for design in ("soft", "classic", "plain")]

    def paint(self):
        """Each plan's paint in every look: the cases already laid out, painted by the reference's renderer."""
        from codex_auto_resume.ui.popup import renderer as renderer_module
        wanted = [case for case in self.cases
                  if case["id"].rsplit("/", 1)[-1] in ("1.5", "2.0") and case["id"].split("/")[0] in ("popup", "card", "tip", "menu")
                  and case["id"].split("/")[2] in ("en", "ar", "ko") and case["id"].split("/")[1] in ("picture", "error", "metered", "icon", "row", "three")]
        saved = renderer_module.system_rgb
        renderer_module.system_rgb = lambda name: tuple(self.SYSTEM[name])
        try:
            for case in wanted:
                expected = self.expected[case["id"]]
                plan = expected["plan"] if "plan" in expected and isinstance(expected["plan"], dict) and "items" in expected["plan"] else expected
                looks = []
                for theme, design, contrast in self.LOOKS:
                    renderer = object.__new__(renderer_module.Renderer)
                    renderer.theme, renderer._look_design, renderer._contrast, renderer.canvas = theme, design, contrast, None
                    items = []
                    for item in plan["items"]:
                        found = {}
                        if "radius" in item or "corner" in item:
                            found["corner"] = renderer._corner(item, plan["scale"])
                        if item["kind"] == "text":
                            found["colour"] = renderer._rgb(item["colour"])
                        if item["kind"] == "chip":
                            found["tone"] = renderer._rgb(item["tone"])
                        if item["kind"] == "button":
                            found["faces"] = [renderer.face_colours(item, state) for state in ("rest", "hover", "pressed", "busy")]
                            found["lifted"] = renderer._lifted(item, None)
                        items.append(found)
                    looks.append({"items": items, "depth": renderer._depth(), "smoothing": renderer.smoothing(),
                                  "control": renderer._control_radius(plan["scale"]), "canvas": renderer._rgb("canvas"),
                                  "focus": renderer._argb("focus"), "ink": renderer._colorref("ink")})
                self.add("paint/" + case["id"], {"surface": "paint", "of": dict(case), "looks": self.LOOKS,
                                                 "system": self.SYSTEM}, {"looks": looks})
        finally:
            renderer_module.system_rgb = saved

    def shape(self):
        from codex_auto_resume.brand import shape
        boxes = [[[0, 0, 100, 60], 16.0, 0.6], [[3.5, 4.5, 200.25, 40.75], 11.0, 0.6], [[0, 0, 40, 22], 11.0, 0.6],
                 [[0, 0, 40, 22], 999.0, 0.6], [[10, 10, 30, 30], 7.0, 0.0], [[0, 0, 0.8, 0.8], 5.0, 0.6],
                 [[0, 0, 688, 900], 32.0, 0.6], [[0, 0, 24, 24], 11.0, 0.6], [[0, 0, 50, 20], 9.5, 0.3]]
        points = [[0.0, 0.0], [10.0, 5.0], [49.0, 29.0], [-49.5, -29.5], [45.0, 25.0], [48.0, 28.5], [60.0, 0.0],
                  [11.0, 10.5], [-19.0, 9.0], [3.3, -2.2]]
        result = {"outlines": [], "flats": [], "distances": [], "insides": [],
                  "designs": [shape.design_smoothing(design) for design in ("soft", "classic", "plain")]}
        for rect, radius, smoothing in boxes:
            outline = shape.outline(rect, radius, smoothing)
            result["outlines"].append(outline)
            result["flats"].append(shape.flatten(outline, 8))
            half_w, half_h = (rect[2] - rect[0]) / 2.0, (rect[3] - rect[1]) / 2.0
            result["distances"].append([shape.distance(x, y, half_w, half_h, radius, smoothing) for x, y in points])
            result["insides"].append([shape.inside(x + rect[0] + half_w, y + rect[1] + half_h, rect, radius, smoothing)
                                      for x, y in points])
        self.add("shape/all", {"surface": "shape", "boxes": boxes, "points": points}, result)

    GDIP_CALLS = [
        ["fill_round", [0, 0, 160, 120], 0, 4293519867], ["fill_round", [8.5, 6.25, 120.75, 70.5], 16, 4282079160],
        ["stroke_round", [10, 80, 90, 112], 11, 4291024079, 1.5], ["fill_round", [100, 80, 140, 102], 999, 2852126720],
        ["fill_circle", [130.3, 30.7, 9.2, 4278242004]], ["fill_polygon", [[20, 20], [60, 10], [44, 50.5], [12.25, 40]], 3439329279],
        ["fill_ellipse", 70, 95, 22.5, 7.25, 1612513279], ["stroke_lines", [[5, 115], [60, 100], [150, 118]], 4294901760, 2.0],
        ["clip_round", [30, 30, 110, 75], 12], ["fill_round", [0, 0, 160, 120], 0, 1342177535], ["clip_none"],
        ["clip_rect", [0, 0, 80, 60]], ["fade", [0, 0, 160, 60], 20.5, 70.25, [242, 163, 58]], ["clip_none"],
        ["arc", 120, 60, 18.5, 33.0, 100.0, 4285636863, 1.6],
        ["glow", 40.5, 60.25, 14.4, [[0.0, 0.67], [0.625, 0.67], [0.6625, 0.58], [0.9, 0.5], [1.0, 0.0]], [6, 182, 212], 0.5],
    ]

    def gdip(self):
        """The painter's calls into an offscreen canvas: the reference's own _Painter on its own _Canvas, in memory,
        and the same calls in C# - pixels byte for byte, and no GDI+ object left behind."""
        import hashlib
        from codex_auto_resume.ui.popup import gdiplus, win32
        win32._declare()
        gdiplus._gdiplus_acquire()
        try:
            for smoothing in (0.6, 0.0):
                for name, fmt in (("rgb", gdiplus.PIXEL_FORMAT_32BPP_RGB), ("pargb", gdiplus.PIXEL_FORMAT_32BPP_PARGB)):
                    for keep in (False, True):
                        canvas = gdiplus._Canvas()
                        try:
                            canvas.ensure(160, 120)
                            canvas.smoothing = smoothing
                            before = gdiplus.gdiplus_objects()
                            with gdiplus._Painter(canvas, fmt) as paint:
                                if keep:
                                    paint.keep_solids()
                                for call in self.GDIP_CALLS:
                                    verb, arguments = call[0], call[1:]
                                    if verb in ("fill_circle",):
                                        arguments = arguments[0]
                                    getattr(paint, verb)(*arguments)
                            result = {"pixels": hashlib.sha256(canvas.pixels()).hexdigest(),
                                      "left": gdiplus.gdiplus_objects() - before}
                        finally:
                            canvas.close()
                        calls = [call if call[0] != "fill_circle" else [call[0]] + call[1] for call in self.GDIP_CALLS]
                        self.add("gdip/%s/%s/%s" % (smoothing, name, keep),
                                 {"surface": "gdip", "size": [160, 120], "smoothing": smoothing, "format": fmt,
                                  "keep_solids": keep, "calls": calls}, result)
        finally:
            gdiplus._gdiplus_release()

    def elevation(self):
        import hashlib
        from codex_auto_resume import brand
        from codex_auto_resume.ui.popup import elevation
        elevation._MASKS.clear()
        masks = [["lift", 640, 900, 32.0, 28.0, None], ["lift", 300, 60, 22.0, 12.0, None], ["lift", 300, 60, 22.0, 12.0, 0.0],
                 ["lift", 80, 44, 22.0, 4.0, None], ["lift", 30, 30, 999.0, 6.0, None], ["lift", 40, 22, 11.0, 0.0, None],
                 ["well", 300, 70, 22.0, 12.0, 4.0, 4.0, None], ["well", 300, 70, 22.0, 12.0, -4.0, -4.0, None],
                 ["well", 300, 70, 22.0, 12.0, 3.0, -2.0, 0.0], ["well", 300, 70, 22.0, 12.0, -3.0, 2.0, 0.0],
                 ["well", 120, 36, 11.0, 6.0, 0.0, 1.0, None], ["well", 60, 20, 7.0, 0.0, 2.0, 2.0, None],
                 ["lift", 688, 700, 32.0, 36.0, None], ["well", 41, 23, 11.5, 3.0, 1.5, 1.5, 0.6]]
        found = []
        for ask in masks:
            if ask[0] == "lift":
                mask = elevation.lift_coverage(ask[1], ask[2], ask[3], ask[4], smoothing=ask[5])
            else:
                mask = elevation.well_coverage(ask[1], ask[2], ask[3], ask[4], ask[5], ask[6], smoothing=ask[7])
            found.append([mask["width"], mask["height"], list(mask["centre"]), mask["extent"],
                          hashlib.sha256(mask["coverage"]).hexdigest()])
        recipes = []
        for recipe in ("card", "control", "inset", "tile"):
            for theme in ("light", "dark"):
                for design in ("soft", "classic", "plain"):
                    recipes.append([[s.dx, s.dy, s.blur, s.token, s.alpha, s.inset]
                                    for s in elevation.recipe_shadows(recipe, theme, design)])
        steps = [0.0, 0.4, 0.5, 1.5, 2.5, -0.5, -1.5, -2.49, 3.7, -0.0]
        result = {"masks": found, "recipes": recipes, "steps": [elevation.shadow_step(value) for value in steps],
                  "grounds": [elevation.tile_ground(theme, design) for theme in ("light", "dark")
                              for design in ("soft", "classic", "plain")]}
        self.add("elevation/all", {"surface": "elevation", "masks": masks, "steps": steps}, result)

    DAY_MOMENTS = [0.0, 16.0, 333.3, 1000.0, 2750.5, 4400.0, 7777.0, 12345.6, 61000.0]
    DAY_WITHIN = [[0.0, 300.0], [40.0, 120.5], [-50.0, 10.0], [250.0, 400.0], [301.0, 500.0]]
    DAY_PATHS = [["M25.5 2l1 3.5 3.5 1-3.5 1-1 3.5-1-3.5-3.5-1 3.5-1z", 1], ["M142 48q4.7 7 9.5 0t9.5 0 9.5 0 9.5 0v-3q0-3-3-3h-32q-3 0-3 3z", 8],
                 ["M60 42q4-6 11-3 5-6 12-1 6-2 8 4z", 8], ["M149 39v12M143 45h12", 8], ["m10 10l5 5H30V2zT4 4", 3]]

    def days(self):
        """A special day's pieces at a few moments (scene_frame, speck_frame with and without `within`), the specks'
        reach, the icon's mark on a grid of the 32 by 32 and path_points over the paths it is fed."""
        from codex_auto_resume import brand
        from codex_auto_resume.brand import days
        points = [[x / 4.0 + 0.125, y / 4.0 + 0.125] for x in range(0, 128, 3) for y in range(0, 128, 3)]
        for look in sorted(brand.DAY_LOOKS):
            def listed(shapes):
                return [[kind, list(numbers), colour, opacity] for kind, numbers, colour, opacity in shapes]
            result = {"scenes": [listed(days.scene_frame(look, ms)) for ms in self.DAY_MOMENTS],
                      "specks": [[listed(days.speck_frame(look, ms))] + [listed(days.speck_frame(look, ms, tuple(within)))
                                                                         for within in self.DAY_WITHIN]
                                 for ms in self.DAY_MOMENTS],
                      "reach": [list(reach) for reach in days.speck_reach(look)],
                      "marks": [days.mark_colour(look, x, y) for x, y in points],
                      "paths": [days.path_points(path, steps) for path, steps in self.DAY_PATHS]}
            self.add("days/" + look, {"surface": "days", "look": look, "moments": self.DAY_MOMENTS, "within": self.DAY_WITHIN,
                                      "points": points, "paths": self.DAY_PATHS}, result)

    PIXEL_LOOKS = [["light", "soft", False], ["dark", "classic", False], ["dark", "plain", False], ["light", "soft", True]]

    def pixels(self):
        """The popup drawn into memory by the reference's own Renderer and fonts (offscreen, as make_screenshots draws
        it, the UI face pinned): whole frames with a hover, a press, a focus, a glide and a face part way, the light
        alone, the day alone and the seventh press's sweep, each step's pixels by digest, and no GDI+ object left."""
        import hashlib
        import make_screenshots
        from codex_auto_resume.ui import popup as tray_popup
        from codex_auto_resume.ui.popup import fonts, gdiplus, light as light_module, renderer as renderer_module, win32
        saved = renderer_module.system_rgb, light_module.system_rgb
        renderer_module.system_rgb = light_module.system_rgb = lambda name: tuple(self.SYSTEM[name])
        try:
            with make_screenshots.pinned_face():
                pinned = fonts._ui_face()
                for locale in ("en", "ko", "ar"):
                    views = popup_views(locale)
                    views += [("day-" + look, dict(views[0][1], scene=look)) for look in ("new_year", "christmas", "seollal", "chuseok")]
                    for name, vm in views:
                        scales = (1.25, 2.0) if name in ("picture", "scene") else (1.5,)
                        looks = self.LOOKS if name == "picture" else self.PIXEL_LOOKS
                        for scale in scales:
                            for index, (theme, design, contrast) in enumerate(looks):
                                lone = index % 2 == 0
                                self._pixels(tray_popup, gdiplus, fonts, win32, hashlib, name, vm, locale, scale, theme, design,
                                             contrast, lone, pinned)
        finally:
            renderer_module.system_rgb, light_module.system_rgb = saved

    def _pixels(self, tray_popup, gdiplus, fonts, win32, hashlib, name, vm, locale, scale, theme, design, contrast, lone, pinned):
        before = gdiplus.gdiplus_objects()
        renderer = tray_popup.Renderer()
        steps, digests = [], []
        try:
            renderer.theme, renderer.design, renderer.contrast, renderer.lone = theme, design, contrast, lone
            plan = renderer.layout(vm, scale, locale)
            items = plan["items"]
            buttons = [item["target"] for item in items if item["kind"] == "button"]
            focusable = [item["target"] for item in items if item["kind"] == "focusable"]
            switches = [item["target"] for item in items if item["kind"] == "switch"]
            state = vm["light"]

            def frame(moment):
                return tray_popup.halo(state, moment, moment, design=design)

            def record(step):
                win32._dll("gdi32").GdiFlush()
                digests.append([hashlib.sha256(renderer.canvas.pixels()).hexdigest(),
                                list(renderer.halo_rows) if renderer.halo_rows is not None else None])
                steps.append(step)

            renderer.draw(vm, plan, frame=frame(0))
            record({"do": "draw", "frame": frame(0), "hover": None, "pressed": None, "focus": None, "glides": [], "faces": [],
                    "scene_ms": 0.0})
            renderer.draw_halo(plan, frame(1700))
            record({"do": "halo", "frame": frame(1700)})
            if lone:
                still_width, still_height, still = tray_popup.card_still(renderer, plan)
                layers = tray_popup.layers.CardLayers(None)
                try:
                    layers.shade(renderer, plan)
                    shade = hashlib.sha256(layers.picture.pixels()).hexdigest() if layers.shadows else None
                    digests.append([still_width, still_height, hashlib.sha256(still).hexdigest(), layers.margin, shade])
                finally:
                    layers.close()
                steps.append({"do": "still"})
            if any(item["kind"] == "scene" for item in items):
                renderer.draw_scene(plan, 1234.5)
                record({"do": "scene", "ms": 1234.5})
            hover = buttons[0] if buttons else None
            focus = focusable[-1] if focusable else None
            glides = {switches[0]: 0.4} if switches else {}
            faces = {buttons[-1]: ((renderer._rgb("accent"), renderer._rgb("line")), 0.3)} if len(buttons) > 1 else {}
            renderer.draw(vm, plan, frame=frame(2600), hover=hover, focus=focus, glides=glides, scene_ms=500.0, faces=faces)
            record({"do": "draw", "frame": frame(2600), "hover": hover, "pressed": None, "focus": focus,
                    "glides": [[target, amount] for target, amount in glides.items()],
                    "faces": [[target, fill, edge, amount] for target, ((fill, edge), amount) in faces.items()], "scene_ms": 500.0})
            pressed = buttons[0] if buttons else None
            renderer.draw(vm, plan, frame=None, pressed=pressed)
            record({"do": "draw", "frame": None, "hover": None, "pressed": pressed, "focus": None, "glides": [], "faces": [],
                    "scene_ms": 0.0})
            renderer.sweep_ms = 900.0
            renderer.draw_halo(plan, frame(300))
            renderer.sweep_ms = None
            record({"do": "sweep", "ms": 900.0, "frame": frame(300)})
        finally:
            renderer.close()
        self.add("pixels/%s/%s/%r/%s-%s-%s-%s" % (name, locale, scale, theme, design, contrast, lone),
                 {"surface": "pixels", "vm": plain(vm), "scale": scale, "locale": locale, "letters": fonts._letters(locale),
                  "look": [theme, design, contrast], "lone": lone, "pinned": pinned, "system": self.SYSTEM, "steps": plain(steps)},
                 {"plan": plan, "pixels": digests, "left": gdiplus.gdiplus_objects() - before})

    def drawn(self):
        """The icon's menu and its card drawn into memory by the reference's MenuRenderer and TipRenderer (its own fonts,
        the face pinned) and by the C#: each step's pixels by digest, the plan, no GDI+ object left."""
        import hashlib
        import make_screenshots
        from codex_auto_resume.ui import popup as tray_popup
        from codex_auto_resume.ui.popup import fonts, gdiplus, light as light_module, menuwindow, renderer as renderer_module
        from codex_auto_resume.ui.tray import tipcard
        saved = renderer_module.system_rgb, light_module.system_rgb
        renderer_module.system_rgb = light_module.system_rgb = lambda name: tuple(self.SYSTEM[name])
        menus = [case for case in self.cases if case["id"].startswith("menu/") and case["scale"] in (1.25, 2.0)
                 and case["locale"] in ("en", "ko", "ar")]
        tips = [case for case in self.cases if case["id"].startswith("tip/") and case["scale"] in (1.25, 2.0)
                and case["locale"] in ("en", "ko", "ar")]
        try:
            with make_screenshots.pinned_face():
                pinned = fonts._ui_face()
                for case in menus:
                    expected = self.expected[case["id"]]
                    entries = expected.get("numbered", case["entries"])
                    usable = [index for index, entry in enumerate(entries) if entry and entry.get("enabled")]
                    for theme, design, contrast in self.PIXEL_LOOKS:
                        before = gdiplus.gdiplus_objects()
                        renderer = menuwindow.MenuRenderer()
                        digests = []
                        chosen = [None, usable[0], usable[-1], len(entries) + 3]
                        try:
                            renderer.theme, renderer.design, renderer.contrast = theme, design, contrast
                            plan = renderer.menu_layout(entries, case["scale"], case["locale"], case["max_width"])
                            for selected in chosen:
                                digests.append(hashlib.sha256(renderer.draw_menu(plan, selected).pixels()).hexdigest())
                        finally:
                            renderer.close()
                        self.add("drawn/%s/%s-%s-%s" % (case["id"], theme, design, contrast),
                                 {"surface": "drawn", "what": "menu", "entries": plain(entries), "scale": case["scale"],
                                  "locale": case["locale"], "max_width": case["max_width"], "selected": chosen,
                                  "letters": fonts._letters(case["locale"]), "look": [theme, design, contrast],
                                  "pinned": pinned, "system": self.SYSTEM},
                                 {"plan": plan, "pixels": digests, "left": gdiplus.gdiplus_objects() - before})
                for case in tips:
                    for theme, design, contrast in self.PIXEL_LOOKS:
                        before = gdiplus.gdiplus_objects()
                        renderer = tipcard.TipRenderer()
                        digests = []
                        day = tipcard.tip_day(case["day"], contrast, design)
                        frames = [tray_popup.halo(case["light"], moment, moment, design=design) for moment in (0, 1700, 2900)]
                        try:
                            renderer.theme, renderer.design, renderer.contrast = theme, design, contrast
                            plan = renderer.tip_layout(case["parts"], case["light"], case["scale"], case["locale"], day)
                            digests.append(hashlib.sha256(renderer.draw_tip(plan, frames[0]).pixels()).hexdigest())
                            for frame in frames[1:]:
                                digests.append(hashlib.sha256(renderer.draw_tip_light(plan, frame).pixels()).hexdigest())
                        finally:
                            renderer.close()
                        self.add("drawn/%s/%s-%s-%s" % (case["id"], theme, design, contrast),
                                 {"surface": "drawn", "what": "tip", "parts": case["parts"], "light": case["light"],
                                  "scale": case["scale"], "locale": case["locale"], "day": case["day"], "frames": plain(frames),
                                  "letters": fonts._letters(case["locale"]), "look": [theme, design, contrast],
                                  "pinned": pinned, "system": self.SYSTEM},
                                 {"plan": plan, "pixels": digests, "left": gdiplus.gdiplus_objects() - before})
        finally:
            renderer_module.system_rgb, light_module.system_rgb = saved

    def cards(self):
        """The notification card offscreen (no windows), as make_screenshots' settled card is made: the reference's Card
        and the C#'s NoticeCard, its entrance part way (the body scaled, a shallower shadow), settled, a breath of its
        light, a hover drawn again and a breath by the stack's rule - each layer's pixels by digest - and the corner's
        coverage at a few radii; no GDI+ object left."""
        import hashlib
        import make_screenshots
        from codex_auto_resume import notice_card
        from codex_auto_resume.ui.card import card as card_module
        from codex_auto_resume.ui.popup import fonts, gdiplus, light as light_module, renderer as renderer_module

        def digest(data):
            return hashlib.sha256(bytes(data)).hexdigest()

        saved = renderer_module.system_rgb, light_module.system_rgb
        renderer_module.system_rgb = light_module.system_rgb = lambda name: tuple(self.SYSTEM[name])
        corners = []
        for radius in (8.0, 12.0, 16.5, 24.0, 32.0):
            for smoothing in (0.6, 0.0, 0.3):
                corners.append([radius, smoothing, digest(b"".join(notice_card.corner_coverage(radius, smoothing)))])
        self.add("cards/corners", {"surface": "cards", "corners": [[r, s] for r, s, _ in corners]}, [c[2] for c in corners])
        try:
            with make_screenshots.pinned_face():
                pinned = fonts._ui_face()
                for locale in ("en", "ko", "ar"):
                    notice = make_screenshots.card_notice(locale)
                    vm = notice_card.view(notice)
                    for dpi, work, text, day in ((144, (0, 0, 0, 0), None, None), (192, (0, 0, 2560, 1400), 1.5, None),
                                                 (144, (0, 0, 1920, 1040), None, "christmas")):
                        for theme, design, contrast in self.PIXEL_LOOKS:
                            drawn = {"theme": theme, "design": design, "contrast": contrast, "reduced": False, "text": text, "day": day}
                            where = {"dpi": dpi, "work": work, "monitor": (0, 0, 0, 0), "anchor": None}
                            before = gdiplus.gdiplus_objects()
                            card = card_module.Card(make_screenshots._NoStack(), notice, now_ms=0, where=where, drawn=drawn,
                                                    windows=False)
                            found = []
                            try:
                                for moment in (100, notice_card.ENTRANCE_MS):
                                    painted = card.paint(moment)
                                    found.append([digest(card.body.pixels()), digest(card.shadow.pixels()), list(painted["key"]),
                                                  painted["margin"]])
                                card._draw_light(card.born + 1700)
                                found.append([digest(card.image._pixels), digest(card.body.pixels())])
                                hover = card.plan["targets"][0][0] if card.plan["targets"] else None
                                card.hover = hover
                                card.redraw()
                                card.paint(notice_card.ENTRANCE_MS + 50)
                                found.append([digest(card.body.pixels()), card.breathe(2900), digest(card.body.pixels())])
                            finally:
                                card.close()
                            self.add("cards/%s/%d-%r-%s/%s-%s-%s" % (locale, dpi, text, day, theme, design, contrast),
                                     {"surface": "cards", "vm": plain(vm), "title": notice.title,
                                      "stays": getattr(notice, "stays", False) is True, "hold": float(notice_card.HOLD_MS),
                                      "dpi": float(dpi), "work": list(work), "drawn": plain(drawn), "hover": plain(hover),
                                      "letters": fonts._letters(vm["locale"]), "pinned": pinned, "system": self.SYSTEM,
                                      "entrance": float(notice_card.ENTRANCE_MS)},
                                     {"steps": found, "left": gdiplus.gdiplus_objects() - before})
        finally:
            renderer_module.system_rgb, light_module.system_rgb = saved

    def bidi(self):
        """l10n.first_strong over a code point of every 173 (no surrogate: the job is UTF-8), each after digits and
        spaces, and a few texts of the plans' own."""
        from codex_auto_resume import l10n
        texts = ["", "123 - 4", "abc", "مرحبا", "12 א", " (𝐀)", "𐠀x", "‏‎a"]
        texts += ["1 " + chr(point) for point in range(0, 0x110000, 173) if not 0xD800 <= point <= 0xDFFF]
        self.add("bidi/all", {"surface": "bidi", "texts": texts}, [l10n.first_strong(text) for text in texts])

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
        job.card()
        job.icon()
        job.paint()
        job.shape()
        job.gdip()
        job.elevation()
        job.days()
        job.bidi()
        job.pixels()
        job.drawn()
        job.cards()
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

    def test_the_card_is_laid_out_as_the_reference_lays_it_out(self):
        self.compare("card/")

    def test_the_cards_stack_shadow_and_text_size_are_the_references(self):
        self.compare("cardroom/")

    def test_a_cards_life_is_the_references_step_for_step(self):
        self.compare("cardlife/")

    def test_the_icons_frames_are_the_references_position_level_and_pixel(self):
        self.compare("icon/")

    def test_every_plan_is_painted_with_the_references_colours_and_corners_in_every_look(self):
        self.compare("paint/")

    def test_the_corner_outline_and_its_tables_are_the_references(self):
        self.compare("shape/")

    def test_the_shadows_masks_and_recipes_are_the_references(self):
        self.compare("elevation/")

    def test_a_special_days_pieces_and_the_icons_mark_are_the_references_frame_for_frame(self):
        self.compare("days/")

    def test_the_popup_is_drawn_into_memory_as_the_reference_draws_it_byte_for_byte(self):
        self.compare("pixels/")
        for case_id, found in self.found.items():
            if case_id.startswith("pixels/") and "plan" in found:
                self.assertEqual(found["plan"]["left"], 0, case_id)

    def test_the_menu_and_the_icons_card_are_drawn_as_the_reference_draws_them_byte_for_byte(self):
        self.compare("drawn/")
        for case_id, found in self.found.items():
            if case_id.startswith("drawn/") and "plan" in found:
                self.assertEqual(found["plan"]["left"], 0, case_id)

    def test_the_notification_card_is_cut_shadowed_and_breathes_as_the_reference_does_it_byte_for_byte(self):
        self.compare("cards/")
        for case_id, found in self.found.items():
            if case_id.startswith("cards/") and isinstance(found.get("plan"), dict):
                self.assertEqual(found["plan"]["left"], 0, case_id)

    def test_the_first_strong_direction_is_the_references_over_the_whole_code_space(self):
        self.compare("bidi/")

    def test_the_painters_gdiplus_calls_make_the_references_pixels_and_leak_nothing(self):
        self.compare("gdip/")
        for case_id, case in self.found.items():
            if case_id.startswith("gdip/"):
                self.assertEqual(case["plan"]["left"], 0, case_id)


class SurfaceSourceTests(unittest.TestCase):
    def test_the_hosts_direction_table_is_the_one_python_writes(self):
        import unicodedata
        import surfacebidi
        written = (ROOT / "gui" / "SurfaceBidi.cs").read_text(encoding="utf-8")
        if unicodedata.unidata_version not in written:
            self.skipTest("this Python's Unicode (%s) is not the table's" % unicodedata.unidata_version)
        self.assertEqual(written, surfacebidi.source(), "run `python -X utf8 tests/surfacebidi.py`")

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
