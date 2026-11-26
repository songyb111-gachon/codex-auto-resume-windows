// Codex Auto Resume - where every piece of the popup goes, in one pass (v0.6.27, S6.3).
//
// The C# port of src/codex_auto_resume/ui/popup/layout.py, call for call: `layout` (Layout), `mirror` (Mirror) and
// `share_columns` (ShareColumns), with brand's day_band and glow_extent, which every surface the tray draws asks. A pure
// function of the view model, the scale and a way to measure text: it returns rectangles and paints nothing, so the
// plan can be compared with the reference's at every language and scale with no screen (tests/test_surface_parity.py).
//
// A plan is what the Python's is: a SurfacePlan whose items are PlanItems, each a dictionary of the very keys the Python
// item has, in the same order, so the renderer, the hit tests, the accessible objects and the dump read them by the
// Python's names. Rectangles are int[4] (left, top, right, bottom), the halo's centre and reach doubles, a target a
// SurfaceTarget. The arithmetic is Python's: `//` floors (SurfaceMath.Div), round() rounds half to even, int() of a
// float truncates.
using System;
using System.Collections.Generic;

namespace CodexAutoResume
{
    /// Python's arithmetic, where it differs from C#'s.
    internal static class SurfaceMath
    {
        /// a // b: floored, not truncated.
        internal static int Div(int a, int b)
        {
            int quotient = a / b;
            if ((a % b != 0) && ((a < 0) != (b < 0))) quotient--;
            return quotient;
        }

        /// a % b with the sign of b, for doubles (Python's float %).
        internal static double Mod(double a, double b)
        {
            double r = a % b;
            if (r != 0 && ((r < 0) != (b < 0))) r += b;
            return r;
        }

        /// int(round(value)): half to even, as Python 3 rounds.
        internal static int Round(double value)
        {
            return (int)Math.Round(value, MidpointRounding.ToEven);
        }

        /// The layouts' px(): device pixels for a size in device-independent pixels at `scale`.
        internal static int Px(double value, double scale)
        {
            return Round(value * scale);
        }

        /// Python's truth of a JSON value: None, False, 0, "" and an empty list or object are false.
        internal static bool Truthy(object value)
        {
            if (value == null) return false;
            if (value is bool) return (bool)value;
            if (value is string) return ((string)value).Length > 0;
            if (value is double) return (double)value != 0;
            if (value is int) return (int)value != 0;
            var list = value as System.Collections.ICollection;
            if (list != null) return list.Count > 0;
            return true;
        }

        /// `a or b`: a when it is true, else b.
        internal static object Or(object a, object b)
        {
            return Truthy(a) ? a : b;
        }
    }

    /// What a press or a key reaches: a name and, for a row or a card's button, its key - ("check", id), ("toggle",),
    /// ("action", index) - as the Python's tuples are. Equal by value, as tuples are.
    internal sealed class SurfaceTarget : IEquatable<SurfaceTarget>
    {
        internal readonly string Name;
        internal readonly object Key;
        internal readonly bool Keyed;

        internal SurfaceTarget(string name)
        {
            Name = name;
        }

        internal SurfaceTarget(string name, object key)
        {
            Name = name;
            Key = key;
            Keyed = true;
        }

        public bool Equals(SurfaceTarget other)
        {
            return other != null && other.Name == Name && other.Keyed == Keyed && Equals(other.Key, Key);
        }

        public override bool Equals(object other)
        {
            return Equals(other as SurfaceTarget);
        }

        public override int GetHashCode()
        {
            return (Name ?? "").GetHashCode() ^ (Key == null ? 0 : Key.GetHashCode());
        }

        /// The tuple as a JSON list: [name] or [name, key].
        internal List<object> ToList()
        {
            var list = new List<object> { Name };
            if (Keyed) list.Add(Key);
            return list;
        }
    }

    /// One thing a plan draws: the Python item's keys and values, in the Python's order.
    internal sealed class PlanItem : Dictionary<string, object>
    {
        internal PlanItem() { }

        internal PlanItem(IDictionary<string, object> other) : base(other) { }

        internal string Kind { get { return (string)this["kind"]; } }

        internal int[] Rect { get { return (int[])this["rect"]; } }

        internal object Get(string key)
        {
            object value;
            return TryGetValue(key, out value) ? value : null;
        }
    }

    /// A laid-out surface: its size, its card, its items in drawing order, its targets for hit testing and focus, the
    /// scale it was laid out at, the popup's rows (where a right click opens a row's menu) and whether it was mirrored.
    internal sealed class SurfacePlan
    {
        internal int[] Size;
        internal int[] Card;
        internal List<PlanItem> Items = new List<PlanItem>();
        internal List<KeyValuePair<object, int[]>> Targets = new List<KeyValuePair<object, int[]>>();
        internal double Scale;
        /// null where the Python's plan has no "rows" (the menu's, the tip's own has an empty one).
        internal List<KeyValuePair<object, int[]>> Rows;
        /// null where the Python's plan has no "rtl" key; the menu's has one from the start.
        internal bool? Rtl;

        internal SurfacePlan Copy()
        {
            var copy = (SurfacePlan)MemberwiseClone();
            copy.Items = new List<PlanItem>(Items);
            copy.Targets = new List<KeyValuePair<object, int[]>>(Targets);
            if (Rows != null) copy.Rows = new List<KeyValuePair<object, int[]>>(Rows);
            return copy;
        }
    }

    /// The popup's layout (ui/popup/layout.py), and brand's two answers every tray surface asks (day_band, glow_extent).
    internal static class PopupLayout
    {
        /// Device-independent pixels at 96 DPI: the card and 12 px around it (layout.WIDTH).
        internal const int Width = 360;
        /// The canvas kept round the card for its lift (SHADOW_MARGIN).
        internal const int ShadowMargin = 20;
        /// The box the state dot sits in, beside the product's name (MARK).
        internal const int Mark = 22;
        /// From a task's switch to the end of its label's column (SWITCH_GAP).
        internal const int SwitchGap = 10;
        /// The popup's status light, its radius in CSS px (brand.STATUS_DOT["popup"]).
        internal const double PopupDot = 4.5;

        /// The state line's colour by the header's word (STATE_INK); anything else is "ink".
        internal static string StateInk(object state)
        {
            switch (state as string)
            {
                case "monitoring": case "checking": case "recovering": return "accent";
                case "waiting": return "waiting";
                case "paused": return "paused";
                case "attention": return "warning";
            }
            return "ink";
        }

        /// The largest outer radius any frame of the light draws (brand.glow_extent = glow_radius(dot, 1.0)).
        internal static double GlowExtent(double dot)
        {
            return dot + (Brand.GlowReachOfRadius * dot) * 1.0;
        }

        /// Where a special day's scene focuses, from its left (brand.SCENE_FOCUS); a look it does not know raises, as
        /// the Python's dictionary does.
        internal static double SceneFocus(string look)
        {
            switch (look)
            {
                case "birthday": return 142.0;
                case "new_year": return 122.0;
                case "christmas": return 117.0;
                case "seollal": return 127.0;
                case "chuseok": return 126.0;
            }
            throw new KeyNotFoundException("no scene for " + look);
        }

        /// The day spread wide over a card's header (brand.day_band): the "scene" item, or null where the words leave
        /// too little room for the fade and a little of the day.
        internal static PlanItem DayBand(string look, double scale, double left, double top, double right, double bottom,
                                         double wordsEnd)
        {
            left = Math.Max(left, wordsEnd + SurfaceMath.Px(Brand.DayWideGap, scale));
            int fade = SurfaceMath.Px(Brand.DayWideFade, scale);
            if (right - left < SurfaceMath.Div(fade, 2) + SurfaceMath.Px(24, scale) || bottom <= top) return null;
            double unit = (bottom - top) / Brand.DaySceneHeight;
            double focal = Brand.DaySceneWidth - SceneFocus(look);
            double solid = left + SurfaceMath.Px(2, scale);
            int room = (int)(right - solid - focal * unit);
            bool scene = room >= SurfaceMath.Px(28, scale);
            var item = new PlanItem();
            item["kind"] = "scene";
            item["scene"] = look;
            item["rect"] = new double[] { left, top, right, bottom };
            item["unit"] = unit;
            item["scene_shown"] = scene;
            item["fade"] = new double[] { solid, solid + Math.Max(SurfaceMath.Px(2, scale),
                                                                  Math.Min(fade, scene ? room : right - solid - SurfaceMath.Px(24, scale))) };
            return item;
        }

        /// Widths for columns side by side in `available` pixels, one per need (share_columns).
        internal static int[] ShareColumns(int available, int[] needs)
        {
            int count = needs.Length;
            var need = new int[count];
            long total = 0;
            for (int i = 0; i < count; i++)
            {
                need[i] = Math.Max(0, needs[i]);
                total += need[i];
            }
            var result = new int[count];
            if (total > available)
            {
                for (int i = 0; i < count; i++) result[i] = (int)Math.Floor((double)((long)available * need[i]) / total);
                return result;
            }
            var fixedWidth = new Dictionary<int, int>();
            while (fixedWidth.Count < count)
            {
                var free = new List<int>();
                for (int i = 0; i < count; i++) if (!fixedWidth.ContainsKey(i)) free.Add(i);
                int used = 0;
                foreach (int value in fixedWidth.Values) used += value;
                int share = SurfaceMath.Div(available - used, free.Count);
                var wider = new List<int>();
                foreach (int i in free) if (need[i] > share) wider.Add(i);
                if (wider.Count == 0)
                {
                    for (int i = 0; i < count; i++) result[i] = fixedWidth.ContainsKey(i) ? fixedWidth[i] : share;
                    return result;
                }
                foreach (int i in wider) fixedWidth[i] = need[i];
            }
            return need;
        }

        private static PlanItem Text(int[] rect, string role, object value, string colour, bool wrap = false,
                                     string align = "left", object target = null)
        {
            var item = new PlanItem();
            item["kind"] = "text";
            item["rect"] = rect;
            item["role"] = role;
            item["text"] = value;
            item["colour"] = colour;
            item["wrap"] = wrap;
            item["align"] = align;
            item["target"] = target;
            return item;
        }

        private static PlanItem Item(string kind, int[] rect)
        {
            var item = new PlanItem();
            item["kind"] = kind;
            item["rect"] = rect;
            return item;
        }

        private static int[] R(int left, int top, int right, int bottom)
        {
            return new[] { left, top, right, bottom };
        }

        private static string S(object value)
        {
            return value as string;
        }

        private static object At(Dictionary<string, object> map, string key)
        {
            object value;
            return map != null && map.TryGetValue(key, out value) ? value : null;
        }

        /// Every rectangle the window draws, in device pixels, and the height it needs (layout.layout).
        internal static SurfacePlan Layout(Dictionary<string, object> vm, double scale, SurfaceText measure, int width = Width)
        {
            Func<double, int> px = value => SurfaceMath.Px(value, scale);
            int cardWidth = px(width) - 2 * px(Brand.SpaceM);
            int margin = px(ShadowMargin), pad = px(Brand.SpaceL);
            int total = cardWidth + 2 * margin;
            int left = margin + pad, right = total - margin - pad;
            int inner = right - left;
            var items = new List<PlanItem>();
            var targets = new List<KeyValuePair<object, int[]>>();
            var rows = new List<KeyValuePair<object, int[]>>();
            int y = margin + pad;

            // Header: the state dot, the product, the state in words.
            int mark = px(Mark);
            int textLeft = left + mark + px(Brand.SpaceS + 2);
            int textWidth = right - textLeft;
            int[] title = measure.Measure("title", S(vm["title"]), textWidth, false);
            int[] state = measure.Measure("state", S(vm["state_text"]), textWidth, true);
            int titleW = title[0], titleH = title[1], stateW = state[0], stateH = state[1];
            int stack = titleH + stateH;
            int headerH = Math.Max(mark, stack);
            int top = y + SurfaceMath.Div(headerH - stack, 2);
            var halo = new PlanItem();
            halo["kind"] = "halo";
            halo["cx"] = left + mark / 2.0;
            halo["cy"] = y + headerH / 2.0;
            halo["state"] = vm["light"];
            halo["radius"] = GlowExtent(PopupDot) * scale;
            halo["sweep_reach"] = Math.Min(mark / 2.0 + px(Brand.SpaceS), headerH / 2.0);
            items.Add(halo);
            items.Add(Item("title_press", R(textLeft, top, textLeft + titleW, top + titleH)));
            items.Add(Text(R(textLeft, top, right, top + titleH), "title", vm["title"], "ink"));
            items.Add(Text(R(textLeft, top + titleH, right, top + stack), "state", vm["state_text"], StateInk(vm["state"]), true));
            y += headerH + px(Brand.SpaceM);
            if (SurfaceMath.Truthy(At(vm, "scene")))
            {
                int edge = Math.Max(1, px(1));
                PlanItem scene = DayBand(S(vm["scene"]), scale, margin + edge, margin + edge, margin + cardWidth - edge,
                                         y - px(2), textLeft + Math.Max(titleW, stateW));
                if (scene != null) items.Add(scene);
            }

            // Summary: three values in one sunken well, a hairline between them.
            int wellTop = y;
            int wellPad = px(Brand.SpaceM);
            y += wellPad;
            int gutter = px(Brand.SpaceM);
            int available = inner - 2 * wellPad - 2 * gutter;
            var counts = (List<object>)vm["counts"];
            var needs = new int[counts.Count];
            for (int i = 0; i < counts.Count; i++)
            {
                var pair = (List<object>)counts[i];
                int need = int.MinValue;
                foreach (string piece in PopupWords.Unbroken(pair[0]))
                    need = Math.Max(need, measure.Measure("label", piece, available, false)[0]);
                need = Math.Max(need, measure.Measure("value", S(pair[1]), available, false)[0]);
                needs[i] = need;
            }
            int[] columns = ShareColumns(available, needs);
            int labelH = int.MinValue, valueH = int.MinValue;
            for (int i = 0; i < counts.Count; i++)
            {
                var pair = (List<object>)counts[i];
                labelH = Math.Max(labelH, measure.Measure("label", S(pair[0]), columns[i], true)[1]);
            }
            for (int i = 0; i < counts.Count; i++)
            {
                var pair = (List<object>)counts[i];
                valueH = Math.Max(valueH, measure.Measure("value", S(pair[1]), columns[i], false)[1]);
            }
            var countItems = new List<PlanItem>();
            int x = left + wellPad;
            for (int i = 0; i < counts.Count; i++)
            {
                var pair = (List<object>)counts[i];
                int column = columns[i];
                if (i > 0)
                {
                    int ruleX = x - SurfaceMath.Div(gutter, 2);
                    countItems.Add(Item("rule", R(ruleX, y + px(2), ruleX + Math.Max(1, px(1)), y + labelH + valueH)));
                }
                countItems.Add(Text(R(x, y, x + column, y + labelH), "label", pair[0], "muted", true));
                countItems.Add(Text(R(x, y + labelH + px(2), x + column, y + labelH + px(2) + valueH), "value", pair[1], "ink"));
                x += column + gutter;
            }
            y += labelH + px(2) + valueH + wellPad;
            items.Add(Item("well", R(left, wellTop, right, y)));
            items.AddRange(countItems);
            y += px(Brand.SpaceM);

            // The tasks, most urgent first.
            int rowPad = px(Brand.SpaceM);
            foreach (object entry in (List<object>)vm["tasks"])
            {
                var task = (Dictionary<string, object>)entry;
                var target = new SurfaceTarget("check", task["interruption_id"]);
                int rowTop = y;
                int x0 = left + rowPad, x1 = right - rowPad;
                int content = x1 - x0;
                var contents = new List<PlanItem>();
                int[] chipText = measure.Measure("chip", S(task["reason"]), content, false);
                int chipPad = px(Brand.ChipPadX);
                int chipW = Math.Min(chipText[0] + 2 * chipPad, SurfaceMath.Div(content, 2));
                int chipH = Math.Max(px(Brand.ChipHeight), chipText[1]);
                int nameW = content - chipW - px(Brand.SpaceS);
                int nameH = measure.Measure("name", S(task["name"]), nameW, false)[1];
                int lineH = Math.Max(nameH, chipH);
                int lineTop = rowTop + rowPad;
                int nameTop = lineTop + SurfaceMath.Div(lineH - nameH, 2);
                contents.Add(Text(R(x0, nameTop, x0 + nameW, nameTop + nameH), "name", task["name"], "ink"));
                int chipTop = lineTop + SurfaceMath.Div(lineH - chipH, 2);
                int[] chip = R(x1 - chipW, chipTop, x1, chipTop + chipH);
                PlanItem chipItem = Item("chip", chip);
                chipItem["tone"] = task["tone"];
                contents.Add(chipItem);
                contents.Add(Text(R(chip[0] + chipPad, chip[1], chip[2] - chipPad, chip[3]), "chip", task["reason"],
                                  S(task["tone"]), false, "center"));
                int line = lineTop + lineH + px(2);
                int statusH = measure.Measure("small", S(task["status"]), content, true)[1];
                contents.Add(Text(R(x0, line, x1, line + statusH), "small", task["status"], "muted", true));
                line += statusH + px(Brand.SpaceS) + px(2);
                int trackW = px(Brand.SwitchWidth), trackH = px(Brand.SwitchHeight);
                int trackLeft = x1 - trackW;
                int labelRight = trackLeft - px(SwitchGap);
                int checkLabelH = measure.Measure("body", S(task["check_label"]), labelRight - x0, true)[1];
                int bodyLineH = measure.Measure("body", "Ag", content, false)[1];
                int labelTop = line + Math.Max(0, SurfaceMath.Div(trackH - bodyLineH, 2));
                int trackTop = line + Math.Max(0, checkLabelH - bodyLineH) + Math.Max(0, SurfaceMath.Div(bodyLineH - trackH, 2));
                int checkH = Math.Max(trackTop + trackH, labelTop + checkLabelH) - line;
                contents.Add(Text(R(x0, labelTop, labelRight, labelTop + checkLabelH), "body", task["check_label"], "ink", true,
                                  "left", target));
                PlanItem toggle = Item("switch", R(trackLeft, trackTop, x1, trackTop + trackH));
                toggle["checked"] = task["checked"];
                toggle["busy"] = task["busy"];
                toggle["target"] = target;
                contents.Add(toggle);
                int[] hit = R(x0 - px(4), line - px(4), x1 + px(4), line + checkH + px(4));
                targets.Add(new KeyValuePair<object, int[]>(target, hit));
                int rowBottom = line + checkH + rowPad;
                items.Add(Item("panel", R(left, rowTop, right, rowBottom)));
                items.AddRange(contents);
                PlanItem focusable = Item("focusable", hit);
                focusable["target"] = target;
                focusable["radius"] = px(Brand.RadiusSmall);
                focusable["corner"] = "small";
                items.Add(focusable);
                rows.Add(new KeyValuePair<object, int[]>(task["interruption_id"], R(left, rowTop, right, rowBottom)));
                y = rowBottom + px(Brand.SpaceS);
            }

            if (SurfaceMath.Truthy(vm["more"]))
            {
                int moreH = measure.Measure("small", S(vm["more"]), inner, true)[1];
                items.Add(Text(R(left, y, right, y + moreH), "small", vm["more"], "muted", true, "center"));
                y += moreH + px(Brand.SpaceS);
            }

            object quiet = SurfaceMath.Or(vm["error"], vm["empty"]);
            if (SurfaceMath.Truthy(quiet))
            {
                int quietH = measure.Measure("body", S(quiet), inner - 2 * pad, true)[1];
                int block = quietH + 2 * pad;
                items.Add(Item("well", R(left, y, right, y + block)));
                items.Add(Text(R(left + pad, y + pad, right - pad, y + pad + quietH), "body", quiet, "muted", true, "center"));
                y += block + px(Brand.SpaceS);
            }

            foreach (object note in new[] { vm["zero_note"], At(vm, "observe_note"), At(vm, "usage_note") })
            {
                if (!SurfaceMath.Truthy(note)) continue;
                int noteH = measure.Measure("small", S(note), inner, true)[1];
                items.Add(Text(R(left, y, right, y + noteH), "small", note, "muted", true));
                y += noteH + px(Brand.SpaceS);
            }

            if (SurfaceMath.Truthy(vm["notice"]))
            {
                int inset = px(Brand.SpaceS);
                int noticeH = measure.Measure("small", S(vm["notice"]), inner - 2 * inset, true)[1];
                int block = noticeH + 2 * inset;
                PlanItem noteItem = Item("note", R(left, y, right, y + block));
                noteItem["tone"] = "warning";
                items.Add(noteItem);
                items.Add(Text(R(left + inset, y + inset, right - inset, y + inset + noticeH), "small", vm["notice"], "warning", true));
                y += block + px(Brand.SpaceS);
            }

            // Footer: Pause/Resume and Open Dashboard, side by side when both fit, stacked when either would not.
            y += px(Brand.SpaceXs);
            int buttonH = px(Brand.ButtonHeight);
            int buttonPad = px(Brand.SpaceM);
            string[] names = { "toggle", "dashboard" };
            object[] labels = { vm["toggle_text"], vm["dashboard_text"] };
            bool[] primary = { false, true };
            object[] busy = { vm["toggle_busy"], false };
            int half = SurfaceMath.Div(inner - px(Brand.SpaceS), 2);
            int widest = Math.Max(measure.Measure("button", S(labels[0]), inner, false)[0],
                                  measure.Measure("button", S(labels[1]), inner, false)[0]);
            var placed = new List<KeyValuePair<int[], bool>>();
            if (widest + 2 * buttonPad <= half)
            {
                placed.Add(new KeyValuePair<int[], bool>(R(left, y, left + half, y + buttonH), false));
                placed.Add(new KeyValuePair<int[], bool>(R(right - half, y, right, y + buttonH), false));
                y += buttonH;
            }
            else
            {
                for (int i = 0; i < 2; i++)
                {
                    int wrappedH = measure.Measure("button", S(labels[i]), inner - 2 * buttonPad, true)[1];
                    int height = Math.Max(buttonH, wrappedH + 2 * px(Brand.SpaceS));
                    placed.Add(new KeyValuePair<int[], bool>(R(left, y, right, y + height), true));
                    y += height + (i == 0 ? px(Brand.SpaceS) : 0);
                }
            }
            for (int i = 0; i < 2; i++)
            {
                int[] rect = placed[i].Key;
                bool wrapped = placed[i].Value;
                var target = new SurfaceTarget(names[i]);
                PlanItem button = Item("button", rect);
                button["primary"] = primary[i];
                button["busy"] = busy[i];
                button["target"] = target;
                items.Add(button);
                int[] labelRect;
                if (wrapped)
                {
                    int wrappedH = measure.Measure("button", S(labels[i]), rect[2] - rect[0] - 2 * buttonPad, true)[1];
                    int labelTop = rect[1] + SurfaceMath.Div(rect[3] - rect[1] - wrappedH, 2);
                    labelRect = R(rect[0] + buttonPad, labelTop, rect[2] - buttonPad, labelTop + wrappedH);
                }
                else labelRect = R(rect[0] + buttonPad, rect[1], rect[2] - buttonPad, rect[3]);
                items.Add(Text(labelRect, "button", labels[i], primary[i] ? "on_accent" : "ink", wrapped, "center", target));
                targets.Add(new KeyValuePair<object, int[]>(target, rect));
                PlanItem focusable = Item("focusable", rect);
                focusable["target"] = target;
                focusable["radius"] = px(Brand.RadiusControl);
                focusable["corner"] = "control";
                items.Add(focusable);
            }
            y += pad;
            int[] card = R(margin, margin, total - margin, y);
            PlanItem cardItem = Item("card", card);
            cardItem["radius"] = px(Brand.RadiusCard);
            cardItem["corner"] = "card";
            items.Insert(0, cardItem);
            var plan = new SurfacePlan();
            plan.Size = new[] { total, y + margin };
            plan.Card = card;
            plan.Items = items;
            plan.Targets = targets;
            plan.Scale = scale;
            plan.Rows = rows;
            return plan;
        }

        /// A rectangle across a canvas `width` wide from where it is.
        internal static int[] Across(int[] rect, int width)
        {
            return new[] { width - rect[2], rect[1], width - rect[0], rect[3] };
        }

        private static double[] Across(double[] rect, int width)
        {
            return new[] { width - rect[2], rect[1], width - rect[0], rect[3] };
        }

        /// The plan right to left (layout.mirror): every rectangle across the canvas, each item marked mirrored, every
        /// line aligned left aligned right, and the plan marked rtl. The card's light stays up and to the left.
        internal static SurfacePlan Mirror(SurfacePlan plan)
        {
            int width = plan.Size[0];
            var items = new List<PlanItem>();
            foreach (PlanItem original in plan.Items)
            {
                var item = new PlanItem(original);
                item["mirrored"] = true;
                if (item.ContainsKey("rect"))
                {
                    var ints = item["rect"] as int[];
                    if (ints != null) item["rect"] = Across(ints, width);
                    else item["rect"] = Across((double[])item["rect"], width);
                }
                if (item.ContainsKey("cx")) item["cx"] = width - (double)item["cx"];
                if (item.Kind == "text")
                {
                    string align = (string)item["align"];
                    item["align"] = align == "left" ? "right" : align == "right" ? "left" : align;
                }
                items.Add(item);
            }
            SurfacePlan mirrored = plan.Copy();
            mirrored.Items = items;
            mirrored.Card = Across(plan.Card, width);
            mirrored.Rtl = true;
            mirrored.Targets = new List<KeyValuePair<object, int[]>>();
            foreach (KeyValuePair<object, int[]> pair in plan.Targets)
                mirrored.Targets.Add(new KeyValuePair<object, int[]>(pair.Key, Across(pair.Value, width)));
            if (plan.Rows != null)
            {
                mirrored.Rows = new List<KeyValuePair<object, int[]>>();
                foreach (KeyValuePair<object, int[]> pair in plan.Rows)
                    mirrored.Rows.Add(new KeyValuePair<object, int[]>(pair.Key, Across(pair.Value, width)));
            }
            return mirrored;
        }

        /// Whether a surface in `locale` is drawn right to left (l10n.RIGHT_TO_LEFT).
        internal static bool RightToLeft(string locale)
        {
            return locale == "ar" || locale == "he" || locale == "fa";
        }

        /// The popup's plan in `locale` at `scale`, mirrored when the language is written right to left (Renderer.layout).
        internal static SurfacePlan Plan(Dictionary<string, object> vm, double scale, string locale, SurfaceText measure)
        {
            SurfacePlan laid = Layout(vm, scale, measure);
            return RightToLeft(locale) ? Mirror(laid) : laid;
        }
    }
}
