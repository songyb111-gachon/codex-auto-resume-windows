"""An MCP server so the product can be managed from inside Codex.

What this is: a typed front end. Every tool here calls the same validated control layer
the command line, the Codex skill and the settings window call, so a value set from a
Codex conversation is the same value the window shows.

What this is deliberately not:

* **Not a second recovery engine.** No tool detects a failure, schedules an attempt,
  reserves an interruption or sends a continuation. The watcher stays the only thing
  that recovers, and it keeps running when this server is not.
* **Not a second scheduler.** The one tool that mentions timing brings a record's next
  attempt forward; it does not decide whether that attempt happens.
* **Not a second database.** Nothing here writes SQL or reads the state file directly.

The safety consequence matters more than the architecture: a model driving these tools
cannot make recovery less careful. It cannot retry an unclassified failure, resolve a
conversation by title, resend an uncertain submission or force a send - not because it
is asked not to, but because no such call exists.

Transport is newline-delimited JSON-RPC on stdin/stdout, which is what MCP's stdio
transport is. Nothing but protocol messages may ever reach stdout: a stray print would
corrupt the stream, so diagnostics go to stderr.
"""
from __future__ import annotations

import json
import sys

from . import settings as policy
from .control import Control, ControlError

PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOLS = (PROTOCOL_VERSION, "2025-03-26", "2024-11-05")
SERVER_NAME = "codex-auto-resume"
SETTINGS_UI = "ui://codex-auto-resume/settings"

# JSON-RPC error codes we actually use.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


def _identifier_schema(title: str) -> dict:
    return {"type": "string", "title": title,
            "description": "The exact interruption id, as listed by list_pending. "
                           "Never a title, a project name, or 'the most recent one'.",
            "pattern": "^[0-9a-fA-F]{64}$"}


# Settings groups a person can change from a front end. Anything else is not offered to
# a model and is refused if a client sends it anyway.
USER_GROUPS = frozenset({"recovery", "limits", "notifications"})


def settings_schema() -> dict:
    """The update_settings input schema, generated from the shared field definitions.

    Generated rather than written out, so the tool cannot drift from the validator: a
    value this schema accepts is a value the validator accepts, and a field added to
    the settings module appears here without being described a second time.
    """
    properties = {}
    for entry in policy.describe():
        name = entry["name"]
        # Only what a person can change in the settings window or the panel. The
        # "advanced" group - which engine binary to run, how far back to look - is
        # deliberately absent from both, and it was present here: a prompt-injected model
        # could point codex_exe somewhere else without any approval prompt. Nothing
        # executes an arbitrary path (the location is confined before anything runs), but
        # recovery silently stopped at the next watcher start.
        if entry.get("group") not in USER_GROUPS:
            continue
        described = {"boolean": {"type": "boolean"},
                     "integer": {"type": "integer"},
                     "number": {"type": "number"},
                     "string": {"type": "string"}}[entry["type"]].copy()
        if "min" in entry:
            described["minimum"] = entry["min"]
        if "max" in entry:
            described["maximum"] = entry["max"]
        if "choices" in entry:
            described["enum"] = list(entry["choices"])
        if name.startswith("recover_"):
            described["description"] = ("Recover interruptions classified as %s. "
                                        "Turning this on can never widen what counts as "
                                        "recoverable; the classifier decides that."
                                        % entry["category"].replace("_", " "))
        described.setdefault("description", "See the settings documentation.")
        properties[name] = described
    return {"type": "object", "properties": properties, "additionalProperties": False}


TOOLS = [
    {
        "name": "open_settings",
        "title": "Open Auto Resume settings",
        "description": "Show the Codex Auto Resume settings panel, with the current "
                       "status and every option. Read-only: opening it changes nothing.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "annotations": {"title": "Open Auto Resume settings", "readOnlyHint": True,
                        "destructiveHint": False, "idempotentHint": True,
                        "openWorldHint": False},
        "_meta": {"openai/outputTemplate": SETTINGS_UI,
                  "openai/toolInvocation/invoking": "Opening Auto Resume settings",
                  "openai/toolInvocation/invoked": "Auto Resume settings"},
    },
    {
        "name": "get_status",
        "title": "Auto Resume status",
        "description": "Whether automatic recovery is on, whether the watcher is "
                       "running, how many recoveries are pending, and the current "
                       "settings. Works with the watcher stopped.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "annotations": {"readOnlyHint": True, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "list_pending",
        "title": "List pending recoveries",
        "description": "Interruptions waiting to be recovered, with their exact "
                       "interruption ids, states and attempt counts.",
        "inputSchema": {"type": "object",
                        "properties": {"include_finished": {
                            "type": "boolean",
                            "description": "Also list recoveries that have already finished."}},
                        "additionalProperties": False},
        "annotations": {"readOnlyHint": True, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "update_settings",
        "title": "Change Auto Resume settings",
        "description": "Change one or more settings. Only the named settings change. "
                       "A value outside the allowed range is refused rather than "
                       "silently adjusted. There is no setting that retries an "
                       "unclassified failure; do not look for one.",
        "inputSchema": settings_schema(),
        # Marked destructive so Codex asks first. A setting can turn recovery up - a
        # category back on, more attempts - and content in a conversation must not be
        # able to do that on the user's behalf without the user seeing it.
        "annotations": {"readOnlyHint": False, "destructiveHint": True,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "restore_default_settings",
        "title": "Restore default settings",
        "description": "Reset every setting to its recommended value. Pending "
                       "recoveries are not affected.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "annotations": {"readOnlyHint": False, "destructiveHint": True,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "pause_auto_recovery",
        "title": "Pause automatic recovery",
        "description": "Global pause. Nothing is sent while paused. Pausing only ever "
                       "reduces automation, so it needs no confirmation.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "annotations": {"readOnlyHint": False, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "resume_auto_recovery",
        "title": "Resume automatic recovery",
        "description": "Undo a global pause. Recovery then continues under every usual "
                       "check. This turns automation back on, so Codex asks the user "
                       "before running it.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        # These were one tool, set_auto_recovery, with no approval either way - so a
        # prompt-injected turn could quietly reverse the user's pause. Pausing and
        # resuming are now separate, and only the direction that adds automation asks.
        "annotations": {"readOnlyHint": False, "destructiveHint": True,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "cancel_recovery",
        "title": "Cancel one recovery",
        "description": "Stop recovering one exact interruption and anything that "
                       "continues it. Identify it by the interruption id from "
                       "list_pending - never by title, project or recency. A continuation "
                       "already in Codex's queue is withdrawn; one already running is not "
                       "stopped. Cancelling only ever reduces automation.",
        "inputSchema": {"type": "object",
                        "properties": {"interruption_id": _identifier_schema("Interruption id")},
                        "required": ["interruption_id"], "additionalProperties": False},
        "annotations": {"readOnlyHint": False, "destructiveHint": True,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "reset_recovery_budget",
        "title": "Give an exhausted recovery its attempts back",
        "description": "For a recovery that stopped because it ran out of attempts or "
                       "kept making no progress. It returns to the ordinary waiting "
                       "state; it does not send anything, and every check runs again.",
        "inputSchema": {"type": "object",
                        "properties": {"interruption_id": _identifier_schema("Interruption id")},
                        "required": ["interruption_id"], "additionalProperties": False},
        # Destructive: it re-arms a recovery that had stopped, so Codex asks first.
        "annotations": {"readOnlyHint": False, "destructiveHint": True,
                        "idempotentHint": False, "openWorldHint": False},
    },
    {
        "name": "start_watcher",
        "title": "Start the background watcher",
        "description": "Start the watcher if it is not running. Nothing is recovered "
                       "while it is stopped, so this is the fix when the status says "
                       "it is not running. It starts the same process the installer "
                       "starts and decides nothing about any interruption.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        # Destructive: a watcher the user stopped would start recovering again.
        "annotations": {"readOnlyHint": False, "destructiveHint": True,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "retry_now",
        "title": "Try a waiting recovery now",
        "description": "Bring a waiting recovery's next attempt forward. This is not a "
                       "send: the watcher still revalidates the interruption, still "
                       "requires the conversation to be open, still waits for usage to "
                       "be available, and still refuses anything uncertain.",
        "inputSchema": {"type": "object",
                        "properties": {"interruption_id": _identifier_schema("Interruption id")},
                        "required": ["interruption_id"], "additionalProperties": False},
        "annotations": {"readOnlyHint": False, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "disable_conversation_recovery",
        "title": "Turn recovery off for one conversation",
        "description": "Stop automatic recovery for one exact conversation, including "
                       "its later interruptions, and cancel what it has waiting. Only "
                       "ever reduces automation.",
        "inputSchema": {"type": "object",
                        "properties": {"thread_id": {"type": "string", "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
                                              "description": "The conversation's exact thread id from list_pending"}},
                        "required": ["thread_id"], "additionalProperties": False},
        "annotations": {"readOnlyHint": False, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "enable_conversation_recovery",
        "title": "Turn recovery back on for one conversation",
        "description": "Let automatic recovery run again for one exact conversation. "
                       "Nothing is sent by this; every check still applies. This turns "
                       "automation back on, so Codex asks the user first.",
        "inputSchema": {"type": "object",
                        "properties": {"thread_id": {"type": "string", "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
                                              "description": "The conversation's exact thread id from list_pending"}},
                        "required": ["thread_id"], "additionalProperties": False},
        "annotations": {"readOnlyHint": False, "destructiveHint": True,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "get_recovery_statistics",
        "title": "Recovery statistics",
        "description": "Counts of interruptions and how their recoveries ended, and "
                       "median waits, over the last N days or all time. Content-free.",
        "inputSchema": {"type": "object",
                        "properties": {"days": {"type": "number", "minimum": 1, "maximum": 3650}},
                        "additionalProperties": False},
        "annotations": {"readOnlyHint": True, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "get_recovery_timeline",
        "title": "Timeline of one recovery",
        "description": "What happened to one exact interruption and everything that "
                       "continued it: detection, waits, the send, the turn it started and "
                       "how that turn ended. Codes and times only.",
        "inputSchema": {"type": "object",
                        "properties": {"interruption_id": _identifier_schema("Interruption id")},
                        "required": ["interruption_id"], "additionalProperties": False},
        "annotations": {"readOnlyHint": True, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "clear_recovery_history",
        "title": "Clear recovery history",
        "description": "Hide finished recoveries from the history. Deletes nothing and "
                       "cancels nothing; a recovery that may still change stays visible, "
                       "and hidden ones still count for every safety check.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "annotations": {"readOnlyHint": False, "destructiveHint": True,
                        "idempotentHint": True, "openWorldHint": False},
    },
]

RESOURCES = [{
    "uri": SETTINGS_UI,
    "name": "Codex Auto Resume settings",
    "description": "The settings panel shown by open_settings.",
    "mimeType": "text/html+skybridge",
}]


class Server:
    """One connection. Synchronous by design: the control layer is not concurrent."""

    def __init__(self, control: Control, stream_in=None, stream_out=None):
        self.control = control
        self.stream_in = stream_in if stream_in is not None else sys.stdin
        self.stream_out = stream_out if stream_out is not None else sys.stdout
        self.initialized = False

    # ------------------------------------------------------------------ transport
    def serve(self) -> int:
        for line in self.stream_in:
            # A UTF-8 BOM ahead of the first message is a Windows fact of life - any
            # tool that wrote the stream with a default text writer put one there - and
            # rejecting it would fail the handshake and nothing else.
            line = line.lstrip("﻿").strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except ValueError:
                self._write(self._error(None, PARSE_ERROR, "invalid JSON"))
                continue
            for response in self._dispatch(message):
                self._write(response)
        return 0

    def _write(self, payload) -> None:
        if payload is None:
            return
        json.dump(payload, self.stream_out, ensure_ascii=False, default=str)
        self.stream_out.write("\n")
        self.stream_out.flush()

    def _dispatch(self, message):
        """A batch is a list; a single message is an object. Notifications get nothing."""
        if isinstance(message, list):
            for item in message:
                yield from self._dispatch(item)
            return
        if not isinstance(message, dict):
            yield self._error(None, INVALID_REQUEST, "message must be an object")
            return
        response = self.handle(message)
        if response is not None:
            yield response

    # ------------------------------------------------------------------- protocol
    @staticmethod
    def _error(request_id, code, message):
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}

    @staticmethod
    def _result(request_id, result):
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def handle(self, message):
        method = message.get("method")
        request_id = message.get("id")
        params = message.get("params") or {}
        if not isinstance(params, dict):
            return self._error(request_id, INVALID_PARAMS, "params must be an object")
        if request_id is None:
            # A notification. Nothing may be written in reply, ever.
            return None
        try:
            if method == "initialize":
                return self._result(request_id, self._initialize(params))
            if method == "ping":
                return self._result(request_id, {})
            if method == "tools/list":
                return self._result(request_id, {"tools": TOOLS})
            if method == "resources/list":
                return self._result(request_id, {"resources": RESOURCES})
            if method == "resources/templates/list":
                return self._result(request_id, {"resourceTemplates": []})
            if method == "prompts/list":
                return self._result(request_id, {"prompts": []})
            if method == "resources/read":
                return self._result(request_id, self._read_resource(params))
            if method == "tools/call":
                return self._result(request_id, self._call_tool(params))
        except ControlError as exc:
            # A rejected request is a tool-level failure, not a protocol failure: the
            # model should read the reason and correct itself, not lose the connection.
            return self._result(request_id, self._failure(str(exc)))
        except LookupError as exc:
            return self._error(request_id, INVALID_PARAMS, str(exc))
        except Exception:
            return self._error(request_id, INTERNAL_ERROR, "the request could not be completed")
        return self._error(request_id, METHOD_NOT_FOUND, "unknown method: %s" % method)

    def _initialize(self, params) -> dict:
        self.initialized = True
        requested = params.get("protocolVersion")
        version = requested if requested in SUPPORTED_PROTOCOLS else PROTOCOL_VERSION
        return {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False},
                             "resources": {"subscribe": False, "listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": self._version()},
            "instructions": (
                "Manage Codex Auto Resume, which recovers the exact Codex task an "
                "interruption stopped. Use open_settings when the user wants to see or "
                "change how it behaves. Identify a pending recovery only by the exact "
                "interruption id from list_pending; never by title, project or recency. "
                "There is no way to retry an unclassified failure or to force a send, "
                "and asking for one is not an oversight to work around."),
        }

    def _version(self) -> str:
        try:
            return str(self.control.get_status().get("version") or "unknown")
        except Exception:
            return "unknown"

    def _read_resource(self, params) -> dict:
        uri = params.get("uri")
        if uri != SETTINGS_UI:
            raise LookupError("unknown resource")
        from .mcpui import settings_page
        return {"contents": [{"uri": SETTINGS_UI, "mimeType": "text/html+skybridge",
                              "text": settings_page()}]}

    # ---------------------------------------------------------------------- tools
    @staticmethod
    def _failure(message: str) -> dict:
        return {"isError": True, "content": [{"type": "text", "text": message}]}

    @staticmethod
    def _reply(summary: str, data: dict, meta=None) -> dict:
        result = {"content": [{"type": "text", "text": summary}], "structuredContent": data}
        if meta:
            result["_meta"] = meta
        return result

    def _call_tool(self, params) -> dict:
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise ControlError("arguments must be an object")
        handler = getattr(self, "_tool_" + str(name).replace("-", "_"), None)
        if handler is None or not str(name).isidentifier():
            raise LookupError("unknown tool")
        return handler(arguments)

    def _snapshot(self) -> dict:
        """Everything the settings panel needs, in one read."""
        return {"status": self.control.get_status(),
                "schema": self.control.describe_settings(),
                "settings": self.control.get_settings(),
                "pending": self.control.list_pending()}

    def _tool_open_settings(self, _arguments) -> dict:
        data = self._snapshot()
        status = data["status"]
        summary = ("Auto recovery is %s; the watcher is %s; %d pending." % (
            "on" if status["enabled"] else "paused",
            {True: "running", False: "not running"}.get(status["watcher_running"], "in an unknown state"),
            status["pending"]))
        return self._reply(summary, data, meta={"openai/outputTemplate": SETTINGS_UI})

    def _tool_get_status(self, _arguments) -> dict:
        status = self.control.get_status()
        return self._reply(
            "Auto recovery %s, watcher %s, %d pending, version %s." % (
                "enabled" if status["enabled"] else "paused",
                {True: "running", False: "not running"}.get(status["watcher_running"], "unknown"),
                status["pending"], status["version"]),
            status)

    def _tool_list_pending(self, arguments) -> dict:
        include = bool(arguments.get("include_finished"))
        rows = self.control.list_pending(include_terminal=include)
        return self._reply("%d recover%s listed." % (len(rows), "y" if len(rows) == 1 else "ies"),
                           {"pending": rows})

    def _tool_update_settings(self, arguments) -> dict:
        if not arguments:
            raise ControlError("name at least one setting to change")
        # The schema already omits them; a client that ignores the schema is refused here.
        offered = set(settings_schema()["properties"])
        refused = sorted(set(arguments) - offered)
        if refused:
            raise ControlError("not changeable from Codex: %s" % ", ".join(refused))
        values = self.control.update_settings(arguments)
        return self._reply("Updated %s." % ", ".join(sorted(arguments)), {"settings": values})

    def _tool_restore_default_settings(self, _arguments) -> dict:
        return self._reply("Settings restored to their defaults.",
                           {"settings": self.control.restore_defaults()})

    def _tool_pause_auto_recovery(self, _arguments) -> dict:
        result = self.control.set_enabled(False)
        return self._reply("Automatic recovery is paused. Nothing will be sent until it is resumed.",
                           result)

    def _tool_resume_auto_recovery(self, _arguments) -> dict:
        result = self.control.set_enabled(True)
        return self._reply("Automatic recovery is on again. Every check still applies.", result)

    def _tool_cancel_recovery(self, arguments) -> dict:
        result = self.control.cancel_interruption(arguments.get("interruption_id"), actor="mcp")
        return self._reply(result["message"][:1].upper() + result["message"][1:] + ".", result)

    def _tool_reset_recovery_budget(self, arguments) -> dict:
        result = self.control.reset_recovery_budget(arguments.get("interruption_id"), actor="mcp")
        summary = "Attempts restored; it is waiting again. Nothing was sent."
        if result.get("note"):
            summary += " Note: " + result["note"] + "."
        return self._reply(summary, result)

    def _tool_disable_conversation_recovery(self, arguments) -> dict:
        result = self.control.cancel_thread(arguments.get("thread_id"), actor="mcp")
        return self._reply("Automatic recovery is off for that conversation.", result)

    def _tool_enable_conversation_recovery(self, arguments) -> dict:
        result = self.control.set_thread_enabled(arguments.get("thread_id"), True, actor="mcp")
        return self._reply("Automatic recovery is on again for that conversation. Nothing was "
                           "sent; every check still applies.", result)

    def _tool_get_recovery_statistics(self, arguments) -> dict:
        days = arguments.get("days")
        if days is not None and (isinstance(days, bool) or not isinstance(days, (int, float))
                                 or not 1 <= days <= 3650):
            raise ControlError("days must be a number from 1 to 3650")
        result = self.control.statistics(days)
        rate = result.get("success_rate")
        return self._reply("%d interruptions, %d continuations sent, %d recovered; success rate %s." % (
            result["interruptions_detected"], result["continuations_submitted"],
            result["outcomes"]["recovered"],
            "not enough data yet" if rate is None else "%d%%" % round(rate * 100)), result)

    def _tool_get_recovery_timeline(self, arguments) -> dict:
        result = self.control.timeline(arguments.get("interruption_id"))
        return self._reply("%d events." % len(result["events"]), result)

    def _tool_clear_recovery_history(self, _arguments) -> dict:
        result = self.control.clear_history(actor="mcp")
        return self._reply("%d finished recoveries hidden; %d kept visible because they may still "
                           "change. Nothing was deleted." % (result["hidden"], result["kept"]), result)

    # What each outcome of a start actually means, in the caller's words. Only the
    # first of these says the watcher is running, and it is the only one that has been
    # told so by the same probe `get_status` uses. Reporting a launch as a running
    # watcher is what produced "The watcher is running." followed immediately by a
    # status saying it was not.
    START_WORDING = {
        "running": "The watcher is running.",
        "already-running": "It was already running; nothing to do.",
        # Deliberately the directory, not `logs/launcher.log`. That file is written by
        # the stable launcher, and `start_watcher` also has an entry-script path where
        # nothing writes it - so naming it sent the reader to a file that was not there
        # on exactly the route where the diagnosis mattered.
        "exited": "The watcher was started but stopped again straight away. "
                  "The logs directory in the installation says why; nothing is "
                  "watching right now.",
        "unconfirmed": "Watcher launch requested, but its running state could not be "
                       "confirmed. Ask for the status again in a moment.",
    }

    def _tool_start_watcher(self, _arguments) -> dict:
        result = self.control.start_watcher()
        return self._reply(self.START_WORDING.get(result.get("state"),
                                                  self.START_WORDING["unconfirmed"]), result)

    def _tool_retry_now(self, arguments) -> dict:
        result = self.control.request_retry_now(arguments.get("interruption_id"), actor="mcp")
        return self._reply(
            result["note"][:1].upper() + result["note"][1:] + ". The watcher still revalidates "
            "it, still needs the conversation open, and still refuses anything uncertain.", result)


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="codex-auto-resume-mcp", add_help=True)
    parser.add_argument("--home", help="runtime home (default: the installed location)")
    args = parser.parse_args(argv)
    home = args.home
    if not home:
        from . import config
        root = config.PROJECT_ROOT
        home = str(root.parent) if root.name == "app" else None
    # Line buffering keeps a reply from sitting in a buffer while the client waits.
    try:
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
        sys.stdin.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    return Server(Control(home)).serve()


if __name__ == "__main__":
    sys.exit(main())
