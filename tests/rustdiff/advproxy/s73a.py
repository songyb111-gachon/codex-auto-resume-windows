"""The forwarders of S7.3a (owner Q3 (c)): `surfaces.answer` and the surface parts the advanced tests call by name, as
car-adv's (`car_adv::surfaces`) over the pipe, for a runtime that is car-adv's (runtime.Runtime, S7.2a3's). A runtime
of any other kind - a test's own stand-in - is handed to the reference's own function (`__advproxy_reference__`), as is
a call that names a store or a source of the test's own (`rows(runtime, store=..., source=...)`): those are Python
objects car-adv cannot read.

What car-adv answers is the reference's shape: a dict (its refusals the vocabulary's words, which compare equal to the
reference's str enums), a list, or DEFER where it passed the request over.
"""
from __future__ import annotations

import sys

from .pipe import PIPE, plain


def _reference(name):
    module = sys.modules["codex_auto_resume_advanced.surfaces"]
    found = getattr(module, name)
    return getattr(found, "__advproxy_reference__", None) or found


def _rust(runtime) -> bool:
    from .runtime import Runtime
    return isinstance(runtime, Runtime)


def _surface(runtime, part, *arguments):
    reply = PIPE.request(runtime._session, "runtime", method="surface", args=[part, *[plain(each) for each in arguments]],
                         kwargs={}, view=None)
    if "defer" in reply:
        from codex_auto_resume.domain.plug import DEFER
        return DEFER
    return reply.get("value")


def answer(runtime, name, facts):
    if not _rust(runtime):
        return _reference("answer")(runtime, name, facts)
    return _surface(runtime, "answer", name, facts)


def bridge(runtime, command, argument):
    if not _rust(runtime):
        return _reference("bridge")(runtime, command, argument)
    return _surface(runtime, "bridge", command, argument)


def mcp(runtime, facts):
    if not _rust(runtime):
        return _reference("mcp")(runtime, facts)
    return _surface(runtime, "mcp", facts)


def rows(runtime, *, store=None, source=None):
    if not _rust(runtime) or store is not None or source is not None:
        return _reference("rows")(runtime, store=store, source=source)
    return _surface(runtime, "rows")


def _view(name):
    def view(runtime):
        if not _rust(runtime):
            return _reference(name)(runtime)
        return _surface(runtime, name)
    view.__name__ = view.__qualname__ = name
    view.__doc__ = "car-adv's `surfaces::%s` for a runtime of car-adv's; the reference's for any other." % name
    return view


badge = _view("badge")
status = _view("status")
meter_view = _view("meter_view")
notice_view = _view("notice_view")
update_view = _view("update_view")
account_view = _view("account_view")
autoswitch_view = _view("autoswitch_view")
diagnostics = _view("diagnostics")
feed_view = _view("feed_view")
fleet_view = _view("fleet_view")
runs = _view("runs")

FORWARDS = {name: "s73a." + name for name in (
    "answer", "bridge", "mcp", "rows", "badge", "status", "meter_view", "notice_view", "update_view", "account_view",
    "autoswitch_view", "diagnostics", "feed_view", "fleet_view", "runs")}


# ------------------------------------------------------------------ the cards' own functions (seat S7.3a2)
# Each card function a test calls by name answers what its bridge command answers (surfaces.bridge hands the command's
# argument to exactly that function), so for a runtime of car-adv's it is asked as that command; a call that hands a
# seam of the test's own (a store, a turn reader, a thread starter, a code ...) or an argument the command would not
# take goes to the reference's own function.
PACKAGE = "codex_auto_resume_advanced."
# What each card reads through another module: a test that patches one of these reaches the reference's card.
READS = {
    "powertasks": ("codex.inuse", "codex.turns", "codex.threads", "engine.powertasks"),
    "analytics": ("codex.tokens", "codex.turns", "engine.analytics"),
    "autoswitch": ("profiles", "codex.authfile", "codex.swap", "codex.inuse", "engine.autoswitch"),
    "conversations": ("codex.inuse", "codex.threads"),
    "keepgoing": (), "resets": (), "prompts": (),
}


class _Card:
    """A card function forwarded: asked as its bridge command for a runtime of car-adv's, unless the call hands a seam
    of the test's own or the test patched a name of the card's module or of a module it reads (a stand-in car-adv
    cannot see) - then the reference's own function answers. What each module held is taken as advproxy patches the
    card's module (its `__advproxy_reference__` set), before any test runs."""

    def __init__(self, module, name, command, build):
        self.module, self.name, self.command, self.build = module, name, command, build
        self.held = None
        self.__name__ = self.__qualname__ = name
        self.__doc__ = "car-adv's answer to `%s` for a runtime of car-adv's; the reference's otherwise." % command

    def __setattr__(self, key, value):
        object.__setattr__(self, key, value)
        if key == "__advproxy_reference__":
            object.__setattr__(self, "held", self._now())

    def _now(self):
        import importlib
        held = {}
        for dotted in ("control." + self.module,) + READS.get(self.module, ()):
            try:
                found = importlib.import_module(PACKAGE + dotted)
            except Exception:
                continue
            held[dotted] = {key: value for key, value in vars(found).items() if not key.startswith("__")}
        return held

    def _patched(self):
        if self.held is None:
            return True
        now = self._now()
        for dotted, names in self.held.items():
            for key, value in now.get(dotted, {}).items():
                if key in names and names[key] is not value and not isinstance(value, _Card):
                    return True
        return False

    def __call__(self, runtime, *args, **kwargs):
        argument = self.build(*args, **kwargs) if _rust(runtime) and not self._patched() else None
        if argument is None:
            return self.__advproxy_reference__(runtime, *args, **kwargs)
        return _surface(runtime, "bridge", self.command, argument)


def _card(module, name, command, build):
    return _Card(module, name, command, build)


def _bare(**seams):
    return all(value is None for value in seams.values())


def _taken(argument, allowed):
    if not isinstance(argument, dict):
        return {}
    return dict(argument) if set(argument) <= set(allowed) else None


powertasks_view = _card("powertasks", "view", "advanced-power-tasks",
                        lambda code=None: {} if code is None else None)
powertasks_arm = _card("powertasks", "arm", "advanced-power-tasks-arm",
                       lambda threads, action, grace_minutes, failed, interrupted, generation, turns=None:
                       {"threads": threads, "action": action, "grace_minutes": grace_minutes, "failed": failed,
                        "interrupted": interrupted, "generation": generation} if turns is None else None)
analytics_view = _card("analytics", "view", "advanced-analytics",
                       lambda days=None: {} if days is None else {"days": days})
analytics_save_csv = _card("analytics", "save_csv", "advanced-analytics-csv",
                           lambda argument: _taken(argument, ("days", "path", "replace")))
accounts_view = _card("autoswitch", "view", "advanced-accounts",
                      lambda store=None, codex_home=None, usage=None, now=None:
                      {} if _bare(store=store, codex_home=codex_home, usage=usage, now=now) else None)
accounts_save = _card("autoswitch", "save", "advanced-accounts-save",
                      lambda store=None, codex_home=None, read_real=None:
                      {} if _bare(store=store, codex_home=codex_home, read_real=read_real) else None)
accounts_delete = _card("autoswitch", "delete", "advanced-accounts-delete",
                        lambda argument, store=None, codex_home=None:
                        _taken(argument, ("id", "all")) if _bare(store=store, codex_home=codex_home) else None)
keepgoing_view = _card("keepgoing", "view", "advanced-keep-going", lambda: {})
conversations_view = _card("conversations", "view", "advanced-conversations", lambda: {})
resets_view = _card("resets", "view", "advanced-resets", lambda: {})
prompts_view = _card("prompts", "view", "advanced-prompts", lambda: {})
