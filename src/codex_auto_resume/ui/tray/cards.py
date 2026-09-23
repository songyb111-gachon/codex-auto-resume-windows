"""Hosting the notification card on the icon's thread.

The card has its own window and its own module; what is here is the decision to host it and
the look it is given, both of which belong to whoever owns the thread.
"""
from __future__ import annotations


class CardsMixin:
    """The notification card, hosted on this thread."""

    # ------------------------------------------------------------- the notification card
    def _host_cards(self):
        """Host the notification card on this thread, if this icon was given an inbox.

        A stack that cannot be made costs the card only: the inbox stays detached, and the
        notifier raises today's toast for everything, as it does with no icon at all.
        """
        if self.inbox is None:
            return
        try:
            from ... import notice_window
            from .. import popup as tray_popup
            self._cards = notice_window.CardStack(on_action=self.on_notice_action,
                                                  on_complete=self.on_notice_complete, log=self.log,
                                                  anchor=lambda: tray_popup.icon_rect(self._hwnd, 1),
                                                  inbox=self.inbox, appearance=self._card_look).create()
        except Exception as exc:
            self._cards = None
            self.log("notification card unavailable (%s)" % type(exc).__name__)

    def _card_look(self):
        """How the next card is drawn: the Theme and Reduce motion stored now, as the popup and the
        menu take them up when they open (`_adopt_settings`), then Windows' own answers."""
        from ... import notice_window
        self._adopt_settings()
        return notice_window.look()

    def _drop_cards(self):
        """Take the cards down with the icon. The stack lets go of the inbox first, so a notice
        from now on is today's toast, and ends every notice it held (notice_window.CardStack)."""
        cards, self._cards = self._cards, None
        if cards is not None:
            try:
                cards.destroy()
            except Exception as exc:
                self.log("notification card cleanup failed (%s)" % type(exc).__name__)
