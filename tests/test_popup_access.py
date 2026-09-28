"""v0.6.11: the notification-area popup for a screen reader, and at Windows' text size.

The popup draws itself, so Windows alone can tell Narrator nothing of what is in it. Asked for its
client object (WM_GETOBJECT, OBJID_CLIENT) it now hands out an IAccessible of its own
(`ui/popup/access.py`): the three counts, each task's row and its switch, the notes under them and
the two buttons - each by name and role, with its state, where it is drawn, and what pressing it
does. What each child is, is a pure function of what is on screen, tested here in every language;
the COM object is read the way Narrator reads it - through `AccessibleObjectFromWindow`, in this
process and from another one - on Windows.

And Windows' text size ("Make text bigger", `win/textsize.py`) draws the whole popup, and the whole
notification card, that much larger - their words and what holds them alike, which is what keeps
any of it from being cut - as far as the screen holds them.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
import unittest.mock

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from codex_auto_resume import brand, interface, l10n, notice_card  # noqa: E402
from codex_auto_resume.ui import popup  # noqa: E402
from codex_auto_resume.ui.popup import access  # noqa: E402
from codex_auto_resume.win import textsize  # noqa: E402
import test_tray_popup as base  # noqa: E402
from test_tray_popup import EN, NOW, OTHER_THREAD, STATUS, measure, row  # noqa: E402

POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0"
              / "powershell.exe")
ROLE_NUMBERS = {"dialog": 0x12, "text": 0x29, "row": 0x22, "switch": 0x2C, "button": 0x2B}


def rows():
    return [row("a", "waiting_reset", "usage_limit", eligible=NOW + 3600, reset=NOW + 3600, name="Ship the release"),
            row("b", eligible=NOW + 42, thread=OTHER_THREAD, name="Fix flaky CI"),
            row("c", eligible=NOW + 90, enabled=False, name="Docs"),
            row("d", eligible=NOW + 95, name="One more")]


def planned(strings=EN, scale=1.0, **extra):
    vm = popup.view_model(rows(), STATUS, strings, NOW, **extra)
    return vm, popup.layout(vm, scale, measure)


class AccessibleItemsTests(unittest.TestCase):
    """What each child is, from what is drawn."""

    def test_every_child_is_named_in_every_language(self):
        for locale in l10n.LOCALES:
            strings = interface.STRINGS[locale]
            vm, plan = planned(strings, notice=strings["popup.stale"])
            with self.subTest(locale=locale):
                items = popup.accessible_items(vm, plan, strings=strings)
                self.assertTrue(items)
                for item in items:
                    self.assertTrue(item["name"].strip(), item)
                    if item["target"] is not None:
                        self.assertTrue(item["action"].strip(), item)
                        self.assertIn(item["action"], {strings["popup.a11y_press"], strings["popup.a11y_on"],
                                                       strings["popup.a11y_off"]})

    def test_the_children_are_what_is_drawn_in_the_order_it_is_drawn(self):
        vm, plan = planned(notice=EN["popup.stale"])
        items = popup.accessible_items(vm, plan, strings=EN)
        roles = [item["role"] for item in items]
        tasks = vm["tasks"]
        self.assertEqual(roles, ["text"] * 3 + ["row", "switch"] * len(tasks) + ["text", "text", "button", "button"])
        self.assertEqual([item["name"] for item in items[:3]], [label for label, _ in vm["counts"]])
        self.assertEqual([item["value"] for item in items[:3]], [value for _, value in vm["counts"]])
        for index, task in enumerate(tasks):
            row_item, switch = items[3 + 2 * index], items[4 + 2 * index]
            with self.subTest(task["name"]):
                self.assertEqual((row_item["name"], row_item["value"], row_item["description"]),
                                 (task["name"], task["status"], task["reason"]))
                self.assertEqual((switch["name"], switch["description"]), (task["check_label"] + ": " + task["name"], None))
        self.assertEqual([item["name"] for item in items[-4:-2]], [vm["more"], EN["popup.stale"]])
        self.assertEqual([item["name"] for item in items[-2:]], [vm["toggle_text"], vm["dashboard_text"]])

    def test_each_switch_is_named_with_its_task_in_every_language(self):
        """Tabbing through the popup says whose switch it is, as the panel's aria-label does ("Auto-resume: Docs"),
        rather than the same word once for every task."""
        for locale in l10n.LOCALES:
            strings = interface.STRINGS[locale]
            vm, plan = planned(strings)
            switches = [item for item in popup.accessible_items(vm, plan, strings=strings) if item["role"] == "switch"]
            with self.subTest(locale=locale):
                self.assertEqual(len(switches), len(vm["tasks"]))
                self.assertEqual(len({item["name"] for item in switches}), len(switches), "one name each")
                for item, task in zip(switches, vm["tasks"]):
                    self.assertEqual(item["name"], strings["pending.col_resume"] + ": " + task["name"])
        self.assertEqual(access.switch_name({"check_label": "Auto-resume", "name": ""}), "Auto-resume")

    def test_each_switch_and_button_is_where_it_is_drawn_and_in_the_keyboards_order(self):
        vm, plan = planned()
        items = popup.accessible_items(vm, plan, strings=EN)
        pressed = [item for item in items if item["target"] is not None]
        self.assertEqual([item["target"] for item in pressed], popup.focus_order(plan["targets"]))
        targets = dict(plan["targets"])
        for item in pressed:
            with self.subTest(item["target"]):
                self.assertEqual(item["rect"], targets[item["target"]])
        rows_drawn = dict(plan["rows"])
        for item, task in zip([item for item in items if item["role"] == "row"], vm["tasks"]):
            self.assertEqual(item["rect"], rows_drawn[task["interruption_id"]])
        for item in items:
            self.assertIsNotNone(item["rect"], item)

    def test_a_childs_state_is_what_is_drawn(self):
        vm, plan = planned()
        vm["tasks"][1]["busy"] = True
        vm["toggle_busy"] = True
        focus = ("check", vm["tasks"][0]["interruption_id"])
        items = popup.accessible_items(vm, plan, focus=focus, hover=("dashboard",), strings=EN)
        switches = [item for item in items if item["role"] == "switch"]
        self.assertEqual([("checked" in item["states"]) for item in switches], [task["checked"] for task in vm["tasks"]])
        self.assertIn("unavailable", switches[1]["states"])
        self.assertIn("focused", switches[0]["states"])
        self.assertEqual(sum("focused" in item["states"] for item in items), 1)
        buttons = [item for item in items if item["role"] == "button"]
        self.assertIn("unavailable", buttons[0]["states"])
        self.assertIn("hot", buttons[1]["states"])
        for item in items:
            self.assertEqual("focusable" in item["states"], item["target"] is not None)
            self.assertEqual("readonly" in item["states"], item["target"] is None)
        self.assertEqual([item["action"] for item in switches],
                         [EN["popup.a11y_off"] if task["checked"] else EN["popup.a11y_on"] for task in vm["tasks"]])

    def test_nothing_on_screen_is_no_child(self):
        self.assertEqual(popup.accessible_items(None, None), [])
        vm, plan = planned()
        self.assertEqual(popup.accessible_items(vm, None), [])

    def test_a_hit_lands_on_the_switch_before_the_row_it_is_in(self):
        vm, plan = planned()
        items = popup.accessible_items(vm, plan, strings=EN)
        for index, item in enumerate(items):
            left, top, right, bottom = item["rect"]
            found = access.pick(items, (left + right) // 2, (top + bottom) // 2)
            with self.subTest(item["name"]):
                if item["role"] == "row":
                    # The row's middle may be its switch's; either is the row's own.
                    self.assertIn(found, (index + 1, index + 2))
                else:
                    self.assertEqual(found, index + 1)
        self.assertEqual(access.pick(items, -5, -5), 0)

    def test_what_changes_on_screen_is_announced_and_a_ticking_countdown_is_not(self):
        vm, plan = planned()
        before = popup.accessible_items(vm, plan, strings=EN)
        self.assertEqual(access.changes(before, before), [])
        ticked = [dict(item, value="0:41" if item["value"] else item["value"]) for item in before]
        self.assertEqual(access.changes(before, ticked), [], "a countdown moves every second and says nothing")
        focus = ("check", vm["tasks"][1]["interruption_id"])
        focused = popup.accessible_items(vm, plan, focus=focus, strings=EN)
        self.assertEqual(access.changes(before, focused), [(access.EVENT_FOCUS, 7)], "the second task's switch")
        hovered = popup.accessible_items(vm, plan, hover=("toggle",), strings=EN)
        self.assertEqual(access.changes(before, hovered), [], "the pointer is not a change of state")
        vm["tasks"][0]["checked"] = not vm["tasks"][0]["checked"]
        flipped = popup.accessible_items(vm, plan, strings=EN)
        self.assertIn((access.EVENT_STATECHANGE, 5), access.changes(before, flipped))
        fewer = before[:3] + before[5:]
        self.assertEqual(access.changes(before, fewer)[0], (access.EVENT_REORDER, 0))


class TextSizeTests(unittest.TestCase):
    """Windows' text size, read and fitted - and the popup and the card whole at every size it gives."""

    def test_the_percentage_is_a_factor_from_one_to_two_and_a_quarter(self):
        for percent, factor in ((100, 1.0), (125, 1.25), (225, 2.25), (99, 1.0), (226, 1.0), (0, 1.0), (True, 1.0),
                                ("150", 1.0), (None, 1.0), (150.0, 1.0)):
            with self.subTest(percent=percent):
                self.assertEqual(textsize.factor(percent), factor)

    @unittest.skipUnless(os.name == "nt", "Windows' own setting")
    def test_the_setting_is_read_where_windows_keeps_it(self):
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, textsize.KEY) as key:
                value, kind = winreg.QueryValueEx(key, textsize.VALUE)
            expected = textsize.factor(value) if kind == winreg.REG_DWORD else 1.0
        except OSError:
            expected = 1.0
        self.assertEqual(textsize.read(), expected)
        self.assertEqual((textsize.KEY, textsize.VALUE), ("Software\\Microsoft\\Accessibility", "TextScaleFactor"))

    def test_a_size_is_fitted_to_the_room_and_never_below_one(self):
        self.assertEqual(textsize.fitting(2.25, (400, 600), (2000, 2000)), 2.25)
        self.assertEqual(textsize.fitting(2.25, (400, 600), (2000, 900)), 1.5)
        self.assertEqual(textsize.fitting(2.25, (400, 600), (300, 300)), 1.0)
        self.assertEqual(textsize.fitting(1.0, (400, 600), (2000, 2000)), 1.0)
        self.assertEqual(textsize.fitting(0.5, (400, 600), (2000, 2000)), 1.0)
        self.assertEqual(textsize.fitting(True, (400, 600), (2000, 2000)), 1.0)

    def test_the_popup_asks_windows_through_the_one_place_a_test_replaces(self):
        with unittest.mock.patch.object(textsize, "read", lambda: 1.75):
            self.assertEqual(popup.theme.text_scale(), 1.75)

    def test_everything_sits_inside_the_card_at_every_text_size_in_every_language(self):
        """The text size draws the whole popup larger (Popup._fitting), so its layout at a text size is its
        layout at that many times the display's scale: every scaling to 200% at every text size to 225%."""
        many = [row(key, eligible=NOW + index * 100, name="A rather long conversation name %d" % index)
                for index, key in enumerate("abcde")]
        for locale in l10n.LOCALES:
            strings = interface.STRINGS[locale]
            for scale in (1.0, 2.0):
                for text in (1.5, 2.25):
                    with self.subTest(locale=locale, scale=scale, text=text):
                        vm = popup.view_model(many, STATUS, strings, NOW, notice=strings["popup.stale"])
                        plan = popup.layout(vm, scale * text, measure)
                        card = plan["card"]
                        for item in plan["items"]:
                            rect = item.get("rect")
                            if rect is None or item["kind"] in ("card", "focusable"):
                                continue
                            self.assertGreaterEqual(rect[0], card[0], item)
                            self.assertGreaterEqual(rect[1], card[1], item)
                            self.assertLessEqual(rect[2], card[2], item)
                            self.assertLessEqual(rect[3], card[3], item)
                            if item["kind"] == "text" and item["wrap"]:
                                left, top, right, bottom = rect
                                self.assertGreaterEqual(bottom - top, measure(item["role"], item["text"],
                                                                              right - left, True)[1])

    def test_the_card_is_fitted_to_half_the_work_area(self):
        where = {"dpi": 96, "work": (0, 0, 3840, 2100)}
        self.assertEqual(popup_card().Card.fitting(where, {"text": 2.25}), 2.25)
        small = {"dpi": 96, "work": (0, 0, 1280, 720)}
        fitted = popup_card().Card.fitting(small, {"text": 2.25})
        self.assertLess(fitted, 2.25)
        self.assertLessEqual(notice_card.USUAL_HEIGHT * fitted, 720 * popup_card().Card.ROOM[1] + 1e-6)
        self.assertEqual(popup_card().Card.fitting(where, {}), 1.0)
        self.assertEqual(popup_card().Card.fitting({"dpi": 96}, {"text": 2.25}), 1.0)
        self.assertEqual(popup_card().Card.fitting(where, {"text": "2"}), 1.0)

    def test_the_notification_card_is_whole_at_every_text_size(self):
        """The card's own layout test (test_notice_card.LayoutTests.check) at a text size's scales: every notice
        in every language, with the longest names, at 150% and 225% of every scaling to 200%."""
        import test_notice_card
        cards = test_notice_card.LayoutTests()
        for locale in l10n.LOCALES:
            for notice in cards.notices(locale):
                for zoom in (1.5, 2.25, 3.0, 4.5):
                    with self.subTest(locale=locale, kind=notice.kind, zoom=zoom):
                        cards.check(notice_card.layout(notice_card.view(notice), zoom,
                                                       test_notice_card.fake_measure(zoom)), zoom)


def popup_card():
    from codex_auto_resume.ui.card import card
    return card


def _pump(seconds):
    base.WindowsTests.pump(None, seconds)


@unittest.skipUnless(os.name == "nt" and ctypes.sizeof(ctypes.c_void_p) == 8, "Windows' accessibility, 64-bit")
class ScreenReaderTests(unittest.TestCase):
    """The real window, read the way a screen reader reads it."""

    @classmethod
    def setUpClass(cls):
        ole32 = ctypes.WinDLL("ole32")
        ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        ole32.CoInitializeEx(None, 2)
        cls.oleacc = ctypes.WinDLL("oleacc")
        cls.oleacc.AccessibleObjectFromWindow.argtypes = [ctypes.c_void_p, ctypes.c_long, ctypes.c_void_p,
                                                          ctypes.POINTER(ctypes.c_void_p)]
        cls.oleacc.AccessibleObjectFromWindow.restype = ctypes.c_long
        cls.oleaut = ctypes.WinDLL("oleaut32")
        cls.oleaut.SysFreeString.argtypes = [ctypes.c_void_p]

    def setUp(self):
        self.control = base.FakeControl(rows())
        self.window = popup.Popup(control=self.control, strings=EN)
        self.window.create()
        self.window.model.apply_outcome(("read",), popup.perform(("read",), self.control), time.time())
        with unittest.mock.patch.object(popup.theme, "text_scale", lambda: 1.0):
            self.window.show(keyboard=True, activate=False, origin=(-32000, -32000))
        _pump(0.2)

    def tearDown(self):
        self.window.destroy()

    def client(self, objid=access.OBJID_CLIENT):
        found = ctypes.c_void_p()
        result = self.oleacc.AccessibleObjectFromWindow(self.window.hwnd, objid,
                                                        ctypes.byref(access.IID_IACCESSIBLE), ctypes.byref(found))
        self.assertEqual(result, 0)
        self.assertTrue(found.value)
        return found

    @staticmethod
    def call(pointer, slot, *types):
        table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
        return ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *types)(table[slot])

    @staticmethod
    def child(number):
        variant = access.VARIANT()
        variant.vt = access.VT_I4
        variant.value.lVal = number
        return variant

    def text(self, pointer, slot, number):
        variant = self.child(number)
        out = ctypes.c_void_p()
        result = self.call(pointer, slot, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(
            pointer, ctypes.addressof(variant), ctypes.byref(out))
        value = ctypes.wstring_at(out.value) if out.value else None
        if out.value:
            self.oleaut.SysFreeString(out)
        return result, value

    def number(self, pointer, slot, number):
        variant, out = self.child(number), access.VARIANT()
        result = self.call(pointer, slot, ctypes.c_void_p, ctypes.POINTER(access.VARIANT))(
            pointer, ctypes.addressof(variant), ctypes.byref(out))
        return result, out.vt, out.value.lVal

    def release(self, pointer):
        ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(
            ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0][2])(pointer)

    def expected(self):
        window = self.window
        return popup.accessible_items(window._vm, window._plan, window.focus if window.keyboard else None,
                                      window.hover, window.model.strings)

    def test_every_row_and_button_is_there_by_name_role_and_state(self):
        pointer = self.client()
        try:
            count = ctypes.c_long()
            self.assertEqual(self.call(pointer, 8, ctypes.POINTER(ctypes.c_long))(pointer, ctypes.byref(count)), 0)
            items = self.expected()
            self.assertEqual(count.value, len(items))
            self.assertEqual(self.text(pointer, 10, 0), (0, EN["tray.title"]))
            self.assertEqual(self.number(pointer, 13, 0), (0, access.VT_I4, ROLE_NUMBERS["dialog"]))
            for index, item in enumerate(items, 1):
                with self.subTest(item["name"]):
                    self.assertEqual(self.text(pointer, 10, index), (0, item["name"]))
                    self.assertEqual(self.number(pointer, 13, index), (0, access.VT_I4, ROLE_NUMBERS[item["role"]]))
                    state = 0
                    for name in item["states"]:
                        state |= access.A11Y_STATES[name]
                    self.assertEqual(self.number(pointer, 14, index), (0, access.VT_I4, state))
                    self.assertEqual(self.text(pointer, 20, index)[1], item["action"])
            self.assertEqual(self.number(pointer, 10 + 3, len(items) + 1)[0], access.E_INVALIDARG)
        finally:
            self.release(pointer)

    def test_each_child_is_where_it_is_drawn_and_a_hit_finds_it(self):
        pointer = self.client()
        user32 = ctypes.WinDLL("user32")
        user32.ClientToScreen.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.wintypes.POINT)]
        try:
            for index, item in enumerate(self.expected(), 1):
                box = [ctypes.c_long() for _ in range(4)]
                variant = self.child(index)
                self.assertEqual(self.call(pointer, 22, *([ctypes.POINTER(ctypes.c_long)] * 4), ctypes.c_void_p)(
                    pointer, *[ctypes.byref(part) for part in box], ctypes.addressof(variant)), 0)
                corner = ctypes.wintypes.POINT(item["rect"][0], item["rect"][1])
                with popup.win32._PerMonitorDpi():
                    user32.ClientToScreen(self.window.hwnd, ctypes.byref(corner))
                with self.subTest(item["name"]):
                    self.assertEqual([part.value for part in box],
                                     [corner.x, corner.y, item["rect"][2] - item["rect"][0],
                                      item["rect"][3] - item["rect"][1]])
                    if item["role"] in ("switch", "button"):
                        out = access.VARIANT()
                        self.assertEqual(self.call(pointer, 24, ctypes.c_long, ctypes.c_long,
                                                   ctypes.POINTER(access.VARIANT))(
                            pointer, corner.x + 2, corner.y + 2, ctypes.byref(out)), 0)
                        self.assertEqual((out.vt, out.value.lVal), (access.VT_I4, index))
        finally:
            self.release(pointer)

    def test_the_keyboards_place_is_the_focused_child_and_a_move_is_announced(self):
        pointer = self.client()
        try:
            out = access.VARIANT()
            self.assertEqual(self.call(pointer, 18, ctypes.POINTER(access.VARIANT))(pointer, ctypes.byref(out)), 0)
            items = self.expected()
            focused = next(index for index, item in enumerate(items, 1) if "focused" in item["states"])
            self.assertEqual((out.vt, out.value.lVal), (access.VT_I4, focused))
            told = []
            with unittest.mock.patch.object(access, "announce", lambda window, before, after: told.append(
                    access.changes(before, after))):
                self.window._key(popup.VK_TAB)
            self.assertEqual(told, [[(access.EVENT_FOCUS, focused + 2)]], "the next switch, a row further on")
        finally:
            self.release(pointer)

    def test_pressing_a_switch_is_the_click_on_it(self):
        pointer = self.client()
        try:
            items = self.expected()
            index = next(index for index, item in enumerate(items, 1) if item["role"] == "switch")
            task = self.window._vm["tasks"][0]
            variant = self.child(index)
            self.assertEqual(self.call(pointer, 25, ctypes.c_void_p)(pointer, ctypes.addressof(variant)), 0)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not any(call[0] == "set_interruption_recovery"
                                                          for call in self.control.calls):
                _pump(0.05)
            self.assertIn(("set_interruption_recovery", task["interruption_id"], task["thread_id"],
                           not task["checked"]), self.control.calls)
            text = next(index for index, item in enumerate(items, 1) if item["target"] is None)
            variant = self.child(text)
            self.assertEqual(self.call(pointer, 25, ctypes.c_void_p)(pointer, ctypes.addressof(variant)),
                             access.DISP_E_MEMBERNOTFOUND)
        finally:
            self.release(pointer)

    def test_anything_else_asked_of_the_window_is_windows_own_answer(self):
        pointer = self.client(access.OBJID_WINDOW)
        try:
            self.assertEqual(self.number(pointer, 13, 0), (0, access.VT_I4, 0x09))      # ROLE_SYSTEM_WINDOW
        finally:
            self.release(pointer)

    @unittest.skipUnless(POWERSHELL.is_file(), "needs PowerShell")
    def test_another_process_reads_it_as_narrator_does(self):
        """Through COM's own marshalling from another process - what Narrator does - with .NET's
        Accessibility.IAccessible as the reader."""
        reader = r'''
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
        import tempfile
        folder = tempfile.mkdtemp()
        script = Path(folder) / "reader.ps1"
        script.write_text(reader, encoding="utf-8")
        child = subprocess.Popen([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                  "-File", str(script)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                 encoding="utf-8", errors="replace", env=dict(os.environ, CAR_HWND=str(self.window.hwnd)),
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        deadline = time.monotonic() + 120
        while child.poll() is None and time.monotonic() < deadline:
            _pump(0.05)                              # its questions arrive as this thread's messages
        out, err = child.communicate(timeout=10)
        script.unlink()
        os.rmdir(folder)
        self.assertEqual(child.returncode, 0, err[-2000:])
        read = json.loads(out)
        items = self.expected()
        self.assertEqual(read[0][:2], [EN["tray.title"], ROLE_NUMBERS["dialog"]])
        self.assertEqual([entry[:2] for entry in read[1:]], [[item["name"], ROLE_NUMBERS[item["role"]]] for item in items])
        for entry, item in zip(read[1:], items):
            with self.subTest(item["name"]):
                self.assertEqual(bool(entry[2] & access.A11Y_STATES["checked"]), "checked" in item["states"])
                self.assertEqual(bool(entry[2] & access.A11Y_STATES["focused"]), "focused" in item["states"])


@unittest.skipUnless(os.name == "nt", "Windows' screen")
class PopupTextSizeTests(unittest.TestCase):
    """The popup at Windows' text size: the whole of it larger, as far as the screen holds it."""

    def make(self, text, work):
        window = popup.Popup(control=base.FakeControl(rows()), strings=EN)
        window.create()
        window.model.apply_outcome(("read",), popup.perform(("read",), window.control), time.time())
        window._text = text
        window._screen = {"work": work, "monitor": work, "icon": None, "cursor": (0, 0), "dpi": 96}
        window.dpi = 96
        return window

    def test_the_popup_is_drawn_that_much_larger_as_far_as_the_screen_holds_it(self):
        for text, work, whole in ((1.0, (0, 0, 3840, 2100), True), (2.25, (0, 0, 3840, 2100), True),
                                  (2.25, (0, 0, 1366, 700), False)):
            window = self.make(text, work)
            try:
                usual = window._renderer.layout(window.model.view(time.time()), 1.0, "en")["size"]
                plan = window._rebuild(time.time())
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
            finally:
                window.destroy()

    def test_the_fit_is_worked_out_once_an_opening_and_not_at_every_tick(self):
        window = self.make(2.25, (0, 0, 3840, 2100))
        try:
            scales, real = [], window._renderer.layout
            window._renderer.layout = lambda vm, scale, locale: scales.append(scale) or real(vm, scale, locale)
            window._rebuild(time.time())
            window._rebuild(time.time())
            self.assertEqual(scales, [1.0, 2.25, 2.25], "the usual size measured once, then the fitted one")
            window.hide()
            window._rebuild(time.time())
            self.assertEqual(scales[3:], [1.0, 2.25], "and again at the next opening")
        finally:
            window.destroy()

    def test_opening_asks_windows_for_its_text_size(self):
        window = self.make(1.0, (0, 0, 3840, 2100))
        try:
            with unittest.mock.patch.object(popup.theme, "text_scale", lambda: 1.5):
                window._read_look()
            self.assertEqual(window._text, 1.5)
        finally:
            window.destroy()


if __name__ == "__main__":
    unittest.main()
