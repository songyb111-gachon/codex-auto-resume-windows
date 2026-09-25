"""The shapes this layer hands every surface, written down as types.

The settings window, the panel in Codex, the popup and the command line all read these replies
by field name, and until v0.6.10-alpha the only statement of what a reply held was the code that
built it and the golden copies in `tests/golden/`. These are that statement as types: what a
Rust port declares as structs, and what `tests/test_wire_types.py` holds to the goldens in both
directions - every key the wire carries is declared here, every key declared here is on the
wire, and every value seen fits its declared type.

Nothing imports this at run time; a reply is still a dict built where it always was. It changes
what can be said about a reply, not what a reply is.

Three things the types keep that a port would be tempted to lose:

  * `bool | None` where a question can go unanswered - whether the watcher is running, whether
    its last tick succeeded. None is "cannot tell", and it is not False.
  * `float` for every time: seconds since the epoch, as the store writes them.
  * Words from the closed vocabularies (`domain/vocabulary.py`) as `str`: a state, a public code,
    a category. The vocabulary is where the allowed words are; the wire carries the word.
"""
# No `from __future__ import annotations`: under it every annotation is a string, and
# TypedDict cannot see NotRequired inside one, so every key would count as required.
from typing import NotRequired, TypedDict

# A gate's verdict as the wire carries it: [result, reason], reason None where there is none.
GateVerdict = list  # [str, str | None]


class RecordView(TypedDict):
    """One record as every interface shows it (`control/records.py:describe_record`)."""
    interruption_id: str
    thread_id: str
    state: str
    code: str
    reason: str | None
    overlays: list[str]
    eligible_at: float | None
    terminal: bool
    category: str
    detected_at: float
    reset_at: float | None
    next_retry_at: float | None
    recovery_attempts: int
    no_progress_count: int
    chain_continuations: int
    chain_origin_id: str
    parent_interruption_id: str | None
    budget_resets: int
    budget_resets_left: int
    cancel_requested: bool
    recovery_turn_status: str | None
    user_joined: bool
    after_user_work: bool
    outcome_at: float | None
    first_queued_at: float | None
    gates: dict[str, GateVerdict] | None
    gates_at: float | None


class PendingRow(RecordView):
    """A row of Pending or History: the record, and what Codex calls its conversation."""
    thread_enabled: bool
    name: str | None
    project: str | None
    cwd_basename: str | None


class TimelineEvent(TypedDict):
    """One entry of a record's journal, as the Timeline dialog lists it."""
    event_id: int
    interruption_id: str
    at: float
    actor: str
    code: str
    from_state: str | None
    to_state: str
    to_code: str
    reason: str | None
    flags: int
    turn_ref: str | None
    value: float | int | None


class WatcherView(TypedDict):
    """What is known of the watcher: its heartbeat, and whether it is there to beat."""
    running: bool | None
    ticking: bool | None
    engine_state: str
    last_tick_at: float | None
    last_tick_ok: bool | None
    code_version: str | None
    pid: int | None
    started_at: float | None


class StatusSnapshot(TypedDict):
    """`status`, and the part of `dashboard` every page opens with."""
    enabled: bool
    pending: int
    version: str
    watcher: WatcherView
    watcher_running: bool
    startup_enabled: bool
    upgrade_pending: bool
    failure_unseen: bool
    codes: dict[str, int]
    states: dict[str, int]
    settings: dict[str, object]


class Outcomes(TypedDict):
    """How many records ended which way, in a period."""
    recovered: int
    no_progress: int
    recovery_failed: int
    failed_terminal: int
    exhausted: int
    cancelled: int
    stopped_by_user: int
    superseded: int
    handed_over: int
    submission_unknown: int
    outcome_unverified: int
    delivered_legacy: int


class Statistics(TypedDict):
    """`statistics`, and the Overview's week."""
    period_days: int | None
    interruptions_detected: int
    continuations_submitted: int
    retry_now_requests: int
    pending: int
    success_denominator: int
    success_rate: float | None
    median_wait_seconds: float | None
    median_recovery_seconds: float | None
    by_category: dict[str, int]
    outcomes: Outcomes


class CompatEngine(TypedDict):
    found: bool
    version: str | None


class CompatData(TypedDict):
    """Which registry data is in force: the bundled baseline, a fetched copy, or neither."""
    source: str
    bundled: str
    bundled_sequence: int
    cache: str
    cache_origin: str | None
    cache_sequence: int | None
    fetched_at: float | None
    expired: bool


class CompatCapability(TypedDict):
    state: str
    tier: str
    source: str
    reason: str


class CompatReported(TypedDict):
    """What other people's filed reports add up to for the Codex version the view names
    (`compat/views.py:reported_for`): shown beside that version, never a state of the ladder.

    `state` is a ReportedState word - reported, none_yet, unavailable or rejected - and the counts
    are 0 unless it is `reported`. They are counts of reports, one per GitHub login per version:
    worked + failed - both + neither = reports. Only the bridge carries this; the summary a model
    reads (`compat.mcp_view`) never does."""
    state: str
    reports: int
    worked: int
    failed: int
    neither: int
    both: int


class CompatView(TypedDict):
    """The Compatibility card's view: what is claimed of the engine in force, and why."""
    status: str
    overall: str
    live: bool
    checked_at: float | None
    acting: str | None
    engine: CompatEngine
    data: CompatData | None
    capabilities: dict[str, CompatCapability]
    checks: dict[str, str]
    reported: CompatReported


class SchemaField(TypedDict):
    """One setting as `describe` publishes it, which the window builds its editor from."""
    name: str
    type: str
    group: str
    default: bool | int | float | str | None
    # Only where they mean something: a reason's own setting has its category, the switch that
    # turns a whole group on or off is its master, and the rest belong to one kind of editor.
    category: NotRequired[str]
    master: NotRequired[bool]
    choices: NotRequired[list[str]]
    min: NotRequired[int | float]
    max: NotRequired[int | float]
    max_length: NotRequired[int]
    multiline: NotRequired[bool]


# Every contract, by name, for the test that holds each to the goldens.
CONTRACTS = (RecordView, PendingRow, TimelineEvent, WatcherView, StatusSnapshot, Outcomes,
             Statistics, CompatEngine, CompatData, CompatCapability, CompatReported, CompatView,
             SchemaField)
