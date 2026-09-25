"""The settings panel Codex renders inside the conversation.

One self-contained page: no network, no CDN, no framework, no fonts to fetch. A widget
that reaches for a script it cannot load is a blank rectangle, and this one has to work
on a machine whose whole point is that its network just failed.

It renders from the schema the tool returns rather than from a hardcoded list of
fields, so it shows exactly what the settings module defines - the same source the
standalone window and the command line render from.

The host API is feature-detected. Different hosts expose the widget bridge under
different names, and a version that assumed one of them would silently show a panel
whose Save button does nothing. When no bridge is found the page says so plainly and
falls back to being a readable summary, which is still worth showing.

v0.6.3 gave it the same visual language as the Dashboard and the notification-area popup
- soft cards on a warm canvas, a state that breathes while it is being watched - and the
continuation settings. Two things about those are structural rather than stylistic:

* **Custom message text is shown, never edited.** Whatever it says is later sent into the
  user's conversations when nobody is watching, so it is written in the Windows Dashboard
  and nowhere else. This page has no text field for it, and neither the Save request nor
  the Preview request can carry it - `editable()` and `previewArguments()` are the two
  gates, and the tests run both.
* **The Preview is the watcher's own text.** It asks `preview_recovery_message`, which
  builds the message with the function the watcher sends with. The page never assembles a
  continuation of its own.

v0.6.4 added the Theme setting and v0.6.6 the panel's own beside it, which the panel applies to
itself - Light or Dark stamp `data-theme` on the root, following Codex stamps nothing - and it
speaks a newly saved Interface language at once, from every language's words for this page,
which ship with it. An on/off setting is a switch when it turns something that runs on or
off and a check box when it picks items of a list, as in the Windows Dashboard. A switch or a
button at the right of a row is pinned to the row's bottom-right, beside the last line of the
text it belongs to, as it is in the window and the notification-area popup.

v0.6.5 made the last native piece its own: a select opened the browser's square, flat, system-blue
list, so a choice now opens the Dashboard's - a raised card of pill items, a WAI-ARIA combobox over
the select, which stays underneath as the value. Since v0.6.6 the scroll bar is ours too, either axis.
And controls move when they change, on brand's one time and one curve: a switch's knob glides and
its track cross-fades, a check box fades its fill and mark, a list rises into place - none of it
with less motion or in High Contrast, and a switch that asks first moves once it is answered.
It also shows the Codex Compatibility Registry as the Dashboard's Diagnostics page does, folded and
read-only (`renderCompatibility`): codes in, words out, and no way to refresh the data from here.
Its tiles - a waiting task, the master switch - stand on their cards as the popup's task tiles do
(`tile_elevation`), and a line of Korean breaks between words and one of Japanese between phrases.

v0.6.10 draws it in the stored Design - Soft, Still, Classic or Plain - stamped on the root as the theme
is, with every design's properties in the stylesheet (`brand.css_design_blocks`) and what each moves
beside them (`design_rules`); and it follows the product's own Reduce motion as well as the host's. It
draws in both and edits neither: what moves is the Dashboard's to change, not Codex's.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

from .. import brand, interface, l10n

_ASSETS = Path(__file__).resolve().parent / "assets"


def _asset(name: str) -> str:
    """One of the panel's own files, read as the page has always carried it.

    Universal newlines, on purpose. `.gitattributes` checks every text file out with CRLF and
    the release archive packs it that way, so on an installed copy these two have CRLF on
    disk - while the page they are served in has always carried LF, and the replies Codex
    receives are held to the byte by `tests/golden/`. Opening these with `newline=""` would
    change what every installed copy serves and nothing that builds one.
    """
    return (_ASSETS / name).read_text(encoding="utf-8")


# The page is delivered as one resource, so the style lives in it. Every colour comes
# from the shared palette, which is what keeps this panel, the settings window and the
# icon the same product rather than three that happen to ship together. It is
# `mcp/assets/panel.css`, with @TOKEN@ wherever a value comes from `brand`; the
# substitutions are below.
_STYLE = _asset("panel.css")


def css_shadow(shadow) -> str:
    """One of brand's Shadows as CSS, word for word as brand.css_elevation writes it."""
    return "%s%s %s %s color-mix(in srgb, var(--%s) %d%%, transparent)" % (
        "inset " if shadow.inset else "", brand._css_length(shadow.dx), brand._css_length(shadow.dy),
        brand._css_length(shadow.blur), shadow.token.replace("_", "-"), int(round(shadow.alpha * 100)))


def tile_elevation(theme, design="soft") -> str:
    """`--elev-tile` for one theme: how a tile - a waiting task's row, the master switch's - stands on
    its card. It is the popup's raised task tile (popup.DEPTH), made of brand's recipes the same
    way: brand's control lift and, where brand's card has one (dark), the card's inset top light, the
    one-pixel edge a drop alone cannot give a tile on a dark card at this size. `none` in a design
    without depth, said outright: a list that began with an `--elev-control` of `none` is not CSS."""
    if not brand.design_depth(design):
        return "--elev-tile: none;"
    top_light = [shadow for shadow in brand.shadows("card", theme) if shadow.inset]
    return "--elev-tile: %s;" % ", ".join(["var(--elev-control)"] + [css_shadow(shadow) for shadow in top_light])


def design_rules() -> str:
    """The stylesheet's rules for what each design moves and for Classic's mark, from brand.DESIGN (v0.6.10).

    Written from the table rather than per design, so a design whose row changes carries its rules with
    it. Every selector starts from the root's stamp - `data-design`, or `data-motion="reduced"` for the
    product's own Reduce motion, which holds everything as a design that does not breathe does - so none
    of them matches a page that is stamped with neither: Soft, and a watcher older than the setting.
    """
    def roots(designs):
        return [':root[data-design="%s"]' % design for design in designs]

    def every(selected):
        return ", ".join("%s %s" % (root, part) for root in selected for part in ("*", "*::before", "*::after"))

    held = roots(design for design in brand.DESIGNS if not brand.design_breathes(design))
    held.append(':root[data-motion="reduced"]')
    unglided = roots(design for design in brand.DESIGNS if not brand.design_glides(design))
    glowless = held + [root for root in roots(design for design in brand.DESIGNS if not brand.design_glow(design))
                       if root not in held]
    barred = roots(design for design in brand.DESIGNS if brand.design_accent_bar(design))
    return "\n".join([
        "%s { animation: none !important; transition: none !important; }" % every(held),
        "%s { transition: none !important; }" % every(unglided),
        "%s { animation: none !important; }" % ", ".join(root + " .combo-list" for root in unglided),
        "%s { display: none; }" % ", ".join(root + " .halo::before" for root in glowless),
        "%s { box-shadow: inset %s 0 0 var(--accent); }" % (", ".join(root + " .card" for root in barred),
                                                            brand._css_length(brand.ACCENT_BAR)),
    ])


# Resolved once, at import: the palette is a build-time fact, not a per-request one. The lift
# of a surface is brand's SHADOWS written as CSS - the recipe the window and the popup paint
# from - so this page states no shadow of its own.
_STYLE = (_STYLE.replace("@LIGHT@", brand.css_variables(brand.LIGHT))
                .replace("@DARK@", brand.css_variables(brand.DARK))
                .replace("@ELEVATION_LIGHT@", brand.css_elevation("light"))
                .replace("@ELEVATION_DARK@", brand.css_elevation("dark"))
                .replace("@TILE_LIGHT@", tile_elevation("light"))
                .replace("@TILE_DARK@", tile_elevation("dark"))
                # v0.6.10: the designs, and what each moves.
                .replace("@DESIGNS@", brand.css_design_blocks(tile_elevation))
                .replace("@DESIGN_MOTION@", design_rules())
                .replace("@SCALE@", brand.css_scale())
                .replace("@GLOW_KEYFRAMES@", brand.css_glow_keyframes())
                # The Automatic recovery tile's light: the same light, smaller (v0.6.10).
                .replace("@GLOW_MINI@", brand.css_glow_geometry(brand.STATUS_DOT["mini"]))
                # Where a drop-down's words start, in its field and in its list: the field's own padding.
                .replace("@SELECT_PAD_LEFT@", "%gpx" % brand.padding("select_pad")[3]))

# The script is `mcp/assets/panel.js`. `panel_keys()` below reads the keys out of it.
_SCRIPT = _asset("panel.js")


# Which catalog keys the script can ask for: every key it names, and every key under a prefix it
# completes at runtime (`t('reason.' + category)`, `S['field.' + name]`). Read from the script
# itself, so a word added to the page is a word every language ships with it; the tests hold the
# script to asking only in these two shapes.
_NAMED_KEY = re.compile(r"\b(?:t|fill|withLanguage)\(\s*'([a-z0-9_.]+)'\s*[,)]")
_KEY_PREFIX = re.compile(r"\b(?:t|fill)\(\s*'([a-z0-9_.]+\.)'\s*\+|\bS\['([a-z0-9_.]+\.)'\s*\+")


def panel_keys() -> tuple:
    """The keys the script names, and the prefixes it builds keys from: ``(names, prefixes)``."""
    names = frozenset(_NAMED_KEY.findall(_SCRIPT))
    prefixes = tuple(sorted({named or indexed for named, indexed in _KEY_PREFIX.findall(_SCRIPT)}))
    return names, prefixes


def panel_catalogs() -> dict:
    """Every shipped language's words for this page, and only this page's.

    So a language chosen in the panel is spoken as soon as the save is confirmed, rather than
    the next time Codex opens the panel. Each catalog is English with that language layered
    over it, exactly as `l10n.catalog` gives it to every other surface.
    """
    names, prefixes = panel_keys()
    return {locale: {key: text for key, text in l10n.catalog(locale).items()
                     if key in names or key.startswith(prefixes)}
            for locale in l10n.LOCALES}


def _script_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c")


def settings_page(data=None, theme=None, design=None) -> str:
    """The panel as one HTML document.

    ``data`` is only ever used for a preview: in Codex the values arrive from the tool
    result, so the served page carries no settings of its own and cannot go stale
    between being read and being shown.
    """
    # The vocabulary always ships, seed data or not. In Codex the values arrive from the
    # tool result, but the page still has to know what to call them - and the panel must
    # not choose the language for itself. A product that speaks Korean in its
    # notifications and English in its settings panel has picked the worst of both, so
    # the language is resolved once, in Python, and handed here - with every other
    # language's words for this page beside it, for the moment the stored choice changes.
    locale = interface.language()
    catalog = "<script>window.__CODEX_AUTO_RESUME_STRINGS__=%s;</script>" % _script_json(
        l10n.catalog(locale))
    catalogs = ("<script>window.__CODEX_AUTO_RESUME_LOCALE__=%s;"
                "window.__CODEX_AUTO_RESUME_CATALOGS__=%s;</script>"
                % (_script_json(locale), _script_json(panel_catalogs())))
    seed = ""
    if data is not None:
        seed = "<script>window.__CODEX_AUTO_RESUME__=%s;</script>" % _script_json(data)
    # `theme` pins the colour scheme instead of following the host or the stored Theme.
    # Codex never passes it - inside Codex the panel follows its own theme, or the Theme's
    # while that is Same as Theme, or the host - and the documentation capture does, because a
    # screenshot whose theme depends on whichever machine ran the build is not a
    # deterministic artefact. `data-theme-pinned` tells the script to leave it alone.
    root = ("<html>" if theme not in ("light", "dark")
            else '<html data-theme="%s" data-theme-pinned="">' % theme)
    # `design` pins the design the same way (v0.6.10): Soft is no stamp, as it is when the script
    # stamps from the stored design, and `data-design-pinned` tells the script to leave it alone.
    if design in brand.DESIGNS:
        stamp = "" if design == brand.DEFAULT_DESIGN else ' data-design="%s"' % design
        root = root[:-1] + stamp + ' data-design-pinned="">'
    return (
        "<!doctype html>" + root + "<head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>Codex Auto Resume</title><style>%s</style></head>"
        "<body><div id=\"root\"></div>%s%s%s<script>%s</script></body></html>"
        % (_STYLE, catalog, catalogs, seed, _SCRIPT))
