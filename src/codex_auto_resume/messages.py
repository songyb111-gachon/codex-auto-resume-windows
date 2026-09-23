"""Kept by name only, for scripts outside this package.

The plugin's own sentences live in `l10n` (l10n.message, l10n.messages, l10n.current), and
nothing in this package imports this module. But every release up to v0.6.4 ships a
`scripts/plugin_setup.py` that does `from codex_auto_resume import ..., messages, ...` and
calls `messages.text(key)`, and tests/test_installer_ownership.py runs v0.5.3's against this
package to prove it cannot answer `verify-home`. Without this line such a script fails on the
import instead of on the command it lacks.
"""
from .l10n import message as text  # noqa: F401
