# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The resident courier (v0.6.22, plans/v0619-design/D-remote.md): `courier --serve`, the roles that stay while local_api or
telegram_remote stands on - the loopback API (api.py) and Telegram's long poll (telegram.py).

It holds a mutex of its own (`mutex`), not the short-lived courier's: the push drain, the status feed's reading and a
pairing keep their own round as the courier always did (__main__.py), beside a resident that runs for hours - so a
notice is never held behind a server, and a second resident for the same home exits at once. The watcher starts it
(engine/remote.py) only where none answers this mutex (`running`, which opens the mutex and never takes it).

`serve` reads the capabilities' states every CHECK seconds: the API's server is started while local_api stands on - on
127.0.0.1 alone, or on every network while local_api_lan stands on too - and started again when its port or its reach
changes; the long poll runs while telegram_remote stands on; each is closed within CHECK seconds of being turned off, and
with neither on the process ends. Recovery paused changes nothing here: what it serves only reads, and what it does only
reduces (or is the person's own release under telegram_continue).
"""
from __future__ import annotations

import threading
import time

from ..vocabulary import ArmingState, OptionKey

API = "local_api"
API_LAN = "local_api_lan"
TELEGRAM = "telegram_remote"
CHECK = 10                       # seconds between two reads of the states
SYNCHRONIZE = 0x00100000


def mutex(paths, timeout=0):
    """This home's resident mutex: core's named mutex under a name of the resident's own."""
    from codex_auto_resume.win.sync import Mutex
    return Mutex("courier-resident\0" + str(paths.state_dir), timeout=timeout)


def running(paths) -> bool:
    """Whether a resident courier holds this home's mutex now: the mutex opened, never taken (a probe that took it
    would turn a resident starting at that moment away)."""
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.OpenMutexW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenMutexW(SYNCHRONIZE, False, mutex(paths).name)
    if not handle:
        return False
    kernel.CloseHandle(handle)
    return True


class Roles:
    """What the resident runs now, and what it was asked to run. `server` and `poller` are the seams a test fills:
    `server(runtime, port, lan)` returns something with `close()`; `poller(runtime, stop)` runs until `stop` is set."""

    def __init__(self, runtime, *, server=None, poller=None):
        self.runtime = runtime
        self._server_factory = server or _server
        self._poller = poller or _poll
        self.thread, self.stop = None, None
        self.server, self.serving = None, None          # the server, and the (port, lan) it serves on
        self._taken = None                              # the (port, lan) last found taken, journalled once

    def wanted(self) -> tuple:
        """(port or None, lan, telegram): what the states ask for now."""
        states = self.runtime.states(fresh=True)
        api = states.get(API) == ArmingState.ARMED
        port = None
        if api:
            from ..engine.remote import DEFAULT_PORT
            chosen = self.runtime.state.options(API).get(OptionKey.API_PORT, DEFAULT_PORT)
            port = chosen if type(chosen) is int else DEFAULT_PORT
        return port, api and states.get(API_LAN) == ArmingState.ARMED, states.get(TELEGRAM) == ArmingState.ARMED

    def follow(self) -> bool:
        """The roles brought to what the states ask for; whether any is wanted."""
        try:
            port, lan, telegram = self.wanted()
        except Exception:
            port, lan, telegram = None, False, False          # unreadable: nothing is served
        if self.server is not None and self.serving != (port, lan):
            self._close_server()
        if port is not None and self.server is None:
            try:
                self.server = self._server_factory(self.runtime, port, lan)
                self.serving, self._taken = (port, lan), None
                self.runtime.state.counted(API, "started")
            except Exception:
                self.server, self.serving = None, None        # the port is taken: tried again at the next check
                if self._taken != (port, lan):
                    self._taken = (port, lan)
                    self.runtime.state.counted(API, "port_taken")
        if self.thread is not None and (not telegram or not self.thread.is_alive()):
            self._stop_poll()
        if telegram and self.thread is None:
            self.stop = threading.Event()
            self.thread = threading.Thread(target=self._poller, args=(self.runtime, self.stop), daemon=True,
                                           name="telegram")
            self.thread.start()
            self.runtime.state.counted(TELEGRAM, "started")
        return port is not None or telegram

    def _close_server(self) -> None:
        try:
            self.server.close()
        except Exception:
            pass
        self.server, self.serving = None, None
        self.runtime.state.counted(API, "stopped")

    def _stop_poll(self) -> None:
        self.stop.set()
        self.thread.join(timeout=1)                      # a read held open ends by itself and obeys nothing it brought
        self.thread, self.stop = None, None
        self.runtime.state.counted(TELEGRAM, "stopped")

    def close(self) -> None:
        if self.server is not None:
            self._close_server()
        if self.thread is not None:
            self._stop_poll()


def serve(runtime, *, server=None, poller=None, sleep=None, rounds=None) -> int:
    """The resident's life: its roles followed every CHECK seconds until none is wanted (or `rounds` checks, for a
    test). Its exit code."""
    from .__main__ import EXIT_DONE
    sleep = sleep or time.sleep
    roles = Roles(runtime, server=server, poller=poller)
    try:
        count = 0
        while roles.follow():
            count += 1
            if rounds is not None and count >= rounds:
                break
            sleep(CHECK)
    finally:
        roles.close()
    return EXIT_DONE


def _server(runtime, port, lan):
    from . import api
    return api.start(runtime, port, lan)


def _poll(runtime, stop):
    from . import telegram
    telegram.run(runtime, stop)
