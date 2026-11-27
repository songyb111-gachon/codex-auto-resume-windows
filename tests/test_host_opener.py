"""Twins of the opener tests whose subject is the wiring to the opener, not the opener (S6.4e).

On the port the icon's menu, the popup and a notification reach the Dashboard through one posted action of the C# host
(gui/ISurfaces.cs `HostActions.OpenDashboard`, `Toggle`), which car-watcher's action table (rust/crates/car-watcher/src/api.rs)
hands to the opener (dashboard.rs) or to the control layer. The Python tests hold that wiring in the Python watcher
(runtime/app.py) and the Python icon's menu (ui/tray/menu.py `MenuMixin._act`); these hold the same rule where the port
writes it: the host's own C# (gui/host.sources) and the watcher's Rust. The opener itself runs on the port through the shim
(tests/rustdiff/surfaceproxy.py, the opener's proxy; diffs_ui_opener.py holds it to the tag).
"""
from __future__ import annotations

from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

import guiscan  # noqa: E402


def code(text: str) -> str:
    """The text without its comments, and its runs of space as one."""
    text = re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", text, flags=re.S))
    return re.sub(r"\s+", " ", text)


def arm(text: str, start: str, end: str) -> str:
    """The match arm of api.rs `Host::act` that begins with `start`, up to the arm that follows it (`end`)."""
    at = text.index(start)
    return text[at:text.index(end, at)]


def api() -> str:
    return code((ROOT / "rust" / "crates" / "car-watcher" / "src" / "api.rs").read_text(encoding="utf-8"))


def member(type_name: str, name: str, source: str) -> str:
    """One method of a host type, by its braces, in the one host file that writes it (guiscan's own rule: a declaration, a
    return type right before the name, which may be generic)."""
    body = guiscan.type_body(type_name, (ROOT / source).read_text(encoding="utf-8"))
    found = re.search(r"(?m)^[ \t]*(?:(?:%s)[ \t]+)*[\w\.]+(?:<[^<>()]*>)?(?:\[\])?\??[ \t]+%s[ \t]*\("
                      % ("|".join(guiscan.MODIFIERS), re.escape(name)), body)
    if found is None:
        raise AssertionError("%s has no member %s in %s" % (type_name, name, source))
    return guiscan._block(body, found.start())


def act() -> str:
    """TrayMenu.cs's `Act`: what the icon's menu does with a choice."""
    return code(member("TrayIcon", "Act", "gui/TrayMenu.cs"))


class PauseResumeTwinTests(unittest.TestCase):
    """Twins of tests/test_tray_reuses_window.py PauseResumeTests."""

    def test_pause_and_resume_from_the_menu_act_directly_and_open_no_window(self):
        """Pause and Resume are the icon's own toggle with the state the menu was drawn in, and open no window: the
        choice posts Toggle with `paused` and nothing else."""
        body = act()
        toggle = re.search(r"if \(chosen == MenuToggle\) (.*?);", body)
        self.assertIsNotNone(toggle, body[:400])
        self.assertEqual(toggle.group(1),
                         'Post(HostActions.Toggle, new Dictionary<string, object> { { "paused", paused } })')
        self.assertEqual(body.count("HostActions.Toggle"), 1)
        self.assertNotIn("OpenDashboard", toggle.group(1))

    def test_the_watchers_toggle_changes_the_paused_state_and_starts_nothing(self):
        """The watcher's toggle (on_toggle(paused): paused -> resume, running -> pause) sets the enabled state to the drawn
        `paused` and does nothing else: no hand-over, no start."""
        toggle = arm(api(), '"toggle" | "disarm_power" =>', '"popup" =>')
        self.assertIn('let paused = fields.get("paused").is_some_and(car_machine::pyval::truthy); '
                      'control.set_enabled(paused).is_ok()', toggle)
        for never in ("dashboard", "hand_over", "start", "Spawn"):
            self.assertNotIn(never, toggle)


class RowWiringTwinTests(unittest.TestCase):
    """Twin of tests/test_popup_row_menu_parity.py OpensTheDashboardTests' "the watcher wires the popup to the opener with
    its row" (runtime/app.py: `on_dashboard=lambda row=None: tray.open_dashboard(home, "pending", row=row)`)."""

    def test_the_watcher_wires_the_popup_to_the_opener_with_its_row(self):
        fields = code(member("PopupWindow", "Fields", "gui/PopupMessages.cs"))
        self.assertIn('if (kind == "dashboard_row" && action.Count == 4 && Array.IndexOf(RowDialogs, action[1] as string) >= 0) '
                      '{ name = HostActions.OpenDashboard; return new Dictionary<string, object> { { "page", "pending" }, '
                      '{ "row", new List<object> { action[1], action[2], action[3] } } }; }', fields)
        self.assertIn('if (kind == "dashboard") { name = HostActions.OpenDashboard; return new Dictionary<string, object> '
                      '{ { "page", "pending" }, { "row", null } }; }', fields)
        opener = arm(api(), '"open_dashboard" | "open_chat" =>', '"notice_action" =>')
        self.assertIn('let row = fields.get("row").filter(|row| !matches!(row, Value::Null)); '
                      'crate::dashboard::open_dashboard(home, page, row)', opener)
        self.assertIn('Some(Value::Str(page)) => page.as_str(),', opener)


if __name__ == "__main__":
    unittest.main()
