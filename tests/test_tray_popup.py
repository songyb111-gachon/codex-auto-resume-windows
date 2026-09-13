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
import os
from pathlib import Path
import re
import time
import unittest

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
                    self.assertEqual(width, round(popup.WIDTH * scale))
                    card = plan["card"]
                    for item in plan["items"]:
                        rect = item.get("rect")
                        if rect is None or item["kind"] in ("card", "focusable"):
                            continue
                        self.assertGreaterEqual(rect[0], card[0], item)
                        self.assertGreaterEqual(rect[1], card[1], item)
                        self.assertLessEqual(rect[2], card[2], item)
                        self.assertLessEqual(rect[3], card[3], item)
                    self.assertLessEqual(card[3], height)

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


# ------------------------------------------------------------------------------- motion
class MotionTests(unittest.TestCase):
    LOW, HIGH = brand.HALO["min_opacity"], brand.HALO["max_opacity"]
    MIDDLE = (LOW + HIGH) / 2
    BREATHE, PULSE = brand.MOTION["breathe_ms"], brand.MOTION["attention_ms"]

    def test_monitoring_breathes_slowly_between_the_two_opacities(self):
        self.assertAlmostEqual(popup.halo("monitoring", 0)["opacity"], self.LOW)
        self.assertAlmostEqual(popup.halo("monitoring", self.BREATHE / 2)["opacity"], self.HIGH)
        self.assertAlmostEqual(popup.halo("monitoring", self.BREATHE)["opacity"], self.LOW)
        for elapsed in range(0, self.BREATHE, 97):
            frame = popup.halo("monitoring", elapsed)
            self.assertTrue(self.LOW - 1e-9 <= frame["opacity"] <= self.HIGH + 1e-9)
        self.assertTrue(popup.animates("monitoring"))

    def test_waiting_is_a_still_soft_halo(self):
        frames = {tuple(sorted(popup.halo("waiting", elapsed).items())) for elapsed in range(0, 5000, 333)}
        self.assertEqual(len(frames), 1)
        self.assertAlmostEqual(popup.halo("waiting", 0)["opacity"], self.MIDDLE)
        self.assertFalse(popup.animates("waiting"))

    def test_checking_turns_a_small_arc(self):
        first, later = popup.halo("checking", 0)["arc"], popup.halo("checking", self.PULSE / 4)["arc"]
        self.assertAlmostEqual(later - first, 90.0)
        self.assertTrue(popup.animates("checking"))

    def test_recovering_pulses_harder_and_faster_than_monitoring_breathes(self):
        recovering = max(popup.halo("recovering", elapsed)["opacity"] for elapsed in range(0, self.PULSE, 10))
        monitoring = max(popup.halo("monitoring", elapsed)["opacity"] for elapsed in range(0, self.BREATHE, 10))
        self.assertGreater(recovering, monitoring)
        self.assertLess(self.PULSE, self.BREATHE)
        self.assertAlmostEqual(popup.halo("recovering", 0)["opacity"], popup.halo("recovering", self.PULSE)["opacity"])

    def test_paused_has_no_halo_and_nothing_moves(self):
        self.assertIsNone(popup.halo("paused", 1234))
        self.assertIsNone(popup.halo("paused", 1234, reduced=True))
        self.assertFalse(popup.animates("paused"))

    def test_attention_pulses_once_when_it_arrives_and_then_holds_still(self):
        during = popup.halo("attention", 0, since_entered_ms=self.PULSE / 2)
        self.assertGreater(during["opacity"], self.MIDDLE)
        after = popup.halo("attention", 0, since_entered_ms=self.PULSE * 3)
        self.assertAlmostEqual(after["opacity"], self.MIDDLE)
        self.assertTrue(popup.animates("attention", self.PULSE / 2))
        self.assertFalse(popup.animates("attention", self.PULSE + 1))

    def test_reduced_motion_never_loops_or_pulses(self):
        for state in popup.STATES:
            with self.subTest(state):
                self.assertFalse(popup.animates(state, 0, reduced=True))
                if state == "paused":
                    continue
                for elapsed in (0, 400, 1200, 2400, 9999):
                    frame = popup.halo(state, elapsed, since_entered_ms=elapsed, reduced=True)
                    self.assertEqual(frame, {"opacity": self.MIDDLE, "scale": 1.0, "arc": None})


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


class FontTests(unittest.TestCase):
    def test_each_script_has_its_own_face(self):
        self.assertEqual(popup.font_faces("ko")[0], "Malgun Gothic")
        self.assertEqual(popup.font_faces("ja")[0], "Yu Gothic UI")
        self.assertEqual(popup.font_faces("zh-CN")[0], "Microsoft YaHei UI")
        self.assertEqual(popup.font_faces("zh-TW")[0], "Microsoft JhengHei UI")
        for locale in ("en", "de", "fr", "es", "pt-BR"):
            self.assertEqual(popup.font_faces(locale)[0], "Segoe UI Variable Text")
        for locale in l10n.LOCALES:
            self.assertEqual(popup.font_faces(locale)[-1], "Segoe UI")
            for weight in (400, 600):
                self.assertEqual(popup.font_candidates(locale, weight)[-1][0], "Segoe UI")

    def test_semibold_is_asked_for_by_name_where_gdi_would_otherwise_embolden(self):
        self.assertEqual(popup.font_candidates("en", 600)[0], ("Segoe UI Variable Text Semibold", 400))
        self.assertEqual(popup.font_candidates("ja", 600)[0], ("Yu Gothic UI Semibold", 400))
        self.assertEqual(popup.font_candidates("ko", 600)[0], ("Malgun Gothic", 700))

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

            self.assertEqual(pixel(1, 1), brand.rgb(brand.LIGHT["canvas"]))
            left, top, right, bottom = dict(plan["targets"])[("dashboard",)]
            self.assertEqual(pixel(left + 6, (top + bottom) // 2), brand.rgb(brand.LIGHT["accent"]))
            card = plan["card"]
            self.assertEqual(pixel(card[0] + 30, card[1] + 3), brand.rgb(brand.LIGHT["surface"]))
        finally:
            renderer.close()

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
            deadline = time.monotonic() + 3
            while icon._badge_token != "waiting" and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertEqual(icon._badge_token, "waiting")
            self.assertTrue(icon._badge)
        finally:
            icon.stop()
        self.assertFalse(icon._thread.is_alive())
        self.assertIsNone(icon._badge)

    def cycle_and_measure(self, action, rounds=50):
        action()                                       # warm caches: fonts, GDI+, classes
        self.pump(0.02)
        before = popup.gui_resources()
        for _ in range(rounds):
            action()
        self.pump(0.05)
        after = popup.gui_resources()
        self.assertLessEqual(after[0] - before[0], 2, "GDI objects grew from %d to %d" % (before[0], after[0]))
        self.assertLessEqual(after[1] - before[1], 2, "USER objects grew from %d to %d" % (before[1], after[1]))


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
