"""The popup's row menus, drawn by the code that draws the icon's menu (v0.6.20).

A task row's own menu (right click, Shift+F10 or the menu key on a row) was Windows' own until the owner asked, on
2026-11-01, for it to open as the icon's menu does: in the product's design, by the same window
(ui/popup/menuwindow.py) and the same plan (menuplan.py). Its items have submenus - Postpone and the tier - so the drawn
menu opens one beside its item. These tests hold:

* parity - the drawn menu is handed exactly the row's items (model.menu_for) in their order and state, and a choice in
  it runs the action Windows' menu ran, through the same checks;
* the fallback - Windows' menu where the drawn one cannot open, and only there;
* submenus - where one opens, the keys, the pointer's delay, one at a time, a choice in one;
* right to left - the arrows swap and the submenu opens leftward;
* the popup and its menu - the popup stays open while its own menu has the focus, and closes it as it hides;
* on Windows, the window it opens in is the drawn menu's class, made and never shown, and its submenu arrow is drawn.
"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import sys
import unittest
import unittest.mock

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from codex_auto_resume import l10n  # noqa: E402
from codex_auto_resume.ui import popup  # noqa: E402
from codex_auto_resume.ui.popup import access, menuwindow  # noqa: E402
from codex_auto_resume.ui.popup import messages as popup_messages, win32  # noqa: E402
from codex_auto_resume.ui.popup import window as popup_window  # noqa: E402

KEY, THREAD = "interruption-example", "thread-example"
EN = l10n.catalog("en")


def measure(role, text, width, wrap):
    """A stand-in for DrawTextW: a fixed advance per character and a fixed line."""
    return int(len(text) * 7), 16


def row(**extra):
    return dict({"interruption_id": KEY, "thread_id": THREAD, "state": "waiting_reset",
                 "category": "usage_limit", "eligible_at": 2000.0, "overlays": [],
                 "thread_enabled": True, "hold": None, "tier": None}, **extra)


def shown_popup(make_menu=None, **extra):
    """A Popup with one drawn row and nothing of Windows': its work and redraws recorded."""
    shown = popup.Popup(strings=EN, make_menu=make_menu)
    shown.hwnd = 7
    shown.model.rows = [row(**extra)]
    shown.model.status = {"enabled": True, "settings": {"default_tier": "ask_first"}}
    shown.model.view(1000.0)
    shown._painted_plan = {"rows": [(KEY, (0, 0, 200, 60))], "targets": []}
    shown.ran = []
    shown._run = shown.ran.append
    shown._update = lambda *args: None
    return shown


class FakeUser32:
    """What the popup's Windows half and the drawn menu ask of user32, recorded; the menu Windows would show chooses
    `chosen`."""

    def __init__(self, chosen=0):
        self.chosen, self.tracked, self.calls = chosen, 0, []

    def TrackPopupMenu(self, *unused):
        self.tracked += 1
        return self.chosen

    def CreatePopupMenu(self):
        return 100 + self.tracked

    def __getattr__(self, name):
        def call(*args):
            self.calls.append((name,) + args)
            return 1
        return call


class FakeDrawn:
    """The drawn menu as the popup sees it: what it was opened with, and whether it opens."""

    def __init__(self, opens=True, breaks=False):
        self.opens, self.breaks, self.opened, self.destroyed, self.closed = opens, breaks, [], 0, 0
        self.hwnd = 4242

    def open(self, entries, strings, on_choose, point=None, owner=None, on_leave=None):
        if self.breaks:
            raise OSError("UpdateLayeredWindow")
        self.opened.append({"entries": entries, "on_choose": on_choose, "point": point, "owner": owner,
                            "on_leave": on_leave})
        return self.opens

    def close(self):
        self.closed += 1

    def destroy(self):
        self.destroyed += 1


def menu_entries(**extra):
    return popup.menu_numbered(shown_popup(**extra).model.menu_for(KEY))[0]


class ParityTests(unittest.TestCase):
    def test_the_drawn_menu_is_handed_the_row_s_items_in_their_order_with_their_state(self):
        made = []
        shown = shown_popup(make_menu=lambda: made.append(FakeDrawn()) or made[-1])
        user32 = FakeUser32()
        with unittest.mock.patch.object(popup_window, "_dll", lambda name: user32):
            shown._context_menu((30 << 16) | 40)
        self.assertEqual(user32.tracked, 0, "Windows' menu is not shown")
        opened = made[0].opened[0]
        model = shown.model.menu_for(KEY)

        def shape(entries):
            return [None if entry is None else (entry["text"], entry["enabled"], entry["checked"],
                                                shape(entry["items"]) if entry["items"] else None)
                    for entry in entries]
        self.assertEqual(shape(opened["entries"]), shape(model))
        self.assertEqual((opened["point"], opened["owner"]), ((40, 30), 7), "at the pointer, the popup's keyboard")
        self.assertEqual(opened["on_leave"], shown.hide)

    def test_a_choice_in_the_drawn_menu_runs_the_action_windows_menu_runs(self):
        made = []
        shown = shown_popup(make_menu=lambda: made.append(FakeDrawn()) or made[-1])
        with unittest.mock.patch.object(popup_window, "_dll", lambda name: FakeUser32()):
            shown._context_menu((30 << 16) | 40)
        made[0].opened[0]["on_choose"](2)                       # the second leaf: postpone by an hour
        drawn_ran = list(shown.ran)
        windows = shown_popup()
        with unittest.mock.patch.object(popup_window, "_dll", lambda name: FakeUser32(chosen=2)):
            windows._context_menu((30 << 16) | 40)
        self.assertEqual(drawn_ran, windows.ran)
        self.assertEqual(drawn_ran, [("postpone", KEY, THREAD, "1_hour")])
        made[0].opened[0]["on_choose"](2)
        self.assertEqual(shown.ran, drawn_ran, "the same check: an action under way is not asked again")

    def test_every_leaf_is_numbered_depth_first_as_windows_menu_numbers_its_commands(self):
        model = shown_popup().model.menu_for(KEY)
        numbered, actions = popup.menu_numbered(model)
        leaves = [entry for top in model if top for entry in (top["items"] or [top]) if entry]
        self.assertEqual([actions[number] for number in sorted(actions)],
                         [entry["action"] if entry["enabled"] else None for entry in leaves])
        self.assertIsNone(numbered[0]["id"], "Postpone opens a submenu and is no command")
        self.assertEqual(numbered[0]["items"][1]["id"], 2)

    def test_the_keyboard_opens_it_at_the_focused_row(self):
        made = []
        shown = shown_popup(make_menu=lambda: made.append(FakeDrawn()) or made[-1])
        shown.focus = ("check", KEY)
        with unittest.mock.patch.object(popup_window, "_dll", lambda name: FakeUser32()):
            shown._context_menu(0xFFFFFFFF)
        self.assertEqual(made[0].opened[0]["point"], (0, 0), "the row's corner (ClientToScreen is a stand-in)")


class FallbackTests(unittest.TestCase):
    def test_a_popup_with_nothing_to_draw_it_with_shows_windows_menu(self):
        user32 = FakeUser32(chosen=2)
        shown = shown_popup()
        with unittest.mock.patch.object(popup_window, "_dll", lambda name: user32):
            shown._context_menu((30 << 16) | 40)
        self.assertEqual((user32.tracked, shown.ran), (1, [("postpone", KEY, THREAD, "1_hour")]))

    def test_an_opening_refused_the_foreground_is_windows_menu_that_once(self):
        drawn = FakeDrawn(opens=False)
        shown = shown_popup(make_menu=lambda: drawn)
        user32 = FakeUser32()
        with unittest.mock.patch.object(popup_window, "_dll", lambda name: user32):
            shown._context_menu((30 << 16) | 40)
            self.assertEqual(user32.tracked, 1)
            drawn.opens = True
            shown._context_menu((30 << 16) | 40)
        self.assertEqual((user32.tracked, len(drawn.opened)), (1, 2), "the next opening is drawn again")

    def test_a_drawn_menu_that_breaks_gives_way_to_windows_for_good_and_says_so_once(self):
        logged, made = [], []
        shown = shown_popup(make_menu=lambda: made.append(FakeDrawn(breaks=True)) or made[-1])
        shown.log = logged.append
        user32 = FakeUser32()
        with unittest.mock.patch.object(popup_window, "_dll", lambda name: user32):
            shown._context_menu((30 << 16) | 40)
            shown._context_menu((30 << 16) | 40)
        self.assertEqual((user32.tracked, len(made), made[0].destroyed), (2, 1, 1))
        self.assertEqual(logged, ["tray popup menu drawn unavailable (OSError)"])
        self.assertIs(shown._row_menu, False)

    def test_the_icon_gives_its_popup_the_drawn_menu(self):
        source = (Path(_HERE).parent / "src/codex_auto_resume/ui/tray/clicks.py").read_text(encoding="utf-8")
        self.assertIn("make_menu=lambda: tray_popup.Menu(log=self.log)", source)


class PopupFocusTests(unittest.TestCase):
    def test_the_popup_stays_open_while_its_own_menu_has_the_focus_and_closes_it_as_it_hides(self):
        drawn = FakeDrawn()
        shown = shown_popup(make_menu=lambda: drawn)
        shown._row_menu = drawn
        shown.visible = True
        hidden = []
        with unittest.mock.patch.object(shown, "hide", lambda: hidden.append(True)), \
                unittest.mock.patch.object(popup_messages, "_dll", lambda name: FakeUser32()):
            shown._handle(7, win32.WM_ACTIVATE, win32.WA_INACTIVE, drawn.hwnd)
            self.assertEqual(hidden, [], "focus to its own menu")
            shown._handle(7, win32.WM_ACTIVATE, win32.WA_INACTIVE, 99)
            self.assertEqual(hidden, [True], "focus anywhere else")
        with unittest.mock.patch.object(popup_window, "_dll", lambda name: FakeUser32()):
            shown.hide()
            self.assertEqual(drawn.closed, 1)
            shown.destroy()
        self.assertEqual(drawn.destroyed, 1)


# ------------------------------------------------------------------------------ the drawn menu's submenus
class StubRenderer:
    def menu_layout(self, entries, scale, locale, max_width=None):
        laid = popup.menu_layout(entries, scale, measure, max_width)
        return popup.menu_mirror(laid) if l10n.right_to_left(locale) else laid

    def close(self):
        pass


class SubmenuTests(unittest.TestCase):
    """The drawn menu's own handlers with a row menu in it; what draws it and Windows replaced, no window made."""

    def setUp(self, locale="en", **extra):
        self.user32 = FakeUser32()
        for target, name, value in ((menuwindow, "_dll", lambda name: self.user32),
                                    (menuwindow.Menu, "_push", lambda menu: None),
                                    (menuwindow.Menu, "_tell", lambda menu, event: self.told.append(event)),
                                    (menuwindow.Menu, "create", self.fake_create),
                                    (access, "announce", lambda *unused: None)):
            patcher = unittest.mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.told, self.chosen, self.left = [], [], []
        self.menu = self.open(locale, **extra)

    @staticmethod
    def fake_create(menu):
        menu.hwnd, menu._renderer = 900 + (1 if menu.parent else 0), StubRenderer()

    def open(self, locale="en", **extra):
        strings = l10n.catalog(locale)
        menu = menuwindow.Menu()
        menu.create()
        menu.entries, menu.strings, menu.locale = menu_entries(**extra), dict(strings), locale
        menu.on_choose, menu.owner, menu.on_leave = self.chosen.append, 7, lambda: self.left.append(True)
        menu._plan = menu._renderer.menu_layout(menu.entries, 1.0, locale)
        menu._work, menu._origin, menu.visible = (0, 0, 1920, 1040), (300, 200), True
        return menu

    def key(self, code, menu=None):
        return (menu or self.menu)._handle(menuwindow.WM_KEYDOWN, code, 0)

    def at(self, menu, index):
        rect = next(item["rect"] for item in menu._plan["items"] if item["index"] == index)
        return (rect[0] + 4) | ((rect[1] + 3) << 16)

    def child(self):
        return self.menu._child

    def test_the_arrow_towards_it_opens_the_submenu_its_first_item_in_hand_and_enter_chooses_in_it(self):
        self.key(menuwindow.VK_DOWN)
        self.assertEqual(self.menu.selected, 0, "Postpone")
        self.key(menuwindow.VK_RIGHT)
        self.assertTrue(self.child().visible)
        self.assertEqual((self.child().selected, self.menu.selected), (0, 0), "the parent's item stays in hand")
        self.assertEqual(self.child().entries, self.menu.entries[0]["items"])
        self.key(menuwindow.VK_DOWN)                           # heard by the parent, moved in the submenu
        self.assertEqual(self.child().selected, 1)
        self.key(menuwindow.VK_RETURN)
        self.assertEqual(self.chosen, [2], "postpone by an hour")
        self.assertFalse(self.menu.visible or self.child().visible)
        self.assertIn(("SetForegroundWindow", 7), self.user32.calls, "the popup has the keyboard back")

    def test_enter_opens_it_and_the_arrow_back_and_esc_close_it_one_level_at_a_time(self):
        self.key(menuwindow.VK_DOWN)
        self.key(menuwindow.VK_RETURN)
        self.assertTrue(self.child().visible)
        self.key(menuwindow.VK_LEFT)
        self.assertFalse(self.child().visible)
        self.assertTrue(self.menu.visible)
        self.key(menuwindow.VK_RIGHT)
        self.key(menuwindow.VK_ESCAPE)
        self.assertEqual((self.child().visible, self.menu.visible), (False, True))
        self.key(menuwindow.VK_ESCAPE)
        self.assertFalse(self.menu.visible)
        self.assertEqual((self.chosen, self.left), ([], []), "Esc chooses nothing and is no click away")

    def test_home_end_and_letters_reach_into_the_open_submenu(self):
        self.key(menuwindow.VK_DOWN)
        self.key(menuwindow.VK_RIGHT)
        self.key(menuwindow.VK_END)
        last = popup.menu_end(self.child().entries, last=True)
        self.assertEqual(self.child().selected, last)
        self.key(menuwindow.VK_HOME)
        self.assertEqual(self.child().selected, 0)
        text = self.child().entries[last]["text"]
        index, choose = popup.menu_letter(self.child().entries, 0, text[0])
        self.menu._handle(menuwindow.WM_CHAR, ord(text[0]), 0)
        if choose:
            self.assertEqual(self.chosen, [self.child().entries[index]["id"]])
        else:
            self.assertEqual(self.child().selected, index)

    def test_the_pointer_resting_on_it_opens_it_after_windows_delay_and_on_another_item_closes_it(self):
        self.menu._handle(menuwindow.WM_MOUSEMOVE, 0, self.at(self.menu, 0))
        self.assertIsNone(self.child(), "nothing opens before the delay")
        self.assertTrue(any(call[0] == "SetTimer" for call in self.user32.calls))
        self.menu._handle(menuwindow.WM_TIMER, menuwindow.HOVER_TIMER, 0)
        self.assertTrue(self.child().visible)
        self.assertIsNone(self.child().selected, "opened by the pointer: nothing in hand")
        self.menu._handle(menuwindow.WM_MOUSEMOVE, 0, self.at(self.menu, 4))
        self.assertTrue(self.child().visible, "still open until the delay passes")
        self.menu._handle(menuwindow.WM_TIMER, menuwindow.HOVER_TIMER, 0)
        self.assertFalse(self.child().visible)

    def test_one_submenu_at_a_time_and_a_click_on_its_item_opens_it_at_once(self):
        self.menu._handle(menuwindow.WM_LBUTTONUP, 0, self.at(self.menu, 0))
        postpone = self.child().entries
        self.assertTrue(self.child().visible)
        self.menu._handle(menuwindow.WM_LBUTTONUP, 0, self.at(self.menu, 3))      # the tier
        self.assertTrue(self.child().visible)
        self.assertEqual(self.child().entries, self.menu.entries[3]["items"])
        self.assertNotEqual(self.child().entries, postpone)
        self.assertEqual(self.menu._child_index, 3)

    def test_a_click_in_the_submenu_chooses_and_the_pointer_there_keeps_its_item_in_hand(self):
        self.menu._handle(menuwindow.WM_LBUTTONUP, 0, self.at(self.menu, 3))
        child = self.child()
        self.assertEqual(child._handle(menuwindow.WM_MOUSEACTIVATE, 0, 0), menuwindow.MA_NOACTIVATE)
        child._handle(menuwindow.WM_MOUSEMOVE, 0, self.at(child, 2))
        self.assertEqual((child.selected, self.menu.selected), (2, 3))
        child._handle(menuwindow.WM_LBUTTONUP, 0, self.at(child, 2))
        self.assertEqual(self.chosen, [self.menu.entries[3]["items"][2]["id"]])
        self.assertFalse(self.menu.visible or child.visible)

    def test_closing_the_menu_closes_its_submenu_and_a_click_away_tells_the_popup(self):
        self.key(menuwindow.VK_DOWN)
        self.key(menuwindow.VK_RIGHT)
        self.menu._handle(menuwindow.WM_ACTIVATE, menuwindow.WA_INACTIVE, 99)
        self.assertFalse(self.menu.visible or self.child().visible)
        self.assertEqual(self.left, [True])
        self.menu.visible = True
        self.menu._handle(menuwindow.WM_ACTIVATE, menuwindow.WA_INACTIVE, 7)
        self.assertEqual(self.left, [True], "the focus went back to the popup: nothing to tell")

    def test_a_submenu_of_an_item_that_cannot_be_used_does_not_open(self):
        menu = self.open(self.menu.locale)
        menu.entries[0] = dict(menu.entries[0], enabled=False)         # Postpone, on a row that is not waiting
        menu._plan = menu._renderer.menu_layout(menu.entries, 1.0, menu.locale)
        menu.selected = 0
        self.key(menuwindow.VK_RIGHT, menu)
        self.key(menuwindow.VK_RETURN, menu)
        self.assertIsNone(menu._child)

    def test_a_screen_reader_hears_an_item_that_opens_a_submenu(self):
        items = self.menu.accessible_items()
        self.assertIn("haspopup", items[0]["states"])
        self.assertNotIn("haspopup", items[1]["states"])
        self.assertIn("haspopup", access.A11Y_STATES)


class RightToLeftSubmenuTests(SubmenuTests):
    def setUp(self):
        super().setUp(locale="ar")

    def key(self, code, menu=None):
        # The tests above are written left to right: the arrows swap where the language is written right to left.
        code = {menuwindow.VK_LEFT: menuwindow.VK_RIGHT, menuwindow.VK_RIGHT: menuwindow.VK_LEFT}.get(code, code)
        return super().key(code, menu)

    def test_the_layout_is_mirrored_with_the_arrow_at_the_left(self):
        item = self.menu._plan["items"][0]
        self.assertTrue(self.menu._plan["rtl"])
        self.assertLess(item["arrow"][0], item["text_rect"][0])

    def test_the_left_to_right_arrow_does_not_open_it(self):
        self.menu.selected = 0
        menuwindow.Menu._key(self.menu, menuwindow.VK_RIGHT)
        self.assertIsNone(self.menu._child)


class PlacementTests(unittest.TestCase):
    WORK = (0, 0, 1920, 1040)

    def plan(self, rtl=False):
        laid = popup.menu_layout(menu_entries()[0]["items"], 1.0, measure)
        return popup.menu_mirror(laid) if rtl else laid

    def card_at(self, plan, beside, work=WORK):
        x, y = popup.menu_beside(plan, beside, work)
        card = plan["card"]
        return (x + card[0], y + card[1], x + card[2], y + card[3])

    def test_it_opens_to_the_right_of_the_card_its_first_item_level_with_the_parent_s(self):
        plan = self.plan()
        card = self.card_at(plan, (400, 300, 600, 330))
        self.assertEqual(card[0], 600)
        first = next(item["rect"][1] for item in plan["items"] if item["kind"] == "item")
        self.assertEqual(card[1] + first - plan["card"][1], 300)

    def test_with_no_room_on_the_right_it_opens_to_the_left(self):
        plan = self.plan()
        card = self.card_at(plan, (1700, 300, 1900, 330))
        self.assertEqual(card[2], 1700)

    def test_right_to_left_it_opens_to_the_left_and_to_the_right_without_room(self):
        plan = self.plan(rtl=True)
        self.assertEqual(self.card_at(plan, (800, 300, 1000, 330))[2], 800)
        self.assertEqual(self.card_at(plan, (10, 300, 210, 330))[0], 210)

    def test_it_stays_inside_the_work_area(self):
        plan = self.plan()
        card = self.card_at(plan, (400, 1020, 600, 1040))
        self.assertLessEqual(card[3], 1040)

    def test_an_item_with_a_submenu_has_an_arrow_at_its_far_end(self):
        plan = popup.menu_layout(menu_entries(), 1.0, measure)
        postpone = plan["items"][0]
        self.assertTrue(postpone["submenu"])
        self.assertGreater(postpone["arrow"][0], postpone["text_rect"][0])
        self.assertNotIn("arrow", plan["items"][1])


@unittest.skipUnless(os.name == "nt", "the drawn menu is a Windows window")
class WindowsTests(unittest.TestCase):
    """The real class and the real renderer; the window is made hidden and never shown, nothing is captured."""

    def test_the_row_menu_opens_in_the_drawn_menu_s_window(self):
        menus = []

        def made():
            menu = popup.Menu()
            menus.append(menu)
            self.addCleanup(menu.destroy)
            return menu

        def opened(menu, entries, strings, on_choose, **unused):
            menu.create()                       # made as an opening makes it, and not shown
            return True
        shown = shown_popup(make_menu=made)
        with unittest.mock.patch.object(popup.Menu, "open", opened), \
                unittest.mock.patch.object(popup_window, "_dll", lambda name: FakeUser32()):
            shown._context_menu((30 << 16) | 40)
        name = ctypes.create_unicode_buffer(256)
        user32 = ctypes.WinDLL("user32")
        user32.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
        user32.GetClassNameW(menus[0].hwnd, name, 256)
        self.assertTrue(name.value.startswith("CodexAutoResumeMenu"), name.value)

    def test_the_submenu_arrow_is_drawn_and_mirrored(self):
        renderer = popup.MenuRenderer()
        self.addCleanup(renderer.close)
        renderer.theme, renderer.contrast, renderer.design = "light", False, "soft"
        for locale in ("en", "he"):
            with self.subTest(locale=locale):
                plan = renderer.menu_layout(menu_entries(), 1.0, locale)
                pixels = renderer.draw_menu(plan).pixels()
                width = plan["size"][0]
                left, top, right, bottom = plan["items"][0]["arrow"]
                inks = {pixels[(y * width + x) * 4:(y * width + x) * 4 + 3]
                        for y in range(top, bottom) for x in range(left, right)}
                self.assertGreater(len(inks), 1, "something is drawn in the arrow's place")
                self.assertEqual(plan["rtl"], locale == "he")


if __name__ == "__main__":
    unittest.main()
