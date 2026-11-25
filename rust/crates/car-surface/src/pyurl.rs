//! `urllib.parse.urlsplit` and `parse_qs` as CPython 3.13 (the reference interpreter) has them, for the four readers
//! of a notice's URIs (`notice_uris`). Every rule that can change what a reader answers is kept: the leading C0
//! characters and spaces dropped, tabs and line breaks removed anywhere, the scheme's characters, the authority split
//! at the first `/`, `?` or `#`, the bracket and IPv6 checks and the NFKC check of a non-ASCII authority (each a
//! ValueError, which the readers answer None for), the query's `&` fields, `+` as a space and `%XX` decoded as
//! UTF-8 with U+FFFD for what does not decode, one ASCII run at a time.

use indexmap::IndexMap;

/// `SplitResult`: scheme, netloc, path, query, fragment.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Split {
    pub scheme: String,
    pub netloc: String,
    pub path: String,
    pub query: String,
    pub fragment: String,
}

const SCHEME_CHARS: &str = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+-.";

/// The code points (past ASCII) whose NFKC form holds one of `/?#@:` - read from the reference interpreter's
/// `unicodedata` 15.1.0 (`tests/rustdiff/diffs_surface_uris.py` holds the list to it). `_checknetloc` refuses an
/// authority with one of them, and only them: the authority never holds `/?#` and the check takes out `@:#?` first.
pub const NFKC_DELIMITERS: &[u32] = &[
    0x2047, 0x2048, 0x2049, 0x2100, 0x2101, 0x2105, 0x2106, 0x2A74, 0xFE13, 0xFE16, 0xFE55, 0xFE56,
    0xFE5F, 0xFE6B, 0xFF03, 0xFF0F, 0xFF1A, 0xFF1F, 0xFF20,
];

/// `urlsplit(url)`: the parts, or `Err` where urlsplit raises ValueError.
pub fn urlsplit(url: &str) -> Result<Split, &'static str> {
    let url = url.trim_start_matches(|c: char| (c as u32) <= 0x20);
    let mut url: String = url
        .chars()
        .filter(|c| !matches!(c, '\t' | '\r' | '\n'))
        .collect();
    let mut scheme = String::new();
    if let Some(i) = url.find(':')
        && i > 0
        && url.as_bytes()[0].is_ascii_alphabetic()
        && url[..i].chars().all(|c| SCHEME_CHARS.contains(c))
    {
        scheme = url[..i].to_ascii_lowercase();
        url = url[i + 1..].to_owned();
    }
    let mut netloc = String::new();
    if url.starts_with("//") {
        let delimiter = ['/', '?', '#']
            .iter()
            .filter_map(|c| url[2..].find(*c).map(|at| at + 2))
            .min()
            .unwrap_or(url.len());
        netloc = url[2..delimiter].to_owned();
        url = url[delimiter..].to_owned();
        let open = netloc.contains('[');
        let close = netloc.contains(']');
        if open != close {
            return Err("ValueError");
        }
        if open && close {
            check_bracketed_netloc(&netloc)?;
        }
    }
    let mut fragment = String::new();
    if let Some(at) = url.find('#') {
        fragment = url[at + 1..].to_owned();
        url.truncate(at);
    }
    let mut query = String::new();
    if let Some(at) = url.find('?') {
        query = url[at + 1..].to_owned();
        url.truncate(at);
    }
    check_netloc(&netloc)?;
    Ok(Split {
        scheme,
        netloc,
        path: url,
        query,
        fragment,
    })
}

fn check_netloc(netloc: &str) -> Result<(), &'static str> {
    if netloc.is_ascii() {
        return Ok(());
    }
    let refused = netloc
        .chars()
        .filter(|c| !matches!(c, '@' | ':' | '#' | '?'))
        .any(|c| NFKC_DELIMITERS.contains(&(c as u32)));
    if refused { Err("ValueError") } else { Ok(()) }
}

fn check_bracketed_netloc(netloc: &str) -> Result<(), &'static str> {
    let host_and_port = netloc.rsplit_once('@').map_or(netloc, |(_, after)| after);
    let hostname = match host_and_port.split_once('[') {
        Some((before, bracketed)) => {
            if !before.is_empty() {
                return Err("ValueError");
            }
            let (hostname, port) = bracketed.split_once(']').unwrap_or((bracketed, ""));
            if !port.is_empty() && !port.starts_with(':') {
                return Err("ValueError");
            }
            hostname
        }
        None => host_and_port
            .split_once(':')
            .map_or(host_and_port, |(host, _)| host),
    };
    check_bracketed_host(hostname)
}

fn check_bracketed_host(hostname: &str) -> Result<(), &'static str> {
    if hostname.starts_with(['v', 'V']) {
        // `\A[vV][a-fA-F0-9]+\..+\Z`, where `.` is anything but a line feed (none is left by now).
        let rest = &hostname[1..];
        let digits = rest.chars().take_while(char::is_ascii_hexdigit).count();
        let after = &rest[digits..];
        let ok = digits > 0
            && after.starts_with('.')
            && !after[1..].is_empty()
            && !after[1..].contains('\n');
        return if ok { Ok(()) } else { Err("ValueError") };
    }
    if ipv4(hostname).is_some() {
        return Err("ValueError");
    }
    if ipv6(hostname) {
        Ok(())
    } else {
        Err("ValueError")
    }
}

/// `IPv4Address(text)`: its value, or None where it raises AddressValueError.
fn ipv4(text: &str) -> Option<u32> {
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

/// `IPv6Address(text)` succeeds.
fn ipv6(text: &str) -> bool {
    if text.contains('/') {
        return false;
    }
    let address = match text.split_once('%') {
        Some((address, scope)) => {
            if scope.is_empty() || scope.contains('%') {
                return false;
            }
            address
        }
        None => text,
    };
    if address.is_empty() || address.chars().count() > 45 {
        return false;
    }
    const HEXTETS: usize = 8;
    let most = HEXTETS + 1;
    // `split(':', maxsplit=9)`: at most ten parts, the last one keeping its colons.
    let mut parts: Vec<String> = Vec::new();
    let mut rest = address;
    while parts.len() < most {
        match rest.split_once(':') {
            Some((part, after)) => {
                parts.push(part.to_owned());
                rest = after;
            }
            None => break,
        }
    }
    parts.push(rest.to_owned());
    if parts.len() < 3 {
        return false;
    }
    if parts.last().is_some_and(|last| last.contains('.')) {
        let Some(tail) = parts.pop().as_deref().and_then(ipv4) else {
            return false;
        };
        parts.push(format!("{:x}", (tail >> 16) & 0xFFFF));
        parts.push(format!("{:x}", tail & 0xFFFF));
    }
    if parts.len() > most {
        return false;
    }
    let mut skip = None;
    for (i, part) in parts.iter().enumerate().take(parts.len() - 1).skip(1) {
        if part.is_empty() {
            if skip.is_some() {
                return false;
            }
            skip = Some(i);
        }
    }
    let (high, low) = match skip {
        Some(at) => {
            let mut high = at;
            let mut low = parts.len() - at - 1;
            if parts[0].is_empty() {
                high -= 1;
                if high > 0 {
                    return false;
                }
            }
            if parts[parts.len() - 1].is_empty() {
                low -= 1;
                if low > 0 {
                    return false;
                }
            }
            if HEXTETS < high + low + 1 {
                return false;
            }
            (high, low)
        }
        None => {
            if parts.len() != HEXTETS || parts[0].is_empty() || parts[HEXTETS - 1].is_empty() {
                return false;
            }
            (parts.len(), 0)
        }
    };
    let hextet = |part: &str| {
        !part.is_empty() && part.len() <= 4 && part.bytes().all(|b| b.is_ascii_hexdigit())
    };
    parts[..high].iter().all(|part| hextet(part))
        && parts[parts.len() - low..].iter().all(|part| hextet(part))
}

/// `unquote_plus(text)`: `+` as a space, then every `%XX` decoded, one ASCII run at a time, as UTF-8 with U+FFFD.
pub fn unquote_plus(text: &str) -> String {
    let text = text.replace('+', " ");
    if !text.contains('%') {
        return text;
    }
    let mut out = String::new();
    let mut run = String::new();
    for c in text.chars() {
        if c.is_ascii() {
            run.push(c);
        } else {
            if !run.is_empty() {
                out.push_str(&unquote_run(&run));
                run.clear();
            }
            out.push(c);
        }
    }
    if !run.is_empty() {
        out.push_str(&unquote_run(&run));
    }
    out
}

fn unquote_run(run: &str) -> String {
    let bytes = run.as_bytes();
    let mut bits = bytes.split(|b| *b == b'%');
    let mut found: Vec<u8> = bits.next().unwrap_or_default().to_vec();
    for item in bits {
        if item.len() >= 2 && item[0].is_ascii_hexdigit() && item[1].is_ascii_hexdigit() {
            let high = (item[0] as char).to_digit(16).unwrap_or(0) as u8;
            let low = (item[1] as char).to_digit(16).unwrap_or(0) as u8;
            found.push(high * 16 + low);
            found.extend_from_slice(&item[2..]);
        } else {
            found.push(b'%');
            found.extend_from_slice(item);
        }
    }
    String::from_utf8_lossy(&found).into_owned()
}

/// `parse_qs(query, keep_blank_values)`: each name's values in the order given, names in the order first seen.
pub fn parse_qs(query: &str, keep_blank: bool) -> IndexMap<String, Vec<String>> {
    let mut parsed: IndexMap<String, Vec<String>> = IndexMap::new();
    if query.is_empty() {
        return parsed;
    }
    for field in query.split('&') {
        if field.is_empty() {
            continue;
        }
        let (name, value) = field.split_once('=').unwrap_or((field, ""));
        if !value.is_empty() || keep_blank {
            parsed
                .entry(unquote_plus(name))
                .or_default()
                .push(unquote_plus(value));
        }
    }
    parsed
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn splits_as_cpython() {
        let found = urlsplit(" codex-auto-resume:cancel?i=ab#x").unwrap();
        assert_eq!(found.scheme, "codex-auto-resume");
        assert_eq!(found.path, "cancel");
        assert_eq!(found.query, "i=ab");
        assert_eq!(found.fragment, "x");
        let found = urlsplit("Codex-Auto-Resume://open/?page=history").unwrap();
        assert_eq!(found.netloc, "open");
        assert_eq!(found.path, "/");
        assert!(urlsplit("x://[::1/").is_err());
        assert!(urlsplit("x://[::1]/a").is_ok());
        assert!(urlsplit("x://[1.2.3.4]/a").is_err());
        assert!(urlsplit("x://a\u{2100}b/c").is_err());
    }

    #[test]
    fn queries() {
        let found = parse_qs("i=a+b&i=%41&j=&k", false);
        assert_eq!(found["i"], vec!["a b", "A"]);
        assert!(!found.contains_key("j"));
        let blank = parse_qs("j=&k", true);
        assert_eq!(blank["j"], vec![""]);
        assert_eq!(blank["k"], vec![""]);
        assert_eq!(unquote_plus("%e2%82"), "\u{fffd}");
    }
}
