"""The notification-area popup in a motion picture: its own paint at a pinned moment, offscreen.

The popup is drawn as the product draws it (`ui/popup/renderer.py`), from the same sample rows the still is
(make_screenshots.popup_view), at the stills' scale. What a person sees happen to it is only what the product does:

- It opens as the product opens it (v0.6.23, tests/test_popup_opening_motion.py): its two layered windows, the card and
  its shadow, fade in over brand's transition and rise `SPACING xs` into place on brand's curve (`ui.popup.motion.opening`,
  `PopupFrames.opening`), a frame every 16 ms. It is hidden with SW_HIDE (`hide`), so it goes at once: a click anywhere else
  closes it (WM_ACTIVATE), and a plan closes it with a cut (motion_plan's `popup` step).
- It stands where `ui.popup.placement.place` puts it (`PopupFrames.origin`): centred on the icon, `SPACING m` above the
  taskbar's work area and inside it, so with the icon at the taskbar's right end its card's right edge is that gap from the
  screen's; its shadow reaches past the card, over the taskbar and past the screen's edge, which a picture keeps whole.
- Its status light breathes on the clock of the state it shows (`ui.popup.motion.halo`), which starts when the state
  is entered and is not restarted by closing and opening again: the picture's own clock, from its first moment. A
  picture whose length is whole breaths loops without a jump.
- Its countdowns are drawn again every second it is open (TIMER_TICK, 1000 ms): the picture's `ticks` since it was
  opened, one more second of the sample's clock each.
- Nothing of the popup is drawn for a pointer over a switch or a row (the renderer's hover face is a button's only,
  and a press has none on a switch), so the pointer is all a viewer sees of it. A pointer over one of its two buttons
  gives it its hover face, gliding there and back as the popup glides it (v0.6.26, audit-apng M8: `messages._face_glides`
  - from what it showed, in `motion.face_length`, on brand's curve), even as it only passes over on its way to a switch.
- A press on a row's switch only fades the switch (PopupModel.begin: busy) while the control layer's answer is
  awaited; the answer (PopupModel.apply_outcome) changes the row and the switch then glides, knob and track, in
  brand's transition time on its curve (`glide_amount`) - at the popup's own 33 ms frame timer.

Each view below is the model's own: the rows are read, a press is `action_for` + `begin`, an answer is
`apply_outcome` - nothing is drawn that the model would not say. Frames are drawn whole when the ground changes
(a countdown, a row's tone, a busy switch, a glide) and only the light otherwise (`Renderer.draw_halo`), as the
popup's frame timer does.
"""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "src"), str(ROOT / "build")):
    if _path not in sys.path:
        sys.path.insert(0, _path)


class PopupFrames:
    """One popup, for one picture: `drawn(frame, closed)` is the picture at the frame's moment.

    `render`, a build/surface_render.py session, draws it through the host's render mode (the C# surfaces) instead of
    the reference's renderer: the same calls with the same arguments. Close it when done: the renderer holds GDI+
    objects."""

    def __init__(self, locale: str, *, scale: float, theme: str = "light", design: str | None = None, render=None):
        import make_screenshots as shots
        from codex_auto_resume import brand, interface
        from codex_auto_resume.ui import popup as tray_popup
        from codex_auto_resume.ui.popup.motion import glide_amount
        self.shots, self.tray, self.glide_amount = shots, tray_popup, glide_amount
        self.strings = interface.STRINGS[locale]
        self.locale = tray_popup.locale_of(self.strings)
        self.scale = scale
        self.design = design or brand.DEFAULT_DESIGN
        self.renderer = render.renderer() if render is not None else tray_popup.Renderer()
        self.renderer.theme = theme
        self.renderer.design = self.design
        # v0.6.24: the popup is its card alone, with a float shadow under it (the card window and the shadow window);
        # a picture of it is that card and its shadow on a clear ground, `pad` round it, as the stills are
        # (popup_picture): RGBA, so the plan's canvas is a transparent one.
        self.renderer.lone = True
        self.theme = theme
        self.pad = tray_popup.layers.still_pad(scale)
        self._views = {}
        self._held = None             # the view whose ground the renderer's canvas holds, or None
        # The buttons' faces (v0.6.26): what each showed at the last frame, and each glide on its way - {target: (started
        # ms, (fill, edge) it left from, length ms)}, as messages._face_glides keeps them.
        self._face_states, self._faces = None, {}
        card = self.view((), (), 0)[1]["card"]
        self.shift = (self.pad - card[0], self.pad - card[1])
        self.size = (card[2] - card[0] + 2 * self.pad, card[3] - card[1] + 2 * self.pad)

    def view(self, off=(), busy=(), ticks=0):
        """(the model's view, its layout) with the rows in `off` switched off, the rows in `busy` awaiting an answer,
        and `ticks` seconds of the sample's clock gone since the popup was opened. Rows count from 1."""
        key = (tuple(off), tuple(busy), int(ticks))
        if key not in self._views:
            shots = self.shots
            model = self.tray.PopupModel(self.strings)
            now = shots.POPUP_NOW + key[2]
            model.apply_outcome(("read",), ("ok", {"rows": shots.popup_rows(), "status": shots.popup_status()}), now)
            vm = model.view(now)
            tasks = [task["interruption_id"] for task in vm["tasks"]]
            for row in key[0]:
                action = model.action_for(("check", tasks[row - 1]))
                model.begin(action)
                model.apply_outcome(action, ("ok", {"enabled": bool(action[3])}), now)
                vm = model.view(now)
            for row in key[1]:
                model.begin(model.action_for(("check", tasks[row - 1])))
                vm = model.view(now)
            with shots.pinned_face():           # the stills' face (make_screenshots.pinned_face, F1)
                self._views[key] = (vm, self.renderer.layout(vm, self.scale, self.locale), tasks)
        vm, plan, _tasks = self._views[key]
        return vm, plan

    def bounds(self) -> dict:
        """{"popup.switch.<n>": (left, top, width, height)} of each row's Auto-resume switch, rows counted from 1, in
        the canvas's pixels - where the popup's own layout puts them, moved with the card in the picture."""
        plan = self.view()[1]
        dx, dy = self.shift
        rects = [item["rect"] for item in plan["items"] if item["kind"] == "switch"]
        return {"popup.switch.%d" % (index + 1): (rect[0] + dx, rect[1] + dy, rect[2] - rect[0], rect[3] - rect[1])
                for index, rect in enumerate(rects)}

    def origin(self, work, monitor, anchor) -> tuple:
        """Where this picture's top-left goes on a canvas, so that the card stands where the product puts it: beside the
        icon's rectangle `anchor` on the taskbar's side, `SPACING m` from the taskbar and the work area's edges
        (`Popup._move`: the placement is the card's own, its shadow reaching into the gap)."""
        from codex_auto_resume import brand
        gap = int(round(brand.SPACING["m"] * self.scale))
        card = self.view((), (), 0)[1]["card"]
        x, y, _edge = self.tray.place((card[2] - card[0], card[3] - card[1]), tuple(work), tuple(monitor),
                                      tuple(anchor), gap=gap)
        return x - self.pad, y - self.pad

    def opening(self, frame) -> tuple:
        """(alpha 0-255, rows below its place, whether it has arrived) of the popup at `frame`: the opening's own
        arithmetic (`ui.popup.motion.opening`) `elapsed` ms after it was opened, the rise being what `_start_opening`
        asks - `SPACING xs` at the popup's scale."""
        from codex_auto_resume import brand
        from codex_auto_resume.ui.popup.motion import opening
        elapsed = frame.t - dict(frame.popup)["opened"]
        return opening(elapsed, max(1, int(round(brand.SPACING["xs"] * self.scale))))

    def hovered(self, point, below: int = 0):
        """The target of the button under `point` (x, y in this picture's pixels, the popup `below` its place while it
        rises), or None: what the popup's own hit test gives a WM_MOUSEMOVE there. Only a button has a hover face."""
        if point is None:
            return None
        x, y = point[0] - self.shift[0], point[1] - self.shift[1] - below
        for item in self.view()[1]["items"]:
            if item["kind"] != "button":
                continue
            left, top, right, bottom = item["rect"]
            if left <= x < right and top <= y < bottom:
                return item["target"]
        return None

    def faces(self, plan, hover, now) -> dict:
        """{target: ((fill, edge) it left from, how far on)} for the buttons part way to a new face at `now` (ms):
        messages._face_glides on the picture's clock - one starts for each button whose state changed since the frame
        before, from what it showed, in motion.face_length; a finished one is let go. None glides on the popup's first
        frame."""
        from codex_auto_resume.ui.popup.motion import face_amount, face_length, face_state, mixed
        states = {item["target"]: (item, face_state(item, hover, None)) for item in plan["items"]
                  if item["kind"] == "button"}
        before = self._face_states or {}
        self._face_states = {target: state for target, (_item, state) in states.items()}
        shown = {}
        for target, (item, state) in states.items():
            face, was = self._faces.get(target), before.get(target, state)
            if was != state:
                colours = self.renderer.face_colours(item, was)
                if face is not None:
                    amount = face_amount(face, now)[0]
                    colours = tuple(mixed(one, other, amount) for one, other in zip(face[1], colours))
                face = (now, colours, face_length(was, state))
            amount, done = face_amount(face, now) if face is not None else (1.0, True)
            if done:
                self._faces.pop(target, None)
            else:
                self._faces[target], shown[target] = face, (face[1], amount)
        return shown

    def drawn(self, frame, closed: bytes, light_at=None, pointer=None) -> bytes:
        """The RGBA picture (straight alpha) at `frame`: `closed`, a clear canvas, while no popup is open. Its light is
        drawn at the frame's moment, or at `light_at` where that is given (the still's own: the first of its breath).
        `pointer` is where the pointer stands, in this picture's pixels, for a button's hover face (`hovered`)."""
        if not frame.popup:
            self._held = None
            self._face_states, self._faces = None, {}
            return closed
        state = dict(frame.popup)
        ticks = (frame.t - state["opened"]) // 1000
        key = (tuple(state["off"]), tuple(state["busy"]), int(ticks))
        vm, plan = self.view(*key)
        tasks = self._views[key][2]
        gliding = {}
        for row, (started, begin, end) in state["glides"]:
            amount, done = self.glide_amount((started, begin, end), frame.t)
            if not done:
                gliding[("check", tasks[row - 1])] = amount
        moment = frame.t if light_at is None else light_at
        light = self.tray.halo(vm["light"], moment, moment, design=self.design)
        # `pointer` is in this picture's own pixels, and the picture is laid `below` its place while it rises
        # (make_motion.make, its popup layer): the rise is already out of it, as the product hit-tests in the risen window's
        # own coordinates. Taken out again, a pointer at a button's top was missed for the opening's 160 ms (audit4 F3).
        hover = self.hovered(pointer)
        faces = self.faces(plan, hover, frame.t)
        with self.shots.pinned_face():
            if gliding or hover is not None or faces:
                self.renderer.draw(vm, plan, frame=light, glides=gliding, hover=hover, faces=faces)
                self._held = None
            elif self._held == key:
                self.renderer.draw_halo(plan, light)
            else:
                self.renderer.draw(vm, plan, frame=light)
                self._held = key
        _w, _h, bgra = self.shots.popup_picture(self.renderer, plan, self.pad, self.theme, self.design)
        return self.shots.clear_rgba(bgra)

    def is_the_still(self, frame, closed: bytes, still: Path) -> bool:
        """Whether the popup at `frame` - open, and arrived - is, pixel for pixel, the first frame of the committed `still`:
        the popup the README's other pictures and the guide show, made by make_screenshots.render_popup, which draws its
        light at the first moment of its breath: so here too, whatever moment the frame is at. What the picture's popup
        draws is what the still draws."""
        width, height, rgb, alpha = self.shots.read_png(still)
        picture = self.drawn(frame, closed, light_at=0)
        self._held = None
        if (width, height) != tuple(self.size) or alpha is None:
            return False
        rgba = bytearray(width * height * 4)
        rgba[0::4], rgba[1::4], rgba[2::4], rgba[3::4] = rgb[0::3], rgb[1::3], rgb[2::3], alpha
        return bytes(rgba) == picture

    def close(self) -> None:
        if self.renderer is not None:
            self.renderer.close()
            self.renderer = None
