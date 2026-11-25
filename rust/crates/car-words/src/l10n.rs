//! `l10n.py`: one catalog per language, one way to look a string up, one language to fall back to.
//!
//! * **Which language** - `resolve` takes what the user stored (`"system"` or a locale id) and turns it into exactly
//!   one locale; `"system"` reads what the desktop app reads (the Windows preferred UI languages, which only
//!   car-platform can ask, so they are handed in).
//! * **Which tag means which catalog** - `normalize` is the single place that maps a BCP-47-ish tag to a shipped
//!   locale; `None` is a language this product does not have.
//! * **What happens to a key a translator has not reached yet** - English is the source and every other catalog is a
//!   layer over it, so a missing key is impossible at runtime.
//!
//! The catalogs are JSON in `locales/` beside this crate, embedded in the program (they are copies of the
//! Python's, held to them by `tests/rustdiff/diffs_leaves_words.py`). Nothing here reaches the network.

use std::collections::HashMap;
use std::sync::{Mutex, OnceLock};

use car_machine::compat::decode;
use car_machine::json::Value;
use car_machine::pytext::{py_str, strip};
use indexmap::IndexMap;

use crate::bidi_tables::{ARABIC_LETTER, LEFT_TO_RIGHT, RIGHT_TO_LEFT as RIGHT_TO_LEFT_CLASS};
use crate::vocab_gen::l10n as table;

/// The environment override the whole product honours, kept at its original name.
pub const ENV_LANG: &str = table::ENV_LANG;
/// The languages the product's own interface has a catalog for; English first.
pub const LOCALES: &[&str] = table::LOCALES;
pub const DEFAULT: &str = table::DEFAULT;
/// Languages with a complete catalog that a release does not offer (none now).
pub const HELD: &[&str] = table::HELD;
/// The languages a person can choose and Windows can reach: every catalog but the held ones.
pub const OFFERED: &[&str] = table::OFFERED;
/// The catalogs written right to left.
pub const RIGHT_TO_LEFT: &[&str] = table::RIGHT_TO_LEFT;
pub const SYSTEM: &str = table::SYSTEM;
pub const CHOICES: &[&str] = table::CHOICES;

/// A catalog file is not usable. Raised at load time, never at lookup time.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CatalogError(pub String);

impl std::fmt::Display for CatalogError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.0)
    }
}

impl std::error::Error for CatalogError {}

/// A catalog: keys in the order the file (and then each layer's new keys) gives them.
pub type Catalog = IndexMap<String, String>;

macro_rules! sources {
    ($($locale:literal),* $(,)?) => {
        &[$(($locale, include_str!(concat!("../locales/", $locale, ".json")))),*]
    };
}

/// Each shipped catalog's file, as embedded.
pub const SOURCES: &[(&str, &str)] = sources![
    "en", "ko", "ja", "zh-CN", "zh-TW", "es", "de", "fr", "pt-BR", "ru", "it", "tr", "pl", "uk",
    "vi", "id", "ar", "he", "fa", "cs", "hu", "th"
];

fn source(locale: &str) -> Option<&'static str> {
    SOURCES
        .iter()
        .find(|(name, _)| *name == locale)
        .map(|(_, text)| *text)
}

/// `repr()` of a short text, as the Python's messages quote a key.
fn quoted(text: &str) -> String {
    let single = text.contains('\'') && !text.contains('"');
    let quote = if single { '"' } else { '\'' };
    let mut out = String::from(quote);
    for each in text.chars() {
        match each {
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if c == quote => {
                out.push('\\');
                out.push(c);
            }
            c if c.is_control() => out.push_str(&format!("\\x{:02x}", c as u32)),
            c => out.push(c),
        }
    }
    out.push(quote);
    out
}

/// `read_catalog(path)` for the bytes of one file named `name`: UTF-8 JSON, one object, every value text, no key twice.
pub fn read_catalog(name: &str, raw: &[u8]) -> Result<Catalog, CatalogError> {
    let not_json = |why: &str| CatalogError(format!("{name} is not JSON ({why})"));
    if raw.starts_with(b"\xEF\xBB\xBF") {
        return Err(not_json("Unexpected UTF-8 BOM"));
    }
    let loaded = match decode(raw, usize::MAX) {
        Ok(value) => value,
        Err(refused) if refused.code == "duplicate_key" => {
            return Err(CatalogError("duplicate key".into()));
        }
        Err(refused) => return Err(not_json(refused.code)),
    };
    let Value::Object(map) = loaded else {
        return Err(CatalogError(format!(
            "{name} does not hold an object of key to string"
        )));
    };
    let mut found = Catalog::with_capacity(map.len());
    for (key, value) in &map {
        let key = String::from_utf8_lossy(key.as_bytes()).into_owned();
        match value {
            Value::Str(text) => {
                found.insert(key, String::from_utf8_lossy(text.as_bytes()).into_owned());
            }
            _ => {
                return Err(CatalogError(format!(
                    "{name}: {} is not text",
                    quoted(&key)
                )));
            }
        }
    }
    Ok(found)
}

fn read(locale: &str) -> Result<Catalog, CatalogError> {
    let text =
        source(locale).ok_or_else(|| CatalogError(format!("{locale}.json is unreadable")))?;
    read_catalog(&format!("{locale}.json"), text.as_bytes())
}

fn cache() -> &'static Mutex<HashMap<String, Catalog>> {
    static CACHE: OnceLock<Mutex<HashMap<String, Catalog>>> = OnceLock::new();
    CACHE.get_or_init(|| Mutex::new(HashMap::new()))
}

/// `catalog(locale)`: every key, in this locale where it exists and in English where it does not. Cached; a catalog
/// that is missing, malformed or truncated is a packaging or translation fault the tests fail on, not a reason to take
/// a window down, so the English underneath is what a person gets.
pub fn catalog(locale: &str) -> Catalog {
    with_catalog(locale, Catalog::clone)
}

/// `body` of the cached catalog of `locale` (`catalog`'s, without a copy: `text` reads one key of it).
fn with_catalog<R>(locale: &str, body: impl FnOnce(&Catalog) -> R) -> R {
    let locale = if LOCALES.contains(&locale) {
        locale
    } else {
        DEFAULT
    };
    let mut kept = cache().lock().expect("the catalog cache");
    if !kept.contains_key(locale) {
        let mut found = read(DEFAULT).unwrap_or_default();
        if locale != DEFAULT
            && let Ok(layer) = read(locale)
        {
            for (key, value) in layer {
                found.insert(key, value);
            }
        }
        kept.insert(locale.to_owned(), found);
    }
    body(&kept[locale])
}

// ---------------------------------------------------------------- which language
const LANGUAGE_HOME: &[(&str, &str)] = &[
    ("en", "en"),
    ("ko", "ko"),
    ("ja", "ja"),
    ("es", "es"),
    ("de", "de"),
    ("fr", "fr"),
    ("pt", "pt-BR"),
    ("ru", "ru"),
    ("it", "it"),
    ("tr", "tr"),
    ("pl", "pl"),
    ("uk", "uk"),
    ("vi", "vi"),
    ("id", "id"),
    ("in", "id"),
    ("ar", "ar"),
    ("he", "he"),
    ("iw", "he"),
    ("fa", "fa"),
    ("cs", "cs"),
    ("hu", "hu"),
    ("th", "th"),
];

/// `normalize(tag)`: the offered locale a language tag belongs to, or `None` if this product has none.
pub fn normalize(tag: &str) -> Option<&'static str> {
    let replaced = strip(tag).replace('_', "-");
    let parts: Vec<&str> = replaced
        .split('-')
        .filter(|part| !part.is_empty())
        .collect();
    let language = parts.first()?.to_lowercase();
    let rest: Vec<String> = parts[1..].iter().map(|part| part.to_lowercase()).collect();
    if language == "zh" {
        for part in &rest {
            if part == "hant" || matches!(part.as_str(), "tw" | "hk" | "mo") {
                return Some("zh-TW");
            }
            if part == "hans" {
                return Some("zh-CN");
            }
        }
        return Some("zh-CN");
    }
    let home = LANGUAGE_HOME
        .iter()
        .find(|(each, _)| *each == language)
        .map(|(_, home)| *home)?;
    OFFERED.iter().copied().find(|offered| *offered == home)
}

/// The environment as a lookup: a name's value, or none.
pub type Environ<'a> = &'a dyn Fn(&str) -> Option<String>;

/// `preferred_languages(environ)`: the override, else the Windows user's preferred UI languages (`windows`, asked
/// of the platform by the caller), else the POSIX variables.
pub fn preferred_languages(environ: Environ, windows: &dyn Fn() -> Vec<String>) -> Vec<String> {
    let override_ = environ(ENV_LANG).unwrap_or_default();
    let override_ = strip(&override_);
    if !override_.is_empty() {
        return vec![override_.to_owned()];
    }
    let tags = windows();
    if !tags.is_empty() {
        return tags;
    }
    for name in ["LC_ALL", "LC_MESSAGES", "LANG"] {
        let value = environ(name).unwrap_or_default();
        let value = strip(&value);
        if !value.is_empty() && value != "C" && value != "POSIX" {
            let head = value.split('.').next().unwrap_or("");
            return vec![head.replace('_', "-")];
        }
    }
    Vec::new()
}

/// `from_system(environ)`: the locale Windows asks for, or English. Only the most preferred language counts.
pub fn from_system(environ: Environ, windows: &dyn Fn() -> Vec<String>) -> &'static str {
    match preferred_languages(environ, windows).first() {
        Some(tag) => normalize(tag).unwrap_or(DEFAULT),
        None => DEFAULT,
    }
}

/// `resolve(preference, environ)`: the one locale to render in, from what the user stored. `preference` is the
/// stored value where it is text; anything else (`None`) follows Windows.
pub fn resolve(
    preference: Option<&str>,
    environ: Environ,
    windows: &dyn Fn() -> Vec<String>,
) -> &'static str {
    if let Some(stored) = preference {
        let chosen = strip(stored);
        if !chosen.is_empty() && chosen != SYSTEM {
            if let Some(offered) = OFFERED.iter().copied().find(|each| *each == chosen) {
                return offered;
            }
            return normalize(chosen).unwrap_or(DEFAULT);
        }
    }
    from_system(environ, windows)
}

// ---------------------------------------------------------------- preference
fn preference_cell() -> &'static Mutex<String> {
    static PREFERENCE: OnceLock<Mutex<String>> = OnceLock::new();
    PREFERENCE.get_or_init(|| Mutex::new(SYSTEM.to_owned()))
}

/// `set_preference(value)`: adopt a stored Interface language; anything unrecognised is `system`. Returns the
/// locale it now resolves to.
pub fn set_preference(
    value: Option<&str>,
    environ: Environ,
    windows: &dyn Fn() -> Vec<String>,
) -> &'static str {
    let adopted = value
        .filter(|each| CHOICES.contains(each))
        .unwrap_or(SYSTEM)
        .to_owned();
    *preference_cell().lock().expect("the preference") = adopted;
    current(environ, windows)
}

/// `preference()`.
pub fn preference() -> String {
    preference_cell().lock().expect("the preference").clone()
}

/// `current(environ)`: the locale this process renders in right now.
pub fn current(environ: Environ, windows: &dyn Fn() -> Vec<String>) -> &'static str {
    resolve(Some(&preference()), environ, windows)
}

/// `ENDONYMS[locale]`: each language named in itself.
pub fn endonym(locale: &str) -> Option<&'static str> {
    table::ENDONYMS
        .get(locale)
        .and_then(car_machine::vocab::Node::as_str)
}

/// `offered_endonyms()`: the names a surface labels its language pickers with, the OFFERED languages' only.
pub fn offered_endonyms() -> Vec<(&'static str, &'static str)> {
    OFFERED
        .iter()
        .filter_map(|locale| endonym(locale).map(|name| (*locale, name)))
        .collect()
}

// ---------------------------------------------------------------- strings
/// `placeholders(value)`: the `{name}` placeholders in one string, a name being `[a-z_][a-z0-9_]*`; sorted, once each.
pub fn placeholders(value: &str) -> Vec<String> {
    let chars: Vec<char> = value.chars().collect();
    let mut found: Vec<String> = Vec::new();
    let mut at = 0;
    while at < chars.len() {
        if chars[at] == '{'
            && chars
                .get(at + 1)
                .is_some_and(|each| each.is_ascii_lowercase() || *each == '_')
        {
            let mut end = at + 2;
            while chars.get(end).is_some_and(|each| {
                each.is_ascii_lowercase() || each.is_ascii_digit() || *each == '_'
            }) {
                end += 1;
            }
            if chars.get(end) == Some(&'}') {
                let name: String = chars[at + 1..end].iter().collect();
                if !found.contains(&name) {
                    found.push(name);
                }
                at = end + 1;
                continue;
            }
        }
        at += 1;
    }
    found.sort();
    found
}

/// `fill(value, **fields)`: `value` with every `{name}` the caller supplies filled in, one after another in the order
/// given, and nothing else touched.
pub fn fill(value: &str, fields: &[(&str, String)]) -> String {
    let mut text = value.to_owned();
    for (name, supplied) in fields {
        text = text.replace(&format!("{{{name}}}"), supplied);
    }
    text
}

/// `text(key, locale, **fields)`: one string, formatted; a key the catalog lacks is a KeyError (`None`).
pub fn text(key: &str, locale: &str, fields: &[(&str, String)]) -> Option<String> {
    // The reference copies the whole catalog for each key (`dict(_CACHE[locale])`); one key is read from the cache.
    with_catalog(locale, |found| {
        found.get(key).map(|value| fill(value, fields))
    })
}

/// `messages(locale)`: the plugin's own sentences in one locale, keyed without their `msg.` prefix.
pub fn messages(locale: &str) -> Catalog {
    catalog(locale)
        .into_iter()
        .filter_map(|(key, value)| {
            key.strip_prefix("msg.")
                .map(|short| (short.to_owned(), value))
        })
        .collect()
}

/// `message(key, environ)`: one of the plugin's own sentences, in the language this process speaks.
pub fn message(key: &str, environ: Environ, windows: &dyn Fn() -> Vec<String>) -> Option<String> {
    text(&format!("msg.{key}"), current(environ, windows), &[])
}

// ---------------------------------------------------------------- direction
const LEFT_TO_RIGHT_EMBEDDING: char = '\u{202a}';
const RIGHT_TO_LEFT_EMBEDDING: char = '\u{202b}';
const POP: char = '\u{202c}';

/// `right_to_left(locale)`: whether a surface in `locale` is drawn right to left.
pub fn right_to_left(locale: &str) -> bool {
    RIGHT_TO_LEFT.contains(&locale)
}

fn in_ranges(table: &[(u32, u32)], point: u32) -> bool {
    table
        .binary_search_by(|&(low, high)| {
            if point < low {
                std::cmp::Ordering::Greater
            } else if point > high {
                std::cmp::Ordering::Less
            } else {
                std::cmp::Ordering::Equal
            }
        })
        .is_ok()
}

/// The bidirectional class of a character, as far as the first-strong rule needs it: `L`, `R` (R or AL), or none.
pub fn strong(each: char) -> Option<char> {
    let point = each as u32;
    if in_ranges(LEFT_TO_RIGHT, point) {
        Some('L')
    } else if in_ranges(RIGHT_TO_LEFT_CLASS, point) || in_ranges(ARABIC_LETTER, point) {
        Some('R')
    } else {
        None
    }
}

/// `first_strong(value)`: "L" or "R" by the first character of `str(value)` with a direction of its own (Unicode's
/// rule P2), none when it has none.
pub fn first_strong(value: &Value) -> Option<char> {
    py_str(value).chars().find_map(strong)
}

/// `embedded(value, locale)`: `value` kept one run inside a sentence of `locale`: in a right-to-left language embedded
/// in its own first strong direction (left to right when it has none); otherwise itself.
pub fn embedded(value: &Value, locale: &str) -> String {
    let text = py_str(value);
    if !right_to_left(locale) || text.is_empty() {
        return text;
    }
    let mark = if first_strong(value) == Some('R') {
        RIGHT_TO_LEFT_EMBEDDING
    } else {
        LEFT_TO_RIGHT_EMBEDDING
    };
    format!("{mark}{text}{POP}")
}

/// `available()`: the locales that have a catalog shipped, which is every one of them.
pub fn available() -> Vec<&'static str> {
    LOCALES
        .iter()
        .copied()
        .filter(|locale| source(locale).is_some())
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn none(_: &str) -> Option<String> {
        None
    }

    #[test]
    fn every_locale_has_its_catalog_and_english_has_every_key() {
        assert_eq!(available(), LOCALES);
        let english = catalog("en");
        assert!(english.len() > 1000);
        for locale in LOCALES {
            let layered = catalog(locale);
            assert_eq!(layered.len(), english.len(), "{locale}");
            assert!(read(locale).is_ok(), "{locale}");
        }
    }

    #[test]
    fn tags() {
        assert_eq!(normalize("ko-KR"), Some("ko"));
        assert_eq!(normalize("zh-Hant-TW"), Some("zh-TW"));
        assert_eq!(normalize("zh"), Some("zh-CN"));
        assert_eq!(normalize("pt_PT"), Some("pt-BR"));
        assert_eq!(normalize("xx"), None);
        assert_eq!(normalize(""), None);
        assert_eq!(resolve(Some("ko"), &none, &Vec::new), "ko");
        assert_eq!(resolve(Some("KO-kr"), &none, &Vec::new), "ko");
        assert_eq!(resolve(Some("klingon"), &none, &Vec::new), "en");
        assert_eq!(resolve(None, &none, &|| vec!["de-AT".to_owned()]), "de");
    }

    #[test]
    fn filling_and_placeholders() {
        assert_eq!(placeholders("{b} {{a}} {a_1} {1} {B}"), ["a", "a_1", "b"]);
        assert_eq!(
            fill("{a}{b}", &[("a", "{b}".to_owned()), ("b", "x".to_owned())]),
            "xx"
        );
    }

    #[test]
    fn embedding() {
        let version = Value::from("0.6.1");
        assert_eq!(embedded(&version, "ar"), "\u{202a}0.6.1\u{202c}");
        assert_eq!(embedded(&version, "en"), "0.6.1");
        assert_eq!(
            embedded(&Value::from("\u{5d0}b"), "he"),
            "\u{202b}\u{5d0}b\u{202c}"
        );
    }

    #[test]
    fn a_catalog_is_held_to_its_rules() {
        assert!(read_catalog("x.json", b"{\"a\": 1}").is_err());
        assert!(read_catalog("x.json", b"{\"a\": \"1\", \"a\": \"2\"}").is_err());
        assert!(read_catalog("x.json", b"[]").is_err());
        assert!(read_catalog("x.json", b"\xEF\xBB\xBF{}").is_err());
        assert!(read_catalog("x.json", b"{\"a\": \"1\"}").is_ok());
    }
}
