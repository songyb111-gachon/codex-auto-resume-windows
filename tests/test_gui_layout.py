"""The settings window's layout rules, and a measurement that holds the window to them.

Clipped fields taught the first of them. The "Retry timing" drop-down, and in v0.6.3
"Continuation language" and "Preview for", rendered without a bottom border. The cause was
measurement, not drawing:

* `NewRow` sizes a row from its label's cell, and it froze the label's margins from the
  editor's height *before the row had a parent* - so everything was measured in
  `Control.DefaultFont` (Gulim 9pt on a Korean Windows), not in the window's font; and
* the drop-down took its real height only afterwards, when the window's font reached it,
  and its `PreferredSize` answered 33 for a 42-pixel owner-drawn field in any case.

A child window is clipped to its parent, so the part of the field below the row - its bottom
border - was cut: 5 to 10 pixels at every scaling, in every language (measured with the real
sources). v0.5.x had held only because a plain ComboBox and its label happened to grow by
about the same amount when the font arrived; the earlier explanation, that a ComboBox
under-reports its height until it has been shown, was not the mechanism - hidden and shown
measured the same.

The source-shape tests pin the reasoning, which is what a later edit would throw away.
`LayoutAuditTests` builds the real window, never shown, and measures every page in every
language at five scalings, which is what a later edit would break.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import unittest
import guiscan

from codex_auto_resume import brand, l10n, machine, settings

ROOT = Path(__file__).resolve().parents[1]
CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")


class RowLayoutTests(unittest.TestCase):
    def setUp(self):
        self.source = guiscan.settings()
        start = self.source.index("private Control NewRow(")
        self.row = self.source[start:self.source.index("private string Humanise(", start)]

    def test_the_editor_is_anchored_to_the_top_and_not_only_to_the_right(self):
        anchors = re.findall(r"editor\.Anchor\s*=\s*([^;]+);", self.row)
        self.assertEqual(len(anchors), 1, "NewRow should set the editor anchor exactly once")
        self.assertIn("Top", anchors[0],
                      "a Right-only anchor centres the editor in a row measured before the "
                      "editor had its real height, and its bottom border hangs below the row")
        self.assertIn("Right", anchors[0], "the editor still aligns to the right of its cell")

    def test_the_row_height_is_reserved_from_the_editors_real_height(self):
        # The label's margins are what make the row tall enough, because the row is
        # measured from the label's cell. A fixed margin cannot know how tall the
        # editor will turn out to be at this scaling, in this font.
        self.assertIn("Math.Max(editor.Height, editor.PreferredSize.Height)", self.row,
                      "a drop-down's PreferredSize answered 33 for a 42-pixel field; its "
                      "Height is what the row has to hold")
        self.assertIn("label.PreferredSize.Height", self.row,
                      "centring the label needs its own measured height")
        self.assertNotRegex(
            self.row, r"label\.Margin\s*=\s*Pad\(",
            "a Pad(...) margin here is a fixed row height again; use the measured one")

    def test_the_margins_are_worked_out_again_when_a_height_or_a_font_changes(self):
        """Worked out once, in NewRow, they were worked out in the default font.

        The row has no parent there, so neither the label nor the editor has the window's
        font yet, and the drop-down has not taken its real height. Both change after NewRow
        returns, and nothing measured the row again.
        """
        for hook in ("editor.SizeChanged +=", "editor.FontChanged +=", "label.FontChanged +="):
            with self.subTest(hook):
                self.assertIn(hook, self.row)

    def test_the_editor_carries_no_vertical_margin(self):
        """Measured: a vertical margin on the editor re-introduces the clipping at 125%.

        The row does not grow to accommodate it, because the row is measured from the
        label's cell - so the margin only pushes the editor further down inside a row that
        never got taller.
        """
        margins = re.findall(r"editor\.Margin\s*=\s*([^;]+);", self.row)
        self.assertEqual(len(margins), 1)
        self.assertIn("new Padding(0)", margins[0])


class WatcherStartReportingTests(unittest.TestCase):
    """The window may not say the watcher is running on the strength of a launch."""

    def setUp(self):
        self.source = guiscan.settings()
        start = self.source.index("private void StartWatcher()")
        # Both halves: the click handler that dispatches, and the continuation that
        # BeginInvoke brings back to the UI thread.
        self.method = self.source[start:self.source.index("private void Save()", start)]

    def test_it_does_not_wait_a_fixed_time_and_hope(self):
        self.assertNotIn("Thread.Sleep", self.method,
                         "a fixed wait is both slower than an ordinary start and shorter "
                         "than a slow one; the engine now waits for the real answer")

    def test_the_wait_does_not_happen_on_the_ui_thread(self):
        """A guard the first version of this needed and did not have.

        Removing `Thread.Sleep` did not remove the wait: it moved into the bridge call,
        which starts python.exe and blocks until it exits, and the engine behind it now
        waits up to six seconds for the watcher to report in. On the click handler that
        is six seconds without pumping messages, and Windows retitles a window that has
        not pumped for five "Not Responding" and paints a grey ghost of it. The old test
        passed throughout, because it only looked for the word `Sleep`.
        """
        self.assertIn("QueueUserWorkItem", self.method,
                      "the blocking call must not run on the click handler")
        self.assertIn("BeginInvoke", self.method,
                      "the answer has to come back to the UI thread to touch a control")
        call = self.method.index('bridge.Call("start-watcher"')
        worker = self.method.index("QueueUserWorkItem")
        self.assertLess(worker, call, "the call must be inside the worker, not before it")

    def test_it_reads_the_state_the_engine_reported(self):
        self.assertIn('"state"', self.method,
                      "the window must report what the engine observed, not that the call "
                      "returned")
        for state in ('"running"', '"already-running"', '"exited"'):
            self.assertIn(state, self.method, state)


class BufferedPaintTests(unittest.TestCase):
    """Every control that paints itself is double-buffered.

    Three captures in a row lost something drawn in a Paint handler - the status dot, the
    header's hairline, then a whole card's border and accent rail - because an unbuffered
    control is erased to its background first and painted a moment later, and anything
    that looks in between sees the erased state. Fixing them one at a time only moved the
    bug to the next painter, so this checks all of them.
    """

    BUFFERED = {"BufferedPanel", "BufferedTable"}

    def test_every_paint_handler_is_on_a_buffered_control(self):
        # Both files of the window. Since v0.6.4 the strips draw no rule of their own - the
        # header and footer are cards on grounds, which are buffered by construction - so there
        # may be no handler left at all; any that returns is held to the rule.
        source = guiscan.window()
        self.assertRegex(source, r"\.Paint \+=|override void OnPaint\(",
                         "nothing in the window paints itself - the patterns are wrong")
        painters = sorted(set(re.findall(r"(\w+)\.Paint \+=", source)))
        for name in painters:
            declared = re.search(r"(?:var|Panel|TableLayoutPanel)\s+%s\s*=\s*new\s+(\w+)\(" % name, source)
            with self.subTest(name):
                self.assertIsNotNone(declared, "cannot find where %s is created" % name)
                self.assertIn(declared.group(1), self.BUFFERED,
                              "%s paints itself but is a plain %s" % (name, declared.group(1)))

    def test_every_control_that_draws_itself_is_buffered(self):
        """A control class with its own OnPaint - the outcome chart - is the same painter."""
        source = guiscan.window()
        classes = re.split(r"\n\s*(?:internal|public|private)\s+(?:sealed\s+)?(?:partial\s+)?class\s+", source)
        drawn = [body for body in classes if "override void OnPaint(" in body]
        self.assertTrue(drawn, "no OnPaint override found - the pattern is wrong")
        for body in drawn:
            name = body.split(None, 1)[0]
            with self.subTest(name):
                self.assertIn("ControlStyles.OptimizedDoubleBuffer", body,
                              "%s paints itself without a back buffer" % name)


class PersistentBridgeTests(unittest.TestCase):
    """The long-lived bridge process actually starts.

    Its first version passed the Python code without "-c", so python.exe took the code
    for a script path and exited, and every call fell back to the one-shot bridge. Every
    answer was still right, which is exactly why nothing noticed: the fallback hid a start
    that had never once worked. So this runs the command line the window builds and
    requires a real serve reply.
    """

    def test_the_serve_command_line_answers_a_request(self):
        import json
        import subprocess
        import sys
        source = guiscan.dashboard()
        start = source.index("private void StartLocked()")
        method = source[start:source.index("internal void Stop()", start)]
        self.assertIn('info.Arguments = "-c " + Bridge.Quote(code)', method,
                      "the persistent bridge must pass its code with -c, as the one-shot bridge does")
        code = "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', method[method.index("string code ="):
                                                               method.index(";", method.index('"sys.exit(')) + 1]))
        self.assertIn("controlcli import main", code)
        request = json.dumps({"id": 1, "command": "strings"}) + "\n"
        result = subprocess.run([sys.executable, "-c", code, str(ROOT / "src"), "serve"],
                                input=request, capture_output=True, text=True, encoding="utf-8",
                                timeout=60)
        replies = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        self.assertEqual(len(replies), 1, result.stderr)
        self.assertEqual(replies[0]["id"], 1)
        self.assertIs(replies[0]["reply"]["ok"], True)


class OneShotBridgeTests(unittest.TestCase):
    """The one-shot bridge never puts its argument on a command line.

    It answers whenever the long-lived process has failed, and it then carries every Custom
    message on the Settings page - for a Preview on each pause in typing, and for Save. A
    command line can be read by any process of the same user and is what process-creation
    auditing keeps, and it stops at 32767 characters. So the argument goes to stdin, and this
    runs the command line the window builds with an argument waiting there.
    """

    def setUp(self):
        source = guiscan.settings()
        start = source.index("internal Dictionary<string, object> Call(string command, string argument)")
        self.method = source[start:source.index("internal static string Quote(", start)]

    def test_the_argument_is_written_to_stdin_and_not_to_the_command_line(self):
        self.assertNotIn("Quote(argument)", self.method)
        self.assertIn('arguments.Append(" -")', self.method)
        self.assertIn("info.RedirectStandardInput = true", self.method)
        self.assertIn("new UTF8Encoding(false).GetBytes(argument)", self.method,
                      "a redirected stdin takes the console code page unless the bytes are UTF-8")
        self.assertIn("process.StandardInput.Close()", self.method)

    def test_the_command_line_it_builds_reads_its_argument_from_stdin(self):
        import json
        import subprocess
        import sys
        import tempfile
        code = "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', self.method[self.method.index("string code ="):
                                                               self.method.index(";", self.method.index('"sys.exit(')) + 1]))
        self.assertIn("controlcli import main", code)
        message = "Keep going — 계속 \U0001f9e9\nwith a second line"
        with tempfile.TemporaryDirectory() as home:
            # --home keeps this off the real installation; the rest is the window's own argv.
            result = subprocess.run([sys.executable, "-c", code, str(ROOT / "src"), "--home", home, "update", "-"],
                                    input=json.dumps({"custom_message": message}, ensure_ascii=False),
                                    capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        reply = json.loads(result.stdout)
        self.assertIs(reply["ok"], True)
        self.assertEqual(reply["settings"]["custom_message"], message)


class FooterTests(unittest.TestCase):
    """The strip along the bottom is as tall as what it holds.

    A user reported the three buttons losing their bottom borders. The cause was not the
    buttons: the strip's height was `MeasureText("Ag") + Px(46)`, a text measurement plus
    a constant, and the row of buttons needed six pixels more than that arithmetic left -
    the FlowLayoutPanel's default margin is 3px on every side and does not scale with the
    display. The strip came out two pixels short, the row was clipped to 46 of its 48
    pixels, and the last thing inside those two rows was every button's own bottom border.

    Measured from a layout dump of the running window at 150%: the strip was 94 tall with
    42 of padding, giving 52 to a grid whose preferred height was 54.

    Since v0.6.4 the strip is a ground holding the save bar card, and the card is the grid:
    the height is the card's content, the card's padding and the strip's padding, and it is
    measured again whenever the window's font changes.
    """

    def setUp(self):
        # By braces. This used to end at "the next `private void `" - a string that stops
        # appearing the day the method after it is a `private static void`, after which the
        # slice ran to the end of the file and every assertion below was made about the whole
        # window rather than about the footer.
        self.source = guiscan.settings()
        self.method = guiscan.member_body("SettingsForm", "BuildFooter")

    def test_the_height_is_measured_rather_than_derived_from_a_font(self):
        self.assertNotIn('MeasureText("Ag", Font).Height + Px(46)', self.method,
                         "a strip sized by a formula cannot know how tall an AutoSize "
                         "button becomes once the font is applied")
        self.assertIn("PreferredSize.Height", self.method,
                      "the strip must be sized from what it contains")
        self.assertIn("savebar.Padding.Vertical", self.method,
                      "and must add the padding of the card the buttons sit in")
        self.assertIn("footer.Padding.Vertical", self.method,
                      "and must add the padding it declares")
        self.assertIn("FontChanged += fit", self.method,
                      "a height measured once is wrong again after the font changes")

    def test_the_button_row_declares_its_margin(self):
        self.assertIn("row.Margin = new Padding(0)", self.method,
                      "the default 3px margin does not scale and is what went missing")

    def test_the_height_is_set_after_the_content_exists(self):
        add = self.method.index("footer.Controls.Add(savebar)")
        height = self.method.index("footer.Height =")
        self.assertLess(add, height,
                        "measuring before the children are added measures nothing")

    def test_the_reopen_note_is_measured_in_the_width_the_window_gives_it(self):
        """The card grows to hold the reopen note, and the width it measures the note in must be the
        one the note is about to get - worked out from the window's own width - not the width the card
        was last laid out at. Showing the note is what asks for the height, and a window just made
        narrower has not always laid the card out at its new width by then; measured at the card's old
        width the note was given two lines where it takes four, and the layout a taller card asks for
        from inside the layout that is running is dropped when that one ends. On CI's fonts that cut the
        note off in Spanish, German and French from 150% up (v0.6.4; LayoutAuditTests measures both
        orders now)."""
        start = self.source.index("private int NoteWidth(Control row)")
        width = self.source[start:self.source.index("\n        }\n", start)]
        self.assertIn("DisplayRectangle.Width", width,
                      "the note's room follows the window's width, which is never a layout behind")
        self.assertNotIn("savebar.ClientSize", width,
                         "the card's own width is the width it was last laid out at")
        self.assertIn("footer.PerformLayout();", self.method,
                      "a card left short by a layout that was already running is laid out again")
        self.assertIn("Resize += follow;", self.method,
                      "and that is asked for once the window's own layout is over")


class NumericInsetTests(unittest.TestCase):
    """The number in a Limits field is set in from the border, and by the border's rules.

    A NumericUpDown paints its value hard against its frame, which reads as a number
    pushed up against the box rather than placed inside it. WinForms offers no inner
    padding for the control, so the space comes from the native edit underneath, through
    the message an edit control has always had for this. Measured on the finished window
    at 150%: the digit sits 8-9 device pixels in, or 5.3-6.0 logical, against the
    ComboBox below it at 4.0.

    Two ways of getting this wrong are worth pinning, because both are silent. Hooking
    the *spinner's* `HandleCreated` looks right and does nothing - the spinner has a
    handle before its child does, and the message goes to a control that is not there
    yet, with no error. And padding the text with spaces would move the digit just as
    well while changing the string the control parses, which is a data change wearing a
    cosmetic one's clothes.
    """

    def setUp(self):
        self.source = guiscan.settings()
        self.method = guiscan.member_body("SettingsForm", "GiveTextRoom")

    def test_the_margin_goes_to_the_edit_control_underneath(self):
        self.assertIn("EM_SETMARGINS", self.method)
        self.assertIn("EC_LEFTMARGIN", self.method,
                      "only the left margin: the spinner buttons own the right edge")

    def test_it_waits_for_the_edit_to_have_a_handle_not_the_spinner(self):
        self.assertIn("edit.HandleCreated", self.method,
                      "the spinner has a handle before its child does, so hooking the "
                      "spinner sends the message into nothing and reports success")
        self.assertNotIn("spin.HandleCreated", self.method)

    def test_the_inset_scales_with_the_display(self):
        self.assertIn("Px(INSET)", self.method,
                      "a raw pixel count would shrink to nothing at 200%")
        declared = re.search(r"private const int INSET = (\d+);", self.source)
        self.assertIsNotNone(declared, "the inset should be named, not inlined")
        self.assertLessEqual(int(declared.group(1)), 6,
                             "past six logical pixels the number looks indented")

    def test_the_value_itself_is_never_touched(self):
        self.assertNotIn('" "', self.method,
                         "leading spaces would move the digit and change what Save writes")
        self.assertNotIn("TextAlign", self.method,
                         "the number stays left aligned; only the margin changed")

    def test_only_the_two_numeric_fields_ask_for_it(self):
        """Retry timing is a ComboBox and is deliberately left alone."""
        self.assertEqual(self.source.count("GiveTextRoom(spin)"), 1,
                         "one call site, on the NumericUpDown the two Limits rows share")
        # Every drop-down on the page is built by ChoiceCombo or LanguageCombo.
        for builder in ("private SoftCombo ChoiceCombo(", "private SoftCombo LanguageCombo("):
            start = self.source.index(builder)
            body = self.source[start:self.source.index("return combo;", start)]
            self.assertNotIn("GiveTextRoom", body, builder)


def card_room(scale: float) -> tuple:
    """How far, per side, the panel's card lift still changes the canvas by more than one
    colour level at `scale`, in CSS px: (left, top, right, bottom)."""
    canvas = brand.rgb(brand.LIGHT["canvas"])
    room = []
    for side in ("left", "top", "right", "bottom"):
        visible = 0
        for d in range(0, int(60 * scale)):
            colour = brand.elevation_colour("card", side, d + 0.5, "canvas", scale=scale)
            if max(abs(a - b) for a, b in zip(colour, canvas)) > 1.0:
                visible = d + 1
        room.append(visible / scale)
    return tuple(room)


def fullest_snapshot(now: float) -> dict:
    """A dashboard reply with the most the pages ever show, in the shape `controlcli dashboard`
    answers: the watcher running, two recoveries waiting - one for hours - and one running in Codex,
    each with the checks the watcher recorded, and four finished conversations with long names. A
    table measures a label at its column's width, and a long name used to wrap the Overview past the
    bottom of the window."""
    gates = {name: [machine.PASS, "ok"] for name in machine.GATES}
    gates["schedule"] = [machine.WAIT, "waiting_reset"]
    for name in ("thread_available", "no_newer_user_work", "usage"):
        gates[name] = [machine.UNKNOWN, "not_checked"]

    def pending(index, code, category, eligible, name):
        return {"interruption_id": ("%x" % index) * 64, "thread_id": "%08d-0000-7000-8000-000000000000" % index,
                "name": name, "state": code, "code": code, "category": category, "overlays": [],
                "eligible_at": eligible, "reset_at": eligible, "detected_at": now - 1500,
                "recovery_attempts": 2, "thread_enabled": True, "gates": gates, "gates_at": now - 40}

    def finished(index, code, category, name, hours):
        return {"interruption_id": ("%x" % index) * 64, "thread_id": "%08d-0000-7000-8000-000000000000" % index,
                "name": name, "state": code, "code": code, "category": category, "overlays": [],
                "eligible_at": None, "detected_at": now - hours * 3600 - 600, "outcome_at": now - hours * 3600,
                "recovery_attempts": 1, "thread_enabled": True}

    waiting = [pending(1, "waiting_reset", "usage_limit", now + 9 * 3600, "payments-api-retry-and-idempotency-review"),
               pending(2, "scheduled", "network_transient", now + 50 * 60, "migrate-the-docs-site-to-the-new-theme"),
               pending(3, "turn_running", "server_5xx", None, "flaky-integration-tests-in-the-sync-service")]
    history = [finished(4, "recovered", "usage_limit", "payments-api-retry-and-idempotency-review", 2),
               finished(5, "stopped_by_user", "network_transient", "migrate-the-docs-site-to-the-new-theme", 8),
               finished(6, "no_progress", "server_5xx", "flaky-integration-tests-in-the-sync-service", 26),
               finished(7, "submission_unknown", "stream_interrupted", "release-notes-and-changelog-for-the-next-version", 50)]
    return {"ok": True,
            "status": {"version": "0.6.4", "enabled": True, "watcher_running": True, "upgrade_pending": False,
                       "startup_enabled": True, "pending": len(waiting),
                       "watcher": {"running": True, "ticking": True, "engine_state": "verified", "last_tick_at": now}},
            "week": {"interruptions_detected": 128, "continuations_submitted": 117, "pending": len(waiting),
                     "outcomes": {"recovered": 96}, "success_rate": 0.82},
            "pending": waiting, "history": waiting + history,
            # Answered by the bridge's own `compatibility` command, not by `dashboard`: LayoutAudit hands it to the
            # Diagnostics page's card, so the card is measured at its fullest (fullest_compatibility).
            "compatibility": fullest_compatibility(now)}


def fullest_compatibility(now: float) -> dict:
    """A Compatibility Registry view, as the bridge's `compatibility` command answers, with the most the Diagnostics
    page's card shows: every part the registry offers, in each of its four states, a long engine version, refreshed
    data that has expired, and a watcher still acting on what it found when it started - every line the card adds."""
    from codex_auto_resume import compat
    capabilities = {}
    for index, (name, (checks, tier)) in enumerate(compat.CAPABILITIES.items()):
        state = ("VERIFIED", "COMPATIBLE", "INCOMPATIBLE", "UNKNOWN")[index % 4] if checks else "UNKNOWN"
        capabilities[name] = {"state": state, "source": "cache" if state in ("VERIFIED", "INCOMPATIBLE") else "local",
                              "tier": tier,
                              "reason": {"VERIFIED": "registry_verified", "COMPATIBLE": "local_checks_passed",
                                         "INCOMPATIBLE": "registry_incompatible",
                                         "UNKNOWN": "local_check_unavailable"}[state] if checks else "not_implemented"}
    return {"status": "ok", "overall": "incompatible", "acting": "structurally_compatible", "checked_at": now - 90,
            "live": False, "engine": {"found": True, "version": "codex-cli 0.155.0-alpha.123456789.987654321"},
            "data": {"bundled": "ok", "bundled_sequence": 1, "cache": "expired", "cache_sequence": 123456,
                     "cache_origin": "main", "fetched_at": now - 200 * 86400, "source": "cache", "expired": True},
            "checks": {name: "PASS" for name in compat.CHECKS}, "capabilities": capabilities}


def overview_states(now: float) -> list:
    """The replies `SettingsForm.OverviewStatesAudit` applies in turn, as [name, reply] pairs: first a watcher in
    trouble with recovery paused - the Overview is built from it, as a window opens on it - then the fullest reply, a
    stopped watcher, one whose state is unknown, nothing waiting with History unreadable, and Pending unreadable.
    These are the Right now card's widest words - "nicht unterstützt", "ne répond pas", "Reprendre la récupération" -
    and in v0.6.4 the Overview opened on them scrolled in German and French, where fullest_snapshot fitted."""
    fullest = fullest_snapshot(now)

    def watcher(enabled=True, running=True, ticking=True, engine="verified", ago=0.0):
        reply = copy.deepcopy(fullest)
        status = reply["status"]
        status["enabled"] = enabled
        # None is a watcher whose state could not be told, which the dashboard shows as unknown.
        status["watcher_running"] = running
        status["watcher"].update(running=bool(running), ticking=ticking, engine_state=engine,
                                 last_tick_at=0 if ago is None else now - ago)
        return reply

    idle = copy.deepcopy(fullest)
    idle["pending"] = []
    idle["status"]["pending"] = 0
    del idle["history"]
    idle["history_error"] = "database is locked"
    unreadable = copy.deepcopy(fullest)
    del unreadable["pending"]
    unreadable["pending_error"] = "database is locked"
    return [["a watcher in trouble, recovery paused", watcher(False, True, False, "incompatible", 59 * 60 + 30)],
            ["the fullest", fullest],
            ["a stopped watcher", watcher(True, False, True, "unknown", 3 * 86400)],
            ["a watcher in an unknown state", watcher(True, None, True, "structurally_compatible", None)],
            ["nothing waiting, History unreadable", idle],
            ["Pending unreadable", unreadable],
            ["a first installation", first_installation(now)]]


def first_installation(now: float) -> dict:
    """A dashboard reply as a first installation gives it: the watcher running, nothing waiting, nothing finished and
    an empty week. Recently finished holds one line, so the Overview's second row needs less than its first."""
    reply = fullest_snapshot(now)
    reply["status"]["pending"] = 0
    reply["week"] = {"interruptions_detected": 0, "continuations_submitted": 0, "pending": 0, "outcomes": {},
                     "success_rate": None}
    reply["pending"] = []
    reply["history"] = []
    return reply


def finished_while_open(snapshot: dict, now: float) -> dict:
    """The next read while the Overview is on screen: a recovery that has just finished, at the top of
    History, so Recently finished is rebuilt on a page that is already laid out."""
    later = copy.deepcopy(snapshot)
    fresh = copy.deepcopy(snapshot["history"][-1])
    fresh.update(interruption_id="8" * 64, thread_id="88888888-8888-7888-8888-888888888888",
                 name="a-conversation-that-finished-while-the-window-was-open", code="recovered", state="recovered",
                 outcome_at=now - 20 * 60, detected_at=now - 30 * 60)
    waiting = len(snapshot["pending"])
    later["history"] = snapshot["history"][:waiting] + [fresh] + snapshot["history"][waiting:]
    return later


class WindowCompositionTests(unittest.TestCase):
    """v0.6.4's window: v0.6.2's proportions, the panel's material, and the speed it lost."""

    def setUp(self):
        self.window = guiscan.settings()
        self.dashboard = guiscan.dashboard()

    @staticmethod
    def method(source, signature):
        start = source.index(signature)
        return source[start:source.index("\n        }\n", start)]

    def test_the_window_opens_at_a_size_the_overview_fits_and_does_not_grow(self):
        """1000 by 664 (v0.6.5): the Overview whole in every language at every scaling, each card a little
        taller than what it holds and the page's rhythm under the last row (LayoutAuditTests holds the page to
        it). With the buttons at the cards' bottom left, in rows of their own, the rows need a window of 624 to
        635 px; 664 is 626 - what they need at 100% - with the scale's medium step in every card and the page's
        gap under them. It is taller than a 1920 by 1080 screen at 150% has room for, where KeepOnScreen makes it
        as tall as the work area and the Overview still fits (LayoutAuditTests measures the shortest window)."""
        self.assertIn("ClientSize = new Size(Px(OpeningWidth), Px(OpeningHeight));", self.window)
        width = int(re.search(r"internal const int OpeningWidth = (\d+);", self.window).group(1))
        height = int(re.search(r"internal const int OpeningHeight = (\d+);", self.window).group(1))
        self.assertEqual((width, height), (1000, 664))
        # The work area of 1920 by 1080 at 150% with the taskbar (72 device pixels), and the frame Windows
        # 11 gives the window there, in device pixels: 22 across, 56 down (measured with GetWindowRect,
        # and AdjustWindowRectExForDpi at 144 DPI answers the same).
        self.assertLessEqual(round(width * 1.5) + 22, 1920)
        self.assertGreater(round(height * 1.5) + 56, 1080 - 72, "it fits there now; the reasoning above is out of date")
        self.assertIn("ClientSize = new Size(Math.Max(Px(340), Math.Min(ClientSize.Width, screen.Width - frameWidth)),",
                      self.method(self.window, "private void KeepOnScreen("), "a smaller screen makes the window smaller")
        self.assertIn("MinimumSize = new Size(Px(800), Px(420));", self.window)
        self.assertIn("KeepOnScreen();", self.window)
        self.assertNotIn("FitToContent", self.window + self.dashboard,
                         "growing to the tallest section laid everything out twice before the first paint")

    def test_nothing_in_the_window_is_see_through(self):
        """A see-through row asked its card to repaint its background - shadow and all - for
        every repaint of the row and of each label in it: 540 card backgrounds, 11 s, in one
        measured session of v0.6.3."""
        for name, source in (("[settings]", self.window), ("[dashboard]", self.dashboard)):
            with self.subTest(name):
                self.assertNotIn("Color.Transparent", source)

    def test_both_swaps_stop_painting_and_start_it_again_in_finally(self):
        redraw = self.method(self.window, "private static bool Redraw(")
        self.assertIn("WM_SETREDRAW", redraw)
        self.assertIn("RDW_INVALIDATE | RDW_ERASE | RDW_ALLCHILDREN | RDW_FRAME", redraw)
        self.assertIn("!control.Visible", redraw,
                      "turning painting back on makes a window visible, so a hidden one is left alone")
        for source, signature, host in ((self.dashboard, "private void ShowPage(", "pageHost"),
                                        (self.window, "private void ShowSection(", "sectionScroll")):
            body = self.method(source, signature)
            with self.subTest(signature):
                stop = body.index("bool paused = Redraw(%s, false);" % host)
                attempt = body.index("try", stop)
                finally_ = body.index("finally", attempt)
                self.assertIn("if (paused) Redraw(%s, true);" % host, body[finally_:])

    def test_a_swap_hides_and_shows_rather_than_removing_and_adding(self):
        """Removing a page moved every native control in it to the parking window and back."""
        for source, signature in ((self.dashboard, "private void ShowPage("),
                                  (self.window, "private void ShowSection(")):
            body = self.method(source, signature)
            with self.subTest(signature):
                self.assertNotIn("Controls.Clear()", body)
                self.assertIn(".Visible = true;", body)

    def test_a_page_switch_does_not_ask_again_for_a_snapshot_it_has_just_had(self):
        show = self.method(self.dashboard, "private void ShowPage(")
        self.assertRegex(show, r"snapshotAge\.ElapsedMilliseconds >= FreshMilliseconds\)\) RefreshNow\(\);")
        self.assertIn("private const int FreshMilliseconds = 2000;", self.dashboard)
        # The age of the read, so it starts again only when a read answers. A page built later is
        # handed the snapshot already held (PageFor), and that made an old one look new.
        self.assertRegex(self.method(self.dashboard, "private void Reread("),
                         r"if \(Ok\(reply\)\)\s*\{\s*snapshotAge\.Restart\(\);\s*ApplySnapshot\(reply\);")
        self.assertNotIn("snapshotAge", self.method(self.dashboard, "private void ApplySnapshot("))
        self.assertNotIn("snapshotAge", self.method(self.dashboard, "private Control PageFor("))

    def test_nothing_out_of_sight_keeps_a_state_it_was_told_to_drop(self):
        """Pages and sections stay parented and hidden, and `Visible` answers false for anything in
        one, whatever the control itself was told - as `Enabled` does under a disabled parent. A
        write skipped because the getter already agreed left the Custom card showing under the
        Standard style, and History's thread button beside a row it did not apply to."""
        for name, source in (("[settings]", self.window), ("[dashboard]", self.dashboard)):
            with self.subTest(name):
                self.assertNotRegex(source, r"\.(?:Visible|Enabled)\s*!=")

    def test_pages_and_settings_editors_are_built_when_they_are_needed(self):
        show = self.method(self.dashboard, "private void ShowPage(")
        self.assertLess(show.index("BuildPendingEditors();"), show.index("PageFor(name)"),
                        "Settings asked for before its editors were built must build them first")
        later = self.method(self.window, "private void BuildEditorsLater(")
        self.assertIn("Application.Idle += idle;", later)
        self.assertNotIn('pages["overview"] = BuildOverview();', self.dashboard)
        self.assertIn("if (snapshot != null) ApplySnapshot(snapshot);", self.method(self.dashboard, "private Control PageFor("))

    def test_fonts_are_not_made_on_every_switch(self):
        for source, signature in ((self.dashboard, "private void ShowPage("),
                                  (self.window, "private void ShowSection(")):
            with self.subTest(signature):
                body = self.method(source, signature)
                self.assertNotIn("new Font(", body)
                self.assertIn("Soft.RoleFont(", body)

    def test_a_scrolling_page_keeps_room_for_a_cards_lift(self):
        """A page that scrolls is the edge of every shadow on it, so the cards' lift must fit
        inside its padding, at every scaling, to within two colour levels of the canvas."""
        declared = re.search(r"private Padding CardRoom\(\)\s*\{\s*return Pad\((\d+), (\d+), (\d+), (\d+)\);", self.window)
        self.assertIsNotNone(declared)
        left, top, right, bottom = (int(value) for value in declared.groups())
        for scale in (1.0, 1.25, 1.5, 1.75, 2.0):
            need = card_room(scale)
            with self.subTest(scale=scale):
                self.assertGreaterEqual(left, need[0])
                self.assertGreaterEqual(top, need[1])
                self.assertGreaterEqual(right, need[2])
                self.assertGreaterEqual(bottom, need[3])
        self.assertIn("page.Padding = CardRoom();", self.method(self.dashboard, "private Panel Page("))
        controls = guiscan.controls()
        see_through = self.method(controls, "internal static bool SeeThrough(")
        self.assertIn("if (Scrolling(control)) return false;", see_through,
                      "a scrolled card must not leave its shadow outside the page")
        scrolling = self.method(controls, "internal static bool Scrolling(")
        self.assertIn("if (page != null) return page.Overflowing;", scrolling,
                      "the soft scroll bar is the page's own, so the page says when it shows")
        self.assertIn("scroller.VerticalScroll.Visible || scroller.HorizontalScroll.Visible", scrolling)
        self.assertIn("page.Scrolls = true;", self.method(self.dashboard, "private Panel Page("))

    def test_nothing_in_the_window_scrolls_on_windows_own_bar(self):
        """Every page, the Settings section page and the gate list scroll on the soft bar (SoftPage),
        and every list on its own clipped away behind it (SoftListHost)."""
        for name, source in (("[settings]", self.window), ("[dashboard]", self.dashboard)):
            with self.subTest(name):
                self.assertNotRegex(source, r"\.AutoScroll\s*=\s*true")
        self.assertIn("sectionScroll.Scrolls = true;", self.window)
        self.assertIn("private readonly SoftPage sectionScroll", self.window)
        self.assertIn("sectionScroll.ScrollTo(0, false);", self.method(self.window, "private void ShowSection("))
        self.assertNotIn("AutoScrollPosition", self.window + self.dashboard)
        self.assertIn("int width = page - SoftBar.Gutter;", self.method(self.window, "private void FitSections("))
        self.assertIn("new SoftListHost(list)", self.method(self.dashboard, "private Control ListCard("))
        self.assertIn("new SoftListHost(view)", self.method(self.dashboard, "private Form BuildTimeline("))
        wheel = self.method(self.window, "private static void IgnoreWheel(")
        self.assertIn("handled.Handled = true;", wheel, "the drop-down must not change under the wheel")
        self.assertIn("Soft.PassWheel(sender as Control, e.Delta);", wheel, "and the page must still scroll over it")

    def test_why_it_is_waiting_scrolls_inside_its_card_and_never_the_page(self):
        pending = self.method(self.dashboard, "private Control BuildPending(")
        explain = pending[pending.index('MakeCard(S("explain.title"'):pending.index("var split = new SoftStack();")]
        self.assertIn("explain.Dock = DockStyle.Fill;", explain, "as tall as the list's card in the same row")
        self.assertIn("explain.AutoSize = false;", explain)
        self.assertIn("gates.Scrolls = true;", explain)
        self.assertIn("explainList.Dock = DockStyle.Top;", explain, "the checks are as tall as they are, inside the scroller")
        self.assertIn("explain.RowStyles.Add(new RowStyle(SizeType.Percent, 100f));", explain,
                      "the scroller takes what the heading and the time leave")
        controls = guiscan.controls()
        measure = self.method(controls, "private int Measure(")
        self.assertIn("else if (child.Dock == DockStyle.Fill) stacked += Math.Max(0, child.MinimumSize.Height);", measure,
                      "a filling child - the list and the explanation - counts at its minimum, so it gives way")

    def test_the_overview_leads_to_each_cards_button_from_its_bottom_left(self):
        """v0.6.5, as the person asked: the first screen's buttons at the bottom LEFT of their cards, as v0.6.2 had
        them - a card's heading at the top left, what it holds under it, and the button it leads to in a row of its
        own under the last line, the scale's medium step clear of it, at the bottom of whatever height the card is
        given. It replaces v0.6.4's button pinned to the bottom right beside the last lines (SoftPin). LayoutAuditTests
        holds every button to its corner, over no text and clear of it, in every language at every scaling."""
        overview = self.method(self.dashboard, "private Control BuildOverview(")
        self.assertEqual(overview.count("Lead("), 4, "every Overview card has the same gap under its heading, so their facts line up")
        self.assertNotIn("PinTo(", self.dashboard)
        self.assertNotIn("SoftPin", self.dashboard.replace("(SoftPin)", ""), "nothing on the Overview is pinned to the right any more")
        self.assertIn("Lead(now, toggleButton);", overview)
        self.assertIn("Lead(week, null);", overview)
        lead = self.method(self.dashboard, "private void Lead(")
        self.assertIn("heading.Margin = Pad(0, 0, 0, Brand.CardFirstGap);", lead)
        self.assertIn("button.Anchor = AnchorStyles.Left | AnchorStyles.Bottom;", lead)
        self.assertIn("button.Margin = Pad(0, LeadGap, 0, 0);", lead)
        self.assertLess(lead.index("card.Controls.Add(button);"), lead.index("card.RowStyles.Add(new RowStyle(SizeType.Percent, 100f));"),
                        "the button's row takes what the card has past its content, and the button stands at its bottom")
        self.assertIn("card.RowStyles.Add(new RowStyle(SizeType.AutoSize));", lead, "what the card holds stays at its top")
        self.assertIn("led[button] = card;", lead, "LayoutAudit holds the button to its card's bottom-left corner")
        self.assertIn("internal const int LeadGap = Brand.SpaceM;", self.dashboard,
                      "the scale's medium step: SpaceL made the Overview taller than a 1920 by 1080 screen at 150%")
        self.assertNotIn("card.Padding", lead, "the Overview's cards keep the padding every card has (brand card_pad)")
        facts = self.method(self.dashboard, "private TableLayoutPanel Facts(")
        self.assertIn("grid.Margin = new Padding(0);", facts, "the default 3 px margin never scaled")
        self.assertIn("var grid = new SoftStack();", facts, "a ground, so a button's lift is drawn on it")
        recent = self.method(self.dashboard, "private void FillRecent(")
        self.assertIn("new LineLabel()", recent, "a long conversation name wrapped the Overview past the window")

    def test_the_overviews_rows_hold_their_cards_and_keep_the_pages_rhythm_under_them(self):
        """v0.6.5, as the person asked: white space is part of the design. v0.6.4 stretched the Overview's cards down
        the whole page, and what they held floated at their tops. Now the rows are alike - each as tall as the tallest
        needs and a little more, never more than comfort allows - and under the last row the page keeps its own
        padding, the mirror of the padding over the first row, as every page keeps under its last card: the review
        found the Overview's gap above the footer 41 px where Pending's and History's is 27, and 87 on a first
        installation, whose short second row was left short over a band (OverviewHeights, whose cases
        LayoutAuditTests runs). What a taller window has past comfort stays as space under the rows. Every spacing is a
        step of brand's scale."""
        overview = self.method(self.dashboard, "private Control BuildOverview(")
        self.assertIn("var grid = new SoftStack();", overview)
        self.assertNotIn("new SoftRows(", overview, "rows that share the whole page are what left the cards emptier than their content")
        self.assertIn("grid.RowStyles.Add(new RowStyle(SizeType.Absolute, 0f));", overview)
        self.assertIn("grid.RowStyles.Add(new RowStyle(SizeType.Percent, 100f));", overview, "a row of space under the cards")
        self.assertIn("grid.AutoSize = true;", overview,
                      "a table that does not size itself tells its page nothing, and a card that grew would not scroll it")
        self.assertIn("page.Layout += delegate { FitOverview(scroller, grid); };", overview,
                      "fitted before the page lays the grid out, every time it does")
        for margin in ("now.Margin = RowGap(0, 0);", "waiting.Margin = RowGap(1, 0);",
                       "week.Margin = RowGap(0, 1);", "recent.Margin = RowGap(1, 1);"):
            with self.subTest(margin):
                self.assertIn(margin, overview)
        fit = self.method(self.dashboard, "private void FitOverview(")
        self.assertIn("OverviewHeights(needs, room, rest, Px(OverviewComfort))", fit)
        self.assertIn("int room = page.ClientSize.Height - page.Padding.Top;", fit)
        self.assertIn("int rest = page.Padding.Bottom;", fit, "under the last row, the page's own padding, as on every page")
        self.assertIn("grid.MinimumSize = new Size(0, total);", fit, "the page counts the rows at what they need, and scrolls past that")
        self.assertIn("grid.SuspendLayout();", fit)
        self.assertIn("grid.ResumeLayout(true);", fit, "one layout of the grid for every row that changed")
        self.assertNotIn("OverviewRest", self.dashboard + self.window,
                         "no space of its own under the rows, past the padding every page keeps under its last card")
        self.assertIn("internal const int OverviewComfort = Brand.SpaceXl;", self.dashboard)
        controls = guiscan.controls()
        measure = self.method(controls, "private int Measure(")
        self.assertIn("else if (child.Dock == DockStyle.Fill) stacked += Math.Max(0, child.MinimumSize.Height);", measure,
                      "the page counts a grid that fills it at its MinimumSize")
        audit = self.method(self.window, "private void AuditRows(")
        self.assertIn("leaves only", audit)
        self.assertIn("leaves an empty band", audit)
        self.assertIn("floats", audit)
        self.assertIn("page.ClientSize.Height - page.Padding.Bottom - bottom", audit)
        self.assertIn("form.AuditRows(page, true, findings);", self.window)
        self.assertIn("form.AuditNames(page, findings);", self.window)
        self.assertIn('if (page == "overview") form.AuditShortest(findings);', self.window)
        state = self.method(self.window, "private void AuditState(")
        self.assertIn("AuditRows(where, true, findings);", state)
        self.assertIn("AuditNames(where, findings);", state)
        self.assertIn("AuditLead(where, pair.Key, pair.Value, Px(LeadGap), findings);", state)

    def test_the_lists_columns_share_the_lists_width(self):
        """v0.6.5 (the person, with a screenshot): a white native horizontal bar under the Pending list, on a dark card.
        The columns had their headings whole whatever the list's width. Now, as the list narrows, what gives way in turn
        is a conversation's name past its heading, the cells past a readable width, the headings past what their columns
        hold (the widest first), and last the cells, down to the least a column can show - each ending in an ellipsis -
        and the last column fills what the others leave (ColumnFloors), in Pending, History and the Timeline dialog
        alike. LayoutAuditTests holds every list to its width at the opening size, with rows and without, and at the
        window's narrowest; tests/test_gui_v065_window.py holds the order to its cases and to the review's German list."""
        fit = self.method(self.dashboard, "private void FitColumns(")
        self.assertIn("int[] floor = ColumnFloors(heading, cells, least, Px(ReadableCells), available);", fit)
        self.assertIn("int width = i == weights.Length - 1 ? Math.Max(floor[i], available - used)", fit, "the last column fills")
        floors = self.method(self.dashboard, "internal static int[] ColumnFloors(")
        self.assertIn("int need = Math.Max(least[i], i == 0 ? Math.Min(cell, heading[0]) : cell);", floors,
                      "a conversation's name holds only as much as its heading, past which it gives way first")
        self.assertIn("hold[i] = Math.Max(least[i], Math.Min(need, readable));", floors)
        self.assertIn("keep[i] = Math.Max(heading[i], hold[i]);", floors, "every heading whole before any gives way")
        capped = self.method(self.dashboard, "private static int Capped(")
        self.assertIn("Math.Max(hold[i], Math.Min(keep[i], cap))", capped,
                      "the headings give way first, the widest first, never below what the column holds")
        self.assertIn("Math.Max(least[i], Math.Min(hold[i], cap))", capped, "then the widest cells, never below the least")
        least = self.method(self.dashboard, "private int LeastWidth(")
        self.assertIn("Px(Brand.SwitchWidth + 2) + Px(14)", least, "the Auto-resume switch is never cut")
        measure = self.method(self.dashboard, "private void MeasureCells(")
        self.assertIn("CountdownText(item.Tag as Dictionary<string, object>, Now())", measure,
                      "the countdown measured as the clock writes it, not as the last tick left it")
        for draw in ("private void DrawHeader(", "private void DrawCell("):
            with self.subTest(draw):
                self.assertIn("TextFormatFlags.EndEllipsis", self.method(self.dashboard, draw))
        self.assertIn("MeasureCells(view);", self.method(self.dashboard, "private Form BuildTimeline("))
        self.assertIn("MeasureCells(list);", self.method(self.dashboard, "private void ShowUnreadableList("),
                      "a list emptied because it cannot be read keeps no room for cells it no longer has")
        self.assertIn('form.AuditLists(page + " with no rows", findings);', self.window)
        self.assertIn("form.AuditTimeline(snapshot, findings);", self.window)

    def test_a_page_shows_its_bar_by_what_fits_without_it_and_not_by_what_showed_before(self):
        controls = guiscan.controls()
        page = controls[controls.index("internal sealed class SoftPage"):controls.index("internal interface ISoftScroller")]
        layout = self.method(page, "protected override void OnLayout(")
        self.assertLess(layout.index("if (scrolls && !moving) overflow = false;"), layout.index("base.OnLayout(levent);"),
                        "laid out without the gutter first: kept from the last layout, it kept German's Overview scrolling")
        move = self.method(page, "private void MoveTo(")
        self.assertIn("moving = true;", move, "scrolling moves what the page holds and lays nothing out twice")
        self.assertIn("finally { moving = false; }", move)

    def test_every_button_at_the_right_of_a_card_or_row_is_pinned_to_its_bottom_right(self):
        """The header's Start button and the Clear buttons under the Custom messages are at the right of a card
        and of a row, and are held to the bottom of it as the Overview's are."""
        header = self.method(self.window, "private void BuildHeader(")
        self.assertIn("startButton.Anchor = AnchorStyles.Right | AnchorStyles.Bottom;", header)
        self.assertIn("Pinned(startButton, hero);", header)
        footer = self.method(self.window, "private Control TextFooter(")
        self.assertIn("clear.Anchor = AnchorStyles.Right | AnchorStyles.Bottom;", footer)
        self.assertIn("Pinned(clear, row);", footer)
        self.assertIn("ForgetPins();", self.method(self.window, "private void BuildEditors("),
                      "rows built again after Restore defaults leave nothing pinned behind")

    def test_recently_finished_fits_its_names_after_every_outcome_and_age_is_written(self):
        """What each outcome says, age and all, decides what the names are left. Fitted inside the
        rebuild, before the ages were written, rows rebuilt on a laid-out Overview cut every outcome
        (LayoutAuditTests measures it)."""
        recent = self.method(self.dashboard, "private void FillRecent(")
        self.assertEqual(recent.count("FitRecentNames();"), 1)
        fit = recent.index("FitRecentNames();")
        rebuild = recent.index("if (key != recentShown)")
        rebuilt = recent.index("\n            }\n", rebuild)
        self.assertGreater(fit, recent.index('Ago(Number(row, "outcome_at"))'),
                           "the names are fitted before the ages are written")
        self.assertGreater(fit, rebuilt, "the names are fitted only when the rows are rebuilt")
        self.assertLess(recent.index("recentGrid.SuspendLayout();"), rebuild)
        self.assertLess(fit, recent.index("recentGrid.ResumeLayout(true);"),
                        "the writes and the fit are one layout, not one per label")

    def test_a_stopped_watcher_is_grey_before_there_is_a_snapshot_too(self):
        """Since v0.6.10 the dot is set with the words beside it (Hero), from the status alone until there is a
        snapshot, and its light is grey for a watcher not known to be running (HeaderLight) - the compiled rule is
        tests/test_light_parity.py's; this holds the path to it. The light reads the rows too: one held for a
        watcher not running (engine_unavailable) is a stopped watcher's grey, whatever the status said."""
        status = self.method(self.window, "private void ApplyStatus(")
        self.assertRegex(status, r'heroStatus = snapshot != null && ReferenceEquals\(status, Map\(snapshot, "status"\)\) '
                                 r'\? null : status;\s+if \(heroStatus != null\) Hero\(status, null, Now\(\)\);')
        self.assertNotIn('"attention"', status)
        hero = self.method(self.window, "private void Hero(")
        self.assertIn("stateDot.State = HeaderLight(status, pending, word);", hero)
        # What "known to be running" is lives in one place (KnownRunning), which the headline reads as well, so a
        # grey light never stands over "Watching for interruptions".
        light = self.method(self.dashboard, "internal static string HeaderLight(")
        self.assertIn('return KnownRunning(status, pending) ? word : "idle";', light)
        known = self.method(self.dashboard, "internal static bool KnownRunning(")
        self.assertIn('if (!Equals(Get(status, "watcher_running"), true)) return false;', known)
        self.assertIn('if (row != null && HasOverlay(row, "engine_unavailable")) return false;', known)
        self.assertIn("if (!KnownRunning(status, pending)) return Said(strings, \"status.not_running\"",
                      self.method(self.dashboard, "internal static string Headline("))

    def test_the_strings_cache_is_checked_before_it_is_used(self):
        constructor = self.window[self.window.index("private SettingsForm(PersistentBridge bridge, Dictionary<string, object> catalog"):]
        constructor = constructor[:constructor.index("\n        }\n")]
        self.assertLess(constructor.index("StringsCache.Key(root)"), constructor.index("StringsCache.Read(root, cacheKey)"))
        self.assertLess(constructor.index("Task.Factory.StartNew"), constructor.index("Font = windowFont ?? SystemFonts.MessageBoxFont;"),
                        "the strings are asked for while the fonts and the icon are made")
        read = self.method(self.window, "internal static Dictionary<string, object> Read(")
        self.assertIn("(string)stored != key) return null;", read)
        key = self.method(self.window, "internal static string Key(")
        for part in ('"|window "', 'PreferencePart', '"|windows "', '"locales"', '"CODEX_AUTO_RESUME_LANG"'):
            with self.subTest(part):
                self.assertIn(part, key)
        # v0.6.9: the settings file's own digest is not in the key. The only thing in that file these
        # words depend on is the Interface language, which is in it by name, and keying on the whole
        # file made every save of anything - a theme, a limit - open the next window cold.
        self.assertNotIn("sha.ComputeHash(stored)", key)

    def test_the_strings_cache_is_kept_in_config(self):
        """Uninstall -Purge removes config\\, and the product writes only its own config\\ and logs\\."""
        cache = self.window[self.window.index("internal static class StringsCache"):]
        cache = cache[:cache.index("\n    }\n")]
        self.assertIn('Path.Combine(Path.Combine(root, "config"), "strings-cache.json")',
                      self.method(cache, "private static string PathIn("))
        self.assertNotIn('"cache"', cache)

    def test_the_strings_cache_is_written_under_a_short_name(self):
        """.NET Framework refuses a path of 260 characters. With a GUID in the temporary file's
        name, an installation in a deep folder failed every write - silently, because a failed
        write is only a miss - and the window never once opened from its cache (measured)."""
        write = self.method(self.window, "internal static void Write(string root, string key,")
        self.assertNotIn("Guid", write)
        self.assertIn("Process.GetCurrentProcess().Id", write)


PROBE = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
# As the window's own Main does before its first control. Without it every label measured its text
# with GDI+, 5 px a line taller at 150% than the window draws it, and the Overview measured 687 px
# of window where a capture of the real one showed 646 (v0.6.4).
[Windows.Forms.Application]::EnableVisualStyles()
[Windows.Forms.Application]::SetCompatibleTextRenderingDefault($false)
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$static = [Reflection.BindingFlags]'Static,NonPublic,Public'
$form = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
$audit = $form.GetMethod('LayoutAudit', $static)
if (-not $audit) { throw 'SettingsForm has no LayoutAudit' }
$work = [string]$env:CAR_WORK
$utf8 = New-Object Text.UTF8Encoding $false
$schema = [IO.File]::ReadAllText((Join-Path $work 'schema.json'), $utf8)
$current = [IO.File]::ReadAllText((Join-Path $work 'settings.json'), $utf8)
# The most the pages ever show (fullest_snapshot).
$snapshot = [IO.File]::ReadAllText((Join-Path $work 'snapshot.json'), $utf8)
$out = @{ audit = @{}; pins = @{}; lists = @{}; notes = @{}; shortest = @{}; hero = @{}; canary = ''; cramped = ''; cache = @{} }
$auditedPins = $form.GetField('AuditedPins', $static)
$auditedHero = $form.GetField('AuditedHero', $static)
$auditedLists = $form.GetField('AuditedLists', $static)
$auditedNotes = $form.GetField('AuditedNotes', $static)
$auditedShortest = @('AuditedShortest', 'AuditedAlike', 'AuditedWraps' | ForEach-Object { $form.GetField($_, $static) })
foreach ($locale in (ConvertFrom-Json $env:CAR_LOCALES)) {
    $catalog = [IO.File]::ReadAllText((Join-Path $work ('strings-' + $locale + '.json')), $utf8)
    $out.audit[$locale] = @{}
    $out.pins[$locale] = @{}
    $out.lists[$locale] = @{}
    $out.notes[$locale] = @{}
    $out.shortest[$locale] = @{}
    $out.hero[$locale] = @{}
    foreach ($scale in (ConvertFrom-Json $env:CAR_SCALES)) {
        $key = ([double]$scale).ToString('0.00', [Globalization.CultureInfo]::InvariantCulture)
        $out.audit[$locale][$key] = [string]$audit.Invoke($null, [object[]]@($schema, $current, $catalog, $snapshot, [double]$scale))
        $out.pins[$locale][$key] = [int]$auditedPins.GetValue($null)
        $out.lists[$locale][$key] = if ($null -eq $auditedLists) { -1 } else { [int]$auditedLists.GetValue($null) }
        $out.notes[$locale][$key] = if ($null -eq $auditedNotes) { -1 } else { [int]$auditedNotes.GetValue($null) }
        $out.shortest[$locale][$key] = @($auditedShortest | ForEach-Object { if ($null -eq $_) { -1 } else { [int]$_.GetValue($null) } })
        $out.hero[$locale][$key] = if ($null -eq $auditedHero) { -1 } else { [int]$auditedHero.GetValue($null) }
    }
}
# How tall the Overview's rows are (SettingsForm.OverviewHeights), for the rows' needs, the room, the rhythm and comfort.
$heightsOf = $form.GetMethod('OverviewHeights', $static)
$out.heights = @()
foreach ($case in (ConvertFrom-Json ([IO.File]::ReadAllText((Join-Path $work 'heights.json'), $utf8)))) {
    if ($null -eq $heightsOf) { $out.heights += ,'SettingsForm has no OverviewHeights'; continue }
    $given = $heightsOf.Invoke($null, [object[]]@([int[]]@($case[0] | ForEach-Object { [int]$_ }), [int]$case[1], [int]$case[2], [int]$case[3]))
    $out.heights += ,@($given | ForEach-Object { [int]$_ })
}
# The Overview as the watcher's state changes under it (overview_states), opened on a watcher in trouble.
$statesAudit = $form.GetMethod('OverviewStatesAudit', $static)
$auditedStates = $form.GetField('AuditedStates', $static)
$states = [IO.File]::ReadAllText((Join-Path $work 'states.json'), $utf8)
$out.states = @{}
$out.statesAudited = @{}
foreach ($locale in (ConvertFrom-Json $env:CAR_LOCALES)) {
    $catalog = [IO.File]::ReadAllText((Join-Path $work ('strings-' + $locale + '.json')), $utf8)
    $out.states[$locale] = @{}
    $out.statesAudited[$locale] = @{}
    foreach ($scale in (ConvertFrom-Json $env:CAR_SCALES)) {
        $key = ([double]$scale).ToString('0.00', [Globalization.CultureInfo]::InvariantCulture)
        $out.states[$locale][$key] = [string]$statesAudit.Invoke($null, [object[]]@($catalog, $states, [double]$scale))
        $out.statesAudited[$locale][$key] = [int]$auditedStates.GetValue($null)
    }
}
# An engine state the window has no word for, as long as a paragraph: Right now cannot be planned for it, so a quiet
# report on the states is the audit measuring.
$english = [IO.File]::ReadAllText((Join-Path $work 'strings-en.json'), $utf8)
$out.statesCanary = [string]$statesAudit.Invoke($null, [object[]]@($english, [IO.File]::ReadAllText((Join-Path $work 'states-canary.json'), $utf8), [double]1.0))
# An engine state one line longer than any the window has a word for: Right now needs a line more, and the page does
# not scroll - so the move shows in the height it needs.
$out.statesLineCanary = [string]$statesAudit.Invoke($null, [object[]]@($english, [IO.File]::ReadAllText((Join-Path $work 'states-line-canary.json'), $utf8), [double]1.0))
# A button that is neither in its card's corner nor clear of the card's text, so a quiet report on pins is the
# audit measuring them.
$pinCard = New-Object Windows.Forms.Panel
$pinCard.Padding = New-Object Windows.Forms.Padding 10
$pinCard.Size = New-Object Drawing.Size 300, 120
$covered = New-Object Windows.Forms.Label
$covered.AutoSize = $false
$covered.Text = 'covered'
$covered.Bounds = New-Object Drawing.Rectangle 10, 60, 280, 20
$stray = New-Object Windows.Forms.Button
$stray.Text = 'stray'
$stray.Bounds = New-Object Drawing.Rectangle 20, 50, 120, 34
$pinCard.Controls.Add($covered)
$pinCard.Controls.Add($stray)
$pinFindings = New-Object 'System.Collections.Generic.List[string]'
$null = $form.GetMethod('AuditPin', $static).Invoke($null, [object[]]@('canary', $stray.PSObject.BaseObject, $pinCard.PSObject.BaseObject, $pinFindings.PSObject.BaseObject))
$out.pinCanary = ($pinFindings -join "`n")
# The same button held to the bottom LEFT, as an Overview card's is (AuditLead), and a line of text just above a button
# that is in its corner, so a quiet report on the Overview's buttons is the audit measuring them.
$leadFindings = New-Object 'System.Collections.Generic.List[string]'
$null = $form.GetMethod('AuditLead', $static).Invoke($null, [object[]]@('canary', $stray.PSObject.BaseObject, $pinCard.PSObject.BaseObject, [int]12, $leadFindings.PSObject.BaseObject))
$crowd = New-Object Windows.Forms.Panel
$crowd.Padding = New-Object Windows.Forms.Padding 10
$crowd.Size = New-Object Drawing.Size 300, 120
$above = New-Object Windows.Forms.Label
$above.AutoSize = $false
$above.Text = 'above'
$above.Bounds = New-Object Drawing.Rectangle 10, 62, 280, 14
$cornered = New-Object Windows.Forms.Button
$cornered.Text = 'cornered'
$cornered.Bounds = New-Object Drawing.Rectangle 10, 76, 120, 34
$crowd.Controls.Add($above)
$crowd.Controls.Add($cornered)
$null = $form.GetMethod('AuditLead', $static).Invoke($null, [object[]]@('crowded', $cornered.PSObject.BaseObject, $crowd.PSObject.BaseObject, [int]12, $leadFindings.PSObject.BaseObject))
$out.leadCanary = ($leadFindings -join "`n")
# A list whose columns are wider than it is (AuditList), so a quiet report on the lists is the audit measuring them.
$wide = New-Object Windows.Forms.ListView
$wide.View = [Windows.Forms.View]::Details
$wide.Size = New-Object Drawing.Size 300, 120
$null = $wide.Columns.Add('one', 200)
$null = $wide.Columns.Add('two', 200)
$listFindings = New-Object 'System.Collections.Generic.List[string]'
$null = $form.GetMethod('AuditList', $static).Invoke($null, [object[]]@('canary', $wide.PSObject.BaseObject, $listFindings.PSObject.BaseObject))
$out.listCanary = ($listFindings -join "`n")
# A label that cannot fit, so an empty report means the audit looked rather than that it saw nothing.
$canary = [IO.File]::ReadAllText((Join-Path $work 'strings-canary.json'), $utf8)
$out.canary = [string]$audit.Invoke($null, [object[]]@($schema, $current, $canary, $snapshot, [double]1.0))
# An Overview that cannot fit - a waiting count as tall as a paragraph - so a quiet report on scrolling is
# the audit measuring, not the page never being asked.
$cramped = [IO.File]::ReadAllText((Join-Path $work 'strings-cramped.json'), $utf8)
$out.cramped = [string]$audit.Invoke($null, [object[]]@($schema, $current, $cramped, $snapshot, [double]1.0))

# The strings cache, in an installation laid out as the real one is.
$cache = $assembly.GetType('CodexAutoResume.StringsCache', $true)
$json = $assembly.GetType('CodexAutoResume.Json', $true)
$keyOf = $cache.GetMethod('Key', $static)
$read = $cache.GetMethod('Read', $static)
$write = $cache.GetMethod('Write', $static)
$parse = $json.GetMethod('Parse', $static)
$escape = $json.GetMethod('Escape', $static)
$root = [string](Join-Path $work 'install')
$config = Join-Path $root 'config'
$settingsFile = Join-Path $config 'settings.json'
$cacheFile = Join-Path $config 'strings-cache.json'
function Get-CacheKey { return [string]$keyOf.Invoke($null, [object[]]@($root)) }
function Read-Cache([string]$key) { return $read.Invoke($null, [object[]]@($root, $key)) }
function Write-Cache([string]$key, $reply) { $null = $write.Invoke($null, [object[]]@($root, $key, $reply)) }
# The English reply as a bridge gives it for a stored Interface language of `system`, and of `ko`:
# parsed from text, so every value in it is what the window's own reader makes.
$englishText = [IO.File]::ReadAllText((Join-Path $work 'strings-en.json'), $utf8)
$systemText = $englishText.Replace('"preference": "en"', '"preference": "system"')
$koreanText = $englishText.Replace('"preference": "en"', '"preference": "ko"')
$original = [IO.File]::ReadAllBytes($settingsFile)
$reply = $parse.Invoke($null, [object[]]@($systemText))
$out.cache.replyNamesItsLanguage = ([string]$reply['preference'] -eq 'system')
$first = Get-CacheKey
$out.cache.missBeforeWrite = ($null -eq (Read-Cache $first))
Write-Cache $first $reply
$back = Read-Cache $first
$out.cache.hit = ($null -ne $back)
$out.cache.sameWords = ($null -ne $back) -and ($back['strings'].Count -eq $reply['strings'].Count)
$out.cache.sameKeyAgain = ($first -eq (Get-CacheKey))
$out.cache.inConfig = [IO.File]::Exists($cacheFile)
$out.cache.noCacheFolder = -not [IO.Directory]::Exists((Join-Path $root 'cache'))
$out.cache.configHolds = ((Get-ChildItem -LiteralPath $config -Force | ForEach-Object { $_.Name } | Sort-Object) -join ',')
[IO.File]::WriteAllText($settingsFile, '{"interface_language": "ko"}', $utf8)
$saved = Get-CacheKey
$out.cache.settingsChangeKey = ($saved -ne $first)
$out.cache.missAfterSave = ($null -eq (Read-Cache $saved))
[IO.File]::WriteAllBytes($settingsFile, $original)

# A reply in a language other than the one the settings store is neither kept nor used.
$korean = $parse.Invoke($null, [object[]]@($koreanText))
Write-Cache $first $korean
$kept = Read-Cache $first
$out.cache.otherLanguageNotWritten = ($null -ne $kept) -and ([string]$kept['preference'] -eq 'system')
[IO.File]::WriteAllText($cacheFile, '{"key": ' + [string]$escape.Invoke($null, [object[]]@($first)) + ', "reply": ' + $koreanText + '}', $utf8)
$out.cache.otherLanguageNotRead = ($null -eq (Read-Cache $first))
# No Interface language stored, or no settings file at all, is `system`, as the bridge takes it.
[IO.File]::WriteAllText($settingsFile, '{"theme": "light"}', $utf8)
$unset = Get-CacheKey
Write-Cache $unset $reply
$out.cache.unsetIsSystem = ($null -ne (Read-Cache $unset))
[IO.File]::Delete($settingsFile)
$absent = Get-CacheKey
Write-Cache $absent $reply
$out.cache.absentIsSystem = ($null -ne (Read-Cache $absent))

# The race a window that is opening can lose: its key is taken, another writer saves a new
# language before the bridge reads the settings, and the reply comes back in that language.
# Then the language is set back, and the file is byte for byte what the key was taken of.
[IO.File]::WriteAllBytes($settingsFile, $original)
[IO.File]::Delete($cacheFile)
$opening = Get-CacheKey
[IO.File]::WriteAllText($settingsFile, '{"interface_language": "ko"}', $utf8)
Write-Cache $opening $korean
[IO.File]::WriteAllBytes($settingsFile, $original)
$out.cache.raceKeyBack = ($opening -eq (Get-CacheKey))
$out.cache.raceNotKept = ($null -eq (Read-Cache $opening))
# A save that leaves the Interface language where it was - a theme, a limit, anything else - keeps
# the key, so the cache written under it is still this installation's words (v0.6.9: the key used to
# hold the whole settings file's digest, so every save of anything opened the next window cold).
[IO.File]::WriteAllText($settingsFile, '{"interface_language": "system", "theme": "light"}', $utf8)
$out.cache.otherSettingKeepsKey = ($opening -eq (Get-CacheKey))
Write-Cache $opening $reply
$out.cache.otherSettingKeepsCache = ($null -ne (Read-Cache $opening))
[IO.File]::WriteAllBytes($settingsFile, $original)

# A catalog corrected to a word of the same length, with its time put back: a release archive
# gives every file the same fixed time, so an installed file's time says nothing.
$now = Get-CacheKey
$catalogFile = Join-Path $root 'app\src\codex_auto_resume\locales\en.json'
$length = (New-Object IO.FileInfo $catalogFile).Length
$time = [IO.File]::GetLastWriteTimeUtc($catalogFile)
[IO.File]::WriteAllText($catalogFile, '{"a": "c"}', $utf8)
[IO.File]::SetLastWriteTimeUtc($catalogFile, $time)
$out.cache.catalogEditKeptLengthAndTime = ((New-Object IO.FileInfo $catalogFile).Length -eq $length) -and ([IO.File]::GetLastWriteTimeUtc($catalogFile) -eq $time)
$out.cache.catalogChangeKey = ($now -ne (Get-CacheKey))
$env:CODEX_AUTO_RESUME_LANG = 'de'
$languageKey = Get-CacheKey
$env:CODEX_AUTO_RESUME_LANG = $null
$out.cache.languageChangeKey = ($languageKey -ne (Get-CacheKey))
$now = Get-CacheKey
Write-Cache $now $reply
$out.cache.hitBeforeDamage = ($null -ne (Read-Cache $now))
[IO.File]::WriteAllText($cacheFile, '{"key": ', $utf8)
$out.cache.missWhenDamaged = ($null -eq (Read-Cache $now))

# The window itself, built and never shown, with a bridge rooted where nothing is.
$instance = [Reflection.BindingFlags]'Instance,NonPublic,Public'
$ownState = [Windows.Forms.Control].GetMethod('GetState', $instance)
# What a control itself was told, whatever its parents are; `Visible` is false inside a hidden page.
function Test-Own($control) { return [bool]$ownState.Invoke($control, [object[]]@(2)) }
function Get-Field($target, [string]$name) { return $form.GetField($name, $instance).GetValue($target) }
function Invoke-Window($target, [string]$name, [object[]]$arguments) {
    $method = @($form.GetMethods($instance) | Where-Object { $_.Name -eq $name -and $_.GetParameters().Count -eq $arguments.Count })[0]
    $null = $method.Invoke($target, $arguments)
}
$english = $parse.Invoke($null, [object[]]@([IO.File]::ReadAllText((Join-Path $work 'strings-en.json'), $utf8)))
$nowhere = [string](Join-Path $work 'nowhere')
$bridgeType = $assembly.GetType('CodexAutoResume.Bridge', $true)
$persistentType = $assembly.GetType('CodexAutoResume.PersistentBridge', $true)
$three = @($form.GetConstructors($instance) | Where-Object { $_.GetParameters().Count -eq 3 })[0]
function New-Window([bool]$auditing) {
    $once = $bridgeType.GetConstructors($instance)[0].Invoke([object[]]@($nowhere))
    $bridge = $persistentType.GetConstructors($instance)[0].Invoke([object[]]@($nowhere, $once))
    $window = $three.Invoke([object[]]@($bridge, $english, [Drawing.SystemFonts]::MessageBoxFont))
    $form.GetField('auditing', $instance).SetValue($window, $auditing)
    $window.TopLevel = $false
    $window.MinimumSize = [Drawing.Size]::Empty
    $window.ClientSize = New-Object Drawing.Size ([int]$form.GetField('OpeningWidth', $static).GetValue($null)), ([int]$form.GetField('OpeningHeight', $static).GetValue($null))
    return $window
}
$out.window = @{}

# The Custom card and its per-kind editor, built into a Settings page that is not on screen - as
# the editors are built on idle when the window opens on Overview.
$schemaValue = $parse.Invoke($null, [object[]]@($schema))
foreach ($style in @('standard', 'custom')) {
    $values = $parse.Invoke($null, [object[]]@([IO.File]::ReadAllText((Join-Path $work ('settings-' + $style + '.json')), $utf8)))
    $window = New-Window $true
    Invoke-Window $window 'ShowPage' @('overview')
    Invoke-Window $window 'BuildEditors' @($schemaValue, $values)
    $card = Get-Field $window 'customCard'
    $perKind = Get-Field $window 'perReasonPanel'
    $built = @((Test-Own $card), (Test-Own $perKind))
    Invoke-Window $window 'ShowPage' @('settings')
    Invoke-Window $window 'ShowSection' @('continuation')
    $out.window[$style] = @{ built = $built; shown = @((Test-Own $card), (Test-Own $perKind)) }
    $window.Dispose()
}

# History's thread button, updated while another page is on screen.
$window = New-Window $true
Invoke-Window $window 'ShowPage' @('history')
$list = Get-Field $window 'historyList'
# A list keeps a selection only once it has a window of its own; nothing is shown.
$null = $list.Handle
$button = Get-Field $window 'historyThread'
$item = New-Object Windows.Forms.ListViewItem 'one'
$item.Tag = $parse.Invoke($null, [object[]]@('{"interruption_id": "one", "code": "cancelled", "thread_enabled": false}'))
$null = $list.Items.Add($item)
$item.Selected = $true
Invoke-Window $window 'UpdateHistoryButtons' @()
$threadOff = Test-Own $button
Invoke-Window $window 'ShowPage' @('pending')
$item.Tag = $parse.Invoke($null, [object[]]@('{"interruption_id": "one", "code": "cancelled", "thread_enabled": true}'))
Invoke-Window $window 'UpdateHistoryButtons' @()
$whileHidden = Test-Own $button
Invoke-Window $window 'ShowPage' @('history')
$out.window.thread = @($threadOff, $whileHidden, (Test-Own $button), [int]$list.SelectedItems.Count)
$window.Dispose()

# A page's first visit, with a snapshot just read and with one over two seconds old. Not audited,
# so the switch decides whether to read; a read asked for here fails to start, and nothing pumps
# the window's messages, so `refreshing` stays as the switch left it.
$window = New-Window $false
$held = $parse.Invoke($null, [object[]]@('{"ok": true, "status": {"watcher_running": true, "enabled": true, "pending": 0, "version": "0.6.4"}, "pending": [], "history": []}'))
$form.GetField('snapshot', $instance).SetValue($window, $held)
$age = Get-Field $window 'snapshotAge'
$age.Restart()
Invoke-Window $window 'ShowPage' @('pending')
$freshReads = [bool](Get-Field $window 'refreshing')
Start-Sleep -Milliseconds 2200
Invoke-Window $window 'ShowPage' @('diagnostics')
$out.window.snapshot = @($freshReads, [bool](Get-Field $window 'refreshing'), [bool]($age.ElapsedMilliseconds -ge 2000))
$window.Dispose()

# Recently finished, filled again on an Overview already laid out: a recovery finishes while the window
# is open (finished_while_open), the rows are rebuilt, and the card's width does not change. At this
# machine's scale and its opening size, as the window opens.
$materialise = $form.GetMethod('Materialise', $static)
$systemScale = [double]$form.GetField('SystemScale', $static).GetValue($null)
function Read-Snapshot([string]$name) { return $parse.Invoke($null, [object[]]@([IO.File]::ReadAllText((Join-Path $work $name), $utf8))) }
function Get-Recent($window) {
    $grid = Get-Field $window 'recentGrid'
    $state = @{ shown = @(); cut = @(); first = 0 }
    foreach ($control in $grid.Controls) {
        if ($null -eq $control.Tag) { continue }
        $wanted = [int]$control.GetPreferredSize([Drawing.Size]::Empty).Width
        $state.shown += [string]$control.Text
        if ($wanted -gt $control.Width + 1) { $state.cut += ([string]$control.Text + ' is ' + $control.Width + ' of ' + $wanted) }
    }
    # Which rows these are: a rebuilt card holds new labels.
    if ($grid.Controls.Count -gt 0) { $state.first = [Runtime.CompilerServices.RuntimeHelpers]::GetHashCode($grid.Controls[0]) }
    return $state
}
$out.recent = @{}
foreach ($locale in (ConvertFrom-Json $env:CAR_LOCALES)) {
    $catalogValue = $parse.Invoke($null, [object[]]@([IO.File]::ReadAllText((Join-Path $work ('strings-' + $locale + '.json')), $utf8)))
    $once = $bridgeType.GetConstructors($instance)[0].Invoke([object[]]@($nowhere))
    $bridge = $persistentType.GetConstructors($instance)[0].Invoke([object[]]@($nowhere, $once))
    $window = $three.Invoke([object[]]@($bridge, $catalogValue, [Drawing.SystemFonts]::MessageBoxFont))
    $form.GetField('auditing', $instance).SetValue($window, $true)
    $window.TopLevel = $false
    $window.MinimumSize = [Drawing.Size]::Empty
    $window.ClientSize = New-Object Drawing.Size ([int][Math]::Round([int]$form.GetField('OpeningWidth', $static).GetValue($null) * $systemScale)), ([int][Math]::Round([int]$form.GetField('OpeningHeight', $static).GetValue($null) * $systemScale))
    Invoke-Window $window 'ApplySnapshot' @((Read-Snapshot 'snapshot.json'))
    Invoke-Window $window 'ShowPage' @('overview')
    $null = $materialise.Invoke($null, [object[]]@($window))
    $window.PerformLayout()
    $opened = Get-Recent $window
    Invoke-Window $window 'ApplySnapshot' @((Read-Snapshot 'snapshot-later.json'))
    $window.PerformLayout()
    $rebuilt = Get-Recent $window
    $out.recent[$locale] = @{ opened = $opened; rebuilt = $rebuilt }
    $window.Dispose()
}

# Each Overview card's button (Lead): the windows of its card under its lift and focus ring, and the order of the card's
# windows - the order Windows hands a screen reader. In a window as tall as the rows need, where every button is as close
# under what its card holds as it ever comes, at this machine's scale, in English, never shown: a window has a handle
# without being on screen.
Add-Type -Namespace LayoutProbe -Name Native -MemberDefinition @'
[DllImport("user32.dll")] public static extern System.IntPtr GetWindow(System.IntPtr window, uint command);
'@
$groundType = $assembly.GetType('CodexAutoResume.Ground', $true)
$bandOf = $groundType.GetMethod('Band', $static)
function Get-Under($container, [int]$x, [int]$y, $band, $skip, $list) {
    foreach ($child in $container.Controls) {
        if ($child -eq $skip -or -not (Test-Own $child)) { continue }
        $bounds = New-Object Drawing.Rectangle ($x + $child.Left), ($y + $child.Top), $child.Width, $child.Height
        if ($bounds.IntersectsWith($band)) { $null = $list.Add(@($child, $bounds)) }
        Get-Under $child ($x + $child.Left) ($y + $child.Top) $band $skip $list
    }
}
$window = New-Window $true
Invoke-Window $window 'ApplySnapshot' @((Read-Snapshot 'snapshot.json'))
Invoke-Window $window 'ShowPage' @('overview')
$null = $materialise.Invoke($null, [object[]]@($window))
$window.PerformLayout()
$overview = (Get-Field $window 'pages')['overview']
$pageExtent = [int]$overview.GetType().GetProperty('Extent', $instance).GetValue($overview)
$window.ClientSize = New-Object Drawing.Size $window.ClientSize.Width, ($window.ClientSize.Height - [Math]::Max(0, $overview.ClientSize.Height - $pageExtent))
$null = $materialise.Invoke($null, [object[]]@($window))
$window.PerformLayout()
$out.liftsAt = @([int]$overview.ClientSize.Height, $pageExtent, [bool]$overview.GetType().GetProperty('Overflowing', $instance).GetValue($overview))
$out.lifts = @()
foreach ($pair in (Get-Field $window 'led').GetEnumerator()) {
    $button = $pair.Key
    $card = $pair.Value
    $band = [Drawing.Rectangle]$bandOf.Invoke($null, [object[]]@($button, 'control'))
    $under = New-Object Collections.ArrayList
    Get-Under $card 0 0 $band $button $under
    $names = @()
    foreach ($entry in $under) { $names += ($entry[0].GetType().Name + ' ' + $entry[1]) }
    $order = @()
    for ($h = [LayoutProbe.Native]::GetWindow($card.Handle, 5); $h -ne [IntPtr]::Zero; $h = [LayoutProbe.Native]::GetWindow($h, 2)) {
        $order += [Windows.Forms.Control]::FromHandle($h).GetType().Name
    }
    $tabs = @($card.Controls | Where-Object { Test-Own $_ } | Sort-Object TabIndex | ForEach-Object { $_.GetType().Name })
    $out.lifts += ,@{ text = [string]$button.Text; parent = [string]$button.Parent.GetType().Name; under = $names; order = $order; tabs = $tabs }
}
$window.Dispose()

# The Overview laid out otherwise than FitOverview lays it out, so a quiet report on its rows is the audit measuring:
# its rows 20 px taller each than FitOverview made them, reaching into the page's padding under them; its rows as they
# were, in a window 120 px taller (a band); and its rows sharing a window 240 px taller (cards that float). At this
# machine's scale, in English, from the opening size.
function Get-RowsCanary([int]$taller, [bool]$fill, [int]$grow) {
    $window = New-Window $true
    Invoke-Window $window 'ApplySnapshot' @((Read-Snapshot 'snapshot.json'))
    Invoke-Window $window 'ShowPage' @('overview')
    $null = $materialise.Invoke($null, [object[]]@($window))
    $window.PerformLayout()
    $form.GetField('fitOverview', $instance).SetValue($window, $false)
    $grid = Get-Field $window 'overviewGrid'
    if ($fill) {
        for ($i = 0; $i -lt 2; $i++) { $grid.RowStyles[$i].SizeType = [Windows.Forms.SizeType]::Percent; $grid.RowStyles[$i].Height = 50 }
        $grid.RowStyles[2].SizeType = [Windows.Forms.SizeType]::Absolute
        $grid.RowStyles[2].Height = 0
    }
    for ($i = 0; $i -lt 2 -and $grow -ne 0; $i++) { $grid.RowStyles[$i].Height = $grid.RowStyles[$i].Height + $grow }
    $window.ClientSize = New-Object Drawing.Size $window.ClientSize.Width, ($window.ClientSize.Height + $taller)
    $null = $materialise.Invoke($null, [object[]]@($window))
    $window.PerformLayout()
    $findings = New-Object 'System.Collections.Generic.List[string]'
    Invoke-Window $window 'AuditRows' @('rows canary', $true, $findings.PSObject.BaseObject)
    $window.Dispose()
    return ($findings -join "`n")
}
$out.rowsCanary = @{ grown = (Get-RowsCanary 0 $false 20); band = (Get-RowsCanary 120 $false 0); floats = (Get-RowsCanary 240 $true 0) }

# The space under each page's last card, down to the page's edge, at the opening size: the Overview's with the fullest
# reply and as a first installation shows it, and Pending's and History's. One rhythm, so the footer stays where it is
# as the tabs change; the review found the Overview's 41 px where the others' is 27, and 87 on a first installation.
function Get-Lowest($container, [int]$top) {
    $lowest = 0
    foreach ($child in $container.Controls) {
        if (-not (Test-Own $child)) { continue }
        if ($child.GetType().Name -eq 'SoftCard' -or $child -is [Windows.Forms.Button]) { $lowest = [Math]::Max($lowest, $top + $child.Bottom) }
        else { $lowest = [Math]::Max($lowest, (Get-Lowest $child ($top + $child.Top))) }
    }
    return $lowest
}
$out.gaps = @{}
foreach ($case in @(@('overview', 'snapshot.json'), @('overview', 'snapshot-first.json'), @('pending', 'snapshot.json'), @('history', 'snapshot.json'))) {
    $window = New-Window $true
    $window.ClientSize = New-Object Drawing.Size ([int][Math]::Round([int]$form.GetField('OpeningWidth', $static).GetValue($null) * $systemScale)), ([int][Math]::Round([int]$form.GetField('OpeningHeight', $static).GetValue($null) * $systemScale))
    Invoke-Window $window 'ApplySnapshot' @((Read-Snapshot $case[1]))
    Invoke-Window $window 'ShowPage' @($case[0])
    $null = $materialise.Invoke($null, [object[]]@($window))
    $window.PerformLayout()
    $page = (Get-Field $window 'pages')[$case[0]]
    $out.gaps[$case[0] + ' ' + $case[1]] = @([int]($page.ClientSize.Height - (Get-Lowest $page 0)), [int]$page.Padding.Top, [int]$page.Padding.Bottom,
                                             [bool]$page.GetType().GetProperty('Overflowing', $instance).GetValue($page))
    $window.Dispose()
}

# A name of Right now that wraps, so a quiet report on names is the audit measuring them.
$window = New-Window $true
Invoke-Window $window 'ApplySnapshot' @((Read-Snapshot 'snapshot.json'))
Invoke-Window $window 'ShowPage' @('overview')
$first = (Get-Field $window 'nowFacts').Controls[0]
$first.MaximumSize = New-Object Drawing.Size 40, 0
$null = $materialise.Invoke($null, [object[]]@($window))
$window.PerformLayout()
$nameFindings = New-Object 'System.Collections.Generic.List[string]'
Invoke-Window $window 'AuditNames' @('names canary', $nameFindings.PSObject.BaseObject)
$out.namesCanary = ($nameFindings -join "`n")
$window.Dispose()

# Pending and History in the narrowest window there is - 800 wide, the window's MinimumSize - with the fullest reply and
# with no rows, in every language at 100% and 200%: their columns share the list's width (FitColumns, ColumnFloors).
$out.narrow = @{}
$empty = $form.GetMethod('WithoutRows', $static).Invoke($null, [object[]]@((Read-Snapshot 'snapshot.json')))
$listOf = @{ pending = 'pendingList'; history = 'historyList' }
foreach ($scale in @(1.0, 2.0)) {
    $form.GetField('dpiScale', $static).SetValue($null, [double]$scale)
    $factor = [single]($scale / $systemScale)
    $box = [Drawing.SystemFonts]::MessageBoxFont
    [Drawing.Font]$font = New-Object Drawing.Font $box.FontFamily, ($box.SizeInPoints * $factor), $box.Style, ([Drawing.GraphicsUnit]::Point)
    foreach ($locale in (ConvertFrom-Json $env:CAR_LOCALES)) {
        $catalogValue = $parse.Invoke($null, [object[]]@([IO.File]::ReadAllText((Join-Path $work ('strings-' + $locale + '.json')), $utf8)))
        $once = $bridgeType.GetConstructors($instance)[0].Invoke([object[]]@($nowhere))
        $bridge = $persistentType.GetConstructors($instance)[0].Invoke([object[]]@($nowhere, $once))
        $window = $three.Invoke([object[]]@($bridge, $catalogValue, $font.PSObject.BaseObject))
        $form.GetField('auditing', $instance).SetValue($window, $true)
        $window.TopLevel = $false
        $window.MinimumSize = [Drawing.Size]::Empty
        $window.ClientSize = New-Object Drawing.Size ([int][Math]::Round(800 * $scale)), ([int][Math]::Round([int]$form.GetField('OpeningHeight', $static).GetValue($null) * $scale))
        $found = @()
        foreach ($reply in @((Read-Snapshot 'snapshot.json'), $empty)) {
            Invoke-Window $window 'ApplySnapshot' @($reply)
            foreach ($page in @('pending', 'history')) {
                Invoke-Window $window 'ShowPage' @($page)
                $null = $materialise.Invoke($null, [object[]]@($window))
                $window.PerformLayout()
                $list = Get-Field $window $listOf[$page]
                $total = 0
                foreach ($column in $list.Columns) { $total += $column.Width }
                if ($total -gt $list.ClientSize.Width) { $found += ($page + ' ' + $total + ' in ' + $list.ClientSize.Width) }
            }
        }
        $out.narrow[$locale + ' ' + $scale] = $found
        $window.Dispose()
    }
}
$form.GetField('dpiScale', $static).SetValue($null, $systemScale)

# A card that grows on an Overview already laid out, as a refresh grows one: the page is told, measures its rows again
# and scrolls, and the card is laid out as tall as it now needs.
$window = New-Window $true
Invoke-Window $window 'ApplySnapshot' @((Read-Snapshot 'snapshot.json'))
Invoke-Window $window 'ShowPage' @('overview')
$null = $materialise.Invoke($null, [object[]]@($window))
$window.PerformLayout()
$overview = (Get-Field $window 'pages')['overview']
$overflowing = $overview.GetType().GetProperty('Overflowing', $instance)
$line = Get-Field $window 'waitingLine'
$grownCard = $line
while ($null -ne $grownCard -and $grownCard.GetType().Name -ne 'SoftCard') { $grownCard = $grownCard.Parent }
$fitted = [bool]$overflowing.GetValue($overview)
$heightBefore = $grownCard.Height
$line.Text = [string]::Join("`n", @('waiting') * 40)
$out.grown = @{ before = $fitted; after = [bool]$overflowing.GetValue($overview); heightBefore = $heightBefore; height = $grownCard.Height
                needs = $grownCard.GetPreferredSize((New-Object Drawing.Size $grownCard.Width, 0)).Height }
$window.Dispose()
[IO.File]::WriteAllText((Join-Path $work 'result.json'), ($out | ConvertTo-Json -Depth 6 -Compress), $utf8)
"""

SCALES = (1.0, 1.25, 1.5, 1.75, 2.0)

# SettingsForm.OverviewHeights: ((each row's need, the room from the first row's top to the page's edge, the page's
# padding under the last row, comfort), each row's height).
HEIGHTS = (
    (([194, 194], 443, 17, 24), [213, 213]),      # the opening size at 100%: the page's padding under them, the rest shared
    (([194, 148], 443, 17, 24), [213, 213]),      # a first installation: its short row as tall as the other, no band under it
    (([194, 184], 443, 17, 24), [213, 213]),
    (([194, 194], 800, 17, 24), [218, 218]),      # a taller window: comfort at most, the rest is space under the rows
    (([194, 148], 800, 17, 24), [218, 218]),
    (([194, 148], 377, 17, 24), [194, 166]),      # no room for them alike: what the page has raises the shorter row
    (([194, 194], 400, 17, 24), [194, 194]),      # less than they need: what they need, and the page scrolls
    (([100, 50, 20], 300, 10, 30), [100, 95, 95]),  # the shortest rows raised first, toward the tallest
    (([0, 0], 100, 14, 24), [24, 24]),
)


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class LayoutAuditTests(unittest.TestCase):
    """Every page of the real window, in every language at five scalings, at its opening size.

    The window is built and laid out without being shown - it is not even a top-level window -
    and no input is sent to it (`SettingsForm.LayoutAudit`). Other scalings are stood in for by
    scaling the window's scale and its fonts together, which matched a real 144-DPI window to the
    pixel when the v0.6.3 clipping was measured. The Custom message and its per-kind editor are
    showing, so every drop-down on the Settings page is laid out.

    The same probe holds the strings cache to the installation it was written for, and the window,
    built the same way, to what its hidden pages and sections are left with.
    """

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        work = Path(cls.folder.name)
        exe = work / "CodexAutoResumeSettings.exe"
        subprocess.run([str(CSC), "/nologo", "/target:winexe", "/platform:x64", "/out:" + str(exe),
                        "/reference:System.dll", "/reference:System.Drawing.dll",
                        "/reference:System.Windows.Forms.dll",
                        *[str(path) for path in guiscan.sources()]],
                       check=True, capture_output=True, timeout=300)
        current = dict(settings.defaults(), continuation_style="custom", custom_message_mode="per_reason")
        (work / "schema.json").write_text(json.dumps(settings.describe(), ensure_ascii=False), encoding="utf-8")
        (work / "settings.json").write_text(json.dumps(current, ensure_ascii=False), encoding="utf-8")
        (work / "settings-custom.json").write_text(json.dumps(current, ensure_ascii=False), encoding="utf-8")
        standard = dict(settings.defaults(), continuation_style="standard")
        (work / "settings-standard.json").write_text(json.dumps(standard, ensure_ascii=False), encoding="utf-8")

        def reply(locale, catalog):
            return {"ok": True, "language": locale, "strings": catalog, "endonyms": dict(l10n.ENDONYMS),
                    "preference": locale, "system_language": locale}

        for locale in l10n.LOCALES:
            (work / ("strings-%s.json" % locale)).write_text(
                json.dumps(reply(locale, l10n.catalog(locale)), ensure_ascii=False), encoding="utf-8")
        # And a reopen note no save card could hold, which the audit shows at the window's narrowest.
        canary = dict(l10n.catalog("en"), **{"field.theme": "W" * 400,
                                              "note.reopen_pending": " ".join(["The window reopens."] * 60),
                                              # The Diagnostics page's compatibility card, measured too.
                                              "compat.source.cache": "V" * 400,
                                              # And a callout on it (v0.6.10), which no card could hold.
                                              "compat.cache.expired": "X" * 400})
        (work / "strings-canary.json").write_text(json.dumps(reply("en", canary)), encoding="utf-8")
        cramped = dict(l10n.catalog("en"), **{"overview.waiting_count": " ".join(["{n} waiting"] * 60)})
        (work / "strings-cramped.json").write_text(json.dumps(reply("en", cramped)), encoding="utf-8")
        now = time.time()
        fullest = fullest_snapshot(now)
        (work / "snapshot.json").write_text(json.dumps(fullest, ensure_ascii=False), encoding="utf-8")
        (work / "snapshot-later.json").write_text(json.dumps(finished_while_open(fullest, now), ensure_ascii=False),
                                                  encoding="utf-8")
        (work / "snapshot-first.json").write_text(json.dumps(first_installation(now), ensure_ascii=False), encoding="utf-8")
        (work / "states.json").write_text(json.dumps(overview_states(now), ensure_ascii=False), encoding="utf-8")
        unheard = copy.deepcopy(fullest)
        unheard["status"]["watcher"]["engine_state"] = " ".join(["a-state-this-window-has-no-word-for"] * 12)
        (work / "states-canary.json").write_text(json.dumps([["the fullest", fullest], ["an unheard-of engine", unheard]]),
                                                 encoding="utf-8")
        longer = copy.deepcopy(fullest)
        longer["status"]["watcher"]["engine_state"] = " ".join(["a-state-this-window-has-no-word-for"] * 2)
        (work / "states-line-canary.json").write_text(
            json.dumps([["the fullest", fullest], ["an engine state a line longer", longer]]), encoding="utf-8")
        (work / "heights.json").write_text(json.dumps([case for case, _ in HEIGHTS]), encoding="utf-8")
        install = work / "install"
        (install / "config").mkdir(parents=True)
        (install / "config" / "settings.json").write_text('{"interface_language": "system"}', encoding="utf-8")
        locales = install / "app" / "src" / "codex_auto_resume" / "locales"
        locales.mkdir(parents=True)
        (locales / "en.json").write_text('{"a": "b"}', encoding="utf-8")
        probe = work / "probe.ps1"
        probe.write_text(PROBE, encoding="utf-8")
        cls.result = subprocess.run(
            [str(POWERSHELL), "-STA", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(probe)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1500,
            env=dict(os.environ, CAR_EXE=str(exe), CAR_WORK=str(work),
                     CAR_LOCALES=json.dumps(list(l10n.LOCALES)), CAR_SCALES=json.dumps(SCALES)))
        answer = work / "result.json"
        cls.answer = (json.loads(answer.read_text(encoding="utf-8-sig"))
                      if cls.result.returncode == 0 and answer.is_file() else {})

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        if not self.answer:
            self.fail("the probe did not run: " + (self.result.stderr or self.result.stdout)[-3000:])

    def test_nothing_is_cut_off_on_any_page_in_any_language_at_any_scaling(self):
        self.assertEqual(sorted(self.answer["audit"]), sorted(l10n.LOCALES))
        for locale in l10n.LOCALES:
            for scale in SCALES:
                report = self.answer["audit"][locale]["%.2f" % scale]
                with self.subTest(locale=locale, scale=scale):
                    self.assertEqual(report, "", "\n" + "\n".join(report.splitlines()[:40]))

    def test_the_header_s_light_was_held_to_its_place_in_every_language_at_every_scaling(self):
        """The header's light stands where it always has: spanning the headline and the line under it, centred on
        the pair, in its own 28 px column (AuditHero; v0.6.10 stood it on the headline's line for a while and gave
        that back). Its findings are in the first test's reports; this holds the audit to having looked, with the
        Start button shown and without."""
        for locale in l10n.LOCALES:
            for scale in SCALES:
                with self.subTest(locale=locale, scale=scale):
                    self.assertEqual(self.answer["hero"][locale]["%.2f" % scale], 2)

    def test_the_audit_finds_what_does_not_fit(self):
        self.assertIn("Label'WWWW", self.answer["canary"],
                      "a 400-character label went unreported, so an empty report proves nothing")
        self.assertIn("reopen note at ", self.answer["canary"],
                      "a note sixty sentences long went unreported, so a quiet report on the note proves nothing")
        self.assertIn("shown before the window was laid out", self.answer["canary"],
                      "the note shown before the window's new width reached the save card went unreported, "
                      "so a quiet report on that order proves nothing")
        self.assertRegex(self.answer["canary"], r"diagnostics/.*Label'VVVV",
                         "the compatibility card's data in force, 400 characters wide, went unreported, so a quiet "
                         "report on the card proves nothing")
        self.assertRegex(self.answer["canary"], r"diagnostics/.*SoftCallout'XXXX[^\n]* :: a word needs ",
                         "a callout's notice, 400 characters wide, went unreported, so a quiet report on the "
                         "callouts proves nothing")

    def test_the_save_card_holds_the_reopen_note_whichever_order_the_window_came_to_its_width(self):
        """The card's height is worked out when the note is shown, and a window that has just been made
        narrower has not always laid the card out at its new width by then. Measured at the width the card
        still had, the note was given the room two of its lines need where four fit in the width it really
        gets - and the layout the taller card asks for, asked for from inside the layout that is running,
        is dropped when that one ends (Control.PerformLayout), so the card stayed short. Every window on
        this machine laid the card out first and measured the same note right; CI's fonts made it four
        lines instead of two, and the audit there reported Spanish, German and French cut off from 150% up
        (v0.6.4). The audit now measures both widths in both orders - the findings are in the first test's
        reports - and this holds it to having measured all four."""
        self.assertEqual(sorted(self.answer["notes"]), sorted(l10n.LOCALES))
        for locale in l10n.LOCALES:
            for scale in SCALES:
                with self.subTest(locale=locale, scale=scale):
                    self.assertEqual(self.answer["notes"][locale]["%.2f" % scale], 4)

    def test_every_button_is_in_its_corner_and_over_no_text(self):
        """The Overview's three card buttons at their cards' bottom LEFT, clear of the text above them (AuditLead), and
        the header's Start button and the Custom messages' two Clear buttons at their card's or row's bottom right
        (AuditPin), in every language at every scaling (their findings are in the first test's reports). This holds the
        audit to having looked at all six."""
        self.assertEqual(sorted(self.answer["pins"]), sorted(l10n.LOCALES))
        for locale in l10n.LOCALES:
            for scale in SCALES:
                with self.subTest(locale=locale, scale=scale):
                    self.assertEqual(self.answer["pins"][locale]["%.2f" % scale], 6)

    def test_the_audit_finds_a_button_out_of_its_corner_or_over_text(self):
        canary = self.answer["pinCanary"]
        self.assertIn("canary/Button'stray' :: is not at the bottom right of its Panel", canary)
        self.assertIn("canary/Button'stray' :: covers Label'covered'", canary)
        lead = self.answer["leadCanary"]
        self.assertIn("canary/Button'stray' :: is not at the bottom left of its Panel", lead)
        self.assertIn("canary/Button'stray' :: covers Label'covered'", lead)
        self.assertIn("crowded/Button'cornered' :: has less than 12 px above it to Label'above'", lead,
                      "a line of text just above a button in its corner went unreported")
        self.assertNotIn("crowded/Button'cornered' :: is not at the bottom left", lead)

    def test_no_list_scrolls_sideways_at_the_opening_size(self):
        """v0.6.5 (the person, with a screenshot): Windows' white horizontal bar under the Pending list. Pending and
        History with the fullest reply and with no rows, and the Timeline dialog's list, in every language at every
        scaling: their columns share their width (their findings are in the first test's reports). This holds the
        audit to having looked at all five, and a list whose columns are wider than it is to being reported."""
        self.assertEqual(sorted(self.answer["lists"]), sorted(l10n.LOCALES))
        for locale in l10n.LOCALES:
            for scale in SCALES:
                with self.subTest(locale=locale, scale=scale):
                    self.assertEqual(self.answer["lists"][locale]["%.2f" % scale], 5)
        self.assertIn("canary :: scrolls sideways at the opening size, its columns 400 wide in ", self.answer["listCanary"])

    def test_the_lists_share_their_width_in_the_narrowest_window_too(self):
        """At the window's MinimumSize, 800 wide, Pending's headings no longer fit in several languages: the widest
        give way first, ending in an ellipsis, and no column is cut below the least it can show (ColumnFloors). v0.6.4 left
        the columns their headings whole there, wider than the list."""
        self.assertEqual(len(self.answer["narrow"]), 2 * len(l10n.LOCALES))
        for key, found in sorted(self.answer["narrow"].items()):
            with self.subTest(key):
                self.assertEqual(found, [], "columns wider than their list")

    def test_the_overview_neither_scrolls_nor_moves_whatever_state_the_watcher_is_in(self):
        """Opened on a watcher in trouble with recovery paused, then refreshed through the fullest reply, a stopped
        watcher, an unknown one, nothing waiting and unreadable lists, and last made shorter than the page and given
        its height back (overview_states, SettingsForm.OverviewStatesAudit). At every step the Overview fits, its
        buttons are in their corners over no text, and Right now is laid out as it was at the first. In v0.6.4 as
        first pinned it scrolled in German at 125% and 150% and in French at every scaling, and a page the soft bar
        had narrowed kept the bar at a height that fitted."""
        self.assertEqual(sorted(self.answer["states"]), sorted(l10n.LOCALES))
        for locale in l10n.LOCALES:
            for scale in SCALES:
                key = "%.2f" % scale
                report = self.answer["states"][locale][key]
                with self.subTest(locale=locale, scale=scale):
                    self.assertEqual(report, "", "\n" + "\n".join(report.splitlines()[:40]))
                    self.assertEqual(self.answer["statesAudited"][locale][key], len(overview_states(0)) + 1,
                                     "every state and the round trip were measured")

    def test_the_state_audit_finds_right_now_laid_out_for_words_it_was_not_planned_for(self):
        self.assertIn("overview (an unheard-of engine) :: Right now is laid out", self.answer["statesCanary"],
                      "an engine state as long as a paragraph moved nothing, so a quiet report on the states proves nothing")

    def test_the_state_audit_finds_a_line_of_right_now_that_moved(self):
        """A state whose words take one more line in Right now, and still fit, makes the card need a line more; the rows
        are then given what they need again, and the page does not scroll, so the height the card needs is what shows
        the move - and the paragraph-long engine state above scrolls the page, which its size alone reports."""
        report = self.answer["statesLineCanary"]
        self.assertNotIn("the page scrolls", report, "the longer state scrolled the page, so it is not the move this measures")
        found = re.search(r"overview \(an engine state a line longer\) :: Right now is laid out (\{[^}]*\}), needing (\d+), "
                          r"where it was (\{[^}]*\}), needing (\d+)", report)
        self.assertIsNotNone(found, "a line more in Right now went unreported, so a quiet report on a move proves nothing:\n" + report)
        self.assertGreater(int(found.group(2)), int(found.group(4)))

    def test_no_window_of_a_card_lies_under_its_buttons_lift_or_focus_ring(self):
        """A button in a row of its own under what its card holds, the scale's medium step clear of it, has no window
        but its card's under its lift and focus ring - the card draws them, and repaints them when the button changes
        (Ground). v0.6.4's buttons lay beside the content, whose windows had to draw and repaint parts of both (SoftPin).
        Measured in a window as tall as the rows need, where each button is as close under what its card holds as it
        ever comes."""
        height, extent, overflowing = self.answer["liftsAt"]
        self.assertEqual((height, overflowing), (extent, False), "the window is not as tall as the page needs")
        lifts = self.answer["lifts"]
        self.assertEqual(sorted(lift["text"] for lift in lifts), ["History", "Pause recovery", "Pending"])
        for lift in lifts:
            with self.subTest(lift["text"]):
                self.assertEqual(lift["parent"], "SoftCard", "the button stands in its card, not in a block beside the content")
                self.assertEqual(lift["under"], [], "a window of the card under the button's lift or ring")

    def test_a_screen_reader_reaches_a_cards_content_before_its_button(self):
        """Windows hands a screen reader a card's windows top of the z-order first, and Tab reaches them by TabIndex: the
        heading and what the card holds first, as they are seen, and the button last."""
        for lift in self.answer["lifts"]:
            with self.subTest(lift["text"]):
                self.assertEqual(lift["order"][-1], "SoftButton")
                self.assertEqual(lift["order"].count("SoftButton"), 1)
                self.assertEqual(lift["tabs"][-1], "SoftButton")

    def test_the_audit_finds_an_overview_that_would_scroll(self):
        """The fullest Overview in every language at every scaling is in the first test's empty
        reports; this is the same measurement shown a page that cannot fit."""
        self.assertIn("overview :: the page scrolls", self.answer["cramped"],
                      "a waiting count sixty lines long did not make the Overview scroll, so no report of it proves nothing")
        self.assertNotIn("pending :: the page scrolls", self.answer["cramped"])

    def test_the_audit_finds_an_overview_laid_out_otherwise(self):
        """The Overview's rows are as FitOverview gives them in every language at every scaling and in every state (the
        first test's and the state test's empty reports); this is the same measurement shown them laid out otherwise:
        rows taller than the page leaves them, reaching into its padding; as they were in a window 120 px taller, over
        an empty band; and sharing a much taller window, every card floating."""
        canary = self.answer["rowsCanary"]
        self.assertIn("rows canary :: leaves only ", canary["grown"],
                      "rows reaching into the page's padding went unreported, so a quiet report on the space under them "
                      "proves nothing")
        self.assertIn("rows canary :: leaves an empty band", canary["band"],
                      "a band under rows that could be taller went unreported")
        self.assertIn(":: floats: ", canary["floats"], "cards stretched far past what they hold went unreported")

    def test_the_footer_keeps_its_place_as_the_tabs_change(self):
        """The review: under the Overview's last row 41 px of canvas above the save card at 200% where Pending and History
        leave 27, and 87 on a first installation - the footer's gap jumped as the tabs changed, three times the gap between
        the cards. Now every page leaves its own padding under its last card, the mirror of the padding over its first,
        with the fullest reply and as a first installation shows the Overview."""
        gaps = self.answer["gaps"]
        self.assertEqual(len(gaps), 4)
        pending = gaps["pending snapshot.json"]
        for key, (gap, top, bottom, overflowing) in sorted(gaps.items()):
            with self.subTest(key):
                self.assertFalse(overflowing, "the page scrolls")
                self.assertLessEqual(abs(gap - bottom), 1, "under the last card, anything but the page's own padding")
                self.assertLessEqual(abs(bottom - top), 1, "the padding under the last card mirrors the padding over the first")
                self.assertLessEqual(abs(gap - pending[0]), 1, "a gap above the footer other than Pending's")

    def test_the_overview_scrolls_only_in_a_window_shorter_than_its_rows_own_tallest_cards(self):
        """In a window shorter than the opening size the space under the rows goes first, then the rows' part, and the
        page scrolls only once the rows themselves do not fit (OverviewHeights). SettingsForm.AuditShortest measures the
        window as tall as the rows' own tallest cards, taken from the cards, in every language at every scaling: the
        page does not scroll there, leaves no space under the rows, cuts off no card and nothing in one, and puts every
        button in its corner over no text - and a pixel shorter it scrolls. And that window fits a 1920 by 1080 screen at
        150%, whose work area leaves the window 952 device pixels, where KeepOnScreen makes it that tall."""
        for locale in l10n.LOCALES:
            for scale in SCALES:
                key = "%.2f" % scale
                shortest, alike, _ = self.answer["shortest"][locale][key]
                report = self.answer["audit"][locale][key]
                with self.subTest(locale=locale, scale=scale):
                    self.assertGreater(shortest, 0, "the shortest window was not measured")
                    self.assertLessEqual(shortest, alike)
                    lines = [line for line in report.splitlines() if "the shortest window" in line]
                    self.assertEqual(lines, [], "\n" + "\n".join(lines[:20]))
            with self.subTest(locale=locale, screen="1920 by 1080 at 150%"):
                self.assertLessEqual(self.answer["shortest"][locale]["1.50"][0], 952)

    def test_the_overviews_rows_are_as_tall_as_their_cards_and_a_little_more(self):
        """SettingsForm.OverviewHeights, the heights the Overview's rows are given: alike, each as tall as the tallest
        needs and an even share of what the page has past that and its padding, never more than comfort; where the page
        has no room for them alike, each what it needs and the shortest raised toward the tallest; less than they need,
        what they need, and the page scrolls."""
        self.assertEqual(len(self.answer["heights"]), len(HEIGHTS))
        for (case, expected), given in zip(HEIGHTS, self.answer["heights"]):
            with self.subTest(needs=case[0], room=case[1]):
                self.assertEqual(given, expected)

    def test_right_now_keeps_its_names_whole(self):
        """The button stands under Right now's facts, so their names have the card's whole width and never wrap - at the
        opening size in every language at every scaling (SettingsForm.AuditNames, in the first test's reports), in every
        state (the state test's) and in the shortest window the Overview fits. The check sees a name that wraps."""
        for locale in l10n.LOCALES:
            for scale in SCALES:
                key = "%.2f" % scale
                with self.subTest(locale=locale, scale=scale):
                    lines = [line for line in self.answer["audit"][locale][key].splitlines() + self.answer["states"][locale][key].splitlines()
                             if " :: wraps, " in line]
                    self.assertEqual(lines, [], "\n" + "\n".join(lines[:20]))
                    self.assertEqual(self.answer["shortest"][locale][key][2], 0, "a name wrapped in the shortest window")
        # A fact's name is a WrapLabel since v0.6.5 (Value), which breaks Korean between its words.
        self.assertIn("names canary/WrapLabel", self.answer["namesCanary"])
        self.assertIn(" :: wraps, ", self.answer["namesCanary"], "a name that wraps went unreported, so a quiet report proves nothing")

    def test_a_card_that_grows_on_an_overview_already_laid_out_scrolls_the_page_and_is_laid_out_whole(self):
        """The rows are given the page's height, so nothing but the page can make them taller: a card that grows as a
        refresh writes into it must reach the page, which measures the rows again, scrolls and gives them what they
        need. Asked from inside the grid's own layout, the page's new size reached the grid while that layout was
        still running and the cards were never laid out at it."""
        grown = self.answer["grown"]
        self.assertFalse(grown["before"], "the Overview scrolled before the card grew")
        self.assertTrue(grown["after"], "a card forty lines taller did not make the page scroll")
        self.assertGreater(grown["height"], grown["heightBefore"], "the card kept the height of its row")
        self.assertGreaterEqual(grown["height"], grown["needs"], "the card is cut off")

    def test_recently_finished_stays_whole_when_a_recovery_finishes_with_the_overview_open(self):
        """The audit fills the Overview before the page has its width, and the width arriving fits
        the names again. A recovery that finishes while the window is open rebuilds the rows on a
        page already laid out, where the width does not change: fitted before the ages were written,
        the names kept the room of the outcomes alone, and in every language measured each outcome
        and its age ended in an ellipsis until the window was resized (v0.6.4)."""
        recent = self.answer["recent"]
        self.assertEqual(sorted(recent), sorted(l10n.LOCALES))
        for locale in l10n.LOCALES:
            opened, rebuilt = recent[locale]["opened"], recent[locale]["rebuilt"]
            with self.subTest(locale=locale):
                self.assertEqual(len(opened["shown"]), 4, "the fullest snapshot shows four finished conversations")
                self.assertEqual(opened["cut"], [])
                self.assertNotEqual(rebuilt["first"], opened["first"], "the rows were not rebuilt, so nothing was asked")
                self.assertEqual(len(rebuilt["shown"]), 4)
                self.assertEqual(rebuilt["cut"], [], "an outcome and its age are cut once the rows were rebuilt")

    def test_the_strings_cache_is_used_only_for_the_installation_as_it_was(self):
        cache = self.answer["cache"]
        self.assertTrue(cache["missBeforeWrite"])
        self.assertTrue(cache["hit"], "a reply written under the current key is read back")
        self.assertTrue(cache["sameWords"])
        self.assertTrue(cache["sameKeyAgain"], "the key is stable while nothing changes")
        self.assertTrue(cache["settingsChangeKey"], "a saved Interface language must miss")
        self.assertTrue(cache["missAfterSave"])
        self.assertTrue(cache["catalogEditKeptLengthAndTime"], "the catalog edit was meant to keep its length and time")
        self.assertTrue(cache["catalogChangeKey"],
                        "a catalog corrected to a word of the same length, with the fixed time a release "
                        "archive gives every file, must miss")
        self.assertTrue(cache["languageChangeKey"], "a language asked for by the environment must miss")
        self.assertTrue(cache["hitBeforeDamage"])
        self.assertTrue(cache["missWhenDamaged"], "a cache that cannot be read is a miss, not an error")

    def test_the_strings_cache_is_kept_beside_the_settings_and_nowhere_else(self):
        """Uninstall -Purge removes config\\, and the product writes only its own config\\ and logs\\."""
        cache = self.answer["cache"]
        self.assertTrue(cache["inConfig"])
        self.assertTrue(cache["noCacheFolder"], "a cache\\ folder of its own")
        self.assertEqual(cache["configHolds"], "settings.json,strings-cache.json", "a temporary file was left behind")

    def test_a_strings_reply_is_kept_and_used_only_in_the_language_the_settings_store(self):
        cache = self.answer["cache"]
        self.assertTrue(cache["replyNamesItsLanguage"], "the probe's reply does not name the language it is for")
        self.assertTrue(cache["otherLanguageNotWritten"], "a reply for another Interface language was written")
        self.assertTrue(cache["otherLanguageNotRead"], "a reply for another Interface language was used")
        self.assertTrue(cache["unsetIsSystem"], "no Interface language stored is the system language")
        self.assertTrue(cache["absentIsSystem"], "no settings file is the system language")

    def test_a_reply_that_comes_back_after_the_settings_changed_is_not_kept(self):
        """A window's key is taken, the language is saved elsewhere before its bridge reads it,
        and later set back - the file byte for byte what it was. The reply in the other language
        must not be waiting under the old key."""
        cache = self.answer["cache"]
        self.assertTrue(cache["raceKeyBack"], "the settings were not put back as they were")
        self.assertTrue(cache["raceNotKept"], "the reply in the language saved meanwhile opens the next window")
        self.assertTrue(cache["otherSettingKeepsKey"],
                        "a save that did not touch the Interface language moved the strings cache's key")
        self.assertTrue(cache["otherSettingKeepsCache"], "and threw away words that were still right")

    def test_the_custom_message_follows_the_style_when_it_is_built_out_of_sight(self):
        window = self.answer["window"]
        self.assertEqual(window["standard"]["built"], [False, False],
                         "the Custom card and its per-kind editor kept under Standard, built while Settings was hidden")
        self.assertEqual(window["standard"]["shown"], [False, False], "and shown on Continuation")
        self.assertEqual(window["custom"]["built"], [True, True])
        self.assertEqual(window["custom"]["shown"], [True, True])

    def test_historys_thread_button_follows_its_row_while_history_is_hidden(self):
        shown_for_off, while_hidden, back, selected = self.answer["window"]["thread"]
        self.assertEqual(selected, 1, "the row the probe chose is not selected")
        self.assertTrue(shown_for_off, "offered for a conversation that is off")
        self.assertFalse(while_hidden, "still offered once the conversation is on, updated while History was hidden")
        self.assertFalse(back, "and on returning to History")

    def test_a_first_visit_to_a_page_reads_again_when_the_snapshot_is_old(self):
        fresh, stale, age_kept = self.answer["window"]["snapshot"]
        self.assertFalse(fresh, "a snapshot under two seconds old was asked for again")
        self.assertTrue(stale, "a page built on its first visit was filled from an old snapshot and nothing was read")
        self.assertTrue(age_kept, "handing a page the snapshot already held made it look new")


if __name__ == "__main__":
    unittest.main()
