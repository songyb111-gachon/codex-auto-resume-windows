//! The tables of advanced.sqlite and the steps from every earlier version (`state/schema.py`).
//!
//! Every statement, table and word list is the tag's own, generated into `schema_gen.rs` (D13: schema 9, readable
//! from 7, frozen through v0.6.27): the dumps compare `sqlite_master`'s text, so a statement is the tag's bytes.
//! Here are the module's functions - what an opening reads of a stored file - with the reference's regular
//! expressions spelled out ([`pattern`]).

use car_machine::json::Value;
use rusqlite::Connection;

pub use super::schema_gen::*;

use super::errors::{Error, Result};
use super::py;
use super::sql;

/// `_MARK_HALF`.
pub const MARK_HALF: i64 = 0xFFFF_0000;

/// A table's name and its columns, as found (`SessionMixin._tables`) or as a version has them (`TABLES`).
pub type Shape = Vec<(String, Vec<String>)>;

/// A generated table list as a [`Shape`].
pub fn shape(tables: &[(&str, &[&str])]) -> Shape {
    tables
        .iter()
        .map(|(name, columns)| {
            (
                (*name).to_string(),
                columns.iter().map(|column| (*column).to_string()).collect(),
            )
        })
        .collect()
}

/// `tables == shape` of two dicts: the same names, each with the same columns in order.
pub fn same(found: &Shape, known: &[(&str, &[&str])]) -> bool {
    found.len() == known.len()
        && known.iter().all(|(name, columns)| {
            found
                .iter()
                .find(|(each, _)| each == name)
                .is_some_and(|(_, held)| {
                    held.iter().map(String::as_str).eq(columns.iter().copied())
                })
        })
}

/// `holds(tables, known)`: every table of `known` with at least its columns, first.
pub fn holds(found: &Shape, known: &[(&str, &[&str])]) -> bool {
    known.iter().all(|(name, columns)| {
        let held: &[String] = found
            .iter()
            .find(|(each, _)| each == name)
            .map_or(&[], |(_, held)| held.as_slice());
        let prefix = &held[..held.len().min(columns.len())];
        prefix
            .iter()
            .map(String::as_str)
            .eq(columns.iter().copied())
    })
}

/// `readable_from(connection, version)`: the mark's low half, or `version` for a file without the mark.
pub fn readable_from(connection: &Connection, version: i64) -> Result<i64> {
    let found = sql::number(connection, "PRAGMA application_id", &[])?;
    Ok(if found & MARK_HALF == MARK {
        found & !MARK_HALF
    } else {
        version
    })
}

/// The stored CREATE of one table, `fetchone()` of it: None where there is no such table; the text, or Python's
/// TypeError for a NULL a regular expression is handed.
fn stored(connection: &Connection, table: &str) -> Result<Option<String>> {
    let row = sql::first(
        connection,
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
        &[py::word(table)],
    )?;
    match row {
        None => Ok(None),
        Some(values) => match values.into_iter().next() {
            Some(Value::Str(text)) => Ok(Some(text.as_str().unwrap_or_default().to_string())),
            _ => Err(Error::type_error("expected string or bytes-like object")),
        },
    }
}

/// `names_checked(connection)`: whether `options` as stored still has the CHECK on its names.
pub fn names_checked(connection: &Connection) -> Result<bool> {
    Ok(stored(connection, "options")?.is_some_and(|text| pattern::choice_check(&text)))
}

/// `wordings_checked(connection)`: whether `wordings` as stored still has the CHECK on its keys.
pub fn wordings_checked(connection: &Connection) -> Result<bool> {
    Ok(stored(connection, "wordings")?.is_some_and(|text| pattern::choice_check(&text)))
}

/// `hourly_bound(connection)`: the highest global hourly ceiling the stored `meta` names in its CHECK, or None.
pub fn hourly_bound(connection: &Connection) -> Result<Option<i64>> {
    Ok(stored(connection, "meta")?.and_then(|text| pattern::hourly_bound(&text)))
}

/// `widen_words(connection)`: the tables of WORDS_TABLES whose CHECK still says WORDS_BEFORE, made again saying
/// WORDS_MOST - every row, index and id counter kept.
pub fn widen_words(connection: &Connection) -> Result<()> {
    for table in WORDS_TABLES {
        let found = sql::first(
            connection,
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            &[py::word(table)],
        )?;
        let Some(values) = found else { continue };
        let text = match values.into_iter().next() {
            Some(Value::Str(text)) => text.as_str().unwrap_or_default().to_string(),
            _ => return Err(Error::type_error("expected string or bytes-like object")),
        };
        let Some(wider) = pattern::widened(&text, WORDS_BEFORE, WORDS_MOST) else {
            continue;
        };
        let made = pattern::renamed(&wider, table, &format!("CREATE TABLE {table}_wide"));
        let indexes: Vec<Value> = sql::tuples(
            connection,
            "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL",
            &[py::word(table)],
        )?
        .into_iter()
        .filter_map(|row| row.into_iter().next())
        .collect();
        let columns: Vec<String> =
            sql::tuples(connection, &format!("PRAGMA table_info({table})"), &[])?
                .into_iter()
                .map(|row| py::py_str(row.get(1).unwrap_or(&Value::Null)))
                .collect();
        let columns = columns.join(", ");
        let counter = sql::first(
            connection,
            "SELECT seq FROM sqlite_sequence WHERE name=?",
            &[py::word(table)],
        )?;
        sql::exec(connection, &made, &[])?;
        sql::exec(
            connection,
            &format!("INSERT INTO {table}_wide ({columns}) SELECT {columns} FROM {table}"),
            &[],
        )?;
        sql::exec(connection, &format!("DROP TABLE {table}"), &[])?;
        sql::exec(
            connection,
            &format!("ALTER TABLE {table}_wide RENAME TO {table}"),
            &[],
        )?;
        for index in indexes {
            match index {
                Value::Str(text) => {
                    sql::exec(connection, text.as_str().unwrap_or_default(), &[])?;
                }
                _ => return Err(Error::type_error("execute() argument 1 must be str")),
            }
        }
        if let Some(counter) = counter {
            sql::exec(
                connection,
                "DELETE FROM sqlite_sequence WHERE name=?",
                &[py::word(table)],
            )?;
            sql::exec(
                connection,
                "INSERT INTO sqlite_sequence (name, seq) VALUES (?, ?)",
                &[
                    py::word(table),
                    counter.into_iter().next().unwrap_or(Value::Null),
                ],
            )?;
        }
    }
    Ok(())
}

/// The reference's regular expressions over a stored CREATE, as Python's `re` reads them: `\s` any of the
/// characters `str.isspace()` holds, `\d` any decimal digit, `\b` a boundary of `\w`, and under `re.I` a letter
/// matching its other case - with the three Unicode letters `re.I` also takes (U+0130 and U+0131 for `i`, U+212A
/// for `k`, U+017F for `s`).
pub mod pattern {
    use car_machine::pytext;

    fn space(point: char) -> bool {
        pytext::is_space(point)
    }

    /// `letter` (an ASCII letter of a pattern) matched by `found` under `re.I`.
    fn letter_matches(letter: char, found: char) -> bool {
        if found.eq_ignore_ascii_case(&letter) {
            return true;
        }
        match letter.to_ascii_lowercase() {
            'i' => found == '\u{130}' || found == '\u{131}',
            'k' => found == '\u{212a}',
            's' => found == '\u{17f}',
            _ => false,
        }
    }

    /// One token of the patterns below.
    #[derive(Clone, Copy)]
    enum Token<'a> {
        /// Literal text, case-insensitively where `fold`.
        Text(&'a str),
        /// `\s+`
        Spaces,
        /// `\s*`
        AnySpaces,
        /// `\b`
        Boundary,
    }

    /// Match `tokens` at `start` of `points`; the end, or None. `\s+` and `\s*` are greedy, and nothing after them
    /// can begin with a space, so they never need to give anything back.
    fn at(points: &[char], start: usize, tokens: &[Token<'_>], fold: bool) -> Option<usize> {
        let mut index = start;
        for token in tokens {
            match token {
                Token::Text(text) => {
                    for expected in text.chars() {
                        let found = *points.get(index)?;
                        let ok = if fold && expected.is_ascii_alphabetic() {
                            letter_matches(expected, found)
                        } else {
                            found == expected
                        };
                        if !ok {
                            return None;
                        }
                        index += 1;
                    }
                }
                Token::Spaces | Token::AnySpaces => {
                    let begun = index;
                    while points.get(index).is_some_and(|point| space(*point)) {
                        index += 1;
                    }
                    if matches!(token, Token::Spaces) && index == begun {
                        return None;
                    }
                }
                Token::Boundary => {
                    let word = |at: usize| {
                        points.get(at).is_some_and(|point| {
                            car_policy::classify::text::is_word(u32::from(*point))
                        })
                    };
                    let before = index > 0 && word(index - 1);
                    if before == word(index) {
                        return None;
                    }
                }
            }
        }
        Some(index)
    }

    /// `re.search(r"CHECK\s*\(\s*choice\s+IN\b", text, re.I) is not None`.
    pub fn choice_check(text: &str) -> bool {
        let points: Vec<char> = text.chars().collect();
        let tokens = [
            Token::Text("CHECK"),
            Token::AnySpaces,
            Token::Text("("),
            Token::AnySpaces,
            Token::Text("choice"),
            Token::Spaces,
            Token::Text("IN"),
            Token::Boundary,
        ];
        (0..=points.len()).any(|start| at(&points, start, &tokens, true).is_some())
    }

    /// `int(re.search(r"global_hourly\s+BETWEEN\s+1\s+AND\s+(\d+)", text, re.I).group(1))`, or None.
    pub fn hourly_bound(text: &str) -> Option<i64> {
        let points: Vec<char> = text.chars().collect();
        let tokens = [
            Token::Text("global_hourly"),
            Token::Spaces,
            Token::Text("BETWEEN"),
            Token::Spaces,
            Token::Text("1"),
            Token::Spaces,
            Token::Text("AND"),
            Token::Spaces,
        ];
        for start in 0..=points.len() {
            let Some(end) = at(&points, start, &tokens, true) else {
                continue;
            };
            let digits: Vec<u32> = points[end..]
                .iter()
                .map_while(|point| pytext::decimal_value(*point))
                .collect();
            if digits.is_empty() {
                continue;
            }
            // int() of digits past 64 bits: a ceiling no file holds; the comparison with GLOBAL_HOURLY says it is
            // not lower, as Python's int would.
            let mut value: i64 = 0;
            for digit in digits {
                value = value.saturating_mul(10).saturating_add(i64::from(digit));
            }
            return Some(value);
        }
        None
    }

    /// `_WORDS_OLD.sub(group(1) + str(most), text)` where `_WORDS_OLD.search(text)` finds one, else None:
    /// `(length\(words\)\s+BETWEEN\s+1\s+AND\s+)<before>\b`, case-insensitively, every match replaced.
    pub fn widened(text: &str, before: i64, most: i64) -> Option<String> {
        let points: Vec<char> = text.chars().collect();
        let number = before.to_string();
        let head = [
            Token::Text("length(words)"),
            Token::Spaces,
            Token::Text("BETWEEN"),
            Token::Spaces,
            Token::Text("1"),
            Token::Spaces,
            Token::Text("AND"),
            Token::Spaces,
        ];
        let mut out = String::new();
        let mut index = 0;
        let mut found = false;
        while index <= points.len() {
            if let Some(middle) = at(&points, index, &head, true)
                && let Some(end) = at(
                    &points,
                    middle,
                    &[Token::Text(&number), Token::Boundary],
                    true,
                )
            {
                found = true;
                out.extend(&points[index..middle]);
                out.push_str(&most.to_string());
                index = end;
                continue;
            }
            if index < points.len() {
                out.push(points[index]);
            }
            index += 1;
        }
        found.then_some(out)
    }

    /// `re.sub(r"^CREATE TABLE\s+\"?<table>\"?", replacement, text, count=1)`: case-sensitive, at the start only.
    pub fn renamed(text: &str, table: &str, replacement: &str) -> String {
        let points: Vec<char> = text.chars().collect();
        let Some(mut index) = at(
            &points,
            0,
            &[Token::Text("CREATE TABLE"), Token::Spaces],
            false,
        ) else {
            return text.to_string();
        };
        if points.get(index) == Some(&'"') {
            index += 1;
        }
        let Some(mut end) = at(&points, index, &[Token::Text(table)], false) else {
            return text.to_string();
        };
        if points.get(end) == Some(&'"') {
            end += 1;
        }
        let mut out = replacement.to_string();
        out.extend(&points[end..]);
        out
    }
}

#[cfg(test)]
mod tests {
    use super::pattern;

    #[test]
    fn patterns() {
        assert!(pattern::choice_check("x CHECK (choice IN ('a'))"));
        assert!(pattern::choice_check("check(choice\nin('a'))"));
        assert!(!pattern::choice_check("CHECK (choice INx"));
        assert_eq!(
            pattern::hourly_bound("global_hourly BETWEEN 1 AND 12)"),
            Some(12)
        );
        assert_eq!(pattern::hourly_bound("global_hourly BETWEEN 1 AND x"), None);
        assert_eq!(
            pattern::widened("a length(words) BETWEEN 1 AND 8192) b", 8192, 30000).as_deref(),
            Some("a length(words) BETWEEN 1 AND 30000) b")
        );
        assert_eq!(
            pattern::widened("length(words) BETWEEN 1 AND 81920", 8192, 30000),
            None
        );
        assert_eq!(
            pattern::renamed(
                "CREATE TABLE \"prompts\" (x)",
                "prompts",
                "CREATE TABLE prompts_wide"
            ),
            "CREATE TABLE prompts_wide (x)"
        );
    }
}
