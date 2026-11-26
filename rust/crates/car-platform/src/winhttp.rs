//! The advanced courier's HTTPS (seat S7.3b; the owner's Q4 (a): WinHTTP through `windows`, the system's TLS).
//!
//! One synchronous request: the system's certificate store and host-name check (WinHTTP's defaults, never turned
//! off), TLS 1.2 or later, no redirect followed (a 3xx is answered as it is), no cookie, no authentication, no keep-alive,
//! the address's path and query sent as written. Each phase waits at most the request's timeout, and the whole
//! request - resolving, connecting, sending, the headers and every read of the body - at most `whole_ms` from its
//! start: each phase's timeout is what is left of that, so a service that trickles a byte inside each read's timeout
//! is cut at the time in all (`expired`). The body is read up to `most` bytes and no further.
//!
//! Only the advanced edition calls this (the courier, `courier/http.rs`): the standard binaries link none of it
//! (standard C2). `secure: false` is plain HTTP for a test's own loopback server, and is refused for any host but
//! 127.0.0.1 before anything is opened.

use std::time::{Duration, Instant};

use windows::Win32::Networking::WinHttp::{
    WINHTTP_ACCESS_TYPE, WINHTTP_ACCESS_TYPE_AUTOMATIC_PROXY, WINHTTP_ACCESS_TYPE_NO_PROXY,
    WINHTTP_ADDREQ_FLAG_ADD, WINHTTP_ADDREQ_FLAG_REPLACE, WINHTTP_DISABLE_AUTHENTICATION,
    WINHTTP_DISABLE_COOKIES, WINHTTP_DISABLE_KEEP_ALIVE, WINHTTP_DISABLE_REDIRECTS,
    WINHTTP_FLAG_ESCAPE_DISABLE, WINHTTP_FLAG_ESCAPE_DISABLE_QUERY, WINHTTP_FLAG_SECURE,
    WINHTTP_FLAG_SECURE_PROTOCOL_TLS1_2, WINHTTP_FLAG_SECURE_PROTOCOL_TLS1_3,
    WINHTTP_OPEN_REQUEST_FLAGS, WINHTTP_OPTION_CONNECT_TIMEOUT, WINHTTP_OPTION_DISABLE_FEATURE,
    WINHTTP_OPTION_RECEIVE_RESPONSE_TIMEOUT, WINHTTP_OPTION_RECEIVE_TIMEOUT,
    WINHTTP_OPTION_REDIRECT_POLICY, WINHTTP_OPTION_REDIRECT_POLICY_NEVER,
    WINHTTP_OPTION_RESOLVE_TIMEOUT, WINHTTP_OPTION_SECURE_PROTOCOLS, WINHTTP_OPTION_SEND_TIMEOUT,
    WINHTTP_QUERY_FLAG_NUMBER, WINHTTP_QUERY_STATUS_CODE, WinHttpAddRequestHeaders,
    WinHttpCloseHandle, WinHttpConnect, WinHttpOpen, WinHttpOpenRequest, WinHttpQueryHeaders,
    WinHttpReadData, WinHttpReceiveResponse, WinHttpSendRequest, WinHttpSetOption,
};
use windows::core::{HSTRING, PCWSTR};

/// One request.
pub struct Asked<'a> {
    pub url: &'a str,
    pub method: &'a str,
    /// Sent as given, after `Accept-Encoding: identity` and before `Connection: close` (urllib's own two).
    pub headers: &'a [(&'a str, &'a str)],
    pub body: Option<&'a [u8]>,
    /// Each phase's timeout.
    pub timeout_ms: u32,
    /// The request's time in all, from its start.
    pub whole_ms: u32,
    /// Bytes of the body read, at most.
    pub most: usize,
    /// HTTPS (the courier, always); plain HTTP only for 127.0.0.1.
    pub secure: bool,
}

/// What the service answered.
#[derive(Debug)]
pub struct Reply {
    pub status: u32,
    /// The body up to `most` bytes, or how its read failed.
    pub body: Result<Vec<u8>, Error>,
    /// The time in all ran out while the body was read: what was read may be cut.
    pub expired: bool,
}

/// How a request failed, by what the courier tells apart.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Error {
    /// The secure connection refused: a certificate that does not verify, a TLS failure. Never downgraded.
    Tls,
    /// No answer in time, or no way there at all.
    Timeout,
    /// The address is not one this function takes (not https, or plain HTTP beyond 127.0.0.1).
    Refused,
}

/// WinHTTP's `ERROR_WINHTTP_*` codes of the secure channel.
fn is_tls(code: u32) -> bool {
    matches!(
        code,
        12037..=12045 | 12157 | 12169 | 12175 | 12179 | 12185 | 12186 | 12187
    )
}

fn fault(error: &windows::core::Error) -> Error {
    let code = (error.code().0 as u32) & 0xFFFF;
    if is_tls(code) {
        Error::Tls
    } else {
        Error::Timeout
    }
}

/// The parts of an address WinHTTP is handed: host, port, path with its query.
#[derive(Debug, PartialEq, Eq)]
pub struct Target {
    pub secure: bool,
    pub host: String,
    pub port: u16,
    pub path: String,
}

/// `scheme://host[:port][/path][?query]`, its fragment already taken off by the caller.
pub fn target(url: &str) -> Option<Target> {
    let (scheme, rest) = url.split_once("://")?;
    let secure = match scheme.to_ascii_lowercase().as_str() {
        "https" => true,
        "http" => false,
        _ => return None,
    };
    let end = rest.find(['/', '?']).unwrap_or(rest.len());
    let (authority, path) = rest.split_at(end);
    if authority.contains('@') || authority.is_empty() {
        return None;
    }
    let (host, port) = if let Some(after) = authority.strip_prefix('[') {
        let (host, tail) = after.split_once(']')?;
        (host.to_owned(), tail.strip_prefix(':'))
    } else {
        match authority.rsplit_once(':') {
            Some((host, port)) => (host.to_owned(), Some(port)),
            None => (authority.to_owned(), None),
        }
    };
    let port = match port {
        Some("") | None => {
            if secure {
                443
            } else {
                80
            }
        }
        Some(port) => port.parse().ok()?,
    };
    let path = if path.is_empty() {
        "/".to_owned()
    } else if path.starts_with('?') {
        format!("/{path}")
    } else {
        path.to_owned()
    };
    Some(Target {
        secure,
        host,
        port,
        path,
    })
}

struct Handle(*mut core::ffi::c_void);

impl Drop for Handle {
    fn drop(&mut self) {
        if !self.0.is_null() {
            // SAFETY: a handle WinHTTP gave this function, closed once.
            unsafe {
                let _ = WinHttpCloseHandle(self.0);
            }
        }
    }
}

fn option(handle: &Handle, name: u32, value: u32) -> Result<(), windows::core::Error> {
    // SAFETY: an open handle and a DWORD option.
    unsafe { WinHttpSetOption(Some(handle.0), name, Some(&value.to_ne_bytes())) }
}

/// What is left of the time in all, as a phase's timeout (at least 1 ms: 0 is WinHTTP's "no timeout").
fn left(start: Instant, timeout_ms: u32, whole_ms: u32) -> Option<u32> {
    let spent = start.elapsed();
    let whole = Duration::from_millis(u64::from(whole_ms));
    if spent >= whole {
        return None;
    }
    let rest = (whole - spent).as_millis().min(u128::from(u32::MAX)) as u32;
    Some(rest.min(timeout_ms).max(1))
}

fn phase(request: &Handle, start: Instant, asked: &Asked<'_>) -> Result<(), Error> {
    let Some(ms) = left(start, asked.timeout_ms, asked.whole_ms) else {
        return Err(Error::Timeout);
    };
    for name in [
        WINHTTP_OPTION_RESOLVE_TIMEOUT,
        WINHTTP_OPTION_CONNECT_TIMEOUT,
        WINHTTP_OPTION_SEND_TIMEOUT,
        WINHTTP_OPTION_RECEIVE_TIMEOUT,
        WINHTTP_OPTION_RECEIVE_RESPONSE_TIMEOUT,
    ] {
        option(request, name, ms).map_err(|_| Error::Timeout)?;
    }
    Ok(())
}

/// One request, as the module says.
pub fn send(asked: &Asked<'_>) -> Result<Reply, Error> {
    let Some(target) = target(asked.url) else {
        return Err(Error::Refused);
    };
    if target.secure != asked.secure || (!target.secure && target.host != "127.0.0.1") {
        return Err(Error::Refused);
    }
    let start = Instant::now();
    let access: WINHTTP_ACCESS_TYPE = if asked.secure {
        WINHTTP_ACCESS_TYPE_AUTOMATIC_PROXY
    } else {
        WINHTTP_ACCESS_TYPE_NO_PROXY
    };
    // SAFETY: plain WinHTTP calls on handles this function owns (each closed by `Handle`'s drop, children first).
    unsafe {
        let session = Handle(WinHttpOpen(
            PCWSTR::null(),
            access,
            PCWSTR::null(),
            PCWSTR::null(),
            0,
        ));
        if session.0.is_null() {
            return Err(Error::Timeout);
        }
        if asked.secure {
            option(
                &session,
                WINHTTP_OPTION_SECURE_PROTOCOLS,
                WINHTTP_FLAG_SECURE_PROTOCOL_TLS1_2 | WINHTTP_FLAG_SECURE_PROTOCOL_TLS1_3,
            )
            .or_else(|_| {
                option(
                    &session,
                    WINHTTP_OPTION_SECURE_PROTOCOLS,
                    WINHTTP_FLAG_SECURE_PROTOCOL_TLS1_2,
                )
            })
            .map_err(|_| Error::Tls)?;
        }
        option(
            &session,
            WINHTTP_OPTION_REDIRECT_POLICY,
            WINHTTP_OPTION_REDIRECT_POLICY_NEVER,
        )
        .map_err(|_| Error::Timeout)?;
        let connection = Handle(WinHttpConnect(
            session.0,
            &HSTRING::from(target.host.as_str()),
            target.port,
            0,
        ));
        if connection.0.is_null() {
            return Err(Error::Timeout);
        }
        let mut flags = WINHTTP_FLAG_ESCAPE_DISABLE.0 | WINHTTP_FLAG_ESCAPE_DISABLE_QUERY.0;
        if asked.secure {
            flags |= WINHTTP_FLAG_SECURE.0;
        }
        let request = Handle(WinHttpOpenRequest(
            connection.0,
            &HSTRING::from(asked.method),
            &HSTRING::from(target.path.as_str()),
            PCWSTR::null(),
            PCWSTR::null(),
            std::ptr::null(),
            WINHTTP_OPEN_REQUEST_FLAGS(flags),
        ));
        if request.0.is_null() {
            return Err(Error::Timeout);
        }
        option(
            &request,
            WINHTTP_OPTION_DISABLE_FEATURE,
            WINHTTP_DISABLE_COOKIES
                | WINHTTP_DISABLE_AUTHENTICATION
                | WINHTTP_DISABLE_KEEP_ALIVE
                | WINHTTP_DISABLE_REDIRECTS,
        )
        .map_err(|_| Error::Timeout)?;
        let mut lines = vec![("Accept-Encoding", "identity")];
        lines.extend(asked.headers.iter().copied());
        lines.push(("Connection", "close"));
        for (name, value) in lines {
            if name.contains(['\r', '\n', ':']) || value.contains(['\r', '\n']) {
                return Err(Error::Refused);
            }
            let line: Vec<u16> = format!("{name}: {value}\r\n").encode_utf16().collect();
            WinHttpAddRequestHeaders(
                request.0,
                &line,
                WINHTTP_ADDREQ_FLAG_ADD | WINHTTP_ADDREQ_FLAG_REPLACE,
            )
            .map_err(|_| Error::Refused)?;
        }
        phase(&request, start, asked)?;
        let body = asked.body.unwrap_or(&[]);
        let length = u32::try_from(body.len()).map_err(|_| Error::Refused)?;
        let data = if body.is_empty() {
            None
        } else {
            Some(body.as_ptr().cast::<core::ffi::c_void>())
        };
        WinHttpSendRequest(request.0, None, data, length, length, 0).map_err(|e| fault(&e))?;
        phase(&request, start, asked)?;
        WinHttpReceiveResponse(request.0, std::ptr::null_mut()).map_err(|e| fault(&e))?;
        let mut status: u32 = 0;
        let mut size = std::mem::size_of::<u32>() as u32;
        WinHttpQueryHeaders(
            request.0,
            WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER,
            PCWSTR::null(),
            Some((&mut status as *mut u32).cast()),
            &mut size,
            std::ptr::null_mut(),
        )
        .map_err(|_| Error::Timeout)?;
        let mut read = Vec::new();
        let mut expired = false;
        let mut failed = None;
        while read.len() < asked.most {
            if phase(&request, start, asked).is_err() {
                expired = true;
                break;
            }
            let want = (asked.most - read.len()).min(65536);
            let mut piece = vec![0u8; want];
            let mut got: u32 = 0;
            match WinHttpReadData(request.0, piece.as_mut_ptr().cast(), want as u32, &mut got) {
                Ok(()) if got == 0 => break,
                Ok(()) => read.extend_from_slice(&piece[..got as usize]),
                Err(error) => {
                    if left(start, asked.timeout_ms, asked.whole_ms).is_none() {
                        expired = true;
                    } else {
                        failed = Some(fault(&error));
                    }
                    break;
                }
            }
        }
        Ok(Reply {
            status,
            body: match failed {
                Some(error) => Err(error),
                None => Ok(read),
            },
            expired,
        })
    }
}

/// The courier's one listening socket (`courier/api.py`'s `Server`: `SO_EXCLUSIVEADDRUSE` before `bind`, so no other
/// program can share the port, and `listen(backlog)`): an IPv4 TCP listener on `ip:port` (port 0: any free one).
pub fn exclusive_listener(
    ip: [u8; 4],
    port: u16,
    backlog: i32,
) -> std::io::Result<std::net::TcpListener> {
    use std::os::windows::io::FromRawSocket;
    use windows::Win32::Networking::WinSock::{
        AF_INET, IN_ADDR, IN_ADDR_0, IPPROTO_TCP, SO_EXCLUSIVEADDRUSE, SOCK_STREAM, SOCKADDR,
        SOCKADDR_IN, SOL_SOCKET, WSA_FLAG_NO_HANDLE_INHERIT, WSA_FLAG_OVERLAPPED, WSADATA,
        WSASocketW, WSAStartup, bind, closesocket, listen, setsockopt,
    };
    // SAFETY: Winsock's own calls on a socket this function owns until it is handed to std (or closed on a failure).
    unsafe {
        let mut data = WSADATA::default();
        if WSAStartup(0x0202, &mut data) != 0 {
            return Err(std::io::Error::last_os_error());
        }
        let socket = WSASocketW(
            i32::from(AF_INET.0),
            SOCK_STREAM.0,
            IPPROTO_TCP.0,
            None,
            0,
            WSA_FLAG_OVERLAPPED | WSA_FLAG_NO_HANDLE_INHERIT,
        )
        .map_err(|_| std::io::Error::last_os_error())?;
        let fail = |socket| {
            let error = std::io::Error::last_os_error();
            let _ = closesocket(socket);
            Err(error)
        };
        if setsockopt(
            socket,
            SOL_SOCKET,
            SO_EXCLUSIVEADDRUSE,
            Some(&1i32.to_ne_bytes()),
        ) != 0
        {
            return fail(socket);
        }
        let address = SOCKADDR_IN {
            sin_family: AF_INET,
            sin_port: port.to_be(),
            sin_addr: IN_ADDR {
                S_un: IN_ADDR_0 {
                    S_addr: u32::from_ne_bytes(ip),
                },
            },
            sin_zero: [0; 8],
        };
        if bind(
            socket,
            (&address as *const SOCKADDR_IN).cast::<SOCKADDR>(),
            std::mem::size_of::<SOCKADDR_IN>() as i32,
        ) != 0
        {
            return fail(socket);
        }
        if listen(socket, backlog) != 0 {
            return fail(socket);
        }
        Ok(std::net::TcpListener::from_raw_socket(socket.0 as u64))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{Read, Write};
    use std::net::TcpListener;

    #[test]
    fn the_listening_socket_is_this_process_s_alone() {
        let first = exclusive_listener([127, 0, 0, 1], 0, 8).expect("a loopback port");
        let port = first.local_addr().expect("its address").port();
        assert!(exclusive_listener([127, 0, 0, 1], port, 8).is_err());
        assert!(TcpListener::bind(("127.0.0.1", port)).is_err());
    }

    #[test]
    fn an_address_is_taken_apart_as_winhttp_is_handed_it() {
        assert_eq!(
            target("https://api.example.org/bot1:x/getMe?offset=2"),
            Some(Target {
                secure: true,
                host: "api.example.org".into(),
                port: 443,
                path: "/bot1:x/getMe?offset=2".into()
            })
        );
        assert_eq!(
            target("http://127.0.0.1:8080").map(|t| t.path),
            Some("/".into())
        );
        assert_eq!(target("ftp://example.org/"), None);
        assert_eq!(target("https://user@example.org/"), None);
    }

    #[test]
    fn plain_http_reaches_no_host_but_loopback() {
        let refused = send(&Asked {
            url: "http://10.0.0.1/",
            method: "GET",
            headers: &[],
            body: None,
            timeout_ms: 100,
            whole_ms: 100,
            most: 10,
            secure: false,
        });
        assert_eq!(refused.err(), Some(Error::Refused));
        let mixed = send(&Asked {
            url: "http://127.0.0.1/",
            method: "GET",
            headers: &[],
            body: None,
            timeout_ms: 100,
            whole_ms: 100,
            most: 10,
            secure: true,
        });
        assert_eq!(mixed.err(), Some(Error::Refused));
    }

    #[test]
    fn a_loopback_request_carries_its_headers_and_body_and_reads_no_more_than_asked() {
        let listener = TcpListener::bind("127.0.0.1:0").expect("a loopback port");
        let port = listener.local_addr().expect("its address").port();
        let server = std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("one client");
            stream
                .set_read_timeout(Some(Duration::from_secs(5)))
                .expect("a timeout");
            let mut seen = Vec::new();
            let mut buffer = [0u8; 4096];
            while !seen.windows(4).any(|w| w == b"\r\n\r\n") || !seen.ends_with(b"hello") {
                let got = stream.read(&mut buffer).expect("the request");
                if got == 0 {
                    break;
                }
                seen.extend_from_slice(&buffer[..got]);
            }
            stream
                .write_all(b"HTTP/1.1 201 Created\r\nContent-Length: 10\r\n\r\n0123456789")
                .expect("the answer");
            String::from_utf8_lossy(&seen).into_owned()
        });
        let url = format!("http://127.0.0.1:{port}/in/made-up?x=1");
        let reply = send(&Asked {
            url: &url,
            method: "POST",
            headers: &[("Content-type", "text/plain"), ("User-agent", "probe")],
            body: Some(b"hello"),
            timeout_ms: 5000,
            whole_ms: 8000,
            most: 4,
            secure: false,
        })
        .expect("an answer");
        let seen = server.join().expect("the server");
        assert_eq!(reply.status, 201);
        assert_eq!(reply.body.expect("a body"), b"0123");
        assert!(
            seen.starts_with("POST /in/made-up?x=1 HTTP/1.1\r\n"),
            "{seen}"
        );
        // WinHTTP writes a header it knows under its own spelling (urllib's title case) and in its own order.
        let lower = seen.to_ascii_lowercase();
        for line in [
            "accept-encoding: identity\r\n",
            "content-type: text/plain\r\n",
            "user-agent: probe\r\n",
            "content-length: 5\r\n",
            "connection: close\r\n",
        ] {
            assert!(lower.contains(line), "{line} in {seen}");
        }
        assert!(
            lower.contains(&format!("host: 127.0.0.1:{port}\r\n")),
            "{seen}"
        );
        assert!(seen.ends_with("\r\n\r\nhello"));
    }
}
