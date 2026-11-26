"""S7.2b: `codex/authfile.py`'s acts on files - read, replace atomically, the owned folder and its marker, confined,
the removal that follows no link, the sweep of what a kill left, the scratch home - held equal to the v0.6.26 final on
copies of the same folders, the files left compared byte for byte. Junctions are the test's own, made in scratch.

Alone: `cd tests && PYTHONPATH="../src;." python -X utf8 -m unittest rustdiff.diffs_advaccount_files`.
"""
from __future__ import annotations

import os
import stat

from rustdiff.advaccount import AdvAccountDiff, junction, sign_in

RECORD: list[str] = []
OLD = 1_000_000_000
NOW = OLD + 2000


def touch(path, at):
    os.utime(path, (at, at))


class AuthFileActsDiff(AdvAccountDiff):
    def test_read_and_replace(self):
        good = bytes.fromhex(sign_in("a@b.c"))

        def setup(root):
            for name, data in (("good", good), ("broken", b"{nope"), ("list", b"[1]"), ("empty", b""),
                               ("big", b'{"a": "' + b"x" * 70000 + b'"}'), ("bom", b"\xef\xbb\xbf{}")):
                (root / name).mkdir()
                (root / name / "auth.json").write_bytes(data)
            (root / "dir").mkdir()
            (root / "dir" / "auth.json").mkdir()
            (root / "none").mkdir()
            (root / "held").mkdir()
            (root / "held" / "auth.json.car-00000001").write_bytes(b"x")
        cases = [["af.read", name] for name in ("good", "broken", "list", "empty", "big", "bom", "dir", "none", "gone")]
        cases += [["af.replace", "good", {"hex": sign_in("new@b.c")}], ["af.replace", "none", {"hex": sign_in("x@y")}],
                  ["af.replace", "gone", {"hex": sign_in("x@y")}], ["af.replace", "good", {"hex": b"[]".hex()}],
                  ["af.replace", "dir", {"hex": sign_in("x@y")}], ["af.replace", "held", {"hex": sign_in("x@y")}],
                  ["af.replace", "good", "not bytes"]]
        RECORD.append("authfile read/replace: %d cases" % len(cases))
        self.same("read-replace", cases, setup=setup, one_by_one=True)

    def test_owned_folder_confined_and_removed(self):
        def setup(root):
            (root / "kept").mkdir()
            (root / "kept" / ".owned-by-codex-auto-resume").write_text("x", encoding="utf-8")
            (root / "afile").write_bytes(b"x")
            junction(root / "link", root / "elsewhere")
            (root / "elsewhere" / "inside.txt").write_bytes(b"keep me")
            tree = root / "tree"
            (tree / "a" / "b").mkdir(parents=True)
            (tree / "a" / "b" / "f.txt").write_bytes(b"1")
            (tree / "g.txt").write_bytes(b"2")
            (tree / "ro.txt").write_bytes(b"3")
            os.chmod(tree / "ro.txt", stat.S_IREAD)
            junction(tree / "j", root / "target")
            (root / "target" / "t.txt").write_bytes(b"not followed")
        cases = [["af.own_folder", "new/accounts"], ["af.own_folder", "kept"], ["af.own_folder", "afile"],
                 ["af.own_folder", "link"], ["af.confined", "kept"], ["af.confined", "link"], ["af.confined", "missing"],
                 ["af.confined", "elsewhere"], ["af.confined", "tree/a"], ["af.remove_tree", "tree"],
                 ["af.remove_tree", "link"], ["af.remove_tree", "missing"], ["af.remove_tree", "afile"]]
        self.same("owned-folder", cases, setup=setup, one_by_one=True)

    def test_the_sweep(self):
        def setup(root):
            accounts, home = root / "accounts", root / "codex"
            accounts.mkdir()
            home.mkdir()
            names = {"scratch-0123456789ab": OLD, "scratch-aaaaaaaaaaaa": NOW - 10, "scratch-0123456789AB": OLD,
                     "scratch-bbbbbbbbbbbb": NOW - 1300}
            for name, at in names.items():
                (accounts / name).mkdir()
                (accounts / name / "auth.json").write_bytes(b"{}")
                touch(accounts / name / "auth.json", at)
                touch(accounts / name, at)
            for name, at in {"x.dat.car-0123abcd": OLD, "y.dat.car-0123abcd": NOW - 5, "z.dat.car-0123abcde": OLD,
                             "q.dat.car-00000000": NOW - 61, "keep.dat": OLD}.items():
                (accounts / name).write_bytes(b"t")
                touch(accounts / name, at)
            junction(accounts / "scratch-cccccccccccc", root / "away")
            (root / "away" / "auth.json").write_bytes(b"{}")
            for name, at in {"auth.json.car-0123abcd": OLD, "auth.json.car-11111111": NOW - 30,
                             "x.dat.car-0123abcd": OLD, "auth.json": OLD}.items():
                (home / name).write_bytes(b"h")
                touch(home / name, at)
            (accounts / "scratch-dddddddddddd").write_bytes(b"a file, not a home")
            touch(accounts / "scratch-dddddddddddd", OLD)
            touch(accounts, OLD)
        cases = []
        for stale in (1200, 0, 5000, 30):
            cases.append(["af.sweep", "accounts", "codex", NOW, stale])
        cases += [["af.sweep", "accounts", None, NOW, 1200], ["af.sweep", "missing", "codex", NOW, 1200],
                  ["af.sweep", "accounts", "missing", NOW, 1200], ["af.sweep", "accounts", "codex", OLD - 100, 1200],
                  ["af.sweep", "codex", "accounts", NOW, 0], ["af.sweep", "accounts", "codex", NOW, 1200.5]]
        RECORD.append("sweep: %d cases" % len(cases))
        self.same("sweep", cases, setup=setup, one_by_one=True)

    def test_the_scratch_home(self):
        def setup(root):
            (root / "kept").mkdir()
            (root / "kept" / ".owned-by-codex-auto-resume").write_text("x", encoding="utf-8")
            junction(root / "link", root / "away")
            (root / "afile").write_bytes(b"x")
        data = {"hex": sign_in("a@b.c")}
        cases = []
        for root in ("accounts", "kept", "link", "afile"):
            for given in (data, None, {"hex": b"[]".hex()}):
                for action in ("keep", {"write": {"hex": sign_in("a@b.c", "r1")}}, "unlink", "raise",
                               {"write": {"hex": b"{bad".hex()}}):
                    cases.append(["af.scratch", root, given, action])
        RECORD.append("scratch home: %d cases" % len(cases))
        self.same("scratch", cases, setup=setup, one_by_one=True)
