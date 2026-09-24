"""Every way this layer refuses, and the two ways it reads an identity.

The refusal codes are a closed vocabulary on purpose: `interface.py` carries an `error.<code>`
string for every member in every language, and the suite refuses both a raise whose code is not
here and a code that reaches the catalogues with nothing to say it.
"""
from __future__ import annotations

from ..domain import ids, vocabulary
from ..store import MAX_BUDGET_RESETS



# Every way this layer can refuse a request, as a stable machine value. The English
# sentence beside each one is what the command line prints and what a support log keeps;
# the code is what a front end looks up in the language the rest of the product is already
# speaking, because a window whose own lead sentence is Korean and whose explanation is
# English has told half the story in the wrong language.
#
# The vocabulary is closed on purpose. `interface.py` carries an `error.<code>` string for
# every member in every language, and the tests refuse both a raise whose code is not here
# and a code that reaches the catalogs without a sentence to say it, so a new refusal
# cannot quietly arrive untranslated.
ERROR_CODES = frozenset(vocabulary.ErrorCode)
# The code for a refusal with nothing more specific to say, and the one every caller may
# assume is present. A rejection carrying no code at all would leave a front end holding
# the English sentence with no way to say it, which is the gap the codes exist to close,
# so the default is a real member of the set and never None.
FALLBACK_CODE = "request_failed"


class ControlError(RuntimeError):
    """A rejected request. The message is safe to show a user.

    `str(exc)` is exactly the English sentence it has always been, because the command
    line prints it and the logs keep it. `code` is that same refusal as one of
    `ERROR_CODES`, so a front end can say it in the person's own language instead of
    parsing prose that was never meant to be parsed.
    """

    def __init__(self, message, *, code: str = FALLBACK_CODE):
        super().__init__(message)
        self.code = code or FALLBACK_CODE


# What the store says when it refuses to restore a budget or to bring a check forward, as
# the sentence a person reads and the code a front end translates. Each detail keeps its
# own code rather than sharing one "cannot" for the group: "it was cancelled", "it may
# already have been sent" and "you have given it its attempts back as often as you may"
# have three different next steps, and one code for the three would hand every front end a
# single unhelpful sentence to show for all of them.
#
# The entry under None is each table's own last resort, so a detail this layer has never
# heard of - a store a version ahead, a record that vanished between two statements - still
# arrives as a coded rejection rather than as an uncoded one.
_REFUSALS_RESTORE = {
    "not_exhausted": ("that recovery has not been exhausted", "not_exhausted"),
    "finished": ("that recovery has already finished", "already_finished"),
    "cancel_requested": ("that recovery was cancelled", "cancel_requested"),
    "possibly_sent": ("that recovery may already have been sent", "possibly_sent"),
    # Left as a template: the count belongs to this layer's own constant, and a sentence
    # frozen at import stops following it the moment that constant moves.
    "reset_limit": ("its budget was already reset %d times; continue this task in Codex "
                    "yourself", "reset_limit"),
    # The record went between the read and the write - the watcher can finish one and the
    # row can be hidden. That is not a refusal of policy, and saying so would send a person
    # looking for a rule that does not exist.
    "unknown_record": ("no such interruption", "no_such_interruption"),
    None: ("that recovery cannot be continued", "cannot_continue"),
}
_REFUSALS_RETRY = {
    "finished": ("that recovery has already finished", "already_finished"),
    "cancel_requested": ("that recovery was cancelled", "cancel_requested"),
    "claimed": ("that recovery is being sent now", "being_sent"),
    "in_flight": ("that recovery is already in Codex", "in_flight"),
    "observing": ("that recovery is already running in Codex", "observing"),
    "unknown_record": ("no such interruption", "no_such_interruption"),
    None: ("that recovery cannot be checked now", "cannot_check_now"),
}


def _refusal(table: dict, detail) -> tuple:
    """The sentence and the code for what the store refused, or the table's last resort."""
    message, code = table.get(detail) or table[None]
    return (message % MAX_BUDGET_RESETS if "%d" in message else message), code


def _identifier(value, name="interruption id") -> str:
    """Interruption ids are opaque lowercase hex. Nothing else addresses a record."""
    key = ids.read_interruption_id(str(value or ""))
    if key is None:
        raise ControlError("invalid %s" % name, code="invalid_id")
    return key


def _thread_id(value) -> str:
    """Any value, read as its text, that is a thread id; a UUID written another way is refused
    with a sentence saying so."""
    problem = ids.uuid_problem(value, as_text=True)
    if problem == ids.MALFORMED:
        raise ControlError("thread id must be a canonical UUID", code="invalid_thread_id")
    if problem is not None:
        raise ControlError("thread id must be lowercase canonical UUID text", code="invalid_thread_id")
    return str(value)
