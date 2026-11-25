"""The command line, plugin_setup.py's commands and the dispatcher (seat S5.2, car-bin): the same `codex-auto-resume.exe
<argv>` through the reference tag's `cli.main` / `plugin_setup.main` (cliworld.HOOK) and through car-bin (car-harness
`cli.run`), over the same scratch installation and world. Compared byte for byte: stdout, the exit code, stderr (where
the reference did not end in a traceback, whose text is Python's own), every file under the workspace (the settings,
the logs, runtime.json, a diagnostics bundle), every row of the state, and every call made through the Host and the
Outside, in order.

* ParserDiff    - the four parsers: valid lines in every form argparse takes (abbreviations, `--name=value`, `-n5`, `--`,
                  negative numbers) and every error it writes, `-h` of each parser and subparser.
* CommandsDiff  - every CLI command over the golden, empty and fresh homes and the world's answers (the watcher,
                  the engine, the app's pairing, the Run key, the registrations, the compatibility views).
* SetupDiff     - every plugin_setup.py command on the runtime home, setup through each of its exits.

Run by run.py; never by the lanes' discovery.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile

from rustdiff import actworld as aw
from rustdiff import bridgeworld as bw
from rustdiff import cliworld as cw
from rustdiff import core, reference
from rustdiff.diffs import RECORD
from rustdiff.diffs_bridge_acting import ActingBase, first_difference, now
import wiregolden as wg

T1, T2, T3 = wg.T1, wg.T2, wg.T3
RESET, BACKOFF, RECOVERED, EXHAUSTED = wg.WAITING_RESET, wg.WAITING_BACKOFF, wg.RECOVERED, wg.EXHAUSTED
COUNTS = {"runs": 0, "calls": 0}


def make(*relatives):
    """Files the installation has before the command: `runtime\\python.exe`, `app\\bin\\CodexAutoResume.exe`, ..."""
    def tune(workspace: Path):
        for relative in relatives:
            path = workspace / "home" / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if relative.endswith("/"):
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.write_bytes(b"")
    return tune


INSTALLED = ("runtime/python.exe", "runtime/pythonw.exe", "app/src/codex_auto_resume/", "app/bin/CodexAutoResume.exe")


def chained(*tunes):
    def tune(workspace):
        for each in tunes:
            if each is not None:
                each(workspace)
    return tune


class CliBase(ActingBase):
    def run_cli(self, argv, *, kind="acts", world=None, tune=None, mode="dispatch", label="", stdin=b""):
        ran = []
        for side in ("reference", "rust"):
            workspace = self.workspace(kind, tune)
            made = world(workspace) if callable(world) else dict(world or {})
            if kind in ("golden", "acts"):
                made.setdefault("now", now())
            environ = {"CODEX_AUTO_RESUME_PLUGIN_HOME": str(workspace / "home"),
                       "USERPROFILE": str(workspace / "profile")}
            environ.update(made.pop("environ", {}))
            asked_world = aw.world_for(workspace, environ=environ, **made)
            asked = [each(workspace) if callable(each) else each for each in argv]
            home = workspace / "home"
            if side == "reference":
                code, out, err, calls = cw.run_reference(home, asked_world, asked, mode=mode, stdin=stdin)
            else:
                code, out, err, calls = cw.run_rust(self.harness, home, asked_world, asked, mode=mode, stdin=stdin)
            files = {name: data for name, data in bw.files_of(workspace).items() if not name.startswith("profile/")}
            ran.append((code, out, err, files, aw.state_dump(home), cw.normal_calls(calls)))
        (code, out, err, files, state, calls), (code2, out2, err2, files2, state2, calls2) = ran
        label = label or " ".join(str(each) for each in argv)
        self.assertEqual(out2.decode("utf-8", "replace"), out.decode("utf-8", "replace"),
                         "%s: stdout differs (reference stderr %r)" % (label, err[-800:]))
        self.assertEqual(code2, code, "%s: the exit code differs (reference stderr %r, rust %r)" % (
            label, err[-800:], err2[-400:]))
        if b"Traceback" not in err:
            self.assertEqual(err2.decode("utf-8", "replace"), err.decode("utf-8", "replace"),
                             "%s: stderr differs" % label)
        for what, mine, theirs in (("the files written", files2, files), ("the state written", state2, state),
                                   ("the Host and Outside calls", calls2, calls)):
            if mine != theirs:
                self.fail("%s: %s differ at %s (reference stderr %r)" % (label, what, first_difference(theirs, mine),
                                                                       err[-600:]))
        COUNTS["runs"] += 1
        COUNTS["calls"] += len(calls or [])
        return out


def H(workspace):
    return str(workspace / "home")


class ParserDiff(CliBase):
    def test_lines_and_errors(self):
        lines = [
            [], ["-h"], ["--help"], ["bogus"], ["--home"], ["--hom=%s"], ["--co", "x", "status"],
            ["--codex-e=x", "--home", H, "--quiet", "logs", "-n5"], ["--home", H, "logs", "-n", "-5"],
            ["--home", H, "logs", "-5"], ["--home", H, "logs", "--lines=2"], ["--home", H, "logs", "--li", "3"],
            ["--home", H, "logs", "-n"], ["--home", H, "logs", "-nx"], ["--home", H, "logs", "-n", " 4 "],
            ["--home", H, "logs", "-n", "1_0"], ["--home", H, "cancel"], ["--home", H, "status", "extra"],
            ["--home", H, "enable", "--", "-x"], ["--home", H, "enable", "--lookback-hours", "x"],
            ["--home", H, "downgrade-state", "--to", "5"], ["--home", H, "downgrade-state"],
            ["--home", H, "install", "--edition-from", "pro"], ["--home", H, "pending", "--js=1"],
            ["--quiet=1", "status"], ["--home", H, "compat", "--import"], ["--home", H, "status", "-h"],
            ["--home", H, "activate"], ["setup", "-h"], ["setup", "--bogus"], ["downgrade-state", "--to", "9"],
            ["downgrade-state", "--to", "3", "--stop"], ["desktop-shortcut", "move"], ["logs", "--lines", "x"],
            ["cancel"], ["uninstall", "--pur"], ["watcher-running", "x"], ["mcp", "--bogus"], ["mcp", "-h"],
            ["bridge"], ["bridge", "-h"], ["bridge", "nope"], ["bridge", "compat-import", "--origin", "web"],
        ]
        for argv in lines:
            argv = [each.replace("%s", "") if isinstance(each, str) else each for each in argv]
            with self.subTest(argv=[each if isinstance(each, str) else "<home>" for each in argv]):
                self.run_cli(argv, world={"watcher_running": False})
        RECORD.append("CLI parsers: %d command lines (forms and errors) equal" % len(lines))


class CommandsDiff(CliBase):
    def test_records(self):
        cases = [
            (["--home", H, "pending"], {}, None), (["--home", H, "pending", "--all"], {}, None),
            (["--home", H, "pending", "--json"], {}, None), (["--home", H, "pending", "--all", "--json"], {}, None),
            (["--home", H, "enable"], {"watcher_running": False}, None),
            (["--home", H, "enable"], {"watcher_running": True}, None),
            (["--home", H, "--quiet", "enable", "--lookback-hours", "12"], {"watcher_running": None}, None),
            (["--home", H, "enable", T1], {}, None), (["--home", H, "enable", T1.upper()], {}, None),
            (["--home", H, "enable", "not-a-uuid"], {}, None),
            (["--home", H, "enable"], {"managed": {"disable_auto_resume": True}}, None),
            (["--home", H, "disable"], {}, None), (["--home", H, "--quiet", "disable", T2], {}, None),
            (["--home", H, "cancel", T1], {}, None), (["--home", H, "cancel", "x"], {}, None),
            (["--home", H, "logs"], {}, None), (["--home", H, "logs", "-n", "2"], {}, None),
            (["--home", H, "logs", "-n", "0"], {}, None),
            (["--home", H, "stop"], {"watcher_running": False}, None),
            (["--home", H, "stop"], {"watcher_running": True, "signals": {"stop": True}, "probes": [True, True, False]},
             None),
            (["--home", H, "stop"], {"watcher_running": True, "signals": {"stop": True}}, None),
            (["--home", H, "run", "--once", "--poll", "30"], {}, None),
        ]
        for argv, world, tune in cases:
            with self.subTest(argv=[str(each) for each in argv[2:]], world=world):
                self.run_cli(argv, world=world, tune=tune)
        for kind in ("empty", "fresh"):
            for argv in (["--home", H, "pending"], ["--home", H, "enable"], ["--home", H, "logs"]):
                with self.subTest(kind=kind, argv=argv[2:]):
                    self.run_cli(argv, kind=kind, world={"watcher_running": False})

    def test_status_and_doctor(self):
        backend = {"codex_exe": "C:\\Codex\\bin\\codex.exe", "engine_version": "0.130.0"}
        worlds = [
            {"watcher_running": True},
            {"watcher_running": False, "startup_value": "x", "backend": {"value": backend}, "engine_word": "verified"},
            {"watcher_running": None, "startup_raise": {"read": "cannot read"},
             "backend": {"raise": ["AdapterError", "codex_not_found"]}, "app_running_now": False},
            {"backend": {"value": backend}, "app_paired": {"identity": [11, 12], "app_look": "paired"},
             "engine_word": "checked", "history": "not_yet"},
            {"backend": {"value": backend}, "app_paired": {"identity": [11, 12], "looked": {
                "codex_exe": "C:\\Other\\codex.exe", "engine_version": "0.131.0"}}, "history": "OSError",
             "protocol_value": "\"C:\\nowhere\\x.exe\" --home H activate \"%1\""},
            {"backend": {"value": backend}, "app_paired": {"app_look": "closed"}, "engine_word": "incompatible",
             "doctor_live": {"value": {"overall": "incompatible", "capabilities": {
                 "engine_present": {"state": "INCOMPATIBLE", "reason": "registry_incompatible",
                                    "registry_reason": "queue_interrupts"}}}},
             "compat_view": dict(cw_view(), status="ok", overall="checked", checked_at=1799999000.0, acting="verified")},
            {"backend": {"raise": ["ConfigError", "bad codex_exe"]}, "app_running_now": True},
            {"backend": {"value": backend}, "doctor_live": {"raise": ["OSError", "x"]},
             "startup_value": "\"C:\\missing\\pythonw.exe\" \"C:\\missing\\watcher-launcher.py\" run"},
        ]
        for index, world in enumerate(worlds):
            for command in ("status", "doctor"):
                with self.subTest(command=command, world=index):
                    self.run_cli(["--home", H, command], world=world, label="%s, world %d" % (command, index))
        with self.subTest("doctor's progress lines"):
            self.run_cli(["--home", H, "--quiet", "doctor"], world=dict(worlds[3], environ={
                "CODEX_AUTO_RESUME_PROGRESS_LINES": "1"}))
        with self.subTest("a lock file for the Restart Manager"):
            def lock(workspace):
                path = workspace / "codex" / "thread-writer-locks" / ".coordination.lock"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"")
            for users in (None, {"raise": ["AdapterError", "restart_manager_failed"]}):
                self.run_cli(["--home", H, "doctor"], tune=lock, world=dict(worlds[3], resource_users=users))

    def test_compat(self):
        view = dict(cw_view(), status="ok", overall="verified", checked_at=1799999000.0,
                    data={"source": "cache", "bundled": "ok", "bundled_sequence": 3, "cache": "ok", "cache_sequence": 5},
                    reported={"state": "reported", "worked": 3, "failed": 1, "neither": 0, "both": 2})
        for argv, world in (
                (["compat"], {}), (["compat", "--json"], {"compat_view": view}), (["compat"], {"compat_view": view}),
                (["compat", "--live"], {"compat_live": {"value": dict(view, live=True)}}),
                (["compat", "--live", "--json"], {"compat_live": {"raise": ["OSError", "x"]}}),
                (["compat", "--import", "C:\\x.json"], {}),
                (["compat", "--import", "C:\\x.json"], {"compat_import": {"value": {"imported": True, "sequence": 9,
                                                                                    "cache": "ok", "reason": None}},
                                                       "signals": {"wake": True}})):
            with self.subTest(argv=argv, world=world):
                self.run_cli(["--home", H, *argv], world=world)

    def test_install_and_uninstall(self):
        window = make("CodexAutoResumeSettings.exe", "codex-auto-resume.ico")
        cases = [
            (["install"], {}, None), (["install", "--startup"], {}, window),
            (["install", "--startup", "--edition-from", "advanced"], {"startup_value": "x"}, None),
            (["install", "--edition-from", "standard"], {"register_aumid": {"raise": ["StartupError", "denied"]}}, None),
            (["install"], {"shortcut_install": {"raise": ["ShortcutError", "no powershell"]},
                           "install_protocol": {"raise": ["StartupError", "no"]}}, None),
            (["uninstall"], {"watcher_running": True}, None), (["uninstall"], {"watcher_running": None}, None),
            (["uninstall"], {"watcher_running": False, "startup_value": "\"C:\\other\\x.exe\" run",
                             "notification_owner": False, "protocol_value": "\"C:\\other\\x.exe\" \"%1\""}, None),
            (["uninstall", "--keep-state", "--keep-logs"], {"watcher_running": False, "notification_owner": True,
                                                            "addremove_unregister": True,
                                                            "desktop_uninstall": True}, None),
            (["uninstall", "--keep-state"], {"watcher_running": False,
                                             "desktop_uninstall": {"raise": ["ShortcutError", "busy"]},
                                             "addremove_unregister": {"raise": ["StartupError", "denied"]}}, None),
            (["uninstall"], {"watcher_running": True, "signals": {"stop": True}, "probes": [True, False]}, None),
        ]
        for argv, world, tune in cases:
            with self.subTest(argv=argv, world=world):
                def run_world(workspace, world=world):
                    made = dict(world)
                    if made.get("startup_value") == "x":
                        made["startup_value"] = cw_rust_watcher(workspace)
                    return made
                self.run_cli(["--home", H, *argv], world=run_world, tune=tune)

    def test_activate_diagnostics_downgrade(self):
        nonce = "0123456789abcdef"
        uris = ["codex-auto-resume:cancel?i=%s" % BACKOFF, "codex-auto-resume:cancel?i=%s&c=1" % RECOVERED,
                "codex-auto-resume:cancel?i=%s" % ("f" * 64), "codex-auto-resume:open?page=pending",
                "codex-auto-resume:open?page=nope", "codex-auto-resume:power-stop?n=%s" % nonce,
                "codex-auto-resume:chat?thread=%s" % T1, "CODEX-AUTO-RESUME://cancel/?i=%s" % BACKOFF,
                "codex-auto-resume:cancel?i=%s&i=%s" % (BACKOFF, BACKOFF), "https://example.invalid/", "",
                "codex-auto-resume:cancel?i=%%41%s" % BACKOFF[2:], "codex-auto-resume:open?page=%20Pending%20"]
        for uri in uris:
            for world in ({}, {"open_dashboard": True, "open_chat": True, "power_stop": "stopped"}):
                with self.subTest(uri=uri, world=world):
                    self.run_cli(["--home", H, "--quiet", "activate", uri], world=world)
        for argv in (["diagnostics", "--out", lambda ws: str(ws / "bundle.json")],
                     ["diagnostics", "--out", lambda ws: str(ws / "home")]):
            with self.subTest(argv=argv[:1]):
                self.run_cli(["--home", H, *argv], world={"checkup_bundle": {"value": {"summary": "ok"}}})
        for argv, world in ((["downgrade-state", "--to", "4"], {}), (["downgrade-state", "--to", "3"], {}),
                            (["downgrade-state", "--to", "2"], {}),
                            (["downgrade-state", "--to", "4"], {"watcher_mutex": "mutex_busy"}),
                            (["downgrade-state", "--to", "4", "--stop-watcher"], {"signals": {"stop": True}}),
                            (["downgrade-state", "--to", "3", "--stop-watcher"], {"watcher_mutex": "mutex_busy"}),
                            (["downgrade-state", "--to", "3", "--stop-watcher"], {"watcher_mutex": "other"})):
            with self.subTest(argv=argv, world=world):
                self.run_cli(["--home", H, *argv], world=world)
        RECORD.append("CLI commands: %d runs, %d Host/Outside calls equal" % (COUNTS["runs"], COUNTS["calls"]))


def cw_view() -> dict:
    from codex_auto_resume.compat import report

    return json.loads(json.dumps(report.unusable_view("absent")))


def cw_rust_watcher(workspace) -> str:
    from codex_auto_resume import startup

    home = str(workspace / "home")
    return " ".join(startup.quote_argument(each) for each in
                    (str(Path(home) / "app" / "bin" / "CodexAutoResume.exe"), "--home", home, "run"))


class SetupDiff(CliBase):
    def test_every_command(self):
        installed = make(*INSTALLED)
        cases = [
            (["setup"], {}, None), (["setup"], {}, installed),
            (["setup", "--keep-state"], {"watcher_running": True}, installed),
            (["setup", "--keep-state", "--no-startup", "--watcher-was-stopped"], {"watcher_running": False}, installed),
            (["setup", "--keep-state", "--watcher-was-stopped"], {"watcher_running": False,
                                                                  "environ": {"CODEX_AUTO_RESUME_SETUP_SAYS_LEFT_STOPPED": "1"}},
             installed),
            (["setup"], {"probes": [False], "watcher_running": True, "launch": {"pid": 9, "polls": [None]}}, installed),
            (["setup"], {"probes": [False, False], "watcher_running": False, "launch": {"pid": 9, "polls": [1]}},
             installed),
            (["setup"], {"watcher_running": False, "environ": {"CODEX_AUTO_RESUME_SETUP_WILL_LOOK_AGAIN": "1",
                                                               "CODEX_AUTO_RESUME_SETUP_ENGLISH": "1",
                                                               "CODEX_AUTO_RESUME_PROGRESS_LINES": "1"},
                         "launch": {"pid": 9, "polls": [None]}}, installed),
            (["setup", "--edition-from", "advanced"], {"watcher_running": True}, installed),
            (["setup"], {"startup_value": "\"C:\\other\\pythonw.exe\" \"C:\\other\\watcher-launcher.py\" run"},
             installed),
            (["setup", "--replace-existing"], {"watcher_running": True,
                                               "startup_value": "\"C:\\other\\x.exe\" run"}, installed),
            (["watcher-running"], {"watcher_running": True}, None), (["watcher-running"], {"watcher_running": False}, None),
            (["watcher-running"], {"watcher_running": None, "environ": {"CODEX_AUTO_RESUME_SETUP_ENGLISH": "1"}}, None),
            (["status"], {"watcher_running": True}, None),
            (["status"], {"watcher_running": False, "startup_value": "\"C:\\other\\x.exe\" run"}, None),
            (["pending"], {}, None), (["enable"], {"watcher_running": True}, None),
            (["enable"], {"watcher_running": False}, installed), (["disable"], {}, None), (["cancel", T1], {}, None),
            (["cancel", "nope"], {}, None), (["stop"], {"watcher_running": False}, None), (["doctor"], {}, None),
            (["logs"], {}, None), (["logs", "-n", "5"], {}, None), (["logs", "--lines", "7"], {}, None),
            (["verify-home"], {}, None), (["claim-home"], {}, None),
            (["remove-entry"], {}, None), (["remove-entry"], {"addremove_unregister": True}, None),
            (["remove-entry"], {"addremove_remove_kept": True}, None),
            (["remove-entry"], {"addremove_unregister": {"raise": ["StartupError", "denied"]}}, None),
            (["desktop-shortcut", "make"], {}, None),
            (["desktop-shortcut", "make"], {"desktop_install": {"raise": ["DesktopTaken", ""]}}, None),
            (["desktop-shortcut", "remove"], {"desktop_uninstall": {"raise": ["ShortcutError", "busy"]}}, None),
            (["downgrade-state", "--to", "3", "--stop-watcher"], {}, None),
            (["downgrade-state", "--to", "4", "--stop-watcher"], {"watcher_mutex": "mutex_busy"}, None),
            (["uninstall"], {"watcher_running": False}, None), (["uninstall", "--purge"], {"watcher_running": False}, None),
            (["uninstall"], {"watcher_running": True}, None),
        ]
        for argv, world, tune in cases:
            with self.subTest(argv=argv, world=world):
                self.run_cli(argv, world=world, tune=tune)
        for kind in ("fresh", "empty"):
            for argv in (["claim-home"], ["verify-home"], ["pending"], ["watcher-running"]):
                with self.subTest(kind=kind, argv=argv):
                    self.run_cli(argv, kind=kind, world={"watcher_running": False})
        RECORD.append("plugin_setup commands: %d runs equal so far, %d Host/Outside calls" % (COUNTS["runs"],
                                                                                             COUNTS["calls"]))


shutil, tempfile, core, reference  # noqa: B018 - shared helpers of the other diffs
