// ADVANCED-EDITION-CODE: in the advanced edition's window, never the standard one's.
//
// Codex Auto Resume - early_reset's line on Pending (v0.6.19, issue #50).
//
// While early_reset stands on, the Recoveries view of Pending has one compact line at its top: Check now, a button to
// the capability's own card on the Advanced features page (its on/off is there and nowhere else), and what it last did -
// when it read usage early, what that reading found and whether anything was continued (the status's
// advanced.early_check, control/earlycheck.py). Check now asks for one fresh reading at once, for every waiting
// conversation together, without choosing a row (advanced-early-check); the answer says whether it was asked, folded
// into a reading just made or already asked, or not asked because the watcher is not running or nothing waits. It never
// sends: every check still runs. With early_reset off, or a status that does not carry the line, there is no line.
//
// C# 5 (the in-box compiler), as the rest of the window.

using System;
using System.Collections.Generic;
using System.Drawing;
using System.Globalization;
using System.Windows.Forms;

namespace CodexAutoResume
{
    internal sealed partial class SettingsForm
    {
        private const string EarlyResetId = "early_reset";
        private SoftFlow earlyLine;
        private Button earlyCheckButton, earlySettingsButton;
        private NoteLabel earlyNote;
        // The last status's line (advanced.early_check), and Check now's answer, shown until the next reading is made.
        private Dictionary<string, object> earlyShown;
        private string earlyAnswer;
        private double earlyAnswerAt = -1;

        /// The line, at the top of the Recoveries view, hidden until a status carries it.
        private void BuildEarlyLine(Control view)
        {
            earlyLine = new SoftFlow();
            earlyLine.Dock = DockStyle.Top;
            earlyLine.AutoSize = true;
            earlyLine.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            earlyLine.WrapContents = true;
            earlyLine.Margin = new Padding(0);
            earlyLine.Padding = Pad(0, 0, 0, 8);
            earlyLine.Visible = false;
            earlyCheckButton = MakeButton(Word("page.early.check_now", "Check now"), false, delegate { EarlyCheckNow(); });
            earlySettingsButton = MakeButton(Word("page.early.settings", "Early reset settings"), false, delegate
            {
                ShowAdvanced();
                OpenAdvanced(EarlyResetId);
            });
            foreach (Button button in new[] { earlyCheckButton, earlySettingsButton })
            {
                button.Margin = Pad(0, 0, 6, 0);
                earlyLine.Controls.Add(button);
            }
            earlyNote = Note();
            earlyLine.Controls.Add(earlyNote);
            // The words wrap within the line's width: beside the buttons where they fit, under them where they do not.
            earlyLine.SizeChanged += delegate { FitEarlyNote(); };
            view.Controls.Add(earlyLine);
        }

        private void FitEarlyNote()
        {
            if (earlyLine == null || earlyNote == null) return;
            int room = Math.Max(Px(120), earlyLine.ClientSize.Width - earlyLine.Padding.Horizontal - earlyNote.Margin.Horizontal);
            if (earlyNote.MaximumSize.Width != room) earlyNote.MaximumSize = new Size(room, 0);
        }

        /// From each snapshot: the line as the status carries it, or none.
        private void EarlyApplied(Dictionary<string, object> reply)
        {
            earlyShown = Map(Map(Map(reply, "status"), "advanced"), "early_check");
            FillEarlyLine();
        }

        private void FillEarlyLine()
        {
            if (earlyLine == null || earlyLine.IsDisposed) return;
            bool on = earlyShown != null;
            if (earlyLine.Visible != on) earlyLine.Visible = on;
            if (!on) return;
            earlyCheckButton.Text = Word("page.early.check_now", "Check now");
            earlyCheckButton.AccessibleName = earlyCheckButton.Text;
            earlySettingsButton.Text = Word("page.early.settings", "Early reset settings");
            earlySettingsButton.AccessibleName = earlySettingsButton.Text;
            double checkedAt = Get(earlyShown, "checked_at") is double ? Number(earlyShown, "checked_at") : 0;
            if (earlyAnswer != null && checkedAt != earlyAnswerAt) earlyAnswer = null;   // a new reading says it now
            FitEarlyNote();
            SetNote(earlyNote, earlyAnswer ?? EarlyText(earlyShown));
        }

        /// What the line says of the last early reading: when, what it read, and whether anything went on.
        internal string EarlyText(Dictionary<string, object> shown)
        {
            if (shown == null) return "";
            if (!(Get(shown, "checked_at") is double)) return Word("page.early.none", "Early reset check: no reading yet.");
            string time = ClockTime(Number(shown, "checked_at"));
            string read = Str(shown, "read");
            if (read == "available")
            {
                if (Equals(Get(shown, "lifted"), true))
                    return Word("page.early.lifted", "Early reset check at {time}: usage available twice. The waiting recoveries went on through every other check.", "time", time);
                string confirm = Get(shown, "confirm_at") is double ? ClockTime(Number(shown, "confirm_at")) : time;
                return Word("page.early.available_first", "Early reset check at {time}: usage available. A second reading from {confirm} confirms it; nothing was continued yet.", "time", time)
                    .Replace("{confirm}", confirm);
            }
            if (read == "still_limited")
                return Word("page.early.limited", "Early reset check at {time}: still limited. Nothing was continued.", "time", time);
            if (read == "unknown")
                return Word("page.early.unknown", "Early reset check at {time}: usage could not be told. Nothing was continued.", "time", time);
            return Word("page.early.not_read", "Early reset check at {time}: usage was not read, because another check came first. Nothing was continued.", "time", time);
        }

        /// Check now: one reading asked for at once; repeated clicks are one request (the bridge folds them).
        private void EarlyCheckNow()
        {
            double checkedAt = earlyShown != null && Get(earlyShown, "checked_at") is double ? Number(earlyShown, "checked_at") : 0;
            AdvancedCall("advanced-early-check", "{}", true, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                string answer = Str(result, "check");
                earlyAnswerAt = checkedAt;
                if (!AdvancedDone(result)) earlyAnswer = AdvancedRefusal(result);
                else if (answer == "asked") earlyAnswer = Word("page.early.asked", "Check asked: the watcher reads usage at its next look.");
                else if (answer == "coalesced") earlyAnswer = Word("page.early.coalesced", "Usage was just read, or a check is already asked: nothing more is asked.");
                else if (answer == "not_running") earlyAnswer = Word("page.early.not_running", "The watcher is not running, so nothing was checked.");
                else earlyAnswer = Word("page.early.nothing_waits", "Nothing waits for a usage reset, so there is nothing to check.");
                FillEarlyLine();
            });
        }
    }
}
