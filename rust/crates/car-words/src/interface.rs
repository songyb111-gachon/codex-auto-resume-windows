//! `interface.py` and `messages.py`: the words the two settings surfaces put on screen, in one table.
//!
//! The standalone window and the Codex panel are handed the resolved language's strings whole, never choosing for
//! themselves. `STRINGS` of the Python (every shipped language's catalog) is [`strings`]; `messages.text` of the
//! Python (a script-compatibility alias of `l10n.message`) is [`crate::l10n::message`].

use crate::l10n::{self, Catalog, Environ};

/// `STRINGS[locale]`: a shipped language's catalog; a locale this product does not ship is a KeyError (`None`).
pub fn strings(locale: &str) -> Option<Catalog> {
    l10n::LOCALES
        .contains(&locale)
        .then(|| l10n::catalog(locale))
}

/// `resolve(preference, environ)`: an explicit choice, else the process's stored one.
pub fn resolve(
    preference: Option<&str>,
    environ: Environ,
    windows: &dyn Fn() -> Vec<String>,
) -> &'static str {
    match preference {
        Some(_) => l10n::resolve(preference, environ, windows),
        None => l10n::resolve(Some(&l10n::preference()), environ, windows),
    }
}

/// `language(environ)`: the locale this process speaks.
pub fn language(environ: Environ, windows: &dyn Fn() -> Vec<String>) -> &'static str {
    resolve(None, environ, windows)
}

/// `catalog(environ)`: the strings for the language this machine resolves to.
pub fn catalog(environ: Environ, windows: &dyn Fn() -> Vec<String>) -> Catalog {
    l10n::catalog(language(environ, windows))
}
