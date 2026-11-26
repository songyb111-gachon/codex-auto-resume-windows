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
        self.add("trayplace/flyout",
                 {"surface": "tray_place", "executable": exe, "uid": 1, "folders": {}, "steps": [], "paths": [],
                  "overflow": sets},
                 {"answers": [], "executable": tray_place._same_path(exe), "paths": [],
                  "open": [overflow(windows) for windows in sets]})

    # The look of Windows' system colours in High Contrast, fixed (as test_surface_parity's pixel cases fix them).
    SYSTEM = {"Window": [0, 0, 0], "WindowFrame": [255, 255, 255], "WindowText": [255, 255, 255],
              "Highlight": [26, 235, 255], "HighlightText": [0, 0, 0], "Control": [0, 0, 0], "GrayText": [63, 242, 63]}

    def tip_window(self):
        """The icon's card as a window: the reference's TipCard driven through a script - the icon's calls, its own
        messages, the clocks, the pointer - with every call that would put a window on the screen answered by a stand-in,
        and the C#'s TipCard over a window made and never shown, through the same script. After each step: shown, alpha,
        fade, frame timer, place, size, text and the picture by digest; and the window's own picture against the render
        mode's (the live-path proof)."""
        import hashlib
        import make_screenshots
        from codex_auto_resume import brand, interface
        from codex_auto_resume.ui import popup
        from codex_auto_resume.ui.popup import fonts, gdiplus, light as light_module, renderer as renderer_module
        from codex_auto_resume.ui.tray import tipcard, words
        import test_tray_tipcard as fixtures
        WM_TIMER, WM_SETTINGCHANGE = 0x0113, 0x001A
        tick, frame, fade, watch = tipcard.TIP_TICK, tipcard.TIP_FRAME, tipcard.TIP_FADE, tipcard.TIP_WATCH
        timer = lambda which: ["message", WM_TIMER, which, True]  # noqa: E731
        script = ([["show"]] + [["clock", 0.05], timer(fade)] * 6 + [["proof"], timer(frame), ["clock", 0.5], timer(frame),
                  ["proof"], ["clock", 1.0], timer(tick), ["pointer", [5, 5]], timer(watch), ["clock", 0.6], timer(watch),
                  ["clock", 0.35], timer(watch), ["clock", 0.05], timer(watch)] + [["clock", 0.03], timer(fade)] * 5
                  + [["show"], ["message", 0x0021, 0, True], ["message", 0x0084, 0, True], ["pointer", [110, 1050]],
                     timer(watch), ["message", WM_SETTINGCHANGE, 0], ["held", True], timer(tick), timer(frame),
                     ["held", False], timer(tick), ["message", 0x007E, 0], ["show"], ["clock", 0.05], timer(fade), ["clock", 0.05],
                     timer(fade), ["leave"], ["clock", 0.05], timer(fade), ["clock", 0.05], timer(fade), ["show"], ["leave"], ["clock", 0.02], timer(fade),
                     ["hide"], ["show"], ["message", 0x0218, 4], ["show"], ["message", 0x0218, 9], ["hide"], ["hide"],
                     ["leave"]])
        screen = {"box": [1800, 1045, 1824, 1069], "dpi": 144, "work": [0, 0, 1920, 1040], "monitor": [0, 0, 1920, 1080]}
        runs = []
        for locale in ("en", "ko", "ar"):
            for name, edition in (("waiting", None), ("metered", "advanced")):
                for theme, design, contrast in (["light", "soft", False], ["dark", "plain", False]):
                    runs.append((locale, name, edition, [theme, design, contrast], False, False, 1.0))
        runs += [("en", "held", None, ["light", "soft", True], False, False, 1.0),
                 ("ko", "failed", "advanced", ["dark", "classic", False], True, False, 1.0),
                 ("en", "waiting", None, ["light", "soft", False], False, True, 1.0),
                 ("ar", "due", None, ["light", "plain", False], False, False, 1.75),
                 ("de" if "de" in interface.STRINGS else "en", "paused", None, ["dark", "soft", False], False, False, 1.25)]
        saved = (renderer_module.system_rgb, light_module.system_rgb, popup._dll, tipcard.time, tipcard.tip_screen,
                 tipcard.tip_pointer, tipcard.access.tell, popup.high_contrast, popup.reduced_motion,
                 popup.apps_use_light_theme, popup.text_scale, popup.theme_setting, popup.design_setting)
        real = popup._dll

        class User32:
            """The real user32 for everything but what makes, shows, places or times a window."""
            def __init__(self, inner):
                self._inner = inner

            def __getattr__(self, name):
                stand = {"RegisterClassW": lambda *a: 1, "CreateWindowExW": lambda *a: 0x1234, "DestroyWindow": lambda *a: 1,
                         "UnregisterClassW": lambda *a: 1, "ShowWindow": lambda *a: 1, "SetWindowPos": lambda *a: 1,
                         "SetTimer": lambda *a: 1, "KillTimer": lambda *a: 1, "UpdateLayeredWindow": lambda *a: 1,
                         "DefWindowProcW": lambda *a: 0}
                return stand[name] if name in stand else getattr(self._inner, name)

        renderer_module.system_rgb = light_module.system_rgb = lambda name: tuple(self.SYSTEM[name])
        popup._dll = lambda name: User32(real(name)) if name == "user32" else real(name)
        tipcard.access.tell = lambda *unused: None
        try:
            with make_screenshots.pinned_face():
                pinned = fonts._ui_face()
                for locale, name, edition, look, reduced, days, text in runs:
                    strings = interface.STRINGS[locale]
                    snapshot = fixtures.FIXTURES[name]
                    state = {"clock": 1000.0, "pointer": None, "held": False}

                    class Clock:
                        @staticmethod
                        def monotonic():
                            return state["clock"]

                        @staticmethod
                        def time():
                            return fixtures.NOW
                    tipcard.time = Clock
                    tipcard.tip_screen = lambda icon=None, point=None: {key: tuple(value) if isinstance(value, list) else value
                                                                        for key, value in screen.items()}
                    tipcard.tip_pointer = lambda: None if state["pointer"] is None else tuple(state["pointer"])
                    popup.high_contrast = lambda: look[2]
                    popup.reduced_motion = lambda: reduced
                    popup.apps_use_light_theme = lambda: look[0] == "light"
                    popup.text_scale = lambda: text
                    popup.theme_setting = lambda: look[0]
                    popup.design_setting = lambda: look[1]
                    shown_locale = popup.locale_of(strings)
                    before = gdiplus.gdiplus_objects()
                    logged = []
                    card = tipcard.TipCard(content=lambda: (words.tooltip_parts(snapshot, strings, fixtures.NOW, edition),
                                                            snapshot, strings),
                                           held=lambda: state["held"], log=logged.append, days=days)
                    steps, proofs = [], []
                    try:
                        for step in script:
                            op, returned = step[0], None
                            if op == "show":
                                card.show()
                            elif op == "hide":
                                card.hide()
                            elif op == "leave":
                                card.hide(at_once=False)
                            elif op == "clock":
                                state["clock"] += step[1]
                            elif op == "pointer":
                                state["pointer"] = step[1]
                            elif op == "held":
                                state["held"] = step[1]
                            elif op == "message":
                                answer = card._wndproc(card.hwnd, step[1], step[2], 0)
                                returned = float(answer) if len(step) > 3 and step[3] else None
                            elif op == "proof":
                                digest = hashlib.sha256(card.render().pixels()).hexdigest()
                                proofs.append([digest, digest, True])
                                continue
                            canvas = card._renderer.canvas if card._renderer is not None and card._plan is not None else None
                            steps.append({"op": op, "visible": card.visible, "alpha": card._alpha,
                                          "fade": card._fade[0] if card._fade else None, "frames": card._frame_running,
                                          "origin": list(card._origin) if card._plan is not None else None,
                                          "size": card._plan["size"] if card._plan is not None else None, "text": card.text,
                                          "pixels": hashlib.sha256(canvas.pixels()).hexdigest() if canvas else None,
                                          "returned": returned})
                    finally:
                        card.destroy()
                    parts = words.tooltip_parts(snapshot, strings, fixtures.NOW, edition)
                    self.add("tipwindow/%s/%s/%s-%s-%s/%s-%s-%r" % (locale, name, look[0], look[1], look[2], reduced, days, text),
                             {"surface": "tip_window", "snapshot": snapshot, "strings": strings, "edition": edition,
                              "locale": shown_locale, "letters": fonts._letters(shown_locale), "look": look,
                              "reduced": reduced, "days": days, "text_scale": text, "now": fixtures.NOW, "screen": screen,
                              "script": script, "pinned": pinned, "system": self.SYSTEM, "parts": parts,
                              "light": tipcard.tip_light(snapshot, fixtures.NOW),
                              "day": tipcard.tip_day(brand.day_look_at(fixtures.NOW) if days else None, look[2], look[1])},
                             {"steps": steps, "proofs": proofs, "log": logged, "left": gdiplus.gdiplus_objects() - before})
        finally:
            (renderer_module.system_rgb, light_module.system_rgb, popup._dll, tipcard.time, tipcard.tip_screen,
             tipcard.tip_pointer, tipcard.access.tell, popup.high_contrast, popup.reduced_motion,
             popup.apps_use_light_theme, popup.text_scale, popup.theme_setting, popup.design_setting) = saved

    def popup_window(self):
        """The popup as a window: the reference's Popup driven through a script - the icon's calls, Windows' messages, the
        clocks, the calls it posts and their answers - with every call that would put a window on the screen recorded by a
        stand-in and not made, and the C#'s PopupWindow over windows made and never shown (SurfaceScreen.Probe), through
        the same script. The core's half (the model) is the reference's PopupModel: what it would hand the host in each
        snapshot is given to the C# wherever the reference's model took an answer. After each step: shown, opening, frame
        timer, place, size, hover/press/focus, the picture by digest and the calls made and logged; and the window's own
        picture against the render mode's (the live-path proof)."""
        import hashlib
        import make_screenshots
        from codex_auto_resume import brand, interface
        from codex_auto_resume.ui.popup import (access, fonts, gdiplus, layers, light as light_module, messages,
                                                renderer as renderer_module, theme, window, words as popup_words)
        from codex_auto_resume.ui.popup import hidden as hidden_module, motion as motion_module
        WM_TIMER, WM_KEYDOWN, WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0113, 0x0100, 0x0200, 0x0201, 0x0202
        WM_CONTEXTMENU, WM_ACTIVATE, WM_SETTINGCHANGE, WM_DPICHANGED, WM_MOUSELEAVE = 0x007B, 0x0006, 0x001A, 0x02E0, 0x02A3
        RESULT, TRANSPARENT = 0x8002, 0x20
        tick, frame = window.TIMER_TICK, window.TIMER_FRAME
        saved = (renderer_module.system_rgb, light_module.system_rgb, window._dll, messages._dll, layers._dll, layers.update,
                 window.time, messages.time, hidden_module.time, messages.threading, access.announce, access.answer,
                 access.disconnect, theme.high_contrast, theme.reduced_motion, theme.apps_use_light_theme, theme.text_scale,
                 motion_module.time)
        real = window._dll
        state = {}

        def fmt(value):
            return "%d" % value if float(value) == int(value) else repr(float(value))

        def role(hwnd):
            return state["roles"].get(hwnd, "0x%x" % (hwnd or 0))

        def log(*parts):
            state["calls"].append(" ".join(str(part) for part in parts))

        def made(style, klass, title, *rest):
            hwnd = 0x5000 + len(state["roles"])
            state["roles"][hwnd] = "shadow" if style & TRANSPARENT else "card"
            return hwnd

        def posted(hwnd, message, wparam, lparam):
            log("PostMessageW", role(hwnd), int(message), int(wparam or 0), int(lparam or 0))
            state["queue"].append((hwnd, int(message), int(wparam or 0), int(lparam or 0)))
            return 1

        class User32:
            """The real user32 for everything but what makes, shows, places, fades or times a window."""
            def __init__(self, inner):
                self._inner = inner

            def __getattr__(self, name):
                stand = {
                    "RegisterClassW": lambda *a: 1, "CreateWindowExW": made, "DestroyWindow": lambda *a: 1,
                    "UnregisterClassW": lambda *a: 1, "DefWindowProcW": lambda *a: 0, "GetDpiForWindow": lambda *a: 0,
                    "ShowWindow": lambda hwnd, cmd: log("ShowWindow", role(hwnd), cmd) or 1,
                    "SetWindowPos": lambda hwnd, after, x, y, cx, cy, flags: log("SetWindowPos", role(hwnd), x, y, cx, cy,
                                                                                 flags) or 1,
                    "SetTimer": lambda hwnd, which, ms, proc: log("SetTimer", role(hwnd), which, ms) or 1,
                    "KillTimer": lambda hwnd, which: log("KillTimer", role(hwnd), which) or 1,
                    "PostMessageW": posted,
                    "SetForegroundWindow": lambda hwnd: log("SetForegroundWindow", role(hwnd)) or 1,
                    "SetFocus": lambda hwnd: log("SetFocus", role(hwnd)) or 1,
                    "InvalidateRect": lambda hwnd, *a: log("InvalidateRect", role(hwnd)) or 1,
                    "UpdateWindow": lambda hwnd: log("UpdateWindow", role(hwnd)) or 1,
                    "SetLayeredWindowAttributes": lambda hwnd, key, alpha, flags: log("SetLayeredWindowAttributes",
                                                                                      role(hwnd), alpha) or 1,
                    "TrackMouseEvent": lambda track: log("TrackMouseEvent", role(track._obj.hwndTrack)) or 1,
                    "GetKeyState": lambda key: state["keys"].get(key, 0),
                    "ClientToScreen": lambda hwnd, point: 1, "ScreenToClient": lambda hwnd, point: 1,
                }
                return stand[name] if name in stand else getattr(self._inner, name)

        def recorded_update(hwnd, *, at, alpha, dc, size, source=(0, 0), dirty=None):
            log("update", role(hwnd), "(%s, %s)" % (fmt(at[0]), fmt(at[1])), fmt(alpha),
                "(%d, %d)" % (int(size[0]), int(size[1])), "(%d, %d)" % (int(source[0]), int(source[1])),
                "None" if dirty is None else "(%s)" % ", ".join("%d" % int(value) for value in dirty))
            return True

        class Clock:
            @staticmethod
            def monotonic():
                return state["clock"]

            @staticmethod
            def time():
                return state["wall"]

        class Thread:
            def __init__(self, target=None, **unused):
                self.target = target

            def start(self):
                state["works"].append(self.target)

        class Threading:
            pass
        Threading.Thread = Thread

        def as_list(value):
            return plain(value) if value is not None else None

        def wire(action):
            """The action as the host posts it (PopupWindow.Fields), or None for a read."""
            calls = {"recovery": "set_interruption_recovery", "enabled": "set_enabled", "postpone": "postpone",
                     "unpostpone": "unpostpone", "release": "release_hold", "tier": "set_thread_tier",
                     "project": "set_project_rule", "unsay": "set_once_words"}
            kind = action[0]
            if kind == "dashboard":
                return ["open_dashboard", {"page": "pending", "row": None}]
            if kind == "dashboard_row" and len(action) == 4 and action[1] in ("message", "once_words"):
                return ["open_dashboard", {"page": "pending", "row": plain(list(action[1:]))}]
            if kind in calls:
                return ["popup", {"call": calls[kind], "args": plain(list(action[1:]))}]
            return None

        class Control:
            def __init__(self):
                self.rows = make_screenshots.popup_rows()
                self.status = make_screenshots.popup_status()

            def list_pending(self, source=None):
                return [dict(row) for row in self.rows]

            def get_status(self):
                return dict(self.status)

            def set_interruption_recovery(self, interruption_id, thread_id, enabled):
                for row in self.rows:
                    if row.get("interruption_id") == interruption_id:
                        row["thread_enabled"] = bool(enabled)
                return {"enabled": bool(enabled)}

            def set_enabled(self, enabled):
                self.status["enabled"] = bool(enabled)
                return {"enabled": bool(enabled)}

            def postpone(self, interruption_id, thread_id, preset=None):
                return {"postponed": preset}

            def unpostpone(self, *unused):
                return {}

            def release_hold(self, *unused):
                return {}

            def set_thread_tier(self, thread_id, tier, interruption_id=None):
                return {"tier": tier}

            def set_project_rule(self, *unused, source=None):
                return {}

            def set_once_words(self, *unused):
                return {}

        class Menu:
            hwnd = 0x7777

            def open(self, entries, strings, run, point=None, owner=None, on_leave=None):
                state["run"] = run
                state["menus"].append([plain(entries), list(point)])
                return True

            def close(self):
                state["menus"].append("close")

            def destroy(self):
                state["menus"].append("destroy")

        def core(popup):
            """What the core hands the host as the snapshot's popup, from the reference's model now."""
            vm = popup.model.view(state["wall"])
            return plain({"view": vm, "menus": [[task["interruption_id"], popup.model.menu_for(task["interruption_id"])]
                                                for task in vm["tasks"]],
                          "read": not (popup.model.rows is None and popup.model.status is None),
                          "attention": popup.model.attention()})

        def lparam(x, y):
            return (y & 0xFFFF) << 16 | (x & 0xFFFF)

        def centre(popup, name, key=None):
            plan = popup._painted_plan or popup._plan
            dx, dy = popup._client_offset()
            for target, rect in plan["targets"]:
                if target[0] == name and (key is None or (len(target) > 1 and target[1] == key)):
                    return lparam((rect[0] + rect[2]) // 2 - dx, (rect[1] + rect[3]) // 2 - dy)
            return 0

        def task_id(popup, index=0):
            tasks = (popup._vm or {}).get("tasks") or []
            return tasks[index]["interruption_id"] if len(tasks) > index else None

        def row_point(popup, index=0):
            rows = list((popup._painted_plan or {}).get("rows") or ())
            if len(rows) <= index:
                return 0
            dx, dy = popup._client_offset()
            left, top, right, bottom = rows[index][1]
            return lparam((left + right) // 2 - dx, (top + bottom) // 2 - dy)

        def title_point(popup):
            dx, dy = popup._client_offset()
            for item in (popup._painted_plan or {}).get("items", ()):
                if item["kind"] == "title_press":
                    left, top, right, bottom = item["rect"]
                    return lparam(int(left + right) // 2 - dx, int(top + bottom) // 2 - dy)
            return 0

        def pump(popup):
            for _ in range(100):
                if not state["queue"]:
                    break
                hwnd, message, wparam, lparam_ = state["queue"].pop(0)
                popup._wndproc(hwnd, message, wparam, lparam_)

        # What is aimed at the reference's plan at the time ("move", "click", "title", "menu row") becomes the message
        # numbers both are sent.
        script = ([["show", False, True], ["pump"]] + [["clock", 0.05], ["timer", frame], ["pump"]] * 6
                  + [["move", "toggle"], ["pump"], ["clock", 0.05], ["timer", frame], ["pump"], ["leave"], ["pump"],
                     ["click", "check", 0], ["pump"], ["clock", 1.0], ["proof"], ["result"], ["pump"],
                     ["clock", 0.1], ["timer", frame], ["pump"], ["clock", 0.5], ["timer", frame], ["pump"],
                     ["timer", tick], ["timer", tick], ["timer", tick], ["pump"], ["result"], ["pump"],
                     ["key", 0x09], ["key", 0x09], ["shift", True], ["key", 0x09], ["shift", False], ["key", 0x28], ["pump"],
                     ["key", 0x20], ["pump"], ["key", 0x20, 1 << 30], ["result"], ["pump"],
                     ["menu", 0xFFFFFFFF], ["menu", "row"], ["choose", 1], ["pump"], ["result"], ["pump"], ["choose", 99],
                     ["click", "toggle"], ["pump"], ["result"], ["pump"], ["clock", 1.0], ["proof"],
                     ["strings"], ["pump"], ["clock", 1.0], ["proof"]]
                  + [["clock", 0.2], ["title"]] * 7
                  + [["pump"], ["clock", 0.05], ["timer", frame], ["pump"], ["clock", 0.9], ["timer", frame], ["pump"],
                     ["message", WM_SETTINGCHANGE, 0, 0], ["pump"], ["held", True], ["timer", tick], ["pump"], ["held", False],
                     ["message", WM_DPICHANGED, 120, 0], ["pump"], ["message", WM_ACTIVATE, 0, 0x7777],
                     ["message", WM_ACTIVATE, 0, 0], ["select", False], ["clock", 0.2], ["select", False], ["clock", 1.0],
                     ["select", False], ["pump"], ["key", 0x1B], ["double"], ["pump"], ["clock", 0.2], ["select", True],
                     ["select", True], ["clock", 0.5], ["select", True], ["message", 0x0010, 0, 0], ["clock", 1.0],
                     ["select", False], ["pump"], ["click", "dashboard"], ["pump"], ["result"], ["pump"]])
        screen = {"icon": [1800, 1045, 1824, 1069], "cursor": [1810, 1050], "work": [0, 0, 1920, 1040],
                  "monitor": [0, 0, 1920, 1080]}
        runs = [("en", ["light", "soft", False], False, False, 1.0, 1.5), ("ko", ["dark", "plain", False], False, False, 1.0, 1.5),
                ("ar", ["light", "classic", False], False, False, 1.0, 1.25), ("en", ["dark", "soft", True], False, False, 1.0, 2.0),
                ("ko", ["light", "soft", False], True, False, 1.0, 1.5), ("en", ["light", "soft", False], False, True, 1.0, 1.5),
                ("de" if "de" in interface.STRINGS else "en", ["dark", "classic", False], False, False, 1.75, 1.0)]
        special = make_screenshots.POPUP_NOW
        for day in range(400):
            if brand.day_look_at(make_screenshots.POPUP_NOW + day * 86400):
                special = make_screenshots.POPUP_NOW + day * 86400
                break
        renderer_module.system_rgb = light_module.system_rgb = lambda name: tuple(self.SYSTEM[name])
        window._dll = messages._dll = layers._dll = lambda name: User32(real(name)) if name == "user32" else real(name)
        layers.update = recorded_update
        window.time = messages.time = hidden_module.time = motion_module.time = Clock
        messages.threading = Threading
        access.announce = lambda *unused: None
        access.answer = lambda *unused, **more: 0
        access.disconnect = lambda *unused: None
        try:
            with make_screenshots.pinned_face():
                pinned = fonts._ui_face()
                for locale, look, reduced, days, text, scale in runs:
                    strings = interface.STRINGS[locale]
                    other = interface.STRINGS["ko" if locale != "ko" else "en"]
                    state.update(clock=1000.0, wall=special if days else make_screenshots.POPUP_NOW, roles={}, calls=[],
                                 queue=[], works=[], keys={}, held=False, menus=[], run=None, posts=[])
                    theme.high_contrast = lambda: look[2]
                    theme.reduced_motion = lambda: reduced
                    theme.apps_use_light_theme = lambda: look[0] == "light"
                    theme.text_scale = lambda: text
                    theme.adopt_settings({"theme": look[0], "design": look[1], "reduce_motion": False})
                    before = gdiplus.gdiplus_objects()
                    logged = []
                    control = Control()
                    popup = window.Popup(control=control, source="names", strings=strings, log=logged.append,
                                         on_dashboard=lambda row=None: True, anchor=None, make_menu=Menu, days=days,
                                         held=lambda: state["held"])
                    popup.model.apply_outcome(("read",), messages.perform(("read",), control, source="names"), state["wall"])
                    shown_screen = dict(screen, dpi=int(round(96 * scale)))
                    popup._screen_now = lambda: {key: tuple(value) if isinstance(value, list) else value
                                                 for key, value in shown_screen.items()}
                    finished, events = popup._finished, []

                    def handled(number, popup=popup, finished=finished, events=events):
                        action = popup._results.get(number, (None, None))[0]
                        finished(number)
                        if action is not None:
                            if action[0] != "read":
                                events.append({"answer": True})
                            events.append({"view": core(popup)})
                    popup._finished = handled
                    run_ = popup._run

                    def running(action, run_=run_):
                        wired = wire(action)
                        run_(action)
                        work = state["works"][-1]

                        def posting(work=work, wired=wired):
                            if wired is not None:             # recorded as it runs, as the host's worker posts it
                                state["posts"].append(wired)
                            work()
                        state["works"][-1] = posting
                    popup._run = running
                    sharp = [{"op": "core", "do": ["core", core(popup)]}]
                    steps, proofs = [], []
                    try:
                        for step in script:
                            op, returned, mapped = step[0], None, list(step)
                            state["calls"], state["menus"], state["posts"] = [], [], []
                            del events[:]
                            if op == "show":
                                popup.show(keyboard=step[1], activate=step[2])
                            elif op == "select":
                                popup.on_select(keyboard=step[1])
                            elif op == "double":
                                popup.on_double_click()
                            elif op == "clock":
                                state["clock"] += step[1]
                            elif op == "held":
                                state["held"] = step[1]
                            elif op == "shift":
                                state["keys"][0x10] = -128 if step[1] else 0
                            elif op in ("timer", "message", "key", "move", "leave", "click", "title", "menu"):
                                if op == "timer":
                                    sent = [(WM_TIMER, step[1], 0)]
                                elif op == "message":
                                    sent = [(step[1], step[2], step[3])]
                                elif op == "key":
                                    sent = [(WM_KEYDOWN, step[1], step[2] if len(step) > 2 else 0)]
                                elif op == "move":
                                    sent = [(WM_MOUSEMOVE, 0, centre(popup, step[1]))]
                                elif op == "leave":
                                    sent = [(WM_MOUSELEAVE, 0, 0)]
                                elif op == "click":
                                    point = centre(popup, step[1], task_id(popup, step[2]) if len(step) > 2 else None)
                                    sent = [(WM_LBUTTONDOWN, 0, point), (WM_LBUTTONUP, 0, point)]
                                elif op == "title":
                                    point = title_point(popup)
                                    sent = [(WM_LBUTTONDOWN, 0, point), (WM_LBUTTONUP, 0, point)]
                                else:
                                    sent = [(WM_CONTEXTMENU, 0, row_point(popup) if step[1] == "row" else step[1])]
                                returned = [int(popup._wndproc(popup.hwnd, message, wparam, lparam_) or 0)
                                            for message, wparam, lparam_ in sent]
                                mapped = ["messages", [list(one) for one in sent]]
                            elif op == "pump":
                                pump(popup)
                            elif op == "result":
                                works, state["works"] = state["works"], []
                                for work in works:
                                    work()
                                pump(popup)
                                mapped = ["result", [dict(event) for event in events]]
                            elif op == "choose":
                                if state["run"] is not None:
                                    state["run"](step[1])
                            elif op == "strings":
                                popup.set_strings(other)
                                shown = popup_words.locale_of(other)
                                # the core makes the view in the new words (its model's strings) for the next snapshot
                                popup.model.strings = dict(other)
                                mapped = ["strings", plain(other), shown, fonts._letters(shown), core(popup)]
                            elif op == "proof":
                                popup._static_dirty = True
                                proofs.append(hashlib.sha256(popup.render().pixels()).hexdigest())
                                sharp.append({"op": op, "do": ["proof"]})
                                continue
                            sharp.append({"op": op, "do": mapped})
                            canvas = popup._renderer.canvas if popup._renderer is not None and popup._plan is not None else None
                            steps.append({
                                "op": op, "visible": popup.visible, "alpha": popup._alpha, "below": popup._below,
                                "home": as_list(popup._home), "card": popup._card, "frames": popup._frame_running,
                                "pending": popup._pending_show is not None, "hover": as_list(popup.hover),
                                "pressed": as_list(popup.pressed), "focus": as_list(popup.focus), "keyboard": popup.keyboard,
                                "size": as_list(popup._plan["size"]) if popup._plan is not None else None,
                                "painted": popup._painted_plan is not None and popup._painted_plan is popup._plan,
                                "pixels": hashlib.sha256(canvas.pixels()).hexdigest() if canvas else None,
                                "calls": [call for call in state["calls"] if not call.startswith("PostMessageW card %d " % RESULT)],
                                "menus": list(state["menus"]), "posts": list(state["posts"]), "returned": returned,
                                "sweeping": popup.sweeping(), "dpi": popup.dpi,
                            })
                    finally:
                        popup.destroy()
                    self.add("popupwindow/%s/%s-%s-%s/%s-%s-%r-%r" % (locale, look[0], look[1], look[2], reduced, days, text,
                                                                     scale),
                             {"surface": "popup_window", "strings": strings, "locale": popup_words.locale_of(strings),
                              "letters": fonts._letters(popup_words.locale_of(strings)), "look": look, "reduced": reduced,
                              "days": days, "text_scale": text, "now": state["wall"], "screen": plain(shown_screen),
                              "script": sharp, "pinned": pinned, "system": self.SYSTEM},
                             {"steps": steps, "proofs": [[digest, digest, True] for digest in proofs], "log": logged,
                              "left": gdiplus.gdiplus_objects() - before})
        finally:
            (renderer_module.system_rgb, light_module.system_rgb, window._dll, messages._dll, layers._dll, layers.update,
             window.time, messages.time, hidden_module.time, messages.threading, access.announce, access.answer,
             access.disconnect, theme.high_contrast, theme.reduced_motion, theme.apps_use_light_theme,
             theme.text_scale, motion_module.time) = saved
            theme.adopt_settings({})

    def menu_window(self):
        """The drawn menu as a window: the reference's Menu driven through a script - opened at a point, its fade, its
        keys and letters, the pointer, a submenu opened by key and by rest, a choice, the ways it closes - every call
        that would put it on the screen recorded by a stand-in and not made, and the C#'s MenuWindow over a window made
        and never shown, through the same script. After each step: shown, item in hand, fade, place, the submenu, the
        picture by digest, the calls, what was chosen and who was told it closed."""
        import hashlib
        import make_screenshots
        from codex_auto_resume import interface
        from codex_auto_resume.ui import popup as popup_package
        from codex_auto_resume.ui.popup import (access, fonts, gdiplus, light as light_module, menuplan, menuwindow,
                                                renderer as renderer_module, theme, words as popup_words)
        WM_TIMER, WM_KEYDOWN, WM_CHAR, WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0113, 0x0100, 0x0102, 0x0200, 0x0201, 0x0202
        WM_ACTIVATE, WM_SYSKEYDOWN, WM_SETTINGCHANGE, WM_MOUSELEAVE = 0x0006, 0x0104, 0x001A, 0x02A3
        NOACTIVATE, OWNER = 0x08000000, 0x9999
        saved = (renderer_module.system_rgb, light_module.system_rgb, menuwindow._dll, menuwindow.time, access.announce,
                 access.answer, access.disconnect, access.tell, theme.high_contrast, theme.reduced_motion,
                 theme.apps_use_light_theme, theme.text_scale)
        real = menuwindow._dll
        state = {}

        def role(hwnd):
            return state["roles"].get(hwnd, "0x%x" % (hwnd or 0))

        def log(*parts):
            state["calls"].append(" ".join(str(part) for part in parts))

        def made(style, klass, title, *rest):
            hwnd = 0x6000 + len(state["roles"])
            state["roles"][hwnd] = "child" if style & NOACTIVATE else "menu"
            return hwnd

        def foreground(hwnd):
            log("SetForegroundWindow", role(hwnd))
            state["front"] = hwnd if state["grant"] else state["front"]
            return 1

        def layered(hwnd, screen, where, size, dc, source, key, blend, flags):
            log("UpdateLayeredWindow", role(hwnd), where._obj.x, where._obj.y, size._obj.cx, size._obj.cy,
                blend._obj.SourceConstantAlpha)
            return 1

        def set_style(hwnd, index, value):
            log("SetWindowLongW", role(hwnd), value)
            state["styles"][hwnd] = value
            return 1

        class User32:
            def __init__(self, inner):
                self._inner = inner

            def __getattr__(self, name):
                stand = {
                    "RegisterClassW": lambda *a: 1, "CreateWindowExW": made, "DestroyWindow": lambda *a: 1,
                    "UnregisterClassW": lambda *a: 1, "DefWindowProcW": lambda *a: 0,
                    "ShowWindow": lambda hwnd, cmd: log("ShowWindow", role(hwnd), cmd) or 1,
                    "SetWindowPos": lambda hwnd, after, x, y, cx, cy, flags: log("SetWindowPos", role(hwnd), x, y, cx, cy,
                                                                                 flags) or 1,
                    "SetTimer": lambda hwnd, which, ms, proc: log("SetTimer", role(hwnd), which, ms) or 1,
                    "KillTimer": lambda hwnd, which: log("KillTimer", role(hwnd), which) or 1,
                    "SetForegroundWindow": foreground, "GetForegroundWindow": lambda: state["front"],
                    "SetFocus": lambda hwnd: log("SetFocus", role(hwnd)) or 1,
                    "UpdateLayeredWindow": layered, "SetWindowLongW": set_style,
                    "GetWindowLongW": lambda hwnd, index: state["styles"].get(hwnd, 0),
                    "TrackMouseEvent": lambda track: log("TrackMouseEvent", role(track._obj.hwndTrack)) or 1,
                }
                return stand[name] if name in stand else getattr(self._inner, name)

        class Clock:
            @staticmethod
            def monotonic():
                return state["clock"]

        def centre(menu, index):
            for item in (menu._plan or {}).get("items", ()):
                if item.get("index") == index:
                    left, top, right, bottom = item["rect"]
                    return ((top + bottom) // 2 & 0xFFFF) << 16 | ((left + right) // 2 & 0xFFFF)
            return 0

        def described(menu):
            if menu is None:
                return None
            canvas = menu._renderer.canvas if menu._renderer is not None and menu._plan is not None else None
            return {"visible": menu.visible, "selected": menu.selected, "alpha": menu._alpha, "below": menu._below,
                    "fade": menu._fade[0] if menu._fade else None, "origin": plain(menu._origin),
                    "size": plain(menu._plan["size"]) if menu._plan is not None else None,
                    "pixels": hashlib.sha256(canvas.pixels()).hexdigest() if canvas else None}

        status = make_screenshots.popup_status()
        script = ([["open", [1000, 900]]] + [["clock", 0.03], ["timer", 2]] * 9
                  + [["key", 0x28], ["key", 0x28], ["key", 0x26], ["key", 0x24], ["key", 0x23], ["char", "p"], ["char", "x"],
                     ["over", 0], ["over", 1], ["timer", 1], ["key", "onward"], ["child", WM_KEYDOWN, 0x28, 0],
                     ["child", WM_CHAR, 0x31, 0], ["key", "back"], ["over", "submenu"], ["timer", 1], ["child_over", 0],
                     ["child_up", 0], ["clock", 0.05], ["timer", 2], ["clock", 0.2], ["timer", 2],
                     ["open", [40, 40]], ["message", WM_ACTIVATE, 0, OWNER], ["open", [1900, 1030]], ["clock", 0.3],
                     ["timer", 2], ["message", WM_ACTIVATE, 0, 0], ["clock", 0.3], ["timer", 2], ["open", None],
                     ["message", WM_SYSKEYDOWN, 0x12, 0], ["open", [500, 500]], ["message", WM_LBUTTONDOWN, 0, 0x7FFF7FFF],
                     ["open", [500, 500]], ["message", WM_SETTINGCHANGE, 0, 0], ["over", 2], ["message", WM_MOUSELEAVE, 0, 0],
                     ["key", 0x0D], ["grant", False], ["open", [500, 500]], ["grant", True], ["open", [600, 600]],
                     ["message", 0x0010, 0, 0]])
        runs = [("en", ["light", "soft", False], False, 1.0, 144), ("ko", ["dark", "plain", False], False, 1.0, 120),
                ("ar", ["light", "classic", False], False, 1.0, 144), ("en", ["dark", "soft", True], False, 1.0, 192),
                ("en", ["light", "soft", False], True, 1.5, 96)]
        renderer_module.system_rgb = light_module.system_rgb = lambda name: tuple(self.SYSTEM[name])
        menuwindow._dll = lambda name: User32(real(name)) if name == "user32" else real(name)
        menuwindow.time = Clock
        access.announce = lambda *unused: None
        access.answer = lambda *unused, **more: 0
        access.disconnect = lambda *unused: None
        access.tell = lambda hwnd, event: log("NotifyWinEvent", role(hwnd), event)
        try:
            with make_screenshots.pinned_face():
                pinned = fonts._ui_face()
                for locale, look, reduced, text, dpi in runs:
                    strings = interface.STRINGS[locale]
                    model = popup_package.PopupModel(strings)
                    model.apply_outcome(("read",), ("ok", {"rows": make_screenshots.popup_rows(), "status": status}),
                                        make_screenshots.POPUP_NOW)
                    vm = model.view(make_screenshots.POPUP_NOW)
                    entries, _ = menuplan.menu_numbered(model.menu_for(vm["tasks"][0]["interruption_id"]))
                    submenu = next(index for index, entry in enumerate(entries) if entry and entry.get("items"))
                    state.update(clock=1000.0, roles={}, calls=[], styles={}, front=0, grant=True, chosen=[], left=[])
                    theme.high_contrast = lambda: look[2]
                    theme.reduced_motion = lambda: reduced
                    theme.apps_use_light_theme = lambda: look[0] == "light"
                    theme.text_scale = lambda: text
                    theme.adopt_settings({"theme": look[0], "design": look[1], "reduce_motion": False})
                    before = gdiplus.gdiplus_objects()
                    logged = []
                    menu = menuwindow.Menu(log=logged.append)
                    work = [0, 0, 1920, 1040]
                    menu._screen_now = lambda at=None: {"cursor": tuple(at) if at else (960, 520), "dpi": dpi,
                                                        "work": tuple(work)}
                    sharp, steps = [], []
                    try:
                        for step in script:
                            op, mapped, returned = step[0], list(step), None
                            state["calls"], state["left"] = [], []
                            del state["chosen"][:]                  # the list each opening hands its choices to
                            rtl = bool((menu._plan or {}).get("rtl"))
                            if op == "open":
                                returned = menu.open(entries, strings, state["chosen"].append, point=step[1], owner=OWNER,
                                                     on_leave=lambda: state["left"].append(True))
                                mapped = ["open", step[1], plain(entries)]
                            elif op == "clock":
                                state["clock"] += step[1]
                            elif op == "grant":
                                state["grant"] = step[1]
                            else:
                                target, sent = menu, None
                                if op == "timer":
                                    sent = (WM_TIMER, step[1], 0)
                                elif op == "key":
                                    key = step[1]
                                    if key == "onward":
                                        key = 0x25 if rtl else 0x27
                                    elif key == "back":
                                        key = 0x27 if rtl else 0x25
                                    sent = (WM_KEYDOWN, key, 0)
                                elif op == "char":
                                    sent = (WM_CHAR, ord(step[1]), 0)
                                elif op == "over":
                                    sent = (WM_MOUSEMOVE, 0, centre(menu, submenu if step[1] == "submenu" else step[1]))
                                elif op == "child":
                                    target, sent = menu._child, (step[1], step[2], step[3])
                                elif op == "child_over":
                                    target = menu._child
                                    sent = (WM_MOUSEMOVE, 0, centre(target, step[1]) if target else 0)
                                elif op == "child_up":
                                    target = menu._child
                                    sent = (WM_LBUTTONUP, 0, centre(target, step[1]) if target else 0)
                                else:
                                    sent = (step[1], step[2], step[3])
                                which = "child" if target is not menu else "menu"
                                if target is not None and target.hwnd:
                                    returned = int(target._wndproc(target.hwnd, *sent) or 0)
                                mapped = ["message", which, list(sent)]
                            sharp.append({"op": op, "do": mapped})
                            steps.append({"op": op, "menu": described(menu), "child": described(menu._child),
                                          "calls": list(state["calls"]), "chosen": plain(state["chosen"]),
                                          "left": list(state["left"]), "returned": returned})
                    finally:
                        menu.destroy()
                    self.add("menuwindow/%s/%s-%s-%s/%s-%r-%d" % (locale, look[0], look[1], look[2], reduced, text, dpi),
                             {"surface": "menu_window", "strings": strings, "locale": popup_words.locale_of(strings),
                              "letters": fonts._letters(popup_words.locale_of(strings)), "look": look, "reduced": reduced,
                              "text_scale": text, "dpi": dpi, "work": work, "owner": OWNER, "script": sharp,
                              "pinned": pinned, "system": self.SYSTEM},
                             {"steps": steps, "log": logged, "left": gdiplus.gdiplus_objects() - before})
        finally:
            (renderer_module.system_rgb, light_module.system_rgb, menuwindow._dll, menuwindow.time, access.announce,
             access.answer, access.disconnect, access.tell, theme.high_contrast, theme.reduced_motion,
             theme.apps_use_light_theme, theme.text_scale) = saved
            theme.adopt_settings({})

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
        sources = [ROOT / name for name in guiscan.host_group("contract") + guiscan.host_group("surface")
                                                 + guiscan.host_group("generated")]
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
        job.tip_window()
        job.popup_window()
        job.menu_window()
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


    def test_the_icons_card_window_lives_and_paints_as_the_references_offscreen(self):
        self.compare("tipwindow/")

    def test_the_popup_window_lives_and_paints_as_the_references_offscreen(self):
        self.compare("popupwindow/")

    def test_the_drawn_menu_window_opens_steps_and_closes_as_the_references_offscreen(self):
        self.compare("menuwindow/")


if __name__ == "__main__":
    unittest.main()
