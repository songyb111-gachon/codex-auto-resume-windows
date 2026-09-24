"""What was stored since: the settings the icon reads for itself.

Named `stored`, not `settings`: `codex_auto_resume/settings.py` is a different thing, and a
`tray/settings.py` beside it would make every `from .. import settings` here a puzzle.
"""
from __future__ import annotations

import os


class StoredMixin:
    """Reading the stored settings the icon needs before it opens anything."""

    # ------------------------------------------------------ what was stored since
    def _stored_settings(self):
        """The stored settings through the control layer, read again only when the file changed.

        None when this icon has no control layer that can say. A look at the file's stamp is all
        an unchanged file costs, so it is taken each time somebody opens the popup or the menu.
        """
        read = getattr(self.control, "get_settings", None)
        if read is None:
            return None
        where = getattr(self.control, "settings_path", None)
        stamp = None
        if where is not None:
            try:
                status = os.stat(where())
                stamp = (status.st_mtime_ns, status.st_size)
            except OSError:
                stamp = None
        if stamp is None or stamp != self._settings_stamp or self._settings_values is None:
            self._settings_values = dict(read())
            self._settings_stamp = stamp
        return self._settings_values

    def _adopt_settings(self):
        """Speak the stored Interface language and draw in the stored Theme from this opening on.

        The watcher adopts a changed settings file at its next tick, which can be an hour away,
        and somebody who has just chosen a language or a theme and clicks the icon expects the
        popup and the menu to have it already. So the icon looks for itself before it opens
        either - the same settings, resolved the way the watcher resolves them - and the watcher
        restarts for none of it. The icon does not change with the theme.
        """
        try:
            values = self._stored_settings()
            if values is None:
                return
            from .. import popup as tray_popup
            tray_popup.adopt_settings(values)
            strings = tray_popup.vocabulary(values.get("interface_language"))
            with self._lock:
                changed = strings != self.strings
            if changed:
                self.set_strings(strings)
        except Exception as exc:                # an unreadable file costs the new words, nothing else
            self.log("tray settings read failed (%s)" % type(exc).__name__)

    def _adopt_reduce_motion(self, tray_popup):
        """Take up the stored Reduce motion on the tick that decides whether the icon may move.

        The watcher adopts a changed settings file at its own next tick, poll_seconds away - 30 s
        by default and up to an hour - and a Save in the window wakes nothing, so an icon that
        waited for it kept moving all that time after somebody asked for stillness. It looks for
        itself instead: a look at the file's stamp a second while there is something to move, and
        a read only when the file changed (`_stored_settings`). What it read is set again on every
        such tick, so a watcher tick that read the file just before the save is overruled a second
        later. An unreadable file keeps the setting there is, and is said once until it reads again.
        """
        try:
            values = self._stored_settings()
        except Exception as exc:
            if not self._motion_read_failed:
                self._motion_read_failed = True
                self.log("tray settings read failed (%s)" % type(exc).__name__)
            return
        self._motion_read_failed = False
        if values is not None:
            tray_popup.set_reduce_motion(values.get("reduce_motion"))
