"""S7.2c remainder: `codex/tokens.py` as the v0.6.26 final has it, held equal to car-adv's `codex::tokens`.

`read` over generated rollouts: the first line's conversation (a uuid in either case, not one, missing, of no text) and
folder; token_count lines with last and running totals (missing kinds, booleans, floats, negatives, past MOST), repeats
of the same totals (a rate-limit update), task_started lines, lines past LINE_BYTES, damaged UTF-8 and JSON, CRLF, a last
line still being written; timestamps short, malformed, around midnight UTC and before 1970 (the local clock's OSError,
let out as the reference lets it out); every `known` row shape (none, empty, the same and another conversation, an
offset inside a line, at and past the end, LOOK_BACK away) and budgets from none to past FILE_BYTES - each under three
TZ settings (unset, JST-9, EST5EDT), because the local day is the C runtime's `localtime` on both sides.
`rollouts` over homes with nested folders, a junction, a folder named like a rollout, a `.JSONL`, files older than
`keep_days`; `file_key`, `unchanged` and `watched_homes` (told, untold, the codex_homes setting, duplicates).

Alone: `cd tests && PYTHONPATH="../src;." python -X utf8 -m unittest rustdiff.diffs_advcodex_tokens`.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import random
import subprocess

from rustdiff.advcodexd import AdvCodexRestDiff

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
THREAD = "0a1b2c3d-c3d4-7e5f-8a9b-0c1d2e3f4a5b"
OTHER = "0a1b2c3d-c3d4-7e5f-8a9b-0c1d2e3f4a5c"
KINDS = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")
STAMPS = ["2026-10-22T03:04:05.123Z", "2026-10-22T23:59:59.999Z", "2026-10-22T00:00:00Z", "2026-10-21T14:59:59Z",
          "2026-10-21T15:00:00Z", "2026-03-08T07:00:00Z", "2026-11-01T05:30:00Z", "2024-02-29T12:00:00Z",
          "1970-01-01T00:00:00Z", "1969-12-31T23:59:59Z", "2026-10-22T03:04", "2026-13-22T03:04:05Z", "garbage",
          "2026-10-22 03:04:05", "２０２６-10-22T03:04:05Z", None, 17, "2026-10-22T03:04:61Z"]


def counts(rng: random.Random, base=None) -> dict:
    if rng.random() < 0.08:
        return rng.choice([None, [], "x", {"input_tokens": 1}])
    out = {}
    for index, kind in enumerate(KINDS):
        value = (base[index] if base else 0) + rng.randint(0, 5000)
        roll = rng.random()
        if roll < 0.02:
            value = True
        elif roll < 0.04:
            value = float(value)
        elif roll < 0.05:
            value = -1
        elif roll < 0.06:
            value = 10 ** 13 + 1
        elif roll < 0.07:
            value = 10 ** 13
        out[kind] = value
    return out


def line_of(rng: random.Random, totals: list) -> bytes:
    roll = rng.random()
    stamp = rng.choice(STAMPS) if rng.random() < 0.3 else rng.choice(STAMPS[:8])
    if roll < 0.15:
        event = {"timestamp": stamp, "type": "event_msg", "payload": {"type": "task_started", "turn_id": "t"}}
    elif roll < 0.2:
        return b'{"type":"event_msg","payload":{"type":"token_count"' + b"\xff\xfe" + b'}}'
    elif roll < 0.24:
        return b'{"type":"event_msg","payload":{"type":"token_count",' + b"x" * rng.randint(0, 40)
    elif roll < 0.27:
        return json.dumps({"timestamp": stamp, "type": "event_msg", "payload": {
            "type": "token_count", "info": {"last_token_usage": counts(rng)}, "pad": "y" * (64 * 1024)}}).encode()
    elif roll < 0.32:
        return json.dumps({"timestamp": stamp, "type": "response_item", "payload": {"type": "message",
                                                                                     "text": "token_count"}}).encode()
    elif roll < 0.36:
        # A repeat of the totals last seen: a rate-limit update.
        event = {"timestamp": stamp, "type": "event_msg", "payload": {"type": "token_count", "info": {
            "total_token_usage": dict(zip(KINDS, totals)) if totals else None}, "rate_limits": {}}}
    else:
        total = counts(rng, totals)
        info = {"total_token_usage": total}
        if rng.random() < 0.7:
            info["last_token_usage"] = counts(rng)
        if rng.random() < 0.05:
            info = rng.choice([None, "info", []])
        event = {"timestamp": stamp, "type": "event_msg", "payload": {"type": "token_count", "info": info}}
        if isinstance(total, dict) and all(type(total.get(k)) is int and 0 <= total[k] <= 10 ** 13 for k in KINDS):
            totals[:] = [total[k] for k in KINDS]
    if rng.random() < 0.03:
        event["type"] = "event_msg " if rng.random() < 0.5 else ["event_msg"]
    return json.dumps(event, ensure_ascii=rng.random() < 0.5).encode("utf-8")


def first_line(rng: random.Random) -> bytes:
    ident = rng.choice([THREAD, THREAD.upper(), OTHER, "not-a-uuid", None, 42, THREAD + " "])
    cwd = rng.choice(["C:\\Work\\Project", "c:/work/project/", "", None, 5, "\\\\server\\share\\x"])
    payload = {"id": ident, "cwd": cwd, "originator": "codex_cli_rs"}
    if ident is None:
        payload.pop("id")
    if rng.random() < 0.05:
        return b'{"type":"session_meta","payload":' + b"{" * 3
    kind = "session_meta" if rng.random() < 0.95 else "turn_context"
    return json.dumps({"timestamp": STAMPS[0], "type": kind, "payload": payload}).encode()


def rollout_bytes(rng: random.Random) -> bytes:
    totals: list = []
    lines = [first_line(rng)] + [line_of(rng, totals) for _ in range(rng.randint(0, 60))]
    newline = b"\r\n" if rng.random() < 0.1 else b"\n"
    data = newline.join(lines)
    if rng.random() < 0.7:
        data += newline
    elif rng.random() < 0.5:
        data += newline + b'{"timestamp":"2026-10-22T03:04:05Z","type":"event_msg","payload":{"type":"task_st'
    return data


class TokensDiff(AdvCodexRestDiff):
    def setUp(self):
        self.held_tz = os.environ.get("TZ")

    def tearDown(self):
        if self.held_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self.held_tz

    def test_read(self):
        rng = random.Random(7210)
        folder = self.fresh("rollouts")
        cases = []
        for index in range(220):
            data = rollout_bytes(rng)
            path = folder / ("rollout-%03d.jsonl" % index)
            path.write_bytes(data)
            size = len(data)
            changed = 1767225600000000000 + index
            rollout = [str(folder), str(path), "k%03d" % index, size, changed]
            knowns = [None, {}, {"thread_id": THREAD, "offset": 0}, {"thread_id": OTHER, "offset": 10},
                      {"thread_id": THREAD, "offset": size}, {"thread_id": THREAD, "offset": size + 5},
                      {"thread_id": THREAD.upper(), "offset": 3}, {"offset": 4}]
            for _ in range(3):
                knowns.append({"thread_id": THREAD, "offset": rng.randint(0, max(size, 1)),
                               "size": size, "mtime_ns": changed})
            for known in knowns:
                budget = rng.choice([0, -3, 1, 40, 200, 1000, 2 * 1024 * 1024, 9 * 1024 * 1024, size])
                cases.append(["tk.read", rollout, known, budget])
                cases.append(["tk.unchanged", rollout, known])
        # The size the row says, and the one the file has, apart (a file that shrank or grew since its stat).
        cases.append(["tk.read", [str(folder), str(folder / "rollout-000.jsonl"), "k", 10 ** 7, 1], None, 10 ** 7])
        cases.append(["tk.read", [str(folder), str(folder / "missing.jsonl"), "k", 10, 1], {"offset": 3}, 100])
        cases.append(["tk.read", [str(folder), str(folder), "k", 10, 1], None, 100])
        # LOOK_BACK: totals far before where the pass begins.
        big = folder / "rollout-big.jsonl"
        totals: list = []
        lines = [json.dumps({"timestamp": STAMPS[0], "type": "session_meta", "payload": {"id": THREAD}}).encode()]
        while sum(len(line) + 1 for line in lines) < 700 * 1024:
            lines.append(line_of(rng, totals))
        big.write_bytes(b"\n".join(lines) + b"\n")
        size = big.stat().st_size
        for offset in (0, 100, 256 * 1024, 256 * 1024 + 1, 300 * 1024, 600 * 1024, size - 1, size):
            for budget in (1000, 64 * 1024, 2 * 1024 * 1024):
                cases.append(["tk.read", [str(folder), str(big), "kb", size, 5], {"thread_id": THREAD, "offset": offset},
                              budget])
        for zone in (None, "JST-9", "EST5EDT"):
            if zone is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = zone
            want = self.same("read-%s" % zone, cases)
            self.assertGreater(sum(1 for one in want if isinstance(one.get("ok"), list) and one["ok"][5]), 200)
        self.assertTrue(any(one.get("error") == "OSError" for one in want))

    def test_rollouts_and_homes(self):
        rng = random.Random(7211)
        root = self.fresh("homes")
        homes = []
        for name in ("one", "two", "three"):
            home = root / name
            sessions = home / "sessions"
            for depth in range(rng.randint(1, 4)):
                folder = sessions.joinpath(*["d%d" % level for level in range(depth)], "2026", "10")
                folder.mkdir(parents=True, exist_ok=True)
                for index in range(rng.randint(0, 6)):
                    path = folder / ("rollout-%d-%d.jsonl" % (depth, index))
                    path.write_bytes(rollout_bytes(rng))
                    age = rng.choice([0, 10, 89, 91, 400]) * 86400 + rng.randint(0, 3600)
                    stamp = 1767225600 - age
                    os.utime(path, ns=(stamp * 10 ** 9 + rng.randint(0, 10 ** 9 - 1),) * 2)
            (sessions / "UPPER.JSONL").write_bytes(b"{}\n")
            (sessions / "dir.jsonl").mkdir(exist_ok=True)
            (sessions / "dir.jsonl" / "inner.jsonl").write_bytes(rollout_bytes(rng))
            (sessions / "notes.txt").write_bytes(b"x")
            homes.append(str(home))
        outside = root / "outside"
        (outside / "deep").mkdir(parents=True)
        (outside / "deep" / "rollout-outside.jsonl").write_bytes(rollout_bytes(rng))
        subprocess.run(["cmd", "/c", "mklink", "/J", str(root / "one" / "sessions" / "joined"), str(outside)],
                       capture_output=True, creationflags=NO_WINDOW, check=True)
        empty = root / "empty"
        empty.mkdir()
        (root / "filehome").mkdir()
        (root / "filehome" / "sessions").write_bytes(b"x")
        lists = [homes, homes[::-1], [homes[0], homes[0].upper(), homes[0] + "\\"], [str(empty), str(root / "missing")],
                 [str(root / "filehome")], [], [homes[1].replace("\\", "/")]]
        cases = []
        for listed in lists:
            for now, keep in ((1767225600.0, 90), (1767225600.5, 0), (1767225600.0, 400), (1767225600.0, -1),
                              (1767225600.0, 91), (1767232800.25, 90)):
                cases.append(["tk.rollouts", listed, now, keep])
        for path in [homes[0] + "\\sessions\\d0\\2026\\10", homes[0].upper(), homes[1] + "/sessions/../sessions",
                     str(root / "missing" / "x.jsonl"), "relative\\x.jsonl", "C:\\", "\\\\?\\" + homes[2]]:
            cases.append(["tk.file_key", path])
        want = self.same("rollouts", cases)
        self.assertTrue(any(one["ok"] for one in want if isinstance(one.get("ok"), list) and one["ok"]))

        # watched_homes: the told home or CODEX_HOME's, then the codex_homes setting, each once.
        installation = root / "install"
        (installation / "config").mkdir(parents=True)
        settings = installation / "config" / "settings.json"
        variants = [None, [], [{"path": homes[1], "alias": "Two"}], [{"path": homes[1]}, {"path": homes[1].upper()}],
                    [{"path": homes[2], "alias": "x"}, {"path": str(root / "missing"), "alias": "m"}],
                    "nonsense", [{"nope": 1}], [{"path": 5}]]
        profile = root / "profile"
        profile.mkdir()
        for told in (False, True):
            for variant in variants:
                if variant is None:
                    settings.unlink(missing_ok=True)
                else:
                    settings.write_text(json.dumps({"codex_homes": variant}), encoding="utf-8")
                cases = [["tk.tell", str(installation), str(root / "codex.exe"), homes[0]]] if told else []
                cases += [["tk.watched_homes", str(installation)], ["tk.watched_homes", None]]
                self.same("homes", cases, profile=profile)
