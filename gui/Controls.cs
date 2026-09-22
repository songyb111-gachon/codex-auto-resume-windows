// Codex Auto Resume - the soft controls the window is drawn with.
//
// v0.6.4 puts the window on the same material as the panel in Codex: a canvas, cards of the
// same stuff lifted by the panel's own two soft shadows, controls resting on them with a
// smaller pair, and values sitting in wells with the inset pair. Every colour, size and shadow
// comes from gui/Brand.cs, generated from src/codex_auto_resume/brand.py, which is also where
// the panel's stylesheet and the tray popup read theirs.
//
// Three rules hold for everything here:
//
// * Nothing depends on seeing a shadow. Every card and control keeps a hairline edge, every
//   state has a word beside its colour, and in High Contrast mode the shadows, tints and
//   motion are gone and system colours are used throughout.
// * Every control is still the standard control underneath - a Button is a Button, a check
//   box a CheckBox, a choice a RadioButton - so keyboard, focus and screen readers behave as
//   they always did. Only the painting is ours.
// * Motion is a state, not decoration, and it stops when Windows is asked to reduce motion,
//   when this product's own "Reduce motion" setting is on, or when nothing is visible.
//
// v0.6.4 adds the dark theme. The window decides its theme once, as it opens (Theme.Resolve):
// the Theme setting, Windows' app mode when that is "system", and High Contrast over both. It
// then draws every colour and every shadow from Palette and Tokens, which hold that one theme
// - never from Brand's light fields directly - so a change of theme is a new window
// (SettingsForm.Reopen), not a repaint.
//
// A child window cannot paint outside itself, so a lift is not drawn by the control that has
// it: the container behind it - its ground - stamps the shadow before the control paints its
// body, and the control repaints only its rounded corners from that ground (see Ground).
//
// C# 5 (the in-box compiler): no string interpolation, no null-conditional operator. No string
// switch and no initialized constant array either: both make the compiler emit a randomly
// named class, and build/normalize_pe.py refuses an executable that has one.

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
    /// Which theme the window is drawn in.
    ///
    /// The Theme setting is "system", "light" or "dark". "system" follows Windows' app mode -
    /// HKCU\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize, AppsUseLightTheme: 0 is
    /// dark, anything else or nothing is light - and High Contrast wins over every choice. The
    /// answer is one of "light", "dark" and "contrast", and it is decided once, as the window opens.
    internal static class Theme
    {
        internal const string System = "system";
        internal const string Light = "light";
        internal const string Dark = "dark";
        internal const string Contrast = "contrast";

        private const string PersonalizeKey = @"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize";

        /// The most a settings file may hold and still be read: settings.MAX_SETTINGS_BYTES.
        internal const int MaxSettingsBytes = 256 * 1024;

        private const int SPI_GETHIGHCONTRAST = 0x0042;
        private const int HCF_HIGHCONTRASTON = 0x0001;

        [StructLayout(LayoutKind.Sequential)]
        private struct HighContrastInfo
        {
            internal int Size;
            internal int Flags;
            internal IntPtr DefaultScheme;
        }

        [DllImport("user32.dll", EntryPoint = "SystemParametersInfoW")]
        private static extern bool SystemParametersInfo(int action, int parameter, ref HighContrastInfo info, int update);

        /// The Theme preference the window opened with; set once, by Program.Main.
        internal static string Opened = System;

        /// A stored Theme preference as the settings layer reads it: "light" or "dark" exactly, and
        /// "system" for anything else - a missing value, another case, another type.
        internal static string Preference(object value)
        {
            string text = value as string;
            return text == Light || text == Dark ? text : System;
        }

        /// The theme a window draws in. Pure, so the rule can be checked without a window.
        /// `appsUseLightTheme` is the registry value, or -1 when there is none.
        internal static string Resolve(string preference, int appsUseLightTheme, bool highContrast)
        {
            if (highContrast) return Contrast;
            string chosen = Preference(preference);
            if (chosen != System) return chosen;
            return appsUseLightTheme == 0 ? Dark : Light;
        }

        /// Windows' app mode as the registry holds it, or -1 when it cannot be read.
        internal static int AppsUseLightTheme()
        {
            try
            {
                using (Microsoft.Win32.RegistryKey key = Microsoft.Win32.Registry.CurrentUser.OpenSubKey(PersonalizeKey))
                {
                    object value = key == null ? null : key.GetValue("AppsUseLightTheme");
                    if (value is int) return (int)value;
                }
            }
            catch (Exception) { }
            return -1;
        }

        /// The theme this machine gives a preference right now.
        internal static string Current(string preference)
        {
            return Resolve(preference, AppsUseLightTheme(), ContrastOn());
        }

        /// Whether High Contrast is on as the window reads it - for Current, and for Palette's first theme:
        /// Windows, asked now (HighContrast). The window never sets it. It is the one input a probe stands its
        /// own answer in, so what follows from it is tested alike on every machine - on one with High Contrast
        /// on, every step of a theme change was skipped - and never by changing Windows' own setting. Null
        /// reads as Windows.
        internal static Func<bool> HighContrastOn = HighContrast;

        /// High Contrast as the window reads it (HighContrastOn).
        internal static bool ContrastOn()
        {
            Func<bool> on = HighContrastOn;
            return on != null ? on() : HighContrast();
        }

        /// Whether High Contrast is on, asked of Windows now. Not SystemInformation.HighContrast: .NET keeps
        /// that from its first read until its own hidden window has handled the change, and the window's
        /// WM_SETTINGCHANGE for turning High Contrast on is handled first (SettingsForm.WndProc) - asked
        /// there, it answered with the old value, and the window kept its colours under High Contrast.
        internal static bool HighContrast()
        {
            try
            {
                var info = new HighContrastInfo();
                info.Size = Marshal.SizeOf(typeof(HighContrastInfo));
                info.Flags = 0;
                info.DefaultScheme = IntPtr.Zero;
                if (SystemParametersInfo(SPI_GETHIGHCONTRAST, info.Size, ref info, 0))
                    return (info.Flags & HCF_HIGHCONTRASTON) != 0;
            }
            catch (Exception) { /* Windows could not be asked: .NET's copy, stale only while a change is on its way */ }
            return SystemInformation.HighContrast;
        }

        /// The Theme preference an installation's settings store, read from its settings file before
        /// anything is drawn: the bridge that reads it properly takes a Python start, and every colour
        /// is decided before the first control exists. The first settings read through the bridge
        /// confirms it (SettingsForm.Observe), so the file is read exactly as settings.load reads it for
        /// the bridge: no more than MaxSettingsBytes, UTF-8 with no byte order mark and no invalid byte,
        /// and one JSON value with nothing after it. Any other file is the defaults to the settings layer,
        /// so it is "system" here too, as is no file at all - a file the two read differently opened the
        /// window in one theme and had its first read reopen it in the other, every time it was opened.
        internal static string Stored(string root)
        {
            try
            {
                var file = new FileInfo(Path.Combine(Path.Combine(root, "config"), "settings.json"));
                if (!file.Exists || file.Length > MaxSettingsBytes) return System;
                string text = new UTF8Encoding(false, true).GetString(File.ReadAllBytes(file.FullName));
                if (text.Length > 0 && text[0] == '\uFEFF') return System;
                var map = Json.ParseDocument(text) as Dictionary<string, object>;
                object value;
                return map != null && map.TryGetValue("theme", out value) ? Preference(value) : System;
            }
            catch (Exception)
            {
                return System;
            }
        }
    }

    /// The brand colours of the theme in effect - Brand's or Brand.Dark's, never a system colour.
    /// What High Contrast replaces is Palette's business; a few rules that name the High Contrast
    /// colour themselves (the scroll bar's) read the brand half here.
    internal static class Tokens
    {
        internal static bool Dark;
        internal static Color Ink, Muted, Line, Surface, Canvas, Raised, Inset, Accent, AccentHover, AccentPressed,
                              OnAccent, AccentSoft, Focus, Active, Idle, Attention, Success, Waiting, Warning, Danger,
                              Paused, Card, ShadowDark, ShadowLight;

        static Tokens()
        {
            Adopt(false);
        }

        internal static void Adopt(bool dark)
        {
            Dark = dark;
            if (dark)
            {
                Ink = Brand.Dark.Ink; Muted = Brand.Dark.Muted; Line = Brand.Dark.Line; Surface = Brand.Dark.Surface;
                Canvas = Brand.Dark.Canvas; Raised = Brand.Dark.Raised; Inset = Brand.Dark.Inset; Accent = Brand.Dark.Accent;
                AccentHover = Brand.Dark.AccentHover; AccentPressed = Brand.Dark.AccentPressed; OnAccent = Brand.Dark.OnAccent;
                AccentSoft = Brand.Dark.AccentSoft; Focus = Brand.Dark.Focus; Active = Brand.Dark.Active; Idle = Brand.Dark.Idle;
                Attention = Brand.Dark.Attention; Success = Brand.Dark.Success; Waiting = Brand.Dark.Waiting;
                Warning = Brand.Dark.Warning; Danger = Brand.Dark.Danger; Paused = Brand.Dark.Paused;
                Card = Brand.Dark.CardGround; ShadowDark = Brand.Dark.ShadowDark; ShadowLight = Brand.Dark.ShadowLight;
            }
            else
            {
                Ink = Brand.Ink; Muted = Brand.Muted; Line = Brand.Line; Surface = Brand.Surface;
                Canvas = Brand.Canvas; Raised = Brand.Raised; Inset = Brand.Inset; Accent = Brand.Accent;
                AccentHover = Brand.AccentHover; AccentPressed = Brand.AccentPressed; OnAccent = Brand.OnAccent;
                AccentSoft = Brand.AccentSoft; Focus = Brand.Focus; Active = Brand.Active; Idle = Brand.Idle;
                Attention = Brand.Attention; Success = Brand.Success; Waiting = Brand.Waiting;
                Warning = Brand.Warning; Danger = Brand.Danger; Paused = Brand.Paused;
                Card = Brand.CardGround; ShadowDark = Brand.ShadowDark; ShadowLight = Brand.ShadowLight;
            }
        }
    }

    /// The palette as the window uses it, with High Contrast honoured in one place. Light until the
    /// window adopts its theme (Adopt), which Program.Main does before the first control is made.
    internal static class Palette
    {
        /// "light", "dark" or "contrast".
        internal static string Theme = CodexAutoResume.Theme.Light;
        internal static bool Contrast;
        internal static Color Ink, Muted, Secondary, Line, Surface, Canvas, Raised, Inset, Accent, AccentHover,
                              AccentPressed, OnAccent, AccentSoft, Focus, Active, Idle, Attention, Success, Waiting,
                              Warning, Danger, Paused;
        /// A card's own ground: the surface in light, the surface lifted a step toward raised in dark.
        internal static Color Card;

        static Palette()
        {
            Adopt(CodexAutoResume.Theme.ContrastOn() ? CodexAutoResume.Theme.Contrast : CodexAutoResume.Theme.Light);
        }

        /// Draws everything from here on in `theme`: "light", "dark" or "contrast". Anything else is light.
        internal static void Adopt(string theme)
        {
            Contrast = theme == CodexAutoResume.Theme.Contrast;
            bool dark = theme == CodexAutoResume.Theme.Dark;
            Theme = Contrast ? CodexAutoResume.Theme.Contrast : dark ? CodexAutoResume.Theme.Dark : CodexAutoResume.Theme.Light;
            Tokens.Adopt(dark);
            Elevation.Forget();
            Ink           = Contrast ? SystemColors.WindowText : Tokens.Ink;
            Muted         = Contrast ? SystemColors.GrayText : Tokens.Muted;
            Secondary     = Contrast ? SystemColors.WindowText : Tokens.Muted;
            Line          = Contrast ? SystemColors.WindowFrame : Tokens.Line;
            Surface       = Contrast ? SystemColors.Window : Tokens.Surface;
            Card          = Contrast ? SystemColors.Window : Tokens.Card;
            Canvas        = Contrast ? SystemColors.Control : Tokens.Canvas;
            Raised        = Contrast ? SystemColors.Window : Tokens.Raised;
            Inset         = Contrast ? SystemColors.Window : Tokens.Inset;
            Accent        = Contrast ? SystemColors.Highlight : Tokens.Accent;
            AccentHover   = Contrast ? SystemColors.Highlight : Tokens.AccentHover;
            AccentPressed = Contrast ? SystemColors.Highlight : Tokens.AccentPressed;
            OnAccent      = Contrast ? SystemColors.HighlightText : Tokens.OnAccent;
            AccentSoft    = Contrast ? SystemColors.Highlight : Tokens.AccentSoft;
            Focus         = Contrast ? SystemColors.WindowText : Tokens.Focus;
            Active        = Contrast ? SystemColors.Highlight : Tokens.Active;
            Idle          = Contrast ? SystemColors.GrayText : Tokens.Idle;
            Attention     = Contrast ? SystemColors.WindowText : Tokens.Attention;
            Success       = Contrast ? SystemColors.WindowText : Tokens.Success;
            Waiting       = Contrast ? SystemColors.WindowText : Tokens.Waiting;
            Warning       = Contrast ? SystemColors.WindowText : Tokens.Warning;
            Danger        = Contrast ? SystemColors.WindowText : Tokens.Danger;
            Paused        = Contrast ? SystemColors.GrayText : Tokens.Paused;
        }

        /// Whether the window is drawn dark: the dark theme, and not High Contrast.
        internal static bool Dark
        {
            get { return Tokens.Dark && !Contrast; }
        }
    }

    /// Drawing helpers shared by every soft control.
    internal static class Soft
    {
        [DllImport("user32.dll")]
        private static extern bool SystemParametersInfo(int action, int param, ref bool value, int winIni);

        [DllImport("user32.dll")]
        private static extern int GetWindowLong(IntPtr window, int index);

        private const int SPI_GETCLIENTAREAANIMATION = 0x1042;
        private const int GWL_STYLE = -16;
        private const int WS_VISIBLE = 0x10000000;

        /// This product's own "Reduce motion" setting, adopted when the settings are read.
        internal static bool ReduceMotionSetting;

        /// Windows' "Animation effects" switch as ReduceMotion reads it: Windows, asked each time
        /// (WindowsAnimationEffects). The window never sets it. It is the one input a probe stands its own
        /// answer in, so motion is tested alike on every machine - GitHub's Windows runner has the switch
        /// off, and there every glide was immediate and the tests of the glide failed or were skipped -
        /// and never by changing Windows' own setting. Null reads as a Windows that could not be asked.
        internal static Func<bool> WindowsAnimates = WindowsAnimationEffects;

        /// Windows' "Animation effects" switch (SPI_GETCLIENTAREAANIMATION), asked now: true while it is on,
        /// and when Windows cannot be asked.
        internal static bool WindowsAnimationEffects()
        {
            try
            {
                bool animate = true;
                if (SystemParametersInfo(SPI_GETCLIENTAREAANIMATION, 0, ref animate, 0)) return animate;
            }
            catch (Exception) { }
            return true;
        }

        /// Whether anything may move. Windows' "Animation effects" switch, this product's own
        /// setting, and High Contrast each turn motion off; nothing turns it back on.
        internal static bool ReduceMotion
        {
            get
            {
                if (ReduceMotionSetting || Palette.Contrast) return true;
                Func<bool> animates = WindowsAnimates;
                try
                {
                    return animates != null && !animates();
                }
                catch (Exception) { }
                return false;
            }
        }

        internal static int Px(int atNinetySix)
        {
            return (int)Math.Round(atNinetySix * SettingsForm.DpiScale);
        }

        internal static float PxF(double atNinetySix)
        {
            return (float)(atNinetySix * SettingsForm.DpiScale);
        }

        /// A 1px hairline in device pixels: whole pixels only, as the panel's border is drawn, so it
        /// stays crisp - one pixel up to 199%, two at 200%.
        internal static int Hairline
        {
            get { return Math.Max(1, (int)Math.Floor(SettingsForm.DpiScale + 1e-6)); }
        }

        /// Whether a control is shown as far as its own window goes, whatever its parents are.
        /// `Visible` answers false for everything inside a window that has not been shown yet,
        /// which would leave a capture of that window without a single shadow.
        internal static bool Shown(Control control)
        {
            if (!control.IsHandleCreated) return control.Visible;
            return (GetWindowLong(control.Handle, GWL_STYLE) & WS_VISIBLE) != 0;
        }

        private static readonly System.Reflection.MethodInfo OwnState =
            typeof(Control).GetMethod("GetState", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance);

        /// Whether a control was told to be visible, which is whether layout makes room for it -
        /// whatever its parents are, and with or without a window.
        internal static bool OwnVisible(Control control)
        {
            return OwnState == null ? control.Visible : (bool)OwnState.Invoke(control, new object[] { 2 });
        }

        /// Hands a turn of the wheel that `control` would not use to the nearest page around it that
        /// can still scroll that way. True when one did.
        internal static bool PassWheel(Control control, int delta)
        {
            for (Control c = control == null ? null : control.Parent; c != null; c = c.Parent)
            {
                var page = c as SoftPage;
                if (page != null && page.Wheel(delta)) return true;
            }
            return false;
        }

        /// Whether two colours are the same to look at: within a step of each other on every channel.
        /// The tokens a ground can be are far further apart than this, so it names one without matching
        /// a literal.
        internal static bool Near(Color one, Color other)
        {
            return Math.Abs(one.R - other.R) <= 2 && Math.Abs(one.G - other.G) <= 2
                   && Math.Abs(one.B - other.B) <= 2;
        }

        internal static Color Mix(Color from, Color to, double amount)
        {
            amount = Math.Max(0, Math.Min(1, amount));
            return Color.FromArgb(
                (int)Math.Round(from.R + (to.R - from.R) * amount),
                (int)Math.Round(from.G + (to.G - from.G) * amount),
                (int)Math.Round(from.B + (to.B - from.B) * amount));
        }

        internal static Color WithAlpha(Color colour, double opacity)
        {
            return Color.FromArgb((int)Math.Round(255 * Math.Max(0, Math.Min(1, opacity))), colour);
        }

        internal static GraphicsPath Rounded(RectangleF bounds, float radius)
        {
            var path = new GraphicsPath();
            float diameter = Math.Min(radius * 2, Math.Min(bounds.Width, bounds.Height));
            if (diameter <= 1f)
            {
                path.AddRectangle(bounds);
                return path;
            }
            path.AddArc(bounds.X, bounds.Y, diameter, diameter, 180, 90);
            path.AddArc(bounds.Right - diameter, bounds.Y, diameter, diameter, 270, 90);
            path.AddArc(bounds.Right - diameter, bounds.Bottom - diameter, diameter, diameter, 0, 90);
            path.AddArc(bounds.X, bounds.Bottom - diameter, diameter, diameter, 90, 90);
            path.CloseFigure();
            return path;
        }

        /// A body filling `face`: the fill, then the hairline inside its edge - the panel's
        /// `background` and `border: 1px solid`. The caller has already painted what lies
        /// behind the corners, and any inset shadow goes between the two (`inset`).
        internal static void Body(Graphics g, Rectangle face, float radius, Color fill, Color edge, bool inset)
        {
            Body(g, face, radius, fill, edge, inset ? "inset" : null);
        }

        /// The same, with the inset shadows of the elevation recipe `inner` between the fill and the
        /// hairline: a well's ("inset"), or in dark a card's one-pixel top light ("card"). Null for none.
        internal static void Body(Graphics g, Rectangle face, float radius, Color fill, Color edge, string inner)
        {
            GraphicsState state = g.Save();
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.PixelOffsetMode = PixelOffsetMode.Half;
            using (var path = Rounded(face, radius))
            using (var brush = new SolidBrush(fill))
                g.FillPath(brush, path);
            int hairline = Hairline;
            if (inner != null)
                Elevation.StampInner(g, Rectangle.Inflate(face, -hairline, -hairline), inner, radius - hairline, face);
            Edge(g, face, radius, edge, hairline);
            g.Restore(state);
        }

        [DllImport("dwmapi.dll")]
        private static extern int DwmSetWindowAttribute(IntPtr window, int attribute, ref int value, int size);

        [DllImport("uxtheme.dll", CharSet = CharSet.Unicode)]
        private static extern int SetWindowTheme(IntPtr window, string application, string idList);

        // DWMWA_USE_IMMERSIVE_DARK_MODE: 20 from Windows 10 20H1, 19 on the builds before it.
        internal const int DarkTitleBarAttribute = 20;
        internal const int DarkTitleBarAttributeBefore20H1 = 19;

        /// A top-level window's title bar in the dark theme, as Windows draws its own dark apps'. Nothing
        /// in light or High Contrast; a Windows that knows neither attribute keeps its light title bar.
        internal static void TitleBar(Form form)
        {
            if (!Palette.Dark || form == null) return;
            EventHandler apply = delegate
            {
                int on = 1;
                try
                {
                    if (DwmSetWindowAttribute(form.Handle, DarkTitleBarAttribute, ref on, 4) != 0)
                        DwmSetWindowAttribute(form.Handle, DarkTitleBarAttributeBefore20H1, ref on, 4);
                }
                catch (Exception) { /* no dwmapi, or no such attribute: the title bar stays light */ }
            };
            form.HandleCreated += apply;
            if (form.IsHandleCreated) apply(form, EventArgs.Empty);
        }

        /// The scroll bars Windows draws on a native control - a text box's - in its dark style, in the
        /// dark theme only. Best effort: an older Windows keeps its light ones.
        internal static void NativeScrollBars(Control control)
        {
            if (!Palette.Dark || control == null) return;
            EventHandler apply = delegate
            {
                try { SetWindowTheme(control.Handle, "DarkMode_Explorer", null); }
                catch (Exception) { }
            };
            control.HandleCreated += apply;
            if (control.IsHandleCreated) apply(control, EventArgs.Empty);
        }

        /// A line `width` device pixels wide, just inside the edge of a body filling `face`.
        internal static void Edge(Graphics g, Rectangle face, float radius, Color colour, float width)
        {
            GraphicsState state = g.Save();
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.PixelOffsetMode = PixelOffsetMode.Half;
            var inner = new RectangleF(face.X + width / 2f, face.Y + width / 2f, face.Width - width, face.Height - width);
            using (var path = Rounded(inner, Math.Max(0f, radius - width / 2f)))
            using (var pen = new Pen(colour, width))
                g.DrawPath(pen, path);
            g.Restore(state);
        }

        /// A shallow well a value sits in: the inset fill, the inset shadow, the hairline, or a
        /// two-pixel focus line inside the edge while it has the keyboard. The panel draws its
        /// focus outline outside the field; a child window cannot, so it goes inside.
        internal static void InsetWell(Graphics g, Rectangle face, float radius, bool focused)
        {
            Body(g, face, radius, Palette.Inset, Palette.Line, !Palette.Contrast);
            if (focused) Edge(g, face, radius, Palette.Focus, PxF(Brand.FocusWidth));
        }

        /// The well at a position that need not be whole pixels, for a page that draws one
        /// inside a cell rather than as a control.
        internal static void Well(Graphics g, RectangleF body, float radius, bool focused)
        {
            InsetWell(g, Rectangle.Round(body), radius, focused);
        }

        /// The switch every true-or-false setting is drawn as: a 40 by 22 pill, a well with a
        /// grey knob at the left when off, the accent with a white knob at the right when on.
        /// Disabled, the track and knob fade halfway into `ground`; the words beside it say
        /// the rest.
        internal static void Switch(Graphics g, Rectangle track, bool on, bool enabled, Color ground)
        {
            SwitchAt(g, track, on ? 1.0 : 0.0, enabled, ground);
        }

        /// The switch `on` of the way from off (0) to on (1), as it glides between them (v0.6.5): the
        /// knob that far along its travel and between its two colours, and the accent laid over the
        /// well at that opacity, so the track cross-fades from the grey well to the accent. At 0 and 1
        /// it is exactly the switch at rest.
        internal static void SwitchAt(Graphics g, Rectangle track, double on, bool enabled, Color ground)
        {
            on = Math.Max(0.0, Math.Min(1.0, on));
            float radius = track.Height / 2f;
            Color offFill = Palette.Inset, offEdge = Palette.Line, onFill = Palette.Accent, onEdge = Palette.Accent;
            Color offKnob = Palette.Contrast ? SystemColors.WindowText : Palette.Muted, onKnob = Palette.OnAccent;
            if (!enabled && !Palette.Contrast)
            {
                offFill = Mix(offFill, ground, 0.5);
                offEdge = Mix(offEdge, ground, 0.5);
                offKnob = Mix(offKnob, ground, 0.5);
                onFill = Mix(onFill, ground, 0.5);
                onEdge = Mix(onEdge, ground, 0.5);
                onKnob = Mix(onKnob, ground, 0.5);
            }
            if (on >= 1.0) Body(g, track, radius, onFill, onEdge, false);
            else
            {
                Body(g, track, radius, offFill, offEdge, enabled && !Palette.Contrast);
                if (on > 0.0)
                {
                    GraphicsState faded = g.Save();
                    g.SmoothingMode = SmoothingMode.AntiAlias;
                    g.PixelOffsetMode = PixelOffsetMode.Half;
                    using (var path = Rounded(track, radius))
                    using (var brush = new SolidBrush(WithAlpha(onFill, on)))
                        g.FillPath(brush, path);
                    g.Restore(faded);
                    Edge(g, track, radius, WithAlpha(onEdge, on), Hairline);
                }
            }
            float size = PxF(Brand.Knob), inset = PxF(Brand.KnobInset);
            float x = track.X + inset + (float)(PxF(Brand.KnobTravel) * on);
            Color knob = on <= 0.0 ? offKnob : on >= 1.0 ? onKnob : Mix(offKnob, onKnob, on);
            GraphicsState state = g.Save();
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.PixelOffsetMode = PixelOffsetMode.Half;
            using (var brush = new SolidBrush(knob))
                g.FillEllipse(brush, x, track.Y + (track.Height - size) / 2f, size, size);
            g.Restore(state);
        }

        /// Draws `image` over `dest` at `opacity`, for a part fading in over what is already there.
        internal static void Faded(Graphics g, Image image, Rectangle dest, double opacity)
        {
            if (opacity <= 0.0) return;
            if (opacity >= 1.0)
            {
                g.DrawImage(image, dest, 0, 0, image.Width, image.Height, GraphicsUnit.Pixel);
                return;
            }
            var matrix = new ColorMatrix();
            matrix.Matrix33 = (float)opacity;
            using (var attributes = new ImageAttributes())
            {
                attributes.SetColorMatrix(matrix);
                g.DrawImage(image, dest, 0, 0, image.Width, image.Height, GraphicsUnit.Pixel, attributes);
            }
        }

        /// The keyboard focus ring as the panel draws it: two pixels wide, two pixels out from
        /// the face, its corners following the face's.
        internal static void Ring(Graphics g, Rectangle face, float radius)
        {
            GraphicsState state = g.Save();
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.PixelOffsetMode = PixelOffsetMode.Half;
            float width = PxF(Brand.FocusWidth), middle = PxF(Brand.FocusOffset) + width / 2f;
            var ring = new RectangleF(face.X - middle, face.Y - middle, face.Width + middle * 2f, face.Height + middle * 2f);
            using (var path = Rounded(ring, radius + middle))
            using (var pen = new Pen(Palette.Focus, width))
                g.DrawPath(pen, path);
            g.Restore(state);
        }

        /// The older ring, drawn inside a control that insets its own body.
        internal static void FocusRing(Graphics g, RectangleF around, float radius)
        {
            g.SmoothingMode = SmoothingMode.AntiAlias;
            float gap = PxF(2);
            var ring = new RectangleF(around.X - gap, around.Y - gap, around.Width + gap * 2, around.Height + gap * 2);
            using (var path = Rounded(ring, radius + gap))
            using (var pen = new Pen(Palette.Focus, PxF(2)))
                g.DrawPath(pen, path);
        }

        // ------------------------------------------------------------------ type

        private static Font baseFont;
        private static readonly Dictionary<string, Font> fonts = new Dictionary<string, Font>();

        /// The font every role is a variant of: the window's, which is Windows' message font.
        /// Settable so a measurement can stand in another scale's or another system's font.
        internal static Font BaseFont
        {
            get
            {
                if (baseFont == null) baseFont = SystemFonts.MessageBoxFont;
                return baseFont;
            }
            set
            {
                // The old fonts are not disposed: a control may still be drawing with one.
                baseFont = value;
                fonts.Clear();
            }
        }

        /// A font for a role in the panel's type table, at the size the window has always used
        /// for it - only the weight follows the panel. Cached: a page switch used to create two
        /// fonts every time, and a cached font must never be disposed by whoever asked for it.
        ///
        /// body, help, count: the window's font. label, button, chip, nav: the same (500, which
        /// is Regular). heading, name, nav_current: 600. title: 1.5pt larger, 600 (card
        /// headings). display: 2.5pt larger, 600 (the header). figure: 3pt larger, 600 (the
        /// Overview's count of what is waiting).
        internal static Font RoleFont(string role)
        {
            Font font;
            string key = role ?? "body";
            if (fonts.TryGetValue(key, out font)) return font;
            float larger = key == "display" ? 2.5f : key == "title" ? 1.5f : key == "figure" ? 3f : 0f;
            int weight = key == "heading" || key == "name" || key == "nav_current" || key == "title" ||
                         key == "display" || key == "figure" ? 600
                       : key == "label" || key == "button" || key == "chip" || key == "nav" ? 500 : 400;
            font = Weighted(BaseFont, BaseFont.SizeInPoints + larger, weight);
            fonts[key] = font;
            return font;
        }

        /// A CSS weight in GDI. 400 and 500 are Regular: Malgun Gothic and the CJK UI faces have
        /// no medium, and a medium Segoe UI would run wider than every label was measured at.
        /// 600 is the face's own semibold where it has one ("Segoe UI" and its variants), and
        /// Bold otherwise.
        internal static Font Weighted(Font from, float points, int weight)
        {
            if (weight < 600) return new Font(from.FontFamily, points, FontStyle.Regular, GraphicsUnit.Point);
            string family = from.FontFamily.Name;
            if (family.StartsWith("Segoe UI", StringComparison.Ordinal) && !family.EndsWith("Semibold", StringComparison.Ordinal))
            {
                try
                {
                    using (var semibold = new FontFamily(family + " Semibold"))
                        return new Font(semibold.Name, points, FontStyle.Regular, GraphicsUnit.Point);
                }
                catch (ArgumentException) { /* not installed: Bold, below */ }
            }
            return new Font(from.FontFamily, points, FontStyle.Bold, GraphicsUnit.Point);
        }

        // ------------------------------------------------------------------ chips

        /// The tinted ground a state word sits on: the state's colour, faint, over the surface.
        internal static Color Tint(Color tone, Color over)
        {
            return Palette.Contrast ? over : Mix(over, tone, 0.12);
        }

        internal static Size ChipSize(string text, Font font)
        {
            Size measured = TextRenderer.MeasureText(text ?? "", font, new Size(int.MaxValue, int.MaxValue),
                                                     TextFormatFlags.SingleLine | TextFormatFlags.NoPadding);
            return new Size(measured.Width + Px(Brand.ChipPadX * 2), measured.Height + Px(6));
        }

        /// A pill with a state word, in the chip role's font. Returns how wide it was drawn.
        internal static int Chip(Graphics g, Rectangle cell, string text, Color tone)
        {
            return Chip(g, cell, text, RoleFont("chip"), tone, Palette.Surface);
        }

        /// A pill with a state word: no border and no shadow, its ground the state's colour at
        /// 12% over the surface whatever it sits on, as the panel's chips are. In High Contrast
        /// the ground is `over`, the ground it sits on. Returns how wide it was drawn.
        internal static int Chip(Graphics g, Rectangle cell, string text, Font font, Color tone, Color over)
        {
            if (string.IsNullOrEmpty(text)) return 0;
            Size size = ChipSize(text, font);
            int width = Math.Min(size.Width, Math.Max(Px(Brand.CountMinWidth), cell.Width));
            var body = new RectangleF(cell.X, cell.Y + (float)Math.Floor((cell.Height - size.Height) / 2f), width, size.Height);
            GraphicsState state = g.Save();
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.PixelOffsetMode = PixelOffsetMode.Half;
            using (var path = Rounded(body, body.Height / 2f))
            using (var brush = new SolidBrush(Palette.Contrast ? over : Mix(Palette.Surface, tone, 0.12)))
                g.FillPath(brush, path);
            g.Restore(state);
            TextRenderer.DrawText(g, text, font, Rectangle.Round(body), tone,
                                  TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter |
                                  TextFormatFlags.SingleLine | TextFormatFlags.EndEllipsis | TextFormatFlags.NoPadding);
            return width;
        }

        // ------------------------------------------------------------------ lines

        /// Whether `text` has Korean in it, whose words Windows' own wrapping splits (Wrap).
        internal static bool SplitsWords(string text)
        {
            if (string.IsNullOrEmpty(text)) return false;
            foreach (char c in text)
                if ((c >= '\uAC00' && c <= '\uD7AF') || (c >= '\u1100' && c <= '\u11FF') || (c >= '\u3130' && c <= '\u318F') ||
                    (c >= '\uA960' && c <= '\uA97F') || (c >= '\uD7B0' && c <= '\uD7FF'))
                    return true;
            return false;
        }

        /// A character a line may end before or after: Chinese and Japanese are set without spaces - the ranges of
        /// tray_popup's _breaks_anywhere.
        private static bool BreaksAnywhere(char c)
        {
            return (c >= '\u2E80' && c <= '\u9FFF') || (c >= '\uF900' && c <= '\uFAFF') || (c >= '\uFF00' && c <= '\uFFEF');
        }

        private static bool Space(char c)
        {
            return c == ' ' || c == '\t' || c == '\u3000';
        }

        private static readonly Dictionary<string, string> wrapped = new Dictionary<string, string>();

        /// `text` broken into the lines it is drawn in, `width` wide in `font` as TextRenderer draws it with `format`
        /// (v0.6.5): a line ends at a space, and in a run of Chinese or Japanese between any two characters - never
        /// inside a Korean word. Windows' own wrapping breaks Korean between any two syllables, and was the only one
        /// of the three surfaces that split a word across two lines (the review found 'is locked or' cut
        /// after its first syllable in the notification card's help line); the popup breaks it at its
        /// spaces (tray_popup.unbroken) and the panel keeps its words whole (word-break: keep-all). So text with
        /// Korean in it comes back with a line break where each line ends, and Windows, given the same format and
        /// width, has nothing left to break; a word wider than the whole line is left on a line of its own, for
        /// Windows to break where it must, as the panel's overflow-wrap does. Anything without Korean comes back as
        /// it is, and Windows breaks it as it always has - Chinese and Japanese between characters, as the popup does.
        /// Measure and draw what this returns, never the text itself, or the two disagree.
        internal static string Wrap(string text, Font font, int width, TextFormatFlags format)
        {
            if (!SplitsWords(text) || font == null || width <= 0 || width >= 1000000) return text;
            string key = width.ToString() + "|" + ((int)format).ToString() + "|" + font.Name + "|" +
                         font.SizeInPoints.ToString("R", System.Globalization.CultureInfo.InvariantCulture) + "|" +
                         ((int)font.Style).ToString() + "|" + text;
            string found;
            if (wrapped.TryGetValue(key, out found)) return found;
            // One line as Windows measures it before it wraps: the same prefix and padding, on one line.
            TextFormatFlags line = (format & (TextFormatFlags.NoPrefix | TextFormatFlags.HidePrefix | TextFormatFlags.PrefixOnly |
                                              TextFormatFlags.NoPadding | TextFormatFlags.LeftAndRightPadding |
                                              TextFormatFlags.RightToLeft)) | TextFormatFlags.SingleLine;
            var lines = new StringBuilder();
            string[] paragraphs = text.Replace("\r\n", "\n").Split('\n');
            for (int p = 0; p < paragraphs.Length; p++)
            {
                if (p > 0) lines.Append('\n');
                WrapParagraph(paragraphs[p], font, width, line, lines);
            }
            string result = lines.ToString();
            if (wrapped.Count > 512) wrapped.Clear();
            wrapped[key] = result;
            return result;
        }

        /// Whether a line of `text` may end at `at`, before its character there.
        private static bool BreaksAt(string text, int at)
        {
            if (at >= text.Length) return true;
            if (at <= 0 || Space(text[at - 1])) return false;
            if (Space(text[at])) return true;
            return BreaksAnywhere(text[at - 1]) || BreaksAnywhere(text[at]);
        }

        // One paragraph onto `lines`, a line at a time: each as long as fits, ending where a line may end.
        private static void WrapParagraph(string text, Font font, int width, TextFormatFlags line, StringBuilder lines)
        {
            var ended = new List<string>();
            int start = 0, fits = -1;
            var unbounded = new Size(int.MaxValue, int.MaxValue);
            for (int at = 1; at <= text.Length; at++)
            {
                if (!BreaksAt(text, at)) continue;
                string candidate = text.Substring(start, at - start).TrimEnd(' ', '\t', '\u3000');
                if (candidate.Length == 0) continue;
                if (TextRenderer.MeasureText(candidate, font, unbounded, line).Width <= width)
                {
                    fits = at;
                    continue;
                }
                // Too wide: the line ends where it last fitted - or, a word wider than the whole line, after it.
                int end = fits > start ? fits : at;
                ended.Add(text.Substring(start, end - start).TrimEnd(' ', '\t', '\u3000'));
                start = end;
                while (start < text.Length && Space(text[start])) start++;
                fits = -1;
                at = start;
            }
            if (start < text.Length || ended.Count == 0) ended.Add(text.Substring(start));
            lines.Append(string.Join("\n", ended.ToArray()));
        }
    }

    /// How a change moves (v0.6.5): brand's one transition, MOTION["transition_ms"] - the 160 ms the
    /// panel's stylesheet emits as --transition - on brand's one curve, MOTION["ease"] (Brand.Ease, the
    /// panel's --transition-ease, the popup's brand.ease()), the same on every surface. It is an ease-out:
    /// a switch leaves at once and settles softly.
    ///
    /// Nothing moves when motion is reduced (Soft.ReduceMotion: this product's setting, Windows'
    /// animation effects, High Contrast), nor where it cannot be seen; the change is then immediate.
    internal static class Motion
    {
        /// A frame, in milliseconds: the soft scroll bar's glide rate.
        internal const int Interval = 15;

        internal static int Duration
        {
            get { return Brand.TransitionMs; }
        }

        /// The eased progress for `t` of the way through the time, both from 0 to 1: brand's curve.
        internal static double Ease(double t)
        {
            return Brand.Ease(t);
        }

        /// Whether `control` may animate a change now: motion is not reduced, and it is on screen - its own window
        /// visible (Soft.Shown) and every control it is in (Visible): a switch on a page or section not shown is not
        /// seen, and its change is immediate.
        internal static bool Allowed(Control control)
        {
            if (control == null || Soft.ReduceMotion || !control.IsHandleCreated || !Soft.Shown(control) || !control.Visible) return false;
            Form form = control.FindForm();
            return form == null || (form.Visible && form.WindowState != FormWindowState.Minimized);
        }
    }

    /// One value gliding to a new target over brand's transition, repainting part of its owner each
    /// frame and nothing else: no layout, and no timer left running once it has arrived.
    internal sealed class Transition : IDisposable
    {
        private readonly Control owner;
        private readonly Timer timer = new Timer();
        private readonly System.Diagnostics.Stopwatch clock = new System.Diagnostics.Stopwatch();
        private double from, to;

        internal Transition(Control owner, double value)
        {
            this.owner = owner;
            from = to = value;
            timer.Interval = Motion.Interval;
            timer.Tick += delegate { Tick(); };
        }

        /// What the owner repaints each frame, in its coordinates; the whole of it when empty.
        internal Rectangle Area;

        /// What the owner repaints each frame, worked out each frame, in place of Area: for a part that may move while
        /// it glides, as a row of a list that scrolls does. Nothing is repainted when it answers an empty rectangle - the
        /// part is not on screen.
        internal Func<Rectangle> Where;

        /// Where it is now.
        internal double Value
        {
            get
            {
                if (!timer.Enabled) return to;
                double t = clock.Elapsed.TotalMilliseconds / Math.Max(1, Motion.Duration);
                return t >= 1.0 ? to : from + (to - from) * Motion.Ease(t);
            }
        }

        /// Where it is going.
        internal double Target { get { return to; } }

        /// Whether it is on its way; its timer runs only then.
        internal bool Running { get { return timer.Enabled; } }

        /// Sends it to `target`: gliding there from wherever it is when `animate`, there at once otherwise.
        internal void To(double target, bool animate)
        {
            double now = Value;
            to = target;
            if (!animate || now == target)
            {
                timer.Stop();
                from = target;
                Repaint();
                return;
            }
            from = now;
            clock.Reset();
            clock.Start();
            if (!timer.Enabled) timer.Start();
            Repaint();
        }

        private void Tick()
        {
            if (clock.Elapsed.TotalMilliseconds >= Motion.Duration || owner.IsDisposed || !Soft.Shown(owner) || !owner.Visible)
            {
                timer.Stop();
                from = to;
            }
            Repaint();
        }

        private void Repaint()
        {
            if (owner.IsDisposed || !owner.IsHandleCreated) return;
            if (Where != null)
            {
                Rectangle part = Where();
                if (!part.IsEmpty) owner.Invalidate(part);
            }
            else if (Area.IsEmpty) owner.Invalidate();
            else owner.Invalidate(Area);
        }

        public void Dispose()
        {
            timer.Stop();
            timer.Dispose();
        }
    }

    /// The panel's shadows, drawn the way its stylesheet defines them.
    ///
    /// A CSS blur B is a Gaussian with sigma B/2, so one shadow's alpha at distance d from a
    /// straight edge is alpha * Phi((offset - d) / sigma) - brand.shadow_alpha, which matches
    /// the panel's own screenshot to about one colour level. Each shadow is computed once per
    /// shape and scale into a premultiplied bitmap - the rounded body's coverage, blurred with
    /// that Gaussian integrated over each pixel - and then stamped in nine pieces: the corners as
    /// they are, the one-pixel middle row and column stretched along the straight edges. A body
    /// too short to have a straight middle gets a bitmap of its exact length instead, which for
    /// buttons, fields and switches - all one height - is still only a handful.
    ///
    /// The recipes are the theme's (brand.SHADOWS): light's is a shadow and a highlight each, and
    /// dark's another shape - two drops and an inset one-pixel top light for a card, one drop for a
    /// control, one inset shadow for a well. So every shadow is read as Brand gives it, inset or not,
    /// and never inferred from the recipe's name. An outer shadow is stamped by the ground behind a
    /// body (StampOuter); an inset one by the body itself, between its fill and its hairline
    /// (StampInner, through Soft.Body).
    ///
    /// Nothing is drawn in High Contrast mode.
    internal static class Elevation
    {
        private sealed class Template
        {
            internal Bitmap Image;
            internal int MiddleX = -1, MiddleY = -1;   // the column and row that stretch; -1 draws it whole
        }

        // Stamped with nearest-neighbour sampling on half-pixel centres, so a one-pixel strip
        // stretches to exactly its own pixels and nothing bleeds in from beside it - which also
        // keeps GDI+ off the slow path that image attributes force on every draw.
        private static readonly Dictionary<long, Template> cache = new Dictionary<long, Template>();

        private static int RecipeId(string recipe)
        {
            if (recipe == "card") return 0;
            if (recipe == "control") return 1;
            if (recipe == "inset") return 2;
            return -1;
        }

        /// How many shadows `recipe` has in the theme in effect.
        internal static int Count(string recipe)
        {
            return Tokens.Dark ? Brand.Dark.ElevationCount(recipe) : Brand.ElevationCount(recipe);
        }

        /// Shadow `index` of `recipe` in the theme in effect, front to back as brand.SHADOWS lists it.
        private static bool Shadow(string recipe, int index, out double dx, out double dy, out double blur,
                                   out double alpha, out bool inset, out Color tone)
        {
            bool found = Tokens.Dark ? Brand.Dark.ElevationShadow(recipe, index, out dx, out dy, out blur, out alpha, out inset, out tone)
                                     : Brand.ElevationShadow(recipe, index, out dx, out dy, out blur, out alpha, out inset, out tone);
            alpha = Math.Round(alpha, 4);
            return found;
        }

        /// How far a recipe's outer shadows reach past its box, per side, in device pixels at the
        /// window's scale: offset plus three sigmas, past which a shadow is under a fifth of a
        /// percent of its strength (brand.reach). A ground that clips its children closer than
        /// this cuts their shadow off. Inset shadows reach nothing outside.
        internal static Padding Reach(string recipe)
        {
            return Reach(recipe, SettingsForm.DpiScale);
        }

        internal static Padding Reach(string recipe, double scale)
        {
            int left = 0, top = 0, right = 0, bottom = 0;
            for (int index = 0; index < Count(recipe); index++)
            {
                double dx, dy, blur, alpha;
                bool inset;
                Color tone;
                if (!Shadow(recipe, index, out dx, out dy, out blur, out alpha, out inset, out tone) || inset) continue;
                left = Math.Max(left, Far(-dx, blur, scale));
                top = Math.Max(top, Far(-dy, blur, scale));
                right = Math.Max(right, Far(dx, blur, scale));
                bottom = Math.Max(bottom, Far(dy, blur, scale));
            }
            return new Padding(left, top, right, bottom);
        }

        /// The reach above and to the left, where the highlight is.
        internal static int ReachNear(string recipe)
        {
            Padding reach = Reach(recipe);
            return Math.Max(reach.Left, reach.Top);
        }

        /// The reach below and to the right, where the shadow is.
        internal static int ReachFar(string recipe)
        {
            Padding reach = Reach(recipe);
            return Math.Max(reach.Right, reach.Bottom);
        }

        private static int Far(double offset, double blur, double scale)
        {
            return Math.Max(0, (int)Math.Ceiling((offset + 1.5 * blur) * scale - 1e-9));
        }

        /// A body's outer lift, "card" or "control", stamped around `body` (in the coordinates
        /// of `g`), drawing only the pieces that meet `clip`. Its inset shadows are the body's own.
        internal static void StampOuter(Graphics g, Rectangle body, string recipe, float radius, Rectangle clip)
        {
            if (Palette.Contrast || body.Width <= 0 || body.Height <= 0) return;
            int count = Count(recipe);
            if (count == 0) return;
            Padding reach = Reach(recipe);
            var band = new Rectangle(body.X - reach.Left, body.Y - reach.Top, body.Width + reach.Horizontal, body.Height + reach.Vertical);
            if (!band.IntersectsWith(clip)) return;
            // Last to first, as CSS paints a shadow list.
            for (int index = count - 1; index >= 0; index--)
                if (!IsInset(recipe, index)) StampOne(g, recipe, index, SettingsForm.DpiScale, body, radius, clip);
        }

        /// A well's inset shadow inside `box` - the well inside its hairline - whose corners have
        /// `radius`. It is already clipped to that shape.
        internal static void StampInset(Graphics g, Rectangle box, float radius, Rectangle clip)
        {
            StampInner(g, box, "inset", radius, clip);
        }

        /// The inset shadows of `recipe` inside `box`, the body inside its hairline.
        internal static void StampInner(Graphics g, Rectangle box, string recipe, float radius, Rectangle clip)
        {
            if (Palette.Contrast || box.Width <= 0 || box.Height <= 0 || !box.IntersectsWith(clip)) return;
            for (int index = Count(recipe) - 1; index >= 0; index--)
                if (IsInset(recipe, index)) StampOne(g, recipe, index, SettingsForm.DpiScale, box, radius, clip);
        }

        private static bool IsInset(string recipe, int index)
        {
            double dx, dy, blur, alpha;
            bool inset;
            Color tone;
            return Shadow(recipe, index, out dx, out dy, out blur, out alpha, out inset, out tone) && inset;
        }

        /// Drops every cached bitmap; the next stamp builds what it needs again.
        internal static void Forget()
        {
            foreach (Template template in cache.Values) template.Image.Dispose();
            cache.Clear();
        }

        internal static int Cached
        {
            get { return cache.Count; }
        }

        private static void StampOne(Graphics g, string recipe, int index, double scale, Rectangle body, float radius, Rectangle clip)
        {
            double dx, dy, blur, alpha;
            bool inset;
            Color tone;
            if (!Shadow(recipe, index, out dx, out dy, out blur, out alpha, out inset, out tone)) return;
            int reach = Spread(blur * scale / 2);
            radius = (float)Math.Max(0, Math.Min(radius, Math.Min(body.Width, body.Height) / 2.0));
            int core, pad, left = body.X, top = body.Y;
            double fx = 0, fy = 0;
            if (inset)
            {
                core = (int)Math.Ceiling(radius) + reach + (int)Math.Ceiling(Math.Max(Math.Abs(dx), Math.Abs(dy)) * scale) + 1;
                pad = 0;
            }
            else
            {
                // A shadow moved a fraction of a pixel keeps the fraction in its bitmap, so
                // 125% and 175% are as exact as the whole-pixel scales.
                int ix, iy;
                Whole(dx * scale, out ix, out fx);
                Whole(dy * scale, out iy, out fy);
                core = (int)Math.Ceiling(radius) + reach;
                pad = reach + 1;
                left = body.X + ix - pad;
                top = body.Y + iy - pad;
            }
            int canonical = 2 * core + 1;
            int width = body.Width >= canonical ? canonical : body.Width;
            int height = body.Height >= canonical ? canonical : body.Height;
            Template template = Get(recipe, index, scale, width, height, radius, fx, fy,
                                    width == canonical ? pad + core : -1, height == canonical ? pad + core : -1);

            GraphicsState state = g.Save();
            g.InterpolationMode = InterpolationMode.NearestNeighbor;
            g.PixelOffsetMode = PixelOffsetMode.Half;
            g.CompositingMode = CompositingMode.SourceOver;
            int across = body.Width + 2 * pad, down = body.Height + 2 * pad;
            int columns = template.MiddleX < 0 ? 1 : 3, rows = template.MiddleY < 0 ? 1 : 3;
            for (int row = 0; row < rows; row++)
            {
                int sourceY, sourceHeight, destY, destHeight;
                Span(template.MiddleY, template.Image.Height, down, row, out sourceY, out sourceHeight, out destY, out destHeight);
                for (int column = 0; column < columns; column++)
                {
                    // The middle of a sliced body lies under the body itself, or holds nothing.
                    if (row == 1 && column == 1) continue;
                    int sourceX, sourceWidth, destX, destWidth;
                    Span(template.MiddleX, template.Image.Width, across, column, out sourceX, out sourceWidth, out destX, out destWidth);
                    var dest = new Rectangle(left + destX, top + destY, destWidth, destHeight);
                    if (destWidth <= 0 || destHeight <= 0 || !dest.IntersectsWith(clip)) continue;
                    g.DrawImage(template.Image, dest, sourceX, sourceY, sourceWidth, sourceHeight, GraphicsUnit.Pixel);
                }
            }
            g.Restore(state);
        }

        private static void Whole(double value, out int whole, out double fraction)
        {
            whole = (int)Math.Floor(value);
            fraction = Math.Round((value - whole) * 8) / 8;
            if (fraction >= 1) { whole++; fraction = 0; }
        }

        /// One of the three pieces along an axis: before the middle, the middle stretched, after.
        private static void Span(int middle, int length, int total, int piece,
                                 out int source, out int sourceLength, out int dest, out int destLength)
        {
            if (middle < 0) { source = 0; sourceLength = length; dest = 0; destLength = length; return; }
            if (piece == 0) { source = 0; sourceLength = middle; dest = 0; destLength = middle; return; }
            int after = length - middle - 1;
            if (piece == 1) { source = middle; sourceLength = 1; dest = middle; destLength = total - middle - after; return; }
            source = middle + 1; sourceLength = after; dest = total - after; destLength = after;
        }

        private static Template Get(string recipe, int index, double scale, int width, int height, double radius,
                                    double fx, double fy, int middleX, int middleY)
        {
            // The theme, the recipe and the shadow, then the shape: a theme's bitmaps are never another's.
            long key = (Tokens.Dark ? 1 : 0) * 16 + Math.Max(0, RecipeId(recipe)) * 4 + Math.Min(3, index);
            key = key * 1024 + Math.Min(1023, (int)Math.Round(scale * 100));
            key = key * 4096 + Math.Min(4095, width);
            key = key * 4096 + Math.Min(4095, height);
            key = key * 16 + (int)Math.Round(fx * 8);
            key = key * 16 + (int)Math.Round(fy * 8);
            key = key * 16384 + Math.Min(16383, (int)Math.Round(radius * 8));
            Template template;
            if (cache.TryGetValue(key, out template)) return template;
            if (cache.Count >= 128) Forget();
            double dx, dy, blur, alpha;
            bool inset;
            Color tone;
            Shadow(recipe, index, out dx, out dy, out blur, out alpha, out inset, out tone);
            template = inset ? Inner(dx, dy, blur, alpha, tone, scale, width, height, radius)
                             : Outer(blur, alpha, tone, scale, width, height, radius, fx, fy);
            template.MiddleX = middleX;
            template.MiddleY = middleY;
            cache[key] = template;
            return template;
        }

        private static Template Outer(double blur, double alpha, Color tone, double scale, int width, int height,
                                      double radius, double fx, double fy)
        {
            double sigma = blur * scale / 2;
            int pad = Spread(sigma) + 1;
            int across = width + 2 * pad, down = height + 2 * pad;
            var shape = new double[across * down];
            Cover(shape, across, down, pad + fx, pad + fy, width, height, radius);
            return Make(Blur(shape, across, down, sigma), across, down, alpha, tone);
        }

        /// An inset shadow is cast by everything outside the box, moved by the offset, blurred,
        /// and seen only inside the box. With no blur - dark's one-pixel top light - it is that edge,
        /// moved, and nothing else.
        private static Template Inner(double dx, double dy, double blur, double alpha, Color tone, double scale,
                                      int width, int height, double radius)
        {
            double sigma = blur * scale / 2, ox = dx * scale, oy = dy * scale;
            int margin = Spread(sigma) + (int)Math.Ceiling(Math.Max(Math.Abs(ox), Math.Abs(oy))) + 1;
            int across = width + 2 * margin, down = height + 2 * margin;
            var outside = new double[across * down];
            Cover(outside, across, down, margin + ox, margin + oy, width, height, radius);
            for (int i = 0; i < outside.Length; i++) outside[i] = 1 - outside[i];
            double[] blurred = Blur(outside, across, down, sigma);
            var inside = new double[width * height];
            Cover(inside, width, height, 0, 0, width, height, radius);
            for (int y = 0; y < height; y++)
                for (int x = 0; x < width; x++)
                    inside[y * width + x] *= blurred[(y + margin) * across + x + margin];
            return Make(inside, width, height, alpha, tone);
        }

        private static Template Make(double[] values, int width, int height, double alpha, Color tone)
        {
            var pixels = new int[width * height];
            for (int i = 0; i < pixels.Length; i++)
            {
                int a = (int)Math.Round(255 * alpha * Math.Max(0, Math.Min(1, values[i])));
                if (a <= 0) continue;
                pixels[i] = (a << 24) | ((tone.R * a + 127) / 255 << 16) | ((tone.G * a + 127) / 255 << 8) | ((tone.B * a + 127) / 255);
            }
            var image = new Bitmap(width, height, PixelFormat.Format32bppPArgb);
            BitmapData data = image.LockBits(new Rectangle(0, 0, width, height), ImageLockMode.WriteOnly, PixelFormat.Format32bppPArgb);
            try
            {
                for (int y = 0; y < height; y++)
                    Marshal.Copy(pixels, y * width, new IntPtr(data.Scan0.ToInt64() + (long)y * data.Stride), width);
            }
            finally { image.UnlockBits(data); }
            var template = new Template();
            template.Image = image;
            return template;
        }

        /// Three sigmas, in whole pixels.
        private static int Spread(double sigma)
        {
            return sigma <= 0 ? 0 : (int)Math.Ceiling(3 * sigma - 1e-9);
        }

        /// How much of each pixel a rounded rectangle covers: sixteen samples where its edge
        /// crosses the pixel, one elsewhere.
        private static void Cover(double[] grid, int across, int down, double left, double top,
                                  double width, double height, double radius)
        {
            radius = Math.Max(0, Math.Min(radius, Math.Min(width, height) / 2));
            double cx = left + width / 2, cy = top + height / 2, hx = width / 2 - radius, hy = height / 2 - radius;
            for (int y = 0; y < down; y++)
                for (int x = 0; x < across; x++)
                {
                    double distance = Outside(x + 0.5 - cx, y + 0.5 - cy, hx, hy, radius);
                    double value;
                    if (distance <= -0.75) value = 1;
                    else if (distance >= 0.75) value = 0;
                    else
                    {
                        int hits = 0;
                        for (int sy = 0; sy < 4; sy++)
                            for (int sx = 0; sx < 4; sx++)
                                if (Outside(x + (sx + 0.5) / 4 - cx, y + (sy + 0.5) / 4 - cy, hx, hy, radius) <= 0) hits++;
                        value = hits / 16.0;
                    }
                    grid[y * across + x] = value;
                }
        }

        /// Signed distance from a rounded rectangle centred on the origin; negative inside.
        private static double Outside(double px, double py, double hx, double hy, double radius)
        {
            double qx = Math.Abs(px) - hx, qy = Math.Abs(py) - hy;
            double ox = Math.Max(qx, 0), oy = Math.Max(qy, 0);
            return Math.Sqrt(ox * ox + oy * oy) + Math.Min(Math.Max(qx, qy), 0) - radius;
        }

        /// The Gaussian integrated over each pixel, across and then down. Over a straight edge on
        /// a pixel boundary this is exactly Phi at each pixel's centre.
        private static double[] Blur(double[] source, int across, int down, double sigma)
        {
            int spread = Spread(sigma);
            if (spread == 0) return source;
            var kernel = new double[2 * spread + 1];
            for (int i = 0; i < kernel.Length; i++)
                kernel[i] = Phi((i - spread + 0.5) / sigma) - Phi((i - spread - 0.5) / sigma);
            var middle = new double[source.Length];
            for (int y = 0; y < down; y++)
            {
                int row = y * across;
                for (int x = 0; x < across; x++)
                {
                    double sum = 0;
                    int from = Math.Max(0, x - spread), to = Math.Min(across - 1, x + spread);
                    for (int k = from; k <= to; k++) sum += source[row + k] * kernel[k - x + spread];
                    middle[row + x] = sum;
                }
            }
            var result = new double[source.Length];
            for (int x = 0; x < across; x++)
                for (int y = 0; y < down; y++)
                {
                    double sum = 0;
                    int from = Math.Max(0, y - spread), to = Math.Min(down - 1, y + spread);
                    for (int k = from; k <= to; k++) sum += middle[k * across + x] * kernel[k - y + spread];
                    result[y * across + x] = sum;
                }
            return result;
        }

        private static double Phi(double x)
        {
            return 0.5 * (1 + Erf(x / Math.Sqrt(2)));
        }

        /// Abramowitz and Stegun 7.1.26: within 1.5e-7, far under a colour level.
        private static double Erf(double x)
        {
            double sign = x < 0 ? -1 : 1;
            x = Math.Abs(x);
            double t = 1 / (1 + 0.3275911 * x);
            double poly = ((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t;
            return sign * (1 - poly * Math.Exp(-x * x));
        }

        /// The shadows of `recipe` as they are stamped at `scale` in the theme in effect, sampled
        /// across the middle of each straight edge: for each of its shadows, in brand.SHADOWS'
        /// order, and each side (left, top, right, bottom), the alpha 0.5, 1.5, 2.5 ... device pixels
        /// from the edge - outward from the body for an outer shadow, inward from inside the hairline
        /// for an inset one. Draws into a bitmap and nowhere else; the tests hold it to
        /// brand.shadow_alpha.
        internal static float[] Profile(string recipe, double scale)
        {
            int count = Count(recipe);
            if (count == 0) return new float[0];
            bool outer = false;
            int samples = 0;
            for (int index = 0; index < count; index++)
            {
                double dx, dy, blur, alpha;
                bool inset;
                Color tone;
                Shadow(recipe, index, out dx, out dy, out blur, out alpha, out inset, out tone);
                if (!inset) outer = true;
                samples = Math.Max(samples, Spread(blur * scale / 2) + (int)Math.Ceiling(Math.Max(Math.Abs(dx), Math.Abs(dy)) * scale) + 2);
            }
            float radius = (float)((recipe == "card" ? Brand.RadiusCard : Brand.RadiusControl) * scale);
            int length = 4 * (samples + (int)Math.Ceiling(radius)) + 40;
            int margin = outer ? samples + 4 : 0;
            var result = new float[count * 4 * samples];
            using (var bitmap = new Bitmap(length + 2 * margin, length + 2 * margin, PixelFormat.Format32bppArgb))
            {
                var body = new Rectangle(margin, margin, length, length);
                var all = new Rectangle(0, 0, bitmap.Width, bitmap.Height);
                int middle = margin + length / 2;
                for (int shadow = 0; shadow < count; shadow++)
                {
                    using (Graphics g = Graphics.FromImage(bitmap))
                    {
                        g.Clear(Color.Transparent);
                        StampOne(g, recipe, shadow, scale, body, radius, all);
                    }
                    bool inside = IsInset(recipe, shadow);
                    for (int i = 0; i < samples; i++)
                    {
                        int near = inside ? margin + i : margin - 1 - i;
                        int far = inside ? margin + length - 1 - i : margin + length + i;
                        result[(shadow * 4) * samples + i] = bitmap.GetPixel(near, middle).A / 255f;
                        result[(shadow * 4 + 1) * samples + i] = bitmap.GetPixel(middle, near).A / 255f;
                        result[(shadow * 4 + 2) * samples + i] = bitmap.GetPixel(far, middle).A / 255f;
                        result[(shadow * 4 + 3) * samples + i] = bitmap.GetPixel(middle, far).A / 255f;
                    }
                }
            }
            return result;
        }

        /// A `width` by `height` body of `recipe` as a page shows it in the theme in effect, with
        /// `margin` device pixels of ground around it: a card on the canvas, a control on a card, a
        /// well on a card. The pixels as ARGB, row by row, for the tests that compare them with
        /// brand.elevation_colour.
        internal static int[] Render(string recipe, double scale, int width, int height, int margin)
        {
            int id = RecipeId(recipe);
            if (id < 0) return new int[0];
            Color fill = id == 0 ? Tokens.Card : id == 2 ? Tokens.Inset : Tokens.Raised;
            float radius = (float)((id == 0 ? Brand.RadiusCard : Brand.RadiusControl) * scale);
            int hairline = Math.Max(1, (int)Math.Floor(scale + 1e-6));
            int across = width + 2 * margin, down = height + 2 * margin;
            var pixels = new int[across * down];
            using (var bitmap = new Bitmap(across, down, PixelFormat.Format32bppArgb))
            {
                using (Graphics g = Graphics.FromImage(bitmap))
                {
                    g.Clear(id == 0 ? Tokens.Canvas : Tokens.Card);
                    var body = new Rectangle(margin, margin, width, height);
                    var all = new Rectangle(0, 0, across, down);
                    int count = Count(recipe);
                    for (int index = count - 1; index >= 0; index--)
                        if (!IsInset(recipe, index)) StampOne(g, recipe, index, scale, body, radius, all);
                    g.SmoothingMode = SmoothingMode.AntiAlias;
                    g.PixelOffsetMode = PixelOffsetMode.Half;
                    using (var path = Soft.Rounded(body, radius))
                    using (var brush = new SolidBrush(fill))
                        g.FillPath(brush, path);
                    Rectangle box = Rectangle.Inflate(body, -hairline, -hairline);
                    for (int index = count - 1; index >= 0; index--)
                        if (IsInset(recipe, index)) StampOne(g, recipe, index, scale, box, radius - hairline, all);
                    Soft.Edge(g, body, radius, Tokens.Line, hairline);
                }
                BitmapData data = bitmap.LockBits(new Rectangle(0, 0, across, down), ImageLockMode.ReadOnly, PixelFormat.Format32bppArgb);
                try
                {
                    for (int y = 0; y < down; y++)
                        Marshal.Copy(new IntPtr(data.Scan0.ToInt64() + (long)y * data.Stride), pixels, y * across, across);
                }
                finally { bitmap.UnlockBits(data); }
            }
            return pixels;
        }
    }

    /// A control whose body the ground behind it lifts: a card, or a raised control.
    internal interface ISoftLifted
    {
        /// "card", "control", or null while it has no lift (pressed, disabled, chosen).
        string Lift { get; }

        /// The corner radius of its body, in device pixels.
        float Radius { get; }

        /// Its body, in its own coordinates.
        Rectangle Face { get; }

        /// Whether the keyboard focus ring is showing around the body.
        bool Ring { get; }
    }

    /// A container that paints the lifts of what it holds in its own background.
    internal interface ISoftGround { }

    /// A ground: a container's colour, then the shadows and focus rings of everything lifted
    /// on it.
    ///
    /// A child window is clipped to itself, so a control cannot draw its own shadow. The
    /// container behind it does, in its background, before the child paints its body; a
    /// rounded child fills its corners from the same ground (PaintBehind), so the shadow runs on
    /// behind them. A container that shows its parent's colour unchanged is looked through: the
    /// outermost such ancestor decides what is stamped, and each container on the way draws the
    /// part over its own area, so a control's shadow crosses from a row into its card's padding
    /// without a seam. SoftStack, SoftPage, SoftFlow, SoftCard and ChoiceGroup do this in their
    /// background; any other container holding a lifted control is given a Paint handler that
    /// does the same (Watch).
    internal static class Ground
    {
        private const int Depth = 6;
        private static readonly HashSet<Control> watched = new HashSet<Control>();

        /// A ground's background: its colour, then the lifts that reach into the clip.
        internal static void Paint(Control ground, PaintEventArgs e)
        {
            using (var brush = new SolidBrush(Colour(ground))) e.Graphics.FillRectangle(brush, e.ClipRectangle);
            Stamps(ground, e.Graphics, e.ClipRectangle);
        }

        /// The colour a control shows: its own, or the first opaque one behind it.
        internal static Color Colour(Control control)
        {
            for (Control c = control; c != null; c = c.Parent)
                if (c.BackColor.A == 255) return c.BackColor;
            return Palette.Canvas;
        }

        /// Whether a container shows its parent's ground unchanged, so a shadow may cross it.
        ///
        /// A page never does while its scroll bars show: it is then the edge of every shadow on it,
        /// as a scrolling box is in the panel. Seen through, a card scrolled out of sight left its
        /// shadow behind in the strip above the page. Without scroll bars nothing on the page can
        /// be offset, so its cards' lift runs on into the strips around it, where a page that was
        /// always an edge cut it in a visible line under the tabs and above the save bar.
        internal static bool SeeThrough(Control control)
        {
            if (control.Parent == null || control is ISoftLifted) return false;
            if (Scrolling(control)) return false;
            return control.BackColor.A < 255 || control.BackColor.ToArgb() == Colour(control.Parent).ToArgb();
        }

        /// Whether a control is a page that is showing a scroll bar: the soft one (SoftPage), or
        /// Windows' own on any other scrolling panel.
        internal static bool Scrolling(Control control)
        {
            var page = control as SoftPage;
            if (page != null) return page.Overflowing;
            var scroller = control as ScrollableControl;
            return scroller != null && scroller.AutoScroll &&
                   (scroller.VerticalScroll.Visible || scroller.HorizontalScroll.Visible);
        }

        /// Stamps every lift and focus ring that reaches into `clip`, in `painter`'s coordinates.
        internal static void Stamps(Control painter, Graphics g, Rectangle clip)
        {
            Control top = painter;
            int x = 0, y = 0;
            for (int depth = 0; depth < Depth && SeeThrough(top); depth++)
            {
                x += top.Left;
                y += top.Top;
                top = top.Parent;
            }
            var lifted = new List<KeyValuePair<Control, Point>>();
            Collect(top, -x, -y, lifted, 0);
            foreach (KeyValuePair<Control, Point> entry in lifted)
            {
                var item = (ISoftLifted)entry.Key;
                string lift = item.Lift;
                if (lift == null) continue;
                Rectangle face = item.Face;
                face.Offset(entry.Value);
                Elevation.StampOuter(g, face, lift, item.Radius, clip);
            }
            foreach (KeyValuePair<Control, Point> entry in lifted)
            {
                var item = (ISoftLifted)entry.Key;
                if (!item.Ring) continue;
                Rectangle face = item.Face;
                face.Offset(entry.Value);
                int ring = Soft.Px(Brand.FocusOffset + Brand.FocusWidth) + 1;
                if (Rectangle.Inflate(face, ring, ring).IntersectsWith(clip)) Soft.Ring(g, face, item.Radius);
            }
        }

        private static void Collect(Control container, int x, int y, List<KeyValuePair<Control, Point>> lifted, int depth)
        {
            foreach (Control child in container.Controls)
            {
                if (!Soft.Shown(child)) continue;
                int left = x + child.Left, top = y + child.Top;
                if (child is ISoftLifted)
                    lifted.Add(new KeyValuePair<Control, Point>(child, new Point(left, top)));
                else if (depth < Depth && child.Controls.Count > 0 && SeeThrough(child))
                    Collect(child, left, top, lifted, depth + 1);
            }
        }

        /// Paints the ground behind the four corners of a rounded body filling `face` of
        /// `child`, including any shadow that lies there - the child's own among them.
        internal static void PaintBehind(Control child, Graphics g, Rectangle face, float radius)
        {
            int size = Math.Min((int)Math.Ceiling(radius) + 1, Math.Min(face.Width, face.Height));
            if (size <= 0) return;
            var corners = new Rectangle[4];
            corners[0] = new Rectangle(face.Left, face.Top, size, size);
            corners[1] = new Rectangle(face.Right - size, face.Top, size, size);
            corners[2] = new Rectangle(face.Left, face.Bottom - size, size, size);
            corners[3] = new Rectangle(face.Right - size, face.Bottom - size, size, size);
            PaintAreas(child, g, corners, face);
        }

        /// Paints the ground behind `area` of `child`, for a control that is not a rectangle.
        internal static void PaintArea(Control child, Graphics g, Rectangle area)
        {
            var areas = new Rectangle[1];
            areas[0] = area;
            PaintAreas(child, g, areas, area);
        }

        private static void PaintAreas(Control child, Graphics g, Rectangle[] areas, Rectangle bounds)
        {
            Control parent = child.Parent;
            GraphicsState state = g.Save();
            using (var region = new Region())
            {
                region.MakeEmpty();
                foreach (Rectangle area in areas) region.Union(area);
                g.SetClip(region, CombineMode.Intersect);
            }
            using (var brush = new SolidBrush(parent == null ? Palette.Canvas : Colour(parent)))
                g.FillRectangle(brush, bounds);
            if (parent != null)
            {
                // The clip stays where it is on the device; only drawing moves.
                g.TranslateTransform(-child.Left, -child.Top);
                bounds.Offset(child.Left, child.Top);
                Stamps(parent, g, bounds);
            }
            g.Restore(state);
        }

        /// The band a lift of `recipe` and the focus ring can cover around `child`, in its
        /// parent's coordinates.
        internal static Rectangle Band(Control child, string recipe)
        {
            var item = child as ISoftLifted;
            Rectangle face = item != null ? item.Face : child.ClientRectangle;
            face.Offset(child.Left, child.Top);
            Padding reach = Elevation.Reach(recipe);
            int ring = Soft.Px(Brand.FocusOffset + Brand.FocusWidth) + 1;
            int left = Math.Max(reach.Left, ring), top = Math.Max(reach.Top, ring);
            int right = Math.Max(reach.Right, ring), bottom = Math.Max(reach.Bottom, ring);
            return new Rectangle(face.X - left, face.Y - top, face.Width + left + right, face.Height + top + bottom);
        }

        /// Repaints the band around `child` wherever its lift is drawn - after a press, a change
        /// of enabled state, a move - so no shadow is left behind where it no longer is.
        internal static void InvalidateLift(Control child)
        {
            if (child.Parent != null) Invalidate(child.Parent, Band(child, child is SoftCard ? "card" : "control"));
        }

        /// Repaints `band` (in `container`'s coordinates) on the container and on every
        /// container it is seen through - and, in a block whose control lies over its content
        /// (SoftPin), on the content's windows under the band, which draw that part of the lift
        /// and the ring in their own backgrounds. Anywhere else a lifted control has no window
        /// under its band but its own, so a container's is enough.
        internal static void Invalidate(Control container, Rectangle band)
        {
            Control c = container;
            for (int depth = 0; c != null && depth < Depth; depth++)
            {
                if (c.IsHandleCreated && !c.IsDisposed)
                {
                    c.Invalidate(band, false);
                    var block = c as SoftPin;
                    if (block != null) block.InvalidateUnder(band);
                }
                if (!SeeThrough(c)) break;
                band.Offset(c.Left, c.Top);
                c = c.Parent;
            }
        }

        /// Makes sure every container `lifted` is drawn on paints its lift, giving the ones that
        /// are not grounds a Paint handler that stamps it.
        internal static void Watch(Control lifted)
        {
            Control c = lifted.Parent;
            for (int depth = 0; c != null && depth < Depth; depth++)
            {
                if (!(c is ISoftGround) && c.BackColor.A == 255 && watched.Add(c))
                {
                    Control container = c;
                    container.Paint += PaintOver;
                    container.Disposed += delegate { watched.Remove(container); };
                }
                if (!SeeThrough(c)) break;
                c = c.Parent;
            }
        }

        private static void PaintOver(object sender, PaintEventArgs e)
        {
            Stamps((Control)sender, e.Graphics, e.ClipRectangle);
        }
    }

    /// Keeps the ground behind a lifted control in step with it: where its shadow was, and
    /// where it is now, are repainted when it moves, resizes, shows, hides or changes state.
    internal sealed class LiftTracker
    {
        private readonly Control owner;
        private readonly string recipe;
        private Control lastParent;
        private Rectangle lastBand;

        internal LiftTracker(Control owner, string recipe)
        {
            this.owner = owner;
            this.recipe = recipe;
            owner.LocationChanged += delegate { Update(); };
            owner.SizeChanged += delegate { Update(); };
            owner.VisibleChanged += delegate { Update(); };
            owner.ParentChanged += delegate { Update(); };
            owner.EnabledChanged += delegate { Update(); };
            owner.GotFocus += delegate { Update(); };
            owner.LostFocus += delegate { Update(); };
            owner.HandleCreated += delegate { Update(); };
        }

        internal void Update()
        {
            Control parent = owner.Parent;
            Rectangle band = parent == null ? Rectangle.Empty : Ground.Band(owner, recipe);
            if (lastParent != null && (lastParent != parent || band != lastBand)) Ground.Invalidate(lastParent, lastBand);
            lastParent = parent;
            lastBand = band;
            if (parent == null) return;
            Ground.Invalidate(parent, band);
            Ground.Watch(owner);
        }
    }

    /// A table that is a ground (see Ground): double-buffered and opaque.
    internal sealed class SoftStack : TableLayoutPanel, ISoftGround
    {
        internal SoftStack()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                     ControlStyles.UserPaint | ControlStyles.ResizeRedraw, true);
            BackColor = Palette.Canvas;
        }

        protected override void OnPaintBackground(PaintEventArgs e)
        {
            Ground.Paint(this, e);
        }
    }

    /// A grid of cards whose rows share the whole height of the page it fills (v0.6.4): every row as tall
    /// as the others where the page has room for that, and every card as tall as its row, so the Overview's
    /// cards reach from under the tabs to above the footer at whatever height the window has. As tall as their
    /// content, the person found them too wide and too short, over an empty band.
    ///
    /// It fills its page, and the page measures it at what its rows need (Needed): each row as tall as its own
    /// tallest card, measured at the narrower column's width as a table measures a card. A page with room for
    /// every row as tall as the tallest card shares all of its height alike; a shorter one gives each row what
    /// it needs and the rest to the shorter rows (Shares); one shorter still scrolls, and the rows keep what
    /// they need. Counted with every row as tall as the tallest, the Overview scrolled in any window from 598
    /// to 617 px high, where v0.6.3's fitted - and KeepOnScreen gives the window 601 on a 1920 by 1200 screen
    /// at 175% (v0.6.4, measured). What a card holds stays at its top, and a control pinned to its bottom
    /// right (SoftPin) goes down with the card's bottom edge. The gap between two rows is half under the one
    /// and half over the other (Dashboard.RowGap), so rows of one height are cards of one height.
    ///
    /// It is AutoSize, though its page decides its size: a table answers its parent's layout from its own only
    /// when it sizes itself (TableLayout returns AutoSize), and WinForms then lays the parent out once the table's
    /// own layout has finished. So a card that grows on a page already laid out has the page measure the rows
    /// again and scroll. Docked to fill, it is given the page's size whatever it asks for. Asked from inside its
    /// own layout instead, the page gave the table a new size while that layout was still running, and the
    /// table never laid its cards out at it.
    internal sealed class SoftRows : TableLayoutPanel, ISoftGround
    {
        internal SoftRows(int columns, int rows)
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                     ControlStyles.UserPaint | ControlStyles.ResizeRedraw, true);
            BackColor = Palette.Canvas;
            Dock = DockStyle.Fill;
            AutoSize = true;
            Margin = new Padding(0);
            ColumnCount = columns;
            RowCount = rows;
            for (int i = 0; i < columns; i++) ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f / columns));
            for (int i = 0; i < rows; i++) RowStyles.Add(new RowStyle(SizeType.Percent, 100f / rows));
        }

        /// How tall it must be, `width` wide, for every row to hold its own tallest card, margins and all.
        internal int Needed(int width)
        {
            int total = 0;
            foreach (int need in RowNeeds(width)) total += need;
            return Padding.Vertical + total;
        }

        /// How tall each row must be, `width` wide, to hold its tallest card, margins and all.
        private int[] RowNeeds(int width)
        {
            var needs = new int[Math.Max(1, Math.Min(RowCount, RowStyles.Count))];
            // The narrower of the columns as the table shares the width out: a card is never shorter narrower.
            int column = Math.Max(1, (width - Padding.Horizontal) / Math.Max(1, ColumnCount));
            foreach (Control child in Controls)
            {
                if (!Soft.OwnVisible(child)) continue;
                int row = GetPositionFromControl(child).Row;
                if (row < 0 || row >= needs.Length) continue;
                int room = Math.Max(1, column - child.Margin.Horizontal);
                int height = child.AutoSize ? child.GetPreferredSize(new Size(room, 0)).Height : child.Height;
                needs[row] = Math.Max(needs[row], height + child.Margin.Vertical);
            }
            return needs;
        }

        protected override void OnLayout(LayoutEventArgs levent)
        {
            // The rows' shares for the size the table is about to lay its cards out at. A share that changes asks for
            // a layout, which, asked from inside this one, does not run again: this one lays out with the new shares.
            Rectangle display = DisplayRectangle;
            float[] shares = Shares(RowNeeds(display.Width), display.Height);
            for (int i = 0; i < shares.Length && i < RowStyles.Count; i++)
                if (RowStyles[i].Height != shares[i]) RowStyles[i].Height = shares[i];
            base.OnLayout(levent);
        }

        /// The weights of the rows' percent styles, for rows that need `needs` pixels in `room`:
        ///   * alike, where every row can be as tall as the tallest needs;
        ///   * what each row needs, where there is no more than that - a page with less scrolls, and a table
        ///     given less on the way shares it in proportion;
        ///   * between the two, the rows that need more than an even share of what the others leave keep what they
        ///     need, and the others share the rest alike, so the shorter rows grow toward the taller and none is
        ///     given less than it needs. In whole pixels that add up to `room`, so the table's shares are exact.
        internal static float[] Shares(int[] needs, int room)
        {
            int rows = needs.Length, tallest = 0, total = 0;
            foreach (int need in needs)
            {
                tallest = Math.Max(tallest, need);
                total += need;
            }
            var shares = new float[rows];
            if (total <= 0 || (long)tallest * rows <= room)
            {
                for (int i = 0; i < rows; i++) shares[i] = 100f / rows;
                return shares;
            }
            if (room <= total)
            {
                for (int i = 0; i < rows; i++) shares[i] = needs[i];
                return shares;
            }
            var keeps = new bool[rows];
            int left = room, sharing = rows;
            while (sharing > 1)
            {
                int most = -1;
                for (int i = 0; i < rows; i++)
                    if (!keeps[i] && (most < 0 || needs[i] > needs[most])) most = i;
                if ((long)needs[most] * sharing <= left) break;
                keeps[most] = true;
                left -= needs[most];
                sharing--;
            }
            int even = left / sharing, over = left - even * sharing;
            for (int i = 0; i < rows; i++)
            {
                if (keeps[i])
                {
                    shares[i] = needs[i];
                    continue;
                }
                shares[i] = even + (over > 0 ? 1 : 0);
                if (over > 0) over--;
            }
            return shares;
        }

        protected override void OnPaintBackground(PaintEventArgs e)
        {
            Ground.Paint(this, e);
        }
    }

    /// A page that is a ground (see Ground): double-buffered and opaque. A page that `Scrolls` moves
    /// what it holds up and down when that is taller than the page, on the soft scroll bar - never
    /// on Windows' own.
    ///
    /// Windows draws its bar in the page's frame, in the system's grey, and nothing a window does to
    /// it makes it the window's material. So the page keeps its own offset. Its DisplayRectangle -
    /// the rectangle WinForms lays every docked and anchored child out in - starts that far above its
    /// top, and while there is more than fits it is narrower by the bar's gutter, so nothing is drawn
    /// under the bar. How tall what it holds is:
    ///   * a child docked to the top or the bottom counts at its height;
    ///   * a child that fills counts at no more than its MinimumSize, so a page a list fills -
    ///     Pending, History - scrolls only when the rest of it no longer fits at all;
    ///   * a grid whose rows share the page (SoftRows) counts at what its rows need, so the Overview
    ///     fills the page it fits and scrolls only when its cards need more;
    ///   * a child placed where it is counts to its bottom.
    /// The wheel scrolls it over anything in it that does not take the wheel for itself (a drop-down
    /// or a number hands it on: Soft.PassWheel), and a control the keyboard moves to is scrolled into
    /// view, as Windows' own scrolling panel does.
    internal sealed class SoftPage : Panel, ISoftGround, ISoftScroller
    {
        // Whether the lift of what it holds may cross out of it follows whether it is scrolling
        // (Ground.SeeThrough), so when that changes the grounds around it are painted again.
        private bool scrolling;
        private bool scrolls, overflow, moving, unsettled;
        private int offset, extent, glideTarget;
        private SoftScrollBar bar;
        private Timer glide;
        private EventHandler entered;
        private ControlEventHandler added, removed;

        internal SoftPage()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                     ControlStyles.UserPaint | ControlStyles.ResizeRedraw, true);
            BackColor = Palette.Canvas;
        }

        /// Whether it scrolls what it holds up and down. Turned on once, when the page is built.
        internal bool Scrolls
        {
            get { return scrolls; }
            set
            {
                if (!value || scrolls) return;
                bar = new SoftScrollBar(this, this);
                glide = new Timer();
                glide.Interval = SoftBar.GlideInterval;
                glide.Tick += delegate { Glide(); };
                entered = delegate(object sender, EventArgs e) { Entered(sender as Control); };
                added = delegate(object sender, ControlEventArgs e) { Follow(e.Control); };
                removed = delegate(object sender, ControlEventArgs e) { Unfollow(e.Control); };
                scrolls = true;
                ControlAdded += added;
                ControlRemoved += removed;
                foreach (Control child in Controls) Follow(child);
                PerformLayout();
            }
        }

        /// Whether it holds more than fits, so the bar is showing.
        internal bool Overflowing { get { return scrolls && overflow; } }

        /// Asks for what it holds to be laid out once more before its layout ends: something in it (SoftPin)
        /// was laid out with less room than it needs, measured before what it holds changed under it.
        internal void Unsettle()
        {
            unsettled = true;
        }

        /// How far down it is scrolled, in pixels.
        internal int Offset { get { return offset; } }

        /// How tall what it holds is, its padding included, in pixels.
        internal int Extent { get { return extent; } }

        internal SoftScrollBar Bar { get { return bar; } }

        int ISoftScroller.Extent { get { return extent; } }
        int ISoftScroller.Viewport { get { return ClientSize.Height; } }
        int ISoftScroller.Offset { get { return offset; } }
        void ISoftScroller.ScrollTo(int target) { ScrollTo(target, false); }
        void ISoftScroller.Page(int direction)
        {
            ScrollTo(offset + direction * SoftBar.PageStep(ClientSize.Height, Soft.Px(SoftBar.Line)), false);
        }

        public override Rectangle DisplayRectangle
        {
            get
            {
                if (!scrolls) return base.DisplayRectangle;
                Size client = ClientSize;
                int gutter = overflow ? SoftBar.Gutter : 0;
                return new Rectangle(Padding.Left, Padding.Top - offset,
                                     Math.Max(0, client.Width - Padding.Horizontal - gutter),
                                     Math.Max(0, Math.Max(client.Height, extent) - Padding.Vertical));
            }
        }

        protected override void OnPaintBackground(PaintEventArgs e)
        {
            Ground.Paint(this, e);
            if (Overflowing) bar.Paint(e.Graphics);
        }

        protected override void OnLayout(LayoutEventArgs levent)
        {
            // Laid out without the bar's gutter first, whatever showed before - except while it only moves
            // what it holds (MoveTo), which changes nothing it measures.
            if (scrolls && !moving) overflow = false;
            base.OnLayout(levent);
            if (scrolls) Settle(levent);
            bool now = Ground.Scrolling(this);
            if (now == scrolling) return;
            scrolling = now;
            Form form = FindForm();
            if (form != null && form.IsHandleCreated) form.Invalidate(true);
        }

        // Measures what it holds and lays it out again until that agrees with the offset and the bar: the
        // gutter narrows what fills the width, which can only make it taller, so it settles in two passes at
        // most once the bar has appeared or gone. It starts without the gutter (OnLayout), so whether the bar
        // shows follows the page's size and what it holds, never what showed before: started from the last
        // layout's gutter, the Overview's cards, narrower by it, wrapped taller than a page they fitted
        // without it, and the bar never went (v0.6.4, measured: German at 150%, 617 px in 598, where the same
        // page grown into that size measured 586).
        private void Settle(LayoutEventArgs levent)
        {
            for (int pass = 0; pass < 4; pass++)
            {
                if (unsettled)
                {
                    // Something in it was given less room than it needs after its row was measured: what it
                    // holds is laid out again, which measures it again.
                    unsettled = false;
                    foreach (Control child in Controls)
                        if (Soft.OwnVisible(child)) child.PerformLayout();
                }
                int measured = Measure();
                int viewport = ClientSize.Height;
                bool over = viewport > 0 && measured > viewport;
                int clamped = over ? Math.Max(0, Math.Min(measured - viewport, offset)) : 0;
                if (measured == extent && over == overflow && clamped == offset) break;
                extent = measured;
                overflow = over;
                offset = clamped;
                base.OnLayout(levent);
            }
            if (glideTarget > offset && !overflow) glideTarget = offset;
            int margin = Soft.Px(SoftBar.TrackMargin);
            bar.Track = overflow
                ? new Rectangle(ClientSize.Width - margin - Soft.Px(SoftBar.TrackWidth), margin,
                                Soft.Px(SoftBar.TrackWidth), Math.Max(0, ClientSize.Height - 2 * margin))
                : Rectangle.Empty;
        }

        private int Measure()
        {
            Rectangle display = DisplayRectangle;
            int stacked = 0, placed = 0;
            foreach (Control child in Controls)
            {
                if (!Soft.OwnVisible(child)) continue;
                if (child.Dock == DockStyle.Top || child.Dock == DockStyle.Bottom) stacked += child.Height;
                else if (child is SoftRows && child.Dock == DockStyle.Fill)
                    stacked += Math.Max(Math.Max(0, child.MinimumSize.Height), ((SoftRows)child).Needed(display.Width));
                else if (child.Dock == DockStyle.Fill) stacked += Math.Max(0, child.MinimumSize.Height);
                else if (child.Dock == DockStyle.None) placed = Math.Max(placed, child.Bottom - display.Top);
            }
            return Padding.Vertical + Math.Max(stacked, placed);
        }

        /// Scrolls to `target` pixels down, as far as there is to scroll. With `animate` it glides
        /// there, unless motion is reduced or it is not on screen; otherwise it is there at once.
        internal void ScrollTo(int target, bool animate)
        {
            if (!scrolls) return;
            int range = overflow ? Math.Max(0, extent - ClientSize.Height) : 0;
            target = Math.Max(0, Math.Min(range, target));
            glideTarget = target;
            if (animate && !Soft.ReduceMotion && IsHandleCreated && Soft.Shown(this))
            {
                if (!glide.Enabled) glide.Start();
                return;
            }
            glide.Stop();
            MoveTo(target);
        }

        /// Whether it is gliding toward an offset rather than standing at one.
        internal bool Gliding { get { return glide != null && glide.Enabled; } }

        private void MoveTo(int value)
        {
            if (value == offset) return;
            offset = value;
            // The children move with their pixels; the page's own ground - its padding, the shadows
            // in it, the bar - is painted again. Only moved: laid out without the gutter first, every
            // frame of a glide would lay a page of cards out twice at two widths.
            moving = true;
            try { PerformLayout(); }
            finally { moving = false; }
            Invalidate(false);
        }

        private void Glide()
        {
            int next = SoftBar.GlideStep(offset, glideTarget);
            MoveTo(next);
            if (next == glideTarget || !Soft.Shown(this)) glide.Stop();
        }

        /// Scrolls by one turn of the wheel, `delta` as Windows reports it. False when there is
        /// nothing to scroll that way, so the turn goes on to whatever holds the page.
        internal bool Wheel(int delta)
        {
            if (!Overflowing) return false;
            int from = Gliding ? glideTarget : offset;
            int step = SoftBar.WheelStep(delta, SystemInformation.MouseWheelScrollLines, Soft.Px(SoftBar.Line), ClientSize.Height);
            int target = Math.Max(0, Math.Min(extent - ClientSize.Height, from + step));
            if (target == from) return false;
            ScrollTo(target, true);
            return true;
        }

        // A turn over the page, or over a child that did not take it: Windows hands a wheel message a
        // window does not use to its parent, so this sees both.
        protected override void OnMouseWheel(MouseEventArgs e)
        {
            base.OnMouseWheel(e);
            var handled = e as HandledMouseEventArgs;
            if (handled != null && handled.Handled) return;
            if (Wheel(e.Delta) && handled != null) handled.Handled = true;
        }

        /// Scrolls just far enough that `control`, somewhere in the page, is in view with a little of
        /// the page around it - or its top, when it is taller than the page.
        internal void Reveal(Control control)
        {
            if (!Overflowing || control == null) return;
            int top = 0;
            Control c = control;
            for (; c != null && c != this; c = c.Parent) top += c.Top;
            if (c == null) return;
            top += offset;
            ScrollTo(SoftBar.IntoView(offset, top, top + control.Height, ClientSize.Height,
                                      Soft.Px(SoftBar.RevealRoom), extent), false);
        }

        // Focus arriving anywhere in the page. From the keyboard only: a click on a control half out of
        // view is where the pointer is, and scrolling it away from under the pointer loses the click.
        // Enter is raised for each container on the way down as well, so what is revealed is the
        // control the window's focus is actually on.
        private void Entered(Control control)
        {
            if (!Overflowing || Control.MouseButtons != MouseButtons.None) return;
            Form form = FindForm();
            Control active = form != null ? form.ActiveControl : null;
            for (var container = active as ContainerControl; container != null && container.ActiveControl != null;
                 container = active as ContainerControl)
                active = container.ActiveControl;
            Reveal(active != null && Contains(active) ? active : control);
        }

        private void Follow(Control control)
        {
            if (control == null) return;
            control.Enter += entered;
            control.ControlAdded += added;
            control.ControlRemoved += removed;
            foreach (Control child in control.Controls) Follow(child);
        }

        private void Unfollow(Control control)
        {
            if (control == null) return;
            control.Enter -= entered;
            control.ControlAdded -= added;
            control.ControlRemoved -= removed;
            foreach (Control child in control.Controls) Unfollow(child);
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing && glide != null) { glide.Stop(); glide.Dispose(); }
            base.Dispose(disposing);
        }
    }

    /// What the soft scroll bar scrolls: a page of controls, or a list's rows.
    internal interface ISoftScroller
    {
        /// How long all of it is, how much shows at once, and how far along the view is - in one
        /// unit: pixels for a page, rows for a list.
        int Extent { get; }
        int Viewport { get; }
        int Offset { get; }

        void ScrollTo(int offset);

        /// A page toward the start (-1) or the end (1).
        void Page(int direction);
    }

    /// The soft scroll bar's measurements and drawing: a thin well - the inset recipe, with its hairline -
    /// and in it a raised pill, the control recipe's material and lift, as the panel's switch holds its
    /// knob. Sizes are logical pixels.
    ///
    /// 12 across: thin beside the cards, and still a target as wide as a check box's mark; the whole
    /// gutter, 18 across, answers the pointer. The pill is 8 across, inside a 2-pixel groove, and never
    /// shorter than 32. Under the pointer and while it is dragged its edge darkens a step and a step
    /// more. In High Contrast the well is Window with a WindowFrame edge and the pill GrayText, or
    /// Highlight under the pointer and while dragged, with no shadow at all.
    internal static class SoftBar
    {
        internal const int TrackWidth = 12;
        internal const int ThumbInset = 2;
        internal const int TrackMargin = 3;
        internal const int MinThumb = 32;
        /// A wheel line: three of them are 99 px, what the panel's page moves for one notch.
        internal const int Line = 33;
        /// The room kept around a control scrolled into view.
        internal const int RevealRoom = 16;
        internal const int GlideInterval = 15;

        /// The strip a page keeps free for the bar while it shows, in device pixels.
        internal static int Gutter
        {
            get { return Soft.Px(TrackWidth + 2 * TrackMargin); }
        }

        /// Where the thumb starts along a track `track` long, and how long it is, for `extent` of which
        /// `viewport` shows, scrolled `offset` along. Proportional, never under `minimum`.
        internal static void Thumb(int track, int extent, int viewport, int offset, int minimum, out int start, out int length)
        {
            start = 0;
            length = Math.Max(0, track);
            if (track <= 0 || extent <= viewport || viewport <= 0) return;
            length = (int)Math.Round((double)track * viewport / extent);
            length = Math.Min(track, Math.Max(Math.Min(minimum, track), length));
            int range = extent - viewport;
            start = (int)Math.Round((double)(track - length) * Math.Max(0, Math.Min(range, offset)) / range);
        }

        /// The offset a thumb `length` long standing at `start` along the track stands for.
        internal static int OffsetAt(int track, int extent, int viewport, int length, int start)
        {
            int travel = track - length, range = extent - viewport;
            if (travel <= 0 || range <= 0) return 0;
            return (int)Math.Round((double)range * Math.Max(0, Math.Min(travel, start)) / travel);
        }

        /// How far one wheel message scrolls: `lines` lines of `line` for each notch of 120, or pages
        /// when Windows is set to scroll a screen at a time (`lines` below zero). A turn up is negative.
        internal static int WheelStep(int delta, int lines, int line, int viewport)
        {
            double amount = lines < 0 ? PageStep(viewport, line) : (double)lines * line;
            return -(int)Math.Round(delta * amount / 120.0);
        }

        /// A page: what shows, less a line kept in view from the page before.
        internal static int PageStep(int viewport, int line)
        {
            return Math.Max(Math.Max(1, line), viewport - line);
        }

        /// The offset that shows `top` to `bottom` of the content with `margin` around it, moving as
        /// little as it can; the top when it is taller than what shows.
        internal static int IntoView(int offset, int top, int bottom, int viewport, int margin, int extent)
        {
            int target = offset;
            if (bottom - top + 2 * margin > viewport || top - margin < offset) target = top - margin;
            else if (bottom + margin > offset + viewport) target = bottom + margin - viewport;
            return Math.Max(0, Math.Min(Math.Max(0, extent - viewport), target));
        }

        /// One frame of a glide from `from` toward `to`: a third of the way, and the rest at the end.
        internal static int GlideStep(int from, int to)
        {
            int left = to - from;
            if (Math.Abs(left) <= 2) return to;
            int step = (int)Math.Round(left * 0.35);
            return from + (step == 0 ? Math.Sign(left) : step);
        }

        // States: 0 resting, 1 under the pointer, 2 dragged. The brand half is the theme's (Tokens).
        /// The well the bar runs in, for the ground it is drawn on. Everywhere but in a well that is the
        /// `inset` groove the design gives a track; in one - the message box, whose own ground is `inset` -
        /// an inset track is the ground, and the bar would be a pill floating on nothing. There it is the
        /// card's colour instead, so the groove is still a step away from what surrounds it.
        internal static Color TrackFill(bool contrast, Color ground)
        {
            if (contrast) return SystemColors.Window;
            return Soft.Near(ground, Tokens.Inset) ? Tokens.Surface : Tokens.Inset;
        }

        internal static Color TrackEdge(bool contrast) { return contrast ? SystemColors.WindowFrame : Tokens.Line; }

        internal static Color ThumbFill(int state, bool contrast)
        {
            if (contrast) return state == 0 ? SystemColors.GrayText : SystemColors.Highlight;
            return Tokens.Raised;
        }

        internal static Color ThumbEdge(int state, bool contrast)
        {
            if (contrast) return ThumbFill(state, true);
            return state == 2 ? Soft.Mix(Tokens.Line, Tokens.Muted, 0.6)
                 : state == 1 ? Soft.Mix(Tokens.Line, Tokens.Muted, 0.35) : Tokens.Line;
        }

        /// The bar in `track`, standing or lying: its ends are round whichever way it runs (v0.6.5, when a
        /// list's bar across its bottom was added).
        internal static void Draw(Graphics g, Rectangle track, Rectangle thumb, int state, Color ground)
        {
            if (track.Width <= 0 || track.Height <= 0) return;
            bool contrast = Palette.Contrast;
            float radius = Math.Min(track.Width, track.Height) / 2f;
            Soft.Body(g, track, radius, TrackFill(contrast, ground), TrackEdge(contrast), !contrast);
            if (thumb.Width <= 0 || thumb.Height <= 0) return;
            float knob = Math.Min(thumb.Width, thumb.Height) / 2f;
            if (!contrast)
            {
                // The pill's lift, kept in the groove: it rests in the well rather than floating over
                // the page, and its shadow never covers the well's own edge.
                int hairline = Soft.Hairline;
                Rectangle groove = Rectangle.Inflate(track, -hairline, -hairline);
                GraphicsState saved = g.Save();
                using (GraphicsPath path = Soft.Rounded(groove, Math.Max(0f, radius - hairline)))
                    g.SetClip(path, CombineMode.Intersect);
                Elevation.StampOuter(g, thumb, "control", knob, groove);
                g.Restore(saved);
            }
            Soft.Body(g, thumb, knob, ThumbFill(state, contrast), ThumbEdge(state, contrast), false);
        }
    }

    /// The soft scroll bar's behaviour, on the control it is drawn in: dragging the thumb, a press on
    /// the track paging toward the pointer and repeating while held, and the step darker edge under the
    /// pointer. It is no window of its own - the host paints it (Paint) in a strip nothing else covers -
    /// so there is nothing to focus and nothing between the host and its children.
    ///
    /// It stands at the right of what it scrolls, or - `across`, v0.6.5 - lies along its bottom and
    /// scrolls it sideways: a list whose columns are wider than it is, in a narrow window. The same
    /// well and pill either way; only the axis changes.
    internal sealed class SoftScrollBar
    {
        private readonly Control host;
        private readonly ISoftScroller scroller;
        private readonly bool across;
        private readonly Timer repeat = new Timer();
        private Rectangle track;
        private bool hover, dragging;
        private int grab, pointer, direction;

        internal SoftScrollBar(Control host, ISoftScroller scroller) : this(host, scroller, false) { }

        internal SoftScrollBar(Control host, ISoftScroller scroller, bool across)
        {
            this.host = host;
            this.scroller = scroller;
            this.across = across;
            host.MouseDown += OnMouseDown;
            host.MouseMove += OnMouseMove;
            host.MouseUp += OnMouseUp;
            host.MouseLeave += delegate { if (!dragging) Hover(false); };
            host.MouseCaptureChanged += delegate { if (!host.Capture) Release(); };
            repeat.Tick += delegate { repeat.Interval = 50; Page(); };
            host.Disposed += delegate { repeat.Dispose(); };
        }

        /// The track, in the host's coordinates; empty while there is nothing to scroll.
        internal Rectangle Track
        {
            get { return track; }
            set
            {
                if (track == value) return;
                Invalidate();
                track = value;
                if (track.IsEmpty) { hover = false; Release(); }
                Invalidate();
            }
        }

        /// What answers the pointer: the track and the margins either side of it.
        internal Rectangle HitArea
        {
            get
            {
                if (track.IsEmpty) return Rectangle.Empty;
                int margin = Soft.Px(SoftBar.TrackMargin);
                return Rectangle.Inflate(track, margin, margin);
            }
        }

        internal Rectangle Thumb
        {
            get
            {
                if (track.IsEmpty) return Rectangle.Empty;
                int inset = Soft.Px(SoftBar.ThumbInset), start, length;
                SoftBar.Thumb(Along(track) - 2 * inset, scroller.Extent, scroller.Viewport, scroller.Offset,
                              Soft.Px(SoftBar.MinThumb), out start, out length);
                if (across)
                    return new Rectangle(track.X + inset + start, track.Y + inset, length, Math.Max(0, track.Height - 2 * inset));
                return new Rectangle(track.X + inset, track.Y + inset + start, Math.Max(0, track.Width - 2 * inset), length);
            }
        }

        /// Whether it lies along the bottom and scrolls sideways.
        internal bool Across { get { return across; } }

        /// 0 resting, 1 under the pointer, 2 dragged.
        internal int State { get { return dragging ? 2 : hover ? 1 : 0; } }

        // Lengths and positions along the axis it scrolls.
        private int Along(Rectangle box) { return across ? box.Width : box.Height; }
        private int Start(Rectangle box) { return across ? box.X : box.Y; }
        private int End(Rectangle box) { return across ? box.Right : box.Bottom; }
        private int Along(MouseEventArgs e) { return across ? e.X : e.Y; }

        internal void Paint(Graphics g)
        {
            if (!track.IsEmpty) SoftBar.Draw(g, track, Thumb, State, Ground.Colour(host));
        }

        internal void Invalidate()
        {
            if (!track.IsEmpty && host.IsHandleCreated) host.Invalidate(HitArea, false);
        }

        private void OnMouseDown(object sender, MouseEventArgs e)
        {
            if (e.Button != MouseButtons.Left || !HitArea.Contains(e.Location)) return;
            Rectangle thumb = Thumb;
            host.Capture = true;
            int at = Along(e);
            if (at >= Start(thumb) && at < End(thumb))
            {
                dragging = true;
                grab = at - Start(thumb);
                Invalidate();
                return;
            }
            pointer = at;
            direction = at < Start(thumb) ? -1 : 1;
            Page();
            // Windows' own delay before a held press repeats, then a page every 50 ms.
            repeat.Interval = (SystemInformation.KeyboardDelay + 1) * 250;
            repeat.Start();
        }

        private void OnMouseMove(object sender, MouseEventArgs e)
        {
            if (dragging)
            {
                int inset = Soft.Px(SoftBar.ThumbInset);
                Rectangle thumb = Thumb;
                scroller.ScrollTo(SoftBar.OffsetAt(Along(track) - 2 * inset, scroller.Extent, scroller.Viewport, Along(thumb),
                                                   Along(e) - grab - Start(track) - inset));
                Invalidate();
                return;
            }
            if (repeat.Enabled) pointer = Along(e);
            Hover(HitArea.Contains(e.Location));
        }

        private void OnMouseUp(object sender, MouseEventArgs e)
        {
            Release();
            host.Capture = false;
            Hover(HitArea.Contains(e.Location));
        }

        // A page toward where the track was pressed, until the thumb has reached the pointer.
        private void Page()
        {
            Rectangle thumb = Thumb;
            if (thumb.IsEmpty || (direction < 0 ? Start(thumb) <= pointer : End(thumb) > pointer))
            {
                repeat.Stop();
                return;
            }
            scroller.Page(direction);
            Invalidate();
        }

        private void Release()
        {
            repeat.Stop();
            if (!dragging) return;
            dragging = false;
            Invalidate();
        }

        private void Hover(bool over)
        {
            if (hover == over) return;
            hover = over;
            Invalidate();
        }
    }

    /// A row of buttons that is a ground (see Ground): double-buffered and opaque.
    internal sealed class SoftFlow : FlowLayoutPanel, ISoftGround
    {
        internal SoftFlow()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                     ControlStyles.UserPaint | ControlStyles.ResizeRedraw, true);
            BackColor = Palette.Canvas;
        }

        protected override void OnPaintBackground(PaintEventArgs e)
        {
            Ground.Paint(this, e);
        }
    }

    /// A card: the window's own material, lifted by the ground it stands on. The card IS the
    /// layout panel, as the old one was, because a Panel wrapping a docked AutoSize table measures
    /// to nothing; and it is the ground of whatever it holds.
    internal sealed class SoftCard : TableLayoutPanel, ISoftLifted, ISoftGround
    {
        private readonly LiftTracker tracker;

        internal SoftCard()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                     ControlStyles.UserPaint | ControlStyles.ResizeRedraw, true);
            BackColor = Palette.Card;
            tracker = new LiftTracker(this, "card");
        }

        /// Zero. A card keeps no band inside itself for its shadow any more - the ground around
        /// it draws the shadow - so nothing needs to add one to its padding.
        internal static int Room { get { return 0; } }

        string ISoftLifted.Lift { get { return "card"; } }
        float ISoftLifted.Radius { get { return Soft.PxF(Brand.RadiusCard); } }
        Rectangle ISoftLifted.Face { get { return ClientRectangle; } }
        bool ISoftLifted.Ring { get { return false; } }

        internal LiftTracker Tracker { get { return tracker; } }

        /// The width the card is being measured at, while a table measures it; 0 otherwise. A table
        /// measures a card by asking what it holds how wide it would be and how tall it is that wide,
        /// never at the width it is measuring the card at - and a block that fills its card and wraps
        /// or drops its button by width (SoftPin) is only as wide as the card (SoftPin.GetPreferredSize).
        internal int Measuring { get; private set; }

        public override Size GetPreferredSize(Size proposedSize)
        {
            int before = Measuring;
            Measuring = proposedSize.Width > 1 && proposedSize.Width < 0x100000 ? proposedSize.Width : 0;
            try { return base.GetPreferredSize(proposedSize); }
            finally { Measuring = before; }
        }

        protected override void OnPaintBackground(PaintEventArgs e)
        {
            float radius = Soft.PxF(Brand.RadiusCard);
            Ground.PaintBehind(this, e.Graphics, ClientRectangle, radius);
            // The card's own ground, and in dark its one-pixel top light inside the hairline.
            Soft.Body(e.Graphics, ClientRectangle, radius, Palette.Card, Palette.Line, "card");
            Ground.Stamps(this, e.Graphics, e.ClipRectangle);
        }
    }

    /// What a card holds under its heading, with the one control the card leads to pinned to its
    /// bottom right (v0.6.4): the control's right edge on the block's right edge and its bottom on the
    /// block's bottom - and the block fills its card's last row, so that is the card's inner
    /// bottom-right corner however tall the card is stretched beside another.
    ///
    /// The content keeps the whole width. Where nothing in it reaches into the control's column - the
    /// control's width and the card's head gap in from the right - the control sits beside the last
    /// lines, as it does on the panel. Where something does, the text gives way first: the names of a
    /// grid of facts (Wraps) wrap, so its values start further left and clear the column. That costs a
    /// line, where putting the control under the facts costs a control and a gap - and in German that
    /// made the Overview taller than its window. Only where wrapping does not clear the column, or costs
    /// more, does the block grow, until the control is under the lowest thing in its column with the
    /// card's first gap between them. Text never runs under it. A control that is hidden takes no room.
    /// A block given more height than that - its card stretched beside a taller one, or down a page whose
    /// rows share its height (SoftRows) - keeps the names whole when the control fits under them.
    ///
    /// Where the content's lines are is worked out (Model) - never read from where its controls happen
    /// to be. A table asks a block how tall it is at widths it never gives it - 1, 0, a column's width on
    /// the way to the real one - and keeps the answers, and a height read from the content as last laid
    /// out answered for the wrong width: a card at 150% stayed three times as tall as its facts.
    ///
    /// A line whose words change with what it shows - a fact's value, the control's own words - can be
    /// planned for the widest words it is ever given (Reserve), so the block is laid out the same whatever
    /// it says now. Planned for the words on screen, Right now wrapped, or dropped its button, as the
    /// watcher's state changed, and every refresh of "Last check" could move it: in French and German the
    /// Overview opened on a watcher in trouble scrolled (v0.6.4, measured).
    ///
    /// The content comes first and the control last, which is the order they are seen in, the order Tab
    /// reaches them, and - the content's window above the control's in the z-order - the order Windows
    /// hands a screen reader. The content's window has a hole the control's size where the control is,
    /// so it never paints over it. The block is a ground in the card's colour, seen through (see Ground),
    /// and so are the content's tables: the control's lift and focus ring are drawn around it on all of
    /// them, and repainted on all of them when it changes (InvalidateUnder).
    internal sealed class SoftPin : Panel, ISoftGround
    {
        private readonly Control body, pin;
        private readonly PinLayout engine = new PinLayout();
        private TableLayoutPanel wraps;
        // How wide the first column of `wraps` is with nothing wrapped, as the last Model found it.
        private int naturalFirst;
        // Measures a name as it would be with a narrower column, or a line with other words, without touching it.
        private static readonly Label twin = new Label();
        private static Button twinButton;
        // The words each line, and the control, are planned for (Reserve), and the last size worked out for each.
        private readonly Dictionary<Control, string[]> reserved = new Dictionary<Control, string[]>();
        private readonly Dictionary<Control, Reservation> planned = new Dictionary<Control, Reservation>();
        // The hole in the content's window, in its coordinates: where the control is.
        private Rectangle hole;
        // The width it was last laid out at; 0 before that.
        private int arranged;

        private struct Reservation
        {
            internal int Room;
            internal Font Font;
            internal Size Size;
        }

        internal SoftPin(Control body, Control pin)
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                     ControlStyles.UserPaint | ControlStyles.ResizeRedraw, true);
            this.body = body;
            this.pin = pin;
            BackColor = Palette.Card;
            AutoSize = true;
            AutoSizeMode = AutoSizeMode.GrowAndShrink;
            Margin = new Padding(0);
            body.Dock = DockStyle.None;
            body.Anchor = AnchorStyles.Top | AnchorStyles.Left;
            body.Margin = new Padding(0);
            pin.Anchor = AnchorStyles.Top | AnchorStyles.Left;
            pin.Margin = new Padding(0);
            // In this order the content is at the top of the z-order and the control under it.
            Controls.Add(body);
            Controls.Add(pin);
            body.TabIndex = 0;
            pin.TabIndex = 1;
        }

        /// Plans the block as though `control` - a label in the content, or the pinned button - said the
        /// widest of `texts`, whatever it says now, so the block is laid out the same whichever of them it
        /// says. Words it is given that are wider still are planned for as they come.
        internal void Reserve(Control control, params string[] texts)
        {
            reserved[control] = texts;
            planned.Remove(control);
            PerformLayout();
        }

        /// Repaints `band`, in this block's coordinates, on every window of the content under it: they draw
        /// the part of the control's lift and focus ring over them in their own backgrounds, and a repaint of
        /// the block alone left the ring without its top and left edges and old pieces of it behind (v0.6.4).
        internal void InvalidateUnder(Rectangle band)
        {
            InvalidateUnder(body, body.Left, body.Top, band);
        }

        private static void InvalidateUnder(Control control, int x, int y, Rectangle band)
        {
            var bounds = new Rectangle(x, y, control.Width, control.Height);
            Rectangle part = Rectangle.Intersect(bounds, band);
            if (part.IsEmpty || !control.IsHandleCreated || control.IsDisposed) return;
            part.Offset(-x, -y);
            control.Invalidate(part, false);
            foreach (Control child in control.Controls)
                if (Soft.OwnVisible(child)) InvalidateUnder(child, x + child.Left, y + child.Top, band);
        }

        /// A grid of facts in the content - a column of names as wide as the widest, and their values - whose
        /// names wrap, down to their longest word, where its values would otherwise reach the control's column.
        internal TableLayoutPanel Wraps
        {
            get { return wraps; }
            set { wraps = value; PerformLayout(); }
        }

        public override System.Windows.Forms.Layout.LayoutEngine LayoutEngine { get { return engine; } }

        protected override void OnPaintBackground(PaintEventArgs e)
        {
            Ground.Paint(this, e);
        }

        public override Size GetPreferredSize(Size proposedSize)
        {
            int limit;
            if (proposedSize.Width > 1 && proposedSize.Width < 0x100000)
                return new Size(proposedSize.Width, Plan(proposedSize.Width, out limit));
            // Asked how narrow it can be (1) or how wide it would be (0), which a table asks for a column's
            // width before it asks how tall the block is that wide - the height its card's row then keeps.
            // The block fills its card, so: as wide as the card being measured (SoftCard.Measuring) leaves
            // it, or else as it was last laid out. Answered from what the content said, the height was asked
            // at a width the block never has, and followed the words: in English, Right now's row was 15 px
            // taller with the watcher running than stopped, planned for the same words (v0.6.4, measured);
            // answered from the last layout, a window given its height back kept the row of the width the
            // soft bar had left it.
            var card = Parent as SoftCard;
            int filled = card != null && card.Measuring > 0 ? card.Measuring - card.Padding.Horizontal - Margin.Horizontal : arranged;
            if (filled > 1) return new Size(filled, Plan(filled, out limit));
            // Never laid out nor measured in a card: as wide as its content would be with the control beside it.
            Size natural = body.GetPreferredSize(Size.Empty);
            if (!Soft.OwnVisible(pin)) return natural;
            Size size = PinSize();
            return new Size(natural.Width + Soft.Px(Brand.CardHeadGap) + PinWidth(), Math.Max(natural.Height, size.Height));
        }

        /// How tall the block is `width` wide, and how wide the names of `wraps` may be then (0: as wide as
        /// they are).
        private int Plan(int width, out int limit)
        {
            int whole;
            return Plan(width, out limit, out whole);
        }

        /// The same, and how tall the block is with every name of `wraps` whole (`whole`).
        private int Plan(int width, out int limit, out int whole)
        {
            limit = 0;
            var marks = new List<Mark>();
            int content = Model(body, 0, 0, width, 0, marks);
            whole = content;
            if (!Soft.OwnVisible(pin)) return content;
            Size size = PinSize();
            int gap = Soft.Px(Brand.CardFirstGap);
            // The column the control's widest words would take, so the text stops short of it whichever it says.
            int column = width - PinWidth() - Soft.Px(Brand.CardHeadGap);
            int beside = Math.Max(content, size.Height);
            int best = Needed(marks, content, column, size.Height, gap);
            whole = best;
            if (best == beside || wraps == null) return best;
            // The names wrap: as far as the values beside the control need, and else as far as every value
            // needs. The shortest block wins, the control under the facts among them.
            int natural = naturalFirst, shortest = LongestWord(wraps);
            int band = beside - size.Height - gap;
            for (int pass = 0; pass < 2; pass++)
            {
                int right = int.MinValue;
                foreach (Mark mark in marks)
                    if (mark.Column == 1 && (pass == 1 || mark.Box.Bottom > band)) right = Math.Max(right, mark.Box.Right);
                if (right <= column) continue;
                int candidate = natural - (right - column);
                if (candidate < shortest) continue;
                var wrapped = new List<Mark>();
                int height = Needed(wrapped, Model(body, 0, 0, width, candidate, wrapped), column, size.Height, gap);
                if (height < best)
                {
                    best = height;
                    limit = candidate;
                }
            }
            return best;
        }

        // A line of text where Model lays it out: its box in the block, and for a cell of `wraps` its column.
        private struct Mark
        {
            internal Rectangle Box;
            internal int Column;
        }

        /// How tall a block of `content` must be for a control `tall` high at its bottom right to be clear of
        /// every mark reaching right of `column`, `gap` under the lowest of them.
        private static int Needed(List<Mark> marks, int content, int column, int tall, int gap)
        {
            int height = Math.Max(content, tall);
            foreach (Mark mark in marks)
                if (mark.Box.Width > 0 && mark.Box.Right > column) height = Math.Max(height, mark.Box.Bottom + gap + tall);
            return height;
        }

        /// Lays `control` out `width` wide with its top left at (x, y) as its table would, adding a mark for
        /// what it draws, and answers its height. A table of one column (a list of lines) or of two (a column
        /// as wide as its widest cell, and the rest: a grid of facts) is laid out cell by cell; anything else
        /// is taken to fill its width. `limit` is how wide the names of `wraps` may be (0: as wide as they are).
        private int Model(Control control, int x, int y, int width, int limit, List<Mark> marks)
        {
            var table = control as TableLayoutPanel;
            if (table != null && table.ColumnCount == 1)
            {
                int left = x + table.Padding.Left, top = y + table.Padding.Top;
                int inner = width - table.Padding.Horizontal;
                foreach (Control child in table.Controls)
                {
                    if (!Soft.OwnVisible(child)) continue;
                    int room = Math.Max(0, inner - child.Margin.Horizontal);
                    Size size = Measured(child, room);
                    top += Place(child, left + child.Margin.Left, top + child.Margin.Top, Drawn(child, size, room), size,
                                 limit, -1, marks) + child.Margin.Vertical;
                }
                return top + table.Padding.Bottom - y;
            }
            if (table != null && table.ColumnCount == 2) return ModelGrid(table, x, y, width, limit, marks);
            return Place(control, x, y, width, Measured(control, width), limit, -1, marks);
        }

        private int ModelGrid(TableLayoutPanel table, int x, int y, int width, int limit, List<Mark> marks)
        {
            bool gives = table == wraps;
            var cells = new List<Control>();
            foreach (Control child in table.Controls)
                if (Soft.OwnVisible(child)) cells.Add(child);
            int inner = width - table.Padding.Horizontal;
            int first = 0, unwrapped = 0;
            for (int i = 0; i < cells.Count; i += 2)
            {
                Control name = cells[i];
                first = Math.Max(first, (gives ? NameSize(name, limit) : Measured(name, 0)).Width + name.Margin.Horizontal);
                if (gives) unwrapped = Math.Max(unwrapped, NameSize(name, 0).Width + name.Margin.Horizontal);
            }
            if (gives) naturalFirst = unwrapped;
            first = Math.Min(first, inner);
            int second = Math.Max(0, inner - first);
            int left = x + table.Padding.Left, top = y + table.Padding.Top;
            for (int i = 0; i < cells.Count; i += 2)
            {
                int line = 0;
                for (int j = i; j < cells.Count && j < i + 2; j++)
                {
                    Control cell = cells[j];
                    bool isName = j == i;
                    int room = Math.Max(0, (isName ? first : second) - cell.Margin.Horizontal);
                    Size size = isName && gives ? NameSize(cell, limit) : Measured(cell, room);
                    int height = Place(cell, left + (isName ? 0 : first) + cell.Margin.Left, top + cell.Margin.Top,
                                       Drawn(cell, size, room), size, limit, gives ? (isName ? 0 : 1) : -1, marks);
                    line = Math.Max(line, height + cell.Margin.Vertical);
                }
                top += line;
            }
            return top + table.Padding.Bottom - y;
        }

        /// A control laid out at (x, y), `width` wide and as tall as `size`: a table is looked into; a line of
        /// text, or anything else that draws, is marked. Answers its height.
        private int Place(Control control, int x, int y, int width, Size size, int limit, int column, List<Mark> marks)
        {
            if (control is TableLayoutPanel) return Model(control, x, y, width, limit, marks);
            bool draws = !(control is Label && string.IsNullOrEmpty(control.Text)) && !(control is Panel && control.Controls.Count == 0);
            if (draws)
            {
                var mark = new Mark();
                mark.Box = new Rectangle(x, y, width, size.Height);
                mark.Column = column;
                marks.Add(mark);
            }
            return size.Height;
        }

        /// A control's size in a cell `room` wide, or as wide as it would be when `room` is 0 - for a label
        /// with reserved words (Reserve), as wide and as tall as the widest and tallest of them and its own.
        private Size Measured(Control control, int room)
        {
            Size size = AsIs(control, room);
            string[] texts;
            var label = control as Label;
            if (label == null || !label.AutoSize || !reserved.TryGetValue(control, out texts)) return size;
            Reservation last;
            if (!planned.TryGetValue(control, out last) || last.Room != room || last.Font != label.Font)
            {
                last = new Reservation();
                last.Room = room;
                last.Font = label.Font;
                twin.AutoSize = true;
                twin.Font = label.Font;
                twin.Padding = label.Padding;
                twin.UseMnemonic = label.UseMnemonic;
                twin.MaximumSize = label.MaximumSize;
                foreach (string text in texts)
                {
                    twin.Text = text ?? "";
                    Size words = twin.GetPreferredSize(new Size(room, 0));
                    last.Size = new Size(Math.Max(last.Size.Width, words.Width), Math.Max(last.Size.Height, words.Height));
                }
                planned[control] = last;
            }
            return new Size(Math.Max(size.Width, last.Size.Width), Math.Max(size.Height, last.Size.Height));
        }

        private static Size AsIs(Control control, int room)
        {
            return control.AutoSize ? control.GetPreferredSize(new Size(room, 0)) : control.Size;
        }

        /// A name of `wraps` as it is with its column at most `limit` wide (0: as wide as it is), measured on
        /// a twin so the name itself is not changed. Asked for a width, which a label never answers from what
        /// it remembers of other text.
        private static Size NameSize(Control cell, int limit)
        {
            var label = cell as Label;
            if (label == null) return AsIs(cell, 0);
            twin.AutoSize = true;
            twin.Font = label.Font;
            twin.Padding = label.Padding;
            twin.UseMnemonic = label.UseMnemonic;
            twin.MaximumSize = limit > 0 ? new Size(Math.Max(1, limit - cell.Margin.Horizontal), 0) : Size.Empty;
            twin.Text = label.Text;
            return twin.GetPreferredSize(new Size(0x3FFFFFFF, 0));
        }

        /// How narrow the names of a grid can wrap: their longest word, and the name's margin.
        private static int LongestWord(TableLayoutPanel grid)
        {
            int longest = 0;
            bool isName = true;
            foreach (Control cell in grid.Controls)
            {
                if (!Soft.OwnVisible(cell)) continue;
                if (isName && cell is Label)
                {
                    string text = cell.Text;
                    for (int start = 0; start < text.Length; )
                    {
                        int end = text.IndexOf(' ', start);
                        if (end < 0) end = text.Length;
                        if (end > start)
                        {
                            twin.MaximumSize = Size.Empty;
                            twin.Font = cell.Font;
                            twin.Padding = cell.Padding;
                            twin.Text = text.Substring(start, end - start);
                            longest = Math.Max(longest, twin.GetPreferredSize(new Size(0x3FFFFFFF, 0)).Width + cell.Margin.Horizontal);
                        }
                        start = end + 1;
                    }
                }
                isName = !isName;
            }
            return longest;
        }

        /// How wide a control is drawn in its cell: all of the cell when it is stretched across it.
        private static int Drawn(Control control, Size size, int room)
        {
            bool stretched = control.Dock == DockStyle.Fill ||
                             (control.Anchor & (AnchorStyles.Left | AnchorStyles.Right)) == (AnchorStyles.Left | AnchorStyles.Right);
            return stretched ? room : Math.Min(size.Width, room);
        }

        private Size PinSize()
        {
            return pin.AutoSize ? pin.GetPreferredSize(Size.Empty) : pin.Size;
        }

        /// How wide the control is with the widest of its reserved words (Reserve), or as it is: the width its
        /// column is planned for. The control itself is as wide as what it says now, at the block's right edge.
        private int PinWidth()
        {
            int width = PinSize().Width;
            string[] texts;
            var button = pin as ButtonBase;
            if (button == null || !button.AutoSize || !reserved.TryGetValue(pin, out texts)) return width;
            Reservation last;
            if (!planned.TryGetValue(pin, out last) || last.Font != button.Font)
            {
                last = new Reservation();
                last.Font = button.Font;
                if (twinButton == null)
                {
                    twinButton = new Button();
                    twinButton.AutoSize = true;
                    twinButton.AutoSizeMode = AutoSizeMode.GrowAndShrink;
                }
                twinButton.FlatStyle = button.FlatStyle;
                if (button.FlatStyle == FlatStyle.Flat) twinButton.FlatAppearance.BorderSize = button.FlatAppearance.BorderSize;
                twinButton.Font = button.Font;
                twinButton.Padding = button.Padding;
                twinButton.MaximumSize = Size.Empty;
                twinButton.MinimumSize = button.MinimumSize;
                twinButton.MaximumSize = button.MaximumSize;
                twinButton.UseMnemonic = button.UseMnemonic;
                foreach (string text in texts)
                {
                    twinButton.Text = text ?? "";
                    Size words = twinButton.GetPreferredSize(Size.Empty);
                    last.Size = new Size(Math.Max(last.Size.Width, words.Width), Math.Max(last.Size.Height, words.Height));
                }
                planned[pin] = last;
            }
            return Math.Max(width, last.Size.Width);
        }

        private void Arrange()
        {
            int width = ClientSize.Width;
            if (width > 1) arranged = width;
            int limit, whole;
            int needed = Plan(width, out limit, out whole);
            // The names give way only to keep the block short. A block stretched taller than that - beside a taller
            // card, or down a page whose rows share its height (SoftRows) - has the room for them whole, with the
            // control under the lowest line in its column, and keeps them whole.
            if (limit > 0 && whole <= ClientSize.Height)
            {
                limit = 0;
                needed = whole;
            }
            if (wraps != null)
            {
                bool isName = true;
                foreach (Control cell in wraps.Controls)
                {
                    if (!Soft.OwnVisible(cell)) continue;
                    Size wanted = limit > 0 ? new Size(Math.Max(1, limit - cell.Margin.Horizontal), 0) : Size.Empty;
                    if (isName && cell.MaximumSize != wanted) cell.MaximumSize = wanted;
                    isName = !isName;
                }
            }
            int content = body.GetPreferredSize(new Size(width, 0)).Height;
            if (body.Left != 0 || body.Top != 0 || body.Width != width || body.Height != content)
            {
                body.SetBounds(0, 0, width, content);
                // Laid out at its width, what it holds can change under it - Recently finished fits its names
                // to the width it gets - so it is planned again.
                int ignored;
                needed = Plan(width, out ignored);
            }
            var place = Rectangle.Empty;
            if (Soft.OwnVisible(pin))
            {
                Size size = PinSize();
                place = new Rectangle(width - size.Width, Math.Max(0, ClientSize.Height - size.Height), size.Width, size.Height);
                if (pin.Bounds != place) pin.Bounds = place;
            }
            Cut(Rectangle.Intersect(place, body.Bounds));
            if (needed <= ClientSize.Height) return;
            // Given less than it needs: its row was measured before what it holds changed under it. The page lays
            // what it holds out once more (SoftPage.Unsettle); left, History stood over the last outcomes of a
            // Japanese Overview opened at 150% (v0.6.4, measured).
            for (Control c = Parent; c != null; c = c.Parent)
            {
                var page = c as SoftPage;
                if (page == null) continue;
                page.Unsettle();
                break;
            }
        }

        /// Cuts the control's place out of the content's window, which is above it in the z-order - or
        /// gives the content its whole window back when the control is beside none of it. What lies under
        /// the hole is the control, and the hole is its size: every line beside it stops a head gap short.
        private void Cut(Rectangle place)
        {
            place.Offset(-body.Left, -body.Top);
            if (place == hole) return;
            hole = place;
            if (place.IsEmpty)
            {
                body.Region = null;
                return;
            }
            // Everything the window could ever be but the hole, so the content growing needs no new region.
            var region = new Region(new Rectangle(0, 0, short.MaxValue, short.MaxValue));
            region.Exclude(place);
            body.Region = region;
        }

        private sealed class PinLayout : System.Windows.Forms.Layout.LayoutEngine
        {
            public override bool Layout(object container, LayoutEventArgs layoutEventArgs)
            {
                ((SoftPin)container).Arrange();
                // As an AutoSize panel's own layout does: what it holds may have changed its height.
                return true;
            }
        }
    }

    /// Painting a native window that paints its own face: one WM_PAINT, drawn off-screen and
    /// copied in, or into the device context a capture hands it.
    internal static class NativePaint
    {
        [DllImport("user32.dll")]
        private static extern IntPtr BeginPaint(IntPtr window, IntPtr paint);

        [DllImport("user32.dll")]
        private static extern bool EndPaint(IntPtr window, IntPtr paint);

        internal const int WM_PAINT = 0x000F;
        internal const int WM_ERASEBKGND = 0x0014;
        internal const int WM_PRINTCLIENT = 0x0318;

        /// True when `m` was a paint message and `draw` has answered it.
        internal static bool Handle(ref Message m, Size size, Action<Graphics> draw)
        {
            if (m.Msg == WM_ERASEBKGND)
            {
                m.Result = (IntPtr)1;
                return true;
            }
            if (m.Msg != WM_PAINT && m.Msg != WM_PRINTCLIENT) return false;
            if (m.WParam != IntPtr.Zero)
            {
                using (Graphics g = Graphics.FromHdc(m.WParam)) draw(g);
            }
            else if (m.Msg == WM_PAINT)
            {
                IntPtr paint = Marshal.AllocHGlobal(128);   // a PAINTSTRUCT is 72 bytes on x64
                try
                {
                    IntPtr dc = BeginPaint(m.HWnd, paint);
                    try
                    {
                        if (size.Width > 0 && size.Height > 0)
                            using (Graphics screen = Graphics.FromHdc(dc))
                            using (BufferedGraphics buffer = BufferedGraphicsManager.Current.Allocate(screen, new Rectangle(Point.Empty, size)))
                            {
                                draw(buffer.Graphics);
                                buffer.Render(screen);
                            }
                    }
                    finally { EndPaint(m.HWnd, paint); }
                }
                finally { Marshal.FreeHGlobal(paint); }
            }
            m.Result = IntPtr.Zero;
            return true;
        }
    }

    /// A button: raised on its ground, or filled with the accent when it is the page's one
    /// primary action. Under the pointer a plain button comes up to the surface and the accent
    /// brightens a step; pressed, either sinks into a well; disabled, it is flat, with muted
    /// words and no accent, so the accent never marks a dead control.
    internal sealed class SoftButton : Button, ISoftLifted
    {
        private bool primary, danger, hover, pressed;
        private readonly LiftTracker tracker;

        internal SoftButton(bool primary)
        {
            this.primary = primary;
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint |
                     ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
            FlatStyle = FlatStyle.Flat;
            FlatAppearance.BorderSize = 0;
            UseVisualStyleBackColor = false;
            Cursor = Cursors.Hand;
            tracker = new LiftTracker(this, "control");
        }

        internal bool Primary
        {
            get { return primary; }
            set { primary = value; Invalidate(); }
        }

        /// A button whose action cannot be taken back: its words are in the danger colour.
        internal bool Danger
        {
            get { return danger; }
            set { danger = value; Invalidate(); }
        }

        string ISoftLifted.Lift { get { return Enabled && !pressed ? "control" : null; } }
        float ISoftLifted.Radius { get { return Soft.PxF(Brand.RadiusControl); } }
        Rectangle ISoftLifted.Face { get { return ClientRectangle; } }
        bool ISoftLifted.Ring { get { return Focused && ShowFocusCues; } }

        private void Press(bool down)
        {
            if (pressed == down) return;
            pressed = down;
            Invalidate();
            tracker.Update();
        }

        protected override void OnMouseEnter(EventArgs e) { hover = true; Invalidate(); base.OnMouseEnter(e); }
        protected override void OnMouseLeave(EventArgs e) { hover = false; Press(false); Invalidate(); base.OnMouseLeave(e); }
        protected override void OnMouseDown(MouseEventArgs e) { if (e.Button == MouseButtons.Left) Press(true); base.OnMouseDown(e); }
        protected override void OnMouseUp(MouseEventArgs e) { Press(false); base.OnMouseUp(e); }
        protected override void OnEnabledChanged(EventArgs e) { Invalidate(); base.OnEnabledChanged(e); }
        protected override void OnGotFocus(EventArgs e) { Invalidate(); base.OnGotFocus(e); }
        protected override void OnLostFocus(EventArgs e) { Invalidate(); base.OnLostFocus(e); }

        protected override void OnPaint(PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            Rectangle face = ClientRectangle;
            float radius = Soft.PxF(Brand.RadiusControl);
            Ground.PaintBehind(this, g, face, radius);
            Color fill, edge, text;
            if (!Enabled)
            {
                fill = Palette.Surface;
                edge = Palette.Line;
                text = Palette.Muted;
            }
            else if (primary)
            {
                fill = pressed ? Palette.AccentPressed : hover ? Palette.AccentHover : Palette.Accent;
                edge = fill;
                text = Palette.OnAccent;
            }
            else
            {
                fill = pressed ? Palette.Inset : hover ? Palette.Surface : Palette.Raised;
                edge = Palette.Line;
                text = danger ? Palette.Danger : Palette.Ink;
            }
            Soft.Body(g, face, radius, fill, edge, pressed && Enabled);
            TextRenderer.DrawText(g, Text, Font, face, text,
                                  TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter |
                                  TextFormatFlags.SingleLine | TextFormatFlags.EndEllipsis);
        }
    }

    /// A true-or-false setting, of one of two kinds, with its words to the right. Still a CheckBox, so
    /// Space turns it, the focus cue shows where the keyboard is, and a screen reader says what it
    /// is and whether it is on.
    ///
    /// The kind follows what the setting is (v0.6.4), the same on every surface. A switch - the
    /// panel's 40 by 22 pill - turns something that runs on or off: the notifications, the
    /// notification-area icon, reduced motion, running at sign-in. A check box (Box) picks which items
    /// of a list apply: which kinds of interruption may be recovered, which events notify. Its box sits
    /// left of its label, as it does on the popup and the panel: unchecked it is the sunken well a
    /// field is, checked the accent with an on-accent mark, disabled a flat surface with a muted mark,
    /// and in High Contrast system colours with no shadow at all (brand.CHECKBOX).
    ///
    /// A change moves (v0.6.5): the switch's knob slides end to end and its track cross-fades from the
    /// well to the accent, and a check box's fill and mark fade in or out, over brand's transition on
    /// its one curve (Motion). Only the glyph is repainted while it moves, and the timer stops when it
    /// arrives. With motion reduced, Windows' animation effects off, in High Contrast, or out of sight,
    /// the change is immediate. It follows Checked, so a caller that asks first and sets Checked only once
    /// the change is confirmed has a switch that moves only then.
    internal sealed class SoftCheck : CheckBox, ISoftLifted
    {
        private readonly LiftTracker tracker;
        private readonly Transition turn;
        private bool box;

        internal SoftCheck()
        {
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint |
                     ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
            Cursor = Cursors.Hand;
            AccessibleRole = AccessibleRole.CheckButton;
            tracker = new LiftTracker(this, "control");
            turn = new Transition(this, 0.0);
        }

        /// How far on the glyph is drawn, from 0 (off) to 1 (on): between the two only while it moves.
        internal double Progress { get { return turn.Value; } }

        /// Whether it is moving between off and on; its timer runs only then.
        internal bool Moving { get { return turn.Running; } }

        /// Drawn as a check box rather than a switch.
        internal bool Box
        {
            get { return box; }
            set
            {
                if (box == value) return;
                box = value;
                if (AutoSize && Parent != null) Parent.PerformLayout();
                Invalidate();
                tracker.Update();
            }
        }

        private int Gap { get { return box ? Soft.Px(Brand.CheckGap) : Soft.Px(9); } }

        /// The switch's track, or the check box's box: at the left, on the control's middle line.
        internal Rectangle Glyph
        {
            get
            {
                if (box)
                {
                    int size = Soft.Px(Brand.CheckSize);
                    return new Rectangle(0, (Height - size) / 2, size, size);
                }
                int height = Soft.Px(Brand.SwitchHeight);
                return new Rectangle(0, (Height - height) / 2, Soft.Px(Brand.SwitchWidth), height);
            }
        }

        // No lift - a switch and a box are wells - but the focus ring runs outside the control on
        // the left, so the ground draws that part of it.
        string ISoftLifted.Lift { get { return null; } }
        float ISoftLifted.Radius { get { return box ? Soft.PxF(Brand.RadiusCheck) : Soft.Px(Brand.SwitchHeight) / 2f; } }
        Rectangle ISoftLifted.Face { get { return Glyph; } }
        bool ISoftLifted.Ring { get { return Focused && ShowFocusCues; } }

        public override Size GetPreferredSize(Size proposedSize)
        {
            Size text = TextRenderer.MeasureText(Text ?? "", Font, new Size(int.MaxValue, int.MaxValue),
                                                 TextFormatFlags.SingleLine);
            int glyphWidth = box ? Soft.Px(Brand.CheckSize) : Soft.Px(Brand.SwitchWidth);
            int glyphHeight = box ? Soft.Px(Brand.CheckSize) : Soft.Px(Brand.SwitchHeight);
            return new Size(glyphWidth + Gap + text.Width + Soft.Px(6), Math.Max(glyphHeight, text.Height) + Soft.Px(6));
        }

        protected override void OnCheckedChanged(EventArgs e)
        {
            // Paint only: the glyph glides to its new state, and nothing is laid out.
            turn.Area = Glyph;
            turn.To(Checked ? 1.0 : 0.0, Motion.Allowed(this));
            Invalidate();
            base.OnCheckedChanged(e);
        }

        protected override void OnEnabledChanged(EventArgs e) { Invalidate(); base.OnEnabledChanged(e); }
        protected override void OnGotFocus(EventArgs e) { Invalidate(); base.OnGotFocus(e); }
        protected override void OnLostFocus(EventArgs e) { Invalidate(); base.OnLostFocus(e); }
        protected override void OnTextChanged(EventArgs e) { Invalidate(); base.OnTextChanged(e); }

        protected override void Dispose(bool disposing)
        {
            if (disposing) turn.Dispose();
            base.Dispose(disposing);
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            Ground.PaintArea(this, g, ClientRectangle);
            Rectangle glyph = Glyph;
            double on = turn.Value;
            if (box) DrawBoxAt(g, glyph, on, Enabled);
            else Soft.SwitchAt(g, glyph, on, Enabled, Parent != null ? Ground.Colour(Parent) : Palette.Card);
            var textBounds = new Rectangle(glyph.Right + Gap, 0, Math.Max(0, Width - glyph.Right - Gap), Height);
            TextRenderer.DrawText(g, Text, Font, textBounds, Enabled ? ForeColor : Palette.Muted,
                                  TextFormatFlags.VerticalCenter | TextFormatFlags.Left |
                                  TextFormatFlags.SingleLine | TextFormatFlags.EndEllipsis);
            if (Focused && ShowFocusCues)
                Soft.Ring(g, glyph, box ? Soft.PxF(Brand.RadiusCheck) : glyph.Height / 2f);
        }

        /// The check box in `face`, a CheckSize square at the window's scale: its fill, the inset well
        /// while it is unchecked and enabled, its hairline, and the mark - the brand's centre line,
        /// stroked CheckStroke wide with flat ends and a mitred corner.
        internal static void DrawBox(Graphics g, Rectangle face, bool on, bool enabled)
        {
            Color fill, edge, mark;
            bool marked, well;
            if (Palette.Contrast)
            {
                fill = Brand.CheckSystemFill(on, enabled);
                edge = Brand.CheckSystemEdge(on, enabled);
                marked = Brand.CheckSystemMark(on, enabled, out mark);
                well = false;
            }
            else
            {
                fill = Tokens.Dark ? Brand.Dark.CheckFill(on, enabled) : Brand.CheckFill(on, enabled);
                edge = Tokens.Dark ? Brand.Dark.CheckEdge(on, enabled) : Brand.CheckEdge(on, enabled);
                marked = Tokens.Dark ? Brand.Dark.CheckMark(on, enabled, out mark) : Brand.CheckMark(on, enabled, out mark);
                well = Brand.CheckWell(on, enabled);
            }
            Soft.Body(g, face, Soft.PxF(Brand.RadiusCheck), fill, edge, well ? "inset" : null);
            if (!marked) return;
            float scale = (float)SettingsForm.DpiScale;
            GraphicsState state = g.Save();
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.PixelOffsetMode = PixelOffsetMode.Half;
            using (var pen = new Pen(mark, Soft.PxF(Brand.CheckStroke)))
            {
                pen.StartCap = LineCap.Flat;
                pen.EndCap = LineCap.Flat;
                pen.LineJoin = LineJoin.Miter;
                g.DrawLines(pen, new[] {
                    new PointF(face.X + Brand.CheckMarkStartX * scale, face.Y + Brand.CheckMarkStartY * scale),
                    new PointF(face.X + Brand.CheckMarkCornerX * scale, face.Y + Brand.CheckMarkCornerY * scale),
                    new PointF(face.X + Brand.CheckMarkEndX * scale, face.Y + Brand.CheckMarkEndY * scale) });
            }
            g.Restore(state);
        }

        /// The check box `on` of the way from unchecked (0) to checked (1), as it fades between them
        /// (v0.6.5): the unchecked box, and the checked one - its fill, edge and mark - over it at that
        /// opacity. At 0 and 1 it is exactly DrawBox.
        internal static void DrawBoxAt(Graphics g, Rectangle face, double on, bool enabled)
        {
            if (on <= 0.0 || on >= 1.0 || Palette.Contrast || face.Width <= 0 || face.Height <= 0)
            {
                DrawBox(g, face, on >= 0.5, enabled);
                return;
            }
            DrawBox(g, face, false, enabled);
            using (var layer = new Bitmap(face.Width + 2, face.Height + 2, PixelFormat.Format32bppPArgb))
            {
                using (Graphics drawn = Graphics.FromImage(layer))
                {
                    drawn.Clear(Color.Transparent);
                    drawn.TranslateTransform(1 - face.X, 1 - face.Y);
                    DrawBox(drawn, face, true, enabled);
                }
                Soft.Faded(g, layer, new Rectangle(face.X - 1, face.Y - 1, layer.Width, layer.Height), on);
            }
        }
    }

    /// A drop-down that is a well, as the panel's select is. Its closed face is drawn here
    /// entirely - the ground behind its corners, the inset well, the chosen item, the chevron -
    /// and it is always one field high.
    ///
    /// The list it opens is its own (v0.6.5): a card of the cards' material floating just under it,
    /// the cards' soft shadow spilling outside the card (SoftDropList). Windows' list - square
    /// corners, a thin grey border, no shadow and a flat blue band - was the one part of the window
    /// drawn in another design, and the design is one. So what Windows' list did for it, it now does
    /// itself, and the tests hold it to each:
    ///   * it opens on a click, F4, Alt+Down, Alt+Up or Space, and on CB_SHOWDROPDOWN - DroppedDown,
    ///     and what UI Automation's Expand sends. Those are every way Windows' list could open, and all
    ///     of them are answered here, so Windows' list never appears; CB_GETDROPPEDSTATE answers for
    ///     this one;
    ///   * while it is open Up, Down, Home, End, Page Up and Page Down move the highlight, typing
    ///     finds the next item that starts with what was typed (TypeAhead), Enter, F4, Alt+Up,
    ///     Alt+Down, Space and Tab take the highlighted item, and Escape closes it as it was. A click
    ///     takes an item and the wheel scrolls a list longer than it shows;
    ///   * a click anywhere else closes it and goes no further, as the click that closes Windows' list
    ///     does; so does the window losing activation or moving, or the drop-down losing the focus,
    ///     moving or hiding;
    ///   * the focus stays on the drop-down throughout: the list never activates and never takes the
    ///     focus, so every key comes here;
    ///   * a screen reader hears it: the drop-down says it is expanded and has a popup, its one child is
    ///     the list and the list's children are its items, and as the highlight moves the drop-down's
    ///     window raises focus and selection events for the item with the list's own object id
    ///     (ListObjectId), which WM_GETOBJECT answers with the list. UI Automation - Narrator - reads it
    ///     as it reads a Win32 drop-down list, a combo box with its choice that it can expand and
    ///     collapse (UiaRoot), and hears the item the highlight is on (NotifyItem);
    ///   * taking an item sets SelectedIndex, so SelectedIndexChanged and every caller work as before,
    ///     and SelectionChangeCommitted is raised as a choice from the list raises it.
    internal sealed class SoftCombo : ComboBox
    {
        private const int WM_KEYDOWN = 0x0100;
        private const int WM_CHAR = 0x0102;
        private const int WM_SYSKEYDOWN = 0x0104;
        private const int WM_SYSCHAR = 0x0106;
        private const int WM_LBUTTONDOWN = 0x0201;
        private const int WM_LBUTTONDBLCLK = 0x0203;
        private const int WM_MOUSEWHEEL = 0x020A;
        private const int CB_SHOWDROPDOWN = 0x014F;
        private const int CB_GETDROPPEDSTATE = 0x0157;

        /// The object id a screen reader asks the drop-down's window for (WM_GETOBJECT) to reach its
        /// list; the focus and selection events for the list's items are raised with it.
        internal const int ListObjectId = 1;

        /// How long letters typed one after another make one search, in milliseconds.
        internal const int TypeAhead = 1000;

        private SoftDropList drop;
        private int highlight = -1;
        private bool keyboard;
        private string typed = "";
        private readonly System.Diagnostics.Stopwatch typing = new System.Diagnostics.Stopwatch();
        // The character a key this handled is followed by (Enter's, Escape's, Space's), which goes no further.
        private int swallow = -1;
        private DropFilter filter;
        private ListAccessible listObject;
        private readonly EventHandler closer;
        private readonly List<Control> watched = new List<Control>();
        private Form watchedForm;

        internal SoftCombo()
        {
            DrawMode = DrawMode.OwnerDrawFixed;
            DropDownStyle = ComboBoxStyle.DropDownList;
            FlatStyle = FlatStyle.Flat;
            BackColor = Palette.Raised;
            ForeColor = Palette.Ink;
            // How many items its list shows before it scrolls: every list in the window whole - the
            // longest, the Interface language, has ten choices.
            MaxDropDownItems = 12;
            closer = delegate { CloseList(); };
            Fit();
        }

        /// The height every SoftCombo has: the panel's field height.
        internal static int FieldHeight
        {
            get { return Soft.Px(Brand.FieldHeight); }
        }

        // A native drop-down list is its item height plus a frame of its own - six device pixels
        // at every scale, measured - and ignores any height it is given once it has a window. So
        // the height is set through the item height: from that frame before there is a window,
        // so the first layout is already right, then from the real frame once there is one, and
        // again whenever the font changes - which is when it used to grow past its row.
        //
        // Before there is a window the item height is only recorded, with the drop-down drawn as
        // a plain one for that moment. Set on an owner-drawn drop-down, ComboBox makes the window
        // there and then (UpdateItemHeight): every one had a window and a list window from its
        // constructor, in Settings sections nobody had opened, and the height it has before a
        // window was never measured. The window takes the recorded height when it is made.
        private const int Frame = 6;

        private void Fit()
        {
            if (!IsHandleCreated)
            {
                int item = Math.Max(1, FieldHeight - Frame);
                if (ItemHeight != item)
                {
                    DrawMode = DrawMode.Normal;
                    ItemHeight = item;
                    DrawMode = DrawMode.OwnerDrawFixed;
                }
                Height = FieldHeight;
                return;
            }
            int wanted = Math.Max(1, FieldHeight - (Height - ItemHeight));
            if (ItemHeight != wanted) ItemHeight = wanted;
        }

        protected override void OnHandleCreated(EventArgs e) { base.OnHandleCreated(e); Fit(); }
        protected override void OnHandleDestroyed(EventArgs e) { CloseList(); base.OnHandleDestroyed(e); }
        protected override void OnFontChanged(EventArgs e) { base.OnFontChanged(e); Fit(); Invalidate(); }

        /// The height it really has. The base class answers from the font alone - 33 for a
        /// 42-pixel owner-drawn combo at 150% - and a row measured from that cut the field's
        /// bottom edge off.
        public override Size GetPreferredSize(Size proposedSize)
        {
            return new Size(base.GetPreferredSize(proposedSize).Width, IsHandleCreated ? Height : FieldHeight);
        }

        // Without a window ComboBox holds a drop-down list to its font's height whatever height it
        // is given - 23 at 9 points, measured, in a constraint a subclass cannot change - so until
        // the window takes its height from the item height, the bounds are put back to a field's
        // height. Once there is a window they are left alone.
        protected override void SetBoundsCore(int x, int y, int width, int height, BoundsSpecified specified)
        {
            base.SetBoundsCore(x, y, width, height, specified);
            if (!IsHandleCreated && Height != FieldHeight) UpdateBounds(Left, Top, Width, FieldHeight);
        }

        protected override void OnSelectedIndexChanged(EventArgs e) { base.OnSelectedIndexChanged(e); Invalidate(); }
        protected override void OnEnabledChanged(EventArgs e) { base.OnEnabledChanged(e); Invalidate(); }
        protected override void OnGotFocus(EventArgs e) { base.OnGotFocus(e); Invalidate(); }
        protected override void OnLostFocus(EventArgs e) { base.OnLostFocus(e); Invalidate(); }
        protected override void OnDropDownClosed(EventArgs e) { base.OnDropDownClosed(e); Invalidate(); }
        protected override void OnResize(EventArgs e) { base.OnResize(e); Invalidate(); }

        protected override void Dispose(bool disposing)
        {
            if (disposing) CloseList();
            base.Dispose(disposing);
        }

        // ------------------------------------------------------------------ its own list

        /// Whether its list is open.
        internal bool Open { get { return drop != null; } }

        /// The item the highlight is on while the list is open: the one Enter takes.
        internal int Highlight { get { return highlight; } }

        /// Whether the highlight shows the focus ring: the list was opened, or moved, from the keyboard.
        /// Under the pointer the item there is raised instead.
        internal bool KeyboardCues { get { return keyboard; } }

        /// The open list, or null.
        internal SoftDropList DropList { get { return drop; } }

        protected override void WndProc(ref Message m)
        {
            if (IsHandleCreated && NativePaint.Handle(ref m, ClientSize, PaintFace)) return;
            if (ListMessage(ref m)) return;
            if (UiaRoot(ref m)) return;
            base.WndProc(ref m);
        }

        private const int WM_GETOBJECT = 0x003D;
        private const int UiaRootObjectId = -25;

        /// UI Automation asking the drop-down's window for a provider of its own (WM_GETOBJECT with
        /// UiaRootObjectId) is told there is none, as a Win32 drop-down list tells it, and reads the drop-down
        /// the way it reads every one of those: a combo box, its choice (the Selection pattern), expanded or
        /// collapsed, and Expand and Collapse - which send CB_SHOWDROPDOWN, answered here with this list.
        ///
        /// Left to ComboBox, .NET 4.8 answers it with a provider of its own around whatever accessible object
        /// the control has, and around ComboAccessible that provider says only "pane": no choice, no Expand or
        /// Collapse, no children - the control type and the patterns come from .NET's own ComboBox object,
        /// which a ControlAccessibleObject cannot supply (they are internal to WinForms). Narrator read every
        /// drop-down in the window as a pane it could not open (v0.6.5, measured with UI Automation against
        /// both builds; v0.6.4's was "combo box, Deutsch, collapsed"). A screen reader that reads MSAA still
        /// gets ComboAccessible (OBJID_CLIENT), and the items are announced to both kinds (NotifyItem).
        /// Compared on the low 32 bits: the id is a DWORD, which a caller may pass sign-extended or not.
        private bool UiaRoot(ref Message m)
        {
            if (m.Msg != WM_GETOBJECT || unchecked((int)m.LParam.ToInt64()) != UiaRootObjectId) return false;
            DefWndProc(ref m);
            return true;
        }

        /// Every message that would open Windows' own list, and the keys and the wheel while this one
        /// is open. True when it was answered here.
        private bool ListMessage(ref Message m)
        {
            int message = m.Msg;
            if (message == CB_SHOWDROPDOWN)
            {
                if (m.WParam != IntPtr.Zero) OpenList(false);
                else CloseList();
                m.Result = (IntPtr)1;
                return true;
            }
            if (message == CB_GETDROPPEDSTATE)
            {
                m.Result = (IntPtr)(Open ? 1 : 0);
                return true;
            }
            if (message == WM_LBUTTONDOWN || message == WM_LBUTTONDBLCLK)
            {
                if (!Focused) Focus();
                if (Open) CloseList();
                else OpenList(false);
                return true;
            }
            if (message == WM_MOUSEWHEEL && Open)
            {
                drop.Wheel(WheelDelta(m.WParam));
                m.Result = IntPtr.Zero;
                return true;
            }
            if (message == WM_KEYDOWN || message == WM_SYSKEYDOWN) return Key(ref m);
            if (message == WM_CHAR || message == WM_SYSCHAR)
            {
                int code = (int)(m.WParam.ToInt64() & 0xFFFF);
                bool swallowed = code == swallow;
                swallow = -1;
                if (swallowed) return true;
                if (message == WM_CHAR && Open)
                {
                    Typed((char)code);
                    return true;
                }
            }
            return false;
        }

        internal static int WheelDelta(IntPtr wParam)
        {
            return unchecked((short)((wParam.ToInt64() >> 16) & 0xFFFF));
        }

        private bool Key(ref Message m)
        {
            swallow = -1;
            Keys key = (Keys)(int)(m.WParam.ToInt64() & 0xFFFF);
            // The context bit, not ModifierKeys: it is what the message says, whatever the keyboard is doing now.
            bool alt = m.Msg == WM_SYSKEYDOWN && (m.LParam.ToInt64() & 0x20000000L) != 0;
            bool plain = m.Msg == WM_KEYDOWN && (ModifierKeys & (Keys.Control | Keys.Alt)) == Keys.None;
            if (!Open)
            {
                bool opens = (alt && (key == Keys.Down || key == Keys.Up)) || (plain && (key == Keys.F4 || key == Keys.Space));
                if (!opens) return false;
                if (key == Keys.Space) swallow = ' ';
                OpenList(true);
                return true;
            }
            if (alt)
            {
                if (key != Keys.Down && key != Keys.Up) return false;
                Pick(highlight);
                return true;
            }
            if (m.Msg != WM_KEYDOWN) return false;
            int page = Math.Max(1, drop.Rows - 1);
            if (key == Keys.Down) MoveHighlight(highlight + 1);
            else if (key == Keys.Up) MoveHighlight(highlight - 1);
            else if (key == Keys.Home) MoveHighlight(0);
            else if (key == Keys.End) MoveHighlight(Items.Count - 1);
            else if (key == Keys.PageDown) MoveHighlight(highlight + page);
            else if (key == Keys.PageUp) MoveHighlight(highlight - page);
            else if (key == Keys.Return)
            {
                swallow = '\r';
                Pick(highlight);
            }
            else if (key == Keys.Escape)
            {
                swallow = 27;
                CloseList();
            }
            else if (key == Keys.F4) Pick(highlight);
            else if (key == Keys.Space)
            {
                // A space inside a search is part of it ("Last 7 days"); otherwise it takes the item.
                if (Typing) return true;
                swallow = ' ';
                Pick(highlight);
            }
            else if (key != Keys.Left && key != Keys.Right) return false;
            return true;
        }

        // While the list is open the keys it answers are the drop-down's, never the window's: Escape does not
        // close a dialog, Enter does not press a default button.
        protected override bool IsInputKey(Keys keyData)
        {
            if (Open && (keyData & (Keys.Alt | Keys.Control)) == Keys.None)
            {
                Keys key = keyData & Keys.KeyCode;
                if (key == Keys.Up || key == Keys.Down || key == Keys.Home || key == Keys.End || key == Keys.PageUp ||
                    key == Keys.PageDown || key == Keys.Return || key == Keys.Escape || key == Keys.Space || key == Keys.F4)
                    return true;
            }
            return base.IsInputKey(keyData);
        }

        // Tab takes the highlighted item and moves on, as a select-only combo box's Tab does.
        protected override bool ProcessDialogKey(Keys keyData)
        {
            if (Open && (keyData & Keys.KeyCode) == Keys.Tab && (keyData & (Keys.Alt | Keys.Control)) == Keys.None)
                Pick(highlight);
            return base.ProcessDialogKey(keyData);
        }

        private bool Typing
        {
            get { return typed.Length > 0 && typing.ElapsedMilliseconds < TypeAhead; }
        }

        private void Typed(char character)
        {
            if (character < ' ') return;
            if (!Typing) typed = "";
            typed += character;
            typing.Reset();
            typing.Start();
            var texts = new string[Items.Count];
            for (int i = 0; i < texts.Length; i++) texts[i] = GetItemText(Items[i]);
            int found = Find(texts, typed, highlight);
            if (found >= 0) MoveHighlight(found);
        }

        /// The item `typed` finds among `texts`, with the highlight on `from`: the first from there on
        /// that starts with it, ignoring case, round to the start again. A first letter looks from the
        /// item after the highlight, and the same letter again steps on through the items that start
        /// with it, as Windows' lists do; a longer search keeps the highlighted item while it still
        /// matches. -1 when none does.
        internal static int Find(string[] texts, string typed, int from)
        {
            int count = texts == null ? 0 : texts.Length;
            if (count == 0 || string.IsNullOrEmpty(typed)) return -1;
            bool repeated = true;
            for (int i = 1; i < typed.Length; i++)
                if (char.ToUpperInvariant(typed[i]) != char.ToUpperInvariant(typed[0])) repeated = false;
            string wanted = repeated ? typed.Substring(0, 1) : typed;
            int start = repeated ? from + 1 : from;
            for (int step = 0; step < count; step++)
            {
                int i = ((start + step) % count + count) % count;
                string text = texts[i];
                if (text != null && text.StartsWith(wanted, StringComparison.CurrentCultureIgnoreCase)) return i;
            }
            return -1;
        }

        /// Opens its list, with the highlight on the chosen item: the focus ring showing on it when it is
        /// opened from the keyboard. Nothing happens when it is disabled, empty or not on screen.
        internal void OpenList(bool fromKeyboard)
        {
            if (Open || !Enabled || !IsHandleCreated || Items.Count == 0 || !Soft.Shown(this)) return;
            Form form = FindForm();
            if (form == null || !form.IsHandleCreated) return;
            highlight = SelectedIndex >= 0 && SelectedIndex < Items.Count ? SelectedIndex : 0;
            keyboard = fromKeyboard;
            typed = "";
            drop = new SoftDropList(this);
            Watch(form);
            OnDropDown(EventArgs.Empty);
            if (drop == null) return;
            drop.Show();
            Invalidate();
            AccessibilityNotifyClients(AccessibleEvents.StateChange, -1);
            AccessibilityNotifyClients(AccessibleEvents.Show, ListObjectId, -1);
            NotifyItem(highlight);
        }

        /// Closes its list, if it is open, leaving the choice as it is.
        internal void CloseList()
        {
            if (drop == null) return;
            SoftDropList closing = drop;
            drop = null;
            Unwatch();
            closing.Dispose();
            typed = "";
            if (IsHandleCreated)
            {
                AccessibilityNotifyClients(AccessibleEvents.Hide, ListObjectId, -1);
                AccessibilityNotifyClients(AccessibleEvents.StateChange, -1);
                if (Focused) AccessibilityNotifyClients(AccessibleEvents.Focus, -1);
            }
            OnDropDownClosed(EventArgs.Empty);
        }

        /// Moves the highlight to `index`, kept to the list, scrolling it into view, with the focus ring on it.
        internal void MoveHighlight(int index)
        {
            if (drop == null || Items.Count == 0) return;
            index = Math.Max(0, Math.Min(Items.Count - 1, index));
            bool moved = index != highlight;
            highlight = index;
            keyboard = true;
            drop.Reveal(index);
            drop.Render();
            if (moved) NotifyItem(index);
        }

        /// The pointer is over item `index` of the open list (-1: over none): the highlight follows it,
        /// shown by the item rising rather than by the ring.
        internal void Hovered(int index)
        {
            keyboard = false;
            if (index >= 0 && index < Items.Count) highlight = index;
        }

        /// Takes item `index` and closes the list: SelectedIndex, and SelectedIndexChanged, when it is not
        /// the item already chosen.
        internal void Pick(int index)
        {
            CloseList();
            if (index < 0 || index >= Items.Count || index == SelectedIndex) return;
            SelectedIndex = index;
            OnSelectionChangeCommitted(EventArgs.Empty);
            AccessibilityNotifyClients(AccessibleEvents.ValueChange, -1);
        }

        /// Tells screen readers the highlight is on item `index`. A reader of MSAA hears the focus and selection
        /// events for the list's item (ListObjectId), and UI Automation turns the selection event into its own; but
        /// UI Automation takes a focus event only for what has the keyboard focus, and that stays on the drop-down.
        /// So the item's focus is also raised to UI Automation itself, as .NET's own ComboBox raises it for the
        /// item its list's highlight is on - the item as UI Automation's MSAA proxy reads it (SoftDropList.RaiseFocus).
        private void NotifyItem(int index)
        {
            if (!IsHandleCreated || index < 0 || index >= Items.Count) return;
            AccessibilityNotifyClients(AccessibleEvents.Focus, ListObjectId, index);
            AccessibilityNotifyClients(AccessibleEvents.Selection, ListObjectId, index);
            if (drop != null) SoftDropList.RaiseFocus(ListObject, index);
        }

        // What closes the list while it is open: the window losing activation, moving or resizing; the
        // drop-down losing the focus, or it or anything it is in moving, resizing, hiding or going; and a
        // click anywhere but the list and the drop-down (DropFilter).
        private void Watch(Form form)
        {
            watchedForm = form;
            form.Deactivate += closer;
            form.Move += closer;
            form.Resize += closer;
            LostFocus += closer;
            for (Control c = this; c != null && c != form; c = c.Parent)
            {
                c.VisibleChanged += closer;
                c.LocationChanged += closer;
                c.SizeChanged += closer;
                c.EnabledChanged += closer;
                c.ParentChanged += closer;
                watched.Add(c);
            }
            if (filter == null) filter = new DropFilter(this);
            Application.AddMessageFilter(filter);
        }

        private void Unwatch()
        {
            if (filter != null) Application.RemoveMessageFilter(filter);
            if (watchedForm != null)
            {
                watchedForm.Deactivate -= closer;
                watchedForm.Move -= closer;
                watchedForm.Resize -= closer;
                watchedForm = null;
            }
            LostFocus -= closer;
            foreach (Control c in watched)
            {
                c.VisibleChanged -= closer;
                c.LocationChanged -= closer;
                c.SizeChanged -= closer;
                c.EnabledChanged -= closer;
                c.ParentChanged -= closer;
            }
            watched.Clear();
        }

        /// What the thread's message loop sees while the list is open, before any window does: a press of
        /// a mouse button anywhere but the list and the drop-down closes it - and, in a window's client
        /// area, goes no further, as the press that closes Windows' own list does; on a title bar it goes
        /// on, so the window still moves - and a turn of the wheel anywhere scrolls the list, never the page
        /// under it.
        private sealed class DropFilter : IMessageFilter
        {
            private const int WM_NCLBUTTONDOWN = 0x00A1;
            private const int WM_NCRBUTTONDOWN = 0x00A4;
            private const int WM_NCMBUTTONDOWN = 0x00A7;
            private const int WM_NCXBUTTONDOWN = 0x00AB;
            private const int WM_RBUTTONDOWN = 0x0204;
            private const int WM_MBUTTONDOWN = 0x0207;
            private const int WM_XBUTTONDOWN = 0x020B;
            private readonly SoftCombo combo;

            internal DropFilter(SoftCombo combo) { this.combo = combo; }

            public bool PreFilterMessage(ref Message m)
            {
                SoftDropList list = combo.drop;
                if (list == null) return false;
                int message = m.Msg;
                if (message == WM_MOUSEWHEEL)
                {
                    list.Wheel(WheelDelta(m.WParam));
                    return true;
                }
                bool client = message == WM_LBUTTONDOWN || message == WM_RBUTTONDOWN || message == WM_MBUTTONDOWN ||
                              message == WM_XBUTTONDOWN || message == WM_LBUTTONDBLCLK;
                bool frame = message == WM_NCLBUTTONDOWN || message == WM_NCRBUTTONDOWN || message == WM_NCMBUTTONDOWN ||
                             message == WM_NCXBUTTONDOWN;
                if (!client && !frame) return false;
                if (m.HWnd == list.Handle) return false;
                if (client && message == WM_LBUTTONDOWN && combo.IsHandleCreated && m.HWnd == combo.Handle) return false;
                combo.CloseList();
                return client;
            }
        }

        // ------------------------------------------------------------------ what a screen reader hears

        protected override AccessibleObject CreateAccessibilityInstance()
        {
            return new ComboAccessible(this);
        }

        protected override AccessibleObject GetAccessibilityObjectById(int objectId)
        {
            return objectId == ListObjectId ? ListObject : base.GetAccessibilityObjectById(objectId);
        }

        /// Its list's accessible object: the drop-down's one child, whose children are the items.
        internal AccessibleObject ListObject
        {
            get
            {
                if (listObject == null) listObject = new ListAccessible(this);
                return listObject;
            }
        }

        private sealed class ComboAccessible : ControlAccessibleObject
        {
            private readonly SoftCombo combo;

            internal ComboAccessible(SoftCombo owner) : base(owner) { combo = owner; }

            public override AccessibleRole Role
            {
                get { return combo.AccessibleRole != AccessibleRole.Default ? combo.AccessibleRole : AccessibleRole.ComboBox; }
            }

            public override AccessibleStates State
            {
                get
                {
                    AccessibleStates state = base.State & ~(AccessibleStates.Expanded | AccessibleStates.Collapsed);
                    return state | AccessibleStates.HasPopup | (combo.Open ? AccessibleStates.Expanded : AccessibleStates.Collapsed);
                }
            }

            public override string Value
            {
                get { return combo.SelectedIndex >= 0 ? combo.GetItemText(combo.SelectedItem) : ""; }
                set { }
            }

            public override void DoDefaultAction()
            {
                if (combo.Open)
                {
                    combo.CloseList();
                    return;
                }
                if (!combo.Focused) combo.Focus();
                combo.OpenList(true);
            }

            public override int GetChildCount() { return 1; }

            public override AccessibleObject GetChild(int index)
            {
                return index == 0 ? combo.ListObject : null;
            }
        }

        private sealed class ListAccessible : AccessibleObject
        {
            private readonly SoftCombo combo;
            private readonly List<ItemAccessible> items = new List<ItemAccessible>();

            internal ListAccessible(SoftCombo combo) { this.combo = combo; }

            public override AccessibleRole Role { get { return AccessibleRole.List; } }

            public override string Name
            {
                get { return combo.AccessibilityObject.Name; }
                set { }
            }

            public override AccessibleStates State
            {
                get { return combo.Open ? AccessibleStates.None : AccessibleStates.Invisible | AccessibleStates.Offscreen; }
            }

            public override Rectangle Bounds
            {
                get { return combo.drop != null ? combo.drop.CardOnScreen : Rectangle.Empty; }
            }

            public override AccessibleObject Parent { get { return combo.AccessibilityObject; } }

            public override int GetChildCount() { return combo.Items.Count; }

            public override AccessibleObject GetChild(int index)
            {
                if (index < 0 || index >= combo.Items.Count) return null;
                while (items.Count <= index) items.Add(new ItemAccessible(this, combo, items.Count));
                return items[index];
            }

            public override AccessibleObject GetFocused()
            {
                return combo.Open ? GetChild(combo.highlight) : null;
            }

            public override AccessibleObject GetSelected()
            {
                return GetFocused();
            }

            public override AccessibleObject HitTest(int x, int y)
            {
                if (combo.drop == null) return null;
                int index = combo.drop.ItemAtScreen(new Point(x, y));
                if (index >= 0) return GetChild(index);
                return combo.drop.CardOnScreen.Contains(x, y) ? this : null;
            }
        }

        private sealed class ItemAccessible : AccessibleObject
        {
            private readonly ListAccessible list;
            private readonly SoftCombo combo;
            private readonly int index;

            internal ItemAccessible(ListAccessible list, SoftCombo combo, int index)
            {
                this.list = list;
                this.combo = combo;
                this.index = index;
            }

            public override AccessibleRole Role { get { return AccessibleRole.ListItem; } }

            public override string Name
            {
                get { return index < combo.Items.Count ? combo.GetItemText(combo.Items[index]) : ""; }
                set { }
            }

            public override AccessibleStates State
            {
                get
                {
                    AccessibleStates state = AccessibleStates.Selectable | AccessibleStates.Focusable;
                    SoftDropList drop = combo.drop;
                    if (drop == null) return state | AccessibleStates.Invisible | AccessibleStates.Offscreen;
                    if (!drop.Shows(index)) state |= AccessibleStates.Offscreen;
                    if (combo.highlight == index) state |= AccessibleStates.Focused | AccessibleStates.Selected;
                    return state;
                }
            }

            public override Rectangle Bounds
            {
                get { return combo.drop != null ? combo.drop.ItemOnScreen(index) : Rectangle.Empty; }
            }

            public override AccessibleObject Parent { get { return list; } }

            public override void DoDefaultAction()
            {
                combo.Pick(index);
            }

            public override void Select(AccessibleSelection flags)
            {
                if ((flags & (AccessibleSelection.TakeFocus | AccessibleSelection.TakeSelection)) != 0 && combo.Open)
                    combo.MoveHighlight(index);
            }

            public override AccessibleObject Navigate(AccessibleNavigation direction)
            {
                if (direction == AccessibleNavigation.Next || direction == AccessibleNavigation.Down) return list.GetChild(index + 1);
                if (direction == AccessibleNavigation.Previous || direction == AccessibleNavigation.Up) return list.GetChild(index - 1);
                return null;
            }
        }

        // ------------------------------------------------------------------ the closed face

        private void PaintFace(Graphics g)
        {
            Rectangle face = ClientRectangle;
            float radius = Soft.PxF(Brand.RadiusControl);
            Ground.PaintBehind(this, g, face, radius);
            Soft.InsetWell(g, face, radius, Focused && ShowFocusCues);
            string text = SelectedIndex >= 0 ? GetItemText(SelectedItem) : "";
            int left = Soft.Px(Brand.SelectPadLeft), right = Soft.Px(Brand.SelectPadRight);
            TextRenderer.DrawText(g, text, Font, new Rectangle(left, 0, Math.Max(0, face.Width - left - right), face.Height),
                                  Enabled ? Palette.Ink : Palette.Muted,
                                  TextFormatFlags.VerticalCenter | TextFormatFlags.Left | TextFormatFlags.SingleLine |
                                  TextFormatFlags.EndEllipsis | TextFormatFlags.NoPrefix);
            // The chevron: a small wedge in the muted colour, where the panel's select has it.
            float wedge = Soft.PxF(Brand.ChevronWidth), tall = Soft.PxF(Brand.ChevronHeight);
            float right1 = face.Right - Soft.Hairline - Soft.PxF(Brand.ChevronRight), left1 = right1 - wedge;
            float top = face.Top + face.Height * 0.55f - tall / 2f;
            GraphicsState state = g.Save();
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.PixelOffsetMode = PixelOffsetMode.Half;
            using (var brush = new SolidBrush(Enabled ? Palette.Muted : Soft.Mix(Palette.Muted, Palette.Inset, 0.5)))
                g.FillPolygon(brush, new[] { new PointF(left1, top), new PointF(right1, top), new PointF((left1 + right1) / 2f, top + tall) });
            g.Restore(state);
        }

        // Windows draws only the closed face with this now - its own list never opens.
        protected override void OnDrawItem(DrawItemEventArgs e)
        {
            if (e.Index < 0) return;
            bool selected = (e.State & DrawItemState.Selected) != 0;
            bool face = (e.State & DrawItemState.ComboBoxEdit) != 0;
            // The closed face is PaintFace's. Windows draws it by itself as well when the choice
            // changes from the keyboard; that becomes a repaint, not a square over the well.
            if (face)
            {
                Invalidate();
                return;
            }
            bool highlighted = selected && !face;
            Color back = highlighted ? Palette.AccentSoft : Palette.Raised;
            // In High Contrast that ground is Highlight, and the one text colour every contrast
            // theme pairs with Highlight is HighlightText - as the page tabs have it. WindowText
            // on Highlight is under 1.5:1 in Aquatic and Desert.
            Color ink = !Enabled ? Palette.Muted
                      : highlighted && Palette.Contrast ? SystemColors.HighlightText : Palette.Ink;
            using (var brush = new SolidBrush(back)) e.Graphics.FillRectangle(brush, e.Bounds);
            var bounds = new Rectangle(e.Bounds.X + Soft.Px(6), e.Bounds.Y, Math.Max(0, e.Bounds.Width - Soft.Px(8)), e.Bounds.Height);
            TextRenderer.DrawText(e.Graphics, GetItemText(Items[e.Index]), Font, bounds, ink,
                                  TextFormatFlags.VerticalCenter | TextFormatFlags.Left |
                                  TextFormatFlags.SingleLine | TextFormatFlags.EndEllipsis);
        }
    }

    /// The list a SoftCombo opens (v0.6.5): a card of the cards' own material - their ground, their
    /// radius, their hairline and in dark their one-pixel top light - floating just under the drop-down,
    /// lifted by the cards' own shadow (brand.SHADOWS' "card"), which spills outside the card over
    /// whatever is behind it. A child window is clipped to itself, so the list is a top-level window
    /// of its own, layered, with an alpha for every pixel (UpdateLayeredWindow): the card opaque, the
    /// shadow around it translucent, and nothing beyond. It is owned by the drop-down's window, never
    /// activates (WS_EX_NOACTIVATE, MA_NOACTIVATE), and lets a press on its shadow through to what is
    /// under it (HTTRANSPARENT), which closes it like any press outside.
    ///
    /// It opens under the drop-down, `Gap` below it and `Indent` to its left, so its items' words start
    /// exactly under the drop-down's own; above it where the screen has no room below and has room above;
    /// and where neither side has room for every row, on the side with more, as many whole rows as fit
    /// (Place). It shows up to MaxDropDownItems rows and scrolls the rest inside the card on the soft bar.
    /// Every size is the window's scale (Soft.Px) - the scale the drop-down itself is drawn at - and it
    /// keeps to the work area of the monitor the drop-down is on.
    ///
    /// Its items are pills set in the drop-down's font with the field's own padding, SpaceXs apart. The
    /// item chosen now is a sunken pill - a well, with its inset shadow - and its words are the accent;
    /// the item under the pointer rises, a raised pill with the control's lift; the item the keyboard is
    /// on has the focus ring. In High Contrast there is no shadow anywhere, the card is Window with a
    /// WindowFrame edge, the chosen item Highlight with HighlightText, and the item under the pointer
    /// has a Highlight edge.
    ///
    /// It opens with a fade from nothing and a rise of SpaceXs into place over brand's transition, on its
    /// one curve (Motion); with motion reduced it is simply there. It closes at once.
    internal sealed class SoftDropList : NativeWindow, IDisposable
    {
        [StructLayout(LayoutKind.Sequential)]
        private struct NativePoint { public int X, Y; }

        [StructLayout(LayoutKind.Sequential)]
        private struct NativeSize { public int Width, Height; }

        [StructLayout(LayoutKind.Sequential, Pack = 1)]
        private struct Blend { public byte Op, Flags, Alpha, Format; }

        [StructLayout(LayoutKind.Sequential)]
        private struct BitmapHeader
        {
            public int Size, Width, Height;
            public short Planes, BitCount;
            public int Compression, SizeImage, XPerMeter, YPerMeter, Used, Important;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct TrackEvent
        {
            public int Size, Flags;
            public IntPtr Window;
            public int Hover;
        }

        [DllImport("user32.dll")]
        private static extern bool UpdateLayeredWindow(IntPtr window, IntPtr target, ref NativePoint at, ref NativeSize size,
                                                       IntPtr source, ref NativePoint from, int key, ref Blend blend, int flags);

        [DllImport("user32.dll")]
        private static extern IntPtr GetDC(IntPtr window);

        [DllImport("user32.dll")]
        private static extern int ReleaseDC(IntPtr window, IntPtr dc);

        [DllImport("gdi32.dll")]
        private static extern IntPtr CreateCompatibleDC(IntPtr dc);

        [DllImport("gdi32.dll")]
        private static extern bool DeleteDC(IntPtr dc);

        [DllImport("gdi32.dll")]
        private static extern IntPtr SelectObject(IntPtr dc, IntPtr item);

        [DllImport("gdi32.dll")]
        private static extern bool DeleteObject(IntPtr item);

        [DllImport("gdi32.dll")]
        private static extern bool GdiFlush();

        [DllImport("gdi32.dll")]
        private static extern IntPtr CreateDIBSection(IntPtr dc, ref BitmapHeader header, int usage, out IntPtr bits,
                                                      IntPtr section, int offset);

        [DllImport("user32.dll")]
        private static extern bool ShowWindow(IntPtr window, int command);

        [DllImport("user32.dll")]
        private static extern bool TrackMouseEvent(ref TrackEvent track);

        [DllImport("user32.dll")]
        private static extern IntPtr SetCapture(IntPtr window);

        [DllImport("user32.dll")]
        private static extern bool ReleaseCapture();

        [DllImport("oleacc.dll")]
        private static extern IntPtr LresultFromObject(ref Guid iid, IntPtr wParam, IntPtr unknown);

        /// IID_IAccessible, as oleacc.h defines it. Built from its fields rather than written as a string: the
        /// repository holds no GUID-shaped text but made-up ones (tests/test_repo_hygiene.py).
        private static readonly Guid IAccessibleId = new Guid(0x618736e0, 0x3c3d, 0x11cf, 0x81, 0x0c, 0x00, 0xaa, 0x00, 0x38, 0x9b, 0x71);

        [DllImport("uiautomationcore.dll")]
        private static extern bool UiaClientsAreListening();

        [DllImport("uiautomationcore.dll")]
        private static extern int UiaProviderFromIAccessible(IntPtr accessible, int child, int flags, out IntPtr provider);

        [DllImport("uiautomationcore.dll")]
        private static extern int UiaRaiseAutomationEvent(IntPtr provider, int eventId);

        private const int UIA_AutomationFocusChangedEventId = 20005;

        /// `accessible` as the IAccessible a screen reader is handed - a reference the caller releases - or zero.
        private static IntPtr AccessibleInterface(AccessibleObject accessible)
        {
            Type type = Type.GetType("Accessibility.IAccessible, Accessibility, Version=4.0.0.0, Culture=neutral, PublicKeyToken=b03f5f7f11d50a3a", false);
            return type == null ? IntPtr.Zero : Marshal.GetComInterfaceForObject(accessible, type);
        }

        /// Raises UI Automation's focus-changed event for item `index` of `list` (SoftCombo.NotifyItem), when a UI
        /// Automation client is listening: the item as UI Automation's MSAA proxy reads it (UiaProviderFromIAccessible),
        /// a list item with its name. Nothing else changes, and a failure is only an event not heard.
        internal static void RaiseFocus(AccessibleObject list, int index)
        {
            try
            {
                if (!UiaClientsAreListening()) return;
                IntPtr unknown = AccessibleInterface(list);
                if (unknown == IntPtr.Zero) return;
                IntPtr provider = IntPtr.Zero;
                try
                {
                    if (UiaProviderFromIAccessible(unknown, index + 1, 0, out provider) == 0 && provider != IntPtr.Zero)
                        UiaRaiseAutomationEvent(provider, UIA_AutomationFocusChangedEventId);
                }
                finally
                {
                    if (provider != IntPtr.Zero) Marshal.Release(provider);
                    Marshal.Release(unknown);
                }
            }
            catch (Exception) { }
        }

        internal const int WS_EX_LAYERED = 0x00080000;
        internal const int WS_EX_TOOLWINDOW = 0x00000080;
        internal const int WS_EX_NOACTIVATE = 0x08000000;
        internal const int MA_NOACTIVATE = 3;
        private const int WS_POPUP = unchecked((int)0x80000000);
        private const int SW_SHOWNOACTIVATE = 4;
        private const int ULW_ALPHA = 2;
        private const int WM_SETCURSOR = 0x0020;
        private const int WM_MOUSEACTIVATE = 0x0021;
        private const int WM_GETOBJECT = 0x003D;
        private const int WM_NCHITTEST = 0x0084;
        private const int WM_MOUSEMOVE = 0x0200;
        private const int WM_LBUTTONDOWN = 0x0201;
        private const int WM_LBUTTONUP = 0x0202;
        private const int WM_LBUTTONDBLCLK = 0x0203;
        private const int WM_MOUSEWHEEL = 0x020A;
        private const int WM_CAPTURECHANGED = 0x0215;
        private const int WM_MOUSELEAVE = 0x02A3;
        private const int HTCLIENT = 1;
        private const int HTTRANSPARENT = -1;
        private const int OBJID_CLIENT = -4;
        private const int TME_LEAVE = 0x00000002;

        private const TextFormatFlags Flags = TextFormatFlags.VerticalCenter | TextFormatFlags.Left | TextFormatFlags.SingleLine |
                                              TextFormatFlags.EndEllipsis | TextFormatFlags.NoPrefix;

        /// The screen area a list keeps to, in place of its monitor's work area - for the tests and the
        /// captures, which open lists in windows nobody sees. Empty: the monitor's.
        internal static Rectangle Area = Rectangle.Empty;

        private readonly SoftCombo combo;
        private readonly Timer timer = new Timer();
        private readonly System.Diagnostics.Stopwatch clock = new System.Diagnostics.Stopwatch();
        private Rectangle card;
        private Padding margin;
        private bool above, scrolls, tracking, dragging;
        private int pad, pill, rowGap, rows, offset, extent, grab, hover = -1, alpha = 255, rise;
        private Point pointer;
        private Bitmap image;
        private IntPtr memory, dib, previous;

        internal SoftDropList(SoftCombo combo)
        {
            this.combo = combo;
            timer.Interval = Motion.Interval;
            timer.Tick += delegate { Tick(); };
        }

        /// The card, on the screen, where it settles.
        internal Rectangle Card { get { return card; } }

        /// The card on the screen where it is now: lower by what is left of its rise while it appears.
        internal Rectangle CardOnScreen { get { return new Rectangle(card.X, card.Y + rise, card.Width, card.Height); } }

        /// The room its window keeps around the card for the shadow: none in High Contrast.
        internal Padding Margin { get { return margin; } }

        /// Whether it opened above the drop-down.
        internal bool Above { get { return above; } }

        /// Whether it holds more rows than it shows, and scrolls them on the soft bar.
        internal bool Scrolls { get { return scrolls; } }

        /// How many whole rows it shows.
        internal int Rows { get { return rows; } }

        /// How far its rows are scrolled, in pixels.
        internal int Offset { get { return offset; } }

        /// The item under the pointer, or -1.
        internal int Hover { get { return hover; } }

        /// Its opacity now, 0 to 255: under 255 only while it fades in.
        internal int Alpha { get { return alpha; } }

        /// Whether it is still fading in and rising; its timer runs only then.
        internal bool Appearing { get { return timer.Enabled; } }

        /// What was last drawn: the card and its shadow, premultiplied, the size of its window.
        internal Bitmap Image { get { return image; } }

        /// A row: an item's pill and the gap under it.
        internal int Pitch { get { return pill + rowGap; } }

        /// How tall a card of `rows` rows is.
        internal static int CardHeight(int rows, int pill, int rowGap, int pad)
        {
            return 2 * pad + rows * pill + Math.Max(0, rows - 1) * rowGap;
        }

        /// Where the card goes for a drop-down at `field` on the screen, `width` wide with `wanted` rows
        /// of `pill` and `rowGap` inside `pad`: `pad` left of the field, so its items' words start under the
        /// field's, and `gap` below it - or above it where `area` has no room below and has room above.
        /// Where neither side has room for every row it goes on the side with more, as many whole rows as fit
        /// there and never fewer than one (`rows`). Across, it is kept inside `area`.
        internal static Rectangle Place(Rectangle field, int width, int wanted, int pill, int rowGap, int pad,
                                        Rectangle area, int gap, out bool above, out int rows)
        {
            width = Math.Max(0, Math.Min(width, area.Width));
            int x = Math.Max(area.Left, Math.Min(area.Right - width, field.X - pad));
            int below = area.Bottom - (field.Bottom + gap), over = field.Top - gap - area.Top;
            rows = Math.Max(1, wanted);
            int height = CardHeight(rows, pill, rowGap, pad);
            above = false;
            if (height > below)
            {
                if (height <= over) above = true;
                else
                {
                    above = over > below;
                    int room = above ? over : below;
                    rows = Math.Max(1, Math.Min(rows, (room - 2 * pad + rowGap) / Math.Max(1, pill + rowGap)));
                    height = CardHeight(rows, pill, rowGap, pad);
                }
            }
            return new Rectangle(x, above ? field.Top - gap - height : field.Bottom + gap, width, height);
        }

        private void Measure()
        {
            Rectangle field = combo.RectangleToScreen(combo.ClientRectangle);
            Rectangle area = Area.IsEmpty ? Screen.FromRectangle(field).WorkingArea : Area;
            Font font = combo.Font;
            pad = Soft.Px(Brand.SpaceS);
            rowGap = Soft.Px(Brand.SpaceXs);
            var unbounded = new Size(int.MaxValue, int.MaxValue);
            pill = TextRenderer.MeasureText("Ag", font, unbounded, Flags).Height + 2 * Soft.Px(Brand.SpaceS);
            int widest = 0, count = combo.Items.Count;
            for (int i = 0; i < count; i++)
                widest = Math.Max(widest, TextRenderer.MeasureText(combo.GetItemText(combo.Items[i]) ?? "", font, unbounded, Flags).Width);
            extent = count * pill + Math.Max(0, count - 1) * rowGap;
            int wanted = Math.Max(1, Math.Min(count, combo.MaxDropDownItems));
            int words = widest + 2 * Soft.Px(Brand.SelectPadLeft);
            int width = Math.Max(field.Width, words) + 2 * pad;
            card = Place(field, width, wanted, pill, rowGap, pad, area, Soft.Px(Brand.SpaceXs), out above, out rows);
            scrolls = rows < count;
            if (scrolls)
            {
                // Room for the soft bar beside the items, which keep the width their words need.
                width = Math.Max(field.Width, words + SoftBar.Gutter) + 2 * pad;
                card = Place(field, width, wanted, pill, rowGap, pad, area, Soft.Px(Brand.SpaceXs), out above, out rows);
            }
            margin = Palette.Contrast ? Padding.Empty : Elevation.Reach("card");
            offset = 0;
            pointer = Cursor.Position;
        }

        /// Opens it: measured, placed, drawn, shown without taking activation, and - unless motion is
        /// reduced - fading in and rising into place.
        internal void Show()
        {
            Measure();
            bool animate = Motion.Allowed(combo);
            alpha = animate ? 0 : 255;
            rise = animate ? Soft.Px(Brand.SpaceXs) : 0;
            var cp = new CreateParams();
            cp.Caption = "";
            cp.X = card.X - margin.Left;
            cp.Y = card.Y - margin.Top + rise;
            cp.Width = card.Width + margin.Horizontal;
            cp.Height = card.Height + margin.Vertical;
            cp.Style = WS_POPUP;
            cp.ExStyle = WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE;
            Form form = combo.FindForm();
            if (form != null && form.IsHandleCreated) cp.Parent = form.Handle;
            CreateHandle(cp);
            Reveal(combo.Highlight);
            Render();
            ShowWindow(Handle, SW_SHOWNOACTIVATE);
            if (!animate) return;
            clock.Reset();
            clock.Start();
            timer.Start();
        }

        private void Tick()
        {
            double t = clock.Elapsed.TotalMilliseconds / Math.Max(1, Motion.Duration);
            double eased = Motion.Ease(t);
            alpha = t >= 1.0 ? 255 : (int)Math.Round(255 * eased);
            rise = t >= 1.0 ? 0 : (int)Math.Round(Soft.Px(Brand.SpaceXs) * (1.0 - eased));
            if (t >= 1.0) timer.Stop();
            Push();
        }

        // ------------------------------------------------------------------ geometry, in the card's coordinates

        private int Viewport { get { return Math.Max(1, card.Height - 2 * pad); } }

        private Rectangle TrackRect
        {
            get
            {
                int width = Soft.Px(SoftBar.TrackWidth);
                return new Rectangle(card.Width - Soft.Hairline - Soft.Px(SoftBar.TrackMargin) - width, pad, width, Viewport);
            }
        }

        private Rectangle ThumbRect
        {
            get
            {
                Rectangle track = TrackRect;
                int inset = Soft.Px(SoftBar.ThumbInset), start, length;
                SoftBar.Thumb(track.Height - 2 * inset, extent, Viewport, offset, Soft.Px(SoftBar.MinThumb), out start, out length);
                return new Rectangle(track.X + inset, track.Y + inset + start, Math.Max(0, track.Width - 2 * inset), length);
            }
        }

        /// Item `index`'s pill, in the card's coordinates, where it is scrolled to.
        internal Rectangle PillRect(int index)
        {
            int right = scrolls ? TrackRect.X - Soft.Px(Brand.SpaceXs) : card.Width - pad;
            return new Rectangle(pad, pad + index * (pill + rowGap) - offset, Math.Max(0, right - pad), pill);
        }

        /// The item at `local`, a point in the card's coordinates, or -1. The gap under a pill is its item's.
        internal int ItemAt(Point local)
        {
            int count = combo.Items.Count;
            Rectangle column = PillRect(0);
            if (count == 0 || local.X < column.Left || local.X >= column.Right) return -1;
            if (local.Y < pad || local.Y >= card.Height - pad) return -1;
            int along = local.Y - pad + offset;
            int index = along / Math.Max(1, pill + rowGap);
            return along < 0 || index >= count ? -1 : index;
        }

        internal int ItemAtScreen(Point screen)
        {
            Rectangle now = CardOnScreen;
            return ItemAt(new Point(screen.X - now.X, screen.Y - now.Y));
        }

        /// Item `index`'s pill on the screen, as much of it as shows; empty when none does.
        internal Rectangle ItemOnScreen(int index)
        {
            Rectangle shown = Rectangle.Intersect(PillRect(index), new Rectangle(0, pad, card.Width, Viewport));
            if (shown.IsEmpty) return Rectangle.Empty;
            Rectangle now = CardOnScreen;
            shown.Offset(now.X, now.Y);
            return shown;
        }

        internal bool Shows(int index)
        {
            return !ItemOnScreen(index).IsEmpty;
        }

        /// Scrolls just far enough that item `index` shows whole. Drawn by whoever asked.
        internal void Reveal(int index)
        {
            if (!scrolls || index < 0) return;
            int top = index * (pill + rowGap);
            offset = SoftBar.IntoView(offset, top, top + pill, Viewport, 0, extent);
        }

        /// Scrolls by one turn of the wheel, `delta` as Windows reports it.
        internal void Wheel(int delta)
        {
            if (!scrolls) return;
            int step = SoftBar.WheelStep(delta, SystemInformation.MouseWheelScrollLines, pill + rowGap, Viewport);
            if (ScrollTo(offset + step)) Render();
        }

        private bool ScrollTo(int target)
        {
            target = Math.Max(0, Math.Min(Math.Max(0, extent - Viewport), target));
            if (target == offset) return false;
            offset = target;
            return true;
        }

        // ------------------------------------------------------------------ drawing

        /// Draws the card and its shadow again, and puts them on the screen.
        internal void Render()
        {
            if (card.Width <= 0 || card.Height <= 0) return;
            var size = new Size(card.Width + margin.Horizontal, card.Height + margin.Vertical);
            var next = new Bitmap(size.Width, size.Height, PixelFormat.Format32bppPArgb);
            var body = new Rectangle(margin.Left, margin.Top, card.Width, card.Height);
            float radius = Soft.PxF(Brand.RadiusCard);
            using (Graphics g = Graphics.FromImage(next))
            {
                g.Clear(Color.Transparent);
                Elevation.StampOuter(g, body, "card", radius, new Rectangle(Point.Empty, size));
            }
            Lay(next, body, radius);
            using (Graphics g = Graphics.FromImage(next))
            {
                int hairline = Soft.Hairline;
                // In dark, the card's one-pixel top light; then its hairline.
                Elevation.StampInner(g, Rectangle.Inflate(body, -hairline, -hairline), "card", radius - hairline, body);
                Soft.Edge(g, body, radius, Palette.Line, hairline);
            }
            if (image != null) image.Dispose();
            image = next;
            Upload();
            Push();
        }

        // The card's face is drawn opaque into a bitmap of Windows' own (Face), where its words are drawn as
        // the window draws them - drawn on a GDI+ bitmap they came out heavier, without ClearType - and laid
        // into the rounded card pixel for pixel: whole inside the rounded edge, and over the shadow in
        // proportion to how much of each edge pixel the card covers.
        private void Lay(Bitmap target, Rectangle body, float radius)
        {
            int[] face = Face(body.Width, body.Height);
            using (var mask = new Bitmap(body.Width, body.Height, PixelFormat.Format32bppPArgb))
            {
                using (Graphics m = Graphics.FromImage(mask))
                {
                    m.Clear(Color.Transparent);
                    m.SmoothingMode = SmoothingMode.AntiAlias;
                    m.PixelOffsetMode = PixelOffsetMode.Half;
                    using (GraphicsPath path = Soft.Rounded(new Rectangle(0, 0, body.Width, body.Height), radius))
                    using (var brush = new SolidBrush(Palette.Card))
                        m.FillPath(brush, path);
                }
                var whole = new Rectangle(0, 0, body.Width, body.Height);
                BitmapData maskData = mask.LockBits(whole, ImageLockMode.ReadOnly, PixelFormat.Format32bppPArgb);
                BitmapData targetData = target.LockBits(body, ImageLockMode.ReadWrite, PixelFormat.Format32bppPArgb);
                try
                {
                    var maskRow = new int[body.Width];
                    var row = new int[body.Width];
                    for (int y = 0; y < body.Height; y++)
                    {
                        Marshal.Copy(new IntPtr(maskData.Scan0.ToInt64() + (long)y * maskData.Stride), maskRow, 0, body.Width);
                        IntPtr at = new IntPtr(targetData.Scan0.ToInt64() + (long)y * targetData.Stride);
                        Marshal.Copy(at, row, 0, body.Width);
                        for (int x = 0; x < body.Width; x++)
                        {
                            int cover = (maskRow[x] >> 24) & 255;
                            if (cover == 0) continue;
                            int over = face[y * body.Width + x];
                            if (cover == 255)
                            {
                                row[x] = over | unchecked((int)0xFF000000);
                                continue;
                            }
                            int under = row[x], rest = 255 - cover;
                            int a = cover + (((under >> 24) & 255) * rest + 127) / 255;
                            int r = (((over >> 16) & 255) * cover + ((under >> 16) & 255) * rest + 127) / 255;
                            int gr = (((over >> 8) & 255) * cover + ((under >> 8) & 255) * rest + 127) / 255;
                            int b = ((over & 255) * cover + (under & 255) * rest + 127) / 255;
                            row[x] = (a << 24) | (r << 16) | (gr << 8) | b;
                        }
                        Marshal.Copy(row, 0, at, body.Width);
                    }
                }
                finally
                {
                    target.UnlockBits(targetData);
                    mask.UnlockBits(maskData);
                }
            }
        }

        // The card's face, `width` by `height`, as opaque RGB, drawn into a device-independent bitmap of
        // Windows' own.
        private int[] Face(int width, int height)
        {
            var pixels = new int[width * height];
            var header = new BitmapHeader();
            header.Size = Marshal.SizeOf(typeof(BitmapHeader));
            header.Width = width;
            header.Height = -height;
            header.Planes = 1;
            header.BitCount = 24;
            IntPtr screen = GetDC(IntPtr.Zero);
            IntPtr bits, bitmap = IntPtr.Zero, dc = IntPtr.Zero, old = IntPtr.Zero;
            try
            {
                bitmap = CreateDIBSection(screen, ref header, 0, out bits, IntPtr.Zero, 0);
                if (bitmap == IntPtr.Zero || bits == IntPtr.Zero) return pixels;
                dc = CreateCompatibleDC(screen);
                old = SelectObject(dc, bitmap);
                using (Graphics f = Graphics.FromHdc(dc)) PaintFace(f);
                GdiFlush();
                int stride = (width * 3 + 3) & ~3;
                var row = new byte[stride];
                for (int y = 0; y < height; y++)
                {
                    Marshal.Copy(new IntPtr(bits.ToInt64() + (long)y * stride), row, 0, stride);
                    for (int x = 0; x < width; x++)
                        pixels[y * width + x] = (row[x * 3 + 2] << 16) | (row[x * 3 + 1] << 8) | row[x * 3];
                }
            }
            finally
            {
                if (dc != IntPtr.Zero)
                {
                    SelectObject(dc, old);
                    DeleteDC(dc);
                }
                if (bitmap != IntPtr.Zero) DeleteObject(bitmap);
                ReleaseDC(IntPtr.Zero, screen);
            }
            return pixels;
        }

        private void PaintFace(Graphics f)
        {
            var whole = new Rectangle(0, 0, card.Width, card.Height);
            using (var brush = new SolidBrush(Palette.Card)) f.FillRectangle(brush, whole);
            int count = combo.Items.Count, chosen = combo.SelectedIndex, highlight = combo.Highlight;
            bool cues = combo.KeyboardCues;
            float radius = Soft.PxF(Brand.RadiusSmall);
            int words = Soft.Px(Brand.SelectPadLeft);
            for (int i = 0; i < count; i++)
            {
                Rectangle item = PillRect(i);
                if (item.Bottom < 0 || item.Top > card.Height) continue;
                Color ink = Palette.Ink;
                if (i == chosen)
                {
                    if (Palette.Contrast)
                    {
                        Soft.Body(f, item, radius, SystemColors.Highlight, SystemColors.Highlight, null);
                        ink = SystemColors.HighlightText;
                    }
                    else
                    {
                        Soft.Body(f, item, radius, Palette.Inset, Palette.Line, "inset");
                        ink = Palette.Accent;
                    }
                }
                else if (i == hover && !cues)
                {
                    if (Palette.Contrast) Soft.Edge(f, item, radius, SystemColors.Highlight, Soft.Hairline);
                    else
                    {
                        Elevation.StampOuter(f, item, "control", radius, whole);
                        Soft.Body(f, item, radius, Palette.Raised, Palette.Line, null);
                    }
                }
                var text = new Rectangle(item.X + words, item.Y, Math.Max(0, item.Width - 2 * words), item.Height);
                TextRenderer.DrawText(f, combo.GetItemText(combo.Items[i]), combo.Font, text, ink, Flags);
            }
            if (scrolls)
            {
                // What scrolls stops at the card's padding, as a list's rows stop at its edge.
                using (var brush = new SolidBrush(Palette.Card))
                {
                    f.FillRectangle(brush, 0, 0, card.Width, pad);
                    f.FillRectangle(brush, 0, card.Height - pad, card.Width, pad);
                }
            }
            if (cues && highlight >= 0 && highlight < count) Soft.Ring(f, PillRect(highlight), radius);
            // The list is its own window, drawn here rather than by a parent: its ground is the card it
            // just filled, which is what the track's colour is chosen against.
            if (scrolls) SoftBar.Draw(f, TrackRect, ThumbRect, dragging ? 2 : 0, Palette.Card);
        }

        // Copies what was drawn into a bitmap Windows can lay on the screen: premultiplied, top down.
        private void Upload()
        {
            Release();
            int width = image.Width, height = image.Height;
            var header = new BitmapHeader();
            header.Size = Marshal.SizeOf(typeof(BitmapHeader));
            header.Width = width;
            header.Height = -height;
            header.Planes = 1;
            header.BitCount = 32;
            IntPtr screen = GetDC(IntPtr.Zero);
            try
            {
                IntPtr bits;
                dib = CreateDIBSection(screen, ref header, 0, out bits, IntPtr.Zero, 0);
                if (dib == IntPtr.Zero || bits == IntPtr.Zero) return;
                BitmapData data = image.LockBits(new Rectangle(0, 0, width, height), ImageLockMode.ReadOnly, PixelFormat.Format32bppPArgb);
                try
                {
                    var row = new byte[width * 4];
                    for (int y = 0; y < height; y++)
                    {
                        Marshal.Copy(new IntPtr(data.Scan0.ToInt64() + (long)y * data.Stride), row, 0, row.Length);
                        Marshal.Copy(row, 0, new IntPtr(bits.ToInt64() + (long)y * width * 4), row.Length);
                    }
                }
                finally { image.UnlockBits(data); }
                memory = CreateCompatibleDC(screen);
                previous = SelectObject(memory, dib);
            }
            finally { ReleaseDC(IntPtr.Zero, screen); }
        }

        private void Push()
        {
            if (Handle == IntPtr.Zero || memory == IntPtr.Zero || image == null) return;
            var at = new NativePoint();
            at.X = card.X - margin.Left;
            at.Y = card.Y - margin.Top + rise;
            var size = new NativeSize();
            size.Width = image.Width;
            size.Height = image.Height;
            var from = new NativePoint();
            var blend = new Blend();
            blend.Alpha = (byte)Math.Max(0, Math.Min(255, alpha));
            blend.Format = 1;   // AC_SRC_ALPHA: every pixel's own alpha, premultiplied
            UpdateLayeredWindow(Handle, IntPtr.Zero, ref at, ref size, memory, ref from, 0, ref blend, ULW_ALPHA);
        }

        private void Release()
        {
            if (memory != IntPtr.Zero)
            {
                SelectObject(memory, previous);
                DeleteDC(memory);
                memory = IntPtr.Zero;
            }
            if (dib != IntPtr.Zero)
            {
                DeleteObject(dib);
                dib = IntPtr.Zero;
            }
        }

        // ------------------------------------------------------------------ the pointer

        protected override void WndProc(ref Message m)
        {
            int message = m.Msg;
            if (message == WM_MOUSEACTIVATE)
            {
                m.Result = (IntPtr)MA_NOACTIVATE;
                return;
            }
            if (message == WM_NCHITTEST)
            {
                m.Result = (IntPtr)(CardOnScreen.Contains(ScreenPoint(m.LParam)) ? HTCLIENT : HTTRANSPARENT);
                return;
            }
            if (message == WM_SETCURSOR)
            {
                Cursor.Current = Cursors.Default;
                m.Result = (IntPtr)1;
                return;
            }
            if (message == WM_MOUSEMOVE)
            {
                Moved(ClientPoint(m.LParam));
                return;
            }
            if (message == WM_MOUSELEAVE)
            {
                tracking = false;
                if (!dragging && hover >= 0)
                {
                    hover = -1;
                    Render();
                }
                return;
            }
            if (message == WM_LBUTTONDOWN || message == WM_LBUTTONDBLCLK)
            {
                Pressed(ClientPoint(m.LParam));
                return;
            }
            if (message == WM_LBUTTONUP)
            {
                Released(ClientPoint(m.LParam));
                return;
            }
            if (message == WM_MOUSEWHEEL)
            {
                Wheel(SoftCombo.WheelDelta(m.WParam));
                m.Result = IntPtr.Zero;
                return;
            }
            if (message == WM_CAPTURECHANGED) dragging = false;
            if (message == WM_GETOBJECT && Accessible(ref m)) return;
            base.WndProc(ref m);
        }

        private static Point ScreenPoint(IntPtr lParam)
        {
            long value = lParam.ToInt64();
            return new Point(unchecked((short)(value & 0xFFFF)), unchecked((short)((value >> 16) & 0xFFFF)));
        }

        // A point in the window, in the card's coordinates.
        private Point ClientPoint(IntPtr lParam)
        {
            Point point = ScreenPoint(lParam);
            return new Point(point.X - margin.Left, point.Y - margin.Top);
        }

        private void Moved(Point local)
        {
            if (!tracking)
            {
                var track = new TrackEvent();
                track.Size = Marshal.SizeOf(typeof(TrackEvent));
                track.Flags = TME_LEAVE;
                track.Window = Handle;
                tracking = TrackMouseEvent(ref track);
            }
            if (dragging)
            {
                Rectangle track = TrackRect, thumb = ThumbRect;
                int inset = Soft.Px(SoftBar.ThumbInset);
                if (ScrollTo(SoftBar.OffsetAt(track.Height - 2 * inset, extent, Viewport, thumb.Height, local.Y - grab - track.Y - inset)))
                    Render();
                return;
            }
            // Windows moves the pointer's message on when a window appears or scrolls under a pointer that
            // is standing still; only a pointer that moved takes the highlight from the keyboard.
            Point now = Cursor.Position;
            if (now == pointer && combo.KeyboardCues) return;
            pointer = now;
            SetHover(ItemAt(local));
        }

        private void SetHover(int index)
        {
            if (index == hover && !combo.KeyboardCues) return;
            hover = index;
            if (index >= 0 || combo.KeyboardCues) combo.Hovered(index);
            Render();
        }

        private void Pressed(Point local)
        {
            if (!scrolls) return;
            Rectangle track = TrackRect;
            int slack = Soft.Px(SoftBar.TrackMargin);
            if (!Rectangle.Inflate(track, slack, 0).Contains(local)) return;
            Rectangle thumb = ThumbRect;
            if (local.Y >= thumb.Top && local.Y < thumb.Bottom)
            {
                dragging = true;
                grab = local.Y - thumb.Top;
                SetCapture(Handle);
                Render();
                return;
            }
            int page = SoftBar.PageStep(Viewport, pill + rowGap);
            if (ScrollTo(offset + (local.Y < thumb.Top ? -page : page))) Render();
        }

        private void Released(Point local)
        {
            if (dragging)
            {
                dragging = false;
                ReleaseCapture();
                Render();
                return;
            }
            int index = ItemAt(local);
            if (index >= 0) combo.Pick(index);
        }

        // A screen reader asking the list's own window what it is gets the list, as asking the drop-down's does.
        private bool Accessible(ref Message m)
        {
            if (unchecked((int)m.LParam.ToInt64()) != OBJID_CLIENT) return false;
            try
            {
                IntPtr unknown = AccessibleInterface(combo.ListObject);
                if (unknown == IntPtr.Zero) return false;
                try
                {
                    Guid iid = IAccessibleId;
                    m.Result = LresultFromObject(ref iid, m.WParam, unknown);
                }
                finally { Marshal.Release(unknown); }
                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }

        public void Dispose()
        {
            timer.Stop();
            timer.Dispose();
            if (dragging) ReleaseCapture();
            dragging = false;
            if (Handle != IntPtr.Zero) DestroyHandle();
            Release();
            if (image != null)
            {
                image.Dispose();
                image = null;
            }
        }
    }

    /// A number in a well, as the panel's number field is: a NumericUpDown without a border of
    /// its own, sitting in the inset well, with its spin buttons redrawn as two small wedges.
    /// `Spin` is the real control - typing, the arrows, the keyboard and screen readers are all
    /// its own - and the one the settings are read from.
    internal sealed class SoftNumber : Panel
    {
        internal readonly NumericUpDown Spin = new NumericUpDown();
        private SpinPainter painter;
        private bool hooked;

        internal SoftNumber()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                     ControlStyles.UserPaint | ControlStyles.ResizeRedraw, true);
            BackColor = Palette.Inset;
            Spin.BorderStyle = BorderStyle.None;
            Spin.BackColor = Palette.Inset;
            Spin.ForeColor = Palette.Ink;
            Spin.Enter += delegate { Invalidate(); };
            Spin.Leave += delegate { Invalidate(); };
            Spin.HandleCreated += delegate { Hook(); };
            Controls.Add(Spin);
            Size = new Size(Soft.Px(Brand.NumberWidth), SoftCombo.FieldHeight);
        }

        // The spin buttons get their window after the NumericUpDown does, so they are hooked
        // when theirs exists - and again if it is ever made anew.
        private void Hook()
        {
            if (hooked) return;
            foreach (Control child in Spin.Controls)
            {
                if (child is TextBox) continue;
                Control buttons = child;
                hooked = true;
                buttons.HandleCreated += delegate { painter = new SpinPainter(buttons); };
                if (buttons.IsHandleCreated) painter = new SpinPainter(buttons);
            }
        }

        public override Size GetPreferredSize(Size proposedSize)
        {
            return new Size(Math.Max(Soft.Px(Brand.NumberWidth), Width),
                            Math.Max(SoftCombo.FieldHeight, Spin.PreferredHeight + Soft.Px(4)));
        }

        protected override void OnLayout(LayoutEventArgs levent)
        {
            base.OnLayout(levent);
            int left = Soft.Px(8), right = Soft.Px(4);
            Spin.SetBounds(left, Math.Max(0, (Height - Spin.Height) / 2), Math.Max(0, Width - left - right), Spin.Height);
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            float radius = Soft.PxF(Brand.RadiusControl);
            Ground.PaintBehind(this, e.Graphics, ClientRectangle, radius);
            Soft.InsetWell(e.Graphics, ClientRectangle, radius, Spin.ContainsFocus);
        }

        /// Draws the spin buttons as two muted wedges on the well in place of the grey
        /// scroll-bar buttons. Only painting is taken over; clicks, holds and the keyboard go on
        /// to the control underneath.
        private sealed class SpinPainter : NativeWindow
        {
            private readonly Control buttons;

            internal SpinPainter(Control buttons)
            {
                this.buttons = buttons;
                AssignHandle(buttons.Handle);
            }

            protected override void WndProc(ref Message m)
            {
                if (NativePaint.Handle(ref m, buttons.ClientSize, Draw)) return;
                base.WndProc(ref m);
            }

            private void Draw(Graphics g)
            {
                Size size = buttons.ClientSize;
                using (var brush = new SolidBrush(Palette.Inset)) g.FillRectangle(brush, 0, 0, size.Width, size.Height);
                float wedge = Math.Max(2f, Math.Min(Soft.PxF(7), size.Width - Soft.PxF(4))), tall = wedge / 2f;
                float centre = size.Width / 2f, half = size.Height / 2f;
                float up = half / 2f + Soft.PxF(1), down = half + half / 2f - Soft.PxF(1);
                GraphicsState state = g.Save();
                g.SmoothingMode = SmoothingMode.AntiAlias;
                g.PixelOffsetMode = PixelOffsetMode.Half;
                using (var brush = new SolidBrush(buttons.Enabled ? Palette.Muted : Soft.Mix(Palette.Muted, Palette.Inset, 0.5)))
                {
                    g.FillPolygon(brush, new[] { new PointF(centre - wedge / 2f, up + tall / 2f), new PointF(centre + wedge / 2f, up + tall / 2f),
                                                 new PointF(centre, up - tall / 2f) });
                    g.FillPolygon(brush, new[] { new PointF(centre - wedge / 2f, down - tall / 2f), new PointF(centre + wedge / 2f, down - tall / 2f),
                                                 new PointF(centre, down + tall / 2f) });
                }
                g.Restore(state);
            }
        }
    }

    /// One choice among several, drawn as a small card with its explanation under it. Resting,
    /// it is raised like a button; chosen, it sinks into a well with an accent edge and title, as
    /// the panel's chosen segment does.
    internal sealed class ChoiceCard : RadioButton, ISoftLifted
    {
        internal string Value;
        internal string Help = "";
        private bool hover;
        private Font titleFont, titleFrom;
        private readonly LiftTracker tracker;

        internal ChoiceCard(string value, string title, string help)
        {
            Value = value;
            Text = title;
            Help = help ?? "";
            AccessibleDescription = Help;
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint |
                     ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
            AutoSize = false;
            Cursor = Cursors.Hand;
            tracker = new LiftTracker(this, "control");
        }

        /// The title's font: 600, chosen or not, so a card keeps its height when it is picked.
        private Font TitleFont
        {
            get
            {
                if (titleFont == null || titleFrom != Font)
                {
                    if (titleFont != null) titleFont.Dispose();
                    titleFont = Soft.Weighted(Font, Font.SizeInPoints, 600);
                    titleFrom = Font;
                }
                return titleFont;
            }
        }

        string ISoftLifted.Lift { get { return Checked ? null : "control"; } }
        float ISoftLifted.Radius { get { return Soft.PxF(Brand.RadiusControl); } }
        Rectangle ISoftLifted.Face { get { return ClientRectangle; } }
        bool ISoftLifted.Ring { get { return Focused && ShowFocusCues; } }

        private static RectangleF Body(int width, int height)
        {
            return new RectangleF(0f, 0f, width, height);
        }

        /// The column the title and help are set in, on a card this wide: from past the radio
        /// mark to the padding on the right. HeightFor measures in it and OnPaint draws in it.
        /// Each used to work it out for itself, five pixels apart, and a help line that wrapped
        /// only when it was drawn ran off the bottom of the card.
        private static Rectangle TextColumn(int width)
        {
            RectangleF body = Body(width, 0);
            int left = (int)(body.X + Soft.PxF(40));
            return new Rectangle(left, 0, Math.Max(Soft.Px(80), (int)body.Right - left - Soft.Px(12)), 0);
        }

        // The title and the help wrap in the text column, Korean between its words (Soft.Wrap).
        private const TextFormatFlags Words = TextFormatFlags.WordBreak | TextFormatFlags.Left;

        internal int HeightFor(int width)
        {
            int textWidth = TextColumn(width).Width;
            Font title = TitleFont;
            int top = TextRenderer.MeasureText(Soft.Wrap(Text ?? "", title, textWidth, Words), title, new Size(textWidth, int.MaxValue),
                                               Words).Height;
            int help = string.IsNullOrEmpty(Help) ? 0
                     : TextRenderer.MeasureText(Soft.Wrap(Help, Font, textWidth, Words), Font, new Size(textWidth, int.MaxValue),
                                                Words).Height + Soft.Px(2);
            return Soft.Px(12) + top + help + Soft.Px(12);
        }

        protected override void OnCheckedChanged(EventArgs e) { Invalidate(); tracker.Update(); base.OnCheckedChanged(e); }
        protected override void OnMouseEnter(EventArgs e) { hover = true; Invalidate(); base.OnMouseEnter(e); }
        protected override void OnMouseLeave(EventArgs e) { hover = false; Invalidate(); base.OnMouseLeave(e); }
        protected override void OnGotFocus(EventArgs e) { Invalidate(); base.OnGotFocus(e); }
        protected override void OnLostFocus(EventArgs e) { Invalidate(); base.OnLostFocus(e); }

        protected override void Dispose(bool disposing)
        {
            if (disposing && titleFont != null) { titleFont.Dispose(); titleFont = null; }
            base.Dispose(disposing);
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            var body = Body(Width, Height);
            float radius = Soft.PxF(Brand.RadiusControl);
            Ground.PaintBehind(this, g, ClientRectangle, radius);
            // In High Contrast the chosen card is filled with Highlight, so everything drawn on
            // it takes HighlightText, the colour every contrast theme pairs with Highlight - as
            // the page tabs do. In Accent the radio dot was Highlight on Highlight, and the title
            // and help in WindowText were under 1.5:1.
            bool onHighlight = Checked && Palette.Contrast;
            Color fill = onHighlight ? Palette.AccentSoft : Checked ? Palette.Inset : hover ? Palette.Surface : Palette.Raised;
            // Resting, raised as a button and as the panel's segment for the same setting are - no top light in
            // dark. Chosen, a well.
            Soft.Body(g, ClientRectangle, radius, fill, Checked ? Palette.Accent : Palette.Line, Checked && !Palette.Contrast);
            // The radio mark, so the card still says "one of these" without its colour.
            float mark = Soft.PxF(16);
            var ring = new RectangleF(body.X + Soft.PxF(14), body.Y + Soft.PxF(12), mark, mark);
            Color markColour = onHighlight ? SystemColors.HighlightText : Checked ? Palette.Accent : Palette.Muted;
            GraphicsState state = g.Save();
            g.SmoothingMode = SmoothingMode.AntiAlias;
            using (var pen = new Pen(markColour, Soft.PxF(1.5))) g.DrawEllipse(pen, ring);
            if (Checked)
            {
                float dot = mark * 0.5f;
                using (var brush = new SolidBrush(markColour))
                    g.FillEllipse(brush, ring.X + (mark - dot) / 2f, ring.Y + (mark - dot) / 2f, dot, dot);
            }
            g.Restore(state);
            Rectangle column = TextColumn(Width);
            int left = column.X, textWidth = column.Width;
            Font title = TitleFont;
            string heading = Soft.Wrap(Text ?? "", title, textWidth, Words);
            Size top = TextRenderer.MeasureText(heading, title, new Size(textWidth, int.MaxValue), Words);
            TextRenderer.DrawText(g, heading, title, new Rectangle(left, (int)body.Y + Soft.Px(10), textWidth, top.Height),
                                  onHighlight ? SystemColors.HighlightText : Checked ? Palette.Accent : Palette.Ink,
                                  Words);
            if (!string.IsNullOrEmpty(Help))
                TextRenderer.DrawText(g, Soft.Wrap(Help, Font, textWidth, Words), Font,
                                      new Rectangle(left, (int)body.Y + Soft.Px(12) + top.Height, textWidth, Height),
                                      onHighlight ? SystemColors.HighlightText : Palette.Secondary,
                                      Words);
        }
    }

    /// A column of ChoiceCards that lays itself out, says which one is chosen, and is the ground
    /// their lift is drawn on.
    internal sealed class ChoiceGroup : Panel, ISoftGround
    {
        internal event EventHandler ValueChanged;

        internal ChoiceGroup()
        {
            SetStyle(ControlStyles.OptimizedDoubleBuffer | ControlStyles.AllPaintingInWmPaint |
                     ControlStyles.UserPaint | ControlStyles.ResizeRedraw, true);
            BackColor = Palette.Card;
            // A TableLayoutPanel asks a child for its preferred size only when the child says
            // it sizes itself; otherwise it keeps whatever height the child already has, and
            // three of the four choices were cut off.
            AutoSize = true;
            AutoSizeMode = AutoSizeMode.GrowAndShrink;
        }

        internal void Add(ChoiceCard card)
        {
            card.CheckedChanged += delegate { if (card.Checked && ValueChanged != null) ValueChanged(this, EventArgs.Empty); };
            Controls.Add(card);
        }

        internal string Value
        {
            get
            {
                foreach (Control control in Controls)
                {
                    var card = control as ChoiceCard;
                    if (card != null && card.Checked) return card.Value;
                }
                return null;
            }
            set
            {
                foreach (Control control in Controls)
                {
                    var card = control as ChoiceCard;
                    if (card != null) card.Checked = card.Value == value;
                }
            }
        }

        private int WidthFor(Size proposed)
        {
            if (proposed.Width > Soft.Px(160) && proposed.Width < 20000) return proposed.Width;
            if (Width > Soft.Px(160)) return Width;
            return Soft.Px(460);
        }

        public override Size GetPreferredSize(Size proposedSize)
        {
            int width = WidthFor(proposedSize);
            int height = 0;
            foreach (Control control in Controls)
            {
                var card = control as ChoiceCard;
                if (card != null) height += card.HeightFor(width) + Soft.Px(Brand.SegmentGap);
            }
            return new Size(width, height);
        }

        protected override void OnLayout(LayoutEventArgs levent)
        {
            base.OnLayout(levent);
            int y = 0;
            foreach (Control control in Controls)
            {
                var card = control as ChoiceCard;
                if (card == null) continue;
                int height = card.HeightFor(Width);
                card.SetBounds(0, y, Width, height);
                y += height + Soft.Px(Brand.SegmentGap);
            }
        }

        protected override void OnSizeChanged(EventArgs e)
        {
            base.OnSizeChanged(e);
            PerformLayout();
        }

        protected override void OnPaintBackground(PaintEventArgs e)
        {
            Ground.Paint(this, e);
        }
    }

    /// A multi-line text box sitting in a well, for a message somebody writes.
    internal sealed class SoftTextArea : Panel, ISoftScroller
    {
        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        private static extern IntPtr SendMessage(IntPtr window, int message, IntPtr wParam, IntPtr lParam);

        [StructLayout(LayoutKind.Sequential)]
        private struct ScrollInfo
        {
            internal int Size, Mask, Min, Max, Page, Pos, TrackPos;
        }

        [DllImport("user32.dll")]
        private static extern bool GetScrollInfo(IntPtr window, int bar, ref ScrollInfo info);

        private const int SB_VERT = 1;
        private const int SIF_ALL = 0x17;
        private const int EM_LINESCROLL = 0x00B6;
        private const int EM_GETFIRSTVISIBLELINE = 0x00CE;
        private const int WM_VSCROLL = 0x0115;

        internal readonly TextBox Box = new TextBox();
        private readonly ListClip clip = new ListClip();
        private readonly SoftScrollBar bar;
        private readonly Watcher watcher;

        internal SoftTextArea()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                     ControlStyles.UserPaint | ControlStyles.ResizeRedraw, true);
            BackColor = Palette.Inset;
            bar = new SoftScrollBar(this, this);
            Box.BorderStyle = BorderStyle.None;
            Box.Multiline = true;
            Box.AcceptsReturn = true;
            Box.WordWrap = true;
            // Windows' own bar is kept - it is what scrolls the text, and the wheel and the keys go
            // through it - and hidden: the box is wider than the room it is given by exactly the bar,
            // so the bar falls outside this control, where a child window is never drawn. The soft bar
            // is drawn in the gutter that leaves, from the box's own scroll position, exactly as the
            // list's is (SoftListHost).
            Box.ScrollBars = ScrollBars.Vertical;
            Box.BackColor = Palette.Inset;
            Box.ForeColor = Palette.Ink;
            Box.GotFocus += delegate { Invalidate(); };
            Box.LostFocus += delegate { Invalidate(); };
            Box.TextChanged += delegate { Changed(); };
            Box.HandleCreated += delegate { Changed(); };
            watcher = new Watcher(this);
            clip.BackColor = Palette.Inset;
            clip.Controls.Add(Box);
            Controls.Add(clip);
            // The well's padding on the left, top and bottom; the scroll bar keeps to the edge.
            Padding = new Padding(Soft.Px(Brand.WellPadLeft), Soft.Px(Brand.WellPadTop), Soft.Px(6), Soft.Px(Brand.WellPadBottom));
            Height = Soft.Px(96);
        }

        /// Windows' own bar on the text box, as the box last drew it: how many lines there are, how
        /// many show, and the first that does.
        private ScrollInfo Read()
        {
            var info = new ScrollInfo();
            info.Size = Marshal.SizeOf(typeof(ScrollInfo));
            info.Mask = SIF_ALL;
            if (Box.IsHandleCreated && GetScrollInfo(Box.Handle, SB_VERT, ref info)) return info;
            info.Max = info.Page = info.Pos = 0;
            return info;
        }

        // The box is asked once a change and the answer kept: GetScrollInfo is cheap, but the bar asks
        // for all three while it draws and drags, and a keystroke must not cost three trips and a repaint.
        private ScrollInfo last;

        public int Extent { get { return Math.Max(0, last.Max - last.Min + 1); } }

        public int Viewport { get { return Math.Max(1, last.Page); } }

        public int Offset { get { return last.Pos; } }

        public void ScrollTo(int offset)
        {
            if (!Box.IsHandleCreated) return;
            int first = (int)SendMessage(Box.Handle, EM_GETFIRSTVISIBLELINE, IntPtr.Zero, IntPtr.Zero);
            SendMessage(Box.Handle, EM_LINESCROLL, IntPtr.Zero, (IntPtr)(offset - first));
            Changed();
        }

        public void Page(int direction)
        {
            ScrollTo(Offset + direction * Math.Max(1, Viewport - 1));
        }

        /// The box's scrolling, whoever caused it - the wheel, a key, the caret moving - so the soft
        /// bar is where the text is. WM_VSCROLL reaches the box's parent, which is this control.
        private sealed class Watcher : NativeWindow
        {
            private readonly SoftTextArea area;

            internal Watcher(SoftTextArea area)
            {
                this.area = area;
                area.Box.HandleCreated += delegate { AssignHandle(area.Box.Handle); };
                area.Box.HandleDestroyed += delegate { ReleaseHandle(); };
                area.Disposed += delegate { ReleaseHandle(); };
            }

            protected override void WndProc(ref Message m)
            {
                base.WndProc(ref m);
                if (m.Msg == WM_VSCROLL || m.Msg == 0x020A || m.Msg == 0x0102 || m.Msg == 0x0100)
                    area.Changed();                      // the wheel and the keys scroll it too
            }
        }

        /// Where the soft bar is, and whether there is one: the gutter is kept only while the text is
        /// taller than the box.
        private void Changed()
        {
            if (IsDisposed || !IsHandleCreated) return;
            ScrollInfo now = Read();
            bool moved = now.Pos != last.Pos || now.Page != last.Page || now.Max != last.Max || now.Min != last.Min;
            last = now;
            if (!moved) return;                          // nothing to draw again: a keystroke costs nothing
            int gutter = Soft.Px(SoftBar.TrackWidth);
            Rectangle track = Extent > Viewport
                ? new Rectangle(Width - Padding.Right - gutter, Padding.Top, gutter,
                                Math.Max(0, Height - Padding.Vertical))
                : Rectangle.Empty;
            bool appeared = track.IsEmpty != bar.Track.IsEmpty;
            bar.Track = track;                           // invalidates what it covers itself
            if (appeared) PerformLayout();               // the gutter came or went: the box's width did too
            else if (!track.IsEmpty) Invalidate(track);
        }

        internal SoftScrollBar Bar { get { return bar; } }

        protected override void OnLayout(LayoutEventArgs levent)
        {
            base.OnLayout(levent);
            int room = Math.Max(0, Width - Padding.Horizontal);
            // Wider than the room by the bar, so Windows' bar sits outside this control and is never
            // drawn; narrower by the gutter while the soft bar shows, so no text runs under it.
            int native = SystemInformation.VerticalScrollBarWidth;
            int gutter = bar.Track.IsEmpty ? 0 : Soft.Px(SoftBar.TrackWidth);
            int tall = Math.Max(0, Height - Padding.Vertical);
            clip.SetBounds(Padding.Left, Padding.Top, Math.Max(0, room - gutter), tall);
            Box.SetBounds(0, 0, Math.Max(0, room - gutter + native), tall);
            Changed();
        }

        protected override void OnPaintBackground(PaintEventArgs e)
        {
            float radius = Soft.PxF(Brand.RadiusControl);
            Ground.PaintBehind(this, e.Graphics, ClientRectangle, radius);
            Soft.InsetWell(e.Graphics, ClientRectangle, radius, Box.Focused);
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            base.OnPaint(e);
            if (!bar.Track.IsEmpty) bar.Paint(e.Graphics);
        }
    }

    /// A read-only block of text in a well: the Preview.
    internal sealed class SoftQuote : Panel
    {
        private string text = "";

        internal SoftQuote()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                     ControlStyles.UserPaint | ControlStyles.ResizeRedraw, true);
            BackColor = Palette.Inset;
            TabStop = false;
            AutoSize = true;
            AutoSizeMode = AutoSizeMode.GrowAndShrink;
        }

        internal string Quote
        {
            get { return text; }
            set
            {
                text = value ?? "";
                AccessibleDescription = text;
                if (Parent != null) Parent.PerformLayout();
                Invalidate();
            }
        }

        public override Size GetPreferredSize(Size proposedSize)
        {
            int width = proposedSize.Width > Soft.Px(160) && proposedSize.Width < 20000 ? proposedSize.Width
                      : Width > Soft.Px(160) ? Width : Soft.Px(460);
            string shown = text.Length == 0 ? " " : text;
            int room = width - Soft.Px(28);
            int textHeight = TextRenderer.MeasureText(Soft.Wrap(shown, Font, room, Words), Font, new Size(room, int.MaxValue),
                                                      Words).Height;
            return new Size(width, textHeight + Soft.Px(24));
        }

        // The message wraps in the well, Korean between its words (Soft.Wrap).
        private const TextFormatFlags Words = TextFormatFlags.WordBreak | TextFormatFlags.TextBoxControl | TextFormatFlags.Left;

        protected override void OnPaint(PaintEventArgs e)
        {
            float radius = Soft.PxF(Brand.RadiusControl);
            Ground.PaintBehind(this, e.Graphics, ClientRectangle, radius);
            Soft.InsetWell(e.Graphics, ClientRectangle, radius, false);
            int room = Math.Max(0, Width - Soft.Px(Brand.WellPadLeft + Brand.WellPadRight));
            TextRenderer.DrawText(e.Graphics, Soft.Wrap(text, Font, room, Words), Font,
                                  new Rectangle(Soft.Px(Brand.WellPadLeft), Soft.Px(Brand.WellPadTop), room, Height),
                                  Palette.Ink, Words);
        }
    }

    /// A label whose lines end where the popup's and the panel's do (Soft.Wrap): Korean between its words,
    /// never inside one - a help line, a note, a value. Text without Korean is measured and drawn by Label
    /// itself, exactly as before; with Korean, as Label would draw it, only broken where a line may end.
    internal class WrapLabel : Label
    {
        /// How Label draws its text (ControlPaint.CreateTextFormatFlags): wrapped as a text box, in its
        /// alignment, with an ellipsis if it ends in one and its mnemonic as it is set.
        internal TextFormatFlags Format
        {
            get
            {
                TextFormatFlags flags = TextFormatFlags.WordBreak | TextFormatFlags.TextBoxControl;
                const ContentAlignment middle = ContentAlignment.MiddleLeft | ContentAlignment.MiddleCenter | ContentAlignment.MiddleRight;
                const ContentAlignment bottom = ContentAlignment.BottomLeft | ContentAlignment.BottomCenter | ContentAlignment.BottomRight;
                const ContentAlignment centre = ContentAlignment.TopCenter | ContentAlignment.MiddleCenter | ContentAlignment.BottomCenter;
                const ContentAlignment right = ContentAlignment.TopRight | ContentAlignment.MiddleRight | ContentAlignment.BottomRight;
                if ((TextAlign & middle) != 0) flags |= TextFormatFlags.VerticalCenter;
                else if ((TextAlign & bottom) != 0) flags |= TextFormatFlags.Bottom;
                if ((TextAlign & centre) != 0) flags |= TextFormatFlags.HorizontalCenter;
                else if ((TextAlign & right) != 0) flags |= TextFormatFlags.Right;
                if (AutoEllipsis) flags |= TextFormatFlags.EndEllipsis;
                if (!UseMnemonic) flags |= TextFormatFlags.NoPrefix;
                else if (!ShowKeyboardCues) flags |= TextFormatFlags.HidePrefix;
                return flags;
            }
        }

        /// Its text in the lines it is drawn in `width` wide inside its padding (Soft.Wrap).
        internal string Lines(int width)
        {
            return Soft.Wrap(Text, Font, width, Format);
        }

        public override Size GetPreferredSize(Size proposedSize)
        {
            if (!Soft.SplitsWords(Text)) return base.GetPreferredSize(proposedSize);
            // As Label answers - a width of 0 or 1 is none - measured in the lines it is drawn in.
            int width = proposedSize.Width > 1 ? proposedSize.Width : int.MaxValue;
            if (MaximumSize.Width > 0) width = Math.Min(width, MaximumSize.Width);
            int inner = width == int.MaxValue ? int.MaxValue : Math.Max(1, width - Padding.Horizontal);
            Size text = TextRenderer.MeasureText(Lines(inner), Font, new Size(inner, int.MaxValue), Format);
            var size = new Size(text.Width + Padding.Horizontal, text.Height + Padding.Vertical);
            if (MaximumSize.Width > 0) size.Width = Math.Min(size.Width, MaximumSize.Width);
            if (MaximumSize.Height > 0) size.Height = Math.Min(size.Height, MaximumSize.Height);
            return new Size(Math.Max(size.Width, MinimumSize.Width), Math.Max(size.Height, MinimumSize.Height));
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            if (!Soft.SplitsWords(Text))
            {
                base.OnPaint(e);
                return;
            }
            var face = new Rectangle(Padding.Left, Padding.Top, Math.Max(0, ClientSize.Width - Padding.Horizontal),
                                     Math.Max(0, ClientSize.Height - Padding.Vertical));
            // Label's disabled ink (TextRenderer.DisabledTextColor), High Contrast as the window reads it.
            Color ink = Enabled ? ForeColor
                      : Palette.Contrast ? SystemColors.GrayText
                      : BackColor.GetBrightness() < SystemColors.Control.GetBrightness() ? ControlPaint.Dark(BackColor)
                      : SystemColors.ControlDark;
            TextRenderer.DrawText(e.Graphics, Lines(face.Width), Font, face, ink, Format);
        }
    }

    /// A list whose rows are drawn by the page that owns it, double-buffered so a five-second
    /// refresh does not flicker.
    internal sealed class SoftList : ListView
    {
        private const int WM_SIZE = 0x0005;
        private const int WM_PAINT = 0x000F;
        private const int WM_STYLECHANGED = 0x007D;
        private const int WM_KEYDOWN = 0x0100;
        private const int WM_HSCROLL = 0x0114;
        private const int WM_VSCROLL = 0x0115;
        private const int WM_MOUSEWHEEL = 0x020A;
        private const int WM_MOUSEHWHEEL = 0x020E;

        internal SoftList()
        {
            SetStyle(ControlStyles.OptimizedDoubleBuffer | ControlStyles.AllPaintingInWmPaint, true);
        }

        /// After anything that can move or resize what the list shows - a scroll either way, a key, a
        /// resize, a scroll bar coming or going, and every paint, which follows all of those.
        internal event EventHandler ScrollChanged;

        protected override void WndProc(ref Message m)
        {
            base.WndProc(ref m);
            if (ScrollChanged != null && (m.Msg == WM_PAINT || m.Msg == WM_VSCROLL || m.Msg == WM_HSCROLL ||
                                          m.Msg == WM_MOUSEWHEEL || m.Msg == WM_MOUSEHWHEEL ||
                                          m.Msg == WM_KEYDOWN || m.Msg == WM_SIZE || m.Msg == WM_STYLECHANGED))
                ScrollChanged(this, EventArgs.Empty);
        }
    }

    /// The strip a SoftListHost shows its list through: exactly as wide as the list's rows and as tall
    /// as the rows it shows, so the list's own scroll bars, beside and below them, are outside it.
    internal sealed class ListClip : Panel
    {
        internal ListClip()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.UserPaint, true);
            TabStop = false;
        }
    }

    /// A list with the soft scroll bar in place of its own.
    ///
    /// The list stays a whole native ListView - its keyboard selection, its wheel, its header, its
    /// owner-drawn rows and what a screen reader is told are all Windows' - and it keeps its own scroll
    /// bar. The host only hides that bar: the list stands in a ListClip exactly as wide as its rows, and
    /// is itself wider by the bar, so the bar lies outside the clip, where a child window is never drawn.
    /// Its rows' width, and so every column (SettingsForm.FitColumns), is what it always was. While it
    /// has more rows than show, the clip is narrower by the gutter, and the host draws the soft bar
    /// there from the list's own scroll position (GetScrollInfo, in rows). Dragging, paging and the
    /// wheel over the bar are sent to the list as the scrolling it already understands (LVM_SCROLL,
    /// WM_VSCROLL), and the bar follows whatever the list does itself (SoftList.ScrollChanged).
    ///
    /// The same across its bottom (v0.6.5): Windows' own horizontal bar showed white on a dark card when
    /// the columns were a little wider than the list. The window makes the columns fit the list at every
    /// ordinary size (SettingsForm.FitColumns), so a list overflows sideways only in a window narrower
    /// than they can shrink to. Then, and only then, the list is taller than the clip by its own
    /// horizontal bar, which lies under the clip unseen, the clip is shorter by the gutter, and the host
    /// draws the soft bar lying along the bottom (AcrossBar) from the list's horizontal scroll position,
    /// in pixels, scrolling it with LVM_SCROLL and WM_HSCROLL.
    internal sealed class SoftListHost : Panel, ISoftScroller
    {
        [StructLayout(LayoutKind.Sequential)]
        private struct ScrollInfo
        {
            public int Size, Mask, Min, Max, Page, Position, TrackPosition;
        }

        [DllImport("user32.dll")]
        private static extern bool GetScrollInfo(IntPtr window, int bar, ref ScrollInfo info);

        [DllImport("user32.dll")]
        private static extern int GetWindowLong(IntPtr window, int index);

        [DllImport("user32.dll")]
        private static extern IntPtr SendMessage(IntPtr window, int message, IntPtr wParam, IntPtr lParam);

        private const int SB_HORZ = 0;
        private const int SB_VERT = 1;
        private const int SIF_ALL = 0x17;
        private const int GWL_STYLE = -16;
        private const int WS_HSCROLL = 0x00100000;
        private const int WS_VSCROLL = 0x00200000;
        private const int WM_HSCROLL = 0x0114;
        private const int WM_VSCROLL = 0x0115;
        private const int SB_PAGEUP = 2;
        private const int SB_PAGEDOWN = 3;
        private const int SB_PAGELEFT = 2;
        private const int SB_PAGERIGHT = 3;
        private const int LVM_SCROLL = 0x1014;

        internal readonly ListView List;
        private readonly ListClip clip = new ListClip();
        private readonly SoftScrollBar bar, acrossBar;
        private readonly Sideways sideways;
        private ScrollInfo scroll, sideScroll;
        private bool native, nativeAcross, queued;

        internal SoftListHost(ListView list)
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                     ControlStyles.UserPaint | ControlStyles.ResizeRedraw, true);
            List = list;
            // Before anything is added: adding lays the host out, and laying out places the bars.
            bar = new SoftScrollBar(this, this);
            sideways = new Sideways(this);
            acrossBar = new SoftScrollBar(this, sideways, true);
            BackColor = list.BackColor;
            clip.BackColor = list.BackColor;
            list.Dock = DockStyle.None;
            list.Margin = new Padding(0);
            clip.Controls.Add(list);
            Controls.Add(clip);
            var soft = list as SoftList;
            if (soft != null) soft.ScrollChanged += delegate { Changed(); };
            list.HandleCreated += delegate { Changed(); };
        }

        internal SoftScrollBar Bar { get { return bar; } }

        /// The soft bar along the bottom, scrolling the list sideways; its Track is empty while the
        /// columns fit.
        internal SoftScrollBar AcrossBar { get { return acrossBar; } }

        /// Whether the list has more rows than show, so the soft bar is showing.
        internal bool Overflowing { get { return native; } }

        /// Whether the list's columns are wider than it is, so the soft bar along its bottom is showing
        /// - and Windows' own horizontal bar is on, under the clip. Read from the list's style once the
        /// window has had its messages; LayoutAudit, which never pumps them, compares the columns with
        /// the list's width instead (SettingsForm.AuditList).
        internal bool OverflowingAcross { get { return nativeAcross; } }

        internal ListClip Clip { get { return clip; } }

        // The list's horizontal scroll position as last read.
        private ScrollInfo Side { get { return sideScroll; } }

        /// The list's sideways scrolling as the soft bar reads it: in pixels, as Windows keeps it for a
        /// list of details.
        private sealed class Sideways : ISoftScroller
        {
            private readonly SoftListHost host;

            internal Sideways(SoftListHost host) { this.host = host; }

            public int Extent { get { ScrollInfo info = host.Side; return Math.Max(0, info.Max - info.Min + 1); } }
            public int Viewport { get { return Math.Max(1, host.Side.Page); } }
            public int Offset { get { ScrollInfo info = host.Side; return Math.Max(0, info.Position - info.Min); } }

            public void ScrollTo(int target)
            {
                ListView list = host.List;
                if (!list.IsHandleCreated) return;
                host.Read();
                target = Math.Max(0, Math.Min(Math.Max(0, Extent - Viewport), target));
                int by = target - Offset;
                if (by == 0) return;
                SendMessage(list.Handle, LVM_SCROLL, new IntPtr(by), IntPtr.Zero);
                host.Sync();
            }

            public void Page(int direction)
            {
                ListView list = host.List;
                if (!list.IsHandleCreated) return;
                SendMessage(list.Handle, WM_HSCROLL, new IntPtr(direction < 0 ? SB_PAGELEFT : SB_PAGERIGHT), IntPtr.Zero);
                host.Sync();
            }
        }

        int ISoftScroller.Extent { get { return Math.Max(0, scroll.Max - scroll.Min + 1); } }
        int ISoftScroller.Viewport { get { return Math.Max(1, scroll.Page); } }
        int ISoftScroller.Offset { get { return Math.Max(0, scroll.Position - scroll.Min); } }

        void ISoftScroller.ScrollTo(int target)
        {
            if (!List.IsHandleCreated || List.Items.Count == 0) return;
            Read();
            var self = (ISoftScroller)this;
            target = Math.Max(0, Math.Min(Math.Max(0, self.Extent - self.Viewport), target));
            int rows = target - self.Offset, row = List.GetItemRect(0).Height;
            if (rows == 0 || row <= 0) return;
            SendMessage(List.Handle, LVM_SCROLL, IntPtr.Zero, new IntPtr(rows * row));
            Sync();
        }

        void ISoftScroller.Page(int direction)
        {
            if (!List.IsHandleCreated) return;
            SendMessage(List.Handle, WM_VSCROLL, new IntPtr(direction < 0 ? SB_PAGEUP : SB_PAGEDOWN), IntPtr.Zero);
            Sync();
        }

        private bool NativeBar
        {
            get { return List.IsHandleCreated && (GetWindowLong(List.Handle, GWL_STYLE) & WS_VSCROLL) != 0; }
        }

        private bool NativeAcross
        {
            get { return List.IsHandleCreated && (GetWindowLong(List.Handle, GWL_STYLE) & WS_HSCROLL) != 0; }
        }

        private void Read()
        {
            scroll = ReadBar(SB_VERT);
            sideScroll = ReadBar(SB_HORZ);
        }

        private ScrollInfo ReadBar(int which)
        {
            var info = new ScrollInfo();
            info.Size = Marshal.SizeOf(typeof(ScrollInfo));
            info.Mask = SIF_ALL;
            if (List.IsHandleCreated && GetScrollInfo(List.Handle, which, ref info)) return info;
            return new ScrollInfo();
        }

        protected override void OnLayout(LayoutEventArgs levent)
        {
            base.OnLayout(levent);
            native = NativeBar;
            nativeAcross = NativeAcross;
            int rows = Math.Max(0, Width - (native ? SoftBar.Gutter : 0));
            int tall = Math.Max(0, Height - (nativeAcross ? SoftBar.Gutter : 0));
            // The list's own bar is as wide as the list is wider than its rows; before it has one,
            // Windows' measure of a scroll bar. The same below, for its bar across the bottom.
            int beside = native ? Math.Max(0, List.Width - List.ClientSize.Width) : 0;
            if (native && beside == 0) beside = SystemInformation.VerticalScrollBarWidth;
            int below = nativeAcross ? Math.Max(0, List.Height - List.ClientSize.Height) : 0;
            if (nativeAcross && below == 0) below = SystemInformation.HorizontalScrollBarHeight;
            clip.SetBounds(0, 0, rows, tall);
            List.SetBounds(0, 0, rows + beside, tall + below);
            Read();
            bar.Track = native ? TrackBounds() : Rectangle.Empty;
            acrossBar.Track = nativeAcross ? AcrossBounds() : Rectangle.Empty;
        }

        // Beside the rows: from under the column headings to the bottom, or to the bar along it.
        private Rectangle TrackBounds()
        {
            int margin = Soft.Px(SoftBar.TrackMargin);
            int top = List.Items.Count > 0 && List.View == View.Details ? Math.Max(0, List.GetItemRect(List.TopItem != null ? List.TopItem.Index : 0).Top) : 0;
            int bottom = Height - (nativeAcross ? SoftBar.Gutter : 0);
            return new Rectangle(Width - margin - Soft.Px(SoftBar.TrackWidth), top + margin, Soft.Px(SoftBar.TrackWidth),
                                 Math.Max(0, bottom - top - 2 * margin));
        }

        // Along the bottom, under the rows: from the left edge to the bar beside them, if that shows.
        private Rectangle AcrossBounds()
        {
            int margin = Soft.Px(SoftBar.TrackMargin);
            int right = Width - (native ? SoftBar.Gutter : 0);
            return new Rectangle(margin, Height - margin - Soft.Px(SoftBar.TrackWidth), Math.Max(0, right - 2 * margin),
                                 Soft.Px(SoftBar.TrackWidth));
        }

        // Called from inside the list's own messages, so what it changes waits until they are done.
        private void Changed()
        {
            if (queued || !IsHandleCreated) return;
            queued = true;
            BeginInvoke(new MethodInvoker(delegate { queued = false; Sync(); }));
        }

        /// Brings the soft bar in step with the list: laid out again when the list's own bar came or went,
        /// painted again when its position or length changed.
        internal void Sync()
        {
            if (IsDisposed || !List.IsHandleCreated) return;
            if (NativeBar != native || NativeAcross != nativeAcross)
            {
                PerformLayout();
                Invalidate();
                return;
            }
            ScrollInfo before = scroll, sideBefore = sideScroll;
            Read();
            Rectangle track = native ? TrackBounds() : Rectangle.Empty;
            if (before.Position != scroll.Position || before.Max != scroll.Max || before.Page != scroll.Page || track != bar.Track)
            {
                bar.Track = track;
                bar.Invalidate();
            }
            Rectangle across = nativeAcross ? AcrossBounds() : Rectangle.Empty;
            if (sideBefore.Position != sideScroll.Position || sideBefore.Max != sideScroll.Max ||
                sideBefore.Page != sideScroll.Page || across != acrossBar.Track)
            {
                acrossBar.Track = across;
                acrossBar.Invalidate();
            }
        }

        protected override void OnMouseWheel(MouseEventArgs e)
        {
            base.OnMouseWheel(e);
            if (!native) return;
            var self = (ISoftScroller)this;
            int rows = SoftBar.WheelStep(e.Delta, SystemInformation.MouseWheelScrollLines, 1, self.Viewport);
            if (rows != 0) self.ScrollTo(self.Offset + rows);
            var handled = e as HandledMouseEventArgs;
            if (handled != null) handled.Handled = true;
        }

        protected override void OnPaintBackground(PaintEventArgs e)
        {
            using (var brush = new SolidBrush(BackColor)) e.Graphics.FillRectangle(brush, e.ClipRectangle);
            if (native) bar.Paint(e.Graphics);
            if (nativeAcross) acrossBar.Paint(e.Graphics);
        }
    }

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
    /// Contrast the dot is a system colour, unlit.
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
            if (!Visible || !IsHandleCreated || Soft.ReduceMotion) return false;
            Form form = FindForm();
            if (form != null && form.WindowState == FormWindowState.Minimized) return false;
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
            double since = clock.Elapsed.TotalMilliseconds - enteredAt;
            double dim, opacity, spread, arc;
            bool lit = Brand.Glow(state, since, since, Soft.ReduceMotion, out dim, out opacity, out spread, out arc);
            Color colour = DotColour(state);
            float cx = Width / 2f, cy = Height / 2f, dot = Soft.PxF(Brand.StatusDotRadius);
            GraphicsState saved = g.Save();
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.PixelOffsetMode = PixelOffsetMode.Half;
            if (lit && opacity > 0 && !Palette.Contrast)
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
    /// Theme.ContrastOn), under battery saver, while the session is locked or disconnected, or while the window is not
    /// shown; the states then differ by colour only.
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
        /// effects or High Contrast (Soft.ReduceMotion, which High Contrast's palette is part of, and Theme.ContrastOn),
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
            return MotionAllowed(Soft.ReduceMotion, contrast, saver, locked, owner.Visible && owner.IsHandleCreated, Frames() != null);
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
