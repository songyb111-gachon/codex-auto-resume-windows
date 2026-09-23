"""Where every piece of the popup goes, in one pass.

A pure function of the view model, the scale and a way to measure text: it returns rectangles
and paints nothing, which is what lets the layout be checked at every language and scale
without a screen.
"""
from __future__ import annotations

from ... import brand
from .words import unbroken


# ---------------------------------------------------------------------------- the pure half
WIDTH = 360                  # device-independent pixels at 96 DPI: the card and 12 px around it


# v0.6.4: the card lifts off the canvas the way the panel's cards do, and its shadow reaches
# 25 px past it. At 20 px the last of it is a third of a colour level, so the window keeps that
# much canvas around the card. Only the canvas grows: the card, and every line of text in it,
# is exactly as wide as it was.
SHADOW_MARGIN = 20


MARK = 22                    # the box the state dot sits in, beside the product's name


# v0.6.4: a task's switch is at the bottom right of its row, as the panel's is, level with its
# label's last line and this far from the end of the label's column (the panel's `.prow-switch` gap).
SWITCH_GAP = 10


STATE_INK = {"monitoring": "accent", "waiting": "waiting", "checking": "accent",
             "recovering": "accent", "paused": "paused", "attention": "warning"}


def share_columns(available, needs) -> list:
    """Widths for columns side by side in `available` pixels, one per need.

    Equal shares while every need fits in one; otherwise each column that needs more is given what
    it needs and the others share what is left alike, repeatedly, until the rest all fit. Only if
    the needs themselves do not fit are they cut down together, each by the same fraction, rather
    than one column taking all of the shortfall.
    """
    count = len(needs)
    needs = [max(0, int(need)) for need in needs]
    total = sum(needs)
    if total > available:
        return [available * need // total for need in needs]
    fixed = {}
    while len(fixed) < count:
        free = [index for index in range(count) if index not in fixed]
        share = (available - sum(fixed.values())) // len(free)
        wider = [index for index in free if needs[index] > share]
        if not wider:
            return [fixed.get(index, share) for index in range(count)]
        fixed.update((index, needs[index]) for index in wider)
    return needs


def layout(vm, scale, measure, width=WIDTH) -> dict:
    """Every rectangle the window draws, in device pixels, and the height it needs.

    `measure(role, text, width, wrap)` returns the (width, height) the text takes in that
    font role - wrapped to `width` when `wrap`, on one line otherwise. Nothing is clipped:
    what does not fit on a line wraps and makes its block taller, and the only text that is
    shortened with an ellipsis is a conversation name and a reason chip.
    """
    space = brand.SPACING

    def px(value):
        return int(round(value * scale))

    # The card is as wide as it has always been; the canvas round it has room for its lift.
    card_width = px(width) - 2 * px(space["m"])
    margin, pad = px(SHADOW_MARGIN), px(space["l"])
    total = card_width + 2 * margin
    left, right = margin + pad, total - margin - pad
    inner = right - left
    items, targets = [], []
    y = margin + pad

    def text(rect, role, value, colour, *, wrap=False, align="left", target=None):
        items.append({"kind": "text", "rect": rect, "role": role, "text": value, "colour": colour,
                      "wrap": wrap, "align": align, "target": target})

    # Header: the state dot, the product, the state in words.
    mark = px(MARK)
    text_left = left + mark + px(space["s"] + 2)
    text_width = right - text_left
    _, title_h = measure("title", vm["title"], text_width, False)
    _, state_h = measure("state", vm["state_text"], text_width, True)
    stack = title_h + state_h
    header_h = max(mark, stack)
    top = y + (header_h - stack) // 2
    items.append({"kind": "halo", "cx": left + mark / 2.0, "cy": y + header_h / 2.0, "state": vm["state"],
                  "radius": brand.glow_extent(brand.STATUS_DOT["popup"]) * scale})
    text((text_left, top, right, top + title_h), "title", vm["title"], "ink")
    text((text_left, top + title_h, right, top + stack), "state", vm["state_text"],
         STATE_INK.get(vm["state"], "ink"), wrap=True)
    y += header_h + px(space["m"])

    # Summary: waiting, recovering, next check - three values read off a field, so since v0.6.5
    # they sit in one sunken well, as the panel's fields do, with a hairline between them. The
    # well's padding comes out of the columns, and an equal third is then narrower than a long word
    # ('Wiederherstellung'), which DrawText would cut in two: a column whose longest word or value
    # needs more is given it, and the others share what is left (share_columns).
    well_top = y
    well_pad = px(space["m"])
    y += well_pad
    gutter = px(space["m"])
    available = inner - 2 * well_pad - 2 * gutter
    needs = [max([measure("label", piece, available, False)[0] for piece in unbroken(label)]
                 + [measure("value", value, available, False)[0]]) for label, value in vm["counts"]]
    columns = share_columns(available, needs)
    label_h = max(measure("label", label, column, True)[1] for (label, _), column in zip(vm["counts"], columns))
    value_h = max(measure("value", value, column, False)[1] for (_, value), column in zip(vm["counts"], columns))
    counts = []
    x = left + well_pad
    for index, ((label, value), column) in enumerate(zip(vm["counts"], columns)):
        if index:
            rule_x = x - gutter // 2
            counts.append({"kind": "rule", "rect": (rule_x, y + px(2), rule_x + max(1, px(1)),
                                                    y + label_h + value_h)})
        counts.append({"kind": "text", "rect": (x, y, x + column, y + label_h), "role": "label", "text": label,
                       "colour": "muted", "wrap": True, "align": "left", "target": None})
        counts.append({"kind": "text", "rect": (x, y + label_h + px(2), x + column,
                                                y + label_h + px(2) + value_h),
                       "role": "value", "text": value, "colour": "ink", "wrap": False, "align": "left",
                       "target": None})
        x += column + gutter
    y += label_h + px(2) + value_h + well_pad
    items.append({"kind": "well", "rect": (left, well_top, right, y)})
    items.extend(counts)
    y += px(space["m"])

    # The tasks, most urgent first.
    row_pad = px(space["m"])
    for task in vm["tasks"]:
        target = ("check", task["interruption_id"])
        row_top = y
        x0, x1 = left + row_pad, right - row_pad
        content = x1 - x0
        contents = []
        chip_text_w, chip_text_h = measure("chip", task["reason"], content, False)
        chip_pad = px(space["s"])
        chip_w = min(chip_text_w + 2 * chip_pad, content // 2)
        chip_h = chip_text_h + px(4)
        name_w = content - chip_w - px(space["s"])
        _, name_h = measure("name", task["name"], name_w, False)
        line_h = max(name_h, chip_h)
        line_top = row_top + row_pad
        contents.append({"kind": "text", "rect": (x0, line_top + (line_h - name_h) // 2, x0 + name_w,
                                                  line_top + (line_h - name_h) // 2 + name_h),
                         "role": "name", "text": task["name"], "colour": "ink", "wrap": False,
                         "align": "left", "target": None})
        chip = (x1 - chip_w, line_top + (line_h - chip_h) // 2, x1, line_top + (line_h - chip_h) // 2 + chip_h)
        contents.append({"kind": "chip", "rect": chip, "tone": task["tone"]})
        contents.append({"kind": "text", "rect": (chip[0] + chip_pad, chip[1], chip[2] - chip_pad, chip[3]),
                         "role": "chip", "text": task["reason"], "colour": task["tone"], "wrap": False,
                         "align": "center", "target": None})
        line = line_top + line_h + px(2)
        _, status_h = measure("small", task["status"], content, True)
        contents.append({"kind": "text", "rect": (x0, line, x1, line + status_h), "role": "small",
                         "text": task["status"], "colour": "muted", "wrap": True, "align": "left",
                         "target": None})
        line += status_h + px(space["s"]) + px(2)
        # A switch, because it turns this conversation's automatic recovery on or off. Since v0.6.4
        # it is where the panel puts it: the label on the left, wrapping in what the switch leaves of
        # the line, and the switch against the row's inner right edge - under the chip - pinned to
        # the bottom of the row: level with the label's last line, however far the label wraps, so
        # it closes the row the way the window's card buttons close theirs. A one-line label is
        # exactly where it was, its line centred on the switch; a longer one keeps its top where a
        # one-line label's is and grows downward, and the switch goes down with its last line. The
        # whole line is still the one thing a click or a key presses.
        track_w, track_h = px(brand.LAYOUT["switch_width"]), px(brand.LAYOUT["switch_height"])
        track_left = x1 - track_w
        label_right = track_left - px(SWITCH_GAP)
        _, label_h = measure("body", task["check_label"], label_right - x0, True)
        _, line_h = measure("body", "Ag", content, False)
        label_top = line + max(0, (track_h - line_h) // 2)
        # The switch stands beside the label's last line exactly as it stands beside a one-line label.
        track_top = line + max(0, label_h - line_h) + max(0, (line_h - track_h) // 2)
        check_h = max(track_top + track_h, label_top + label_h) - line
        contents.append({"kind": "text", "rect": (x0, label_top, label_right, label_top + label_h),
                         "role": "body", "text": task["check_label"], "colour": "ink", "wrap": True,
                         "align": "left", "target": target})
        contents.append({"kind": "switch", "rect": (track_left, track_top, x1, track_top + track_h),
                         "checked": task["checked"], "busy": task["busy"], "target": target})
        hit = (x0 - px(4), line - px(4), x1 + px(4), line + check_h + px(4))
        targets.append((target, hit))
        row_bottom = line + check_h + row_pad
        items.append({"kind": "panel", "rect": (left, row_top, right, row_bottom)})
        items.extend(contents)
        items.append({"kind": "focusable", "rect": hit, "target": target, "radius": px(brand.RADII["small"])})
        y = row_bottom + px(space["s"])

    if vm["more"]:
        _, more_h = measure("small", vm["more"], inner, True)
        text((left, y, right, y + more_h), "small", vm["more"], "muted", wrap=True, align="center")
        y += more_h + px(space["s"])

    quiet = vm["error"] or vm["empty"]
    if quiet:
        # Nothing to list is said from a well: an empty field, not a tile with nothing on it.
        _, quiet_h = measure("body", quiet, inner - 2 * pad, True)
        block = quiet_h + 2 * pad
        items.append({"kind": "well", "rect": (left, y, right, y + block)})
        text((left + pad, y + pad, right - pad, y + pad + quiet_h), "body", quiet, "muted",
             wrap=True, align="center")
        y += block + px(space["s"])

    if vm["zero_note"]:
        _, note_h = measure("small", vm["zero_note"], inner, True)
        text((left, y, right, y + note_h), "small", vm["zero_note"], "muted", wrap=True)
        y += note_h + px(space["s"])

    if vm["notice"]:
        inset = px(space["s"])
        _, notice_h = measure("small", vm["notice"], inner - 2 * inset, True)
        block = notice_h + 2 * inset
        items.append({"kind": "note", "rect": (left, y, right, y + block), "tone": "warning"})
        text((left + inset, y + inset, right - inset, y + inset + notice_h), "small", vm["notice"],
             "warning", wrap=True)
        y += block + px(space["s"])

    # Footer: Pause/Resume and Open Dashboard. Side by side when both fit on one line,
    # stacked when either would not - a German button label is not cut in half.
    y += px(space["xs"])
    button_h = px(32)
    button_pad = px(space["m"])
    buttons = (("toggle", vm["toggle_text"], False, vm["toggle_busy"]),
               ("dashboard", vm["dashboard_text"], True, False))
    half = (inner - px(space["s"])) // 2
    widths = [measure("button", label, inner, False)[0] for _, label, _, _ in buttons]
    if max(widths) + 2 * button_pad <= half:
        placed = [((left, y, left + half, y + button_h), False), ((right - half, y, right, y + button_h), False)]
        y += button_h
    else:
        placed = []
        for index, (_, label, _, _) in enumerate(buttons):
            _, label_h = measure("button", label, inner - 2 * button_pad, True)
            height = max(button_h, label_h + 2 * px(space["s"]))
            placed.append(((left, y, right, y + height), True))
            y += height + (px(space["s"]) if index == 0 else 0)
    for (name, label, primary, busy), (rect, wrapped) in zip(buttons, placed):
        target = (name,)
        items.append({"kind": "button", "rect": rect, "primary": primary, "busy": busy, "target": target})
        if wrapped:
            _, label_h = measure("button", label, rect[2] - rect[0] - 2 * button_pad, True)
            top = rect[1] + (rect[3] - rect[1] - label_h) // 2
            label_rect = (rect[0] + button_pad, top, rect[2] - button_pad, top + label_h)
        else:
            label_rect = (rect[0] + button_pad, rect[1], rect[2] - button_pad, rect[3])
        items.append({"kind": "text", "rect": label_rect, "role": "button", "text": label,
                      "colour": "on_accent" if primary else "ink", "wrap": wrapped, "align": "center",
                      "target": target})
        targets.append((target, rect))
        items.append({"kind": "focusable", "rect": rect, "target": target, "radius": px(brand.RADII["control"])})
    y += pad
    card = (margin, margin, total - margin, y)
    items.insert(0, {"kind": "card", "rect": card, "radius": px(brand.RADII["card"])})
    return {"size": (total, y + margin), "card": card, "items": items, "targets": targets, "scale": scale}
