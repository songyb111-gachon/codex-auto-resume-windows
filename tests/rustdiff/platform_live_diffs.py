"""Platform diffs, the rest (S3.1): no window, pure rules, live questions, and the named objects held across both.

* NoWindow     - every process the Rust core starts has CREATE_NO_WINDOW: the creation flags the starter applied are read
                 back, the constants equal the reference's, and no source file of the Rust core but `spawn.rs` has a
                 `Command::new` (PLAN 6.7; the reference's own test is tests/test_no_console_windows.py).
* PureRules    - kernel (`decide_host`, `host_verdict`, `trusted_owner`), acl (`verdict`, `is_sandbox_group`, SDDL
                 descriptors that exist only in a process), authenticode (`reason`, `signer` of a few files), typeface.
* LiveQuestions- the read-only questions Windows is asked (network, sign-in, power, sessions, processes, the Restart
                 Manager, a folder's identity and access list) put to both implementations at once. Nothing is written,
                 no window is shown, power is never acted on (`act` refuses).
* Held         - a mutex, the stop, wake and demo events and the home lock made by one implementation and met by the other,
                 in both directions: the same names, the same refusals.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import random
import subprocess
import sys
import time
import unittest

import released
from rustdiff import core, refguard, reference
from rustdiff.platform_diffs import NO_WINDOW, RECORD, Base, Probe, ref

CRATES = core.ROOT / "rust" / "crates"


# ------------------------------------------------------------------------------------------------ no window

class NoWindow(Base):
    def test_constants_equal_the_references(self):
        script = ("import json,sys,subprocess\nfrom codex_auto_resume.win import kernel\n"
                  "json.dump({'no_window':subprocess.CREATE_NO_WINDOW,'kernel':kernel.NO_WINDOW,'breakaway':kernel.CREATE_BREAKAWAY_FROM_JOB,"
                  "'job':[kernel.JOB_BREAKAWAY_OK,kernel.JOB_SILENT_BREAKAWAY_OK,kernel.JOB_KILL_ON_CLOSE],"
                  "'appmodel':kernel.APPMODEL_ERROR_NO_PACKAGE},sys.stdout)")
        want = ref(script, None, self.profile)
        with self.probe() as probe:
            got = probe.ask("constants")
        self.assertEqual(got["no_window"], want["no_window"])
        self.assertEqual(got["no_window"], want["kernel"])
        self.assertEqual((got["breakaway"], got["job"], got["appmodel"]), (want["breakaway"], want["job"], want["appmodel"]))

    def test_every_process_started_has_create_no_window(self):
        with self.probe() as probe:
            for extra in (0, 0x01000000, 0x00000008 | 0x00000200, 0x08000000):
                self.assertEqual(probe.ask("spawn_flags", argv=["x.exe", "a b"], extra=extra)["flags"] & 0x08000000, 0x08000000)
            flags = []
            for argv in ([sys.executable, "-c", "pass"], ["cmd", "/c", "exit", "0"]):
                done = probe.ask("echo", argv=argv)
                self.assertEqual(done["code"], 0)
                flags.append(done["flags"])
        self.assertEqual(flags, [0x08000000, 0x08000000], "the creation flags the starter applied to real children")
        RECORD.append("no window: every starter flag set read back = CREATE_NO_WINDOW (0x08000000), also with breakaway/detached added")

    def test_no_command_new_outside_the_one_starter(self):
        """PLAN 6.7: one car-platform function starts every child; a test reads the source for any other."""
        offenders = []
        for crate in sorted(CRATES.iterdir()):
            for folder in ("src", "examples"):
                for source in sorted((crate / folder).rglob("*.rs")) if (crate / folder).is_dir() else []:
                    text = source.read_text(encoding="utf-8")
                    for needle in ("Command::new", "CreateProcessW", "CreateProcessA", "ShellExecute", "CreateProcessAsUser"):
                        if needle in text and source != CRATES / "car-platform" / "src" / "spawn.rs":
                            # a doc comment that names the rule is not a call
                            code = [line for line in text.splitlines() if needle in line and not line.lstrip().startswith("//")]
                            if code:
                                offenders.append((source.relative_to(core.ROOT).as_posix(), needle))
        self.assertEqual(offenders, [])
        spawn = (CRATES / "car-platform" / "src" / "spawn.rs").read_text(encoding="utf-8")
        self.assertEqual(spawn.count("Command::new("), 1)
        self.assertIn("command.creation_flags(flags)", spawn)
        self.assertIn("self.extra_flags | CREATE_NO_WINDOW", spawn)


# ------------------------------------------------------------------------------------------------ pure rules

def random_table(rng: random.Random):
    pids = rng.sample(range(1, 40), rng.randint(1, 8))
    table = {}
    for pid in pids:
        parent = rng.choice(pids + [0, 99])
        created = rng.choice([0, 0, 100, 200, 300, 400, 116444736000000000 + rng.randint(0, 10 ** 9)])
        family = rng.choice([None, None, None, "OpenAI.Codex_2p2nqsd0c76g0", "Claude_pzs8sxrjxfjjc", "bad family", "x_short"])
        table[pid] = (parent, created, family)
    return pids, table


class PureRules(Base):
    def test_host_walk(self):
        rng = random.Random(11)
        cases = []
        for _ in range(600):
            pids, table = random_table(rng)
            cases.append({"start": rng.choice(pids + [77]), "table": [[pid, *row] for pid, row in table.items()],
                          "started_by": rng.choice([None, 11644473600.0 + 5.0, 1.0e9])})
        families = [None, "", "OpenAI.Codex_2p2nqsd0c76g0", "A_b", "_x", "plain", "a_b_c", "한_x"]
        script = r'''
import json, sys
from codex_auto_resume.win import kernel
request = json.load(sys.stdin)
out = []
for case in request["cases"]:
    table = {row[0]: (row[1], row[2], row[3]) for row in case["table"]}
    out.append([kernel.decide_host(case["start"], table), kernel.host_verdict(case["start"], table, case["started_by"])])
owners = [[o, u, kernel.trusted_owner(o, u)] for o in (None, "", "S-1-5-21-1", "S-1-5-32-544", "S-1-5-18", "S-1-1-0")
          for u in (None, "", "S-1-5-21-1", "S-1-5-21-2")]
json.dump({"walk": out, "names": [kernel.app_name(f) for f in request["families"]], "owners": owners}, sys.stdout)
'''
        want = ref(script, {"cases": cases, "families": families}, self.profile)
        with self.probe() as probe:
            for case, (decided, verdict) in zip(cases, want["walk"]):
                self.assertEqual(probe.ask("decide_host", **{k: case[k] for k in ("start", "table")}), decided)
                self.assertEqual(probe.ask("host_verdict", **case), verdict)
            self.assertEqual([probe.ask("app_name", family=f) for f in families], want["names"])
            for owner, user, trusted in want["owners"]:
                self.assertEqual(probe.ask("trusted_owner", owner=owner, user=user), trusted)

    def test_access_list_rules(self):
        rng = random.Random(5)
        sids = ["S-1-5-18", "S-1-5-32-544", "S-1-3-0", "S-1-1-0", "S-1-5-21-1-2-3-1001", "S-1-5-21-1-2-3-1002",
                "S-1-15-2-1-2", "S-1-5-11"]
        masks = [0x001F01FF, 0x001200A9, 0x80000000, 0x20000000, 0x120089, 0x10000, 0x40000000, 0xFFFFFFFF, 0x12019F]
        cases = []
        for _ in range(500):
            allowed = None if rng.random() < 0.1 else [[rng.choice(sids), rng.choice(masks)] for _ in range(rng.randint(0, 5))]
            cases.append({"allowed": allowed, "own": rng.choice(["S-1-5-21-1-2-3-1001", None, ""]),
                          "sandbox": rng.sample(sids, rng.randint(0, 3))})
        names = [("CodexSandboxUsers", "PC", 4, "PC"), ("codexsandboxusers", "pc", 4, "PC"), ("CodexSandboxUsers", "PC", 1, "PC"),
                 ("CodexSandboxUsers", "OTHER", 4, "PC"), ("Other", "PC", 4, "PC"), ("CodexSandboxUsers", "PC", 4, "")]
        sddls = ["D:(A;;FA;;;BA)(A;;FR;;;WD)", "D:(A;;FA;;;S-1-5-21-1-2-3-1001)(D;;FA;;;WD)", "D:", "D:NO_ACCESS_CONTROL",
                 "D:(OA;;FA;;;BA)", "O:BAG:BAD:(A;;0x1200a9;;;S-1-5-21-1-2-3-1002)", "not sddl", "D:(A;OICI;FA;;;SY)(A;;GR;;;AU)"]
        script = r'''
import json, sys
from codex_auto_resume.win import acl
request = json.load(sys.stdin)
verdicts = [acl.verdict(None if c["allowed"] is None else [tuple(e) for e in c["allowed"]], c["own"], frozenset(c["sandbox"]))
            for c in request["cases"]]
groups = [acl.is_sandbox_group(*n) for n in request["names"]]
described = [acl.described_entries(s) for s in request["sddls"]]
table = {"S-1-5-21-1-2-3-1001": ("CodexSandboxUsers", "PC", 4), "S-1-5-21-1-2-3-1002": ("Someone", "PC", 1)}
sandbox = sorted(acl.sandbox_sids([("S-1-5-21-1-2-3-1001", 1), ("S-1-5-21-1-2-3-1002", 1), ("S-1-5-18", 1)],
                                  account=table.get, computer="PC"))
json.dump({"verdicts": verdicts, "groups": groups, "described": described, "sandbox": sandbox}, sys.stdout)
'''
        want = ref(script, {"cases": cases, "names": names, "sddls": sddls}, self.profile)
        with self.probe() as probe:
            for case, verdict in zip(cases, want["verdicts"]):
                self.assertEqual(probe.ask("acl_verdict", **case), verdict, case)
            self.assertEqual([probe.ask("is_sandbox_group", name=n, domain=d, kind=k, computer=c) for n, d, k, c in names],
                             want["groups"])
            got = [probe.ask("described_entries", sddl=sddl) for sddl in sddls]
            self.assertEqual([None if row is None else [list(e) for e in row] for row in got],
                             [None if row is None else [list(e) for e in row] for row in want["described"]])
            self.assertEqual(probe.ask("sandbox_sids", entries=[["S-1-5-21-1-2-3-1001", 1], ["S-1-5-21-1-2-3-1002", 1], ["S-1-5-18", 1]],
                                       accounts={"S-1-5-21-1-2-3-1001": ["CodexSandboxUsers", "PC", 4], "S-1-5-21-1-2-3-1002": ["Someone", "PC", 1]},
                                       computer="PC"), want["sandbox"])

    def test_authenticode_reasons_and_signers(self):
        statuses = [0, 0x800B0100, 0x800B0003, 0x800B0001, 0x80096010, 0x80096011, 0x80092003, 0x80070002, 0x80070005,
                    0x80070020, 0x800B0109, 0x800B010A, 0x12345678, -2146762496, -2146885616]
        windows = Path(os.environ.get("SystemRoot", r"C:\Windows"))
        files = [Path(sys.executable), windows / "System32" / "notepad.exe", windows / "System32" / "kernel32.dll",
                 windows / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe", self.scratch / "plain.txt",
                 self.scratch / "missing.exe"]
        (self.scratch / "plain.txt").write_text("not signed", encoding="utf-8")
        script = ("import json,sys\nfrom codex_auto_resume.win import authenticode\nr=json.load(sys.stdin)\nout=[]\n"
                  "for p in r['files']:\n    try: out.append({'ok': authenticode.signer(p)})\n"
                  "    except Exception as e: out.append({'error': str(e)})\n"
                  "json.dump({'reasons':[authenticode.reason(s) for s in r['statuses']],'signers':out},sys.stdout)")
        want = ref(script, {"statuses": statuses, "files": [str(f) for f in files]}, self.profile)
        with self.probe() as probe:
            self.assertEqual([probe.ask("auth_reason", status=s) for s in statuses], want["reasons"])
            self.assertEqual([probe.ask("signer", path=str(f)) for f in files], want["signers"])

    def test_typeface_rules(self):
        rng = random.Random(3)
        pool = [chr(c) for c in list(range(0x20, 0x250)) + list(range(0x400, 0x460)) + [0xAD, 0x200B, 0x200E, 0x202A, 0x2066,
                0xFEFF, 0x0600, 0x061C, 0x180E, 0x3000, 0xAC00, 0x3042, 0x4E00, 0xE01, 0xFFFF, 0xFFF9, 0x0085, 0x00A0, 0x1680, 0x2028]]
        texts = ["".join(rng.choice(pool) for _ in range(rng.randint(0, 20))) for _ in range(200)]
        script = ("import json,sys\nfrom codex_auto_resume.win import typeface\nr=json.load(sys.stdin)\n"
                  "lacking={'Malgun Gothic':'ế ї ą ş','Yu Gothic UI':'ế','Segoe UI':'한'}\n"
                  "def lacks(face,text): return ''.join(c for c in text if c in lacking.get(face,''))\n"
                  "installed=lambda face: face in ('Malgun Gothic','Leelawadee UI')\n"
                  "json.dump({'letters':typeface.letters(r['texts']),'each':[typeface.letters([t]) for t in r['texts']],"
                  "'faces':[typeface.face_for(f,t,lacks) for f in ('Malgun Gothic','Segoe UI','segoe ui ','Yu Gothic UI','')"
                  " for t in ('abc','ế','한','ąş','')],"
                  "'language':[typeface.language_face(l,f,t,lacks,installed) for l in (None,'ko','ja','th','en') for f in ('Malgun Gothic','Segoe UI')"
                  " for t in ('abc','ế','한')]},sys.stdout,ensure_ascii=False)")
        want = ref(script, {"texts": texts}, self.profile)
        lacking = {"Malgun Gothic": "ế ї ą ş", "Yu Gothic UI": "ế", "Segoe UI": "한"}
        with self.probe() as probe:
            self.assertEqual(probe.ask("letters", texts=texts), want["letters"])
            self.assertEqual([probe.ask("letters", texts=[t]) for t in texts], want["each"])
            faces = [probe.ask("face_for", face=f, text=t, lacks=lacking) for f in ("Malgun Gothic", "Segoe UI", "segoe ui ", "Yu Gothic UI", "")
                     for t in ("abc", "ế", "한", "ąş", "")]
            self.assertEqual(faces, want["faces"])
            language = [probe.ask("language_face", locale=l, face=f, text=t, lacks=lacking, installed=["Malgun Gothic", "Leelawadee UI"])
                        for l in (None, "ko", "ja", "th", "en") for f in ("Malgun Gothic", "Segoe UI") for t in ("abc", "ế", "한")]
            self.assertEqual(language, want["language"])


# ------------------------------------------------------------------------------------------ live questions

LIVE_SCRIPT = r'''
import json, os, sys, time
from codex_auto_resume.win import acl, handover, inventory, kernel, network, ownprocess, power, powerdown, homelock
request = json.load(sys.stdin)
context = kernel.process_context()
def named(names, families):
    return sorted([[p["pid"], p["parent"], p["path"], p["created"], p["family"]] for p in kernel.processes_named(names, families)])
out = {
    "internet": network.internet(), "connectivity": network.connectivity(), "sign_in": ownprocess.sign_in(),
    "awake": power.awake_seconds(), "mains": power.on_mains(), "idle": powerdown.idle_seconds(),
    "sessions": powerdown.other_sessions(), "privilege": powerdown.holds_shutdown_privilege(),
    "available": [list(powerdown.available(a)) for a in ("sleep", "hibernate", "shut_down", "nonsense")],
    "install_in_progress": homelock.install_in_progress(), "rm_available": inventory.restart_manager_available(),
    "context": context, "booted_at": ownprocess.booted_at(),
    "memory_known": ownprocess.memory() is not None,
    "identity": [kernel.process_identity(p) for p in request["pids"]],
    "named": named(request["names"], request["families"]),
    "images": sorted(set(kernel.running_images() or [])),
    "host": [kernel.host_app(p) for p in request["pids"]],
    "users": inventory.resource_users(*request["held"]),
    "windows_of": handover.windows_of(request["exe"]), "spelled": [handover.spelled(p) for p in request["spell"]],
    "request_text": [handover.request_text(None), handover.request_text("home"), handover.request_text("home", "row 1")],
    "state_access": [acl.state_access(p) for p in request["dirs"]],
    "sids": [acl.allowed_sids(p) for p in request["dirs"]],
}
json.dump(out, sys.stdout, ensure_ascii=False)
'''


class LiveQuestions(Base):
    def test_live_answers_equal(self):
        sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], creationflags=NO_WINDOW,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        held = self.scratch / "held file.txt"
        held.write_text("held", encoding="utf-8")
        holder = subprocess.Popen([sys.executable, "-c", "import sys,time; f=open(sys.argv[1],'r+'); print('held', flush=True); time.sleep(120)", str(held)],
                                  creationflags=NO_WINDOW, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            self.assertEqual(holder.stdout.readline().strip(), b"held")
            folder = self.scratch / "an access list"
            folder.mkdir()
            request = {"pids": [sleeper.pid, holder.pid], "names": ["explorer.exe", "winlogon.exe", "csrss.exe"],
                       "families": [], "held": [str(held)], "exe": str(self.scratch / "nothing.exe"),
                       "spell": [str(self.scratch / "A B" / ".." / "x"), "relative\\p", str(self.scratch).upper(), "C:\\Windows\\System32\\.."],
                       "dirs": [str(folder), os.environ.get("SystemRoot", r"C:\Windows")]}
            # this PC's process table is the subject here (explorer.exe, the test's own sleepers): asked for by name
            # (refguard.py; the engine discovery and the engine path stay refused)
            want = ref(LIVE_SCRIPT, request, self.profile, env={refguard.VARIABLE: refguard.LIVE})
            with self.probe() as probe:
                got = probe.ask("live")
                identity = [probe.ask("process_identity", pid=pid) for pid in request["pids"]]
                named = probe.ask("processes_named", names=request["names"], families=request["families"])
                images = probe.ask("running_images")
                hosts = [probe.ask("host_app", pid=pid) for pid in request["pids"]]
                users = probe.ask("resource_users", paths=request["held"])
                windows = probe.ask("windows_of", exe=request["exe"])
                spelled = [probe.ask("spelled", path=p) for p in request["spell"]]
                texts = [probe.ask("request_text"), probe.ask("request_text", page="home"), probe.ask("request_text", page="home", row="row 1")]
                access = [probe.ask("state_access", path=p) for p in request["dirs"]]
                sids = [probe.ask("allowed_sids", path=p) for p in request["dirs"]]
        finally:
            for child in (sleeper, holder):
                child.kill()
                child.wait()
                if child.stdout:
                    child.stdout.close()
        for key in ("internet", "connectivity", "sign_in", "mains", "sessions", "privilege", "available", "install_in_progress",
                    "rm_available", "context"):
            self.assertEqual(got[key], want[key], key)
        self.assertTrue(got["act_refused"] and got["memory_known"] and want["memory_known"])
        self.assertLess(abs(got["awake"] - want["awake"]), 10, "awake seconds")
        self.assertTrue(abs(got["idle"] - want["idle"]) < 10 or min(got["idle"], want["idle"]) < 10, "idle seconds")
        self.assertLess(abs(got["booted_at"] - want["booted_at"]), 5, "boot time")
        self.assertEqual([[i["pid"], i["path"], i["created"]] for i in identity],
                         [[i["pid"], i["path"], i["created"]] for i in want["identity"]])
        self.assertEqual(sorted([p["pid"], p["parent"], p["path"], p["created"], p["family"]] for p in named), want["named"])
        self.assertEqual(hosts, want["host"])
        self.assertEqual(sorted((u["pid"], u["created"]) for u in users), sorted((u["pid"], u["created"]) for u in want["users"]))
        self.assertIn(holder.pid, [u["pid"] for u in users], "the Restart Manager names the holder of the file")
        self.assertEqual(windows, want["windows_of"])
        self.assertEqual(spelled, want["spelled"])
        self.assertEqual(texts, want["request_text"])
        self.assertEqual(access, want["state_access"])
        self.assertEqual(sids, want["sids"])
        ours, theirs = set(images), set(want["images"])
        self.assertLessEqual(len(ours ^ theirs), max(12, len(theirs) // 10), "running images differ by a few short-lived programs only")
        RECORD.append("live: network, sign-in, power, sessions, privilege, job context, %d processes named, %d images, Restart Manager "
                      "holder, access lists, handover text: equal (read only)" % (len(named), len(images)))

    def test_typeface_live(self):
        pairs = [["Segoe UI", "abc ế ї"], ["Malgun Gothic", "abc ế ą ş"], ["Microsoft JhengHei UI", "абв"], ["Segoe UI", "한국어"],
                 ["No Such Face Anywhere", "abc"], ["Yu Gothic UI", "ế"], ["Leelawadee UI", "สวัสดี"]]
        faces = ["Segoe UI", "Malgun Gothic", "Yu Gothic UI", "Microsoft YaHei UI", "Leelawadee UI", "No Such Face Anywhere", ""]
        script = ("import json,sys\nfrom codex_auto_resume.win import typeface\nr=json.load(sys.stdin)\n"
                  "json.dump({'installed':[typeface.installed(f) for f in r['faces']],'lacks':[typeface.lacks(*p) for p in r['pairs']],"
                  "'ui_face':typeface.ui_face()},sys.stdout,ensure_ascii=False)")
        want = ref(script, {"faces": faces, "pairs": pairs}, self.profile)
        with self.probe() as probe:
            self.assertEqual(probe.ask("typeface_live", faces=faces, pairs=pairs), want)


# ------------------------------------------------------------------------------------- objects held across

HOLDER = r'''
import json, os, sys
from pathlib import Path
from codex_auto_resume.domain.errors import AdapterError
from codex_auto_resume.win import homelock, sync

held = {}
for line in sys.stdin:
    request = json.loads(line)
    kind, action, name = request["kind"], request["action"], request.get("name")
    try:
        if kind == "mutex" and action == "take":
            held["mutex"] = sync.Mutex(name, request.get("timeout", 0.0)).__enter__()
            result = {"ok": True, "abandoned": held["mutex"].abandoned}
        elif kind == "mutex":
            held.pop("mutex").__exit__()
            result = {"ok": True}
        elif kind in ("stop", "wake", "demo") and action == "create":
            held[kind] = {"stop": sync.StopEvent, "wake": sync.WakeEvent, "demo": sync.DemoEvent}[kind](name).__enter__()
            result = {"ok": True}
        elif kind in ("stop", "wake", "demo") and action == "signal":
            result = {"signalled": {"stop": sync.StopEvent, "wake": sync.WakeEvent, "demo": sync.DemoEvent}[kind](name).signal()}
        elif kind == "stop" and action == "wait":
            result = {"got": held["stop"].wait(request["seconds"])}
        elif kind == "wake" and action == "wait":
            result = {"got": sync.wait_any([held["wake"].handle], request["seconds"]) is not None}
        elif kind == "demo" and action == "wait":
            result = {"got": held["demo"].taken()}
        elif kind == "homelock" and action == "take":
            held["lock"] = homelock.HomeLock(request["codex_home"], request.get("base")).__enter__()
            result = {"ok": True, "identity": held["lock"].identity}
        elif kind == "homelock":
            held.pop("lock").__exit__()
            result = {"ok": True}
        else:
            result = {"error": "unknown"}
    except AdapterError as error:
        result = {"error": str(error)}
    print(json.dumps(result), flush=True)
'''


class ReferenceHolder:
    """The reference tag's own process, keeping named objects until it is told to let go."""

    def __init__(self, profile: Path):
        self.profile = profile

    def __enter__(self):
        source = released.package(reference.TAG)
        environment = reference.scratch_environment(self.profile, PYTHONPATH=str(source))
        self.process = subprocess.Popen(reference.command(HOLDER, paths=[source]), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, env=environment, cwd=str(self.profile), creationflags=NO_WINDOW)
        return self

    def ask(self, **request):
        self.process.stdin.write((json.dumps(request) + "\n").encode("utf-8"))
        self.process.stdin.flush()
        return json.loads(self.process.stdout.readline().decode("utf-8"))

    def __exit__(self, *_exc):
        try:
            self.process.stdin.close()
            self.process.wait(timeout=30)
        finally:
            if self.process.poll() is None:
                self.process.kill()
            self.process.stdout.close()
            self.process.stderr.close()


class Held(Base):
    def userprofile(self) -> str:
        return str(self.profile)

    def test_the_mutex_is_one_mutex(self):
        state = r"C:\scratch\state folder"
        with ReferenceHolder(self.profile) as python, self.probe() as rust:
            fields = {"userprofile": self.userprofile(), "name": state, "kind": "mutex"}
            self.assertEqual(python.ask(kind="mutex", action="take", name=state)["ok"], True)
            busy = rust.ask("hold", action="take", timeout=0.0, **fields)
            self.assertEqual(busy["result"], {"error": "mutex_busy"}, "Rust meets Python's mutex by the same name")
            python.ask(kind="mutex", action="release")
            self.assertEqual(rust.ask("hold", action="take", timeout=0.0, **fields)["result"], {"ok": True})
            self.assertEqual(python.ask(kind="mutex", action="take", name=state, timeout=0.0), {"error": "mutex_busy"},
                             "Python meets Rust's mutex by the same name")
            rust.ask("hold", action="release", **fields)
            self.assertEqual(python.ask(kind="mutex", action="take", name=state, timeout=0.0)["ok"], True)
            # another state folder is another mutex
            self.assertEqual(rust.ask("hold", action="take", timeout=0.0, **dict(fields, name=state + "2"))["result"], {"ok": True})

    def test_the_events_are_one_event(self):
        state = r"C:\scratch\state folder"
        with ReferenceHolder(self.profile) as python, self.probe() as rust:
            for kind in ("stop", "wake", "demo"):
                fields = {"userprofile": self.userprofile(), "name": state, "kind": kind}
                self.assertFalse(rust.ask("hold", action="signal", **fields)["signalled"], "no watcher holds it yet: false")
                self.assertEqual(python.ask(kind=kind, action="signal", name=state), {"signalled": False})
                # Python makes it, Rust signals it, Python is woken.
                self.assertEqual(python.ask(kind=kind, action="create", name=state), {"ok": True})
                self.assertTrue(rust.ask("hold", action="signal", **fields)["signalled"])
                self.assertTrue(python.ask(kind=kind, action="wait", seconds=3)["got"], kind + " signalled by Rust reached Python")
                # Rust makes it too (the same object), Python signals it, Rust is woken.
                self.assertEqual(rust.ask("hold", action="create", **fields)["result"], {"ok": True})
                self.assertEqual(python.ask(kind=kind, action="signal", name=state), {"signalled": True})
                self.assertTrue(rust.ask("hold", action="wait", seconds=3, **fields)["got"], kind + " signalled by Python reached Rust")
                rust.ask("hold", action="release", **fields)
        RECORD.append("held: a mutex, the stop, wake and demo events made by either implementation are met by the other, both ways")

    def test_the_home_lock_is_one_lock(self):
        home = self.scratch / "a codex home"
        home.mkdir()
        base = str(self.scratch / "lock files")
        fields = {"userprofile": self.userprofile(), "kind": "homelock", "name": "", "codex_home": str(home), "base": base}
        with ReferenceHolder(self.profile) as python, self.probe() as rust:
            taken = python.ask(kind="homelock", action="take", codex_home=str(home), base=base)
            self.assertEqual(taken["ok"], True)
            self.assertEqual(rust.ask("hold", action="take", **fields)["result"], {"error": "home_lock_busy"})
            python.ask(kind="homelock", action="release")
            mine = rust.ask("hold", action="take", **fields)
            self.assertEqual(mine["result"], {"ok": True})
            self.assertEqual(mine["identity"], taken["identity"], "the same folder identity")
            self.assertEqual(python.ask(kind="homelock", action="take", codex_home=str(home), base=base), {"error": "home_lock_busy"})
            # the same folder under another spelling is the same home: a junction to it, held by the other implementation
            link = self.scratch / "junction to the home"
            subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(home)], capture_output=True, creationflags=NO_WINDOW)
            if link.exists():
                self.assertEqual(python.ask(kind="homelock", action="take", codex_home=str(link), base=base), {"error": "home_lock_busy"})
            rust.ask("hold", action="release", **fields)
            self.assertEqual(python.ask(kind="homelock", action="take", codex_home=str(home), base=base)["ok"], True)
            # a home that is not there is locked by its path alone, and refused when its identity is required
            missing = dict(fields, codex_home=str(self.scratch / "no such home"))
            python.ask(kind="homelock", action="release")
            self.assertEqual(rust.ask("hold", action="take", require_identity=True, **missing)["result"], {"error": "home_unavailable"})
            self.assertEqual(rust.ask("hold", action="take", **missing)["result"], {"ok": True})
            if link.exists():
                os.rmdir(link)


if __name__ == "__main__":
    unittest.main(verbosity=2)
