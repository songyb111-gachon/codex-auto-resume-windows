# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Codex's own retry settings (item 6 of stage 4) - by a provider of our own, on our own server only (v0.6.22).

How many times Codex retries a failed request and a dropped reply stream is two settings of its provider,
`request_max_retries` and `stream_max_retries` (4 and 5 by its documentation). MB measured that Codex refuses any write
under its built-in `model_providers.openai` (config/value/write, -32600, "reserved built-in provider IDs" - codex-cli
0.162.0-alpha.17.2 and 0.166.0-alpha.5.1); that route stays MB's record.

The route here (plans/v0622-retry-settings-design.md, the owner's decision of 2026-11-01): a provider of our own,
PROVIDER, that copies the built-in one for a ChatGPT sign-in - its base URL, the responses wire, Codex's own sign-in -
with both retry settings at the person's Attempts (6, 8, 10 or 12; 8 by default), and `model_provider` naming it. It
is never written to Codex's configuration: it is a set of `-c` settings (`overrides`) the app server this product
starts for its own turns takes (codex/headless.live_session - headless_run, compact_continue, model_fallback), so the
person's app, terminal and editor never see it, and there is nothing to put back - turned off, crashed, uninstalled or
with Codex updated, the next server simply starts without it.

It fails closed (`fits`): only on a ChatGPT sign-in, with `model_provider` unset or Codex's own `openai`, no
`openai_base_url`, and no provider of PROVIDER's id of the person's own; anything else, or a read that failed, and no
setting is given. The P8 tick looks again whether it fits at most once a LOOK_SECONDS - one look on our own server,
config/read and account/read - and renews the setting (`in_force`, held in codex/headless.py); one not renewed for
FRESH_SECONDS lapses, so a capability turned off stops giving it within that time.

Hidden until MB2 passes on the Codex in force (registry.WAITING): until then nothing calls this but its tests.
"""
from __future__ import annotations

import time

from codex_auto_resume.domain.plug import DEFER

from ..codex import headless
from ..codex.account import parse as parse_account
from ..vocabulary import OptionKey

CAPABILITY = "codex_retry_settings"
ATTEMPTS = (6, 8, 10, 12, 16, 20)
DEFAULT_ATTEMPTS = 8
# Our provider's id: never a built-in one (openai, ollama, lmstudio are reserved), and one a person is unlikely to own.
PROVIDER = "codex_auto_resume_retries"
# The built-in provider's base URL for a ChatGPT sign-in (Codex's config reference: openai_base_url overrides it).
CHATGPT_BASE_URL = "https://chatgpt.com/backend-api/codex"
BUILT_IN = "openai"
LOOK_SECONDS = 600.0      # how often the tick looks again whether the provider fits
FRESH_SECONDS = 180.0     # how long a setting not renewed by the tick stays in force
READ, ACCOUNT = "config/read", "account/read"


def _toml(value) -> str:
    """`value` as a TOML literal for a `-c key=value` setting: a bool, an int, or a plain string."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str) and all(ch.isprintable() and ch not in '"\\' for ch in value):
        return '"%s"' % value
    raise ValueError("not a value a setting takes")


def overrides(attempts) -> tuple:
    """The `-c` settings that make our server's turns use PROVIDER with both retries at `attempts`: ((key, value), ...)
    as codex/protocol.Session's `config` takes them. Pure; refuses an Attempts it does not offer."""
    if attempts not in ATTEMPTS or isinstance(attempts, bool):
        raise ValueError("an Attempts this capability does not offer")
    entry = (("name", "OpenAI"), ("base_url", CHATGPT_BASE_URL), ("wire_api", "responses"),
             ("requires_openai_auth", True), ("request_max_retries", attempts), ("stream_max_retries", attempts))
    return tuple(("model_providers.%s.%s" % (PROVIDER, key), _toml(value)) for key, value in entry) + (
        ("model_provider", _toml(PROVIDER)),)


def _config(read):
    found = read.get("config") if isinstance(read, dict) else None
    return found if isinstance(found, dict) else None


def fits(config_read, account_read) -> bool:
    """Whether PROVIDER is a true copy of what the person's Codex uses: a ChatGPT sign-in, `model_provider` unset or the
    built-in `openai`, no `openai_base_url`, and no provider of PROVIDER's id already there. Any read that is not one
    Codex gives is a no. Pure."""
    config = _config(config_read)
    if config is None:
        return False
    if config.get("model_provider") not in (None, BUILT_IN):
        return False
    if config.get("openai_base_url") is not None:
        return False
    providers = config.get("model_providers")
    if providers is not None and (not isinstance(providers, dict) or PROVIDER in providers):
        return False
    return parse_account(account_read).get("kind") == "chatgpt"


def in_force(now=None) -> tuple:
    """The `-c` settings our own servers start with for this capability now (codex/headless.retry_settings), or ()."""
    return headless.retry_settings(now)


def _hold(settings, now) -> None:
    headless.hold_retry_settings(settings, now + FRESH_SECONDS if settings else 0.0)


def _session(paths):
    from ..codex import inuse
    from ..codex.protocol import Session
    return Session(inuse.backend(paths), capability=CAPABILITY)


class RetrySettings:
    """The capability's code: its P8 tick looks, now and then, whether the provider fits, and keeps the settings in
    force while it is on. It answers DEFER always - it sends nothing and writes nothing. Its seams are the tests':
    `session` opens the look's session (None: a live one on our own server), `clock` is time.monotonic."""
    __slots__ = ("paths", "_scoped", "_open", "_clock", "_looked", "_fits")

    def __init__(self, paths, *, session=None, clock=None):
        self.paths, self._scoped, self._open = paths, None, session
        self._clock = clock if clock is not None else time.monotonic
        self._looked, self._fits = None, False

    def bind(self, scoped):
        self._scoped = scoped

    def _wanted(self) -> int:
        try:
            chosen = self._scoped.options().get(OptionKey.ATTEMPTS, DEFAULT_ATTEMPTS)
        except Exception:
            chosen = DEFAULT_ATTEMPTS
        return chosen if chosen in ATTEMPTS else DEFAULT_ATTEMPTS

    def _look(self) -> bool:
        try:
            with (self._open() if self._open is not None else _session(self.paths)) as session:
                return fits(session.call(READ, {"includeLayers": False}), session.call(ACCOUNT, {}))
        except Exception:
            return False

    def tick(self, view):
        now = self._clock()
        if self._looked is None or now - self._looked >= LOOK_SECONDS:
            self._fits, self._looked = self._look(), now
        _hold(overrides(self._wanted()) if self._fits else (), now)
        return DEFER


def make(paths) -> RetrySettings:
    return RetrySettings(paths)
