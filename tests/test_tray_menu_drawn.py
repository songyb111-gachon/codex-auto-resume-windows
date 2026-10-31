"""The icon's right-click menu, drawn in the product's design (v0.6.20).

Until v0.6.20 the menu was Windows' own (TrackPopupMenu). The owner asked for it in the product's design
(2026-11-01), as the window's menus are (gui/SoftMenu.cs), with everything Windows' menu gave a person. These tests
hold it to that, in four parts:

* parity - both ways of showing the menu are built from one list (ui/tray/menu.py menu_items), so the drawn one has
  every item of Windows' one, in its order, with its state, and a choice in it reaches the same action;
* the fallback - Windows' menu where the drawn one cannot open, and only there;
* keys, the pointer and closing - what Windows' menu does with each, against the drawn menu's own handlers;
* where it opens, right to left, and what it looks like in light, dark and High Contrast - and, on Windows, its real
  window read the way a screen reader reads it, never shown on the desktop.
"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import sys
import time
import unittest
import unittest.mock

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from codex_auto_resume import brand, interface  # noqa: E402
from codex_auto_resume.ui import popup, tray  # noqa: E402
from codex_auto_resume.ui.popup import access, menuwindow  # noqa: E402
from codex_auto_resume.ui.tray import menu as tray_menu  # noqa: E402

EN = interface.STRINGS["en"]
NOW = 1_800_000_000.0


def measure(role, text, width, wrap):
    """A stand-in for DrawTextW: a fixed advance per character and a fixed line."""
    return int(len(text) * 7), 16


class FakeUser32:
    """Just enough of user32 for Windows' menu to be built without being shown, choosing `chosen`."""

    def __init__(self, chosen=0):
        self.appended, self.chosen, self.tracked = [], chosen, 0

    def CreatePopupMenu(self):
        return 1

    def AppendMenuW(self, menu, flags, identifier, text):
        self.appended.append((flags, identifier, text))

    def GetCursorPos(self, point):
        return 1

    def SetForegroundWindow(self, hwnd):
        return 1

    def TrackPopupMenu(self, *unused):
        self.tracked += 1
        return self.chosen

    def PostMessageW(self, *unused):
        return 1

    def DestroyMenu(self, menu):
        return 1


class FakeDrawn:
    """The drawn menu as the icon sees it: what it was asked to show, and a way to choose in it."""

    def __init__(self, opens=True, breaks=False):
        self.opens, self.breaks, self.shown, self.destroyed = opens, breaks, [], 0

    def open(self, entries, strings, on_choose):
        if self.breaks:
            raise OSError("UpdateLayeredWindow")
        self.shown.append((entries, strings, on_choose))
        return self.opens

    def destroy(self):
        self.destroyed += 1


class FakeControl:
    def __init__(self, armed=None):
        self.armed, self.calls = armed, []

    def power_view(self):
        return {"armed": {"action": self.armed}} if self.armed else {"armed": None}

    def disarm_power_action(self, actor):
        self.calls.append(("disarm_power_action", actor))


SNAPSHOTS = [
    {"enabled": True, "waiting": 0, "running": 0},
    {"enabled": True, "waiting": 2, "running": 1, "next_at": NOW + 90},
    {"enabled": False, "waiting": 3},
]


def icon(armed=None, pending=True, **calls):
    made = tray.Tray(strings=dict(EN), control=FakeControl(armed),
                     on_pending=(calls.get("on_pending") or (lambda: None)) if pending else None,
                     on_open=calls.get("on_open"), on_toggle=calls.get("on_toggle"), on_stop=calls.get("on_stop"))
    made._adopt_settings = lambda: None            # the stored language is not this test's
    made._theme_menu = lambda: None
    return made


def native(items, chosen=0):
    """The (flags, id, text) Windows' menu is built with from `items`, and what it returns."""
    fake = FakeUser32(chosen)
    with unittest.mock.patch.object(tray_menu, "_dll", lambda name: fake):
        returned = icon()._native_menu(items)
    return fake.appended, returned


# ------------------------------------------------------------------------------ parity
class ParityTests(unittest.TestCase):
    def cases(self):
        for snapshot in SNAPSHOTS:
            for pending in (True, False):
                for armed in (None, "sleep", "hibernate", "shut_down"):
                    yield snapshot, pending, armed

    def test_the_drawn_menu_has_every_item_of_windows_menu_in_its_order_with_its_state(self):
        for snapshot, pending, armed in self.cases():
            with self.subTest(snapshot=snapshot, pending=pending, armed=armed):
                items = tray.menu_items(snapshot, EN, NOW, pending, armed)
                appended, _ = native(items)
                plan = popup.menu_layout(items, 1.0, measure)
                drawn = [("rule",) if item["kind"] == "rule" else (item["id"], item["text"], item["enabled"],
                                                                   item["checked"]) for item in plan["items"]]
                windows = [("rule",) if flags & tray_menu.MF_SEPARATOR else
                           (identifier, text, not flags & tray_menu.MF_GRAYED, bool(flags & tray_menu.MF_CHECKED))
                           for flags, identifier, text in appended]
                self.assertEqual(drawn, windows)
                usable = [index for index, _ in plan["targets"]]
                self.assertEqual(usable, [index for index, entry in enumerate(items) if entry and entry["enabled"]])

    def test_the_items_are_the_menu_windows_has_always_shown(self):
        items = tray.menu_items({"enabled": True, "waiting": 2}, EN, NOW, True, "shut_down")
        self.assertEqual([entry and (entry["id"], entry["text"], entry["enabled"]) for entry in items],
                         [(tray.MENU_STATUS, "2 waiting", False), None,
                          (tray.MENU_OPEN, EN["menu.open"], True),
                          (tray.MENU_PENDING, EN["menu.pending"].replace("{n}", "2"), True),
                          (tray.MENU_TOGGLE, EN["menu.pause"], True),
                          (tray.MENU_POWER_OFF, EN["menu.power_off.shut_down"], True), None,
                          (tray.MENU_STOP, EN["menu.stop"], True)])
        paused = tray.menu_items({"enabled": False}, EN, NOW, True, None)
        self.assertEqual([entry["id"] for entry in paused if entry], [tray.MENU_STATUS, tray.MENU_OPEN, tray.MENU_TOGGLE,
                                                                       tray.MENU_STOP])
        self.assertEqual(paused[3]["text"], EN["menu.resume"])
        self.assertFalse(any(entry and entry["checked"] for entry in items), "Windows' menu checks nothing")

    def test_the_icon_hands_the_drawn_menu_exactly_what_windows_menu_would_get(self):
        for snapshot, pending, armed in self.cases():
            with self.subTest(snapshot=snapshot, pending=pending, armed=armed):
                made = icon(armed, pending)
                made._hwnd, made._menu_drawn = 1, FakeDrawn()
                made.update(snapshot)
                with unittest.mock.patch.object(tray_menu.time, "time", lambda: NOW):
                    made._menu()
                    expected = tray.menu_items(made._shown(), EN, NOW, pending, armed)
                (entries, strings, _), = made._menu_drawn.shown
                self.assertEqual(entries, expected)
                self.assertEqual(strings, EN)

    def test_a_choice_in_the_drawn_menu_reaches_the_action_windows_menu_reaches(self):
        for enabled in (True, False):
            done = []
            made = icon("sleep", on_open=lambda: done.append("open"), on_stop=lambda: done.append("stop"),
                        on_pending=lambda: done.append("pending"),
                        on_toggle=lambda paused: done.append(("toggle", paused)))
            made._hwnd, made._menu_drawn = 1, FakeDrawn()
            made.update({"enabled": enabled, "waiting": 1})
            made._menu()
            (_, _, choose), = made._menu_drawn.shown
            made.update({"enabled": not enabled})               # what changes after drawing changes nothing
            for chosen in (tray.MENU_OPEN, tray.MENU_PENDING, tray.MENU_TOGGLE, tray.MENU_STOP, tray.MENU_POWER_OFF,
                           tray.MENU_STATUS):
                choose(chosen)
            self.assertEqual(done, ["open", "pending", ("toggle", not enabled), "stop"])
            self.assertEqual(made.control.calls, [("disarm_power_action", "tray")])


# ------------------------------------------------------------------------------ the fallback
class FallbackTests(unittest.TestCase):
    def open(self, made, chosen=0):
        fake = FakeUser32(chosen)
        with unittest.mock.patch.object(tray_menu, "_dll", lambda name: fake):
            made._menu()
        return fake

    def test_an_icon_without_its_own_window_shows_windows_menu(self):
        made = icon()
        made._menu_drawn = FakeDrawn()
        fake = self.open(made)
        self.assertEqual(fake.tracked, 1)
        self.assertEqual(made._menu_drawn.shown, [], "no loop of the icon's own to serve a drawn window")

    def test_the_drawn_menu_is_shown_and_windows_is_not(self):
        made = icon()
        made._hwnd, made._menu_drawn = 1, FakeDrawn()
        fake = self.open(made)
        self.assertEqual((fake.tracked, fake.appended), (0, []))
        self.assertEqual(len(made._menu_drawn.shown), 1)

    def test_a_drawn_menu_that_breaks_gives_way_to_windows_for_good_and_says_so_once(self):
        logged = []
        made = icon()
        made.log = logged.append
        broken = FakeDrawn(breaks=True)
        made._hwnd, made._menu_drawn = 1, broken
        done = []
        made.on_open = lambda: done.append("open")
        fake = self.open(made, chosen=tray.MENU_OPEN)
        self.assertEqual((fake.tracked, done), (1, ["open"]), "Windows' menu, and its choice acted on")
        self.assertIs(made._menu_drawn, False)
        self.assertEqual(broken.destroyed, 1)
        self.assertEqual(logged, ["tray menu drawn unavailable (OSError)"])
        fake = self.open(made)
        self.assertEqual(fake.tracked, 1)
        self.assertEqual(len(logged), 1, "said once")

    def test_an_opening_refused_the_foreground_is_windows_menu_that_once(self):
        made = icon()
        drawn = FakeDrawn(opens=False)
        made._hwnd, made._menu_drawn = 1, drawn
        self.assertEqual(self.open(made).tracked, 1)
        drawn.opens = True
        self.assertEqual(self.open(made).tracked, 0, "the next opening is drawn again")
        self.assertEqual(len(drawn.shown), 2)

    def test_the_drawn_menu_is_made_on_the_first_right_click_and_goes_with_the_icon(self):
        made = icon()
        made._hwnd = 1
        with unittest.mock.patch.object(popup, "Menu", lambda log: FakeDrawn()):
            self.open(made)
        drawn = made._menu_drawn
        self.assertIsInstance(drawn, FakeDrawn)
        made._drop_menu()
        self.assertEqual(drawn.destroyed, 1)
        self.assertIsNone(made._menu_drawn, "made again on the next right click")


# ------------------------------------------------------------------------------ keys, pointer, closing
def entries(**extra):
    return tray.menu_items({"enabled": True, "waiting": 2}, EN, NOW, True, extra.get("armed"))


class KeyTests(unittest.TestCase):
    def test_arrows_go_round_the_usable_items_and_never_land_on_the_status_or_a_line(self):
        items = entries()                   # status, line, Open, Show, Pause, line, Stop
        self.assertEqual(popup.menu_step(items, None), 2, "Down from nothing: the first")
        self.assertEqual(popup.menu_step(items, None, backwards=True), 6, "Up from nothing: the last")
        self.assertEqual(popup.menu_step(items, 4), 6, "over the line")
        self.assertEqual(popup.menu_step(items, 6), 2, "round from the end")
        self.assertEqual(popup.menu_step(items, 2, backwards=True), 6, "round from the start")
        self.assertEqual((popup.menu_end(items), popup.menu_end(items, last=True)), (2, 6))
        self.assertIsNone(popup.menu_step([None, {"id": 0, "text": "x", "enabled": False}], None))

    def test_a_letter_chooses_the_one_item_it_starts_and_steps_through_several(self):
        items = entries()
        self.assertEqual(popup.menu_letter(items, None, "o"), (2, True), "Open Dashboard, the only O")
        self.assertEqual(popup.menu_letter(items, None, "P"), (4, True))
        self.assertEqual(popup.menu_letter(items, None, "s"), (3, False), "Show and Stop: the first")
        self.assertEqual(popup.menu_letter(items, 3, "S"), (6, False), "then the next")
        self.assertEqual(popup.menu_letter(items, 6, "s"), (3, False), "and round")
        self.assertEqual(popup.menu_letter(items, 4, "x"), (4, False), "nothing starts with it")
        self.assertEqual(popup.menu_letter(items, 4, "2"), (4, False), "the status line cannot be chosen")


class BehaviourTests(unittest.TestCase):
    """The drawn menu's own handlers, with what draws it replaced: nothing here makes a window."""

    def setUp(self):
        self.chosen = []
        self.menu = popup.Menu()
        self.menu.entries = entries()
        self.menu.strings = dict(EN)
        self.menu.on_choose = self.chosen.append
        self.menu._plan = popup.menu_layout(self.menu.entries, 1.0, measure)
        self.menu.visible = True
        self.told = []
        for name, value in (("_push", lambda: None), ("_tell", self.told.append)):
            patcher = unittest.mock.patch.object(self.menu, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = unittest.mock.patch.object(access, "announce", lambda window, before, after: self.told.append(
            access.changes(before, after)))
        patcher.start()
        self.addCleanup(patcher.stop)

    def send(self, message, wparam=0, lparam=0):
        return self.menu._handle(message, wparam, lparam)

    def at(self, index, dx=4):
        rect = next(item["rect"] for item in self.menu._plan["items"] if item["index"] == index)
        return (rect[0] + dx) | ((rect[1] + 3) << 16)

    def test_down_and_enter_choose_the_item_and_close_first(self):
        self.send(menuwindow.WM_KEYDOWN, menuwindow.VK_DOWN)
        self.send(menuwindow.WM_KEYDOWN, menuwindow.VK_DOWN)
        self.assertEqual(self.menu.selected, 3)
        self.send(menuwindow.WM_KEYDOWN, menuwindow.VK_RETURN)
        self.assertEqual(self.chosen, [tray.MENU_PENDING])
        self.assertFalse(self.menu.visible)
        self.assertIn(menuwindow.EVENT_SYSTEM_MENUPOPUPEND, self.told)

    def test_home_end_and_up(self):
        self.send(menuwindow.WM_KEYDOWN, menuwindow.VK_END)
        self.assertEqual(self.menu.selected, 6)
        self.send(menuwindow.WM_KEYDOWN, menuwindow.VK_UP)
        self.assertEqual(self.menu.selected, 4)
        self.send(menuwindow.WM_KEYDOWN, menuwindow.VK_HOME)
        self.assertEqual(self.menu.selected, 2)
        self.assertEqual(self.chosen, [])

    def test_enter_with_nothing_in_hand_does_nothing(self):
        self.send(menuwindow.WM_KEYDOWN, menuwindow.VK_RETURN)
        self.assertEqual((self.chosen, self.menu.visible), ([], True))

    def test_esc_alt_and_f10_close_it_choosing_nothing(self):
        for message, key in ((menuwindow.WM_KEYDOWN, menuwindow.VK_ESCAPE),
                             (menuwindow.WM_SYSKEYDOWN, menuwindow.VK_MENU),
                             (menuwindow.WM_SYSKEYDOWN, menuwindow.VK_F10)):
            with self.subTest(key=key):
                self.menu.visible = True
                self.assertEqual(self.send(message, key), 0)
                self.assertFalse(self.menu.visible)
        self.assertEqual(self.chosen, [])

    def test_a_letter_chooses_or_moves(self):
        self.send(menuwindow.WM_CHAR, ord("s"))
        self.assertEqual((self.menu.selected, self.chosen), (3, []))
        self.send(menuwindow.WM_CHAR, ord("O"))
        self.assertEqual(self.chosen, [tray.MENU_OPEN])
        self.menu.visible = True
        self.send(menuwindow.WM_CHAR, 0x0D)                  # Enter's own character, after its key
        self.assertEqual(self.chosen, [tray.MENU_OPEN])

    def test_the_pointer_puts_an_item_in_hand_and_either_button_s_release_chooses_it(self):
        self.send(menuwindow.WM_MOUSEMOVE, 0, self.at(4))
        self.assertEqual(self.menu.selected, 4)
        self.send(menuwindow.WM_MOUSEMOVE, 0, self.at(0))
        self.assertIsNone(self.menu.selected, "the status line is never in hand")
        self.send(menuwindow.WM_LBUTTONUP, 0, self.at(0))
        self.assertEqual((self.chosen, self.menu.visible), ([], True), "nor chosen")
        self.send(menuwindow.WM_RBUTTONUP, 0, self.at(4))
        self.assertEqual(self.chosen, [tray.MENU_TOGGLE])
        self.menu.visible = True
        self.send(menuwindow.WM_LBUTTONUP, 0, self.at(6))
        self.assertEqual(self.chosen, [tray.MENU_TOGGLE, tray.MENU_STOP])

    def test_leaving_it_puts_nothing_in_hand(self):
        self.send(menuwindow.WM_MOUSEMOVE, 0, self.at(2))
        self.send(menuwindow.WM_MOUSELEAVE)
        self.assertIsNone(self.menu.selected)

    def test_a_click_elsewhere_and_losing_the_focus_close_it(self):
        self.assertEqual(self.send(menuwindow.WM_ACTIVATE, menuwindow.WA_INACTIVE), 0)
        self.assertFalse(self.menu.visible)
        for message, wparam in ((menuwindow.WM_ACTIVATEAPP, 0), (menuwindow.WM_CANCELMODE, 0)):
            self.menu.visible = True
            self.send(message, wparam)
            self.assertFalse(self.menu.visible, hex(message))
        self.menu.visible = True
        self.send(menuwindow.WM_LBUTTONDOWN, 0, 1 | (1 << 16))   # its shadow, outside the card
        self.assertFalse(self.menu.visible)
        self.menu.visible = True
        self.send(menuwindow.WM_LBUTTONDOWN, 0, self.at(2))
        self.assertTrue(self.menu.visible, "a press on the card is the start of a click on it")
        self.assertEqual(self.chosen, [])

    def test_a_screen_reader_hears_the_item_in_hand_move(self):
        self.menu._spoken = self.menu.accessible_items()
        self.send(menuwindow.WM_KEYDOWN, menuwindow.VK_DOWN)
        self.assertEqual(self.told[-1], [(access.EVENT_FOCUS, 3)], "Open Dashboard, the third child")

    def test_what_a_screen_reader_is_told_is_each_item_by_name_role_and_state(self):
        self.menu.selected = 4
        items = self.menu.accessible_items()
        self.assertEqual([(item["role"], item["name"]) for item in items],
                         [("menuitem", "2 waiting"), ("separator", ""), ("menuitem", EN["menu.open"]),
                          ("menuitem", EN["menu.pending"].replace("{n}", "2")), ("menuitem", EN["menu.pause"]),
                          ("separator", ""), ("menuitem", EN["menu.stop"])])
        self.assertEqual(items[0]["states"], ["unavailable"])
        self.assertEqual(items[4]["states"], ["focusable", "focused", "hot"])
        self.assertEqual(items[2]["states"], ["focusable"])
        self.assertEqual([item["target"] for item in items], [None, None, 2, 3, 4, None, 6])
        self.assertEqual(items[2]["action"], EN["popup.a11y_press"])
        for role in ("menu", "menuitem", "separator"):
            self.assertIn(role, access.A11Y_ROLES)
        self.menu.visible = False
        self.assertEqual(self.menu.accessible_items(), [], "nothing on screen is no child")


# ------------------------------------------------------------------------------ where, and which way
class PlacementTests(unittest.TestCase):
    WORK = (0, 0, 1920, 1040)

    def plan(self, rtl=False):
        laid = popup.menu_layout(entries(), 1.0, measure)
        return popup.menu_mirror(laid) if rtl else laid

    def card_at(self, plan, point, work=WORK):
        x, y = popup.menu_place(plan, point, work)
        card = plan["card"]
        return (x + card[0], y + card[1], x + card[2], y + card[3])

    def test_its_corner_is_at_the_pointer_opening_right_and_down(self):
        card = self.card_at(self.plan(), (300, 200))
        self.assertEqual(card[:2], (300, 200))

    def test_at_the_notification_area_it_turns_up_and_left_and_stays_in_the_work_area(self):
        for point in ((1900, 1060), (1915, 1035), (1919, 1079)):
            with self.subTest(point=point):
                left, top, right, bottom = self.card_at(self.plan(), point)
                self.assertLessEqual(right, 1920)
                self.assertLessEqual(bottom, 1040)
                self.assertGreaterEqual((left, top), (0, 0))
        self.assertEqual(self.card_at(self.plan(), (1900, 1000))[2:], (1900, 1000), "its far corner at the pointer")

    def test_right_to_left_it_opens_leftward_first(self):
        plan = self.plan(rtl=True)
        card = self.card_at(plan, (900, 200))
        self.assertEqual((card[2], card[1]), (900, 200))
        card = self.card_at(plan, (20, 200))
        self.assertEqual(card[0], 20, "no room to the left: rightward")

    def test_on_a_monitor_left_of_and_above_the_primary_one(self):
        work = (-1920, -1080, 0, -40)
        left, top, right, bottom = self.card_at(self.plan(), (-5, -45), work)
        self.assertTrue(-1920 <= left and right <= 0 and -1080 <= top and bottom <= -40)

    def test_a_menu_bigger_than_the_work_area_starts_at_its_corner(self):
        left, top, _, _ = self.card_at(self.plan(), (50, 50), (0, 0, 100, 60))
        self.assertEqual((left, top), (0, 0))

    def test_it_grows_with_the_scale_and_its_words_fit_at_every_scale(self):
        for scale in (1.0, 1.25, 1.5, 2.0, 3.0):
            with self.subTest(scale=scale):
                plan = popup.menu_layout(entries(armed="shut_down"), scale, lambda r, t, w, wr: (int(len(t) * 7 * scale),
                                                                                                 int(16 * scale)))
                for item in plan["items"]:
                    if item["kind"] == "item":
                        text = item["text_rect"]
                        self.assertGreaterEqual(text[2] - text[0], int(len(item["text"]) * 7 * scale))
                        self.assertTrue(plan["card"][0] < item["rect"][0] and item["rect"][2] < plan["card"][2])
                        radius = brand.RADII["card"] * scale
                        self.assertGreaterEqual(text[0] - plan["card"][0], radius, "words clear of the corner")
                        self.assertGreaterEqual(plan["card"][2] - text[2], radius)


class RightToLeftTests(unittest.TestCase):
    def test_every_rectangle_is_across_the_window_and_every_line_aligned_right(self):
        plan = popup.menu_layout(entries(), 1.0, measure)
        turned = popup.menu_mirror(plan)
        width = plan["size"][0]
        self.assertTrue(turned["rtl"])
        self.assertFalse(plan["rtl"])
        for before, after in zip(plan["items"], turned["items"]):
            for key in ("rect", "text_rect", "dot"):
                if key in before:
                    self.assertEqual(after[key], (width - before[key][2], before[key][1], width - before[key][0],
                                                  before[key][3]))
            if before["kind"] == "item":
                self.assertEqual((before["align"], after["align"]), ("left", "right"))
                self.assertTrue(after["rect"][0] <= after["dot"][0] and after["dot"][2] <= after["rect"][2])
                self.assertGreater(after["dot"][0], after["text_rect"][2], "the dot's column at the right")
        self.assertEqual([index for index, _ in turned["targets"]], [index for index, _ in plan["targets"]])


@unittest.skipUnless(os.name == "nt", "the drawn menu is a Windows window")
class LookTests(unittest.TestCase):
    """The renderer, drawing into memory: nothing is shown and nothing is captured."""

    def setUp(self):
        self.renderer = popup.MenuRenderer()
        self.addCleanup(self.renderer.close)

    def draw(self, theme="light", contrast=False, design="soft", locale="en", selected=None, scale=1.0):
        renderer = self.renderer
        renderer.theme, renderer.contrast, renderer.design = theme, contrast, design
        items = tray.menu_items({"enabled": True, "waiting": 2}, interface.STRINGS[locale], NOW, True, None)
        plan = renderer.menu_layout(items, scale, locale)
        canvas = renderer.draw_menu(plan, selected)
        return plan, canvas.pixels()

    @staticmethod
    def pixel(plan, pixels, x, y):
        index = (y * plan["size"][0] + x) * 4
        blue, green, red, alpha = pixels[index:index + 4]
        return (red, green, blue), alpha

    def ground(self, plan, pixels):
        card = plan["card"]
        stop = next(item for item in plan["items"] if item["kind"] == "item" and item["id"] == tray.MENU_STOP)
        return self.pixel(plan, pixels, (card[0] + card[2]) // 2, (stop["rect"][3] + card[3]) // 2)

    def test_the_card_is_the_popup_s_card_in_light_and_in_dark(self):
        for theme in ("light", "dark"):
            with self.subTest(theme=theme):
                plan, pixels = self.draw(theme)
                self.assertEqual(self.ground(plan, pixels), (brand.rgb(brand.card_ground(theme, "soft")), 255))
        self.assertNotEqual(self.ground(*self.draw("light")), self.ground(*self.draw("dark")))

    def test_its_lift_falls_outside_the_card_and_past_it_there_is_nothing(self):
        plan, pixels = self.draw("light")
        card = plan["card"]
        _, beside = self.pixel(plan, pixels, card[2] + 3, (card[1] + card[3]) // 2)
        self.assertGreater(beside, 0, "the shadow")
        self.assertEqual(self.pixel(plan, pixels, 0, 0)[1], 0, "the window's corner is nothing")
        self.assertEqual(self.pixel(plan, pixels, card[0] + 1, card[1] + 1)[1] < 255, True, "the card's round corner")

    def test_every_pixel_of_the_card_inside_its_corners_is_whole_words_and_all(self):
        """GDI's text clears the alpha of every pixel it draws; on a layered window that would be a hole in the card
        where every letter is."""
        for locale in ("en", "ko", "ar"):
            with self.subTest(locale=locale):
                plan, pixels = self.draw(locale=locale, selected=2)
                width = plan["size"][0]
                left, top, right, bottom = plan["card"]
                radius = int(brand.RADII["card"]) + 1
                holes = [(x, y) for y in range(top, bottom) for x in range(left + radius, right - radius)
                         if pixels[(y * width + x) * 4 + 3] != 255]
                self.assertEqual(holes[:5], [])

    def test_the_item_in_hand_rises_into_a_raised_pill(self):
        plan, idle = self.draw("light")
        _, held = self.draw("light", selected=2)
        item = next(item for item in plan["items"] if item.get("index") == 2)
        x, y = item["rect"][0] + 6, (item["rect"][1] + item["rect"][3]) // 2
        self.assertEqual(self.pixel(plan, held, x, y)[0], brand.rgb(brand.palette("light")["raised"]))
        self.assertNotEqual(self.pixel(plan, idle, x, y), self.pixel(plan, held, x, y))

    def test_high_contrast_is_system_colours_with_no_shadow(self):
        plan, pixels = self.draw(contrast=True, selected=2)
        card = plan["card"]
        self.assertEqual(self.ground(plan, pixels), (popup.system_rgb("Window"), 255))
        item = next(item for item in plan["items"] if item.get("index") == 2)
        self.assertEqual(self.pixel(plan, pixels, item["rect"][0] + 6, (item["rect"][1] + item["rect"][3]) // 2),
                         (popup.system_rgb("Highlight"), 255), "the item in hand in Highlight, as Windows' menus")
        outside = [self.pixel(plan, pixels, x, (card[1] + card[3]) // 2)[1] for x in range(card[2] + 1, plan["size"][0])]
        self.assertEqual(set(outside), {0}, "no shadow")

    def test_arabic_and_hebrew_are_laid_out_right_to_left_and_nothing_else_is(self):
        for locale in ("ar", "he", "en", "ko", "de"):
            with self.subTest(locale=locale):
                plan, _ = self.draw(locale=locale)
                self.assertEqual(plan["rtl"], locale in ("ar", "he"))


@unittest.skipUnless(os.name == "nt" and ctypes.sizeof(ctypes.c_void_p) == 8, "Windows' accessibility, 64-bit")
class LiveWindowTests(unittest.TestCase):
    """The real layered window, shown off every screen and never activated, read as a screen reader reads it."""

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
        self.chosen = []
        self.menu = popup.Menu()
        self.menu.create()
        self.addCleanup(self.menu.destroy)
        self.menu.entries, self.menu.strings, self.menu.on_choose = entries(), dict(EN), self.chosen.append
        self.menu._plan = self.menu._renderer.menu_layout(self.menu.entries, 1.0, "en")
        self.menu._origin = (-32000, -32000)
        self.menu._push()                                    # UpdateLayeredWindow, as an opening does
        user32 = ctypes.WinDLL("user32")
        user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user32.ShowWindow(self.menu.hwnd, 4)                 # SW_SHOWNOACTIVATE, off every screen
        self.menu.visible = True

    def client(self):
        found = ctypes.c_void_p()
        self.assertEqual(self.oleacc.AccessibleObjectFromWindow(self.menu.hwnd, access.OBJID_CLIENT,
                                                                ctypes.byref(access.IID_IACCESSIBLE),
                                                                ctypes.byref(found)), 0)
        self.addCleanup(lambda: ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(
            ctypes.cast(found, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0][2])(found))
        return found

    @staticmethod
    def call(pointer, slot, *types):
        table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
        return ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *types)(table[slot])

    @staticmethod
    def child(number):
        variant = access.VARIANT()
        variant.vt, variant.value.lVal = access.VT_I4, number
        return variant

    def text(self, pointer, slot, number):
        variant, out = self.child(number), ctypes.c_void_p()
        self.call(pointer, slot, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(
            pointer, ctypes.addressof(variant), ctypes.byref(out))
        value = ctypes.wstring_at(out.value) if out.value else None
        if out.value:
            self.oleaut.SysFreeString(out)
        return value

    def number(self, pointer, slot, number):
        variant, out = self.child(number), access.VARIANT()
        self.call(pointer, slot, ctypes.c_void_p, ctypes.POINTER(access.VARIANT))(
            pointer, ctypes.addressof(variant), ctypes.byref(out))
        return out.value.lVal

    def test_it_is_a_menu_whose_children_are_its_items_by_name_role_and_state(self):
        pointer = self.client()
        count = ctypes.c_long()
        self.call(pointer, 8, ctypes.POINTER(ctypes.c_long))(pointer, ctypes.byref(count))
        self.assertEqual(count.value, len(self.menu.entries))
        self.assertEqual(self.text(pointer, 10, 0), "Codex Auto Resume")
        self.assertEqual(self.number(pointer, 13, 0), access.A11Y_ROLES["menu"])
        for number, entry in enumerate(self.menu.entries, 1):
            with self.subTest(number=number):
                role = self.number(pointer, 13, number)
                state = self.number(pointer, 14, number)
                if entry is None:
                    self.assertEqual(role, access.A11Y_ROLES["separator"])
                    continue
                self.assertEqual(role, access.A11Y_ROLES["menuitem"])
                self.assertEqual(self.text(pointer, 10, number), entry["text"])
                self.assertEqual(bool(state & access.A11Y_STATES["unavailable"]), not entry["enabled"])

    def test_its_default_action_is_the_choice(self):
        pointer = self.client()
        variant = self.child(3)                              # Open Dashboard
        self.assertEqual(self.call(pointer, 25, ctypes.c_void_p)(pointer, ctypes.addressof(variant)), 0)
        self.assertEqual(self.chosen, [tray.MENU_OPEN])
        self.assertFalse(self.menu.visible)

    def test_the_layered_picture_is_taken_at_every_scale_and_theme(self):
        for scale, theme, contrast in ((1.0, "light", False), (1.5, "dark", False), (2.0, "light", True)):
            with self.subTest(scale=scale, theme=theme, contrast=contrast):
                self.menu._theme, self.menu.contrast = theme, contrast
                self.menu._plan = self.menu._renderer.menu_layout(self.menu.entries, scale, "en")
                self.menu._push()


if __name__ == "__main__":
    unittest.main()
