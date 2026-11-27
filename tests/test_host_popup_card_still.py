"""The popup's shadow window and its shadow rule on the C# host (S6.4d4, P6-DESIGN 3.4 "window").

Twins of tests/test_popup_card_still.py's ShadowLayerTests and RecipeTests:

* ShadowLayerTests: the originals' bodies through `super()`, with the popup's renderer and its shadow window's picture the
  host's - gui/SurfaceRenderer.cs drawing the card alone and gui/SurfaceLayers.cs's CardLayers shading it, with no window
  (HostProbe.cs `card_shade`). The test's renderer and layer are stand-ins that keep its calls as one history of steps
  (draw, shade, drop), replayed from the start on one host renderer and one CardLayers for every question the test asks of
  them: the canvas, the card, the picture and its margin, the images kept, and the GDI+ objects alive (the patched
  `gdiplus.gdiplus_objects`). The host lets its images go in CardLayers.Dispose, its one release of them, where the
  reference has `_drop_images`.
* RecipeTests: the popup's `float_shadows` and `float_reach` are the host's (SurfaceLayers.FloatShadows and FloatReach,
  `float_recipe`), held equal to the reference's notification card - the rule and the port in one assertion.

Not here, and why: AloneTests (6) and StillTests (5) hand the plan to the drawing and to `card_still` - the render serve's
`draw`, `pixels` and `card_still` calls, seat S6.4f's plan proxy.

Nothing is shown: the probe runs with CREATE_NO_WINDOW and makes no window (CardLayers is given no shadow window).
"""
from __future__ import annotations

import base64
import os
from pathlib import Path
import sys
import unittest
import unittest.mock

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "tests"), str(ROOT / "tests" / "rustdiff")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import surfacehost  # noqa: E402
import test_popup_card_still as original  # noqa: E402  (a module name: its classes are not collected here)

ON_HOST = unittest.skipUnless(os.name == "nt" and surfacehost.CSC.is_file(), "the host's surfaces need the in-box C# compiler")


def _plain(value):
    """A view as JSON carries it (tuples as lists)."""
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _replay(steps, canvas=False, picture=False):
    return surfacehost.SERVE.ask("card_shade", steps=steps, canvas=canvas, picture=picture)


class HostRenderer:
    """The test's popup.Renderer: its look, and each layout a step the host lays out and draws when asked."""

    def __init__(self):
        self.theme, self.design, self.contrast, self.lone = "light", "soft", False, False

    def layout(self, vm, scale, locale):
        step = {"step": "draw", "vm": _plain(vm), "scale": float(scale), "locale": locale, "theme": self.theme,
                "design": self.design, "contrast": bool(self.contrast), "lone": bool(self.lone)}
        return {"card": [int(n) for n in _replay([step])["card"]], "scale": float(scale), "_step": step}

    def draw(self, vm, plan, frame=None):
        """The host draws at the step (with its own light's first frame, as PopupWindow does): nothing more to keep."""
        return None

    def close(self):
        pass


class _Picture:
    def __init__(self, layer):
        self.layer = layer

    @property
    def width(self):
        return int(self.layer.ask(picture=True)["picture_width"])

    def pixels(self):
        return base64.b64decode(self.layer.ask(picture=True)["picture"])

    def close(self):
        pass


class HostLayer:
    """The test's layers.CardLayers(0): every shade and drop a step of one history, replayed per question."""

    current = None

    def __init__(self):
        self.steps = []
        self.picture = _Picture(self)
        self.answers = {}
        HostLayer.current = self

    def ask(self, picture=False):
        """What the host's layer holds after this history (one replay per history and kind of question: the test reads
        the picture's width once a pixel)."""
        key = (len(self.steps), picture)
        if key not in self.answers:
            self.answers[key] = _replay(self.steps, picture=picture)
        return self.answers[key]

    def shade(self, renderer, plan):
        self.steps.append(dict(plan["_step"], step="shade"))

    @property
    def margin(self):
        return int(self.ask()["margin"])

    @property
    def images(self):
        return [None] * int(self.ask()["images"])

    def _drop_images(self):
        self.steps.append({"step": "drop"})


def host_gdiplus_objects():
    """The GDI+ objects the host holds past its run's start, at the end of the current layer's history."""
    layer = HostLayer.current
    return int((layer.ask() if layer is not None else _replay([]))["gdip"])


@ON_HOST
class ShadowLayerOnHostTests(original.ShadowLayerTests):
    def setUp(self):
        from codex_auto_resume.ui.popup import gdiplus
        self.renderer = HostRenderer()
        self.vm = original.view()
        HostLayer.current = None
        patcher = unittest.mock.patch.object(gdiplus, "gdiplus_objects", host_gdiplus_objects)
        patcher.start()
        self.addCleanup(patcher.stop)

    def draw(self, scale=1.5, theme="light", design="soft", contrast=False, lone=True):
        renderer = self.renderer
        renderer.theme, renderer.design, renderer.contrast, renderer.lone = theme, design, contrast, lone
        plan = renderer.layout(self.vm, scale, "en")
        found = _replay([plan["_step"]], canvas=True)
        return plan, int(found["width"]), base64.b64decode(found["canvas"])

    def layer(self):
        return HostLayer()

    def test_nothing_of_the_shadow_lies_under_the_card(self):
        super().test_nothing_of_the_shadow_lies_under_the_card()

    def test_one_image_a_shadow_whatever_sizes_the_card_has_had(self):
        super().test_one_image_a_shadow_whatever_sizes_the_card_has_had()


def host_float_shadows(theme, design="soft"):
    """The host's shadows in the reference popup's container (layers.FloatShadow: a tuple read by name)."""
    from codex_auto_resume.ui.popup import layers
    return tuple(layers.FloatShadow(*shadow) for shadow in surfacehost.SERVE.ask("float_recipe", op="shadows", theme=theme, design=design))


def host_float_reach(shadows, scale):
    return int(surfacehost.SERVE.ask("float_recipe", op="reach", shadows=[list(shadow) for shadow in shadows],
                                     scale=float(scale)))


@ON_HOST
class RecipeOnHostTests(original.RecipeTests):
    def setUp(self):
        super().setUp()
        for name, value in (("float_shadows", host_float_shadows), ("float_reach", host_float_reach)):
            patcher = unittest.mock.patch.object(original.tray_popup, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_the_popup_floats_the_notification_card_s_shadows(self):
        super().test_the_popup_floats_the_notification_card_s_shadows()


if __name__ == "__main__":
    unittest.main()
