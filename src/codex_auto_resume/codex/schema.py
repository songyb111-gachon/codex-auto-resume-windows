"""Finding Codex's databases, and refusing one whose schema has moved.

Codex names its files with a schema generation - `state_5.sqlite`, `thread_history_1.sqlite` -
and an update can bump that number, so a database is found by pattern and then checked against
the columns this product actually reads (`DB_KINDS`). A missing column means the schema moved,
and the answer to that is to refuse rather than to guess.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import re
import sqlite3
from .errors import SourceError
from .paths import DB_KINDS, _safe_path


class SchemaMixin:
    def __init__(self, codex_home: Path):
        self.home = _safe_path(Path(codex_home))

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
        pattern, tables = DB_KINDS[kind]
        candidates = []
        try:
            for entry in self.home.iterdir():
                match = pattern.fullmatch(entry.name)
                if match and entry.is_file() and not entry.is_symlink():
                    candidates.append((int(match.group(1)), entry))
        except OSError:
            raise SourceError("Codex local state unavailable or unsupported") from None
        for _, path in sorted(candidates, key=lambda item: -item[0])[:1]:
            connection = None
            try:
                connection = self._connect(_safe_path(path))
                if self._schema_ok(connection, tables):
                    return path.name
            except (sqlite3.Error, OSError, ValueError):
                continue
            finally:
                if connection is not None:
                    connection.close()
        raise SourceError("No Codex %s database with the required schema" % kind)

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
