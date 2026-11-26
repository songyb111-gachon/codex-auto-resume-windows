// Codex Auto Resume - GDI+: the surfaces drawn on, and the counting that proves nothing leaks (v0.6.27, S6.3).
//
// The C# port of src/codex_auto_resume/ui/popup/gdiplus.py, call for call (Q8): the same flat GDI+ entry points of the
// same gdiplus.dll, with the same arguments in the same order - never System.Drawing's wrappers, which choose their own
// defaults. GdipObjects counts every image, graphics, brush, pen and path made here less every one let go, as
// _GDIPLUS_LIVE does, because GetGuiResources cannot see GDI+ objects; the leak checks read it.
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;

namespace CodexAutoResume
{
    internal static class SurfaceGdip
    {
        private static readonly object LiveLock = new object();
        private static int live;

        internal static void Made(int count)
        {
            lock (LiveLock) live += count;
        }

        /// How many GDI+ objects the surfaces hold at this moment (gdiplus_objects).
        internal static int GdipObjects
        {
            get { lock (LiveLock) return live; }
        }

        [StructLayout(LayoutKind.Sequential)]
        internal struct GdiplusStartupInput
        {
            internal uint GdiplusVersion;
            internal IntPtr DebugEventCallback;
            internal int SuppressBackgroundThread, SuppressExternalCodecs;
        }

        [StructLayout(LayoutKind.Sequential)]
        internal struct PointF { internal float X, Y; }

        private const string Dll = "gdiplus.dll";
        [DllImport(Dll)] internal static extern int GdiplusStartup(out UIntPtr token, ref GdiplusStartupInput input, IntPtr output);
        [DllImport(Dll)] internal static extern void GdiplusShutdown(UIntPtr token);
        [DllImport(Dll)] internal static extern int GdipCreateBitmapFromScan0(int width, int height, int stride, int format, IntPtr scan0, out IntPtr bitmap);
        [DllImport(Dll)] internal static extern int GdipGetImageGraphicsContext(IntPtr image, out IntPtr graphics);
        [DllImport(Dll)] internal static extern int GdipDisposeImage(IntPtr image);
        [DllImport(Dll)] internal static extern int GdipDeleteGraphics(IntPtr graphics);
        [DllImport(Dll)] internal static extern int GdipSetSmoothingMode(IntPtr graphics, int mode);
        [DllImport(Dll)] internal static extern int GdipSetPixelOffsetMode(IntPtr graphics, int mode);
        [DllImport(Dll)] internal static extern int GdipSetInterpolationMode(IntPtr graphics, int mode);
        [DllImport(Dll)] internal static extern int GdipCreateSolidFill(uint colour, out IntPtr brush);
        [DllImport(Dll)] internal static extern int GdipDeleteBrush(IntPtr brush);
        [DllImport(Dll)] internal static extern int GdipCreatePen1(uint colour, float width, int unit, out IntPtr pen);
        [DllImport(Dll)] internal static extern int GdipDeletePen(IntPtr pen);
        [DllImport(Dll)] internal static extern int GdipSetPenStartCap(IntPtr pen, int cap);
        [DllImport(Dll)] internal static extern int GdipSetPenEndCap(IntPtr pen, int cap);
        [DllImport(Dll)] internal static extern int GdipSetPenLineJoin(IntPtr pen, int join);
        [DllImport(Dll)] internal static extern int GdipCreatePath(int fillMode, out IntPtr path);
        [DllImport(Dll)] internal static extern int GdipDeletePath(IntPtr path);
        [DllImport(Dll)] internal static extern int GdipAddPathRectangle(IntPtr path, float x, float y, float width, float height);
        [DllImport(Dll)] internal static extern int GdipAddPathArc(IntPtr path, float x, float y, float width, float height, float start, float sweep);
        [DllImport(Dll)] internal static extern int GdipAddPathBezier(IntPtr path, float x1, float y1, float x2, float y2, float x3, float y3, float x4, float y4);
        [DllImport(Dll)] internal static extern int GdipAddPathEllipse(IntPtr path, float x, float y, float width, float height);
        [DllImport(Dll)] internal static extern int GdipClosePathFigure(IntPtr path);
        [DllImport(Dll)] internal static extern int GdipFillPath(IntPtr graphics, IntPtr brush, IntPtr path);
        [DllImport(Dll)] internal static extern int GdipDrawPath(IntPtr graphics, IntPtr pen, IntPtr path);
        [DllImport(Dll)] internal static extern int GdipFillEllipse(IntPtr graphics, IntPtr brush, float x, float y, float width, float height);
        [DllImport(Dll)] internal static extern int GdipFillPolygon2(IntPtr graphics, IntPtr brush, float[] points, int count);
        [DllImport(Dll)] internal static extern int GdipDrawLines(IntPtr graphics, IntPtr pen, PointF[] points, int count);
        [DllImport(Dll)] internal static extern int GdipSetClipPath(IntPtr graphics, IntPtr path, int combine);
        [DllImport(Dll)] internal static extern int GdipSetClipRect(IntPtr graphics, float x, float y, float width, float height, int combine);
        [DllImport(Dll)] internal static extern int GdipResetClip(IntPtr graphics);
        [DllImport(Dll)] internal static extern int GdipCreateLineBrush(float[] point1, float[] point2, uint colour1, uint colour2, int wrap, out IntPtr brush);
        [DllImport(Dll)] internal static extern int GdipFillRectangle(IntPtr graphics, IntPtr brush, float x, float y, float width, float height);
        [DllImport(Dll)] internal static extern int GdipDrawArc(IntPtr graphics, IntPtr pen, float x, float y, float width, float height, float start, float sweep);
        [DllImport(Dll)] internal static extern int GdipCreatePathGradientFromPath(IntPtr path, out IntPtr brush);
        [DllImport(Dll)] internal static extern int GdipSetPathGradientCenterPoint(IntPtr brush, ref PointF point);
        [DllImport(Dll)] internal static extern int GdipSetPathGradientPresetBlend(IntPtr brush, uint[] colours, float[] positions, int count);
        [DllImport(Dll)]
        internal static extern int GdipDrawImageRectRectI(IntPtr graphics, IntPtr image, int dx, int dy, int dw, int dh, int sx, int sy,
                                                          int sw, int sh, int unit, IntPtr attributes, IntPtr callback, IntPtr data);

        internal const int PixelFormat32bppRgb = 0x00022009;
        internal const int PixelFormat32bppPArgb = 0x000E200B;

        private static readonly object StartLock = new object();
        private static UIntPtr token;
        private static int users;

        /// GDI+ started for one more user (_gdiplus_acquire).
        internal static void Acquire()
        {
            lock (StartLock)
            {
                if (users == 0)
                {
                    var input = new GdiplusStartupInput { GdiplusVersion = 1 };
                    UIntPtr made;
                    int status = GdiplusStartup(out made, ref input, IntPtr.Zero);
                    if (status != 0) throw new InvalidOperationException("GdiplusStartup failed (" + status + ")");
                    token = made;
                }
                users++;
            }
        }

        /// One user fewer; GDI+ shut down after the last (_gdiplus_release).
        internal static void Release()
        {
            lock (StartLock)
            {
                if (users <= 0) return;
                users--;
                if (users == 0)
                {
                    GdiplusShutdown(token);
                    token = UIntPtr.Zero;
                }
            }
        }
    }

    /// A top-down 32-bpp DIB selected into a memory DC: the frame is built here, whole (_Canvas).
    internal sealed class SurfaceCanvas : IDisposable
    {
        internal IntPtr Dc;
        internal IntPtr Bitmap, Original, Bits;
        internal int Width, Height;
        /// The corners its painters round: null is Soft's.
        internal double? Smoothing;

        internal SurfaceCanvas()
        {
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

        internal byte[] Pixels()
        {
            var copy = new byte[Width * Height * 4];
            Marshal.Copy(Bits, copy, 0, copy.Length);
            return copy;
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

    /// Antialiased shapes straight into a canvas's pixels, through the GDI+ flat API (_Painter). Every object is
    /// released, and counted in and out.
    internal sealed class SurfacePainter : IDisposable
    {
        private Dictionary<uint, IntPtr> solids;
        internal readonly double Smoothing;
        internal IntPtr Bitmap, Graphics;

        internal SurfacePainter(SurfaceCanvas canvas, int pixelFormat = SurfaceGdip.PixelFormat32bppRgb, double? smoothing = null)
        {
            Smoothing = smoothing ?? canvas.Smoothing ?? SurfaceShape.DesignSmoothing();
            SurfaceNative.GdiFlush();
            int status = SurfaceGdip.GdipCreateBitmapFromScan0(canvas.Width, canvas.Height, canvas.Width * 4, pixelFormat, canvas.Bits, out Bitmap);
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
            SurfaceGdip.GdipSetSmoothingMode(Graphics, 4);
            SurfaceGdip.GdipSetPixelOffsetMode(Graphics, 4);
            SurfaceGdip.GdipSetInterpolationMode(Graphics, SurfaceNative.INTERPOLATION_NEAREST);
        }

        public void Dispose()
        {
            if (solids != null) foreach (IntPtr brush in solids.Values) DeleteBrush(brush);
            solids = null;
            SurfaceGdip.GdipDeleteGraphics(Graphics);
            SurfaceGdip.GdipDisposeImage(Bitmap);
            SurfaceGdip.Made(-2);
        }

        private static void Check(int status, string what)
        {
            if (status != 0) throw new InvalidOperationException(what + " failed (" + status + ")");
            SurfaceGdip.Made(1);
        }

        private void DeletePath(IntPtr path) { SurfaceGdip.GdipDeletePath(path); SurfaceGdip.Made(-1); }
        private void DeleteBrush(IntPtr brush) { SurfaceGdip.GdipDeleteBrush(brush); SurfaceGdip.Made(-1); }
        private void DeletePen(IntPtr pen) { SurfaceGdip.GdipDeletePen(pen); SurfaceGdip.Made(-1); }

        private IntPtr Brush(uint colour)
        {
            IntPtr brush;
            Check(SurfaceGdip.GdipCreateSolidFill(colour, out brush), "GdipCreateSolidFill");
            return brush;
        }

        /// Each colour's solid brush made once from here until the painter closes (keep_solids).
        internal void KeepSolids()
        {
            if (solids == null) solids = new Dictionary<uint, IntPtr>();
        }

        private IntPtr Solid(uint colour)
        {
            if (solids == null) return Brush(colour);
            IntPtr brush;
            if (!solids.TryGetValue(colour, out brush)) brush = solids[colour] = Brush(colour);
            return brush;
        }

        private void DoneWith(IntPtr brush)
        {
            if (solids == null) DeleteBrush(brush);
        }

        private IntPtr Path(double[] rect, double radius)
        {
            float left = (float)rect[0], top = (float)rect[1], right = (float)rect[2], bottom = (float)rect[3];
            double l = rect[0], t = rect[1], r = rect[2], b = rect[3];
            IntPtr path;
            Check(SurfaceGdip.GdipCreatePath(0, out path), "GdipCreatePath");
            radius = Math.Max(0.0, Math.Min(radius, Math.Min((r - l) / 2.0, (b - t) / 2.0)));
            if (radius <= 0.0)
            {
                SurfaceGdip.GdipAddPathRectangle(path, (float)l, (float)t, (float)(r - l), (float)(b - t));
                return path;
            }
            ShapeCorner found = SurfaceShape.Corner(radius, Smoothing, Math.Min(r - l, b - t) / 2.0);
            if (SurfaceShape.Smoothed(found))
            {
                foreach (ShapeSegment segment in SurfaceShape.Outline(rect, radius, Smoothing))
                {
                    if (segment.Kind == "bezier")
                    {
                        double[][] p = segment.Points;
                        SurfaceGdip.GdipAddPathBezier(path, (float)p[0][0], (float)p[0][1], (float)p[1][0], (float)p[1][1],
                                                      (float)p[2][0], (float)p[2][1], (float)p[3][0], (float)p[3][1]);
                    }
                    else
                    {
                        double cx = segment.Points[0][0], cy = segment.Points[0][1], rr = segment.Radius;
                        SurfaceGdip.GdipAddPathArc(path, (float)(cx - rr), (float)(cy - rr), (float)(2.0 * rr), (float)(2.0 * rr),
                                                   (float)segment.Start, (float)segment.Sweep);
                    }
                }
                SurfaceGdip.GdipClosePathFigure(path);
                return path;
            }
            double d = radius * 2.0;
            SurfaceGdip.GdipAddPathArc(path, (float)l, (float)t, (float)d, (float)d, 180f, 90f);
            SurfaceGdip.GdipAddPathArc(path, (float)(r - d), (float)t, (float)d, (float)d, 270f, 90f);
            SurfaceGdip.GdipAddPathArc(path, (float)(r - d), (float)(b - d), (float)d, (float)d, 0f, 90f);
            SurfaceGdip.GdipAddPathArc(path, (float)l, (float)(b - d), (float)d, (float)d, 90f, 90f);
            SurfaceGdip.GdipClosePathFigure(path);
            return path;
        }

        private IntPtr Pen(uint colour, double width)
        {
            IntPtr pen;
            Check(SurfaceGdip.GdipCreatePen1(colour, (float)width, 2, out pen), "GdipCreatePen1");
            SurfaceGdip.GdipSetPenStartCap(pen, 2);
            SurfaceGdip.GdipSetPenEndCap(pen, 2);
            SurfaceGdip.GdipSetPenLineJoin(pen, 2);
            return pen;
        }

        internal void FillRound(double[] rect, double radius, uint colour)
        {
            IntPtr path = Path(rect, radius);
            try
            {
                IntPtr brush = Brush(colour);
                try { SurfaceGdip.GdipFillPath(Graphics, brush, path); }
                finally { DeleteBrush(brush); }
            }
            finally { DeletePath(path); }
        }

        internal void StrokeRound(double[] rect, double radius, uint colour, double width)
        {
            double half = width / 2.0;
            double[] inner = { rect[0] + half, rect[1] + half, rect[2] - half, rect[3] - half };
            IntPtr path = Path(inner, Math.Max(0.0, radius - half));
            try
            {
                IntPtr pen = Pen(colour, width);
                try { SurfaceGdip.GdipDrawPath(Graphics, pen, path); }
                finally { DeletePen(pen); }
            }
            finally { DeletePath(path); }
        }

        internal void FillCircle(double cx, double cy, double radius, uint colour)
        {
            IntPtr brush = Solid(colour);
            try { SurfaceGdip.GdipFillEllipse(Graphics, brush, (float)(cx - radius), (float)(cy - radius), (float)(radius * 2), (float)(radius * 2)); }
            finally { DoneWith(brush); }
        }

        internal void FillPolygon(IList<double[]> points, uint colour)
        {
            IntPtr brush = Solid(colour);
            try
            {
                var flat = new float[points.Count * 2];
                for (int i = 0; i < points.Count; i++) { flat[2 * i] = (float)points[i][0]; flat[2 * i + 1] = (float)points[i][1]; }
                SurfaceGdip.GdipFillPolygon2(Graphics, brush, flat, points.Count);
            }
            finally { DoneWith(brush); }
        }

        internal void FillEllipse(double cx, double cy, double rx, double ry, uint colour)
        {
            IntPtr brush = Solid(colour);
            try { SurfaceGdip.GdipFillEllipse(Graphics, brush, (float)(cx - rx), (float)(cy - ry), (float)(rx * 2), (float)(ry * 2)); }
            finally { DoneWith(brush); }
        }

        internal void StrokeLines(IList<double[]> points, uint colour, double width)
        {
            IntPtr pen = Pen(colour, width);
            try
            {
                var flat = new SurfaceGdip.PointF[points.Count];
                for (int i = 0; i < points.Count; i++) { flat[i].X = (float)points[i][0]; flat[i].Y = (float)points[i][1]; }
                SurfaceGdip.GdipDrawLines(Graphics, pen, flat, points.Count);
            }
            finally { DeletePen(pen); }
        }

        internal void ClipRound(double[] rect, double radius)
        {
            IntPtr path = Path(rect, radius);
            try { SurfaceGdip.GdipSetClipPath(Graphics, path, 0); }
            finally { DeletePath(path); }
        }

        internal void ClipRect(double[] rect)
        {
            SurfaceGdip.GdipSetClipRect(Graphics, (float)rect[0], (float)rect[1], (float)(rect[2] - rect[0]), (float)(rect[3] - rect[1]), 1);
        }

        internal void ClipNone()
        {
            SurfaceGdip.GdipResetClip(Graphics);
        }

        /// `rect` filled with `rgb`, whole at x = solidX and see-through at x = clearX (fade).
        internal void Fade(double[] rect, double solidX, double clearX, int[] rgb)
        {
            float top = (float)rect[1];
            var one = new[] { (float)solidX, top };
            var other = new[] { (float)clearX, top };
            IntPtr brush;
            Check(SurfaceGdip.GdipCreateLineBrush(one, other, SurfaceNative.Pack(rgb[0], rgb[1], rgb[2], 1.0),
                                                  SurfaceNative.Pack(rgb[0], rgb[1], rgb[2], 0.0), 3, out brush), "GdipCreateLineBrush");
            try { SurfaceGdip.GdipFillRectangle(Graphics, brush, (float)rect[0], top, (float)(rect[2] - rect[0]), (float)(rect[3] - rect[1])); }
            finally { DeleteBrush(brush); }
        }

        internal void Arc(double cx, double cy, double radius, double start, double sweep, uint colour, double width)
        {
            IntPtr pen = Pen(colour, width);
            try
            {
                SurfaceGdip.GdipDrawArc(Graphics, pen, (float)(cx - radius), (float)(cy - radius), (float)(radius * 2), (float)(radius * 2),
                                        (float)start, (float)sweep);
            }
            finally { DeletePen(pen); }
        }

        /// A soft round light of `radius` (glow): `rgb` at `opacity` times each stop's factor, the stops turned round
        /// because a GDI+ path gradient counts from the edge inward.
        internal void Glow(double cx, double cy, double radius, IList<double[]> stops, int[] rgb, double opacity)
        {
            if (radius <= 0 || opacity <= 0) return;
            IntPtr path;
            Check(SurfaceGdip.GdipCreatePath(0, out path), "GdipCreatePath");
            try
            {
                SurfaceGdip.GdipAddPathEllipse(path, (float)(cx - radius), (float)(cy - radius), (float)(radius * 2), (float)(radius * 2));
                IntPtr brush;
                Check(SurfaceGdip.GdipCreatePathGradientFromPath(path, out brush), "GdipCreatePathGradientFromPath");
                try
                {
                    var centre = new SurfaceGdip.PointF { X = (float)cx, Y = (float)cy };
                    SurfaceGdip.GdipSetPathGradientCenterPoint(brush, ref centre);
                    int count = stops.Count;
                    var colours = new uint[count];
                    var positions = new float[count];
                    for (int i = 0; i < count; i++)
                    {
                        double[] stop = stops[count - 1 - i];
                        colours[i] = SurfaceNative.Pack(rgb[0], rgb[1], rgb[2], opacity * stop[1]);
                        positions[i] = (float)(1.0 - stop[0]);
                    }
                    SurfaceGdip.GdipSetPathGradientPresetBlend(brush, colours, positions, count);
                    SurfaceGdip.GdipFillPath(Graphics, brush, path);
                }
                finally { DeleteBrush(brush); }
            }
            finally { DeletePath(path); }
        }
    }

    /// One shadow in its colour: a coverage mask as a premultiplied GDI+ image (_ShadowImage).
    internal sealed class SurfaceShadowImage : IDisposable
    {
        internal readonly int Width, Height;
        internal readonly int[] Centre;
        internal readonly double Extent;
        private readonly byte[] pixels;
        private GCHandle pin;
        internal IntPtr Bitmap;

        /// `coverage` is the mask's bytes, a row of `width` after another; `centre` its middle pixel.
        internal SurfaceShadowImage(byte[] coverage, int width, int height, int[] centre, double extent, int[] rgb, double strength)
        {
            Width = width;
            Height = height;
            Centre = centre;
            Extent = extent;
            var alpha = new byte[256];
            for (int level = 0; level < 256; level++) alpha[level] = (byte)Math.Min(255, (int)(strength * level + 0.5));
            var tables = new byte[3][];
            int[] channels = { rgb[2], rgb[1], rgb[0] };
            for (int c = 0; c < 3; c++)
            {
                tables[c] = new byte[256];
                for (int level = 0; level < 256; level++) tables[c][level] = (byte)(int)(channels[c] * alpha[level] / 255.0 + 0.5);
            }
            pixels = new byte[4 * width * height];
            for (int i = 0; i < width * height; i++)
            {
                byte value = coverage[i];
                pixels[4 * i] = tables[0][value];
                pixels[4 * i + 1] = tables[1][value];
                pixels[4 * i + 2] = tables[2][value];
                pixels[4 * i + 3] = alpha[value];
            }
            pin = GCHandle.Alloc(pixels, GCHandleType.Pinned);
            int status = SurfaceGdip.GdipCreateBitmapFromScan0(width, height, width * 4, SurfaceGdip.PixelFormat32bppPArgb,
                                                               pin.AddrOfPinnedObject(), out Bitmap);
            if (status != 0)
            {
                pin.Free();
                throw new InvalidOperationException("GdipCreateBitmapFromScan0 failed (" + status + ")");
            }
            SurfaceGdip.Made(1);
        }

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

        /// Into (left, top, width, height): the corners as they are, the middle row and column stretched (stamp).
        internal void Stamp(SurfacePainter paint, int left, int top, int width, int height, bool middle = true)
        {
            int cx = Centre[0], cy = Centre[1];
            int right = Width - cx - 1, bottom = Height - cy - 1;
            int[][] columns = { new[] { left, cx, 0 }, new[] { left + cx, width - cx - right, cx }, new[] { left + width - right, right, cx + 1 } };
            int[][] rows = { new[] { top, cy, 0 }, new[] { top + cy, height - cy - bottom, cy }, new[] { top + height - bottom, bottom, cy + 1 } };
            for (int row = 0; row < 3; row++)
                for (int column = 0; column < 3; column++)
                {
                    int x = columns[column][0], wide = columns[column][1], sourceX = columns[column][2];
                    int y = rows[row][0], tall = rows[row][1], sourceY = rows[row][2];
                    if (wide <= 0 || tall <= 0 || (row == 1 && column == 1 && !middle)) continue;
                    SurfaceGdip.GdipDrawImageRectRectI(paint.Graphics, Bitmap, x, y, wide, tall, sourceX, sourceY,
                                                       column == 1 ? 1 : wide, row == 1 ? 1 : tall, SurfaceNative.UNIT_PIXEL,
                                                       IntPtr.Zero, IntPtr.Zero, IntPtr.Zero);
                }
        }
    }
}
