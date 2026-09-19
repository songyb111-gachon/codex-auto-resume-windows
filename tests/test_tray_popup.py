"""The notification-area mini-dashboard.

What it says, in what order, where it goes, what a click on it means and how it moves are
pure functions, tested on every platform. What it may never do - act on a task it did not
draw, change anything when the control layer refuses, reach anything that submits - is
asserted against a fake control layer and against the module's own source. The real
window, its renderer and its icon badge are exercised on Windows, where a leaked GDI or
USER object would show in the process's resource counts.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import os
from pathlib import Path
import re
import time
import unittest
import unittest.mock

from codex_auto_resume import brand, control, interface, l10n, tray, tray_popup as popup

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "codex_auto_resume" / "tray_popup.py"
NOW = 1_800_000_000.0
THREAD = "0a1b2c3d-0001-7000-8000-000000000001"
OTHER_THREAD = "0a1b2c3d-0001-7000-8000-000000000002"
EN = interface.STRINGS["en"]
STATUS = {"enabled": True, "watcher_running": True,
          "watcher": {"running": True, "ticking": True, "engine_state": "verified"}}


def row(key, state="waiting_retry", category="network_transient", *, eligible=None, reset=None,
        thread=THREAD, enabled=True, name="A task", overlays=(), detected=0.0, **extra):
    record = {"interruption_id": key * 64, "thread_id": thread, "state": state, "category": category,
              "eligible_at": eligible, "reset_at": reset, "next_retry_at": eligible,
              "thread_enabled": enabled, "name": name, "overlays": list(overlays),
              "detected_at": detected}
    record.update(extra)
    return record


def measure(role, text, width, wrap):
    """A stand-in for DrawTextW: fixed advance per character, line height from the size."""
    size = popup.ROLES[role][0]
    advance = size * 0.55
    line = int(size * 1.4)
    natural = int(len(text) * advance)
    if not wrap:
        return natural, line
    per_line = max(1, int(width // advance))
    lines = max(1, -(-len(text) // per_line))
    return min(natural, int(width)), lines * line


class FakeControl:
    """The four calls the popup may make, recorded, with a refusal on request."""

    def __init__(self, rows, status=STATUS, refuse=None, explode=False):
        self.rows = [dict(item) for item in rows]
        self.status = copy.deepcopy(status)
        self.refuse = refuse
        self.explode = explode
        self.calls = []

    def list_pending(self, include_terminal=False, source=None):
        self.calls.append(("list_pending", source))
        return [dict(item) for item in self.rows]

    def get_status(self):
        self.calls.append(("get_status",))
        return copy.deepcopy(self.status)

    def set_enabled(self, enabled):
        self.calls.append(("set_enabled", enabled))
        self._maybe_refuse()
        self.status["enabled"] = enabled
        return {"enabled": enabled}

    def set_interruption_recovery(self, interruption_id, thread_id, enabled, *, actor="gui"):
        self.calls.append(("set_interruption_recovery", interruption_id, thread_id, enabled))
        self._maybe_refuse()
        for item in self.rows:
            if item["thread_id"] == thread_id:
                item["thread_enabled"] = enabled
        return {"interruption_id": interruption_id, "thread_id": thread_id, "enabled": enabled,
                "state": "waiting_retry"}

    def _maybe_refuse(self):
        if self.explode:
            raise RuntimeError("the store went away")
        if self.refuse:
            raise control.ControlError("refused", code=self.refuse)


def opened(fake, strings=EN, now=NOW):
    model = popup.PopupModel(strings)
    model.apply_outcome(("read",), popup.perform(("read",), fake), now)
    return model, model.view(now)


# ------------------------------------------------------------------------------ wording
class ViewModelTests(unittest.TestCase):
    def test_most_urgent_first_and_the_counts_match(self):
        rows = [row("a", eligible=NOW + 900), row("b", state="queued"), row("c", eligible=NOW + 42),
                row("d", state="waiting_for_app")]
        vm = popup.view_model(rows, STATUS, EN, NOW)
        self.assertEqual([task["interruption_id"][0] for task in vm["tasks"]], ["b", "c", "a"])
        self.assertEqual([value for _, value in vm["counts"]], ["3", "1", "42s"])
        self.assertEqual([label for label, _ in vm["counts"]],
                         [EN["popup.count_waiting"], EN["popup.count_recovering"], EN["popup.next_check"]])

    def test_a_usage_limit_counts_down_to_its_reset_and_offers_to_resume(self):
        vm = popup.view_model([row("a", "waiting_reset", "usage_limit", eligible=NOW + 3725, reset=NOW + 3725)],
                              STATUS, EN, NOW)
        task = vm["tasks"][0]
        self.assertEqual(task["status"], EN["popup.until_reset"].replace("{time}", "1:02:05"))
        self.assertEqual(task["check_label"], EN["popup.resume_usage"])
        self.assertEqual(task["reason"], EN["reason.usage_limit"])
        self.assertEqual(task["tone"], "waiting")

    def test_every_other_interruption_counts_down_to_its_retry(self):
        for category in ("network_transient", "rate_limit_transient", "timeout", "server_5xx",
                         "stream_interrupted", "auth_service_transient"):
            with self.subTest(category):
                task = popup.view_model([row("a", category=category, eligible=NOW + 65)], STATUS, EN, NOW)["tasks"][0]
                self.assertEqual(task["status"], EN["popup.until_retry"].replace("{time}", "1:05"))
                self.assertEqual(task["check_label"], EN["popup.resume_transient"])
                self.assertEqual(task["reason"], EN["reason." + category])

    def test_reaching_zero_only_says_the_watcher_looks_again(self):
        vm = popup.view_model([row("a", eligible=NOW - 5)], STATUS, EN, NOW)
        self.assertEqual(vm["tasks"][0]["status"], EN["popup.until_retry"].replace("{time}", "0s"))
        self.assertEqual(vm["zero_note"], EN["popup.zero_note"])
        self.assertIsNone(popup.view_model([row("a", eligible=NOW + 5)], STATUS, EN, NOW)["zero_note"])

    def test_three_tasks_at_most_and_the_rest_are_counted(self):
        rows = [row(key, eligible=NOW + index) for index, key in enumerate("abcde")]
        vm = popup.view_model(rows, STATUS, EN, NOW)
        self.assertEqual(len(vm["tasks"]), popup.MAX_TASKS)
        self.assertEqual(vm["more"], EN["popup.more"].replace("{n}", "2"))
        self.assertIsNone(popup.view_model(rows[:3], STATUS, EN, NOW)["more"])

    def test_nothing_waiting_says_so_and_a_list_not_yet_read_says_nothing(self):
        empty = popup.view_model([], STATUS, EN, NOW)
        self.assertEqual(empty["empty"], EN["popup.nothing"])
        self.assertEqual([value for _, value in empty["counts"]], ["0", "0", "—"])
        unknown = popup.view_model(None, None, EN, NOW)
        self.assertIsNone(unknown["empty"])
        self.assertEqual([value for _, value in unknown["counts"]], ["—"] * 3)
        self.assertIsNone(unknown["paused"])

    def test_only_the_name_is_taken_from_the_conversation(self):
        rows = [row("a", name="Line one\nline two", project="secret-project", cwd_basename="secret-dir"),
                row("b", name=None, eligible=NOW + 1)]
        vm = popup.view_model(rows, STATUS, EN, NOW)
        self.assertEqual(vm["tasks"][0]["name"], EN["msg.toast_unnamed"])
        self.assertEqual(vm["tasks"][1]["name"], "Line one line two")
        self.assertNotIn("secret", repr(vm))

    def test_a_conversation_switched_off_is_unchecked_and_quiet(self):
        task = popup.view_model([row("a", enabled=False, eligible=NOW + 5)], STATUS, EN, NOW)["tasks"][0]
        self.assertFalse(task["checked"])
        self.assertEqual(task["tone"], "paused")

    def test_paused_offers_resume_and_running_offers_pause(self):
        self.assertEqual(popup.view_model([], dict(STATUS, enabled=False), EN, NOW)["toggle_text"], EN["action.resume"])
        self.assertEqual(popup.view_model([], STATUS, EN, NOW)["toggle_text"], EN["action.pause"])

    def test_every_word_comes_from_the_catalog_in_each_language(self):
        for locale in ("en", "ko", "ja", "de"):
            strings = interface.STRINGS[locale]
            with self.subTest(locale):
                rows = [row("a", "waiting_reset", "usage_limit", eligible=NOW + 60, reset=NOW + 60),
                        row("b", eligible=NOW + 120, thread=OTHER_THREAD)]
                vm = popup.view_model(rows, STATUS, strings, NOW)
                self.assertEqual(vm["title"], strings["tray.title"])
                self.assertEqual(vm["state_text"], strings["activity.waiting"])
                self.assertEqual([label for label, _ in vm["counts"]],
                                 [strings["popup.count_waiting"], strings["popup.count_recovering"],
                                  strings["popup.next_check"]])
                usage, transient = vm["tasks"]
                self.assertEqual(usage["status"], strings["popup.until_reset"].replace("{time}", "1:00"))
                self.assertEqual(usage["check_label"], strings["popup.resume_usage"])
                self.assertEqual(usage["reason"], strings["reason.usage_limit"])
                self.assertEqual(transient["status"], strings["popup.until_retry"].replace("{time}", "2:00"))
                self.assertEqual(transient["check_label"], strings["popup.resume_transient"])
                self.assertEqual(vm["toggle_text"], strings["action.pause"])
                self.assertEqual(vm["dashboard_text"], strings["popup.open_dashboard"])
                self.assertEqual(popup.view_model([], STATUS, strings, NOW)["empty"], strings["popup.nothing"])

    def test_an_empty_vocabulary_still_speaks_english(self):
        vm = popup.view_model([row("a", eligible=NOW + 5)], STATUS, {}, NOW)
        self.assertEqual(vm["dashboard_text"], EN["popup.open_dashboard"])
        self.assertEqual(vm["tasks"][0]["check_label"], EN["popup.resume_transient"])


class ActivityTests(unittest.TestCase):
    def test_each_state_is_what_the_records_say(self):
        cases = {
            "monitoring": ([], STATUS),
            "waiting": ([row("a", eligible=NOW + 10)], STATUS),
            "checking": ([row("a", eligible=NOW - 1)], STATUS),
            "recovering": ([row("a", state="turn_started"), row("b", eligible=NOW + 1)], STATUS),
            "paused": ([row("a", eligible=NOW + 10)], dict(STATUS, enabled=False)),
            "attention": ([], dict(STATUS, watcher={"running": True, "ticking": False})),
        }
        for expected, (rows, status) in cases.items():
            with self.subTest(expected):
                self.assertEqual(popup.activity(status, rows, NOW), expected)
                self.assertIn(expected, popup.STATES)

    def test_something_nobody_can_recover_from_needs_attention_even_while_paused(self):
        status = dict(STATUS, enabled=False)
        self.assertEqual(popup.activity(status, [row("a", overlays=["engine_unavailable"])], NOW), "attention")
        self.assertEqual(popup.activity(dict(STATUS, watcher_running=False), [], NOW), "attention")
        self.assertEqual(popup.activity(dict(STATUS, watcher={"engine_state": "incompatible"}), [], NOW),
                         "attention")

    def test_the_badge_follows_the_ticks_snapshot(self):
        self.assertIsNone(popup.BADGE[popup.snapshot_activity({}, NOW)])
        self.assertIsNone(popup.BADGE[popup.snapshot_activity({"enabled": True, "waiting": 0}, NOW)])
        self.assertEqual(popup.BADGE[popup.snapshot_activity({"enabled": True, "waiting": 2, "next_at": NOW + 9},
                                                             NOW)], "waiting")
        self.assertEqual(popup.BADGE[popup.snapshot_activity({"enabled": False, "waiting": 2}, NOW)], "paused")
        self.assertEqual(popup.BADGE[popup.snapshot_activity({"enabled": True}, NOW, attention=True)], "attention")
        for state in popup.STATES:
            token = popup.BADGE[state]
            self.assertTrue(token is None or token in brand.LIGHT, state)


# ---------------------------------------------------------------------------- placement
class PlacementTests(unittest.TestCase):
    SIZE = (360, 500)

    def assertInside(self, x, y, work, size=SIZE, gap=12):
        self.assertGreaterEqual(x, work[0] + gap)
        self.assertGreaterEqual(y, work[1] + gap)
        self.assertLessEqual(x + size[0], work[2] - gap)
        self.assertLessEqual(y + size[1], work[3] - gap)

    def test_a_bottom_taskbar_puts_it_above_the_icon(self):
        work, monitor = (0, 0, 1920, 1032), (0, 0, 1920, 1080)
        x, y, edge = popup.place(self.SIZE, work, monitor, icon=(1700, 1040, 1724, 1064))
        self.assertEqual((x, y, edge), (1532, 520, "bottom"))
        self.assertInside(x, y, work)

    def test_an_icon_near_the_corner_is_clamped_inside_the_work_area(self):
        work, monitor = (0, 0, 1920, 1032), (0, 0, 1920, 1080)
        x, y, _ = popup.place(self.SIZE, work, monitor, icon=(1890, 1040, 1914, 1064))
        self.assertEqual(x, 1920 - 12 - 360)
        self.assertInside(x, y, work)

    def test_a_top_taskbar_puts_it_below(self):
        work, monitor = (0, 48, 1920, 1080), (0, 0, 1920, 1080)
        x, y, edge = popup.place(self.SIZE, work, monitor, icon=(1700, 12, 1724, 36))
        self.assertEqual((y, edge), (60, "top"))
        self.assertInside(x, y, work)

    def test_a_left_taskbar_puts_it_to_the_right(self):
        work, monitor = (48, 0, 1920, 1080), (0, 0, 1920, 1080)
        x, y, edge = popup.place(self.SIZE, work, monitor, icon=(12, 900, 36, 924))
        self.assertEqual((x, y, edge), (60, 1080 - 12 - 500, "left"))
        self.assertInside(x, y, work)

    def test_a_right_taskbar_puts_it_to_the_left(self):
        work, monitor = (0, 0, 1872, 1080), (0, 0, 1920, 1080)
        x, y, edge = popup.place(self.SIZE, work, monitor, icon=(1884, 500, 1908, 524))
        self.assertEqual((x, y, edge), (1500, 262, "right"))
        self.assertInside(x, y, work)

    def test_a_monitor_left_of_and_above_the_primary_one(self):
        work, monitor = (-2560, -300, 0, 1092), (-2560, -300, 0, 1140)
        x, y, edge = popup.place(self.SIZE, work, monitor, icon=(-300, 1100, -276, 1124))
        self.assertEqual((x, y, edge), (-468, 580, "bottom"))
        self.assertInside(x, y, work)
        x, y, _ = popup.place(self.SIZE, work, monitor, icon=(-2555, 1100, -2531, 1124))
        self.assertEqual(x, -2560 + 12)

    def test_without_an_icon_rectangle_the_cursor_stands_in(self):
        work, monitor = (0, 0, 1920, 1032), (0, 0, 1920, 1080)
        x, y, edge = popup.place(self.SIZE, work, monitor, icon=None, cursor=(1000, 1060))
        self.assertEqual((x, y, edge), (820, 520, "bottom"))
        x, y, _ = popup.place(self.SIZE, work, monitor)
        self.assertInside(x, y, work)

    def test_an_auto_hidden_taskbar_is_found_from_the_icon(self):
        whole = (0, 0, 1920, 1080)
        self.assertEqual(popup.taskbar_edge(whole, whole, (1700, 1070, 1724, 1080)), "bottom")
        self.assertEqual(popup.taskbar_edge(whole, whole, (0, 500, 10, 524)), "left")
        self.assertEqual(popup.taskbar_edge(whole, whole, (1910, 500, 1920, 524)), "right")
        self.assertEqual(popup.taskbar_edge(whole, whole, (900, 0, 924, 10)), "top")

    def test_taller_than_the_screen_starts_at_the_top_of_the_work_area(self):
        work, monitor = (0, 0, 1280, 672), (0, 0, 1280, 720)
        _, y, _ = popup.place((360, 900), work, monitor, icon=(1200, 680, 1224, 704))
        self.assertEqual(y, 12)

    def test_it_is_always_inside_the_work_area(self):
        monitor = (0, 0, 1920, 1080)
        for work in ((0, 0, 1920, 1032), (0, 48, 1920, 1080), (60, 0, 1920, 1080), (0, 0, 1860, 1080)):
            for icon_x in range(-50, 2000, 170):
                for icon_y in range(-50, 1150, 190):
                    x, y, _ = popup.place(self.SIZE, work, monitor, icon=(icon_x, icon_y, icon_x + 24, icon_y + 24))
                    self.assertInside(x, y, work)


# ------------------------------------------------------------------ layout, hits, focus
class LayoutTests(unittest.TestCase):
    def plan(self, strings=EN, rows=None, scale=1.0, **extra):
        rows = rows if rows is not None else [row("a", eligible=NOW + 42),
                                              row("b", "waiting_reset", "usage_limit", eligible=NOW + 99,
                                                  reset=NOW + 99, thread=OTHER_THREAD)]
        vm = popup.view_model(rows, STATUS, strings, NOW, **extra)
        return vm, popup.layout(vm, scale, measure)

    def test_targets_are_the_switches_then_pause_then_dashboard(self):
        _, plan = self.plan()
        self.assertEqual(popup.focus_order(plan["targets"]),
                         [("check", "a" * 64), ("check", "b" * 64), ("toggle",), ("dashboard",)])

    def test_a_switch_is_addressed_by_its_interruption_never_by_its_position(self):
        _, plan = self.plan()
        for target, _ in plan["targets"]:
            if target[0] == "check":
                self.assertIsInstance(target[1], str)
                self.assertEqual(len(target[1]), 64)

    def test_hit_testing_finds_each_target_and_nothing_between_them(self):
        _, plan = self.plan()
        for target, (left, top, right, bottom) in plan["targets"]:
            self.assertEqual(popup.hit_test(plan["targets"], (left + right) // 2, (top + bottom) // 2), target)
            self.assertEqual(popup.hit_test(plan["targets"], left, top), target)
            self.assertNotEqual(popup.hit_test(plan["targets"], right, bottom), target)
        self.assertIsNone(popup.hit_test(plan["targets"], 1, 1))
        self.assertIsNone(popup.hit_test(plan["targets"], -5, 200))

    def test_tab_and_shift_tab_cycle(self):
        order = ["one", "two", "three"]
        self.assertEqual(popup.next_focus(order, None), "one")
        self.assertEqual(popup.next_focus(order, None, backwards=True), "three")
        self.assertEqual(popup.next_focus(order, "one"), "two")
        self.assertEqual(popup.next_focus(order, "three"), "one")
        self.assertEqual(popup.next_focus(order, "one", backwards=True), "three")
        self.assertEqual(popup.next_focus(order, "gone"), "one")
        self.assertIsNone(popup.next_focus([], "one"))

    def test_everything_sits_inside_the_card_at_every_scale_and_in_every_language(self):
        rows = [row(key, eligible=NOW + index * 100, name="A rather long conversation name %d" % index)
                for index, key in enumerate("abcde")]
        for locale in l10n.LOCALES:
            for scale in (1.0, 1.25, 1.5, 1.75, 2.0):
                with self.subTest(locale=locale, scale=scale):
                    vm, plan = self.plan(interface.STRINGS[locale], rows, scale,
                                         notice=interface.STRINGS[locale]["popup.stale"])
                    width, height = plan["size"]
                    card = plan["card"]
                    # The card is exactly as wide as it always was; only the canvas round it grew.
                    self.assertEqual(card[2] - card[0],
                                     round(popup.WIDTH * scale) - 2 * round(brand.SPACING["m"] * scale))
                    margin = round(popup.SHADOW_MARGIN * scale)
                    self.assertEqual((card[0], card[1], width - card[2], height - card[3]), (margin,) * 4)
                    for item in plan["items"]:
                        rect = item.get("rect")
                        if rect is None or item["kind"] in ("card", "focusable"):
                            continue
                        self.assertGreaterEqual(rect[0], card[0], item)
                        self.assertGreaterEqual(rect[1], card[1], item)
                        self.assertLessEqual(rect[2], card[2], item)
                        self.assertLessEqual(rect[3], card[3], item)

    def test_wrapped_text_gets_all_the_height_it_measured(self):
        vm, plan = self.plan(interface.STRINGS["de"], notice=interface.STRINGS["de"]["popup.stale"])
        for item in plan["items"]:
            if item["kind"] == "text" and item["wrap"]:
                left, top, right, bottom = item["rect"]
                self.assertGreaterEqual(bottom - top, measure(item["role"], item["text"], right - left, True)[1])

    def test_buttons_stack_when_either_label_would_not_fit_beside_the_other(self):
        _, side = self.plan(EN)
        toggle = dict(side["targets"])[("toggle",)]
        dashboard = dict(side["targets"])[("dashboard",)]
        self.assertEqual(toggle[1], dashboard[1])
        _, stacked = self.plan(interface.STRINGS["de"])
        toggle = dict(stacked["targets"])[("toggle",)]
        dashboard = dict(stacked["targets"])[("dashboard",)]
        self.assertLess(toggle[3], dashboard[1] + 1)
        self.assertEqual(toggle[0], dashboard[0])

    def test_the_empty_state_and_the_notice_are_drawn(self):
        vm = popup.view_model([], STATUS, EN, NOW, notice=EN["popup.stale"])
        texts = [item["text"] for item in popup.layout(vm, 1.0, measure)["items"] if item["kind"] == "text"]
        self.assertIn(EN["popup.nothing"], texts)
        self.assertIn(EN["popup.stale"], texts)

    def test_the_card_s_lift_has_faded_into_the_canvas_by_the_window_s_edge(self):
        canvas = brand.rgb(brand.LIGHT["canvas"])
        for scale in (1.0, 1.25, 1.5, 1.75, 2.0):
            margin = round(popup.SHADOW_MARGIN * scale)
            for side in ("left", "top", "right", "bottom"):
                with self.subTest(scale=scale, side=side):
                    colour = brand.elevation_colour("card", side, margin, "canvas", scale=scale)
                    self.assertLess(max(abs(part - ground) for part, ground in zip(colour, canvas)), 1.0)

    def test_a_switch_sits_at_the_end_of_its_label_s_last_line(self):
        """v0.6.4: the label on the left, the switch at the bottom right of its row, level with the
        label's last line (the geometry in every language, at every scale and with labels far longer
        than any translation is tests/test_tray_popup_v064.py)."""
        line_h = measure("body", "Ag", 100, False)[1]
        wrapped = 0
        for scale in (1.0, 1.25, 1.5, 1.75, 2.0):
            _, plan = self.plan(scale=scale)
            switches = [item for item in plan["items"] if item["kind"] == "switch"]
            self.assertEqual(len(switches), 2)
            for switch in switches:
                with self.subTest(scale=scale, target=switch["target"]):
                    left, top, right, bottom = switch["rect"]
                    self.assertEqual((right - left, bottom - top), (round(brand.LAYOUT["switch_width"] * scale),
                                                                    round(brand.LAYOUT["switch_height"] * scale)))
                    label = next(item for item in plan["items"]
                                 if item["kind"] == "text" and item["target"] == switch["target"])
                    row_inner_right = plan["card"][2] - round(brand.SPACING["l"] * scale) - round(brand.SPACING["m"] * scale)
                    self.assertEqual(right, row_inner_right)
                    self.assertEqual(label["rect"][2], left - round(popup.SWITCH_GAP * scale))
                    # Centred on the label's last line, however many lines it wraps to...
                    self.assertLessEqual(abs(label["rect"][3] - line_h / 2.0 - (top + bottom) / 2.0), 0.5)
                    wrapped += label["rect"][3] - label["rect"][1] > line_h
                    # ...and the lowest thing on its line: the line's hit rectangle ends its margin below it.
                    hit = dict(plan["targets"])[switch["target"]]
                    self.assertEqual(hit[3], bottom + round(4 * scale))
                    self.assertTrue(hit[0] <= label["rect"][0] and hit[1] <= label["rect"][1] and right <= hit[2])
        self.assertGreater(wrapped, 0, "no label wrapped, so nothing here tells the last line from the first")

    def test_the_header_keeps_its_place_and_the_glow_stays_on_the_card(self):
        for scale in (1.0, 1.25, 1.5, 1.75, 2.0):
            with self.subTest(scale=scale):
                _, plan = self.plan(scale=scale)
                card = plan["card"]
                halo = next(item for item in plan["items"] if item["kind"] == "halo")
                self.assertAlmostEqual(halo["radius"], brand.glow_extent(brand.STATUS_DOT["popup"]) * scale)
                self.assertGreaterEqual(halo["cx"] - halo["radius"], card[0])
                title = next(item for item in plan["items"] if item["kind"] == "text" and item["role"] == "title")
                self.assertEqual(title["rect"][0], card[0] + round(brand.SPACING["l"] * scale)
                                 + round(popup.MARK * scale) + round((brand.SPACING["s"] + 2) * scale))


# ------------------------------------------------------------------------------- motion
class MotionTests(unittest.TestCase):
    """The glow is brand's status light, frame for frame, and it moves as v0.6.5 decided."""
    GLOW = brand.GLOW
    STILL = brand.GLOW["still"]
    MOMENTS = (0, 1, 97, 350, 550, 700, 900, 1100, 1399, 1400, 1600, 1800, 2200, 2700, 3599, 3600, 5000, 12345.6)

    def test_every_frame_is_the_brand_status_light(self):
        for state in popup.STATES + ("idle", "failed", "unknown"):
            with self.subTest(state):
                for elapsed in self.MOMENTS:
                    for since in (None, -1, 0, 350, 700, 1399, 1400, 9999):
                        for reduced in (False, True):
                            self.assertEqual(popup.halo(state, elapsed, since, reduced=reduced),
                                             brand.glow(state, elapsed, since, reduced=reduced))
                            self.assertEqual(popup.animates(state, since, reduced=reduced),
                                             brand.glow_moves(state, since, reduced=reduced))

    def test_monitoring_breathes_slowly_and_low(self):
        cycle, low, high = self.GLOW["monitoring_ms"], self.GLOW["monitoring_low"], self.GLOW["monitoring_high"]
        self.assertAlmostEqual(popup.halo("monitoring", 0)["opacity"], low)
        self.assertAlmostEqual(popup.halo("monitoring", cycle / 2)["opacity"], high)
        self.assertAlmostEqual(popup.halo("monitoring", cycle)["opacity"], low)
        for elapsed in range(0, cycle, 97):
            frame = popup.halo("monitoring", elapsed)
            self.assertTrue(low - 1e-9 <= frame["opacity"] <= high + 1e-9)
            self.assertTrue(self.GLOW["monitoring_scale_low"] - 1e-9 <= frame["scale"]
                            <= self.GLOW["monitoring_scale_high"] + 1e-9)
            self.assertIsNone(frame["arc"])
        self.assertTrue(popup.animates("monitoring"))

    def test_waiting_is_a_still_soft_glow(self):
        frames = {tuple(sorted(popup.halo("waiting", elapsed).items())) for elapsed in range(0, 5000, 333)}
        self.assertEqual(frames, {(("arc", None), ("opacity", self.STILL), ("scale", 1.0))})
        self.assertFalse(popup.animates("waiting"))

    def test_checking_turns_a_small_arc_over_a_still_glow(self):
        first, later = popup.halo("checking", 0), popup.halo("checking", self.GLOW["arc_ms"] / 4)
        self.assertAlmostEqual(later["arc"] - first["arc"], 90.0)
        self.assertEqual((first["opacity"], later["opacity"]), (self.STILL, self.STILL))
        self.assertTrue(popup.animates("checking"))

    def test_recovering_breathes_brighter_and_quicker_than_monitoring(self):
        recovering = max(popup.halo("recovering", elapsed)["opacity"]
                         for elapsed in range(0, self.GLOW["recovering_ms"], 10))
        monitoring = max(popup.halo("monitoring", elapsed)["opacity"]
                         for elapsed in range(0, self.GLOW["monitoring_ms"], 10))
        self.assertGreater(recovering, monitoring)
        self.assertLess(self.GLOW["recovering_ms"], self.GLOW["monitoring_ms"])
        self.assertAlmostEqual(popup.halo("recovering", 0)["opacity"],
                               popup.halo("recovering", self.GLOW["recovering_ms"])["opacity"])

    def test_paused_has_no_glow_and_nothing_moves(self):
        self.assertIsNone(popup.halo("paused", 1234))
        self.assertIsNone(popup.halo("paused", 1234, reduced=True))
        self.assertFalse(popup.animates("paused"))

    def test_attention_glows_up_once_when_it_arrives_and_then_holds_still(self):
        pulse = self.GLOW["attention_ms"]
        self.assertAlmostEqual(popup.halo("attention", 0, since_entered_ms=pulse / 2)["opacity"],
                               self.GLOW["attention_peak"])
        self.assertAlmostEqual(popup.halo("attention", 0, since_entered_ms=pulse * 3)["opacity"], self.STILL)
        self.assertAlmostEqual(popup.halo("attention", 0)["opacity"], self.STILL)
        self.assertTrue(popup.animates("attention", pulse / 2))
        self.assertFalse(popup.animates("attention", pulse + 1))

    def test_reduced_motion_never_loops_or_pulses(self):
        for state in popup.STATES:
            with self.subTest(state):
                self.assertFalse(popup.animates(state, 0, reduced=True))
                frames = {repr(popup.halo(state, elapsed, since_entered_ms=elapsed, reduced=True))
                          for elapsed in (0, 400, 1200, 2400, 9999)}
                self.assertEqual(len(frames), 1)
        self.assertEqual(popup.halo("monitoring", 900, reduced=True),
                         {"opacity": brand.glow_rest("monitoring"), "scale": 1.0, "arc": None})
        self.assertAlmostEqual(brand.glow_rest("monitoring"), 0.35)            # v0.6.5: .12 to .58
        self.assertEqual(popup.halo("waiting", 900, reduced=True)["opacity"], self.STILL)
        # Checking keeps its arc, still: with waiting and checking the same cyan, it is the difference.
        self.assertEqual(popup.halo("checking", 900, reduced=True)["arc"], self.GLOW["arc_still_at"])


class SwitchGlideTests(unittest.TestCase):
    """v0.6.5: a task's switch glides between its ends in brand's transition time, on brand's curve."""
    T = ("check", "a" * 64)
    U = ("check", "b" * 64)
    MS = brand.MOTION["transition_ms"]

    def test_a_glide_runs_its_ends_in_the_transition_time_on_the_brand_curve(self):
        glide = (1000.0, 0.0, 1.0)
        self.assertEqual(popup.glide_amount(glide, 1000.0), (0.0, False))
        for elapsed in (16, 40, 80, 120, 159):
            amount, done = popup.glide_amount(glide, 1000.0 + elapsed)
            self.assertFalse(done)
            self.assertAlmostEqual(amount, brand.ease(elapsed / float(self.MS)))
        self.assertEqual(popup.glide_amount(glide, 1000.0 + self.MS), (1.0, True))
        self.assertEqual(popup.glide_amount(glide, 99999.0), (1.0, True))
        back = (0.0, 1.0, 0.0)
        self.assertAlmostEqual(popup.glide_amount(back, 40)[0], 1.0 - brand.ease(40 / float(self.MS)))

    def test_only_a_switch_drawn_the_other_way_starts_one(self):
        self.assertEqual(popup.next_glides({self.T: True}, None, {}, 0.0), {})            # just opened
        self.assertEqual(popup.next_glides({self.T: True}, {self.T: True}, {}, 0.0), {})  # unchanged
        self.assertEqual(popup.next_glides({self.T: True}, {}, {}, 0.0), {})              # new row
        self.assertEqual(popup.next_glides({self.T: True}, {self.T: False}, {}, 500.0),
                         {self.T: (500.0, 0.0, 1.0)})
        self.assertEqual(popup.next_glides({self.T: False, self.U: True}, {self.T: True, self.U: True}, {}, 7.0),
                         {self.T: (7.0, 1.0, 0.0)})

    def test_a_glide_keeps_going_turns_back_from_where_it_is_and_ends_with_its_row(self):
        running = {self.T: (0.0, 0.0, 1.0)}
        self.assertEqual(popup.next_glides({self.T: True}, {self.T: True}, running, 60.0), running)
        turned = popup.next_glides({self.T: False}, {self.T: True}, running, 60.0)
        self.assertEqual(turned[self.T][0], 60.0)
        self.assertAlmostEqual(turned[self.T][1], brand.ease(60 / float(self.MS)))
        self.assertEqual(turned[self.T][2], 0.0)
        self.assertEqual(popup.next_glides({}, {self.T: True}, running, 60.0), {})

    def test_reduced_motion_high_contrast_and_a_hidden_window_move_nothing(self):
        running = {self.T: (0.0, 0.0, 1.0)}
        self.assertEqual(popup.next_glides({self.T: True}, {self.T: False}, {}, 0.0, animate=False), {})
        self.assertEqual(popup.next_glides({self.T: True}, {self.T: True}, running, 60.0, animate=False), {})


class StatusLightTests(unittest.TestCase):
    def test_the_dot_is_the_brand_status_light(self):
        for state in popup.STATES:
            self.assertEqual(popup.DOT_FILL[state], brand.status_fill(state), state)
        for state in ("monitoring", "waiting", "checking", "recovering"):
            self.assertEqual(popup.DOT_FILL[state], "active", state)      # the colour it had before v0.6.3
        self.assertEqual(popup.DOT_FILL["paused"], "paused")
        self.assertEqual(popup.DOT_FILL["attention"], "attention")


# ---------------------------------------------------------------------------- elevation
class ElevationTests(unittest.TestCase):
    """The shadow images are the panel's recipes: brand's model along an edge, round at a corner."""

    def test_along_an_edge_a_lift_is_brand_s_shadow_model(self):
        for recipe, radius, body in (("card", brand.RADII["card"], (336, 400)),
                                     ("control", brand.RADII["control"], (148, 32))):
            for scale in (1.0, 1.5, 2.0):
                with self.subTest(recipe=recipe, scale=scale):
                    width, height = round(body[0] * scale), round(body[1] * scale)
                    worst = 0.0
                    for d in range(40):
                        colour = [float(part) for part in brand.rgb(brand.LIGHT["canvas"])]
                        for shadow in reversed(brand.SHADOWS["light"][recipe]):
                            mask = popup.lift_coverage(width, height, radius * scale, shadow.blur * scale)
                            box = mask["width"] - 2 * mask["extent"]
                            column = mask["extent"] + box + d - popup.shadow_step(shadow.dx * scale)
                            row = mask["centre"][1] * mask["width"]
                            level = mask["coverage"][row + column] if 0 <= column < mask["width"] else 0
                            alpha = min(255, int(shadow.alpha * level + 0.5)) / 255.0
                            colour = [part + (tone - part) * alpha
                                      for part, tone in zip(colour, brand.rgb(brand.LIGHT[shadow.token]))]
                        model = brand.elevation_colour(recipe, "right", d + 0.5, "canvas", scale=scale)
                        worst = max(worst, max(abs(part - want) for part, want in zip(colour, model)))
                    self.assertLess(worst, 1.5)

    def test_a_lift_is_symmetric_and_round_at_its_corners(self):
        mask = popup.lift_coverage(336, 400, 16, 14)
        width, height, extent = mask["width"], mask["height"], mask["extent"]
        rows = [mask["coverage"][y * width:(y + 1) * width] for y in range(height)]
        self.assertEqual(rows, rows[::-1])
        self.assertTrue(all(row == row[::-1] for row in rows))
        middle = mask["centre"][1]
        self.assertLess(rows[extent][extent], rows[middle][extent])       # the corner is cut round

    def test_along_its_top_a_well_is_brand_s_inset_model(self):
        width, height, radius = 146, 30, 10               # a pressed button inside its border, at 100%
        centre = None
        worst = 0.0
        for j in range(14):
            colour = [float(part) for part in brand.rgb(brand.LIGHT["inset"])]
            for shadow in reversed(brand.SHADOWS["light"]["inset"]):
                mask = popup.well_coverage(width, height, radius, shadow.blur, shadow.dx, shadow.dy)
                centre = mask["centre"][0]
                level = mask["coverage"][j * mask["width"] + centre]
                alpha = min(255, int(shadow.alpha * level + 0.5)) / 255.0
                colour = [part + (tone - part) * alpha
                          for part, tone in zip(colour, brand.rgb(brand.LIGHT[shadow.token]))]
            model = brand.elevation_colour("inset", "top", j + 0.5, "inset")
            worst = max(worst, max(abs(part - want) for part, want in zip(colour, model)))
        self.assertLess(worst, 1.5)

    def test_a_well_is_shaded_at_its_top_and_its_light_is_the_shade_turned_round(self):
        popup._MASKS.clear()
        light = popup.well_coverage(38, 20, 10, 6, -2, -2)["coverage"]
        popup._MASKS.clear()
        dark = popup.well_coverage(38, 20, 10, 6, 2, 2)
        self.assertEqual(light, dark["coverage"][::-1])
        data, width = dark["coverage"], dark["width"]
        self.assertGreater(data[1 * width + 25], data[10 * width + 25])
        self.assertGreater(data[1 * width + 25], data[18 * width + 25])

    def test_every_body_longer_than_its_corners_shares_one_mask(self):
        """A mask is keyed on the box it is made from, so a taller card or a wider button finds it."""
        popup._MASKS.clear()
        card = popup.lift_coverage(336, 400, 16, 14)
        self.assertTrue(popup.lift_coverage(336, 520, 16, 14) is card, "a taller card made a mask of its own")
        self.assertTrue(popup.lift_coverage(298, 401, 16, 14) is card, "a narrower card made a mask of its own")
        well = popup.well_coverage(146, 30, 10, 6, 2, 2)
        self.assertTrue(popup.well_coverage(230, 30, 10, 6, 2, 2) is well, "a wider well made a mask of its own")
        # The light shadow is the shade turned round, whatever body the shade was made for.
        with unittest.mock.patch.object(popup, "_rounded_distance", side_effect=AssertionError("made again")):
            turned = popup.well_coverage(260, 30, 10, 6, -2, -2)
        self.assertEqual(turned["coverage"], well["coverage"][::-1])
        # A body shorter than its corners keeps a mask of its own, and every mask is the one it
        # would have been made alone.
        bodies = [("lift", (336, 400, 16, 14)), ("lift", (20, 400, 16, 14)), ("lift", (336, 21, 16, 14)),
                  ("lift", (148, 32, 10, 6)), ("lift", (296, 64, 20, 12)), ("lift", (40, 40, 20, 12)),
                  ("well", (146, 30, 10, 6, 2, 2)), ("well", (146, 30, 10, 6, -2, -2)),
                  ("well", (36, 18, 9, 6, 2, 2)), ("well", (220, 45, 15, 9, -3, -3)),
                  ("well", (30, 45, 15, 9, 3, 3))]
        make = {"lift": popup.lift_coverage, "well": popup.well_coverage}
        popup._MASKS.clear()
        together = [make[kind](*args) for kind, args in bodies]
        self.assertEqual(together[1]["width"] - 2 * together[1]["extent"], 20)
        self.assertEqual(together[2]["height"] - 2 * together[2]["extent"], 21)
        for (kind, args), mask in zip(bodies, together):
            popup._MASKS.clear()
            alone = make[kind](*args)
            with self.subTest(kind=kind, args=args):
                self.assertEqual({name: alone[name] for name in ("width", "height", "centre", "extent", "coverage")},
                                 {name: mask[name] for name in ("width", "height", "centre", "extent", "coverage")})

    def test_light_and_shade_move_by_the_same_whole_pixels(self):
        self.assertEqual([popup.shadow_step(value) for value in (4.0, -4.0, 2.5, -2.5, 3.5, -3.5, 0.4)],
                         [4, -4, 3, -3, 4, -4, 0])


class HighContrastTests(unittest.TestCase):
    """In High Contrast every colour is a system colour, mapped as the settings window maps it."""

    def test_every_token_has_the_settings_window_s_system_colour(self):
        window = {"ink": "WindowText", "muted": "GrayText", "line": "WindowFrame", "surface": "Window",
                  "canvas": "Control", "raised": "Window", "inset": "Window", "accent": "Highlight",
                  "on_accent": "HighlightText", "accent_soft": "Highlight", "focus": "WindowText",
                  "active": "Highlight", "idle": "GrayText", "attention": "WindowText", "success": "WindowText",
                  "waiting": "WindowText", "warning": "WindowText", "danger": "WindowText", "paused": "GrayText"}
        for token, system in window.items():
            self.assertEqual(popup.contrast_colour(token), system, token)
        self.assertEqual(set(popup.CONTRAST_COLOURS), set(brand.LIGHT))
        for token in brand.LIGHT:
            self.assertIn(popup.contrast_colour(token), popup.SYSTEM_COLOURS, token)

    def test_the_state_dot_is_a_system_colour_too(self):
        for state in popup.STATES:
            self.assertIn(brand.status_system(state), popup.SYSTEM_COLOURS, state)
        self.assertEqual({brand.status_system(state) for state in ("monitoring", "waiting", "checking", "recovering")},
                         {"Highlight"})
        self.assertEqual(brand.status_system("attention"), "WindowText")
        self.assertEqual(brand.status_system("paused"), "GrayText")


class SelectTests(unittest.TestCase):
    def test_a_click_opens_and_a_second_click_closes(self):
        self.assertEqual(popup.select_action(False, 10.0), "show")
        self.assertEqual(popup.select_action(True, 10.0), "hide")

    def test_the_click_that_took_activation_away_does_not_reopen_it(self):
        self.assertEqual(popup.select_action(False, 10.2, hidden_at=10.0), "none")
        self.assertEqual(popup.select_action(False, 11.0, hidden_at=10.0), "show")

    def test_a_double_click_leaves_it_open(self):
        self.assertEqual(popup.select_action(True, 10.1, double_click_at=10.0), "none")
        self.assertEqual(popup.select_action(False, 10.1, double_click_at=10.0, hidden_at=10.05), "show")

    def test_enter_on_the_icon_counts_once(self):
        self.assertEqual(popup.select_action(True, 10.1, previous_key_at=10.0, keyboard=True), "none")
        self.assertEqual(popup.select_action(True, 10.6, previous_key_at=10.0, keyboard=True), "hide")


# ----------------------------------------------------------------- actions and refusals
class ActionTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeControl([row("a", eligible=NOW + 42), row("b", eligible=NOW + 900, thread=OTHER_THREAD)])

    def test_a_click_carries_exactly_the_ids_its_row_was_drawn_with(self):
        model, _ = opened(self.fake)
        action = model.action_for(("check", "b" * 64))
        self.assertEqual(action, ("recovery", "b" * 64, OTHER_THREAD, False))
        outcome = popup.perform(action, self.fake)
        self.assertEqual(self.fake.calls[-1], ("set_interruption_recovery", "b" * 64, OTHER_THREAD, False))
        model.apply_outcome(action, outcome, NOW)
        self.assertEqual({item["interruption_id"][0]: item["thread_enabled"] for item in model.rows},
                         {"a": True, "b": False})
        self.assertTrue(model.wants_read)

    def test_a_list_that_re_sorted_after_drawing_does_not_move_the_click(self):
        model, vm = opened(self.fake)
        self.assertEqual(vm["tasks"][0]["interruption_id"], "a" * 64)
        # The watcher reschedules: b is now due first. A read lands but nothing is redrawn.
        self.fake.rows[1]["eligible_at"] = NOW + 1
        model.apply_outcome(("read",), popup.perform(("read",), self.fake), NOW)
        self.assertEqual(model.action_for(("check", "a" * 64)), ("recovery", "a" * 64, THREAD, False))
        # A position is not a target, and neither is a row that was never drawn.
        self.assertIsNone(model.action_for(("check", 0)))
        self.assertIsNone(model.action_for(("check", "f" * 64)))
        self.assertIsNone(model.action_for(("send", "a" * 64)))

    def test_every_stale_refusal_changes_nothing_and_says_so(self):
        for code in sorted(popup.STALE_CODES):
            with self.subTest(code):
                fake = FakeControl(self.fake.rows, refuse=code)
                model, _ = opened(fake)
                rows_before, status_before = copy.deepcopy(model.rows), copy.deepcopy(model.status)
                action = model.action_for(("check", "a" * 64))
                self.assertTrue(model.begin(action))
                outcome = popup.perform(action, fake)
                self.assertEqual(outcome, ("refused", code))
                model.apply_outcome(action, outcome, NOW)
                self.assertEqual(model.rows, rows_before)
                self.assertEqual(model.status, status_before)
                self.assertEqual([item["thread_enabled"] for item in fake.rows], [True, True])
                self.assertEqual(model.view(NOW + 1)["notice"], EN["popup.stale"])
                self.assertTrue(model.wants_read)
                self.assertEqual(model.busy, set())

    def test_the_stale_notice_goes_away_by_itself(self):
        fake = FakeControl(self.fake.rows, refuse="thread_mismatch")
        model, _ = opened(fake)
        action = model.action_for(("check", "a" * 64))
        model.apply_outcome(action, popup.perform(action, fake), NOW)
        self.assertIsNone(model.view(NOW + popup.NOTICE_SECONDS + 0.1)["notice"])

    def test_an_unexpected_failure_changes_nothing_either(self):
        fake = FakeControl(self.fake.rows, explode=True)
        model, _ = opened(fake)
        before = copy.deepcopy(model.rows)
        action = model.action_for(("check", "a" * 64))
        outcome = popup.perform(action, fake)
        self.assertEqual(outcome, ("failed", "RuntimeError"))
        model.apply_outcome(action, outcome, NOW)
        self.assertEqual(model.rows, before)
        self.assertEqual(model.view(NOW)["notice"], EN["action.failed"])

    def test_the_same_switch_cannot_be_pressed_twice_while_it_is_under_way(self):
        model, _ = opened(self.fake)
        action = model.action_for(("check", "a" * 64))
        self.assertTrue(model.begin(action))
        self.assertFalse(model.begin(action))
        self.assertTrue(model.view(NOW)["tasks"][0]["busy"])
        model.apply_outcome(action, popup.perform(action, self.fake), NOW)
        self.assertTrue(model.begin(action))

    def test_pause_and_resume_follow_what_was_drawn(self):
        model, _ = opened(self.fake)
        self.assertEqual(model.action_for(("toggle",)), ("enabled", False))
        popup.perform(model.action_for(("toggle",)), self.fake)
        self.assertEqual(self.fake.calls[-1], ("set_enabled", False))
        paused, _ = opened(FakeControl([], dict(STATUS, enabled=False)))
        self.assertEqual(paused.action_for(("toggle",)), ("enabled", True))

    def test_nothing_can_be_toggled_before_the_status_is_known(self):
        model = popup.PopupModel(EN)
        vm = model.view(NOW)
        self.assertIsNone(model.action_for(("toggle",)))
        self.assertTrue(vm["toggle_busy"])

    def test_open_dashboard_makes_no_control_call(self):
        reached = []
        self.assertEqual(popup.perform(("dashboard",), self.fake, dashboard=lambda: reached.append(1) or True),
                         ("ok", {"opened": True}))
        self.assertEqual((reached, self.fake.calls), ([1], []))

    def test_the_read_asks_for_names_through_list_pending(self):
        names = object()
        popup.perform(("read",), self.fake, source=names)
        self.assertEqual(self.fake.calls, [("list_pending", names), ("get_status",)])

    def test_a_failed_read_says_it_cannot_be_read(self):
        class Broken:
            def list_pending(self, **unused):
                raise OSError("locked")
        model = popup.PopupModel(EN)
        model.apply_outcome(("read",), popup.perform(("read",), Broken()), NOW)
        self.assertEqual(model.view(NOW)["error"], EN["pending.unavailable"])


# -------------------------------------------------------------------- badge and fonts
class BadgeTests(unittest.TestCase):
    def test_the_dot_is_drawn_in_its_colour_inside_a_cut_out(self):
        size = 32
        pixels = bytearray(bytes((200, 100, 50, 255)) * (size * size))
        colour = brand.rgb(brand.LIGHT["waiting"])
        popup.composite_badge(pixels, size, size, colour)
        cut = size * 0.25
        centre = int(size - cut)
        index = (centre * size + centre) * 4
        self.assertEqual(tuple(pixels[index:index + 4]), (colour[2], colour[1], colour[0], 255))
        ring = int(size - cut + (cut - 1.0))                   # inside the cut, outside the dot
        index = (centre * size + min(size - 1, ring)) * 4
        self.assertLess(pixels[index + 3], 255)
        self.assertEqual(tuple(pixels[0:4]), (200, 100, 50, 255))

    def test_a_small_icon_still_gets_a_dot(self):
        pixels = bytearray(16 * 16 * 4)
        popup.composite_badge(pixels, 16, 16, brand.rgb(brand.LIGHT["attention"]))
        self.assertGreater(sum(pixels[3::4]), 255 * 4)

    def test_the_icon_s_badge_is_what_it_was_before_v0_6_4(self):
        """v0.6.4 changed the status light inside the windows and left the icon alone: the same
        table, the same state from the same snapshot, and the same pixels, pinned from v0.6.3."""
        self.assertEqual(popup.BADGE, {"monitoring": None, "waiting": "waiting", "checking": "waiting",
                                       "recovering": "active", "paused": "paused", "attention": "attention"})
        snapshots = [({}, {}), ({"enabled": True, "waiting": 0}, {}),
                     ({"enabled": True, "waiting": 2, "next_at": NOW + 9}, {}),
                     ({"enabled": True, "waiting": 2, "next_at": NOW - 1}, {}),
                     ({"enabled": True, "waiting": 2, "next_at": None}, {}),
                     ({"enabled": True, "running": 1, "waiting": 2}, {}), ({"enabled": False, "waiting": 2}, {}),
                     ({"enabled": False, "running": 1}, {}), ({"enabled": True}, {"attention": True}),
                     ({}, {"attention": True}), (None, {})]
        self.assertEqual([popup.snapshot_activity(snapshot, NOW, **options) for snapshot, options in snapshots],
                         ["monitoring", "monitoring", "waiting", "checking", "waiting", "recovering", "paused",
                          "paused", "attention", "attention", "monitoring"])
        digest = hashlib.sha256()
        for size in (16, 20, 24, 32, 48):
            for token in ("waiting", "active", "paused", "attention"):
                pixels = bytearray()
                for y in range(size):
                    for x in range(size):
                        pixels += bytes(((x * 17 + y * 5) % 256, (x * 3 + y * 11) % 256, (x * 29 + 7) % 256,
                                         255 if (x + y) % 5 else 128))
                popup.composite_badge(pixels, size, size, brand.rgb(brand.LIGHT[token]))
                digest.update(bytes(pixels))
        self.assertEqual(digest.hexdigest(), "5b39ad98edd39a1426d1cf24e4ac9a83c4bdc9199e5c625ad80c50fd63855494")


MALGUN_LOCALIZED = "\ub9d1\uc740 \uace0\ub515"       # Malgun Gothic's name on a Korean Windows
LATIN = ("en", "de", "fr", "es", "pt-BR")


class FontTests(unittest.TestCase):
    def test_each_script_has_its_own_face(self):
        for system in (None, "Segoe UI", MALGUN_LOCALIZED, "Yu Gothic UI"):
            self.assertEqual(popup.font_faces("ko", system)[0], "Malgun Gothic")
            self.assertEqual(popup.font_faces("ja", system)[0], "Yu Gothic UI")
            self.assertEqual(popup.font_faces("zh-CN", system)[0], "Microsoft YaHei UI")
            self.assertEqual(popup.font_faces("zh-TW", system)[0], "Microsoft JhengHei UI")
            for locale in l10n.LOCALES:
                self.assertEqual(popup.font_faces(locale, system)[-1], "Segoe UI")
                for weight in (400, 600):
                    self.assertEqual(popup.font_candidates(locale, weight, system)[-1][0], "Segoe UI")

    def test_every_other_language_is_set_in_windows_own_ui_font_first(self):
        """The panel's type stack, read the way GDI can read it. The panel asks for `system-ui`,
        then "Segoe UI Variable Text", then "Segoe UI"; `system-ui` is Windows' UI font, the
        message font the window itself is drawn in (SystemFonts.MessageBoxFont). On a Korean
        Windows that is Malgun Gothic, so English in the popup and the card must be Malgun Gothic
        too, not Segoe UI Variable Text beside a window and a panel that are not."""
        for locale in LATIN:
            self.assertEqual(popup.font_faces(locale, MALGUN_LOCALIZED),
                             (MALGUN_LOCALIZED, "Segoe UI Variable Text", "Segoe UI"))
            self.assertEqual(popup.font_faces(locale, "Segoe UI"), ("Segoe UI",))
            self.assertEqual(popup.font_faces(locale, "segoe ui"), ("Segoe UI",))
            self.assertEqual(popup.font_faces(locale, "Segoe UI Variable Text"),
                             ("Segoe UI Variable Text", "Segoe UI"))
            # Windows could not be asked: the panel's next choices, as before.
            for nothing in (None, ""):
                self.assertEqual(popup.font_faces(locale, nothing), ("Segoe UI Variable Text", "Segoe UI"))
        with unittest.mock.patch.object(popup, "message_face", return_value=MALGUN_LOCALIZED):
            self.assertEqual(popup.font_faces("en")[0], MALGUN_LOCALIZED)
            self.assertEqual(popup.font_faces("ko")[0], "Malgun Gothic")

    def test_semibold_is_asked_for_by_name_where_gdi_would_otherwise_embolden(self):
        self.assertEqual(popup.font_candidates("en", 600, None)[0], ("Segoe UI Variable Text Semibold", 400))
        self.assertEqual(popup.font_candidates("ja", 600, None)[0], ("Yu Gothic UI Semibold", 400))
        self.assertEqual(popup.font_candidates("ko", 600, None)[0], ("Malgun Gothic", 700))

    def test_emphasis_follows_the_windows_own_rule(self):
        """Soft.Weighted in gui/Controls.cs: a Segoe UI face's own semibold family, the face's
        bold otherwise (Malgun Gothic and the other UI faces have no semibold)."""
        self.assertEqual(popup.font_candidates("en", 600, "Segoe UI"),
                         (("Segoe UI Semibold", 400), ("Segoe UI", 600)))
        self.assertEqual(popup.font_candidates("en", 600, MALGUN_LOCALIZED),
                         ((MALGUN_LOCALIZED, 700), ("Segoe UI Variable Text Semibold", 400),
                          ("Segoe UI Semibold", 400), ("Segoe UI", 600)))
        self.assertEqual(popup.font_candidates("en", 600, None),
                         (("Segoe UI Variable Text Semibold", 400), ("Segoe UI Semibold", 400), ("Segoe UI", 600)))
        self.assertEqual(popup.font_candidates("de", 400, MALGUN_LOCALIZED),
                         ((MALGUN_LOCALIZED, 400), ("Segoe UI Variable Text", 400), ("Segoe UI", 400)))
        self.assertIn('family.StartsWith("Segoe UI", StringComparison.Ordinal) && '
                      '!family.EndsWith("Semibold", StringComparison.Ordinal)',
                      (ROOT / "gui" / "Controls.cs").read_text(encoding="utf-8"))

    def test_the_three_surfaces_start_from_the_same_face(self):
        """One product: the window's every font is a variant of Windows' message font, the panel's
        stack starts with `system-ui`, which resolves to it, and the popup asks Windows for it.
        Putting "Segoe UI" ahead of `system-ui` in the panel would part the panel from the window
        on every Windows whose UI font is not Segoe UI - a Korean one among them."""
        from codex_auto_resume import mcpui
        controls = (ROOT / "gui" / "Controls.cs").read_text(encoding="utf-8")
        self.assertIn("if (baseFont == null) baseFont = SystemFonts.MessageBoxFont;", controls)
        stack = re.search(r"--font:\s*([^;]+);", mcpui._STYLE).group(1)
        self.assertEqual(stack.split(",")[0].strip(), "system-ui")
        panel = [face.strip().strip('"') for face in stack.split(",")[1:3]]
        self.assertEqual(popup.font_faces("en", MALGUN_LOCALIZED)[1:], tuple(panel))
        self.assertIn("SPI_GETNONCLIENTMETRICS", SOURCE.read_text(encoding="utf-8"))

    @unittest.skipUnless(os.name == "nt", "asks Windows")
    def test_the_popup_asks_windows_for_the_font_the_window_is_drawn_in(self):
        face = popup.message_face()
        self.assertTrue(face)
        powershell = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
                      / "WindowsPowerShell" / "v1.0" / "powershell.exe")
        if not powershell.is_file():
            self.skipTest("no Windows PowerShell to ask Windows Forms")
        import subprocess
        script = ("Add-Type -AssemblyName System.Drawing; "
                  "([int[]][char[]][Drawing.SystemFonts]::MessageBoxFont.Name) -join ','")
        done = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-Command", script],
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        window = "".join(chr(int(point)) for point in done.stdout.strip().split(","))
        self.assertEqual(face, window)

    @unittest.skipUnless(os.name == "nt", "GDI")
    def test_english_is_drawn_in_that_font(self):
        face = popup.message_face()
        renderer = popup.Renderer()
        try:
            renderer.use("en", 1.0)
            self.assertEqual(renderer.fonts.faces["body"], face)
            self.assertIn(renderer.fonts.faces["name"], (face, face + " Semibold"))
            renderer.use("ko", 1.0)
            self.assertEqual(renderer.fonts.faces["body"], "Malgun Gothic")
        finally:
            renderer.close()

    def test_the_vocabulary_tells_which_language_it_is(self):
        for locale in l10n.LOCALES:
            self.assertEqual(popup.locale_of(interface.STRINGS[locale]), locale)
        self.assertEqual(popup.locale_of({}), "en")

    def test_dense_scripts_get_a_pixel_more(self):
        self.assertEqual(popup.role_size("body", "ko"), brand.TYPE["body"] + 1)
        self.assertEqual(popup.role_size("body", "de"), brand.TYPE["body"])


# ----------------------------------------------------------------------------- safety
class SafetyTests(unittest.TestCase):
    """What this window can reach is what its source says it can reach."""

    def setUp(self):
        self.text = SOURCE.read_text(encoding="utf-8")
        self.tree = ast.parse(self.text)

    def test_it_imports_nothing_that_can_submit(self):
        package, stdlib = set(), set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ImportFrom):
                if node.level:
                    names = [node.module] if node.module else [alias.name for alias in node.names]
                    package.update(names)
                else:
                    stdlib.add(node.module)
            elif isinstance(node, ast.Import):
                stdlib.update(alias.name for alias in node.names)
        self.assertLessEqual(package, {"brand", "l10n", "machine", "reasons", "tray"})
        for forbidden in ("engine", "backend", "windows", "store", "source", "app", "continuation",
                          "notify", "control", "controlcli", "mcpserver"):
            self.assertNotIn(forbidden, package)
        self.assertLessEqual(stdlib, {"__future__", "ctypes", "ctypes.wintypes", "itertools", "math", "os",
                                      "threading", "time"})

    def test_no_name_in_it_sends_submits_or_queues(self):
        names = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.alias):
                names.add(node.asname or node.name)
        offenders = sorted(name for name in names
                           if re.search(r"send|submit|queue|dispatch|backend|engine", name, re.I))
        self.assertEqual(offenders, [])

    def test_it_asks_the_control_layer_for_exactly_four_things(self):
        called = set()
        for node in ast.walk(self.tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == "control"):
                called.add(node.func.attr)
        self.assertEqual(called, set(popup.CONTROL_CALLS))

    def test_it_drives_nobody_else_s_window_and_opens_no_connection(self):
        forbidden = re.compile(r"\bSendInput\b|\bkeybd_event\b|\bmouse_event\b|\bSetCursorPos\b|"
                               r"\bPrintWindow\b|\bBitBlt\b|\bFindWindow\w*\b|\bsubprocess\b|\bsocket\b|"
                               r"\burllib\b|\bAccessibleObjectFromWindow\b|\bUIAutomation\w*\b")
        self.assertEqual(forbidden.findall(self.text), [])

    def test_every_colour_is_a_brand_token(self):
        self.assertEqual(re.findall(r"#[0-9A-Fa-f]{6}\b", self.text), [])
        used = set(re.findall(r"(?:argb|colorref)\(\"([a-z_]+)\"", self.text))
        tables = set(popup.DOT_FILL.values()) | set(popup.STATE_INK.values()) | {
            token for token in popup.BADGE.values() if token}
        for token in used | tables | {"waiting", "warning", "paused"}:
            self.assertIn(token, brand.LIGHT, token)

    def test_the_menu_still_offers_nothing_per_task(self):
        self.assertEqual((tray.MENU_OPEN, tray.MENU_TOGGLE, tray.MENU_STOP, tray.MENU_PENDING), (1, 2, 3, 4))


# ------------------------------------------------------------------------------ Windows
@unittest.skipUnless(os.name == "nt", "the popup is a Windows window")
class WindowsTests(unittest.TestCase):
    ROWS = [row("a", "waiting_reset", "usage_limit", eligible=NOW + 3600, reset=NOW + 3600,
                name="Add Korean translations to onboarding"),
            row("b", eligible=NOW + 42, thread=OTHER_THREAD, name="Fix flaky CI"),
            row("c", eligible=NOW + 90, enabled=False, name=None),
            row("d", state="queued", category="server_5xx", name="Ship it")]

    def pump(self, seconds=0.05):
        import ctypes
        user32 = ctypes.WinDLL("user32")
        user32.PeekMessageW.argtypes = [ctypes.POINTER(tray.MSG), ctypes.c_void_p, ctypes.c_uint,
                                        ctypes.c_uint, ctypes.c_uint]
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

    def make(self, strings=EN):
        window = popup.Popup(control=FakeControl(self.ROWS), strings=strings)
        window.create()
        window.model.apply_outcome(("read",), popup.perform(("read",), window.control), time.time())
        return window

    def cycle(self, window, keyboard=False):
        window.show(keyboard=keyboard, activate=False, origin=(-32000, -32000))
        self.pump(0.02)
        window.render()
        window.hide()
        self.pump(0.01)

    def test_a_frame_is_drawn_in_the_brand_colours(self):
        renderer = popup.Renderer()
        try:
            vm = popup.view_model(self.ROWS, STATUS, EN, NOW)
            plan = renderer.layout(vm, 1.0, "en")
            canvas = renderer.draw(vm, plan, frame=popup.halo(vm["state"], 0))
            pixels = canvas.pixels()
            width = plan["size"][0]

            def pixel(x, y):
                index = (y * width + x) * 4
                return pixels[index + 2], pixels[index + 1], pixels[index]

            ground, surface = brand.rgb(brand.LIGHT["canvas"]), brand.rgb(brand.LIGHT["surface"])

            def darker(one, other):
                return all(part < reference for part, reference in zip(one, other))

            self.assertEqual(pixel(1, 1), ground)
            left, top, right, bottom = dict(plan["targets"])[("dashboard",)]
            self.assertEqual(pixel(left + 6, (top + bottom) // 2), brand.rgb(brand.LIGHT["accent"]))
            card = plan["card"]
            self.assertEqual(pixel(card[0] + 30, card[1] + 3), surface)
            # The card is lifted off the canvas: shade below and right of it, light above and left.
            middle_x, middle_y = (card[0] + card[2]) // 2, (card[1] + card[3]) // 2
            for x, y in ((card[2] + 5, middle_y), (middle_x, card[3] + 5)):
                self.assertTrue(darker(pixel(x, y), ground), (x, y, pixel(x, y)))
            for x, y in ((card[0] - 6, middle_y), (middle_x, card[1] - 6)):
                self.assertTrue(darker(ground, pixel(x, y)), (x, y, pixel(x, y)))
            # A secondary button stands on the card, with shade under it.
            left, top, right, bottom = dict(plan["targets"])[("toggle",)]
            self.assertTrue(darker(pixel((left + right) // 2, bottom + 3), surface))
            # A switch that is off is a well: shaded along the inside of its top, not in its middle.
            off = next(item for item in plan["items"] if item["kind"] == "switch" and not item["checked"])
            left, top, right, bottom = off["rect"]
            self.assertLess(sum(pixel(left + 25, top + 2)), sum(pixel(left + 25, (top + bottom) // 2)) - 10)
            # The dot is flat and cyan, with a soft glow round it that has faded before the words.
            halo = next(item for item in plan["items"] if item["kind"] == "halo")
            cx, cy = int(halo["cx"]), int(halo["cy"])
            self.assertEqual(pixel(cx, cy), brand.rgb(brand.LIGHT[brand.status_fill(vm["state"])]))
            self.assertEqual(brand.status_fill(vm["state"]), "active")
            self.assertLess(pixel(cx + 7, cy)[0], surface[0] - 8)
            self.assertEqual(pixel(cx + 13, cy), surface)
        finally:
            renderer.close()

    def test_a_paused_dot_is_grey_with_no_glow(self):
        renderer = popup.Renderer()
        try:
            vm = popup.view_model(self.ROWS, dict(STATUS, enabled=False), EN, NOW)
            self.assertEqual(vm["state"], "paused")
            plan = renderer.layout(vm, 1.5, "en")
            canvas = renderer.draw(vm, plan, frame=popup.halo(vm["state"], 0))
            pixels, width = canvas.pixels(), plan["size"][0]

            def pixel(x, y):
                index = (y * width + x) * 4
                return pixels[index + 2], pixels[index + 1], pixels[index]

            halo = next(item for item in plan["items"] if item["kind"] == "halo")
            cx, cy = int(halo["cx"]), int(halo["cy"])
            self.assertEqual(pixel(cx, cy), brand.rgb(brand.LIGHT["paused"]))
            for distance in (9, 12, 15):
                self.assertEqual(pixel(cx + distance, cy), brand.rgb(brand.LIGHT["surface"]))
        finally:
            renderer.close()

    def test_high_contrast_is_system_colours_with_no_shadow_and_no_glow(self):
        renderer = popup.Renderer()
        try:
            renderer.contrast = True
            vm = popup.view_model(self.ROWS, STATUS, EN, NOW)
            plan = renderer.layout(vm, 1.0, "en")
            canvas = renderer.draw(vm, plan, frame=popup.halo(vm["state"], 0, reduced=True))
            pixels, width = canvas.pixels(), plan["size"][0]

            def pixel(x, y):
                index = (y * width + x) * 4
                return pixels[index + 2], pixels[index + 1], pixels[index]

            ground, window = popup.system_rgb("Control"), popup.system_rgb("Window")
            card = plan["card"]
            middle_y = (card[1] + card[3]) // 2
            self.assertEqual(pixel(1, 1), ground)
            self.assertEqual(pixel(card[2] + 5, middle_y), ground)
            self.assertEqual(pixel(card[0] - 6, middle_y), ground)
            self.assertEqual(pixel(card[0] + 30, card[1] + 3), window)
            halo = next(item for item in plan["items"] if item["kind"] == "halo")
            cx, cy = int(halo["cx"]), int(halo["cy"])
            self.assertEqual(pixel(cx, cy), popup.system_rgb(brand.status_system(vm["state"])))
            self.assertEqual(pixel(cx + 7, cy), window)
        finally:
            renderer.close()

    def test_high_contrast_holds_the_glow_still(self):
        window = self.make()
        original = popup.high_contrast
        popup.high_contrast = lambda: True
        try:
            window.show(activate=False, origin=(-32000, -32000))
            self.pump(0.2)
            self.assertEqual(window._vm["state"], "recovering")          # a state that breathes
            self.assertTrue(window._reduced)
            self.assertFalse(window._frame_running)
            self.assertTrue(window._renderer.contrast)
        finally:
            popup.high_contrast = original
            window.destroy()

    def test_the_renderer_lets_go_of_every_gdiplus_object(self):
        """GetGuiResources cannot see GDI+, so the module counts its own objects."""
        before = popup.gdiplus_objects()
        renderer = popup.Renderer()
        try:
            vm = popup.view_model(self.ROWS, STATUS, EN, NOW)
            held = {}
            for scale in (1.0, 1.5, 1.0, 1.5):
                plan = renderer.layout(vm, scale, "en")
                for options in ({}, {"hover": ("dashboard",)}, {"pressed": ("toggle",)}, {"focus": ("toggle",)}):
                    renderer.draw(vm, plan, frame=popup.halo("checking", 400), **options)
                    renderer.draw_halo(plan, popup.halo("monitoring", 900))
                count = popup.gdiplus_objects() - before
                # The shadow images of one scale are kept, and nothing else outlives a frame.
                self.assertGreater(count, 0)
                self.assertEqual(held.setdefault(scale, count), count, scale)
            renderer.contrast = True
            renderer.draw(vm, plan, frame=popup.halo("checking", 400, reduced=True))
        finally:
            renderer.close()
        self.assertEqual(popup.gdiplus_objects(), before)

    def test_rows_notices_and_a_pause_add_no_shadow_image(self):
        """The card's height comes and goes all day; the renderer holds one image per distinct shape."""
        rows = self.ROWS + [row("e", eligible=NOW - 1, name="Due now")]
        before = popup.gdiplus_objects()
        renderer = popup.Renderer()
        sizes, held = set(), []
        try:
            for _ in range(2):
                for count in range(len(rows) + 1):
                    for paused in (False, True):
                        for notice in (None, EN["popup.stale"]):
                            vm = popup.view_model(rows[:count], dict(STATUS, enabled=not paused), EN, NOW,
                                                  notice=notice)
                            plan = renderer.layout(vm, 1.0, "en")
                            sizes.add(plan["size"])
                            renderer.draw(vm, plan, frame=popup.halo(vm["state"], 0))
                            for item in plan["items"]:
                                if item["kind"] == "button":
                                    renderer.draw(vm, plan, frame=popup.halo(vm["state"], 0),
                                                  pressed=item["target"])
                held.append(popup.gdiplus_objects() - before)
            shapes = {(image.width, image.height, bytes(image._pixels)) for image in renderer._images.values()}
        finally:
            renderer.close()
        self.assertEqual(popup.gdiplus_objects(), before)
        self.assertGreaterEqual(len(sizes), 6)                 # the card really did change height
        self.assertEqual(held, [len(shapes)] * 2, "%d window sizes" % len(sizes))

    def test_single_line_text_is_never_shortened_except_names_and_chips(self):
        """Measured by GDI itself, at every scale Windows offers, in every language."""
        renderer = popup.Renderer()
        rows = self.ROWS + [row("e", eligible=NOW + 5)]
        try:
            for locale in l10n.LOCALES:
                strings = interface.STRINGS[locale]
                for scale in (1.0, 1.25, 1.5, 1.75, 2.0):
                    vm = popup.view_model(rows, dict(STATUS, enabled=False), strings, NOW,
                                          notice=strings["popup.stale"])
                    plan = renderer.layout(vm, scale, locale)
                    for item in plan["items"]:
                        if item["kind"] != "text" or item["wrap"] or item["role"] in ("name", "chip"):
                            continue
                        left, _, right, _ = item["rect"]
                        natural = renderer.measure(item["role"], item["text"], right - left, False)[0]
                        with self.subTest(locale=locale, scale=scale, text=item["text"]):
                            self.assertLessEqual(natural, right - left)
        finally:
            renderer.close()

    def test_korean_breaks_between_words_and_never_inside_one(self):
        renderer = popup.Renderer()
        try:
            strings = interface.STRINGS["ko"]
            renderer.use("ko", 1.0)
            self.assertIn("\n", renderer.lines("body", strings["popup.resume_usage"], 140))
            for key in ("popup.resume_usage", "popup.stale", "popup.zero_note", "action.pause"):
                for width in (90, 140, 200, 260):
                    with self.subTest(key=key, width=width):
                        wrapped = renderer.lines("body", strings[key], width)
                        self.assertEqual(wrapped.replace("\n", " "), strings[key])
            renderer.use("en", 1.0)
            self.assertEqual(renderer.lines("body", EN["popup.stale"], 120), EN["popup.stale"])
        finally:
            renderer.close()

    def test_the_window_is_created_rendered_and_destroyed_without_leaking(self):
        self.cycle_and_measure(lambda: self._create_render_destroy())

    def _create_render_destroy(self):
        window = self.make()
        try:
            window.render()
        finally:
            window.destroy()
        self.pump(0.005)

    def test_opening_and_closing_it_many_times_holds_nothing(self):
        window = self.make()
        try:
            self.cycle_and_measure(lambda: self.cycle(window, keyboard=True))
            self.assertFalse(window._frame_running)
        finally:
            window.destroy()

    def test_the_badge_icon_is_made_and_released(self):
        import ctypes
        user32 = ctypes.WinDLL("user32")
        user32.LoadImageW.restype = ctypes.c_void_p
        user32.LoadImageW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_int,
                                      ctypes.c_int, ctypes.c_uint]
        user32.DestroyIcon.argtypes = [ctypes.c_void_p]
        base = user32.LoadImageW(None, str(ROOT / "assets" / "codex-auto-resume.ico"), 1, 32, 32, 0x10)
        self.assertTrue(base)
        try:
            def once():
                badge = popup.badge_icon(base, "waiting")
                self.assertTrue(badge)
                user32.DestroyIcon(badge)
            self.cycle_and_measure(once)
        finally:
            user32.DestroyIcon(base)

    def test_the_badge_icon_is_the_badge_drawn_into_the_icon_s_own_pixels(self):
        import ctypes
        user32 = ctypes.WinDLL("user32")
        user32.LoadImageW.restype = ctypes.c_void_p
        user32.LoadImageW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_int,
                                      ctypes.c_int, ctypes.c_uint]
        user32.DestroyIcon.argtypes = [ctypes.c_void_p]
        popup._declare()
        gdi32 = popup._dll("gdi32")

        def colour_pixels(icon):
            info = popup.ICONINFO()
            self.assertTrue(popup._dll("user32").GetIconInfo(icon, ctypes.byref(info)))
            try:
                shape = popup.BITMAP()
                self.assertTrue(gdi32.GetObjectW(info.hbmColor, ctypes.sizeof(popup.BITMAP), ctypes.byref(shape)))
                return popup._read_pixels(info.hbmColor, shape.bmWidth, abs(shape.bmHeight)), shape.bmWidth
            finally:
                gdi32.DeleteObject(info.hbmColor)
                gdi32.DeleteObject(info.hbmMask)

        for size in (16, 32):
            base = user32.LoadImageW(None, str(ROOT / "assets" / "codex-auto-resume.ico"), 1, size, size, 0x10)
            self.assertTrue(base)
            try:
                original, width = colour_pixels(base)
                self.assertTrue(any(original[3::4]))                   # the icon carries its own alpha
                for token in ("waiting", "active", "paused", "attention"):
                    with self.subTest(size=size, token=token):
                        expected = bytearray(original)
                        popup.composite_badge(expected, width, len(original) // (4 * width),
                                              brand.rgb(brand.LIGHT[token]))
                        badge = popup.badge_icon(base, token)
                        try:
                            self.assertEqual(colour_pixels(badge)[0], expected)
                        finally:
                            user32.DestroyIcon(badge)
            finally:
                user32.DestroyIcon(base)

    def test_a_new_language_rebuilds_the_fonts_on_the_next_frame(self):
        window = self.make()
        try:
            window.render()
            self.assertEqual(window.locale, "en")
            window.set_strings(interface.STRINGS["ko"])
            window._rebuild(time.time())
            window.render()
            self.assertEqual(window.locale, "ko")
            self.assertEqual(window._renderer.fonts.faces["body"], "Malgun Gothic")
            self.assertEqual(window._vm["dashboard_text"], interface.STRINGS["ko"]["popup.open_dashboard"])
        finally:
            window.destroy()

    def test_a_refused_click_in_the_real_window_changes_nothing(self):
        window = self.make()
        window.control.refuse = "already_finished"
        try:
            window.show(activate=False, origin=(-32000, -32000))
            self.pump(0.2)
            before = copy.deepcopy(window.model.rows)
            window._activate(("check", "b" * 64))
            deadline = time.monotonic() + 3
            while window.model.notice_key is None and time.monotonic() < deadline:
                self.pump(0.02)
            self.assertEqual(window.model.notice_key, "popup.stale")
            self.assertEqual(window._vm["notice"], EN["popup.stale"])
            self.assertEqual(window.model.rows, before)
            self.assertIn(("set_interruption_recovery", "b" * 64, OTHER_THREAD, False), window.control.calls)
        finally:
            window.destroy()

    def test_tab_moves_the_focus_space_uses_it_and_escape_closes_the_window(self):
        # The messages a key press becomes, delivered to the real window procedure.
        import ctypes
        user32 = ctypes.WinDLL("user32")
        user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
        window = self.make()
        try:
            window.show(activate=False, origin=(-32000, -32000))
            self.pump(0.2)
            self.assertTrue(window.visible)
            order = popup.focus_order(window._plan["targets"])
            user32.SendMessageW(window.hwnd, popup.WM_KEYDOWN, popup.VK_TAB, 0)
            self.assertEqual(window.focus, order[0])
            self.assertTrue(window.keyboard)
            user32.SendMessageW(window.hwnd, popup.WM_KEYDOWN, popup.VK_TAB, 0)
            self.assertEqual(window.focus, order[1])
            self.assertEqual(order[1][0], "check")
            user32.SendMessageW(window.hwnd, popup.WM_KEYDOWN, popup.VK_SPACE, 0)

            def switched():
                return [call for call in window.control.calls
                        if call[0] == "set_interruption_recovery" and call[1] == order[1][1]]
            deadline = time.monotonic() + 3
            while not switched() and time.monotonic() < deadline:
                self.pump(0.02)
            self.assertEqual(len(switched()), 1)
            self.pump(0.3)                              # the answer is in; the switch is free again
            # Holding the key: Windows repeats the key-down with the was-down bit set. One
            # press is one change, however long the key is held.
            for _ in range(3):
                user32.SendMessageW(window.hwnd, popup.WM_KEYDOWN, popup.VK_SPACE, popup.KEY_WAS_DOWN)
                self.pump(0.1)
            self.assertEqual(len(switched()), 1)
            user32.SendMessageW(window.hwnd, popup.WM_KEYDOWN, popup.VK_ESCAPE, 0)
            self.assertFalse(window.visible)
        finally:
            window.destroy()

    def test_a_click_is_aimed_at_the_layout_on_screen_not_one_still_to_be_painted(self):
        window = self.make()
        try:
            window.show(activate=False, origin=(-32000, -32000))
            self.pump(0.2)
            painted = window._plan
            self.assertIs(window._painted_plan, painted)
            target, (left, top, right, bottom) = painted["targets"][0]
            self.assertEqual(target[0], "check")
            x, y = (left + right) // 2, (top + bottom) // 2
            # A read takes that task away and the layout is rebuilt, but not yet painted.
            window.model.rows = [item for item in window.model.rows if item["interruption_id"] != target[1]]
            window._rebuild(time.time())
            self.assertNotEqual(popup.hit_test(window._plan["targets"], x, y), target)
            self.assertEqual(window._hit((y << 16) | x), target)
            window._invalidate()
            self.pump(0.2)
            self.assertIs(window._painted_plan, window._plan)
            self.assertEqual(window._hit((y << 16) | x), popup.hit_test(window._plan["targets"], x, y))
        finally:
            window.destroy()

    def still_window(self, **options):
        """A popup with nothing in flight - waiting, no glow that moves - shown off screen, with
        motion allowed whatever this machine's own animation setting is."""
        patcher = unittest.mock.patch.object(popup, "reduced_motion", lambda: False)
        patcher.start()
        self.addCleanup(patcher.stop)
        window = popup.Popup(control=FakeControl(self.ROWS[:3], **options), strings=EN)
        window.create()
        window.model.apply_outcome(("read",), popup.perform(("read",), window.control), time.time())
        window.show(activate=False, origin=(-32000, -32000))
        self.pump(0.2)
        if window._contrast:                      # High Contrast still holds everything still
            window.destroy()
            self.skipTest("High Contrast is on: nothing glides")
        window._reduced = False
        self.assertEqual(window._vm["state"], "waiting")
        self.assertFalse(window._frame_running)
        return window

    def test_a_switch_glides_only_once_its_change_is_confirmed_and_then_the_timer_stops(self):
        window = self.still_window()
        target = ("check", "b" * 64)
        try:
            self.assertTrue(window._switches[target])
            window._activate(target)
            # Asked, not yet answered: faded where it was, not moving.
            self.assertEqual(window._glides, {})
            self.assertTrue(next(item for item in window._plan["items"]
                                 if item["kind"] == "switch" and item["target"] == target)["busy"])
            deadline = time.monotonic() + 3
            while target not in window._glides and time.monotonic() < deadline:
                self.pump(0.005)
            self.assertIn(target, window._glides)
            started, begin, end = window._glides[target]
            self.assertEqual((begin, end), (1.0, 0.0))
            self.assertTrue(window._frame_running)
            deadline = time.monotonic() + 2
            while (window._glides or window._frame_running) and time.monotonic() < deadline:
                self.pump(0.02)
            self.assertEqual(window._glides, {})
            self.assertFalse(window._frame_running, "a timer is left running with nothing moving")
            self.assertFalse(window._switches[target])
        finally:
            window.destroy()

    def test_a_refused_change_never_moves_the_switch(self):
        window = self.still_window(refuse="already_finished")
        target = ("check", "b" * 64)
        try:
            window._activate(target)
            deadline = time.monotonic() + 3
            while window.model.notice_key is None and time.monotonic() < deadline:
                self.pump(0.01)
                self.assertEqual(window._glides, {})
            self.assertEqual(window.model.notice_key, "popup.stale")
            self.pump(0.2)
            self.assertEqual(window._glides, {})
            self.assertTrue(window._switches[target])
        finally:
            window.destroy()

    def test_with_motion_reduced_a_confirmed_change_is_simply_drawn_there(self):
        window = self.still_window()
        window._reduced = True                    # Reduce motion, Windows' animation setting or High Contrast
        target = ("check", "b" * 64)
        try:
            window._activate(target)
            deadline = time.monotonic() + 3
            while window._switches.get(target) is not False and time.monotonic() < deadline:
                self.pump(0.01)
                self.assertEqual(window._glides, {})
            self.assertIs(window._switches[target], False)
            self.assertFalse(window._frame_running)
        finally:
            window.destroy()

    def test_a_glide_s_ends_are_the_switch_as_it_is_drawn_at_rest(self):
        renderer = popup.Renderer()
        try:
            for theme in ("light", "dark"):
                renderer.theme = theme
                vm = popup.view_model(self.ROWS, STATUS, EN, NOW)
                plan = renderer.layout(vm, 1.25, "en")
                switches = [item for item in plan["items"] if item["kind"] == "switch"]
                rest = renderer.draw(vm, plan).pixels()
                ends = {item["target"]: 1.0 if item["checked"] else 0.0 for item in switches}
                with self.subTest(theme=theme):
                    self.assertEqual(renderer.draw(vm, plan, glides=ends).pixels(), rest)
                    # Halfway, the knob is halfway along its travel and the track between its looks.
                    on = next(item for item in switches if item["checked"])
                    middle = renderer.draw(vm, plan, glides={on["target"]: 0.5}).pixels()
                    self.assertNotEqual(middle, rest)
                    left, top, right, bottom = on["rect"]
                    width = plan["size"][0]
                    knob = round(brand.LAYOUT["knob"] * 1.25)
                    start = left + round(brand.LAYOUT["knob_inset"] * 1.25)
                    travel = round(brand.LAYOUT["knob_travel"] * 1.25)
                    centre = int(start + travel * 0.5 + knob / 2.0)
                    y = (top + bottom) // 2
                    index = (y * width + centre) * 4
                    knob_colour = tuple(middle[index + 2 - part] for part in range(3))
                    tokens = brand.palette(theme)
                    off, lit = brand.rgb(tokens["muted"]), brand.rgb(tokens["on_accent"])
                    expected = tuple(int(round(a + (b - a) * 0.5)) for a, b in zip(off, lit))
                    for got, want in zip(knob_colour, expected):
                        self.assertLessEqual(abs(got - want), 2, (knob_colour, expected))
        finally:
            renderer.close()

    def test_a_closed_popup_does_not_hold_the_badge_on_attention(self):
        import ctypes
        from types import SimpleNamespace
        user32 = ctypes.WinDLL("user32")
        user32.LoadImageW.restype = ctypes.c_void_p
        user32.LoadImageW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_int,
                                      ctypes.c_int, ctypes.c_uint]
        user32.DestroyIcon.argtypes = [ctypes.c_void_p]
        base = user32.LoadImageW(None, str(ROOT / "assets" / "codex-auto-resume.ico"), 1, 32, 32, 0x10)
        self.assertTrue(base)
        stale = dict(STATUS, watcher=dict(STATUS["watcher"], ticking=False))
        window = popup.Popup(control=FakeControl([], stale), strings=EN)
        window.model.apply_outcome(("read",), popup.perform(("read",), window.control), time.time())
        self.assertTrue(window.attention())
        icon = SimpleNamespace(_icon=base, _popup=window, _badge=None, _badge_token=None, _shown_icon=None,
                               log=lambda message: None)
        snapshot = {"enabled": True, "waiting": 0, "running": 0, "next_at": None}
        try:
            window.visible = False
            tray.Tray._badge_for(icon, snapshot)
            self.assertNotEqual(icon._badge_token, "attention")
            window.visible = True
            tray.Tray._badge_for(icon, snapshot)
            self.assertEqual(icon._badge_token, "attention")
        finally:
            if icon._badge:
                user32.DestroyIcon(icon._badge)
            user32.DestroyIcon(base)

    def test_the_icon_starts_with_the_popup_wired_and_stops_cleanly(self):
        icon = tray.Tray(icon_path=ROOT / "assets" / "codex-auto-resume.ico", strings=EN,
                         control=FakeControl(self.ROWS))
        self.assertTrue(icon.start())
        try:
            icon.update({"enabled": True, "waiting": 2, "running": 0, "next_at": time.time() + 60})
            deadline = time.monotonic() + 5

            def badged_frame():
                key = icon._frame_key
                return bool(icon._frame_icon) and key is not None and key[2] == "waiting"
            while not badged_frame() and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertEqual(icon._badge_token, "waiting")
            # Since v0.6.5 the icon is shown as a composed frame carrying the badge, and the badged
            # copy of the .ico it was shown as until its frame table was built has been let go.
            self.assertTrue(badged_frame())
            self.assertIsNone(icon._badge)
        finally:
            icon.stop()
        self.assertFalse(icon._thread.is_alive())
        self.assertIsNone(icon._badge)
        self.assertIsNone(icon._frame_icon)

    def cycle_and_measure(self, action, rounds=50):
        action()                                       # warm caches: fonts, GDI+, classes, shadow images
        self.pump(0.02)
        before = popup.gui_resources()
        drawing = popup.gdiplus_objects()
        for _ in range(rounds):
            action()
        self.pump(0.05)
        after = popup.gui_resources()
        self.assertLessEqual(after[0] - before[0], 2, "GDI objects grew from %d to %d" % (before[0], after[0]))
        self.assertLessEqual(after[1] - before[1], 2, "USER objects grew from %d to %d" % (before[1], after[1]))
        self.assertEqual(popup.gdiplus_objects(), drawing,
                         "GDI+ objects went from %d to %d" % (drawing, popup.gdiplus_objects()))


class ReduceMotionSettingTests(unittest.TestCase):
    """The product's own Reduce motion setting stops the popup's motion, whatever Windows says."""

    def tearDown(self):
        popup.set_reduce_motion(False)

    def test_the_setting_wins_over_windows(self):
        popup.set_reduce_motion(True)
        self.assertTrue(popup.reduced_motion())

    def test_only_true_turns_it_on(self):
        for value in (False, None, "true", 1):
            with self.subTest(value=value):
                popup.set_reduce_motion(value)
                self.assertIs(popup._reduce_motion_setting, False)


if __name__ == "__main__":
    unittest.main()
