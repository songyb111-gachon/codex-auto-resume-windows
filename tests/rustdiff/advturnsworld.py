"""The fakes of the `advturns` traces (seat S7.2e1), the reference's half: `REFERENCE_WORLD` is put before
`advturns.REFERENCE` and defines `World` - how each capability of the scenario is made (the tag's own class, with the
scenario's fakes where the class takes them) and the steps that move a fake. `examples/advturns/world.rs` is the Rust
half, the same rules. Every fake notes each call it is asked in `asked`, in order, as `[fake, call, ...]`.
"""
from __future__ import annotations

REFERENCE_WORLD = r'''
import importlib


class World:
    """The scenario's fakes, by capability."""

    MODULES = {
        "silent_continuation": "silent", "every_conversation": "everyconversation", "parallel_dispatch": "parallel",
        "other_sessions": "sessions", "once_more_when_unsure": "oncemore",
    }

    def __init__(self, seams, asked, clock):
        self.seams, self.asked, self.clock = seams, asked, clock

    def note(self, *entry):
        self.asked.append(list(entry))

    def maker(self, capability):
        def make(paths):
            module = importlib.import_module("codex_auto_resume_advanced.engine." + self.MODULES[capability])
            builder = getattr(self, "make_" + capability, None)
            return builder(module, paths) if builder is not None else module.make(paths)
        return make

    def step(self, op, args, runtime):
        if op == "flag":
            from codex_auto_resume_advanced.codex import headless
            if args[0] == "empty_refused":
                headless.EMPTY_REFUSED = bool(args[1])
            return None
        raise SystemExit("unknown op %s" % op)
'''
