// Codex Auto Resume - what the icon does while it is watched: the states it moves in, and every frame of them
// (v0.6.27, S6.3).
//
// The C# port of src/codex_auto_resume/ui/tray/motion.py, call for call: the states (ICON_FOR_LIGHT, icon_brand_state),
// the head's colours (icon_head_colour, icon_level_colour), the frame table's arithmetic (icon_turn, icon_frame and
// icon_frame_ms, with the notification area's finer steps), what may move (icon_motion_allowed), and the frames as
// pixels (IconFrames, build_icon_frames) from brand/mark.py's rasteriser (icon_samples, icon_pixel, icon_head_box).
// Pure: the frames need no Windows. Brand.Mark (gui/Brand.cs) is the same motion for the window's taskbar button,
// generated, at its 24 positions and with .NET's own cosine; the icon's frames here run on `fine` steps and the C
// runtime's functions, as the Python's do.
//
// Not here yet: a special day's motif on the badge (brand.mark_colour and the day looks' bodies, IconFrames' `look`):
// IconFrames refuses a look rather than drawing a day it does not know.
using System;
using System.Collections.Generic;
using System.Drawing;

namespace CodexAutoResume
{
    internal static class TrayMotion
    {
        internal static readonly string[] IconStates = { "watching", "recovering", "idle", "attention", "failed" };
        internal const int Breaths = 3, SweepBreaths = 2;
        internal const double SweepOut = 0.4, SweepHold = 0.025, RecoverRest = 0.075, FailedSlot = 0.5;
        internal const int BreatheFrameMs = 156, TurnFrameMs = 62, Positions = 24, TrayFine = 4, GlideFrameMs = 31;
        internal const int Levels = 24;
        internal const double Dim = 0.6;
        internal const int BuildBudgetMs = 2000, Cache = 256;
        /// The stroke, in degrees: (arc_end - arc_start) % 360 (ICON_SWEEP).
        internal static readonly double IconSweep = SurfaceMath.Mod(IconMark.ArcEnd - IconMark.ArcStart, 360.0);

        /// The icon's state as a brand status-light state; anything unknown is idle (icon_brand_state).
        internal static string BrandState(string state)
        {
            switch (state)
            {
                case "watching": return "monitoring";
                case "recovering": return "recovering";
                case "attention": return "attention";
                case "failed": return "failed";
            }
            return "idle";
        }

        /// The icon's state for a status-light word; anything else is idle (ICON_FOR_LIGHT).
        internal static string ForLight(string word)
        {
            switch (word)
            {
                case "monitoring": case "waiting": case "checking": return "watching";
                case "recovering": return "recovering";
                case "attention": return "attention";
                case "failed": return "failed";
            }
            return "idle";
        }

        /// The brand fill token a status-light state is drawn in (brand.status_fill): running states the active fill.
        internal static string StatusFill(string state)
        {
            switch (state)
            {
                case "monitoring": case "waiting": case "checking": case "recovering": return "active";
                case "attention": return "attention";
                case "failed": return "danger";
            }
            return "idle";
        }

        /// The head's full colour in a state, as (red, green, blue) (icon_head_colour): the mark's accent while it
        /// runs, else the state's colour in the palette ICON_HEAD_PALETTE names.
        internal static int[] HeadColour(string state)
        {
            string token = StatusFill(BrandState(state));
            if (token == "active") return IconMark.Rgb(IconMark.Accent);
            string palette = token == "attention" || token == "danger" ? "dark" : "light";
            return SurfaceTheme.Rgb(SurfaceTheme.Token(token, palette, "soft"));
        }

        /// The head's colour at breathing `level` (icon_level_colour): the top level is `colour`, the lowest Dim of the
        /// way toward the badge's deep blue.
        internal static int[] LevelColour(int[] colour, int level)
        {
            int top = Levels - 1;
            level = Math.Max(0, Math.Min(top, level));
            double amount = Dim * (top - level) / (double)top;
            int[] target = IconMark.Rgb(IconMark.Bottom);
            var found = new int[3];
            for (int i = 0; i < 3; i++) found[i] = (int)Math.Floor(colour[i] + (target[i] - colour[i]) * amount + 0.5);
            return found;
        }

        /// 0 at the start of a cycle, 1 halfway, 0 again (brand._breath).
        internal static double Breath(double elapsedMs, double cycleMs)
        {
            return 0.5 - 0.5 * SurfaceMath.Cos(2 * Math.PI * SurfaceMath.Mod(elapsedMs, cycleMs) / cycleMs);
        }

        private static int BreathLevel(double elapsedMs, double cycleMs)
        {
            int top = Levels - 1;
            return SurfaceMath.Round(top * (1.0 - Breath(elapsedMs, cycleMs)));
        }

        /// How far along the stroke the head has swept, in degrees, or null when the state is not sweeping (icon_turn).
        internal static double? Turn(string state, double elapsedMs)
        {
            if (state != "watching" && state != "recovering" && state != "failed") return null;
            double breath = Brand.GlowMonitoringMs;
            if (state == "failed") breath *= FailedSlot;
            int sweeps = state == "watching" ? SweepBreaths : 1;
            double outMs = breath * sweeps * SweepOut, hold = breath * sweeps * SweepHold;
            double start = state == "watching" ? breath * Breaths : 0.0;
            double cycle = state == "watching" ? start + breath * sweeps : 2 * outMs + hold + breath * RecoverRest;
            double into = SurfaceMath.Mod(elapsedMs, cycle) - start;
            if (into < 0 || into >= 2 * outMs + hold) return into < 0 ? (double?)null : 0.0;
            return IconSweep * Breath(Math.Min(into, Math.Max(outMs, into - hold)), 2 * outMs);
        }

        /// (head position, breathing level) for one frame (icon_frame); `fine` positions per plain one.
        internal static int[] Frame(string state, double elapsedMs, bool reduced = false, int fine = 1)
        {
            int positions = Positions * fine, top = Levels - 1;
            if (reduced) return new[] { 0, top };
            double? turn = Turn(state, elapsedMs);
            if (turn.HasValue)
            {
                int level = state == "failed" ? BreathLevel(elapsedMs, Brand.GlowFailedMs) : top;
                int position = SurfaceMath.Round(turn.Value / (360.0 / positions));
                return new[] { ((position % positions) + positions) % positions, level };
            }
            if (state == "watching") return new[] { 0, BreathLevel(elapsedMs, Brand.GlowMonitoringMs) };
            if (state == "attention") return new[] { 0, BreathLevel(elapsedMs, Brand.GlowAttentionMs) };
            return new[] { 0, top };
        }

        /// How soon the next frame is due, in ms, or null when nothing moves (icon_frame_ms). With `fine` steps,
        /// watching's sweep glides at GlideFrameMs and, home after it, waits for the next breath in one go.
        internal static double? FrameMs(string state, double elapsedMs, bool reduced = false, int fine = 1)
        {
            if (reduced) return null;
            if (Turn(state, elapsedMs).HasValue)
            {
                if (fine > 1 && state == "watching")
                {
                    double glide = GlideFrameMs;
                    double breath = Brand.GlowMonitoringMs;
                    int sweeps = SweepBreaths;
                    double outMs = breath * sweeps * SweepOut, hold = breath * sweeps * SweepHold;
                    double cycle = breath * (Breaths + sweeps);
                    double into = SurfaceMath.Mod(elapsedMs, cycle);
                    if (into - breath * Breaths >= 2 * outMs + hold)
                    {
                        double each = Math.Ceiling(glide / (1000.0 / 64)) * (1000.0 / 64);
                        return glide * Math.Max(1, (int)Math.Ceiling((cycle - into) / each - 1e-9));
                    }
                    return glide;
                }
                return TurnFrameMs;
            }
            if (state == "watching" || state == "attention") return BreatheFrameMs;
            return null;
        }

        /// Whether the icon may move at all (icon_motion_allowed): any one stopper holds it still.
        internal static bool MotionAllowed(bool reduced = false, bool contrast = false, bool batterySaver = false,
                                           bool locked = false, bool hidden = false, bool frames = true)
        {
            return frames && !(reduced || contrast || batterySaver || locked || hidden);
        }
    }

    /// brand/mark.py: the mark's own colours, its geometry, and the rasteriser the icon's frames are drawn from.
    internal static class IconMark
    {
        internal const string Top = "#1B62C4", Bottom = "#0B2545", Mark = "#F2F9FF", Accent = "#4FE0F5";
        internal const double RingInner = 0.34, RingOuter = 0.53, ArcStart = 125.0, ArcEnd = 55.0, HeadRadius = 0.155;
        internal const double CornerLarge = 0.30, CornerSmall = 0.24;
        internal const int CornerThreshold = 32, Supersample = 4;

        internal static int[] Rgb(string hex)
        {
            string text = hex.TrimStart('#');
            return new[] { Convert.ToInt32(text.Substring(0, 2), 16), Convert.ToInt32(text.Substring(2, 2), 16),
                           Convert.ToInt32(text.Substring(4, 2), 16) };
        }

        /// math.hypot as CPython 3.8+ computes it for two values: correctly rounded wherever the double-double residual
        /// can tell, which the C runtime's _hypot and sqrt(x*x + y*y) are not always.
        internal static double Hypot(double x, double y)
        {
            x = Math.Abs(x);
            y = Math.Abs(y);
            if (double.IsInfinity(x) || double.IsInfinity(y)) return double.PositiveInfinity;
            if (double.IsNaN(x) || double.IsNaN(y)) return double.NaN;
            double max = Math.Max(x, y), min = Math.Min(x, y);
            if (max == 0.0) return 0.0;
            // Scale to [0.5, 1) by a power of two, square exactly as a double-double, then take one correcting step of
            // the square root (CPython's vector_norm, "Improved accuracy" since 3.10).
            int exponent = (int)Math.Floor(Math.Log(max, 2)) + 1;
            double scale = Math.Pow(2.0, -exponent);
            double a = max * scale, b = min * scale;
            double hi, lo;
            TwoSquareSum(a, b, out hi, out lo);
            double h = Math.Sqrt(hi);
            // One Newton step on the residual of h * h against hi + lo, exactly as a double-double.
            double square, squareLow;
            TwoProduct(h, h, out square, out squareLow);
            double residual = (hi - square) - squareLow + lo;
            h += residual / (2.0 * h);
            return h / scale;
        }

        private static void TwoProduct(double a, double b, out double product, out double error)
        {
            product = a * b;
            const double split = 134217729.0;           // 2^27 + 1
            double ca = split * a, ah = ca - (ca - a), al = a - ah;
            double cb = split * b, bh = cb - (cb - b), bl = b - bh;
            error = ((ah * bh - product) + ah * bl + al * bh) + al * bl;
        }

        private static void TwoSquareSum(double a, double b, out double hi, out double lo)
        {
            double aa, aaLow, bb, bbLow;
            TwoProduct(a, a, out aa, out aaLow);
            TwoProduct(b, b, out bb, out bbLow);
            hi = aa + bb;
            double virtualB = hi - aa;
            double sumLow = (aa - (hi - virtualB)) + (bb - virtualB);
            lo = sumLow + aaLow + bbLow;
        }

        /// Signed distance to a rounded square of half-size 1; negative inside (icon_rounded_square).
        internal static double RoundedSquare(double x, double y, double radius)
        {
            double half = 1.0 - radius;
            double dx = Math.Max(Math.Abs(x) - half, 0.0);
            double dy = Math.Max(Math.Abs(y) - half, 0.0);
            if (Math.Abs(x) > 1.0 || Math.Abs(y) > 1.0) return 1.0;
            return Hypot(dx, dy) - radius;
        }

        /// True inside an annulus sector, angles in radians counter-clockwise (icon_ring_arc).
        internal static bool RingArc(double x, double y, double inner, double outer, double start, double end)
        {
            double distance = Hypot(x, y);
            if (!(inner <= distance && distance <= outer)) return false;
            double angle = SurfaceMath.Mod(SurfaceMath.Atan2(y, x), 2 * Math.PI);
            start = SurfaceMath.Mod(start, 2 * Math.PI);
            end = SurfaceMath.Mod(end, 2 * Math.PI);
            if (start <= end) return start <= angle && angle <= end;
            return angle >= start || angle <= end;
        }

        /// math.radians.
        internal static double Radians(double degrees)
        {
            return degrees * (Math.PI / 180.0);
        }

        /// The head's centre on the stroke's centre line at `angle` degrees (icon_head_centre).
        internal static double[] HeadCentre(double? angle)
        {
            double middle = (RingInner + RingOuter) / 2.0;
            double radians = Radians(angle ?? ArcEnd);
            return new[] { middle * SurfaceMath.Cos(radians), middle * SurfaceMath.Sin(radians) };
        }

        /// The pixels (left, top, right, bottom) a head at `angle` can touch in a `size` icon (icon_head_box).
        internal static int[] HeadBox(int size, double? angle)
        {
            double[] centre = HeadCentre(angle);
            double x = centre[0], y = centre[1], reach = HeadRadius;
            return new[] { Math.Max(0, (int)Math.Floor((x - reach + 1.0) / 2.0 * size)),
                           Math.Max(0, (int)Math.Floor((1.0 - (y + reach)) / 2.0 * size)),
                           Math.Min(size, (int)Math.Ceiling((x + reach + 1.0) / 2.0 * size)),
                           Math.Min(size, (int)Math.Ceiling((1.0 - (y - reach)) / 2.0 * size)) };
        }

        /// The mark's samples, pixel by pixel (icon_samples): rows of (covered, heads, red, green, blue).
        internal static int[][][] Samples(int size, double rim = 0.0, double? headAngle = null, bool head = true, int[] box = null)
        {
            int steps = Supersample;
            int scale = size * steps;
            double radius = size >= CornerThreshold ? CornerLarge : CornerSmall;
            int[] topColour = Rgb(Top), bottomColour = Rgb(Bottom), mark = Rgb(Mark);
            double start = Radians(ArcStart), end = Radians(ArcEnd);
            double[] centre = HeadCentre(headAngle);
            double headX = centre[0], headY = centre[1];
            int left = 0, top = 0, right = size, bottom = size;
            if (box != null) { left = box[0]; top = box[1]; right = box[2]; bottom = box[3]; }
            var rows = new int[Math.Max(0, bottom - top)][][];
            for (int py = top; py < bottom; py++)
            {
                var row = new int[Math.Max(0, right - left)][];
                for (int px = left; px < right; px++)
                {
                    int covered = 0, heads = 0, red = 0, green = 0, blue = 0;
                    for (int sy = 0; sy < steps; sy++)
                    {
                        double fy = (py * steps + sy + 0.5) / scale * 2.0 - 1.0;
                        for (int sx = 0; sx < steps; sx++)
                        {
                            double fx = (px * steps + sx + 0.5) / scale * 2.0 - 1.0;
                            double distance = RoundedSquare(fx, fy, radius);
                            if (distance > 0.0) continue;
                            covered++;
                            if (head && Hypot(fx - headX, -fy - headY) <= HeadRadius)
                            {
                                heads++;
                                continue;
                            }
                            int r, g, b;
                            if (RingArc(fx, -fy, RingInner, RingOuter, start, end)) { r = mark[0]; g = mark[1]; b = mark[2]; }
                            else if (rim != 0.0 && distance >= -rim) { r = topColour[0]; g = topColour[1]; b = topColour[2]; }
                            else
                            {
                                double position = (fy + 1.0) / 2.0;
                                r = SurfaceMath.Round(topColour[0] + (bottomColour[0] - topColour[0]) * position);
                                g = SurfaceMath.Round(topColour[1] + (bottomColour[1] - topColour[1]) * position);
                                b = SurfaceMath.Round(topColour[2] + (bottomColour[2] - topColour[2]) * position);
                            }
                            red += r;
                            green += g;
                            blue += b;
                        }
                    }
                    row[px - left] = new[] { covered, heads, red, green, blue };
                }
                rows[py - top] = row;
            }
            return rows;
        }

        /// One (red, green, blue, alpha) pixel from a sample, with the head in `head` (icon_pixel).
        internal static int[] Pixel(int[] sample, int[] head)
        {
            int covered = sample[0], heads = sample[1];
            if (covered == 0) return new[] { 0, 0, 0, 0 };
            return new[] { (sample[2] + heads * head[0]) / covered, (sample[3] + heads * head[1]) / covered,
                           (sample[4] + heads * head[2]) / covered, covered * 255 / (Supersample * Supersample) };
        }
    }

    /// The icon's frames for one size, as pixels (motion.IconFrames): the mark without its head rendered once, and
    /// for each head position only the pixels the head can touch, the head kept apart so it can take any colour.
    /// Top-down BGRA with straight alpha, as icon bitmaps are.
    internal sealed class IconFrames
    {
        internal readonly int Size, Fine;
        internal readonly string Look;
        internal readonly byte[] Ground;
        private readonly List<KeyValuePair<int[], int[][][]>> heads = new List<KeyValuePair<int[], int[][][]>>();
        private readonly Dictionary<string, byte[]> cache = new Dictionary<string, byte[]>();
        private readonly LinkedList<string> order = new LinkedList<string>();

        internal IconFrames(int size, int fine = 1, string look = null)
        {
            if (size <= 0 || fine < 1) throw new ArgumentException("an icon has a size, and a position at least one step");
            if (look != null) throw new NotSupportedException("a special day's mark is not drawn by the host yet: " + look);
            Size = size;
            Fine = fine;
            Look = look;
            int positions = TrayMotion.Positions * Fine;
            var ground = new byte[size * size * 4];
            int[][][] rows = IconMark.Samples(size, 0.0, null, false);
            for (int y = 0; y < rows.Length; y++)
                for (int x = 0; x < rows[y].Length; x++)
                {
                    int[] pixel = IconMark.Pixel(rows[y][x], new[] { 0, 0, 0 });
                    int index = (y * size + x) * 4;
                    ground[index] = (byte)pixel[2];
                    ground[index + 1] = (byte)pixel[1];
                    ground[index + 2] = (byte)pixel[0];
                    ground[index + 3] = (byte)pixel[3];
                }
            Ground = ground;
            for (int position = 0; position < positions; position++)
            {
                double angle = IconMark.ArcEnd - 360.0 * position / positions;
                int[] box = IconMark.HeadBox(size, angle);
                heads.Add(new KeyValuePair<int[], int[][][]>(box, IconMark.Samples(size, 0.0, angle, true, box)));
            }
        }

        internal int Count { get { return heads.Count; } }

        /// One frame: the head at `position` in `head` (red, green, blue) (compose).
        internal byte[] Compose(int position, int[] head)
        {
            int at = ((position % heads.Count) + heads.Count) % heads.Count;
            string key = at + "," + head[0] + "," + head[1] + "," + head[2];
            byte[] cached;
            if (cache.TryGetValue(key, out cached)) return cached;
            var pixels = (byte[])Ground.Clone();
            int[] box = heads[at].Key;
            int[][][] rows = heads[at].Value;
            for (int y = 0; y < rows.Length; y++)
                for (int x = 0; x < rows[y].Length; x++)
                {
                    int[] pixel = IconMark.Pixel(rows[y][x], head);
                    int index = ((box[1] + y) * Size + box[0] + x) * 4;
                    pixels[index] = (byte)pixel[2];
                    pixels[index + 1] = (byte)pixel[1];
                    pixels[index + 2] = (byte)pixel[0];
                    pixels[index + 3] = (byte)pixel[3];
                }
            if (cache.Count >= TrayMotion.Cache)
            {
                cache.Remove(order.First.Value);
                order.RemoveFirst();
            }
            cache[key] = pixels;
            order.AddLast(key);
            return pixels;
        }
    }
}
