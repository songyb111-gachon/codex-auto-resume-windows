"""The product's local clock (car-platform `localclock::Crt`) in zones with summer time, against the interpreter's own.

Quiet hours, a postponement and a reset time read `time.localtime` and `time.mktime`, which on Windows are the C
runtime's `_localtime64_s` and `_mktime64`; `Crt` calls the same two (REVIEW-int5 note 3). diffs_classify_policy.py
holds it to the reference in this PC's own zone (the zone `"local"`). Here both processes run under a `TZ` the C
runtime reads instead of Windows' setting - zones with summer time (the C runtime puts its changes on the US dates),
one west of UTC, one with half hours, UTC - so every hour around both changes of the clock, the hour that is skipped and
the hour that comes twice, and quiet windows that span them are asked of both. Nothing of the PC's own zone changes:
`TZ` is set only in the two child processes' environments.
"""
from __future__ import annotations

import os
import time

from rustdiff.diffs_classify_policy import ZONE
from rustdiff.leaves import Leaves

RECORD: list[str] = []

ZONES_TZ = ["PST8PDT", "EST5EDT", "CET-1CEST", "UTC0", "IST-5:30", "NZST-12NZDT"]

SCRIPT = ZONE + r'''
from codex_auto_resume import quiet
rng = random.Random(1125)
def zone_case(value, spec):
    zone = Zone(spec)
    if isinstance(value, list):
        return zone.mktime(tuple(value))
    t = zone.localtime(value)
    return [t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec, t.tm_wday]
def quiet_until(now, values, spec):
    return quiet.quiet_until(now, values)          # the product's own clock: time.localtime, time.mktime
def postpone_time(now, preset, spec):
    return quiet.postpone_time(now, preset)
ops = {"quiet.zone": zone_case, "quiet.quiet_until": quiet_until, "quiet.postpone_time": postpone_time}
base = 1_767_225_600  # 2026-01-01 00:00 UTC
cases = []
# Every half hour of 2026, then each hour of the two changes of the clock's weeks at 15-minute steps.
for step in range(0, 366 * 48):
    cases.append(["quiet.zone", base + step * 1800 + rng.choice([0, 1, 899, 1799]), "local"])
for year in (2026, 2027, 1970, 2999):
    for month, day in ((3, 1), (3, 8), (3, 29), (4, 5), (10, 25), (11, 1), (9, 27)):
        for hour in range(-6, 30):
            for minute in (0, 15, 30, 59):
                cases.append(["quiet.zone", [year, month, day, hour, minute, 0], "local"])
for _ in range(3000):
    cases.append(["quiet.zone", [rng.randrange(1969, 3002), rng.randrange(1, 13), rng.randrange(-3, 35),
                                 rng.randrange(-3, 27), rng.randrange(0, 60), rng.randrange(-90, 90)], "local"])
windows = [{"quiet_hours_start": "22:00", "quiet_hours_end": "07:00"},
           {"quiet_hours_start": "01:30", "quiet_hours_end": "03:30", "quiet_hours_days": "weekends"},
           {"quiet_hours_start": "02:00", "quiet_hours_end": "02:30"}]
for day in range(0, 366):
    for hour in (0, 1, 2, 3, 6, 23):
        now = base + day * 86400 + hour * 3600 + rng.choice([0, 1799, 3599.5])
        cases.append(["quiet.quiet_until", now, rng.choice(windows), "local"])
for day in range(0, 366, 2):
    cases.append(["quiet.postpone_time", base + day * 86400 + rng.randrange(86400), "tomorrow_morning", "local"])
finish(cases, ops)
'''


class LocalClockDiff(Leaves):
    def test_the_product_clock_in_zones_with_summer_time(self):
        # This process's C runtime reads TZ once, at its first local time: read it now, so setting TZ below reaches
        # only the two child processes each family starts (both read the environment they are given).
        time.localtime(0)
        before = os.environ.get("TZ")
        counted = 0
        try:
            for zone in ZONES_TZ:
                with self.subTest(tz=zone):
                    os.environ["TZ"] = zone
                    done = self.family(SCRIPT, label="clock-" + zone.replace(":", "-"), chunk=20000)
                    counted += len(done["cases"])
        finally:
            if before is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = before
        RECORD.append("local clock: %d cases of localtime, mktime, quiet_until and postpone_time in %d TZ zones (%s) "
                      "equal the interpreter's own time module" % (counted, len(ZONES_TZ), ", ".join(ZONES_TZ)))
