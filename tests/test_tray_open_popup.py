"""The icon's right-click menu offers Open the popup (v0.6.23; the owner, 2026-11-11: "트레이에서 아이콘 우클릭시 메뉴에 팝업
열기? 도 있으면 좋을 겉아").

One item right after Open Dashboard, in both ways the menu is shown - drawn in the product's design and Windows' own -
since both are built from the one list (ui/tray/menu.py menu_items). It opens the popup a left click on the icon opens:
the same popup object, made the way the click makes it, shown where the click shows it, and what the icon shows marked
seen as the click marks it. The right click that opened the menu closed the popup, so choosing the item opens it - never
the click's toggle, which would close one already open. It is offered only where the icon has a popup to open (a control
layer, and a popup that has not broken), as the left click opens one only there.

The menu chooses by an item's first letter; in most languages Open the popup starts with the letter Open Dashboard does
(English "O"), and then the letter steps between them, as Windows' menus do. What is held here is that the letter always
reaches the item, in every language.
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest
import unittest.mock

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from codex_auto_resume import interface  # noqa: E402
from codex_auto_resume.ui import popup, tray  # noqa: E402
from codex_auto_resume.ui.tray import menu as tray_menu  # noqa: E402

from test_tray_menu_drawn import FakeDrawn, FakeUser32, measure  # noqa: E402

EN = interface.STRINGS["en"]
NOW = 1_800_000_000.0


class FakePopup:
    """The popup as the icon drives it: what it was made with and every call it was given."""

    made = []

    def __init__(self, **given):
        self.given, self.calls, self.breaks = given, [], False
        FakePopup.made.append(self)

    def show(self, **given):
        self.calls.append(("show", given))
        if self.breaks:
            raise OSError("CreateWindowExW")

    def on_select(self, keyboard=False):
        self.calls.append(("on_select", keyboard))

    def hide(self):
        self.calls.append(("hide",))

    def destroy(self):
        self.calls.append(("destroy",))

    def set_strings(self, strings):
        pass


class FakeControl:
    def __init__(self):
        self.acknowledged = 0

    def power_view(self):
        return {"armed": None}

    def acknowledge_failure(self):
        self.acknowledged += 1
        return {"seen_at": NOW}


def icon(control=True, **calls):
    made = tray.Tray(strings=dict(EN), control=FakeControl() if control else None, on_pending=lambda: None, **calls)
    made._adopt_settings = lambda: None            # the stored language is not this test's
    made._theme_menu = lambda: None
    made._refresh = lambda: None                   # no icon to redraw
    return made


def ids(items):
    return [entry and entry["id"] for entry in items]


class ItemTests(unittest.TestCase):
    def test_it_is_right_after_open_dashboard(self):
        """Fails with the item reverted: menu_items takes no `popup` and the list has no MENU_POPUP."""
        items = tray.menu_items({"enabled": True, "waiting": 2}, EN, NOW, True, "sleep", True)
        self.assertEqual(ids(items), [tray.MENU_STATUS, None, tray.MENU_OPEN, tray.MENU_POPUP, tray.MENU_PENDING,
                                      tray.MENU_TOGGLE, tray.MENU_POWER_OFF, None, tray.MENU_STOP])
        entry = items[3]
        self.assertEqual((entry["text"], entry["enabled"], entry["checked"]), (EN["menu.open_popup"], True, False))
        self.assertEqual(EN["menu.open_popup"], "Open the popup")
        paused = tray.menu_items({"enabled": False}, EN, NOW, False, None, True)
        self.assertEqual(ids(paused), [tray.MENU_STATUS, None, tray.MENU_OPEN, tray.MENU_POPUP, tray.MENU_TOGGLE, None,
                                       tray.MENU_STOP])

    def test_without_a_popup_the_menu_is_what_it_was(self):
        for popup_there in (False,):
            items = tray.menu_items({"enabled": True, "waiting": 2}, EN, NOW, True, None, popup_there)
            self.assertNotIn(tray.MENU_POPUP, ids(items))
        self.assertEqual(tray.menu_items({"enabled": True}, EN, NOW), tray.menu_items({"enabled": True}, EN, NOW,
                                                                                      False, None, False))

    def test_its_own_command_and_every_language_has_its_words(self):
        self.assertEqual(tray.MENU_POPUP, 6)
        self.assertEqual(len({tray.MENU_STATUS, tray.MENU_OPEN, tray.MENU_TOGGLE, tray.MENU_STOP, tray.MENU_PENDING,
                              tray.MENU_POWER_OFF, tray.MENU_POPUP}), 7)
        self.assertEqual(interface.STRINGS["ko"]["menu.open_popup"], "팝업 열기")
        for locale, strings in interface.STRINGS.items():
            with self.subTest(locale=locale):
                self.assertTrue(strings.get("menu.open_popup", "").strip())
                if locale != "en":
                    self.assertNotEqual(strings["menu.open_popup"], EN["menu.open_popup"], "translated")

    def test_the_drawn_menu_and_windows_menu_have_it_alike(self):
        items = tray.menu_items({"enabled": True, "waiting": 1}, EN, NOW, True, None, True)
        fake = FakeUser32()
        with unittest.mock.patch.object(tray_menu, "_dll", lambda name: fake):
            icon()._native_menu(items)
        windows = [identifier for flags, identifier, _ in fake.appended if not flags & tray_menu.MF_SEPARATOR]
        plan = popup.menu_layout(items, 1.0, measure)
        drawn = [item["id"] for item in plan["items"] if item["kind"] == "item"]
        self.assertEqual(drawn, windows)
        self.assertIn(tray.MENU_POPUP, drawn)

    def test_its_letter_reaches_it_in_every_language(self):
        """Its first letter chooses it, or - where another item starts with that letter too - steps to it."""
        for locale, strings in interface.STRINGS.items():
            items = tray.menu_items({"enabled": True, "waiting": 2}, strings, NOW, True, "shut_down", True)
            target = ids(items).index(tray.MENU_POPUP)
            letter = items[target]["text"].lstrip()[:1]
            with self.subTest(locale=locale, letter=letter):
                current, reached = None, False
                for _ in range(len(items)):
                    current, chosen = popup.menu_letter(items, current, letter)
                    if current == target:
                        reached = True
                        break
                    self.assertFalse(chosen, "another item was chosen by the letter")
                self.assertTrue(reached)


class OfferedTests(unittest.TestCase):
    def shown(self, made):
        made._hwnd, made._menu_drawn = 1, FakeDrawn()
        made._menu()
        (entries, _, choose), = made._menu_drawn.shown
        return entries, choose

    def test_it_is_offered_where_a_left_click_opens_a_popup(self):
        entries, _ = self.shown(icon())
        self.assertIn(tray.MENU_POPUP, ids(entries))

    def test_not_without_a_control_layer_or_after_the_popup_broke(self):
        """Fails with the condition reverted: the menu offers an item that would open nothing."""
        entries, _ = self.shown(icon(control=False))
        self.assertNotIn(tray.MENU_POPUP, ids(entries))
        broken = icon()
        broken._popup_failed = True
        entries, _ = self.shown(broken)
        self.assertNotIn(tray.MENU_POPUP, ids(entries))


class OpensTests(unittest.TestCase):
    def setUp(self):
        FakePopup.made = []
        patcher = unittest.mock.patch.object(popup, "Popup", FakePopup)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_choosing_it_opens_the_popup_the_left_click_opens(self):
        """Fails with the command reverted: the choice reaches no action and no popup is made."""
        made = icon()
        made._act(tray.MENU_POPUP, False)
        window, = FakePopup.made
        self.assertEqual(window.calls, [("show", {})])
        self.assertIs(made._popup, window)
        made._select()                                   # the left click drives the same popup, not a second one
        self.assertEqual(FakePopup.made, [window])
        self.assertEqual(window.calls[-1], ("on_select", False))
        self.assertIs(window.given["control"], made.control)
        self.assertIs(window.given["on_dashboard"], made.on_dashboard)

    def test_made_by_the_click_it_is_shown_again_never_toggled_closed(self):
        made = icon()
        made._select()
        window, = FakePopup.made
        made._act(tray.MENU_POPUP, False)
        made._act(tray.MENU_POPUP, False)
        self.assertEqual(window.calls, [("on_select", False), ("show", {}), ("show", {})])
        self.assertNotIn(("hide",), window.calls)

    def test_from_the_drawn_menu_and_from_windows_menu(self):
        made = icon()
        _, choose = OfferedTests.shown(self, made)
        choose(tray.MENU_POPUP)
        self.assertEqual(FakePopup.made[0].calls, [("show", {})])
        native = icon()
        with unittest.mock.patch.object(tray_menu, "_dll", lambda name: FakeUser32(tray.MENU_POPUP)):
            native._menu()                               # no window of its own: Windows' menu, its choice acted on
        self.assertEqual(FakePopup.made[1].calls, [("show", {})])

    def test_what_the_icon_shows_is_seen_as_a_click_sees_it(self):
        made = icon()
        made._failed = True
        made._act(tray.MENU_POPUP, False)
        self.assertEqual(made.control.acknowledged, 1)
        quiet = icon()
        quiet._act(tray.MENU_POPUP, False)
        self.assertEqual(quiet.control.acknowledged, 0, "nothing shown, nothing to see")

    def test_a_popup_that_breaks_is_given_up_as_the_clicks_is(self):
        logged = []
        made = icon(log=logged.append)
        window = made._popup_for_click()
        window.breaks = True
        made._act(tray.MENU_POPUP, False)
        self.assertTrue(made._popup_failed)
        self.assertIsNone(made._popup)
        self.assertEqual(logged, ["tray popup unavailable (OSError)"])
        self.assertFalse(made._popup_can_open())

    def test_without_a_control_layer_nothing_is_made(self):
        made = icon(control=False)
        made._act(tray.MENU_POPUP, False)
        self.assertEqual(FakePopup.made, [])


if __name__ == "__main__":
    unittest.main()
