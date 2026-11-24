"""S2.2, the settings file held to the tag: read, load, save and update, byte for byte, over the files earlier
versions wrote, the files the settings tests write, and generated ones - every encoding and BOM, no JSON, too large,
nested past the reader, a NaN, an int of 4,301 digits, half of a surrogate pair, a folder in its place, a file held
open with no sharing, a read-only one - and config.py's three settings functions (cut C2) on a home of their own.

Each case lays its file out in a scratch folder of its own, makes the call, and answers what the call answered (the
settings, or the exception with its sentence, reason and whether it is transient) and what was left behind: the
file's bytes and every other name in its folder, so a temporary file left over is a difference. Also here: the
status file's writer and remover, and `homes.problem`/`homes.strict` and the edition's look over a tree of
folders, junctions included, that the test makes once and hands both implementations.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from rustdiff import reference
from rustdiff.settingsdiff import Family

RECORD: list[str] = []
ROOT = Path(__file__).resolve().parents[2]

# Each tag writes its defaults, then takes the edits it knows one by one: what earlier versions left on disk.
OLD = r'''
import json, sys, tempfile
from pathlib import Path
from codex_auto_resume import settings
folder = Path(tempfile.mkdtemp())
path = folder / "settings.json"
written = []
try:
    settings.save(path, settings.defaults())
    written.append(path.read_bytes().hex())
    for name, value in [("max_recovery_attempts", 7), ("theme", "dark"), ("design", "still"), ("continuation_style", "careful"),
                        ("custom_message", "Keep going {reason}"), ("notifications", False), ("detection_lookback_hours", 12),
                        ("retry_timing", "aggressive"), ("quiet_hours_start", "22:00"), ("codex_exe", "C:\\Tools\\codex.exe"),
                        ("interface_language", "ko"), ("recover_timeout", False), ("panel_theme", "light"),
                        ("notify_stopped", False), ("memory_guard", "warn"), ("reduce_motion", True), ("observe_only", True),
                        ("retry_wait_2", "m45"), ("notices_stay", ["interruption"]), ("default_tier", "ask_first")]:
        try:
            settings.update(path, {name: value})
        except Exception:
            pass
    written.append(path.read_bytes().hex())
except Exception as error:
    written.append("failed: %s" % type(error).__name__)
print(json.dumps(written))
'''
TAGS = ("v0.5.0", "v0.5.7", "v0.6.0", "v0.6.5", "v0.6.9", "v0.6.10", "v0.6.11-beta", "v0.6.11", "v0.6.15", "v0.6.18",
        "v0.6.20", "v0.6.23", "v0.6.25", "v0.6.26-beta")

FILES = r'''
from codex_auto_resume import settings, config
cases = json.loads(sys.stdin.read())
def file_op(setup, op, argument):
    def call(target, folder):
        if op == "read": return settings.read(target)
        if op == "load": return settings.load(target)
        if op == "save": return settings.save(target, argument)
        if op == "update": return settings.update(target, argument)
    return in_scratch(("config", "settings.json"), setup, call)
def config_op(setup, op, argument):
    def call(target, folder):
        paths = config.Paths(folder / "home")
        if op == "load": return config.load_settings(paths)
        if op == "save": return config.save_settings(paths, argument)
        if op == "update": return config.update_settings(paths, argument)
    return in_scratch(("home", "config", "settings.json"), setup, call)
finish(cases, {"settings.file": file_op, "config.file": config_op})
'''


def text(body: str) -> dict:
    return {"kind": "bytes", "hex": body.encode("utf-8").hex()}


def raw(data: bytes, kind: str = "bytes") -> dict:
    return {"kind": kind, "hex": data.hex()}


class SettingsFileDiff(Family):
    def old_files(self) -> list:
        found = []
        for tag in TAGS:
            made = reference.run(OLD, profile=self.profile("old-%s" % tag), tag=tag)
            self.assertEqual(made.returncode, 0, made.stderr[-2000:].decode("utf-8", "replace"))
            for each in json.loads(made.stdout.decode("utf-8")):
                self.assertFalse(each.startswith("failed"), "%s: %s" % (tag, each))
                found.append(bytes.fromhex(each))
        return found

    def test_settings_files(self):
        old = self.old_files()
        flat = [{"max_recovery_attempts": 6, "poll_seconds": 30}, {"detection_lookback_hours": 2, "notifications": False},
                {"design": "still", "reduce_motion": False, "theme": "dark"}, {"config_version": 99, "max_no_progress": 5},
                {"config_version": 2, "theme": "neon", "max_no_progress": 5}, {"config_version": 2, "design": "neon"},
                {"continuation_style": "careful"}, {"config_version": 2, "custom_message": "\ud800"},
                {"config_version": 2, "custom_message_by_thread": {"0a1b2c3d-0001-7000-8000-000000000001": "a\udc00"}},
                {"config_version": 2, "codex_homes": [{"path": "C:\\a\ud800", "alias": "A"}, {"path": "C:\\b", "alias": "B"}]},
                {"config_version": 2, "home_suggestions_dismissed": ["C:\\a\ud800", "C:\\b"]}]
        bodies = [json.dumps(each) for each in flat] + [json.dumps(each, ensure_ascii=False) for each in flat[:7]]
        bodies += ["{ this is not json", "{not json", '{"observe_only": true,', "", "   ", "null", "[]", "5", '"x"',
                   "[" * 100 + "]" * 100, "[" * 10000 + "]" * 10000, '{"max_recovery_attempts": NaN}',
                   '{"detection_lookback_hours": Infinity, "config_version": 2}', '{"a": 1, "a": 2, "theme": "dark"}',
                   '{"max_recovery_attempts": ' + "7" * 4301 + "}", '{"max_recovery_attempts": ' + "7" * 4300 + "}",
                   '{"theme": "dark"} trailing', '{"theme": "dark"}\n', '{"theme": "da\\u0000rk"}', '{"x": "\x01"}',
                   '{"custom_message": "\\ud800 hi", "config_version": 2}', '{"theme": "dark", "config_version": true}']
        setups = [{"kind": "absent"}, {"kind": "dir"}] + [raw(data) for data in old] + [text(body) for body in bodies]
        golden = (ROOT / "tests" / "golden" / "defaults-v0.6.10.json").read_bytes()
        setups += [raw(golden), raw(b"\xef\xbb\xbf" + golden), raw(golden.decode("utf-8").encode("utf-16")),
                   raw(golden.decode("utf-8").encode("utf-16-le")), raw('{"theme": "dark", "x": "é"}'.encode("latin-1")),
                   raw(b"\xef\xbb\xbf{}"), raw(b"\xff\xfe{\x00}\x00"), raw(b'{"a": "\xed\xa0\x80"}'),
                   raw(b"{}" + b" " * (4 * 1024 * 1024 - 2)), raw(b"{}" + b" " * (4 * 1024 * 1024 - 1)),
                   raw(old[-1], "locked"), raw(old[-1], "readonly")]
        edits = [{"theme": "dark"}, {"max_recovery_attempts": 99}, {"no_such": 1}, {"design": "still"},
                 {"custom_message": "{prompt}"}, {"custom_message": "Go on {reason}"}, {"retry_wait_2": "m60"},
                 {"codex_homes": [{"path": "C:\\a", "alias": "A"}]}, {"notices_stay": ["power", "power"]}]
        cases = []
        for setup in setups:
            for op in ("read", "load"):
                cases.append(["settings.file", setup, op, None])
            cases.append(["settings.file", setup, "update", edits[len(cases) % len(edits)]])
            cases.append(["settings.file", setup, "save", {"theme": "light", "custom_message": "Hi \ud800"}])
        for values in [{}, {"max_recovery_attempts": 20, "detection_lookback_hours": 0.1, "custom_message": "x" * 2000},
                       {"codex_exe": "C:\\" + "é" * 100, "interface_language": "ja", "notices_stay": ["memory"]}, "x", None]:
            cases.append(["settings.file", {"kind": "absent"}, "save", values])
        for edit in edits:
            cases.append(["settings.file", {"kind": "absent"}, "update", edit])
        for setup in [{"kind": "absent"}, raw(old[-1]), text("{ bad"), text('{"theme": "dark"}'), {"kind": "dir"}]:
            for op, argument in [("load", None), ("save", {"theme": "dark"}), ("update", {"theme": "dark"}),
                                 ("update", {"theme": 5}), ("save", {})]:
                cases.append(["config.file", setup, op, argument])
        script = FILES
        done = self.family(script, label="files", expect=200, chunk=50, stdin=json.dumps(cases).encode("ascii"))
        refused = sum(1 for each in done["results"] if "error" in each.get("ok", {}).get("result", {}))
        RECORD.append("settings files: %d read/load/save/update and config cases equal, %d old files from %d tags; "
                      "%d answered by an exception, each with its class, sentence and reason"
                      % (len(done["cases"]), len(old), len(TAGS), refused))


STATUS = r'''
from codex_auto_resume import statusfile, homes
from codex_auto_resume.edition import name as edition_name, cached_copy
from pathlib import Path
cases = json.loads(sys.stdin.read())
WITH_MESSAGE.add("homes.strict")
def status_op(setup, op, argument):
    def call(target, folder):
        if op == "write": return statusfile.write(target, argument)
        if op == "remove": return statusfile.remove(target)
        if op == "ours": return statusfile._ours(target)
    return in_scratch(("status.json",), setup, call)
def identity(path):
    return homes.key(path) if Path(path).is_dir() else None
finish(cases, {"status.file": status_op, "homes.problem": homes.problem,
               "homes.strict": lambda value, default: homes.strict(value, default, identity),
               "edition.name": lambda src: edition_name(Path(src)), "edition.cached_copy": cached_copy})
'''


class StatusTreeDiff(Family):
    def tree(self) -> dict:
        import _winapi
        base = self.profile("tree")
        made = {}
        for name, files in [("good", ["state_5.sqlite"]), ("seven", ["state_1234567.sqlite"]), ("upper", ["STATE_5.sqlite"]),
                            ("empty", []), ("other", ["state_.sqlite", "state_5.sqlite-wal", "notes.txt"]),
                            ("six", ["state_123456.sqlite"])]:
            folder = base / name
            folder.mkdir()
            for each in files:
                (folder / each).write_bytes(b"")
            made[name] = str(folder)
        (base / "statedir" / "state_5.sqlite").mkdir(parents=True)
        made["statedir"] = str(base / "statedir")
        (base / "afile").write_bytes(b"x")
        made["afile"] = str(base / "afile")
        _winapi.CreateJunction(made["good"], str(base / "junction"))
        made["junction"] = str(base / "junction")
        made["missing"] = str(base / "missing")
        # The edition's look: src folders, each with or without the advanced package in one shape or another.
        layouts = {"advanced": ["__init__.py"], "standard": None, "pyc": ["__init__.pyc"], "pyd": ["__init__.pyd", "__init__.py"],
                   "pyw": ["__init__.pyw", "__init__.pyc"], "namespace": [], "upperinit": ["__INIT__.PY"]}
        for name, inits in layouts.items():
            src = base / ("src-" + name)
            (src / "codex_auto_resume").mkdir(parents=True)
            if inits is not None:
                package = src / "codex_auto_resume_advanced"
                package.mkdir()
                for each in inits:
                    (package / each).write_bytes(b"")
            made["src-" + name] = str(src)
        (base / "src-module").mkdir()
        (base / "src-module" / "codex_auto_resume_advanced.py").write_bytes(b"")
        made["src-module"] = str(base / "src-module")
        (base / "src-case" / "Codex_Auto_Resume_Advanced").mkdir(parents=True)
        (base / "src-case" / "Codex_Auto_Resume_Advanced" / "__init__.py").write_bytes(b"")
        made["src-case"] = str(base / "src-case")
        (base / "src-initdir" / "codex_auto_resume_advanced" / "__init__.py").mkdir(parents=True)
        made["src-initdir"] = str(base / "src-initdir")
        # Codex's copies of this plugin: the newest by its time decides.
        for home, copies in [("codex-a", [("0.6.25", False, 100), ("0.6.26", True, 200)]),
                             ("codex-b", [("0.6.25", True, 300), ("0.6.26", False, 200)]),
                             ("codex-c", [("x", False, 50)]), ("codex-d", [])]:
            root = base / home / "plugins" / "cache" / "codex-auto-resume-windows" / "codex-auto-resume"
            root.mkdir(parents=True)
            for version, advanced, when in copies:
                src = root / version / "src"
                (src / "codex_auto_resume").mkdir(parents=True)
                if advanced:
                    (src / "codex_auto_resume_advanced").mkdir()
                    (src / "codex_auto_resume_advanced" / "__init__.py").write_bytes(b"")
                os.utime(root / version, (1_700_000_000 + when, 1_700_000_000 + when))
            made[home] = str(base / home)
        (base / "codex-c" / "plugins" / "cache" / "codex-auto-resume-windows" / "codex-auto-resume" / "loose.txt").write_bytes(b"")
        made["codex-none"] = str(base / "codex-none")
        return made

    def test_status_homes_edition(self):
        tree = self.tree()
        content = {"format": "codex-auto-resume/status/1", "written_at": 1700000000.0, "version": "0.6.26",
                   "watcher": "running", "recovery": "on", "engine": "verified", "pending": 1,
                   "states": {"waiting_reset": 1}, "next_check_at": 1700000060.0, "usage": None}
        ours = json.dumps(content, indent=2).encode("ascii")
        cases = []
        for setup in [{"kind": "absent"}, raw(ours), raw(b'{"format": "something else"}'), raw(b"not json"),
                      {"kind": "dir"}, raw(b"[" * 9000 + b"]" * 9000), raw(b'{"format": "codex-auto-resume/status/1"}' + b" " * 17000),
                      raw(ours, "readonly"), raw(ours, "locked"), raw(b"[1, 2]"), raw("{\"format\": \"codex-auto-resume/status/1\", \"x\": \"\u00e9\"}".encode("latin-1"))]:
            cases += [["status.file", setup, "write", content], ["status.file", setup, "remove", None],
                      ["status.file", setup, "ours", None], ["status.file", setup, "write", dict(content, pending=2)],
                      ["status.file", setup, "write", dict(content, version="0.6.26\u00e9")]]
        for name in ["good", "seven", "upper", "empty", "other", "six", "statedir", "afile", "junction", "missing"]:
            cases.append(["homes.problem", tree[name]])
        cases += [["homes.problem", "\\\\server\\share"], ["homes.problem", "//server/share"]]
        home = lambda path, alias: {"path": path, "alias": alias}
        for value, default in [([home(tree["good"], "Good")], None), ([home(tree["good"], "Good")], tree["good"]),
                               ([home(tree["good"], "Good"), home(tree["seven"], "Seven")], tree["six"]),
                               ([home(tree["empty"], "Empty")], None), ([home(tree["missing"], "Gone")], None),
                               ([home(tree["junction"], "Link")], None), ([home(tree["good"], "A"), home(tree["good"].upper(), "B")], None),
                               ([home(tree["six"], "Six")], tree["missing"]), ([home(tree["good"], "\u00c4")], tree["good"]),
                               ("bad", None), ([home(tree["good"], "Good"), home(tree["good"] + "\\", "Again")], None)]:
            cases.append(["homes.strict", value, default])
        for name in tree:
            if name.startswith("src-"):
                cases.append(["edition.name", tree[name]])
        cases.append(["edition.name", tree["missing"]])
        for name in ["codex-a", "codex-b", "codex-c", "codex-d", "codex-none"]:
            cases.append(["edition.cached_copy", tree[name]])
        done = self.family(STATUS, label="tree", expect=50, chunk=50, stdin=json.dumps(cases).encode("ascii"))
        RECORD.append("status file, homes on disk, edition's look: %d cases equal (junction, 8 src layouts, 5 Codex homes)"
                      % len(done["cases"]))
