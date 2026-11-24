"""S1.1, car-machine's domain (`domain/*.py`) and the registry's format (`compat/model.py`), held to the tag.

Each test makes its cases inside the reference (`leaves.py`): the generated and hand-picked inputs, and what the
tag answers to each - the value or the class of the exception it raises. The same cases go to car-harness, and
every answer must be the same. Edges are chosen to reach the places Python and Rust differ: Unicode digits and
white space, `int(text, 16)`'s underscores and prefixes, a bool that is an int, an int too large for a float, a
list where a hashable is needed.
"""
from __future__ import annotations

from rustdiff.leaves import Leaves

RECORD: list[str] = []


class IdsDiff(Leaves):
    def test_ids(self):
        script = r'''
from codex_auto_resume.domain import ids, skips
rng = random.Random(3)
def uuid_text():
    h = "".join(rng.choice("0123456789abcdef") for _ in range(32))
    return "-".join((h[:8], h[8:12], h[12:16], h[16:20], h[20:]))
pool = list("0123456789abcdefABCDEF-{}_ gxXz+") + ["١", "Ａ", "²", "　", ":", "urn:", "uuid:"]
cases = []
fixed = ["0a1b2c3d-0001-7000-8000-000000000001", "{0a1b2c3d-0001-7000-8000-000000000001}", "urn:uuid:0a1b2c3d-0001-7000-8000-000000000001",
         "0A1B2C3D-0001-7000-8000-000000000001", "0a1b2c3d00017000800000000000000" + "1", "0x" + "a" * 30, " " + "a" * 31, "-" + "0" * 31,
         "+" + "1" * 31, "0" * 32, "-".join(["0" * 8, "0" * 4, "0" * 4, "0" * 4, "0" * 12]), "a_" * 16, "", "0a1b2c3d-0001-7000-8000-00000000000",
         "١" * 32, "{{" + "a" * 32 + "}}", "urn:" + "a" * 28]
values = fixed + [uuid_text() for _ in range(300)]
for _ in range(2500):
    base = list(rng.choice(values))
    for _ in range(rng.randrange(1, 4)):
        spot = rng.randrange(len(base) + 1)
        action = rng.randrange(3)
        if action == 0 and spot < len(base):
            base[spot] = rng.choice(pool)
        elif action == 1:
            base.insert(spot, rng.choice(pool))
        elif spot < len(base):
            del base[spot]
    values.append("".join(base))
others = [None, True, False, 0, 5, -3, 1.5, 12345678901234567890123456789012, [], ["a"], {}, {"a": 1}, 10 ** 31]
for value in values + others:
    cases.append(["ids.uuid_problem", value, False])
    cases.append(["ids.uuid_problem", value, True])
    cases.append(["ids.is_uuid", value])
cases += [["ids.uuid_pattern", False], ["ids.uuid_pattern", True]]
completed = [0, 1, 1.0, 1.5, 1700000000, 1700000000.123456, -0.0, 5e-324, 1e300, True, "12.5", " 3 ", "inf", "nan", "1e400", None, [1], 10 ** 400, 2 ** 70, "x", 2 ** 53 + 1, 0.1 + 0.2]
names = ["0a1b2c3d-0001-7000-8000-000000000001", "t", "é中", "\U0001f600", "", None, 7, 1.5, ["a", 1], {"k": "v"}, "q\"uote\\"]
for thread in names:
    for turn in names[:5]:
        for moment in completed[:9]:
            cases.append(["ids.interruption_id", thread, turn, moment, 0, ""])
for moment in completed:
    for ordinal in [0, 3, -1, 2 ** 40, 1.5, None, "1", True]:
        cases.append(["ids.interruption_id", "t", "u", moment, ordinal, ""])
        cases.append(["ids.interruption_id", "t", "u", moment, ordinal, "ab" * 32])
for home in ["", None, 0, False, "abc", "é", 5, [], [1], "a" * 64]:
    cases += [["ids.interruption_id", "t", "u", 1.5, 2, home], ["ids.stalled_id", "t", "u", home]]
for thread in names:
    for turn in names:
        cases.append(["ids.stalled_id", thread, turn, ""])
        cases.append(["ids.stalled_id", thread, turn, "home"])
hexes = ["a" * 64, "A" * 64, "a" * 63, "a" * 65, "0" * 64, "g" * 64, ("ab" * 32), "", None, 5, "١" * 64, " " + "a" * 63, "a" * 63 + "\n",
         "a" * 16, "A" * 16, "ab_" * 21 + "a", "a" * 128, "a" * 129, "-" * 5, "__", "a-b_c", "é"]
for value in hexes:
    cases += [["ids.is_digest", value], ["ids.is_interruption_id", value, False], ["ids.is_interruption_id", value, True],
              ["ids.is_power_nonce", value], ["ids.is_client_id", value]]
    cases += [["ids.is_marker", value], ["ids.is_delivery_proof", value]]
for key in ["a" * 64, "0123456789abcdef" * 4, "abc", "", "A" * 64, "x" * 16, "é" * 3, "short", "f" * 63]:
    cases += [["ids.marker", key], ["ids.short_marker", key], ["ids.record_markers", key], ["ids.continuation_client_id", key],
              ["ids.is_marker", "[codex-auto-resume:" + key + "]"], ["ids.is_delivery_proof", "[codex-auto-resume:" + key[:16] + "]"]]
for body in ["a" * 64, "a" * 16, "a" * 17, "", "A" * 16, "g" * 16, "a" * 16 + "]"]:
    for tail in ["]", "", "] ", "]]"]:
        cases.append(["ids.is_marker", "[codex-auto-resume:" + body + tail])
for text in ["  " + "A" * 64 + "\n", "a" * 64, "　" + "b" * 64, "a" * 63, "G" * 64, "", " ", "K" * 64, "İ" * 3]:
    cases.append(["ids.read_interruption_id", text])
for value in [None, "vscode", "Sub-Agent", "SubAgent", "thread_spawn", "a b", "x" * 32, "x" * 33, "", "a\n", "abé", 12, 1.5, True, ["subagent"], ["a", {"k": "Subagent"}], {"SUBAGENT": 1}, [1], "cli", "exec.v2-x", "é"]:
    cases.append(["skips.kind", value])
ops = {"ids.uuid_problem": lambda v, t: ids.uuid_problem(v, as_text=t), "ids.is_uuid": ids.is_uuid,
       "ids.uuid_pattern": lambda any_case: ids.uuid_pattern(any_case=any_case),
       "ids.interruption_id": ids.interruption_id, "ids.stalled_id": ids.stalled_id, "ids.is_digest": ids.is_digest,
       "ids.is_interruption_id": lambda v, s: ids.is_interruption_id(v, as_stored=s), "ids.is_power_nonce": ids.is_power_nonce,
       "ids.read_interruption_id": ids.read_interruption_id, "ids.marker": ids.marker, "ids.short_marker": ids.short_marker,
       "ids.record_markers": ids.record_markers, "ids.is_marker": ids.is_marker, "ids.is_client_id": ids.is_client_id,
       "ids.continuation_client_id": ids.continuation_client_id, "ids.is_delivery_proof": ids.is_delivery_proof, "skips.kind": skips.kind}
finish(cases, ops)
'''
        done = self.family(script, label="ids")
        RECORD.append("ids: %d cases of uuid_problem, interruption_id, stalled_id, markers, client ids and kind equal the "
                      "tag's, exceptions included" % len(done["cases"]))


class StatesDiff(Leaves):
    def test_states_and_usage(self):
        script = r'''
from codex_auto_resume import machine
from codex_auto_resume.domain import states, usage
rng = random.Random(4)
all_states = sorted(machine.STATES)
junk = [None, "", "nope", 5, True, 1.5, [], ["queued"], {}, "Queued"]
cases = []
for state in all_states + junk:
    for queue in [None, "q", 0, ""]:
        cases.append(["states.may_be_queued", state, queue])
    for other in all_states[::3] + junk[:4]:
        cases.append(["states.plain_move_allowed", state, other])
for old in all_states:
    for new in all_states:
        cases.append(["states.plain_move_allowed", old, new])
nums = [0, 1, -1, 946684800, 946684799, 4102444800, 4102444801, 253402300799, 253402300800, 1700000000, 1700000000.5, 1e18, 1e308,
        True, False, None, "1", [1], 2 ** 70, 10 ** 400, 1.5e9, 0.0, -0.0]
windows = [(0, 253402300799), (946684800, 4102444800), (1, 4102444800)]
for value in nums:
    for low, high in windows:
        for integer in (False, True):
            for finite in (False, True):
                cases.append(["states.epoch", value, low, high, integer, finite])
rows = [{"state": "submission_unknown", "queue_id": "q"}, {"state": "submission_unknown", "submitted_at": 100.0},
        {"state": "submission_unknown", "detected_at": 100}, {"state": "submission_unknown"},
        {"state": "submission_unknown", "submitted_at": 0, "detected_at": 90.5}, {"state": "queued"}, {},
        {"state": "submission_unknown", "submitted_at": "x"}, {"state": "submission_unknown", "submitted_at": True},
        {"state": "submission_unknown", "submitted_at": None, "detected_at": None}, []]
for row in rows:
    for now in [100.0, 150, 1000.5, 0, "1", None]:
        for window in [30, 30.0, 0, "x", None]:
            cases.append(["states.still_followed", row, now, window])
for category in ["usage_limit", "server_5xx", None, 5, []]:
    for reset in [None, 500, 500.5, 1500, 0, "5", 1000]:
        for now in [1000, 1000.0, 999, "x"]:
            cases.append(["states.waiting_state", {"category": category, "reset_at": reset}, now])
cases.append(["states.waiting_state", [], 1])
for started in [1700000000, 1700000000.0, 0, -5, True, None, "x", 2 ** 70, 1e30]:
    for booted in [1700000000, 1700000005, 1700000005.5, 1700000006, 1700000100, 0, None, 253402300800, 10 ** 400]:
        cases.append(["states.ended_by_boot", started, booted])

def window(**changes):
    value = {"bucket": "codex", "window": "primary", "used_percent": 12.5, "window_minutes": 300, "reset_at": 1700000000}
    value.update(changes)
    return value
variants = [window(), window(bucket="premium", window="secondary", window_minutes=None, reset_at=None), window(used_percent=0),
            window(used_percent=10000), window(used_percent=10000.5), window(used_percent=-0.1),
            window(used_percent=True), window(used_percent="5"), window(used_percent=None), window(used_percent=10 ** 400),
            window(bucket="x"), window(bucket=None), window(window="tertiary"), window(window_minutes=0), window(window_minutes=100800),
            window(window_minutes=100801), window(window_minutes=1.5), window(window_minutes=True), window(window_minutes=-1),
            window(reset_at=1.5), window(reset_at=1700000000.0), window(reset_at=True), window(reset_at=0), window(reset_at=1),
            window(reset_at=4102444801), window(reset_at=4102444800), {"bucket": "codex"}, dict(window(), extra=1), 5, None, [], "x",
            window(bucket=["codex"])]
for count in range(0, 11):
    reply = {"windows": [window(bucket=["codex", "premium", "legacy", "other"][index % 4], window=["primary", "secondary"][index // 4 % 2])
                         for index in range(count)]}
    cases += [["usage.windows_of", reply], ["usage.encode", reply["windows"]], ["usage.decode", json.dumps(reply["windows"])]]
for variant in variants:
    cases += [["usage.windows_of", {"windows": [variant]}], ["usage.encode", [variant]], ["usage.decode", json.dumps([variant])]]
    cases += [["usage.windows_of", {"windows": [window(), variant]}]]
cases += [["usage.decode", '[{"bucket": "codex", "window": "primary", "used_percent": 1e999, "window_minutes": 5, "reset_at": null}]'],
          ["usage.decode", '[{"bucket": "codex", "window": "primary", "used_percent": NaN, "window_minutes": 5, "reset_at": null}]'],
          ["usage.decode", '[{"bucket": "codex", "window": "primary", "used_percent": 1' + "0" * 400 + ', "window_minutes": 5, "reset_at": null}]'],
          ["usage.windows_of", None], ["usage.windows_of", {}], ["usage.windows_of", {"windows": "x"}], ["usage.windows_of", {"windows": {}}],
          ["usage.encode", "x"], ["usage.encode", None], ["usage.decode", None], ["usage.decode", ""], ["usage.decode", "not json"],
          ["usage.decode", "[" * 10], ["usage.decode", "x" * 3000], ["usage.decode", "[NaN]"], ["usage.decode", 5],
          ["usage.decode", json.dumps([window(reset_at=1700000000, used_percent=33.3)] * 8)],
          ["usage.decode", json.dumps([window(used_percent=1.0e-5, reset_at=None)] * 3)],
          ["usage.encode", [window(used_percent=12.0), window(used_percent=1e-7), window(used_percent=9999.999999)]]]
ops = {"states.may_be_queued": states.may_be_queued, "states.plain_move_allowed": states.plain_move_allowed,
       "states.epoch": lambda v, low, high, i, f: machine.epoch(v, low, high, integer=i, finite=f),
       "states.still_followed": states.still_followed, "states.waiting_state": states.waiting_state,
       "states.ended_by_boot": states.ended_by_boot,
       "usage.windows_of": usage.windows_of, "usage.encode": usage.encode, "usage.decode": usage.decode}
finish(cases, ops)
'''
        done = self.family(script, label="states")
        RECORD.append("states, usage: %d cases of may_be_queued, plain_move_allowed (all 27 x 27), epoch, still_followed, "
                      "waiting_state, ended_by_boot, windows_of, encode, decode equal the tag's" % len(done["cases"]))


class PublicDiff(Leaves):
    def test_public(self):
        script = r'''
from codex_auto_resume import machine
from codex_auto_resume.domain import public, vocabulary
all_states = sorted(machine.STATES)
errors = [None, "", "queue_process_not_started", "awaiting_delivery_receipt", "app_server_unmatched", "app_server_unmatched:named_engine",
          "app_server_unmatched:", "app_server_unmatchedx", "usage_unavailable", "x", 5, ["a"]] + sorted(public.REASONS)[:12]
cases = []
records = []
for state in all_states + [None, "bogus", 5, ["queued"]]:
    for error in errors:
        records.append({"state": state, "last_error": error})
    records.append({"state": state, "queue_id": "q", "last_error": None})
    records.append({"state": state, "hold": "ask", "last_error": "app_server_unmatched"})
    records.append({"state": state, "cancel_requested": 1, "next_retry_at": 100, "reset_at": 200.5, "not_before": 150})
    records.append({"state": state, "next_retry_at": 0, "reset_at": None, "not_before": 0})
    records.append({"state": state, "next_retry_at": "x", "reset_at": 2})
    records.append({"state": state, "next_retry_at": 5, "reset_at": 5.0, "not_before": True})
    records.append({"state": state, "not_before": 500, "objection_until": 400})
    records.append({"state": state, "not_before": 300, "objection_until": 400})
    records.append({"state": state, "not_before": 400, "objection_until": 400})
    records.append({"state": state, "not_before": 500, "objection_until": "x"})
records += [{}, [], None, 5, {"state": "waiting_retry"}]
watchers = [None, {}, {"running": True, "ticking": True}, {"running": True, "ticking": False}, {"running": False},
            {"engine_state": "incompatible", "running": True}, {"engine_state": "failed_here"},
            {"running": True, "ticking": True, "self_check": {"blocked": "recovery_blocked:locks_unread"}},
            {"running": True, "self_check": {"blocked": "nope"}}, {"running": True, "self_check": 5},
            {"running": True, "ticking": False, "self_check": {"blocked": "detection_blocked:engine_missing"}}, [], [1], 0]
for record in records:
    cases += [["public.public_code", record], ["public.eligible_at", record], ["public.public_reason", record]]
    for now in [None, 100, 175.5, 1000, "x"]:
        cases.append(["public.own_postponement", record, now])
    for enabled, thread in [(True, True), (False, True), (True, False), (0, "")]:
        for watcher in watchers[:5]:
            cases.append(["public.describe", record, enabled, thread, watcher])
for record in records[::5]:
    for watcher in watchers:
        cases.append(["public.describe", record, True, True, watcher])
        cases.append(["public.overlays", record, True, True, watcher])
for watcher in watchers:
    cases.append(["public.blocked", watcher])
words = (sorted(public.EVENT_CODES)[:40] + sorted(public.REASONS)[:40] + sorted(public.ACTORS) + sorted(public.TURN_STATUSES)
         + [None, "", "other", "Engine", 5, True, ["x"]])
for value in words:
    cases += [["public.event_code", value], ["public.reason_code", value], ["public.actor_code", value], ["public.turn_status", value]]
for tier in list(vocabulary.ImportanceTier) + [None, "x", 5, ["ask_first"]]:
    cases.append(["public.hold_for_tier", tier])
for text in ["0.171.0", "codex-cli 0.171.0-alpha.13", "codex-cli", "", "abc", "1", "-1", "a" * 32, "a1" + "b" * 30, "1" * 33, "x 1.2 y 3.4",
             "(1.2)", "v1.2", "1.2.3\n", "0.1 " + "z" * 300, "z" * 255 + " 1.0", "z" * 256 + " 1.0", "١.2", "1.2é", "ab-cd",
             "1..2", None, 5, ["1"]]:
    cases.append(["public.version_word", text])
for started in [0, 1.5, 1700000000.25, True, "12.5", -3]:
    for word in [None, "recovery_blocked:held_elsewhere", "nope", 5]:
        cases.append(["public.self_check_note", started, word, None, "1.2.3", None])
cases.append(["public.self_check_note", 1.0, None, {"code": "x", "count": 2}, None, "0.6.25"])
cases.append(["public.self_check_note", None, None, None, None, None])
ops = {"public.public_code": public.public_code, "public.eligible_at": public.eligible_at, "public.public_reason": public.public_reason,
       "public.own_postponement": lambda record, now: public.own_postponement(record, now=now),
       "public.describe": lambda record, enabled, thread, watcher: public.describe(record, enabled=enabled, thread_enabled=thread, watcher=watcher),
       "public.overlays": lambda record, enabled, thread, watcher: public.overlays(record, enabled=enabled, thread_enabled=thread, watcher=watcher),
       "public.blocked": public.blocked, "public.event_code": public.event_code, "public.reason_code": public.reason_code,
       "public.actor_code": public.actor_code, "public.turn_status": public.turn_status, "public.hold_for_tier": public.hold_for_tier,
       "public.version_word": public.version_word, "public.self_check_note": public.self_check_note}
finish(cases, ops)
'''
        done = self.family(script, label="public")
        RECORD.append("public: %d cases of public_code, eligible_at, own_postponement, public_reason, describe and the code "
                      "readers equal the tag's" % len(done["cases"]))


class CompatDiff(Leaves):
    def test_registry_format(self):
        script = r'''
import copy
from codex_auto_resume.compat import model
def doc(**changes):
    value = {"format": "codex-auto-resume-compat/1", "sequence": 14, "published_at": "2026-11-01T08:30:00Z", "expires_at": "2027-02-01T00:00:00Z",
             "min_product": "0.6.20",
             "engines": [{"version": "codex-cli 0.171.0", "capabilities": {
                 "engine_present": {"state": "VERIFIED", "evidence": ["docs/evidence/codex/0.171.json"], "verified_at": "2026-10-30", "reason": "registry_verified"},
                 "queue_withdraw": {"state": "INCOMPATIBLE", "reason": "no_such_reason"},
                 "no_such_capability": {"state": "VERIFIED", "evidence": []},
                 "usage_probe": {"state": "CHECKED", "evidence": ["docs/evidence/x.json"]}}},
                {"version": "codex-cli 0.172.0-alpha.3.2", "capabilities": {}}],
             "advisories": [{"id": "CAR-2026-0001", "state": "INCOMPATIBLE", "match": {"version_gte": "0.170.0", "version_lt": "0.171.0-alpha.2"},
                             "capabilities": ["engine_present", "zzz"], "reason": "unspecified"}]}
    value.update(changes)
    return value
documents = [doc()]
def mutate(path, replacement):
    value = copy.deepcopy(doc())
    node = value
    for step in path[:-1]:
        node = node[step]
    if replacement is KeyError:
        node.pop(path[-1], None)
    else:
        node[path[-1]] = replacement
    return value
for key in ["format", "sequence", "published_at", "expires_at", "min_product", "engines", "advisories", "requires_signature", "signature", "key_id"]:
    for replacement in [KeyError, None, 5, "x", [], {}, True, "codex-auto-resume-compat/2", "codex-auto-resume-compat/1x", 2 ** 40, -1, 1.5,
                        "a" * 9000, "2026-02-30T00:00:00Z", "2026-11-01T24:00:00Z", "2026-11-01T08:30:61Z", "2026-11-01T08:30:62Z",
                        "1999-12-31T23:59:59Z", "2100-01-01T00:00:00Z", "2100-01-01T00:00:01Z", "2026-11-01T08:30:00", "2026-11-01 08:30:00Z",
                        "٢٠٢٦-11-01T08:30:00Z", "2024-02-29T00:00:00Z", "2023-02-29T00:00:00Z", "0.6.20", "0.6", " 0.6.20 ",
                        "0.6.20.1", "0000001.0.0", "0.6.٢٠", False, "2026-11-01T08:30:00Z "]:
        documents.append(mutate([key], replacement))
for path, replacements in [
        (["engines", 0, "version"], [KeyError, None, "codex-cli 0.171.0-alpha.3", "codex-cli 0.172.0-alpha.3.2", "codex-cli 1.2", "x" * 90,
                                      "codex-cli 0.171.0 ", " codex-cli 0.171.0"]),
        (["engines", 0, "capabilities"], [None, [], "x"]),
        (["engines", 0, "capabilities", "engine_present"], [None, [], {}, {"state": "VERIFIED"}, {"state": "CHECKED", "evidence": []},
                                                            {"state": "COMPATIBLE"}, {"state": "UNKNOWN", "evidence": ["x"]},
                                                            {"state": "VERIFIED", "evidence": ["docs/evidence/community/a.json"]}]),
        (["engines", 0, "capabilities", "engine_present", "evidence"],
         [None, "x", [5], ["docs/evidence/a/../b.json"], ["docs/evidence/Community/b.json"], ["docs/evidence/communityx/b.json"],
          ["docs/evidence/community.json"], ["docs/evidence/a./b.json"], ["docs/evidence/a.json.json"], ["docs/evidence/é.json"],
          ["docs/evidence/a b.json"], ["docs/evidence/.json"], ["docs/evidence/a/.json"], ["docs/evidence/a//b.json"],
          ["docs/evidence/-a_b.json"], ["docs/evidence/COMMUNITY"], ["docs/evidence/community/"], ["docs/evidenceX/a.json"], ["a.json"],
          ["docs/evidence/a.json"] * 9, ["docs/evidence/a.json"] * 8]),
        (["engines", 0, "capabilities", "engine_present", "verified_at"], [None, 5, "2026-10-30", "2026-1-30", "2026-10-30x", "٢026-10-30"]),
        (["engines", 0, "capabilities", "engine_present", "reason"], [None, 5, "registry_verified", "nope", ["x"]]),
        (["advisories", 0, "id"], [KeyError, None, "CAR-2026-0001", "CAR-2026-001", "CAR-26-0001", "car-2026-0001", "CAR-2026-0001\n", "CAR-٢026-0001"]),
        (["advisories", 0, "state"], [KeyError, "VERIFIED", "CHECKED", "incompatible", None]),
        (["advisories", 0, "match"], [None, {}, [], {"x": 1}, {"version_gte": "0.1.0"}, {"version_lt": "0.1.0"},
                                      {"version_gte": "0.2.0", "version_lt": "0.1.0"}, {"version_gte": "0.2.0", "version_lt": "0.2.0"},
                                      {"version_gte": "0.2.0-alpha.1", "version_lt": "0.2.0"}, {"version_gte": 5}, {"version_gte": "x"},
                                      {"version_gte": " 0.1.0"}, {"version_gte": "0.1.0-alpha.1.2", "version_lt": "0.1.0-alpha.1.3"},
                                      {"version_gte": "0.1.0-alpha.1234567890"}]),
        (["advisories", 0, "capabilities"], [None, [], ["a"], [5], ["engine_present", 5], ["engine_present", "engine_present"], "engine_present", ["zzz"]]),
        (["advisories", 0, "reason"], [None, 5, "unspecified", "local_check_failed_here", "zz"])]:
    for replacement in replacements:
        documents.append(mutate(path, replacement))
documents.append(doc(engines=[doc()["engines"][0]] * 2))
documents.append(doc(advisories=[doc()["advisories"][0]] * 2))
documents.append(doc(engines=[{"version": "codex-cli 0.%d.0" % index, "capabilities": {}} for index in range(501)]))
documents.append(doc(engines=[{"version": "codex-cli 0.%d.0" % index, "capabilities": {}} for index in range(500)]))
documents.append(doc(advisories=[{"id": "CAR-2026-%04d" % index, "state": "INCOMPATIBLE", "match": {"version_gte": "0.1.0"},
                                  "capabilities": ["engine_present"]} for index in range(201)]))
documents.append(doc(engines=[5]))
documents.append(doc(advisories=[5]))
documents.append(doc(requires_signature=True))
documents.append(doc(requires_signature=False, signature="s", key_id="k"))
documents.append(doc(requires_signature=1))
documents.append(doc(engines=[{"version": "codex-cli 0.171.0", "capabilities": {"engine_present": 5}}]))
documents.append(doc(engines=[{"version": "codex-cli 0.171.0", "capabilities": {"nope": 5}}]))
documents.append(doc(engines=[{"version": "codex-cli 0.171.0"}]))
documents.append(doc(engines=[{"version": "codex-cli ٠.١٧١.٠"}]))
cases = []
for value in documents:
    cases.append(["compat.parse_document", json.dumps(value).encode("utf-8").hex(), 262144])
cases.append(["compat.parse_document", json.dumps(doc(), indent=2).encode("utf-8-sig").hex(), 262144])
cases.append(["compat.parse_document", json.dumps(doc()).encode("utf-8").hex(), 100])
cases.append(["compat.parse_document", (b"\xef\xbb\xbf" * 2 + json.dumps(doc()).encode()).hex(), 262144])
cases.append(["compat.parse_document", b"\xff\xfe{}".hex(), 262144])
cases.append(["compat.parse_document", "[]".encode().hex(), 262144])
cases.append(["compat.parse_document", "{}".encode().hex(), 262144])
raw = ['{"a": 1, "a": 2}', '{"a": {"b": 1, "b": 2}}', '[{"a":1,"a":2}, NaN]', '[NaN, {"a":1,"a":2}]', '{"a":1,"a":2} x', '{"a":1,"a":2',
       '[1e999]', '[-1e999]', '[1e-999]', '[1E5, 0.0, -0, -0.0, 1.0e+2, 123456789012345678901234567890]', '[' * 100 + ']' * 100,
       '[' * 5000, '{"a":' * 3500 + '1' + '}' * 3500, '[[[[', '', ' ', '  []  ', '\t\n\r []', '\x0b[]', '[1,]', '[,1]',
       '{"a":1,}', '{"a"}', '{a:1}', "{'a':1}", '{"a":1 "b":2}', '[1 2]', '"abc', '"\\u12"', '"\\x41"', '"\\ud83d\\ude00"', '"a\nb"',
       '"tab\there"', '"\\/\\b\\f\\n\\r\\t\\\\\\""', 'null', 'true', 'false', 'nul', 'True', 'NaN', 'Infinity', '-Infinity', '-Inf', '[Infinity]',
       '[-Infinity]', '-', '-x', '01', '1.', '.5', '1.5.5', '1e', '1e+', '0e0', '9' * 4300, '9' * 4301, '-' + '9' * 4300, '-' + '9' * 4301,
       '[1]x', '[1] [2]', '{"k": [1, {"z": null}]}', '"é中\U0001f600"', '"\\u00e9"', '[true, false, null]', '{"a": 1, "b": 2, "a": 3}',
       '{"\\u0061": 1, "a": 2}', '[1.7976931348623157e308, 1.8e308]']
for text in raw:
    cases.append(["compat.decode", text.encode("utf-8").hex(), 262144])
for depth in (900, 1200, 2000, 2900):
    cases.append(["compat.decode_probe", ("[" * depth + "]" * depth).encode().hex()])
    cases.append(["compat.decode_probe", ('{"a":' * depth + "1" + "}" * depth).encode().hex()])
for depth in (4000, 20000):
    cases.append(["compat.decode_probe", ("[" * depth + "]" * depth).encode().hex()])
cases.append(["compat.decode", "[]".encode().hex(), 1])
cases.append(["compat.decode", b"\xc3\x28".hex(), 262144])
cases.append(["compat.decode", b"[1]\xef\xbb\xbf".hex(), 262144])
for text in ["codex-cli 0.171.0", "codex-cli 0.171.0-alpha.13", "codex-cli 0.171.0-alpha.13.2", " codex-cli 1.2.3 ", "codex-cli  1.2.3",
             "codex-cli 1.2.3-alpha", "codex-cli 1.2.3-alpha.", "codex-cli 1.2.3-beta.1", "codex-cli 123456.123456.123456",
             "codex-cli 1234567.1.1", "codex-cli 1.2.3-alpha.1234567890", "codex-cli 1.2.3-alpha.123456789", "codex-cli 1.2.3-alpha.1.2.3",
             "codex-cli ١.٢.٣", "CODEX-CLI 1.2.3", "codex-cli 1.2.3\n", "codex-cli 01.2.3", "1.2.3", None, 5, ["x"]]:
    cases.append(["compat.parse_version", text])
for text in ["0.6.26", " 0.6.26 ", "0.6.26-alpha.1", "0.6", "1234567.0.0", "٠.٦.٢٦", "a.b.c", "0.6.26\n", None, 7]:
    cases.append(["compat.product_key", text])
for text in ["codex-cli 1.2.3", "a", "1.2", "x" * 80, "x" * 81, " a", "a b ._+()-", "a\n", "é", "", "(a)", "a" + "(" * 79, None, 5]:
    cases.append(["compat.safe_version", text])
def refuse(call):
    def wrapped(*args):
        try:
            return call(*args)
        except model.DocumentError as error:
            return {"refused": error.code}
    return wrapped
def normal(document):
    document = dict(document)
    document["advisories"] = [dict(each, capabilities=sorted(each["capabilities"])) for each in document["advisories"]]
    return document
ops = {"compat.parse_document": refuse(lambda raw, limit: normal(model.parse_document(bytes.fromhex(raw), limit))),
       "compat.decode": refuse(lambda raw, limit: model.decode(bytes.fromhex(raw), limit)),
       "compat.decode_probe": refuse(lambda raw: ["parsed", model.decode(bytes.fromhex(raw)) is not None]),
       "compat.parse_version": model.parse_version, "compat.product_key": model.product_key, "compat.safe_version": model.safe_version}
finish(cases, ops)
'''
        done = self.family(script, label="compat")
        refused = sorted({result["ok"]["refused"] for result in done["results"]
                          if isinstance(result.get("ok"), dict) and len(result["ok"]) == 1 and "refused" in result["ok"]})
        self.assertGreaterEqual(len(refused), 8, refused)
        RECORD.append("compat.model: %d cases of parse_document, decode, parse_version, product_key, safe_version equal the tag's; "
                      "%d different refusals reached (%s)" % (len(done["cases"]), len(refused), ", ".join(refused)))
