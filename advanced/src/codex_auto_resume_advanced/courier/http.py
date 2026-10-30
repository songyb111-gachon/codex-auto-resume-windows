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
"""
from __future__ import annotations

import socket
import ssl
import urllib.error
import urllib.request

from .address import checked_url

TIMEOUT = 10                       # seconds, every request
MAX_BODY = 4096                    # bytes a push may carry
MAX_REPLY = 65536                  # bytes of a reply read, at most; the rest is never read
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


def make_opener():
    """urllib's opener for every courier request: verification on, redirects refused."""
    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=context()), _NoRedirect())


def _class(status) -> str:
    return "2xx" if 200 <= status < 300 else "5xx" if status >= 500 else "4xx"


def request(url, body=None, headers=None, *, method="POST", timeout=TIMEOUT, opener=None) -> bytes:
    """One request to `url`; what the service answered, at most MAX_REPLY bytes, for a 2xx. Failed otherwise, and
    address.AddressRefused for an address no push may go to - before anything is sent."""
    checked_url(url)
    if body is not None and (not isinstance(body, bytes) or len(body) > MAX_BODY):
        raise ValueError("body")
    made = urllib.request.Request(url, data=body, method=method,
                                  headers=dict(headers or {}, **{"User-Agent": USER_AGENT}))
    try:
        reply = (opener or make_opener()).open(made, timeout=timeout)
    except urllib.error.HTTPError as exc:
        status = exc.code if isinstance(exc.code, int) else 0
        try:
            exc.close()
        except Exception:
            pass
        raise Failed("5xx" if status >= 500 else "4xx", status) from None
    except urllib.error.URLError as exc:
        raise Failed("tls" if isinstance(exc.reason, (ssl.SSLError, ssl.CertificateError)) else "timeout") from None
    except (ssl.SSLError, ssl.CertificateError):
        raise Failed("tls") from None
    except (socket.timeout, TimeoutError, OSError):
        raise Failed("timeout") from None
    try:
        status = getattr(reply, "status", None)
        status = status if isinstance(status, int) else 200
        if _class(status) != "2xx":
            raise Failed(_class(status), status)
        return reply.read(MAX_REPLY)
    except (socket.timeout, TimeoutError):
        raise Failed("timeout") from None
    except OSError:
        raise Failed("timeout") from None
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


def get(url, *, timeout=TIMEOUT, opener=None, headers=None) -> bytes:
    """GET `url`: what it answered, at most MAX_REPLY bytes; Failed otherwise."""
    return request(url, None, headers, method="GET", timeout=timeout, opener=opener)
