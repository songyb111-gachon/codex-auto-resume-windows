"""The host's render mode as the surfaces' picture maker (v0.6.27, S6.3f; P6-DESIGN 3.2, comparisons B and C).

build/make_screenshots.py's surface functions and build/motion_{popup,tip,card}.py draw the popup, the icon's hover card and
the notification card through the reference's own renderers. With the render mode asked for (`CODEX_AR_SURFACE_RENDER=1`,
or a session handed to them) they make the same calls, with the same arguments, of the stand-ins here, which ask the C#
surfaces (gui/host.sources [surface], gui/SurfaceRenderServe.cs) to make them: the plans are the C#'s, and every picture
is the C#'s premultiplied BGRA, read back from the render mode's frames folder. The scripts around them - the motion
plans, the moments, the faces, the compositing, the PNG and APNG writers - are unchanged.

The render mode is the host's (`CODEX_AR_SURFACE_EXE` names a built CodexAutoResume.exe, whose Main asks
SurfaceRender.Run() first); without one, the surfaces are compiled here with the in-box csc behind the same entry, into a
scratch folder named after the sources' digest. It runs with CREATE_NO_WINDOW, shows nothing and makes no window: it
draws into memory with this machine's fonts - which is why the pictures are the main session's, on the picture machine.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "src"), str(ROOT / "build")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
FORMAT = "car-surface-job/1"
# The variable that asks the picture makers for the render mode, and the one that names a built host.
SWITCH = "CODEX_AR_SURFACE_RENDER"
HOST = "CODEX_AR_SURFACE_EXE"
GROUPS = ("contract", "surface", "generated")
# The host's entry for the render mode alone: what its Main asks before anything else (S6.2b).
DRIVER = """
namespace CodexAutoResume
{
    internal static class SurfaceRenderDriver
    {
        private static int Main(string[] args)
        {
            return SurfaceRender.Run() ?? 2;
        }
    }
}
"""


def wanted() -> bool:
    """Whether the picture makers are asked to draw through the render mode."""
    return os.environ.get(SWITCH, "").strip() not in ("", "0")


def sources(root: Path = ROOT) -> list:
    """The [contract], [surface] and [generated] files of gui/host.sources, in order (tests/guiscan.py reads it alike)."""
    groups, group = {}, None
    for line in (root / "gui" / "host.sources").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            group = line[1:-1]
            continue
        groups.setdefault(group, []).append(root / line)
    return [path for name in GROUPS for path in groups.get(name, [])]


def executable() -> Path:
    """The render mode's program: the built host `CODEX_AR_SURFACE_EXE` names, or the surfaces compiled here once per
    digest of their sources."""
    named = os.environ.get(HOST)
    if named:
        return Path(named)
    files = sources()
    digest = hashlib.sha256(DRIVER.encode("utf-8"))
    for path in files:
        digest.update(path.name.encode("utf-8") + b"\0" + path.read_bytes())
    folder = Path(tempfile.gettempdir()) / "car-surface-render" / digest.hexdigest()[:16]
    exe = folder / "surface-render.exe"
    if exe.is_file():
        return exe
    folder.mkdir(parents=True, exist_ok=True)
    driver = folder / "SurfaceRenderDriver.cs"
    driver.write_text(DRIVER, encoding="utf-8")
    building = folder / "building.exe"
    done = subprocess.run([str(CSC), "-nologo", "-target:exe", "-platform:x64", "-warnaserror", "-optimize+",
                           "-out:%s" % building, "-r:System.dll", "-r:System.Drawing.dll"]
                          + [str(path) for path in files] + [str(driver)],
                          capture_output=True, timeout=600, creationflags=NO_WINDOW)
    if done.returncode != 0:
        raise RuntimeError("the surfaces do not compile:\n%s" % done.stdout.decode("utf-8", "replace"))
    os.replace(building, exe)
    return exe


def wire(value):
    """A value as the render mode reads it: a frame (a named tuple) as its fields, tuples as lists."""
    if hasattr(value, "_asdict"):
        return {key: wire(one) for key, one in value._asdict().items()}
    if isinstance(value, dict):
        return {str(key): wire(one) for key, one in value.items()}
    if isinstance(value, (list, tuple)):
        return [wire(one) for one in value]
    return value


def _tupled(value):
    return tuple(_tupled(one) for one in value) if isinstance(value, list) else value


class Plan(dict):
    """A plan the C# laid out: its dump, as the reference's plan dictionary (its targets tuples again, as the reference's
    are, so they key a dictionary), and the handle the render mode keeps it by."""

    def __init__(self, dump, handle):
        super().__init__(dump)
        self.handle = handle
        for item in self.get("items", ()):
            if isinstance(item, dict) and "target" in item:
                item["target"] = _tupled(item["target"])
        if "targets" in self:
            self["targets"] = [(_tupled(target), tuple(rect)) for target, rect in self["targets"]]


class Session:
    """One render mode, serving the calls of one picture maker. Close it when done."""

    def __init__(self, pinned: str | None = None, exe: Path | None = None):
        self.folder = Path(tempfile.mkdtemp(prefix="car-surface-render-"))
        job = self.folder / "job.json"
        job.write_text(json.dumps({"format": FORMAT, "serve": True, "frames": str(self.folder / "frames"),
                                   "pinned": pinned}), encoding="utf-8")
        environment = dict(os.environ, CODEX_AR_RENDER_PLAN=str(job), CODEX_AR_RENDER_OUT=str(self.folder / "answer.json"))
        self.process = subprocess.Popen([str(exe or executable())], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        env=environment, creationflags=NO_WINDOW)
        self.asked = 0
        self.log = []                       # every call and its arguments, in order (the structure check reads it)

    def call(self, name: str, **args):
        self.asked += 1
        self.log.append((name, wire(args)))
        line = json.dumps({"id": self.asked, "call": name, "args": wire(args)}, ensure_ascii=True) + "\n"
        self.process.stdin.write(line.encode("utf-8"))
        self.process.stdin.flush()
        answer = json.loads(self.process.stdout.readline().decode("utf-8") or "{}")
        if answer.get("id") != self.asked or "error" in answer:
            raise RuntimeError("the render mode refused %s: %s" % (name, answer.get("error", answer)))
        return answer.get("ok")

    def picture(self, answer) -> bytes:
        """The BGRA picture an answer names, read and let go."""
        path = Path(answer["file"])
        data = path.read_bytes()
        path.unlink()
        if len(data) != answer["bytes"] or hashlib.sha256(data).hexdigest() != answer["digest"]:
            raise RuntimeError("the render mode's picture %s is not the one it answered" % path)
        return data

    def renderer(self, **look) -> "Renderer":
        return Renderer(self, **look)

    def card(self, notice, *, now_ms, where, drawn, hold) -> "Card":
        return Card(self, notice, now_ms=now_ms, where=where, drawn=drawn, hold=hold)

    def close(self) -> None:
        if self.process is not None:
            try:
                self.process.stdin.close()
                self.process.wait(timeout=60)
                self.process.stdout.close()
            finally:
                self.process = None
                shutil.rmtree(self.folder, ignore_errors=True)


def session(pinned=True) -> Session:
    """A session whose UI face is the stills' (make_screenshots.pinned_face), as every surface picture is drawn."""
    face = None
    if pinned:
        import make_screenshots
        from codex_auto_resume.ui.popup import fonts
        with make_screenshots.pinned_face():
            face = fonts._ui_face()
    return Session(face)


class _Canvas:
    def __init__(self, owner):
        self._owner = owner

    def pixels(self) -> bytes:
        owner = self._owner
        return owner.session.picture(owner.session.call("pixels", renderer=owner.handle))


class Renderer:
    """The popup's Renderer and the icon's TipRenderer, drawn by the C#: the same attributes and calls."""

    def __init__(self, session: Session, *, theme="light", design="soft", contrast=False, lone=False):
        self.session = session
        self.theme, self.design, self.contrast, self.lone = theme, design, contrast, lone
        self.letters = None
        self.halo_rows = None
        self.handle = session.call("open_renderer", **self._look())["renderer"]
        self.canvas = _Canvas(self)
        self._items = {}

    def _look(self) -> dict:
        return {"theme": self.theme, "design": self.design, "contrast": bool(self.contrast), "lone": bool(self.lone),
                "letters": self.letters}

    def _plan(self, answer) -> Plan:
        plan = Plan(answer["dump"], answer["plan"])
        for index, item in enumerate(plan.get("items", ())):
            self._items[id(item)] = (plan, index)
        return plan

    def _use(self, locale):
        from codex_auto_resume.ui.popup import fonts
        self.letters = fonts._letters(locale)

    def layout(self, vm, scale, locale) -> Plan:
        self._use(locale)
        return self._plan(self.session.call("layout", renderer=self.handle, vm=vm, scale=float(scale), locale=locale,
                                            **self._look()))

    def tip_layout(self, parts, light, scale, locale, day=None) -> Plan:
        self._use(locale)
        return self._plan(self.session.call("tip_layout", renderer=self.handle, parts=parts, light=light,
                                            scale=float(scale), locale=locale, day=day, **self._look()))

    def draw(self, vm, plan, *, frame=None, hover=None, pressed=None, focus=None, glides=None, scene_ms=0.0, faces=None):
        self.session.call("draw", renderer=self.handle, plan=plan.handle, frame=frame, hover=hover, pressed=pressed,
                          focus=focus, glides=[[target, amount] for target, amount in (glides or {}).items()],
                          scene_ms=float(scene_ms),
                          faces=[[target, fill, edge, amount] for target, ((fill, edge), amount) in (faces or {}).items()],
                          **self._look())
        return self.canvas

    def _light(self, name, plan, frame):
        self.halo_rows = self.session.call(name, renderer=self.handle, plan=plan.handle, frame=frame, **self._look())["rows"]
        return self.canvas

    def draw_halo(self, plan, frame, *, restore=True):
        if not restore:
            raise NotImplementedError("the picture makers draw the light restored")
        return self._light("draw_halo", plan, frame)

    def draw_tip(self, plan, frame=None):
        return self._light("draw_tip", plan, frame)

    def draw_tip_light(self, plan, frame, *, restore=True):
        if not restore:
            raise NotImplementedError("the picture makers draw the light restored")
        return self._light("draw_tip_light", plan, frame)

    def face_colours(self, item, state) -> tuple:
        plan, index = self._items[id(item)]
        fill, edge = self.session.call("face_colours", renderer=self.handle, plan=plan.handle, index=index, state=state,
                                       **self._look())
        return tuple(fill), tuple(edge)

    def card_still(self, plan, pad=None) -> tuple:
        answer = self.session.call("card_still", renderer=self.handle, plan=plan.handle, pad=pad, **self._look())
        return answer["width"], answer["height"], self.session.picture(answer)

    def close(self) -> None:
        if self.handle is not None and self.session.process is not None:
            self.session.call("close", handle=self.handle)
        self.handle = None


class _LayerPixels:
    def __init__(self, card, which):
        self._card, self._which = card, which

    def pixels(self) -> bytes:
        return self._card._layers()[self._which]


class Card:
    """notice_window.Card offscreen (windows=False), drawn by the C#: its size, margin, plan and view, its pointer marks and
    light, `paint(now_ms)` and its two layers' pixels. The motion a picture gives it is said through `follow`, and every
    frame the C# paints is checked against the reference's own motion arithmetic for the same moment."""

    def __init__(self, session: Session, notice, *, now_ms, where, drawn, hold):
        from codex_auto_resume import notice_card
        from codex_auto_resume.ui.popup import fonts
        self.session = session
        self.notice = notice
        view = notice_card.view(notice)
        answer = session.call("open_card", vm=view, title=notice.title, stays=getattr(notice, "stays", False) is True,
                              hold=float(hold), now=float(now_ms), dpi=float(where["dpi"]), work=list(where["work"]),
                              drawn=drawn, letters=fonts._letters(view["locale"]))
        self.handle = answer["card"]
        self.size, self.margin = tuple(answer["size"]), answer["margin"]
        self.plan, self.vm = answer["plan"], answer["vm"]
        self.born, self._edge = float(now_ms), "bottom"
        self.hover = self.pressed = None
        self._breathed = float(now_ms)
        self.motion = None
        self.body, self.shadow = _LayerPixels(self, "body"), _LayerPixels(self, "shadow")
        self._painted = None

    @property
    def edge(self):
        return self._edge

    @edge.setter
    def edge(self, value):
        self._edge = value
        self.session.call("card_set", card=self.handle, edge=value)

    def follow(self, motion, born, hold, place, leave=None):
        """The motion a picture gives the card - CardMotion(born, hold_ms=hold), move_to(born, place), retire(leave) - in
        the render mode, beside `motion`, the reference's own, which every paint is checked against."""
        self.motion, self.born = motion, float(born)
        self.session.call("card_motion", card=self.handle, born=float(born), hold=float(hold), place=list(place),
                          leave=None if leave is None else float(leave))

    def redraw(self):
        self.session.call("card_set", card=self.handle, hover=self.hover, pressed=self.pressed,
                          breathed=float(self._breathed))
        self.session.call("card_redraw", card=self.handle)
        self._painted = None

    def light_band(self, now_ms) -> tuple:
        """(top, bottom, the image's rows between) after the card's breath at `now_ms` (Card._draw_light)."""
        answer = self.session.call("card_light", card=self.handle, ms=float(now_ms))
        self._painted = None
        top, bottom = answer["rows"]
        return top, bottom, self.session.picture(answer["band"])

    def _draw_light(self, now_ms):
        self.light_band(now_ms)

    def paint(self, now_ms) -> dict:
        from codex_auto_resume import notice_card
        answer = self.session.call("card_paint", card=self.handle, ms=float(now_ms))
        frame = notice_card.Frame(**answer["frame"])
        if self.motion is not None:
            mine, at = self.motion.frame(now_ms), self.motion.place(now_ms) or (0, 0)
            if tuple(mine) != tuple(frame) or self.motion.gone != answer["gone"]:
                raise RuntimeError("the render mode's card moved otherwise at %r: %r, not %r" % (now_ms, frame, mine))
            del at
        self._painted = None
        key = tuple(float(part) if "." in part or "E" in part else int(part) for part in answer["key"].split(","))
        return {"frame": frame, "x": answer["x"], "y": answer["y"], "margin": answer["margin"], "key": key}

    def _layers(self) -> dict:
        if self._painted is None:
            answer = self.session.call("card_layers", card=self.handle)
            self._painted = {"body": self.session.picture(answer["body"]), "shadow": self.session.picture(answer["shadow"])}
        return self._painted

    def close(self) -> None:
        if self.handle is not None and self.session.process is not None:
            self.session.call("close", handle=self.handle)
        self.handle = None
