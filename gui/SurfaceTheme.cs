// Codex Auto Resume - light or dark, the design, motion or none, the text size, and the colours High Contrast takes
// over (v0.6.27, S6.3).
//
// The C# port of src/codex_auto_resume/ui/popup/theme.py, call for call: the stored Theme, Design and Reduce motion the
// surfaces adopt (adopt_settings), what they resolve to (theme_choice, effective_theme, appearance, design_choice), and
// the four questions put to Windows - the app mode, Reduce motion's animation effects, High Contrast and the system
// colours - with the text size of win/textsize.py. Each is asked once and adopted: a surface never decides its own
// appearance while it is open.
//
// It also holds what the surfaces read of brand by a token's name (brand.palette(theme, design)[token]) and brand's
// colour arithmetic (brand/colour.py: rgb, mix, luminance), so a colour is resolved here as the Python resolves it.
using System;
using System.Collections.Generic;
using System.Drawing;
using System.Globalization;
using System.Runtime.InteropServices;

namespace CodexAutoResume
{
    internal static class SurfaceTheme
    {
        internal const string ThemeSystem = "system";
        internal static readonly string[] Themes = { "light", "dark" };
        internal static readonly string[] Designs = { "soft", "classic", "plain" };

        /// The system colour index Windows Forms names each High Contrast colour by (SYSTEM_COLOURS).
        internal static int SystemIndex(string name)
        {
            switch (name)
            {
                case "Window": return 5;
                case "WindowFrame": return 6;
                case "WindowText": return 8;
                case "Highlight": return 13;
                case "HighlightText": return 14;
                case "Control": return 15;
                case "GrayText": return 17;
            }
            throw new KeyNotFoundException(name);
        }

        /// The system colour a brand token is drawn in while High Contrast is on (contrast_colour); "WindowText" for
        /// any other token.
        internal static string ContrastColour(string token)
        {
            switch (token)
            {
                case "ink": return "WindowText";
                case "muted": return "GrayText";
                case "line": return "WindowFrame";
                case "surface": return "Window";
                case "canvas": return "Control";
                case "raised": return "Window";
                case "inset": return "Window";
                case "shadow_dark": return "WindowFrame";
                case "shadow_light": return "Window";
                case "accent": case "accent_hover": case "accent_pressed": case "accent_soft": return "Highlight";
                case "on_accent": return "HighlightText";
                case "focus": return "WindowText";
                case "active": return "Highlight";
                case "idle": return "GrayText";
                case "attention": case "success": case "waiting": case "warning": case "danger": return "WindowText";
                case "paused": return "GrayText";
            }
            return "WindowText";
        }

        /// The stored choice as "system", "light" or "dark"; anything else is "system" (theme_choice).
        internal static string ThemeChoice(object value)
        {
            string text = value as string;
            return text == ThemeSystem || text == "light" || text == "dark" ? text : ThemeSystem;
        }

        /// "light" or "dark": a choice of either, or for "system" what Windows' app mode says, only an explicit dark
        /// being dark (effective_theme).
        internal static string EffectiveTheme(object choice, bool? appsUseLight)
        {
            string chosen = ThemeChoice(choice);
            if (chosen != ThemeSystem) return chosen;
            return appsUseLight == false ? "dark" : "light";
        }

        /// What a surface draws with: "contrast" whenever High Contrast is on, else the theme (appearance).
        internal static string Appearance(object choice, bool? appsUseLight, bool contrast)
        {
            return contrast ? "contrast" : EffectiveTheme(choice, appsUseLight);
        }

        /// The stored design as one of the designs; anything else is Soft (design_choice).
        internal static string DesignChoice(object value)
        {
            string text = value as string;
            return Array.IndexOf(Designs, text) >= 0 ? text : Brand.DesignDefault;
        }

        // ------------------------------------------------------------------ what the surfaces adopt
        private static bool reduceMotionSetting;
        private static string themeSetting = ThemeSystem;
        private static string designSetting = Brand.DesignDefault;

        internal static void SetReduceMotion(object value) { reduceMotionSetting = value is bool && (bool)value; }
        internal static void SetTheme(object value) { themeSetting = ThemeChoice(value); }
        internal static string ThemeSetting { get { return themeSetting; } }
        internal static void SetDesign(object value) { designSetting = DesignChoice(value); }
        internal static string DesignSetting { get { return designSetting; } }
        internal static bool ReduceMotionSetting { get { return reduceMotionSetting; } }

        /// Take up the stored Theme, Design and Reduce motion from a settings dictionary; anything else is ignored
        /// (adopt_settings). A value that is not a dictionary changes nothing.
        internal static void AdoptSettings(object values)
        {
            var map = values as Dictionary<string, object>;
            if (map == null) return;
            object value;
            SetTheme(map.TryGetValue("theme", out value) ? value : null);
            SetDesign(map.TryGetValue("design", out value) ? value : null);
            SetReduceMotion(map.TryGetValue("reduce_motion", out value) ? value : null);
        }

        // ------------------------------------------------------------------ Windows' answers
        internal const string PersonalizeKey = "Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize";
        internal const string AppModeValue = "AppsUseLightTheme";

        /// Windows' app mode: true for light, false for dark, null when Windows does not say (apps_use_light_theme).
        internal static bool? AppsUseLightTheme()
        {
            try
            {
                uint data = 0, size = 4;
                int status = SurfaceNative.RegGetValueW(SurfaceNative.HKEY_CURRENT_USER, PersonalizeKey, AppModeValue,
                                                        SurfaceNative.RRF_RT_REG_DWORD, IntPtr.Zero, ref data, ref size);
                if (status != 0) return null;
                return data != 0;
            }
            catch (Exception)
            {
                return null;
            }
        }

        /// True when Windows, or this product's Reduce motion setting, asks for fewer animations (reduced_motion).
        internal static bool ReducedMotion()
        {
            if (reduceMotionSetting) return true;
            try
            {
                int value = 1;
                if (!SurfaceNative.SystemParametersInfoBool(SurfaceNative.SPI_GETCLIENTAREAANIMATION, 0, ref value, 0)) return false;
                return value == 0;
            }
            catch (Exception)
            {
                return false;
            }
        }

        /// True while Windows' High Contrast is on (high_contrast).
        internal static bool HighContrast()
        {
            try
            {
                var info = new SurfaceNative.HIGHCONTRASTW();
                info.CbSize = (uint)Marshal.SizeOf(typeof(SurfaceNative.HIGHCONTRASTW));
                if (!SurfaceNative.SystemParametersInfoContrast(SurfaceNative.SPI_GETHIGHCONTRAST, info.CbSize, ref info, 0))
                    return false;
                return (info.DwFlags & SurfaceNative.HCF_HIGHCONTRASTON) != 0;
            }
            catch (Exception)
            {
                return false;
            }
        }

        /// A system colour, by the name Windows Forms gives it, as (red, green, blue) (system_rgb).
        internal static int[] SystemRgb(string name)
        {
            uint value = SurfaceNative.GetSysColor(SystemIndex(name));
            return new[] { (int)(value & 0xFF), (int)((value >> 8) & 0xFF), (int)((value >> 16) & 0xFF) };
        }

        private const string AccessibilityKey = "Software\\Microsoft\\Accessibility";
        private const string TextScaleValue = "TextScaleFactor";

        /// Windows' text size, "Make text bigger", as a factor from 1 to 2.25 (text_scale, win/textsize.read): the
        /// percentage stored under Accessibility, 100 to 225, anything else or nothing at all 1.
        internal static double TextScale()
        {
            try
            {
                uint data = 0, size = 4;
                int status = SurfaceNative.RegGetValueW(SurfaceNative.HKEY_CURRENT_USER, AccessibilityKey, TextScaleValue,
                                                        SurfaceNative.RRF_RT_REG_DWORD, IntPtr.Zero, ref data, ref size);
                if (status != 0 || data < 100 || data > 225) return 1.0;
                return data / 100.0;
            }
            catch (Exception)
            {
                return 1.0;
            }
        }

        /// The text size a surface draws at (textsize.fitting): `text`, but no larger than lets what it needs at the
        /// usual size grow into the room it has, and never below 1.
        internal static double Fitting(double text, double[] needs, double[] room)
        {
            double size = text > 1.0 ? text : 1.0;
            for (int i = 0; i < Math.Min(needs.Length, room.Length); i++)
                if (needs[i] > 0 && room[i] > 0) size = Math.Min(size, room[i] / needs[i]);
            return Math.Max(1.0, size);
        }

        // ------------------------------------------------------------------ brand, by a token's name

        /// brand.palette(theme, design)[token] as the colour it names: the design's look in that theme.
        internal static Color Token(string token, string theme, string design)
        {
            Brand.Look look = Brand.LookOf(DesignChoice(design), theme == "dark");
            switch (token)
            {
                case "ink": return look.Ink;
                case "muted": return look.Muted;
                case "line": return look.Line;
                case "surface": return look.Surface;
                case "canvas": return look.Canvas;
                case "accent": return look.Accent;
                case "on_accent": return look.OnAccent;
                case "active": return look.Active;
                case "idle": return look.Idle;
                case "raised": return look.Raised;
                case "inset": return look.Inset;
                case "shadow_dark": return look.ShadowDark;
                case "shadow_light": return look.ShadowLight;
                case "accent_soft": return look.AccentSoft;
                case "focus": return look.Focus;
                case "attention": return look.Attention;
                case "success": return look.Success;
                case "waiting": return look.Waiting;
                case "warning": return look.Warning;
                case "danger": return look.Danger;
                case "paused": return look.Paused;
                case "accent_hover": return look.AccentHover;
                case "accent_pressed": return look.AccentPressed;
            }
            throw new KeyNotFoundException("no token " + token);
        }

        /// #RRGGBB, as brand writes a colour.
        internal static string Hex(Color colour)
        {
            return string.Format(CultureInfo.InvariantCulture, "#{0:X2}{1:X2}{2:X2}", colour.R, colour.G, colour.B);
        }

        /// A colour as brand.rgb reads #RRGGBB: (red, green, blue).
        internal static int[] Rgb(Color colour)
        {
            return new[] { (int)colour.R, colour.G, colour.B };
        }

        private static double Channel(int value)
        {
            double part = value / 255.0;
            return part <= 0.04045 ? part / 12.92 : SurfaceMath.Pow((part + 0.055) / 1.055, 2.4);
        }

        /// WCAG's relative luminance (brand.luminance).
        internal static double Luminance(Color colour)
        {
            return 0.2126 * Channel(colour.R) + 0.7152 * Channel(colour.G) + 0.0722 * Channel(colour.B);
        }

        /// `one` moved `amount` of the way toward `other`, per channel, rounded half up (brand.mix).
        internal static Color Mix(Color one, Color other, double amount)
        {
            Func<int, int, int> toward = (a, b) => (int)Math.Floor(a + (b - a) * amount + 0.5);
            return Color.FromArgb(toward(one.R, other.R), toward(one.G, other.G), toward(one.B, other.B));
        }
    }
}
