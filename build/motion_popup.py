"""The notification-area popup in a motion picture: its own paint at a pinned moment, offscreen.

The popup is drawn as the product draws it (`ui/popup/renderer.py`), from the same sample rows the still is
(make_screenshots.popup_view), at the stills' scale. What a person sees happen to it is only what the product does:

- It has no entrance. `Popup.show` places the window and calls ShowWindow, and `hide` calls SW_HIDE: it is there at
  once and gone at once, so a plan opens and closes it with a cut (motion_plan's `popup` step).
- Its status light breathes on the clock of the state it shows (`ui.popup.motion.halo`), which starts when the state
  is entered and is not restarted by closing and opening again: the picture's own clock, from its first moment. A
  picture whose length is whole breaths loops without a jump.
- Its countdowns are drawn again every second it is open (TIMER_TICK, 1000 ms): the picture's `ticks` since it was
  opened, one more second of the sample's clock each.
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

    Close it when done: the renderer holds GDI+ objects."""

    def __init__(self, locale: str, *, scale: float, theme: str = "light", design: str | None = None):
        import make_screenshots as shots
        from codex_auto_resume import brand, interface
        from codex_auto_resume.ui import popup as tray_popup
        from codex_auto_resume.ui.popup.motion import glide_amount
        self.shots, self.tray, self.glide_amount = shots, tray_popup, glide_amount
        self.strings = interface.STRINGS[locale]
        self.locale = tray_popup.locale_of(self.strings)
        self.scale = scale
        self.design = design or brand.DEFAULT_DESIGN
        self.renderer = tray_popup.Renderer()
        self.renderer.theme = theme
        self.renderer.design = self.design
        self._views = {}
        self._held = None             # the view whose ground the renderer's canvas holds, or None
        self.size = self.view((), (), 0)[1]["size"]

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
            self._views[key] = (vm, self.renderer.layout(vm, self.scale, self.locale), tasks)
        vm, plan, _tasks = self._views[key]
        return vm, plan

    def drawn(self, frame, closed: bytes) -> bytes:
        """The RGB picture at `frame`: `closed` while no popup is open."""
        if not frame.popup:
            self._held = None
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
        light = self.tray.halo(vm["light"], frame.t, frame.t, design=self.design)
        if gliding:
            canvas = self.renderer.draw(vm, plan, frame=light, glides=gliding)
            self._held = None
        elif self._held == key:
            canvas = self.renderer.draw_halo(plan, light)
        else:
            canvas = self.renderer.draw(vm, plan, frame=light)
            self._held = key
        return self.shots.bgra_rgb(canvas.pixels())

    def is_the_still(self, frame, closed: bytes, still: Path) -> bool:
        """Whether the picture at `frame` is, pixel for pixel, the first frame of the committed `still`: the popup the
        README's other pictures and the guide show, made by make_screenshots.render_popup. The motion's first frame is
        what a viewer that does not animate shows, so it must be that one."""
        width, height, rgb = self.shots.read_png_rgb(still)
        picture = self.drawn(frame, closed)
        self._held = None
        return (width, height) == tuple(self.size) and bytes(rgb) == picture

    def close(self) -> None:
        if self.renderer is not None:
            self.renderer.close()
            self.renderer = None
