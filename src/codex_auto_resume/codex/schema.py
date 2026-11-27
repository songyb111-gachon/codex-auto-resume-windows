"""Finding Codex's databases, and refusing one whose schema has moved.

Codex names its files with a schema generation - `state_5.sqlite`, `thread_history_1.sqlite` -
and an update can bump that number, so a database is found by pattern and then checked against
the columns this product actually reads (`DB_KINDS`). A missing column means the schema moved,
and the answer to that is to refuse rather than to guess.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import re
import sqlite3
from .errors import HistoryNotYet, SourceError
from .chains import memory as chain_memory
from .paths import DB_KINDS, _safe_path, newest_generation


class SchemaMixin:
    def __init__(self, codex_home: Path, chains=None):
        self.home = _safe_path(Path(codex_home))
        # v0.6.16-beta.3: the ids each split conversation has had (codex/chains.py) - the watcher's file, or this
        # process's own.
        self.chains = chains if chains is not None else chain_memory()

    def _connect(self, path):
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=3)
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _schema_ok(connection, tables) -> bool:
        for table, required in tables.items():
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
                return False
            found = {row[1] for row in connection.execute("PRAGMA table_info(%s)" % table)}
            if not required <= found:
                return False
        return True

    def resolve(self, kind: str) -> str:
        """The newest generation, only if its current schema is supported.

        Older files can survive a Codex migration. They are not a fallback: their
        history and queue can be stale. Discover on every read so a running watcher
        never stays attached to the pre-migration database.
        """
        tables = DB_KINDS[kind][1]
        try:
            path = newest_generation(self.home, kind)
        except OSError:
            raise SourceError("Codex local state unavailable or unsupported") from None
        if path is not None:
            connection = None
            try:
                connection = self._connect(_safe_path(path))
                if self._schema_ok(connection, tables):
                    return path.name
            except (sqlite3.Error, OSError, ValueError):
                pass
            finally:
                if connection is not None:
                    connection.close()
        elif kind == "history" and self._history_not_made():
            raise HistoryNotYet("No Codex history database yet")
        raise SourceError("No Codex %s database with the required schema" % kind)

    def _history_not_made(self) -> bool:
        """v0.6.26 final: whether a home with no history database is one Codex has not made it in yet - its newest state
        database read, and holding no conversation (HistoryNotYet). Anything that cannot be read is no: the refusal as
        it always was."""
        try:
            return self._no_conversation()
        except Exception:
            return False

    @contextmanager
    def _db(self, kind):
        connection = None
        try:
            path = _safe_path(self.home / self.resolve(kind))
            if path.parent != self.home:
                raise SourceError("Codex database path is outside configured home")
            connection = self._connect(path)
            yield connection
        except (sqlite3.Error, OSError, ValueError):
            raise SourceError("Codex local state unavailable or unsupported") from None
        finally:
            if connection is not None:
                connection.close()

    # v0.6.16-beta.3: two facts for the Diagnostics check (checkup.py), neither of them a conversation's.
    GLOBAL_STATE = ".codex-global-state.json"
    CLOUD_PREFIX = "cloud-thread-prototype-threads-by-account-v1."
    MAX_GLOBAL_STATE = 16 * 1024 * 1024

    def written(self) -> dict:
        """When this home's newest state and history databases were last written: their files' - and their
        write-ahead logs' - modification times, one stat each, nothing opened; None where there is none."""
        found = {}
        for kind in ("state", "history"):
            path, times = newest_generation(self.home, kind), []
            for each in () if path is None else (path, path.with_name(path.name + "-wal")):
                try:
                    times.append(each.stat().st_mtime)
                except OSError:
                    pass
            found[kind + "_written"] = max(times) if times else None
        return found

    def cloud_tasks(self):
        """How many cloud tasks the app knows: the entries under its `CLOUD_PREFIX` keys in the home's
        GLOBAL_STATE file, a count and nothing of them - or None where the file cannot be read as JSON."""
        path = self.home / self.GLOBAL_STATE
        try:
            if path.is_symlink() or path.stat().st_size > self.MAX_GLOBAL_STATE:
                return None
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, RecursionError):
            return None
        count, stack = 0, [(data, 0)]
        while stack:
            value, depth = stack.pop()
            if not isinstance(value, dict) or depth > 4:
                continue
            for key, held in value.items():
                if isinstance(key, str) and key.startswith(self.CLOUD_PREFIX):
                    count += len(held) if isinstance(held, (list, dict)) else 1
                else:
                    stack.append((held, depth + 1))
        return count
