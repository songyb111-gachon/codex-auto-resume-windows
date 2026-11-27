// Codex Auto Resume - the icon's right-click menu as the popup draws it: where each item goes, where it opens, which key
// reaches what (v0.6.27, S6.3).
//
// The C# port of src/codex_auto_resume/ui/popup/menuplan.py, call for call: menu_layout, menu_mirror, menu_place,
// menu_beside, menu_numbered, the keys (menu_usable, menu_step, menu_end, menu_letter) and menu_accessible_items. Pure:
// it asks Windows nothing and paints nothing. The items - their words, order, states and what each does - are the
// icon's list (TrayMenu.cs), each a dictionary as Json.Parse gives it: id, text, enabled, checked, and items for a
// submenu; null for a line between groups. The window that draws it and hears the keys is MenuWindow.cs.
using System;
using System.Collections.Generic;
using System.Globalization;

namespace CodexAutoResume
{
    internal static class MenuPlan
    {
        /// The column at an item's start where a chosen item's dot is drawn (MENU_CHECK).
        internal const int MenuCheck = 24;
        /// The card's least width, in device-independent pixels (MENU_MIN_WIDTH).
        internal const int MenuMinWidth = 160;

        /// How far the cards' lift reaches past a card: three sigmas past the farthest offset of any theme's outer
        /// shadows, and 2 (menuplan._reach), from brand's card recipes in both themes.
        internal static readonly double MenuReach = Reach();

        private static double Reach()
        {
            double found = 0.0;
            bool any = false;
            for (int theme = 0; theme < 2; theme++)
            {
                for (int index = 0; ; index++)
                {
                    double dx, dy, blur, alpha;
                    bool inset;
                    System.Drawing.Color tone;
                    bool there = theme == 0 ? Brand.ElevationShadow("card", index, out dx, out dy, out blur, out alpha, out inset, out tone)
                                            : Brand.Dark.ElevationShadow("card", index, out dx, out dy, out blur, out alpha, out inset, out tone);
                    if (!there) break;
                    if (inset) continue;
                    double reach = Math.Max(Math.Abs(dx), Math.Abs(dy)) + 1.5 * blur;
                    found = any ? Math.Max(found, reach) : reach;
                    any = true;
                }
            }
            return (any ? found : 0.0) + 2;
        }

        private static object At(object entry, string key)
        {
            var map = entry as Dictionary<string, object>;
            object value;
            return map != null && map.TryGetValue(key, out value) ? value : null;
        }

        /// Every rectangle of the menu in device pixels, left to right, and the window's size (menu_layout).
        /// `maxWidth` (the work area's width) caps the window, or null.
        internal static SurfacePlan Layout(List<object> entries, double scale, SurfaceText measure, int? maxWidth = null)
        {
            Func<double, int> px = value => SurfaceMath.Px(value, scale);
            int margin = SurfaceMath.Round(MenuReach * scale);
            int pad = px(Brand.SpaceXs);
            int room = px(Brand.SpaceXs);
            int gap = Math.Max(1, px(1));
            int check = px(MenuCheck);
            int after = px(Brand.SpaceL);
            int hairline = Math.Max(1, px(1));
            int ruleH = px(Brand.SpaceS) + hairline;
            int lineH = measure.Measure("body", "Ag", 10000, false)[1];
            int itemH = lineH + 2 * room;
            int inner = px(MenuMinWidth) - 2 * pad;
            foreach (object entry in entries)
            {
                if (!SurfaceMath.Truthy(entry)) continue;
                int width = measure.Measure("body", At(entry, "text") as string, 10000, false)[0];
                inner = Math.Max(inner, check + width + after);
            }
            if (maxWidth.HasValue)
                inner = Math.Max(check + after + px(Brand.SpaceL), Math.Min(inner, maxWidth.Value - 2 * margin - 2 * pad));
            int left = margin + pad;
            int right = left + inner;
            var plan = new SurfacePlan();
            int y = margin + pad;
            for (int index = 0; index < entries.Count; index++)
            {
                object entry = entries[index];
                if (entry == null)
                {
                    int middle = y + SurfaceMath.Div(ruleH - hairline, 2);
                    int inset = px(Brand.SpaceS);
                    var rule = new PlanItem();
                    rule["kind"] = "rule";
                    rule["index"] = index;
                    rule["rect"] = new[] { left + inset, middle, right - inset, middle + hairline };
                    plan.Items.Add(rule);
                    y += ruleH;
                    continue;
                }
                y += gap;
                int[] rect = { left, y, right, y + itemH };
                int dot = Math.Max(px(6), SurfaceMath.Div(check, 4));
                int cx = left + SurfaceMath.Div(check, 2), cy = y + SurfaceMath.Div(itemH, 2);
                var laid = new PlanItem();
                laid["kind"] = "item";
                laid["index"] = index;
                laid["id"] = At(entry, "id");
                laid["text"] = At(entry, "text");
                laid["enabled"] = SurfaceMath.Truthy(At(entry, "enabled"));
                laid["checked"] = SurfaceMath.Truthy(At(entry, "checked"));
                laid["rect"] = rect;
                laid["text_rect"] = new[] { left + check, y, right - after, y + itemH };
                laid["dot"] = new[] { cx - SurfaceMath.Div(dot, 2), cy - SurfaceMath.Div(dot, 2),
                                      cx - SurfaceMath.Div(dot, 2) + dot, cy - SurfaceMath.Div(dot, 2) + dot };
                laid["align"] = "left";
                laid["submenu"] = SurfaceMath.Truthy(At(entry, "items"));
                if ((bool)laid["submenu"]) laid["arrow"] = new[] { right - after, y, right - pad, y + itemH };
                plan.Items.Add(laid);
                if (SurfaceMath.Truthy(At(entry, "enabled"))) plan.Targets.Add(new KeyValuePair<object, int[]>(index, rect));
                y += itemH + gap;
            }
            int bottom = y + pad;
            plan.Card = new[] { margin, margin, right + pad, bottom };
            plan.Size = new[] { plan.Card[2] + margin, bottom + margin };
            plan.Scale = scale;
            plan.Rtl = false;
            return plan;
        }

        /// The menu right to left (menu_mirror): every rectangle across the window, every line aligned right.
        internal static SurfacePlan Mirror(SurfacePlan plan)
        {
            int width = plan.Size[0];
            var items = new List<PlanItem>();
            foreach (PlanItem item in plan.Items)
            {
                var turned = new PlanItem(item);
                turned["rect"] = PopupLayout.Across(item.Rect, width);
                foreach (string key in new[] { "text_rect", "dot", "arrow" })
                    if (item.ContainsKey(key)) turned[key] = PopupLayout.Across((int[])item[key], width);
                if (item.ContainsKey("align")) turned["align"] = "right";
                items.Add(turned);
            }
            SurfacePlan mirrored = plan.Copy();
            mirrored.Items = items;
            mirrored.Card = PopupLayout.Across(plan.Card, width);
            mirrored.Rtl = true;
            mirrored.Targets = new List<KeyValuePair<object, int[]>>();
            foreach (KeyValuePair<object, int[]> pair in plan.Targets)
                mirrored.Targets.Add(new KeyValuePair<object, int[]>(pair.Key, PopupLayout.Across(pair.Value, width)));
            return mirrored;
        }

        /// The menu's plan in `locale` at `scale`, mirrored right to left (MenuRenderer.menu_layout).
        internal static SurfacePlan Plan(List<object> entries, double scale, string locale, SurfaceText measure, int? maxWidth)
        {
            SurfacePlan laid = Layout(entries, scale, measure, maxWidth);
            return PopupLayout.RightToLeft(locale) ? Mirror(laid) : laid;
        }

        private static int Keep(int value, int low, int high, int least)
        {
            return high - low >= least ? Math.Max(low, Math.Min(value, high - least)) : low;
        }

        /// Where the window goes, (x, y), for a menu opened at `point` on a monitor whose work area is `work` (menu_place).
        internal static int[] Place(SurfacePlan plan, int[] point, int[] work)
        {
            int[] card = plan.Card;
            int width = card[2] - card[0], height = card[3] - card[1];
            int left = work[0], top = work[1], right = work[2], bottom = work[3];
            int px = point[0], py = point[1];
            int x;
            if (plan.Rtl == true) x = px - width >= left ? px - width : px;
            else x = px + width <= right ? px : px - width;
            int y = py + height <= bottom ? py : py - height;
            x = Keep(x, left, right, width);
            y = Keep(y, top, bottom, height);
            return new[] { x - card[0], y - card[1] };
        }

        /// Where a submenu's window goes, (x, y): its card beside `beside` - the parent's card's left and right and its
        /// item's top and bottom, on the screen - its first item level with the parent's item (menu_beside).
        internal static int[] Beside(SurfacePlan plan, int[] beside, int[] work)
        {
            int[] card = plan.Card;
            int width = card[2] - card[0], height = card[3] - card[1];
            int left = work[0], top = work[1], right = work[2], bottom = work[3];
            int first = card[1];
            foreach (PlanItem item in plan.Items)
                if (item.Kind == "item") { first = item.Rect[1]; break; }
            int x;
            if (plan.Rtl == true) x = beside[0] - width >= left ? beside[0] - width : beside[2];
            else x = beside[2] + width <= right ? beside[2] : beside[0] - width;
            int y = beside[1] - (first - card[1]);
            x = Keep(x, left, right, width);
            y = Keep(y, top, bottom, height);
            return new[] { x - card[0], y - card[1] };
        }

        /// A row menu's entries numbered as both menus take them (menu_numbered): each item that does something numbered
        /// from 1, depth first - its id - and {number: action}, null for an item that cannot be used.
        internal static List<object> Numbered(List<object> entries, Dictionary<int, object> actions)
        {
            var found = new List<object>();
            foreach (object entry in entries)
            {
                if (entry == null)
                {
                    found.Add(null);
                    continue;
                }
                var copy = new Dictionary<string, object>((Dictionary<string, object>)entry);
                if (SurfaceMath.Truthy(At(entry, "items")))
                {
                    copy["id"] = null;
                    copy["items"] = Numbered((List<object>)At(entry, "items"), actions);
                    found.Add(copy);
                    continue;
                }
                int command = actions.Count + 1;
                actions[command] = SurfaceMath.Truthy(At(entry, "enabled")) ? At(entry, "action") : null;
                copy["id"] = command;
                copy["items"] = null;
                found.Add(copy);
            }
            return found;
        }

        // ---------------------------------------------------------------------------------------- keys

        /// The indexes of the items a key or a click can choose, in order: every enabled item, no line (menu_usable).
        internal static List<int> Usable(List<object> entries)
        {
            var usable = new List<int>();
            for (int index = 0; index < entries.Count; index++)
                if (entries[index] != null && SurfaceMath.Truthy(At(entries[index], "enabled"))) usable.Add(index);
            return usable;
        }

        /// The item an arrow reaches from `current` (menu_step), round from the end to the start; null when nothing can
        /// be used.
        internal static int? Step(List<object> entries, int? current, bool backwards = false)
        {
            List<int> usable = Usable(entries);
            if (usable.Count == 0) return null;
            if (!current.HasValue || !usable.Contains(current.Value)) return backwards ? usable[usable.Count - 1] : usable[0];
            int at = usable.IndexOf(current.Value) + (backwards ? -1 : 1);
            return usable[((at % usable.Count) + usable.Count) % usable.Count];
        }

        /// Home's item, or End's (menu_end); null when nothing can be used.
        internal static int? End(List<object> entries, bool last = false)
        {
            List<int> usable = Usable(entries);
            if (usable.Count == 0) return null;
            return last ? usable[usable.Count - 1] : usable[0];
        }

        /// What a typed character does (menu_letter): (index, chosen). One usable item starting with it is chosen;
        /// several are stepped through from `current`; none leaves the menu as it is. Case is not told apart.
        internal static KeyValuePair<int?, bool> Letter(List<object> entries, int? current, string character)
        {
            string wanted = Fold(character ?? "");
            if (GdiTextCalc.PyStrip(wanted).Length == 0) return new KeyValuePair<int?, bool>(current, false);
            var found = new List<int>();
            foreach (int index in Usable(entries))
            {
                object text = At(entries[index], "text");
                string words = LStrip(SurfaceMath.Truthy(text) ? PopupWords.Str(text) : "");
                List<string> points = PopupWords.CodePoints(words);
                if (Fold(points.Count > 0 ? points[0] : "") == wanted) found.Add(index);
            }
            if (found.Count == 0) return new KeyValuePair<int?, bool>(current, false);
            if (found.Count == 1) return new KeyValuePair<int?, bool>(found[0], true);
            foreach (int index in found)
                if (current.HasValue && index > current.Value) return new KeyValuePair<int?, bool>(index, false);
            return new KeyValuePair<int?, bool>(found[0], false);
        }

        /// str.casefold(), as far as .NET has one: the invariant lower case, with the German sharp s folded as Python
        /// folds it.
        private static string Fold(string text)
        {
            return text.ToLower(CultureInfo.InvariantCulture).Replace("ß", "ss");
        }

        private static string LStrip(string text)
        {
            List<string> points = PopupWords.CodePoints(text);
            int start = 0;
            while (start < points.Count && PopupWords.IsSpace(PopupWords.Code(points[start]))) start++;
            return string.Concat(points.GetRange(start, points.Count - start).ToArray());
        }

        // ---------------------------------------------------------------------------------------- a screen reader

        /// The menu's children for a screen reader, in the order drawn (menu_accessible_items): a menuitem per item, a
        /// separator per line.
        internal static List<Dictionary<string, object>> AccessibleItems(SurfacePlan plan, int? selected,
                                                                          IDictionary<string, object> strings)
        {
            var found = new List<Dictionary<string, object>>();
            if (plan == null) return found;
            foreach (PlanItem item in plan.Items)
            {
                var child = new Dictionary<string, object>();
                if (item.Kind == "rule")
                {
                    child["role"] = "separator"; child["name"] = ""; child["value"] = null; child["description"] = null;
                    child["states"] = new List<object>(); child["rect"] = item.Rect; child["target"] = null; child["action"] = null;
                    found.Add(child);
                    continue;
                }
                var states = new SortedSet<string>(StringComparer.Ordinal);
                bool enabled = (bool)item["enabled"];
                if ((bool)item["checked"]) states.Add("checked");
                if (SurfaceMath.Truthy(item.Get("submenu"))) states.Add("haspopup");
                if (enabled)
                {
                    states.Add("focusable");
                    if (selected.HasValue && (int)item["index"] == selected.Value) { states.Add("focused"); states.Add("hot"); }
                }
                else states.Add("unavailable");
                child["role"] = "menuitem"; child["name"] = item["text"]; child["value"] = null; child["description"] = null;
                child["states"] = new List<object>(states); child["rect"] = item.Rect;
                child["target"] = enabled ? item["index"] : null;
                child["action"] = enabled ? PopupWords.Say(strings, "popup.a11y_press") : null;
                found.Add(child);
            }
            return found;
        }
    }
}
