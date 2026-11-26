"""The platform seat's diffs (S3.1, PLAN 5.3): car-platform, the Windows layer, against the reference tag.

Every comparison runs one input through the reference (the tag's own Python, `reference.py`) and through
car-platform's probe (`rust/crates/car-platform/examples/probe.rs`, a dev-only example that is never shipped), and holds
the answers equal:

* ObjectNames   - the mutex, stop, wake and demo names, the install lock, the home lock's files, for 50 homes (Unicode,
                  case, 8.3 short names, a junction, forward slashes, `..`, homes that do not exist), and the objects
                  themselves held across the two implementations (a Python holder and a Rust taker, and back).
* CommandLines  - `subprocess.list2cmdline`, `startup.quote_argument` and `startup.parse_command` for a generated corpus
                  of argument lists; the child sees the arguments it was given.
* Registry      - every registry writer and reader (Run value, AUMID, URL protocol, the Uninstall entry, policy keys,
                  CODEX_HOME, text size) behind a stand-in in BOTH implementations: the calls recorded, in order, and the
                  store they leave are equal. Never HKCU: the reference runs with its `winreg` replaced by a recorder,
                  the probe on `FakeRegistry`.
* NoWindow      - every process the Rust core starts has CREATE_NO_WINDOW: the flags the starter applied are read, and no
                  `Command::new` exists outside `spawn.rs`.
* Shortcuts     - the shortcut writers (the scripts, the values handed to them, the refusals) behind a recording starter.
* Pure rules, live questions - kernel, acl, authenticode, typeface, network, power and the rest, read only.

Run by `run.py` (it loads every `*_diffs` module), or alone: `python -X utf8 tests/rustdiff/platform_diffs.py`. The probe
is built on demand (`cargo build -p car-platform --example probe`, two jobs).
"""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for entry in (ROOT / "src", ROOT / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from rustdiff import core, reference  # noqa: E402

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
RECORD: list[str] = []


# ------------------------------------------------------------------------------------------------ the probe

def probe_path() -> Path:
    named = os.environ.get("CODEX_AR_PLATFORM_PROBE")
    return Path(named) if named else core.target_dir() / "debug" / "examples" / "probe.exe"


def build_probe() -> None:
    environment = dict(os.environ)
    environment.setdefault("CARGO_BUILD_JOBS", "2")
    subprocess.run(["cargo", "build", "--locked", "-p", "car-platform", "--example", "probe", "--manifest-path",
                    str(ROOT / "rust" / "Cargo.toml")], env=environment, check=True, creationflags=NO_WINDOW,
                   timeout=1800)


class Probe:
    """One probe process for the length of a `with`: `ask(op, **fields)` answers the reply's value."""

    def __init__(self, profile: Path, env: dict | None = None):
        self.profile = profile
        self.env = env or {}
        self.process = None

    def __enter__(self):
        if not probe_path().is_file():
            build_probe()
        environment = reference.scratch_environment(self.profile, **self.env)
        environment.pop("CODEX_AR_PLATFORM_PROBE", None)
        self.process = subprocess.Popen([str(probe_path())], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, env=environment, cwd=str(self.profile),
                                        creationflags=NO_WINDOW)
        return self

    def ask(self, op: str, **fields):
        line = json.dumps(dict(fields, op=op), ensure_ascii=False) + "\n"
        self.process.stdin.write(line.encode("utf-8"))
        self.process.stdin.flush()
        reply = json.loads(self.process.stdout.readline().decode("utf-8"))
        if "error" in reply:
            raise AssertionError("probe %s: %s" % (op, reply["error"]))
        return reply["ok"]

    def __exit__(self, *_exc):
        try:
            self.process.stdin.close()
            self.process.wait(timeout=30)
        finally:
            if self.process.poll() is None:
                self.process.kill()
            self.process.stdout.close()
            self.process.stderr.close()


def ref(script: str, payload, profile: Path, env: dict | None = None):
    """The reference tag's answer: `script` reads one JSON document on stdin and prints one. `env` adds variables to
    the scratch environment the reference runs in (`reference.run` offers no hook, so its builder is wrapped)."""
    original = reference.scratch_environment
    if env:
        reference.scratch_environment = lambda home, **more: original(home, **env, **more)
    try:
        done = reference.run(script, profile=profile, stdin=json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    finally:
        reference.scratch_environment = original
    if done.returncode != 0:
        raise AssertionError("the reference failed: %s" % done.stderr.decode("utf-8", "replace")[-1500:])
    return json.loads(done.stdout.decode("utf-8"))


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="platform-diff-")
        cls.scratch = Path(cls._tmp.name).resolve()
        cls.profile = cls.scratch / "profile"
        cls.profile.mkdir()

    @classmethod
    def tearDownClass(cls):
        for entry in cls.scratch.rglob("*"):
            try:
                if entry.is_junction():
                    os.rmdir(entry)
            except OSError:
                pass
        cls._tmp.cleanup()

    def probe(self, env: dict | None = None):
        return Probe(self.profile, env)


# ----------------------------------------------------------------------------------- 1. the names of 50 homes

NAMES_SCRIPT = r'''
import json, os, sys
from pathlib import Path
from codex_auto_resume.win import folderid, homelock, sync
request = json.load(sys.stdin)
out = []
for case in request["cases"]:
    os.environ["USERPROFILE"] = case["userprofile"]
    if case.get("localappdata"):
        os.environ["LOCALAPPDATA"] = case["localappdata"]
    state = case["state"]
    lock = homelock.HomeLock(case["codex_home"], case.get("base"))
    out.append({"identity": os.path.normcase(str(Path.home().resolve())),
                "mutex": sync.Mutex(state).name, "stop": sync.StopEvent(state).name,
                "wake": sync.WakeEvent(state).name, "demo": sync.DemoEvent(state).name,
                "install_lock": homelock.INSTALL_LOCK, "home_lock": str(lock.path), "lock_root": str(lock.root),
                "folder_identity": folderid.identity(Path(case["codex_home"]))})
json.dump(out, sys.stdout, ensure_ascii=False)
'''


def short_path(path: Path) -> str:
    buffer = ctypes.create_unicode_buffer(1024)
    if ctypes.windll.kernel32.GetShortPathNameW(str(path), buffer, 1024):
        return buffer.value
    return str(path)


def make_homes(scratch: Path) -> list[str]:
    """Fifty spellings of homes: made folders in odd spellings, and folders that are not there."""
    made = scratch / "homes"
    made.mkdir()
    homes: list[str] = []
    for name in ("plain", "with space", "한국어 홈", "Éléonore", "Ωmega", "кириллица", "日本語", "emoji-😀-home",
                 "MiXeD CaSe", "dots.in.name", "trailing space dir", "ünï cödé", "ǅ lowercase", "ßtraße", "İstanbul",
                 "Mixed-ΣΑΣ", "a'postrophe", "amp&ersand", "paren(s)", "hash#tag", "LongFolderNameForShortNaming",
                 "AnotherQuiteLongFolderName2"):
        folder = made / name
        folder.mkdir(exist_ok=True)
        homes.append(str(folder))
    first = made / "MiXeD CaSe"
    homes += [str(first).upper(), str(first).lower(), str(first).replace("\\", "/"), str(first) + "\\",
              str(first) + "\\.", str(made / "plain" / ".." / "MiXeD CaSe"), str(made).replace("homes", "HOMES") + "\\plain",
              str(first)[0].lower() + str(first)[1:]]
    long_one = made / "LongFolderNameForShortNaming"
    homes += [short_path(long_one), short_path(long_one).lower(), short_path(made / "AnotherQuiteLongFolderName2")]
    target = made / "plain"
    junction = made / "junction-to-plain"
    subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(target)], capture_output=True, creationflags=NO_WINDOW)
    if junction.exists():
        homes += [str(junction), str(junction).upper()]
    homes += [str(made / "not there"), str(made / "not there" / "deeper" / "still"), str(made / "ünï nöt thêre"),
              str(made / "plain" / "not-there-below"), str(made / "NOT THERE" / ".." / "x"),
              str(scratch / "missing-parent" / "한국어"), str(scratch).replace("\\", "/") + "/missing//double//slash",
              str(made / "plain" / "." / "dot")]
    while len(homes) < 50:
        homes.append(str(made / ("extra-%d" % len(homes))))
    return homes[:50]


class ObjectNames(Base):
    def test_names_equal_for_50_homes(self):
        homes = make_homes(self.scratch)
        self.assertEqual(len(homes), 50)
        states = [r"C:\Users\ExampleUser\.codex-auto-resume\state", "relative state", "한국어 상태 폴더 😀"]
        cases = []
        for index, home in enumerate(homes):
            other = homes[(index * 7 + 3) % len(homes)]
            for state in states:
                cases.append({"userprofile": home, "state": state, "codex_home": other,
                              "base": str(self.scratch / ("locks-%d" % (index % 3))) if index % 2 else None,
                              "localappdata": str(self.scratch / "local")})
        expected = ref(NAMES_SCRIPT, {"cases": cases}, self.profile)
        keys = ("identity", "mutex", "stop", "wake", "demo", "install_lock", "home_lock", "lock_root", "folder_identity")
        differing = []
        with self.probe() as probe:
            for case, want in zip(cases, expected):
                got = probe.ask("names", **{k: v for k, v in case.items() if v is not None})
                for key in keys:
                    if got.get(key) != want[key]:
                        differing.append((case["userprofile"], key, got.get(key), want[key]))
        self.assertEqual(differing[:5], [], "names differ for %d of %d" % (len(differing), len(cases) * len(keys)))
        RECORD.append("names: %d homes x %d state names, %d values each, all equal to %s (%d distinct mutex names)"
                      % (len(homes), len(states), len(keys), reference.TAG, len({row["mutex"] for row in expected})))

    def test_text_rules_equal(self):
        """normcase, realpath and the hash, on texts Python spells in more than one way."""
        texts = ["C:/Users/ExampleUser/b", "c:\\users\\ExampleUser\\ÄÖÜ\\straße", "\\\\Server\\Share\\Dir\\..\\X", "İ\\ǅ\\Σ", "C:\\a\\.\\b\\..\\c", "",
                 "relative\\path", "C:\\", "ΑΣ", "Ǆ", "ẞ", "K\u212a", "C:\\한국어\\😀"]
        script = ("import json,sys,os,hashlib\nfrom pathlib import Path\nt=json.load(sys.stdin)\n"
                  "json.dump([{'n':os.path.normcase(x),'h':hashlib.sha256(x.encode('utf-8')).hexdigest()} for x in t],"
                  "sys.stdout,ensure_ascii=False)")
        expected = ref(script, texts, self.profile)
        with self.probe() as probe:
            for text, want in zip(texts, expected):
                self.assertEqual(probe.ask("normcase", text=text), want["n"], text)
                self.assertEqual(probe.ask("sha256", text=text), want["h"], text)


# --------------------------------------------------------------------------------------- 2. command lines

ALPHABET = ["a", "b", "Z", "0", " ", "  ", "\t", '"', '""', "\\", "\\\\", "\\\\\\", "é", "한", "😀", "\u00a0", "'", "&", "%",
            "^", "|", "*", "?", "=", ";", "/", ":", "-", "--home", "C:\\Program Files\\x", "\\\\server\\share", "\u2018", "\u2019"]


def corpus(count: int, seed: int = 20260625) -> list[list[str]]:
    """Argument lists: the awkward ones by hand, then generated."""
    rng = random.Random(seed)
    lists = [[], [""], ["", ""], ["a b"], ['a"b'], ["a\\"], ["a\\\\"], ["a b\\"], ["a b\\\\"], ['"'], ['\\"'], ['\\\\"'],
             ['a\\"b c'], ["C:\\Program Files\\App\\app.exe", "--home", "D:\\"], ["x\ty"], ["\t"], [" "], ["한 국"],
             ["a", "", "b"], ['"quoted"'], ["tail\\\\\\"], ["\\\\server\\share\\dir with space\\"]]
    while len(lists) < count:
        lists.append(["".join(rng.choice(ALPHABET) for _ in range(rng.randint(0, 6))) for _ in range(rng.randint(0, 5))])
    return lists


class CommandLines(Base):
    def test_list2cmdline_equal_on_the_corpus(self):
        lists = corpus(4000)
        want = [subprocess.list2cmdline(arguments) for arguments in lists]
        with self.probe() as probe:
            got = [probe.ask("list2cmdline", args=arguments) for arguments in lists]
            self.assertEqual([(a, g, w) for a, g, w in zip(lists, got, want) if g != w][:5], [])
            started = [probe.ask("spawn_flags", argv=arguments)["command_line"] for arguments in lists[:300]]
        self.assertEqual(started, want[:300], "Spawn.command_line is list2cmdline")
        RECORD.append("command lines: %d argument lists, Rust list2cmdline equal to subprocess.list2cmdline" % len(lists))

    def test_quote_and_parse_equal_to_the_reference(self):
        values = [value for arguments in corpus(800) for value in arguments][:1500]
        script = ("import json,sys\nfrom codex_auto_resume import startup\nv=json.load(sys.stdin)\n"
                  "q=[startup.quote_argument(x) for x in v]\n"
                  "json.dump({'q':q,'p':[startup.parse_command(x) for x in q],'c':[startup.parse_command(x) for x in v],"
                  "'i':[startup.script_index(['p.exe']+x.split()) for x in v]},sys.stdout,ensure_ascii=False)")
        want = ref(script, values, self.profile)
        with self.probe() as probe:
            for index, value in enumerate(values):
                quoted = probe.ask("quote_argument", value=value)
                self.assertEqual(quoted, want["q"][index], repr(value))
                self.assertEqual(probe.ask("parse_command", command=quoted), want["p"][index], repr(value))
                if value:  # an empty line makes CommandLineToArgvW answer the program's own path, which differs by process
                    self.assertEqual(probe.ask("parse_command", command=value), want["c"][index], repr(value))
                self.assertEqual(probe.ask("script_index", args=["p.exe"] + value.split()), want["i"][index])

    def test_the_value_the_run_key_holds_equals_the_reference(self):
        """startup.command_line / protocol_command_line / the uninstall strings for paths with spaces, quotes and a
        trailing backslash."""
        home = self.scratch / "run value home"
        (home / "uninstall").mkdir(parents=True)
        (home / "uninstall" / "install.ps1").write_text("x", encoding="utf-8")
        entry = home / "app" / "auto_resume.py"
        entry.parent.mkdir()
        entry.write_text("x", encoding="utf-8")
        launcher = r"C:\Program Files\Codex Auto Resume\runtime\pythonw.exe"
        script = r'''
import json, sys
from pathlib import Path
from codex_auto_resume import addremove, startup
r = json.load(sys.stdin)
out = {"c1": startup.command_line(Path(r["entry"]), Path(r["home"]), Path(r["launcher"])),
       "c2": startup.command_line(Path(r["entry"]), None, Path(r["launcher"]), startup.NO_REMOTE_DEBUG),
       "p1": startup.protocol_command_line(Path(r["entry"]), Path(r["home"]), Path(r["launcher"])),
       "u1": addremove.uninstall_command(Path(r["home"])), "u2": addremove.uninstall_command(Path(r["home"]), True),
       "b": [startup.belongs_to(c, Path(r["home"])) for c in r["commands"]]}
json.dump(out, sys.stdout, ensure_ascii=False)
'''
        commands = []
        with self.probe() as probe:
            mine = {"c1": probe.ask("command_line", entry=str(entry), home=str(home), launcher=launcher),
                    "c2": probe.ask("command_line", entry=str(entry), launcher=launcher, options=["-X", "disable-remote-debug"]),
                    "p1": probe.ask("protocol_command_line", entry=str(entry), home=str(home), launcher=launcher,
                                    options=["-X", "disable-remote-debug"]),
                    "u1": probe.ask("uninstall_command", home=str(home)),
                    "u2": probe.ask("uninstall_command", home=str(home), silent=True)}
            commands = [mine["c1"], mine["p1"], mine["u1"], '"x.exe" --home "%s"' % home, '"x.exe" --home "%s"' % (home / "other"),
                        '"%s" "%s" run' % (launcher, entry), "", "garbage"]
            beliefs = [probe.ask("belongs_to", command=command, home=str(home)) for command in commands]
        want = ref(script, {"entry": str(entry), "home": str(home), "launcher": launcher, "commands": commands}, self.profile)
        # The reference's protocol line carries -X disable-remote-debug always; the probe was given the same options.
        self.assertEqual(mine, {key: want[key] for key in mine})
        self.assertEqual(beliefs, want["b"])
        RECORD.append("run value: command_line, protocol line, both uninstall strings and belongs_to equal")

    def test_child_sees_the_arguments_it_was_given(self):
        """The tail Rust hands CreateProcess is list2cmdline's: Python, started with the same list, reads the same argv."""
        lists = [arguments for arguments in corpus(120, seed=7) if arguments and all("\0" not in a for a in arguments)]
        code = "import json,sys;print(json.dumps(sys.argv[1:],ensure_ascii=True))"
        with self.probe() as probe:
            for arguments in lists:
                seen = probe.ask("echo", argv=[sys.executable, "-X", "utf8", "-c", code, *arguments])
                own = subprocess.run([sys.executable, "-X", "utf8", "-c", code, *arguments], capture_output=True,
                                     encoding="utf-8", errors="replace", creationflags=NO_WINDOW).stdout
                self.assertEqual(json.loads(seen["stdout"]), json.loads(own), arguments)
                self.assertEqual(seen["flags"] & 0x08000000, 0x08000000)
