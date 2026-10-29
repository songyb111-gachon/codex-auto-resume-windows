// ADVANCED-EDITION-CODE: in the advanced edition's window, never the standard one's.
//
// Codex Auto Resume - the Advanced features page in the render mode (gui/WindowRender.cs), for the pictures of the
// advanced edition (build/advanced_shots.py).
//
// The render mode puts the window in each frame's state as far as the standard window goes - a page, a section, a
// scroll, a face - and hands the frame here (RenderStateNamed, a point gui/Dashboard.cs declares). A frame on this page
// shows it once this edition has answered with its words; opens the capability it names, waiting until its statement
// and what it keeps have been read and shown; for the compatibility report, writes the report and checks what sending
// would write, each from the job's replies, as a person's clicks would; shows a number of one's own the frame names in
// its choice's drop-down, as one item before Custom..., as the drop-down shows a number its dialog took - sending
// nothing (v0.6.16: the usage numbers' picture); and scrolls the open capability's column, to a part the frame names or
// by turns of the wheel. Each
// is waited for until it is drawn. A capability this tree does not have, a statement that was not read, or a report
// that was not written stops the job: a picture is never of something else.
//
// Nothing here runs in a window a person opens: only the render mode calls the point, beside a capture's event.
//
// C# 5 (the in-box compiler), as the rest of the window.

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Windows.Forms;

namespace CodexAutoResume
{
    internal sealed partial class SettingsForm
    {
        partial void RenderStateNamed(Dictionary<string, object> frame, RenderWriter writer, ref bool moved)
        {
            // v0.6.19: the Chat page, at the conversation the frame names ("chat"), once the edition and its list answered.
            if (Str(frame, "page") == ChatPageName)
            {
                if (!RenderUntil(delegate { return advancedWords != null; }))
                    throw new InvalidDataException("the advanced edition did not answer with its words");
                string thread = Str(frame, "chat");
                if (thread != null && ChatShape.IsMatch(thread) && thread != chatThread) askedChat = thread;
                if (currentPage != ChatPageName || askedChat != null)
                {
                    ShowChat();
                    moved = true;
                }
                if (!RenderUntil(delegate { return advancedListing != null && !advancedReading; }))
                    throw new InvalidDataException("the advanced features' list was not read");
                FillChatPage(null);
                return;
            }
            if (Str(frame, "page") != AdvancedPageName) return;
            if (!RenderUntil(delegate { return advancedWords != null; }))
                throw new InvalidDataException("the advanced edition did not answer with its words");
            if (currentPage != AdvancedPageName)
            {
                ShowAdvanced();
                moved = true;
            }
            if (!RenderUntil(delegate { return advancedListing != null && !advancedReading; }))
                throw new InvalidDataException("the advanced features' list was not read");
            string id = Str(frame, "capability");
            if (id != null)
            {
                if (AdvancedItem(id) == null) throw new InvalidDataException("no capability called " + id + " is in this tree");
                if (advancedOpen != id)
                {
                    OpenAdvanced(id);
                    moved = true;
                }
            }
            string open = advancedOpen;
            if (!RenderUntil(delegate { return !advancedReading && advancedThen.Count == 0 && AdvancedStatement(open) != null; }))
                throw new InvalidDataException("the statement of " + open + " was not read");
            var report = Map(frame, "report");
            if (report != null)
            {
                RenderReport(open, report);
                moved = true;
            }
            var custom = Map(frame, "custom");
            if (custom != null)
            {
                RenderCustom(Str(custom, "key"), Str(custom, "value"));
                moved = true;
            }
            string show = Str(frame, "show");
            if (show != null) RenderShow(show);
            var scroll = Map(frame, "scroll");
            if (scroll != null && advancedScroll != null)
            {
                Materialise(this);
                PerformLayout();
                object gliding;
                int notches = Convert.ToInt32(scroll["notches"], CultureInfo.InvariantCulture);
                int glide = scroll.TryGetValue("glide_ms", out gliding) && gliding != null
                    ? Convert.ToInt32(gliding, CultureInfo.InvariantCulture) : -1;
                ((ISoftScroller)advancedScroll).ScrollTo(RenderOffset(((ISoftScroller)advancedScroll).Extent,
                                                                      ((ISoftScroller)advancedScroll).Viewport, notches, glide));
            }
        }

        /// The compatibility report written for the frame's `login`, and with `check` what sending would write checked -
        /// each started as its button starts it and its job read until it ends, from the job's replies.
        private void RenderReport(string open, Dictionary<string, object> report)
        {
            if (open != ReportId) throw new InvalidDataException("a report is asked of " + open + ", which is not the report");
            if (reportBuilt == null)
            {
                reportLoginText = Str(report, "login") ?? "";
                WriteReport();
                if (!RenderUntil(ReportEnded) || reportBuilt == null)
                    throw new InvalidDataException("the report was not written: " + (reportTold ?? "no answer"));
            }
            if (Equals(Get(report, "check"), true) && reportChecked == null)
            {
                CheckReport();
                if (!RenderUntil(ReportEnded) || reportChecked == null)
                    throw new InvalidDataException("what sending would write was not checked: " + (reportTold ?? "no answer"));
            }
        }

        /// The open capability's choice `key` showing `value`, a number of one's own, as its drop-down shows one its Custom...
        /// dialog took (AdvancedUsage.cs TakeCustom): one item before Custom..., chosen - and nothing sent. A choice the
        /// open capability does not have, one that takes no number of its own, or a number outside its range stops the job.
        private void RenderCustom(string key, string value)
        {
            SoftCombo combo = advancedChoices.Find(delegate(SoftCombo each) { return Equals(each.Tag, key); });
            CustomPick pick;
            if (combo == null || !customPicks.TryGetValue(key ?? "", out pick))
                throw new InvalidDataException("no choice called " + key + " takes a number of its own on " + advancedOpen);
            int number;
            if (!int.TryParse(value ?? "", NumberStyles.None, CultureInfo.InvariantCulture, out number) ||
                number < pick.Range[0] || number > pick.Range[1])
                throw new InvalidDataException(key + " takes no number " + value);
            TakeCustom(combo, pick, number.ToString(CultureInfo.InvariantCulture));
        }

        // How far above the part a frame shows the column stops, in logical pixels: the caption or line over it shows too.
        private const int RenderShowLead = 40;

        /// The open capability's column scrolled so the part `name` names stands at its top: `report`, the report's card;
        /// `report.file`, the whole file; `report.check`, what checking found; (v0.6.16) `choices`, its Choices card. One
        /// that does not show stops the job.
        private void RenderShow(string name)
        {
            Control part = name == "report.file" ? (Control)reportFile : name == "report.check" ? reportCheck
                         : name == "report" ? (Control)reportLogin
                         : name == "choices" && advancedChoices.Count > 0 ? advancedChoices[0] : null;
            Control card = part;
            while (card != null && card.Parent != advancedStack) card = card.Parent;
            if (part == null || card == null || advancedScroll == null)
                throw new InvalidDataException("no part called " + name + " shows on " + advancedOpen);
            Materialise(this);
            PerformLayout();
            int top = name == "report" || name == "choices" ? card.Top - card.Margin.Top : InStack(part) - Px(RenderShowLead);
            ((ISoftScroller)advancedScroll).ScrollTo(Math.Max(0, top));
        }

        /// Where `control` stands in the open capability's column, from the positions of it and everything round it.
        private int InStack(Control control)
        {
            int y = 0;
            for (Control c = control; c != null && c != advancedStack; c = c.Parent) y += c.Top;
            return y;
        }

        /// Whether the report's job has ended - read now, rather than at its timer's next tick.
        private bool ReportEnded()
        {
            if (reportJob != null && !reportPolling && busy == 0) PollReport();
            return reportJob == null && busy == 0;
        }

        /// Pumps the window's messages until `done` says so, or the render mode's limit passes: false then.
        private bool RenderUntil(Func<bool> done)
        {
            var waited = Stopwatch.StartNew();
            while (waited.ElapsedMilliseconds < RenderSettleLimit)
            {
                Application.DoEvents();
                if (done()) return true;
                System.Threading.Thread.Sleep(10);
            }
            return false;
        }
    }
}
