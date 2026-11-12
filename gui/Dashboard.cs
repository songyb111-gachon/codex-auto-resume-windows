// Codex Auto Resume - the Dashboard: what the watcher is doing, what is waiting and when
// it is next looked at, what happened before, how often it worked, the watcher's health,
// and the settings - in one native window, with no local web server and no browser.
//
// Like the rest of the window it owns nothing: every fact comes from the same control
// layer every other interface uses, over one long-lived bridge process, and every action
// addresses a recovery by its exact interruption id. The countdowns are drawn locally
// from the time the watcher persisted; reaching zero means the watcher looks again, not
// that anything is sent.
//
// Nothing that talks to the bridge runs on the window's own thread. A read can take as
// long as the store and the interpreter take, and a window that stops repainting while it
// waits looks exactly like one that has hung.
//
// C# 5 (the in-box compiler): no string interpolation, no null-conditional operator.
//
// The window is one `partial class SettingsForm`, written across several files since
// v0.6.10-alpha. This one is the Dashboard's own controls, its page frame and its two lists -
// Pending and History - with the column fitting and cell drawing they are measured and painted
// by. Beside it: gui/DashboardPages.cs is what each page is built out of, gui/DashboardCompat.cs
// the compatibility card, gui/DashboardData.cs the clock and the snapshot every page reads,
// gui/DashboardActions.cs what a button does, and gui/DashboardMaintenance.cs the Diagnostics
// actions that run a process. `gui/window.sources` is the list of them all.

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Globalization;
using System.IO;
using System.Text;
using System.Threading.Tasks;
using System.Windows.Forms;
using System.Windows.Forms.Automation;

namespace CodexAutoResume
{
    /// One control process for the life of the window, instead of one per call.
    ///
    /// Requests and replies are single JSON lines (controlcli serve). The request bytes
    /// are written as UTF-8 by hand: .NET Framework encodes a redirected stdin with the
    /// console code page, which is CP949 on a Korean machine, and the other end reads
    /// UTF-8. Anything that goes wrong - a crash, a timeout, a reply out of turn - stops
    /// the process and answers that call through the one-shot bridge instead, so a broken
    /// pipe costs speed, never a wrong or missing answer.
    internal sealed class PersistentBridge
    {
        private const int ReplyMilliseconds = 30000;
        // After this many failures in a row the long-lived process is given up for the life
        // of the window. Each failed start costs an interpreter launch on top of the one-shot
        // call that answers it, and a start that has failed three times running is not going
        // to succeed on the fourth - the first version of this class failed every start for
        // a missing "-c", and the fallback hid it completely.
        private const int MaxFailures = 3;
        // v0.6.18: and tried again once this long has passed since it was given up - a laptop resumed from sleep in
        // the middle of a call counts as a failure, and three of those used to leave every call of the window's life,
        // every five seconds, a fresh interpreter. One more failure gives it up for as long again.
        internal static int RetryMilliseconds = 300000;
        private readonly Stopwatch givenUp = new Stopwatch();
        private readonly Bridge once;
        private string python;
        private readonly string bundled;
        private readonly string appSrc;
        private readonly object gate = new object();
        private Process process;
        private int nextId;
        private int failures;
        private volatile bool closed;

        internal PersistentBridge(string root, Bridge once)
        {
            this.once = once;
            python = RuntimeChoice.Python(root);
            bundled = RuntimeChoice.BundledPython(root);
            appSrc = Path.Combine(root, "app", "src");
        }

        internal bool Available { get { return once.Available; } }

        private int calls;

        /// How many calls are on their way, on either bridge, and how many reads handed to Queue have not yet
        /// handed their answer to the window: a picture is taken only while none is (SettingsForm.WatchForStill).
        internal int InFlight { get { return System.Threading.Volatile.Read(ref calls); } }

        /// Runs `work` - a read on this bridge, and the BeginInvoke that hands its answer to the window - on a
        /// worker, counted in InFlight from this moment, on the window's thread, until the work has returned. Call
        /// alone counts a read only once a worker has started it: on a loaded machine one queued as the Preview's
        /// timer stopped had not started a clock tick later, nothing said it was coming, and the window could say it
        /// held still without its answer. The answer is posted before the count drops, and the window looks at the
        /// count on a timer, whose message comes only after every posted one: the answer is applied first. A read
        /// that sets a flag Settled reads before it is queued - refreshing, loadingCompat, busy - is counted by it.
        internal void Queue(Action work)
        {
            System.Threading.Interlocked.Increment(ref calls);
            try
            {
                System.Threading.ThreadPool.QueueUserWorkItem(delegate
                {
                    try { work(); }
                    finally { System.Threading.Interlocked.Decrement(ref calls); }
                });
            }
            catch (Exception)
            {
                System.Threading.Interlocked.Decrement(ref calls);
                throw;
            }
        }

        /// The render mode's answers (WindowRender.cs), in place of any process: null for every window a person opens.
        internal static Func<string, string, Dictionary<string, object>> Answers;

        internal Dictionary<string, object> Call(string command, string argument)
        {
            System.Threading.Interlocked.Increment(ref calls);
            try { return CallCounted(command, argument); }
            finally { System.Threading.Interlocked.Decrement(ref calls); }
        }

        private Dictionary<string, object> CallCounted(string command, string argument)
        {
            if (closed) throw new ObjectDisposedException("the window is closing");
            if (Answers != null) return Answers(command, argument);
            lock (gate)
            {
                if (closed) throw new ObjectDisposedException("the window is closing");
                if (failures >= MaxFailures && givenUp.ElapsedMilliseconds >= RetryMilliseconds)
                {
                    failures = MaxFailures - 1;
                    givenUp.Reset();
                }
                if (failures < MaxFailures)
                {
                    try
                    {
                        var reply = Ask(command, argument);
                        failures = 0;
                        return reply;
                    }
                    catch (Exception)
                    {
                        FailedLocked();
                        StopLocked();
                        // Ended by Stop while the window closes: the request may already have
                        // been carried out, and there is nobody left to show a second answer to.
                        if (closed) throw;
                    }
                }
            }
            // v0.6.23: the one-shot answer past the lock. It can take up to Bridge.CallMilliseconds, and held under the
            // lock it held every other read of the window - the Dashboard's, the chat's, the previews' - behind it, up to
            // about 92 s after a pipe that hung (the long-lived reply limit, the 2 s stop, then the one-shot limit). The
            // one-shot bridge needs no lock: each call is a process of its own (CallOnce never took it).
            return once.Call(command, argument);
        }

        /// v0.6.19: the code of the answer CallAdvanced gives while the long-lived process cannot be reached.
        internal const string ReconnectingCode = "reconnecting";

        /// v0.6.19: one call of the edition's (the Advanced features page and every page built on it), which only the
        /// long-lived process can carry: the one-shot form never reaches the edition (STANDARDS K3), so it is never
        /// asked. While the long-lived process is given up a read is answered at once with ReconnectingCode, and an
        /// action - a person's click - tries to open it again at once, not after RetryMilliseconds, and is carried if
        /// it opens. A call the long-lived process failed on is answered with ReconnectingCode and never asked again:
        /// it may already have been carried out there.
        internal Dictionary<string, object> CallAdvanced(string command, string argument, bool action)
        {
            if (closed) throw new ObjectDisposedException("the window is closing");
            if (Answers != null) return Answers(command, argument);
            System.Threading.Interlocked.Increment(ref calls);
            try
            {
                lock (gate)
                {
                    if (closed) throw new ObjectDisposedException("the window is closing");
                    if (failures >= MaxFailures)
                    {
                        if (!action) return Reconnecting();
                        failures = MaxFailures - 1;
                        givenUp.Reset();
                    }
                    try
                    {
                        var reply = Ask(command, argument);
                        failures = 0;
                        return reply;
                    }
                    catch (Exception)
                    {
                        FailedLocked();
                        StopLocked();
                        if (closed) throw;
                        return Reconnecting();
                    }
                }
            }
            finally { System.Threading.Interlocked.Decrement(ref calls); }
        }

        private static Dictionary<string, object> Reconnecting()
        {
            var reply = new Dictionary<string, object>();
            reply["ok"] = false;
            reply["error"] = "the connection to the local service is being restored";
            reply["error_code"] = ReconnectingCode;
            return reply;
        }

        /// One call on the one-shot bridge, past the long-lived process and its lock (v0.6.5): for a command that can
        /// take minutes - the compatibility refresh waits up to 150 s on the network - which on the long-lived pipe
        /// would hold every read the window paints from, and past the pipe's own 30 s reply limit would end the
        /// process under it. Called from a worker thread only, as every bridge call is.
        internal Dictionary<string, object> CallOnce(string command, string argument)
        {
            if (closed) throw new ObjectDisposedException("the window is closing");
            if (Answers != null) return Answers(command, argument);
            System.Threading.Interlocked.Increment(ref calls);
            try { return once.Call(command, argument, Bridge.LongCallMilliseconds); }
            finally { System.Threading.Interlocked.Decrement(ref calls); }
        }

        /// Whether the long-lived process is given up for now (for the tests).
        internal bool GivenUp { get { return failures >= MaxFailures; } }

        /// One more failure of the long-lived process. v0.6.23: a chosen Python that has failed it MaxFailures times is
        /// left for the bundled one, for the life of this window, and the count starts again: this is what keeps the
        /// Advanced features page, and its Back to the bundled version, reachable while the chosen runtime is broken.
        private void FailedLocked()
        {
            failures++;
            if (failures < MaxFailures) return;
            if (string.Equals(python, bundled, StringComparison.OrdinalIgnoreCase))
            {
                givenUp.Restart();
                return;
            }
            python = bundled;
            once.UseBundled();
            failures = 0;
        }

        private Dictionary<string, object> Ask(string command, string argument)
        {
            if (process == null || process.HasExited) StartLocked();
            int id = ++nextId;
            var line = new StringBuilder("{\"id\":").Append(id.ToString(CultureInfo.InvariantCulture))
                                                     .Append(",\"command\":").Append(Json.Escape(command));
            if (!string.IsNullOrEmpty(argument)) line.Append(",\"argument\":").Append(argument);
            line.Append("}\n");
            byte[] bytes = new UTF8Encoding(false).GetBytes(line.ToString());
            Stream input = process.StandardInput.BaseStream;
            input.Write(bytes, 0, bytes.Length);
            input.Flush();
            Task<string> read = process.StandardOutput.ReadLineAsync();
            if (!read.Wait(ReplyMilliseconds)) throw new TimeoutException("the local service did not answer");
            if (read.Result == null) throw new InvalidOperationException("the local service closed");
            var envelope = (Dictionary<string, object>)Json.Parse(read.Result);
            object got;
            if (!envelope.TryGetValue("id", out got) || got == null ||
                Convert.ToInt32(got, CultureInfo.InvariantCulture) != id)
                throw new InvalidOperationException("the local service answered out of turn");
            return (Dictionary<string, object>)envelope["reply"];
        }

        private void StartLocked()
        {
            var info = new ProcessStartInfo();
            info.FileName = python;
            string code = "import sys;sys.path.insert(0,sys.argv[1]);" +
                          "from codex_auto_resume.controlcli import main;" +
                          "sys.exit(main(sys.argv[2:]))";
            // "-c", as the one-shot bridge has it: without it python.exe takes the code for a
            // script path, exits, and every call silently falls back to the one-shot bridge.
            info.Arguments = Bridge.NoRemoteDebug + "-c " + Bridge.Quote(code) + " " + Bridge.Quote(appSrc) + " serve";
            info.UseShellExecute = false;
            info.RedirectStandardInput = true;
            info.RedirectStandardOutput = true;
            info.RedirectStandardError = true;
            info.CreateNoWindow = true;
            info.StandardOutputEncoding = Encoding.UTF8;
            process = Process.Start(info);
            // Drained, so a child that writes to stderr can never block on a full pipe.
            process.ErrorDataReceived += delegate { };
            process.BeginErrorReadLine();
        }

        /// Called as the window closes, on its own thread - so it must not wait for a call
        /// that a worker is in the middle of. Waiting would hold the closing window for up
        /// to the reply timeout; ending the process ends that call instead.
        internal void Stop()
        {
            closed = true;
            // v0.6.18: the one-shot children too - the fallback of a call a worker is in the middle of, and CallOnce's -
            // which ending `process` never reached: StopLocked had set it to null before the fallback started.
            once.Stop();
            if (System.Threading.Monitor.TryEnter(gate))
            {
                try { StopLocked(); }
                finally { System.Threading.Monitor.Exit(gate); }
                return;
            }
            Process running = process;
            try { if (running != null && !running.HasExited) running.Kill(); }
            catch (Exception) { }
        }

        private void StopLocked()
        {
            Process running = process;
            process = null;
            if (running == null) return;
            try
            {
                if (!running.HasExited)
                {
                    running.StandardInput.Close();
                    if (!running.WaitForExit(2000)) running.Kill();
                }
            }
            catch (Exception) { }
            // The pipes and the process handle are released now rather than whenever the
            // finalizer gets to them.
            try { running.Dispose(); } catch (Exception) { }
        }
    }

    /// Presses one after another: seven, each within 1.8 s of the last, and it says so once and starts again.
    internal sealed class PressRun
    {
        internal const int Wanted = 7;
        internal const double Gap = 1800.0;

        private double last = double.NegativeInfinity;
        private int count;

        internal bool Press(double milliseconds)
        {
            count = milliseconds - last <= Gap ? count + 1 : 1;
            last = milliseconds;
            if (count < Wanted) return false;
            count = 0;
            return true;
        }
    }

    /// A line that can say something else for a moment, coming in and leaving by a fade and a small rise (paint only, in its own
    /// rectangle; immediate with motion reduced). What it is told meanwhile is what it says afterwards.
    internal sealed class AsideLabel : Label
    {
        internal const int InMs = 450, OutMs = 400, Rise = 5;

        private readonly Timer timer = new Timer();
        private readonly Transition fade;
        private string behind, words;
        private bool waiting, aside;
        private int holdMs;

        internal AsideLabel()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer, true);
            fade = new Transition(this, 1.0);
            timer.Tick += delegate
            {
                timer.Stop();
                if (waiting) Speak();
                else Return();
            };
        }

        internal bool Saying { get { return aside; } }

        /// Whether it is fading in or out (for the tests).
        internal bool Fading { get { return fade.Running; } }

        public override string Text
        {
            get { return base.Text; }
            set
            {
                if (aside || waiting) behind = value;
                else base.Text = value;
            }
        }

        /// In `delayMs` it says `said`, for `heldMs`.
        internal void Aside(string said, int delayMs, int heldMs)
        {
            if (!aside && !waiting) behind = base.Text;
            words = said;
            holdMs = heldMs;
            timer.Stop();
            aside = false;
            waiting = true;
            if (delayMs <= 0)
            {
                Speak();
                return;
            }
            timer.Interval = delayMs;
            timer.Start();
        }

        private void Speak()
        {
            waiting = false;
            aside = true;
            base.Text = words;
            Glide(InMs);
            timer.Interval = holdMs;
            timer.Start();
        }

        private void Return()
        {
            aside = false;
            base.Text = behind;
            Glide(OutMs);
        }

        private void Glide(int milliseconds)
        {
            fade.Jump(0.0);
            fade.To(1.0, Motion.Allowed(this), milliseconds);
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            if (!aside && !fade.Running)
            {
                base.OnPaint(e);
                return;
            }
            double shown = fade.Value;
            Color ink = Soft.Mix(Ground.Colour(this), aside ? Palette.Ink : ForeColor, shown);
            var line = new Rectangle(0, (int)Math.Round(Soft.Px(Rise) * (1.0 - shown)), Width, Height);
            TextRenderer.DrawText(e.Graphics, Text, Font, line, ink,
                                  Mirror.Words(Mirror.Of(this), TextFormatFlags.Top | TextFormatFlags.Left | TextFormatFlags.SingleLine |
                                                                TextFormatFlags.EndEllipsis | TextFormatFlags.NoPrefix));
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                timer.Dispose();
                fade.Dispose();
            }
            base.Dispose(disposing);
        }
    }

    /// A page tab that tells assistive technology it is one, and which one is selected.
    ///
    /// A plain button with AccessibleRole.PageTab announced its role but never its state,
    /// so a screen reader said "Overview, page tab" for every tab alike.
    internal sealed class NavButton : Button
    {
        private bool current, hover, pressed;
        private readonly SoftSurfaceGlide glide;

        /// A section in a vertical list rather than a tab in a strip: text starts at the left.
        internal bool Vertical;

        internal NavButton()
        {
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint |
                     ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
            FlatStyle = FlatStyle.Flat;
            FlatAppearance.BorderSize = 0;
            UseVisualStyleBackColor = false;
            Cursor = Cursors.Hand;
            glide = new SoftSurfaceGlide(this, Wanted);
            glide.Where = delegate { return Face; };
        }

        /// What its state looks like (v0.6.23): a tab at rest has no body, so one fades in from nothing under the pointer and
        /// on the chosen page. Only the tab moves; the page below it changes in one finished frame, as it always has.
        private SurfaceLook Wanted()
        {
            Color words = !current ? Palette.Secondary : Palette.Contrast ? SystemColors.HighlightText : Palette.Accent;
            if (current)
            {
                if (Palette.Contrast) return new SurfaceLook(Palette.AccentSoft, Palette.AccentSoft, words);
                if (Palette.AccentBar) return new SurfaceLook(SurfaceLook.None(Palette.Raised), SurfaceLook.None(Palette.Line), words, Palette.Accent);
                if (!Palette.Depth) return new SurfaceLook(Palette.AccentSoft, Palette.AccentSoft, words);
                return new SurfaceLook(Palette.Inset, Palette.Inset, words);
            }
            if (pressed) return new SurfaceLook(Palette.Inset, Palette.Line, words);
            if (hover) return new SurfaceLook(Palette.Raised, Palette.Line, words);
            return new SurfaceLook(SurfaceLook.None(Palette.Raised), SurfaceLook.None(Palette.Line), words);
        }

        private void Press(bool down)
        {
            if (pressed == down) return;
            pressed = down;
            glide.Changed(Motion.Press);
        }

        internal bool Current
        {
            get { return current; }
            set
            {
                if (current == value) return;
                current = value;
                glide.Changed();
                Invalidate();
                if (IsHandleCreated)
                {
                    AccessibilityNotifyClients(AccessibleEvents.StateChange, -1);
                    if (value) AccessibilityNotifyClients(AccessibleEvents.Selection, -1);
                }
            }
        }

        protected override void OnMouseEnter(EventArgs e) { hover = true; glide.Changed(); base.OnMouseEnter(e); }
        protected override void OnMouseLeave(EventArgs e) { hover = false; Press(false); glide.Changed(); base.OnMouseLeave(e); }
        protected override void OnMouseDown(MouseEventArgs e) { if (e.Button == MouseButtons.Left) Press(true); base.OnMouseDown(e); }
        protected override void OnMouseUp(MouseEventArgs e) { Press(false); base.OnMouseUp(e); }
        protected override void OnKeyDown(KeyEventArgs e) { if (e.KeyCode == Keys.Space) Press(true); base.OnKeyDown(e); }
        protected override void OnKeyUp(KeyEventArgs e) { if (e.KeyCode == Keys.Space) Press(false); base.OnKeyUp(e); }
        protected override void OnGotFocus(EventArgs e) { Invalidate(); base.OnGotFocus(e); }
        protected override void OnLostFocus(EventArgs e) { Press(false); Invalidate(); base.OnLostFocus(e); }

        protected override void Dispose(bool disposing)
        {
            if (disposing) glide.Dispose();
            base.Dispose(disposing);
        }

        /// v0.6.23 (the second round's F6): a tab in the strip is as wide as its name is in the wider of the strip's two weights -
        /// the chosen page's name is set in nav_current, every other in nav (ShowPage) - whichever it is set in now. Choosing a
        /// page changes only the weight drawn: no tab in the strip moves, and the tab pressed stays under the pointer. A section
        /// in Settings' column (Vertical) is sized by its column.
        public override Size GetPreferredSize(Size proposedSize)
        {
            Size size = base.GetPreferredSize(proposedSize);
            if (Vertical || string.IsNullOrEmpty(Text)) return size;
            int now = NameWidth(Font);
            int widest = Math.Max(NameWidth(Soft.RoleFont("nav")), NameWidth(Soft.RoleFont("nav_current")));
            if (widest > now) size.Width += widest - now;
            return size;
        }

        // The name's width in `font`, on one line (remembered: Soft.Measure).
        private int NameWidth(Font font)
        {
            return Soft.Measure(Text, font, int.MaxValue, TextFormatFlags.SingleLine).Width;
        }

        /// v0.6.20: the arrow keys along a mirrored strip of tabs go the way it reads - Left to the next tab, which stands
        /// left of this one, and Right back to the one before - as they go the way it reads left to right (Mirror).
        protected override bool ProcessDialogKey(Keys keyData)
        {
            return base.ProcessDialogKey(Vertical ? keyData : Mirror.Arrow(Mirror.Of(this), keyData));
        }

        /// The tab's body. Room is kept around it for the focus ring, which a child window cannot
        /// draw outside itself.
        internal Rectangle Face
        {
            get
            {
                int ring = Soft.Px(Brand.FocusOffset + Brand.FocusWidth);
                return Rectangle.Inflate(ClientRectangle, -ring, -ring);
            }
        }

        /// Where the name is set: the body, and in the section list less its indent.
        internal Rectangle TextBounds
        {
            get
            {
                Rectangle bounds = Face;
                if (Vertical)
                {
                    // v0.6.20: indented from the right in a mirrored window (Mirror).
                    bounds.X += Mirror.Of(this) ? Soft.Px(4) : Soft.Px(12);
                    bounds.Width = Math.Max(0, bounds.Width - Soft.Px(16));
                }
                return bounds;
            }
        }

        // The panel's tab, drawn as its segmented control draws a choice. The pages not chosen
        // are muted words straight on the canvas, which come up as a raised body with a hairline
        // under the pointer; the chosen page is pressed into a well, its name in the accent. The
        // state is also in the weight of the text and in what a screen reader is told, never in
        // colour alone. v0.6.10: in Classic the chosen page is underlined in the accent, as v0.6.2's
        // tabs were (a section of Settings, whose tabs stand in a column, has the bar at its left), and
        // in Plain it is a flat quiet-accent ground - neither design has a well to press it into.
        protected override void OnPaint(PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            // The ground behind the tab, lifts included: the header card's shadow runs on under
            // the tabs rather than stopping at the edge of each one.
            Ground.PaintArea(this, g, ClientRectangle);
            Rectangle face = Face;
            float radius = Soft.PxF(Palette.RadiusControl);
            // High Contrast keeps what it had: Highlight, with HighlightText on it (Wanted). The well's inset shadow has no
            // way to fade, so it comes in past half way.
            SurfaceLook look = glide.Now;
            bool well = current && !Palette.Contrast && !Palette.AccentBar && Palette.Depth && glide.Progress >= 0.5;
            if (look.Fill.A > 0 || look.Edge.A > 0) Soft.Body(g, face, radius, look.Fill, look.Edge, well);
            if (look.Mark.A > 0) Underline(g, face, look.Mark);
            Color text = look.Ink;
            TextRenderer.DrawText(g, Text, Font, TextBounds, text,
                                  Mirror.Words(Mirror.Of(this),
                                               TextFormatFlags.VerticalCenter | TextFormatFlags.SingleLine | TextFormatFlags.EndEllipsis |
                                               (Vertical ? TextFormatFlags.Left : TextFormatFlags.HorizontalCenter)));
            if (Focused && ShowFocusCues) Soft.Ring(g, face, radius);
        }

        /// Classic's current tab (v0.6.2's): an AccentBar-high line in the accent along the bottom of `face`, in from
        /// its ends as that release's was - or, for a section of Settings in its column, as high as the name and at
        /// the left. Paint only, inside the body the tab always had.
        internal void Underline(Graphics g, Rectangle face)
        {
            Underline(g, face, Palette.Accent);
        }

        private void Underline(Graphics g, Rectangle face, Color colour)
        {
            int bar = Soft.Px(Brand.AccentBar), inset = Soft.Px(Brand.SpaceXs);
            // v0.6.20: a section's bar at the right in a mirrored window (Mirror).
            Rectangle line = Vertical
                ? new Rectangle(Mirror.Of(this) ? face.Right - bar : face.X, face.Y + inset, bar, face.Height - 2 * inset)
                : new Rectangle(face.X + inset, face.Bottom - bar, face.Width - 2 * inset, bar);
            if (line.Width > 0 && line.Height > 0) g.FillRectangle(Soft.Fill(colour), line);
        }

        protected override AccessibleObject CreateAccessibilityInstance()
        {
            return new NavAccessible(this);
        }

        private sealed class NavAccessible : ButtonBase.ButtonBaseAccessibleObject
        {
            private readonly NavButton owner;

            internal NavAccessible(NavButton owner) : base(owner) { this.owner = owner; }

            public override AccessibleRole Role { get { return AccessibleRole.PageTab; } }

            public override AccessibleStates State
            {
                get
                {
                    AccessibleStates state = base.State | AccessibleStates.Selectable;
                    if (owner.Current) state |= AccessibleStates.Selected;
                    return state;
                }
            }
        }
    }

    /// A line that reports what an action did.
    ///
    /// Declared a polite live region (see Note()), which is what a screen reader follows
    /// for a sentence that appears somewhere the focus is not; the name-change event
    /// below is the same news through the older interface. Neither announces a repeat of
    /// the identical sentence, which is why the note is also left on screen.
    internal sealed class NoteLabel : WrapLabel
    {
        protected override void OnTextChanged(EventArgs e)
        {
            base.OnTextChanged(e);
            if (IsHandleCreated && Text.Length > 0) AccessibilityNotifyClients(AccessibleEvents.NameChange, -1);
        }
    }

    /// A line of text straight on the canvas beside a card.
    ///
    /// It paints the ground behind it, lifts included. A plain label paints a flat patch of its
    /// background colour, and the card below "Nothing is waiting" had no light along its top edge
    /// where the label covered it.
    internal sealed class GroundLabel : Label
    {
        internal GroundLabel()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.UserPaint, true);
        }

        protected override void OnPaintBackground(PaintEventArgs e)
        {
            Ground.Paint(this, e);
        }
    }

    /// A line of text that stays one line - a conversation's name, how its recovery ended - and
    /// ends in an ellipsis where it does not fit.
    ///
    /// A table asks a label for its size at the width of its column, and a plain label answers
    /// with as many lines as the text wraps to: four long conversation names took the Overview to
    /// 713 px of window at 150%, and 729 in German (measured, 900 px wide). The whole text is still
    /// the label's name for a screen reader; only what is drawn is cut.
    internal sealed class LineLabel : Label
    {
        internal LineLabel()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.UserPaint, true);
            AutoSize = true;
            AutoEllipsis = true;
            // A conversation is called whatever its owner called it, ampersands included.
            UseMnemonic = false;
        }

        public override Size GetPreferredSize(Size proposedSize)
        {
            // Remembered (Soft.Measure, v0.6.14): a table asks for this at several widths in every pass.
            Size line = Soft.Measure(string.IsNullOrEmpty(Text) ? " " : Text, Font, int.MaxValue,
                                     TextFormatFlags.SingleLine | TextFormatFlags.NoPrefix);
            int width = line.Width + Padding.Horizontal;
            if (MaximumSize.Width > 0) width = Math.Min(width, MaximumSize.Width);
            if (proposedSize.Width > 1 && proposedSize.Width < width) width = proposedSize.Width;
            return new Size(width, line.Height + Padding.Vertical);
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            bool mirrored = Mirror.Of(this);
            var bounds = new Rectangle(mirrored ? Padding.Right : Padding.Left, Padding.Top, Math.Max(0, Width - Padding.Horizontal),
                                       Math.Max(0, Height - Padding.Vertical));
            TextRenderer.DrawText(e.Graphics, Text, Font, bounds, ForeColor,
                                  Mirror.Words(mirrored, TextFormatFlags.SingleLine | TextFormatFlags.EndEllipsis | TextFormatFlags.NoPrefix |
                                                         TextFormatFlags.Left | TextFormatFlags.Top));
        }
    }

    /// v0.6.11: the whole of a line that ends in an ellipsis where it does not fit (LineLabel), while the pointer rests
    /// on it - in the window's own colours and font rather than Windows' own tooltip, which knows neither the theme nor
    /// the design: its words in ink, wrapped at a readable width. v0.6.23: on a card of the cards' own material, as every other
    /// overlay is (SoftTipWindow). Windows' tooltip still says when; in High Contrast it is still what is drawn.
    internal sealed class SoftTip : ToolTip
    {
        // How far the words stand in from the tip's edge, and the widest a line of them runs, at 96 DPI.
        private const int Inset = 8, Widest = 420;
        private const TextFormatFlags Flags = TextFormatFlags.WordBreak | TextFormatFlags.NoPrefix | TextFormatFlags.Left |
                                              TextFormatFlags.Top;

        private SoftTipWindow card;
        private Control over;
        private readonly Timer popDown = new Timer();
        private readonly EventHandler left;
        private readonly MouseEventHandler pressed;

        /// The card showing now, or null (for the tests).
        internal SoftTipWindow Card { get { return card; } }

        internal SoftTip()
        {
            OwnerDraw = true;
            left = delegate { Close(); };
            pressed = delegate { Close(); };
            popDown.Tick += delegate { Close(); };
            Popup += delegate(object sender, PopupEventArgs e)
            {
                string text = GetToolTip(e.AssociatedControl) ?? "";
                Size words = TextRenderer.MeasureText(text, Soft.BaseFont, new Size(Soft.Px(Widest), int.MaxValue), Flags);
                e.ToolTipSize = new Size(words.Width + 2 * Soft.Px(Inset), words.Height + 2 * Soft.Px(Inset));
                if (Palette.Contrast || e.AssociatedControl == null) return;
                e.Cancel = true;
                Open(e.AssociatedControl, text, words);
            };
            Draw += delegate(object sender, DrawToolTipEventArgs e)
            {
                e.Graphics.FillRectangle(Soft.Fill(Palette.Raised), e.Bounds);
                using (var pen = new Pen(Palette.Line))
                    e.Graphics.DrawRectangle(pen, e.Bounds.X, e.Bounds.Y, e.Bounds.Width - 1, e.Bounds.Height - 1);
                TextRenderer.DrawText(e.Graphics, e.ToolTipText, Soft.BaseFont,
                                      Rectangle.Inflate(e.Bounds, -Soft.Px(Inset), -Soft.Px(Inset)), Palette.Ink,
                                      Mirror.Words(Mirror.Of(e.AssociatedControl), Flags));
            };
        }

        /// The card for `control`, under the pointer, until the pointer leaves it or presses, or Windows' own time is up.
        internal void Open(Control control, string text, Size words)
        {
            Close();
            over = control;
            over.MouseLeave += left;
            over.MouseDown += pressed;
            over.Disposed += left;
            bool mirrored = Mirror.Of(control);
            Point at = Cursor.Position;
            card = new SoftTipWindow(text, words, Soft.Px(Inset), Mirror.Words(mirrored, Flags));
            card.Show(mirrored ? at.X - card.CardWidth : at.X, at.Y + Soft.Px(20), Screen.FromPoint(at).WorkingArea, Motion.Allowed(control));
            popDown.Interval = Math.Max(1000, AutoPopDelay);
            popDown.Start();
        }

        private void Close()
        {
            popDown.Stop();
            // v0.6.23 (the second round's F8): it fades out as it faded in, as the menu and the drop-down leave (SoftTipWindow.Close).
            bool fade = over != null && Motion.Allowed(over);
            if (over != null)
            {
                over.MouseLeave -= left;
                over.MouseDown -= pressed;
                over.Disposed -= left;
                over = null;
            }
            if (card != null) card.Close(fade);
            card = null;
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                Close();
                popDown.Dispose();
            }
            base.Dispose(disposing);
        }
    }

    /// A small bar chart of how recoveries ended, drawn to the same scale for every bar.
    internal sealed class OutcomeChart : Panel
    {
        /// One bar: the outcome's words, its count, and its part in the success rate as the statistics answer gives it
        /// (outcome_groups: "success", "failure" or "other").
        internal sealed class Bar
        {
            public readonly string Key;
            public readonly int Value;
            public readonly string Group;

            internal Bar(string key, int value, string group)
            {
                Key = key;
                Value = value;
                Group = group ?? "";
            }
        }

        internal List<Bar> Bars = new List<Bar>();
        // v0.6.22 (the owner, 2026-11-08): three colours by what an outcome means for the success rate - the accent
        // (BarColor) for a recovery, the warning colour (FailureColor) for an outcome the rate counts as not succeeded,
        // and a muted slate (OtherColor) for one it leaves out, and for a group the window does not know. Which outcome
        // is which is the statistics answer's (the store's one rule), never a list here.
        internal Color BarColor, FailureColor, OtherColor, TextColor;
        internal string EmptyText = "";

        internal OutcomeChart()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                     ControlStyles.UserPaint | ControlStyles.ResizeRedraw, true);
            grow = new Transition(this, 1.0);
        }

        private readonly Transition grow;
        private string[] seenKeys = new string[0];
        private double[] seenShares = new double[0], fromShares = new double[0];

        /// Whether its bars are on their way to new lengths; its timer runs only then.
        internal bool Growing { get { return grow.Running; } }

        /// The numbers have been read again (v0.6.23): the bars glide to their new lengths, when they are the same bars. A row
        /// that comes or goes, or the same rows in another order, is a new chart and is simply drawn. Paint only.
        internal void Changed()
        {
            int max = 0;
            foreach (var bar in Bars) max = Math.Max(max, bar.Value);
            var keys = new string[Bars.Count];
            var shares = new double[Bars.Count];
            bool sameRows = seenKeys.Length == keys.Length, sameLengths = sameRows;
            for (int index = 0; index < keys.Length; index++)
            {
                keys[index] = Bars[index].Key;
                shares[index] = max == 0 ? 0.0 : Bars[index].Value / (double)max;
                if (sameRows && keys[index] != seenKeys[index]) sameRows = sameLengths = false;
                else if (sameRows && shares[index] != seenShares[index]) sameLengths = false;
            }
            if (sameRows && sameLengths) return;
            var from = new double[keys.Length];
            if (sameRows) for (int index = 0; index < from.Length; index++) from[index] = Share(index);
            fromShares = from;
            seenKeys = keys;
            seenShares = shares;
            grow.Jump(0.0);
            grow.To(1.0, sameRows && Motion.Allowed(this));
        }

        // How much of the track bar `index` stands on now: its share of the longest, or between shares while it glides.
        private double Share(int index)
        {
            if (index >= seenShares.Length) return 0.0;
            if (!grow.Running || index >= fromShares.Length) return seenShares[index];
            return fromShares[index] + (seenShares[index] - fromShares[index]) * grow.Value;
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing) grow.Dispose();
            base.Dispose(disposing);
        }

        // Spacing is written at 96 DPI and scaled like the rest of the window. The text is
        // already scaled by its font, so unscaled gaps beside it look cramped at 200%.
        private static int Px(int atNinetySix)
        {
            return Soft.Px(atNinetySix);
        }

        /// A row: a line of text and the room round its bar for the control's lift in the Soft design, the same in
        /// every design (a design changes paint, never where anything is).
        internal int RowHeight()
        {
            return Font.Height + Px(12);
        }

        internal Color ColorOf(string group)
        {
            if (group == "success") return BarColor;
            if (group == "failure") return FailureColor;
            return OtherColor;
        }

        /// The numbers as words, for whoever cannot see the bars.
        internal void Describe()
        {
            var spoken = new List<string>();
            foreach (var bar in Bars)
                spoken.Add(bar.Key + " " + bar.Value.ToString(CultureInfo.CurrentCulture));
            AccessibleDescription = spoken.Count == 0 ? EmptyText : string.Join(", ", spoken.ToArray());
        }

        /// Where each bar's body is, in the chart's own coordinates, one for each of Bars.
        internal Rectangle[] Faces()
        {
            int max = 0;
            foreach (var bar in Bars) max = Math.Max(max, bar.Value);
            var faces = new Rectangle[max == 0 ? 0 : Bars.Count];
            if (max == 0) return faces;
            bool mirrored = Mirror.Of(this);
            int row = RowHeight();
            int labelWidth = LabelWidth();
            int track = Track(labelWidth);
            for (int index = 0, y = 0; index < Bars.Count; index++, y += row)
            {
                int bodyWidth = Math.Max(Px(2), Length(index, max, track));
                int left = mirrored ? Width - labelWidth - Px(12) - bodyWidth : labelWidth + Px(12);
                faces[index] = new Rectangle(left, y + Px(5), bodyWidth, Font.Height - Px(2));
            }
            return faces;
        }

        private int LabelWidth()
        {
            int labelWidth = 0;
            foreach (var bar in Bars)
                labelWidth = Math.Max(labelWidth, TextRenderer.MeasureText(bar.Key, Font).Width);
            return labelWidth;
        }

        private int Track(int labelWidth)
        {
            int numberWidth = TextRenderer.MeasureText("0000", Font).Width;
            return Math.Max(Px(10), Width - labelWidth - numberWidth - Px(24));
        }

        // Bar `index`'s length on a track `track` long: as far as its glide has come while it has one (Changed), and what its
        // number says, of the longest, otherwise.
        private int Length(int index, int max, int track)
        {
            if (grow.Running && index < seenShares.Length) return (int)Math.Round(track * Share(index));
            return (int)Math.Round(track * (Bars[index].Value / (double)max));
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            base.OnPaint(e);
            e.Graphics.Clear(BackColor);
            int max = 0;
            foreach (var bar in Bars) max = Math.Max(max, bar.Value);
            // v0.6.20: mirrored, each word at the right, its bar growing left from beside it and its number past the
            // bar's end (Mirror).
            bool mirrored = Mirror.Of(this);
            if (max == 0)
            {
                TextRenderer.DrawText(e.Graphics, EmptyText, Font, ClientRectangle, TextColor,
                                      Mirror.Words(mirrored, TextFormatFlags.Top | TextFormatFlags.WordBreak));
                return;
            }
            int row = RowHeight();
            int labelWidth = LabelWidth();
            int track = Track(labelWidth);
            // v0.6.22 (the owner's mock A, 2026-11-08): in the Soft design each bar is a pill raised off the card with the
            // control's lift, as a raised button is. Every lift is stamped before any body, so one bar's shadow never lies over
            // its neighbour. v0.6.23 (the second round's F10): a pill in every design and in High Contrast, as their switch
            // tracks, meters and scroll thumbs are round-ended - a design changes depth, not shape; the lift alone is Soft's.
            Rectangle[] faces = Faces();
            if (Palette.Depth)
                foreach (var face in faces)
                    Elevation.StampOuter(e.Graphics, face, "control", face.Height / 2f, ClientRectangle);
            for (int index = 0, y = 0; index < Bars.Count; index++, y += row)
            {
                Bar bar = Bars[index];
                Rectangle face = faces[index];
                Color fill = ColorOf(bar.Group);
                Soft.Body(e.Graphics, face, face.Height / 2f, fill, fill, null);
                string number = bar.Value.ToString(CultureInfo.CurrentCulture);
                int length = Length(index, max, track);
                if (mirrored)
                {
                    var word = new Rectangle(Width - labelWidth, y + Px(4), labelWidth, row - Px(4));
                    TextRenderer.DrawText(e.Graphics, bar.Key, Font, word, TextColor,
                                          Mirror.Words(true, TextFormatFlags.Top | TextFormatFlags.SingleLine));
                    int numberWide = TextRenderer.MeasureText(number, Font).Width;
                    TextRenderer.DrawText(e.Graphics, number, Font, new Point(Width - labelWidth - Px(18) - length - numberWide, y + Px(4)),
                                          TextColor);
                }
                else
                {
                    TextRenderer.DrawText(e.Graphics, bar.Key, Font, new Point(0, y + Px(4)), TextColor);
                    TextRenderer.DrawText(e.Graphics, number, Font, new Point(labelWidth + Px(18) + length, y + Px(4)), TextColor);
                }
            }
        }

        protected override AccessibleObject CreateAccessibilityInstance()
        {
            return new ChartAccessible(this);
        }

        // Screen readers read a control's value more consistently than its description, so
        // the chart's data is its value as well.
        private sealed class ChartAccessible : Control.ControlAccessibleObject
        {
            private readonly OutcomeChart chart;

            internal ChartAccessible(OutcomeChart owner) : base(owner) { chart = owner; }

            public override string Value { get { return chart.AccessibleDescription ?? ""; } }
        }
    }

    /// Why a task is waiting: the watcher's safety checks, each with its last result.
    ///
    /// The results are the ones the watcher itself recorded the last time it looked at the
    /// task, read back from the store - nothing here evaluates a check, and nothing here can
    /// make one pass.
    internal sealed class GateList : Control
    {
        private readonly List<string[]> rows = new List<string[]>();   // label, result word, result code
        private string empty = "";
        // v0.6.11: a sentence under the rows - why the first check that did not pass stops it - or "".
        private string note = "";
        /// The sentence under the rows, as it was last set (the audits and the tests read it), and what it says with none.
        internal string Note { get { return note; } }
        internal string Empty { get { return empty; } }

        internal GateList()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                     ControlStyles.UserPaint | ControlStyles.ResizeRedraw, true);
            TabStop = false;
            AccessibleRole = AccessibleRole.List;
            AutoSize = true;
        }

        private int RowHeight { get { return Font.Height + Soft.Px(12); } }

        internal void SetRows(List<string[]> fresh, string whenEmpty)
        {
            SetRows(fresh, whenEmpty, null);
        }

        internal void SetRows(List<string[]> fresh, string whenEmpty, string under)
        {
            // The snapshot arrives every five seconds and the checks in it rarely move, so the same
            // thirteen rows were rebuilt, given a new accessible description and handed a full parent
            // layout every time - on the window's thread, whether or not this page was the one on
            // screen. Identical rows are now nothing to do.
            if (Same(fresh, whenEmpty) && note == (rows.Count == 0 ? "" : under ?? "")) return;
            GateFills++;
            rows.Clear();
            rows.AddRange(fresh);
            empty = whenEmpty ?? "";
            note = rows.Count == 0 ? "" : under ?? "";
            var spoken = new List<string>();
            foreach (string[] row in rows) spoken.Add(row[0] + ": " + row[1]);
            if (note.Length > 0) spoken.Add(note);
            AccessibleDescription = rows.Count == 0 ? empty : string.Join(", ", spoken.ToArray());
            if (Parent != null) Parent.PerformLayout();
            Invalidate();
        }

        internal static int GateFills;

        /// Whether these are the rows it already holds, word for word, in the same order.
        private bool Same(List<string[]> fresh, string whenEmpty)
        {
            if (fresh == null || rows.Count != fresh.Count || empty != (whenEmpty ?? "")) return false;
            for (int i = 0; i < rows.Count; i++)
            {
                string[] mine = rows[i], theirs = fresh[i];
                if (mine == null || theirs == null || mine.Length != theirs.Length) return false;
                for (int c = 0; c < mine.Length; c++)
                    if (mine[c] != theirs[c]) return false;
            }
            return true;
        }

        // What it says with no checks to show: wrapped, Korean between its words (Soft.Wrap).
        private const TextFormatFlags EmptyFormat = TextFormatFlags.WordBreak | TextFormatFlags.Left;

        public override Size GetPreferredSize(Size proposedSize)
        {
            int width = proposedSize.Width > 0 && proposedSize.Width < 20000 ? proposedSize.Width : Soft.Px(260);
            string text = empty.Length == 0 ? " " : empty;
            int height = rows.Count == 0
                ? TextRenderer.MeasureText(Soft.Wrap(text, Font, width, EmptyFormat), Font, new Size(width, int.MaxValue),
                                           EmptyFormat).Height
                : rows.Count * RowHeight + NoteHeight(width);
            return new Size(width, height);
        }

        /// The sentence under the rows, wrapped at `width`, with the gap above it; 0 when there is none.
        private int NoteHeight(int width)
        {
            if (note.Length == 0) return 0;
            return Soft.Px(8) + TextRenderer.MeasureText(Soft.Wrap(note, Font, width, EmptyFormat), Font,
                                                         new Size(width, int.MaxValue), EmptyFormat).Height;
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            Color ground = Parent != null ? Parent.BackColor : Palette.Card;
            g.Clear(ground);
            // v0.6.20: mirrored, each check's name from the right and its chip at the row's left end (Mirror).
            bool mirrored = Mirror.Of(this);
            if (rows.Count == 0)
            {
                TextRenderer.DrawText(g, Soft.Wrap(empty, Font, Width, EmptyFormat), Font, ClientRectangle, Palette.Secondary,
                                      Mirror.Words(mirrored, EmptyFormat));
                return;
            }
            int y = 0, height = RowHeight;
            // The rows of a settings list in the panel: a hairline between each two, and the result
            // as a borderless chip at the end of the row.
            using (var rule = new SolidBrush(Palette.Line))
                foreach (string[] row in rows)
                {
                    Color tone = row[2] == "PASS" ? Palette.Success : row[2] == "WAIT" ? Palette.Waiting
                               : row[2] == "BLOCK" ? Palette.Danger : Palette.Paused;
                    if (y > 0) g.FillRectangle(rule, 0, y, Width, Soft.Hairline);
                    Size chip = Soft.ChipSize(row[1], Font);
                    var label = Mirror.Box(mirrored, Width, new Rectangle(0, y, Math.Max(0, Width - chip.Width - Soft.Px(8)), height));
                    TextRenderer.DrawText(g, row[0], Font, label, Palette.Ink,
                                          Mirror.Words(mirrored, TextFormatFlags.VerticalCenter | TextFormatFlags.Left |
                                                                 TextFormatFlags.SingleLine | TextFormatFlags.EndEllipsis));
                    Soft.Chip(g, Mirror.Box(mirrored, Width, new Rectangle(Math.Max(0, Width - chip.Width), y, chip.Width, height)),
                              row[1], Font, tone, ground, mirrored);
                    y += height;
                }
            if (note.Length > 0)
                TextRenderer.DrawText(g, Soft.Wrap(note, Font, Width, EmptyFormat), Font,
                                      new Rectangle(0, y + Soft.Px(8), Width, Math.Max(0, Height - y - Soft.Px(8))),
                                      Palette.Secondary, Mirror.Words(mirrored, EmptyFormat));
        }
    }

    internal sealed partial class SettingsForm
    {
        // ------------------------------------------------------------------ state
        // Both are grounds on the canvas (see Ground): the tabs sit straight on it, under the
        // header card, and the header card's lift runs on across them.
        private readonly Panel nav = new SoftPage();
        private readonly Panel pageHost = new SoftPage();
        // How long ago the snapshot on screen was read (see ShowPage). Started again only when a
        // read answers (Reread): a page built later is handed the snapshot already held (PageFor),
        // and restarting it there made an old snapshot look new, so a first visit never read.
        private readonly Stopwatch snapshotAge = new Stopwatch();
        private const int FreshMilliseconds = 2000;
        private readonly Dictionary<string, Control> pages = new Dictionary<string, Control>();
        private readonly Dictionary<string, NavButton> navButtons = new Dictionary<string, NavButton>();
        private static readonly string[] PageOrder = { "overview", "pending", "history", "statistics",
                                                       "diagnostics", "settings" };
        private string firstPage = "overview";
        private string currentPage;
        private Button saveButton, restoreButton;
        private Timer clock;
        private int ticks;
        // One dashboard read at a time; a request made during one is remembered here.
        private bool refreshing, refreshAgain;
        // Actions in flight. While there is one, every other action waits its turn, visibly.
        private int busy;
        // Work a page started that outlasts the call that started it: a job of the service this window talks to, which
        // ends with the window. While there is any, the window does not reopen itself (CheckReopen, HoldReopen); unlike
        // `busy`, it holds back no other action.
        private int reopenHolds;
        // Which statistics request is the latest, so an older answer never overwrites a newer one.
        private int statsToken;
        // One statistics read at a time; a period change made during one is remembered here.
        private bool loadingStats, statsAgain;
        // What the pause button currently stands for; null until a status has been read.
        private bool? shownEnabled;
        // v0.6.11: whether an administrator's DisableUpdateCheck is in force (the status's `managed`).
        private bool updatesManaged;
        private Dictionary<string, object> snapshot;
        // Lists whose first row has already been preselected once (see Preselect).
        private readonly Dictionary<ListView, bool> preselected = new Dictionary<ListView, bool>();
        // Set while a list is being rebuilt, when its selection events say nothing about
        // what the person chose.
        private bool filling;

        // Overview
        private Label nowRecovery, nowWatcher, nowEngine, nowLastCheck, waitingLine, nextLine,
                      runningLine, usageLine, weekDetected, weekSent, weekRecovered, weekSuccess, recentEmpty;
        // v0.6.11: the usage line's whole text, while the pointer rests on it (WaitingLine).
        private SoftTip lineTip;
        private Button toggleButton;
        private TableLayoutPanel recentGrid;
        private string recentShown;
        // Pending and history
        private ListView pendingList, historyList;
        private Label pendingEmpty, historyEmpty;
        private Button retryButton, cancelButton, timelineButton, threadButton, cancelAllButton;
        // v0.6.16 (issue #39): every waiting recovery looked at again, after the person says yes.
        private Button rescanButton;
        // Why the selected task is waiting.
        private GateList explainList;
        // The soft page Why it is waiting scrolls its checks on, for the render mode (WindowRender.cs).
        private SoftPage explainPage;
        private Label explainAsOf;
        // The Pending list's Auto-resume column, a check box for the task on its row.
        private const int ResumeColumn = 5;
        // v0.6.19 (the owner's decision of 2026-10-24): a list row that is not a recovery - the advanced edition's queued
        // message, reset rule or delivered message (ListRowsJoined) - carries what kind it is, the key it is known by in
        // the list, and the sentence Why it is waiting says of it. Nothing of a recovery's is offered on it: no switch, no
        // menu, none of a recovery's buttons.
        private const string RowKindKey = "row_kind", RowKeyKey = "row_key", RowSaidKey = "row_said";
        // v0.6.11: a Pending row's own menu, and whether the right button opened it - then it is the row under
        // the pointer's, and from the keyboard the chosen row's.
        private SoftMenu pendingMenu;
        private bool menuByMouse;
        // v0.6.19: the row a double left-click opened the menu on, until the menu has read it (PrepareRowMenu).
        private Dictionary<string, object> menuRow;
        // The times a task can be postponed by, and how much a conversation asks before it resumes, least first
        // (quiet.PRESETS, machine.IMPORTANCE_TIERS).
        private static readonly string[] PostponePresets = { "30_minutes", "1_hour", "3_hours", "tomorrow_morning" };
        private static readonly string[] PostponeEnglish = { "30 minutes", "1 hour", "3 hours", "Tomorrow at 09:00" };
        private static readonly string[] TierOrder = { "automatic", "objection_window", "ask_first", "notify_only" };
        private static readonly string[] TierEnglish = { "Resume automatically", "After a chance to object",
                                                         "Ask me first", "Only notify me" };
        // The Pending list's Next check column, which the clock writes (UpdateCountdowns).
        private const int CountdownColumn = 3;
        // The note that belongs to no single record: what Cancel all did.
        private const string BulkNote = "*";
        // The watcher's safety checks, in the order it evaluates them (machine.GATES).
        private static readonly string[] GateOrder = { "consent", "engine_compatible", "single_owner",
            "submission_safe", "identity", "known_failure", "schedule", "chain_budget", "attempt_budget",
            "no_progress_budget", "thread_available", "no_newer_user_work", "usage" };
        private NoteLabel pendingNote, historyNote;
        private string pendingNoteFor, pendingNoteText = "";
        // v0.6.19 (the owner's decision of 2026-10-24): the Rescan note this belongs to, what its click did about Codex's
        // usage, and when it asked for the reading (0: none) - so the note says what was read once the watcher has read it.
        private string rescanNoteText, rescanUsageNote;
        private double rescanAskedAt;
        /// The tests' answers to the window's questions, in place of the dialog (Dialog): null for every window a person
        /// opens, as PersistentBridge.Answers is.
        internal static Func<string, string, bool> DialogAnswers;
        private Button historyTimeline, historyReset, historyThread, historyClear;
        // Statistics
        private ComboBox period;
        private Label statsDetected, statsSent, statsRecovered, statsSuccess, statsWait, statsRecover,
                      statsRetry, statsKinds;
        private OutcomeChart chart;
        // Diagnostics
        private VersionLabel diagVersion;
        private Label diagWatcher, diagLastCheck, diagEngine, diagRecovery, diagStartup,
                      diagUpgrade, diagUpdate, diagMemory, diagPlugin, diagStateAccess, diagStateNote, diagWaiting;
        // v0.6.17: whether the watcher and this window's bridge run inside another app, and what that means.
        private Label diagHostApp, diagHostNote;
        // v0.6.11: Diagnostics' Show me what happens, which waits while an action runs.
        private Button demoButton;
        private Button exportButton, repairButton, stopButton, updateButton;
        // Codex compatibility (v0.6.5; BuildCompatibility): its facts, what the view cannot vouch for - a callout each,
        // since v0.6.10 - the parts in two lists, what each state word means, and the refresh with what it last answered.
        // What others report of the Codex version (v0.6.10) is one muted fact under it, compatReported.
        private Label compatOverall, compatEngine, compatReported, compatServer, compatChecked, compatData, compatLegend;
        private TableLayoutPanel compatNotice;
        private GateList compatLeft, compatRight;
        private Control compatLists;
        private NoteLabel compatNote;
        private Button compatButton;
        private string compatSaid = "";
        // The watcher's report as last read; the live check a refresh brought, shown instead while it stands over the
        // reports read after it (LiveStands); and whether the last read failed.
        private Dictionary<string, object> compatView, compatLive;
        // What the report said when the live check arrived (Reading): news the live check has already seen past.
        private string compatLiveOver;
        private bool compatUnreadable, loadingCompat, compatRefreshing;

        // ------------------------------------------------------ the advanced edition
        // Where the advanced edition's window joins this one (v0.6.11). Each is a `partial void`
        // with no body in any source gui/window.sources lists. `make_gui.ps1 -Edition advanced`
        // also compiles the sources advanced/gui/window.sources lists, and one of those may give
        // it a body. With no body the compiler removes the declaration and every call to it, so
        // the standard window does not hold a switched-off copy of either: it holds neither
        // (build/edition_audit.py; tests/test_edition_window.py builds it both ways).
        //
        // The Dashboard's pages and navigation are built, and the snapshot is shown on those
        // built so far.
        partial void DashboardBuilt();
        // v0.6.22: how much the Overview keeps under its two rows of cards, for what the edition shows there; nothing here.
        partial void OverviewRoomAsked(ref int under);
        // v0.6.23: once the standard pages have been made ready ahead of their first visit (PrepareNext), a page of the
        // advanced edition's to make ready the same way, by its name, which `prepared` does not yet hold; and that page,
        // built as its tab's first press builds it.
        partial void EditionPageNamed(List<string> prepared, ref string name);
        partial void EditionPageFor(string name, ref Control page);
        // A snapshot has been shown (ApplySnapshot), or there is none and the pages say so
        // (MarkUnavailable, with null). A page of the advanced edition follows the same read.
        partial void SnapshotApplied(Dictionary<string, object> reply);
        // Pending has been built but for its buttons (BuildPending): what the advanced edition has
        // waiting for a reset - its own rules, not recoveries - is shown under the list (v0.6.14).
        partial void PendingBuilt(Panel page);
        // The cells of one row of Pending (`pending`) or History have been written (Cells): what the advanced edition
        // says of a row it had a hand in joins the cell's line, never a cell or a column of its own (v0.6.16-beta.4).
        partial void CellsWritten(Dictionary<string, object> row, bool pending, string[] cells);
        // One argument of the window's command line has been read (ParseArguments): a page of
        // the advanced edition's, or the keyboard on its tab, is one the standard checks refuse.
        static partial void ArgumentParsed(string argument, OpenRequest request);
        // The arguments a window that reopens itself passes on have been written (ReopenArguments),
        // with only the standard window's pages and places among them.
        static partial void ReopenArgumentsWritten(string page, string focus, List<string> arguments);
        // The render mode (gui/WindowRender.cs) has put the window in a frame's state as far as the
        // standard window goes: a page of the advanced edition's, and what the frame asks of it, is
        // put in place here, `moved` set when anything changed.
        partial void RenderStateNamed(Dictionary<string, object> frame, RenderWriter writer, ref bool moved);
        // v0.6.19 (the owner's decision of 2026-10-24): a person's Retry now or Rescan has asked the watcher to read Codex's
        // usage once. The advanced edition counts that reading as one of early_reset's two while it stands on.
        partial void UsageAsked();
        // v0.6.19 (the owner's decision of 2026-10-24): Why it is waiting has said the usage readings of a recovery that
        // waits for a usage limit (WithUsage); the advanced edition adds early_reset's own to `said`.
        partial void UsageNoted(Dictionary<string, object> row, List<string> said);
        // v0.6.19 (the owner's decision of 2026-10-24: Pending is one list): a list (Pending or History) is about to be
        // filled from `rows` - the advanced edition adds the rows of its own to it (EditionRow), after the recoveries.
        partial void ListRowsJoined(ListView list, List<Dictionary<string, object>> rows);
        // Pending's buttons and History's are built (BuildPending, BuildHistory), before their notes: the advanced edition
        // adds its own to `row`.
        partial void PendingButtonsBuilt(FlowLayoutPanel row);
        partial void HistoryButtonsBuilt(FlowLayoutPanel row);
        // The chosen row of Pending, or of History, has been offered its buttons (UpdatePendingButtons,
        // UpdateHistoryButtons): the advanced edition offers its own for a row of its own, and hides them otherwise.
        partial void PendingButtonsUpdated(Dictionary<string, object> row, bool idle);
        partial void HistoryButtonsUpdated(Dictionary<string, object> row, bool idle);
        // A row of the edition's own was double-clicked on Pending (a recovery's opens its menu).
        partial void EditionRowOpened(Dictionary<string, object> row);
        // Clear history was pressed: the advanced edition, while History lists completed messages of its own, asks and
        // clears them together with the finished recoveries, and says so (`handled`); otherwise Clear history is as it was.
        partial void ClearHistoryPressed(ref bool handled);
        // v0.6.20 (the owner's report of 2026-10-26): the header's light and headline have been decided from what the window
        // read (Hero), just before they are written: the advanced edition, while a message of its chat is waiting to be
        // delivered or on its way, changes them to the working light and the words that say so.
        partial void HeroTold(ref string light, ref string head);

        // ----------------------------------------------------------------- chrome
        private void BuildDashboard()
        {
            // `--page=<name>` opens on that page (`--settings` is the older spelling) and `--section=<name>`
            // on that Settings section; each is checked against the pages and sections there are
            // (ParseArguments), and anything else opens the Overview and General.
            if (request.Page != null) firstPage = request.Page;
            if (request.Section != null) currentSection = request.Section;
            // v0.6.23: `--dialog=` (ParseArguments: Pending, and a row's dialog) is asked for once the rows are read.
            if (request.RowDialog != null) rowAsked = request.RowDialog;

            nav.Dock = DockStyle.Top;
            nav.Padding = Pad(12, 0, 14, 0);
            var strip = new SoftFlow();
            strip.Dock = DockStyle.Fill;
            strip.FlowDirection = FlowDirection.LeftToRight;
            strip.WrapContents = false;
            strip.Margin = new Padding(0);
            strip.AccessibleRole = AccessibleRole.PageTabList;
            string[] fallbacks = { "Overview", "Pending", "History", "Statistics", "Diagnostics", "Settings" };
            for (int i = 0; i < PageOrder.Length; i++)
            {
                string name = PageOrder[i];
                var button = new NavButton();
                button.Text = S("nav." + name, fallbacks[i]);
                button.Font = Soft.RoleFont("nav");
                button.AutoSize = true;
                button.AutoSizeMode = AutoSizeMode.GrowAndShrink;
                button.FlatStyle = FlatStyle.Flat;
                button.FlatAppearance.BorderSize = 0;
                button.ForeColor = Secondary;
                // The panel's tab padding, 7 by 14, inside the room NavButton keeps for its ring.
                button.Padding = Pad(18, 8, 18, 8);
                button.Margin = Pad(0, 0, 2, 0);
                button.Cursor = Cursors.Hand;
                button.UseVisualStyleBackColor = false;
                string target = name;
                button.Click += delegate { ShowPage(target); };
                navButtons[name] = button;
                strip.Controls.Add(button);
            }
            nav.Controls.Add(strip);
            // As tall as the tabs, measured, and again whenever the window's font changes - with the room the chosen
            // tab's heavier words take (ShowPage sets it in nav_current): in Microsoft YaHei UI the bold is a face of
            // its own, a pixel taller than the regular, and the chosen tab was cut off at the strip's foot (v0.6.17).
            EventHandler fit = delegate { nav.Height = strip.PreferredSize.Height + HeavierTab(strip) + nav.Padding.Vertical; };
            fit(this, EventArgs.Empty);
            FontChanged += fit;

            pageHost.Dock = DockStyle.Fill;

            // The Dashboard's pages are built the first time each is shown (PageFor). Settings is
            // built here, empty, and filled with editors once the settings have been read.
            columns.Visible = false;
            pageHost.Controls.Add(columns);
            pages["settings"] = columns;

            KeyPreview = true;
            KeyDown += delegate(object sender, KeyEventArgs e)
            {
                // Ctrl+Tab and Ctrl+Shift+Tab move between pages, as in any tabbed window.
                if (e.Control && e.KeyCode == Keys.Tab)
                {
                    int index = Array.IndexOf(PageOrder, currentPage);
                    index = (index + (e.Shift ? PageOrder.Length - 1 : 1)) % PageOrder.Length;
                    ShowPage(PageOrder[index]);
                    e.Handled = true;
                }
                else if (e.KeyCode == Keys.F5)
                {
                    RefreshNow();
                    if (currentPage == "statistics") LoadStatistics();
                    if (currentPage == "diagnostics") LoadCompatibility();
                    e.Handled = true;
                }
            };
            DashboardBuilt();
        }

        private void ShowPage(string name)
        {
            if (Array.IndexOf(PageOrder, name) < 0) name = "overview";
            // v0.6.23 (round 5): what making it ready ahead holds of it let go first, innermost first, as it would be.
            if (preparing == name) LetGoAll();
            currentPage = name;
            bool settings = name == "settings";
            // Settings asked for before its editors were built on idle: built now, before it shows.
            if (settings) BuildPendingEditors();
            // Painting stops while one page is hidden and the next shown, so the page is painted
            // once, finished (see Redraw).
            bool paused = Redraw(pageHost, false);
            try
            {
                Control page = PageFor(name);
                // v0.6.23: what came while it was out of sight, written before it shows (Writes).
                WriteIfStale(name);
                // Every page stays in the host once built and only the one shown is visible: taking a
                // page off and putting the next on moved every native control in it to Windows'
                // parking window and back.
                pageHost.SuspendLayout();
                foreach (Control other in pageHost.Controls)
                    if (other != page) other.Visible = false;
                // Held while it becomes visible and laid out once after, as ShowSection holds a
                // section - and the Settings page holds the section it shows, which is where each
                // control that sizes itself asked for another layout: a switch to Settings took 113 ms
                // once its sections kept one width, and takes 58 held (measured, 150%).
                TableLayoutPanel section = settings && sections.ContainsKey(currentSection) ? sections[currentSection] : null;
                page.SuspendLayout();
                if (section != null) section.SuspendLayout();
                // Coming back to the Overview: its Waiting lines, which the clock writes only while it is in front
                // (UpdateCountdowns), written before it shows and so laid out with it.
                if (name == "overview" && snapshot != null) UpdateCountdowns();
                // v0.6.23: and everything in it that lays others out. Shown, each card, grid and row of the page asked for a
                // layout of its own, outermost first, and each one's layout asked the one around it again: Diagnostics took
                // 130-320 ms on every switch to it (measured 2026-11-11). Let go innermost first, each lays itself out once.
                List<Control> inner = HoldWithin(page);
                page.Visible = true;
                LetGoWithin(inner);
                if (section != null) section.ResumeLayout(true);
                page.ResumeLayout(true);
                pageHost.ResumeLayout(false);
                pageHost.PerformLayout();
                foreach (var pair in navButtons)
                {
                    pair.Value.ForeColor = pair.Key == name ? Ink : Secondary;
                    // Cached: a switch used to create a font for every tab.
                    pair.Value.Font = Soft.RoleFont(pair.Key == name ? "nav_current" : "nav");
                    pair.Value.Current = pair.Key == name;
                }
                if (saveButton != null) saveButton.Visible = settings;
                if (restoreButton != null) restoreButton.Visible = settings;
            }
            finally
            {
                if (paused) Redraw(pageHost, true);
            }
            // Coming back to Pending: the countdowns the clock did not write while it was hidden.
            if (name == "pending" && snapshot != null) WriteCountdowns(Now());
            if (auditing) return;
            if (name == "statistics") LoadStatistics();
            if (name == "diagnostics") LoadCompatibility();
            // The power action's card, if Settings opens on General: what Windows offers is asked once it is shown.
            if (settings) LoadPowerWhereShown();
            // v0.6.18: the Codex home the homes' card suggests, if Settings opens on Advanced.
            if (settings) LoadHomeSuggestionWhereShown();
            // Not when the snapshot on screen is under two seconds old: switching pages straight
            // after a read asked for the same answer again - 17-87 ms of Python and up to 45 ms of
            // redrawing, for nothing new.
            if (!settings && (snapshot == null || snapshotAge.ElapsedMilliseconds >= FreshMilliseconds)) RefreshNow();
        }

        /// A page, built the first time it is shown. Building all five before the first screen
        /// cost 75-290 ms, for pages most openings never visit. A page built after a snapshot has
        /// arrived is given that snapshot at once, so it never shows its placeholders.
        private Control PageFor(string name)
        {
            Control page;
            if (pages.TryGetValue(name, out page)) return page;
            // v0.6.23: a build begun ahead (BuildSome) finished now, at once; else the page built whole.
            PageBuild begun;
            if (pageBuilds.TryGetValue(name, out begun))
            {
                pageBuilds.Remove(name);
                while (begun.Steps.MoveNext()) { }
                page = begun.Page;
            }
            else
                page = name == "pending" ? BuildPending()
                     : name == "history" ? BuildHistory()
                     : name == "statistics" ? BuildStatistics()
                     : name == "diagnostics" ? BuildDiagnostics()
                     : BuildOverview();
            page.Visible = false;
            pages[name] = page;
            pageHost.Controls.Add(page);
            // v0.6.23: a page built out of sight - made ready ahead - is only marked, and written when it is (Writes,
            // WriteIfStale): a whole snapshot written for it cost 100-300 ms on an installation that had run for months.
            if (snapshot != null && !Writes(name)) return page;
            if (snapshot != null) ApplySnapshot(snapshot);
            return page;
        }

        /// v0.6.23: a page being built a step at a time (PendingSteps, DiagnosticsSteps) - the page as soon as its first step
        /// has made it, and the steps left.
        private sealed class PageBuild
        {
            internal Control Page;
            internal IEnumerator<bool> Steps;
        }

        // The builds begun ahead of their page's first visit (BuildSome), by page, until PageFor finishes one.
        private readonly Dictionary<string, PageBuild> pageBuilds = new Dictionary<string, PageBuild>();

        /// A page built by its steps, all of them, at once.
        private static Control Built(Func<PageBuild, IEnumerator<bool>> steps)
        {
            var build = new PageBuild();
            build.Steps = steps(build);
            while (build.Steps.MoveNext()) { }
            return build.Page;
        }

        /// One step of building `name` ahead, where its builder has steps; true while there are more. The last step
        /// leaves the build to PageFor, which finishes it (nothing is left) and puts the page in the host.
        private bool BuildSome(string name)
        {
            if (pages.ContainsKey(name)) return false;
            Func<PageBuild, IEnumerator<bool>> steps = name == "pending" ? (Func<PageBuild, IEnumerator<bool>>)PendingSteps
                                                     : name == "diagnostics" ? (Func<PageBuild, IEnumerator<bool>>)DiagnosticsSteps : null;
            if (steps == null) return false;
            PageBuild build;
            if (!pageBuilds.TryGetValue(name, out build))
            {
                build = new PageBuild();
                build.Steps = steps(build);
                pageBuilds[name] = build;
            }
            return build.Steps.MoveNext();
        }

        // ------------------------------------------------------------ pages made ready ahead (v0.6.23)
        // The owner (2026-11-11): a page took a moment to appear the first time its tab was pressed - building it, making
        // its native controls and laying it out all waited for the click (measured 2026-11-11, medians in four languages:
        // Pending 150-630 ms, Diagnostics 440-1420, Settings 320-760, the Advanced features page 340-680, where a page seen
        // before takes 15-320). Once
        // the window is on screen and has read its first snapshot, each page it has not shown is made ready the next times
        // nothing else is waiting: built by PageFor as a click builds it, given the room it will fill, its controls made and
        // laid out - hidden all the while, so nothing on screen changes. One step a turn, and none while a person is using
        // its mouse or keyboard (PrepareInput), so no step is taken while a hover or a click waits on it. A tab pressed
        // before its page is ready builds it as it always did. What a page shows is read as it always was: a page made
        // ready ahead is handed the snapshot already held (PageFor), and its own reads wait for its first visit (ShowPage).
        private readonly List<string> preparedPages = new List<string>();
        // The page being made ready and how far it has got: 0 not begun, 1 built, 2 written, 3 its controls made, 4 laid out
        // and its own reads asked, 5 those answered, 6 what they added made.
        private string preparing;
        private int prepareStep;
        private bool prepareQueued;

        // When this window last had a key or the mouse (PrepareInput), so no step is taken while a person uses it.
        private PrepareInput prepareInput;
        // How long its mouse and keyboard must have been still before a step is taken, in milliseconds.
        private const int PrepareAfterInputMilliseconds = 250;
        // How long one step makes native controls for before it leaves the rest to the next; and those still to be made.
        private const int PrepareSliceMilliseconds = 40;
        private Stack<Control> prepareMake;

        /// Starts making the pages not yet shown ready, on the window's idle turns, once it is on screen.
        private void PreparePagesLater()
        {
            if (!shown || prepareQueued || auditing || IsDisposed) return;
            prepareQueued = true;
            if (prepareInput == null) prepareInput = new PrepareInput();
            Application.AddMessageFilter(prepareInput);
            EventHandler idle = null;
            idle = delegate
            {
                if (IsDisposed || !PrepareNext())
                {
                    Application.Idle -= idle;
                    Application.RemoveMessageFilter(prepareInput);
                    prepareQueued = false;
                }
            };
            Application.Idle += idle;
        }

        /// One step of making a page ready; false when there is nothing left to make ready for now.
        private bool PrepareNext()
        {
            // Not before the first snapshot and the Settings editors: a page is built with what it will show, and the
            // editors are built first on these turns (BuildEditorsLater).
            if (snapshot == null || !settingsRead || pendingSchema != null || buildQueued) return true;
            if (busy > 0 || refreshing || prepareInput.Since < PrepareAfterInputMilliseconds) return true;
            if (preparing == null)
            {
                preparing = NextToPrepare();
                prepareStep = 0;
                if (preparing == null) return false;
            }
            // Built on the first step as a click builds it, the snapshot not yet written into it - it is out of sight, so
            // PageFor leaves it marked (Writes) - and written on the next (WriteIfStale), each a turn of its own: built and
            // written in one, Pending and Diagnostics held the window 550-750 ms on an installation that had run for
            // months (the live acceptance, 2026-11-11). A click in between writes it as it shows (ShowPage).
            // A page whose builder has steps is built a step a turn first (BuildSome).
            if (prepareStep == 0 && BuildSome(preparing)) return true;
            // Put in the page host on a turn of its own, and given its room on the next (round 5: the two together took
            // 260 ms for Diagnostics at that size).
            bool joining = prepareStep == 0 && Array.IndexOf(PageOrder, preparing) >= 0 && preparing != "settings" &&
                           !pages.ContainsKey(preparing);
            Control page = PreparedPage(preparing);
            if (page == null || Soft.OwnVisible(page))
            {
                // Shown meanwhile, by a click: ready as it is.
                Prepared();
                return true;
            }
            if (joining) return true;
            if (prepareStep == 0)
            {
                // Built (PreparedPage), and the room the page host will give it once shown, so it is never laid out
                // narrower first. Everything in it that lays others out held from now (round 5), so that its room, what
                // is written into it and what its reads add lay nothing out; let go a few at a time, innermost first, at
                // the end (LetGoSome) - as ShowPage lets a page go when it shows. Settings' room took 140-290 ms in one
                // turn, Diagnostics' compatibility answer 300-500, at that size.
                prepareHeld = HoldWithin(page);
                page.SuspendLayout();
                prepareHeld.Insert(0, page);
                page.Bounds = pageHost.DisplayRectangle;
                prepareStep = 1;
            }
            else if (prepareStep == 1)
            {
                WriteIfStale(preparing);
                prepareStep = 2;
            }
            else if (prepareStep == 2)
            {
                // Its native controls, made as showing it would make them while it stays hidden: in Materialise's order,
                // for PrepareSliceMilliseconds a turn (Settings' took 860 ms in one on that installation).
                if (MakeSome(page)) prepareStep = 3;
            }
            else if (prepareStep == 3)
            {
                // What it reads on each visit that the snapshot does not hold, read once now, so its first visit finds it
                // there as every later visit does; the visit reads it again (ShowPage).
                bool reads = preparing == "statistics" || preparing == "diagnostics";
                if (preparing == "statistics") LoadStatistics();
                if (preparing == "diagnostics") LoadCompatibility();
                prepareStep = reads ? 4 : 6;
            }
            else if (prepareStep == 4)
            {
                // Those answers written: whatever they added made, a few at a time, and laid out.
                if (!loadingStats && !loadingCompat && bridge.InFlight == 0) prepareStep = 5;
            }
            else if (prepareStep == 5)
            {
                if (MakeSome(page)) prepareStep = 6;
            }
            else if (prepareStep == 6)
            {
                if (LetGoSome()) prepareStep = 7;
            }
            else
            {
                page.PerformLayout();
                Prepared();
            }
            return true;
        }

        // What the page being made ready holds from laying itself out, outermost first, the page itself first of all
        // (PrepareNext); null when nothing is held.
        private List<Control> prepareHeld;

        /// Lets what the page being made ready holds lay itself out, innermost first, until PrepareSliceMilliseconds have
        /// gone; the page itself last, on a turn of its own. True once all are let go.
        private bool LetGoSome()
        {
            if (prepareHeld == null) return true;
            var slice = Stopwatch.StartNew();
            int let = 0;
            while (prepareHeld.Count > 1 && slice.ElapsedMilliseconds < PrepareSliceMilliseconds)
            {
                Control last = prepareHeld[prepareHeld.Count - 1];
                prepareHeld.RemoveAt(prepareHeld.Count - 1);
                if (!last.IsDisposed) last.ResumeLayout(true);
                let++;
            }
            if (let > 0) return false;
            LetGoAll();
            return true;
        }

        /// Lets everything the page being made ready holds go at once, innermost first: as it is shown, or given up.
        private void LetGoAll()
        {
            if (prepareHeld == null) return;
            List<Control> held = prepareHeld;
            prepareHeld = null;
            for (int i = held.Count - 1; i >= 0; i--)
                if (!held[i].IsDisposed) held[i].ResumeLayout(true);
        }

        /// Makes the native controls of `page` not yet made - each before the controls in it, siblings in their order, as
        /// Materialise makes them - until PrepareSliceMilliseconds have gone; true once all are made.
        private bool MakeSome(Control page)
        {
            if (prepareMake == null)
            {
                prepareMake = new Stack<Control>();
                prepareMake.Push(page);
            }
            var slice = Stopwatch.StartNew();
            while (prepareMake.Count > 0 && slice.ElapsedMilliseconds < PrepareSliceMilliseconds)
            {
                Control next = prepareMake.Pop();
                if (next.IsDisposed || next.Handle == IntPtr.Zero) continue;
                for (int i = next.Controls.Count - 1; i >= 0; i--)
                    if (Soft.OwnVisible(next.Controls[i])) prepareMake.Push(next.Controls[i]);
            }
            if (prepareMake.Count > 0) return false;
            prepareMake = null;
            return true;
        }

        private void Prepared()
        {
            LetGoAll();
            if (preparing != null && !preparedPages.Contains(preparing)) preparedPages.Add(preparing);
            preparing = null;
            prepareStep = 0;
            prepareMake = null;
        }

        /// Stamps the moment the window's thread last had a key or the mouse, and lets every message through.
        private sealed class PrepareInput : IMessageFilter
        {
            private readonly Stopwatch since = Stopwatch.StartNew();

            /// Milliseconds since the last key or mouse message.
            internal long Since { get { return since.ElapsedMilliseconds; } }

            public bool PreFilterMessage(ref Message m)
            {
                int message = m.Msg;
                // WM_KEYFIRST-WM_KEYLAST, WM_MOUSEFIRST-WM_MOUSELAST, and the mouse over a frame (WM_NCMOUSEMOVE-WM_NCXBUTTONDBLCLK).
                if ((message >= 0x0100 && message <= 0x0109) || (message >= 0x0200 && message <= 0x020E) ||
                    (message >= 0x00A0 && message <= 0x00AD))
                    since.Restart();
                return false;
            }
        }

        /// The next page to make ready: the Dashboard's in their order, Settings once its editors are built, then the
        /// advanced edition's.
        private string NextToPrepare()
        {
            foreach (string name in PageOrder)
            {
                // Shown once already, or made ready: its controls are made.
                Control built = name == "settings" ? columns : pages.ContainsKey(name) ? pages[name] : null;
                if (name != currentPage && !preparedPages.Contains(name) && (built == null || !built.IsHandleCreated)) return name;
            }
            string edition = null;
            EditionPageNamed(preparedPages, ref edition);
            return edition;
        }

        /// The page, built now if it has not been (PageFor); Settings is the page its editors are on.
        private Control PreparedPage(string name)
        {
            if (name == "settings") return columns;
            if (Array.IndexOf(PageOrder, name) >= 0) return PageFor(name);
            Control page = null;
            EditionPageFor(name, ref page);
            return page;
        }

        /// v0.6.23: every page in the page host but the one on screen held from laying itself out (LayOutHeld lets them
        /// go), while what they show is written. Each line written asked its whole page for a layout of its own, card by
        /// card up to the page's scrolling measure, and a page took them one by one: a snapshot with Diagnostics built
        /// cost 210 ms, and the compatibility answer for a Diagnostics not yet shown as much as 1.0-3.0 s (measured
        /// 2026-11-11). Laid out once after, each page is laid out from the same text as before, so it is the same page.
        private List<Control> HoldPages()
        {
            var held = new List<Control>();
            foreach (Control page in pageHost.Controls)
            {
                // Not the page on screen: its layout runs on as written, each step as before. Held too, the Overview's
                // History card kept its button 2 px under its corner after a refresh whose Pending could not be read
                // (test_gui_layout's states audit) - it takes more than one layout to settle.
                if (Soft.OwnVisible(page)) continue;
                page.SuspendLayout();
                held.Add(page);
            }
            return held;
        }

        private static void LayOutHeld(List<Control> held)
        {
            foreach (Control page in held) page.ResumeLayout(true);
        }

        /// v0.6.23: every control in `root` that holds others, outermost first, each held from laying itself out
        /// (LetGoWithin lets them go).
        private static List<Control> HoldWithin(Control root)
        {
            var held = new List<Control>();
            HoldWithin(root, held);
            return held;
        }

        private static void HoldWithin(Control parent, List<Control> held)
        {
            foreach (Control child in parent.Controls)
            {
                if (child.Controls.Count == 0) continue;
                child.SuspendLayout();
                held.Add(child);
                HoldWithin(child, held);
            }
        }

        /// Lets go innermost first, each laid out once if anything asked it to be.
        private static void LetGoWithin(List<Control> held)
        {
            for (int i = held.Count - 1; i >= 0; i--) held[i].ResumeLayout(true);
        }

        // v0.6.23 (the live acceptance, 2026-11-11): the pages a snapshot was not written into because they were out of
        // sight (Writes), each written when it is next shown (ShowPage); and the page being written although it is not
        // the one on screen - the page made ready ahead (PrepareNext), or brought up to date as it is shown.
        private readonly HashSet<string> stalePages = new HashSet<string>();
        private string writingPage;

        /// Whether a snapshot is written into `page` now: the page on screen and the one being written are; every other
        /// is marked to be written when it is shown. Every 5 s the snapshot was written into every page built - on an
        /// installation that had run for months, each refresh held the window 0.16-0.59 s for pages nobody was looking
        /// at. The layout audits write every page, as they measure every page.
        private bool Writes(string page)
        {
            if (auditing || page == currentPage || page == writingPage) return true;
            stalePages.Add(page);
            return false;
        }

        /// The snapshot written into `page` before it is shown, when a snapshot came while it was out of sight.
        private void WriteIfStale(string page)
        {
            if (!stalePages.Remove(page) || snapshot == null) return;
            string before = writingPage;
            writingPage = page;
            try { ApplySnapshot(snapshot); }
            finally { writingPage = before; }
        }

        private Panel Page()
        {
            var page = new SoftPage();
            page.Dock = DockStyle.Fill;
            // A page may scroll, and while it does it is the edge of the shadows on it (see Ground):
            // the cards' lift is kept inside its padding.
            page.Padding = CardRoom();
            page.Scrolls = true;
            return page;
        }

        private Label Value(string text)
        {
            // A value that wraps breaks Korean between its words (WrapLabel).
            return Value(new WrapLabel(), text);
        }

        private Label Value(WrapLabel label, string text)
        {
            label.Text = text;
            label.AutoSize = true;
            label.ForeColor = Ink;
            label.Margin = Pad(0, 3, 0, 3);
            return label;
        }

        /// A line of text straight on the canvas beside a card, which keeps the card's lift where
        /// a plain label would cover it (see GroundLabel).
        private Label GroundText(string text)
        {
            var label = new GroundLabel();
            label.Text = text;
            label.AutoSize = true;
            label.ForeColor = Ink;
            label.Margin = Pad(0, 3, 0, 3);
            return label;
        }

        private NoteLabel Note()
        {
            var note = new NoteLabel();
            note.AutoSize = true;
            note.ForeColor = Secondary;
            note.LiveSetting = AutomationLiveSetting.Polite;
            note.Margin = Pad(4, 8, 0, 0);
            return note;
        }

        private static void SetNote(Label note, string text)
        {
            if (note.Text != text) note.Text = text;
        }

        private TableLayoutPanel Facts(TableLayoutPanel card)
        {
            var grid = new SoftStack();
            grid.ColumnCount = 2;
            grid.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            grid.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
            grid.AutoSize = true;
            grid.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            grid.Dock = DockStyle.Fill;
            // None of its own: the default is 3 px that never scaled, which set every fact 3 px in
            // from the card's heading and added 6 px to each card of the Overview.
            grid.Margin = new Padding(0);
            // Opaque, in the card's own colour. See-through, every repaint of the grid and of each
            // label in it asked the card to paint its background again, shadow and all: 23 card
            // backgrounds for one Overview, and 1.4 s the first time Statistics was shown. A ground
            // (SoftStack), because a button pinned beside the facts lifts over the grid.
            grid.BackColor = Card;
            card.Controls.Add(grid);
            return grid;
        }

        private Label Fact(TableLayoutPanel grid, string label)
        {
            return Fact(grid, label, new WrapLabel());
        }

        /// A fact whose value is `value`: a WrapLabel, or one that draws itself otherwise (Diagnostics' Version, VersionLabel).
        private T Fact<T>(TableLayoutPanel grid, string label, T value) where T : WrapLabel
        {
            var name = Value(label);
            name.ForeColor = Secondary;
            name.Margin = Pad(0, 3, 18, 3);
            Value(value, "-");
            grid.Controls.Add(name);
            grid.Controls.Add(value);
            return value;
        }

        private TableLayoutPanel Grid(int columnCount)
        {
            var grid = new SoftStack();
            grid.Dock = DockStyle.Top;
            grid.AutoSize = true;
            grid.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            grid.ColumnCount = columnCount;
            for (int i = 0; i < columnCount; i++) grid.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f / columnCount));
            return grid;
        }

        /// The gap around a card in a grid of two columns, as the panel's page gap: half of it on
        /// each side of the gutter between the columns, all of it under every row but the last.
        private Padding GridGap(int column, bool lastRow)
        {
            int half = Brand.PageGap / 2;
            return Pad(column == 0 ? 0 : half, 0, column == 0 ? half : 0, lastRow ? 0 : Brand.PageGap);
        }

        /// The gap around a card in the Overview's grid, whose rows FitOverview sizes: between the columns as GridGap
        /// has it, and between the rows half of the page gap under the one and half over the other, so rows of one
        /// height are cards of one height.
        private Padding RowGap(int column, int row)
        {
            int half = Brand.PageGap / 2;
            return Pad(column == 0 ? 0 : half, row == 0 ? 0 : half, column == 0 ? half : 0, row == 0 ? half : 0);
        }

        private FlowLayoutPanel ButtonRow()
        {
            var row = new SoftFlow();
            row.Dock = DockStyle.Bottom;
            row.AutoSize = true;
            row.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            row.WrapContents = true;
            row.Padding = Pad(0, 12, 0, 0);
            return row;
        }

        private ListView List(string accessibleName, params KeyValuePair<string, int>[] columnSpec)
        {
            var list = new SoftList();
            list.View = View.Details;
            list.FullRowSelect = true;
            list.MultiSelect = false;
            list.HideSelection = false;
            list.Dock = DockStyle.Fill;
            list.BorderStyle = BorderStyle.None;
            list.BackColor = Card;
            list.ForeColor = Ink;
            list.AccessibleName = accessibleName;
            // Rows tall enough for a state chip at any scaling. A ListView takes its row height
            // from its small image list and from nothing else it will listen to.
            list.SmallImageList = new ImageList();
            list.SmallImageList.ImageSize = new Size(1, Math.Max(16, Math.Min(255, Px(34))));
            list.OwnerDraw = true;
            list.DrawColumnHeader += DrawHeader;
            list.DrawItem += delegate { };
            list.DrawSubItem += DrawCell;
            var weights = new int[columnSpec.Length];
            for (int i = 0; i < columnSpec.Length; i++)
            {
                list.Columns.Add(columnSpec[i].Key, Px(columnSpec[i].Value));
                weights[i] = columnSpec[i].Value;
            }
            // The columns share the list's width in the proportions they were declared with, so
            // the last one - the Auto-resume box - is never pushed past a scroll bar.
            columnWeights[list] = weights;
            list.ClientSizeChanged += delegate { FitColumns(list); };
            return list;
        }

        private readonly Dictionary<ListView, int[]> columnWeights = new Dictionary<ListView, int[]>();

        private void FitColumns(ListView list)
        {
            int[] weights;
            if (!columnWeights.TryGetValue(list, out weights) || list.Columns.Count != weights.Length) return;
            int total = 0;
            foreach (int weight in weights) total += weight;
            // All of it: the header control paints whatever the columns leave in plain white.
            int available = list.ClientSize.Width;
            if (available < Px(160) || total <= 0) return;
            // Each column's heading, the widest cell under it and the least it is drawn at; how wide each is then
            // follows what the list has room for (ColumnFloors), and what is left past that is shared in the declared
            // proportions.
            int[] cells;
            cellWidths.TryGetValue(list, out cells);
            var heading = new int[weights.Length];
            var least = new int[weights.Length];
            for (int i = 0; i < weights.Length; i++)
            {
                heading[i] = HeadingWidth(list, i);
                least[i] = LeastWidth(list, i);
            }
            int[] floor = ColumnFloors(heading, cells, least, Px(ReadableCells), available);
            int floors = 0;
            foreach (int width in floor) floors += width;
            int spare = Math.Max(0, available - floors);
            int used = 0;
            for (int i = 0; i < weights.Length; i++)
            {
                int width = i == weights.Length - 1 ? Math.Max(floor[i], available - used)
                          : floor[i] + (int)Math.Floor(spare * (double)weights[i] / total);
                if (list.Columns[i].Width != width) list.Columns[i].Width = width;
                used += width;
            }
        }

        /// How much of what a column holds is kept before a heading gives way (ColumnFloors): about a dozen characters,
        /// with the cell's inset - twice the least a column is drawn at (LeastWidth).
        internal const int ReadableCells = 96;

        /// The least each of a list's columns is given, `available` wide (v0.6.5): `heading` each heading's width whole,
        /// `cells` each column's widest cell (null before any was measured), `least` the least each is drawn at
        /// (LeastWidth), `readable` how much of what a column holds is kept before a heading gives way (ReadableCells).
        /// What the list has past their total is shared in the declared proportions (FitColumns).
        ///
        /// As the list narrows, what gives way, in turn:
        ///   * a conversation's name past its heading: every other column keeps its heading and its widest cell whole,
        ///     and the conversation's has what they leave - a name may be as long as its owner made it, and a state or a
        ///     kind cut short says nothing. From the headings alone, a status needed the window 1,239 px wide before
        ///     "waiting for the usage reset" was drawn whole (measured, 150%);
        ///   * cells past a readable width: every heading stays whole - "Next check", "Attempts" and "Auto-resume" were
        ///     cut short in a window of v0.6.2's width - and every column keeps what it holds up to `readable`; what is
        ///     left past that goes to the columns that want the least first, each whole in turn, the widest held to one cap;
        ///   * headings wider than what their column holds, the widest first, each down to the next widest, never below
        ///     what the column holds, readable;
        ///   * last, the cells, the widest first, never below the least. Only a list narrower than every column's least
        ///     is wider than its card, and scrolls sideways on the soft bar (SoftListHost).
        /// A heading and the cells under it that no longer fit end in an ellipsis (DrawHeader, DrawCell). The columns kept
        /// every heading whole whatever the list's width until v0.6.5, so a list narrower than its headings - a window
        /// made narrower than it opens - was wider than its card, with Windows' own white bar under the rows; then the
        /// headings alone gave way, and the review found the German Pending list 800 px wide at 200% with "Status" and
        /// "Art" at three or four letters of what they hold while "Versuche" kept 70 px for a single digit and the
        /// switch's column 100 for its 40 px switch. Widest first rather than in proportion, so a time or a count - which
        /// says nothing cut - stays whole while a long state or name ends in an ellipsis.
        internal static int[] ColumnFloors(int[] heading, int[] cells, int[] least, int readable, int available)
        {
            int count = heading.Length, others = 0, keeps = 0, holds = 0;
            var full = new int[count];
            var hold = new int[count];
            var keep = new int[count];
            for (int i = 0; i < count; i++)
            {
                int cell = cells != null && i < cells.Length ? cells[i] : 0;
                // A conversation's name holds only as much as its heading, past which it gives way first.
                int need = Math.Max(least[i], i == 0 ? Math.Min(cell, heading[0]) : cell);
                full[i] = Math.Max(heading[i], i == 0 ? cell : need);
                hold[i] = Math.Max(least[i], Math.Min(need, readable));
                keep[i] = Math.Max(heading[i], hold[i]);
                if (i > 0) others += full[i];
                keeps += keep[i];
                holds += hold[i];
            }
            var widths = new int[count];
            if (count == 0) return widths;
            if (heading[0] + others <= available)
            {
                for (int i = 1; i < count; i++) widths[i] = full[i];
                widths[0] = Math.Max(heading[0], Math.Min(full[0], available - others));
                return widths;
            }
            if (keeps <= available)
            {
                // What is left past what each keeps goes first to the columns that want the least past it, each whole in
                // turn, and the widest are held to one cap: a time, a kind or a count stays whole while a long state ends
                // in an ellipsis. Up to v0.6.19-beta.3 it was shared in proportion to what each wanted, which cut every
                // column a little - "Every day 09:00" to "Every day 09:..." beside a state cut too (the owner, 2026-10-25).
                widths[0] = keep[0];
                int under = 0, over = 0;
                for (int i = 1; i < count; i++) over = Math.Max(over, full[i]);
                while (under < over)
                {
                    int cap = (under + over + 1) / 2, total = keep[0];
                    for (int i = 1; i < count; i++) total += Math.Min(full[i], Math.Max(keep[i], cap));
                    if (total <= available) under = cap;
                    else over = cap - 1;
                }
                for (int i = 1; i < count; i++) widths[i] = Math.Min(full[i], Math.Max(keep[i], under));
                return widths;
            }
            bool headings = holds <= available;
            int top = 0;
            for (int i = 0; i < count; i++) top = Math.Max(top, headings ? keep[i] : hold[i]);
            // The widest a heading, or else a cell, may stay: the largest cap under which the columns fit.
            int low = 0, high = top;
            while (low < high)
            {
                int cap = (low + high + 1) / 2;
                if (Capped(keep, hold, least, cap, headings, null) <= available) low = cap;
                else high = cap - 1;
            }
            Capped(keep, hold, least, low, headings, widths);
            return widths;
        }

        // The columns' total with every heading (`headings`: each column between what it holds and its heading), or else
        // every cell (between the least and what it holds), held to `cap`; each width into `widths` when it is given.
        private static int Capped(int[] keep, int[] hold, int[] least, int cap, bool headings, int[] widths)
        {
            int total = 0;
            for (int i = 0; i < keep.Length; i++)
            {
                int width = headings ? Math.Max(hold[i], Math.Min(keep[i], cap)) : Math.Max(least[i], Math.Min(hold[i], cap));
                if (widths != null) widths[i] = width;
                total += width;
            }
            return total;
        }

        /// The narrowest a column is drawn: an ellipsis and a letter or two of its heading - DrawHeader's inset and
        /// 34 px - or, for Pending's Auto-resume column, its switch whole (DrawResumeBox) with DrawCell's inset.
        private int LeastWidth(ListView list, int column)
        {
            if (list == pendingList && column == ResumeColumn) return Px(Brand.SwitchWidth + 2) + Px(14);
            return Px(48);
        }

        // The widest cell of each column, as DrawCell draws it, measured when a list's rows change
        // (MeasureCells) - not on every resize, which for a long history was every cell again.
        private readonly Dictionary<ListView, int[]> cellWidths = new Dictionary<ListView, int[]>();

        /// Measures the widest cell of every column, and fits the columns again.
        private void MeasureCells(ListView list)
        {
            var widths = new int[list.Columns.Count];
            int rows = 0;
            foreach (ListViewItem item in list.Items)
            {
                // Enough to know the widths by; a history of thousands is not measured whole.
                if (++rows > 200) break;
                for (int c = 0; c < widths.Length && c < item.SubItems.Count; c++)
                    widths[c] = Math.Max(widths[c], CellWidth(list, item, c));
            }
            cellWidths[list] = widths;
            FitColumns(list);
        }

        /// How wide `item`'s cell in `column` is drawn whole, DrawCell's inset with it.
        private int CellWidth(ListView list, ListViewItem item, int column)
        {
            var record = item.Tag as Dictionary<string, object>;
            // The countdown as the clock writes it now: the cell holds only what the last tick wrote, and nothing
            // yet in a row just added, so a list's first fit left the column no room for its time (v0.6.5). Not for a
            // row of the edition's own, whose cell keeps what it was written with (WriteCountdowns): measured as the
            // countdown it never shows, its "Every day 09:00" was cut to "Every day 09:..." (the owner, 2026-10-25).
            string text = list == pendingList && column == CountdownColumn && !EditionRow(record)
                        ? CountdownText(record, Now()) : item.SubItems[column].Text;
            // A state chip where DrawCell draws one: the second column of a row that has its record.
            int width = column == 1 && record != null ? Soft.ChipSize(text, list.Font).Width
                      : list == pendingList && column == ResumeColumn ? Px(Brand.SwitchWidth + 2)
                      : TextRenderer.MeasureText(text, list.Font, new Size(int.MaxValue, int.MaxValue), TextFormatFlags.SingleLine).Width;
            // DrawCell's inset: 10 before, 4 after.
            return width + Px(14);
        }

        /// How much taller the tallest tab of `strip` is set in nav_current than in the font it has now: 0 where the
        /// heavier weight is no taller, as in Segoe UI and Malgun Gothic.
        private static int HeavierTab(Control strip)
        {
            int more = 0;
            var any = new Size(int.MaxValue, int.MaxValue);
            Font heavy = Soft.RoleFont("nav_current");
            foreach (Control control in strip.Controls)
            {
                var tab = control as NavButton;
                if (tab == null || string.IsNullOrEmpty(tab.Text) || ReferenceEquals(tab.Font, heavy)) continue;
                more = Math.Max(more, TextRenderer.MeasureText(tab.Text, heavy, any, TextFormatFlags.SingleLine).Height -
                                      TextRenderer.MeasureText(tab.Text, tab.Font, any, TextFormatFlags.SingleLine).Height);
            }
            return more;
        }

        /// How wide a column must be for its heading to be drawn whole: the heading in the list's
        /// font, DrawHeader's inset around it, and never less than 48 px.
        private int HeadingWidth(ListView list, int column)
        {
            int heading = TextRenderer.MeasureText(list.Columns[column].Text, list.Font, new Size(int.MaxValue, int.MaxValue),
                                                   TextFormatFlags.SingleLine).Width;
            return Math.Max(Px(48), heading + Px(14));
        }

        /// How wide a list must be for every heading to be drawn whole.
        private int HeadingsWidth(ListView list)
        {
            int total = 0;
            for (int i = 0; i < list.Columns.Count; i++) total += HeadingWidth(list, i);
            return total;
        }

        /// A list on its own card, filling it.
        private Control ListCard(ListView list)
        {
            var card = new SoftCard();
            card.Dock = DockStyle.Fill;
            card.ColumnCount = 1;
            card.RowCount = 1;
            card.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
            card.RowStyles.Add(new RowStyle(SizeType.Percent, 100f));
            // Its body is the whole control; the page it stands on draws its lift (see SoftCard).
            card.Padding = Pad(8, 8, 8, 8);
            card.Margin = new Padding(0);
            // The list scrolls on the soft bar, not its own (see SoftListHost).
            var host = new SoftListHost(list);
            host.Dock = DockStyle.Fill;
            host.Margin = new Padding(0);
            card.Controls.Add(host, 0, 0);
            return card;
        }

        /// A dialog's list on the card History puts its list on (v0.6.20, the owner 2026-10-28): the same ListCard, standing on
        /// a ground that fills the dialog's middle and keeps the room round the card that the History page's padding keeps
        /// (CardRoom: the lift reaches 16 px up and left, 17 down and right), so the card is lifted from the dialog's
        /// canvas as it is from the page's. The one place a dialog's list is made: the receipt (Timeline), the log, Install
        /// another version and the advanced edition's Find a conversation all call it, and its rows stay the flat
        /// hairline rows every list here has. The caller adds the result to its dialog, docked Fill; what is inside takes
        /// its width from the dialog's own client width.
        private Control DialogListCard(ListView list)
        {
            var ground = new SoftStack();
            ground.Name = "dialog_list_ground";
            ground.Dock = DockStyle.Fill;
            ground.ColumnCount = 1;
            ground.RowCount = 1;
            ground.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
            ground.RowStyles.Add(new RowStyle(SizeType.Percent, 100f));
            ground.Padding = CardRoom();
            ground.Margin = new Padding(0);
            ground.Controls.Add(ListCard(list), 0, 0);
            return ground;
        }

        /// What a dialog searches its list with (`row`: a search box and what goes with it), moved onto the list's own card above
        /// the list (v0.6.23, the second round's F9): a field stands on a card wherever it is, as every other dialog's do
        /// (DialogBodyCard). `ground` is what DialogListCard made; the row keeps its own layout, on the card's ground, with
        /// the card's room above the list under it.
        private void SearchOnCard(Control ground, Control row)
        {
            var card = ground.Controls.Count > 0 ? ground.Controls[0] as SoftCard : null;
            if (card == null || card.Controls.Count == 0) return;
            Control host = card.Controls[0];
            card.SuspendLayout();
            card.RowStyles.Clear();
            card.RowCount = 2;
            card.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            card.RowStyles.Add(new RowStyle(SizeType.Percent, 100f));
            card.SetCellPosition(host, new TableLayoutPanelCellPosition(0, 1));
            row.Dock = DockStyle.Fill;
            row.BackColor = Palette.Card;
            row.Padding = Pad(0, 0, 0, 8);
            row.Margin = new Padding(0);
            card.Controls.Add(row, 0, 0);
            card.ResumeLayout(false);
        }

        /// A dialog's fields on a card, as the same fields stand on the Settings page (v0.6.23, the design audit's D2): `body` -
        /// a text well, or the column a dialog stacks its words and fields in - laid on a SoftCard, on a ground with the room
        /// the card's lift reaches into. The one place a dialog's body goes on a card: every dialog holding a field or a well
        /// calls this (or DialogListCard for a list); tests/test_gui_v0623_motion.py finds one that does not. The dialog grows
        /// by DialogCardGrowth, so what is inside keeps the width and the height it was laid out for.
        private Control DialogBodyCard(Control body)
        {
            var card = new SoftCard();
            card.Dock = DockStyle.Fill;
            card.ColumnCount = 1;
            card.RowCount = 1;
            card.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
            card.RowStyles.Add(new RowStyle(SizeType.Percent, 100f));
            card.Padding = Pad(12, 12, 12, 12);
            card.Margin = new Padding(0);
            body.Dock = DockStyle.Fill;
            body.Margin = new Padding(0);
            if (!(body is SoftTextArea)) body.BackColor = Palette.Card;
            if (!(body is SoftTextArea)) body.Padding = new Padding(0);
            card.Controls.Add(body, 0, 0);
            var ground = new SoftStack();
            ground.Name = "dialog_body_ground";
            ground.Dock = DockStyle.Fill;
            ground.ColumnCount = 1;
            ground.RowCount = 1;
            ground.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
            ground.RowStyles.Add(new RowStyle(SizeType.Percent, 100f));
            // The lift's room, and even left and right: the card ends where the dialog's buttons do.
            ground.Padding = Pad(16, 16, 16, 17);
            ground.Margin = new Padding(0);
            ground.Controls.Add(card, 0, 0);
            // Two tables deep a table measures what it holds at no width at all: what wraps was asked for one line.
            ground.Measured = body;
            ground.Around = new Size(ground.Padding.Horizontal + card.Padding.Horizontal, ground.Padding.Vertical + card.Padding.Vertical);
            return ground;
        }

        /// What a dialog's client area grows by for DialogBodyCard: the card's padding and the rest of its lift, less the 12 px its
        /// button row no longer keeps above itself (the lift's room is that gap now).
        private Size DialogCardGrowth()
        {
            return new Size(Px(24), Px(29));
        }

        private void DrawHeader(object sender, DrawListViewColumnHeaderEventArgs e)
        {
            e.Graphics.FillRectangle(Soft.Fill(Card), e.Bounds);
            e.Graphics.FillRectangle(Soft.Fill(Line), e.Bounds.Left, e.Bounds.Bottom - Soft.Hairline, e.Bounds.Width, Soft.Hairline);
            // v0.6.20: mirrored, the heading from its column's right, read right to left (Mirror; the columns themselves are
            // in the other order, SoftListHost.MirrorColumns).
            bool mirrored = ListMirrored(sender as ListView);
            var bounds = new Rectangle(e.Bounds.X + (mirrored ? Px(4) : Px(10)), e.Bounds.Y, Math.Max(0, e.Bounds.Width - Px(14)),
                                       e.Bounds.Height);
            TextRenderer.DrawText(e.Graphics, e.Header.Text, e.Font, bounds, Secondary,
                                  Mirror.Words(mirrored, TextFormatFlags.VerticalCenter | TextFormatFlags.Left |
                                                         TextFormatFlags.SingleLine | TextFormatFlags.EndEllipsis));
        }

        /// Whether a list's rows are drawn mirrored (v0.6.20): its host's window is (Mirror). The list itself never is
        /// (SoftListHost), so its own RightToLeft says nothing.
        private static bool ListMirrored(ListView list)
        {
            return list != null && Mirror.Of(list.Parent);
        }

        /// A cell's bounds, worked out from the columns' order rather than asked of Windows: for the first column Windows
        /// answers the whole row from its left edge, wherever that column stands - at the right, in a mirrored window.
        private static Rectangle CellBounds(ListView list, DrawListViewSubItemEventArgs e)
        {
            int x = e.Item.Bounds.Left, at = list.Columns[e.ColumnIndex].DisplayIndex;
            foreach (ColumnHeader column in list.Columns)
                if (column.DisplayIndex < at) x += column.Width;
            return new Rectangle(x, e.Bounds.Y, list.Columns[e.ColumnIndex].Width, e.Bounds.Height);
        }

        private void DrawCell(object sender, DrawListViewSubItemEventArgs e)
        {
            var list = (ListView)sender;
            bool selected = e.Item.Selected;
            bool mirrored = ListMirrored(list);
            Rectangle bounds = mirrored ? CellBounds(list, e) : e.Bounds;
            // Rows on the card's surface with a full hairline between them, as the panel's setting
            // rows have; the chosen row is pressed into the inset colour. High Contrast keeps
            // Highlight for it.
            // v0.6.23: the row under the pointer has a flat tint, half way to the chosen row's colour: no lift, still flat.
            var soft = list as SoftList;
            double hot = soft == null || selected || Palette.Contrast ? 0.0 : soft.Glow.Amount(e.ItemIndex);
            Color back = selected ? (Palette.Contrast ? Palette.AccentSoft : Palette.Inset) : hot > 0.0 ? Soft.Mix(Card, Palette.Inset, hot * 0.5) : Card;
            // Brushes from Soft.Fill, which keeps one per colour: a list of twenty rows across six columns
            // allocated two hundred and forty brushes every time it repainted, and it repaints on every
            // scroll, selection and refresh.
            e.Graphics.FillRectangle(Soft.Fill(back), bounds);
            // The hairline across the cell's own bounds, wherever its column stands, so that the cells' lines are the row's
            // whole width. Not across what Windows hands the cell: for the first column that is a rectangle at the row's
            // left edge, which mirrored is the wrong end - the line stopped before the first column in Arabic and Hebrew
            // (v0.6.20 final, the live re-check's finding 3).
            e.Graphics.FillRectangle(Soft.Fill(Line), bounds.Left, bounds.Bottom - Soft.Hairline, bounds.Width, Soft.Hairline);
            var row = e.Item.Tag as Dictionary<string, object>;
            var cell = new Rectangle(bounds.X + (mirrored ? Px(4) : Px(10)), bounds.Y, Math.Max(0, bounds.Width - Px(14)), bounds.Height);
            string text = e.SubItem == null ? "" : e.SubItem.Text;
            // v0.6.12: a version Install another version... refused keeps its row, and its words go quiet (PickRefusedRow).
            Color ink = Palette.Contrast && selected ? SystemColors.HighlightText : PickRefusedRow(row) ? Secondary : Ink;
            // The quieter columns and the focus mark too: in High Contrast a selected row is
            // Highlight, and anything mixed away from HighlightText fell to about 2.4:1 on it.
            Color quiet = Palette.Contrast && selected ? ink : Soft.Mix(ink, Secondary, 0.4);
            if (e.ColumnIndex == 1 && row != null)
                Soft.Chip(e.Graphics, cell, text, list.Font, Palette.Contrast && selected ? ink : ToneFor(row), back, mirrored);
            else if (list == pendingList && e.ColumnIndex == ResumeColumn && row != null && !EditionRow(row))
                DrawResumeBox(e.Graphics, cell, row, back);
            else
                TextRenderer.DrawText(e.Graphics, text, list.Font, cell, e.ColumnIndex == 0 ? ink : quiet,
                                      Mirror.Words(mirrored, TextFormatFlags.VerticalCenter | TextFormatFlags.Left |
                                                             TextFormatFlags.SingleLine | TextFormatFlags.EndEllipsis));
            // The focus mark at the row's start: its left end, or its right end where the first column stands mirrored.
            int mark = mirrored ? bounds.Right - Px(2) : e.Item.Bounds.Left + Px(2);
            if (e.ColumnIndex == 0 && selected && list.Focused)
                using (var pen = new Pen(Palette.Contrast ? ink : Palette.Focus, Soft.PxF(2)))
                    e.Graphics.DrawLine(pen, mark, e.Item.Bounds.Top + Px(6), mark, e.Item.Bounds.Bottom - Px(6));
        }

        /// The Auto-resume box, drawn as the switch every other on-or-off setting in the window is,
        /// on the row's own ground: where its record says, or part-way there while it glides
        /// (FollowResumeSwitches).
        private void DrawResumeBox(Graphics g, Rectangle cell, Dictionary<string, object> row, Color ground)
        {
            int width = Px(Brand.SwitchWidth), height = Px(Brand.SwitchHeight);
            var track = new Rectangle(cell.X + Px(2), cell.Y + (cell.Height - height) / 2, width, height);
            // v0.6.20: at the cell's right, its knob travelling left, in a mirrored window (Mirror).
            bool mirrored = ListMirrored(pendingList);
            if (mirrored) track.X = cell.Right - Px(2) - width;
            double on = ThreadOn(row) ? 1.0 : 0.0;
            Transition glide;
            string id = Str(row, "interruption_id");
            if (id != null && resumeGlides.TryGetValue(id, out glide) && glide.Running) on = glide.Value;
            // v0.6.23 (the second round's F7): up under the pointer, its knob wider while it is held, and halfway into the row
            // while the change it sent is awaited, as every other switch and the popup's (ListSwitchFeel). At rest, as it was.
            double hover = resumeFeel == null ? 0.0 : resumeFeel.Hover(id), press = resumeFeel == null ? 0.0 : resumeFeel.Press(id);
            double live = resumeFeel == null ? 1.0 : resumeFeel.Live(id);
            if (hover > 0.0 || press > 0.0 || live < 1.0) Soft.SwitchLive(g, track, on, live, hover, press, ground, mirrored);
            else if (mirrored) Soft.SwitchSide(g, track, on, true, ground, true);
            else Soft.SwitchAt(g, track, on, true, ground);
        }

        // Pending's Auto-resume switches (v0.6.5): each row's as it was last drawn, by its record's id, and the glide of
        // each that has moved.
        private readonly Dictionary<string, bool> resumeShown = new Dictionary<string, bool>();
        private readonly Dictionary<string, Transition> resumeGlides = new Dictionary<string, Transition>();
        // And how each answers the pointer and its call (v0.6.23, ListSwitchFeel; made with the list, PendingSteps).
        private ListSwitchFeel resumeFeel;

        /// Every Auto-resume switch in Pending, after its rows were written (v0.6.5). The switch never moves when it is
        /// pressed: the press sends the change, and the list is read again once the control layer has answered
        /// (ToggleAutoResume, Send). A switch already on screen that its record now says is the other way then glides
        /// there - brand's one transition on its one curve, the knob sliding and the track cross-fading, as the popup's
        /// and the panel's switch for the same conversation do - repainting only its own cell each frame (ResumeCell),
        /// with no layout and no timer once it has arrived. A change refused leaves the record as it was, and nothing
        /// moves. A row that appears is drawn as it is; with motion reduced, or Pending not on screen, the switch is
        /// where its record says at once.
        private void FollowResumeSwitches()
        {
            bool animate = Motion.Allowed(pendingList);
            var present = new HashSet<string>();
            foreach (ListViewItem item in pendingList.Items)
            {
                var row = item.Tag as Dictionary<string, object>;
                string id = Str(row, "interruption_id");
                if (id == null || !present.Add(id)) continue;
                bool on = ThreadOn(row), was;
                bool known = resumeShown.TryGetValue(id, out was);
                resumeShown[id] = on;
                Transition glide;
                resumeGlides.TryGetValue(id, out glide);
                if (!known || (was == on && (glide == null || glide.Target == (on ? 1.0 : 0.0)))) continue;
                if (glide == null)
                {
                    if (!animate) continue;
                    glide = new Transition(pendingList, was ? 1.0 : 0.0);
                    string key = id;
                    glide.Where = delegate { return ResumeCell(key); };
                    resumeGlides[id] = glide;
                }
                glide.To(on ? 1.0 : 0.0, animate);
            }
            foreach (string id in new List<string>(resumeShown.Keys))
            {
                if (present.Contains(id)) continue;
                resumeShown.Remove(id);
                if (resumeFeel != null) resumeFeel.Forget(id);
                Transition glide;
                if (resumeGlides.TryGetValue(id, out glide))
                {
                    glide.Dispose();
                    resumeGlides.Remove(id);
                }
            }
        }

        /// Where the Auto-resume switch of the row for `id` is in Pending's list now, or nothing when that row is not
        /// there: the cell a glide repaints, found again each frame, so a list that scrolls meanwhile is followed.
        private Rectangle ResumeCell(string id)
        {
            if (pendingList == null || pendingList.IsDisposed) return Rectangle.Empty;
            foreach (ListViewItem item in pendingList.Items)
                if (Str(item.Tag as Dictionary<string, object>, "interruption_id") == id && item.SubItems.Count > ResumeColumn)
                    return item.SubItems[ResumeColumn].Bounds;
            return Rectangle.Empty;
        }

        /// The id of the record whose Auto-resume switch is at `point` in Pending's list, or null where none is.
        private string ResumeAt(ListView list, Point point)
        {
            ListViewHitTestInfo hit = list.HitTest(point);
            if (hit.Item == null || hit.SubItem == null || hit.Item.SubItems.IndexOf(hit.SubItem) != ResumeColumn) return null;
            var row = hit.Item.Tag as Dictionary<string, object>;
            return row == null || EditionRow(row) ? null : Str(row, "interruption_id");
        }

        /// The colour a record's state word is drawn in. Always beside the word itself.
        internal static Color ToneFor(Dictionary<string, object> row)
        {
            if (HasOverlay(row, "paused") || HasOverlay(row, "thread_disabled")) return Palette.Paused;
            // Comparisons rather than a switch, for the reason in Controls.DotColour: a string
            // switch this long made the in-box compiler emit a randomly named class.
            string code = Str(row, "code") ?? "";
            if (code == "recovered" || code == "delivered_legacy") return Palette.Success;
            if (code == "waiting_reset" || code == "waiting_usage" || code == "waiting_thread" || code == "scheduled")
                return Palette.Waiting;
            if (code == "submission_claimed" || code == "submitted" || code == "turn_running" ||
                code == "turn_finishing")
                return Palette.Accent;
            if (code == "failed_retryable" || code == "no_progress" || code == "exhausted" ||
                code == "handed_over" || code == "outcome_unverified" || code == "submission_unknown" ||
                code == "withdrawing")
                return Palette.Warning;
            if (code == "failed_terminal" || code == "recovery_failed") return Palette.Danger;
            // v0.6.12: Install another version...'s Kind chips (DashboardVersions.cs).
            if (code == PickRelease) return Palette.Success;
            if (code == PickPrerelease) return Palette.Warning;
            if (code == PickInstalled) return Palette.Accent;
            if (code == PickUnavailable) return Palette.Paused;
            return Palette.Paused;
        }

        private static KeyValuePair<string, int> Col(string name, int width)
        {
            return new KeyValuePair<string, int>(name, width);
        }

    }
}
