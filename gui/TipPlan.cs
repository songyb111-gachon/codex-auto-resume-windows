// Codex Auto Resume - where everything on the icon's own tooltip card goes (v0.6.27, S6.3).
//
// The C# port of src/codex_auto_resume/ui/tray/tipplan.py, call for call: tip_layout, tip_anchor and tip_text, and the
// part of TipRenderer.tip_layout (ui/tray/tipcard.py) that measures and mirrors. Pure: a function of the parts (the
// tooltip's words, ui/tray/words.py tooltip_parts, as the core gives them), the light, the scale and a way to measure
// text, returning rectangles in the popup renderer's items; the window that shows the card is TipCard.cs.
using System;
using System.Collections.Generic;
using System.Text;

namespace CodexAutoResume
{
    internal static class TipPlan
    {
        internal const int TipMost = 360;
        internal const int TipPadY = 13, TipPadX = 16;
        internal const int TipGap = 8;
        internal const int TipMark = 14;
        internal const int TipBar = 6;
        internal const int TipBarLeast = 72;
        internal const string TipJoin = " · ";

        /// The roles each line is set in (TIP_ROLES).
        internal const string RoleTitle = "name", RoleChip = "chip", RoleLine = "body", RoleMeter = "small";

        /// A role's (ascent, x-height) where no font answers: by the line box (_line_box).
        private static double[] LineBox(int height)
        {
            return new[] { height * 3 / 4.0, height / 2.0 };
        }

        private static object At(Dictionary<string, object> map, string key)
        {
            object value;
            return map != null && map.TryGetValue(key, out value) ? value : null;
        }

        private static PlanItem Text(int[] rect, string role, object value, string colour, bool wrap = false, string align = "left")
        {
            var item = new PlanItem();
            item["kind"] = "text";
            item["rect"] = rect;
            item["role"] = role;
            item["text"] = value;
            item["colour"] = colour;
            item["wrap"] = wrap;
            item["align"] = align;
            item["target"] = null;
            return item;
        }

        private sealed class Run
        {
            internal object Value;
            internal string Colour;
            internal int Width;
        }

        /// Every rectangle of the card in device pixels, left to right, and its size (tip_layout). `metrics` and `ink`
        /// are the renderer's font questions, or null where there are none (the line boxes, and no bearings).
        internal static SurfacePlan Layout(Dictionary<string, object> parts, object light, double scale, SurfaceText measure,
                                           Func<string, double[]> metrics, string day, Func<string, string, int[]> ink)
        {
            Func<double, int> px = value => SurfaceMath.Px(value, scale);
            int padY = px(TipPadY), padX = px(TipPadX), gap = px(Brand.SpaceS);
            int mark = px(TipMark);
            const int wide = 100000;

            object titleText = parts["title"];
            int[] title = measure.Measure(RoleTitle, titleText as string, wide, false);
            int titleW = title[0], titleH = title[1];
            object chip = At(parts, "edition");
            bool hasChip = SurfaceMath.Truthy(chip);
            int chipW = 0, chipH = 0, chipPad = 0, chipTextW = 0, chipTextH = 0;
            if (hasChip)
            {
                int[] chipText = measure.Measure(RoleChip, chip as string, wide, false);
                chipTextW = chipText[0];
                chipTextH = chipText[1];
                chipPad = px(Brand.ChipPadX);
                chipW = chipTextW + 2 * chipPad;
                chipH = Math.Max(px(Brand.ChipHeight), chipTextH);
            }
            double dot = PopupLayout.PopupDot * scale;
            int lead = SurfaceMath.Round(mark / 2.0 + dot) + gap;
            int[] bearings = ink != null ? ink(RoleTitle, titleText as string) : new[] { 0, 0 };
            int after = Math.Max(0, gap + bearings[0] - bearings[1]);
            int headNeed = lead + titleW + (hasChip ? after + chipW : 0);
            int most = px(TipMost);
            var pieces = new List<object>();
            object lineValue = At(parts, "line");
            if (SurfaceMath.Truthy(lineValue)) pieces.AddRange((List<object>)lineValue);
            int[] join = measure.Measure(RoleLine, TipJoin, wide, false);
            int joinW = join[0], lineH = join[1];
            var widths = new List<int>();
            foreach (object piece in pieces) widths.Add(measure.Measure(RoleLine, ((List<object>)piece)[0] as string, wide, false)[0]);
            int lineRoom = most - 2 * padX - lead;
            var lines = new List<List<Run>>();
            if (pieces.Count > 0)
            {
                var current = new List<Run>();
                int used = 0;
                for (int i = 0; i < pieces.Count; i++)
                {
                    var piece = (List<object>)pieces[i];
                    int pieceW = widths[i];
                    if (current.Count > 0 && used + joinW + pieceW > lineRoom)
                    {
                        lines.Add(current);
                        current = new List<Run>();
                        used = 0;
                    }
                    if (current.Count > 0)
                    {
                        current.Add(new Run { Value = TipJoin, Colour = "ink", Width = joinW });
                        used += joinW;
                    }
                    current.Add(new Run { Value = piece[0], Colour = SurfaceMath.Truthy(piece[1]) ? "accent" : "ink", Width = pieceW });
                    used += pieceW;
                }
                lines.Add(current);
            }
            int widest = 0;
            bool anyLine = false;
            foreach (List<Run> runs in lines)
            {
                int sum = 0;
                foreach (Run run in runs) sum += run.Width;
                int shown = Math.Min(lineRoom, sum);
                widest = anyLine ? Math.Max(widest, shown) : shown;
                anyLine = true;
            }
            int lineNeed = lead + (anyLine ? widest : 0);
            var rows = new List<object>();
            object meterValue = At(parts, "meter");
            if (SurfaceMath.Truthy(meterValue)) rows.AddRange((List<object>)meterValue);
            int labelW = 0, shareW = 0;
            bool firstRow = true;
            foreach (object entry in rows)
            {
                var row = (Dictionary<string, object>)entry;
                int labelMeasure = measure.Measure(RoleMeter, row["label"] as string, wide, false)[0];
                labelW = firstRow ? labelMeasure : Math.Max(labelW, labelMeasure);
                firstRow = false;
            }
            firstRow = true;
            foreach (object entry in rows)
            {
                var row = (Dictionary<string, object>)entry;
                int shareMeasure = measure.Measure(RoleMeter, row["percent"] as string, wide, false)[0];
                shareW = firstRow ? shareMeasure : Math.Max(shareW, shareMeasure);
                firstRow = false;
            }
            int meterNeed = rows.Count > 0 ? labelW + gap + px(TipBarLeast) + gap + shareW : 0;
            int width = Math.Min(most, Math.Max(headNeed, Math.Max(lineNeed, meterNeed)) + 2 * padX);
            int left = padX, right = width - padX;
            int inner = right - left;
            var items = new List<PlanItem>();

            // Row 1: the light, the name, the edition's chip - one line to the eye.
            int y = padY;
            int textLeft = left + lead;
            if (hasChip) chipW = Math.Min(chipW, SurfaceMath.Div(inner, 2));
            int titleRoom = right - textLeft - (hasChip ? after + chipW : 0);
            titleW = Math.Min(titleW, titleRoom);
            double[] titleMetrics = metrics != null ? metrics(RoleTitle) : LineBox(titleH);
            double ascent = titleMetrics[0], xHeight = titleMetrics[1];
            double baseline = ascent;
            double middle = baseline - xHeight / 2.0;
            int chipTop = 0, chipWordsTop = 0;
            if (hasChip)
            {
                double chipAscent = (metrics != null ? metrics(RoleChip) : LineBox(chipTextH))[0];
                chipTop = SurfaceMath.Round(middle - chipH / 2.0);
                chipWordsTop = SurfaceMath.Round(baseline - chipAscent);
            }
            var tops = new List<int> { 0, SurfaceMath.Round(middle - mark / 2.0) };
            var bottoms = new List<int> { titleH, SurfaceMath.Round(middle + mark / 2.0) };
            if (hasChip)
            {
                tops.Add(chipTop); tops.Add(chipWordsTop);
                bottoms.Add(chipTop + chipH); bottoms.Add(chipWordsTop + chipTextH);
            }
            int least = int.MaxValue, highest = int.MinValue;
            foreach (int value in tops) least = Math.Min(least, value);
            foreach (int value in bottoms) highest = Math.Max(highest, value);
            int shift = y - least;
            int headH = highest - least;
            var halo = new PlanItem();
            halo["kind"] = "halo";
            halo["cx"] = left + mark / 2.0;
            halo["cy"] = shift + middle;
            halo["state"] = light;
            halo["radius"] = PopupLayout.GlowExtent(PopupLayout.PopupDot) * scale;
            halo["sweep_reach"] = 0.0;
            items.Add(halo);
            int top = shift;
            items.Add(Text(new[] { textLeft, top, textLeft + titleW, top + titleH }, RoleTitle, titleText, "ink"));
            if (hasChip)
            {
                int chipLeft = textLeft + titleW + after;
                int[] rect = { chipLeft, shift + chipTop, chipLeft + chipW, shift + chipTop + chipH };
                var chipItem = new PlanItem();
                chipItem["kind"] = "chip";
                chipItem["rect"] = rect;
                chipItem["tone"] = "accent";
                items.Add(chipItem);
                int wordsTop = shift + chipWordsTop;
                items.Add(Text(new[] { rect[0] + chipPad, wordsTop, rect[2] - chipPad, wordsTop + chipTextH }, RoleChip, chip,
                               "accent", false, "center"));
            }
            y += headH;

            // Row 2: the state line under the name, as it was broken above, piece by piece.
            if (lines.Count > 0)
            {
                y += px(Brand.SpaceXs);
                int room = right - textLeft;
                foreach (List<Run> runs in lines)
                {
                    if (runs.Count == 1 && runs[0].Width > room)
                    {
                        int wrappedH = measure.Measure(RoleLine, runs[0].Value as string, room, true)[1];
                        items.Add(Text(new[] { textLeft, y, right, y + wrappedH }, RoleLine, runs[0].Value, runs[0].Colour, true));
                        y += wrappedH;
                        continue;
                    }
                    int x = textLeft;
                    foreach (Run run in runs)
                    {
                        items.Add(Text(new[] { x, y, Math.Min(right, x + run.Width), y + lineH }, RoleLine, run.Value, run.Colour));
                        x += run.Width;
                    }
                    y += lineH;
                }
            }

            // The advanced edition's meter: a row per window.
            if (rows.Count > 0)
            {
                y += px(Brand.SpaceS);
                int rowH = measure.Measure(RoleMeter, "Ag", wide, false)[1];
                int labelCol = Math.Min(labelW, SurfaceMath.Div(inner, 3));
                int barLeft = left + labelCol + gap, barRight = right - shareW - gap;
                int barH = Math.Max(2, px(TipBar));
                for (int index = 0; index < rows.Count; index++)
                {
                    var row = (Dictionary<string, object>)rows[index];
                    if (index > 0) y += px(Brand.SpaceXs);
                    items.Add(Text(new[] { left, y, left + labelCol, y + rowH }, RoleMeter, row["label"], "muted"));
                    int barTop = y + SurfaceMath.Div(rowH - barH, 2);
                    bool low = SurfaceMath.Truthy(At(row, "low"));
                    var meter = new PlanItem();
                    meter["kind"] = "meter";
                    meter["rect"] = new[] { barLeft, barTop, barRight, barTop + barH };
                    meter["fraction"] = row["fraction"];
                    meter["low"] = low;
                    items.Add(meter);
                    items.Add(Text(new[] { right - shareW, y, right, y + rowH }, RoleMeter, row["percent"], low ? "warning" : "ink",
                                   false, "right"));
                    y += rowH;
                }
            }

            y += padY;
            if (SurfaceMath.Truthy(day))
            {
                int edge = Math.Max(1, px(1));
                double unit = (y - 2 * edge) / Brand.DaySceneHeight;
                double focal = Brand.DaySceneWidth - PopupLayout.SceneFocus(day);
                width = right + px(Brand.DayWideGap) + px(2) + SurfaceMath.Div(px(Brand.DayWideFade), 2)
                      + -(int)Math.Floor(-focal * unit) + edge;
                PlanItem band = PopupLayout.DayBand(day, scale, edge, edge, width - edge, y - edge, right);
                if (band != null) items.Add(band);
            }
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
            plan.Scale = scale;
            plan.Rows = new List<KeyValuePair<object, int[]>>();
            return plan;
        }

        /// The card's plan in `locale` at `scale`, on `day`'s look or none, mirrored right to left, with the name's
        /// bearings read from the light (TipRenderer.tip_layout).
        internal static SurfacePlan Plan(Dictionary<string, object> parts, object light, double scale, string locale, string day,
                                         SurfaceText measure)
        {
            bool mirrored = PopupLayout.RightToLeft(locale);
            Func<string, string, int[]> ink = (role, text) =>
            {
                int[] found = measure.Calc.Ink(role, text);
                return mirrored ? new[] { found[1], found[0] } : found;
            };
            SurfacePlan laid = Layout(parts, light, scale, measure, measure.Calc.Metrics, day, ink);
            return mirrored ? PopupLayout.Mirror(laid) : laid;
        }

        /// The box the card stands beside, in screen pixels (tip_anchor): the icon's rectangle when the pointer or the
        /// shell's anchor point is on it; else the anchor point, else the pointer, else the rectangle, else null.
        internal static int[] Anchor(int[] icon, int[] point, int[] cursor)
        {
            Func<int[], int[], bool> on = (spot, rect) => spot != null && rect != null && rect[0] <= spot[0] && spot[0] < rect[2]
                                                          && rect[1] <= spot[1] && spot[1] < rect[3];
            if (icon != null && (on(cursor, icon) || on(point, icon))) return (int[])icon.Clone();
            foreach (int[] spot in new[] { point, cursor })
                if (spot != null) return new[] { spot[0], spot[1], spot[0] + 1, spot[1] + 1 };
            return icon != null ? (int[])icon.Clone() : null;
        }

        /// Every word the plan draws, in drawing order (tip_text).
        internal static string TipText(SurfacePlan plan)
        {
            var words = new List<string>();
            foreach (PlanItem item in plan.Items)
                if (item.Kind == "text") words.Add(PopupWords.Str(item["text"]));
            return string.Join(" ", words.ToArray());
        }
    }
}
