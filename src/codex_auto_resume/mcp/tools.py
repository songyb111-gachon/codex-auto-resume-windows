"""What this server offers Codex: the tools, their schemas, and the one resource.

Declarations only - no behaviour. Every tool here is a name, a description a model reads to
decide whether to call it, and a JSON Schema its arguments are validated against; what happens
when one is called is `server.py`. They were the first 300 lines of `mcpserver.py`, which meant
that reading what the server *does* started with 195 lines of schema.

The descriptions are part of the product's safety, not documentation of it. A model chooses
between these tools by reading them, so each says plainly what it will and will not do - and
`annotations` says the same thing in the words MCP defines (`readOnlyHint`, `destructiveHint`,
`idempotentHint`), for a client that shows them rather than the prose.
"""
from __future__ import annotations

import re

from .. import controlcli, quiet, reasons as _reasons, settings as policy
from ..domain import ids

SETTINGS_UI = "ui://codex-auto-resume/settings"



def _identifier_schema(title: str) -> dict:
    return {"type": "string", "title": title,
            "description": "The exact interruption id, as listed by list_pending. "
                           "Never a title, a project name, or 'the most recent one'.",
            "pattern": ids.INTERRUPTION_ID_SCHEMA}


# Settings groups a person can change from a front end. Anything else is not offered to
# a model and is refused if a client sends it anyway.
USER_GROUPS = frozenset({"general", "recovery", "limits", "notifications", "continuation"})
# The Appearance settings the panel offers: both themes, which colour it. Reduce motion and the
# notification-area icon ("windows") stay out: what moves is not Codex's to change (standard H3). So
# does the design (v0.6.10). It was kept out because it decided what moves - v0.6.10's Still stopped
# motion and Soft started it again - and since v0.6.11 it chooses paint alone, Still having become
# Reduce motion; offering it to Codex now would be a decision of its own, not a side effect of that.
# The panel draws in both, and edits neither: they are written in the Dashboard.
# restore_default_settings still puts both back, as it puts back every setting.
PANEL_APPEARANCE = frozenset({"theme", "panel_theme"})


# v0.6.11: what the quiet hours and the tiers do, for a model choosing a value. Each can only hold
# a recovery back, except default_tier towards automatic, which is why update_settings asks first.
QUIET_AND_TIERS = {
    "quiet_hours_start": "When quiet hours start, local time, or off (the default: none). A recovery "
                         "that falls due in them waits until they end; nothing else changes.",
    "quiet_hours_end": "When quiet hours end, local time. Nothing while quiet_hours_start is off.",
    "quiet_hours_days": "The days quiet hours start on. Nothing while quiet_hours_start is off.",
    "default_tier": "How much a conversation without a tier of its own asks before it is resumed: "
                    "automatic (the default), objection_window (a card first, objection_minutes to "
                    "stop it), ask_first or notify_only (nothing is sent until a person lets it "
                    "continue). Applies to interruptions detected after it is chosen.",
    "objection_minutes": "How long the objection window waits before a continuation is sent.",
    # And what Observe only does, and which conversations and projects resume without a person.
    "observe_only": "Observe only: every check still runs and when a continuation would have been "
                    "sent is recorded, but nothing is sent. false (the default) sends as usual.",
    "new_conversation_policy": "What a conversation this product has never seen before gets: resume "
                               "(the default: the same as every other conversation) or notify_only "
                               "(its own tier becomes Only notify me, so nothing is sent for it until "
                               "a person lets a task continue).",
    "project_policy": "Which projects resume without a person: every (the default), only_listed (only "
                      "projects a person set to Always on a task's row) or except_listed (every "
                      "project but those set to Never). An interruption of any other project, or of "
                      "one whose project cannot be read, waits for a person and is never dropped. "
                      "Applies to interruptions detected after it is chosen.",
    # And the Custom waits, jitter, the time ceiling and the two guards (ladder.py, guards.py).
    **{field: "Wait %d of the custom retry timing, read only while retry_timing is custom: the "
              "wait before attempt %d at a task that failed with a temporary error. Whatever is "
              "chosen, one conversation gets a continuation at most every 15 minutes and 5 a day."
              % (number, number) for number, field in enumerate(policy.STEP_FIELDS, 1)},
    "retry_jitter": "Adds up to a fifth to each wait of a temporary failure, never taking any off. "
                    "false (the default) waits exactly.",
    "chain_time_ceiling": "How long a task may keep failing with temporary errors before it stops: "
                          "off (the default) or a number of hours, from its first failure to its "
                          "latest. Waiting for a person, quiet hours or a closed app never count.",
    "task_changed_guard": "When a recovery falls due, compare its conversation's model, approval "
                          "mode and folder's git HEAD with when it stopped: off (the default, nothing "
                          "is read), hold (a change waits for a person) or tell (it is sent, and its "
                          "notification says the task changed). Only a digest is kept.",
    "context_guard": "Codex's token count for a conversation, where Codex keeps one: off (the "
                     "default, nothing is read), show (on Pending), or above_100k to above_1m (also "
                     "hold a recovery whose conversation has used more, for a person).",
}


def _thread_schema() -> dict:
    return {"type": "string", "pattern": ids.THREAD_ID_SCHEMA,
            "description": "The conversation's exact thread id, from the same row of list_pending"}


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
        if entry.get("group") not in USER_GROUPS and name not in PANEL_APPEARANCE:
            continue
        # Custom continuation text is the one thing in the continuation group Codex may not
        # write. Whatever it says is later sent into the user's conversations by the
        # watcher, on the user's behalf, when nobody is watching. A model that had been
        # talked into changing it by a page it read would have turned one injected
        # instruction into a standing one, delivered at every future interruption. Language
        # and style only choose among texts this product ships or the user wrote; the text
        # itself is written in the Windows Dashboard, where the person typing it is the
        # person it will speak for.
        if policy.is_custom_text(name):
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
        elif name in ("theme", "panel_theme"):
            described["description"] = {
                "theme": "Light or dark for the settings window, the popup, the notification card and, "
                         "while panel_theme is same, the panel. system: Windows there, Codex in the panel.",
                "panel_theme": "Light or dark for the settings panel in Codex alone: same uses theme's "
                               "choice, system follows Codex whatever theme is. Changes nothing but colours."}[name]
        elif name in QUIET_AND_TIERS:
            described["description"] = QUIET_AND_TIERS[name]
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
                       "starts and decides nothing about any interruption. Started from "
                       "here it runs inside Codex. Where Codex ends what its plugins start, "
                       "as Codex 26.915 was measured to, it stops when Codex closes, if not "
                       "sooner; the reply reads that from the job each time and says so. A "
                       "watcher that outlives Codex is one started from Codex Auto Resume in "
                       "the Start menu once Codex has closed, or at Windows sign-in.",
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
        "name": "postpone_recovery",
        "title": "Postpone one waiting recovery",
        "description": "Make one exact waiting recovery wait longer: nothing is sent for it before "
                       "the time asked for - preset 30_minutes, 1_hour, 3_hours or tomorrow_morning "
                       "(09:00 local time), or a number of minutes up to a week; give exactly one. "
                       "Identify it by its interruption id and its thread id, both from the same row "
                       "of list_pending - never by title, project or recency. It only ever makes a "
                       "recovery later, sends nothing and skips no check; retry_now does not bring "
                       "it forward.",
        "inputSchema": {"type": "object",
                        "properties": {"interruption_id": _identifier_schema("Interruption id"),
                                       "thread_id": _thread_schema(),
                                       "preset": {"type": "string", "enum": list(quiet.PRESETS)},
                                       "minutes": {"type": "integer", "minimum": 1,
                                                   "maximum": quiet.MAX_POSTPONE_SECONDS // 60}},
                        "required": ["interruption_id", "thread_id"], "additionalProperties": False},
        # Not destructive: it only ever holds a recovery back, as a pause does (H8).
        "annotations": {"readOnlyHint": False, "destructiveHint": False,
                        "idempotentHint": False, "openWorldHint": False},
    },
    {
        "name": "release_hold",
        "title": "Let one held recovery continue",
        "description": "Let one exact recovery that waits for a person continue - one whose "
                       "conversation asks first or only notifies (its hold in list_pending). "
                       "Identify it by its interruption id and its thread id from the same row. "
                       "Nothing is sent by this; the watcher still runs every check, and a "
                       "postponement or quiet hours still apply. This lets automation run again for "
                       "that recovery, so Codex asks the user first.",
        "inputSchema": {"type": "object",
                        "properties": {"interruption_id": _identifier_schema("Interruption id"),
                                       "thread_id": _thread_schema()},
                        "required": ["interruption_id", "thread_id"], "additionalProperties": False},
        # Destructive: it lets a recovery a person held go again, so Codex asks first (H8).
        "annotations": {"readOnlyHint": False, "destructiveHint": True,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "disable_conversation_recovery",
        "title": "Turn recovery off for one conversation",
        "description": "Stop automatic recovery for one exact conversation, including "
                       "its later interruptions, and cancel what it has waiting. Only "
                       "ever reduces automation.",
        "inputSchema": {"type": "object",
                        "properties": {"thread_id": {"type": "string", "pattern": ids.THREAD_ID_SCHEMA,
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
                        "properties": {"thread_id": {"type": "string", "pattern": ids.THREAD_ID_SCHEMA,
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
                        "properties": {"days": {"type": "number", "minimum": controlcli.DAYS[0],
                                                "maximum": controlcli.DAYS[1]}},
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

# Preview, read-only. It sends nothing and saves nothing: it returns the text the watcher
# would send for one kind of interruption under the current settings, or under a language
# and style given for the preview alone. Custom text is not accepted here, for the same
# reason it is not writable from Codex at all.
TOOLS.append({
    "name": "preview_recovery_message",
    "title": "Preview the recovery message",
    "description": "Show the exact text Codex Auto Resume would send to continue a task after "
                   "an interruption of the given kind, under the current settings or the "
                   "language and style given. Read-only: it saves nothing and sends nothing.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "category": {"type": "string", "enum": list(_reasons.RECOVERABLE),
                         "description": "The kind of interruption to preview."},
            "changes": {
                "type": "object",
                "description": "Unsaved choices to preview with. Nothing is stored.",
                "properties": {
                    "interface_language": {"type": "string"},
                    "continuation_language": {"type": "string"},
                    "continuation_style": {"type": "string"},
                    "custom_message_mode": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        "required": ["category"],
        "additionalProperties": False,
    },
    "annotations": {"title": "Preview the recovery message", "readOnlyHint": True,
                    "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
})

# v0.6.11: what a tool the edition's plug offers (P10) is let through as. A name of its own, never
# one of core's - so no plug can stand in for a tool whose description a model has learned to
# trust - and a schema that names every argument and allows no other, which is what the server
# checks a call against before the plug hears of it. The annotations say at least whether it
# reads and whether it destroys, as every tool of core's does. What such a tool may do is its
# edition's affair; a declaration that is not one of these shapes is not offered at all.
PLUGGED_NAME = re.compile(r"[a-z][a-z0-9_]{2,63}")
PLUGGED_KEYS = ("name", "title", "description", "inputSchema", "annotations")


def _declared(tool, taken) -> bool:
    if not isinstance(tool, dict):
        return False
    name, schema, notes = tool.get("name"), tool.get("inputSchema"), tool.get("annotations")
    if (not isinstance(name, str) or not PLUGGED_NAME.fullmatch(name) or name in taken
            or not isinstance(tool.get("description"), str)
            or not isinstance(tool.get("title", ""), str)):
        return False
    if (not isinstance(schema, dict) or schema.get("type") != "object"
            or schema.get("additionalProperties") is not False
            or not isinstance(schema.get("properties"), dict)
            or not all(isinstance(value, dict) for value in schema["properties"].values())):
        return False
    required = schema.get("required", [])
    if not isinstance(required, list) or not all(isinstance(key, str) for key in required):
        return False
    return (set(required) <= set(schema["properties"]) and isinstance(notes, dict)
            and all(isinstance(notes.get(hint), bool) for hint in ("readOnlyHint", "destructiveHint")))


def plugged_tools(declared) -> list:
    """The tools a plug declared that may be offered, in its order, each once and after core's."""
    if not isinstance(declared, list):
        return []
    taken, kept = {tool["name"] for tool in TOOLS}, []
    for tool in declared:
        if _declared(tool, taken):
            taken.add(tool["name"])
            kept.append({key: tool[key] for key in PLUGGED_KEYS if key in tool})
    return kept


RESOURCES = [{
    "uri": SETTINGS_UI,
    "name": "Codex Auto Resume settings",
    "description": "The settings panel shown by open_settings.",
    "mimeType": "text/html+skybridge",
}]
