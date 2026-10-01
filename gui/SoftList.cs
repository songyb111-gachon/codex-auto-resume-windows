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

    /// The version, and after it the edition that runs as quiet secondary text: the save bar's version and
    /// Diagnostics' Version row (v0.6.11). The owner's decision of 2026-10-02 on "v0.6.11 · Standard": no separator,
    /// the edition a space of the version's font after it, smaller (Soft.AsidePoints), in the theme's secondary
    /// colour whichever edition it is - Advanced is not blue - and with its baseline on the version's, not centred
    /// beside it. The panel's heading says it the same way (panel.css, .edition).
    ///
    /// Its Text is the whole line, "v0.6.11 Standard", which is what a screen reader reads and what anything that
    /// measures the label's text measures; it is drawn in two runs. Without an edition - or with a Text set some
    /// other way - it is the WrapLabel it always was, letter for letter.
    internal sealed class VersionLabel : WrapLabel
    {
        private string version = "", edition;
        private Font aside, asideOf;

        internal VersionLabel()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.UserPaint, true);
        }

        /// The version and the edition's word (null or "" for none), shown together.
        internal void Set(string versionText, string editionText)
        {
            version = versionText ?? "";
            edition = string.IsNullOrEmpty(editionText) ? null : editionText;
            string text = edition == null ? version : version + " " + edition;
            if (Text != text) Text = text;
            else Invalidate();
        }

        internal string Version { get { return version; } }
        internal string Edition { get { return edition; } }

        /// The colour the edition is drawn in: the theme's secondary text, for every edition.
        internal static Color EditionColor { get { return Palette.Secondary; } }

        /// The colour the edition was last drawn in, for the tests; empty until it has been.
        internal Color EditionDrawn { get; private set; }

        /// Whether it is drawn in two runs: an edition, and the Text Set wrote.
        internal bool Split { get { return edition != null && Text == version + " " + edition; } }

        /// The edition's font: the label's own face, regular, at Soft.AsidePoints of the label's size.
        internal Font AsideFont
        {
            get
            {
                if (aside == null || !ReferenceEquals(asideOf, Font))
                {
                    if (aside != null) aside.Dispose();
                    asideOf = Font;
                    aside = new Font(Font.FontFamily, Soft.AsidePoints(Font.SizeInPoints), FontStyle.Regular,
                                     GraphicsUnit.Point, Font.GdiCharSet);
                }
                return aside;
            }
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing && aside != null)
            {
                aside.Dispose();
                aside = null;
            }
            base.Dispose(disposing);
        }

        /// The version's line, as Label draws one line: its own padding, its mnemonic as it is set.
        private TextFormatFlags LineFormat
        {
            get { return TextFormatFlags.SingleLine | (UseMnemonic ? TextFormatFlags.Default : TextFormatFlags.NoPrefix); }
        }

        /// The edition's, without padding: one line beside the version, or wrapped under it (`below`).
        private TextFormatFlags EditionFormat(bool below)
        {
            return (below ? TextFormatFlags.WordBreak | TextFormatFlags.TextBoxControl : TextFormatFlags.SingleLine) |
                   TextFormatFlags.NoPadding | (UseMnemonic ? TextFormatFlags.Default : TextFormatFlags.NoPrefix);
        }

        /// The two runs in a face `width` wide (int.MaxValue: as wide as they ask), from the top left of what they
        /// make together, which is returned. The version as Label draws it, its own padding included, so its letters
        /// stand where they always stood; the edition without padding, a space of the version's font after the
        /// version's last letter, its top as far below the version's as its ascent is shorter - GDI's ascent of the
        /// font TextRenderer draws each in (Baseline) - so the two share a baseline, inside the version's line. Where
        /// the face is too narrow for both, the edition goes under the version (`below`), wrapped in what is left.
        internal Size Arrange(int width, out Rectangle versionBox, out Rectangle editionBox, out bool below)
        {
            Measure();
            versionBox = new Rectangle(0, 0, whole.Width, whole.Height);
            below = false;
            editionBox = Rectangle.Empty;
            if (edition == null) return whole;
            if (width == int.MaxValue || after + word.Width + pad <= width)
            {
                editionBox = new Rectangle(after, drop, word.Width, word.Height);
                return new Size(after + word.Width + pad, whole.Height);
            }
            below = true;
            int room = Math.Max(1, width - 2 * pad);
            TextFormatFlags wrap = EditionFormat(true);
            Size block = Soft.Measure(Soft.Wrap(edition, AsideFont, room, wrap), AsideFont, room, wrap);
            editionBox = new Rectangle(pad, whole.Height, room, block.Height);
            return new Size(Math.Max(whole.Width, pad + block.Width + pad), whole.Height + block.Height);
        }

        // What Arrange lays out, measured once for each font, words and format (a layout asks for the label's size
        // again and again, and Label caches its own measurement): the version's line with and without its padding, the
        // padding either side, where the edition starts - a space of the version's font after its last letter - how far
        // below the version's top the edition's is, and the edition's line.
        private Font measuredFont;
        private string measuredVersion, measuredEdition;
        private TextFormatFlags measuredFormat;
        private Size whole, word;
        private int pad, after, drop;

        private void Measure()
        {
            TextFormatFlags line = LineFormat;
            if (ReferenceEquals(measuredFont, Font) && measuredVersion == version && measuredEdition == edition &&
                measuredFormat == line)
                return;
            var unbounded = new Size(int.MaxValue, int.MaxValue);
            whole = TextRenderer.MeasureText(version, Font, unbounded, line);
            if (edition != null)
            {
                TextFormatFlags bare = line | TextFormatFlags.NoPadding;
                int letters = TextRenderer.MeasureText(version, Font, unbounded, bare).Width;
                int space = TextRenderer.MeasureText("x x", Font, unbounded, bare).Width
                          - TextRenderer.MeasureText("xx", Font, unbounded, bare).Width;
                pad = Math.Max(0, (whole.Width - letters) / 2);
                after = pad + letters + Math.Max(1, space);
                word = TextRenderer.MeasureText(edition, AsideFont, unbounded, EditionFormat(false));
                drop = Baseline(Font) - Baseline(AsideFont);
            }
            measuredFont = Font;
            measuredVersion = version;
            measuredEdition = edition;
            measuredFormat = line;
        }

        public override Size GetPreferredSize(Size proposedSize)
        {
            if (!Split) return base.GetPreferredSize(proposedSize);
            // As WrapLabel answers: a width of 0 or 1 is none, and the label's maximum holds.
            int width = proposedSize.Width > 1 ? proposedSize.Width : int.MaxValue;
            if (MaximumSize.Width > 0) width = Math.Min(width, MaximumSize.Width);
            int inner = width == int.MaxValue ? int.MaxValue : Math.Max(1, width - Padding.Horizontal);
            Rectangle versionBox, editionBox;
            bool below;
            Size text = Arrange(inner, out versionBox, out editionBox, out below);
            var size = new Size(text.Width + Padding.Horizontal, text.Height + Padding.Vertical);
            if (MaximumSize.Width > 0) size.Width = Math.Min(size.Width, MaximumSize.Width);
            if (MaximumSize.Height > 0) size.Height = Math.Min(size.Height, MaximumSize.Height);
            return new Size(Math.Max(size.Width, MinimumSize.Width), Math.Max(size.Height, MinimumSize.Height));
        }

        /// Where the two runs are drawn in the label as it stands: the block Arrange makes, placed in the label's
        /// face as its TextAlign places text.
        internal void Placed(out Rectangle versionBox, out Rectangle editionBox, out bool below)
        {
            var face = new Rectangle(Padding.Left, Padding.Top, Math.Max(0, ClientSize.Width - Padding.Horizontal),
                                     Math.Max(0, ClientSize.Height - Padding.Vertical));
            Size block = Arrange(face.Width, out versionBox, out editionBox, out below);
            const ContentAlignment middle = ContentAlignment.MiddleLeft | ContentAlignment.MiddleCenter | ContentAlignment.MiddleRight;
            const ContentAlignment bottom = ContentAlignment.BottomLeft | ContentAlignment.BottomCenter | ContentAlignment.BottomRight;
            const ContentAlignment centre = ContentAlignment.TopCenter | ContentAlignment.MiddleCenter | ContentAlignment.BottomCenter;
            const ContentAlignment right = ContentAlignment.TopRight | ContentAlignment.MiddleRight | ContentAlignment.BottomRight;
            int x = (TextAlign & centre) != 0 ? face.X + (face.Width - block.Width) / 2
                  : (TextAlign & right) != 0 ? face.Right - block.Width : face.X;
            int y = (TextAlign & middle) != 0 ? face.Y + (face.Height - block.Height) / 2
                  : (TextAlign & bottom) != 0 ? face.Bottom - block.Height : face.Y;
            versionBox.Offset(x, y);
            editionBox.Offset(x, y);
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            if (!Split)
            {
                base.OnPaint(e);
                return;
            }
            Rectangle versionBox, editionBox;
            bool below;
            Placed(out versionBox, out editionBox, out below);
            // Label's disabled ink (TextRenderer.DisabledTextColor) for both, as WrapLabel draws it.
            Color disabled = Palette.Contrast ? SystemColors.GrayText
                           : BackColor.GetBrightness() < SystemColors.Control.GetBrightness() ? ControlPaint.Dark(BackColor)
                           : SystemColors.ControlDark;
            Color ink = Enabled ? ForeColor : disabled;
            Color quiet = Enabled ? EditionColor : disabled;
            TextRenderer.DrawText(e.Graphics, version, Font, versionBox, ink, LineFormat);
            TextFormatFlags format = EditionFormat(below);
            string word = below ? Soft.Wrap(edition, AsideFont, Math.Max(1, editionBox.Width), format) : edition;
            TextRenderer.DrawText(e.Graphics, word, AsideFont, editionBox, quiet, format);
            EditionDrawn = quiet;
        }

        // ------------------------------------------------------------------ the baseline

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        private struct TextMetric
        {
            public int Height, Ascent, Descent, InternalLeading, ExternalLeading, AveCharWidth, MaxCharWidth, Weight,
                       Overhang, DigitizedAspectX, DigitizedAspectY;
            public char FirstChar, LastChar, DefaultChar, BreakChar;
            public byte Italic, Underlined, StruckOut, PitchAndFamily, CharacterSet;
        }

        private const int LogPixelsY = 90;
        private static readonly Dictionary<string, int> baselines = new Dictionary<string, int>();

        [DllImport("gdi32.dll")] private static extern IntPtr CreateCompatibleDC(IntPtr dc);
        [DllImport("gdi32.dll")] private static extern bool DeleteDC(IntPtr dc);
        [DllImport("gdi32.dll")] private static extern int GetDeviceCaps(IntPtr dc, int index);
        [DllImport("gdi32.dll")] private static extern IntPtr SelectObject(IntPtr dc, IntPtr gdiObject);
        [DllImport("gdi32.dll")] private static extern bool DeleteObject(IntPtr gdiObject);
        [DllImport("gdi32.dll", CharSet = CharSet.Unicode)]
        private static extern IntPtr CreateFontW(int height, int width, int escapement, int orientation, int weight,
            uint italic, uint underline, uint strikeOut, uint charSet, uint outPrecision, uint clipPrecision,
            uint quality, uint pitchAndFamily, string face);
        [DllImport("gdi32.dll", CharSet = CharSet.Unicode)]
        private static extern bool GetTextMetricsW(IntPtr dc, out TextMetric metric);

        /// How far below the top of its line TextRenderer sets the baseline of `font`: GDI's ascent of the font
        /// TextRenderer makes of it - its face, its em in pixels rounded up at the measuring DC's DPI, bold or not
        /// (WindowsFont.FromFont) - selected into a DC like TextRenderer's own measuring one. Asked once per font.
        internal static int Baseline(Font font)
        {
            string face = font.FontFamily.Name;
            if (face.Length > 1 && face[0] == '@') face = face.Substring(1);
            string key = face + "|" + font.SizeInPoints.ToString("R", System.Globalization.CultureInfo.InvariantCulture) + "|" +
                         ((int)font.Style).ToString(System.Globalization.CultureInfo.InvariantCulture) + "|" +
                         font.GdiCharSet.ToString(System.Globalization.CultureInfo.InvariantCulture);
            lock (baselines)
            {
                int known;
                if (baselines.TryGetValue(key, out known)) return known;
                // Should Windows not answer: the face's own ascent at the font's height, as GDI+ has it.
                int found = (int)Math.Round(font.GetHeight() * font.FontFamily.GetCellAscent(font.Style)
                                            / font.FontFamily.GetLineSpacing(font.Style));
                IntPtr dc = CreateCompatibleDC(IntPtr.Zero);
                if (dc != IntPtr.Zero)
                {
                    try
                    {
                        int pixels = (int)Math.Ceiling(GetDeviceCaps(dc, LogPixelsY) * font.SizeInPoints / 72f);
                        IntPtr made = CreateFontW(-pixels, 0, 0, 0, (font.Style & FontStyle.Bold) != 0 ? 700 : 400,
                                                  (font.Style & FontStyle.Italic) != 0 ? 1u : 0u,
                                                  (font.Style & FontStyle.Underline) != 0 ? 1u : 0u,
                                                  (font.Style & FontStyle.Strikeout) != 0 ? 1u : 0u,
                                                  font.GdiCharSet, 0, 0, 0, 0, face);
                        if (made != IntPtr.Zero)
                        {
                            IntPtr previous = SelectObject(dc, made);
                            try
                            {
                                TextMetric metric;
                                if (GetTextMetricsW(dc, out metric)) found = metric.Ascent;
                            }
                            finally
                            {
                                SelectObject(dc, previous);
                                DeleteObject(made);
                            }
                        }
                    }
                    finally { DeleteDC(dc); }
                }
                baselines[key] = found;
                return found;
            }
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

    /// A row's own menu (v0.6.11): the Pending list's - postpone the task, let a held one continue, how its
    /// conversation resumes. Windows' menu, drawn in the window's colours rather than its own light ones: the
    /// card's ground, its ink and hairline, the accent's soft tint under the item in hand, and High Contrast's
    /// system colours when it is on. Paint only; the items, their keys and what a screen reader hears are Windows'.
    internal sealed class SoftMenu : ContextMenuStrip
    {
        internal SoftMenu()
        {
            Renderer = new SoftMenuRenderer();
            ShowImageMargin = false;
            ShowCheckMargin = true;
        }

        /// A submenu drawn as its menu is.
        internal ToolStripMenuItem Branch(string text)
        {
            var item = new ToolStripMenuItem(text);
            item.DropDown.Renderer = Renderer;
            var menu = item.DropDown as ToolStripDropDownMenu;
            if (menu != null)
            {
                menu.ShowImageMargin = false;
                menu.ShowCheckMargin = true;
            }
            return item;
        }
    }

    internal sealed class SoftMenuRenderer : ToolStripRenderer
    {
        protected override void OnRenderToolStripBackground(ToolStripRenderEventArgs e)
        {
            using (var ground = new SolidBrush(Palette.Card)) e.Graphics.FillRectangle(ground, e.AffectedBounds);
        }

        protected override void OnRenderToolStripBorder(ToolStripRenderEventArgs e)
        {
            Rectangle edge = e.AffectedBounds;
            edge.Width -= 1;
            edge.Height -= 1;
            using (var line = new Pen(Palette.Line)) e.Graphics.DrawRectangle(line, edge);
        }

        protected override void OnRenderMenuItemBackground(ToolStripItemRenderEventArgs e)
        {
            if (!e.Item.Selected || !e.Item.Enabled) return;
            var band = new Rectangle(Point.Empty, e.Item.Size);
            band.Inflate(-Soft.Px(2), 0);
            using (var tint = new SolidBrush(Palette.AccentSoft)) e.Graphics.FillRectangle(tint, band);
        }

        protected override void OnRenderItemText(ToolStripItemTextRenderEventArgs e)
        {
            bool inHand = e.Item.Selected && e.Item.Enabled;
            e.TextColor = !e.Item.Enabled ? Palette.Muted
                        : Palette.Contrast && inHand ? SystemColors.HighlightText : Palette.Ink;
            base.OnRenderItemText(e);
        }

        protected override void OnRenderArrow(ToolStripArrowRenderEventArgs e)
        {
            e.ArrowColor = e.Item != null && !e.Item.Enabled ? Palette.Muted
                         : Palette.Contrast && e.Item != null && e.Item.Selected ? SystemColors.HighlightText : Palette.Ink;
            base.OnRenderArrow(e);
        }

        protected override void OnRenderItemCheck(ToolStripItemImageRenderEventArgs e)
        {
            // The chosen one of a set, as a dot in the accent: the menu's own tick is Windows' light glyph.
            Rectangle box = e.ImageRectangle;
            int size = Math.Max(Soft.Px(6), Math.Min(box.Width, box.Height) / 2);
            var dot = new Rectangle(box.X + (box.Width - size) / 2, box.Y + (box.Height - size) / 2, size, size);
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            using (var fill = new SolidBrush(e.Item.Enabled ? Palette.Accent : Palette.Muted)) e.Graphics.FillEllipse(fill, dot);
        }

        protected override void OnRenderSeparator(ToolStripSeparatorRenderEventArgs e)
        {
            int y = e.Item.Height / 2;
            using (var rule = new SolidBrush(Palette.Line))
                e.Graphics.FillRectangle(rule, Soft.Px(4), y, Math.Max(0, e.Item.Width - Soft.Px(8)), Soft.Hairline);
        }
    }
}
