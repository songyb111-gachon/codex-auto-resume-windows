"""v0.6.4 in the notification-area popup.

Three decisions, each held here. The Theme setting: "system" follows Windows' app mode, a choice
of light or dark overrides it, High Contrast outranks both, and the popup's colours, shadows and
cached images follow whichever is in effect. The per-conversation switch sits at the bottom right of
its row, level with the last line of its label, and the label on the left wraps in what the switch
leaves - in every language, at every scale Windows offers, and with labels far longer than any
translation. And a language or theme stored while the watcher runs is what the popup and the
icon's menu show the next time they open, without the watcher being restarted.
"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import tempfile
import sys
import time
import unittest
import unittest.mock

from codex_auto_resume import brand, control, interface, l10n, settings, tray, tray_popup as popup
from codex_auto_resume.tray import menu  # the module the icon's menu is built in
from test_tray_popup import EN, NOW, OTHER_THREAD, STATUS, FakeControl, measure, row

SCALES = (1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5)
LONG_NAME = ("Refactor the onboarding flow so that the Korean, Japanese and German translations "
             "load before the first paint")
OFFSCREEN = (-32000, -32000)


def task_rows():
    return [row("a", "waiting_reset", "usage_limit", eligible=NOW + 3600, reset=NOW + 3600, name=LONG_NAME),
            row("b", eligible=NOW + 42, thread=OTHER_THREAD, name="Fix flaky CI"),
            row("c", eligible=NOW + 90, enabled=False, name=None, thread="0a1b2c3d-0001-7000-8000-000000000003")]


def inside(inner, outer):
    return outer[0] <= inner[0] and outer[1] <= inner[1] and inner[2] <= outer[2] and inner[3] <= outer[3]


def overlaps(one, other):
    return one[0] < other[2] and other[0] < one[2] and one[1] < other[3] and other[1] < one[3]


def task_parts(plan):
    """Each task row as drawn: its tile, chip, switch, label, hit rectangle and everything else on it."""
    items, hits = plan["items"], dict(plan["targets"])
    parts = []
    for switch in (item for item in items if item["kind"] == "switch"):
        panel = next(item for item in items if item["kind"] == "panel" and inside(switch["rect"], item["rect"]))
        chip = next(item for item in items if item["kind"] == "chip" and inside(item["rect"], panel["rect"]))
        label = next(item for item in items if item["kind"] == "text" and item["target"] == switch["target"])
        others = [item for item in items if item is not switch and item["kind"] not in ("panel", "focusable")
                  and "rect" in item and inside(item["rect"], panel["rect"])]
        parts.append({"panel": panel["rect"], "chip": chip["rect"], "switch": switch["rect"], "label": label,
                      "hit": hits[switch["target"]], "target": switch["target"], "others": others})
    return parts


def lengthen(vm, times):
    """Every task's label said `times` over, in its own language: far longer than any translation."""
    if times > 1:
        for task in vm["tasks"]:
            task["check_label"] = " ".join([task["check_label"]] * times)
    return vm


def restore_preferences(case):
    case.addCleanup(popup.set_theme, popup.THEME_SYSTEM)
    case.addCleanup(popup.set_reduce_motion, False)


# ---------------------------------------------------------------------------------- theme
class ThemeResolutionTests(unittest.TestCase):
    def setUp(self):
        restore_preferences(self)

    def test_the_choices_are_the_setting_s_choices(self):
        self.assertEqual(popup.THEME_CHOICES, settings.THEMES)
        self.assertEqual(popup.THEME_SYSTEM, settings.THEME_SYSTEM)
        for value in settings.THEMES:
            self.assertEqual(popup.theme_choice(value), value)
        for value in (None, "", "Dark", "auto", 1, True, ["dark"]):
            with self.subTest(value=value):
                self.assertEqual(popup.theme_choice(value), "system")

    def test_system_follows_windows_app_mode_and_only_an_explicit_dark_is_dark(self):
        self.assertEqual(popup.effective_theme("system", True), "light")
        self.assertEqual(popup.effective_theme("system", False), "dark")
        self.assertEqual(popup.effective_theme("system", None), "light")     # the value is missing
        self.assertEqual(popup.effective_theme("nonsense", False), "dark")    # read as system

    def test_a_choice_of_light_or_dark_wins_over_windows(self):
        for mode in (True, False, None):
            with self.subTest(apps_use_light=mode):
                self.assertEqual(popup.effective_theme("light", mode), "light")
                self.assertEqual(popup.effective_theme("dark", mode), "dark")

    def test_high_contrast_wins_over_every_choice(self):
        for choice in popup.THEME_CHOICES:
            for mode in (True, False, None):
                with self.subTest(choice=choice, apps_use_light=mode):
                    self.assertEqual(popup.appearance(choice, mode, contrast=True), "contrast")
                    self.assertEqual(popup.appearance(choice, mode), popup.effective_theme(choice, mode))

    def test_the_stored_theme_is_adopted_and_nonsense_is_system(self):
        popup.set_theme("dark")
        self.assertEqual(popup.theme_setting(), "dark")
        popup.set_theme("purple")
        self.assertEqual(popup.theme_setting(), "system")
        popup.adopt_settings({"theme": "light", "reduce_motion": True, "interface_language": "ko"})
        self.assertEqual(popup.theme_setting(), "light")
        self.assertIs(popup.theme._reduce_motion_setting, True)
        popup.adopt_settings(None)                                   # nothing to adopt changes nothing
        self.assertEqual(popup.theme_setting(), "light")

    def test_a_language_is_resolved_exactly_as_the_watcher_resolves_it(self):
        previous = l10n.preference()
        self.addCleanup(l10n.set_preference, previous)
        for choice in l10n.CHOICES + ("klingon", None, 7):
            with self.subTest(choice=choice):
                l10n.set_preference(choice)                          # what the watcher does
                self.assertEqual(popup.vocabulary(choice), interface.catalog())

    @unittest.skipUnless(os.name == "nt", "Windows' app mode is in the registry")
    def test_windows_app_mode_is_read_from_the_registry(self):
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, popup.PERSONALIZE_KEY) as key:
                value, kind = winreg.QueryValueEx(key, popup.APP_MODE_VALUE)
            expected = (value != 0) if kind == winreg.REG_DWORD else None
        except OSError:
            expected = None
        self.assertEqual(popup.apps_use_light_theme(), expected)


class DarkElevationTests(unittest.TestCase):
    """The popup's shadow images are brand's dark recipes, as the light ones are brand's light ones."""

    def test_the_dark_card_has_faded_into_the_canvas_by_the_window_s_edge(self):
        canvas = brand.rgb(brand.DARK["canvas"])
        for scale in SCALES:
            margin = round(popup.SHADOW_MARGIN * scale)
            for side in ("left", "top", "right", "bottom"):
                with self.subTest(scale=scale, side=side):
                    colour = brand.elevation_colour("card", side, margin, "canvas", theme="dark", scale=scale,
                                                    inside=False)
                    self.assertLess(max(abs(part - ground) for part, ground in zip(colour, canvas)), 1.0)

    def test_along_its_right_and_bottom_a_dark_lift_is_brand_s_model(self):
        for recipe, radius, body in (("card", brand.RADII["card"], (336, 400)),
                                     ("control", brand.RADII["control"], (148, 32))):
            outer = [shadow for shadow in brand.shadows(recipe, "dark") if not shadow.inset]
            for scale in (1.0, 1.5, 2.0):
                for side in ("right", "bottom"):
                    with self.subTest(recipe=recipe, scale=scale, side=side):
                        width, height = round(body[0] * scale), round(body[1] * scale)
                        worst = 0.0
                        for d in range(48):
                            colour = [float(part) for part in brand.rgb(brand.DARK["canvas"])]
                            for shadow in reversed(outer):
                                mask = popup.lift_coverage(width, height, radius * scale, shadow.blur * scale)
                                if side == "right":
                                    box = mask["width"] - 2 * mask["extent"]
                                    column = mask["extent"] + box + d - popup.shadow_step(shadow.dx * scale)
                                    inside_mask = 0 <= column < mask["width"]
                                    index = mask["centre"][1] * mask["width"] + column
                                else:
                                    box = mask["height"] - 2 * mask["extent"]
                                    line = mask["extent"] + box + d - popup.shadow_step(shadow.dy * scale)
                                    inside_mask = 0 <= line < mask["height"]
                                    index = line * mask["width"] + mask["centre"][0]
                                level = mask["coverage"][index] if inside_mask else 0
                                alpha = min(255, int(shadow.alpha * level + 0.5)) / 255.0
                                colour = [part + (tone - part) * alpha
                                          for part, tone in zip(colour, brand.rgb(brand.DARK[shadow.token]))]
                            model = brand.elevation_colour(recipe, side, d + 0.5, "canvas", theme="dark", scale=scale,
                                                           inside=False)
                            worst = max(worst, max(abs(part - want) for part, want in zip(colour, model)))
                        self.assertLess(worst, 1.5)

    def test_the_dark_card_s_top_light_and_the_dark_well_are_brand_s_inset_model(self):
        ground = brand.card_ground("dark")
        for recipe, fill, radius in (("card", ground, brand.RADII["card"]), ("inset", "inset", brand.RADII["control"])):
            inset = [shadow for shadow in brand.shadows(recipe, "dark") if shadow.inset]
            self.assertEqual(len(inset), 1)
            for scale in (1.0, 2.0):
                with self.subTest(recipe=recipe, scale=scale):
                    border = int(max(1.0, round(scale)))
                    width, height = round(146 * scale) - 2 * border, round(32 * scale) - 2 * border
                    worst = 0.0
                    for j in range(int(8 * scale)):
                        colour = [float(part) for part in brand.rgb(brand.DARK.get(fill, fill))]
                        for shadow in inset:
                            mask = popup.well_coverage(width, height, radius * scale - border, shadow.blur * scale,
                                                       shadow.dx * scale, shadow.dy * scale)
                            level = mask["coverage"][j * mask["width"] + mask["centre"][0]]
                            alpha = min(255, int(shadow.alpha * level + 0.5)) / 255.0
                            colour = [part + (tone - part) * alpha
                                      for part, tone in zip(colour, brand.rgb(brand.DARK[shadow.token]))]
                        model = brand.elevation_colour(recipe, "top", j + 0.5, fill, theme="dark", scale=scale,
                                                       inside=True)
                        worst = max(worst, max(abs(part - want) for part, want in zip(colour, model)))
                    self.assertLess(worst, 1.5)


# ------------------------------------------------------------------------- the task switch
class SwitchPlacementTests(unittest.TestCase):
    """The label on the left, wrapping; the switch at the row's bottom right, level with its last line."""

    LENGTHS = (1, 3)        # each language's own labels, and each said three times over

    def plans(self):
        rows = task_rows()
        for locale in l10n.LOCALES:
            strings = interface.STRINGS[locale]
            for scale in SCALES:
                for times in self.LENGTHS:
                    vm = lengthen(popup.view_model(rows, STATUS, strings, NOW, notice=strings["popup.stale"]), times)
                    yield locale, scale, times, vm, popup.layout(vm, scale, measure)

    def test_the_switch_is_at_the_row_s_inner_right_edge_under_the_chip(self):
        for locale, scale, times, _, plan in self.plans():
            row_pad = round(brand.SPACING["m"] * scale)
            for part in task_parts(plan):
                with self.subTest(locale=locale, scale=scale, times=times, target=part["target"][1][:1]):
                    left, top, right, bottom = part["switch"]
                    self.assertEqual(right, part["panel"][2] - row_pad)
                    self.assertEqual(right, part["chip"][2])
                    self.assertEqual((right - left, bottom - top), (round(brand.LAYOUT["switch_width"] * scale),
                                                                    round(brand.LAYOUT["switch_height"] * scale)))

    def test_the_switch_is_pinned_to_the_bottom_of_its_row_beside_the_label_s_last_line(self):
        line_h = measure("body", "Ag", 100, False)[1]
        lines_seen = set()
        for locale, scale, times, _, plan in self.plans():
            row_pad = round(brand.SPACING["m"] * scale)
            track_h = round(brand.LAYOUT["switch_height"] * scale)
            for part in task_parts(plan):
                label, switch, hit = part["label"]["rect"], part["switch"], part["hit"]
                lines = (label[3] - label[1]) // line_h
                lines_seen.add(lines)
                with self.subTest(locale=locale, scale=scale, times=times, lines=lines, target=part["target"][1][:1]):
                    # Level with the last line: centred on it, as it is on a one-line label.
                    self.assertLessEqual(abs(label[3] - line_h / 2.0 - (switch[1] + switch[3]) / 2.0), 0.5)
                    # Its bottom is the text block's bottom, lower only by the half of it that is taller
                    # than a line - and nothing on the row is lower than it: it closes the row.
                    self.assertGreaterEqual(switch[3], label[3])
                    self.assertLessEqual(switch[3] - label[3], -(-max(0, track_h - line_h) // 2))
                    self.assertEqual(switch[3], max(item["rect"][3] for item in part["others"] + [{"rect": switch}]))
                    self.assertEqual(switch[3], part["panel"][3] - row_pad)
                    self.assertEqual(hit[3], switch[3] + round(4 * scale))
                    # The label's top does not move with its length; one line of it is where it always was.
                    line_top = hit[1] + round(4 * scale)
                    self.assertEqual(label[1], line_top + max(0, (track_h - line_h) // 2))
                    if lines == 1:
                        self.assertEqual(switch[1], line_top + max(0, (line_h - track_h) // 2))
                    else:
                        self.assertGreater((switch[1] + switch[3]) / 2.0, label[1] + (lines - 1) * line_h)
        self.assertIn(1, lines_seen)
        self.assertGreaterEqual(max(lines_seen), 3, "no label wrapped far enough to tell its last line from the rest")

    def test_the_label_is_never_under_the_switch_in_any_language_at_any_scale(self):
        for locale, scale, times, _, plan in self.plans():
            row_pad = round(brand.SPACING["m"] * scale)
            for part in task_parts(plan):
                label, switch = part["label"], part["switch"]
                left, top, right, bottom = label["rect"]
                with self.subTest(locale=locale, scale=scale, times=times, target=part["target"][1][:1]):
                    self.assertEqual(left, part["panel"][0] + row_pad)
                    self.assertEqual(right, switch[0] - round(popup.SWITCH_GAP * scale))
                    self.assertLess(right, switch[0])
                    self.assertTrue(label["wrap"])
                    self.assertGreaterEqual(bottom - top, measure("body", label["text"], right - left, True)[1])
                    # Nothing else on the row - the name, the chip and its word, the status, the label -
                    # is under the switch, however far the label wraps.
                    for item in part["others"]:
                        self.assertFalse(overlaps(item["rect"], switch), item)
                    # Both inside the tile, with the tile's padding under them.
                    self.assertLessEqual(max(bottom, switch[3]), part["panel"][3] - row_pad)

    def test_a_label_far_longer_than_any_translation_wraps_and_the_row_grows(self):
        label = " ".join(["Automatically resume this task when the limit resets"] * 6)
        line_h = measure("body", "Ag", 100, False)[1]
        rows = task_rows()
        for scale in SCALES:
            with self.subTest(scale=scale):
                vm = popup.view_model(rows, STATUS, EN, NOW)
                for task in vm["tasks"]:
                    task["check_label"] = label
                plan = popup.layout(vm, scale, measure)
                parts = task_parts(plan)
                for part in parts:
                    rect, switch = part["label"]["rect"], part["switch"]
                    self.assertGreater(rect[3] - rect[1], 3 * line_h)
                    self.assertLess(rect[2], switch[0])
                    self.assertTrue(inside(rect, part["panel"]))
                    # The switch went down with the last line, past every line before it.
                    self.assertGreater((switch[1] + switch[3]) / 2.0, rect[1] + 3 * line_h)
                    self.assertLessEqual(abs(rect[3] - line_h / 2.0 - (switch[1] + switch[3]) / 2.0), 0.5)
                    self.assertTrue(inside(switch, part["panel"]))
                for above, below in zip(parts, parts[1:]):
                    self.assertLessEqual(above["panel"][3], below["panel"][1])

    def test_the_whole_line_is_still_one_target_with_room_for_its_focus_ring(self):
        for locale, scale, times, _, plan in self.plans():
            for part in task_parts(plan):
                with self.subTest(locale=locale, scale=scale, times=times, target=part["target"][1][:1]):
                    hit = part["hit"]
                    self.assertTrue(inside(part["switch"], hit))
                    self.assertTrue(inside(part["label"]["rect"], hit))
                    self.assertTrue(inside(hit, part["panel"]))
                    ring = next(item for item in plan["items"]
                                if item["kind"] == "focusable" and item["target"] == part["target"])
                    self.assertEqual(ring["rect"], hit)
                    self.assertEqual(popup.hit_test(plan["targets"], hit[0], hit[1]), part["target"])
                    self.assertEqual(popup.hit_test(plan["targets"], (part["switch"][0] + part["switch"][2]) // 2,
                                                    (part["switch"][1] + part["switch"][3]) // 2), part["target"])

    def test_the_keyboard_order_is_unchanged(self):
        for locale, scale, times, vm, plan in self.plans():
            with self.subTest(locale=locale, scale=scale, times=times):
                self.assertEqual(popup.focus_order(plan["targets"]),
                                 [("check", task["interruption_id"]) for task in vm["tasks"]]
                                 + [("toggle",), ("dashboard",)])

    def test_the_card_keeps_its_width_and_the_label_keeps_most_of_the_line(self):
        for locale, scale, times, _, plan in self.plans():
            card = plan["card"]
            row_pad = round(brand.SPACING["m"] * scale)
            with self.subTest(locale=locale, scale=scale, times=times):
                self.assertEqual(card[2] - card[0], round(popup.WIDTH * scale) - 2 * round(brand.SPACING["m"] * scale))
                for part in task_parts(plan):
                    content = part["panel"][2] - part["panel"][0] - 2 * row_pad
                    label = part["label"]["rect"]
                    self.assertGreaterEqual(label[2] - label[0], 0.75 * content)

    def test_a_busy_switch_is_still_drawn_in_its_place(self):
        model = popup.PopupModel(EN)
        model.apply_outcome(("read",), popup.perform(("read",), FakeControl(task_rows())), NOW)
        vm = model.view(NOW)
        action = model.action_for(("check", "b" * 64))
        self.assertTrue(model.begin(action))
        busy = model.view(NOW)
        before = {part["target"]: part["switch"] for part in task_parts(popup.layout(vm, 1.5, measure))}
        plan = popup.layout(busy, 1.5, measure)
        for part in task_parts(plan):
            self.assertEqual(part["switch"], before[part["target"]])
        flags = {item["target"]: item["busy"] for item in plan["items"] if item["kind"] == "switch"}
        self.assertEqual(flags, {("check", "a" * 64): False, ("check", "b" * 64): True, ("check", "c" * 64): False})


# ------------------------------------------------------------------ a stored change, next open
class SettingsControl(FakeControl):
    """The popup's fake control layer, with the settings of a real one in a scratch home."""

    def __init__(self, home, rows=(), status=STATUS):
        super().__init__(list(rows), status)
        self.real = control.Control(home)
        self.reads = 0

    def settings_path(self):
        return self.real.settings_path()

    def get_settings(self):
        self.reads += 1
        return self.real.get_settings()

    def store(self, **changes):
        before = self.real.settings_path().stat().st_mtime_ns if self.real.settings_path().exists() else None
        self.real.update_settings(changes)
        # A stamp is a modification time and a size; make sure a test never writes twice inside one tick.
        while before is not None and self.real.settings_path().stat().st_mtime_ns == before:
            time.sleep(0.01)
            self.real.update_settings(changes)


class FakeUser32:
    """Just enough of user32 for the icon's menu to be built and dismissed without being shown."""

    def __init__(self):
        self.items = []

    def CreatePopupMenu(self):
        return 1

    def AppendMenuW(self, menu, flags, identifier, text):
        self.items.append((identifier, text))

    def GetCursorPos(self, point):
        return 1

    def SetForegroundWindow(self, hwnd):
        return 1

    def TrackPopupMenu(self, *unused):
        return 0                                         # dismissed: nothing chosen

    def PostMessageW(self, *unused):
        return 1

    def DestroyMenu(self, menu):
        return 1


class NextOpenTests(unittest.TestCase):
    def setUp(self):
        restore_preferences(self)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.control = SettingsControl(Path(folder.name))
        self.control.store(interface_language="en", theme="system")
        self.logged = []
        self.icon = tray.Tray(strings=EN, control=self.control, log=self.logged.append)

    def test_a_new_language_and_theme_are_taken_up_by_the_icon_before_it_opens_anything(self):
        self.control.store(interface_language="ko", theme="dark", reduce_motion=True)
        self.icon._adopt_settings()
        self.assertEqual(self.icon.strings, interface.STRINGS["ko"])
        self.assertEqual(popup.theme_setting(), "dark")
        self.assertIs(popup.theme._reduce_motion_setting, True)
        self.control.store(interface_language="pt-BR", theme="light", reduce_motion=False)
        self.icon._adopt_settings()
        self.assertEqual(self.icon.strings, interface.STRINGS["pt-BR"])
        self.assertEqual(popup.theme_setting(), "light")
        self.assertIs(popup.theme._reduce_motion_setting, False)
        self.assertEqual(self.logged, [])

    def test_an_unchanged_file_is_not_read_again(self):
        self.icon._adopt_settings()
        reads = self.control.reads
        for _ in range(5):
            self.icon._adopt_settings()
        self.assertEqual(self.control.reads, reads)
        self.control.store(theme="dark")
        self.icon._adopt_settings()
        self.assertEqual(self.control.reads, reads + 1)

    def test_a_click_adopts_the_stored_language_before_the_popup_is_made(self):
        self.control.store(interface_language="de")
        seen = []
        with unittest.mock.patch.object(self.icon, "_popup_for_click", lambda: seen.append(dict(self.icon.strings))):
            self.icon._select()
            self.icon._double_click()
        self.assertEqual(seen, [interface.STRINGS["de"]] * 2)

    def test_the_menu_speaks_the_language_stored_when_it_opens(self):
        self.control.store(interface_language="ja")
        fake = FakeUser32()
        # The menu's look is MenuThemeTests' business; here Windows is never asked.
        with unittest.mock.patch.object(menu, "_dll", lambda name: fake), \
                unittest.mock.patch.object(menu, "prefer_app_mode", lambda mode: False):
            self.icon._menu()
        self.assertEqual(self.logged, [])
        ja = interface.STRINGS["ja"]
        texts = [text for _, text in fake.items if text]
        self.assertIn(ja["menu.open"], texts)
        self.assertIn(ja["menu.pause"], texts)
        self.assertIn(ja["menu.stop"], texts)
        self.assertNotIn(EN["menu.open"], texts)

    def test_an_unreadable_settings_file_costs_only_the_new_words(self):
        with unittest.mock.patch.object(self.control, "get_settings", side_effect=OSError("locked")):
            self.icon._settings_values = None
            self.icon._adopt_settings()
        self.assertEqual(self.icon.strings, EN)
        self.assertEqual(self.logged, ["tray settings read failed (OSError)"])

    def test_an_icon_without_a_settings_reader_changes_nothing(self):
        icon = tray.Tray(strings=EN, control=FakeControl([]), log=self.logged.append)
        popup.set_theme("dark")
        icon._adopt_settings()
        self.assertEqual((icon.strings, popup.theme_setting(), self.logged), (EN, "dark", []))
        tray.Tray(strings=EN)._adopt_settings()

    def test_the_icon_s_tooltip_is_rewritten_in_the_new_language(self):
        self.icon._last_tip = "Codex Auto Resume"
        self.control.store(interface_language="fr")
        self.icon._adopt_settings()
        self.assertIsNone(self.icon._last_tip)
        self.assertTrue(tray.tooltip({}, self.icon.strings, NOW).startswith(interface.STRINGS["fr"]["tray.title"]))


class RecordingUser32(FakeUser32):
    """The fake user32, noting when the menu is made, so a request can be put before or after it."""

    def __init__(self, events):
        super().__init__()
        self.events = events

    def CreatePopupMenu(self):
        self.events.append("menu")
        return 1


class MenuThemeTests(unittest.TestCase):
    """The right-click menu is Windows' own control, and Windows draws it light unless the process
    asks for dark. So it is asked for exactly when the popup beside it is dark, before the menu is
    made, and asked back when it is not; where Windows cannot be asked, the menu opens as it did."""

    def setUp(self):
        restore_preferences(self)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.control = SettingsControl(Path(folder.name))
        self.control.store(interface_language="en", theme="light")
        self.logged, self.events = [], []
        self.icon = tray.Tray(strings=EN, control=self.control, log=self.logged.append)
        self.light = True
        self.contrast = False
        for name, value in (("apps_use_light_theme", lambda: self.light), ("high_contrast", lambda: self.contrast)):
            patcher = unittest.mock.patch.object(popup, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def open_menu(self, answer=True):
        def prefer(mode):
            self.events.append(("prefer", mode))
            if isinstance(answer, Exception):
                raise answer
            return answer
        fake = RecordingUser32(self.events)
        with unittest.mock.patch.object(menu, "_dll", lambda name: fake), \
                unittest.mock.patch.object(menu, "prefer_app_mode", prefer):
            self.icon._menu()
        return [text for _, text in fake.items if text]

    def asked(self):
        asked = [event[1] for event in self.events if isinstance(event, tuple)]
        del self.events[:]
        return asked

    def test_dark_only_when_the_popup_is_dark(self):
        self.assertEqual([tray.menu_app_mode(look) for look in ("light", "dark", "contrast", None, "system")],
                         [tray.APP_MODE_DEFAULT, tray.APP_MODE_FORCE_DARK, tray.APP_MODE_DEFAULT,
                          tray.APP_MODE_DEFAULT, tray.APP_MODE_DEFAULT])
        self.assertEqual((tray.APP_MODE_DEFAULT, tray.APP_MODE_FORCE_DARK), (0, 2))

    def test_a_dark_theme_is_asked_for_before_the_menu_is_made_and_given_back_after(self):
        self.open_menu()
        self.assertEqual(self.events, ["menu"], "light is how Windows draws it already: nothing is asked")
        del self.events[:]
        self.control.store(theme="dark")
        self.open_menu()
        self.assertEqual(self.events, [("prefer", tray.APP_MODE_FORCE_DARK), "menu"])
        del self.events[:]
        self.open_menu()
        self.assertEqual(self.events, ["menu"], "asked once, not at every opening")
        del self.events[:]
        # Use system setting follows Windows' app mode, read when the menu opens.
        self.light = False
        self.control.store(theme="system")
        self.open_menu()
        self.assertEqual(self.asked(), [], "Windows in dark: the menu is already dark")
        self.light = True
        self.open_menu()
        self.assertEqual(self.asked(), [tray.APP_MODE_DEFAULT])
        self.light = False
        self.open_menu()
        self.assertEqual(self.asked(), [tray.APP_MODE_FORCE_DARK])
        # High Contrast outranks the theme, as it does in the popup.
        self.contrast = True
        self.open_menu()
        self.assertEqual(self.asked(), [tray.APP_MODE_DEFAULT])
        self.assertEqual(self.logged, [])

    def test_where_windows_cannot_be_asked_the_menu_opens_as_it_always_did(self):
        self.control.store(theme="dark")
        self.assertIn(EN["menu.open"], self.open_menu(answer=False))
        self.assertEqual(self.asked(), [tray.APP_MODE_FORCE_DARK])
        self.control.store(theme="light")
        self.assertIn(EN["menu.open"], self.open_menu(answer=False))
        self.assertEqual(self.asked(), [], "a Windows that cannot be asked is not asked again")
        self.assertEqual(self.logged, [])

    def test_a_request_that_fails_is_logged_once_and_costs_only_the_look(self):
        self.control.store(theme="dark")
        self.assertIn(EN["menu.open"], self.open_menu(answer=OSError("no such ordinal")))
        self.assertIn(EN["menu.pause"], self.open_menu(answer=OSError("no such ordinal")))
        self.assertEqual(self.asked(), [tray.APP_MODE_FORCE_DARK])
        self.assertEqual(self.logged, ["tray menu theme failed (OSError)"])

    def test_windows_is_asked_through_uxtheme_by_ordinal_and_only_from_windows_10_1903(self):
        calls = []

        class Export:
            def __init__(self, ordinal):
                self.ordinal = ordinal

            def __call__(self, *args):
                calls.append((self.ordinal, args, self.argtypes, self.restype))
                return 0

        class Uxtheme:
            def __getitem__(self, ordinal):
                return Export(ordinal)

        names = []

        def dll(name):
            names.append(name)
            return Uxtheme()

        with unittest.mock.patch.object(menu, "_dll", dll):
            for build, expected in ((17763, False), (18362, True), (26200, True)):
                version = unittest.mock.Mock(build=build)
                with self.subTest(build=build), \
                        unittest.mock.patch.object(sys, "getwindowsversion", lambda: version, create=True), \
                        unittest.mock.patch.object(os, "name", "nt"):
                    del calls[:], names[:]
                    self.assertIs(tray.prefer_app_mode(tray.APP_MODE_FORCE_DARK), expected)
                    if not expected:
                        self.assertEqual((calls, names), ([], []), "an older build's ordinal 135 is another function")
                        continue
                    self.assertEqual(set(names), {"uxtheme"})
                    self.assertEqual(calls, [
                        (tray.UXTHEME_SET_PREFERRED_APP_MODE, (tray.APP_MODE_FORCE_DARK,), (ctypes.c_int,), ctypes.c_int),
                        (tray.UXTHEME_FLUSH_MENU_THEMES, (), (), None)])
        self.assertEqual((tray.UXTHEME_SET_PREFERRED_APP_MODE, tray.UXTHEME_FLUSH_MENU_THEMES), (135, 136))
        with unittest.mock.patch.object(os, "name", "posix"):
            self.assertIs(tray.prefer_app_mode(tray.APP_MODE_FORCE_DARK), False)


# ------------------------------------------------------------------------------ Windows
def pixel_reader(canvas, width):
    pixels = canvas.pixels()

    def pixel(x, y):
        index = (y * width + x) * 4
        return pixels[index + 2], pixels[index + 1], pixels[index]
    return pixel


def darker(one, other):
    return all(part < reference for part, reference in zip(one, other))


@unittest.skipUnless(os.name == "nt", "the popup is a Windows window")
class DarkRendererTests(unittest.TestCase):
    def setUp(self):
        self.renderer = popup.Renderer()
        self.addCleanup(self.renderer.close)

    def draw(self, theme, scale=1.0, contrast=False, status=STATUS):
        self.renderer.theme, self.renderer.contrast = theme, contrast
        vm = popup.view_model(task_rows(), status, EN, NOW)
        plan = self.renderer.layout(vm, scale, "en")
        canvas = self.renderer.draw(vm, plan, frame=popup.halo(vm["state"], 0))
        return vm, plan, pixel_reader(canvas, plan["size"][0])

    def test_a_dark_frame_is_drawn_in_the_dark_palette_on_the_panel_s_dark_card(self):
        vm, plan, pixel = self.draw("dark")
        dark = {token: brand.rgb(value) for token, value in brand.DARK.items()}
        ground = brand.rgb(brand.card_ground("dark"))
        card = plan["card"]
        middle_x, middle_y = (card[0] + card[2]) // 2, (card[1] + card[3]) // 2
        self.assertEqual(pixel(1, 1), dark["canvas"])
        self.assertEqual(pixel(card[0] + 30, card[1] + 6), ground)
        # The one-pixel top light inside the border, as brand says it is.
        top_light = brand.elevation_colour("card", "top", 0.5, brand.card_ground("dark"), theme="dark", inside=True)
        self.assertLessEqual(max(abs(part - want) for part, want in zip(pixel(middle_x, card[1] + 1), top_light)), 1.5)
        self.assertGreater(sum(pixel(middle_x, card[1] + 1)), sum(ground))
        # A drop below the card, and next to nothing beside it - each as brand's model says.
        self.assertTrue(darker(pixel(middle_x, card[3] + 4), dark["canvas"]))
        for x, y, side, d in ((middle_x, card[3] + 4, "bottom", 4.5), (card[0] - 12, middle_y, "left", 11.5)):
            model = brand.elevation_colour("card", side, d, "canvas", theme="dark", inside=False)
            self.assertLessEqual(max(abs(part - want) for part, want in zip(pixel(x, y), model)), 1.5, side)
        left, top, right, bottom = dict(plan["targets"])[("dashboard",)]
        self.assertEqual(pixel(left + 6, (top + bottom) // 2), dark["accent"])
        left, top, right, bottom = dict(plan["targets"])[("toggle",)]
        self.assertEqual(pixel(left + 6, (top + bottom) // 2), dark["raised"])
        # A switch that is off is a dark well: shaded along the inside of its top.
        off = next(item for item in plan["items"] if item["kind"] == "switch" and not item["checked"])
        left, top, right, bottom = off["rect"]
        self.assertEqual(pixel(left + 25, (top + bottom) // 2), dark["inset"])
        self.assertLess(sum(pixel(left + 25, top + 1)), sum(dark["inset"]) - 10)
        on = next(item for item in plan["items"] if item["kind"] == "switch" and item["checked"])
        self.assertEqual(pixel(on["rect"][0] + 4, (on["rect"][1] + on["rect"][3]) // 2), dark["accent"])
        halo = next(item for item in plan["items"] if item["kind"] == "halo")
        self.assertEqual(pixel(int(halo["cx"]), int(halo["cy"])), dark[brand.status_fill(vm["state"])])

    def test_high_contrast_wins_over_dark(self):
        _, plan, pixel = self.draw("dark", contrast=True)
        card = plan["card"]
        self.assertEqual(pixel(1, 1), popup.system_rgb("Control"))
        self.assertEqual(pixel(card[0] + 30, card[1] + 3), popup.system_rgb("Window"))
        self.assertEqual(pixel(card[2] + 5, (card[1] + card[3]) // 2), popup.system_rgb("Control"))

    def test_the_ground_and_every_shadow_image_are_kept_by_theme(self):
        for scale in (1.0, 2.0):
            with self.subTest(scale=scale):
                _, plan, _ = self.draw("light", scale)
                first = self.renderer.canvas.pixels()
                self.assertEqual(self.renderer._ground_key[2], "light")
                self.assertTrue(self.renderer._images)
                self.assertEqual({key[1] for key in self.renderer._images}, {"light"})
                _, _, pixel = self.draw("dark", scale)
                self.assertEqual(self.renderer._ground_key[2], "dark")
                self.assertEqual({key[1] for key in self.renderer._images}, {"dark"})
                self.assertEqual(pixel(1, 1), brand.rgb(brand.DARK["canvas"]))
                self.draw("light", scale)
                self.assertEqual(self.renderer.canvas.pixels(), first)

    def test_one_mask_in_two_themes_is_two_images(self):
        mask = popup.lift_coverage(148, 32, 11, 6)
        shadow = brand.Shadow(0, 1, 2, "shadow_dark", 0.6, False)
        self.renderer.theme = "light"
        light = self.renderer._image(mask, shadow)
        self.renderer.theme = "dark"
        dark = self.renderer._image(mask, shadow)
        self.assertIsNot(light, dark)
        self.assertIs(self.renderer._image(mask, shadow), dark)
        solid = mask["centre"][1] * mask["width"] + mask["centre"][0]
        self.assertEqual(mask["coverage"][solid], 255)
        self.assertNotEqual(bytes(light._pixels[solid * 4:solid * 4 + 3]), bytes(dark._pixels[solid * 4:solid * 4 + 3]))

    def test_flipping_the_theme_all_day_holds_no_more_images(self):
        before = popup.gdiplus_objects()
        held = []
        for _ in range(6):
            self.draw("dark", 1.5)
            self.draw("light", 1.5)
            held.append(popup.gdiplus_objects() - before)
        self.assertEqual(len(set(held)), 1, held)
        self.renderer.close()
        self.assertEqual(popup.gdiplus_objects(), before)

    def test_every_label_fits_its_column_as_gdi_measures_it(self):
        rows = task_rows()
        for locale in l10n.LOCALES:
            strings = interface.STRINGS[locale]
            for scale in SCALES:
                for times in SwitchPlacementTests.LENGTHS:
                    vm = lengthen(popup.view_model(rows, STATUS, strings, NOW), times)
                    plan = self.renderer.layout(vm, scale, locale)
                    line_h = self.renderer.measure("body", "Ag", 100, False)[1]
                    for part in task_parts(plan):
                        left, top, right, bottom = part["label"]["rect"]
                        switch = part["switch"]
                        width, height = self.renderer.measure("body", part["label"]["text"], right - left, True)
                        with self.subTest(locale=locale, scale=scale, times=times, target=part["target"][1][:1]):
                            self.assertLessEqual(width, right - left)
                            self.assertLessEqual(height, bottom - top)
                            self.assertLess(right, switch[0])
                            # GDI's lines are all one height, so the last of them is the bottom one...
                            self.assertEqual(height % line_h, 0)
                            # ...and the switch is level with it and closes the row, over nothing else on it.
                            self.assertLessEqual(abs(bottom - line_h / 2.0 - (switch[1] + switch[3]) / 2.0), 0.5)
                            self.assertEqual(switch[3], max([switch[3]] + [item["rect"][3] for item in part["others"]]))
                            for item in part["others"]:
                                self.assertFalse(overlaps(item["rect"], switch), item)

    def test_as_drawn_the_label_s_last_line_is_beside_the_switch_in_both_themes(self):
        """The pixels, not the plan: GDI draws the label's lines where the layout measured them, so its
        lowest ink is level with the switch and the lines above it are drawn above the switch."""
        rows = task_rows()
        for theme in ("light", "dark"):
            for locale in ("en", "ko", "de"):
                for scale in (1.0, 2.0):
                    self.renderer.theme, self.renderer.contrast = theme, False
                    vm = lengthen(popup.view_model(rows, STATUS, interface.STRINGS[locale], NOW), 3)
                    plan = self.renderer.layout(vm, scale, locale)
                    canvas = self.renderer.draw(vm, plan, frame=popup.halo(vm["state"], 0))
                    pixels, width = canvas.pixels(), plan["size"][0]
                    tile = brand.rgb(popup.tile_ground(theme))       # v0.6.5: the tile's own ground

                    def blank(y, x0, x1):
                        """Whether a run of pixels on line `y` is the tile's own colour and nothing else."""
                        run = pixels[(y * width + x0) * 4:(y * width + x1) * 4]
                        return all(run[channel::4] == bytes((tile[2 - channel],)) * (x1 - x0) for channel in range(3))

                    for part in task_parts(plan):
                        left, top, right, bottom = part["label"]["rect"]
                        switch = part["switch"]
                        inked = [y for y in range(top, bottom) if not blank(y, left, right)]
                        with self.subTest(theme=theme, locale=locale, scale=scale, target=part["target"][1][:1]):
                            self.assertTrue(inked)
                            self.assertLess(min(inked), switch[1])               # the lines above it...
                            self.assertGreaterEqual(max(inked), switch[1])       # ...and the last one beside it
                            self.assertLess(max(inked), switch[3])
                            # Nothing is drawn in the gap between the label's column and the switch.
                            gap = [y for y in range(switch[1], switch[3]) if not blank(y, right, switch[0] - 2)]
                            self.assertEqual(gap, [])


@unittest.skipUnless(os.name == "nt", "the popup is a Windows window")
class PopupThemeTests(unittest.TestCase):
    def setUp(self):
        restore_preferences(self)
        self.mode = {"light": False}
        patcher = unittest.mock.patch.object(popup.theme, "apps_use_light_theme", lambda: self.mode["light"])
        patcher.start()
        self.addCleanup(patcher.stop)
        contrast = unittest.mock.patch.object(popup.theme, "high_contrast", lambda: False)
        contrast.start()
        self.addCleanup(contrast.stop)

    def pump(self, seconds=0.05):
        user32 = ctypes.WinDLL("user32")
        user32.PeekMessageW.argtypes = [ctypes.POINTER(tray.MSG), ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint,
                                        ctypes.c_uint]
        user32.TranslateMessage.argtypes = [ctypes.POINTER(tray.MSG)]
        user32.DispatchMessageW.argtypes = [ctypes.POINTER(tray.MSG)]
        message = tray.MSG()
        deadline = time.monotonic() + seconds
        while True:
            while user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 1):
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
            if time.monotonic() >= deadline:
                return
            time.sleep(0.005)

    def window(self, fake=None, strings=EN):
        window = popup.Popup(control=fake or FakeControl(task_rows()), strings=strings)
        window.create()
        self.addCleanup(window.destroy)
        window.model.apply_outcome(("read",), popup.perform(("read",), window.control), time.time())
        return window

    def corner(self, window):
        canvas = window.render()
        return pixel_reader(canvas, canvas.width)(1, 1)

    def test_system_follows_windows_and_a_choice_overrides_it_on_the_next_frame(self):
        window = self.window()
        window.show(activate=False, origin=OFFSCREEN)
        self.pump(0.1)
        self.assertEqual(window._theme, "dark")
        self.assertEqual(self.corner(window), brand.rgb(brand.DARK["canvas"]))
        popup.set_theme("light")
        window._update()
        self.assertEqual(window._theme, "light")
        self.assertEqual(self.corner(window), brand.rgb(brand.LIGHT["canvas"]))
        self.mode["light"] = True
        popup.set_theme("dark")
        window.hide()
        window.show(activate=False, origin=OFFSCREEN)
        self.pump(0.1)
        self.assertEqual(self.corner(window), brand.rgb(brand.DARK["canvas"]))

    def test_windows_changing_its_app_mode_repaints_an_open_popup(self):
        user32 = ctypes.WinDLL("user32")
        user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
        window = self.window()
        window.show(activate=False, origin=OFFSCREEN)
        self.pump(0.1)
        self.assertEqual(self.corner(window), brand.rgb(brand.DARK["canvas"]))
        self.mode["light"] = True
        user32.SendMessageW(window.hwnd, popup.WM_SETTINGCHANGE, 0, 0)
        self.assertEqual(window._theme, "light")
        self.assertTrue(window._static_dirty)
        self.assertEqual(self.corner(window), brand.rgb(brand.LIGHT["canvas"]))
        self.assertIs(window._framed_dark, False)

    def test_high_contrast_wins_in_the_window_too(self):
        popup.set_theme("dark")
        with unittest.mock.patch.object(popup.theme, "high_contrast", lambda: True):
            window = self.window()
            window.show(activate=False, origin=OFFSCREEN)
            self.pump(0.1)
            self.assertTrue(window._renderer.contrast)
            self.assertEqual(self.corner(window), popup.system_rgb("Control"))
            self.assertIs(window._framed_dark, False)

    def test_a_read_that_carries_new_settings_changes_an_open_popup(self):
        stored = dict(settings.defaults(), interface_language="ko", theme="light", reduce_motion=True)
        fake = FakeControl(task_rows(), dict(STATUS, settings=stored))
        window = self.window(fake)
        window.show(activate=False, origin=OFFSCREEN)
        deadline = time.monotonic() + 3
        while window.locale != "ko" and time.monotonic() < deadline:
            self.pump(0.02)
        self.assertEqual(window.locale, "ko")
        self.assertEqual(window._vm["dashboard_text"], interface.STRINGS["ko"]["popup.open_dashboard"])
        self.assertEqual(window._theme, "light")
        self.assertTrue(window._reduced)
        self.assertFalse(window._frame_running)

    def test_an_icon_that_already_made_its_popup_opens_it_in_the_new_language_and_theme(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        fake = SettingsControl(Path(folder.name), task_rows())
        fake.store(interface_language="en", theme="light")
        icon = tray.Tray(strings=EN, control=fake)
        icon._adopt_settings()
        window = icon._popup_for_click()
        self.addCleanup(window.destroy)
        window.show(activate=False, origin=OFFSCREEN)
        self.pump(0.1)
        self.assertEqual((window.locale, window._theme), ("en", "light"))
        window.hide()
        fake.store(interface_language="de", theme="dark")
        icon._adopt_settings()                   # what a click does first
        window.show(activate=False, origin=OFFSCREEN)
        self.pump(0.1)
        self.assertEqual((window.locale, window._theme), ("de", "dark"))
        self.assertEqual(window._vm["toggle_text"], interface.STRINGS["de"]["action.pause"])
        self.assertIs(icon._popup, window)       # the same popup, and no watcher restarted
        self.assertEqual(self.corner(window), brand.rgb(brand.DARK["canvas"]))


if __name__ == "__main__":
    unittest.main()
