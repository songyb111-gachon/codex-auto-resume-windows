# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""P10: what this edition adds to the bridge and to MCP.

The bridge is the Dashboard's (controlcli.serve, the long-lived form; the one-shot form never
reaches a plug). It is where a person reads a capability's statement and turns it on, watches
it, turns it off, turns everything off, or lowers the global ceiling - every request made as
the Dashboard.

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
from codex_auto_resume.domain.plug import DEFER, Surface

from .vocabulary import Actor, ArmingState, BridgeCommand, McpTool, Refusal

# The arguments each bridge command takes. Anything else in a request refuses it.
ARGUMENTS = {
    BridgeCommand.ADVANCED_LIST: frozenset(),
    BridgeCommand.ADVANCED_STATEMENT: frozenset({"capability", "locale"}),
    BridgeCommand.ADVANCED_ARM: frozenset({"capability", "state", "revision", "generation",
                                           "engine_version"}),
    BridgeCommand.ADVANCED_DISARM: frozenset({"capability"}),
    BridgeCommand.ADVANCED_DISARM_ALL: frozenset(),
    BridgeCommand.ADVANCED_CEILING: frozenset({"global_hourly", "generation"}),
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
    if not isinstance(facts, dict):
        return DEFER
    if name == Surface.BRIDGE:
        return bridge(runtime, facts.get("command"), facts.get("argument"))
    if name == Surface.MCP:
        return mcp(runtime, facts)
    return DEFER


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
    return arming.set_global_hourly(argument.get("global_hourly"), generation=argument.get("generation"),
                                    actor=Actor.DASHBOARD)


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
