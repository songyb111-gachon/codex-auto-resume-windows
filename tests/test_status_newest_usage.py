"""v0.6.26 final: every surface that says the last usage reading says the same one, the newest.

The live acceptance of 2026-11-24 saw the tray popup say the advanced usage meter's reading (5-hour 88% left) while the
Dashboard's Overview and Diagnostics said the watcher's older one (100% left): the popup took the newest of the two
(ui/popup/model.newest_reading), the Dashboard, the panel and the checkup only the watcher's `usage`. Now the status
itself carries the newest under the watcher's `usage` (control/watcher.get_status, by domain/usage.newest, the one
rule the popup asks too), so every reader of the status says the same reading. The standard edition's plug adds
nothing, so its status is exactly what it was.

    PYTHONPATH=src;tests python -m unittest test_status_newest_usage
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from codex_auto_resume import control  # noqa: E402
from codex_auto_resume.control import wire  # noqa: E402
from codex_auto_resume.domain import usage as usage_rule  # noqa: E402
from codex_auto_resume.domain.plug import EXTRA, Edition, Plug, Surface  # noqa: E402
from codex_auto_resume.ui.popup import model  # noqa: E402
from test_control import ControlTestCase  # noqa: E402

NOW = 1_800_000_000
WATCHER = {"read_at": NOW - 4 * 86400, "windows": [
    {"bucket": "codex", "window": "primary", "used_percent": 0, "window_minutes": 300, "reset_at": NOW + 3600},
    {"bucket": "codex", "window": "secondary", "used_percent": 0, "window_minutes": 10080, "reset_at": NOW + 86400}]}
METER = {"read_at": NOW - 4 * 86400 + 600, "notices": [], "windows": [
    {"bucket": "codex", "window_minutes": 300, "used_percent": 12, "reset_at": NOW + 3600, "band": "none"},
    {"bucket": "codex", "window_minutes": 10080, "used_percent": 2, "reset_at": NOW + 86400, "band": "none"}]}


# The meter's windows as core keeps a window: the slot the watcher's reading gave each, the band left out.
SHAPED = [{"bucket": "codex", "window": "primary", "used_percent": 12, "window_minutes": 300, "reset_at": NOW + 3600},
          {"bucket": "codex", "window": "secondary", "used_percent": 2, "window_minutes": 10080, "reset_at": NOW + 86400}]


class MeterPlug(Plug):
    """An advanced edition's plug whose usage meter last read `meter`, as its STATUS surface adds it."""
    __slots__ = ("meter",)
    edition = Edition.ADVANCED
    badge = "Advanced"

    def __init__(self, meter):
        self.meter = meter

    def surface(self, name, facts):
        return {"meter": self.meter} if name == Surface.STATUS else {}


class StatusTests(ControlTestCase):
    def status(self, plug=None, reading=WATCHER):
        made = control.Control(self.paths, plug=plug) if plug is not None else self.control
        own = control.Control._watcher

        def watcher(this, store):
            return dict(own(this, store), usage=reading)
        with patch.object(control.Control, "_watcher", watcher):
            return made.get_status()

    def test_the_status_carries_the_meters_reading_where_it_is_newer(self):
        status = self.status(MeterPlug(METER))
        self.assertEqual(status["watcher"]["usage"], {"read_at": METER["read_at"], "windows": SHAPED})
        # The meter's own fields stay where the plug put them.
        self.assertEqual(status[EXTRA]["meter"], METER)

    def test_every_surface_then_says_the_one_reading(self):
        status = self.status(MeterPlug(METER))
        # The popup's rule over the status is the status's own reading; the Dashboard, the panel and the checkup read
        # that same `watcher.usage` (gui/DashboardData.cs WaitingLine, mcp/assets/panel.js, checkup._usage).
        self.assertEqual(model.newest_reading(status), status["watcher"]["usage"])

    def test_the_advanced_status_keeps_cores_wire_type_and_allowlist(self):
        """watcher.usage is a wire.UsageReading whichever reading it is: every window exactly UsageWindow's keys, and
        what core's own allowlist (domain/usage.windows_of) keeps - the meter's band never reaches it."""
        declared = set(wire.UsageWindow.__annotations__)
        for reading in (WATCHER, None):
            with self.subTest(watcher=reading is not None):
                usage = self.status(MeterPlug(METER), reading)["watcher"]["usage"]
                self.assertEqual(set(usage), set(wire.UsageReading.__annotations__))
                for window in usage["windows"]:
                    self.assertEqual(set(window), declared)
                self.assertEqual(usage_rule.windows_of(usage), usage["windows"])

    def test_a_meter_reading_core_cannot_keep_leaves_the_watchers(self):
        broken = dict(METER, windows=[dict(METER["windows"][0], used_percent="12")])
        self.assertEqual(self.status(MeterPlug(broken))["watcher"]["usage"], WATCHER)
        odd = dict(METER, windows=[dict(METER["windows"][0], window_minutes=300.5)])
        self.assertEqual(self.status(MeterPlug(odd))["watcher"]["usage"], WATCHER)

    def test_the_watchers_reading_stays_where_it_is_newer(self):
        newer = dict(WATCHER, read_at=METER["read_at"] + 1)
        self.assertEqual(self.status(MeterPlug(METER), newer)["watcher"]["usage"], newer)

    def test_the_standard_editions_status_is_what_it_was(self):
        status = self.status()
        self.assertEqual(status["watcher"]["usage"], WATCHER)
        self.assertNotIn(EXTRA, status)
        self.assertIsNone(self.status(reading=None)["watcher"]["usage"])


class RuleTests(unittest.TestCase):
    def test_the_popup_asks_the_one_rule(self):
        status = {"watcher": {"usage": WATCHER}, EXTRA: {"meter": METER}}
        self.assertEqual(model.newest_reading(status), usage_rule.newest(WATCHER, {"meter": METER}))
        self.assertIs(usage_rule.newest(WATCHER, None), WATCHER)
        self.assertIs(usage_rule.newest(WATCHER, {"meter": "nonsense"}), WATCHER)


if __name__ == "__main__":
    unittest.main()
