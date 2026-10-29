# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The courier process: `pythonw.exe -m codex_auto_resume_advanced.courier --home <home> [--feed | --test <channel> |
--pair]`.

It takes this home's courier mutex first - a second courier for the same home exits at once with EXIT_BUSY, and one
whose mutex a lower-integrity process made first is refused (core's win/sync.Mutex, E12) - then does one round and
exits:

* by default, the outbox: each row due is sent on its channel while push_notices stands on and recovery is not paused
  (K5: paused, nothing is sent - rows wait, then drop at seven days); every row too old is dropped;
* `--feed`, the same, then OpenAI's status page read once while status_feed stands on and recovery is not paused;
* `--test <channel>`, the fixed test notice on one channel, now, its outcome as the exit code (EXIT_TEST), for the
  Dashboard's Send a test - while push_notices is on or watched;
* `--pair`, Telegram's pairing: up to PAIR_SECONDS of reading the bot's messages for the one-time code the Dashboard
  showed, keeping the chat that sent it (channels.pair).

Exit codes: 0 done, 3 busy, 4 refused (arguments, a home or a state that cannot be used, a capability not standing on
or a channel not saved); a test's, per EXIT_TEST; 9 a pairing that found no code. Nothing is printed: pythonw has
nowhere to print it, and nothing it could print would be content-free.
"""
from __future__ import annotations

import sys
import time

EXIT_DONE, EXIT_BUSY, EXIT_REFUSED, EXIT_NOT_PAIRED = 0, 3, 4, 9
# A test notice's outcome as its exit code: sent, refused (3xx or 4xx), the service's own failure, no answer in time, the
# secure connection refused.
EXIT_TEST = {"2xx": 0, "4xx": 5, "5xx": 6, "timeout": 7, "tls": 8}
PUSH = "push_notices"
FEED = "status_feed"


def parse(argv):
    """{"home", "mode", "channel"} from `argv`, or None for anything else: exactly `--home <path>` and at most one of
    `--feed`, `--test <channel>`, `--pair`."""
    from ..vocabulary import CourierChannel
    argv, found = list(argv), {"home": None, "mode": "drain", "channel": None}
    while argv:
        word = argv.pop(0)
        if word == "--home" and argv and found["home"] is None:
            found["home"] = argv.pop(0)
        elif word in ("--feed", "--pair") and found["mode"] == "drain":
            found["mode"] = word[2:]
        elif word == "--test" and argv and found["mode"] == "drain" and argv[0] in tuple(CourierChannel):
            found["mode"], found["channel"] = "test", argv.pop(0)
        else:
            return None
    return found if found["home"] else None


def mutex(paths):
    """This home's courier mutex, not waited for: core's named mutex under a name of the courier's own."""
    from codex_auto_resume.win.sync import Mutex
    return Mutex("courier\0" + str(paths.state_dir), timeout=0)


def main(argv=None, **seams) -> int:
    """One round of the courier, as its arguments say; its exit code. `seams` are a test's: `runtime` (a factory given
    the paths), `mutex`, `secrets`, `opener`, `smtp`, `paused`, `clock` and `sleep`."""
    from codex_auto_resume import config
    found = parse(sys.argv[1:] if argv is None else argv)
    if found is None:
        return EXIT_REFUSED
    try:
        paths = config.Paths(found["home"])
    except Exception:
        return EXIT_REFUSED
    lock = (seams.get("mutex") or mutex)(paths)
    try:
        lock.__enter__()
    except Exception as exc:
        return EXIT_BUSY if str(exc) == "mutex_busy" else EXIT_REFUSED
    try:
        return work(paths, found, **seams)
    except Exception:
        return EXIT_REFUSED
    finally:
        lock.__exit__(None, None, None)


def work(paths, found, **seams) -> int:
    """The round itself, under the mutex."""
    from codex_auto_resume import l10n, settings
    from ..vocabulary import ArmingState
    clock = seams.get("clock") or time.time
    if seams.get("runtime") is not None:
        runtime = seams["runtime"](paths)
    else:
        from ..runtime import Runtime
        runtime = Runtime(paths, clock=clock)
    try:
        l10n.set_preference(settings.load(paths.settings_file).get("interface_language"))
    except Exception:
        pass
    states = runtime.states(fresh=True)
    if runtime.registry.get(PUSH) is None and found["mode"] in ("test", "pair"):
        return EXIT_REFUSED
    push = states.get(PUSH, ArmingState.OFF)
    paused = seams["paused"](paths) if "paused" in seams else _paused(paths)
    if found["mode"] in ("test", "pair"):
        if push == ArmingState.OFF:
            return EXIT_REFUSED
        from . import channels
        secrets = seams.get("secrets") or channels.secrets_of(runtime.registry)
        if found["mode"] == "test":
            return channels.test(runtime, found["channel"], secrets, opener=seams.get("opener"),
                                 smtp=seams.get("smtp"))
        return channels.pair(runtime, secrets, opener=seams.get("opener"), clock=clock)
    if push == ArmingState.ARMED and paused is False:
        from . import channels
        secrets = seams.get("secrets") or channels.secrets_of(runtime.registry)
        channels.drain(runtime, secrets, opener=seams.get("opener"), smtp=seams.get("smtp"), now=clock())
    elif runtime.registry.get(PUSH) is not None:
        from . import outbox
        try:
            for channel in outbox.expire(runtime.state, clock()):
                runtime.state.counted(PUSH, "dropped_%s" % channel)
        except Exception:
            pass
    if (found["mode"] == "feed" and runtime.registry.get(FEED) is not None
            and states.get(FEED) == ArmingState.ARMED and paused is False):
        from . import feed
        feed.refresh(runtime, opener=seams.get("opener"), now=clock())
    return EXIT_DONE


def _paused(paths):
    """Whether recovery is paused now, as the compatibility report reads it - None where that cannot be told."""
    from ..report.records import paused
    return paused(paths)


if __name__ == "__main__":
    sys.exit(main())
