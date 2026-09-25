"""Everything that writes CSS, and nothing that decides a value.

The top of this package. Every number it writes comes from one of the files above, so the
panel in Codex and the windows drawn in Python are working from one set of decisions.
"""
from __future__ import annotations

from .checkbox import CHECKBOX, check_mark_outline
from .elevation import SHADOWS, _CARD_GROUND
from .light import (GLOW,
                    GLOW_BREATHES,
                    STATUS_DOT,
                    glow_extent,
                    glow_phase,
                    glow_radius,
                    glow_reach)
from .motion import MOTION
from .scale import LAYOUT, LINE_HEIGHT, RADII, SPACING, TYPE_SCALE
from .tokens import theme_name



def _number(value) -> str:
    """A number as a stylesheet or a C# literal writes it: 14, 12.5, 0.3."""
    value = round(float(value), 4)
    return "%d" % value if value.is_integer() else repr(value)


def _css_length(value) -> str:
    return "0" if value == 0 else "%spx" % _number(value)



def css_scale() -> str:
    """The scale as CSS custom properties, for the panel's stylesheet.

    The glow's properties are all `--glow-*`, so attention's breath is
    `--glow-attention-ms` and never `--attention`: the palette already emits `--attention` as
    a colour on the same `:root`, and two custom properties with one name do not raise
    anything - the later declaration wins, the dark theme re-declares the colour, and an
    animation handed a colour for its duration simply does not run.

    `--type-*` is the panel's own type scale (TYPE_SCALE); the popup's TYPE is not a
    stylesheet's business. The glow's stops (css_glow_geometry) are written for the panel's dot,
    and the tile's smaller light writes its own under `.halo.mini`; `--glow-from`, the glow's scale
    with no spread, is a share of the dot and so the same at both sizes. The checking arc's
    numbers are `--glow-arc-*`: how long a turn takes, its colour's strength, how far past the
    dot's edge it runs and how wide, how many degrees it sweeps and where it holds still.
    """
    parts = []
    for prefix, table in (("radius", RADII), ("space", SPACING), ("type", TYPE_SCALE)):
        for name, value in table.items():
            parts.append("--%s-%s: %spx;" % (prefix, name.replace("_", "-"), _number(value)))
    for name, value in LINE_HEIGHT.items():
        parts.append("--lh-%s: %s;" % (name.replace("_", "-"), _number(value)))
    for name, value in LAYOUT.items():
        values = value if isinstance(value, tuple) else (value,)
        parts.append("--size-%s: %s;" % (name.replace("_", "-"),
                                          " ".join(_css_length(part) for part in values)))
    parts.append("--transition: %dms;" % MOTION["transition_ms"])
    parts.append("--transition-ease: %s;" % css_ease())
    dot, light = STATUS_DOT["panel"], GLOW
    parts.append(css_glow_geometry(dot))
    for name in ("edge", "near", "far"):
        parts.append("--glow-%s-mix: %s%%;" % (name, _number(light[name + "_alpha"] * 100)))
    parts.append("--glow-from: %s;" % _number(dot / glow_extent(dot)))
    for state in GLOW_BREATHES:
        parts.append("--glow-%s-ms: %dms;" % (state, light[state + "_ms"]))
    parts.append("--glow-arc-ms: %dms;" % light["arc_ms"])
    parts.append("--glow-arc-mix: %s%%;" % _number(light["arc_alpha"] * 100))
    parts.append("--glow-arc-gap: %s;" % _css_length(light["arc_gap"]))
    parts.append("--glow-arc-width: %s;" % _css_length(light["arc_width"]))
    parts.append("--glow-arc-sweep: %sdeg;" % _number(light["arc_sweep"]))
    parts.append("--glow-arc-still: %sdeg;" % _number(light["arc_still_at"]))
    parts.append(css_check_box())
    return " ".join(parts)


def css_glow_geometry(dot) -> str:
    """Where the glow of a light `dot` px in radius reaches, and where its falloff's stops lie: `--glow-reach`, and
    `--glow-edge`, `--glow-near`, `--glow-far` and `--glow-outer` measured from the dot's centre.

    Written once in css_scale() for the panel's light and again, for the Automatic recovery tile's smaller one, under
    `.halo.mini` (v0.6.10), whose glow the stylesheet's own rules then draw from it. The reach is a share of the dot,
    so the two are the same light at two sizes; the breath needs nothing per size, its scale and its brightness being
    shares too.
    """
    parts = ["--glow-reach: %s;" % _css_length(glow_reach(dot))]
    for name, fraction in (("edge", 0.0), ("near", GLOW["near_at"]), ("far", GLOW["far_at"]), ("outer", 1.0)):
        parts.append("--glow-%s: %s;" % (name, _css_length(dot + glow_reach(dot) * fraction)))
    return " ".join(parts)


GLOW_STOPS = 40             # keyframe stops a breath is written as: one every 2.5% of the cycle, which keeps the
                            # straight lines between them inside a thousandth of the curve


def css_glow_keyframes() -> str:
    """GLOW's breath as the panel's keyframes: `glow-dot`, the dot's colour drawn toward the ground it stands on,
    `glow-spread`, the glow's opacity and scale, and `glow-arc`, one turn of the checking arc.

    A keyframe selector cannot read a custom property and CSS has no cosine, so the curve is sampled here from
    glow_phase itself, every 2.5% of the cycle, and written out as stops. What the browser puts between two stops is
    a straight line across a fortieth of a four-second breath, which is below what an eye can see; sampling is what
    keeps the panel's light the same light as the window's rather than a hand-fitted lookalike.

    The dot dims by mixing its colour with `--halo-ground`, the ground under it, and not by its opacity (v0.6.10).
    The glow is drawn inside the dot's element, so an opacity on the dot multiplied the glow by the dot's brightness
    as well, and halfway through a breath the panel's glow was a fifth weaker than the window's and the popup's,
    which draw the two apart. A value inside a keyframe may read custom properties; its selector may not.
    """
    dot, spread, extent = [], [], glow_extent(STATUS_DOT["panel"])
    for step in range(GLOW_STOPS + 1):
        fraction = step / float(GLOW_STOPS)
        dim, out = glow_phase(fraction)
        at = "%s%%" % _number(fraction * 100)
        dot.append("%s { background-color: color-mix(in srgb, var(--halo-color) %s%%, var(--halo-ground)); }"
                   % (at, _number((1.0 - dim) * 100)))
        scale = glow_radius(STATUS_DOT["panel"], out) / extent
        spread.append("%s { opacity: %s; transform: scale(%s); }" % (at, _number(GLOW["peak"] * out), _number(scale)))
    return ("@keyframes glow-dot { %s }\n@keyframes glow-spread { %s }\n"
            "@keyframes glow-arc { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }"
            % (" ".join(dot), " ".join(spread)))


def css_ease() -> str:
    """MOTION's curve as CSS writes it: cubic-bezier(0.33, 1, 0.68, 1)."""
    return "cubic-bezier(%s)" % ", ".join(_number(value) for value in MOTION["ease"])



def css_check_box() -> str:
    """The check box's custom properties, part of css_scale().

    `--check-<state>-<part>` for every CHECKBOX entry - `--check-off-fill: var(--inset);` - so a
    stylesheet that draws with them follows the table and the theme block that redefines the
    tokens. A custom property's var() is resolved on the element that declares it and inherited
    resolved, so these follow a theme only where the theme is stamped on that same element: the
    panel's `:root`, never a descendant.

    `--check-<state>-elev` is `var(--elev-inset)` where the well is drawn and `none` elsewhere.
    `--check-mark-shape` is the mark as a `clip-path` polygon on a box of `--size-check-size`,
    measured from its outer top-left corner - so the layer it clips covers the whole box, border
    included (an absolutely placed `::before` sits a hairline up and left of its padding box).
    The sizes themselves are the `--size-check-*` and `--radius-check` css_scale() writes.
    """
    parts = []
    for state, entry in CHECKBOX.items():
        name = state.replace("_", "-")
        for part in ("fill", "edge", "mark"):
            if entry[part] is not None:
                parts.append("--check-%s-%s: var(--%s);" % (name, part, entry[part].replace("_", "-")))
        parts.append("--check-%s-elev: %s;" % (name, "var(--elev-inset)" if entry["well"] else "none"))
    parts.append("--check-mark-shape: polygon(%s);" % ", ".join(
        "%spx %spx" % (_number(x), _number(y)) for x, y in check_mark_outline()))
    return " ".join(parts)



def css_elevation(theme) -> str:
    """`--elev-card`, `--elev-control`, `--elev-inset` and `--card-ground` for one theme.

    `color-mix(in srgb, X p%, transparent)` is X at alpha p, which is what keeps the shadow's
    colour a token in the stylesheet rather than a number baked into it.
    """
    name = theme_name(theme)
    parts = []
    for recipe, listed in SHADOWS[name].items():
        parts.append("--elev-%s: %s;" % (recipe, ", ".join(
            "%s%s %s %s color-mix(in srgb, var(--%s) %d%%, transparent)" % (
                "inset " if shadow.inset else "", _css_length(shadow.dx), _css_length(shadow.dy),
                _css_length(shadow.blur), shadow.token.replace("_", "-"),
                int(round(shadow.alpha * 100)))
            for shadow in listed)))
    parts.append("--card-ground: %s;" % _CARD_GROUND[name])
    return " ".join(parts)



def css_variables(theme: dict) -> str:
    """`--name: #value;` pairs, in declaration order, for a stylesheet block.

    Token names are hyphenated on the way out, because that is what CSS custom
    properties look like everywhere else. Emitting `--on_accent` and then writing
    `var(--on-accent)` in the stylesheet is a mistake that produces no error at all:
    the property is simply unset and the text falls back to whatever it inherited.
    """
    return " ".join("--%s: %s;" % (name.replace("_", "-"), value)
                    for name, value in theme.items())
