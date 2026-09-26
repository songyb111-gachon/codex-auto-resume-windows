"""The defaults v0.6.10 shipped, pinned; and every setting added since, as v0.6.10 behaved.

The standard edition's rule from v0.6.11: at its defaults it makes exactly v0.6.10's calls to
Codex and behaves as v0.6.10 did, and a setting added later changes nothing until a person turns
it on. `tests/golden/defaults-v0.6.10.json` is `settings.defaults()` exactly as the tagged v0.6.10
returned it - every name, and every value with its JSON type, so a 6 that became 6.0 or a false
that became 0 fails as surely as a changed number.

A setting added since is named in ADDED with its default and why that default is v0.6.10's
behaviour: off, none, every conversation, automatic, and the like. One that is not named there
fails here, so nobody adds a setting without saying so.

The golden is written from the tag, never by hand:

    py -c "import sys; sys.path[:0] = ['src', 'tests']; import test_defaults_golden as t; t.write()"
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import released  # noqa: E402
from codex_auto_resume import settings  # noqa: E402

GOLDEN = _HERE / "golden" / "defaults-v0.6.10.json"
TAG = "v0.6.10"
_READ = "import json\nfrom codex_auto_resume import settings\nprint(json.dumps(settings.defaults()))"

# name -> (its default, why that default is what v0.6.10 did). Empty until a setting is added.
ADDED: dict = {
    "quiet_hours_start": ("off", "no quiet hours: nothing that falls due waits for a time of day"),
    "quiet_hours_end": ("07:00", "inert while quiet_hours_start is off, which is the default"),
    "quiet_hours_days": ("every_day", "inert while quiet_hours_start is off, which is the default"),
    "default_tier": ("automatic", "every conversation is resumed automatically, as v0.6.10 resumed it"),
    "objection_minutes": (5, "read only by the objection-window tier, which nothing has at the defaults"),
    "observe_only": (False, "off: recovery sends as v0.6.10 sent"),
    "new_conversation_policy": ("resume", "a conversation first seen is resumed like every other, as in v0.6.10"),
    "project_policy": ("every", "every project resumes, and no project of Codex's is read for it"),
    "project_keys_always": ("", "empty, and read only by the only-listed project policy"),
    "project_keys_never": ("", "empty, and read only by the except-listed project policy"),
    "retry_wait_1": ("s5", "read only while retry_timing is custom, which it is not by default"),
    "retry_wait_2": ("m15", "read only while retry_timing is custom, which it is not by default"),
    "retry_wait_3": ("m15", "read only while retry_timing is custom, which it is not by default"),
    "retry_wait_4": ("m15", "read only while retry_timing is custom, which it is not by default"),
    "retry_wait_5": ("m15", "read only while retry_timing is custom, which it is not by default"),
    "retry_jitter": (False, "off: every wait is exactly the ladder's, as in v0.6.10"),
    "chain_time_ceiling": ("off", "no time ceiling: a task stops on its budgets alone, as in v0.6.10"),
    "task_changed_guard": ("off", "off: nothing of a task's workspace is read, and nothing is held for it"),
    "context_guard": ("off", "off: no token count is read, shown or held for"),
}


def text(values: dict) -> str:
    return json.dumps(values, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"


def write() -> None:
    """Write the golden from the tagged v0.6.10 itself."""
    GOLDEN.write_text(text(released.run(TAG, _READ)), encoding="utf-8", newline="\n")


class DefaultsGoldenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.golden = json.loads(GOLDEN.read_text(encoding="utf-8"))

    def test_every_default_v0_6_10_shipped_is_still_the_default(self):
        now = settings.defaults()
        for name, value in sorted(self.golden.items()):
            with self.subTest(name):
                self.assertIn(name, now, "a v0.6.10 setting is gone")
                self.assertEqual(json.dumps(now[name]), json.dumps(value))

    def test_every_setting_added_since_is_named_with_a_default_that_keeps_v0_6_10(self):
        now = settings.defaults()
        added = set(now) - set(self.golden)
        self.assertEqual(sorted(added), sorted(ADDED), "name each new setting in ADDED, with why")
        for name, (default, why) in sorted(ADDED.items()):
            with self.subTest(name):
                self.assertEqual(json.dumps(now[name]), json.dumps(default))
                self.assertTrue(why.strip(), "say why this default is v0.6.10's behaviour")

    def test_the_golden_is_what_the_tagged_v0_6_10_returns(self):
        self.assertEqual(released.run(TAG, _READ), self.golden)

    def test_the_golden_is_written_one_way(self):
        self.assertEqual(GOLDEN.read_text(encoding="utf-8"), text(self.golden))
        self.assertEqual(len(self.golden), 35)


if __name__ == "__main__":
    unittest.main()
