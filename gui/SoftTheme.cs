// Codex Auto Resume - the window's vocabulary: its theme, its colours, its sizes and its motion.
//
// Everything below is read from gui/Brand.cs, which is generated from the Python palette, so
// this window, the panel in Codex and the notification-area popup cannot end up different
// colours or different speeds. Nothing here paints; it says what painting is allowed to use.

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

        /// v0.6.10's fourth design, which the settings layer reads as Soft with Reduce motion on
        /// (settings.FOLDED_DESIGN, settings._fold_design) - a name the window reads in a stored file, never draws.
        internal const string FoldedDesign = "still";

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

        /// The Theme and Design preferences an installation's settings store, read from its settings file
        /// before anything is drawn: the bridge that reads it properly takes a Python start, and every colour
        /// is decided before the first control exists. The first settings read through the bridge
        /// confirms it (SettingsForm.Observe), so the file is read exactly as settings.load reads it for
        /// the bridge: no more than MaxSettingsBytes, UTF-8 with no byte order mark and no invalid byte,
        /// and one JSON value with nothing after it. Any other file is the defaults to the settings layer,
        /// so it is "system" and "soft" here too, as is no file at all - a file the two read differently
        /// opened the window in one theme and had its first read reopen it in the other, every time it was
        /// opened. v0.6.10: the design is read in the same parse as the theme, never in a second read of its
        /// own, so the two can never come from two versions of the file. v0.6.11: Reduce motion too, as
        /// settings.load has it - true exactly, or a stored Still (FoldedDesign), whatever stands beside it - so a
        /// window that opens on a Still, or on Reduce motion, holds its motion from its first frame and not only
        /// once the bridge's settings read has come back (SettingsPage.AdoptSettings).
        internal static void Stored(string root, out string theme, out string design, out bool reduceMotion)
        {
            theme = System;
            design = Brand.DesignDefault;
            reduceMotion = false;
            try
            {
                var file = new FileInfo(Path.Combine(Path.Combine(root, "config"), "settings.json"));
                if (!file.Exists || file.Length > MaxSettingsBytes) return;
                string text = new UTF8Encoding(false, true).GetString(File.ReadAllBytes(file.FullName));
                if (text.Length > 0 && text[0] == '\uFEFF') return;
                var map = Json.ParseDocument(text) as Dictionary<string, object>;
                if (map == null) return;
                object value;
                string storedTheme = map.TryGetValue("theme", out value) ? Preference(value) : System;
                string storedDesign = Brand.DesignDefault;
                bool storedMotion = map.TryGetValue("reduce_motion", out value) && Equals(value, true);
                if (map.TryGetValue("design", out value))
                {
                    storedDesign = Design.Preference(value);
                    if (Equals(value, FoldedDesign)) storedMotion = true;
                }
                theme = storedTheme;
                design = storedDesign;
                reduceMotion = storedMotion;
            }
            catch (Exception)
            {
                theme = System;
                design = Brand.DesignDefault;
                reduceMotion = false;
            }
        }
    }

    /// Which design the window is drawn in (v0.6.10): the Design setting, which says what is drawn
    /// (brand/design.py, read through Brand's Design rules) and never what moves - Soft.ReduceMotion says that.
    /// It is independent of the theme, so each design is drawn light or dark, and High Contrast replaces every
    /// design: its system colours, with no depth, glow or accent bar and Soft's corners. It is decided once, as
    /// the window opens, from the same read of the settings file as the theme (Theme.Stored), and a change of
    /// it reopens the window as a change of theme does.
    internal static class Design
    {
        /// The Design preference the window opened with; set once, by Program.Main.
        internal static string Opened = Brand.DesignDefault;

        /// A stored Design as the settings layer reads it: one of Brand's designs exactly, and "soft" for
        /// anything else (Brand.DesignOf) - v0.6.10's "still" too, whose Reduce motion the settings layer adds
        /// (settings._migrate) and the window reads beside it in the same parse (Theme.Stored).
        internal static string Preference(object value)
        {
            return Brand.DesignOf(value);
        }

        /// The design a window draws in `theme` ("light", "dark" or "contrast") when `design` is chosen: the
        /// choice, and in High Contrast none but Soft's, which High Contrast has replaced. What a reopen compares,
        /// so a change of design under High Contrast, which draws nothing differently, reopens nothing. Pure.
        internal static string Drawn(string theme, string design)
        {
            return theme == Theme.Contrast ? Brand.DesignDefault : Preference(design);
        }
    }

    /// The brand colours of the theme and design in effect - Soft's, or since v0.6.10 a design's own - never a
    /// system colour. What High Contrast replaces is Palette's business; a few rules that name
    /// the High Contrast colour themselves (the scroll bar's) read the brand half here. Every colour is the one
    /// Brand.LookOf answers for the design and the theme: choosing a design's colours by its name is generated code
    /// (Brand.Look), and nothing here or anywhere else in the window names a design.
    internal static class Tokens
    {
        internal static bool Dark;
        /// The design whose colours these are (Brand.DesignColours): a design's own where it has them, and Soft's
        /// otherwise. Palette sets the design it draws in before it adopts a theme, and Adopt narrows it to this.
        internal static string Design = Brand.DesignDefault;
        /// The design and theme in effect, as Brand.LookOf answers them: the colours below and the check box's.
        internal static Brand.Look Look;
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
            Look = Brand.LookOf(Design, dark);
            Design = Look.Colours;
            Ink = Look.Ink; Muted = Look.Muted; Line = Look.Line; Surface = Look.Surface; Canvas = Look.Canvas;
            Raised = Look.Raised; Inset = Look.Inset; Accent = Look.Accent; AccentHover = Look.AccentHover;
            AccentPressed = Look.AccentPressed; OnAccent = Look.OnAccent; AccentSoft = Look.AccentSoft;
            Focus = Look.Focus; Active = Look.Active; Idle = Look.Idle; Attention = Look.Attention;
            Success = Look.Success; Waiting = Look.Waiting; Warning = Look.Warning; Danger = Look.Danger;
            Paused = Look.Paused; Card = Look.CardGround; ShadowDark = Look.ShadowDark; ShadowLight = Look.ShadowLight;
        }

        /// The check box's fill in the design and theme in effect (brand.check_box): its own colours' rule, so an
        /// unchecked box is the design's well colour and a disabled one its surface.
        internal static Color CheckFill(bool on, bool enabled)
        {
            return Look.CheckFill(on, enabled);
        }

        /// The check box's hairline edge in the design and theme in effect.
        internal static Color CheckEdge(bool on, bool enabled)
        {
            return Look.CheckEdge(on, enabled);
        }

        /// The check mark's colour in the design and theme in effect, or false when the box has no mark.
        internal static bool CheckMark(bool on, bool enabled, out Color mark)
        {
            return Look.CheckMark(on, enabled, out mark);
        }
    }

    /// The palette as the window uses it, with High Contrast honoured in one place. Light and Soft until the
    /// window adopts its design and theme (AdoptDesign, Adopt), which Program.Main does before the first control
    /// is made.
    ///
    /// v0.6.10: Contrast meant two things until the designs came - draw in system colours, and draw no depth,
    /// glow or tint - and Classic and Plain need the second without the first. So Contrast now means the system
    /// colours alone, and what a design may take away has a flag of its own that High Contrast also clears:
    /// Depth (shadows, wells, a lifted card), Halo (the status light's glow) and AccentBar (Classic's bar and
    /// underlined tab), with the corners' radii beside them. None of them changes a size, a margin or where
    /// anything is: a design changes paint, never layout.
    internal static class Palette
    {
        /// "light", "dark" or "contrast".
        internal static string Theme = CodexAutoResume.Theme.Light;
        internal static bool Contrast;
        /// The design the window is drawn in, one of Brand's designs as Brand.DesignOf reads it (AdoptDesign).
        internal static string Design = Brand.DesignDefault;
        /// The design in the theme in effect, as Brand.LookOf answers it: what the flags below are read from.
        internal static Brand.Look Look;
        /// Whether shadows, wells and a card's lift are drawn: the design has depth, and not High Contrast.
        internal static bool Depth;
        /// Whether the status light's glow is drawn: the design has one, and not High Contrast.
        internal static bool Halo;
        /// Whether Classic's accent bar and underlined tab are drawn: the design has them, and not High Contrast.
        internal static bool AccentBar;
        /// The corners, in CSS px: the design's (Brand.DesignRadius), never rounder than Soft's, and Soft's in High
        /// Contrast. Paint only.
        internal static int RadiusCard, RadiusControl, RadiusSmall, RadiusCheck;
        internal static Color Ink, Muted, Secondary, Line, Surface, Canvas, Raised, Inset, Accent, AccentHover,
                              AccentPressed, OnAccent, AccentSoft, Focus, Active, Idle, Attention, Success, Waiting,
                              Warning, Danger, Paused;
        /// A card's own ground: the surface in light, the surface lifted a step toward raised in dark.
        internal static Color Card;

        static Palette()
        {
            Adopt(CodexAutoResume.Theme.ContrastOn() ? CodexAutoResume.Theme.Contrast : CodexAutoResume.Theme.Light);
        }

        /// Draws everything from here on in `design` (one of Brand's four; anything else is Soft, as the settings
        /// layer reads it) and in the theme in effect again.
        internal static void AdoptDesign(string design)
        {
            Design = Brand.DesignOf(design);
            Adopt(Theme);
        }

        /// Draws everything from here on in `theme`: "light", "dark" or "contrast". Anything else is light. In
        /// the design in effect (AdoptDesign).
        internal static void Adopt(string theme)
        {
            Contrast = theme == CodexAutoResume.Theme.Contrast;
            bool dark = theme == CodexAutoResume.Theme.Dark;
            Theme = Contrast ? CodexAutoResume.Theme.Contrast : dark ? CodexAutoResume.Theme.Dark : CodexAutoResume.Theme.Light;
            Tokens.Design = Design;
            Tokens.Adopt(dark);
            Elevation.Forget();
            Look = Brand.LookOf(Design, dark);
            Depth = !Contrast && Look.Depth;
            Halo = !Contrast && Look.Glow;
            AccentBar = !Contrast && Look.AccentBar;
            Brand.Look corners = Brand.LookOf(CodexAutoResume.Design.Drawn(Theme, Design), dark);
            RadiusCard = corners.RadiusCard;
            RadiusControl = corners.RadiusControl;
            RadiusSmall = corners.RadiusSmall;
            RadiusCheck = corners.RadiusCheck;
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

        /// This product's own "Reduce motion" setting: read from the settings file as the window opens
        /// (Theme.Stored, Program.Main), and adopted again when the bridge's settings read comes back.
        internal static bool ReduceMotionSetting;

        /// The moment of its breath every status light is held at, in milliseconds, or -1 for the
        /// light's own clock - which is what anybody running the product gets.
        ///
        /// A picture of a light that breathes is taken at whatever moment the capture happened to
        /// fall on, so the same window photographed twice came out with the dot at two different
        /// brightnesses and every screenshot in the repository changed for a reason that was not
        /// the source. CODEX_AR_STILL_LIGHT=&lt;ms&gt; holds the breath still at that moment;
        /// build/capture_window.ps1 sets it to 0, where the breath is brightest. Read once, at
        /// start, and never set by the product itself.
        internal static readonly double StillLightMs = ReadStillLight();

        /// The moment the window is to believe it is, in seconds since 1970, or -1 for the real
        /// clock - which is what anybody running the product gets.
        ///
        /// The window works out a countdown itself, from the times in an answer against now, so a
        /// picture of the same pinned records taken a minute later showed one minute less and the
        /// screenshot changed for a reason that was not the source. CODEX_AR_STILL_NOW=&lt;epoch&gt;
        /// makes the window read that moment instead; build/make_screenshots.py sets it to the
        /// moment its records are seeded at. Read once, at start, and never set by the product.
        internal static readonly double StillNow = ReadStillNow();

        private static double ReadStillNow()
        {
            try
            {
                double seconds;
                string set = Environment.GetEnvironmentVariable("CODEX_AR_STILL_NOW");
                if (!string.IsNullOrEmpty(set) &&
                    double.TryParse(set, System.Globalization.NumberStyles.Float,
                                    System.Globalization.CultureInfo.InvariantCulture, out seconds) &&
                    seconds > 0) return seconds;
            }
            catch (Exception) { }
            return -1;
        }

        private static double ReadStillLight()
        {
            try
            {
                double ms;
                string set = Environment.GetEnvironmentVariable("CODEX_AR_STILL_LIGHT");
                if (!string.IsNullOrEmpty(set) &&
                    double.TryParse(set, System.Globalization.NumberStyles.Float,
                                    System.Globalization.CultureInfo.InvariantCulture, out ms) &&
                    ms >= 0 && ms < 1000000) return ms;
            }
            catch (Exception) { }
            return -1;
        }

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

        // The same method, bound once as a delegate. It is asked on a dozen hot paths - every layout of
        // every row, card and page - and `MethodInfo.Invoke` boxes an argument array and walks the
        // reflection layer each time, which is about a microsecond a call for an answer that is a bit
        // test. Binding is done once, and falls back to the reflection call if it cannot be done at all.
        private delegate bool StateOf(Control control, int bit);

        private static readonly StateOf OwnStateCall = BindOwnState();

        private static StateOf BindOwnState()
        {
            if (OwnState == null) return null;
            try { return (StateOf)Delegate.CreateDelegate(typeof(StateOf), OwnState); }
            catch (Exception) { return null; }
        }

        /// Whether a control was told to be visible, which is whether layout makes room for it -
        /// whatever its parents are, and with or without a window.
        internal static bool OwnVisible(Control control)
        {
            if (OwnStateCall != null) return OwnStateCall(control, 2);
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
            Body(g, face, radius, Palette.Inset, Palette.Line, Palette.Depth);
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
        /// the rest. In a design without depth (Classic, Plain) the well is flat: its fill and its
        /// hairline, with the same flat knob.
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
                Body(g, track, radius, offFill, offEdge, enabled && Palette.Depth);
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
            // 4096, from 512: the Korean catalog alone holds 567 strings that wrap, and a layout pass asks
            // for several widths of each, so the old ceiling emptied the cache during a single page and
            // every wipe re-ran the per-word measuring loop below.
            if (wrapped.Count > 4096) wrapped.Clear();
            wrapped[key] = result;
            return result;
        }

        private static readonly Dictionary<int, SolidBrush> brushes = new Dictionary<int, SolidBrush>();

        /// A brush of this colour, kept. Painting happens on one thread, and the window's lists drew two
        /// new brushes for every cell of every row on every repaint - two hundred and forty of them for
        /// one list - each allocated, used for one rectangle and thrown away. Never dispose what this
        /// returns: it belongs to the window for as long as it runs, and there are only ever as many as
        /// the palette has colours.
        internal static SolidBrush Fill(Color colour)
        {
            SolidBrush found;
            int key = colour.ToArgb();
            if (brushes.TryGetValue(key, out found)) return found;
            found = new SolidBrush(colour);
            // A theme or a High Contrast change is what ever puts a new colour in here, so this holds a
            // palette's worth. Past that they go, handles and all, rather than being left to a finaliser.
            if (brushes.Count > 256)
            {
                foreach (SolidBrush old in brushes.Values) old.Dispose();
                brushes.Clear();
            }
            brushes[key] = found;
            return found;
        }

        private static readonly Dictionary<string, Size> measured = new Dictionary<string, Size>();

        /// `TextRenderer.MeasureText`, remembered. The same label is measured several times in one layout
        /// pass - a table asks for its preferred size at width 1, at 0 and at the real width, and a page
        /// settles in up to four passes - and a Korean label is measured again every pass, because
        /// `WrapLabel` wraps the text itself and so never reaches Label's own measurement cache.
        internal static Size Measure(string text, Font font, int width, TextFormatFlags format)
        {
            if (font == null) return TextRenderer.MeasureText(text ?? "", font, new Size(width, int.MaxValue), format);
            string key = width.ToString(System.Globalization.CultureInfo.InvariantCulture) + "|" +
                         ((int)format).ToString(System.Globalization.CultureInfo.InvariantCulture) + "|" +
                         font.Name + "|" +
                         font.SizeInPoints.ToString("R", System.Globalization.CultureInfo.InvariantCulture) + "|" +
                         ((int)font.Style).ToString(System.Globalization.CultureInfo.InvariantCulture) + "|" + text;
            Size found;
            if (measured.TryGetValue(key, out found)) return found;
            found = TextRenderer.MeasureText(text ?? "", font, new Size(width, int.MaxValue), format);
            if (measured.Count > 4096) measured.Clear();
            measured[key] = found;
            return found;
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
    /// animation effects, High Contrast), in any design, nor where it cannot be seen; the change is then
    /// immediate.
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

        /// Whether `control` may animate a change now: motion is not reduced (Soft.ReduceMotion), and it is on screen - its own window visible (Soft.Shown) and every
        /// control it is in (Visible): a switch on a page or section not shown is not seen, and its change is
        /// immediate.
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
}
