"""Make the install motion pictures: the setup program's window installing the product, every frame drawn by the
window's own code, offscreen.

    python -X utf8 build/make_install_motion.py                  # docs/images/install-motion.png and -ko.png
    python -X utf8 build/make_install_motion.py install-ko       # one of them (a plan's name under build/motion/)
    python -X utf8 build/make_install_motion.py --dry-run        # only the frames each plan asks for, scene by scene
    python -X utf8 build/make_install_motion.py --fidelity       # only the window held to the captured stills
    python -X utf8 build/make_install_motion.py --still          # first draw the Welcome still(s) offscreen, then on
    python -X utf8 build/make_install_motion.py --out DIR        # the pictures into DIR; nothing else is written
    python -X utf8 build/make_install_motion.py --out DIR --client-only   # a proof with no still: the client area

A plan (build/motion/install-en.json, install-ko.json, their scenes and the installer's lines in
install-scenes.json) says, on one clock, what a person does and what the installer prints: the Welcome page of a
first installation, Next, the Options page, Install, the run - each step's line as build/install/install.ps1 prints
it, the bar and the step's name moving on as the window reads them - and the Finish page, its light lit.

Each frame is drawn by the setup program's own window. build/motion/InstallerRender.cs is compiled TOGETHER with
the sources build/make_setup.py compiles the setup program from - nothing added to them, nothing taken away - into a
scratch program that makes the window as the setup program makes it and drives it through its own doors: its primary
button clicked, its own run started, told the plan's lines one at a time, ended with the code a run that succeeded
ends with. Nothing is installed, unpacked or started. Round each frame's client area go the caption, frame and corners
of one captured still of the real setup window (`window.still`), and over it a pointer and a click's ring of our own
(build/motion_compose.py). The frames are written as a lossless APNG within the plan's byte budget
(build/motion_apng.py), and recorded with what they were made from in assets/install-motion.json.

Before any picture the window is held to the stills (FIDELITY: the Welcome page of a first installation): the client
area drawn offscreen must be the still's (build/motion_fidelity.compare). A still that fails stops the run; with no
still at all there is no frame to put the window in, and only `--client-only` draws (a proof, never the documentation's
picture). Since v0.6.20 the still is drawn too, offscreen (`--still`): the Welcome page at the pinned scale, framed with
the setup window's title bar kept from a capture at that scale (build/window_frame.py) and its corners cut as
build/capture_window.ps1 cuts them - the captured still, byte for byte, with no Setup exe built or shown. A still
captured from a Setup exe (the main session, build/capture_window.ps1) is held the same way.

It captures nothing and moves no pointer: nothing is shown on the screen. It needs Windows (GDI and GDI+) and the
in-box C# compiler; the window is drawn at the pinned scale (make_screenshots.PINNED_SCALE, 150 %) whatever the
display is. Run it from the main session, detached, under plans/proof/gui_lock.sh like every picture.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "src"), str(ROOT / "build")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import motion_plan  # noqa: E402

PLAN_NAMES = ("install-en", "install-ko")
PLANS = motion_plan.PLANS
MANIFEST = ROOT / "assets" / "install-motion.json"
# The picture-build shim, compiled with the setup program's own sources only here.
SHIM = "build/motion/InstallerRender.cs"
ENTRY = "CodexAutoResume.InstallerRender"
# What the picture is made from, beside the setup program's sources, the catalogs and the still: these files.
CODE = ("build/make_install_motion.py", SHIM, "build/motion_plan.py", "build/motion_compose.py", "build/motion_apng.py",
        "build/motion_fidelity.py")
# The captured stills of the real setup window the drawing is held to, by language: its Welcome page on a first
# installation, light, as the main session captures it. Whichever exist are held; the first that exists frames them.
FIDELITY = (("en", "assets/screenshot-setup.png"), ("ko", "assets/screenshot-setup-ko.png"))
# The installation every frame shows: the fixtures' user (nothing personal in a picture).
HOME = "C:\\Users\\ExampleUser\\.codex-auto-resume"

# A first installation's pages, in the window's order (InstallerFlow.Pages), and what a frame may set.
PAGES = ("welcome", "options", "progress", "finish")
STATE_KEYS = ("page", "progress", "hover", "pressed")
STEPS = ("hold", "set", "move", "hover", "press", "events")
HOLDING = ("set",)
# What the pointer goes to: the page's primary button (Next, Install, Finish), or a point.
TARGET = re.compile(r"button\.forward\Z")
EDITIONS = ("standard", "advanced")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# The longest a render may take, in seconds.
RENDER_LIMIT = 30 * 60


class PlanError(motion_plan.PlanError):
    """An install plan that cannot be drawn as written."""


def version(root: Path = ROOT) -> str:
    """The version the pictured setup program carries: .codex-plugin/plugin.json's."""
    return json.loads((root / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8-sig"))["version"]


# ---------------------------------------------------------------------------------------------------- reading
def plan_path(name) -> Path:
    path = Path(name)
    if path.suffix == ".json" and path.is_file():
        return path
    return PLANS / ("%s.json" % name)


def load(name) -> dict:
    """A plan by name or path, its scenes and events read in (`scenes_from`), its values put in, its `events` steps
    spelled out as the cuts they are, and checked (`check`)."""
    path = plan_path(name)
    plan = json.loads(path.read_text(encoding="utf-8"))
    if plan.get("format") != motion_plan.FORMAT or plan.get("kind") != "installer":
        raise PlanError("%s is not an installer plan" % path.name)
    if "scenes_from" in plan:
        shared = json.loads((path.parent / plan["scenes_from"]).read_text(encoding="utf-8"))
        plan["events"], plan["scenes"] = shared.get("events"), shared.get("scenes")
    # What a release changes, put in as it is now: the version and the name of the archive the setup program carries.
    import make_release
    values = dict(plan.get("values") or {}, version=version(),
                  archive=make_release.archive_name(plan.get("edition", "standard"), version()))
    plan["events"] = motion_plan._substitute(plan.get("events") or [], values)
    plan["scenes"] = spell_events(motion_plan._substitute(plan.get("scenes") or [], values), plan["events"])
    check(plan)
    return plan


def spell_events(scenes: list, events: list) -> list:
    """`scenes` with each {"events": [first, last]} step replaced by one cut an event, events[first..last] (1-based,
    inclusive): {"set": {"progress": n}, "hold": that event's hold}."""
    out = []
    for scene in scenes:
        steps = []
        for step in scene.get("steps") or []:
            if "events" not in step:
                steps.append(step)
                continue
            span = step["events"]
            if set(step) != {"events"} or not (isinstance(span, list) and len(span) == 2 and 1 <= span[0] <= span[1]
                                               <= len(events)):
                raise PlanError("%s: an events step names a span of the plan's events: %r" % (scene.get("id"), step))
            for number in range(span[0], span[1] + 1):
                steps.append({"set": {"progress": number}, "hold": int(events[number - 1].get("hold", 0))})
        out.append(dict(scene, steps=steps))
    return out


def check(plan: dict) -> None:
    """Raises PlanError for a plan that cannot be drawn: an unknown step, state, page or target; a delay under
    motion_plan.SHORTEST; pages out of the window's order or progress going back; a run that finishes before the
    installer has said everything; an event that is neither a line nor a share unpacked; a picture outside its
    `length`."""
    for key in ("name", "output", "locale", "edition", "canvas", "budget", "length", "pointer"):
        if key not in plan:
            raise PlanError("an installer plan has %s" % key)
    if plan["edition"] not in EDITIONS:
        raise PlanError("no edition %r" % plan["edition"])
    events = plan.get("events")
    if not isinstance(events, list) or not events:
        raise PlanError("an installer plan has the installer's events")
    share = 0.0
    for event in events:
        if len({"line", "unpacked"} & set(event)) != 1 or set(event) - {"line", "unpacked", "hold"}:
            raise PlanError("an event is a line the installer prints or a share unpacked: %r" % (event,))
        if int(event.get("hold", 0)) < motion_plan.SHORTEST:
            raise PlanError("an event is held at least %d ms: %r" % (motion_plan.SHORTEST, event))
        if "unpacked" in event:
            if not share < float(event["unpacked"]) <= 1.0:
                raise PlanError("the unpacked share rises to 1: %r" % (event,))
            share = float(event["unpacked"])
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
            unknown = set(step) - set(STEPS) - {"frames", "step"}
            if unknown:
                raise PlanError("%s: a step has keys no step has: %s" % (name, sorted(unknown)))
            if "frames" in step and (not isinstance(step["frames"], int) or step["frames"] < 1):
                raise PlanError("%s: a step draws at least one frame: %r" % (name, step))
            if "step" in step and step["step"] < motion_plan.SHORTEST:
                raise PlanError("%s: %d ms is shorter than a browser shows a frame for" % (name, step["step"]))
            for key in ("move", "hover", "press"):
                if key in step:
                    _check_target(name, step[key])
            if "set" in step:
                unknown = set(step["set"]) - set(STATE_KEYS)
                if unknown:
                    raise PlanError("%s: the window has no state %s" % (name, sorted(unknown)))
                if "page" in step["set"] and step["set"]["page"] not in PAGES:
                    raise PlanError("%s: a first installation has no page %r" % (name, step["set"]["page"]))
    frames = motion_plan.expand(plan)
    if any(b.t <= a.t for a, b in zip(frames, frames[1:])):
        raise PlanError("the frames' moments do not rise")
    walk_pages(frames, len(events))
    end = motion_plan.plan_end(plan)
    lo, hi = plan["length"]
    if not lo <= end <= hi:
        raise PlanError("the picture is %d ms long; the plan says %d to %d" % (end, lo, hi))


def _check_target(scene: str, target) -> None:
    if isinstance(target, dict):
        point = target.get("at", target.get("by"))
        if set(target) - {"at", "by"} or not (isinstance(point, list) and len(point) == 2):
            raise PlanError("%s: a point is {\"at\": [x, y]} or {\"by\": [dx, dy]}: %r" % (scene, target))
        return
    if not isinstance(target, str) or not TARGET.match(target):
        raise PlanError("%s: the setup window has nothing called %r" % (scene, target))


def walk_pages(frames: list, events: int) -> list:
    """The pages the frames show, in order, each once: exactly PAGES, starting on the first frame, the progress
    told only while the window is installing, never going back, and every event told before the Finish page."""
    shown, told = [], 0
    for frame in frames:
        state = dict(frame.window)
        page, progress = state.get("page"), int(state.get("progress") or 0)
        if not shown or shown[-1] != page:
            shown.append(page)
        if progress < told:
            raise PlanError("%s: the progress goes back from %d to %d" % (frame.scene, told, progress))
        if progress > told and page != "progress":
            raise PlanError("%s: the installer prints only while the window is installing" % frame.scene)
        if page == "finish" and progress != events:
            raise PlanError("%s: the run finishes after %d of %d events" % (frame.scene, progress, events))
        told = progress
    if tuple(shown) != PAGES:
        raise PlanError("the pages are %s, not a first installation's %s" % (shown, list(PAGES)))
    return shown


def schedule(plan: dict) -> tuple:
    """(frames, delays in ms, end in ms): every frame the plan's steps emit, with those the light and the ripples
    add, each with the delay it is held for."""
    end = motion_plan.plan_end(plan)
    frames = motion_plan.fill(motion_plan.expand(plan), end, int(plan.get("light_step_ms") or 0),
                              ripple_step=int(plan.get("ripple_step") or 0))
    return frames, motion_plan.delays([frame.t for frame in frames], end), end


def describe(plan: dict) -> str:
    """The frames a plan asks for, scene by scene, for reading before anything is drawn."""
    frames, held, end = schedule(plan)
    lines, counts = [], {}
    for frame, delay in zip(frames, held):
        entry = counts.setdefault(frame.scene, [0, 0, frame.t])
        entry[0] += 1
        entry[1] += delay
    for scene, (count, ms, start) in counts.items():
        lines.append("  %-5s at %6.2f s  %3d frames  %5.2f s" % (scene, start / 1000.0, count, ms / 1000.0))
    lines.append("  %d frames, %.2f s, %d window states, %d installer events"
                 % (len(frames), end / 1000.0, len(motion_plan.window_states(frames)), len(plan["events"])))
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------------- the window
def compile_shim(folder: Path, edition: str = "standard", root: Path = ROOT) -> Path:
    """The setup program's sources, as build/make_setup.py lists them, compiled with the shim into a scratch program
    in `folder` whose entry point is the shim's: the setup program's window, never the setup program."""
    import make_setup
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    exe = folder / "InstallerRender.exe"
    info = folder / "Setup.VersionInfo.cs"
    info.write_bytes(make_setup.version_source(edition, version(root), root).encode("ascii"))
    embedded = folder / "Setup.Embedded.cs"
    embedded.write_bytes(make_setup.embedded_source("picture.zip", b"").encode("ascii"))
    manifest = folder / "setup.manifest"
    manifest.write_bytes(make_setup.manifest_bytes(root))
    arguments = [str(make_setup.compiler()), "/nologo", "/utf8output", "/target:winexe", "/platform:x64", "/optimize+",
                 "/out:" + str(exe), "/win32manifest:" + str(manifest), "/main:" + ENTRY, "/nowarn:0649"]
    arguments += ["/reference:" + reference for reference in make_setup.REFERENCES]
    arguments += [str(root / SHIM), str(root / make_setup.SOURCE), str(root / make_setup.WINDOW)]
    arguments += [str(root / name) for name in make_setup.window_sources(root)]
    arguments += [str(info), str(embedded)]
    done = subprocess.run(arguments, capture_output=True, stdin=subprocess.DEVNULL, timeout=600,
                          creationflags=NO_WINDOW)
    if done.returncode != 0 or not exe.is_file():
        raise RuntimeError("the setup window did not compile:\n" + make_setup._said(done.stdout or b"")
                           + make_setup._said(done.stderr or b""))
    return exe


def job(plan: dict, frames: list, out: Path, root: Path = ROOT) -> dict:
    """The render job for `frames` of `plan`: the window's look, language, edition and version, the installer's
    events, and one entry per frame, in order."""
    canvas = plan.get("canvas") or {}
    states = []
    for index, frame in enumerate(frames):
        state = {key: value for key, value in motion_plan.thawed(frame.window).items() if key in STATE_KEYS}
        state.update(index=index, light=frame.t)
        states.append(state)
    import make_screenshots
    return {"out": str(out), "theme": canvas.get("theme", "light"), "design": canvas.get("design", "soft"),
            "scale": make_screenshots.PINNED_SCALE,
            "locale": plan["locale"], "locales": str(root / "src" / "codex_auto_resume" / "locales"),
            "edition": plan["edition"], "version": version(root), "home": HOME,
            "events": [{key: value for key, value in event.items() if key != "hold"} for event in plan["events"]],
            "targets": ["button.forward"], "frames": states}


def render(exe: Path, job_data: dict, folder: Path) -> dict:
    """Runs the shim on `job_data` (written into `folder`) and returns its frames.json, raising when it failed. It
    reads no installation: its Codex home and local application data are scratch folders of its own."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "job.json"
    path.write_text(json.dumps(job_data, ensure_ascii=False), encoding="utf-8")
    environment = dict(os.environ, CODEX_HOME=str(folder / "no-codex"), LOCALAPPDATA=str(folder / "no-local"))
    for name in ("CODEX_AUTO_RESUME_PLUGIN_HOME", "CODEX_AR_STILL_READY", "CODEX_AR_STILL_LIGHT", "CODEX_AR_STILL_NOW",
                 "CODEX_AR_STILL_CLOCK", "CODEX_AR_RENDER_PLAN"):
        environment.pop(name, None)
    done = subprocess.run([str(exe), str(path)], env=environment, timeout=RENDER_LIMIT, creationflags=NO_WINDOW,
                          capture_output=True, stdin=subprocess.DEVNULL)
    result = Path(job_data["out"]) / "frames.json"
    if not result.is_file():
        raise RuntimeError("the shim wrote no frames.json (exit %d)" % done.returncode)
    read = json.loads(result.read_text(encoding="utf-8"))
    if read.get("error") or done.returncode != 0:
        raise RuntimeError("the shim failed (exit %d): %s" % (done.returncode, read.get("error")))
    return read


def pictures(result: dict, folder: Path):
    """(frame index, (width, height), client RGB, bounds) for each frame the shim drew, the client picture rebuilt
    whole from each frame's changed rectangle - and started again whole where the window changed size."""
    picture, size = None, None
    for entry in result["frames"]:
        width, height = (int(value) for value in entry["client"])
        left, top, wide, tall = (int(value) for value in entry["box"])
        if (width, height) != size:
            if (left, top, wide, tall) != (0, 0, width, height):
                raise RuntimeError("frame %s is the window at a new size and not whole" % entry["index"])
            size = (width, height)
            picture = bytearray((Path(folder) / entry["file"]).read_bytes())
        elif entry["file"]:
            patch = (Path(folder) / entry["file"]).read_bytes()
            for row in range(tall):
                at = ((top + row) * width + left) * 3
                picture[at:at + wide * 3] = patch[row * wide * 3:(row + 1) * wide * 3]
        yield int(entry["index"]), size, bytes(picture), entry.get("bounds") or {}


# ---------------------------------------------------------------------------------------------------- the frame
def corner_rows(still: tuple) -> int:
    """How many rows at the bottom of a captured still hold a pixel that is not wholly opaque: the corners Windows
    rounds."""
    width, height, _rgb, alpha = still
    if alpha is None:
        return 0
    rows = 0
    for y in range(height - 1, -1, -1):
        if min(alpha[y * width:(y + 1) * width]) == 255:
            break
        rows += 1
    return rows


def framed_still(still: tuple, caption: int, client: tuple) -> tuple:
    """A still of the window at another client size: the captured still's caption rows, and its rounded bottom
    corners under a client area `client` (width, height) - what motion_compose.WindowChrome lays round a frame. The
    width is the captured one's, or it is not the same window."""
    width, height, rgb, alpha = still
    client_w, client_h = client
    if client_w != width:
        raise ValueError("the still is %d px wide and the client area %d: not the same window" % (width, client_w))
    corners = min(corner_rows(still), client_h)
    out_rgb = bytearray(rgb[:caption * width * 3]) + bytearray(width * client_h * 3)
    if alpha is None:
        return width, caption + client_h, bytes(out_rgb), None
    out_alpha = bytearray(alpha[:caption * width]) + bytearray(b"\xff" * (width * client_h))
    if corners:
        out_alpha[-corners * width:] = alpha[(height - corners) * width:]
    return width, caption + client_h, bytes(out_rgb), bytes(out_alpha)


def fidelity_still(root: Path = ROOT):
    """(locale, path) of the first captured still of the setup window that exists, or None."""
    for locale, name in FIDELITY:
        if (root / name).is_file():
            return locale, root / name
    return None


def at_rest() -> dict:
    """A one-frame plan state: the Welcome page at rest, its light at its first moment."""
    return {"index": 0, "page": "welcome", "light": 0}


def check_fidelity(exe: Path, work: Path, root: Path = ROOT, theme: str = "light", edition: str = "standard",
                   stills: Path | None = None) -> dict:
    """{"<locale>": comparison} of the Welcome page drawn now with each captured still that exists, and
    {"<locale>": client size} as `sizes` beside them."""
    import make_screenshots
    import motion_fidelity
    results = {}
    for locale, name in FIDELITY:
        # The stills where they are: in the tree, or where a proof drew them (`stills`, --still --out DIR).
        path = (stills or root) / name
        if not path.is_file():
            continue
        out = Path(work) / ("fidelity-" + locale)
        data = {"out": str(out / "frames"), "theme": theme, "design": "soft", "locale": locale,
                "scale": make_screenshots.PINNED_SCALE,
                "locales": str(root / "src" / "codex_auto_resume" / "locales"), "edition": edition,
                "version": version(root), "home": HOME, "events": [], "targets": [], "frames": [at_rest()]}
        result = render(exe, data, out)
        _index, size, picture, _bounds = next(pictures(result, out / "frames"))
        compared = motion_fidelity.compare(picture, make_screenshots.read_png(path), size)
        compared["client"] = list(size)
        results[locale] = compared
    return results


def draw_still(exe: Path, work: Path, locale: str, target: Path, root: Path = ROOT, theme: str = "light",
               edition: str = "standard") -> str:
    """Draws the Welcome page of a first installation in `locale` offscreen, as build/capture_window.ps1 captures the
    setup window on a monitor at the pinned scale (v0.6.20): the client area at that scale, Windows' title bar kept from
    such a capture above it and the corners cut (build/window_frame.py) - into `target`; its size."""
    import make_screenshots
    import window_frame
    out = Path(work) / ("still-" + locale)
    data = {"out": str(out / "frames"), "theme": theme, "design": "soft", "locale": locale,
            "scale": make_screenshots.PINNED_SCALE,
            "still": window_frame.still_job("setup", make_screenshots.PINNED_DPI, theme),
            "locales": str(root / "src" / "codex_auto_resume" / "locales"), "edition": edition,
            "version": version(root), "home": HOME, "events": [], "targets": [], "frames": [at_rest()]}
    render(exe, data, out)
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    make_screenshots.copy_file(out / "frames" / "still-00000.png", target)
    return make_screenshots.dimensions(Path(target))


def render_input(plan: dict, root: Path = ROOT) -> str:
    """The digest an install picture is made from: its plan as read, the setup program's sources as make_setup.py
    compiles them, the catalogs of its language and English, the still its frame is taken from and this generator's
    own files - so a change to any of them marks the picture stale (tests/test_install_motion.py)."""
    import make_screenshots as shots
    import make_setup
    parts = [json.dumps(plan, sort_keys=True, ensure_ascii=False), version(root)]
    sources = [make_setup.SOURCE, make_setup.WINDOW, make_setup.MANIFEST] + make_setup.window_sources(root)
    parts += ["%s\0%s" % (name, shots.input_digest(root / name)) for name in sources]
    for locale in sorted({"en", plan["locale"]}):
        parts.append(shots.input_digest(root / "src" / "codex_auto_resume" / "locales" / ("%s.json" % locale)))
    for _locale, name in FIDELITY:
        if (root / name).is_file():
            parts.append(shots.input_digest(root / name))
    parts += [shots.input_digest(root / name) for name in CODE]
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


def read_manifest() -> dict:
    if MANIFEST.is_file():
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {"inputs": {}, "images": {}, "fidelity": {}}


def prune(manifest: dict) -> dict:
    """`manifest` with only what a plan of PLAN_NAMES makes: a picture no plan makes any more, and its inputs, go."""
    outputs = {json.loads(plan_path(name).read_text(encoding="utf-8"))["output"] for name in PLAN_NAMES}
    manifest["images"] = {key: value for key, value in (manifest.get("images") or {}).items() if key in outputs}
    inputs = {"<install-motion:%s>" % name for name in PLAN_NAMES}
    manifest["inputs"] = {key: value for key, value in (manifest.get("inputs") or {}).items() if key in inputs}
    return manifest


def write_manifest(manifest: dict) -> None:
    prune(manifest)
    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def make(plan: dict, exe: Path, work: Path, still: tuple | None, caption: int, output: Path):
    """Draws `plan`'s picture into `output` and returns the assembler's Report. With `still` (a captured still of the
    setup window and its caption's height) the window is framed as Windows frames it, on a clear canvas the size of
    the window; without one the canvas is the client area alone (a proof)."""
    import motion_apng
    import motion_compose
    from codex_auto_resume import brand
    frames, held, end = schedule(plan)
    canvas = plan["canvas"]
    theme, design = canvas.get("theme", "light"), canvas.get("design", brand.DEFAULT_DESIGN)
    result = render(exe, job(plan, frames, work / "frames"), work)
    sizes = sorted({tuple(int(value) for value in entry["client"]) for entry in result["frames"]})
    if len(result["frames"]) != len(frames):
        raise RuntimeError("the shim drew %d frames of %d" % (len(result["frames"]), len(frames)))
    width = max(size[0] for size in sizes)
    height = max(size[1] for size in sizes) + (caption if still is not None else 0)
    if len({size[0] for size in sizes}) != 1:
        raise RuntimeError("the window changed its width: %s" % sizes)
    chromes = {}
    for size in sizes:
        if still is not None:
            chromes[size] = motion_compose.WindowChrome(framed_still(still, caption, size), size,
                                                        size=(width, height), at=(0, 0), ground=None, shadow=False,
                                                        scale=float(result.get("dpi_scale") or 1.5))
    accent = tuple(brand.rgb(brand.palette(theme, design)["accent"]))
    scale = float((plan.get("pointer") or {}).get("scale", 1.5))
    seen_bounds, standing = {}, {}
    origin = (0, caption if still is not None else 0)
    drawn = pictures(result, work / "frames")

    def draw(frame, index):
        number, size, client, bounds = next(drawn)
        if number != index:
            raise RuntimeError("the shim's frame %d came where frame %d was wanted" % (number, index))
        seen_bounds.update(bounds)
        if still is not None:
            picture = chromes[size].frame(client)
        else:
            picture = bytearray(width * height * 4)
            for y in range(size[1]):
                row = client[y * size[0] * 3:(y + 1) * size[0] * 3]
                line = bytearray(size[0] * 4)
                line[0::4], line[1::4], line[2::4], line[3::4] = row[0::3], row[1::3], row[2::3], b"\xff" * size[0]
                picture[y * width * 4:y * width * 4 + size[0] * 4] = line
        if frame.pointer[0] == "at" and frame.pointer in standing:
            x, y = standing[frame.pointer]
        else:
            x, y = motion_compose.pointer_at(frame, seen_bounds, origin)
            standing.clear()
            if frame.pointer[0] == "at":
                standing[frame.pointer] = (x, y)
        pressed = dict(frame.window).get("pressed") is not None
        motion_compose.draw_pointer(picture, width, height, x, y, scale=scale, pressed=pressed,
                                    ripple=motion_plan.ripple_at(frame), accent=accent)
        return bytes(picture)

    def run():
        previous = None
        for index, (frame, delay) in enumerate(zip(frames, held)):
            picture = draw(frame, index)
            if previous is not None and picture == previous[2]:
                previous[0] += delay
                continue
            if previous is not None:
                yield tuple(previous)
            previous = [delay, frame.scene, picture]
        if previous is not None:
            yield tuple(previous)

    budget = plan.get("budget") or {}
    return motion_apng.assemble(output, width, height, run(), target=budget.get("target"), cap=budget.get("cap"),
                                alpha=True), (width, height)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    out_dir = None
    if "--out" in argv:
        at = argv.index("--out")
        out_dir = Path(argv[at + 1])
        del argv[at:at + 2]
    names = [item for item in argv if not item.startswith("--")] or list(PLAN_NAMES)
    plans = [load(name) for name in names]
    if "--dry-run" in argv:
        for plan in plans:
            print("%s -> %s" % (plan["name"], plan["output"]))
            print(describe(plan))
        return 0
    client_only = "--client-only" in argv
    if client_only and out_dir is None:
        raise SystemExit("--client-only draws a proof: give it --out DIR")
    stills_root = ROOT
    if "--still" in argv:
        # v0.6.20: the Welcome still(s) drawn offscreen first - into assets/, or with --out into DIR, which the rest of
        # the run then holds the window to and frames it with.
        with tempfile.TemporaryDirectory(prefix="install-still-") as name:
            work = Path(name)
            edition = plans[0]["edition"] if plans else "standard"
            exe = compile_shim(work / "shim", edition)
            theme = (plans[0]["canvas"].get("theme") if plans else None) or "light"
            wanted = [(locale, still) for locale, still in FIDELITY if (ROOT / still).is_file()] or [FIDELITY[-1]]
            for locale, still in wanted:
                target = (out_dir / still) if out_dir is not None else ROOT / still
                print("still %-4s %s  %s  (drawn offscreen)" % (locale, target, draw_still(exe, work, locale, target,
                                                                                         theme=theme, edition=edition)))
        if out_dir is not None:
            stills_root = out_dir
    found = fidelity_still(stills_root)
    if found is None and not client_only:
        raise SystemExit("no captured still of the setup window (%s): capture one first, or draw a proof with "
                         "--out DIR --client-only" % ", ".join(name for _locale, name in FIDELITY))
    manifest = read_manifest()
    with tempfile.TemporaryDirectory(prefix="install-motion-") as name:
        work = Path(name)
        edition = plans[0]["edition"] if plans else "standard"
        exe = compile_shim(work / "shim", edition)
        theme = (plans[0]["canvas"].get("theme") if plans else None) or "light"
        results = check_fidelity(exe, work, theme=theme, edition=edition, stills=stills_root)
        for key in sorted(results):
            result = results[key]
            print("fidelity %-4s %s  exact %.4f%%  worst %d  outside %d%s"
                  % (key, "pass" if result["passed"] else "FAIL", 100 * result["exact"], result["worst"],
                     result["outside"], "  (%s)" % result["why"] if result.get("why") else ""))
        if out_dir is None and results:
            manifest["fidelity"] = results
            write_manifest(manifest)
        failed = sorted(key for key, result in results.items() if not result["passed"])
        if failed:
            raise SystemExit("the setup window drawn offscreen is not the captured one in %s" % ", ".join(failed))
        if "--fidelity" in argv:
            return 0
        still, caption = None, 0
        if found is not None and not client_only:
            import make_screenshots
            locale, path = found
            still = make_screenshots.read_png(path)
            caption = still[1] - results[locale]["client"][1]
            if caption < 0:
                raise SystemExit("%s is shorter than the window's client area" % path)
        for plan in plans:
            output = (out_dir / Path(plan["output"]).name) if out_dir is not None else ROOT / plan["output"]
            report, size = make(plan, exe, work / plan["name"], still, caption, output)
            print("%s  %d bytes, %d frames, %.2f s, %dx%d%s" % (output, report.size, report.frames, report.ms / 1000.0,
                                                                size[0], size[1],
                                                                "  OVER THE TARGET" if report.over_target else ""))
            if out_dir is not None:
                continue
            key = str(Path(plan["output"])).replace("\\", "/")
            manifest["inputs"]["<install-motion:%s>" % plan["name"]] = render_input(plan)
            manifest["images"][key] = {"sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                                       "size": "%dx%d" % size, "bytes": report.size, "frames": report.frames,
                                       "ms": report.ms, "scenes": report.scenes}
            write_manifest(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
