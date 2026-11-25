//! `statement.py`: what a person reads before a capability is turned on - its statement, in their own language.
//!
//! Every capability has one, in five fields (`Field`), and in every language the product has a catalog for
//! (`l10n::LOCALES`). The words live in this package's own catalogs, `locales/<locale>.json`, one per language, held to
//! core's rules by core's own code (`car_words::l10n::read_catalog`, `fill`): UTF-8 JSON, text only, no key twice, English
//! as the layer every other language is laid over. A capability's fields are the keys `statement.<id>.<field>`.
//!
//! The key lists the tag writes out (`PAGE_KEYS`, `CONTINUATION_KEYS`, `EDITION_KEYS`, `WARNING_KEYS`) are generated
//! (`statement_gen.rs`). The catalogs are read at run time from a directory, as the tag reads them, so the package's own
//! files are the ones the C# window reads too; where that directory is, is the host's to say (`Catalogs::new`).

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::{Mutex, PoisonError};

use car_machine::json::Value;
use car_machine::pytext::strip;
use car_words::l10n::{self, Catalog, CatalogError};

use crate::jsonx::{int, object, text, texts};
use crate::registry::CapabilityDef;
use crate::vocabulary::{ArmingWarning, Field};

pub use crate::statement_gen::{CONTINUATION_KEYS, EDITION_KEYS, PAGE_KEYS, WARNING_KEYS};

pub const SENTINEL_KEY: &str = "_edition";
pub const ALL_OFF_KEY: &str = "all_off";
pub const BADGE_KEY: &str = "edition.badge";
pub const NOT_LOADED_KEY: &str = "edition.not_loaded";
pub const SUMMARY_KEY: &str = "edition.summary";
pub const WARNING_TITLE_KEY: &str = "warning.title";
pub const WARNING_NOTE_KEY: &str = "warning.note";
pub const PAGE_PREFIX: &str = "page.";
pub const NAME_PREFIX: &str = "name.";
pub const RESETS_PREFIX: &str = "page.resets.";
pub const REPORT_PREFIX: &str = "page.report.";
pub const CONTINUE_PREFIX: &str = "continue.";

/// `FIELDS`: the five fields of a statement, in the order a person reads them.
pub fn fields() -> &'static [Field] {
    Field::ALL
}

/// `key(capability, field)`: the catalog key of one field of one capability's statement.
pub fn key(capability: &str, field: Field) -> String {
    format!("statement.{capability}.{}", field.as_str())
}

/// `title_key(field)`.
pub fn title_key(field: Field) -> String {
    format!("field.{}", field.as_str())
}

/// `warning_key(warning)`.
pub fn warning_key(warning: ArmingWarning) -> String {
    format!("warning.{}", warning.as_str())
}

/// `name_key(capability)`: the catalog key of a capability's name, as the page lists it.
pub fn name_key(capability: &str) -> String {
    format!("{NAME_PREFIX}{capability}")
}

/// Python's `UnicodeDecodeError`, which the tag lets out of every call that reads a catalog (kept: AUDIT-v0628.md).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Undecodable;

impl Undecodable {
    /// The class the reference raises.
    pub const CLASS: &'static str = "UnicodeDecodeError";
}

/// The locale this process renders in right now (`l10n.current()`), which only the host can say.
pub type Current = Box<dyn Fn() -> String + Send + Sync>;

/// One directory of catalogs, read once each: this package's, or a test's.
pub struct Catalogs {
    directory: PathBuf,
    cache: Mutex<HashMap<String, Catalog>>,
    current: Current,
}

impl Catalogs {
    /// `Catalogs(directory)`: `current` is `l10n.current()`, asked where a call names no locale.
    pub fn new(directory: impl Into<PathBuf>, current: Current) -> Catalogs {
        Catalogs {
            directory: directory.into(),
            cache: Mutex::new(HashMap::new()),
            current,
        }
    }

    pub fn directory(&self) -> &Path {
        &self.directory
    }

    /// `own(locale)`: one language's own entries, exactly as its file has them. The outer error is what the tag lets
    /// through: a file that is not UTF-8 raises `UnicodeDecodeError` out of `Path.read_text`, which `read_catalog` does not
    /// catch (it catches `OSError` only), and no caller in `statement.py` catches it either. The inner one is `CatalogError`.
    pub fn own(&self, locale: &str) -> Result<Result<Catalog, CatalogError>, Undecodable> {
        let name = format!("{locale}.json");
        let raw = match std::fs::read(self.directory.join(&name)) {
            Ok(raw) => raw,
            Err(error) => return Ok(Err(CatalogError(format!("{name} is unreadable ({error})")))),
        };
        if std::str::from_utf8(&raw).is_err() {
            return Err(Undecodable);
        }
        Ok(l10n::read_catalog(&name, &raw))
    }

    fn locale_of(&self, locale: Option<&str>) -> String {
        match locale {
            Some(given) => given.to_owned(),
            None => (self.current)(),
        }
    }

    /// `catalog(locale)`: every key, in `locale` where it has one and in English where it does not. A catalog that cannot
    /// be read is English, as core's are: the tests fail on it, the runtime keeps working.
    pub fn catalog(&self, locale: &str) -> Result<Catalog, Undecodable> {
        let locale = if l10n::LOCALES.contains(&locale) {
            locale
        } else {
            l10n::DEFAULT
        };
        let mut kept = self.cache.lock().unwrap_or_else(PoisonError::into_inner);
        if !kept.contains_key(locale) {
            let mut table = self.own(l10n::DEFAULT)?.unwrap_or_default();
            if locale != l10n::DEFAULT
                && let Ok(layer) = self.own(locale)?
            {
                for (key, value) in layer {
                    table.insert(key, value);
                }
            }
            kept.insert(locale.to_owned(), table);
        }
        Ok(kept[locale].clone())
    }

    /// `text(name, locale, **fields)`: one entry, filled in; `None` when no catalog has it.
    pub fn text(
        &self,
        name: &str,
        locale: Option<&str>,
        fields: &[(&str, String)],
    ) -> Result<Option<String>, Undecodable> {
        let locale = self.locale_of(locale);
        Ok(self
            .catalog(&locale)?
            .get(name)
            .map(|value| l10n::fill(value, fields)))
    }

    /// `badge(on, locale, loaded=)`: the edition badge for a surface to show beside the version: the word for a loaded
    /// installation followed by how many capabilities are armed, or the not-loaded word for one whose package could not be
    /// taken.
    pub fn badge(
        &self,
        on: i64,
        locale: Option<&str>,
        loaded: bool,
    ) -> Result<Option<String>, Undecodable> {
        if !loaded {
            return self.text(NOT_LOADED_KEY, locale, &[]);
        }
        self.text(SUMMARY_KEY, locale, &[("n", on.to_string())])
    }

    /// `words(locale)`: the Advanced features page's words in `locale`, English underneath: every `page.*` and `name.*`
    /// entry, the three states', and the edition's own continuations. Unfilled.
    pub fn words(&self, locale: Option<&str>) -> Result<Catalog, Undecodable> {
        let table = self.catalog(&self.locale_of(locale))?;
        Ok(table
            .into_iter()
            .filter(|(name, _)| {
                name.starts_with(PAGE_PREFIX)
                    || name.starts_with(NAME_PREFIX)
                    || name.starts_with("state.")
                    || CONTINUATION_KEYS.contains(&name.as_str())
            })
            .collect())
    }

    /// `missing(definition)`: `(locale, field)` for every field of `definition`'s statement a language does not have in its
    /// own words. A statement is complete when this is empty.
    pub fn missing(
        &self,
        definition: &CapabilityDef,
    ) -> Result<Vec<(String, String)>, Undecodable> {
        let mut found = Vec::new();
        for locale in l10n::LOCALES {
            let table = self.own(locale)?.unwrap_or_default();
            for field in fields() {
                let held = table
                    .get(&key(&definition.id, *field))
                    .is_some_and(|value| !strip(value).is_empty());
                if !held {
                    found.push(((*locale).to_owned(), field.as_str().to_owned()));
                }
            }
        }
        Ok(found)
    }

    /// `complete_in(definition, locale)`: whether one language has every field of `definition`'s statement in its own words.
    pub fn complete_in(
        &self,
        definition: &CapabilityDef,
        locale: &str,
    ) -> Result<bool, Undecodable> {
        Ok(self
            .missing(definition)?
            .iter()
            .all(|(found, _)| found != locale))
    }

    /// `statement(definition, locale, warnings=)`: what the Dashboard shows before the choice: the five fields, each with
    /// its title, the revision the choice will name, the ids of the standards it departs from, and above them `warnings`.
    pub fn statement(
        &self,
        definition: &CapabilityDef,
        locale: Option<&str>,
        warnings: &[ArmingWarning],
    ) -> Result<Value, Undecodable> {
        let locale = self.locale_of(locale);
        let shown = if l10n::LOCALES.contains(&locale.as_str()) {
            locale.as_str()
        } else {
            l10n::DEFAULT
        };
        let line = |name: &str| -> Result<Value, Undecodable> {
            Ok(match self.text(name, Some(&locale), &[])? {
                Some(found) => text(&found),
                None => Value::Null,
            })
        };
        let (title, note) = (line(WARNING_TITLE_KEY)?, line(WARNING_NOTE_KEY)?);
        let mut items: Vec<Value> = Vec::new();
        for word in warnings {
            items.push(object([
                ("warning", text(word.as_str())),
                ("text", line(&warning_key(*word))?),
            ]));
        }
        let mut fields_shown: Vec<Value> = Vec::new();
        for field in fields() {
            fields_shown.push(object([
                ("field", text(field.as_str())),
                ("title", line(&title_key(*field))?),
                ("text", line(&key(&definition.id, *field))?),
            ]));
        }
        Ok(object([
            ("capability", text(&definition.id)),
            ("revision", int(definition.revision)),
            ("locale", text(shown)),
            ("requires", texts(&definition.requires)),
            ("departs_from", texts(&definition.departs_from)),
            (
                "warnings",
                object([
                    ("title", title),
                    ("note", note),
                    ("items", Value::Array(items)),
                ]),
            ),
            ("fields", Value::Array(fields_shown)),
        ]))
    }
}
