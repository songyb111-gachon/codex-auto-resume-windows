"""The host's seams the UI tests wait for (v0.6.27, seat S6.3e): every Win32 call by which the popup's Windows row menu
and the icon's tooltip card reach the screen goes through gui/SurfaceScreen.cs, and the icon makes its card through a
seam that is handed what the card is made with.

* The popup's row menu, Windows' own (PopupWindow.ContextMenu's fallback half): CreatePopupMenu, AppendMenuW (a command,
  a line, a submenu), TrackPopupMenu and DestroyMenu. Probed, each is a line in SurfaceScreen.Probe and none is made;
  `SurfaceScreen.MenuChoice` answers what TrackPopupMenu chose. Compared call for call with the reference's
  `Popup._context_menu` over a recording user32, left to right, right to left and from the keyboard, and the action
  each choice posts with the one the reference ran. On the live path the menu is Windows' own: made, filled and read
  back through user32's own questions (GetMenuItemCount, GetMenuItemID, GetMenuState, GetMenuStringW, GetSubMenu) and
  destroyed with its submenu - never tracked here, since a tracked menu is on the screen; TrackPopupMenu's live line is
  read from the source.
* The tooltip card (TipCard): ShowWindow, SetWindowPos, UpdateLayeredWindow, SetTimer, KillTimer and what a screen reader
  is told (NotifyWinEvent, through SurfaceScreen.Tell). Probed, compared call for call with the reference's TipCard as
  test_tray_tipcard.CardStateTests drives it (a hide at once, a fade out and its end, a hide ending a fade on its way,
  the backstop, a suspend); on the live path over a message-only window of the driver's own (never on any screen): the
  timers Windows holds after each step, the window's WS_VISIBLE bit, and the events a WinEvent hook of the driver's own
  hears.
* The icon's card (TrayIcon.MakeTipCard): made once on the first rest with the icon's TipContent, PopupHeld, Log and
  Days, as icon.py makes TipCard(content=, held=, log=, days=); the live maker's TipCard is given exactly those and is
  attached to SurfaceAccess.

The C# is compiled with the in-box csc into a temporary folder with a driver of its own and run as a console program
with CREATE_NO_WINDOW. No window is shown, nothing is captured, no real menu is tracked.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

import guiscan  # noqa: E402

CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
CREATE_NO_WINDOW = 0x08000000
MENU_BASE = 0x3E0
MENU_CALLS = ("CreatePopupMenu", "AppendMenuW", "TrackPopupMenu", "DestroyMenu")
TIP_CALLS = ("ShowWindow", "SetTimer", "KillTimer", "NotifyWinEvent", "SetWindowPos", "UpdateLayeredWindow")

DRIVER = r"""
using System;
using System.Collections.Generic;
using System.Reflection;
using System.Runtime.InteropServices;

namespace CodexAutoResume
{
    internal static class HostSeamsDriver
    {
        [DllImport("user32.dll")] private static extern int GetMenuItemCount(IntPtr menu);
        [DllImport("user32.dll")] private static extern uint GetMenuItemID(IntPtr menu, int position);
        [DllImport("user32.dll")] private static extern uint GetMenuState(IntPtr menu, uint id, uint flags);
        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        private static extern int GetMenuStringW(IntPtr menu, uint id, System.Text.StringBuilder text, int max, uint flags);
        [DllImport("user32.dll")] private static extern IntPtr GetSubMenu(IntPtr menu, int position);
        [DllImport("user32.dll")] private static extern bool IsMenu(IntPtr menu);
        [DllImport("user32.dll")] private static extern int GetWindowLongW(IntPtr hwnd, int index);
        [DllImport("user32.dll")] private static extern bool KillTimer(IntPtr hwnd, UIntPtr id);
        [DllImport("user32.dll")] private static extern bool ShowWindow(IntPtr hwnd, int command);
        [DllImport("user32.dll")] private static extern bool DestroyWindow(IntPtr hwnd);
        [DllImport("user32.dll")] private static extern int GetCurrentThreadId();
        [DllImport("kernel32.dll", EntryPoint = "GetCurrentThreadId")] private static extern uint ThreadId();
        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        private static extern IntPtr CreateWindowExW(uint ex, string klass, string name, uint style, int x, int y, int w, int h,
                                                     IntPtr parent, IntPtr menu, IntPtr instance, IntPtr param);
        private delegate void WinEventProc(IntPtr hook, uint winEvent, IntPtr hwnd, int objectId, int childId, uint thread, uint time);
        [DllImport("user32.dll")]
        private static extern IntPtr SetWinEventHook(uint min, uint max, IntPtr module, WinEventProc proc, uint process, uint thread, uint flags);
        [DllImport("user32.dll")] private static extern bool UnhookWinEvent(IntPtr hook);
        [StructLayout(LayoutKind.Sequential)]
        private struct MSG { public IntPtr Hwnd; public uint Message; public IntPtr W; public IntPtr L; public uint Time; public int X, Y; }
        [DllImport("user32.dll")] private static extern bool PeekMessageW(out MSG msg, IntPtr hwnd, uint min, uint max, uint remove);
        [DllImport("user32.dll")] private static extern bool TranslateMessage(ref MSG msg);
        [DllImport("user32.dll")] private static extern IntPtr DispatchMessageW(ref MSG msg);

        private static int Main(string[] args)
        {
            var job = (Dictionary<string, object>)Json.Parse(System.IO.File.ReadAllText(args[0]));
            var answers = new List<object>();
            foreach (object one in (List<object>)job["cases"])
            {
                var task = (Dictionary<string, object>)one;
                object found;
                try
                {
                    string kind = (string)task["kind"];
                    if (kind == "row_menu") found = RowMenu(task);
                    else if (kind == "menu_real") found = MenuReal(task);
                    else if (kind == "tip_state") found = TipState(task);
                    else if (kind == "make_tip") found = MakeTip(task);
                    else if (kind == "make_tip_live") found = MakeTipLive(task);
                    else throw new ArgumentException("no case " + kind);
                }
                catch (Exception exc)
                {
                    found = new Dictionary<string, object> { { "error", exc.GetType().Name + ": " + exc.Message } };
                }
                answers.Add(found);
            }
            System.IO.File.WriteAllText(args[1], Json.Write(answers));
            return 0;
        }

        private static IntPtr Own()
        {
            IntPtr own = CreateWindowExW(0, "STATIC", "", 0, 0, 0, 0, 0, new IntPtr(-3), IntPtr.Zero, IntPtr.Zero, IntPtr.Zero);
            if (own == IntPtr.Zero) throw new InvalidOperationException("CreateWindowExW");
            return own;
        }

        private static int[] Ints(object value)
        {
            return ((List<object>)value).ConvertAll(each => (int)(double)each).ToArray();
        }

        private sealed class Posts : IHostActions
        {
            internal readonly List<object> Made = new List<object>();
            public string Post(string action, IDictionary<string, object> fields)
            {
                Made.Add(new List<object> { action, new Dictionary<string, object>(fields) });
                return "{\"ok\": true}";
            }
        }

        // ------------------------------------------------------------------ the popup's Windows row menu
        private static object RowMenu(Dictionary<string, object> task)
        {
            IntPtr own = Own();
            var record = new List<string>();
            List<string> saved = SurfaceScreen.Probe;
            Func<IntPtr, string> savedName = SurfaceScreen.Name;
            var tracked = new List<object>();
            var posts = new Posts();
            var logs = new List<object>();
            try
            {
                if ((bool)task["probe"]) SurfaceScreen.Probe = record;
                SurfaceScreen.NextMenu = 0x3E0;
                int choice = (int)(double)task["choice"];
                SurfaceScreen.MenuChoice = menu => { tracked.Add("0x" + menu.ToInt64().ToString("x")); return choice; };
                SurfaceScreen.Name = hwnd => hwnd == own ? "popup" : "0x" + hwnd.ToInt64().ToString("x");
                var popup = new PopupWindow((Dictionary<string, object>)task["strings"]) { Hwnd = own, Worker = work => work(),
                                                                                           Actions = posts };
                popup.Log = line => logs.Add(line);
                popup.Snapshot((Dictionary<string, object>)task["core"]);
                popup.View();
                var rows = new List<KeyValuePair<object, int[]>>();
                foreach (object entry in (List<object>)task["rows"])
                {
                    var pair = (List<object>)entry;
                    rows.Add(new KeyValuePair<object, int[]>(pair[0], Ints(pair[1])));
                }
                popup.PaintedPlan = new SurfacePlan { Rows = rows, Rtl = task["rtl"] as bool? };
                if (task["focus"] != null) popup.Focus = new SurfaceTarget("check", task["focus"]);
                MethodInfo context = typeof(PopupWindow).GetMethod("ContextMenu", BindingFlags.Instance | BindingFlags.NonPublic);
                context.Invoke(popup, new object[] { (long)(double)task["lparam"] });
            }
            finally
            {
                SurfaceScreen.Probe = saved;
                SurfaceScreen.Name = savedName;
                SurfaceScreen.MenuChoice = null;
                SurfaceScreen.Posted.Clear();
                DestroyWindow(own);
            }
            return new Dictionary<string, object> { { "record", new List<object>(record) }, { "tracked", tracked },
                                                    { "posts", posts.Made }, { "logs", logs } };
        }

        /// The live path: a menu made, filled and read back by user32's own questions, destroyed with its submenu; never tracked.
        private static object MenuReal(Dictionary<string, object> task)
        {
            if (SurfaceScreen.Probing) throw new InvalidOperationException("probing");
            IntPtr main = SurfaceScreen.CreatePopupMenu();
            IntPtr sub = SurfaceScreen.CreatePopupMenu();
            var read = new List<object>();
            bool mainGone, subGone;
            try
            {
                foreach (object entry in (List<object>)task["sub"])
                {
                    var item = (List<object>)entry;
                    SurfaceScreen.AppendMenu(sub, (uint)(double)item[0], (ulong)(double)item[1], item[2] as string);
                }
                foreach (object entry in (List<object>)task["main"])
                {
                    var item = (List<object>)entry;
                    if (item[1] == null) SurfaceScreen.AppendSubmenu(main, (uint)(double)item[0], sub, item[2] as string);
                    else SurfaceScreen.AppendMenu(main, (uint)(double)item[0], (ulong)(double)item[1], item[2] as string);
                }
                foreach (IntPtr menu in new[] { main, sub })
                {
                    var items = new List<object>();
                    int count = GetMenuItemCount(menu);
                    for (int at = 0; at < count; at++)
                    {
                        var text = new System.Text.StringBuilder(256);
                        GetMenuStringW(menu, (uint)at, text, 256, 0x400);
                        IntPtr below = GetSubMenu(menu, at);
                        items.Add(new List<object> { (double)GetMenuItemID(menu, at), (double)(GetMenuState(menu, (uint)at, 0x400) & 0xFFFF),
                                                     text.ToString(), below == IntPtr.Zero ? null : (object)(below == sub) });
                    }
                    read.Add(items);
                }
            }
            finally
            {
                SurfaceScreen.DestroyMenu(main);
                mainGone = !IsMenu(main);
                subGone = !IsMenu(sub);
            }
            return new Dictionary<string, object> { { "read", read }, { "main_gone", mainGone }, { "sub_gone", subGone } };
        }

        // ------------------------------------------------------------------ the tooltip card
        private static object TipState(Dictionary<string, object> task)
        {
            bool probe = (bool)task["probe"];
            IntPtr own = Own();
            var record = new List<string>();
            List<string> saved = SurfaceScreen.Probe;
            Func<IntPtr, string> savedName = SurfaceScreen.Name;
            var heard = new List<object>();
            var after = new List<object>();
            IntPtr hook = IntPtr.Zero;
            WinEventProc listen = (h, winEvent, hwnd, objectId, childId, thread, time) =>
            {
                if (hwnd == own) heard.Add(new List<object> { (double)winEvent, (double)objectId, (double)childId });
            };
            var tip = new TipCard(() => null) { Hwnd = own, OnScreen = false, Contrast = false };
            try
            {
                if (probe) SurfaceScreen.Probe = record;
                else hook = SetWinEventHook(0x8002, 0x8003, IntPtr.Zero, listen, (uint)System.Diagnostics.Process.GetCurrentProcess().Id,
                                            ThreadId(), 0);
                SurfaceScreen.Name = hwnd => hwnd == own ? "tip" : "0x" + hwnd.ToInt64().ToString("x");
                double clock = 0;
                int[] pointer = { 0, 0 };
                bool moves = true;
                tip.AskReduced = () => !moves;
                tip.AskContrast = () => false;
                tip.Pointer = () => pointer;
                tip.Monotonic = () => clock;
                MethodInfo proc = typeof(TipCard).GetMethod("WindowProc", BindingFlags.Instance | BindingFlags.NonPublic);
                foreach (object each in (List<object>)task["steps"])
                {
                    var step = (List<object>)each;
                    string what = (string)step[0];
                    object answer = null;
                    if (what == "visible") tip.Visible = (bool)step[1];
                    else if (what == "plan") tip.Plan = new SurfacePlan { Scale = (double)step[1], Size = Ints(step[2]) };
                    else if (what == "screen") tip.Screen = new TipCard.TipScreen { Box = Ints(step[1]) };
                    else if (what == "origin") tip.Origin = Ints(step[1]);
                    else if (what == "clock") clock = (double)step[1];
                    else if (what == "pointer") pointer = Ints(step[1]);
                    else if (what == "moves") moves = (bool)step[1];
                    else if (what == "hide") tip.Hide((bool)step[1]);
                    else if (what == "message")
                        proc.Invoke(tip, new object[] { own, (uint)(double)step[1], new IntPtr((long)(double)step[2]), IntPtr.Zero });
                    else if (what == "shown") ShowWindow(own, 4);           // SW_SHOWNOACTIVATE; a message-only window is on no screen
                    else if (what == "is_visible") answer = (GetWindowLongW(own, -16) & 0x10000000) != 0;   // WS_VISIBLE in GWL_STYLE
                    else if (what == "timers")
                    {
                        var alive = new List<object>();
                        foreach (int id in Ints(step[1])) alive.Add(KillTimer(own, new UIntPtr((uint)id)));
                        answer = alive;
                    }
                    else if (what == "pump")
                    {
                        MSG msg;
                        var until = DateTime.UtcNow.AddMilliseconds(200);
                        while (DateTime.UtcNow < until)
                            while (PeekMessageW(out msg, IntPtr.Zero, 0, 0, 1))
                            {
                                TranslateMessage(ref msg);
                                DispatchMessageW(ref msg);
                            }
                        answer = new List<object>(heard);
                    }
                    else throw new ArgumentException("no tip step " + what);
                    after.Add(new Dictionary<string, object> { { "visible", tip.Visible }, { "fade", tip.Fade }, { "answer", answer } });
                }
            }
            finally
            {
                var kept = new List<object>(record);
                SurfaceScreen.Probe = saved;
                SurfaceScreen.Name = savedName;
                if (hook != IntPtr.Zero) UnhookWinEvent(hook);
                tip.Dispose();
                GC.KeepAlive(listen);
                record = new List<string>();
                foreach (object line in kept) record.Add((string)line);
            }
            return new Dictionary<string, object> { { "record", new List<object>(record) }, { "steps", after } };
        }

        // ------------------------------------------------------------------ the icon's card, made
        private sealed class Made : ITrayTip
        {
            internal int Shown;
            public void Show(Func<int[]> icon, int[] point) { Shown++; }
            public void Hide(bool atOnce) { }
            public void Destroy() { }
        }

        private static object MakeTip(Dictionary<string, object> task)
        {
            var icon = new TrayIcon { Version4 = true, Days = (bool)task["days"] };
            Action<string> log = line => { };
            icon.Log = log;
            var makes = new List<object>();
            var made = new Made();
            icon.MakeTipCard = (content, held, given, days) =>
            {
                makes.Add(new List<object> { content.Method.Name, ReferenceEquals(content.Target, icon), held.Method.Name,
                                             ReferenceEquals(held.Target, icon), ReferenceEquals(given, log), days });
                return made;
            };
            MethodInfo show = typeof(TrayIcon).GetMethod("ShowTip", BindingFlags.Instance | BindingFlags.NonPublic);
            show.Invoke(icon, new object[] { (long)0 });
            show.Invoke(icon, new object[] { (long)0 });
            return new Dictionary<string, object> { { "makes", makes }, { "shown", (double)made.Shown } };
        }

        private static object MakeTipLive(Dictionary<string, object> task)
        {
            var icon = new TrayIcon();
            Func<TipCard.Content> content = () => null;
            Func<bool> held = () => true;
            Action<string> log = line => { };
            bool days = (bool)task["days"];
            ITrayTip tip = icon.MakeTipCard(content, held, log, days);
            object card = tip.GetType().GetField("card", BindingFlags.Instance | BindingFlags.NonPublic).GetValue(tip);
            var flags = BindingFlags.Instance | BindingFlags.NonPublic;
            var found = new Dictionary<string, object>
            {
                { "surface", tip.GetType().Name }, { "card", card.GetType().Name },
                { "content", ReferenceEquals(typeof(TipCard).GetField("content", flags).GetValue(card), content) },
                { "held", ReferenceEquals(typeof(TipCard).GetField("held", flags).GetValue(card), held) },
                { "log", ReferenceEquals(typeof(TipCard).GetField("log", flags).GetValue(card), log) },
                { "days", typeof(TipCard).GetField("days", flags).GetValue(card) },
                { "accessible", ((TipCard)card).Accessible != null }, { "window", ((TipCard)card).Hwnd != IntPtr.Zero },
            };
            ((TipCard)card).Dispose();
            return found;
        }
    }
}
"""


class _Recorder:
    """user32 as the reference calls it, every call kept: a menu is a number from MENU_BASE up, TrackPopupMenu answers
    `chosen`, anything else yes."""

    def __init__(self, chosen=0):
        self.calls, self.menus, self.chosen = [], [], chosen

    def __call__(self, name):
        return self

    def CreatePopupMenu(self):
        menu = MENU_BASE + len(self.menus)
        self.menus.append(menu)
        self.calls.append(("CreatePopupMenu", (menu,)))
        return menu

    def TrackPopupMenu(self, *arguments):
        self.calls.append(("TrackPopupMenu", arguments))
        return self.chosen

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)

        def call(*arguments):
            self.calls.append((name, arguments))
            return 1
        return call


def plain(value):
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    return value


def number_text(value, menus=()):
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, int) and value in menus:
        return "0x%x" % value
    return "None" if value is None else str(value)


def host_member(path, type_name, member):
    """One method of one host type by its braces (guiscan's member_body reads the window's sources only)."""
    body = guiscan.type_body(type_name, (ROOT / path).read_text(encoding="utf-8"))
    pattern = re.compile(r"(?m)^[ 	]*(?:(?:%s)[ 	]+)*[\w<>,\[\]\.\?]+[ 	]+%s[ 	]*[\(\{]"
                         % ("|".join(guiscan.MODIFIERS), re.escape(member)))
    found = pattern.search(body)
    if found is None:
        raise AssertionError("%s has no member %s" % (type_name, member))
    return guiscan._block(body, found.start())


def build_driver(folder):
    driver = folder / "HostSeamsDriver.cs"
    driver.write_text(DRIVER, encoding="utf-8")
    sources = [ROOT / name for name in guiscan.host_group("contract") + guiscan.host_group("surface")
               + guiscan.host_group("generated")]
    exe = folder / "host-seams.exe"
    built = subprocess.run([str(CSC), "-nologo", "-target:exe", "-platform:x64", "-warnaserror", "-optimize+",
                            "-out:%s" % exe, "-r:System.dll", "-r:System.Drawing.dll"]
                           + [str(path) for path in sources] + [str(driver)],
                           capture_output=True, timeout=600, creationflags=CREATE_NO_WINDOW)
    if built.returncode != 0:
        raise AssertionError("the host does not compile with the driver:\n%s" % built.stdout.decode("utf-8", "replace"))
    return exe


@unittest.skipUnless(CSC.is_file(), "needs the in-box C# compiler")
class SeamTests(unittest.TestCase):
    """Each case run by the host's own classes in one driver process, compared with the reference."""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory(prefix="car-host-seams-")
        cls.exe = build_driver(Path(cls.folder.name))

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def run_cases(self, cases):
        folder = Path(self.folder.name)
        job, out = folder / "job.json", folder / "job.out.json"
        if out.exists():
            out.unlink()
        job.write_text(json.dumps({"cases": cases}, ensure_ascii=False), encoding="utf-8")
        env = dict(os.environ, CODEX_AUTO_RESUME_CODEX_EXE=str(folder / "no-codex.exe"), CAR_NO_REAL_ENGINE="1")
        ran = subprocess.run([str(self.exe), str(job), str(out)], capture_output=True, timeout=300, env=env,
                             creationflags=CREATE_NO_WINDOW)
        if not out.is_file():
            raise AssertionError("the driver wrote nothing (exit %d):\n%s" % (ran.returncode, ran.stdout.decode("utf-8", "replace")))
        answers = json.loads(out.read_text(encoding="utf-8"))
        for answer in answers:
            if isinstance(answer, dict) and "error" in answer:
                raise AssertionError("the driver: %s" % answer["error"])
        return answers

    # ------------------------------------------------------------------ the popup's Windows row menu
    def reference_row_menu(self, lparam, chosen, rtl=None, focus=None, **extra):
        """The reference Popup with one drawn row (test_popup_row_menu_drawn's), no drawn menu: Windows' menu over a
        recording user32. Returns (the menu calls in SurfaceScreen's words, what it ran, the case for the host)."""
        import test_popup_row_menu_drawn as fixtures
        from codex_auto_resume.ui.popup import window as popup_window
        shown = fixtures.shown_popup(**extra)
        if rtl is not None:
            shown._painted_plan["rtl"] = rtl
        if focus is not None:
            shown.focus = ("check", focus)
        user32 = _Recorder(chosen)
        with mock.patch.object(popup_window, "_dll", user32):
            shown._context_menu(lparam)
        menus = set(user32.menus)
        record = []
        for name, arguments in user32.calls:
            if name == "PostMessageW" and arguments[1:] == (0, 0, 0):
                record.append("PostMessageW popup 0 0 0")
            if name not in MENU_CALLS:
                continue
            if name == "TrackPopupMenu":
                menu, flags, x, y, _reserved, hwnd, _rect = arguments
                record.append("TrackPopupMenu 0x%x %d %d %d %s" % (menu, flags, x, y, "popup" if hwnd == shown.hwnd else hwnd))
            elif name == "AppendMenuW":
                menu, flags, identifier, text = arguments
                record.append("AppendMenuW 0x%x %d %s %s" % (menu, flags, number_text(identifier, menus),
                                                            "None" if text is None else text.replace("\n", "\\n")))
            else:
                record.append("%s 0x%x" % (name, arguments[0]))
        view = shown.model.view(1000.0)
        menus_of = [[task["interruption_id"], shown.model.menu_for(task["interruption_id"])]
                    for task in view.get("tasks", []) if task.get("interruption_id")]
        case = {"kind": "row_menu", "probe": True, "strings": plain(shown.model.strings), "choice": chosen,
                "core": plain({"view": view, "menus": menus_of, "read": False}),
                "rows": plain(shown._painted_plan["rows"]), "rtl": rtl, "lparam": lparam, "focus": focus}
        return record, list(shown.ran), case

    @staticmethod
    def posted(action):
        """What the host posts for an action the reference ran (PopupWindow.Fields)."""
        kind = action[0]
        if kind == "dashboard_row":
            return ["open_dashboard", {"page": "pending", "row": list(action[1:])}]
        calls = {"recovery": "set_interruption_recovery", "enabled": "set_enabled", "postpone": "postpone",
                 "unpostpone": "unpostpone", "release": "release_hold", "tier": "set_thread_tier",
                 "project": "set_project_rule", "unsay": "set_once_words"}
        return ["popup", {"call": calls[kind], "args": plain(list(action[1:]))}]

    def test_windows_row_menu_is_made_tracked_and_destroyed_through_the_seam_as_the_reference_makes_it(self):
        import test_popup_row_menu_drawn as fixtures
        shapes = [((30 << 16) | 40, 2, None, None), ((30 << 16) | 40, 0, True, None), ((12 << 16) | 9, 3, False, None),
                  (0xFFFFFFFF, 2, None, fixtures.KEY), (0xFFFFFFFF, 1, True, fixtures.KEY), ((30 << 16) | 40, 99, None, None)]
        expected, cases = [], []
        for lparam, chosen, rtl, focus in shapes:
            record, ran, case = self.reference_row_menu(lparam, chosen, rtl, focus)
            expected.append((record, ran))
            cases.append(case)
        answers = self.run_cases(cases)
        for (lparam, chosen, rtl, focus), (record, ran), answer in zip(shapes, expected, answers):
            with self.subTest(lparam=lparam, chosen=chosen, rtl=rtl, focus=focus):
                found = [line for line in answer["record"]
                         if line.split(" ")[0] in MENU_CALLS or line == "PostMessageW popup 0 0 0"]
                self.assertTrue(any(line.startswith("TrackPopupMenu ") for line in record), "the reference showed Windows' menu")
                self.assertEqual(found, record)
                self.assertEqual(len(answer["tracked"]), 1, "MenuChoice asked once, with the menu tracked")
                self.assertEqual(answer["posts"], [self.posted(action) for action in ran])
        self.assertTrue(any(ran for _record, ran in expected), "a choice ran an action")
        self.assertTrue(any(not ran for _record, ran in expected), "a click away ran nothing")

    def test_windows_row_menu_s_live_calls_make_fill_and_destroy_windows_own_menu(self):
        mf_string, mf_grayed, mf_checked, mf_popup, mf_separator = 0x0, 0x1, 0x8, 0x10, 0x800
        sub = [[mf_string, 1, "For an hour"], [mf_string | mf_grayed, 2, "Until tomorrow"], [mf_string | mf_checked, 3, "Line\nbreak"]]
        main = [[mf_string | mf_popup, None, "Postpone"], [mf_separator, 0, None], [mf_string, 4, "Release"],
                [mf_string | mf_grayed | mf_checked, 5, "Tier"]]
        answer, = self.run_cases([{"kind": "menu_real", "main": main, "sub": sub}])
        main_read, sub_read = answer["read"]
        self.assertEqual([item[:3] for item in sub_read],
                         [[1, mf_string, "For an hour"], [2, mf_grayed, "Until tomorrow"], [3, mf_checked, "Line\nbreak"]])
        self.assertEqual(main_read[0][2:], ["Postpone", True], "the submenu is the item's own")
        self.assertEqual(main_read[0][1] & mf_popup, mf_popup)
        self.assertEqual(main_read[1][1] & mf_separator, mf_separator)
        self.assertEqual([item[:3] for item in main_read[2:]], [[4, 0, "Release"], [5, mf_grayed | mf_checked, "Tier"]])
        self.assertEqual((answer["main_gone"], answer["sub_gone"]), (True, True), "destroyed with its submenu")

    def test_trackpopupmenu_s_live_line_is_windows_own_call_with_the_reference_s_arguments(self):
        body = host_member("gui/SurfaceScreen.cs", "SurfaceScreen", "TrackPopupMenu")
        self.assertIn("if (!Probing) return SurfaceNative.TrackPopupMenu(menu, flags, x, y, 0, hwnd, IntPtr.Zero);", body)
        context = host_member("gui/PopupWindow.cs", "PopupWindow", "ContextMenu")
        for native in ("SurfaceNative.CreatePopupMenu", "SurfaceNative.AppendMenuW", "SurfaceNative.TrackPopupMenu",
                       "SurfaceNative.DestroyMenu"):
            self.assertNotIn(native, context, "Windows' row menu goes through SurfaceScreen")

    # ------------------------------------------------------------------ the tooltip card
    def reference_tip(self, steps):
        """The reference TipCard as CardStateTests drives it: no window, user32 and access.tell recorded."""
        from codex_auto_resume.ui import popup
        from codex_auto_resume.ui.tray import tipcard
        user32 = _Recorder()
        clock = [0.0]
        pointer = [(0, 0)]
        moves = [True]
        card = tipcard.TipCard(content=lambda: None)
        card.hwnd = 0x99
        card._moves = lambda: moves[0]
        record = []

        def tell(hwnd, event):
            user32.calls.append(("NotifyWinEvent", (hwnd, event)))
        after = []
        with mock.patch.object(popup, "_dll", user32), mock.patch.object(tipcard.access, "tell", tell), \
                mock.patch.object(tipcard, "tip_pointer", lambda: pointer[0]), \
                mock.patch.object(tipcard, "time", types.SimpleNamespace(monotonic=lambda: clock[0], time=lambda: 0.0)):
            for step in steps:
                what = step[0]
                if what == "visible":
                    card.visible = step[1]
                elif what == "plan":
                    card._plan = dict(card._plan or {}, scale=step[1], size=tuple(step[2]))
                elif what == "screen":
                    card._screen = {"box": tuple(step[1])}
                elif what == "origin":
                    card._origin = tuple(step[1])
                elif what == "clock":
                    clock[0] = step[1]
                elif what == "pointer":
                    pointer[0] = tuple(step[1])
                elif what == "moves":
                    moves[0] = step[1]
                elif what == "hide":
                    card.hide(at_once=step[1])
                elif what == "message":
                    card._wndproc(card.hwnd, step[1], step[2], 0)
                else:
                    raise AssertionError(what)
                after.append({"visible": card.visible, "fade": card._fade[0] if card._fade else None})
        for name, arguments in user32.calls:
            if name not in TIP_CALLS:
                continue
            hwnd, rest = arguments[0], arguments[1:]
            if name == "SetTimer":
                rest = rest[:2]
            record.append(" ".join([name, "tip" if hwnd == card.hwnd else str(hwnd)] + [number_text(value) for value in rest]))
        return record, after

    TIP_STEPS = {
        "hide at once": [["visible", True], ["hide", True], ["hide", True]],
        "fade out and its end": [["visible", True], ["clock", 10.0], ["hide", False], ["clock", 11.0],
                                 ["message", 0x0113, 3]],
        "a hide ends a fade on its way": [["visible", True], ["hide", False], ["hide", True], ["hide", True]],
        "no motion": [["visible", True], ["moves", False], ["hide", False]],
        "backstop": [["visible", True], ["moves", False], ["plan", 1.0, [300, 80]], ["screen", [1700, 1040, 1724, 1064]],
                     ["origin", [1562, 952]], ["pointer", [100, 100]], ["clock", 0.0], ["message", 0x0113, 4],
                     ["clock", 0.5], ["message", 0x0113, 4], ["clock", 1.0], ["message", 0x0113, 4]],
        "backstop kept": [["visible", True], ["plan", 1.0, [300, 80]], ["screen", [1700, 1040, 1724, 1064]],
                          ["origin", [1562, 952]], ["pointer", [1690, 1050]], ["clock", 0.0], ["message", 0x0113, 4],
                          ["clock", 5.0], ["message", 0x0113, 4]],
        "suspend": [["visible", True], ["message", 0x0218, 4]],
        "display change": [["visible", True], ["moves", True], ["message", 0x007E, 0]],
    }

    def test_the_tip_card_s_screen_timer_and_reader_calls_go_through_the_seam_as_the_reference_makes_them(self):
        names = list(self.TIP_STEPS)
        expected = [self.reference_tip(self.TIP_STEPS[name]) for name in names]
        answers = self.run_cases([{"kind": "tip_state", "probe": True, "steps": self.TIP_STEPS[name]} for name in names])
        for name, (record, after), answer in zip(names, expected, answers):
            with self.subTest(name):
                found = [line for line in answer["record"] if line.split(" ")[0] in TIP_CALLS]
                self.assertEqual(found, record)
                self.assertEqual([{"visible": step["visible"], "fade": step["fade"]} for step in answer["steps"]], after)
        hides = [line for record, _after in expected for line in record if line == "ShowWindow tip 0"]
        self.assertTrue(hides, "the cases hide the card")

    def test_the_tip_card_s_live_calls_reach_windows(self):
        """Over a message-only window of the driver's own (on no screen): the fade's timer is Windows' after a hide that
        fades and gone after its end, the window's visible bit is cleared by the hide, and a WinEvent hook hears the
        hide (EVENT_OBJECT_HIDE, OBJID_CLIENT, CHILDID_SELF)."""
        steps = [["visible", True], ["shown"], ["is_visible"], ["hide", False], ["timers", [3]], ["hide", True],
                 ["is_visible"], ["visible", True], ["hide", False], ["clock", 5.0], ["message", 0x0113, 3],
                 ["timers", [1, 2, 3, 4]], ["pump"]]
        answer, = self.run_cases([{"kind": "tip_state", "probe": False, "steps": steps}])
        self.assertEqual(answer["record"], [], "nothing recorded on the live path")
        found = [step["answer"] for step in answer["steps"]]
        self.assertEqual(found[2], True, "the message-only window took the visible bit")
        self.assertEqual(found[4], [True], "the fade's timer was set by Windows")
        self.assertEqual(found[6], False, "the hide at once hid it (ShowWindow SW_HIDE)")
        self.assertEqual(found[11], [False, False, False, False], "the fade's end killed its timer; no other runs")
        told = [event for event in found[12] if event[1] == -4]        # Windows' own show/hide of the window is OBJID_WINDOW
        self.assertEqual(told, [[0x8003, -4, 0], [0x8003, -4, 0]], "each hide told the reader once, of the client")

    # ------------------------------------------------------------------ the icon's card, made
    def test_the_icon_makes_its_card_once_with_what_icon_py_hands_tipcard(self):
        answers = self.run_cases([{"kind": "make_tip", "days": days} for days in (True, False)])
        for days, answer in zip((True, False), answers):
            with self.subTest(days=days):
                self.assertEqual(answer["makes"], [["TipContent", True, "PopupHeld", True, True, days]])
                self.assertEqual(answer["shown"], 2, "made once and kept, shown at each rest")
        source = (ROOT / "src/codex_auto_resume/ui/tray/icon.py").read_text(encoding="utf-8")
        self.assertIn("TipCard(content=self._tip_content, held=self._popup_held, log=self.log, days=self.days)", source)

    def test_the_live_maker_gives_the_card_exactly_that_and_attaches_the_screen_reader(self):
        answers = self.run_cases([{"kind": "make_tip_live", "days": days} for days in (True, False)])
        for days, answer in zip((True, False), answers):
            with self.subTest(days=days):
                self.assertEqual(answer, {"surface": "TipSurface", "card": "TipCard", "content": True, "held": True,
                                          "log": True, "days": days, "accessible": True, "window": False})


if __name__ == "__main__":
    unittest.main()
