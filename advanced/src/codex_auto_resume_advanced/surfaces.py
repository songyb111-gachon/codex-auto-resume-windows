# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""P10: what this edition adds to the status, the bridge and MCP.

The edition badge is the first of them, and the only one this version shows: the word the
version-bearing surfaces already carry gains one that says which edition this is
(decision C12). Core asks the plug at the status, the tray snapshot and the diagnostics
bundle, and the standard edition's NULL plug adds nothing there, so those surfaces are
byte-identical to today; this edition adds `edition` and how many capabilities are armed
(`on`, 0 while the registry is empty), in codes only - no version string, no path, no free
text, because the status is part of what Codex sends on. The display word for each locale
lives in this package's own catalogs (`edition.*`); core surfaces keep their own words.

The bridge is the Dashboard's (controlcli.serve, the long-lived form; the one-shot form never
reaches a plug). It is where a person reads a capability's statement and turns it on, watches
it, turns it off, turns everything off, lowers the global ceiling, or runs a measurement by
hand (`measure <id>`, measure.py) - every request made as the Dashboard.

MCP is a model's. It can list the capabilities, turn one off and turn all of them off, and that
is all: turning something off only ever does less, as a Pause does. There is no tool that turns
anything on, and nothing a client sends reaches `Arming.arm` from here - not an unknown tool, not
an argument the schema does not name (advanced/tests/test_advanced_surfaces.py). Turning a
capability on follows the Custom message's precedent: written only in the Dashboard, by the
person it will act for.

What MCP is told is codes and ids, like core's own status there: no version string, no path, no
free text, since a reply is part of what Codex sends on.
"""
from __future__ import annotations

from codex_auto_resume import l10n
from codex_auto_resume.domain.plug import DEFER, Edition, Surface

from .vocabulary import (Actor, ArmingState, BridgeCommand, McpTool, Measurement, NoteCode,
                         Refusal, Verdict)

# The surfaces that show the version, where the edition badge sits beside it (decision C12).
# Core adds nothing there in the standard edition, so each stays as it was; this edition puts
# its badge under core's one "advanced" key, never in place of anything core shows.
BADGE_SURFACES = frozenset({Surface.STATUS, Surface.TRAY, Surface.DIAGNOSTICS})

# The arguments each bridge command takes. Anything else in a request refuses it.
ARGUMENTS = {
    BridgeCommand.ADVANCED_LIST: frozenset(),
    BridgeCommand.ADVANCED_STATEMENT: frozenset({"capability", "locale"}),
    BridgeCommand.ADVANCED_ARM: frozenset({"capability", "state", "revision", "generation",
                                           "engine_version"}),
    BridgeCommand.ADVANCED_DISARM: frozenset({"capability"}),
    BridgeCommand.ADVANCED_DISARM_ALL: frozenset(),
    BridgeCommand.ADVANCED_CEILING: frozenset({"global_hourly", "generation"}),
    BridgeCommand.MEASURE: frozenset({"measurement", "thread"}),
    BridgeCommand.MEASURE_VERDICT: frozenset({"measurement", "verdict", "note"}),
}

_NO_ARGUMENTS = {"type": "object", "properties": {}, "additionalProperties": False}
_OFF_ONLY = ("Turning a capability on is not something any tool does: the user does it in the "
             "Codex Auto Resume Dashboard, after reading what it does.")

TOOLS = [
    {"name": McpTool.LIST_ADVANCED_CAPABILITIES, "title": "List advanced capabilities",
     "description": "The advanced edition's capabilities, each with its id, whether it is on, "
                    "watched or off, since when and why, and the standards it departs from. "
                    "Read-only. " + _OFF_ONLY,
     "inputSchema": _NO_ARGUMENTS,
     "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True,
                     "openWorldHint": False}},
    {"name": McpTool.DISARM_ADVANCED_CAPABILITY, "title": "Turn one advanced capability off",
     "description": "Turn off one advanced capability, by the exact id list_advanced_capabilities "
                    "gives. Only ever reduces automation, so it needs no confirmation. " + _OFF_ONLY,
     "inputSchema": {"type": "object", "additionalProperties": False, "required": ["capability"],
                     "properties": {"capability": {"type": "string", "description":
                                                   "The capability's exact id."}}},
     "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True,
                     "openWorldHint": False}},
    {"name": McpTool.DISARM_ALL_ADVANCED, "title": "Turn all advanced features off",
     "description": "Turn off every advanced capability at once. Only ever reduces automation, "
                    "so it needs no confirmation. " + _OFF_ONLY,
     "inputSchema": _NO_ARGUMENTS,
     "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True,
                     "openWorldHint": False}},
]


def answer(runtime, name, facts):
    """What this edition shows on surface `name`, or DEFER."""
    if name in BADGE_SURFACES:
        return badge(runtime)
    if not isinstance(facts, dict):
        return DEFER
    if name == Surface.BRIDGE:
        return bridge(runtime, facts.get("command"), facts.get("argument"))
    if name == Surface.MCP:
        return mcp(runtime, facts)
    return DEFER


# ---------------------------------------------------------------------------- the edition badge
def badge(runtime) -> dict:
    """Which edition this is, and how many capabilities are armed. Codes only.

    `on` is 0 while the registry is empty, and reading it opens nothing then: a home where
    nothing was ever turned on stays a home with no advanced state (state.AdvancedState). The
    word a person reads is this package's own (`edition.*` in the catalogs); this is the token
    core's own status uses for a machine value, so a front end says it in the reader's language.
    """
    try:
        on = sum(state == ArmingState.ARMED for state in runtime.states().values())
    except Exception:
        on = 0
    return {"edition": str(Edition.ADVANCED), "on": on}


# ---------------------------------------------------------------------------- the Dashboard
def bridge(runtime, command, argument):
    if command not in tuple(BridgeCommand) or not isinstance(argument, dict):
        return DEFER
    command = BridgeCommand(command)
    if set(argument) - ARGUMENTS[command]:
        return {"done": False, "refusal": Refusal.INVALID_REQUEST}
    arming = runtime.arming
    if command == BridgeCommand.ADVANCED_LIST:
        return dict(arming.listing(), done=True)
    if command == BridgeCommand.ADVANCED_STATEMENT:
        definition = runtime.registry.get(argument.get("capability"))
        if definition is None:
            return {"done": False, "refusal": Refusal.UNKNOWN_CAPABILITY}
        locale = argument.get("locale")
        locale = l10n.resolve(locale) if isinstance(locale, str) and locale else l10n.current()
        return dict(arming.catalogs.statement(definition, locale), done=True)
    if command == BridgeCommand.ADVANCED_ARM:
        return arming.arm(argument.get("capability"), state=argument.get("state"),
                          revision=argument.get("revision"), generation=argument.get("generation"),
                          acknowledged_version=argument.get("engine_version"), actor=Actor.DASHBOARD)
    if command == BridgeCommand.ADVANCED_DISARM:
        return arming.disarm(argument.get("capability"), actor=Actor.DASHBOARD)
    if command == BridgeCommand.ADVANCED_DISARM_ALL:
        return arming.all_off(actor=Actor.DASHBOARD)
    if command == BridgeCommand.MEASURE:
        return measure(runtime, argument.get("measurement"), argument.get("thread"))
    if command == BridgeCommand.MEASURE_VERDICT:
        return measure_verdict(runtime, argument.get("measurement"), argument.get("verdict"),
                               argument.get("note"))
    return arming.set_global_hourly(argument.get("global_hourly"), generation=argument.get("generation"),
                                    actor=Actor.DASHBOARD)


def measure(runtime, measurement, thread=None):
    """Run one measurement the person named, and hand back what was recorded (measure.py).

    The id has to be one of the M-list, or it is refused as an invalid request; running it opens
    a real one-turn session and writes to the source tree, so it is the person's own action, made
    from the Dashboard, and never a model's - no MCP tool reaches this.

    `thread` is an optional real throwaway conversation the person points it at. It has to be a
    string when given; whether it is a Codex thread id is checked in the harness, which never
    writes it into the record."""
    try:
        which = Measurement(measurement)
    except ValueError:
        return {"done": False, "refusal": Refusal.INVALID_REQUEST}
    if thread is not None and not isinstance(thread, str):
        return {"done": False, "refusal": Refusal.INVALID_REQUEST}
    try:
        summary = runtime.run_measurement(which, thread=thread)
    except Exception:
        return {"done": False, "refusal": Refusal.STATE_UNAVAILABLE}
    return dict(summary, done=True)


def measure_verdict(runtime, measurement, verdict, note):
    """Record a person's completion of a blocked measurement (measure-verdict, measure.py).

    After a probe leaves a verdict blocked, the person does the step in the Codex app and records
    what they saw here: a pass or a fail, and one closed note code. It appends the completion to
    the newest blocked record of that measurement for this Codex version, and is refused when the
    id, the verdict or the note is not one of the closed sets, or when there is no such record.
    The Dashboard's like `measure`, and reached by no MCP tool."""
    try:
        which = Measurement(measurement)
        chosen = Verdict(verdict)
        code = NoteCode(note)
    except ValueError:
        return {"done": False, "refusal": Refusal.INVALID_REQUEST}
    if chosen not in (Verdict.PASS, Verdict.FAIL):
        return {"done": False, "refusal": Refusal.INVALID_REQUEST}
    try:
        summary = runtime.complete_measurement(which, chosen, code)
    except Exception:
        return {"done": False, "refusal": Refusal.STATE_UNAVAILABLE}
    return dict(summary, done=True)


# ---------------------------------------------------------------------------- a model
def mcp(runtime, facts):
    request = facts.get("request")
    if request == "tools":
        return {"tools": TOOLS}
    tool, arguments = facts.get("tool"), facts.get("arguments")
    if request != "call" or tool not in tuple(McpTool) or not isinstance(arguments, dict):
        return DEFER
    declared = next(entry for entry in TOOLS if entry["name"] == tool)
    if set(arguments) - set(declared["inputSchema"]["properties"]):
        return {"refused": "unrecognized tool arguments"}
    arming = runtime.arming
    if tool == McpTool.LIST_ADVANCED_CAPABILITIES:
        listing = arming.listing()
        shown = [{key: item[key] for key in ("id", "state", "since", "by", "reason", "departs_from")}
                 for item in listing["capabilities"]]
        return {"summary": "%d advanced capabilit%s, %d on." % (
                    len(shown), "y" if len(shown) == 1 else "ies", listing["on"]),
                "data": {"capabilities": shown, "on": listing["on"]}}
    if tool == McpTool.DISARM_ADVANCED_CAPABILITY:
        capability = arguments.get("capability")
        result = arming.disarm(capability, actor=Actor.MCP)
        if not result["done"]:
            return {"refused": "no advanced capability has that id"
                    if result["refusal"] == Refusal.UNKNOWN_CAPABILITY
                    else "the advanced state could not be changed"}
        return {"summary": "%s is %s." % (capability, "now off" if result["changed"] else "off"),
                "data": {"capability": capability, "state": ArmingState.OFF, "changed": result["changed"]}}
    result = arming.all_off(actor=Actor.MCP)
    if not result["done"]:
        return {"refused": "the advanced state could not be changed"}
    return {"summary": "All advanced features are off (%d turned off)." % result["count"],
            "data": {"count": result["count"]}}
