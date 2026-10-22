# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""P10: what this edition adds to the status, the bridge and MCP.

The edition badge is the first of them, and the only one this version shows: the word the
version-bearing surfaces already carry gains one that says which edition this is
(decision C12). Core asks the plug at the status, the tray snapshot and the diagnostics
bundle, and the standard edition's NULL plug adds nothing there, so those surfaces are
byte-identical to today; this edition adds `edition` and how many capabilities are armed
(`on`, 0 while the registry is empty), in codes only - no version string, no path, no free
text, because the status is part of what Codex sends on. The display word for each locale
lives in this package's own catalogs (`edition.*`); core surfaces keep their own words. Since the
v0.6.11 final, core itself names the edition beside the version (the status's `edition`,
edition.shown) - since v0.6.14 only this edition, the standard edition's word is shown nowhere - so
what this badge adds there is the count.

The bridge is the Dashboard's (controlcli.serve, the long-lived form; the one-shot form never
reaches a plug). It is where the Dashboard's Advanced features page takes its words from (the
window's catalog is core's, and holds none of this edition's), and where a person reads a
capability's statement and turns it on, watches
it, turns it off, turns everything off, lowers the global ceiling, or runs a measurement by
hand (`measure <id>`, measure.py), or writes, saves, checks and sends a compatibility report
(report/flow.py, which starts gh, the GitHub CLI, as `measure` starts a session), or reads what a
watched capability would have done (`advanced-watch-log`, watchlog.py), or sets, lists and cancels the reset
actions' rules - a reset credit at the limit a person picked, their own message at the reset they picked - and uses a
reset credit now (control/resets.py) - every request made as the Dashboard. The statement carries
the warnings that hold now and the Codex version an "on" acknowledges; the request to turn it on
sends both back as the person's confirmation, and a warning is never what refuses it
(arming.py).

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
                         OffReason, Refusal, Verdict)

# The surfaces that show the version, where the edition badge sits beside it (decision C12).
# Core adds nothing there in the standard edition, so each stays as it was; this edition puts
# its badge under core's one "advanced" key, never in place of anything core shows.
BADGE_SURFACES = frozenset({Surface.STATUS, Surface.TRAY, Surface.DIAGNOSTICS})

# The arguments each bridge command takes. Anything else in a request refuses it.
ARGUMENTS = {
    BridgeCommand.ADVANCED_LIST: frozenset(),
    BridgeCommand.ADVANCED_WORDS: frozenset({"locale"}),
    BridgeCommand.ADVANCED_STATEMENT: frozenset({"capability", "locale"}),
    BridgeCommand.ADVANCED_ARM: frozenset({"capability", "state", "revision", "generation",
                                           "engine_version", "warnings", "also", "keep_on"}),
    BridgeCommand.ADVANCED_DISARM: frozenset({"capability"}),
    BridgeCommand.ADVANCED_WORDINGS: frozenset({"capability"}),
    BridgeCommand.ADVANCED_WORDING: frozenset({"capability", "key", "words", "generation"}),
    BridgeCommand.ADVANCED_DISARM_ALL: frozenset(),
    BridgeCommand.ADVANCED_CEILING: frozenset({"global_hourly", "generation"}),
    BridgeCommand.MEASURE: frozenset({"measurement", "thread", "may_spend"}),
    BridgeCommand.MEASURE_VERDICT: frozenset({"measurement", "verdict", "note"}),
    BridgeCommand.ADVANCED_OPTION: frozenset({"capability", "key", "value", "generation"}),
    BridgeCommand.ADVANCED_RULES: frozenset(),
    BridgeCommand.ADVANCED_RULE_ADD: frozenset({"tag", "status_from", "status_to", "category", "generation"}),
    BridgeCommand.ADVANCED_RULE_REMOVE: frozenset({"rule", "generation"}),
    BridgeCommand.ADVANCED_SAMPLES: frozenset(),
    BridgeCommand.ADVANCED_KEEP_ON: frozenset({"capability", "keep_on", "send_again", "generation", "confirmed"}),
    BridgeCommand.ADVANCED_SEND_NOW: frozenset({"interruption_id"}),
    BridgeCommand.ADVANCED_WATCH_LOG: frozenset({"capability"}),
    BridgeCommand.ADVANCED_RESETS: frozenset(),
    BridgeCommand.ADVANCED_RESET_ADD: frozenset({"kind", "bucket", "minutes", "ordinal", "repeat", "ask_first",
                                                 "thread_id", "words", "generation"}),
    BridgeCommand.ADVANCED_RESET_CANCEL: frozenset({"rule", "generation"}),
    BridgeCommand.ADVANCED_RESET_GO_ON: frozenset({"rule", "generation"}),
    BridgeCommand.ADVANCED_CREDIT_NOW: frozenset({"rule", "bucket", "minutes", "generation"}),
    BridgeCommand.ADVANCED_KEEP_GOING: frozenset(),
    BridgeCommand.ADVANCED_KEEP_GOING_SET: frozenset({"thread_id", "count", "generation"}),
    BridgeCommand.ADVANCED_KEEP_GOING_STOP: frozenset({"thread_id", "generation"}),
    BridgeCommand.ADVANCED_PROMPTS: frozenset(),
    BridgeCommand.ADVANCED_PROMPT_ADD: frozenset({"thread_id", "words", "trigger", "at", "every", "occurrences",
                                                  "depends", "generation", "while_running"}),
    BridgeCommand.ADVANCED_PROMPT_CANCEL: frozenset({"prompt", "generation"}),
    BridgeCommand.ADVANCED_PROMPT_GO_ON: frozenset({"prompt", "generation"}),
    BridgeCommand.ADVANCED_REPORT_BUILD: frozenset({"login"}),
    BridgeCommand.ADVANCED_REPORT_SAVE: frozenset({"sha256", "path"}),
    BridgeCommand.ADVANCED_REPORT_CHECK: frozenset({"sha256"}),
    BridgeCommand.ADVANCED_REPORT_SEND: frozenset({"sha256", "writes", "word"}),
    BridgeCommand.ADVANCED_REPORT_JOB: frozenset({"job"}),
    BridgeCommand.ADVANCED_HEADLESS_STOP: frozenset({"interruption_id"}),
}
# v0.6.19 (the groundwork): the stage's commands, in the vocabulary before any capability that answers one is built.
# Each is passed over - DEFER, so core says "unknown command" exactly as for a command this edition does not have -
# until the writer of its capability builds it: that writer gives it its arguments here, takes it out of this set, and
# answers it in `bridge`.
UNANSWERED = frozenset({
    BridgeCommand.ADVANCED_ANALYTICS, BridgeCommand.ADVANCED_ANALYTICS_CSV, BridgeCommand.ADVANCED_COURIER,
    BridgeCommand.ADVANCED_COURIER_SAVE, BridgeCommand.ADVANCED_COURIER_FORGET, BridgeCommand.ADVANCED_COURIER_TEST,
    BridgeCommand.ADVANCED_FEED_REFRESH, BridgeCommand.ADVANCED_API, BridgeCommand.ADVANCED_API_TOKEN_NEW,
    BridgeCommand.ADVANCED_REMOTE_PAIR_START, BridgeCommand.ADVANCED_REMOTE_PAIR_STATE, BridgeCommand.ADVANCED_FLEET,
    BridgeCommand.ADVANCED_FLEET_SAVE,
    BridgeCommand.ADVANCED_ACCOUNT, BridgeCommand.ADVANCED_ACCOUNT_SWITCH})
ARGUMENTS.update({command: frozenset() for command in UNANSWERED})
# #50 (v0.6.19): the completed prompts the Dashboard showed, deleted from the list (control/prompts.clear_done).
ARGUMENTS[BridgeCommand.ADVANCED_PROMPTS_CLEAR_DONE] = frozenset({"prompts", "generation"})
# and one waiting edited (control/prompts.edit): its id, and what advanced-prompt-add takes but the conversation.
ARGUMENTS[BridgeCommand.ADVANCED_PROMPT_EDIT] = frozenset({"prompt", "words", "trigger", "at", "every", "occurrences",
                                                          "depends", "while_running", "generation"})
# The compatibility report's commands (report/flow.py), answered by the action itself.
REPORT_COMMANDS = frozenset({BridgeCommand.ADVANCED_REPORT_BUILD, BridgeCommand.ADVANCED_REPORT_SAVE,
                             BridgeCommand.ADVANCED_REPORT_CHECK, BridgeCommand.ADVANCED_REPORT_SEND,
                             BridgeCommand.ADVANCED_REPORT_JOB})
REPORT = "compat_report"
# The reset actions' commands (control/resets.py).
RESET_COMMANDS = frozenset({BridgeCommand.ADVANCED_RESETS, BridgeCommand.ADVANCED_RESET_ADD,
                            BridgeCommand.ADVANCED_RESET_CANCEL, BridgeCommand.ADVANCED_RESET_GO_ON,
                            BridgeCommand.ADVANCED_CREDIT_NOW})

# Keep going's commands (control/keepgoing.py, v0.6.15-beta), the Dashboard's alone.
KEEP_GOING_COMMANDS = frozenset({BridgeCommand.ADVANCED_KEEP_GOING, BridgeCommand.ADVANCED_KEEP_GOING_SET,
                                 BridgeCommand.ADVANCED_KEEP_GOING_STOP})

# The prompt queue's commands (control/prompts.py, v0.6.15-beta), the Dashboard's alone.
PROMPT_COMMANDS = frozenset({BridgeCommand.ADVANCED_PROMPTS, BridgeCommand.ADVANCED_PROMPT_ADD,
                             BridgeCommand.ADVANCED_PROMPT_CANCEL, BridgeCommand.ADVANCED_PROMPT_GO_ON,
                             # v0.6.19 (#50): Delete completed, and an edit.
                             BridgeCommand.ADVANCED_PROMPTS_CLEAR_DONE, BridgeCommand.ADVANCED_PROMPT_EDIT})

_NO_ARGUMENTS = {"type": "object", "properties": {}, "additionalProperties": False}
_OFF_ONLY = ("Turning a capability on is not something any tool does: the user does it in the "
             "Codex Auto Resume Dashboard, after reading what it does.")

TOOLS = [
    {"name": McpTool.LIST_ADVANCED_CAPABILITIES, "title": "List advanced capabilities",
     "description": "The advanced edition's capabilities, each with its id, whether it is on, "
                    "watched or off, since when and why, the standards it departs from, the "
                    "choices set for it and whether it is kept on, and sends again when unsure. "
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
    if name == Surface.DIAGNOSTICS:
        return diagnostics(runtime)
    if name == Surface.STATUS:
        return status(runtime)
    if name == Surface.TRAY:
        return dict(badge(runtime), **meter_view(runtime), **notice_view(runtime), **update_view(runtime))
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


def status(runtime) -> dict:
    """The status's badge, and - only where a reset rule waits (v0.6.14) - how many messages and credit rules wait
    and how many of them are due: counts, never a word of a message or a conversation (control/resets.counts)."""
    shown = badge(runtime)
    from .control import prompts as prompt_queue, resets as reset_actions
    try:
        shown.update(reset_actions.counts(runtime))
        shown.update(prompt_queue.counts(runtime))
    except Exception:
        pass
    shown.update(meter_view(runtime))
    # v0.6.16-beta.4: the turns run here now, only where there are any - and what Pending and History say of a row
    # the edition had a hand in, keyed by interruption id, only where there is something to say.
    found = runs(runtime)
    if found:
        shown["runs"] = found
    shown.update(rows(runtime))
    return shown


def meter_view(runtime) -> dict:
    """The usage meter's last reading, for the tooltip and the popup (v0.6.16-beta.3, issue #29) - only while the
    meter is on, and {} otherwise, so with it off nothing here changes: {"meter": {"read_at", "windows": [each
    window's bucket, window_minutes, used_percent, reset_at and band - warn, wrap_up, pause or none, by the
    percentages of the stages that are on], "notices": [a warning the meter showed in the last NOTICE_FOR seconds:
    its key, window_minutes, used_percent, reset_at]}}. Numbers and closed words only, as core's own reading is."""
    from .engine import usage
    try:
        states = runtime.states()
        if states.get(usage.METER) != ArmingState.ARMED:
            return {}
        rows = runtime.state.meter()
        now = runtime.clock()
        options = {capability: runtime.state.options(capability)
                   for capability in (usage.METER, usage.WRAP_UP, usage.PAUSE)}
    except Exception:
        return {}
    if not rows:
        return {}
    shown, notices = [], []
    # v0.6.16 final: each stage by the windows its own switches leave on.
    on = {capability: usage.acting(values) for capability, values in options.items()}
    for (bucket, minutes), row in sorted(rows.items()):
        band = "none"
        for capability, word in ((usage.PAUSE, "pause"), (usage.WRAP_UP, "wrap_up"), (usage.METER, "warn")):
            if (minutes in on[capability] and states.get(capability) == ArmingState.ARMED
                    and usage.reached(row, usage.percent(options[capability], capability, minutes), now)):
                band = word
                break
        shown.append({"bucket": bucket, "window_minutes": minutes, "used_percent": row["used_percent"],
                      "reset_at": row["reset_at"], "band": band})
        warned = row["warned_at"]
        if (warned is not None and 0 <= now - warned < usage.NOTICE_FOR and row["warned_reset_at"] == row["reset_at"]
                and row["reset_at"] is not None):
            notices.append({"key": "%s:%d:%d" % (bucket, minutes, row["reset_at"]), "window_minutes": minutes,
                            "used_percent": row["used_percent"], "reset_at": row["reset_at"], "kind": "warn"})
    # v0.6.16-beta.4 (h): what the forced stop has to say - a turn it could not stop, a queue to Resume in Codex, a
    # conversation it could not continue after the reset.
    if states.get(usage.PAUSE) == ArmingState.ARMED:
        try:
            said = runtime._code_of(runtime.registry.get(usage.PAUSE)).notices(now)
        except Exception:
            said = []
        for notice in said:
            notices.append(dict(notice, used_percent=None))
    return {"meter": {"read_at": max(row["read_at"] for row in rows.values()), "windows": shown,
                      "notices": notices}}


def notice_view(runtime) -> dict:
    """What the watcher adds to the notices it builds (v0.6.18): {"notice": {"open_codex": true}} while Open Codex on
    a notice stands on and Windows can open a `codex:` link here (control/opencodex.py), {} otherwise - so with it
    off, or with no handler, every notice is exactly the standard edition's. A closed flag, nothing else."""
    from .control import opencodex
    try:
        definition = runtime.registry.get(opencodex.CAPABILITY)
        if definition is None or runtime.states().get(opencodex.CAPABILITY) != ArmingState.ARMED:
            return {}
        if runtime.action(definition).available() is not True:
            return {}
    except Exception:
        return {}
    return {"notice": {"open_codex": True}}


def update_view(runtime) -> dict:
    """What the weekly update check offers (v0.6.18), for the watcher to show once: {"update": {"notices": [{"key",
    "version", "prerelease"}]}} while it stands on and its last check in this process offered a newer version, {}
    otherwise. A version and a flag, both read back to their shapes by core before anything is shown."""
    from .engine import updatecheck
    try:
        definition = runtime.registry.get(updatecheck.CAPABILITY)
        if definition is None or runtime.states().get(updatecheck.CAPABILITY) != ArmingState.ARMED:
            return {}
        found = runtime._code_of(definition).offered()
    except Exception:
        return {}
    if found is None:
        return {}
    version, prerelease = found
    return {"update": {"notices": [{"key": "update:" + version, "version": version, "prerelease": prerelease}]}}


def diagnostics(runtime) -> dict:
    """The badge, and - only where there are any - the samples of the last 30 days of failures nothing
    classified, aggregated: Codex's code, a status number, the error's form, how many times and the last
    day (arming.samples_view); and what each watched capability would have done in those 30 days: its
    id, since when it is watched, each answer's word, where it was asked, how many times and the first
    and last minute (watchlog.exported). No id of a conversation, a turn or an interruption, and never a
    word of an error or of a continuation (D5): nothing in either to alias, and nothing quoted. The
    export is the person's own, made when they ask for it; the status and the tray, which Codex sends
    on, never carry them."""
    shown = badge(runtime)
    try:
        found = runtime.arming.samples_view()
    except Exception:
        found = {}
    if found.get("samples"):
        shown["samples"] = found["samples"]
    from . import watchlog
    try:
        watch = watchlog.exported(runtime)
    except Exception:
        watch = []
    if watch:
        shown["watch"] = watch
    return shown


# ---------------------------------------------------------------------------- the Dashboard
def bridge(runtime, command, argument):
    if command not in tuple(BridgeCommand) or command in UNANSWERED or not isinstance(argument, dict):
        return DEFER
    command = BridgeCommand(command)
    if set(argument) - ARGUMENTS[command]:
        return {"done": False, "refusal": Refusal.INVALID_REQUEST}
    if command in REPORT_COMMANDS:
        return report(runtime, command, argument)
    arming = runtime.arming
    if command == BridgeCommand.ADVANCED_LIST:
        return dict(arming.listing(), done=True)
    if command == BridgeCommand.ADVANCED_WORDS:
        locale = _locale(argument.get("locale"))
        return {"done": True, "locale": locale, "words": arming.catalogs.words(locale)}
    if command == BridgeCommand.ADVANCED_STATEMENT:
        definition = runtime.registry.get(argument.get("capability"))
        if definition is None:
            return {"done": False, "refusal": Refusal.UNKNOWN_CAPABILITY}
        return dict(arming.statement(definition, _locale(argument.get("locale"))), done=True)
    if command == BridgeCommand.ADVANCED_ARM:
        return arming.arm(argument.get("capability"), state=argument.get("state"),
                          revision=argument.get("revision"), generation=argument.get("generation"),
                          acknowledged_version=argument.get("engine_version"),
                          warnings=argument.get("warnings"), also=argument.get("also"),
                          keep_on=argument.get("keep_on", False), actor=Actor.DASHBOARD)
    if command == BridgeCommand.ADVANCED_DISARM:
        return arming.disarm(argument.get("capability"), actor=Actor.DASHBOARD)
    if command == BridgeCommand.ADVANCED_WORDINGS:
        return arming.wordings_view(argument.get("capability"))
    if command == BridgeCommand.ADVANCED_WORDING:
        return arming.set_wording(argument.get("capability"), argument.get("key"), argument.get("words"),
                                  generation=argument.get("generation"), actor=Actor.DASHBOARD)
    if command == BridgeCommand.ADVANCED_DISARM_ALL:
        return arming.all_off(actor=Actor.DASHBOARD)
    if command == BridgeCommand.MEASURE:
        return measure(runtime, argument.get("measurement"), argument.get("thread"),
                       argument.get("may_spend", False))
    if command == BridgeCommand.MEASURE_VERDICT:
        return measure_verdict(runtime, argument.get("measurement"), argument.get("verdict"),
                               argument.get("note"))
    if command == BridgeCommand.ADVANCED_OPTION:
        return arming.set_option(argument.get("capability"), argument.get("key"), argument.get("value"),
                                 generation=argument.get("generation"), actor=Actor.DASHBOARD)
    if command == BridgeCommand.ADVANCED_RULES:
        return arming.rules_view()
    if command == BridgeCommand.ADVANCED_RULE_ADD:
        return arming.add_rule(argument.get("tag"), argument.get("status_from"), argument.get("status_to"),
                               argument.get("category"), generation=argument.get("generation"),
                               actor=Actor.DASHBOARD)
    if command == BridgeCommand.ADVANCED_RULE_REMOVE:
        return arming.remove_rule(argument.get("rule"), generation=argument.get("generation"),
                                  actor=Actor.DASHBOARD)
    if command == BridgeCommand.ADVANCED_SAMPLES:
        return arming.samples_view()
    if command == BridgeCommand.ADVANCED_SEND_NOW:
        from .control import sendnow
        return sendnow.request(runtime, argument.get("interruption_id"))
    if command == BridgeCommand.ADVANCED_HEADLESS_STOP:
        return headless_stop(runtime, argument.get("interruption_id"))
    if command == BridgeCommand.ADVANCED_WATCH_LOG:
        from . import watchlog
        return watchlog.view(runtime, argument.get("capability"))
    if command in RESET_COMMANDS:
        return resets(runtime, command, argument)
    if command in PROMPT_COMMANDS:
        from .control import prompts
        if command == BridgeCommand.ADVANCED_PROMPTS:
            return prompts.view(runtime)
        if command == BridgeCommand.ADVANCED_PROMPT_ADD:
            return prompts.add(runtime, argument)
        if command == BridgeCommand.ADVANCED_PROMPT_CANCEL:
            return prompts.cancel(runtime, argument.get("prompt"), argument.get("generation"))
        if command == BridgeCommand.ADVANCED_PROMPTS_CLEAR_DONE:
            return prompts.clear_done(runtime, argument)
        if command == BridgeCommand.ADVANCED_PROMPT_EDIT:
            return prompts.edit(runtime, argument)
        return prompts.go_on(runtime, argument.get("prompt"), argument.get("generation"))
    if command in KEEP_GOING_COMMANDS:
        from .control import keepgoing
        if command == BridgeCommand.ADVANCED_KEEP_GOING:
            return keepgoing.view(runtime)
        if command == BridgeCommand.ADVANCED_KEEP_GOING_SET:
            return keepgoing.set_one(runtime, argument)
        return keepgoing.stop(runtime, argument)
    if command == BridgeCommand.ADVANCED_KEEP_ON:
        return arming.set_keep_on(argument.get("capability"), argument.get("keep_on"),
                                  send_again=argument.get("send_again", False),
                                  generation=argument.get("generation"), confirmed=argument.get("confirmed"),
                                  actor=Actor.DASHBOARD)
    return arming.set_global_hourly(argument.get("global_hourly"), generation=argument.get("generation"),
                                    actor=Actor.DASHBOARD)


def headless_stop(runtime, interruption_id):
    """advanced-headless-stop (v0.6.16-beta.4): a person's Stop of the turn run here for `interruption_id`, asked
    from the Dashboard - written for the watcher's next tick to hand on (engine/headless.py), and the watcher woken.
    Refused for an id of the wrong shape and where no such run is going. Never an MCP tool's."""
    from codex_auto_resume.domain import ids
    from .control.sendnow import wake
    from .state import StateError
    if not ids.is_interruption_id(interruption_id):
        return {"done": False, "refusal": Refusal.INVALID_REQUEST}
    try:
        stopped = runtime.state.run_stop(interruption_id, at=runtime.clock())
    except StateError:
        return {"done": False, "refusal": Refusal.STATE_UNAVAILABLE}
    if not stopped:
        return {"done": False, "refusal": Refusal.NOT_ON}
    try:
        wake(runtime.paths)
    except Exception:
        pass                                         # the Stop stands; the next tick finds it
    return {"done": True, "refusal": None}


def runs(runtime) -> list:
    """The turns run here now, as Pending shows them (v0.6.16-beta.4): each one's interruption id, which capability
    runs it, when it began and by when its cap ends it, and whether a Stop was asked - never a conversation's word."""
    try:
        return [{"interruption_id": row["interruption_id"], "capability": row["capability"],
                 "started_at": row["started_at"], "ends_by": row["ends_by"],
                 "stopping": row["stop_requested_at"] is not None}
                for row in runtime.state.runs(live=True)]
    except Exception:
        return []


# ---------------------------------------------------------------------------- Pending's and History's rows
# The rows Pending and History list (control/records: the records still going, and the newest 200), and how long a
# conversation's kind is kept once read: a conversation the Codex app takes over from a terminal (issue #37) is the
# app's own from then on, so a kind is read again after a while.
ROWS_READ = 200
KIND_SECONDS = 600.0
# {(Codex home, conversation id): (its kind or None, when it was read)}, for the life of the bridge's process.
_KINDS = {}


def rows(runtime, *, store=None, source=None) -> dict:
    """What Pending and History say beside a row this edition had a hand in (P10, v0.6.16-beta.4), keyed by
    interruption id - words of this edition's own, never a conversation's: {"kinds": {id: "cli" or "ide"}} for a
    conversation of a terminal's Codex TUI or of VS Code (other_sessions: " · CLI" or " · VS Code" on its label line);
    {"compacting": [id, ...]} for a full conversation compact_continue holds until the person runs /compact in the
    Codex app (its row's status says so); {"model_not_restored": [id, ...]} for a turn model_fallback ran on Codex's
    default model whose conversation's own model Codex would not put back - its row says to switch it back in Codex,
    in words with no model's name (the review's finding 22), for as long as it is owed (state/runs.py), whatever the
    capability stands at now; {"silent": [id, ...]} for a continuation a turn run here started with no words and
    proved by its id (silent_continuation: History says so), while the edition keeps that run (engine/headless.py,
    KEEP_ENDED). Each part only where there is something in it, and read only while the capability it
    is of stands on (or, for the kinds, watched) - a model owed back aside, which is the edition's own state - so with
    none of them on nothing of core's or Codex's is read at all. `store` is core's state and `source` the Codex
    home's reader - the Dashboard's own, by default; a test's."""
    from .registry import COMPACT_CONTINUE, MODEL_FALLBACK, OTHER_SESSIONS
    try:
        states = runtime.states()
    except Exception:
        return {}
    shown = {}
    try:
        owed = [row["interruption_id"] for row in runtime.state.runs_owed(MODEL_FALLBACK.id)
                if row["ended_at"] is not None]
    except Exception:
        owed = []
    if owed:
        shown["model_not_restored"] = owed
    silent = _silent(runtime, store)
    if silent:
        shown["silent"] = silent
    kinds_wanted = states.get(OTHER_SESSIONS.id, ArmingState.OFF) != ArmingState.OFF
    compact_wanted = states.get(COMPACT_CONTINUE.id, ArmingState.OFF) == ArmingState.ARMED
    if not (kinds_wanted or compact_wanted):
        return shown
    try:
        listed = _listed(runtime, store)
    except Exception:
        return shown
    if kinds_wanted:
        try:
            reader = source if source is not None else _source(runtime)
            kinds = {key: kind for key, kind in ((row["interruption_id"], _kind(reader, row["thread_id"]))
                                                 for row in listed if not row.get("home_key")) if kind}
        except Exception:
            kinds = {}
        if kinds:
            shown["kinds"] = kinds
    if compact_wanted:
        compacting = [row["interruption_id"] for row in listed if _compacting(row)]
        if compacting:
            shown["compacting"] = compacting
    return shown


def _silent(runtime, store) -> list:
    """The interruptions a turn run here continued with no words (P15's SILENT): a run of headless_run's or
    compact_continue's the edition still keeps whose core record went by the client id core derives for it
    (engine/routes._silent) - the proof by id, which a marker-free send through a channel never had from a run here.
    Core's state is opened only where there is such a run."""
    from codex_auto_resume.domain import ids
    from codex_auto_resume.store import Store
    try:
        keys = [row["interruption_id"] for row in runtime.state.runs(live=False, limit=ROWS_READ)
                if row["capability"] in ("headless_run", "compact_continue") and row["ended_at"] is not None]
    except Exception:
        return []
    if not keys:
        return []
    try:
        if store is None:
            with Store(runtime.paths.state_dir) as opened:
                return _silent_of(opened, keys, ids)
        return _silent_of(store, keys, ids)
    except Exception:
        return []


def _silent_of(store, keys, ids) -> list:
    found = []
    for key in keys:
        row = store.get(key)
        if row is not None and row.get("recovery_client_id") == ids.continuation_client_id(key):
            found.append(key)
    return found


def _compacting(row) -> bool:
    """Whether core's record `row` is a full conversation compact_continue holds for the person's /compact: still
    waiting, of its kind, its conversation available to the app and held there at P3 (engine/compact.py)."""
    from codex_auto_resume import machine
    from .engine.compact import KIND
    if row.get("category") != KIND or row.get("state") not in machine.WAITING or not row.get("gate_eval"):
        return False
    try:
        return machine.decode_gates(row["gate_eval"]).get("thread_available") == (machine.WAIT, machine.HELD)
    except Exception:
        return False


def _listed(runtime, store) -> list:
    """The records Pending and History list, each once: those still going, then the newest ROWS_READ."""
    from codex_auto_resume.store import Store
    if store is None:
        with Store(runtime.paths.state_dir) as opened:
            return _listed(runtime, opened)
    seen, found = set(), []
    for row in store.pending() + store.history(limit=ROWS_READ):
        if row["interruption_id"] not in seen:
            seen.add(row["interruption_id"])
            found.append(row)
    return found


def _source(runtime):
    from codex_auto_resume.codex import LocalSource
    from .codex import inuse
    return LocalSource(inuse.home(runtime.paths))


def _kind(source, thread_id):
    """"cli" or "ide" for a conversation of a terminal's Codex TUI or of VS Code, judged as core judges one
    (LocalSource.taken: its row and its file's first line); None for the app's own - one it took over or forked from
    a terminal among them - and for anything else. Kept KIND_SECONDS; one that cannot be read is not kept."""
    from time import monotonic
    from codex_auto_resume.domain.plughands import SessionKind
    key, now = (str(getattr(source, "home", "")), thread_id), monotonic()
    held = _KINDS.get(key)
    if held is not None and 0 <= now - held[1] < KIND_SECONDS:
        return held[0]
    found = None
    if not source.taken(thread_id, frozenset()):
        found = next((str(kind) for kind in (SessionKind.CLI, SessionKind.IDE)
                      if source.taken(thread_id, frozenset({kind}))), None)
    if len(_KINDS) > 4096:
        _KINDS.clear()
    _KINDS[key] = (found, now)
    return found


def resets(runtime, command, argument):
    """One of the reset actions' commands (control/resets.py), the Dashboard's."""
    from .control import resets as reset_actions
    if command == BridgeCommand.ADVANCED_RESETS:
        return reset_actions.view(runtime)
    if command == BridgeCommand.ADVANCED_RESET_ADD:
        return reset_actions.add(runtime, argument)
    if command == BridgeCommand.ADVANCED_RESET_CANCEL:
        return reset_actions.cancel(runtime, argument.get("rule"), argument.get("generation"))
    if command == BridgeCommand.ADVANCED_RESET_GO_ON:
        return reset_actions.go_on(runtime, argument.get("rule"), argument.get("generation"))
    return reset_actions.credit_now(runtime, argument)


def report(runtime, command, argument):
    """One of the compatibility report's commands, put to the action's own code (report/flow.py), which
    answers it as the Dashboard's: write it, save it, check what sending would write, send it - which
    starts gh, as `measure` starts a session - or read how a job is getting on."""
    definition = runtime.registry.get(REPORT)
    if definition is None:
        return {"done": False, "refusal": Refusal.UNKNOWN_CAPABILITY}
    try:
        code = runtime.action(definition)
        return code.answer(runtime, definition, command, argument)
    except Exception:
        runtime.arming.trip(definition.id, OffReason.HOOK_EXCEPTION)
        return {"done": False, "refusal": Refusal.STATE_UNAVAILABLE}


def _locale(asked):
    """The locale a request's words are in: the Interface language the window names - `system`
    included, which is Windows' - or, where it names none, the one this process resolved to."""
    return l10n.resolve(asked) if isinstance(asked, str) and asked else l10n.current()


def measure(runtime, measurement, thread=None, may_spend=False):
    """Run one measurement the person named, and hand back what was recorded (measure.py).

    The id has to be one of the M-list, or it is refused as an invalid request; running it opens
    a real one-turn session and writes to the source tree, so it is the person's own action, made
    from the Dashboard, and never a model's - no MCP tool reaches this.

    `thread` is an optional real throwaway conversation the person points it at. It has to be a
    string when given; whether it is a Codex thread id is checked in the harness, which never
    writes it into the record. `may_spend` (v0.6.14) is the person's second, explicit yes that MR may
    spend one real reset credit: a boolean when given, true only in as many words, and read by MR
    alone - without it MR opens no session and spends nothing."""
    try:
        which = Measurement(measurement)
    except ValueError:
        return {"done": False, "refusal": Refusal.INVALID_REQUEST}
    if (thread is not None and not isinstance(thread, str)) or type(may_spend) is not bool:
        return {"done": False, "refusal": Refusal.INVALID_REQUEST}
    try:
        summary = runtime.run_measurement(which, thread=thread, may_spend=may_spend)
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
        # Its choices' values, read-only; never its rules or samples, which only the Dashboard reads.
        shown = [dict({key: item[key] for key in ("id", "state", "since", "by", "reason", "departs_from",
                                                  "keep_on", "send_again", "notice")},
                      options={option["key"]: option["value"] for option in item["options"]})
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
