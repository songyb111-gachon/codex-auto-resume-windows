// Codex Auto Resume - lists, and the clipping that keeps their rows inside the card.

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
    /// A label whose lines end where the popup's and the panel's do (Soft.Wrap): Korean between its words,
    /// never inside one - a help line, a note, a value. Text without Korean is measured and drawn by Label
    /// itself, exactly as before; with Korean, as Label would draw it, only broken where a line may end.
    internal class WrapLabel : Label
    {
        /// How Label draws its text (ControlPaint.CreateTextFormatFlags): wrapped as a text box, in its
        /// alignment, with an ellipsis if it ends in one and its mnemonic as it is set.
        internal TextFormatFlags Format
        {
            get
            {
                TextFormatFlags flags = TextFormatFlags.WordBreak | TextFormatFlags.TextBoxControl;
                const ContentAlignment middle = ContentAlignment.MiddleLeft | ContentAlignment.MiddleCenter | ContentAlignment.MiddleRight;
                const ContentAlignment bottom = ContentAlignment.BottomLeft | ContentAlignment.BottomCenter | ContentAlignment.BottomRight;
                const ContentAlignment centre = ContentAlignment.TopCenter | ContentAlignment.MiddleCenter | ContentAlignment.BottomCenter;
                const ContentAlignment right = ContentAlignment.TopRight | ContentAlignment.MiddleRight | ContentAlignment.BottomRight;
                if ((TextAlign & middle) != 0) flags |= TextFormatFlags.VerticalCenter;
                else if ((TextAlign & bottom) != 0) flags |= TextFormatFlags.Bottom;
                if ((TextAlign & centre) != 0) flags |= TextFormatFlags.HorizontalCenter;
                else if ((TextAlign & right) != 0) flags |= TextFormatFlags.Right;
                if (AutoEllipsis) flags |= TextFormatFlags.EndEllipsis;
                if (!UseMnemonic) flags |= TextFormatFlags.NoPrefix;
                else if (!ShowKeyboardCues) flags |= TextFormatFlags.HidePrefix;
                return flags;
            }
        }

        /// Its text in the lines it is drawn in `width` wide inside its padding (Soft.Wrap).
        internal string Lines(int width)
        {
            return Soft.Wrap(Text, Font, width, Format);
        }

        public override Size GetPreferredSize(Size proposedSize)
        {
            if (!Soft.SplitsWords(Text)) return base.GetPreferredSize(proposedSize);
            // As Label answers - a width of 0 or 1 is none - measured in the lines it is drawn in.
            int width = proposedSize.Width > 1 ? proposedSize.Width : int.MaxValue;
            if (MaximumSize.Width > 0) width = Math.Min(width, MaximumSize.Width);
            int inner = width == int.MaxValue ? int.MaxValue : Math.Max(1, width - Padding.Horizontal);
            Size text = Soft.Measure(Lines(inner), Font, inner, Format);
            var size = new Size(text.Width + Padding.Horizontal, text.Height + Padding.Vertical);
            if (MaximumSize.Width > 0) size.Width = Math.Min(size.Width, MaximumSize.Width);
            if (MaximumSize.Height > 0) size.Height = Math.Min(size.Height, MaximumSize.Height);
            return new Size(Math.Max(size.Width, MinimumSize.Width), Math.Max(size.Height, MinimumSize.Height));
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            if (!Soft.SplitsWords(Text))
            {
                base.OnPaint(e);
                return;
            }
            var face = new Rectangle(Padding.Left, Padding.Top, Math.Max(0, ClientSize.Width - Padding.Horizontal),
                                     Math.Max(0, ClientSize.Height - Padding.Vertical));
            // Label's disabled ink (TextRenderer.DisabledTextColor), High Contrast as the window reads it.
            Color ink = Enabled ? ForeColor
                      : Palette.Contrast ? SystemColors.GrayText
                      : BackColor.GetBrightness() < SystemColors.Control.GetBrightness() ? ControlPaint.Dark(BackColor)
                      : SystemColors.ControlDark;
            TextRenderer.DrawText(e.Graphics, Lines(face.Width), Font, face, ink, Format);
        }
    }

    /// A list whose rows are drawn by the page that owns it, double-buffered so a five-second
    /// refresh does not flicker.
    internal sealed class SoftList : ListView
    {
        private const int WM_SIZE = 0x0005;
        private const int WM_PAINT = 0x000F;
        private const int WM_STYLECHANGED = 0x007D;
        private const int WM_KEYDOWN = 0x0100;
        private const int WM_HSCROLL = 0x0114;
        private const int WM_VSCROLL = 0x0115;
        private const int WM_MOUSEWHEEL = 0x020A;
        private const int WM_MOUSEHWHEEL = 0x020E;

        internal SoftList()
        {
            SetStyle(ControlStyles.OptimizedDoubleBuffer | ControlStyles.AllPaintingInWmPaint, true);
        }

        /// After anything that can move or resize what the list shows - a scroll either way, a key, a
        /// resize, a scroll bar coming or going, and every paint, which follows all of those.
        internal event EventHandler ScrollChanged;

        protected override void WndProc(ref Message m)
        {
            base.WndProc(ref m);
            if (ScrollChanged != null && (m.Msg == WM_PAINT || m.Msg == WM_VSCROLL || m.Msg == WM_HSCROLL ||
                                          m.Msg == WM_MOUSEWHEEL || m.Msg == WM_MOUSEHWHEEL ||
                                          m.Msg == WM_KEYDOWN || m.Msg == WM_SIZE || m.Msg == WM_STYLECHANGED))
                ScrollChanged(this, EventArgs.Empty);
        }
    }

    /// The strip a SoftListHost shows its list through: exactly as wide as the list's rows and as tall
    /// as the rows it shows, so the list's own scroll bars, beside and below them, are outside it.
    internal sealed class ListClip : Panel
    {
        internal ListClip()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.UserPaint, true);
            TabStop = false;
        }
    }

    /// A list with the soft scroll bar in place of its own.
    ///
    /// The list stays a whole native ListView - its keyboard selection, its wheel, its header, its
    /// owner-drawn rows and what a screen reader is told are all Windows' - and it keeps its own scroll
    /// bar. The host only hides that bar: the list stands in a ListClip exactly as wide as its rows, and
    /// is itself wider by the bar, so the bar lies outside the clip, where a child window is never drawn.
    /// Its rows' width, and so every column (SettingsForm.FitColumns), is what it always was. While it
    /// has more rows than show, the clip is narrower by the gutter, and the host draws the soft bar
    /// there from the list's own scroll position (GetScrollInfo, in rows). Dragging, paging and the
    /// wheel over the bar are sent to the list as the scrolling it already understands (LVM_SCROLL,
    /// WM_VSCROLL), and the bar follows whatever the list does itself (SoftList.ScrollChanged).
    ///
    /// The same across its bottom (v0.6.5): Windows' own horizontal bar showed white on a dark card when
    /// the columns were a little wider than the list. The window makes the columns fit the list at every
    /// ordinary size (SettingsForm.FitColumns), so a list overflows sideways only in a window narrower
    /// than they can shrink to. Then, and only then, the list is taller than the clip by its own
    /// horizontal bar, which lies under the clip unseen, the clip is shorter by the gutter, and the host
    /// draws the soft bar lying along the bottom (AcrossBar) from the list's horizontal scroll position,
    /// in pixels, scrolling it with LVM_SCROLL and WM_HSCROLL.
    internal sealed class SoftListHost : Panel, ISoftScroller
    {
        [StructLayout(LayoutKind.Sequential)]
        private struct ScrollInfo
        {
            public int Size, Mask, Min, Max, Page, Position, TrackPosition;
        }

        [DllImport("user32.dll")]
        private static extern bool GetScrollInfo(IntPtr window, int bar, ref ScrollInfo info);

        [DllImport("user32.dll")]
        private static extern int GetWindowLong(IntPtr window, int index);

        [DllImport("user32.dll")]
        private static extern IntPtr SendMessage(IntPtr window, int message, IntPtr wParam, IntPtr lParam);

        private const int SB_HORZ = 0;
        private const int SB_VERT = 1;
        private const int SIF_ALL = 0x17;
        private const int GWL_STYLE = -16;
        private const int WS_HSCROLL = 0x00100000;
        private const int WS_VSCROLL = 0x00200000;
        private const int WM_HSCROLL = 0x0114;
        private const int WM_VSCROLL = 0x0115;
        private const int SB_PAGEUP = 2;
        private const int SB_PAGEDOWN = 3;
        private const int SB_PAGELEFT = 2;
        private const int SB_PAGERIGHT = 3;
        private const int LVM_SCROLL = 0x1014;

        internal readonly ListView List;
        private readonly ListClip clip = new ListClip();
        private readonly SoftScrollBar bar, acrossBar;
        private readonly Sideways sideways;
        private ScrollInfo scroll, sideScroll;
        private bool native, nativeAcross, queued;

        internal SoftListHost(ListView list)
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                     ControlStyles.UserPaint | ControlStyles.ResizeRedraw, true);
            List = list;
            // Before anything is added: adding lays the host out, and laying out places the bars.
            bar = new SoftScrollBar(this, this);
            sideways = new Sideways(this);
            acrossBar = new SoftScrollBar(this, sideways, true);
            BackColor = list.BackColor;
            clip.BackColor = list.BackColor;
            list.Dock = DockStyle.None;
            list.Margin = new Padding(0);
            clip.Controls.Add(list);
            Controls.Add(clip);
            var soft = list as SoftList;
            if (soft != null) soft.ScrollChanged += delegate { Changed(); };
            list.HandleCreated += delegate { Changed(); };
        }

        internal SoftScrollBar Bar { get { return bar; } }

        /// The soft bar along the bottom, scrolling the list sideways; its Track is empty while the
        /// columns fit.
        internal SoftScrollBar AcrossBar { get { return acrossBar; } }

        /// Whether the list has more rows than show, so the soft bar is showing.
        internal bool Overflowing { get { return native; } }

        /// Whether the list's columns are wider than it is, so the soft bar along its bottom is showing
        /// - and Windows' own horizontal bar is on, under the clip. Read from the list's style once the
        /// window has had its messages; LayoutAudit, which never pumps them, compares the columns with
        /// the list's width instead (SettingsForm.AuditList).
        internal bool OverflowingAcross { get { return nativeAcross; } }

        internal ListClip Clip { get { return clip; } }

        // The list's horizontal scroll position as last read.
        private ScrollInfo Side { get { return sideScroll; } }

        /// The list's sideways scrolling as the soft bar reads it: in pixels, as Windows keeps it for a
        /// list of details.
        private sealed class Sideways : ISoftScroller
        {
            private readonly SoftListHost host;

            internal Sideways(SoftListHost host) { this.host = host; }

            public int Extent { get { ScrollInfo info = host.Side; return Math.Max(0, info.Max - info.Min + 1); } }
            public int Viewport { get { return Math.Max(1, host.Side.Page); } }
            public int Offset { get { ScrollInfo info = host.Side; return Math.Max(0, info.Position - info.Min); } }

            public void ScrollTo(int target)
            {
                ListView list = host.List;
                if (!list.IsHandleCreated) return;
                host.Read();
                target = Math.Max(0, Math.Min(Math.Max(0, Extent - Viewport), target));
                int by = target - Offset;
                if (by == 0) return;
                SendMessage(list.Handle, LVM_SCROLL, new IntPtr(by), IntPtr.Zero);
                host.Sync();
            }

            public void Page(int direction)
            {
                ListView list = host.List;
                if (!list.IsHandleCreated) return;
                SendMessage(list.Handle, WM_HSCROLL, new IntPtr(direction < 0 ? SB_PAGELEFT : SB_PAGERIGHT), IntPtr.Zero);
                host.Sync();
            }
        }

        int ISoftScroller.Extent { get { return Math.Max(0, scroll.Max - scroll.Min + 1); } }
        int ISoftScroller.Viewport { get { return Math.Max(1, scroll.Page); } }
        int ISoftScroller.Offset { get { return Math.Max(0, scroll.Position - scroll.Min); } }

        void ISoftScroller.ScrollTo(int target)
        {
            if (!List.IsHandleCreated || List.Items.Count == 0) return;
            Read();
            var self = (ISoftScroller)this;
            target = Math.Max(0, Math.Min(Math.Max(0, self.Extent - self.Viewport), target));
            int rows = target - self.Offset, row = List.GetItemRect(0).Height;
            if (rows == 0 || row <= 0) return;
            SendMessage(List.Handle, LVM_SCROLL, IntPtr.Zero, new IntPtr(rows * row));
            Sync();
        }

        void ISoftScroller.Page(int direction)
        {
            if (!List.IsHandleCreated) return;
            SendMessage(List.Handle, WM_VSCROLL, new IntPtr(direction < 0 ? SB_PAGEUP : SB_PAGEDOWN), IntPtr.Zero);
            Sync();
        }

        private bool NativeBar
        {
            get { return List.IsHandleCreated && (GetWindowLong(List.Handle, GWL_STYLE) & WS_VSCROLL) != 0; }
        }

        private bool NativeAcross
        {
            get { return List.IsHandleCreated && (GetWindowLong(List.Handle, GWL_STYLE) & WS_HSCROLL) != 0; }
        }

        private void Read()
        {
            scroll = ReadBar(SB_VERT);
            sideScroll = ReadBar(SB_HORZ);
        }

        private ScrollInfo ReadBar(int which)
        {
            var info = new ScrollInfo();
            info.Size = Marshal.SizeOf(typeof(ScrollInfo));
            info.Mask = SIF_ALL;
            if (List.IsHandleCreated && GetScrollInfo(List.Handle, which, ref info)) return info;
            return new ScrollInfo();
        }

        protected override void OnLayout(LayoutEventArgs levent)
        {
            base.OnLayout(levent);
            native = NativeBar;
            nativeAcross = NativeAcross;
            int rows = Math.Max(0, Width - (native ? SoftBar.Gutter : 0));
            int tall = Math.Max(0, Height - (nativeAcross ? SoftBar.Gutter : 0));
            // The list's own bar is as wide as the list is wider than its rows; before it has one,
            // Windows' measure of a scroll bar. The same below, for its bar across the bottom.
            int beside = native ? Math.Max(0, List.Width - List.ClientSize.Width) : 0;
            if (native && beside == 0) beside = SystemInformation.VerticalScrollBarWidth;
            int below = nativeAcross ? Math.Max(0, List.Height - List.ClientSize.Height) : 0;
            if (nativeAcross && below == 0) below = SystemInformation.HorizontalScrollBarHeight;
            clip.SetBounds(0, 0, rows, tall);
            List.SetBounds(0, 0, rows + beside, tall + below);
            Read();
            bar.Track = native ? TrackBounds() : Rectangle.Empty;
            acrossBar.Track = nativeAcross ? AcrossBounds() : Rectangle.Empty;
        }

        // Beside the rows: from under the column headings to the bottom, or to the bar along it.
        private Rectangle TrackBounds()
        {
            int margin = Soft.Px(SoftBar.TrackMargin);
            int top = List.Items.Count > 0 && List.View == View.Details ? Math.Max(0, List.GetItemRect(List.TopItem != null ? List.TopItem.Index : 0).Top) : 0;
            int bottom = Height - (nativeAcross ? SoftBar.Gutter : 0);
            return new Rectangle(Width - margin - Soft.Px(SoftBar.TrackWidth), top + margin, Soft.Px(SoftBar.TrackWidth),
                                 Math.Max(0, bottom - top - 2 * margin));
        }

        // Along the bottom, under the rows: from the left edge to the bar beside them, if that shows.
        private Rectangle AcrossBounds()
        {
            int margin = Soft.Px(SoftBar.TrackMargin);
            int right = Width - (native ? SoftBar.Gutter : 0);
            return new Rectangle(margin, Height - margin - Soft.Px(SoftBar.TrackWidth), Math.Max(0, right - 2 * margin),
                                 Soft.Px(SoftBar.TrackWidth));
        }

        // Called from inside the list's own messages, so what it changes waits until they are done.
        private void Changed()
        {
            if (queued || !IsHandleCreated) return;
            queued = true;
            BeginInvoke(new MethodInvoker(delegate { queued = false; Sync(); }));
        }

        /// Brings the soft bar in step with the list: laid out again when the list's own bar came or went,
        /// painted again when its position or length changed.
        internal void Sync()
        {
            if (IsDisposed || !List.IsHandleCreated) return;
            if (NativeBar != native || NativeAcross != nativeAcross)
            {
                PerformLayout();
                Invalidate();
                return;
            }
            ScrollInfo before = scroll, sideBefore = sideScroll;
            Read();
            Rectangle track = native ? TrackBounds() : Rectangle.Empty;
            if (before.Position != scroll.Position || before.Max != scroll.Max || before.Page != scroll.Page || track != bar.Track)
            {
                bar.Track = track;
                bar.Invalidate();
            }
            Rectangle across = nativeAcross ? AcrossBounds() : Rectangle.Empty;
            if (sideBefore.Position != sideScroll.Position || sideBefore.Max != sideScroll.Max ||
                sideBefore.Page != sideScroll.Page || across != acrossBar.Track)
            {
                acrossBar.Track = across;
                acrossBar.Invalidate();
            }
        }

        protected override void OnMouseWheel(MouseEventArgs e)
        {
            base.OnMouseWheel(e);
            if (!native) return;
            var self = (ISoftScroller)this;
            int rows = SoftBar.WheelStep(e.Delta, SystemInformation.MouseWheelScrollLines, 1, self.Viewport);
            if (rows != 0) self.ScrollTo(self.Offset + rows);
            var handled = e as HandledMouseEventArgs;
            if (handled != null) handled.Handled = true;
        }

        protected override void OnPaintBackground(PaintEventArgs e)
        {
            using (var brush = new SolidBrush(BackColor)) e.Graphics.FillRectangle(brush, e.ClipRectangle);
            if (native) bar.Paint(e.Graphics);
            if (nativeAcross) acrossBar.Paint(e.Graphics);
        }
    }
}
