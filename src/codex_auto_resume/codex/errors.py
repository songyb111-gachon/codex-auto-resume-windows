"""What the reader refuses with: one exception, for one reason."""
from __future__ import annotations

# Raised by the platform as well as by this reader, so it is declared below both.
from ..domain.errors import AdapterError

__all__ = ["AdapterError", "SourceError"]


class SourceError(RuntimeError):
    """Safe diagnostic: never include database contents or underlying errors."""
