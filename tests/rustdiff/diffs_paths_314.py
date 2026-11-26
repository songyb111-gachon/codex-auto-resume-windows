"""`os.path.realpath` of a home whose missing tail has a component spelled like a drive, on the bundled Python 3.14.10.

3.13's `ntpath.realpath` joined the part it could not resolve with `ntpath.join`, which reads `a:b` as a new drive and
drops everything before it; 3.14.10's `_getfinalpathname_nonstrict` joins with a local `join` that keeps it as a name
(REFERENCE-314.md, finding C). The product ships 3.14.10, so `config.Paths(home)` of `<tree>\\h\\a:b` is `<tree>\\h\\a:b`
and its twenty-one names follow. The same fifteen homes run on the tag (bundled Python) and on car-config through
`paths.build`; under `--reference-python system` (3.13.15) the eight that name a drive-like tail differ BY DESIGN.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import unittest

from rustdiff import reference
from rustdiff.diffs_leaves_config import ENV, ConfigBase

RECORD: list[str] = []

# The first eight are the ones 3.13.15 and 3.14.10 answer differently; the rest are equal on both (a reserved device
# name, a trailing dot or space, an alternate-data-stream name that is not one letter, `a:b\..` which resolves away).
DIFFERENT = ["@/a:b", "@/h/a:b", "@/h/a:b/c", "@/a:", "@/h/x:y:z", "@/h/a:b:$DATA", "@/h/../a:b", "@/h/c:/x"]
EQUAL = ["@/h/CON", "@/h/aux.txt", "@/h/nul.x", "@/h/trailing. ", "@/h/ADS:stream", "@/h/a:b/..", "@/h/z:\\q\\w"]


class DriveLikeTails(ConfigBase):
    def long_paths(self) -> bool:
        """Whether this system takes a path past 260 characters as it is (the same probe as PathsDiff's)."""
        probe = self.profile("probe")
        deep = probe
        for index in range(6):
            deep = deep / ("long-folder-name-%02d-" % index + "x" * 45)
        os.makedirs("\\\\?\\" + str(deep))
        script = ("import os, sys, json\nsys.stdout.write(json.dumps(os.path.realpath(sys.argv[1]).startswith(chr(92) * 2 + '?' + chr(92))))")
        done = reference.run(script, str(deep), profile=probe)
        self.assertEqual(done.returncode, 0, done.stderr[-1000:])
        return not json.loads(done.stdout)

    def test_fifteen_homes(self):
        long_paths = self.long_paths()
        template = [["paths.build", home, "@/root", ENV, "@/cwd", long_paths] for home in DIFFERENT + EQUAL]
        self.assertEqual(len(template), 15)

        def tree(root: Path):
            for folder in ("h", "root", "cwd", "profile", "local"):
                (root / folder).mkdir(parents=True, exist_ok=True)
        expected = self.pair("drive-tails", template, tree=tree)
        homes = [result["ok"]["home"] for result in expected if "ok" in result]
        self.assertEqual(len(homes), 15)
        # The tag's own answer keeps the tail as a name (`<tree>\h\a:b`), not the drive `a:b` 3.13 made of it.
        tree = "\\ref-drive-tails\\tree"
        self.assertTrue(homes[1].endswith(tree + "\\h\\a:b"), homes[1])
        self.assertTrue(homes[2].endswith(tree + "\\h\\a:b\\c"), homes[2])
        self.assertTrue(homes[7].endswith(tree + "\\h\\c:\\x"), homes[7])
        self.assertTrue(all(tree in each for each in homes), homes)
        RECORD.append("realpath of a drive-like tail: 15 homes (8 that 3.13 joined as a new drive, 7 equal on both) give every name "
                      "equal to the bundled Python 3.14.10's")


if __name__ == "__main__":
    unittest.main()
