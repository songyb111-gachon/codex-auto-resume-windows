"""The picture makers retargeted to the host's render mode are wired right (P6-DESIGN 3.3 B and C; seat S6.3f).

build/motion_{popup,tip,card}.py and build/make_screenshots.py's surface functions draw, with CODEX_AR_SURFACE_RENDER,
through build/surface_render.py's stand-ins, which ask the C# surfaces (gui/SurfaceRenderServe.cs). The pictures
themselves are the main session's (they draw with the picture machine's fonts). This holds what needs no picture:

* the structure: over the committed motion plans' own frames, the popup's and the hover card's makers call the render
  mode's renderer with the same calls and the same arguments, in the same order, as they call the reference's renderer
  - every call recorded and none drawn (the plans are the reference's layout, measured, never painted);
* the card: its maker says to the render mode the motion, the pointer marks, the breaths and the paints the reference's
  Card is given, and every frame the render mode answers is the reference's motion arithmetic for that moment;
* the serving itself (in-box csc): a session lays out the popup as the reference does under the stills' face and
  answers every call; a picture comes back as BGRA of the plan's size; no GDI+ object is left once its objects close.
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "src"), str(ROOT / "build"), str(ROOT / "tests")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import surface_render  # noqa: E402

FRAMES = 60


def frames_of(name: str, key: str):
    import make_motion
    plan = make_motion.load(name)
    frames, _held, _end = make_motion.schedule(plan, make_motion.icon_moments(plan, make_motion.motion_plan.plan_end(plan)))
    return plan, [frame for frame in frames if getattr(frame, key)][:FRAMES]


class Recorder:
    """The two sides' calls in one shape: plans by the order they were laid out, the look with each drawing call."""

    def __init__(self):
        self.calls, self.plans = [], []

    def plan(self, plan):
        for index, known in enumerate(self.plans):
            if known is plan:
                return index
        self.plans.append(plan)
        return len(self.plans) - 1

    def add(self, *call):
        self.calls.append(surface_render.wire(list(call)))


class Spy:
    """The reference's renderer as the picture makers call it, every call recorded: a layout is the reference's own
    (measured, not painted); a drawing call is recorded and not made; a picture is clear bytes of its size."""

    def __init__(self, inner, recorder):
        self.__dict__.update(_inner=inner, _rec=recorder, canvas=self)
        self.__dict__["_size"] = (0, 0)

    def __setattr__(self, name, value):
        setattr(self._inner, name, value)

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def _look(self):
        inner = self._inner
        return [inner.theme, inner.design, bool(inner.contrast), bool(getattr(inner, "lone", False))]

    def layout(self, vm, scale, locale):
        plan = self._inner.layout(vm, scale, locale)
        self._rec.add("layout", self._rec.plan(plan), vm, float(scale), locale, self._look())
        return plan

    def tip_layout(self, parts, light, scale, locale, day=None):
        plan = self._inner.tip_layout(parts, light, scale, locale, day)
        self._rec.add("tip_layout", self._rec.plan(plan), parts, light, float(scale), locale, day, self._look())
        return plan

    def draw(self, vm, plan, *, frame=None, hover=None, pressed=None, focus=None, glides=None, scene_ms=0.0, faces=None):
        self._rec.add("draw", self._rec.plan(plan), frame, hover, pressed, focus,
                      [[target, amount] for target, amount in (glides or {}).items()], float(scene_ms),
                      [[target, fill, edge, amount] for target, ((fill, edge), amount) in (faces or {}).items()],
                      self._look())
        self.__dict__["_size"] = tuple(plan["size"])

    def draw_halo(self, plan, frame, *, restore=True):
        self._rec.add("draw_halo", self._rec.plan(plan), frame, self._look())

    def draw_tip(self, plan, frame=None):
        self._rec.add("draw_tip", self._rec.plan(plan), frame, self._look())
        self.__dict__["_size"] = tuple(plan["size"])

    def draw_tip_light(self, plan, frame, *, restore=True):
        self._rec.add("draw_tip_light", self._rec.plan(plan), frame, self._look())

    def face_colours(self, item, state):
        colours = self._inner.face_colours(item, state)
        self._rec.add("face_colours", state, self._look())
        return colours

    def pixels(self):
        self._rec.add("pixels")
        width, height = self._size
        return bytes(width * height * 4)

    def card_still(self, plan, pad=None):
        self._rec.add("card_still", self._rec.plan(plan), pad, self._look())
        card = plan["card"]
        width, height = card[2] - card[0] + 2 * pad, card[3] - card[1] + 2 * pad
        return width, height, bytes(width * height * 4)


class SpySession:
    """What the makers are handed for the reference's side: its renderer, spied on."""

    def __init__(self, recorder, factory):
        self.recorder, self.factory = recorder, factory

    def renderer(self):
        return Spy(self.factory(), self.recorder)


class FakeSession(surface_render.Session):
    """A render mode that is not started: each call is recorded in the Spy's shape and answered from the reference
    (layouts measured, never painted; pictures clear bytes of their size)."""

    def __init__(self, recorder):
        self.process, self.asked, self.log, self.rec = object(), 0, [], recorder
        self.objects, self.looks, self.sizes = {}, {}, {}

    def call(self, name, **args):
        from codex_auto_resume.ui import popup
        from codex_auto_resume.ui.tray import tipcard
        args = surface_render.wire(args)
        self.asked += 1
        look = [args.get("theme"), args.get("design"), args.get("contrast"), args.get("lone")]
        if name == "open_renderer":
            self.objects[self.asked] = None
            return {"renderer": self.asked}
        if name in ("layout", "tip_layout"):
            inner = self.objects[args["renderer"]]
            if inner is None:
                inner = self.objects[args["renderer"]] = popup.Renderer() if name == "layout" else tipcard.TipRenderer()
            inner.theme, inner.design, inner.contrast = args["theme"], args["design"], args["contrast"]
            if name == "layout":
                inner.lone = args["lone"]
                plan = inner.layout(args["vm"], args["scale"], args["locale"])
                self.rec.add("layout", self.rec.plan(plan), args["vm"], args["scale"], args["locale"], look)
            else:
                plan = inner.tip_layout(args["parts"], args["light"], args["scale"], args["locale"], args["day"])
                self.rec.add("tip_layout", self.rec.plan(plan), args["parts"], args["light"], args["scale"], args["locale"],
                             args["day"], look)
            self.objects[self.asked] = plan
            return {"plan": self.asked, "dump": surface_render.wire(plan)}
        plan = self.objects.get(args.get("plan"))
        if name == "draw":
            self.rec.add("draw", self.rec.plan(plan), args["frame"], args["hover"], args["pressed"], args["focus"],
                         args["glides"], args["scene_ms"], args["faces"], look)
            self.sizes[args["renderer"]] = tuple(plan["size"])
            return None
        if name in ("draw_halo", "draw_tip", "draw_tip_light"):
            self.rec.add(name, self.rec.plan(plan), args["frame"], look)
            if name == "draw_tip":
                self.sizes[args["renderer"]] = tuple(plan["size"])
            return {"rows": None}
        if name == "face_colours":
            self.rec.add("face_colours", args["state"], look)
            fill, edge = self.objects[args["renderer"]].face_colours(plan["items"][args["index"]], args["state"])
            return [list(fill), list(edge)]
        if name == "pixels":
            self.rec.add("pixels")
            width, height = self.sizes.get(args["renderer"], (0, 0))
            return {"data": bytes(width * height * 4)}
        if name == "card_still":
            self.rec.add("card_still", self.rec.plan(plan), args["pad"], look)
            card = plan["card"]
            width, height = card[2] - card[0] + 2 * args["pad"], card[3] - card[1] + 2 * args["pad"]
            return {"data": bytes(width * height * 4), "width": width, "height": height}
        if name == "close":
            return None
        raise AssertionError("an unexpected call: %s" % name)

    def picture(self, answer):
        return answer["data"]

    def close(self):
        self.process = None


class RetargetStructureTests(unittest.TestCase):
    def _pair(self, make, drive, factory):
        """The calls one maker makes of the reference's renderer and of the render mode's, over the same frames."""
        import make_screenshots
        reference, render = Recorder(), Recorder()
        with make_screenshots.pinned_face():
            maker = make(SpySession(reference, factory))
            try:
                drive(maker)
            finally:
                maker.close()
            session = FakeSession(render)
            maker = make(session)
            try:
                drive(maker)
            finally:
                maker.close()
        return reference.calls, render.calls

    def assertSameCalls(self, reference, render):
        self.assertGreater(len(reference), 10)
        for index, (one, other) in enumerate(zip(reference, render)):
            self.assertEqual(one, other, "call %d differs" % index)
        self.assertEqual(len(reference), len(render))

    def test_the_popups_maker_calls_the_render_mode_as_it_calls_the_reference(self):
        import motion_popup
        plan, frames = frames_of("popup-en", "popup")
        popup_plan = plan["popup"]

        def make(render):
            return motion_popup.PopupFrames(popup_plan.get("locale", plan["locale"]), scale=popup_plan["scale"],
                                            theme=plan["canvas"].get("theme", "light"), render=render)

        def drive(maker):
            closed = bytes(maker.size[0] * maker.size[1] * 4)
            button = next(item for item in maker.view()[1]["items"] if item["kind"] == "button")["rect"]
            pointer = ((button[0] + button[2]) // 2 + maker.shift[0], (button[1] + button[3]) // 2 + maker.shift[1])
            for index, frame in enumerate(frames):
                maker.drawn(frame, closed, pointer=pointer if 10 <= index < 20 else None)
            maker.drawn(frames[-1], closed, light_at=0)
        from codex_auto_resume.ui import popup as tray_popup
        reference, render = self._pair(make, drive, tray_popup.Renderer)
        self.assertIn("card_still", {call[0] for call in reference})
        self.assertSameCalls(reference, render)

    def test_the_hover_cards_maker_calls_the_render_mode_as_it_calls_the_reference(self):
        import motion_tip
        for name in ("popup-en", "readme-ko"):
            plan, frames = frames_of(name, "tip")
            if not frames:
                continue
            tip_plan = plan["tip"]

            def make(render):
                return motion_tip.TipFrames(tip_plan.get("locale", plan["locale"]), scale=tip_plan["scale"],
                                            work=(0, 0, 1920, 1032), monitor=(0, 0, 1920, 1080), box=(1800, 1040, 1824, 1064),
                                            render=render)

            def drive(maker):
                for frame in frames:
                    maker.drawn(frame)
            from codex_auto_resume.ui.tray import tipcard
            reference, render = self._pair(make, drive, tipcard.TipRenderer)
            self.assertIn("draw_tip_light", {call[0] for call in reference})
            self.assertSameCalls(reference, render)
            return
        self.fail("no committed plan shows the hover card")

    def test_the_cards_maker_tells_the_render_mode_what_the_reference_card_is_told(self):
        """The card's maker, retargeted, says to the render mode each picture's motion (born, hold, place, leave), the
        pointer marks with the breath a redraw draws at, each breath and each paint, in order - the reference's own
        rules for when the card draws its face again and when only its light (motion_card.CardFrames._drawn)."""
        import motion_card
        from codex_auto_resume import notice_card

        class CardSession(FakeSession):
            def call(self, name, **args):
                args = surface_render.wire(args)
                self.log.append([name, {key: value for key, value in args.items() if key != "card"}])
                if name == "open_card":
                    return {"card": 1, "size": [400, 120], "margin": 20, "vm": {"actions": [
                        {"uri": "codex-auto-resume:open?page=pending", "target": ["action", 0]}]},
                            "plan": {"targets": [[["action", 0], [300, 80, 380, 110]]], "items": []}}
                if name == "card_paint":
                    motion = self.motion
                    frame = motion.frame(args["ms"])
                    return {"frame": frame._asdict(), "x": 0, "y": 0, "margin": 20, "key": "0,0,1,1,5",
                            "gone": motion.gone}
                if name == "card_motion":
                    self.motion = notice_card.CardMotion(args["born"], hold_ms=args["hold"])
                    self.motion.move_to(args["born"], tuple(args["place"]))
                    if args["leave"] is not None:
                        self.motion.retire(args["leave"])
                    return None
                if name == "card_light":
                    return {"rows": [10, 20], "band": {"data": bytes(400 * 10 * 4)}}
                if name == "card_layers":
                    return {"body": {"data": bytes(4)}, "shadow": {"data": bytes(4)}}
                return None

        session = CardSession(Recorder())
        maker = motion_card.CardFrames("en", scale=1.5, work=(0, 0, 1920, 1032), monitor=(0, 0, 1920, 1080),
                                       anchor=(1800, 1040, 1824, 1064), render=session)
        try:
            steps = [(0, 0, None, None, None), (100, 0, None, None, None), (700, 0, None, None, None),
                     (900, 0, "open", None, None), (950, 0, "open", "open", None), (1400, 0, None, None, None),
                     (2000, 0, None, None, 1800), (2400, 0, None, None, 1800)]
            for t, born, hover, pressed, leave in steps:
                maker.drawn(t, born, hover=hover, pressed=pressed, leave=leave)
        finally:
            maker.close()
        names = [call[0] for call in session.log]
        self.assertEqual(names[:2], ["open_card", "card_set"])          # made, then placed on the stack's edge
        motions = [call[1] for call in session.log if call[0] == "card_motion"]
        self.assertEqual([[one["born"], one["hold"], one["leave"]] for one in motions],
                         [[0.0, motion_card.FOREVER_MS, leave] for _t, _b, _h, _p, leave in steps])
        self.assertTrue(all(one["place"] == list(maker.place) for one in motions))
        redraws = [index for index, name in enumerate(names) if name == "card_redraw"]
        self.assertEqual(len(redraws), 3)                               # onto the button, pressed, off it again
        marks = [session.log[index - 1][1] for index in redraws]
        self.assertEqual([[mark["hover"], mark["pressed"]] for mark in marks],
                         [[["action", 0], None], [["action", 0], ["action", 0]], [None, None]])
        self.assertEqual(names.count("card_paint"), len(steps))
        self.assertIn("card_light", names)
        self.assertEqual(names[-1], "close")


@unittest.skipUnless(surface_render.CSC.is_file(), "needs the in-box C# compiler")
class ServeTests(unittest.TestCase):
    def test_a_session_lays_out_draws_and_answers_every_call_and_leaves_no_object(self):
        import make_screenshots
        from codex_auto_resume.ui import popup as tray_popup
        session = surface_render.session()
        try:
            strings, view = make_screenshots.popup_view("en")
            locale = tray_popup.locale_of(strings)
            renderer = session.renderer()
            renderer.theme, renderer.design, renderer.lone = "light", "soft", True
            plan = renderer.layout(view, 2.0, locale)
            reference = tray_popup.Renderer()
            try:
                reference.theme, reference.design, reference.lone = "light", "soft", True
                with make_screenshots.pinned_face():
                    expected = reference.layout(view, 2.0, locale)
                item = next(item for item in expected["items"] if item["kind"] == "button")
                colours = reference.face_colours(item, "hover")
            finally:
                reference.close()
            self.assertEqual(surface_render.wire(dict(plan)), surface_render.wire(expected))
            renderer.draw(view, plan, frame=tray_popup.halo(view["light"], 0, 0, design="soft"))
            self.assertEqual(len(renderer.canvas.pixels()), plan["size"][0] * plan["size"][1] * 4)
            renderer.draw_halo(plan, tray_popup.halo(view["light"], 900, 900, design="soft"))
            self.assertIsNotNone(renderer.halo_rows)
            pad = tray_popup.layers.still_pad(2.0)
            width, height, still = renderer.card_still(plan, pad)
            self.assertEqual(len(still), width * height * 4)
            item = next(item for item in plan["items"] if item["kind"] == "button")
            self.assertEqual(renderer.face_colours(item, "hover"), tuple(tuple(one) for one in colours))
            renderer.close()
            card = session.card(make_screenshots.card_notice("en"), now_ms=0,
                                where={"dpi": 144, "work": (0, 0, 0, 0)},
                                drawn={"theme": "light", "design": "soft", "contrast": False, "reduced": False},
                                hold=make_screenshots._NoStack().hold())
            painted = card.paint(400)
            self.assertEqual(len(card.body.pixels()), card.size[0] * card.size[1] * 4)
            self.assertEqual(painted["margin"], card.margin)
            top, bottom, band = card.light_band(1700)
            self.assertEqual(len(band), (bottom - top) * card.size[0] * 4)
            card.close()
            self.assertEqual(session.call("objects"), 0)
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
