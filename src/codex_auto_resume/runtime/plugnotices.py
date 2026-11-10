"""The notices an edition's plug adds to the icon's snapshot, shown by the watcher.

The advanced edition's usage meter, update check and account switch say what happened in the snapshot; the watcher shows
each once in its life, under the notifications switch and off the tick path. The standard edition adds none.
"""
from __future__ import annotations

from ..domain.plug import DEFER


class PlugNotices:
    """The watcher's part (App): `_watcher_notice` is App's."""

    def _edition_notices(self, added):
        """What the edition's plug added to the icon's snapshot, for the watcher: the meter's warnings, from v0.6.18 the
        update check's offers and whether a notice offers Open Codex, from v0.6.19 whether the in-app chat is on
        (notifier.click_destination), from v0.6.20 a change of account - each only while the plug says so."""
        notice = (added if isinstance(added, dict) else {}).get("notice")
        self._open_codex = isinstance(notice, dict) and notice.get("open_codex") is True
        self._chat = isinstance(notice, dict) and notice.get("chat") is True
        if added is not DEFER:
            for shown in (self._near_limit, self._update_offered, self._account_changed):
                shown(added)

    def _update_offered(self, added):
        """The advanced edition's weekly update check offers a newer version (v0.6.18): each offer shown once in this
        watcher's life (_unshown), under the notifications switch, off the tick path. The standard edition adds none."""
        for notice in _unshown(self, added, "update"):
            self._watcher_notice("update_offered", {"version": notice.get("version"),
                                                    "prerelease": notice.get("prerelease") is True})

    def _account_changed(self, added):
        """v0.6.20: the advanced edition's account switch saw another Codex account signed in - each change, with how
        many recoveries it held, shown once in this watcher's life (_unshown), as the update check's offers are; v0.6.22:
        and each time the automatic switch found every saved account at its limit, the same way."""
        for notice in _unshown(self, added, "account"):
            self._watcher_notice("account_changed", {"count": notice.get("count")})
        for notice in _unshown(self, added, "autoswitch"):
            self._watcher_notice("accounts_exhausted", {"why": notice.get("why")})

    def _near_limit(self, added):
        """The advanced edition's usage meter at a warning (v0.6.16-beta.3, issue #29): each notice shown once in this
        watcher's life by its key - a window and its reset (_unshown). The standard edition adds none."""
        for notice in _unshown(self, added, "meter", "_near_limit_shown"):
            # v0.6.16-beta.4: `kind` is what the forced stop says, a closed word, else a warning.
            self._watcher_notice("near_limit", {"minutes": notice.get("window_minutes"), "percent": notice.get(
                "used_percent"), "reset_at": notice.get("reset_at"), "kind": notice.get("kind")})


def _unshown(owner, added, part, shown_name=None):
    """The notices under `part` of what the edition's plug added to the icon's snapshot that the watcher `owner` has
    not shown in its life, by their keys (at most 64), each marked shown as it is given."""
    found = added.get(part) if isinstance(added, dict) else None
    notices = found.get("notices") if isinstance(found, dict) else None
    shown = owner.__dict__.setdefault(shown_name or "_%s_shown" % part, set())
    for notice in notices if isinstance(notices, list) else ():
        key = notice.get("key") if isinstance(notice, dict) else None
        if isinstance(key, str) and key not in shown and len(shown) <= 64:
            shown.add(key)
            yield notice
