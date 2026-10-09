"""The state this product keeps: one SQLite file, and the rules for writing it.

`store.py` was 1,565 lines and one class of sixty-one methods. It is the same class, composed
here from the mixins beside this file, so every `from codex_auto_resume.store import Store` and
every `store.method()` reads exactly as it did - and each part of it is now a file small enough
to hold in your head:

    session     the connection, the transaction, the moment
    schema      the tables as they are created today
    migrations  bringing an older state forward
    columns     what each schema version holds, in order
    validate    every value checked before it is written
    errors      the four ways the store refuses
    journal     what happened to a record, and the pruning of it
    policy      recovery on or off, per conversation
    records     registering, reading, and the rules a change obeys
    claims      the right to send, taken and let go
    ledger      the edition's say in a claim (P11), and what it may do there
    plugclaims  the edition's plug's own work, claimed and guarded as core's is (v0.6.14)
    actions     what a person asks for
    schedule    a record made later, held and let go (v0.6.11)
    watcher     the heartbeat
    notices     a needs-you notice, raised once (v0.6.11)
    reporting   counts, and the last seven days
    legacy      an older release's state, read-only
    downgrade   putting it back to v3 or v2, by hand

The order the mixins are named in is the order the file used to read in, and nothing depends
on it: no two of them define the same method, which `tests/test_store_shape.py` holds them to.
"""
from __future__ import annotations

# Everything that was reachable as `store.<name>` before the split still is. The names with a
# leading underscore are the package's own, and are re-exported because tests reach the
# validator and the counters through this module.
import sqlite3  # noqa: F401

from ..machine import (CLAIMED, EXHAUSTED, IN_FLIGHT, OBSERVING, STATES,  # noqa: F401
                       TERMINAL, WAITING, WATCHED)
from .actions import ActionsMixin, MAX_BUDGET_RESETS, UNKNOWN_WINDOW  # noqa: F401
from .claims import ClaimsMixin
from .columns import (_EVENT_COLUMNS, _MUTABLE, _NEEDS_RECOVERY_TURN,  # noqa: F401
                      _NOTICE_COLUMNS, _RECORD_COLUMNS, _SCHEMA_2_COLUMNS, _SCHEMA_3_COLUMNS,
                      _SCHEMA_4_COLUMNS, _SETTINGS_COLUMNS, _THREAD_COLUMNS, _V2_COLUMNS,
                      _V3_COLUMNS, _WATCHER_COLUMNS)
from .downgrade import downgrade_state, downgrade_to_v2, downgrade_to_v3  # noqa: F401
from .errors import (RecordSchemaMismatch, StateFromNewerVersion,  # noqa: F401
                     StoreError, UpgradePending)
from .journal import EVENT_LIMIT, EVENT_MAX_AGE, JournalMixin, _PRUNE_EVERY  # noqa: F401
from .ledger import LedgerMixin
from .legacy import LegacyStore  # noqa: F401
from .migrations import MigrationsMixin
from .notices import NoticesMixin
from .plugclaims import PlugClaimsMixin
from .policy import PolicyMixin
from .records import RecordsMixin
from .reporting import ReportingMixin
from .schedule import ScheduleMixin
from .schema import SCHEMA_VERSION, SchemaMixin, _TABLES_V2, _TABLES_V3, _TABLES_V4  # noqa: F401
from .session import SessionMixin
from .validate import (ENGINE_STATES, WATCHER_ENDS, _choice, _claim_cost, _finite, _flag,  # noqa: F401
                       _integer, _short_text, _sql, _timestamp, _uuid,
                       _validated_notice, _validated_record, _validated_tier, is_usage)
from .watcher import WatcherMixin


class Store(SessionMixin, SchemaMixin, MigrationsMixin, JournalMixin, PolicyMixin,
            RecordsMixin, ClaimsMixin, LedgerMixin, ActionsMixin, ScheduleMixin, WatcherMixin,
            ReportingMixin, NoticesMixin, PlugClaimsMixin):
    """One connection to our own state database.

    ``migrate`` must be passed explicitly: only the watcher, or a caller holding the
    watcher's single-instance mutex, may upgrade an older schema. Anyone else gets
    ``UpgradePending``. ``check`` runs the full integrity check and validates every row
    at open; per-call openers skip it and validate only the rows they read.
    """
