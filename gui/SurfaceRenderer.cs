// Codex Auto Resume - the one renderer of the popup, the menu, the tip and the card (v0.6.27, S6.3).
//
// The C# port of src/codex_auto_resume/ui/popup/renderer.py's Renderer, call for call. This file holds its look half
// so far: the theme, the design and High Contrast as the renderer adopts them, the corners each design rounds by
// (_radii, _corner, _control_radius, smoothing, _depth), and every colour it paints with (_tokens, _rgb, _argb,
// _colorref, face_colours), each resolved by a token's name exactly as the Python resolves it; and its drawing half
// (draw, _seal, draw_scene, _ground with its kept pixels, _scene and _scene_shape over gui/SurfaceDays.cs, _ground_item,
// _accent_bar, the shadow images, _lift, _inner, _well, _switch, _meter, _button and _text), over SurfaceGdip.cs's flat
// GDI+ and DrawTextW, in the Python's order of calls (Q8). The light is gui/SurfaceLight.cs, a part of this class as
// light.py is a part of the Python's.
using System;
using System.Collections.Generic;
using System.Drawing;
using System.Globalization;
using System.Runtime.InteropServices;
using System.Text;

namespace CodexAutoResume
{
    internal sealed partial class SurfaceRenderer : IDisposable
    {
        /// The system colours High Contrast draws with, by name; null asks Windows (system_rgb). A render job sets a
        /// fixed table, so a plan's paint in High Contrast is the same on every machine.
        internal static Dictionary<string, int[]> SystemColours { get; set; }

        /// The theme: "light" or "dark", as the window resolved it.
        internal string Theme = "light";

        private string design = "soft";
        private bool contrast;

        /// The design: one of brand's designs, as the window adopted it.
        internal string Design
        {
            get { return design; }
            set { design = value; CornersFollowTheLook(); }
        }

        /// High Contrast: system colours, and no shadow, tint or glow.
        internal bool Contrast
        {
            get { return contrast; }
            set { contrast = value; CornersFollowTheLook(); }
        }

        /// The card alone (v0.6.24): transparent round it, no lift.
        internal bool Lone { get; set; }

        /// The theme the colours come from: brand's name for it, light for anything unknown (_theme).
        internal string ThemeName()
        {
            return Theme == "light" || Theme == "dark" ? Theme : "light";
        }

        /// The design the drawing follows: brand's name for it, Soft for anything unknown (_design).
        internal string DesignName()
        {
            return Array.IndexOf(SurfaceTheme.Designs, design) >= 0 ? design : Brand.DesignDefault;
        }

        /// Whether anything is drawn with depth: the design has it and High Contrast is off (_depth).
        internal bool Depth()
        {
            return !contrast && Brand.DesignDepth(DesignName());
        }

        /// How much this look smooths its corners: its design's, Soft's in High Contrast (smoothing).
        internal double Smoothing()
        {
            return Brand.DesignSmoothing(contrast ? Brand.DesignDefault : DesignName());
        }

        /// The design's corner radius for a role, in CSS px - Soft's in High Contrast (_radii).
        internal int Radius(string role)
        {
            return Brand.DesignRadius(contrast ? Brand.DesignDefault : DesignName(), role);
        }

        /// A laid-out item's corner in the design, in device px (_corner); an item that names no role keeps the
        /// radius it was laid out with.
        internal double Corner(PlanItem item, double scale)
        {
            object role = item.Get("corner");
            if (role == null) return Convert.ToDouble(item["radius"]);
            return SurfaceMath.Round(Radius((string)role) * scale);
        }

        /// A control's corner in the design, in device px (_control_radius).
        internal double ControlRadius(double scale)
        {
            return Radius("control") * scale;
        }

        /// A token's colour as (red, green, blue): its system colour in High Contrast, else the design's palette in
        /// the theme (_rgb).
        internal int[] Rgb(string token)
        {
            if (contrast)
            {
                string name = SurfaceTheme.ContrastColour(token);
                int[] found;
                if (SystemColours != null && SystemColours.TryGetValue(name, out found)) return found;
                return SurfaceTheme.SystemRgb(name);
            }
            return SurfaceTheme.Rgb(SurfaceTheme.Token(token, ThemeName(), DesignName()));
        }

        /// The token as the ARGB number GDI+ takes (_argb).
        internal uint Argb(string token, double alpha = 1.0)
        {
            int[] rgb = Rgb(token);
            return SurfaceNative.Pack(rgb[0], rgb[1], rgb[2], alpha);
        }

        /// The token as a COLORREF, for GDI's text (_colorref).
        internal uint ColorRef(string token)
        {
            int[] rgb = Rgb(token);
            return (uint)(rgb[0] | (rgb[1] << 8) | (rgb[2] << 16));
        }

        /// ((fill), (edge)) as (red, green, blue): what a button looks like in `state` (face_colours).
        internal int[][] FaceColours(PlanItem item, string state)
        {
            bool primary = SurfaceMath.Truthy(item["primary"]);
            string fill, edge;
            if (state == "busy") { fill = "surface"; edge = "line"; }
            else if (state == "pressed") { fill = primary ? "accent_pressed" : "inset"; edge = primary ? "accent" : "line"; }
            else if (state == "hover") { fill = primary ? "accent_hover" : "surface"; edge = primary ? "accent_hover" : "line"; }
            else { fill = primary ? "accent" : "raised"; edge = primary ? "accent" : "line"; }
            return new[] { Rgb(fill), Rgb(edge) };
        }

        /// A button stands on the card unless it is pressed or busy (_lifted).
        internal static bool Lifted(PlanItem item, object pressed)
        {
            return !SurfaceMath.Truthy(item["busy"]) && !Equals(pressed, item["target"]);
        }

        // ------------------------------------------------------------------ the canvas and the fonts
        /// The canvas every frame is built in (null for a renderer that only resolves the look, as the plans' paint does).
        internal SurfaceCanvas Canvas;
        /// The locale's fonts at the scale the last plan was laid out at.
        internal SurfaceFontSet Fonts;
        /// What measures with those fonts (Renderer.measure and lines).
        internal SurfaceText Text;
        /// Every character the locale's words draw (typeface.letters of its catalog): the fonts' lacks rule. The core
        /// hands it with the strings; null is none.
        internal string Letters { get; set; }
        private bool acquired;

        /// A renderer that draws: GDI+ started for it and its own canvas (Renderer.__init__).
        internal static SurfaceRenderer Open()
        {
            SurfaceGdip.Acquire();
            var renderer = new SurfaceRenderer();
            try
            {
                renderer.Canvas = new SurfaceCanvas();
            }
            catch
            {
                SurfaceGdip.Release();
                throw;
            }
            renderer.acquired = true;
            renderer.CornersFollowTheLook();
            return renderer;
        }

        /// Every object it made, let go (close).
        public void Dispose()
        {
            DropImages();
            if (Fonts != null)
            {
                Fonts.Dispose();
                Fonts = null;
            }
            if (Canvas != null)
            {
                Canvas.Dispose();
                Canvas = null;
                if (acquired) SurfaceGdip.Release();
                acquired = false;
            }
        }

        /// The fonts for `locale` at `scale`, made again only when either changes (use).
        internal void Use(string locale, double scale)
        {
            if (Fonts == null || Fonts.Locale != locale || Fonts.Scale != scale)
            {
                if (Fonts != null)
                {
                    Fonts.Dispose();
                    Fonts = null;
                }
                Fonts = new SurfaceFontSet(Canvas.Dc, locale, scale, Letters ?? "");
                Text = new SurfaceText(new GdiTextCalc(Canvas.Dc, Fonts), locale);
            }
        }

        /// The popup's plan in `locale` at `scale`: mirrored when the language is written right to left (layout).
        internal SurfacePlan Layout(Dictionary<string, object> vm, double scale, string locale)
        {
            Use(locale, scale);
            return PopupLayout.Plan(vm, scale, locale, Text);
        }

        private void CornersFollowTheLook()
        {
            if (Canvas != null) Canvas.Smoothing = Smoothing();
        }

        /// What the ground's colours depend on besides the tokens: the system colours, in High Contrast (_system_key).
        private string SystemKey()
        {
            if (!contrast) return "";
            var key = new StringBuilder();
            var names = new List<string> { "Window", "WindowFrame", "WindowText", "Highlight", "HighlightText", "Control", "GrayText" };
            names.Sort(string.CompareOrdinal);
            foreach (string name in names)
            {
                int[] rgb = SystemColour(name);
                key.Append(rgb[0]).Append(',').Append(rgb[1]).Append(',').Append(rgb[2]).Append(';');
            }
            return key.ToString();
        }

        // ------------------------------------------------------------------ numbers as the plans hold them
        internal static double D(object value)
        {
            return Convert.ToDouble(value, CultureInfo.InvariantCulture);
        }

        internal static double[] Box(object value)
        {
            var ints = value as int[];
            if (ints != null) return Array.ConvertAll(ints, entry => (double)entry);
            var doubles = value as double[];
            if (doubles != null) return doubles;
            var list = (System.Collections.IList)value;
            var found = new double[list.Count];
            for (int i = 0; i < found.Length; i++) found[i] = D(list[i]);
            return found;
        }

        private static string KeyOf(object value)
        {
            if (value == null) return "~";
            if (value is bool) return (bool)value ? "T" : "F";
            if (value is string) return "s" + ((string)value).Length + ":" + value;
            if (value is int || value is double || value is long || value is float)
                return "n" + D(value).ToString("R", CultureInfo.InvariantCulture);
            var target = value as SurfaceTarget;
            if (target != null) return "t" + KeyOf(target.Name) + (target.Keyed ? KeyOf(target.Key) : "");
            var list = value as System.Collections.IEnumerable;
            if (list != null)
            {
                var key = new StringBuilder("[");
                foreach (object entry in list) key.Append(KeyOf(entry)).Append(',');
                return key.Append(']').ToString();
            }
            return value.ToString();
        }

        // ------------------------------------------------------------------ a whole frame
        private string groundKey;
        private byte[] groundPixels;

        /// One whole frame into the canvas; returns the canvas (draw). `glides` is {switch target: how far on} for the
        /// switches part way through a glide; `faces` {button target: (fill and edge it left from, how far on)} for the
        /// buttons part way through a change of face.
        internal SurfaceCanvas Draw(SurfacePlan plan, LightFrame frame = null, object hover = null, object pressed = null,
                                    object focus = null, Dictionary<object, double> glides = null, double sceneMs = 0.0,
                                    Dictionary<object, ButtonFace> faces = null)
        {
            faces = faces ?? new Dictionary<object, ButtonFace>();
            glides = glides ?? new Dictionary<object, double>();
            double scale = plan.Scale;
            Canvas.Ensure(plan.Size[0], plan.Size[1]);
            Ground(plan, pressed, glides);
            var busy = new List<object>();
            foreach (PlanItem item in plan.Items)
                if (SurfaceMath.Truthy(item.Get("busy"))) busy.Add(item["target"]);
            using (var paint = new SurfacePainter(Canvas))
            {
                foreach (PlanItem item in plan.Items)
                {
                    if (item.Kind == "button")
                    {
                        ButtonFace face;
                        Button(paint, item, scale, hover, pressed, faces.TryGetValue(item["target"], out face) ? face : null);
                    }
                    else if (item.Kind == "switch" && glides.ContainsKey(item["target"]))
                        Switch(paint, item, scale, glides[item["target"]]);
                }
                Scene(paint, plan, sceneMs);
            }
            DrawText(Canvas.Dc, plan, busy);
            if (focus != null)
            {
                using (var paint = new SurfacePainter(Canvas))
                {
                    foreach (PlanItem item in plan.Items)
                    {
                        if (item.Kind == "focusable" && Equals(item["target"], focus))
                        {
                            double ring = Math.Max(2.0, 2.0 * scale);
                            double grow = ring + Math.Max(1.0, scale);
                            double[] rect = Box(item["rect"]);
                            paint.StrokeRound(new[] { rect[0] - grow, rect[1] - grow, rect[2] + grow, rect[3] + grow },
                                              Corner(item, scale) + grow, Argb("focus"), ring);
                        }
                    }
                }
            }
            if (Lone) Seal(plan);
            KeepHaloBand(plan);
            return DrawHalo(plan, frame, false);
        }

        /// The card alone: each line of words' alpha put back to the ground's - GDI's text clears what it covers (_seal).
        private void Seal(SurfacePlan plan)
        {
            int width = Canvas.Width, height = Canvas.Height;
            SurfaceNative.GdiFlush();
            byte[] pixels = Canvas.Pixels();
            foreach (PlanItem item in plan.Items)
            {
                if (item.Kind != "text") continue;
                double[] rect = Box(item["rect"]);
                int left = (int)rect[0], top = (int)rect[1], right = (int)rect[2], bottom = (int)rect[3];
                for (int row = Math.Max(0, top); row < Math.Min(height, bottom); row++)
                {
                    int start = (row * width + Math.Max(0, left)) * 4 + 3, stop = (row * width + Math.Min(width, right)) * 4;
                    for (int at = start; at < stop; at += 4) pixels[at] = groundPixels[at];
                }
            }
            Marshal.Copy(pixels, 0, Canvas.Bits, pixels.Length);
        }

        /// Only the day's scene, for an animation frame (draw_scene).
        internal SurfaceCanvas DrawScene(SurfacePlan plan, double milliseconds)
        {
            bool found = false;
            foreach (PlanItem entry in plan.Items) if (entry.Kind == "scene") { found = true; break; }
            if (!found) return Canvas;
            using (var paint = new SurfacePainter(Canvas)) Scene(paint, plan, milliseconds);
            return Canvas;
        }

        // ------------------------------------------------------------------ the ground
        /// Everything but the text, the buttons' faces and the halo: drawn once, then copied (_ground).
        private void Ground(SurfacePlan plan, object pressed, Dictionary<object, double> glides)
        {
            double scale = plan.Scale;
            UseScale(scale);
            var parts = new StringBuilder();
            foreach (PlanItem item in plan.Items)
            {
                string kind = item.Kind;
                if (kind == "button")
                    parts.Append(KeyOf(new object[] { kind, item["rect"], item["primary"], Lifted(item, pressed) }));
                else if (kind != "text" && kind != "focusable" && kind != "halo" && kind != "scene" && kind != "title_press")
                    parts.Append(KeyOf(new object[] { kind, item["rect"], item.Get("radius"), item.Get("tone"), item.Get("checked"),
                                                      item.Get("busy"), kind == "switch" && glides.ContainsKey(item["target"]),
                                                      item.Get("fraction"), item.Get("low") }));
            }
            string key = KeyOf(new object[] { plan.Size, scale, ThemeName(), DesignName(), SystemKey(), plan.Rtl == true,
                                              parts.ToString(), Lone });
            if (groundKey == key && groundPixels != null)
            {
                Marshal.Copy(groundPixels, 0, Canvas.Bits, groundPixels.Length);
                return;
            }
            var drawn = new List<PlanItem>();
            foreach (PlanItem item in plan.Items)
                if (!(item.Kind == "switch" && glides.ContainsKey(item["target"]))) drawn.Add(item);
            if (Lone)
            {
                SurfaceNative.GdiFlush();
                Marshal.Copy(new byte[Canvas.Width * Canvas.Height * 4], 0, Canvas.Bits, Canvas.Width * Canvas.Height * 4);
            }
            using (var paint = Lone ? new SurfacePainter(Canvas, SurfaceGdip.PixelFormat32bppPArgb) : new SurfacePainter(Canvas))
            {
                if (!Lone) paint.FillRound(new double[] { 0, 0, Canvas.Width, Canvas.Height }, 0, Argb("canvas"));
                foreach (PlanItem item in drawn)
                    if (item.Kind == "card") GroundItem(paint, item, scale, pressed);
                foreach (PlanItem item in drawn)
                    if (item.Kind == "panel") Lift(paint, "tile", Box(item["rect"]), ControlRadius(scale), scale);
                foreach (PlanItem item in drawn)
                    if (item.Kind != "card") GroundItem(paint, item, scale, pressed);
            }
            groundPixels = Canvas.Pixels();
            groundKey = key;
        }

        private static int[] Hex(string colour)
        {
            return SurfaceTheme.Rgb(ColorTranslator.FromHtml(colour));
        }

        private static uint PieceColour(string colour, double alpha)
        {
            return Pack(Hex(colour), alpha);
        }

        /// The day across the band the plan worked out (_scene).
        private void Scene(SurfacePainter paint, SurfacePlan plan, double milliseconds)
        {
            PlanItem item = null;
            foreach (PlanItem entry in plan.Items) if (entry.Kind == "scene") { item = entry; break; }
            if (item == null) return;
            double[] rect = Box(item["rect"]);
            double left = rect[0], top = rect[1], right = rect[2], bottom = rect[3];
            bool mirrored = SurfaceMath.Truthy(item.Get("mirrored"));
            double unit = D(item["unit"]);
            string look = (string)item["scene"];
            double originY = Brand.DayFromTop(look) ? top : bottom - SurfaceDays.SceneHeight * unit;
            Func<double, double, double[]> at = (x, y) => new[] {
                mirrored ? left + (SurfaceDays.SceneWidth - x) * unit : right - (SurfaceDays.SceneWidth - x) * unit, originY + y * unit };
            double band = SurfaceDays.SpeckBand * unit;
            double[] fade = Box(item["fade"]);
            double solidX = fade[0];
            double shownFrom = mirrored ? left : solidX, shownTo = mirrored ? plan.Size[0] - solidX : right;
            double hairline = Math.Max(1.0, SurfaceMath.Round(plan.Scale));
            int[] card = plan.Card;
            paint.ClipRound(new[] { card[0] + hairline, card[1] + hairline, card[2] - hairline, card[3] - hairline },
                            SurfaceMath.Round(Radius("card") * plan.Scale) - hairline);
            paint.ClipRect(rect);
            paint.KeepSolids();
            try
            {
                string ground, bodyTop, bodyBottom;
                Brand.DayGround(look, out ground, out bodyTop, out bodyBottom);
                paint.FillRound(rect, 0, PieceColour(ground, 1.0));
                double offset = 0.0;
                while (offset < right - left)
                {
                    double[] within = mirrored
                        ? new[] { (shownFrom - left - offset) / unit, (shownTo - left - offset) / unit }
                        : new[] { SurfaceDays.SpeckBand - (right - offset - shownFrom) / unit, SurfaceDays.SpeckBand - (right - offset - shownTo) / unit };
                    double here = offset;
                    Func<double, double, double[]> place = (x, y) => new[] {
                        mirrored ? left + here + x * unit : right - here - (SurfaceDays.SpeckBand - x) * unit, top + y * unit };
                    foreach (DayShape shape in SurfaceDays.SpeckFrame(look, milliseconds, within)) SceneShape(paint, shape, place, unit);
                    offset += band;
                }
                object shown = item.Get("scene_shown");
                if (shown == null || SurfaceMath.Truthy(shown))
                    foreach (DayShape shape in SurfaceDays.SceneFrame(look, milliseconds)) SceneShape(paint, shape, at, unit);
                int[] cardGround = SurfaceTheme.Rgb(CardGround());
                double solid = fade[0], clear = fade[1], inner = left;
                if (mirrored)
                {
                    double width = plan.Size[0];
                    solid = width - fade[0];
                    clear = width - fade[1];
                    inner = right;
                }
                paint.FillRound(new[] { Math.Min(inner, solid), top, Math.Max(inner, solid), bottom }, 0, Pack(cardGround));
                paint.Fade(new[] { Math.Min(solid, clear), top, Math.Max(solid, clear), bottom }, solid, clear, cardGround);
            }
            finally
            {
                paint.ClipNone();
            }
            foreach (PlanItem chip in plan.Items)
            {
                if (chip.Kind != "chip") continue;
                double[] chipRect = Box(chip["rect"]);
                if (chipRect[0] < right && chipRect[2] > left && chipRect[1] < bottom) GroundItem(paint, chip, plan.Scale, null);
            }
        }

        /// brand.card_ground(theme, design): a card's own fill.
        private Color CardGround()
        {
            return Brand.LookOf(DesignName(), ThemeName() == "dark").CardGround;
        }

        private static List<double[]> PointsOf(DayShape shape, Func<double, double, double[]> at)
        {
            var points = new List<double[]>();
            double[] numbers = shape.Numbers;
            for (int i = shape.Kind == "stroke" ? 1 : 0; i < numbers.Length - 1; i += 2) points.Add(at(numbers[i], numbers[i + 1]));
            return points;
        }

        private static void SceneShape(SurfacePainter paint, DayShape shape, Func<double, double, double[]> at, double scale)
        {
            string kind = shape.Kind;
            double[] n = shape.Numbers;
            if (kind == "glow")
            {
                double[] centre = at(n[0], n[1]);
                double whole = n[3];
                var stops = new[] { new[] { 0.0, 1.0 }, new[] { whole, 1.0 }, new[] { whole + (1.0 - whole) * 0.3, 0.55 },
                                    new[] { whole + (1.0 - whole) * 0.65, 0.16 }, new[] { 1.0, 0.0 } };
                paint.Glow(centre[0], centre[1], n[2] * scale, stops, Hex(shape.Colour), shape.Opacity);
                return;
            }
            uint argb = PieceColour(shape.Colour, shape.Opacity);
            if (kind == "poly") paint.FillPolygon(PointsOf(shape, at), argb);
            else if (kind == "circle")
            {
                double[] centre = at(n[0], n[1]);
                paint.FillCircle(centre[0], centre[1], n[2] * scale, argb);
            }
            else if (kind == "ellipse")
            {
                double[] centre = at(n[0], n[1]);
                paint.FillEllipse(centre[0], centre[1], n[2] * scale, n[3] * scale, argb);
            }
            else if (kind == "round")
            {
                double[] one = at(n[0], n[1]), other = at(n[0] + n[2], n[1]);
                paint.FillRound(new[] { Math.Min(one[0], other[0]), one[1], Math.Max(one[0], other[0]), one[1] + n[3] * scale }, n[4] * scale, argb);
            }
            else if (kind == "ring")
            {
                double[] centre = at(n[0], n[1]);
                double radius = n[2] * scale;
                paint.StrokeRound(new[] { centre[0] - radius, centre[1] - radius, centre[0] + radius, centre[1] + radius }, radius, argb, n[3] * scale);
            }
            else paint.StrokeLines(PointsOf(shape, at), argb, n[0] * scale);
        }

        private void GroundItem(SurfacePainter paint, PlanItem item, double scale, object pressed)
        {
            string kind = item.Kind;
            double hairline = Math.Max(1.0, SurfaceMath.Round(scale));
            if (kind == "scene" || kind == "title_press") return;
            if (kind == "card")
            {
                double[] rect = Box(item["rect"]);
                double radius = Corner(item, scale);
                if (!Lone) Lift(paint, "card", rect, radius, scale);
                uint ground = contrast ? Argb("surface") : Pack(SurfaceTheme.Rgb(CardGround()));
                paint.FillRound(rect, radius, ground);
                if (!contrast && Brand.DesignAccentBar(DesignName()))
                    AccentBar(paint, rect, radius, scale, ground, SurfaceMath.Truthy(item.Get("mirrored")));
                Inner(paint, "card", rect, radius, scale);
                paint.StrokeRound(rect, radius, Argb("line"), hairline);
            }
            else if (kind == "panel")
            {
                double[] rect = Box(item["rect"]);
                double radius = ControlRadius(scale);
                uint ground = contrast ? Argb("raised") : Pack(SurfaceTheme.Rgb(SurfaceElevation.TileGround(ThemeName(), DesignName())));
                paint.FillRound(rect, radius, ground);
                Inner(paint, "tile", rect, radius, scale);
                paint.StrokeRound(rect, radius, Argb("line"), hairline);
            }
            else if (kind == "well")
            {
                double[] rect = Box(item["rect"]);
                double radius = ControlRadius(scale);
                paint.FillRound(rect, radius, Argb("inset"));
                Well(paint, rect, radius, scale);
                paint.StrokeRound(rect, radius, Argb("line"), hairline);
            }
            else if (kind == "rule") paint.FillRound(Box(item["rect"]), 0, Argb("line"));
            else if (kind == "chip" || kind == "note")
            {
                double[] rect = Box(item["rect"]);
                double radius = kind == "chip" ? (rect[3] - rect[1]) / 2.0 : ControlRadius(scale);
                if (contrast)
                {
                    if (kind == "note") paint.StrokeRound(rect, radius, Argb("line"), hairline);
                }
                else
                {
                    Color mixed = SurfaceTheme.Mix(SurfaceTheme.Token("surface", ThemeName(), DesignName()),
                                                   SurfaceTheme.Token((string)item["tone"], ThemeName(), DesignName()), ChipAlpha);
                    paint.FillRound(rect, radius, Pack(SurfaceTheme.Rgb(mixed)));
                }
            }
            else if (kind == "switch") Switch(paint, item, scale, null);
            else if (kind == "meter") Meter(paint, item, scale);
            else if (kind == "button" && Lifted(item, pressed)) Lift(paint, "control", Box(item["rect"]), ControlRadius(scale), scale);
        }

        /// Classic's mark: brand.ACCENT_BAR px of the accent just inside the card's hairline, following its corners
        /// (_accent_bar); mirrored, inside the right one.
        private void AccentBar(SurfacePainter paint, double[] rect, double radius, double scale, uint ground, bool mirrored)
        {
            double border = Math.Max(1.0, SurfaceMath.Round(scale));
            double[] inside = { rect[0] + border, rect[1] + border, rect[2] - border, rect[3] - border };
            double inner = Math.Max(0.0, radius - border);
            paint.FillRound(inside, inner, Argb("accent"));
            double bar = Brand.AccentBar * scale;
            double[] cover = mirrored ? new[] { inside[0], inside[1], inside[2] - bar, inside[3] }
                                      : new[] { inside[0] + bar, inside[1], inside[2], inside[3] };
            paint.FillRound(cover, inner, ground);
        }

        // ------------------------------------------------------------------ materials
        private readonly Dictionary<string, SurfaceShadowImage> images = new Dictionary<string, SurfaceShadowImage>();
        private string imagesLook;

        /// Shadow images are kept for one scale, one theme and one design only (_use_scale).
        private void UseScale(double scale)
        {
            string look = KeyOf(new object[] { scale, ThemeName(), DesignName() });
            if (imagesLook != look)
            {
                DropImages();
                imagesLook = look;
            }
        }

        private void DropImages()
        {
            foreach (SurfaceShadowImage image in images.Values) image.Dispose();
            images.Clear();
        }

        private SurfaceShadowImage Image(ShadowMask mask, SurfaceShadow shadow)
        {
            string theme = ThemeName(), look = DesignName();
            string key = KeyOf(new object[] { mask.Key, theme, look, shadow.Token, shadow.Alpha });
            SurfaceShadowImage image;
            if (!images.TryGetValue(key, out image))
            {
                int[] rgb = SurfaceTheme.Rgb(SurfaceTheme.Token(shadow.Token, theme, look));
                image = images[key] = new SurfaceShadowImage(mask.Coverage, mask.Width, mask.Height, mask.Centre, mask.Extent, rgb, shadow.Alpha);
            }
            return image;
        }

        /// A raised body's outer shadows, the last listed first as CSS paints them (_lift); `lights` false leaves out
        /// the highlight.
        internal void Lift(SurfacePainter paint, string recipe, double[] rect, double radius, double scale, bool lights = true)
        {
            if (!Depth()) return;
            int left = (int)rect[0], top = (int)rect[1], right = (int)rect[2], bottom = (int)rect[3];
            List<SurfaceShadow> shadows = SurfaceElevation.RecipeShadows(recipe, ThemeName(), DesignName());
            for (int i = shadows.Count - 1; i >= 0; i--)
            {
                SurfaceShadow shadow = shadows[i];
                if (shadow.Inset || (!lights && shadow.Token == "shadow_light")) continue;
                SurfaceShadowImage image = Image(SurfaceElevation.LiftCoverage(right - left, bottom - top, radius, shadow.Blur * scale), shadow);
                int extent = (int)image.Extent;
                image.Stamp(paint, left - extent + SurfaceElevation.ShadowStep(shadow.Dx * scale),
                            top - extent + SurfaceElevation.ShadowStep(shadow.Dy * scale),
                            right - left + 2 * extent, bottom - top + 2 * extent, false);
            }
        }

        /// A recipe's inset shadows inside a body's border, over its fill (_inner).
        private void Inner(SurfacePainter paint, string recipe, double[] rect, double radius, double scale)
        {
            if (!Depth()) return;
            var inset = new List<SurfaceShadow>();
            List<SurfaceShadow> shadows = SurfaceElevation.RecipeShadows(recipe, ThemeName(), DesignName());
            for (int i = shadows.Count - 1; i >= 0; i--) if (shadows[i].Inset) inset.Add(shadows[i]);
            if (inset.Count == 0) return;
            int border = (int)Math.Max(1.0, SurfaceMath.Round(scale));
            int left = (int)rect[0], top = (int)rect[1], right = (int)rect[2], bottom = (int)rect[3];
            int width = right - left - 2 * border, height = bottom - top - 2 * border;
            if (width <= 0 || height <= 0) return;
            double inner = Math.Max(0.0, radius - border);
            foreach (SurfaceShadow shadow in inset)
            {
                ShadowMask mask = SurfaceElevation.WellCoverage(width, height, inner, shadow.Blur * scale, shadow.Dx * scale, shadow.Dy * scale);
                Image(mask, shadow).Stamp(paint, left + border, top + border, width, height);
            }
        }

        /// The inset recipe inside a body's border (_well).
        private void Well(SurfacePainter paint, double[] rect, double radius, double scale)
        {
            Inner(paint, "inset", rect, radius, scale);
        }

        /// The panel's switch (_switch); `on` is how far on it is drawn for a glide, null where it stands.
        private void Switch(SurfacePainter paint, PlanItem item, double scale, double? on)
        {
            double[] rect = Box(item["rect"]);
            double left = rect[0], top = rect[1], right = rect[2], bottom = rect[3];
            double radius = (bottom - top) / 2.0;
            bool busy = SurfaceMath.Truthy(item["busy"]);
            double faded = busy ? 0.5 : 1.0;
            int knob = SurfaceMath.Round(Brand.Knob * scale);
            double knobLeft = left + SurfaceMath.Round(Brand.KnobInset * scale);
            double amount = on.HasValue ? Math.Max(0.0, Math.Min(1.0, on.Value)) : (SurfaceMath.Truthy(item["checked"]) ? 1.0 : 0.0);
            string offKnob = contrast ? "ink" : "muted";
            if (amount < 1.0)
            {
                paint.FillRound(rect, radius, Argb("inset", faded));
                if (!busy) Well(paint, rect, radius, scale);
                paint.StrokeRound(rect, radius, Argb("line", faded), Math.Max(1.0, SurfaceMath.Round(scale)));
            }
            if (amount > 0.0) paint.FillRound(rect, radius, Argb("accent", faded * amount));
            knobLeft += SurfaceMath.Round(Brand.KnobTravel * scale) * amount;
            if (SurfaceMath.Truthy(item.Get("mirrored"))) knobLeft = left + right - knobLeft - knob;
            uint colour;
            if (amount == 0.0 || amount == 1.0) colour = Argb(amount != 0.0 ? "on_accent" : offKnob, faded);
            else
            {
                int[] start = Rgb(offKnob), end = Rgb("on_accent");
                var mixed = new int[3];
                for (int i = 0; i < 3; i++) mixed[i] = SurfaceMath.Round(start[i] + (end[i] - start[i]) * amount);
                colour = Pack(mixed, faded);
            }
            paint.FillCircle(knobLeft + knob / 2.0, (top + bottom) / 2.0, knob / 2.0, colour);
        }

        /// A usage window's bar: a pill sunk into the card, filled in the accent as far as the window has left (_meter).
        private void Meter(SurfacePainter paint, PlanItem item, double scale)
        {
            double[] rect = Box(item["rect"]);
            double left = rect[0], top = rect[1], right = rect[2], bottom = rect[3];
            double radius = (bottom - top) / 2.0;
            bool low = SurfaceMath.Truthy(item.Get("low"));
            paint.FillRound(rect, radius, Argb("inset"));
            Well(paint, rect, radius, scale);
            if (contrast || low) paint.StrokeRound(rect, radius, Argb(low ? "warning" : "line"), Math.Max(1.0, SurfaceMath.Round(scale)));
            object value = item.Get("fraction");
            double fraction = Math.Max(0.0, Math.Min(1.0, SurfaceMath.Truthy(value) ? D(value) : 0.0));
            if (fraction > 0.0)
            {
                double reach = Math.Max(bottom - top, (right - left) * fraction);
                double[] fill = SurfaceMath.Truthy(item.Get("mirrored")) ? new[] { right - reach, top, right, bottom }
                                                                       : new[] { left, top, left + reach, bottom };
                paint.FillRound(fill, radius, Argb(low ? "warning" : "accent"));
            }
        }

        /// A button's face (_button): its lift is in the ground; pressed, it sinks into a well instead.
        private void Button(SurfacePainter paint, PlanItem item, double scale, object hover, object pressed, ButtonFace face)
        {
            double[] rect = Box(item["rect"]);
            string state = PopupMotion.FaceState(item, hover, pressed);
            double radius = ControlRadius(scale);
            int[][] colours = FaceColours(item, state);
            int[] fill = colours[0], edge = colours[1];
            if (face != null)
            {
                fill = PopupMotion.Mixed(face.Fill, fill, face.Amount);
                edge = PopupMotion.Mixed(face.Edge, edge, face.Amount);
            }
            paint.FillRound(rect, radius, Pack(fill));
            if (state == "pressed") Well(paint, rect, radius, scale);
            paint.StrokeRound(rect, radius, Pack(edge), Math.Max(1.0, SurfaceMath.Round(scale)));
        }

        /// Whether a line in a right-to-left plan is read left to right: a conversation's name, by its first strong
        /// character (_own_direction_left).
        private static bool OwnDirectionLeft(PlanItem item)
        {
            return (item["role"] as string) == "name"
                && SurfaceBidi.FirstStrong(Convert.ToString(item["text"], CultureInfo.InvariantCulture)) == "L";
        }

        /// The words, by GDI (_text).
        private void DrawText(IntPtr dc, SurfacePlan plan, List<object> busy)
        {
            SurfaceNative.SetBkMode(dc, SurfaceNative.TRANSPARENT);
            IntPtr original = IntPtr.Zero;
            bool selected = false;
            try
            {
                foreach (PlanItem item in plan.Items)
                {
                    if (item.Kind != "text") continue;
                    string role = (string)item["role"];
                    IntPtr previous = SurfaceNative.SelectObject(dc, Fonts.Handles[role]);
                    if (!selected)
                    {
                        original = previous;
                        selected = true;
                    }
                    object target = item.Get("target");
                    bool waiting = false;
                    foreach (object entry in busy) if (Equals(entry, target)) { waiting = true; break; }
                    SurfaceNative.SetTextColor(dc, ColorRef(waiting ? "muted" : (string)item["colour"]));
                    uint flags = SurfaceNative.DT_NOPREFIX;
                    bool wrap = SurfaceMath.Truthy(item["wrap"]);
                    if (wrap) flags |= SurfaceNative.DT_WORDBREAK | SurfaceNative.DT_EDITCONTROL;
                    else flags |= SurfaceNative.DT_SINGLELINE | SurfaceNative.DT_VCENTER | SurfaceNative.DT_END_ELLIPSIS;
                    string align = item["align"] as string;
                    if (align == "center") flags |= SurfaceNative.DT_CENTER;
                    else if (align == "right") flags |= SurfaceNative.DT_RIGHT;
                    if (plan.Rtl == true && !OwnDirectionLeft(item)) flags |= SurfaceNative.DT_RTLREADING;
                    double[] rect = Box(item["rect"]);
                    string text = item["text"] as string;
                    string value = wrap ? Text.Lines(role, text, (int)(rect[2] - rect[0])) : text;
                    var box = new SurfaceNative.RECT((int)rect[0], (int)rect[1], (int)rect[2], (int)rect[3]);
                    SurfaceNative.DrawTextW(dc, value, -1, ref box, flags);
                }
            }
            finally
            {
                if (selected) SurfaceNative.SelectObject(dc, original);
                SurfaceNative.GdiFlush();
            }
        }

        /// A reason chip's ground: its colour mixed CHIP_ALPHA of the way into the card's surface (CHIP_ALPHA).
        internal const double ChipAlpha = 0.12;
    }

    /// A button part way through a change of face: the fill and edge it left from, and how far it has come.
    internal sealed class ButtonFace
    {
        internal readonly int[] Fill, Edge;
        internal readonly double Amount;

        internal ButtonFace(int[] fill, int[] edge, double amount)
        {
            Fill = fill;
            Edge = edge;
            Amount = amount;
        }
    }
}
