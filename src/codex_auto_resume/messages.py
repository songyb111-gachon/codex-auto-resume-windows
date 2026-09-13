"""User-facing strings for the plugin layer, in English by default.

Korean is used only when the locale *explicitly* says Korean. Detection reuses the
same source the ChatGPT desktop app itself uses to pick its display language
(``app.getPreferredSystemLanguages()`` -> ``GetUserPreferredUILanguages`` on Windows),
so this tool speaks whatever the app speaks. Nothing here infers a language from an
IP address, a time zone, a user name, a country or a keyboard layout.
"""
from __future__ import annotations

from . import l10n

# Re-exported: detection lives in `l10n` now, and these are the names it had here.
ENV_LANG = l10n.ENV_LANG
preferred_languages = l10n.preferred_languages
DEFAULT = l10n.DEFAULT
# Every language the interface ships in. A Windows tag is mapped onto one of these by
# `l10n.normalize`, which is the single place that mapping lives.
SUPPORTED = l10n.LOCALES

# Small table on purpose: no i18n framework, no external dependency. Keys are stable
# identifiers; every key must exist in every language so a lookup can never fall back
# to a missing string at runtime.
# The plugin layer's own sentences, from the same locale files as everything else and
# stored there under a `msg.` prefix so a name like `cancelled` cannot collide with a
# settings label. This was a second hand-maintained table until v0.6.3.
def _plugin_messages(locale):
    return {key[len("msg."):]: value
            for key, value in l10n.catalog(locale).items() if key.startswith("msg.")}


MESSAGES = {locale: _plugin_messages(locale) for locale in l10n.LOCALES}



def language(environ=None) -> str:
    """The language this process speaks: the stored Interface language, else Windows.

    With no choice stored this is what Windows asks for, and only the *most preferred*
    tag counts - a machine that lists Japanese after English is not asking for Japanese.
    """
    return l10n.current(environ)


def text(key: str, environ=None) -> str:
    return l10n.text("msg." + key, language(environ))
