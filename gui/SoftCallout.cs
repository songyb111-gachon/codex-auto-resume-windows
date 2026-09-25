// Codex Auto Resume - the callout: a notice set apart, as the panel sets one apart.

using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Windows.Forms;

namespace CodexAutoResume
{
    /// A notice set apart from what is around it, the panel's `.callout` (v0.6.10): a flat `accent_soft` ground
    /// with the control's corners, an "i" badge - a circle in the accent with the letter in `on_accent` - and the
    /// notice itself in ink beside it, padded, spaced and sized by the brand's own numbers (Brand.CalloutPad*,
    /// CalloutGap, CalloutBadge). Flat, as the panel's is: no lift and no well. In High Contrast the tint becomes an
    /// edge - the card's own ground inside a hairline. The notice is drawn here, as the Custom message's quote is
    /// (SoftQuote), wrapped where the other text of the window wraps: Korean between its words (Soft.Wrap). A label
    /// inside it sized itself to one line and ran out of the card; a screen reader hears the notice as the
    /// callout's name.
    ///
    /// Until v0.6.10 the window said the same notices as accent-coloured help text, and the callout's numbers the
    /// brand generates for it were used by nothing.
    internal sealed class SoftCallout : Panel
    {
        private readonly string notice;

        // Wrapped as a text box wraps, as every wrapped line of the window is (WrapLabel.Format).
        private const TextFormatFlags Words = TextFormatFlags.WordBreak | TextFormatFlags.TextBoxControl |
                                              TextFormatFlags.Left | TextFormatFlags.NoPrefix;

        internal SoftCallout(string text)
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                     ControlStyles.UserPaint | ControlStyles.ResizeRedraw, true);
            notice = text ?? "";
            TabStop = false;
            AutoSize = true;
            AutoSizeMode = AutoSizeMode.GrowAndShrink;
            BackColor = Tint;
            ForeColor = Palette.Ink;
            // The notice starts after the badge and the gap beside it; the badge stands in the left padding.
            Padding = new Padding(Soft.Px(Brand.CalloutPadLeft + Brand.CalloutBadge + Brand.CalloutGap), Soft.Px(Brand.CalloutPadTop),
                                  Soft.Px(Brand.CalloutPadRight), Soft.Px(Brand.CalloutPadBottom));
            AccessibleRole = AccessibleRole.StaticText;
            AccessibleName = notice;
        }

        /// What it says.
        internal string Notice
        {
            get { return notice; }
        }

        /// Its ground: the accent's soft tint, or in High Contrast the card's own, which the edge then outlines.
        internal static Color Tint
        {
            get { return Palette.Contrast ? Palette.Card : Palette.AccentSoft; }
        }

        /// The room the notice has beside the badge, `width` wide.
        private int Inner(int width)
        {
            return Math.Max(1, width - Padding.Horizontal);
        }

        /// How tall the notice is in `inner` pixels of width, in the lines it is drawn in.
        private int TextHeight(int inner)
        {
            return Soft.Measure(Soft.Wrap(notice, Font, inner, Words), Font, inner, Words).Height;
        }

        /// As wide as it is offered - the card's width - and as tall as the notice wraps to there, never less than
        /// the badge.
        public override Size GetPreferredSize(Size proposedSize)
        {
            int width = proposedSize.Width > 1 && proposedSize.Width < 20000 ? proposedSize.Width
                      : Width > Padding.Horizontal ? Width : Soft.Px(460);
            return new Size(width, Math.Max(TextHeight(Inner(width)), Soft.Px(Brand.CalloutBadge)) + Padding.Vertical);
        }

        /// What it needs and does not have, for the layout audit, or null: the height its notice wraps to at its
        /// width, and room for its longest word, which a text box would otherwise cut in two.
        internal string Fits()
        {
            int needed = GetPreferredSize(new Size(Width, 0)).Height;
            if (needed > Height) return "needs " + needed + " high, has " + Height;
            int inner = Inner(Width);
            // Split at white space (a null separator), never at a constant array: the in-box compiler stores one in
            // a class it names with a fresh random GUID, and the build would not be reproducible (normalize_pe.py).
            foreach (string word in notice.Split((char[])null, StringSplitOptions.RemoveEmptyEntries))
            {
                int wide = TextRenderer.MeasureText(word, Font, new Size(int.MaxValue, int.MaxValue),
                                                    TextFormatFlags.SingleLine | TextFormatFlags.NoPadding).Width;
                if (wide > inner) return "a word needs " + wide + " wide, has " + inner;
            }
            return null;
        }

        protected override void OnFontChanged(EventArgs e)
        {
            base.OnFontChanged(e);
            if (Parent != null) Parent.PerformLayout();
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            float radius = Soft.PxF(Brand.RadiusControl);
            Ground.PaintBehind(this, g, ClientRectangle, radius);
            GraphicsState state = g.Save();
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.PixelOffsetMode = PixelOffsetMode.Half;
            using (var path = Soft.Rounded(ClientRectangle, radius))
                g.FillPath(Soft.Fill(Tint), path);
            // The badge, level with the notice's first line.
            int badge = Soft.Px(Brand.CalloutBadge);
            var circle = new RectangleF(Soft.Px(Brand.CalloutPadLeft), Padding.Top + (Font.Height - badge) / 2f, badge, badge);
            g.FillEllipse(Soft.Fill(Palette.Accent), circle);
            g.Restore(state);
            if (Palette.Contrast) Soft.Edge(g, ClientRectangle, radius, Palette.Line, Soft.Hairline);
            TextRenderer.DrawText(g, "i", Soft.RoleFont("heading"), Rectangle.Round(circle), Palette.OnAccent,
                                  TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter |
                                  TextFormatFlags.SingleLine | TextFormatFlags.NoPadding | TextFormatFlags.NoPrefix);
            int inner = Inner(Width);
            TextRenderer.DrawText(g, Soft.Wrap(notice, Font, inner, Words), Font,
                                  new Rectangle(Padding.Left, Padding.Top, inner, Math.Max(0, Height - Padding.Vertical)),
                                  ForeColor, Words);
        }
    }
}
