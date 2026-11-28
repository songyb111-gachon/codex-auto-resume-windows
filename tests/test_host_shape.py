"""The shape rules of the Python UI, held of the C# host's surfaces (S6.4, P6-DESIGN 3.4 "source scans").

tests/test_popup_shape.py and tests/test_tray_tip_shape.py hold the popup and the icon's tooltip card to a shape by reading
the Python sources: which files there are, which of them ask Windows nothing, which names two files define, what the icon
asks of the card, what style its window has. The surfaces are C# now (gui/host.sources, `[surface]`), so the same rules
are read here from those sources through tests/guiscan.py's block finders. A rule that is about Python's own packaging -
what `__init__` re-exports, the order its imports run in - has no C# to be read in and stays with the Python test; the
ledger (tests/rustdiff/surface_ledger.json) names each such test.

Nothing here compiles or runs anything: it reads files.
"""
from __future__ import annotations

from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

import guiscan  # noqa: E402

# The files that ask Windows nothing (test_popup_shape.ASKS_WINDOWS_NOTHING: words, placement, motion, elevation, layout,
# menuplan - model is car-surface's - and test_tray_tip_shape's tipplan): the half the documentation's pictures are drawn
# by. The C runtime's maths (ucrtbase.dll, which Python's `math` calls) is the one DLL they may declare.
ASK_WINDOWS_NOTHING = ("gui/PopupWords.cs", "gui/PopupPlace.cs", "gui/PopupMotion.cs", "gui/SurfaceElevation.cs",
                       "gui/PopupLayout.cs", "gui/MenuPlan.cs", "gui/TipPlan.cs", "gui/CardPlan.cs")
WINDOWS_LIBRARIES = ("user32", "gdi32", "gdiplus", "shell32", "dwmapi", "uxtheme", "kernel32", "wtsapi32", "oleacc",
                     "ole32", "oleaut32", "advapi32", "comctl32", "shcore", "ntdll", "msimg32")


def source(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def code(text: str) -> str:
    """The text without its comments, so a rule is about what is written and not about what is said."""
    return re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", text, flags=re.S))


def host_files() -> tuple[str, ...]:
    return guiscan.host_group("surface")


class HostListTests(unittest.TestCase):
    """Twin of test_popup_shape's "the sixteen modules are all there and nothing else is"."""

    def test_every_surface_source_is_listed_once_and_is_there(self):
        listed = host_files()
        self.assertTrue(listed)
        self.assertEqual(len(set(listed)), len(listed), "a source listed twice")
        for name in listed:
            self.assertTrue((ROOT / name).is_file(), name)

    def test_no_surface_source_is_part_of_the_window(self):
        window = set(guiscan.manifest())
        self.assertEqual(sorted(set(host_files()) & window), [], "the window and the host do not share a source")

    def test_every_source_under_gui_is_in_a_list(self):
        """A file under gui/ that no compile list names is a surface that is never built, or a rule never read."""
        named = set(guiscan.manifest()) | set(host_files()) | set(guiscan.host_group("contract")) \
            | set(guiscan.host_group("generated")) | set(guiscan.SEPARATE)
        on_disk = {path.relative_to(ROOT).as_posix() for path in (ROOT / "gui").rglob("*.cs")}
        self.assertEqual(sorted(on_disk - named), [], "a C# source no list names")


class AskWindowsNothingTests(unittest.TestCase):
    """Twin of test_popup_shape's "the seven that ask Windows nothing ask it nothing" and test_tray_tip_shape's "the plan
    imports only the brand": the layout half is laid out and checked with no screen."""

    def test_the_layout_half_declares_no_windows_library_and_names_no_window_class(self):
        for name in ASK_WINDOWS_NOTHING:
            with self.subTest(name):
                text = code(source(name))
                for declared in re.findall(r'DllImport\(\s*"([^"]+)"', text):
                    self.assertNotIn(declared.lower().removesuffix(".dll"), WINDOWS_LIBRARIES, name)
                    self.assertEqual(declared.lower(), "ucrtbase.dll", "%s declares %s" % (name, declared))
                self.assertNotIn("System.Windows.Forms", text, name)
                self.assertNotIn("SurfaceNative", text, "%s reaches the win32 declarations" % name)

    def test_the_tips_plan_reads_only_the_brand(self):
        text = code(source("gui/TipPlan.cs"))
        self.assertEqual(sorted(set(re.findall(r"^using ([\w\.]+);", text, re.M))),
                         ["System", "System.Collections.Generic", "System.Text"])
        self.assertIn("Brand.", text)


class OneDefinitionTests(unittest.TestCase):
    """Twin of test_popup_shape's "no two modules define the same name"."""

    def test_no_two_sources_declare_the_same_type(self):
        owners: dict[str, list[str]] = {}
        for name in (*host_files(), *guiscan.host_group("contract")):
            text = code(source(name))
            for declared in re.findall(r"(?m)^ {4}(?:\w+ )*(?:class|struct|enum|interface) (\w+)", text):
                if re.search(r"(?m)^ {4}(?:\w+ )*partial (?:\w+ )*(?:class|struct) %s\b" % declared, text):
                    continue                  # one type written in several files, as the window's own is
                owners.setdefault(declared, []).append(name)
        self.assertEqual({declared: where for declared, where in owners.items() if len(where) > 1}, {})


class TipCardTests(unittest.TestCase):
    """Twin of tests/test_tray_tip_shape.py: the icon's tooltip card is made on a hover, asked three things, and never takes
    the focus or a click."""

    def test_the_card_is_made_by_the_icon_on_a_hover_and_by_nothing_else(self):
        users = []
        for name in host_files():
            if name == "gui/TipCard.cs":
                continue
            if re.search(r"\bnew TipCard\(", code(source(name))):
                users.append(name)
        # The icon, on a hover - and the probe mode's own case (SurfaceRenderWindows.cs), which makes the card unshown
        # for the tests that drive it: the one other place, and never on the product's path.
        self.assertEqual(users, ["gui/TrayIcon.cs", "gui/SurfaceRenderWindows.cs"])
        icon = code(source("gui/TrayIcon.cs"))
        # S6.3e: made by the icon's maker (MakeTipCard, whose live default MakeLiveTip is the one `new TipCard(`), which the
        # hover's own path calls only when no card is held yet - nothing else calls it
        maker = icon.index("private static ITrayTip MakeLiveTip(")
        self.assertEqual(icon.count("new TipCard("), 1)
        self.assertGreater(icon.index("new TipCard("), maker)
        self.assertLess(icon.index("new TipCard("), icon.index("\n        }", maker))
        self.assertEqual(re.findall(r"\bMakeLiveTip\b", icon), ["MakeLiveTip", "MakeLiveTip"], "the default, and itself")
        self.assertIn("MakeTipCard = MakeLiveTip;", icon)
        self.assertEqual(icon.count("MakeTipCard("), 1, "called in one place")
        at = icon.index("MakeTipCard(")
        self.assertIn("if (Tip == null)", icon[max(0, at - 400):at])
        self.assertIn("Tip.Show(IconRectReader, point)", icon[at:at + 600])

    def test_the_cards_window_never_takes_the_focus_or_a_click(self):
        text = code(source("gui/TipCard.cs"))
        style = re.search(r"internal const uint TipStyle\s*=\s*(.*?);", text, re.S)
        self.assertIsNotNone(style)
        for flag in ("WS_EX_LAYERED", "WS_EX_NOACTIVATE", "WS_EX_TRANSPARENT"):
            self.assertIn(flag, style.group(1))

    def test_what_the_icon_asks_of_the_card(self):
        body = guiscan.type_body("TipSurface", source("gui/TrayIcon.cs"))
        asked = set(re.findall(r"\bcard\.(\w+)\(", body))
        self.assertEqual(asked, {"Show", "Hide", "Dispose"})

    def test_the_cards_numbers_are_the_plans(self):
        text = code(source("gui/TipPlan.cs"))
        self.assertRegex(text, r"internal const int TipMost = 360;")
        self.assertRegex(text, r"internal const int TipGap = 8;")
        self.assertNotIn("TipWidth", text)


class MenuFallbackTests(unittest.TestCase):
    """Twin of tests/test_tray_menu_fallbacks.py's "every fallback of the menu is the English sentence": a menu built with no
    words says what the English catalog says, for every key it writes a literal for (gui/TrayMenu.cs `Say(strings, key,
    fallback)` and `PowerOffWords`)."""

    def test_every_fallback_of_the_menu_is_the_english_sentence(self):
        from codex_auto_resume import l10n
        english = l10n.catalog("en")
        text = code(source("gui/TrayMenu.cs"))
        literal = r'"((?:[^"\\\r\n]|\\.)*)"'
        found = re.findall(r'Say\(strings,\s*"([\w.\-]+)"\s*,\s*%s\s*\)' % literal, text)
        self.assertGreaterEqual(len(found), 6)
        for key, said in found:
            with self.subTest(key=key):
                self.assertEqual(said, english[key])
        words = re.search(r"PowerOffWords = new Dictionary<string, string> \{(.*?)\};", text, re.S)
        self.assertIsNotNone(words)
        pairs = re.findall(r'\{\s*"(\w+)"\s*,\s*"((?:[^"\\]|\\.)*)"\s*\}', words.group(1))
        self.assertEqual({word for word, _ in pairs}, {"sleep", "hibernate", "shut_down"})
        for word, said in pairs:
            with self.subTest(power=word):
                self.assertEqual(said, english["menu.power_off." + word])


def written(name: str) -> str:
    """A source's code: no comment, no string - what its names and calls are."""
    return re.sub(r'"(?:[^"\\\n]|\\.)*"', '""', code(source(name)))


def surfaces() -> tuple[str, ...]:
    return (*guiscan.host_group("contract"), *host_files())


class ReachTests(unittest.TestCase):
    """Twin of test_tray_popup.SafetyTests: what the surfaces can reach is what their source says they can reach. They send,
    submit and queue nothing (only the watcher sends: they post actions through the host's closed table), drive nobody else's
    window and open no connection."""

    # The names that match "send|submit|queue|dispatch|backend|engine" and are not a send: the message pump's own call, the
    # COM interface id MSAA's IDispatch needs, the thread pool's work item (a surface's off-thread work is not a queue of
    # recoveries), the probe's stand-in for a window message, and the end of a word.
    NOT_SENDS = {"DispatchMessageW", "IidDispatch", "QueueUserWorkItem", "SendMessageW", "wordsEnd"}

    def test_no_name_in_them_sends_submits_or_queues(self):
        offenders = {}
        for name in surfaces():
            for word in set(re.findall(r"\b\w+\b", written(name))):
                if re.search(r"send|submit|queue|dispatch|backend|engine", word, re.I) and word not in self.NOT_SENDS:
                    offenders.setdefault(word, []).append(name)
        self.assertEqual(offenders, {})

    def test_they_drive_nobody_else_s_window_and_open_no_connection(self):
        forbidden = re.compile(r"\bSendInput\b|\bkeybd_event\b|\bmouse_event\b|\bSetCursorPos\b|\bPrintWindow\b|\bBitBlt\b|"
                               r"\bProcess\.Start\b|\bProcessStartInfo\b|System\.Net|\bSocket\b|\bHttpClient\b|\bWebClient\b|"
                               r"\bAccessibleObjectFromWindow\b|\bUIAutomation\w*\b")
        for name in surfaces():
            with self.subTest(name):
                self.assertEqual(forbidden.findall(written(name)), [])
        # Explorer's overflow flyout is asked of, never driven (tray_place.py's rule): FindWindow is the icon's placement alone.
        for name in surfaces():
            if name not in ("gui/TrayPlace.cs", "gui/SurfaceRenderWindows.cs"):
                with self.subTest(name):
                    self.assertEqual(re.findall(r"\bFindWindow\w*\b", written(name)), [])

    def test_they_use_nothing_that_can_submit(self):
        allowed = {"Microsoft.Win32", "System", "System.Collections", "System.Collections.Generic", "System.Drawing",
                   "System.Globalization", "System.IO", "System.Runtime.InteropServices", "System.Security.Cryptography",
                   "System.Text", "System.Text.RegularExpressions", "System.Threading"}
        used = {}
        for name in surfaces():
            for namespace in re.findall(r"(?m)^using ([\w\.]+);", code(source(name))):
                used.setdefault(namespace, []).append(name)
        self.assertEqual(sorted(set(used) - allowed), [])


def rust(name: str) -> str:
    """A Rust source of the port, without its comments."""
    text = (ROOT / "rust" / name).read_text(encoding="utf-8")
    return re.sub(r"//[^\n]*", "", text)


def rust_words(text: str, constant: str) -> tuple[str, ...]:
    """The words of `pub const <constant>: [&str; N] = [...]`, in order."""
    found = re.search(r"pub const %s: \[&str; (\d+)\] = \[(.*?)\];" % constant, text, re.S)
    if found is None:
        raise AssertionError("no %s in the source" % constant)
    words = tuple(re.findall(r'"([^"\\]*)"', found.group(2)))
    if len(words) != int(found.group(1)):
        raise AssertionError("%s says %s words and has %d" % (constant, found.group(1), len(words)))
    return words


class EditionTwinTests(unittest.TestCase):
    """Twins of tests/test_edition_label.py's rules that name the icon's unnamed edition (`tray.UNNAMED_EDITION`) or read
    the Python icon's source: the panel's heading and the Dashboard's version line name no edition where the host's icon
    names none (gui/TrayWords.cs `UnnamedEdition`), and the watcher hands the host's icon the edition that runs, which every
    tooltip it makes is given."""

    @staticmethod
    def unnamed() -> str:
        found = re.search(r'internal const string UnnamedEdition = "([^"]*)";', code(source("gui/TrayWords.cs")))
        if found is None:
            raise AssertionError("gui/TrayWords.cs has no UnnamedEdition")
        return found.group(1)

    def test_the_hosts_unnamed_edition_is_the_standard_edition_the_core_shows(self):
        from codex_auto_resume import edition
        from codex_auto_resume.domain.plug import NULL, Edition
        self.assertEqual(self.unnamed(), str(Edition.STANDARD))
        self.assertEqual(edition.shown(NULL), self.unnamed())

    def test_the_panels_heading_names_no_edition_where_the_hosts_icon_names_none(self):
        script = source("src/codex_auto_resume/mcp/assets/panel.js")
        heading = script[script.index("function renderHero("):]
        heading = heading[:heading.index("var line = ")]
        self.assertIn("var named = status.edition && status.edition !== '%s';" % self.unnamed(), heading)
        self.assertIn("if (named) eyebrow.appendChild(element('span', 'edition', "
                      "t('edition.' + status.edition, status.edition)));", heading)

    def test_the_dashboards_version_line_names_no_edition_where_the_hosts_icon_names_none(self):
        window = guiscan.whole()
        method = guiscan.member_body("SettingsForm", "ShowVersion")
        self.assertIn('private const string UnnamedEdition = "%s";' % self.unnamed(), window)
        self.assertIn("bool named = !string.IsNullOrEmpty(edition) && edition != UnnamedEdition;", method)
        self.assertIn('named ? S("edition." + edition, edition) : null', method)

    def test_the_watcher_hands_the_hosts_icon_the_edition_that_runs(self):
        """Twin of TooltipTests.test_the_watcher_hands_its_icon_the_edition_that_runs: the core's surfaces event carries
        `edition.shown(plug)`, the host's pump hands it to the icon, and every tooltip the icon makes is given it."""
        app = rust("crates/car-watcher/src/app.rs")
        self.assertIn("let edition = car_policy::plug::edition::shown(&self.plug);", app)
        events = rust("crates/car-watcher/src/events.rs")
        self.assertIn('("edition", Value::from(edition)),', events)
        self.assertIn('Edition = Text(found, "edition"),', code(source("gui/HostPump.cs")))
        self.assertIn("tray.Edition = surfaces.Edition;", code(source("gui/HostSurfaces.cs")))
        icon = code(source("gui/TrayIcon.cs"))
        calls = icon.count("TrayWords.Tooltip(") + icon.count("TrayWords.TooltipParts(")
        self.assertGreaterEqual(calls, 2)
        self.assertEqual(calls, icon.count("Now(), Edition)"))
        self.assertEqual(icon.count("TrayWords.TooltipParts("), 1)


class VocabularyTwinTests(unittest.TestCase):
    """Twin of tests/test_vocabulary.py's three UI lists (ListTests' frozen members, HomeTests' homes and the attention
    overlays beside `Overlay`): the port's own lists - car-surface's popup model (STATES, ATTENTION_OVERLAYS) and the
    host's icon (gui/TrayMotion.cs IconStates) - have the members the Python UI's had, by the same digest."""

    def test_the_ports_lists_are_the_vocabularys(self):
        import test_vocabulary as vocabulary
        v = vocabulary.v
        model = rust("crates/car-surface/src/popup/model.rs")
        icon = re.search(r"internal static readonly string\[\] IconStates = \{(.*?)\};", code(source("gui/TrayMotion.cs")),
                         re.S)
        self.assertIsNotNone(icon)
        port = {"ui.tray.ICON_STATES": tuple(re.findall(r'"([^"\\]*)"', icon.group(1))),
                "ui.popup.STATES": rust_words(model, "STATES"),
                "ui.popup.ATTENTION_OVERLAYS": frozenset(rust_words(model, "ATTENTION_OVERLAYS"))}
        for name, value in port.items():
            with self.subTest(name):
                kind, members = vocabulary.shape(value)
                self.assertEqual((kind, len(value), vocabulary.digest(members)), vocabulary.LISTS[name],
                                 "its members are now %s" % sorted(members))
        self.assertEqual(port["ui.popup.STATES"], tuple(v.ActivityState))
        self.assertEqual(port["ui.tray.ICON_STATES"], tuple(v.IconState))
        self.assertLessEqual(port["ui.popup.ATTENTION_OVERLAYS"], set(v.Overlay))


class HandoverTwinTests(unittest.TestCase):
    """Twin of tests/test_tray_reuses_window.py WindowSideTests' "the mark and the answer are the same on both sides": the
    Dashboard's WM_COPYDATA mark and answer are the ones the port's hand-over (car-platform/src/handover.rs) sends and
    takes, as they were win/handover.py's."""

    def test_the_mark_and_the_answer_are_the_same_on_both_sides(self):
        window = guiscan.type_body("SettingsForm", "gui/WindowReopen.cs")
        handover = rust("crates/car-platform/src/handover.rs")

        def constant(name):
            found = re.search(r"internal const (?:int|long) %s = (0x[0-9A-Fa-f]+);" % name, window)
            self.assertIsNotNone(found, name)
            return int(found.group(1), 16)

        def port(name):
            found = re.search(r"pub const %s: usize = (0x[0-9A-Fa-f_]+);" % name, handover)
            self.assertIsNotNone(found, name)
            return int(found.group(1).replace("_", ""), 16)

        self.assertEqual(constant("OpenRequestMark"), port("OPEN_REQUEST_MARK"))
        self.assertEqual(constant("OpenRequestTaken"), port("OPEN_REQUEST_TAKEN"))
        # WM_COPYDATA is Windows' own number; the port takes it from the Windows bindings by name and sends under it.
        self.assertEqual(constant("WM_COPYDATA"), 0x004A)
        self.assertRegex(handover, r"\bWM_COPYDATA\b,")
        self.assertIn("dwData: OPEN_REQUEST_MARK,", handover)
        self.assertIn("answer == OPEN_REQUEST_TAKEN", handover)


if __name__ == "__main__":
    unittest.main()
