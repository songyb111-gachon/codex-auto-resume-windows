"""The icon's hover card in a motion picture: its own paint at a pinned moment, offscreen, as the product shows it.

The card the icon shows when the pointer rests on it (ui/tray/tipcard.py, planned by tipplan.py) is drawn here by its
own renderer (`TipRenderer.tip_layout`, `draw_tip`, `draw_tip_light`), from what the icon's tooltip says (`words.tooltip_parts`)
of the popup's own sample rows (make_screenshots.popup_rows, the same the popup's still is made from): two waiting, the next
check in a minute and a half. What a person sees happen to it is only what the product does:

- It appears when the shell says the pointer rests on the icon (NIN_POPUPOPEN): the delay is Windows' (its mouse-hover
  time, 400 ms by default), not ours - the product has no constant for it, so a plan says it as a hold before the card.
- It fades in over brand's transition on brand's curve (`ui.popup.motion.opening` with no rise: `TipCard._fade_step`), and
  it is placed by the popup's own placement (`tipcard.tip_place`): centred on the icon, `TIP_GAP` from the taskbar and
  inside the work area. It has no shadow of its own: it fills its window.
- It is drawn again each second it is on screen, for the countdown (`TIP_TICK`), and only its light between two of those
  (`draw_tip_light`); the light's cycle starts when the card is made, which is when it first appears.
- A click hides it at once (`Tray._select` -> `_hide_tip()`), before the popup shows: a plan's `tip` frames end where the
  popup opens, and each says when (`until`), so the countdown it shows reads the sample's own 1:35 at its last second and
  the popup that follows begins from the same number.
"""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "src"), str(ROOT / "build")):
    if _path not in sys.path:
        sys.path.insert(0, _path)


class TipFrames:
    """One hover card, for one picture: `drawn(frame)` is the card at the frame's moment, or None while it is not on screen.

    `work` and `monitor` are the canvas's work area and whole screen, (left, top, right, bottom) in its pixels, and `box`
    the icon's rectangle the card stands beside; `scale` its size (2.0 beside a popup pictured at 200 %). `render`, a
    build/surface_render.py session, draws it through the host's render mode instead of the reference's renderer, with
    the same calls. Close it when done: the renderer holds GDI+ objects."""

    def __init__(self, locale: str, *, scale: float, work, monitor, box, theme: str = "light",
                 design: str | None = None, render=None):
        import make_screenshots as shots
        from codex_auto_resume import brand, interface
        from codex_auto_resume.ui import popup as tray_popup
        from codex_auto_resume.ui.tray import tipcard, words
        self.shots, self.tray, self.tipcard, self.words = shots, tray_popup, tipcard, words
        self.strings = interface.STRINGS[locale]
        self.locale = tray_popup.locale_of(self.strings)
        self.scale = scale
        self.design = design or brand.DEFAULT_DESIGN
        self.work, self.monitor, self.box = tuple(work), tuple(monitor), tuple(box)
        self.renderer = render.renderer() if render is not None else tipcard.TipRenderer()
        self.renderer.theme, self.renderer.design, self.renderer.contrast = theme, self.design, False
        self._plans = {}
        self._held = None                     # the reading whose ground the renderer's canvas holds, or None

    def snapshot(self) -> dict:
        """What the icon's tick says of the popup's sample rows: recovery on, how many wait and how many run, and when the
        next check is - model.snapshot_from's own fields, from the rows the popup lists."""
        from codex_auto_resume.ui.popup import model
        rows = self.shots.popup_rows()
        waiting = [row for row in rows if model.is_waiting(row)]
        due = [row["eligible_at"] for row in waiting if row.get("eligible_at") is not None]
        snapshot = {"enabled": True, "waiting": len(waiting), "running": len(rows) - len(waiting)}
        if due:
            snapshot["next_at"] = min(due)
        return snapshot

    def reading(self, shift: int = 0) -> tuple:
        """(the card's plan, its light, where its window goes) with the sample's clock `shift` seconds on from the moment the
        popup's still is drawn at - negative before it."""
        if shift not in self._plans:
            now = self.shots.POPUP_NOW + shift
            snapshot = self.snapshot()
            parts = self.words.tooltip_parts(snapshot, self.strings, now, None)
            light = self.tipcard.tip_light(snapshot, now)
            with self.shots.pinned_face():      # the popup's stills' face (make_screenshots.pinned_face, F1)
                plan = self.renderer.tip_layout(parts, light, self.scale, self.locale)
            where = self.tipcard.tip_place(plan, self.work, self.monitor, self.box)
            self._plans[shift] = (plan, light, where)
        return self._plans[shift]

    def shift_of(self, frame) -> int:
        """How many seconds of the sample's clock the card at `frame` is from the moment the popup opens at: its countdown
        ticks once a second from when it was shown, and reads the sample's own moment at the last tick before the click."""
        state = dict(frame.tip)
        ticks = int((frame.t - state["born"]) // 1000)
        last = int((state["until"] - state["born"]) // 1000) if "until" in state else 0
        return ticks - last

    def alpha(self, frame) -> int:
        """How opaque the card is at `frame`: brand's fade-in, `opening` with nothing to rise (TipCard._fade_step)."""
        from codex_auto_resume.ui.popup.motion import opening
        return opening(frame.t - dict(frame.tip)["born"], 0)[0]

    def drawn(self, frame):
        """(RGBA picture straight alpha, (width, height), (left, top), alpha 0-255) of the card at `frame`; None with no card."""
        if not frame.tip:
            self._held = None
            return None
        shift = self.shift_of(frame)
        plan, light, where = self.reading(shift)
        since = frame.t - dict(frame.tip)["born"]
        halo = self.tray.halo(light, since, since, design=self.design)
        with self.shots.pinned_face():
            if self._held == shift:
                self.renderer.draw_tip_light(plan, halo)
            else:
                self.renderer.draw_tip(plan, halo)
                self._held = shift
        pixels = bytes(self.renderer.canvas.pixels())
        return self.shots.clear_rgba(pixels), tuple(plan["size"]), where, self.alpha(frame)

    def close(self) -> None:
        if self.renderer is not None:
            self.renderer.close()
            self.renderer = None
