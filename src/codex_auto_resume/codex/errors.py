"""What the reader refuses with: one exception, for one reason."""
from __future__ import annotations


class SourceError(RuntimeError):
    """Safe diagnostic: never include database contents or underlying errors."""
