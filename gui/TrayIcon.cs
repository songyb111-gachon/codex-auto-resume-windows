// Codex Auto Resume - the notification-area icon: its hidden window, the shell's words, its motion and its clicks
// (v0.6.27, S6.3e).
//
// ui/tray/icon.py (Tray: the window, the shell icon, the tooltip card's rules, the session's changes, TaskbarCreated),
// win32.py (the numbers), clicks.py (making, showing and hiding the popup, the failure seen), cards.py (hosting the
// notification cards), animation.py (the frame table built off the thread, what may move, the frame timer) and the
// package's __init__, ported call for call; its menu is gui/TrayMenu.cs (menu.py), the other half of this partial class.
//
// It runs on the host's UI thread, which owns every window and the one message loop (P6-DESIGN 1.4): the reference's icon
// had a thread and a loop of its own, so where it ended that loop (PostQuitMessage, WM_DESTROY) the port calls `Ended`,
// which the surfaces' class turns into the `closed` action. What the reference asked its control layer the core answers
// (DECISIONS.md, "The popup's model at the host boundary"; the seams are GROUNDWORK's S6.3 sixth part):
//
//   * whether the failure (or the unconfirmed sending) the icon shows is unseen: `FailureUnseen` / `UnconfirmedUnseen`,
//     by default the snapshot's own `failure_unseen` / `unconfirmed_unseen` (control.failure_unseen(marks) is True);
//   * the armed power action's word as the menu opens: `PowerArmed`, by default the snapshot's `power_armed`;
//   * a failure seen, the switch, Stop, the Dashboard, the power action turned off: posted through IHostActions on a
//     worker thread (failure_seen, toggle {paused}, stop, open_dashboard {page, row}, disarm_power);
//   * the stored settings it read for itself (StoredMixin): the core's `settings` and `strings` events, so `AdoptSettings`
//     and `AdoptReduceMotion` do nothing on the live host unless the surfaces' class gives them something to do.
//
// Every call that would reach the shell or the screen goes through one member here or through SurfaceScreen, so the probe
// mode drives the icon over a window that is made and never shown, with no icon added to the notification area: the
// shell, its icons, the session watch and the menus are recorded in the reference's words and not made.
using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Threading;

namespace CodexAutoResume
{
    /// The popup as the icon drives it (ui/popup/window.py's Popup): PopupWindow on the live host.
    internal interface ITrayPopup
    {
        bool Visible { get; }
        bool Attention();
        void OnSelect(bool keyboard);
        void OnDoubleClick();
        void Show();
        void Hide();
        void Destroy();
        void SetStrings(Dictionary<string, object> strings, string locale, string letters);
        void Snapshot(Dictionary<string, object> popup);
        void FollowSettings(Dictionary<string, object> values);
    }

    /// The icon's tooltip card (ui/tray/tipcard.py's TipCard): TipCard on the live host.
    internal interface ITrayTip
    {
        void Show(Func<int[]> icon, int[] point);
        void Hide(bool atOnce);
        void Destroy();
    }

    /// The drawn menu as the icon opens it (menuwindow.Menu): MenuWindow on the live host.
    internal interface ITrayMenu
    {
        bool Visible { get; }
        bool Open(List<object> items, Dictionary<string, object> strings, string locale, string letters, Action<object> chosen);
        void Destroy();
    }

    /// The notification cards as the icon hosts them (notice_window.CardStack): CardStack on the live host.
    internal interface ITrayCards
    {
        void Show(Dictionary<string, object> notice);
        void Destroy();
    }

    internal sealed partial class TrayIcon : IDisposable
    {
        // ------------------------------------------------------------------ win32.py's numbers
        internal const int WM_DESTROY = 0x0002, WM_CLOSE = 0x0010, WM_TIMER = 0x0113, WM_NULL = 0x0000;
        internal const int WM_WTSSESSION_CHANGE = 0x02B1;
        internal const int WTS_CONSOLE_CONNECT = 1, WTS_CONSOLE_DISCONNECT = 2, WTS_REMOTE_CONNECT = 3, WTS_REMOTE_DISCONNECT = 4;
        internal const int WTS_SESSION_LOCK = 7, WTS_SESSION_UNLOCK = 8, NOTIFY_FOR_THIS_SESSION = 0;
        internal const int WM_LBUTTONUP = 0x0202, WM_LBUTTONDBLCLK = 0x0203, WM_RBUTTONUP = 0x0205, WM_CONTEXTMENU = 0x007B;
        internal const int WM_USER = 0x0400, WM_APP = 0x8000;
        internal const int CALLBACK = WM_APP + 1, WM_TRAY_FRAMES = WM_APP + 2;
        internal const int TIMER_TICK = 1, TIMER_FRAME = 2, TIMER_TIP = 3;
        internal const int NIN_SELECT = WM_USER + 0, NIN_KEYSELECT = WM_USER + 1;
        internal const int NIN_POPUPOPEN = WM_USER + 6, NIN_POPUPCLOSE = WM_USER + 7;
        internal const int WM_MOUSEMOVE = 0x0200, WM_LBUTTONDOWN = 0x0201, WM_RBUTTONDOWN = 0x0204;
        internal const int NIM_ADD = 0, NIM_MODIFY = 1, NIM_DELETE = 2, NIM_SETVERSION = 4, NOTIFYICON_VERSION_4 = 4;
        internal const uint NIF_MESSAGE = 0x1, NIF_ICON = 0x2, NIF_TIP = 0x4, NIF_SHOWTIP = 0x80;
        internal const int IMAGE_ICON = 1, LR_LOADFROMFILE = 0x10, SM_CXSMICON = 49, SM_CYSMICON = 50, IDI_APPLICATION = 32512;
        /// icon.py: the shell's silence, timed (TIP_PROBE_S, TIP_EPISODE_GAP_S, TIP_SILENT_VISITS).
        internal const double TipProbeS = 2.0, TipEpisodeGapS = 1.0;
        internal const int TipSilentVisits = 2;
        /// animation.py's TRAY_FINE: ICON_MOTION tray_fine.
        internal const int TrayFine = TrayMotion.TrayFine;

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        private struct NOTIFYICONDATAW
        {
            internal uint CbSize;
            internal IntPtr HWnd;
            internal uint UID, UFlags, UCallbackMessage;
            internal IntPtr HIcon;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = TrayWords.TipChars)] internal string SzTip;
            internal uint DwState, DwStateMask;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 256)] internal string SzInfo;
            internal uint UVersion;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 64)] internal string SzInfoTitle;
            internal uint DwInfoFlags;
            internal Guid GuidItem;
            internal IntPtr HBalloonIcon;
        }

        [DllImport("shell32.dll", CharSet = CharSet.Unicode)] private static extern bool Shell_NotifyIconW(uint message, ref NOTIFYICONDATAW data);
        [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern IntPtr LoadImageW(IntPtr instance, string name, uint type, int cx, int cy, uint load);
        [DllImport("user32.dll")] private static extern IntPtr LoadIconW(IntPtr instance, IntPtr name);
        [DllImport("user32.dll")] private static extern int GetSystemMetrics(int index);
        [DllImport("wtsapi32.dll")] private static extern bool WTSRegisterSessionNotification(IntPtr hwnd, uint flags);
        [DllImport("wtsapi32.dll")] private static extern bool WTSUnRegisterSessionNotification(IntPtr hwnd);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode)] private static extern IntPtr CreateEventW(IntPtr attributes, bool manual, bool initial, string name);
        [DllImport("kernel32.dll")] private static extern uint WaitForSingleObject(IntPtr handle, uint ms);
        [DllImport("kernel32.dll")] private static extern bool CloseHandle(IntPtr handle);

        private static int made;

        // ------------------------------------------------------------------ what it is given (Tray.__init__)
        internal string IconPath;
        internal Dictionary<string, object> Strings = new Dictionary<string, object>();
        /// The catalog's locale and its letters: the core's words, the host having no catalogs.
        internal string Locale = "en", Letters = "";
        internal string Edition;
        internal bool Days;
        internal string DemoName;
        /// What a signalled demo event does (on_demo); null: no demo event is made, as the reference makes none without it.
        internal Action OnDemo;
        /// Where its actions go (the pump's); null: no popup, nothing posted (the reference without a control layer).
        internal IHostActions Actions;
        /// Whether the menu offers what is waiting (bool(on_pending)), and the Open Dashboard / Stop / switch it acts on.
        internal bool Pending = true;
        internal Action<string> Log = unused => { };
        /// How a post or the frame table's building runs off the UI thread (a pool thread on the live host).
        internal Action<Action> Worker = work => ThreadPool.QueueUserWorkItem(unused => work());
        /// What happens where the reference's loop ended (PostQuitMessage): the surfaces' class posts `closed`.
        internal Action Ended = () => { };
        internal Func<double> Monotonic = TrayPlace.Monotonic;
        internal Func<double> Now = () => (DateTime.UtcNow - new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc)).TotalSeconds;
        /// time.perf_counter, which times the frame table's budget.
        internal Func<double> PerfCounter = () => System.Diagnostics.Stopwatch.GetTimestamp() / (double)System.Diagnostics.Stopwatch.Frequency;
        /// The core's answers (see the head): whether what the icon shows is unseen, and the armed power word.
        internal Func<Dictionary<string, object>, bool> FailureUnseen = snapshot => SnapshotTrue(snapshot, "failure_unseen");
        internal Func<Dictionary<string, object>, bool> UnconfirmedUnseen = snapshot => SnapshotTrue(snapshot, "unconfirmed_unseen");
        internal Func<string> PowerArmed;
        /// StoredMixin's two readings; nothing on the live host (the core's settings and strings events carry them).
        internal Action AdoptSettings = () => { };
        internal Action AdoptReduceMotion = () => { };
        /// Windows' answers, fields for the probe mode.
        internal Func<int[]> IconRectReader;
        internal Func<int[]> Cursor = () => { SurfaceNative.POINT spot; SurfaceNative.GetCursorPos(out spot); return new[] { spot.X, spot.Y }; };
        internal Func<bool> AskContrast = SurfaceTheme.HighContrast, AskReduced = SurfaceTheme.ReducedMotion;
        internal Func<bool> AskBatterySaver = () => TrayPlace.BatterySaver();
        internal Func<bool?> AskPlacement;
        internal Func<bool> AskOverflowOpen = () => TrayPlace.OverflowOpen();
        internal Func<int, int> Metric = GetSystemMetrics;
        /// The surfaces it makes (the probe hands its own).
        internal Func<ITrayPopup> MakePopup;
        internal Func<ITrayTip> MakeTip;
        /// How the icon's card is made when MakeTip is not set (icon.py: TipCard(content=, held=, log=, days=)): what it shows,
        /// whether the popup holds it still, the log and whether it looks at the date, handed in as the reference hands them,
        /// so a probe can answer the making and see what it was made with (S6.3e). The live icon's: TipCard, attached to
        /// SurfaceAccess, as its ITrayTip.
        internal Func<Func<TipCard.Content>, Func<bool>, Action<string>, bool, ITrayTip> MakeTipCard = MakeLiveTip;
        internal Func<ITrayMenu> MakeMenu;
        internal Func<ITrayCards> MakeCards;
        /// Whether it hosts the notification cards (an inbox was given).
        internal bool Inbox;

        // ------------------------------------------------------------------ its state
        private Dictionary<string, object> snapshot = new Dictionary<string, object>();
        private readonly object guard = new object();
        internal IntPtr Hwnd;
        private SurfaceNative.WndProc proc;
        private string className;
        private IntPtr icon;
        private bool iconOwned;
        internal bool Failed, Unconfirmed;
        private IntPtr shownIcon;
        internal string LastTip;
        private uint taskbarCreated;
        internal bool Version4;
        internal ITrayPopup Popup;
        internal bool PopupFailed;
        internal int MenuMode = AppModeDefault;
        internal bool MenuTheming = true;
        /// The drawn menu: null until the first right click, Broken once it could not be made or shown.
        internal ITrayMenu MenuDrawn;
        internal bool MenuBroken;
        internal IconFrames Frames;
        internal bool FramesBroken;
        private object[] framesResult;                 // (frames or null, reason) the building left
        private bool framesPending;
        private IntPtr frameIcon;
        internal string FrameKey;
        internal string IconState;
        internal double StateSince, Epoch;
        internal bool MotionAllowed;
        internal int? MotionMs;
        internal bool SessionLocked, SessionAway;
        private bool sessionWatch;
        private IconPlacement placement;
        internal ITrayCards Cards;
        private IntPtr demo;
        internal ITrayTip Tip;
        internal bool TipBroken;
        internal bool TipHeard;
        internal double[] TipMoves;
        internal int TipSilent;
        internal bool TipFallback;
        /// The names the probe's record gives the icons it is shown with.
        private readonly Dictionary<long, string> iconNames = new Dictionary<long, string>();
        private int iconsMade;

        internal TrayIcon()
        {
            StateSince = Epoch = TrayPlace.Monotonic();
            IconRectReader = () => SurfaceNative.IconRect(Hwnd, 1);
            PowerArmed = () => PowerWord(SurfaceRender.Field(Shown(), "power_armed"));
            AskPlacement = () =>
            {
                if (placement == null) placement = new IconPlacement();
                return placement.Overflowed();
            };
        }

        private static bool SnapshotTrue(Dictionary<string, object> snapshot, string key)
        {
            object value;
            return snapshot != null && snapshot.TryGetValue(key, out value) && value is bool && (bool)value;
        }

        // ------------------------------------------------------------------ public
        /// update: the last tick's snapshot (and the popup's view, which the popup takes at once).
        internal void Update(Dictionary<string, object> value, Dictionary<string, object> popupView = null)
        {
            lock (guard) snapshot = value != null ? new Dictionary<string, object>(value) : new Dictionary<string, object>();
            if (popupView != null && Popup != null) Popup.Snapshot(popupView);
        }

        /// set_strings: a new vocabulary, after the Interface language changed.
        internal void SetStrings(Dictionary<string, object> strings, string locale, string letters)
        {
            lock (guard)
            {
                Strings = strings != null ? new Dictionary<string, object>(strings) : new Dictionary<string, object>();
                Locale = string.IsNullOrEmpty(locale) ? "en" : locale;
                Letters = letters ?? "";
                LastTip = null;
            }
            ITrayPopup popup = Popup;
            if (popup != null) popup.SetStrings(Strings, Locale, Letters);
        }

        /// stop: the window told to close; its WM_DESTROY takes everything down and calls `Ended`.
        internal void Stop()
        {
            if (Hwnd != IntPtr.Zero) SurfaceScreen.Post(Hwnd, WM_CLOSE, 0, 0);
        }

        public void Dispose()
        {
            if (Hwnd != IntPtr.Zero) SurfaceNative.DestroyWindow(Hwnd);
        }

        // ------------------------------------------------------------------ window
        /// _create: the class, the hidden top-level window (only a real one hears TaskbarCreated), the icon added, the
        /// version asked, the cards hosted, the demo event, the tick, the session watch, the frames built off the thread.
        internal void Create()
        {
            IntPtr instance = SurfaceNative.GetModuleHandleW(null);
            proc = WindowProc;
            var klass = new SurfaceNative.WNDCLASSW { LpfnWndProc = proc, HInstance = instance };
            className = "CodexAutoResumeTray-" + System.Diagnostics.Process.GetCurrentProcess().Id + "-" + Interlocked.Increment(ref made);
            klass.LpszClassName = className;
            if (SurfaceNative.RegisterClassW(ref klass) == 0)
            {
                className = null;
                throw new InvalidOperationException("RegisterClassW");
            }
            Hwnd = SurfaceNative.CreateWindowExW(0, className, "Codex Auto Resume", 0, 0, 0, 0, 0, IntPtr.Zero, IntPtr.Zero, instance,
                                                 IntPtr.Zero);
            if (Hwnd == IntPtr.Zero) throw new InvalidOperationException("CreateWindowExW");
            taskbarCreated = SurfaceNative.RegisterWindowMessageW("TaskbarCreated");
            icon = LoadIcon();
            shownIcon = icon;
            Notify(NIM_ADD);
            SetVersion();
            HostCards();
            demo = OpenDemo();
            SurfaceScreen.SetTimer(Hwnd, TIMER_TICK, 1000);
            WatchSession();
            if (iconOwned) BuildFramesLater(Metric(SM_CXSMICON));
        }

        /// The message the shell sends when Explorer starts again (the probe sends it by this number).
        internal uint TaskbarCreated { get { return taskbarCreated; } }

        /// Where the reference's loop ended: the class freed so the next icon can register.
        internal void Unregister()
        {
            if (className == null) return;
            SurfaceNative.UnregisterClassW(className, SurfaceNative.GetModuleHandleW(null));
            className = null;
        }

        private IntPtr OpenDemo()
        {
            if (string.IsNullOrEmpty(DemoName) || OnDemo == null) return IntPtr.Zero;
            try
            {
                if (SurfaceScreen.Probing)
                {
                    SurfaceScreen.Record("CreateEventW", DemoName);
                    return new IntPtr(0xDE);
                }
                // win/sync.py DemoEvent: the auto-reset event this icon makes for its state folder; the core names it
                // (car-platform's watcher_names(state_dir).demo), the host having no Path.home().resolve().
                if (!DemoName.StartsWith("Local\\", StringComparison.Ordinal)) throw new ArgumentException("not an event's name");
                IntPtr handle = CreateEventW(IntPtr.Zero, false, false, DemoName);
                if (handle == IntPtr.Zero) throw new System.ComponentModel.Win32Exception();
                return handle;
            }
            catch (Exception exc)
            {
                Log("demo unavailable (" + TipCard.PythonName(exc) + ")");
                return IntPtr.Zero;
            }
        }

        /// Whether the demo event was signalled since the last look, which resets it (DemoEvent.taken); the probe's answer
        /// is `DemoTaken`.
        internal Func<bool> DemoTaken;

        private void LookForDemo()
        {
            if (demo == IntPtr.Zero) return;
            bool taken = DemoTaken != null ? DemoTaken() : WaitForSingleObject(demo, 0) == 0;
            if (!taken) return;
            try
            {
                OnDemo();
            }
            catch (Exception exc)
            {
                Log("demo failed (" + TipCard.PythonName(exc) + ")");
            }
        }

        private string NameOf(IntPtr handle)
        {
            if (handle == IntPtr.Zero) return "None";
            string name;
            return iconNames.TryGetValue(handle.ToInt64(), out name) ? name : "0x" + handle.ToInt64().ToString("x");
        }

        private IntPtr LoadIcon()
        {
            int width = Metric(SM_CXSMICON), height = Metric(SM_CYSMICON);
            if (!string.IsNullOrEmpty(IconPath) && File.Exists(IconPath))
            {
                IntPtr handle;
                if (SurfaceScreen.Probing)
                {
                    SurfaceScreen.Record("LoadImageW", width, height);
                    handle = new IntPtr(0x1C0);
                }
                else handle = LoadImageW(IntPtr.Zero, IconPath, IMAGE_ICON, width, height, LR_LOADFROMFILE);
                if (handle != IntPtr.Zero)
                {
                    iconOwned = true;
                    iconNames[handle.ToInt64()] = "ico";
                    return handle;
                }
            }
            iconOwned = false;
            IntPtr shared = SurfaceScreen.Probing ? new IntPtr(0x1A0) : LoadIconW(IntPtr.Zero, new IntPtr(IDI_APPLICATION));
            iconNames[shared.ToInt64()] = "app";
            return shared;
        }

        private IntPtr MakeIcon(byte[] pixels, int size)
        {
            string name = "frame" + (++iconsMade);
            IntPtr handle;
            if (SurfaceScreen.Probing)
            {
                using (var sha = SHA256.Create())
                    SurfaceScreen.Record("CreateIconIndirect", name, BitConverter.ToString(sha.ComputeHash(pixels)).Replace("-", "").ToLowerInvariant());
                handle = new IntPtr(0x2000 + iconsMade);
            }
            else handle = SurfaceNative.IconFromPixels(pixels, size, size);
            if (handle != IntPtr.Zero) iconNames[handle.ToInt64()] = name;
            return handle;
        }

        private void DestroyIcon(IntPtr handle)
        {
            if (SurfaceScreen.Probing) SurfaceScreen.Record("DestroyIcon", NameOf(handle));
            else SurfaceNative.DestroyIcon(handle);
        }

        /// _shown: the last tick's snapshot as the icon shows it, with whether a failure nobody has seen is on it.
        internal Dictionary<string, object> Shown()
        {
            Dictionary<string, object> shown;
            lock (guard) shown = new Dictionary<string, object>(snapshot);
            shown["failed"] = Failed;
            shown["unconfirmed"] = Unconfirmed;
            return shown;
        }

        private bool Shell(int action, uint flags, string tip, uint version = 0)
        {
            if (SurfaceScreen.Probing)
            {
                if (action == NIM_SETVERSION) SurfaceScreen.Record("Shell_NotifyIconW", action, version);
                else if (action == NIM_DELETE) SurfaceScreen.Record("Shell_NotifyIconW", action);
                else SurfaceScreen.Record("Shell_NotifyIconW", action, flags, NameOf(shownIcon != IntPtr.Zero ? shownIcon : icon),
                                          tip == null ? "None" : tip.Replace("\n", "\\n"));
                return ShellAnswer == null || ShellAnswer(action);
            }
            var data = new NOTIFYICONDATAW { HWnd = Hwnd, UID = 1, UFlags = flags };
            data.CbSize = (uint)Marshal.SizeOf(typeof(NOTIFYICONDATAW));
            if (action == NIM_SETVERSION) data.UVersion = version;
            else if (action != NIM_DELETE)
            {
                data.UCallbackMessage = CALLBACK;
                data.HIcon = shownIcon != IntPtr.Zero ? shownIcon : icon;
                data.SzTip = tip;
            }
            return Shell_NotifyIconW((uint)action, ref data);
        }

        /// What the probe's shell answers each action (null: yes to every one).
        internal Func<int, bool> ShellAnswer;

        /// _notify: the icon, its message and its whole tooltip; NIF_SHOWTIP only while the icon's own card cannot show.
        private bool Notify(int action)
        {
            uint flags = NIF_MESSAGE | NIF_ICON | NIF_TIP | (TipShows() ? 0u : NIF_SHOWTIP);
            string tip;
            lock (guard) tip = TrayWords.Tooltip(Shown(), Strings, Now(), Edition);
            // szTip as the shell holds it: what the structure keeps of the text (TIP_CHARS - 1 characters).
            string held = tip.Length >= TrayWords.TipChars ? tip.Substring(0, TrayWords.TipChars - 1) : tip;
            int nul = held.IndexOf('\0');
            if (nul >= 0) held = held.Substring(0, nul);
            LastTip = held;
            return Shell(action, flags, tip);
        }

        private void SetVersion()
        {
            Version4 = Shell(NIM_SETVERSION, 0, null, NOTIFYICON_VERSION_4);
            if (TipShows()) Notify(NIM_MODIFY);
        }

        // ------------------------------------------------------------------ the tooltip card (v0.6.24)
        internal bool TipShows()
        {
            return Version4 && !TipBroken && !TipFallback;
        }

        private TipCard.Content TipContent()
        {
            Dictionary<string, object> strings;
            string locale, letters;
            lock (guard)
            {
                strings = new Dictionary<string, object>(Strings);
                locale = Locale;
                letters = Letters;
            }
            Dictionary<string, object> shown = Shown();
            return new TipCard.Content { Parts = TrayWords.TooltipParts(shown, strings, Now(), Edition), Snapshot = shown,
                                         Strings = strings, Locale = locale, Letters = letters };
        }

        private void ShowTip(long wparam)
        {
            TipHeard = true;
            TipMoves = null;
            TipSilent = 0;
            if (Hwnd != IntPtr.Zero) SurfaceScreen.KillTimer(Hwnd, TIMER_TIP);
            if (TipFallback)
            {
                TipFallback = false;
                Notify(NIM_MODIFY);
            }
            if (!TipShows()) return;
            ITrayPopup popup = Popup;
            if ((popup != null && popup.Visible) || (MenuDrawn != null && MenuDrawn.Visible)) return;
            int[] point = { (short)(wparam & 0xFFFF), (short)((wparam >> 16) & 0xFFFF) };
            try
            {
                if (Tip == null)
                {
                    if (MakeTip != null) Tip = MakeTip();
                    else Tip = MakeTipCard(TipContent, PopupHeld, Log, Days);
                }
                Tip.Show(IconRectReader, point);
            }
            catch (Exception exc)
            {
                TipGone("tray tip card unavailable (" + TipCard.PythonName(exc) + ")");
            }
        }

        internal void HideTip(bool atOnce = true)
        {
            ITrayTip tip = Tip;
            if (tip == null || TipBroken) return;
            try
            {
                tip.Hide(atOnce);
            }
            catch (Exception exc)
            {
                TipGone("tray tip card failed (" + TipCard.PythonName(exc) + ")");
            }
        }

        private void TipMoved()
        {
            if (TipHeard || !TipShows() || Hwnd == IntPtr.Zero) return;
            double now = Monotonic();
            if (TipMoves == null)
            {
                TipMoves = new[] { now, now };
                SurfaceScreen.SetTimer(Hwnd, TIMER_TIP, (int)(TipProbeS * 1000));
            }
            else TipMoves = new[] { TipMoves[0], now };
        }

        private void TipProbe()
        {
            if (Hwnd != IntPtr.Zero) SurfaceScreen.KillTimer(Hwnd, TIMER_TIP);
            double[] moves = TipMoves;
            TipMoves = null;
            if (TipHeard || moves == null || !TipShows()) return;
            if (!(Monotonic() - moves[1] < TipEpisodeGapS || PointerOnIcon())) return;
            TipSilent += 1;
            if (TipSilent >= TipSilentVisits)
            {
                Log("tray tip card waits: no hover word from the shell, Windows' tooltip meanwhile");
                TipFallback = true;
                Notify(NIM_MODIFY);
            }
        }

        private bool PointerOnIcon()
        {
            int[] rect, spot;
            try
            {
                using (new SurfaceNative.PerMonitorDpi())
                {
                    rect = IconRectReader();
                    spot = Cursor();
                }
            }
            catch (Exception)
            {
                return false;
            }
            return rect != null && rect[0] <= spot[0] && spot[0] < rect[2] && rect[1] <= spot[1] && spot[1] < rect[3];
        }

        private void TipGone(string why)
        {
            Log(why);
            ITrayTip tip = Tip;
            Tip = null;
            TipBroken = true;
            if (tip != null)
            {
                try
                {
                    tip.Destroy();
                }
                catch (Exception)
                {
                }
            }
            if (Hwnd != IntPtr.Zero) Notify(NIM_MODIFY);
        }

        /// _refresh: the one-second tick - what is unseen, the tooltip, the frame - and the frame timer kept in step.
        internal void Refresh()
        {
            Dictionary<string, object> now;
            lock (guard) now = new Dictionary<string, object>(snapshot);
            Failed = Unseen(now, FailureUnseen);
            Unconfirmed = Unseen(now, UnconfirmedUnseen);
            now["failed"] = Failed;
            now["unconfirmed"] = Unconfirmed;
            string text;
            lock (guard) text = TrayWords.Tooltip(now, Strings, Now(), Edition);
            bool changed = false;
            var replaced = new List<IntPtr>();
            if (Frames != null)
            {
                FollowTheDay(Frames.Size);
                Observe(now);
                changed = FrameFor(Monotonic(), replaced);
            }
            if (text != LastTip || changed) Notify(NIM_MODIFY);
            foreach (IntPtr handle in replaced)
                if (handle != IntPtr.Zero) DestroyIcon(handle);
            SyncMotion();
        }

        /// clicks.py's _failure_unseen / _unconfirmed_unseen: no control layer, no failures, or one that cannot say: no.
        private bool Unseen(Dictionary<string, object> now, Func<Dictionary<string, object>, bool> ask)
        {
            if (Actions == null || !SurfaceMath.Truthy(SurfaceRender.Field(now, "failures"))) return false;
            try
            {
                return ask(now);
            }
            catch (Exception)
            {
                return false;
            }
        }

        private void WatchSession()
        {
            try
            {
                if (SurfaceScreen.Probing)
                {
                    SurfaceScreen.Record("WTSRegisterSessionNotification", Hwnd, NOTIFY_FOR_THIS_SESSION);
                    sessionWatch = true;
                }
                else sessionWatch = WTSRegisterSessionNotification(Hwnd, NOTIFY_FOR_THIS_SESSION);
            }
            catch (Exception)
            {
                sessionWatch = false;
            }
        }

        private void SessionChanged(long change)
        {
            if (change == WTS_SESSION_LOCK) SessionLocked = true;
            else if (change == WTS_SESSION_UNLOCK) SessionLocked = false;
            else if (change == WTS_CONSOLE_DISCONNECT || change == WTS_REMOTE_DISCONNECT) SessionAway = true;
            else if (change == WTS_CONSOLE_CONNECT || change == WTS_REMOTE_CONNECT) SessionAway = false;
            else return;
            if (SessionLocked || SessionAway) HideTip();
            Refresh();
        }

        // ------------------------------------------------------------------ clicks.py
        private ITrayPopup PopupForClick()
        {
            if (Actions == null || PopupFailed) return null;
            if (Popup == null)
            {
                if (MakePopup != null) Popup = MakePopup();
                else
                {
                    Dictionary<string, object> strings;
                    string locale, letters;
                    lock (guard)
                    {
                        strings = new Dictionary<string, object>(Strings);
                        locale = Locale;
                        letters = Letters;
                    }
                    var window = new PopupWindow(strings, locale, letters, Days, PopupHeld)
                    {
                        Log = Log, Actions = Actions, Worker = Worker, Anchor = IconRectReader, ThemeMenu = ThemeMenu,
                        MakeMenu = () => Accessible(new MenuWindow(Log)),
                    };
                    SurfaceAccess.Attach(window);
                    Popup = new PopupSurface(window);
                }
            }
            return Popup;
        }

        private void PopupBroke(Exception exc)
        {
            Log("tray popup unavailable (" + TipCard.PythonName(exc) + ")");
            PopupFailed = true;
            ITrayPopup popup = Popup;
            Popup = null;
            if (popup != null)
            {
                try
                {
                    popup.Destroy();
                }
                catch (Exception)
                {
                }
            }
        }

        private void Select(bool keyboard = false)
        {
            HideTip();
            AdoptSettings();
            ITrayPopup popup = PopupForClick();
            if (popup == null) return;
            try
            {
                popup.OnSelect(keyboard);
            }
            catch (Exception exc)
            {
                PopupBroke(exc);
                return;
            }
            FailureSeen();
        }

        internal bool PopupCanOpen()
        {
            return Actions != null && !PopupFailed;
        }

        private void OpenPopup()
        {
            HideTip();
            AdoptSettings();
            ITrayPopup popup = PopupForClick();
            if (popup == null) return;
            try
            {
                popup.Show();
            }
            catch (Exception exc)
            {
                PopupBroke(exc);
                return;
            }
            FailureSeen();
        }

        /// _failure_seen: a click that opened the popup has seen the failure the icon shows; the icon goes back now.
        private void FailureSeen()
        {
            if (!(Failed || Unconfirmed) || Actions == null) return;
            Post(HostActions.FailureSeen, new Dictionary<string, object>());
            Refresh();
        }

        private void DoubleClick()
        {
            HideTip();
            AdoptSettings();
            ITrayPopup popup = PopupForClick();
            if (popup == null)
            {
                Act(MenuOpen, false);
                return;
            }
            try
            {
                popup.OnDoubleClick();
            }
            catch (Exception exc)
            {
                PopupBroke(exc);
            }
        }

        internal void HidePopup()
        {
            if (Popup == null) return;
            try
            {
                Popup.Hide();
            }
            catch (Exception exc)
            {
                PopupBroke(exc);
            }
        }

        /// One action, posted off the UI thread (a click's answer is the next snapshot).
        private void Post(string action, Dictionary<string, object> fields)
        {
            IHostActions actions = Actions;
            if (actions == null) return;
            Worker(new PostWork
            {
                Body = () =>
                {
                    try
                    {
                        actions.Post(action, fields);
                    }
                    catch (Exception exc)
                    {
                        Log("tray action failed (" + TipCard.PythonName(exc) + ")");
                    }
                },
            }.Run);
        }

        private sealed class PostWork
        {
            internal Action Body;
            internal void Run() { Body(); }
        }

        /// Whether a job handed to `Worker` is a post (the probe runs those within the step that made them).
        internal static bool IsPost(Action job)
        {
            return job.Target is PostWork;
        }

        // ------------------------------------------------------------------ cards.py
        private void HostCards()
        {
            if (!Inbox) return;
            try
            {
                if (MakeCards != null) Cards = MakeCards();
                else
                {
                    var stack = new CardStack { Log = Log, Anchor = IconRectReader, Actions = Actions, Worker = Worker, Appearance = CardLook };
                    Cards = new CardsSurface(stack.Create());
                }
                Post(HostActions.CardsAttached, new Dictionary<string, object>());
            }
            catch (Exception exc)
            {
                Cards = null;
                Log("notification card unavailable (" + TipCard.PythonName(exc) + ")");
            }
        }

        /// _card_look: the stored look, as the popup and the menu take it up, then Windows' answers; the day, if one.
        private Dictionary<string, object> CardLook()
        {
            AdoptSettings();
            Dictionary<string, object> drawn = CardStack.Look();
            string day = Days ? TipCard.DayLookAt(Now()) : null;
            if (!string.IsNullOrEmpty(day)) drawn["day"] = day;
            return drawn;
        }

        private void DropCards()
        {
            ITrayCards cards = Cards;
            Cards = null;
            if (cards == null) return;
            try
            {
                cards.Destroy();
            }
            catch (Exception exc)
            {
                Log("notification card cleanup failed (" + TipCard.PythonName(exc) + ")");
            }
            Post(HostActions.CardsDetached, new Dictionary<string, object>());
        }

        // ------------------------------------------------------------------ animation.py
        private string DayLook()
        {
            if (!Days) return null;
            if (AskContrast()) return null;
            return TipCard.DayLookAt(Now());
        }

        private void FollowTheDay(int size)
        {
            string look = DayLook();
            if (Frames != null && look != Frames.Look && framesResult == null && !framesPending) BuildFramesLater(size);
        }

        private void BuildFramesLater(int size)
        {
            string look = DayLook();
            framesPending = true;
            Worker(() =>
            {
                object[] result;
                try
                {
                    double started = PerfCounter();
                    var frames = new IconFrames(size, TrayFine, look);
                    if ((PerfCounter() - started) * 1000.0 > TrayMotion.BuildBudgetMs) frames = null;
                    result = new object[] { frames, frames == null ? "over its time budget" : null };
                }
                catch (Exception exc)
                {
                    result = new object[] { null, TipCard.PythonName(exc) };
                }
                lock (guard) framesResult = result;
                IntPtr hwnd = Hwnd;
                if (hwnd != IntPtr.Zero) SurfaceScreen.Post(hwnd, WM_TRAY_FRAMES, 0, 0);
            });
        }

        private void FramesBuilt()
        {
            object[] result;
            lock (guard)
            {
                result = framesResult;
                framesResult = null;
            }
            framesPending = false;
            if (result == null || icon == IntPtr.Zero) return;
            var frames = result[0] as IconFrames;
            if (frames == null)
            {
                Frames = null;
                FramesBroken = true;
                Log("tray motion unavailable (" + result[1] + ")");
                return;
            }
            Frames = frames;
            Refresh();
        }

        private void Observe(Dictionary<string, object> now)
        {
            bool attention = Popup != null && Popup.Visible && Popup.Attention();
            string state = SurfaceMath.Truthy(SurfaceRender.Field(now, "failed")) && now["failed"] is bool && (bool)now["failed"]
                ? "failed" : TrayMotion.ForLight(TipCard.SnapshotActivity(now, Now(), attention));
            double moment = Monotonic();
            if (state != IconState)
            {
                IconState = state;
                StateSince = moment;
            }
            bool allowed = false;
            if (TrayMotion.FrameMs(state, (moment - Epoch) * 1000.0).HasValue)
            {
                AdoptReduceMotion();
                allowed = TrayMotion.MotionAllowed(reduced: AskReduced(), contrast: AskContrast(), batterySaver: AskBatterySaver(),
                                                   locked: SessionLocked || SessionAway, frames: Frames != null);
                if (allowed) allowed = !Overflowed() && IconRectReader() != null;
            }
            MotionAllowed = allowed;
        }

        /// _popup_held: battery saver or a locked or disconnected session holds the popup's and the tip's motion.
        internal bool PopupHeld()
        {
            return !TrayMotion.MotionAllowed(batterySaver: AskBatterySaver(), locked: SessionLocked || SessionAway);
        }

        private bool Overflowed()
        {
            return AskPlacement() == true && !AskOverflowOpen();
        }

        /// _frame_for: the frame this moment wants; true when it changed, with the icons to destroy once shown.
        private bool FrameFor(double now, List<IntPtr> replaced)
        {
            IconFrames frames = Frames;
            if (frames == null) return false;
            string state = IconState ?? "watching";
            double elapsed = (now - Epoch) * 1000.0;
            int[] frame = TrayMotion.Frame(state, elapsed, !MotionAllowed, frames.Fine);
            int[] head = TrayMotion.LevelColour(TrayMotion.HeadColour(state), frame[1]);
            string key = frame[0] + ":" + string.Join(",", head);
            if (key == FrameKey && frameIcon != IntPtr.Zero) return false;
            IntPtr madeIcon;
            try
            {
                byte[] pixels = frames.Compose(frame[0], head);
                madeIcon = MakeIcon(pixels, frames.Size);
                if (madeIcon == IntPtr.Zero) throw new InvalidOperationException("CreateIconIndirect");
            }
            catch (Exception exc)
            {
                Log("tray motion failed (" + TipCard.PythonName(exc) + ")");
                Frames = null;
                FramesBroken = true;
                FrameKey = null;
                replaced.Add(frameIcon);
                frameIcon = IntPtr.Zero;
                shownIcon = icon;
                return true;
            }
            replaced.Add(frameIcon);
            frameIcon = madeIcon;
            FrameKey = key;
            shownIcon = madeIcon;
            return true;
        }

        private void Animate()
        {
            var replaced = new List<IntPtr>();
            if (FrameFor(Monotonic(), replaced)) NotifyIcon();
            foreach (IntPtr handle in replaced)
                if (handle != IntPtr.Zero) DestroyIcon(handle);
            SyncMotion();
        }

        /// _notify_icon: NIM_MODIFY with the icon alone.
        private bool NotifyIcon()
        {
            if (SurfaceScreen.Probing)
            {
                SurfaceScreen.Record("Shell_NotifyIconW", NIM_MODIFY, NIF_ICON, NameOf(shownIcon != IntPtr.Zero ? shownIcon : icon));
                return ShellAnswer == null || ShellAnswer(NIM_MODIFY);
            }
            var data = new NOTIFYICONDATAW { HWnd = Hwnd, UID = 1, UFlags = NIF_ICON, HIcon = shownIcon != IntPtr.Zero ? shownIcon : icon };
            data.CbSize = (uint)Marshal.SizeOf(typeof(NOTIFYICONDATAW));
            return Shell_NotifyIconW(NIM_MODIFY, ref data);
        }

        private void SyncMotion()
        {
            int? interval = null;
            if (Frames != null && MotionAllowed && IconState != null)
            {
                double now = Monotonic();
                double? due = TrayMotion.FrameMs(IconState, (now - Epoch) * 1000.0, false, Frames.Fine);
                if (due.HasValue) interval = (int)due.Value;
            }
            if (interval == MotionMs) return;
            if (interval == null) SurfaceScreen.KillTimer(Hwnd, TIMER_FRAME);
            else SurfaceScreen.SetTimer(Hwnd, TIMER_FRAME, interval.Value);
            MotionMs = interval;
        }

        // ------------------------------------------------------------------ the window procedure (_wndproc)
        private IntPtr WindowProc(IntPtr hwnd, uint message, IntPtr wParam, IntPtr lParam)
        {
            IntPtr? answer = Message(hwnd, (int)message, wParam.ToInt64(), lParam.ToInt64());
            return answer.HasValue ? answer.Value : SurfaceNative.DefWindowProcW(hwnd, message, wParam, lParam);
        }

        /// One message, as _wndproc takes it: its answer, or null for Windows' default.
        internal IntPtr? Message(IntPtr hwnd, int message, long wParam, long lParam)
        {
            try
            {
                if (message == CALLBACK)
                {
                    long note = lParam & 0xFFFF;
                    if (Version4)
                    {
                        if (note == NIN_POPUPOPEN) ShowTip(wParam);
                        else if (note == NIN_POPUPCLOSE) HideTip(false);
                        else if (note == WM_MOUSEMOVE) TipMoved();
                        else if (note == WM_LBUTTONDOWN || note == WM_RBUTTONDOWN) HideTip();
                        else if (note == NIN_SELECT || note == NIN_KEYSELECT) Select(note == NIN_KEYSELECT);
                        else if (note == WM_LBUTTONDBLCLK) DoubleClick();
                        else if (note == WM_CONTEXTMENU)
                        {
                            HidePopup();
                            Menu();
                        }
                    }
                    else
                    {
                        if (note == WM_RBUTTONUP || note == WM_CONTEXTMENU)
                        {
                            HidePopup();
                            Menu();
                        }
                        else if (note == WM_LBUTTONUP) Select();
                        else if (note == WM_LBUTTONDBLCLK) DoubleClick();
                    }
                    return IntPtr.Zero;
                }
                if (message == WM_TIMER)
                {
                    if (wParam == TIMER_TIP) TipProbe();
                    else if (wParam == TIMER_FRAME) Animate();
                    else
                    {
                        Refresh();
                        LookForDemo();
                    }
                    return IntPtr.Zero;
                }
                if (message == WM_TRAY_FRAMES)
                {
                    FramesBuilt();
                    return IntPtr.Zero;
                }
                if (message == WM_WTSSESSION_CHANGE)
                {
                    SessionChanged(wParam);
                    return IntPtr.Zero;
                }
                if (taskbarCreated != 0 && (uint)message == taskbarCreated)
                {
                    HideTip();
                    HidePopup();
                    Notify(NIM_ADD);
                    SetVersion();
                    return IntPtr.Zero;
                }
                if (message == WM_CLOSE)
                {
                    if (SurfaceScreen.Probing) SurfaceScreen.Record("DestroyWindow", hwnd);
                    else SurfaceNative.DestroyWindow(hwnd);
                    return IntPtr.Zero;
                }
                if (message == WM_DESTROY)
                {
                    Destroyed(hwnd);
                    return IntPtr.Zero;
                }
            }
            catch (Exception exc)
            {
                Log("tray message failed (" + TipCard.PythonName(exc) + ")");
                return IntPtr.Zero;
            }
            return null;
        }

        private void Destroyed(IntPtr hwnd)
        {
            SurfaceScreen.KillTimer(hwnd, TIMER_TICK);
            SurfaceScreen.KillTimer(hwnd, TIMER_FRAME);
            SurfaceScreen.KillTimer(hwnd, TIMER_TIP);
            MotionMs = null;
            if (sessionWatch)
            {
                try
                {
                    if (SurfaceScreen.Probing) SurfaceScreen.Record("WTSUnRegisterSessionNotification", hwnd);
                    else WTSUnRegisterSessionNotification(hwnd);
                }
                catch (Exception)
                {
                }
                sessionWatch = false;
            }
            DropCards();
            DropMenu();
            ITrayTip tip = Tip;
            Tip = null;
            if (tip != null)
            {
                try
                {
                    tip.Destroy();
                }
                catch (Exception exc)
                {
                    Log("tray tip card cleanup failed (" + TipCard.PythonName(exc) + ")");
                }
            }
            IntPtr demoEvent = demo;
            demo = IntPtr.Zero;
            if (demoEvent != IntPtr.Zero)
            {
                if (SurfaceScreen.Probing) SurfaceScreen.Record("CloseHandle", DemoName);
                else CloseHandle(demoEvent);
            }
            ITrayPopup popup = Popup;
            Popup = null;
            if (popup != null)
            {
                try
                {
                    popup.Destroy();
                }
                catch (Exception exc)
                {
                    Log("tray popup cleanup failed (" + TipCard.PythonName(exc) + ")");
                }
            }
            Shell(NIM_DELETE, 0, null);
            if (frameIcon != IntPtr.Zero)
            {
                DestroyIcon(frameIcon);
                frameIcon = IntPtr.Zero;
                FrameKey = null;
            }
            if (icon != IntPtr.Zero && iconOwned) DestroyIcon(icon);
            icon = shownIcon = IntPtr.Zero;
            Hwnd = IntPtr.Zero;
            Ended();
        }

        /// A drawn menu with its screen reader's hooks filled (SurfaceAccess).
        private static MenuWindow Accessible(MenuWindow menu)
        {
            SurfaceAccess.Attach(menu);
            return menu;
        }

        /// The icon shown now, by the probe record's name.
        internal string ShownName { get { return NameOf(shownIcon != IntPtr.Zero ? shownIcon : icon); } }

        // ------------------------------------------------------------------ the live host's surfaces behind the interfaces
        private sealed class PopupSurface : ITrayPopup
        {
            private readonly PopupWindow window;
            internal PopupSurface(PopupWindow window) { this.window = window; }
            public bool Visible { get { return window.Visible; } }
            public bool Attention() { return window.Attention(); }
            public void OnSelect(bool keyboard) { window.OnSelect(keyboard); }
            public void OnDoubleClick() { window.OnDoubleClick(); }
            public void Show() { window.Show(); }
            public void Hide() { window.Hide(); }
            public void Destroy() { window.Dispose(); }
            public void SetStrings(Dictionary<string, object> strings, string locale, string letters) { window.SetStrings(strings, locale, letters); }
            public void Snapshot(Dictionary<string, object> popup) { window.Snapshot(popup); }
            public void FollowSettings(Dictionary<string, object> values) { window.FollowSettings(values); }
        }

        /// The live icon's card (MakeTipCard's default): a TipCard a screen reader can ask, as the icon's ITrayTip.
        private static ITrayTip MakeLiveTip(Func<TipCard.Content> content, Func<bool> held, Action<string> log, bool days)
        {
            var card = new TipCard(content, held, log, days);
            SurfaceAccess.Attach(card);
            return new TipSurface(card);
        }

        private sealed class TipSurface : ITrayTip
        {
            private readonly TipCard card;
            internal TipSurface(TipCard card) { this.card = card; }
            public void Show(Func<int[]> icon, int[] point) { card.Show(icon, point); }
            public void Hide(bool atOnce) { card.Hide(atOnce); }
            public void Destroy() { card.Dispose(); }
        }

        private sealed class CardsSurface : ITrayCards
        {
            private readonly CardStack stack;
            internal CardsSurface(CardStack stack) { this.stack = stack; }
            public void Show(Dictionary<string, object> notice) { stack.Show(notice); }
            public void Destroy() { stack.Dispose(); }
        }
    }
}
