// Codex Auto Resume - the soft depth: how far a shadow reaches, and how much of each pixel it covers (v0.6.27, S6.3).
//
// The C# port of src/codex_auto_resume/ui/popup/elevation.py, call for call: recipe_shadows (with brand.shadows'
// recipes, read from gui/Brand.cs), tile_ground, the masks (lift_coverage, well_coverage and v0.6.5's circular
// _lift_round and _well_round), their one shared memory with its 64-mask limit and its turned-round reuse - kept as it
// is, because a well reused turned round is not always the byte image a fresh one would be - and shadow_step. Every
// distance is CPython's hypot and every blur the C runtime's erfc, as the Python's math is.
using System;
using System.Collections.Generic;
using System.Drawing;

namespace CodexAutoResume
{
    /// One shadow of a recipe (brand.elevation Shadow): offset, blur, token, alpha, and whether it falls inside.
    internal struct SurfaceShadow
    {
        internal double Dx, Dy, Blur, Alpha;
        internal string Token;
        internal bool Inset;
    }

    /// A shadow's coverage: its bytes, a row of Width after another, the middle pixel, and how far the blur reaches.
    internal sealed class ShadowMask
    {
        internal string Key;
        internal int Width, Height, Extent;
        internal int[] Centre;
        internal byte[] Coverage;

        internal ShadowMask With(string key, byte[] coverage)
        {
            return new ShadowMask { Key = key, Width = Width, Height = Height, Extent = Extent, Centre = Centre, Coverage = coverage };
        }
    }

    internal static class SurfaceElevation
    {
        [System.Runtime.InteropServices.DllImport("ucrtbase.dll", EntryPoint = "erfc", CallingConvention = System.Runtime.InteropServices.CallingConvention.Cdecl)]
        private static extern double CrtErfc(double x);

        /// math.erfc.
        internal static double Erfc(double x) { return CrtErfc(x); }

        /// brand.shadows(recipe, theme, design): front to back, as CSS lists them; none in a design without depth.
        internal static List<SurfaceShadow> Shadows(string recipe, string theme, string design = "soft")
        {
            var found = new List<SurfaceShadow>();
            if (!Brand.DesignDepth(SurfaceTheme.DesignChoice(design))) return found;
            bool dark = theme == "dark";
            for (int index = 0; ; index++)
            {
                double dx, dy, blur, alpha;
                bool inset;
                Color tone;
                bool there = dark ? Brand.Dark.ElevationShadow(recipe, index, out dx, out dy, out blur, out alpha, out inset, out tone)
                                  : Brand.ElevationShadow(recipe, index, out dx, out dy, out blur, out alpha, out inset, out tone);
                if (!there) break;
                string token = tone.ToArgb() == (dark ? Brand.Dark.ShadowLight : Brand.ShadowLight).ToArgb() ? "shadow_light" : "shadow_dark";
                found.Add(new SurfaceShadow { Dx = dx, Dy = dy, Blur = blur, Alpha = alpha, Token = token, Inset = inset });
            }
            return found;
        }

        /// A recipe's shadows in `theme` (recipe_shadows): the tile's own (DEPTH) or brand's; none without depth.
        internal static List<SurfaceShadow> RecipeShadows(string recipe, string theme, string design = "soft")
        {
            theme = theme == "dark" ? "dark" : "light";
            if (!Brand.DesignDepth(SurfaceTheme.DesignChoice(design))) return new List<SurfaceShadow>();
            if (recipe == "tile")
            {
                List<SurfaceShadow> tile = Shadows("control", theme);
                if (theme == "dark")
                    foreach (SurfaceShadow shadow in Shadows("card", "dark")) if (shadow.Inset) tile.Add(shadow);
                return tile;
            }
            return Shadows(recipe, theme);
        }

        /// A task tile's ground: the palette's raised (tile_ground).
        internal static Color TileGround(string theme, string design)
        {
            return SurfaceTheme.Token("raised", theme, design);
        }

        private const int MaskLimit = 64;
        private static readonly Dictionary<string, ShadowMask> Masks = new Dictionary<string, ShadowMask>();

        private static string K(double value)
        {
            return CardPlan.RoundTo(value, 3).ToString("R", System.Globalization.CultureInfo.InvariantCulture);
        }

        private static ShadowMask Remember(string key, ShadowMask mask)
        {
            if (Masks.Count >= MaskLimit) Masks.Clear();
            Masks[key] = mask;
            return mask;
        }

        private static double RoundedDistance(double x, double y, double halfWidth, double halfHeight, double radius)
        {
            double qx = Math.Abs(x) - (halfWidth - radius);
            double qy = Math.Abs(y) - (halfHeight - radius);
            if (qx > 0 && qy > 0) return IconMark.Hypot(qx, qy) - radius;
            return Math.Max(qx, qy) - radius;
        }

        private static double Blurred(double distance, double sigma)
        {
            if (sigma <= 0) return Math.Max(0.0, Math.Min(1.0, 0.5 - distance));
            return 0.5 * Erfc(distance / (sigma * SurfaceMath.Sqrt(2.0)));
        }

        private static Func<double, int> LevelOf(double sigma)
        {
            if (sigma <= 0) return distance => (int)(Math.Max(0.0, Math.Min(1.0, 0.5 - distance)) * 255 + 0.5);
            double factor = 1.0 / (sigma * SurfaceMath.Sqrt(2.0));
            return distance => (int)(127.5 * Erfc(distance * factor) + 0.5);
        }

        private static ShadowMask LiftRound(int width, int height, double radius, double blur)
        {
            int core = 2 * (int)Math.Ceiling(radius) + 1;
            int boxW = Math.Min(width, core), boxH = Math.Min(height, core);
            radius = Math.Max(0.0, Math.Min(radius, Math.Min(boxW / 2.0, boxH / 2.0)));
            string key = "lift|" + boxW + "|" + boxH + "|" + K(radius) + "|" + K(blur);
            ShadowMask known;
            if (Masks.TryGetValue(key, out known)) return known;
            double sigma = blur / 2.0;
            int extent = (int)Math.Ceiling(3 * sigma) + 1;
            int imageW = boxW + 2 * extent, imageH = boxH + 2 * extent;
            var coverage = new byte[imageW * imageH];
            for (int j = 0; j < (imageH + 1) / 2; j++)
            {
                double y = j + 0.5 - imageH / 2.0;
                for (int i = 0; i < (imageW + 1) / 2; i++)
                {
                    double distance = RoundedDistance(i + 0.5 - imageW / 2.0, y, boxW / 2.0, boxH / 2.0, radius);
                    byte value = (byte)(int)(Blurred(distance, sigma) * 255 + 0.5);
                    Put(coverage, imageW, imageH, i, j, value);
                }
            }
            return Remember(key, new ShadowMask { Key = key, Width = imageW, Height = imageH, Centre = new[] { imageW / 2, imageH / 2 },
                                                  Extent = extent, Coverage = coverage });
        }

        /// The four mirrored places of a quarter's pixel, as the Python's row[i] = row[w-1-i] and rows[j] = rows[h-1-j].
        private static void Put(byte[] coverage, int width, int height, int i, int j, byte value)
        {
            coverage[j * width + i] = value;
            coverage[j * width + width - 1 - i] = value;
            coverage[(height - 1 - j) * width + i] = value;
            coverage[(height - 1 - j) * width + width - 1 - i] = value;
        }

        private static byte[] Reversed(byte[] bytes)
        {
            var turned = (byte[])bytes.Clone();
            Array.Reverse(turned);
            return turned;
        }

        private static ShadowMask WellRound(int width, int height, double radius, double blur, double dx, double dy)
        {
            double sigma = blur / 2.0;
            int reach = (int)Math.Ceiling(radius) + (int)Math.Ceiling(3 * sigma);
            int boxW = Math.Min(width, 2 * (reach + (int)Math.Ceiling(Math.Abs(dx))) + 1);
            int boxH = Math.Min(height, 2 * (reach + (int)Math.Ceiling(Math.Abs(dy))) + 1);
            radius = Math.Max(0.0, Math.Min(radius, Math.Min(boxW / 2.0, boxH / 2.0)));
            string head = "well|" + boxW + "|" + boxH + "|" + K(radius) + "|" + K(blur);
            string key = head + "|" + K(dx) + "|" + K(dy);
            ShadowMask known;
            if (Masks.TryGetValue(key, out known)) return known;
            ShadowMask turned;
            if (Masks.TryGetValue(head + "|" + K(-dx) + "|" + K(-dy), out turned)) return Remember(key, turned.With(key, Reversed(turned.Coverage)));
            double halfW = boxW / 2.0, halfH = boxH / 2.0;
            var data = new byte[boxW * boxH];
            for (int j = 0; j < boxH; j++)
            {
                double y = j + 0.5 - halfH;
                for (int i = 0; i < boxW; i++)
                {
                    double x = i + 0.5 - halfW;
                    double inside = Math.Max(0.0, Math.Min(1.0, 0.5 - RoundedDistance(x, y, halfW, halfH, radius)));
                    if (inside > 0)
                    {
                        double hole = Blurred(RoundedDistance(x - dx, y - dy, halfW, halfH, radius), sigma);
                        data[j * boxW + i] = (byte)(int)((1.0 - hole) * inside * 255 + 0.5);
                    }
                }
            }
            return Remember(key, new ShadowMask { Key = key, Width = boxW, Height = boxH, Centre = new[] { boxW / 2, boxH / 2 },
                                                  Extent = 0, Coverage = data });
        }

        /// An outer shadow's shape: a rounded rectangle blurred by `blur`, in device pixels (lift_coverage).
        internal static ShadowMask LiftCoverage(int width, int height, double radius, double blur, double? smoothing = null)
        {
            ShapeCorner found = SurfaceShape.Corner(radius, smoothing ?? SurfaceShape.CornerSmoothing, Math.Min(width, height) / 2.0);
            if (!SurfaceShape.Smoothed(found)) return LiftRound(width, height, radius, blur);
            int core = 2 * (int)Math.Ceiling(found.P) + 1;
            int boxW = Math.Min(width, core), boxH = Math.Min(height, core);
            radius = found.Radius;
            double smooth = found.Smoothing;
            string key = "lift|" + boxW + "|" + boxH + "|" + K(radius) + "|" + K(blur) + "|" + K(smooth);
            ShadowMask known;
            if (Masks.TryGetValue(key, out known)) return known;
            double sigma = blur / 2.0;
            int extent = (int)Math.Ceiling(3 * sigma) + 1;
            int imageW = boxW + 2 * extent, imageH = boxH + 2 * extent;
            ShapeProfile made = SurfaceShape.Profile(radius, smooth, Math.Min(boxW, boxH) / 2.0);
            double p = made.P;
            double[] rho = made.Rho, lean = made.Lean;
            int steps = SurfaceShape.RhoSteps;
            Func<double, int> level = LevelOf(sigma);
            double factor = sigma > 0 ? 1.0 / (sigma * SurfaceMath.Sqrt(2.0)) : 0.0;
            int across = (imageW + 1) / 2, down = (imageH + 1) / 2;
            var qxs = new double[across];
            var qys = new double[down];
            for (int i = 0; i < across; i++) qxs[i] = Math.Abs(i + 0.5 - imageW / 2.0) - (boxW / 2.0 - p);
            for (int j = 0; j < down; j++) qys[j] = Math.Abs(j + 0.5 - imageH / 2.0) - (boxH / 2.0 - p);
            var columns = new int[across];
            var lines = new int[down];
            for (int i = 0; i < across; i++) columns[i] = level(qxs[i] - p);
            for (int j = 0; j < down; j++) lines[j] = level(qys[j] - p);
            bool square = imageW == imageH;
            var coverage = new byte[imageW * imageH];
            var madeRows = new List<int[]>();
            for (int j = 0; j < down; j++)
            {
                double qy = qys[j];
                int line = lines[j];
                var row = new int[across];
                for (int i = 0; i < across; i++)
                {
                    int value;
                    if (square && i < j) value = madeRows[i][j];
                    else
                    {
                        double qx = qxs[i];
                        if (qx > 0.0 && qy > 0.0)
                        {
                            int k = (int)(qy / (qx + qy) * steps + 0.5);
                            double distance = (IconMark.Hypot(qx, qy) - rho[k]) * lean[k];
                            value = factor != 0 ? (int)(127.5 * Erfc(distance * factor) + 0.5) : level(distance);
                        }
                        else value = columns[i] < line ? columns[i] : line;
                    }
                    row[i] = value;
                    Put(coverage, imageW, imageH, i, j, (byte)value);
                }
                madeRows.Add(row);
            }
            return Remember(key, new ShadowMask { Key = key, Width = imageW, Height = imageH, Centre = new[] { imageW / 2, imageH / 2 },
                                                  Extent = extent, Coverage = coverage });
        }

        /// An inset shadow inside a box: how much of it shows at each pixel (well_coverage).
        internal static ShadowMask WellCoverage(int width, int height, double radius, double blur, double dx, double dy, double? smoothing = null)
        {
            ShapeCorner found = SurfaceShape.Corner(radius, smoothing ?? SurfaceShape.CornerSmoothing, Math.Min(width, height) / 2.0);
            if (!SurfaceShape.Smoothed(found)) return WellRound(width, height, radius, blur, dx, dy);
            double sigma = blur / 2.0;
            int reach = (int)Math.Ceiling(found.P) + (int)Math.Ceiling(3 * sigma);
            int boxW = Math.Min(width, 2 * (reach + (int)Math.Ceiling(Math.Abs(dx))) + 1);
            int boxH = Math.Min(height, 2 * (reach + (int)Math.Ceiling(Math.Abs(dy))) + 1);
            radius = found.Radius;
            double smooth = found.Smoothing;
            string head = "well|" + boxW + "|" + boxH + "|" + K(radius) + "|" + K(blur) + "|" + K(smooth);
            string key = head + "|" + K(dx) + "|" + K(dy);
            ShadowMask known;
            if (Masks.TryGetValue(key, out known)) return known;
            ShadowMask turned;
            if (Masks.TryGetValue(head + "|" + K(-dx) + "|" + K(-dy), out turned)) return Remember(key, turned.With(key, Reversed(turned.Coverage)));
            double halfW = boxW / 2.0, halfH = boxH / 2.0;
            ShapeProfile made = SurfaceShape.Profile(radius, smooth, Math.Min(halfW, halfH));
            double p = made.P;
            double[] rho = made.Rho, lean = made.Lean;
            int steps = SurfaceShape.RhoSteps;
            Func<double, int> level = LevelOf(sigma);
            double factor = sigma > 0 ? 1.0 / (sigma * SurfaceMath.Sqrt(2.0)) : 0.0;
            var cutX = new double[boxW];
            var holeX = new double[boxW];
            var holeColumns = new int[boxW];
            for (int i = 0; i < boxW; i++)
            {
                double x = i + 0.5 - halfW;
                cutX[i] = Math.Abs(x) - (halfW - p);
                holeX[i] = Math.Abs(x - dx) - (halfW - p);
                holeColumns[i] = level(holeX[i] - p);
            }
            var data = new byte[boxW * boxH];
            for (int j = 0; j < boxH; j++)
            {
                double y = j + 0.5 - halfH;
                double cy = Math.Abs(y) - (halfH - p), hy = Math.Abs(y - dy) - (halfH - p);
                int holeLine = level(hy - p);
                for (int i = 0; i < boxW; i++)
                {
                    double cx = cutX[i], cut;
                    if (cx > 0.0 && cy > 0.0)
                    {
                        int k = (int)(cy / (cx + cy) * steps + 0.5);
                        cut = 0.5 - (IconMark.Hypot(cx, cy) - rho[k]) * lean[k];
                    }
                    else cut = 0.5 - ((cx > cy ? cx : cy) - p);
                    if (cut <= 0.0) continue;
                    if (cut > 1.0) cut = 1.0;
                    double hx = holeX[i];
                    int hole;
                    if (hx > 0.0 && hy > 0.0)
                    {
                        int k = (int)(hy / (hx + hy) * steps + 0.5);
                        double distance = (IconMark.Hypot(hx, hy) - rho[k]) * lean[k];
                        hole = factor != 0 ? (int)(127.5 * Erfc(distance * factor) + 0.5) : level(distance);
                    }
                    else hole = holeColumns[i] < holeLine ? holeColumns[i] : holeLine;
                    data[j * boxW + i] = (byte)(int)((255 - hole) * cut + 0.5);
                }
            }
            return Remember(key, new ShadowMask { Key = key, Width = boxW, Height = boxH, Centre = new[] { boxW / 2, boxH / 2 },
                                                  Extent = 0, Coverage = data });
        }

        /// A shadow's offset in whole device pixels, rounded away from zero (shadow_step).
        internal static int ShadowStep(double value)
        {
            double step = Math.Floor(Math.Abs(value) + 0.5);
            return (int)(value < 0 || (value == 0 && 1 / value < 0) ? -step : step);
        }
    }
}
