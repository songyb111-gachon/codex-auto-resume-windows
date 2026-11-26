// Codex Auto Resume - the corner every rounded thing on the surfaces is drawn with: Figma's corner smoothing
// (v0.6.27, S6.3).
//
// The C# port of src/codex_auto_resume/brand/shape.py, call for call: design_smoothing, corner, smoothed,
// corner_segments, outline, flatten, and the corner's tables (profile, edge_at, inside_corner, inside, distance) the
// shadows and the card's cut read. gui/SoftShape.cs is the window's copy of the same numbers, but it reads the window's
// Palette and Design and does not compile without the window (seam (1) of S6.3's first return), so the host has this
// port, on the C runtime's sin, cos, tan and sqrt as the Python's math is. Coordinates are pixels, y down.
using System;
using System.Collections.Generic;

namespace CodexAutoResume
{
    /// One corner (brand/shape.py Corner): its radius and smoothing as the budget settled them, where it begins (p),
    /// the Bezier's lengths a, b, c, d and the arc's chord.
    internal sealed class ShapeCorner
    {
        internal double Radius, Smoothing, P, A, B, C, D, Chord;
    }

    /// One piece of an outline: a Bezier (four points), an arc (centre, radius, start, sweep in GDI+'s degrees) or a
    /// point (a corner left square).
    internal sealed class ShapeSegment
    {
        internal string Kind;
        internal double[][] Points;
        internal double Radius, Start, Sweep;
    }

    /// A corner's tables (brand/shape.py Profile).
    internal sealed class ShapeProfile
    {
        internal ShapeCorner Corner;
        internal double P, Middle, Joint;
        internal double[] BezierU, BezierV, Rho, Lean;
    }

    internal static class SurfaceShape
    {
        internal const double CornerSmoothing = 0.6;
        internal const int RhoSteps = 512;
        private const int HalfSteps = 64;
        private const int ProfileLimit = 64;

        private static double Rad(double degrees)
        {
            return degrees * (Math.PI / 180.0);
        }

        [System.Runtime.InteropServices.DllImport("ucrtbase.dll", EntryPoint = "tan", CallingConvention = System.Runtime.InteropServices.CallingConvention.Cdecl)]
        private static extern double CrtTan(double x);

        /// How much a design smooths its corners: Soft 0.6, Classic and Plain none (design_smoothing).
        internal static double DesignSmoothing(string design = "soft")
        {
            string name = SurfaceTheme.DesignChoice(design);
            return name == "soft" ? CornerSmoothing : 0.0;
        }

        /// One corner of `radius` smoothed by `smoothing`, in a box whose shorter side is 2 * budget (corner).
        internal static ShapeCorner Corner(double radius, double smoothing, double budget)
        {
            budget = Math.Max(0.0, budget);
            radius = Math.Max(0.0, Math.Min(radius, budget));
            if (radius <= 0.0) return new ShapeCorner();
            smoothing = Math.Max(0.0, Math.Min(smoothing, budget / radius - 1.0));
            double p = Math.Min((1.0 + smoothing) * radius, budget);
            double arc = 90.0 * (1.0 - smoothing);
            double chord = SurfaceMath.Sin(Rad(arc / 2.0)) * radius * SurfaceMath.Sqrt(2.0);
            double alpha = (90.0 - arc) / 2.0;
            double p3ToP4 = radius * CrtTan(Rad(alpha / 2.0));
            double beta = 45.0 * smoothing;
            double c = p3ToP4 * SurfaceMath.Cos(Rad(beta));
            double d = c * CrtTan(Rad(beta));
            double b = (p - chord - c - d) / 3.0;
            return new ShapeCorner { Radius = radius, Smoothing = smoothing, P = p, A = 2.0 * b, B = b, C = c, D = d, Chord = chord };
        }

        /// Whether a corner is drawn smoothed (smoothed).
        internal static bool Smoothed(ShapeCorner found)
        {
            return found.Smoothing > 1e-9;
        }

        internal static readonly string[] Order = { "top_left", "top_right", "bottom_right", "bottom_left" };

        private static double[] Turn(string name, double x, double y)
        {
            switch (name)
            {
                case "top_right": return new[] { x, y };
                case "bottom_right": return new[] { -y, x };
                case "bottom_left": return new[] { -x, -y };
            }
            return new[] { y, -x };
        }

        private static double Quadrant(string name)
        {
            switch (name)
            {
                case "top_right": return 270.0;
                case "bottom_right": return 0.0;
                case "bottom_left": return 90.0;
            }
            return 180.0;
        }

        private static double[] Vertex(double left, double top, double right, double bottom, string name)
        {
            switch (name)
            {
                case "top_left": return new[] { left, top };
                case "top_right": return new[] { right, top };
                case "bottom_right": return new[] { right, bottom };
            }
            return new[] { left, bottom };
        }

        /// One corner's segments (corner_segments): a Bezier, its arc and the Bezier back; a circular corner its arc alone.
        internal static List<ShapeSegment> CornerSegments(ShapeCorner found, double[] vertex, string name)
        {
            Func<double, double, double[]> at = (x, y) =>
            {
                double[] t = Turn(name, x, y);
                return new[] { vertex[0] + t[0], vertex[1] + t[1] };
            };
            double radius = found.Radius, p = found.P, a = found.A, b = found.B, c = found.C, d = found.D;
            double start = Quadrant(name);
            double[] centre = at(-radius, radius);
            var segments = new List<ShapeSegment>();
            if (!Smoothed(found))
            {
                segments.Add(new ShapeSegment { Kind = "arc", Points = new[] { centre }, Radius = radius, Start = start, Sweep = 90.0 });
                return segments;
            }
            double beta = 45.0 * found.Smoothing;
            segments.Add(new ShapeSegment { Kind = "bezier", Points = new[] { at(-p, 0.0), at(-p + a, 0.0), at(-p + a + b, 0.0), at(-p + a + b + c, d) } });
            segments.Add(new ShapeSegment { Kind = "arc", Points = new[] { centre }, Radius = radius, Start = start + beta, Sweep = 90.0 - 2.0 * beta });
            segments.Add(new ShapeSegment { Kind = "bezier", Points = new[] { at(-d, p - a - b - c), at(0.0, p - a - b), at(0.0, p - a), at(0.0, p) } });
            return segments;
        }

        /// The outline of `rect` with `corners` rounded (outline); empty for a box under a pixel across.
        internal static List<ShapeSegment> Outline(double[] rect, double radius, double smoothing, string[] corners = null)
        {
            corners = corners ?? Order;
            double left = rect[0], top = rect[1], right = rect[2], bottom = rect[3];
            double budget = Math.Min(right - left, bottom - top) / 2.0;
            ShapeCorner found = Corner(radius, smoothing, budget);
            var segments = new List<ShapeSegment>();
            if (found.Radius * 2.0 <= 1.0) return segments;
            foreach (string name in Order)
            {
                double[] vertex = Vertex(left, top, right, bottom, name);
                if (Array.IndexOf(corners, name) >= 0) segments.AddRange(CornerSegments(found, vertex, name));
                else segments.Add(new ShapeSegment { Kind = "point", Points = new[] { vertex } });
            }
            return segments;
        }

        internal static double[] BezierAt(double[] p0, double[] p1, double[] p2, double[] p3, double t)
        {
            double s = 1.0 - t;
            return new[] { s * s * s * p0[0] + 3 * s * s * t * p1[0] + 3 * s * t * t * p2[0] + t * t * t * p3[0],
                           s * s * s * p0[1] + 3 * s * s * t * p1[1] + 3 * s * t * t * p2[1] + t * t * t * p3[1] };
        }

        /// The outline's points, each Bezier and arc cut into `steps` straight pieces (flatten).
        internal static List<double[]> Flatten(List<ShapeSegment> segments, int steps = 32)
        {
            var points = new List<double[]>();
            foreach (ShapeSegment segment in segments)
            {
                if (segment.Kind == "point") points.Add(segment.Points[0]);
                else if (segment.Kind == "bezier")
                    for (int k = 0; k <= steps; k++)
                        points.Add(BezierAt(segment.Points[0], segment.Points[1], segment.Points[2], segment.Points[3], k / (double)steps));
                else
                    for (int k = 0; k <= steps; k++)
                    {
                        double angle = Rad(segment.Start + segment.Sweep * k / (double)steps);
                        points.Add(new[] { segment.Points[0][0] + segment.Radius * SurfaceMath.Cos(angle),
                                           segment.Points[0][1] + segment.Radius * SurfaceMath.Sin(angle) });
                    }
            }
            return points;
        }

        // ------------------------------------------------------------------ the corner's tables

        private static double ArcV(double radius, double u)
        {
            double rest = radius * radius - (radius - u) * (radius - u);
            return rest > 0.0 ? radius - SurfaceMath.Sqrt(rest) : radius;
        }

        private static List<double[]> HalfPoints(ShapeCorner found)
        {
            double radius = found.Radius, p = found.P, a = found.A, b = found.B, c = found.C, d = found.D;
            var points = new List<double[]>();
            double start;
            if (Smoothed(found))
            {
                for (int k = 0; k < HalfSteps; k++)
                    points.Add(BezierAt(new[] { p, 0.0 }, new[] { p - a, 0.0 }, new[] { p - a - b, 0.0 }, new[] { p - a - b - c, d },
                                        k / (double)HalfSteps));
                start = Rad(270.0 - 45.0 * found.Smoothing);
            }
            else start = Rad(270.0);
            double end = Rad(225.0);
            for (int k = 0; k <= HalfSteps; k++)
            {
                double angle = start + (end - start) * k / (double)HalfSteps;
                points.Add(new[] { radius + radius * SurfaceMath.Cos(angle), radius + radius * SurfaceMath.Sin(angle) });
            }
            return points;
        }

        /// Python's bisect.bisect_left over an ascending list.
        internal static int BisectLeft(IList<double> values, double x)
        {
            int low = 0, high = values.Count;
            while (low < high)
            {
                int middle = (low + high) / 2;
                if (values[middle] < x) low = middle + 1;
                else high = middle;
            }
            return low;
        }

        private static readonly Dictionary<double, ShapeProfile> Units = new Dictionary<double, ShapeProfile>();
        private static readonly Dictionary<string, ShapeProfile> Profiles = new Dictionary<string, ShapeProfile>();

        private static ShapeProfile Unit(double smoothing)
        {
            ShapeProfile known;
            if (Units.TryGetValue(smoothing, out known)) return known;
            ShapeCorner found = Corner(1.0, smoothing, 1e9);
            double p = found.P, radius = found.Radius;
            List<double[]> half = HalfPoints(found);
            double joint = Smoothed(found) ? p - found.A - found.B - found.C : radius;
            var bezier = new List<double[]>();
            if (Smoothed(found))
            {
                for (int i = 0; i <= HalfSteps && i < half.Count; i++) if (half[i][0] >= joint) bezier.Add(half[i]);
                bezier.Sort((x, y) => x[0] != y[0] ? x[0].CompareTo(y[0]) : x[1].CompareTo(y[1]));
            }
            var ts = new List<double>();
            var rs = new List<double>();
            var leans = new List<double>();
            int last = half.Count - 1;
            for (int k = last; k >= 0; k--)
            {
                double u = half[k][0], v = half[k][1];
                double qx = p - u, qy = p - v;
                if (qx + qy <= 0.0) continue;
                double[] one = half[Math.Max(0, k - 1)], other = half[Math.Min(last, k + 1)];
                double tangent = IconMark.Hypot(other[0] - one[0], other[1] - one[1]);
                double r = IconMark.Hypot(qx, qy);
                ts.Add(qy / (qx + qy));
                rs.Add(r);
                leans.Add(tangent > 0.0 && r > 0.0 ? Math.Abs(qx * (other[1] - one[1]) - qy * (other[0] - one[0])) / (r * tangent) : 1.0);
            }
            var rho = new double[RhoSteps + 1];
            var lean = new double[RhoSteps + 1];
            for (int i = 0; i <= RhoSteps; i++) lean[i] = 1.0;
            for (int k = RhoSteps / 2; k <= RhoSteps; k++)
            {
                double t = k / (double)RhoSteps;
                int i = Math.Min(Math.Max(1, BisectLeft(ts, t)), ts.Count - 1);
                double t0 = ts[i - 1], t1 = ts[i];
                double share = t1 > t0 ? Math.Min(1.0, Math.Max(0.0, (t - t0) / (t1 - t0))) : 0.0;
                rho[k] = rho[RhoSteps - k] = rs[i - 1] + (rs[i] - rs[i - 1]) * share;
                lean[k] = lean[RhoSteps - k] = leans[i - 1] + (leans[i] - leans[i - 1]) * share;
            }
            var made = new ShapeProfile { Corner = found, P = p, Middle = radius * (1.0 - SurfaceMath.Sqrt(0.5)), Joint = joint,
                                          BezierU = bezier.ConvertAll(point => point[0]).ToArray(),
                                          BezierV = bezier.ConvertAll(point => point[1]).ToArray(), Rho = rho, Lean = lean };
            if (Units.Count >= ProfileLimit) Units.Clear();
            Units[smoothing] = made;
            return made;
        }

        private static double Round(double value, int digits)
        {
            return CardPlan.RoundTo(value, digits);
        }

        /// The corner's tables, kept per corner as drawn: the unit corner's, made `radius` large (profile).
        internal static ShapeProfile Profile(double radius, double smoothing, double budget)
        {
            ShapeCorner found = Corner(radius, smoothing, budget);
            string key = Round(found.Radius, 6).ToString("R") + "|" + Round(found.Smoothing, 6).ToString("R");
            ShapeProfile known;
            if (Profiles.TryGetValue(key, out known)) return known;
            ShapeProfile unit = Unit(Round(found.Smoothing, 9));
            double size = found.Radius;
            Func<double[], double[]> grown = values => Array.ConvertAll(values, value => size * value);
            var made = new ShapeProfile { Corner = found, P = found.P, Middle = unit.Middle * size, Joint = unit.Joint * size,
                                          BezierU = grown(unit.BezierU), BezierV = grown(unit.BezierV), Rho = grown(unit.Rho),
                                          Lean = unit.Lean };
            if (Profiles.Count >= ProfileLimit) Profiles.Clear();
            Profiles[key] = made;
            return made;
        }

        /// f(u): the outline's v at u on its half nearer the horizontal side (edge_at).
        internal static double EdgeAt(ShapeProfile made, double u)
        {
            if (u >= made.P) return 0.0;
            if (u <= made.Joint || made.BezierU.Length < 2) return ArcV(made.Corner.Radius, Math.Max(0.0, Math.Min(u, made.Corner.Radius)));
            double[] us = made.BezierU, vs = made.BezierV;
            int i = Math.Min(Math.Max(1, BisectLeft(us, u)), us.Length - 1);
            double u0 = us[i - 1], u1 = us[i];
            return vs[i - 1] + (vs[i] - vs[i - 1]) * (u1 > u0 ? (u - u0) / (u1 - u0) : 0.0);
        }

        /// Whether a point in a corner's local frame is inside the outline (inside_corner).
        internal static bool InsideCorner(ShapeProfile made, double u, double v)
        {
            if (u < 0.0 || v < 0.0) return false;
            if (u >= made.P || v >= made.P) return true;
            if (v > u) { double swap = u; u = v; v = swap; }
            if (u < made.Middle) return false;
            return v >= EdgeAt(made, u);
        }

        /// Whether (x, y) is inside `rect` rounded by `radius` and `smoothing` (inside).
        internal static bool Inside(double x, double y, double[] rect, double radius, double smoothing)
        {
            double left = rect[0], top = rect[1], right = rect[2], bottom = rect[3];
            if (!(left <= x && x <= right && top <= y && y <= bottom)) return false;
            ShapeProfile made = Profile(radius, smoothing, Math.Min(right - left, bottom - top) / 2.0);
            return InsideCorner(made, Math.Min(x - left, right - x), Math.Min(y - top, bottom - y));
        }

        /// Signed distance from (x, y) to the rounded box centred on the origin; inside is negative (distance).
        internal static double Distance(double x, double y, double halfWidth, double halfHeight, double radius, double smoothing)
        {
            ShapeProfile made = Profile(radius, smoothing, Math.Min(halfWidth, halfHeight));
            double p = made.P;
            double qx = Math.Abs(x) - (halfWidth - p);
            double qy = Math.Abs(y) - (halfHeight - p);
            if (qx > 0.0 && qy > 0.0)
            {
                if (!Smoothed(made.Corner)) return IconMark.Hypot(qx, qy) - p;
                int k = (int)(qy / (qx + qy) * RhoSteps + 0.5);
                return (IconMark.Hypot(qx, qy) - made.Rho[k]) * made.Lean[k];
            }
            return Math.Max(qx, qy) - p;
        }
    }
}
