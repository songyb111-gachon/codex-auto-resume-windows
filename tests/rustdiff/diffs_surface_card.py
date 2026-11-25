"""S6.0, car-surface: notice_card.py - the card's words, every rectangle it draws, its life on a clock, the stack, the
shadow it floats on and its rounded edge.

* ViewDiff - `view` and `texts` of every notice kind in all 22 languages (the product's name, the chip, a long or
  odd name cut to one line, the origin cut at 200, the buttons and which is the accent).
* LayoutDiff - `layout` at five scales, right to left in Arabic, Hebrew and Persian (`mirror`), with a special day's
  band and without, with no chip, no line, no origin, one, two, three and five buttons, labels too wide to stand side
  by side, and `mirror` of plans with rows; the renderer's measure is the shared stand-in.
* MotionDiff - `entrance`, `leaving`, `ease_in`, `rise_vector`, `hold_ms`, `depth_level`, and `CardMotion` over
  scripted lives: enter, hold, pause while pointed at and resume with the grace, leave and be brought back, retire
  (quick or not, while entering, holding, leaving or gone), restart, delay, glide to a place, reduced motion, a hold
  until clicked; every state field compared after every step.
* StackDiff - `popup.place`, `taskbar_edge`, `stack_direction` and `stack_positions` over taskbars on each edge, an
  auto-hidden one, monitors left of and above the primary, short screens that hold one or two cards.
* ShadowDiff - `float_shadows` for both themes and every design (and the names that raise), `shadow_at`,
  `shadow_margin`, `corner_coverage` (the circle and Soft's squircle, at the radii the scales make) and `premultiply`
  of whole cards and of bands (and of pixels no card has).
"""
from __future__ import annotations

from rustdiff.surface import Surface, counted

RECORD: list[str] = []

CARD = r'''
from codex_auto_resume import l10n, notifier, notice_card
UUID = "0a1b2c3d-3d4e-7f80-9a0b-1c2d3e4f5a6b"
KEY = "1" * 64
T = 1_800_000_000
EVENTS = [("interruption", {"thread_id": UUID, "interruption_id": KEY, "reset_at": T, "category": "usage_limit"}),
          ("interruption", {"thread_id": UUID, "interruption_id": KEY, "category": "server_5xx", "hold": "ask"}),
          ("result", {"thread_id": UUID, "state": "resumed"}), ("result", {"thread_id": UUID, "state": "failed"}),
          ("stopped", {"thread_id": UUID, "reason": "parent_cancelled"}),
          ("needs_you", {"thread_id": UUID, "category": "terminal_auth"}),
          ("after_sleep", {"slept": 9000, "count": 4}), ("memory_stopped", {"used": 800, "limit": 512}),
          ("near_limit", {"minutes": 300, "percent": 95, "reset_at": T + 600}),
          ("power_grace", {"action": "shut_down", "until": T + 120, "nonce": "0123456789abcdef"}),
          ("python_returned", {"content": {"title": "t", "body": "b", "more": [["Open diagnostics now please",
                                                                                "codex-auto-resume:open?page=diagnostics"]] * 5,
                                           "button": "Cancel this", "uri": "codex-auto-resume:cancel?i=" + KEY}})]
IDENTITIES = [None, {"name": "example-project"}, {"name": "x" * 400, "project": "example-service"},
              {"name": "שלום עולם", "project": "مشروع"},
              {"name": "例子项目 一二三 四五六", "cwd_basename": "docs"}]

def notice(locale, event, detail, identity):
    speak(locale)
    return notifier.build(event, detail, identity)

def view(locale, event, detail, identity):
    return notice_card.view(notice(locale, event, detail, identity))

def layout(locale, event, detail, identity, scale, scene):
    vm = view(locale, event, detail, identity)
    vm["scene"] = scene
    return notice_card.layout(vm, scale, measure)

cases = []
for locale in l10n.LOCALES:
    for index, (event, detail) in enumerate(EVENTS):
        identity = IDENTITIES[index % len(IDENTITIES)]
        cases.append(["card.view", locale, event, detail, identity])
        cases.append(["card.texts", locale, event, detail, identity])
        cases.append(["card.layout", locale, event, detail, identity, 1.5, None])
for locale in ("en", "de", "ar", "he", "fa", "ja", "ko", "th"):
    for event, detail in EVENTS:
        for identity in IDENTITIES:
            for scale in (1, 1.25, 2.0, 3, 1.75):
                cases.append(["card.layout", locale, event, detail, identity, scale, None])
        for scene in ("birthday", "new_year", "christmas", "seollal", "chuseok", "nope"):
            cases.append(["card.layout", locale, event, detail, None, 1.5, scene])
labels = ["Stop", "Open Dashboard", "x" * 40, "Überprüfung der Einstellungen jetzt", ""]
for count in range(6):
    for label in labels:
        actions = [{"label": label if index % 2 == 0 else "Open", "uri": "codex-auto-resume:open?page=pending" if index
                    else "codex-auto-resume:cancel?i=" + KEY, "primary": index > 0, "target": ["action", index]}
                   for index in range(count)]
        for chip, line, origin in (("Usage limit", "line", "origin"), (None, "", ""), ("A chip far too long " * 4,
                                                                                  "l " * 80, "o " * 120)):
            vm = {"product": "Codex Auto Resume", "status": "waiting", "chip": chip, "chip_tone": "attention",
                  "title": "title", "line": line, "origin": origin, "actions": actions, "click": "", "locale": "en",
                  "scene": None}
            for scale in (1, 2.5):
                cases.append(["card.layout_vm", vm, scale])
            cases.append(["card.layout_vm", dict(vm, locale="ar"), 1.25])
plan = {"size": [100, 40], "card": [0, 0, 100, 40], "items": [{"kind": "text", "rect": [1, 2, 30, 4], "align": "center"},
        {"kind": "halo", "cx": 10.5}, {"kind": "text", "rect": [0, 0, 5, 5], "align": "right"}], "targets": [[["a", 1], [0, 0, 1, 1]]],
        "rows": [["r", [2, 2, 3, 3]]], "scale": 1}
cases += [["card.mirror", plan], ["card.mirror", dict(plan, rows=[])], ["card.mirror", {"size": [5]}],
          ["card.mirror", dict(plan, items=[{"kind": "text", "align": []}])], ["card.consts"]]

def consts():
    return [notice_card.WIDTH, notice_card.CARD_WIDTH, notice_card.MAX_CARDS, notice_card.FRAME_MS,
            notice_card.BREATH_FRAME_MS, notice_card.ENTRANCE_MS, notice_card.EXIT_MS, notice_card.SLIDE_MS,
            notice_card.SWAP_MS, notice_card.STACK_DELAY_MS, notice_card.HOLD_MS, notice_card.HOVER_GRACE_MS,
            notice_card.RISE, notice_card.SCALE_FROM, notice_card.ALPHA_SHARE, notice_card.DEPTH_START,
            notice_card.DEPTH_LEVELS, notice_card.FLOAT_SHADOW_INK, notice_card.FLOAT_SHADOW_THEME,
            notice_card.DARK_ENOUGH, notice_card.HEADER_KEY, notice_card.USUAL_HEIGHT, notice_card.UNTIL_CLICKED]

ops = {"card.view": view, "card.texts": lambda *args: notice_card.texts(view(*args)), "card.layout": layout,
       "card.layout_vm": lambda vm, scale: notice_card.layout(vm, scale, measure),
       "card.mirror": lambda plan: __import__("codex_auto_resume.ui.popup", fromlist=["mirror"]).mirror(plan),
       "card.consts": consts}
finish(cases, ops)
'''

MOTION = r'''
import random
from codex_auto_resume import notice_card as c
rng = random.Random(340)
cases = []
for elapsed in [-50, 0, 1, 50.5, 119, 170, 339.9, 340, 400, float("nan"), float("inf")]:
    for reduced in (False, True):
        cases.append(["card.entrance", elapsed, reduced])
        for duration in (220, 130, 0, 1):
            cases.append(["card.leaving", elapsed, 0.6, reduced, duration])
for progress in [-1, 0, 0.25, 0.5, 1, 2, float("nan")]:
    cases.append(["card.ease_in", progress])
for edge in ["bottom", "top", "left", "right", "x", None, []]:
    cases.append(["card.rise", edge])
for duration in [None, 0, 5000, 6000, 9000, 9000.5, True, "9000", float("inf"), float("nan"), 10 ** 400, -(10 ** 400)]:
    cases.append(["card.hold_ms", duration])
for depth in [-1, 0, 0.09, 0.1, 0.3, 0.5, 0.7, 0.9, 1, 2, float("nan")]:
    cases.append(["card.depth_level", depth])

def life():
    steps = [["new", rng.choice([0.0, 1000.0, 5.5]), rng.choice([6000.0, 0.0, 9000.0, float("inf"), -5.0]),
              rng.random() < 0.2, rng.choice([None, [10, 20]])]]
    now = steps[0][1]
    for _ in range(rng.randint(3, 40)):
        now += rng.choice([0.0, 16.0, 50.0, 130.0, 220.0, 340.0, 1000.0, 1500.0, 6000.0, 33.3])
        kind = rng.choice(["frame", "frame", "pause", "unpause", "retire", "quick", "restart", "delay", "move", "place",
                           "moving", "wait", "gone", "state"])
        if kind == "pause":
            steps.append(["pause", now, True])
        elif kind == "unpause":
            steps.append(["pause", now, False])
        elif kind == "retire":
            steps.append(["retire", now, False])
        elif kind == "quick":
            steps.append(["retire", now, True])
        elif kind == "delay":
            steps.append(["delay", rng.choice([0.0, 120.0, -5.0])])
        elif kind == "move":
            steps.append(["move", now, [rng.randint(-50, 2000), rng.randint(-50, 1200)], rng.choice([0.0, 120.0, -3.0])])
        else:
            steps.append([kind, now])
        steps.append(["state"])
    return steps

for _ in range(400):
    cases.append(["card.motion", life()])

def state(m):
    slide = m._slide
    return {"phase": m.phase, "since": float(m.since), "hold_ms": float(m.hold_ms), "hold_left": float(m.hold_left),
            "paused": m.paused, "from_alpha": float(m.from_alpha), "exit_ms": float(m.exit_ms), "final": m.final,
            "position": None if m.position is None else list(m.position),
            "slide": None if slide is None else [list(slide[0]), list(slide[1]), float(slide[2])]}

def motion(steps):
    m, out = None, []
    for step in steps:
        kind = step[0]
        if kind == "new":
            m = c.CardMotion(step[1], hold_ms=step[2], reduced=step[3], position=step[4])
            out.append(None)
        elif kind == "frame":
            f = m.frame(step[1])
            out.append([float(f.alpha), float(f.offset), float(f.scale), float(f.depth)])
        elif kind == "pause":
            out.append(m.pause(step[1], step[2]))
        elif kind == "retire":
            out.append(m.retire(step[1], quick=step[2]))
        elif kind == "restart":
            out.append(m.restart(step[1]))
        elif kind == "delay":
            out.append(m.delay(step[1]))
        elif kind == "move":
            out.append(m.move_to(step[1], step[2], step[3]))
        elif kind == "place":
            found = m.place(step[1])
            out.append(None if found is None else list(found))
        elif kind == "moving":
            out.append(m.moving(step[1]))
        elif kind == "wait":
            found = m.wait_ms(step[1])
            out.append(None if found is None else float(found))
        elif kind == "gone":
            out.append(m.gone)
        else:
            out.append(state(m))
    return out

frame = lambda f: [float(f.alpha), float(f.offset), float(f.scale), float(f.depth)]
ops = {"card.entrance": lambda e, r: frame(c.entrance(e, reduced=r)),
       "card.leaving": lambda e, s, r, d: c.leaving(e, s, reduced=r, duration=d), "card.ease_in": c.ease_in,
       "card.rise": c.rise_vector, "card.hold_ms": c.hold_ms, "card.depth_level": c.depth_level, "card.motion": motion}
finish(cases, ops)
'''

STACK = r'''
import random
from codex_auto_resume import notice_card as c
from codex_auto_resume.ui import popup
rng = random.Random(3)
screens = [([0, 0, 1920, 1040], [0, 0, 1920, 1080]), ([0, 40, 1920, 1080], [0, 0, 1920, 1080]),
           ([60, 0, 1920, 1080], [0, 0, 1920, 1080]), ([0, 0, 1860, 1080], [0, 0, 1860 + 60, 1080]),
           ([0, 0, 1920, 1080], [0, 0, 1920, 1080]), ([-1920, -300, 0, 740], [-1920, -300, 0, 780]),
           ([0, 0, 1366, 728], [0, 0, 1366, 768]), ([0, 0, 2880, 1752], [0, 0, 2880, 1800])]
anchors = [None, [1800, 1050, 1824, 1074], [10, 500, 34, 524], [900, 0, 924, 30], [-100, 700, -76, 724], [5, 5, 6, 6]]
cases = []
for work, monitor in screens:
    for anchor in anchors:
        cases.append(["popup.edge", work, monitor, anchor])
        for size in ([360, 200], [504, 333], [1, 1], [4000, 4000]):
            for cursor in (None, [700, 700]):
                cases.append(["popup.place", size, work, monitor, anchor, cursor, rng.choice([12, 0, 18])])
        for count in range(5):
            sizes = [[rng.choice([504, 420, 630]), rng.choice([240, 333, 400, 500])] for _ in range(count)]
            for gap, spacing in ((12, 12), (18, 9), (0, 0)):
                cases.append(["card.stack", sizes, work, monitor, anchor, gap, spacing])
        for edge in ("bottom", "top", "left", "right"):
            for y in (0, 400, 700, 1000):
                cases.append(["card.direction", edge, y, 333, work])

def place(size, work, monitor, anchor, cursor, gap):
    return list(popup.place(tuple(size), tuple(work), tuple(monitor), None if anchor is None else tuple(anchor),
                            None if cursor is None else tuple(cursor), gap=gap))

def stack(sizes, work, monitor, anchor, gap, spacing):
    positions, edge = c.stack_positions([tuple(s) for s in sizes], tuple(work), tuple(monitor),
                                        None if anchor is None else tuple(anchor), gap=gap, spacing=spacing)
    return [[list(p) for p in positions], edge]

ops = {"popup.edge": lambda work, monitor, anchor: popup.taskbar_edge(tuple(work), tuple(monitor),
                                                                      None if anchor is None else tuple(anchor)),
       "popup.place": place, "card.stack": stack,
       "card.direction": lambda edge, y, h, work: c.stack_direction(edge, y, h, tuple(work))}
finish(cases, ops)
'''

SHADOW = r'''
import random
from codex_auto_resume import notice_card as c
rng = random.Random(16)
cases = []
for theme in ("light", "dark", None, "system", 5):
    for design in ("soft", "classic", "plain", None, "x"):
        cases.append(["card.float_shadows", theme, design])
settled = [[4, 4, 14, "#05080C", 0.5], [-4, -4, 14, "#05080C", 0.25], [0, 6, 18, "#05080C", 0.35]]
for depth in (0, 0.25, 0.5, 1, 1.5, -1):
    cases.append(["card.shadow_at", settled, depth])
for scale in (1, 1.25, 2.0, 3):
    cases.append(["card.shadow_margin", settled, scale])
    cases.append(["card.shadow_margin", [], scale])
for radius in (0, 1, 3, 7.5, 16, 20, 24, 32, 48, 12.0):
    for smoothing in (None, 0.0, 0.6, 0.3, 1.0):
        cases.append(["card.corner", radius, smoothing])
for width, height, radius in ((40, 40, 16), (60, 24, 20), (10, 10, 16), (336, 200, 24), (3, 3, 2)):
    pixels = bytes(rng.randrange(256) for _ in range(4 * width * height)).hex()
    for smoothing in (None, 0.0):
        cases.append(["card.premultiply", pixels, width, height, radius, 0, smoothing])
    band = bytes(rng.randrange(256) for _ in range(4 * width * min(height, 6))).hex()
    for top in (0, 2, height - 6, height - 3):
        cases.append(["card.premultiply", band, width, height, radius, top, None])
cases += [["card.premultiply", "0102030405", 1, 1, 4, 0, None], ["card.premultiply", "00" * 12, 2, 1, 4, 0, None],
          ["card.premultiply", "", 0, 0, 4, 0, None], ["card.premultiply", "00" * 8, 0, 2, 4, 0, None],
          ["card.premultiply", "ff" * 16, -2, 2, 4, 0, None]]

def shadows(theme, design):
    return [list(s) for s in c.float_shadows(theme, design)]

ops = {"card.float_shadows": shadows,
       "card.shadow_at": lambda found, depth: [list(s) for s in c.shadow_at([c.FloatShadow(*s) for s in found], depth)],
       "card.shadow_margin": lambda found, scale: c.shadow_margin([c.FloatShadow(*s) for s in found], scale),
       "card.corner": lambda radius, smoothing: [row.hex() for row in c.corner_coverage(radius, smoothing)],
       "card.premultiply": lambda pixels, width, height, radius, top, smoothing: bytes(c.premultiply(
           bytes.fromhex(pixels), width, height, radius, top, smoothing)).hex()}
finish(cases, ops)
'''


class ViewDiff(Surface):
    def test_card(self):
        done = self.family(CARD, label="card", chunk=1000)
        RECORD.append("card: %d views, %d texts and %d layouts (5 scales, right to left, special days, 0-5 buttons) equal "
                      "the tag's" % (counted(done, "card.view"), counted(done, "card.texts"),
                                     counted(done, "card.layout") + counted(done, "card.mirror")))


class MotionDiff(Surface):
    def test_motion(self):
        done = self.family(MOTION, label="card-motion")
        steps = sum(len(case[1]) for case in done["cases"] if case[0] == "card.motion")
        RECORD.append("motion: %d curve cases and %d CardMotion lives (%d steps, every state field after each) equal "
                      "the tag's" % (len(done["cases"]) - counted(done, "card.motion"), counted(done, "card.motion"),
                                     steps))


class StackDiff(Surface):
    def test_stack(self):
        done = self.family(STACK, label="card-stack")
        RECORD.append("stack: %d placement, edge, direction and stack cases equal the tag's" % len(done["cases"]))


class ShadowDiff(Surface):
    def test_shadow(self):
        done = self.family(SHADOW, label="card-shadow")
        RECORD.append("shadow: %d floating-shadow, corner and premultiply cases equal the tag's"
                      % len(done["cases"]))
