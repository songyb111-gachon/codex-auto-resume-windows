//! `smtplib.SMTP` / `SMTP_SSL` as `channels.mail` drives them: connect (and, on 465, TLS from the start), read the
//! greeting, EHLO (HELO where it is refused), STARTTLS on 587, sign in by the best of CRAM-MD5, PLAIN and LOGIN the
//! server offers, send the one message (MAIL, RCPT, DATA with its periods doubled), QUIT. Every command and reply as
//! smtplib writes and reads it; every failure the exception smtplib raises ([`Error`]).
//!
//! [`Wire`] is the socket and its TLS (`socket.create_connection` and `context.wrap_socket`, the system's Schannel
//! through car-platform `tls`, the name checked); a test's wire reaches a loopback server of its own.

#![allow(clippy::result_unit_err, clippy::result_large_err)]

use std::io::{BufRead, BufReader, Read, Write};
use std::net::TcpStream;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use super::mime;

const MAXLINE: usize = 8192;
const MAXCHALLENGE: u32 = 5;

/// A stream a session reads and writes.
pub trait Stream: Read + Write + Send {}
impl<T: Read + Write + Send> Stream for T {}

/// How a TLS handshake failed.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Handshake {
    /// `ssl.SSLError` / `CertificateError`.
    Tls,
    /// The socket failed under it (`OSError`).
    Io,
}

/// The socket and its TLS, as smtplib makes them.
pub trait Wire: Send + Sync {
    /// `socket.create_connection((host, port), timeout)`.
    fn connect(&self, host: &str, port: u16, timeout: i64) -> std::io::Result<Box<dyn Stream>>;
    /// `context.wrap_socket(stream, server_hostname=host)`.
    fn secure(&self, stream: Box<dyn Stream>, host: &str) -> Result<Box<dyn Stream>, Handshake>;
    /// `socket.getfqdn()` as smtplib names this PC to the server (EHLO's argument).
    fn local_hostname(&self) -> String;
}

/// What smtplib raises.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Error {
    /// `SMTPNotSupportedError`.
    NotSupported,
    /// `SMTPAuthenticationError(code)`.
    Authentication(i64),
    /// `SMTPResponseException(code)` and its kin (`SMTPConnectError`, `SMTPHeloError`, `SMTPSenderRefused`,
    /// `SMTPDataError`).
    Response(i64),
    /// `SMTPRecipientsRefused`.
    Recipients,
    /// `ssl.SSLError`.
    Tls,
    /// `SMTPServerDisconnected` or a plain `SMTPException`.
    Smtp,
    /// `OSError` / `socket.timeout`.
    Os,
    /// `binascii.Error`, a ValueError, out of a challenge that is not base64.
    Value,
}

/// One session.
pub struct Session {
    stream: BufReader<Box<dyn Stream>>,
    local_hostname: String,
    esmtp: Option<Vec<(String, String)>>,
    helo_done: bool,
    challenges: u32,
}

impl Session {
    fn send(&mut self, data: &[u8]) -> Result<(), Error> {
        self.stream
            .get_mut()
            .write_all(data)
            .and_then(|()| self.stream.get_mut().flush())
            .map_err(|_| Error::Smtp)
    }

    fn putcmd(&mut self, command: &str, args: &str) -> Result<(), Error> {
        let line = if args.is_empty() {
            command.to_owned()
        } else {
            format!("{command} {args}")
        };
        if line.contains(['\r', '\n']) {
            return Err(Error::Value);
        }
        self.send(format!("{line}\r\n").as_bytes())
    }

    /// `getreply()`: the code (-1 where it is not one) and the reply's lines joined by `\n`.
    fn getreply(&mut self) -> Result<(i64, Vec<u8>), Error> {
        let mut lines: Vec<Vec<u8>> = Vec::new();
        loop {
            let mut line = Vec::new();
            let read = (&mut self.stream)
                .take((MAXLINE + 1) as u64)
                .read_until(b'\n', &mut line);
            match read {
                Err(_) => return Err(Error::Smtp),
                Ok(0) => return Err(Error::Smtp),
                Ok(_) => {}
            }
            if line.len() > MAXLINE {
                return Err(Error::Response(500));
            }
            let text = if line.len() > 4 { &line[4..] } else { &[][..] };
            let trimmed: &[u8] = {
                let start = text
                    .iter()
                    .position(|b| !b" \t\r\n".contains(b))
                    .unwrap_or(text.len());
                let end = text
                    .iter()
                    .rposition(|b| !b" \t\r\n".contains(b))
                    .map_or(start, |at| at + 1);
                &text[start..end.max(start)]
            };
            lines.push(trimmed.to_vec());
            let code = &line[..line.len().min(3)];
            let errcode = parse_code(code);
            match errcode {
                None => return Ok((-1, lines.join(&b"\n"[..]))),
                Some(found) => {
                    if line.get(3) != Some(&b'-') {
                        return Ok((found, lines.join(&b"\n"[..])));
                    }
                }
            }
        }
    }

    fn docmd(&mut self, command: &str, args: &str) -> Result<(i64, Vec<u8>), Error> {
        self.putcmd(command, args)?;
        self.getreply()
    }

    fn ehlo(&mut self) -> Result<i64, Error> {
        self.esmtp = None;
        let name = self.local_hostname.clone();
        self.putcmd("ehlo", &name)?;
        let (code, message) = self.getreply()?;
        if code == -1 && message.is_empty() {
            return Err(Error::Smtp);
        }
        if code != 250 {
            return Ok(code);
        }
        let text: String = message.iter().map(|b| *b as char).collect();
        let mut features: Vec<(String, String)> = Vec::new();
        let mut put = |name: String, value: String, append: bool| {
            if let Some(found) = features.iter_mut().find(|(each, _)| *each == name) {
                if append {
                    found.1.push(' ');
                    found.1.push_str(&value);
                } else {
                    found.1 = value;
                }
            } else if append {
                features.push((name, format!(" {value}")));
            } else {
                features.push((name, value));
            }
        };
        for each in text.split('\n').skip(1) {
            // OLDSTYLE_AUTH: `auth=(.*)`, any case.
            if each.len() >= 5 && each[..5].eq_ignore_ascii_case("auth=") {
                put("auth".into(), each[5..].to_owned(), true);
                continue;
            }
            // `(?P<feature>[A-Za-z0-9][A-Za-z0-9\-]*) ?`
            let bytes = each.as_bytes();
            if bytes.first().is_some_and(u8::is_ascii_alphanumeric) {
                let end = bytes
                    .iter()
                    .position(|b| !(b.is_ascii_alphanumeric() || *b == b'-'))
                    .unwrap_or(bytes.len());
                let feature = each[..end].to_ascii_lowercase();
                let params = py_strip(&each[end..]).to_owned();
                let append = feature == "auth";
                put(feature, params, append);
            }
        }
        self.esmtp = Some(features);
        Ok(code)
    }

    fn has(&self, name: &str) -> Option<&str> {
        self.esmtp
            .as_ref()?
            .iter()
            .find(|(each, _)| each == name)
            .map(|(_, value)| value.as_str())
    }

    /// `ehlo_or_helo_if_needed()`.
    fn hello(&mut self) -> Result<(), Error> {
        if self.helo_done || self.esmtp.is_some() {
            return Ok(());
        }
        let code = self.ehlo()?;
        if !(200..=299).contains(&code) {
            let name = self.local_hostname.clone();
            let (code, _) = self.docmd("helo", &name)?;
            if !(200..=299).contains(&code) {
                return Err(Error::Response(code));
            }
            self.helo_done = true;
        }
        Ok(())
    }

    fn reset_hello(&mut self) {
        self.esmtp = None;
        self.helo_done = false;
    }

    /// `starttls(context)`.
    pub fn starttls(
        self,
        wire: &dyn Wire,
        host: &str,
    ) -> Result<Session, (Error, Option<Session>)> {
        let mut session = self;
        if let Err(error) = session.hello() {
            return Err((error, Some(session)));
        }
        if session.has("starttls").is_none() {
            return Err((Error::NotSupported, Some(session)));
        }
        let (code, _) = match session.docmd("STARTTLS", "") {
            Ok(found) => found,
            Err(error) => return Err((error, Some(session))),
        };
        if code != 220 {
            return Err((Error::Response(code), Some(session)));
        }
        let stream = session.stream.into_inner();
        match wire.secure(stream, host) {
            Ok(stream) => Ok(Session {
                stream: BufReader::new(stream),
                local_hostname: session.local_hostname,
                esmtp: None,
                helo_done: false,
                challenges: 0,
            }),
            Err(Handshake::Tls) => Err((Error::Tls, None)),
            Err(Handshake::Io) => Err((Error::Os, None)),
        }
    }

    fn auth(
        &mut self,
        mechanism: &str,
        user: &str,
        password: &str,
    ) -> Result<(i64, Vec<u8>), Error> {
        let initial = match mechanism {
            "PLAIN" => Some(format!("\0{user}\0{password}")),
            "LOGIN" => Some(user.to_owned()),
            _ => None,
        };
        let (mut code, mut reply) = match initial {
            Some(initial) => {
                let response = mime::b2a_base64(initial.as_bytes(), false);
                let found = self.docmd("AUTH", &format!("{mechanism} {response}"))?;
                self.challenges = 1;
                found
            }
            None => {
                let found = self.docmd("AUTH", mechanism)?;
                self.challenges = 0;
                found
            }
        };
        while code == 334 {
            self.challenges += 1;
            let challenge = mime::a2b_base64(&reply).map_err(|()| Error::Value)?;
            let answer = match mechanism {
                "CRAM-MD5" => format!(
                    "{user} {}",
                    mime::hmac_md5_hex(password.as_bytes(), &challenge)
                ),
                "PLAIN" => format!("\0{user}\0{password}"),
                _ => {
                    if self.challenges < 2 {
                        user.to_owned()
                    } else {
                        password.to_owned()
                    }
                }
            };
            let response = mime::b2a_base64(answer.as_bytes(), false);
            (code, reply) = self.docmd(&response, "")?;
            if self.challenges > MAXCHALLENGE {
                return Err(Error::Smtp);
            }
        }
        if code == 235 || code == 503 {
            return Ok((code, reply));
        }
        Err(Error::Authentication(code))
    }

    /// `login(user, password)`.
    pub fn login(&mut self, user: &str, password: &str) -> Result<(), Error> {
        self.hello()?;
        let Some(advertised) = self.has("auth").map(str::to_owned) else {
            return Err(Error::NotSupported);
        };
        let advertised: Vec<&str> = advertised.split_whitespace().collect();
        let methods: Vec<&str> = ["CRAM-MD5", "PLAIN", "LOGIN"]
            .into_iter()
            .filter(|method| advertised.contains(method))
            .collect();
        if methods.is_empty() {
            return Err(Error::Smtp);
        }
        let mut last = Error::Smtp;
        for method in methods {
            match self.auth(method, user, password) {
                Ok(_) => return Ok(()),
                Err(Error::Authentication(code)) => last = Error::Authentication(code),
                Err(other) => return Err(other),
            }
        }
        Err(last)
    }

    /// `send_message(message)` with its sender and one recipient: MAIL (SIZE where it is offered), RCPT, DATA.
    pub fn send_message(&mut self, from: &str, to: &str, message: &[u8]) -> Result<(), Error> {
        self.hello()?;
        let mut options = String::new();
        if self.esmtp.is_some() && self.has("size").is_some() {
            options = format!(" size={}", message.len());
        }
        let (code, _) = self.docmd("mail", &format!("from:<{from}>{options}"))?;
        if code != 250 {
            if code != 421 {
                let _ = self.docmd("rset", "");
            }
            return Err(Error::Response(code));
        }
        let (code, _) = self.docmd("rcpt", &format!("to:<{to}>"))?;
        if code != 250 && code != 251 {
            if code != 421 {
                let _ = self.docmd("rset", "");
            }
            return Err(Error::Recipients);
        }
        let (code, _) = self.docmd("data", "")?;
        if code != 354 {
            return Err(Error::Response(code));
        }
        let mut quoted = quote_periods(message);
        if !quoted.ends_with(b"\r\n") {
            quoted.extend_from_slice(b"\r\n");
        }
        quoted.extend_from_slice(b".\r\n");
        self.send(&quoted)?;
        let (code, _) = self.getreply()?;
        if code != 250 {
            if code != 421 {
                let _ = self.docmd("rset", "");
            }
            return Err(Error::Response(code));
        }
        Ok(())
    }

    /// `quit()`.
    pub fn quit(mut self) {
        let _ = self.docmd("quit", "");
        self.reset_hello();
    }
}

/// `int(code)` of a reply's first three bytes (bytes: ASCII white space around it, an underscore between digits).
fn parse_code(code: &[u8]) -> Option<i64> {
    if !code.is_ascii() {
        return None;
    }
    let text = std::str::from_utf8(code).ok()?;
    let parsed = car_machine::pytext::parse_int(text, 10)?;
    let magnitude = i64::try_from(parsed.magnitude?).ok()?;
    Some(if parsed.negative {
        -magnitude
    } else {
        magnitude
    })
}

fn py_strip(text: &str) -> &str {
    car_machine::pytext::strip(text)
}

/// `_quote_periods`: every line that starts with a period has it doubled.
fn quote_periods(data: &[u8]) -> Vec<u8> {
    let mut out = Vec::with_capacity(data.len() + 8);
    let mut at_line_start = true;
    for &b in data {
        if at_line_start && b == b'.' {
            out.push(b'.');
        }
        out.push(b);
        at_line_start = b == b'\n';
    }
    out
}

/// `SMTP(host, port, timeout)` or `SMTP_SSL(host, port, timeout, context)`: connected, greeted (220).
pub fn open(
    wire: &dyn Wire,
    host: &str,
    port: u16,
    timeout: i64,
    ssl: bool,
) -> Result<Session, Error> {
    let stream = wire.connect(host, port, timeout).map_err(|_| Error::Os)?;
    let stream = if ssl {
        wire.secure(stream, host).map_err(|failed| match failed {
            Handshake::Tls => Error::Tls,
            Handshake::Io => Error::Os,
        })?
    } else {
        stream
    };
    let mut session = Session {
        stream: BufReader::new(stream),
        local_hostname: wire.local_hostname(),
        esmtp: None,
        helo_done: false,
        challenges: 0,
    };
    let (code, _) = session.getreply()?;
    if code != 220 {
        return Err(Error::Response(code));
    }
    Ok(session)
}

// ------------------------------------------------------------------------------------------ the system's wire
/// A TCP wire: every socket held by the time in all (`deadline`, closed both ways when it comes, so a read waiting on
/// it returns at once), TLS by Schannel - or, for a test's loopback server, every connection made to `loopback`
/// whatever the host, and no TLS (`plain`).
pub struct TcpWire {
    pub local_hostname: String,
    /// A test's own server: every connection goes to 127.0.0.1 at this port, and nothing is encrypted.
    pub loopback: Option<u16>,
    held: Arc<Mutex<Vec<TcpStream>>>,
}

impl TcpWire {
    /// A wire whose sockets are all shut `whole_seconds` from now.
    pub fn new(local_hostname: String, loopback: Option<u16>, whole_seconds: u64) -> TcpWire {
        let held: Arc<Mutex<Vec<TcpStream>>> = Arc::new(Mutex::new(Vec::new()));
        let watched = Arc::downgrade(&held);
        std::thread::spawn(move || {
            std::thread::sleep(Duration::from_secs(whole_seconds));
            if let Some(held) = watched.upgrade() {
                for stream in held
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner)
                    .iter()
                {
                    let _ = stream.shutdown(std::net::Shutdown::Both);
                }
            }
        });
        TcpWire {
            local_hostname,
            loopback,
            held,
        }
    }
}

impl Wire for TcpWire {
    fn connect(&self, host: &str, port: u16, timeout: i64) -> std::io::Result<Box<dyn Stream>> {
        let limit = Duration::from_secs(timeout.max(1) as u64);
        let stream = match self.loopback {
            Some(port) => TcpStream::connect_timeout(&([127, 0, 0, 1], port).into(), limit)?,
            None => {
                use std::net::ToSocketAddrs;
                let mut last = std::io::Error::other("no address");
                let mut made = None;
                for address in (host, port).to_socket_addrs()? {
                    match TcpStream::connect_timeout(&address, limit) {
                        Ok(stream) => {
                            made = Some(stream);
                            break;
                        }
                        Err(error) => last = error,
                    }
                }
                made.ok_or(last)?
            }
        };
        stream.set_read_timeout(Some(limit))?;
        stream.set_write_timeout(Some(limit))?;
        self.held
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .push(stream.try_clone()?);
        Ok(Box::new(stream))
    }

    fn secure(&self, stream: Box<dyn Stream>, host: &str) -> Result<Box<dyn Stream>, Handshake> {
        if self.loopback.is_some() {
            return Ok(stream);
        }
        match car_platform::tls::client(stream, host) {
            Ok(session) => Ok(Box::new(session)),
            Err(car_platform::tls::Error::Tls(_)) => Err(Handshake::Tls),
            Err(car_platform::tls::Error::Io(_)) => Err(Handshake::Io),
        }
    }

    fn local_hostname(&self) -> String {
        self.local_hostname.clone()
    }
}
