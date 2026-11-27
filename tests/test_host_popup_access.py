"""The popup for a screen reader and at Windows' text size, on the C# host (S6.4d3, P6-DESIGN 3.4 "window").

Twins of tests/test_popup_access.py:

* AccessibleItemsTests: the originals' bodies through `super()`, with the screen reader's rules the host's - `accessible_items`,
  `access.pick`, `access.changes`, `access.switch_name` and the keyboard's `focus_order` answered by gui/SurfaceAccess.cs and
  gui/PopupPlace.cs (HostProbe.cs `popup_access`), over the same view and plan the test made.
* TextSizeTests' two UI tests: the card's fit is CardPlan.Fitting (`card_fitting`); "the one place a test replaces" is the
  host popup's AskTextScale, which a new PopupWindow points at SurfaceTheme.TextScale and ReadLook takes whatever it answers.
* ScreenReaderTests: the host's PopupWindow given the core's popup (the reference's model over the same rows), its window a
  message-only window of the probe's own class whose messages are the popup's, SurfaceAccess attached as the live host
  attaches it, shown for the keyboard; its client object fetched by AccessibleObjectFromWindow and asked through its table at
  the slots the originals ask the reference's at, and read from another process through COM (`popup_reader`). The same
  assertions over what it answers.
* PopupTextSizeTests: the host's PopupWindow at a text size on a screen (`popup_fit`): its Rebuild's scale and size, Fit
  worked out once an opening (its renderer's fonts made again only where another scale was laid out), ReadLook.

Not here, and why: TextSizeTests' `test_everything_sits_inside_the_card_at_every_text_size_in_every_language` and
`test_the_notification_card_is_whole_at_every_text_size` lay out plans (popup.layout, notice_card.layout): the drawing's
(seat S6.4f's plan proxy). The other three of TextSizeTests read only win/textsize (unaffected).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
import unittest.mock

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "tests"), str(ROOT / "tests" / "rustdiff")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import hostpopup  # noqa: E402
import surfacehost  # noqa: E402
import test_popup_access as original  # noqa: E402  (a module name: its classes are not collected here)
from codex_auto_resume import brand  # noqa: E402
from codex_auto_resume.ui import popup  # noqa: E402
from codex_auto_resume.ui.popup import access  # noqa: E402
from codex_auto_resume.win import textsize  # noqa: E402
from test_tray_popup import EN, FakeControl  # noqa: E402

ON_HOST = unittest.skipUnless(os.name == "nt" and surfacehost.CSC.is_file(), "the host's surfaces need the in-box C# compiler")


def _tuple(value):
    return tuple(_tuple(part) for part in value) if isinstance(value, list) else value


def _child(item):
    """A child as the host answered it, in the reference's container kinds (rectangles and targets tuples)."""
    item = dict(item)
    for key in ("rect", "target"):
        if isinstance(item.get(key), list):
            item[key] = _tuple(item[key])
    return item


def _plan_json(plan):
    if plan is None:
        return None
    return {"items": [dict(item) for item in plan.get("items", ())],
            "targets": [[list(target), list(rect)] for target, rect in plan.get("targets", ())],
            "rows": [[key, list(rect)] for key, rect in plan.get("rows") or ()]}


def _ask(op, **fields):
    return surfacehost.SERVE.ask("popup_access", op=op, **fields)


def host_accessible_items(vm, plan, focus=None, hover=None, strings=None):
    return [_child(item) for item in _ask("items", vm=vm, plan=_plan_json(plan), focus=list(focus) if focus else None,
                                          hover=list(hover) if hover else None, strings=strings)]


def host_pick(items, x, y):
    return int(_ask("pick", items=items, x=int(x), y=int(y)))


def host_changes(before, after):
    return [tuple(int(part) for part in event) for event in _ask("changes", before=before, after=after)]


def host_switch_name(task):
    return _ask("switch_name", task=task)


def host_focus_order(targets):
    return [_tuple(target) for target in _ask("focus_order", plan={"targets": [[list(t), list(r)] for t, r in targets]})]


def core_popup(rows, strings=EN):
    """The core's popup over `rows` as car-watcher's surface field sends it: the reference's model after one read."""
    control = FakeControl(rows)
    model = hostpopup.CoreModel(strings)
    model.apply_outcome(("read",), popup.perform(("read",), control), time.time())
    vm = model.view(time.time())
    return {"view": vm, "menus": [[task["interruption_id"], model.menu_for(task["interruption_id"])] for task in vm["tasks"]],
            "read": True, "attention": False}


@ON_HOST
class AccessibleItemsOnHostTests(original.AccessibleItemsTests):
    def setUp(self):
        super().setUp()
        for owner, name, value in ((popup, "accessible_items", host_accessible_items), (access, "pick", host_pick),
                                   (access, "changes", host_changes), (access, "switch_name", host_switch_name),
                                   (popup, "focus_order", host_focus_order)):
            patcher = unittest.mock.patch.object(owner, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_the_hosts_event_numbers_are_the_references(self):
        self.assertEqual(_ask("events"), {"focus": access.EVENT_FOCUS, "reorder": access.EVENT_REORDER,
                                          "statechange": access.EVENT_STATECHANGE, "namechange": access.EVENT_NAMECHANGE})


@ON_HOST
class TextSizeOnHostTests(original.TextSizeTests):
    def test_the_popup_asks_windows_through_the_one_place_a_test_replaces(self):
        found = surfacehost.SERVE.ask("popup_fit", strings=EN, core=core_popup(original.rows()), text=1.0,
                                      work=[0, 0, 3840, 2100], now=time.time(), steps=[["asks"], ["read_look", 1.75]])
        self.assertEqual(found["steps"][0]["asks"], "SurfaceTheme.TextScale")
        self.assertEqual(found["steps"][1]["text"], 1.75)

    def test_the_card_is_fitted_to_half_the_work_area(self):
        class Card:
            @staticmethod
            def fitting(where, settings):
                found = surfacehost.SERVE.ask("card_fitting", dpi=where["dpi"], work=where.get("work"), text=settings.get("text"))
                return found["fit"]

        Card.ROOM = tuple(surfacehost.SERVE.ask("card_fitting", dpi=96, work=None, text=None)["room"])
        self.assertEqual(Card.ROOM, tuple(original.popup_card().Card.ROOM))
        stand_in = type("CardModule", (), {"Card": Card})
        with unittest.mock.patch.object(original, "popup_card", lambda: stand_in):
            super().test_the_card_is_fitted_to_half_the_work_area()

    # win/textsize alone (unaffected), and the drawing's two (seat S6.4f): see the module's head
    test_the_percentage_is_a_factor_from_one_to_two_and_a_quarter = None
    test_the_setting_is_read_where_windows_keeps_it = None
    test_a_size_is_fitted_to_the_room_and_never_below_one = None
    test_everything_sits_inside_the_card_at_every_text_size_in_every_language = None
    test_the_notification_card_is_whole_at_every_text_size = None


@ON_HOST
@unittest.skipUnless(os.name == "nt", "Windows' accessibility")
class ScreenReaderOnHostTests(original.ScreenReaderTests):
    @classmethod
    def setUpClass(cls):
        pass

    def setUp(self):
        self.core = core_popup(original.rows())

    def tearDown(self):
        pass

    def read(self, steps=()):
        return surfacehost.SERVE.ask("popup_reader", strings=EN, core=self.core, origin=[-32000, -32000], steps=list(steps))

    def expected_of(self, found):
        return [_child(item) for item in found["items"]]

    def test_every_row_and_button_is_there_by_name_role_and_state(self):
        found = self.read()
        items, children = self.expected_of(found), found["children"]
        self.assertEqual(found["count"], [0, len(items)])
        self.assertEqual(children[0]["name"], [0, EN["tray.title"]])
        self.assertEqual(children[0]["role"], [0, access.VT_I4, original.ROLE_NUMBERS["dialog"]])
        for index, item in enumerate(items, 1):
            with self.subTest(item["name"]):
                self.assertEqual(children[index]["name"], [0, item["name"]])
                self.assertEqual(children[index]["role"], [0, access.VT_I4, original.ROLE_NUMBERS[item["role"]]])
                state = 0
                for name in item["states"]:
                    state |= access.A11Y_STATES[name]
                self.assertEqual(children[index]["state"], [0, access.VT_I4, state])
                self.assertEqual(children[index]["action"][1], item["action"])
        self.assertEqual(children[len(items) + 1]["role"][0], access.E_INVALIDARG)

    def test_each_child_is_where_it_is_drawn_and_a_hit_finds_it(self):
        found = self.read()
        dx, dy = found["offset"]
        x0, y0 = found["corner"]
        for index, item in enumerate(self.expected_of(found), 1):
            child = found["children"][index]
            corner = (x0 + item["rect"][0] - dx, y0 + item["rect"][1] - dy)
            with self.subTest(item["name"]):
                self.assertEqual(child["box"], [0, corner[0], corner[1], item["rect"][2] - item["rect"][0],
                                                item["rect"][3] - item["rect"][1]])
                if item["role"] in ("switch", "button"):
                    self.assertEqual(child["hit"], [0, access.VT_I4, index])

    def test_the_keyboards_place_is_the_focused_child_and_a_move_is_announced(self):
        found = self.read([["tab"]])
        items = self.expected_of(found)
        focused = next(index for index, item in enumerate(items, 1) if "focused" in item["states"])
        self.assertEqual(found["focus"], [0, access.VT_I4, focused])
        told = [[tuple(event) for event in events] for events in found["steps"][0]["told"]]
        self.assertEqual(told, [[(access.EVENT_FOCUS, focused + 2)]], "the next switch, a row further on")

    def test_pressing_a_switch_is_the_click_on_it(self):
        items = self.expected_of(self.read())
        index = next(index for index, item in enumerate(items, 1) if item["role"] == "switch")
        text = next(index for index, item in enumerate(items, 1) if item["target"] is None)
        found = self.read([["press", index], ["press", text]])
        task = self.core["view"]["tasks"][0]
        self.assertEqual(found["steps"][0]["result"], 0)
        calls = [(fields["call"],) + tuple(fields["args"]) for name, fields in found["steps"][0]["posted"] if name == "popup"]
        self.assertIn(("set_interruption_recovery", task["interruption_id"], task["thread_id"], not task["checked"]), calls)
        self.assertEqual(found["steps"][1]["result"], access.DISP_E_MEMBERNOTFOUND)

    def test_anything_else_asked_of_the_window_is_windows_own_answer(self):
        self.assertEqual(self.read()["window_role"], [0, access.VT_I4, 0x09])      # ROLE_SYSTEM_WINDOW

    @unittest.skipUnless(original.POWERSHELL.is_file(), "needs PowerShell")
    def test_another_process_reads_it_as_narrator_does(self):
        folder = tempfile.mkdtemp()
        script = Path(folder) / "reader.ps1"
        script.write_text(READER, encoding="utf-8")
        try:
            found = self.read([["reader", str(original.POWERSHELL), str(script)]])
        finally:
            script.unlink()
            os.rmdir(folder)
        ran = found["steps"][0]
        self.assertEqual(ran["code"], 0, ran["err"][-2000:])
        read = json.loads(ran["out"])
        items = self.expected_of(found)
        self.assertEqual(read[0][:2], [EN["tray.title"], original.ROLE_NUMBERS["dialog"]])
        self.assertEqual([entry[:2] for entry in read[1:]],
                         [[item["name"], original.ROLE_NUMBERS[item["role"]]] for item in items])
        for entry, item in zip(read[1:], items):
            with self.subTest(item["name"]):
                self.assertEqual(bool(entry[2] & access.A11Y_STATES["checked"]), "checked" in item["states"])
                self.assertEqual(bool(entry[2] & access.A11Y_STATES["focused"]), "focused" in item["states"])


# The original's reader, as it hands it to Windows PowerShell (tests/test_popup_access.py
# ScreenReaderTests.test_another_process_reads_it_as_narrator_does).
READER = r'''
$ErrorActionPreference = 'Stop'
Add-Type -ReferencedAssemblies Accessibility -TypeDefinition @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public static class MsaaReader {
    [DllImport("oleacc.dll")]
    private static extern int AccessibleObjectFromWindow(IntPtr hwnd, uint id, ref Guid iid,
        [MarshalAs(UnmanagedType.Interface)] out object found);
    private static string Quote(object value) {
        if (value == null) return "null";
        var text = new StringBuilder("\"");
        foreach (char c in value.ToString()) {
            if (c == '"' || c == '\\') text.Append('\\').Append(c);
            else if (c < ' ' || c > '~') text.AppendFormat("\\u{0:x4}", (int)c);
            else text.Append(c);
        }
        return text.Append('"').ToString();
    }
    public static string Read(long hwnd) {
        Guid iid = typeof(Accessibility.IAccessible).GUID;
        object found;
        int hr = AccessibleObjectFromWindow(new IntPtr(hwnd), 0xFFFFFFFC, ref iid, out found);
        if (hr != 0) throw new COMException("AccessibleObjectFromWindow", hr);
        var client = (Accessibility.IAccessible)found;
        var parts = new List<string>();
        for (int i = 0; i <= client.accChildCount; i++)
            parts.Add("[" + Quote(client.get_accName(i)) + "," + Convert.ToInt32(client.get_accRole(i)) + "," +
                      Convert.ToInt32(client.get_accState(i)) + "]");
        return "[" + string.Join(",", parts.ToArray()) + "]";
    }
}
"@
[Console]::Out.Write([MsaaReader]::Read([long]$env:CAR_HWND))
'''


@ON_HOST
@unittest.skipUnless(os.name == "nt", "Windows' screen")
class PopupTextSizeOnHostTests(original.PopupTextSizeTests):
    def fit(self, text, work, steps):
        return surfacehost.SERVE.ask("popup_fit", strings=EN, core=core_popup(original.rows()), text=text, work=list(work),
                                     now=time.time(), steps=steps)

    def test_the_popup_is_drawn_that_much_larger_as_far_as_the_screen_holds_it(self):
        for text, work, whole in ((1.0, (0, 0, 3840, 2100), True), (2.25, (0, 0, 3840, 2100), True),
                                  (2.25, (0, 0, 1366, 700), False)):
            found = self.fit(text, work, [["usual"], ["rebuild"]])
            self.assertEqual(found["spacing_m"], brand.SPACING["m"])
            usual = tuple(found["steps"][0]["size"])
            plan = found["steps"][1]
            with self.subTest(text=text, work=work):
                width, height = plan["size"]
                gap = 2 * brand.SPACING["m"]
                self.assertAlmostEqual(plan["scale"], textsize.fitting(text, usual, (work[2] - gap, work[3] - gap)))
                if whole:
                    self.assertAlmostEqual(plan["scale"], text, msg="a screen that holds it gets it whole")
                else:
                    self.assertTrue(1.0 < plan["scale"] < text, plan["scale"])
                self.assertLessEqual(height, work[3] - work[1])
                self.assertLessEqual(width, work[2] - work[0])

    def test_the_fit_is_worked_out_once_an_opening_and_not_at_every_tick(self):
        # The reference counts its renderer's layouts ([1.0, 2.25, 2.25], then [1.0, 2.25]); the host's renderer makes
        # its fonts again for every layout at another scale than the last, so a usual size measured again shows there.
        first, second, hidden, third = self.fit(2.25, (0, 0, 3840, 2100),
                                                [["rebuild"], ["rebuild"], ["hide"], ["rebuild"]])["steps"]
        self.assertEqual((first["fit"], first["scale"], first["fonts_scale"]), (2.25, 2.25, 2.25))
        self.assertEqual((second["scale"], second["fonts_made"]), (2.25, False), "the usual size measured once")
        self.assertIsNone(hidden["fit"])
        self.assertEqual((third["scale"], third["fonts_made"], third["fonts_scale"]), (2.25, True, 2.25),
                         "and again at the next opening")

    def test_opening_asks_windows_for_its_text_size(self):
        found = self.fit(1.0, (0, 0, 3840, 2100), [["read_look", 1.5]])
        self.assertEqual(found["steps"][0]["text"], 1.5)


if __name__ == "__main__":
    unittest.main()
