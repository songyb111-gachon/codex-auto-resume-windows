// Codex Auto Resume - what moves on the popup, and how far along it is (v0.6.27, S6.3).
//
// The C# port of src/codex_auto_resume/ui/popup/motion.py, call for call: the status light's frame (halo, which is
// brand.glow with the design's say), animates, opening, closing, the button faces (face_state, face_length,
// face_amount), mixed, and the switches' glides (glide_amount, next_glides). Every curve is brand's one ease
// (Brand.Ease, the same Newton-then-halving solve as brand.ease), every length brand.MOTION's.
using System;
using System.Collections.Generic;

namespace CodexAutoResume
{
    /// One frame of the status light (brand.glow's dictionary): how far the dot is drawn toward the card, the glow's
    /// opacity and spread, and the checking arc's start angle (null when it has none).
    internal sealed class LightFrame
    {
        internal double Dim, Opacity, Spread;
        internal double? Arc;

        internal Dictionary<string, object> ToMap()
        {
            return new Dictionary<string, object> { { "dim", Dim }, { "opacity", Opacity }, { "spread", Spread },
                                                    { "arc", Arc.HasValue ? (object)Arc.Value : null } };
        }
    }

    /// A switch's glide: when it started, and how far on it was and is going (0 off, 1 on).
    internal sealed class Glide
    {
        internal double Started, Begin, End;

        internal Glide(double started, double begin, double end)
        {
            Started = started;
            Begin = begin;
            End = end;
        }
    }

    internal static class PopupMotion
    {
        /// A one-shot glide's frames, in ms (GLIDE_FRAME_MS): an opening, a button's face.
        internal const int GlideFrameMs = 16;

        private static double Cycle(string state)
        {
            switch (state)
            {
                case "monitoring": return Brand.GlowMonitoringMs;
                case "waiting": return Brand.GlowWaitingMs;
                case "recovering": return Brand.GlowRecoveringMs;
                case "attention": return Brand.GlowAttentionMs;
                case "failed": return Brand.GlowFailedMs;
            }
            return 0;
        }

        /// The light at `fraction` of one breath, as (dim, spread) (brand.glow_phase).
        internal static double[] GlowPhase(double fraction)
        {
            double breath = 0.5 + 0.5 * SurfaceMath.Cos(2.0 * Math.PI * SurfaceMath.Mod(fraction, 1.0));
            double lit = SurfaceMath.Pow(Brand.GlowLow + (1.0 - Brand.GlowLow) * breath, 1.0 / Brand.GlowGamma);
            double floor = SurfaceMath.Pow(Brand.GlowLow, 1.0 / Brand.GlowGamma);
            double risen = (lit - floor) / (1.0 - floor);
            return new[] { 1.0 - lit, risen * risen };
        }

        /// The state dot's light for one frame, or null when it is off (motion.halo, brand.glow): the breathing states
        /// on their cycles, checking's arc, and in a design with no glow (Plain) the dim alone.
        internal static LightFrame Halo(string state, double elapsedMs, bool reduced, string design)
        {
            double? fraction = null, arc = null;
            double cycle = Cycle(state);
            if (cycle > 0)
            {
                if (!reduced) fraction = SurfaceMath.Mod(elapsedMs, cycle) / cycle;
            }
            else if (state == "checking")
                arc = reduced ? Brand.GlowArcStillAt : SurfaceMath.Mod(elapsedMs, Brand.GlowArcMs) / Brand.GlowArcMs * 360.0;
            else return null;
            double dim = 0.0, spread = 0.0;
            if (fraction.HasValue)
            {
                double[] phase = GlowPhase(fraction.Value);
                dim = phase[0];
                spread = phase[1];
            }
            if (!Brand.DesignGlow(design)) spread = 0.0;
            return new LightFrame { Dim = dim, Opacity = Brand.GlowPeak * spread, Spread = spread, Arc = arc };
        }

        /// Whether the frame timer should run at all (animates, brand.glow_moves).
        internal static bool Animates(string state, bool reduced)
        {
            return !reduced && (Cycle(state) > 0 || state == "checking");
        }

        /// (alpha 0 to 255, how far below its place, whether it has arrived) `elapsedMs` into an opening `rise` px below.
        internal static int[] Opening(double elapsedMs, int rise)
        {
            double progress = Math.Max(0.0, elapsedMs) / Brand.TransitionMs;
            if (progress >= 1.0) return new[] { 255, 0, 1 };
            double eased = Brand.Ease(progress);
            return new[] { SurfaceMath.Round(255 * eased), SurfaceMath.Round(rise * (1.0 - eased)), 0 };
        }

        /// (alpha, whether it has gone) `elapsedMs` into a fade-out from `alpha`, in brand's press time.
        internal static int[] Closing(double elapsedMs, int alpha)
        {
            double progress = Math.Max(0.0, elapsedMs) / Brand.TransitionPressMs;
            if (progress >= 1.0) return new[] { 0, 1 };
            return new[] { SurfaceMath.Round(alpha * (1.0 - Brand.Ease(progress))), 0 };
        }

        /// What a laid-out button shows now (face_state): busy, pressed, hover or rest.
        internal static string FaceState(PlanItem item, object hover, object pressed)
        {
            object target = item["target"];
            if (SurfaceMath.Truthy(item.Get("busy"))) return "busy";
            if (Equals(pressed, target)) return "pressed";
            if (Equals(hover, target)) return "hover";
            return "rest";
        }

        /// How long a face takes from `before` to `after` (face_length): a press or its release brand's press time.
        internal static int FaceLength(string before, string after)
        {
            return before == "pressed" || after == "pressed" ? Brand.TransitionPressMs : Brand.TransitionMs;
        }

        /// (how far from the face it left toward the state's, eased; whether it is over) at `nowMs` (face_amount).
        internal static double[] FaceAmount(double started, double length, double nowMs)
        {
            double progress = (nowMs - started) / Math.Max(1.0, length);
            if (progress >= 1.0) return new[] { 1.0, 1.0 };
            return new[] { Brand.Ease(Math.Max(0.0, progress)), 0.0 };
        }

        /// (red, green, blue) `amount` of the way from `one` to `other` (mixed).
        internal static int[] Mixed(int[] one, int[] other, double amount)
        {
            var found = new int[Math.Min(one.Length, other.Length)];
            for (int i = 0; i < found.Length; i++) found[i] = SurfaceMath.Round(one[i] + (other[i] - one[i]) * amount);
            return found;
        }

        /// (how far on the switch is, whether the glide is over) at `nowMs`, eased (glide_amount).
        internal static double[] GlideAmount(Glide glide, double nowMs)
        {
            double progress = (nowMs - glide.Started) / Brand.TransitionMs;
            if (progress >= 1.0) return new[] { glide.End, 1.0 };
            return new[] { glide.Begin + (glide.End - glide.Begin) * Brand.Ease(progress), 0.0 };
        }

        /// The glides running after a switch table `seen` ({target: checked}) replaced `previous` (next_glides): one
        /// still heading where its switch is drawn keeps going; a switch drawn the other way starts one from where it
        /// is. `previous` null (the window has just opened) starts none; `animate` false stops them all.
        internal static Dictionary<object, Glide> NextGlides(Dictionary<object, bool> seen, Dictionary<object, bool> previous,
                                                            Dictionary<object, Glide> glides, double nowMs, bool animate = true)
        {
            var running = new Dictionary<object, Glide>();
            if (!animate) return running;
            foreach (KeyValuePair<object, bool> pair in seen)
            {
                double end = pair.Value ? 1.0 : 0.0;
                Glide glide;
                glides.TryGetValue(pair.Key, out glide);
                if (glide != null && glide.End == end)
                {
                    running[pair.Key] = glide;
                    continue;
                }
                bool before;
                if (previous == null || !previous.TryGetValue(pair.Key, out before) || before == pair.Value) continue;
                double begin = glide != null ? GlideAmount(glide, nowMs)[0] : 1.0 - end;
                running[pair.Key] = new Glide(nowMs, begin, end);
            }
            return running;
        }
    }
}
