"""Make the README's motion pictures: the product at work, every frame drawn by its own code, offscreen.

    python -X utf8 build/make_motion.py                 # docs/images/readme-motion.png and readme-motion-ko.png
    python -X utf8 build/make_motion.py readme-en       # one of them (a plan's name under build/motion/, or a path)
    python -X utf8 build/make_motion.py --dry-run       # only the frames each plan asks for, scene by scene
    python -X utf8 build/make_motion.py --fidelity      # only the window held to today's stills, recorded
    python -X utf8 build/make_motion.py card-en card-ko # the notification card appearing, on its own
    python -X utf8 build/make_motion.py logo-light logo-dark   # the README's logo, moving (build/motion_logo.py)
    python -X utf8 build/make_motion.py popup-en popup-ko   # the notification-area popup opened, used and closed
    python -X utf8 build/make_motion.py --all           # all ten: the final's picture pass

The README's two show the Dashboard alone, the window bare, with no shadow (RGBA, its rounded corners clear);
the card's two the card appearing as the product shows it, on the canvas colour; the popup's two the popup the icon
opens, its switch turned off and on again, on the canvas colour (build/motion_popup.py); the logos the icon's own
watching motion.

A plan (build/motion_plan.py, build/motion/*.json) says what a person does, scene by scene, on one clock. Each frame
is then drawn:

- the window's client area by the window itself, in its render mode (gui/WindowRender.cs, build/motion_window.py):
  a compiled copy of the working tree's window, never on the screen, answered from the generator's pinned scratch
  installation, put in the frame's page, section, scroll, hover or pressed face, drop-down value or open list, its
  lights at the frame's moment;
- round it, the caption, frame and corners of one captured still (assets/screenshot-dashboard.png) and a drawn
  shadow (build/motion_compose.py);
- under it a plain taskbar strip with the tray icon's own frame at that moment (ui.tray.IconFrames, icon_frame);
- over it the notification card's own paint at that moment of its life (build/motion_card.py);
- over everything a pointer and a click's ring of our own - never the real pointer.

Then identical frames are merged and the frames written as a lossless APNG within the plan's byte budget
(build/motion_apng.py): over the cap nothing is written and the bytes of each scene are printed. Before any picture,
every page the window draws at rest is held to today's committed still (build/motion_fidelity.py) and the result is
recorded, with the picture's inputs, in assets/motion.json; a page that fails stops the run.

It captures nothing and moves no pointer: nothing is shown on the screen. It needs Windows (the window and the card
are drawn with its GDI and GDI+), the in-box C# compiler, and the display at the scale the stills were captured at
(assets/screenshots.json's system_dpi). Run it from the main session after the stills are made, detached, under
plans/proof/quiet.sh like every picture; it takes minutes, most of them the window settling on each page.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "src"), str(ROOT / "build")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import motion_plan  # noqa: E402

PLAN_NAMES = ("readme-en", "readme-ko")
# The notification card on its own (APNG-storyboard.md section 5): drawn only when named, or with --all - the
# final's picture pass draws it beside the README's two.
CARD_PLANS = ("card-en", "card-ko")
# The README's logo, moving as the icon does while watching (build/motion_logo.py): by name, or with --all.
LOGO_PLANS = ("logo-light", "logo-dark")
# What opens when the notification-area icon is clicked, moving (docs/images/tray-popup-motion*.png, beside the card's):
# by name, or with --all. The still beside them, tray-popup.png, stays make_screenshots' own.
POPUP_PLANS = ("popup-en", "popup-ko")
ALL_PLANS = PLAN_NAMES + CARD_PLANS + POPUP_PLANS + LOGO_PLANS
MANIFEST = ROOT / "assets" / "motion.json"
# What the picture is made from, beside the window, the card and the icon: these files.
CODE = ("build/make_motion.py", "build/motion_plan.py", "build/motion_window.py", "build/motion_card.py",
        "build/motion_compose.py", "build/motion_apng.py", "build/motion_fidelity.py", "build/motion_logo.py")


def plan_path(name) -> Path:
    """A plan named by its file under build/motion/, or a path to one."""
    path = Path(name)
    if path.suffix == ".json" and path.is_file():
        return path
    return motion_plan.PLANS / ("%s.json" % name)


def load(name) -> dict:
    """A plan by name or path: a logo plan as it is written (it has no scenes - the icon's own cycle is its story),
    every other one read and checked by motion_plan."""
    path = plan_path(name)
    plan = json.loads(path.read_text(encoding="utf-8"))
    if plan.get("kind") == "logo":
        if plan.get("format") != motion_plan.FORMAT or not {"name", "output", "size"} <= set(plan):
            raise motion_plan.PlanError("%s is not a logo plan" % path.name)
        return plan
    return motion_plan.load(path)


def schedule(plan: dict, also=()) -> tuple:
    """(frames, delays in ms, end in ms): every frame the plan's steps emit, with the frames the lights, the
    ripples and `also` (the tray icon's frame times) add, each with the delay it is held for."""
    end = motion_plan.plan_end(plan)
    frames = motion_plan.fill(motion_plan.expand(plan), end, int(plan.get("light_step_ms") or 0), also,
                              first_hold=int(plan.get("first_hold") or 0), ripple_step=int(plan.get("ripple_step") or 0))
    return frames, motion_plan.delays([frame.t for frame in frames], end), end


def run(plan: dict, draw, also=()):
    """(delay in ms, scene, picture) for each frame of the plan, drawn by `draw(frame)`, one at a time: a
    frame whose picture is the one before's only lengthens it, so a picture is written once however long it holds.
    The first is always frame 1, even when the next is the same."""
    frames, held, _end = schedule(plan, also)
    previous = None
    for frame, delay in zip(frames, held):
        picture = draw(frame)
        if previous is not None and picture == previous[2]:
            previous[0] += delay
            continue
        if previous is not None:
            yield tuple(previous)
        previous = [delay, frame.scene, picture]
    if previous is not None:
        yield tuple(previous)


def describe(plan: dict, also=()) -> str:
    """The frames a plan asks for, scene by scene, for reading before anything is drawn."""
    frames, held, end = schedule(plan, also)
    lines, counts = [], {}
    for frame, delay in zip(frames, held):
        entry = counts.setdefault(frame.scene, [0, 0, frame.t])
        entry[0] += 1
        entry[1] += delay
    for scene, (count, ms, start) in counts.items():
        lines.append("  %-5s at %6.2f s  %3d frames  %5.2f s" % (scene, start / 1000.0, count, ms / 1000.0))
    lines.append("  %d frames, %.2f s, %d window states, targets: %s"
                 % (len(frames), end / 1000.0, len(motion_plan.window_states(frames)),
                    ", ".join(sorted(motion_plan.pointer_targets(frames)))))
    return "\n".join(lines)


def describe_logo(plan: dict) -> str:
    """What a logo plan draws: one cycle of the icon's own motion."""
    import motion_logo
    cycle = motion_logo.cycle(plan.get("state", "watching"))
    return "  %d px, %s, one cycle of the icon's watching motion: %d frames, %.2f s" % (
        plan["size"], "dark" if plan.get("dark") else "light", len(cycle), sum(item[0] for item in cycle) / 1000.0)


# ---------------------------------------------------------------------------------------------------- inputs
def icon_moments(plan: dict, end: int) -> list:
    """The moments the tray icon's own timer shows a new frame at, over the picture: none without a taskbar."""
    if "taskbar" not in plan:
        return []
    import make_screenshots
    state = (plan.get("taskbar") or {}).get("icon", {}).get("state", "watching")
    return [at for at, _position, _level in make_screenshots.icon_timeline(state, 0.0, float(end))]


def render_input(plan: dict) -> str:
    """The digest a motion picture is made from: its plan as read, the window's sources, what draws the card and the
    icon, the catalogs of its languages, the still its frame is taken from and this generator's own files - so a
    change to any of them marks the picture stale (tests/test_motion_fidelity.py). A logo's is motion_logo's."""
    if plan.get("kind") == "logo":
        import motion_logo
        return motion_logo.render_input(plan)
    import make_screenshots as shots
    parts = [json.dumps(plan, sort_keys=True, ensure_ascii=False), shots.card_drawing()]
    if "popup" in plan:
        # The sample rows and what draws the popup (the still's own key), and the file that sequences it.
        parts += [shots.popup_render_input(plan["popup"].get("locale", plan["locale"])),
                  shots.input_digest(ROOT / "build" / "motion_popup.py")]
    if "window" in plan:
        parts.append(shots.window_digest())
    if "taskbar" in plan:
        parts.append(shots.icon_drawing())
    for locale in sorted(plan.get("forms") or {plan.get("locale", "en"): {}}):
        parts.append(shots.input_digest(ROOT / "src" / "codex_auto_resume" / "locales" / ("%s.json" % locale)))
    if "window" in plan:
        parts.append(shots.input_digest(ROOT / plan["window"]["still"]))
    parts += [shots.input_digest(ROOT / name) for name in CODE]
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


def read_manifest() -> dict:
    if MANIFEST.is_file():
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {"inputs": {}, "images": {}, "fidelity": {}}


def write_manifest(manifest: dict) -> None:
    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------------------------------- making one
def make(plan: dict, exe: Path | None, work: Path, forms=None) -> object:
    """Draws `plan`'s picture into its output and returns the assembler's Report. A plan with no `window` (the card
    on its own) is drawn on the plain canvas and needs no window (`exe` may be None); one with no `taskbar` has no
    strip and no icon; `card.at`, where given, is where the settled card's top-left stands."""
    import make_screenshots as shots
    import motion_apng
    import motion_card
    import motion_compose
    import motion_window
    from codex_auto_resume import brand
    from codex_auto_resume.ui import tray
    end = motion_plan.plan_end(plan)
    frames, _held, _end = schedule(plan, icon_moments(plan, end))
    canvas = plan["canvas"]
    width, height = canvas["size"]
    theme, design = canvas.get("theme", "light"), canvas.get("design", brand.DEFAULT_DESIGN)
    # A clear canvas: everything outside what is pictured is transparent, RGBA (the window on its own).
    clear = bool(canvas.get("transparent"))
    ground = None if clear else tuple(brand.rgb(brand.palette(theme, design)[canvas.get("ground", "canvas")]))
    if "window" in plan:
        job = motion_window.job(plan, frames, work / "frames", forms)
        result = motion_window.render(exe, job, work)
        pictures = motion_window.pictures(result, work / "frames")
        still = shots.read_png(ROOT / plan["window"]["still"])
        chrome = motion_compose.WindowChrome(still, tuple(result["client"]), size=(width, height),
                                             at=tuple(plan["window"]["at"]), ground=ground,
                                             shadow=bool(canvas.get("shadow", True)),
                                             scale=float(result.get("dpi_scale") or 1.5))
        origin = chrome.client_origin()
        # A clear canvas is exactly the union of the window and its shadow, if it has one: an empty border would
        # only push the picture's caption away on the page (the owner, 2026-10-19). The pointer stays on the window.
        border = chrome.empty_border()
        if clear and any(border):
            raise SystemExit("the canvas %dx%d has an empty border (left, top, right, bottom) of %s: make it "
                             "smaller by that and move the window and the pointer's rest by the left and top"
                             % (width, height, border))
    else:
        pictures, chrome, origin = None, None, (0, 0)
        plain = bytes(width * height * 4) if clear else bytes(ground) * (width * height)
    strip = plan.get("taskbar")
    anchor = None
    if strip:
        icon = strip["icon"]
        icon_left = width - icon["right"] - icon["size"]
        icon_top = strip["top"] + (strip["height"] - icon["size"]) // 2
        icons = tray.IconFrames(icon["size"])
        anchor = (icon_left, icon_top, icon_left + icon["size"], icon_top + icon["size"])
    popup_plan, popup = plan.get("popup"), None
    if popup_plan:
        import motion_popup
        popup = motion_popup.PopupFrames(popup_plan.get("locale", plan["locale"]), scale=popup_plan["scale"],
                                         theme=theme, design=design)
        if tuple(popup.size) != (width, height):
            popup.close()
            raise SystemExit("the popup is drawn %dx%d and the canvas is %dx%d: make the stills again, or the "
                             "canvas the size of the popup's still" % (tuple(popup.size) + (width, height)))
        if not popup.is_the_still(frames[0], plain, ROOT / popup_plan["still"]):
            popup.close()
            raise SystemExit("the popup's first frame is not %s as it is committed: make the stills again first "
                             "(build/make_screenshots.py)" % popup_plan["still"])
    card_plan, card = plan.get("card"), None
    if card_plan:
        card = motion_card.CardFrames(card_plan.get("locale", plan["locale"]), scale=card_plan["scale"],
                                      work=(0, 0, width, strip["top"] if strip else height),
                                      monitor=(0, 0, width, height), anchor=anchor, theme=theme, design=design)
        if "at" in card_plan:
            card.place = tuple(card_plan["at"])
    accent = tuple(brand.rgb(brand.palette(theme, design)["accent"]))
    scale = float((plan.get("pointer") or {}).get("scale", 1.5))
    seen_bounds, standing = {}, {}

    def draw(frame):
        if popup is not None:
            return popup.drawn(frame, plain)          # nobody points, and no window, strip or card
        if pictures is not None:
            _index, client, bounds = next(pictures)
            seen_bounds.update(bounds)
            picture = chrome.frame(client)
        else:
            picture = bytearray(plain)
        if strip:
            motion_compose.draw_strip(picture, width, height, strip["top"], strip["height"],
                                      tuple(brand.rgb(strip["colour"])))
            position, level = tray.icon_frame(icon["state"], frame.t, frame.t)
            head = tray.icon_level_colour(tray.icon_head_colour(icon["state"]), level)
            motion_compose.draw_icon(picture, width, height, icons.compose(position, head), icon["size"],
                                     icon_left, icon_top)
        state = dict(frame.card) if frame.card else None
        if state is not None and card is not None:
            card.lay_on(picture, width, height, card.drawn(frame.t, state["born"], hover=state["hover"],
                                                           pressed=state["pressed"], leave=state["leave"]))
        if plan.get("pointer") is None:
            return bytes(picture)                     # nobody points: the card appearing on its own
        # A pointer that has come to rest stays where it came to rest, whatever moves under it.
        if frame.pointer[0] == "at" and frame.pointer in standing:
            x, y = standing[frame.pointer]
        else:
            x, y = motion_compose.pointer_at(frame, seen_bounds, origin, card)
            standing.clear()
            if frame.pointer[0] == "at":
                standing[frame.pointer] = (x, y)
        window = dict(frame.window)
        pressed = window.get("pressed") is not None or bool(state and state["pressed"])
        motion_compose.draw_pointer(picture, width, height, x, y, scale=scale, pressed=pressed,
                                    ripple=motion_plan.ripple_at(frame), accent=accent)
        return bytes(picture)

    budget = plan.get("budget") or {}
    try:
        return motion_apng.assemble(ROOT / plan["output"], width, height,
                                    run(plan, draw, icon_moments(plan, end)),
                                    target=budget.get("target"), cap=budget.get("cap"), alpha=clear)
    finally:
        if card is not None:
            card.close()
        if popup is not None:
            popup.close()


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    names = [item for item in argv if not item.startswith("--")] or list(ALL_PLANS if "--all" in argv
                                                                          else PLAN_NAMES)
    plans = [load(name) for name in names]
    if "--dry-run" in argv:
        for plan in plans:
            print("%s -> %s" % (plan["name"], plan.get("output")))
            print(describe_logo(plan) if plan.get("kind") == "logo" else describe(plan))
        return 0
    import make_screenshots as shots
    import motion_fidelity
    import motion_window
    # A card on its own has no window: no stills to be fresh, no window to hold to them.
    windowed = any("window" in plan for plan in plans)
    recorded = json.loads(shots.MANIFEST.read_text(encoding="utf-8"))
    if windowed and shots.system_dpi() != recorded.get("system_dpi"):
        raise SystemExit("the display is at %s DPI and the stills were captured at %s: make them again first"
                         % (shots.system_dpi(), recorded.get("system_dpi")))
    if windowed and recorded["inputs"].get("<window sources>") != shots.window_digest():
        raise SystemExit("the window's stills are stale: run build/make_screenshots.py first")
    manifest = read_manifest()
    with tempfile.TemporaryDirectory() as name:
        work = Path(name)
        exe = motion_window.compile_window(work) if windowed else None
        locales = sorted({locale for plan in plans if "window" in plan for locale in plan.get("forms", {})})
        forms = {locale: {"answers": motion_window.answers(locale)} for locale in locales}
        results = motion_fidelity.check(exe, work, locales, forms) if windowed else {}
        if windowed:
            manifest["fidelity"] = dict(results, window=shots.window_digest())
            write_manifest(manifest)
        failed = sorted(key for key, result in results.items() if not result["passed"])
        for key in sorted(results):
            result = results[key]
            print("fidelity %-18s %s  exact %.4f%%  worst %d  outside %d  light %d"
                  % (key, "pass" if result["passed"] else "FAIL", 100 * result["exact"], result["worst"],
                     result["outside"], result["light"]))
        if failed:
            raise SystemExit("the window drawn offscreen is not the captured one on %s" % ", ".join(failed))
        if "--fidelity" in argv:
            return 0
        for plan in plans:
            if plan.get("kind") == "logo":
                import motion_logo
                report = motion_logo.make(plan)
                size = (int(plan["size"]),) * 2
            else:
                plan_forms = {locale: {"answers": motion_window.answers(locale, stored)}
                              for locale, stored in plan.get("forms", {}).items()}
                # Another state of the installation each language's frames may be in (`variant`): the replies of a
                # paused one, under "<locale>-paused" (gui/WindowRender.cs opens the window on them).
                for variant in plan.get("variants", ()):
                    for locale, stored in plan.get("forms", {}).items():
                        plan_forms["%s-%s" % (locale, variant)] = {"answers": motion_window.answers(
                            locale, stored, paused=variant == "paused")}
                report = make(plan, exe, work / plan["name"], plan_forms)
                size = tuple(plan["canvas"]["size"])
            output = ROOT / plan["output"]
            key = str(Path(plan["output"])).replace("\\", "/")
            manifest["inputs"]["<motion:%s>" % plan["name"]] = render_input(plan)
            manifest["images"][key] = {"sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                                       "size": "%dx%d" % size, "bytes": report.size,
                                       "frames": report.frames, "ms": report.ms,
                                       "scenes": report.scenes}
            write_manifest(manifest)
            print("%s  %d bytes, %d frames, %.2f s%s" % (key, report.size, report.frames, report.ms / 1000.0,
                                                         "  OVER THE TARGET" if report.over_target else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
