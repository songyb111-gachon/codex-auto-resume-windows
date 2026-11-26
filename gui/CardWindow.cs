// Codex Auto Resume - one notification card: its corner cut, its shadow, its body, its breathing light, and where a
// click lands on it (v0.6.27, S6.3).
//
// The C# port of ui/card/card.py's Card and ui/card/surfaces.py (_Layer, _Surface, _Image, _CardRenderer), with
// notice_card.py's corner_coverage (_round_corner, _squircle_corner) and premultiply, call for call. A card is drawn by
// the one renderer (SurfaceRenderer, as _CardRenderer is the popup's: its _halo override draws what the popup's does for
// every state brand knows and idle grey for any other, which is the popup's own rule, so it is the renderer's here); its
// two layers are layered windows, or with no windows (`windows` false) the same DIBs offscreen, for the tests and the
// pictures. The stack that holds the cards, its timer and its window procedure, is gui/CardStack.cs.
using System;
using System.Collections.Generic;
using System.Drawing;
using System.Runtime.InteropServices;

namespace CodexAutoResume
{
    /// The card's corner and its cut (notice_card.corner_coverage, premultiply).
    internal static class CardCorner
    {
        private static readonly Dictionary<string, byte[][]> Corners = new Dictionary<string, byte[][]>();
        private static readonly object Lock = new object();

        /// How much of each pixel of a card's top-left corner square the card covers, 0-255, rows of bytes
        /// (corner_coverage); kept, at most eight, as the Python keeps them.
        internal static byte[][] Coverage(double radius, double? smoothing = null)
        {
            double smooth = smoothing ?? SurfaceShape.DesignSmoothing();
            string key = radius.ToString("R") + "|" + smooth.ToString("R");
            lock (Lock)
            {
                byte[][] rows;
                if (Corners.TryGetValue(key, out rows)) return rows;
                ShapeProfile made = SurfaceShape.Profile(radius, smooth, 1e9);
                rows = SurfaceShape.Smoothed(made.Corner) ? Squircle(made) : Round(radius);
                if (Corners.Count >= 8) Corners.Clear();
                Corners[key] = rows;
                return rows;
            }
        }

        private static byte[][] Round(double radius)
        {
            int size = (int)Math.Ceiling(radius);
            var rows = new byte[size][];
            for (int j = 0; j < size; j++)
            {
                var row = new byte[size];
                for (int i = 0; i < size; i++)
                {
                    double distance = IconMark.Hypot(radius - (i + 0.5), radius - (j + 0.5)) - radius;
                    if (i + 0.5 >= radius || j + 0.5 >= radius) distance = -1.0;
                    row[i] = (byte)SurfaceMath.Round(Math.Min(1.0, Math.Max(0.0, 0.5 - distance)) * 255);
                }
                rows[j] = row;
            }
            return rows;
        }

        private static byte Count(int count) { return (byte)SurfaceMath.Div(count * 255 + 8, 16); }

        private static byte[][] Squircle(ShapeProfile made)
        {
            int size = (int)Math.Ceiling(made.P);
            double middle = made.Middle;
            var half = new byte[size][];
            for (int i = 0; i < size; i++)
            {
                var column = new byte[size];
                half[i] = column;
                if (i + 1 <= middle) continue;
                var edges = new double[4];
                for (int s = 0; s < 4; s++)
                {
                    double u = i + (s + 0.5) / 4.0;
                    edges[s] = u >= middle ? SurfaceShape.EdgeAt(made, u) : size;
                }
                double least = Math.Min(Math.Min(edges[0], edges[1]), Math.Min(edges[2], edges[3]));
                double most = Math.Max(Math.Max(edges[0], edges[1]), Math.Max(edges[2], edges[3]));
                int first = Math.Max(0, Math.Min(i, (int)Math.Floor(least - 0.875)));
                int full = Math.Max(first, Math.Min(i, (int)Math.Ceiling(most - 0.125)));
                for (int j = first; j < full; j++)
                {
                    int count = 16;
                    foreach (double edge in edges)
                    {
                        int skipped = (int)Math.Ceiling(4.0 * (edge - j) - 0.5);
                        count -= skipped > 4 ? 4 : (skipped > 0 ? skipped : 0);
                    }
                    column[j] = Count(count);
                }
                for (int j = full; j < i; j++) column[j] = 0xFF;
            }
            var rows = new byte[size][];
            for (int r = 0; r < size; r++)
            {
                var row = new byte[size];
                for (int c = 0; c < r; c++) row[c] = half[r][c];
                for (int c = r + 1; c < size; c++) row[c] = half[c][r];
                if (r + 1 <= middle) row[r] = 0;
                else if (r >= middle + 1) row[r] = 255;
                else
                {
                    int count = 0;
                    for (int sy = 0; sy < 4; sy++)
                        for (int sx = 0; sx < 4; sx++)
                            if (SurfaceShape.InsideCorner(made, r + (sx + 0.5) / 4.0, r + (sy + 0.5) / 4.0)) count++;
                    row[r] = Count(count);
                }
                rows[r] = row;
            }
            return rows;
        }

        /// A card's opaque BGRX pixels as premultiplied BGRA with its rounded corners cut out; `pixels` may be a band of
        /// whole rows starting at row `top` (premultiply).
        internal static byte[] Premultiply(byte[] pixels, int width, int height, double radius, int top = 0, double? smoothing = null)
        {
            var data = (byte[])pixels.Clone();
            int band = width != 0 ? data.Length / (4 * width) : 0;
            for (int at = 3; at < width * band * 4; at += 4) data[at] = 0xFF;
            byte[][] rows = Coverage(radius, smoothing);
            int size = rows.Length;
            for (int j = 0; j < Math.Min(size, height); j++)
                for (int i = 0; i < Math.Min(size, width); i++)
                {
                    byte cover = rows[j][i];
                    if (cover == 255) continue;
                    int[][] four = { new[] { i, j }, new[] { width - 1 - i, j }, new[] { i, height - 1 - j }, new[] { width - 1 - i, height - 1 - j } };
                    foreach (int[] point in four)
                    {
                        int x = point[0], y = point[1] - top;
                        if (!(0 <= y && y < band)) continue;
                        int index = (y * width + x) * 4;
                        if (cover == 0)
                        {
                            data[index] = data[index + 1] = data[index + 2] = data[index + 3] = 0;
                        }
                        else
                        {
                            for (int channel = 0; channel < 3; channel++) data[index + channel] = (byte)((data[index + channel] * cover + 127) / 255);
                            data[index + 3] = cover;
                        }
                    }
                }
            return data;
        }
    }

    /// A layered window and the premultiplied 32-bit DIB it is updated from (_Layer); with no window, the DIB alone.
    internal sealed class CardLayer : IDisposable
    {
        internal IntPtr Hwnd, Dc, Bitmap, Original, Bits;
        internal int Width, Height;
        internal bool Shown;

        internal CardLayer(IntPtr hwnd)
        {
            Hwnd = hwnd;
            Dc = SurfaceNative.CreateCompatibleDC(IntPtr.Zero);
            if (Dc == IntPtr.Zero) throw new InvalidOperationException("CreateCompatibleDC");
        }

        internal void Ensure(int width, int height)
        {
            if (Bitmap != IntPtr.Zero && width == Width && height == Height) return;
            SurfaceNative.BITMAPINFO info = SurfaceNative.BitmapInfo(width, height);
            IntPtr bits;
            IntPtr bitmap = SurfaceNative.CreateDIBSection(Dc, ref info, 0, out bits, IntPtr.Zero, 0);
            if (bitmap == IntPtr.Zero) throw new InvalidOperationException("CreateDIBSection");
            IntPtr previous = SurfaceNative.SelectObject(Dc, bitmap);
            if (Bitmap != IntPtr.Zero) SurfaceNative.DeleteObject(Bitmap);
            else Original = previous;
            Bitmap = bitmap;
            Bits = bits;
            Width = width;
            Height = height;
        }

        internal void Clear()
        {
            SurfaceNative.GdiFlush();
            Marshal.Copy(new byte[Width * Height * 4], 0, Bits, Width * Height * 4);
        }

        internal byte[] Pixels()
        {
            SurfaceNative.GdiFlush();
            var copy = new byte[Width * Height * 4];
            Marshal.Copy(Bits, copy, 0, copy.Length);
            return copy;
        }

        /// Put the DIB on screen at (x, y) with the whole window at `alpha` (0-1) (push).
        internal bool Push(int x, int y, double alpha)
        {
            var blend = new SurfaceNative.BLENDFUNCTION { BlendOp = 0, BlendFlags = 0, AlphaFormat = 1,
                                                          SourceConstantAlpha = (byte)Math.Max(0, Math.Min(255, SurfaceMath.Round(alpha * 255))) };
            using (new SurfaceNative.PerMonitorDpi())
            {
                var point = new SurfaceNative.POINT { X = x, Y = y };
                var size = new SurfaceNative.SIZE { Cx = Width, Cy = Height };
                var source = new SurfaceNative.POINT { X = 0, Y = 0 };
                bool ok = SurfaceNative.UpdateLayeredWindow(Hwnd, IntPtr.Zero, ref point, ref size, Dc, ref source, 0, ref blend,
                                                            SurfaceNative.ULW_ALPHA);
                if (ok && !Shown)
                {
                    SurfaceNative.SetWindowPos(Hwnd, SurfaceNative.HWND_TOPMOST, 0, 0, 0, 0,
                                               SurfaceNative.SWP_NOACTIVATE | SurfaceLayers.SWP_NOMOVE_NOSIZE);
                    SurfaceNative.ShowWindow(Hwnd, SurfaceNative.SW_SHOWNOACTIVATE);
                    Shown = true;
                }
                return ok;
            }
        }

        public void Dispose()
        {
            if (Bitmap != IntPtr.Zero)
            {
                SurfaceNative.SelectObject(Dc, Original);
                SurfaceNative.DeleteObject(Bitmap);
                Bitmap = IntPtr.Zero;
            }
            if (Dc != IntPtr.Zero)
            {
                SurfaceNative.DeleteDC(Dc);
                Dc = IntPtr.Zero;
            }
        }
    }

    /// GDI+ drawing straight into a layer's premultiplied pixels (_Surface): half-pixel offsets, high-speed compositing.
    internal sealed class CardSurface : IDisposable
    {
        internal IntPtr Bitmap, Graphics;

        [DllImport("gdiplus.dll")] internal static extern int GdipSetCompositingQuality(IntPtr graphics, int quality);

        [DllImport("gdiplus.dll")]
        internal static extern int GdipDrawImageRectRect(IntPtr graphics, IntPtr image, float dx, float dy, float dw, float dh, float sx,
                                                         float sy, float sw, float sh, int unit, IntPtr attributes, IntPtr callback, IntPtr data);

        internal CardSurface(CardLayer layer)
        {
            SurfaceNative.GdiFlush();
            int status = SurfaceGdip.GdipCreateBitmapFromScan0(layer.Width, layer.Height, layer.Width * 4, SurfaceGdip.PixelFormat32bppPArgb,
                                                               layer.Bits, out Bitmap);
            if (status != 0) throw new InvalidOperationException("GdipCreateBitmapFromScan0 failed (" + status + ")");
            SurfaceGdip.Made(1);
            status = SurfaceGdip.GdipGetImageGraphicsContext(Bitmap, out Graphics);
            if (status != 0)
            {
                SurfaceGdip.GdipDisposeImage(Bitmap);
                SurfaceGdip.Made(-1);
                throw new InvalidOperationException("GdipGetImageGraphicsContext failed (" + status + ")");
            }
            SurfaceGdip.Made(1);
            SurfaceGdip.GdipSetPixelOffsetMode(Graphics, 4);
            GdipSetCompositingQuality(Graphics, 1);
        }

        public void Dispose()
        {
            SurfaceGdip.GdipDeleteGraphics(Graphics);
            SurfaceGdip.GdipDisposeImage(Bitmap);
            SurfaceGdip.Made(-2);
        }
    }

    /// Premultiplied pixels as a GDI+ image, kept alive for exactly as long as the image (_Image).
    internal sealed class CardImage : IDisposable
    {
        internal readonly int Width, Height;
        internal readonly byte[] Pixels;
        private GCHandle pin;
        internal IntPtr Bitmap;

        internal CardImage(byte[] pixels, int width, int height)
        {
            Width = width;
            Height = height;
            Pixels = (byte[])pixels.Clone();
            pin = GCHandle.Alloc(Pixels, GCHandleType.Pinned);
            int status = SurfaceGdip.GdipCreateBitmapFromScan0(width, height, width * 4, SurfaceGdip.PixelFormat32bppPArgb,
                                                               pin.AddrOfPinnedObject(), out Bitmap);
            if (status != 0)
            {
                pin.Free();
                throw new InvalidOperationException("GdipCreateBitmapFromScan0 failed (" + status + ")");
            }
            SurfaceGdip.Made(1);
        }

        internal IntPtr Memory { get { return pin.AddrOfPinnedObject(); } }

        public void Dispose()
        {
            if (Bitmap != IntPtr.Zero)
            {
                SurfaceGdip.GdipDisposeImage(Bitmap);
                SurfaceGdip.Made(-1);
                Bitmap = IntPtr.Zero;
            }
            if (pin.IsAllocated) pin.Free();
        }
    }

    /// How the card's windows are made: the stack's window class and module (CardStack.class_name, instance), and the
    /// table a window's messages are routed through (stack.windows).
    internal interface ICardHost
    {
        string ClassName { get; }
        IntPtr Instance { get; }
        Dictionary<IntPtr, NoticeCard> Windows { get; }
    }

    /// One notice on screen: its view, its drawn image, its two windows and its motion (Card).
    internal sealed class NoticeCard : IDisposable
    {
        internal readonly ICardHost Stack;
        internal readonly Dictionary<string, object> Vm;
        internal readonly string Title;
        internal string Edge = "bottom";
        internal readonly double Born;
        private double breathed;
        internal readonly double Scale;
        internal readonly string Theme, Design;
        internal readonly bool Contrast;
        internal readonly CardMotion Motion;
        /// The button under the pointer, and the one pressed (the stack sets them, then Redraw).
        internal object Hover { get; set; }
        internal object Pressed { get; set; }
        /// The stack's marks: the pointer tracked, pushed out by a newer card, moved out, a frame at full strength put
        /// on screen (or clicked), a newer notice about the same conversation in its place, on_complete called.
        internal bool Tracking { get; set; }
        internal bool PushedOut { get; set; }
        internal bool MovedOut { get; set; }
        internal bool Seen;
        internal bool Superseded { get; set; }
        internal bool Ended { get; set; }
        internal SurfaceRenderer Renderer;
        internal SurfacePlan Plan;
        internal CardImage Image;
        internal readonly List<FloatShadow> Shadows;
        internal readonly int Margin;
        private readonly Dictionary<int, List<SurfaceShadowImage>> shadowImages = new Dictionary<int, List<SurfaceShadowImage>>();
        private int? drawnLevel;
        private double? drawnScale;
        private string pushed;
        internal CardLayer Shadow, Body;
        /// Every character the card's words draw, for the fonts' lacks rule (the core hands it with the notice).
        internal readonly string Letters;

        /// `vm` is notice_card.view(notice); `where` the dpi and work area; `drawn` the theme, contrast, design,
        /// reduced, text and day the hosting icon saw; `hold` the stack's hold (`stays` holds until clicked).
        internal NoticeCard(ICardHost stack, Dictionary<string, object> vm, string title, bool stays, double hold, double nowMs,
                            double dpi, int[] work, Dictionary<string, object> drawn, bool windows = true, string letters = null)
        {
            Stack = stack;
            Vm = new Dictionary<string, object>(vm);
            Title = title;
            Letters = letters;
            string design = SurfaceTheme.DesignChoice(SurfaceRender.Field(drawn, "design"));
            object day = SurfaceRender.Field(drawn, "day");
            if (SurfaceMath.Truthy(day) && !SurfaceMath.Truthy(SurfaceRender.Field(drawn, "contrast")) && design != "classic")
                Vm["scene"] = day;
            Born = nowMs;
            breathed = nowMs;
            Scale = dpi / 96.0 * CardPlan.Fitting(dpi, work, SurfaceRender.Field(drawn, "text"));
            Theme = (string)drawn["theme"];
            Contrast = SurfaceMath.Truthy(drawn["contrast"]);
            Design = design;
            Motion = new CardMotion(nowMs, stays ? CardPlan.UntilClicked : hold, SurfaceMath.Truthy(drawn["reduced"]));
            Shadows = Contrast ? new List<FloatShadow>() : CardPlan.FloatShadows(Theme, Design);
            Margin = Shadows.Count > 0 ? CardPlan.ShadowMargin(Shadows, Scale) : 0;
            try
            {
                DrawCard();
                if (windows) CreateWindows();
                else
                {
                    Shadow = new CardLayer(IntPtr.Zero);
                    Body = new CardLayer(IntPtr.Zero);
                }
                int[] size = Plan.Size;
                Body.Ensure(size[0], size[1]);
                Shadow.Ensure(size[0] + 2 * Margin, size[1] + 2 * Margin);
            }
            catch
            {
                Dispose();
                throw;
            }
        }

        /// The card's corner in device px: the design's, or Soft's in High Contrast (radius).
        internal double Radius { get { return Brand.DesignRadius(Contrast ? Brand.DesignDefault : Design, "card") * Scale; } }

        /// How much the card's corners are smoothed (smoothing).
        internal double Smoothing { get { return SurfaceShape.DesignSmoothing(Contrast ? Brand.DesignDefault : Design); } }

        private LightFrame Glow(double? nowMs)
        {
            double age = nowMs.HasValue ? nowMs.Value - Born : 0.0;
            return Contrast ? null : PopupMotion.Halo((string)Vm["status"], age, Motion.Reduced, Design);
        }

        private void DrawCard(double? nowMs = null)
        {
            if (Renderer == null)
            {
                Renderer = SurfaceRenderer.Open();
                Renderer.Theme = Theme;
                Renderer.Design = Design;
                Renderer.Contrast = Contrast;
                Renderer.Letters = Letters;
                Renderer.Canvas.Smoothing = Smoothing;
            }
            Renderer.Use((string)Vm["locale"], Scale);
            Plan = CardPlan.Layout(Vm, Scale, Renderer.Text);
            SurfaceCanvas canvas = Renderer.Draw(Plan, Glow(nowMs), Hover, Pressed);
            int width = Plan.Size[0], height = Plan.Size[1];
            byte[] pixels = CardCorner.Premultiply(canvas.Pixels(), width, height, Radius, 0, Smoothing);
            if (Image != null) Image.Dispose();
            Image = new CardImage(pixels, width, height);
            drawnScale = null;
        }

        /// Only the status light, for a breath: its band drawn again and cut, into the image and, settled, the layer
        /// (_draw_light).
        internal void DrawLight(double nowMs)
        {
            SurfaceCanvas canvas = Renderer.DrawHalo(Plan, Glow(nowMs));
            int[] rows = Renderer.HaloRows;
            int top = rows[0], bottom = rows[1];
            int width = Plan.Size[0], height = Plan.Size[1];
            int row = width * 4;
            SurfaceNative.GdiFlush();
            var raw = new byte[(bottom - top) * row];
            Marshal.Copy(canvas.Bits + top * row, raw, 0, raw.Length);
            byte[] band = CardCorner.Premultiply(raw, width, height, Radius, top, Smoothing);
            Array.Copy(band, 0, Image.Pixels, top * row, band.Length);
            CardLayer layer = Body;
            if (drawnScale.HasValue && drawnScale.Value >= 0.9999 && layer != null && layer.Bits != IntPtr.Zero
                && layer.Width == width && layer.Height == height)
                Marshal.Copy(Image.Pixels, top * row, layer.Bits + top * row, band.Length);
            else drawnScale = null;
        }

        internal int[] Size { get { return Plan.Size; } }

        private void CreateWindows()
        {
            int width = Size[0], height = Size[1];
            using (new SurfaceNative.PerMonitorDpi())
            {
                uint style = SurfaceNative.WS_EX_LAYERED | SurfaceNative.WS_EX_NOACTIVATE | SurfaceNative.WS_EX_TOOLWINDOW | SurfaceNative.WS_EX_TOPMOST;
                IntPtr shadow = SurfaceNative.CreateWindowExW(style | SurfaceLayers.WS_EX_TRANSPARENT, Stack.ClassName, "", SurfaceNative.WS_POPUP,
                                                              0, 0, width + 2 * Margin, height + 2 * Margin, IntPtr.Zero, IntPtr.Zero, Stack.Instance, IntPtr.Zero);
                if (shadow == IntPtr.Zero) throw new InvalidOperationException("CreateWindowExW");
                Shadow = new CardLayer(shadow);
                Stack.Windows[shadow] = this;
                IntPtr body = SurfaceNative.CreateWindowExW(style, Stack.ClassName, Title, SurfaceNative.WS_POPUP, 0, 0, width, height, shadow,
                                                            IntPtr.Zero, Stack.Instance, IntPtr.Zero);
                if (body == IntPtr.Zero) throw new InvalidOperationException("CreateWindowExW");
                Body = new CardLayer(body);
                Stack.Windows[body] = this;
            }
        }

        /// The pointer moved onto or off a button, or pressed one: the face again, the light where its breath last was
        /// (redraw).
        internal void Redraw()
        {
            DrawCard(breathed);
            pushed = null;
        }

        /// Whether the status light moves now; its band alone drawn again once a breath's frame has passed (breathe).
        internal bool Breathe(double nowMs)
        {
            if (Contrast || !Brand.GlowMoves((string)Vm["status"], nowMs - Born, Motion.Reduced)) return false;
            if (nowMs - breathed >= PopupWindowMotion.FrameMs - CardPlan.FrameMs)
            {
                DrawLight(nowMs);
                pushed = null;
                breathed = nowMs;
            }
            return true;
        }

        private void PaintBody(double scale)
        {
            if (drawnScale == scale) return;
            CardLayer layer = Body;
            if (scale >= 0.9999)
            {
                SurfaceNative.GdiFlush();
                Marshal.Copy(Image.Pixels, 0, layer.Bits, Image.Pixels.Length);
            }
            else
            {
                layer.Clear();
                double width = Image.Width * scale, height = Image.Height * scale;
                double left = (Image.Width - width) / 2.0, top = (Image.Height - height) / 2.0;
                using (var surface = new CardSurface(layer))
                {
                    SurfaceGdip.GdipSetInterpolationMode(surface.Graphics, 6);
                    CardSurface.GdipDrawImageRectRect(surface.Graphics, Image.Bitmap, (float)left, (float)top, (float)width, (float)height,
                                                      0.0f, 0.0f, (float)Image.Width, (float)Image.Height, SurfaceNative.UNIT_PIXEL,
                                                      IntPtr.Zero, IntPtr.Zero, IntPtr.Zero);
                }
            }
            drawnScale = scale;
        }

        private void PaintShadow(int level)
        {
            if (drawnLevel == level || Shadows.Count == 0) return;
            CardLayer layer = Shadow;
            layer.Clear();
            List<SurfaceShadowImage> images;
            shadowImages.TryGetValue(level, out images);
            int width = Size[0], height = Size[1];
            double radius = Radius;
            double depth = level / (double)(CardPlan.DepthLevels - 1);
            List<FloatShadow> placed = CardPlan.ShadowAt(Shadows, depth);
            if (images == null)
            {
                images = new List<SurfaceShadowImage>();
                foreach (FloatShadow shadow in placed)
                {
                    ShadowMask mask = SurfaceElevation.LiftCoverage(width, height, radius, shadow.Blur * Scale, Smoothing);
                    images.Add(new SurfaceShadowImage(mask.Coverage, mask.Width, mask.Height, mask.Centre, mask.Extent,
                                                      SurfaceTheme.Rgb(ColorTranslator.FromHtml(shadow.Colour)), shadow.Alpha));
                }
                shadowImages[level] = images;
            }
            using (var surface = new CardSurface(layer))
            {
                SurfaceGdip.GdipSetInterpolationMode(surface.Graphics, 5);
                for (int i = placed.Count - 1; i >= 0; i--)
                {
                    FloatShadow shadow = placed[i];
                    SurfaceShadowImage image = images[i];
                    int extent = (int)image.Extent;
                    image.StampOn(surface.Graphics, Margin - extent + SurfaceElevation.ShadowStep(shadow.Dx * Scale),
                                  Margin - extent + SurfaceElevation.ShadowStep(shadow.Dy * Scale), width + 2 * extent, height + 2 * extent, false);
                }
            }
            CutUnderBody(layer);
            drawnLevel = level;
        }

        /// Nothing of the shadow lies under the card: every pixel the body covers wholly made clear (_cut_under_body).
        private void CutUnderBody(CardLayer layer)
        {
            int width = Size[0], height = Size[1];
            SurfaceNative.GdiFlush();
            byte[] pixels = Image.Pixels;
            int wide = layer.Width;
            for (int row = 0; row < height; row++)
            {
                int first = -1, last = -1;
                for (int x = 0; x < width; x++)
                {
                    if (pixels[(row * width + x) * 4 + 3] != 0xFF) continue;
                    if (first < 0) first = x;
                    last = x;
                }
                if (first < 0) continue;
                int at = (wide * (Margin + row) + Margin + first) * 4;
                Marshal.Copy(new byte[(last - first + 1) * 4], 0, layer.Bits + at, (last - first + 1) * 4);
            }
        }

        private static double Round4(double value) { return CardPlan.RoundTo(value, 4); }

        /// Both layers drawn for `nowMs`: the frame, where the card goes, and a key for the frame (paint).
        internal Dictionary<string, object> Paint(double nowMs)
        {
            CardFrame frame = Motion.Frame(nowMs);
            int[] place = Motion.Place(nowMs) ?? new[] { 0, 0 };
            int[] vector = CardPlan.RiseVector(Edge);
            int push = SurfaceMath.Round(frame.Offset * Scale);
            int x = place[0] + vector[0] * push, y = place[1] + vector[1] * push;
            int level = CardPlan.DepthLevel(frame.Depth);
            PaintBody(Round4(frame.Scale));
            if (Shadows.Count > 0) PaintShadow(level);
            string key = x + "," + y + "," + CardPlan.RoundTo(frame.Alpha, 3).ToString("R") + "," + Round4(frame.Scale).ToString("R") + "," + level;
            return new Dictionary<string, object> { { "frame", frame }, { "x", x }, { "y", y }, { "margin", Margin }, { "key", key } };
        }

        /// This card drawn for `nowMs` and both windows put where the frame says; raises when Windows refuses either
        /// layer (present).
        internal void Present(double nowMs)
        {
            Dictionary<string, object> drawn = Paint(nowMs);
            if ((string)drawn["key"] == pushed) return;
            int x = (int)drawn["x"], y = (int)drawn["y"];
            double alpha = ((CardFrame)drawn["frame"]).Alpha;
            if (Shadows.Count > 0 && !Shadow.Push(x - Margin, y - Margin, alpha)) throw new InvalidOperationException("UpdateLayeredWindow refused the shadow");
            if (!Body.Push(x, y, alpha)) throw new InvalidOperationException("UpdateLayeredWindow refused the card");
            pushed = (string)drawn["key"];
            if (alpha >= 1.0) Seen = true;
        }

        /// What a click at a mouse message's point lands on (hit).
        internal object Hit(long lparam)
        {
            int x = (short)(lparam & 0xFFFF), y = (short)((lparam >> 16) & 0xFFFF);
            return Plan != null ? PopupPlace.HitTest(Plan.Targets, x, y) : null;
        }

        public void Dispose()
        {
            foreach (CardLayer layer in new[] { Body, Shadow })
            {
                if (layer == null) continue;
                if (layer.Hwnd != IntPtr.Zero)
                {
                    if (Stack != null) Stack.Windows.Remove(layer.Hwnd);
                    SurfaceNative.DestroyWindow(layer.Hwnd);
                }
                layer.Dispose();
            }
            Body = Shadow = null;
            foreach (List<SurfaceShadowImage> images in shadowImages.Values)
                foreach (SurfaceShadowImage image in images) image.Dispose();
            shadowImages.Clear();
            if (Image != null)
            {
                Image.Dispose();
                Image = null;
            }
            if (Renderer != null)
            {
                Renderer.Dispose();
                Renderer = null;
            }
        }
    }

    /// The popup window's frame rate, which the card's breath runs at (popup.FRAME_MS, notice_card.BREATH_FRAME_MS).
    internal static class PopupWindowMotion
    {
        internal const int FrameMs = 33;
    }
}
