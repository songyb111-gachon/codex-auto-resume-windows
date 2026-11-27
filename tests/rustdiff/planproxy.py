"""CODEX_AR_CORE=rust: the drawing half's plans and motion, as the C# host's (S6.4f, P6-DESIGN 3.4 "drawn").

`shim.install()` calls `install(module)` as the modules of MODULES load, and each named function there is replaced by one
that asks the host's own C# (gui/host.sources' [surface] files, compiled with PlanProbe.cs beside this file into one
process the run shares): the icon's frames and colours (TrayMotion), the popup's light and glides (PopupMotion), where the
popup goes, what a point hits and where focus goes (PopupPlace), the lifts and wells (SurfaceElevation), and the popup's
layout, which goes through the render mode itself (SurfaceRender.RunJob, the same job tests/test_surface_parity.py builds).

How a layout is asked (the plan proxy of S6.4's notes): the test's call is made once on the reference with its `measure`
wrapped, so every measure question the layout asks and the test's answer are recorded as the job's table, keyed as the C#
asks it (SurfaceText.Measure: the role, the text or " ", the width at least 1, DrawTextW's flags); the render mode lays the
case out from that table and nothing else; the C# plan's dump is rebuilt as the reference's plan object (tuples where the
reference has tuples, a float where it has a float) and handed to the test, so the test's own assertions run on the C#.
Only the containers' kinds come from the reference's plan; every value, every item and their order are the C#'s.

Only a test's own call is routed (the caller's module is a `test_*` one): the Python product's own callers (its window,
its renderer) keep Python's, since the window is what the host replaces and is held by the window rows. A routed call is
counted per test (CAR_PLAN_PROXY_REPORT=<file> appends the counts at exit), so a test is "on the host" only when its count
is not zero. Nothing falls back to Python: a question the C# refuses raises.

Self-contained: stdlib only at import (it loads by path before anything is on sys.path).
"""
from __future__ import annotations

import atexit
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
ROOT = Path(__file__).resolve().parents[2]
DRIVER = Path(__file__).resolve().with_name("PlanProbe.cs")
CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
GROUPS = ("contract", "surface", "generated")
DT_CALCRECT, DT_NOPREFIX, DT_WORDBREAK, DT_EDITCONTROL, DT_SINGLELINE = 0x400, 0x800, 0x10, 0x2000, 0x20
CALLS: dict = {}
BY_TEST: dict = {}


# ------------------------------------------------------------------------------------------- the probe process
def sources() -> list:
    """gui/host.sources' [contract], [surface] and [generated] files in order (each once), then PlanProbe.cs."""
    groups, group = {}, None
    for line in (ROOT / "gui" / "host.sources").read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            group = line[1:-1]
        else:
            groups.setdefault(group, []).append(ROOT / line)
    found = []
    for name in GROUPS:
        for path in groups.get(name, []):
            if path not in found:
                found.append(path)
    return found + [DRIVER]


def executable() -> Path:
    files = sources()
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.name.encode("utf-8") + b"\0" + path.read_bytes())
    folder = Path(tempfile.gettempdir()) / "car-plan-host" / digest.hexdigest()[:16]
    exe = folder / "plan-probe.exe"
    if not exe.is_file():
        folder.mkdir(parents=True, exist_ok=True)
        building = folder / ("building-%d.exe" % os.getpid())
        done = subprocess.run([str(CSC), "-nologo", "-target:exe", "-platform:x64", "-warnaserror", "-optimize+",
                               "-out:%s" % building, "-r:System.dll", "-r:System.Drawing.dll"] + [str(p) for p in files],
                              capture_output=True, timeout=600, creationflags=NO_WINDOW)
        if done.returncode != 0:
            raise RuntimeError("the surfaces do not compile with PlanProbe.cs:\n%s" % done.stdout.decode("utf-8", "replace"))
        os.replace(building, exe)
    return exe


class Probe:
    """PlanProbe.exe as one process the run shares, with every home pointed into a folder of its own and no Codex."""

    def __init__(self):
        self.lock, self.process = threading.Lock(), None

    def ask(self, op: str, **fields):
        with self.lock:
            if self.process is None:
                home = tempfile.mkdtemp(prefix="car-plan-proxy-")
                environment = {name: value for name, value in os.environ.items() if name != "CODEX_AR_CORE"}
                environment.update({name: home for name in ("USERPROFILE", "HOME", "APPDATA", "LOCALAPPDATA", "CODEX_HOME")})
                environment["CODEX_AUTO_RESUME_CODEX_EXE"] = str(Path(home) / "no-codex" / "codex.exe")
                self.process = subprocess.Popen([str(executable())], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                                stderr=subprocess.DEVNULL, env=environment, creationflags=NO_WINDOW)
                atexit.register(self.stop)
            self.process.stdin.write((json.dumps(dict(fields, op=op), ensure_ascii=True) + "\n").encode("utf-8"))
            self.process.stdin.flush()
            line = self.process.stdout.readline()
        if not line:
            raise RuntimeError("the plan probe ended")
        found = json.loads(line.decode("utf-8"))
        if "error" in found:
            raise RuntimeError("the host refused %s: %s" % (op, found["error"]))
        return found["ok"]

    def stop(self):
        process, self.process = self.process, None
        if process is not None:
            try:
                process.stdin.close()
                process.wait(timeout=20)
            except Exception:
                process.kill()
        if os.environ.get("CAR_PLAN_PROXY_REPORT") and (CALLS or BY_TEST):
            with open(os.environ["CAR_PLAN_PROXY_REPORT"], "a", encoding="utf-8") as out:
                out.write(json.dumps({"pid": os.getpid(), "calls": CALLS, "tests": BY_TEST}, sort_keys=True) + "\n")


PROBE = Probe()


def _test_frame(depth: int):
    """The frame that called the proxy, when it is a test module's; else None (the product's own callers keep Python's)."""
    frame = sys._getframe(depth)
    return frame if frame.f_globals.get("__name__", "").startswith("test_") else None


def _count(op: str, frame) -> None:
    CALLS[op] = CALLS.get(op, 0) + 1
    while frame is not None:
        owner = frame.f_locals.get("self")
        if isinstance(owner, unittest.TestCase):
            ident = owner.id()
            BY_TEST.setdefault(ident, {})
            BY_TEST[ident][op] = BY_TEST[ident].get(op, 0) + 1
            return
        frame = frame.f_back


def ask(op: str, **fields):
    _count(op, sys._getframe(2))
    return PROBE.ask(op, **fields)


# ------------------------------------------------------------------------------------------- JSON in, objects out
def wire(value):
    """A Python value as the probe reads it: tuples as lists, everything else as it is."""
    if isinstance(value, (list, tuple)):
        return [wire(each) for each in value]
    if isinstance(value, dict):
        return {key: wire(each) for key, each in value.items()}
    if isinstance(value, (bytes, bytearray)):
        return list(value)
    return value


def shaped(found, like):
    """The C#'s value with the reference's container kinds: a list where the reference has a tuple becomes a tuple, an
    integral number where it has a float becomes a float. Every value, length and key is the C#'s own."""
    if isinstance(found, list):
        kind = tuple if isinstance(like, tuple) else list
        likes = list(like) if isinstance(like, (list, tuple)) else []
        return kind(shaped(each, likes[index] if index < len(likes) else _sibling(likes, each))
                    for index, each in enumerate(found))
    if isinstance(found, dict):
        likes = like if isinstance(like, dict) else {}
        return {key: shaped(each, likes.get(key)) for key, each in found.items()}
    if isinstance(found, int) and not isinstance(found, bool) and isinstance(like, float):
        return float(found)
    return found


def _sibling(likes, each):
    """A template for an item past the reference's end: the reference's last item of the same kind, if any."""
    for like in reversed(likes):
        if isinstance(like, dict) and isinstance(each, dict) and like.get("kind") == each.get("kind"):
            return like
    return likes[-1] if likes else None


def target_of(found, candidates=()):
    """A target the C# answered as JSON, as the Python object it stands for: the first candidate the test handed in that
    is the same value, else the reference's tuple."""
    for candidate in candidates:
        if wire(candidate) == found:
            return candidate
    return tuple(found) if isinstance(found, list) else found


def _number(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else value


# ------------------------------------------------------------------------------------------- the proxies
def _replace(module, name, make):
    original = getattr(module, name)
    proxy = make(original)

    def routed(*args, **kwargs):
        if _test_frame(2) is None:
            return original(*args, **kwargs)
        return proxy(*args, **kwargs)

    routed.rust_core = "host"
    routed.__wrapped__ = original
    routed.__doc__ = original.__doc__
    routed.__name__ = name
    setattr(module, name, routed)


def _tray_motion(module):
    """The icon's frames, its clock and its colours (gui/TrayMotion.cs)."""
    def frame(original):
        def icon_frame(state, elapsed_ms, since_entered_ms=None, *, reduced=False, fine=1):
            return tuple(ask("icon_frame", state=state, elapsed=float(elapsed_ms), reduced=bool(reduced), fine=int(fine)))
        return icon_frame

    def frame_ms(original):
        def icon_frame_ms(state, elapsed_ms, since_entered_ms=None, *, reduced=False, fine=1):
            found = ask("icon_frame_ms", state=state, elapsed=float(elapsed_ms), reduced=bool(reduced), fine=int(fine))
            return found
        return icon_frame_ms

    def turn(original):
        def icon_turn(state, elapsed_ms):
            found = ask("icon_turn", state=state, elapsed=float(elapsed_ms))
            return None if found is None else float(found)
        return icon_turn

    def brand_state(original):
        def icon_brand_state(state):
            return ask("icon_brand_state", state=state)
        return icon_brand_state

    def head(original):
        def icon_head_colour(state):
            return tuple(ask("icon_head_colour", state=state))
        return icon_head_colour

    def level(original):
        def icon_level_colour(colour, level):
            return tuple(ask("icon_level_colour", colour=wire(colour), level=float(int(level))))
        return icon_level_colour

    def allowed(original):
        def icon_motion_allowed(*, reduced=False, contrast=False, battery_saver=False, locked=False, hidden=False,
                                frames=True):
            return ask("icon_motion_allowed", reduced=bool(reduced), contrast=bool(contrast),
                       battery_saver=bool(battery_saver), locked=bool(locked), hidden=bool(hidden), frames=bool(frames))
        return icon_motion_allowed

    for name, make in (("icon_frame", frame), ("icon_frame_ms", frame_ms), ("icon_turn", turn),
                       ("icon_brand_state", brand_state), ("icon_head_colour", head), ("icon_level_colour", level),
                       ("icon_motion_allowed", allowed)):
        _replace(module, name, make)


def _popup_motion(module):
    """The status light and the glides (gui/PopupMotion.cs)."""
    def halo(original):
        def halo(state, elapsed_ms, since_entered_ms=None, *, reduced=False, design="soft"):
            found = ask("halo", state=state, elapsed=float(elapsed_ms), reduced=bool(reduced), design=design)
            if found is None:
                return None
            return {key: (None if value is None else float(value)) for key, value in found.items()}
        return halo

    def animates(original):
        def animates(state, since_entered_ms=0, *, reduced=False):
            return ask("animates", state=state, reduced=bool(reduced))
        return animates

    def opening(original):
        def opening(elapsed_ms, rise):
            alpha, below, arrived = ask("opening", elapsed=float(elapsed_ms), rise=int(rise))
            return alpha, below, bool(arrived)
        return opening

    def closing(original):
        def closing(elapsed_ms, alpha):
            found, gone = ask("closing", elapsed=float(elapsed_ms), alpha=int(alpha))
            return found, bool(gone)
        return closing

    def face_amount(original):
        def face_amount(face, now_ms):
            started, _, length = face
            amount, over = ask("face_amount", started=float(started), length=float(length), now=float(now_ms))
            return float(amount), bool(over)
        return face_amount

    def face_length(original):
        def face_length(before, after):
            return ask("face_length", before=before, after=after)
        return face_length

    def mixed(original):
        def mixed(one, other, amount):
            return tuple(ask("mixed", one=wire(one), other=wire(other), amount=float(amount)))
        return mixed

    def glide_amount(original):
        def glide_amount(glide, now_ms):
            amount, over = ask("glide_amount", glide=[float(part) for part in glide], now=float(now_ms))
            return _number(amount), bool(over)
        return glide_amount

    def next_glides(original):
        def next_glides(seen, previous, glides, now_ms, *, animate=True):
            keys = list(seen) + list(previous or ()) + list(glides)
            found = ask("next_glides", seen=[[wire(key), bool(value)] for key, value in seen.items()],
                        previous=None if previous is None else [[wire(key), bool(value)] for key, value in previous.items()],
                        glides=[[wire(key), [float(part) for part in glide]] for key, glide in glides.items()],
                        now=float(now_ms), animate=bool(animate))
            return {target_of(key, keys): tuple(float(part) for part in glide) for key, glide in found}
        return next_glides

    for name, make in (("halo", halo), ("animates", animates), ("opening", opening), ("closing", closing),
                       ("face_amount", face_amount), ("face_length", face_length), ("mixed", mixed),
                       ("glide_amount", glide_amount), ("next_glides", next_glides)):
        _replace(module, name, make)


def _placement(module):
    """Where the popup goes, what a point hits, where focus goes (gui/PopupPlace.cs)."""
    def rect(value):
        return None if value is None else [int(part) for part in value]

    def taskbar_edge(original):
        def taskbar_edge(work, monitor, anchor=None):
            return ask("taskbar_edge", work=rect(work), monitor=rect(monitor), anchor=rect(anchor))
        return taskbar_edge

    def place(original):
        def place(size, work, monitor, icon=None, cursor=None, gap=12):
            x, y, edge = ask("place", size=rect(size), work=rect(work), monitor=rect(monitor), icon=rect(icon),
                             cursor=rect(cursor), gap=int(gap))
            return x, y, edge
        return place

    def hit_test(original):
        def hit_test(targets, x, y):
            targets = list(targets)
            found = ask("hit_test", targets=[[wire(target), rect(box)] for target, box in targets], x=int(x), y=int(y))
            return None if found is None else target_of(found, [target for target, _ in targets])
        return hit_test

    def focus_order(original):
        def focus_order(targets):
            targets = list(targets)
            found = ask("focus_order", targets=[[wire(target), rect(box)] for target, box in targets])
            return [target_of(each, [target for target, _ in targets]) for each in found]
        return focus_order

    def next_focus(original):
        def next_focus(order, current, backwards=False):
            order = list(order)
            found = ask("next_focus", order=[wire(each) for each in order], current=wire(current), backwards=bool(backwards))
            return None if found is None else target_of(found, order)
        return next_focus

    for name, make in (("taskbar_edge", taskbar_edge), ("place", place), ("hit_test", hit_test),
                       ("focus_order", focus_order), ("next_focus", next_focus)):
        _replace(module, name, make)


def _elevation(module):
    """The lifts and the wells (gui/SurfaceElevation.cs). The C# keeps a mask by the box it is made from (its `Key`); here
    each key's mask is one Python object kept in the module's own `_MASKS` under ("host", key), so a test that clears
    `_MASKS` starts both afresh and `is` holds exactly where the C# made one mask of two bodies."""
    def mask(found):
        key = ("host", found["key"])
        kept = module._MASKS.get(key)
        if kept is not None:
            return kept
        made = {"key": found["key"], "width": found["width"], "height": found["height"],
                "centre": tuple(found["centre"]), "extent": found["extent"], "coverage": bytes(found["coverage"])}
        module._MASKS[key] = made
        return made

    def smoothing_of(value):
        return None if value is None else float(value)

    def lift(original):
        def lift_coverage(width, height, radius, blur, smoothing=None):
            return mask(ask("lift_coverage", width=int(width), height=int(height), radius=float(radius), blur=float(blur),
                            smoothing=smoothing_of(smoothing)))
        return lift_coverage

    def well(original):
        def well_coverage(width, height, radius, blur, dx, dy, smoothing=None):
            return mask(ask("well_coverage", width=int(width), height=int(height), radius=float(radius), blur=float(blur),
                            dx=float(dx), dy=float(dy), smoothing=smoothing_of(smoothing)))
        return well_coverage

    def step(original):
        def shadow_step(value):
            return ask("shadow_step", value=float(value))
        return shadow_step

    def recipe(original):
        def recipe_shadows(recipe, theme="light", design="soft"):
            return tuple(module.brand.Shadow(*each) for each in ask("recipe_shadows", recipe=recipe, theme=theme, design=design))
        return recipe_shadows

    def ground(original):
        def tile_ground(theme="light", design="soft"):
            return ask("tile_ground", theme=theme, design=design)
        return tile_ground

    for name, make in (("lift_coverage", lift), ("well_coverage", well), ("shadow_step", step), ("recipe_shadows", recipe),
                       ("tile_ground", ground)):
        _replace(module, name, make)


def _flags(wrap) -> int:
    return DT_CALCRECT | DT_NOPREFIX | ((DT_WORDBREAK | DT_EDITCONTROL) if wrap else DT_SINGLELINE)


def _recorded(original, case_of, pick=None):
    """A layout(vm, scale, measure, ...) asked of the render mode: the reference's call made once with `measure` wrapped,
    every question and the test's answer recorded as the job's table (keyed as SurfaceText.Measure asks it), the case
    `case_of(vm, scale)` laid out from that table alone, and the C#'s plan (`pick` of the case's answer) handed back in
    the reference's container kinds."""
    def layout(vm, scale, measure, *rest):
        table = {}

        def recorded(role, text, at, wrap):
            found = measure(role, text, at, wrap)
            table[(role, text if text else " ", max(1, int(at)), _flags(wrap))] = (int(found[0]), int(found[1]))
            return found
        reference = original(vm, scale, recorded, *rest)
        rows = [[role, text, at, flags, w, h] for (role, text, at, flags), (w, h) in table.items()]
        found = ask("render", tables={"t": {"measure": rows, "metrics": {}, "ink": []}}, case=case_of(vm, scale))
        return shaped(found if pick is None else found[pick], reference)
    return layout


def _layout(module):
    """The popup's layout (gui/PopupLayout.cs), through the render mode's `popup` case in a language written left to
    right with no breaking of its own (so the case is layout.layout's, not Renderer.layout's mirror), and share_columns."""
    def layout(original):
        inner = _recorded(original, lambda vm, scale: {"surface": "popup", "vm": wire(vm), "scale": float(scale),
                                                        "locale": "en", "table": "t"})

        def layout(vm, scale, measure, width=module.WIDTH):
            if width != module.WIDTH:
                raise TypeError("the render mode lays the popup out at its own width only (layout.WIDTH)")
            return inner(vm, scale, measure)
        return layout

    def share(original):
        def share_columns(available, needs):
            return ask("share_columns", available=int(available), needs=[int(need) for need in needs])
        return share_columns

    _replace(module, "layout", layout)
    _replace(module, "share_columns", share)


class _HostCardMotion:
    """notice_card.CardMotion as the C#'s CardMotion (gui/CardPlan.cs), by replay: every step the test took is sent again
    as the render mode's `card_life` case, and what a step returns and the state read after it (phase, since, hold_left,
    from_alpha, exit_ms, paused, final, gone) are the last step's. The constructor's own inputs (reduced, hold_ms) read
    back as given; anything else read or assigned is refused, never answered by Python."""

    STATE = ("phase", "since", "hold_left", "from_alpha", "exit_ms", "paused", "final")
    module = None

    def __init__(self, now_ms, *, hold_ms=None, reduced=False, position=None):
        hold = float(self.module.HOLD_MS if hold_ms is None else hold_ms)
        object.__setattr__(self, "_steps", [["new", float(now_ms), "inf" if hold == float("inf") else hold, bool(reduced),
                                             wire(position)]])
        object.__setattr__(self, "_inputs", {"reduced": bool(reduced), "hold_ms": max(0.0, hold)})
        object.__setattr__(self, "_last", self._run())

    def _run(self):
        return ask("render", case={"surface": "card_life", "steps": self._steps})[-1]

    def _step(self, *step):
        self._steps.append(list(step))
        object.__setattr__(self, "_last", self._run())
        return self._last[0]

    def __getattr__(self, name):
        if name in self.STATE:
            return self._last[1 + self.STATE.index(name)]
        if name in ("reduced", "hold_ms"):
            return self._inputs[name]
        raise TypeError("the host's CardMotion is asked by replay: %s is not read back" % name)

    def __setattr__(self, name, value):
        raise TypeError("the host's CardMotion is asked by replay: %s cannot be set" % name)

    @property
    def gone(self):
        return self._last[1] == "gone"

    def frame(self, now_ms):
        return _frame(self.module, self._step("frame", float(now_ms)))

    def restart(self, now_ms):
        self._step("restart", float(now_ms))

    def delay(self, ms):
        self._step("delay", float(ms))

    def pause(self, now_ms, paused):
        self._step("pause", float(now_ms), bool(paused))

    def retire(self, now_ms, *, quick=False):
        self._step("retire", float(now_ms), bool(quick))

    def move_to(self, now_ms, target, delay=0):
        self._step("move", float(now_ms), wire(target), float(delay))

    def place(self, now_ms):
        found = self._step("place", float(now_ms))
        return None if found is None else tuple(found)

    def moving(self, now_ms):
        return self._step("moving", float(now_ms))

    def wait_ms(self, now_ms):
        found = self._step("wait", float(now_ms))
        return None if found is None else float(found)


def _frame(module, found):
    return module.Frame(**{key: float(found[key]) for key in ("alpha", "offset", "scale", "depth")})


def _scalar(value):
    """A value the C# can be handed as it is (a number, a bool, None, text); anything else as None, which neither side
    takes for a duration."""
    return value if value is None or isinstance(value, (bool, int, float, str)) else None


def _notice_card(module):
    """The notification card's plan, motion, stack and floating shadow (gui/CardPlan.cs)."""
    def floats(found):
        return tuple(module.FloatShadow(*each) for each in found)

    def entrance(original):
        def entrance(elapsed_ms, *, reduced=False):
            return _frame(module, ask("entrance", elapsed=float(elapsed_ms), reduced=bool(reduced)))
        return entrance

    def leaving(original):
        def leaving(elapsed_ms, start_alpha=1.0, *, reduced=False, duration=module.EXIT_MS):
            return float(ask("leaving", elapsed=float(elapsed_ms), start_alpha=float(start_alpha), reduced=bool(reduced),
                             duration=float(duration)))
        return leaving

    def rise(original):
        def rise_vector(edge):
            return tuple(ask("rise_vector", edge=edge if isinstance(edge, str) else None))
        return rise_vector

    def hold(original):
        def hold_ms(message_duration_ms=None):
            value = _scalar(message_duration_ms)
            return float(ask("hold_ms", duration=float(value) if isinstance(value, int) and not isinstance(value, bool)
                             else value))
        return hold_ms

    def direction(original):
        def stack_direction(edge, y, height, work):
            return ask("stack_direction", edge=edge, y=int(y), height=int(height), work=[int(part) for part in work])
        return stack_direction

    def positions(original):
        def stack_positions(sizes, work, monitor, anchor=None, *, gap, spacing):
            found, edge = ask("stack_positions", sizes=wire(sizes), work=wire(work), monitor=wire(monitor), anchor=wire(anchor),
                              gap=int(gap), spacing=int(spacing))
            return [tuple(each) for each in found], edge
        return stack_positions

    def float_shadows(original):
        def float_shadows(theme, design="soft"):
            return floats(ask("float_shadows", theme=theme, design=design))
        return float_shadows

    def shadow_at(original):
        def shadow_at(shadows, depth):
            return floats(ask("shadow_at", shadows=wire(shadows), depth=float(depth)))
        return shadow_at

    def depth_level(original):
        def depth_level(depth):
            return ask("depth_level", depth=float(depth))
        return depth_level

    def shadow_margin(original):
        def shadow_margin(shadows, scale):
            return ask("shadow_margin", shadows=wire(shadows), scale=float(scale))
        return shadow_margin

    def layout(original):
        return _recorded(original, lambda vm, scale: {"surface": "card", "vm": wire(vm), "scale": float(scale), "locale": "en",
                                                      "table": "t"}, "plan")

    for name, make in (("entrance", entrance), ("leaving", leaving), ("rise_vector", rise), ("hold_ms", hold),
                       ("stack_direction", direction), ("stack_positions", positions), ("float_shadows", float_shadows),
                       ("shadow_at", shadow_at), ("depth_level", depth_level), ("shadow_margin", shadow_margin),
                       ("layout", layout)):
        _replace(module, name, make)

    original = module.CardMotion
    host = type("CardMotion", (_HostCardMotion,), {"module": module, "__doc__": original.__doc__})

    class CardMotion:
        """A test's CardMotion is the host's (by replay); the product's own callers keep Python's."""

        def __new__(cls, *args, **kwargs):
            if _test_frame(2) is None:
                return original(*args, **kwargs)
            return host(*args, **kwargs)

    CardMotion.__wrapped__, CardMotion.rust_core = original, "host"
    module.CardMotion = CardMotion


MODULES = {"codex_auto_resume.ui.tray.motion": _tray_motion, "codex_auto_resume.ui.popup.motion": _popup_motion,
           "codex_auto_resume.ui.popup.placement": _placement, "codex_auto_resume.ui.popup.elevation": _elevation,
           "codex_auto_resume.ui.popup.layout": _layout, "codex_auto_resume.notice_card": _notice_card}


def install(module) -> None:
    """Replace the module's plan and motion functions as it loads; once."""
    if getattr(module, "_rust_plan", False) or module.__name__ not in MODULES:
        return
    MODULES[module.__name__](module)
    module._rust_plan = True
