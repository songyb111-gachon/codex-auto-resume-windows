"""Right to left: the popup, the notification card and the panel mirror in Arabic and Hebrew (v0.6.11).

Arabic and Hebrew are translated and held (l10n.HELD): offered once every surface mirrors fully and the
window's layout audit passes right to left at every scaling. Three of the four surfaces mirror from this
release, and are held to it here; the window does not yet, so the two stay held (and no person reaches any
of this - these tests do, by asking for the two languages directly).

* **What mirrors.** Everything that stands to one side stands to the other: the light and the product, a
  row's name and chip, the switch under the chip, the first of two buttons, the three counts, a switch's
  knob, Classic's accent bar, a drop-down's wedge, a folded section's chevron, the paddings that are wider
  on one side. Every line is aligned to the right and read right to left.
* **What does not.** The brand's light falls from the top left on every surface in every language: the
  lift under a card is the room's light, not the reading direction, so a shadow is not mirrored. A check
  mark is a mark, not an arrow.
* **Mixed directions.** A value set into a sentence - a version, a path, an id - stays one run in its own
  direction. The panel's browser isolates it (FSI ... PDI). GDI draws an isolate as a box (measured here),
  so the popup and the card embed it instead (LRE or RLE ... PDF, l10n.embedded). A conversation's name is
  read in its own direction on every surface.

The popup's and the card's mirroring is a plan mirrored (popup.mirror), so it is checked against the plan
laid out left to right, and then drawn - with the words left out - to be the same picture flipped. The
panel is laid out by a real browser (headless Edge, where it is installed) twice, right to left and with the
direction taken off, and every box, every line of words and every drawn piece is where the other's mirror
image puts it.
"""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import html as html_text
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from codex_auto_resume import brand, l10n, notice_card, notify  # noqa: E402
from codex_auto_resume.mcp import panel as mcpui  # noqa: E402
from codex_auto_resume.ui import popup  # noqa: E402
from codex_auto_resume.ui.popup import win32 as popup_win32  # noqa: E402

RTL = sorted(l10n.RIGHT_TO_LEFT)
THREAD = "0a1b2c3d-0001-7000-8000-000000000001"
SCALES = (1.0, 1.25, 1.5, 1.75, 2.0)


def across(rect, width):
    left, top, right, bottom = rect
    return (width - right, top, width - left, bottom)


# ------------------------------------------------------------------------------------------ the language
class DirectionTests(unittest.TestCase):
    def test_arabic_and_hebrew_are_the_right_to_left_catalogs_and_still_held(self):
        self.assertEqual(l10n.RIGHT_TO_LEFT, frozenset({"ar", "he"}))
        self.assertLessEqual(l10n.RIGHT_TO_LEFT, set(l10n.LOCALES))
        # The window does not mirror yet, so neither is offered (docs: every surface, or not at all).
        self.assertLessEqual(l10n.RIGHT_TO_LEFT, l10n.HELD)
        for locale in l10n.LOCALES:
            self.assertEqual(l10n.right_to_left(locale), locale in ("ar", "he"))
        self.assertFalse(l10n.right_to_left(None))

    def test_a_value_s_direction_is_its_first_strong_character(self):
        self.assertEqual(l10n.first_strong("Fix the build"), "L")
        self.assertEqual(l10n.first_strong("12 مهمة"), "R")
        self.assertEqual(l10n.first_strong("עברית"), "R")
        self.assertEqual(l10n.first_strong("0.6.11 - 3:05"), None)
        self.assertEqual(l10n.first_strong(""), None)

    def test_a_value_is_embedded_in_a_right_to_left_sentence_and_left_alone_in_any_other(self):
        for locale in l10n.LOCALES:
            for value in (THREAD, "0.6.11-alpha.2", "C:\\Users\\example\\repo", "مشروع", "12"):
                embedded = l10n.embedded(value, locale)
                with self.subTest(locale=locale, value=value):
                    if l10n.right_to_left(locale):
                        mark = "\u202b" if l10n.first_strong(value) == "R" else "\u202a"
                        self.assertEqual(embedded, mark + value + "\u202c")
                    else:
                        self.assertEqual(embedded, value)
        self.assertEqual(l10n.embedded("", "ar"), "")

    @unittest.skipUnless(os.name == "nt", "GDI")
    def test_gdi_draws_an_embedding_as_nothing_and_an_isolate_as_a_box(self):
        """Why the popup and the card embed where the panel isolates: measured, GDI gives U+2066-2069 a width -
        the box of a character it does not know - and the embedding marks none."""
        gdi32, user32 = C.WinDLL("gdi32"), C.WinDLL("user32")
        gdi32.CreateCompatibleDC.restype, gdi32.CreateCompatibleDC.argtypes = W.HDC, [W.HDC]
        gdi32.CreateFontW.restype = W.HFONT
        gdi32.CreateFontW.argtypes = [C.c_int] * 5 + [W.DWORD] * 8 + [W.LPCWSTR]
        gdi32.SelectObject.restype, gdi32.SelectObject.argtypes = W.HGDIOBJ, [W.HDC, W.HGDIOBJ]
        gdi32.DeleteObject.argtypes, gdi32.DeleteDC.argtypes = [W.HGDIOBJ], [W.HDC]
        user32.DrawTextW.argtypes = [W.HDC, W.LPCWSTR, C.c_int, C.POINTER(W.RECT), W.UINT]
        dc = gdi32.CreateCompatibleDC(None)
        font = gdi32.CreateFontW(-40, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 5, 0, "Segoe UI")
        gdi32.SelectObject(dc, font)
        try:
            def width(text):
                rect = W.RECT(0, 0, 4000, 0)
                user32.DrawTextW(dc, text, -1, C.byref(rect), 0x400 | 0x20 | 0x800)   # CALCRECT, SINGLELINE
                return rect.right
            plain = width("abc")
            self.assertEqual(width("a\u202ab\u202cc"), plain)
            self.assertEqual(width("a\u202bb\u202cc"), plain)
            self.assertGreater(width("a\u2068b\u2069c"), plain)
        finally:
            gdi32.DeleteObject(font)
            gdi32.DeleteDC(dc)


# ------------------------------------------------------------------------------------------ the popup
@unittest.skipUnless(os.name == "nt", "measured and drawn by GDI")
class PopupMirrorTests(unittest.TestCase):
    def setUp(self):
        from test_words_fit import popup_views
        self.views = popup_views
        self.renderer = popup.Renderer()
        self.addCleanup(self.renderer.close)

    def laid(self, vm, scale, locale):
        """The plan as drawn, and the same view laid out left to right in the same fonts."""
        drawn = self.renderer.layout(vm, scale, locale)
        return drawn, popup.layout(vm, scale, self.renderer.measure)

    def test_right_to_left_every_rectangle_is_across_the_popup_from_where_it_is_left_to_right(self):
        for locale in RTL:
            for scale in SCALES:
                for vm in self.views(l10n.catalog(locale))[:2]:
                    drawn, ltr = self.laid(vm, scale, locale)
                    width = ltr["size"][0]
                    with self.subTest(locale=locale, scale=scale):
                        self.assertTrue(drawn["rtl"])
                        self.assertEqual(drawn["size"], ltr["size"])
                        self.assertEqual(drawn["card"], across(ltr["card"], width))
                        self.assertEqual(len(drawn["items"]), len(ltr["items"]))
                        for mirrored, item in zip(drawn["items"], ltr["items"]):
                            self.assertEqual(mirrored["kind"], item["kind"])
                            self.assertTrue(mirrored["mirrored"])
                            if "rect" in item:
                                self.assertEqual(mirrored["rect"], across(item["rect"], width))
                            if "cx" in item:
                                self.assertEqual(mirrored["cx"], width - item["cx"])
                            if item["kind"] == "text":
                                self.assertEqual(mirrored["align"],
                                                 {"left": "right"}.get(item["align"], item["align"]))
                        self.assertEqual(drawn["targets"], [(t, across(r, width)) for t, r in ltr["targets"]])
                        self.assertEqual(drawn["rows"], [(k, across(r, width)) for k, r in ltr["rows"]])

    def test_right_to_left_the_light_the_switch_and_the_first_button_are_on_the_other_side(self):
        vm = self.views(l10n.catalog("ar"))[0]
        plan = self.renderer.layout(vm, 1.0, "ar")
        items = plan["items"]
        halo = next(item for item in items if item["kind"] == "halo")
        title = next(item for item in items if item["kind"] == "text" and item["role"] == "title")
        self.assertGreater(halo["cx"], title["rect"][2], "the light at the right of the product")
        for switch in (item for item in items if item["kind"] == "switch"):
            label = next(item for item in items if item.get("target") == switch["target"] and item["kind"] == "text")
            self.assertLess(switch["rect"][2], label["rect"][0], "the switch at the left of its label")
        buttons = [item["rect"] for item in items if item["kind"] == "button"]
        if buttons[0][1] == buttons[1][1]:                          # side by side
            self.assertGreater(buttons[0][0], buttons[1][0], "Pause at the right, Open Dashboard at the left")

    def test_left_to_right_nothing_is_mirrored(self):
        for locale in l10n.LOCALES:
            if l10n.right_to_left(locale):
                continue
            vm = self.views(l10n.catalog(locale))[0]
            drawn, ltr = self.laid(vm, 1.25, locale)
            with self.subTest(locale=locale):
                self.assertEqual(drawn, ltr)
                self.assertNotIn("rtl", drawn)

    def pixels(self, vm, plan, design, theme):
        self.renderer.design, self.renderer.theme, self.renderer.contrast = design, theme, False
        with patch.object(self.renderer, "_text", lambda *unused: None):
            canvas = self.renderer.draw(vm, plan, frame=None)
            return bytes(canvas.pixels()), plan["size"]

    def test_drawn_without_its_words_the_popup_is_its_left_to_right_picture_flipped(self):
        """Classic and Plain, the designs with no light to keep: every tile, well, rule, chip, switch - knob and
        all - button, the light's dot and Classic's accent bar, flipped. Soft keeps the brand's light from the
        top left (module docstring), and its lift is the one thing that differs. Flipped to within GDI+'s
        anti-aliasing, which does not give a curve and its mirror image quite the same coverage (measured: at
        most a quarter of a channel, on the edge of a corner or a circle); a piece on the wrong side, a knob at
        the wrong end or a missing bar is a whole channel off."""
        for locale in RTL:
            vm = self.views(l10n.catalog(locale))[1]
            for design in ("classic", "plain"):
                for theme in ("light", "dark"):
                    for scale in (1.0, 1.5):
                        drawn, ltr = self.laid(vm, scale, locale)
                        right, (width, height) = self.pixels(vm, drawn, design, theme)
                        left, _ = self.pixels(vm, ltr, design, theme)
                        worst = 0
                        for y in range(height):
                            row = left[y * width * 4:(y + 1) * width * 4]
                            flipped = b"".join(row[x * 4:x * 4 + 4] for x in range(width - 1, -1, -1))
                            mirrored = right[y * width * 4:(y + 1) * width * 4]
                            if flipped != mirrored:
                                worst = max(worst, max(abs(a - b) for a, b in zip(flipped, mirrored)))
                        with self.subTest(locale=locale, design=design, theme=theme, scale=scale):
                            self.assertLess(worst, 64)

    def test_the_flip_check_sees_a_knob_at_the_wrong_end(self):
        """So a quiet report is the check having looked: one switch drawn unmirrored is a whole channel off."""
        vm = self.views(l10n.catalog("ar"))[1]
        drawn, ltr = self.laid(vm, 1.0, "ar")
        switch = next(item for item in drawn["items"] if item["kind"] == "switch")
        switch["mirrored"] = False
        right, (width, height) = self.pixels(vm, drawn, "plain", "light")
        left, _ = self.pixels(vm, ltr, "plain", "light")
        worst = 0
        for y in range(switch["rect"][1], switch["rect"][3]):
            for x in range(switch["rect"][0], switch["rect"][2]):
                one = right[(y * width + x) * 4:(y * width + x) * 4 + 3]
                two = left[(y * width + width - 1 - x) * 4:(y * width + width - 1 - x) * 4 + 3]
                worst = max(worst, max(abs(a - b) for a, b in zip(one, two)))
        self.assertGreaterEqual(worst, 64)

    def test_the_accent_bar_is_inside_the_right_hairline(self):
        vm = self.views(l10n.catalog("he"))[0]
        drawn, _ = self.laid(vm, 1.0, "he")
        picture, (width, height) = self.pixels(vm, drawn, "classic", "light")
        card = drawn["card"]
        y = (card[1] + card[3]) // 2
        accent = brand.rgb(brand.palette("light", "classic")["accent"])

        def at(x):
            b, g, r = picture[(y * width + x) * 4:(y * width + x) * 4 + 3]
            return (r, g, b)
        self.assertEqual(at(card[2] - 2), accent)
        self.assertNotEqual(at(card[0] + 2), accent)

    def test_every_line_is_aligned_right_and_read_right_to_left_but_a_name_in_its_own_direction(self):
        seen = []
        user32 = popup_win32._dll("user32")
        original = user32.DrawTextW

        def record(dc, text, count, rect, flags):
            seen.append((text, flags))
            return original(dc, text, count, rect, flags)
        vm = self.views(l10n.catalog("ar"))[0]
        vm["tasks"][1]["name"] = "مهمة طويلة"
        for locale in ("ar", "en"):
            plan = self.renderer.layout(vm, 1.0, locale)
            del seen[:]
            with patch.object(user32, "DrawTextW", record):
                self.renderer.draw(vm, plan, frame=None)
            texts = {item["text"]: item for item in plan["items"] if item["kind"] == "text"}
            self.assertEqual(len(seen), sum(1 for item in plan["items"] if item["kind"] == "text"))
            for text, flags in seen:
                item = texts[text]
                rtl_reading = bool(flags & popup_win32.DT_RTLREADING)
                right = bool(flags & popup_win32.DT_RIGHT)
                with self.subTest(locale=locale, text=text):
                    if locale == "en":
                        self.assertFalse(rtl_reading or right, "left to right is drawn as it always was")
                    else:
                        self.assertEqual(right, item["align"] == "right")
                        self.assertNotEqual(item["align"], "left")
                        own = item["role"] == "name" and l10n.first_strong(text) == "L"
                        self.assertEqual(rtl_reading, not own)


# ------------------------------------------------------------------------------------------ the card
class CardMirrorTests(unittest.TestCase):
    def test_the_card_is_the_popup_s_card_mirrored(self):
        from test_notice_card import EVENTS, build, fake_measure
        for event, detail, _identity in EVENTS:
            vm = notice_card.view(build(event, detail))
            for scale in (1.0, 1.5, 2.0):
                measure = fake_measure(scale)
                ltr = notice_card.layout(dict(vm, locale="en"), scale, measure)
                self.assertNotIn("rtl", ltr)
                for locale in RTL:
                    with self.subTest(event=event, scale=scale, locale=locale):
                        self.assertEqual(notice_card.layout(dict(vm, locale=locale), scale, measure), popup.mirror(ltr))

    def test_its_last_line_keeps_the_exact_id_one_run(self):
        """The origin line ends in the conversation's exact id: in Arabic or Hebrew it is embedded left to right,
        and the project before it in its own direction. In every other language the line is what it was."""
        identity = {"name": "A task", "project": "مشروع"}
        with patch.object(l10n, "current", lambda environ=None: "ar"):
            line = notify._origin_line(identity, "A task", THREAD)
        self.assertIn("\u202a" + THREAD + "\u202c", line)
        self.assertTrue(line.startswith("\u202bمشروع\u202c"))
        for locale in l10n.OFFERED:
            with patch.object(l10n, "current", lambda environ=None, locale=locale: locale):
                line = notify._origin_line({"name": "A task", "project": "A project"}, "A task", THREAD)
            with self.subTest(locale=locale):
                self.assertEqual(line, "A project  ·  " + l10n.text("msg.toast_thread", locale).format(uuid=THREAD))
                self.assertFalse(re.search("[\u202a-\u202e\u2066-\u2069]", line))


# ------------------------------------------------------------------------------------------ the panel
NODE = __import__("shutil").which("node")


@unittest.skipUnless(NODE, "needs Node to run the panel's own code")
class PanelDirectionTests(unittest.TestCase):
    def run_page(self, locale, body):
        from test_mcpui_v064 import run_page, snapshot
        data = snapshot()
        data["system_language"] = locale
        return run_page(body, data=data, locale=locale,
                        prelude="window.__CODEX_AUTO_RESUME_RTL__ = %s;" % json.dumps(RTL))

    def test_the_root_says_rtl_in_arabic_and_hebrew_and_nothing_in_any_other_language(self):
        probe = ("process.stdout.write(JSON.stringify({dir: document.documentElement.getAttribute('dir'),"
                 " lang: document.documentElement.getAttribute('lang'),"
                 " filled: fill('panel.more', 'and {n} more', {n: 5})}));")
        for locale in ("ar", "he", "en", "de", "ja"):
            seen = self.run_page(locale, probe)
            with self.subTest(locale=locale):
                self.assertEqual(seen["lang"], locale)
                if l10n.right_to_left(locale):
                    self.assertEqual(seen["dir"], "rtl")
                    self.assertIn("\u20685\u2069", seen["filled"])
                else:
                    self.assertIsNone(seen["dir"])
                    self.assertEqual(seen["filled"], l10n.catalog(locale)["panel.more"].replace("{n}", "5"))

    def test_the_page_is_told_which_languages_are_written_right_to_left(self):
        page = mcpui.settings_page()
        self.assertIn("window.__CODEX_AUTO_RESUME_RTL__=%s;" % json.dumps(RTL), page)


class PanelStyleTests(unittest.TestCase):
    def test_nothing_in_the_stylesheet_is_placed_by_a_side_but_the_chevron_s_own_strokes(self):
        """A margin, a padding, an inset and an alignment are the line's start or end, so they turn with the
        direction; the chevron is drawn from two borders of its own box, which its rotation turns (and the
        right-to-left rules turn the other way)."""
        css = re.sub(r"/\*.*?\*/", "", mcpui._STYLE, flags=re.S)
        sided = re.findall(r"(?<![-\w])((?:margin|padding|border|inset)-(?:left|right)|left|right)\s*:\s*([^;}]+)", css)
        self.assertEqual([found for found in sided if found[0] != "border-right"], [])
        self.assertEqual([value.strip() for name, value in sided if name == "border-right"], ["2px solid var(--muted)"])
        self.assertFalse(re.search(r"text-align:\s*(left|right)\b", css))
        for name, value in re.findall(r"--size-([a-z-]+-pad):\s*([^;]+);", brand.css_scale()):
            sides = value.split()
            if len(sides) == 4 and sides[1] != sides[3]:
                with self.subTest(padding=name):
                    self.assertIn("--size-%s: %s %s %s %s;" % (name, sides[0], sides[3], sides[2], sides[1]),
                                  mcpui.right_to_left_rules())

    def test_the_right_to_left_rules_match_only_a_page_that_says_rtl(self):
        for rule in mcpui.right_to_left_rules().splitlines():
            with self.subTest(rule=rule):
                for selector in rule.split("{", 1)[0].split(","):
                    self.assertTrue(selector.strip().startswith(':root[dir="rtl"]'), selector)
        self.assertIn(mcpui.right_to_left_rules(), mcpui._STYLE)


EDGE = next((path for path in (Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")),
                               Path(os.environ.get("ProgramFiles", "C:/Program Files")))
             if (path / "Microsoft/Edge/Application/msedge.exe").is_file()), None)
PROBE = "CAR-MIRROR-PROBE:"
MEASURE = """<style>*, *::before, *::after { transition: none !important; animation: none !important; }</style>
<script>window.addEventListener('load',function(){setTimeout(function(){
function boxes(){
  var root=document.documentElement,width=root.clientWidth,out=[];
  Array.prototype.forEach.call(document.querySelectorAll('body *'),function(n){
    var s=getComputedStyle(n),r=n.getBoundingClientRect();
    if(s.display==='none'||s.display==='inline'||s.display==='contents'||!r.width||!r.height){out.push(null);return;}
    var text=null;
    if(!n.children.length&&n.textContent.trim()){var range=document.createRange();range.selectNodeContents(n);
      var t=range.getBoundingClientRect();text=[t.left,t.right];}
    var pseudo={};
    ['::before','::after'].forEach(function(p){var q=getComputedStyle(n,p);
      if(q.content&&q.content!=='none'&&q.display!=='none')pseudo[p]={left:q.left,right:q.right,transform:q.transform};});
    out.push({what:n.tagName+'.'+n.className,left:r.left,right:r.right,top:r.top,bottom:r.bottom,text:text,
      own:s.unicodeBidi==='plaintext'||s.direction!==getComputedStyle(root).direction,
      transform:s.transform,shadow:s.boxShadow,pseudo:pseudo});
  });
  return {width:width,boxes:out};
}
var root=document.documentElement,rtl=boxes(),dir=root.getAttribute('dir'),lang=root.getAttribute('lang');
root.removeAttribute('dir');var ltr=boxes();root.setAttribute('dir','rtl');
document.title='""" + PROBE + """'+JSON.stringify({dir:dir,lang:lang,rtl:rtl,ltr:ltr});},300);});</script>"""


def is_card(what) -> bool:
    """A box measured as `TAG.classes` that is a card."""
    return "card" in what.split(".", 1)[-1].split()


def matrix(transform):
    found = re.match(r"matrix\(([^)]*)\)", transform or "")
    return [float(part) for part in found.group(1).split(",")] if found else None


@unittest.skipUnless(EDGE is not None, "needs Microsoft Edge to lay the page out")
class PanelMirrorLayoutTests(unittest.TestCase):
    """The panel in Arabic, laid out by headless Edge right to left and again with the direction taken off: every
    box and every line of words across the page from where the other puts it, every drawn piece on the other
    side, every translation the other way and the chevron pointing the other way."""

    def measure(self, locale, design, width=900):
        from test_mcpui_v064 import snapshot
        data = snapshot()
        data["system_language"] = locale
        with patch.object(l10n, "preference", lambda: locale), \
                patch("codex_auto_resume.interface.language", lambda: locale):
            page = mcpui.settings_page(data, theme="light", design=design, text=1.0)
        with tempfile.TemporaryDirectory() as folder:
            probe = Path(folder) / "panel.html"
            probe.write_text(page.replace("</body>", MEASURE + "</body>"), encoding="utf-8")
            done = subprocess.run([str(EDGE / "Microsoft/Edge/Application/msedge.exe"), "--headless=new", "--disable-gpu",
                                   "--hide-scrollbars", "--virtual-time-budget=3000", "--user-data-dir=" + folder + "/p",
                                   "--window-size=%d,%d" % (width, 1600), "--dump-dom", probe.as_uri()],
                                  capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        for piece in done.stdout.split(PROBE)[1:]:
            try:
                return json.loads(html_text.unescape(piece.split("</title>", 1)[0]))
            except ValueError:
                continue
        self.fail("the browser said nothing: " + done.stderr[-1500:])

    def mismatches(self, found):
        width, problems, checked = found["rtl"]["width"], [], 0
        self.assertEqual(width, found["ltr"]["width"])
        for mirrored, plain in zip(found["rtl"]["boxes"], found["ltr"]["boxes"]):
            if mirrored is None or plain is None:
                self.assertEqual(mirrored is None, plain is None)
                continue
            checked += 1
            what = mirrored["what"]
            if (abs(mirrored["left"] - (width - plain["right"])) > 1 or abs(mirrored["right"] - (width - plain["left"])) > 1
                    or abs(mirrored["top"] - plain["top"]) > 1 or abs(mirrored["bottom"] - plain["bottom"]) > 1):
                problems.append("box %s %r / %r" % (what, mirrored, plain))
            if mirrored["text"] and plain["text"] and not mirrored["own"]:
                if (abs(mirrored["text"][0] - (width - plain["text"][1])) > 1
                        or abs(mirrored["text"][1] - (width - plain["text"][0])) > 1):
                    problems.append("words %s %r / %r" % (what, mirrored["text"], plain["text"]))
            for part, drawn in plain["pseudo"].items():
                other = mirrored["pseudo"].get(part)
                if other is None or (other["left"], other["right"]) != (drawn["right"], drawn["left"]):
                    problems.append("%s%s %r / %r" % (what, part, other, drawn))
                    continue
                one, two = matrix(other["transform"]), matrix(drawn["transform"])
                if (one is None) != (two is None) or (one and (one[:4] != two[:4] or one[4] != -two[4])):
                    problems.append("%s%s moves %r / %r" % (what, part, other["transform"], drawn["transform"]))
            one, two = matrix(mirrored["transform"]), matrix(plain["transform"])
            if "chevron" in what and two:
                # Where the chevron's corner points: across, and at the same height.
                corner = (two[0] + two[2], two[1] + two[3])
                turned = (one[0] + one[2], one[1] + one[3])
                if abs(turned[0] + corner[0]) > 0.01 or abs(turned[1] - corner[1]) > 0.01:
                    problems.append("chevron points %r / %r" % (mirrored["transform"], plain["transform"]))
            elif (one is None) != (two is None) or (one and (one[:4] != two[:4] or one[4] != -two[4])):
                problems.append("%s moves %r / %r" % (what, mirrored["transform"], plain["transform"]))
            if mirrored["shadow"] != plain["shadow"] and not (is_card(what) and "inset" in plain["shadow"]):
                problems.append("%s shadow %r / %r" % (what, mirrored["shadow"], plain["shadow"]))
        return problems, checked

    def test_in_arabic_every_box_line_and_drawn_piece_is_the_left_to_right_page_mirrored(self):
        for design in ("soft", "classic"):
            for width in (900, 480):
                found = self.measure("ar", design, width)
                problems, checked = self.mismatches(found)
                with self.subTest(design=design, width=width):
                    self.assertEqual((found["dir"], found["lang"]), ("rtl", "ar"))
                    self.assertGreater(checked, 100, "the page was laid out")
                    self.assertEqual(problems, [])

    def test_classic_s_accent_bar_is_inside_the_right_hairline(self):
        found = self.measure("he", "classic")
        cards = [(one, two) for one, two in zip(found["rtl"]["boxes"], found["ltr"]["boxes"])
                 if one and two and is_card(one["what"])]
        self.assertTrue(cards)
        bar = "%gpx" % brand.ACCENT_BAR
        for mirrored, plain in cards:
            self.assertIn("inset", plain["shadow"])
            self.assertIn(" %s 0px 0px 0px inset" % bar, plain["shadow"])
            self.assertIn(" -%s 0px 0px 0px inset" % bar, mirrored["shadow"])

    def test_the_measurement_finds_a_box_that_did_not_turn(self):
        """So a quiet report is the browser having looked: a rule that pins a box to the left is caught."""
        found = self.measure("ar", "soft")
        index = next(i for i, box in enumerate(found["ltr"]["boxes"]) if box and "prow-switch" in box["what"])
        found["rtl"]["boxes"][index] = dict(found["ltr"]["boxes"][index])
        problems, _ = self.mismatches(found)
        self.assertTrue(any("prow-switch" in problem for problem in problems), problems)


if __name__ == "__main__":
    unittest.main()
