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
                // v0.6.20: mirrored as Label mirrors itself (RtlTranslateAlignment), read right to left (Mirror).
                return Mirror.Words(Mirror.Of(this), flags);
            }
        }

        /// Its text in the lines it is drawn in `width` wide inside its padding (Soft.Wrap).
        internal string Lines(int width)
        {
            return Soft.Wrap(Text, Font, width, Format);
        }

        public override Size GetPreferredSize(Size proposedSize)
        {
            if (!Soft.SplitsWords(Text)) return Mirror.Of(this) ? Agreed(proposedSize) : Remembered(proposedSize);
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

        /// v0.6.20: Label's answer for a mirrored label, held to agree with itself. Measured right to left, GDI can say a
        /// line is so wide unbounded and yet wrap it to one more line at exactly that width: Arabic help.theme came out 590
        /// px wide and two lines high unbounded, and three lines high at 590 (measured). A table sizes a column by the first
        /// answer and its row by the second, and the Appearance card kept a line's height of nothing under its last line.
        /// So the unbounded answer is widened, a pixel at a time and never past its maximum - a line held to one, to the width at which
        /// the label really is that high - the width it is then drawn at - as Label's answers agree left to right.
        private Size Agreed(Size proposedSize)
        {
            Size free = Remembered(proposedSize);
            // Only a line held to a maximum width (a help line): one that takes its cell's width is measured at that width,
            // and widening its unbounded answer past the cell changed the width it was measured at (the Advanced page's
            // other_sessions card at 200%, measured).
            if (proposedSize.Width > 1 || MaximumSize.Width <= 0) return free;
            for (int width = free.Width; width <= Math.Min(MaximumSize.Width, free.Width + 8); width++)
                if (Remembered(new Size(width, 0)).Height <= free.Height) return new Size(width, free.Height);
            return free;
        }

        // ---------------------------------------------------------------- Label's own answer, remembered
        // v0.6.17: Label's measurement of text without Korean, remembered for the whole process. Label keeps what it
        // measured only for itself and forgets it when its text or font changes, and the Advanced page builds its
        // cards anew each time a capability is opened or a read comes back - so the same help line was measured at the
        // same width again and again, about 235,000 times in one layout audit for some 3,000 different answers. In
        // Chinese and Japanese each of those is a wrapped GDI measurement that borrows glyphs from a linked face, 10 to
        // 45 ms where English takes 1.5, and one click on the page waited about 2 s for it. What is drawn is unchanged:
        // the answer is Label's own, given again only for a label that would ask exactly the same question.

        /// How many times Label itself was asked (base.GetPreferredSize) for text without Korean: the misses of the
        /// remembered answers. Read by tests/test_wrap_measure_cache.py.
        internal static long LabelMeasures;

        /// The remembered answers, at most RememberedMost of them: past that they are all let go, as Soft.Measure's are.
        private static readonly Dictionary<MeasureKey, Size> remembered = new Dictionary<MeasureKey, Size>();
        internal const int RememberedMost = 8192;

        internal static int RememberedCount
        {
            get { return remembered.Count; }
        }

        /// Label's answer for this label at `proposedSize`, from an earlier label that asked the same question where there
        /// was one. A label being disposed, or one with an image, is asked itself every time.
        private Size Remembered(Size proposedSize)
        {
            if (IsDisposed || Disposing || Image != null)
            {
                LabelMeasures++;
                return base.GetPreferredSize(proposedSize);
            }
            var key = new MeasureKey(this, proposedSize);
            Size found;
            if (remembered.TryGetValue(key, out found)) return found;
            LabelMeasures++;
            found = base.GetPreferredSize(proposedSize);
            if (remembered.Count >= RememberedMost) remembered.Clear();
            remembered[key] = found;
            return found;
        }

        /// Everything Label.GetPreferredSize reads: the label's kind (a subclass may change its frame), its text and
        /// font, the size asked and its minimum and maximum, its padding and border, how its text is laid out (Format:
        /// alignment, ellipsis, mnemonic, keyboard cues), whether it sizes itself, its flat style, its reading order and
        /// whether it measures with GDI+ - and nothing else, so two labels with one key are answered alike.
        private struct MeasureKey : IEquatable<MeasureKey>
        {
            private readonly Type kind;
            private readonly string text, face;
            private readonly float points;
            private readonly int style, unit, charSet;
            private readonly bool vertical, autoSize, compatible;
            private readonly Size proposed, least, most;
            private readonly Padding padding;
            private readonly int format, border, flat, reading;
            private readonly int hash;

            internal MeasureKey(WrapLabel label, Size proposedSize)
            {
                Font font = label.Font;
                kind = label.GetType();
                text = label.Text ?? "";
                face = font.Name;
                points = font.SizeInPoints;
                style = (int)font.Style;
                unit = (int)font.Unit;
                charSet = font.GdiCharSet;
                vertical = font.GdiVerticalFont;
                autoSize = label.AutoSize;
                compatible = label.UseCompatibleTextRendering;
                proposed = proposedSize;
                least = label.MinimumSize;
                most = label.MaximumSize;
                padding = label.Padding;
                format = (int)label.Format;
                border = (int)label.BorderStyle;
                flat = (int)label.FlatStyle;
                reading = (int)label.RightToLeft;
                unchecked
                {
                    int h = text.GetHashCode();
                    h = h * 31 + face.GetHashCode();
                    h = h * 31 + points.GetHashCode();
                    h = h * 31 + proposed.GetHashCode();
                    h = h * 31 + most.GetHashCode();
                    h = h * 31 + padding.GetHashCode();
                    h = h * 31 + format;
                    hash = h;
                }
            }

            public bool Equals(MeasureKey other)
            {
                return hash == other.hash && kind == other.kind && points == other.points && style == other.style &&
                       unit == other.unit && charSet == other.charSet && vertical == other.vertical &&
                       autoSize == other.autoSize && compatible == other.compatible && proposed == other.proposed &&
                       least == other.least && most == other.most && padding == other.padding && format == other.format &&
                       border == other.border && flat == other.flat && reading == other.reading &&
                       string.Equals(face, other.face, StringComparison.Ordinal) &&
                       string.Equals(text, other.text, StringComparison.Ordinal);
            }

            public override bool Equals(object other)
            {
                return other is MeasureKey && Equals((MeasureKey)other);
            }

            public override int GetHashCode()
            {
                return hash;
            }
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
            // v0.6.20: mirrored, the version stands at the block's right and the edition left of it, and the block where
            // Label puts its text (Mirror).
            bool mirrored = Mirror.Of(this);
            versionBox = Mirror.Box(mirrored, block.Width, versionBox);
            editionBox = Mirror.Box(mirrored, block.Width, editionBox);
            ContentAlignment align = Mirror.Align(mirrored, TextAlign);
            const ContentAlignment middle = ContentAlignment.MiddleLeft | ContentAlignment.MiddleCenter | ContentAlignment.MiddleRight;
            const ContentAlignment bottom = ContentAlignment.BottomLeft | ContentAlignment.BottomCenter | ContentAlignment.BottomRight;
            const ContentAlignment centre = ContentAlignment.TopCenter | ContentAlignment.MiddleCenter | ContentAlignment.BottomCenter;
            const ContentAlignment right = ContentAlignment.TopRight | ContentAlignment.MiddleRight | ContentAlignment.BottomRight;
            int x = (align & centre) != 0 ? face.X + (face.Width - block.Width) / 2
                  : (align & right) != 0 ? face.Right - block.Width : face.X;
            int y = (align & middle) != 0 ? face.Y + (face.Height - block.Height) / 2
                  : (align & bottom) != 0 ? face.Bottom - block.Height : face.Y;
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
            TextFormatFlags format = Mirror.Words(Mirror.Of(this), EditionFormat(below));
            string word = below ? Soft.Wrap(edition, AsideFont, Math.Max(1, editionBox.Width), format) : edition;
            TextRenderer.DrawText(e.Graphics, word, AsideFont, editionBox, quiet, format);
            EditionDrawn = quiet;
        }

        // ------------------------------------------------------------------ the baseline

        [StructLayout(LayoutKind.Sequential, CharSet = System.Runtime.InteropServices.CharSet.Unicode)]
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
    /// The row under the pointer in a list (v0.6.23): which one, and how far its flat tint has come. A list's rows stay flat
    /// hairline rows: this is a colour, no lift and no radius, on the one row, repainted alone by one Transition - the row
    /// arriving and the row it left, which goes back as the other comes. The selected row is the page's, and is instant.
    internal sealed class RowGlow : IDisposable
    {
        private readonly ListView list;
        private readonly Transition time;
        private int row = -1, left = -1;

        internal RowGlow(ListView list)
        {
            this.list = list;
            time = new Transition(list, 1.0);
            time.Where = delegate { return Rectangle.Union(Bounds(row), Bounds(left)); };
            list.MouseMove += delegate(object sender, MouseEventArgs e) { Over(RowAt(e.Location)); };
            list.MouseLeave += delegate { Over(-1); };
        }

        /// The row it is on, or -1.
        internal int Row { get { return row; } }

        /// Whether it is on its way; its timer runs only then.
        internal bool Running { get { return time.Running; } }

        /// How far the tint of row `index` has come, 0 to 1.
        internal double Amount(int index)
        {
            if (index == row) return time.Value;
            return index == left ? 1.0 - time.Value : 0.0;
        }

        private int RowAt(Point point)
        {
            ListViewItem item = list.GetItemAt(point.X, point.Y);
            return item == null ? -1 : item.Index;
        }

        private Rectangle Bounds(int index)
        {
            if (index < 0 || index >= list.Items.Count || !list.IsHandleCreated) return Rectangle.Empty;
            Rectangle bounds = list.GetItemRect(index, ItemBoundsPortion.Entire);
            bounds.X = 0;
            bounds.Width = list.ClientSize.Width;
            return bounds;
        }

        internal void Over(int index)
        {
            if (index == row) return;
            // A row still on its way back when another is left is simply back.
            Rectangle gone = time.Running ? Bounds(left) : Rectangle.Empty;
            left = row;
            row = index;
            time.Jump(0.0);
            time.To(1.0, Motion.Allowed(list), Motion.Press);
            if (!gone.IsEmpty) list.Invalidate(gone);
        }

        public void Dispose()
        {
            time.Dispose();
        }
    }

    /// The feel of the switches a list draws in a column of its own (v0.6.23, the second round's F7: Pending's Auto-resume),
    /// as every SoftCheck switch has it and as the popup's switch for the same conversation does: the well comes up while the
    /// pointer is on the switch's cell, the knob widens while it is held down there (or Space is held on its row), and while
    /// the change it sent is awaited the switch fades halfway into its row - only once BusyHold's moment is over with the call
    /// still running, as a button turned off for a call does, so a call answered in time shows nothing. The knob itself moves
    /// only when the reply has been read (the caller's glide, FollowResumeSwitches). Each row is the caller's key - a record's
    /// id - and where its switch is now the caller's `cell`, asked each frame, so a list that scrolls is followed. Paint only:
    /// no layout, no bitmap, a timer only while something moves; with motion reduced or the list out of sight, at once.
    internal sealed class ListSwitchFeel : IBusyFace, IDisposable
    {
        private readonly Control list;
        private readonly Func<string, Rectangle> cell;
        private readonly Func<bool> stillWaiting;
        private readonly Transition hot, down;
        private readonly Dictionary<string, Transition> awaited = new Dictionary<string, Transition>();
        private readonly HashSet<string> holding = new HashSet<string>();
        private string hotKey, hotLeft, downKey;

        /// `stillWaiting` answers whether a call is still running when BusyHold's moment ends: the moment also ends when the
        /// last call is over, and then nothing fades.
        internal ListSwitchFeel(Control list, Func<string, Rectangle> cell, Func<bool> stillWaiting)
        {
            this.list = list;
            this.cell = cell;
            this.stillWaiting = stillWaiting;
            hot = new Transition(list, 1.0);
            hot.Where = delegate { return Both(Cell(hotKey), Cell(hotLeft)); };
            down = new Transition(list, 0.0);
            down.Where = delegate { return Cell(downKey); };
        }

        private Rectangle Cell(string key)
        {
            return key == null || list.IsDisposed ? Rectangle.Empty : cell(key);
        }

        private static Rectangle Both(Rectangle one, Rectangle other)
        {
            if (one.IsEmpty) return other;
            return other.IsEmpty ? one : Rectangle.Union(one, other);
        }

        /// The switch whose cell the pointer is on, or null.
        internal string Hot { get { return hotKey; } }

        /// Whether anything of it is on its way; a timer runs only then (for the tests).
        internal bool Running
        {
            get
            {
                if (hot.Running || down.Running) return true;
                foreach (Transition fade in awaited.Values) if (fade.Running) return true;
                return false;
            }
        }

        /// How far the switch of `key` has come up under the pointer, 0 to 1.
        internal double Hover(string key)
        {
            if (key == null) return 0.0;
            if (key == hotKey) return hot.Value;
            return key == hotLeft ? 1.0 - hot.Value : 0.0;
        }

        /// How far it is held down, 0 to 1.
        internal double Press(string key)
        {
            return key != null && key == downKey ? down.Value : 0.0;
        }

        /// How live it is drawn, 1 at rest and 0 halfway into its row while its change is awaited.
        internal double Live(string key)
        {
            Transition fade;
            return key != null && awaited.TryGetValue(key, out fade) ? fade.Value : 1.0;
        }

        /// The pointer is on the switch of `key` now, or on none (null).
        internal void Over(string key)
        {
            if (key == hotKey) return;
            // Off its cell a switch held down is let go, as a SoftCheck is when the pointer leaves it.
            if (downKey != null && key != downKey) Held(null);
            Rectangle gone = hot.Running ? Cell(hotLeft) : Rectangle.Empty;
            hotLeft = hotKey;
            hotKey = key;
            hot.Jump(0.0);
            hot.To(1.0, Motion.Allowed(list));
            if (!gone.IsEmpty) list.Invalidate(gone);
        }

        /// The switch of `key` is held down now, or none is (null).
        internal void Held(string key)
        {
            if (key == null)
            {
                if (downKey != null) down.To(0.0, Motion.Allowed(list), Motion.Press);
                return;
            }
            if (key != downKey)
            {
                Rectangle was = Cell(downKey);
                downKey = key;
                down.Jump(0.0);
                if (!was.IsEmpty) list.Invalidate(was);
            }
            down.To(1.0, Motion.Allowed(list), Motion.Press);
        }

        /// The change the switch of `key` sent is awaited (`on`), or its answer has come.
        internal void Awaiting(string key, bool on)
        {
            if (key == null) return;
            if (!on)
            {
                holding.Remove(key);
                Fade(key, 1.0);
                return;
            }
            // For BusyHold's moment it looks as it did; a call over by then has shown nothing.
            if (BusyHold.Join(this))
            {
                holding.Add(key);
                return;
            }
            Fade(key, 0.0);
        }

        void IBusyFace.HoldEnded()
        {
            var keys = new List<string>(holding);
            holding.Clear();
            if (stillWaiting != null && !stillWaiting()) return;
            foreach (string key in keys) Fade(key, 0.0);
        }

        private void Fade(string key, double to)
        {
            Transition fade;
            if (!awaited.TryGetValue(key, out fade))
            {
                if (to >= 1.0) return;
                fade = new Transition(list, 1.0);
                string row = key;
                fade.Where = delegate { return Cell(row); };
                awaited[key] = fade;
            }
            fade.To(to, Motion.Allowed(list));
        }

        /// The row of `key` has left the list.
        internal void Forget(string key)
        {
            Transition fade;
            if (key != null && awaited.TryGetValue(key, out fade))
            {
                fade.Dispose();
                awaited.Remove(key);
            }
            holding.Remove(key ?? "");
            if (key == hotKey) hotKey = null;
            if (key == hotLeft) hotLeft = null;
            if (key == downKey) downKey = null;
        }

        public void Dispose()
        {
            hot.Dispose();
            down.Dispose();
            foreach (Transition fade in awaited.Values) fade.Dispose();
            awaited.Clear();
        }
    }

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
            Glow = new RowGlow(this);
            Disposed += delegate { Glow.Dispose(); };
        }

        /// The row under the pointer (DrawCell).
        internal readonly RowGlow Glow;

        // ---------------------------------------------------------------- rows held while the window is made
        // v0.6.23 (the second round, idlefix2): a list made ready ahead (SettingsForm.PrepareNext) has its rows before
        // its window, and making the window inserted every one of them in that one step: History's list with its 200
        // rows held the window's thread for up to 450 ms, and the header's light and every glide with it (measured
        // 2026-11-13, months of data). So its rows are taken out just before its window is made (HoldRows) and put
        // back a slice at a time after (PutBackRows), its painting held from the first slice to the last - the same
        // rows, in the same order, chosen and focused as they were. Anything that reads or writes the rows meanwhile
        // has them all put back first (SettingsForm.Selected, FillList, ShowUnreadable, ShowPage).
        private ListViewItem[] heldRows;
        private bool[] heldChosen, heldFocused;
        private int heldBack;
        private bool redrawHeld, puttingBack;
        private const int WM_SETREDRAW = 0x000B;

        /// Whether rows are held aside (HoldRows) and not yet all put back.
        internal bool HoldsRows
        {
            get { return heldRows != null; }
        }

        /// Takes the rows out of a list whose window is not yet made, to be put back once it is; false, and nothing
        /// taken, when the window is made or there are no rows to hold.
        internal bool HoldRows()
        {
            if (heldRows != null || IsHandleCreated || IsDisposed || Items.Count == 0) return false;
            heldRows = new ListViewItem[Items.Count];
            Items.CopyTo(heldRows, 0);
            heldChosen = new bool[heldRows.Length];
            heldFocused = new bool[heldRows.Length];
            for (int i = 0; i < heldRows.Length; i++)
            {
                heldChosen[i] = heldRows[i].Selected;
                heldFocused[i] = heldRows[i].Focused;
            }
            heldBack = 0;
            Items.Clear();
            return true;
        }

        /// Puts held rows back, in their order, until `milliseconds` have gone (at least a few rows each time); true
        /// once all are back. Painting is held from the first row put back to the last by the window's own switch
        /// (WM_SETREDRAW): ListView's BeginUpdate keeps every row added under it until EndUpdate and inserts them all
        /// there, in one step again.
        internal bool PutBackRows(int milliseconds)
        {
            if (heldRows == null) return true;
            // Asked again from inside a slice - a row chosen again tells the list's SelectedIndexChanged, whose handler
            // reads the rows (SettingsForm.Selected): the slice under way goes on, and the rows it has put back are read.
            if (puttingBack) return false;
            if (IsDisposed)
            {
                heldRows = null;
                return true;
            }
            puttingBack = true;
            try
            {
                if (heldBack == 0 && IsHandleCreated && Soft.OwnVisible(this))
                {
                    SendHeaderMessage(Handle, WM_SETREDRAW, IntPtr.Zero, IntPtr.Zero);
                    redrawHeld = true;
                }
                var slice = System.Diagnostics.Stopwatch.StartNew();
                do
                {
                    int from = heldBack, count = Math.Min(heldRows.Length - from, 8);
                    var some = new ListViewItem[count];
                    Array.Copy(heldRows, from, some, 0, count);
                    heldBack = from + count;
                    Items.AddRange(some);
                    for (int i = from; i < from + count; i++)
                    {
                        if (heldRows[i].Selected != heldChosen[i]) heldRows[i].Selected = heldChosen[i];
                        if (heldFocused[i] && !heldRows[i].Focused) heldRows[i].Focused = true;
                    }
                }
                while (heldBack < heldRows.Length && slice.ElapsedMilliseconds < milliseconds);
                if (heldBack < heldRows.Length) return false;
                heldRows = null;
                heldChosen = heldFocused = null;
                if (redrawHeld && IsHandleCreated)
                {
                    SendHeaderMessage(Handle, WM_SETREDRAW, (IntPtr)1, IntPtr.Zero);
                    Invalidate();
                }
                redrawHeld = false;
                return true;
            }
            finally { puttingBack = false; }
        }

        /// Puts every held row back at once.
        internal void PutBackRows()
        {
            PutBackRows(int.MaxValue);
        }

        protected override void OnHandleCreated(EventArgs e)
        {
            base.OnHandleCreated(e);
            // v0.6.20: only in a picture drawn at a scale pinned apart from this machine's (SettingsForm.RenderPinned).
            if (SettingsForm.RenderPinned) PinnedHeader.Attach(this);
        }

        [DllImport("user32.dll", EntryPoint = "SendMessageW")]
        private static extern IntPtr SendHeaderMessage(IntPtr window, int message, IntPtr wParam, IntPtr lParam);

        [DllImport("user32.dll")]
        private static extern int GetDpiForWindow(IntPtr window);

        [DllImport("gdi32.dll")]
        private static extern IntPtr CreateCompatibleDC(IntPtr dc);

        [DllImport("gdi32.dll")]
        private static extern bool DeleteDC(IntPtr dc);

        [DllImport("gdi32.dll")]
        private static extern IntPtr SelectObject(IntPtr dc, IntPtr item);

        [DllImport("gdi32.dll")]
        private static extern bool DeleteObject(IntPtr item);

        [DllImport("gdi32.dll", CharSet = CharSet.Unicode)]
        private static extern bool GetTextMetricsW(IntPtr dc, out HeaderMetric metric);

        [StructLayout(LayoutKind.Sequential, CharSet = System.Runtime.InteropServices.CharSet.Unicode)]
        private struct HeaderMetric
        {
            public int Height, Ascent, Descent, InternalLeading, ExternalLeading, AveCharWidth, MaxCharWidth, Weight,
                       Overhang, DigitizedAspectX, DigitizedAspectY;
            public char FirstChar, LastChar, DefaultChar, BreakChar;
            public byte Italic, Underlined, StruckOut, PitchAndFamily, Set;
        }

        /// v0.6.20: the list's column header as tall as Windows makes it on a monitor of the pinned scale. Windows lays the
        /// header out at the DPI of the monitor the list is on - its text's height and a margin it scales with that DPI -
        /// and the window draws everything else at the pinned scale (SettingsForm.AdoptRenderScale): on a 200 % laptop a
        /// picture pinned at 150 % had its headers 2 px taller, and every row under them 2 px lower, than a window on a
        /// 150 % monitor. The header's answer to HDM_LAYOUT is taken, its margin - what it gives beyond the font's height -
        /// scaled from the monitor's DPI to the pinned scale, and the list told that height instead.
        private sealed class PinnedHeader : NativeWindow
        {
            private const int LVM_GETHEADER = 0x101F;
            private const int HDM_LAYOUT = 0x1205;
            private readonly SoftList list;

            private PinnedHeader(SoftList list) { this.list = list; }

            internal static void Attach(SoftList list)
            {
                IntPtr header = SendHeaderMessage(list.Handle, LVM_GETHEADER, IntPtr.Zero, IntPtr.Zero);
                if (header == IntPtr.Zero) return;
                new PinnedHeader(list).AssignHandle(header);
                // Laid out again now, with this answering (WM_SIZE, as a resize lays the header out).
                Size client = list.ClientSize;
                SendHeaderMessage(list.Handle, 0x0005, IntPtr.Zero, (IntPtr)(((client.Height & 0xFFFF) << 16) | (client.Width & 0xFFFF)));
            }

            protected override void WndProc(ref Message m)
            {
                base.WndProc(ref m);
                if (m.Msg != HDM_LAYOUT || m.LParam == IntPtr.Zero) return;
                try
                {
                    // HDLAYOUT: the rectangle the header and the rows share, and where the header goes (WINDOWPOS).
                    IntPtr area = Marshal.ReadIntPtr(m.LParam);
                    IntPtr place = Marshal.ReadIntPtr(m.LParam, IntPtr.Size);
                    if (area == IntPtr.Zero || place == IntPtr.Zero) return;
                    // WINDOWPOS: hwnd, hwndInsertAfter, x, y, cx, cy, flags.
                    int cyAt = 2 * IntPtr.Size + 12;
                    int given = Marshal.ReadInt32(place, cyAt);
                    int wanted = Pinned(given);
                    if (wanted == given) return;
                    Marshal.WriteInt32(place, cyAt, wanted);
                    // RECT: left, top, right, bottom - the rows start under the header.
                    Marshal.WriteInt32(area, 4, Marshal.ReadInt32(area, 4) + wanted - given);
                }
                catch (Exception) { /* a picture's header at Windows' height: a pixel or two off, never a failure */ }
            }

            /// The header's height `given` at the monitor's DPI, at the pinned scale: the font's height, and the margin
            /// scaled from that DPI to the scale.
            private int Pinned(int given)
            {
                int dpi = GetDpiForWindow(Handle);
                if (given <= 0 || dpi < 48) return given;
                double scale = SettingsForm.DisplayScale * 96.0;
                if (Math.Abs(scale - dpi) < 0.5) return given;
                int text = TextHeight(list.Font);
                if (text <= 0 || text >= given) return given;
                return text + (int)Math.Round((given - text) * scale / dpi);
            }

            private static int TextHeight(Font font)
            {
                IntPtr dc = CreateCompatibleDC(IntPtr.Zero);
                if (dc == IntPtr.Zero) return 0;
                IntPtr made = font.ToHfont();
                try
                {
                    IntPtr previous = SelectObject(dc, made);
                    HeaderMetric metric;
                    bool read = GetTextMetricsW(dc, out metric);
                    SelectObject(dc, previous);
                    return read ? metric.Height : 0;
                }
                finally
                {
                    DeleteObject(made);
                    DeleteDC(dc);
                }
            }
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
        // v0.6.20: whether a mirrored list wider than it is has been scrolled to its first column, at the right
        // (StartAtFirstColumn); let go when its columns fit again.
        private bool startedRight;

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
            // v0.6.20: never mirrored by Windows, in a mirrored window too: Windows would move its own bar to the left, where
            // the clip shows it. Its columns go the other way instead (MirrorColumns), and its rows are drawn mirrored.
            list.RightToLeft = RightToLeft.No;
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

        /// Whether the list's columns stand in the other order, the first at the right: in a mirrored window (Mirror).
        internal bool ColumnsMirrored
        {
            get
            {
                int count = List.Columns.Count;
                // One column, or none, has no other order: it is the same either way.
                return count <= 1 || List.Columns[0].DisplayIndex == count - 1;
            }
        }

        /// The list's columns in the order its window reads: the first at the left, or in a mirrored window at the right
        /// (v0.6.20). The order they are declared and filled in, and every width, stay as they are.
        internal void MirrorColumns()
        {
            bool mirrored = Mirror.Of(this);
            int count = List.Columns.Count;
            for (int i = 0; i < count; i++)
            {
                int wanted = mirrored ? count - 1 - i : i;
                if (List.Columns[i].DisplayIndex != wanted) List.Columns[i].DisplayIndex = wanted;
            }
        }

        protected override void OnLayout(LayoutEventArgs levent)
        {
            base.OnLayout(levent);
            if (Mirror.Of(this) || List.Columns.Count > 1 && ColumnsMirrored) MirrorColumns();
            native = NativeBar;
            nativeAcross = NativeAcross;
            int rows = Math.Max(0, Width - (native ? SoftBar.Gutter : 0));
            // v0.6.20: mirrored, the soft bar stands at the left and the rows start past its gutter (Mirror). The list
            // itself is not mirrored by Windows - its own bar would move to the left, into the clip - and its columns are
            // put in the other order by the window instead (SettingsForm.MirrorColumns).
            bool mirrored = Mirror.Of(this);
            int tall = Math.Max(0, Height - (nativeAcross ? SoftBar.Gutter : 0));
            // The list's own bar is as wide as the list is wider than its rows; before it has one,
            // Windows' measure of a scroll bar. The same below, for its bar across the bottom.
            int beside = native ? Math.Max(0, List.Width - List.ClientSize.Width) : 0;
            if (native && beside == 0) beside = SystemInformation.VerticalScrollBarWidth;
            int below = nativeAcross ? Math.Max(0, List.Height - List.ClientSize.Height) : 0;
            if (nativeAcross && below == 0) below = SystemInformation.HorizontalScrollBarHeight;
            clip.SetBounds(mirrored ? Width - rows : 0, 0, rows, tall);
            if (List.Width != rows + beside || List.Height != tall + below) FromFirstPixel();
            List.SetBounds(0, 0, rows + beside, tall + below);
            Read();
            bar.Track = native ? TrackBounds() : Rectangle.Empty;
            acrossBar.Track = nativeAcross ? AcrossBounds() : Rectangle.Empty;
            StartAtFirstColumn();
        }

        /// v0.6.20 (the final's live acceptance, A5): a list scrolled sideways is scrolled back to its left edge before it
        /// takes another size. Its columns are fitted to its new width as it takes it (SettingsForm.FitColumns, on the
        /// list's ClientSizeChanged, inside Windows' own handling of the size), and a list that had been scrolled sideways
        /// and whose columns then fitted kept its headings and rows as far right as it had been scrolled, with no bar left
        /// to scroll them back: Windows had taken the scroll back twice. A mirrored list is scrolled to its first column
        /// whenever its columns are wider than it is (StartAtFirstColumn) - and History, built while the window had not
        /// yet given it its room (133 px wide, no row tall), was scrolled 107 px to the right before it took its full
        /// width: in Arabic and Hebrew it showed its End column alone, at its right, and every other column past its edge,
        /// headings and rows blank. Left to right the same followed a sideways scroll and a wider window. Mirrored, a list
        /// still wider than its columns once it has its size starts at its first column again.
        private void FromFirstPixel()
        {
            if (!List.IsHandleCreated || !NativeAcross) return;
            Read();
            int at = sideScroll.Position - sideScroll.Min;
            if (at > 0) SendMessage(List.Handle, LVM_SCROLL, new IntPtr(-at), IntPtr.Zero);
            startedRight = false;
        }

        /// Whether the list now shows its first column: at the left, scrolled not at all, or at the right where it stands
        /// mirrored, scrolled sideways as far as it goes. True for a list whose columns fit.
        internal bool AtFirstColumn
        {
            get
            {
                Read();
                int range = Math.Max(0, sideScroll.Max - sideScroll.Min + 1 - Math.Max(1, sideScroll.Page));
                int at = Math.Max(0, sideScroll.Position - sideScroll.Min);
                // Left to right the first column is at the left: scrolled not at all.
                return !nativeAcross || range == 0 || (ColumnsMirrored && List.Columns.Count > 1 ? at >= range : at == 0);
            }
        }

        /// v0.6.20: a mirrored list whose columns are wider than it is - in a window narrower than they shrink to - starts
        /// scrolled to its first column, which stands at the right of its columns (MirrorColumns), as a list left to right
        /// starts at its first column at the left. Once each time its columns stop fitting; the person scrolls it after that.
        private void StartAtFirstColumn()
        {
            if (!nativeAcross)
            {
                startedRight = false;
                return;
            }
            if (startedRight || !Mirror.Of(this) || !List.IsHandleCreated) return;
            startedRight = true;
            Read();
            int range = Math.Max(0, sideScroll.Max - sideScroll.Min + 1 - Math.Max(1, sideScroll.Page));
            int by = range - Math.Max(0, sideScroll.Position - sideScroll.Min);
            if (by > 0) SendMessage(List.Handle, LVM_SCROLL, new IntPtr(by), IntPtr.Zero);
            Read();
            acrossBar.Track = AcrossBounds();
        }

        // Beside the rows: from under the column headings to the bottom, or to the bar along it.
        private Rectangle TrackBounds()
        {
            int margin = Soft.Px(SoftBar.TrackMargin);
            int top = List.Items.Count > 0 && List.View == View.Details ? Math.Max(0, List.GetItemRect(List.TopItem != null ? List.TopItem.Index : 0).Top) : 0;
            int bottom = Height - (nativeAcross ? SoftBar.Gutter : 0);
            return Mirror.Box(Mirror.Of(this), Width,
                              new Rectangle(Width - margin - Soft.Px(SoftBar.TrackWidth), top + margin, Soft.Px(SoftBar.TrackWidth),
                                            Math.Max(0, bottom - top - 2 * margin)));
        }

        // Along the bottom, under the rows: from the left edge to the bar beside them, if that shows.
        private Rectangle AcrossBounds()
        {
            int margin = Soft.Px(SoftBar.TrackMargin);
            int right = Width - (native ? SoftBar.Gutter : 0);
            return Mirror.Box(Mirror.Of(this), Width,
                              new Rectangle(margin, Height - margin - Soft.Px(SoftBar.TrackWidth), Math.Max(0, right - 2 * margin),
                                            Soft.Px(SoftBar.TrackWidth)));
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

        /// The gutters the soft bars run in, painted again over a picture of the window: DrawToBitmap draws the list
        /// whole, its own scroll bars with it, past the clip that hides them on screen, and so over the soft bar beside
        /// them (WindowRender.RenderPicture; the Advanced features pictures of v0.6.19-beta.4, the owner 2026-10-26).
        internal void PaintGutters(Graphics g)
        {
            using (var brush = new SolidBrush(BackColor))
            {
                if (native) g.FillRectangle(brush, Mirror.X(Mirror.Of(this), Width, Width - SoftBar.Gutter, SoftBar.Gutter), 0,
                                            SoftBar.Gutter, Height);
                if (nativeAcross) g.FillRectangle(brush, 0, Height - SoftBar.Gutter, Width, SoftBar.Gutter);
            }
            if (native) bar.Paint(g);
            if (nativeAcross) acrossBar.Paint(g);
        }
    }
}
