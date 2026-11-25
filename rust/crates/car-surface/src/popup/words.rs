//! The pure part of `ui/popup/words.py` that the popup's model, the card and the icon read: one string from the
//! catalog the icon was given (English underneath it), a name as one bounded line, the right-to-left keeping of a
//! value, which catalog a vocabulary is, and the catalog a stored Interface language speaks. How a line is broken
//! (`unbroken`) is the C# renderer's.

use car_machine::json::{Map, Value};
use car_machine::pytext;
use car_words::l10n;

use crate::py::{str_of, text_of};

/// `say(strings, key, **fields)`: one string from `strings`, English (or the key) where it has no text for it, every
/// `{name}` given filled in, one after another.
pub fn say(strings: &Map, key: &str, fields: &[(&str, String)]) -> String {
    let mut value = match strings.get(key) {
        Some(Value::Str(text)) if !text.is_empty() => text_of(text),
        _ => l10n::text(key, l10n::DEFAULT, &[]).unwrap_or_else(|| key.to_owned()),
    };
    for (name, supplied) in fields {
        value = value.replace(&format!("{{{name}}}"), supplied);
    }
    value
}

/// `one_line(text, limit)`: a conversation name as a single, bounded line.
pub fn one_line(text: &Value, limit: usize) -> String {
    let words: Vec<String> = str_of(text)
        .split(pytext::is_space)
        .filter(|word| !word.is_empty())
        .map(str::to_owned)
        .collect();
    let flat = words.join(" ");
    let length = flat.chars().count();
    if length <= limit {
        return flat;
    }
    let kept: String = flat.chars().take(limit.saturating_sub(1)).collect();
    format!("{kept}\u{2026}")
}

const LOCALE_PROBES: [&str; 4] = [
    "activity.monitoring",
    "popup.nothing",
    "action.pause",
    "popup.open_dashboard",
];

/// `locale_of(strings)`: which shipped catalog a vocabulary is; the language this process speaks (`current`) asked
/// first, and a catalog every probe matches ends the search.
pub fn locale_of(strings: &Map, current: &str) -> &'static str {
    if strings.is_empty() {
        return l10n::DEFAULT;
    }
    let first = l10n::LOCALES.iter().copied().find(|each| *each == current);
    let order: Vec<&'static str> = match first {
        Some(first) => std::iter::once(first)
            .chain(l10n::LOCALES.iter().copied().filter(|each| *each != first))
            .collect(),
        // `l10n.current()` is always a catalog's; anything else is read as English is, after none.
        None => l10n::LOCALES.to_vec(),
    };
    let (mut best, mut score) = (l10n::DEFAULT, -1i64);
    for locale in order {
        let table = l10n::catalog(locale);
        let found = LOCALE_PROBES
            .iter()
            .filter(|key| match (strings.get(**key), table.get(**key)) {
                (Some(Value::Str(text)), Some(expected)) => {
                    text.as_str() == Some(expected.as_str())
                }
                _ => false,
            })
            .count() as i64;
        if found > score {
            best = locale;
            score = found;
        }
        if found == LOCALE_PROBES.len() as i64 {
            break;
        }
    }
    best
}

/// `kept(strings)`: what keeps a value one left-to-right run in a sentence of the language `strings` speak.
pub fn kept(strings: &Map, current: &str) -> impl Fn(&str) -> String + use<> {
    let locale = locale_of(strings, current);
    move |value: &str| l10n::embedded(&Value::from(value), locale)
}

/// `vocabulary(language)`: the catalog a stored Interface language speaks, resolved as the watcher resolves it.
pub fn vocabulary(
    language: &Value,
    environ: l10n::Environ,
    windows: &dyn Fn() -> Vec<String>,
) -> Map {
    let chosen = match language {
        Value::Str(text) => text
            .as_str()
            .filter(|each| l10n::CHOICES.contains(each))
            .unwrap_or(l10n::SYSTEM),
        _ => l10n::SYSTEM,
    };
    let mut made = Map::new();
    for (key, value) in l10n::catalog(l10n::resolve(Some(chosen), environ, windows)) {
        made.insert(key.into(), Value::from(value));
    }
    made
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn lines() {
        assert_eq!(one_line(&Value::from("  a \n b\t"), 120), "a b");
        assert_eq!(one_line(&Value::from("abcdef"), 4), "abc\u{2026}");
        let empty = Map::new();
        assert_eq!(say(&empty, "no.such.key", &[]), "no.such.key");
        assert_eq!(locale_of(&empty, "ko"), "en");
    }
}
