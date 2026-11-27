// Codex Auto Resume - the icon's menu and its card, drawn (v0.6.27, S6.3).
//
// The C# port of ui/popup/menuwindow.py's MenuRenderer (menu_layout, draw_menu, _menu_words) and ui/tray/tipcard.py's
// TipRenderer drawing (tip_layout with the GDI font questions, draw_tip, draw_tip_light, _opaque_words), call for call.
// In the Python each is a subclass of the popup's Renderer; here each is a part of the one renderer's class, drawing
// with its colours, its corners, its ground items, its day and its light.
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;

namespace CodexAutoResume
{
    internal sealed partial class SurfaceRenderer
    {
        // ------------------------------------------------------------------ the menu (MenuRenderer)
        /// The menu's plan in `locale` at `scale`: mirrored when the language is written right to left (menu_layout).
        internal SurfacePlan MenuLayout(List<object> entries, double scale, string locale, int? maxWidth = null)
        {
            Use(locale, scale);
            return MenuPlan.Plan(entries, scale, locale, Text, maxWidth);
        }

        private void Clear(int width, int height)
        {
            SurfaceNative.GdiFlush();
            Marshal.Copy(new byte[width * height * 4], 0, Canvas.Bits, width * height * 4);
        }

        /// The whole menu into the canvas, premultiplied, transparent but for the card (draw_menu).
        internal SurfaceCanvas DrawMenu(SurfacePlan plan, int? selected = null)
        {
            int width = plan.Size[0], height = plan.Size[1];
            double scale = plan.Scale;
            double[] card = Box(plan.Card);
            Canvas.Ensure(width, height);
            Clear(width, height);
            UseScale(scale);
            int radius = SurfaceMath.Round(Radius("card") * scale);
            double pill = Radius("small") * scale;
            double hairline = Math.Max(1.0, SurfaceMath.Round(scale));
            using (var paint = new SurfacePainter(Canvas, SurfaceGdip.PixelFormat32bppPArgb))
            {
                uint ground = contrast ? Argb("surface") : Pack(SurfaceTheme.Rgb(CardGround()));
                paint.FillRound(card, radius, ground);
                paint.StrokeRound(card, radius, Argb("line"), hairline);
                foreach (PlanItem item in plan.Items)
                {
                    if (item.Kind == "rule")
                    {
                        paint.FillRound(Box(item["rect"]), 0, Argb("line"));
                        continue;
                    }
                    bool enabled = SurfaceMath.Truthy(item["enabled"]);
                    bool held = enabled && selected.HasValue && Convert.ToInt32(item["index"]) == selected.Value;
                    double[] rect = Box(item["rect"]);
                    if (held && contrast) paint.FillRound(rect, pill, Argb("accent"));
                    else if (held)
                    {
                        Lift(paint, "control", rect, pill, scale);
                        paint.FillRound(rect, pill, Argb("raised"));
                        paint.StrokeRound(rect, pill, Argb("line"), hairline);
                    }
                    if (SurfaceMath.Truthy(item["checked"]))
                    {
                        double[] dot = Box(item["dot"]);
                        string token = held && contrast ? "on_accent" : (enabled ? "accent" : "muted");
                        paint.FillCircle((dot[0] + dot[2]) / 2.0, (dot[1] + dot[3]) / 2.0, (dot[2] - dot[0]) / 2.0, Argb(token));
                    }
                }
            }
            MenuWords(plan, selected);
            return Canvas;
        }

        /// Each item's words in the body role, through GDI, and then each line's alpha put back whole (_menu_words).
        private void MenuWords(SurfacePlan plan, int? selected)
        {
            IntPtr dc = Canvas.Dc;
            SurfaceNative.SetBkMode(dc, SurfaceNative.TRANSPARENT);
            IntPtr previous = SurfaceNative.SelectObject(dc, Fonts.Handles["body"]);
            var drawn = new List<int[]>();
            bool rtl = plan.Rtl == true;
            try
            {
                foreach (PlanItem item in plan.Items)
                {
                    if (item.Kind != "item") continue;
                    bool enabled = SurfaceMath.Truthy(item["enabled"]);
                    bool held = enabled && selected.HasValue && Convert.ToInt32(item["index"]) == selected.Value;
                    string colour = !enabled ? "muted" : (held && contrast ? "on_accent" : "ink");
                    SurfaceNative.SetTextColor(dc, ColorRef(colour));
                    uint flags = SurfaceNative.DT_NOPREFIX | SurfaceNative.DT_SINGLELINE | SurfaceNative.DT_VCENTER | SurfaceNative.DT_END_ELLIPSIS;
                    if (rtl) flags |= SurfaceNative.DT_RIGHT | SurfaceNative.DT_RTLREADING;
                    double[] box = Box(item["text_rect"]);
                    int[] rect = { (int)box[0], (int)box[1], (int)box[2], (int)box[3] };
                    var area = new SurfaceNative.RECT(rect[0], rect[1], rect[2], rect[3]);
                    SurfaceNative.DrawTextW(dc, (string)item["text"], -1, ref area, flags);
                    drawn.Add(rect);
                    object arrow = item.Get("arrow");
                    if (SurfaceMath.Truthy(arrow))
                    {
                        double[] where = Box(arrow);
                        int[] at = { (int)where[0], (int)where[1], (int)where[2], (int)where[3] };
                        var arrowArea = new SurfaceNative.RECT(at[0], at[1], at[2], at[3]);
                        SurfaceNative.DrawTextW(dc, rtl ? "‹" : "›", -1, ref arrowArea,
                                                SurfaceNative.DT_NOPREFIX | SurfaceNative.DT_SINGLELINE | SurfaceNative.DT_VCENTER | SurfaceNative.DT_CENTER);
                        drawn.Add(at);
                    }
                }
            }
            finally
            {
                SurfaceNative.SelectObject(dc, previous);
                SurfaceNative.GdiFlush();
            }
            Opaque(drawn, false);
        }

        /// Every pixel of each rectangle made whole (alpha 255), as the Python's slices put b"\xff" back; `skipEmpty`
        /// leaves a rectangle with no width alone, as _opaque_words does (a slice of nothing is nothing either way).
        private void Opaque(List<int[]> rects, bool skipEmpty)
        {
            int width = Canvas.Width, height = Canvas.Height;
            byte[] pixels = Canvas.Pixels();
            foreach (int[] rect in rects)
            {
                int left = Math.Max(0, rect[0]), right = Math.Min(width, rect[2]);
                if (skipEmpty && right <= left) continue;
                for (int row = Math.Max(0, rect[1]); row < Math.Min(height, rect[3]); row++)
                {
                    int start = (row * width + left) * 4 + 3, stop = (row * width + right) * 4;
                    for (int at = start; at < stop; at += 4) pixels[at] = 0xFF;
                }
            }
            Marshal.Copy(pixels, 0, Canvas.Bits, pixels.Length);
        }

        // ------------------------------------------------------------------ the icon's card (TipRenderer)
        /// The card's plan in `locale` at `scale`, on `day`'s look or none, mirrored right to left (tip_layout).
        internal SurfacePlan TipLayout(Dictionary<string, object> parts, object light, double scale, string locale, string day = null)
        {
            Use(locale, scale);
            return TipPlan.Plan(parts, light, scale, locale, day, Text);
        }

        /// The day the card shows: `look`, but never in High Contrast nor in Classic (tip_day).
        internal static string TipDay(string look, bool contrast, string design)
        {
            return !string.IsNullOrEmpty(look) && !contrast && design != "classic" ? look : null;
        }

        /// The whole card into the canvas, premultiplied, transparent but for the card (draw_tip).
        internal SurfaceCanvas DrawTip(SurfacePlan plan, LightFrame frame = null)
        {
            int width = plan.Size[0], height = plan.Size[1];
            double scale = plan.Scale;
            Canvas.Ensure(width, height);
            Clear(width, height);
            UseScale(scale);
            PlanItem card = plan.Items[0];
            double radius = Corner(card, scale);
            using (var paint = new SurfacePainter(Canvas, SurfaceGdip.PixelFormat32bppPArgb))
            {
                uint ground = contrast ? Argb("surface") : Pack(SurfaceTheme.Rgb(CardGround()));
                paint.FillRound(Box(card["rect"]), radius, ground);
                paint.StrokeRound(Box(card["rect"]), radius, Argb("line"), Math.Max(1.0, SurfaceMath.Round(scale)));
                foreach (PlanItem item in plan.Items)
                    if (item.Kind == "chip" || item.Kind == "meter") GroundItem(paint, item, scale, null);
                Scene(paint, plan, 0.0);
            }
            DrawText(Canvas.Dc, plan, new List<object>());
            OpaqueWords(plan);
            KeepHaloBand(plan);
            return DrawTipLight(plan, frame, false);
        }

        /// Only the light, for one of its frames: the band of rows behind it put back, and the light drawn on it
        /// (draw_tip_light).
        internal SurfaceCanvas DrawTipLight(SurfacePlan plan, LightFrame frame, bool restore = true)
        {
            PlanItem item = HaloOf(plan);
            if (item == null) return Canvas;
            if (restore)
            {
                if (haloPlan != plan || haloBand == null) throw new ArgumentException("the whole card has to be drawn before its light");
                Marshal.Copy(haloBand, 0, Canvas.Bits + haloOffset, haloBand.Length);
            }
            using (var paint = new SurfacePainter(Canvas, SurfaceGdip.PixelFormat32bppPArgb)) Halo(paint, item, plan.Scale, frame);
            return Canvas;
        }

        /// GDI's text clears the alpha of what it touches: every line lies on the opaque card, so it is put back whole
        /// (_opaque_words).
        private void OpaqueWords(SurfacePlan plan)
        {
            SurfaceNative.GdiFlush();
            var rects = new List<int[]>();
            foreach (PlanItem item in plan.Items)
            {
                if (item.Kind != "text") continue;
                double[] box = Box(item["rect"]);
                rects.Add(new[] { (int)box[0], (int)box[1], (int)box[2], (int)box[3] });
            }
            Opaque(rects, true);
        }
    }
}
