//! `domain/skips.py`: why a failed turn was not taken up. The codes are generated into
//! [`crate::vocab_gen::domain_skips`]; `kind` is the one function.

use crate::json::Value;
use crate::pytext::py_str;

/// Whether `repr(value)` of a list or a dict holds the word: some text nested in it does, whatever else it holds.
fn nested_subagent(value: &Value) -> bool {
    match value {
        Value::Str(text) => String::from_utf8_lossy(text.as_bytes())
            .to_lowercase()
            .contains("subagent"),
        Value::Array(items) => items.iter().any(nested_subagent),
        Value::Object(map) => map
            .iter()
            .any(|(key, item)| nested_subagent(&Value::Str(key.clone())) || nested_subagent(item)),
        _ => false,
    }
}

/// `kind(value)`: a kind word as Codex writes one, safe to print: itself where it is a short plain word,
/// `subagent` for any subagent's, `none` for none, else `other`.
pub fn kind(value: &Value) -> String {
    if matches!(value, Value::Null) {
        return "none".into();
    }
    let word = match value {
        Value::Array(_) | Value::Object(_) => {
            // `str()` of a container has brackets or quotes in it, which no kind word has.
            return if nested_subagent(value) {
                "subagent"
            } else {
                "other"
            }
            .into();
        }
        other => py_str(other),
    };
    if word.to_lowercase().contains("subagent") {
        return "subagent".into();
    }
    let plain = (1..=32).contains(&word.chars().count())
        && word
            .chars()
            .all(|each| each.is_ascii_alphanumeric() || matches!(each, '_' | '.' | '-'));
    if plain { word } else { "other".into() }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::json::from_str;

    #[test]
    fn kinds() {
        assert_eq!(kind(&Value::Null), "none");
        assert_eq!(kind(&from_str("\"vscode\"").unwrap()), "vscode");
        assert_eq!(kind(&from_str("\"Sub-SubAgent\"").unwrap()), "subagent");
        assert_eq!(kind(&from_str("\"a b\"").unwrap()), "other");
        assert_eq!(kind(&from_str("12").unwrap()), "12");
    }
}
