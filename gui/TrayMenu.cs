// Codex Auto Resume - the icon's right-click menu: what it offers, the drawn menu, Windows' own as the fallback, and
// asking Windows to draw its own dark (v0.6.27, S6.3e).
//
// ui/tray/menu.py ported call for call, the other half of gui/TrayIcon.cs's partial class. What it offers is one list,
// MenuItems, and both ways of showing it are built from that list alone. The drawn menu (MenuWindow, ui/popup/menuwindow.py)
// is shown first; Windows' own (TrackPopupMenu) only where the reference shows it: no window of the icon's own, a drawn
// menu that broke (given up for the rest of the icon's life), or an opening Windows refused the drawn menu the foreground
// for. What is chosen is posted through IHostActions (toggle {paused}, stop, open_dashboard {page, row}, disarm_power), or
// opens the popup.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Runtime.InteropServices;

namespace CodexAutoResume
{
    internal sealed partial class TrayIcon
    {
        /// The command ids (MENU_*), the status line's, and the menu's flags.
        internal const int MenuStatus = 0, MenuOpen = 1, MenuToggle = 2, MenuStop = 3, MenuPending = 4, MenuPowerOff = 5, MenuPopup = 6;
        internal const uint MF_STRING = 0x0, MF_GRAYED = 0x1, MF_CHECKED = 0x8, MF_SEPARATOR = 0x800;
        internal const uint TPM_RIGHTBUTTON = 0x2, TPM_RETURNCMD = 0x100, TPM_NONOTIFY = 0x80;
        /// uxtheme's preferred app mode, by ordinal (Default, ForceDark), and the first build that has it.
        internal const int AppModeDefault = 0, AppModeForceDark = 2;
        internal const int UxthemeSetPreferredAppMode = 135, UxthemeFlushMenuThemes = 136, DarkMenuBuild = 18362;

        /// POWER_OFF_WORDS: the armed power action's item, by its word.
        internal static readonly Dictionary<string, string> PowerOffWords = new Dictionary<string, string> {
            { "sleep", "Don't sleep after recoveries" }, { "hibernate", "Don't hibernate after recoveries" },
            { "shut_down", "Don't shut down after recoveries" } };

        /// Windows' app mode and what the probe's Windows answers (the menu's look; prefer_app_mode).
        internal Func<bool?> AskAppsLight = SurfaceTheme.AppsUseLightTheme;
        internal Func<int, bool> PreferAppModeCall = PreferAppMode;
        /// What Windows' own menu answers while probed (TrackPopupMenu's command; 0 for none).
        internal int NativeChoice;

        /// menu_items: what the menu offers, in order - a dictionary per item (id, text, enabled, checked) and null for
        /// a line between groups. Pure.
        internal static List<object> MenuItems(Dictionary<string, object> snapshot, Dictionary<string, object> strings, double now,
                                               bool pending = false, string armed = null, bool popup = false)
        {
            strings = strings ?? new Dictionary<string, object>();
            Func<int, string, bool, Dictionary<string, object>> item = (identifier, text, usable) =>
                new Dictionary<string, object> { { "id", identifier }, { "text", text }, { "enabled", usable }, { "checked", false } };
            string tip = TrayWords.Tooltip(snapshot, strings, now, null);
            int cut = tip.IndexOf('\n');
            string status = cut < 0 ? tip : tip.Substring(cut + 1);
            var items = new List<object> { item(MenuStatus, status, false), null, item(MenuOpen, Say(strings, "menu.open", "Open Dashboard"), true) };
            if (popup) items.Add(item(MenuPopup, Say(strings, "menu.open_popup", "Open the popup"), true));
            long waiting = Count(SurfaceRender.Field(snapshot, "waiting")) + Count(SurfaceRender.Field(snapshot, "running"));
            if (waiting != 0 && pending)
                items.Add(item(MenuPending, Say(strings, "menu.pending", "Show what is waiting ({n})")
                                                .Replace("{n}", waiting.ToString(CultureInfo.InvariantCulture)), true));
            object enabled;
            bool paused = !SurfaceMath.Truthy(snapshot.TryGetValue("enabled", out enabled) ? enabled : true);
            items.Add(item(MenuToggle, paused ? Say(strings, "menu.resume", "Resume recovery") : Say(strings, "menu.pause", "Pause recovery"), true));
            if (armed != null && PowerOffWords.ContainsKey(armed))
                items.Add(item(MenuPowerOff, Say(strings, "menu.power_off." + armed, PowerOffWords[armed]), true));
            items.Add(null);
            items.Add(item(MenuStop, Say(strings, "menu.stop", "Stop the watcher"), true));
            return items;
        }

        /// strings.get(key, default): the catalog's word as a string, or the default.
        private static string Say(Dictionary<string, object> strings, string key, string fallback)
        {
            object value;
            return strings.TryGetValue(key, out value) ? Convert.ToString(value, CultureInfo.InvariantCulture) : fallback;
        }

        /// int(value or 0), as the snapshot's numbers read.
        private static long Count(object value)
        {
            if (!SurfaceMath.Truthy(value)) return 0;
            if (value is bool) return (bool)value ? 1 : 0;
            if (value is double) return (long)(double)value;
            if (value is string) return long.Parse(((string)value).Trim(), CultureInfo.InvariantCulture);
            return Convert.ToInt64(value, CultureInfo.InvariantCulture);
        }

        /// menu_app_mode: dark only in dark.
        internal static int MenuAppMode(string look)
        {
            return look == "dark" ? AppModeForceDark : AppModeDefault;
        }

        [DllImport("ntdll.dll")] private static extern int RtlGetVersion(ref OSVERSIONINFOW info);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode)] private static extern IntPtr LoadLibraryW(string name);
        [DllImport("kernel32.dll")] private static extern IntPtr GetProcAddress(IntPtr module, IntPtr ordinal);
        [UnmanagedFunctionPointer(CallingConvention.Winapi)] private delegate int PreferredAppMode(int mode);
        [UnmanagedFunctionPointer(CallingConvention.Winapi)] private delegate void FlushMenuThemes();

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        private struct OSVERSIONINFOW
        {
            internal uint Size, Major, Minor, Build, Platform;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)] internal string ServicePack;
        }

        /// prefer_app_mode: ask Windows to draw this process's menus in `mode`; false where Windows cannot be asked.
        internal static bool PreferAppMode(int mode)
        {
            var version = new OSVERSIONINFOW();
            version.Size = (uint)Marshal.SizeOf(typeof(OSVERSIONINFOW));
            if (RtlGetVersion(ref version) != 0 || version.Build < DarkMenuBuild) return false;
            IntPtr uxtheme = LoadLibraryW("uxtheme.dll");
            if (uxtheme == IntPtr.Zero) throw new System.ComponentModel.Win32Exception();
            IntPtr prefer = GetProcAddress(uxtheme, new IntPtr(UxthemeSetPreferredAppMode));
            IntPtr flush = GetProcAddress(uxtheme, new IntPtr(UxthemeFlushMenuThemes));
            if (prefer == IntPtr.Zero || flush == IntPtr.Zero) throw new System.ComponentModel.Win32Exception();
            ((PreferredAppMode)Marshal.GetDelegateForFunctionPointer(prefer, typeof(PreferredAppMode)))(mode);
            ((FlushMenuThemes)Marshal.GetDelegateForFunctionPointer(flush, typeof(FlushMenuThemes)))();
            return true;
        }

        // ------------------------------------------------------------------ MenuMixin
        /// _menu: the tip goes, the stored language and look are taken up, the items built, drawn - or Windows' own.
        internal void Menu()
        {
            HideTip();
            AdoptSettings();
            ThemeMenu();
            Dictionary<string, object> shown = Shown();
            object enabled;
            bool paused = !SurfaceMath.Truthy(shown.TryGetValue("enabled", out enabled) ? enabled : true);
            List<object> items;
            lock (guard) items = MenuItems(shown, Strings, Now(), Pending, Armed(), PopupCanOpen());
            if (DrawMenu(items, paused)) return;
            Act(NativeMenu(items), paused);
        }

        private bool DrawMenu(List<object> items, bool paused)
        {
            if (Hwnd == IntPtr.Zero || MenuBroken) return false;
            try
            {
                if (MenuDrawn == null) MenuDrawn = MakeMenu != null ? MakeMenu() : new MenuSurface(Accessible(new MenuWindow(Log)));
                Dictionary<string, object> strings;
                string locale, letters;
                lock (guard)
                {
                    strings = new Dictionary<string, object>(Strings);
                    locale = Locale;
                    letters = Letters;
                }
                return MenuDrawn.Open(items, strings, locale, letters, chosen => Act(Convert.ToInt32(chosen, CultureInfo.InvariantCulture), paused));
            }
            catch (Exception exc)
            {
                Log("tray menu drawn unavailable (" + TipCard.PythonName(exc) + ")");
                DropMenu();
                MenuBroken = true;
                return false;
            }
        }

        private void DropMenu()
        {
            ITrayMenu menu = MenuDrawn;
            if (menu == null) return;
            MenuDrawn = null;
            try
            {
                menu.Destroy();
            }
            catch (Exception exc)
            {
                Log("tray menu cleanup failed (" + TipCard.PythonName(exc) + ")");
            }
        }

        /// _native_menu: Windows' own menu from the same items, at the pointer; the command chosen, or 0.
        private int NativeMenu(List<object> items)
        {
            IntPtr menu = SurfaceScreen.Probing ? new IntPtr(0x3E0) : SurfaceNative.CreatePopupMenu();
            int chosen;
            try
            {
                foreach (object entry in items)
                {
                    var item = entry as Dictionary<string, object>;
                    if (item == null)
                    {
                        Append(menu, MF_SEPARATOR, 0, null);
                        continue;
                    }
                    uint flags = MF_STRING | ((bool)item["enabled"] ? 0 : MF_GRAYED) | ((bool)item["checked"] ? MF_CHECKED : 0);
                    Append(menu, flags, (int)item["id"], (string)item["text"]);
                }
                int[] point = Cursor();
                // Without this the menu does not close when the user clicks elsewhere.
                SurfaceScreen.SetForegroundWindow(Hwnd);
                if (SurfaceScreen.Probing)
                {
                    SurfaceScreen.Record("TrackPopupMenu", TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY, point[0], point[1]);
                    chosen = NativeChoice;
                }
                else chosen = SurfaceNative.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY, point[0], point[1], 0,
                                                           Hwnd, IntPtr.Zero);
                SurfaceScreen.Post(Hwnd, WM_NULL, 0, 0);
            }
            finally
            {
                if (SurfaceScreen.Probing) SurfaceScreen.Record("DestroyMenu");
                else SurfaceNative.DestroyMenu(menu);
            }
            return chosen;
        }

        private static void Append(IntPtr menu, uint flags, int id, string text)
        {
            if (SurfaceScreen.Probing) SurfaceScreen.Record("AppendMenuW", flags, id, text == null ? "None" : text.Replace("\n", "\\n"));
            else SurfaceNative.AppendMenuW(menu, flags, new UIntPtr((uint)id), text);
        }

        /// _act: what was chosen, done; the core is told through one posted action.
        private void Act(int chosen, bool paused)
        {
            try
            {
                if (chosen == MenuToggle) Post(HostActions.Toggle, new Dictionary<string, object> { { "paused", paused } });
                else if (chosen == MenuPowerOff && Actions != null) Post(HostActions.DisarmPower, new Dictionary<string, object>());
                else if (chosen == MenuPopup) OpenPopup();
                else if (chosen == MenuOpen) Post(HostActions.OpenDashboard, new Dictionary<string, object> { { "page", null }, { "row", null } });
                else if (chosen == MenuStop) Post(HostActions.Stop, new Dictionary<string, object>());
                else if (chosen == MenuPending && Pending)
                    Post(HostActions.OpenDashboard, new Dictionary<string, object> { { "page", "pending" }, { "row", null } });
            }
            catch (Exception exc)
            {
                Log("tray action failed (" + TipCard.PythonName(exc) + ")");
            }
        }

        /// _power_armed: the armed power action's word, or null (no control layer, none armed, or one not read).
        private string Armed()
        {
            if (Actions == null || PowerArmed == null) return null;
            try
            {
                return PowerArmed();
            }
            catch (Exception)
            {
                return null;
            }
        }

        /// What power_view's `armed` names: its action, when it is one the menu can turn off.
        internal static string PowerWord(object armed)
        {
            var map = armed as Dictionary<string, object>;
            object action;
            if (map == null || !map.TryGetValue("action", out action)) return null;
            var word = action as string;
            return word != null && PowerOffWords.ContainsKey(word) ? word : null;
        }

        /// _theme_menu: a dark menu when the popup beside it is dark, Windows' own look otherwise; asked only on a change,
        /// and given up for good once Windows cannot be asked.
        internal void ThemeMenu()
        {
            if (!MenuTheming) return;
            try
            {
                string look = SurfaceTheme.Appearance(SurfaceTheme.ThemeSetting, AskAppsLight(), AskContrast());
                int mode = MenuAppMode(look);
                if (mode == MenuMode) return;
                bool asked;
                if (SurfaceScreen.Probing)
                {
                    SurfaceScreen.Record("SetPreferredAppMode", mode);
                    asked = PreferAppModeCall(mode);
                }
                else asked = PreferAppModeCall(mode);
                if (asked) MenuMode = mode;
                else MenuTheming = false;
            }
            catch (Exception exc)
            {
                MenuTheming = false;
                Log("tray menu theme failed (" + TipCard.PythonName(exc) + ")");
            }
        }

        private sealed class MenuSurface : ITrayMenu
        {
            private readonly MenuWindow menu;
            internal MenuSurface(MenuWindow menu) { this.menu = menu; }
            public bool Visible { get { return menu.Visible; } }
            public bool Open(List<object> items, Dictionary<string, object> strings, string locale, string letters, Action<object> chosen)
            {
                return menu.Open(items, strings, locale, letters, chosen);
            }
            public void Destroy() { menu.Destroy(); }
        }
    }
}
