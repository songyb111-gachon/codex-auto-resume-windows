// Codex Auto Resume - the status light and the mark, drawn as the icon and the popup draw them.
//
// The same brand tables the notification-area icon's frames are composed from, so the window's
// light and the icon's are the same light at the same moment in the same cycle.

using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;

namespace CodexAutoResume
{
    /// The status light: a flat dot whose colour says what the watcher is doing, and that blinks
    /// the way the notification-area icon's head does to say it is alive.
    ///
    /// The dot keeps the size it has always had. Every state in which the watcher runs with
    /// recovery on is the brand's cyan, the colour the dot had before v0.6.3; a stopped or
    /// unknown watcher and a pause keep their greys and never move; a watcher that runs but is
    /// not well is amber, and a failure red. Monitoring, recovering, attention and a failure run
    /// brand's cycle for as long as they last - attention slowest, a failure quickest: the dot
    /// dims toward the card and comes back with nothing spreading, and only then, lit, a small
    /// glow spreads from its edge and draws back in. Waiting breathes on monitoring's rhythm (until
    /// v0.6.9 it held lit and still); checking holds lit and turns a small arc. Until v0.6.8 a problem ran the cycle once and held. brand.glow() defines every number, for the popup and the
    /// panel too. With motion reduced nothing moves and the dot holds lit with no glow; in High
    /// Contrast the dot is a system colour, unlit. v0.6.10: in the design too (Soft.LightStill, Palette.Halo) -
    /// Still holds it as Reduce motion does, and Plain dims it on its breath with no glow, which Classic keeps.
    internal sealed class HaloDot : Control
    {
        private string state = "idle";
        private readonly Timer timer = new Timer();
        private readonly System.Diagnostics.Stopwatch clock = System.Diagnostics.Stopwatch.StartNew();
        private double enteredAt;

        internal HaloDot()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                     ControlStyles.UserPaint | ControlStyles.ResizeRedraw | ControlStyles.SupportsTransparentBackColor, true);
            TabStop = false;
            AccessibleRole = AccessibleRole.Graphic;
            timer.Interval = 33;
            timer.Tick += delegate { Invalidate(); if (!ShouldRun()) timer.Stop(); };
        }

        internal string State
        {
            get { return state; }
            set
            {
                string next = string.IsNullOrEmpty(value) ? "idle" : value;
                if (next == state) return;
                state = next;
                enteredAt = clock.Elapsed.TotalMilliseconds;
                Invalidate();
                Sync();
            }
        }

        /// How far the largest glow reaches from the dot's centre, in device pixels: the room a
        /// column holding the light keeps on each side of it.
        internal static int Extent
        {
            get { return (int)Math.Ceiling(Soft.PxF(Brand.GlowExtent)); }
        }

        /// Loops for as long as the state lasts.
        internal static bool Loops(string state)
        {
            // Brand's own rule, so the window's timer cannot drift from what brand.glow_moves says moves.
            return Brand.GlowMoves(state, 0, false);
        }

        /// The glow's opacity for one frame, brand.glow()'s "opacity", or 0 when there is no glow.
        /// The cycle follows `elapsedMs`; `sinceEnteredMs` is read by nothing since v0.6.8, when the
        /// one-time pulse went. Pure, so the rule can be checked without drawing.
        internal static double HaloOpacity(string state, double elapsedMs, double sinceEnteredMs, bool reduced)
        {
            double dim, opacity, spread, arc;
            return Brand.Glow(state, elapsedMs, sinceEnteredMs, reduced, out dim, out opacity, out spread, out arc) ? opacity : 0;
        }

        /// How far the dot is drawn from its colour toward the card for one frame, or 0.
        internal static double HaloDim(string state, double elapsedMs, double sinceEnteredMs, bool reduced)
        {
            double dim, opacity, spread, arc;
            return Brand.Glow(state, elapsedMs, sinceEnteredMs, reduced, out dim, out opacity, out spread, out arc) ? dim : 0;
        }

        /// How far out the glow is for one frame, 0 to 1 of Brand.GlowReach past the dot's edge.
        internal static double HaloSpread(string state, double elapsedMs, double sinceEnteredMs, bool reduced)
        {
            double dim, opacity, spread, arc;
            return Brand.Glow(state, elapsedMs, sinceEnteredMs, reduced, out dim, out opacity, out spread, out arc) ? spread : 0;
        }

        /// Where the checking arc starts for one frame, in degrees, or -1 when there is none.
        internal static double HaloArc(string state, double elapsedMs, double sinceEnteredMs, bool reduced)
        {
            double dim, opacity, spread, arc;
            return Brand.Glow(state, elapsedMs, sinceEnteredMs, reduced, out dim, out opacity, out spread, out arc) ? arc : -1;
        }

        internal static Color DotColour(string state)
        {
            return DotColour(state, Palette.Contrast);
        }

        /// The dot's fill: the brand's colour for the state in the theme in effect, or in High
        /// Contrast its system colour. Comparisons, not a switch, inside Brand: the in-box compiler
        /// turns a string switch with enough cases into a dictionary held by a class it names with a
        /// fresh random GUID, and that one name made two builds of the same source differ.
        internal static Color DotColour(string state, bool contrast)
        {
            return contrast ? Brand.StatusSystem(state) : Tokens.Dark ? Brand.Dark.StatusFill(state) : Brand.StatusFill(state);
        }

        private bool ShouldRun()
        {
            if (!Visible || !IsHandleCreated || Soft.LightStill) return false;
            Form form = FindForm();
            if (form != null && form.WindowState == FormWindowState.Minimized) return false;
            if (Soft.StillLightMs >= 0) return false;      // held still for a picture
            return Brand.GlowMoves(state, clock.Elapsed.TotalMilliseconds - enteredAt, false);
        }

        /// Starts or stops the timer to match what should be moving. Called whenever the
        /// state, the visibility or the window's size changes.
        internal void Sync()
        {
            if (ShouldRun()) { if (!timer.Enabled) timer.Start(); }
            else if (timer.Enabled) timer.Stop();
        }

        protected override void OnVisibleChanged(EventArgs e) { base.OnVisibleChanged(e); Sync(); }
        protected override void OnHandleCreated(EventArgs e) { base.OnHandleCreated(e); Sync(); }
        protected override void OnHandleDestroyed(EventArgs e) { timer.Stop(); base.OnHandleDestroyed(e); }

        protected override void Dispose(bool disposing)
        {
            if (disposing) { timer.Stop(); timer.Dispose(); }
            base.Dispose(disposing);
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            g.Clear(Parent != null ? Ground.Colour(Parent) : Palette.Card);
            double since = Soft.StillLightMs >= 0 ? Soft.StillLightMs
                                                  : clock.Elapsed.TotalMilliseconds - enteredAt;
            double dim, opacity, spread, arc;
            bool lit = Brand.Glow(state, since, since, Soft.LightStill, out dim, out opacity, out spread, out arc);
            Color colour = DotColour(state);
            float cx = Width / 2f, cy = Height / 2f, dot = Soft.PxF(Brand.StatusDotRadius);
            GraphicsState saved = g.Save();
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.PixelOffsetMode = PixelOffsetMode.Half;
            // The glow in a design that has one (Palette.Halo: Soft, Classic), never in High Contrast; the dimming
            // below is the breath itself, which Plain keeps without a glow.
            if (lit && opacity > 0 && Palette.Halo)
                Glow(g, cx, cy, Soft.PxF(Brand.StatusDotRadius + Brand.GlowReach * spread), colour, opacity);
            // Dimmed, the dot is its colour over the card it was cleared to: that far toward the ground.
            Color fill = lit && dim > 0 && !Palette.Contrast ? Soft.WithAlpha(colour, 1 - dim) : colour;
            using (var brush = new SolidBrush(fill)) g.FillEllipse(brush, cx - dot, cy - dot, dot * 2, dot * 2);
            if (lit && arc >= 0)
            {
                float radius = Soft.PxF(Brand.StatusDotRadius + Brand.GlowArcGap);
                using (var pen = new Pen(Palette.Contrast ? colour : Soft.WithAlpha(colour, Brand.GlowArcAlpha), Soft.PxF(Brand.GlowArcWidth)))
                {
                    pen.StartCap = LineCap.Round;
                    pen.EndCap = LineCap.Round;
                    g.DrawArc(pen, cx - radius, cy - radius, radius * 2, radius * 2, (float)arc, (float)Brand.GlowArcSweep);
                }
            }
            g.Restore(saved);
        }

        /// The glow, brand.glow_stops: the dot's colour at `opacity` times GlowEdgeAlpha from the
        /// centre out to where the dot's edge is at the peak, then fading through brand.GLOW's stops
        /// to nothing at `outer`. The stops are fractions of `outer`, so a smaller spread is the same
        /// falloff drawn smaller. A path gradient counts its positions from the edge inward, so the
        /// stops are written in reverse.
        private static void Glow(Graphics g, float cx, float cy, float outer, Color colour, double opacity)
        {
            if (outer <= 0) return;
            double dot = Brand.StatusDotRadius, whole = Brand.GlowExtent;
            using (var path = new GraphicsPath())
            {
                path.AddEllipse(cx - outer, cy - outer, outer * 2, outer * 2);
                using (var brush = new PathGradientBrush(path))
                {
                    brush.CenterPoint = new PointF(cx, cy);
                    brush.CenterColor = Soft.WithAlpha(colour, opacity * Brand.GlowEdgeAlpha);
                    brush.SurroundColors = new[] { Soft.WithAlpha(colour, 0) };
                    var blend = new ColorBlend(5);
                    blend.Positions[0] = 0f;
                    blend.Colors[0] = Soft.WithAlpha(colour, 0);
                    blend.Positions[1] = (float)(1 - (dot + Brand.GlowReach * Brand.GlowFarAt) / whole);
                    blend.Colors[1] = Soft.WithAlpha(colour, opacity * Brand.GlowFarAlpha);
                    blend.Positions[2] = (float)(1 - (dot + Brand.GlowReach * Brand.GlowNearAt) / whole);
                    blend.Colors[2] = Soft.WithAlpha(colour, opacity * Brand.GlowNearAlpha);
                    blend.Positions[3] = (float)(1 - dot / whole);
                    blend.Colors[3] = Soft.WithAlpha(colour, opacity * Brand.GlowEdgeAlpha);
                    blend.Positions[4] = 1f;
                    blend.Colors[4] = Soft.WithAlpha(colour, opacity * Brand.GlowEdgeAlpha);
                    brush.InterpolationColors = blend;
                    g.FillPath(brush, path);
                }
            }
        }
    }

    /// The notification-area icon's frames at one size, as Brand.Mark carries them (v0.6.5): the mark without its
    /// head, and for each head position the samples its head draws over it - tray.IconFrames' own, written by
    /// build/make_brand.py. Compose is IconFrames.compose's arithmetic, so a frame here is the icon's frame, pixel for
    /// pixel, and nothing is rendered in the window.
    internal sealed class MarkFrames
    {
        [StructLayout(LayoutKind.Sequential)]
        private struct BitmapHeader
        {
            internal int Size;
            internal int Width;
            internal int Height;
            internal short Planes;
            internal short BitCount;
            internal int Compression;
            internal int SizeImage;
            internal int XPelsPerMeter;
            internal int YPelsPerMeter;
            internal int ColoursUsed;
            internal int ColoursImportant;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct IconInfo
        {
            [MarshalAs(UnmanagedType.Bool)] internal bool Icon;
            internal int HotspotX;
            internal int HotspotY;
            internal IntPtr Mask;
            internal IntPtr Colour;
        }

        [DllImport("gdi32.dll")]
        private static extern IntPtr CreateDIBSection(IntPtr dc, ref BitmapHeader header, int usage, out IntPtr bits,
                                                      IntPtr section, int offset);

        [DllImport("gdi32.dll")]
        private static extern IntPtr CreateBitmap(int width, int height, int planes, int bitCount, byte[] bits);

        [DllImport("gdi32.dll")]
        private static extern bool DeleteObject(IntPtr item);

        [DllImport("user32.dll")]
        private static extern IntPtr CreateIconIndirect(ref IconInfo info);

        /// The frames' size in pixels, both ways.
        internal readonly int Size;
        private readonly byte[] ground;
        // Per head position, six numbers for each pixel the head touches: where it is in the frame, how many of its
        // samples fall on the badge, how many of those are the head, and the others' red, green and blue sums.
        private readonly int[][] heads;

        private MarkFrames(int size, byte[] ground, int[][] heads)
        {
            Size = size;
            this.ground = ground;
            this.heads = heads;
        }

        /// The frames for a big icon of `size` px, or null when Brand.Mark has none at that size, or they cannot be read.
        internal static MarkFrames For(int size)
        {
            string text = Brand.Mark.Frames(size);
            if (text == null) return null;
            try
            {
                return Read(size, Convert.FromBase64String(text));
            }
            catch (Exception)
            {
                return null;
            }
        }

        /// build/make_brand.py's mark_frames, read: the ground as runs of equal pixels, then each position's box and
        /// one entry for each of its pixels. Anything that does not add up is refused, never guessed at.
        private static MarkFrames Read(int size, byte[] data)
        {
            var ground = new byte[size * size * 4];
            int at = 0, filled = 0;
            while (filled < ground.Length)
            {
                int count = data[at];
                if (count == 0 || filled + 4 * count > ground.Length) throw new FormatException("the ground's runs");
                for (int i = 0; i < count; i++)
                {
                    Buffer.BlockCopy(data, at + 1, ground, filled, 4);
                    filled += 4;
                }
                at += 5;
            }
            var heads = new int[Brand.Mark.Positions][];
            for (int position = 0; position < heads.Length; position++)
            {
                int left = data[at], top = data[at + 1], right = data[at + 2], bottom = data[at + 3];
                at += 4;
                if (left > right || top > bottom || right > size || bottom > size) throw new FormatException("a head's box");
                var entries = new List<int>();
                for (int y = top; y < bottom; y++)
                {
                    for (int x = left; x < right; x++)
                    {
                        int kind = data[at++];
                        if (kind == Brand.Mark.EntryGround) continue;
                        entries.Add((y * size + x) * 4);
                        if (kind == Brand.Mark.EntryHead)
                        {
                            entries.Add(Brand.Mark.Samples);
                            entries.Add(Brand.Mark.Samples);
                            entries.Add(0);
                            entries.Add(0);
                            entries.Add(0);
                            continue;
                        }
                        if (kind != Brand.Mark.EntrySamples) throw new FormatException("a head pixel's entry");
                        entries.Add(data[at]);
                        entries.Add(data[at + 1]);
                        entries.Add(data[at + 2] | data[at + 3] << 8);
                        entries.Add(data[at + 4] | data[at + 5] << 8);
                        entries.Add(data[at + 6] | data[at + 7] << 8);
                        at += 8;
                    }
                }
                heads[position] = entries.ToArray();
            }
            if (at != data.Length) throw new FormatException("bytes nothing reads");
            return new MarkFrames(size, ground, heads);
        }

        /// One frame: the head at `position` in `head`, top-down BGRA with straight alpha - tray.IconFrames.compose
        /// with no badge.
        internal byte[] Compose(int position, Color head)
        {
            var pixels = (byte[])ground.Clone();
            int[] entries = heads[(position % heads.Length + heads.Length) % heads.Length];
            for (int i = 0; i < entries.Length; i += 6)
            {
                int at = entries[i], covered = entries[i + 1], count = entries[i + 2];
                if (covered == 0)
                {
                    pixels[at] = pixels[at + 1] = pixels[at + 2] = pixels[at + 3] = 0;
                    continue;
                }
                pixels[at] = (byte)((entries[i + 5] + count * head.B) / covered);
                pixels[at + 1] = (byte)((entries[i + 4] + count * head.G) / covered);
                pixels[at + 2] = (byte)((entries[i + 3] + count * head.R) / covered);
                pixels[at + 3] = (byte)(covered * 255 / Brand.Mark.Samples);
            }
            return pixels;
        }

        /// An icon of these pixels (top-down BGRA, straight alpha), as the notification-area icon makes its frames
        /// (tray_popup._icon_from_pixels): a 32-bit colour bitmap and an empty mask. The caller destroys it.
        internal static IntPtr IconFrom(byte[] pixels, int size)
        {
            var header = new BitmapHeader();
            header.Size = Marshal.SizeOf(typeof(BitmapHeader));
            header.Width = size;
            header.Height = -size;
            header.Planes = 1;
            header.BitCount = 32;
            IntPtr bits;
            IntPtr colour = CreateDIBSection(IntPtr.Zero, ref header, 0, out bits, IntPtr.Zero, 0);
            if (colour == IntPtr.Zero) return IntPtr.Zero;
            IntPtr mask = IntPtr.Zero;
            try
            {
                mask = CreateBitmap(size, size, 1, 1, new byte[(size + 15) / 16 * 2 * size]);
                if (mask == IntPtr.Zero || bits == IntPtr.Zero) return IntPtr.Zero;
                Marshal.Copy(pixels, 0, bits, Math.Min(pixels.Length, size * size * 4));
                var info = new IconInfo();
                info.Icon = true;
                info.Mask = mask;
                info.Colour = colour;
                return CreateIconIndirect(ref info);
            }
            finally
            {
                DeleteObject(colour);
                if (mask != IntPtr.Zero) DeleteObject(mask);
            }
        }
    }

    /// The window's taskbar button moves as the notification-area icon does, while the window is open (v0.6.5).
    ///
    /// Windows draws the button from the window's big icon (WM_SETICON, ICON_BIG) - measured on Windows 11 at 150%: the
    /// 48 px big icon, drawn at 36 - and looks at it again only when the window's small icon changes: a new big icon
    /// alone never reached the button. So a frame is the big icon, and then the small icon - the title bar's - is set
    /// again with the other of two handles to one image (Refresh): the title bar keeps every pixel, and the button
    /// takes the frame within a frame's time.
    ///
    /// The state is the notification-area icon's for the watcher the window read (SettingsForm.TrayActivity, told
    /// wherever the header light is, and mapped by Brand.Mark.IconState, tray.ICON_FOR_LIGHT), the rhythms are its
    /// (Brand.Mark.Frame and FrameMs, tray.icon_frame and icon_frame_ms), and the frames are its own pixels at the size
    /// of the window's big icon (MarkFrames). At rest - watching or recovering with
    /// nothing moving - the big icon is the window's own again, the icon it had before v0.6.5; paused or with the
    /// watcher stopped it is grey, a problem its colour. No badge: the header says the rest.
    ///
    /// Nothing moves under this product's Reduce motion, Windows' animation effects or High Contrast (Soft.ReduceMotion,
    /// Theme.ContrastOn), in a design whose light does not breathe (v0.6.10: Still, as the notification-area icon holds
    /// for it - Soft.LightStill), under battery saver, while the session is locked or disconnected, or while the window
    /// is not shown; the states then differ by colour only.
    /// Windows is asked only while the state has something to move, once a second (Sync, on the window's clock), so the
    /// motion is back within a second of the last reason going. With nothing moving there is no timer at all. Every
    /// icon made is destroyed once the window holds the next; the timer stops once the window has closed (FormClosed,
    /// or its handle going), and then the window has its own icons back and nothing of the mark's is left.
    internal sealed class TaskbarMark : IDisposable
    {
        [DllImport("user32.dll")]
        private static extern IntPtr SendMessage(IntPtr window, int message, IntPtr wParam, IntPtr lParam);

        [DllImport("user32.dll")]
        private static extern bool DestroyIcon(IntPtr icon);

        [DllImport("user32.dll")]
        private static extern IntPtr CopyIcon(IntPtr icon);

        [StructLayout(LayoutKind.Sequential)]
        private struct PowerStatus
        {
            internal byte AcLine;
            internal byte Battery;
            internal byte BatteryPercent;
            internal byte SystemStatus;
            internal int BatteryLifeTime;
            internal int BatteryFullLifeTime;
        }

        [DllImport("kernel32.dll")]
        private static extern bool GetSystemPowerStatus(out PowerStatus status);

        [DllImport("wtsapi32.dll", CharSet = CharSet.Unicode)]
        private static extern bool WTSQuerySessionInformationW(IntPtr server, int session, int infoClass, out IntPtr buffer, out int bytes);

        [DllImport("wtsapi32.dll")]
        private static extern void WTSFreeMemory(IntPtr memory);

        private const int WTS_CURRENT_SESSION = -1;
        private const int WTSSessionInfoEx = 25;
        private const int WTSDisconnected = 4;
        private const int WTS_SESSIONSTATE_LOCK = 0;
        private const int WM_GETICON = 0x007F;
        private const int WM_SETICON = 0x0080;
        private const int ICON_SMALL = 0;
        private const int ICON_BIG = 1;

        /// Whether battery saver is on, as the mark reads it: Windows, asked now (BatterySaver). The window never sets
        /// it. Like Soft.WindowsAnimates and Theme.HighContrastOn it is an input a probe stands its own answer in, so the
        /// mark is tested alike on every machine and never by changing Windows' own setting.
        internal static Func<bool> BatterySaverOn = BatterySaver;

        /// Whether this session is locked or disconnected, as the mark reads it: Windows, asked now (SessionLocked). As
        /// the notification-area icon stops while nobody can see it (tray._session_changed), so does the button; and
        /// like BatterySaverOn it is an input a probe stands its own answer in - a runner's session decides nothing.
        internal static Func<bool> SessionLockedOn = SessionLocked;

        private readonly Form owner;
        private readonly Timer timer = new Timer();
        private readonly System.Diagnostics.Stopwatch watch = System.Diagnostics.Stopwatch.StartNew();
        /// The motion's clock in ms: breaths and turns count from the mark's start. A probe stands its own in.
        internal Func<double> Clock;
        private string state;               // the icon state, null until the window first tells it one
        private double enteredAt;           // when it was entered, on Clock
        private bool allowed;               // whether it may move, as Sync last found
        private int interval = -1;          // the frame timer's interval while it runs
        private MarkFrames frames;
        private bool framesRead;
        private IntPtr ownBig, ownSmall;    // the window's own icons, as WinForms gave them to Windows: never ours
        private IntPtr smallCopy;           // a second handle to the small icon's image (Refresh)
        private IntPtr shown;               // the frame on show as the big icon; zero while that is the window's own
        private long shownKey = -1;
        private bool closing, disposed;

        internal TaskbarMark(Form owner)
        {
            this.owner = owner;
            Clock = delegate { return watch.Elapsed.TotalMilliseconds; };
            timer.Tick += delegate { Animate(); };
            // Stopped once the window has closed, not as it is asked to: WinForms raises FormClosing for Windows'
            // WM_QUERYENDSESSION too, and a shutdown another program calls off (WM_ENDSESSION, FALSE) - or a Restart
            // Manager query that ends nothing - leaves the window open, with a button that would never move again.
            owner.FormClosed += delegate { Dispose(); };
            owner.HandleDestroyed += delegate { Forget(); };
            owner.Disposed += delegate { Dispose(); };
        }

        /// The icon state shown: watching, recovering, idle, attention or failed; null before the first.
        internal string State
        {
            get { return state; }
        }

        /// Whether the frame timer runs.
        internal bool Moving
        {
            get { return timer.Enabled; }
        }

        /// The icon's state for a status-light word (Brand.Mark.IconState) - the window's is SettingsForm.TrayActivity's
        /// - from now on. The same state again changes nothing: a breath or a sweep carries on.
        internal void Follow(string light)
        {
            string next = Brand.Mark.IconState(light);
            if (next == state || closing) return;
            state = next;
            enteredAt = Clock();
            Sync();
        }

        /// Decide again whether the state may move - asking Windows only when it has something to move - show the frame
        /// this moment wants, and run the frame timer at the interval it wants, or not at all.
        internal void Sync()
        {
            if (closing || state == null) return;
            double now = Clock();
            allowed = Brand.Mark.FrameMs(state, now, now - enteredAt, false) >= 0 && MayMove();
            Draw(now);
            Schedule(now);
        }

        /// Whether anything may move. Any one reason holds it still: this product's Reduce motion, Windows' animation
        /// effects, High Contrast or a design whose light does not breathe (Soft.LightStill, which High Contrast's palette
        /// is part of, and Theme.ContrastOn),
        /// battery saver, a locked or disconnected session, a window that is not shown - with no taskbar button - or no
        /// frames at its big icon's size.
        internal static bool MotionAllowed(bool reduced, bool contrast, bool batterySaver, bool locked, bool shown, bool frames)
        {
            return shown && frames && !(reduced || contrast || batterySaver || locked);
        }

        private bool MayMove()
        {
            bool contrast, saver, locked;
            try { contrast = Theme.ContrastOn(); }
            catch (Exception) { contrast = false; }
            try
            {
                Func<bool> on = BatterySaverOn;
                saver = on != null && on();
            }
            catch (Exception) { saver = false; }
            try
            {
                Func<bool> away = SessionLockedOn;
                locked = away != null && away();
            }
            catch (Exception) { locked = false; }
            return MotionAllowed(Soft.LightStill, contrast, saver, locked, owner.Visible && owner.IsHandleCreated, Frames() != null);
        }

        /// Whether this session is locked (WTSINFOEX's SessionFlags) or disconnected (its SessionState), asked now; false
        /// where Windows cannot say. WTSINFOEXW is the level, then - 8-aligned, for the logon times it carries - the
        /// session's id, its state and its flags; Windows 10 and 11 report the lock the right way round.
        internal static bool SessionLocked()
        {
            IntPtr buffer = IntPtr.Zero;
            try
            {
                int bytes;
                if (!WTSQuerySessionInformationW(IntPtr.Zero, WTS_CURRENT_SESSION, WTSSessionInfoEx, out buffer, out bytes)
                    || buffer == IntPtr.Zero || bytes < 20 || Marshal.ReadInt32(buffer, 0) != 1)
                    return false;
                return Marshal.ReadInt32(buffer, 16) == WTS_SESSIONSTATE_LOCK || Marshal.ReadInt32(buffer, 12) == WTSDisconnected;
            }
            catch (Exception) { return false; }
            finally
            {
                if (buffer != IntPtr.Zero) WTSFreeMemory(buffer);
            }
        }

        /// Windows' battery saver (energy saver), asked now; false where Windows cannot say.
        internal static bool BatterySaver()
        {
            try
            {
                PowerStatus status;
                if (GetSystemPowerStatus(out status)) return (status.SystemStatus & 1) != 0;
            }
            catch (Exception) { }
            return false;
        }

        private void Animate()
        {
            if (closing) return;                    // stopped already, and perhaps disposed
            if (state == null || !owner.IsHandleCreated)
            {
                timer.Stop();
                interval = -1;
                return;
            }
            double now = Clock();
            Draw(now);
            Schedule(now);
        }

        private void Schedule(double now)
        {
            int next = allowed && !closing ? Brand.Mark.FrameMs(state, now, now - enteredAt, false) : -1;
            if (next == interval && timer.Enabled == next >= 0) return;
            interval = next;
            if (next < 0)
            {
                timer.Stop();
                return;
            }
            timer.Interval = next;
            timer.Start();
        }

        /// The frames at the size of the window's own big icon, read once. That is the .ico entry new Icon(path) took for
        /// SM_CXICON, never a scaled one: 48 px at 175%, 64 px from 200% to 300%, and from 350% the 128 px entry, which
        /// has no frames - the button then keeps the window's own icon (build/make_brand.py, MARK_SIZES).
        private MarkFrames Frames()
        {
            if (!framesRead)
            {
                framesRead = true;
                Icon own = owner.Icon;
                frames = own == null ? null : MarkFrames.For(own.Width);
            }
            return frames;
        }

        /// Show the frame this moment wants as the window's big icon, if it is not the one on show.
        private void Draw(double now)
        {
            if (!owner.IsHandleCreated || !Own()) return;
            int position, level;
            Brand.Mark.Frame(state, now, now - enteredAt, !allowed, out position, out level);
            Color head = Brand.Mark.LevelColour(Brand.Mark.HeadColour(state), level);
            // At rest in the mark's own colour the frame is the window's own icon, and that is what is shown.
            bool own = position == 0 && head.ToArgb() == Brand.Mark.HeadColour("watching").ToArgb();
            long key = own ? 0 : ((long)(position + 1) << 32) | (uint)head.ToArgb();
            IntPtr big = Send(WM_GETICON, ICON_BIG, IntPtr.Zero);
            if (key == shownKey && big == (own ? ownBig : shown)) return;
            if (own && big == ownBig)
            {
                // The window's own icon is already the big one: nothing to show, and nothing to refresh.
                if (shown != IntPtr.Zero) DestroyIcon(shown);
                shown = IntPtr.Zero;
                shownKey = key;
                return;
            }
            IntPtr made = IntPtr.Zero;
            if (!own)
            {
                MarkFrames table = Frames();
                if (table == null) return;          // no frames at this size: the window's own icon stays
                made = MarkFrames.IconFrom(table.Compose(position, head), table.Size);
                if (made == IntPtr.Zero) return;
            }
            Send(WM_SETICON, ICON_BIG, own ? ownBig : made);
            Refresh();
            if (shown != IntPtr.Zero) DestroyIcon(shown);  // only now the window holds the next one
            shown = made;
            shownKey = key;
        }

        /// The window's own icons, as WinForms gave them to Windows; false while it has not given both. Without a small
        /// icon of its own the title bar would be drawn from the big one, and would move with it.
        private bool Own()
        {
            if (ownBig != IntPtr.Zero && ownSmall != IntPtr.Zero) return true;
            IntPtr big = Send(WM_GETICON, ICON_BIG, IntPtr.Zero), small = Send(WM_GETICON, ICON_SMALL, IntPtr.Zero);
            if (big == IntPtr.Zero || small == IntPtr.Zero) return false;
            ownBig = big;
            ownSmall = small;
            return true;
        }

        /// Make the taskbar look at the big icon again: the small icon set again, with the other of two handles to its
        /// one image, so the title bar keeps every pixel.
        private void Refresh()
        {
            IntPtr small = Send(WM_GETICON, ICON_SMALL, IntPtr.Zero);
            if (small == IntPtr.Zero) return;
            if (small != ownSmall && small != smallCopy)
            {
                // WinForms has given the window another small icon since: that is the image to keep.
                if (smallCopy != IntPtr.Zero) DestroyIcon(smallCopy);
                smallCopy = IntPtr.Zero;
                ownSmall = small;
            }
            if (smallCopy == IntPtr.Zero) smallCopy = CopyIcon(ownSmall);
            if (smallCopy == IntPtr.Zero) return;
            Send(WM_SETICON, ICON_SMALL, small == ownSmall ? smallCopy : ownSmall);
        }

        private IntPtr Send(int message, int which, IntPtr icon)
        {
            return SendMessage(owner.Handle, message, (IntPtr)which, icon);
        }

        /// The window has closed: no frame from here on, and no timer.
        internal void Stop()
        {
            closing = true;
            interval = -1;
            timer.Stop();
        }

        /// The window's handle is gone - it is closing, or WinForms is making it again - and with it whatever it held:
        /// what the mark made is destroyed, and a new handle starts from its own icons again.
        private void Forget()
        {
            if (!disposed) timer.Stop();
            interval = -1;
            Release();
            ownBig = ownSmall = IntPtr.Zero;
        }

        private void Release()
        {
            if (shown != IntPtr.Zero) DestroyIcon(shown);
            if (smallCopy != IntPtr.Zero) DestroyIcon(smallCopy);
            shown = smallCopy = IntPtr.Zero;
            shownKey = -1;
        }

        /// The window's own icons back where the mark's are on show, everything the mark made destroyed, and the timer
        /// with it.
        public void Dispose()
        {
            if (disposed) return;
            disposed = true;
            Stop();
            if (owner.IsHandleCreated)
            {
                if (shown != IntPtr.Zero && Send(WM_GETICON, ICON_BIG, IntPtr.Zero) == shown) Send(WM_SETICON, ICON_BIG, ownBig);
                if (smallCopy != IntPtr.Zero && Send(WM_GETICON, ICON_SMALL, IntPtr.Zero) == smallCopy)
                    Send(WM_SETICON, ICON_SMALL, ownSmall);
            }
            Release();
            timer.Dispose();
        }
    }
}
