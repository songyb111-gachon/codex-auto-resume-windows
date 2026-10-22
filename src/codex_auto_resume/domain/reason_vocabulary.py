"""The reasons a record waits, stops or is taken back, and what a watcher found of each Codex home.

Out of domain/vocabulary.py, which is at its line budget, in v0.6.15-beta and named through it still:
`from .vocabulary import ReasonCode` reads as it did. Each list is a contract as every other there is -
the store validates against it, the catalogs carry a sentence for each member (tests/test_vocabulary.py).

Pure: nothing here but the enums.
"""
from __future__ import annotations

from enum import StrEnum


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
    # v0.6.11: taken back because Observe only is on - a Pause's promise, under words of its own.
    OBSERVE_ONLY = "observe_only"
    OBSERVE_ONLY_UNKNOWN = "observe_only_unknown"
    # v0.6.15-beta: one queued for when its conversation is opened (P16's QUEUE_FOR_OPEN) - the plug no longer
    # keeps it there, or seven days and an hour passed; or the conversation was opened and Codex did not deliver it.
    WINDOW_ENDED = "window_ended"
    NOT_DELIVERED_ON_OPEN = "not_delivered_on_open"


class ReasonCode(StrEnum):
    """Every reason the engine or the store writes, a withdrawal's among them (machine.REASONS)."""
    # waiting
    DESKTOP_APP_UNAVAILABLE = "desktop_app_unavailable"
    NOTLOADED = "notLoaded"
    LOADED_STATE_UNKNOWN = "loaded_state_unknown"
    # v0.6.16-beta.4: open in another Codex session - a terminal or VS Code - which the app's queue cannot reach.
    HELD_BY_OTHER_SESSION = "held_by_other_session"
    # v0.6.16-beta.4: a terminal's or VS Code's conversation a newer Codex wrote than the engine is (`codex --version`):
    # it waits for Codex to be updated (engine/kinds.py, only while the plug names such a kind).
    VERSION_NEWER_THAN_ENGINE = "version_newer_than_engine"
    LOADED_RECHECK_FAILED = "loaded_recheck_failed"
    USAGE_UNAVAILABLE = "usage_unavailable"
    USAGE_UNKNOWN = "usage_unknown"
    USAGE_RECHECK_FAILED = "usage_recheck_failed"
    # v0.6.11: Windows reports no internet connection, so usage is not read (power.py; off by default).
    OFFLINE = "offline"
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
    NOT_RECOVERABLE = "not_recoverable"      # v0.6.14: a failure taken up (P17) nothing takes up now
    ADMISSION_EXPIRED = "admission_expired"  # and one taken up a day ago on the clock, ended unsent
    CAPACITY_WINDOW = "capacity_window"      # and capacity retries past twelve hours on the clock
    # v0.6.15-beta: a Codex home taken out of Settings, its waiting records cancelled (runtime/homes.py); and,
    # going back to a version that watches one home, another home's waiting records (store/downgrade.py).
    HOME_REMOVED = "home_removed"
    HOME_NOT_WATCHED = "home_not_watched"
    # v0.6.16-beta.4: a kind of conversation the plug no longer watches (P18) - a terminal's, VS Code's - cancels the
    # waiting records of its conversations.
    SESSION_KIND_OFF = "session_kind_off"
    # v0.6.16-beta.4: one sent to a conversation another Codex session held (P16's TO_SESSION), taken back because
    # that session let go of it, or did not take it within the delivery window. Shown reasons only: what is stored as
    # the withdrawal's own word is window_ended or not_delivered_on_open, which v0.6.15-beta and beta.2 read and
    # release alike, so no older reader meets a word it refuses (the review's blocker 2).
    SESSION_ENDED = "session_ended"
    SESSION_EXPIRED = "session_expired"
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
    # A recovery that worked and was interrupted again, usually by the next usage limit: the record is
    # `recovered`, because it was, and this reason keeps that the turn itself did not end cleanly.
    PROGRESS_THEN_TURN_FAILED = "progress_then_turn_failed"
    # And one that worked and whose turn Codex never finished: Codex closed, or the PC went off, mid-turn, so its row
    # says inProgress for good - a later turn of the conversation has started, or Windows started since (2026-10-21).
    PROGRESS_THEN_TURN_CUT_OFF = "progress_then_turn_cut_off"
    # And one that worked before a person's message entered its turn - one they had queued in the Codex app, or an
    # answer to a question Codex asked: recovered, not handed over, so its turn's next failure is recovered (2026-10-22).
    PROGRESS_THEN_USER_JOINED = "progress_then_user_joined"
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
    OBSERVE_ONLY = "observe_only"
    OBSERVE_ONLY_UNKNOWN = "observe_only_unknown"
    WINDOW_ENDED = "window_ended"
    NOT_DELIVERED_ON_OPEN = "not_delivered_on_open"


class HomeState(StrEnum):
    """What a watcher found of one Codex home it is set to watch (v0.6.15-beta, runtime/homes.py), as the
    heartbeat keeps it (store/watcher.py) and Settings words it: watched; another watcher holds its lock;
    its folder cannot be read; the ChatGPT app runs on another home; the same folder as a home already
    watched; removed, and kept only until what was sent there settles."""
    WATCHED = "watched"
    LOCK_BUSY = "lock_busy"
    UNAVAILABLE = "unavailable"
    OTHER_HOME = "other_home"
    DUPLICATE = "duplicate"
    RETIRING = "retiring"
