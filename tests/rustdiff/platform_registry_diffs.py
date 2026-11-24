"""Platform diffs, registry and shortcut writers (S3.1): every call recorded, in both implementations, behind a stand-in.

Brief rule 3: nothing here opens the real per-user registry. The reference runs with `winreg` replaced by `FAKE`
below - an in-memory registry that records every call, `OpenKey`, `CreateKeyEx`, `QueryValueEx`, `SetValueEx`,
`DeleteValue`, `DeleteKey` and each close - and the Rust side runs on `FakeRegistry`, which keeps the same rules and
records the same calls. A scenario is a seed, some refusals and a list of steps; both sides run it and answer the
results, the calls and the store. Equal means the Rust writers make exactly the calls the Python writers make.

The real Win32 writer (`WinRegistry`) is held to the stand-in by a Rust test on a private hive of a scratch file
(`RegLoadAppKey`), which never opens HKCU: `cargo test -p car-platform --test registry_hive`.

The shortcut writers run behind a recording starter: the reference with `subprocess.run` replaced, the probe with its
recording starter. Neither starts PowerShell; what is compared is the command line, the environment variables the
values travel in, the creation flags and the timeout, and what the writers answer and refuse.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import unittest

from rustdiff import reference
from rustdiff.platform_diffs import RECORD, Base, ref

FAKE = r'''
import os, sys, winreg as _real

KEY_READ = 0x20019
KEY_SET_VALUE = 0x2
KEY_WOW64_64KEY = 0x100
REG_SZ, REG_EXPAND_SZ, REG_DWORD = 1, 2, 4


class Key:
    def __init__(self, owner, slot):
        self.owner, self.slot = owner, slot

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        self.owner.calls.append(["Close", self.slot])


class Winreg:
    HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE = "HKCU", "HKLM"
    KEY_READ, KEY_SET_VALUE, KEY_WOW64_64KEY = KEY_READ, KEY_SET_VALUE, KEY_WOW64_64KEY
    REG_SZ, REG_EXPAND_SZ, REG_DWORD = REG_SZ, REG_EXPAND_SZ, REG_DWORD

    def __init__(self, request):
        self.keys, self.calls = {}, []
        self.deny_keys = {"%s|%s" % (r, p) for r, p in request.get("deny_keys", [])}
        self.deny_values = {("%s|%s" % (r, p), n) for r, p, n in request.get("deny_values", [])}
        for root, path, values in request.get("seed", []):
            self._create(root, path)
            self.keys["%s|%s" % (root, path)].update({n: tuple(v) for n, v in values.items()})

    def _create(self, root, path):
        so_far = []
        for part in path.split("\\"):
            so_far.append(part)
            self.keys.setdefault("%s|%s" % (root, "\\".join(so_far)), {})

    def ExpandEnvironmentStrings(self, text):
        return _real.ExpandEnvironmentStrings(text)

    def OpenKey(self, root, path, reserved=0, access=KEY_READ):
        slot = "%s|%s" % (root, path)
        self.calls.append(["OpenKey", root, path, access])
        if slot in self.deny_keys:
            raise PermissionError(5, "denied")
        if slot not in self.keys:
            raise FileNotFoundError(2, "not found")
        return Key(self, slot)

    def CreateKeyEx(self, root, path, reserved=0, access=KEY_SET_VALUE):
        slot = "%s|%s" % (root, path)
        self.calls.append(["CreateKeyEx", root, path, access])
        if slot in self.deny_keys:
            raise PermissionError(5, "denied")
        self._create(root, path)
        return Key(self, slot)

    def QueryValueEx(self, key, name):
        self.calls.append(["QueryValueEx", key.slot, name])
        if (key.slot, name) in self.deny_values:
            raise PermissionError(5, "denied")
        if name not in self.keys.get(key.slot, {}):
            raise FileNotFoundError(2, "not found")
        return self.keys[key.slot][name]

    def SetValueEx(self, key, name, reserved, kind, value):
        self.calls.append(["SetValueEx", key.slot, name, kind, value])
        self.keys.setdefault(key.slot, {})[name] = (value, kind)

    def DeleteValue(self, key, name):
        self.calls.append(["DeleteValue", key.slot, name])
        if name not in self.keys.get(key.slot, {}):
            raise FileNotFoundError(2, "not found")
        del self.keys[key.slot][name]

    def DeleteKey(self, root, path):
        slot = "%s|%s" % (root, path)
        self.calls.append(["DeleteKey", root, path])
        if slot in self.deny_keys:
            raise PermissionError(5, "denied")
        if slot not in self.keys:
            raise FileNotFoundError(2, "not found")
        if any(other.startswith(slot + "\\") for other in self.keys):
            raise PermissionError(5, "has subkeys")
        del self.keys[slot]

    def store(self):
        return {slot: {n: list(v) for n, v in values.items()} for slot, values in self.keys.items()}
'''

REGISTRY_SCRIPT = FAKE + r'''
import json
from pathlib import Path
from codex_auto_resume import addremove, startup
from codex_auto_resume.win import policykeys, textsize, userenv

request = json.load(sys.stdin)
fake = Winreg(request)
startup._winreg = lambda: fake
policykeys._winreg = lambda: fake
sys.modules["winreg"] = fake
results = []
for step in request["steps"]:
    op = step[0]
    try:
        if op == "install": result = startup.install(step[1])
        elif op == "uninstall": result = startup.uninstall()
        elif op == "current_value": result = startup.current_value()
        elif op == "aumid_registration": result = startup.aumid_registration()
        elif op == "register_aumid": result = startup.register_aumid(step[1])
        elif op == "notification_identity_owner": result = startup.notification_identity_owner(step[1])
        elif op == "unregister_aumid": result = startup.unregister_aumid()
        elif op == "protocol_value": result = startup.protocol_value()
        elif op == "install_protocol": result = startup.install_protocol(step[1])
        elif op == "uninstall_protocol": result = startup.uninstall_protocol()
        elif op == "read_key": result = startup.read_key(step[1], step[2])
        elif op == "write_key": result = startup.write_key(step[1], step[2])
        elif op == "delete_key": result = startup.delete_key(step[1])
        elif op == "ar_register": result = addremove.register(step[1], step[2], step[3], step[4])
        elif op == "ar_unregister": result = addremove.unregister(step[1])
        elif op == "ar_remove_edition": result = addremove.remove_edition(step[1], step[2])
        elif op == "ar_read": result = addremove.read(step[1])
        elif op == "policy_read": result = [{n: list(v) for n, v in place.items()} for place in policykeys.read()]
        elif op == "codex_home": result = userenv.codex_home(registry=fake)
        elif op == "text_size": result = textsize.read()
        else: result = {"error": "unknown step"}
    except startup.StartupError as error:
        result = {"error": str(error)}
    results.append(result)
json.dump({"results": results, "calls": fake.calls, "store": fake.store()}, sys.stdout, ensure_ascii=False)
'''

SHORTCUT_SCRIPT = r'''
import json, os, subprocess, sys
from pathlib import Path
from codex_auto_resume import pwsh, shortcut

request = json.load(sys.stdin)
runs = []


def fake_run(argv, **keywords):
    env = keywords.get("env") or {}
    args = {k: v for k, v in env.items() if k.upper().startswith(pwsh.PREFIX)}
    maker = len(argv) > 4 and argv[4] == shortcut._MAKER
    runs.append({"argv": list(argv), "command_line": subprocess.list2cmdline(argv), "args": args,
                 "flags": keywords.get("creationflags"), "timeout": float(keywords.get("timeout")), "maker": maker,
                 "streams": [keywords.get("stdin"), keywords.get("stdout"), keywords.get("stderr")],
                 "shell": keywords.get("shell")})
    if maker:
        if request.get("maker_code", 0) == 0 and "CODEX_AUTO_RESUME_ARG_LNK" in args:
            Path(args["CODEX_AUTO_RESUME_ARG_LNK"]).write_bytes(b"lnk")
        return subprocess.CompletedProcess(argv, request.get("maker_code", 0))
    return subprocess.CompletedProcess(argv, request.get("reader_code", 0))


pwsh.subprocess.run = fake_run
results = []
for step in request["steps"]:
    op = step[0]
    try:
        if op == "install": result = shortcut.install(Path(step[1]), step[2], Path(step[3]) if step[3] else None, step[4], step[5])
        elif op == "install_desktop":
            result = shortcut.install_desktop(Path(step[1]), Path(step[2]), step[3], Path(step[4]) if step[4] else None, step[5], step[6])
        elif op == "uninstall_desktop": result = shortcut.uninstall_desktop(Path(step[1]))
        elif op == "uninstall": result = shortcut.uninstall()
        elif op == "shortcut_path": result = str(shortcut.shortcut_path())
        elif op == "desktop_path": result = str(shortcut.desktop_path()) if shortcut.desktop_path() else None
        else: result = {"error": "unknown step"}
    except shortcut.DesktopTaken as error:
        result = {"error": str(error), "taken": True}
    except shortcut.ShortcutError as error:
        result = {"error": str(error), "taken": False}
    results.append(result)
json.dump({"results": results, "runs": runs}, sys.stdout, ensure_ascii=False)
'''

PWSH_SCRIPT = r'''
import json, os, subprocess, sys
from codex_auto_resume import pwsh

request = json.load(sys.stdin)
runs = []


def fake_run(argv, **keywords):
    env = keywords.get("env") or {}
    runs.append({"argv": list(argv), "command_line": subprocess.list2cmdline(argv),
                 "args": {k: v for k, v in env.items() if k.upper().startswith(pwsh.PREFIX)},
                 "flags": keywords.get("creationflags"), "timeout": float(keywords.get("timeout")), "maker": False})
    return subprocess.CompletedProcess(argv, 7)


pwsh.subprocess.run = fake_run
os.environ["CODEX_AUTO_RESUME_ARG_STALE"] = "left by a parent"
try:
    outcome = {"code": pwsh.run(request["script"], {n: v for n, v in request["values"]}, timeout=request["timeout"])}
except pwsh.PowerShellError as error:
    outcome = {"error": str(error)}
json.dump({"outcome": outcome, "runs": runs, "executable": pwsh.executable()}, sys.stdout, ensure_ascii=False)
'''

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
PROTOCOL = r"Software\Classes\codex-auto-resume"
PROTOCOL_COMMAND = PROTOCOL + r"\shell\open\command"
AUMID = r"Software\Classes\AppUserModelId\CodexAutoResume.Watcher"
UNINSTALL = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\CodexAutoResume"
POLICY = r"Software\Policies\CodexAutoResume"
# The editions the reference knows; the Rust side names none of its own, so it is told them.
EDITIONS = ["standard", "advanced"]


class Registries(Base):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.home = cls.scratch / "install home"
        (cls.home / "uninstall").mkdir(parents=True)
        (cls.home / "uninstall" / "install.ps1").write_text("# kept", encoding="utf-8")
        (cls.home / "codex-auto-resume.ico").write_bytes(b"ico")
        (cls.home / "CodexAutoResumeSettings.exe").write_bytes(b"exe")
        cls.other = cls.scratch / "other home"
        (cls.other / "uninstall").mkdir(parents=True)
        (cls.other / "uninstall" / "install.ps1").write_text("# kept", encoding="utf-8")
        (cls.other / "plugin.json").write_text(json.dumps({"interface": {"displayName": " Codex Auto Resume Advanced "}}),
                                               encoding="utf-8-sig")
        (cls.other / "broken.json").write_text("{not json", encoding="utf-8")
        cls.icon = cls.home / "codex-auto-resume.ico"

    def both(self, scenario: dict):
        want = ref(REGISTRY_SCRIPT, scenario, self.profile)
        with self.probe() as probe:
            got = probe.ask("registry", **scenario)
        self.assertEqual(got["results"], want["results"], "results")
        self.assertEqual(got["calls"], want["calls"], "calls recorded")
        self.assertEqual(got["store"], want["store"], "store left")
        return want

    def test_run_value(self):
        command = '"C:\\Program Files\\Codex Auto Resume\\runtime\\pythonw.exe" "C:\\x\\auto_resume.py" run'
        want = self.both({"steps": [["current_value"], ["install", command], ["current_value"], ["install", command],
                                    ["install", command + " --again"], ["uninstall"], ["uninstall"], ["current_value"]]})
        self.assertEqual(want["results"][:3], [None, True, command])
        self.both({"seed": [["HKCU", RUN_KEY, {"CodexAutoResume": [4, 4]}]],
                   "steps": [["current_value"], ["install", command], ["uninstall"]]})
        self.both({"deny_keys": [["HKCU", RUN_KEY]], "steps": [["current_value"], ["install", command], ["uninstall"]]})
        self.both({"seed": [["HKCU", RUN_KEY, {}]], "deny_values": [["HKCU", RUN_KEY, "CodexAutoResume"]],
                   "steps": [["current_value"], ["install", command], ["uninstall"]]})

    def test_aumid_and_protocol(self):
        steps = [["aumid_registration"], ["register_aumid", None], ["aumid_registration"], ["register_aumid", None],
                 ["register_aumid", str(self.icon)], ["register_aumid", str(self.icon)], ["aumid_registration"],
                 ["notification_identity_owner", str(self.home)], ["notification_identity_owner", str(self.other)],
                 ["unregister_aumid"], ["unregister_aumid"], ["notification_identity_owner", str(self.home)]]
        want = self.both({"steps": steps})
        self.assertEqual(want["results"][1], True)
        self.both({"seed": [["HKCU", AUMID, {"DisplayName": ["Codex Auto Resume", 1]}]],
                   "steps": [["notification_identity_owner", str(self.home)], ["register_aumid", str(self.icon)]]})
        self.both({"deny_keys": [["HKCU", AUMID]], "steps": steps[:4]})
        command = '"x.exe" --home "%s" --quiet activate "%%1"' % self.home
        self.both({"steps": [["protocol_value"], ["install_protocol", command], ["protocol_value"], ["install_protocol", command],
                             ["uninstall_protocol"], ["uninstall_protocol"], ["protocol_value"]]})
        self.both({"seed": [["HKCU", PROTOCOL + r"\shell\open\extra", {}], ["HKCU", PROTOCOL_COMMAND, {"": [command, 1]}]],
                   "steps": [["uninstall_protocol"], ["protocol_value"]]})
        self.both({"deny_keys": [["HKCU", PROTOCOL_COMMAND]], "steps": [["protocol_value"], ["install_protocol", command]]})

    def test_a_keys_own_values(self):
        path = r"Software\Example\Key"
        self.both({"seed": [["HKCU", path, {"A": ["one", 1], "N": [5, 4]}]],
                   "steps": [["read_key", path, ["A", "N", "Missing"]], ["read_key", path + "x", ["A"]],
                             ["write_key", path, {"A": "two", "B": 7}], ["read_key", path, ["A", "B"]],
                             ["delete_key", path], ["delete_key", path], ["delete_key", "Software\\Example"]]})
        self.both({"deny_keys": [["HKCU", path]], "steps": [["read_key", path, ["A"]], ["write_key", path, {"A": "x"}],
                                                           ["delete_key", path]]})

    def test_the_uninstall_entry(self):
        home, other = str(self.home), str(self.other)
        steps = [["ar_read", "standard"], ["ar_register", home, "standard", "0.6.26", "Codex Auto Resume"],
                 ["ar_read", "standard"], ["ar_register", home, "standard", "0.6.26", "Codex Auto Resume"],
                 ["ar_register", home, "standard", "0.6.27", None], ["ar_register", home, "advanced", "0.6.27", "Codex Auto Resume Advanced"],
                 ["ar_read", "advanced"], ["ar_read", "standard"], ["ar_register", other, "advanced", "0.6.27", None],
                 ["ar_register", home, "standard", "unknown", None], ["ar_register", home, "other", "1", None],
                 ["ar_remove_edition", "advanced", home], ["ar_unregister", home], ["ar_unregister", home]]
        self.both({"steps": steps, "editions": EDITIONS})
        foreign = {"InstallLocation": [other, 1], "UninstallString": ["cmd /c exit", 1]}
        self.both({"editions": EDITIONS, "seed": [["HKCU", UNINSTALL, foreign]], "steps": steps[:4] + [["ar_unregister", home], ["ar_unregister", other]]})
        self.both({"editions": EDITIONS, "deny_keys": [["HKCU", UNINSTALL]], "steps": steps[:3]})

    def test_display_name(self):
        script = ("import json,sys\nfrom pathlib import Path\nfrom codex_auto_resume import addremove\n"
                  "p=json.load(sys.stdin)\njson.dump([addremove.display_name(Path(x)) for x in p],sys.stdout,ensure_ascii=False)")
        files = [str(self.other / "plugin.json"), str(self.other / "broken.json"), str(self.other / "missing.json")]
        for index, body in enumerate(['{"interface": {"displayName": 5}}', '{"interface": {"displayName": null}}',
                                      '{"interface": {"displayName": "  "}}', '{"interface": {}}', '[]',
                                      '{"interface": {"displayName": "한국어 이름"}}']):
            path = self.other / ("m%d.json" % index)
            path.write_text(body, encoding="utf-8")
            files.append(str(path))
        want = ref(script, files, self.profile)
        with self.probe() as probe:
            self.assertEqual([probe.ask("display_name", path=path) for path in files], want)

    def test_policy_keys_codex_home_and_text_size(self):
        place = [["HKLM", POLICY, {"DisableAutoResume": [1, 4], "QuietHours": ["22:00-07:00", 1], "MaxRecoveryAttempts": [3, 4]}],
                 ["HKCU", POLICY, {"ForceObserveOnly": [1, 4], "DisablePowerAction": [0, 4]}]]
        steps = [["policy_read"]]
        self.both({"seed": place, "steps": steps})
        self.both({"seed": place, "deny_values": [["HKLM", POLICY, "QuietHours"]], "steps": steps})
        self.both({"seed": place, "deny_keys": [["HKCU", POLICY]], "steps": steps})
        self.both({"steps": steps})
        env = r"Environment"
        for values in ({"CODEX_HOME": ["D:\\codex home", 1]}, {"CODEX_HOME": ["%SystemRoot%\\codex", 2]}, {"CODEX_HOME": ["  ", 1]},
                       {"CODEX_HOME": [5, 4]}, {}):
            self.both({"seed": [["HKCU", env, values]], "steps": [["codex_home"]]})
        self.both({"steps": [["codex_home"]]})
        access = r"Software\Microsoft\Accessibility"
        for value in ([150, 4], [100, 4], [225, 4], [99, 4], [226, 4], ["150", 1]):
            self.both({"seed": [["HKCU", access, {"TextScaleFactor": value}]], "steps": [["text_size"]]})
        self.both({"steps": [["text_size"]]})
        RECORD.append("registry: calls, results and store equal to the reference on 30 scenarios behind a stand-in; HKCU never opened")


class Shortcuts(Base):
    def both(self, scenario: dict, env: dict | None = None):
        before = {entry: entry.read_bytes() for folder in (env or {}).values() for entry in Path(folder).rglob("*.lnk")}
        want = ref(SHORTCUT_SCRIPT, scenario, self.profile, env)
        # The second side starts where the first did: the shortcuts the reference wrote are taken away again.
        for folder in (env or {}).values():
            for entry in Path(folder).rglob("*.lnk"):
                entry.unlink()
        for entry, body in before.items():
            entry.write_bytes(body)
        with self.probe(env) as probe:
            got = probe.ask("shortcut", **scenario)
        self.assertEqual(got["results"], want["results"], "results")
        self.assertEqual(len(got["runs"]), len(want["runs"]))
        for rust, python in zip(got["runs"], want["runs"]):
            for key in ("streams", "shell"):
                python.pop(key, None)
            self.assertEqual(rust, python)
        return got, want

    def test_the_scripts_are_the_references(self):
        script = "import json,sys\nfrom codex_auto_resume import shortcut\njson.dump([shortcut._MAKER, shortcut._READER],sys.stdout)"
        maker, reader = ref(script, None, self.profile)
        with self.probe() as probe:
            got = probe.ask("scripts")
        self.assertEqual((got["maker"], got["reader"]), (maker, reader))

    def test_start_menu_and_desktop_writers(self):
        base = self.scratch / "shortcuts"
        (base / "appdata").mkdir(parents=True)
        (base / "desktop").mkdir()
        home = base / "home"
        (home / "app").mkdir(parents=True)
        target = home / "app" / "Codex Auto Resume's.exe"
        target.write_text("x", encoding="utf-8")
        outside = base / "outside.exe"
        outside.write_text("x", encoding="utf-8")
        icon = home / "app.ico"
        icon.write_bytes(b"i")
        env = {"APPDATA": str(base / "appdata"), "CODEX_AUTO_RESUME_DESKTOP": str(base / "desktop")}
        steps = [["shortcut_path"], ["desktop_path"], ["install", str(target), "--page", str(icon), None, "Codex Auto Resume"],
                 ["install", str(target), "", None, "Other.Aumid", ""], ["uninstall"], ["uninstall"],
                 ["install_desktop", str(home), str(target), "", str(icon), None, "d"],
                 ["install_desktop", str(home), str(outside), "", None, None, "d"], ["uninstall_desktop", str(home)],
                 ["uninstall_desktop", str(home)], ["install_desktop", str(home), str(target), "", None, None, "d"]]
        got, _want = self.both({"steps": steps, "reader_code": 0, "maker_code": 0}, env)
        self.assertTrue(any(run["maker"] for run in got["runs"]))
        for run in got["runs"]:
            self.assertEqual(run["flags"] & 0x08000000, 0x08000000, "CREATE_NO_WINDOW on every shell start")
        # A shortcut of another's on the Desktop stays as it is (the reader says 3: not inside), and a shell that fails or
        # cannot be read is a refusal, never a yes.
        link = base / "desktop" / "Codex Auto Resume.lnk"
        link.write_bytes(b"theirs")
        taken, _ = self.both({"steps": [["install_desktop", str(home), str(target), "", None, None, "d"],
                                        ["uninstall_desktop", str(home)]], "reader_code": 3}, env)
        self.assertEqual(taken["results"][0]["taken"], True)
        self.both({"steps": [["install_desktop", str(home), str(target), "", None, None, "d"],
                             ["uninstall_desktop", str(home)]], "reader_code": 9}, env)
        self.both({"steps": [["uninstall_desktop", str(home)]], "reader_code": 0}, env)
        link.unlink(missing_ok=True)
        self.both({"steps": [["install", str(target), "", None, None, "d"]], "maker_code": 1}, env)
        RECORD.append("shortcuts: %d shell runs recorded equal (command line, values, flags, timeout); every one CREATE_NO_WINDOW"
                      % len(got["runs"]))

    def test_pwsh_run(self):
        script = "Write-Output $env:CODEX_AUTO_RESUME_ARG_A"
        stale = {"CODEX_AUTO_RESUME_ARG_STALE": "left by a parent"}
        for values in ([["A", "x y"], ["B", "\ud55c\uad6d\uc5b4"], ["C", "it's"]], [["a", "x"]], [["A", "has\u0000nul"]],
                       [["A", "x" * 16001]], [["A", None]], [["A" * 41, "x"]], [["A" * 42, "x"]]):
            request = {"script": script, "values": values, "timeout": 30}
            want = ref(PWSH_SCRIPT, request, self.profile, stale)
            with self.probe(stale) as probe:
                got = probe.ask("pwsh", **request)
            self.assertEqual(got["outcome"], want["outcome"], values[0][0][:3])
            self.assertEqual(got["executable"], want["executable"])
            self.assertEqual(got["runs"], want["runs"])
            for run in got["runs"]:
                self.assertNotIn("CODEX_AUTO_RESUME_ARG_STALE", run["args"], "a parent's stale value never reaches the child")
                self.assertEqual(run["flags"], 0x08000000)
        error = {"error": "invalid argument name"}
        with self.probe() as probe:
            self.assertEqual(probe.ask("pwsh_names", names=["A", "AB_1", "a", "1A", "A" * 41, "A" * 42, ""]),
                             ["$env:CODEX_AUTO_RESUME_ARG_A", "$env:CODEX_AUTO_RESUME_ARG_AB_1", error, error,
                              "$env:CODEX_AUTO_RESUME_ARG_" + "A" * 41, error, error])


if __name__ == "__main__":
    unittest.main(verbosity=2)
