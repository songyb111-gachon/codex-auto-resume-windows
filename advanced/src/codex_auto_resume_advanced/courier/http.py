# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The courier's one way to an HTTPS service: `request`, and `post` and `get` on top of it.

Every request is urllib's, with `ssl.create_default_context()` - Windows' certificate store, the host name checked,
TLS 1.2 or later - and no redirect followed: a 3xx is a refusal, like a 4xx, never a second request somewhere else.
The address is checked first (address.checked_url): https only, no user name or password in it, no IP literal and no
loopback name. A body is at most MAX_BODY bytes; a reply is read up to MAX_REPLY bytes and no further. A request that
fails says how in one closed word - the status class a journal line keeps (STATUS_CLASSES) - and never the address,
the body or what the service answered: a service's error text can echo a token, and the journal is no place for one.

`opener` is the seam a test fills: anything with `open(request, timeout=)` returning a reply with `status` and
`read(n)`, or raising as urllib raises. No test reaches the network.

`stream` (v0.6.23, python_choice) hands a large reply over in pieces, to a caller that bounds it (pythonorg.py); `most`
lets one that knows a longer answer is due, and bounds that, read more than MAX_REPLY.

A timeout is urllib's, for each read; every `request` also has its timeout plus WHOLE_MORE seconds in all, from its
connection to the last byte read, and then its connection is shut (S1, the second security review of v0.6.23: a
service that sends a byte just inside each read's timeout - Telegram's getUpdates waits 60 s a read - would hold the
courier's poll for weeks). `stream` keeps the timeout for each read alone: a download takes as long as the line it
comes down, its progress is real, and its size is bounded by its caller.
"""
from __future__ import annotations

import http.client
import socket
import ssl
import threading
import urllib.error
import urllib.request

from .address import checked_url

TIMEOUT = 10                       # seconds, every request
WHOLE_MORE = 10                    # seconds a request may take in all beyond its timeout (connecting, sending, reading)
MAX_BODY = 4096                    # bytes a push may carry
MAX_REPLY = 65536                  # bytes of a reply read, at most; the rest is never read
STREAM_PIECE = 65536               # bytes `stream` asks for at a time
# What came of a request, as the journal keeps it: answered well, refused (a 3xx or 4xx), the service's own failure, no
# answer in time (or no way there at all), or the secure connection refused - a certificate that does not verify, which
# is never downgraded.
STATUS_CLASSES = ("2xx", "4xx", "5xx", "timeout", "tls")
USER_AGENT = "codex-auto-resume-advanced-courier"


class Failed(Exception):
    """A request that did not answer well. `word` is its status class (STATUS_CLASSES), `status` the HTTP status where
    the service answered one; nothing else is kept."""

    def __init__(self, word, status=None):
        self.word, self.status = word, status
        super().__init__(word)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A 3xx is answered as it is: urllib then raises it as an HTTPError, which `request` counts as a refusal."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def context() -> ssl.SSLContext:
    made = ssl.create_default_context()
    made.minimum_version = ssl.TLSVersion.TLSv1_2
    return made


class _Whole:
    """One request's time in all: when it is up, the connection's socket is shut both ways, so a read that waits returns
    at once whatever the service still sends, and `expired` says so."""

    def __init__(self, seconds):
        self.expired = False
        self._sock = None
        self._lock = threading.Lock()
        self._timer = threading.Timer(seconds, self._shut)
        self._timer.daemon = True
        self._timer.start()

    def hold(self, sock) -> None:
        with self._lock:
            self._sock = sock
            expired = self.expired
        if expired:
            self._shut()

    def _shut(self) -> None:
        with self._lock:
            self.expired = True
            sock = self._sock
        if sock is not None:
            try:                               # the socket's own shutdown: an SSLSocket's would drop its TLS state too
                socket.socket.shutdown(sock, socket.SHUT_RDWR)
            except (OSError, ValueError):
                pass

    def cancel(self) -> None:
        self._timer.cancel()


class _WholeConnection:
    """An HTTP connection whose request has its timeout plus WHOLE_MORE seconds in all, from the connection's making.
    The reply it gives carries the `_Whole` as `whole`, so `request` can stop its clock and tell a cut reply."""

    def __init__(self, *arguments, **keywords):
        super().__init__(*arguments, **keywords)
        seconds = self.timeout
        self.whole = _Whole(seconds + WHOLE_MORE) if isinstance(seconds, (int, float)) and seconds > 0 else None

    def connect(self):
        super().connect()
        if self.whole is not None:
            self.whole.hold(self.sock)

    def getresponse(self):
        try:
            reply = super().getresponse()
        except BaseException:
            if self.whole is not None:
                self.whole.cancel()
            raise
        reply.whole = self.whole
        return reply


class _WholeHTTPS(_WholeConnection, http.client.HTTPSConnection):
    """The courier's HTTPS connection: every request through `request` is made on one."""


class _Handler(urllib.request.HTTPSHandler):
    """urllib's HTTPS handler, its connections `_WholeHTTPS` - or urllib's own for `stream`."""

    def __init__(self, *, whole=True, **keywords):
        super().__init__(**keywords)
        self._connection = _WholeHTTPS if whole else http.client.HTTPSConnection

    def https_open(self, req):
        return self.do_open(self._connection, req, context=self._context)


def make_opener(*, whole=True):
    """urllib's opener for every courier request: verification on, redirects refused - and, but for `stream`, the
    request's time in all bounded (WHOLE_MORE)."""
    return urllib.request.build_opener(_Handler(context=context(), whole=whole), _NoRedirect())


def _stop(reply) -> bool:
    """The reply's clock stopped; whether its time ran out before (what was read may be cut)."""
    whole = getattr(reply, "whole", None)
    if not isinstance(whole, _Whole):
        return False
    whole.cancel()
    return whole.expired


def _class(status) -> str:
    return "2xx" if 200 <= status < 300 else "5xx" if status >= 500 else "4xx"


def _opened(url, body, headers, method, timeout, opener, whole=True):
    """The reply to one request, checked and sent as `request` says; raises as it does."""
    checked_url(url)
    if body is not None and (not isinstance(body, bytes) or len(body) > MAX_BODY):
        raise ValueError("body")
    made = urllib.request.Request(url, data=body, method=method,
                                  headers=dict(headers or {}, **{"User-Agent": USER_AGENT}))
    try:
        reply = (opener or make_opener(whole=whole)).open(made, timeout=timeout)
    except urllib.error.HTTPError as exc:
        status = exc.code if isinstance(exc.code, int) else 0
        _stop(getattr(exc, "fp", None))
        try:
            exc.close()
        except Exception:
            pass
        raise Failed("5xx" if status >= 500 else "4xx", status) from None
    except urllib.error.URLError as exc:
        raise Failed("tls" if isinstance(exc.reason, (ssl.SSLError, ssl.CertificateError)) else "timeout") from None
    except (ssl.SSLError, ssl.CertificateError):
        raise Failed("tls") from None
    except (socket.timeout, TimeoutError, OSError, http.client.HTTPException):
        raise Failed("timeout") from None              # HTTPException: a status line or headers cut when the time ran out
    return reply


def _well(reply) -> None:
    status = getattr(reply, "status", None)
    status = status if isinstance(status, int) else 200
    if _class(status) != "2xx":
        raise Failed(_class(status), status)


def request(url, body=None, headers=None, *, method="POST", timeout=TIMEOUT, opener=None, most=MAX_REPLY) -> bytes:
    """One request to `url`; what the service answered, at most `most` bytes, for a 2xx. Failed otherwise, and
    address.AddressRefused for an address no push may go to - before anything is sent."""
    reply = _opened(url, body, headers, method, timeout, opener)
    try:
        _well(reply)
        read = reply.read(most)
    except (socket.timeout, TimeoutError, OSError, http.client.HTTPException):
        _stop(reply)
        raise Failed("timeout") from None
    except BaseException:
        _stop(reply)
        raise
    else:
        if _stop(reply):                                # the time in all ran out: what was read is cut
            raise Failed("timeout")
        return read
    finally:
        close = getattr(reply, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass


def post(url, body, headers, *, timeout=TIMEOUT, opener=None) -> str:
    """POST `body` to `url`: "2xx", or Failed. What the service answered is read (to MAX_REPLY) and dropped."""
    request(url, body, headers, method="POST", timeout=timeout, opener=opener)
    return "2xx"


def get(url, *, timeout=TIMEOUT, opener=None, headers=None, most=MAX_REPLY) -> bytes:
    """GET `url`: what it answered, at most `most` bytes; Failed otherwise."""
    return request(url, None, headers, method="GET", timeout=timeout, opener=opener, most=most)


def stream(url, take, *, timeout=TIMEOUT, opener=None, piece=STREAM_PIECE) -> None:
    """GET `url`, handing `take` each piece of a 2xx answer as it arrives; `take` bounds it, by raising. Failed otherwise."""
    reply = _opened(url, None, None, "GET", timeout, opener, whole=False)
    try:
        _well(reply)
        while True:
            read = reply.read(piece)
            if not read:
                return
            take(read)
    except (socket.timeout, TimeoutError):
        raise Failed("timeout") from None
    except ssl.SSLError:
        raise Failed("tls") from None
    finally:
        close = getattr(reply, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass
