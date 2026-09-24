"""What this product refuses with, carrying only a reason.

One exception, raised by the Codex adapter and by the Windows platform under it, holding a
static reason code and never the output of the process or protocol that failed. A refusal is
shown to a person and written to the log, so what it may contain is a domain rule.
"""
from __future__ import annotations


class AdapterError(RuntimeError):
    """Contains only a static reason code; never raw CLI/protocol output."""
