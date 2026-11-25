//! car-words' calls: the catalogs, the language choice, the direction marks and the usage sentences.

use car_machine::json::{Map, Str, Value};
use car_machine::pytext::{float_repr, py_str};
use car_machine::pyval::Py;
use car_words::l10n::{self, Environ};
use car_words::words::{self, Say, Tm};

use super::Args;

fn array(items: Vec<Value>) -> Value {
    Value::Array(items)
}

fn strings(items: impl IntoIterator<Item = impl AsRef<str>>) -> Value {
    array(
        items
            .into_iter()
            .map(|each| Value::from(each.as_ref()))
            .collect(),
    )
}

/// `{name: value}` fields, stringified as `str()` does, in the order given.
fn fields(value: &Value) -> Vec<(String, String)> {
    match value {
        Value::Object(map) => map
            .iter()
            .map(|(name, each)| {
                (
                    String::from_utf8_lossy(name.as_bytes()).into_owned(),
                    py_str(each),
                )
            })
            .collect(),
        _ => Vec::new(),
    }
}

fn as_pairs(owned: &[(String, String)]) -> Vec<(&str, String)> {
    owned
        .iter()
        .map(|(name, value)| (name.as_str(), value.clone()))
        .collect()
}

/// An environment given as `{name: text}`.
fn environment(value: &Value) -> impl Fn(&str) -> Option<String> {
    let map: Vec<(String, String)> = fields(value);
    move |name: &str| {
        map.iter()
            .find(|(each, _)| each == name)
            .map(|(_, text)| text.clone())
    }
}

fn windows_of(value: &Value) -> impl Fn() -> Vec<String> {
    let tags: Vec<String> = match value {
        Value::Array(items) => items.iter().map(py_str).collect(),
        _ => Vec::new(),
    };
    move || tags.clone()
}

fn optional_text(value: &Value) -> Option<&str> {
    match value {
        Value::Str(text) => text.as_str(),
        _ => None,
    }
}

/// `{repr(float(at)): [year, month, day, hour, minute]}`, the local times the case was made with.
fn local_times(table: &Value) -> impl Fn(f64) -> Tm {
    let rows: Vec<(String, Tm)> = match table {
        Value::Object(map) => map
            .iter()
            .filter_map(|(key, row)| {
                let Value::Array(parts) = row else {
                    return None;
                };
                let at = |i: usize| match parts.get(i) {
                    Some(Value::Int(int)) => int.as_i64(),
                    _ => None,
                };
                Some((
                    String::from_utf8_lossy(key.as_bytes()).into_owned(),
                    (at(0)?, at(1)?, at(2)?, at(3)?, at(4)?),
                ))
            })
            .collect(),
        _ => Vec::new(),
    };
    move |moment: f64| {
        let key = float_repr(moment);
        rows.iter()
            .find(|(each, _)| *each == key)
            .map_or((0, 0, 0, 0, 0), |(_, tm)| *tm)
    }
}

fn catalog_value(found: l10n::Catalog) -> Value {
    let mut map = Map::with_capacity(found.len());
    for (key, value) in found {
        map.insert(Str::from(key), Value::from(value));
    }
    Value::Object(map)
}

/// `{locale: class}` for each code point: `L`, `R` (R or AL) or `-`.
fn bidi_classes() -> String {
    (0..0x110000u32)
        .map(|point| char::from_u32(point).and_then(l10n::strong).unwrap_or('-'))
        .collect()
}

pub fn case(name: &str, a: &Args) -> Option<Py<Value>> {
    Some(match name {
        "words.catalog_text" => a.text(0).and_then(|locale| {
            l10n::SOURCES
                .iter()
                .find(|(each, _)| *each == locale)
                .map(|(_, text)| Value::from(*text))
                .ok_or("KeyError")
        }),
        "words.catalog" => a.text(0).map(|locale| catalog_value(l10n::catalog(locale))),
        "words.messages" => a
            .text(0)
            .map(|locale| catalog_value(l10n::messages(locale))),
        "words.text" => (|| {
            let (key, locale) = (a.text(0)?, a.text(1)?);
            let owned = fields(a.get(2));
            l10n::text(key, locale, &as_pairs(&owned))
                .map(Value::from)
                .ok_or("KeyError")
        })(),
        "words.fill" => (|| {
            let owned = fields(a.get(1));
            Ok(Value::from(l10n::fill(a.text(0)?, &as_pairs(&owned))))
        })(),
        "words.placeholders" => a.text(0).map(|value| strings(l10n::placeholders(value))),
        "l10n.normalize" => Ok(optional_text(a.get(0))
            .and_then(l10n::normalize)
            .map_or(Value::Null, Value::from)),
        "l10n.preferred_languages" => {
            let (env, windows) = (environment(a.get(0)), windows_of(a.get(1)));
            Ok(strings(l10n::preferred_languages(
                &env as Environ,
                &windows,
            )))
        }
        "l10n.from_system" => {
            let (env, windows) = (environment(a.get(0)), windows_of(a.get(1)));
            Ok(Value::from(l10n::from_system(&env as Environ, &windows)))
        }
        "l10n.resolve" => {
            let (env, windows) = (environment(a.get(1)), windows_of(a.get(2)));
            Ok(Value::from(l10n::resolve(
                optional_text(a.get(0)),
                &env as Environ,
                &windows,
            )))
        }
        "l10n.set_preference" => {
            let (env, windows) = (environment(a.get(1)), windows_of(a.get(2)));
            let now = l10n::set_preference(optional_text(a.get(0)), &env as Environ, &windows);
            Ok(array(vec![
                Value::from(now),
                Value::from(l10n::preference()),
            ]))
        }
        "l10n.right_to_left" => Ok(Value::Bool(
            optional_text(a.get(0)).is_some_and(l10n::right_to_left),
        )),
        "l10n.first_strong" => {
            Ok(l10n::first_strong(a.get(0)).map_or(Value::Null, |c| Value::from(c.to_string())))
        }
        "l10n.embedded" => Ok(Value::from(l10n::embedded(
            a.get(0),
            optional_text(a.get(1)).unwrap_or(""),
        ))),
        "l10n.offered_endonyms" => {
            let mut map = Map::new();
            for (locale, endonym) in l10n::offered_endonyms() {
                map.insert(Str::from(locale), Value::from(endonym));
            }
            Ok(Value::Object(map))
        }
        "l10n.available" => Ok(strings(l10n::available())),
        "bidi.classes" => Ok(Value::from(bidi_classes())),
        // ui/words.py
        "words.countdown" => words::countdown(a.get(0)).map(Value::from),
        "words.age" => (|| {
            let locale = a.text(1)?;
            let say = |key: &str, given: &[(&str, String)]| {
                l10n::text(key, locale, given).unwrap_or_default()
            };
            words::age(a.get(0), &say as Say).map(Value::from)
        })(),
        "words.window_name" => (|| {
            let locale = a.text(1)?;
            let say = |key: &str, given: &[(&str, String)]| {
                l10n::text(key, locale, given).unwrap_or_default()
            };
            Ok(Value::from(words::window_name(a.get(0), &say as Say)))
        })(),
        "words.share" => words::share(a.get(0)).map(Value::Int),
        "words.left" => words::left(a.get(0)).map(Value::from),
        "words.clock_time" => (|| {
            let (moment, today) = (tm(a.get(0))?, tm(a.get(1))?);
            Ok(Value::from(words::clock_time(moment, today)))
        })(),
        "words.usage_windows" | "words.usage_line" => (|| {
            let locale = a.text(1)?;
            let say = |key: &str, given: &[(&str, String)]| {
                l10n::text(key, locale, given).unwrap_or_default()
            };
            let local = local_times(a.get(4));
            let rtl = a.flag(2);
            let keep = |text: &str| {
                if rtl {
                    l10n::embedded(&Value::from(text), locale)
                } else {
                    text.to_owned()
                }
            };
            if name == "words.usage_windows" {
                words::usage_windows(a.get(0), &say as Say, a.get(3), &local, &keep)
                    .map(Value::from)
            } else {
                words::usage_line(a.get(0), &say as Say, a.get(3), &local, &keep)
                    .map(|found| found.map_or(Value::Null, Value::from))
            }
        })(),
        _ => return None,
    })
}

fn tm(value: &Value) -> Py<Tm> {
    let Value::Array(parts) = value else {
        return Err("TypeError");
    };
    let at = |i: usize| match parts.get(i) {
        Some(Value::Int(int)) => int.as_i64().ok_or("OverflowError"),
        _ => Err("TypeError"),
    };
    Ok((at(0)?, at(1)?, at(2)?, at(3)?, at(4)?))
}
