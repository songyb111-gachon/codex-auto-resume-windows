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


TRIPWIRES = frozenset({OffReason.SUBMISSION_UNKNOWN, OffReason.LOCAL_CHECK_FAILED,
                       OffReason.FAILED_HERE, OffReason.INCOMPATIBLE, OffReason.HOOK_EXCEPTION,
                       OffReason.STATEMENT_CHANGED})


class Refusal(StrEnum):
    """Why a request to move a capability, or the ceiling, was refused."""
    UNKNOWN_CAPABILITY = "unknown_capability"
    NOT_THE_DASHBOARD = "not_the_dashboard"
    INVALID_REQUEST = "invalid_request"
    STALE_GENERATION = "stale_generation"    # something changed since the Dashboard looked
    STALE_REVISION = "stale_revision"        # the statement read is not the current one
    STATEMENT_INCOMPLETE = "statement_incomplete"
    FORBIDDEN_BY_POLICY = "forbidden_by_policy"
    NOT_ALLOWED_BY_POLICY = "not_allowed_by_policy"
    SHADOW_FORCED_BY_POLICY = "shadow_forced_by_policy"
    NOT_PERMITTED = "not_permitted"          # compat.permits said no; its reason goes beside
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
    long-lived form, which is the one the Dashboard talks to."""
    ADVANCED_LIST = "advanced-list"
    ADVANCED_STATEMENT = "advanced-statement"
    ADVANCED_ARM = "advanced-arm"
    ADVANCED_DISARM = "advanced-disarm"
    ADVANCED_DISARM_ALL = "advanced-disarm-all"
    ADVANCED_CEILING = "advanced-ceiling"


class McpTool(StrEnum):
    """The MCP tools this edition adds (P10). They read, or turn off; none turns anything on."""
    LIST_ADVANCED_CAPABILITIES = "list_advanced_capabilities"
    DISARM_ADVANCED_CAPABILITY = "disarm_advanced_capability"
    DISARM_ALL_ADVANCED = "disarm_all_advanced"
