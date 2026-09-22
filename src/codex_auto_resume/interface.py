"""Every word the two settings surfaces put on screen, in one table.

The standalone Windows window and the Codex panel show the same product. Until v0.5.6
they each carried their own English literals - one set in C#, one set in JavaScript - and
the plugin layer had a third set in Python for its own messages. Three copies of the same
vocabulary is how "Retry timing" becomes three different words, and it is why the two
settings surfaces were English no matter what language the rest of the product spoke.

So there is one catalog, here, and both surfaces are handed the resolved language's
strings rather than choosing for themselves:

    messages.language()          decides once, from the Windows preferred UI languages
        |
        +-- controlcli `strings` -> the standalone window, over the bridge it already uses
        +-- mcpui.settings_page  -> the Codex panel, embedded in the page it already seeds

Neither surface guesses. The C# window does not read the registry and the panel's
JavaScript does not look at `navigator.language`, because a product that speaks Korean in
its notifications and English in its settings window is worse than one that picks either.

Keys are stable identifiers and every key exists in every language; `tests/test_locale.py`
asserts that, so a missing string cannot reach a user as a blank label or an English word
in the middle of a Korean sentence.

Brand names are not translated: Codex, Codex Auto Resume, Windows, MCP. Korean particles
attach to them normally.
"""
from __future__ import annotations

from collections.abc import Mapping

from . import l10n, messages

# Ordinary UI vocabulary. The `field.*` keys are the settings schema's own names, so a
# setting added to `settings.py` needs a line here and nowhere else; a missing one shows
# the humanised English name rather than a blank, and the test says so out loud.
# The strings themselves live in `locales/*.json` - one file per language, English the
# source and every other a layer over it. They were a literal table here until v0.6.3,
# which was workable while there were two languages and is not with nine: a table in a
# source file cannot be handed to a translator, cannot be diffed usefully when one label
# changes, and cannot be checked for a duplicated key, because Python's own parser
# silently keeps the last one.
#
# `STRINGS` stays because everything that reads it still reads it, and because the
# shape - language to key to text - is the right one. It is now a view onto the files.
# Every shipped language, not only the ones whose file is complete: a catalog is
# English with the locale's own entries layered over it, so every locale always has
# every key. `tests/test_l10n.py` checks the files themselves for completeness,
# which is the question this mapping deliberately cannot answer.
class _Catalogs(Mapping):
    """Every shipped language's catalog, each built the first time it is asked for.

    This was a dict comprehension at import, so importing this module built nine catalogs and read
    the English file nine times - in the watcher, in every bridge process and in the MCP server,
    each of which uses exactly one language. `l10n.catalog` caches, so nothing is read twice; what
    changes is that eight languages nobody asked for are never read at all.
    """

    def __getitem__(self, locale):
        if locale not in l10n.LOCALES:
            raise KeyError(locale)
        return l10n.catalog(locale)

    def __iter__(self):
        return iter(l10n.LOCALES)

    def __len__(self):
        return len(l10n.LOCALES)


STRINGS = _Catalogs()

def catalog(environ=None) -> dict:
    """The strings for the language this machine resolves to, as a plain dict.

    Handed whole to each surface rather than looked up key by key across a process
    boundary: the standalone window makes one bridge call at startup and the panel is
    seeded once, so neither can end up rendering half of one language.
    """
    return l10n.catalog(resolve(environ=environ))


def language(environ=None) -> str:
    return resolve(environ=environ)


def resolve(preference=None, environ=None) -> str:
    """The locale to render in: an explicit choice, else the process's stored one.

    With nothing passed this is the Interface language the process adopted from its
    settings, which is `system` - follow Windows - until somebody chooses otherwise.
    """
    return l10n.resolve(l10n.preference() if preference is None else preference, environ)
