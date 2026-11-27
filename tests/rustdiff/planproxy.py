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
        if owner is not None and hasattr(owner, "id") and hasattr(owner, "_testMethodName"):
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

    for name, make in (("lift_coverage", lift), ("well_coverage", well), ("shadow_step", step)):
        _replace(module, name, make)


def _flags(wrap) -> int:
    return DT_CALCRECT | DT_NOPREFIX | ((DT_WORDBREAK | DT_EDITCONTROL) if wrap else DT_SINGLELINE)


def _layout(module):
    """The popup's layout (gui/PopupLayout.cs), through the render mode's `popup` case: the reference's measure questions
    recorded from the test's own `measure`, the case laid out from that table, the dump rebuilt as the reference's plan."""
    def layout(original):
        def layout(vm, scale, measure, width=module.WIDTH):
            if width != module.WIDTH:
                raise TypeError("the render mode lays the popup out at its own width only (layout.WIDTH)")
            table = {}

            def recorded(role, text, at, wrap):
                found = measure(role, text, at, wrap)
                table[(role, text if text else " ", max(1, int(at)), _flags(wrap))] = (int(found[0]), int(found[1]))
                return found
            reference = original(vm, scale, recorded, width)
            rows = [[role, text, at, flags, w, h] for (role, text, at, flags), (w, h) in table.items()]
            found = ask("render", tables={"t": {"measure": rows, "metrics": {}, "ink": []}},
                        case={"surface": "popup", "vm": wire(vm), "scale": float(scale), "locale": "en", "table": "t"})
            return shaped(found, reference)
        return layout

    _replace(module, "layout", layout)


MODULES = {"codex_auto_resume.ui.tray.motion": _tray_motion, "codex_auto_resume.ui.popup.motion": _popup_motion,
           "codex_auto_resume.ui.popup.placement": _placement, "codex_auto_resume.ui.popup.elevation": _elevation,
           "codex_auto_resume.ui.popup.layout": _layout}


def install(module) -> None:
    """Replace the module's plan and motion functions as it loads; once."""
    if getattr(module, "_rust_plan", False) or module.__name__ not in MODULES:
        return
    MODULES[module.__name__](module)
    module._rust_plan = True
