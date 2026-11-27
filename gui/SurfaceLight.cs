// Codex Auto Resume - the popup's status light, drawn (v0.6.27, S6.3).
//
// The C# port of src/codex_auto_resume/ui/popup/light.py, call for call: StatusLight's sweep (the seventh press's arc
// and rings, brand.sweep_at), draw_halo over the band of rows the whole frame kept (_keep_halo_band, halo_rows), the
// dot and its glow (_halo, _light). As in the Python it is a part of the renderer's class, not a class of its own: it
// paints with the renderer's colours and its High Contrast.
using System;
using System.Runtime.InteropServices;

namespace CodexAutoResume
{
    internal sealed partial class SurfaceRenderer
    {
        // brand.SWEEP: the sweep and its two rings, in the mock's numbers for a light in a box 54 across.
        internal const double SweepArcMs = 735, SweepArcFadeMs = 315, SweepRingMs = 900, SweepFirstRingMs = 750;
        internal const double SweepSecondRingMs = 1000, SweepReach = 27.0, SweepArcRadius = 17.0, SweepRingFrom = 15.0;
        internal const double SweepHeadRadius = 3.4, SweepRingOpacity = 0.65;
        /// brand.STATUS_DOT["popup"], in CSS px.
        internal const double PopupDot = 4.5;

        /// How far on the seventh press's sweep is, or null: the window says, and it is drawn with the light.
        internal double? SweepMs { get; set; }

        private SurfacePlan haloPlan;
        private int haloOffset;
        private byte[] haloBand;

        /// brand.sweep_at: (arc covered 0 to 1, arc opacity, the two rings' (spread, opacity)).
        internal static double[] SweepAt(double milliseconds)
        {
            double covered = Brand.Ease(milliseconds / SweepArcMs);
            double opacity = milliseconds <= SweepArcMs ? 1.0 : 1.0 - Brand.Ease((milliseconds - SweepArcMs) / SweepArcFadeMs);
            var found = new double[6];
            found[0] = covered;
            found[1] = opacity;
            double[] starts = { SweepFirstRingMs, SweepSecondRingMs };
            for (int i = 0; i < 2; i++)
            {
                double since = milliseconds - starts[i];
                double spread = Brand.Ease(since / SweepRingMs);
                found[2 + 2 * i] = spread;
                found[3 + 2 * i] = since < 0 || since >= SweepRingMs ? 0.0 : SweepRingOpacity * (1.0 - spread);
            }
            return found;
        }

        /// brand.status_fill: the token a state's dot is filled with; anything unknown is idle grey.
        internal static string StatusFill(object state)
        {
            string word = state as string;
            if (word == "monitoring" || word == "waiting" || word == "checking" || word == "recovering") return "active";
            if (word == "attention") return "attention";
            if (word == "failed") return "danger";
            if (word == "paused") return "paused";
            return "idle";
        }

        /// brand.status_system: the High Contrast system colour a state's dot is filled with.
        internal static string StatusSystem(object state)
        {
            string word = state as string;
            if (word == "monitoring" || word == "waiting" || word == "checking" || word == "recovering") return "Highlight";
            if (word == "attention" || word == "failed") return "WindowText";
            return "GrayText";
        }

        /// A system colour as High Contrast paints with it: the job's table when one is set, else Windows (system_rgb).
        private static int[] SystemColour(string name)
        {
            int[] found;
            if (SystemColours != null && SystemColours.TryGetValue(name, out found)) return found;
            return SurfaceTheme.SystemRgb(name);
        }

        private static uint Pack(int[] rgb, double alpha = 1.0)
        {
            return SurfaceNative.Pack(rgb[0], rgb[1], rgb[2], alpha);
        }

        /// The arc round the light with its head leading, then two rings, in the room the plan keeps for it (_sweep).
        private void Sweep(SurfacePainter paint, PlanItem item, double milliseconds)
        {
            double cx = D(item["cx"]), cy = D(item["cy"]);
            double unit = D(item["sweep_reach"]) / SweepReach;
            // brand.status_colour(state, theme): the default design's palette, as the Python asks it.
            int[] colour = SurfaceTheme.Rgb(SurfaceTheme.Token(StatusFill(item["state"]), ThemeName(), "soft"));
            double[] at = SweepAt(milliseconds);
            double covered = at[0], opacity = at[1];
            double[] widths = { 1.6, 1.2 };
            for (int i = 0; i < 2; i++)
            {
                double spread = at[2 + 2 * i], ring = at[3 + 2 * i];
                if (ring > 0)
                {
                    double radius = unit * (SweepRingFrom + (SweepReach - SweepRingFrom) * spread);
                    paint.StrokeRound(new[] { cx - radius, cy - radius, cx + radius, cy + radius }, radius, Pack(colour, ring),
                                      Math.Max(1.0, unit * widths[i]));
                }
            }
            if (opacity <= 0) return;
            double arcRadius = unit * SweepArcRadius;
            if (covered > 0.001) paint.Arc(cx, cy, arcRadius, -90.0, 360.0 * covered, Pack(colour, opacity), Math.Max(1.0, unit * 2.4));
            double angle = (360.0 * covered - 90.0) * (Math.PI / 180.0);
            paint.FillCircle(cx + arcRadius * SurfaceMath.Cos(angle), cy + arcRadius * SurfaceMath.Sin(angle),
                             Math.Max(1.5, unit * SweepHeadRadius), SurfaceNative.Pack(0x4F, 0xE0, 0xF5, opacity));
        }

        private static PlanItem HaloOf(SurfacePlan plan)
        {
            foreach (PlanItem entry in plan.Items)
                if (entry.Kind == "halo") return entry;
            return null;
        }

        /// Only the halo, for an animation frame; everything else in the canvas is kept (draw_halo). The band of rows
        /// behind it was saved when the whole frame was drawn.
        internal SurfaceCanvas DrawHalo(SurfacePlan plan, LightFrame frame, bool restore = true)
        {
            PlanItem item = HaloOf(plan);
            if (item == null) return Canvas;
            if (restore)
            {
                if (haloPlan != plan || haloBand == null) throw new ArgumentException("the whole frame has to be drawn before its halo");
                Marshal.Copy(haloBand, 0, Canvas.Bits + haloOffset, haloBand.Length);
            }
            using (var paint = new SurfacePainter(Canvas))
            {
                Halo(paint, item, plan.Scale, frame);
                if (SweepMs.HasValue) Sweep(paint, item, SweepMs.Value);
            }
            return Canvas;
        }

        internal SurfacePlan HaloPlan { get { return haloPlan; } }

        /// (first row, row after the last) of the band DrawHalo draws into, or null (halo_rows).
        internal int[] HaloRows
        {
            get
            {
                if (haloBand == null) return null;
                int row = Canvas.Width * 4;
                return new[] { haloOffset / row, (haloOffset + haloBand.Length) / row };
            }
        }

        private void KeepHaloBand(SurfacePlan plan)
        {
            PlanItem item = HaloOf(plan);
            haloPlan = plan;
            if (item == null)
            {
                haloBand = null;
                return;
            }
            SurfaceNative.GdiFlush();
            // The item's radius is the largest glow any frame draws; leave room for its soft edge.
            object sweepReach = item.Get("sweep_reach");
            double reach = Math.Max(D(item["radius"]), sweepReach == null ? 0.0 : D(sweepReach)) + 2 * plan.Scale + 2;
            double cy = D(item["cy"]);
            int top = Math.Max(0, (int)(cy - reach));
            int bottom = Math.Min(Canvas.Height, (int)Math.Ceiling(cy + reach));
            haloOffset = top * Canvas.Width * 4;
            haloBand = new byte[Math.Max(0, (bottom - top) * Canvas.Width * 4)];
            Marshal.Copy(Canvas.Bits + haloOffset, haloBand, 0, haloBand.Length);
        }

        /// The state dot, flat and the size it always was, with its glow and the checking arc (_halo).
        private void Halo(SurfacePainter paint, PlanItem item, double scale, LightFrame frame)
        {
            object state = item["state"];
            double cx = D(item["cx"]), cy = D(item["cy"]);
            double dot = PopupDot;
            double? arc = frame != null ? frame.Arc : null;
            double arcRadius = (dot + Brand.GlowArcGap) * scale, arcWidth = Brand.GlowArcWidth * scale;
            if (Contrast)
            {
                uint colour = Pack(SystemColour(StatusSystem(state)));
                paint.FillCircle(cx, cy, dot * scale, colour);
                if (arc.HasValue) paint.Arc(cx, cy, arcRadius, arc.Value, Brand.GlowArcSweep, colour, arcWidth);
                return;
            }
            Light(paint, cx, cy, dot, scale, StatusFill(state), frame);
            if (arc.HasValue) paint.Arc(cx, cy, arcRadius, arc.Value, Brand.GlowArcSweep, Argb("active", Brand.GlowArcAlpha), arcWidth);
        }

        /// brand.glow_reach.
        internal static double GlowReach(double dot) { return Brand.GlowReachOfRadius * dot; }

        /// brand.glow_radius: the glow's outer radius in CSS px for a frame's `spread`.
        internal static double GlowRadius(double dot, double spread = 1.0) { return dot + GlowReach(dot) * spread; }

        /// brand.glow_stops: the falloff as (fraction of the outer radius, alpha factor) stops.
        internal static double[][] GlowStops(double dot)
        {
            double outer = PopupLayout.GlowExtent(dot), reach = GlowReach(dot);
            return new[] {
                new[] { 0.0, Brand.GlowEdgeAlpha }, new[] { dot / outer, Brand.GlowEdgeAlpha },
                new[] { (dot + reach * Brand.GlowNearAt) / outer, Brand.GlowNearAlpha },
                new[] { (dot + reach * Brand.GlowFarAt) / outer, Brand.GlowFarAlpha },
                new[] { 1.0, 0.0 } };
        }

        /// The dot and its glow for a brand.glow frame (null: off); dimmed, the dot is its colour over the card (_light).
        private void Light(SurfacePainter paint, double cx, double cy, double dot, double scale, string fill, LightFrame frame)
        {
            double dim = frame != null ? frame.Dim : 0.0, opacity = frame != null ? frame.Opacity : 0.0;
            if (opacity > 0) paint.Glow(cx, cy, GlowRadius(dot, frame.Spread) * scale, GlowStops(dot), Rgb(fill), opacity);
            paint.FillCircle(cx, cy, dot * scale, Argb(fill, 1.0 - dim));
        }
    }
}
