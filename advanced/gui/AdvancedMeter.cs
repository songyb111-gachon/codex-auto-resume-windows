// ADVANCED-EDITION-CODE: in the advanced edition's window, never the standard one's.
//
// Codex Auto Resume - the saved accounts' usage meters, on the automatic account switch's card (v0.6.22 final; the owner's
// mock of 2026-11-08).
//
// Each meter is a groove in the Soft design's inset look - the scroll bar's well (SoftBar.TrackFill, its hairline and the
// inset recipe's depth, Soft.Body), a step deeper than the card it lies on - with the share used as a bar inside it: the
// accent below WarnAt per cent, the warning colour at WarnAt or more, and nothing at all where no reading was made. The bar
// grows from the left, and from the right where the page is mirrored right to left. In High Contrast the groove is
// Window with a WindowFrame edge, as the scroll bar's is, and the bar the theme's accent or warning colour.
//
// The card's own pieces stand here too, so AdvancedAccounts.cs keeps to the page's: the heading with Read usage at its
// right (AccountsHeading), a saved account's row with "in use" beside it in the accent (AccountsRow), under it the two
// meters - "5-hour" and "7-day" - each with its words after it (AccountsMeters), and under them, on the rows that offer
// it, Switch to this account (AccountsSwitchLine, v0.6.22 final). Every colour is the theme's; nothing is
// drawn the page does not draw already but the groove's bar.
//
// C# 5 (the in-box compiler), as the rest of the window.

using System;
using System.Collections.Generic;
using System.Drawing;
using System.Windows.Forms;

namespace CodexAutoResume
{
    /// One usage meter: a groove, and the share used inside it. `Used` is the percentage, or below zero for no reading.
    internal sealed class AccountMeter : Control
    {
        /// The percentage used from which the bar is the warning colour rather than the accent.
        internal const double WarnAt = 90.0;
        internal const int GrooveWidth = 120;
        internal const int GrooveHeight = 8;

        private double used = -1;

        internal AccountMeter()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                     ControlStyles.UserPaint | ControlStyles.ResizeRedraw, true);
            TabStop = false;
            AccessibleRole = AccessibleRole.ProgressBar;
            BackColor = Palette.Card;
            Size = new Size(Soft.Px(GrooveWidth), Soft.Px(GrooveHeight));
        }

        /// The percentage used, 0 to 100 drawn (more is a full bar), or below zero where no reading was made.
        internal double Used
        {
            get { return used; }
            set { used = value; Invalidate(); }
        }

        /// Whether a share used is drawn in the warning colour.
        internal static bool Warns(double share)
        {
            return share >= WarnAt;
        }

        /// The bar's colour for a share used: the accent, or the warning colour at WarnAt or more.
        internal static Color BarColor(double share)
        {
            return Warns(share) ? Palette.Warning : Palette.Accent;
        }

        /// The bar's width inside a groove `inner` wide: none without a reading, at least its own height above zero, and
        /// never past the groove.
        internal static int BarWidth(double share, int inner, int height)
        {
            if (share <= 0 || inner <= 0) return 0;
            int width = (int)Math.Round(inner * Math.Min(100.0, share) / 100.0);
            return Math.Min(inner, Math.Max(height, width));
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            g.Clear(Palette.Card);
            Rectangle track = new Rectangle(0, 0, Width - 1, Height - 1);
            if (track.Width <= 0 || track.Height <= 0) return;
            bool contrast = Palette.Contrast;
            float radius = track.Height / 2f;
            Soft.Body(g, track, radius, SoftBar.TrackFill(contrast, Palette.Card), SoftBar.TrackEdge(contrast), Palette.Depth);
            if (used < 0) return;                                  // no reading: the groove empty
            int inset = Soft.Hairline;
            Rectangle groove = Rectangle.Inflate(track, -inset, -inset);
            int width = BarWidth(used, groove.Width, groove.Height);
            if (width <= 0) return;
            int left = RightToLeft == RightToLeft.Yes ? groove.Right - width : groove.Left;
            Rectangle bar = new Rectangle(left, groove.Top, width, groove.Height);
            Color tone = BarColor(used);
            Soft.Body(g, bar, groove.Height / 2f, tone, tone, false);
        }
    }

    internal sealed partial class SettingsForm
    {
        /// The card's heading with `button` at its right, in one row: the heading MakeCard put first, moved into it.
        private void AccountsHeading(TableLayoutPanel card, Button button)
        {
            Control heading = card.Controls.Count > 0 ? card.Controls[0] : null;
            var row = new TableLayoutPanel();
            row.ColumnCount = 2;
            row.RowCount = 1;
            row.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
            row.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            row.AutoSize = true;
            row.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            row.Dock = DockStyle.Fill;
            row.BackColor = Card;
            row.Margin = new Padding(0);
            row.Padding = new Padding(0);
            if (heading != null)
            {
                card.Controls.Remove(heading);
                heading.Anchor = AnchorStyles.Left;
                row.Controls.Add(heading, 0, 0);
            }
            button.Anchor = AnchorStyles.Right | AnchorStyles.Top;
            button.Margin = Pad(8, 0, 0, 8);
            row.Controls.Add(button, 1, 0);
            card.Controls.Add(row);
            card.Controls.SetChildIndex(row, 0);
        }

        /// A saved account's row: its check row, with "in use" after it in the accent where it is the account signed in.
        private Control AccountsRow(CheckBox check, bool inUse)
        {
            if (!inUse) return check;
            var row = new TableLayoutPanel();
            row.ColumnCount = 2;
            row.RowCount = 1;
            row.AutoSize = true;
            row.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            row.BackColor = Card;
            row.Margin = new Padding(0);
            row.Padding = new Padding(0);
            var word = new Label();
            word.AutoSize = true;
            word.Text = Word("page.accounts.in_use", "in use");
            word.ForeColor = Palette.Accent;
            word.Anchor = AnchorStyles.Left;
            word.Margin = Pad(6, 0, 0, 0);
            row.Controls.Add(check, 0, 0);
            row.Controls.Add(word, 1, 0);
            return row;
        }

        /// Switch to this account on a line of its own under the row's meters, in from the card's edge as they are: beside the
        /// row it took the account's line's room, and that line was cut off in German, Italian, Russian, Ukrainian and
        /// Vietnamese (the layout audit, 2026-11-08).
        private Control AccountsSwitchLine(Button switchTo)
        {
            switchTo.Anchor = AnchorStyles.Left;
            switchTo.Margin = Pad(26, 0, 0, 8);
            return switchTo;
        }

        /// The two meters under a saved account's row - the five-hour window's and the weekly one's - each with its words.
        private Control AccountsMeters(Dictionary<string, object> row)
        {
            var meters = new TableLayoutPanel();
            meters.ColumnCount = 3;
            meters.RowCount = 2;
            meters.AutoSize = true;
            meters.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            meters.BackColor = Card;
            meters.Margin = Pad(26, 0, 0, 6);
            meters.Padding = new Padding(0);
            AccountsMeterLine(meters, 0, Word("page.accounts.five_hour", "5-hour"), Get(row, "five_hour") as Dictionary<string, object>);
            AccountsMeterLine(meters, 1, Word("page.accounts.weekly", "7-day"), Get(row, "weekly") as Dictionary<string, object>);
            return meters;
        }

        private void AccountsMeterLine(TableLayoutPanel meters, int line, string name, Dictionary<string, object> window)
        {
            var caption = new Label();
            caption.AutoSize = true;
            caption.Text = name;
            caption.ForeColor = Secondary;
            caption.Anchor = AnchorStyles.Left;
            caption.Margin = Pad(0, 1, 8, 1);
            var meter = new AccountMeter();
            meter.Used = window != null ? Number(window, "used") : -1;
            meter.Anchor = AnchorStyles.Left;
            meter.Margin = Pad(0, 1, 8, 1);
            var said = new Label();
            said.AutoSize = true;
            said.Text = AccountsMeterWords(window);
            said.ForeColor = Secondary;
            said.Anchor = AnchorStyles.Left;
            said.Margin = Pad(0, 1, 0, 1);
            meter.AccessibleName = name + " " + said.Text;
            meters.Controls.Add(caption, 0, line);
            meters.Controls.Add(meter, 1, line);
            meters.Controls.Add(said, 2, line);
        }
    }
}
