"""The pure rules forwarded by proxy2 (owner Q3 (c), completion part 1): module functions of the advanced package whose
answers car-adv decides, reached through advserve's `op` (advprobe's families, compiled into it): `arming.standing`,
`arming.warnings_for`, `registry.offered`, `registry.problems`. Each has the reference's signature; its arguments are
handed as advprobe's diffs hand them (diffs_advpolicy_pure.py), its answer given back its Python shape.

A value car-adv's closed types cannot hold (a definition that is not a CapabilityDef, a row without its fields) is
refused by car-adv as `ValueError` at the pipe; where the reference has an answer for it, that answer is the
reference's own rule for what is not a definition (`problems`'s "not a definition"), named here and nowhere else.
"""
from __future__ import annotations

from .pipe import PIPE, plain


def _op(name, *arguments):
    return PIPE.request(0, "op", op=name, args=[plain(each) for each in arguments])


def _definition(definition):
    from .runtime import _shipped, dump_def
    return dump_def(definition, _shipped(definition.make))


def _table(measured):
    if not isinstance(measured, dict):
        return []          # a table that is no table reads as one that holds nothing (the reference's `.get` finds none)
    return [[str(measurement), str(verdict), evidence] for measurement, (verdict, evidence) in measured.items()]


def _checked(checked):
    return [[str(measurement), str(result)] for measurement, result in (checked or {}).items()]


def _row(row):
    if row is None:
        return None
    found = {name: row.get(name) for name in ("state", "since", "actor", "reason", "statement_revision",
                                               "engine_version", "keep_on", "send_again")}
    found["warnings"] = [str(each) for each in row.get("warnings") or ()]
    # the reference reads both as truth values (`row.get("keep_on")`): a row without them is a row with them off
    found["keep_on"], found["send_again"] = bool(found["keep_on"]), bool(found["send_again"])
    return found


def _policy(policy):
    return {"forbid": policy.forbid, "force_shadow": policy.force_shadow,
            "allowed": None if policy.allowed is None else sorted(policy.allowed)}


def _measured_default():
    from codex_auto_resume_advanced.measured import MEASURED
    return MEASURED


def warnings_for(definition, view, measured=None, *, parts=True, checked=None) -> tuple:
    from codex_auto_resume_advanced.vocabulary import ArmingWarning
    measured = _measured_default() if measured is None else measured
    found = _op("arming.pure.warnings_for", _definition(definition), view, _table(measured), bool(parts),
                _checked(checked))
    return tuple(ArmingWarning(each) for each in found)


def standing(definition, row, policy, view, measured=None, checked=None) -> tuple:
    from codex_auto_resume_advanced.vocabulary import ArmingState, ArmingWarning, OffReason
    measured = _measured_default() if measured is None else measured
    state, change, held, notice = _op("arming.pure.standing", _definition(definition), _row(row), _policy(policy),
                                      view, _table(measured), _checked(checked))
    return (ArmingState(state), None if change is None else OffReason(change),
            None if held is None else ArmingWarning(held), None if notice is None else OffReason(notice))


def offered(measured) -> tuple:
    from codex_auto_resume_advanced import registry
    ids = _op("registry.offered", _table(measured))
    waiting = {definition.id: definition for definition, _ in registry.WAITING}
    return tuple(waiting[each] for each in ids if each in waiting)


def problems(definition) -> list:
    from codex_auto_resume_advanced.registry import CapabilityDef
    if not isinstance(definition, CapabilityDef):
        return ["not a definition"]
    return list(_op("registry.problems", _definition(definition)))
