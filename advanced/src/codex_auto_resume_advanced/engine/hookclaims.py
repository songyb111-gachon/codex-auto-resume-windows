# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Continue inside the turn (stop_hook_continuation, v0.6.20): the claim the Stop hook shares with the watcher, and the
capability's answers at P3 and P8 (plans/v0619-design/D-stop-hook.md).

The hook (hook/handler.py) runs in a process Codex starts, not in the watcher, so it cannot be asked through core's
claim. It claims in the same file and under the same lock instead: core's state.sqlite with this edition's state
attached, in one BEGIN IMMEDIATE - exactly the transaction core's own claim takes, with the claim ledger's file
attached there too (ledger.py). Whichever begins first is the one that takes the failure:

* the watcher first: its claim has moved core's record past waiting, which the hook reads, and the hook passes (a
  `passed` row);
* the hook first: its `blocked` row stands under the interruption id core derives from the same turn (domain/ids.py),
  and core is held twice - at P3, by this capability's gate, for HOLD_SECONDS, while its next look finds the
  conversation moved on; and at P11, inside core's claim, by the ledger (`held`), whatever the capability's state - so
  a hook's continuation is never followed by core's for the same interruption, and a turn off since does not undo it.

The hook's continuation is a continuation like any other to the caps on one conversation (standard A20): one unit of
this capability's is spent with its claim, and the ledger counts those units beside core's own claims and this
edition's records - five a conversation a day, fifteen minutes apart (`spent_on`). Once a turn: a turn that has had
a block is refused another, under any interruption id (`refused`). The hold lasts HOLD_SECONDS, core's own spacing
between claims, and no longer: a block Codex did not carry out leaves core to recover the record as it always would.

P8: while the capability is on, its declaration stands in our plugin copies - written back after a Repair replaced
the plugin's files (control/hookplugin.py); arming writes and removes it as the capability moves (arming.py).
"""
from __future__ import annotations

from pathlib import Path
import sqlite3
import time

from codex_auto_resume import config
from codex_auto_resume.domain.ids import is_interruption_id
from codex_auto_resume.domain.plug import DEFER, Alternative

from ..vocabulary import HookOutcome

CAPABILITY = "stop_hook_continuation"
DAY = 86400
# How long a block holds core back from the same interruption: core's own spacing between two claims on one
# conversation (registry.CORE_COOLDOWN_SECONDS), so it holds nothing core's floor would not have held anyway.
HOLD_SECONDS = 900
BUSY_SECONDS = 0.5               # how long the hook waits for the claim's lock before it passes
CORE_FILE = "state.sqlite"

def _core_settled():
    """Core's waiting states and its terminal ones: a record in neither is in flight."""
    from codex_auto_resume import machine
    return frozenset(machine.WAITING) | frozenset(machine.TERMINAL)


def _advanced_file(paths) -> Path:
    from ..state.schema import FILE_NAME
    return Path(paths.advanced_dir) / FILE_NAME


def _readable(path) -> bool:
    try:
        return path.is_file() and not config.is_link(path) and not config.is_link(path.parent)
    except OSError:
        return False


def blocked_at(paths, interruption_id):
    """When the hook blocked the turn of `interruption_id`, or None: read-only, from this edition's state as it stands
    on disk, with nothing made, migrated or written."""
    if not is_interruption_id(interruption_id):
        return None
    path = _advanced_file(paths)
    if not _readable(path):
        return None
    try:
        connection = sqlite3.connect("file:%s?mode=ro" % path.as_posix(), uri=True, timeout=1)
    except sqlite3.Error:
        return None
    try:
        row = connection.execute("SELECT at FROM hook_claims WHERE interruption_id=? AND outcome=?",
                                 (interruption_id, HookOutcome.BLOCKED)).fetchone()
    except sqlite3.Error:
        return None
    finally:
        connection.close()
    return row[0] if row is not None and isinstance(row[0], (int, float)) else None


def held(connection, schema, interruption_id, now) -> bool:
    """P11, inside core's claim with this edition's file attached as `schema`: whether the hook blocked the turn of
    `interruption_id` within HOLD_SECONDS - then core's claim of it is held, whatever the capability's state."""
    row = connection.execute("SELECT at FROM %s.hook_claims WHERE interruption_id=? AND outcome=?" % schema,
                             (interruption_id, HookOutcome.BLOCKED)).fetchone()
    return row is not None and 0 <= now - row[0] < HOLD_SECONDS


def spent_on(connection, schema, thread_id, now) -> tuple:
    """(the hook's continuations in `thread_id` in the last day, when the latest was or None): what the caps on one
    conversation count of it, beside core's claims and this edition's records (ledger.held_by_records)."""
    row = connection.execute("SELECT count(*), max(at) FROM %s.spend WHERE capability=? AND thread_id=? AND at>?"
                             % schema, (CAPABILITY, thread_id, now - DAY)).fetchone()
    return int(row[0] or 0), row[1]


def _core_holds(connection, thread_id, now) -> bool:
    """Core's own caps on one conversation, read on its file: a record of its in flight there, a claim within its
    spacing, or five in the day once the hook's units and this edition's records are counted with them."""
    from ..ledger import held_by_records
    from ..registry import CORE_COOLDOWN_SECONDS, CORE_DAILY_CAP
    from ..state import ATTACHED
    settled = _core_settled()
    rows = connection.execute(
        "SELECT state, max(attempt_count, 1), coalesce(submitted_at, last_claim_at) FROM main.interruptions "
        "WHERE thread_id=?", (thread_id,)).fetchall()
    if any(row[0] not in settled for row in rows):
        return True
    recent = [row for row in rows if isinstance(row[2], (int, float)) and row[2] > now - DAY]
    if any(now - row[2] < CORE_COOLDOWN_SECONDS for row in recent):
        return True
    hooks, _last = spent_on(connection, ATTACHED, thread_id, now)
    if sum(row[1] for row in recent) + hooks >= CORE_DAILY_CAP:
        return True
    return held_by_records(connection, thread_id, now)


def claim(paths, failure, turn_key, now, *, registry=None, busy=BUSY_SECONDS):
    """The hook's claim of `failure` - core's detection of the latest turn, with its interruption id - for the turn
    digested as `turn_key`: the HookOutcome it wrote, or None where nothing was written (recovery or the capability
    off, the state not there, the turn already answered, the lock not had in time). Only BLOCKED lets the hook block.

    One transaction on core's file with this edition's attached, BEGIN IMMEDIATE - core's claim's own lock - and
    nothing written to core's file, ever."""
    from ..ledger import ceiling_reached
    from ..registry import REGISTRY
    from ..state import ATTACHED, AdvancedState
    from ..vocabulary import ArmingState
    registry = REGISTRY if registry is None else registry
    definition = registry.get(CAPABILITY)
    key, thread = failure.get("interruption_id"), failure.get("thread_id")
    core = Path(paths.state_dir) / CORE_FILE
    if definition is None or not is_interruption_id(key) or not _readable(core):
        return None
    state = AdvancedState(paths, registry=registry)
    connection = None
    try:
        connection = sqlite3.connect(str(core), timeout=busy, isolation_level=None)
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.row_factory = sqlite3.Row             # as core's claim reads its rows (state/spend.counts)
        if not state.attach(connection):
            return None
        connection.execute("BEGIN IMMEDIATE")
        try:
            outcome = _decide(connection, state, definition, key, thread, turn_key, now, ATTACHED,
                              ArmingState.ARMED, ceiling_reached)
            if outcome is not None:
                connection.execute("INSERT INTO %s.hook_claims (interruption_id, turn_digest, at, outcome) "
                                   "VALUES (?,?,?,?)" % ATTACHED, (key, turn_key, now, outcome))
                if outcome == HookOutcome.BLOCKED:
                    at = state.claim_time(connection, ATTACHED, key, now)
                    state.record_spend(connection, ATTACHED, CAPABILITY, thread, key, at)
            connection.execute("COMMIT")
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        return outcome
    except Exception:
        return None
    finally:
        if connection is not None:
            connection.close()
        state.close()


def _decide(connection, state, definition, key, thread, turn_key, now, schema, armed, ceiling_reached):
    """The outcome to write, inside the claim's transaction, or None for nothing written."""
    settings = connection.execute("SELECT enabled, observe_only FROM main.settings").fetchone()
    if settings is None or not settings[0] or settings[1]:
        return None
    on = connection.execute("SELECT enabled FROM main.threads WHERE thread_id=?", (thread,)).fetchone()
    if on is not None and not on[0]:
        return None
    if connection.execute("SELECT 1 FROM %s.hook_claims WHERE interruption_id=?" % schema, (key,)).fetchone():
        return None                                   # answered already: once for each interruption
    row = connection.execute("SELECT state FROM %s.arming WHERE capability=?" % schema, (CAPABILITY,)).fetchone()
    if row is None or row[0] != armed:
        return None                                   # a turn off since the hook looked always wins
    if connection.execute("SELECT 1 FROM %s.hook_claims WHERE turn_digest=? AND outcome=?" % schema,
                          (turn_key, HookOutcome.BLOCKED)).fetchone():
        return HookOutcome.REFUSED                    # once a turn
    core = connection.execute("SELECT state FROM main.interruptions WHERE interruption_id=?", (key,)).fetchone()
    from codex_auto_resume import machine
    if core is not None and core[0] not in machine.WAITING:
        return HookOutcome.PASSED                     # the watcher took it first
    if _core_holds(connection, thread, now):
        return HookOutcome.REFUSED
    global_hourly = connection.execute("SELECT global_hourly FROM %s.meta" % schema).fetchone()[0]
    if ceiling_reached(state.counts(connection, schema, CAPABILITY, thread, now), definition, global_hourly):
        return HookOutcome.REFUSED
    return HookOutcome.BLOCKED


class StopHook:
    """The capability's code: P3's hold on a record the hook blocked, and P8's upkeep of the declaration. `bind` gives
    it the runtime's clock (state.Scoped)."""
    __slots__ = ("paths", "_scoped")

    def __init__(self, paths):
        self.paths = paths
        self._scoped = None

    def bind(self, scoped):
        self._scoped = scoped

    def _now(self) -> float:
        return self._scoped.now() if self._scoped is not None else time.time()

    def gate(self, name, record, facts):
        """P3: HOLD for a core record whose turn the hook blocked within HOLD_SECONDS - its continuation went in the
        turn, and core's would be a second one. DEFER for every other record and gate."""
        key = record.get("interruption_id") if isinstance(record, dict) else None
        at = blocked_at(self.paths, key)
        if at is None or not 0 <= self._now() - at < HOLD_SECONDS:
            return DEFER
        return Alternative.HOLD


    def tick(self, view):
        """P8, asked only while the capability is on: its declaration stands in our plugin copies - written back where a
        Repair or an update replaced the plugin's files. Nothing for core to run."""
        from ..codex import inuse
        from ..control import hookplugin
        hookplugin.follow(self.paths, inuse.home(self.paths), True)
        return DEFER


def make(paths) -> StopHook:
    """The capability's factory (registry.CapabilityDef.make): its code for one installation."""
    return StopHook(paths)
