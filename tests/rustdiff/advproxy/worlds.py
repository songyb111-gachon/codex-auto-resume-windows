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
    "empty_response": "engine.emptyreply", "subagent_parent": "engine.subagent", "goal_continuation": "engine.goal",
    "prompt_queue": "engine.promptqueue",
}

# The reference's class of each code whose own methods a seam calls on a shadow of the code (`_Shadow`).
CLASSES = {"goal_continuation": "GoalContinuation", "empty_response": "EmptyResponse",
           "subagent_parent": "SubagentParent", "prompt_queue": "PromptQueue"}


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
        if name in self.METHODS.get(self.capability, ()):
            return lambda *arguments: self._runtime._call("code_call", self.capability, name, list(arguments))
        raise AttributeError("advproxy: %s of car-adv's %s is not forwarded" % (name, self.capability))

    # The code's own methods a surface or a test calls, car-adv's (advserve `code_call`).
    METHODS = {"usage_pause": ("notices", "holding")}


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



# ---------------------------------------------------------------- the continuation family (completion part 2, step 2)

class _Shadow:
    """The reference's code as a seam calls its own method on: `paths` the runtime's, every attribute the test set on
    the RustCode, the reference's default (None, or the class's own) for the rest."""

    def __init__(self, runtime, code):
        self.paths = runtime.paths
        self.__dict__.update({name: value for name, value in (code.__dict__ if code is not None else {}).items()
                              if not name.startswith("_runtime") and name != "capability"})

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return None


def _class(capability):
    return getattr(_module(capability), CLASSES[capability])


def _codex_home(runtime, capability, code):
    found = _set(code, "_home")
    return found if found is not None else _module(capability).inuse.home(runtime.paths)


def _session(runtime, capability, code, named):
    """The code's own `_session()`: the test's patched one, its `_open`, or a Session over `inuse.backend`."""
    from codex_auto_resume_advanced.codex import inuse, protocol
    try:
        if capability == "goal_continuation":
            made = _class(capability)._session(_Shadow(runtime, code))
        else:
            opened = _set(code, "_session") or _set(code, "_open")
            made = opened() if opened is not None else protocol.Session(inuse.backend(runtime.paths),
                                                                         capability=named)
        return _keep(runtime, made)
    except Exception as error:   # noqa: BLE001 - said as the session's own raise, or re-raised
        return _session_error(error)


def _plain_turn(turn):
    if turn is None:
        return None
    return {"turn_id": turn.turn_id, "status": turn.status, "errored": turn.errored, "completed_at": turn.completed_at,
            "final_agent": turn.final_agent, "ordinal": turn.ordinal, "kinds": dict(turn.kinds),
            "started_at": getattr(turn, "started_at", None)}


def _look(runtime, capability, code, method, *args):
    """The reference's reads of the code's Codex home, each through the code's own module (a test's patch of
    `module.Turns` is what is met)."""
    module = _module(capability)
    home = _codex_home(runtime, capability, code)
    if method == "recent":
        return plain(list(module.Turns(home).recent(args[0])))
    if method == "latest":
        return _plain_turn(module.Turns(home).latest(args[0]))
    if method == "between":
        return module.Turns(home).between(*args)
    if method == "plan_statuses":
        found = module.Turns(home).plan_statuses(args[0])
        return None if found is None else list(found)
    if method == "goal":
        goals = getattr(module, "Goals", None) or importlib.import_module(
            "codex_auto_resume_advanced.codex.goals").Goals
        found = goals(home).read(args[0])
        return None if found is None else plain(getattr(found, "status", found))
    if method == "own":
        from codex_auto_resume.codex import LocalSource
        from codex_auto_resume.domain.plughands import Widening
        source = LocalSource(home)
        source.widened = frozenset({Widening.EVERY_DESKTOP}) if args[1] else frozenset()
        return source.latest(args[0]) is not None
    if method == "children":
        lineage = getattr(module, "Lineage", None) or importlib.import_module(
            "codex_auto_resume_advanced.codex.lineage").Lineage
        return [{"thread_id": child.thread_id, "turn_id": plain(child.turn_id), "status": plain(child.status),
                 "category": plain(child.category)} for child in lineage(home).children(args[0])]
    raise AttributeError("advproxy: look %s is not forwarded" % method)


def _goal_read(runtime, capability, code, thread):
    found = _class(capability)._goal(_Shadow(runtime, code), thread)
    return None if found is None else {"goal_id": plain(found.goal_id), "status": plain(found.status)}


def _m2b(runtime, capability, code):
    return bool(_class(capability)._m2b(_Shadow(runtime, code)))


def _clock(runtime, capability, code):
    import time
    found = _set(code, "clock")
    return (found or time.time)()


def _turn_in_progress(runtime, capability, code, thread):
    return _module(capability).turn_in_progress(runtime.paths, thread)


SEAMS.update({"session": _session, "look": _look, "goal_read": _goal_read, "m2b": _m2b, "clock": _clock,
              "turn_in_progress": _turn_in_progress})

def answer(runtime, line):
    import os
    capability = line["capability"]
    code = runtime._code.get(capability)
    try:
        found = SEAMS[line["seam"]](runtime, capability, code, *(line.get("args") or []))
    except BaseException as error:
        if os.environ.get("CODEX_AR_ENGINEPROXY_TRACE"):
            import sys
            sys.stderr.write("WORLD %s %s %s raised %r\n" % (capability, line["seam"], line.get("args"), error))
        raise
    if os.environ.get("CODEX_AR_ENGINEPROXY_TRACE"):
        import sys
        sys.stderr.write("WORLD %s %s %s -> %s\n" % (capability, line["seam"], str(line.get("args"))[:120],
                                                     str(found)[:160]))
    # what crosses the pipe is JSON: a Path a test set (`code._home = h.home.root`) as its text, as every answer
    return plain(found)
