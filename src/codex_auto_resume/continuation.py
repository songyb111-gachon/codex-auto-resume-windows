"""The one place a continuation message is built.

Every continuation this product sends comes out of `build()`, and so does every preview
of one. That is the whole point of the module: a Preview that renders its own
approximation of the message is a Preview of nothing, and the way that bug reaches a
user is that the two code paths were written on different days.

What the text depends on:

    classified category  x  language  x  style  x  the user's Custom settings

and, where the category actually has it, a small amount of metadata that is already
known and already safe to say out loud.

What it must never depend on, and cannot, because none of it is passed in: the user's
prompt, the assistant's reply, the conversation title, a file path, a Windows account
name, a raw error string, a token. The placeholder whitelist below is the enforcement,
and it is a whitelist rather than a blacklist so that a placeholder invented next year
is refused by default instead of quietly resolving to something.

Style is presentation, never permission. `build()` is called after the engine has
already decided the interruption is recoverable and every gate has passed; it cannot
make an unknown failure recoverable, and it is never asked to build text for one -
`reasons.py` gives a non-recoverable category no continuation keys at all.
"""
from __future__ import annotations

import re
import time

from . import failures, l10n, reasons
from .domain.vocabulary import ContinuationStyle, CustomMode

# Minimal is short on purpose and says nothing about the cause. Standard names the
# safely known reason. Detailed asks for the work to be continued from where it
# stopped. Custom is the user's own words.
STYLES = tuple(ContinuationStyle)
DEFAULT_STYLE = "standard"

# One message for everything, or one per interruption category.
CUSTOM_MODES = tuple(CustomMode)
DEFAULT_CUSTOM_MODE = "global"

# Long enough for a paragraph somebody actually wants to send, short enough that it
# cannot become a place to paste a transcript into the conversation.
MAX_CUSTOM_LENGTH = 2000

# Values this product knows, can produce deterministically, and can say without
# revealing anything about the work. Anything not on this list is refused by name.
ALLOWED_PLACEHOLDERS = ("reason", "category", "attempt", "max_attempts", "reset_time")

# Named individually so the refusal can say why, rather than "unknown placeholder".
# These are the ones somebody would plausibly reach for, and each of them would put
# either private content or an account detail into a message sent to a model.
FORBIDDEN_PLACEHOLDERS = {
    "prompt": "the text you sent",
    "reply": "the assistant's answer",
    "conversation_title": "the conversation's title",
    "project_path": "a path on this machine",
    "path": "a path on this machine",
    "cwd": "a path on this machine",
    "username": "your Windows account name",
    "user": "your Windows account name",
    "raw_error": "the unredacted error",
    "error": "the unredacted error",
    "account": "your account",
    "email": "your e-mail address",
    "credential": "a credential",
    "token": "a token",
}

PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


class CustomMessageError(ValueError):
    """A Custom message that will not be stored. The sentence names what to change.

    `code` is the same refusal as a machine value (`not_text`, `empty`, `too_long`,
    `forbidden_placeholder`, `unknown_placeholder`) and `detail` the one fact it needs -
    the placeholder, or the length - so a surface can say it in the reader's language
    instead of showing this English sentence inside a translated window.
    """

    def __init__(self, message, code="invalid", detail=None):
        super().__init__(message)
        self.code = code
        self.detail = detail


def validate_custom(text) -> str:
    """The text unchanged, or a refusal a person can act on.

    Nothing is rewritten - not the spacing, not the line breaks, not the wording. A
    message is sent exactly as it was typed, so the only two answers this can give are
    "stored as you wrote it" and "refused, and here is why". Trimming would be a third,
    and a product that silently edits what you asked it to say is worse than one that
    tells you no.
    """
    if not isinstance(text, str):
        raise CustomMessageError("A custom message has to be text.", "not_text")
    if not text.strip():
        raise CustomMessageError("A custom message cannot be empty.", "empty")
    if len(text) > MAX_CUSTOM_LENGTH:
        raise CustomMessageError(
            "A custom message can be at most %d characters; this one is %d."
            % (MAX_CUSTOM_LENGTH, len(text)), "too_long", str(len(text)))
    for name in PLACEHOLDER.findall(text):
        lowered = name.lower()
        if lowered in FORBIDDEN_PLACEHOLDERS:
            raise CustomMessageError(
                "{%s} is not available: it would put %s into the message."
                % (name, FORBIDDEN_PLACEHOLDERS[lowered]), "forbidden_placeholder", "{%s}" % name)
        if name not in ALLOWED_PLACEHOLDERS:
            raise CustomMessageError(
                "{%s} is not a placeholder this product knows. Available: %s."
                % (name, ", ".join("{%s}" % allowed for allowed in ALLOWED_PLACEHOLDERS)),
                "unknown_placeholder", "{%s}" % name)
    return text


def _fill(template: str, values: dict) -> str:
    """Substitute only what is known, and leave the rest exactly as written.

    A placeholder with no value - `{reset_time}` on a dropped connection, which has no
    reset time - is removed rather than printed, and only the gap it leaves is closed: the
    spaces on either side of it become the ones on its left, or go altogether before
    punctuation, a line break, or the start or end of the text. Nothing anywhere else is
    touched - not a double space, not an indent, not the space French puts before a colon.
    """
    if not PLACEHOLDER.search(template):
        # Nothing to substitute. A Custom message with no placeholders is the common case
        # and it goes out exactly as it was typed - spacing, line breaks and all.
        return template
    out = ""
    position = 0
    for match in PLACEHOLDER.finditer(template):
        out += template[position:match.start()]
        position = match.end()
        value = values.get(match.group(1))
        value = "" if value is None else str(value)
        if value:
            out += value
            continue
        kept = out.rstrip(" \t")
        after = template[position:]
        rest = after.lstrip(" \t")
        left, right = out[len(kept):], after[:len(after) - len(rest)]
        if not (left or right):
            continue
        if not kept or kept.endswith("\n") or not rest or rest[0] in "\r\n,.;:!?":
            out = kept
        else:
            out = kept + (left or right)
        position += len(right)
    return out + template[position:]


def metadata_for(row=None, *, locale=l10n.DEFAULT, limits=None, reset_time=None) -> dict:
    """The safe values a message may refer to, from one interruption record.

    Everything here is either a number this product itself counted or a time it was
    told by Codex. Nothing is read out of the conversation.
    """
    values = {}
    category = None
    if row is not None:
        category = row["category"] if "category" in row.keys() else None
    # A usage limit spends no attempts - waiting for a reset is not a try that failed - so
    # it has neither an attempt number nor a maximum, and a message saying "2 of 3" there
    # would be counting something that is not happening.
    counted = category != failures.USAGE_LIMIT
    if row is not None and counted:
        # The number of *this* attempt, from the counter the attempt budget is checked
        # against, so {attempt} and {max_attempts} always count the same thing: a claim
        # given back, a budget restored or a chain continuing all move both together.
        # A first attempt is 1, never 0.
        spent = row["recovery_attempts"] if "recovery_attempts" in row.keys() else None
        if spent is not None:
            values["attempt"] = int(spent or 0) + 1
    if category:
        values["category"] = category
        values["reason"] = l10n.text(reasons.label_key(category), locale)
    if limits and counted:
        maximum = limits.get("max_recovery_attempts")
        if maximum:
            values["max_attempts"] = int(maximum)
    # Only a category that actually carries one, and only when the caller formatted it.
    if reset_time and (category is None or reasons.has_reset_time(category)):
        values["reset_time"] = reset_time
    return values


def build(category, *, locale=l10n.DEFAULT, style=DEFAULT_STYLE, custom=None,
          metadata=None) -> str:
    """The exact text that would be sent for this interruption.

    `custom` is the user's Custom settings, shaped as::

        {"mode": "global" | "per_reason",
         "text": "...",                       # the global message
         "per_reason": {"usage_limit": "..."}}

    The fallback when Custom is selected is deterministic and documented: the
    per-reason message if this category has a usable one, otherwise the global one,
    otherwise the localized Standard message for this category. An empty continuation
    is never produced - every path ends at a template that exists, and Custom text that
    fills in to nothing is not usable.
    """
    entry = reasons.get(category)
    values = _message_values(entry, locale, metadata)

    # A Custom message is only ever attached to a category that is continued. The engine
    # never asks for anything else, and a Preview refuses to; this makes it structural too,
    # so no caller can get the user's own words back for an unknown or terminal failure.
    if style == "custom" and entry.recoverable:
        _, text = _custom_choice(entry.category, custom, values)
        if text is not None:
            return text
        style = DEFAULT_STYLE

    if style == "minimal":
        return _fill(l10n.text("continuation.minimal", locale), values)
    if style == "detailed" and entry.detailed_key:
        return _fill(l10n.text(entry.detailed_key, locale), values)
    if entry.standard_key:
        return _fill(l10n.text(entry.standard_key, locale), values)
    # A category with no continuation text is never sent - the engine's gates stop it
    # long before here - so this is the shape of a bug, not a message anyone receives.
    # It still has to be text rather than an exception, because a Preview of a
    # non-recoverable category is a legitimate thing for a settings page to ask for.
    return _fill(l10n.text("continuation.minimal", locale), values)


def _message_values(entry, locale, metadata):
    values = dict(metadata or {})
    values.setdefault("category", entry.category)
    values.setdefault("reason", l10n.text(entry.label_key, locale))
    return values


def _custom_choice(category, custom, values):
    """Which Custom text is sent for this category, and what it says: `(source, text)`,
    or `(None, None)` when there is no usable Custom text.

    Usable means it still says something once filled in. "{reset_time}" on its own, for
    an interruption that has no reset time, fills in to nothing, and a turn holding only
    the marker would spend an attempt on a message Codex has nothing to act on.
    """
    if not isinstance(custom, dict):
        return None, None
    candidates = []
    per = custom.get("per_reason")
    if (custom.get("mode") or DEFAULT_CUSTOM_MODE) == "per_reason" and isinstance(per, dict):
        candidates.append(("per_reason", per.get(category)))
    candidates.append(("global", custom.get("text")))
    for source, candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            text = _fill(candidate, values)
            if text.strip():
                return source, text
    return None, None


# -------------------------------------------------------------- from settings
# Everything below turns stored settings into the arguments `build()` takes. The watcher
# calls `for_settings()` at the moment it sends, and the settings Preview calls the same
# function with the values being edited, so there is one resolution of "which language,
# which style, which Custom message" and not two that agree today.

def resolve_locale(values, environ=None) -> str:
    """The language a continuation is written in.

    An explicit Continuation language wins. `follow`, the default, is the Interface
    language - and the Interface language is itself `system`, following Windows, until
    someone chooses one. Changing the Interface language therefore carries continuations
    with it only for a person who has not chosen a Continuation language of their own.
    """
    values = values or {}
    chosen = values.get("continuation_language")
    if isinstance(chosen, str) and chosen in l10n.LOCALES:
        return chosen
    return l10n.resolve(values.get("interface_language"), environ)


def style_from(values) -> str:
    style = (values or {}).get("continuation_style")
    return style if style in STYLES else DEFAULT_STYLE


def custom_from(values) -> dict:
    values = values or {}
    mode = values.get("custom_message_mode")
    return {"mode": mode if mode in CUSTOM_MODES else DEFAULT_CUSTOM_MODE,
            "text": values.get("custom_message"),
            "per_reason": {category: values.get("custom_message_" + category)
                           for category in reasons.RECOVERABLE}}


def source_for(category, values, *, row=None, limits=None, environ=None):
    """Which text a continuation for this category actually uses.

    `per_reason`, `global` or `standard` when the Custom style is selected - the third
    meaning no usable Custom text exists and the Standard message is sent instead - and
    `None` for every other style. A settings page says this out loud beside the Preview,
    because "I chose Custom and something else was sent" is otherwise a mystery. It is
    decided for the same record `for_settings` is given, because whether Custom text is
    usable can depend on what its placeholders fill in to.
    """
    if style_from(values) != "custom":
        return None
    locale, metadata = _settings_metadata(values, row, limits, environ)
    filled = _message_values(reasons.get(category), locale, metadata)
    source, _ = _custom_choice(category, custom_from(values), filled)
    return source or "standard"


def format_reset_time(stamp):
    """A reset time as a person reads it on this machine, or None if there is none."""
    if not stamp:
        return None
    try:
        return time.strftime("%H:%M", time.localtime(float(stamp)))
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def for_settings(category, values, *, row=None, limits=None, environ=None) -> str:
    """The exact continuation for one interruption under these settings.

    `row` is the interruption record, or a stand-in with the same few fields for a
    Preview. Only the fields `metadata_for` names are read from it.
    """
    locale, metadata = _settings_metadata(values, row, limits, environ)
    return build(category, locale=locale, style=style_from(values),
                 custom=custom_from(values), metadata=metadata)


def _settings_metadata(values, row, limits, environ):
    locale = resolve_locale(values, environ)
    reset_at = None
    if row is not None and "reset_at" in row.keys():
        reset_at = row["reset_at"]
    return locale, metadata_for(row, locale=locale, limits=limits,
                                reset_time=format_reset_time(reset_at))
