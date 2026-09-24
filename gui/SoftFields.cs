// Codex Auto Resume - the controls a person acts on: buttons, checks, numbers, choices, text.
//
// A Button is still a Button, a check box a CheckBox and a choice a RadioButton. Only the
// painting is ours, which is what keeps the keyboard and the screen reader working.

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
    /// A button: raised on its ground, or filled with the accent when it is the page's one
    /// primary action. Under the pointer a plain button comes up to the surface and the accent
    /// brightens a step; pressed, either sinks into a well; disabled, it is flat, with muted
    /// words and no accent, so the accent never marks a dead control.
    internal sealed class SoftButton : Button, ISoftLifted
    {
        private bool primary, danger, hover, pressed;
        private readonly LiftTracker tracker;

        internal SoftButton(bool primary)
        {
            this.primary = primary;
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint |
                     ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
            FlatStyle = FlatStyle.Flat;
            FlatAppearance.BorderSize = 0;
            UseVisualStyleBackColor = false;
            Cursor = Cursors.Hand;
            tracker = new LiftTracker(this, "control");
        }

        internal bool Primary
        {
            get { return primary; }
            set { primary = value; Invalidate(); }
        }

        /// A button whose action cannot be taken back: its words are in the danger colour.
        internal bool Danger
        {
            get { return danger; }
            set { danger = value; Invalidate(); }
        }

        string ISoftLifted.Lift { get { return Enabled && !pressed ? "control" : null; } }
        float ISoftLifted.Radius { get { return Soft.PxF(Brand.RadiusControl); } }
        Rectangle ISoftLifted.Face { get { return ClientRectangle; } }
        bool ISoftLifted.Ring { get { return Focused && ShowFocusCues; } }

        private void Press(bool down)
        {
            if (pressed == down) return;
            pressed = down;
            Invalidate();
            tracker.Update();
        }

        protected override void OnMouseEnter(EventArgs e) { hover = true; Invalidate(); base.OnMouseEnter(e); }
        protected override void OnMouseLeave(EventArgs e) { hover = false; Press(false); Invalidate(); base.OnMouseLeave(e); }
        protected override void OnMouseDown(MouseEventArgs e) { if (e.Button == MouseButtons.Left) Press(true); base.OnMouseDown(e); }
        protected override void OnMouseUp(MouseEventArgs e) { Press(false); base.OnMouseUp(e); }
        protected override void OnEnabledChanged(EventArgs e) { Invalidate(); base.OnEnabledChanged(e); }
        protected override void OnGotFocus(EventArgs e) { Invalidate(); base.OnGotFocus(e); }
        protected override void OnLostFocus(EventArgs e) { Invalidate(); base.OnLostFocus(e); }

        protected override void OnPaint(PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            Rectangle face = ClientRectangle;
            float radius = Soft.PxF(Brand.RadiusControl);
            Ground.PaintBehind(this, g, face, radius);
            Color fill, edge, text;
            if (!Enabled)
            {
                fill = Palette.Surface;
                edge = Palette.Line;
                text = Palette.Muted;
            }
            else if (primary)
            {
                fill = pressed ? Palette.AccentPressed : hover ? Palette.AccentHover : Palette.Accent;
                edge = fill;
                text = Palette.OnAccent;
            }
            else
            {
                fill = pressed ? Palette.Inset : hover ? Palette.Surface : Palette.Raised;
                edge = Palette.Line;
                text = danger ? Palette.Danger : Palette.Ink;
            }
            Soft.Body(g, face, radius, fill, edge, pressed && Enabled);
            TextRenderer.DrawText(g, Text, Font, face, text,
                                  TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter |
                                  TextFormatFlags.SingleLine | TextFormatFlags.EndEllipsis);
        }
    }

    /// A true-or-false setting, of one of two kinds, with its words to the right. Still a CheckBox, so
    /// Space turns it, the focus cue shows where the keyboard is, and a screen reader says what it
    /// is and whether it is on.
    ///
    /// The kind follows what the setting is (v0.6.4), the same on every surface. A switch - the
    /// panel's 40 by 22 pill - turns something that runs on or off: the notifications, the
    /// notification-area icon, reduced motion, running at sign-in. A check box (Box) picks which items
    /// of a list apply: which kinds of interruption may be recovered, which events notify. Its box sits
    /// left of its label, as it does on the popup and the panel: unchecked it is the sunken well a
    /// field is, checked the accent with an on-accent mark, disabled a flat surface with a muted mark,
    /// and in High Contrast system colours with no shadow at all (brand.CHECKBOX).
    ///
    /// A change moves (v0.6.5): the switch's knob slides end to end and its track cross-fades from the
    /// well to the accent, and a check box's fill and mark fade in or out, over brand's transition on
    /// its one curve (Motion). Only the glyph is repainted while it moves, and the timer stops when it
    /// arrives. With motion reduced, Windows' animation effects off, in High Contrast, or out of sight,
    /// the change is immediate. It follows Checked, so a caller that asks first and sets Checked only once
    /// the change is confirmed has a switch that moves only then.
    internal sealed class SoftCheck : CheckBox, ISoftLifted
    {
        private readonly LiftTracker tracker;
        private readonly Transition turn;
        private bool box;

        internal SoftCheck()
        {
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint |
                     ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
            Cursor = Cursors.Hand;
            AccessibleRole = AccessibleRole.CheckButton;
            tracker = new LiftTracker(this, "control");
            turn = new Transition(this, 0.0);
        }

        /// How far on the glyph is drawn, from 0 (off) to 1 (on): between the two only while it moves.
        internal double Progress { get { return turn.Value; } }

        /// Whether it is moving between off and on; its timer runs only then.
        internal bool Moving { get { return turn.Running; } }

        /// Drawn as a check box rather than a switch.
        internal bool Box
        {
            get { return box; }
            set
            {
                if (box == value) return;
                box = value;
                if (AutoSize && Parent != null) Parent.PerformLayout();
                Invalidate();
                tracker.Update();
            }
        }

        private int Gap { get { return box ? Soft.Px(Brand.CheckGap) : Soft.Px(9); } }

        /// The switch's track, or the check box's box: at the left, on the control's middle line.
        internal Rectangle Glyph
        {
            get
            {
                if (box)
                {
                    int size = Soft.Px(Brand.CheckSize);
                    return new Rectangle(0, (Height - size) / 2, size, size);
                }
                int height = Soft.Px(Brand.SwitchHeight);
                return new Rectangle(0, (Height - height) / 2, Soft.Px(Brand.SwitchWidth), height);
            }
        }

        // No lift - a switch and a box are wells - but the focus ring runs outside the control on
        // the left, so the ground draws that part of it.
        string ISoftLifted.Lift { get { return null; } }
        float ISoftLifted.Radius { get { return box ? Soft.PxF(Brand.RadiusCheck) : Soft.Px(Brand.SwitchHeight) / 2f; } }
        Rectangle ISoftLifted.Face { get { return Glyph; } }
        bool ISoftLifted.Ring { get { return Focused && ShowFocusCues; } }

        public override Size GetPreferredSize(Size proposedSize)
        {
            Size text = TextRenderer.MeasureText(Text ?? "", Font, new Size(int.MaxValue, int.MaxValue),
                                                 TextFormatFlags.SingleLine);
            int glyphWidth = box ? Soft.Px(Brand.CheckSize) : Soft.Px(Brand.SwitchWidth);
            int glyphHeight = box ? Soft.Px(Brand.CheckSize) : Soft.Px(Brand.SwitchHeight);
            return new Size(glyphWidth + Gap + text.Width + Soft.Px(6), Math.Max(glyphHeight, text.Height) + Soft.Px(6));
        }

        protected override void OnCheckedChanged(EventArgs e)
        {
            // Paint only: the glyph glides to its new state, and nothing is laid out.
            turn.Area = Glyph;
            turn.To(Checked ? 1.0 : 0.0, Motion.Allowed(this));
            Invalidate();
            base.OnCheckedChanged(e);
        }

        protected override void OnEnabledChanged(EventArgs e) { Invalidate(); base.OnEnabledChanged(e); }
        protected override void OnGotFocus(EventArgs e) { Invalidate(); base.OnGotFocus(e); }
        protected override void OnLostFocus(EventArgs e) { Invalidate(); base.OnLostFocus(e); }
        protected override void OnTextChanged(EventArgs e) { Invalidate(); base.OnTextChanged(e); }

        protected override void Dispose(bool disposing)
        {
            if (disposing) turn.Dispose();
            base.Dispose(disposing);
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            Ground.PaintArea(this, g, ClientRectangle);
            Rectangle glyph = Glyph;
            double on = turn.Value;
            if (box) DrawBoxAt(g, glyph, on, Enabled);
            else Soft.SwitchAt(g, glyph, on, Enabled, Parent != null ? Ground.Colour(Parent) : Palette.Card);
            var textBounds = new Rectangle(glyph.Right + Gap, 0, Math.Max(0, Width - glyph.Right - Gap), Height);
            TextRenderer.DrawText(g, Text, Font, textBounds, Enabled ? ForeColor : Palette.Muted,
                                  TextFormatFlags.VerticalCenter | TextFormatFlags.Left |
                                  TextFormatFlags.SingleLine | TextFormatFlags.EndEllipsis);
            if (Focused && ShowFocusCues)
                Soft.Ring(g, glyph, box ? Soft.PxF(Brand.RadiusCheck) : glyph.Height / 2f);
        }

        /// The check box in `face`, a CheckSize square at the window's scale: its fill, the inset well
        /// while it is unchecked and enabled, its hairline, and the mark - the brand's centre line,
        /// stroked CheckStroke wide with flat ends and a mitred corner.
        internal static void DrawBox(Graphics g, Rectangle face, bool on, bool enabled)
        {
            Color fill, edge, mark;
            bool marked, well;
            if (Palette.Contrast)
            {
                fill = Brand.CheckSystemFill(on, enabled);
                edge = Brand.CheckSystemEdge(on, enabled);
                marked = Brand.CheckSystemMark(on, enabled, out mark);
                well = false;
            }
            else
            {
                fill = Tokens.Dark ? Brand.Dark.CheckFill(on, enabled) : Brand.CheckFill(on, enabled);
                edge = Tokens.Dark ? Brand.Dark.CheckEdge(on, enabled) : Brand.CheckEdge(on, enabled);
                marked = Tokens.Dark ? Brand.Dark.CheckMark(on, enabled, out mark) : Brand.CheckMark(on, enabled, out mark);
                well = Brand.CheckWell(on, enabled);
            }
            Soft.Body(g, face, Soft.PxF(Brand.RadiusCheck), fill, edge, well ? "inset" : null);
            if (!marked) return;
            float scale = (float)SettingsForm.DpiScale;
            GraphicsState state = g.Save();
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.PixelOffsetMode = PixelOffsetMode.Half;
            using (var pen = new Pen(mark, Soft.PxF(Brand.CheckStroke)))
            {
                pen.StartCap = LineCap.Flat;
                pen.EndCap = LineCap.Flat;
                pen.LineJoin = LineJoin.Miter;
                g.DrawLines(pen, new[] {
                    new PointF(face.X + Brand.CheckMarkStartX * scale, face.Y + Brand.CheckMarkStartY * scale),
                    new PointF(face.X + Brand.CheckMarkCornerX * scale, face.Y + Brand.CheckMarkCornerY * scale),
                    new PointF(face.X + Brand.CheckMarkEndX * scale, face.Y + Brand.CheckMarkEndY * scale) });
            }
            g.Restore(state);
        }

        /// The check box `on` of the way from unchecked (0) to checked (1), as it fades between them
        /// (v0.6.5): the unchecked box, and the checked one - its fill, edge and mark - over it at that
        /// opacity. At 0 and 1 it is exactly DrawBox.
        internal static void DrawBoxAt(Graphics g, Rectangle face, double on, bool enabled)
        {
            if (on <= 0.0 || on >= 1.0 || Palette.Contrast || face.Width <= 0 || face.Height <= 0)
            {
                DrawBox(g, face, on >= 0.5, enabled);
                return;
            }
            DrawBox(g, face, false, enabled);
            using (var layer = new Bitmap(face.Width + 2, face.Height + 2, PixelFormat.Format32bppPArgb))
            {
                using (Graphics drawn = Graphics.FromImage(layer))
                {
                    drawn.Clear(Color.Transparent);
                    drawn.TranslateTransform(1 - face.X, 1 - face.Y);
                    DrawBox(drawn, face, true, enabled);
                }
                Soft.Faded(g, layer, new Rectangle(face.X - 1, face.Y - 1, layer.Width, layer.Height), on);
            }
        }
    }

    /// A number in a well, as the panel's number field is: a NumericUpDown without a border of
    /// its own, sitting in the inset well, with its spin buttons redrawn as two small wedges.
    /// `Spin` is the real control - typing, the arrows, the keyboard and screen readers are all
    /// its own - and the one the settings are read from.
    internal sealed class SoftNumber : Panel
    {
        internal readonly NumericUpDown Spin = new NumericUpDown();
        private SpinPainter painter;
        private bool hooked;

        internal SoftNumber()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                     ControlStyles.UserPaint | ControlStyles.ResizeRedraw, true);
            BackColor = Palette.Inset;
            Spin.BorderStyle = BorderStyle.None;
            Spin.BackColor = Palette.Inset;
            Spin.ForeColor = Palette.Ink;
            Spin.Enter += delegate { Invalidate(); };
            Spin.Leave += delegate { Invalidate(); };
            Spin.HandleCreated += delegate { Hook(); };
            Controls.Add(Spin);
            Size = new Size(Soft.Px(Brand.NumberWidth), SoftCombo.FieldHeight);
        }

        // The spin buttons get their window after the NumericUpDown does, so they are hooked
        // when theirs exists - and again if it is ever made anew.
        private void Hook()
        {
            if (hooked) return;
            foreach (Control child in Spin.Controls)
            {
                if (child is TextBox) continue;
                Control buttons = child;
                hooked = true;
                buttons.HandleCreated += delegate { painter = new SpinPainter(buttons); };
                if (buttons.IsHandleCreated) painter = new SpinPainter(buttons);
            }
        }

        public override Size GetPreferredSize(Size proposedSize)
        {
            return new Size(Math.Max(Soft.Px(Brand.NumberWidth), Width),
                            Math.Max(SoftCombo.FieldHeight, Spin.PreferredHeight + Soft.Px(4)));
        }

        protected override void OnLayout(LayoutEventArgs levent)
        {
            base.OnLayout(levent);
            int left = Soft.Px(8), right = Soft.Px(4);
            Spin.SetBounds(left, Math.Max(0, (Height - Spin.Height) / 2), Math.Max(0, Width - left - right), Spin.Height);
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            float radius = Soft.PxF(Brand.RadiusControl);
            Ground.PaintBehind(this, e.Graphics, ClientRectangle, radius);
            Soft.InsetWell(e.Graphics, ClientRectangle, radius, Spin.ContainsFocus);
        }

        /// Draws the spin buttons as two muted wedges on the well in place of the grey
        /// scroll-bar buttons. Only painting is taken over; clicks, holds and the keyboard go on
        /// to the control underneath.
        private sealed class SpinPainter : NativeWindow
        {
            private readonly Control buttons;

            internal SpinPainter(Control buttons)
            {
                this.buttons = buttons;
                AssignHandle(buttons.Handle);
            }

            protected override void WndProc(ref Message m)
            {
                if (NativePaint.Handle(ref m, buttons.ClientSize, Draw)) return;
                base.WndProc(ref m);
            }

            private void Draw(Graphics g)
            {
                Size size = buttons.ClientSize;
                using (var brush = new SolidBrush(Palette.Inset)) g.FillRectangle(brush, 0, 0, size.Width, size.Height);
                float wedge = Math.Max(2f, Math.Min(Soft.PxF(7), size.Width - Soft.PxF(4))), tall = wedge / 2f;
                float centre = size.Width / 2f, half = size.Height / 2f;
                float up = half / 2f + Soft.PxF(1), down = half + half / 2f - Soft.PxF(1);
                GraphicsState state = g.Save();
                g.SmoothingMode = SmoothingMode.AntiAlias;
                g.PixelOffsetMode = PixelOffsetMode.Half;
                using (var brush = new SolidBrush(buttons.Enabled ? Palette.Muted : Soft.Mix(Palette.Muted, Palette.Inset, 0.5)))
                {
                    g.FillPolygon(brush, new[] { new PointF(centre - wedge / 2f, up + tall / 2f), new PointF(centre + wedge / 2f, up + tall / 2f),
                                                 new PointF(centre, up - tall / 2f) });
                    g.FillPolygon(brush, new[] { new PointF(centre - wedge / 2f, down - tall / 2f), new PointF(centre + wedge / 2f, down - tall / 2f),
                                                 new PointF(centre, down + tall / 2f) });
                }
                g.Restore(state);
            }
        }
    }

    /// One choice among several, drawn as a small card with its explanation under it. Resting,
    /// it is raised like a button; chosen, it sinks into a well with an accent edge and title, as
    /// the panel's chosen segment does.
    internal sealed class ChoiceCard : RadioButton, ISoftLifted
    {
        internal string Value;
        internal string Help = "";
        private bool hover;
        private Font titleFont, titleFrom;
        private readonly LiftTracker tracker;

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
            tracker = new LiftTracker(this, "control");
        }

        /// The title's font: 600, chosen or not, so a card keeps its height when it is picked.
        private Font TitleFont
        {
            get
            {
                if (titleFont == null || titleFrom != Font)
                {
                    if (titleFont != null) titleFont.Dispose();
                    titleFont = Soft.Weighted(Font, Font.SizeInPoints, 600);
                    titleFrom = Font;
                }
                return titleFont;
            }
        }

        string ISoftLifted.Lift { get { return Checked ? null : "control"; } }
        float ISoftLifted.Radius { get { return Soft.PxF(Brand.RadiusControl); } }
        Rectangle ISoftLifted.Face { get { return ClientRectangle; } }
        bool ISoftLifted.Ring { get { return Focused && ShowFocusCues; } }

        private static RectangleF Body(int width, int height)
        {
            return new RectangleF(0f, 0f, width, height);
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

        // The title and the help wrap in the text column, Korean between its words (Soft.Wrap).
        private const TextFormatFlags Words = TextFormatFlags.WordBreak | TextFormatFlags.Left;

        internal int HeightFor(int width)
        {
            int textWidth = TextColumn(width).Width;
            Font title = TitleFont;
            int top = TextRenderer.MeasureText(Soft.Wrap(Text ?? "", title, textWidth, Words), title, new Size(textWidth, int.MaxValue),
                                               Words).Height;
            int help = string.IsNullOrEmpty(Help) ? 0
                     : TextRenderer.MeasureText(Soft.Wrap(Help, Font, textWidth, Words), Font, new Size(textWidth, int.MaxValue),
                                                Words).Height + Soft.Px(2);
            return Soft.Px(12) + top + help + Soft.Px(12);
        }

        protected override void OnCheckedChanged(EventArgs e) { Invalidate(); tracker.Update(); base.OnCheckedChanged(e); }
        protected override void OnMouseEnter(EventArgs e) { hover = true; Invalidate(); base.OnMouseEnter(e); }
        protected override void OnMouseLeave(EventArgs e) { hover = false; Invalidate(); base.OnMouseLeave(e); }
        protected override void OnGotFocus(EventArgs e) { Invalidate(); base.OnGotFocus(e); }
        protected override void OnLostFocus(EventArgs e) { Invalidate(); base.OnLostFocus(e); }

        protected override void Dispose(bool disposing)
        {
            if (disposing && titleFont != null) { titleFont.Dispose(); titleFont = null; }
            base.Dispose(disposing);
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            var body = Body(Width, Height);
            float radius = Soft.PxF(Brand.RadiusControl);
            Ground.PaintBehind(this, g, ClientRectangle, radius);
            // In High Contrast the chosen card is filled with Highlight, so everything drawn on
            // it takes HighlightText, the colour every contrast theme pairs with Highlight - as
            // the page tabs do. In Accent the radio dot was Highlight on Highlight, and the title
            // and help in WindowText were under 1.5:1.
            bool onHighlight = Checked && Palette.Contrast;
            Color fill = onHighlight ? Palette.AccentSoft : Checked ? Palette.Inset : hover ? Palette.Surface : Palette.Raised;
            // Resting, raised as a button and as the panel's segment for the same setting are - no top light in
            // dark. Chosen, a well.
            Soft.Body(g, ClientRectangle, radius, fill, Checked ? Palette.Accent : Palette.Line, Checked && !Palette.Contrast);
            // The radio mark, so the card still says "one of these" without its colour.
            float mark = Soft.PxF(16);
            var ring = new RectangleF(body.X + Soft.PxF(14), body.Y + Soft.PxF(12), mark, mark);
            Color markColour = onHighlight ? SystemColors.HighlightText : Checked ? Palette.Accent : Palette.Muted;
            GraphicsState state = g.Save();
            g.SmoothingMode = SmoothingMode.AntiAlias;
            using (var pen = new Pen(markColour, Soft.PxF(1.5))) g.DrawEllipse(pen, ring);
            if (Checked)
            {
                float dot = mark * 0.5f;
                using (var brush = new SolidBrush(markColour))
                    g.FillEllipse(brush, ring.X + (mark - dot) / 2f, ring.Y + (mark - dot) / 2f, dot, dot);
            }
            g.Restore(state);
            Rectangle column = TextColumn(Width);
            int left = column.X, textWidth = column.Width;
            Font title = TitleFont;
            string heading = Soft.Wrap(Text ?? "", title, textWidth, Words);
            Size top = TextRenderer.MeasureText(heading, title, new Size(textWidth, int.MaxValue), Words);
            TextRenderer.DrawText(g, heading, title, new Rectangle(left, (int)body.Y + Soft.Px(10), textWidth, top.Height),
                                  onHighlight ? SystemColors.HighlightText : Checked ? Palette.Accent : Palette.Ink,
                                  Words);
            if (!string.IsNullOrEmpty(Help))
                TextRenderer.DrawText(g, Soft.Wrap(Help, Font, textWidth, Words), Font,
                                      new Rectangle(left, (int)body.Y + Soft.Px(12) + top.Height, textWidth, Height),
                                      onHighlight ? SystemColors.HighlightText : Palette.Secondary,
                                      Words);
        }
    }

    /// A column of ChoiceCards that lays itself out, says which one is chosen, and is the ground
    /// their lift is drawn on.
    internal sealed class ChoiceGroup : Panel, ISoftGround
    {
        internal event EventHandler ValueChanged;

        internal ChoiceGroup()
        {
            SetStyle(ControlStyles.OptimizedDoubleBuffer | ControlStyles.AllPaintingInWmPaint |
                     ControlStyles.UserPaint | ControlStyles.ResizeRedraw, true);
            BackColor = Palette.Card;
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
                if (card != null) height += card.HeightFor(width) + Soft.Px(Brand.SegmentGap);
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
                y += height + Soft.Px(Brand.SegmentGap);
            }
        }

        protected override void OnSizeChanged(EventArgs e)
        {
            base.OnSizeChanged(e);
            PerformLayout();
        }

        protected override void OnPaintBackground(PaintEventArgs e)
        {
            Ground.Paint(this, e);
        }
    }

    /// A multi-line text box sitting in a well, for a message somebody writes.
    internal sealed class SoftTextArea : Panel, ISoftScroller
    {
        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        private static extern IntPtr SendMessage(IntPtr window, int message, IntPtr wParam, IntPtr lParam);

        [StructLayout(LayoutKind.Sequential)]
        private struct ScrollInfo
        {
            internal int Size, Mask, Min, Max, Page, Pos, TrackPos;
        }

        [DllImport("user32.dll")]
        private static extern bool GetScrollInfo(IntPtr window, int bar, ref ScrollInfo info);

        private const int SB_VERT = 1;
        private const int SIF_ALL = 0x17;
        private const int EM_LINESCROLL = 0x00B6;
        private const int EM_GETFIRSTVISIBLELINE = 0x00CE;
        private const int WM_VSCROLL = 0x0115;

        internal readonly TextBox Box = new TextBox();
        private readonly ListClip clip = new ListClip();
        private readonly SoftScrollBar bar;
        private readonly Watcher watcher;

        internal SoftTextArea()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                     ControlStyles.UserPaint | ControlStyles.ResizeRedraw, true);
            BackColor = Palette.Inset;
            bar = new SoftScrollBar(this, this);
            Box.BorderStyle = BorderStyle.None;
            Box.Multiline = true;
            Box.AcceptsReturn = true;
            Box.WordWrap = true;
            // Windows' own bar is kept - it is what scrolls the text, and the wheel and the keys go
            // through it - and hidden: the box is wider than the room it is given by exactly the bar,
            // so the bar falls outside this control, where a child window is never drawn. The soft bar
            // is drawn in the gutter that leaves, from the box's own scroll position, exactly as the
            // list's is (SoftListHost).
            Box.ScrollBars = ScrollBars.Vertical;
            Box.BackColor = Palette.Inset;
            Box.ForeColor = Palette.Ink;
            Box.GotFocus += delegate { Invalidate(); };
            Box.LostFocus += delegate { Invalidate(); };
            Box.TextChanged += delegate { Changed(); };
            Box.HandleCreated += delegate { Changed(); };
            watcher = new Watcher(this);
            clip.BackColor = Palette.Inset;
            clip.Controls.Add(Box);
            Controls.Add(clip);
            // The well's padding on the left, top and bottom; the scroll bar keeps to the edge.
            Padding = new Padding(Soft.Px(Brand.WellPadLeft), Soft.Px(Brand.WellPadTop), Soft.Px(6), Soft.Px(Brand.WellPadBottom));
            Height = Soft.Px(96);
        }

        /// Windows' own bar on the text box, as the box last drew it: how many lines there are, how
        /// many show, and the first that does.
        private ScrollInfo Read()
        {
            var info = new ScrollInfo();
            info.Size = Marshal.SizeOf(typeof(ScrollInfo));
            info.Mask = SIF_ALL;
            if (Box.IsHandleCreated && GetScrollInfo(Box.Handle, SB_VERT, ref info)) return info;
            info.Max = info.Page = info.Pos = 0;
            return info;
        }

        // The box is asked once a change and the answer kept: GetScrollInfo is cheap, but the bar asks
        // for all three while it draws and drags, and a keystroke must not cost three trips and a repaint.
        private ScrollInfo last;

        public int Extent { get { return Math.Max(0, last.Max - last.Min + 1); } }

        public int Viewport { get { return Math.Max(1, last.Page); } }

        public int Offset { get { return last.Pos; } }

        public void ScrollTo(int offset)
        {
            if (!Box.IsHandleCreated) return;
            int first = (int)SendMessage(Box.Handle, EM_GETFIRSTVISIBLELINE, IntPtr.Zero, IntPtr.Zero);
            SendMessage(Box.Handle, EM_LINESCROLL, IntPtr.Zero, (IntPtr)(offset - first));
            Changed();
        }

        public void Page(int direction)
        {
            ScrollTo(Offset + direction * Math.Max(1, Viewport - 1));
        }

        /// The box's scrolling, whoever caused it - the wheel, a key, the caret moving - so the soft
        /// bar is where the text is. WM_VSCROLL reaches the box's parent, which is this control.
        private sealed class Watcher : NativeWindow
        {
            private readonly SoftTextArea area;

            internal Watcher(SoftTextArea area)
            {
                this.area = area;
                area.Box.HandleCreated += delegate { AssignHandle(area.Box.Handle); };
                area.Box.HandleDestroyed += delegate { ReleaseHandle(); };
                area.Disposed += delegate { ReleaseHandle(); };
            }

            protected override void WndProc(ref Message m)
            {
                base.WndProc(ref m);
                if (m.Msg == WM_VSCROLL || m.Msg == 0x020A || m.Msg == 0x0102 || m.Msg == 0x0100)
                    area.Changed();                      // the wheel and the keys scroll it too
            }
        }

        /// Where the soft bar is, and whether there is one: the gutter is kept only while the text is
        /// taller than the box.
        private void Changed()
        {
            if (IsDisposed || !IsHandleCreated) return;
            ScrollInfo now = Read();
            bool moved = now.Pos != last.Pos || now.Page != last.Page || now.Max != last.Max || now.Min != last.Min;
            last = now;
            if (!moved) return;                          // nothing to draw again: a keystroke costs nothing
            int gutter = Soft.Px(SoftBar.TrackWidth);
            Rectangle track = Extent > Viewport
                ? new Rectangle(Width - Padding.Right - gutter, Padding.Top, gutter,
                                Math.Max(0, Height - Padding.Vertical))
                : Rectangle.Empty;
            bool appeared = track.IsEmpty != bar.Track.IsEmpty;
            bar.Track = track;                           // invalidates what it covers itself
            if (appeared) PerformLayout();               // the gutter came or went: the box's width did too
            else if (!track.IsEmpty) Invalidate(track);
        }

        internal SoftScrollBar Bar { get { return bar; } }

        protected override void OnLayout(LayoutEventArgs levent)
        {
            base.OnLayout(levent);
            int room = Math.Max(0, Width - Padding.Horizontal);
            // Wider than the room by the bar, so Windows' bar sits outside this control and is never
            // drawn; narrower by the gutter while the soft bar shows, so no text runs under it.
            int native = SystemInformation.VerticalScrollBarWidth;
            int gutter = bar.Track.IsEmpty ? 0 : Soft.Px(SoftBar.TrackWidth);
            int tall = Math.Max(0, Height - Padding.Vertical);
            clip.SetBounds(Padding.Left, Padding.Top, Math.Max(0, room - gutter), tall);
            Box.SetBounds(0, 0, Math.Max(0, room - gutter + native), tall);
            Changed();
        }

        protected override void OnPaintBackground(PaintEventArgs e)
        {
            float radius = Soft.PxF(Brand.RadiusControl);
            Ground.PaintBehind(this, e.Graphics, ClientRectangle, radius);
            Soft.InsetWell(e.Graphics, ClientRectangle, radius, Box.Focused);
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            base.OnPaint(e);
            if (!bar.Track.IsEmpty) bar.Paint(e.Graphics);
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
            BackColor = Palette.Inset;
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
            string shown = text.Length == 0 ? " " : text;
            int room = width - Soft.Px(28);
            int textHeight = TextRenderer.MeasureText(Soft.Wrap(shown, Font, room, Words), Font, new Size(room, int.MaxValue),
                                                      Words).Height;
            return new Size(width, textHeight + Soft.Px(24));
        }

        // The message wraps in the well, Korean between its words (Soft.Wrap).
        private const TextFormatFlags Words = TextFormatFlags.WordBreak | TextFormatFlags.TextBoxControl | TextFormatFlags.Left;

        protected override void OnPaint(PaintEventArgs e)
        {
            float radius = Soft.PxF(Brand.RadiusControl);
            Ground.PaintBehind(this, e.Graphics, ClientRectangle, radius);
            Soft.InsetWell(e.Graphics, ClientRectangle, radius, false);
            int room = Math.Max(0, Width - Soft.Px(Brand.WellPadLeft + Brand.WellPadRight));
            TextRenderer.DrawText(e.Graphics, Soft.Wrap(text, Font, room, Words), Font,
                                  new Rectangle(Soft.Px(Brand.WellPadLeft), Soft.Px(Brand.WellPadTop), room, Height),
                                  Palette.Ink, Words);
        }
    }
}
