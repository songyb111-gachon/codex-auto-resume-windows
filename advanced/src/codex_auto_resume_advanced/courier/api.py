# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The loopback API and web view (local_api, v0.6.22, plans/v0619-design/D-remote.md): the one listening socket of this
product, in the resident courier alone (resident.py) and only while local_api stands on.

It binds to 127.0.0.1 and the port chosen (47615 by default) - to every network only while local_api_lan stands on too;
Windows asks about its firewall then, and nothing here touches a firewall rule. Every route is in ROUTES:

    GET  /             the web view (page.py): no data in it, so no token asked; its script asks the rest
    GET  /status.json  the status file's document (core's statusfile: its closed keys)
    GET  /metrics      the same, as Prometheus' text
    GET  /pending      the waiting recoveries as `task N`, their public state and next check, and the list's snapshot
    POST /pause        recovery paused (local_api_actions)
    POST /resume-off   the same: there is no remote resume (local_api_actions)
    POST /cancel/N     one waiting recovery cancelled by its place on the list, {"snapshot": ...} the list it was read
                       on - refused 409 "list_again" where the list has changed (local_api_actions)

Nothing else: no route sends, chats, changes a setting, turns a feature on or off, sends now or gives attempts back
(a test holds ROUTES to the design's table). Each request, in this order: closed for five minutes after LOCK_AFTER
wrong tokens in LOCK_WINDOW seconds (503); exactly one Host header, 127.0.0.1:<port> or localhost:<port> - or, open to
the network, an IPv4 address with the port - so a web page served under another name (DNS rebinding) is refused 421;
an unknown path is 404 and a method a route does not take 405; every route but `/` needs `Authorization: Bearer
<token>` (local_api's token in Windows Credential Manager, compared in constant time) or is 401 - and only a Bearer token
offered and wrong counts towards the lock, so a request with none, which any web page can make, never closes it; an action while
local_api_actions does not stand on is 403; a body over MAX_BODY is 413. No answer carries a CORS header, a cookie or a
server's version, and a query string is never read: the token never travels in an address. Requests are served by at
most THREADS threads at a time; each read waits TIMEOUT seconds at most, and each request, from its connection to its
answer, has DEADLINE seconds in all - then its connection is shut - and after its answer LINGER_SECONDS more in all, so a
few clients that trickle a byte at a time cannot hold every slot, before the answer or after it. Nothing is logged: not a
request, not an address, not a failure.
"""
from __future__ import annotations

import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import re
import socket
import threading
import time

from ..vocabulary import ArmingState

API = "local_api"
API_ACTIONS = "local_api_actions"
LOOPBACK = "127.0.0.1"
EVERYWHERE = "0.0.0.0"
MAX_BODY = 1024
THREADS = 8
TIMEOUT = 10                       # seconds one read may wait
DEADLINE = 10                      # seconds one request may take in all, its connection to its answer
LINGER_SECONDS = 1.0               # after its answer, how long in all a connection waits for what the client still sends
LINGER_BYTES = 64 * 1024           # and how much of that it reads and drops, at most
LOCK_AFTER, LOCK_WINDOW, LOCK_SECONDS = 10, 60, 300
# Every route, with the methods it takes and whether it changes anything (an action, local_api_actions'). A test holds
# this table to the design's: reads and reduce-actions, nothing else.
ROUTES = {"/": ("GET", False), "/status.json": ("GET", False), "/metrics": ("GET", False),
          "/pending": ("GET", False), "/pause": ("POST", True), "/resume-off": ("POST", True),
          "/cancel/": ("POST", True)}
CANCEL = re.compile(r"/cancel/([1-9][0-9]{0,3})\Z")
JSON = "application/json; charset=utf-8"


class Service:
    """What a request is answered from: the token, whether the actions stand on, and the control layer's reads and
    reduce-actions (control/remote.py). `layer`, `secrets` and `clock` are the seams a test fills."""

    def __init__(self, runtime, port, lan, *, layer=None, secrets=None, clock=None):
        from ..control import remote
        self.runtime, self.port, self.lan = runtime, port, bool(lan)
        self._remote = remote
        self._layer = layer
        self._secrets = secrets
        self.clock = clock or time.time

    @property
    def layer(self):
        if self._layer is None:
            self._layer = self._remote.control(self.runtime.paths)
        return self._layer

    def token(self):
        from ..credentials import Secrets
        try:
            found = (self._secrets or Secrets(self.runtime.registry)).read(API, self._remote.TOKEN)
        except Exception:
            return None
        return found if isinstance(found, str) and found else None

    def actions_on(self) -> bool:
        try:
            return self.runtime.states(fresh=True).get(API_ACTIONS) == ArmingState.ARMED
        except Exception:
            return False

    def status(self) -> dict:
        return self._remote.status_document(self.layer, self.clock())

    def metrics(self) -> str:
        return self._remote.metrics(self.status())

    def pending(self) -> dict:
        return self._remote.pending(self.layer)

    def pause(self) -> dict:
        found = self._remote.pause(self.layer)
        self.runtime.state.counted(API_ACTIONS, "paused")
        return found

    def cancel(self, alias, listed) -> dict:
        try:
            found = self._remote.cancel(self.layer, alias, listed)
        except self._remote.Stale:
            self.runtime.state.counted(API_ACTIONS, "list_again")
            raise
        self.runtime.state.counted(API_ACTIONS, "cancelled")
        return found

    def page(self) -> bytes:
        from codex_auto_resume import l10n
        from ..statement import CATALOGS
        from .page import render
        locale = l10n.current()
        return render(CATALOGS.catalog(locale), locale)

    def locked(self) -> None:
        self.runtime.state.counted(API, "locked")


class Gate:
    """The wrong tokens counted, and the five minutes closed after LOCK_AFTER of them in LOCK_WINDOW seconds."""

    def __init__(self, clock):
        self.clock = clock
        self._wrong, self._until = [], 0.0
        self._lock = threading.Lock()

    def closed(self) -> bool:
        return self.clock() < self._until

    def wrong(self) -> bool:
        """One wrong token counted; whether that closed it."""
        now = self.clock()
        with self._lock:
            self._wrong = [at for at in self._wrong if 0 <= now - at < LOCK_WINDOW] + [now]
            if len(self._wrong) >= LOCK_AFTER:
                self._wrong, self._until = [], now + LOCK_SECONDS
                return True
        return False


def host_allowed(header, port, lan) -> bool:
    """Whether a Host header names this server as itself: 127.0.0.1 or localhost with its port - or, open to the
    network, an IPv4 address with its port. Any other name is a page served under it (DNS rebinding)."""
    if not isinstance(header, str) or not header.endswith(":%d" % port):
        return False
    name = header[:-len(":%d" % port)].lower()
    if name in (LOOPBACK, "localhost"):
        return True
    if not lan:
        return False
    try:
        return isinstance(ipaddress.ip_address(name), ipaddress.IPv4Address)
    except ValueError:
        return False


def route_of(path):
    """The ROUTES key of `path` (its query string never read), or None."""
    path = path.split("?", 1)[0].split("#", 1)[0]
    if path in ROUTES and path != "/cancel/":
        return path
    return "/cancel/" if CANCEL.match(path) else None


class Handler(BaseHTTPRequestHandler):
    """One request, as the module says. `server.service` and `server.gate` answer it."""
    server_version = "codex-auto-resume"
    sys_version = ""
    protocol_version = "HTTP/1.0"
    timeout = TIMEOUT

    def setup(self):
        super().setup()
        self._deadline = threading.Timer(DEADLINE, self._expire)
        self._deadline.daemon = True
        self._deadline.start()

    def _expire(self):
        """The request's time is up: its connection is shut, so a read that waits returns and its slot is free."""
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def finish(self):
        self._deadline.cancel()
        try:
            super().finish()
        except OSError:
            pass
        self._linger()

    def _linger(self):
        """The answer ends here, and what the client sent that was not read is read and dropped before the socket is
        closed. A refusal (401, 404, 405, 413) answers on the headers alone, and a body that is unread or still on its way
        to a socket already closed resets the connection: a client that has not read the answer yet loses it. Bounded
        both ways, and in all from the answer: LINGER_SECONDS of waiting in total, not for each read (S1, the second
        security review of v0.6.23: one byte a second kept a slot for hours), and LINGER_BYTES - so a client holds its
        slot past its answer for a moment only, whatever it sends."""
        try:
            self.connection.shutdown(socket.SHUT_WR)
            end = time.monotonic() + LINGER_SECONDS
            left = LINGER_BYTES
            while left > 0:
                wait = end - time.monotonic()
                if wait <= 0:
                    break
                self.connection.settimeout(wait)
                got = self.connection.recv(min(left, 4096))
                if not got:
                    break
                left -= len(got)
        except OSError:
            pass

    def log_message(self, *unused):            # nothing is logged: an address can carry a token by mistake
        return

    def version_string(self):
        return self.server_version

    def _answer(self, status, body=b"", kind=JSON, extra=None):
        if isinstance(body, dict):
            body = json.dumps(body, separators=(",", ":"), allow_nan=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _refuse(self, status, word, extra=None):
        self._answer(status, {"error": word}, extra=extra)

    def send_error(self, code, message=None, explain=None):
        """What http.server itself refuses - a request line that cannot be read, an unknown method: one closed word, the
        request never echoed."""
        self.close_connection = True
        self._refuse(code, "bad_request")

    def _offered(self) -> bool:
        """Whether the request offers a Bearer token at all: one that does not is refused and never counted."""
        given = self.headers.get("Authorization") or ""
        return given.startswith("Bearer ") and len(given) > len("Bearer ")

    def _authorized(self, service) -> bool:
        token = service.token()
        given = self.headers.get("Authorization") or ""
        if token is None or not given.startswith("Bearer "):
            return False
        return hmac.compare_digest(given[len("Bearer "):].encode("utf-8", "replace"), token.encode("utf-8"))

    def _handle(self):
        service, gate = self.server.service, self.server.gate
        if gate.closed():
            return self._refuse(503, "locked", {"Retry-After": str(LOCK_SECONDS)})
        hosts = self.headers.get_all("Host") or []
        if len(hosts) != 1 or not host_allowed(hosts[0], service.port, service.lan):
            return self._refuse(421, "misdirected")
        route = route_of(self.path)
        if route is None:
            return self._refuse(404, "not_found")
        method, action = ROUTES[route]
        if self.command != method:
            return self._refuse(405, "method", {"Allow": method})
        if route == "/":
            from .page import CSP
            try:
                page = service.page()
            except Exception:
                return self._refuse(503, "unavailable")
            return self._answer(200, page, "text/html; charset=utf-8", {"Content-Security-Policy": CSP})
        if not self._authorized(service):
            if self._offered() and gate.wrong():
                service.locked()
            return self._refuse(401, "unauthorized", {"WWW-Authenticate": "Bearer"})
        body = b""
        if action:
            if not service.actions_on():
                return self._refuse(403, "not_on")
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return self._refuse(400, "length")
            if length < 0 or length > MAX_BODY:
                return self._refuse(413, "too_large")
            body = self.rfile.read(length) if length else b""
        try:
            if route == "/status.json":
                return self._answer(200, service.status())
            if route == "/metrics":
                return self._answer(200, service.metrics(), "text/plain; version=0.0.4; charset=utf-8")
            if route == "/pending":
                return self._answer(200, service.pending())
            if route in ("/pause", "/resume-off"):
                return self._answer(200, service.pause())
            return self._cancel(service, body)
        except Exception:
            return self._refuse(503, "unavailable")

    def _cancel(self, service, body):
        from ..control.remote import Stale
        try:
            listed = json.loads(body.decode("utf-8")).get("snapshot") if body else None
        except (ValueError, UnicodeDecodeError, AttributeError):
            return self._refuse(400, "body")
        alias = "task %s" % CANCEL.match(self.path.split("?", 1)[0]).group(1)
        try:
            return self._answer(200, service.cancel(alias, listed))
        except Stale:
            return self._refuse(409, "list_again")

    # Every method a request may name goes the one way: closed, Host, 404, 405 - so a preflight gets a refusal and no CORS.
    do_GET = do_POST = do_HEAD = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_TRACE = do_CONNECT = _handle


class Server(ThreadingHTTPServer):
    """The loopback server: at most THREADS requests at once - one more is closed unanswered - its socket bound for
    this process alone (no address reuse another program could share)."""
    daemon_threads = True
    allow_reuse_address = False
    request_queue_size = THREADS

    def __init__(self, address, service, gate):
        self.service, self.gate = service, gate
        self._slots = threading.BoundedSemaphore(THREADS)
        super().__init__(address, Handler)

    def server_bind(self):
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive is not None:
            self.socket.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        super().server_bind()

    def handle_error(self, request, client_address):
        """Nothing is logged: socketserver would print the client's address and a traceback."""

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        super().process_request(request, client_address)

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


class Running:
    """A server serving on its own thread, until `close`."""

    def __init__(self, server):
        self.server = server
        self.thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.5}, daemon=True,
                                       name="local-api")
        self.thread.start()
        self.addresses = []                 # this PC's own addresses it answers on beyond 127.0.0.1 (`lan_addresses`)

    @property
    def port(self) -> int:
        return self.server.server_address[1]

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def lan_addresses() -> list:
    """This PC's own IPv4 addresses on its networks, as Windows resolves its own name - no request leaves the PC -
    loopback, link-local, multicast and unspecified ones left out, at most four, in the order Windows gives them."""
    found = []
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except (OSError, UnicodeError):
        return []
    for info in infos:
        try:
            address = ipaddress.IPv4Address(info[4][0])
        except (ValueError, IndexError, TypeError):
            continue
        if address.is_loopback or address.is_link_local or address.is_unspecified or address.is_multicast:
            continue
        if str(address) not in found:
            found.append(str(address))
    return found[:4]


def bind_address(lan) -> str:
    """127.0.0.1 - or every network, while local_api_lan stands on."""
    return EVERYWHERE if lan else LOOPBACK


def start(runtime, port, lan, *, service=None, clock=None) -> Running:
    """The server started on `port` (0 for any free one, a test's) - OSError where it is taken."""
    clock = clock or time.time
    service = service or Service(runtime, port, lan, clock=clock)
    server = Server((bind_address(lan), port), service, Gate(clock))
    if not port:
        service.port = server.server_address[1]
    running = Running(server)
    if lan:
        running.addresses = lan_addresses()        # recorded by the resident for the card (control/remote.py)
    return running
