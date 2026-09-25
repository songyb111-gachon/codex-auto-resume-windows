// Codex Auto Resume - what holds what: stacks, rows, pages, scrolling, cards and pins.
//
// The containers the window is arranged with. Each is still the standard control underneath,
// so keyboard, focus and screen readers behave as they always did; only the painting is ours.

using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;

namespace CodexAutoResume
{
    /// A table that is a ground (see Ground): double-buffered and opaque.
    internal sealed class SoftStack : TableLayoutPanel, ISoftGround
    {
        internal SoftStack()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                     ControlStyles.UserPaint | ControlStyles.ResizeRedraw, true);
            BackColor = Palette.Canvas;
        }

        protected override void OnPaintBackground(PaintEventArgs e)
        {
            Ground.Paint(this, e);
        }
    }

    /// A grid of cards whose rows share the whole height of the page it fills (v0.6.4): every row as tall
    /// as the others where the page has room for that, and every card as tall as its row, so the Overview's
    /// cards reach from under the tabs to above the footer at whatever height the window has. As tall as their
    /// content, the person found them too wide and too short, over an empty band.
    ///
    /// It fills its page, and the page measures it at what its rows need (Needed): each row as tall as its own
    /// tallest card, measured at the narrower column's width as a table measures a card. A page with room for
    /// every row as tall as the tallest card shares all of its height alike; a shorter one gives each row what
    /// it needs and the rest to the shorter rows (Shares); one shorter still scrolls, and the rows keep what
    /// they need. Counted with every row as tall as the tallest, the Overview scrolled in any window from 598
    /// to 617 px high, where v0.6.3's fitted - and KeepOnScreen gives the window 601 on a 1920 by 1200 screen
    /// at 175% (v0.6.4, measured). What a card holds stays at its top, and a control pinned to its bottom
    /// right (SoftPin) goes down with the card's bottom edge. The gap between two rows is half under the one
    /// and half over the other (Dashboard.RowGap), so rows of one height are cards of one height.
    ///
    /// It is AutoSize, though its page decides its size: a table answers its parent's layout from its own only
    /// when it sizes itself (TableLayout returns AutoSize), and WinForms then lays the parent out once the table's
    /// own layout has finished. So a card that grows on a page already laid out has the page measure the rows
    /// again and scroll. Docked to fill, it is given the page's size whatever it asks for. Asked from inside its
    /// own layout instead, the page gave the table a new size while that layout was still running, and the
    /// table never laid its cards out at it.
    internal sealed class SoftRows : TableLayoutPanel, ISoftGround
    {
        internal SoftRows(int columns, int rows)
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                     ControlStyles.UserPaint | ControlStyles.ResizeRedraw, true);
            BackColor = Palette.Canvas;
            Dock = DockStyle.Fill;
            AutoSize = true;
            Margin = new Padding(0);
            ColumnCount = columns;
            RowCount = rows;
            for (int i = 0; i < columns; i++) ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f / columns));
            for (int i = 0; i < rows; i++) RowStyles.Add(new RowStyle(SizeType.Percent, 100f / rows));
        }

        /// How tall it must be, `width` wide, for every row to hold its own tallest card, margins and all.
        internal int Needed(int width)
        {
            int total = 0;
            foreach (int need in RowNeeds(width)) total += need;
            return Padding.Vertical + total;
        }

        /// How tall each row must be, `width` wide, to hold its tallest card, margins and all.
        private int[] RowNeeds(int width)
        {
            var needs = new int[Math.Max(1, Math.Min(RowCount, RowStyles.Count))];
            // The narrower of the columns as the table shares the width out: a card is never shorter narrower.
            int column = Math.Max(1, (width - Padding.Horizontal) / Math.Max(1, ColumnCount));
            foreach (Control child in Controls)
            {
                if (!Soft.OwnVisible(child)) continue;
                int row = GetPositionFromControl(child).Row;
                if (row < 0 || row >= needs.Length) continue;
                int room = Math.Max(1, column - child.Margin.Horizontal);
                int height = child.AutoSize ? child.GetPreferredSize(new Size(room, 0)).Height : child.Height;
                needs[row] = Math.Max(needs[row], height + child.Margin.Vertical);
            }
            return needs;
        }

        protected override void OnLayout(LayoutEventArgs levent)
        {
            // The rows' shares for the size the table is about to lay its cards out at. A share that changes asks for
            // a layout, which, asked from inside this one, does not run again: this one lays out with the new shares.
            Rectangle display = DisplayRectangle;
            float[] shares = Shares(RowNeeds(display.Width), display.Height);
            for (int i = 0; i < shares.Length && i < RowStyles.Count; i++)
                if (RowStyles[i].Height != shares[i]) RowStyles[i].Height = shares[i];
            base.OnLayout(levent);
        }

        /// The weights of the rows' percent styles, for rows that need `needs` pixels in `room`:
        ///   * alike, where every row can be as tall as the tallest needs;
        ///   * what each row needs, where there is no more than that - a page with less scrolls, and a table
        ///     given less on the way shares it in proportion;
        ///   * between the two, the rows that need more than an even share of what the others leave keep what they
        ///     need, and the others share the rest alike, so the shorter rows grow toward the taller and none is
        ///     given less than it needs. In whole pixels that add up to `room`, so the table's shares are exact.
        internal static float[] Shares(int[] needs, int room)
        {
            int rows = needs.Length, tallest = 0, total = 0;
            foreach (int need in needs)
            {
                tallest = Math.Max(tallest, need);
                total += need;
            }
            var shares = new float[rows];
            if (total <= 0 || (long)tallest * rows <= room)
            {
                for (int i = 0; i < rows; i++) shares[i] = 100f / rows;
                return shares;
            }
            if (room <= total)
            {
                for (int i = 0; i < rows; i++) shares[i] = needs[i];
                return shares;
            }
            var keeps = new bool[rows];
            int left = room, sharing = rows;
            while (sharing > 1)
            {
                int most = -1;
                for (int i = 0; i < rows; i++)
                    if (!keeps[i] && (most < 0 || needs[i] > needs[most])) most = i;
                if ((long)needs[most] * sharing <= left) break;
                keeps[most] = true;
                left -= needs[most];
                sharing--;
            }
            int even = left / sharing, over = left - even * sharing;
            for (int i = 0; i < rows; i++)
            {
                if (keeps[i])
                {
                    shares[i] = needs[i];
                    continue;
                }
                shares[i] = even + (over > 0 ? 1 : 0);
                if (over > 0) over--;
            }
            return shares;
        }

        protected override void OnPaintBackground(PaintEventArgs e)
        {
            Ground.Paint(this, e);
        }
    }

    /// A page that is a ground (see Ground): double-buffered and opaque. A page that `Scrolls` moves
    /// what it holds up and down when that is taller than the page, on the soft scroll bar - never
    /// on Windows' own.
    ///
    /// Windows draws its bar in the page's frame, in the system's grey, and nothing a window does to
    /// it makes it the window's material. So the page keeps its own offset. Its DisplayRectangle -
    /// the rectangle WinForms lays every docked and anchored child out in - starts that far above its
    /// top, and while there is more than fits it is narrower by the bar's gutter, so nothing is drawn
    /// under the bar. How tall what it holds is:
    ///   * a child docked to the top or the bottom counts at its height;
    ///   * a child that fills counts at no more than its MinimumSize, so a page a list fills -
    ///     Pending, History - scrolls only when the rest of it no longer fits at all;
    ///   * a grid whose rows share the page (SoftRows) counts at what its rows need, so the Overview
    ///     fills the page it fits and scrolls only when its cards need more;
    ///   * a child placed where it is counts to its bottom.
    /// The wheel scrolls it over anything in it that does not take the wheel for itself (a drop-down
    /// or a number hands it on: Soft.PassWheel), and a control the keyboard moves to is scrolled into
    /// view, as Windows' own scrolling panel does.
    internal sealed class SoftPage : Panel, ISoftGround, ISoftScroller
    {
        // Whether the lift of what it holds may cross out of it follows whether it is scrolling
        // (Ground.SeeThrough), so when that changes the grounds around it are painted again.
        private bool scrolling;
        private bool scrolls, overflow, moving, unsettled;
        private int offset, extent, glideTarget;
        private SoftScrollBar bar;
        private Timer glide;
        private EventHandler entered;
        private ControlEventHandler added, removed;

        internal SoftPage()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                     ControlStyles.UserPaint | ControlStyles.ResizeRedraw, true);
            BackColor = Palette.Canvas;
        }

        /// Whether it scrolls what it holds up and down. Turned on once, when the page is built.
        internal bool Scrolls
        {
            get { return scrolls; }
            set
            {
                if (!value || scrolls) return;
                bar = new SoftScrollBar(this, this);
                glide = new Timer();
                glide.Interval = SoftBar.GlideInterval;
                glide.Tick += delegate { Glide(); };
                entered = delegate(object sender, EventArgs e) { Entered(sender as Control); };
                added = delegate(object sender, ControlEventArgs e) { Follow(e.Control); };
                removed = delegate(object sender, ControlEventArgs e) { Unfollow(e.Control); };
                scrolls = true;
                ControlAdded += added;
                ControlRemoved += removed;
                foreach (Control child in Controls) Follow(child);
                PerformLayout();
            }
        }

        /// Whether it holds more than fits, so the bar is showing.
        internal bool Overflowing { get { return scrolls && overflow; } }

        /// Asks for what it holds to be laid out once more before its layout ends: something in it (SoftPin)
        /// was laid out with less room than it needs, measured before what it holds changed under it.
        internal void Unsettle()
        {
            unsettled = true;
        }

        /// How far down it is scrolled, in pixels.
        internal int Offset { get { return offset; } }

        /// How tall what it holds is, its padding included, in pixels.
        internal int Extent { get { return extent; } }

        internal SoftScrollBar Bar { get { return bar; } }

        int ISoftScroller.Extent { get { return extent; } }
        int ISoftScroller.Viewport { get { return ClientSize.Height; } }
        int ISoftScroller.Offset { get { return offset; } }
        void ISoftScroller.ScrollTo(int target) { ScrollTo(target, false); }
        void ISoftScroller.Page(int direction)
        {
            ScrollTo(offset + direction * SoftBar.PageStep(ClientSize.Height, Soft.Px(SoftBar.Line)), false);
        }

        public override Rectangle DisplayRectangle
        {
            get
            {
                if (!scrolls) return base.DisplayRectangle;
                Size client = ClientSize;
                int gutter = overflow ? SoftBar.Gutter : 0;
                return new Rectangle(Padding.Left, Padding.Top - offset,
                                     Math.Max(0, client.Width - Padding.Horizontal - gutter),
                                     Math.Max(0, Math.Max(client.Height, extent) - Padding.Vertical));
            }
        }

        protected override void OnPaintBackground(PaintEventArgs e)
        {
            Ground.Paint(this, e);
            if (Overflowing) bar.Paint(e.Graphics);
        }

        protected override void OnLayout(LayoutEventArgs levent)
        {
            // Laid out without the bar's gutter first, whatever showed before - except while it only moves
            // what it holds (MoveTo), which changes nothing it measures.
            if (scrolls && !moving) overflow = false;
            base.OnLayout(levent);
            if (scrolls) Settle(levent);
            bool now = Ground.Scrolling(this);
            if (now == scrolling) return;
            scrolling = now;
            Form form = FindForm();
            if (form != null && form.IsHandleCreated) form.Invalidate(true);
        }

        // Measures what it holds and lays it out again until that agrees with the offset and the bar: the
        // gutter narrows what fills the width, which can only make it taller, so it settles in two passes at
        // most once the bar has appeared or gone. It starts without the gutter (OnLayout), so whether the bar
        // shows follows the page's size and what it holds, never what showed before: started from the last
        // layout's gutter, the Overview's cards, narrower by it, wrapped taller than a page they fitted
        // without it, and the bar never went (v0.6.4, measured: German at 150%, 617 px in 598, where the same
        // page grown into that size measured 586).
        private void Settle(LayoutEventArgs levent)
        {
            for (int pass = 0; pass < 4; pass++)
            {
                if (unsettled)
                {
                    // Something in it was given less room than it needs after its row was measured: what it
                    // holds is laid out again, which measures it again.
                    unsettled = false;
                    foreach (Control child in Controls)
                        if (Soft.OwnVisible(child)) child.PerformLayout();
                }
                int measured = Measure();
                int viewport = ClientSize.Height;
                bool over = viewport > 0 && measured > viewport;
                int clamped = over ? Math.Max(0, Math.Min(measured - viewport, offset)) : 0;
                if (measured == extent && over == overflow && clamped == offset) break;
                extent = measured;
                overflow = over;
                offset = clamped;
                base.OnLayout(levent);
            }
            if (glideTarget > offset && !overflow) glideTarget = offset;
            int margin = Soft.Px(SoftBar.TrackMargin);
            bar.Track = overflow
                ? new Rectangle(ClientSize.Width - margin - Soft.Px(SoftBar.TrackWidth), margin,
                                Soft.Px(SoftBar.TrackWidth), Math.Max(0, ClientSize.Height - 2 * margin))
                : Rectangle.Empty;
        }

        private int Measure()
        {
            Rectangle display = DisplayRectangle;
            int stacked = 0, placed = 0;
            foreach (Control child in Controls)
            {
                if (!Soft.OwnVisible(child)) continue;
                if (child.Dock == DockStyle.Top || child.Dock == DockStyle.Bottom) stacked += child.Height;
                else if (child is SoftRows && child.Dock == DockStyle.Fill)
                    stacked += Math.Max(Math.Max(0, child.MinimumSize.Height), ((SoftRows)child).Needed(display.Width));
                else if (child.Dock == DockStyle.Fill) stacked += Math.Max(0, child.MinimumSize.Height);
                else if (child.Dock == DockStyle.None) placed = Math.Max(placed, child.Bottom - display.Top);
            }
            return Padding.Vertical + Math.Max(stacked, placed);
        }

        /// Scrolls to `target` pixels down, as far as there is to scroll. With `animate` it glides
        /// there, unless motion is reduced, the design does not glide (Soft.ControlsStill) or it is not
        /// on screen; otherwise it is there at once.
        internal void ScrollTo(int target, bool animate)
        {
            if (!scrolls) return;
            int range = overflow ? Math.Max(0, extent - ClientSize.Height) : 0;
            target = Math.Max(0, Math.Min(range, target));
            glideTarget = target;
            if (animate && !Soft.ControlsStill && IsHandleCreated && Soft.Shown(this))
            {
                if (!glide.Enabled) glide.Start();
                return;
            }
            glide.Stop();
            MoveTo(target);
        }

        /// Whether it is gliding toward an offset rather than standing at one.
        internal bool Gliding { get { return glide != null && glide.Enabled; } }

        private void MoveTo(int value)
        {
            if (value == offset) return;
            offset = value;
            // The children move with their pixels; the page's own ground - its padding, the shadows
            // in it, the bar - is painted again. Only moved: laid out without the gutter first, every
            // frame of a glide would lay a page of cards out twice at two widths.
            moving = true;
            try { PerformLayout(); }
            finally { moving = false; }
            Invalidate(false);
        }

        private void Glide()
        {
            int next = SoftBar.GlideStep(offset, glideTarget);
            MoveTo(next);
            if (next == glideTarget || !Soft.Shown(this)) glide.Stop();
        }

        /// Scrolls by one turn of the wheel, `delta` as Windows reports it. False when there is
        /// nothing to scroll that way, so the turn goes on to whatever holds the page.
        internal bool Wheel(int delta)
        {
            if (!Overflowing) return false;
            int from = Gliding ? glideTarget : offset;
            int step = SoftBar.WheelStep(delta, SystemInformation.MouseWheelScrollLines, Soft.Px(SoftBar.Line), ClientSize.Height);
            int target = Math.Max(0, Math.Min(extent - ClientSize.Height, from + step));
            if (target == from) return false;
            ScrollTo(target, true);
            return true;
        }

        // A turn over the page, or over a child that did not take it: Windows hands a wheel message a
        // window does not use to its parent, so this sees both.
        protected override void OnMouseWheel(MouseEventArgs e)
        {
            base.OnMouseWheel(e);
            var handled = e as HandledMouseEventArgs;
            if (handled != null && handled.Handled) return;
            if (Wheel(e.Delta) && handled != null) handled.Handled = true;
        }

        /// Scrolls just far enough that `control`, somewhere in the page, is in view with a little of
        /// the page around it - or its top, when it is taller than the page.
        internal void Reveal(Control control)
        {
            if (!Overflowing || control == null) return;
            int top = 0;
            Control c = control;
            for (; c != null && c != this; c = c.Parent) top += c.Top;
            if (c == null) return;
            top += offset;
            ScrollTo(SoftBar.IntoView(offset, top, top + control.Height, ClientSize.Height,
                                      Soft.Px(SoftBar.RevealRoom), extent), false);
        }

        // Focus arriving anywhere in the page. From the keyboard only: a click on a control half out of
        // view is where the pointer is, and scrolling it away from under the pointer loses the click.
        // Enter is raised for each container on the way down as well, so what is revealed is the
        // control the window's focus is actually on.
        private void Entered(Control control)
        {
            if (!Overflowing || Control.MouseButtons != MouseButtons.None) return;
            Form form = FindForm();
            Control active = form != null ? form.ActiveControl : null;
            for (var container = active as ContainerControl; container != null && container.ActiveControl != null;
                 container = active as ContainerControl)
                active = container.ActiveControl;
            Reveal(active != null && Contains(active) ? active : control);
        }

        private void Follow(Control control)
        {
            if (control == null) return;
            control.Enter += entered;
            control.ControlAdded += added;
            control.ControlRemoved += removed;
            foreach (Control child in control.Controls) Follow(child);
        }

        private void Unfollow(Control control)
        {
            if (control == null) return;
            control.Enter -= entered;
            control.ControlAdded -= added;
            control.ControlRemoved -= removed;
            foreach (Control child in control.Controls) Unfollow(child);
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing && glide != null) { glide.Stop(); glide.Dispose(); }
            base.Dispose(disposing);
        }
    }

    /// What the soft scroll bar scrolls: a page of controls, or a list's rows.
    internal interface ISoftScroller
    {
        /// How long all of it is, how much shows at once, and how far along the view is - in one
        /// unit: pixels for a page, rows for a list.
        int Extent { get; }
        int Viewport { get; }
        int Offset { get; }

        void ScrollTo(int offset);

        /// A page toward the start (-1) or the end (1).
        void Page(int direction);
    }

    /// The soft scroll bar's measurements and drawing: a thin well - the inset recipe, with its hairline -
    /// and in it a raised pill, the control recipe's material and lift, as the panel's switch holds its
    /// knob. Sizes are logical pixels.
    ///
    /// 12 across: thin beside the cards, and still a target as wide as a check box's mark; the whole
    /// gutter, 18 across, answers the pointer. The pill is 8 across, inside a 2-pixel groove, and never
    /// shorter than 32. Under the pointer and while it is dragged its edge darkens a step and a step
    /// more. In High Contrast the well is Window with a WindowFrame edge and the pill GrayText, or
    /// Highlight under the pointer and while dragged, with no shadow at all.
    internal static class SoftBar
    {
        internal const int TrackWidth = 12;
        internal const int ThumbInset = 2;
        internal const int TrackMargin = 3;
        internal const int MinThumb = 32;
        /// A wheel line: three of them are 99 px, what the panel's page moves for one notch.
        internal const int Line = 33;
        /// The room kept around a control scrolled into view.
        internal const int RevealRoom = 16;
        internal const int GlideInterval = 15;

        /// The strip a page keeps free for the bar while it shows, in device pixels.
        internal static int Gutter
        {
            get { return Soft.Px(TrackWidth + 2 * TrackMargin); }
        }

        /// Where the thumb starts along a track `track` long, and how long it is, for `extent` of which
        /// `viewport` shows, scrolled `offset` along. Proportional, never under `minimum`.
        internal static void Thumb(int track, int extent, int viewport, int offset, int minimum, out int start, out int length)
        {
            start = 0;
            length = Math.Max(0, track);
            if (track <= 0 || extent <= viewport || viewport <= 0) return;
            length = (int)Math.Round((double)track * viewport / extent);
            length = Math.Min(track, Math.Max(Math.Min(minimum, track), length));
            int range = extent - viewport;
            start = (int)Math.Round((double)(track - length) * Math.Max(0, Math.Min(range, offset)) / range);
        }

        /// The offset a thumb `length` long standing at `start` along the track stands for.
        internal static int OffsetAt(int track, int extent, int viewport, int length, int start)
        {
            int travel = track - length, range = extent - viewport;
            if (travel <= 0 || range <= 0) return 0;
            return (int)Math.Round((double)range * Math.Max(0, Math.Min(travel, start)) / travel);
        }

        /// How far one wheel message scrolls: `lines` lines of `line` for each notch of 120, or pages
        /// when Windows is set to scroll a screen at a time (`lines` below zero). A turn up is negative.
        internal static int WheelStep(int delta, int lines, int line, int viewport)
        {
            double amount = lines < 0 ? PageStep(viewport, line) : (double)lines * line;
            return -(int)Math.Round(delta * amount / 120.0);
        }

        /// A page: what shows, less a line kept in view from the page before.
        internal static int PageStep(int viewport, int line)
        {
            return Math.Max(Math.Max(1, line), viewport - line);
        }

        /// The offset that shows `top` to `bottom` of the content with `margin` around it, moving as
        /// little as it can; the top when it is taller than what shows.
        internal static int IntoView(int offset, int top, int bottom, int viewport, int margin, int extent)
        {
            int target = offset;
            if (bottom - top + 2 * margin > viewport || top - margin < offset) target = top - margin;
            else if (bottom + margin > offset + viewport) target = bottom + margin - viewport;
            return Math.Max(0, Math.Min(Math.Max(0, extent - viewport), target));
        }

        /// One frame of a glide from `from` toward `to`: a third of the way, and the rest at the end.
        internal static int GlideStep(int from, int to)
        {
            int left = to - from;
            if (Math.Abs(left) <= 2) return to;
            int step = (int)Math.Round(left * 0.35);
            return from + (step == 0 ? Math.Sign(left) : step);
        }

        // States: 0 resting, 1 under the pointer, 2 dragged. The brand half is the theme's (Tokens).
        /// The well the bar runs in, for the ground it is drawn on. Everywhere but in a well that is the
        /// `inset` groove the design gives a track; in one - the message box, whose own ground is `inset` -
        /// an inset track is the ground, and the bar would be a pill floating on nothing. There it is the
        /// card's colour instead, so the groove is still a step away from what surrounds it.
        internal static Color TrackFill(bool contrast, Color ground)
        {
            if (contrast) return SystemColors.Window;
            return Soft.Near(ground, Tokens.Inset) ? Tokens.Surface : Tokens.Inset;
        }

        internal static Color TrackEdge(bool contrast) { return contrast ? SystemColors.WindowFrame : Tokens.Line; }

        internal static Color ThumbFill(int state, bool contrast)
        {
            if (contrast) return state == 0 ? SystemColors.GrayText : SystemColors.Highlight;
            return Tokens.Raised;
        }

        internal static Color ThumbEdge(int state, bool contrast)
        {
            if (contrast) return ThumbFill(state, true);
            return state == 2 ? Soft.Mix(Tokens.Line, Tokens.Muted, 0.6)
                 : state == 1 ? Soft.Mix(Tokens.Line, Tokens.Muted, 0.35) : Tokens.Line;
        }

        /// The bar in `track`, standing or lying: its ends are round whichever way it runs (v0.6.5, when a
        /// list's bar across its bottom was added).
        internal static void Draw(Graphics g, Rectangle track, Rectangle thumb, int state, Color ground)
        {
            if (track.Width <= 0 || track.Height <= 0) return;
            bool contrast = Palette.Contrast;
            float radius = Math.Min(track.Width, track.Height) / 2f;
            // The well's inset shadow and the thumb's lift are depth: neither in High Contrast nor in a flat design.
            Soft.Body(g, track, radius, TrackFill(contrast, ground), TrackEdge(contrast), Palette.Depth);
            if (thumb.Width <= 0 || thumb.Height <= 0) return;
            float knob = Math.Min(thumb.Width, thumb.Height) / 2f;
            if (Palette.Depth)
            {
                // The pill's lift, kept in the groove: it rests in the well rather than floating over
                // the page, and its shadow never covers the well's own edge.
                int hairline = Soft.Hairline;
                Rectangle groove = Rectangle.Inflate(track, -hairline, -hairline);
                GraphicsState saved = g.Save();
                using (GraphicsPath path = Soft.Rounded(groove, Math.Max(0f, radius - hairline)))
                    g.SetClip(path, CombineMode.Intersect);
                Elevation.StampOuter(g, thumb, "control", knob, groove);
                g.Restore(saved);
            }
            Soft.Body(g, thumb, knob, ThumbFill(state, contrast), ThumbEdge(state, contrast), false);
        }
    }

    /// The soft scroll bar's behaviour, on the control it is drawn in: dragging the thumb, a press on
    /// the track paging toward the pointer and repeating while held, and the step darker edge under the
    /// pointer. It is no window of its own - the host paints it (Paint) in a strip nothing else covers -
    /// so there is nothing to focus and nothing between the host and its children.
    ///
    /// It stands at the right of what it scrolls, or - `across`, v0.6.5 - lies along its bottom and
    /// scrolls it sideways: a list whose columns are wider than it is, in a narrow window. The same
    /// well and pill either way; only the axis changes.
    internal sealed class SoftScrollBar
    {
        private readonly Control host;
        private readonly ISoftScroller scroller;
        private readonly bool across;
        private readonly Timer repeat = new Timer();
        private Rectangle track;
        private bool hover, dragging;
        private int grab, pointer, direction;

        internal SoftScrollBar(Control host, ISoftScroller scroller) : this(host, scroller, false) { }

        internal SoftScrollBar(Control host, ISoftScroller scroller, bool across)
        {
            this.host = host;
            this.scroller = scroller;
            this.across = across;
            host.MouseDown += OnMouseDown;
            host.MouseMove += OnMouseMove;
            host.MouseUp += OnMouseUp;
            host.MouseLeave += delegate { if (!dragging) Hover(false); };
            host.MouseCaptureChanged += delegate { if (!host.Capture) Release(); };
            repeat.Tick += delegate { repeat.Interval = 50; Page(); };
            host.Disposed += delegate { repeat.Dispose(); };
        }

        /// The track, in the host's coordinates; empty while there is nothing to scroll.
        internal Rectangle Track
        {
            get { return track; }
            set
            {
                if (track == value) return;
                Invalidate();
                track = value;
                if (track.IsEmpty) { hover = false; Release(); }
                Invalidate();
            }
        }

        /// What answers the pointer: the track and the margins either side of it.
        internal Rectangle HitArea
        {
            get
            {
                if (track.IsEmpty) return Rectangle.Empty;
                int margin = Soft.Px(SoftBar.TrackMargin);
                return Rectangle.Inflate(track, margin, margin);
            }
        }

        internal Rectangle Thumb
        {
            get
            {
                if (track.IsEmpty) return Rectangle.Empty;
                int inset = Soft.Px(SoftBar.ThumbInset), start, length;
                SoftBar.Thumb(Along(track) - 2 * inset, scroller.Extent, scroller.Viewport, scroller.Offset,
                              Soft.Px(SoftBar.MinThumb), out start, out length);
                if (across)
                    return new Rectangle(track.X + inset + start, track.Y + inset, length, Math.Max(0, track.Height - 2 * inset));
                return new Rectangle(track.X + inset, track.Y + inset + start, Math.Max(0, track.Width - 2 * inset), length);
            }
        }

        /// Whether it lies along the bottom and scrolls sideways.
        internal bool Across { get { return across; } }

        /// 0 resting, 1 under the pointer, 2 dragged.
        internal int State { get { return dragging ? 2 : hover ? 1 : 0; } }

        // Lengths and positions along the axis it scrolls.
        private int Along(Rectangle box) { return across ? box.Width : box.Height; }
        private int Start(Rectangle box) { return across ? box.X : box.Y; }
        private int End(Rectangle box) { return across ? box.Right : box.Bottom; }
        private int Along(MouseEventArgs e) { return across ? e.X : e.Y; }

        internal void Paint(Graphics g)
        {
            if (!track.IsEmpty) SoftBar.Draw(g, track, Thumb, State, Ground.Colour(host));
        }

        internal void Invalidate()
        {
            if (!track.IsEmpty && host.IsHandleCreated) host.Invalidate(HitArea, false);
        }

        private void OnMouseDown(object sender, MouseEventArgs e)
        {
            if (e.Button != MouseButtons.Left || !HitArea.Contains(e.Location)) return;
            Rectangle thumb = Thumb;
            host.Capture = true;
            int at = Along(e);
            if (at >= Start(thumb) && at < End(thumb))
            {
                dragging = true;
                grab = at - Start(thumb);
                Invalidate();
                return;
            }
            pointer = at;
            direction = at < Start(thumb) ? -1 : 1;
            Page();
            // Windows' own delay before a held press repeats, then a page every 50 ms.
            repeat.Interval = (SystemInformation.KeyboardDelay + 1) * 250;
            repeat.Start();
        }

        private void OnMouseMove(object sender, MouseEventArgs e)
        {
            if (dragging)
            {
                int inset = Soft.Px(SoftBar.ThumbInset);
                Rectangle thumb = Thumb;
                scroller.ScrollTo(SoftBar.OffsetAt(Along(track) - 2 * inset, scroller.Extent, scroller.Viewport, Along(thumb),
                                                   Along(e) - grab - Start(track) - inset));
                Invalidate();
                return;
            }
            if (repeat.Enabled) pointer = Along(e);
            Hover(HitArea.Contains(e.Location));
        }

        private void OnMouseUp(object sender, MouseEventArgs e)
        {
            Release();
            host.Capture = false;
            Hover(HitArea.Contains(e.Location));
        }

        // A page toward where the track was pressed, until the thumb has reached the pointer.
        private void Page()
        {
            Rectangle thumb = Thumb;
            if (thumb.IsEmpty || (direction < 0 ? Start(thumb) <= pointer : End(thumb) > pointer))
            {
                repeat.Stop();
                return;
            }
            scroller.Page(direction);
            Invalidate();
        }

        private void Release()
        {
            repeat.Stop();
            if (!dragging) return;
            dragging = false;
            Invalidate();
        }

        private void Hover(bool over)
        {
            if (hover == over) return;
            hover = over;
            Invalidate();
        }
    }

    /// A row of buttons that is a ground (see Ground): double-buffered and opaque.
    internal sealed class SoftFlow : FlowLayoutPanel, ISoftGround
    {
        internal SoftFlow()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                     ControlStyles.UserPaint | ControlStyles.ResizeRedraw, true);
            BackColor = Palette.Canvas;
        }

        protected override void OnPaintBackground(PaintEventArgs e)
        {
            Ground.Paint(this, e);
        }
    }

    /// A card: the window's own material, lifted by the ground it stands on. The card IS the
    /// layout panel, as the old one was, because a Panel wrapping a docked AutoSize table measures
    /// to nothing; and it is the ground of whatever it holds.
    internal sealed class SoftCard : TableLayoutPanel, ISoftLifted, ISoftGround
    {
        private readonly LiftTracker tracker;

        internal SoftCard()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                     ControlStyles.UserPaint | ControlStyles.ResizeRedraw, true);
            BackColor = Palette.Card;
            tracker = new LiftTracker(this, "card");
        }

        /// Zero. A card keeps no band inside itself for its shadow any more - the ground around
        /// it draws the shadow - so nothing needs to add one to its padding.
        internal static int Room { get { return 0; } }

        string ISoftLifted.Lift { get { return "card"; } }
        float ISoftLifted.Radius { get { return Soft.PxF(Palette.RadiusCard); } }
        Rectangle ISoftLifted.Face { get { return ClientRectangle; } }
        bool ISoftLifted.Ring { get { return false; } }

        internal LiftTracker Tracker { get { return tracker; } }

        /// The width the card is being measured at, while a table measures it; 0 otherwise. A table
        /// measures a card by asking what it holds how wide it would be and how tall it is that wide,
        /// never at the width it is measuring the card at - and a block that fills its card and wraps
        /// or drops its button by width (SoftPin) is only as wide as the card (SoftPin.GetPreferredSize).
        internal int Measuring { get; private set; }

        public override Size GetPreferredSize(Size proposedSize)
        {
            int before = Measuring;
            Measuring = proposedSize.Width > 1 && proposedSize.Width < 0x100000 ? proposedSize.Width : 0;
            try { return base.GetPreferredSize(proposedSize); }
            finally { Measuring = before; }
        }

        protected override void OnPaintBackground(PaintEventArgs e)
        {
            float radius = Soft.PxF(Palette.RadiusCard);
            Ground.PaintBehind(this, e.Graphics, ClientRectangle, radius);
            // The card's own ground, and in dark its one-pixel top light inside the hairline.
            Soft.Body(e.Graphics, ClientRectangle, radius, Palette.Card, Palette.Line, "card");
            if (Palette.AccentBar) Bar(e.Graphics, ClientRectangle, radius);
            Ground.Stamps(this, e.Graphics, e.ClipRectangle);
        }

        /// Classic's mark (v0.6.10, v0.6.2's card): an AccentBar-wide bar in the accent just inside the left
        /// hairline of a body filling `face`, from its top to its bottom and following its corners. Paint only: it
        /// lies over the card's own ground, in the card's padding, and nothing is laid out for it.
        internal static void Bar(Graphics g, Rectangle face, float radius)
        {
            int hairline = Soft.Hairline;
            Rectangle inner = Rectangle.Inflate(face, -hairline, -hairline);
            if (inner.Width <= 0 || inner.Height <= 0) return;
            GraphicsState state = g.Save();
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.PixelOffsetMode = PixelOffsetMode.Half;
            // The body's inner shape, filled where the bar is: its corners drawn as smoothly as the card's own, and
            // its right edge a whole pixel.
            g.SetClip(new Rectangle(inner.X, inner.Y, Math.Min(inner.Width, Soft.Px(Brand.AccentBar)), inner.Height), CombineMode.Intersect);
            using (GraphicsPath shape = Soft.Rounded(inner, Math.Max(0f, radius - hairline)))
                g.FillPath(Soft.Fill(Palette.Accent), shape);
            g.Restore(state);
        }
    }

    /// What a card holds under its heading, with the one control the card leads to pinned to its
    /// bottom right (v0.6.4): the control's right edge on the block's right edge and its bottom on the
    /// block's bottom - and the block fills its card's last row, so that is the card's inner
    /// bottom-right corner however tall the card is stretched beside another.
    ///
    /// The content keeps the whole width. Where nothing in it reaches into the control's column - the
    /// control's width and the card's head gap in from the right - the control sits beside the last
    /// lines, as it does on the panel. Where something does, the text gives way first: the names of a
    /// grid of facts (Wraps) wrap, so its values start further left and clear the column. That costs a
    /// line, where putting the control under the facts costs a control and a gap - and in German that
    /// made the Overview taller than its window. Only where wrapping does not clear the column, or costs
    /// more, does the block grow, until the control is under the lowest thing in its column with the
    /// card's first gap between them. Text never runs under it. A control that is hidden takes no room.
    /// A block given more height than that - its card stretched beside a taller one, or down a page whose
    /// rows share its height (SoftRows) - keeps the names whole when the control fits under them.
    ///
    /// Where the content's lines are is worked out (Model) - never read from where its controls happen
    /// to be. A table asks a block how tall it is at widths it never gives it - 1, 0, a column's width on
    /// the way to the real one - and keeps the answers, and a height read from the content as last laid
    /// out answered for the wrong width: a card at 150% stayed three times as tall as its facts.
    ///
    /// A line whose words change with what it shows - a fact's value, the control's own words - can be
    /// planned for the widest words it is ever given (Reserve), so the block is laid out the same whatever
    /// it says now. Planned for the words on screen, Right now wrapped, or dropped its button, as the
    /// watcher's state changed, and every refresh of "Last check" could move it: in French and German the
    /// Overview opened on a watcher in trouble scrolled (v0.6.4, measured).
    ///
    /// The content comes first and the control last, which is the order they are seen in, the order Tab
    /// reaches them, and - the content's window above the control's in the z-order - the order Windows
    /// hands a screen reader. The content's window has a hole the control's size where the control is,
    /// so it never paints over it. The block is a ground in the card's colour, seen through (see Ground),
    /// and so are the content's tables: the control's lift and focus ring are drawn around it on all of
    /// them, and repainted on all of them when it changes (InvalidateUnder).
    internal sealed class SoftPin : Panel, ISoftGround
    {
        private readonly Control body, pin;
        private readonly PinLayout engine = new PinLayout();
        private TableLayoutPanel wraps;
        // How wide the first column of `wraps` is with nothing wrapped, as the last Model found it.
        private int naturalFirst;
        // Measures a name as it would be with a narrower column, or a line with other words, without touching it.
        private static readonly Label twin = new Label();
        private static Button twinButton;
        // The words each line, and the control, are planned for (Reserve), and the last size worked out for each.
        private readonly Dictionary<Control, string[]> reserved = new Dictionary<Control, string[]>();
        private readonly Dictionary<Control, Reservation> planned = new Dictionary<Control, Reservation>();
        // The hole in the content's window, in its coordinates: where the control is.
        private Rectangle hole;
        // The width it was last laid out at; 0 before that.
        private int arranged;

        private struct Reservation
        {
            internal int Room;
            internal Font Font;
            internal Size Size;
        }

        internal SoftPin(Control body, Control pin)
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                     ControlStyles.UserPaint | ControlStyles.ResizeRedraw, true);
            this.body = body;
            this.pin = pin;
            BackColor = Palette.Card;
            AutoSize = true;
            AutoSizeMode = AutoSizeMode.GrowAndShrink;
            Margin = new Padding(0);
            body.Dock = DockStyle.None;
            body.Anchor = AnchorStyles.Top | AnchorStyles.Left;
            body.Margin = new Padding(0);
            pin.Anchor = AnchorStyles.Top | AnchorStyles.Left;
            pin.Margin = new Padding(0);
            // In this order the content is at the top of the z-order and the control under it.
            Controls.Add(body);
            Controls.Add(pin);
            body.TabIndex = 0;
            pin.TabIndex = 1;
        }

        /// Plans the block as though `control` - a label in the content, or the pinned button - said the
        /// widest of `texts`, whatever it says now, so the block is laid out the same whichever of them it
        /// says. Words it is given that are wider still are planned for as they come.
        internal void Reserve(Control control, params string[] texts)
        {
            reserved[control] = texts;
            planned.Remove(control);
            PerformLayout();
        }

        /// Repaints `band`, in this block's coordinates, on every window of the content under it: they draw
        /// the part of the control's lift and focus ring over them in their own backgrounds, and a repaint of
        /// the block alone left the ring without its top and left edges and old pieces of it behind (v0.6.4).
        internal void InvalidateUnder(Rectangle band)
        {
            InvalidateUnder(body, body.Left, body.Top, band);
        }

        private static void InvalidateUnder(Control control, int x, int y, Rectangle band)
        {
            var bounds = new Rectangle(x, y, control.Width, control.Height);
            Rectangle part = Rectangle.Intersect(bounds, band);
            if (part.IsEmpty || !control.IsHandleCreated || control.IsDisposed) return;
            part.Offset(-x, -y);
            control.Invalidate(part, false);
            foreach (Control child in control.Controls)
                if (Soft.OwnVisible(child)) InvalidateUnder(child, x + child.Left, y + child.Top, band);
        }

        /// A grid of facts in the content - a column of names as wide as the widest, and their values - whose
        /// names wrap, down to their longest word, where its values would otherwise reach the control's column.
        internal TableLayoutPanel Wraps
        {
            get { return wraps; }
            set { wraps = value; PerformLayout(); }
        }

        public override System.Windows.Forms.Layout.LayoutEngine LayoutEngine { get { return engine; } }

        protected override void OnPaintBackground(PaintEventArgs e)
        {
            Ground.Paint(this, e);
        }

        public override Size GetPreferredSize(Size proposedSize)
        {
            int limit;
            if (proposedSize.Width > 1 && proposedSize.Width < 0x100000)
                return new Size(proposedSize.Width, Plan(proposedSize.Width, out limit));
            // Asked how narrow it can be (1) or how wide it would be (0), which a table asks for a column's
            // width before it asks how tall the block is that wide - the height its card's row then keeps.
            // The block fills its card, so: as wide as the card being measured (SoftCard.Measuring) leaves
            // it, or else as it was last laid out. Answered from what the content said, the height was asked
            // at a width the block never has, and followed the words: in English, Right now's row was 15 px
            // taller with the watcher running than stopped, planned for the same words (v0.6.4, measured);
            // answered from the last layout, a window given its height back kept the row of the width the
            // soft bar had left it.
            var card = Parent as SoftCard;
            int filled = card != null && card.Measuring > 0 ? card.Measuring - card.Padding.Horizontal - Margin.Horizontal : arranged;
            if (filled > 1) return new Size(filled, Plan(filled, out limit));
            // Never laid out nor measured in a card: as wide as its content would be with the control beside it.
            Size natural = body.GetPreferredSize(Size.Empty);
            if (!Soft.OwnVisible(pin)) return natural;
            Size size = PinSize();
            return new Size(natural.Width + Soft.Px(Brand.CardHeadGap) + PinWidth(), Math.Max(natural.Height, size.Height));
        }

        /// How tall the block is `width` wide, and how wide the names of `wraps` may be then (0: as wide as
        /// they are).
        private int Plan(int width, out int limit)
        {
            int whole;
            return Plan(width, out limit, out whole);
        }

        /// The same, and how tall the block is with every name of `wraps` whole (`whole`).
        private int Plan(int width, out int limit, out int whole)
        {
            limit = 0;
            var marks = new List<Mark>();
            int content = Model(body, 0, 0, width, 0, marks);
            whole = content;
            if (!Soft.OwnVisible(pin)) return content;
            Size size = PinSize();
            int gap = Soft.Px(Brand.CardFirstGap);
            // The column the control's widest words would take, so the text stops short of it whichever it says.
            int column = width - PinWidth() - Soft.Px(Brand.CardHeadGap);
            int beside = Math.Max(content, size.Height);
            int best = Needed(marks, content, column, size.Height, gap);
            whole = best;
            if (best == beside || wraps == null) return best;
            // The names wrap: as far as the values beside the control need, and else as far as every value
            // needs. The shortest block wins, the control under the facts among them.
            int natural = naturalFirst, shortest = LongestWord(wraps);
            int band = beside - size.Height - gap;
            for (int pass = 0; pass < 2; pass++)
            {
                int right = int.MinValue;
                foreach (Mark mark in marks)
                    if (mark.Column == 1 && (pass == 1 || mark.Box.Bottom > band)) right = Math.Max(right, mark.Box.Right);
                if (right <= column) continue;
                int candidate = natural - (right - column);
                if (candidate < shortest) continue;
                var wrapped = new List<Mark>();
                int height = Needed(wrapped, Model(body, 0, 0, width, candidate, wrapped), column, size.Height, gap);
                if (height < best)
                {
                    best = height;
                    limit = candidate;
                }
            }
            return best;
        }

        // A line of text where Model lays it out: its box in the block, and for a cell of `wraps` its column.
        private struct Mark
        {
            internal Rectangle Box;
            internal int Column;
        }

        /// How tall a block of `content` must be for a control `tall` high at its bottom right to be clear of
        /// every mark reaching right of `column`, `gap` under the lowest of them.
        private static int Needed(List<Mark> marks, int content, int column, int tall, int gap)
        {
            int height = Math.Max(content, tall);
            foreach (Mark mark in marks)
                if (mark.Box.Width > 0 && mark.Box.Right > column) height = Math.Max(height, mark.Box.Bottom + gap + tall);
            return height;
        }

        /// Lays `control` out `width` wide with its top left at (x, y) as its table would, adding a mark for
        /// what it draws, and answers its height. A table of one column (a list of lines) or of two (a column
        /// as wide as its widest cell, and the rest: a grid of facts) is laid out cell by cell; anything else
        /// is taken to fill its width. `limit` is how wide the names of `wraps` may be (0: as wide as they are).
        private int Model(Control control, int x, int y, int width, int limit, List<Mark> marks)
        {
            var table = control as TableLayoutPanel;
            if (table != null && table.ColumnCount == 1)
            {
                int left = x + table.Padding.Left, top = y + table.Padding.Top;
                int inner = width - table.Padding.Horizontal;
                foreach (Control child in table.Controls)
                {
                    if (!Soft.OwnVisible(child)) continue;
                    int room = Math.Max(0, inner - child.Margin.Horizontal);
                    Size size = Measured(child, room);
                    top += Place(child, left + child.Margin.Left, top + child.Margin.Top, Drawn(child, size, room), size,
                                 limit, -1, marks) + child.Margin.Vertical;
                }
                return top + table.Padding.Bottom - y;
            }
            if (table != null && table.ColumnCount == 2) return ModelGrid(table, x, y, width, limit, marks);
            return Place(control, x, y, width, Measured(control, width), limit, -1, marks);
        }

        private int ModelGrid(TableLayoutPanel table, int x, int y, int width, int limit, List<Mark> marks)
        {
            bool gives = table == wraps;
            var cells = new List<Control>();
            foreach (Control child in table.Controls)
                if (Soft.OwnVisible(child)) cells.Add(child);
            int inner = width - table.Padding.Horizontal;
            int first = 0, unwrapped = 0;
            for (int i = 0; i < cells.Count; i += 2)
            {
                Control name = cells[i];
                first = Math.Max(first, (gives ? NameSize(name, limit) : Measured(name, 0)).Width + name.Margin.Horizontal);
                if (gives) unwrapped = Math.Max(unwrapped, NameSize(name, 0).Width + name.Margin.Horizontal);
            }
            if (gives) naturalFirst = unwrapped;
            first = Math.Min(first, inner);
            int second = Math.Max(0, inner - first);
            int left = x + table.Padding.Left, top = y + table.Padding.Top;
            for (int i = 0; i < cells.Count; i += 2)
            {
                int line = 0;
                for (int j = i; j < cells.Count && j < i + 2; j++)
                {
                    Control cell = cells[j];
                    bool isName = j == i;
                    int room = Math.Max(0, (isName ? first : second) - cell.Margin.Horizontal);
                    Size size = isName && gives ? NameSize(cell, limit) : Measured(cell, room);
                    int height = Place(cell, left + (isName ? 0 : first) + cell.Margin.Left, top + cell.Margin.Top,
                                       Drawn(cell, size, room), size, limit, gives ? (isName ? 0 : 1) : -1, marks);
                    line = Math.Max(line, height + cell.Margin.Vertical);
                }
                top += line;
            }
            return top + table.Padding.Bottom - y;
        }

        /// A control laid out at (x, y), `width` wide and as tall as `size`: a table is looked into; a line of
        /// text, or anything else that draws, is marked. Answers its height.
        private int Place(Control control, int x, int y, int width, Size size, int limit, int column, List<Mark> marks)
        {
            if (control is TableLayoutPanel) return Model(control, x, y, width, limit, marks);
            bool draws = !(control is Label && string.IsNullOrEmpty(control.Text)) && !(control is Panel && control.Controls.Count == 0);
            if (draws)
            {
                var mark = new Mark();
                mark.Box = new Rectangle(x, y, width, size.Height);
                mark.Column = column;
                marks.Add(mark);
            }
            return size.Height;
        }

        /// A control's size in a cell `room` wide, or as wide as it would be when `room` is 0 - for a label
        /// with reserved words (Reserve), as wide and as tall as the widest and tallest of them and its own.
        private Size Measured(Control control, int room)
        {
            Size size = AsIs(control, room);
            string[] texts;
            var label = control as Label;
            if (label == null || !label.AutoSize || !reserved.TryGetValue(control, out texts)) return size;
            Reservation last;
            if (!planned.TryGetValue(control, out last) || last.Room != room || last.Font != label.Font)
            {
                last = new Reservation();
                last.Room = room;
                last.Font = label.Font;
                twin.AutoSize = true;
                twin.Font = label.Font;
                twin.Padding = label.Padding;
                twin.UseMnemonic = label.UseMnemonic;
                twin.MaximumSize = label.MaximumSize;
                foreach (string text in texts)
                {
                    twin.Text = text ?? "";
                    Size words = twin.GetPreferredSize(new Size(room, 0));
                    last.Size = new Size(Math.Max(last.Size.Width, words.Width), Math.Max(last.Size.Height, words.Height));
                }
                planned[control] = last;
            }
            return new Size(Math.Max(size.Width, last.Size.Width), Math.Max(size.Height, last.Size.Height));
        }

        private static Size AsIs(Control control, int room)
        {
            return control.AutoSize ? control.GetPreferredSize(new Size(room, 0)) : control.Size;
        }

        /// A name of `wraps` as it is with its column at most `limit` wide (0: as wide as it is), measured on
        /// a twin so the name itself is not changed. Asked for a width, which a label never answers from what
        /// it remembers of other text.
        private static Size NameSize(Control cell, int limit)
        {
            var label = cell as Label;
            if (label == null) return AsIs(cell, 0);
            twin.AutoSize = true;
            twin.Font = label.Font;
            twin.Padding = label.Padding;
            twin.UseMnemonic = label.UseMnemonic;
            twin.MaximumSize = limit > 0 ? new Size(Math.Max(1, limit - cell.Margin.Horizontal), 0) : Size.Empty;
            twin.Text = label.Text;
            return twin.GetPreferredSize(new Size(0x3FFFFFFF, 0));
        }

        /// How narrow the names of a grid can wrap: their longest word, and the name's margin.
        private static int LongestWord(TableLayoutPanel grid)
        {
            int longest = 0;
            bool isName = true;
            foreach (Control cell in grid.Controls)
            {
                if (!Soft.OwnVisible(cell)) continue;
                if (isName && cell is Label)
                {
                    string text = cell.Text;
                    for (int start = 0; start < text.Length; )
                    {
                        int end = text.IndexOf(' ', start);
                        if (end < 0) end = text.Length;
                        if (end > start)
                        {
                            twin.MaximumSize = Size.Empty;
                            twin.Font = cell.Font;
                            twin.Padding = cell.Padding;
                            twin.Text = text.Substring(start, end - start);
                            longest = Math.Max(longest, twin.GetPreferredSize(new Size(0x3FFFFFFF, 0)).Width + cell.Margin.Horizontal);
                        }
                        start = end + 1;
                    }
                }
                isName = !isName;
            }
            return longest;
        }

        /// How wide a control is drawn in its cell: all of the cell when it is stretched across it.
        private static int Drawn(Control control, Size size, int room)
        {
            bool stretched = control.Dock == DockStyle.Fill ||
                             (control.Anchor & (AnchorStyles.Left | AnchorStyles.Right)) == (AnchorStyles.Left | AnchorStyles.Right);
            return stretched ? room : Math.Min(size.Width, room);
        }

        private Size PinSize()
        {
            return pin.AutoSize ? pin.GetPreferredSize(Size.Empty) : pin.Size;
        }

        /// How wide the control is with the widest of its reserved words (Reserve), or as it is: the width its
        /// column is planned for. The control itself is as wide as what it says now, at the block's right edge.
        private int PinWidth()
        {
            int width = PinSize().Width;
            string[] texts;
            var button = pin as ButtonBase;
            if (button == null || !button.AutoSize || !reserved.TryGetValue(pin, out texts)) return width;
            Reservation last;
            if (!planned.TryGetValue(pin, out last) || last.Font != button.Font)
            {
                last = new Reservation();
                last.Font = button.Font;
                if (twinButton == null)
                {
                    twinButton = new Button();
                    twinButton.AutoSize = true;
                    twinButton.AutoSizeMode = AutoSizeMode.GrowAndShrink;
                }
                twinButton.FlatStyle = button.FlatStyle;
                if (button.FlatStyle == FlatStyle.Flat) twinButton.FlatAppearance.BorderSize = button.FlatAppearance.BorderSize;
                twinButton.Font = button.Font;
                twinButton.Padding = button.Padding;
                twinButton.MaximumSize = Size.Empty;
                twinButton.MinimumSize = button.MinimumSize;
                twinButton.MaximumSize = button.MaximumSize;
                twinButton.UseMnemonic = button.UseMnemonic;
                foreach (string text in texts)
                {
                    twinButton.Text = text ?? "";
                    Size words = twinButton.GetPreferredSize(Size.Empty);
                    last.Size = new Size(Math.Max(last.Size.Width, words.Width), Math.Max(last.Size.Height, words.Height));
                }
                planned[pin] = last;
            }
            return Math.Max(width, last.Size.Width);
        }

        private void Arrange()
        {
            int width = ClientSize.Width;
            if (width > 1) arranged = width;
            int limit, whole;
            int needed = Plan(width, out limit, out whole);
            // The names give way only to keep the block short. A block stretched taller than that - beside a taller
            // card, or down a page whose rows share its height (SoftRows) - has the room for them whole, with the
            // control under the lowest line in its column, and keeps them whole.
            if (limit > 0 && whole <= ClientSize.Height)
            {
                limit = 0;
                needed = whole;
            }
            if (wraps != null)
            {
                bool isName = true;
                foreach (Control cell in wraps.Controls)
                {
                    if (!Soft.OwnVisible(cell)) continue;
                    Size wanted = limit > 0 ? new Size(Math.Max(1, limit - cell.Margin.Horizontal), 0) : Size.Empty;
                    if (isName && cell.MaximumSize != wanted) cell.MaximumSize = wanted;
                    isName = !isName;
                }
            }
            int content = body.GetPreferredSize(new Size(width, 0)).Height;
            if (body.Left != 0 || body.Top != 0 || body.Width != width || body.Height != content)
            {
                body.SetBounds(0, 0, width, content);
                // Laid out at its width, what it holds can change under it - Recently finished fits its names
                // to the width it gets - so it is planned again.
                int ignored;
                needed = Plan(width, out ignored);
            }
            var place = Rectangle.Empty;
            if (Soft.OwnVisible(pin))
            {
                Size size = PinSize();
                place = new Rectangle(width - size.Width, Math.Max(0, ClientSize.Height - size.Height), size.Width, size.Height);
                if (pin.Bounds != place) pin.Bounds = place;
            }
            Cut(Rectangle.Intersect(place, body.Bounds));
            if (needed <= ClientSize.Height) return;
            // Given less than it needs: its row was measured before what it holds changed under it. The page lays
            // what it holds out once more (SoftPage.Unsettle); left, History stood over the last outcomes of a
            // Japanese Overview opened at 150% (v0.6.4, measured).
            for (Control c = Parent; c != null; c = c.Parent)
            {
                var page = c as SoftPage;
                if (page == null) continue;
                page.Unsettle();
                break;
            }
        }

        /// Cuts the control's place out of the content's window, which is above it in the z-order - or
        /// gives the content its whole window back when the control is beside none of it. What lies under
        /// the hole is the control, and the hole is its size: every line beside it stops a head gap short.
        private void Cut(Rectangle place)
        {
            place.Offset(-body.Left, -body.Top);
            if (place == hole) return;
            hole = place;
            if (place.IsEmpty)
            {
                body.Region = null;
                return;
            }
            // Everything the window could ever be but the hole, so the content growing needs no new region.
            var region = new Region(new Rectangle(0, 0, short.MaxValue, short.MaxValue));
            region.Exclude(place);
            body.Region = region;
        }

        private sealed class PinLayout : System.Windows.Forms.Layout.LayoutEngine
        {
            public override bool Layout(object container, LayoutEventArgs layoutEventArgs)
            {
                ((SoftPin)container).Arrange();
                // As an AutoSize panel's own layout does: what it holds may have changed its height.
                return true;
            }
        }
    }

    /// Painting a native window that paints its own face: one WM_PAINT, drawn off-screen and
    /// copied in, or into the device context a capture hands it.
    internal static class NativePaint
    {
        [DllImport("user32.dll")]
        private static extern IntPtr BeginPaint(IntPtr window, IntPtr paint);

        [DllImport("user32.dll")]
        private static extern bool EndPaint(IntPtr window, IntPtr paint);

        internal const int WM_PAINT = 0x000F;
        internal const int WM_ERASEBKGND = 0x0014;
        internal const int WM_PRINTCLIENT = 0x0318;

        /// True when `m` was a paint message and `draw` has answered it.
        internal static bool Handle(ref Message m, Size size, Action<Graphics> draw)
        {
            if (m.Msg == WM_ERASEBKGND)
            {
                m.Result = (IntPtr)1;
                return true;
            }
            if (m.Msg != WM_PAINT && m.Msg != WM_PRINTCLIENT) return false;
            if (m.WParam != IntPtr.Zero)
            {
                using (Graphics g = Graphics.FromHdc(m.WParam)) draw(g);
            }
            else if (m.Msg == WM_PAINT)
            {
                IntPtr paint = Marshal.AllocHGlobal(128);   // a PAINTSTRUCT is 72 bytes on x64
                try
                {
                    IntPtr dc = BeginPaint(m.HWnd, paint);
                    try
                    {
                        if (size.Width > 0 && size.Height > 0)
                            using (Graphics screen = Graphics.FromHdc(dc))
                            using (BufferedGraphics buffer = BufferedGraphicsManager.Current.Allocate(screen, new Rectangle(Point.Empty, size)))
                            {
                                draw(buffer.Graphics);
                                buffer.Render(screen);
                            }
                    }
                    finally { EndPaint(m.HWnd, paint); }
                }
                finally { Marshal.FreeHGlobal(paint); }
            }
            m.Result = IntPtr.Zero;
            return true;
        }
    }
}
