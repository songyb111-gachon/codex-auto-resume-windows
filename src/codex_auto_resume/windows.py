"""Windows adapter. Only documented Win32 APIs and the pinned official Codex CLI.

Writer-lock ownership is a version-pinned implementation dependency, not a public
loaded-state endpoint. Unknown ownership fails closed. No GUI or private pipe.

Since v0.6.10-alpha this is the front, and the two halves it was are apart. One module was
two of the eight parts `docs/ROADMAP.md` says the Rust core is built from - the Codex
adapters and the platform under them - which is one port done twice, and the second one is
where the behaviour quietly changes. Everything is re-exported here, so nothing that imports
`windows` changes.
"""
from __future__ import annotations

from .codex.appserver import PROTOCOL_METHODS, Protocol
from .codex.errors import AdapterError
from .codex.pairing import desktop_pair, inventory
from .codex.transport import (Backend, FAIL, PASS, REQUIRED_QUEUE_FLAGS, UNAVAILABLE,
                              canonical_uuid, verified_versions)
from .codex.usage import parse_usage
from .win.homelock import HomeLock, INSTALL_LOCK, install_in_progress
from .win.inventory import resource_users, restart_manager_available
from .win.kernel import (APPMODEL_ERROR_NO_PACKAGE, CREATE_BREAKAWAY_FROM_JOB,
                         JOB_BREAKAWAY_OK, JOB_KILL_ON_CLOSE, JOB_SILENT_BREAKAWAY_OK,
                         NO_WINDOW, process_context, process_identity)
from .win.sync import Mutex, StopEvent, WakeEvent, wait_any

__all__ = ["APPMODEL_ERROR_NO_PACKAGE", "AdapterError", "Backend", "CREATE_BREAKAWAY_FROM_JOB",
           "FAIL", "HomeLock", "INSTALL_LOCK", "JOB_BREAKAWAY_OK", "JOB_KILL_ON_CLOSE",
           "JOB_SILENT_BREAKAWAY_OK", "Mutex", "NO_WINDOW", "PASS", "PROTOCOL_METHODS",
           "Protocol", "REQUIRED_QUEUE_FLAGS", "StopEvent", "UNAVAILABLE", "WakeEvent",
           "canonical_uuid", "desktop_pair",
           "install_in_progress", "inventory", "parse_usage", "process_context",
           "process_identity", "resource_users", "restart_manager_available",
           "verified_versions", "wait_any"]
