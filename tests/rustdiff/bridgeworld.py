"""The bridge's diffs' world (seat S5.1a, car-control): a scratch installation, the answers both sides share for what
the machine would say, and the two askers - the reference tag's `controlcli` and car-control through car-harness.

What a quiet bridge command reads is the state, the settings, the store, Codex's files and the vocabulary; what it
asks the machine is a short list, and the list is the **world** (a JSON object, `DEFAULT_WORLD`): the clock, whether
the watcher's mutex is held, the Run value, the administrator's policy keys, the install lock, the Codex home, the
languages, who may open the state folder, where the watcher and the bridge run, the compatibility view, the sign-in
and boot times. The reference gets each patched into the tag's modules (`SCRIPT`), car-control gets the same JSON
(`car-harness/src/bridge.rs`, `WorldHost`), so both answer for one machine.

An installation is a folder of scratch files made by the product's own code (`installation`): the golden
installation the screenshot envelope and the wire goldens use (`make_screenshots.pinned_installation`), an empty
home, damaged ones, a huge one. Both sides then read the same files; a command that writes (`update`, `defaults`,
`failure-seen`, ...) is run on a copy of the home for each side, and the two homes are compared afterwards.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

import released
from rustdiff import core, reference

ROOT = core.ROOT
NOW = 1_790_000_000.0

# What the machine says, unless a case says otherwise. Every key is read by both sides.
DEFAULT_WORLD = {
    "now": NOW,
    "codex_home": None,            # the installation's own Codex home
    "version": None,               # the tag's own, read once
    "watcher_running": False,      # True, False or None (the probe was unavailable)
    "startup_value": None,         # the Run value, or None
    "install_in_progress": False,  # True, False or None (cannot be looked at)
    "superseded": False,
    "managed": {},                 # an administrator's keys: disable_auto_resume, ..., quiet_hours (a list of dicts)
    "languages": [],               # Windows' preferred UI languages
    "environ": {},
    "state_access": "owner_only",
    "host_app": {"default": {"state": "outside", "family": None, "app": None}, "pids": {}},
    "compat_view": None,
    "installed": False,            # an installed copy looks for other Codex homes; a checkout does not
    "account_codex_home": None,    # the account's CODEX_HOME as Windows holds it
    "app_homes": [],               # where the Codex app says it has run
    "boot": {"sign_in": None, "booted_at": None},
}

# The reference side: the tag's controlcli, with the world patched in. It runs `serve` itself (never `main(["serve"])`,
# whose set-aside sweep is the watcher crate's) or the one-shot `main`.
SCRIPT = r'''
import json, os, sys, time
from pathlib import Path

spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
world, mode, home, argv = spec["world"], spec["mode"], spec["home"], spec["argv"]

for name in ("CODEX_AUTO_RESUME_LANG", "LANG", "LC_ALL", "LC_MESSAGES"):
    os.environ.pop(name, None)
os.environ.update(world.get("environ") or {})

real_gmtime = time.gmtime
time.time = lambda: world["now"]
time.gmtime = lambda seconds=None: real_gmtime(world["now"] if seconds is None else seconds)
time.localtime = lambda seconds=None: real_gmtime(world["now"] if seconds is None else seconds)

from codex_auto_resume import config
config.version = lambda: world["version"]
config.codex_home = lambda: Path(world["codex_home"])
from codex_auto_resume import compatio, controlcli, control, l10n, managed, startup, windows
from codex_auto_resume.control import policy, state, watcher as control_watcher
from codex_auto_resume.win import acl, kernel, ownprocess

l10n._windows_preferred = lambda: list(world["languages"])
held = world.get("managed") or {}
made = managed.Managed(
    disable_auto_resume=bool(held.get("disable_auto_resume")),
    force_observe_only=bool(held.get("force_observe_only")),
    disable_update_check=bool(held.get("disable_update_check")),
    disable_status_file=bool(held.get("disable_status_file")),
    max_recovery_attempts=held.get("max_recovery_attempts"),
    quiet_hours=tuple(held.get("quiet_hours") or ()),
    disable_power_action=bool(held.get("disable_power_action")))
policy.managed_policy = lambda: made
state.superseded = lambda: bool(world["superseded"])
windows.install_in_progress = lambda: world["install_in_progress"]
control_watcher.WatcherMixin.watcher_running = lambda self: world["watcher_running"]
startup.current_value = lambda: world["startup_value"]
boot = world.get("boot") or {}
ownprocess.sign_in = lambda: boot.get("sign_in")
ownprocess.booted_at = lambda: boot.get("booted_at")
acl.state_access = lambda path: world["state_access"]
apps = world.get("host_app") or {}
kernel.host_app = lambda pid=None, started_by=None: dict((apps.get("pids") or {}).get(str(pid), apps.get("default")))
compatio.reader_view = lambda paths, settings=None: world["compat_view"]
from codex_auto_resume import homefind
from codex_auto_resume.win import userenv
if world.get("installed"):
    homefind.looks = lambda installed: True
userenv.codex_home = lambda: world.get("account_codex_home")
homefind.app_homes = lambda local_appdata=None: list(world.get("app_homes") or [])

for hook in spec.get("hooks") or ():
    exec(hook)

if mode == "serve":
    controlcli._use_utf8()
    sys.exit(controlcli.serve(control.Control(Path(home)), sys.stdin, sys.stdout))
sys.exit(controlcli.main(["--home", home, *argv]))
'''


def tag_version() -> str:
    """The reference tag's own `config.version()`, asked once."""
    global _VERSION
    if _VERSION is None:
        done = reference.run("from codex_auto_resume import config; print(config.version())")
        _VERSION = done.stdout.decode("utf-8").strip()
    return _VERSION


_VERSION = None


def world_for(workspace: Path, **changes) -> dict:
    """`DEFAULT_WORLD` for the installation in `workspace`, with `changes` laid over it."""
    world = json.loads(json.dumps(DEFAULT_WORLD))
    world["codex_home"] = str(workspace / "codex")
    world["version"] = tag_version()
    world.update(changes)
    return world


def ask_reference(home: Path, world: dict, *, mode="serve", stdin: bytes = b"", argv=(), hooks=()):
    """The tag's bridge on `home`: (exit code, stdout bytes). `hooks` are lines of Python run after the world is in."""
    spec = Path(tempfile.mkdtemp(prefix="car-bridge-spec-")) / "spec.json"
    try:
        spec.write_text(json.dumps({"world": world, "mode": mode, "home": str(home), "argv": list(argv),
                                    "hooks": list(hooks)}), encoding="utf-8")
        done = reference.run(SCRIPT, spec, profile=home.parent / "profile", stdin=stdin)
    finally:
        shutil.rmtree(spec.parent, ignore_errors=True)
    return done.returncode, done.stdout, done.stderr


def ask_rust(harness: core.Harness, home: Path, world: dict, *, mode="serve", stdin: bytes = b"", argv=()):
    """car-control's bridge on `home` through car-harness: (exit code, output bytes), or the harness's refusal."""
    _, line = harness.call("bridge.run", home=str(home), world=world, mode=mode, input=stdin.hex(), argv=list(argv))
    reply = json.loads(line.decode("utf-8"))["reply"]
    if not reply.get("ok"):
        raise AssertionError("car-harness refused bridge.run: %r" % (reply,))
    value = reply["value"]
    return value["code"], value["output"].encode("utf-8")


def installation(workspace: Path, kind: str = "golden") -> Path:
    """A scratch installation in `workspace`, by `kind`; its home (`workspace/"home"`). The Codex home beside it is
    `workspace/"codex"`.

    * golden - the wire goldens' own: five conversations, records in most states, a Codex home to read labels from,
      settings stored, the watcher's heartbeat (`make_screenshots.pinned_installation`, no watcher mutex held);
    * empty - the home's folders and nothing in them: no state, no settings, no Codex home;
    * fresh - an empty folder: not even the home exists.
    """
    home = workspace / "home"
    (workspace / "profile").mkdir(parents=True, exist_ok=True)
    if kind == "fresh":
        return home
    if kind == "empty":
        (home / "config").mkdir(parents=True)
        (home / "logs").mkdir(parents=True)
        return home
    for entry in (ROOT / "src", ROOT / "build", ROOT / "tests"):
        if str(entry) not in sys.path:
            sys.path.insert(0, str(entry))
    import make_screenshots as generator

    with generator.pinned_installation(workspace, watching=False, engine=False):
        pass
    return home


def copy_home(workspace: Path, name: str) -> Path:
    """A copy of the installation `workspace` for one side to write into: the new workspace."""
    target = workspace.parent / (workspace.name + "-" + name)
    shutil.copytree(workspace, target)
    return target


def files_of(home: Path) -> dict:
    """Every file under `home` (relative path -> bytes), the volatile ones left out: the state is compared by its
    own dump elsewhere; here the small files a command writes (settings.json, failure-seen.json, once-words.json,
    a set-aside copy)."""
    found = {}
    for path in sorted(home.rglob("*")):
        if path.is_file() and path.suffix not in (".sqlite", ".tmp") and "-journal" not in path.name \
                and "-wal" not in path.name and "-shm" not in path.name:
            found[path.relative_to(home).as_posix()] = path.read_bytes()
    return found
