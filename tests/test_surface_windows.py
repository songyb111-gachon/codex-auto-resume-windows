"""Comparison A for what the host's surface windows decide (P6-DESIGN 3.3; seat S6.3c).

tests/test_surface_parity.py holds the plans and the pixels; this module holds the windows' own halves against the
reference over a fixed matrix, exactly: the icon's words (ui/tray/words.py -> gui/TrayWords.cs), where Windows keeps the
icon (tray_place.py -> gui/TrayPlace.cs), and the windows' message handling as the probe mode drives it. The C# is
compiled with the in-box csc and run once as a console program with CREATE_NO_WINDOW; it makes no window anybody sees.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "build"))

import guiscan  # noqa: E402
from test_surface_parity import CREATE_NO_WINDOW, CSC, DRIVER, JOB_FORMAT, first_difference, plain  # noqa: E402

NOW = 1_800_000_000.0


class WindowJob:
    def __init__(self):
        self.cases, self.expected = [], {}

    def add(self, case_id, case, plan):
        self.cases.append(dict(case, id=case_id))
        self.expected[case_id] = plain(plan)

    def tray_words(self):
        from codex_auto_resume import interface
        from codex_auto_resume.ui.tray import words
        import test_tray_tipcard as fixtures
        long_meter = {"windows": [{"window_minutes": minutes, "used_percent": used} for minutes, used in
                                  ((300, 12.5), (10080, 99.6), (1440, 100), (2880, -4), (90, 0.4), (60, 55),
                                   (45, 101), (60, 90), (120, 89.5), (0, 7), (None, 8), (-60, 1), (7 * 1440, 50))]}
        odd_meter = {"windows": [{"window_minutes": 300, "used_percent": True}, {"window_minutes": 300, "used_percent": "9"},
                                 "row", None, {"used_percent": 33.3}, {"window_minutes": 120, "used_percent": 0}]}
        snapshots = dict(fixtures.FIXTURES)
        snapshots.update({
            "none": None, "all": {"enabled": True, "waiting": 12, "running": 3, "held": 2, "next_at": NOW + 3 * 3600 + 5},
            "past": {"enabled": True, "waiting": 2, "next_at": NOW - 4000}, "zero_due": {"waiting": 1, "next_at": 0},
            "long": {"enabled": True, "waiting": 4, "running": 2, "held": 1, "next_at": NOW + 59.9,
                     "advanced": {"meter": long_meter}},
            "odd": {"enabled": True, "waiting": 1, "advanced": {"meter": odd_meter}},
            "bad_extra": {"enabled": True, "advanced": {"meter": {"windows": "x"}}},
            "falsy_enabled": {"enabled": 0, "waiting": 1}, "string_counts": {"waiting": "2", "running": ""},
            "fraction": {"waiting": 1.5, "running": 2, "next_at": NOW + 0.5},
            "huge": {"waiting": 10 ** 6, "next_at": NOW + 10 ** 7},
        })
        catalogs = [(str(locale.value if hasattr(locale, "value") else locale), strings)
                    for locale, strings in interface.STRINGS.items()]
        catalogs += [("blank", {}), ("empty_words", {"usage.window": "", "tray.title": "T", "usage.hours": "{n}h"}),
                     ("colon", {"usage.window": "{window}: {percent} %", "usage.weekly": "W"}),
                     ("narrow", {"usage.window": "{window} : {percent} %", "usage.days": "{n} j"})]
        for locale, strings in catalogs:
            for name, snapshot in snapshots.items():
                for edition in (None, "standard", "advanced", "beta"):
                    try:
                        parts = words.tooltip_parts(snapshot, strings, NOW, edition)
                        plan = {"parts": parts, "tooltip": words.tooltip(snapshot, strings, NOW, edition),
                                "joined": words.tooltip_joined(parts), "meter_line": words.meter_line(snapshot, strings)}
                    except Exception as exc:                # noqa: BLE001 - the error class is what is compared
                        plan = {"raised": type(exc).__name__}
                    self.add("traywords/%s/%s/%s" % (locale, name, edition),
                             {"surface": "tray_words", "snapshot": snapshot, "strings": strings, "now": NOW,
                              "edition": edition}, plan)
        from codex_auto_resume.ui import words as shared
        seconds = [-5, 0, 0.9, 1, 59, 59.99, 60, 61, 3599, 3600, 3661, 86399, 86400 * 3 + 7, 10 ** 9]
        for value in seconds:
            self.add("traywords/countdown/%r" % value,
                     {"surface": "tray_words", "snapshot": {"waiting": 1, "next_at": NOW + value}, "strings": {}, "now": NOW,
                      "edition": None},
                     {"parts": words.tooltip_parts({"waiting": 1, "next_at": NOW + value}, {}, NOW, None),
                      "tooltip": words.tooltip({"waiting": 1, "next_at": NOW + value}, {}, NOW, None),
                      "joined": words.tooltip_joined(words.tooltip_parts({"waiting": 1, "next_at": NOW + value}, {}, NOW,
                                                                         None)),
                      "meter_line": None})
            assert shared.countdown(value) in self.expected["traywords/countdown/%r" % value]["tooltip"]

    def tray_place(self):
        """IconPlacement over runs of registry states and clock readings, _same_path, and overflow_open over windows."""
        from codex_auto_resume import tray_place
        settings, notify = tray_place.NOTIFY_ICON_SETTINGS, tray_place.TRAY_NOTIFY
        exe = r"C:\Program Files\Codex Auto Resume\CodexAutoResume.exe"
        folders = {"{6D809377-6AF0-444B-8957-A3773F02200E}": r"C:\Program Files",
                   "{F1B32785-6FBA-4FCF-9D55-7B8E7F157091}": r"C:\Users\ExampleUser\AppData\Local", "{BAD}": None}

        def entry(path, uid=1, promoted=1, guid=None):
            values = {"ExecutablePath": path, "UID": uid, "IsPromoted": promoted}
            if guid is not None:
                values["IconGuid"] = guid
            return {"values": values}

        def state(*entries, chevron=None, extra=None, subkeys=True):
            keys = {notify: {"values": {} if chevron is None else {"SystemTrayChevronVisibility": chevron}}}
            names = []
            for index, one in enumerate(entries):
                name = "%d" % (1000 + index)
                names.append(name)
                keys[settings + "\\" + name] = one
            if subkeys:
                keys[settings] = {"subkeys": names + ["9999"], "values": {}}
            keys.update(extra or {})
            return keys

        ours, theirs = entry(exe), entry(r"C:\Other\app.exe")
        known = entry("{6D809377-6AF0-444B-8957-A3773F02200E}\\Codex Auto Resume\\CodexAutoResume.exe", promoted=0)
        runs = {
            "promoted": [(0, state(theirs, ours)), (1, state(theirs, ours)), (2, state(theirs, entry(exe, promoted=0)))],
            "overflow": [(0, state(known)), (5, state(known))],
            "chevron": [(0, state(ours, chevron=0)), (1, state(ours, chevron=1)), (2, state(ours, chevron=False)),
                        (3, state(ours, chevron="0"))],
            "missing": [(0, state(theirs)), (10, state(theirs, ours)), (29.9, state(ours)), (30, state(ours)),
                        (31, state(ours))],
            "gone": [(0, state(ours)), (1, state(theirs)), (2, state(theirs)), (40, state(theirs, entry(exe, promoted=0)))],
            "no_keys": [(0, state(ours, subkeys=False)), (40, state(ours))],
            "broken": [(0, state(ours, extra={notify: {"broken": True}})), (1, state(ours))],
            "uid": [(0, state(entry(exe, uid=2), entry(exe, uid="1"), entry(exe, uid=True)))],
            "guid": [(0, state(entry(exe, guid="{X}"), entry(exe, promoted=0)))],
            "case": [(0, state(entry(exe.upper().replace("\\", "/"), promoted=0)))],
            "dots": [(0, state(entry(r"C:\Program Files\.\x\..\Codex Auto Resume\\CodexAutoResume.exe")))],
            "bad_folder": [(0, state(entry("{BAD}\\CodexAutoResume.exe"), entry("{NONE}\\x.exe"), entry("{only")))],
            "two": [(0, state(entry(exe, promoted=0), entry(exe, promoted=1)))],
            "two_back": [(0, state(entry(exe, promoted=1), entry(exe, promoted=0)))],
            "promoted_odd": [(0, state(entry(exe, promoted="")))],
        }

        class Keys:
            current = {}

            def subkeys(self, path):
                key = self.current.get(path)
                if not isinstance(key, dict) or "subkeys" not in key:
                    raise FileNotFoundError(path)
                return list(key["subkeys"])

            def value(self, path, name):
                key = self.current.get(path)
                if key is None:
                    return None
                if key.get("broken"):
                    raise PermissionError(path)
                return key.get("values", {}).get(name)

        paths = [exe, "c:/program files/x/../y/./z.exe", r"\\server\share\a\..\..\b", "\\\\?\\UNC\\s\\h\\x",
                 "\\\\?\\C:\\a\\..\\b", r"\\.\pipe\x", "C:relative\\..\\..\\x", r"\rooted\..\..\x", "a/b/../../..",
                 "", ".", "..", "C:", "C:\\", "//", r"\\server", r"\\server\share", "ÄÖÜ\\İı\\ΣΑΣ\\Straße",
                 "C:\\x\\...\\y", "x\\..\\..\\..\\y", "\\\\?\\unc\\a", "C:/a//b///c/"]
        for name, steps in runs.items():
            keys = Keys()
            clock = [0.0]
            placement = tray_place.IconPlacement(exe, 1, reader=keys, folders=folders.get, clock=lambda: clock[0])
            answers = []
            for moment, current in steps:
                clock[0], keys.current = float(moment), current
                answers.append(placement.overflowed())
            self.add("trayplace/%s" % name,
                     {"surface": "tray_place", "executable": exe, "uid": 1, "folders": folders,
                      "steps": [{"clock": float(moment), "keys": current} for moment, current in steps],
                      "paths": paths if name == "promoted" else [], "overflow": []},
                     {"answers": answers, "executable": placement.executable,
                      "paths": [tray_place._same_path(path) for path in paths] if name == "promoted" else [],
                      "open": []})

        class Function:
            """A stand-in for a ctypes function: callable, and argtypes/restype can be set on it."""

            def __init__(self, body):
                self.body = body

            def __call__(self, *arguments):
                return self.body(*arguments)

        def overflow(windows):
            def find(parent, after, name, title):
                for index in range(after or 0, len(windows)):
                    if windows[index][0] == name:
                        return index + 1
                return None

            def attribute(hwnd, what, pointer, size):
                cloaked = windows[hwnd - 1][2]
                if cloaked is None:
                    return -2147467259
                pointer._obj.value = cloaked
                return 0

            class Library:
                FindWindowExW = Function(find)
                IsWindowVisible = Function(lambda hwnd: windows[hwnd - 1][1])
                DwmGetWindowAttribute = Function(attribute)
            return tray_place.overflow_open(lambda name: Library)

        win11, win10 = tray_place.OVERFLOW_WINDOWS
        sets = [[], [[win11, False, 0]], [[win11, True, 0]], [[win11, True, 1]], [[win11, True, None]],
                [[win11, True, 1], [win10, True, 0]], [["Other", True, 0], [win10, False, 0], [win10, True, 2]],
                [[win10, True, 0]] * 3, [[win11, True, 1]] * 20 + [[win10, True, 0]], [[win11, True, 1]] * 17,
                [[win11, True, 1]] * 15 + [[win11, True, 0]], [[win11, True, 1]] * 16 + [[win11, True, 0]]]
        self.add("trayplace/overflow",
                 {"surface": "tray_place", "executable": exe, "uid": 1, "folders": {}, "steps": [], "paths": [],
                  "overflow": sets},
                 {"answers": [], "executable": tray_place._same_path(exe), "paths": [],
                  "open": [overflow(windows) for windows in sets]})

    def job(self):
        return {"format": JOB_FORMAT, "tables": {}, "cases": self.cases}


@unittest.skipUnless(CSC.is_file(), "needs the in-box C# compiler")
class SurfaceWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory(prefix="car-surface-windows-")
        folder = Path(cls.folder.name)
        driver = folder / "SurfaceParityDriver.cs"
        driver.write_text(DRIVER, encoding="utf-8")
        sources = [ROOT / name for name in guiscan.host_group("surface") + guiscan.host_group("generated")]
        exe = folder / "surface-windows.exe"
        built = subprocess.run([str(CSC), "-nologo", "-target:exe", "-platform:x64", "-warnaserror", "-optimize+",
                                "-out:%s" % exe, "-r:System.dll", "-r:System.Drawing.dll"]
                               + [str(path) for path in sources] + [str(driver)],
                               capture_output=True, timeout=600, creationflags=CREATE_NO_WINDOW)
        if built.returncode != 0:
            raise AssertionError("the surfaces do not compile:\n%s" % built.stdout.decode("utf-8", "replace"))
        job = WindowJob()
        job.tray_words()
        job.tray_place()
        cls.expected = job.expected
        job_path, out_path = folder / "job.json", folder / "job.out.json"
        job_path.write_text(json.dumps(job.job(), ensure_ascii=False), encoding="utf-8")
        ran = subprocess.run([str(exe), str(job_path), str(out_path)], capture_output=True, timeout=600,
                             creationflags=CREATE_NO_WINDOW)
        if not out_path.is_file():
            raise AssertionError("the render mode wrote nothing (exit %d):\n%s"
                                 % (ran.returncode, ran.stdout.decode("utf-8", "replace")))
        cls.found = {case["id"]: case for case in json.loads(out_path.read_text(encoding="utf-8"))["cases"]}

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def compare(self, prefix):
        ids = [case_id for case_id in self.expected if case_id.startswith(prefix)]
        self.assertTrue(ids, "no case for %s" % prefix)
        wrong = []
        for case_id in ids:
            found = self.found.get(case_id, {})
            if "error" in found:
                wrong.append("%s: %s" % (case_id, found["error"]))
                continue
            difference = first_difference(self.expected[case_id], found.get("plan"))
            if difference:
                wrong.append("%s: %s" % (case_id, difference))
        self.assertEqual(wrong[:10], [], "%d of %d cases differ" % (len(wrong), len(ids)))

    def test_the_icons_words_are_the_references_in_every_language(self):
        self.compare("traywords/")


    def test_where_windows_keeps_the_icon_is_read_as_the_reference_reads_it(self):
        self.compare("trayplace/")


if __name__ == "__main__":
    unittest.main()
