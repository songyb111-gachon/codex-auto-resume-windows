"""The one door to the state, and what this layer says when it cannot open it.

Every method that reads or writes goes through `_open`, so there is one place where a store
that will not open becomes a refusal a front end can show.
"""
from __future__ import annotations

from ..openstate import UPGRADE_PENDING, open_state
from ..store import StateFromNewerVersion, StoreError, UpgradePending
from .errors import ControlError


NEWER_STATE = ("The recovery state was written by a newer version of Codex Auto Resume. "
               "Update this installation; do not delete the state.")


def _unavailable(exc) -> ControlError:
    return ControlError("local state is unavailable: %s" % exc, code="store_unavailable")


class StateMixin:
    """Opening the store, once, for whoever asks."""

    # ------------------------------------------------------------------- state
    def _open(self, *, legacy_ok: bool = False):
        """The state, opened as every per-call opener opens it (openstate.open_state).

        While an older watcher still holds an older state, only the actions that reduce
        automation are offered its store (`legacy_ok`); everything else says the upgrade is
        pending. A failed upgrade is reported as the state being unavailable.
        """
        try:
            return open_state(self.paths.state_dir, legacy="if_reducing", reducing=legacy_ok,
                              upgrade_failed=_unavailable)
        except UpgradePending:
            raise ControlError(UPGRADE_PENDING, code="upgrade_pending") from None
        except StateFromNewerVersion:
            raise ControlError(NEWER_STATE, code="newer_state") from None
        except StoreError as exc:
            raise _unavailable(exc) from None
