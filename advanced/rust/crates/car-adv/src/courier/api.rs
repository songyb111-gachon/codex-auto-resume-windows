//! `courier/api.py` (seat S7.3b): the loopback API and web view (local_api) - the one listening socket of this product,
//! in the resident courier alone and only while local_api stands on.
//!
//! The owner's Q5 (a): a small HTTP/1.1 server on `std::net`, equal to the tag's `http.server` subclass for every request
//! the Gate can see. It binds 127.0.0.1 and the port chosen (every network only while local_api_lan stands on too).
//! Every route is in [`ROUTES`]. Each request, in this order: closed for five minutes to a client after LOCK_AFTER wrong
//! tokens from it in LOCK_WINDOW seconds (503); exactly one Host header naming this server (421); an unknown path 404,
//! a method a route does not take 405; every route but `/` needs `Authorization: Bearer <token>` (401, and only a token
//! offered and wrong counts towards the lock); an action while local_api_actions does not stand on 403; a body over
//! MAX_BODY 413. What `http.server` itself answers is kept as it writes it: the request line read as it reads it
//! (414 past 65,536 bytes, 400 for a bad version or syntax, 505 for HTTP/2, an HTTP/0.9 request answered with the body
//! alone), the headers as `http.client.parse_headers` and the e-mail parser take them (431 for a line too long or more
//! than 100), 501 for an unknown method, and `Server` and `Date` on every answer. Served by at most THREADS threads at a
//! time; each read waits TIMEOUT seconds, each request DEADLINE seconds in all, then LINGER_SECONDS more. Nothing is
//! logged.

#![allow(clippy::result_unit_err)]

use std::io::{BufRead, BufReader, Read, Write};
use std::net::{Shutdown, TcpListener, TcpStream};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex, mpsc};
use std::time::{Duration, Instant};

use car_machine::json::{Options, Value, to_string};
use car_platform::credman::Backend;

use crate::control::remote::{self as remote_layer, Failed, Layer};
use crate::courier::address::{self, Ip};
use crate::courier::main::SharedRuntime;
use crate::courier::resident::Served;
use crate::credentials::Secrets;
use crate::state::sql::string;
use crate::vocabulary::ArmingState;

pub const API: &str = "local_api";
pub const API_ACTIONS: &str = "local_api_actions";
pub const LOOPBACK: [u8; 4] = [127, 0, 0, 1];
pub const EVERYWHERE: [u8; 4] = [0, 0, 0, 0];
pub const MAX_BODY: i64 = 1024;
pub const THREADS: usize = 8;
pub const TIMEOUT: u64 = 10;
pub const DEADLINE: u64 = 10;
pub const LINGER_SECONDS: f64 = 1.0;
pub const LINGER_BYTES: usize = 64 * 1024;
pub const LOCK_AFTER: usize = 10;
pub const LOCK_WINDOW: f64 = 60.0;
pub const LOCK_SECONDS: f64 = 300.0;
pub const CLIENTS: usize = 256;
pub const LOOPBACK_CLIENT: &str = "loopback";
pub const JSON: &str = "application/json; charset=utf-8";
pub const SERVER_VERSION: &str = "codex-auto-resume";

/// `ROUTES`: every route, the method it takes and whether it changes anything.
pub const ROUTES: [(&str, &str, bool); 7] = [
    ("/", "GET", false),
    ("/status.json", "GET", false),
    ("/metrics", "GET", false),
    ("/pending", "GET", false),
    ("/pause", "POST", true),
    ("/resume-off", "POST", true),
    ("/cancel/", "POST", true),
];

const METHODS: [&str; 9] = [
    "GET", "POST", "HEAD", "PUT", "DELETE", "PATCH", "OPTIONS", "TRACE", "CONNECT",
];

/// `CANCEL.match(path)`: `/cancel/([1-9][0-9]{0,3})\Z`, the number.
pub fn cancel_number(path: &str) -> Option<&str> {
    let digits = path.strip_prefix("/cancel/")?;
    let good = (1..=4).contains(&digits.len())
        && digits.bytes().all(|b| b.is_ascii_digit())
        && !digits.starts_with('0');
    good.then_some(digits)
}

/// `route_of(path)`: the ROUTES key of `path` (its query string never read), or None.
pub fn route_of(path: &str) -> Option<&'static str> {
    let path = path.split('?').next().unwrap_or("");
    let path = path.split('#').next().unwrap_or("");
    if let Some((route, _, _)) = ROUTES
        .iter()
        .find(|(route, _, _)| *route == path && *route != "/cancel/")
    {
        return Some(route);
    }
    cancel_number(path).map(|_| "/cancel/")
}

/// `client_of(address)`: LOOPBACK_CLIENT for this PC's own loopback, else the address as written.
pub fn client_of(address_text: &str) -> String {
    match address::ip(address_text) {
        None => address_text.to_owned(),
        Some(Ip::V4(value)) => {
            if value >> 24 == 127 {
                LOOPBACK_CLIENT.to_owned()
            } else {
                address::ipv4_text(value)
            }
        }
        Some(Ip::V6 { value, scoped }) => {
            if value >> 32 == 0xffff && !scoped {
                let four = value as u32;
                return if four >> 24 == 127 {
                    LOOPBACK_CLIENT.to_owned()
                } else {
                    address::ipv4_text(four)
                };
            }
            if value == 1 {
                return LOOPBACK_CLIENT.to_owned();
            }
            std::net::Ipv6Addr::from(value).to_string()
        }
    }
}

/// `host_allowed(header, port, lan)`.
pub fn host_allowed(header: &str, port: i64, lan: bool) -> bool {
    let suffix = format!(":{port}");
    let Some(name) = header.strip_suffix(&suffix) else {
        return false;
    };
    let name = name.to_lowercase();
    if name == "127.0.0.1" || name == "localhost" {
        return true;
    }
    lan && address::ipv4(&name).is_some()
}

/// `Gate(clock)`: the wrong tokens counted for each client, closed for LOCK_SECONDS after LOCK_AFTER in LOCK_WINDOW.
pub struct Gate {
    clock: Arc<dyn Fn() -> f64 + Send + Sync>,
    clients: Mutex<Vec<(String, Vec<f64>, f64)>>,
}

impl Gate {
    pub fn new(clock: Arc<dyn Fn() -> f64 + Send + Sync>) -> Gate {
        Gate {
            clock,
            clients: Mutex::new(Vec::new()),
        }
    }

    fn held(&self) -> std::sync::MutexGuard<'_, Vec<(String, Vec<f64>, f64)>> {
        self.clients
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }

    /// `closed(client)`.
    pub fn closed(&self, client: &str) -> bool {
        let now = (self.clock)();
        self.held()
            .iter()
            .any(|(each, _, until)| each == client && now < *until)
    }

    /// `wrong(client)`: one wrong token counted; whether that closed it to it.
    pub fn wrong(&self, client: &str) -> bool {
        let now = (self.clock)();
        let mut clients = self.held();
        let mut found = match clients.iter().position(|(each, _, _)| each == client) {
            Some(at) => clients.remove(at),
            None => (client.to_owned(), Vec::new(), 0.0),
        };
        found
            .1
            .retain(|at| 0.0 <= now - at && now - at < LOCK_WINDOW);
        found.1.push(now);
        let closing = found.1.len() >= LOCK_AFTER;
        if closing {
            found.1.clear();
            found.2 = now + LOCK_SECONDS;
        }
        clients.push(found);
        while clients.len() > CLIENTS {
            match clients
                .iter()
                .position(|(_, _, until)| now >= *until || until.is_nan())
            {
                Some(at) => {
                    clients.remove(at);
                }
                None => {
                    clients.remove(0);
                }
            }
        }
        closing
    }

    /// The clients kept, oldest first, each with its times and when it is closed until (a diff's look).
    pub fn kept(&self) -> Vec<(String, Vec<f64>, f64)> {
        self.held().clone()
    }
}

/// `Service(runtime, port, lan, layer=, secrets=, clock=)`: what a request is answered from.
pub struct Service {
    pub runtime: SharedRuntime,
    pub port: i64,
    pub lan: bool,
    pub layer: Arc<dyn Layer + Send + Sync>,
    pub backend: Arc<dyn Backend>,
    pub clock: Arc<dyn Fn() -> f64 + Send + Sync>,
    /// `page()`: the web view in the process's language (`page.render(CATALOGS.catalog(locale), locale)`).
    pub page: Arc<dyn Fn() -> Result<Vec<u8>, ()> + Send + Sync>,
}

impl Service {
    fn token(&self) -> Option<String> {
        let secrets = Secrets::new(self.runtime.registry(), self.backend.clone());
        secrets
            .read(API, &string(remote_layer::TOKEN))
            .ok()
            .flatten()
            .filter(|token| !token.is_empty())
    }

    fn actions_on(&self) -> bool {
        self.runtime
            .states()
            .is_ok_and(|states| states.get(API_ACTIONS) == Some(ArmingState::Armed))
    }

    fn counted(&self, capability: &str, code: &str) -> Result<(), Failed> {
        self.runtime
            .state()
            .counted(&string(capability), &string(code), &Value::Null)
            .map(|_| ())
            .map_err(|error| Failed::Raised(error.class().to_owned()))
    }
}

// ------------------------------------------------------------------------------------------ http.server's reading
/// `str.split()` of a latin-1 text: on runs of Python white space.
fn py_split(text: &str) -> Vec<&str> {
    text.split(car_machine::pytext::is_space)
        .filter(|part| !part.is_empty())
        .collect()
}

fn latin1(bytes: &[u8]) -> String {
    bytes.iter().map(|b| *b as char).collect()
}

/// The headers as `email.parser` (compat32) keeps them from `parse_headers`' text: (name, value) in order.
pub fn parse_header_block(text: &str) -> Vec<(String, String)> {
    // BufferedSubFile: lines split on CRLF, CR or LF, each keeping its end.
    let mut lines: Vec<&str> = Vec::new();
    let mut start = 0;
    let bytes = text.as_bytes();
    let mut at = 0;
    while at < bytes.len() {
        match bytes[at] {
            b'\r' => {
                let end = if bytes.get(at + 1) == Some(&b'\n') {
                    at + 2
                } else {
                    at + 1
                };
                lines.push(&text[start..end]);
                start = end;
                at = end;
            }
            b'\n' => {
                lines.push(&text[start..at + 1]);
                start = at + 1;
                at += 1;
            }
            _ => at += 1,
        }
    }
    if start < text.len() {
        lines.push(&text[start..]);
    }
    // headerRE: `^(From |[\041-\071\073-\176]*:|[\t ])`; the first line that is not one ends the headers.
    let matches = |line: &str| {
        if line.starts_with("From ") || line.starts_with(['\t', ' ']) {
            return true;
        }
        let name_end = line
            .find(|c: char| !((('\x21'..='\x39').contains(&c)) || (('\x3b'..='\x7e').contains(&c))))
            .unwrap_or(line.len());
        line[name_end..].starts_with(':')
    };
    let mut kept: Vec<&str> = Vec::new();
    for line in &lines {
        if !matches(line) {
            break;
        }
        kept.push(line);
    }
    let mut headers: Vec<(String, String)> = Vec::new();
    let mut last: Vec<&str> = Vec::new();
    let flush = |last: &mut Vec<&str>, headers: &mut Vec<(String, String)>| {
        if let Some(first) = last.first() {
            let (name, value) = first.split_once(':').unwrap_or((first, ""));
            let mut value = value.trim_start_matches([' ', '\t']).to_owned();
            for more in &last[1..] {
                value.push_str(more);
            }
            headers.push((
                name.to_owned(),
                value.trim_end_matches(['\r', '\n']).to_owned(),
            ));
        }
        last.clear();
    };
    let count = kept.len();
    for (number, line) in kept.into_iter().enumerate() {
        if line.starts_with([' ', '\t']) {
            if !last.is_empty() {
                last.push(line);
            }
            continue;
        }
        flush(&mut last, &mut headers);
        if line.starts_with("From ") {
            if number + 1 == count && number != 0 {
                break;
            }
            continue;
        }
        if line.starts_with(':') {
            continue;
        }
        last.push(line);
    }
    flush(&mut last, &mut headers);
    headers
}

fn header_get<'a>(headers: &'a [(String, String)], name: &str) -> Option<&'a str> {
    headers
        .iter()
        .find(|(each, _)| each.eq_ignore_ascii_case(name))
        .map(|(_, value)| value.as_str())
}

/// `HTTPStatus(code).phrase`.
pub fn phrase(code: u16) -> &'static str {
    match code {
        200 => "OK",
        400 => "Bad Request",
        401 => "Unauthorized",
        403 => "Forbidden",
        404 => "Not Found",
        405 => "Method Not Allowed",
        409 => "Conflict",
        413 => "Content Too Large",
        414 => "URI Too Long",
        421 => "Misdirected Request",
        431 => "Request Header Fields Too Large",
        501 => "Not Implemented",
        503 => "Service Unavailable",
        505 => "HTTP Version Not Supported",
        _ => "",
    }
}

/// `email.utils.formatdate(seconds, usegmt=True)`.
pub fn http_date(seconds: f64) -> String {
    let whole = seconds.floor() as i64;
    let days = whole.div_euclid(86400);
    let rest = whole.rem_euclid(86400);
    let (year, month, day) = civil(days);
    let weekday = ["Thu", "Fri", "Sat", "Sun", "Mon", "Tue", "Wed"][days.rem_euclid(7) as usize];
    let months = [
        "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    ];
    format!(
        "{weekday}, {day:02} {} {year:04} {:02}:{:02}:{:02} GMT",
        months[(month - 1) as usize],
        rest / 3600,
        rest % 3600 / 60,
        rest % 60
    )
}

/// Days since 1970-01-01 as (year, month, day).
fn civil(days: i64) -> (i64, i64, i64) {
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    (yoe + era * 400 + i64::from(month <= 2), month, day)
}

/// One answer, as `Handler._answer` writes it.
struct Answer {
    status: u16,
    body: Vec<u8>,
    kind: &'static str,
    extra: Vec<(&'static str, String)>,
}

fn refuse(status: u16, word: &str, extra: Vec<(&'static str, String)>) -> Answer {
    Answer {
        status,
        body: format!("{{\"error\":\"{word}\"}}").into_bytes(),
        kind: JSON,
        extra,
    }
}

fn json_answer(value: &Value) -> Result<Answer, Failed> {
    let text = to_string(value, &Options::new().separators(",", ":"))
        .map_err(|_| Failed::Raised("ValueError".into()))?;
    Ok(Answer {
        status: 200,
        body: text.into_bytes(),
        kind: JSON,
        extra: Vec::new(),
    })
}

fn written(answer: &Answer, version_0_9: bool, head: bool, now: f64) -> Vec<u8> {
    let mut out = Vec::new();
    if !version_0_9 {
        out.extend_from_slice(
            format!("HTTP/1.0 {} {}\r\n", answer.status, phrase(answer.status)).as_bytes(),
        );
        let mut header = |name: &str, value: &str| {
            out.extend_from_slice(name.as_bytes());
            out.extend_from_slice(b": ");
            out.extend(value.chars().map(|c| c as u32 as u8));
            out.extend_from_slice(b"\r\n");
        };
        header("Server", SERVER_VERSION);
        header("Date", &http_date(now));
        header("Content-Type", answer.kind);
        header("Content-Length", &answer.body.len().to_string());
        header("Cache-Control", "no-store");
        header("X-Content-Type-Options", "nosniff");
        header("Referrer-Policy", "no-referrer");
        for (name, value) in &answer.extra {
            header(name, value);
        }
        out.extend_from_slice(b"\r\n");
    }
    if !head {
        out.extend_from_slice(&answer.body);
    }
    out
}

/// The request as `parse_request` leaves it, or the answer `send_error` gives.
enum Request {
    /// Nothing to answer (an empty request line, a read that timed out).
    Nothing,
    /// `send_error(code)`: our one closed word; `version_0_9` where no status line is written.
    Error {
        status: u16,
        version_0_9: bool,
        head: bool,
    },
    Parsed {
        command: String,
        path: String,
        version_0_9: bool,
        headers: Vec<(String, String)>,
    },
}

fn read_line(reader: &mut BufReader<TcpStream>, most: usize) -> std::io::Result<Vec<u8>> {
    let mut line = Vec::new();
    reader
        .by_ref()
        .take(most as u64)
        .read_until(b'\n', &mut line)?;
    Ok(line)
}

fn read_request(reader: &mut BufReader<TcpStream>) -> Request {
    let Ok(raw) = read_line(reader, 65537) else {
        return Request::Nothing;
    };
    if raw.len() > 65536 {
        return Request::Error {
            status: 414,
            version_0_9: false,
            head: false,
        };
    }
    if raw.is_empty() {
        return Request::Nothing;
    }
    let line = latin1(&raw);
    let line = line.trim_end_matches(['\r', '\n']);
    let words = py_split(line);
    if words.is_empty() {
        return Request::Nothing;
    }
    let mut version_0_9 = true;
    if words.len() >= 3 {
        let version = words[words.len() - 1];
        let parsed = version.strip_prefix("HTTP/").and_then(|base| {
            let parts: Vec<&str> = base.split('.').collect();
            if parts.len() != 2
                || parts.iter().any(|part| {
                    part.is_empty() || !part.chars().all(|c| c.is_ascii_digit()) || part.len() > 10
                })
            {
                return None;
            }
            Some((parts[0].parse::<u64>().ok()?, parts[1].parse::<u64>().ok()?))
        });
        let Some(number) = parsed else {
            return Request::Error {
                status: 400,
                version_0_9: true,
                head: false,
            };
        };
        if number >= (2, 0) {
            return Request::Error {
                status: 505,
                version_0_9: true,
                head: false,
            };
        }
        version_0_9 = false;
    }
    if !(2..=3).contains(&words.len()) {
        return Request::Error {
            status: 400,
            version_0_9,
            head: false,
        };
    }
    let (command, mut path) = (words[0].to_owned(), words[1].to_owned());
    if words.len() == 2 && command != "GET" {
        return Request::Error {
            status: 400,
            version_0_9,
            head: false,
        };
    }
    if path.starts_with("//") {
        path = format!("/{}", path.trim_start_matches('/'));
    }
    let mut block = Vec::new();
    let mut count = 0;
    loop {
        let Ok(line) = read_line(reader, 65537) else {
            return Request::Nothing;
        };
        if line.len() > 65536 {
            return Request::Error {
                status: 431,
                version_0_9,
                head: command == "HEAD",
            };
        }
        count += 1;
        let end = line.is_empty() || line == b"\r\n" || line == b"\n";
        block.extend_from_slice(&line);
        if count > 100 {
            return Request::Error {
                status: 431,
                version_0_9,
                head: command == "HEAD",
            };
        }
        if end {
            break;
        }
    }
    Request::Parsed {
        command,
        path,
        version_0_9,
        headers: parse_header_block(&latin1(&block)),
    }
}

/// Constant-time equality (`hmac.compare_digest`).
fn same(given: &[u8], token: &[u8]) -> bool {
    let mut differ = given.len() ^ token.len();
    for (index, byte) in given.iter().enumerate() {
        differ |= usize::from(byte ^ token.get(index % token.len().max(1)).copied().unwrap_or(0));
    }
    differ == 0
}

fn handle(
    service: &Service,
    gate: &Gate,
    reader: &mut BufReader<TcpStream>,
    peer: &str,
) -> Option<(Answer, bool, bool)> {
    let (command, path, version_0_9, headers) = match read_request(reader) {
        Request::Nothing => return None,
        Request::Error {
            status,
            version_0_9,
            head,
        } => {
            return Some((refuse(status, "bad_request", Vec::new()), version_0_9, head));
        }
        Request::Parsed {
            command,
            path,
            version_0_9,
            headers,
        } => (command, path, version_0_9, headers),
    };
    if !METHODS.contains(&command.as_str()) {
        return Some((refuse(501, "bad_request", Vec::new()), version_0_9, false));
    }
    let head = command == "HEAD";
    let done = |answer: Answer| Some((answer, version_0_9, head));
    let client = client_of(peer);
    if gate.closed(&client) {
        return done(refuse(
            503,
            "locked",
            vec![("Retry-After", format!("{}", LOCK_SECONDS as i64))],
        ));
    }
    let hosts: Vec<&str> = headers
        .iter()
        .filter(|(name, _)| name.eq_ignore_ascii_case("Host"))
        .map(|(_, value)| value.as_str())
        .collect();
    if hosts.len() != 1 || !host_allowed(hosts[0], service.port, service.lan) {
        return done(refuse(421, "misdirected", Vec::new()));
    }
    let Some(route) = route_of(&path) else {
        return done(refuse(404, "not_found", Vec::new()));
    };
    let (_, method, action) = ROUTES
        .iter()
        .find(|(each, _, _)| *each == route)
        .copied()
        .unwrap_or(("/", "GET", false));
    if command != method {
        return done(refuse(405, "method", vec![("Allow", method.to_owned())]));
    }
    if route == "/" {
        return done(match (service.page)() {
            Ok(page) => Answer {
                status: 200,
                body: page,
                kind: "text/html; charset=utf-8",
                extra: vec![(
                    "Content-Security-Policy",
                    crate::courier::page::CSP.to_owned(),
                )],
            },
            Err(()) => refuse(503, "unavailable", Vec::new()),
        });
    }
    let given = header_get(&headers, "Authorization").unwrap_or("");
    let token = service.token();
    let authorized = match (&token, given.strip_prefix("Bearer ")) {
        (Some(token), Some(offered)) => same(offered.as_bytes(), token.as_bytes()),
        _ => false,
    };
    if !authorized {
        if given.starts_with("Bearer ") && given.len() > "Bearer ".len() && gate.wrong(&client) {
            let _ = service.counted(API, "locked");
        }
        return done(refuse(
            401,
            "unauthorized",
            vec![("WWW-Authenticate", "Bearer".to_owned())],
        ));
    }
    let mut body = Vec::new();
    if action {
        if !service.actions_on() {
            return done(refuse(403, "not_on", Vec::new()));
        }
        let length = header_get(&headers, "Content-Length").unwrap_or("");
        let length = if length.is_empty() {
            Some(0)
        } else {
            car_machine::pytext::parse_int(length, 10).and_then(|parsed| {
                let magnitude = i64::try_from(parsed.magnitude?).ok()?;
                Some(if parsed.negative {
                    -magnitude
                } else {
                    magnitude
                })
            })
        };
        let Some(length) = length else {
            return done(refuse(400, "length", Vec::new()));
        };
        if !(0..=MAX_BODY).contains(&length) {
            return done(refuse(413, "too_large", Vec::new()));
        }
        if length > 0 {
            let mut taken = Vec::new();
            if reader
                .by_ref()
                .take(length as u64)
                .read_to_end(&mut taken)
                .is_err()
            {
                return None;
            }
            body = taken;
        }
    }
    let answered = (|| -> Result<Answer, Failed> {
        match route {
            "/status.json" => json_answer(&service.layer.status_document((service.clock)())?),
            "/metrics" => {
                let document = service.layer.status_document((service.clock)())?;
                Ok(Answer {
                    status: 200,
                    body: remote_layer::metrics(&document)?.into_bytes(),
                    kind: "text/plain; version=0.0.4; charset=utf-8",
                    extra: Vec::new(),
                })
            }
            "/pending" => json_answer(&remote_layer::pending(service.layer.as_ref())?),
            "/pause" | "/resume-off" => {
                let found = remote_layer::pause(service.layer.as_ref())?;
                service.counted(API_ACTIONS, "paused")?;
                json_answer(&found)
            }
            _ => cancel(service, &path, &body),
        }
    })();
    done(answered.unwrap_or_else(|_| refuse(503, "unavailable", Vec::new())))
}

fn cancel(service: &Service, path: &str, body: &[u8]) -> Result<Answer, Failed> {
    let listed = if body.is_empty() {
        Value::Null
    } else {
        match crate::courier::feed::loads_bytes(body) {
            Ok(Some(Value::Object(found))) => found.get("snapshot").cloned().unwrap_or(Value::Null),
            Ok(_) => return Ok(refuse(400, "body", Vec::new())),
            Err(()) => return Err(Failed::Raised("RecursionError".into())),
        }
    };
    let number = cancel_number(path.split('?').next().unwrap_or("")).unwrap_or("");
    let alias = Value::from(format!("task {number}"));
    match remote_layer::cancel(service.layer.as_ref(), &alias, &listed) {
        Ok(found) => {
            service.counted(API_ACTIONS, "cancelled")?;
            json_answer(&found)
        }
        Err(Failed::Stale) => {
            service.counted(API_ACTIONS, "list_again")?;
            Ok(refuse(409, "list_again", Vec::new()))
        }
        Err(other) => Err(other),
    }
}

/// One connection, from its setup to its linger: as `Handler` serves it.
fn serve_one(service: &Service, gate: &Gate, stream: TcpStream) {
    let peer = stream
        .peer_addr()
        .map(|address| address.ip().to_string())
        .unwrap_or_default();
    let limit = Some(Duration::from_secs(TIMEOUT));
    let _ = stream.set_read_timeout(limit);
    let _ = stream.set_write_timeout(limit);
    let (cancel, cancelled) = mpsc::channel::<()>();
    if let Ok(watched) = stream.try_clone() {
        std::thread::spawn(move || {
            if cancelled.recv_timeout(Duration::from_secs(DEADLINE))
                == Err(mpsc::RecvTimeoutError::Timeout)
            {
                let _ = watched.shutdown(Shutdown::Both);
            }
        });
    }
    let Ok(read_half) = stream.try_clone() else {
        return;
    };
    let mut reader = BufReader::new(read_half);
    let now = (service.clock)();
    let answer = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        handle(service, gate, &mut reader, &peer)
    }))
    .ok()
    .flatten();
    let mut writer = &stream;
    if let Some((answer, version_0_9, head)) = answer {
        let _ = writer.write_all(&written(&answer, version_0_9, head, now));
        let _ = writer.flush();
    }
    let _ = cancel.send(());
    // _linger: the answer ends, and what the client still sends is read and dropped, bounded both ways.
    let _ = stream.shutdown(Shutdown::Write);
    let end = Instant::now() + Duration::from_secs_f64(LINGER_SECONDS);
    let mut left = LINGER_BYTES;
    let mut buffer = [0u8; 4096];
    while left > 0 {
        let wait = end.saturating_duration_since(Instant::now());
        if wait.is_zero() || stream.set_read_timeout(Some(wait)).is_err() {
            break;
        }
        match reader.get_mut().read(&mut buffer[..left.min(4096)]) {
            Ok(0) | Err(_) => break,
            Ok(got) => left -= got.min(left),
        }
    }
}

/// `Running`: a server serving on its own thread, until `close`.
pub struct Running {
    pub port: i64,
    pub addresses: Vec<String>,
    stop: Arc<AtomicBool>,
    thread: Option<std::thread::JoinHandle<()>>,
}

impl Served for Running {
    fn addresses(&self) -> Vec<String> {
        self.addresses.clone()
    }

    fn close(&mut self) {
        self.stop.store(true, Ordering::SeqCst);
        if let Some(thread) = self.thread.take() {
            let until = Instant::now() + Duration::from_secs(2);
            while !thread.is_finished() && Instant::now() < until {
                std::thread::sleep(Duration::from_millis(10));
            }
            if thread.is_finished() {
                let _ = thread.join();
            }
        }
    }
}

impl Drop for Running {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::SeqCst);
    }
}

/// `lan_addresses()`: this PC's own IPv4 addresses on its networks as Windows resolves its own name (no request leaves
/// the PC), loopback, link-local, multicast and unspecified ones left out, at most four.
pub fn lan_addresses() -> Vec<String> {
    use std::net::ToSocketAddrs;
    let Ok(name) = std::env::var("COMPUTERNAME") else {
        return Vec::new();
    };
    let Ok(found) = (name.as_str(), 0).to_socket_addrs() else {
        return Vec::new();
    };
    let mut kept: Vec<String> = Vec::new();
    for each in found {
        let std::net::IpAddr::V4(four) = each.ip() else {
            continue;
        };
        if four.is_loopback()
            || four.is_link_local()
            || four.is_unspecified()
            || four.is_multicast()
        {
            continue;
        }
        let text = four.to_string();
        if !kept.contains(&text) {
            kept.push(text);
        }
    }
    kept.truncate(4);
    kept
}

/// `bind_address(lan)`.
pub fn bind_address(lan: bool) -> [u8; 4] {
    if lan { EVERYWHERE } else { LOOPBACK }
}

/// `start(runtime, port, lan, service=, clock=)` with the address it binds given (`bind_address(lan)` in the product;
/// a test's 127.0.0.1 always): the server started on `port` (0 for any free one), or the error where it is taken.
pub fn start_on(mut service: Service, bind: [u8; 4], port: i64) -> std::io::Result<Running> {
    let listener: TcpListener = car_platform::winhttp::exclusive_listener(
        bind,
        u16::try_from(port).unwrap_or(0),
        THREADS as i32,
    )?;
    let bound = i64::from(listener.local_addr()?.port());
    if port == 0 {
        service.port = bound;
    }
    listener.set_nonblocking(true)?;
    let lan = service.lan;
    let gate = Arc::new(Gate::new(service.clock.clone()));
    let service = Arc::new(service);
    let stop = Arc::new(AtomicBool::new(false));
    let slots = Arc::new(AtomicUsize::new(0));
    let watched = stop.clone();
    let thread = std::thread::Builder::new()
        .name("local-api".into())
        .spawn(move || {
            while !watched.load(Ordering::SeqCst) {
                match listener.accept() {
                    Ok((stream, _)) => {
                        let _ = stream.set_nonblocking(false);
                        if slots.fetch_add(1, Ordering::SeqCst) >= THREADS {
                            slots.fetch_sub(1, Ordering::SeqCst);
                            let _ = stream.shutdown(Shutdown::Write);
                            continue;
                        }
                        let (service, gate, slots) = (service.clone(), gate.clone(), slots.clone());
                        std::thread::spawn(move || {
                            serve_one(&service, &gate, stream);
                            slots.fetch_sub(1, Ordering::SeqCst);
                        });
                    }
                    Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                        std::thread::sleep(Duration::from_millis(20));
                    }
                    Err(_) => std::thread::sleep(Duration::from_millis(20)),
                }
            }
        })?;
    Ok(Running {
        port: bound,
        addresses: if lan { lan_addresses() } else { Vec::new() },
        stop,
        thread: Some(thread),
    })
}

/// `start(runtime, port, lan)`: as the product starts it.
pub fn start(service: Service, port: i64) -> std::io::Result<Running> {
    let bind = bind_address(service.lan);
    start_on(service, bind, port)
}
