"""S1.1, car-machine: the domain, the registry's format and Python's text, held to the reference tag's own answers.

* VocabParity - every word of vocab.json (`build/vocab_export.py --ref TAG`) of the modules car-machine, car-config
  and car-words hold is the same in Rust: the Rust side's `export()` is compared with the tag's, module by module,
  and the three generated files are what the tag's vocabulary generates (`gen_vocab.py --check`).
* TextTables - Python's `str.isspace` and decimal digits, for each of the 1,114,112 code points.
* HashDiff, TextDiff, IdsDiff, StatesDiff, UsageDiff, PublicDiff, CompatDiff - the functions of `domain/` and of
  `compat/model.py`, over generated cases and hand-picked edges, each answer or each exception's class compared.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unicodedata

from rustdiff import core, diffs, reference
from rustdiff.leaves import Leaves

ROOT = core.ROOT
RECORD: list[str] = []


def generator(name):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        return __import__(name)
    finally:
        sys.path.pop(0)


class VocabParity(Leaves):
    def test_every_word_is_the_same(self):
        gen = generator("gen_vocab")
        vocab = gen.vocabulary(reference.TAG)
        with core.Harness(reference.scratch_environment(self.profile("rust"))) as harness:
            number, line = harness.call("leaves.batch", cases=[["vocab.export"]])
        rust = json.loads(line.decode("utf-8"))["reply"]["value"][0]["ok"]
        self.assertEqual(sorted(rust), sorted(gen.MINE))
        words = 0
        for name in gen.MINE:
            want, got = json.dumps(vocab["modules"][name], ensure_ascii=False), json.dumps(rust[name], ensure_ascii=False)
            self.assertEqual(got, want, "%s differs from %s's vocabulary" % (name, reference.TAG))
            body = vocab["modules"][name]
            words += sum(len(found["members"]) for found in body.get("enums", {}).values()) + len(body.get("constants", {}))
        RECORD.append("vocab: %d modules, %d enum members and constants, identical to %s's vocab.json" % (
            len(gen.MINE), words, reference.TAG))

    def test_the_generated_files_are_what_the_tag_generates(self):
        gen = generator("gen_vocab")
        files = gen.generate(gen.vocabulary(reference.TAG))
        for crate, text in files.items():
            path = ROOT / "rust" / "crates" / crate / "src" / "vocab_gen.rs"
            self.assertEqual(path.read_bytes().decode("utf-8"), text, "%s is stale: gen_vocab.py --write" % path.name)


class TextTables(Leaves):
    def test_every_code_point(self):
        script = r'''
import unicodedata
out = []
for point in range(0x110000):
    if 0xD800 <= point < 0xE000:
        out.append("-")
        continue
    char = chr(point)
    value = unicodedata.decimal(char, None)
    out.append("S" if char.isspace() else ("-" if value is None else str(value)))
sys.stdout.write(json.dumps("".join(out)))
'''
        profile = self.profile("reference-tables")
        made = reference.run(PRELUDE_ONLY + script, profile=profile)
        self.assertEqual(made.returncode, 0, made.stderr[-2000:].decode("utf-8", "replace"))
        wanted = json.loads(made.stdout.decode("utf-8"))
        with core.Harness(reference.scratch_environment(self.profile("rust"))) as harness:
            _number, line = harness.call("leaves.batch", cases=[["pytext.classes"]])
        got = json.loads(line.decode("utf-8"))["reply"]["value"][0]["ok"]
        self.assertEqual(len(got), len(wanted))
        for point, (want, have) in enumerate(zip(wanted, got)):
            if want != have:
                self.fail("U+%04X: Python says %r, Rust says %r (gen_tables.py --write)" % (point, want, have))
        RECORD.append("tables: str.isspace and the decimal digits agree for all 1114112 code points (Unicode %s)"
                      % unicodedata.unidata_version)


PRELUDE_ONLY = "import json, sys\n"


class HashDiff(Leaves):
    def test_sha1_and_sha256(self):
        script = r'''
import hashlib
rng = random.Random(1)
cases = []
for size in list(range(0, 140)) + [255, 256, 1000, 4096, 100000]:
    data = rng.randbytes(size)
    cases += [["hash.sha256", data.hex()], ["hash.sha1", data.hex()]]
ops = {"hash.sha256": lambda h: hashlib.sha256(bytes.fromhex(h)).hexdigest(),
       "hash.sha1": lambda h: hashlib.sha1(bytes.fromhex(h)).hexdigest()}
finish(cases, ops)
'''
        done = self.family(script, label="hash")
        RECORD.append("hash: sha1 and sha256 of %d inputs (0 to 100000 bytes) equal hashlib's" % len(done["cases"]))


class TextDiff(Leaves):
    def test_strip_int_float(self):
        script = r'''
import struct
rng = random.Random(2)
spaces = ["", " ", "\t", "\n", "\x0b", "\x1c", "\x1f", "\x85", "\xa0", " ", " ", "​", " ", "　", "﻿"]
digits = ["0", "7", "f", "F", "g", "_", "-", "+", "x", "X", "١", "۲", "１", "²", " ", "　", "z", "."]
cases = []
for _ in range(400):
    cases.append(["pytext.strip", rng.choice(spaces) + "".join(rng.choice("ab " + "".join(spaces)) for _ in range(rng.randrange(6))) + rng.choice(spaces)])
for text in ["ff", "0xFF", " 0xFF ", "0x_f_f", "-0", "+1", "0x", "", "_", "f_", "f__f", "0x__1", "1_0", "١٢", "٣", "0X1", "0b1",
             "ffffffffffffffffffffffffffffffff", "f" * 33, "-" + "f" * 32, "1 2", "1　", "　1"]:
    cases.append(["pytext.int16", text])
for _ in range(1500):
    cases.append(["pytext.int16", "".join(rng.choice(digits) for _ in range(rng.randrange(1, 12)))])
for value in [0.0, -0.0, 1.0, 0.1, 1e16, 1e-320, 5e-324, 1.7976931348623157e308, 123456.789, True, False, 3, -7, 2 ** 70, 10 ** 400, "1.5", " 2 ", "1_0.5", "inf", "-Infinity", "nan", "1e400", ".5", "5.", "1e", "e5", "0x10", "", None, [1], "٣.٥"]:
    cases.append(["pytext.float_hex", value])
for _ in range(2000):
    bits = struct.unpack("<d", rng.randbytes(8))[0]
    if bits == bits and abs(bits) != float("inf"):
        cases.append(["pytext.float_hex", bits])
for text in ["1.5", "  -2.5e3 ", "1_000.5", "1__0", "_1", "1_", "+inf", "-INF", "Infinity", "NaN", "nan(1)", "1e", "1e+", "1e+5", ".", "-.5e-3", "1.2.3", "0x1p3", "١٢.٥", "1e999", "1,5", "", " "]:
    cases.append(["pytext.float_from_text", text])
ops = {"pytext.strip": lambda s: s.strip(),
       "pytext.int16": lambda s: (lambda n: [n < 0, str(abs(n)) if abs(n) < 2 ** 128 else None])(int(s, 16)),
       "pytext.float_hex": lambda x: float(x).hex(),
       "pytext.float_from_text": lambda s: float(s).hex()}
finish(cases, ops)
'''
        done = self.family(script, label="text")
        RECORD.append("text: strip, int(,16), float() and float.hex() equal Python's over %d cases" % len(done["cases"]))
