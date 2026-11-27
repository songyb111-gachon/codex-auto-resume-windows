"""The seventh press of the popup's title on the C# host (S6.4d4, P6-DESIGN 3.4 "window").

Twins of tests/test_gui_v0623_surfaces.py's PopupPressTests:

* The four presses-and-sentence tests: the originals' bodies through `super()`, the popup they make the host's PopupWindow
  (HostProbe.cs `popup_press`): no window (its Hwnd none, so Update and SyncFrames reach nothing; every Windows call
  recorded besides), the test's reduced, contrast, visible, painted plan and strings given; each `title_pressed`, each
  assignment of `_aside_from` and each `aside_words` (with the test's patched clock at that call, as the host's Monotonic) a
  step of one history replayed from the start for every question - the private TitlePressed and AsideWords by reflection,
  and SweepSince/AsideFrom read back.
* `test_it_reaches_nothing_but_the_window`: the same rule over the host's half of hidden.py - PopupWindow's members of "the
  seventh press" (DayView, TitlePressed, Press, TitlePress, Sweeping, AsideWords, StepHidden), found by guiscan - with the
  host's names for what the reference's list keeps out (the core's actions and their posting, a read asked, a file, a log).
* `test_the_title_is_no_target_...`: the original's body with the host's layout (gui/SurfaceRenderer.cs, its plan's items
  and targets) and its hit test (PopupPlace.HitTest).

Nothing is shown: the probe runs with CREATE_NO_WINDOW and makes no window.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import sys
import unittest
import unittest.mock

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "tests"), str(ROOT / "tests" / "rustdiff")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import guiscan  # noqa: E402
import surfacehost  # noqa: E402
import test_gui_v0623_surfaces as original  # noqa: E402  (a module name: its classes are not collected here)

ON_HOST = unittest.skipUnless(os.name == "nt" and surfacehost.CSC.is_file(), "the host's surfaces need the in-box C# compiler")
SEVENTH_PRESS = ("DayView", "TitlePressed", "Press", "TitlePress", "Sweeping", "AsideWords", "StepHidden")
# The reference keeps out "control", "perform", "_request_read", "open(", "journal", "log(": the host's names for them.
NEVER = ("Actions", "Post(", "Run(", "Begin(", "RequestRead", "File.", "Journal", "Log(")


def host_member(type_name, member):
    """One member of a type of the host's [surface] sources (gui/host.sources), as guiscan.member_body finds one of the
    window's: every part of the type, a declaration and never a call, by its braces."""
    pattern = re.compile(r"(?m)^[ \t]*(?:(?:%s)[ \t]+)*[\w<>,\[\]\.\?]+[ \t]+%s[ \t]*[\(\{]"
                         % ("|".join(guiscan.MODIFIERS), re.escape(member)))
    for source in guiscan.host_group("surface"):
        try:
            body = guiscan.type_body(type_name, (ROOT / source).read_text(encoding="utf-8"))
        except guiscan.ScanError:
            continue
        found = pattern.search(body)
        if found is not None:
            return guiscan._block(body, found.start())
    raise guiscan.ScanError("%s has no member named %s in the host's sources" % (type_name, member))


def _plain(value):
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _tuple(value):
    return tuple(_tuple(part) for part in value) if isinstance(value, list) else value


class HostPressPopup:
    """The test's Popup made with `__new__`: what it sets, and every press and sentence a step of one history."""

    def __init__(self, reduced, contrast, visible, plan, strings):
        object.__setattr__(self, "_given", {"reduced": bool(reduced), "contrast": bool(contrast), "visible": bool(visible),
                                            "items": _plain(plan["items"]), "strings": dict(strings)})
        object.__setattr__(self, "_steps", [])

    def _ask(self, steps):
        return surfacehost.SERVE.ask("popup_press", op="steps", steps=steps, **self._given)

    def title_pressed(self, lparam, now_ms):
        self._steps.append(["press", int(lparam), float(now_ms)])

    def aside_words(self, state_text):
        from codex_auto_resume.ui.popup import hidden
        step = ["aside_words", state_text, float(hidden.time.monotonic())]
        self._steps.append(step)
        return self._ask(self._steps)["words"]

    @property
    def _sweep_since(self):
        return self._ask(self._steps)["sweep_since"]

    def __getattr__(self, name):
        if name == "_aside_from":
            return self._ask(self._steps)["aside_from"]
        raise AttributeError(name)

    def __setattr__(self, name, value):
        if name != "_aside_from":
            raise AttributeError("the host's popup has no %s to set" % name)
        self._steps.append(["set_aside", None if value is None else float(value)])


class HostLayoutRenderer:
    """popup.Renderer as the last test uses it: the host's layout, its items and targets."""

    def layout(self, vm, scale, locale):
        found = surfacehost.SERVE.ask("popup_press", op="layout", vm=_plain(vm), scale=float(scale), locale=locale)
        return {"items": [dict(item, rect=_tuple(item["rect"])) for item in found["items"]],
                "targets": [(_tuple(target), _tuple(rect)) for target, rect in found["targets"]]}

    def close(self):
        pass


def host_hit_test(targets, x, y):
    found = surfacehost.SERVE.ask("popup_press", op="hit", targets=[[_plain(t), list(r)] for t, r in targets], x=int(x), y=int(y))
    return _tuple(found)


@ON_HOST
class PopupPressOnHostTests(original.PopupPressTests):
    def popup(self, reduced=False):
        return HostPressPopup(reduced, False, True, self.PLAN, {"status.aside": "The sentence"})

    def test_seven_presses_of_the_title_start_it_once(self):
        super().test_seven_presses_of_the_title_start_it_once()

    def test_a_press_anywhere_else_is_not_counted(self):
        super().test_a_press_anywhere_else_is_not_counted()

    def test_with_motion_reduced_no_sweep_and_the_sentence_at_once(self):
        super().test_with_motion_reduced_no_sweep_and_the_sentence_at_once()

    def test_the_sentence_stands_for_its_moment_and_the_state_line_returns(self):
        super().test_the_sentence_stands_for_its_moment_and_the_state_line_returns()

    def test_it_reaches_nothing_but_the_window(self):
        source = "\n".join(host_member("PopupWindow", member) for member in SEVENTH_PRESS)
        for never in NEVER:
            self.assertNotIn(never, source)

    def test_the_title_is_no_target_so_a_press_on_it_does_what_it_always_did(self):
        with unittest.mock.patch.object(original.tray_popup, "Renderer", HostLayoutRenderer), \
                unittest.mock.patch.object(original.tray_popup, "hit_test", host_hit_test):
            super().test_the_title_is_no_target_so_a_press_on_it_does_what_it_always_did()


if __name__ == "__main__":
    unittest.main()
