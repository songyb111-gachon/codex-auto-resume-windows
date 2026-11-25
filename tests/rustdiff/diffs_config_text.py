"""The bytes of the text files car-config writes, against the tag's (fix4, from the S7.1a seat's finding).

config.py writes its provenance markers with `Path.write_text(OWNER_TEXT, encoding="utf-8")`: text mode on Windows, so
the marker's line ends are CRLF. `ensure()` and `claim_home()` run on a fresh home on both sides (the tag's through its
own Paths, car-config's through the harness), and every file either made is compared byte for byte, names included. The
log's lines are held the same way by the logbook diffs (`diffs_leaves_log.py` reads the files back).
"""
from __future__ import annotations

from pathlib import Path
import unittest

from rustdiff.diffs_leaves_config import ENV, ConfigBase

RECORD: list[str] = []


def files(root: Path) -> dict:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


class ConfigTextBytes(ConfigBase):
    def test_the_markers_are_the_tags_bytes(self):
        def tree(root: Path):
            (root / "fresh").mkdir()
        template = [["paths.mutate", "@/fresh", "@/root", ENV, "@/", False, []]]
        self.pair("text-bytes", template, tree=tree)
        ours, theirs = self.scratch / "ref-text-bytes", self.scratch / "rust-text-bytes"  # what pair's roots() made
        want, got = files(ours / "tree" / "fresh"), files(theirs / "tree" / "fresh")
        self.assertTrue(any(name.endswith(".owned-by-codex-auto-resume") for name in want), sorted(want))
        self.assertTrue(all(b"\r\n" in data for name, data in want.items() if name.endswith("-auto-resume")))
        self.assertEqual(got, want, "the files car-config writes differ in bytes from the tag's")
        RECORD.append("config text: %d files ensure() and claim_home() write, byte for byte the tag's" % len(want))


if __name__ == "__main__":
    unittest.main()
