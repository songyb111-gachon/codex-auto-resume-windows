//! `courier/http.py` (seat S7.3b): the courier's one way to an HTTPS service - [`request`], and [`post`] and [`get`]
//! on top of it.
//!
//! Every request is checked first (`address::checked_url`: https only, no user name or password, no IP literal and no
//! loopback name); a body is at most [`MAX_BODY`] bytes; a reply is read up to `most` bytes and no further. A request
//! that fails says how in one closed word - its status class ([`STATUS_CLASSES`]) - and never the address, the body or
//! what the service answered. No redirect is followed: a 3xx is a refusal.
//!
//! [`Opener`] is urllib's opener as the reference's seam has it (`opener.open(request, timeout=)`): it is handed the
//! request exactly as urllib's `Request` holds it before it is sent - the address without its fragment, the method, the
//! headers capitalised as `Request.add_header` keeps them, the body and the timeout - and answers what the reply was
//! (its status and the bytes read, or how it failed, and whether the request's time in all ran out). The production
//! opener is WinHTTP's ([`SystemOpener`], car-platform `winhttp`: the system's TLS, the certificate store, TLS 1.2 or
//! later, no redirect, each read's timeout and the time in all, `WHOLE_MORE`); every test hands its own.
//!
//! Not ported: `stream`, whose one caller (`courier/pythonorg.py`) is retired with the Python picker (D8).

use crate::courier::address::{self, AddressRefused};

pub const TIMEOUT: i64 = 10;
/// Seconds a request may take in all beyond its timeout.
pub const WHOLE_MORE: i64 = 10;
pub const MAX_BODY: usize = 4096;
pub const MAX_REPLY: usize = 65536;
pub const STATUS_CLASSES: [&str; 5] = ["2xx", "4xx", "5xx", "timeout", "tls"];
pub const USER_AGENT: &str = "codex-auto-resume-advanced-courier";

/// One request as urllib's `Request` holds it when the opener is handed it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Request {
    /// `full_url`: the address, its fragment (after the last `#`) taken off.
    pub url: String,
    pub method: String,
    /// `header_items()`: each name capitalised (`"Content-type"`), in the order they were first given.
    pub headers: Vec<(String, String)>,
    pub body: Option<Vec<u8>>,
    pub timeout: i64,
}

/// How an opener's call failed, as urllib raises it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Fault {
    /// `HTTPError` (the reply's status, None where it is not a number): a 3xx, 4xx or 5xx.
    Status(Option<i64>),
    /// `ssl.SSLError` / `CertificateError`, or a `URLError` whose reason is one.
    Tls,
    /// `URLError` of any other reason, `socket.timeout`, `OSError`, `http.client.HTTPException`.
    Timeout,
    /// Any other exception, by its class (`ValueError` among them): it goes on up.
    Raised(String),
}

/// What an opener answered.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Answer {
    /// `reply.status`, None where it has none that is a number (read as 200).
    pub status: Option<i64>,
    /// `reply.read(most)`: the bytes, or how the read failed.
    pub body: Result<Vec<u8>, Fault>,
    /// The request's time in all ran out (`_stop(reply)`): what was read may be cut.
    pub expired: bool,
}

/// urllib's opener: `opener.open(request, timeout=)`, then `read(most)`.
pub trait Opener: Send + Sync {
    fn open(&self, request: &Request, most: usize) -> Result<Answer, Fault>;
}

/// Why a request, a push or a pairing did not answer well, as the reference's exceptions say it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Failure {
    /// `http.Failed(word, status)`.
    Failed {
        word: &'static str,
        status: Option<i64>,
    },
    /// `keep.NotSaved`.
    NotSaved,
    /// `address.AddressRefused(word)` - a ValueError.
    Refused(&'static str),
    /// Any other exception, by class; `value_error` where it is one (`except ValueError` takes it).
    Raised { class: String, value_error: bool },
}

impl Failure {
    pub fn failed(word: &'static str, status: Option<i64>) -> Failure {
        Failure::Failed { word, status }
    }

    pub fn value_error(class: &str) -> Failure {
        Failure::Raised {
            class: class.to_owned(),
            value_error: true,
        }
    }

    /// An exception of `class` the reference raises (`ValueError`, `UnicodeDecodeError` and `JSONDecodeError` are
    /// ValueErrors).
    pub fn raised(class: &str) -> Failure {
        let value_error = matches!(
            class,
            "ValueError" | "UnicodeDecodeError" | "UnicodeEncodeError" | "JSONDecodeError"
        );
        Failure::Raised {
            class: class.to_owned(),
            value_error,
        }
    }

    /// `isinstance(exc, ValueError)`.
    pub fn is_value_error(&self) -> bool {
        matches!(
            self,
            Failure::Refused(_)
                | Failure::Raised {
                    value_error: true,
                    ..
                }
        )
    }

    /// The exception's class name.
    pub fn class(&self) -> String {
        match self {
            Failure::Failed { .. } => "Failed".to_owned(),
            Failure::NotSaved => "NotSaved".to_owned(),
            Failure::Refused(_) => "AddressRefused".to_owned(),
            Failure::Raised { class, .. } => class.clone(),
        }
    }

    /// The word a `Failed` or an `AddressRefused` carries.
    pub fn word(&self) -> Option<&'static str> {
        match self {
            Failure::Failed { word, .. } | Failure::Refused(word) => Some(word),
            _ => None,
        }
    }
}

impl From<AddressRefused> for Failure {
    fn from(refused: AddressRefused) -> Failure {
        Failure::Refused(refused.word)
    }
}

/// `_class(status)`.
pub fn class_of(status: i64) -> &'static str {
    if (200..300).contains(&status) {
        "2xx"
    } else if status >= 500 {
        "5xx"
    } else {
        "4xx"
    }
}

/// `str.capitalize()` of an ASCII header name.
fn capitalized(name: &str) -> String {
    let mut chars = name.chars();
    match chars.next() {
        Some(first) => first.to_uppercase().chain(chars.flat_map(char::to_lowercase)).collect(),
        None => String::new(),
    }
}

/// `urllib.request.Request(url, data=body, method=method, headers=dict(headers, **{"User-Agent": ...}))` as the
/// opener is handed it.
pub fn made(url: &str, body: Option<&[u8]>, headers: &[(&str, &str)], method: &str, timeout: i64) -> Request {
    let mut given: Vec<(String, String)> = Vec::new();
    let mut put = |name: &str, value: &str| {
        // dict(headers, **{"User-Agent": ...}): a later equal key keeps the first one's place.
        if let Some(found) = given.iter_mut().find(|(each, _)| each == name) {
            found.1 = value.to_owned();
        } else {
            given.push((name.to_owned(), value.to_owned()));
        }
    };
    for (name, value) in headers {
        put(name, value);
    }
    put("User-Agent", USER_AGENT);
    let mut capital: Vec<(String, String)> = Vec::new();
    for (name, value) in given {
        let name = capitalized(&name);
        if let Some(found) = capital.iter_mut().find(|(each, _)| *each == name) {
            found.1 = value;
        } else {
            capital.push((name, value));
        }
    }
    let full = url.rsplit_once('#').map_or(url, |(before, _)| before);
    Request {
        url: full.to_owned(),
        method: method.to_owned(),
        headers: capital,
        body: body.map(<[u8]>::to_vec),
        timeout,
    }
}

fn opened(
    url: &str,
    body: Option<&[u8]>,
    headers: &[(&str, &str)],
    method: &str,
    timeout: i64,
    opener: &dyn Opener,
    most: usize,
) -> Result<Answer, Failure> {
    address::checked_url_text(url)?;
    if body.is_some_and(|body| body.len() > MAX_BODY) {
        return Err(Failure::value_error("ValueError"));
    }
    match opener.open(&made(url, body, headers, method, timeout), most) {
        Ok(answer) => Ok(answer),
        Err(Fault::Status(code)) => {
            let status = code.unwrap_or(0);
            Err(Failure::failed(
                if status >= 500 { "5xx" } else { "4xx" },
                Some(status),
            ))
        }
        Err(Fault::Tls) => Err(Failure::failed("tls", None)),
        Err(Fault::Timeout) => Err(Failure::failed("timeout", None)),
        Err(Fault::Raised(class)) => Err(Failure::raised(&class)),
    }
}

/// `request(url, body, headers, method=, timeout=, opener=, most=)`: what the service answered, at most `most` bytes,
/// for a 2xx; Failed otherwise, and AddressRefused for an address no push may go to - before anything is sent.
pub fn request(
    url: &str,
    body: Option<&[u8]>,
    headers: &[(&str, &str)],
    method: &str,
    timeout: i64,
    opener: &dyn Opener,
    most: usize,
) -> Result<Vec<u8>, Failure> {
    let answer = opened(url, body, headers, method, timeout, opener, most)?;
    let status = answer.status.unwrap_or(200);
    if class_of(status) != "2xx" {
        return Err(Failure::failed(class_of(status), Some(status)));
    }
    match answer.body {
        Ok(read) => {
            if answer.expired {
                return Err(Failure::failed("timeout", None));
            }
            Ok(read)
        }
        Err(Fault::Raised(class)) => Err(Failure::raised(&class)),
        // A read that failed (a timeout, a reset, a cut reply) is "timeout", whatever urllib called it.
        Err(_) => Err(Failure::failed("timeout", None)),
    }
}

/// `post(url, body, headers, timeout=, opener=)`: "2xx", or Failed. What the service answered is read and dropped.
pub fn post(
    url: &str,
    body: &[u8],
    headers: &[(&str, &str)],
    timeout: i64,
    opener: &dyn Opener,
) -> Result<&'static str, Failure> {
    request(url, Some(body), headers, "POST", timeout, opener, MAX_REPLY)?;
    Ok("2xx")
}

/// `get(url, timeout=, opener=, headers=, most=)`: what it answered, at most `most` bytes; Failed otherwise.
pub fn get(url: &str, timeout: i64, opener: &dyn Opener, most: usize) -> Result<Vec<u8>, Failure> {
    request(url, None, &[], "GET", timeout, opener, most)
}

// ------------------------------------------------------------------------------------------ the system's opener
/// The production opener: WinHTTP (car-platform `winhttp`), HTTPS alone, verification on, no redirect, each read's
/// timeout and the time in all (`timeout + WHOLE_MORE`). Made only by the courier's entry point; no test reaches it
/// but over a loopback server of its own (`plain` set, which an https address never asks for).
pub struct SystemOpener {
    /// Plain HTTP (a loopback test's server): never set by the courier, whose addresses are https alone.
    pub plain: bool,
}

impl Opener for SystemOpener {
    fn open(&self, request: &Request, most: usize) -> Result<Answer, Fault> {
        use car_platform::winhttp;
        let headers: Vec<(&str, &str)> = request
            .headers
            .iter()
            .map(|(name, value)| (name.as_str(), value.as_str()))
            .collect();
        let asked = winhttp::Asked {
            url: &request.url,
            method: &request.method,
            headers: &headers,
            body: request.body.as_deref(),
            timeout_ms: (request.timeout.max(0) as u32).saturating_mul(1000),
            whole_ms: ((request.timeout + WHOLE_MORE).max(0) as u32).saturating_mul(1000),
            most,
            secure: !self.plain,
        };
        match winhttp::send(&asked) {
            Ok(reply) => {
                if !(200..300).contains(&reply.status) {
                    // urllib's HTTPErrorProcessor: anything but a 2xx is an HTTPError (no redirect is followed).
                    return Err(Fault::Status(Some(i64::from(reply.status))));
                }
                Ok(Answer {
                    status: Some(i64::from(reply.status)),
                    body: match reply.body {
                        Ok(body) => Ok(body),
                        Err(_) => Err(Fault::Timeout),
                    },
                    expired: reply.expired,
                })
            }
            Err(winhttp::Error::Tls) => Err(Fault::Tls),
            Err(_) => Err(Fault::Timeout),
        }
    }
}
