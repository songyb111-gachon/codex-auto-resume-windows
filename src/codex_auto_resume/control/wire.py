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
    # v0.6.11 (schema 4): not before this time, of that the time a person postponed it to (which
    # Don't postpone can take away), and whether it waits for a person.
    not_before: float | None
    postponed_until: float | None
    hold: str | None
    # v0.6.11: observe only - when every check but consent last passed, or None.
    would_send_at: float | None
    # v0.6.11: the conversation's token count the context-cost guard read, or None.
    context_tokens: int | None


class PendingRow(RecordView):
    """A row of Pending or History: the record, and what Codex calls its conversation."""
    thread_enabled: bool
    # v0.6.11: the conversation's own tier, or None for the default in Settings.
    tier: str | None
    # v0.6.11: the attempts a temporary failure may have now (None for a usage limit), shown beside
    # recovery_attempts even when that is more.
    attempt_limit: int | None
    name: str | None
    project: str | None
    cwd_basename: str | None


class DemoRow(PendingRow):
    """Show me what happens' made-up task (v0.6.11, demo.py): a row in every key a row has, and `demo`."""
    demo: bool


class DemoReply(TypedDict):
    """`demo`: how long the made-up task counts down, its Pending row and its History entry, and whether
    the watcher's icon was asked to draw its card."""
    seconds: int
    pending: DemoRow
    history: DemoRow
    asked: bool


class LogLine(TypedDict):
    """One line of this product's own log (v0.6.11, control/tools.py): its time as written, and the rest."""
    at: str
    text: str


class LogSearch(TypedDict):
    """`logs`: the lines that matched, newest last, how many did and how many were read, and the search."""
    lines: list[LogLine]
    matched: int
    total: int
    query: str


class StateAccessReply(TypedDict):
    """`state-access`: who Windows lets open the state folder, as one StateAccess word (v0.6.11)."""
    access: str


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


class Receipt(TypedDict):
    """What delivery showed of one continuation of a chain (v0.6.11): seen, uncertain or queued."""
    interruption_id: str
    kind: str
    at: float | None


class UsageWindow(TypedDict):
    """One window of a usage reading (v0.6.11), the allowlisted numbers and nothing else
    (domain/usage.py): the bucket and the window as closed words, the share used, the window's length
    in minutes and when it resets, in whole seconds."""
    bucket: str
    window: str
    used_percent: float
    window_minutes: int | None
    reset_at: int | None


class UsageReading(TypedDict):
    """The last usage reading the watcher made (v0.6.11), and when it made it."""
    read_at: float
    windows: list[UsageWindow]


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
    # v0.6.11: Codex's usage as last read, or None until it has been read.
    usage: UsageReading | None
    # v0.6.11: since when the watcher keeps this PC awake while a task waits, or None.
    awake_since: float | None
    # v0.6.11: the most private memory the watcher committed, in bytes, or None.
    memory_peak: int | None
    # v0.6.11: how a watcher that is not running ended - clean, memory_guard or unexpected - and when;
    # None and None for one that runs, or of which nothing can be said.
    ended: str | None
    ended_at: float | None


class PowerArmed(TypedDict):
    """What is armed of the power action after usage-limit recoveries (v0.6.12, control/poweraction.py):
    the action, after what and how often - PowerAction, PowerAfter and PowerRepeat words - how long its
    notice warns first, and when it was armed and its batch began. Never the batch's nonce, which only
    a notice's stop button carries."""
    action: str
    after: str
    repeat: str
    grace_seconds: int
    armed_at: float
    since: float


class PowerShown(TypedDict):
    """What the watcher last showed of an arming: waiting (for a PowerWait word, or None) or counting
    down (grace) to `grace_until`. Display only."""
    phase: str
    waiting_for: str | None
    grace_until: float | None


class PowerLast(TypedDict):
    """How the last batch ended: its action, a PowerEnd word, and when."""
    action: str
    result: str
    at: float


class PowerView(TypedDict):
    """The power action as every surface is told it (poweraction.view): each part None when there is none."""
    armed: PowerArmed | None
    shown: PowerShown | None
    last: PowerLast | None


class PowerChoice(TypedDict):
    """One action, and whether Windows will do it for this account here - and why not, a
    PowerUnavailable word, or None."""
    value: str
    available: bool
    reason: str | None


class PowerOptions(TypedDict):
    """`power-action`: what the Dashboard's card draws - the view, each action, an administrator's
    DisablePowerAction, and an older watcher holding the state."""
    view: PowerView
    actions: list[PowerChoice]
    managed: bool
    upgrade_pending: bool


class PowerDisarmed(TypedDict):
    """`power-disarm`: whether there was an arming to turn off."""
    changed: bool


class StatusSnapshot(TypedDict):
    """`status`, and the part of `dashboard` every page opens with."""
    enabled: bool
    # v0.6.11: nothing will be sent - the state's switch or the setting it is written from.
    observe_only: bool
    pending: int
    version: str
    # v0.6.11: the edition beside the version - standard, advanced or advanced_not_loaded (edition.shown).
    edition: str
    watcher: WatcherView
    watcher_running: bool
    startup_enabled: bool
    upgrade_pending: bool
    failure_unseen: bool
    codes: dict[str, int]
    states: dict[str, int]
    settings: dict[str, object]
    # v0.6.11: the administrator's policy keys in force, by name - only while one is (managed.py).
    managed: NotRequired[list[str]]
    # v0.6.12: the power action after usage-limit recoveries - only while its file exists.
    power_action: NotRequired[PowerView]


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
    """One capability's standing. `registry_reason` is there only when registry data in force
    marks the capability for this version, and names why (compat/standing.py); the reply has
    always carried it, and no golden held a view with an engine found until v0.6.10."""
    state: str
    tier: str
    source: str
    reason: str
    registry_reason: NotRequired[str]


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


class OwnValue(TypedDict):
    """v0.6.11: what a drop-down takes of a person's own besides its choices (ownvalues.published): the
    kind, the words' pattern, and where they mean something the bounds, the units, a count's prefix and
    catalog words, and the days with the sets a choice names."""
    kind: str
    pattern: str
    min: NotRequired[int]
    max: NotRequired[int]
    units: NotRequired[list[str]]
    prefix: NotRequired[str]
    amount: NotRequired[str]
    label: NotRequired[str]
    days: NotRequired[list[str]]
    named: NotRequired[dict[str, list[str]]]


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
    # v0.6.11: the value above which a limit is warned of; each retry preset's waits as a person is
    # shown them (ladder.preview); and each Custom wait's choices in seconds.
    high: NotRequired[int]
    waits: NotRequired[dict[str, list[int]]]
    seconds: NotRequired[dict[str, int]]
    # v0.6.11: an administrator's policy key decides it, so it is drawn greyed (managed.py).
    managed: NotRequired[bool]
    # v0.6.11: Custom... - a value of the person's own it takes besides its choices.
    custom: NotRequired[OwnValue]


# Every contract, by name, for the test that holds each to the goldens.
CONTRACTS = (RecordView, PendingRow, TimelineEvent, Receipt, UsageWindow, UsageReading, WatcherView,
             StatusSnapshot, Outcomes, Statistics, CompatEngine, CompatData, CompatCapability,
             CompatReported, CompatView, SchemaField, OwnValue, DemoRow, DemoReply, LogLine, LogSearch,
             StateAccessReply, PowerArmed, PowerShown, PowerLast, PowerView, PowerChoice, PowerOptions,
             PowerDisarmed)
