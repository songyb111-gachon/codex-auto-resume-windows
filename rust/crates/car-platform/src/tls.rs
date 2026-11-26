//! The advanced courier's TLS over a socket of its own (seat S7.3b): SMTP on 465 (TLS from the start) and 587
//! (STARTTLS), which WinHTTP cannot do. The owner's Q4 (a): the `schannel` crate (MIT), the system's own TLS - never
//! written by hand.
//!
//! A client session only: the server's certificate checked against the system's store and its name against `host`
//! (schannel's defaults, never turned off), TLS 1.2 or later (1.3 where this Windows has it). The standard binaries link
//! none of it (standard C2).

use std::io::{Read, Write};

use schannel::schannel_cred::{Direction, Protocol, SchannelCred};
use schannel::tls_stream::{Builder, HandshakeError, TlsStream};

/// A TLS session over `S`.
pub type Session<S> = TlsStream<S>;

/// Why a session could not be had.
#[derive(Debug)]
pub enum Error {
    /// The secure connection refused: the certificate, its name, or the handshake. Never downgraded.
    Tls(std::io::Error),
    /// The stream failed under the handshake (a timeout, a reset): no answer.
    Io(std::io::Error),
}

fn credentials() -> std::io::Result<SchannelCred> {
    SchannelCred::builder()
        .enabled_protocols(&[Protocol::Tls12, Protocol::Tls13])
        .acquire(Direction::Outbound)
        .or_else(|_| {
            SchannelCred::builder()
                .enabled_protocols(&[Protocol::Tls12])
                .acquire(Direction::Outbound)
        })
}

/// A client session over `stream` to `host`, its certificate verified.
pub fn client<S: Read + Write>(stream: S, host: &str) -> Result<Session<S>, Error> {
    let credentials = credentials().map_err(Error::Tls)?;
    match Builder::new().domain(host).connect(credentials, stream) {
        Ok(session) => Ok(session),
        Err(HandshakeError::Failure(error)) => {
            if matches!(
                error.kind(),
                std::io::ErrorKind::TimedOut
                    | std::io::ErrorKind::WouldBlock
                    | std::io::ErrorKind::ConnectionReset
                    | std::io::ErrorKind::ConnectionAborted
                    | std::io::ErrorKind::UnexpectedEof
            ) {
                Err(Error::Io(error))
            } else {
                Err(Error::Tls(error))
            }
        }
        Err(HandshakeError::Interrupted(_)) => Err(Error::Io(std::io::Error::from(
            std::io::ErrorKind::WouldBlock,
        ))),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::{TcpListener, TcpStream};
    use std::time::Duration;

    #[test]
    fn a_server_that_speaks_no_tls_is_a_refused_session() {
        let listener = TcpListener::bind("127.0.0.1:0").expect("a loopback port");
        let port = listener.local_addr().expect("its address").port();
        let server = std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("one client");
            let mut hello = [0u8; 512];
            let _ = stream.read(&mut hello);
            let _ = stream.write_all(b"220 not a TLS server at all\r\n");
        });
        let stream = TcpStream::connect(("127.0.0.1", port)).expect("connected");
        stream
            .set_read_timeout(Some(Duration::from_secs(5)))
            .expect("a timeout");
        let made = client(stream, "smtp.example.org");
        assert!(made.is_err());
        server.join().expect("the server");
    }
}
