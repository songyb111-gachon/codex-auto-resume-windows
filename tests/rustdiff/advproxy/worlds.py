"""The worlds of the shipped codes (owner Q3 (c), completion part 1): what car-adv's own code of a shipped capability
asks of the outside world, answered with the reference's own function for it at the time of the ask (advserve
`worlds.rs` asks `{"ask": "world", "capability", "seam", "args"}`).

A test reaches a shipped code with `runtime._code_of(definition)`: on Rust that is a `RustCode` - the code car-adv made
stands behind it, and what the test sets on it (`code._stop = ...`, `code._home = root`) is what the seams below read,
as the reference's own code reads its `self._stop or ipc.stop_turn`. Each seam looks the reference's module up when it
is asked (`usagestop.ipc.stop_turn`, `usage.inuse.home`), so a test's `patch.object` of it is what car-adv meets.

    SEAMS       every seam by its name: the reference's own call for it
    MODULES     the reference's module each capability's seams are looked up in
"""
from __future__ import annotations

import contextlib
import importlib

from .pipe import PIPE, plain

MODULES = {
    "usage_meter": "engine.usage", "usage_wrap_up": "engine.usage", "usage_pause": "engine.usagestop",
    "reset_message": "engine.resetmessage", "reset_credit": "engine.credits",
}


class RustCode:
    """A shipped capability's code, car-adv's: what a test sets on it is kept here for its seams to read; what it
    reads of it (`code._home`) is what it set, else the reference's default (None)."""

    def __init__(self, runtime, capability):
        object.__setattr__(self, "_runtime", runtime)
        object.__setattr__(self, "capability", capability)

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        if name.startswith("_"):
            return None
        raise AttributeError("advproxy: %s of car-adv's %s is not forwarded" % (name, self.capability))


def _module(capability):
    return importlib.import_module("codex_auto_resume_advanced." + MODULES.get(capability, "engine.usage"))


def _set(code, name):
    found = code.__dict__.get(name) if code is not None else None
    return found


def _home(runtime, capability, code):
    found = _set(code, "_home")
    return found if found is not None else _module(capability).inuse.home(runtime.paths)


def _gate(runtime, number):
    """`gate` as the reference hands it to ipc: called, a context manager whose `permitted` is core's guard's answer -
    car-adv's gate entered and left over the pipe, while the seam's ask waits."""
    @contextlib.contextmanager
    def entered():
        permitted = PIPE.request(runtime._session, "gate", gate=number, method="enter")
        try:
            yield permitted
        finally:
            PIPE.request(runtime._session, "gate", gate=number, method="exit")
    return entered


def _turn(name, attribute):
    def seam(runtime, capability, code, thread, other, gate):
        act = _set(code, attribute) or getattr(_module(capability).ipc, name)
        return plain(act(thread, other, gate=_gate(runtime, gate)))
    return seam


def _running(runtime, capability, code, home):
    module = _module(capability)
    return list(module.Turns(home).running(booted=module.booted_of(runtime.paths)))


def _latest(runtime, capability, code, home, thread):
    found = _module(capability).Turns(home).latest(thread)
    return None if found is None else {"status": found.status, "ordinal": found.ordinal, "turn_id": found.turn_id}


def _between(runtime, capability, code, home, thread, after, before):
    return _module(capability).Turns(home).between(thread, after, before)


def _source(runtime, capability, code, home):
    from codex_auto_resume.codex import LocalSource
    LocalSource(home)


def _source_latest(runtime, capability, code, home, thread, widened):
    from codex_auto_resume.codex import LocalSource
    from codex_auto_resume.domain.plughands import Widening
    source = LocalSource(home)
    source.widened = frozenset({Widening.EVERY_DESKTOP}) if widened else frozenset()
    return plain(source.latest(thread))


def _locale(runtime, capability, code):
    from codex_auto_resume import continuation, settings
    return continuation.resolve_locale(settings.load(runtime.paths.settings_file))


def _keep(runtime, found):
    objects = runtime.__dict__.setdefault("_world_objects", {})
    number = len(objects) + 1
    objects[number] = found
    return {"object": number}


def _backend(runtime, capability, code):
    return _keep(runtime, _module(capability).inuse.backend(runtime.paths))


def _session_error(error):
    from codex_auto_resume.domain.errors import AdapterError
    from codex_auto_resume_advanced.codex.protocol import SessionRefused
    if isinstance(error, SessionRefused):
        return {"__session_error__": "SessionRefused"}
    if isinstance(error, AdapterError):
        if type(error).__name__ == "RefusedByCodex":
            return {"__session_error__": "RefusedByCodex", "method": getattr(error, "method", None),
                    "number": getattr(error, "code", None)}
        return {"__session_error__": "AdapterError", "code": str(error.args[0]) if error.args else "adapter"}
    raise error


def _open(runtime, capability, code, named):
    module = _module(capability)
    from codex_auto_resume_advanced.codex import protocol
    try:
        return _keep(runtime, getattr(module, "Session", protocol.Session)(module.inuse.backend(runtime.paths),
                                                                             capability=named))
    except Exception as error:   # noqa: BLE001 - said as the session's own raise, or re-raised
        return _session_error(error)


def _object(runtime, capability, code, number, method, arguments):
    found = runtime.__dict__.get("_world_objects", {})[number]
    if method in ("codex_exe", "served_elsewhere", "app_look"):
        return plain(getattr(found, method, None))
    try:
        if method == "__exit__":
            return found.__exit__(None, None, None)
        if method in ("submit", "receive"):
            method_name, *rest = arguments
            rest = [each for each in rest]
            if method == "submit":
                return found.submit(method_name, rest[0])
            return plain(found.receive(method_name, rest[0], rest[1]))
        return plain(getattr(found, method)(*arguments))
    except Exception as error:   # noqa: BLE001
        if method in ("app_identity", "compatible"):
            raise
        return _session_error(error)


def _key(runtime, capability, code):
    import uuid
    return str(uuid.uuid4())


def _switched(runtime, capability, code):
    from codex_auto_resume_advanced.engine import usage
    return usage._switched_at(runtime.paths)


SEAMS = {"home": lambda runtime, capability, code: _home(runtime, capability, code),
         "stop_turn": _turn("stop_turn", "_stop"), "start_turn": _turn("start_turn", "_start"),
         "running": _running, "latest": _latest, "between": _between, "source": _source,
         "source_latest": _source_latest, "locale": _locale, "backend": _backend, "open": _open,
         "object": _object, "key": _key, "switched": _switched}


def answer(runtime, line):
    capability = line["capability"]
    code = runtime._code.get(capability)
    return SEAMS[line["seam"]](runtime, capability, code, *(line.get("args") or []))
