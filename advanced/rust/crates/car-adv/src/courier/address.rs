//! `courier/address.py` (seat S7.3b): what an address a person types must be before the courier keeps it or sends to it -
//! pure string checks, no network.
//!
//! A push goes only to an `https` address of a named host: never `http`, never a user name or password in the address,
//! never an IP literal and never a loopback name (`localhost`, `*.localhost`), and never one longer than [`MAX_URL`].
//! Every refusal is one closed word ([`AddressRefused::word`]), never the address. The e-mail server's host is held to
//! the same host rules; its addresses and its user to shapes that cannot carry a line break.
//!
//! The reference parses with `urllib.parse.urlsplit` and `ipaddress.ip_address`; [`split`] and [`ip`] are those two,
//! as far as these checks read them (the bundled 3.14.10's rules: the bracketed host's check, the NFKC netloc check
//! over the 19 code points whose compatibility form holds a delimiter, IPv6's 45-character limit and scope id).

#![allow(clippy::result_unit_err)]

use car_machine::json::Value;

use crate::jsonx::object;

pub const MAX_URL: usize = 2048;
pub const MAX_TOKEN: usize = 512;
pub const SMTP_PORTS: [i64; 2] = [465, 587];

/// `AddressRefused(word)`: an address that may not be kept or used; `word` says why.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AddressRefused {
    pub word: &'static str,
}

fn refused(word: &'static str) -> AddressRefused {
    AddressRefused { word }
}

/// `web_view(port, token=None, host=None)`: the loopback web view's address.
pub fn web_view(port: i64, token: Option<&str>, host: Option<&str>) -> String {
    let made = format!(
        "http://{}:{}/",
        host.filter(|host| !host.is_empty()).unwrap_or("127.0.0.1"),
        port
    );
    match token {
        Some(token) if !token.is_empty() => format!("{made}#{token}"),
        _ => made,
    }
}

// ------------------------------------------------------------------------------------------ the shapes
/// `_LABEL.match(label)`: `(?!-)[A-Za-z0-9-]{1,63}(?<!-)\Z`.
fn label(text: &str) -> bool {
    let bytes = text.as_bytes();
    !bytes.is_empty()
        && bytes.len() <= 63
        && bytes
            .iter()
            .all(|b| b.is_ascii_alphanumeric() || *b == b'-')
        && bytes[0] != b'-'
        && bytes[bytes.len() - 1] != b'-'
}

/// `TELEGRAM_TOKEN`: `[0-9]{1,20}:[A-Za-z0-9_-]{20,100}\Z`.
pub fn telegram_token(text: &str) -> bool {
    let Some((digits, rest)) = text.split_once(':') else {
        return false;
    };
    (1..=20).contains(&digits.len())
        && digits.bytes().all(|b| b.is_ascii_digit())
        && (20..=100).contains(&rest.len())
        && rest
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
}

/// `TELEGRAM_CHAT`: `-?[0-9]{1,20}\Z`.
pub fn telegram_chat(text: &str) -> bool {
    let digits = text.strip_prefix('-').unwrap_or(text);
    (1..=20).contains(&digits.len()) && digits.bytes().all(|b| b.is_ascii_digit())
}

/// `_PRINTABLE`: `[!-~]{1,512}\Z`.
fn printable(text: &str) -> bool {
    (1..=MAX_TOKEN).contains(&text.len()) && text.bytes().all(|b| (b'!'..=b'~').contains(&b))
}

/// `_MAILBOX`: `[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@[A-Za-z0-9.-]{3,253}\Z`.
fn mailbox(text: &str) -> bool {
    let Some((local, domain)) = text.split_once('@') else {
        return false;
    };
    (1..=64).contains(&local.len())
        && local
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b".!#$%&'*+/=?^_`{|}~-".contains(&b))
        && (3..=253).contains(&domain.len())
        && domain
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'.' || b == b'-')
}

/// Which shape a token is held to (`shape=`).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Shape {
    Printable,
    TelegramToken,
    TelegramChat,
}

/// `shape.match(text)` for a text.
pub fn fits(text: &str, shape: Shape) -> bool {
    match shape {
        Shape::Printable => printable(text),
        Shape::TelegramToken => telegram_token(text),
        Shape::TelegramChat => telegram_chat(text),
    }
}

// ------------------------------------------------------------------------------------------ the checks
/// `host_problem(host)`: why `host` may not be pushed to, or None (None is "host": not a name).
pub fn host_problem(host: Option<&str>) -> Option<&'static str> {
    match host {
        Some(host) => host_problem_of(host),
        None => Some("host"),
    }
}

fn host_problem_of(host: &str) -> Option<&'static str> {
    if host.is_empty() || host.chars().count() > 253 {
        return Some("host");
    }
    let name = host.trim_end_matches('.').to_lowercase();
    if ip(name.trim_matches(|c| c == '[' || c == ']')).is_some() {
        return Some("ip_literal");
    }
    if name == "localhost" || name.ends_with(".localhost") {
        return Some("loopback");
    }
    let labels: Vec<&str> = name.split('.').collect();
    if labels.len() < 2 || !labels.iter().all(|each| label(each)) {
        return Some("host");
    }
    None
}

/// `host_problem(value)` for any value: a non-text is "host".
pub fn host_problem_value(host: &Value) -> Option<&'static str> {
    match text_of(host) {
        Some(host) => host_problem_of(&host),
        None => Some("host"),
    }
}

/// A Python `str` as Rust text: a lone surrogate (which no check passes as a host or a shape) as U+FFFD.
pub fn text_of(value: &Value) -> Option<String> {
    match value {
        Value::Str(text) => Some(match text.as_str() {
            Some(text) => text.to_owned(),
            None => text
                .code_points()
                .map(|point| char::from_u32(point).unwrap_or('\u{FFFD}'))
                .collect(),
        }),
        _ => None,
    }
}

/// `checked_url(url)`: `url` where a push may go, as it was given.
pub fn checked_url(url: &Value) -> Result<String, AddressRefused> {
    let Some(text) = text_of(url) else {
        return Err(refused("url"));
    };
    checked_url_text(&text)
}

/// `checked_url(url)` for a text.
pub fn checked_url_text(text: &str) -> Result<String, AddressRefused> {
    if text.is_empty()
        || text.chars().count() > MAX_URL
        || text.chars().any(|c| (c as u32) < 33 || c as u32 == 127)
    {
        return Err(refused("url"));
    }
    let Ok(parts) = split(text) else {
        return Err(refused("url"));
    };
    let Ok(port) = parts.port() else {
        return Err(refused("url"));
    };
    if parts.scheme.to_lowercase() != "https" {
        return Err(refused("not_https"));
    }
    if parts.netloc.contains('@') {
        return Err(refused("userinfo"));
    }
    if let Some(problem) = host_problem(parts.hostname().as_deref()) {
        return Err(refused(problem));
    }
    if let Some(port) = port
        && !(1..=65535).contains(&port)
    {
        return Err(refused("url"));
    }
    Ok(text.to_owned())
}

/// `checked_token(token, shape=...)`.
pub fn checked_token(token: &Value, shape: Shape) -> Result<String, AddressRefused> {
    match text_of(token) {
        Some(text) if fits(&text, shape) => Ok(text),
        _ => Err(refused("token")),
    }
}

/// `checked_mailbox(address)`.
pub fn checked_mailbox(address: &Value) -> Result<String, AddressRefused> {
    let Some(text) = text_of(address) else {
        return Err(refused("mailbox"));
    };
    let host = text.rsplit_once('@').map_or("", |(_, host)| host);
    if !mailbox(&text) || host_problem_of(host).is_some() {
        return Err(refused("mailbox"));
    }
    Ok(text)
}

/// `checked_smtp(blob)`: the e-mail channel's settings, each checked; the object a courier keeps as one secret.
pub fn checked_smtp(blob: &Value) -> Result<Value, AddressRefused> {
    let Value::Object(blob) = blob else {
        return Err(refused("smtp"));
    };
    const KEYS: [&str; 6] = ["host", "port", "user", "password", "from", "to"];
    if blob.len() != KEYS.len() || !KEYS.iter().all(|key| blob.get(*key).is_some()) {
        return Err(refused("smtp"));
    }
    let get = |key: &str| blob.get(key).cloned().unwrap_or(Value::Null);
    if let Some(problem) = host_problem_value(&get("host")) {
        return Err(refused(problem));
    }
    let port = match get("port") {
        Value::Int(port) => port.as_i64().filter(|port| SMTP_PORTS.contains(port)),
        _ => None,
    };
    let Some(port) = port else {
        return Err(refused("port"));
    };
    let user = checked_token(&get("user"), Shape::Printable)?;
    let password = checked_token(&get("password"), Shape::Printable)?;
    let from = checked_mailbox(&get("from"))?;
    let to = checked_mailbox(&get("to"))?;
    Ok(object([
        ("host", get("host")),
        ("port", Value::from(port)),
        ("user", Value::from(user)),
        ("password", Value::from(password)),
        ("from", Value::from(from)),
        ("to", Value::from(to)),
    ]))
}

// ------------------------------------------------------------------------------------------ urlsplit
/// What `urlsplit` gives that these checks read.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Split {
    pub scheme: String,
    pub netloc: String,
    pub path: String,
    pub query: String,
    pub fragment: String,
}

/// Code points whose NFKC form holds one of `/?#@:` (Unicode 16, the bundled 3.14.10's `unicodedata`).
const NFKC_DELIMITERS: [u32; 19] = [
    0x2047, 0x2048, 0x2049, 0x2100, 0x2101, 0x2105, 0x2106, 0x2A74, 0xFE13, 0xFE16, 0xFE55, 0xFE56,
    0xFE5F, 0xFE6B, 0xFF03, 0xFF0F, 0xFF1A, 0xFF1F, 0xFF20,
];

const SCHEME_CHARS: &str = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+-.";

/// `urllib.parse.urlsplit(url)` (no default scheme, fragments allowed); `Err` where it raises ValueError.
pub fn split(url: &str) -> Result<Split, ()> {
    // lstrip of C0 controls and space, then every tab, CR and LF removed.
    let url: String = url
        .trim_start_matches(|c: char| (c as u32) <= 0x20)
        .chars()
        .filter(|c| !matches!(c, '\t' | '\r' | '\n'))
        .collect();
    let mut scheme = String::new();
    let mut rest: &str = &url;
    if let Some(i) = url.find(':')
        && i > 0
    {
        let first = url.chars().next().unwrap_or(' ');
        if first.is_ascii_alphabetic() && url[..i].chars().all(|c| SCHEME_CHARS.contains(c)) {
            scheme = url[..i].to_lowercase();
            rest = &url[i + 1..];
        }
    }
    let mut netloc = String::new();
    if let Some(after) = rest.strip_prefix("//") {
        let end = after.find(['/', '?', '#']).unwrap_or(after.len());
        netloc = after[..end].to_owned();
        rest = &after[end..];
        let (open, close) = (netloc.contains('['), netloc.contains(']'));
        if open != close {
            return Err(());
        }
        if open && close {
            check_bracketed_netloc(&netloc)?;
        }
    }
    let (rest, fragment) = match rest.split_once('#') {
        Some((before, after)) => (before, after.to_owned()),
        None => (rest, String::new()),
    };
    let (path, query) = match rest.split_once('?') {
        Some((before, after)) => (before.to_owned(), after.to_owned()),
        None => (rest.to_owned(), String::new()),
    };
    if !netloc.is_ascii() {
        let stripped = netloc.replace(['@', ':', '#', '?'], "");
        if stripped
            .chars()
            .any(|c| NFKC_DELIMITERS.contains(&(c as u32)))
        {
            return Err(());
        }
    }
    Ok(Split {
        scheme,
        netloc,
        path,
        query,
        fragment,
    })
}

/// `_check_bracketed_netloc(netloc)` (3.14): nothing before the bracket, nothing after it but a port.
fn check_bracketed_netloc(netloc: &str) -> Result<(), ()> {
    let host_and_port = netloc.rsplit_once('@').map_or(netloc, |(_, after)| after);
    let hostname = match host_and_port.split_once('[') {
        Some((before, bracketed)) => {
            if !before.is_empty() {
                return Err(());
            }
            let (hostname, port) = bracketed.split_once(']').unwrap_or((bracketed, ""));
            if !port.is_empty() && !port.starts_with(':') {
                return Err(());
            }
            hostname
        }
        None => host_and_port
            .split_once(':')
            .map_or(host_and_port, |(host, _)| host),
    };
    check_bracketed(hostname)
}

/// `_check_bracketed_host(hostname)`.
fn check_bracketed(host: &str) -> Result<(), ()> {
    if let Some(rest) = host.strip_prefix('v') {
        // `\Av[a-fA-F0-9]+\..+\z`: hex digits, a dot, then anything but a newline (urlsplit removed them).
        let hex_end = rest
            .find(|c: char| !c.is_ascii_hexdigit())
            .unwrap_or(rest.len());
        let after = &rest[hex_end..];
        let good = hex_end > 0 && after.starts_with('.') && after.len() > 1;
        return if good { Ok(()) } else { Err(()) };
    }
    match ip(host) {
        Some(Ip::V6 { .. }) => Ok(()),
        _ => Err(()),
    }
}

impl Split {
    /// `_hostinfo`: (hostname, port) as written.
    fn hostinfo(&self) -> (String, Option<String>) {
        let info = self
            .netloc
            .rsplit_once('@')
            .map_or(self.netloc.as_str(), |(_, info)| info);
        let (hostname, port) = match info.split_once('[') {
            Some((_, bracketed)) => {
                let (host, after) = bracketed.split_once(']').unwrap_or((bracketed, ""));
                (host, after.split_once(':').map_or("", |(_, port)| port))
            }
            None => info.split_once(':').unwrap_or((info, "")),
        };
        let port = if port.is_empty() {
            None
        } else {
            Some(port.to_owned())
        };
        (hostname.to_owned(), port)
    }

    /// `.hostname`: lower case but for an IPv6 zone, or None for an empty one.
    pub fn hostname(&self) -> Option<String> {
        let (hostname, _) = self.hostinfo();
        if hostname.is_empty() {
            return None;
        }
        Some(match hostname.split_once('%') {
            Some((host, zone)) => format!("{}%{}", host.to_lowercase(), zone),
            None => hostname.to_lowercase(),
        })
    }

    /// `.port`: the number, None, or `Err` where it raises ValueError.
    pub fn port(&self) -> Result<Option<i64>, ()> {
        let (_, port) = self.hostinfo();
        let Some(port) = port else {
            return Ok(None);
        };
        // `port.isdigit() and port.isascii()`, then `int`, then 0-65535.
        if !port.bytes().all(|b| b.is_ascii_digit()) {
            return Err(());
        }
        let trimmed = port.trim_start_matches('0');
        if trimmed.len() > 5 {
            return Err(());
        }
        let value: u32 = if trimmed.is_empty() {
            0
        } else {
            trimmed.parse().map_err(|_| ())?
        };
        if value > 65535 {
            return Err(());
        }
        Ok(Some(i64::from(value)))
    }
}

// ------------------------------------------------------------------------------------------ ipaddress
/// What `ipaddress.ip_address(text)` makes of a text.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Ip {
    V4(u32),
    V6 { value: u128, scoped: bool },
}

/// `IPv4Address(text)`'s parse.
pub fn ipv4(text: &str) -> Option<u32> {
    if text.is_empty() || text.contains('/') {
        return None;
    }
    let octets: Vec<&str> = text.split('.').collect();
    if octets.len() != 4 {
        return None;
    }
    let mut value: u32 = 0;
    for octet in octets {
        if octet.is_empty() || !octet.bytes().all(|b| b.is_ascii_digit()) || octet.len() > 3 {
            return None;
        }
        if octet != "0" && octet.starts_with('0') {
            return None;
        }
        let number: u32 = octet.parse().ok()?;
        if number > 255 {
            return None;
        }
        value = (value << 8) | number;
    }
    Some(value)
}

/// `IPv6Address(text)`'s parse: the value and whether it had a scope id.
pub fn ipv6(text: &str) -> Option<(u128, bool)> {
    if text.contains('/') {
        return None;
    }
    let (address, scoped) = match text.split_once('%') {
        Some((address, scope)) => {
            if scope.is_empty() || scope.contains('%') {
                return None;
            }
            (address, true)
        }
        None => (text, false),
    };
    if address.is_empty() || address.chars().count() > 45 {
        return None;
    }
    let mut parts: Vec<String> = address.split(':').map(str::to_owned).collect();
    if parts.len() < 3 {
        return None;
    }
    if parts.last().is_some_and(|last| last.contains('.')) {
        let last = parts.pop().unwrap_or_default();
        let four = ipv4(&last)?;
        parts.push(format!("{:x}", (four >> 16) & 0xFFFF));
        parts.push(format!("{:x}", four & 0xFFFF));
    }
    if parts.len() > 9 {
        return None;
    }
    let mut skip = None;
    for (index, part) in parts.iter().enumerate().take(parts.len() - 1).skip(1) {
        if part.is_empty() {
            if skip.is_some() {
                return None;
            }
            skip = Some(index);
        }
    }
    let (high, low, skipped) = match skip {
        Some(index) => {
            let mut high = index;
            let mut low = parts.len() - index - 1;
            if parts[0].is_empty() {
                high -= 1;
                if high != 0 {
                    return None;
                }
            }
            if parts[parts.len() - 1].is_empty() {
                low -= 1;
                if low != 0 {
                    return None;
                }
            }
            let skipped = 8_i64 - (high + low) as i64;
            if skipped < 1 {
                return None;
            }
            (high, low, skipped as u32)
        }
        None => {
            if parts.len() != 8 || parts[0].is_empty() || parts[7].is_empty() {
                return None;
            }
            (parts.len(), 0, 0)
        }
    };
    let hextet = |part: &str| -> Option<u128> {
        if !part.bytes().all(|b| b.is_ascii_hexdigit()) || part.len() > 4 {
            return None;
        }
        // An empty hextet (at an end, beside "::") is int('', 16): ValueError.
        u128::from_str_radix(part, 16).ok()
    };
    let mut value: u128 = 0;
    for part in &parts[..high] {
        value = (value << 16) | hextet(part)?;
    }
    value = value.checked_shl(16 * skipped).unwrap_or(0);
    for part in &parts[parts.len() - low..] {
        value = (value << 16) | hextet(part)?;
    }
    Some((value, scoped))
}

/// `ipaddress.ip_address(text)`: an IPv4 or IPv6 address, or None where it raises ValueError.
pub fn ip(text: &str) -> Option<Ip> {
    if let Some(value) = ipv4(text) {
        return Some(Ip::V4(value));
    }
    ipv6(text).map(|(value, scoped)| Ip::V6 { value, scoped })
}

/// `str(IPv4Address(value))`.
pub fn ipv4_text(value: u32) -> String {
    let b = value.to_be_bytes();
    format!("{}.{}.{}.{}", b[0], b[1], b[2], b[3])
}

#[cfg(test)]
mod tests {
    use super::*;

    fn url(text: &str) -> Result<String, &'static str> {
        checked_url(&Value::from(text)).map_err(|refusal| refusal.word)
    }

    #[test]
    fn a_push_goes_to_a_named_https_host_alone() {
        assert_eq!(
            url("https://ntfy.example.org/topic"),
            Ok("https://ntfy.example.org/topic".into())
        );
        assert_eq!(url("http://ntfy.example.org/"), Err("not_https"));
        assert_eq!(url("https://user@example.org/"), Err("userinfo"));
        assert_eq!(url("https://127.0.0.1/"), Err("ip_literal"));
        assert_eq!(url("https://[::1]/"), Err("ip_literal"));
        assert_eq!(url("https://a.localhost/"), Err("loopback"));
        assert_eq!(url("https://intranet/"), Err("host"));
        assert_eq!(url("https://example.org:0/"), Err("url"));
        assert_eq!(url("https://example.org:x/"), Err("url"));
        assert_eq!(url("https://exa\u{FF0F}mple.org/"), Err("url"));
    }

    #[test]
    fn ip_literals_are_ipaddress_s() {
        assert_eq!(ip("1.2.3.4"), Some(Ip::V4(0x01020304)));
        assert_eq!(ip("01.2.3.4"), None);
        assert!(ip("::ffff:1.2.3.4").is_some());
        assert!(ip("fe80::1%eth0").is_some());
        assert_eq!(ip("1::2::3"), None);
        assert_eq!(ip("1:2:3:4:5:6:7:8:9"), None);
    }
}
