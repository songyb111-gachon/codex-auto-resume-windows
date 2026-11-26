"""CODEX_AR_CORE=rust for the advanced edition (seat S7.2a3, owner Q3 (c)): the package `codex_auto_resume_advanced` as it
loads, with each name table.py forwards replaced by car-adv's over a pipe (`advserve`), so `advanced/tests` run
unedited on Rust - S4.2's scenario proxy (tests/rustdiff/engineproxy.py) widened from core's `Engine` to the advanced
edition, module by module.

`tests/rustdiff/shim.py` (the core shim) hands every `codex_auto_resume_advanced.*` module this package's `patch` as it
loads: a module table.py names has its forwarded names replaced, at once, before anything imports from it; every other
module is the reference's own, unchanged, until its seat adds its row. Loaded by path (`rustdiff_advproxy`), stdlib
only at import: the product's modules are imported where used.

    table.py     THE place: every module of the package, its seat, and what of it is forwarded (or why not yet)
    pipe.py      the pipe to advserve, the questions car-adv asks back, the JSON rule
    runtime.py   S7.2a3's forwarders: Runtime (and so AdvancedPlug's runtime), its state and arming, AdvancedState
    ledger.py    every advanced test file: "green on Rust" or "waits for <seat>", and why (python -X utf8 ...)
"""
from __future__ import annotations

import importlib

PACKAGE = "codex_auto_resume_advanced"


def wanted_module(name: str) -> bool:
    return name == PACKAGE or name.startswith(PACKAGE + ".")


def patch(module) -> None:
    """Replace the forwarded names of `module` (table.py), once."""
    from . import table
    dotted = module.__name__[len(PACKAGE) + 1:] if module.__name__ != PACKAGE else ""
    row = table.MODULES.get(dotted)
    if row is None or not row.forwards or getattr(module, "__advproxy__", False):
        return
    for name, target in row.forwards.items():
        where, _, attribute = target.rpartition(".")
        found = getattr(importlib.import_module(__name__ + "." + where), attribute)
        found.__advproxy_reference__ = getattr(module, name, None)
        setattr(module, name, found)
    module.__advproxy__ = True
