"""The closed vocabularies: every word the product stores, shows, translates or decides on.

A record's state, its public code, a reason, a gate, a failure category, a refusal, a setting's
choice, what the queue said of a send, a registry state - each is a word from a closed list,
and each list is a contract: the store validates against it, the window and the panel look
words up by it, the catalogs carry a sentence for every member, and a port of the core to
another language has to write exactly these strings. Each list is one `enum.StrEnum` here.

A member *is* its value. `RecordState.QUEUED == "queued"`, it hashes as "queued", so it is
found in a set of plain strings and a plain string is found in a set of members; `json.dumps`
writes "queued" for it as a value and as a key; a database binds it as "queued"; "%s" and
format() write "queued". So a member can go anywhere a plain string went and no byte changes
(tests/test_vocabulary.py asserts each of those for every member). Only repr() tells them
apart, and nothing the product writes uses it.

The module that owned a list keeps it under its old name, made from its enum -
`machine.STATES = frozenset(RecordState)`, `machine.GATES = tuple(GateName)` - so every
`x in STATES` still works, a tuple keeps its order, and a word is added in one place. A few
words are not a list anywhere yet: what a function returns (`SendOutcome`, `LoadedState`, the
watcher's start and stop), the keys of a table (`NoticeKind`), or a list in a module that
cannot take the import yet (`ActivityState`, `IconState`, `RefreshAnswer`). The test holds
each of those to the code that spells it, so the two cannot drift until that code is typed.

A member's name is its value in capitals, with `-` as `_`: `ALREADY_RUNNING` is
"already-running", `NOTLOADED` is Codex's own "notLoaded". The rule is mechanical, so a port
can generate the names.

Pure: nothing here but the enums, and the registry's, which are named here from their own file.
"""
from __future__ import annotations

from enum import StrEnum

# The compatibility registry's lists live beside this file since v0.6.11 (compat_vocabulary.py), and
# each is a name of this module too, so every `from .vocabulary import CompatState` reads as it did.
from .compat_vocabulary import (  # noqa: F401
    CompatState, LocalResult, Tier, CompatCheck, Capability, ResolutionReason, ViewReason,
    RegistryReason, ImportReason, PermitReason, CompatSource, BundledState, CacheState, DataSource,
    ViewStatus, CacheOrigin, ReportedState, RefreshAnswer)


# ------------------------------------------------------------------------------ records
class RecordState(StrEnum):
    """What the engine knows of a record, as the store keeps it (machine.STATES)."""
    # waiting
    WAITING_RESET = "waiting_reset"
    WAITING_POLL = "waiting_poll"
    WAITING_FOR_APP = "waiting_for_app"
    WAITING_FOR_LOADED_THREAD = "waiting_for_loaded_thread"
    WAITING_FOR_USAGE = "waiting_for_usage"
    WAITING_RETRY = "waiting_retry"
    WAITING_BACKOFF = "waiting_backoff"
    # claimed, in flight, observed
    SUBMITTING = "submitting"
    QUEUED = "queued"
    WITHDRAWN_UNCONFIRMED = "withdrawn_unconfirmed"
    TURN_STARTED = "turn_started"
    TURN_COMPLETED = "turn_completed"
    # how an observed recovery turn ended
    RECOVERED = "recovered"
    COMPLETED_NO_PROGRESS = "completed_no_progress"
    HANDED_OVER = "handed_over"
    RECOVERY_TURN_FAILED = "recovery_turn_failed"
    STOPPED_BY_USER = "stopped_by_user"
    OUTCOME_UNVERIFIED = "outcome_unverified"
    # stopped
    RETRY_BUDGET_EXHAUSTED = "retry_budget_exhausted"
    NO_PROGRESS_EXHAUSTED = "no_progress_exhausted"
    RESUMED = "resumed"                      # v0.5's delivered; kept for old rows, never written
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"
    SUPERSEDED_BY_USER = "superseded_by_user"
    FAILED = "failed"
    SUBMISSION_UNKNOWN = "submission_unknown"
    TERMINAL_FAILURE = "terminal_failure"


class PublicCode(StrEnum):
    """What a person is told a record is: stable, and never a setting's (machine.PUBLIC_CODES)."""
    WAITING_RESET = "waiting_reset"
    WAITING_USAGE = "waiting_usage"
    WAITING_THREAD = "waiting_thread"
    SCHEDULED = "scheduled"
    FAILED_RETRYABLE = "failed_retryable"
    SUBMISSION_CLAIMED = "submission_claimed"
    SUBMITTED = "submitted"
    WITHDRAWING = "withdrawing"
    TURN_RUNNING = "turn_running"
    TURN_FINISHING = "turn_finishing"
    RECOVERED = "recovered"
    NO_PROGRESS = "no_progress"
    HANDED_OVER = "handed_over"
    RECOVERY_FAILED = "recovery_failed"
    STOPPED_BY_USER = "stopped_by_user"
    OUTCOME_UNVERIFIED = "outcome_unverified"
    DELIVERED_LEGACY = "delivered_legacy"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"
    EXHAUSTED = "exhausted"
    FAILED_TERMINAL = "failed_terminal"
    SUBMISSION_UNKNOWN = "submission_unknown"


class WithdrawReason(StrEnum):
    """Why a continuation was taken back out of Codex's queue (machine.WITHDRAW_REASONS)."""
    CANCEL = "cancel"
    PAUSED = "paused"
    PAUSED_UNKNOWN = "paused_unknown"
    THREAD_DISABLED = "thread_disabled"
    SUPERSEDED = "superseded"
    SUPERSEDED_BY_USER = "superseded_by_user"
    USER_QUEUED_INPUT = "user_queued_input"
    NOT_LOADED = "not_loaded"
    EXPIRED = "expired"
    PROJECTION_STALE = "projection_stale"
    DUPLICATE_OWNER = "duplicate_owner"


class ReasonCode(StrEnum):
    """Every reason the engine or the store writes, a withdrawal's among them (machine.REASONS)."""
    # waiting
    DESKTOP_APP_UNAVAILABLE = "desktop_app_unavailable"
    NOTLOADED = "notLoaded"
    LOADED_STATE_UNKNOWN = "loaded_state_unknown"
    LOADED_RECHECK_FAILED = "loaded_recheck_failed"
    USAGE_UNAVAILABLE = "usage_unavailable"
    USAGE_UNKNOWN = "usage_unknown"
    USAGE_RECHECK_FAILED = "usage_recheck_failed"
    DAILY_SUBMISSION_CAP = "daily_submission_cap"
    THREAD_SUBMISSION_COOLDOWN = "thread_submission_cooldown"
    QUEUE_PROCESS_NOT_STARTED = "queue_process_not_started"
    PROJECTION_STALE = "projection_stale"
    USER_INPUT_QUEUED = "user_input_queued"
    WAITING_RESET = "waiting_reset"
    OTHER_RECOVERY_IN_FLIGHT = "other_recovery_in_flight"
    RELEASED_BEFORE_SEND = "released_before_send"
    RELEASED_AFTER_WITHDRAWAL = "released_after_withdrawal"
    BUDGET_RESTORED = "budget_restored"
    RETRY_NOW = "retry_now"
    # stops
    RECOVERY_BUDGET = "recovery_budget"
    NO_PROGRESS_BUDGET = "no_progress_budget"
    CHAIN_CAP = "chain_cap"
    # v0.6.11: a transient task kept failing for longer than its time ceiling (ladder.py).
    CHAIN_TIME_CAP = "chain_time_cap"
    QUEUE_LAUNCH_RETRY_LIMIT = "queue_launch_retry_limit"
    LATER_TURN_EXISTS = "later_turn_exists"
    LATEST_TURN_CHANGED = "latest_turn_changed"
    PARENT_CANCELLED = "parent_cancelled"
    PARENT_HANDED_OVER = "parent_handed_over"
    USER_CANCELLED = "user_cancelled"
    USAGE_NEVER_AVAILABLE = "usage_never_available"
    USAGE_NOT_RESTORED_AFTER_RESET = "usage_not_restored_after_reset"
    DUPLICATE_OWNER = "duplicate_owner"
    CATEGORY_DISABLED = "category_disabled"
    # sending and receipts
    AWAITING_DELIVERY_RECEIPT = "awaiting_delivery_receipt"
    QUEUE_RESULT_UNKNOWN_DO_NOT_RESEND = "queue_result_unknown_do_not_resend"
    NO_RECEIPT_DO_NOT_RESEND = "no_receipt_do_not_resend"
    MULTIPLE_MATCHING_QUEUE_ITEMS = "multiple_matching_queue_items"
    QUEUE_CLEANUP_UNCONFIRMED = "queue_cleanup_unconfirmed"
    WITHDRAW_UNCONFIRMED = "withdraw_unconfirmed"
    DUPLICATE_MARKER = "duplicate_marker"
    AMBIGUOUS_RECEIPT = "ambiguous_receipt"
    QUEUED_ITEM_EDITED = "queued_item_edited"
    OWNED_QUEUE_REMOVED = "owned_queue_removed"
    TURN_WITHOUT_USER_ITEM = "turn_without_user_item"
    POST_SEND_BOOKKEEPING_FAILED = "post_send_bookkeeping_failed"
    # outcomes
    MARKER_NOT_TURN_INITIATOR = "marker_not_turn_initiator"
    USER_JOINED = "user_joined"
    STALE_TURN_ROW = "stale_turn_row"
    UNKNOWN_TURN_STATUS = "unknown_turn_status"
    OUTCOME_DEADLINE = "outcome_deadline"
    CORRELATION_CONFLICT = "correlation_conflict"
    PROGRESS_OBSERVED = "progress_observed"
    NO_PROGRESS_OBSERVED = "no_progress_observed"
    TURN_FAILED = "turn_failed"
    # A recovery that worked and was interrupted again - usually by the next usage limit, which
    # Codex records on the turn as a failure. The record is `recovered`, because it was; this
    # reason is how the journal keeps the distinction that the turn itself did not end cleanly.
    PROGRESS_THEN_TURN_FAILED = "progress_then_turn_failed"
    TURN_INTERRUPTED = "turn_interrupted"
    # a withdrawal's, as WithdrawReason
    CANCEL = "cancel"
    PAUSED = "paused"
    PAUSED_UNKNOWN = "paused_unknown"
    THREAD_DISABLED = "thread_disabled"
    SUPERSEDED = "superseded"
    SUPERSEDED_BY_USER = "superseded_by_user"
    USER_QUEUED_INPUT = "user_queued_input"
    NOT_LOADED = "not_loaded"
    EXPIRED = "expired"


class EventCode(StrEnum):
    """What a journal entry records (machine.EVENT_CODES)."""
    DETECTED = "detected"
    STATE = "state"
    CLAIM = "claim"
    SUBMITTED = "submitted"
    RELEASE_CLAIM = "release_claim"
    WITHDRAW = "withdraw"
    RELEASE_WITHDRAWN = "release_withdrawn"
    CORRELATED = "correlated"
    CONTINUATION_AFTER_USER_TURN = "continuation_after_user_turn"
    DISPATCHED_DESPITE_DELETE = "dispatched_despite_delete"
    DISPATCHED_WHILE_PAUSED = "dispatched_while_paused"
    CANCEL = "cancel"
    CANCEL_REQUESTED = "cancel_requested"
    RESET_BUDGET = "reset_budget"
    RETRY_NOW = "retry_now"
    IDENTITY_DRIFT = "identity_drift"
    HIDDEN = "hidden"
    MIGRATED = "migrated"
    DISABLED_THREADS_WITH_PENDING = "disabled_threads_with_pending"
    THREAD_ENABLED = "thread_enabled"
    # v0.6.11: a record made later - by a person, or by the engine for its conversation's objection
    # window - held for a person, let go by one, and a conversation given a tier of its own.
    POSTPONED = "postponed"
    HELD = "held"
    HOLD_RELEASED = "hold_released"
    TIER_SET = "tier_set"
    # v0.6.11: observe only - every check but consent passed, and nothing was sent (once a period).
    WOULD_SEND = "would_send"
    OTHER = "other"


class Actor(StrEnum):
    """Who made a journal entry happen (machine.ACTORS)."""
    ENGINE = "engine"
    GUI = "gui"
    CLI = "cli"
    TOAST = "toast"
    MCP = "mcp"


class TurnStatus(StrEnum):
    """How a Codex turn stands - Codex's four words, and ours for any other (machine.TURN_STATUSES)."""
    INPROGRESS = "inProgress"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    OTHER = "other"


class Page(StrEnum):
    """The settings window's pages, in the order it shows them (machine.PAGES)."""
    OVERVIEW = "overview"
    PENDING = "pending"
    HISTORY = "history"
    STATISTICS = "statistics"
    DIAGNOSTICS = "diagnostics"
    SETTINGS = "settings"


class Overlay(StrEnum):
    """A circumstance that changes what a waiting record does next (machine.OVERLAYS)."""
    CANCEL_PENDING = "cancel_pending"
    PAUSED = "paused"
    THREAD_DISABLED = "thread_disabled"
    COMPATIBILITY_BLOCKED = "compatibility_blocked"
    COMPATIBILITY_FAILED_HERE = "compatibility_failed_here"
    ENGINE_UNAVAILABLE = "engine_unavailable"
    WATCHER_NOT_TICKING = "watcher_not_ticking"
    # v0.6.11: waits for a person to let it continue (`interruptions.hold`).
    HELD = "held"


class HoldKind(StrEnum):
    """Why a record waits for a person before it may be sent (schema 4; machine.HOLDS)."""
    ASK = "ask"
    NOTIFY_ONLY = "notify_only"
    AFTER_SLEEP = "after_sleep"
    ACCOUNT_CHANGED = "account_changed"
    WORKSPACE_CHANGED = "workspace_changed"
    # v0.6.11: its conversation has used more tokens than the context-cost guard allows (guards.py).
    CONTEXT_COST = "context_cost"


class ImportanceTier(StrEnum):
    """How much a conversation asks before it is resumed, least first (machine.IMPORTANCE_TIERS)."""
    AUTOMATIC = "automatic"
    OBJECTION_WINDOW = "objection_window"
    ASK_FIRST = "ask_first"
    NOTIFY_ONLY = "notify_only"


# -------------------------------------------------------------------------------- gates
class GateName(StrEnum):
    """The gates, in the order they are evaluated (machine.GATES)."""
    CONSENT = "consent"
    ENGINE_COMPATIBLE = "engine_compatible"
    SINGLE_OWNER = "single_owner"
    SUBMISSION_SAFE = "submission_safe"
    IDENTITY = "identity"
    KNOWN_FAILURE = "known_failure"
    SCHEDULE = "schedule"
    CHAIN_BUDGET = "chain_budget"
    ATTEMPT_BUDGET = "attempt_budget"
    NO_PROGRESS_BUDGET = "no_progress_budget"
    THREAD_AVAILABLE = "thread_available"
    NO_NEWER_USER_WORK = "no_newer_user_work"
    USAGE = "usage"


class GateResult(StrEnum):
    """What one gate found (machine.GATE_RESULTS). UNKNOWN never passes."""
    PASS = "PASS"
    WAIT = "WAIT"
    BLOCK = "BLOCK"
    UNKNOWN = "UNKNOWN"


# ----------------------------------------------------------------------------- failures
class FailureCategory(StrEnum):
    """What a failed turn was classified as (failures.CATEGORIES). `unknown` is never recovered."""
    USAGE_LIMIT = "usage_limit"
    NETWORK_TRANSIENT = "network_transient"
    TIMEOUT = "timeout"
    RATE_LIMIT_TRANSIENT = "rate_limit_transient"
    SERVER_5XX = "server_5xx"
    STREAM_INTERRUPTED = "stream_interrupted"
    # Reserved since v0.6.10 (failures.RESERVED): nothing produces it; kept so a row naming it reads.
    AUTH_SERVICE_TRANSIENT = "auth_service_transient"
    TERMINAL_USER = "terminal_user"
    TERMINAL_PERMISSION = "terminal_permission"
    TERMINAL_POLICY = "terminal_policy"
    TERMINAL_INVALID = "terminal_invalid"
    TERMINAL_AUTH = "terminal_auth"
    TERMINAL_FAILURE = "terminal_failure"
    UNKNOWN = "unknown"


# ------------------------------------------------------------------------ the watcher
class EngineState(StrEnum):
    """The heartbeat's word for the Codex engine (store.ENGINE_STATES, compat.ENGINE_STATES)."""
    VERIFIED = "verified"
    CHECKED = "checked"
    STRUCTURALLY_COMPATIBLE = "structurally_compatible"
    FAILED_HERE = "failed_here"
    INCOMPATIBLE = "incompatible"
    UNKNOWN = "unknown"


class WatcherStartState(StrEnum):
    """What a start of the watcher came to (Control.start_watcher, control.await_watcher)."""
    RUNNING = "running"
    ALREADY_RUNNING = "already-running"
    EXITED = "exited"
    UNCONFIRMED = "unconfirmed"


class WatcherStopState(StrEnum):
    """What a stop of the watcher came to (Control.stop_watcher, control.await_stopped)."""
    STOPPED = "stopped"
    NOT_RUNNING = "not-running"
    STILL_FINISHING = "still-finishing"
    UNKNOWN = "unknown"


class ErrorCode(StrEnum):
    """Every way the control layer refuses a request (control.ERROR_CODES)."""
    INVALID_ID = "invalid_id"
    INVALID_THREAD_ID = "invalid_thread_id"
    INVALID_ENABLED = "invalid_enabled"
    NO_SUCH_INTERRUPTION = "no_such_interruption"
    NOT_INSTALLED = "not_installed"
    START_FAILED = "start_failed"
    STORE_UNAVAILABLE = "store_unavailable"
    NEWER_STATE = "newer_state"
    UPGRADE_PENDING = "upgrade_pending"
    STATE_BUSY = "state_busy"
    NOT_EXHAUSTED = "not_exhausted"
    CANCEL_REQUESTED = "cancel_requested"
    POSSIBLY_SENT = "possibly_sent"
    RESET_LIMIT = "reset_limit"
    ALREADY_FINISHED = "already_finished"
    BEING_SENT = "being_sent"
    IN_FLIGHT = "in_flight"
    OBSERVING = "observing"
    CANNOT_CONTINUE = "cannot_continue"
    CANNOT_CHECK_NOW = "cannot_check_now"
    FILE_EXISTS = "file_exists"
    REQUEST_FAILED = "request_failed"
    THREAD_MISMATCH = "thread_mismatch"
    # v0.6.11: a postponement that is not a later time, or more than a week ahead; a record that
    # is not held; a tier that is not one.
    INVALID_TIME = "invalid_time"
    NOT_LATER = "not_later"
    TOO_FAR = "too_far"
    NOT_HELD = "not_held"
    INVALID_TIER = "invalid_tier"
    # v0.6.11: Always or Never for a project whose conversation's project cannot be read, or one more
    # than a list of projects holds.
    PROJECT_UNREADABLE = "project_unreadable"
    TOO_MANY_PROJECTS = "too_many_projects"


# ---------------------------------------------------------------- settings and language
class ContinuationStyle(StrEnum):
    """How the continuation is worded (continuation.STYLES)."""
    MINIMAL = "minimal"
    STANDARD = "standard"
    DETAILED = "detailed"
    CUSTOM = "custom"


class CustomMode(StrEnum):
    """One Custom message for everything, or one per category (continuation.CUSTOM_MODES)."""
    GLOBAL = "global"
    PER_REASON = "per_reason"


class Theme(StrEnum):
    """The surfaces' colours; `system` follows the host (settings.THEMES)."""
    SYSTEM = "system"
    LIGHT = "light"
    DARK = "dark"


class Design(StrEnum):
    """How the surfaces are drawn, in either theme (settings.DESIGNS, brand.DESIGN): `soft` is the
    design every surface drew until v0.6.10, `classic` is v0.6.2's flat cards and `plain` flat
    neutral grey. v0.6.10's `still` is gone: a stored one reads as Soft with Reduce motion on
    (settings._migrate)."""
    SOFT = "soft"
    CLASSIC = "classic"
    PLAIN = "plain"


class QuietDays(StrEnum):
    """The days quiet hours start on (settings.QUIET_DAYS, quiet.DAYS), each an ISO weekday set."""
    EVERY_DAY = "every_day"
    WEEKDAYS = "weekdays"
    WEEKENDS = "weekends"


class NewConversationPolicy(StrEnum):
    """What a conversation this product has never seen gets (settings.NEW_CONVERSATION_POLICIES):
    the same as every other (the default), or Only notify me as a tier of its own (v0.6.11)."""
    RESUME = "resume"
    NOTIFY_ONLY = "notify_only"


class ProjectPolicy(StrEnum):
    """Which projects may resume without a person (settings.PROJECT_POLICIES, projects.py): every
    one (the default), only those set to Always, or every one but those set to Never (v0.6.11)."""
    EVERY = "every"
    ONLY_LISTED = "only_listed"
    EXCEPT_LISTED = "except_listed"


class RetryTiming(StrEnum):
    """The retry ladders a person may choose (settings.RETRY_TIMINGS): the three presets - the keys
    of settings.RETRY_TIMING - and, from v0.6.11, Custom, the five waits a person picks (ladder.py)."""
    CONSERVATIVE = "conservative"
    NORMAL = "normal"
    AGGRESSIVE = "aggressive"
    CUSTOM = "custom"


class RetryWait(StrEnum):
    """One wait of the Custom ladder, from a closed list (ladder.WAITS): a unit's letter and a number,
    as a clock says it - never a number a person or a model types (v0.6.11)."""
    S5 = "s5"
    S15 = "s15"
    S30 = "s30"
    M1 = "m1"
    M2 = "m2"
    M5 = "m5"
    M10 = "m10"
    M15 = "m15"
    M30 = "m30"
    H1 = "h1"
    H2 = "h2"
    H3 = "h3"
    H6 = "h6"


class ChainCeiling(StrEnum):
    """How long a task may keep failing with a temporary error before it stops (ladder.CEILINGS):
    off, the default and v0.6.10's, or a number of hours (v0.6.11)."""
    OFF = "off"
    H1 = "h1"
    H3 = "h3"
    H6 = "h6"
    H12 = "h12"
    H24 = "h24"


class TaskGuard(StrEnum):
    """What a change to a task's workspace does when its recovery falls due (guards.TASK_GUARDS): nothing,
    the default; hold it for a person; or say so on the notice of its continuation (v0.6.11)."""
    OFF = "off"
    HOLD = "hold"
    TELL = "tell"


class ContextGuard(StrEnum):
    """The context-cost guard (guards.CONTEXT_GUARDS): off, the default; show how many tokens a
    conversation has used; or also hold one that has used more than a number of them (v0.6.11)."""
    OFF = "off"
    SHOW = "show"
    ABOVE_100K = "above_100k"
    ABOVE_250K = "above_250k"
    ABOVE_500K = "above_500k"
    ABOVE_1M = "above_1m"


class NotifyEvent(StrEnum):
    """What a notification may be about, each switchable (settings.NOTIFICATION_EVENTS)."""
    INTERRUPTION = "interruption"
    STARTING = "starting"
    RESULT = "result"
    STOPPED = "stopped"


class Locale(StrEnum):
    """The languages the product speaks, the source catalog first (l10n.LOCALES)."""
    EN = "en"
    KO = "ko"
    JA = "ja"
    ZH_CN = "zh-CN"
    ZH_TW = "zh-TW"
    ES = "es"
    DE = "de"
    FR = "fr"
    PT_BR = "pt-BR"


# ------------------------------------------------------------------------ Codex's answers
class SendOutcome(StrEnum):
    """What the queue said of a send (windows.Backend.send). `unknown` may have been sent."""
    ACCEPTED = "accepted"
    NOT_STARTED = "not_started"
    UNKNOWN = "unknown"


class SendError(StrEnum):
    """Why a send was not accepted (windows.Backend.send)."""
    QUEUE_PREFLIGHT_FAILED = "queue_preflight_failed"
    QUEUE_CONSENT_REFUSED = "queue_consent_refused"
    QUEUE_SPAWN_FAILED = "queue_spawn_failed"
    QUEUE_RESPONSE_UNCONFIRMED = "queue_response_unconfirmed"
    QUEUE_TIMEOUT = "queue_timeout"
    QUEUE_RESULT_UNKNOWN = "queue_result_unknown"


class LoadedState(StrEnum):
    """Whether the app has a conversation open, in Codex's words (windows.Backend.loaded)."""
    LOADED = "loaded"
    NOTLOADED = "notLoaded"
    UNKNOWN = "unknown"


# ------------------------------------------------------------------------- the surfaces
class ActivityState(StrEnum):
    """The popup's word for what the watcher is doing (popup.STATES)."""
    MONITORING = "monitoring"
    WAITING = "waiting"
    CHECKING = "checking"
    RECOVERING = "recovering"
    PAUSED = "paused"
    ATTENTION = "attention"


class IconState(StrEnum):
    """What the notification-area icon shows; it has no words (tray.ICON_STATES)."""
    WATCHING = "watching"
    RECOVERING = "recovering"
    IDLE = "idle"
    ATTENTION = "attention"
    FAILED = "failed"


class NoticeKind(StrEnum):
    """What a notification is about, on the card and the toast (the keys of notifier.STATUS)."""
    INTERRUPTION = "interruption"
    STARTING = "starting"
    RESUMED = "resumed"
    FAILED = "failed"
    UNKNOWN = "unknown"
    STOPPED = "stopped"
    CANCELLED = "cancelled"
