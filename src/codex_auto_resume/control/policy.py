"""The settings, as this layer offers them.

Named `policy` and not `settings`: the module it calls is `codex_auto_resume/settings.py`, and
two files of that name one directory apart is a puzzle for a reader whatever Python resolves.
"""
from __future__ import annotations

from .. import settings
from .errors import ControlError


class SettingsMixin:
    """Reading, writing and describing the stored settings."""

    # ------------------------------------------------------------------ settings
    def settings_path(self) -> Path:
        return self.paths.settings_file

    def get_settings(self) -> dict:
        return settings.load(self.settings_path())

    def update_settings(self, changes: dict) -> dict:
        try:
            return settings.update(self.settings_path(), changes)
        except settings.SettingsError as exc:
            # The sentence is the validator's own and names the setting it refused. The
            # closed set has no code for "this value is out of range", because a code is
            # there for a refusal a front end must word itself and both settings surfaces
            # already frame this one in their own language - "Not saved: {reason}" - around
            # the English detail. So this carries the generic code deliberately.
            raise ControlError(str(exc), code="request_failed") from None

    def restore_defaults(self) -> dict:
        try:
            return settings.save(self.settings_path(), settings.defaults())
        except settings.SettingsError as exc:
            # Generic for the same reason as `update_settings` above.
            raise ControlError(str(exc), code="request_failed") from None

    def describe_settings(self) -> list:
        return settings.describe()
