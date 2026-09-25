"""Sizes, type and the panel's layout: everything that is not a colour and does not move.

Device-independent units throughout, so the same table answers at every scale factor.
"""
from __future__ import annotations



# ------------------------------------------------------------------- scale
# Everything that is not a colour, in device-independent pixels at 96 DPI. The window
# multiplies by its own scale factor; the panel writes these as CSS pixels. One table,
# so a card in the window and a card in Codex round their corners by the same amount.
RADII = {"card": 16, "control": 11, "chip": 999, "small": 7, "check": 5}
SPACING = {"xs": 4, "s": 8, "m": 12, "l": 16, "xl": 24, "xxl": 32}
# The notification-area popup's type sizes. The panel sets its own (TYPE_SCALE, below) and
# the settings window keeps the system message font, so this table is the popup's alone.
TYPE = {"title": 20, "heading": 14, "body": 12, "small": 11}




# ------------------------------------------------------------ v0.6.4: the panel, as data
# The Codex panel is the design the other two surfaces follow, and until v0.6.4 most of its
# numbers lived only in its stylesheet. The window and the popup could not read them, so each
# drew its own approximation of the same card - three surfaces that looked alike and were
# made of different stuff. These tables are the stylesheet's numbers, so they can be one.

# Type, in CSS px, as the panel sets it. The panel's only: the window keeps the system message
# font at its own sizes and the popup keeps TYPE, and both of those were decisions.
TYPE_SCALE = {"display": 21, "display_narrow": 20, "title": 15, "body": 14, "small": 12.5,
              "mono": 13, "badge": 12}
LINE_HEIGHT = {"display": 1.25, "title": 1.35, "body": 1.5, "small": 1.45, "bubble": 1.55}
# What each kind of text is set in: (TYPE_SCALE key, CSS weight).
TYPE_ROLES = {
    "display": ("display", 600), "title": ("title", 600), "heading": ("body", 600),
    "label": ("body", 500), "body": ("body", 400), "button": ("body", 500),
    "name": ("body", 600), "chip": ("small", 500), "help": ("small", 400),
    "count": ("small", 400), "mono": ("mono", 400),
}

# Sizes, in CSS px. A tuple is a padding in CSS shorthand order - top, right, bottom, left,
# a missing value repeating the one CSS would repeat - so the panel writes it as it stands and
# the window expands it with `padding()`.
LAYOUT = {
    "page_pad": (16, 14, 20),       # around the page of cards
    "page_gap": 14,                 # between cards
    "card_pad": (16, 18),
    "card_head_gap": 12,            # a card's heading and what sits beside it
    "card_first_gap": 6,            # the heading and the first thing under it
    "hero_pad": (16, 20),           # the state card at the top
    "hero_gap": 4,
    # v0.6.10: a status light and the word beside it stand alike on every surface - this far from
    # the line's start to the dot's edge, and this far from the dot's other edge to the word. Until
    # then each surface had its own literals, and the word stood 15 to 18.5 px from its light.
    "light_inset": 9,
    "light_gap": 14,
    "savebar_pad": (10, 12),        # the save card at the bottom
    "row_pad": (11, 0),             # a setting: its name on the left, its control on the right
    "row_gap": 16,
    "tile_pad": (10, 12, 10, 14),   # a row tile: a pending task, the master switch
    "tile_gap": 8,
    "button_height": 34,
    "button_pad": (6, 16),
    "field_height": 35,             # a select or a number: a well
    "select_pad": (6, 34, 6, 12),
    "chevron_width": 10,            # the select's wedge, `muted`
    "chevron_height": 5,
    "chevron_right": 13,            # from the inside of the well's right border to the wedge
    "number_width": 88,
    "segment_height": 36,
    "segment_pad": (7, 8),
    "segment_gap": 6,
    "switch_width": 40,
    "switch_height": 22,
    "knob": 16,
    "knob_inset": 3,                # from the track's outer edge
    "knob_travel": 18,
    # v0.6.4: the check box (CHECKBOX, below). The knob plus a hairline each side, so its inner
    # square is exactly the switch's knob; it fits inside the switch's height and inside one line
    # of body text, so a row of check boxes is never taller than a row with a switch.
    "check_size": 18,
    "check_gap": 10,                # from the box to its label, which is always on its right
    "check_stroke": 2,              # the check mark's line (CHECK_MARK)
    "chip_height": 22,
    "chip_pad_x": 9,
    "count_height": 20,
    "count_min_width": 24,
    "count_pad_x": 8,
    "well_pad": (12, 14),           # text in a well: the preview bubble, a text area
    "stored_pad": (9, 12),          # stored text: a well with no inner shadow
    "callout_pad": (10, 12),
    "callout_gap": 10,
    "callout_badge": 18,
    "nav_pad": (7, 14),             # a page tab or a section item (derived from the segment)
    "fold_chevron": 8,              # a fold's chevron arms, drawn 2px in `muted`
    "skeleton_height": 9,
    "skeleton_radius": 6,
    "focus_width": 2,
    "focus_offset": 2,
    "hairline": 1,
}




def padding(key: str) -> tuple:
    """A LAYOUT padding as (top, right, bottom, left), expanded the way CSS expands it."""
    value = LAYOUT[key]
    if not isinstance(value, tuple):
        value = (value,)
    if len(value) == 1:
        return value * 4
    if len(value) == 2:
        return (value[0], value[1], value[0], value[1])
    if len(value) == 3:
        return (value[0], value[1], value[2], value[1])
    return tuple(value)
