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

from codex_auto_resume import brand, l10n, machine, settings

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = ROOT / "gui" / "SettingsApp.cs"
DASHBOARD = ROOT / "gui" / "Dashboard.cs"
CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")


class RowLayoutTests(unittest.TestCase):
    def setUp(self):
        self.source = SETTINGS.read_text(encoding="utf-8")
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
        self.source = SETTINGS.read_text(encoding="utf-8")
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
        source = SETTINGS.read_text(encoding="utf-8") + DASHBOARD.read_text(encoding="utf-8")
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
        source = SETTINGS.read_text(encoding="utf-8") + DASHBOARD.read_text(encoding="utf-8")
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
        source = DASHBOARD.read_text(encoding="utf-8")
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
        source = SETTINGS.read_text(encoding="utf-8")
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
        self.source = SETTINGS.read_text(encoding="utf-8")
        start = self.source.index("private void BuildFooter()")
        self.method = self.source[start:self.source.index("private void ", start + 10)]

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
        self.source = SETTINGS.read_text(encoding="utf-8")
        start = self.source.index("private void GiveTextRoom(")
        self.method = self.source[start:self.source.index("private static void ", start)]

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
            "pending": waiting, "history": waiting + history}


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
            ["Pending unreadable", unreadable]]


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
        self.window = SETTINGS.read_text(encoding="utf-8")
        self.dashboard = DASHBOARD.read_text(encoding="utf-8")

    @staticmethod
    def method(source, signature):
        start = source.index(signature)
        return source[start:source.index("\n        }\n", start)]

    def test_the_window_opens_at_a_size_the_overview_fits_and_does_not_grow(self):
        """1000 by 600: the Overview whole in every language at every scaling (LayoutAuditTests
        holds the page to it), and the window still inside a 1920 by 1080 screen at 150%."""
        self.assertIn("ClientSize = new Size(Px(OpeningWidth), Px(OpeningHeight));", self.window)
        width = int(re.search(r"internal const int OpeningWidth = (\d+);", self.window).group(1))
        height = int(re.search(r"internal const int OpeningHeight = (\d+);", self.window).group(1))
        self.assertEqual((width, height), (1000, 600))
        # The work area of 1920 by 1080 at 150% with the taskbar, and the frame Windows 11 gives the
        # window there, in device pixels (measured with GetWindowRect: 22 across, 56 down).
        self.assertLessEqual(round(width * 1.5) + 22, 1920)
        self.assertLessEqual(round(height * 1.5) + 56, 1080 - 72)
        self.assertIn("MinimumSize = new Size(Px(800), Px(420));", self.window)
        self.assertIn("KeepOnScreen();", self.window)
        self.assertNotIn("FitToContent", self.window + self.dashboard,
                         "growing to the tallest section laid everything out twice before the first paint")

    def test_nothing_in_the_window_is_see_through(self):
        """A see-through row asked its card to repaint its background - shadow and all - for
        every repaint of the row and of each label in it: 540 card backgrounds, 11 s, in one
        measured session of v0.6.3."""
        for name, source in (("SettingsApp.cs", self.window), ("Dashboard.cs", self.dashboard)):
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
        for name, source in (("SettingsApp.cs", self.window), ("Dashboard.cs", self.dashboard)):
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
        controls = (ROOT / "gui" / "Controls.cs").read_text(encoding="utf-8")
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
        for name, source in (("SettingsApp.cs", self.window), ("Dashboard.cs", self.dashboard)):
            with self.subTest(name):
                self.assertNotRegex(source, r"\.AutoScroll\s*=\s*true")
        self.assertIn("sectionScroll.Scrolls = true;", self.window)
        self.assertIn("private readonly SoftPage sectionScroll", self.window)
        self.assertIn("sectionScroll.ScrollTo(0, false);", self.method(self.window, "private void ShowSection("))
        self.assertNotIn("AutoScrollPosition", self.window + self.dashboard)
        self.assertIn("int width = page - SoftBar.Gutter;", self.method(self.window, "private void FitSections("))
        self.assertIn("new SoftListHost(list)", self.method(self.dashboard, "private Control ListCard("))
        self.assertIn("new SoftListHost(view)", self.method(self.dashboard, "private void OpenTimeline("))
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
        controls = (ROOT / "gui" / "Controls.cs").read_text(encoding="utf-8")
        measure = self.method(controls, "private int Measure(")
        self.assertIn("else if (child.Dock == DockStyle.Fill) stacked += Math.Max(0, child.MinimumSize.Height);", measure,
                      "a filling child - the list and the explanation - counts at its minimum, so it gives way")

    def test_the_overview_pins_each_cards_action_to_the_cards_bottom_right(self):
        """v0.6.4, as the person asked: a card's heading at the top left and the button it leads to at its
        bottom right - beside the last lines where they leave room, under them where they do not, and never
        over text (LayoutAuditTests measures every language at every scaling). It replaces the row that put
        the button beside the heading."""
        overview = self.method(self.dashboard, "private Control BuildOverview(")
        self.assertEqual(overview.count("PinTo("), 4, "every Overview card has the same gap under its heading, so their facts line up")
        self.assertNotIn("HeadWith(", self.dashboard, "a card's button no longer sits beside its heading")
        self.assertIn("SoftPin nowBlock = PinTo(now, toggleButton);", overview)
        self.assertIn("nowBlock.Wraps = facts;", overview,
                      "the names of the facts give way before the button drops under them: dropped in German, it "
                      "made the Overview taller than its window")
        self.assertIn("ReserveNowWords(nowBlock);", overview)
        self.assertIn("PinTo(week, null);", overview)
        pin = self.method(self.dashboard, "private SoftPin PinTo(")
        self.assertIn("heading.Margin = Pad(0, 0, 0, Brand.CardFirstGap);", pin)
        self.assertIn("card.RowStyles.Add(new RowStyle(SizeType.Percent, 100f));", pin,
                      "the block reaches the card's inner bottom edge however tall the card beside it makes this one")
        self.assertIn("Pinned(button, card);", pin, "LayoutAudit holds the button to its card's corner")
        controls = (ROOT / "gui" / "Controls.cs").read_text(encoding="utf-8")
        block = controls[controls.index("internal sealed class SoftPin"):controls.index("internal static class NativePaint")]
        self.assertNotIn("SetChildIndex", block,
                         "the content above the button in the z-order, so a screen reader reaches it first")
        self.assertLess(block.index("Controls.Add(body);"), block.index("Controls.Add(pin);"))
        self.assertIn("region.Exclude(place);", block, "and the button shows through a hole in the content's window")
        self.assertIn("body.TabIndex = 0;", block)
        self.assertIn("pin.TabIndex = 1;", block, "read and reached by Tab after what the card says")
        self.assertIn("place = new Rectangle(width - size.Width, Math.Max(0, ClientSize.Height - size.Height), size.Width, size.Height);",
                      block)
        self.assertIn("Soft.Px(Brand.CardHeadGap)", block, "text stops the card's head gap short of the button")
        self.assertIn("Soft.Px(Brand.CardFirstGap)", block, "and a button under text is the first gap below it")
        planned = block[block.index("private int Plan("):block.index("private Size PinSize(")]
        self.assertNotRegex(planned, r"(?<!Padding)(?<!Margin)(?<!AnchorStyles)\.(?:Left|Top|Bounds|Location)\b",
                            "a height read from where the content was last laid out answered for a width the table "
                            "only asked about, and a card at 150% stayed three times as tall as its facts")
        self.assertIn("var card = Parent as SoftCard;", block,
                      "asked how wide it would be, the block answers the width of the card being measured")
        card = controls[controls.index("internal sealed class SoftCard"):controls.index("internal sealed class SoftPin")]
        self.assertIn("Measuring = proposedSize.Width > 1 && proposedSize.Width < 0x100000 ? proposedSize.Width : 0;", card)
        self.assertIn("page.Unsettle();", block, "a block given less than it needs has its page lay it out once more")
        facts = self.method(self.dashboard, "private TableLayoutPanel Facts(")
        self.assertIn("grid.Margin = new Padding(0);", facts, "the default 3 px margin never scaled")
        self.assertIn("var grid = new SoftStack();", facts, "a ground, so a button pinned beside the facts keeps its lift")
        recent = self.method(self.dashboard, "private void FillRecent(")
        self.assertIn("new LineLabel()", recent, "a long conversation name wrapped the Overview past the window")

    def test_right_now_is_planned_for_every_word_its_facts_and_its_button_are_given(self):
        """Right now is laid out for the widest words each fact and the button are ever given (SoftPin.Reserve), so it
        neither scrolls the Overview nor moves as the watcher's state changes or its last check ages; and its watcher
        and engine, whose words run longest, stand above the button, with automatic recovery on the button's line.
        LayoutAuditTests measures it in every language at every scaling."""
        overview = self.method(self.dashboard, "private Control BuildOverview(")
        order = [overview.index(name + " = Fact(facts,") for name in ("nowWatcher", "nowEngine", "nowLastCheck", "nowRecovery")]
        self.assertEqual(order, sorted(order), "watcher, engine, last check, then automatic recovery beside its button")
        reserve = self.method(self.dashboard, "private void ReserveNowWords(")
        applied = self.method(self.dashboard, "private void ApplySnapshot(")
        applied = applied[:applied.index("if (diagVersion != null)")]
        for key in sorted(set(re.findall(r'S\("((?:overview|diag)\.[a-z_]+)"', applied))):
            with self.subTest(key=key):
                self.assertIn('S("%s"' % key, reserve, "a word Right now is given that it is not planned for")
        for state in ("verified", "structurally_compatible", "incompatible", "unknown"):
            with self.subTest(engine=state):
                self.assertIn('S("engine.%s"' % state, reserve)
        self.assertIn('S("engine." + engine, engine)', applied, "the engine's word is the one its state is looked up by")
        for age in ("Age(0)", "Age(59)", "Age(59 * 60)", "Age(23 * 3600)", "Age(999 * 86400)", 'S("time.never", "never")'):
            with self.subTest(age=age):
                self.assertIn(age, reserve, "the widest word of each unit Age writes")
        toggle = self.method(self.dashboard, "private void UpdateToggle(")
        for key in re.findall(r'S\("(action\.[a-z_]+)"', toggle):
            with self.subTest(key=key):
                self.assertIn('block.Reserve(toggleButton, ', reserve)
                self.assertIn('S("%s"' % key, reserve[reserve.index("block.Reserve(toggleButton, "):])
        self.assertIn('"unknown"', self.method(self.dashboard, "private void MarkUnavailable("))
        self.assertIn('string unknown = S("diag.unknown", "unknown");', reserve)

    def test_a_page_shows_its_bar_by_what_fits_without_it_and_not_by_what_showed_before(self):
        controls = (ROOT / "gui" / "Controls.cs").read_text(encoding="utf-8")
        page = controls[controls.index("internal sealed class SoftPage"):controls.index("internal interface ISoftScroller")]
        layout = self.method(page, "protected override void OnLayout(")
        self.assertLess(layout.index("if (scrolls && !moving) overflow = false;"), layout.index("base.OnLayout(levent);"),
                        "laid out without the gutter first: kept from the last layout, it kept German's Overview scrolling")
        move = self.method(page, "private void MoveTo(")
        self.assertIn("moving = true;", move, "scrolling moves what the page holds and lays nothing out twice")
        self.assertIn("finally { moving = false; }", move)
        invalidate = self.method(controls, "internal static void Invalidate(Control container, Rectangle band)")
        self.assertIn("block.InvalidateUnder(band);", invalidate,
                      "a pinned button's ring and lift are repainted on the content windows under them")

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
        status = self.method(self.window, "private void ApplyStatus(")
        self.assertRegex(status, r'stateDot\.State = !Equals\(running, true\) \? "idle"')
        self.assertNotIn('"attention"', status)

    def test_the_strings_cache_is_checked_before_it_is_used(self):
        constructor = self.window[self.window.index("private SettingsForm(PersistentBridge bridge, Dictionary<string, object> catalog"):]
        constructor = constructor[:constructor.index("\n        }\n")]
        self.assertLess(constructor.index("StringsCache.Key(root)"), constructor.index("StringsCache.Read(root, cacheKey)"))
        self.assertLess(constructor.index("Task.Factory.StartNew"), constructor.index("Font = windowFont ?? SystemFonts.MessageBoxFont;"),
                        "the strings are asked for while the fonts and the icon are made")
        read = self.method(self.window, "internal static Dictionary<string, object> Read(")
        self.assertIn("(string)stored != key) return null;", read)
        key = self.method(self.window, "internal static string Key(")
        for part in ('"|window "', '"|settings "', '"|windows "', '"locales"', '"CODEX_AUTO_RESUME_LANG"'):
            with self.subTest(part):
                self.assertIn(part, key)

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
$out = @{ audit = @{}; pins = @{}; canary = ''; cramped = ''; cache = @{} }
$auditedPins = $form.GetField('AuditedPins', $static)
foreach ($locale in (ConvertFrom-Json $env:CAR_LOCALES)) {
    $catalog = [IO.File]::ReadAllText((Join-Path $work ('strings-' + $locale + '.json')), $utf8)
    $out.audit[$locale] = @{}
    $out.pins[$locale] = @{}
    foreach ($scale in (ConvertFrom-Json $env:CAR_SCALES)) {
        $key = ([double]$scale).ToString('0.00', [Globalization.CultureInfo]::InvariantCulture)
        $out.audit[$locale][$key] = [string]$audit.Invoke($null, [object[]]@($schema, $current, $catalog, $snapshot, [double]$scale))
        $out.pins[$locale][$key] = [int]$auditedPins.GetValue($null)
    }
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
# The same with the language unchanged: nothing is written under a key the settings have left.
[IO.File]::WriteAllText($settingsFile, '{"interface_language": "system", "theme": "light"}', $utf8)
Write-Cache $opening $reply
[IO.File]::WriteAllBytes($settingsFile, $original)
$out.cache.staleKeyNotWritten = ($null -eq (Read-Cache $opening))

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

# Each Overview card's button, over the content it is pinned beside: the windows under its lift and focus ring, whether
# a change of the button's state repaints them, and the order of the block's windows - the order Windows hands a
# screen reader. At this machine's scale, in English, never shown: a window has a handle without being on screen.
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
$out.lifts = @()
$script:repainted = @{}
foreach ($pair in (Get-Field $window 'pinned').GetEnumerator()) {
    $button = $pair.Key
    $onOverview = $false
    for ($c = $button; $null -ne $c; $c = $c.Parent) { if ($c -eq $overview) { $onOverview = $true } }
    if (-not $onOverview) { continue }
    $block = $button.Parent
    $band = [Drawing.Rectangle]$bandOf.Invoke($null, [object[]]@($button, 'control'))
    $under = New-Object Collections.ArrayList
    Get-Under $block 0 0 $band $button $under
    $script:repainted.Clear()
    foreach ($entry in $under) {
        $entry[0].add_Invalidated([Windows.Forms.InvalidateEventHandler]{
            param($sender, $e)
            $script:repainted[[Runtime.CompilerServices.RuntimeHelpers]::GetHashCode($sender)] = $e.InvalidRect
        })
    }
    # A change of state that moves nothing: the lift goes, and comes back.
    $button.Enabled = $false
    $button.Enabled = $true
    $names = @()
    $covered = @()
    foreach ($entry in $under) {
        $names += ($entry[0].GetType().Name + ' ' + $entry[1])
        $rect = $script:repainted[[Runtime.CompilerServices.RuntimeHelpers]::GetHashCode($entry[0])]
        $wanted = [Drawing.Rectangle]::Intersect($band, $entry[1])
        $wanted.Offset(-$entry[1].X, -$entry[1].Y)
        $covered += [bool]($null -ne $rect -and ([Drawing.Rectangle]$rect).Contains($wanted))
    }
    $order = @()
    for ($h = [LayoutProbe.Native]::GetWindow($block.Handle, 5); $h -ne [IntPtr]::Zero; $h = [LayoutProbe.Native]::GetWindow($h, 2)) {
        $order += [Windows.Forms.Control]::FromHandle($h).GetType().Name
    }
    $body = @($block.Controls | Where-Object { $_ -ne $button })[0]
    $overlaps = $body.Bounds.IntersectsWith($button.Bounds)
    $middle = New-Object Drawing.Point ($button.Left + [int]($button.Width / 2) - $body.Left), ($button.Top + [int]($button.Height / 2) - $body.Top)
    $beside = New-Object Drawing.Point ($button.Left - 1 - $body.Left), ($button.Top + [int]($button.Height / 2) - $body.Top)
    $region = $body.Region
    $out.lifts += ,@{ text = [string]$button.Text; under = $names; repainted = $covered; order = $order; overlaps = [bool]$overlaps
                      buttonShows = [bool]($null -ne $region -and -not $region.IsVisible($middle));
                      contentShows = [bool]($null -eq $region -or $region.IsVisible($beside)) }
}
$window.Dispose()
[IO.File]::WriteAllText((Join-Path $work 'result.json'), ($out | ConvertTo-Json -Depth 6 -Compress), $utf8)
"""

SCALES = (1.0, 1.25, 1.5, 1.75, 2.0)


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
                        *[str(ROOT / "gui" / name)
                          for name in ("SettingsApp.cs", "Dashboard.cs", "Controls.cs", "Brand.cs")]],
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
                                              "note.reopen_pending": " ".join(["The window reopens."] * 60)})
        (work / "strings-canary.json").write_text(json.dumps(reply("en", canary)), encoding="utf-8")
        cramped = dict(l10n.catalog("en"), **{"overview.waiting_count": " ".join(["{n} waiting"] * 60)})
        (work / "strings-cramped.json").write_text(json.dumps(reply("en", cramped)), encoding="utf-8")
        now = time.time()
        fullest = fullest_snapshot(now)
        (work / "snapshot.json").write_text(json.dumps(fullest, ensure_ascii=False), encoding="utf-8")
        (work / "snapshot-later.json").write_text(json.dumps(finished_while_open(fullest, now), ensure_ascii=False),
                                                  encoding="utf-8")
        (work / "states.json").write_text(json.dumps(overview_states(now), ensure_ascii=False), encoding="utf-8")
        unheard = copy.deepcopy(fullest)
        unheard["status"]["watcher"]["engine_state"] = " ".join(["a-state-this-window-has-no-word-for"] * 12)
        (work / "states-canary.json").write_text(json.dumps([["the fullest", fullest], ["an unheard-of engine", unheard]]),
                                                 encoding="utf-8")
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

    def test_the_audit_finds_what_does_not_fit(self):
        self.assertIn("Label'WWWW", self.answer["canary"],
                      "a 400-character label went unreported, so an empty report proves nothing")
        self.assertIn("reopen note at ", self.answer["canary"],
                      "a note sixty sentences long went unreported, so a quiet report on the note proves nothing")

    def test_every_pinned_button_is_at_its_bottom_right_and_over_no_text(self):
        """The Overview's three card buttons, the Custom messages' two Clear buttons and the header's Start
        button, in every language at every scaling: each within a pixel of its card's or row's inner bottom-right
        corner and over no line of text in it (their findings are in the first test's reports). This holds the
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

    def test_a_pinned_buttons_lift_and_focus_ring_are_repainted_on_the_content_under_them(self):
        """The ring and the lift run outside the button, over the content it is pinned beside, whose windows draw
        that part of them in their own backgrounds (Ground). A change of the button's state - focus, a press, being
        disabled while an action runs, Pause becoming Resume - must repaint those windows too: repainting only the
        block behind them left the ring without its top and left edges, and old pieces of it behind."""
        lifts = self.answer["lifts"]
        self.assertEqual(sorted(lift["text"] for lift in lifts), ["History", "Pause recovery", "Pending"])
        self.assertGreater(sum(len(lift["under"]) for lift in lifts), 0, "no window lies under any ring, so none was checked")
        for lift in lifts:
            with self.subTest(lift["text"]):
                self.assertEqual(lift["repainted"], [True] * len(lift["under"]),
                                 "not repainted where the ring and the lift cross them: %s" % lift["under"])

    def test_a_screen_reader_reaches_a_cards_content_before_its_pinned_button(self):
        """Windows hands a screen reader a block's windows top of the z-order first. The content is on top and read
        first, as it is seen and as Tab reaches it; the button shows through a hole in the content's window the
        button's size, so the content never paints over it."""
        for lift in self.answer["lifts"]:
            with self.subTest(lift["text"]):
                self.assertEqual(lift["order"], ["SoftStack", "SoftButton"])
                if lift["overlaps"]:
                    self.assertTrue(lift["buttonShows"], "the content's window covers the button")
                self.assertTrue(lift["contentShows"], "the content's window is cut away beside the button")

    def test_the_audit_finds_an_overview_that_would_scroll(self):
        """The fullest Overview in every language at every scaling is in the first test's empty
        reports; this is the same measurement shown a page that cannot fit."""
        self.assertIn("overview :: the page scrolls", self.answer["cramped"],
                      "a waiting count sixty lines long did not make the Overview scroll, so no report of it proves nothing")
        self.assertNotIn("pending :: the page scrolls", self.answer["cramped"])

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
        self.assertTrue(cache["staleKeyNotWritten"], "a reply was written under a key the settings had left")

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
