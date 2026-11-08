"""The App Server, spoken to for exactly three things and closed again.

A finite separate stdio server, opened for one call and shut: it reads the usage or deletes
one queued message this product itself queued. `PROTOCOL_METHODS` is the whole of what it may
be asked, and `tests/test_privacy_claims.py` holds it to that list.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import queue
import re
import subprocess as S
import threading
import time

from ..win.kernel import NO_WINDOW
from .errors import AdapterError
from .usage import parse_usage


# The only App Server methods the finite helper may call.
PROTOCOL_METHODS = ("initialize", "account/rateLimits/read", "thread/queue/delete")
# The Compatibility Registry's local-check words, which the adapter's own probes answer with.

# v0.6.22: a line up to LINE_LIMIT is parsed whole. A longer one - Codex echoes a message's pictures inline, and one
# phone photo is over a megabyte - is read to its newline LINE_LIMIT at a time keeping only its first and last KEPT
# characters, never the whole line and never json.loads of it; until then such a line ended the reader for good.
LINE_LIMIT = 1024 * 1024
KEPT = 64 * 1024
# The one word an answer too large to keep carries: {"id": n, "result": {OVERSIZE: True}}, or "error" in place of
# "result" (with Codex's numeric code where its head shows one). A caller reads no other field from it.
OVERSIZE = "_oversize"
# What next_message returns for a line that is no message this client reads.
SKIPPED = object()
_DECODER = json.JSONDecoder()
_SPACE = re.compile(r"\s*")
# The top-level id at the very end of a line: Codex writes an error as {"error": {...}, "id": n}, its id last.
_LAST_ID = re.compile(r'"id"\s*:\s*(-?\d+|"(?:[^"\\]|\\.)*")\s*\}\s*$')
_ERROR_CODE = re.compile(r'\{\s*"error"\s*:\s*\{\s*"code"\s*:\s*(-?\d+)\s*[,}]')


def next_message(stream):
    """The next message on a Codex server's stdout: a dict, None at the stream's end, or SKIPPED for a line that is
    no JSON object or an oversize line that is no answer or request. Bounded: one LINE_LIMIT read at a time, linear
    in the line's length, KEPT characters of each end held."""
    line = stream.readline(LINE_LIMIT + 1)
    if not line:
        return None
    if line.endswith("\n") or len(line) <= LINE_LIMIT:
        try:
            value = json.loads(line)
        except ValueError:
            return SKIPPED
        return value if isinstance(value, dict) else SKIPPED
    head, tail, size = line[:KEPT], line[-KEPT:], len(line)
    while True:
        piece = stream.readline(LINE_LIMIT)
        if not piece:
            break
        size += len(piece)
        tail = piece[-KEPT:] if len(piece) >= KEPT else (tail + piece)[-KEPT:]
        if piece.endswith("\n"):
            break
    return _oversize(head, tail, size)


def _members(head):
    """The top-level members of the JSON object `head` begins, as far as it reaches: ({key: value}, the key whose
    value runs past the head or None). A value that ends exactly at the head's end counts as cut."""
    seen = {}
    position = _SPACE.match(head).end()
    if not head.startswith("{", position):
        return seen, None
    position = _SPACE.match(head, position + 1).end()
    while position < len(head):
        try:
            key, position = _DECODER.raw_decode(head, position)
        except (ValueError, RecursionError):
            return seen, None
        position = _SPACE.match(head, position).end()
        if not isinstance(key, str) or not head.startswith(":", position):
            return seen, None
        position = _SPACE.match(head, position + 1).end()
        try:
            value, position = _DECODER.raw_decode(head, position)
        except (ValueError, RecursionError):
            return seen, key
        position = _SPACE.match(head, position).end()
        if position >= len(head):
            return seen, key
        seen[key] = value
        if not head.startswith(",", position):
            return seen, None
        position = _SPACE.match(head, position + 1).end()
    return seen, None


def _oversize(head, tail, size):
    """What an oversize line is, from its head and its tail alone: Codex writes an answer {"id": n, "result": ...}
    with its id first, an error {"error": {...}, "id": n} with its id last, and a request or a notification with its
    method before its params (codex-cli 0.167.0-alpha.3.2's app server, read 2026-11-08). An answer comes back
    carrying OVERSIZE, a request as its id and method alone; a notification, or a line read as none of these, is
    dropped with one line in the log - its method or "unknown", and its size in megabytes."""
    seen, cut = _members(head)
    method = seen.get("method")
    ident = seen.get("id")
    if isinstance(method, str):
        if "id" in seen and type(ident) in (int, str):
            return {"id": ident, "method": method}
        logging.getLogger(__name__).info("a notification of %d MB was not read: %s", -(-size // LINE_LIMIT),
                                         method[:80])
        return SKIPPED
    kind = cut if cut in ("result", "error") else None
    if kind is None:
        kind = next((key for key in ("result", "error") if key in seen), None)
    if kind is not None and "id" not in seen:
        found = _LAST_ID.search(tail)
        if found is not None:
            try:
                ident = json.loads(found.group(1))
            except ValueError:
                ident = None
    if kind is not None and type(ident) in (int, str):
        payload = {OVERSIZE: True}
        if kind == "error":
            code = _ERROR_CODE.match(head)
            if code is not None:
                payload["code"] = int(code.group(1))
        return {"id": ident, kind: payload}
    logging.getLogger(__name__).info("a line of %d MB was not read: unknown", -(-size // LINE_LIMIT))
    return SKIPPED


class Protocol:
    """Finite separate stdio server: reads usage or deletes one owned queue item.

    Never attaches to desktop server, loads a thread, starts a turn, authenticates
    by a custom route or services server requests. Official binary owns auth.
    """
    def __init__(self, backend):
        self.backend = backend
        self.process = None
        self.sequence = 0
        self.responses = queue.Queue(maxsize=64)
        self.write_lock = threading.Lock()

    def __enter__(self):
        self.backend._compatible()
        try:
            self.process = S.Popen(self.backend._argv() + ["app-server", "--stdio"],
                                   stdin=S.PIPE, stdout=S.PIPE, stderr=S.DEVNULL, text=True,
                                   encoding="utf-8", errors="replace", bufsize=1,
                                   creationflags=NO_WINDOW, close_fds=True, shell=False,
                                   cwd=str(self.backend.codex_home), env=self.backend._environment())
            self.reader = threading.Thread(target=self._read, daemon=True)
            self.reader.start()
            # Codex reports clientInfo to OpenAI as the client's identity, so it should be
            # true: this product's real version, read from the manifest like every other
            # version it displays. It said "0.1" for six releases.
            from ..config import version as product_version
            response = self.call("initialize", {"clientInfo": {"name": "codex_auto_resume",
                                                               "version": product_version()},
                                                "capabilities": {"experimentalApi": True}})
            if not isinstance(response, dict) or Path(response.get("codexHome", "")).resolve() != self.backend.codex_home:
                raise AdapterError("protocol_home_mismatch")
            if response.get("platformOs") != "windows":
                raise AdapterError("protocol_platform_mismatch")
            self._write({"method": "initialized"})
            return self
        except BaseException:
            self.__exit__()
            raise

    def _write(self, payload):
        with self.write_lock:
            self.process.stdin.write(json.dumps(payload, ensure_ascii=False, allow_nan=False) + "\n")
            self.process.stdin.flush()

    def _read(self):
        try:
            while True:
                value = next_message(self.process.stdout)
                if value is None:
                    return
                if value is SKIPPED:
                    continue
                if "id" in value and "method" in value:
                    self._write({"id": value["id"], "error": {"code": -32601, "message": "Client requests unsupported"}})
                elif "id" in value and ("result" in value or "error" in value):
                    try:
                        self.responses.put_nowait(value)
                    except queue.Full:
                        return
        except (OSError, ValueError):
            return

    def call(self, method, params=None):
        if method not in PROTOCOL_METHODS:
            raise AdapterError("protocol_method_not_allowed")
        self.sequence += 1
        sequence = self.sequence
        request = {"id": sequence, "method": method}
        if params is not None:
            request["params"] = params
        try:
            self._write(request)
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                response = self.responses.get(timeout=max(0.01, deadline - time.monotonic()))
                if response.get("id") != sequence:
                    continue
                if "error" in response:
                    raise AdapterError("protocol_request_failed")
                return response.get("result")
        except (queue.Empty, OSError, ValueError):
            raise AdapterError("protocol_unavailable") from None
        raise AdapterError("protocol_timeout")

    def __exit__(self, *unused):
        process = self.process
        if process is None:
            return
        try:
            if process.stdin:
                try:
                    process.stdin.close()
                except OSError:
                    pass
            try:
                process.wait(timeout=4)
            except S.TimeoutExpired:
                process.terminate()  # only our own finite helper
                try:
                    process.wait(timeout=4)
                except S.TimeoutExpired:
                    pass    # v0.6.18: never raised from here - a delete that worked stays reported as worked
        finally:
            if hasattr(self, "reader"):
                self.reader.join(timeout=1)
            if process.stdout:
                process.stdout.close()
