"""The final-port seat (FINAL-DELTA.md, v0.6.26 final): the rows a diff of their own holds to the tag.

* StatusMeterDiff - `control/watcher.py` `get_status` (FINAL-DELTA #15, with #12/#13's `domain/usage.newest` and
  `meter_windows`): the last usage reading every surface says is the newest of the watcher's and the meter's an
  advanced plug adds to the status. A plug whose STATUS surface adds the world's `status_plug` (test_status_newest_usage's
  `MeterPlug`, on both sides: actworld's HOOK, car-harness `bridge.rs` `StatusPlug`) over the golden installation, the
  watcher's stored reading set to each of several, and meters of every shape: newer, older, the same time, broken,
  windows core cannot keep, a band, three windows of a bucket, a slot the watcher's reading names or does not, read_at
  of the wrong type, `added` that is no dict. Each answer, file, state row and Host call compared, as ControlCallDiff
  does (diffs_bridge_acting).

* PackageEnginesDiff - `codex/pairing.py` `package_engines`, `compat/probes.py` `_package_engines` and
  `compat/views.py` `_binding_holds` (FINAL-DELTA #6-#9, live acceptance R2b): the world's package folders
  (`packages`: appserverdiff's `fake_packages`, car-harness `appserver.rs` `World::package_roots`; never this PC's) over
  a scratch WindowsApps - the package engine (signed or not), the update trampoline, the main's slot, a program that is
  not codex, names in any case, a folder called codex.exe, depths 1 to 5, a junction, a root outside WindowsApps, with a
  trailing separator, absent, a file, twice, `..` in it - and the package manager refusing in three ways; reports bound
  to the package engine, to bin, to a replaced or vanished file, with the app's process list open, closed or refused.
  test_package_engine_bound's cases.

The fresh-home rows (#1-#5, #11) are held by diffs_codex_homes (`history-absent-*`), diffs_codex_compat_io
(`schema_variants`) and diffs_review6 (`r6_fresh_home_*`).

Run by run.py; never by the lanes' discovery.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3

from rustdiff import diffs_bridge_acting as acting
from rustdiff.appserverdiff import AppBase, facts, op
from rustdiff.diffs import RECORD

PUBLISHER = "2p2nqsd0c76g0"
OPENAI = "OpenAI OpCo, LLC"

DAY = 86400
COUNTS = {"cases": 0}


def windows(now: float, primary=0, secondary=0, *, minutes=(300, 10080), bucket="codex") -> list:
    return [{"bucket": bucket, "window": "primary", "used_percent": primary, "window_minutes": minutes[0],
             "reset_at": now + 3600},
            {"bucket": bucket, "window": "secondary", "used_percent": secondary, "window_minutes": minutes[1],
             "reset_at": now + DAY}]


def stored_reading(at, found):
    """The watcher's heartbeat holding this reading (the store's own columns), or none at all (`found` None)."""
    def tune(workspace):
        connection = sqlite3.connect(workspace / "home" / "config" / "state.sqlite")
        try:
            text = None if found is None else json.dumps(found, separators=(",", ":"), allow_nan=False)
            connection.execute("UPDATE watcher_status SET usage_at=?, usage=? WHERE singleton=1",
                               (None if found is None else at, text))
            connection.commit()
        finally:
            connection.close()
    return tune


class StatusMeterDiff(acting.ActingBase):
    def call(self, world, tune, label):
        COUNTS["cases"] += 1
        return self.run_both("acts", method="get_status", args=(), world=world, tune=tune, label=label)

    def test_the_status_says_the_newest_reading(self):
        now = acting.now()
        own_at = now - 4 * DAY
        readings = {
            "none": stored_reading(None, None),
            "watcher": stored_reading(own_at, windows(now)),
            "watcher, other lengths": stored_reading(own_at, windows(now, minutes=(60, 1440))),
            "watcher, slots swapped": stored_reading(own_at, [dict(windows(now)[0], window="secondary"),
                                                              dict(windows(now)[1], window="primary")]),
            "watcher, another bucket": stored_reading(own_at, windows(now, bucket="codex_other")),
        }

        def meter(read_at=own_at + 600, found=None, **extra):
            made = {"read_at": read_at, "notices": [], "windows": found if found is not None else [
                {"bucket": "codex", "window_minutes": 300, "used_percent": 12, "reset_at": now + 3600, "band": "none"},
                {"bucket": "codex", "window_minutes": 10080, "used_percent": 2, "reset_at": now + DAY,
                 "band": "warn"}]}
            made.update(extra)
            return {"meter": made}

        one = {"bucket": "codex", "window_minutes": 300, "used_percent": 12, "reset_at": now + 3600, "band": "none"}
        plugs = {
            "standard": None,
            "nothing added": {},
            "newer": meter(),
            "newer, int read_at": meter(read_at=int(own_at) + 600),
            "same time": meter(read_at=own_at),
            "older": meter(read_at=own_at - 1),
            "much newer": meter(read_at=1e300),
            "negative read_at": meter(read_at=-5),
            "read_at true": meter(read_at=True),
            "read_at text": meter(read_at=str(own_at + 600)),
            "read_at none": meter(read_at=None),
            "no read_at": {"meter": {"windows": [one]}},
            "windows not a list": meter(found={"0": one}),
            "no windows": {"meter": {"read_at": own_at + 600}},
            "empty windows": meter(found=[]),
            "one window": meter(found=[one]),
            "a window no dict": meter(found=[one, "x"]),
            "used_percent text": meter(found=[dict(one, used_percent="12")]),
            "half a minute": meter(found=[dict(one, window_minutes=300.5)]),
            "three of a bucket": meter(found=[one, dict(one, window_minutes=1440), dict(one, window_minutes=10080)]),
            "two buckets": meter(found=[one, dict(one, bucket="codex_other", window_minutes=60)]),
            "unknown bucket": meter(found=[dict(one, bucket="nope")]),
            "same length twice": meter(found=[one, dict(one, used_percent=50)]),
            "no minutes": meter(found=[dict(one, window_minutes=None), one]),
            "nine windows": meter(found=[dict(one, window_minutes=60 * (n + 1)) for n in range(9)]),
            "unicode bucket": meter(found=[dict(one, bucket="cödex")]),
            "meter not a dict": {"meter": [1, 2]},
            "meter null": {"meter": None},
            "added a list": [meter()],
            "added text": "meter",
            "added a number": 5,
            "other keys": dict(meter(), other={"x": 1}),
        }
        for reading, tune in readings.items():
            for name, plug in plugs.items():
                with self.subTest(reading=reading, plug=name):
                    self.call({"status_plug": plug}, tune, "get_status, %s, %s" % (reading, name))
        RECORD.append("finalport status meter: %d get_status cases equal" % COUNTS["cases"])


class PackageEnginesDiff(AppBase):
    def test_package_engines_and_the_binding(self):
        folder = self.profile("packages")
        local, native = folder / "local", folder / "pf"
        bin_exe = local / "OpenAI" / "Codex" / "bin" / "0123abcd" / "codex.exe"
        bin_exe.parent.mkdir(parents=True)
        bin_exe.write_bytes(b"MZ-bin")
        apps = native / "WindowsApps"
        root = apps / ("OpenAI.Codex_26.1120.0.0_x64__" + PUBLISHER)
        engine = root / "app" / "resources" / "codex.exe"
        engine.parent.mkdir(parents=True)
        engine.write_bytes(b"MZ-package-0.171")
        files = {
            "trampoline": root / "app" / "Codex.exe",
            "main slot": root / "app" / "codex.exe",
            "node": root / "app" / "resources" / "node.exe",
            "upper": root / "app" / "tools" / "CODEX.EXE",
            "depth 1": root / "codex.exe",
            "depth 4": root / "a" / "b" / "c" / "codex.exe",
            "depth 5": root / "a" / "b" / "c" / "d" / "codex.exe",
            "codex.exe.bak": root / "app" / "resources" / "codex.exe.bak",
        }
        for path in files.values():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"MZ-" + path.name.encode())
        (root / "app" / "folder" / "codex.exe").mkdir(parents=True)
        # A junction below the package folder, to a folder of it that holds an engine (a folder to Python 3.12+).
        target = root / "linked-target"
        target.mkdir()
        (target / "codex.exe").write_bytes(b"MZ-linked")
        try:
            import _winapi

            _winapi.CreateJunction(str(target), str(root / "junction"))
        except (ImportError, OSError):
            pass
        second = apps / ("OpenAI.Codex_26.1201.0.0_arm64__" + PUBLISHER)
        (second / "app" / "resources").mkdir(parents=True)
        (second / "app" / "resources" / "codex.exe").write_bytes(b"MZ-second")
        elsewhere = folder / "elsewhere" / ("OpenAI.Codex_26.1120.0.0_x64__" + PUBLISHER)
        (elsewhere / "app" / "resources").mkdir(parents=True)
        (elsewhere / "app" / "resources" / "codex.exe").write_bytes(b"MZ-elsewhere")
        stranger = apps / "Other.App_1.0.0.0_x64__abcdefghijklm"
        (stranger / "app" / "resources").mkdir(parents=True)
        (stranger / "app" / "resources" / "codex.exe").write_bytes(b"MZ-stranger")
        a_file = folder / "a-file"
        a_file.write_bytes(b"x")
        every = [engine] + list(files.values()) + [target / "codex.exe", root / "junction" / "codex.exe",
                                                   second / "app" / "resources" / "codex.exe",
                                                   elsewhere / "app" / "resources" / "codex.exe",
                                                   stranger / "app" / "resources" / "codex.exe", bin_exe]
        signed_all = {str(path).lower(): OPENAI for path in every}
        known = facts()
        spec = {"bundled": known["bundled"], "reported": known["reported"], "cache_file": str(folder / "cache.json"),
                "version": known["version"], "report_file": str(folder / "report.json")}

        def report_on(exe):
            stat = exe.stat()
            return {"engine": {"found": True, "version": "codex-cli 0.171.0", "candidates": 1,
                               "signature": [stat.st_size, stat.st_mtime_ns],
                               "path_digest": hashlib.sha256(str(exe.resolve()).lower().encode("utf-8")).hexdigest()}}

        reports = [report_on(each) for each in (engine, bin_exe, files["trampoline"], files["node"],
                                                elsewhere / "app" / "resources" / "codex.exe",
                                                second / "app" / "resources" / "codex.exe", files["depth 4"],
                                                target / "codex.exe")]
        reports.append({"engine": dict(report_on(engine)["engine"], signature=[1, 2])})
        reports.append({"engine": dict(report_on(engine)["engine"], path_digest="b" * 64)})
        ops = [op("package_engines"), op("registry.package_engines")]
        ops += [op("registry.binding", spec, report, None) for report in reports]
        ops += [op("registry.binding", spec, reports[0], str(bin_exe))]
        env = {"LOCALAPPDATA": str(local), "ProgramW6432": str(native)}
        app_open = [{"pid": 10, "parent": 1, "path": str(root / "app" / "ChatGPT.exe"), "created": 100,
                     "family": "OpenAI.Codex_" + PUBLISHER},
                    {"pid": 20, "parent": 10, "path": str(engine), "created": 200}]
        sep = chr(92)
        rooted = {
            "the package": [str(root)],
            "two packages": [str(root), str(second)],
            "twice": [str(root), str(root)],
            "trailing separator": [str(root) + sep],
            "forward slashes": [str(root).replace(sep, "/")],
            "upper case": [str(root).upper()],
            "outside WindowsApps": [str(elsewhere)],
            "another package": [str(stranger)],
            "absent": [str(apps / ("OpenAI.Codex_9.9.9.9_x64__" + PUBLISHER))],
            "a file": [str(a_file)],
            "dot dot": [str(root / "app") + sep + ".."],
            "empty text": [""],
            "none": [],
            "not texts": [5, None, str(root)],
            "refused OSError": {"raise": "OSError"},
            "refused AdapterError": {"raise": "windows_required"},
            "refused ValueError": {"raise": "ValueError"},
        }
        cases = []
        for packages in rooted.values():
            for signers in (signed_all, {}):
                for processes in ([], app_open, {"raise": "OSError"}):
                    cases.append({"world": {"env": env, "packages": packages, "signers": signers,
                                            "processes": processes, "restart_manager": True}, "ops": ops})
        # No packages at all: the world says nothing (the guard's answer on a PC with the app, CI's on one without).
        cases.append({"world": {"env": env, "signers": signed_all, "processes": []}, "ops": ops})
        count, calls = self.script(cases, "package engines", chunk=20)
        # The file replaced, then gone, under the same reports.
        engine.write_bytes(b"MZ-package-0.172-and-longer")
        replaced = self.script(cases[:6], "package engine replaced", chunk=20)
        engine.unlink()
        gone = self.script(cases[:6], "package engine gone", chunk=20)
        RECORD.append("finalport package engines: %d worlds, %d calls equal (+%d replaced, +%d gone)"
                      % (count, calls, replaced[1], gone[1]))


if __name__ == "__main__":
    import unittest

    unittest.main()
