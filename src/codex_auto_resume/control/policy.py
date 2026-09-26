"""The settings, as this layer offers them.

Named `policy` and not `settings`: the module it calls is `codex_auto_resume/settings.py`, and
two files of that name one directory apart is a puzzle for a reader whatever Python resolves.

From v0.6.11 the settings every surface is shown, and the watcher works from, are the stored ones as
an administrator's policy keys leave them (managed.py): read here, where the keys are asked for, and
applied after the settings are read, never written into the file.
"""
from __future__ import annotations

from .. import config, managed, settings
from ..store import StoreError
from ..win import policykeys
from .errors import ControlError


def managed_policy() -> managed.Managed:
    """What an administrator's policy keys hold (managed.py), asked afresh each time.

    Only an installed copy asks Windows - the copy an administrator's PC runs, from its `app`
    folder (config.installed_home). A copy run from a source checkout is managed by nothing, and
    that is what keeps the test suite, which runs from one, off this machine's registry; a test
    that means to be managed says so by standing in for this function."""
    if config.installed_home() is None:
        return managed.NONE
    return managed.parse(policykeys.read())


class SettingsMixin:
    """Reading, writing and describing the stored settings."""

    # ------------------------------------------------------------------ settings
    def settings_path(self) -> Path:
        return self.paths.settings_file

    def managed(self) -> managed.Managed:
        """The policy keys in force now: managed_policy, looked up when asked, so a test that stands
        in for it is asked instead."""
        return managed_policy()

    def get_settings(self) -> dict:
        return managed.clamp(settings.load(self.settings_path()), self.managed())

    def update_settings(self, changes: dict) -> dict:
        held = self.managed()
        try:
            if held.active:
                # Checked as ever first, so a wrong value is refused in the validator's own words;
                # then a setting a key decides keeps what the key says (managed.admit).
                settings.validate_update(changes)
                effective = managed.clamp(settings.load(self.settings_path()), held)
                changes, refused = managed.admit(changes, effective, held)
                if refused is not None:
                    raise ControlError("%s is set by your administrator" % refused, code="managed_by_policy")
            saved = settings.update(self.settings_path(), changes)
        except settings.SettingsError as exc:
            # The sentence is the validator's own and names the setting it refused. The
            # closed set has no code for "this value is out of range", because a code is
            # there for a refusal a front end must word itself and both settings surfaces
            # already frame this one in their own language - "Not saved: {reason}" - around
            # the English detail. So this carries the generic code deliberately.
            raise ControlError(str(exc), code="request_failed") from None
        saved = managed.clamp(saved, held)
        if isinstance(changes, dict) and "observe_only" in changes or held.force_observe_only:
            self._observe_only(saved)
        return saved

    def restore_defaults(self) -> dict:
        try:
            saved = settings.save(self.settings_path(), settings.defaults())
        except settings.SettingsError as exc:
            # Generic for the same reason as `update_settings` above.
            raise ControlError(str(exc), code="request_failed") from None
        saved = managed.clamp(saved, self.managed())
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
        """settings.describe(), with `"managed": true` on each setting a policy key decides while
        one does - which every surface draws greyed, as set by your administrator. With no key set,
        exactly settings.describe()."""
        described = settings.describe()
        decided = managed.fields(self.managed())
        if decided:
            described = [dict(entry, managed=True) if entry["name"] in decided else entry
                         for entry in described]
        return described
