// Codex Auto Resume - the setup program's window drawing frames of itself, offscreen, for the install motion picture
// (build/make_install_motion.py). Picture-build only.
//
// This file is never part of anything shipped: it is not in gui/window.sources and not in what build/make_setup.py
// compiles (tests/test_install_motion.py holds both). The picture's generator compiles it TOGETHER with the setup
// program's own sources - build/setup/Setup.cs, build/setup/SetupWindow.cs and the window's [installer], [controls] and
// [generated] groups, exactly as make_setup.py lists them - into a scratch program whose entry point is Main below, so
// the window drawn is the setup program's window, byte for byte the same code.
//
// It drives that window as a person and a run would, through the window's own doors: the window is made as
// SetupWindow.Run makes it for a first installation (FlowFor, the catalog's words, the display's scale and text
// size), its primary button is
// clicked (Form.AcceptButton), the run is the window's own Start on its own worker, told each line the installer would
// print and how far the archive is unpacked - the lines install.ps1 really prints, from the plan - and the run ends
// with the code a run that succeeded ends with. Nothing is installed, unpacked, started or written anywhere but the
// job's folder: the runner only hands the window the plan's lines.
//
// For each frame of the job the window is put in the frame's page and progress (forward only), its primary button in
// its hover or pressed face (the button's own `hover` flag and Press, as gui/WindowRender.cs gives a face), its light
// held at the frame's moment of the state it is in (Soft.StillLightMs), and drawn into a bitmap, never shown: built as
// a child of Windows' parking window, as the render mode builds the Dashboard. Only what changed since the frame
// before is written, as raw RGB, with frames.json beside it, in the render mode's own format.
//
// C# 5 only: the in-box csc compiles it, as it compiles the setup program.

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Imaging;
using System.Globalization;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Windows.Forms;

namespace CodexAutoResume
{
    internal static class InstallerRender
    {
        [DllImport("user32.dll", EntryPoint = "SendMessageW")]
        private static extern IntPtr SendMessage(IntPtr window, int message, IntPtr wParam, IntPtr lParam);

        private const int WM_UPDATEUISTATE = 0x0128;
        // WM_PRINT of one control alone - its frame, its background and its face, never its children: the frame is
        // put together child by child, each clipped to its parent, as Windows shows a window (Compose).
        private const int WM_PRINT = 0x0317;
        private static readonly IntPtr PrintOwn = (IntPtr)(0x02 | 0x04 | 0x08);   // PRF_NONCLIENT | PRF_CLIENT | PRF_ERASEBKGND

        [DllImport("user32.dll")]
        private static extern bool GetWindowRect(IntPtr window, out Rect rect);

        [DllImport("user32.dll")]
        private static extern bool ClientToScreen(IntPtr window, ref Point point);

        private struct Rect { internal int Left, Top, Right, Bottom; }
        // UIS_SET with UISF_HIDEFOCUS | UISF_HIDEACCEL: the window as a person using the mouse sees it.
        private static readonly IntPtr HideCues = (IntPtr)0x00030001;
        // The pages of a first installation, in the order the window goes through them (InstallerFlow.Pages).
        private static readonly string[] Order = { InstallerFlow.Welcome, InstallerFlow.Options, InstallerFlow.Progress,
                                                   InstallerFlow.Finish };
        // The longest one step of the window may take to be shown, in milliseconds.
        private const int StepLimit = 10000;

        [STAThread]
        private static int Main(string[] arguments)
        {
            if (arguments.Length != 1 || !File.Exists(arguments[0])) return 2;
            var job = Json.Parse(File.ReadAllText(arguments[0], new UTF8Encoding(false))) as Dictionary<string, object>;
            if (job == null) return 2;
            string folder = Str(job, "out");
            if (string.IsNullOrEmpty(folder)) return 2;
            Directory.CreateDirectory(folder);
            var writer = new Writer(folder);
            Driver driver = null;
            try
            {
                driver = new Driver(job, writer);
                foreach (object item in Items(job, "frames"))
                {
                    var frame = item as Dictionary<string, object>;
                    if (frame == null) continue;
                    driver.Put(frame);
                    using (Bitmap picture = driver.Picture())
                    {
                        writer.Write(Int(frame, "index"), picture, driver.Bounds(Items(job, "targets")));
                        // v0.6.20: the still a capture takes of the window, when the job asks (StillFrame).
                        var still = Map(job, "still");
                        if (still != null)
                            using (Bitmap caption = StillFrame.LoadCaption(Str(still, "caption")))
                            using (Bitmap framed = StillFrame.FramedStill(picture, caption, Int(still, "left"),
                                                                          Int(still, "right"), Int(still, "radius"),
                                                                          Int(still, "dpi")))
                                framed.Save(Path.Combine(folder, "still-" + Int(frame, "index").ToString("D5",
                                            CultureInfo.InvariantCulture) + ".png"), ImageFormat.Png);
                    }
                }
            }
            catch (Exception error)
            {
                writer.Failed(error.ToString());
            }
            finally
            {
                if (driver != null) driver.Dispose();
                writer.Finish();
            }
            return writer.Error == null ? 0 : 2;
        }

        /// The window and the run behind it, put in one frame's state after another.
        private sealed class Driver : IDisposable
        {
            private readonly InstallerWindow window;
            private readonly List<object> events;
            private readonly Writer writer;
            // What the run is told next: an event of the plan, or the end. The worker takes one at a time and says when
            // it has handed it to the window (told).
            private readonly Queue<object> next = new Queue<object>();
            private readonly object gate = new object();
            private readonly AutoResetEvent given = new AutoResetEvent(false);
            private readonly AutoResetEvent told = new AutoResetEvent(false);
            private int delivered;
            private Control faced;
            private HaloDot light;
            private string lightState;
            private double lightSince;

            internal Driver(Dictionary<string, object> job, Writer writer)
            {
                this.writer = writer;
                events = Items(job, "events");
                string theme = Str(job, "theme") ?? "light", design = Str(job, "design") ?? "soft";
                string locales = Str(job, "locales"), language = Str(job, "locale") ?? "en";
                // As SetupWindow.Run opens the window: its look, the display's scale and Windows' text size.
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                Soft.ReduceMotionSetting = false;
                Palette.AdoptDesign(design);
                Palette.Adopt(Theme.Current(theme));
                Font font;
                object pinned;
                double scale = job.TryGetValue("scale", out pinned) && pinned != null
                    ? Convert.ToDouble(pinned, CultureInfo.InvariantCulture) : 0;
                if (scale >= 0.5)
                {
                    // v0.6.20: at the job's scale and Windows' plain text size, whatever display this machine has - as the
                    // layout audit stands a scaling in (InstallerAudit), the fonts in points at that scale's size, and the
                    // controls' own steps with them (FontFactor).
                    SettingsForm.StandIn(scale, 1.0);
                    SettingsForm.FontFactor = (float)(scale / SettingsForm.SystemScale);
                    SettingsForm.RenderPinned = true;
                    Font box = SystemFonts.MessageBoxFont;
                    font = new Font(box.FontFamily, box.SizeInPoints * SettingsForm.FontFactor, box.Style, GraphicsUnit.Point);
                }
                else
                {
                    double read = TextScale.Read();
                    SettingsForm.AdoptTextSize(TextScale.Fitting(read, Screen.PrimaryScreen.WorkingArea.Size, SettingsForm.SystemScale));
                    font = TextScale.Apply(SystemFonts.MessageBoxFont, read, SettingsForm.TextSize);
                }
                Soft.StillLightMs = 0;
                var spoken = new Dictionary<string, InstallerWords>();
                InstallerWindow.Speaker speaker = delegate(string other)
                {
                    InstallerWords found;
                    if (spoken.TryGetValue(other, out found)) return found;
                    string path = Path.Combine(locales ?? "", other + ".json");
                    var catalog = File.Exists(path)
                        ? InstallerFlow.ParseObject(File.ReadAllText(path, new UTF8Encoding(false)).TrimStart('\uFEFF'))
                        : null;
                    found = new InstallerWords(catalog, other);
                    spoken[other] = found;
                    return found;
                };
                // A first installation of the archive's edition and version: the flow the setup program makes for it.
                var flow = CodexAutoResumeSetup.SetupWindow.FlowFor(new string[0], Str(job, "home"), Str(job, "edition"),
                                                                    null, Str(job, "version"), "");
                window = new InstallerWindow(flow, speaker(language), speaker, Run, new string[0], font);
                Size client = window.ClientSize;
                window.TopLevel = false;
                window.FormBorderStyle = FormBorderStyle.None;
                window.ClientSize = client;
                window.CreateControl();
                IntPtr made = window.Handle;
                // A child of Windows' parking window, which is never on the screen.
                window.Visible = true;
                SendMessage(made, WM_UPDATEUISTATE, HideCues, IntPtr.Zero);
                Settle();
                light = Find<HaloDot>(window);
                if (light == null) throw new InvalidOperationException("the window has no status light");
            }

            /// The run the window starts (InstallerWindow.Runner): it tells the window each event the frames ask for,
            /// one at a time, and ends with the code it is given - as Setup.cs's InstallFrom tells it what the installer
            /// prints and how far the archive is unpacked.
            private int Run(InstallerFlow flow, Action<string> line, Action<double> unpacked)
            {
                while (true)
                {
                    object item;
                    lock (gate)
                    {
                        while (next.Count == 0) Monitor.Wait(gate);
                        item = next.Dequeue();
                    }
                    if (item is int) return (int)item;
                    var said = (Dictionary<string, object>)item;
                    if (said.ContainsKey("unpacked")) unpacked(Convert.ToDouble(said["unpacked"], CultureInfo.InvariantCulture));
                    else line(Str(said, "line") ?? "");
                    told.Set();
                }
            }

            private void Tell(object item)
            {
                lock (gate)
                {
                    next.Enqueue(item);
                    Monitor.PulseAll(gate);
                }
            }

            /// Puts the window in `frame`'s state: its page and its progress, forward only, as the window's own
            /// buttons and run take it there; the primary button's face; the light's moment.
            internal void Put(Dictionary<string, object> frame)
            {
                string page = Str(frame, "page") ?? InstallerFlow.Welcome;
                int want = Array.IndexOf(Order, page);
                if (want < 0) throw new InvalidDataException("the window has no page " + page);
                int progress = frame.ContainsKey("progress") ? Int(frame, "progress") : delivered;
                if (progress < delivered || progress > events.Count)
                    throw new InvalidDataException("progress " + progress + " after " + delivered + " of " + events.Count);
                int at = Array.IndexOf(Order, window.Page);
                if (want < at) throw new InvalidDataException("the window is on " + window.Page + " and cannot go back to " + page);
                while (Array.IndexOf(Order, window.Page) < Math.Min(want, Array.IndexOf(Order, InstallerFlow.Progress)))
                {
                    // Next on the Welcome page, Install on Options: the window's own primary button.
                    string before = window.Page;
                    Face(null, null);
                    ((Button)window.AcceptButton).PerformClick();
                    Settle();
                    if (window.Page == before) throw new InvalidOperationException("the window's " + ((Button)window.AcceptButton).Text + " did not leave " + before);
                }
                while (delivered < progress)
                {
                    if (window.Page != InstallerFlow.Progress) throw new InvalidDataException("progress is told only while the window is installing");
                    Tell(events[delivered]);
                    if (!told.WaitOne(StepLimit)) throw new TimeoutException("the run did not take event " + delivered);
                    delivered++;
                    Settle();
                }
                if (want == Array.IndexOf(Order, InstallerFlow.Finish) && window.Page != InstallerFlow.Finish)
                {
                    if (delivered != events.Count) throw new InvalidDataException("the run ends only after every event");
                    Tell(0);
                    var waited = Stopwatch.StartNew();
                    while (window.Page != InstallerFlow.Finish && waited.ElapsedMilliseconds < StepLimit) Settle();
                }
                if (window.Page != page) throw new InvalidOperationException("the window shows " + window.Page + ", the frame " + page);
                Face(Str(frame, "hover"), Str(frame, "pressed"));
                // The light at the frame's moment of the state it is in: its own clock starts when the state does.
                double t = frame.ContainsKey("light") ? Convert.ToDouble(frame["light"], CultureInfo.InvariantCulture) : 0;
                if (light.State != lightState)
                {
                    lightState = light.State;
                    lightSince = t;
                }
                Soft.StillLightMs = Math.Max(0, t - lightSince);
                Settle();
            }

            /// The hover or pressed face of the control a frame names, as the pointer gives it.
            private void Face(string hover, string pressed)
            {
                if (faced != null) SetFace(faced, false, false);
                faced = null;
                string name = pressed ?? hover;
                if (name == null) return;
                Control control = Target(name);
                if (control == null) { writer.Note("no control is called " + name); return; }
                SetFace(control, true, pressed != null);
                faced = control;
            }

            private static void SetFace(Control control, bool hover, bool pressed)
            {
                const System.Reflection.BindingFlags own = System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance;
                Type type = control.GetType();
                System.Reflection.FieldInfo hovered = type.GetField("hover", own);
                if (hovered != null && hovered.FieldType == typeof(bool)) hovered.SetValue(control, hover);
                System.Reflection.MethodInfo press = type.GetMethod("Press", own, null, new[] { typeof(bool) }, null);
                if (press != null) press.Invoke(control, new object[] { pressed });
                control.Invalidate();
            }

            /// A control the plan names: `button.forward` is the page's primary button (Next, Install, Finish).
            private Control Target(string name)
            {
                if (name == "button.forward") return window.AcceptButton as Control;
                return null;
            }

            /// Pumps the window's messages until nothing moves.
            private void Settle()
            {
                var waited = Stopwatch.StartNew();
                int quiet = 0;
                while (waited.ElapsedMilliseconds < StepLimit)
                {
                    Application.DoEvents();
                    Application.RaiseIdle(EventArgs.Empty);
                    if (Transition.Moving > 0) quiet = 0;
                    else if (++quiet >= 3) return;
                    Thread.Sleep(5);
                }
                writer.Note("the " + window.Page + " page did not hold still");
            }

            /// The window as Windows shows it. Not DrawToBitmap: that prints every child window whole, past the parent
            /// that clips it on the screen - a text area's box is wider than its clip by Windows' own scroll bar, which
            /// the real window never shows (SoftTextArea, ListClip), and DrawToBitmap drew that bar beside the soft one.
            internal Bitmap Picture()
            {
                var picture = new Bitmap(window.ClientSize.Width, window.ClientSize.Height, PixelFormat.Format32bppArgb);
                window.Invalidate(true);
                using (Graphics g = Graphics.FromImage(picture))
                    Compose(g, window, Point.Empty, new Rectangle(Point.Empty, window.ClientSize));
                return picture;
            }

            /// `control` printed alone at `at`, inside `clip`, then each of its children over it, bottom of the z-order
            /// first, each inside its parent's client area as well: a child window shows only within its parent.
            private static void Compose(Graphics g, Control control, Point at, Rectangle clip)
            {
                Rectangle shown = Rectangle.Intersect(new Rectangle(at, control.Size), clip);
                if (shown.Width <= 0 || shown.Height <= 0 || !control.IsHandleCreated) return;
                using (var own = new Bitmap(control.Width, control.Height, PixelFormat.Format32bppRgb))
                {
                    using (Graphics paper = Graphics.FromImage(own))
                    {
                        IntPtr dc = paper.GetHdc();
                        try { SendMessage(control.Handle, WM_PRINT, dc, PrintOwn); }
                        finally { paper.ReleaseHdc(dc); }
                    }
                    g.SetClip(shown);
                    g.DrawImageUnscaled(own, at.X, at.Y);
                    g.ResetClip();
                }
                Point inside = ClientOffset(control);
                Rectangle client = Rectangle.Intersect(shown, new Rectangle(at.X + inside.X, at.Y + inside.Y,
                                                                            control.ClientSize.Width, control.ClientSize.Height));
                for (int i = control.Controls.Count - 1; i >= 0; i--)
                {
                    Control child = control.Controls[i];
                    if (!child.Visible) continue;
                    Compose(g, child, new Point(at.X + inside.X + child.Left, at.Y + inside.Y + child.Top), client);
                }
            }

            /// Where a control's client area starts inside its window rectangle: past its border, if it has one.
            private static Point ClientOffset(Control control)
            {
                Rect outer;
                var origin = new Point(0, 0);
                if (!GetWindowRect(control.Handle, out outer) || !ClientToScreen(control.Handle, ref origin)) return Point.Empty;
                return new Point(origin.X - outer.Left, origin.Y - outer.Top);
            }

            /// The bounds, in client coordinates, of every target the job names that shows now.
            internal Dictionary<string, object> Bounds(List<object> targets)
            {
                var found = new Dictionary<string, object>();
                foreach (object item in targets)
                {
                    string name = Convert.ToString(item, CultureInfo.InvariantCulture);
                    Control control = Target(name);
                    if (control == null || !control.Visible) continue;
                    int x = 0, y = 0;
                    for (Control c = control; c != null && c != window; c = c.Parent) { x += c.Left; y += c.Top; }
                    found[name] = new List<object> { (double)x, (double)y, (double)control.Width, (double)control.Height };
                }
                // Each text area shown, and where its box keeps Windows' own scroll bar - outside the clip, never seen:
                // what tests/test_install_motion_window.py holds a frame to.
                int number = 0;
                foreach (SoftTextArea area in All<SoftTextArea>(window))
                {
                    if (!area.Visible) continue;
                    Point where = InWindow(area), box = InWindow(area.Box);
                    int native = SystemInformation.VerticalScrollBarWidth;
                    found["area." + number] = new List<object> { (double)where.X, (double)where.Y, (double)area.Width, (double)area.Height };
                    found["native." + number] = new List<object> { (double)(box.X + area.Box.Width - native), (double)box.Y,
                                                                   (double)native, (double)area.Box.Height };
                    number++;
                }
                return found;
            }

            /// Where `control` stands in the window's client area.
            private Point InWindow(Control control)
            {
                int x = 0, y = 0;
                for (Control c = control; c != null && c != window; c = c.Parent) { x += c.Left; y += c.Top; }
                return new Point(x, y);
            }

            public void Dispose()
            {
                // A run still waiting is ended, so its worker does not outlive the window.
                Tell(InstallerFlow.NotStarted);
                window.Dispose();
            }
        }

        private static List<T> All<T>(Control root) where T : Control
        {
            var found = new List<T>();
            foreach (Control child in root.Controls)
            {
                if (child is T) found.Add((T)child);
                found.AddRange(All<T>(child));
            }
            return found;
        }

        private static T Find<T>(Control root) where T : Control
        {
            foreach (Control child in root.Controls)
            {
                if (child is T) return (T)child;
                T found = Find<T>(child);
                if (found != null) return found;
            }
            return null;
        }

        private static string Str(Dictionary<string, object> map, string key)
        {
            object value;
            return map != null && map.TryGetValue(key, out value) && value != null
                ? Convert.ToString(value, CultureInfo.InvariantCulture) : null;
        }

        private static int Int(Dictionary<string, object> map, string key)
        {
            return Convert.ToInt32(map[key], CultureInfo.InvariantCulture);
        }

        private static Dictionary<string, object> Map(Dictionary<string, object> map, string key)
        {
            object value;
            return map != null && map.TryGetValue(key, out value) ? value as Dictionary<string, object> : null;
        }

        private static List<object> Items(Dictionary<string, object> map, string key)
        {
            object value;
            return map != null && map.TryGetValue(key, out value) && value is List<object> ? (List<object>)value : new List<object>();
        }

        /// Writes each frame as the rectangle that changed since the one before - the first, and any after the window
        /// changed size, whole - as raw RGB, and frames.json: each frame's client size, rectangle and file, the bounds
        /// of its targets, what was noted. gui/WindowRender.cs's format, with the client size per frame.
        private sealed class Writer
        {
            private readonly string folder;
            private int[] previous;
            private int width, height;
            private readonly StringBuilder frames = new StringBuilder();
            private readonly List<object> notes = new List<object>();
            internal string Error;

            internal Writer(string folder) { this.folder = folder; }

            internal void Note(string text) { notes.Add(text); }

            internal void Failed(string text) { Error = text; }

            internal void Write(int index, Bitmap picture, Dictionary<string, object> bounds)
            {
                bool resized = picture.Width != width || picture.Height != height;
                width = picture.Width;
                height = picture.Height;
                var pixels = new int[width * height];
                BitmapData data = picture.LockBits(new Rectangle(0, 0, width, height), ImageLockMode.ReadOnly, PixelFormat.Format32bppArgb);
                try
                {
                    for (int y = 0; y < height; y++)
                        Marshal.Copy(new IntPtr(data.Scan0.ToInt64() + (long)y * data.Stride), pixels, y * width, width);
                }
                finally { picture.UnlockBits(data); }
                int left = 0, top = 0, right = width - 1, bottom = height - 1;
                if (previous != null && !resized)
                {
                    left = width; top = height; right = -1; bottom = -1;
                    for (int y = 0; y < height; y++)
                        for (int x = 0; x < width; x++)
                        {
                            if (((pixels[y * width + x] ^ previous[y * width + x]) & 0xFFFFFF) == 0) continue;
                            if (x < left) left = x;
                            if (x > right) right = x;
                            if (y < top) top = y;
                            if (y > bottom) bottom = y;
                        }
                }
                string file = "";
                if (right >= left && bottom >= top)
                {
                    file = index.ToString("D5", CultureInfo.InvariantCulture) + ".rgb";
                    int wide = right - left + 1, tall = bottom - top + 1;
                    var raw = new byte[wide * tall * 3];
                    for (int y = 0; y < tall; y++)
                        for (int x = 0; x < wide; x++)
                        {
                            int pixel = pixels[(top + y) * width + left + x], at = (y * wide + x) * 3;
                            raw[at] = (byte)(pixel >> 16);
                            raw[at + 1] = (byte)(pixel >> 8);
                            raw[at + 2] = (byte)pixel;
                        }
                    File.WriteAllBytes(Path.Combine(folder, file), raw);
                }
                else { left = top = 0; right = bottom = -1; }
                var entry = new Dictionary<string, object>();
                entry["index"] = (double)index;
                entry["client"] = new List<object> { (double)width, (double)height };
                entry["box"] = new List<object> { (double)left, (double)top, (double)(right - left + 1), (double)(bottom - top + 1) };
                entry["file"] = file;
                entry["bounds"] = bounds;
                if (frames.Length > 0) frames.Append(",\n");
                frames.Append(Json.Write(entry));
                previous = pixels;
            }

            internal void Finish()
            {
                var text = new StringBuilder("{\"client\": [")
                    .Append(width.ToString(CultureInfo.InvariantCulture)).Append(", ")
                    .Append(height.ToString(CultureInfo.InvariantCulture)).Append("],\n\"dpi_scale\": ")
                    .Append(SettingsForm.DpiScale.ToString("R", CultureInfo.InvariantCulture)).Append(",\n\"notes\": ")
                    .Append(Json.Write(notes)).Append(",\n\"misses\": [],\n\"error\": ")
                    .Append(Error == null ? "null" : Json.Escape(Error))
                    .Append(",\n\"frames\": [\n").Append(frames).Append("\n]}\n");
                File.WriteAllText(Path.Combine(folder, "frames.json"), text.ToString(), new UTF8Encoding(false));
            }
        }
    }
    /// v0.6.20: the still a capture takes of the setup window, framed with Windows' title bar kept from a capture at the
    /// job's scale (build/window_frame.py) and its corners cut as build/capture_window.ps1 cuts them. The very members of
    /// gui/WindowRender.cs (SettingsForm), which this program does not compile: tests/test_install_motion.py holds each
    /// one to the window's, character for character.
    internal static class StillFrame
    {
        /// The title bar a still is framed with, as 32-bit ARGB, its file let go at once.
        internal static Bitmap LoadCaption(string path)
        {
            if (string.IsNullOrEmpty(path) || !File.Exists(path)) throw new InvalidDataException("the job's still names no title bar: " + path);
            using (var read = new Bitmap(path))
            {
                var caption = new Bitmap(read.Width, read.Height, PixelFormat.Format32bppArgb);
                using (Graphics g = Graphics.FromImage(caption))
                {
                    g.CompositingMode = System.Drawing.Drawing2D.CompositingMode.SourceCopy;
                    g.DrawImage(read, new Rectangle(0, 0, read.Width, read.Height), 0, 0, read.Width, read.Height, GraphicsUnit.Pixel);
                }
                return caption;
            }
        }

        private static int[] Argb(Bitmap picture)
        {
            var pixels = new int[picture.Width * picture.Height];
            BitmapData data = picture.LockBits(new Rectangle(0, 0, picture.Width, picture.Height), ImageLockMode.ReadOnly,
                                               PixelFormat.Format32bppArgb);
            try
            {
                for (int y = 0; y < picture.Height; y++)
                    Marshal.Copy(new IntPtr(data.Scan0.ToInt64() + (long)y * data.Stride), pixels, y * picture.Width, picture.Width);
            }
            finally { picture.UnlockBits(data); }
            return pixels;
        }

        /// The window as build/capture_window.ps1 photographs it, from the client area drawn here: Windows' title bar above
        /// it - the caption the job gives, taken from a capture at the job's scale (build/window_frame.py): its first `left`
        /// px and its last `right` px as they are, and between them its plain bar - and the corners Windows rounds cut, as
        /// that script cuts them (the same GDI+ fill of the same path, `radius` px, so the same pixels) - its resolution
        /// `dpi`, as a capture's bitmap has the monitor's, so the PNG it is saved as says the same. Nothing of the screen is
        /// read: Windows draws a window's title bar on a monitor, at that monitor's DPI, and this one is on none.
        internal static Bitmap FramedStill(Bitmap client, Bitmap caption, int left, int right, int radius, int dpi)
        {
            int width = client.Width, top = caption.Height, height = top + client.Height;
            int across = caption.Width;
            left = Math.Max(0, Math.Min(left, Math.Min(width, across - 1)));
            right = Math.Max(0, Math.Min(right, Math.Min(width - left, across - left - 1)));
            int[] bar = Argb(caption), body = Argb(client);
            var pixels = new int[width * height];
            for (int y = 0; y < top; y++)
                for (int x = 0; x < width; x++)
                {
                    int from = x < left ? x : x >= width - right ? across - (width - x) : left;
                    pixels[y * width + x] = bar[y * across + from];
                }
            for (int i = 0; i < body.Length; i++) pixels[top * width + i] = unchecked((int)0xFF000000) | (body[i] & 0xFFFFFF);
            using (var square = new Bitmap(width, height, PixelFormat.Format32bppArgb))
            {
                BitmapData data = square.LockBits(new Rectangle(0, 0, width, height), ImageLockMode.WriteOnly, PixelFormat.Format32bppArgb);
                try
                {
                    for (int y = 0; y < height; y++)
                        Marshal.Copy(pixels, y * width, new IntPtr(data.Scan0.ToInt64() + (long)y * data.Stride), width);
                }
                finally { square.UnlockBits(data); }
                Bitmap rounded = Rounded(square, radius);
                if (dpi > 0) rounded.SetResolution(dpi, dpi);
                return rounded;
            }
        }

        /// `square` with its corners cut round, `radius` px, the corners left clear: build/capture_window.ps1's own steps -
        /// a new 32-bit ARGB bitmap, antialiased, high-quality pixel offsets, the four arcs filled through a texture of the
        /// picture - so a still drawn here and one captured on a monitor of that scale have the same corners.
        internal static Bitmap Rounded(Bitmap square, int radius)
        {
            int width = square.Width, height = square.Height;
            var rounded = new Bitmap(width, height, PixelFormat.Format32bppArgb);
            if (radius <= 0 || width <= 2 * radius || height <= 2 * radius)
            {
                using (Graphics g = Graphics.FromImage(rounded))
                {
                    g.CompositingMode = System.Drawing.Drawing2D.CompositingMode.SourceCopy;
                    g.DrawImage(square, new Rectangle(0, 0, width, height), 0, 0, width, height, GraphicsUnit.Pixel);
                }
                return rounded;
            }
            using (Graphics paint = Graphics.FromImage(rounded))
            using (var path = new System.Drawing.Drawing2D.GraphicsPath())
            using (var brush = new TextureBrush(square))
            {
                paint.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
                paint.PixelOffsetMode = System.Drawing.Drawing2D.PixelOffsetMode.HighQuality;
                int d = 2 * radius;
                path.AddArc(0, 0, d, d, 180, 90);
                path.AddArc(width - d, 0, d, d, 270, 90);
                path.AddArc(width - d, height - d, d, d, 0, 90);
                path.AddArc(0, height - d, d, d, 90, 90);
                path.CloseFigure();
                paint.FillPath(brush, path);
            }
            return rounded;
        }
    }
}
