"""The one layer every surface asks, and the only one that may change anything.

`control.py` was 1,083 lines. It is the same layer in ten files, and every `control.<name>`
reads as it did.

    errors      every way this layer refuses, and how it reads an identity
    state       the one door to the store, and what a refusal to open says
    seen        when a failure was last seen, and the file that remembers
    policy      the settings, read, written and described
    records     one record as every interface shows it, and the three listings
    preview     the message the watcher would send, without sending it
    actions     what a person asks for: a flag, a schedule, a budget
    codexstart  the launch Codex asks for, and the note saying why it was refused
    watcher     whether it runs, whether it starts at sign-in, starting and stopping it
    layer       `Control` composed from the eight mixins above

Nothing here sends. The watcher is the only thing that hands anything to Codex, and every
method in `actions` changes a flag, a schedule or a budget and then stops - which is the rule
`tests/test_structural_invariants.py` reads this package for.
"""
from __future__ import annotations

from .errors import (ControlError,
                     ERROR_CODES,
                     FALLBACK_CODE,
                     _REFUSALS_RESTORE,
                     _REFUSALS_RETRY,
                     _identifier,
                     _refusal,
                     _thread_id)  # noqa: F401
from .state import NEWER_STATE, _unavailable  # noqa: F401
from .seen import SEEN_LIMIT, SEEN_SKEW, _replace_seen, unseen_failure  # noqa: F401
from .records import _REASON_UNCHANGED, describe_record  # noqa: F401
from .actions import CANCEL_RETRY_SECONDS  # noqa: F401
from .codexstart import CODEX_START_LOG_LINES, _context_words, _note_line  # noqa: F401
from .watcher import (TICK_STALE_SECONDS,
                      WATCHER_START_INTERVAL,
                      WATCHER_START_TIMEOUT,
                      WATCHER_STOP_INTERVAL,
                      WATCHER_STOP_TIMEOUT,
                      _version,
                      await_stopped,
                      await_watcher)  # noqa: F401
from .layer import Control  # noqa: F401
