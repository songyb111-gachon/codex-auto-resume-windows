"""S2.2, `homefind.coerce_dismissed` held to the tag on its own.

The function is the one thing of `homefind.py` the settings read (the coercer of `home_suggestions_dismissed`). It sat in
a seam of car-policy's settings because neither seat's list named it; it is ported as the reference has it
(`settings/homefind.rs`). `diffs_settings_values.py` already sends `DISMISSED` through every field as the settings' coercer;
this sends it, and more, straight to the function: lists of 0 to 18 folders, a relative path, a share, a drive-relative one,
a non-text entry, half of a surrogate pair, two spellings of one folder (case, a slash, a trailing dot, `..`), a dict, and
the default given by the caller.
"""
from __future__ import annotations

from rustdiff import diffs_settings_values as values
from rustdiff.settingsdiff import Family

RECORD: list[str] = []


class HomefindDiff(Family):
    def test_coerce_dismissed(self):
        script = values.VALUES + r'''
from codex_auto_resume import homefind
cases = []
folders = ["C:\\a", "c:/A", "C:\\a.", "C:\\a ", "C:\\a\\..\\b", "C:\\b", "D:\\x\\y", "D:\\x\\y\\", "relative",
           "\\\\server\\share", "C:", "C:x", "C:\\" + "a" * 257, "C:\\" + "a" * 258, "C:\\a\x01", "C:\\a" + SUR,
           "C:\\\u0130", "C:\\i\u0307", "", 5, None, True]
for count in range(0, 19):
    cases.append(["homefind.coerce_dismissed", ["C:\\x%d" % n for n in range(count)]])
for each in folders:
    cases.append(["homefind.coerce_dismissed", [each]])
    cases.append(["homefind.coerce_dismissed", ["C:\\keep", each]])
for _ in range(1500):
    cases.append(["homefind.coerce_dismissed", [rng.choice(folders) for _ in range(rng.randrange(0, 6))]])
for value in WRONG + [{"a": 1}, "C:\\a", [[]], [["C:\\a"]]]:
    cases.append(["homefind.coerce_dismissed", value])
ops = {"homefind.coerce_dismissed": lambda value: homefind.coerce_dismissed(value, [])}
finish(cases, ops)
'''
        done = self.family(script, label="homefind", expect=1500)
        RECORD.append("homefind.coerce_dismissed: %d cases equal" % len(done["cases"]))
