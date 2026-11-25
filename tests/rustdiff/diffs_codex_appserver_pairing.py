"""S3.3: car-codex's pairing and layout held to the reference (`codex/pairing.py`, `codex/layout.py`).

Every function the pairing has - the package paths, the engine and app rows, the mains, the walk through helpers,
the served engines, the other-session test, the database holders, the pairing itself with what it was told, the
inventory's three seconds, the signers' cache and our own servers - over the process layouts tests/test_codex_layouts.py
holds and over generated rows of every odd kind (no dict, no path, a path that is no text, missing and unreadable
creation times, reused and repeated pids, loops, case, forward slashes, `..`, another publisher, renamed mains,
the package's own programs), with stand-in holders, identities and signers. The layout: `snapshot` of each, and the
watcher's `Watch` over sequences of looks (a clock that moves, the app's version and the engine's file changing, the
"starting" count and its gaps, a look seen again, the kept file before and after this product's own update), its log
lines and the file it leaves. No process of this machine is read.
"""
from __future__ import annotations

import json
from pathlib import Path
import random

from rustdiff.appserverdiff import AppBase, op

RECORD: list[str] = []
NATIVE = r"C:\Program Files"
PUBLISHER = "2p2nqsd0c76g0"
FAMILY = "OpenAI.Codex_" + PUBLISHER
PROFILE = r"C:\Users\ExampleUser"
EXTENSION = PROFILE + r"\.vscode\extensions\openai.chatgpt-26.1.0-win32-x64\bin\windows-x86_64\codex.exe"
SHELL = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"


def folder(version, arch="x64", publisher=PUBLISHER):
    return NATIVE + r"\WindowsApps\OpenAI.Codex_%s_%s__%s" % (version, arch, publisher)


def app(version, arch="x64"):
    return folder(version, arch) + r"\app\ChatGPT.exe"


def p(pid, parent, path, created, family=None):
    return {"pid": pid, "parent": parent, "path": path, "created": created, "family": family}


def main(version, pid=10, created=100):
    return p(pid, 1, app(version), created, FAMILY)


# tests/test_codex_layouts.py's layouts: rows (engine keys "a", "b", "package", "daemon"), bin folders, the engine,
# the holders of the newest databases.
LAYOUTS = [
    ([main("26.915.1.0"), p(20, 10, "a", 200)], "a", (20,)),
    ([main("26.930.2377.0"), p(20, 10, "a", 200), p(21, 10, "a", 210)], "a", (20,)),
    ([main("26.930.7945.0"), p(20, 10, "b", 200)], "a", (20,)),
    ([main("26.1111.1.0"), p(20, 10, "package", 200)], "package", (20,)),
    ([main("26.1117.4957.0"), p(11, 10, app("26.1117.4957.0"), 110, FAMILY),
      p(12, 10, app("26.1117.4957.0"), 120, FAMILY), p(20, 11, "a", 200), p(21, 10, "a", 210)], "a", (20,)),
    ([main("26.1117.4957.0"), p(20, 5, "daemon", 200)], "a", (20,)),
    ([main("26.1117.4957.0"), p(11, 10, app("26.1117.4957.0"), 110, FAMILY), p(20, 11, "a", 200),
      p(30, 11, SHELL, 300, FAMILY), p(31, 30, "a", 310)], "a", (20, 31)),
    ([main("26.1117.4957.0"), p(20, 10, "a", 200), p(40, 6, EXTENSION, 400)], "a", (20, 40)),
    ([main("26.1117.4957.0"), p(999, 10, app("26.1117.4957.0"), 900, FAMILY), p(40, 999, "a", 400)], "a", (40,)),
    ([p(10, 1, folder("26.1200.1.0") + r"\OpenAI Codex.exe", 100, FAMILY), p(20, 10, "a", 200)], "a", (20,)),
    ([p(30, 5, "a", 300)], "a", (30,)),
    ([main("26.1300.1.0"), p(20, 10, "a", 200), p(21, 10, "a", 210), p(22, 10, "a", 220)], "a", (20, 21)),
    ([main("26.1300.1.0"), p(20, 10, "a", 200), p(21, 10, "b", 210)], "a", (21,)),
    ([main("26.1300.1.0"), p(20, 10, "a", 200)], "a", ()),
    ([main("26.1300.1.0"), main("26.1300.1.0", pid=11, created=110), p(20, 10, "a", 200)], "a", (20,)),
    ([main("26.1300.1.0"), p(20, 10, "a", 50)], "a", (20,)),
    ([main("26.1300.1.0"), p(20, 10, folder("26.1300.1.0") + r"\app\Codex.exe", 200, FAMILY)], "a", (20,)),
    ([p(10, 1, folder("26.1300.1.0") + r"\app\plugins\extension-host.exe", 100, FAMILY)], "a", ()),
    ([], "a", ()),
]


class World:
    """The paths a case's rows name, made under the scratch folder: LOCALAPPDATA's bin folders and a Codex home."""

    def __init__(self, root: Path):
        self.local = root / "local"
        self.home = root / "codex-home"
        self.home.mkdir(parents=True, exist_ok=True)
        for name in ("state_5.sqlite", "queue_1.sqlite"):
            (self.home / name).write_bytes(b"")
        self.engines = {"a": self.local / "OpenAI/Codex/bin/aaaa/codex.exe",
                        "b": self.local / "OpenAI/Codex/bin/bbbb/codex.exe",
                        "package": Path(folder("26.1111.1.0") + r"\app\resources\codex.exe"),
                        "daemon": self.home / "packages/app-server-daemon/releases/1.0/bin/codex.exe"}
        for key in ("a", "b"):
            self.engines[key].parent.mkdir(parents=True, exist_ok=True)
            self.engines[key].write_bytes(b"engine " + key.encode())
        self.env = {"ProgramW6432": NATIVE, "LOCALAPPDATA": str(self.local), "USERPROFILE": PROFILE}

    def path(self, key):
        return str(self.engines[key]) if key in self.engines else key

    def rows(self, rows):
        return [dict(row, path=self.path(row["path"])) if isinstance(row, dict) and isinstance(row.get("path"), str)
                else row for row in rows]


def identities(rows, drift=None):
    found = []
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("pid"), int) and isinstance(row.get("path"), str):
            created = row.get("created")
            if drift and row["pid"] in drift and isinstance(created, (int, type(None))):
                created = (created or 0) + drift[row["pid"]]
            found.append({"pid": row["pid"], "path": row["path"].lower(), "created": created})
    return found


def per_row_ops(rows, engine, home, holders_pids):
    ops = [op("app_mains", rows), op("server_engines", rows), op("engines_instead", rows, engine),
           op("app_running", rows), op("snapshot", rows, engine, None), op("database_holders", home),
           op("desktop_pair", rows, engine, home, False, True), op("desktop_pair", rows, engine, home, True, True),
           op("desktop_pair", rows, engine, None, False, True)]
    for index, row in enumerate(rows):
        ops += [op("engine_row", row), op("app_process", row), op("under_app", rows, index, 10),
                op("under_app", rows, index, None)]
        if isinstance(row, dict) and isinstance(row.get("path"), str):
            ops += [op(name, row["path"]) for name in ("package_app", "package_file", "main_slot", "main_place",
                                                       "extension_engine")]
    for pid in holders_pids:
        created = next((row.get("created") for row in rows if isinstance(row, dict) and row.get("pid") == pid), None)
        ops.append(op("session_kind", rows, {"pid": pid, "created": created}, engine))
    seen = {"server_holds": True}
    ops += [op("snapshot", rows, engine, seen), op("snapshot", rows, None, {}), op("snapshot", "rows", engine, None)]
    return ops


ODD_PATHS = [
    app("26.1300.1.0"), app("26.1300.1.0", "arm64"), app("26.1300.1.0", "x86"), app("26.1300"),
    app("1.2.3").upper(), app("1.2.3").replace("\\", "/"), folder("1.2.3") + r"\app\..\app\ChatGPT.exe",
    folder("1.2.3", publisher="otherpublish1") + r"\app\ChatGPT.exe", folder("1.2.3") + r"\app\Codex.exe",
    folder("1.2.3") + r"\app\CODEX.EXE", folder("1.2.3") + r"\app\resources\codex.exe",
    folder("1.2.3") + r"\app\plugins\extension-host.exe", folder("1.2.3") + r"\OpenAI Codex.exe",
    folder("1.2.3") + "\\", folder("1.2.3") + r"\\app\ChatGPT.exe", folder("1.2.3") + r"\app\cua_node\node.exe",
    NATIVE + r"\WindowsApps\OpenAI.Codex___" + PUBLISHER + r"\app\ChatGPT.exe",
    NATIVE + r"\WindowsApps\OpenAI.Codex_x__" + PUBLISHER.upper() + r"\app\ChatGPT.exe",
    NATIVE + r"\WindowsApps\openai.codex_1.0_x64__" + PUBLISHER + r"\APP\chatgpt.exe",
    NATIVE + r"\WindowsApps\OpenAI.Codex_1.0_X64__" + PUBLISHER + r"\app\ChatGPT.exe",
    NATIVE + "\\WindowsApps\\OpenAI.Codex_1.0_x64__2p2nq\u017fd0c76g0\\app\\ChatGPT.exe",
    NATIVE + r"\WindowsApps\OpenAI.Codex_1.0_x64__" + PUBLISHER, EXTENSION, EXTENSION.upper(),
    PROFILE + r"\.vscode\extensions\openai.chatgpt-\codex.exe", PROFILE + r"\.vscode\extensions\openai.chatgpt-1\codex.exe",
    PROFILE + r"\.vscode\extensions\openai.chatgpt-1\a\b\c\codex.exe", PROFILE + r"\.vscode\extensions\other\codex.exe",
    SHELL, "codex.exe", "", "C:\\", r"\\?\C:\x\codex.exe", "a", "b", "package", "daemon",
]


def random_rows(rng: random.Random):
    rows = []
    for _ in range(rng.randint(0, 9)):
        pick = rng.random()
        if pick < 0.04:
            rows.append(rng.choice([None, 5, "row", [1, 2]]))
            continue
        row = {"pid": rng.choice([10, 11, 12, 20, 21, 22, 30, 40, 999, rng.randint(1, 60)]),
               "parent": rng.choice([1, 5, 10, 11, 12, 20, 30, 999, None, rng.randint(1, 60)]),
               "path": rng.choice(ODD_PATHS),
               "created": rng.choice([100, 110, 200, 210, 300, 50, 0, -5, None, rng.randint(1, 500)]),
               "family": rng.choice([FAMILY, FAMILY.lower(), None, "Other_family", FAMILY.upper()])}
        if pick < 0.08:
            row.pop(rng.choice(["pid", "parent", "path", "created", "family"]))
        elif pick < 0.1:
            row["path"] = rng.choice([7, None, ["x"]])
        elif pick < 0.12:
            row["created"] = rng.choice(["100", 1.5, True])
        rows.append(row)
    return rows


class PairingDiff(AppBase):
    def world(self, name):
        return World(self.scratch / name)

    def test_known_layouts(self):
        made = self.world("layouts")
        cases = []
        for rows, engine, holders in LAYOUTS:
            rows = made.rows(rows)
            listed = [{"pid": row["pid"], "created": row["created"]} for row in rows if row["pid"] in holders]
            for variant in range(4):
                world = {"env": made.env, "processes": rows, "pid": 4242, "clock": 1000.0,
                         "holders": {"state_5.sqlite": listed, "queue_1.sqlite": listed[:1]} if variant != 1
                         else {"raise": "resource_inventory_failed"},
                         "identities": identities(rows, {20: 1} if variant == 2 else None)}
                if variant == 3:
                    world["env"] = dict(made.env, ProgramW6432="")
                    world["env"]["ProgramFiles"] = NATIVE
                cases.append({"world": world, "ops": per_row_ops(rows, made.path(engine), str(made.home), holders)})
        count, calls = self.script(cases, "known layouts")
        RECORD.append("pairing: %d known layouts x 4 worlds, %d calls equal" % (count // 4, calls))

    def test_generated_rows(self):
        made = self.world("generated")
        rng = random.Random(3303)
        cases = []
        for _ in range(900):
            rows = made.rows(random_rows(rng))
            pids = [row["pid"] for row in rows if isinstance(row, dict) and isinstance(row.get("pid"), int)]
            chosen = rng.sample(pids, min(len(pids), rng.randint(0, 3)))
            listed = [{"pid": pid, "created": rng.choice([100, 200, 210, 300, 400, None])} for pid in chosen]
            env = dict(made.env)
            if rng.random() < 0.1:
                env.pop(rng.choice(list(env)))
            world = {"env": env, "processes": rows, "pid": rng.choice([4242, 20, 30]), "clock": 1000.0,
                     "holders": {"state_5.sqlite": listed, "*": listed[:1]},
                     "identities": identities(rows, {pid: rng.choice([0, 1]) for pid in pids})}
            cases.append({"world": world, "ops": per_row_ops(rows, made.path(rng.choice(["a", "b", "package"])),
                                                             str(made.home), chosen)})
        count, calls = self.script(cases, "generated rows", chunk=150)
        RECORD.append("pairing: %d generated row lists, %d calls equal" % (count, calls))

    def test_engine_and_signers(self):
        made = self.world("signers")
        other = made.local / "elsewhere" / "codex.exe"
        other.parent.mkdir(parents=True)
        other.write_bytes(b"other engine")
        junk = made.local / "folder"
        junk.mkdir()
        paths = [made.path("a"), made.path("a").upper(), made.path("a").replace("\\", "/"), str(other),
                 str(made.local / "OpenAI/Codex/bin/AAAA/codex.exe"), str(made.local / "OpenAI/Codex/bin/xyz/codex.exe"),
                 str(made.local / "OpenAI/Codex/bin/codex.exe"), str(junk), str(made.local / "absent.exe"),
                 "", "codex.exe", "C:\\x\0y\\codex.exe", str(made.local / "OpenAI/Codex/bin/aaaa/../aaaa/codex.exe")]
        cases = []
        answers = ["OpenAI OpCo, LLC", "OpenAI, Inc.", {"raise": "signature_unreadable"},
                   {"raise": "signature_untrusted"}, {"raise": "unsigned"}, {"other": True}, None]
        for answer in answers:
            for env in (made.env, {}, {"LOCALAPPDATA": ""}, {"LOCALAPPDATA": str(made.local).upper()}):
                signers = {} if answer is None else {str(other).lower(): answer, str(junk).lower(): answer}
                ops = []
                for path in paths:
                    ops += [op("at_official_location", path), op("official_engine", path)]
                # the cache: the same answer again, a changed signer kept or asked again by the minute
                ops += [op("world", {"signers": {str(other).lower(): "OpenAI OpCo, LLC"}}),
                        op("official_engine", str(other)), op("advance", 30), op("official_engine", str(other)),
                        op("advance", 31), op("official_engine", str(other)), op("advance", -200),
                        op("official_engine", str(other))]
                cases.append({"world": {"env": env, "signers": signers, "clock": 1000.0}, "ops": ops})
        # more than 32 files: the cache is cleared whole
        many = []
        for index in range(40):
            each = made.local / "many" / ("%d.exe" % index)
            each.parent.mkdir(exist_ok=True)
            each.write_bytes(b"x" * index)
            many.append(str(each))
        cases.append({"world": {"env": made.env, "signers": {path.lower(): {"raise": "signature_untrusted"}
                                                              for path in many}},
                      "ops": [op("official_engine", path) for path in many + many]})
        count, calls = self.script(cases, "official engine")
        RECORD.append("pairing: official_engine and at_official_location over %d worlds, %d calls equal" % (count, calls))

    def test_inventory_and_own_servers(self):
        made = self.world("inventory")
        rows = made.rows(LAYOUTS[4][0])
        cases = []
        for raised in (None, "process_inventory_unavailable", "OSError", "ValueError", "TypeError"):
            processes = rows if raised is None else {"raise": raised}
            ops = [op("inventory"), op("world", {"processes": rows[:2]}), op("inventory"), op("advance", 2.9),
                   op("inventory"), op("advance", 0.2), op("inventory"), op("world", {"processes": rows}),
                   op("forget_inventory"), op("inventory"), op("advance", -1), op("inventory"), op("app_engines"),
                   op("app_running_now"), op("advance", 10), op("world", {"processes": processes}),
                   op("app_running_now"), op("app_engines")]
            ops += [op("own_server", pid) for pid in (20, 21, 0, -1, "20", True, 77)]
            ops += [op("own_holder", {"pid": 20, "created": 200}), op("own_holder", {"pid": 20, "created": 201}),
                    op("own_holder", {"pid": 21}), op("own_holder", [20]), op("own_holder", {"pid": [20], "created": 1}),
                    op("own_server_gone", [20, 200]), op("own_holder", {"pid": 20, "created": 200}),
                    op("inventory")]
            identities_list = identities(rows) + [{"pid": 77, "raise": "process_exited"}]
            cases.append({"world": {"env": made.env, "processes": processes, "identities": identities_list,
                                    "clock": 500.0}, "ops": ops})
        count, calls = self.script(cases, "inventory and our servers")
        RECORD.append("pairing: the inventory's 3 s and our own servers, %d worlds, %d calls equal" % (count, calls))


def snapshot_of(rows, engine, seen=None):
    """A layout op whose answer the next look uses: the reference's snapshot, made by each side."""
    return op("snapshot", rows, engine, seen)


class WatchDiff(AppBase):
    def test_watch_sequences(self):
        made = World(self.scratch / "watch")
        rng = random.Random(1117)
        cases, files = [], []
        shapes = []
        for rows, engine, _ in LAYOUTS:
            rows = made.rows(rows)
            shapes.append({"rows": rows, "engine": made.path(engine)})
        kept_variants = [None, b"", b"{", b"[]", json.dumps({"format": 1}).encode(),
                         json.dumps({"format": True}).encode(), json.dumps({"format": 1.0}).encode(),
                         json.dumps({"format": 1, "code_version": "0.6.25", "last_good": {
                             "code_version": "0.6.25", "engine_version": "codex-cli 0.171.0", "app_version": "26.1117",
                             "layout": {"mains": 1, "shape": "single_child", "paired": True, "helpers": 10 ** 7}},
                             "updated_from": None}).encode(),
                         json.dumps({"format": 1, "code_version": "0.6.26", "updated_from": "0.6.24",
                                     "unpaired_after_update": True, "catalogued": "yes",
                                     "layout": {"mains": -1, "engines_elsewhere": 2.0, "renamed_main": 1,
                                                "app_version": "x" * 65, "shape": "closed"}}).encode(),
                         b"\xef\xbb\xbf{\"format\": 1}", ("[" * 3000).encode(), b"{\"format\": 1, " + b" " * 17000 + b"}"]
        for number in range(120):
            path = made.home.parent / ("layout-%d.json" % number)
            files.append(str(path))
            variant = kept_variants[number % len(kept_variants)]
            if variant is not None:
                path.write_bytes(variant)
            code_version = rng.choice(["0.6.26", "0.6.25", "", None, "ü", "0.6.26-beta.2"])
            ops = [op("layout.read", str(path)), op("watch.new", str(path), code_version)]
            found = None
            for _ in range(rng.randint(3, 25)):
                pick = rng.random()
                if pick < 0.15 and found is not None:
                    ops.append(op("watch.look", "again", rng.choice([None, [1, 2], [1, 3]]),
                                  rng.choice([None, "codex-cli 0.171.0"])))
                elif pick < 0.25:
                    ops.append(op("advance", rng.choice([5, 60, 300, 599, 601, 1200, 3600, 0.5])))
                else:
                    shape = rng.choice(shapes)
                    seen = rng.choice([None, {}, {"server_holds": True}, {"server_holds": False}])
                    found = {"mains": 0}
                    # the look's snapshot is made the reference's way, then handed to the watch as each side made it
                    ops.append(op("snapshot", shape["rows"], shape["engine"], seen))
                    ops.append(op("watch.look", {"__snapshot__": len(ops) - 1}, rng.choice([None, [1, 2], [1, 3]]),
                                  rng.choice([None, "codex-cli 0.171.0", "x" * 70])))
            ops += [op("file", str(path)), op("layout.read", str(path))]
            cases.append({"world": {"env": made.env, "clock": 5000.0}, "ops": resolve_snapshots(ops)})
        count, calls = self.script(cases, "layout watch", chunk=60, files=files)
        RECORD.append("layout: %d watch sequences (looks, gaps, again, kept files in 12 forms), %d calls equal"
                      % (count, calls))


def resolve_snapshots(ops):
    """A look whose snapshot is the op before it gets that snapshot's own arguments' result: the found dict is given
    literally (both sides already agree on `snapshot`, held by the pairing diff), so the watch is fed the same."""
    import copy
    out = []
    for each in ops:
        if each["op"] == "watch.look" and isinstance(each["args"][0], dict) and "__snapshot__" in each["args"][0]:
            source = ops[each["args"][0]["__snapshot__"]]
            rows, engine, seen = source["args"]
            each = dict(each, args=[expected_snapshot(rows, engine, seen)] + each["args"][1:])
        out.append(copy.deepcopy(each))
    return out


def expected_snapshot(rows, engine, seen):
    """A plausible snapshot as the watcher hands one over: the counts of a layout, with its seen pairing. Built here
    (not by either implementation) so the watch's input is the same for both."""
    mains = sum(1 for row in rows if isinstance(row, dict) and str(row.get("path", "")).endswith("ChatGPT.exe")
                and row.get("parent") == 1)
    engines = sum(1 for row in rows if isinstance(row, dict) and str(row.get("path", "")).lower().endswith("codex.exe"))
    shape = {(1, 1): "single_child", (1, 2): "two_children", (1, 0): "starting", (0, 0): "closed"}.get(
        (min(mains, 2), min(engines, 2)))
    version = None
    for row in rows:
        if isinstance(row, dict) and "OpenAI.Codex_" in str(row.get("path")):
            version = str(row["path"]).split("OpenAI.Codex_")[1].split("_")[0]
            break
    return {"mains": mains, "helpers": 0, "renamed_main": False, "app_version": version, "engines_under_main": engines,
            "engines_under_helper": 0, "engines_elsewhere": 0, "engine_in_package": False,
            "paired": isinstance(seen, dict) and "server_holds" in seen,
            "server_holds": seen.get("server_holds") if isinstance(seen, dict) else None, "shape": shape}
