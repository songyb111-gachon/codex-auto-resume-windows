// Codex Auto Resume - the popup on screen as its card: the card's window, the shadow below it, and its still
// (v0.6.27, S6.3).
//
// The C# port of src/codex_auto_resume/ui/popup/layers.py's drawing and its on-screen half, call for call: the shadows'
// rule (float_shadows is the notification card's, CardPlan.FloatShadows, as the Python holds the two equal; float_reach,
// card_shadows, card_radius), stamp_shadows with its kept images, cut_card, _over, still_pad and card_still (offscreen, for
// the pictures and the tests), update (one UpdateLayeredWindowIndirect, only the dirty rows) and CardLayers (the shadow
// window and the card window's pushes, stands and shows). The window's side of it (PopupCard: _redraw, _push, _plain and
// the plain window's corner, frame and class shadow) is the popup window's, gui/PopupWindow.cs.
using System;
using System.Collections.Generic;
using System.Drawing;
using System.Runtime.InteropServices;

namespace CodexAutoResume
{
    internal static class SurfaceLayers
    {
        internal const uint ULW_ALPHA = 0x2;
        internal const byte AC_SRC_ALPHA = 0x1;
        internal const uint SWP_NOMOVE_NOSIZE = 0x0002 | 0x0001;
        internal const uint WS_EX_NOACTIVATE = 0x08000000, WS_EX_TRANSPARENT = 0x00000020;
        /// The card's picture is owed (PopupCard._redraw).
        internal const int WM_POPUP_PAINT = SurfaceNative.WM_APP + 4;
        internal const int GCL_STYLE = -26;
        /// A dirty rectangle that uploads no pixel: a move or a fade (NOTHING).
        internal static readonly int[] Nothing = new int[4];

        /// float_shadows: the card recipe's outer shadows as they may be drawn over a wallpaper.
        internal static List<FloatShadow> FloatShadows(string theme, string design = "soft")
        {
            return CardPlan.FloatShadows(theme, design);
        }

        /// How far the shadows reach past the card, in device pixels (three sigmas), and 0 for none (float_reach).
        internal static int FloatReach(List<FloatShadow> shadows, double scale)
        {
            if (shadows.Count == 0) return 0;
            return CardPlan.ShadowMargin(shadows, scale);
        }

        /// What floats under the card: nothing in High Contrast, else float_shadows (card_shadows).
        internal static List<FloatShadow> CardShadows(string theme, string design, bool contrast)
        {
            return contrast ? new List<FloatShadow>() : FloatShadows(theme, design);
        }

        /// The card's corner in device px, as the renderer rounds it in its design (card_radius).
        internal static double CardRadius(SurfaceRenderer renderer, SurfacePlan plan)
        {
            foreach (PlanItem item in plan.Items)
                if (item.Kind == "card") return renderer.Corner(item, plan.Scale);
            throw new InvalidOperationException("the plan has no card");
        }

        private static string ImageKey(string maskKey, FloatShadow shadow)
        {
            return maskKey + "|" + shadow.Colour + "|" + shadow.Alpha.ToString("R", System.Globalization.CultureInfo.InvariantCulture);
        }

        /// `shadows` under a card of `size` whose corner is at `origin` in `canvas` (PARGB), from images kept in
        /// `images` by the mask's own shape and the colour; an image this draw does not use is let go (stamp_shadows).
        internal static void StampShadows(SurfaceCanvas canvas, List<FloatShadow> shadows, int[] size, double radius, double scale,
                                          int[] origin, Dictionary<string, SurfaceShadowImage> images)
        {
            int width = size[0], height = size[1];
            var used = new HashSet<string>();
            using (var paint = new SurfacePainter(canvas, SurfaceGdip.PixelFormat32bppPArgb))
            {
                for (int i = shadows.Count - 1; i >= 0; i--)
                {
                    FloatShadow shadow = shadows[i];
                    ShadowMask mask = SurfaceElevation.LiftCoverage(width, height, radius, shadow.Blur * scale);
                    string key = ImageKey(mask.Key, shadow);
                    used.Add(key);
                    SurfaceShadowImage image;
                    if (!images.TryGetValue(key, out image))
                        image = images[key] = new SurfaceShadowImage(mask.Coverage, mask.Width, mask.Height, mask.Centre, mask.Extent,
                                                                     SurfaceTheme.Rgb(ColorTranslator.FromHtml(shadow.Colour)), shadow.Alpha);
                    int extent = (int)image.Extent;
                    image.Stamp(paint, origin[0] - extent + SurfaceElevation.ShadowStep(shadow.Dx * scale),
                                origin[1] - extent + SurfaceElevation.ShadowStep(shadow.Dy * scale), width + 2 * extent, height + 2 * extent, false);
                }
            }
            foreach (string key in new List<string>(images.Keys))
            {
                if (used.Contains(key)) continue;
                images[key].Dispose();
                images.Remove(key);
            }
        }

        /// Nothing of the shadow under the card: every pixel the card covers wholly made clear in `picture` (cut_card).
        internal static void CutCard(SurfaceCanvas picture, byte[] ground, int groundWidth, int[] card, int[] origin)
        {
            int left = card[0], top = card[1], right = card[2], bottom = card[3];
            int width = right - left;
            SurfaceNative.GdiFlush();
            for (int row = 0; row < bottom - top; row++)
            {
                int start = ((top + row) * groundWidth + left) * 4 + 3;
                int first = -1, last = -1;
                for (int x = 0; x < width; x++)
                {
                    int at = start + x * 4;
                    if (at >= ground.Length) break;
                    if (ground[at] == 0xFF)
                    {
                        if (first < 0) first = x;
                        last = x;
                    }
                }
                if (first < 0) continue;
                int offset = ((origin[1] + row) * picture.Width + origin[0] + first) * 4;
                Marshal.Copy(new byte[(last - first + 1) * 4], 0, picture.Bits + offset, (last - first + 1) * 4);
            }
        }

        /// The card's rectangle of `source` (premultiplied) laid over `canvas` with its corner at `at`, by GDI+ (_over).
        internal static void Over(SurfaceCanvas canvas, SurfaceCanvas source, int[] card, int[] at)
        {
            int left = card[0], top = card[1], width = card[2] - card[0], height = card[3] - card[1];
            SurfaceNative.GdiFlush();
            IntPtr bitmap;
            int status = SurfaceGdip.GdipCreateBitmapFromScan0(width, height, source.Width * 4, SurfaceGdip.PixelFormat32bppPArgb,
                                                               source.Bits + (top * source.Width + left) * 4, out bitmap);
            if (status != 0) throw new InvalidOperationException("GdipCreateBitmapFromScan0 failed (" + status + ")");
            SurfaceGdip.Made(1);
            try
            {
                using (var paint = new SurfacePainter(canvas, SurfaceGdip.PixelFormat32bppPArgb))
                    SurfaceGdip.GdipDrawImageRectRectI(paint.Graphics, bitmap, at[0], at[1], width, height, 0, 0, width, height,
                                                       SurfaceNative.UNIT_PIXEL, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero);
            }
            finally
            {
                SurfaceGdip.GdipDisposeImage(bitmap);
                SurfaceGdip.Made(-1);
            }
        }

        /// How much transparent room a still keeps round the card: the deepest theme's Soft shadow (still_pad).
        internal static int StillPad(double scale)
        {
            int pad = int.MinValue;
            foreach (string theme in SurfaceTheme.Themes) pad = Math.Max(pad, FloatReach(FloatShadows(theme), scale));
            return pad;
        }

        /// (width, height, premultiplied BGRA): the card the renderer last drew alone and its shadow, over nothing, with
        /// `pad` px of room round the card (card_still).
        internal static object[] CardStill(SurfaceRenderer renderer, SurfacePlan plan, int? pad = null)
        {
            double scale = plan.Scale;
            int[] card = plan.Card;
            int room = pad ?? StillPad(scale);
            int width = card[2] - card[0], height = card[3] - card[1];
            var images = new Dictionary<string, SurfaceShadowImage>();
            var canvas = new SurfaceCanvas();
            try
            {
                canvas.Ensure(width + 2 * room, height + 2 * room);
                SurfaceNative.GdiFlush();
                Marshal.Copy(new byte[canvas.Width * canvas.Height * 4], 0, canvas.Bits, canvas.Width * canvas.Height * 4);
                List<FloatShadow> shadows = CardShadows(renderer.ThemeName(), renderer.DesignName(), renderer.Contrast);
                if (shadows.Count > 0)
                    StampShadows(canvas, shadows, new[] { width, height }, CardRadius(renderer, plan), scale, new[] { room, room }, images);
                Over(canvas, renderer.Canvas, card, new[] { room, room });
                SurfaceNative.GdiFlush();
                return new object[] { canvas.Width, canvas.Height, canvas.Pixels() };
            }
            finally
            {
                foreach (SurfaceShadowImage image in images.Values) image.Dispose();
                canvas.Dispose();
            }
        }

        // ------------------------------------------------------------------------------ on screen
        [StructLayout(LayoutKind.Sequential)]
        internal struct UPDATELAYEREDWINDOWINFO
        {
            internal uint CbSize;
            internal IntPtr HdcDst, PptDst, Psize, HdcSrc, PptSrc;
            internal uint CrKey;
            internal IntPtr Pblend;
            internal uint DwFlags;
            internal IntPtr PrcDirty;
        }

        [DllImport("user32.dll", SetLastError = true)]
        private static extern bool UpdateLayeredWindowIndirect(IntPtr hwnd, ref UPDATELAYEREDWINDOWINFO info);

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
        private static extern IntPtr GetModuleHandleW(string name);

        [DllImport("kernel32.dll", CharSet = CharSet.Ansi)]
        private static extern IntPtr GetProcAddress(IntPtr module, string name);

        /// Whether this Windows has UpdateLayeredWindowIndirect (Vista on), which the card is put on screen with
        /// (PopupCard._can_be_card).
        internal static bool CanBeCard()
        {
            IntPtr user32 = GetModuleHandleW("user32.dll");
            return user32 != IntPtr.Zero && GetProcAddress(user32, "UpdateLayeredWindowIndirect") != IntPtr.Zero;
        }

        private static IntPtr Put<T>(T value, List<IntPtr> made) where T : struct
        {
            IntPtr memory = Marshal.AllocHGlobal(Marshal.SizeOf(typeof(T)));
            made.Add(memory);
            Marshal.StructureToPtr(value, memory, false);
            return memory;
        }

        /// One UpdateLayeredWindowIndirect: the window at `at` (screen px) at `alpha` (0-255), its picture `size` px of
        /// `dc` from `source`; only the `dirty` rectangle of it (window px) uploaded when one is given (update). Through
        /// SurfaceScreen, so the probe mode records it instead.
        internal static bool Update(IntPtr hwnd, double[] at, double alpha, IntPtr dc, int[] size, int[] source = null, int[] dirty = null)
        {
            return SurfaceScreen.Update(hwnd, at, alpha, dc, size, source ?? new[] { 0, 0 }, dirty);
        }

        /// The call itself (SurfaceScreen.Update on a live host).
        internal static bool UpdateNow(IntPtr hwnd, double[] at, double alpha, IntPtr dc, int[] size, int[] source, int[] dirty)
        {
            source = source ?? new[] { 0, 0 };
            var made = new List<IntPtr>();
            try
            {
                var info = new UPDATELAYEREDWINDOWINFO();
                info.CbSize = (uint)Marshal.SizeOf(typeof(UPDATELAYEREDWINDOWINFO));
                info.PptDst = Put(new SurfaceNative.POINT { X = (int)at[0], Y = (int)at[1] }, made);
                info.Pblend = Put(new SurfaceNative.BLENDFUNCTION { BlendOp = 0, BlendFlags = 0,
                                                                    SourceConstantAlpha = (byte)Math.Max(0, Math.Min(255, (int)alpha)),
                                                                    AlphaFormat = AC_SRC_ALPHA }, made);
                info.DwFlags = ULW_ALPHA;
                info.HdcSrc = dc;
                info.Psize = Put(new SurfaceNative.SIZE { Cx = size[0], Cy = size[1] }, made);
                info.PptSrc = Put(new SurfaceNative.POINT { X = source[0], Y = source[1] }, made);
                if (dirty != null) info.PrcDirty = Put(new SurfaceNative.RECT(dirty[0], dirty[1], dirty[2], dirty[3]), made);
                using (new SurfaceNative.PerMonitorDpi()) return UpdateLayeredWindowIndirect(hwnd, ref info);
            }
            finally
            {
                foreach (IntPtr memory in made) Marshal.FreeHGlobal(memory);
            }
        }
    }

    /// The popup's two pictures on screen: its own window, which is the card, and the shadow window it is owned by
    /// (CardLayers). Owns the shadow window, its picture and its shadow images; the card window is the popup's.
    internal sealed class CardLayers : IDisposable
    {
        internal IntPtr ShadowHwnd;
        internal SurfaceCanvas Picture;
        internal readonly Dictionary<string, SurfaceShadowImage> Images = new Dictionary<string, SurfaceShadowImage>();
        internal List<FloatShadow> Shadows = new List<FloatShadow>();
        internal int Margin;
        private string shadowKey;
        private bool shadowOwed = true;
        private IntPtr bodyDc;
        private int[] bodySize, bodySource;
        internal bool Shown;
        private bool shadowShown;
        private string shadowAt;

        internal CardLayers(IntPtr shadowHwnd)
        {
            ShadowHwnd = shadowHwnd;
            Picture = new SurfaceCanvas();
        }

        private static string ShadowsKey(List<FloatShadow> shadows)
        {
            var key = new System.Text.StringBuilder();
            foreach (FloatShadow s in shadows)
                key.Append(string.Join(",", new[] { s.Dx.ToString("R"), s.Dy.ToString("R"), s.Blur.ToString("R"), s.Colour, s.Alpha.ToString("R") })).Append(';');
            return key.ToString();
        }

        /// The shadow picture for this plan's card, drawn again only when its size, scale or look changed (shade).
        internal bool Shade(SurfaceRenderer renderer, SurfacePlan plan)
        {
            List<FloatShadow> shadows = SurfaceLayers.CardShadows(renderer.ThemeName(), renderer.DesignName(), renderer.Contrast);
            int[] card = plan.Card;
            double scale = plan.Scale;
            int[] size = { card[2] - card[0], card[3] - card[1] };
            double radius = SurfaceLayers.CardRadius(renderer, plan);
            string key = ShadowsKey(shadows) + "|" + size[0] + "x" + size[1] + "|" + radius.ToString("R") + "|" + scale.ToString("R");
            if (key == shadowKey) return false;
            Shadows = shadows;
            Margin = SurfaceLayers.FloatReach(shadows, scale);
            if (shadows.Count > 0)
            {
                Picture.Ensure(size[0] + 2 * Margin, size[1] + 2 * Margin);
                SurfaceNative.GdiFlush();
                Marshal.Copy(new byte[Picture.Width * Picture.Height * 4], 0, Picture.Bits, Picture.Width * Picture.Height * 4);
                SurfaceLayers.StampShadows(Picture, shadows, size, radius, scale, new[] { Margin, Margin }, Images);
                SurfaceLayers.CutCard(Picture, renderer.GroundPixels, renderer.Canvas.Width, card, new[] { Margin, Margin });
            }
            shadowKey = key;
            shadowOwed = true;
            return true;
        }

        private bool SameBody(IntPtr dc, int[] size, int[] source)
        {
            return bodySize != null && bodyDc == dc && bodySize[0] == size[0] && bodySize[1] == size[1]
                && bodySource[0] == source[0] && bodySource[1] == source[1];
        }

        /// The card window at `at` at `alpha`, its picture the card's rectangle of `canvas`: whole, or only `rows` when its
        /// size is what it was; then the shadow (push).
        internal bool Push(IntPtr hwnd, SurfaceCanvas canvas, SurfacePlan plan, double[] at, double alpha, int[] rows = null)
        {
            int[] card = plan.Card;
            int[] size = { card[2] - card[0], card[3] - card[1] };
            int[] source = { card[0], card[1] };
            int[] dirty = null;
            if (rows != null && SameBody(canvas.Dc, size, source))
            {
                int top = Math.Max(rows[0], card[1]) - card[1], bottom = Math.Min(rows[1], card[3]) - card[1];
                dirty = bottom <= top ? SurfaceLayers.Nothing : new[] { 0, top, size[0], bottom };
            }
            if (!SurfaceLayers.Update(hwnd, at, alpha, canvas.Dc, size, source, dirty))
            {
                bodySize = null;
                return false;
            }
            bodyDc = canvas.Dc;
            bodySize = size;
            bodySource = source;
            return StandShadow(at, alpha);
        }

        /// Both windows moved to `at` at `alpha`, nothing uploaded: a frame of the opening (stand).
        internal bool Stand(IntPtr hwnd, double[] at, double alpha)
        {
            if (bodySize == null) return true;
            if (!SurfaceLayers.Update(hwnd, at, alpha, bodyDc, bodySize, bodySource, SurfaceLayers.Nothing)) return false;
            return StandShadow(at, alpha);
        }

        internal bool StandShadow(double[] at, double alpha)
        {
            if (Shown && (Shadows.Count > 0) != shadowShown) ShowShadow();
            if (Shadows.Count == 0) return true;
            double[] where = { at[0] - Margin, at[1] - Margin };
            string place = where[0].ToString("R") + "," + where[1].ToString("R") + "," + alpha.ToString("R");
            bool owed = shadowOwed;
            if (!owed && shadowAt == place) return true;
            bool ok = SurfaceLayers.Update(ShadowHwnd, where, alpha, Picture.Dc, new[] { Picture.Width, Picture.Height }, null,
                                           owed ? null : SurfaceLayers.Nothing);
            shadowOwed = owed && !ok;
            shadowAt = ok ? place : null;
            return ok;
        }

        /// The shadow window raised to the top of the topmost windows and shown (show).
        internal void Show()
        {
            SurfaceScreen.SetWindowPos(ShadowHwnd, SurfaceNative.HWND_TOPMOST, 0, 0, 0, 0,
                                       SurfaceNative.SWP_NOACTIVATE | SurfaceLayers.SWP_NOMOVE_NOSIZE);
            ShowShadow();
            Shown = true;
        }

        private void ShowShadow()
        {
            SurfaceScreen.ShowWindow(ShadowHwnd, Shadows.Count > 0 ? SurfaceNative.SW_SHOWNOACTIVATE : SurfaceNative.SW_HIDE);
            shadowShown = Shadows.Count > 0;
        }

        internal void Hide()
        {
            SurfaceScreen.ShowWindow(ShadowHwnd, SurfaceNative.SW_HIDE);
            Shown = shadowShown = false;
        }

        /// What is on screen is no longer known: the next push is whole (forget).
        internal void Forget()
        {
            bodySize = null;
            shadowAt = null;
        }

        /// The shadow window and everything drawn for it (close).
        public void Dispose()
        {
            foreach (SurfaceShadowImage image in Images.Values) image.Dispose();
            Images.Clear();
            IntPtr hwnd = ShadowHwnd;
            ShadowHwnd = IntPtr.Zero;
            if (hwnd != IntPtr.Zero) SurfaceNative.DestroyWindow(hwnd);
            if (Picture != null)
            {
                Picture.Dispose();
                Picture = null;
            }
        }
    }
}
