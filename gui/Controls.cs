// Codex Auto Resume - the soft controls the window is drawn with.
//
// v0.6.4 puts the window on the same material as the panel in Codex: a canvas, cards of the
// same stuff lifted by the panel's own two soft shadows, controls resting on them with a
// smaller pair, and values sitting in wells with the inset pair. Every colour, size and shadow
// comes from gui/Brand.cs, generated from src/codex_auto_resume/brand.py, which is also where
// the panel's stylesheet and the tray popup read theirs.
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
// A child window cannot paint outside itself, so a lift is not drawn by the control that has
// it: the container behind it - its ground - stamps the shadow before the control paints its
// body, and the control repaints only its rounded corners from that ground (see Ground).
//
// C# 5 (the in-box compiler): no string interpolation, no null-conditional operator. No string
// switch and no initialized constant array either: both make the compiler emit a randomly
// named class, and build/normalize_pe.py refuses an executable that has one.

using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.Runtime.InteropServices;
using System.Windows.Forms;

namespace CodexAutoResume
{
    /// The palette as the window uses it, with High Contrast honoured in one place.
    internal static class Palette
    {
        internal static readonly bool Contrast = SystemInformation.HighContrast;
        internal static readonly Color Ink           = Contrast ? SystemColors.WindowText : Brand.Ink;
        internal static readonly Color Muted         = Contrast ? SystemColors.GrayText : Brand.Muted;
        internal static readonly Color Secondary     = Contrast ? SystemColors.WindowText : Brand.Muted;
        internal static readonly Color Line          = Contrast ? SystemColors.WindowFrame : Brand.Line;
        internal static readonly Color Surface       = Contrast ? SystemColors.Window : Brand.Surface;
        internal static readonly Color Canvas        = Contrast ? SystemColors.Control : Brand.Canvas;
        internal static readonly Color Raised        = Contrast ? SystemColors.Window : Brand.Raised;
        internal static readonly Color Inset         = Contrast ? SystemColors.Window : Brand.Inset;
        internal static readonly Color Accent        = Contrast ? SystemColors.Highlight : Brand.Accent;
        internal static readonly Color AccentHover   = Contrast ? SystemColors.Highlight : Brand.AccentHover;
        internal static readonly Color AccentPressed = Contrast ? SystemColors.Highlight : Brand.AccentPressed;
        internal static readonly Color OnAccent      = Contrast ? SystemColors.HighlightText : Brand.OnAccent;
        internal static readonly Color AccentSoft    = Contrast ? SystemColors.Highlight : Brand.AccentSoft;
        internal static readonly Color Focus         = Contrast ? SystemColors.WindowText : Brand.Focus;
        internal static readonly Color Active        = Contrast ? SystemColors.Highlight : Brand.Active;
        internal static readonly Color Idle          = Contrast ? SystemColors.GrayText : Brand.Idle;
        internal static readonly Color Attention     = Contrast ? SystemColors.WindowText : Brand.Attention;
        internal static readonly Color Success       = Contrast ? SystemColors.WindowText : Brand.Success;
        internal static readonly Color Waiting       = Contrast ? SystemColors.WindowText : Brand.Waiting;
        internal static readonly Color Warning       = Contrast ? SystemColors.WindowText : Brand.Warning;
        internal static readonly Color Danger        = Contrast ? SystemColors.WindowText : Brand.Danger;
        internal static readonly Color Paused        = Contrast ? SystemColors.GrayText : Brand.Paused;
    }

    /// Drawing helpers shared by every soft control.
    internal static class Soft
    {
        [DllImport("user32.dll")]
        private static extern bool SystemParametersInfo(int action, int param, ref bool value, int winIni);

        [DllImport("user32.dll")]
        private static extern int GetWindowLong(IntPtr window, int index);

        private const int SPI_GETCLIENTAREAANIMATION = 0x1042;
        private const int GWL_STYLE = -16;
        private const int WS_VISIBLE = 0x10000000;

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

        /// A 1px hairline in device pixels: whole pixels only, as the panel's border is drawn, so it
        /// stays crisp - one pixel up to 199%, two at 200%.
        internal static int Hairline
        {
            get { return Math.Max(1, (int)Math.Floor(SettingsForm.DpiScale + 1e-6)); }
        }

        /// Whether a control is shown as far as its own window goes, whatever its parents are.
        /// `Visible` answers false for everything inside a window that has not been shown yet,
        /// which would leave a capture of that window without a single shadow.
        internal static bool Shown(Control control)
        {
            if (!control.IsHandleCreated) return control.Visible;
            return (GetWindowLong(control.Handle, GWL_STYLE) & WS_VISIBLE) != 0;
        }

        private static readonly System.Reflection.MethodInfo OwnState =
            typeof(Control).GetMethod("GetState", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance);

        /// Whether a control was told to be visible, which is whether layout makes room for it -
        /// whatever its parents are, and with or without a window.
        internal static bool OwnVisible(Control control)
        {
            return OwnState == null ? control.Visible : (bool)OwnState.Invoke(control, new object[] { 2 });
        }

        /// Hands a turn of the wheel that `control` would not use to the nearest page around it that
        /// can still scroll that way. True when one did.
        internal static bool PassWheel(Control control, int delta)
        {
            for (Control c = control == null ? null : control.Parent; c != null; c = c.Parent)
            {
                var page = c as SoftPage;
                if (page != null && page.Wheel(delta)) return true;
            }
            return false;
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

        /// A body filling `face`: the fill, then the hairline inside its edge - the panel's
        /// `background` and `border: 1px solid`. The caller has already painted what lies
        /// behind the corners, and any inset shadow goes between the two (`inset`).
        internal static void Body(Graphics g, Rectangle face, float radius, Color fill, Color edge, bool inset)
        {
            GraphicsState state = g.Save();
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.PixelOffsetMode = PixelOffsetMode.Half;
            using (var path = Rounded(face, radius))
            using (var brush = new SolidBrush(fill))
                g.FillPath(brush, path);
            int hairline = Hairline;
            if (inset)
                Elevation.StampInset(g, Rectangle.Inflate(face, -hairline, -hairline), radius - hairline, face);
            Edge(g, face, radius, edge, hairline);
            g.Restore(state);
        }

        /// A line `width` device pixels wide, just inside the edge of a body filling `face`.
        internal static void Edge(Graphics g, Rectangle face, float radius, Color colour, float width)
        {
            GraphicsState state = g.Save();
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.PixelOffsetMode = PixelOffsetMode.Half;
            var inner = new RectangleF(face.X + width / 2f, face.Y + width / 2f, face.Width - width, face.Height - width);
            using (var path = Rounded(inner, Math.Max(0f, radius - width / 2f)))
            using (var pen = new Pen(colour, width))
                g.DrawPath(pen, path);
            g.Restore(state);
        }

        /// A shallow well a value sits in: the inset fill, the inset shadow, the hairline, or a
        /// two-pixel focus line inside the edge while it has the keyboard. The panel draws its
        /// focus outline outside the field; a child window cannot, so it goes inside.
        internal static void InsetWell(Graphics g, Rectangle face, float radius, bool focused)
        {
            Body(g, face, radius, Palette.Inset, Palette.Line, !Palette.Contrast);
            if (focused) Edge(g, face, radius, Palette.Focus, PxF(Brand.FocusWidth));
        }

        /// The well at a position that need not be whole pixels, for a page that draws one
        /// inside a cell rather than as a control.
        internal static void Well(Graphics g, RectangleF body, float radius, bool focused)
        {
            InsetWell(g, Rectangle.Round(body), radius, focused);
        }

        /// The switch every true-or-false setting is drawn as: a 40 by 22 pill, a well with a
        /// grey knob at the left when off, the accent with a white knob at the right when on.
        /// Disabled, the track and knob fade halfway into `ground`; the words beside it say
        /// the rest.
        internal static void Switch(Graphics g, Rectangle track, bool on, bool enabled, Color ground)
        {
            float radius = track.Height / 2f;
            Color fill = on ? Palette.Accent : Palette.Inset;
            Color edge = on ? Palette.Accent : Palette.Line;
            Color knob = on ? Palette.OnAccent : Palette.Contrast ? SystemColors.WindowText : Palette.Muted;
            if (!enabled && !Palette.Contrast)
            {
                fill = Mix(fill, ground, 0.5);
                edge = Mix(edge, ground, 0.5);
                knob = Mix(knob, ground, 0.5);
            }
            Body(g, track, radius, fill, edge, !on && enabled && !Palette.Contrast);
            float size = PxF(Brand.Knob), inset = PxF(Brand.KnobInset);
            float x = track.X + inset + (on ? PxF(Brand.KnobTravel) : 0f);
            GraphicsState state = g.Save();
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.PixelOffsetMode = PixelOffsetMode.Half;
            using (var brush = new SolidBrush(knob))
                g.FillEllipse(brush, x, track.Y + (track.Height - size) / 2f, size, size);
            g.Restore(state);
        }

        /// The keyboard focus ring as the panel draws it: two pixels wide, two pixels out from
        /// the face, its corners following the face's.
        internal static void Ring(Graphics g, Rectangle face, float radius)
        {
            GraphicsState state = g.Save();
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.PixelOffsetMode = PixelOffsetMode.Half;
            float width = PxF(Brand.FocusWidth), middle = PxF(Brand.FocusOffset) + width / 2f;
            var ring = new RectangleF(face.X - middle, face.Y - middle, face.Width + middle * 2f, face.Height + middle * 2f);
            using (var path = Rounded(ring, radius + middle))
            using (var pen = new Pen(Palette.Focus, width))
                g.DrawPath(pen, path);
            g.Restore(state);
        }

        /// The older ring, drawn inside a control that insets its own body.
        internal static void FocusRing(Graphics g, RectangleF around, float radius)
        {
            g.SmoothingMode = SmoothingMode.AntiAlias;
            float gap = PxF(2);
            var ring = new RectangleF(around.X - gap, around.Y - gap, around.Width + gap * 2, around.Height + gap * 2);
            using (var path = Rounded(ring, radius + gap))
            using (var pen = new Pen(Palette.Focus, PxF(2)))
                g.DrawPath(pen, path);
        }

        // ------------------------------------------------------------------ type

        private static Font baseFont;
        private static readonly Dictionary<string, Font> fonts = new Dictionary<string, Font>();

        /// The font every role is a variant of: the window's, which is Windows' message font.
        /// Settable so a measurement can stand in another scale's or another system's font.
        internal static Font BaseFont
        {
            get
            {
                if (baseFont == null) baseFont = SystemFonts.MessageBoxFont;
                return baseFont;
            }
            set
            {
                // The old fonts are not disposed: a control may still be drawing with one.
                baseFont = value;
                fonts.Clear();
            }
        }

        /// A font for a role in the panel's type table, at the size the window has always used
        /// for it - only the weight follows the panel. Cached: a page switch used to create two
        /// fonts every time, and a cached font must never be disposed by whoever asked for it.
        ///
        /// body, help, count: the window's font. label, button, chip, nav: the same (500, which
        /// is Regular). heading, name, nav_current: 600. title: 1.5pt larger, 600 (card
        /// headings). display: 2.5pt larger, 600 (the header). figure: 3pt larger, 600 (the
        /// Overview's count of what is waiting).
        internal static Font RoleFont(string role)
        {
            Font font;
            string key = role ?? "body";
            if (fonts.TryGetValue(key, out font)) return font;
            float larger = key == "display" ? 2.5f : key == "title" ? 1.5f : key == "figure" ? 3f : 0f;
            int weight = key == "heading" || key == "name" || key == "nav_current" || key == "title" ||
                         key == "display" || key == "figure" ? 600
                       : key == "label" || key == "button" || key == "chip" || key == "nav" ? 500 : 400;
            font = Weighted(BaseFont, BaseFont.SizeInPoints + larger, weight);
            fonts[key] = font;
            return font;
        }

        /// A CSS weight in GDI. 400 and 500 are Regular: Malgun Gothic and the CJK UI faces have
        /// no medium, and a medium Segoe UI would run wider than every label was measured at.
        /// 600 is the face's own semibold where it has one ("Segoe UI" and its variants), and
        /// Bold otherwise.
        internal static Font Weighted(Font from, float points, int weight)
        {
            if (weight < 600) return new Font(from.FontFamily, points, FontStyle.Regular, GraphicsUnit.Point);
            string family = from.FontFamily.Name;
            if (family.StartsWith("Segoe UI", StringComparison.Ordinal) && !family.EndsWith("Semibold", StringComparison.Ordinal))
            {
                try
                {
                    using (var semibold = new FontFamily(family + " Semibold"))
                        return new Font(semibold.Name, points, FontStyle.Regular, GraphicsUnit.Point);
                }
                catch (ArgumentException) { /* not installed: Bold, below */ }
            }
            return new Font(from.FontFamily, points, FontStyle.Bold, GraphicsUnit.Point);
        }

        // ------------------------------------------------------------------ chips

        /// The tinted ground a state word sits on: the state's colour, faint, over the surface.
        internal static Color Tint(Color tone, Color over)
        {
            return Palette.Contrast ? over : Mix(over, tone, 0.12);
        }

        internal static Size ChipSize(string text, Font font)
        {
            Size measured = TextRenderer.MeasureText(text ?? "", font, new Size(int.MaxValue, int.MaxValue),
                                                     TextFormatFlags.SingleLine | TextFormatFlags.NoPadding);
            return new Size(measured.Width + Px(Brand.ChipPadX * 2), measured.Height + Px(6));
        }

        /// A pill with a state word, in the chip role's font. Returns how wide it was drawn.
        internal static int Chip(Graphics g, Rectangle cell, string text, Color tone)
        {
            return Chip(g, cell, text, RoleFont("chip"), tone, Palette.Surface);
        }

        /// A pill with a state word: no border and no shadow, its ground the state's colour at
        /// 12% over the surface whatever it sits on, as the panel's chips are. In High Contrast
        /// the ground is `over`, the ground it sits on. Returns how wide it was drawn.
        internal static int Chip(Graphics g, Rectangle cell, string text, Font font, Color tone, Color over)
        {
            if (string.IsNullOrEmpty(text)) return 0;
            Size size = ChipSize(text, font);
            int width = Math.Min(size.Width, Math.Max(Px(Brand.CountMinWidth), cell.Width));
            var body = new RectangleF(cell.X, cell.Y + (float)Math.Floor((cell.Height - size.Height) / 2f), width, size.Height);
            GraphicsState state = g.Save();
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.PixelOffsetMode = PixelOffsetMode.Half;
            using (var path = Rounded(body, body.Height / 2f))
            using (var brush = new SolidBrush(Palette.Contrast ? over : Mix(Palette.Surface, tone, 0.12)))
                g.FillPath(brush, path);
            g.Restore(state);
            TextRenderer.DrawText(g, text, font, Rectangle.Round(body), tone,
                                  TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter |
                                  TextFormatFlags.SingleLine | TextFormatFlags.EndEllipsis | TextFormatFlags.NoPadding);
            return width;
        }
    }

    /// The panel's shadows, drawn the way its stylesheet defines them.
    ///
    /// A CSS blur B is a Gaussian with sigma B/2, so one shadow's alpha at distance d from a
    /// straight edge is alpha * Phi((offset - d) / sigma) - brand.shadow_alpha, which matches
    /// the panel's own screenshot to about one colour level. Each shadow is computed once per
    /// shape and scale into a premultiplied bitmap - the rounded body's coverage, blurred with
    /// that Gaussian integrated over each pixel - and then stamped in nine pieces: the corners as
    /// they are, the one-pixel middle row and column stretched along the straight edges. A body
    /// too short to have a straight middle gets a bitmap of its exact length instead, which for
    /// buttons, fields and switches - all one height - is still only a handful.
    ///
    /// Nothing is drawn in High Contrast mode.
    internal static class Elevation
    {
        private sealed class Template
        {
            internal Bitmap Image;
            internal int MiddleX = -1, MiddleY = -1;   // the column and row that stretch; -1 draws it whole
        }

        // Stamped with nearest-neighbour sampling on half-pixel centres, so a one-pixel strip
        // stretches to exactly its own pixels and nothing bleeds in from beside it - which also
        // keeps GDI+ off the slow path that image attributes force on every draw.
        private static readonly Dictionary<long, Template> cache = new Dictionary<long, Template>();

        // Shadows by number: 0 and 1 a card's, 2 and 3 a control's, 4 and 5 a well's. The even
        // one is the dark shadow and the odd one the highlight; the panel lists the dark one
        // first, and a list is painted last to first, so the highlight goes down first.
        private static int First(string recipe)
        {
            if (recipe == "card") return 0;
            if (recipe == "control") return 2;
            if (recipe == "inset") return 4;
            return -1;
        }

        private static void Shadow(int id, out double dx, out double dy, out double blur, out double alpha)
        {
            if (id == 0) { dx = Brand.ElevCardShadowDx; dy = Brand.ElevCardShadowDy; blur = Brand.ElevCardShadowBlur; alpha = Brand.ElevCardShadowAlpha; }
            else if (id == 1) { dx = Brand.ElevCardHighlightDx; dy = Brand.ElevCardHighlightDy; blur = Brand.ElevCardHighlightBlur; alpha = Brand.ElevCardHighlightAlpha; }
            else if (id == 2) { dx = Brand.ElevControlShadowDx; dy = Brand.ElevControlShadowDy; blur = Brand.ElevControlShadowBlur; alpha = Brand.ElevControlShadowAlpha; }
            else if (id == 3) { dx = Brand.ElevControlHighlightDx; dy = Brand.ElevControlHighlightDy; blur = Brand.ElevControlHighlightBlur; alpha = Brand.ElevControlHighlightAlpha; }
            else if (id == 4) { dx = Brand.ElevInsetShadowDx; dy = Brand.ElevInsetShadowDy; blur = Brand.ElevInsetShadowBlur; alpha = Brand.ElevInsetShadowAlpha; }
            else { dx = Brand.ElevInsetHighlightDx; dy = Brand.ElevInsetHighlightDy; blur = Brand.ElevInsetHighlightBlur; alpha = Brand.ElevInsetHighlightAlpha; }
            // Brand.cs holds them as floats, and 0.55f widened is not 0.55.
            alpha = Math.Round(alpha, 4);
        }

        private static Color Tone(int id)
        {
            return id % 2 == 0 ? Brand.ShadowDark : Brand.ShadowLight;
        }

        /// How far a recipe's shadows reach past its box, per side, in device pixels at the
        /// window's scale: offset plus three sigmas, past which a shadow is under a fifth of a
        /// percent of its strength (brand.reach). A ground that clips its children closer than
        /// this cuts their shadow off. The inset recipe reaches nothing outside.
        internal static Padding Reach(string recipe)
        {
            return Reach(recipe, SettingsForm.DpiScale);
        }

        internal static Padding Reach(string recipe, double scale)
        {
            int first = First(recipe);
            if (first < 0 || first >= 4) return Padding.Empty;
            int left = 0, top = 0, right = 0, bottom = 0;
            for (int id = first; id < first + 2; id++)
            {
                double dx, dy, blur, alpha;
                Shadow(id, out dx, out dy, out blur, out alpha);
                left = Math.Max(left, Far(-dx, blur, scale));
                top = Math.Max(top, Far(-dy, blur, scale));
                right = Math.Max(right, Far(dx, blur, scale));
                bottom = Math.Max(bottom, Far(dy, blur, scale));
            }
            return new Padding(left, top, right, bottom);
        }

        /// The reach above and to the left, where the highlight is.
        internal static int ReachNear(string recipe)
        {
            Padding reach = Reach(recipe);
            return Math.Max(reach.Left, reach.Top);
        }

        /// The reach below and to the right, where the shadow is.
        internal static int ReachFar(string recipe)
        {
            Padding reach = Reach(recipe);
            return Math.Max(reach.Right, reach.Bottom);
        }

        private static int Far(double offset, double blur, double scale)
        {
            return Math.Max(0, (int)Math.Ceiling((offset + 1.5 * blur) * scale - 1e-9));
        }

        /// A body's outer lift, "card" or "control", stamped around `body` (in the coordinates
        /// of `g`), drawing only the pieces that meet `clip`.
        internal static void StampOuter(Graphics g, Rectangle body, string recipe, float radius, Rectangle clip)
        {
            if (Palette.Contrast || body.Width <= 0 || body.Height <= 0) return;
            int first = First(recipe);
            if (first < 0 || first >= 4) return;
            Padding reach = Reach(recipe);
            var band = new Rectangle(body.X - reach.Left, body.Y - reach.Top, body.Width + reach.Horizontal, body.Height + reach.Vertical);
            if (!band.IntersectsWith(clip)) return;
            StampOne(g, first + 1, SettingsForm.DpiScale, body, radius, clip);
            StampOne(g, first, SettingsForm.DpiScale, body, radius, clip);
        }

        /// A well's inset shadow inside `box` - the well inside its hairline - whose corners have
        /// `radius`. It is already clipped to that shape.
        internal static void StampInset(Graphics g, Rectangle box, float radius, Rectangle clip)
        {
            if (Palette.Contrast || box.Width <= 0 || box.Height <= 0 || !box.IntersectsWith(clip)) return;
            StampOne(g, 5, SettingsForm.DpiScale, box, radius, clip);
            StampOne(g, 4, SettingsForm.DpiScale, box, radius, clip);
        }

        /// Drops every cached bitmap; the next stamp builds what it needs again.
        internal static void Forget()
        {
            foreach (Template template in cache.Values) template.Image.Dispose();
            cache.Clear();
        }

        internal static int Cached
        {
            get { return cache.Count; }
        }

        private static void StampOne(Graphics g, int id, double scale, Rectangle body, float radius, Rectangle clip)
        {
            double dx, dy, blur, alpha;
            Shadow(id, out dx, out dy, out blur, out alpha);
            bool inset = id >= 4;
            int reach = Spread(blur * scale / 2);
            radius = (float)Math.Max(0, Math.Min(radius, Math.Min(body.Width, body.Height) / 2.0));
            int core, pad, left = body.X, top = body.Y;
            double fx = 0, fy = 0;
            if (inset)
            {
                core = (int)Math.Ceiling(radius) + reach + (int)Math.Ceiling(Math.Max(Math.Abs(dx), Math.Abs(dy)) * scale) + 1;
                pad = 0;
            }
            else
            {
                // A shadow moved a fraction of a pixel keeps the fraction in its bitmap, so
                // 125% and 175% are as exact as the whole-pixel scales.
                int ix, iy;
                Whole(dx * scale, out ix, out fx);
                Whole(dy * scale, out iy, out fy);
                core = (int)Math.Ceiling(radius) + reach;
                pad = reach + 1;
                left = body.X + ix - pad;
                top = body.Y + iy - pad;
            }
            int canonical = 2 * core + 1;
            int width = body.Width >= canonical ? canonical : body.Width;
            int height = body.Height >= canonical ? canonical : body.Height;
            Template template = Get(id, scale, width, height, radius, fx, fy,
                                    width == canonical ? pad + core : -1, height == canonical ? pad + core : -1);

            GraphicsState state = g.Save();
            g.InterpolationMode = InterpolationMode.NearestNeighbor;
            g.PixelOffsetMode = PixelOffsetMode.Half;
            g.CompositingMode = CompositingMode.SourceOver;
            int across = body.Width + 2 * pad, down = body.Height + 2 * pad;
            int columns = template.MiddleX < 0 ? 1 : 3, rows = template.MiddleY < 0 ? 1 : 3;
            for (int row = 0; row < rows; row++)
            {
                int sourceY, sourceHeight, destY, destHeight;
                Span(template.MiddleY, template.Image.Height, down, row, out sourceY, out sourceHeight, out destY, out destHeight);
                for (int column = 0; column < columns; column++)
                {
                    // The middle of a sliced body lies under the body itself, or holds nothing.
                    if (row == 1 && column == 1) continue;
                    int sourceX, sourceWidth, destX, destWidth;
                    Span(template.MiddleX, template.Image.Width, across, column, out sourceX, out sourceWidth, out destX, out destWidth);
                    var dest = new Rectangle(left + destX, top + destY, destWidth, destHeight);
                    if (destWidth <= 0 || destHeight <= 0 || !dest.IntersectsWith(clip)) continue;
                    g.DrawImage(template.Image, dest, sourceX, sourceY, sourceWidth, sourceHeight, GraphicsUnit.Pixel);
                }
            }
            g.Restore(state);
        }

        private static void Whole(double value, out int whole, out double fraction)
        {
            whole = (int)Math.Floor(value);
            fraction = Math.Round((value - whole) * 8) / 8;
            if (fraction >= 1) { whole++; fraction = 0; }
        }

        /// One of the three pieces along an axis: before the middle, the middle stretched, after.
        private static void Span(int middle, int length, int total, int piece,
                                 out int source, out int sourceLength, out int dest, out int destLength)
        {
            if (middle < 0) { source = 0; sourceLength = length; dest = 0; destLength = length; return; }
            if (piece == 0) { source = 0; sourceLength = middle; dest = 0; destLength = middle; return; }
            int after = length - middle - 1;
            if (piece == 1) { source = middle; sourceLength = 1; dest = middle; destLength = total - middle - after; return; }
            source = middle + 1; sourceLength = after; dest = total - after; destLength = after;
        }

        private static Template Get(int id, double scale, int width, int height, double radius, double fx, double fy,
                                    int middleX, int middleY)
        {
            long key = id;
            key = key * 1024 + Math.Min(1023, (int)Math.Round(scale * 100));
            key = key * 4096 + Math.Min(4095, width);
            key = key * 4096 + Math.Min(4095, height);
            key = key * 16 + (int)Math.Round(fx * 8);
            key = key * 16 + (int)Math.Round(fy * 8);
            key = key * 16384 + Math.Min(16383, (int)Math.Round(radius * 8));
            Template template;
            if (cache.TryGetValue(key, out template)) return template;
            if (cache.Count >= 128) Forget();
            template = id >= 4 ? Inner(id, scale, width, height, radius) : Outer(id, scale, width, height, radius, fx, fy);
            template.MiddleX = middleX;
            template.MiddleY = middleY;
            cache[key] = template;
            return template;
        }

        private static Template Outer(int id, double scale, int width, int height, double radius, double fx, double fy)
        {
            double dx, dy, blur, alpha;
            Shadow(id, out dx, out dy, out blur, out alpha);
            double sigma = blur * scale / 2;
            int pad = Spread(sigma) + 1;
            int across = width + 2 * pad, down = height + 2 * pad;
            var shape = new double[across * down];
            Cover(shape, across, down, pad + fx, pad + fy, width, height, radius);
            return Make(Blur(shape, across, down, sigma), across, down, alpha, Tone(id));
        }

        /// An inset shadow is cast by everything outside the box, moved by the offset, blurred,
        /// and seen only inside the box.
        private static Template Inner(int id, double scale, int width, int height, double radius)
        {
            double dx, dy, blur, alpha;
            Shadow(id, out dx, out dy, out blur, out alpha);
            double sigma = blur * scale / 2, ox = dx * scale, oy = dy * scale;
            int margin = Spread(sigma) + (int)Math.Ceiling(Math.Max(Math.Abs(ox), Math.Abs(oy))) + 1;
            int across = width + 2 * margin, down = height + 2 * margin;
            var outside = new double[across * down];
            Cover(outside, across, down, margin + ox, margin + oy, width, height, radius);
            for (int i = 0; i < outside.Length; i++) outside[i] = 1 - outside[i];
            double[] blurred = Blur(outside, across, down, sigma);
            var inside = new double[width * height];
            Cover(inside, width, height, 0, 0, width, height, radius);
            for (int y = 0; y < height; y++)
                for (int x = 0; x < width; x++)
                    inside[y * width + x] *= blurred[(y + margin) * across + x + margin];
            return Make(inside, width, height, alpha, Tone(id));
        }

        private static Template Make(double[] values, int width, int height, double alpha, Color tone)
        {
            var pixels = new int[width * height];
            for (int i = 0; i < pixels.Length; i++)
            {
                int a = (int)Math.Round(255 * alpha * Math.Max(0, Math.Min(1, values[i])));
                if (a <= 0) continue;
                pixels[i] = (a << 24) | ((tone.R * a + 127) / 255 << 16) | ((tone.G * a + 127) / 255 << 8) | ((tone.B * a + 127) / 255);
            }
            var image = new Bitmap(width, height, PixelFormat.Format32bppPArgb);
            BitmapData data = image.LockBits(new Rectangle(0, 0, width, height), ImageLockMode.WriteOnly, PixelFormat.Format32bppPArgb);
            try
            {
                for (int y = 0; y < height; y++)
                    Marshal.Copy(pixels, y * width, new IntPtr(data.Scan0.ToInt64() + (long)y * data.Stride), width);
            }
            finally { image.UnlockBits(data); }
            var template = new Template();
            template.Image = image;
            return template;
        }

        /// Three sigmas, in whole pixels.
        private static int Spread(double sigma)
        {
            return sigma <= 0 ? 0 : (int)Math.Ceiling(3 * sigma - 1e-9);
        }

        /// How much of each pixel a rounded rectangle covers: sixteen samples where its edge
        /// crosses the pixel, one elsewhere.
        private static void Cover(double[] grid, int across, int down, double left, double top,
                                  double width, double height, double radius)
        {
            radius = Math.Max(0, Math.Min(radius, Math.Min(width, height) / 2));
            double cx = left + width / 2, cy = top + height / 2, hx = width / 2 - radius, hy = height / 2 - radius;
            for (int y = 0; y < down; y++)
                for (int x = 0; x < across; x++)
                {
                    double distance = Outside(x + 0.5 - cx, y + 0.5 - cy, hx, hy, radius);
                    double value;
                    if (distance <= -0.75) value = 1;
                    else if (distance >= 0.75) value = 0;
                    else
                    {
                        int hits = 0;
                        for (int sy = 0; sy < 4; sy++)
                            for (int sx = 0; sx < 4; sx++)
                                if (Outside(x + (sx + 0.5) / 4 - cx, y + (sy + 0.5) / 4 - cy, hx, hy, radius) <= 0) hits++;
                        value = hits / 16.0;
                    }
                    grid[y * across + x] = value;
                }
        }

        /// Signed distance from a rounded rectangle centred on the origin; negative inside.
        private static double Outside(double px, double py, double hx, double hy, double radius)
        {
            double qx = Math.Abs(px) - hx, qy = Math.Abs(py) - hy;
            double ox = Math.Max(qx, 0), oy = Math.Max(qy, 0);
            return Math.Sqrt(ox * ox + oy * oy) + Math.Min(Math.Max(qx, qy), 0) - radius;
        }

        /// The Gaussian integrated over each pixel, across and then down. Over a straight edge on
        /// a pixel boundary this is exactly Phi at each pixel's centre.
        private static double[] Blur(double[] source, int across, int down, double sigma)
        {
            int spread = Spread(sigma);
            if (spread == 0) return source;
            var kernel = new double[2 * spread + 1];
            for (int i = 0; i < kernel.Length; i++)
                kernel[i] = Phi((i - spread + 0.5) / sigma) - Phi((i - spread - 0.5) / sigma);
            var middle = new double[source.Length];
            for (int y = 0; y < down; y++)
            {
                int row = y * across;
                for (int x = 0; x < across; x++)
                {
                    double sum = 0;
                    int from = Math.Max(0, x - spread), to = Math.Min(across - 1, x + spread);
                    for (int k = from; k <= to; k++) sum += source[row + k] * kernel[k - x + spread];
                    middle[row + x] = sum;
                }
            }
            var result = new double[source.Length];
            for (int x = 0; x < across; x++)
                for (int y = 0; y < down; y++)
                {
                    double sum = 0;
                    int from = Math.Max(0, y - spread), to = Math.Min(down - 1, y + spread);
                    for (int k = from; k <= to; k++) sum += middle[k * across + x] * kernel[k - y + spread];
                    result[y * across + x] = sum;
                }
            return result;
        }

        private static double Phi(double x)
        {
            return 0.5 * (1 + Erf(x / Math.Sqrt(2)));
        }

        /// Abramowitz and Stegun 7.1.26: within 1.5e-7, far under a colour level.
        private static double Erf(double x)
        {
            double sign = x < 0 ? -1 : 1;
            x = Math.Abs(x);
            double t = 1 / (1 + 0.3275911 * x);
            double poly = ((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t;
            return sign * (1 - poly * Math.Exp(-x * x));
        }

        /// The shadows of `recipe` as they are stamped at `scale`, sampled across the middle of
        /// each straight edge: for each of its two shadows (the dark one first) and each side
        /// (left, top, right, bottom), the alpha 0.5, 1.5, 2.5 ... device pixels from the edge -
        /// outward from the body for "card" and "control", inward from inside the hairline for
        /// "inset". Draws into a bitmap and nowhere else; the tests hold it to brand.shadow_alpha.
        internal static float[] Profile(string recipe, double scale)
        {
            int first = First(recipe);
            if (first < 0) return new float[0];
            bool inset = first == 4;
            double dx, dy, blur, alpha;
            Shadow(first, out dx, out dy, out blur, out alpha);
            int samples = Spread(blur * scale / 2) + (int)Math.Ceiling(Math.Abs(dx) * scale) + 2;
            float radius = (float)((first == 0 ? Brand.RadiusCard : Brand.RadiusControl) * scale);
            int length = 4 * (samples + (int)Math.Ceiling(radius)) + 40;
            int margin = inset ? 0 : samples + 4;
            var result = new float[8 * samples];
            using (var bitmap = new Bitmap(length + 2 * margin, length + 2 * margin, PixelFormat.Format32bppArgb))
            {
                var body = new Rectangle(margin, margin, length, length);
                var all = new Rectangle(0, 0, bitmap.Width, bitmap.Height);
                int middle = margin + length / 2;
                for (int shadow = 0; shadow < 2; shadow++)
                {
                    using (Graphics g = Graphics.FromImage(bitmap))
                    {
                        g.Clear(Color.Transparent);
                        StampOne(g, first + shadow, scale, body, radius, all);
                    }
                    for (int i = 0; i < samples; i++)
                    {
                        int near = inset ? margin + i : margin - 1 - i;
                        int far = inset ? margin + length - 1 - i : margin + length + i;
                        result[(shadow * 4) * samples + i] = bitmap.GetPixel(near, middle).A / 255f;
                        result[(shadow * 4 + 1) * samples + i] = bitmap.GetPixel(middle, near).A / 255f;
                        result[(shadow * 4 + 2) * samples + i] = bitmap.GetPixel(far, middle).A / 255f;
                        result[(shadow * 4 + 3) * samples + i] = bitmap.GetPixel(middle, far).A / 255f;
                    }
                }
            }
            return result;
        }

        /// A `width` by `height` body of `recipe` as a page shows it, with `margin` device pixels
        /// of ground around it: a card on the canvas, a control on a card, a well on a card. The
        /// pixels as ARGB, row by row, for the tests that compare them with brand.elevation_colour.
        internal static int[] Render(string recipe, double scale, int width, int height, int margin)
        {
            int first = First(recipe);
            if (first < 0) return new int[0];
            bool inset = first == 4;
            Color fill = first == 0 ? Brand.Surface : inset ? Brand.Inset : Brand.Raised;
            float radius = (float)((first == 0 ? Brand.RadiusCard : Brand.RadiusControl) * scale);
            int hairline = Math.Max(1, (int)Math.Floor(scale + 1e-6));
            int across = width + 2 * margin, down = height + 2 * margin;
            var pixels = new int[across * down];
            using (var bitmap = new Bitmap(across, down, PixelFormat.Format32bppArgb))
            {
                using (Graphics g = Graphics.FromImage(bitmap))
                {
                    g.Clear(first == 0 ? Brand.Canvas : Brand.Surface);
                    var body = new Rectangle(margin, margin, width, height);
                    var all = new Rectangle(0, 0, across, down);
                    if (!inset)
                    {
                        StampOne(g, first + 1, scale, body, radius, all);
                        StampOne(g, first, scale, body, radius, all);
                    }
                    g.SmoothingMode = SmoothingMode.AntiAlias;
                    g.PixelOffsetMode = PixelOffsetMode.Half;
                    using (var path = Soft.Rounded(body, radius))
                    using (var brush = new SolidBrush(fill))
                        g.FillPath(brush, path);
                    if (inset)
                    {
                        Rectangle box = Rectangle.Inflate(body, -hairline, -hairline);
                        StampOne(g, 5, scale, box, radius - hairline, all);
                        StampOne(g, 4, scale, box, radius - hairline, all);
                    }
                    Soft.Edge(g, body, radius, Brand.Line, hairline);
                }
                BitmapData data = bitmap.LockBits(new Rectangle(0, 0, across, down), ImageLockMode.ReadOnly, PixelFormat.Format32bppArgb);
                try
                {
                    for (int y = 0; y < down; y++)
                        Marshal.Copy(new IntPtr(data.Scan0.ToInt64() + (long)y * data.Stride), pixels, y * across, across);
                }
                finally { bitmap.UnlockBits(data); }
            }
            return pixels;
        }
    }

    /// A control whose body the ground behind it lifts: a card, or a raised control.
    internal interface ISoftLifted
    {
        /// "card", "control", or null while it has no lift (pressed, disabled, chosen).
        string Lift { get; }

        /// The corner radius of its body, in device pixels.
        float Radius { get; }

        /// Its body, in its own coordinates.
        Rectangle Face { get; }

        /// Whether the keyboard focus ring is showing around the body.
        bool Ring { get; }
    }

    /// A container that paints the lifts of what it holds in its own background.
    internal interface ISoftGround { }

    /// A ground: a container's colour, then the shadows and focus rings of everything lifted
    /// on it.
    ///
    /// A child window is clipped to itself, so a control cannot draw its own shadow. The
    /// container behind it does, in its background, before the child paints its body; a
    /// rounded child fills its corners from the same ground (PaintBehind), so the shadow runs on
    /// behind them. A container that shows its parent's colour unchanged is looked through: the
    /// outermost such ancestor decides what is stamped, and each container on the way draws the
    /// part over its own area, so a control's shadow crosses from a row into its card's padding
    /// without a seam. SoftStack, SoftPage, SoftFlow, SoftCard and ChoiceGroup do this in their
    /// background; any other container holding a lifted control is given a Paint handler that
    /// does the same (Watch).
    internal static class Ground
    {
        private const int Depth = 6;
        private static readonly HashSet<Control> watched = new HashSet<Control>();

        /// A ground's background: its colour, then the lifts that reach into the clip.
        internal static void Paint(Control ground, PaintEventArgs e)
        {
            using (var brush = new SolidBrush(Colour(ground))) e.Graphics.FillRectangle(brush, e.ClipRectangle);
            Stamps(ground, e.Graphics, e.ClipRectangle);
        }

        /// The colour a control shows: its own, or the first opaque one behind it.
        internal static Color Colour(Control control)
        {
            for (Control c = control; c != null; c = c.Parent)
                if (c.BackColor.A == 255) return c.BackColor;
            return Palette.Canvas;
        }

        /// Whether a container shows its parent's ground unchanged, so a shadow may cross it.
        ///
        /// A page never does while its scroll bars show: it is then the edge of every shadow on it,
        /// as a scrolling box is in the panel. Seen through, a card scrolled out of sight left its
        /// shadow behind in the strip above the page. Without scroll bars nothing on the page can
        /// be offset, so its cards' lift runs on into the strips around it, where a page that was
        /// always an edge cut it in a visible line under the tabs and above the save bar.
        internal static bool SeeThrough(Control control)
        {
            if (control.Parent == null || control is ISoftLifted) return false;
            if (Scrolling(control)) return false;
            return control.BackColor.A < 255 || control.BackColor.ToArgb() == Colour(control.Parent).ToArgb();
        }

        /// Whether a control is a page that is showing a scroll bar: the soft one (SoftPage), or
        /// Windows' own on any other scrolling panel.
        internal static bool Scrolling(Control control)
        {
            var page = control as SoftPage;
            if (page != null) return page.Overflowing;
            var scroller = control as ScrollableControl;
            return scroller != null && scroller.AutoScroll &&
                   (scroller.VerticalScroll.Visible || scroller.HorizontalScroll.Visible);
        }

        /// Stamps every lift and focus ring that reaches into `clip`, in `painter`'s coordinates.
        internal static void Stamps(Control painter, Graphics g, Rectangle clip)
        {
            Control top = painter;
            int x = 0, y = 0;
            for (int depth = 0; depth < Depth && SeeThrough(top); depth++)
            {
                x += top.Left;
                y += top.Top;
                top = top.Parent;
            }
            var lifted = new List<KeyValuePair<Control, Point>>();
            Collect(top, -x, -y, lifted, 0);
            foreach (KeyValuePair<Control, Point> entry in lifted)
            {
                var item = (ISoftLifted)entry.Key;
                string lift = item.Lift;
                if (lift == null) continue;
                Rectangle face = item.Face;
                face.Offset(entry.Value);
                Elevation.StampOuter(g, face, lift, item.Radius, clip);
            }
            foreach (KeyValuePair<Control, Point> entry in lifted)
            {
                var item = (ISoftLifted)entry.Key;
                if (!item.Ring) continue;
                Rectangle face = item.Face;
                face.Offset(entry.Value);
                int ring = Soft.Px(Brand.FocusOffset + Brand.FocusWidth) + 1;
                if (Rectangle.Inflate(face, ring, ring).IntersectsWith(clip)) Soft.Ring(g, face, item.Radius);
            }
        }

        private static void Collect(Control container, int x, int y, List<KeyValuePair<Control, Point>> lifted, int depth)
        {
            foreach (Control child in container.Controls)
            {
                if (!Soft.Shown(child)) continue;
                int left = x + child.Left, top = y + child.Top;
                if (child is ISoftLifted)
                    lifted.Add(new KeyValuePair<Control, Point>(child, new Point(left, top)));
                else if (depth < Depth && child.Controls.Count > 0 && SeeThrough(child))
                    Collect(child, left, top, lifted, depth + 1);
            }
        }

        /// Paints the ground behind the four corners of a rounded body filling `face` of
        /// `child`, including any shadow that lies there - the child's own among them.
        internal static void PaintBehind(Control child, Graphics g, Rectangle face, float radius)
        {
            int size = Math.Min((int)Math.Ceiling(radius) + 1, Math.Min(face.Width, face.Height));
            if (size <= 0) return;
            var corners = new Rectangle[4];
            corners[0] = new Rectangle(face.Left, face.Top, size, size);
            corners[1] = new Rectangle(face.Right - size, face.Top, size, size);
            corners[2] = new Rectangle(face.Left, face.Bottom - size, size, size);
            corners[3] = new Rectangle(face.Right - size, face.Bottom - size, size, size);
            PaintAreas(child, g, corners, face);
        }

        /// Paints the ground behind `area` of `child`, for a control that is not a rectangle.
        internal static void PaintArea(Control child, Graphics g, Rectangle area)
        {
            var areas = new Rectangle[1];
            areas[0] = area;
            PaintAreas(child, g, areas, area);
        }

        private static void PaintAreas(Control child, Graphics g, Rectangle[] areas, Rectangle bounds)
        {
            Control parent = child.Parent;
            GraphicsState state = g.Save();
            using (var region = new Region())
            {
                region.MakeEmpty();
                foreach (Rectangle area in areas) region.Union(area);
                g.SetClip(region, CombineMode.Intersect);
            }
            using (var brush = new SolidBrush(parent == null ? Palette.Canvas : Colour(parent)))
                g.FillRectangle(brush, bounds);
            if (parent != null)
            {
                // The clip stays where it is on the device; only drawing moves.
                g.TranslateTransform(-child.Left, -child.Top);
                bounds.Offset(child.Left, child.Top);
                Stamps(parent, g, bounds);
            }
            g.Restore(state);
        }

        /// The band a lift of `recipe` and the focus ring can cover around `child`, in its
        /// parent's coordinates.
        internal static Rectangle Band(Control child, string recipe)
        {
            var item = child as ISoftLifted;
            Rectangle face = item != null ? item.Face : child.ClientRectangle;
            face.Offset(child.Left, child.Top);
            Padding reach = Elevation.Reach(recipe);
            int ring = Soft.Px(Brand.FocusOffset + Brand.FocusWidth) + 1;
            int left = Math.Max(reach.Left, ring), top = Math.Max(reach.Top, ring);
            int right = Math.Max(reach.Right, ring), bottom = Math.Max(reach.Bottom, ring);
            return new Rectangle(face.X - left, face.Y - top, face.Width + left + right, face.Height + top + bottom);
        }

        /// Repaints the band around `child` wherever its lift is drawn - after a press, a change
        /// of enabled state, a move - so no shadow is left behind where it no longer is.
        internal static void InvalidateLift(Control child)
        {
            if (child.Parent != null) Invalidate(child.Parent, Band(child, child is SoftCard ? "card" : "control"));
        }

        /// Repaints `band` (in `container`'s coordinates) on the container and on every
        /// container it is seen through.
        internal static void Invalidate(Control container, Rectangle band)
        {
            Control c = container;
            for (int depth = 0; c != null && depth < Depth; depth++)
            {
                if (c.IsHandleCreated && !c.IsDisposed) c.Invalidate(band, false);
                if (!SeeThrough(c)) break;
                band.Offset(c.Left, c.Top);
                c = c.Parent;
            }
        }

        /// Makes sure every container `lifted` is drawn on paints its lift, giving the ones that
        /// are not grounds a Paint handler that stamps it.
        internal static void Watch(Control lifted)
        {
            Control c = lifted.Parent;
            for (int depth = 0; c != null && depth < Depth; depth++)
            {
                if (!(c is ISoftGround) && c.BackColor.A == 255 && watched.Add(c))
                {
                    Control container = c;
                    container.Paint += PaintOver;
                    container.Disposed += delegate { watched.Remove(container); };
                }
                if (!SeeThrough(c)) break;
                c = c.Parent;
            }
        }

        private static void PaintOver(object sender, PaintEventArgs e)
        {
            Stamps((Control)sender, e.Graphics, e.ClipRectangle);
        }
    }

    /// Keeps the ground behind a lifted control in step with it: where its shadow was, and
    /// where it is now, are repainted when it moves, resizes, shows, hides or changes state.
    internal sealed class LiftTracker
    {
        private readonly Control owner;
        private readonly string recipe;
        private Control lastParent;
        private Rectangle lastBand;

        internal LiftTracker(Control owner, string recipe)
        {
            this.owner = owner;
            this.recipe = recipe;
            owner.LocationChanged += delegate { Update(); };
            owner.SizeChanged += delegate { Update(); };
            owner.VisibleChanged += delegate { Update(); };
            owner.ParentChanged += delegate { Update(); };
            owner.EnabledChanged += delegate { Update(); };
            owner.GotFocus += delegate { Update(); };
            owner.LostFocus += delegate { Update(); };
            owner.HandleCreated += delegate { Update(); };
        }

        internal void Update()
        {
            Control parent = owner.Parent;
            Rectangle band = parent == null ? Rectangle.Empty : Ground.Band(owner, recipe);
            if (lastParent != null && (lastParent != parent || band != lastBand)) Ground.Invalidate(lastParent, lastBand);
            lastParent = parent;
            lastBand = band;
            if (parent == null) return;
            Ground.Invalidate(parent, band);
            Ground.Watch(owner);
        }
    }

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
    ///   * a child placed where it is counts to its bottom.
    /// The wheel scrolls it over anything in it that does not take the wheel for itself (a drop-down
    /// or a number hands it on: Soft.PassWheel), and a control the keyboard moves to is scrolled into
    /// view, as Windows' own scrolling panel does.
    internal sealed class SoftPage : Panel, ISoftGround, ISoftScroller
    {
        // Whether the lift of what it holds may cross out of it follows whether it is scrolling
        // (Ground.SeeThrough), so when that changes the grounds around it are painted again.
        private bool scrolling;
        private bool scrolls, overflow;
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
            base.OnLayout(levent);
            if (scrolls) Settle(levent);
            bool now = Ground.Scrolling(this);
            if (now == scrolling) return;
            scrolling = now;
            Form form = FindForm();
            if (form != null && form.IsHandleCreated) form.Invalidate(true);
        }

        // Measures what it holds and lays it out again until that agrees with the offset and the bar:
        // the gutter narrows what fills the width, which can only make it taller, so it settles in two
        // passes at most once the bar has appeared or gone.
        private void Settle(LayoutEventArgs levent)
        {
            for (int pass = 0; pass < 4; pass++)
            {
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
                else if (child.Dock == DockStyle.Fill) stacked += Math.Max(0, child.MinimumSize.Height);
                else if (child.Dock == DockStyle.None) placed = Math.Max(placed, child.Bottom - display.Top);
            }
            return Padding.Vertical + Math.Max(stacked, placed);
        }

        /// Scrolls to `target` pixels down, as far as there is to scroll. With `animate` it glides
        /// there, unless motion is reduced or it is not on screen; otherwise it is there at once.
        internal void ScrollTo(int target, bool animate)
        {
            if (!scrolls) return;
            int range = overflow ? Math.Max(0, extent - ClientSize.Height) : 0;
            target = Math.Max(0, Math.Min(range, target));
            glideTarget = target;
            if (animate && !Soft.ReduceMotion && IsHandleCreated && Soft.Shown(this))
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
            // in it, the bar - is painted again.
            PerformLayout();
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

        // States: 0 resting, 1 under the pointer, 2 dragged.
        internal static Color TrackFill(bool contrast) { return contrast ? SystemColors.Window : Brand.Inset; }
        internal static Color TrackEdge(bool contrast) { return contrast ? SystemColors.WindowFrame : Brand.Line; }

        internal static Color ThumbFill(int state, bool contrast)
        {
            if (contrast) return state == 0 ? SystemColors.GrayText : SystemColors.Highlight;
            return Brand.Raised;
        }

        internal static Color ThumbEdge(int state, bool contrast)
        {
            if (contrast) return ThumbFill(state, true);
            return state == 2 ? Soft.Mix(Brand.Line, Brand.Muted, 0.6)
                 : state == 1 ? Soft.Mix(Brand.Line, Brand.Muted, 0.35) : Brand.Line;
        }

        internal static void Draw(Graphics g, Rectangle track, Rectangle thumb, int state)
        {
            if (track.Width <= 0 || track.Height <= 0) return;
            bool contrast = Palette.Contrast;
            float radius = track.Width / 2f;
            Soft.Body(g, track, radius, TrackFill(contrast), TrackEdge(contrast), !contrast);
            if (thumb.Width <= 0 || thumb.Height <= 0) return;
            float knob = thumb.Width / 2f;
            if (!contrast)
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
    internal sealed class SoftScrollBar
    {
        private readonly Control host;
        private readonly ISoftScroller scroller;
        private readonly Timer repeat = new Timer();
        private Rectangle track;
        private bool hover, dragging;
        private int grab, pointer, direction;

        internal SoftScrollBar(Control host, ISoftScroller scroller)
        {
            this.host = host;
            this.scroller = scroller;
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
                SoftBar.Thumb(track.Height - 2 * inset, scroller.Extent, scroller.Viewport, scroller.Offset,
                              Soft.Px(SoftBar.MinThumb), out start, out length);
                return new Rectangle(track.X + inset, track.Y + inset + start, Math.Max(0, track.Width - 2 * inset), length);
            }
        }

        /// 0 resting, 1 under the pointer, 2 dragged.
        internal int State { get { return dragging ? 2 : hover ? 1 : 0; } }

        internal void Paint(Graphics g)
        {
            if (!track.IsEmpty) SoftBar.Draw(g, track, Thumb, State);
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
            if (e.Y >= thumb.Top && e.Y < thumb.Bottom)
            {
                dragging = true;
                grab = e.Y - thumb.Top;
                Invalidate();
                return;
            }
            pointer = e.Y;
            direction = e.Y < thumb.Top ? -1 : 1;
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
                scroller.ScrollTo(SoftBar.OffsetAt(track.Height - 2 * inset, scroller.Extent, scroller.Viewport, thumb.Height,
                                                   e.Y - grab - track.Y - inset));
                Invalidate();
                return;
            }
            if (repeat.Enabled) pointer = e.Y;
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
            if (thumb.IsEmpty || (direction < 0 ? thumb.Top <= pointer : thumb.Bottom > pointer))
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
            BackColor = Palette.Surface;
            tracker = new LiftTracker(this, "card");
        }

        /// Zero. A card keeps no band inside itself for its shadow any more - the ground around
        /// it draws the shadow - so nothing needs to add one to its padding.
        internal static int Room { get { return 0; } }

        string ISoftLifted.Lift { get { return "card"; } }
        float ISoftLifted.Radius { get { return Soft.PxF(Brand.RadiusCard); } }
        Rectangle ISoftLifted.Face { get { return ClientRectangle; } }
        bool ISoftLifted.Ring { get { return false; } }

        internal LiftTracker Tracker { get { return tracker; } }

        protected override void OnPaintBackground(PaintEventArgs e)
        {
            float radius = Soft.PxF(Brand.RadiusCard);
            Ground.PaintBehind(this, e.Graphics, ClientRectangle, radius);
            Soft.Body(e.Graphics, ClientRectangle, radius, Palette.Surface, Palette.Line, false);
            Ground.Stamps(this, e.Graphics, e.ClipRectangle);
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

    /// A check box drawn as the panel's switch, with its words to the right. Still a CheckBox,
    /// so Space turns it and a screen reader says what it is and whether it is on.
    internal sealed class SoftCheck : CheckBox, ISoftLifted
    {
        private readonly LiftTracker tracker;

        internal SoftCheck()
        {
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint |
                     ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
            Cursor = Cursors.Hand;
            tracker = new LiftTracker(this, "control");
        }

        private static int Gap { get { return Soft.Px(9); } }

        private Rectangle Track
        {
            get
            {
                int height = Soft.Px(Brand.SwitchHeight);
                return new Rectangle(0, (Height - height) / 2, Soft.Px(Brand.SwitchWidth), height);
            }
        }

        // No lift - a switch is a well - but its focus ring runs outside the control on the left,
        // so the ground draws that part of it.
        string ISoftLifted.Lift { get { return null; } }
        float ISoftLifted.Radius { get { return Soft.Px(Brand.SwitchHeight) / 2f; } }
        Rectangle ISoftLifted.Face { get { return Track; } }
        bool ISoftLifted.Ring { get { return Focused && ShowFocusCues; } }

        public override Size GetPreferredSize(Size proposedSize)
        {
            Size text = TextRenderer.MeasureText(Text ?? "", Font, new Size(int.MaxValue, int.MaxValue),
                                                 TextFormatFlags.SingleLine);
            return new Size(Soft.Px(Brand.SwitchWidth) + Gap + text.Width + Soft.Px(6),
                            Math.Max(Soft.Px(Brand.SwitchHeight), text.Height) + Soft.Px(6));
        }

        protected override void OnCheckedChanged(EventArgs e) { Invalidate(); base.OnCheckedChanged(e); }
        protected override void OnEnabledChanged(EventArgs e) { Invalidate(); base.OnEnabledChanged(e); }
        protected override void OnGotFocus(EventArgs e) { Invalidate(); base.OnGotFocus(e); }
        protected override void OnLostFocus(EventArgs e) { Invalidate(); base.OnLostFocus(e); }
        protected override void OnTextChanged(EventArgs e) { Invalidate(); base.OnTextChanged(e); }

        protected override void OnPaint(PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            Ground.PaintArea(this, g, ClientRectangle);
            Rectangle track = Track;
            Soft.Switch(g, track, Checked, Enabled, Parent != null ? Ground.Colour(Parent) : Palette.Surface);
            var textBounds = new Rectangle(track.Right + Gap, 0, Math.Max(0, Width - track.Right - Gap), Height);
            TextRenderer.DrawText(g, Text, Font, textBounds, Enabled ? ForeColor : Palette.Muted,
                                  TextFormatFlags.VerticalCenter | TextFormatFlags.Left |
                                  TextFormatFlags.SingleLine | TextFormatFlags.EndEllipsis);
            if (Focused && ShowFocusCues) Soft.Ring(g, track, track.Height / 2f);
        }
    }

    /// A drop-down that is a well, as the panel's select is. Its closed face is drawn here
    /// entirely - the ground behind its corners, the inset well, the chosen item, the chevron -
    /// and it is always one field high. The list it opens is the native one, in the palette.
    internal sealed class SoftCombo : ComboBox
    {
        internal SoftCombo()
        {
            DrawMode = DrawMode.OwnerDrawFixed;
            DropDownStyle = ComboBoxStyle.DropDownList;
            FlatStyle = FlatStyle.Flat;
            BackColor = Palette.Raised;
            ForeColor = Palette.Ink;
            Fit();
        }

        /// The height every SoftCombo has: the panel's field height.
        internal static int FieldHeight
        {
            get { return Soft.Px(Brand.FieldHeight); }
        }

        // A native drop-down list is its item height plus a frame of its own - six device pixels
        // at every scale, measured - and ignores any height it is given once it has a window. So
        // the height is set through the item height: from that frame before there is a window,
        // so the first layout is already right, then from the real frame once there is one, and
        // again whenever the font changes - which is when it used to grow past its row.
        //
        // Before there is a window the item height is only recorded, with the drop-down drawn as
        // a plain one for that moment. Set on an owner-drawn drop-down, ComboBox makes the window
        // there and then (UpdateItemHeight): every one had a window and a list window from its
        // constructor, in Settings sections nobody had opened, and the height it has before a
        // window was never measured. The window takes the recorded height when it is made.
        private const int Frame = 6;

        private void Fit()
        {
            if (!IsHandleCreated)
            {
                int item = Math.Max(1, FieldHeight - Frame);
                if (ItemHeight != item)
                {
                    DrawMode = DrawMode.Normal;
                    ItemHeight = item;
                    DrawMode = DrawMode.OwnerDrawFixed;
                }
                Height = FieldHeight;
                return;
            }
            int wanted = Math.Max(1, FieldHeight - (Height - ItemHeight));
            if (ItemHeight != wanted) ItemHeight = wanted;
        }

        protected override void OnHandleCreated(EventArgs e) { base.OnHandleCreated(e); Fit(); }
        protected override void OnFontChanged(EventArgs e) { base.OnFontChanged(e); Fit(); Invalidate(); }

        /// The height it really has. The base class answers from the font alone - 33 for a
        /// 42-pixel owner-drawn combo at 150% - and a row measured from that cut the field's
        /// bottom edge off.
        public override Size GetPreferredSize(Size proposedSize)
        {
            return new Size(base.GetPreferredSize(proposedSize).Width, IsHandleCreated ? Height : FieldHeight);
        }

        // Without a window ComboBox holds a drop-down list to its font's height whatever height it
        // is given - 23 at 9 points, measured, in a constraint a subclass cannot change - so until
        // the window takes its height from the item height, the bounds are put back to a field's
        // height. Once there is a window they are left alone.
        protected override void SetBoundsCore(int x, int y, int width, int height, BoundsSpecified specified)
        {
            base.SetBoundsCore(x, y, width, height, specified);
            if (!IsHandleCreated && Height != FieldHeight) UpdateBounds(Left, Top, Width, FieldHeight);
        }

        protected override void OnSelectedIndexChanged(EventArgs e) { base.OnSelectedIndexChanged(e); Invalidate(); }
        protected override void OnEnabledChanged(EventArgs e) { base.OnEnabledChanged(e); Invalidate(); }
        protected override void OnGotFocus(EventArgs e) { base.OnGotFocus(e); Invalidate(); }
        protected override void OnLostFocus(EventArgs e) { base.OnLostFocus(e); Invalidate(); }
        protected override void OnDropDownClosed(EventArgs e) { base.OnDropDownClosed(e); Invalidate(); }
        protected override void OnResize(EventArgs e) { base.OnResize(e); Invalidate(); }

        protected override void WndProc(ref Message m)
        {
            if (IsHandleCreated && NativePaint.Handle(ref m, ClientSize, PaintFace)) return;
            base.WndProc(ref m);
        }

        private void PaintFace(Graphics g)
        {
            Rectangle face = ClientRectangle;
            float radius = Soft.PxF(Brand.RadiusControl);
            Ground.PaintBehind(this, g, face, radius);
            Soft.InsetWell(g, face, radius, Focused && ShowFocusCues);
            string text = SelectedIndex >= 0 ? GetItemText(SelectedItem) : "";
            int left = Soft.Px(Brand.SelectPadLeft), right = Soft.Px(Brand.SelectPadRight);
            TextRenderer.DrawText(g, text, Font, new Rectangle(left, 0, Math.Max(0, face.Width - left - right), face.Height),
                                  Enabled ? Palette.Ink : Palette.Muted,
                                  TextFormatFlags.VerticalCenter | TextFormatFlags.Left | TextFormatFlags.SingleLine |
                                  TextFormatFlags.EndEllipsis | TextFormatFlags.NoPrefix);
            // The chevron: a small wedge in the muted colour, where the panel's select has it.
            float wedge = Soft.PxF(Brand.ChevronWidth), tall = Soft.PxF(Brand.ChevronHeight);
            float right1 = face.Right - Soft.Hairline - Soft.PxF(Brand.ChevronRight), left1 = right1 - wedge;
            float top = face.Top + face.Height * 0.55f - tall / 2f;
            GraphicsState state = g.Save();
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.PixelOffsetMode = PixelOffsetMode.Half;
            using (var brush = new SolidBrush(Enabled ? Palette.Muted : Soft.Mix(Palette.Muted, Palette.Inset, 0.5)))
                g.FillPolygon(brush, new[] { new PointF(left1, top), new PointF(right1, top), new PointF((left1 + right1) / 2f, top + tall) });
            g.Restore(state);
        }

        protected override void OnDrawItem(DrawItemEventArgs e)
        {
            if (e.Index < 0) return;
            bool selected = (e.State & DrawItemState.Selected) != 0;
            bool face = (e.State & DrawItemState.ComboBoxEdit) != 0;
            // The closed face is PaintFace's. Windows draws it by itself as well when the choice
            // changes from the keyboard; that becomes a repaint, not a square over the well.
            if (face)
            {
                Invalidate();
                return;
            }
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

        internal int HeightFor(int width)
        {
            int textWidth = TextColumn(width).Width;
            Font title = TitleFont;
            int top = TextRenderer.MeasureText(Text ?? "", title, new Size(textWidth, int.MaxValue),
                                               TextFormatFlags.WordBreak).Height;
            int help = string.IsNullOrEmpty(Help) ? 0
                     : TextRenderer.MeasureText(Help, Font, new Size(textWidth, int.MaxValue),
                                                TextFormatFlags.WordBreak).Height + Soft.Px(2);
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
            Size top = TextRenderer.MeasureText(Text ?? "", title, new Size(textWidth, int.MaxValue), TextFormatFlags.WordBreak);
            TextRenderer.DrawText(g, Text, title, new Rectangle(left, (int)body.Y + Soft.Px(10), textWidth, top.Height),
                                  onHighlight ? SystemColors.HighlightText : Checked ? Palette.Accent : Palette.Ink,
                                  TextFormatFlags.WordBreak | TextFormatFlags.Left);
            if (!string.IsNullOrEmpty(Help))
                TextRenderer.DrawText(g, Help, Font,
                                      new Rectangle(left, (int)body.Y + Soft.Px(12) + top.Height, textWidth, Height),
                                      onHighlight ? SystemColors.HighlightText : Palette.Secondary,
                                      TextFormatFlags.WordBreak | TextFormatFlags.Left);
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
    internal sealed class SoftTextArea : Panel
    {
        internal readonly TextBox Box = new TextBox();

        internal SoftTextArea()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                     ControlStyles.UserPaint | ControlStyles.ResizeRedraw, true);
            BackColor = Palette.Inset;
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
            // The well's padding on the left, top and bottom; the scroll bar keeps to the edge.
            Padding = new Padding(Soft.Px(Brand.WellPadLeft), Soft.Px(Brand.WellPadTop), Soft.Px(6), Soft.Px(Brand.WellPadBottom));
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
            float radius = Soft.PxF(Brand.RadiusControl);
            Ground.PaintBehind(this, e.Graphics, ClientRectangle, radius);
            Soft.InsetWell(e.Graphics, ClientRectangle, radius, Box.Focused);
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
            int textHeight = TextRenderer.MeasureText(text.Length == 0 ? " " : text, Font,
                                                      new Size(width - Soft.Px(28), int.MaxValue),
                                                      TextFormatFlags.WordBreak | TextFormatFlags.TextBoxControl).Height;
            return new Size(width, textHeight + Soft.Px(24));
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            float radius = Soft.PxF(Brand.RadiusControl);
            Ground.PaintBehind(this, e.Graphics, ClientRectangle, radius);
            Soft.InsetWell(e.Graphics, ClientRectangle, radius, false);
            TextRenderer.DrawText(e.Graphics, text, Font,
                                  new Rectangle(Soft.Px(Brand.WellPadLeft), Soft.Px(Brand.WellPadTop),
                                                Math.Max(0, Width - Soft.Px(Brand.WellPadLeft + Brand.WellPadRight)), Height),
                                  Palette.Ink, TextFormatFlags.WordBreak | TextFormatFlags.TextBoxControl | TextFormatFlags.Left);
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
        private const int WM_VSCROLL = 0x0115;
        private const int WM_MOUSEWHEEL = 0x020A;

        internal SoftList()
        {
            SetStyle(ControlStyles.OptimizedDoubleBuffer | ControlStyles.AllPaintingInWmPaint, true);
        }

        /// After anything that can move or resize what the list shows - a scroll, a key, a resize, its
        /// scroll bar coming or going, and every paint, which follows all of those.
        internal event EventHandler ScrollChanged;

        protected override void WndProc(ref Message m)
        {
            base.WndProc(ref m);
            if (ScrollChanged != null && (m.Msg == WM_PAINT || m.Msg == WM_VSCROLL || m.Msg == WM_MOUSEWHEEL ||
                                          m.Msg == WM_KEYDOWN || m.Msg == WM_SIZE || m.Msg == WM_STYLECHANGED))
                ScrollChanged(this, EventArgs.Empty);
        }
    }

    /// The strip a SoftListHost shows its list through: exactly as wide as the list's rows, so the
    /// list's own scroll bar, beside them, is outside it.
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

        private const int SB_VERT = 1;
        private const int SIF_ALL = 0x17;
        private const int GWL_STYLE = -16;
        private const int WS_VSCROLL = 0x00200000;
        private const int WM_VSCROLL = 0x0115;
        private const int SB_PAGEUP = 2;
        private const int SB_PAGEDOWN = 3;
        private const int LVM_SCROLL = 0x1014;

        internal readonly ListView List;
        private readonly ListClip clip = new ListClip();
        private readonly SoftScrollBar bar;
        private ScrollInfo scroll;
        private bool native, queued;

        internal SoftListHost(ListView list)
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                     ControlStyles.UserPaint | ControlStyles.ResizeRedraw, true);
            List = list;
            // Before anything is added: adding lays the host out, and laying out places the bar.
            bar = new SoftScrollBar(this, this);
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

        /// Whether the list has more rows than show, so the soft bar is showing.
        internal bool Overflowing { get { return native; } }

        internal ListClip Clip { get { return clip; } }

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

        private void Read()
        {
            var info = new ScrollInfo();
            info.Size = Marshal.SizeOf(typeof(ScrollInfo));
            info.Mask = SIF_ALL;
            if (List.IsHandleCreated && GetScrollInfo(List.Handle, SB_VERT, ref info)) scroll = info;
            else scroll = new ScrollInfo();
        }

        protected override void OnLayout(LayoutEventArgs levent)
        {
            base.OnLayout(levent);
            native = NativeBar;
            int rows = Math.Max(0, Width - (native ? SoftBar.Gutter : 0));
            // The list's own bar is as wide as the list is wider than its rows; before it has one,
            // Windows' measure of a scroll bar.
            int beside = native ? Math.Max(0, List.Width - List.ClientSize.Width) : 0;
            if (native && beside == 0) beside = SystemInformation.VerticalScrollBarWidth;
            clip.SetBounds(0, 0, rows, Height);
            List.SetBounds(0, 0, rows + beside, Height);
            Read();
            bar.Track = native ? TrackBounds() : Rectangle.Empty;
        }

        // Beside the rows: from under the column headings to the bottom.
        private Rectangle TrackBounds()
        {
            int margin = Soft.Px(SoftBar.TrackMargin);
            int top = List.Items.Count > 0 && List.View == View.Details ? Math.Max(0, List.GetItemRect(List.TopItem != null ? List.TopItem.Index : 0).Top) : 0;
            return new Rectangle(Width - margin - Soft.Px(SoftBar.TrackWidth), top + margin, Soft.Px(SoftBar.TrackWidth),
                                 Math.Max(0, Height - top - 2 * margin));
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
            if (NativeBar != native)
            {
                PerformLayout();
                Invalidate();
                return;
            }
            ScrollInfo before = scroll;
            Read();
            Rectangle track = native ? TrackBounds() : Rectangle.Empty;
            if (before.Position != scroll.Position || before.Max != scroll.Max || before.Page != scroll.Page || track != bar.Track)
            {
                bar.Track = track;
                bar.Invalidate();
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
        }
    }

    /// The status light: a flat dot whose colour says what the watcher is doing, and a soft glow
    /// that says it is alive.
    ///
    /// The dot keeps the size it has always had. Every state in which the watcher runs with
    /// recovery on is the brand's cyan, the colour the dot had before v0.6.3; a stopped or
    /// unknown watcher and a pause keep their greys and have no glow; a watcher that runs but is
    /// not well is amber, and a failure red. The glow fades out from the dot's edge with no edge
    /// of its own. Monitoring breathes slowly, recovering a little faster; waiting holds still;
    /// checking also turns a small arc; a state that needs a person swells once when it is
    /// entered, then holds. brand.glow() defines every number, for the popup and the panel too.
    /// With motion reduced nothing moves; in High Contrast the dot is a system colour, unlit.
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

        /// How far the largest glow reaches from the dot's centre, in device pixels: the room a
        /// column holding the light keeps on each side of it.
        internal static int Extent
        {
            get { return (int)Math.Ceiling(Soft.PxF(Brand.GlowExtent)); }
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

        /// The glow's opacity for one frame, brand.glow()'s "opacity", or 0 when the state has
        /// no glow. Breathing follows `elapsedMs`; the one pulse follows `sinceEnteredMs`, and a
        /// negative value means it is over. Pure, so the rule can be checked without drawing.
        internal static double HaloOpacity(string state, double elapsedMs, double sinceEnteredMs, bool reduced)
        {
            double opacity, scale, arc;
            return Brand.Glow(state, elapsedMs, sinceEnteredMs, reduced, out opacity, out scale, out arc) ? opacity : 0;
        }

        /// How much the glow's outer radius is scaled for one frame, or 0 when there is no glow.
        internal static double HaloScale(string state, double elapsedMs, double sinceEnteredMs, bool reduced)
        {
            double opacity, scale, arc;
            return Brand.Glow(state, elapsedMs, sinceEnteredMs, reduced, out opacity, out scale, out arc) ? scale : 0;
        }

        /// Where the checking arc starts for one frame, in degrees, or -1 when there is none.
        internal static double HaloArc(string state, double elapsedMs, double sinceEnteredMs, bool reduced)
        {
            double opacity, scale, arc;
            return Brand.Glow(state, elapsedMs, sinceEnteredMs, reduced, out opacity, out scale, out arc) ? arc : -1;
        }

        internal static Color DotColour(string state)
        {
            return DotColour(state, Palette.Contrast);
        }

        /// The dot's fill: the brand's colour for the state, or in High Contrast its system
        /// colour. Comparisons, not a switch, inside Brand: the in-box compiler turns a string
        /// switch with enough cases into a dictionary held by a class it names with a fresh
        /// random GUID, and that one name made two builds of the same source differ.
        internal static Color DotColour(string state, bool contrast)
        {
            return contrast ? Brand.StatusSystem(state) : Brand.StatusFill(state);
        }

        private bool ShouldRun()
        {
            if (!Visible || !IsHandleCreated || Soft.ReduceMotion) return false;
            Form form = FindForm();
            if (form != null && form.WindowState == FormWindowState.Minimized) return false;
            return Brand.GlowMoves(state, clock.Elapsed.TotalMilliseconds - enteredAt, false);
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
            g.Clear(Parent != null ? Ground.Colour(Parent) : Palette.Surface);
            double since = clock.Elapsed.TotalMilliseconds - enteredAt;
            double opacity, scale, arc;
            bool lit = Brand.Glow(state, since, since, Soft.ReduceMotion, out opacity, out scale, out arc);
            Color colour = DotColour(state);
            float cx = Width / 2f, cy = Height / 2f, dot = Soft.PxF(Brand.StatusDotRadius);
            GraphicsState saved = g.Save();
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.PixelOffsetMode = PixelOffsetMode.Half;
            if (lit && opacity > 0 && !Palette.Contrast)
                Glow(g, cx, cy, (float)(Soft.PxF(Brand.StatusDotRadius + Brand.GlowReach) * scale), colour, opacity);
            using (var brush = new SolidBrush(colour)) g.FillEllipse(brush, cx - dot, cy - dot, dot * 2, dot * 2);
            if (lit && arc >= 0)
            {
                float radius = Soft.PxF(Brand.StatusDotRadius + Brand.GlowArcGap);
                using (var pen = new Pen(Palette.Contrast ? colour : Soft.WithAlpha(colour, Brand.GlowArcAlpha), Soft.PxF(Brand.GlowArcWidth)))
                {
                    pen.StartCap = LineCap.Round;
                    pen.EndCap = LineCap.Round;
                    g.DrawArc(pen, cx - radius, cy - radius, radius * 2, radius * 2, (float)arc, (float)Brand.GlowArcSweep);
                }
            }
            g.Restore(saved);
        }

        /// The glow: the dot's colour at `opacity` from the centre out to the dot's edge, then
        /// fading through brand.GLOW's stops to nothing at `outer`. A path gradient counts its
        /// positions from the edge inward, so the stops are written in reverse.
        private static void Glow(Graphics g, float cx, float cy, float outer, Color colour, double opacity)
        {
            if (outer <= 0) return;
            double dot = Brand.StatusDotRadius, whole = Brand.StatusDotRadius + Brand.GlowReach;
            using (var path = new GraphicsPath())
            {
                path.AddEllipse(cx - outer, cy - outer, outer * 2, outer * 2);
                using (var brush = new PathGradientBrush(path))
                {
                    brush.CenterPoint = new PointF(cx, cy);
                    brush.CenterColor = Soft.WithAlpha(colour, opacity);
                    brush.SurroundColors = new[] { Soft.WithAlpha(colour, 0) };
                    var blend = new ColorBlend(5);
                    blend.Positions[0] = 0f;
                    blend.Colors[0] = Soft.WithAlpha(colour, 0);
                    blend.Positions[1] = (float)(1 - (dot + Brand.GlowReach * Brand.GlowFarAt) / whole);
                    blend.Colors[1] = Soft.WithAlpha(colour, opacity * Brand.GlowFarAlpha);
                    blend.Positions[2] = (float)(1 - (dot + Brand.GlowReach * Brand.GlowNearAt) / whole);
                    blend.Colors[2] = Soft.WithAlpha(colour, opacity * Brand.GlowNearAlpha);
                    blend.Positions[3] = (float)(1 - dot / whole);
                    blend.Colors[3] = Soft.WithAlpha(colour, opacity);
                    blend.Positions[4] = 1f;
                    blend.Colors[4] = Soft.WithAlpha(colour, opacity);
                    brush.InterpolationColors = blend;
                    g.FillPath(brush, path);
                }
            }
        }
    }
}
