"""The icon's right-click menu as the popup draws it (v0.6.20): where each item goes, where it opens, which key reaches what.

Until v0.6.20 the menu was Windows' own (TrackPopupMenu), asked to be dark when the popup was. The owner asked for it
in the product's design (2026-11-01), as the window's menus have been since v0.6.18 (gui/SoftMenu.cs): a card of the
cards' material - their ground, radius, hairline and in dark their one-pixel top light - lifted by the cards' own
shadow, which falls outside the card over whatever is behind it. The item in hand rises into a raised pill with the
control's lift, its words in the ink; an item that cannot be used is in the muted ink; the chosen one of a set is a dot
in the accent; a line between groups is a hairline.

The items themselves - their words, order, states and what each does - are the icon's (ui/tray/menu.py menu_items), the
same list its Windows menu is built from, so the two cannot drift apart. The popup's row menus (model.row_menu) are drawn
by the same code since the owner asked for it the same day: theirs have submenus, an item whose `items` is a list, drawn
with an arrow at its far end and opened beside it (menu_beside) as a second menu of the same kind. This half is pure: it
asks Windows nothing and paints nothing, which is what lets it be checked at every scale and in every language without a
screen. The window that draws it and hears the keys is menuwindow.py.
"""
from __future__ import annotations

from ... import brand
from .words import say


MENU_CHECK = 24          # the column at an item's start where a chosen item's dot is drawn (SoftMenu's check margin)
MENU_MIN_WIDTH = 160     # the card's least width, in device-independent pixels, as a menu of Windows' has one


def _reach() -> float:
    """How far the cards' lift reaches past a card, in device-independent pixels: three sigmas past the farthest
    offset of any theme's outer shadows (notice_card's measure). The window keeps that much room round the card."""
    shadows = [shadow for theme in brand.THEMES for shadow in brand.shadows("card", theme) if not shadow.inset]
    return max((max(abs(shadow.dx), abs(shadow.dy)) + 1.5 * shadow.blur for shadow in shadows), default=0.0) + 2


MENU_REACH = _reach()


def menu_layout(entries, scale, measure, max_width=None) -> dict:
    """Every rectangle of the menu in device pixels, left to right, and the window's size.

    `entries` is the icon's list: a dict per item (`id`, `text`, `enabled`, `checked`, and `items` when it opens a
    submenu) and None for a line between groups. `measure(role, text, width, wrap)` returns the (width, height) of a
    line in the popup's font role. The card is as wide as its widest item needs and no narrower than MENU_MIN_WIDTH;
    `max_width` (the work area) caps the window, and a line wider than what is left is shortened with an ellipsis by
    the renderer, never wrapped.
    """
    space = brand.SPACING

    def px(value):
        return int(round(value * scale))

    margin = int(round(MENU_REACH * scale))
    pad = px(space["xs"])                       # inside the card, round its items (SoftMenuLayer.Pad)
    room = px(space["xs"])                      # above and below an item's words (SoftMenuRenderer.Fit)
    gap = max(1, px(1))                         # between two items (Fit's margin)
    check = px(MENU_CHECK)
    after = px(space["l"])                      # from the words to the item's far end
    hairline = max(1, px(1))
    rule_h = px(space["s"]) + hairline
    _, line_h = measure("body", "Ag", 10 ** 4, False)
    item_h = line_h + 2 * room
    widths = [measure("body", entry["text"], 10 ** 4, False)[0] for entry in entries if entry]
    inner = max([check + width + after for width in widths] + [px(MENU_MIN_WIDTH) - 2 * pad])
    if max_width is not None:
        inner = max(check + after + px(space["l"]), min(inner, int(max_width) - 2 * margin - 2 * pad))
    left = margin + pad
    right = left + inner
    items, targets = [], []
    y = margin + pad
    for index, entry in enumerate(entries):
        if entry is None:
            middle = y + (rule_h - hairline) // 2
            inset = px(space["s"])
            items.append({"kind": "rule", "index": index, "rect": (left + inset, middle, right - inset, middle + hairline)})
            y += rule_h
            continue
        y += gap
        rect = (left, y, right, y + item_h)
        dot = max(px(6), check // 4)
        cx, cy = left + check // 2, y + item_h // 2
        laid = {"kind": "item", "index": index, "id": entry.get("id"), "text": entry["text"],
                "enabled": bool(entry["enabled"]), "checked": bool(entry.get("checked")), "rect": rect,
                "text_rect": (left + check, y, right - after, y + item_h),
                "dot": (cx - dot // 2, cy - dot // 2, cx - dot // 2 + dot, cy - dot // 2 + dot),
                "align": "left", "submenu": bool(entry.get("items"))}
        if laid["submenu"]:
            laid["arrow"] = (right - after, y, right - pad, y + item_h)     # where its arrow is drawn
        items.append(laid)
        if entry["enabled"]:
            targets.append((index, rect))
        y += item_h + gap
    bottom = y + pad
    card = (margin, margin, right + pad, bottom)
    return {"size": (card[2] + margin, bottom + margin), "card": card, "items": items, "targets": targets,
            "scale": scale, "rtl": False}


def menu_mirror(plan) -> dict:
    """The menu right to left: every rectangle across the window from where it is, so the dot's column is at the right
    and every line is aligned right - as popup.mirror turns the popup, and as Windows lays out a menu with
    TPM_LAYOUTRTL. The card's lift keeps the brand's one light, up and to the left, in every language."""
    width = plan["size"][0]

    def across(rect):
        return (width - rect[2], rect[1], width - rect[0], rect[3])

    items = []
    for item in plan["items"]:
        turned = dict(item, rect=across(item["rect"]))
        for key in ("text_rect", "dot", "arrow"):
            if key in item:
                turned[key] = across(item[key])
        if "align" in item:
            turned["align"] = "right"
        items.append(turned)
    return dict(plan, items=items, card=across(plan["card"]), rtl=True,
                targets=[(index, across(rect)) for index, rect in plan["targets"]])


def menu_place(plan, point, work) -> tuple:
    """Where the window goes, (x, y), for a menu opened at `point` on a monitor whose work area is `work`.

    As Windows places a menu opened at a point: the card's corner at the point, opening right and down - left first,
    right to left - turned the other way along an axis where it would not fit, and then kept inside the work area
    (left, top, right, bottom, physical pixels, negative on a monitor left of or above the primary one). The shadow
    may reach past the work area; the card never does."""
    card = plan["card"]
    width, height = card[2] - card[0], card[3] - card[1]
    left, top, right, bottom = work
    px, py = point
    if plan.get("rtl"):
        x = px - width if px - width >= left else px
    else:
        x = px if px + width <= right else px - width
    y = py if py + height <= bottom else py - height
    x = max(left, min(x, right - width)) if right - left >= width else left
    y = max(top, min(y, bottom - height)) if bottom - top >= height else top
    return x - card[0], y - card[1]


def menu_beside(plan, beside, work) -> tuple:
    """Where a submenu's window goes, (x, y): its card beside `beside` - the parent's card's left and right and its
    item's top and bottom, on the screen - to the right, or to the left right to left or where the right has no room
    (and the other way round), its first item level with the parent's item, kept inside the work area as a menu is."""
    card = plan["card"]
    width, height = card[2] - card[0], card[3] - card[1]
    left, top, right, bottom = work
    first = next((item["rect"][1] for item in plan["items"] if item["kind"] == "item"), card[1])
    if plan.get("rtl"):
        x = beside[0] - width if beside[0] - width >= left else beside[2]
    else:
        x = beside[2] if beside[2] + width <= right else beside[0] - width
    y = beside[1] - (first - card[1])
    x = max(left, min(x, right - width)) if right - left >= width else left
    y = max(top, min(y, bottom - height)) if bottom - top >= height else top
    return x - card[0], y - card[1]


def menu_numbered(entries) -> tuple:
    """A row menu's entries (model.row_menu: `action` and `items`) as both menus take them: each item that does
    something numbered from 1, depth first, as Windows' menu numbers its commands - `id`, and None for an item that
    opens a submenu - and {number: action}, None for an item that cannot be used. Pure."""
    actions = {}

    def number(items):
        found = []
        for entry in items:
            if entry is None:
                found.append(None)
                continue
            if entry.get("items"):
                found.append(dict(entry, id=None, items=number(entry["items"])))
                continue
            command = len(actions) + 1
            actions[command] = entry.get("action") if entry.get("enabled") else None
            found.append(dict(entry, id=command, items=None))
        return found
    return number(entries), actions


# ------------------------------------------------------------------------------ keys
def menu_usable(entries) -> list:
    """The indexes of the items a key or a click can choose, in order: every enabled item, no line."""
    return [index for index, entry in enumerate(entries) if entry is not None and entry.get("enabled")]


def menu_step(entries, current, backwards=False):
    """The item an arrow reaches from `current`: the next usable one, round from the end to the start, as Windows'
    menus go. From nothing, Down reaches the first and Up the last. None when nothing can be used."""
    usable = menu_usable(entries)
    if not usable:
        return None
    if current not in usable:
        return usable[-1] if backwards else usable[0]
    return usable[(usable.index(current) + (-1 if backwards else 1)) % len(usable)]


def menu_end(entries, last=False):
    """Home's item, or End's: the first usable one, or the last. None when nothing can be used."""
    usable = menu_usable(entries)
    return (usable[-1] if last else usable[0]) if usable else None


def menu_letter(entries, current, char) -> tuple:
    """What a typed character does, as in Windows' menus whose items have no access key: each item's first letter is
    its key. One usable item starting with it is chosen - (index, True); several are stepped through from `current`
    - (index, False); none leaves the menu as it is - (current, False). Case is not told apart."""
    wanted = str(char or "").casefold()
    if not wanted.strip():
        return current, False
    found = [index for index in menu_usable(entries)
             if str(entries[index].get("text") or "").lstrip()[:1].casefold() == wanted]
    if not found:
        return current, False
    if len(found) == 1:
        return found[0], True
    later = [index for index in found if current is not None and index > current]
    return (later[0] if later else found[0]), False


# ------------------------------------------------------------------------------ a screen reader
def menu_accessible_items(plan, selected=None, strings=None) -> list:
    """The menu's children for a screen reader, in the order drawn, shaped as access.accessible_items' are.

    Each item is a `menuitem` named with its words: unavailable when it cannot be used, checked when it is the chosen
    one, focusable when it can, and focused and hot while it is the item in hand - its default action the one press
    that chooses it. A line between groups is a `separator`. Nothing on screen is no child."""
    if not plan:
        return []
    found = []
    for item in plan.get("items") or ():
        if item["kind"] == "rule":
            found.append({"role": "separator", "name": "", "value": None, "description": None, "states": [],
                          "rect": tuple(item["rect"]), "target": None, "action": None})
            continue
        states = set()
        if item["checked"]:
            states.add("checked")
        if item.get("submenu"):
            states.add("haspopup")
        if item["enabled"]:
            states.add("focusable")
            if item["index"] == selected:
                states.update(("focused", "hot"))
        else:
            states.add("unavailable")
        found.append({"role": "menuitem", "name": item["text"], "value": None, "description": None,
                      "states": sorted(states), "rect": tuple(item["rect"]),
                      "target": item["index"] if item["enabled"] else None,
                      "action": say(strings, "popup.a11y_press") if item["enabled"] else None})
    return found
