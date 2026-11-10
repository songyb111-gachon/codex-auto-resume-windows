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
    ///
    /// v0.6.23: each of those changes glides (SoftSurfaceGlide) - hover and enabled in brand's transition, a press and its
    /// release in its shorter press time - and a press from the keyboard shows as one from the mouse does. The shadow goes
    /// and comes at the moment of the press: a shadow has no way to fade (Elevation).
    internal sealed class SoftButton : Button, ISoftLifted, IBusyFace
    {
        private bool primary, danger, hover, pressed;
        private bool held;
        private readonly LiftTracker tracker;
        private readonly SoftSurfaceGlide glide;

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
            glide = new SoftSurfaceGlide(this, Wanted);
        }

        internal bool Primary
        {
            get { return primary; }
            set { primary = value; glide.Changed(); Invalidate(); }
        }

        /// A button whose action cannot be taken back: its words are in the danger colour.
        internal bool Danger
        {
            get { return danger; }
            set { danger = value; glide.Changed(); Invalidate(); }
        }

        /// Whether it looks enabled: it is, or it was turned off a moment ago by a call that may yet be over at once (BusyHold).
        private bool LooksEnabled { get { return Enabled || held; } }

        string ISoftLifted.Lift { get { return LooksEnabled && !pressed ? "control" : null; } }
        float ISoftLifted.Radius { get { return Soft.PxF(Palette.RadiusControl); } }
        Rectangle ISoftLifted.Face { get { return ClientRectangle; } }
        bool ISoftLifted.Ring { get { return Focused && ShowFocusCues; } }

        private void Press(bool down)
        {
            if (pressed == down) return;
            pressed = down;
            glide.Changed(Motion.Press);
            Invalidate();
            tracker.Update();
        }

        /// What its state looks like, for SoftSurfaceGlide.
        private SurfaceLook Wanted()
        {
            if (!LooksEnabled) return new SurfaceLook(Palette.Surface, Palette.Line, Palette.Muted);
            if (primary)
            {
                Color accent = pressed ? Palette.AccentPressed : hover ? Palette.AccentHover : Palette.Accent;
                return new SurfaceLook(accent, accent, Palette.OnAccent);
            }
            return new SurfaceLook(pressed ? Palette.Inset : hover ? Palette.Surface : Palette.Raised, Palette.Line,
                                   danger ? Palette.Danger : Palette.Ink);
        }

        private void Hover(bool over)
        {
            hover = over;
            glide.Changed();
        }

        protected override void OnMouseEnter(EventArgs e) { Hover(true); base.OnMouseEnter(e); }
        protected override void OnMouseLeave(EventArgs e) { Press(false); Hover(false); base.OnMouseLeave(e); }
        protected override void OnMouseDown(MouseEventArgs e) { if (e.Button == MouseButtons.Left) Press(true); base.OnMouseDown(e); }
        protected override void OnMouseUp(MouseEventArgs e) { Press(false); base.OnMouseUp(e); }

        // Space presses it while the key is down, as Windows' own button does; Enter clicks it at once, and shows until the key
        // comes up. The key's own action, and the click, stay ButtonBase's.
        protected override void OnKeyDown(KeyEventArgs e) { if (e.KeyCode == Keys.Space) Press(true); base.OnKeyDown(e); }
        protected override void OnKeyUp(KeyEventArgs e) { if (e.KeyCode == Keys.Space || e.KeyCode == Keys.Enter) Press(false); base.OnKeyUp(e); }

        protected override bool ProcessDialogKey(Keys keyData)
        {
            if (keyData == Keys.Enter && Focused && Enabled) Press(true);
            return base.ProcessDialogKey(keyData);
        }

        protected override void OnEnabledChanged(EventArgs e)
        {
            held = !Enabled && BusyHold.Join(this);
            if (!Enabled && pressed) { pressed = false; }
            glide.Changed();
            Invalidate();
            base.OnEnabledChanged(e);
        }

        void IBusyFace.HoldEnded()
        {
            if (!held || IsDisposed) return;
            held = false;
            glide.Changed();
            Invalidate();
            tracker.Update();
        }

        protected override void OnGotFocus(EventArgs e) { Invalidate(); base.OnGotFocus(e); }
        protected override void OnLostFocus(EventArgs e) { Press(false); Invalidate(); base.OnLostFocus(e); }

        protected override void Dispose(bool disposing)
        {
            if (disposing) glide.Dispose();
            base.Dispose(disposing);
        }

        public override Size GetPreferredSize(Size proposedSize)
        {
            if (Font == null || Font.FontFamily.Name != Typeface.Persian) return base.GetPreferredSize(proposedSize);
            // Native Button measures mixed-script text differently when its parent is mirrored.
            Size words = Soft.Measure(Text, Font, int.MaxValue, TextFormatFlags.SingleLine);
            return new Size(Math.Max(MinimumSize.Width, words.Width + Padding.Horizontal + Soft.Px(12)),
                            Math.Max(MinimumSize.Height, words.Height + Padding.Vertical + Soft.Px(10)));
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            Rectangle face = ClientRectangle;
            float radius = Soft.PxF(Palette.RadiusControl);
            Ground.PaintBehind(this, g, face, radius);
            SurfaceLook look = glide.Now;
            Color text = look.Ink;
            Soft.Body(g, face, radius, look.Fill, look.Edge, pressed && LooksEnabled);
            TextRenderer.DrawText(g, Text, Font, face, text,
                                  Mirror.Words(Mirror.Of(this), TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter |
                                                                TextFormatFlags.SingleLine | TextFormatFlags.EndEllipsis));
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
    ///
    /// v0.6.23: it answers the pointer as well - the well comes up under it, held down a switch's knob widens and a box darkens,
    /// the same from the keyboard's Space - and a check box's mark is drawn on along its stroke. A frame lays down one picture of
    /// the ground (GroundShot) and cached glyphs (BoxGlyphs) rather than working either out again.
    internal sealed class SoftCheck : CheckBox, ISoftLifted, IBusyFace
    {
        private readonly LiftTracker tracker;
        private readonly Transition turn, hot, down, live;
        private readonly GroundShot shot = new GroundShot();
        private bool box, held;

        internal SoftCheck()
        {
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint |
                     ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
            Cursor = Cursors.Hand;
            AccessibleRole = AccessibleRole.CheckButton;
            tracker = new LiftTracker(this, "control");
            turn = Part(0.0);
            hot = Part(0.0);
            down = Part(0.0);
            live = Part(1.0);
        }

        // One of the things that move, repainting the glyph where it is now.
        private Transition Part(double value)
        {
            var part = new Transition(this, value);
            part.Where = delegate { return Glyph; };
            return part;
        }

        /// How far under the pointer it is drawn, and how far held down, each from 0 to 1 (for the tests).
        internal double Hot { get { return hot.Value; } }
        internal double Down { get { return down.Value; } }

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

        /// Whether a line too long for the width it is offered goes on in more lines rather than end in an ellipsis
        /// (v0.6.14): the power action's switch, whose line says what it is set to - in German, French, Russian and
        /// Ukrainian longer than the narrowest window's card for sleep and hibernate. A line that fits is measured and
        /// drawn exactly as without it; a longer one breaks where a WrapLabel's lines break (Soft.Wrap).
        internal bool Wraps { get; set; }

        private const TextFormatFlags WrapFormat = TextFormatFlags.Left | TextFormatFlags.WordBreak;

        /// Its text in the lines it is drawn in, `width` wide.
        private string Lines(int width)
        {
            return Soft.Wrap(Text ?? "", Font, Math.Max(1, width), WrapFormat);
        }

        /// The switch's track, or the check box's box: at the left, on the control's middle line - at the right in a
        /// mirrored window (v0.6.20, Mirror), its words then left of it.
        internal Rectangle Glyph
        {
            get
            {
                Rectangle glyph;
                if (box)
                {
                    int size = Soft.Px(Brand.CheckSize);
                    glyph = new Rectangle(0, (Height - size) / 2, size, size);
                }
                else
                {
                    int height = Soft.Px(Brand.SwitchHeight);
                    glyph = new Rectangle(0, (Height - height) / 2, Soft.Px(Brand.SwitchWidth), height);
                }
                return Mirror.Box(Mirror.Of(this), Width, glyph);
            }
        }

        // No lift - a switch and a box are wells - but the focus ring runs outside the control on
        // the left, so the ground draws that part of it.
        string ISoftLifted.Lift { get { return null; } }
        float ISoftLifted.Radius { get { return box ? Soft.PxF(Palette.RadiusCheck) : Soft.Px(Brand.SwitchHeight) / 2f; } }
        Rectangle ISoftLifted.Face { get { return Glyph; } }
        bool ISoftLifted.Ring { get { return Focused && ShowFocusCues; } }

        public override Size GetPreferredSize(Size proposedSize)
        {
            // Remembered (Soft.Measure, v0.6.14): a table asks for this at several widths in every pass, and a page
            // settles in up to four - thousands of measurements of the same words on each layout of Settings.
            Size text = Soft.Measure(Text ?? "", Font, int.MaxValue, TextFormatFlags.SingleLine);
            int glyphWidth = box ? Soft.Px(Brand.CheckSize) : Soft.Px(Brand.SwitchWidth);
            int glyphHeight = box ? Soft.Px(Brand.CheckSize) : Soft.Px(Brand.SwitchHeight);
            int beside = glyphWidth + Gap + Soft.Px(6);
            // Wrapping, only where the width offered is too narrow for the one line - and, as Label answers, a width of
            // 0 or 1 is none.
            if (Wraps && proposedSize.Width > 1 && beside + text.Width > proposedSize.Width)
            {
                int width = Math.Max(1, proposedSize.Width - beside);
                text = Soft.Measure(Lines(width), Font, width, WrapFormat);
            }
            return new Size(beside + text.Width, Math.Max(glyphHeight, text.Height) + Soft.Px(6));
        }

        protected override void OnCheckedChanged(EventArgs e)
        {
            // Paint only: the glyph glides to its new state, and nothing is laid out.
            turn.To(Checked ? 1.0 : 0.0, Motion.Allowed(this));
            Invalidate();
            base.OnCheckedChanged(e);
        }

        private void Held(bool on) { down.To(on ? 1.0 : 0.0, Motion.Allowed(this), Motion.Press); }

        protected override void OnMouseEnter(EventArgs e) { hot.To(1.0, Motion.Allowed(this)); base.OnMouseEnter(e); }
        protected override void OnMouseLeave(EventArgs e) { Held(false); hot.To(0.0, Motion.Allowed(this)); base.OnMouseLeave(e); }
        protected override void OnMouseDown(MouseEventArgs e) { if (e.Button == MouseButtons.Left) Held(true); base.OnMouseDown(e); }
        protected override void OnMouseUp(MouseEventArgs e) { Held(false); base.OnMouseUp(e); }
        protected override void OnKeyDown(KeyEventArgs e) { if (e.KeyCode == Keys.Space) Held(true); base.OnKeyDown(e); }
        protected override void OnKeyUp(KeyEventArgs e) { if (e.KeyCode == Keys.Space) Held(false); base.OnKeyUp(e); }

        protected override void OnEnabledChanged(EventArgs e)
        {
            held = !Enabled && BusyHold.Join(this);
            if (!Enabled) { down.To(0.0, false); hot.To(0.0, false); }
            live.To(Enabled || held ? 1.0 : 0.0, Motion.Allowed(this));
            Invalidate();
            base.OnEnabledChanged(e);
        }

        void IBusyFace.HoldEnded()
        {
            if (!held || IsDisposed) return;
            held = false;
            live.To(Enabled ? 1.0 : 0.0, Motion.Allowed(this));
            Invalidate();
        }

        protected override void OnGotFocus(EventArgs e) { Invalidate(); base.OnGotFocus(e); }
        protected override void OnLostFocus(EventArgs e) { Held(false); Invalidate(); base.OnLostFocus(e); }
        protected override void OnTextChanged(EventArgs e) { Invalidate(); base.OnTextChanged(e); }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                turn.Dispose();
                hot.Dispose();
                down.Dispose();
                live.Dispose();
                shot.Dispose();
            }
            base.Dispose(disposing);
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            Rectangle glyph = Glyph;
            // A frame of a glide repaints the glyph alone, and lays down the one picture of the ground it took at its first.
            bool frame = (turn.Running || hot.Running || down.Running || live.Running) && glyph.Contains(e.ClipRectangle);
            if (frame) shot.Paint(this, g, glyph);
            else
            {
                shot.Forget();
                Ground.PaintArea(this, g, ClientRectangle);
            }
            double on = turn.Value;
            bool mirrored = Mirror.Of(this);
            if (box) DrawBoxLive(g, glyph, on, live.Value, hot.Value, down.Value);
            else Soft.SwitchLive(g, glyph, on, live.Value, hot.Value, down.Value, Parent != null ? Ground.Colour(Parent) : Palette.Card, mirrored);
            if (frame) return;
            int wide = glyph.Width + Gap;
            var textBounds = Mirror.Box(mirrored, Width, new Rectangle(wide, 0, Math.Max(0, Width - wide), Height));
            Color ink = Enabled || held ? ForeColor : Palette.Muted;
            int room = textBounds.Width - Soft.Px(6);
            if (Wraps && TextRenderer.MeasureText(Text ?? "", Font, new Size(int.MaxValue, int.MaxValue),
                                                  TextFormatFlags.SingleLine).Width > room)
            {
                // In the lines GetPreferredSize measured, the block centred on the glyph's middle line.
                string lines = Lines(room);
                int height = Soft.Measure(lines, Font, Math.Max(1, room), WrapFormat).Height;
                TextRenderer.DrawText(g, lines, Font, new Rectangle(textBounds.X, (Height - height) / 2, textBounds.Width, height),
                                      ink, Mirror.Words(mirrored, WrapFormat));
            }
            else
                TextRenderer.DrawText(g, Text, Font, textBounds, ink,
                                      Mirror.Words(mirrored, TextFormatFlags.VerticalCenter | TextFormatFlags.Left |
                                                             TextFormatFlags.SingleLine | TextFormatFlags.EndEllipsis));
            if (Focused && ShowFocusCues)
                Soft.Ring(g, glyph, box ? Soft.PxF(Palette.RadiusCheck) : glyph.Height / 2f);
        }

        /// The check box in `face`, a CheckSize square at the window's scale: its fill, the inset well
        /// while it is unchecked and enabled, its hairline, and the mark - the brand's centre line,
        /// stroked CheckStroke wide with flat ends and a mitred corner.
        internal static void DrawBox(Graphics g, Rectangle face, bool on, bool enabled)
        {
            BoxBody(g, face, on, enabled);
            BoxMark(g, face, on, enabled, 1.0);
        }

        // The box without its mark: the fill, the inset well while it has one, the hairline.
        private static void BoxBody(Graphics g, Rectangle face, bool on, bool enabled)
        {
            Color fill, edge;
            bool well;
            BoxColours(on, enabled, out fill, out edge, out well);
            Soft.Body(g, face, Soft.PxF(Palette.RadiusCheck), fill, edge, well ? "inset" : null);
        }

        // Its colours: the design's own in the theme in effect (Tokens: Soft's, Classic's or Plain's), and the well only
        // where the design has depth - in Classic and Plain an empty box is its fill and its hairline. The system's in
        // High Contrast.
        private static void BoxColours(bool on, bool enabled, out Color fill, out Color edge, out bool well)
        {
            if (Palette.Contrast)
            {
                fill = Brand.CheckSystemFill(on, enabled);
                edge = Brand.CheckSystemEdge(on, enabled);
                well = false;
                return;
            }
            fill = Tokens.CheckFill(on, enabled);
            edge = Tokens.CheckEdge(on, enabled);
            well = Palette.Depth && Brand.CheckWell(on, enabled);
        }

        // The mark, as far along its stroke as `length` says, from its start: all of it at 1, exactly as it has always been.
        private static void BoxMark(Graphics g, Rectangle face, bool on, bool enabled, double length)
        {
            Color mark;
            bool marked = Palette.Contrast ? Brand.CheckSystemMark(on, enabled, out mark) : Tokens.CheckMark(on, enabled, out mark);
            if (!marked || length <= 0.0) return;
            float scale = (float)SettingsForm.DpiScale;
            var start = new PointF(face.X + Brand.CheckMarkStartX * scale, face.Y + Brand.CheckMarkStartY * scale);
            var corner = new PointF(face.X + Brand.CheckMarkCornerX * scale, face.Y + Brand.CheckMarkCornerY * scale);
            var end = new PointF(face.X + Brand.CheckMarkEndX * scale, face.Y + Brand.CheckMarkEndY * scale);
            GraphicsState state = g.Save();
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.PixelOffsetMode = PixelOffsetMode.Half;
            using (var pen = new Pen(mark, Soft.PxF(Brand.CheckStroke)))
            {
                pen.StartCap = LineCap.Flat;
                pen.EndCap = LineCap.Flat;
                pen.LineJoin = LineJoin.Miter;
                if (length >= 1.0) g.DrawLines(pen, new[] { start, corner, end });
                else
                {
                    double first = Math.Sqrt(Square(corner.X - start.X) + Square(corner.Y - start.Y));
                    double second = Math.Sqrt(Square(end.X - corner.X) + Square(end.Y - corner.Y));
                    double drawn = (first + second) * length;
                    if (drawn <= first) g.DrawLine(pen, start, Along(start, corner, drawn / first));
                    else g.DrawLines(pen, new[] { start, corner, Along(corner, end, (drawn - first) / second) });
                }
            }
            g.Restore(state);
        }

        private static double Square(double value) { return value * value; }

        private static PointF Along(PointF from, PointF to, double part)
        {
            return new PointF((float)(from.X + (to.X - from.X) * part), (float)(from.Y + (to.Y - from.Y) * part));
        }

        /// The check box `on` of the way from unchecked (0) to checked (1), as it moves between them: the unchecked box, the
        /// checked box's fill and edge over it at that opacity, and the mark drawn on along its stroke that far (v0.6.23; until
        /// then the mark faded with the fill). Both boxes are kept pictures (BoxGlyphs), so a frame makes none. At 0 and 1 it
        /// is exactly DrawBox.
        internal static void DrawBoxAt(Graphics g, Rectangle face, double on, bool enabled)
        {
            if (on <= 0.0 || on >= 1.0 || Palette.Contrast || face.Width <= 0 || face.Height <= 0)
            {
                DrawBox(g, face, on >= 0.5, enabled);
                return;
            }
            Rectangle dest = BoxGlyphs.Around(face);
            g.DrawImage(BoxGlyphs.Of(face, false, enabled), dest);
            Soft.Faded(g, BoxGlyphs.Of(face, true, enabled), dest, on);
            BoxMark(g, face, true, enabled, on);
        }

        /// The check box with what else moves, each from 0 to 1 and exact at its ends: `live`, how enabled it is, `hover`, the
        /// pointer on it, `press`, held down.
        internal static void DrawBoxLive(Graphics g, Rectangle face, double on, double live, double hover, double press)
        {
            bool enabled = live >= 0.5;
            bool whole = on <= 0.0 || on >= 1.0;
            if (Palette.Contrast || face.Width <= 0 || face.Height <= 0 || (hover <= 0.0 && press <= 0.0 && (live <= 0.0 || live >= 1.0)))
            {
                DrawBoxAt(g, face, on, enabled);
                return;
            }
            bool chosen = on >= 0.5;
            if (whole && live > 0.0 && live < 1.0)
            {
                // Between enabled and not: the one over the other, at how far it has come.
                Rectangle dest = BoxGlyphs.Around(face);
                g.DrawImage(BoxGlyphs.Of(face, chosen, false), dest);
                Soft.Faded(g, BoxGlyphs.Of(face, chosen, true), dest, live);
                BoxMark(g, face, chosen, enabled, 1.0);
                return;
            }
            if (whole) BoxBody(g, face, chosen, enabled);
            else
            {
                Rectangle dest = BoxGlyphs.Around(face);
                g.DrawImage(BoxGlyphs.Of(face, false, enabled), dest);
                Soft.Faded(g, BoxGlyphs.Of(face, true, enabled), dest, on);
            }
            // Over the body and under the mark: under the pointer it comes up a step, held down it goes down one.
            Tint(g, face, chosen ? Palette.AccentHover : Palette.Surface, hover * 0.8);
            Tint(g, face, chosen ? Palette.AccentPressed : Palette.Accent, press * (chosen ? 1.0 : 0.25));
            BoxMark(g, face, whole ? chosen : true, enabled, whole ? 1.0 : on);
        }

        private static void Tint(Graphics g, Rectangle face, Color colour, double amount)
        {
            if (amount <= 0.0) return;
            int hairline = Soft.Hairline;
            GraphicsState state = g.Save();
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.PixelOffsetMode = PixelOffsetMode.Half;
            using (GraphicsPath path = Soft.Rounded(Rectangle.Inflate(face, -hairline, -hairline), Math.Max(0f, Soft.PxF(Palette.RadiusCheck) - hairline)))
            using (var brush = new SolidBrush(Soft.WithAlpha(colour, amount)))
                g.FillPath(brush, path);
            g.Restore(state);
        }

        /// The two boxes a moving check box is made of (v0.6.23): each one's body, drawn once for its size, state and colours and
        /// kept, so a frame of the glide lays pictures down and makes none. Until then every frame drew a new bitmap.
        internal static class BoxGlyphs
        {
            private static readonly Dictionary<string, Bitmap> kept = new Dictionary<string, Bitmap>();

            /// How many have been drawn since the window started: what a test counts across the frames of a glide.
            internal static int Made;

            internal static Rectangle Around(Rectangle face)
            {
                return new Rectangle(face.X - 1, face.Y - 1, face.Width + 2, face.Height + 2);
            }

            internal static Bitmap Of(Rectangle face, bool on, bool enabled)
            {
                Color fill, edge;
                bool well;
                BoxColours(on, enabled, out fill, out edge, out well);
                string key = face.Width.ToString() + "x" + face.Height.ToString() + (on ? "+" : "-") + (enabled ? "e" : "d") +
                             (well ? "w" : "f") + fill.ToArgb().ToString() + "," + edge.ToArgb().ToString();
                Bitmap found;
                if (kept.TryGetValue(key, out found)) return found;
                // A theme, a design or a scale change is what puts a new one in here, so this holds a few.
                if (kept.Count >= 24)
                {
                    foreach (Bitmap old in kept.Values) old.Dispose();
                    kept.Clear();
                }
                found = new Bitmap(face.Width + 2, face.Height + 2, PixelFormat.Format32bppPArgb);
                Made++;
                using (Graphics drawn = Graphics.FromImage(found))
                {
                    drawn.Clear(Color.Transparent);
                    BoxBody(drawn, new Rectangle(1, 1, face.Width, face.Height), on, enabled);
                }
                kept[key] = found;
                return found;
            }
        }
    }

    /// A link in the window's own terms (v0.6.23, the design audit's D4): accent words on the card, underlined under the pointer and
    /// from the keyboard, darker held down, gliding between those as a button does, and the soft focus ring. Enter and Space press it;
    /// a screen reader is told it is a link and can press it.
    internal sealed class SoftLink : Control
    {
        private bool hover, pressed;
        private readonly SoftSurfaceGlide glide;

        internal SoftLink()
        {
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                     ControlStyles.ResizeRedraw | ControlStyles.Selectable, true);
            TabStop = true;
            Cursor = Cursors.Hand;
            AccessibleRole = AccessibleRole.Link;
            glide = new SoftSurfaceGlide(this, Wanted);
        }

        private const TextFormatFlags Line = TextFormatFlags.VerticalCenter | TextFormatFlags.Left | TextFormatFlags.SingleLine |
                                             TextFormatFlags.NoPrefix | TextFormatFlags.EndEllipsis | TextFormatFlags.NoPadding;

        private SurfaceLook Wanted()
        {
            Color words = pressed ? Palette.AccentPressed : Palette.Accent;
            bool marked = hover || pressed || (Focused && ShowFocusCues);
            return new SurfaceLook(Color.Empty, Color.Empty, words, marked ? words : SurfaceLook.None(words));
        }

        private void Press(bool down)
        {
            if (pressed == down) return;
            pressed = down;
            glide.Changed(Motion.Press);
        }

        protected override void OnMouseEnter(EventArgs e) { hover = true; glide.Changed(); base.OnMouseEnter(e); }
        protected override void OnMouseLeave(EventArgs e) { hover = false; Press(false); glide.Changed(); base.OnMouseLeave(e); }
        protected override void OnMouseDown(MouseEventArgs e) { if (e.Button == MouseButtons.Left) { Focus(); Press(true); } base.OnMouseDown(e); }
        protected override void OnMouseUp(MouseEventArgs e) { Press(false); base.OnMouseUp(e); }
        protected override void OnGotFocus(EventArgs e) { glide.Changed(); Invalidate(); base.OnGotFocus(e); }
        protected override void OnLostFocus(EventArgs e) { Press(false); glide.Changed(); Invalidate(); base.OnLostFocus(e); }
        protected override void OnTextChanged(EventArgs e) { Invalidate(); base.OnTextChanged(e); }
        protected override bool IsInputKey(Keys keyData) { return keyData == Keys.Enter || keyData == Keys.Space || base.IsInputKey(keyData); }

        protected override void OnKeyDown(KeyEventArgs e)
        {
            if (e.KeyCode == Keys.Enter || e.KeyCode == Keys.Space) Press(true);
            base.OnKeyDown(e);
        }

        protected override void OnKeyUp(KeyEventArgs e)
        {
            bool key = (e.KeyCode == Keys.Enter || e.KeyCode == Keys.Space) && pressed;
            Press(false);
            base.OnKeyUp(e);
            if (key) OnClick(EventArgs.Empty);
        }

        public override Size GetPreferredSize(Size proposedSize)
        {
            return Soft.Measure(Text ?? "", Font, int.MaxValue, Line) + new Size(Soft.Px(6), Soft.Px(6));
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            Ground.PaintArea(this, g, ClientRectangle);
            bool mirrored = Mirror.Of(this);
            SurfaceLook look = glide.Now;
            int inset = Soft.Px(3);
            var line = new Rectangle(inset, 0, Math.Max(0, Width - 2 * inset), Height);
            TextRenderer.DrawText(g, Text, Font, line, look.Ink, Mirror.Words(mirrored, Line));
            Size words = Soft.Measure(Text ?? "", Font, int.MaxValue, Line);
            int wide = Math.Min(words.Width, line.Width);
            var box = new Rectangle(mirrored ? line.Right - wide : line.X, (Height - words.Height) / 2, wide, words.Height);
            if (look.Mark.A > 0) g.FillRectangle(Soft.Fill(look.Mark), box.X, box.Bottom - Soft.Hairline, box.Width, Soft.Hairline);
            if (Focused && ShowFocusCues) Soft.FocusRing(g, Rectangle.Inflate(box, 1, 1), Soft.PxF(Palette.RadiusSmall) / 2f);
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing) glide.Dispose();
            base.Dispose(disposing);
        }

        protected override AccessibleObject CreateAccessibilityInstance()
        {
            return new LinkAccessible(this);
        }

        private sealed class LinkAccessible : Control.ControlAccessibleObject
        {
            private readonly SoftLink link;

            internal LinkAccessible(SoftLink owner) : base(owner) { link = owner; }

            public override string DefaultAction { get { return "Press"; } }

            public override void DoDefaultAction() { link.OnClick(EventArgs.Empty); }
        }
    }

    /// A control whose disabled look can wait a moment (BusyHold).
    internal interface IBusyFace
    {
        /// The moment is over: look as you are.
        void HoldEnded();
    }

    /// Every action turned every button in the window off and on again around its call, and most calls are over in 17 to
    /// 87 ms: a flash of flat grey on each click, longer than the action (v0.6.23, the design audit's M3). The controls are
    /// disabled at once as ever - a second click is refused - but for the first 150 ms of a call those turned off go on
    /// looking as they did. A call still running then shows, and fades; one over by then has shown nothing. With motion
    /// reduced there is no holding at all.
    internal static class BusyHold
    {
        internal const int Milliseconds = 150;

        private static readonly List<IBusyFace> faces = new List<IBusyFace>();
        private static Timer timer;
        private static Action lapsed;

        /// Whether a call's first moments are on now.
        internal static bool On { get; private set; }

        /// A call has started. `whenLapsed` runs if it is still running when the moment is over. False when nothing is held.
        internal static bool Begin(Action whenLapsed)
        {
            if (On) return true;
            if (Soft.ReduceMotion) return false;
            if (timer == null)
            {
                timer = new Timer();
                timer.Interval = Milliseconds;
                timer.Tick += delegate { Lapse(); };
            }
            On = true;
            lapsed = whenLapsed;
            timer.Start();
            return true;
        }

        /// `face` has just been turned off: whether it goes on looking as it did for now.
        internal static bool Join(IBusyFace face)
        {
            if (On) faces.Add(face);
            return On;
        }

        /// The last call is over.
        internal static void End()
        {
            lapsed = null;
            Finish();
        }

        /// The moment is over now, as if its timer had run out: a call still running looks it (also a still of one: RenderBusy).
        internal static void Lapse()
        {
            Action then = lapsed;
            lapsed = null;
            Finish();
            if (then != null) then();
        }

        private static void Finish()
        {
            if (timer != null) timer.Stop();
            On = false;
            IBusyFace[] held = faces.ToArray();
            faces.Clear();
            foreach (IBusyFace face in held) face.HoldEnded();
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
        private readonly Transition focus;

        internal SoftNumber()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                     ControlStyles.UserPaint | ControlStyles.ResizeRedraw, true);
            BackColor = Palette.Inset;
            Spin.BorderStyle = BorderStyle.None;
            Spin.BackColor = Palette.Inset;
            Spin.ForeColor = Palette.Ink;
            focus = new Transition(this, 0.0);
            Spin.Enter += delegate { focus.To(1.0, Motion.Allowed(this)); };
            Spin.Leave += delegate { focus.To(0.0, Motion.Allowed(this)); };
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
            int width = Math.Max(0, Width - left - right);
            // v0.6.20: mirrored, the wider side is the right one, where the number starts; Windows puts the spin buttons left.
            Spin.SetBounds(Mirror.X(Mirror.Of(this), Width, left, width), Math.Max(0, (Height - Spin.Height) / 2), width, Spin.Height);
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            float radius = Soft.PxF(Palette.RadiusControl);
            Ground.PaintBehind(this, e.Graphics, ClientRectangle, radius);
            // At rest what the keyboard says (v0.6.23); only while it moves, where the glide has got to.
            Soft.InsetWellAt(e.Graphics, ClientRectangle, radius, focus.Running ? focus.Value : Spin.ContainsFocus ? 1.0 : 0.0);
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing) focus.Dispose();
            base.Dispose(disposing);
        }

        /// Draws the spin buttons as two muted wedges on the well in place of the grey
        /// scroll-bar buttons. Only painting is taken over; clicks, holds and the keyboard go on
        /// to the control underneath. v0.6.23: the half under the pointer has a pill behind its wedge, and held
        /// down the pill comes up a step - the only control in the window that showed nothing of a press.
        private sealed class SpinPainter : NativeWindow
        {
            private const int WM_MOUSEMOVE = 0x0200, WM_LBUTTONDOWN = 0x0201, WM_LBUTTONUP = 0x0202, WM_MOUSELEAVE = 0x02A3;

            private readonly Control buttons;
            private readonly Transition glow;
            private int hotHalf = -1;
            private bool over, held;

            internal SpinPainter(Control buttons)
            {
                this.buttons = buttons;
                glow = new Transition(buttons, 0.0);
                buttons.Disposed += delegate { glow.Dispose(); };
                AssignHandle(buttons.Handle);
            }

            /// Which half the pointer is on (0 the upper, 1 the lower, -1 neither), and whether it is held down (for the tests).
            internal int Half { get { return over ? hotHalf : -1; } }
            internal bool Held { get { return held; } }

            private void Hot(int now)
            {
                if (now < 0)
                {
                    if (!over) return;
                    over = false;
                    glow.To(0.0, Motion.Allowed(buttons), Motion.Press);
                    return;
                }
                if (!over)
                {
                    over = true;
                    hotHalf = now;
                    glow.To(1.0, Motion.Allowed(buttons), Motion.Press);
                }
                else if (hotHalf != now)
                {
                    hotHalf = now;
                    buttons.Invalidate();
                }
            }

            protected override void WndProc(ref Message m)
            {
                if (NativePaint.Handle(ref m, buttons.ClientSize, Draw)) return;
                if (m.Msg == WM_MOUSEMOVE && buttons.Enabled)
                {
                    int y = unchecked((short)((m.LParam.ToInt64() >> 16) & 0xFFFF));
                    Hot(y < buttons.ClientSize.Height / 2 ? 0 : 1);
                }
                else if (m.Msg == WM_MOUSELEAVE) { Hot(-1); held = false; }
                else if (m.Msg == WM_LBUTTONDOWN) { held = true; buttons.Invalidate(); }
                else if (m.Msg == WM_LBUTTONUP) { held = false; buttons.Invalidate(); }
                base.WndProc(ref m);
            }

            private void Draw(Graphics g)
            {
                Size size = buttons.ClientSize;
                using (var brush = new SolidBrush(Palette.Inset)) g.FillRectangle(brush, 0, 0, size.Width, size.Height);
                double shown = glow.Value;
                if (shown > 0.0 && hotHalf >= 0 && !Palette.Contrast)
                {
                    int tall2 = size.Height / 2;
                    var pill = new Rectangle(0, hotHalf == 0 ? 0 : tall2, size.Width, hotHalf == 0 ? tall2 : size.Height - tall2);
                    GraphicsState under = g.Save();
                    g.SmoothingMode = SmoothingMode.AntiAlias;
                    g.PixelOffsetMode = PixelOffsetMode.Half;
                    using (GraphicsPath path = Soft.Rounded(pill, Soft.PxF(Palette.RadiusSmall) / 2f))
                    using (var brush = new SolidBrush(Soft.WithAlpha(held ? Palette.Raised : Palette.Surface, shown)))
                        g.FillPath(brush, path);
                    g.Restore(under);
                }
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
        private readonly SoftSurfaceGlide glide;

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
            glide = new SoftSurfaceGlide(this, Wanted);
        }

        // In High Contrast the chosen card is filled with Highlight, so everything drawn on it takes HighlightText, the
        // colour every contrast theme pairs with Highlight - as the page tabs do. In Accent the radio dot was Highlight on
        // Highlight, and the title and help in WindowText were under 1.5:1.
        private SurfaceLook Wanted()
        {
            bool onHighlight = Checked && Palette.Contrast;
            return new SurfaceLook(onHighlight ? Palette.AccentSoft : Checked ? Palette.Inset : hover ? Palette.Surface : Palette.Raised,
                                   Checked ? Palette.Accent : Palette.Line,
                                   onHighlight ? SystemColors.HighlightText : Checked ? Palette.Accent : Palette.Ink,
                                   onHighlight ? SystemColors.HighlightText : Checked ? Palette.Accent : Palette.Muted);
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
        float ISoftLifted.Radius { get { return Soft.PxF(Palette.RadiusControl); } }
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
            // Remembered (Soft.Measure, v0.6.14): a table asks for this at several widths in every pass.
            int top = Soft.Measure(Soft.Wrap(Text ?? "", title, textWidth, Words), title, textWidth, Words).Height;
            int help = string.IsNullOrEmpty(Help) ? 0
                     : Soft.Measure(Soft.Wrap(Help, Font, textWidth, Words), Font, textWidth, Words).Height + Soft.Px(2);
            return Soft.Px(12) + top + help + Soft.Px(12);
        }

        // v0.6.23: the colours and the dot glide; the shadow goes and comes at the moment of the change (Elevation has no fade).
        protected override void OnCheckedChanged(EventArgs e) { glide.Changed(); Invalidate(); tracker.Update(); base.OnCheckedChanged(e); }
        protected override void OnMouseEnter(EventArgs e) { hover = true; glide.Changed(); base.OnMouseEnter(e); }
        protected override void OnMouseLeave(EventArgs e) { hover = false; glide.Changed(); base.OnMouseLeave(e); }
        protected override void OnGotFocus(EventArgs e) { Invalidate(); base.OnGotFocus(e); }
        protected override void OnLostFocus(EventArgs e) { Invalidate(); base.OnLostFocus(e); }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                glide.Dispose();
                if (titleFont != null) { titleFont.Dispose(); titleFont = null; }
            }
            base.Dispose(disposing);
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            var body = Body(Width, Height);
            float radius = Soft.PxF(Palette.RadiusControl);
            Ground.PaintBehind(this, g, ClientRectangle, radius);
            bool onHighlight = Checked && Palette.Contrast;
            SurfaceLook look = glide.Now;
            // Resting, raised as a button and as the panel's segment for the same setting are - no top light in
            // dark. Chosen, a well.
            Soft.Body(g, ClientRectangle, radius, look.Fill, look.Edge, Checked && Palette.Depth);
            // The radio mark, so the card still says "one of these" without its colour.
            float mark = Soft.PxF(16);
            // v0.6.20: mirrored, the mark at the right and the words left of it (Mirror).
            bool mirrored = Mirror.Of(this);
            var ring = Mirror.Box(mirrored, (float)Width, new RectangleF(body.X + Soft.PxF(14), body.Y + Soft.PxF(12), mark, mark));
            Color markColour = look.Mark;
            GraphicsState state = g.Save();
            g.SmoothingMode = SmoothingMode.AntiAlias;
            using (var pen = new Pen(markColour, Soft.PxF(1.5))) g.DrawEllipse(pen, ring);
            // The dot fades in on the card chosen, and out on the one left, as the rest of it glides.
            double shown = !glide.Running ? (Checked ? 1.0 : 0.0) : Checked ? glide.Progress : 1.0 - glide.Progress;
            if (shown > 0.0)
            {
                float dot = mark * 0.5f;
                using (var brush = new SolidBrush(shown >= 1.0 ? markColour : Soft.WithAlpha(markColour, shown)))
                    g.FillEllipse(brush, ring.X + (mark - dot) / 2f, ring.Y + (mark - dot) / 2f, dot, dot);
            }
            g.Restore(state);
            Rectangle column = Mirror.Box(mirrored, Width, TextColumn(Width));
            int left = column.X, textWidth = column.Width;
            TextFormatFlags words = Mirror.Words(mirrored, Words);
            Font title = TitleFont;
            string heading = Soft.Wrap(Text ?? "", title, textWidth, Words);
            Size top = TextRenderer.MeasureText(heading, title, new Size(textWidth, int.MaxValue), Words);
            TextRenderer.DrawText(g, heading, title, new Rectangle(left, (int)body.Y + Soft.Px(10), textWidth, top.Height),
                                  look.Ink, words);
            if (!string.IsNullOrEmpty(Help))
                TextRenderer.DrawText(g, Soft.Wrap(Help, Font, textWidth, Words), Font,
                                      new Rectangle(left, (int)body.Y + Soft.Px(12) + top.Height, textWidth, Height),
                                      onHighlight ? SystemColors.HighlightText : Palette.Secondary,
                                      words);
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
        private readonly Transition focus;

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
            focus = new Transition(this, 0.0);
            Box.GotFocus += delegate { focus.To(1.0, Motion.Allowed(this)); };
            Box.LostFocus += delegate { focus.To(0.0, Motion.Allowed(this)); };
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
                ? Mirror.Box(Mirror.Of(this), Width, new Rectangle(Width - Padding.Right - gutter, Padding.Top, gutter,
                                                                   Math.Max(0, Height - Padding.Vertical)))
                : Rectangle.Empty;
            bool appeared = track.IsEmpty != bar.Track.IsEmpty;
            bar.Track = track;                           // invalidates what it covers itself
            if (appeared) PerformLayout();               // the gutter came or went: the box's width did too
            else if (!track.IsEmpty) Invalidate(track);
        }

        internal SoftScrollBar Bar { get { return bar; } }

        private bool oneLine;

        /// One line (issue #34): a box a person types one line in - a login, a word, a name, a search - or one that
        /// shows one line. The well's top and bottom padding is a message's, 12 px each, and in a box a field or a
        /// button high that left less than a line, so the text was cut off. A one-line box keeps its size and place,
        /// and its line is centred in it as a button's text is: the same well, the same left padding, the line whole.
        internal bool OneLine
        {
            get { return oneLine; }
            set
            {
                oneLine = value;
                if (value)
                {
                    Box.AcceptsReturn = false;
                    Box.WordWrap = false;
                }
                PerformLayout();
            }
        }

        /// The height one line of the box's text takes: its font's line, and the edit control's own pixel above it.
        internal int LineHeight { get { return Box.Font.Height + Soft.Px(2); } }

        protected override void OnLayout(LayoutEventArgs levent)
        {
            base.OnLayout(levent);
            int room = Math.Max(0, Width - Padding.Horizontal);
            // Wider than the room by the bar, so Windows' bar sits outside this control and is never
            // drawn; narrower by the gutter while the soft bar shows, so no text runs under it.
            int native = SystemInformation.VerticalScrollBarWidth;
            int gutter = bar.Track.IsEmpty ? 0 : Soft.Px(SoftBar.TrackWidth);
            // v0.6.20: mirrored, the well's wide padding is on the right, where the words start, and the soft bar on the left.
            // The box is mirrored by Windows, whose own bar then stands at its left: it is set that much left of the clip,
            // where it is not drawn (Mirror).
            bool mirrored = Mirror.Of(this);
            int shown = Math.Max(0, room - gutter);
            int clipX = mirrored ? Width - Padding.Left - shown : Padding.Left;
            int boxX = mirrored ? -native : 0;
            if (oneLine)
            {
                // The line centred in the box, as a button's text is - never taller than the box itself.
                int line = Math.Min(LineHeight, Height);
                int top = Math.Max(0, (Height - line) / 2);
                clip.SetBounds(clipX, top, shown, line);
                Box.SetBounds(boxX, 0, Math.Max(0, room - gutter + native), line);
                Changed();
                return;
            }
            int tall = Math.Max(0, Height - Padding.Vertical);
            clip.SetBounds(clipX, Padding.Top, shown, tall);
            Box.SetBounds(boxX, 0, Math.Max(0, room - gutter + native), tall);
            Changed();
        }

        protected override void OnPaintBackground(PaintEventArgs e)
        {
            float radius = Soft.PxF(Palette.RadiusControl);
            Ground.PaintBehind(this, e.Graphics, ClientRectangle, radius);
            // At rest what the keyboard says (v0.6.23); only while it moves, where the glide has got to.
            Soft.InsetWellAt(e.Graphics, ClientRectangle, radius, focus.Running ? focus.Value : Box.Focused ? 1.0 : 0.0);
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            base.OnPaint(e);
            if (!bar.Track.IsEmpty) bar.Paint(e.Graphics);
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing) focus.Dispose();
            base.Dispose(disposing);
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
            float radius = Soft.PxF(Palette.RadiusControl);
            Ground.PaintBehind(this, e.Graphics, ClientRectangle, radius);
            Soft.InsetWell(e.Graphics, ClientRectangle, radius, false);
            int room = Math.Max(0, Width - Soft.Px(Brand.WellPadLeft + Brand.WellPadRight));
            // v0.6.20: mirrored, from the right, read right to left (Mirror).
            bool mirrored = Mirror.Of(this);
            TextRenderer.DrawText(e.Graphics, Soft.Wrap(text, Font, room, Words), Font,
                                  new Rectangle(Mirror.X(mirrored, Width, Soft.Px(Brand.WellPadLeft), room), Soft.Px(Brand.WellPadTop),
                                                room, Height),
                                  Palette.Ink, Mirror.Words(mirrored, Words));
        }
    }
}
