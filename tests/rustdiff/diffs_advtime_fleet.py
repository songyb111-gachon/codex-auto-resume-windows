"""S7.2e2: `engine/fleet.py` (fleet_view, P8) as the v0.6.26 final has it, held equal to car-adv's `engine::fleet`.

The pure parts over generated values: `alias_valid` (letters of every script, digits, reserved device names, spaces at
the ends), `clean` and `document` over the closed shape and its mutants, `shown` over every age, `_within`, the waiting
words. The files on a scratch shared folder: `write` (a new file, its own, another PC's under the same name, a newer one,
a link, a missing folder; the bytes it leaves), `read_peers` (valid peers, its own alias skipped in any case, damaged,
too large, NaN, a folder named like a file, more than MOST), `remove_old_name`, `write_seen`/`read_seen` and
`folder_problem` (inside the home, a junction, a file, a device path, characters no folder has). Then the capability:
a walk over the real state's wordings and stamps with a scripted status, spawn (the pass run at once or held), worker
and clock (a pass held past BOUND is given up LATE). Compared: every answer, call, row, and file left.

Alone: `cd tests && PYTHONPATH="../src;." python -X utf8 -m unittest rustdiff.diffs_advtime_fleet`.
"""
from __future__ import annotations

import json
import os
import random
import subprocess
import unittest

from rustdiff import advtime

CAPABILITY = "fleet_view"
NOW = advtime.NOW
FORMAT = "codex-auto-resume/fleet/1"
ALIASES = ["PC-1", "pc-1", "PC 2", " PC", "PC ", "", "a" * 32, "a" * 33, "CON", "con", "COM1", "LPT9", "COM0", "Büro",
           "東京", "٣", "Ⅻ", "PC_1", "PC.1", "a\u0903", "x\u00b2", "\u2167", None, 5]


def status(rng: random.Random) -> dict:
    found = {"format": "codex-auto-resume/status/1", "written_at": "now", "version": rng.choice(["0.6.27", "0.6.27-alpha"]),
             "watcher": "running", "recovery": rng.choice(["on", "paused", "observe_only"]),
             "engine": rng.choice(["verified", "unknown", "incompatible"]), "pending": 0, "states": {},
             "next_check_at": rng.choice([None, NOW + 600, NOW + 10 ** 12]), "usage": None}
    if rng.random() < 0.3:
        found["states"] = {"waiting_reset": 2}
        found["pending"] = 2
    if rng.random() < 0.05:
        found["watcher"] = "bad"
    return found


def peer(alias: str, rng: random.Random, written=None) -> dict:
    return {"format": FORMAT, "alias": alias, "edition": "advanced",
            "written_at": written if written is not None else NOW - rng.choice([10, 1000, 10 ** 6]),
            "version": "0.6.26", "watcher": rng.choice(["running", "stopped"]), "recovery": "on", "engine": "verified",
            "pending": 0, "states": {}, "next_check_at": None, "usage": None}


def peer_files(rng: random.Random, own="PC-1") -> dict:
    files = {}
    for index in range(rng.randint(0, 5)):
        alias = "Peer-%d" % index
        pick = rng.random()
        if pick < 0.6:
            body = json.dumps(peer(alias, rng), indent=2)
        elif pick < 0.7:
            body = json.dumps(peer("Other", rng))
        elif pick < 0.8:
            body = json.dumps(peer(alias, rng)).replace('"pending": 0', '"pending": NaN')
        elif pick < 0.9:
            body = "{broken"
        else:
            body = json.dumps(peer(alias, rng)) + " " * 20000
        files["shared/%s.json" % rng.choice([alias, alias.upper()])] = body
    if rng.random() < 0.3:
        files["shared/%s.JSON" % own.lower()] = json.dumps(peer(own, rng))
    if rng.random() < 0.2:
        files["shared/note.txt"] = "x"
    if rng.random() < 0.1:
        files["shared/dir.json"] = {"dir": True}
    return files


class FleetPureDiff(unittest.TestCase):
    def test_pure(self):
        rng = random.Random(7262)
        cases = []

        def add(name, *arguments, files=None):
            cases.append({"op": "fl.pure", "name": name, "arguments": list(arguments), "files": files or {},
                          "dump": False, "left": [name_ for name_ in (files or {})] + ["shared/PC-1.json"]})
        for alias in ALIASES:
            add("alias_valid", alias)
        base = dict(peer("PC-1", rng), written_at=NOW)
        for _ in range(4):
            for key in list(base):
                for value in (None, True, 1, 1.5, "x", NOW, 10 ** 400 if False else 10 ** 20, [], {}):
                    changed = dict(base)
                    changed[key] = value
                    add("clean", changed, rng.choice([None, "pc-1", "PC-2"]))
                cut = dict(base)
                del cut[key]
                add("clean", cut, None)
        add("clean", dict(base, extra=1), None)
        for alias in ALIASES:
            add("document", status(rng) | {"written_at": NOW}, alias)
        add("document", {"format": "x"}, "PC-1")
        for age in (-700, -600, 0, 899, 900, 901, 7 * 86400, 7 * 86400 + 1):
            for due in (None, NOW + 10, NOW - 10, NOW + 8 * 86400 + 1):
                add("shown", dict(base, written_at=NOW - age, next_check_at=due), NOW)
        for stamp in (0, 1, 7, 8, True, None, "1"):
            add("waiting_word", stamp)
        for path, root in (("C:\\a\\b", "C:\\a"), ("c:\\A\\b", "C:\\a"), ("C:\\ab", "C:\\a"), ("D:\\a", "C:\\a"),
                           ("C:\\a", "C:\\a"), ("\\\\s\\h\\x", "\\\\s\\h"), ("C:\\", "C:\\"), ("C:\\a\\.\\b", "C:\\a")):
            add("within", path, root)
        own = json.dumps(peer("PC-1", rng, written=NOW - 50), indent=2)
        newer = json.dumps(peer("PC-1", rng, written=NOW + 5000), indent=2)
        value = dict(peer("PC-1", rng), written_at=NOW)
        for files, before in (({}, None), ({"shared/PC-1.json": own}, None), ({"shared/PC-1.json": own}, int(NOW)),
                              ({"shared/PC-1.json": newer}, int(NOW)), ({"shared/PC-1.json": "{}"}, None),
                              ({"shared/PC-1.json": {"dir": True}}, None), ({"shared/PC-1.json": own}, 0)):
            add("write", "{home}\\shared", "PC-1", value, before, files={"shared": {"dir": True}, **files})
        add("write", "{home}\\missing", "PC-1", value, None)
        add("write", "{home}\\shared", "PC-1", dict(value, pending=-1), None, files={"shared": {"dir": True}})
        for _ in range(60):
            files = {"shared": {"dir": True}, **peer_files(rng)}
            add("read_peers", "{home}\\shared", rng.choice(["PC-1", "pc-1", None]), files=files)
        add("read_peers", "{home}\\missing", "PC-1")
        add("remove_old_name", "{home}\\shared", "PC-1", files={"shared/PC-1.json": own})
        add("remove_old_name", "{home}\\shared", "PC-1", files={"shared/PC-1.json": newer.replace("PC-1", "PC-2")})
        for kept in ([], [peer("A", rng)], [peer("A", rng), dict(peer("B", rng), pending=-1)]):
            add("seen", NOW, kept, 1, 2)
        add("read_seen", files={"config/advanced/fleet-seen.json": json.dumps({"format": "x"})})
        add("read_seen", files={"config/advanced/fleet-seen.json": json.dumps(
            {"read_at": NOW, "format": "codex-auto-resume/fleet-seen/1", "ignored": 0, "held": 0, "peers": []})})
        for folder in ("{home}\\shared", "{home}", "{home}\\config", "{home}\\missing", "{home}\\file", "relative",
                       "C:", "\\\\?\\C:\\x", "\\\\.\\pipe\\x", "{home}\\sh<ared", "", None, "C:\\" + "a" * 260,
                       "//server/share/x", "\\\\server\\share"):
            add("folder_problem", folder, files={"shared": {"dir": True}, "file": "x"})
        advtime.Scene(self, "fleet pure").run(cases)

    def test_junction(self):
        """A junction for the folder is LINK, and a peer file that is a link is ignored (made with mklink /J: no
        privilege needed)."""
        rng = random.Random(7263)
        cases = [{"op": "fl.pure", "name": "folder_problem", "arguments": ["{home}\\joined"], "dump": False,
                  "files": {"target": {"dir": True}}, "junction": ["joined", "target"]}]
        made = advtime.Scene(self, "fleet junction")
        original = advtime.seed

        def seed(home, files):
            original(home, files)
            for case in cases:
                if case.get("home") == str(home) and case.get("junction"):
                    link, target = case["junction"]
                    subprocess.run(["cmd", "/c", "mklink", "/J", str(home / link), str(home / target)],
                                   capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        advtime.seed = seed
        try:
            found = made.run(cases)
        finally:
            advtime.seed = original
        self.assertEqual(found[0]["result"]["ok"], "link")
        del rng


class FleetDiff(unittest.TestCase):
    def walk(self, rng: random.Random) -> dict:
        setup = []
        generation = 0
        if rng.random() < 0.9:
            setup.append(["set_wording", [CAPABILITY, "fleet_alias", rng.choice(["PC-1", "PC-1", "CON", "PC 1"])],
                          {"generation": generation, "actor": "dashboard"}])
            generation += 1
        if rng.random() < 0.9:
            setup.append(["set_wording", [CAPABILITY, "fleet_folder", rng.choice(["{home}\\shared", "{home}\\shared",
                                                                                 "{home}\\gone", "{home}"])],
                          {"generation": generation, "actor": "dashboard"}])
        steps, now = [], NOW
        for _ in range(rng.randint(2, 9)):
            pick = rng.random()
            if pick < 0.5:
                steps += [["tick"], ["run"]]
            elif pick < 0.65:
                now += rng.choice([10, 299, 300, 301, 3600])
                steps.append(["clock", now])
            elif pick < 0.72:
                steps.append(["on", rng.random() < 0.7])
            elif pick < 0.82:
                steps.append(["seen"])
            else:
                steps.append(["tick"])
        files = {"shared": {"dir": True}, **peer_files(rng)}
        return {"op": "fl", "capability": CAPABILITY, "now": NOW, "setup": setup, "steps": steps, "files": files,
                "status": status(rng) if rng.random() < 0.92 else None, "on": rng.random() < 0.9,
                "bind": rng.random() < 0.95, "run_pass": rng.random() < 0.85, "spawn_raise": rng.random() < 0.05,
                "alive": [rng.choice([False, False, True]) for _ in range(rng.randint(1, 4))],
                "clock": [rng.choice([0.0, 1.0, 4.0, 6.0, 20.0]) for _ in range(rng.randint(1, 6))],
                "left": ["shared/PC-1.json", "shared/PC 1.json", "config/advanced/fleet-seen.json"]}

    def test_walks(self):
        rng = random.Random(7264)
        found = advtime.Scene(self, "fleet").run([self.walk(rng) for _ in range(300)])
        wrote = sum(1 for each in found if each["left"].get("shared/PC-1.json"))
        self.assertGreater(wrote, 30)


if __name__ == "__main__":
    unittest.main()
