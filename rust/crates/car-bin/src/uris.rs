//! The capability URIs a notice's buttons carry, read as `activate` reads them (`notice_uris.parse_*`,
//! `codex_link.parse_chat_uri`, over `urllib.parse.urlsplit` and `parse_qs`). car-surface owns `notice_uris` (another
//! seat); this is the reading `activate` needs, behind a module the integration replaces with car-surface's.

use car_machine::domain::ids;
use car_machine::json::Value;
use car_machine::vocab_gen::domain_public::PAGES;

const SCHEME: &str = "codex-auto-resume";
const CHAT_LINK: &str = "codex-auto-resume:chat?thread=";

/// What a URI asks for, in the order `cmd_activate` asks.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Activation {
    Chat(String),
    Open(String),
    PowerStop,
    Cancel { id: String, open_codex: bool },
    Malformed,
}

/// `urlsplit(url)`: (scheme, netloc, path, query), or None where it raises ValueError.
fn urlsplit(url: &str) -> Option<(String, String, String, String)> {
    let stripped = url.trim_start_matches(|c: char| (c as u32) <= 0x20);
    let mut url: String = stripped
        .chars()
        .filter(|c| !matches!(c, '\t' | '\r' | '\n'))
        .collect();
    let mut scheme = String::new();
    if let Some(colon) = url.find(':')
        && colon > 0
    {
        let head = &url[..colon];
        let first = head.chars().next().unwrap_or(' ');
        if first.is_ascii_alphabetic()
            && head
                .chars()
                .all(|c| c.is_ascii_alphanumeric() || matches!(c, '+' | '-' | '.'))
        {
            scheme = head.to_ascii_lowercase();
            url = url[colon + 1..].to_owned();
        }
    }
    let mut netloc = String::new();
    if url.starts_with("//") {
        let rest = &url[2..];
        let end = rest.find(['/', '?', '#']).unwrap_or(rest.len());
        netloc = rest[..end].to_owned();
        url = rest[end..].to_owned();
        let (open, close) = (netloc.contains('['), netloc.contains(']'));
        if open != close {
            return None;
        }
    }
    if let Some(hash) = url.find('#') {
        url.truncate(hash);
    }
    let mut query = String::new();
    if let Some(mark) = url.find('?') {
        query = url[mark + 1..].to_owned();
        url.truncate(mark);
    }
    Some((scheme, netloc, url, query))
}

/// `unquote(text)`: `%XX` as bytes decoded as UTF-8, a bad sequence replaced.
fn unquote(text: &str) -> String {
    if !text.contains('%') {
        return text.to_owned();
    }
    let bytes = text.as_bytes();
    let mut out = Vec::with_capacity(bytes.len());
    let mut at = 0;
    while at < bytes.len() {
        if bytes[at] == b'%' {
            let hex = |b: u8| (b as char).to_digit(16);
            if let (Some(Some(a)), Some(Some(b))) = (
                bytes.get(at + 1).map(|b| hex(*b)),
                bytes.get(at + 2).map(|b| hex(*b)),
            ) {
                out.push((a * 16 + b) as u8);
                at += 3;
                continue;
            }
        }
        out.push(bytes[at]);
        at += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

/// `parse_qs(query, keep_blank_values=...)`: names in first-seen order, each with its values.
fn parse_qs(query: &str, keep_blank: bool) -> Vec<(String, Vec<String>)> {
    let mut found: Vec<(String, Vec<String>)> = Vec::new();
    if query.is_empty() {
        return found;
    }
    for pair in query.split('&') {
        if pair.is_empty() {
            continue;
        }
        let (name, value) = match pair.split_once('=') {
            Some((name, value)) => (name, value),
            None if keep_blank => (pair, ""),
            None => continue,
        };
        if value.is_empty() && !keep_blank {
            continue;
        }
        let name = unquote(&name.replace('+', " "));
        let value = unquote(&value.replace('+', " "));
        match found.iter_mut().find(|(each, _)| *each == name) {
            Some((_, values)) => values.push(value),
            None => found.push((name, vec![value])),
        }
    }
    found
}

fn values_of<'a>(parsed: &'a [(String, Vec<String>)], name: &str) -> &'a [String] {
    parsed
        .iter()
        .find(|(each, _)| each == name)
        .map_or(&[], |(_, values)| values.as_slice())
}

/// `(parts.path or parts.netloc or "").strip("/").lower()` of a URI of this scheme.
fn action(url: &str) -> Option<(String, String)> {
    let (scheme, netloc, path, query) = urlsplit(url)?;
    if scheme != SCHEME {
        return None;
    }
    let named = if !path.is_empty() { path } else { netloc };
    Some((named.trim_matches('/').to_lowercase(), query))
}

/// `parse_cancel_uri(uri)`.
pub fn parse_cancel_uri(uri: &str) -> Option<String> {
    let (named, query) = action(uri)?;
    if named != "cancel" {
        return None;
    }
    let parsed = parse_qs(&query, false);
    let values = values_of(&parsed, "i");
    if values.len() != 1 {
        return None;
    }
    ids::read_interruption_id(&values[0])
}

/// `cancel_asks_open_codex(uri)`.
pub fn cancel_asks_open_codex(uri: &str) -> bool {
    if parse_cancel_uri(uri).is_none() {
        return false;
    }
    let Some((_, _, _, query)) = urlsplit(uri) else {
        return false;
    };
    let parsed = parse_qs(&query, false);
    values_of(&parsed, "c") == ["1".to_owned()]
}

/// `parse_open_uri(uri)`.
pub fn parse_open_uri(uri: &str) -> Option<String> {
    let (named, query) = action(uri)?;
    if named != "open" {
        return None;
    }
    let parsed = parse_qs(&query, false);
    let values = values_of(&parsed, "page");
    if values.len() != 1 {
        return None;
    }
    let page = car_machine::pytext::strip(&values[0]).to_lowercase();
    PAGES.contains(&page.as_str()).then_some(page)
}

/// `parse_power_stop_uri(uri)`.
pub fn parse_power_stop_uri(uri: &str) -> Option<String> {
    let (named, query) = action(uri)?;
    if named != "power-stop" {
        return None;
    }
    let parsed = parse_qs(&query, true);
    let values = values_of(&parsed, "n");
    if values.len() != 1 || parsed.len() != 1 {
        return None;
    }
    ids::is_power_nonce(&Value::from(values[0].as_str())).then(|| values[0].clone())
}

/// `parse_chat_uri(uri)`.
pub fn parse_chat_uri(uri: &str) -> Option<String> {
    let thread = uri.strip_prefix(CHAT_LINK)?;
    ids::is_uuid(&Value::from(thread)).then(|| thread.to_owned())
}

/// `cmd_activate`'s reading, in its order.
pub fn parse(uri: &str) -> Activation {
    if let Some(thread) = parse_chat_uri(uri) {
        return Activation::Chat(thread);
    }
    if let Some(page) = parse_open_uri(uri) {
        return Activation::Open(page);
    }
    if parse_power_stop_uri(uri).is_some() {
        return Activation::PowerStop;
    }
    match parse_cancel_uri(uri) {
        Some(id) => Activation::Cancel {
            open_codex: cancel_asks_open_codex(uri),
            id,
        },
        None => Activation::Malformed,
    }
}
