// Codex Auto Resume - standalone Windows settings window.
//
// This exists so the product stays configurable exactly when the thing it recovers is
// not: with Codex closed, the plugin unloaded, the MCP server unavailable or the
// watcher stopped. It talks only to our own local control bridge.
//
// It deliberately owns no configuration of its own. Every read and write goes through
// the same validated Python control layer the command line, the Codex skill and the
// MCP server use, so a value set here is identical to a value set anywhere else. The
// window renders itself from the schema that layer publishes, which is why adding a
// setting there makes it appear here without touching this file.
//
// Layout notes, each of which came from looking at the result rather than the code:
//   * Sizes come from AutoSize containers, never fixed pixels. Above 100% scaling a
//     hardcoded row is shorter than its own text and clips the descenders.
//   * Groups sit in a TableLayoutPanel, not a FlowLayoutPanel: flow hands a child its
//     preferred width, so an AutoSize group collapses to the width of its content.
//   * The Settings page is a list of sections beside one section's cards. Everything on
//     one scrolling page stopped fitting a laptop screen once languages and the
//     Continuation message joined it, and a setting is found faster under the name of
//     what it is for.
//   * Status leads. What the watcher is doing is the reason the window gets opened, so
//     it sits at the top in the largest type here, and the settings follow it.
//   * Every status fact is its own label in its own cell, never one concatenated string.
//     A single label wraps or truncates as the window narrows, and what disappears first
//     is the version - the part people are asked for when reporting a problem.
//   * Colours come from gui/Brand.cs, which is generated from the palette in
//     src/codex_auto_resume/brand.py, through Palette, which holds the theme the window opened
//     in. Do not write a literal colour in this file, nor one of Brand's light fields.
//   * A window speaks one language and draws one theme, both decided as it opens. When either
//     changes - saved here, or anywhere else, or Windows' own app mode under "system" - the
//     window reopens itself where it was (see Reopen), never while somebody has edits unsaved.
//
// Built with the in-box C# compiler against .NET Framework 4.8, which ships on every
// supported Windows, so the release carries no extra runtime for the interface.
//
// The window is one `partial class SettingsForm`, written across several files since
// v0.6.10-alpha. This one is the process and the window as a window: `Program.Main`, the
// `Bridge` it calls the control layer through, and the form's scale, columns, section list,
// header and footer. Beside it: gui/SettingsPage.cs is the Settings page itself - its cards,
// its rows, its editors and Save - gui/WindowJson.cs the JSON reader and the words cache,
// gui/WindowReopen.cs the reopening, and gui/WindowAudit.cs the layout audit the tests run.
// The Dashboard's half is gui/Dashboard.cs and the five files beside it, and
// `gui/window.sources` is the list of them all.

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;
using System.Windows.Forms.Automation;

namespace CodexAutoResume
{
    /// A panel that paints into a back buffer, so a repaint never shows it erased.
    ///
    /// The status dot is drawn in a Paint handler on an ordinary Panel, which Windows
    /// erases to the background colour first and paints second. Anything that looks in
    /// between - a screenshot, or the eye during a status refresh - sees no dot at all:
    /// the Korean window screenshot published with v0.5.7 has a white square where the
    /// dot belongs.
    internal sealed class BufferedPanel : Panel
    {
        internal BufferedPanel()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                     ControlStyles.UserPaint | ControlStyles.ResizeRedraw, true);
        }
    }

    /// The same, for a table that draws its own card border and accent rail.
    ///
    /// The third instance of one bug: after the dot and the header rule, a capture of the
    /// Korean window came out with the Windows card's border and rail missing. Every
    /// control in this file that has a Paint handler is now one of these two classes,
    /// and tests/test_gui_layout.py holds it to that.
    internal sealed class BufferedTable : TableLayoutPanel
    {
        internal BufferedTable()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                     ControlStyles.UserPaint | ControlStyles.ResizeRedraw, true);
        }
    }

    /// What the window was asked to open with, from its command line (SettingsForm.ParseArguments).
    /// Every value has been checked against what it may be; what was not given, or not valid, is
    /// null, false or zero, and the window opens as it always did.
    internal sealed class OpenRequest
    {
        /// A page of the window: `--page=<name>`, or `--settings`, the older spelling.
        internal string Page;
        /// A Settings section: `--section=<name>`.
        internal string Section;
        /// A Theme preference - "system", "light" or "dark" - that the window opens in instead of the
        /// stored one: `--theme=<name>`, which a window that reopens itself passes on (see Reopen).
        internal string Theme;
        /// A Design - "soft", "classic" or "plain" - that the window opens in instead of the stored
        /// one: `--design=<name>` (v0.6.10), passed on by a reopen as the theme is.
        internal string Design;
        /// Where the window goes, in device pixels: `--bounds=<x>,<y>,<width>,<height>`.
        internal bool HasBounds;
        internal Rectangle Bounds;
        /// `--maximized`.
        internal bool Maximized;
        /// How many reopens in a row led to this window, 1 to 9: `--reopened=<n>`. 0 when a person
        /// opened it.
        internal int Generation;
        /// v0.6.23 (the final's live acceptance): the window this one replaces opened in English because its words came
        /// late (StringsWaitMilliseconds), and reopened for them: `--late-words` (SettingsForm.ReopenedForLateWords).
        /// Words that come late to this one too are not reopened for again (TakeLateWords).
        internal bool ForLateWords;
        /// How far the bounds reach past the frame one sees - the resize border Windows keeps invisible -
        /// as the window this one replaces measured it: `--frame=<left>,<top>,<right>,<bottom>`. Empty
        /// when not given.
        internal Padding Frame;
        /// Where the keyboard was in the window this one replaces (SettingsForm.FocusName): `--focus=<name>`.
        internal string Focus;
        /// v0.6.23: a row of Pending and one of its own dialogs to open for it, from the popup's row menu:
        /// `--dialog=<dialog>:<interruption id>:<thread id>` (SettingsForm.RowDialogRequest), which opens Pending.
        internal string RowDialog;
    }

    /// A drop-down entry whose stored value and displayed label differ.
    internal sealed class Choice
    {
        internal readonly string Value;
        private readonly string label;

        internal Choice(string value, string label) { Value = value; this.label = label; }

        public override string ToString() { return label; }
    }

    internal sealed class Bridge
    {
        /// The longest one call may take (v0.6.18): twice the long-lived pipe's own reply limit, for the core's start on
        /// top of the answer. Past it the child is ended, with what it started (ChildTree.End), and the call throws, as a
        /// pipe that does not answer does: a stuck bridge - a locked state file, an antivirus scan holding the core -
        /// could otherwise hold the call, and with it every later one queued behind the long-lived bridge's lock, for
        /// good. Not readonly, so the tests can make it short.
        internal static int CallMilliseconds = 60000;
        /// The same for CallOnce's commands: the compatibility refresh waits up to 150 s on the network
        /// (compat.files.REFRESH_TIMEOUT_SECONDS), and the core's start comes on top.
        internal static int LongCallMilliseconds = 180000;

        /// v0.6.27: the installation's core (CoreExe), which answers `bridge <command> [-]` as controlcli did.
        private readonly string core;
        // Every one-shot child on its way, so the window's close can end them (Stop): the long-lived bridge's own
        // Stop could only end its own process.
        private readonly List<Process> running = new List<Process>();
        private volatile bool stopped;

        internal Bridge(string root)
        {
            core = CoreExe.Path(root);
        }

        /// The program both bridges start (PersistentBridge starts its `bridge serve` from here too).
        internal string Core { get { return core; } }

        internal bool Available { get { return File.Exists(core); } }

        internal Dictionary<string, object> Call(string command, string argument)
        {
            return Call(command, argument, CallMilliseconds);
        }

        /// One call, ended after `milliseconds` (see CallMilliseconds).
        ///
        /// Both of the child's streams are read at once, from the moment it starts: stdout read to its end before
        /// stderr was read at all, so a child that wrote more than a pipe holds to stderr first - a traceback from
        /// before main's own try - waited for the window to read it while the window waited for its stdout, for good.
        /// The argument goes in on its own task too, so a child that never reads its stdin cannot hold the write.
        /// The time limit holds the child's end and its output's end together: a process it started that kept its
        /// stdout open (a probe of Codex) holds the output's end past its own exit.
        internal Dictionary<string, object> Call(string command, string argument, int milliseconds)
        {
            if (stopped) throw new ObjectDisposedException("the window is closing");
            var info = new ProcessStartInfo();
            info.FileName = core;
            // `bridge <command>`: the core's bridge role, controlcli's words (v0.6.27). No path rides on the command
            // line any more: the core finds its installation from where it is.
            var arguments = new StringBuilder("bridge");
            arguments.Append(' ').Append(command);
            // The argument goes in on stdin, never on the command line: "-" tells the bridge to
            // read it there. This call answers whenever the long-lived process has failed, and
            // then carries every Custom message on the page - on each pause in typing, for the
            // Preview. A command line can be read by any process this user runs and is what
            // process auditing keeps, and it stops at 32767 characters, which a Save could pass.
            bool hasArgument = !string.IsNullOrEmpty(argument);
            if (hasArgument) arguments.Append(" -");
            info.Arguments = arguments.ToString();
            info.UseShellExecute = false;
            info.RedirectStandardInput = true;
            info.RedirectStandardOutput = true;
            info.RedirectStandardError = true;
            info.CreateNoWindow = true;
            info.StandardOutputEncoding = Encoding.UTF8;

            var clock = Stopwatch.StartNew();
            using (Process process = Process.Start(info))
            {
                lock (running) running.Add(process);
                try
                {
                    System.Threading.Tasks.Task<string> output = process.StandardOutput.ReadToEndAsync();
                    System.Threading.Tasks.Task<string> errors = process.StandardError.ReadToEndAsync();
                    // UTF-8 written by hand, as the long-lived bridge writes its requests: .NET
                    // Framework encodes a redirected stdin with the console code page. Closed with or
                    // without an argument, so the child never waits on a stdin nobody writes to.
                    byte[] bytes = hasArgument ? new UTF8Encoding(false).GetBytes(argument) : new byte[0];
                    Stream input = process.StandardInput.BaseStream;
                    System.Threading.Tasks.Task written = System.Threading.Tasks.Task.Factory.StartNew(delegate
                    {
                        try
                        {
                            if (bytes.Length > 0) input.Write(bytes, 0, bytes.Length);
                            input.Close();
                        }
                        catch (Exception) { /* the child ended or was ended; its answer, or none, says what happened */ }
                    });
                    // Ended at once when the window closed while it started (Stop looked before it was listed).
                    bool done = !stopped && process.WaitForExit(Math.Max(0, milliseconds));
                    if (done) done = output.Wait(Left(clock, milliseconds));
                    if (!done || stopped)
                    {
                        ChildTree.End(process);
                        // The reads end with the pipes; nobody waits for them, and what they throw is looked at, so
                        // nothing is left unobserved.
                        Observe(output);
                        Observe(errors);
                        if (stopped) throw new ObjectDisposedException("the window is closing");
                        throw new TimeoutException("the local service did not answer in time");
                    }
                    Observe(errors);
                    string said = output.Result;
                    if (string.IsNullOrEmpty(said))
                        throw new InvalidOperationException("No response from the local service.");
                    return (Dictionary<string, object>)Json.Parse(said);
                }
                finally
                {
                    lock (running) running.Remove(process);
                }
            }
        }

        private static int Left(Stopwatch clock, int milliseconds)
        {
            return (int)Math.Max(0, milliseconds - clock.ElapsedMilliseconds);
        }

        private static void Observe(System.Threading.Tasks.Task task)
        {
            task.ContinueWith(delegate(System.Threading.Tasks.Task ended) { var ignored = ended.Exception; },
                              System.Threading.Tasks.TaskContinuationOptions.OnlyOnFaulted);
        }

        /// As the window closes: every one-shot child on its way is ended, with what it started (ChildTree.End), and
        /// no new one starts. On the window's own thread, so it waits for nothing.
        internal void Stop()
        {
            stopped = true;
            Process[] children;
            lock (running) children = running.ToArray();
            foreach (Process child in children) ChildTree.End(child);
        }

        /// How many one-shot children are on their way now (for the tests).
        internal int Running
        {
            get { lock (running) return running.Count; }
        }

        // Windows command-line quoting, by the documented CommandLineToArgvW rules: a
        // run of backslashes is only special immediately before a quote, where 2n means
        // n literal backslashes and a delimiter, and 2n+1 means n and a literal quote.
        // Doubling every backslash instead - the obvious-looking version - turns a path
        // into one with doubled separators. Windows tolerates that, so it works right up
        // until something compares two paths for equality.
        internal static string Quote(string value)
        {
            var builder = new StringBuilder("\"");
            int slashes = 0;
            foreach (char c in value ?? string.Empty)
            {
                if (c == '\\') { slashes++; continue; }
                if (c == '\"') builder.Append('\\', slashes * 2 + 1).Append('\"');
                else builder.Append('\\', slashes).Append(c);
                slashes = 0;
            }
            return builder.Append('\\', slashes * 2).Append('\"').ToString();
        }
    }

    internal sealed partial class SettingsForm : Form
    {
        // The palette lives in src/codex_auto_resume/brand.py and is generated into
        // gui/Brand.cs, so the window, the Codex panel, the icon and the plugin card
        // cannot disagree about what colour this product is. The window reads it through
        // Palette, which holds the one theme it opened in: light, dark, or High Contrast,
        // where the person has chosen their colours for a reason and every colour is a
        // system one.
        private static bool Contrast { get { return Palette.Contrast; } }
        private static Color Ink { get { return Palette.Ink; } }
        private static Color Muted { get { return Palette.Muted; } }
        // Secondary text that is still live. In High Contrast mode GrayText means
        // "disabled", so there it is the ordinary text colour, and weight and position
        // carry the hierarchy instead. Muted stays for what really is disabled.
        private static Color Secondary { get { return Palette.Secondary; } }
        private static Color Line { get { return Palette.Line; } }
        // A card's own ground: what everything opaque inside a card is filled with.
        private static Color Card { get { return Palette.Card; } }
        private static Color Canvas { get { return Palette.Canvas; } }
        private static Color Accent { get { return Palette.Accent; } }
        private static Color OnAccent { get { return Palette.OnAccent; } }
        private static Color Active { get { return Palette.Active; } }

        private readonly PersistentBridge bridge;
        private readonly Dictionary<string, Control> editors = new Dictionary<string, Control>();

        private readonly TableLayoutPanel columns = new SoftStack();
        // The Settings page's sections, in the order the section list shows them. Each is a
        // single column of cards; one is on screen at a time.
        private static readonly string[] SectionOrder = { "general", "recovery", "continuation", "appearance", "advanced" };
        private readonly Dictionary<string, TableLayoutPanel> sections = new Dictionary<string, TableLayoutPanel>();
        private readonly Dictionary<string, NavButton> sectionButtons = new Dictionary<string, NavButton>();
        private readonly SoftPage sectionScroll = new SoftPage();
        private string currentSection = "general";
        // The schema and settings as read, until the Settings editors are built from them
        // (BuildEditorsLater); null once they have been.
        private List<object> pendingSchema;
        private Dictionary<string, object> pendingSettings;
        private bool shown, buildQueued;
        // Set by LayoutAudit: the window is measured, so nothing is read and nothing is scheduled.
        private bool auditing;
        // Editors whose value is not a check box, a number or a drop-down, as the JSON each
        // contributes to a save.
        private readonly Dictionary<string, Func<string>> jsonValues = new Dictionary<string, Func<string>>();
        // The Continuation message editors, kept so the Preview and the visibility rules can
        // read what is on screen without asking anything.
        private ChoiceGroup styleGroup;
        private SoftCombo modeCombo, interfaceCombo, continuationCombo, previewReason, perReasonCombo;
        private TableLayoutPanel customCard, perReasonPanel;
        private SoftTextArea globalText, perReasonText;
        private Label globalCount, perReasonCount, customRefusal, previewSource;
        private SoftQuote previewText;
        private readonly Dictionary<string, string> perReasonValues = new Dictionary<string, string>();
        private readonly List<string> reasonOrder = new List<string>();
        private string perReasonShown;
        private Timer previewTimer;
        private int previewToken;
        private string loadedInterfaceLanguage = "system";
        // What the window was opened with (see OpenRequest), and the installation it belongs to.
        private readonly OpenRequest request;
        private readonly string installRoot;
        // v0.6.24 final: the key the window's words were looked up under (StringsCache.Key), or null - the advanced
        // edition keeps its page's words under the same key.
        private string openedKey;
        // Reopening (see Reopen). What this window shows - the Interface language its words were
        // resolved for, the theme it draws and, since v0.6.10, the design it draws (Design.Drawn) - against
        // what is stored: the Interface language, Theme preference and Design as last read or saved.
        private string openedLanguage, openedTheme, openedDesign, storedLanguage, storedTheme, storedDesign;
        private string wordsLanguage;
        private bool settingsRead, readingSettings, reopening, recheck;
        // v0.6.18: the screen the window opens on (OpeningScreen), taken once.
        private Screen opening;
        // v0.6.18: on a monitor of another scale since WM_DPICHANGED (CheckScale), in the middle of a move or resize, held
        // for later, and the scale a reopen for it opens at (0: none).
        private bool scaleMoved, sizing, recheckScale;
        private double reopenScale;
        // v0.6.18 B3: the window's size while it was still at the scale it is drawn at (ReopenBounds); empty until a move.
        private Size drawnSize;
        // v0.6.18 B3: the bounds a reopened window was placed at (PlaceOnScreen), held to as it is shown (KeepPlacedBounds).
        private Rectangle placedBounds;
        // v0.6.18: the words were not had in time and the window opened in English (StringsWaitMilliseconds); the reply,
        // once it comes, is lateReply until the window has taken it (TakeLateWords).
        private bool lateWords;
        private volatile Dictionary<string, object> lateReply;
        // v0.6.23: the window opened in English because its words were not had in time, for its whole life - it never takes
        // the late words in place, it reopens in them. The advanced edition's own words are asked in English here too
        // (AdvancedPage.LocaleArgument), so the window is in one language until it does.
        private bool openedLate;
        private long settingsStamp;
        // The language, theme and design a reopen on its way is for; and the three a new window was last started
        // for that never showed, which this window does not try again (CheckReopen, FinishReopen).
        private string reopenLanguage, reopenTheme, reopenDesign, declinedLanguage, declinedTheme, declinedDesign;
        // What a read or a save leaves undone while the window reopens, done after all if it stays.
        private MethodInvoker heldForReopen;
        // Where the keyboard was as a save that may reopen the window began (Save); and where a window that
        // replaces another still has to put it once the page is built (FocusPending).
        private string reopenFocus, pendingFocus;
        // The resize border Windows keeps invisible around this window, as last measured (InvisibleFrame).
        private Padding invisibleFrame;
        // Whether the reopen note is showing, which the save card's height follows (BuildFooter).
        private bool reopenNoteShown;
        private EventHandler fitFooter;
        // The editors' values as the page was built or last saved, which is what "unsaved edits" is
        // measured from, and the sign-in switch as the status last said.
        private Dictionary<string, string> baseline;
        private bool startupBaseline;
        // Whether a status read has said what Windows holds for the sign-in switch since the page was built
        // (ApplyStatus). Until it has, the switch shows nothing it knows and Save writes no entry (v0.6.16-beta.3).
        private bool startupKnown;
        private NoteLabel reopenNote;
        // The same limit the settings layer enforces. Shown, never enforced here: text past it
        // is refused when saved rather than cut off while it is typed.
        private const int MaxCustomLength = 2000;
        // The header and the footer are cards on the canvas, as the panel's hero and its save bar
        // are: each strip is a ground (see Ground) and its card is lifted on it. Grounds are
        // double-buffered, because the header is invalidated on every status refresh, and an
        // unbuffered strip was erased and repainted a moment later - a capture taken in that
        // moment, one in four measured, showed the header with half of it missing.
        private readonly Panel header = new SoftPage();
        private readonly Panel footer = new SoftPage();
        private readonly SoftCard hero = new SoftCard();
        private readonly SoftCard savebar = new SoftCard();
        private readonly Label headline = new Label();
        private readonly AsideLabel detail = new AsideLabel();
        private readonly VersionLabel versionText = new VersionLabel();
        // v0.6.24-beta.2: the version's pill at the end of the page tabs (BuildVersionPill), and the strip of ground it
        // stands on, docked at the tabs' outer end.
        private VersionPill versionPill;
        private SoftPage pillSlot;
        // v0.6.24: its hint on a special day, that it can be pressed (FollowPillHint).
        private PillHint pillHint;
        private readonly HaloDot stateDot = new HaloDot();
        private readonly SoftDayScene dayScene = new SoftDayScene();
        private string dayLook;
        // v0.6.24-beta.2 (the owner, 2026-11-16): the run of presses on the version that plays a special egg at the sixth, which
        // one (SpecialEggs), what each press played (for the tests), the confetti on the screen and the count read last asked.
        private readonly System.Diagnostics.Stopwatch versionClock = System.Diagnostics.Stopwatch.StartNew();
        private readonly PressRun versionPresses = new PressRun();
        internal readonly EggPick SpecialEggs = new EggPick();
        internal readonly List<string> EggsPlayed = new List<string>();
        private ConfettiLayer confetti;
        private int countAsked;

        /// How the count egg reads how many recoveries the app has made in all - the bridge's statistics over all time, the
        /// figure Statistics shows for "All time" - handing it, or -1 where it cannot be read, to `then` on the window's thread.
        /// The tests give their own.
        internal Action<Action<int>> ReadRecoveredAllTime;

        /// The presses' clock, in milliseconds (the tests give their own; the window's stopwatch otherwise).
        internal Func<double> PressNow;

        // Until when, on the presses' clock, the special egg that last played is still on the screen (VersionPressed).
        private double specialUntil = double.NegativeInfinity;

        /// Until when the special egg that last played is on the screen, on the presses' clock (for the tests).
        internal double SpecialUntil { get { return specialUntil; } }

        // The sentence comes in as the sweep ends, and goes 4 s after it has come in.
        internal const int AsideAfterMs = 850, AsideMs = 4150;

        // v0.6.24-beta.2 (the owner, 2026-11-16): the egg's light, without its sentence, as the window opens and as the light
        // turns on. The light the watcher's state last gave (Hero, before an action's working light: BusyLight) - null until
        // the first read; whether the window's opening sweep has been decided; and whether it waits for the window to show.
        private string lightBefore;
        private bool lightOpened, sweepOnShown;

        /// What the light's sweep was asked for, in order - "open" and "on" - for the tests; whether each played is the
        /// sweep's own (Motion.Allowed).
        internal readonly List<string> LightSweepsAsked = new List<string>();

        /// Whether the light is off: the watcher not running or not known to (idle), or recovery paused.
        internal static bool LightOff(string light)
        {
            return light == null || light == "idle" || light == "paused";
        }

        /// Whether the light says the watcher is watching: its running colours.
        internal static bool LightWatching(string light)
        {
            return light == "monitoring" || light == "waiting" || light == "checking" || light == "recovering";
        }

        /// Whether the light turns on from `before` to `after`: from off to watching; never between two watching states,
        /// from the amber of a watcher that needs a person, or as it turns off.
        internal static bool LightTurnsOn(string before, string after)
        {
            return before != null && LightOff(before) && LightWatching(after);
        }

        /// No sweep in a picture: a render job, a capture or the layout audit draws the light still, the same every time.
        private bool LightSweepsShown
        {
            get { return !auditing && !RenderPinned && Soft.StillLightMs < 0 && Soft.StillReady == null && Soft.StillNow < 0; }
        }

        /// The light the watcher's state gives, as a read writes it (Hero): the first in a window a person opened - not one that
        /// reopened itself for a language, a theme or a monitor's scale, the same open going on - sweeps once; after that, a
        /// light that turns on does.
        private void LightRead(string light)
        {
            string before = lightBefore;
            lightBefore = light;
            if (!lightOpened)
            {
                lightOpened = true;
                if (request.Generation == 0) SweepLight("open");
                return;
            }
            if (LightTurnsOn(before, light)) SweepLight("on");
        }

        /// The egg's sweep, and the line under the headline coming in as it ends (AsideLabel.Arrive), at the egg's pace
        /// (AsideAfterMs) - never its sentence. Once at a time: asked while one is on its way, nothing. A window not yet on
        /// screen sweeps as it is shown.
        private void SweepLight(string why)
        {
            if (!LightSweepsShown || stateDot.Sweeping) return;
            LightSweepsAsked.Add(why);
            if (!shown)
            {
                sweepOnShown = true;
                return;
            }
            stateDot.Sweep();
            if (stateDot.Sweeping) detail.Arrive(AsideAfterMs);
        }

        /// The easter egg: the light's sweep and the sentence coming in as it ends. v0.6.24-beta.2 (the owner, 2026-11-16,
        /// "이스터에그 버전 알약 한번만 눌러도 뜨게 하자" - let one press on the version pill show the easter egg): one press, where
        /// seven within 1.8 s each were asked before (v0.6.23); a new run's first press starts it again from its start - the
        /// sweep from the top (HaloDot.Sweep), the sentence again as that ends (AsideLabel.Aside) - and nothing stacks.
        ///
        /// And the sixth press in a row, each within 1.8 s of the last (PressRun; the owner, the same day, "여러번 누를때의
        /// 이스터에그도 별도로 만들자", "6번"), plays one of three special eggs instead, at random and never the same twice in a
        /// row (EggPick) - never in a picture or the layout audit (LightSweepsShown).
        ///
        /// v0.6.24-beta.2 (the owner, 2026-11-17, "6번 눌러야 뜨는 이스터에그를 보기 위해 여러번 클릭할 때, 1번 누르면 뜨는
        /// 이스터에그 시작이 계속 반복해 / 둘이 중첩되어있네" - pressing towards the sixth restarted the one-press egg at every
        /// press, and the two overlapped): within a run only its first press plays the one-press egg, at once; the next four
        /// play nothing new; the sixth clears it - no sweep, no sentence, no fade - and plays the special one alone. A press
        /// after 1.8 s of quiet begins a new run.
        ///
        /// And ("여섯번보다 더 계속 누를 경우는? 정확히 6번만 누르진 않을거잖아" - nobody presses exactly six times): while a special
        /// egg plays, a press is not counted and starts nothing (SpecialUntil); once it has ended the next press begins a run,
        /// so pressing on shows one, then a special one, then one again - never two at once.
        private void VersionPressed()
        {
            double now = PressNow != null ? PressNow() : versionClock.Elapsed.TotalMilliseconds;
            if (now < specialUntil) return;
            countAsked++;
            bool sixth = versionPresses.Press(now);
            // v0.6.24 (the owner, 2026-11-17/18): a special day's own egg and sentences, the date the window's (EggDay).
            string day = EggDay();
            if (sixth && LightSweepsShown)
            {
                stateDot.StopSweep();
                detail.Unsay();
                if (day != null) PlayDayEgg(day);
                else PlaySpecialEgg(SpecialEggs.Pick());
                // Until its sentence has come, been said and gone: the sweep's or the colours' time first, where they play.
                bool moving = stateDot.Sweeping || stateDot.ColoursRunning || (confetti != null && confetti.Running);
                specialUntil = now + (moving ? AsideAfterMs : 0) + AsideMs + AsideLabel.OutMs;
                return;
            }
            if (!versionPresses.First) return;
            EggsPlayed.Add("one");
            stateDot.Sweep();
            if (day != null)
                detail.Aside(S("status.aside_day_" + day, S("status.aside", "It's okay if it stops. I'll pick it up.")),
                             stateDot.Sweeping ? AsideAfterMs : 0, AsideMs);
            else detail.Aside(S("status.aside", "It's okay if it stops. I'll pick it up."), stateDot.Sweeping ? AsideAfterMs : 0, AsideMs);
        }

        /// v0.6.24: the special day the version's eggs speak of - the window's date (DayArt.Clock), or null for an ordinary day
        /// and for a window that is no person's (DayArt.On off: a picture, a probe without a probe date). In High Contrast too,
        /// unlike the day's look: these are words, and there nothing of the egg moves (PlayDayEgg, PillHint).
        internal string EggDay()
        {
            if (!DayArt.On) return null;
            DateTime now = DayArt.Clock();
            string look, top, bottom;
            return Brand.DayLook(now.Year, now.Month, now.Day, out look, out top, out bottom) ? look : null;
        }

        /// v0.6.24 (the owner, 2026-11-17/18, the Special board): the sixth press on a special day plays that day's own egg in
        /// place of the three ordinary ones - from the pill, in a layer over the window (DayEggPlay) - and says its sentence,
        /// as the confetti egg does. With motion reduced, Windows' animations off or in High Contrast, the sentence alone.
        private void PlayDayEgg(string day)
        {
            EggsPlayed.Add("day:" + day);
            bool moving = DayEggPlay(day);
            detail.Aside(S("status.aside_egg_" + day, S("status.aside", "It's okay if it stops. I'll pick it up.")),
                         moving ? AsideAfterMs : 0, AsideMs);
        }

        /// The day's egg on the screen: the confetti's layer and box (Confetti) round the pill, drawing DayEgg into the window
        /// from the pill's side. Nothing where nothing may move, in High Contrast, or with no pill on the screen.
        private bool DayEggPlay(string day)
        {
            if (versionPill == null || !Soft.OwnVisible(versionPill) || !Motion.Allowed(versionPill) || Palette.Contrast)
                return false;
            Point centre = PointToClient(versionPill.PointToScreen(new Point(versionPill.Width / 2, versionPill.Height / 2)));
            int reach = Px(260);
            Rectangle client = ClientRectangle;
            Rectangle area = Rectangle.FromLTRB(Math.Max(client.Left, centre.X - reach), Math.Max(client.Top, centre.Y - Px(130)),
                                                Math.Min(client.Right, centre.X + reach), client.Bottom);
            if (area.Width <= 0 || area.Height <= 0) return false;
            if (confetti != null) confetti.Dispose();
            var egg = new DayEgg(day, new PointF(centre.X - area.X, centre.Y - area.Y), Soft.PxF(1), Mirror.Of(this) ? 1 : -1);
            confetti = new ConfettiLayer(this, area, egg);
            confetti.Start();
            return true;
        }

        /// v0.6.24 (the owner, 2026-11-18, the Hint board's H2 and H3): the pill's hint on a special day (PillHint) and a hand
        /// over it - none in a picture or the layout audit (LightSweepsShown). Asked by the window's clock every second
        /// (FollowDayScene), as the window shows, and as the pill shows or goes.
        internal void FollowPillHint()
        {
            if (pillHint == null) return;
            string day = LightSweepsShown ? EggDay() : null;
            Cursor hand = day != null ? Cursors.Hand : Cursors.Default;
            if (versionPill.Cursor != hand) versionPill.Cursor = hand;
            if (versionText.Cursor != hand) versionText.Cursor = hand;
            pillHint.Follow(day);
        }

        /// One special egg, each with its sentence. With motion reduced or Windows' animations off, nothing moves and the
        /// sentence comes at once, as the one-press egg's does; in High Contrast the light runs no colours and no confetti
        /// falls, the sentence alone.
        private void PlaySpecialEgg(int which)
        {
            if (which == EggPick.Colours)
            {
                // The light through each of its colours in turn, back to its own (HaloDot.RunColours).
                EggsPlayed.Add("colours");
                stateDot.RunColours();
                detail.Aside(S("status.aside_colours", "Did you see? My light has four colours."), stateDot.ColoursRunning ? AsideAfterMs : 0, AsideMs);
            }
            else if (which == EggPick.Count)
            {
                // The sweep, and what it has picked up in all, read as the sweep plays.
                EggsPlayed.Add("count");
                stateDot.Sweep();
                bool sweeping = stateDot.Sweeping;
                var since = System.Diagnostics.Stopwatch.StartNew();
                int asked = countAsked;
                (ReadRecoveredAllTime ?? ReadRecovered)(delegate(int recovered)
                {
                    if (asked != countAsked || IsDisposed) return;
                    int left = sweeping ? Math.Max(0, AsideAfterMs - (int)since.ElapsedMilliseconds) : 0;
                    detail.Aside(CountAside(recovered), left, AsideMs);
                });
            }
            else
            {
                EggsPlayed.Add("confetti");
                bool falling = Confetti();
                detail.Aside(S("status.aside_confetti", "You found it! Thank you for staying."), falling ? AsideAfterMs : 0, AsideMs);
            }
        }

        /// The count egg's sentence: how many it has picked up in all, none yet, or - where that cannot be read - the
        /// one-press egg's own.
        internal string CountAside(int recovered)
        {
            if (recovered < 0) return S("status.aside", "It's okay if it stops. I'll pick it up.");
            if (recovered == 0) return S("status.aside_count_none", "None picked up yet. If one stops, I'll take it from there.");
            if (recovered == 1) return S("status.aside_count_one", "So far I have picked up 1 conversation for you.");
            return S("status.aside_count_many", "So far I have picked up {n} conversations for you.", "n",
                     recovered.ToString(CultureInfo.CurrentCulture));
        }

        /// The bridge's statistics over all time, off the window's thread - reading numbers is not an action (LoadStatistics) -
        /// through PersistentBridge.Queue, which counts it from the moment it is queued, as the window's other reads are.
        private void ReadRecovered(Action<int> then)
        {
            bridge.Queue(delegate
            {
                int recovered = -1;
                try
                {
                    Dictionary<string, object> reply = bridge.Call("statistics", "{}");
                    if (Ok(reply)) recovered = (int)Number(Map(Map(reply, "result"), "outcomes"), "recovered");
                }
                catch (Exception) { recovered = -1; }
                MethodInvoker tell = delegate { then(recovered); };
                try { if (IsHandleCreated && !IsDisposed) BeginInvoke(tell); }
                catch (Exception) { }
            });
        }

        /// A small burst of confetti from the version's pill, falling within the window for ConfettiBurst.LengthMs, in the
        /// brand's colours (ConfettiLayer: it takes no input and is never outside the client area). A burst on its way gives way
        /// to the new one. Nothing where nothing may move, in High Contrast, or with no pill on the screen.
        private bool Confetti()
        {
            if (versionPill == null || pillSlot == null || !Soft.OwnVisible(pillSlot) || !Motion.Allowed(versionPill) || Palette.Contrast)
                return false;
            Point centre = PointToClient(versionPill.PointToScreen(new Point(versionPill.Width / 2, versionPill.Height / 2)));
            int reach = Px(260);
            Rectangle client = ClientRectangle;
            Rectangle area = Rectangle.FromLTRB(Math.Max(client.Left, centre.X - reach), Math.Max(client.Top, centre.Y - Px(130)),
                                                Math.Min(client.Right, centre.X + reach), client.Bottom);
            if (area.Width <= 0 || area.Height <= 0) return false;
            if (confetti != null) confetti.Dispose();
            var burst = new ConfettiBurst(new Random(), new PointF(centre.X - area.X, centre.Y - area.Y), Soft.PxF(1), ConfettiBurst.Colours());
            confetti = new ConfettiLayer(this, area, burst);
            confetti.Start();
            return true;
        }
        // v0.6.5: the notification-area icon's motion on the taskbar button (TaskbarMark), told the icon's state for what
        // the window read wherever stateDot is told its own (TellTaskbar); null in a window LayoutAudit builds, and
        // without the product's own icon.
        private TaskbarMark taskbar;
        private Button startButton;
        // Whether the last status read said the watcher is not running (ApplyStatus): Start watcher then, not Pause.
        private bool watcherOff;
        // v0.6.12: while Start watcher's own start is in flight (StartWatcher), apart from the actions SetBusy counts.
        private bool starting;

        // The interface vocabulary, in the language the engine resolved. Fetched once,
        // over the same bridge every other read goes through.
        //
        // The window does not decide the language and carries no Korean of its own. It
        // used to carry English of its own, which is why a machine whose Windows is
        // Korean, whose notifications were Korean and whose setup output was Korean still
        // opened an English settings window. `S` falls back to the English literal at each
        // call site, so a bridge that cannot answer degrades to what this file used to be
        // rather than to blank labels.
        private Dictionary<string, object> strings = new Dictionary<string, object>();
        // Each language named in itself, and the language Windows asks for, for the two
        // language drop-downs. Neither is translated.
        private Dictionary<string, object> endonyms = new Dictionary<string, object>();
        private string systemLanguage = "en";

        private string S(string key, string fallback)
        {
            object value;
            if (strings.TryGetValue(key, out value) && value is string && ((string)value).Length > 0)
                return (string)value;
            return fallback;
        }

        private string S(string key, string fallback, string token, object replacement)
        {
            // v0.6.20: the value one run in a sentence written right to left (Mirror.Embed).
            return S(key, fallback).Replace("{" + token + "}", Mirror.Embed(Convert.ToString(replacement,
                                                                                            CultureInfo.InvariantCulture)));
        }

        /// How long a window with no words cached for it waits for them before it opens (v0.6.18), in English, its own
        /// words: on the window's own thread, before there is a window, so past this a stuck interpreter left a process
        /// running with no window and no taskbar button - after every update or change of language, whose words are not
        /// cached yet - and a second click started a second one. The words that come later open the window again in its
        /// language (TakeLateWords). Not readonly, so the tests can make it short.
        internal static int StringsWaitMilliseconds = 5000;

        /// What `openedLanguage` says while the words the window opened in were not had in time: no language a setting
        /// stores, so the first answer that comes - from the strings or the settings - reopens the window in its own
        /// (ReopenDecision), as a language changed anywhere else does.
        internal const string LateLanguage = "(not yet read)";

        /// The words that came after the window had opened in English, on its own thread: kept, as any reply is, for the
        /// next window to open in (StringsCache.Write, on the worker that had them), and the window opened again in
        /// them where it is - as a change of language reopens it, so never under unsaved edits (CheckReopen). English
        /// words are this window's already; a window that was itself reopened FOR late words (`--late-words`,
        /// OpenRequest.ForLateWords) stays as it is, so a bridge that is always slower than the wait cannot reopen it
        /// over and over.
        ///
        /// v0.6.23 (the final's live acceptance): this was `request.Generation != 0` - any reopened window - and the
        /// window the setup program opens again after an update starts from the old window's reopen record, which
        /// carries `--reopened=1`: the first bridge start after an update took 11 s, the window opened in English and
        /// stayed in English for good. Only a reopen for late words is held back now; one for an update, a language,
        /// a theme, a design or a monitor's scale was not caused by late words, and takes them as a window a person
        /// opened does.
        private void TakeLateWords()
        {
            Dictionary<string, object> reply = lateReply;
            if (!lateWords || reply == null || IsDisposed) return;
            lateWords = false;
            lateReply = null;
            if (!Ok(reply) || !(Get(reply, "strings") is Dictionary<string, object>)) return;
            string language = Get(reply, "language") as string;
            if (language == "en")
            {
                openedLanguage = Get(reply, "preference") as string;
                return;
            }
            if (request.ForLateWords) return;
            openedLanguage = LateLanguage;
            if (settingsRead) CheckReopen(false);
        }

        /// The bridge's strings reply, or null when it could not be had.
        private Dictionary<string, object> AskStrings()
        {
            try
            {
                return bridge.Call("strings", null);
            }
            catch (Exception)
            {
                // English, then. A settings window that will not open because it could
                // not fetch its own labels is worse than one in the wrong language.
                return null;
            }
        }

        /// Takes the words, the language names and Windows' language from a strings reply.
        private void AdoptStrings(Dictionary<string, object> reply)
        {
            if (!Ok(reply) || !(Get(reply, "strings") is Dictionary<string, object>)) return;
            strings = (Dictionary<string, object>)reply["strings"];
            // The Interface language these words were resolved for, as the settings stored it.
            openedLanguage = Get(reply, "preference") as string;
            // The language the words are in, whose face the window is set in (Typeface.ForLanguage, v0.6.17).
            wordsLanguage = Get(reply, "language") as string;
            object names, system;
            if (reply.TryGetValue("endonyms", out names) && names is Dictionary<string, object>)
                endonyms = (Dictionary<string, object>)names;
            if (reply.TryGetValue("system_language", out system) && system is string)
                systemLanguage = (string)system;
        }

        [System.Runtime.InteropServices.DllImport("user32.dll")]
        private static extern int GetDpiForSystem();

        private static readonly double SystemScale = MeasureDpiScale();
        private static double dpiScale = SystemScale;
        // v0.6.18: the scale of the monitor the window is drawn for (AdoptDisplayScale) - SystemScale until it is adopted.
        private static double displayScale = SystemScale;

        [System.Runtime.InteropServices.StructLayout(System.Runtime.InteropServices.LayoutKind.Sequential)]
        private struct NativeRect { public int Left, Top, Right, Bottom; }

        [System.Runtime.InteropServices.DllImport("user32.dll")]
        private static extern IntPtr MonitorFromRect(ref NativeRect rect, int flags);

        [System.Runtime.InteropServices.DllImport("shcore.dll")]
        private static extern int GetDpiForMonitor(IntPtr monitor, int type, out uint dpiX, out uint dpiY);

        [System.Runtime.InteropServices.DllImport("user32.dll")]
        private static extern int GetDpiForWindow(IntPtr window);

        private const int MONITOR_DEFAULTTONEAREST = 2;
        private const int MDT_EFFECTIVE_DPI = 0;

        /// The window's opening client size, in logical pixels.
        ///
        /// v0.6.24 (the owner's decision of 2026-11-18, from real renders): 1000 by 618 at text size 1, 30 px past
        /// beta.2's 588, which the owner found too short. They compared the window at 588, 612, 625 and 645, then at 612,
        /// 615, 618, 621 and 625 with the Overview's cards not growing, and chose 618 (1000:618): "better not to grow
        /// the cards". So the cards keep their comfortable height (OverviewComfort, unchanged) and the page has a little
        /// more than its own padding under the Overview's last row - the owner's choice, not a defect (WindowAudit's
        /// OpeningBandMax holds it to what 618 adds past the rows' comfort). The header card is two lines in 76 px
        /// (HeroHeight), the page tabs under it, and the pages below them: the four Overview cards are about 205 px at
        /// 100 %. Only Settings has a footer, its save bar, inside that height; the version is a pill at the end of the
        /// tabs (VersionPill) and the header's X closes the window.
        ///
        /// What the pages need (v0.6.5): the Overview's cards hold what they hold with the button each leads to at its
        /// bottom left, in a row of its own under the last line (Lead), and FitOverview gives the rows what the tallest
        /// needs, a little more, and under the last row the page's own padding, as every page has under its last card.
        /// What the rows need, with the most the Overview ever shows - three lines under Waiting, four finished
        /// conversations, four facts in Right now - is the same in every language (every line is one line, whatever it
        /// says); tests/test_gui_layout.py holds the page to it, every card a little taller than what it holds and never
        /// past comfort (OverviewComfort). On a screen too short for the window KeepOnScreen makes it shorter, and the
        /// Overview scrolls on the soft bar only where its rows no longer fit.
        ///
        /// The width is where the Pending list draws "waiting for the usage reset" and "Usage limit"
        /// whole beside "Why it is waiting" at its full 256 px: 933 to 946 in English, 813 to 817 in
        /// Korean.
        internal const int OpeningWidth = 1000;
        internal const int OpeningHeight = 618;

        /// v0.6.24-beta.2: the header card's height at text size 1 in the decision's mockup, two lines and its padding
        /// (HeroPadY); a language whose lines are taller has a taller card, and the window opens that much taller (heroRoom).
        internal const int HeroHeight = 76;

        /// The header card's room above and below its two lines: the brand's hero padding (16) less a pixel, which with
        /// the two lines makes HeroHeight.
        internal const int HeroPadY = 15;

        /// The display's scale, times the text size the window is drawn at (v0.6.11, AdoptTextSize). Read-only to the
        /// window; only LayoutAudit stands another scale in, to measure a layout at a scaling this machine is not set to.
        internal static double DpiScale
        {
            get { return dpiScale; }
        }

        /// v0.6.11: the text size the window is drawn at, and Windows' own (TextScale): 1 until Program.Main adopts them.
        internal static double TextSize = 1.0;
        private static double textRead = 1.0;

        /// Draws the window from here on at text size `drawn` - Windows' `read`, as far as the screen holds the window
        /// (TextScale.Fitting): everything at that many times the display's scale, the words and what holds them alike.
        /// Once, before the window is made (Program.Main).
        internal static void AdoptTextSize(double read, double drawn)
        {
            textRead = Math.Max(1.0, read);
            TextSize = Math.Max(1.0, drawn);
            dpiScale = displayScale * TextSize;
        }

        /// v0.6.18: draws the window from here on at `scale`, the scale of the monitor it opens on (ScaleOfMonitor), in
        /// place of the one Windows had at sign-in (SystemScale). Before AdoptTextSize, and before the window is made
        /// (Program.Main).
        ///
        /// The manifest says per-monitor v2, so Windows never stretches the window's pixels for a monitor: every one is
        /// the window's own. Drawn at the sign-in scale on every monitor, the window was twice too big on a 100% monitor
        /// beside a 200% laptop, half size the other way, and tiny on a screen whose scaling was raised without
        /// signing out - GetDpiForSystem keeps the scale of the sign-in. The window drawn at one monitor's scale opens
        /// again at the next one's when it is moved there (WM_DPICHANGED, CheckScale).
        internal static void AdoptDisplayScale(double scale)
        {
            displayScale = scale >= 0.5 ? scale : SystemScale;
            dpiScale = displayScale * TextSize;
        }

        /// The scale the window is drawn for (AdoptDisplayScale), without the text size.
        internal static double DisplayScale { get { return displayScale; } }

        /// How much larger a size in points is drawn than Windows draws it (v0.6.18): Windows turns points into pixels
        /// at the sign-in scale whatever monitor the window is on, so on a monitor of another scale the window's fonts
        /// are made that much larger or smaller - as LayoutAudit stands another scaling in, which matched a real window
        /// to the pixel. 1 where the monitor's scale is the sign-in's.
        internal static float FontFactor { get { return (float)(displayScale / SystemScale); } }

        /// `font` at FontFactor: itself where that is 1.
        internal static Font AtDisplayScale(Font font)
        {
            float factor = FontFactor;
            if (font == null || Math.Abs(factor - 1f) < 0.001f) return font;
            return new Font(font.FontFamily, font.SizeInPoints * factor, font.Style, GraphicsUnit.Point);
        }

        /// The scale of the monitor most of `area` is on (1 at 96 DPI), as Windows has it now; SystemScale where it
        /// cannot say (before Windows 8.1).
        internal static double ScaleOfMonitor(Rectangle area)
        {
            try
            {
                var rect = new NativeRect();
                rect.Left = area.Left;
                rect.Top = area.Top;
                rect.Right = Math.Max(area.Right, area.Left + 1);
                rect.Bottom = Math.Max(area.Bottom, area.Top + 1);
                IntPtr monitor = MonitorFromRect(ref rect, MONITOR_DEFAULTTONEAREST);
                uint x, y;
                if (monitor != IntPtr.Zero && GetDpiForMonitor(monitor, MDT_EFFECTIVE_DPI, out x, out y) == 0 && x >= 48)
                    return x / 96.0;
            }
            catch (Exception) { /* no shcore.dll: the sign-in scale */ }
            return SystemScale;
        }

        /// The scale of the monitor this window is on now (GetDpiForWindow), or 0 when it cannot be told.
        private double WindowScale()
        {
            try
            {
                if (!IsHandleCreated) return 0;
                int dpi = GetDpiForWindow(Handle);
                return dpi >= 48 ? dpi / 96.0 : 0;
            }
            catch (Exception) { return 0; }
        }

        /// Where a window opened with `request` goes, on the virtual screen: the bounds a reopen passes on, or the pointer
        /// - the window opens centred on the screen the pointer is on, as a window opened from the Start menu or the
        /// notification-area icon should (CenterOn).
        internal static Rectangle OpeningPlace(OpenRequest request, Point pointer)
        {
            return request != null && request.HasBounds ? request.Bounds : new Rectangle(pointer.X, pointer.Y, 1, 1);
        }

        /// The screen a window opened with `request` goes on (OpeningPlace).
        internal static Screen OpeningScreen(OpenRequest request)
        {
            return Screen.FromRectangle(OpeningPlace(request, OpeningPointer()));
        }

        /// The point a window with no bounds of its own opens at: the pointer - or, while a picture is taken (Soft.StillReady,
        /// build/capture_window.ps1), the middle of the primary screen, so a pointer on another monitor at another scaling
        /// never sets a picture's screen or size (2026-10-28: a second monitor at 100% beside the 150% primary drew pictures
        /// 1006 px wide).
        internal static Point OpeningPointer()
        {
            if (Soft.StillReady == null) return Cursor.Position;
            Rectangle primary = Screen.PrimaryScreen.WorkingArea;
            return new Point(primary.Left + primary.Width / 2, primary.Top + primary.Height / 2);
        }

        // Every fixed number in this file is written at 96 DPI and scaled here.
        //
        // Windows Forms scales the *font* with the display and leaves explicit pixel
        // sizes exactly as written, so at 200% the text is twice the size inside a
        // window that is still 780 units wide: the second column's labels clip, the
        // spin boxes crowd the card edge and the last row falls off the bottom. It
        // looked right at 100% and at 150% and was only found by opening it on a
        // 192-DPI display.
        //
        // The DPI has to come from Windows, not from `DeviceDpi`. This assembly's
        // manifest declares per-monitor awareness, but .NET Framework's WinForms only
        // honours that with an app.config opt-in this product does not ship - so
        // `DeviceDpi` answers 96 on a 192-DPI screen, which is exactly the value that
        // makes the bug invisible to a fix written against it. Measured, twice: once
        // when the window came out a third of its intended width, and again when
        // scaling by DeviceDpi changed nothing at all.
        private static double MeasureDpiScale()
        {
            try
            {
                int dpi = GetDpiForSystem();
                if (dpi >= 96) return dpi / 96.0;
            }
            catch (Exception) { /* pre-1607 Windows: fall through */ }
            try
            {
                using (var graphics = Graphics.FromHwnd(IntPtr.Zero))
                    if (graphics.DpiX >= 96f) return graphics.DpiX / 96.0;
            }
            catch (Exception) { }
            return 1.0;
        }

        private int Px(int atNinetySix)
        {
            return Soft.Px(atNinetySix);
        }

        private Padding Pad(int left, int top, int right, int bottom)
        {
            return new Padding(Px(left), Px(top), Px(right), Px(bottom));
        }

        internal SettingsForm(PersistentBridge bridge) : this(bridge, null, null)
        {
        }

        /// `catalog` and `windowFont` stand in a strings reply and the window's font, for
        /// LayoutAudit; the window itself passes neither.
        private SettingsForm(PersistentBridge bridge, Dictionary<string, object> catalog, Font windowFont)
        {
            this.bridge = bridge;
            // What it was asked to open with. A window LayoutAudit builds is asked for nothing.
            request = catalog != null ? new OpenRequest() : ParseArguments(Environment.GetCommandLineArgs());
            // The theme and the design it draws were adopted before this (Program.Main), from the same request.
            openedTheme = Palette.Theme;
            storedTheme = Theme.Opened;
            openedDesign = Design.Drawn(Palette.Theme, Palette.Design);
            storedDesign = Design.Opened;
            invisibleFrame = request.Frame;
            // Before anything is built: every label below asks the catalog for its text.
            //
            // From the cache when it was written for exactly this installation, this Interface
            // language and this Windows language (see StringsCache); otherwise asked for on a
            // worker, while the fonts and the icon are made. The window used to wait 260-400 ms for
            // the interpreter to start, and then spend 130-260 ms more on the first font.
            StartMarks.Mark("window made");
            string root = AppDomain.CurrentDomain.BaseDirectory;
            installRoot = root;
            string cacheKey = null;
            System.Threading.Tasks.Task<Dictionary<string, object>> asking = null;
            if (catalog != null) AdoptStrings(catalog);
            else
            {
                cacheKey = StringsCache.Key(root);
                openedKey = cacheKey;
                Dictionary<string, object> cached = StringsCache.Read(root, cacheKey);
                if (cached != null)
                {
                    AdoptStrings(cached);
                    // The interpreter every later read needs starts now, and if its answer differs
                    // from what was cached, the cache is what changes: this window keeps the words it
                    // opened with, as it does after a language is saved.
                    string key = cacheKey;
                    System.Threading.ThreadPool.QueueUserWorkItem(delegate { StringsCache.Refresh(root, key, cached, AskStrings()); });
                }
                else asking = System.Threading.Tasks.Task.Factory.StartNew<Dictionary<string, object>>(AskStrings);
            }
            Text = "Codex Auto Resume";
            // v0.6.11: at the text size the window opens at (TextScale, AdoptTextSize); v0.6.18: and at the scale of the
            // monitor it opens on (AtDisplayScale).
            Font = windowFont ?? AtDisplayScale(TextScale.Apply(SystemFonts.MessageBoxFont, textRead, TextSize));
            // The type roles (Soft.RoleFont) are variants of the window's own font.
            Soft.BaseFont = Font;
            StartMarks.Mark("font");
            ForeColor = Ink;
            // v0.6.24-beta.3 (W2): on a special day the window's ground faintly takes the day's (DayGround), before anything is
            // made in it - and as it was everywhere else, a picture's or a probe's window included, which look at no date.
            DayGround.Adopt(Palette.AccentBar ? null : DayArt.Today(), this);
            BackColor = Canvas;
            StartPosition = FormStartPosition.CenterScreen;
            AutoScaleMode = AutoScaleMode.Font;
            // The page the window opens on, the Overview, is whole at this size without scrolling, in
            // every language at every scaling and with the most it ever shows - tests/test_gui_layout.py
            // measures it - its cards a little taller than what they hold and the page's rhythm under
            // them; on a 1920 by 1080 screen at 150% KeepOnScreen makes it shorter, and it still fits.
            // A Settings section taller than the page scrolls. v0.6.3 grew the window to its tallest
            // section instead, which cost a second layout of everything before the first screen was
            // painted. See OpeningWidth.
            ClientSize = new Size(Px(OpeningWidth), Px(OpeningHeight));
            // Wide enough that the two columns always hold their content. Allowing a
            // narrower window buys nothing: the labels start truncating mid-word, which
            // looks broken rather than compact.
            MinimumSize = new Size(Px(800), Px(420));
            try
            {
                string icon = Path.Combine(root, "codex-auto-resume.ico");
                if (File.Exists(icon))
                {
                    Icon = new Icon(icon);
                    // With our own mark, and never in a window LayoutAudit builds: the taskbar button moves as the
                    // notification-area icon does while the window is open (TaskbarMark).
                    if (catalog == null) taskbar = new TaskbarMark(this);
                }
            }
            catch (Exception) { /* an icon is decoration; never fail the window over it */ }
            if (asking != null)
            {
                string key = cacheKey;
                // A bounded wait (StringsWaitMilliseconds): the window opens in English past it, and its words come after.
                if (asking.Wait(Math.Max(0, StringsWaitMilliseconds)))
                {
                    Dictionary<string, object> reply = asking.Result;
                    AdoptStrings(reply);
                    // Kept only if it answers for the settings the key was taken of (StringsCache.Write).
                    System.Threading.ThreadPool.QueueUserWorkItem(delegate { StringsCache.Write(root, key, reply); });
                }
                else
                {
                    lateWords = true;
                    openedLate = true;
                    asking.ContinueWith(delegate(System.Threading.Tasks.Task<Dictionary<string, object>> asked)
                    {
                        Dictionary<string, object> reply = asked.Result;
                        StringsCache.Write(root, key, reply);
                        lateReply = reply;
                        try { if (IsHandleCreated && !IsDisposed) BeginInvoke(new MethodInvoker(TakeLateWords)); }
                        catch (Exception) { /* closed meanwhile, or not yet shown: Shown takes them */ }
                    });
                }
            }
            // v0.6.11: in a language whose letters Windows' UI font does not all have, and Segoe UI does - Vietnamese
            // on a Korean Windows - the window is set in Segoe UI, as the popup, the card and the panel are (Typeface).
            // v0.6.17: Korean, Japanese and Chinese in the face Windows sets each in, where this machine has it.
            // Before anything is built, so every role's font is a variant of it.
            Font whole = Typeface.ForLanguage(Font, strings, wordsLanguage);
            if (!ReferenceEquals(whole, Font))
            {
                Font = whole;
                Soft.BaseFont = Font;
            }
            // v0.6.20: in a language written right to left the window is mirrored (Mirror), and so is every dialog it
            // opens (Soft.TitleBar). Before anything is built, so what is built inherits it.
            Mirror.Window = Mirror.Language(wordsLanguage);
            Mirror.Apply(this);

            BuildFooter();
            BuildHeader();
            // v0.6.24: taller by what the header card grew past HeroHeight (OpeningClient).
            if (heroRoom > 0) ClientSize = new Size(ClientSize.Width, ClientSize.Height + heroRoom);
            BuildColumns();
            BuildDashboard();
            // v0.6.24 final (J9): the version's pill from the first paint, read from this installation's own files.
            ShowLocalVersion(installRoot);
            // v0.6.24: the tab strip's ground and the save bar's ground drag the window as the header's does (never a tab,
            // and never the version's pill, which is pressed: only the ground of its slot drags).
            chrome.Drag(nav);
            foreach (Control strip in nav.Controls) chrome.Drag(strip);
            chrome.Drag(footer);
            if (catalog == null) opening = OpeningScreen(request);
            KeepOnScreen();
            if (catalog == null && !request.HasBounds)
            {
                // Centred on that screen by hand, as CenterScreen centres a window on the pointer's - which it measured
                // again as the window was shown, by when the pointer may have moved to another one.
                StartPosition = FormStartPosition.Manual;
                Location = CenterOn(opening.WorkingArea, Size);
            }
            if (request.HasBounds)
            {
                // Reopened where the window it replaces was, on the screen that window was on: the frame one
                // sees where that one's was, with the invisible border that window measured around it.
                StartPosition = FormStartPosition.Manual;
                Bounds = PlaceOnScreen(request.Bounds, Screen.FromRectangle(request.Bounds).WorkingArea, MinimumSize, request.Frame);
                placedBounds = Bounds;
            }
            if (request.Maximized) WindowState = FormWindowState.Maximized;
            // A dark title bar over a dark window.
            Soft.TitleBar(this);

            // The fill control is added first so the docked strips keep their edges:
            // docking is resolved from the last-added control inward, so whatever is
            // added first ends up with what is left. The page host holds whichever page
            // is showing; the settings columns are one of those pages.
            Controls.Add(pageHost);
            Controls.Add(footer);
            Controls.Add(nav);
            Controls.Add(header);
            // The keyboard follows the screen, not the order docking needs: without these the
            // Tab key went through the page, the save bar and the page tabs before it reached
            // the header's Start button - the one control that matters when the watcher is off.
            header.TabIndex = 0;
            nav.TabIndex = 1;
            pageHost.TabIndex = 2;
            footer.TabIndex = 3;

            Load += delegate
            {
                if (auditing) return;
                StartMarks.Mark("load");
                Reload();
                ShowPage(firstPage);
                StartMarks.Mark("first page");
                // A window that replaces another puts the keyboard where that one had it (FocusName).
                FocusInterim();
                StartClock();
            };
            Shown += delegate
            {
                StartMarks.Mark("shown");
                shown = true;
                // v0.6.20: the watcher's request to come forward is heard even when this window runs elevated.
                AcceptOpenRequests();
                // v0.6.24-beta.2: the opening sweep a read before this asked for (SweepLight) - after the open requests,
                // which the window takes before anything else it does once shown.
                if (sweepOnShown)
                {
                    sweepOnShown = false;
                    stateDot.Sweep();
                    if (stateDot.Sweeping) detail.Arrive(AsideAfterMs);
                }
                // v0.6.18 B3: a window that replaces another is the size it was placed at once it is on screen, whatever
                // creating it on a monitor of another scale than Windows' own did to that size on the way.
                KeepPlacedBounds();
                // Words that came before the window had a handle to be told on (StringsWaitMilliseconds).
                TakeLateWords();
                // Measured once it is on screen, for a reopen from this window maximized (Reopen).
                Padding measured = InvisibleFrame();
                if (measured != Padding.Empty) invisibleFrame = measured;
                BuildEditorsLater();
                // v0.6.23: the pages not yet shown made ready on the turns after, so a tab's first press is as quick as its next.
                PreparePagesLater();
                // Only a window build/capture_window.ps1 started, which says when it may be photographed.
                WatchForStill();
                // v0.6.16: an update from a setup program closes this window and opens it again on the new version.
                WatchForUpdate();
            };
            FormClosed += delegate { StopClock(); bridge.Stop(); };
            // W2: the controls made as the window's fields were, before the day's tint was adopted above, take it too.
            if (DayGround.Look != null) DayGround.Repaint(this, DayGround.Untinted, Palette.Canvas);
            StartMarks.Mark("built");
        }

        /// The window within the screen it opens on. Its sizes are scaled, so on a small screen at
        /// a large scaling factor it can be asked to be larger than the display - and a window
        /// whose controls sit past the edge of the screen cannot be reached at all, where a
        /// scrolling one can. Settled here, before it is shown, so it never jumps once it is.
        private void KeepOnScreen()
        {
            // v0.6.18: the screen it opens on - the pointer's, or a reopen's (OpeningScreen, taken as `opening`) - and not
            // Screen.FromControl, which before the window has a place answers the primary: a window opened on a smaller
            // secondary screen kept the primary's height and ran off it, its footer out of reach. A window LayoutAudit or
            // the render mode builds opens on no screen and is measured against the primary, as it always was: the
            // audit's sizes at a scaling this machine is not set to are taken from there (wherever the pointer is, its
            // 200% text-size audit cut the Settings section list off against a smaller screen).
            // v0.6.20: a picture drawn at a pinned scale opens on no screen at all, at its own size (RenderPinned).
            if (RenderPinned) return;
            Rectangle screen = (opening ?? Screen.FromControl(this)).WorkingArea;
            // v0.6.18: the frame its style adds (SizeFromClientSize), not Width less ClientSize.Width: Windows holds a
            // form's Width to the largest window the screen allows (SystemInformation.MaxWindowTrackSize) while the client
            // area keeps what was asked, so on a small screen at 200% that read went negative and the clamp let the
            // window grow past the screen - as the Advanced tab's frame did (HoldTabs, fixed the same way).
            Size frame = SizeFromClientSize(Size.Empty);
            int frameWidth = frame.Width, frameHeight = frame.Height;
            if (MinimumSize.Width > screen.Width || MinimumSize.Height > screen.Height)
                MinimumSize = new Size(Math.Min(MinimumSize.Width, screen.Width), Math.Min(MinimumSize.Height, screen.Height));
            ClientSize = new Size(Math.Max(Px(340), Math.Min(ClientSize.Width, screen.Width - frameWidth)),
                                  Math.Max(Px(340), Math.Min(ClientSize.Height, screen.Height - frameHeight)));
        }

        /// A reopened window back at the bounds it was placed at, when anything on the way to the screen changed them and
        /// it is neither maximized nor minimized.
        private void KeepPlacedBounds()
        {
            if (placedBounds.IsEmpty || WindowState != FormWindowState.Normal) return;
            if (Bounds != placedBounds) Bounds = placedBounds;
            placedBounds = Rectangle.Empty;
        }

        /// Where CenterScreen puts a window `size` big on a screen whose work area is `area`: centred, and never above or
        /// left of it.
        internal static Point CenterOn(Rectangle area, Size size)
        {
            return new Point(Math.Max(area.X, area.X + (area.Width - size.Width) / 2),
                             Math.Max(area.Y, area.Y + (area.Height - size.Height) / 2));
        }

        /// Control.DefaultFont, which an unparented control measures in, at FontFactor too - as LayoutAudit sets it for a
        /// scaling it stands in (v0.6.18). Once, before the window is made; nothing where the factor is 1.
        internal static void ScaleDefaultFont()
        {
            if (Math.Abs(FontFactor - 1f) < 0.001f) return;
            try
            {
                System.Reflection.FieldInfo fallback = typeof(Control).GetField("defaultFont",
                    System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Static);
                if (fallback != null) fallback.SetValue(null, AtDisplayScale(Control.DefaultFont));
            }
            catch (Exception) { /* measured in Windows' own size: a few pixels off, never a failure */ }
        }

        // ------------------------------------------------------------------- the window's own caption (v0.6.24)
        // No Windows title bar: the caption buttons stand in the hero (BuildHeader, gui/SoftChrome.cs), the window's frame
        // has no caption and no top frame (ChromeHost.Intercept, called first by WndProc), and its ClientSize means what it
        // says - a Form works its window out from its styles, which still count WS_CAPTION.
        private ChromeHost chrome;

        /// The window's caption, for the tests and the audit.
        internal ChromeHost CaptionHost { get { return chrome; } }

        // v0.6.24-beta.2: what the header card is taller than HeroHeight (BuildHeader's fit) - none in English at any
        // scaling; a language whose two lines are taller, by that.
        private int heroRoom;

        /// The client area the window opens at: OpeningWidth by OpeningHeight, and taller by what the header card is past
        /// HeroHeight, so every page is as tall in every language.
        internal Size OpeningClient
        {
            get { return new Size(Px(OpeningWidth), Px(OpeningHeight) + heroRoom); }
        }

        private void PassOn(ref Message m)
        {
            base.WndProc(ref m);
        }

        private Padding OwnFrame()
        {
            // v0.6.24 W5: no frame at all while the window's outer corner is its own (gui/SoftWindowShape.cs).
            if (chrome != null && chrome.Frameless) return Padding.Empty;
            CreateParams created = CreateParams;
            return Chrome.Frame(created.Style, created.ExStyle);
        }

        protected override Size SizeFromClientSize(Size clientSize)
        {
            return Chrome.WindowSize(clientSize, OwnFrame());
        }

        protected override void SetClientSizeCore(int x, int y)
        {
            SuspendLayout();
            try
            {
                base.SetClientSizeCore(x, y);
                Size outer = SizeFromClientSize(new Size(x, y));
                if (Size != outer) Size = outer;
                // As Control.SetClientSizeCore keeps it: the client asked for, even where Form held the window to the
                // largest the screen allows (SystemInformation.MaxWindowTrackSize) - which a picture drawn at a pinned
                // scale then sizes itself past with SetWindowPos (WindowRender.OpenForRender).
                if (ClientSize != new Size(x, y)) UpdateBounds(Left, Top, Width, Height, x, y);
            }
            finally { ResumeLayout(true); }
        }

        protected override void SetBoundsCore(int x, int y, int width, int height, BoundsSpecified specified)
        {
            // Back from maximised or minimised at the size it had (ChromeHost.Restoring).
            if (chrome != null) chrome.Restoring(ref width, ref height, specified, CreateParams);
            base.SetBoundsCore(x, y, width, height, specified);
            if (IsHandleCreated) return;
            Size client = Chrome.ClientOf(Size, OwnFrame());
            if (client != ClientSize) UpdateBounds(Left, Top, Width, Height, client.Width, client.Height);
        }

        /// The headline ends at least 8 px before the caption buttons (Brand.CaptionInsetEnd from the card's edge), by its own
        /// margin. The line under the headline starts below the caption buttons (BuildHeader's fit). v0.6.24-beta.2 (the owner,
        /// 2026-11-17, the design canvas's row 17, option C): the header holds no button - Start watcher is the Overview's
        /// Right now card's, in place of Pause (PlaceStartButton).
        private void KeepHeadlineClear()
        {
            if (chrome == null) return;
            // The card's padding at its outer side, the caption buttons' - its right, which the card mirrors for a language
            // written right to left: the pill's inset while it is in the card (PillToHeader).
            int reach = Px(Brand.CaptionInsetEnd) + chrome.GroupWidth + Px(8) - hero.Padding.Right;
            var wanted = new Padding(0, 0, Math.Max(0, reach), 0);
            if (headline.Margin != wanted) headline.Margin = wanted;
        }

        // ------------------------------------------------------------------- chrome
        private void BuildColumns()
        {
            // The Settings page: the section list on the left and one section's cards on the
            // right, scrolling on their own if a section is taller than the window.
            columns.Dock = DockStyle.Fill;
            // The editors are built before ShowPage first shows this page, and an unparented
            // control inherits Control.DefaultFont rather than the window's.
            columns.Font = Font;
            columns.ColumnCount = 2;
            columns.RowCount = 1;
            // Wide enough for "Automatische Wiederherstellung" and its peers at every scaling.
            columns.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, Px(244)));
            columns.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
            columns.RowStyles.Add(new RowStyle(SizeType.Percent, 100f));
            // The section list's faces in line with the tabs' (NavStart): Brand.PillInset inside the header card's edge.
            columns.Padding = Pad(NavStart, 0, 0, 0);

            var list = new SoftFlow();
            list.Dock = DockStyle.Fill;
            list.FlowDirection = FlowDirection.TopDown;
            list.WrapContents = false;
            // The first section's face level with the first card's top (PageRoom), its ring's room above it.
            list.Margin = Pad(0, PageTop - TabRing, 2, 0);
            list.AccessibleRole = AccessibleRole.PageTabList;
            list.AccessibleName = S("nav.settings", "Settings");
            // v0.6.23 (perffix): laid out once its sections' buttons are all in it (the strip of tabs says why).
            list.SuspendLayout();
            foreach (string name in SectionOrder)
            {
                var button = new NavButton();
                button.Vertical = true;
                button.Text = SectionTitle(name);
                button.Font = Soft.RoleFont("nav");
                button.AutoSize = false;
                button.Size = new Size(Px(230), Px(40));
                button.Margin = Pad(0, 0, 0, 2);
                string target = name;
                button.Click += delegate { ShowSection(target); };
                sectionButtons[name] = button;
                list.Controls.Add(button);

                var stack = new SoftStack();
                // Not docked, and as wide as the page less a scroll bar whether or not one is
                // showing (FitSections). Docked, a section took the page's width with the bar or
                // without it, and Continuation - the one section tall enough to scroll - was laid out
                // again at a new width every time it was shown.
                stack.Location = Point.Empty;
                stack.Anchor = AnchorStyles.Top | AnchorStyles.Left;
                stack.ColumnCount = 1;
                stack.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
                stack.GrowStyle = TableLayoutPanelGrowStyle.AddRows;
                stack.AutoSize = true;
                stack.AutoSizeMode = AutoSizeMode.GrowAndShrink;
                stack.Font = Font;
                // The cards' lift is kept inside the scrolling page, which is its edge (see Ground).
                // Each card already keeps a gap below it.
                Padding room = PageRoom();
                stack.Padding = new Padding(room.Left, room.Top, room.Right, Math.Max(0, room.Bottom - Px(Brand.PageGap)));
                // Every section stays on the page and only the one shown is visible (ShowSection).
                stack.Visible = false;
                sections[name] = stack;
                sectionScroll.Controls.Add(stack);
            }
            list.ResumeLayout(true);

            sectionScroll.Dock = DockStyle.Fill;
            // On the soft scroll bar (see SoftPage), which keeps the section's own cards' material.
            sectionScroll.Scrolls = true;
            // Its sections keep the tab row's gap over their first card (PageRoom), where a scrolling page fades its lift.
            sectionScroll.FadeTop = PageRoom().Top;
            sectionScroll.Margin = new Padding(0);
            sectionScroll.SizeChanged += delegate { FitSections(); };
            columns.Controls.Add(list, 0, 0);
            columns.Controls.Add(sectionScroll, 1, 0);
            FitSections();
        }

        /// Every section as wide as the page less the scroll bar's gutter, whether or not the bar is
        /// showing, so a section's width changes only when the window's does.
        ///
        /// Docked, a section took whatever width the page had, and the page had less of it whenever
        /// the section was tall enough to scroll. Continuation, which is, was resized twice and laid
        /// out again at each new width on every switch to it; holding the width took that switch
        /// from 290 to 225 ms (measured, 150%), and ShowSection the rest of the way. Before the page
        /// has been laid out its width is worked out from the window's, as the table will give it.
        private void FitSections()
        {
            int page = sectionScroll.Width > 0 ? sectionScroll.Width
                     : ClientSize.Width - columns.Padding.Horizontal - Px(244);
            int width = page - SoftBar.Gutter;
            if (width <= Px(160)) return;
            foreach (TableLayoutPanel stack in sections.Values)
            {
                if (stack.MinimumSize.Width == width && stack.MaximumSize.Width == width) continue;
                // In the order that never has the minimum above the maximum.
                if (width < stack.MinimumSize.Width)
                {
                    stack.MinimumSize = new Size(width, 0);
                    stack.MaximumSize = new Size(width, 0);
                }
                else
                {
                    stack.MaximumSize = new Size(width, 0);
                    stack.MinimumSize = new Size(width, 0);
                }
            }
        }

        /// The room a page keeps around its cards for their lift: as far as the panel's card shadow
        /// still changes the canvas by a colour level, at any scaling - 16 px up and to the left,
        /// where the light is, and 17 down and to the right (brand.shadow_alpha). A page that is
        /// scrolling is the edge of every shadow on it (see Ground), and at 14 px the cut was a
        /// line one could see along the top of the Continuation section.
        private Padding CardRoom()
        {
            return Pad(16, 16, 17, 17);
        }

        /// v0.6.24-beta.2 (the owner, 2026-11-17, the design canvas's row 15, "촘촘하게"): as much room above the tab row as
        /// below it - TabRowGap from the header card's foot to the tabs' faces, and TabRowGap from the faces to the top of the
        /// page's cards (AuditTabRow). Above: the header's own padding (2), the tab strip's (NavTop) and the room a tab keeps
        /// round its face for its focus ring (TabRing); below: the ring's room again and the page's top (PageTop).
        internal const int TabRowGap = 10, HeaderBelow = 2;
        /// The header's ground at either side of its card: the header card's outer edges, which the tab row lines up with.
        internal const int HeaderSide = 14;
        /// v0.6.24-beta.2 (the owner, 2026-11-17, row 18): the tab row's ends Brand.PillInset inside the header card's edges -
        /// the first tab's face at its start, the version's pill at its end (mirrored, the other way round); a tab keeps its
        /// ring's room round its face, so the strip starts that much sooner.
        internal const int NavStart = HeaderSide + Brand.PillInset - TabRing, NavEnd = HeaderSide + Brand.PillInset;
        internal const int TabRing = Brand.FocusOffset + Brand.FocusWidth;
        internal const int NavTop = TabRowGap - HeaderBelow - TabRing, PageTop = TabRowGap - TabRing;

        /// The room a page keeps for its cards' lift (CardRoom), but at its top PageTop: under the tab row its first card's
        /// lift runs on onto the tabs' ground, as the header card's runs on under the tabs.
        private Padding PageRoom()
        {
            Padding room = CardRoom();
            // In device pixels, the gap's less the ring's: each rounded alone, 7.5 and 5 at 125 % made 13 under the tabs.
            return new Padding(room.Left, Math.Max(0, Px(TabRowGap) - Px(TabRing)), room.Right, room.Bottom);
        }

        private string SectionTitle(string name)
        {
            switch (name)
            {
                case "general": return S("group.general", "General");
                case "recovery": return S("group.recovery", "Automatic recovery");
                case "continuation": return S("group.continuation", "Continuation message");
                case "appearance": return S("group.appearance", "Appearance");
                default: return S("group.advanced", "Advanced");
            }
        }

        private void ShowSection(string name)
        {
            if (!sections.ContainsKey(name)) name = "general";
            currentSection = name;
            // Painting stops while one section is hidden and the next shown, so the section is
            // painted once, finished (see Redraw).
            bool paused = Redraw(sectionScroll, false);
            try
            {
                // Every section stays on the page and only this one is visible. Taking a section
                // off the page and putting the next one on moved each of its native fields to
                // Windows' parking window and back: about 120 ms to take Continuation off and 160 ms
                // to put it back, at 150% (measured).
                sectionScroll.SuspendLayout();
                foreach (var pair in sections)
                    if (pair.Key != name) pair.Value.Visible = false;
                // Held while it becomes visible, and laid out once after. Each control in a section
                // that sizes itself asks the section to lay out again when it is shown: Continuation
                // was laid out thirteen times on the way to the screen, and a switch to it took
                // 225 ms; held, it is laid out once, and the switch takes 80 (measured, 150%).
                TableLayoutPanel section = sections[name];
                section.SuspendLayout();
                section.Visible = true;
                section.ResumeLayout(true);
                sectionScroll.ResumeLayout(false);
                sectionScroll.PerformLayout();
                sectionScroll.ScrollTo(0, false);
            }
            finally
            {
                if (paused) Redraw(sectionScroll, true);
            }
            foreach (var pair in sectionButtons)
            {
                pair.Value.Current = pair.Key == name;
                // Cached: a switch used to create a font for every item in the list.
                pair.Value.Font = Soft.RoleFont(pair.Key == name ? "nav_current" : "nav");
            }
            // General holds the power action's card: what Windows offers is asked the first time it is shown.
            LoadPowerWhereShown();
            // v0.6.18: Advanced holds the homes' card: the Codex home it suggests is asked each time it is shown.
            LoadHomeSuggestionWhereShown();
        }

        private const int WM_SETREDRAW = 0x000B;
        private const int RDW_INVALIDATE = 0x0001;
        private const int RDW_ERASE = 0x0004;
        private const int RDW_ALLCHILDREN = 0x0080;
        private const int RDW_FRAME = 0x0400;

        [System.Runtime.InteropServices.DllImport("user32.dll")]
        private static extern bool RedrawWindow(IntPtr window, IntPtr rectangle, IntPtr region, int flags);

        /// Stops painting `control` while what it shows is swapped, or starts it again and has
        /// the whole of it painted once. Returns whether it stopped it: a window that is not on
        /// screen is left alone, because turning painting back on also makes a window visible.
        ///
        /// A page switch otherwise painted every control it moved on the way, once for each move.
        private static bool Redraw(Control control, bool on)
        {
            if (!on && (!control.IsHandleCreated || !control.Visible)) return false;
            SendMessage(control.Handle, WM_SETREDRAW, on ? (IntPtr)1 : IntPtr.Zero, IntPtr.Zero);
            if (on) RedrawWindow(control.Handle, IntPtr.Zero, IntPtr.Zero, RDW_INVALIDATE | RDW_ERASE | RDW_ALLCHILDREN | RDW_FRAME);
            return true;
        }

        private void BuildHeader()
        {
            // What the watcher is doing belongs at the top, in the window's largest
            // type. It used to be a muted sentence in a strip along the bottom, under
            // sixteen checkboxes - which put the one thing a person opens this window to
            // check below everything they did not come for.
            //
            // A card on the canvas, as the panel's hero is. The card is the grid.
            header.Dock = DockStyle.Top;
            header.Padding = Pad(HeaderSide, 12, HeaderSide, HeaderBelow);
            hero.Dock = DockStyle.Fill;
            hero.Margin = new Padding(0);
            // v0.6.24-beta.2: two lines in HeroHeight - the brand's padding at the sides, HeroPadY above and below.
            hero.Padding = Pad(Brand.HeroPadLeft, HeroPadY, Brand.HeroPadRight, HeroPadY);
            hero.ColumnCount = 3;
            hero.RowCount = 2;
            // Wide enough for the dot and its glow at any scaling: an absolute 22 held a 24-pixel
            // dot at 200% and sliced a third of it off.
            hero.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, Px(28)));   // state dot and its glow
            hero.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));   // what it is doing
            hero.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));        // the way out
            hero.RowStyles.Add(new RowStyle(SizeType.Percent, 50f));
            hero.RowStyles.Add(new RowStyle(SizeType.Percent, 50f));

            // Drawn rather than a glyph so the dot stays round and vertically centred at
            // any scaling, and it carries the same state as the words beside it. It
            // spans both rows because it describes the pair, not the first line (v0.6.10
            // stood it on the headline's line for a while, and gave that back). Its glow is
            // the one thing in the window that moves, and only while there is something to
            // show moving (see HaloDot); with motion reduced it holds still.
            var dot = stateDot;
            dot.Dock = DockStyle.Fill;
            dot.BackColor = Card;
            dot.Margin = new Padding(0);

            headline.Dock = DockStyle.Fill;
            headline.TextAlign = ContentAlignment.BottomLeft;
            headline.ForeColor = Ink;
            headline.Font = Soft.RoleFont("display");
            headline.AutoEllipsis = true;
            // The light's name for a screen reader is the headline, whichever of the header's writers set it last.
            headline.TextChanged += delegate { stateDot.AccessibleName = headline.Text; };
            // In the window's language until the first status arrives: after a reopen it showed a moment, in English in
            // every language (the v0.6.20 final's live acceptance, A5).
            headline.Text = S("status.loading", "Loading...");

            detail.Dock = DockStyle.Fill;
            detail.TextAlign = ContentAlignment.TopLeft;
            detail.ForeColor = Secondary;
            detail.AutoEllipsis = true;   // narrow gracefully instead of wrapping
            detail.Margin = Pad(0, 2, 0, 0);

            // Shown only while the watcher is stopped. Nothing is recovered then, so a window that reports the fact and offers
            // no way out is a dead end - and the watcher is the part nobody should have to think about. v0.6.24-beta.2 (the
            // owner, 2026-11-17, the design canvas's row 17, option C): no longer in the header, which shows the state only, but
            // in the Overview's Right now card in place of Pause recovery - the two never stand together (PlaceStartButton).
            startButton = MakeButton(S("action.start", "Start watcher"), true, delegate { StartWatcher(); });
            startButton.Visible = false;

            hero.Controls.Add(dot, 0, 0);
            hero.SetRowSpan(dot, 2);
            hero.Controls.Add(headline, 1, 0);
            hero.Controls.Add(detail, 1, 1);
            header.Controls.Add(hero);
            // v0.6.24: the window's caption buttons in the hero's top outer corner, over the card and its day's scene
            // (gui/SoftChrome.cs) - the window's own children, as the header (a SoftPage) moves what it holds of its own to
            // its right when mirrored; the ground, the card, its words and its light drag the window.
            chrome = ChromeHost.Install(this, hero, this);
            // v0.6.24 W5: and the window's own outer corner, where Brand.WindowSquircle turns it on (on from v0.6.24-beta).
            chrome.OwnCorner();
            chrome.Drag(header);
            chrome.Drag(headline);
            chrome.Drag(detail);
            chrome.Drag(stateDot);
            hero.Layout += delegate { KeepHeadlineClear(); };
            KeepHeadlineClear();
            // Measured, not a formula of the font: two lines of the taller of the two, each row
            // half the card so the pair stays centred on the dot, and never less than the dot's
            // glow needs. Again whenever the window's font changes.
            EventHandler fit = delegate
            {
                // In the window's own font: the header joins the window after this, and until it does the line under
                // the headline measures in Control.DefaultFont - a smaller one, which a larger text size (v0.6.11)
                // made a line too short for it.
                detail.Font = Font;
                int line = Math.Max(headline.PreferredSize.Height, detail.PreferredSize.Height + detail.Margin.Vertical);
                // v0.6.24-beta.2: the line under the headline starts below the caption buttons, in the card's top corner.
                line = Math.Max(line, Px(Brand.CaptionInsetTop + Brand.CaptionButtonH) - hero.Padding.Top);
                int body = Math.Max(2 * line, 2 * HaloDot.Extent + Px(2));
                // Never shorter than HeroHeight, whose two lines a face with shorter lines centres in it.
                body = Math.Max(body, Px(HeroHeight) - hero.Padding.Vertical);
                // What the card is taller than HeroHeight the window opens taller by (OpeningClient), so the pages keep theirs.
                heroRoom = Math.Max(0, body + hero.Padding.Vertical - Px(HeroHeight));
                header.Height = body + hero.Padding.Vertical + header.Padding.Vertical;
            };
            fit(this, EventArgs.Empty);
            FontChanged += fit;
            dayLook = Palette.AccentBar ? null : DayArt.Today();
            if (dayLook != null) JoinDayScene();
        }

        private bool dayJoined;

        /// The day's scene on the header, placed again whenever the words or the card move: once, the first day it has a look.
        private void JoinDayScene()
        {
            if (dayJoined) return;
            dayJoined = true;
            header.Controls.Add(dayScene);
            dayScene.BringToFront();
            // v0.6.24: the caption buttons stand over the scene, which is drawn under them (ChromeHost.Scene).
            chrome.Scene = dayScene;
            EventHandler place = delegate { PlaceDayScene(); };
            hero.SizeChanged += place;
            headline.TextChanged += place;
            detail.TextChanged += place;
            Resize += place;
            Shown += place;
        }

        /// A window left open past midnight (the window's clock, every second): the scene of the new day, or none, as the
        /// taskbar and title-bar icons follow the date (TaskbarMark.FollowTheDay).
        private void FollowDayScene()
        {
            // v0.6.24: and the version pill's hint, which starts once the pill is on the screen and follows the date too.
            FollowPillHint();
            if (!dayScene.Follow(ref dayLook)) return;
            // W2: the window's ground follows the date too - every ground in the old day's colour takes the new one.
            Color was = Palette.Canvas;
            DayGround.Adopt(dayLook, this);
            if (Palette.Canvas.ToArgb() != was.ToArgb()) DayGround.Repaint(this, was, Palette.Canvas);
            if (dayLook == null)
            {
                dayScene.Place(false, null, 0, 0, 0, 0, 0, 0);
                return;
            }
            JoinDayScene();
            PlaceDayScene();
        }

        private int WordsEnd(Label label, bool mirrored, int width)
        {
            Size words = Soft.Measure(label.Text ?? "", label.Font, int.MaxValue, TextFormatFlags.SingleLine | TextFormatFlags.NoPrefix);
            return (mirrored ? width - label.Right : label.Left) + Math.Min(words.Width, label.Width);
        }

        /// The day in what the header's words leave of the card (W2, the owner's pick of 2026-11-17): from past the last word to
        /// the card's outer edge, under the caption buttons too, its scene as tall as the card left of them (DayArt.Fit, Band).
        /// No word on it; where the words leave it no room, none of it - and so no slice behind the buttons either. This is the
        /// one place that decides its rectangle; the buttons paint what it puts under them (ChromeHost.Scene).
        private void PlaceDayScene()
        {
            if (dayLook == null) return;
            // The version's pill at the card's outer end (PillToHeader) stands where the scene would: no scene then.
            if (versionPill != null && versionPill.Parent == hero)
            {
                dayScene.Place(false, null, 0, 0, 0, 0, 0, 0);
                return;
            }
            bool mirrored = Mirror.Of(hero);
            int width = hero.Width, hair = Soft.Hairline, outer = width - hair;
            int end = Math.Max(WordsEnd(headline, mirrored, width), WordsEnd(detail, mirrored, width)), left, fade;
            int room = CaptionRoom(mirrored, width, outer);
            double unit;
            bool scene = DayArt.Fit(dayLook, end, 0, width, outer - room, hair, hero.Height - hair, out left, out unit, out fade);
            dayScene.Keep(room, scene);
            dayScene.Place(DayArt.Band(left, outer), dayLook, hero.Left + (mirrored ? width - outer : left), hero.Top + hair, outer - left,
                           hero.Height - 2 * hair, unit, fade);
        }

        /// How far in from the card's outer edge (`outer`, measured from its inner side as the words are) the caption buttons
        /// reach, and a gap past them: the room the day's scene keeps clear. None where no button is shown.
        private int CaptionRoom(bool mirrored, int width, int outer)
        {
            if (chrome == null) return 0;
            Point card = Point.Empty;
            for (Control c = hero; c != null && c != this; c = c.Parent) card.Offset(c.Left, c.Top);
            int reach = 0;
            foreach (CaptionButton button in new[] { chrome.MinimizeButton, chrome.MaximizeButton, chrome.CloseButton })
            {
                if (button == null || !Soft.OwnVisible(button)) continue;
                Point at = Point.Empty;
                for (Control c = button; c != null && c != this; c = c.Parent) at.Offset(c.Left, c.Top);
                int inner = mirrored ? at.X + button.Width - card.X : width - (at.X - card.X);
                reach = Math.Max(reach, inner - (width - outer));
            }
            return reach > 0 ? reach + Px(Brand.DayWideGap) : 0;
        }

        private void BuildFooter()
        {
            // The save bar: a card on the canvas at the foot of the window, as the panel's is. The
            // card is the grid. v0.6.24-beta.2 (the owner's decision of 2026-11-16): on the Settings page only (ShowPage),
            // the one page with anything to save, inside the height the other pages give their cards; no Close (the
            // header's X closes the window) and no version (its pill is at the end of the page tabs, BuildVersionPill).
            footer.Dock = DockStyle.Bottom;
            footer.Visible = false;
            footer.Padding = Pad(14, 10, 14, 12);
            savebar.Dock = DockStyle.Fill;
            savebar.Margin = new Padding(0);
            savebar.Padding = Pad(Brand.SavebarPadLeft + 6, Brand.SavebarPadTop, Brand.SavebarPadRight, Brand.SavebarPadBottom);
            savebar.ColumnCount = 2;
            savebar.RowCount = 1;
            savebar.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));   // what happens once edits are saved
            savebar.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));        // buttons
            // A Dock=Fill child of an implicit AutoSize row measures to nothing, and the
            // strip then renders empty. Say what the row is.
            savebar.RowStyles.Add(new RowStyle(SizeType.Percent, 100f));

            // Said only while a language or theme changed and there are edits to keep: the window
            // reopens in the new one once they are saved or discarded (see CheckReopen). The card grows to
            // hold all of it beside the buttons (fit, below) - five lines of French at the window's narrowest -
            // and only past NoteLines does it end in an ellipsis; a screen reader has it whole.
            reopenNote = new NoteLabel();
            reopenNote.AutoSize = false;
            reopenNote.Dock = DockStyle.Fill;
            reopenNote.TextAlign = ContentAlignment.MiddleLeft;
            reopenNote.AutoEllipsis = true;
            reopenNote.UseMnemonic = false;
            reopenNote.ForeColor = Secondary;
            reopenNote.LiveSetting = AutomationLiveSetting.Polite;
            reopenNote.Margin = Pad(0, 0, 8, 0);
            reopenNote.Visible = false;

            var row = new SoftFlow();
            row.BackColor = Card;
            // At the right of its cell and in the middle of it, beside a note taller than the buttons.
            row.Anchor = AnchorStyles.Right;
            row.FlowDirection = FlowDirection.RightToLeft;
            row.WrapContents = false;
            row.AutoSize = true;
            row.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            // Explicit, because the default is 3px on every side and does not scale. Those
            // six pixels were the whole bug: the strip's height was computed from a text
            // measurement plus a constant, the row needed six more than the arithmetic
            // allowed for, and every button lost the last two rows of its own border.
            row.Margin = new Padding(0);
            // v0.6.23 (perffix): laid out once its buttons are all in it (the strip of tabs says why).
            row.SuspendLayout();
            // Only the Settings page has anything to save. v0.6.23: in the accent only while there is (ShowSaveLook).
            saveButton = MakeButton(S("action.save", "Save"), false, delegate { Save(); });
            restoreButton = MakeButton(S("action.restore", "Restore defaults"), false, delegate { RestoreDefaults(); });
            row.Controls.Add(saveButton);
            row.Controls.Add(restoreButton);
            row.ResumeLayout(true);

            savebar.Controls.Add(reopenNote, 0, 0);
            savebar.Controls.Add(row, 1, 0);
            footer.Controls.Add(savebar);
            // Measured, not derived. A strip sized by a formula cannot know how tall an
            // AutoSize button becomes once the font is applied, and being two pixels short
            // looks exactly like a drawing bug. Again whenever the window's font changes, the
            // reopen note is shown or hidden, and - while it shows - the room beside it changes.
            bool fitting = false;
            EventHandler fit = delegate
            {
                // Laying the card out again below raises what calls this, so the height is worked out once.
                if (fitting) return;
                fitting = true;
                try
                {
                    int content = Math.Max(savebar.PreferredSize.Height, row.PreferredSize.Height + savebar.Padding.Vertical);
                    if (reopenNoteShown) content = Math.Max(content, NoteHeight(row) + savebar.Padding.Vertical);
                    int height = content + footer.Padding.Vertical;
                    if (footer.Height != height) footer.Height = height;
                    // A height given to the strip while the window is being laid out reaches the strip and not
                    // the card in it: the layout that is running has already placed the card, and the layout the
                    // new height asks for is dropped when that one ends (Control.PerformLayout). The card would
                    // then keep the height it was given before the note was shown - which is what left it two
                    // lines short of the note on the CI runner (v0.6.4, measured). So the card is held to the
                    // strip here, and the window laid out around a strip whose height changed; both are asked
                    // for again from the window's own Resize, which is raised after that layout is over.
                    if (savebar.Height != footer.ClientSize.Height - footer.Padding.Vertical)
                    {
                        PerformLayout();
                        footer.PerformLayout();
                    }
                }
                finally { fitting = false; }
            };
            fit(this, EventArgs.Empty);
            FontChanged += fit;
            fitFooter = fit;
            EventHandler follow = delegate { if (reopenNoteShown) fit(this, EventArgs.Empty); };
            savebar.SizeChanged += follow;
            row.SizeChanged += follow;
            // The window's own size last of all: its Resize is raised once it has been laid out, which is the
            // one place a card left short by a layout that was already running can be given its height.
            Resize += follow;
        }

        /// v0.6.24-beta.2 (the owner's decision of 2026-11-16): the version and the edition's word in a raised pill at the outer
        /// end of the page tabs, centred on them (VersionPill) - in a slot of ground docked there, mirrored to the left end
        /// for a language written right to left. It never lies over a tab: where the tabs need the width (FitVersionPill),
        /// it shows the version alone, and where even that does not fit, it is not shown - the version is still on
        /// Diagnostics.
        private void BuildVersionPill(Control strip)
        {
            // Secondary text, which it is. The idle fill it was drawn in is a colour for a status light, 2.41:1
            // on the card in light and 3.10:1 in dark: too faint for the one field people are asked to read out.
            versionText.ForeColor = Secondary;
            versionPill = new VersionPill(versionText);
            versionPill.Padding = VersionPill.Inner;
            // Each press, not Click: a quick second press is a double click and raises no Click.
            versionText.MouseDown += delegate(object sender, MouseEventArgs e) { if (e.Button == MouseButtons.Left) VersionPressed(); };
            versionPill.MouseDown += delegate(object sender, MouseEventArgs e) { if (e.Button == MouseButtons.Left) VersionPressed(); };
            pillSlot = new SoftPage();
            pillSlot.Dock = Mirror.Window ? DockStyle.Left : DockStyle.Right;
            pillSlot.TabStop = false;
            pillSlot.Controls.Add(versionPill);
            nav.Controls.Add(pillSlot);
            // v0.6.24: its hint on a special day - the nudge moves it up in its slot, the ring is drawn on it (FollowPillHint).
            pillHint = new PillHint(versionPill);
            versionPill.Hint = pillHint;
            pillHint.Changed = delegate(bool moved)
            {
                if (moved && versionPill.Parent == pillSlot) pillSlot.PerformLayout();
                // v0.6.26 (audit D11): placed in whole pixels, drawn the rest of a pixel lower - it moves smoothly.
                versionPill.Shift(versionPill.Parent == pillSlot ? pillHint.Offset : 0f);
                versionPill.Invalidate();
            };
            Shown += delegate { FollowPillHint(); };
            versionPill.VisibleChanged += delegate { FollowPillHint(); };
            // Where the pill stands in its slot: at its outer end, the gap to the tabs at its inner (the slot's padding,
            // which a mirrored slot mirrors), and centred on the tabs' line - less the hint's nudge. Not while it stands in
            // the header card (PillToHeader), whose table places it.
            pillSlot.Layout += delegate
            {
                if (versionPill.Parent != pillSlot) return;
                Rectangle room = pillSlot.DisplayRectangle;
                int tabs = 0;
                foreach (Control tab in strip.Controls) tabs = Math.Max(tabs, tab.Height);
                if (tabs == 0) tabs = pillSlot.Height;
                var at = new Point(Mirror.Of(pillSlot) ? room.Right - versionPill.Width : room.X,
                                   Math.Max(0, (tabs - versionPill.Height) / 2 - pillHint.Nudge));
                if (versionPill.Location != at)
                {
                    versionPill.Location = at;
                    versionPill.Lifted();
                }
            };
            nav.Layout += delegate { FitVersionPill(strip); };
            // And whenever the strip lays its tabs out again: a tab shown later - the advanced edition's Advanced features
            // and Chat, once their words come (AdvancedPage.cs) - lays out the strip alone, and the pill gives way to it.
            // Where that layout is the nav's own placing the strip, the layout the slot's change asks of the nav is dropped
            // as the running one ends (Control.PerformLayout), and the strip would keep the width it had beside the pill -
            // the Chat tab cut off (dev CI 43859506322): so the strip is given here the room the slot now leaves it, as the
            // nav's next layout gives it, before it lays its tabs out in it.
            strip.Layout += delegate
            {
                if (!FitVersionPill(strip) || strip.Dock != DockStyle.Fill) return;
                Rectangle room = nav.DisplayRectangle;
                if (Soft.OwnVisible(pillSlot))
                {
                    if (pillSlot.Dock == DockStyle.Left) room.X += pillSlot.Width;
                    room.Width -= pillSlot.Width;
                }
                if (room.Width > 0 && strip.Bounds != room) strip.Bounds = room;
            };
            versionText.TextChanged += delegate { if (nav.IsHandleCreated) nav.PerformLayout(); else FitVersionPill(strip); };
            FitVersionPill(strip);
        }

        private bool fittingPill;

        /// v0.6.24 (the owner, 2026-11-18, the advanced edition's eight tabs in English, where the pill had gone): the room
        /// a tab keeps at either side of its name - today's, and the least the tabs are drawn closer to so the pill stays,
        /// half of it, where the names still read as separate tabs. Every tab alike, so the gaps stay equal; the chosen
        /// tab's raised look is its face, which the ring's room (TabRing) and the margin keep off its neighbours whatever
        /// the padding.
        internal const int TabPadX = 18, TabPadXLeast = 9, TabPadY = 8;

        /// The pill whole - the version and the edition - where the tabs leave room for it and the gap before it; else the
        /// tabs drawn closer, every one alike and no closer than needed (TabPadX down to TabPadXLeast), so it still fits
        /// whole; else the version alone, the tabs as close as that needs; and where even the closest tabs leave no room,
        /// the pill at the end of the header card's second line, under the caption buttons (PillToHeader) - never hidden
        /// (the owner, 2026-11-18). The room is the strip's less the tabs' own width, at every text size and in every
        /// language, and again whenever the strip lays its tabs out (test_gui_v0624_dashboard, test_gui_pill_room). Whether
        /// the slot was shown, hidden or resized, or the tabs' padding changed, which changes the strip's room.
        private bool FitVersionPill(Control strip)
        {
            if (fittingPill || versionPill == null) return false;
            fittingPill = true;
            try
            {
                int gap = Px(12);
                // The tabs' own row less the room at the sides of their names, each shown tab as wide as it asks with its
                // margins - not the strip's PreferredSize, which a tab just shown has not yet reached while the strip lays
                // out for it (dev CI 43859506322: the Chat tab).
                int room = nav.DisplayRectangle.Width;
                int full = Px(TabPadX), least = Math.Min(full, Px(TabPadXLeast));
                // The most room at either side of every name, from today's down, that leaves `taken` beside the tabs; or
                // less than the least where none does. Each tab as wide as it would ask with that room (TabRowAt), measured
                // rather than reckoned: a short name's tab has a floor of its own (NavButton's measure of its other weight).
                Func<int, int> sides = delegate(int taken)
                {
                    for (int each = full; each >= least; each--)
                        if (TabRowAt(strip, each) + taken <= room) return each;
                    return least - 1;
                };
                bool known = !string.IsNullOrEmpty(versionText.Version);
                // Two rows of tabs (the advanced edition's on a screen too narrow for one, HoldTabs) leave the row no end.
                var flow = strip as FlowLayoutPanel;
                bool oneRow = flow == null || !flow.WrapContents;
                // v0.6.24 (the owner, 2026-11-18): the version alone in both editions, never the edition's word - a screen
                // reader is still told both (VersionPill.Tell), and the advanced edition is told by its ink (VersionInk).
                versionText.Shortened = true;
                VersionInk();
                int alone = versionPill.VersionWidth;
                int pad = sides(alone + gap);
                bool inRow = known && oneRow && pad >= least;
                if (!inRow) pad = oneRow ? Math.Max(least, sides(0)) : full;
                bool changed = TabSides(strip, pad);
                versionPill.Tell();
                var size = new Size(alone, versionPill.PillHeight);
                if (versionPill.Size != size) versionPill.Size = size;
                pillSlot.Padding = new Padding(gap, 0, 0, 0);
                int width = size.Width + gap;
                if (pillSlot.Width != width)
                {
                    pillSlot.Width = width;
                    changed = true;
                }
                if (Soft.OwnVisible(pillSlot) != inRow)
                {
                    pillSlot.Visible = inRow;
                    changed = true;
                }
                PillToHeader(known && !inRow);
                versionPill.Lifted();
                return changed;
            }
            finally { fittingPill = false; }
        }

        // A tab of its own, never shown, that a tab's words, weight and room are set on to ask how wide it would be (TabRowAt),
        // and what it answered, by the font, the words and the room.
        private NavButton tabMeasure;
        private readonly Dictionary<string, int> tabWidths = new Dictionary<string, int>();

        /// How wide the strip's row of shown tabs would be with `pad` at either side of every name, margins included: each
        /// tab as a tab of its own set as it is but for the room asks - for every room alike, the room the tabs have now
        /// too, so the answer never depends on which room that is and a fitting never undoes the one before it.
        private int TabRowAt(Control strip, int pad)
        {
            int width = strip.Padding.Horizontal;
            foreach (Control tab in strip.Controls)
            {
                if (!Soft.OwnVisible(tab)) continue;
                var button = tab as NavButton;
                if (button == null)
                {
                    width += tab.GetPreferredSize(Size.Empty).Width + tab.Margin.Horizontal;
                    continue;
                }
                width += TabWidthAt(button, pad) + tab.Margin.Horizontal;
            }
            // v0.6.24 final (J9): and the room of a tab whose showing is not known yet (TabsHeld) - the advanced edition's
            // Chat until its state is read - so the row does not move when it shows.
            var held = new List<NavButton>();
            TabsHeld(held);
            foreach (NavButton button in held) width += TabWidthAt(button, pad) + button.Margin.Horizontal;
            return width;
        }

        /// The width `button` asks for with `pad` at either side of its words, measured once per font, room and words.
        private int TabWidthAt(NavButton button, int pad)
        {
            var room = new Padding(pad, button.Padding.Top, pad, button.Padding.Bottom);
            string key = System.Runtime.CompilerServices.RuntimeHelpers.GetHashCode(button.Font).ToString(CultureInfo.InvariantCulture) +
                         "|" + room + "|" + button.AutoSizeMode + "|" + button.Text;
            int asked;
            if (!tabWidths.TryGetValue(key, out asked))
            {
                if (tabMeasure == null) tabMeasure = new NavButton();
                tabMeasure.AutoSize = button.AutoSize;
                tabMeasure.AutoSizeMode = button.AutoSizeMode;
                tabMeasure.Font = button.Font;
                tabMeasure.Text = button.Text;
                tabMeasure.Padding = room;
                asked = tabMeasure.GetPreferredSize(Size.Empty).Width;
                tabWidths[key] = asked;
            }
            return asked;
        }

        /// Every tab of the strip with `pad` at either side of its name, shown or not (a tab shown later comes in as close
        /// as the rest). Whether any changed.
        private bool TabSides(Control strip, int pad)
        {
            bool changed = false;
            var wanted = new Padding(pad, Px(TabPadY), pad, Px(TabPadY));
            foreach (Control tab in strip.Controls)
            {
                if (!(tab is NavButton) || tab.Padding == wanted) continue;
                tab.Padding = wanted;
                changed = true;
            }
            return changed;
        }

        // The header card's padding as it was built, which the pill's room at its outer side replaces while it is there.
        private Padding heroPadding;

        /// v0.6.24 (the owner, 2026-11-18): the pill in the header card where even the closest tabs leave it no room - the
        /// card's third column, on its second line, at its outer end under the caption buttons, Brand.PillInset from the
        /// card's edge as at the tab row's end (the card's padding at that side is the inset while it is there; the headline
        /// keeps clear of the caption buttons by its own margin, KeepHeadlineClear); the line under the headline ends a gap
        /// before it. Back in its slot at the tab row's end as soon as the row has room again.
        private void PillToHeader(bool wanted)
        {
            if (wanted == (versionPill.Parent == hero)) return;
            if (heroPadding == Padding.Empty) heroPadding = hero.Padding;
            hero.SuspendLayout();
            try
            {
                if (wanted)
                {
                    pillSlot.Controls.Remove(versionPill);
                    int inset = Px(Brand.PillInset);
                    // The card's right and the pill's left as a language written left to right has them: the card mirrors both
                    // for one written right to left (measured: swapped here as well, the pill stood 32 px in, 2026-11-18).
                    hero.Padding = new Padding(heroPadding.Left, heroPadding.Top, inset, heroPadding.Bottom);
                    versionPill.Anchor = AnchorStyles.None;
                    versionPill.Margin = new Padding(Px(12), 0, 0, 0);
                    hero.Controls.Add(versionPill, 2, 1);
                    hero.SetColumnSpan(headline, 2);
                }
                else
                {
                    hero.Controls.Remove(versionPill);
                    hero.SetColumnSpan(headline, 1);
                    hero.Padding = heroPadding;
                    versionPill.Anchor = AnchorStyles.Top | AnchorStyles.Left;
                    versionPill.Margin = Padding.Empty;
                    pillSlot.Controls.Add(versionPill);
                }
            }
            finally { hero.ResumeLayout(true); }
            KeepHeadlineClear();
            PlaceDayScene();
        }

        /// v0.6.24 (the owner, 2026-11-18, from real renders): the advanced edition is told on the pill by its ink alone -
        /// Brand.EditionInk, its own blue in light and in dark - while the pill's fill and edge are the standard ones; the
        /// standard edition keeps the secondary ink, and High Contrast the system's (Secondary there).
        private void VersionInk()
        {
            Color ink = versionText.Edition == null || Palette.Contrast ? Secondary
                      : Tokens.Dark ? Brand.Dark.EditionInk() : Brand.EditionInk();
            if (versionText.ForeColor != ink) versionText.ForeColor = ink;
        }

        /// How the pill was last fitted, for the tests and the audit: "whole" at the tab row's end (the version, all the pill
        /// shows since 2026-11-18), "header" in the header card, or "none" before there is a version to show.
        internal string PillFit
        {
            get
            {
                if (versionPill != null && versionPill.Parent == hero) return "header";
                return pillSlot == null || !Soft.OwnVisible(pillSlot) ? "none" : "whole";
            }
        }

    }

    /// What becomes of an exception thrown in a click, a timer or a reply handed back to the window (v0.6.23): never .NET's
    /// own dialog, which is in English and whose Quit ends the program with its bridge still up. It goes to errors.log,
    /// where the watcher's own go, and the window stays: one such exception leaves what is on the screen as it was. Where
    /// they keep coming - a timer or a paint that fails each time - going on is not safe, so the bridge is stopped and
    /// the program ends.
    internal static class UiFaults
    {
        internal const int MostInAMinute = 5;
        private const long Minute = 60000;
        private const int MostWritten = 8000;
        private static readonly Stopwatch clock = Stopwatch.StartNew();
        private static long firstAt = -Minute - 1;
        private static int seen;
        private static string home;
        private static PersistentBridge bridge;

        /// The installation errors.log is in, and the bridge to stop; before this nothing is written and nothing stopped.
        internal static void Follow(string root, PersistentBridge running)
        {
            home = root;
            bridge = running;
        }

        internal static void Caught(object sender, System.Threading.ThreadExceptionEventArgs e)
        {
            Write(e.Exception);
            long now = clock.ElapsedMilliseconds;
            if (now - firstAt > Minute)
            {
                firstAt = now;
                seen = 0;
            }
            if (++seen < MostInAMinute) return;
            try { if (bridge != null) bridge.Stop(); }
            catch (Exception) { /* it ends with this process's pipes all the same */ }
            Environment.Exit(1);
        }

        /// v0.6.23 (G6): an exception the window has dealt with itself (a page made ready ahead that it gave up), written
        /// to errors.log as one caught here is, and not counted towards ending the window.
        internal static void Note(Exception error)
        {
            Write(error);
        }

        private static void Write(Exception error)
        {
            try
            {
                if (home == null) return;
                string logs = Path.Combine(home, "logs");
                if (!Directory.Exists(logs)) return;
                string what = error == null ? "" : error.ToString();
                if (what.Length > MostWritten) what = what.Substring(0, MostWritten);
                File.AppendAllText(Path.Combine(logs, "errors.log"),
                                   "[" + DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture) +
                                   "] the window\n" + what + "\n", new UTF8Encoding(false));
            }
            catch (Exception) { /* not written: the window goes on */ }
        }
    }

    /// v0.6.24 final (the live re-check's L3): where the time goes from this process's start to the window's first frame on
    /// the screen, written down only when CODEX_AR_START_MARKS names a file - a person's or the measurement's, never by
    /// default. Each mark is one line, the milliseconds since the process was created and the step's name; the file is
    /// written when the first frame is on the screen and again once the first state has been shown. With the variable
    /// unset every mark is one test of a field that is null, and nothing is read, measured or written.
    internal static class StartMarks
    {
        private static readonly string target = Environment.GetEnvironmentVariable("CODEX_AR_START_MARKS");
        private static readonly StringBuilder said = string.IsNullOrEmpty(target) ? null : new StringBuilder();
        private static double offset = double.NaN;

        [DllImport("kernel32.dll", EntryPoint = "GetCurrentProcess")]
        private static extern IntPtr ThisProcess();

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool GetProcessTimes(IntPtr process, out long created, out long exited, out long kernel, out long user);

        /// Whether marks are being written down.
        internal static bool On { get { return said != null; } }

        /// `step` reached now.
        internal static void Mark(string step)
        {
            if (said == null) return;
            try
            {
                double now = Stopwatch.GetTimestamp() * 1000.0 / Stopwatch.Frequency;
                lock (said)
                {
                    if (double.IsNaN(offset))
                    {
                        // When Windows created this process, asked without a Process object (OwnProcess holds the one).
                        long created, exited, kernel, user;
                        if (!GetProcessTimes(ThisProcess(), out created, out exited, out kernel, out user)) created = DateTime.UtcNow.ToFileTimeUtc();
                        offset = (DateTime.UtcNow - DateTime.FromFileTimeUtc(created)).TotalMilliseconds - now;
                    }
                    said.Append((now + offset).ToString("0.0", CultureInfo.InvariantCulture)).Append(' ').Append(step).Append('\n');
                }
            }
            catch (Exception) { /* a mark not written down; the window goes on */ }
        }

        /// The marks so far, written to the file named.
        internal static void Write()
        {
            if (said == null) return;
            try
            {
                string text;
                lock (said) text = said.ToString();
                File.WriteAllText(target, text, new UTF8Encoding(false));
            }
            catch (Exception) { /* not written: the window goes on */ }
        }
    }

    internal static class Program
    {
        [DllImport("shell32.dll", PreserveSig = false)]
        private static extern void SetCurrentProcessExplicitAppUserModelID([MarshalAs(UnmanagedType.LPWStr)] string id);

        /// The identity Windows files this window's taskbar button under, and why it is the window's own.
        ///
        /// v0.6.5 moved the mark on the taskbar button by setting the window's big icon frame by frame, and it
        /// was captured doing so - from a build in a scratch folder. Installed, it never moved. Measured on this
        /// machine: the same executable, byte for byte, moved the button from a scratch folder and did not move
        /// it from the installed one, where an instrumented build showed the window setting frame after frame
        /// into a button that stayed pixel-identical for twenty-four seconds. What decides it is the location:
        /// Windows files an installed window under the application registered there and paints its button from
        /// that application's icon, which no window can change. (A Start Menu shortcut alone does not do it: one
        /// written for a scratch folder, with the same identity and icon, left the button moving.)
        ///
        /// So the window claims an identity of its own, which no shortcut registers, and Windows falls back to
        /// the icon the window itself carries. The notification identity is untouched: toasts are raised by the
        /// watcher process under the watcher's AUMID, and this call changes only this process. Called before any
        /// window exists, which is the only time Windows accepts it.
        internal static void TakeOwnTaskbarIdentity()
        {
            try { SetCurrentProcessExplicitAppUserModelID("CodexAutoResume.Settings"); }
            catch (Exception) { }           // an older shell, or a shell that refuses: the button simply stays still
        }

        /// v0.6.24 final (the live re-check's L3: the Start menu's Dashboard showed its first frame 6-7 s after the click): the
        /// first font this process makes, made on a thread of its own as the process starts. GDI+ builds the collection of
        /// every font installed on the machine for the first font any thread asks for - measured on the owner's PC 225-260 ms
        /// in a bare program, 230-525 ms inside the window's start, on the window's own thread, before anything of it could
        /// be painted (SettingsForm's constructor: SystemFonts.MessageBoxFont). Asked here, it is built while that thread
        /// does everything Main does before the window is made, and the constructor's font finds it built, or waits only
        /// for the rest. It changes no font: this one is let go at once, and the window makes its own as it always did.
        internal static void WarmFonts()
        {
            try
            {
                var warm = new System.Threading.Thread(delegate()
                {
                    try { using (Font font = SystemFonts.MessageBoxFont) { } }
                    catch (Exception) { /* the window's own font makes the collection, as it did before */ }
                });
                warm.IsBackground = true;
                warm.Start();
            }
            catch (Exception) { /* as before: the first font the window makes builds it */ }
        }

        /// The file the JIT keeps the window's start in (StartProfile), in the installation's config\ folder.
        internal const string StartProfileName = "window-start.jit";

        /// v0.6.24 final (L3): the window's start compiled ahead, on the machine's other cores. The window is one assembly of
        /// some 2 MiB of IL, and every method it runs before its first frame is compiled as it is first called, on the
        /// window's thread - the header, the tab row, the Overview, the first paint (ngen needs an administrator, so no
        /// image of it is made ahead). .NET's multicore JIT (ProfileOptimization) writes down which methods the start
        /// compiled, in this installation's config\ folder, and on the next start compiles them on other threads, from
        /// the first moment, ahead of the window's own thread calling them. Only for a window that opens: never for a
        /// start that hands over or opens again outside (which would write down a start of a few methods), nor for a
        /// capture's or where there is no config\ folder. A profile that cannot be read or written is no profile: the
        /// window starts as it did before.
        internal static void StartProfile(string root)
        {
            try
            {
                string folder = Path.Combine(root, "config");
                if (!Directory.Exists(folder)) return;
                System.Runtime.ProfileOptimization.SetProfileRoot(folder);
                System.Runtime.ProfileOptimization.StartProfile(StartProfileName);
            }
            catch (Exception) { /* compiled as it is called, as before */ }
        }

        [STAThread]
        internal static int Main(string[] argv)
        {
            // v0.6.24 final (L3): before anything else, the machine's fonts collected on a thread of their own (WarmFonts).
            WarmFonts();
            StartMarks.Mark("main");
            // The accessibility improvements .NET 4.8 ships but leaves off for an assembly
            // with no target-framework attribute, which is what the in-box compiler builds.
            // Without them a live region never reaches a screen reader.
            AppContext.SetSwitch("Switch.UseLegacyAccessibilityFeatures", false);
            AppContext.SetSwitch("Switch.UseLegacyAccessibilityFeatures.2", false);
            AppContext.SetSwitch("Switch.UseLegacyAccessibilityFeatures.3", false);
            TakeOwnTaskbarIdentity();
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.ThreadException += UiFaults.Caught;
            // Only a window build/capture_window.ps1 started: the mouse changes nothing it draws.
            SettingsForm.ShutOutPointer();
            // v0.6.16: the entry in Add or remove programs, in the installer window (SettingsRemove), and nothing else.
            if (SettingsRemove.IsAsked(argv)) return SettingsRemove.Run(argv);
            // Only for build/make_motion.py: frames of the window drawn offscreen, and nothing else (WindowRender.cs).
            string renderJob = SettingsForm.RenderJob;
            if (renderJob != null) return SettingsForm.RenderFrames(renderJob);

            // v0.6.20 (the final's live acceptance): started by a person - the Start menu, the program itself - while a window
            // of this program is open, that window comes forward on the page asked and this process ends, before anything is
            // built: never two Dashboards (HandsOverOnStart, HandOverTo). A reopen, the chat a notice opens and a capture start
            // as they always did.
            if (SettingsForm.HandsOverOnStart(argv, Soft.StillReady != null) &&
                SettingsForm.HandOverTo(Application.ExecutablePath, SettingsForm.HandOverPage(argv)))
                return 0;
            string root = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
            // v0.6.17: opened inside another app's private view of Windows - from the tray of a watcher the Codex app
            // started - Repair, an update and another version would register this installation where Windows never
            // looks (HostApp). The window opens again outside, once (HostApp.Outside), and this one ends; where it
            // cannot, it stays and refuses those three (HostApp.StuckInside). A capture's window stays where it was
            // started.
            string inside = Soft.StillReady == null ? HostApp.Inside() : null;
            if (inside != null && !HostApp.Relaunched(argv) &&
                HostApp.Relaunch(Application.ExecutablePath, HostApp.Arguments(argv), root))
                return 0;
            HostApp.StuckInside = inside;
            // v0.6.24 final (L3): from here on this process opens the window - the start compiled ahead (StartProfile).
            if (Soft.StillReady == null) StartProfile(root);
            StartMarks.Mark("opening");
            var bridge = new Bridge(root);
            if (!bridge.Available)
            {
                // The one message box left, and deliberately Windows' own: there is no window yet, no
                // theme has been read and no catalog has been loaded, so the window's dialog would
                // have neither its material nor its language. This says, in English, that there is
                // nothing here to run, and nothing here can say it any better.
                MessageBox.Show("Codex Auto Resume is not installed in this location." +
                                Environment.NewLine + Environment.NewLine + root,
                                "Codex Auto Resume", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return 1;
            }
            // The theme and the design, decided before the first control is made: the ones a reopening window
            // passed on, or the ones stored - read from the settings file once, both in the same parse - with the
            // theme as Windows and High Contrast have it now (Theme). Every colour below comes from them. Reduce
            // motion comes out of the same parse, so nothing moves before the bridge's first read confirms it.
            OpenRequest request = SettingsForm.ParseArguments(argv);
            string storedTheme, storedDesign;
            bool storedReduceMotion;
            Theme.Stored(root, out storedTheme, out storedDesign, out storedReduceMotion);
            Soft.ReduceMotionSetting = storedReduceMotion;
            Theme.Opened = request.Theme ?? storedTheme;
            Design.Opened = request.Design ?? storedDesign;
            Palette.AdoptDesign(Design.Opened);
            Palette.Adopt(Theme.Current(Theme.Opened));
            // v0.6.18: drawn at the scale of the monitor it opens on, the pointer's or a reopen's (AdoptDisplayScale).
            Screen opening = SettingsForm.OpeningScreen(request);
            SettingsForm.AdoptDisplayScale(SettingsForm.ScaleOfMonitor(SettingsForm.OpeningPlace(request, SettingsForm.OpeningPointer())));
            SettingsForm.ScaleDefaultFont();
            // v0.6.11: Windows' text size, as far as the screen the window opens on holds it at its narrowest.
            double text = TextScale.Read();
            SettingsForm.AdoptTextSize(text, TextScale.Fitting(text, opening.WorkingArea.Size, SettingsForm.DpiScale));
            var persistent = new PersistentBridge(root, bridge);
            UiFaults.Follow(root, persistent);
            DayArt.On = Soft.StillClock < 0;
            // v0.6.24 final (J10): opened again by the setup after an update or a Repair, behind its Finish page.
            SettingsForm.OpensBehind = SettingsForm.OpensBehindFor(argv, Soft.StillReady != null);
            var window = new SettingsForm(persistent);
            // A window a person opened comes to the front - after Finish, and opened again outside (v0.6.17); a window
            // that reopens itself, and a capture's, keep their place.
            if (request.Generation == 0 && Soft.StillReady == null) HostApp.BringToFront(window);
            Application.Run(window);
            return 0;
        }
    }
}
