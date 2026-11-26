"""S2.1, car-policy's generated files, held to the reference.

* VocabParity - every word of vocab.json (`build/vocab_export.py --ref TAG`) of the eleven Python modules S2.1 ports
  is the same in Rust (`export()` of car-policy's `classify::vocab_gen::MODULES`, module by module), and the
  generated files are what the tag and the product's bundled Python generate (`gen_policy.py --check`, run as its own process).
* TextTables - Python's `str.lower()`, `str.casefold()` and `re`'s `\\w`, for each of the 1,114,112 code points, as the
  reference's interpreter answers them.
* SeamParity - the copy of S2.2's `ownvalues` and plug words in car-policy's seam is the reference's (the functions are
  held by diffs_classify_policy.py's `own.*` cases).
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from rustdiff import core, reference
from rustdiff.leaves import Leaves

RECORD: list[str] = []


def generator():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import gen_policy
    finally:
        sys.path.pop(0)
    return gen_policy


class VocabParity(Leaves):
    def test_every_word_is_the_same(self):
        gen = generator()
        vocab = gen._gen_vocab().vocabulary(reference.TAG)
        rust = self.rust("leaves.batch", cases=[["classify.vocab"]])["value"][0]["ok"]
        self.assertEqual(sorted(rust), sorted(gen.MINE))
        words = 0
        for name in gen.MINE:
            want = json.dumps(vocab["modules"][name], ensure_ascii=False)
            self.assertEqual(json.dumps(rust[name], ensure_ascii=False), want,
                             "%s differs from %s's vocabulary" % (name, reference.TAG))
            body = vocab["modules"][name]
            words += sum(len(found["members"]) for found in body.get("enums", {}).values()) + len(body.get("constants", {}))
        RECORD.append("classify vocab: %d modules, %d constants, identical to %s's vocab.json"
                      % (len(gen.MINE), words, reference.TAG))

    def test_the_generated_files_are_what_the_tag_generates(self):
        # The generator's own --check: it runs itself under the product's bundled Python (productpy.py), whose Unicode
        # tables text_tables.rs and unicode_gen.rs hold - generated in this process (3.13.15, say) they would differ.
        done = subprocess.run(reference.script_command(Path(__file__).resolve().parent / "gen_policy.py", "--check", "--ref",
                                                       reference.TAG, paths=[]), cwd=str(core.ROOT), capture_output=True,
                              creationflags=reference.NO_WINDOW, timeout=900)
        self.assertEqual(done.returncode, 0, "gen_policy.py --check: %s%s" % (
            done.stdout.decode("utf-8", "replace"), done.stderr.decode("utf-8", "replace")[-2000:]))


class TextTables(Leaves):
    def test_every_code_point(self):
        script = r'''
import re
word = re.compile(r"\w")
out, lowered, folded = [], [], []
for point in range(0x110000):
    if 0xD800 <= point < 0xE000:
        out.append("-")
        continue
    char = chr(point)
    out.append("w" if word.match(char) else ".")
    if char.lower() != char:
        lowered.append([point, char.lower()])
    if char.casefold() != char:
        folded.append([point, char.casefold()])
sys.stdout.write(json.dumps(["".join(out), lowered, folded], ensure_ascii=False))
'''
        made = reference.run(script.replace("import re", "import json, re, sys"), profile=self.profile("reference"))
        self.assertEqual(made.returncode, 0, made.stderr[-2000:])
        theirs = json.loads(made.stdout.decode("utf-8"))
        mine = self.rust("leaves.batch", cases=[["classify.tables"]])["value"][0]["ok"]
        self.assertEqual(len(mine[0]), len(theirs[0]))
        for point, (want, got) in enumerate(zip(theirs[0], mine[0])):
            if want != got:
                self.fail("\\w differs at U+%04X: python %r, rust %r" % (point, want, got))
        self.assertEqual(mine[1], theirs[1], "str.lower() differs")
        self.assertEqual(mine[2], theirs[2], "str.casefold() differs")
        RECORD.append("classify text tables: \\w of 1,112,064 code points, %d lower() and %d casefold() mappings, "
                      "the reference interpreter's" % (len(theirs[1]), len(theirs[2])))


class SeamParity(Leaves):
    def test_the_plug_words_are_the_references(self):
        done = self.family(r'''
from codex_auto_resume.domain.plug import TAKE_UP, PACED_AS
finish([["own.plug"]], {"own.plug": lambda: [sorted(TAKE_UP), {str(k): v for k, v in PACED_AS.items()}]})
''', label="seam")
        RECORD.append("classify seam: TAKE_UP and PACED_AS (S2.2's plug words) equal to %s's" % reference.TAG)
        self.assertEqual(len(done["cases"]), 1)
        self.assertTrue(core.ROOT.exists())
