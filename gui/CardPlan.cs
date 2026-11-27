// Codex Auto Resume - the notification card's drawing half: where everything goes, how it moves, where the stack
// stands and what its floating shadow is (v0.6.27, S6.3).
//
// Q1 (the owner's answer, 2026-11-26): C# owns the card's layout, motion, stack, shadow and corner; car-surface keeps
// what the watcher decides from (the view, the texts, presence, the inbox, the notifier). This is the C# port of
// src/codex_auto_resume/notice_card.py's half the owner gave C#, call for call: layout, ease_in, entrance, leaving,
// rise_vector, CardMotion, hold_ms, stack_direction, stack_positions, float_shadows, shadow_at, depth_level,
// shadow_margin, and ui/card/card.py's Card.fitting. The card's corner (corner_coverage, premultiply) is drawn with the
// window in CardWindow.cs. Pure: no Win32 here.
using System;
using System.Collections.Generic;
using System.Drawing;

namespace CodexAutoResume
{
    /// One frame of a card's life: its alpha, its offset toward the taskbar in dip, its scale and its shadow's depth.
    internal struct CardFrame
    {
        internal double Alpha, Offset, Scale, Depth;

        internal CardFrame(double alpha, double offset, double scale, double depth)
        {
            Alpha = alpha;
            Offset = offset;
            Scale = scale;
            Depth = depth;
        }

        internal static readonly CardFrame Settled = new CardFrame(1.0, 0.0, 1.0, 1.0);

        internal CardFrame WithAlpha(double alpha)
        {
            return new CardFrame(alpha, Offset, Scale, Depth);
        }
    }

    /// A shadow drawn over the wallpaper: offset, blur, colour (#RRGGBB) and alpha (FloatShadow).
    internal struct FloatShadow
    {
        internal double Dx, Dy, Blur, Alpha;
        internal string Colour;

        internal FloatShadow(double dx, double dy, double blur, string colour, double alpha)
        {
            Dx = dx;
            Dy = dy;
            Blur = blur;
            Colour = colour;
            Alpha = alpha;
        }
    }

    internal static class CardPlan
    {
        internal const int CardWidth = PopupLayout.Width - 2 * Brand.SpaceM;
        internal const int MaxCards = 3;
        internal const int FrameMs = 16;
        internal const int EntranceMs = 340, ExitMs = 220, SlideMs = 280, SwapMs = 130, StackDelayMs = 120;
        internal const int HoldMs = 6000, HoverGraceMs = 1500;
        internal const int Rise = 20;
        internal const double ScaleFrom = 0.98, AlphaShare = 0.35;
        internal const double DepthStartOffset = 0.35, DepthStartBlur = 0.55, DepthStartAlpha = 0.30;
        internal const int DepthLevels = 6;
        internal const string FloatShadowInk = "shadow_dark", FloatShadowTheme = "dark";
        internal const double DarkEnough = 0.05;
        internal const int UsualHeight = 240;
        /// The hold of a card that stays until it is clicked (UNTIL_CLICKED).
        internal const double UntilClicked = double.PositiveInfinity;

        private static object At(Dictionary<string, object> map, string key)
        {
            object value;
            return map != null && map.TryGetValue(key, out value) ? value : null;
        }

        private static PlanItem Text(double[] rect, string role, object value, string colour, bool wrap = false,
                                     string align = "left", object target = null)
        {
            var item = new PlanItem();
            item["kind"] = "text";
            item["rect"] = new[] { (int)rect[0], (int)rect[1], (int)rect[2], (int)rect[3] };
            item["role"] = role;
            item["text"] = value;
            item["colour"] = colour;
            item["wrap"] = wrap;
            item["align"] = align;
            item["target"] = target;
            return item;
        }

        /// Every rectangle the card draws, in device pixels, with the card at (0, 0) (notice_card.layout), mirrored
        /// right to left in the view's locale.
        internal static SurfacePlan Layout(Dictionary<string, object> vm, double scale, SurfaceText measure)
        {
            Func<double, int> px = value => SurfaceMath.Px(value, scale);
            int width = px(CardWidth);
            int pad = px(Brand.SpaceL);
            int left = pad, right = width - pad;
            int inner = right - left;
            var items = new List<PlanItem>();
            var targets = new List<KeyValuePair<object, int[]>>();
            int y = pad;

            // The header: the status light in the popup's mark box, the product, and the reason's chip.
            int mark = px(PopupLayout.Mark);
            int textLeft = left + mark + px(Brand.SpaceS);
            string product = At(vm, "product") as string;
            int productH = measure.Measure("label", product, inner, false)[1];
            int[] chipRect = null;
            int chipW = 0, chipH = 0;
            int chipPad = px(Brand.ChipPadX);
            bool hasChip = SurfaceMath.Truthy(At(vm, "chip"));
            if (hasChip)
            {
                int[] chipText = measure.Measure("chip", At(vm, "chip") as string, inner, false);
                int productW = measure.Measure("label", product, inner, false)[0];
                int room = right - (textLeft + productW + px(Brand.SpaceM));
                chipW = Math.Max(Math.Min(chipText[0] + 2 * chipPad, room), Math.Min(chipText[0] + 2 * chipPad, SurfaceMath.Div(inner, 3)));
                chipH = Math.Max(px(Brand.ChipHeight), chipText[1]);
            }
            int headerH = Math.Max(mark, Math.Max(productH, chipH));
            var halo = new PlanItem();
            halo["kind"] = "halo";
            halo["cx"] = left + mark / 2.0;
            halo["cy"] = y + headerH / 2.0;
            halo["state"] = At(vm, "status");
            halo["radius"] = PopupLayout.GlowExtent(PopupLayout.PopupDot) * scale;
            items.Add(halo);
            int productRight = right - (chipW != 0 ? chipW + px(Brand.SpaceS) : 0);
            int top = y + SurfaceMath.Div(headerH - productH, 2);
            items.Add(Text(new double[] { textLeft, top, productRight, top + productH }, "label", At(vm, "product"), "muted"));
            if (hasChip)
            {
                int chipTop = y + SurfaceMath.Div(headerH - chipH, 2);
                chipRect = new[] { right - chipW, chipTop, right, chipTop + chipH };
                var chip = new PlanItem();
                chip["kind"] = "chip";
                chip["rect"] = chipRect;
                chip["tone"] = At(vm, "chip_tone");
                items.Add(chip);
                items.Add(Text(new double[] { chipRect[0] + chipPad, chipRect[1], chipRect[2] - chipPad, chipRect[3] }, "chip",
                               At(vm, "chip"), At(vm, "chip_tone") as string, false, "center"));
            }
            y += headerH + px(Brand.SpaceS);
            if (SurfaceMath.Truthy(At(vm, "scene")))
            {
                int edge = Math.Max(1, px(1));
                int productW = measure.Measure("label", product, inner, false)[0];
                PlanItem band = PopupLayout.DayBand((string)vm["scene"], scale, edge, edge, width - edge, y - px(2), textLeft + productW);
                if (band != null) items.Add(band);
            }

            // The notice itself, as a task tile: its name, why, and exactly which conversation.
            int tilePad = px(Brand.SpaceM);
            int tileTop = y;
            int x0 = left + tilePad, x1 = right - tilePad;
            int content = x1 - x0;
            int lineY = tileTop + tilePad;
            int titleH = measure.Measure("name", At(vm, "title") as string, content, false)[1];
            items.Add(Text(new double[] { x0, lineY, x1, lineY + titleH }, "name", At(vm, "title"), "ink"));
            lineY += titleH + px(Brand.SpaceXs);
            if (SurfaceMath.Truthy(At(vm, "line")))
            {
                int lineH = measure.Measure("body", (string)vm["line"], content, true)[1];
                items.Add(Text(new double[] { x0, lineY, x1, lineY + lineH }, "body", vm["line"], "ink", true));
                lineY += lineH + px(Brand.SpaceXs);
            }
            if (SurfaceMath.Truthy(At(vm, "origin")))
            {
                int originH = measure.Measure("small", (string)vm["origin"], content, true)[1];
                items.Add(Text(new double[] { x0, lineY, x1, lineY + originH }, "small", vm["origin"], "muted", true));
                lineY += originH;
            }
            int tileBottom = lineY + tilePad;
            var panel = new PlanItem();
            panel["kind"] = "panel";
            panel["rect"] = new[] { left, tileTop, right, tileBottom };
            items.Add(panel);
            y = tileBottom;

            // The toast's buttons: side by side when both labels fit on one line, stacked when either would not.
            var actions = At(vm, "actions") as List<object> ?? new List<object>();
            if (actions.Count > 0)
            {
                y += px(Brand.SpaceM);
                int buttonH = px(Brand.ButtonHeight);
                int buttonPad = px(Brand.SpaceM);
                int half = SurfaceMath.Div(inner - px(Brand.SpaceS), 2);
                int widest = int.MinValue;
                foreach (object action in actions)
                    widest = Math.Max(widest, measure.Measure("button", At((Dictionary<string, object>)action, "label") as string, inner, false)[0]);
                var placed = new List<KeyValuePair<int[], bool>>();
                if (actions.Count == 1)
                {
                    placed.Add(new KeyValuePair<int[], bool>(new[] { right - half, y, right, y + buttonH }, false));
                    y += buttonH;
                }
                else if (actions.Count == 2 && widest + 2 * buttonPad <= half)
                {
                    placed.Add(new KeyValuePair<int[], bool>(new[] { left, y, left + half, y + buttonH }, false));
                    placed.Add(new KeyValuePair<int[], bool>(new[] { right - half, y, right, y + buttonH }, false));
                    y += buttonH;
                }
                else
                {
                    for (int index = 0; index < actions.Count; index++)
                    {
                        var action = (Dictionary<string, object>)actions[index];
                        int labelH = measure.Measure("button", At(action, "label") as string, inner - 2 * buttonPad, true)[1];
                        int height = Math.Max(buttonH, labelH + 2 * px(Brand.SpaceS));
                        placed.Add(new KeyValuePair<int[], bool>(new[] { left, y, right, y + height }, true));
                        y += height + (index < actions.Count - 1 ? px(Brand.SpaceS) : 0);
                    }
                }
                for (int index = 0; index < actions.Count && index < placed.Count; index++)
                {
                    var action = (Dictionary<string, object>)actions[index];
                    int[] rect = placed[index].Key;
                    bool wrapped = placed[index].Value;
                    object target = SurfaceRender.TargetOf(At(action, "target"));
                    bool primary = SurfaceMath.Truthy(At(action, "primary"));
                    var button = new PlanItem();
                    button["kind"] = "button";
                    button["rect"] = rect;
                    button["primary"] = At(action, "primary");
                    button["busy"] = false;
                    button["target"] = target;
                    items.Add(button);
                    double[] labelRect;
                    if (wrapped)
                    {
                        int labelH = measure.Measure("button", At(action, "label") as string, rect[2] - rect[0] - 2 * buttonPad, true)[1];
                        int labelTop = rect[1] + SurfaceMath.Div(rect[3] - rect[1] - labelH, 2);
                        labelRect = new double[] { rect[0] + buttonPad, labelTop, rect[2] - buttonPad, labelTop + labelH };
                    }
                    else labelRect = new double[] { rect[0] + buttonPad, rect[1], rect[2] - buttonPad, rect[3] };
                    items.Add(Text(labelRect, "button", At(action, "label"), primary ? "on_accent" : "ink", wrapped, "center", target));
                    targets.Add(new KeyValuePair<object, int[]>(target, rect));
                }
            }
            y += pad;
            int[] card = { 0, 0, width, y };
            var cardItem = new PlanItem();
            cardItem["kind"] = "card";
            cardItem["rect"] = card;
            cardItem["radius"] = px(Brand.RadiusCard);
            cardItem["corner"] = "card";
            items.Insert(0, cardItem);
            var plan = new SurfacePlan();
            plan.Size = new[] { width, y };
            plan.Card = card;
            plan.Items = items;
            plan.Targets = targets;
            plan.Scale = scale;
            return PopupLayout.RightToLeft(At(vm, "locale") as string) ? PopupLayout.Mirror(plan) : plan;
        }

        // ------------------------------------------------------------------------------- motion

        /// easeInQuad, for leaving: it lingers a moment, then goes (ease_in).
        internal static double EaseIn(double progress)
        {
            double t = Math.Min(1.0, Math.Max(0.0, progress));
            return t * t;
        }

        /// The card `elapsedMs` into its entrance (entrance).
        internal static CardFrame Entrance(double elapsedMs, bool reduced = false)
        {
            if (reduced || elapsedMs >= EntranceMs) return CardFrame.Settled;
            double t = Math.Max(0.0, elapsedMs) / EntranceMs;
            double settle = Brand.Ease(t);
            return new CardFrame(Brand.Ease(t / AlphaShare), Rise * (1.0 - settle), ScaleFrom + (1.0 - ScaleFrom) * settle, settle);
        }

        /// The card's alpha `elapsedMs` into its exit, from `startAlpha` (leaving).
        internal static double Leaving(double elapsedMs, double startAlpha = 1.0, bool reduced = false, double duration = ExitMs)
        {
            if (reduced || elapsedMs >= duration) return 0.0;
            return startAlpha * (1.0 - EaseIn(Math.Max(0.0, elapsedMs) / duration));
        }

        /// Which way the entrance offset points: toward the taskbar (rise_vector).
        internal static int[] RiseVector(string edge)
        {
            switch (edge)
            {
                case "top": return new[] { 0, -1 };
                case "left": return new[] { -1, 0 };
                case "right": return new[] { 1, 0 };
            }
            return new[] { 0, 1 };
        }

        /// HOLD_MS, or Windows' own "dismiss notifications after" time when that is longer (hold_ms).
        internal static double HoldFor(object messageDurationMs)
        {
            if (messageDurationMs is double) return Math.Max(HoldMs, (double)messageDurationMs);
            if (messageDurationMs is int) return Math.Max(HoldMs, (int)messageDurationMs);
            return HoldMs;
        }

        // ------------------------------------------------------------------------------- the stack

        /// -1 when older cards stand above the newest one, +1 when below: away from the corner (stack_direction).
        internal static int StackDirection(string edge, int y, int height, int[] work)
        {
            if (edge == "top") return 1;
            if ((edge == "left" || edge == "right") && (y + height / 2.0) < (work[1] + work[3]) / 2.0) return 1;
            return -1;
        }

        /// Where the cards go, newest first, and the edge (stack_positions); only the cards that fit are placed.
        internal static List<int[]> StackPositions(List<int[]> sizes, int[] work, int[] monitor, int[] anchor, int gap,
                                                  int spacing, out string edge)
        {
            var positions = new List<int[]>();
            if (sizes.Count == 0)
            {
                edge = PopupPlace.TaskbarEdge(work, monitor, anchor);
                return positions;
            }
            int firstW = sizes[0][0], firstH = sizes[0][1];
            int[] at = PopupPlace.Place(new[] { firstW, firstH }, work, monitor, anchor, null, gap, out edge);
            int x0 = at[0], y0 = at[1];
            bool upward = StackDirection(edge, y0, firstH, work) < 0;
            positions.Add(new[] { x0, y0 });
            int edgeX = x0 + firstW;
            int y = y0;
            int previousH = firstH;
            for (int i = 1; i < sizes.Count; i++)
            {
                int width = sizes[i][0], height = sizes[i][1];
                int x = edge == "left" ? x0 : edgeX - width;
                y = upward ? y - spacing - height : y + previousH + spacing;
                if (y < work[1] + gap || y + height > work[3] - gap) break;
                x = PopupPlace.Clamp(x, work[0] + gap, work[2] - gap - width);
                positions.Add(new[] { x, y });
                previousH = height;
            }
            return positions;
        }

        // ------------------------------------------------------------------------------- the floating shadow

        /// Python's round(value, digits): the nearest multiple of 10^-digits, half to even, as the nearest double.
        internal static double RoundTo(double value, int digits)
        {
            double power = Math.Pow(10, digits);
            return Math.Round(value * power, MidpointRounding.ToEven) / power;
        }

        /// The card recipe's outer shadows as they may be drawn over a wallpaper (float_shadows): a light-coloured one
        /// redrawn in the near-black ink at the alpha that darkens white as much, a highlight dropped, an inset one left
        /// to the card. A design without depth floats none.
        internal static List<FloatShadow> FloatShadows(string theme, string design)
        {
            var found = new List<FloatShadow>();
            if (!Brand.DesignDepth(SurfaceTheme.DesignChoice(design))) return found;
            bool dark = theme == "dark";
            Color ink = SurfaceTheme.Token(FloatShadowInk, FloatShadowTheme, "soft");
            Color ground = SurfaceTheme.Token("canvas", theme, design);
            for (int index = 0; ; index++)
            {
                double dx, dy, blur, alpha;
                bool inset;
                Color tone;
                bool there = dark ? Brand.Dark.ElevationShadow("card", index, out dx, out dy, out blur, out alpha, out inset, out tone)
                                  : Brand.ElevationShadow("card", index, out dx, out dy, out blur, out alpha, out inset, out tone);
                if (!there) break;
                if (inset) continue;
                string token = tone.ToArgb() == (dark ? Brand.Dark.ShadowLight : Brand.ShadowLight).ToArgb() ? "shadow_light" : "shadow_dark";
                Color colour = SurfaceTheme.Token(token, theme, design);
                double luminance = SurfaceTheme.Luminance(colour);
                if (luminance >= SurfaceTheme.Luminance(ground)) continue;
                if (luminance <= DarkEnough)
                {
                    found.Add(new FloatShadow(dx, dy, blur, SurfaceTheme.Hex(colour), alpha));
                    continue;
                }
                double darkening = alpha * (1.0 - luminance) / (1.0 - SurfaceTheme.Luminance(ink));
                found.Add(new FloatShadow(dx, dy, blur, SurfaceTheme.Hex(ink), RoundTo(darkening, 4)));
            }
            return found;
        }

        /// The floating shadows at `depth`, 0 the entrance's start to 1 settled (shadow_at).
        internal static List<FloatShadow> ShadowAt(List<FloatShadow> shadows, double depth)
        {
            depth = Math.Min(1.0, Math.Max(0.0, depth));
            Func<double, double> toward = start => start + (1.0 - start) * depth;
            double offset = toward(DepthStartOffset), blur = toward(DepthStartBlur), alpha = toward(DepthStartAlpha);
            var found = new List<FloatShadow>();
            foreach (FloatShadow s in shadows)
                found.Add(new FloatShadow(s.Dx * offset, s.Dy * offset, s.Blur * blur, s.Colour, s.Alpha * alpha));
            return found;
        }

        /// Which of DEPTH_LEVELS pre-drawn shadow images stands for `depth` (depth_level).
        internal static int DepthLevel(double depth)
        {
            return SurfaceMath.Round(Math.Min(1.0, Math.Max(0.0, depth)) * (DepthLevels - 1));
        }

        /// How far the settled shadows reach past the card, in device pixels, three sigmas (shadow_margin).
        internal static int ShadowMargin(List<FloatShadow> shadows, double scale)
        {
            double reach = 0.0;
            foreach (FloatShadow s in shadows) reach = Math.Max(reach, Math.Max(Math.Abs(s.Dx), Math.Abs(s.Dy)) + 1.5 * s.Blur);
            return (int)Math.Ceiling(reach * scale) + 2;
        }

        /// The most of the work area one card may take at a text size, across and down (Card.ROOM).
        internal static readonly double[] Room = { 0.5, 0.5 };

        /// The text size the card is drawn at (Card.fitting): Windows' (`text`), but no larger than lets a card of the
        /// usual size grow into half the work area each way; 1 where nothing says.
        internal static double Fitting(double dpi, int[] work, object text)
        {
            if (!(text is double) || (double)text <= 1.0 || work == null) return 1.0;
            double scale = dpi / 96.0;
            double[] usual = { CardWidth * scale, UsualHeight * scale };
            double[] room = { (work[2] - work[0]) * Room[0], (work[3] - work[1]) * Room[1] };
            return SurfaceTheme.Fitting((double)text, usual, room);
        }
    }

    /// One card's life on a clock it is given: enter, hold, exit, gone (notice_card.CardMotion). No Win32 here.
    internal sealed class CardMotion
    {
        internal readonly bool Reduced;
        internal string Phase;
        internal double Since;
        internal readonly double HoldMs;
        internal double HoldLeft;
        internal bool Paused;
        internal double FromAlpha = 1.0;
        internal double ExitMs = CardPlan.ExitMs;
        internal bool Final;
        internal int[] Position;
        private int[][] slide;          // where a glide starts and ends, or null
        private double slideBegan;

        internal CardMotion(double nowMs, double holdMs = CardPlan.HoldMs, bool reduced = false, int[] position = null)
        {
            Reduced = reduced;
            Phase = Reduced ? "hold" : "enter";
            Since = nowMs;
            HoldMs = Math.Max(0.0, holdMs);
            HoldLeft = HoldMs;
            Position = position;
        }

        /// Begin the card's life at `nowMs`, once it is drawn and ready to show (restart).
        internal void Restart(double nowMs)
        {
            if ((Phase == "enter" || Phase == "hold") && !Final)
            {
                Phase = Reduced ? "hold" : "enter";
                Since = nowMs;
                HoldLeft = HoldMs;
            }
        }

        /// Start the entrance `ms` later (delay).
        internal void Delay(double ms)
        {
            if (Phase == "enter" && ms > 0) Since += ms;
        }

        private void Advance(double nowMs)
        {
            if (Phase == "enter" && nowMs - Since >= CardPlan.EntranceMs) { Phase = "hold"; Since = Since + CardPlan.EntranceMs; }
            if (Phase == "return" && nowMs - Since >= CardPlan.ExitMs) { Phase = "hold"; Since = Since + CardPlan.ExitMs; }
            if (Phase == "hold" && !Paused && nowMs - Since >= HoldLeft)
            {
                Phase = "exit";
                Since = Since + HoldLeft;
                FromAlpha = 1.0;
                HoldLeft = 0.0;
            }
            if (Phase == "exit" && (Reduced || nowMs - Since >= ExitMs)) Phase = "gone";
        }

        internal CardFrame Frame(double nowMs)
        {
            Advance(nowMs);
            double elapsed = nowMs - Since;
            if (Phase == "enter") return CardPlan.Entrance(elapsed, Reduced);
            if (Phase == "return")
            {
                double t = Brand.Ease(elapsed / CardPlan.ExitMs);
                return CardFrame.Settled.WithAlpha(FromAlpha + (1.0 - FromAlpha) * t);
            }
            if (Phase == "exit") return CardFrame.Settled.WithAlpha(CardPlan.Leaving(elapsed, FromAlpha, Reduced, ExitMs));
            if (Phase == "gone") return CardFrame.Settled.WithAlpha(0.0);
            return CardFrame.Settled;
        }

        internal bool Gone { get { return Phase == "gone"; } }

        /// Hold still while somebody points at the stack; count down again when they stop (pause).
        internal void Pause(double nowMs, bool paused)
        {
            Advance(nowMs);
            if (paused == Paused) return;
            if (paused)
            {
                if (Phase == "hold")
                {
                    HoldLeft = Math.Max(0.0, HoldLeft - (nowMs - Since));
                    Since = nowMs;
                }
                else if (Phase == "exit" && !Reduced && !Final)
                {
                    FromAlpha = Frame(nowMs).Alpha;
                    Phase = "return";
                    Since = nowMs;
                    HoldLeft = 0.0;
                }
            }
            else if (Phase == "hold" || Phase == "return")
            {
                if (Phase == "hold") Since = nowMs;
                HoldLeft = Math.Max(HoldLeft, CardPlan.HoverGraceMs);
            }
            Paused = paused;
        }

        /// Leave now and for good: a newer card needs the place, or it was clicked (retire).
        internal void Retire(double nowMs, bool quick = false)
        {
            Advance(nowMs);
            Final = true;
            if (Phase == "gone") return;
            if (Phase == "exit")
            {
                if (quick && ExitMs > CardPlan.SwapMs)
                {
                    FromAlpha = Frame(nowMs).Alpha;
                    Since = nowMs;
                    ExitMs = CardPlan.SwapMs;
                }
                return;
            }
            FromAlpha = Phase == "enter" && nowMs < Since ? 0.0 : Frame(nowMs).Alpha;
            Phase = "exit";
            Since = nowMs;
            Paused = false;
            ExitMs = quick ? CardPlan.SwapMs : CardPlan.ExitMs;
            if (Reduced) Phase = "gone";
        }

        /// Glide to a new place in the stack, starting `delay` ms from now, or jump there (move_to).
        internal void MoveTo(double nowMs, int[] target, double delay = 0)
        {
            target = (int[])target.Clone();
            if (Position == null || Reduced)
            {
                Position = target;
                slide = null;
                return;
            }
            int[] current = Place(nowMs);
            if (current[0] == target[0] && current[1] == target[1] && current.Length == target.Length)
            {
                slide = null;
                Position = target;
                return;
            }
            slide = new[] { current, target };
            slideBegan = nowMs + Math.Max(0, delay);
            Position = target;
        }

        /// Where the card stands now (place).
        internal int[] Place(double nowMs)
        {
            if (slide == null) return Position;
            int[] start = slide[0], target = slide[1];
            double t = (nowMs - slideBegan) / CardPlan.SlideMs;
            if (t >= 1.0)
            {
                slide = null;
                return target;
            }
            double settle = Brand.Ease(t);
            var at = new int[Math.Min(start.Length, target.Length)];
            for (int i = 0; i < at.Length; i++) at[i] = SurfaceMath.Round(start[i] + (target[i] - start[i]) * settle);
            return at;
        }

        /// Whether a frame timer has anything to draw for this card now (moving).
        internal bool Moving(double nowMs)
        {
            Advance(nowMs);
            if (slide != null && nowMs - slideBegan < CardPlan.SlideMs) return true;
            return (Phase == "enter" || Phase == "exit" || Phase == "return") && !Reduced;
        }

        /// How long nothing will change, when nothing is moving: the rest of the hold, or null (wait_ms).
        internal double? WaitMs(double nowMs)
        {
            Advance(nowMs);
            if (Phase == "hold" && !Paused && !double.IsInfinity(HoldLeft)) return Math.Max(0.0, HoldLeft - (nowMs - Since));
            return null;
        }
    }
}
