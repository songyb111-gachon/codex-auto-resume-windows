r"""v0.6.24-beta.3: the Dashboard's header shows its day's scene on a special day, and no slice of it where it has no room.

Found 2026-11-17 in renders of the window on each special day: the header card showed no scene, only slices of it behind
the three caption buttons. The scene (SoftDayScene) is the header's child above the card (the hero), and on the screen it
stands over the card: it is higher in the header's z-order and every child window clips its siblings. A picture of the
window is DrawToBitmap, which prints a window's children from the top of the z-order down, each over the one before - the
card was printed over the scene. Only the caption buttons, painted again over the picture (PaintCaptionOver), drew the
scene under them. The picture now lays the scene down over it as the screen stacks it (PaintSceneOver), then the buttons.

A probe compiled with the window builds the Dashboard as a render builds it (OpenForRender: a child of Windows' parking
window, never on the screen) at the pictures' pinned 150 %, with the probe's own date (DayArt.On, DayArt.Clock) - a special
day and an ordinary one - and compares the two pictures (RenderPicture) inside the header card, left of the caption buttons
and behind them. With words that leave no room, the scene is not shown and the two pictures are the same: no slice.

GUI test module (it compiles the window and builds windows that are never shown): run on its own, through gui_lock.sh.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "src"), str(ROOT / "tests")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import guiscan  # noqa: E402
from codex_auto_resume import brand, l10n, settings  # noqa: E402
from test_gui_layout import fullest_snapshot  # noqa: E402

CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

PROBE = r"""
using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;

namespace CodexAutoResume
{
    internal static class DayHeaderProbe
    {
        [STAThread]
        internal static int Main(string[] argv)
        {
            Application.SetUnhandledExceptionMode(UnhandledExceptionMode.ThrowException);
            var said = new Dictionary<string, object>();
            int code = 0;
            try { SettingsForm.DayHeaderRun(argv[1], said); }
            catch (Exception e) { said["error"] = e.ToString(); code = 3; }
            File.WriteAllText(argv[0], Json.Write(said), new UTF8Encoding(false));
            return code;
        }
    }

    internal sealed partial class SettingsForm
    {
        [DllImport("user32.dll", EntryPoint = "GetWindowLongPtrW")]
        private static extern IntPtr DayHeaderStyle(IntPtr h, int index);

        // v0.6.26 (audit Z1): every window the probe opens, and what it still waited for when its HoldStill gave up - a
        // window opened with nothing to answer its Dashboard read waited out the whole RenderSettleLimit, 26 times.
        private static readonly List<object> DayHeaderUnsettled = new List<object>();
        private static int DayHeaderOpened;

        // The settings the window reads, as the probe has set the window up: its theme and design, in English.
        private static Dictionary<string, object> DayHeaderSettings;

        private static SettingsForm DayHeaderOpen(RenderWriter writer)
        {
            SettingsForm form = DayHeaderOpenUnsettled(writer);
            DayHeaderSettle(form);
            return form;
        }

        private static SettingsForm DayHeaderOpenUnsettled(RenderWriter writer)
        {
            var current = (Dictionary<string, object>)DayHeaderSettings["settings"];
            current["theme"] = Palette.Dark ? "dark" : "light";
            current["design"] = Palette.Design;
            current["interface_language"] = "en";
            // Made as a process's first window is: the controls the window makes as its fields, before it reads its date
            // (DayGround.Adopt in its constructor), take the palette's own canvas - not the tint the probe's last window, on
            // another date, left in it. A window opened on an ordinary day after a special day's kept that day's tint on its
            // header, tabs and page host (#D9DEE8 for #E9EEF4): the window repaints its fields from the untinted canvas to the
            // day's, never from another day's to none. In the product the date does not jump between two windows of one
            // process - the open window follows midnight each second (FollowDayScene) - so this is the probe's own state.
            DayGround.Adopt(null, null);
            SettingsForm form = OpenForRender(writer);
            DayHeaderOpened++;
            var notes = (List<string>)typeof(RenderWriter).GetField("notes", System.Reflection.BindingFlags.Instance |
                                                                    System.Reflection.BindingFlags.NonPublic).GetValue(writer);
            foreach (string note in notes) DayHeaderUnsettled.Add(note);
            return form;
        }

        // Every read the window has on its way back, answered and applied (at most 20 s; one still out is noted).
        private static void DayHeaderDrain(SettingsForm form, string after)
        {
            var draining = System.Diagnostics.Stopwatch.StartNew();
            while ((form.refreshing || form.bridge.InFlight > 0) && draining.ElapsedMilliseconds < 20000)
            {
                Application.DoEvents();
                System.Threading.Thread.Sleep(10);
            }
            Application.DoEvents();
            if (form.refreshing || form.bridge.InFlight > 0) DayHeaderUnsettled.Add("a read still out after " + after);
        }

        // Found 2026-11-27 (three of this module's tests red alone on dev on US Thanksgiving, green the run after on the same
        // date: not the date, whose every read here is the probe's own, DayArt.Clock): the header's words and light are those
        // of whichever read the window applied last - the status, which nothing answers here ("Status unavailable"), or the
        // Dashboard's, which is answered ("Watching for interruptions") - and the window's clock reads the Dashboard every
        // five seconds. Whether a window had lived past one of those reads when it was drawn was the wall clock's doing: one
        // window crossed one and the window it is compared with did not, and the two pictures differed in the words and the
        // light, and a window past midnight in its count of grounds (3 of 5 runs of one build, 2026-11-27). Every window now
        // stops its clock and takes the Dashboard's read last, so the header is the same in every window however long each
        // took. The product is not at fault: a person's window follows its reads as they come (ApplyStatus, StatusUnavailable).
        private static void DayHeaderSettle(SettingsForm form)
        {
            form.clock.Stop();
            DayHeaderDrain(form, "the window opened");
            form.RefreshNow();
            DayHeaderDrain(form, "the last Dashboard read");
            // And drawn from it, nothing moving, as OpenForRender's HoldStill waits - less the clock's tick, now stopped - and
            // every page made ready ahead (PreparePagesLater): how far the idle turns had got was the wall clock's as well, and
            // so was how many of the window's controls stood on its ground (DayHeaderTinted).
            var waited = System.Diagnostics.Stopwatch.StartNew();
            var still = new System.Diagnostics.Stopwatch();
            while (waited.ElapsedMilliseconds < RenderSettleLimit)
            {
                Application.DoEvents();
                Application.RaiseIdle(EventArgs.Empty);
                Materialise(form);
                if (!form.Settled() || form.prepareQueued || form.urgentPage != null) still.Reset();
                else if (!still.IsRunning) still.Start();
                else if (still.ElapsedMilliseconds >= 250) return;
                System.Threading.Thread.Sleep(10);
            }
            DayHeaderUnsettled.Add("the window did not hold still after its last Dashboard read: " + form.Unsettled() +
                                   (form.prepareQueued ? ", pages still made ready (" + form.preparing + ")" : ""));
        }

        private static List<object> DayHeaderBox(Rectangle r)
        {
            return new List<object> { (double)r.Left, (double)r.Top, (double)r.Width, (double)r.Height };
        }

        private static Rectangle DayHeaderIn(Control c, Control root)
        {
            Point at = Point.Empty;
            for (Control each = c; each != null && each != root; each = each.Parent) at.Offset(each.Left, each.Top);
            return new Rectangle(at, c.Size);
        }

        // How many pixels of `area` differ between the two pictures by more than a rounding's worth in any channel.
        private static int DayHeaderDiffer(Bitmap one, Bitmap other, Rectangle area)
        {
            area.Intersect(new Rectangle(Point.Empty, one.Size));
            if (area.Width <= 0 || area.Height <= 0) return 0;
            int count = 0;
            for (int y = area.Top; y < area.Bottom; y++)
                for (int x = area.Left; x < area.Right; x++)
                {
                    Color a = one.GetPixel(x, y), b = other.GetPixel(x, y);
                    if (Math.Abs(a.R - b.R) > 8 || Math.Abs(a.G - b.G) > 8 || Math.Abs(a.B - b.B) > 8) count++;
                }
            return count;
        }

        private static Bitmap DayHeaderPicture(DateTime day, string headlineText, Dictionary<string, object> said, string work)
        {
            DayArt.On = true;
            DayArt.Clock = delegate { return day; };
            var writer = new RenderWriter(Path.Combine(work, "frames-" + day.ToString("yyyyMMdd") + (headlineText == null ? "" : "-long")));
            SettingsForm form = DayHeaderOpen(writer);
            try
            {
                if (headlineText != null)
                {
                    // The words held against the window's own reads: its clock reads the Dashboard every five seconds, and
                    // nothing answers that read here, so its failure (MarkUnavailable) wrote "Status unavailable" over the
                    // words whenever a read came back after they were set - on two slower runners of dev run 44273621705,
                    // once before the words were read and once between the two pictures. The clock stopped, and every read
                    // already on its way back, before the words are set - since 2026-11-27 in every window (DayHeaderSettle).
                    form.headline.Text = headlineText;
                    form.detail.Text = headlineText;
                    Application.DoEvents();
                    form.PlaceDayScene();
                }
                said["look"] = form.dayLook;
                said["headline"] = form.headline.Text;
                said["light"] = form.stateDot.State;
                said["sceneShown"] = Soft.OwnVisible(form.dayScene) && form.dayScene.Look != null;
                Rectangle hero = DayHeaderIn(form.hero, form);
                said["hero"] = DayHeaderBox(hero);
                said["scene"] = DayHeaderBox(DayHeaderIn(form.dayScene, form));
                Rectangle buttons = Rectangle.Empty;
                foreach (CaptionButton b in new[] { form.chrome.MinimizeButton, form.chrome.MaximizeButton, form.chrome.CloseButton })
                    if (Soft.OwnVisible(b))
                    {
                        Rectangle r = DayHeaderIn(b, form);
                        buttons = buttons.IsEmpty ? r : Rectangle.Union(buttons, r);
                    }
                said["buttons"] = DayHeaderBox(buttons);
                // On the screen: the scene above the card in the header's z-order, both clipping their siblings.
                if (form.dayScene.Parent == form.header)
                {
                    said["sceneAboveCard"] = form.header.Controls.GetChildIndex(form.dayScene) < form.header.Controls.GetChildIndex(form.hero);
                    const long clip = 0x04000000;   // WS_CLIPSIBLINGS
                    said["clipsSiblings"] = (DayHeaderStyle(form.dayScene.Handle, -16).ToInt64() & clip) != 0 &&
                                            (DayHeaderStyle(form.hero.Handle, -16).ToInt64() & clip) != 0;
                }
                // W2: where the band of the day begins, the ground the window's ground was given, a page card to hold unchanged.
                said["band"] = DayHeaderBox(DayHeaderIn(form.dayScene, form));
                said["canvas"] = (double)Palette.Canvas.ToArgb();
                said["words"] = new List<object> { (double)Palette.Ink.ToArgb(), (double)Palette.Muted.ToArgb(), (double)Palette.Accent.ToArgb() };
                said["tint"] = Brand.DayGroundTint;
                string dayGround, dayTop, dayBottom;
                Brand.DayGround(form.dayLook ?? "seollal", out dayGround, out dayTop, out dayBottom);
                said["dayGround"] = (double)ColorTranslator.FromHtml(dayGround).ToArgb();
                SoftCard page = null;
                var walk = new Stack<Control>();
                walk.Push(form.pageHost);
                while (walk.Count > 0 && page == null)
                {
                    Control c = walk.Pop();
                    if (c is SoftCard && c != form.hero && Soft.OwnVisible(c) && c.Width > 200 && c.Height > 80) page = (SoftCard)c;
                    foreach (Control child in c.Controls) walk.Push(child);
                }
                if (page != null) said["pageCard"] = DayHeaderBox(Rectangle.Inflate(DayHeaderIn(page, form), -Soft.Px(20), -Soft.Px(20)));
                said["groundWords"] = DayHeaderGroundWords(form);
                said["tinted"] = (double)DayHeaderTinted(form, Palette.Canvas);
                // A frame of the day: what the header's band costs to draw, as its timer draws it thirty times a second.
                if (Soft.OwnVisible(form.dayScene) && form.dayScene.Width > 0)
                    using (var frame = new Bitmap(form.dayScene.Width, form.dayScene.Height))
                    {
                        // Against the scene alone - the frame the header drew before the band (a5cb40038: 3.8-7.4 ms
                        // against 6.9-7.7 ms) - timed in turn in the same process, so a slow or busy runner slows both
                        // (v0.6.26 audit Z5: a bound in milliseconds was the runner's speed as much as the frame's work).
                        // The quickest of five turns of each: what the work takes, not what the runner let it have.
                        // The scene alone is a control of the band's size drawn the same way (DrawToBitmap, double
                        // buffered), in the window but hidden, and taken out again before the window's picture.
                        var sceneAlone = new DayHeaderSceneAlone(form.dayLook, form.dayScene.Unit, form.dayScene.Size);
                        form.Controls.Add(sceneAlone);
                        try
                        {
                            form.dayScene.DrawToBitmap(frame, new Rectangle(Point.Empty, frame.Size));
                            sceneAlone.DrawToBitmap(frame, new Rectangle(Point.Empty, frame.Size));
                            double band = double.MaxValue, alone = double.MaxValue;
                            for (int turn = 0; turn < 5; turn++)
                            {
                                var clock = System.Diagnostics.Stopwatch.StartNew();
                                for (int i = 0; i < 10; i++) form.dayScene.DrawToBitmap(frame, new Rectangle(Point.Empty, frame.Size));
                                band = Math.Min(band, clock.Elapsed.TotalMilliseconds / 10.0);
                                clock.Restart();
                                for (int i = 0; i < 10; i++) sceneAlone.DrawToBitmap(frame, new Rectangle(Point.Empty, frame.Size));
                                alone = Math.Min(alone, clock.Elapsed.TotalMilliseconds / 10.0);
                            }
                            said["frameMs"] = band;
                            said["sceneMs"] = alone;
                        }
                        finally
                        {
                            form.Controls.Remove(sceneAlone);
                            sceneAlone.Dispose();
                        }
                        // What a frame fills: the day's whole band, and what the close button, which paints the day under it
                        // each frame, fills of it - only what lies under it.
                        DayArt.Filled = 0;
                        form.dayScene.DrawToBitmap(frame, new Rectangle(Point.Empty, frame.Size));
                        said["sceneFilled"] = (double)DayArt.Filled;
                        CaptionButton close = form.chrome.CloseButton;
                        using (var under = new Bitmap(close.Width, close.Height))
                        {
                            DayArt.Filled = 0;
                            close.DrawToBitmap(under, new Rectangle(Point.Empty, under.Size));
                            said["buttonFilled"] = (double)DayArt.Filled;
                        }
                    }
                return form.RenderPicture(new Dictionary<string, object>(), writer);
            }
            finally
            {
                form.Dispose();
                DayArt.On = false;
            }
        }

        // The day's scene alone on its ground, where the header's band stands, as the header drew a frame of the day before
        // the band (W2): the reference a frame of the band is held against.
        private sealed class DayHeaderSceneAlone : Control
        {
            private readonly string look;
            private readonly double u;

            internal DayHeaderSceneAlone(string look, double u, Size size)
            {
                SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
                this.look = look;
                this.u = u;
                Size = size;
                Visible = false;
            }

            protected override void OnPaint(PaintEventArgs e)
            {
                Graphics g = e.Graphics;
                string name, top, bottom;
                Brand.DayGround(look, out name, out top, out bottom);
                g.Clear(ColorTranslator.FromHtml(name));
                double width = Width, origin = Brand.DayFromTop(look) ? 0.0 : Height - Brand.DaySceneHeight * u;
                DayArt.Draw(g, DayArt.Parse(Brand.DayScene(look)), 0.0, u, delegate(double x, double y)
                {
                    return new PointF((float)(width - (Brand.DaySceneWidth - x) * u), (float)(origin + y * u));
                });
            }
        }

        // Every word the window shows on its own ground (a label whose ground is the window's canvas): its words' colour and
        // their contrast with that ground, as the window has it now.
        private static List<object> DayHeaderGroundWords(SettingsForm form)
        {
            var found = new List<object>();
            var walk = new Stack<Control>();
            walk.Push(form);
            while (walk.Count > 0)
            {
                Control c = walk.Pop();
                foreach (Control child in c.Controls) walk.Push(child);
                // Every page's, shown or not yet: a page off the card's words (the Statistics period) stand on the ground.
                if (!(c is Label) || string.IsNullOrEmpty(c.Text)) continue;
                if (Ground.Colour(c).ToArgb() != Palette.Canvas.ToArgb()) continue;
                found.Add(new List<object> { c.GetType().Name, c.Text, (double)c.ForeColor.ToArgb(), Chrome.Contrast(c.ForeColor, Palette.Canvas) });
            }
            return found;
        }

        // How many of the window's controls are in `colour`.
        private static int DayHeaderTinted(Control form, Color colour)
        {
            int count = 0;
            var walk = new Stack<Control>();
            walk.Push(form);
            while (walk.Count > 0)
            {
                Control c = walk.Pop();
                if (c.BackColor.ToArgb() == colour.ToArgb()) count++;
                foreach (Control child in c.Controls) walk.Push(child);
            }
            return count;
        }

        // A window opened on `from` and left open past midnight into `to` (the window's clock asks FollowDayScene each second).
        private static Dictionary<string, object> DayHeaderFollow(DateTime from, DateTime to, string work)
        {
            var said = new Dictionary<string, object>();
            DateTime now = from;
            DayArt.On = true;
            DayArt.Clock = delegate { return now; };
            var writer = new RenderWriter(Path.Combine(work, "frames-follow-" + from.ToString("yyyyMMdd")));
            SettingsForm form = DayHeaderOpen(writer);
            try
            {
                form.FollowDayScene();
                Color before = Palette.Canvas;
                said["lookBefore"] = form.dayLook;
                now = to;
                form.FollowDayScene();
                Application.DoEvents();
                said["look"] = form.dayLook;
                said["canvas"] = (double)Palette.Canvas.ToArgb();
                said["formGround"] = (double)form.BackColor.ToArgb();
                said["inOldColour"] = (double)DayHeaderTinted(form, before);
                said["inNewColour"] = (double)DayHeaderTinted(form, Palette.Canvas);
                said["sceneShown"] = Soft.OwnVisible(form.dayScene) && form.dayScene.Look != null;
                said["groundLook"] = DayGround.Look;
            }
            finally
            {
                form.Dispose();
                DayArt.On = false;
            }
            return said;
        }

        // A window whose reads came back in one order or the other - the status (unanswered here) last, or the Dashboard's
        // last, as a window that lived past its clock's five-second read has it - and was then settled (DayHeaderSettle):
        // what its header says.
        private static Dictionary<string, object> DayHeaderRace(DateTime day, bool statusLast, string work)
        {
            var said = new Dictionary<string, object>();
            DayArt.On = true;
            DayArt.Clock = delegate { return day; };
            SettingsForm form = DayHeaderOpenUnsettled(new RenderWriter(Path.Combine(work, "frames-race-" + (statusLast ? "status" : "dashboard"))));
            try
            {
                form.clock.Stop();
                DayHeaderDrain(form, "the race's window opened");
                if (statusLast)
                {
                    form.RefreshNow();
                    DayHeaderDrain(form, "the race's Dashboard read");
                    form.RefreshStatusAsync(null);
                    DayHeaderDrain(form, "the race's status read");
                }
                else
                {
                    form.RefreshStatusAsync(null);
                    DayHeaderDrain(form, "the race's status read");
                    form.RefreshNow();
                    DayHeaderDrain(form, "the race's Dashboard read");
                }
                said["before"] = form.headline.Text;
                DayHeaderSettle(form);
                said["headline"] = form.headline.Text;
                said["detail"] = form.detail.Text;
                said["light"] = form.stateDot.State;
                said["tinted"] = (double)DayHeaderTinted(form, Palette.Canvas);
            }
            finally
            {
                form.Dispose();
                DayArt.On = false;
            }
            return said;
        }

        private static Dictionary<string, object> DayHeaderCompare(DateTime special, DateTime plain, string headlineText, string work)
        {
            var said = new Dictionary<string, object>();
            var one = new Dictionary<string, object>();
            var other = new Dictionary<string, object>();
            using (Bitmap a = DayHeaderPicture(special, headlineText, one, work))
            using (Bitmap b = DayHeaderPicture(plain, headlineText, other, work))
            {
                said["special"] = one;
                said["plain"] = other;
                var hero = (List<object>)one["hero"];
                var box = (List<object>)one["buttons"];
                var card = new Rectangle((int)(double)hero[0], (int)(double)hero[1], (int)(double)hero[2], (int)(double)hero[3]);
                var buttons = new Rectangle((int)(double)box[0], (int)(double)box[1], (int)(double)box[2], (int)(double)box[3]);
                // The card left of the buttons, top to bottom, and the buttons themselves.
                var left = new Rectangle(card.Left, card.Top, Math.Max(0, buttons.Left - card.Left), card.Height);
                said["leftOfButtons"] = (double)DayHeaderDiffer(a, b, left);
                said["behindButtons"] = (double)DayHeaderDiffer(a, b, buttons);
                // The card's inside, its round corners left out: they show the window's ground, which a day tints.
                said["card"] = (double)DayHeaderDiffer(a, b, Rectangle.Inflate(card, -Soft.Px(24), 0));
                // The band: how much of it between the fade and the scene is the day's ground (the rest its specks).
                var band = (List<object>)one["band"];
                var inside = new Rectangle((int)(double)band[0], card.Top + Soft.Px(2), (int)(double)band[2], card.Height - Soft.Px(4));
                said["bandBox"] = DayHeaderBox(inside);
                said["leftOfBand"] = (double)DayHeaderDiffer(a, b, new Rectangle(card.Left + Soft.Px(24), card.Top + Soft.Px(2),
                                                                                    Math.Max(0, inside.Left - card.Left - Soft.Px(24)), card.Height - Soft.Px(4)));
                int dayGround = (int)(double)one["dayGround"], grounds = 0, all = 0;
                for (int y = inside.Top; y < inside.Bottom; y++)
                    for (int x = inside.Left + Soft.Px(100); x < inside.Left + inside.Width / 2; x++)
                    {
                        all++;
                        if (a.GetPixel(x, y).ToArgb() == dayGround) grounds++;
                    }
                said["dayGroundShare"] = all == 0 ? 0.0 : grounds / (double)all;
                // The window's ground: every pixel of an ordinary day's ground, on the day the tint - or near it, where a card's
                // lit edge, which an ordinary day's ground hides, lies on it - or one of the day's specks.
                int canvas = (int)(double)other["canvas"], ground = 0, tint = 0, specks = 0;
                Color tinted = Color.FromArgb((int)(double)one["canvas"]);
                for (int y = 0; y < a.Height; y += 2)
                    for (int x = 0; x < a.Width; x += 2)
                    {
                        if (b.GetPixel(x, y).ToArgb() != canvas) continue;
                        ground++;
                        Color day = a.GetPixel(x, y);
                        int far = Math.Max(Math.Abs(day.R - tinted.R), Math.Max(Math.Abs(day.G - tinted.G), Math.Abs(day.B - tinted.B)));
                        if (far <= 24) tint++;
                        else specks++;
                    }
                said["ground"] = new List<object> { (double)ground, (double)tint, (double)specks };
                if (one.ContainsKey("pageCard"))
                {
                    var box2 = (List<object>)one["pageCard"];
                    said["pageCard"] = (double)DayHeaderDiffer(a, b, new Rectangle((int)(double)box2[0], (int)(double)box2[1], (int)(double)box2[2], (int)(double)box2[3]));
                }
            }
            return said;
        }

        internal static void DayHeaderRun(string work, Dictionary<string, object> said)
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Theme.Opened = "light";
            Palette.AdoptDesign(null);
            Palette.Adopt("light");
            // As a render job pinned at the pictures' 150 % (AdoptRenderScale).
            RenderPinned = true;
            AdoptDisplayScale(1.5);
            ScaleDefaultFont();
            AdoptTextSize(1.0, 1.0);
            Soft.StillLightMs = 0;
            var strings = Json.Parse(File.ReadAllText(Path.Combine(work, "strings-en.json"), new UTF8Encoding(false)));
            DayHeaderSettings = (Dictionary<string, object>)Json.Parse(File.ReadAllText(Path.Combine(work, "settings.json"), new UTF8Encoding(false)));
            var dashboard = Json.Parse(File.ReadAllText(Path.Combine(work, "dashboard.json"), new UTF8Encoding(false)));
            renderAnswers = new List<object> { new Dictionary<string, object> { { "command", "strings" }, { "reply", strings } },
                                               new Dictionary<string, object> { { "command", "dashboard" }, { "reply", dashboard } },
                                               new Dictionary<string, object> { { "command", "describe" }, { "reply", Json.Parse(File.ReadAllText(Path.Combine(work, "describe.json"), new UTF8Encoding(false))) } },
                                               new Dictionary<string, object> { { "command", "settings" }, { "reply", DayHeaderSettings } } };
            PersistentBridge.Answers = RenderAnswer;
            DateTime special = DateTime.MinValue, plain = DateTime.MinValue;
            string look, top, bottom;
            for (DateTime day = new DateTime(2027, 1, 1); day.Year == 2027; day = day.AddDays(1))
            {
                if (Brand.DayLook(day.Year, day.Month, day.Day, out look, out top, out bottom))
                { if (special == DateTime.MinValue) special = day.AddHours(12); }
                else if (plain == DateTime.MinValue) plain = day.AddHours(12);
            }
            said["room"] = DayHeaderCompare(special, plain, null, work);
            // Words as long as the card holds, the headline and its second line: they reach the caption buttons and, below
            // them, the card's edge, and leave the scene no room (a long language at a large text size).
            string words = "Watching for interruptions in every conversation of every project on this computer, day and night";
            said["noRoom"] = DayHeaderCompare(special, plain, words + " " + words, work);
            // Past midnight, both ways (the window's clock): into an ordinary day and into a special one.
            said["intoPlain"] = DayHeaderFollow(special, plain, work);
            said["intoSpecial"] = DayHeaderFollow(plain, special, work);
            // The two orders the window's reads can come back in, each forced, then settled as every window is (DayHeaderSettle).
            said["settled"] = new List<object> { DayHeaderRace(plain, false, work), DayHeaderRace(plain, true, work) };
            // The words on the window's ground on each day's look, in both themes of each design that shows a day.
            var words2 = new Dictionary<string, object>();
            foreach (string design in new[] { "soft", "plain" })
                foreach (string theme in new[] { "light", "dark" })
                    for (DateTime day = new DateTime(2027, 1, 1); day.Year == 2027; day = day.AddDays(1))
                    {
                        if (!Brand.DayLook(day.Year, day.Month, day.Day, out look, out top, out bottom)) continue;
                        string key = design + "/" + theme + "/" + look;
                        if (words2.ContainsKey(key)) continue;
                        Palette.AdoptDesign(design);
                        Palette.Adopt(theme);
                        DateTime noon = day.AddHours(12);
                        DayArt.On = true;
                        DayArt.Clock = delegate { return noon; };
                        SettingsForm form = DayHeaderOpen(new RenderWriter(Path.Combine(work, "frames-words-" + design + "-" + theme)));
                        try
                        {
                            words2[key] = new Dictionary<string, object> { { "look", form.dayLook }, { "words", DayHeaderGroundWords(form) },
                                                                            { "design", Palette.Design },
                                                                            { "canvas", (double)Palette.Canvas.ToArgb() },
                                                                            { "untinted", (double)DayGround.Untinted.ToArgb() },
                                                                            { "colours", new List<object> { (double)Palette.Ink.ToArgb(),
                                                                                (double)Palette.Muted.ToArgb(), (double)Palette.Accent.ToArgb() } } };
                        }
                        finally
                        {
                            form.Dispose();
                            DayArt.On = false;
                        }
                    }
            said["groundWords"] = words2;
            said["opened"] = (double)DayHeaderOpened;
            said["unsettled"] = DayHeaderUnsettled;
            Palette.AdoptDesign(null);
            Palette.Adopt("light");
            PersistentBridge.Answers = null;
        }
    }
}
"""



def _hex(argb):
    return "#%06X" % (int(argb) & 0xFFFFFF)


def _mixed(canvas, day, share):
    return "#" + "".join("%02X" % int(round(((int(canvas) >> shift) & 255) + (((int(day) >> shift) & 255) - ((int(canvas) >> shift) & 255)) * share))
                         for shift in (16, 8, 0))


def expected_share(canvas, day, words, tint):
    """The share of the day's ground the window's canvas takes: brand's, stepped down by half a percent until every
    colour of the ground's words stands out from it by 4.5:1 - or by what it did on any other day, where that was less."""
    share = tint
    while share > 0.0:
        tinted = _mixed(canvas, day, share)
        if all(brand.contrast(_hex(word), tinted) >= min(4.5, brand.contrast(_hex(word), _hex(canvas))) - 1e-9 for word in words):
            return share
        share -= 0.005
    return 0.0

# How much more than the scene alone a frame of the band may cost, each the quickest of five turns of ten DrawToBitmaps in
# one process: 1.2 here (4.2 ms against 3.5 ms at 150 %); the band was made to cost about what the scene had (a5cb40038).
# A band that painted itself three times over measured 2.5 (7.0 ms against 2.8) - under the 12 ms the test held until
# v0.6.26, which a loaded runner could break with no more work done (audit Z5).
FRAME_OVER_SCENE = 2.0


@unittest.skipUnless(CSC.is_file(), "needs the in-box C# compiler")
class DayHeaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        work = Path(cls.folder.name)
        reply = {"ok": True, "language": "en", "strings": l10n.catalog("en"), "endonyms": dict(l10n.ENDONYMS),
                 "preference": "en", "system_language": "en"}
        (work / "strings-en.json").write_text(json.dumps(reply, ensure_ascii=False), encoding="utf-8")
        # The Dashboard's reads answered - its settings, its schema and the dashboard - as the pictures' renders answer
        # them: each window holds still once drawn from them, instead of waiting out the render's whole settle limit for a reply that never came (audit Z1).
        (work / "dashboard.json").write_text(json.dumps(fullest_snapshot(time.time()), ensure_ascii=False), encoding="utf-8")
        (work / "describe.json").write_text(json.dumps({"ok": True, "schema": settings.describe()}, ensure_ascii=False),
                                            encoding="utf-8")
        (work / "settings.json").write_text(json.dumps({"ok": True, "settings": settings.defaults()}, ensure_ascii=False),
                                            encoding="utf-8")
        probe = work / "DayHeaderProbe.cs"
        probe.write_text(PROBE, encoding="utf-8")
        exe = work / "DayHeader.exe"
        built = subprocess.run([str(CSC), "/nologo", "/target:winexe", "/platform:x64", "/out:" + str(exe),
                                "/main:CodexAutoResume.DayHeaderProbe", "/win32manifest:" + str(ROOT / "gui" / "app.manifest"),
                                "/reference:System.dll", "/reference:System.Drawing.dll", "/reference:System.Windows.Forms.dll",
                                *[str(path) for path in guiscan.sources()], str(probe)],
                               capture_output=True, timeout=600, creationflags=NO_WINDOW)
        cls.failure = None if built.returncode == 0 else built.stdout.decode("mbcs", "replace")[-3000:]
        cls.answer = {}
        if cls.failure is None:
            out = work / "out.json"
            environment = dict(os.environ, CODEX_HOME=str(work / "no-codex"), LOCALAPPDATA=str(work / "no-local"),
                               TEMP=str(work), TMP=str(work))
            done = subprocess.run([str(exe), str(out), str(work)], capture_output=True, timeout=900,
                                  creationflags=NO_WINDOW, env=environment)
            cls.answer = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else {}
            if done.returncode != 0 or "error" in cls.answer or not cls.answer:
                cls.failure = "the probe failed (exit %d): %s" % (done.returncode, cls.answer.get("error"))

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        if self.failure:
            self.fail(self.failure)

    def test_every_window_the_probe_opens_holds_still(self):
        """Each window is drawn from every answer it asked for before it is looked at (OpenForRender's HoldStill): one that
        gave up waiting said so only in its writer's notes, never read, and cost the render's whole 20 s settle limit -
        26 windows, 520 of the module's 526 s in every lane (v0.6.26 audit Z1)."""
        # Two pictures each with room and without, two windows past midnight, two of the reads' race, and one for each look's
        # words in both themes of both designs.
        self.assertEqual(self.answer["opened"], 8 + 2 * 2 * len(brand.DAY_LOOKS))
        self.assertEqual(self.answer["unsettled"], [])

    def test_the_probe_s_date_gives_the_window_a_look_and_an_ordinary_day_none(self):
        room = self.answer["room"]
        self.assertTrue(room["special"]["look"], "the special day has its look")
        self.assertIsNone(room["plain"]["look"])

    def test_on_the_screen_the_scene_stands_over_the_card(self):
        special = self.answer["room"]["special"]
        self.assertTrue(special["sceneShown"])
        self.assertTrue(special["sceneAboveCard"], "higher in the header's z-order than the card")
        self.assertTrue(special["clipsSiblings"])

    def test_the_scene_shows_in_the_card_left_of_the_caption_buttons(self):
        """Fails without PaintSceneOver: the card was printed over the scene and only the buttons drew it."""
        room = self.answer["room"]
        hero, buttons = room["special"]["hero"], room["special"]["buttons"]
        self.assertGreater(buttons[2], 0, "the caption buttons are shown")
        # A good part of the card's height, over a run of columns wider than the buttons: the scene, not a fringe.
        self.assertGreater(room["leftOfButtons"], hero[3] * buttons[2] // 2, room)

    def test_and_behind_the_caption_buttons_as_well(self):
        self.assertGreater(self.answer["room"]["behindButtons"], 0)

    def test_w2_the_card_is_in_the_day_past_the_words(self):
        room = self.answer["room"]
        band, hero, buttons = room["special"]["band"], room["special"]["hero"], room["special"]["buttons"]
        self.assertLess(band[0], hero[0] + hero[2] * 0.5, "the day begins past the words, not in a corner")
        self.assertEqual(band[0] + band[2], hero[0] + hero[2] - 1, "and reaches the card's outer side, under the buttons")
        self.assertGreater(room["dayGroundShare"], 0.3, "the day's own ground")
        self.assertEqual(room["leftOfBand"], 0, "the words and the light stand as on any other day")

    def test_w2_the_window_s_ground_takes_the_day_faintly_with_its_specks_and_the_cards_stay(self):
        room = self.answer["room"]
        ground, tint, specks = room["ground"]
        self.assertGreater(ground, 1000)
        self.assertGreater(tint / ground, 0.9, "the tint")
        self.assertGreater(specks, 0, "and the day's specks on it")
        canvas, tinted, day = room["plain"]["canvas"], room["special"]["canvas"], room["special"]["dayGround"]
        # Brand's share of the day's ground, or less, as much as keeps the words on the ground at 4.5:1 (DayGround.Tinted).
        share = expected_share(canvas, day, room["special"]["words"], room["special"]["tint"])
        self.assertGreater(share, 0.0)
        mix = [round(((int(canvas) >> shift) & 255) * (1 - share) + ((int(day) >> shift) & 255) * share) for shift in (16, 8, 0)]
        got = [(int(tinted) >> shift) & 255 for shift in (16, 8, 0)]
        for one, other in zip(mix, got):
            self.assertLessEqual(abs(one - other), 1)
        self.assertEqual(room.get("pageCard"), 0, "a page's card is as on any other day")

    def test_w2_the_words_on_the_window_s_ground_keep_4_5_to_1_on_every_day(self):
        """The ground's tint is faint, but a dark day's whole tint took a light window's secondary words to 4.3:1: the
        window's ink, secondary words and accent stand out from its ground by 4.5:1 (or as on any other day, where less)."""
        self.assertEqual(len(self.answer["groundWords"]), 2 * 2 * len(brand.DAY_LOOKS))
        for key, found in sorted(self.answer["groundWords"].items()):
            self.assertTrue(found["look"], key)
            self.assertNotEqual(found["canvas"], found["untinted"], key + ": the ground takes the day")
            for colour in found["colours"]:
                ordinary = brand.contrast(_hex(colour), _hex(found["untinted"]))
                self.assertGreaterEqual(brand.contrast(_hex(colour), _hex(found["canvas"])), min(4.5, ordinary) - 1e-9,
                                        "%s: %s" % (key, _hex(colour)))
            for kind, text, _, contrast in found["words"]:
                self.assertGreaterEqual(contrast, 4.5, "%s: %s %r" % (key, kind, text))

    def test_w2_the_ground_follows_midnight_into_an_ordinary_day(self):
        into, room = self.answer["intoPlain"], self.answer["room"]
        self.assertTrue(into["lookBefore"])
        self.assertIsNone(into["look"])
        self.assertIsNone(into["groundLook"])
        self.assertEqual(into["canvas"], room["plain"]["canvas"])
        self.assertEqual(into["formGround"], room["plain"]["canvas"])
        self.assertEqual(into["inOldColour"], 0, "nothing left in the day's tint")
        self.assertFalse(into["sceneShown"])

    def test_w2_the_ground_follows_midnight_into_a_special_day(self):
        into, room = self.answer["intoSpecial"], self.answer["room"]
        self.assertIsNone(into["lookBefore"])
        self.assertEqual(into["look"], room["special"]["look"])
        self.assertEqual(into["groundLook"], room["special"]["look"])
        self.assertEqual(into["canvas"], room["special"]["canvas"])
        self.assertEqual(into["inOldColour"], 0, "nothing left in an ordinary day's ground")
        self.assertEqual(into["inNewColour"], room["special"]["tinted"], "as many grounds tinted as a window opened that day")
        self.assertTrue(into["sceneShown"])

    def test_w2_a_caption_button_fills_only_the_day_under_it(self):
        """Each button paints the day under it every frame: it filled every speck and the whole scene, clipped away."""
        special = self.answer["room"]["special"]
        self.assertGreater(special["sceneFilled"], 10)
        self.assertLess(special["buttonFilled"], special["sceneFilled"] / 3, special)

    def test_w2_a_frame_of_the_band_costs_little(self):
        """About what a frame of the scene alone costs, timed beside it in the same process (audit Z5): never a number of
        milliseconds, which a loaded runner breaks without the frame doing any more."""
        special = self.answer["room"]["special"]
        self.assertLess(special["frameMs"], FRAME_OVER_SCENE * special["sceneMs"], special)

    def test_every_window_s_header_is_the_dashboard_s_whichever_read_came_back_last(self):
        """Fails without DayHeaderSettle on any date and any machine: the header was the last read's, the status (unanswered
        here, "Status unavailable") or the Dashboard's, and which came last was the wall clock's - a window that lived past
        its clock's five-second read took the Dashboard's (2026-11-27: three tests red alone, green the run after)."""
        dashboard_last, status_last = self.answer["settled"]
        unavailable = l10n.catalog("en")["status.unavailable"]
        self.assertEqual(status_last["before"], unavailable, "the status read forced last")
        self.assertNotEqual(dashboard_last["before"], unavailable, "the Dashboard's read forced last")
        for key in ("headline", "detail", "light", "tinted"):
            self.assertEqual(status_last[key], dashboard_last[key], key)
        self.assertEqual(status_last["headline"], dashboard_last["before"], "the Dashboard's words, as its read left them")
        room = self.answer["room"]
        self.assertEqual(room["special"]["headline"], room["plain"]["headline"])
        self.assertEqual(room["special"]["light"], room["plain"]["light"])

    def test_with_no_room_there_is_no_scene_and_no_slice_of_it(self):
        no_room = self.answer["noRoom"]
        self.assertTrue(no_room["special"]["look"], "a special day")
        self.assertGreater(len(no_room["special"]["headline"]), 100, "the long headline was still in place when drawn")
        self.assertFalse(no_room["special"]["sceneShown"])
        self.assertEqual(no_room["behindButtons"], 0, "no slice behind the caption buttons")
        self.assertEqual(no_room["card"], 0, "the card is as on an ordinary day")


class DayHeaderWiringTests(unittest.TestCase):
    def test_a_picture_lays_the_scene_down_before_the_caption_buttons(self):
        body = guiscan.member_body("SettingsForm", "RenderPicture")
        self.assertIn("PaintSceneOver(picture, this);", body)
        self.assertLess(body.index("PaintSceneOver(picture, this);"), body.index("PaintCaptionOver(picture, this);"))


if __name__ == "__main__":
    unittest.main()
