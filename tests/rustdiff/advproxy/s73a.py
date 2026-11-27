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
