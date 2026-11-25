"""The float's text, character for character: car-machine's JSON writer, `pytext::float_repr` and car-brand's
`pyfmt::repr` against the reference interpreter's `json.dumps` and `repr` (REVIEW-int5 S1).

The other leaves diffs re-read every answer with `json.loads` and write it again before comparing, so a float that
Rust wrote with a digit too few or too many but that reads back as a nearby float was never seen. Here each float
goes to Rust as its bits and comes back as text, and the texts are compared. The cases are the ones a shortest-digits
rule gets wrong and random bits seldom reach: every power of two in the f64 range and its neighbours, the
subnormals, the doubles around every decimal exponent, the non-finite values, and random values.
"""
from __future__ import annotations

from rustdiff.leaves import Leaves

RECORD: list[str] = []


class FloatTextDiff(Leaves):
    def test_every_float_text(self):
        script = r'''
import math, struct
rng = random.Random(1125)

def bits(x):
    return struct.pack(">d", x).hex()

def around(x, steps=2):
    for step in range(-steps, steps + 1):
        n = struct.unpack(">q", struct.pack(">d", abs(x)))[0] + step
        if 0 <= n < 0x7FF0000000000000:
            y = struct.unpack(">d", struct.pack(">q", n))[0]
            yield y
            yield -y

values = []
for exponent in range(-1074, 1024):
    values += around(math.ldexp(1.0, exponent))
for n in list(range(1, 2049)) + list(range(0x000FFFFFFFFFF800, 0x0010000000000800)):
    values.append(struct.unpack(">d", struct.pack(">q", n))[0])
for k in range(-324, 309):
    for mantissa in ["1", "5", "9.999999999999999", "9.9999999999999999", "1.0000000000000002"]:
        x = float("%se%d" % (mantissa, k))
        if x and math.isfinite(x):
            values += around(x)
values += [0.0, -0.0, float("nan"), float("inf"), float("-inf"), struct.unpack(">d", bytes.fromhex("7ff8000000000001"))[0],
           struct.unpack(">d", bytes.fromhex("fff8000000000000"))[0], 224335367548872.625]
for _ in range(100000):
    values.append(struct.unpack(">d", rng.randbytes(8))[0])
    values.append(float("%de%d" % (rng.randrange(10 ** rng.randint(1, 17)), rng.randint(-330, 310))))
cases = []
for x in values:
    cases.append(["pytext.float_texts", bits(x)])
    cases.append(["pyfmt.repr_bits", bits(x)])
ops = {"pytext.float_texts": lambda b: (lambda x: [json.dumps(x) if math.isfinite(x) else None, repr(x)])(struct.unpack(">d", bytes.fromhex(b))[0]),
       "pyfmt.repr_bits": lambda b: repr(struct.unpack(">d", bytes.fromhex(b))[0])}
finish(cases, ops)
'''
        done = self.family(script, label="float-texts", chunk=20000)
        RECORD.append("float texts: %d floats (every power of two, the subnormals, every decimal exponent's boundary, "
                      "random) written by the JSON writer, pytext::float_repr and pyfmt::repr as json.dumps and repr "
                      "write them, character for character" % (len(done["cases"]) // 2))
