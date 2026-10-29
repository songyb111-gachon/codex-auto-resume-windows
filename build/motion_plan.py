"""The frame plan of a rendered motion picture: scenes of pinned states, read from a file, expanded to frames.

A motion picture of the product (plans/v0616-readme/APNG-storyboard.md) is never filmed: every frame is drawn by the
product's own code on a pinned clock, from synthetic data, and the pointer is drawn onto it afterwards. What is drawn
when is written down here, as a plan file under build/motion/, scene by scene, and nothing about the motion is decided
anywhere else - the window's render mode (gui/WindowRender.cs) is told a state per frame and draws it, the card is
told a moment, and the compositor is told where the pointer stands.

A plan is JSON:

    {"format": "car-motion/1", "name": "readme-en", "output": "docs/images/readme-motion.png",
     "scenes_from": "readme-scenes.json", "values": {"first": "en", "second": "ko"},
     "light_step_ms": 33, "length": [25000, 35000], "budget": {"cap": 9000000},
     ...the canvas, the window, the taskbar and the card (make_motion.py reads those)...}

`scenes` (or the file `scenes_from` names, beside it) is a list of {"id", "steps"}. A `${name}` anywhere in the scenes
is replaced by `values[name]`, so one storyboard serves both READMEs. Each step starts where the one before ended:

    {"hold": ms}                                   nothing changes; only the lights move
    {"set": {...}, "hold": ms}                     a cut: the window's state changes at once
    {"move": target, "frames": n, "step": ms}      the pointer travels to `target`, eased (brand.ease)
    {"hover": target, "frames": n, "step": ms}     the target shows its hover face
    {"press": target, "frames": n, "step": ms}     ...its pressed face, and a ripple where the pointer is
    {"card": "enter" | "shown" | "leave", "frames": n, "step": ms}   ("shown": already at rest)
    {"wheel": notches, "frames": n, "step": ms}    the page scrolls as SoftPage glides it
    {"open": "setting.<field>", "frames": n, "step": ms, "hold": ms}   the field's drop list fades in, then holds
    {"rows": [value, ...], "step": ms}             the pointer's row in the open list, one after another
    {"choose": value, "hold": ms}                  the list closes with `value` shown (not saved)
    {"right": "task.<n>", "frames": n, "step": ms, "hold": ms}   a right click on a Pending row: it is chosen, a
                                                   ripple where the pointer is, and the row's own menu opens there
    {"dismiss": "menu", "hold": ms}                the menu closes with nothing chosen (Escape)
    {"popup": "open" | "close", "hold": ms}        the notification-area popup is shown at once, or hidden at once (it
                                                   has no entrance of its own: ShowWindow, SW_HIDE)
    {"ask": row, "frames": n, "step": ms}          the popup's row n (1 is the first) has had its switch pressed: it
                                                   is drawn half faded while the control layer's answer is awaited
    {"switch": row, "to": "off" | "on", "frames": n, "step": ms}   the answer came: the switch glides to its new place
                                                   (ui.popup.motion.glide_amount, brand's transition time and curve)

A target is a name the window answers with bounds (`page.<name>`, `section.<name>`, `save`, `setting.<field>`,
`row.<value>` in an open drop list, `task.<n>` - the Pending list's row n - `menu.<n>` - item n of the open row
menu, which a hover in it names - and `popup.switch.<n>` - row n's Auto-resume switch in the notification-area
popup), a button of the card (`card.<target>`), `{"at": [x, y]}` on the canvas, or `{"by": [dx, dy]}` from where the
pointer is. Window states use the keys `STATE_KEYS`; the render mode refuses any
other. Every frame is a moment `t` in ms from the start, and everything that moves by itself - the window's lights,
the card's light, the tray icon - is drawn at that moment, so a plan only says what a person does.
"""
from __future__ import annotations

import bisect
import copy
import json
import math
from pathlib import Path
import re
from typing import NamedTuple

FORMAT = "car-motion/1"
HERE = Path(__file__).resolve().parent
PLANS = HERE / "motion"

# The window state a frame may set (gui/WindowRender.cs reads exactly these).
STATE_KEYS = ("locale", "page", "section", "scroll", "hover", "pressed", "combo", "droplist", "selected", "menu")
PAGES = ("overview", "pending", "history", "statistics", "diagnostics", "settings")
SECTIONS = ("general", "recovery", "continuation", "appearance", "advanced")
STEPS = ("hold", "set", "move", "hover", "press", "card", "wheel", "open", "rows", "choose", "right", "dismiss",
         "popup", "ask", "switch")
# The steps that may say how long their one frame holds.
HOLDING = ("set", "open", "choose", "right", "dismiss", "popup")
# The shortest a frame is held, in ms: the product's own quickest step (a scroll's glide and a drop list's fade tick
# every 15 ms, the card's every 16). Delays are whole milliseconds, exact; browsers show 10 ms or less as 100 ms.
SHORTEST = 15
# The least an added frame's moment may be from another's, in ms: room for its changes to be written as two
# rectangles of SHORTEST each (motion_apng.patches) - a light at the top of the picture and the
# tray icon at its bottom - rather than one round both.
CLOSEST = 2 * SHORTEST
# How long a click's ripple lasts (TOOLING 2.3), in ms.
RIPPLE_MS = 240
NAME = re.compile(r"(page\.(%s)|section\.(%s)|save|restore|start|close|setting\.[a-z_]+|row\.[A-Za-z_-]+|card\.[a-z_]+"
                  r"|task\.[0-9]+|menu\.[0-9]+|popup\.switch\.[0-9]+)\Z"
                  % ("|".join(PAGES), "|".join(SECTIONS)))


class PlanError(ValueError):
    """A plan that cannot be drawn as written."""


class Frame(NamedTuple):
    """One moment of the picture: what the window, the card and the pointer are at `t` (ms)."""
    t: int
    scene: str
    window: tuple          # sorted (key, value) pairs of the window's state; values JSON-safe and hashable
    card: tuple            # () with no card, else (("born", ms), ("hover", name), ("pressed", name), ("leave", ms))
    pointer: tuple         # ("at", target) or ("move", from target, to target, eased fraction)
    ripple: tuple          # () or (target the press was on, ms it began)
    popup: tuple = ()      # () with no popup open, else (("busy", rows), ("glides", ((row, (start, from, to)), ...)),
                           # ("off", rows), ("opened", ms)): rows are the popup's, counted from 1


def _frozen(value):
    """`value` made hashable: dicts as sorted pairs, lists as tuples."""
    if isinstance(value, dict):
        return tuple(sorted((key, _frozen(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_frozen(item) for item in value)
    return value


def thawed(value):
    """The window state of a frame back as a dict, for JSON."""
    if isinstance(value, tuple) and all(isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], str)
                                        for item in value):
        return {key: thawed(item) for key, item in value}
    if isinstance(value, tuple):
        return [thawed(item) for item in value]
    return value


def ease(progress: float) -> float:
    """The product's own curve (brand.ease), which every switch and the card glide on."""
    from codex_auto_resume import brand
    return brand.ease(progress)


# ---------------------------------------------------------------------------------------------------- reading
def _substitute(value, values: dict):
    """`value` with each `${name}` replaced by `values[name]`: a string that is only `${name}` takes the value as it
    is, a list or a point included; inside a longer string it is written as text."""
    if isinstance(value, str):
        whole = re.fullmatch(r"\$\{([a-z_]+)\}", value)
        if whole:
            if whole.group(1) not in values:
                raise PlanError("the plan uses ${%s} and gives no value for it" % whole.group(1))
            return copy.deepcopy(values[whole.group(1)])
        def replace(match):
            name = match.group(1)
            if name not in values:
                raise PlanError("the plan uses ${%s} and gives no value for it" % name)
            return str(values[name])
        return re.sub(r"\$\{([a-z_]+)\}", replace, value)
    if isinstance(value, dict):
        return {_substitute(key, values): _substitute(item, values) for key, item in value.items()}
    if isinstance(value, list):
        return [_substitute(item, values) for item in value]
    return value


def load(path) -> dict:
    """A plan file, its scenes read in (`scenes_from`) and its values put in, checked (`check`)."""
    path = Path(path)
    plan = json.loads(path.read_text(encoding="utf-8"))
    if plan.get("format") != FORMAT:
        raise PlanError("%s is not a %s plan" % (path.name, FORMAT))
    if "scenes_from" in plan:
        shared = path.parent / plan["scenes_from"]
        plan["scenes"] = json.loads(shared.read_text(encoding="utf-8"))
    plan["scenes"] = _substitute(plan.get("scenes") or [], plan.get("values") or {})
    check(plan)
    return plan


def check(plan: dict) -> None:
    """Raises PlanError for a plan that cannot be drawn: an unknown step or state key, a page or name the window does
    not have, a step with no frames or a delay under SHORTEST ms, or a picture outside its `length`."""
    scenes = plan.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise PlanError("a plan has scenes")
    seen = set()
    for scene in scenes:
        name = scene.get("id")
        if not name or name in seen:
            raise PlanError("every scene has an id of its own (%r)" % (name,))
        seen.add(name)
        for step in scene.get("steps") or []:
            actions = [key for key in step if key in STEPS and key != "hold"]
            if len(actions) > 1 or (not actions and "hold" not in step) or (
                    actions and "hold" in step and actions[0] not in HOLDING):
                raise PlanError("%s: a step does one thing: %r" % (name, step))
            unknown = set(step) - set(STEPS) - {"frames", "step", "to"}
            if unknown:
                raise PlanError("%s: a step has keys no step has: %s" % (name, sorted(unknown)))
            if "frames" in step and (not isinstance(step["frames"], int) or step["frames"] < 1):
                raise PlanError("%s: a step draws at least one frame: %r" % (name, step))
            if "step" in step and step["step"] < SHORTEST:
                raise PlanError("%s: %d ms is shorter than a browser shows a frame for" % (name, step["step"]))
            for key in ("move", "hover", "press", "right"):
                if key in step:
                    _check_target(name, step[key])
            if "right" in step and not str(step["right"]).startswith("task."):
                raise PlanError("%s: a right click opens a Pending row's menu, on task.<n>, not %r" % (name, step["right"]))
            if "dismiss" in step and step["dismiss"] != "menu":
                raise PlanError("%s: only the row menu is dismissed, not %r" % (name, step["dismiss"]))
            if "set" in step:
                _check_state(name, step["set"])
    run = _walk(plan)
    frames, end = run.frames, run.t
    lo, hi = plan.get("length") or (0, 10 ** 9)
    if not lo <= end <= hi:
        raise PlanError("the picture is %d ms long; the plan says %d to %d" % (end, lo, hi))
    if any(b.t <= a.t for a, b in zip(frames, frames[1:])):
        raise PlanError("the frames' moments do not rise")


def _check_target(scene: str, target) -> None:
    if isinstance(target, dict):
        point = target.get("at", target.get("by"))
        if set(target) - {"at", "by"} or not (isinstance(point, list) and len(point) == 2):
            raise PlanError("%s: a point is {\"at\": [x, y]} or {\"by\": [dx, dy]}: %r" % (scene, target))
        return
    if not isinstance(target, str) or not NAME.match(target):
        raise PlanError("%s: the window has nothing called %r" % (scene, target))


def _check_state(scene: str, state: dict) -> None:
    unknown = set(state) - set(STATE_KEYS)
    if unknown:
        raise PlanError("%s: the window's render mode has no state %s" % (scene, sorted(unknown)))
    if "page" in state and state["page"] not in PAGES:
        raise PlanError("%s: the window has no page %r" % (scene, state["page"]))
    if "section" in state and state["section"] not in SECTIONS:
        raise PlanError("%s: Settings has no section %r" % (scene, state["section"]))
    for key in ("hover", "pressed"):
        if state.get(key) is not None:
            _check_target(scene, state[key])


# ---------------------------------------------------------------------------------------------------- expanding
class _Run:
    """The state as the steps leave it, and the frames they emit."""

    def __init__(self, plan):
        self.t = 0
        self.window = {"page": "overview", "locale": plan.get("locale", "en")}
        self.card = None
        self.pointer = ("at", {"at": list((plan.get("pointer") or {}).get("rest", [0, 0]))})
        self.ripple = ()
        self.popup = None
        self.frames = []
        self.scene = ""

    def emit(self, at=None):
        at = self.t if at is None else at
        if self.popup:
            # A glide that is over is let go, as the popup lets go of its own (window._glide_amounts).
            from codex_auto_resume import brand
            self.popup["glides"] = {row: glide for row, glide in self.popup["glides"].items()
                                    if at < glide[0] + brand.MOTION["transition_ms"]}
        frame = Frame(int(at), self.scene, _frozen(self.window), _frozen(self.card) if self.card else (),
                      _frozen(self.pointer), self.ripple, _frozen(self.popup) if self.popup else ())
        if self.frames and self.frames[-1].t == frame.t:
            self.frames[-1] = frame              # a later state at the same moment is the one shown
        else:
            self.frames.append(frame)

    def frames_of(self, step, default_frames=1, default_step=40):
        return int(step.get("frames", default_frames)), int(step.get("step", default_step))

    def resting(self):
        """Where the pointer stands once whatever it was doing is done: ("at", target)."""
        return self.pointer if self.pointer[0] == "at" else ("at", self.pointer[2])


def _set_face(run, kind, target):
    """`kind` ("hover" or "pressed") on the window or on the card, whichever `target` names."""
    if isinstance(target, str) and target.startswith("card."):
        if run.card is None:
            raise PlanError("%s: there is no card to %s" % (run.scene, kind))
        run.card[kind] = target[len("card."):]
    else:
        run.window[kind] = target


def _clear_faces(run):
    for kind in ("hover", "pressed"):
        run.window.pop(kind, None)
        if run.card is not None:
            run.card[kind] = None


def _walk(plan: dict) -> _Run:
    run = _Run(plan)
    for scene in plan["scenes"]:
        run.scene = scene["id"]
        for step in scene.get("steps") or []:
            _step(run, step)
    return run


def expand(plan: dict) -> list:
    """Every frame the plan's steps emit, in order: [Frame]."""
    return _walk(plan).frames


def plan_end(plan: dict) -> int:
    """The picture's length in ms: where the last step ends."""
    return _walk(plan).t


def _step(run, step):
    if "set" in step:
        state = copy.deepcopy(step["set"])
        if "page" in state and "section" not in state and state["page"] != run.window.get("page"):
            run.window.pop("section", None)
        # The Pending row a right click chose shows only on Pending: another page leaves it behind, and the window that
        # opens again in another language has chosen nothing.
        if ("page" in state and state["page"] != "pending") or "locale" in state:
            run.window.pop("selected", None)
        if ("page" in state or "section" in state or "locale" in state) and "scroll" not in state:
            run.window.pop("scroll", None)
        for key, value in state.items():
            if value is None:
                run.window.pop(key, None)
            elif key == "scroll":
                run.window["scroll"] = {"notches": int(value)}
            else:
                run.window[key] = value
        _settle_scroll(run)
        run.pointer = run.resting()
        run.emit()
        run.t += int(step.get("hold", 40))
        return
    if "hold" in step and len(step) == 1:
        _settle_scroll(run)
        run.pointer = run.resting()
        run.emit()
        run.t += int(step["hold"])
        return
    if "move" in step:
        count, gap = run.frames_of(step, 10)
        start = run.resting()[1]
        target = step["move"]
        if isinstance(target, dict) and "by" in target:
            target = {"by": list(target["by"]), "from": start}
        for index in range(count):
            fraction = 1.0 if count == 1 else ease(index / float(count - 1))
            run.pointer = ("move", start, target, round(fraction, 6))
            run.emit(run.t + index * gap)
        run.pointer = ("at", target)
        run.t += count * gap
        return
    if "hover" in step or "press" in step:
        kind = "hover" if "hover" in step else "pressed"
        target = step.get("hover", step.get("press"))
        if isinstance(target, str) and target.startswith("menu.") and ("menu" not in run.window or kind != "hover"):
            raise PlanError("%s: %s is an item of the row menu, which is not open (or is pressed)" % (run.scene, target))
        count, gap = run.frames_of(step, 1, 200 if kind == "hover" else 40)
        _set_face(run, "hover", target)
        if kind == "pressed":
            _set_face(run, "pressed", target)
            run.ripple = (_frozen(run.resting()[1]), run.t)
        for index in range(count):
            run.emit(run.t + index * gap)
        run.t += count * gap
        if kind == "pressed":
            _clear_faces(run)
        return
    if "card" in step:
        count, gap = run.frames_of(step, 9)
        if step["card"] == "enter":
            run.card = {"born": run.t, "hover": None, "pressed": None, "leave": None}
        elif step["card"] == "shown":
            # Already there: born one whole entrance ago, so it stands at rest from this moment on.
            from codex_auto_resume import notice_card
            run.card = {"born": run.t - notice_card.ENTRANCE_MS, "hover": None, "pressed": None, "leave": None}
        elif step["card"] == "leave":
            if run.card is None:
                raise PlanError("%s: there is no card to leave" % run.scene)
            run.card["leave"] = run.t
        else:
            raise PlanError("%s: a card enters, is shown or leaves, not %r" % (run.scene, step["card"]))
        for index in range(count):
            run.emit(run.t + index * gap)
        run.t += count * gap
        if step["card"] == "leave":
            run.card = None
        return
    if "wheel" in step:
        count, gap = run.frames_of(step, 4)
        notches = (run.window.get("scroll") or {}).get("notches", 0) + int(step["wheel"])
        for index in range(count):
            run.window["scroll"] = {"notches": notches, "glide_ms": index * gap}
            run.emit(run.t + index * gap)
        run.t += count * gap
        return
    if "open" in step:
        field = step["open"]
        if not field.startswith("setting."):
            raise PlanError("%s: only a setting's drop-down opens a list, not %r" % (run.scene, field))
        _clear_faces(run)
        # It fades in and rises into place as SoftDropList.Show animates it: a frame every `step` ms of that, the
        # list `appear_ms` into it, then at rest.
        count, gap = run.frames_of(step, 0, SHORTEST)
        name = field[len("setting."):]
        for index in range(count):
            run.window["droplist"] = {"field": name, "hover": None, "appear_ms": index * gap}
            run.emit(run.t + index * gap)
        run.t += count * gap
        run.window["droplist"] = {"field": name, "hover": None}
        run.emit()
        run.t += int(step.get("hold", 40))
        return
    if "rows" in step:
        if "droplist" not in run.window:
            raise PlanError("%s: no drop list is open" % run.scene)
        gap = int(step.get("step", 80))
        for value in step["rows"]:
            run.window["droplist"] = dict(run.window["droplist"], hover=value)
            run.pointer = ("at", "row." + value)
            run.emit()
            run.t += gap
        return
    if "choose" in step:
        listed = run.window.pop("droplist", None)
        if listed is None:
            raise PlanError("%s: no drop list is open to choose from" % run.scene)
        combo = dict(run.window.get("combo") or {})
        combo[listed["field"]] = step["choose"]
        run.window["combo"] = combo
        run.pointer = ("at", "setting." + listed["field"])
        run.emit()
        run.t += int(step.get("hold", 40))
        return
    if "right" in step:
        # A right press on a Pending row, as the list takes it (DashboardPages: MouseDown chooses the row under the
        # pointer), a ripple where the pointer is; on letting go the row's own menu opens with its card's corner there.
        target = step["right"]
        count, gap = run.frames_of(step, 1, 40)
        _clear_faces(run)
        run.window["selected"] = {"pending": int(target[len("task."):])}
        run.pointer = run.resting()
        run.ripple = (_frozen(run.resting()[1]), run.t)
        for index in range(count):
            run.emit(run.t + index * gap)
        run.t += count * gap
        run.window["menu"] = {"at": target}
        run.emit()
        run.t += int(step.get("hold", 40))
        return
    if "dismiss" in step:
        if "menu" not in run.window:
            raise PlanError("%s: no menu is open to dismiss" % run.scene)
        run.window.pop("menu")
        if str(run.window.get("hover", "")).startswith("menu."):
            run.window.pop("hover")
        run.pointer = run.resting()
        run.emit()
        run.t += int(step.get("hold", 40))
        return
    if "popup" in step:
        if step["popup"] == "open":
            if run.popup is not None:
                raise PlanError("%s: the popup is open already" % run.scene)
            run.popup = {"opened": run.t, "off": [], "busy": [], "glides": {}}
        elif step["popup"] == "close":
            if run.popup is None:
                raise PlanError("%s: there is no popup to close" % run.scene)
            run.popup = None
        else:
            raise PlanError("%s: the popup opens or closes, not %r" % (run.scene, step["popup"]))
        run.emit()
        run.t += int(step.get("hold", 40))
        return
    if "ask" in step or "switch" in step:
        kind = "ask" if "ask" in step else "switch"
        row = step[kind]
        if run.popup is None:
            raise PlanError("%s: the popup is not open" % run.scene)
        if not isinstance(row, int) or isinstance(row, bool) or row < 1:
            raise PlanError("%s: a popup row is counted from 1, not %r" % (run.scene, row))
        count, gap = run.frames_of(step, 3 if kind == "ask" else 5, 33)
        if kind == "ask":
            run.popup["busy"] = sorted(set(run.popup["busy"]) | {row})
        else:
            if step.get("to") not in ("off", "on"):
                raise PlanError("%s: a switch goes to off or on, not %r" % (run.scene, step.get("to")))
            end = 1.0 if step["to"] == "on" else 0.0
            if (row in run.popup["off"]) == (end == 0.0):
                raise PlanError("%s: row %d is %s already" % (run.scene, row, step["to"]))
            run.popup["off"] = sorted(set(run.popup["off"]) ^ {row})
            run.popup["busy"] = sorted(set(run.popup["busy"]) - {row})
            run.popup["glides"][row] = [run.t, 1.0 - end, end]
        for index in range(count):
            run.emit(run.t + index * gap)
        run.t += count * gap
        return
    raise PlanError("%s: no step does %r" % (run.scene, step))


def _settle_scroll(run):
    """A wheel's glide is over once anything else happens."""
    scroll = run.window.get("scroll")
    if scroll and "glide_ms" in scroll:
        run.window["scroll"] = {"notches": scroll["notches"]}


# ---------------------------------------------------------------------------------------------------- the clock
def fill(frames: list, end: int, light_step: int, also=(), first_hold: int = 0, ripple_step: int = 0) -> list:
    """`frames` with a frame added wherever something moves by itself between two of them: every `light_step` ms of
    the picture's clock (the lights, at their own timer's step), at each moment in `also` (the tray icon's own frame
    times), and every
    `ripple_step` ms while a click's ripple fades - each the state of the frame before it at its own moment. Nothing
    is added before `first_hold` (frame 1 is the still, held), at or past `end`, or where a frame already is."""
    if not frames:
        return []
    step = float(light_step) if light_step else None
    moments = set()
    if step:
        moments.update(int(round(index * step)) for index in range(int(math.ceil(end / step))))
    moments.update(int(round(at)) for at in also)
    ripples = set()
    if ripple_step:
        for start in sorted({frame.ripple[1] for frame in frames if frame.ripple}):
            ripples.update(range(start, start + RIPPLE_MS, ripple_step))
    have = sorted({frame.t for frame in frames} | {end})
    # A ripple's frames are steps of their own, kept wherever a browser can show them apart from the steps' frames.
    ripples = _apart(sorted(at for at in ripples if frames[0].t <= at < end), have, SHORTEST)
    have = sorted(set(have) | set(ripples))
    # The lights' and the icon's are kept CLOSEST from every other: of two of them, the earlier.
    added = _apart(sorted(at for at in moments if first_hold <= at < end and at >= frames[0].t), have, CLOSEST)
    added = sorted(set(added) | set(ripples))
    out, index = [], 0
    for frame in frames:
        while index < len(added) and added[index] < frame.t:
            out.append(out[-1]._replace(t=added[index]))
            index += 1
        out.append(frame)
    while index < len(added):
        out.append(out[-1]._replace(t=added[index]))
        index += 1
    return out


def _apart(candidates: list, fixed: list, gap: int) -> list:
    """The candidates at least `gap` ms from every fixed moment and from the candidate kept before them."""
    kept, last = [], None
    for at in candidates:
        place = bisect.bisect_left(fixed, at)
        if any(abs(at - fixed[i]) < gap for i in (place - 1, place) if 0 <= i < len(fixed)):
            continue
        if last is not None and at - last < gap:
            continue
        kept.append(at)
        last = at
    return kept


def delays(moments: list, end: int) -> list:
    """Each frame's delay in ms, from the moments (ms) the frames start at and the picture's end: they sum to the end
    exactly. A moment under SHORTEST ms after the one before raises: the plan asked for a frame no browser shows."""
    starts = [int(round(at)) for at in moments] + [int(round(end))]
    out = []
    for index in range(len(moments)):
        delay = starts[index + 1] - starts[index]
        if delay < SHORTEST:
            raise PlanError("a frame at %d ms is held %d ms; this picture shows a frame at least %d"
                            % (moments[index], delay, SHORTEST))
        out.append(delay)
    return out


def window_states(frames: list) -> list:
    """Each different (window state, moment of its lights) the frames need drawn, in the order they first appear."""
    seen, out = set(), []
    for frame in frames:
        key = (frame.window, frame.t)
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def pointer_targets(frames: list) -> set:
    """Every named target a frame's pointer or ripple stands at or travels between."""
    names = set()

    def named(ref):
        if isinstance(ref, str):
            names.add(ref)
        elif isinstance(ref, tuple):
            for key, value in ref:
                if key == "from":
                    named(value)
    for frame in frames:
        for ref in frame.pointer[1:3] + (frame.ripple[:1] if frame.ripple else ()):
            named(ref)
    return names


def ripple_at(frame: Frame) -> tuple:
    """(radius fraction, opacity fraction) of the frame's ripple at its moment, or None once it has faded."""
    if not frame.ripple:
        return None
    age = frame.t - frame.ripple[1]
    if age < 0 or age >= RIPPLE_MS:
        return None
    eased = ease(age / float(RIPPLE_MS))
    return eased, 1.0 - eased
