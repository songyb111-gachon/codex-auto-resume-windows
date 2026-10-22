"""v0.6.18 (audit R2): Always or Never for a project reads each record's project in its own Codex home.

A record of a Codex home Settings added (v0.6.15-beta) is labelled on Pending through that home's reader
(control/records.py). Always/Never on its row read the project through the default home's reader instead, which
has no such conversation: the row was refused as `project_unreadable`, and Never chosen on a default-home row of
the same project left that home's waiting records unheld, so they went on to be resumed. Both now read each record
through its own home's reader, made as Pending makes one (LocalSource.elsewhere).
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from codex_auto_resume import homes, projects  # noqa: E402
from codex_auto_resume.domain import ids  # noqa: E402
from codex_auto_resume.store import Store  # noqa: E402
from test_settings_homes import Case  # noqa: E402

DEFAULT_THREAD = "0a1b2c3d-0001-7000-8000-000000000001"
WORK_THREAD = "0a1b2c3d-0001-7000-8000-000000000005"
TURN = "0a1b2c3d-0002-7000-8000-000000000002"


class HomeSource:
    """A reader of one Codex home's projects; `elsewhere` hands the reader of another, as LocalSource does."""

    def __init__(self, by_home, home):
        self.by_home, self.home = by_home, home

    def project_key(self, thread_id):
        return self.by_home.get(self.home, {}).get(thread_id)

    def elsewhere(self, path):
        return HomeSource(self.by_home, str(path))


class ProjectRuleHomesTests(Case):
    def setUp(self):
        super().setUp()
        self.work = self.codex_home("work")
        self.control.update_settings({homes.FIELD: [self.entry(self.work, "Work")]})
        self.project = projects.key_for(None, r"C:\work\alpha")
        self.source = HomeSource({str(self.default): {DEFAULT_THREAD: self.project},
                                  str(self.work): {WORK_THREAD: self.project}}, str(self.default))
        self.default_key = self.record(DEFAULT_THREAD, "")
        self.work_key = self.record(WORK_THREAD, homes.key(self.work))

    def record(self, thread, home_key):
        key = ids.interruption_id(thread, TURN, 110.0, 2, home_key=home_key)
        with Store(self.paths.state_dir) as store:
            store.set_enabled(True, 90.0)
            store.register({"thread_id": thread, "turn_id": TURN, "completed_at": 110.0, "started_at": 105.0,
                            "ordinal": 2, "interruption_id": key, "reset_at": 150.0,
                            "limit_type": "codex.primary", "uncertain": False, "category": "usage_limit"},
                           120.0, home_key=home_key)
        return key

    def holds(self):
        with Store(self.paths.state_dir) as store:
            return store.get(self.default_key)["hold"], store.get(self.work_key)["hold"]

    def test_never_on_a_row_of_an_added_home_reads_its_project_there(self):
        result = self.control.set_project_rule(self.work_key, WORK_THREAD, False, source=self.source)
        self.assertEqual((result["allowed"], result["held"]), (False, 2))
        self.assertEqual(self.control.get_settings()["project_keys_never"], self.project)
        self.assertEqual(self.holds(), ("notify_only", "notify_only"))

    def test_never_on_a_default_row_holds_the_added_homes_rows_of_the_project_too(self):
        result = self.control.set_project_rule(self.default_key, DEFAULT_THREAD, False, source=self.source)
        self.assertEqual(result["held"], 2)
        self.assertEqual(self.holds(), ("notify_only", "notify_only"))

    def test_a_project_no_home_can_read_is_still_refused(self):
        from codex_auto_resume.control import ControlError
        with self.assertRaises(ControlError) as caught:
            self.control.set_project_rule(self.work_key, WORK_THREAD, False,
                                          source=HomeSource({}, str(self.default)))
        self.assertEqual(caught.exception.code, "project_unreadable")


if __name__ == "__main__":
    unittest.main()
