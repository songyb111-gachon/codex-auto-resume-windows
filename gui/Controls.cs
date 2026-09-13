// Codex Auto Resume - the soft controls the window is drawn with.
//
// v0.6.3 moved the window from flat cards with an accent rail to the soft, rounded language
// the tray popup and the panel in Codex share: a card is the same material as the window,
// lifted by a small shadow; a control rests on it; a value sits in a shallow well. Every
// colour and size comes from gui/Brand.cs, generated from src/codex_auto_resume/brand.py.
//
// Three rules hold for everything here:
//
// * Nothing depends on seeing a shadow. Every card and control keeps a hairline edge, every
//   state has a word beside its colour, and in High Contrast mode the shadows, tints and
//   motion are gone and system colours are used throughout.
// * Every control is still the standard control underneath - a Button is a Button, a check
//   box a CheckBox, a choice a RadioButton - so keyboard, focus and screen readers behave as
//   they always did. Only the painting is ours.
// * Motion is a state, not decoration, and it stops when Windows is asked to reduce motion,
//   when this product's own "Reduce motion" setting is on, or when nothing is visible.
//
// C# 5 (the in-box compiler): no string interpolation, no null-conditional operator.

using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Runtime.InteropServices;
using System.Windows.Forms;

namespace CodexAutoResume
{
    /// The palette as the window uses it, with High Contrast honoured in one place.
    internal static class Palette
    {
        internal static readonly bool Contrast = SystemInformation.HighContrast;
        internal static readonly Color Ink        = Contrast ? SystemColors.WindowText : Brand.Ink;
        internal static readonly Color Muted      = Contrast ? SystemColors.GrayText : Brand.Muted;
        internal static readonly Color Secondary  = Contrast ? SystemColors.WindowText : Brand.Muted;
        internal static readonly Color Line       = Contrast ? SystemColors.WindowFrame : Brand.Line;
        internal static readonly Color Surface    = Contrast ? SystemColors.Window : Brand.Surface;
        internal static readonly Color Canvas     = Contrast ? SystemColors.Control : Brand.Canvas;
        internal static readonly Color Raised     = Contrast ? SystemColors.Window : Brand.Raised;
        internal static readonly Color Inset      = Contrast ? SystemColors.Window : Brand.Inset;
        internal static readonly Color Accent     = Contrast ? SystemColors.Highlight : Brand.Accent;
        internal static readonly Color OnAccent   = Contrast ? SystemColors.HighlightText : Brand.OnAccent;
        internal static readonly Color AccentSoft = Contrast ? SystemColors.Highlight : Brand.AccentSoft;
        internal static readonly Color Focus      = Contrast ? SystemColors.WindowText : Brand.Focus;
        internal static readonly Color Active     = Contrast ? SystemColors.Highlight : Brand.Active;
        internal static readonly Color Idle       = Contrast ? SystemColors.GrayText : Brand.Idle;
        internal static readonly Color Attention  = Contrast ? SystemColors.WindowText : Brand.Attention;
        internal static readonly Color Success    = Contrast ? SystemColors.WindowText : Brand.Success;
        internal static readonly Color Waiting    = Contrast ? SystemColors.WindowText : Brand.Waiting;
        internal static readonly Color Warning    = Contrast ? SystemColors.WindowText : Brand.Warning;
        internal static readonly Color Danger     = Contrast ? SystemColors.WindowText : Brand.Danger;
        internal static readonly Color Paused     = Contrast ? SystemColors.GrayText : Brand.Paused;
    }

    /// Drawing helpers shared by every soft control.
    internal static class Soft
    {
        [DllImport("user32.dll")]
        private static extern bool SystemParametersInfo(int action, int param, ref bool value, int winIni);

        private const int SPI_GETCLIENTAREAANIMATION = 0x1042;

        /// This product's own "Reduce motion" setting, adopted when the settings are read.
        internal static bool ReduceMotionSetting;

        /// Whether anything may move. Windows' "Animation effects" switch, this product's own
        /// setting, and High Contrast each turn motion off; nothing turns it back on.
        internal static bool ReduceMotion
        {
            get
            {
                if (ReduceMotionSetting || Palette.Contrast) return true;
                try
                {
                    bool animate = true;
                    if (SystemParametersInfo(SPI_GETCLIENTAREAANIMATION, 0, ref animate, 0)) return !animate;
                }
                catch (Exception) { }
                return false;
            }
        }

        internal static int Px(int atNinetySix)
        {
            return (int)Math.Round(atNinetySix * SettingsForm.DpiScale);
        }

        internal static float PxF(double atNinetySix)
        {
            return (float)(atNinetySix * SettingsForm.DpiScale);
        }

        internal static Color Mix(Color from, Color to, double amount)
        {
            amount = Math.Max(0, Math.Min(1, amount));
            return Color.FromArgb(
                (int)Math.Round(from.R + (to.R - from.R) * amount),
                (int)Math.Round(from.G + (to.G - from.G) * amount),
                (int)Math.Round(from.B + (to.B - from.B) * amount));
        }

        internal static Color WithAlpha(Color colour, double opacity)
        {
            return Color.FromArgb((int)Math.Round(255 * Math.Max(0, Math.Min(1, opacity))), colour);
        }

        internal static GraphicsPath Rounded(RectangleF bounds, float radius)
        {
            var path = new GraphicsPath();
            float diameter = Math.Min(radius * 2, Math.Min(bounds.Width, bounds.Height));
            if (diameter <= 1f)
            {
                path.AddRectangle(bounds);
                return path;
            }
            path.AddArc(bounds.X, bounds.Y, diameter, diameter, 180, 90);
            path.AddArc(bounds.Right - diameter, bounds.Y, diameter, diameter, 270, 90);
            path.AddArc(bounds.Right - diameter, bounds.Bottom - diameter, diameter, diameter, 0, 90);
            path.AddArc(bounds.X, bounds.Bottom - diameter, diameter, diameter, 90, 90);
            path.CloseFigure();
            return path;
        }

        /// A raised surface: a soft shadow below and to the right, a faint highlight above and
        /// to the left, the fill, and a hairline. Small on purpose - exaggerated embossing is
        /// what makes soft interfaces unreadable.
        internal static void Raise(Graphics g, RectangleF body, float radius, Color fill, bool strong)
        {
            g.SmoothingMode = SmoothingMode.AntiAlias;
            if (!Palette.Contrast)
            {
                int steps = 6;
                float spread = PxF(Brand.RaisedBlur * (strong ? 0.5 : 0.32));
                float drop = PxF(Brand.RaisedOffset * (strong ? 0.6 : 0.35));
                for (int i = steps; i >= 1; i--)
                {
                    float grow = spread * i / steps;
                    var layer = new RectangleF(body.X - grow * 0.6f, body.Y - grow * 0.35f + drop,
                                               body.Width + grow * 1.2f, body.Height + grow * 1.1f);
                    double opacity = Brand.ShadowOpacity * (strong ? 0.20 : 0.14) * (1.0 - (i - 1.0) / steps);
                    using (var path = Rounded(layer, radius + grow))
                    using (var brush = new SolidBrush(WithAlpha(Brand.ShadowDark, opacity)))
                        g.FillPath(brush, path);
                }
                var light = new RectangleF(body.X - PxF(1), body.Y - PxF(1), body.Width, body.Height);
                using (var path = Rounded(light, radius))
                using (var brush = new SolidBrush(WithAlpha(Brand.ShadowLight, 0.85)))
                    g.FillPath(brush, path);
            }
            using (var path = Rounded(body, radius))
            {
                using (var brush = new SolidBrush(fill)) g.FillPath(brush, path);
                using (var pen = new Pen(Palette.Contrast ? Palette.Line : WithAlpha(Palette.Line, 0.9), 1f))
                    g.DrawPath(pen, path);
            }
        }

        /// A shallow well a value sits in.
        internal static void Well(Graphics g, RectangleF body, float radius, bool focused)
        {
            g.SmoothingMode = SmoothingMode.AntiAlias;
            using (var path = Rounded(body, radius))
            {
                using (var brush = new SolidBrush(Palette.Inset)) g.FillPath(brush, path);
                if (!Palette.Contrast)
                {
                    // The inner shadow along the top edge that makes a well read as lower than
                    // the card around it.
                    var region = g.Clip;
                    g.SetClip(path, CombineMode.Intersect);
                    using (var pen = new Pen(WithAlpha(Brand.ShadowDark, 0.55), PxF(2)))
                        g.DrawLine(pen, body.X, body.Y + PxF(1), body.Right, body.Y + PxF(1));
                    g.Clip = region;
                }
                using (var pen = new Pen(focused ? Palette.Focus : Palette.Line, focused ? PxF(1.5) : 1f))
                    g.DrawPath(pen, path);
            }
        }

        internal static void FocusRing(Graphics g, RectangleF around, float radius)
        {
            g.SmoothingMode = SmoothingMode.AntiAlias;
            float gap = PxF(2);
            var ring = new RectangleF(around.X - gap, around.Y - gap, around.Width + gap * 2, around.Height + gap * 2);
            using (var path = Rounded(ring, radius + gap))
            using (var pen = new Pen(Palette.Focus, PxF(2)))
                g.DrawPath(pen, path);
        }

        /// The tinted ground a state word sits on: the state's colour, faint, over the surface.
        internal static Color Tint(Color tone, Color over)
        {
            return Palette.Contrast ? over : Mix(over, tone, 0.12);
        }

        internal static Size ChipSize(string text, Font font)
        {
            Size measured = TextRenderer.MeasureText(text ?? "", font, new Size(int.MaxValue, int.MaxValue),
                                                     TextFormatFlags.SingleLine | TextFormatFlags.NoPadding);
            return new Size(measured.Width + Px(18), measured.Height + Px(6));
        }

        /// A pill with a state word. Returns how wide it was drawn.
        internal static int Chip(Graphics g, Rectangle cell, string text, Font font, Color tone, Color over)
        {
            if (string.IsNullOrEmpty(text)) return 0;
            Size size = ChipSize(text, font);
            int width = Math.Min(size.Width, Math.Max(Px(24), cell.Width));
            var body = new RectangleF(cell.X + 0.5f, cell.Y + (cell.Height - size.Height) / 2f + 0.5f,
                                      width - 1f, size.Height - 1f);
            g.SmoothingMode = SmoothingMode.AntiAlias;
            using (var path = Rounded(body, body.Height / 2f))
            {
                using (var brush = new SolidBrush(Tint(tone, over))) g.FillPath(brush, path);
                using (var pen = new Pen(Palette.Contrast ? Palette.Line : Mix(over, tone, 0.32), 1f))
                    g.DrawPath(pen, path);
            }
            TextRenderer.DrawText(g, text, font, Rectangle.Round(body), tone,
                                  TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter |
                                  TextFormatFlags.SingleLine | TextFormatFlags.EndEllipsis | TextFormatFlags.NoPadding);
            return width;
        }
    }

    /// A card: the window's own material, lifted. The card IS the layout panel, as the old one
    /// was, because a Panel wrapping a docked AutoSize table measures to nothing.
    internal sealed class SoftCard : TableLayoutPanel
    {
        internal SoftCard()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                     ControlStyles.UserPaint | ControlStyles.ResizeRedraw, true);
            BackColor = Palette.Surface;
        }

        /// The band around the card's body the shadow is drawn into.
        internal static int Room { get { return Soft.Px(10); } }

        protected override void OnPaintBackground(PaintEventArgs e)
        {
            Color ground = Parent != null ? Parent.BackColor : Palette.Canvas;
            using (var brush = new SolidBrush(ground)) e.Graphics.FillRectangle(brush, ClientRectangle);
            float room = Room;
            var body = new RectangleF(room, room * 0.5f, Width - room * 2f - 1f, Height - room * 1.5f - 1f);
            Soft.Raise(e.Graphics, body, Soft.PxF(Brand.RadiusCard), Palette.Surface, true);
        }
    }

    /// A button: raised on a card, or filled with the accent when it is the page's one primary
    /// action.
    internal sealed class SoftButton : Button
    {
        private bool primary, hover, pressed;

        internal SoftButton(bool primary)
        {
            this.primary = primary;
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint |
                     ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
            FlatStyle = FlatStyle.Flat;
            FlatAppearance.BorderSize = 0;
            UseVisualStyleBackColor = false;
            Cursor = Cursors.Hand;
        }

        internal bool Primary
        {
            get { return primary; }
            set { primary = value; Invalidate(); }
        }

        protected override void OnMouseEnter(EventArgs e) { hover = true; Invalidate(); base.OnMouseEnter(e); }
        protected override void OnMouseLeave(EventArgs e) { hover = false; pressed = false; Invalidate(); base.OnMouseLeave(e); }
        protected override void OnMouseDown(MouseEventArgs e) { if (e.Button == MouseButtons.Left) { pressed = true; Invalidate(); } base.OnMouseDown(e); }
        protected override void OnMouseUp(MouseEventArgs e) { pressed = false; Invalidate(); base.OnMouseUp(e); }
        protected override void OnEnabledChanged(EventArgs e) { Invalidate(); base.OnEnabledChanged(e); }
        protected override void OnGotFocus(EventArgs e) { Invalidate(); base.OnGotFocus(e); }
        protected override void OnLostFocus(EventArgs e) { Invalidate(); base.OnLostFocus(e); }

        protected override void OnPaint(PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            g.Clear(Parent != null ? Parent.BackColor : Palette.Surface);
            float inset = Soft.PxF(3);
            var body = new RectangleF(inset, inset, Width - inset * 2f - 1f, Height - inset * 2f - 1f);
            float radius = Soft.PxF(Brand.RadiusControl);
            bool live = Enabled;
            Color text;
            if (primary && live)
            {
                Color fill = pressed ? Soft.Mix(Palette.Accent, Palette.Ink, 0.18)
                           : hover ? Soft.Mix(Palette.Accent, Palette.OnAccent, 0.08) : Palette.Accent;
                if (pressed) Soft.Well(g, body, radius, false);
                else Soft.Raise(g, body, radius, fill, false);
                if (pressed)
                    using (var path = Soft.Rounded(body, radius))
                    using (var brush = new SolidBrush(fill)) g.FillPath(brush, path);
                text = Palette.OnAccent;
            }
            else if (!live)
            {
                using (var path = Soft.Rounded(body, radius))
                {
                    g.SmoothingMode = SmoothingMode.AntiAlias;
                    using (var brush = new SolidBrush(Palette.Canvas == Palette.Surface ? Palette.Inset : Soft.Mix(Palette.Surface, Palette.Inset, 0.5)))
                        g.FillPath(brush, path);
                    using (var pen = new Pen(Palette.Line, 1f)) g.DrawPath(pen, path);
                }
                text = Palette.Muted;
            }
            else
            {
                if (pressed) Soft.Well(g, body, radius, false);
                else Soft.Raise(g, body, radius, hover ? Soft.Mix(Palette.Raised, Palette.AccentSoft, 0.45) : Palette.Raised, false);
                text = Palette.Ink;
            }
            TextRenderer.DrawText(g, Text, Font, Rectangle.Round(body), text,
                                  TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter |
                                  TextFormatFlags.SingleLine | TextFormatFlags.EndEllipsis);
            if (Focused && ShowFocusCues) Soft.FocusRing(g, body, radius);
        }
    }

    /// A check box drawn as a rounded square: a well when it is off, the accent when it is on.
    internal sealed class SoftCheck : CheckBox
    {
        private bool hover;

        internal SoftCheck()
        {
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint |
                     ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
            Cursor = Cursors.Hand;
        }

        private static int Box { get { return Soft.Px(16); } }
        private static int Gap { get { return Soft.Px(9); } }

        public override Size GetPreferredSize(Size proposedSize)
        {
            Size text = TextRenderer.MeasureText(Text ?? "", Font, new Size(int.MaxValue, int.MaxValue),
                                                 TextFormatFlags.SingleLine);
            return new Size(Box + Gap + text.Width + Soft.Px(6), Math.Max(Box, text.Height) + Soft.Px(8));
        }

        protected override void OnCheckedChanged(EventArgs e) { Invalidate(); base.OnCheckedChanged(e); }
        protected override void OnEnabledChanged(EventArgs e) { Invalidate(); base.OnEnabledChanged(e); }
        protected override void OnMouseEnter(EventArgs e) { hover = true; Invalidate(); base.OnMouseEnter(e); }
        protected override void OnMouseLeave(EventArgs e) { hover = false; Invalidate(); base.OnMouseLeave(e); }
        protected override void OnGotFocus(EventArgs e) { Invalidate(); base.OnGotFocus(e); }
        protected override void OnLostFocus(EventArgs e) { Invalidate(); base.OnLostFocus(e); }
        protected override void OnTextChanged(EventArgs e) { Invalidate(); base.OnTextChanged(e); }

        protected override void OnPaint(PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            g.Clear(Parent != null ? Parent.BackColor : Palette.Surface);
            g.SmoothingMode = SmoothingMode.AntiAlias;
            int box = Box;
            var body = new RectangleF(Soft.PxF(1), (Height - box) / 2f, box - 1f, box - 1f);
            float radius = Soft.PxF(Brand.RadiusSmall - 2);
            if (Checked)
            {
                Color fill = Enabled ? Palette.Accent : Palette.Idle;
                using (var path = Soft.Rounded(body, radius))
                using (var brush = new SolidBrush(fill)) g.FillPath(brush, path);
                using (var pen = new Pen(Palette.OnAccent, Soft.PxF(2)))
                {
                    pen.StartCap = LineCap.Round;
                    pen.EndCap = LineCap.Round;
                    pen.LineJoin = LineJoin.Round;
                    g.DrawLines(pen, new[] {
                        new PointF(body.X + body.Width * 0.26f, body.Y + body.Height * 0.52f),
                        new PointF(body.X + body.Width * 0.44f, body.Y + body.Height * 0.70f),
                        new PointF(body.X + body.Width * 0.76f, body.Y + body.Height * 0.32f) });
                }
            }
            else
            {
                Soft.Well(g, body, radius, false);
                if (hover && Enabled)
                    using (var path = Soft.Rounded(body, radius))
                    using (var pen = new Pen(Palette.Accent, 1f)) g.DrawPath(pen, path);
            }
            var textBounds = new Rectangle(box + Gap, 0, Math.Max(0, Width - box - Gap), Height);
            TextRenderer.DrawText(g, Text, Font, textBounds, Enabled ? ForeColor : Palette.Muted,
                                  TextFormatFlags.VerticalCenter | TextFormatFlags.Left |
                                  TextFormatFlags.SingleLine | TextFormatFlags.EndEllipsis);
            if (Focused && ShowFocusCues) Soft.FocusRing(g, body, radius);
        }
    }

    /// A drop-down whose list and closed face use the palette.
    internal sealed class SoftCombo : ComboBox
    {
        internal SoftCombo()
        {
            DrawMode = DrawMode.OwnerDrawFixed;
            DropDownStyle = ComboBoxStyle.DropDownList;
            FlatStyle = FlatStyle.Flat;
            BackColor = Palette.Raised;
            ForeColor = Palette.Ink;
        }

        protected override void OnFontChanged(EventArgs e)
        {
            base.OnFontChanged(e);
            ItemHeight = Font.Height + Soft.Px(8);
        }

        private const int WM_PAINT = 0x000F;

        // A flat drop-down draws no edge of its own, and without one it reads as a label
        // with an arrow beside it. The edge is drawn over the native face once it has
        // painted, in the same hairline every other field has.
        protected override void WndProc(ref Message m)
        {
            base.WndProc(ref m);
            if (m.Msg != WM_PAINT || !IsHandleCreated) return;
            using (Graphics g = Graphics.FromHwnd(Handle))
            using (var pen = new Pen(Focused ? Palette.Focus : Palette.Line, 1f))
                g.DrawRectangle(pen, 0, 0, Width - 1, Height - 1);
        }

        protected override void OnDrawItem(DrawItemEventArgs e)
        {
            if (e.Index < 0) return;
            bool selected = (e.State & DrawItemState.Selected) != 0;
            bool face = (e.State & DrawItemState.ComboBoxEdit) != 0;
            bool highlighted = selected && !face;
            Color back = highlighted ? Palette.AccentSoft : Palette.Raised;
            // In High Contrast that ground is Highlight, and the one text colour every contrast
            // theme pairs with Highlight is HighlightText - as the page tabs have it. WindowText
            // on Highlight is under 1.5:1 in Aquatic and Desert.
            Color ink = !Enabled ? Palette.Muted
                      : highlighted && Palette.Contrast ? SystemColors.HighlightText : Palette.Ink;
            using (var brush = new SolidBrush(back)) e.Graphics.FillRectangle(brush, e.Bounds);
            var bounds = new Rectangle(e.Bounds.X + Soft.Px(6), e.Bounds.Y, Math.Max(0, e.Bounds.Width - Soft.Px(8)), e.Bounds.Height);
            TextRenderer.DrawText(e.Graphics, GetItemText(Items[e.Index]), Font, bounds, ink,
                                  TextFormatFlags.VerticalCenter | TextFormatFlags.Left |
                                  TextFormatFlags.SingleLine | TextFormatFlags.EndEllipsis);
        }
    }

    /// One choice among several, drawn as a small card with its explanation under it.
    internal sealed class ChoiceCard : RadioButton
    {
        internal string Value;
        internal string Help = "";
        private bool hover;

        internal ChoiceCard(string value, string title, string help)
        {
            Value = value;
            Text = title;
            Help = help ?? "";
            AccessibleDescription = Help;
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint |
                     ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
            AutoSize = false;
            Cursor = Cursors.Hand;
        }

        private Font TitleFont
        {
            get { return new Font(Font.FontFamily, Font.Size, FontStyle.Bold); }
        }

        private static RectangleF Body(int width, int height)
        {
            return new RectangleF(Soft.PxF(2), Soft.PxF(2), width - Soft.PxF(4) - 1f, height - Soft.PxF(4) - 1f);
        }

        /// The column the title and help are set in, on a card this wide: from past the radio
        /// mark to the padding on the right. HeightFor measures in it and OnPaint draws in it.
        /// Each used to work it out for itself, five pixels apart, and a help line that wrapped
        /// only when it was drawn ran off the bottom of the card.
        private static Rectangle TextColumn(int width)
        {
            RectangleF body = Body(width, 0);
            int left = (int)(body.X + Soft.PxF(40));
            return new Rectangle(left, 0, Math.Max(Soft.Px(80), (int)body.Right - left - Soft.Px(12)), 0);
        }

        internal int HeightFor(int width)
        {
            int textWidth = TextColumn(width).Width;
            using (Font title = TitleFont)
            {
                int top = TextRenderer.MeasureText(Text ?? "", title, new Size(textWidth, int.MaxValue),
                                                   TextFormatFlags.WordBreak).Height;
                int help = string.IsNullOrEmpty(Help) ? 0
                         : TextRenderer.MeasureText(Help, Font, new Size(textWidth, int.MaxValue),
                                                    TextFormatFlags.WordBreak).Height + Soft.Px(2);
                return Soft.Px(12) + top + help + Soft.Px(12);
            }
        }

        protected override void OnCheckedChanged(EventArgs e) { Invalidate(); base.OnCheckedChanged(e); }
        protected override void OnMouseEnter(EventArgs e) { hover = true; Invalidate(); base.OnMouseEnter(e); }
        protected override void OnMouseLeave(EventArgs e) { hover = false; Invalidate(); base.OnMouseLeave(e); }
        protected override void OnGotFocus(EventArgs e) { Invalidate(); base.OnGotFocus(e); }
        protected override void OnLostFocus(EventArgs e) { Invalidate(); base.OnLostFocus(e); }

        protected override void OnPaint(PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            g.Clear(Parent != null ? Parent.BackColor : Palette.Surface);
            var body = Body(Width, Height);
            float radius = Soft.PxF(Brand.RadiusControl);
            g.SmoothingMode = SmoothingMode.AntiAlias;
            using (var path = Soft.Rounded(body, radius))
            {
                Color fill = Checked ? Palette.AccentSoft : hover ? Soft.Mix(Palette.Raised, Palette.AccentSoft, 0.35) : Palette.Raised;
                using (var brush = new SolidBrush(fill)) g.FillPath(brush, path);
                using (var pen = new Pen(Checked ? Palette.Accent : Palette.Line, Checked ? Soft.PxF(1.5) : 1f))
                    g.DrawPath(pen, path);
            }
            // In High Contrast the chosen card is filled with Highlight, so everything drawn on
            // it takes HighlightText, the colour every contrast theme pairs with Highlight - as
            // the page tabs do. In Accent the radio dot was Highlight on Highlight, and the title
            // and help in WindowText were under 1.5:1.
            bool onHighlight = Checked && Palette.Contrast;
            // The radio mark, so the card still says "one of these" without its colour.
            float mark = Soft.PxF(16);
            var ring = new RectangleF(body.X + Soft.PxF(14), body.Y + Soft.PxF(12), mark, mark);
            Color markColour = onHighlight ? SystemColors.HighlightText : Checked ? Palette.Accent : Palette.Muted;
            using (var pen = new Pen(markColour, Soft.PxF(1.5))) g.DrawEllipse(pen, ring);
            if (Checked)
            {
                float dot = mark * 0.5f;
                using (var brush = new SolidBrush(markColour))
                    g.FillEllipse(brush, ring.X + (mark - dot) / 2f, ring.Y + (mark - dot) / 2f, dot, dot);
            }
            Rectangle column = TextColumn(Width);
            int left = column.X, textWidth = column.Width;
            using (Font title = TitleFont)
            {
                Size top = TextRenderer.MeasureText(Text ?? "", title, new Size(textWidth, int.MaxValue), TextFormatFlags.WordBreak);
                TextRenderer.DrawText(g, Text, title, new Rectangle(left, (int)body.Y + Soft.Px(10), textWidth, top.Height),
                                      onHighlight ? SystemColors.HighlightText : Palette.Ink,
                                      TextFormatFlags.WordBreak | TextFormatFlags.Left);
                if (!string.IsNullOrEmpty(Help))
                    TextRenderer.DrawText(g, Help, Font,
                                          new Rectangle(left, (int)body.Y + Soft.Px(12) + top.Height, textWidth, Height),
                                          onHighlight ? SystemColors.HighlightText : Palette.Secondary,
                                          TextFormatFlags.WordBreak | TextFormatFlags.Left);
            }
            if (Focused && ShowFocusCues) Soft.FocusRing(g, body, radius);
        }
    }

    /// A column of ChoiceCards that lays itself out and says which one is chosen.
    internal sealed class ChoiceGroup : Panel
    {
        internal event EventHandler ValueChanged;

        internal ChoiceGroup()
        {
            SetStyle(ControlStyles.OptimizedDoubleBuffer | ControlStyles.AllPaintingInWmPaint, true);
            BackColor = Palette.Surface;
            // A TableLayoutPanel asks a child for its preferred size only when the child says
            // it sizes itself; otherwise it keeps whatever height the child already has, and
            // three of the four choices were cut off.
            AutoSize = true;
            AutoSizeMode = AutoSizeMode.GrowAndShrink;
        }

        internal void Add(ChoiceCard card)
        {
            card.CheckedChanged += delegate { if (card.Checked && ValueChanged != null) ValueChanged(this, EventArgs.Empty); };
            Controls.Add(card);
        }

        internal string Value
        {
            get
            {
                foreach (Control control in Controls)
                {
                    var card = control as ChoiceCard;
                    if (card != null && card.Checked) return card.Value;
                }
                return null;
            }
            set
            {
                foreach (Control control in Controls)
                {
                    var card = control as ChoiceCard;
                    if (card != null) card.Checked = card.Value == value;
                }
            }
        }

        private int WidthFor(Size proposed)
        {
            if (proposed.Width > Soft.Px(160) && proposed.Width < 20000) return proposed.Width;
            if (Width > Soft.Px(160)) return Width;
            return Soft.Px(460);
        }

        public override Size GetPreferredSize(Size proposedSize)
        {
            int width = WidthFor(proposedSize);
            int height = 0;
            foreach (Control control in Controls)
            {
                var card = control as ChoiceCard;
                if (card != null) height += card.HeightFor(width) + Soft.Px(6);
            }
            return new Size(width, height);
        }

        protected override void OnLayout(LayoutEventArgs levent)
        {
            base.OnLayout(levent);
            int y = 0;
            foreach (Control control in Controls)
            {
                var card = control as ChoiceCard;
                if (card == null) continue;
                int height = card.HeightFor(Width);
                card.SetBounds(0, y, Width, height);
                y += height + Soft.Px(6);
            }
        }

        protected override void OnSizeChanged(EventArgs e)
        {
            base.OnSizeChanged(e);
            PerformLayout();
        }
    }

    /// A multi-line text box sitting in a well, for a message somebody writes.
    internal sealed class SoftTextArea : Panel
    {
        internal readonly TextBox Box = new TextBox();

        internal SoftTextArea()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                     ControlStyles.UserPaint | ControlStyles.ResizeRedraw, true);
            BackColor = Palette.Surface;
            Box.BorderStyle = BorderStyle.None;
            Box.Multiline = true;
            Box.AcceptsReturn = true;
            Box.WordWrap = true;
            Box.ScrollBars = ScrollBars.Vertical;
            Box.BackColor = Palette.Inset;
            Box.ForeColor = Palette.Ink;
            Box.GotFocus += delegate { Invalidate(); };
            Box.LostFocus += delegate { Invalidate(); };
            Controls.Add(Box);
            Padding = new Padding(Soft.Px(10), Soft.Px(8), Soft.Px(6), Soft.Px(8));
            Height = Soft.Px(96);
        }

        protected override void OnLayout(LayoutEventArgs levent)
        {
            base.OnLayout(levent);
            Box.SetBounds(Padding.Left, Padding.Top, Math.Max(0, Width - Padding.Horizontal),
                          Math.Max(0, Height - Padding.Vertical));
        }

        protected override void OnPaintBackground(PaintEventArgs e)
        {
            Color ground = Parent != null ? Parent.BackColor : Palette.Surface;
            using (var brush = new SolidBrush(ground)) e.Graphics.FillRectangle(brush, ClientRectangle);
            var body = new RectangleF(0.5f, 0.5f, Width - 1.5f, Height - 1.5f);
            Soft.Well(e.Graphics, body, Soft.PxF(Brand.RadiusControl), Box.Focused);
        }
    }

    /// A read-only block of text in a well: the Preview.
    internal sealed class SoftQuote : Panel
    {
        private string text = "";

        internal SoftQuote()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                     ControlStyles.UserPaint | ControlStyles.ResizeRedraw, true);
            BackColor = Palette.Surface;
            TabStop = false;
            AutoSize = true;
            AutoSizeMode = AutoSizeMode.GrowAndShrink;
        }

        internal string Quote
        {
            get { return text; }
            set
            {
                text = value ?? "";
                AccessibleDescription = text;
                if (Parent != null) Parent.PerformLayout();
                Invalidate();
            }
        }

        public override Size GetPreferredSize(Size proposedSize)
        {
            int width = proposedSize.Width > Soft.Px(160) && proposedSize.Width < 20000 ? proposedSize.Width
                      : Width > Soft.Px(160) ? Width : Soft.Px(460);
            int textHeight = TextRenderer.MeasureText(text.Length == 0 ? " " : text, Font,
                                                      new Size(width - Soft.Px(28), int.MaxValue),
                                                      TextFormatFlags.WordBreak | TextFormatFlags.TextBoxControl).Height;
            return new Size(width, textHeight + Soft.Px(24));
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            Color ground = Parent != null ? Parent.BackColor : Palette.Surface;
            e.Graphics.Clear(ground);
            var body = new RectangleF(0.5f, 0.5f, Width - 1.5f, Height - 1.5f);
            Soft.Well(e.Graphics, body, Soft.PxF(Brand.RadiusControl), false);
            TextRenderer.DrawText(e.Graphics, text, Font,
                                  new Rectangle(Soft.Px(14), Soft.Px(12), Math.Max(0, Width - Soft.Px(28)), Height),
                                  Palette.Ink, TextFormatFlags.WordBreak | TextFormatFlags.TextBoxControl | TextFormatFlags.Left);
        }
    }

    /// A list whose rows are drawn by the page that owns it, double-buffered so a five-second
    /// refresh does not flicker.
    internal sealed class SoftList : ListView
    {
        internal SoftList()
        {
            SetStyle(ControlStyles.OptimizedDoubleBuffer | ControlStyles.AllPaintingInWmPaint, true);
        }
    }

    /// The state dot, with a halo that says whether the watcher is alive.
    ///
    /// Monitoring breathes slowly; waiting holds a soft halo; checking turns a small arc;
    /// recovering pulses faster; paused and stopped are still; a state that needs a person
    /// pulses once when it is entered and then holds. With motion reduced nothing moves.
    internal sealed class HaloDot : Control
    {
        private string state = "idle";
        private readonly Timer timer = new Timer();
        private readonly System.Diagnostics.Stopwatch clock = System.Diagnostics.Stopwatch.StartNew();
        private double enteredAt;

        internal HaloDot()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                     ControlStyles.UserPaint | ControlStyles.ResizeRedraw | ControlStyles.SupportsTransparentBackColor, true);
            TabStop = false;
            AccessibleRole = AccessibleRole.Graphic;
            timer.Interval = 33;
            timer.Tick += delegate { Invalidate(); if (!ShouldRun()) timer.Stop(); };
        }

        internal string State
        {
            get { return state; }
            set
            {
                string next = string.IsNullOrEmpty(value) ? "idle" : value;
                if (next == state) return;
                state = next;
                enteredAt = clock.Elapsed.TotalMilliseconds;
                Invalidate();
                Sync();
            }
        }

        /// Loops for as long as the state lasts.
        internal static bool Loops(string state)
        {
            return state == "monitoring" || state == "checking" || state == "recovering";
        }

        /// Pulses once, when the state is entered.
        internal static bool PulsesOnce(string state)
        {
            return state == "attention" || state == "failed";
        }

        /// The halo's opacity, from the state and the milliseconds since it was entered.
        /// Pure, so the rule can be checked without drawing anything.
        internal static double HaloOpacity(string state, double elapsedMs, bool reduced)
        {
            double low = Brand.HaloMin, high = Brand.HaloMax, middle = (low + high) / 2;
            // Comparisons, not a switch: see DotColour. Six string cases were already enough for
            // the in-box compiler to emit the randomly named class.
            if (state == "monitoring")
            {
                if (reduced) return middle;
                return low + (high - low) * (0.5 - 0.5 * Math.Cos(2 * Math.PI * (elapsedMs % Brand.BreatheMs) / Brand.BreatheMs));
            }
            if (state == "recovering")
            {
                if (reduced) return Math.Min(0.6, high * 1.2);
                return low + (Math.Min(0.6, high * 1.6) - low) *
                       (0.5 - 0.5 * Math.Cos(2 * Math.PI * (elapsedMs % Brand.AttentionMs) / Brand.AttentionMs));
            }
            if (state == "waiting" || state == "checking") return middle;
            if (state == "attention" || state == "failed")
            {
                if (reduced || elapsedMs >= Brand.AttentionMs) return middle;
                return middle + (Math.Min(0.6, high * 1.6) - middle) * Math.Sin(Math.PI * elapsedMs / Brand.AttentionMs);
            }
            return 0;          // paused, idle: still, and no halo
        }

        internal static Color DotColour(string state)
        {
            // Comparisons, not a switch. The in-box compiler turns a string switch with enough
            // cases into a dictionary held by a class it names with a fresh random GUID, and that
            // one name made two builds of the same source differ - which stopped a release.
            if (state == "monitoring" || state == "recovering") return Palette.Active;
            if (state == "waiting" || state == "checking") return Palette.Waiting;
            if (state == "attention") return Palette.Attention;
            if (state == "failed") return Palette.Danger;
            if (state == "paused") return Palette.Paused;
            return Palette.Idle;
        }

        private bool ShouldRun()
        {
            if (!Visible || !IsHandleCreated || Soft.ReduceMotion) return false;
            Form form = FindForm();
            if (form != null && form.WindowState == FormWindowState.Minimized) return false;
            if (Loops(state)) return true;
            return PulsesOnce(state) && clock.Elapsed.TotalMilliseconds - enteredAt < Brand.AttentionMs;
        }

        /// Starts or stops the timer to match what should be moving. Called whenever the
        /// state, the visibility or the window's size changes.
        internal void Sync()
        {
            if (ShouldRun()) { if (!timer.Enabled) timer.Start(); }
            else if (timer.Enabled) timer.Stop();
        }

        protected override void OnVisibleChanged(EventArgs e) { base.OnVisibleChanged(e); Sync(); }
        protected override void OnHandleCreated(EventArgs e) { base.OnHandleCreated(e); Sync(); }
        protected override void OnHandleDestroyed(EventArgs e) { timer.Stop(); base.OnHandleDestroyed(e); }

        protected override void Dispose(bool disposing)
        {
            if (disposing) { timer.Stop(); timer.Dispose(); }
            base.Dispose(disposing);
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            g.Clear(Parent != null ? Parent.BackColor : Palette.Surface);
            g.SmoothingMode = SmoothingMode.AntiAlias;
            bool reduced = Soft.ReduceMotion;
            double elapsed = clock.Elapsed.TotalMilliseconds - enteredAt;
            Color colour = DotColour(state);
            float cx = Soft.PxF(Brand.HaloRadius + 2), cy = Height / 2f;
            double opacity = HaloOpacity(state, elapsed, reduced);
            if (opacity > 0 && !Palette.Contrast)
            {
                float halo = Soft.PxF(Brand.HaloRadius);
                using (var brush = new SolidBrush(Soft.WithAlpha(colour, opacity)))
                    g.FillEllipse(brush, cx - halo, cy - halo, halo * 2, halo * 2);
            }
            float dot = Soft.PxF(5);
            using (var brush = new SolidBrush(colour)) g.FillEllipse(brush, cx - dot, cy - dot, dot * 2, dot * 2);
            if (state == "checking")
            {
                float arc = Soft.PxF(Brand.HaloRadius - 1);
                float angle = reduced ? 300f : (float)(elapsed % 1000 / 1000.0 * 360.0);
                using (var pen = new Pen(colour, Soft.PxF(1.6)))
                {
                    pen.StartCap = LineCap.Round;
                    pen.EndCap = LineCap.Round;
                    g.DrawArc(pen, cx - arc, cy - arc, arc * 2, arc * 2, angle, 100f);
                }
            }
        }
    }
}
