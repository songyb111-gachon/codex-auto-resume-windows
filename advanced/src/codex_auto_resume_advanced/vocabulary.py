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


TRIPWIRES = frozenset({OffReason.SUBMISSION_UNKNOWN, OffReason.LOCAL_CHECK_FAILED,
                       OffReason.FAILED_HERE, OffReason.INCOMPATIBLE, OffReason.HOOK_EXCEPTION,
                       OffReason.STATEMENT_CHANGED, OffReason.MEASUREMENT_FAILED})


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
    CEILING_CHANGED = "ceiling_changed"
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


class McpTool(StrEnum):
    """The MCP tools this edition adds (P10). They read, or turn off; none turns anything on."""
    LIST_ADVANCED_CAPABILITIES = "list_advanced_capabilities"
    DISARM_ADVANCED_CAPABILITY = "disarm_advanced_capability"
    DISARM_ALL_ADVANCED = "disarm_all_advanced"
