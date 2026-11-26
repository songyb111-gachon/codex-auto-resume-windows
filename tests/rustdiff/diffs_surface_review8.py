"""review8 (REVIEW-surface.md): car-surface over inputs no S6.0 diff feeds. Both diffs FAIL today, on purpose.

* EdgeDiff - the reference interpreter the harness runs (3.13.15 here): the card at scales 0.5-5.0 (custom scaling,
  225%, 350%, 450%) with names of 1,000 characters, `CardMotion` at clocks near 10**12 and holds of NaN and infinity,
  corners and `premultiply` at radii and bands no diff feeds, the stack at sizes and gaps no screen has, the readers
  over the white space, separators and digits of other scripts the URI generator never mixes in, the local clock at the
  C runtime's edges, `int()` of texts in the near-limit, sleep and memory notices - all equal - but for two: the
  icon's `snapshot_from` over a row whose conversation id cannot be hashed beside a store whose disabled list fails
  (the reference raises the store's OSError, as it calls `disabled_threads()` before `in` hashes the id; car-surface
  TypeError, tray/model.rs hashing first: REVIEW-surface N1), and `corner_coverage` of a NaN radius (ValueError in
  the reference, `int(math.ceil(nan))`; an empty corner in car-surface: N2). 7 cases differ.
* ShippedInterpreterDiff - the same cases with the tag run by the interpreter the product ships (3.14; 3.14.10 is
  bundled, build/make_release.py PYTHON_VERSION; Unicode 16.0 against 3.13's 15.1): `int()` reads the eight digit
  blocks Unicode 16 added (Garay, Ol Onal, ...), so "\\U0001e5f9\\U0001e5f5" (Ol Onal 8, 4) is a near-limit share
  of 84 used ("16% left") and car-surface, whose digits are car-machine's 3.13 table (pytext_tables.rs), says no
  share at all. 13 cases differ (S1's 6 and EdgeDiff's 7). Found with `py -3.14`; CAR_REVIEW8_PYTHON names another
  interpreter. REVIEW-surface S1.
"""
from __future__ import annotations

import json
import os
import subprocess

import released
from rustdiff import core, reference
from rustdiff.leaves import PRELUDE
from rustdiff.surface import SURFACE, Surface, surface_tag

EDGES = r'''
from codex_auto_resume import l10n, notifier, notice_card, notify, notice_uris
UUID = "0a1b2c3d-3d4e-7f80-9a0b-1c2d3e4f5a6b"
KEY = "1" * 64
T = 1_800_000_000
cases = []
# card layout at scales no diff feeds, and long names
for locale in ("en", "ar", "de", "ja"):
    for scale in (0.5, 1.1, 1.13, 2.25, 3.5, 4.0, 4.5, 5.0):
        for identity in ({"name": "x" * 1000, "project": "y" * 500}, {"name": "a b " * 200}, None):
            cases.append(["card.layout", locale, "interruption", {"thread_id": UUID, "interruption_id": KEY,
                          "reset_at": T, "category": "usage_limit"}, identity, scale, None])
            cases.append(["card.layout", locale, "power_grace", {"action": "shut_down", "until": T + 120,
                          "nonce": "0123456789abcdef"}, identity, scale, "birthday"])
# motion at large clocks and odd holds
for now in (1e12, 123456789.125, -1e9):
    steps = [["new", now, 6000.0, False, [10, 20]]]
    t = now
    for d in (0.0, 16.0, 170.0, 340.0, 3000.0, 0.5, 6000.0, 100.0, 220.0, 1.0):
        t += d
        steps += [["frame", t], ["state"], ["move", t, [500, 600], 0.0], ["place", t + 7.0], ["wait", t]]
    cases.append(["card.motion", steps])
for hold in (float("nan"), float("-inf"), 1e308):
    cases.append(["card.motion", [["new", 0.0, hold, False, None], ["frame", 400.0], ["state"], ["wait", 500.0],
                                  ["pause", 600.0, True], ["pause", 700.0, False], ["state"], ["frame", 1e9], ["state"]]])
for elapsed in (float("-inf"), -0.0, 1e-300, 339.99999999999994):
    cases.append(["card.entrance", elapsed, False])
    cases.append(["card.leaving", elapsed, 0.6, False, 220])
# corners and premultiply at radii no diff feeds
for radius in (0.5, 2.5, 5.25, 36, 60, 100.5, -1, -0.5, float("nan")):
    for smoothing in (None, 0.0, 2.0, -0.5, 0.999):
        cases.append(["card.corner", radius, smoothing])
# a radius no card has (fix8, N2): infinity is OverflowError, a huge one OverflowError or MemoryError, never an abort
for radius in (float("inf"), float("-inf"), 1e300, 1e19, 1e18):
    for smoothing in (None, 0.0, 2.0):
        cases.append(["card.corner", radius, smoothing])
cases.append(["card.premultiply", "ab" * (4 * 30 * 10), 30, 40, 12, -5, None])
cases.append(["card.premultiply", "ab" * (4 * 30 * 10), 30, 40, 12, 35, None])
cases.append(["card.premultiply", "ab" * (4 * 30 * 10 + 1), 30, 40, 12, 0, None])
cases.append(["card.premultiply", "ab" * (4 * 30 * 10 + 3), 30, 40, 12, 0, None])
# stack at odd sizes
work, monitor = [0, 0, 1920, 1040], [0, 0, 1920, 1080]
for sizes in ([[0, 0]], [[-10, 50], [20, -5]], [[504, 333]] * 6, [[5000, 10]] * 3, [[504, 1100]], [[504, 520], [504, 520]]):
    for anchor in (None, [1800, 1050, 1824, 1074], [-5000, -5000, -4990, -4990]):
        for gap, spacing in ((12, 12), (-12, -3), (0, 600)):
            cases.append(["card.stack", sizes, work, monitor, anchor, gap, spacing])
# readers: characters the generator never mixes in
pieces = ["\x1c", "\x1d", "　", " ", "\u0085", " ", "​", "%1C", "%E3%80%80", "%C2%85", "%00", "%0A",
          ";", "%3B", "%26", "%3D", "٠" * 16, "０" * 16, "٩" * 64, "Historyİ", "Key"]
for piece in pieces:
    for uri in ("codex-auto-resume:open?page=%shistory%s" % (piece, piece),
                "codex-auto-resume:open?page=history&%s=1" % piece,
                "codex-auto-resume:%scancel%s?i=%s" % (piece, piece, KEY),
                "codex-auto-resume:cancel?i=%s%s" % (KEY, piece),
                "codex-auto-resume:cancel?i=%s" % piece,
                "codex-auto-resume:power-stop?n=%s" % piece,
                "codex-auto-resume:power-stop?n=0123456789abcdef%s" % piece,
                "codex-auto-resume://%sopen%s?page=history" % (piece, piece)):
        cases += [["uri.parse_cancel", uri], ["uri.parse_open", uri], ["uri.parse_power", uri],
                  ["uri.asks_flag", uri], ["uri.with_flag", uri], ["uri.split", uri]]
def split(uri):
    from urllib.parse import urlsplit
    parts = urlsplit(uri)
    return [parts.scheme, parts.netloc, parts.path, parts.query, parts.fragment]
# the near-limit share and the other int() readers over texts
texts = ["٩٥", " 95 ", "9_5", "+95", "95\n", "٥", "９５", "0x5f", "95.0", "1" * 4300,
         "1" * 4301, "-0", "²", "Ⅷ", "\U0001e5f9\U0001e5f5", "\U00010d49\U00010d45"]
for text in texts:
    cases.append(["notify.near", "en", 300, text, T + 3600, None])
    cases.append(["notify.slept", "en", text])
    cases.append(["notify.after_sleep", "en", 7200, text])
    cases.append(["notify.memory", "en", "memory_warning", text, text])
# the local clock at its edges
for when in (float("inf"), float("-inf"), 1e300, -1.5, -0.5, 0.5, 32503680000, 32503679999.5, 32536850000,
             2 ** 53, 2 ** 53 + 1, 2 ** 63, 2 ** 63 - 1, -2 ** 63, -2 ** 63 - 1, 86399.99999999999):
    cases.append(["notify.local_time", "en", when])
    cases.append(["notify.local_time", "fa", when])

# the icon's snapshot: a row whose conversation id cannot be hashed, beside a store whose disabled list fails
from codex_auto_resume.ui.tray import model as tray_model

class Store:
    def __init__(self, spec):
        self.spec = spec
    def pending(self):
        return answer(self.spec["pending"])
    def disabled_threads(self):
        return frozenset(answer(self.spec["disabled"]))
    def settings(self):
        return answer(self.spec["settings"])
    def failure_marks(self):
        return answer(self.spec["marks"])

for thread in ([1], {"a": 1}, UUID):
    for disabled in ({"raise": "OSError"}, [], [UUID]):
        cases.append(["tray.snapshot", {"pending": [{"state": "waiting_reset", "last_error": "app_server_unmatched",
                                                     "thread_id": thread}], "disabled": disabled,
                                        "settings": {"enabled": True}, "marks": None}])

OPS = {"notify.near": notify.near_limit_content, "notify.slept": notify.slept_for,
       "notify.after_sleep": notify.after_sleep_content, "notify.memory": notify.memory_content,
       "notify.local_time": notify._local_time}

def notify_op(name):
    return lambda locale, *args: (speak(locale), OPS[name](*args))[1]

def notice(locale, event, detail, identity):
    speak(locale)
    return notifier.build(event, detail, identity)

def layout(locale, event, detail, identity, scale, scene):
    vm = notice_card.view(notice(locale, event, detail, identity))
    vm["scene"] = scene
    return notice_card.layout(vm, scale, measure)

def state(m):
    slide = m._slide
    return {"phase": m.phase, "since": float(m.since), "hold_ms": float(m.hold_ms), "hold_left": float(m.hold_left),
            "paused": m.paused, "from_alpha": float(m.from_alpha), "exit_ms": float(m.exit_ms), "final": m.final,
            "position": None if m.position is None else list(m.position),
            "slide": None if slide is None else [list(slide[0]), list(slide[1]), float(slide[2])]}

def motion(steps):
    c, m, out = notice_card, None, []
    for step in steps:
        kind = step[0]
        if kind == "new":
            m = c.CardMotion(step[1], hold_ms=step[2], reduced=step[3], position=step[4]); out.append(None)
        elif kind == "frame":
            f = m.frame(step[1]); out.append([float(f.alpha), float(f.offset), float(f.scale), float(f.depth)])
        elif kind == "pause":
            out.append(m.pause(step[1], step[2]))
        elif kind == "move":
            out.append(m.move_to(step[1], step[2], step[3]))
        elif kind == "place":
            found = m.place(step[1]); out.append(None if found is None else list(found))
        elif kind == "wait":
            found = m.wait_ms(step[1]); out.append(None if found is None else float(found))
        else:
            out.append(state(m))
    return out

def stack(sizes, work, monitor, anchor, gap, spacing):
    positions, edge = notice_card.stack_positions([tuple(s) for s in sizes], tuple(work), tuple(monitor),
                                                  None if anchor is None else tuple(anchor), gap=gap, spacing=spacing)
    return [[list(p) for p in positions], edge]

frame = lambda f: [float(f.alpha), float(f.offset), float(f.scale), float(f.depth)]
ops = {"card.layout": layout, "card.motion": motion, "card.stack": stack,
       "card.entrance": lambda e, r: frame(notice_card.entrance(e, reduced=r)),
       "card.leaving": lambda e, s, r, d: notice_card.leaving(e, s, reduced=r, duration=d),
       "card.corner": lambda radius, smoothing: [row.hex() for row in notice_card.corner_coverage(radius, smoothing)],
       "card.premultiply": lambda pixels, width, height, radius, top, smoothing: bytes(notice_card.premultiply(
           bytes.fromhex(pixels), width, height, radius, top, smoothing)).hex(),
       "uri.parse_cancel": notice_uris.parse_cancel_uri, "uri.parse_open": notice_uris.parse_open_uri,
       "uri.parse_power": notice_uris.parse_power_stop_uri, "uri.asks_flag": notice_uris.cancel_asks_open_codex,
       "uri.with_flag": notice_uris.with_open_codex_flag, "uri.split": split,
       "tray.snapshot": lambda spec: tray_model.snapshot_from(Store(spec), 0)}
ops.update({name: notify_op(name) for name in OPS})
finish(cases, ops)
'''


def shipped_interpreter() -> str | None:
    """The interpreter the product ships (3.14): CAR_REVIEW8_PYTHON, else the launcher's 3.14, else None."""
    named = os.environ.get("CAR_REVIEW8_PYTHON")
    if named:
        return named
    try:
        found = subprocess.run(["py", "-3.14", "-c", "import sys; print(sys.executable)"], capture_output=True,
                               encoding="utf-8", errors="replace", timeout=60, creationflags=reference.NO_WINDOW)
    except OSError:
        return None
    return found.stdout.strip() if found.returncode == 0 and found.stdout.strip() else None


class Edges(Surface):
    """Every case run by the reference and by car-harness; every mismatch listed, not only the first."""

    def edges(self, interpreter: str | None, label: str) -> None:
        profile = self.profile("reference-" + label)
        if interpreter is None:
            made = reference.run(PRELUDE + SURFACE + EDGES, profile=profile, tag=surface_tag())
        else:
            # reference.run with another interpreter: the tag's src alone on the path, every home the scratch one.
            environment = reference.scratch_environment(profile, PYTHONPATH=str(released.package(surface_tag())))
            made = subprocess.run([interpreter, "-X", "utf8", "-c", PRELUDE + SURFACE + EDGES], capture_output=True,
                                  env=environment, cwd=str(profile), creationflags=reference.NO_WINDOW, timeout=300)
        self.assertEqual(made.returncode, 0, made.stderr[-3000:].decode("utf-8", "replace"))
        done = json.loads(made.stdout.decode("utf-8"))
        cases, expected = done["cases"], done["results"]
        actual = []
        with core.Harness(reference.scratch_environment(self.profile("rust-" + label))) as harness:
            for start in range(0, len(cases), 500):
                number, line = harness.call("surface.batch", cases=cases[start:start + 500], scratch=str(profile))
                reply = json.loads(line.decode("utf-8"))
                self.assertEqual(reply.get("id"), number, line[:300])
                self.assertTrue(reply["reply"].get("ok"), line[:600])
                actual += reply["reply"]["value"]
        self.assertEqual(len(actual), len(expected))
        bad = []
        for index, (want, got) in enumerate(zip(expected, actual)):
            wanted, gotten = (json.dumps(each, ensure_ascii=True, allow_nan=False) for each in (want, got))
            if wanted != gotten:
                bad.append("case %d %s\n    reference %s\n    rust      %s" % (
                    index, json.dumps(cases[index], ensure_ascii=True)[:300], wanted[:300], gotten[:300]))
        self.assertEqual(bad, [], "%s: %d of %d cases differ\n  %s" % (label, len(bad), len(cases), "\n  ".join(bad)))


class EdgeDiff(Edges):
    def test_edges(self):
        self.edges(None, "edges")


class ShippedInterpreterDiff(Edges):
    def test_edges_shipped(self):
        interpreter = shipped_interpreter()
        if interpreter is None:
            self.skipTest("no Python 3.14 here (CAR_REVIEW8_PYTHON names one)")
        self.edges(interpreter, "edges-314")
