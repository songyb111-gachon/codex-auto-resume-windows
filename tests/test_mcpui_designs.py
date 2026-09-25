"""v0.6.10 in the panel in Codex: the Design setting, and the product's own Reduce motion.

The panel's stylesheet is built once, at import, so a design cannot be chosen by rebuilding it: every
design is in it, as custom properties under the root's `data-design` stamp in the four places the base
theme blocks stand, and as rules for what each design moves. The script stamps the root from the stored
settings (applyDesign) - the design, and `data-motion="reduced"` for Reduce motion, which until this
release the panel did not read at all. And the panel draws in the design without ever writing it: it is
not an editor, not a change, and not in what Save sends (standard H3).
"""
from __future__ import annotations

import re
import unittest

from codex_auto_resume import brand
from codex_auto_resume.mcp import panel as mcpui
from test_mcpui_v063 import REDUCED, RULES
from test_mcpui_v064 import NODE, run_page, say, snapshot

STAMPED = {design: ':root[data-design="%s"]' % design for design in brand.DESIGNS}
MOTION = ':root[data-motion="reduced"]'


def block(design, form):
    """The declarations of one of a design's four blocks: 'root', 'host dark', 'dark' or 'light'."""
    root = STAMPED[design]
    wanted, where = {"root": (root, ""),
                     "host dark": (root + ':not([data-theme="light"])', "@media (prefers-color-scheme: dark)"),
                     "dark": (root + '[data-theme="dark"]', ""),
                     "light": (root + '[data-theme="light"]', "")}[form]
    found = [declarations for context, selectors, declarations in RULES
             if context == where and selectors == (wanted,)]
    return found[0] if len(found) == 1 else None


def selectors_with(prop, value):
    return {selector for where, selectors, declarations in RULES if where == "" and declarations.get(prop) == value
            for selector in selectors}


class StylesheetTests(unittest.TestCase):
    def test_each_flat_design_is_declared_in_the_four_places_a_theme_is(self):
        for design in ("classic", "plain"):
            for form, theme in (("root", "light"), ("host dark", "dark"), ("dark", "dark"), ("light", "light")):
                declarations = block(design, form)
                with self.subTest(design=design, form=form):
                    self.assertIsNotNone(declarations)
                    for token, value in brand.palette(theme, design).items():
                        self.assertEqual(declarations["--" + token.replace("_", "-")], value, token)
                    # All four elevations said outright: none of them may end up a list starting `none`.
                    for name in ("--elev-card", "--elev-control", "--elev-inset", "--elev-tile"):
                        self.assertEqual(declarations[name], "none", name)
                    self.assertEqual(declarations["--card-ground"], "var(--surface)")
                    for role, radius in brand.design_radii(design).items():
                        self.assertEqual(declarations["--radius-" + role], "%dpx" % radius)

    def test_soft_and_still_have_no_block_of_their_own(self):
        for design in ("soft", "still"):
            for form in ("root", "host dark", "dark", "light"):
                self.assertIsNone(block(design, form), (design, form))

    def test_every_variable_a_design_block_uses_is_defined(self):
        used = set(re.findall(r"var\(\s*(--[a-z-]+)\s*\)", brand.css_design_blocks(mcpui.tile_elevation)
                              + mcpui.design_rules()))
        defined = set(re.findall(r"(--[a-z-]+)\s*:", mcpui._STYLE))
        self.assertEqual(used - defined, set())

    def test_still_and_reduce_motion_hold_everything_as_the_reduced_motion_block_does(self):
        stopped = selectors_with("animation", "none !important") & selectors_with("transition", "none !important")
        hidden = {selector for where, selectors, declarations in RULES
                  if where == "" and declarations.get("display") == "none" for selector in selectors}
        for root in (STAMPED["still"], MOTION):
            with self.subTest(root):
                for part in ("*", "*::before", "*::after"):
                    self.assertIn("%s %s" % (root, part), stopped)
                self.assertIn(root + " .halo::before", hidden)
        # The reduced-motion block the host's preference reaches says the same.
        reduced = [declarations for where, selectors, declarations in RULES if where == REDUCED]
        self.assertTrue(any(declarations.get("animation") == "none !important" for declarations in reduced))

    def test_plain_hides_only_the_glow_and_its_light_still_dims(self):
        hidden = {selector for where, selectors, declarations in RULES
                  if where == "" and declarations.get("display") == "none" for selector in selectors}
        self.assertIn(STAMPED["plain"] + " .halo::before", hidden)
        animation_stopped = selectors_with("animation", "none !important")
        for part in ("*", "*::before", "*::after"):
            self.assertNotIn("%s %s" % (STAMPED["plain"], part), animation_stopped)
            self.assertNotIn("%s %s" % (STAMPED["classic"], part), animation_stopped)
        self.assertNotIn(STAMPED["classic"] + " .halo::before", hidden)

    def test_only_soft_glides(self):
        stopped = selectors_with("transition", "none !important")
        lists = selectors_with("animation", "none !important")
        for design in brand.DESIGNS:
            with self.subTest(design):
                self.assertEqual(STAMPED[design] + " *" in stopped, not brand.design_glides(design))
                self.assertEqual(STAMPED[design] + " .combo-list" in lists | stopped,
                                 not brand.design_glides(design))

    def test_classic_draws_its_bar_as_a_shadow_so_nothing_moves(self):
        bar = [declarations for where, selectors, declarations in RULES
               if where == "" and selectors == (STAMPED["classic"] + " .card",)]
        self.assertEqual(bar, [{"box-shadow": "inset %dpx 0 0 var(--accent)" % brand.ACCENT_BAR}])
        for where, selectors, declarations in RULES:
            if any("data-design" in selector for selector in selectors):
                with self.subTest(selectors):
                    for prop in ("border", "border-left", "border-width", "padding", "margin", "width", "height"):
                        self.assertNotIn(prop, declarations)

    def test_a_pinned_page_carries_its_design_and_soft_carries_no_stamp(self):
        self.assertIn('<html data-theme="light" data-theme-pinned="" data-design="plain" data-design-pinned="">',
                      mcpui.settings_page(theme="light", design="plain"))
        self.assertIn('<html data-design-pinned="">', mcpui.settings_page(design="soft"))
        self.assertIn("<html><head>", mcpui.settings_page())
        self.assertIn("<html><head>", mcpui.settings_page(design="neon"))


@unittest.skipUnless(NODE, "needs Node to run the panel's own code")
class ApplyDesignTests(unittest.TestCase):
    ROOT = say("{design: document.documentElement.getAttribute('data-design'),"
               " motion: document.documentElement.getAttribute('data-motion')}")

    def test_the_stored_design_and_reduce_motion_are_stamped_on_the_root(self):
        for design in brand.DESIGNS:
            for reduced in (False, True):
                observed = run_page(self.ROOT, data=snapshot(design=design, reduce_motion=reduced))
                with self.subTest(design=design, reduced=reduced):
                    self.assertEqual(observed, {"design": None if design == "soft" else design,
                                                "motion": "reduced" if reduced else None})

    def test_soft_an_unknown_value_or_none_at_all_removes_the_stamp(self):
        for value in ("soft", "neon", "Classic", 3, None):
            observed = run_page("adopt({design: 'plain', reduce_motion: true});"
                                "adopt({design: %s});" % ("null" if value is None else repr(value)) + self.ROOT)
            with self.subTest(value=value):
                self.assertEqual(observed, {"design": None, "motion": None})
        observed = run_page("adopt({design: 'plain'}); adopt({});" + self.ROOT)
        self.assertEqual(observed, {"design": None, "motion": None})

    def test_a_pinned_design_is_left_alone(self):
        observed = run_page("adopt({design: 'classic', reduce_motion: true});" + self.ROOT,
                            root_attributes={"data-design": "plain", "data-design-pinned": ""})
        self.assertEqual(observed, {"design": "plain", "motion": "reduced"})

    def test_the_design_is_never_an_editor_a_change_or_a_thing_save_sends(self):
        observed = run_page("""
          var steps = {editors: Object.keys(EDITORS), changes: Object.keys(collectChanges(EDITORS, DATA.schema)),
                       editable: editable({name: 'design', group: 'appearance'}),
                       shown: !!byId('car-design')};
          saveButton().fire('click');
          await settle();
          steps.sent = CALLS.filter(function (call) { return call[0] === 'update_settings'; })
                            .map(function (call) { return Object.keys(call[1]); });
        """ + say("steps"), data=snapshot(design="classic"))
        self.assertNotIn("design", observed["editors"])
        self.assertNotIn("design", observed["changes"])
        self.assertIs(observed["editable"], False)
        self.assertIs(observed["shown"], False)
        for sent in observed["sent"]:
            self.assertNotIn("design", sent)
