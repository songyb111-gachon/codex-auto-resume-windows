"""The one place a colour is decided.

Five surfaces used to carry their own copies of the palette - the plugin manifest, the
Codex panel's stylesheet, the settings window's C# literals, the icon renderer and the
documentation. Five copies is five chances to drift, and they had already drifted: the
manifest's brand colour and the panel's accent agreed, and neither agreed with the icon.

So the palette lives here, in the package, and everything else is generated from it or
tested against it. The C# window cannot import Python, so its colours are *generated*
into `gui/Brand.cs` and a test regenerates and compares. Everything else imports.

## The idea

The product waits, and then it acts. That is the whole behaviour, so it is the whole
palette: deep blue at rest, cyan at the moment it does something. The ramp is not
decoration, it is the state model - a reader who learns that bright means active has
learned what the tool does.

## Reading the tokens

`LIGHT` and `DARK` hold the same key set, so a surface themes by swapping one for the
other. `RAMP` is the identity blues, darkest first, which the icon and any promotional
surface draw from; it does not change with the theme, because a brand mark that changes
colour with the operating system is not a brand mark.

`active` is a **fill-only** token: 2.4:1 against white, fine for a dot and not for text.
`accent` is the token for anything a person reads - 6.8:1 on white, 6.7:1 on the dark
surface - and text drawn *on* it takes `on_accent`, which differs between the themes.

## Two themes, three surfaces (v0.6.4)

The window, the popup and the panel all have both themes, and the panel in dark is the
reference. Every theme-dependent value is reachable by theme name - `palette(theme)`,
`shadows(recipe, theme)`, `card_ground(theme)`, `status_colour(state, theme)`,
`check_box(checked, enabled, theme)` - and the window gets the dark half generated as
`Brand.Dark`. Which theme is in effect is the surfaces' business; High Contrast replaces both.

v0.6.10-alpha: nine files, in the order they are imported below, which is their dependency
order - each uses only what is above it.

    colour      arithmetic on #RRGGBB, and nothing that decides a colour
    tokens      the identity ramp, the one brand colour, and the two themes
    scale       sizes, type and the panel's layout: what is not colour and does not move
    motion      how long a change takes, and the one curve it takes it on
    elevation   the shadow recipes, and what a shadow does to a pixel
    checkbox    the check box and its tick
    light       the status light, frame by frame
    mark        the mark's own colours, its geometry, and its rasteriser
    css         everything that writes CSS, and nothing that decides a value

Three private names are re-exported on purpose, because something outside reads each of them
and each would be silent if it stopped: `_breath` (the icon's frames, behind an `except`),
`_css_length` (the panel's stylesheet, built at import behind another) and `_bezier` (the
suite's own check that `ease` is the curve it claims).
"""
from __future__ import annotations

from .colour import brighten, contrast, luminance, mix, rgb  # noqa: F401
from .tokens import BRAND, DARK, LIGHT, RAMP, THEMES, palette, theme_name  # noqa: F401
from .scale import (LAYOUT,
                    LINE_HEIGHT,
                    RADII,
                    SPACING,
                    TYPE,
                    TYPE_ROLES,
                    TYPE_SCALE,
                    padding)  # noqa: F401
from .motion import MOTION, _bezier, ease  # noqa: F401
from .elevation import (CARD_LIFT,
                        SHADOWS,
                        Shadow,
                        card_ground,
                        elevation_colour,
                        reach,
                        shadow_alpha,
                        shadow_offset,
                        shadows)  # noqa: F401
from .checkbox import (CHECKBOX,
                       CHECKBOX_SYSTEM,
                       CHECK_MARK,
                       SYSTEM_CSS,
                       check_box,
                       check_box_state,
                       check_box_system,
                       check_mark,
                       check_mark_outline,
                       css_system)  # noqa: F401
from .light import (GLOW,
                    GLOW_BREATHES,
                    STATUS_DOT,
                    STATUS_FILL,
                    STATUS_SYSTEM,
                    _breath,
                    glow,
                    glow_extent,
                    glow_floor,
                    glow_moves,
                    glow_phase,
                    glow_radius,
                    glow_reach,
                    glow_stops,
                    status_colour,
                    status_fill,
                    status_system)  # noqa: F401
from .mark import (ICON_ACCENT,
                   ICON_BOTTOM,
                   ICON_MARK,
                   ICON_SHAPE,
                   ICON_SUPERSAMPLE,
                   ICON_TOP,
                   icon_head_box,
                   icon_head_centre,
                   icon_pixel,
                   icon_render,
                   icon_ring_arc,
                   icon_rounded_square,
                   icon_samples)  # noqa: F401
from .css import (GLOW_STOPS,
                  _css_length,
                  css_check_box,
                  css_ease,
                  css_elevation,
                  css_glow_geometry,
                  css_glow_keyframes,
                  css_scale,
                  css_variables)  # noqa: F401
