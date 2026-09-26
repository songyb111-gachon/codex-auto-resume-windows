"""The settings, as this layer offers them.

Named `policy` and not `settings`: the module it calls is `codex_auto_resume/settings.py`, and
two files of that name one directory apart is a puzzle for a reader whatever Python resolves.
"""
from __future__ import annotations

from .. import settings
from ..store import StoreError
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
            saved = settings.update(self.settings_path(), changes)
        except settings.SettingsError as exc:
            # The sentence is the validator's own and names the setting it refused. The
            # closed set has no code for "this value is out of range", because a code is
            # there for a refusal a front end must word itself and both settings surfaces
            # already frame this one in their own language - "Not saved: {reason}" - around
            # the English detail. So this carries the generic code deliberately.
            raise ControlError(str(exc), code="request_failed") from None
        if isinstance(changes, dict) and "observe_only" in changes:
            self._observe_only(saved)
        return saved

    def restore_defaults(self) -> dict:
        try:
            saved = settings.save(self.settings_path(), settings.defaults())
        except settings.SettingsError as exc:
            # Generic for the same reason as `update_settings` above.
            raise ControlError(str(exc), code="request_failed") from None
        self._observe_only(saved)
        return saved

    def _observe_only(self, values: dict) -> None:
        """Write Observe only into the state as the settings now say it (v0.6.11), where the claim
        itself refuses every send while it is on. A state that cannot take it now - an older watcher
        still owns it, or it is busy - is left to the watcher, which writes it from the settings the
        next time it reads them (runtime/app.py); until then its engine refuses on the setting alone."""
        try:
            with self._open() as store:
                store.set_observe_only(bool(values.get("observe_only")))
        except (ControlError, StoreError):
            pass

    def describe_settings(self) -> list:
        return settings.describe()
