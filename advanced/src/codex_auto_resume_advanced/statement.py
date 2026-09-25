# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""What a person reads before a capability is turned on: its statement, in their own language.

Every capability has one, in five fields - what it does, what the standard edition does
instead, the standards it departs from, what can go wrong and how to stop it - and in all nine
of the product's languages. It has a revision (registry.CapabilityDef.revision): arming names
the revision the person read, and a statement that changes afterwards turns the capability off
until they have read the new one.

The words live in this package's own catalogs, `locales/<locale>.json`, one per language, and
are held to core's rules by core's own code (`l10n.read_catalog`, `l10n.fill`): UTF-8 JSON, text
only, no key twice, English as the layer every other language is laid over, `{name}`
placeholders filled and nothing else touched. A capability's fields are the keys
`statement.<id>.<field>`; the titles of the fields, the words for the three states and the
kill switch's name are this edition's own and ship now, with no capability yet.

The first key of every catalog is `_edition`, which holds the line every shipped file of this
edition carries, for the audit of the standard archive to look for.
"""
from __future__ import annotations

from pathlib import Path

from codex_auto_resume import l10n

from .vocabulary import ArmingState, Field

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


def key(capability, field) -> str:
    """The catalog key of one field of one capability's statement."""
    return "statement.%s.%s" % (capability, Field(field))


def title_key(field) -> str:
    return "field.%s" % Field(field)


def state_key(state) -> str:
    return "state.%s" % ArmingState(state)


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

    def statement(self, definition, locale=None) -> dict:
        """What the Dashboard shows before the choice: the five fields, each with its title,
        the revision the choice will name, and the ids of the standards it departs from."""
        locale = l10n.current() if locale is None else locale
        return {"capability": definition.id, "revision": definition.revision,
                "locale": locale if locale in l10n.LOCALES else l10n.DEFAULT,
                "departs_from": list(definition.departs_from),
                "fields": [{"field": str(field), "title": self.text(title_key(field), locale),
                            "text": self.text(key(definition.id, field), locale)}
                           for field in FIELDS]}


CATALOGS = Catalogs()
