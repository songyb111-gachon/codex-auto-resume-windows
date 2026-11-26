"""S2.2, the plug held to the tag: PLUG_API and the interface's tables, what NULL answers at every point (P2-P22) and
what core takes of it through `Guarded`, the closed set each decision point keeps (`consult`), and the checks core
holds a plug's values to (`records_of`, `workers`, `fields`, `kinds_of`, `widening_of`, `Guarded.power`). Also the
vocabularies of every module the seat ports, and car-policy's generated files, against what the tag generates.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from rustdiff import core, reference
from rustdiff.settingsdiff import Family

RECORD: list[str] = []
ROOT = Path(__file__).resolve().parents[2]

PLUG = r'''
from codex_auto_resume.domain import plug as P, plughands as H
from codex_auto_resume import edition
from codex_auto_resume.domain.plugwords import Alternative, Point
rng = random.Random(3)
def d(answer):
    if answer is P.DEFER:
        return "DEFER"
    if answer is P.BACKEND:
        return "BACKEND"
    if isinstance(answer, Alternative):
        return answer.value
    return answer
def tables():
    return {"PLUG_API": P.PLUG_API, "POINTS": [point.value for point in P.POINTS], "POWER_TASKS": list(P.POWER_TASKS),
            "POWER_THREADS": P.POWER_THREADS, "EXTRA": P.EXTRA,
            "HOOKS": {point.value: P.HOOKS[point] for point in Point},
            "ALTERNATIVES": {point.value: sorted(word.value for word in P.ALTERNATIVES[point])
                             for point in Point if point in P.ALTERNATIVES},
            "PACED_AS": {word.value: P.PACED_AS[word] for word in Alternative if word in P.PACED_AS},
            "QUEUED": sorted(word.value for word in P.QUEUED), "ANSWERS": sorted(word.value for word in P.ANSWERS),
            "RECORDS_LIMIT": H.RECORDS_LIMIT, "MAX_WORKERS": H.MAX_WORKERS, "WORDS_LIMIT": H.WORDS_LIMIT,
            "ERRAND_GUARDS": H.ERRAND_GUARDS, "NOT_LOADED": edition.NOT_LOADED}
def null():
    N, record = P.NULL, {}
    hooks = {"records": d(N.records(None)), "gate": d(N.gate("consent", record, record)), "text": d(N.text(record, "x")),
             "sender": d(N.sender(record, P.BACKEND)), "outcome": d(N.outcome(record, "recovered")),
             "schedule": d(N.schedule(record, 0.0)), "tick": d(N.tick(None)), "start_route": d(N.start_route(record)),
             "surface": d(N.surface("status", record)), "claim_ledger": d(N.claim_ledger(None, record, 0.0, ())),
             "partition": d(N.partition([])), "supervise": d(N.supervise(record)), "moved": d(N.moved(record, "recovered")),
             "delivery": d(N.delivery(record)), "unloaded": d(N.unloaded(record)), "admission": d(N.admission(record)),
             "sessions": d(N.sessions()), "eligibility": d(N.eligibility()), "notice": d(N.notice(record)),
             "power": d(N.power(record)), "resident": d(N.resident(None))}
    assert set(hooks) == set(P.HOOKS.values())
    g = P.Guarded(P.NULL)
    told = []
    g.notice(lambda: told.append(1) or {})
    backend = object()
    held = {"null": g.null, "edition": str(g.edition), "badge": g.badge, "records": list(g.records(None)),
            "gate": d(g.gate("consent", record, record)), "text": d(g.text(record, "x")),
            "sender": "backend" if g.sender(record, backend) is backend else "channel",
            "outcome": d(g.outcome(record, "recovered")), "schedule": d(g.schedule(record, 0.0)),
            "tick": d(g.tick(None)), "resident": d(g.resident(None)), "start_route": d(g.start_route(record)),
            "surface": d(g.surface("status", record)),
            "claim_ledger": [d(each) for each in g.claim_ledger_checked(None, record, 0.0, ())],
            "partition": g.partition([]), "supervise": d(g.supervise(record)), "notice": "made" if told else None,
            "power": g.power(record), "delivery": d(g.delivery(record)), "unloaded": d(g.unloaded(record)),
            "admission": d(g.admission(record)), "eligibility": sorted(g.eligibility()), "sessions": sorted(g.sessions()),
            "wants": [g.wants(point) for point in Point], "start_held": g.start_held(),
            "supervise_held": g.supervise_held(), "failures": g.failures, "shown": edition.shown(g)}
    g.codex("codex.exe", "home")
    g.conversation_off("0a1b2c3d-0001-7000-8000-000000000001")
    return {"edition": str(N.edition), "badge": N.badge, "hooks": hooks, "points": [point.value for point in Point],
            "wants": [N.wants(point) for point in Point], "edition_changed": N.edition_changed("advanced"),
            "codex": N.codex("codex.exe", "home"), "conversation_off": N.conversation_off("x"), "guarded": held,
            "failures_after": g.failures}
class Answering(P.Plug):
    edition = "advanced"
    def __init__(self, word):
        self.word = word
    def _answer(self, *unused):
        if self.word is None:
            raise RuntimeError("a hook that fails")
        return self.word
    gate = outcome = schedule = claim_ledger = supervise = delivery = admission = _answer
def consult(point, word):
    g = P.Guarded(Answering(None if word is None else Alternative(word)))
    record = {}
    answer = {"gates": lambda: g.gate("consent", record, record), "outcome": lambda: g.outcome(record, "recovered"),
              "schedule": lambda: g.schedule(record, 0.0), "claim_ledger": lambda: g.claim_ledger(None, record, 0.0, ()),
              "supervision": lambda: g.supervise(record), "delivery": lambda: g.delivery(record),
              "admission": lambda: g.admission(record)}[point]()
    return [d(answer), g.failures]
class Powered(P.Plug):
    edition = "advanced"
    def __init__(self, answer):
        self.answer = answer
    def wants(self, point):
        return point == Point.POWER
    def power(self, facts):
        return self.answer
def power(answer):
    found = P.Guarded(Powered(answer)).power({})
    return found
def as_collection(value):
    return tuple(value[1]) if isinstance(value, list) and len(value) == 2 and value[0] == "tuple" and isinstance(value[1], list) else value
KEY = "%064x"
UUID = "0a1b2c3d-0001-7000-8000-00000000000%d"
cases = [["plug.tables"], ["plug.null"], ["policy.vocab"]]
for point in ["gates", "outcome", "schedule", "claim_ledger", "supervision", "delivery", "admission"]:
    for word in [None] + [word.value for word in Alternative]:
        cases.append(["plug.consult", point, word])
def record():
    key = KEY % rng.randrange(4)
    made = {"record_id": key, "thread_id": UUID % rng.randrange(3), "marker": "[codex-auto-resume:%s]" % key[:16],
            "state": rng.choice(["waiting", "in_flight", "x"]), "words": rng.choice(["Hello", None, "", "a" * 30000, "a" * 30001, 5]),
            "sent_at": rng.choice([None, 1700000000, 1700000000.5, 2 ** 70, True, -1, "x"])}
    for key2 in ("purpose", "ordinal", "queue_id", "withdraw", "pause_keeps"):
        if rng.random() < 0.3:
            made[key2] = rng.choice(["message", "continuation", "wrap_up", "x", None, 0, 3, -1, True, False,
                                     UUID % 9, "not-a-uuid"])
    roll = rng.random()
    if roll < 0.05:
        made["extra"] = 1
    elif roll < 0.1:
        del made["marker"]
    elif roll < 0.15:
        made["marker"] = "[codex-auto-resume:%s]" % ("f" * 16)
    elif roll < 0.18:
        made["record_id"] = made["record_id"].upper()
    return made
for _ in range(1500):
    cases.append(["plug.records_of", [record() for _ in range(rng.randrange(0, 11))]])
for answer in [None, "x", 5, {}, [5, "x", None]]:
    cases.append(["plug.records_of", answer])
for answer in [None, 0, 1, 2, 5, 8, 9, -3, True, False, 2.0, "2", [2], 2 ** 70]:
    cases.append(["plug.workers", answer])
for answer in [None, {}, {"a": 1}, {"a": float("nan")}, {"a": [1, {"b": "\ud800"}]}, {"a": 10 ** 30}, {"a": -0.0, "b": 1e16},
               {"a": {"b": {"c": [None, True, 1.5e-7]}}}, [1], "x", 5, {"k": float("inf")}, {"é": "é"}]:
    cases.append(["plug.fields", answer])
for answer in [None, "cli", ["cli"], ["tuple", ["cli"]], ["tuple", ["cli", "ide"]], ["tuple", ["cli", "cli"]], ["tuple", []],
               ["tuple", ["cli", "x"]], ["tuple", [["cli"]]], ["tuple", [5]], ["tuple", ["every_desktop"]], {"cli": 1}]:
    cases += [["plug.kinds_of", answer], ["plug.widening_of", answer]]
for answer in [None, {}, {"tasks": "met", "threads": []}, {"tasks": "met", "threads": [UUID % 1, UUID % 1, UUID % 2]},
               {"tasks": "running", "threads": [UUID % 1], "x": 1}, {"tasks": "x", "threads": []},
               {"tasks": 5, "threads": []}, {"tasks": "met", "threads": ["nope"]}, {"tasks": "met", "threads": [5]},
               {"tasks": "met", "threads": [UUID % 1] * 64}, {"tasks": "met", "threads": [UUID % 1] * 65},
               {"tasks": "not_met", "threads": "x"}, {"tasks": "unknown", "threads": [(UUID % 1).upper()]}, "met"]:
    cases.append(["plug.power", answer])
ops = {"plug.tables": tables, "plug.null": null, "plug.consult": consult,
       "plug.records_of": H.records_of, "plug.workers": H.workers, "plug.fields": lambda answer: H.fields(answer, "DEFER"),
       "plug.kinds_of": lambda answer: H.kinds_of(as_collection(answer)),
       "plug.widening_of": lambda answer: H.widening_of(as_collection(answer)), "plug.power": power,
       "policy.vocab": lambda: VOCAB}
VOCAB = json.loads(sys.stdin.read())
finish(cases, ops)
'''


def generator():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        return __import__("gen_policy")
    finally:
        sys.path.pop(0)


class PlugDiff(Family):
    def test_plug_null_and_checks(self):
        gen = generator()
        from rustdiff import gen_vocab
        vocab = gen_vocab.vocabulary(reference.TAG)
        mine = {name: vocab["modules"][name] for names in gen.TARGETS.values() for name in names}
        done = self.family(PLUG, label="plug", expect=1500, stdin=json.dumps(mine).encode("ascii"))
        null = done["results"][1]["ok"]
        self.assertTrue(all(value in ("DEFER", "BACKEND") for value in null["hooks"].values()), null["hooks"])
        count = lambda prefix: sum(1 for case in done["cases"] if case[0].startswith(prefix))
        RECORD.append("plug: PLUG_API %d and every table equal; NULL's %d hooks and Guarded(NULL)'s %d answers equal; "
                      "consult %d, records_of %d, workers/fields/kinds/widening/power %d cases equal; vocab of %d modules "
                      "equal to %s's" % (done["results"][0]["ok"]["PLUG_API"], len(null["hooks"]), len(null["guarded"]),
                                         count("plug.consult"), count("plug.records_of"),
                                         count("plug.workers") + count("plug.fields") + count("plug.kinds_of")
                                         + count("plug.widening_of") + count("plug.power"), len(mine), reference.TAG))

    def test_generated_files_are_the_tags(self):
        # The generator's own --check, which runs under the product's bundled Python (productpy.py) whose Unicode tables
        # text_tables.rs and unicode_gen.rs hold; generated in this process (3.13.15, say) they would differ.
        done = subprocess.run([sys.executable, "-X", "utf8", str(Path(__file__).resolve().parent / "gen_policy.py"),
                               "--check", "--ref", reference.TAG], cwd=str(ROOT), capture_output=True,
                              creationflags=reference.NO_WINDOW, timeout=900)
        self.assertEqual(done.returncode, 0, "gen_policy.py --check: %s%s" % (
            done.stdout.decode("utf-8", "replace"), done.stderr.decode("utf-8", "replace")[-2000:]))
