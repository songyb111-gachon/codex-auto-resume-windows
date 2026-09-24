"""The App Server, spoken to for exactly three things and closed again.

A finite separate stdio server, opened for one call and shut: it reads the usage or deletes
one queued message this product itself queued. `PROTOCOL_METHODS` is the whole of what it may
be asked, and `tests/test_privacy_claims.py` holds it to that list.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import subprocess as S
import threading
import time

from ..win.kernel import NO_WINDOW
from .errors import AdapterError
from .usage import parse_usage


# The only App Server methods the finite helper may call.
PROTOCOL_METHODS = ("initialize", "account/rateLimits/read", "thread/queue/delete")
# The Compatibility Registry's local-check words, which the adapter's own probes answer with.


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
                line = self.process.stdout.readline(1024 * 1024 + 1)
                if not line or len(line) > 1024 * 1024:
                    return
                try:
                    value = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(value, dict):
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
                process.wait(timeout=4)
        finally:
            if hasattr(self, "reader"):
                self.reader.join(timeout=1)
            if process.stdout:
                process.stdout.close()
