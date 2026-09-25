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

This server starts nothing. v0.6.9 measured whether it could start the watcher when Codex starts
it - Codex runs each MCP server in a job object with KILL_ON_JOB_CLOSE and no breakaway, and every
watcher started there died with the server seconds later - so `Control.start_for_codex` refuses and
records what the job said. No surface offers the setting it would have read. What a person or a
model asks for with `start_watcher` is started, in that same job, and since v0.6.10 the reply says
it lasts only until Codex ends this server rather than reporting a lasting start.

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
import math
import sys

from .. import config, controlcli, l10n, reasons as _reasons
from ..control import Control, ControlError
from .tools import RESOURCES, SETTINGS_UI, TOOLS, settings_schema

PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOLS = (PROTOCOL_VERSION, "2025-03-26", "2024-11-05")
SERVER_NAME = "codex-auto-resume"
# How long a finished server waits for its start-with-Codex launch (control.start_for_codex).
STARTER_GRACE_SECONDS = 3.0

# JSON-RPC error codes we actually use.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


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
        failed = self._error(payload.get("id"), INTERNAL_ERROR, "the request could not be completed")
        self.stream_out.write(controlcli.encode(payload, failed, dict(failed, id=None)) + "\n")
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
        # Check the envelope before any method can reach the control layer. In
        # particular, a false-y malformed value is not the same as an omitted one.
        method = message.get("method")
        request_id = message.get("id")
        valid_id = (request_id is None or isinstance(request_id, str)
                    or type(request_id) is int
                    or (type(request_id) is float and math.isfinite(request_id)))
        if (message.get("jsonrpc") != "2.0" or not isinstance(method, str)
                or not valid_id):
            return self._error(request_id if valid_id else None, INVALID_REQUEST,
                               "invalid JSON-RPC request")
        if "id" not in message:
            # A notification. Nothing may be written in reply, ever.
            return None
        params = message.get("params", {})
        if not isinstance(params, dict):
            return self._error(request_id, INVALID_PARAMS, "params must be an object")
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
            return self._result(request_id, self._failure(str(exc), exc.code))
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
        from .panel import settings_page
        l10n.set_preference(self.control.get_settings().get("interface_language"))
        return {"contents": [{"uri": SETTINGS_UI, "mimeType": "text/html+skybridge",
                              "text": settings_page()}]}

    # ---------------------------------------------------------------------- tools
    @staticmethod
    def _failure(message: str, code: str) -> dict:
        """A refused call: the sentence a reader gets, and the same refusal as a value.

        The sentence is untouched - it is what the model reads and what a bug report
        quotes. Beside it travels that refusal's code, one of the closed set the control
        layer publishes, in the same `structuredContent` a successful call already
        carries and under the same `error_code` name the bridge answers with. The code is
        the only part of a refusal a front end can say in another language; without it the
        settings panel could do nothing but frame an English sentence in Korean.

        Nothing else goes in. A code from a closed set is a machine value that carries no
        content of its own - free text here would, and this reply is part of what Codex
        sends on.
        """
        return {"isError": True, "content": [{"type": "text", "text": message}],
                "structuredContent": {"error_code": code}}

    @staticmethod
    def _reply(summary: str, data: dict, meta=None) -> dict:
        result = {"content": [{"type": "text", "text": summary}], "structuredContent": data}
        if meta:
            result["_meta"] = meta
        return result

    def _call_tool(self, params) -> dict:
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(arguments, dict):
            raise ControlError("arguments must be an object")
        tool = next((tool for tool in TOOLS if tool["name"] == name), None)
        if tool is None:
            raise LookupError("unknown tool")
        offered = tool["inputSchema"]["properties"]
        if set(arguments) - set(offered):
            raise ControlError("unrecognized tool arguments")
        if any(key not in arguments for key in tool["inputSchema"].get("required", ())):
            raise ControlError("missing required tool arguments")
        # Settings and identifiers receive their full validation in the control
        # layer; this flag used to coerce strings such as "false" to True.
        if "include_finished" in arguments and not isinstance(arguments["include_finished"], bool):
            raise ControlError("include_finished must be true or false")
        handler = getattr(self, "_tool_" + name)
        return handler(arguments)

    def _status(self) -> dict:
        """The shared status, plus the Compatibility Registry's summary under `watcher`.

        Read-only, and codes only: the coarse state and the one the watcher acts on, whether the
        report could be used, where its data came from and its sequence number, the refreshed
        data's standing, when it was checked, and each capability's state and reason from
        closed sets - what the window's Diagnostics card shows, so the settings panel's card can
        say the same. No version string, no path and no free text - this reply is part of what
        Codex sends on - and there is deliberately no tool that refreshes or imports registry
        data, so nothing a model reads can make this machine talk to GitHub. Nor what others
        report of the version (v0.6.10): that is for a person, beside the version on the
        Dashboard, and `compat.mcp_view` leaves it out.
        """
        status = self.control.get_status()
        try:
            from .. import compat, compatio
            summary = compat.mcp_view(compatio.reader_view(self.control.paths,
                                                           settings=status.get("settings")))
        except Exception:
            summary = None
        if isinstance(status.get("watcher"), dict) and summary is not None:
            status = dict(status, watcher=dict(status["watcher"], compatibility=summary))
        return status

    def _snapshot(self) -> dict:
        """Everything the settings panel needs, in one read."""
        settings = self.control.get_settings()
        l10n.set_preference(settings.get("interface_language"))
        return {"status": self._status(),
                "schema": self.control.describe_settings(),
                "settings": settings,
                "pending": self.control.list_pending(),
                "reasons": list(_reasons.RECOVERABLE),
                "endonyms": dict(l10n.ENDONYMS),
                "system_language": l10n.from_system()}

    def _tool_open_settings(self, _arguments) -> dict:
        data = self._snapshot()
        status = data["status"]
        summary = ("Auto recovery is %s; the watcher is %s; %d pending." % (
            "on" if status["enabled"] else "paused",
            {True: "running", False: "not running"}.get(status["watcher_running"], "in an unknown state"),
            status["pending"]))
        return self._reply(summary, data, meta={"openai/outputTemplate": SETTINGS_UI})

    def _tool_get_status(self, _arguments) -> dict:
        status = self._status()
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

    def _tool_preview_recovery_message(self, arguments) -> dict:
        changes = arguments.get("changes")
        if changes is not None:
            if not isinstance(changes, dict):
                raise ControlError("changes must be an object")
            allowed = {"interface_language", "continuation_language", "continuation_style",
                       "custom_message_mode"}
            if set(changes) - allowed:
                raise ControlError("only language and style can be previewed from Codex")
        preview = self.control.preview_continuation(arguments.get("category"), changes)
        return self._reply(preview["text"], {"preview": preview})

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
        result = self.control.statistics(controlcli.statistics_days(arguments))
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

    # How long a watcher started from here lasts, said after the state's own sentence whenever it
    # may be running. This server runs in the job Codex puts it in, and Start watcher asks nothing
    # of that job: measured on Codex 26.915 (v0.6.9-alpha), the job has KILL_ON_JOB_CLOSE and no
    # breakaway, so the watcher ends when Codex ends this server - when Codex closes, if not sooner.
    # Keyed by Control.launch_ends_with_job: True, or None where Windows would not say. False - a
    # watcher that outlives Codex - needs no sentence. The reply carries it as `ends_with_codex`.
    ENDS_WITH_CODEX = {
        True: "It was started from inside Codex, which ends what its plugins start, so it stops "
              "when Codex closes, if not sooner. To keep it running, start it from the Dashboard, "
              "or turn on Run at Windows sign-in there.",
        None: "It was started from inside Codex, and Windows would not say whether Codex ends what "
              "its plugins start, so it may stop when Codex closes. To keep it running, start it "
              "from the Dashboard, or turn on Run at Windows sign-in there.",
    }

    def _tool_start_watcher(self, _arguments) -> dict:
        result = self.control.start_watcher()
        summary = self.START_WORDING.get(result.get("state"), self.START_WORDING["unconfirmed"])
        if result.get("started"):
            # Only a start made here: a watcher that was already running was started elsewhere.
            ends = self.control.launch_ends_with_job()
            result["ends_with_codex"] = ends
            if ends is not False and result.get("state") != "exited":
                summary += " " + self.ENDS_WITH_CODEX[ends]
        return self._reply(summary, result)

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
    home = args.home or config.installed_home()
    # Line buffering keeps a reply from sitting in a buffer while the client waits.
    try:
        controlcli.use_utf8(sys.stdout)
        controlcli.use_utf8(sys.stdin, newline=None)
    except AttributeError:
        pass
    control = Control(home)
    # v0.6.9, "Start when Codex starts": Codex starts this server whenever it opens, so this is
    # the moment to start a watcher that is not running - beside the handshake, never in front of
    # it. Only for an installation (a home); a source checkout run without --home starts nothing.
    # Codex cancels the first servers it starts within seconds, so the launch is made at once and
    # given a moment to finish when the server is done, and never more.
    starter = None
    if home:
        import threading
        starter = threading.Thread(target=control.start_for_codex, name="start-for-codex")
        starter.start()
    try:
        return Server(control).serve()
    finally:
        if starter is not None:
            starter.join(STARTER_GRACE_SECONDS)
