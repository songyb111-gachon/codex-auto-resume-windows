"""The one authoritative definition of configurable policy.

Every front end - the command line, the Codex skill, the MCP server and the standalone
Windows settings window - reads and writes through this module. There is exactly one
schema, one set of defaults, one validator, one persistence path and one migration, so
a value set in any interface is the same value everywhere.

Two rules shape what may live here:

* Only *policy* is configurable. Safety properties are not settings. There is no field
  that can retry an unknown failure, resolve a thread by title, skip revalidation or
  resend an uncertain submission - those are invariants of the engine, not preferences.
* An invalid or unknown value is never fatal and never silently widens behaviour. It
  falls back to the default, which is always the conservative choice.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from . import continuation, failures, guards, l10n, ladder, needsyou, projects, quiet, reasons
from .domain.vocabulary import (Design, ImportanceTier, NewConversationPolicy, NotifyEvent,
                                ProjectPolicy, Theme)

CONFIG_VERSION = 2
MAX_SETTINGS_BYTES = 256 * 1024

# Recovery categories a user may turn off. The set is intentionally exactly the
# categories the classifier can already recover: enabling something here can never
# introduce a new class of automatic action.
CONFIGURABLE_CATEGORIES = (
    failures.USAGE_LIMIT,
    "network_transient",
    "timeout",
    "rate_limit_transient",
    "server_5xx",
    "stream_interrupted",
    # Not `auth_service_transient`, from v0.6.10. v0.6.3 gave it a switch here, believing it
    # the one recoverable category without one; but nothing in the classifier ever produced it,
    # so the switch - and its Custom message - changed nothing and never could. It is reserved
    # now (failures.RESERVED): no field, so describe() offers it on no surface, and a settings
    # file that still carries `recover_auth_service_transient` or its Custom message loads as
    # it always did, the two keys dropped on read like any key this build does not have.
)

# Notification events, each independently suppressible.
NOTIFICATION_EVENTS = tuple(NotifyEvent)

# Retry timing presets. Raw ladders are not exposed: a preset cannot produce a zero
# delay or an unbounded one, which a free-form number could. v0.6.11 adds Custom, five waits
# each chosen from a closed list for the same reason (ladder.py); the presets are unchanged.
RETRY_TIMING = ladder.PRESETS
RETRY_TIMINGS = ladder.TIMINGS
DEFAULT_TIMING = ladder.DEFAULT_TIMING

# Light or dark, for the settings window, the notification-area popup and the notification
# card - and for the panel in Codex too while its own choice is "same". "system" is not a
# colour: it is the standing instruction to follow the host - Windows' app mode for the
# window and the popup, Codex's own theme for the panel - so a later change there carries
# every surface with it. Windows High Contrast outranks every choice on every surface; that
# is an accessibility setting, not a theme.
THEME_SYSTEM = "system"
THEMES = tuple(Theme)
DEFAULT_THEME = THEME_SYSTEM

# The panel's own, from v0.6.6. Use system setting already let each surface follow its host,
# but a Light or Dark Theme bound the panel too: nobody could keep the window dark and let the
# panel follow Codex, or pin the panel whatever Codex does. "same" follows the Theme above,
# which is what every panel did before this existed - so it is the default, and an upgrade
# changes nothing anybody can see. "system" here is Codex's own theme.
PANEL_THEME_SAME = "same"
PANEL_THEMES = (PANEL_THEME_SAME, THEME_SYSTEM, "light", "dark")
DEFAULT_PANEL_THEME = PANEL_THEME_SAME

# v0.6.10: how every surface is drawn, in whichever theme is in effect - Soft (the design they all
# drew until then, so the default, and an upgrade changes nothing anybody can see), Classic (v0.6.2's
# flat cards) or Plain. brand.DESIGN says what each draws. It is not called `look`: the drawing code
# already uses that name for what a surface resolved. High Contrast outranks every design, and Reduce
# motion stops the motion in each; no design stops it on its own (see _migrate for the one that did).
DESIGNS = tuple(Design)
DEFAULT_DESIGN = "soft"


class SettingsError(ValueError):
    """A rejected write. Reads never raise; they fall back to defaults."""


def _boolean(value, default):
    return value if isinstance(value, bool) else default


def _bounded_int(value, default, low, high):
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return value if low <= value <= high else default


def _bounded_number(value, default, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return float(value) if low <= value <= high else default


def _choice(value, default, allowed):
    return value if isinstance(value, str) and value in allowed else default


def _optional_text(value, default):
    return value if isinstance(value, str) and value.strip() else default


# name -> (default, coercer). The coercer takes (raw, default) and always returns a
# valid value; that is what makes a malformed file harmless.
FIELDS = {
    "max_recovery_attempts": (4, lambda v, d: _bounded_int(v, d, 1, 20)),
    "max_no_progress": (3, lambda v, d: _bounded_int(v, d, 1, 10)),
    # How many continuations one task may receive in total, across every failure of it.
    # Never above 10, whatever the other limits say.
    "max_chain_continuations": (6, lambda v, d: _bounded_int(v, d, 1, 10)),
    "retry_timing": (DEFAULT_TIMING, lambda v, d: _choice(v, d, RETRY_TIMINGS)),
    "detection_lookback_hours": (6.0, lambda v, d: _bounded_number(v, d, 0.0, 24 * 7)),
    "notifications": (True, _boolean),
    # The watcher's notification-area icon. Showing it changes nothing about recovery.
    "show_tray": (True, _boolean),
    # v0.6.5: notifications drawn as the product's own card beside the notification area, with a
    # silent copy in Windows' notification center; off, every notification is Windows' own toast
    # as before. It chooses where a notification is drawn, never whether there is one: that is
    # `notifications` and `notify_<event>`. It changes nothing about recovery.
    "notification_card": (True, _boolean),
    # v0.6.9: start the watcher when Codex starts this plugin's MCP server, as well as - or
    # instead of - at Windows sign-in. Off by default. It decides when the watcher starts,
    # never what it does once it runs: the MCP server launches the same launcher sign-in uses,
    # only while no watcher runs and no installation holds its lock (control.start_for_codex).
    "start_with_codex": (False, _boolean),
    # First in Appearance, so it comes before Reduce motion wherever the schema is listed.
    # Changes nothing but colours; the notification-area icon stays as it is.
    "theme": (DEFAULT_THEME, lambda v, d: _choice(v, d, THEMES)),
    # The panel in Codex's own light or dark, or "same" as the Theme above (the default).
    "panel_theme": (DEFAULT_PANEL_THEME, lambda v, d: _choice(v, d, PANEL_THEMES)),
    # v0.6.10: the design every surface is drawn in, after the themes and before Reduce motion.
    # Added without raising CONFIG_VERSION, as panel_theme was: a file without it reads as Soft.
    "design": (DEFAULT_DESIGN, lambda v, d: _choice(v, d, DESIGNS)),
    # Stops every animation - the status light, the controls, the card - on every surface, the
    # panel in Codex included since v0.6.10, in every design, on top of Windows' own "Animation
    # effects" switch, which is honoured anyway. It can only stop motion, never start it.
    "reduce_motion": (False, _boolean),
    "codex_exe": (None, _optional_text),
}
# Every configurable category defaults ON: these are the failures already proven safe
# to recover, and a fresh install should recover them.
for _category in CONFIGURABLE_CATEGORIES:
    FIELDS["recover_" + _category] = (True, _boolean)
for _event in NOTIFICATION_EVENTS:
    # Every event on, as it always was - but the needs-you notice (v0.6.11), which v0.6.10 never raised.
    FIELDS["notify_" + _event] = (_event != NotifyEvent.NEEDS_YOU, _boolean)
# v0.6.11: which kinds a needs-you notice is raised for, each on once the notice is (needsyou.py);
# a turn that stops moving, told after a time chosen here - never, by default; and a sound of the
# notice's own, which only Windows' notification can carry (notify.py). Where a kind is switched off
# is here, in Settings - never on the notice itself (A28).
for _field in needsyou.KIND_FIELDS.values():
    FIELDS[_field] = (True, _boolean)
FIELDS[needsyou.STALL_FIELD] = (needsyou.DEFAULT_STALL, lambda v, d: _choice(v, d, needsyou.STALL_WAITS))
FIELDS[needsyou.SOUND_FIELD] = (False, _boolean)

# ------------------------------------------------------------------- language
# Two languages, deliberately independent. One is what the product says to you; the
# other is what it says to Codex on your behalf. A Korean interface with English
# continuations is a real preference - the person reads Korean and the model is being
# addressed in the language the rest of their conversation is in - and a product that
# tied the two together would be unable to express it.
FIELDS["interface_language"] = (l10n.SYSTEM,
                                lambda v, d: _choice(v, d, l10n.CHOICES))
# `follow` is not a locale: it is the standing instruction to use whatever the
# interface resolves to, so a later interface change carries the continuation with it
# unless the user has said otherwise.
FOLLOW_INTERFACE = "follow"
CONTINUATION_LANGUAGES = (FOLLOW_INTERFACE,) + l10n.LOCALES
FIELDS["continuation_language"] = (FOLLOW_INTERFACE,
                                   lambda v, d: _choice(v, d, CONTINUATION_LANGUAGES))

# -------------------------------------------------------- continuation message
FIELDS["continuation_style"] = (continuation.DEFAULT_STYLE,
                                lambda v, d: _choice(v, d, continuation.STYLES))
FIELDS["custom_message_mode"] = (continuation.DEFAULT_CUSTOM_MODE,
                                 lambda v, d: _choice(v, d, continuation.CUSTOM_MODES))


def _custom_message(value, default):
    """Stored exactly as typed, or refused. Never rewritten.

    `None` means "not configured", which is not the same as an empty message: the
    first falls back, the second would be a message that says nothing.
    """
    if value is None:
        return None
    try:
        return continuation.validate_custom(value)
    except continuation.CustomMessageError:
        return default


FIELDS["custom_message"] = (None, _custom_message)
# One field per recoverable category, generated from the registry rather than listed,
# so a category added to the classifier cannot end up without a place to put its text.
for _category in reasons.RECOVERABLE:
    FIELDS["custom_message_" + _category] = (None, _custom_message)

# ------------------------------------------------------------ quiet hours and tiers (v0.6.11)
# Each defaults to what v0.6.10 did (tests/test_defaults_golden.py, ADDED): no quiet hours - the
# start is `off`, and the end and the days change nothing until a start is chosen - and every
# conversation resumed automatically. They can only hold a recovery back: quiet hours make one
# that falls due wait until they end, and a tier that asks first holds an interruption for a
# person, or gives them the objection window's minutes to stop it first (quiet.py).
QUIET_STARTS, QUIET_TIMES, QUIET_DAYS = quiet.STARTS, quiet.TIMES, quiet.DAYS
FIELDS["quiet_hours_start"] = (quiet.DEFAULT_START, lambda v, d: _choice(v, d, QUIET_STARTS))
FIELDS["quiet_hours_end"] = (quiet.DEFAULT_END, lambda v, d: _choice(v, d, QUIET_TIMES))
FIELDS["quiet_hours_days"] = (quiet.DEFAULT_DAYS, lambda v, d: _choice(v, d, QUIET_DAYS))
# The tier a conversation without one of its own has, least asking first; and how long the
# objection window gives a person to stop a continuation before it is sent.
TIERS = tuple(ImportanceTier)
DEFAULT_TIER = ImportanceTier.AUTOMATIC.value
FIELDS["default_tier"] = (DEFAULT_TIER, lambda v, d: _choice(v, d, TIERS))
FIELDS["objection_minutes"] = (5, lambda v, d: _bounded_int(v, d, 1, 60))

# ------------------------------------------------ observe only, and who may resume (v0.6.11)
# Observe only: every check is made and when a continuation would have gone is recorded, and
# nothing is sent - the engine refuses it, and the state's own switch, which this one is written
# into (control/policy.py, runtime/app.py), makes the claim refuse it too. Off by default.
FIELDS["observe_only"] = (False, _boolean)
# What a conversation this product has never seen gets: the same as every other (the default), or
# Only notify me as a tier of its own, so nothing is sent for it until a person says so. And which
# projects may resume without a person (projects.py): every one, the default. The two lists a task
# row's Always and Never for this project write are keys, never paths, and no editor draws them
# (ROW_ACTION_FIELDS). Each of these can only hold a recovery back, and none does at the defaults.
NEW_CONVERSATION_POLICIES = tuple(NewConversationPolicy)
PROJECT_POLICIES = tuple(ProjectPolicy)
FIELDS["new_conversation_policy"] = (NewConversationPolicy.RESUME.value,
                                     lambda v, d: _choice(v, d, NEW_CONVERSATION_POLICIES))
FIELDS["project_policy"] = (projects.DEFAULT_POLICY, lambda v, d: _choice(v, d, PROJECT_POLICIES))
FIELDS[projects.ALWAYS] = ("", projects.coerce_keys)
FIELDS[projects.NEVER] = ("", projects.coerce_keys)

# ------------------------------------------- waits, a time ceiling and two guards (v0.6.11)
# The Custom ladder's five waits, read only while retry_timing is Custom; jitter, which only ever
# lengthens a wait; how long a task may keep failing with a temporary error; and the task-changed
# and context-cost guards (guards.py). Each defaults to what v0.6.10 did: the waits are inert under
# a preset, jitter and the ceiling are off, and neither guard reads or holds anything.
for _field, _default in zip(ladder.STEP_FIELDS, ladder.DEFAULT_STEPS):
    FIELDS[_field] = (_default, lambda v, d, _allowed=ladder.choices_for(_field): _choice(v, d, _allowed))
FIELDS["retry_jitter"] = (False, _boolean)
STEP_FIELDS = ladder.STEP_FIELDS
CHAIN_CEILINGS, TASK_GUARDS, CONTEXT_GUARDS = ladder.CEILINGS, guards.TASK_GUARDS, guards.CONTEXT_GUARDS
FIELDS["chain_time_ceiling"] = (ladder.DEFAULT_CEILING, lambda v, d: _choice(v, d, CHAIN_CEILINGS))
FIELDS["task_changed_guard"] = (guards.DEFAULT_TASK_GUARD, lambda v, d: _choice(v, d, TASK_GUARDS))
FIELDS["context_guard"] = (guards.DEFAULT_CONTEXT_GUARD, lambda v, d: _choice(v, d, CONTEXT_GUARDS))


def is_custom_text(name) -> bool:
    """Whether a settings field holds Custom continuation text: the user's own words, which
    the watcher sends into their conversations on their behalf.

    The one test of it. The MCP server never offers these fields to a model, the Preview
    validates them as text, the diagnostics bundle never quotes them, and the settings
    surfaces draw them as free text. `custom_message_mode` is not one of them: it chooses
    which message is used.
    """
    return name.startswith("custom_message") and name != "custom_message_mode"

# A refusal a person can act on. `validate_update` reports "invalid value for X" for
# most fields, which is enough when the field is a number with a published range and
# useless when it is free text: "invalid value for custom_message" does not say that
# the problem is a placeholder that would have leaked the conversation. The one choice
# this version no longer has - v0.6.10's design "still" (FOLDED_DESIGN) - is answered with
# the designs it has (`_refuse`); every other refusal says what it said in v0.6.10.
EXPLAIN = {name: lambda value: continuation.validate_custom(value)
           for name in FIELDS if is_custom_text(name)}

DEFAULTS = {name: default for name, (default, _coerce) in FIELDS.items()}

# Ranges published to the user interfaces so a slider or spin box cannot offer a value
# the validator would reject.
# v0.6.11: a limit above its "high" gets a warning beside it on every surface that edits it - a
# task that keeps failing may then be continued many times, each one using the person's Codex usage.
HIGH_LIMITS = {"max_recovery_attempts": 8, "max_no_progress": 5, "max_chain_continuations": 8}

RANGES = {
    "max_recovery_attempts": {"min": 1, "max": 20, "high": HIGH_LIMITS["max_recovery_attempts"]},
    "max_no_progress": {"min": 1, "max": 10, "high": HIGH_LIMITS["max_no_progress"]},
    "max_chain_continuations": {"min": 1, "max": 10, "high": HIGH_LIMITS["max_chain_continuations"]},
    "detection_lookback_hours": {"min": 0.0, "max": float(24 * 7)},
    # Each preset's waits as a person is shown them (ladder.preview), for the surfaces to look up.
    "retry_timing": {"choices": list(RETRY_TIMINGS), "waits": ladder.previews()},
    "theme": {"choices": list(THEMES)},
    "panel_theme": {"choices": list(PANEL_THEMES)},
    "design": {"choices": list(DESIGNS)},
    "interface_language": {"choices": list(l10n.CHOICES)},
    "continuation_language": {"choices": list(CONTINUATION_LANGUAGES)},
    "continuation_style": {"choices": list(continuation.STYLES)},
    "custom_message_mode": {"choices": list(continuation.CUSTOM_MODES)},
    "quiet_hours_start": {"choices": list(QUIET_STARTS)},
    "quiet_hours_end": {"choices": list(QUIET_TIMES)},
    "quiet_hours_days": {"choices": list(QUIET_DAYS)},
    "default_tier": {"choices": list(TIERS)},
    "objection_minutes": {"min": 1, "max": 60},
    "new_conversation_policy": {"choices": list(NEW_CONVERSATION_POLICIES)},
    "project_policy": {"choices": list(PROJECT_POLICIES)},
    **{field: {"choices": list(ladder.choices_for(field)),
               "seconds": {wait: ladder.WAIT_SECONDS[wait] for wait in ladder.choices_for(field)}}
       for field in ladder.STEP_FIELDS},
    "chain_time_ceiling": {"choices": list(CHAIN_CEILINGS)},
    "task_changed_guard": {"choices": list(TASK_GUARDS)},
    "context_guard": {"choices": list(CONTEXT_GUARDS)},
    needsyou.STALL_FIELD: {"choices": list(needsyou.STALL_WAITS)},
}

# The fields that shape a needs-you notice (v0.6.11), in the order they follow its switch.
NEEDS_YOU_FIELDS = tuple(needsyou.KIND_FIELDS.values()) + (needsyou.STALL_FIELD, needsyou.SOUND_FIELD)


# What each published type accepts on a write. A number takes an integer - JSON has one
# numeric type, and a person who types 6 into a box that measures hours has given a
# number - and nothing takes a boolean but a boolean, because `bool` is an `int` in
# Python and is not one in JSON, so a tick box is not a count.
_ACCEPTED_TYPES = {"boolean": (bool,), "integer": (int,), "number": (int, float),
                   "string": (str,)}


def field_type(name: str) -> str:
    """The JSON type this field's values have: "boolean", "integer", "number" or "string".

    One derivation, read by `describe()` - and therefore by the MCP schema and by every
    window's editor - and by `validate_update`. What the schema will not offer, the
    validator will not take.
    """
    default = FIELDS[name][0]
    return ("boolean" if isinstance(default, bool)
            else "integer" if isinstance(default, int)
            else "number" if isinstance(default, float)
            else "string")


def _right_type(name: str, value) -> bool:
    """Whether `value` is of this field's type, asked before anything looks at the value."""
    if value is None:
        # `null` empties a field that can have no value - the Codex path, and each custom
        # message. Every other field has one, and null is not it.
        return FIELDS[name][0] is None
    if isinstance(value, bool):
        return field_type(name) == "boolean"
    return isinstance(value, _ACCEPTED_TYPES[field_type(name)])


def _refuse(name: str, value):
    """Raise the refusal for one field, in that field's own words where it has any."""
    explain = EXPLAIN.get(name)
    if explain is not None and value is not None:
        # The field's own validator says what is wrong with it. A range is
        # self-explanatory; free text is not.
        try:
            explain(value)
        except ValueError as exc:
            raise SettingsError(str(exc)) from None
    if name == "design" and value == FOLDED_DESIGN:
        raise SettingsError("invalid value for design: expected one of %s" % ", ".join(DESIGNS))
    raise SettingsError("invalid value for %s" % name)


def defaults() -> dict:
    return dict(DEFAULTS)


def coerce(raw) -> dict:
    """Validate a candidate mapping into a complete settings dict.

    Unknown keys are dropped and invalid values fall back to their default, so neither
    a hand-edited file nor a newer version's file can break the running watcher.
    """
    values = dict(DEFAULTS)
    if isinstance(raw, dict):
        for name, (default, coercer) in FIELDS.items():
            if name in raw:
                values[name] = coercer(raw[name], default)
    return values


def validate_update(changes) -> dict:
    """Strictly validate an explicit user edit. Unlike `coerce`, this rejects.

    A write is a deliberate act, so a bad value is reported rather than quietly
    replaced - otherwise a user would set 999 and be told it worked.
    """
    if not isinstance(changes, dict):
        raise SettingsError("settings must be an object")
    unknown = sorted(set(changes) - set(FIELDS))
    if unknown:
        raise SettingsError("unknown setting: %s" % ", ".join(unknown))
    clean = {}
    for name, value in changes.items():
        default, coercer = FIELDS[name]
        # The type first, and only then the value. A coercer answers a value it does not
        # like with the field's default, and this used to decide by comparing that answer
        # with the value supplied - so a wrong type that happened to equal the default was
        # read as "unchanged" and written. Which wrong types those were depended on the
        # default, so `{"reduce_motion": 0}` was taken and `{"notifications": 0}` refused,
        # and `{"max_no_progress": 3.0}` was taken and 5.0 refused. Asking the type first
        # closes it for every field at once and leaves the range check exactly as it was.
        if not _right_type(name, value):
            _refuse(name, value)
        coerced = coercer(value, default)
        if coerced != value and not (name == "codex_exe" and value is None):
            _refuse(name, value)
        clean[name] = coerced
    return clean


def timing_ladder(values) -> tuple:
    """The five waits in effect: a preset's, or the Custom ones (ladder.py)."""
    return ladder.ladder(values)


def high_limits(values) -> list:
    """The limits set above their "high", in the order they are shown: each is warned of."""
    values = values if isinstance(values, dict) else {}
    return [name for name, high in HIGH_LIMITS.items()
            if isinstance(values.get(name), int) and not isinstance(values.get(name), bool)
            and values[name] > high]


def theme_preference(values) -> str:
    """The stored theme choice - "system", "light" or "dark" - never anything else.

    Only the choice. What "system" resolves to depends on the surface (Windows' app mode,
    or the host's colour scheme in Codex), and High Contrast outranks every choice, so
    resolving it belongs to the surface that draws.
    """
    raw = values.get("theme") if isinstance(values, dict) else None
    return _choice(raw, DEFAULT_THEME, THEMES)


def design_preference(values) -> str:
    """The stored design - "soft", "classic" or "plain" - never anything else.

    Read as the settings layer reads it, so a surface drawing from a settings dict it was handed
    draws the design the watcher would: anything unreadable is Soft. A stored "still" is Soft here
    as well, and the Reduce motion that keeps its picture is `load`'s to add (_migrate).
    """
    raw = values.get("design") if isinstance(values, dict) else None
    return _choice(raw, DEFAULT_DESIGN, DESIGNS)


def tier_of(values, own=None) -> str:
    """The tier a conversation has: its own (`threads.tier`), or else the default in `values`."""
    if own in TIERS:
        return own
    raw = values.get("default_tier") if isinstance(values, dict) else None
    return _choice(raw, DEFAULT_TIER, TIERS)


def category_enabled(values, category: str) -> bool:
    """Whether automatic recovery is allowed for one failure category.

    A category this build does not expose is treated as enabled: the classifier already
    decided it is recoverable, and the absence of a toggle is not a instruction to stop.
    """
    key = "recover_" + str(category)
    if key not in FIELDS:
        return True
    return bool((values or {}).get(key, DEFAULTS[key]))


# v0.6.11: a notice about to be acted on - the objection window's "Continuing at 14:07" - is told
# under the switch of the notice it comes before, Recovery starting.
GOVERNED_BY = {"objection": NotifyEvent.STARTING.value}


def notification_enabled(values, event: str) -> bool:
    values = values or {}
    if not values.get("notifications", DEFAULTS["notifications"]):
        return False
    key = "notify_" + GOVERNED_BY.get(str(event), str(event))
    return bool(values.get(key, DEFAULTS.get(key, True)))


# --------------------------------------------------------------------- persistence
# v0.6.10's fourth design. "still" was Soft with nothing moving, which on every surface is exactly
# what Soft draws under Reduce motion; two ways to one picture only confused, so v0.6.11 folded it
# into Reduce motion, the one way to stop motion. A file that stored it reads as Soft with Reduce
# motion on - whatever Reduce motion said beside it - so the person keeps the picture they chose,
# and the next save writes those two, which v0.6.10 also reads as that picture. CONFIG_VERSION does
# not move: nothing else in the file changes meaning, and a file v0.6.10 wrote needs no marker to
# say it may hold "still".
FOLDED_DESIGN = "still"


def _fold_design(raw: dict) -> dict:
    """A stored Still as Soft with Reduce motion on; any other file as it is."""
    if raw.get("design") != FOLDED_DESIGN:
        return raw
    return dict(raw, design=DEFAULT_DESIGN, reduce_motion=True)


def _migrate(raw) -> dict:
    """Bring an older settings file forward without losing what the user chose."""
    if not isinstance(raw, dict):
        return {}
    version = raw.get("config_version")
    if not isinstance(version, int) or version < 1:
        # v0.4.x wrote a flat file with no version marker. Its field names that still
        # exist keep their values; everything else takes the new default. A hand-written
        # file with no marker may hold a Still too, and keeps its picture like any other.
        return _fold_design({name: raw[name] for name in FIELDS if name in raw})
    return _fold_design(raw)


def load(path: Path) -> dict:
    """Read settings, falling back to defaults for anything missing or malformed."""
    try:
        target = Path(path)
        if (not target.is_file() or target.is_symlink()
                or target.stat().st_size > MAX_SETTINGS_BYTES):
            return defaults()
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return defaults()
    return coerce(_migrate(raw))


def save(path: Path, values: dict) -> dict:
    """Persist a complete settings dict atomically. Returns what was written."""
    target = Path(path)
    complete = coerce(values)
    payload = dict(complete, config_version=CONFIG_VERSION)
    target.parent.mkdir(parents=True, exist_ok=True)
    # mkstemp + replace: a reader never observes a half-written file, and a pre-planted
    # symlink at a predictable temp name cannot be followed.
    descriptor, temporary = tempfile.mkstemp(dir=str(target.parent), prefix="settings.", suffix=".json.tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except OSError as exc:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise SettingsError("cannot save settings") from exc
    return complete


def update(path: Path, changes: dict) -> dict:
    """Validate and merge an edit into the stored settings."""
    clean = validate_update(changes)
    return save(path, dict(load(path), **clean))


# Fields that exist - stored, validated, defaulted - but that no surface offers yet, because
# nothing reads them yet. `describe()` leaves them out, and the Dashboard, the panel and the MCP
# schema are all drawn from it, so none of them shows a switch that would change nothing.
# `notification_card` waited here until the watcher handed notices to the notifier (app.py) and the
# icon's thread hosted the card (tray.py); tests/test_notice_card.py (SettingTests) holds the name here
# exactly while that wiring is missing.
#
# `start_with_codex` is here for the opposite reason: it is wired, and what it would do cannot be done.
# v0.6.9-alpha measured Codex 26.915 on a real machine - Codex runs each plugin's MCP server in a job
# with KILL_ON_JOB_CLOSE that forbids breakaway, and cancels the server seconds after it starts, so
# every watcher started from there was killed within about six seconds. A switch that says the watcher
# starts with Codex, and never leaves one running, would be a false thing to show, so no surface offers
# it; `Control.start_for_codex` refuses for the same reason and writes what the job said to
# logs/codex-start.log, which is how the next Codex gets measured. The advanced edition builds it
# properly in v0.6.11, where starting a process outside the host's job is a thing a person may turn on.
NOT_YET_OFFERED = frozenset({"start_with_codex"})

# Fields a task's row writes and no settings editor offers (v0.6.11): the projects set to Always and to
# Never, each a list of keys a person has no way to read (projects.py). `describe()` leaves them out, so
# the Dashboard, the panel and the MCP schema draw nothing for them, and update_settings refuses them
# as it refuses every field its schema does not offer; Restore defaults empties them with the rest.
ROW_ACTION_FIELDS = frozenset({projects.ALWAYS, projects.NEVER})


def describe() -> list:
    """Machine-readable schema for the settings interfaces.

    The user interfaces render themselves from this, so a field added here appears in
    every front end at once instead of being wired up three times. A field in
    NOT_YET_OFFERED is not described: it has no front end until something reads it.
    """
    described = []
    for name, (default, _coerce) in FIELDS.items():
        if name in NOT_YET_OFFERED or name in ROW_ACTION_FIELDS:
            continue
        entry = {"name": name, "default": default, "type": field_type(name)}
        if name in RANGES:
            entry.update(RANGES[name])
        if name.startswith("recover_"):
            entry["group"] = "recovery"
            entry["category"] = name[len("recover_"):]
        elif (name.startswith("notify_") or name == "notifications"
              or name in NEEDS_YOU_FIELDS):
            # v0.6.11: the needs-you notice's kinds, its stall and its sound under its own switch.
            entry["group"] = "notifications"
            entry["master"] = name == "notifications"
        elif name in ("theme", "panel_theme", "design", "reduce_motion"):
            # How the surfaces look. Both themes are offered in the window and in the panel. The
            # design and Reduce motion are offered only in the window: both decide what moves, and
            # what moves is not Codex's to change (mcp.tools.PANEL_APPEARANCE). The panel draws in
            # both since v0.6.10, as well as following the host's own reduced-motion preference.
            entry["group"] = "appearance"
        elif name in ("show_tray", "notification_card", "start_with_codex"):
            # A desktop preference, beside "run at sign-in" - not a notification, and
            # not something the notifications switch governs. The card only chooses how a
            # notification looks on this desktop, so it lives here too, and like the icon it is
            # outside what the Codex panel and MCP may change (mcpserver.USER_GROUPS).
            entry["group"] = "windows"
        elif name in ("max_recovery_attempts", "max_no_progress", "max_chain_continuations",
                      "retry_timing", "quiet_hours_start", "quiet_hours_end", "quiet_hours_days",
                      "default_tier", "objection_minutes", "new_conversation_policy",
                      "project_policy", *ladder.STEP_FIELDS, "retry_jitter", "chain_time_ceiling",
                      "task_changed_guard", "context_guard"):
            # v0.6.11: quiet hours and the tier a conversation has by default join the limits -
            # how hard, and when, recovery tries - in the window and in the panel alike; and beside
            # the tier, what a new conversation gets and which projects resume without a person;
            # and after them the Custom waits, jitter, the time ceiling and the two guards.
            entry["group"] = "limits"
        elif name == "observe_only":
            # v0.6.11: a switch of automatic recovery itself, under the kinds it recovers.
            entry["group"] = "recovery"
        elif name == "interface_language":
            entry["group"] = "general"
        elif name in ("continuation_language", "continuation_style", "custom_message_mode"):
            entry["group"] = "continuation"
        elif is_custom_text(name):
            # Free text. The surfaces need to know that before they draw a one-line box
            # for it, and they need the limit before a person types past it.
            entry["group"] = "continuation"
            entry["multiline"] = True
            entry["max_length"] = continuation.MAX_CUSTOM_LENGTH
            if name != "custom_message":
                entry["category"] = name[len("custom_message_"):]
        else:
            entry["group"] = "advanced"
        described.append(entry)
    return described
