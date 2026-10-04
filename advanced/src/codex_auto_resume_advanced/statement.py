# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""What a person reads before a capability is turned on: its statement, in their own language.

Every capability has one, in five fields - what it does, what the standard edition does
instead, the standards it departs from, what can go wrong and how to stop it - and in every one
of the product's languages (l10n.LOCALES, the held ones too). It has a revision (registry.CapabilityDef.revision): arming names
the revision the person read, and a statement that changes afterwards turns the capability off
until they have read the new one.

The words live in this package's own catalogs, `locales/<locale>.json`, one per language, and
are held to core's rules by core's own code (`l10n.read_catalog`, `l10n.fill`): UTF-8 JSON, text
only, no key twice, English as the layer every other language is laid over, `{name}`
placeholders filled and nothing else touched. A capability's fields are the keys
`statement.<id>.<field>`; the titles of the fields, the words for the three states and the
kill switch's name are this edition's own and ship now, with no capability yet. So do the words
of the warnings a statement shows above its fields (`warning.<word>`, vocabulary.ArmingWarning),
with their title and the note that none of them stops the person turning the capability on.

The first key of every catalog is `_edition`, which holds the line every shipped file of this
edition carries, for the audit of the standard archive to look for.
"""
from __future__ import annotations

from pathlib import Path

from codex_auto_resume import l10n

from .vocabulary import ArmingState, ArmingWarning, Field, ReportRefusal, ReportWrite, WebReason

DIRECTORY = Path(__file__).resolve().parent / "locales"
FIELDS = tuple(Field)
SENTINEL_KEY = "_edition"
ALL_OFF_KEY = "all_off"
# The edition badge, in this package's own words (decision C12). The status carries the code
# `advanced` and the count of what is armed; a surface turns them into these. `summary` takes
# `{n}`, the count. `not_loaded` is the word an installation whose package could not be loaded
# shows - it is the standard edition then, and says so.
BADGE_KEY = "edition.badge"
NOT_LOADED_KEY = "edition.not_loaded"
SUMMARY_KEY = "edition.summary"
EDITION_KEYS = (BADGE_KEY, NOT_LOADED_KEY, SUMMARY_KEY)
# The warnings' words: a title, the note under it, and one line for each warning.
WARNING_TITLE_KEY = "warning.title"
WARNING_NOTE_KEY = "warning.note"


def key(capability, field) -> str:
    """The catalog key of one field of one capability's statement."""
    return "statement.%s.%s" % (capability, Field(field))


def title_key(field) -> str:
    return "field.%s" % Field(field)


def state_key(state) -> str:
    return "state.%s" % ArmingState(state)


def warning_key(warning) -> str:
    return "warning.%s" % ArmingWarning(warning)


WARNING_KEYS = (WARNING_TITLE_KEY, WARNING_NOTE_KEY) + tuple(warning_key(word) for word in ArmingWarning)

# The Dashboard's Advanced features page (advanced/gui/AdvancedPage.cs): its own words, each
# capability's name (`name.<id>`) and the three states' words, handed over whole by the bridge's
# advanced-words (`words`). The window's catalog is core's, so a word of this page lives here and
# nowhere in core, and the standard edition carries none of them.
PAGE_PREFIX = "page."
NAME_PREFIX = "name."
PAGE_KEYS = tuple(PAGE_PREFIX + name for name in (
    "nav", "col_feature", "col_state", "choose", "unavailable",
    "policy.forbid", "policy.not_allowed", "policy.shadow_only",
    "about", "limits", "per_day", "per_conversation", "nominal", "hourly", "hourly_note",
    "turn_on", "watch", "turn_off", "all_off",
    "confirm.on", "confirm.watch", "confirm.changed", "confirm.version",
    "done.on", "done.watch", "done.off", "done.all_off", "done.hourly",
    "refused.changed", "refused.unavailable", "refused.other", "refused.hourly",
    "statement_unavailable", "refused.unread",
    "tripped", "tripped.measurement_failed", "tripped.failed_here", "tripped.incompatible",
    "tripped.local_check_failed", "tripped.submission_unknown", "tripped.hook_exception",
    "tripped.statement_changed", "tripped.engine_changed", "action_limits"))
# The compatibility report's card on that page (advanced/gui/AdvancedReport.cs): its own words, one for each
# write sending makes (vocabulary.ReportWrite), one for each reason it has to be sent on the web (WebReason) and
# one for each word it refuses with (ReportRefusal) - so a word the flow can answer with is one the page can say.
REPORT_PREFIX = PAGE_PREFIX + "report."
REPORT_KEYS = (tuple(REPORT_PREFIX + name for name in (
    "title", "intro", "login", "version", "write", "writing", "records", "verdict", "size", "sha256", "left_out",
    "file", "save", "saved", "watched", "check", "checking", "gh", "signed_in", "interrupted", "writes", "type",
    "send", "sending", "sent", "already", "after", "partial", "again", "lost", "last",
    "web.intro", "web.1", "web.2", "web.3", "web.4"))
    + tuple(REPORT_PREFIX + "w." + str(write) for write in ReportWrite)
    + tuple(REPORT_PREFIX + "web." + str(reason) for reason in WebReason)
    + tuple(REPORT_PREFIX + "refused." + str(code) for code in ReportRefusal))
PAGE_KEYS = PAGE_KEYS + REPORT_KEYS


def name_key(capability) -> str:
    """The catalog key of a capability's name, as the page lists it."""
    return NAME_PREFIX + capability


class Catalogs:
    """One directory of catalogs, read once each: this package's, or a test's."""

    def __init__(self, directory=DIRECTORY):
        self.directory = Path(directory)
        self._cache = {}

    def own(self, locale) -> dict:
        """One language's own entries, exactly as its file has them. Raises l10n.CatalogError."""
        return l10n.read_catalog(self.directory / ("%s.json" % locale))

    def catalog(self, locale) -> dict:
        """Every key, in `locale` where it has one and in English where it does not. A catalog
        that cannot be read is English, as core's are (l10n.catalog): the tests fail on it, the
        runtime keeps working."""
        locale = locale if locale in l10n.LOCALES else l10n.DEFAULT
        if locale not in self._cache:
            try:
                table = dict(self.own(l10n.DEFAULT))
            except l10n.CatalogError:
                table = {}
            if locale != l10n.DEFAULT:
                try:
                    table.update(self.own(locale))
                except l10n.CatalogError:
                    pass
            self._cache[locale] = table
        return dict(self._cache[locale])

    def text(self, name, locale=None, **fields) -> str | None:
        """One entry, filled in; None when no catalog has it."""
        value = self.catalog(l10n.current() if locale is None else locale).get(name)
        return None if value is None else l10n.fill(value, **fields)

    def badge(self, on, locale=None, *, loaded=True) -> str | None:
        """The edition badge for a surface to show beside the version: the word for a loaded
        installation followed by how many capabilities are armed, or the not-loaded word for
        one whose package could not be taken. The count comes from the status's `on`; the words
        are this package's own, in `locale` or the one the process resolved to."""
        if not loaded:
            return self.text(NOT_LOADED_KEY, locale)
        return self.text(SUMMARY_KEY, locale, n=on)

    def words(self, locale=None) -> dict:
        """The Advanced features page's words in `locale`, English underneath: every `page.*`
        and `name.*` entry, and the three states'. Unfilled - the window fills `{name}` and `{n}`
        itself, as it fills core's."""
        table = self.catalog(l10n.current() if locale is None else locale)
        return {name: value for name, value in table.items()
                if name.startswith((PAGE_PREFIX, NAME_PREFIX, "state."))}

    def missing(self, definition) -> list:
        """(locale, field) for every field of `definition`'s statement a language does not have
        in its own words. A statement is complete when this is empty."""
        found = []
        for locale in l10n.LOCALES:
            try:
                table = self.own(locale)
            except l10n.CatalogError:
                table = {}
            for field in FIELDS:
                value = table.get(key(definition.id, field))
                if not isinstance(value, str) or not value.strip():
                    found.append((locale, str(field)))
        return found

    def complete_in(self, definition, locale) -> bool:
        """Whether one language has every field of `definition`'s statement in its own words."""
        return all(found != locale for found, _field in self.missing(definition))

    def statement(self, definition, locale=None, *, warnings=()) -> dict:
        """What the Dashboard shows before the choice: the five fields, each with its title,
        the revision the choice will name, the ids of the standards it departs from, and above
        them `warnings` - the words of what holds now (arming.warnings_for), each with its line,
        which the choice confirms and never has to overcome."""
        locale = l10n.current() if locale is None else locale
        return {"capability": definition.id, "revision": definition.revision,
                "locale": locale if locale in l10n.LOCALES else l10n.DEFAULT,
                "departs_from": list(definition.departs_from),
                "warnings": {"title": self.text(WARNING_TITLE_KEY, locale),
                             "note": self.text(WARNING_NOTE_KEY, locale),
                             "items": [{"warning": str(ArmingWarning(word)),
                                        "text": self.text(warning_key(word), locale)}
                                       for word in warnings]},
                "fields": [{"field": str(field), "title": self.text(title_key(field), locale),
                            "text": self.text(key(definition.id, field), locale)}
                           for field in FIELDS]}


CATALOGS = Catalogs()
