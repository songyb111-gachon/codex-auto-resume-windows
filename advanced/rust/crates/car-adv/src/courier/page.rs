//! `courier/page.py` (seat S7.3b): the loopback API's web view, one small page served at `/` by `api`.
//!
//! It carries no data and needs no token itself: its script reads the token from the address's fragment and asks
//! `status.json` and `pending` on this same origin, then writes what they answered as text. Its Content-Security-Policy
//! lets it load nothing from anywhere and connect only to its own origin. Its words are the person's language's, put in
//! as a JSON value escaped for a script. The template is the tag's, byte for byte (`page_template.html`).

#![allow(clippy::result_unit_err)]

use car_machine::json::{Map, Options, Str, Value, to_string};

pub const CSP: &str = "default-src 'none'; script-src 'self' 'unsafe-inline'; connect-src 'self'; style-src 'unsafe-inline'; \
                       base-uri 'none'; form-action 'none'; frame-ancestors 'none'";

/// `WORDS`: the page's words, their catalog keys and English fallbacks.
pub const WORDS: [(&str, &str, &str); 12] = [
    ("title", "page.api.title", "Codex Auto Resume - this PC"),
    ("watcher", "page.api.watcher", "Watcher"),
    ("recovery", "page.api.recovery", "Recovery"),
    ("pending", "page.api.pending", "Waiting"),
    ("next_check", "page.api.next_check", "Next check"),
    (
        "no_token",
        "page.api.ask_token",
        "Open this page from the address the Dashboard copied: it carries the token.",
    ),
    ("refused", "page.api.refused", "The token was not accepted."),
    ("running", "page.api.word.running", "running"),
    ("stopped", "page.api.word.stopped", "stopped"),
    ("on", "page.api.word.on", "on"),
    ("paused", "page.api.word.paused", "paused"),
    (
        "observe_only",
        "page.api.word.observe_only",
        "only watching",
    ),
];

const TEMPLATE: &str = include_str!("page_template.html");

/// `html.escape(text)` (quote on).
pub fn html_escape(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    for c in text.chars() {
        match c {
            '&' => out.push_str("&amp;"),
            '<' => out.push_str("&lt;"),
            '>' => out.push_str("&gt;"),
            '"' => out.push_str("&quot;"),
            '\'' => out.push_str("&#x27;"),
            other => out.push(other),
        }
    }
    out
}

/// `render(catalog, locale)`: the page in `catalog`'s words, as UTF-8 bytes. `Err` where a word cannot be written (a
/// lone surrogate, which Python's `encode("utf-8")` refuses).
pub fn render(catalog: &Map, locale: &Value) -> Result<Vec<u8>, ()> {
    let mut words = Map::new();
    for (name, key, fallback) in WORDS {
        let value = match catalog.get(key) {
            Some(Value::Str(text)) => Value::Str(text.clone()),
            _ => Value::from(fallback),
        };
        words.insert(Str::from(name), value);
    }
    let title = car_machine::pytext::py_str(words.get("title").unwrap_or(&Value::Null));
    let script = to_string(&Value::Object(words), &Options::new())
        .map_err(|_| ())?
        .replace('<', "\\u003c")
        .replace('>', "\\u003e")
        .replace('&', "\\u0026");
    let lang = match locale {
        Value::Str(text) => {
            let text = text.as_str().unwrap_or("");
            let bare: String = text.chars().filter(|c| *c != '-').collect();
            if !bare.is_empty() && bare.chars().all(char::is_alphanumeric) {
                text.to_owned()
            } else {
                "en".to_owned()
            }
        }
        _ => "en".to_owned(),
    };
    if title
        .chars()
        .any(|c| (0xD800..=0xDFFF).contains(&(c as u32)))
    {
        return Err(());
    }
    // `TEMPLATE % {...}`: one pass, so a word that reads like a placeholder stays a word.
    let (lang, title) = (html_escape(&lang), html_escape(&title));
    let mut page = String::with_capacity(TEMPLATE.len() + script.len());
    let mut rest = TEMPLATE;
    while let Some(at) = rest.find("%(") {
        page.push_str(&rest[..at]);
        let after = &rest[at..];
        let (value, length) = if after.starts_with("%(lang)s") {
            (lang.as_str(), 8)
        } else if after.starts_with("%(title)s") {
            (title.as_str(), 9)
        } else if after.starts_with("%(words)s") {
            (script.as_str(), 9)
        } else {
            ("%(", 2)
        };
        page.push_str(value);
        rest = &after[length..];
    }
    page.push_str(rest);
    Ok(page.into_bytes())
}
