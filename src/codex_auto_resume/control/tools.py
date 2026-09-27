"""Diagnostics' own tools (v0.6.11): the logs searched, who may open the state folder, and a demo.

Each only reads, and each is asked only when a person asks for it in the Dashboard - none is an MCP
tool, and none reaches the store, the engine or Codex:

* `search_logs` reads this product's own log - written from a fixed table of messages (logbook.py),
  so it holds reason codes, ids and times and never a prompt, a reply or an error's text - and gives
  back the lines that match, newest last. errors.log, which keeps exception messages unfiltered, is
  not read.
* `state_access` asks Windows who may open the state folder (win/acl.py) and gives back one word.
* `show_demo` asks the watcher's icon to draw one made-up card (win/sync.py DemoEvent) and gives the
  Dashboard the made-up rows it plays (demo.py). Nothing it touches is written anywhere.
"""
from __future__ import annotations

import re
import time

from .. import demo
from ..logbook import BACKUP_COUNT
from ..win import acl
from ..win.sync import DemoEvent
from .errors import ControlError

# A line as logbook's formatter writes it: its time, then the message. Anything else is not read.
LOG_LINE = re.compile(r"\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\] ([^\r\n]{1,2000})\Z")
# The most lines one answer carries, the longest search, and the most of each file read.
LOG_LIMIT = 500
MAX_QUERY = 100
MAX_LOG_BYTES = 2 * 1024 * 1024


class ToolsMixin:
    """What Diagnostics asks for, on request, and nothing that changes anything."""

    def _log_files(self) -> list:
        """The log and its rotated copies, oldest first (auto-resume.log.5 ... auto-resume.log)."""
        main = self.paths.log_file
        older = [main.with_name("%s.%d" % (main.name, number)) for number in range(BACKUP_COUNT, 0, -1)]
        return [path for path in older + [main] if path.is_file() and not path.is_symlink()]

    def search_logs(self, query=None, limit=LOG_LIMIT) -> dict:
        """The log's lines that hold `query` - every line for none - newest last, at most `limit`.

        `lines` are {"at", "text"}: the time as the log wrote it and the rest of the line. `matched`
        counts every line that matched and `total` every line read, so a surface can say how many
        it is not showing. A search is at most MAX_QUERY characters, with no control character; the
        match ignores case."""
        if query is not None and (not isinstance(query, str) or len(query) > MAX_QUERY
                                  or any(ord(character) < 32 for character in query)):
            raise ControlError("that is not something to search the log for", code="request_failed")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= LOG_LIMIT:
            limit = LOG_LIMIT
        wanted = (query or "").strip().casefold()
        found, total = [], 0
        for path in self._log_files():
            try:
                with path.open("rb") as stream:
                    size = stream.seek(0, 2)
                    stream.seek(max(0, size - MAX_LOG_BYTES))
                    text = stream.read().decode("utf-8", errors="replace")
            except OSError:
                continue
            for line in text.splitlines():
                match = LOG_LINE.match(line)
                if match is None:
                    continue
                total += 1
                if not wanted or wanted in line.casefold():
                    found.append({"at": match.group(1), "text": match.group(2)})
        return {"lines": found[-limit:], "matched": len(found), "total": total, "query": query or ""}

    def state_access(self) -> dict:
        """Who Windows lets open the state folder: owner_only, shared or unknown (win/acl.py)."""
        return {"access": acl.state_access(self.paths.state_dir)}

    def show_demo(self) -> dict:
        """Show me what happens: the made-up rows the Dashboard plays (demo.rows), and whether the
        watcher's icon was asked to draw the made-up card - False when no watcher is running, which
        leaves the rows to show on their own. Nothing is read from the state or written to it."""
        try:
            asked = bool(DemoEvent(str(self.paths.state_dir)).signal())
        except Exception:
            asked = False
        return dict(demo.rows(time.time()), asked=asked)
