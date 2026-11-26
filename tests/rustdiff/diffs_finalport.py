"""The final-port seat (FINAL-DELTA.md, v0.6.26 final): the rows a diff of their own holds to the tag.

* StatusMeterDiff - `control/watcher.py` `get_status` (FINAL-DELTA #15, with #12/#13's `domain/usage.newest` and
  `meter_windows`): the last usage reading every surface says is the newest of the watcher's and the meter's an
  advanced plug adds to the status. A plug whose STATUS surface adds the world's `status_plug` (test_status_newest_usage's
  `MeterPlug`, on both sides: actworld's HOOK, car-harness `bridge.rs` `StatusPlug`) over the golden installation, the
  watcher's stored reading set to each of several, and meters of every shape: newer, older, the same time, broken,
  windows core cannot keep, a band, three windows of a bucket, a slot the watcher's reading names or does not, read_at
  of the wrong type, `added` that is no dict. Each answer, file, state row and Host call compared, as ControlCallDiff
  does (diffs_bridge_acting).

The fresh-home rows (#1-#5, #11) are held by diffs_codex_homes (`history-absent-*`), diffs_codex_compat_io
(`schema_variants`) and diffs_review6 (`r6_fresh_home_*`).

Run by run.py; never by the lanes' discovery.
"""
from __future__ import annotations

import json
import sqlite3

from rustdiff import diffs_bridge_acting as acting
from rustdiff.diffs import RECORD

DAY = 86400
COUNTS = {"cases": 0}


def windows(now: float, primary=0, secondary=0, *, minutes=(300, 10080), bucket="codex") -> list:
    return [{"bucket": bucket, "window": "primary", "used_percent": primary, "window_minutes": minutes[0],
             "reset_at": now + 3600},
            {"bucket": bucket, "window": "secondary", "used_percent": secondary, "window_minutes": minutes[1],
             "reset_at": now + DAY}]


def stored_reading(at, found):
    """The watcher's heartbeat holding this reading (the store's own columns), or none at all (`found` None)."""
    def tune(workspace):
        connection = sqlite3.connect(workspace / "home" / "config" / "state.sqlite")
        try:
            text = None if found is None else json.dumps(found, separators=(",", ":"), allow_nan=False)
            connection.execute("UPDATE watcher_status SET usage_at=?, usage=? WHERE singleton=1",
                               (None if found is None else at, text))
            connection.commit()
        finally:
            connection.close()
    return tune


class StatusMeterDiff(acting.ActingBase):
    def call(self, world, tune, label):
        COUNTS["cases"] += 1
        return self.run_both("acts", method="get_status", args=(), world=world, tune=tune, label=label)

    def test_the_status_says_the_newest_reading(self):
        now = acting.now()
        own_at = now - 4 * DAY
        readings = {
            "none": stored_reading(None, None),
            "watcher": stored_reading(own_at, windows(now)),
            "watcher, other lengths": stored_reading(own_at, windows(now, minutes=(60, 1440))),
            "watcher, slots swapped": stored_reading(own_at, [dict(windows(now)[0], window="secondary"),
                                                              dict(windows(now)[1], window="primary")]),
            "watcher, another bucket": stored_reading(own_at, windows(now, bucket="codex_other")),
        }

        def meter(read_at=own_at + 600, found=None, **extra):
            made = {"read_at": read_at, "notices": [], "windows": found if found is not None else [
                {"bucket": "codex", "window_minutes": 300, "used_percent": 12, "reset_at": now + 3600, "band": "none"},
                {"bucket": "codex", "window_minutes": 10080, "used_percent": 2, "reset_at": now + DAY,
                 "band": "warn"}]}
            made.update(extra)
            return {"meter": made}

        one = {"bucket": "codex", "window_minutes": 300, "used_percent": 12, "reset_at": now + 3600, "band": "none"}
        plugs = {
            "standard": None,
            "nothing added": {},
            "newer": meter(),
            "newer, int read_at": meter(read_at=int(own_at) + 600),
            "same time": meter(read_at=own_at),
            "older": meter(read_at=own_at - 1),
            "much newer": meter(read_at=1e300),
            "negative read_at": meter(read_at=-5),
            "read_at true": meter(read_at=True),
            "read_at text": meter(read_at=str(own_at + 600)),
            "read_at none": meter(read_at=None),
            "no read_at": {"meter": {"windows": [one]}},
            "windows not a list": meter(found={"0": one}),
            "no windows": {"meter": {"read_at": own_at + 600}},
            "empty windows": meter(found=[]),
            "one window": meter(found=[one]),
            "a window no dict": meter(found=[one, "x"]),
            "used_percent text": meter(found=[dict(one, used_percent="12")]),
            "half a minute": meter(found=[dict(one, window_minutes=300.5)]),
            "three of a bucket": meter(found=[one, dict(one, window_minutes=1440), dict(one, window_minutes=10080)]),
            "two buckets": meter(found=[one, dict(one, bucket="codex_other", window_minutes=60)]),
            "unknown bucket": meter(found=[dict(one, bucket="nope")]),
            "same length twice": meter(found=[one, dict(one, used_percent=50)]),
            "no minutes": meter(found=[dict(one, window_minutes=None), one]),
            "nine windows": meter(found=[dict(one, window_minutes=60 * (n + 1)) for n in range(9)]),
            "unicode bucket": meter(found=[dict(one, bucket="cödex")]),
            "meter not a dict": {"meter": [1, 2]},
            "meter null": {"meter": None},
            "added a list": [meter()],
            "added text": "meter",
            "added a number": 5,
            "other keys": dict(meter(), other={"x": 1}),
        }
        for reading, tune in readings.items():
            for name, plug in plugs.items():
                with self.subTest(reading=reading, plug=name):
                    self.call({"status_plug": plug}, tune, "get_status, %s, %s" % (reading, name))
        RECORD.append("finalport status meter: %d get_status cases equal" % COUNTS["cases"])


if __name__ == "__main__":
    import unittest

    unittest.main()
