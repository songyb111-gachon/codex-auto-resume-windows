// Codex Auto Resume - depth: the shadows, what stands on what, and what is sunk into it.
//
// The same two soft shadows the panel in Codex is drawn with, and the rule that nothing
// depends on seeing one: every card and control keeps a hairline edge, and in High Contrast
// the shadows and tints are gone and system colours are used throughout.

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
    /// The recipes are the theme's (brand.SHADOWS): light's is a shadow and a highlight each, and
    /// dark's another shape - two drops and an inset one-pixel top light for a card, one drop for a
    /// control, one inset shadow for a well. So every shadow is read as Brand gives it, inset or not,
    /// and never inferred from the recipe's name. An outer shadow is stamped by the ground behind a
    /// body (StampOuter); an inset one by the body itself, between its fill and its hairline
    /// (StampInner, through Soft.Body).
    ///
    /// Nothing is drawn in High Contrast mode, nor in a design without depth (v0.6.10: Classic, Plain), where a
    /// surface is its fill and its hairline (Palette.Depth). How far a recipe reaches is its theme's in every design
    /// all the same: a ground keeps the room, so a design changes paint and never where anything is.
    internal static class Elevation
    {
        private sealed class Template
        {
            internal Bitmap Image;
            internal int MiddleX = -1, MiddleY = -1;   // the column and row that stretch; -1 draws it whole
            internal long Used;                        // when it was last stamped, for the eviction below
        }

        // Stamped with nearest-neighbour sampling on half-pixel centres, so a one-pixel strip
        // stretches to exactly its own pixels and nothing bleeds in from beside it - which also
        // keeps GDI+ off the slow path that image attributes force on every draw.
        private static readonly Dictionary<long, Template> cache = new Dictionary<long, Template>();

        private static int RecipeId(string recipe)
        {
            if (recipe == "card") return 0;
            if (recipe == "control") return 1;
            if (recipe == "inset") return 2;
            return -1;
        }

        /// How many shadows `recipe` has in the theme in effect.
        internal static int Count(string recipe)
        {
            return Tokens.Dark ? Brand.Dark.ElevationCount(recipe) : Brand.ElevationCount(recipe);
        }

        /// Shadow `index` of `recipe` in the theme in effect, front to back as brand.SHADOWS lists it.
        private static bool Shadow(string recipe, int index, out double dx, out double dy, out double blur,
                                   out double alpha, out bool inset, out Color tone)
        {
            bool found = Tokens.Dark ? Brand.Dark.ElevationShadow(recipe, index, out dx, out dy, out blur, out alpha, out inset, out tone)
                                     : Brand.ElevationShadow(recipe, index, out dx, out dy, out blur, out alpha, out inset, out tone);
            alpha = Math.Round(alpha, 4);
            return found;
        }

        /// How far a recipe's outer shadows reach past its box, per side, in device pixels at the
        /// window's scale: offset plus three sigmas, past which a shadow is under a fifth of a
        /// percent of its strength (brand.reach). A ground that clips its children closer than
        /// this cuts their shadow off. Inset shadows reach nothing outside.
        internal static Padding Reach(string recipe)
        {
            return Reach(recipe, SettingsForm.DpiScale);
        }

        internal static Padding Reach(string recipe, double scale)
        {
            int left = 0, top = 0, right = 0, bottom = 0;
            for (int index = 0; index < Count(recipe); index++)
            {
                double dx, dy, blur, alpha;
                bool inset;
                Color tone;
                if (!Shadow(recipe, index, out dx, out dy, out blur, out alpha, out inset, out tone) || inset) continue;
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
        /// of `g`), drawing only the pieces that meet `clip`. Its inset shadows are the body's own.
        internal static void StampOuter(Graphics g, Rectangle body, string recipe, float radius, Rectangle clip)
        {
            if (!Palette.Depth || body.Width <= 0 || body.Height <= 0) return;
            int count = Count(recipe);
            if (count == 0) return;
            Padding reach = Reach(recipe);
            var band = new Rectangle(body.X - reach.Left, body.Y - reach.Top, body.Width + reach.Horizontal, body.Height + reach.Vertical);
            if (!band.IntersectsWith(clip)) return;
            // Last to first, as CSS paints a shadow list.
            for (int index = count - 1; index >= 0; index--)
                if (!IsInset(recipe, index)) StampOne(g, recipe, index, SettingsForm.DpiScale, body, radius, clip);
        }

        /// A well's inset shadow inside `box` - the well inside its hairline - whose corners have
        /// `radius`. It is already clipped to that shape.
        internal static void StampInset(Graphics g, Rectangle box, float radius, Rectangle clip)
        {
            StampInner(g, box, "inset", radius, clip);
        }

        /// The inset shadows of `recipe` inside `box`, the body inside its hairline.
        internal static void StampInner(Graphics g, Rectangle box, string recipe, float radius, Rectangle clip)
        {
            if (!Palette.Depth || box.Width <= 0 || box.Height <= 0 || !box.IntersectsWith(clip)) return;
            for (int index = Count(recipe) - 1; index >= 0; index--)
                if (IsInset(recipe, index)) StampOne(g, recipe, index, SettingsForm.DpiScale, box, radius, clip);
        }

        private static bool IsInset(string recipe, int index)
        {
            double dx, dy, blur, alpha;
            bool inset;
            Color tone;
            return Shadow(recipe, index, out dx, out dy, out blur, out alpha, out inset, out tone) && inset;
        }

        /// Drops every cached bitmap; the next stamp builds what it needs again.
        internal static void Forget()
        {
            foreach (Template template in cache.Values) template.Image.Dispose();
            cache.Clear();
        }

        // How many templates have been stamped, so the oldest can be told from the newest.
        private static long stamped;

        /// Drops the half of the cache that has gone unused the longest, and disposes those bitmaps.
        private static void ForgetOldest()
        {
            var keys = new List<long>(cache.Keys);
            keys.Sort(delegate(long left, long right) { return cache[left].Used.CompareTo(cache[right].Used); });
            for (int i = 0; i < keys.Count / 2; i++)
            {
                Template template = cache[keys[i]];
                template.Image.Dispose();
                cache.Remove(keys[i]);
            }
        }

        internal static int Cached
        {
            get { return cache.Count; }
        }

        private static void StampOne(Graphics g, string recipe, int index, double scale, Rectangle body, float radius, Rectangle clip)
        {
            double dx, dy, blur, alpha;
            bool inset;
            Color tone;
            if (!Shadow(recipe, index, out dx, out dy, out blur, out alpha, out inset, out tone)) return;
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
            Template template = Get(recipe, index, scale, width, height, radius, fx, fy,
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

        private static Template Get(string recipe, int index, double scale, int width, int height, double radius,
                                    double fx, double fy, int middleX, int middleY)
        {
            // The theme, the recipe and the shadow, then the shape: a theme's bitmaps are never another's.
            long key = (Tokens.Dark ? 1 : 0) * 16 + Math.Max(0, RecipeId(recipe)) * 4 + Math.Min(3, index);
            key = key * 1024 + Math.Min(1023, (int)Math.Round(scale * 100));
            key = key * 4096 + Math.Min(4095, width);
            key = key * 4096 + Math.Min(4095, height);
            key = key * 16 + (int)Math.Round(fx * 8);
            key = key * 16 + (int)Math.Round(fy * 8);
            key = key * 16384 + Math.Min(16383, (int)Math.Round(radius * 8));
            Template template;
            if (cache.TryGetValue(key, out template))
            {
                template.Used = ++stamped;
                return template;
            }
            // Past the ceiling the oldest half goes, not all of it. Dropping every template meant a page
            // whose mix of control sizes crossed 128 re-blurred its shadows again and again - the blur is
            // the one expensive thing here, and the shapes a page uses are asked for over and over.
            if (cache.Count >= 128) ForgetOldest();
            double dx, dy, blur, alpha;
            bool inset;
            Color tone;
            Shadow(recipe, index, out dx, out dy, out blur, out alpha, out inset, out tone);
            template = inset ? Inner(dx, dy, blur, alpha, tone, scale, width, height, radius)
                             : Outer(blur, alpha, tone, scale, width, height, radius, fx, fy);
            template.MiddleX = middleX;
            template.MiddleY = middleY;
            template.Used = ++stamped;
            cache[key] = template;
            return template;
        }

        private static Template Outer(double blur, double alpha, Color tone, double scale, int width, int height,
                                      double radius, double fx, double fy)
        {
            double sigma = blur * scale / 2;
            int pad = Spread(sigma) + 1;
            int across = width + 2 * pad, down = height + 2 * pad;
            var shape = new double[across * down];
            Cover(shape, across, down, pad + fx, pad + fy, width, height, radius);
            return Make(Blur(shape, across, down, sigma), across, down, alpha, tone);
        }

        /// An inset shadow is cast by everything outside the box, moved by the offset, blurred,
        /// and seen only inside the box. With no blur - dark's one-pixel top light - it is that edge,
        /// moved, and nothing else.
        private static Template Inner(double dx, double dy, double blur, double alpha, Color tone, double scale,
                                      int width, int height, double radius)
        {
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
            return Make(inside, width, height, alpha, tone);
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

        /// The shadows of `recipe` as they are stamped at `scale` in the theme in effect, sampled
        /// across the middle of each straight edge: for each of its shadows, in brand.SHADOWS'
        /// order, and each side (left, top, right, bottom), the alpha 0.5, 1.5, 2.5 ... device pixels
        /// from the edge - outward from the body for an outer shadow, inward from inside the hairline
        /// for an inset one. Draws into a bitmap and nowhere else; the tests hold it to
        /// brand.shadow_alpha.
        internal static float[] Profile(string recipe, double scale)
        {
            int count = Count(recipe);
            if (count == 0) return new float[0];
            bool outer = false;
            int samples = 0;
            for (int index = 0; index < count; index++)
            {
                double dx, dy, blur, alpha;
                bool inset;
                Color tone;
                Shadow(recipe, index, out dx, out dy, out blur, out alpha, out inset, out tone);
                if (!inset) outer = true;
                samples = Math.Max(samples, Spread(blur * scale / 2) + (int)Math.Ceiling(Math.Max(Math.Abs(dx), Math.Abs(dy)) * scale) + 2);
            }
            float radius = (float)((recipe == "card" ? Brand.RadiusCard : Brand.RadiusControl) * scale);
            int length = 4 * (samples + (int)Math.Ceiling(radius)) + 40;
            int margin = outer ? samples + 4 : 0;
            var result = new float[count * 4 * samples];
            using (var bitmap = new Bitmap(length + 2 * margin, length + 2 * margin, PixelFormat.Format32bppArgb))
            {
                var body = new Rectangle(margin, margin, length, length);
                var all = new Rectangle(0, 0, bitmap.Width, bitmap.Height);
                int middle = margin + length / 2;
                for (int shadow = 0; shadow < count; shadow++)
                {
                    using (Graphics g = Graphics.FromImage(bitmap))
                    {
                        g.Clear(Color.Transparent);
                        StampOne(g, recipe, shadow, scale, body, radius, all);
                    }
                    bool inside = IsInset(recipe, shadow);
                    for (int i = 0; i < samples; i++)
                    {
                        int near = inside ? margin + i : margin - 1 - i;
                        int far = inside ? margin + length - 1 - i : margin + length + i;
                        result[(shadow * 4) * samples + i] = bitmap.GetPixel(near, middle).A / 255f;
                        result[(shadow * 4 + 1) * samples + i] = bitmap.GetPixel(middle, near).A / 255f;
                        result[(shadow * 4 + 2) * samples + i] = bitmap.GetPixel(far, middle).A / 255f;
                        result[(shadow * 4 + 3) * samples + i] = bitmap.GetPixel(middle, far).A / 255f;
                    }
                }
            }
            return result;
        }

        /// A `width` by `height` body of `recipe` as a page shows it in the theme in effect, with
        /// `margin` device pixels of ground around it: a card on the canvas, a control on a card, a
        /// well on a card. The pixels as ARGB, row by row, for the tests that compare them with
        /// brand.elevation_colour.
        internal static int[] Render(string recipe, double scale, int width, int height, int margin)
        {
            int id = RecipeId(recipe);
            if (id < 0) return new int[0];
            Color fill = id == 0 ? Tokens.Card : id == 2 ? Tokens.Inset : Tokens.Raised;
            float radius = (float)((id == 0 ? Brand.RadiusCard : Brand.RadiusControl) * scale);
            int hairline = Math.Max(1, (int)Math.Floor(scale + 1e-6));
            int across = width + 2 * margin, down = height + 2 * margin;
            var pixels = new int[across * down];
            using (var bitmap = new Bitmap(across, down, PixelFormat.Format32bppArgb))
            {
                using (Graphics g = Graphics.FromImage(bitmap))
                {
                    g.Clear(id == 0 ? Tokens.Canvas : Tokens.Card);
                    var body = new Rectangle(margin, margin, width, height);
                    var all = new Rectangle(0, 0, across, down);
                    int count = Count(recipe);
                    for (int index = count - 1; index >= 0; index--)
                        if (!IsInset(recipe, index)) StampOne(g, recipe, index, scale, body, radius, all);
                    g.SmoothingMode = SmoothingMode.AntiAlias;
                    g.PixelOffsetMode = PixelOffsetMode.Half;
                    using (var path = Soft.Rounded(body, radius))
                    using (var brush = new SolidBrush(fill))
                        g.FillPath(brush, path);
                    Rectangle box = Rectangle.Inflate(body, -hairline, -hairline);
                    for (int index = count - 1; index >= 0; index--)
                        if (IsInset(recipe, index)) StampOne(g, recipe, index, scale, box, radius - hairline, all);
                    Soft.Edge(g, body, radius, Tokens.Line, hairline);
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
            e.Graphics.FillRectangle(Soft.Fill(Colour(ground)), e.ClipRectangle);
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
        /// container it is seen through - and, in a block whose control lies over its content
        /// (SoftPin), on the content's windows under the band, which draw that part of the lift
        /// and the ring in their own backgrounds. Anywhere else a lifted control has no window
        /// under its band but its own, so a container's is enough.
        internal static void Invalidate(Control container, Rectangle band)
        {
            Control c = container;
            for (int depth = 0; c != null && depth < Depth; depth++)
            {
                if (c.IsHandleCreated && !c.IsDisposed)
                {
                    c.Invalidate(band, false);
                    var block = c as SoftPin;
                    if (block != null) block.InvalidateUnder(band);
                }
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
}
