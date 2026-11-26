"""The command line's world (seat S5.2): the tag's `cli.main` and `plugin_setup.main` patched to the stand-ins car-bin's
Outside answers from (`car-harness/src/cli.rs`, `WorldOutside`), over bridgeworld's and actworld's world, every call
written down in order. Nothing the reference does here writes the registry, makes a shortcut, starts a process or
touches the real installation: each of those is a function patched to a recorder.

Rust's own registrations (PLAN 6.4, S8.2) are not the reference's - the sign-in value starts the watcher host, the link
handler is the core's, a Start-menu entry with no settings window opens the core, and there is no Python launcher to
copy - so `HOOK` puts Rust's shapes where the reference builds its own (`watcher_command`, `notification_command`,
`startup.command_line`, `_what_the_entry_opens`) and leaves every other line of the commands as the tag has it. A
watcher's launch is compared without its command line (the host's is not the launcher's), by its folder and flags.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from rustdiff import actworld as aw
from rustdiff import bridgeworld as bw
from rustdiff import core, gen_cli, reference

HOOK = r'''
if mode in ("cli", "dispatch"):
    import contextlib as _contextlib, importlib.util as _ilu, shutil as _shutil
    from codex_auto_resume import addremove as _ar, config as _config, shortcut as _sc, startup as _st, windows as _win
    from codex_auto_resume import notifier as _notifier
    from codex_auto_resume.codex import errors as _codex_errors
    from codex_auto_resume.commands import base as _base, install as _install_cmds, status as _status
    from codex_auto_resume.runtime import app as _app_module
    from codex_auto_resume import cli as _cli
    import logging as _logging
    # logging takes time.localtime when it is imported, after the world's patch: as a plain function it would be bound.
    _logging.Formatter.converter = staticmethod(time.localtime)
    # A record's time is time.time_ns() since 3.13: the world's clock.
    time.time_ns = lambda: int(world["now"] * 1_000_000_000)
    _status.WakeEvent = _event("wake")

    def _world_raise(found, default_class):
        said = found.get("raise")
        name, message = (said[0], said[1] if len(said) > 1 else "") if isinstance(said, list) else (said, "")
        kind = {"AdapterError": _win.AdapterError, "ConfigError": _config.ConfigError,
                "StartupError": _st.StartupError, "ShortcutError": _sc.ShortcutError,
                "DesktopTaken": _sc.DesktopTaken}.get(name) or getattr(builtins, name, None)
        if kind is None:
            kind = type(name, (Exception,), {})
        if kind is _sc.DesktopTaken:
            raise kind()
        raise kind(message)

    def _world(name, fallback=None):
        found = world.get(name)
        if isinstance(found, dict) and "raise" in found:
            _world_raise(found, "RuntimeError")
        if isinstance(found, dict) and "value" in found:
            return found["value"]
        return fallback if found is None else found

    def _quote_all(argv):
        return " ".join(_st.quote_argument(str(each)) for each in argv)

    def _rust_watcher(home):
        home = str(home)
        return _quote_all([os.path.join(home, "app", "bin", "CodexAutoResume.exe"), "--home", home, "run"])

    def _rust_protocol(home):
        home = str(home)
        return _quote_all([os.path.join(home, "app", "bin", "codex-auto-resume.exe"), "--home", home, "activate"]) + ' "%1"'

    _st.command_line = lambda script, home=None, launcher=None, options=None: _rust_watcher(home)
    _st.protocol_command_line = lambda script, home, launcher=None, options=None: _rust_protocol(home)
    _st.watcher_python = lambda home=None: Path("pythonw.exe")

    def _opens(paths):
        icon = str(paths.icon_file) if paths.icon_file.is_file() else None
        window = paths.home / "CodexAutoResumeSettings.exe"
        if window.is_file():
            return {"target": window, "icon": icon, "description": "Codex Auto Resume Settings"}
        return {"target": paths.home / "app" / "bin" / "codex-auto-resume.exe",
                "arguments": _quote_all(["--home", str(paths.home), "status"]), "icon": icon,
                "description": "Codex Auto Resume"}
    _install_cmds._what_the_entry_opens = _opens

    def _opened(opens):
        return {"target": str(opens["target"]), "arguments": opens.get("arguments"),
                "icon": None if opens.get("icon") is None else str(opens["icon"]), "description": opens["description"]}

    def _register_aumid(icon=None):
        _log("register_aumid", None if icon is None else str(icon))
        return bool(_world("register_aumid", True))
    def _unregister_aumid():
        _log("unregister_aumid")
        return bool(_world("unregister_aumid", True))
    def _install_protocol(command):
        _log("install_protocol", command)
        return bool(_world("install_protocol", True))
    def _uninstall_protocol():
        _log("uninstall_protocol")
        return bool(_world("uninstall_protocol", True))
    _st.register_aumid, _st.unregister_aumid = _register_aumid, _unregister_aumid
    _st.install_protocol, _st.uninstall_protocol = _install_protocol, _uninstall_protocol

    def _shortcut(name):
        found = world.get(name)
        if isinstance(found, dict) and "raise" in found:
            _world_raise(found, "ShortcutError")
        return found is not False
    def _sc_install(**opens):
        _log("shortcut_install", _opened(opens))
        return _shortcut("shortcut_install")
    def _sc_uninstall():
        _log("shortcut_uninstall")
        return world.get("shortcut_uninstall") is not False
    def _sc_desktop(home, **opens):
        _log("desktop_install", str(home), _opened(opens))
        return _shortcut("desktop_install")
    def _sc_undesktop(home):
        _log("desktop_uninstall", str(home))
        return _shortcut("desktop_uninstall")
    _sc.install, _sc.uninstall, _sc.install_desktop, _sc.uninstall_desktop = (_sc_install, _sc_uninstall, _sc_desktop,
                                                                              _sc_undesktop)

    def _ar_register(home, edition, version, name):
        _log("addremove_register", str(home), str(edition), str(version), str(name))
        _world("addremove_register")
    def _ar_unregister(home):
        _log("addremove_unregister", str(home))
        return bool(_world("addremove_unregister", False))
    def _ar_remove_kept(home):
        _log("addremove_remove_kept", str(home))
        return world.get("addremove_remove_kept") is True
    _ar.register, _ar.unregister, _ar.remove_kept = _ar_register, _ar_unregister, _ar_remove_kept

    class _Backend:
        def __init__(self, found):
            self.codex_exe = found.get("codex_exe", "")
            self.engine_version = found.get("engine_version", "")
    def _backend(self):
        _log("backend", self._codex_exe_override, str(self.codex_home))
        found = _world("backend")
        if not isinstance(found, dict):
            raise _win.AdapterError("engine_discovery_not_ported")
        return _Backend(found)
    _app_module.App.backend = _backend
    def _engine_word(paths, version):
        _log("engine_word", version)
        found = world.get("engine_word")
        return found if isinstance(found, str) else None
    compatio.engine_word = _engine_word
    def _paired(app, backend):
        _log("app_paired", backend.codex_exe)
        found = world.get("app_paired")
        if not isinstance(found, dict):
            looked = backend
            looked.app_look = "unmatched"
            return None, looked
        pair = found.get("identity")
        identity = {"pid": pair[0], "server": {"pid": pair[1]}} if isinstance(pair, list) and len(pair) == 2 else None
        looked = _Backend(found.get("looked") or {"codex_exe": backend.codex_exe,
                                                 "engine_version": backend.engine_version})
        looked.app_look = found.get("app_look", "unmatched")
        return identity, looked
    _status._app_paired = _paired
    def _running_now():
        _log("app_running_now")
        found = world.get("app_running_now")
        return found if isinstance(found, bool) else None
    _status.app_running_now = _running_now
    def _users(path):
        _log("resource_users", str(path))
        _world("resource_users")
    _status.resource_users = _users
    class _Source:
        def latest_failures(self, since):
            _log("history")
            found = world.get("history", "readable")
            if found == "not_yet":
                raise _codex_errors.HistoryNotYet("not yet")
            if found == "readable":
                return []
            raise type(found, (Exception,), {})()
    _app_module.App.source = lambda self: _Source()
    _live_before = compatio.live_view
    def _live_any(paths, codex_home, explicit=None, backend=None, discovery=None, source=None):
        if backend is None:
            return _live_before(paths, codex_home, explicit)
        _log("doctor_live_view", str(codex_home), backend.codex_exe)
        return _world("doctor_live")
    compatio.live_view = _live_any
    def _run_watcher(self, once=False, poll=None):
        _log("run_watcher", str(self.paths.home), bool(once), poll)
        return 0
    _app_module.App.run = _run_watcher
    _app_module.App.watcher_running = _running
    _app_module.App.stop_event = lambda self: _event("stop")(None)
    @_contextlib.contextmanager
    def _mutex(self, timeout=0.0):
        _log("watcher_mutex", float(timeout))
        found = _world("watcher_mutex", "free")
        if found != "free":
            raise _win.AdapterError(found)
        yield None
    _app_module.App.mutex = _mutex

    def _announce(notice, inbox=None, setting=False):
        _log("announce_cancelled", notice[0], bool(notice[1]))
    _notifier.build_cancelled = lambda thread, stay=None: thread
    _notifier.with_open_codex = lambda notice, open_codex: (notice, open_codex)
    _notifier.deliver = _announce
    def _power_stop(uri, **kwargs):
        _log("power_stop", uri)
        return world.get("power_stop", "refused")
    _notifier.activate = _power_stop
    from codex_auto_resume.ui import tray as _tray
    def _open_dashboard(home, page):
        _log("open_dashboard", str(home), page)
        return world.get("open_dashboard") is True
    def _open_chat(home, thread):
        _log("open_chat", str(home), thread)
        return world.get("open_chat") is True
    _tray.open_dashboard, _tray.open_chat = _open_dashboard, _open_chat
    # cli's own pid in the health checks' log mark.
    _base.os = __import__("types").SimpleNamespace(getpid=lambda: world.get("pid", 7777), environ=os.environ)

    spec_setup = _ilu.spec_from_file_location("plugin_setup", spec["plugin_setup"])
    _plugin_setup = _ilu.module_from_spec(spec_setup)
    spec_setup.loader.exec_module(_plugin_setup)
    _plugin_setup.watcher_command = _rust_watcher
    _plugin_setup.notification_command = _rust_protocol
    def _python_for_watcher(home=None):
        host = Path(home) / "app" / "bin" / "CodexAutoResume.exe"
        if not host.is_file():
            raise _st.StartupError("no host")
        return host
    _plugin_setup.python_for_watcher = _python_for_watcher
    _copy = _shutil.copyfile
    _plugin_setup.shutil = __import__("types").SimpleNamespace(
        copyfile=lambda source, target: None if str(source).endswith("watcher_launcher.py") else _copy(source, target))

    argv = list(spec["argv"])
    if mode == "cli":
        sys.exit(_cli.main(argv))
    # car-bin's own roles: `bridge` is controlcli.main's, `mcp` mcpserver.main's.
    if argv[:1] == ["bridge"]:
        sys.exit(controlcli.main(argv[1:]))
    if argv[:1] == ["mcp"]:
        from codex_auto_resume import mcpserver as _mcpserver_main
        sys.exit(_mcpserver_main.main(argv[1:]))
    commands = [name for action in _plugin_setup.build_parser()._actions if hasattr(action, "choices")
                and isinstance(action.choices, dict) for name in action.choices]
    if argv and argv[0] in commands:
        sys.exit(_plugin_setup.main(argv))
    sys.exit(_cli.main(argv))
'''


def run_reference(home: Path, world: dict, argv, *, mode="dispatch", stdin: bytes = b"", tag=None):
    """The tag's command line (mode "cli") or `codex-auto-resume.exe`'s dispatch (mode "dispatch") on `home`, from the
    tag's own tree (src, scripts): (code, stdout, stderr, calls)."""
    tree = gen_cli.tree(tag or reference.TAG)
    folder = Path(tempfile.mkdtemp(prefix="car-v0627-mcp-cli-spec-"))
    try:
        spec = {"world": world, "mode": mode, "home": str(home), "argv": list(argv),
                "hooks": [aw.HOOK, HOOK], "calls_path": str(folder / "calls.json"),
                "result_path": str(folder / "result.json"), "method": None, "args": [],
                "plugin_setup": str(tree / "scripts" / "plugin_setup.py")}
        (folder / "spec.json").write_text(json.dumps(spec), encoding="utf-8")
        # The world's zone is UTC (car-harness's local clock); `format_local` asks the C runtime's, which TZ sets.
        environment = reference.scratch_environment(home.parent / "profile", PYTHONPATH=str(tree / "src"), TZ="UTC0")
        done = subprocess.run(reference.command(bw.SCRIPT, folder / "spec.json", paths=[tree / "src"]),
                              input=stdin, capture_output=True, env=environment, cwd=str(home.parent),
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=600)
        calls = (json.loads((folder / "calls.json").read_text(encoding="utf-8"))
                 if (folder / "calls.json").is_file() else None)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    return done.returncode, done.stdout, done.stderr, calls


def run_rust(harness: core.Harness, home: Path, world: dict, argv, *, mode="dispatch", stdin: bytes = b"", tag=None):
    """car-bin on `home` through car-harness's `cli.run`: (code, stdout, stderr, calls)."""
    tree = gen_cli.tree(tag or reference.TAG)
    _, line = harness.call("cli.run", home=str(home), world=world, argv=list(argv), input=stdin.hex(),
                           project_root=str(tree), entry=mode)
    reply = json.loads(line.decode("utf-8"))["reply"]
    if not reply.get("ok"):
        raise AssertionError("car-harness refused cli.run: %r" % (reply,))
    value = reply["value"]
    return value["code"], value["output"].encode("utf-8"), value["error"].encode("utf-8"), value["calls"]


def normal_calls(calls):
    """The calls as compared: a launch without its command line (the host is not the Python launcher)."""
    if calls is None:
        return None
    out = []
    for each in calls:
        if each and each[0] == "launch" and len(each) == 4:
            each = ["launch", "<watcher>", each[2], each[3]]
        out.append(each)
    return out


os  # noqa: B018 - the environment the reference runs under is reference.scratch_environment's
