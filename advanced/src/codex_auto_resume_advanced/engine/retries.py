# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Codex's own retry settings (item 6 of stage 4) - hidden until Codex lets them be changed.

How many times Codex retries a failed request and stream is two settings of its built-in provider,
`model_providers.openai.request_max_retries` and `stream_max_retries`. MB measured on codex-cli 0.162.0-alpha.17.2 that
Codex refuses any write under model_providers.openai (config/value/write, -32600), so on that Codex nothing here can
work - and on codex-cli 0.166.0-alpha.5.1 (2026-10-31) MB failed the same way: it is hidden because its measurement
failed. The owner's rule of 2026-10-16 keeps such a capability out of sight: no row on the Advanced features page, no
statement, no switch (registry.WAITING, offered only once MB passes - registry.offered).

This is its definition's code while it waits: it answers nothing. When a later Codex passes MB, the writer that keeps
each prior value and puts it back (turned off, read down, the product leaving) is built here from the stage-4 draft
(commit 3d4da6c6, engine/retries.py and state/runs.py's codex_config), its statements added to the catalogs, and the
capability moved from WAITING into DEFINITIONS.
"""
from __future__ import annotations

from codex_auto_resume.domain.plug import DEFER

CAPABILITY = "codex_retry_settings"
ATTEMPTS = (6, 8, 10, 12)
DEFAULT_ATTEMPTS = 8


class RetrySettings:
    """The waiting capability's code: its P8 tick answers nothing."""
    __slots__ = ("paths",)

    def __init__(self, paths):
        self.paths = paths

    def tick(self, view):
        return DEFER


def make(paths) -> RetrySettings:
    return RetrySettings(paths)
