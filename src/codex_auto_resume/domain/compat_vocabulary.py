"""The compatibility registry's closed vocabularies: what it says of a capability, and why.

Out of `vocabulary.py` in v0.6.11, when that file reached its line budget, and unchanged: every
member here is the word it was, every list is `vocabulary.<Name>` as well as its own name here, and
`tests/test_vocabulary.py` holds these to every rule it holds the rest to. Pure: nothing here but
the enums.
"""
from __future__ import annotations

from enum import StrEnum


# ------------------------------------------------------------ the compatibility registry
class CompatState(StrEnum):
    """What the registry says of a capability, worst last in trust (compat.STATES)."""
    VERIFIED = "VERIFIED"
    CHECKED = "CHECKED"
    COMPATIBLE = "COMPATIBLE"
    FAILED_HERE = "FAILED_HERE"
    INCOMPATIBLE = "INCOMPATIBLE"
    UNKNOWN = "UNKNOWN"


class LocalResult(StrEnum):
    """What one local check found (compat.RESULTS; the Codex adapter's probes answer with it)."""
    PASS = "PASS"
    FAIL = "FAIL"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class Tier(StrEnum):
    """How a capability is offered: not a registry state (compat.TIERS)."""
    CONSERVATIVE = "conservative"
    ADVANCED = "advanced"
    EXPERIMENTAL = "experimental"
    UNSUPPORTED = "unsupported"


class CompatCheck(StrEnum):
    """Every local structural check, each grounded in the code path that relies on it (compat.CHECKS).
    None of them sends anything, starts `codex app-server`, or writes anywhere."""
    # E1 windows.Backend.engine_checks: the binary sits at the official, content-addressed
    #    %LOCALAPPDATA%\OpenAI\Codex\bin\<hex>\codex.exe.
    OFFICIAL_LOCATION = "official_location"
    # E2 `codex --version` runs and exits 0.
    VERSION_RUNS = "version_runs"
    # E5 config.discover_codex_exe: exactly one candidate passes (or one was named).
    SINGLE_CANDIDATE = "single_candidate"
    # E4 `codex queue --help` exits 0 and still offers the two flags the one interface
    #    windows.Backend.send drives needs.
    QUEUE_FLAGS = "queue_flags"
    # E6 source.DB_KINDS: the newest generation of each database has every column the
    #    read-only adapter reads. A missing column is a FAIL; no database is UNAVAILABLE.
    STATE_SCHEMA = "state_schema"
    HISTORY_SCHEMA = "history_schema"
    QUEUE_SCHEMA = "queue_schema"
    # E7 source.LocalSource.projection: thread_history_projection_state with
    #    next_rollout_byte_offset, which the freshness gate compares with the rollout file.
    PROJECTION_TABLE = "projection_table"
    # The rollout directory the reset hint and eligibility read (source._rollout_path).
    SESSIONS_DIRECTORY = "sessions_directory"
    # windows.Backend.loaded: the writer-lock directory, and the Restart Manager API that
    # inventories it without ever taking a lock.
    LOCK_DIRECTORY = "lock_directory"
    RESTART_MANAGER = "restart_manager"
    # windows.Protocol.call: the two App Server methods usage and withdrawal use are the ones
    # the adapter allowlists (a code-level check; nothing is started).
    PROTOCOL_USAGE_METHOD = "protocol_usage_method"
    PROTOCOL_DELETE_METHOD = "protocol_delete_method"


class Capability(StrEnum):
    """What the product does that Codex's engine must allow (the keys of compat.CAPABILITIES).
    The last four are not implemented; they are listed so they can be offered later."""
    ENGINE_PRESENT = "engine_present"
    EXACT_THREAD_RECOVERY = "exact_thread_recovery"
    USAGE_LIMIT_DETECTION = "usage_limit_detection"
    USAGE_RESET_HINT = "usage_reset_hint"
    USAGE_PROBE = "usage_probe"
    THREAD_ELIGIBILITY = "thread_eligibility"
    LOADED_STATE_DETECTION = "loaded_state_detection"
    RECOVERY_TURN_TRACKING = "recovery_turn_tracking"
    QUEUE_WITHDRAW = "queue_withdraw"
    OUTCOME_OBSERVATION = "outcome_observation"
    TRANSIENT_CLASSIFICATION = "transient_classification"
    PROJECTION_FRESHNESS = "projection_freshness"
    EMPTY_RESPONSE_RECOVERY = "empty_response_recovery"
    NOT_LOADED_RECOVERY = "not_loaded_recovery"
    GOAL_CONTINUATION = "goal_continuation"
    SUBAGENT_RECOVERY = "subagent_recovery"


class ResolutionReason(StrEnum):
    """Why a capability has the state it has (compat.RESOLUTION_REASONS)."""
    LOCAL_CHECK_FAILED = "local_check_failed"
    REGISTRY_INCOMPATIBLE = "registry_incompatible"
    LOCAL_CHECK_UNAVAILABLE = "local_check_unavailable"
    NOT_IMPLEMENTED = "not_implemented"
    REGISTRY_VERIFIED = "registry_verified"
    REGISTRY_CHECKED = "registry_checked"
    LOCAL_CHECKS_PASSED = "local_checks_passed"
    LOCAL_CHECK_FAILED_HERE = "local_check_failed_here"


class ViewReason(StrEnum):
    """Why a reader could not use the report, so every capability is UNKNOWN (compat.VIEW_REASONS)."""
    REPORT_ABSENT = "report_absent"
    REPORT_INVALID = "report_invalid"
    REPORT_STALE = "report_stale"
    ENGINE_CHANGED = "engine_changed"


class RegistryReason(StrEnum):
    """The reasons a registry document may give; anything else is `unspecified` (compat.REGISTRY_REASONS)."""
    QUEUED_MESSAGE_NOT_DELIVERED_WHILE_UNLOADED = "queued_message_not_delivered_while_unloaded"
    QUEUE_RECEIPT_FORMAT_CHANGED = "queue_receipt_format_changed"
    QUEUE_INTERFACE_CHANGED = "queue_interface_changed"
    SCHEMA_CHANGED = "schema_changed"
    PROTOCOL_CHANGED = "protocol_changed"
    DELIVERY_UNVERIFIED = "delivery_unverified"
    MAINTAINER_ADVISORY = "maintainer_advisory"
    UNSPECIFIED = "unspecified"


class ImportReason(StrEnum):
    """Why registry data was refused (compat.IMPORT_REASONS)."""
    TOO_LARGE = "too_large"
    NOT_JSON = "not_json"
    DUPLICATE_KEY = "duplicate_key"
    NOT_FINITE = "not_finite"
    TOO_DEEP = "too_deep"
    NOT_AN_OBJECT = "not_an_object"
    UNKNOWN_FORMAT = "unknown_format"
    INVALID_FIELD = "invalid_field"
    SIGNATURE_REQUIRED = "signature_required"
    RANGE_CANNOT_GRANT = "range_cannot_grant"
    UNEVIDENCED_VERIFIED = "unevidenced_verified"
    TOO_MANY = "too_many"
    FROM_THE_FUTURE = "from_the_future"
    FROM_NEWER_PRODUCT = "from_newer_product"
    ROLLBACK = "rollback"
    UNREADABLE = "unreadable"
    NOT_A_JSON_FILE = "not_a_json_file"
    WRITE_FAILED = "write_failed"


class PermitReason(StrEnum):
    """Why doing a capability at a tier is allowed or not (compat.PERMIT_REASONS)."""
    ALLOWED = "allowed"
    INCOMPATIBLE = "incompatible"
    UNKNOWN = "unknown"
    NOT_OPTED_IN = "not_opted_in"
    NOT_VERIFIED = "not_verified"
    NOT_ACKNOWLEDGED_FOR_THIS_ENGINE = "not_acknowledged_for_this_engine"
    UNSUPPORTED_TIER = "unsupported_tier"


class CompatSource(StrEnum):
    """Where a capability's answer came from (compat.SOURCES)."""
    LOCAL = "local"
    BUNDLED = "bundled"
    CACHE = "cache"


class BundledState(StrEnum):
    """How the baseline shipped with the release stands (compat.BUNDLED_STATES)."""
    OK = "ok"
    MISSING = "missing"
    REJECTED = "rejected"


class CacheState(StrEnum):
    """How refreshed registry data stands (compat.CACHE_STATES). Time may only withhold trust:
    `expired` and `from_the_future` data still restricts and no longer grants VERIFIED."""
    ABSENT = "absent"                        # none imported
    OK = "ok"                                # in force
    EXPIRED = "expired"                      # past expires_at
    REJECTED = "rejected"                    # failed validation; kept on disk to be looked at
    SUPERSEDED = "superseded"                # older than the bundled baseline
    FROM_NEWER_PRODUCT = "from_newer_product"  # needs a newer version of this product
    FROM_THE_FUTURE = "from_the_future"      # published ahead of this computer's clock


class DataSource(StrEnum):
    """Which registry data the report was computed from (compat.DATA_SOURCES)."""
    CACHE = "cache"
    BUNDLED = "bundled"
    NONE = "none"


class ViewStatus(StrEnum):
    """Whether a reader could use the report (compat.VIEW_STATUSES)."""
    OK = "ok"
    ABSENT = "absent"
    INVALID = "invalid"
    STALE = "stale"
    ENGINE_CHANGED = "engine_changed"


class CacheOrigin(StrEnum):
    """Where refreshed registry data came from (compat.CACHE_ORIGINS)."""
    MAIN = "main"
    FILE = "file"


class ReportedState(StrEnum):
    """What other people's filed reports say of one Codex version (compat.reported.STATES).

    Reported is a grade beside the ladder of CompatState and never on it: nothing that decides
    reads it, and no member here is a state a capability can have."""
    REPORTED = "reported"                    # at least one filed report names this version
    NONE_YET = "none_yet"                    # the counts are readable and name it nowhere
    UNAVAILABLE = "unavailable"              # no counts to read, or no version to look up
    REJECTED = "rejected"                    # the counts file failed its own validation


class RefreshAnswer(StrEnum):
    """What a request to refresh the registry data came to (compatio.REFRESH_ANSWERS)."""
    REFRESHED = "refreshed"
    REFUSED = "refused"
    UNAVAILABLE = "unavailable"
    INCOMPLETE = "incomplete"
    FAILED = "failed"
