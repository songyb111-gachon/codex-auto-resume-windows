// Codex Auto Resume - the render mode: the window drawing frames of itself, offscreen, for the documentation's
// motion pictures (build/make_motion.py).
//
// Never a window a person opens: it runs only when build/motion_window.py names a render job in
// CODEX_AR_RENDER_PLAN beside a capture's event (Soft.StillReady), and then the window is built as LayoutAudit
// builds it - never shown, not even a top-level window - answered from the job's own canned replies instead of
// a bridge, so nothing is read from an installation, nothing is written anywhere but the job's folder, and no
// process is started. For each frame of the job it is put in a state - a page, a Settings section, a scroll
// offset, a control's hover or pressed face, a drop-down's value, its open list, a Pending row chosen and its own
// menu open (v0.6.18), the moment of its lights -
// waits until it holds still as a capture waits (Settled), and draws itself into a bitmap; only what changed
// since the frame before is written.

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Imaging;
using System.Globalization;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;

namespace CodexAutoResume
{
    internal sealed partial class SettingsForm
    {
        // ------------------------------------------------------------------ render mode
        [DllImport("user32.dll", EntryPoint = "SendMessageW")]
        private static extern IntPtr SendRenderMessage(IntPtr window, int message, IntPtr wParam, IntPtr lParam);

        private const int WM_UPDATEUISTATE = 0x0128;
        // UIS_SET with UISF_HIDEFOCUS | UISF_HIDEACCEL: a window as a person using the mouse sees it, as every capture
        // is taken (build/capture_window.ps1).
        private static readonly IntPtr HideCues = (IntPtr)0x00030001;
        // The longest a state may take to hold still, in milliseconds; a frame drawn past it says so.
        private const int RenderSettleLimit = 20000;
        // How many lines a turn of the wheel scrolls in a picture: Windows' own default, whatever this machine says.
        internal const int RenderWheelLines = 3;

        /// Set on a window the render mode builds: it never starts another window of itself (Reopen).
        private bool rendering;

        /// The render job's file, or null - which is what anybody running the product gets. Only beside a capture's
        /// event (Soft.StillReady), as every hook of the pictures is.
        internal static string RenderJob
        {
            get
            {
                if (Soft.StillReady == null) return null;
                try
                {
                    string path = Environment.GetEnvironmentVariable("CODEX_AR_RENDER_PLAN");
                    return string.IsNullOrEmpty(path) || !File.Exists(path) ? null : path;
                }
                catch (Exception) { return null; }
            }
        }

        // The replies the window being rendered is given, and every read it made that they did not answer.
        private static List<object> renderAnswers;
        private static readonly List<string> RenderMisses = new List<string>();

        /// A read answered from the job's replies: the one for exactly this argument, else the one the job gave for
        /// the command whatever its argument. Anything else - every command that changes something among them - is
        /// refused, and noted.
        private static Dictionary<string, object> RenderAnswer(string command, string argument)
        {
            Dictionary<string, object> any = null;
            string asked = Compact(argument);
            lock (RenderMisses)
            {
                foreach (object item in renderAnswers ?? new List<object>())
                {
                    var answer = item as Dictionary<string, object>;
                    if (answer == null || Str(answer, "command") != command) continue;
                    object given;
                    answer.TryGetValue("argument", out given);
                    var reply = Map(answer, "reply");
                    if (given == null) { if (any == null) any = reply; continue; }
                    if (Compact(Convert.ToString(given, CultureInfo.InvariantCulture)) == asked) return Copy(reply);
                }
                if (any != null) return Copy(any);
                RenderMisses.Add(command + (string.IsNullOrEmpty(argument) ? "" : " " + argument));
            }
            var refused = new Dictionary<string, object>();
            refused["ok"] = false;
            refused["error"] = "not answered in the render";
            return refused;
        }

        private static string Compact(string json)
        {
            if (string.IsNullOrEmpty(json)) return "";
            try { return Json.Write(Json.Parse(json)); }
            catch (Exception) { return json; }
        }

        // Each read gets a reply of its own: the window keeps and changes what it is given.
        private static Dictionary<string, object> Copy(Dictionary<string, object> reply)
        {
            return reply == null ? null : Json.Parse(Json.Write(reply)) as Dictionary<string, object>;
        }

        /// Draws the job's frames into its folder and ends: 0 when every frame was drawn, 2 when the job could not be
        /// read. What went wrong, and every read nobody answered, is in the folder's frames.json.
        internal static int RenderFrames(string jobPath)
        {
            var job = Json.Parse(File.ReadAllText(jobPath, new UTF8Encoding(false))) as Dictionary<string, object>;
            if (job == null) return 2;
            string folder = Str(job, "out");
            if (string.IsNullOrEmpty(folder)) return 2;
            Directory.CreateDirectory(folder);
            var writer = new RenderWriter(folder);
            SettingsForm form = null;
            string formLocale = null;
            try
            {
                string theme = Str(job, "theme"), design = Str(job, "design");
                if (theme == null || design == null) throw new InvalidDataException("the job names no theme or design");
                Theme.Opened = theme;
                Design.Opened = design;
                Palette.AdoptDesign(design);
                Palette.Adopt(Theme.Current(theme));
                double text = TextScale.Read();
                AdoptTextSize(text, TextScale.Fitting(text, Screen.PrimaryScreen.WorkingArea.Size, DpiScale));
                Soft.StillLightMs = 0;
                PersistentBridge.Answers = RenderAnswer;
                // The job's command line, read as the window's own is (ParseArguments), for what a page takes from it:
                // the advanced edition's `--capability=`. The standard window takes nothing here.
                var arguments = new List<string>();
                foreach (object argument in Items(job, "arguments") ?? new List<object>())
                    arguments.Add(Convert.ToString(argument, CultureInfo.InvariantCulture));
                ParseArguments(arguments.ToArray());
                var forms = Map(job, "forms") ?? new Dictionary<string, object>();
                var targets = Items(job, "targets") ?? new List<object>();
                foreach (object item in Items(job, "frames") ?? new List<object>())
                {
                    var frame = item as Dictionary<string, object>;
                    if (frame == null) continue;
                    string locale = Str(frame, "locale") ?? "en";
                    if (form == null || formLocale != locale)
                    {
                        if (form != null) form.Dispose();
                        form = null;
                        renderAnswers = Items(Map(forms, locale), "answers");
                        form = OpenForRender(writer);
                        formLocale = locale;
                    }
                    form.RenderState(frame, writer);
                    using (Bitmap picture = form.RenderPicture(frame, writer))
                        writer.Write(Convert.ToInt32(frame["index"], CultureInfo.InvariantCulture), picture,
                                     form.RenderBounds(targets, frame));
                }
            }
            catch (Exception error)
            {
                writer.Failed(error.ToString());
            }
            finally
            {
                if (form != null) form.Dispose();
                PersistentBridge.Answers = null;
                lock (RenderMisses) writer.Finish(RenderMisses);
            }
            return writer.Error == null ? 0 : 2;
        }

        /// The window as a capture opens it, built never shown, for the job's replies in force.
        private static SettingsForm OpenForRender(RenderWriter writer)
        {
            var strings = RenderAnswer("strings", null);
            string nowhere = Path.Combine(Path.GetTempPath(), "codex-auto-resume-render-" + Guid.NewGuid().ToString("N"));
            var form = new SettingsForm(new PersistentBridge(nowhere, new Bridge(nowhere)), strings, null);
            form.rendering = true;
            form.TopLevel = false;
            form.FormBorderStyle = FormBorderStyle.None;
            form.ClientSize = new Size(form.Px(OpeningWidth), form.Px(OpeningHeight));
            form.CreateControl();
            IntPtr made = form.Handle;
            // Shown as a child of Windows' parking window, which is never on the screen: its Load (the reads, the
            // first page, the clock) and its Shown come as they come to a window a person opens.
            form.Visible = true;
            Application.DoEvents();
            if (form.currentPage == null) form.OnLoad(EventArgs.Empty);
            if (!form.shown) form.OnShown(EventArgs.Empty);
            Materialise(form);
            SendRenderMessage(made, WM_UPDATEUISTATE, HideCues, IntPtr.Zero);
            if (!form.HoldStill(true)) writer.Note("the window did not hold still as it opened: " + form.Unsettled());
            return form;
        }

        /// Waits, pumping the window's messages, until the page in front is drawn from every answer it asked for,
        /// nothing moves, and the clock has ticked once since - as a capture waits for its event (WatchForStill).
        private bool HoldStill(bool settle)
        {
            var waited = Stopwatch.StartNew();
            int since = -1;
            var still = new Stopwatch();
            while (waited.ElapsedMilliseconds < RenderSettleLimit)
            {
                Application.DoEvents();
                // What the window's own message loop raises once its queue is empty, and DoEvents never does: the Settings
                // editors are built on it (BuildEditorsLater).
                Application.RaiseIdle(EventArgs.Empty);
                Materialise(this);
                if (!settle) return true;
                // Settled asks about the page the window opened on: the page in front is that page here.
                firstPage = currentPage ?? firstPage;
                if (!Settled()) { since = -1; }
                else if (since < 0) { since = ticks; still.Restart(); }
                else if (ticks != since && still.ElapsedMilliseconds >= 250) return true;
                System.Threading.Thread.Sleep(10);
            }
            return false;
        }

        /// What the window is still waiting for, of everything Settled asks.
        private string Unsettled()
        {
            var waiting = new List<string>();
            if (!shown) waiting.Add("shown");
            if (!settingsRead) waiting.Add("settings read");
            if (readingSettings) waiting.Add("reading settings");
            if (reopening) waiting.Add("reopening");
            if (pendingSchema != null) waiting.Add("editors to build");
            if (buildQueued) waiting.Add("build queued");
            if (busy > 0) waiting.Add("busy " + busy);
            if (refreshing) waiting.Add("refreshing");
            if (loadingStats) waiting.Add("statistics");
            if (loadingCompat) waiting.Add("compatibility");
            if (readingFailure) waiting.Add("failure");
            if (acknowledging) waiting.Add("acknowledging");
            if (bridge.InFlight > 0) waiting.Add("in flight " + bridge.InFlight);
            if (Transition.Moving > 0) waiting.Add("moving " + Transition.Moving);
            if (previewTimer != null && previewTimer.Enabled) waiting.Add("preview timer");
            if (previewToken <= 0) waiting.Add("no preview");
            if (snapshot == null) waiting.Add("no snapshot");
            if (statsToken <= 0) waiting.Add("no statistics");
            waiting.Add("ticks " + ticks);
            return string.Join(", ", waiting.ToArray());
        }

        // The face the last frame gave a control, taken off before the next frame gives one.
        private Control renderFaced;
        private int renderCombo = -1;
        private string renderComboField;

        /// Puts the window in a frame's state, and waits for it to hold still when that took a read or a layout.
        private void RenderState(Dictionary<string, object> frame, RenderWriter writer)
        {
            bool moved = false;
            string page = Str(frame, "page") ?? "overview";
            if (currentPage != page && Array.IndexOf(PageOrder, page) >= 0)
            {
                ShowPage(page);
                moved = true;
            }
            RenderStateNamed(frame, writer, ref moved);
            // A page this window does not have is never drawn as another: the job stops.
            if (currentPage != page) throw new InvalidDataException("no page called " + page + " is in this window");
            string section = Str(frame, "section");
            if (page == "settings" && section != null && currentSection != section)
            {
                ShowSection(section);
                moved = true;
            }
            moved |= RenderCombo(Map(frame, "combo"));
            moved |= RenderSelected(Map(frame, "selected"));
            if (moved)
            {
                Materialise(this);
                PerformLayout();
                if (!HoldStill(true)) writer.Note("frame " + frame["index"] + ": the " + page + " page did not hold still: " + Unsettled());
            }
            // The chosen row again, now that the page holds still (RenderSelected).
            RenderSelected(Map(frame, "selected"));
            RenderScroll(page, Map(frame, "scroll"));
            RenderFace(Str(frame, "hover"), Str(frame, "pressed"), writer);
            object light;
            Soft.StillLightMs = frame.TryGetValue("light", out light) && light != null
                ? Convert.ToDouble(light, CultureInfo.InvariantCulture) : 0;
            HoldStill(false);
        }

        /// A drop-down showing a value that is not saved, as a pick from its list leaves it; the value it was built
        /// with again when no frame names it any more. True when anything changed.
        private bool RenderCombo(Dictionary<string, object> combo)
        {
            string field = null, value = null;
            if (combo != null)
                foreach (KeyValuePair<string, object> pair in combo) { field = pair.Key; value = Convert.ToString(pair.Value, CultureInfo.InvariantCulture); }
            if (renderComboField != null && renderComboField != field)
            {
                Control was;
                if (editors.TryGetValue(renderComboField, out was) && was is ComboBox) ((ComboBox)was).SelectedIndex = renderCombo;
                renderComboField = null;
                return true;
            }
            Control editor;
            if (field == null || !editors.TryGetValue(field, out editor)) return false;
            var box = editor as ComboBox;
            if (box == null) return false;
            for (int i = 0; i < box.Items.Count; i++)
            {
                var choice = box.Items[i] as Choice;
                if (choice == null || choice.Value != value) continue;
                if (box.SelectedIndex == i) return false;
                if (renderComboField == null) { renderComboField = field; renderCombo = box.SelectedIndex; }
                box.SelectedIndex = i;
                return true;
            }
            return false;
        }

        // The Pending row the last frame chose (RenderSelected), or -1.
        private int renderSelected = -1;

        /// v0.6.18: the Pending row a right click chose - `{"pending": n}` - as the list chooses the row under the pointer
        /// (DashboardPages, MouseDown); none again once no frame names one. True when anything changed.
        private bool RenderSelected(Dictionary<string, object> selected)
        {
            object given;
            int row = selected != null && selected.TryGetValue("pending", out given) && given != null
                ? Convert.ToInt32(given, CultureInfo.InvariantCulture) : -1;
            if (pendingList == null || (row < 0 && renderSelected < 0)) return false;
            renderSelected = row;
            // Asked of every frame, not only when it changes: a read the window makes while it settles fills the list
            // again, and the row chosen with it.
            bool chosen = row >= 0 && row < pendingList.Items.Count;
            if (chosen && pendingList.SelectedIndices.Count == 1 && pendingList.Items[row].Selected) return false;
            if (!chosen && pendingList.SelectedIndices.Count == 0) return false;
            pendingList.SelectedIndices.Clear();
            if (chosen) pendingList.Items[row].Selected = true;
            pendingList.Invalidate();
            return true;
        }

        /// The page scrolled `notches` turns of the wheel down, the last of them `glide_ms` into its glide - as
        /// SoftPage glides, a step of SoftBar.GlideStep every SoftBar.GlideInterval - or at rest.
        private void RenderScroll(string page, Dictionary<string, object> scroll)
        {
            Control built;
            ISoftScroller scroller = page == "settings" ? sectionScroll
                                   : pages.TryGetValue(page, out built) ? built as ISoftScroller : null;
            if (scroller == null) return;
            int notches = scroll == null ? 0 : Convert.ToInt32(scroll["notches"], CultureInfo.InvariantCulture);
            object gliding;
            int glide = scroll != null && scroll.TryGetValue("glide_ms", out gliding) && gliding != null
                ? Convert.ToInt32(gliding, CultureInfo.InvariantCulture) : -1;
            scroller.ScrollTo(RenderOffset(scroller.Extent, scroller.Viewport, notches, glide));
        }

        /// Where a page `extent` long showing `viewport` of it stands after `notches` turns of the wheel down from its
        /// top, the last `glide` ms into its glide (-1: arrived).
        internal static int RenderOffset(int extent, int viewport, int notches, int glide)
        {
            int range = Math.Max(0, extent - viewport), offset = 0;
            for (int notch = 0; notch < notches; notch++)
            {
                int step = SoftBar.WheelStep(-120, RenderWheelLines, Soft.Px(SoftBar.Line), viewport);
                int target = Math.Max(0, Math.Min(range, offset + step));
                if (notch < notches - 1 || glide < 0) { offset = target; continue; }
                for (int tick = 0; tick < glide / SoftBar.GlideInterval; tick++) offset = SoftBar.GlideStep(offset, target);
            }
            return offset;
        }

        /// The hover or pressed face of the control a frame names, as the pointer gives it: the control's own
        /// `hover` flag and its own Press - nothing a control does not draw of its own. A name the window has no
        /// control for is noted.
        private void RenderFace(string hover, string pressed, RenderWriter writer)
        {
            if (renderFaced != null) SetRenderFace(renderFaced, false, false);
            renderFaced = null;
            string name = pressed ?? hover;
            // A row of an open list, a Pending row or an item of the row menu: drawn by RenderPicture, not a control's face.
            if (name == null || name.StartsWith("row.", StringComparison.Ordinal) ||
                name.StartsWith("task.", StringComparison.Ordinal) || name.StartsWith("menu.", StringComparison.Ordinal)) return;
            Control control = FocusTarget(name);
            if (control == null) { writer.Note("no control is called " + name); return; }
            SetRenderFace(control, true, pressed != null);
            renderFaced = control;
        }

        private static void SetRenderFace(Control control, bool hover, bool pressed)
        {
            const System.Reflection.BindingFlags own = System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance;
            Type type = control.GetType();
            System.Reflection.FieldInfo hovered = type.GetField("hover", own);
            if (hovered != null && hovered.FieldType == typeof(bool)) hovered.SetValue(control, hover);
            System.Reflection.MethodInfo press = type.GetMethod("Press", own, null, new[] { typeof(bool) }, null);
            if (press != null) press.Invoke(control, new object[] { pressed });
            control.Invalidate();
            if (control.Parent != null) control.Parent.Invalidate(true);
        }

        /// The window drawn into a bitmap the size of its client area - and over it, when the frame has one open, a
        /// drop-down's list, which is a window of its own a picture of the window would never hold, drawn by its own
        /// painter (SoftDropList.PaintSettled) where it opens.
        private Bitmap RenderPicture(Dictionary<string, object> frame, RenderWriter writer)
        {
            var picture = new Bitmap(ClientSize.Width, ClientSize.Height, PixelFormat.Format32bppArgb);
            Invalidate(true);
            DrawToBitmap(picture, new Rectangle(Point.Empty, ClientSize));
            renderRows = null;
            renderMenu = null;
            // v0.6.18: a Pending row's own menu, over everything: a window of its own too (SoftMenu), drawn by its own
            // card where it opens.
            RenderDropList(picture, Map(frame, "droplist"), writer);
            var menu = Map(frame, "menu");
            if (menu != null) RenderMenu(picture, Str(menu, "at"), Str(frame, "hover"), writer);
            return picture;
        }

        // The items of the row menu the last picture showed open, by name (`menu.<n>`), in client coordinates.
        private Dictionary<string, Rectangle> renderMenu;

        /// The Pending row `name` names (`task.<n>`) in client coordinates, and its index; false when it is not shown.
        private bool RenderTask(string name, out Rectangle bounds, out int index)
        {
            bounds = Rectangle.Empty;
            index = -1;
            if (name == null || !name.StartsWith("task.", StringComparison.Ordinal) || pendingList == null) return false;
            if (!int.TryParse(name.Substring(5), NumberStyles.None, CultureInfo.InvariantCulture, out index)) return false;
            if (index < 0 || index >= pendingList.Items.Count) return false;
            for (Control c = pendingList; c != null && c != this; c = c.Parent) if (!OwnVisible(c)) return false;
            Rectangle row = pendingList.Items[index].Bounds;
            Point list = InClient(pendingList);
            bounds = new Rectangle(list.X + row.X, list.Y + row.Y, row.Width, row.Height);
            return true;
        }

        /// The row menu of the Pending row `at` names, as a right click there opens it - filled by FillRowMenu as the
        /// menu's Opening fills it, the item `hover` names (`menu.<n>`) in hand - drawn by its own card (SoftMenuLayer)
        /// with the card's corner where the pointer is (RenderMenuPlace), and its items named for the pointer.
        private void RenderMenu(Bitmap picture, string at, string hover, RenderWriter writer)
        {
            Rectangle row;
            int index;
            if (!RenderTask(at, out row, out index)) { writer.Note("no Pending row is called " + at); return; }
            if (pendingMenu == null || !FillRowMenu(pendingList.Items[index].Tag as Dictionary<string, object>))
            {
                writer.Note("the row menu offers nothing on " + at);
                return;
            }
            pendingMenu.Size = pendingMenu.GetPreferredSize(Size.Empty);
            pendingMenu.PerformLayout();
            IntPtr made = pendingMenu.Handle;
            int held;
            if (hover != null && hover.StartsWith("menu.", StringComparison.Ordinal) &&
                int.TryParse(hover.Substring(5), NumberStyles.None, CultureInfo.InvariantCulture, out held) &&
                held < pendingMenu.Items.Count)
                pendingMenu.Items[held].Select();
            SoftMenuLayer layer = pendingMenu.Layer;
            if (layer == null) { writer.Note("the row menu is Windows' own here: no card to draw"); return; }
            layer.Render();
            Bitmap image = layer.Image;
            if (image == null) return;
            // Where the pointer stands on the row: its centre, as the pointer is put on a target (motion_compose.locate).
            var anchor = new Point(row.X + row.Width / 2, row.Y + row.Height / 2);
            Point corner = RenderMenuPlace(anchor, image.Size, SoftMenuLayer.Reach, ClientSize);
            using (Graphics g = Graphics.FromImage(picture)) g.DrawImage(image, corner.X, corner.Y, image.Width, image.Height);
            renderMenu = new Dictionary<string, Rectangle>();
            for (int i = 0; i < pendingMenu.Items.Count; i++)
            {
                ToolStripItem item = pendingMenu.Items[i];
                if (item is ToolStripSeparator || !item.Available) continue;
                renderMenu["menu." + i.ToString(CultureInfo.InvariantCulture)] =
                    new Rectangle(corner.X + item.Bounds.X, corner.Y + item.Bounds.Y, item.Bounds.Width, item.Bounds.Height);
            }
        }

        /// Where a menu's window `size` big goes, with its card `reach` in from each edge, when it opens at `anchor` in
        /// a client area `client` big: its card's top left corner at the anchor - or, where the card has no room right
        /// of it or below it, its right or bottom edge, as Windows turns a menu round to fit - and the card kept inside.
        internal static Point RenderMenuPlace(Point anchor, Size size, Padding reach, Size client)
        {
            int wide = size.Width - reach.Horizontal, tall = size.Height - reach.Vertical;
            int left = anchor.X + wide <= client.Width ? anchor.X : anchor.X - wide;
            int top = anchor.Y + tall <= client.Height ? anchor.Y : anchor.Y - tall;
            left = Math.Max(0, Math.Min(left, client.Width - wide));
            top = Math.Max(0, Math.Min(top, client.Height - tall));
            return new Point(left - reach.Left, top - reach.Top);
        }

        /// A drop-down's open list over the picture, when the frame has one (see RenderPicture).
        private void RenderDropList(Bitmap picture, Dictionary<string, object> listed, RenderWriter writer)
        {
            if (listed == null) return;
            Control editor;
            var combo = editors.TryGetValue(Str(listed, "field") ?? "", out editor) ? editor as SoftCombo : null;
            if (combo == null) { writer.Note("no drop-down is called " + Str(listed, "field")); return; }
            int hovered = -1;
            string value = Str(listed, "hover");
            for (int i = 0; i < combo.Items.Count; i++)
            {
                var choice = combo.Items[i] as Choice;
                if (choice != null && choice.Value == value) hovered = i;
            }
            Point field = InClient(combo);
            using (var list = new SoftDropList(combo))
            {
                // Its own placement, against the window's client area for a screen: where it opens under the field.
                Rectangle screenField = combo.RectangleToScreen(combo.ClientRectangle);
                Rectangle area = RectangleToScreen(new Rectangle(Point.Empty, ClientSize));
                // As it opens it fades in and rises into place (SoftDropList.Show and Tick): `appear_ms` into that.
                object appearing;
                double appear = listed.TryGetValue("appear_ms", out appearing) && appearing != null
                    ? Convert.ToDouble(appearing, CultureInfo.InvariantCulture) : -1;
                Bitmap image = list.PaintAt(hovered, area, appear);
                if (image == null) return;
                Rectangle card = list.Card;
                Padding margin = list.Margin;
                int rise = list.CardOnScreen.Y - card.Y;
                int left = field.X + card.X - screenField.X - margin.Left;
                int top = field.Y + card.Y - screenField.Y - margin.Top + rise;
                using (Graphics g = Graphics.FromImage(picture))
                using (var faded = new ImageAttributes())
                {
                    var matrix = new ColorMatrix();
                    matrix.Matrix33 = list.Alpha / 255f;
                    faded.SetColorMatrix(matrix);
                    g.DrawImage(image, new Rectangle(left, top, image.Width, image.Height), 0, 0, image.Width, image.Height,
                                GraphicsUnit.Pixel, faded);
                }
                renderRows = new Dictionary<string, Rectangle>();
                for (int i = 0; i < combo.Items.Count; i++)
                {
                    var choice = combo.Items[i] as Choice;
                    Rectangle pill = list.PillRect(i);
                    if (choice != null && list.Shows(i))
                        renderRows["row." + choice.Value] = new Rectangle(left + margin.Left + pill.X, top + margin.Top + pill.Y,
                                                                          pill.Width, pill.Height);
                }
            }
        }

        // The rows of the list the last picture showed open, by name, in client coordinates.
        private Dictionary<string, Rectangle> renderRows;

        /// Where `control` stands in the client area, from the positions of it and every control around it.
        private Point InClient(Control control)
        {
            int x = 0, y = 0;
            for (Control c = control; c != null && c != this; c = c.Parent) { x += c.Left; y += c.Top; }
            return new Point(x, y);
        }

        /// The bounds, in client coordinates, of every target the job names that shows in this frame.
        private Dictionary<string, object> RenderBounds(List<object> targets, Dictionary<string, object> frame)
        {
            var found = new Dictionary<string, object>();
            foreach (object item in targets)
            {
                string name = Convert.ToString(item, CultureInfo.InvariantCulture);
                Rectangle rect;
                if (renderRows != null && renderRows.TryGetValue(name, out rect)) { found[name] = Box(rect); continue; }
                if (renderMenu != null && renderMenu.TryGetValue(name, out rect)) { found[name] = Box(rect); continue; }
                int row;
                if (RenderTask(name, out rect, out row)) { found[name] = Box(rect); continue; }
                if (name.StartsWith("menu.", StringComparison.Ordinal) || name.StartsWith("task.", StringComparison.Ordinal)) continue;
                Control control = name.StartsWith("row.", StringComparison.Ordinal) ? null : FocusTarget(name);
                if (control == null) continue;
                bool shows = true;
                for (Control c = control; c != null && c != this; c = c.Parent) shows &= OwnVisible(c);
                if (!shows) continue;
                Point at = InClient(control);
                found[name] = Box(new Rectangle(at, control.Size));
            }
            return found;
        }

        private static List<object> Box(Rectangle rect)
        {
            return new List<object> { (double)rect.X, (double)rect.Y, (double)rect.Width, (double)rect.Height };
        }

        /// Writes each frame as the rectangle that changed since the one before - the first whole - as raw RGB, and
        /// frames.json: the client size, each frame's rectangle and file, the bounds of its targets, what was noted.
        private sealed class RenderWriter
        {
            private readonly string folder;
            private int[] previous;
            private int width, height;
            private readonly StringBuilder frames = new StringBuilder();
            private readonly List<string> notes = new List<string>();
            internal string Error;

            internal RenderWriter(string folder) { this.folder = folder; }

            internal void Note(string text) { notes.Add(text); }

            internal void Failed(string text) { Error = text; }

            internal void Write(int index, Bitmap picture, Dictionary<string, object> bounds)
            {
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
                if (previous != null && previous.Length == pixels.Length)
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
                entry["box"] = new List<object> { (double)left, (double)top, (double)(right - left + 1), (double)(bottom - top + 1) };
                entry["file"] = file;
                entry["bounds"] = bounds;
                if (frames.Length > 0) frames.Append(",\n");
                frames.Append(Json.Write(entry));
                previous = pixels;
            }

            internal void Finish(List<string> misses)
            {
                var notesJson = new List<object>();
                foreach (string note in notes) notesJson.Add(note);
                var missesJson = new List<object>();
                foreach (string miss in misses) missesJson.Add(miss);
                var text = new StringBuilder("{\"client\": [")
                    .Append(width.ToString(CultureInfo.InvariantCulture)).Append(", ")
                    .Append(height.ToString(CultureInfo.InvariantCulture)).Append("],\n\"dpi_scale\": ")
                    .Append(DpiScale.ToString("R", CultureInfo.InvariantCulture)).Append(",\n\"notes\": ")
                    .Append(Json.Write(notesJson)).Append(",\n\"misses\": ").Append(Json.Write(missesJson))
                    .Append(",\n\"error\": ").Append(Error == null ? "null" : Json.Escape(Error))
                    .Append(",\n\"frames\": [\n").Append(frames).Append("\n]}\n");
                File.WriteAllText(Path.Combine(folder, "frames.json"), text.ToString(), new UTF8Encoding(false));
            }
        }
    }
}
