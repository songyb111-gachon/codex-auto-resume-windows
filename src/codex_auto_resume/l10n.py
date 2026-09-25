"""One catalog per language, one way to look a string up, one language to fall back to.

Until v0.6.3 this product spoke two languages, and it decided which one by reading the
Windows preferred UI languages every time anybody asked. That worked because there were
two: a tag either started with `ko` or it did not. Nine languages is a different problem,
and three parts of it are worth naming.

**Which language.** A user may now choose, and a choice is not the same as a detection.
`resolve()` takes what the user stored - `"system"` or a locale id - and turns it into
exactly one locale. `"system"` still reads the same source the desktop app itself uses,
so an unconfigured install speaks whatever Codex speaks. An explicit choice is obeyed
even when Windows disagrees, because a person who picked Japanese on a Korean machine
meant it. Nothing infers a language from an IP address, a time zone, a user name, a
country or a keyboard layout.

**Which tag means which catalog.** Windows says `ko-KR`, `zh-Hans-CN`, `pt-PT`,
`es-419`. Nine catalogs cannot each be a list of every tag that should reach them, so
`normalize()` is the single place that maps a BCP-47-ish tag to a shipped locale, script
subtags included. It returns `None` for a language this product does not have, which is
how "not supported" stays distinguishable from "supported, and the answer is English".

**What happens to a key a translator has not reached yet.** English is the source and
every other catalog is a layer over it: `catalog()` hands back English updated with the
locale's own entries. A missing key is therefore impossible at runtime - the worst case
is an English word in a Korean sentence, which is a translation bug somebody can see and
fix, rather than a blank label or a `KeyError` in front of a user. `tests/test_l10n.py`
fails on a missing key anyway, so the fallback is a safety net and not a licence.

The catalogs are JSON next to this file, one per locale, UTF-8. JSON because a catalog
is data that people and scripts both edit: a translator can be handed one file, a
completeness check is a set difference, and a duplicated key is detectable rather than
silently last-one-wins - which is exactly what `json.load` does by default, so the
loader here refuses duplicates instead.

Nothing in this module reaches the network. There is no translation service, no runtime
download, and no locale data beyond the files in this directory.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re

from .domain.vocabulary import Locale

# The environment override the whole product honours, kept at its original name
# because it is documented and people have it in scripts.
ENV_LANG = "CODEX_AUTO_RESUME_LANG"

# The languages the product's own interface is shipped in. English is first because it
# is the source catalog, not because it is preferred.
LOCALES = tuple(Locale)
DEFAULT = "en"
# What a settings field may hold. `system` is stored as a choice in its own right so
# that "follow Windows" survives a Windows language change, which storing the resolved
# locale would quietly throw away.
SYSTEM = "system"
CHOICES = (SYSTEM,) + LOCALES

DIRECTORY = Path(__file__).resolve().parent / "locales"

# A placeholder is `{name}`. Anything else in a string is literal text, including a
# brace that stands alone, so the pattern is deliberately narrow.
PLACEHOLDER = re.compile(r"\{([a-z_][a-z0-9_]*)\}")

# Language subtags that are not themselves shipped locales but have an obvious home.
# Portuguese is the one judgement call: the product ships Brazilian Portuguese, and a
# reader in Portugal is better served by it than by English, so `pt` and `pt-PT` land
# there rather than falling through.
_LANGUAGE_HOME = {
    "en": "en", "ko": "ko", "ja": "ja",
    "es": "es", "de": "de", "fr": "fr", "pt": "pt-BR",
}

# Chinese is chosen by script, not by country, and Windows may say either. Simplified
# and traditional are different catalogs, so a tag that names only `zh` has to be
# resolved by the region or script it carries.
_CHINESE_TRADITIONAL_REGIONS = frozenset({"tw", "hk", "mo"})
_CHINESE_TRADITIONAL_SCRIPTS = frozenset({"hant"})
_CHINESE_SIMPLIFIED_SCRIPTS = frozenset({"hans"})


def _windows_preferred() -> list[str]:
    """The Windows user's preferred UI languages, most preferred first.

    This is the exact API behind Electron's ``app.getPreferredSystemLanguages()``,
    which is how the ChatGPT desktop app chooses its own display language.
    """
    if os.name != "nt":
        return []
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        MUI_LANGUAGE_NAME = 0x8
        count = wintypes.ULONG(0)
        size = wintypes.ULONG(0)
        if not kernel32.GetUserPreferredUILanguages(MUI_LANGUAGE_NAME, ctypes.byref(count), None, ctypes.byref(size)):
            return []
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.GetUserPreferredUILanguages(MUI_LANGUAGE_NAME, ctypes.byref(count), buffer, ctypes.byref(size)):
            return []
        return [tag for tag in "".join(buffer[:size.value]).split("\x00") if tag]
    except Exception:
        return []    # An unavailable probe means English, never a guess.


def preferred_languages(environ=None) -> list[str]:
    environ = os.environ if environ is None else environ
    override = (environ.get(ENV_LANG) or "").strip()
    if override:
        return [override]
    tags = _windows_preferred()
    if tags:
        return tags
    for name in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = (environ.get(name) or "").strip()
        if value and value not in ("C", "POSIX"):
            return [value.split(".")[0].replace("_", "-")]
    return []


class CatalogError(ValueError):
    """A catalog file is not usable. Raised at load time, never at lookup time."""


def normalize(tag) -> str | None:
    """The shipped locale a language tag belongs to, or `None` if this product has none.

    Accepts what real systems produce: `ko`, `ko-KR`, `ko_KR`, `zh-Hans-CN`, `es-419`,
    `pt-PT`, and the locale ids this product itself stores.
    """
    if not isinstance(tag, str):
        return None
    parts = [part for part in tag.strip().replace("_", "-").split("-") if part]
    if not parts:
        return None
    language = parts[0].lower()
    rest = [part.lower() for part in parts[1:]]
    if language == "zh":
        for part in rest:
            if part in _CHINESE_TRADITIONAL_SCRIPTS or part in _CHINESE_TRADITIONAL_REGIONS:
                return "zh-TW"
            if part in _CHINESE_SIMPLIFIED_SCRIPTS:
                return "zh-CN"
        # Bare `zh`, or a region this table does not call traditional: simplified is
        # what the large majority of `zh` speakers read.
        return "zh-CN"
    return _LANGUAGE_HOME.get(language)


def from_system(environ=None) -> str:
    """The locale Windows asks for, or English.

    Only the *most preferred* language counts. A machine that lists German after English
    is not asking for German, and answering it in German because the list mentions it is
    how a product ends up speaking a language nobody chose.
    """
    for tag in preferred_languages(environ):
        found = normalize(tag)
        if found is not None:
            return found
        # A first preference this product does not have is an answer, not an invitation
        # to search further down the list for one it does.
        break
    return DEFAULT


def resolve(preference, environ=None) -> str:
    """The one locale to render in, from what the user stored.

    `system`, an empty value or anything unrecognised means "follow Windows". An
    explicit locale wins over Windows; an explicit locale this build does not ship
    falls back to English rather than to Windows, because the stored value was a
    decision and Windows was not.
    """
    if isinstance(preference, str):
        chosen = preference.strip()
        if chosen and chosen != SYSTEM:
            if chosen in LOCALES:
                return chosen
            found = normalize(chosen)
            return found if found is not None else DEFAULT
    return from_system(environ)


# ---------------------------------------------------------------- preference
# The Interface language the user stored, for everything this process renders.
#
# Each process that shows a person anything - the watcher with its icon and its
# notifications, the bridge the window talks to, the MCP server that draws the panel -
# belongs to exactly one installation and reads exactly one settings file, so the choice
# is held once per process rather than threaded through every call that formats a
# sentence. The watcher sets it when it loads settings and again whenever they change;
# the bridge and the MCP server set it before they hand over a catalog. Anything that
# asks without a choice having been made gets `system`, which is what it always got.
_preference = SYSTEM


def set_preference(value) -> str:
    """Adopt a stored Interface language. Returns the locale it now resolves to.

    An unrecognised value is `system`, not an error: a settings file edited by hand, or
    written by a newer version, must not leave a process unable to say anything.
    """
    global _preference
    _preference = value if isinstance(value, str) and value in CHOICES else SYSTEM
    return current()


def preference() -> str:
    return _preference


def current(environ=None) -> str:
    """The locale this process renders in right now."""
    return resolve(_preference, environ)


# Each language named in itself. These are not translated and do not live in the
# catalogs: a person looking for their own language in a list scans for the name they
# know, and "Japanese" written in Korean is a name a Japanese reader does not know.
ENDONYMS = {
    "en": "English",
    "ko": "한국어",
    "ja": "日本語",
    "zh-CN": "简体中文",
    "zh-TW": "繁體中文",
    "es": "Español",
    "de": "Deutsch",
    "fr": "Français",
    "pt-BR": "Português (Brasil)",
}


def _no_duplicates(pairs):
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise CatalogError("duplicate key %r" % key)
        seen[key] = value
    return seen


def _read(locale: str) -> dict:
    return read_catalog(DIRECTORY / ("%s.json" % locale))


def read_catalog(path) -> dict:
    """One catalog file, held to every rule a catalog is: UTF-8 JSON, one object, every value
    text, no key twice. `CatalogError` says which rule it broke.

    The catalogs beside this module are read through here, and so is any other set of them -
    the advanced edition keeps its own words in a directory of its own, and they are held to
    the same rules by the same code rather than by a copy of it."""
    path = Path(path)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CatalogError("%s is unreadable (%s)" % (path.name, exc)) from None
    try:
        loaded = json.loads(raw, object_pairs_hook=_no_duplicates)
    except CatalogError:
        raise
    except ValueError as exc:
        raise CatalogError("%s is not JSON (%s)" % (path.name, exc)) from None
    if not isinstance(loaded, dict):
        raise CatalogError("%s does not hold an object of key to string" % path.name)
    for key, value in loaded.items():
        if not isinstance(value, str):
            raise CatalogError("%s: %r is not text" % (path.name, key))
    return loaded


_CACHE: dict = {}


def catalog(locale: str) -> dict:
    """Every key, in this locale where it exists and in English where it does not.

    Cached: a catalog is read once per process. The window and the panel are each
    handed a whole catalog rather than calling back per key, so this is a handful of
    reads over a run, not one per label.
    """
    locale = locale if locale in LOCALES else DEFAULT
    if locale not in _CACHE:
        source = dict(_read(DEFAULT))
        if locale != DEFAULT:
            try:
                source.update(_read(locale))
            except CatalogError:
                # A catalog that is missing, malformed or truncated is a packaging or
                # translation fault, and `tests/test_l10n.py` fails on every one of
                # them. It is not a reason to take the window down in front of somebody
                # who only wanted to read their pending list, so the English underneath
                # is what they get. Strictness belongs in the tests; the runtime's job
                # is to keep working.
                pass
        _CACHE[locale] = source
    return dict(_CACHE[locale])


def text(key: str, locale: str = DEFAULT, **fields) -> str:
    """One string, formatted.

    Formatting is deliberately not `str.format`: a translated string containing a stray
    brace would raise in front of a user, and a placeholder the caller did not supply
    would too. Every `{name}` the caller provides is substituted and anything else is
    left exactly as the translator wrote it.
    """
    value = catalog(locale).get(key)
    if value is None:
        raise KeyError(key)
    return fill(value, **fields)


def fill(value: str, **fields) -> str:
    """`value` with every `{name}` the caller supplies filled in, and nothing else touched: the
    one way a sentence is formatted, whichever catalog it came from."""
    for name, supplied in fields.items():
        value = value.replace("{%s}" % name, str(supplied))
    return value


# The plugin's own sentences - setup output and the notifications - live in the same catalogs
# under a `msg.` prefix, so a name like `cancelled` cannot collide with a settings label. They
# were reached through a `messages` module that only re-exported this one; these two are what
# it added.
def messages(locale: str) -> dict:
    """The plugin's own sentences in one locale, keyed without their `msg.` prefix."""
    return {key[len("msg."):]: value for key, value in catalog(locale).items() if key.startswith("msg.")}


def message(key: str, environ=None) -> str:
    """One of the plugin's own sentences, in the language this process speaks."""
    return text("msg." + key, current(environ))


def placeholders(value: str) -> frozenset:
    """The `{name}` placeholders in one string."""
    return frozenset(PLACEHOLDER.findall(value))


def available() -> tuple:
    """The locales that actually have a catalog file shipped beside this module."""
    return tuple(locale for locale in LOCALES if (DIRECTORY / ("%s.json" % locale)).is_file())
