"""The icon's tooltip card as tests/test_tray_tipcard.py CardStateTests drives it, answered by the C# host's TipCard (S6.4d,
P6-DESIGN 3.4 "window").

`HostTip` stands where the test made `tipcard.TipCard(content=...)` and set its window, `visible`, `_moves`, `_fade`,
`_plan`, `_screen` and `_origin`. Each assignment and each call it makes - `hide(at_once)`, `_wndproc(hwnd, message, wparam,
lparam)` - is a step of one history, run from the start on a fresh TipCard of the host's (HostProbe.cs `tip_steps`, its
window a message-only window of the probe's, never shown) for every question, so what the test reads (`visible`, `_fade`)
is the host's state after its own handling of every step so far. What the host's card asks while it handles a step is the
test's answer at that moment: whether it fades (the test's `_moves()`), where the pointer is (the test's patched
`tipcard.tip_pointer()`) and what the clock says (its patched `tipcard.time.monotonic()`).
"""
from __future__ import annotations

import surfacehost


def _fade(value):
    return None if value is None else (value, None, None)


class HostTip:
    def __init__(self, module, **unused):
        self.__dict__.update(module=module, history=[], hwnd=None, visible=False, _fade=None, last=None,
                             _moves=lambda: True)

    def __setattr__(self, name, value):
        if name == "visible":
            self.history.append(["visible", bool(value)])
        elif name == "_fade":
            if value is not None:
                raise AssertionError("a test set a fade the host's card cannot be given: %r" % (value,))
            self.history.append(["fade", None])
        elif name == "_plan":
            self.history.append(["plan", float(value["scale"]), list(value["size"])])
        elif name == "_screen":
            self.history.append(["screen", list(value["box"])])
        elif name == "_origin":
            self.history.append(["origin", list(value)])
        self.__dict__[name] = value
        if name in ("visible", "_fade"):
            self._run()

    def hide(self, at_once=True):
        self.history.append(["hide", bool(at_once), bool(self._moves())])
        self._run()

    def _wndproc(self, hwnd, message, wparam, lparam):
        pointer = self.module.tip_pointer()
        self.history.append(["message", int(message), int(wparam), int(lparam), bool(self._moves()),
                             None if pointer is None else list(pointer), float(self.module.time.monotonic())])
        self._run()
        return 0

    def _run(self):
        found = surfacehost.SERVE.ask("tip_steps", steps=self.history)
        last = found["steps"][-1]
        self.__dict__["visible"] = last["visible"]
        self.__dict__["_fade"] = _fade(last["fade"])
        self.__dict__["last"] = found
