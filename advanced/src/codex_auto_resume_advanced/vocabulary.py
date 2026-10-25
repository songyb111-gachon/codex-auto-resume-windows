# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The advanced edition's closed words: every word its state holds, its journal writes and its
surfaces answer with.

Held to the rules core's own are (codex_auto_resume/domain/vocabulary.py): one StrEnum per
list, a member is its value, and its name is its value in capitals with `-` as `_`
(advanced/tests/test_advanced_state.py). A word no list here holds is never stored: the tables a
decision reads refuse it, and the journal writes "other" in its place.

Pure: nothing here but the enums.
"""
from __future__ import annotations

from enum import StrEnum


class CapabilityKind(StrEnum):
    """What a capability is. A ROUTE answers at plug points: core asks it, and what it changes core
    carries out, under its ceilings. An ACTION answers at no point: core never asks it, it sends
    nothing to Codex and spends no unit, and only a person, in the Dashboard, starts what it does
    (a compatibility report, written and sent only when they say so)."""
    ROUTE = "route"
    ACTION = "action"


class ArmingState(StrEnum):
    """Where one capability stands. OFF is where every capability starts, and the only state
    anything but a person in the Dashboard can move one to."""
    OFF = "off"
    SHADOW = "shadow"                        # "Watch first": asked, journalled, never acts
    ARMED = "armed"


class Actor(StrEnum):
    """Who, or what, moved a capability's state."""
    DASHBOARD = "dashboard"                  # a person, in the Dashboard: the one way on
    MCP = "mcp"
    TRAY = "tray"
    CARD = "card"
    TRIPWIRE = "tripwire"
    EDITION_ENTRY = "edition_entry"          # the installer entered the advanced edition
    ENGINE_CHANGE = "engine_change"          # Codex is not the version the person agreed to


class OffReason(StrEnum):
    """Why a capability that was on is off."""
    DISARMED = "disarmed"                    # a person turned it off
    ALL_OFF = "all_off"                      # "All advanced features off"
    EDITION_ENTERED = "edition_entered"
    ENGINE_CHANGED = "engine_changed"
    # The tripwires (TRIPWIRES): something the capability did, or what it stands on, went wrong.
    SUBMISSION_UNKNOWN = "submission_unknown"
    LOCAL_CHECK_FAILED = "local_check_failed"
    FAILED_HERE = "failed_here"
    INCOMPATIBLE = "incompatible"
    HOOK_EXCEPTION = "hook_exception"
    STATEMENT_CHANGED = "statement_changed"
    MEASUREMENT_FAILED = "measurement_failed"
    # A continuation it sent once more was found twice in Codex's history (v0.6.14, stage 3b): the
    # harm a resend risks. It turns off what sent it again whether or not it is kept on - the
    # once-more capability, or Keep on's Send again alone (arming.py).
    DUPLICATE_SEEN = "duplicate_seen"
    # A conversation queued for opening was opened and Codex did not run the item within core's delivery window
    # (v0.6.15-beta, queue_for_open): what M1 measured did not hold on this Codex.
    NOT_DELIVERED_ON_OPEN = "not_delivered_on_open"
    # A capability this one requires (registry.CapabilityDef.requires) is not on now - turned off, watched, read
    # down by an administrator's policy, or its compatibility failed here (v0.6.16-beta.3): a capability is only as
    # on as what it needs.
    REQUIREMENT_OFF = "requirement_off"
    # A continuation sent to a conversation another Codex session held - a terminal's, VS Code's - was taken back
    # because that session did not take it within core's delivery window (v0.6.16-beta.4, other_sessions): what M5
    # measured did not hold on this Codex.
    NOT_DISPATCHED_BY_SESSION = "not_dispatched_by_session"
    # Codex refused a turn started with no input (v0.6.16-beta.4, silent_continuation): what M3B measured did not
    # hold on this Codex.
    REFUSED_BY_CODEX = "refused_by_codex"


TRIPWIRES = frozenset({OffReason.SUBMISSION_UNKNOWN, OffReason.LOCAL_CHECK_FAILED,
                       OffReason.FAILED_HERE, OffReason.INCOMPATIBLE, OffReason.HOOK_EXCEPTION,
                       OffReason.STATEMENT_CHANGED, OffReason.MEASUREMENT_FAILED,
                       OffReason.DUPLICATE_SEEN, OffReason.NOT_DELIVERED_ON_OPEN, OffReason.REQUIREMENT_OFF,
                       OffReason.NOT_DISPATCHED_BY_SESSION, OffReason.REFUSED_BY_CODEX})
# What a capability kept on (KeepOn, K8) notes instead of turning off, most serious first: the order
# in which one notice gives way to another (state/arming.py, note_kept). A notice only ever rises.
KEPT_NOTICES = (OffReason.DUPLICATE_SEEN, OffReason.STATEMENT_CHANGED, OffReason.FAILED_HERE,
                OffReason.LOCAL_CHECK_FAILED, OffReason.INCOMPATIBLE, OffReason.MEASUREMENT_FAILED,
                OffReason.NOT_DELIVERED_ON_OPEN, OffReason.NOT_DISPATCHED_BY_SESSION, OffReason.REFUSED_BY_CODEX,
                OffReason.REQUIREMENT_OFF,
                OffReason.ENGINE_CHANGED,
                OffReason.SUBMISSION_UNKNOWN, OffReason.HOOK_EXCEPTION)


class ArmingWarning(StrEnum):
    """What a capability's statement warns of, above its five fields, before a person turns it
    on or watches it (arming.warnings_for). A warning never refuses: the person reads it, and
    turning the capability on is their confirmation of every warning shown, which is stored
    beside the state. What stands behind a warning getting worse afterwards - one the person did
    not confirm appearing - is a tripwire's, as it always was (arming.standing). The owner's
    rule of 2026-09-26, which replaced decision C7's refusals."""
    MEASUREMENT_FAILED = "measurement_failed"  # a measurement its route rests on failed
    UNMEASURED = "unmeasured"                # ... has no pass or fail for the Codex in force
    FAILED_HERE = "failed_here"              # what it stands on failed a local check here
    INCOMPATIBLE = "incompatible"            # the Compatibility Registry's data says incompatible
    LOCAL_CHECK_FAILED = "local_check_failed"  # a local check found it incompatible
    COMPAT_UNKNOWN = "compat_unknown"        # nothing is known of it for this Codex
    ENGINE_UNKNOWN = "engine_unknown"        # no Codex version to acknowledge


class Refusal(StrEnum):
    """Why a request to move a capability, or the ceiling, was refused. Of these, only the three
    policy words say a capability may not be on; every other one says the request was not the
    person's own, current confirmation, which the Dashboard can ask for again."""
    UNKNOWN_CAPABILITY = "unknown_capability"
    NOT_THE_DASHBOARD = "not_the_dashboard"
    INVALID_REQUEST = "invalid_request"
    STALE_GENERATION = "stale_generation"    # something changed since the Dashboard looked
    STALE_REVISION = "stale_revision"        # the statement read is not the current one
    STATEMENT_INCOMPLETE = "statement_incomplete"
    FORBIDDEN_BY_POLICY = "forbidden_by_policy"
    NOT_ALLOWED_BY_POLICY = "not_allowed_by_policy"
    SHADOW_FORCED_BY_POLICY = "shadow_forced_by_policy"
    # What the person confirmed - the statement's warnings, or the Codex version - is not what
    # holds now: something changed after the Dashboard showed it. Shown again, it can be
    # confirmed at once; it never says the capability cannot be turned on.
    STALE_CONFIRMATION = "stale_confirmation"
    STATE_UNAVAILABLE = "state_unavailable"
    # Keep on (v0.6.14, K8) for a capability that is not on or watched: there is nothing to keep on.
    NOT_ON = "not_on"
    # A capability's own choices and rules (v0.6.14, state/choices.py): a value it does not offer,
    # and each way a rule for Codex's error codes is refused.
    OPTION_INVALID = "option_invalid"
    RULE_SHAPE = "rule_shape"                # not letters and digits, starting with a letter, <= 64
    RULE_KNOWN = "rule_known"                # a code the product already classifies
    RULE_DECISION = "rule_decision"          # a code that may name a person's decision
    RULE_RANGE = "rule_range"                # status numbers outside 100-599, or backwards
    RULE_OVERLAP = "rule_overlap"            # another rule covers this code and these numbers
    RULES_FULL = "rules_full"                # ten rules already
    UNKNOWN_RULE = "unknown_rule"
    # The reset actions (v0.6.14, state/resets.py): a window or a count of resets that is not one on offer;
    # as many rules waiting as may; a message the check refuses or too long; one waiting in that conversation
    # already; one being sent, which Cancel no longer reaches; and a message for a conversation switched off.
    OCCASION_INVALID = "occasion_invalid"
    RESETS_FULL = "resets_full"
    MESSAGE_REFUSED = "message_refused"
    ALREADY_SCHEDULED = "already_scheduled"
    BEING_SENT = "being_sent"
    CONVERSATION_OFF = "conversation_off"
    # Stage 3c (v0.6.15-beta, state/prompts.py, state/continuations.py): a prompt the check refuses or too long;
    # twenty waiting, or five in that conversation; one that waits for the one before it where there is none; and
    # a count of continuations to keep going that is not one on offer.
    PROMPT_REFUSED = "prompt_refused"
    QUEUE_FULL = "queue_full"
    DEPENDENCY_UNKNOWN = "dependency_unknown"
    KEEP_COUNT_INVALID = "keep_count_invalid"
    # Turning a capability on with its requirements in the one confirmation (v0.6.16-beta.3): the `also` list did
    # not carry exactly the requirements that are off, or one of them was refused its own confirmation.
    REQUIREMENT_REFUSED = "requirement_refused"
    # A requirement's compatibility grade is Failed here on this PC: like a policy on it, it keeps the dependent off,
    # whatever is confirmed - the owner's rule for `requires`.
    REQUIREMENT_FAILED_HERE = "requirement_failed_here"
    # Keep it on (v0.6.16-beta.4) for a capability whose compatibility is Failed here: never kept on that way.
    FAILED_HERE = "failed_here"
    # A person's own wording the custom continuation text's checks refuse, or a key the capability does not keep.
    WORDING_INVALID = "wording_invalid"
    # v0.6.16-beta.4 (j): a near-limit percentage out of order - a window's warning above its wrap-up, or the wrap-up at
    # or above the stop its words ask for.
    OPTION_ORDER = "option_order"


class JournalCode(StrEnum):
    """What the advanced journal says happened. A capability's own codes are written after its
    prefix (registry.CapabilityDef.codes); anything else is OTHER."""
    ARMED = "armed"
    WATCHED = "watched"                      # moved to shadow
    DISARMED = "disarmed"
    ALL_OFF = "all_off"
    TRIPPED = "tripped"
    RESET = "reset"                          # turned off by an edition entry or a Codex change
    WOULD_HAVE = "would_have"                # a watched capability's answer, not taken
    ACTED = "acted"                          # an armed capability's answer, taken
    CEILING = "ceiling"                      # an armed capability's answer, not taken: no unit left
    # v0.6.17 (issue #42): two capabilities' answers for one record that cannot both be carried (runtime.CONFLICTS):
    # this one stood aside for the other, which the line's answer names - a split; each serves its own cases.
    OVERRULED = "overruled"
    CEILING_CHANGED = "ceiling_changed"
    OPTION_CHANGED = "option_changed"        # a capability's own choice, set in the Dashboard
    RULE_ADDED = "rule_added"
    RULE_REMOVED = "rule_removed"
    # Keep on (v0.6.14, K8): set and let go in the Dashboard, and what a kept-on capability noted
    # instead of turning itself off - once each time its notice rises, never once a tick.
    KEEP_ON = "keep_on"
    KEEP_ON_OFF = "keep_on_off"
    KEPT = "kept"
    # Keep on's Send again let go while Keep on stays (v0.6.14): by the person, or by a continuation it
    # sent again found twice.
    SEND_AGAIN_OFF = "send_again_off"
    OTHER = "other"


class RecordState(StrEnum):
    """An advanced record's state: only what the claim ledger counts."""
    WAITING = "waiting"
    IN_FLIGHT = "in_flight"
    FINISHED = "finished"
    CANCELLED = "cancelled"


class OverrideKind(StrEnum):
    """What a capability asks of one standard record, keyed by its interruption id."""
    FORCE_ONCE = "force_once"
    EARLY_RESET = "early_reset"
    CAPACITY_LADDER = "capacity_ladder"
    RESEND_ONCE = "resend_once"
    # v0.6.15-beta: a continuation queued for when its conversation is opened, paid for in the claim - once for
    # each interruption, so one released from that queue is never queued for opening again.
    QUEUE_FOR_OPEN = "queue_for_open"


class OptionKey(StrEnum):
    """A choice a capability offers a person (registry.Option), stored in `options` by this key."""
    ATTEMPTS = "attempts"                    # how many tries a task gets
    CEILING_HOURS = "ceiling_hours"          # for how long, in hours on the clock, it keeps trying
    # v0.6.15-beta: how many sends may wait for their receipts at once (parallel_dispatch, 2 to 4), and how many
    # days a continuation is kept in Codex's queue for when its conversation is opened (queue_for_open, 3 to 7).
    WORKERS = "workers"
    DAYS = "days"
    # v0.6.16-beta.3 (issue #29), each a person's own choice: how often the usage meter reads (minutes), and for
    # each of the five-hour and the weekly window the percentage it warns at, wraps up at and pauses at - and the
    # wrap-up's wording (1 short, 2 standard, 3 detailed).
    POLL_MINUTES = "poll_minutes"
    WARN_FIVE_HOUR = "warn_five_hour"
    WARN_WEEKLY = "warn_weekly"
    WRAP_FIVE_HOUR = "wrap_five_hour"
    WRAP_WEEKLY = "wrap_weekly"
    WRAP_STYLE = "wrap_style"
    PAUSE_FIVE_HOUR = "pause_five_hour"
    PAUSE_WEEKLY = "pause_weekly"
    # v0.6.16-beta.4 (the owner's additions to issue #29), each 1 on or 2 off where it is a switch: each window acted
    # on or not, the stop percentage the wrap-up's words ask Codex to stop at in each window (a request, apart from
    # the forced stop's own, PAUSE_*), whether the words carry the reset time, and one continuation after the reset.
    WINDOW_FIVE_HOUR = "window_five_hour"
    WINDOW_WEEKLY = "window_weekly"
    STOP_WORDS_FIVE_HOUR = "stop_words_five_hour"
    STOP_WORDS_WEEKLY = "stop_words_weekly"
    WRAP_RESET_TIME = "wrap_reset_time"
    WRAP_AFTER_RESET = "wrap_after_reset"
    # v0.6.18: not a person's choice - no capability offers it as one (registry.Option), so `options` never reads it and
    # set_option refuses it - but a time a capability's own code keeps beside its choices (state/choices.py, `stamp`):
    # when the weekly update check last ran (engine/updatecheck.py), in whole Unix seconds.
    LAST_CHECK = "last_check"
    # and, beside it, the newest version a check offered and not yet put away (engine/updatecheck.encode), and when it
    # was found.
    OFFERED_VERSION = "offered_version"
    OFFERED_AT = "offered_at"
    # v0.6.19 (issue #50; before the groundwork's block, which ends the list): early_reset's own times, for the line on
    # Pending - when it last read usage early, when a reading found usage, when two readings lifted a limit, and when
    # a person last asked for a reading now (a Retry now or a Rescan, control/earlycheck.py).
    CHECKED_AT = "checked_at"
    AVAILABLE_AT = "available_at"
    LIFTED_AT = "lifted_at"
    CHECK_ASKED = "check_asked"
    # and (the review of 2026-10-24) when a probe last found usage available - so the line tells that reading, and what
    # it continued, even once the recoveries it continued wait no more.
    FOUND_AT = "found_at"
    # v0.6.19 (the groundwork, plans/v0619-design/D-groundwork.md), added in one block so the stage's writers never edit
    # this list at once. A person's choices: how many days the analytics keep (usage_analytics), how often the status
    # feed is read in minutes (status_feed), which events are pushed (push_notices: a bit set of CourierEvent's, in its
    # order), each push channel on or off, the loopback API's port (local_api), how long a conversation may sit unopened
    # before it is opened and whether Codex is started to open it (open_to_send), how many minutes before a reset the PC
    # is woken (wake_for_reset), and the crash restarts' cap (crash_restart: fixed at 3, kept as a stamp only). And the
    # times a capability's own code keeps (stamps): the last token ingest, feed read and fleet write.
    ANALYTICS_DAYS = "analytics_days"
    FEED_MINUTES = "feed_minutes"
    PUSH_EVENTS = "push_events"
    NTFY = "ntfy"
    WEBHOOK = "webhook"
    TELEGRAM = "telegram"
    EMAIL = "email"
    API_PORT = "api_port"
    OPEN_IDLE_MINUTES = "open_idle_minutes"
    OPEN_START_CODEX = "open_start_codex"
    WAKE_LEAD_MINUTES = "wake_lead_minutes"
    RESTART_CAP = "restart_cap"
    LAST_INGEST = "last_ingest"
    LAST_FEED = "last_feed"
    LAST_FLEET_WRITE = "last_fleet_write"


class WordingKey(StrEnum):
    """A person's own wording a capability keeps (v0.6.16-beta.4, state `wordings`): text, never logged, checked as
    the custom continuation text is (continuation.MAX_CUSTOM_LENGTH)."""
    WRAP_CUSTOM_FIVE_HOUR = "wrap_custom_five_hour"
    WRAP_CUSTOM_WEEKLY = "wrap_custom_weekly"
    # v0.6.19 (fleet_view): this PC's alias among the person's PCs, and the folder their status files are shared in -
    # which `wordings` holds since it was freed of the CHECK on its keys (advanced state version 8).
    FLEET_ALIAS = "fleet_alias"
    FLEET_FOLDER = "fleet_folder"


class KeepOn(StrEnum):
    """What a person chose, in the Dashboard, to keep a capability on through (v0.6.14, the owner's
    K8): stored in `options` beside its own choices, one row for each, none for none - and every row
    taken away by any move to off. Not a capability's own choice: every capability may be kept on."""
    KEEP_ON = "keep_on"                      # it does not turn itself off; what would have, is noted
    # With Keep on alone (v0.6.14): a continuation it paid for that cannot be proven to have arrived
    # is sent once more, under the once-more capability's rules (engine/oncemore.py), where the policy
    # admits that capability too.
    SEND_AGAIN = "send_again"


class Ceiling(StrEnum):
    """Which ceiling left no unit to spend."""
    CAPABILITY_DAY = "capability_day"
    CONVERSATION_DAY = "conversation_day"
    GLOBAL_HOUR = "global_hour"


class Field(StrEnum):
    """The five fields of a capability's statement, in the order a person reads them."""
    DOES = "does"                            # What it does
    INSTEAD = "instead"                      # What the standard edition does instead
    DEPARTS = "departs"                      # Standards it departs from
    RISKS = "risks"                          # What can go wrong
    STOP = "stop"                            # How to stop it


class BridgeCommand(StrEnum):
    """The bridge commands this edition answers (P10): the Dashboard's, and only in the bridge's
    long-lived form, which is the one the Dashboard talks to.

    `MEASURE` is the one a person runs by hand, on a throwaway conversation, to find whether a
    capability can work on this Codex (measure.py). It is the Dashboard's like the rest; nothing
    runs it unless the person asks, and no MCP tool exposes it."""
    ADVANCED_LIST = "advanced-list"
    # The words of the Dashboard's Advanced features page in the person's language - its own, the
    # capabilities' names and the three states' (statement.Catalogs.words) - which the page is
    # built from once this edition has answered: the window's own catalog is core's, and holds
    # none of them.
    ADVANCED_WORDS = "advanced-words"
    ADVANCED_STATEMENT = "advanced-statement"
    ADVANCED_ARM = "advanced-arm"
    ADVANCED_DISARM = "advanced-disarm"
    ADVANCED_DISARM_ALL = "advanced-disarm-all"
    ADVANCED_CEILING = "advanced-ceiling"
    MEASURE = "measure"
    # After a probe leaves a verdict blocked - it saw what the harness could see and left the
    # rest to a person to do in the Codex app - the person records the outcome with this. It
    # appends a pass or a fail, and one closed note code, to the newest blocked record of that
    # measurement for the same Codex version (measure.py, evidence.complete). Content-free, the
    # Dashboard's like MEASURE, and reached by no MCP tool.
    MEASURE_VERDICT = "measure-verdict"
    # A capability's own choices and the rules for Codex's error codes (v0.6.14, state/choices.py): a
    # choice set, the rules read, one added, one removed, and the samples of what nothing classified
    # read - the Dashboard's like the rest, each write against the generation the page read, and
    # reached by no MCP tool.
    ADVANCED_OPTION = "advanced-option"
    ADVANCED_RULES = "advanced-rules"
    ADVANCED_RULE_ADD = "advanced-rule-add"
    ADVANCED_RULE_REMOVE = "advanced-rule-remove"
    ADVANCED_SAMPLES = "advanced-samples"
    # Keep on (v0.6.14, K8): set or let go for one capability that is on or watched, the Dashboard's
    # alone, after its warning, against the generation the page read; no MCP tool reaches it.
    ADVANCED_KEEP_ON = "advanced-keep-on"
    # v0.6.16-beta.4: a capability's own wordings read, and one set or taken away (the wrap-up's Custom text) - the
    # Dashboard's alone, against the generation the page read; no MCP tool reaches them.
    ADVANCED_WORDINGS = "advanced-wordings"
    ADVANCED_WORDING = "advanced-wording"
    # Send now (v0.6.14): a person's request that one waiting recovery go at the watcher's next look,
    # by its interruption id, the Dashboard's alone while Send now is on; no MCP tool reaches it.
    ADVANCED_SEND_NOW = "advanced-send-now"
    # The watch log (v0.6.14, watchlog.py): what a watched capability would have done, by its id -
    # read-only, the Dashboard's; no MCP tool reaches it.
    ADVANCED_WATCH_LOG = "advanced-watch-log"
    # The reset actions (v0.6.14, control/resets.py): the rules and messages read, one added, one cancelled, one held
    # over a gap let go on, and a reset credit used now - the Dashboard's alone, against the generation the page
    # read; no MCP tool reaches any of them.
    ADVANCED_RESETS = "advanced-resets"
    ADVANCED_RESET_ADD = "advanced-reset-add"
    ADVANCED_RESET_CANCEL = "advanced-reset-cancel"
    ADVANCED_RESET_GO_ON = "advanced-reset-go-on"
    ADVANCED_CREDIT_NOW = "advanced-credit-now"
    # v0.6.15-beta: keep going (control/keepgoing.py) - the conversations kept going read, one picked, one stopped.
    ADVANCED_KEEP_GOING = "advanced-keep-going"
    ADVANCED_KEEP_GOING_SET = "advanced-keep-going-set"
    ADVANCED_KEEP_GOING_STOP = "advanced-keep-going-stop"
    # and the prompt queue (control/prompts.py): the prompts read, one added, one cancelled, one held let go on.
    ADVANCED_PROMPTS = "advanced-prompts"
    ADVANCED_PROMPT_ADD = "advanced-prompt-add"
    ADVANCED_PROMPT_CANCEL = "advanced-prompt-cancel"
    ADVANCED_PROMPT_GO_ON = "advanced-prompt-go-on"
    # The compatibility report (report/flow.py): write it, save it where the person chooses, check what
    # sending would write, send it, and read how one of the first, third or fourth - each a job this
    # process holds - is getting on. Like the rest, only the Dashboard's; no MCP tool reaches any of them.
    ADVANCED_REPORT_BUILD = "advanced-report-build"
    ADVANCED_REPORT_SAVE = "advanced-report-save"
    ADVANCED_REPORT_CHECK = "advanced-report-check"
    ADVANCED_REPORT_SEND = "advanced-report-send"
    ADVANCED_REPORT_JOB = "advanced-report-job"
    # v0.6.16-beta.4: a person's Stop of a turn run here (engine/headless.py) - the Dashboard's alone, never MCP.
    ADVANCED_HEADLESS_STOP = "advanced-headless-stop"
    # v0.6.19: the Chat page's (control/chat.py) - the Dashboard's alone, never MCP.
    ADVANCED_CHAT_READ = "advanced-chat-read"
    ADVANCED_CHAT_SEND = "advanced-chat-send"
    ADVANCED_CHAT_CANCEL = "advanced-chat-cancel"
    # v0.6.19 (issue #50): early_reset's probe a person's Retry now or Rescan asks for (control/earlycheck.py) - the
    # Dashboard's alone, never MCP.
    ADVANCED_EARLY_CHECK = "advanced-early-check"
    # v0.6.19 (the groundwork): every command the stage's designs name, in one block, each the Dashboard's alone and
    # reached by no MCP tool. Until the capability that answers one is built, the bridge passes it over as it passes a
    # command this edition does not have (surfaces.UNANSWERED). The analytics' aggregates and their CSV
    # (usage_analytics); the courier's card read, one channel saved or forgotten, a test notice, and the status feed read
    # now (push_notices, status_feed); the loopback API's state and a new token, Telegram's pairing started and its state,
    # the other PCs read and this PC's alias and folder saved (local_api, telegram_remote, fleet_view); a queued prompt
    # edited and the done ones cleared (#50); the account read and a switch asked for (account_switch).
    ADVANCED_ANALYTICS = "advanced-analytics"
    ADVANCED_ANALYTICS_CSV = "advanced-analytics-csv"
    ADVANCED_COURIER = "advanced-courier"
    ADVANCED_COURIER_SAVE = "advanced-courier-save"
    ADVANCED_COURIER_FORGET = "advanced-courier-forget"
    ADVANCED_COURIER_TEST = "advanced-courier-test"
    ADVANCED_FEED_REFRESH = "advanced-feed-refresh"
    ADVANCED_API = "advanced-api"
    ADVANCED_API_TOKEN_NEW = "advanced-api-token-new"
    ADVANCED_REMOTE_PAIR_START = "advanced-remote-pair-start"
    ADVANCED_REMOTE_PAIR_STATE = "advanced-remote-pair-state"
    ADVANCED_FLEET = "advanced-fleet"
    ADVANCED_FLEET_SAVE = "advanced-fleet-save"
    ADVANCED_PROMPT_EDIT = "advanced-prompt-edit"
    ADVANCED_PROMPTS_CLEAR_DONE = "advanced-prompts-clear-done"
    ADVANCED_ACCOUNT = "advanced-account"
    ADVANCED_ACCOUNT_SWITCH = "advanced-account-switch"


class Measurement(StrEnum):
    """What the owner measures on a real machine for a capability whose route depends on it
    (measure.py and the roadmap's M-list). Each writes one content-free record to
    docs/evidence/live/; what a release ships of them is measured.py, and a capability whose
    measurement failed or was never made for the Codex in force says so in its statement as a
    warning (ArmingWarning), never by being withheld."""
    M1 = "m1"                                # a notLoaded queue item is delivered on open
    M2 = "m2"                                # thread/goal/set reaches a Desktop-loaded goal
    # A goal set active and a turn queued while the Desktop holds the conversation: the turn runs,
    # and the goal stays active and carries on after it (the owner, 2026-09-28; measure._m2b).
    M2B = "m2b"
    M3 = "m3"                                # an empty thread/queue/add is dispatched, correlatable
    M4 = "m4"                                # plugin Stop hooks run after a failed turn
    M5 = "m5"                                # TUI and IDE servers dispatch codex queue items
    M6 = "m6"                                # a headless turn with declined approvals
    M7 = "m7"                                # queued '/compact' text stays plain text
    MH = "mh"                                # the Desktop runs on a second CODEX_HOME
    MA = "ma"                                # the running app picks up an account logout+login
    MW = "mw"                                # re-proof of the WMI escape, with the job words
    # The settings panel beside a conversation, in the Codex app's right side panel (v0.6.14): the
    # engine keeps the panel's side-panel entrypoint and the side panel's New tab lists the panel and
    # opens it (MP1); Open beside the chat moves it into a side panel tab, and closing the tab brings
    # it back (MP2); beside the chat it calls its tools and reads again on return, and nothing
    # appears in the conversation (MP3). Each is what a person sees in the app; MP1 alone reads.
    MP1 = "mp1"
    MP2 = "mp2"
    MP3 = "mp3"
    # Reset credits (v0.6.14): the usage read carries the count of reset credits, takes the param that
    # leaves their details out, and keeps a running window's reset time still, and a window opens with
    # its first use after a reset (MU); a consume with no credit to spend spends nothing (MN); and at a
    # real limit one consume resets it, spends exactly one credit, and asked again with its key spends no
    # second one (MR). Each is what the reset actions' routes rest on (engine/credits.py).
    MU = "mu"
    MN = "mn"
    MR = "mr"
    # v0.6.15-beta: two to four throwaway conversations sent to at once through core's backend - each receipt
    # matched, each marker in its own history once and nowhere else (parallel_dispatch).
    MQ = "mq"
    # A turn that ended with no reply, when Codex produces one: its item kinds (closed words) and its final agent item
    # absent (empty_response).
    ME = "me"
    # A throwaway parent whose subagent fails: the spawn edge is there, and the subagent's latest turn can be told as a
    # closed kind (subagent_parent's 5b).
    MS = "ms"
    # A throwaway conversation with a plan: the newest plan item found and its steps' statuses read (keep_going).
    MK = "mk"
    # One message queued while a turn runs in a throwaway conversation: delivered once, after that turn ended
    # (prompt_queue's after_turn).
    MT = "mt"
    # v0.6.16-beta.3 - the three probes for what stop-now and send-now would need, each read-only, no live run
    # from this product (measure.py). MIPC: whether the Desktop's own IPC pipe \\.\pipe\codex-ipc is reachable -
    # it never writes a start, an interrupt or a message; the person confirms whether a turn the app holds could be
    # driven through it. MAWS: whether a shared app-server is a setting Codex documents (CODEX_APP_SERVER_WS_URL or a
    # shared-backend switch), read from the engine's own help. MCLOUD: whether a `codex cloud` command offers a
    # supported, read-only way to read a cloud task's state. None of the three drives a turn; stop-now and send-now
    # wait on MIPC's answer.
    MIPC = "mipc"
    MAWS = "maws"
    MCLOUD = "mcloud"
    # v0.6.16-beta.4 (stage 4). With Codex closed: a headless turn on the thread's own saved settings, a command
    # run under them, every approval declined (M6B); thread/compact/start on our own server, and the turn it leaves
    # (MX); a model override at resume lasting the session only, or a restore by thread/settings/update read back
    # (MF); a turn started with no input, proven by its client id (M3B); and Codex's own config writes on a scratch
    # home - read back, removed, a stale version refused (MB). With Codex open: a terminal's TUI and VS Code's
    # conversations - their source, originator and holder (MO); a person's own /compact in the app (MXA); a message
    # queued with no marker showing as the person's own (MC1); and which of the history and the rollout says first
    # that a turn started and ended (MC2).
    M6B = "m6b"
    MO = "mo"
    MX = "mx"
    MXA = "mxa"
    MF = "mf"
    M3B = "m3b"
    MB = "mb"
    MC1 = "mc1"
    MC2 = "mc2"
    # v0.6.17 (issue #42): one message added with no marker, under a client id, to a throwaway conversation the
    # Desktop does not hold, stays queued, is taken when the person opens it there, and its delivered message is found
    # in Codex's history by that client id - the proof marker-free continuation uses on a loaded conversation. What
    # marker-free continuation needs to carry a continuation queued for opening (engine/markerfree.carries).
    MQO = "mqo"
    # v0.6.17: two to four messages added at once, each under its own client id, to as many throwaway conversations
    # the Desktop does not hold - whether every add is accepted and each lands in its own conversation only (what
    # pooling several sends through one channel rests on, parallel_dispatch).
    MQP = "mqp"
    # v0.6.17: a throwaway conversation the Desktop does not hold, with its goal set active and a continuation queued
    # for opening, opened by the person - whether two turns then run (the goal's and the queued one) or one (M1 and
    # M2 together, which no measurement made; goal_continuation beside queue_for_open rests on it).
    MQG = "mqg"
    # v0.6.19 (the groundwork, plans/v0619-design/D-groundwork.md section 5), made while the stage is built. MTOK: a
    # throwaway conversation's rollout keeps per-turn token totals of the five kinds, never decreasing, and the history's
    # tokens_used agrees (usage_analytics). MOPEN: a conversation the app does not hold loads within ten seconds of its
    # link being opened (open_to_send). MAL: a `codex logout` and `codex login` in a terminal reach the running app
    # without a restart (account_switch). MWAKE: a wake timer wakes this PC from sleep (wake_for_reset). MHK: Codex's
    # generated schema has a Stop event for plugin hooks, and the feature is there (stop_hook_continuation). M4B: a
    # block from this edition's Stop hook continues the turn - its probe is the Stop hook's writer's to finish.
    MTOK = "mtok"
    MOPEN = "mopen"
    MAL = "mal"
    MWAKE = "mwake"
    MHK = "mhk"
    M4B = "m4b"


class ObservedWord(StrEnum):
    """The closed words a stage-4 measurement's observation may hold besides booleans and counts (v0.6.16-beta.4,
    evidence.CLOSED_WORDS): a thread's saved sandbox and approval policy and its reviewer, as Codex's schema names
    them; a conversation's source, thread source, history mode, originator and holder; and the buckets a span or a
    lag is kept in, and which of two came first - never a model, a name, a path or anything a turn said."""
    READONLY = "readOnly"
    WORKSPACEWRITE = "workspaceWrite"
    EXTERNALSANDBOX = "externalSandbox"
    DANGERFULLACCESS = "dangerFullAccess"
    UNTRUSTED = "untrusted"
    ON_FAILURE = "on-failure"
    ON_REQUEST = "on-request"
    NEVER = "never"
    GRANULAR = "granular"
    USER = "user"
    CLI = "cli"
    VSCODE = "vscode"
    EXEC = "exec"
    MCP = "mcp"
    PAGINATED = "paginated"
    CLI_ORIGINATOR = "cli_originator"
    IDE_ORIGINATOR = "ide_originator"
    DESKTOP = "desktop"
    APP = "app"
    SESSION = "session"
    NONE = "none"
    UNKNOWN = "unknown"
    OTHER = "other"
    UNDER_1S = "under_1s"
    S1_TO_5 = "s1_to_5"
    OVER_5S = "over_5s"
    UNDER_10S = "under_10s"
    UNDER_60S = "under_60s"
    UNDER_600S = "under_600s"
    OVER_600S = "over_600s"
    DB = "db"
    ROLLOUT = "rollout"
    SAME = "same"
    NEITHER = "neither"
    # v0.6.19: how long a conversation took to load once its link was opened (MOPEN), and what powered the PC (MWAKE).
    UNDER_2S = "under_2s"
    S2_TO_10 = "s2_to_10"
    OVER_10S = "over_10s"
    AC = "ac"
    BATTERY = "battery"


class RunEnd(StrEnum):
    """How a turn run here ended (v0.6.16-beta.4, codex/headless.py): it completed, failed or was interrupted - by a
    person's Stop, or the watcher leaving - by itself; its cap ended it; the Codex app started and it gave way (Q3);
    nothing was left to follow it (lost); or the conversation's saved settings were refused before anything started."""
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    CAPPED = "capped"
    YIELDED = "yielded"
    LOST = "lost"
    REFUSED_SETTINGS = "refused_settings"


class ChatState(StrEnum):
    """Where a message of the Dashboard's chat stands (v0.6.16-beta.4, state/chat.py): waiting to be handed to core,
    in flight - claimed and sent, watched - or finished, done or cancelled. Only one waiting holds its words."""
    WAITING = "waiting"
    IN_FLIGHT = "in_flight"
    DONE = "done"
    CANCELLED = "cancelled"


class ChatReason(StrEnum):
    """Why a chat message stands where it stands: Codex took it and its turn started (delivered); Codex did not take
    it within three minutes and it was taken back (not_taken); a Pause took it back (withdrawn); a person cancelled
    it; chat was turned off; its conversation was switched off; or what came of it cannot be proven (unknown)."""
    DELIVERED = "delivered"
    NOT_TAKEN = "not_taken"
    WITHDRAWN = "withdrawn"
    CANCELLED = "cancelled"
    TURNED_OFF = "turned_off"
    CONVERSATION_OFF = "conversation_off"
    UNKNOWN = "unknown"


class RuleState(StrEnum):
    """Where one of the reset actions' rules stands (state/resets.py): counting the resets or fills of its
    window, due (READY) and acting or asking, held until a person says go on, or finished - done, or
    cancelled. Only a message that is counting, due or held holds its words."""
    COUNTING = "counting"
    READY = "ready"
    HELD = "held"
    DONE = "done"
    CANCELLED = "cancelled"


class RuleReason(StrEnum):
    """Why a rule stands where it stands (state/resets.py), in the order a rule meets them."""
    ASK_FIRST = "ask_first"                  # due: a person's click spends the credit (MR, or their choice)
    COUNT_UNKNOWN = "count_unknown"          # due: how many credits there are cannot be read
    EXPIRY_UNKNOWN = "expiry_unknown"        # due: when they expire cannot be read (the owner's rule)
    BOUND = "bound"                          # due: two a day or seven a week spent already
    NO_METHOD = "no_method"                  # due: this Codex has no way to spend one
    NOTHING_WAITING = "nothing_waiting"      # due: no recovery waits for usage, so nothing is spent
    COUNT_GAP = "count_gap"                  # held: two readings further apart than the window
    WINDOW_GONE = "window_gone"              # held: Codex stopped reporting the window
    SPENT = "spent"
    NOTHING_TO_RESET = "nothing_to_reset"
    NO_CREDIT = "no_credit"
    LAPSED = "lapsed"                        # the window reset before anything was spent
    UNKNOWN = "unknown"                      # what came of it cannot be proven
    DELIVERED = "delivered"
    EXPIRED = "expired"
    NOT_STARTED = "not_started"
    BY_PERSON = "by_person"
    TURNED_OFF = "turned_off"
    CONVERSATION_OFF = "conversation_off"    # its conversation was switched off (H5)
    # v0.6.15-beta: edited by a person in Codex's queue, theirs now; its turn no longer the latest (a continuation);
    # taken back out of Codex's queue on a Cancel or a Pause; and Codex would not give it back, so it is left there.
    HANDED_OVER = "handed_over"
    SUPERSEDED = "superseded"
    WITHDRAWN = "withdrawn"
    WITHDRAW_REFUSED = "withdraw_refused"


class SpendOutcome(StrEnum):
    """What one consume of a reset credit came to (account/rateLimitResetCredit/consume), in this
    edition's words for Codex's four outcomes (codex/credits.OUTCOMES), and UNKNOWN for no answer, an
    answer of another shape, or none in time - which is never taken for any of the four."""
    RESET = "reset"                          # a credit was spent and the window reset
    NOTHING_TO_RESET = "nothing_to_reset"    # no window was one a credit resets
    NO_CREDIT = "no_credit"                  # no credit to spend
    ALREADY_REDEEMED = "already_redeemed"    # the same key had reset it already
    UNKNOWN = "unknown"


class GoalStatus(StrEnum):
    """A Codex goal's status, as goals_<N>.sqlite stores it (codex-rs state/goals_migrations:
    thread_goals.status, a CHECK of exactly these six). The goal continuation reads the status
    and nothing the goal says (codex/goals.py); a word outside these is no status it acts on."""
    ACTIVE = "active"
    PAUSED = "paused"
    BLOCKED = "blocked"
    USAGE_LIMITED = "usage_limited"
    BUDGET_LIMITED = "budget_limited"
    COMPLETE = "complete"


class Verdict(StrEnum):
    """What a measurement found, in the live-acceptance record's own words (scripts/live_evidence)."""
    PASS = "pass"
    FAIL = "fail"
    BLOCKED = "blocked"                      # it could not be reached to be measured


class NoteCode(StrEnum):
    """The closed words a person completing a blocked measurement may leave, and no others
    (evidence.complete). They say what the person saw in the Codex app when they did the step
    the harness could not do for them, and nothing more - never a sentence, never an id. Which
    code fits which measurement is in the runbook; the record only ever holds the code.

    A completion is a pass or a fail, so a pass carries AS_EXPECTED and a fail one of the rest.
    PRECONDITION_UNMET is for a step whose world this machine could set up but did not behave -
    a step this machine cannot set up at all (no IDE server, no second sign-in) stays blocked
    with its probe's note, never completed."""
    AS_EXPECTED = "as_expected"              # it behaved as the capability needs (a pass)
    NOT_AS_EXPECTED = "not_as_expected"      # it did not (a fail)
    PARTIAL = "partial"                      # some of it, not all (a fail)
    PRECONDITION_UNMET = "precondition_unmet"  # the step's world would not come up here (a fail)
    INCONCLUSIVE = "inconclusive"            # it ran but did not settle the question (a fail)


NOTE_FOR_PASS = frozenset({NoteCode.AS_EXPECTED})
NOTE_FOR_FAIL = frozenset(NoteCode) - NOTE_FOR_PASS


class ReportRefusal(StrEnum):
    """Why the compatibility report did not do what the Dashboard asked (report/). The first ten are
    the reader's (report/records.ReadRefusal), the next four the file's (report/document.
    DocumentRefusal); the rest are the flow's, the save's and GitHub's, through gh. A word, never an
    id, a path, a login or text."""
    NO_STATE = "no_state"
    STATE_NEWER = "state_newer"
    STATE_OLDER = "state_older"
    STATE_UNREADABLE = "state_unreadable"
    STATE_BUSY = "state_busy"
    LEDGER_NEWER = "ledger_newer"
    LEDGER_UNREADABLE = "ledger_unreadable"
    NO_ENGINE_VERSION = "no_engine_version"
    VERSION_INVALID = "version_invalid"
    TOO_MANY_RECORDS = "too_many_records"
    LOGIN_INVALID = "login_invalid"
    LOGIN_RESERVED = "login_reserved"
    LOGIN_OWNER = "login_owner"
    TOO_LARGE = "too_large"
    NOT_ON = "not_on"                        # off: nothing of it may be done
    WATCHED = "watched"                      # watched: written, read and saved, never checked or sent
    PAUSED = "paused"                        # recovery is paused: nothing is checked or sent (K5)
    BUSY = "busy"                            # a report is being checked or sent, here or in another window
    UNKNOWN_BUILD = "unknown_build"          # no report this process wrote has that SHA-256
    CHANGED = "changed"                      # what sending would write is not what the person read
    WORD = "word"                            # the word typed was not exactly send
    FILE_EXISTS = "file_exists"
    SAVE_FAILED = "save_failed"
    GH_FAILED = "gh_failed"                  # gh could not be started, or GitHub refused a step
    GH_TIMEOUT = "gh_timeout"                # gh did not answer in time, and was ended
    GH_SPELLING = "gh_spelling"              # GitHub spells the login in other letters
    NOT_OPEN = "not_open"                    # the project is not taking reports yet
    ALREADY_FILED = "already_filed"
    PR_OPEN = "pr_open"                      # another report pull request of that login is open
    FORK_NAMED_OTHERWISE = "fork_named_otherwise"
    FORK_NOT_READY = "fork_not_ready"
    BASE_INVALID = "base_invalid"            # GitHub did not answer with the project's main as a commit


class ReportStatus(StrEnum):
    """Where one of the compatibility report's jobs stands, as advanced-report-job answers it."""
    RUNNING = "running"
    BUILT = "built"                          # written: the file, its SHA-256 and what it holds
    SAVED = "saved"
    CHECKED = "checked"                      # GitHub asked: every write sending would make
    WEB = "web"                              # gh cannot send it from here: the web's steps instead
    SENT = "sent"                            # the pull request is open, sent now or already
    PARTIAL = "partial"                      # stopped after some writes: what is on GitHub now
    REFUSED = "refused"                      # stopped before anything was written
    LOST = "lost"                            # a job this process does not hold: whether it was sent is unknown


class ReportWrite(StrEnum):
    """One write sending a report makes to GitHub, in the order it makes them; each is shown, with its
    name, before the person types send, and the send makes exactly those."""
    FORK_NEW = "fork_new"
    FORK_KEPT = "fork_kept"
    BRANCH_NEW = "branch_new"
    BRANCH_RESET = "branch_reset"
    FILE = "file"
    PR = "pr"


class WebReason(StrEnum):
    """Why a report has to be sent on the web: gh cannot send it from this PC."""
    NO_GH = "no_gh"
    GH_SIGNED_OUT = "gh_signed_out"
    GH_OTHER_LOGIN = "gh_other_login"


class McpTool(StrEnum):
    """The MCP tools this edition adds (P10). They read, or turn off; none turns anything on."""
    LIST_ADVANCED_CAPABILITIES = "list_advanced_capabilities"
    DISARM_ADVANCED_CAPABILITY = "disarm_advanced_capability"
    DISARM_ALL_ADVANCED = "disarm_all_advanced"


# ------------------------------------------------------------------ stage 3c (v0.6.15-beta)
class ContinuationKind(StrEnum):
    """What one of the edition's own continuations answers (state/continuations.py): a turn that ended with no reply,
    a subagent that stopped, or a conversation a person asked to keep going."""
    EMPTY_RESPONSE = "empty_response"
    SUBAGENT = "subagent"
    KEEP_GOING = "keep_going"
    # v0.6.16-beta.3 (issue #29): a conversation with a turn running asked to wrap up, once for each usage window
    # that reached the percentage a person chose (usage_wrap_up), sent while that turn is still the latest.
    WRAP_UP = "wrap_up"
    # v0.6.16-beta.4: one continuation when the window resets, to a conversation that was wrapped up or stopped and
    # then ended well - sent only while its turn is still the latest, final and with nothing after it.
    AFTER_RESET = "after_reset"


class ContinuationReason(StrEnum):
    """How one of the edition's own continuations ended, or why none was made (state/continuations.py)."""
    SENT = "sent"
    DELIVERED = "delivered"
    UNKNOWN = "unknown"
    SUPERSEDED = "superseded"
    HANDED_OVER = "handed_over"
    WITHDRAWN = "withdrawn"
    CHAIN_SPENT = "chain_spent"              # an empty reply's chain had its two continuations
    GOAL_LEFT = "goal_left"                  # a goal Codex keeps going, or blocked: left alone
    MENTIONED = "mentioned"                  # a subagent's stop told in the parent's own continuation (P4)
    TURNED_OFF = "turned_off"
    CONVERSATION_OFF = "conversation_off"


class KeepState(StrEnum):
    """Where a conversation a person asked to keep going stands (state/continuations.py keep_going)."""
    ON = "on"
    DONE = "done"


class KeepReason(StrEnum):
    """Why a conversation kept going stopped."""
    NO_PROGRESS = "no_progress"              # the last turn left nothing that counts as progress
    PLAN_DONE = "plan_done"                  # every step of its plan is completed
    COUNT_SPENT = "count_spent"              # the continuations a person allowed were used
    GOAL_ACTIVE = "goal_active"              # a goal is active: Codex goes on itself
    FAILED = "failed"                        # a failed turn is core's ordinary recovery, never this
    PLAN_UNREADABLE = "plan_unreadable"      # a plan item there whose steps cannot be read: stopped (fail closed)
    BY_PERSON = "by_person"
    TURNED_OFF = "turned_off"
    CONVERSATION_OFF = "conversation_off"


class PromptTrigger(StrEnum):
    """When a queued prompt goes (state/prompts.py): after the turn now running, at a time, or on a schedule."""
    AFTER_TURN = "after_turn"
    AT_TIME = "at_time"
    RECURRING = "recurring"


class PromptEvery(StrEnum):
    """How often a recurring prompt goes."""
    DAY = "day"
    WEEK = "week"


class PromptState(StrEnum):
    """Where a queued prompt stands: waiting for its time, due (READY) and being tried, held until a person says go on
    or cancel, or finished - done, or cancelled. Only one waiting, due or held holds its words."""
    WAITING = "waiting"
    READY = "ready"
    HELD = "held"
    DONE = "done"
    CANCELLED = "cancelled"


class PromptReason(StrEnum):
    """Why a queued prompt stands where it stands."""
    DELIVERED = "delivered"
    HANDED_OVER = "handed_over"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"                      # not sent a day after it fell due
    MISSED = "missed"                        # an occurrence that fell while nothing ran, counted as used
    DEPENDENCY_FAILED = "dependency_failed"  # the one before it did not arrive: held for a person
    BY_PERSON = "by_person"
    TURNED_OFF = "turned_off"
    TOO_LONG = "too_long"                    # over 2,000 characters once Longer messages was turned off
    CONVERSATION_OFF = "conversation_off"
    WITHDRAWN = "withdrawn"                  # taken back out of Codex's queue on a Cancel or a Pause
    WITHDRAW_REFUSED = "withdraw_refused"    # Codex would not give it back: left there, never sent again
    UNKNOWN = "unknown"
    # v0.6.19 (#50's send mode): a prompt that waits while a turn runs is not handed to core this tick, the latest turn
    # of its conversation still in progress.
    TURN_RUNNING = "turn_running"


# ------------------------------------------------------------------ v0.6.19 (the groundwork)
# The closed words the stage's capabilities store and journal, added in one block before any of them is built
# (plans/v0619-design/D-groundwork.md), so the parallel writers never edit one list at once and the stored format is
# fixed once: a later writer that needs a word this missed appends it in a block headed with its capability id.
class WhileRunning(StrEnum):
    """What a queued prompt does while a turn of its conversation runs (#50, state `prompts.while_running`): goes into
    Codex's queue as every prompt always did, or waits for that turn to end."""
    QUEUE = "queue"
    WAIT = "wait"


class CourierChannel(StrEnum):
    """Where a notice is pushed (push_notices, state `outbox`): each the person's own service, its address and secret
    in Credential Manager, never here."""
    NTFY = "ntfy"
    WEBHOOK = "webhook"
    TELEGRAM = "telegram"
    EMAIL = "email"


class CourierEvent(StrEnum):
    """What a pushed notice says happened - each one of core's notice kinds or one of this edition's, never free text
    (push_notices maps them 1:1, engine/push.py) - and the test notice a person sends from the card."""
    USAGE_LIMIT_DETECTED = "usage_limit_detected"
    RECOVERED = "recovered"
    FAILED = "failed"
    NEEDS_YOU = "needs_you"
    STOPPED_UNEXPECTEDLY = "stopped_unexpectedly"
    RESTARTED = "restarted"
    UPDATE_OFFERED = "update_offered"
    TEST = "test"


class OutboxState(StrEnum):
    """Where one pushed notice stands (state `outbox`): waiting to go, sent, or dropped after its tries."""
    WAITING = "waiting"
    SENT = "sent"
    DROPPED = "dropped"


class FeedWord(StrEnum):
    """What the status feed last said (status_feed, state `feed`): of the service, and of Codex in it."""
    OPERATIONAL = "operational"
    DEGRADED = "degraded"
    OUTAGE = "outage"
    UNKNOWN = "unknown"


class OpenOutcome(StrEnum):
    """What came of opening a conversation for a message to be sent (open_to_send, state `opens`): the link opened,
    the app then loaded it, it did not, or the open was refused."""
    OPENED = "opened"
    LOADED = "loaded"
    NOT_LOADED = "not_loaded"
    REFUSED = "refused"


class HookOutcome(StrEnum):
    """What the Stop hook did with a turn (stop_hook_continuation, state `hook_claims`): blocked its end with a
    continuation, let it pass, or was refused."""
    BLOCKED = "blocked"
    PASSED = "passed"
    REFUSED = "refused"


class PlanWord(StrEnum):
    """The plan the signed-in account is on, as Codex names it, or `other` (account_switch, state `account_seen`)."""
    FREE = "free"
    PLUS = "plus"
    PRO = "pro"
    TEAM = "team"
    BUSINESS = "business"
    ENTERPRISE = "enterprise"
    EDU = "edu"
    OTHER = "other"
