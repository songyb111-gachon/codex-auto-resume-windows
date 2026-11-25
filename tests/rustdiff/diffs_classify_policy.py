"""S2.1, car-policy's policy half: the gates, guards, ladder, quiet hours, projects, needs-you, power, the permits,
and the seam of `ownvalues.py` S2.2 will replace - every function held to the reference tag's own answers over
generated settings, records and times.

Quiet hours and a postponement read the local clock; both sides are handed the same test zone (`ZONE`, below, and
`car-harness`'s `Zone`): a fixed offset, and summer time between two days of the UTC year, so a window is walked
across midnight and across both changes of the clock as the Python's own tests walk it.
"""
from __future__ import annotations

from rustdiff.leaves import Leaves

RECORD: list[str] = []

ZONE = r'''
import math, time

def civil(days):
    z = days + 719468
    era = z // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    y = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    d = doy - (153 * mp + 2) // 5 + 1
    m = mp + 3 if mp < 10 else mp - 9
    return (y + (1 if m <= 2 else 0), m, d)

def days_from(y, m, d):
    y -= 1 if m <= 2 else 0
    era = y // 400
    yoe = y - era * 400
    doy = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468

def yday(y, m, d):
    return days_from(y, m, d) - days_from(y, 1, 1) + 1

class Zone:
    def __init__(self, spec):
        self.offset, self.dst, self.start, self.end = (list(spec) + [0, 0, 0, 0])[:4]
    def in_dst(self, t):
        if not self.dst:
            return False
        y, m, d = civil(t // 86400)
        return self.start <= yday(y, m, d) < self.end
    def localtime(self, t):
        if not isinstance(t, (int, float)):
            raise TypeError("a number")
        t = float(t)
        if math.isnan(t):
            raise ValueError("nan")
        if math.isinf(t):
            raise OverflowError("inf")
        if t < 0 or t > 32503680000:
            raise OSError(22, "out of range")
        t = math.floor(t)
        local = t + self.offset + (self.dst if self.in_dst(t) else 0)
        days, rest = divmod(local, 86400)
        y, m, d = civil(days)
        return time.struct_time((y, m, d, rest // 3600, rest % 3600 // 60, rest % 60, (days + 3) % 7, yday(y, m, d), 0))
    def mktime(self, parts):
        y, m, d, hh, mm, ss = parts[:6]
        y += (m - 1) // 12
        m = (m - 1) % 12 + 1
        local = (days_from(y, m, 1) + d - 1) * 86400 + hh * 3600 + mm * 60 + ss
        standard = local - self.offset
        summer = standard - self.dst
        t = summer if (self.dst and self.in_dst(summer)) else standard
        if t < 0 or t > 32503680000:
            raise OverflowError("mktime argument out of range")
        return float(t)

ZONES = [[0, 0, 0, 0], [32400, 0, 0, 0], [-18000, 3600, 70, 308], [3600, 3600, 86, 301], [19800, 0, 0, 0],
         [-36000, 1800, 1, 60]]
'''

GATES = r'''
from codex_auto_resume.domain import gates as g
rng = random.Random(11)
T = lambda value: tuple(value) if isinstance(value, list) else value

def vec(value):
    return {name: tuple(pair) for name, pair in value.items()} if isinstance(value, dict) else value

ops = {
    "gates.gate": g.gate,
    "gates.consent": lambda a, b, c, d, e: g.gate_consent(a, b, c, observe_only=d, hold=e),
    "gates.schedule": lambda r, now, q, early, forced: g.gate_schedule(r, now, quiet_until=q, early=early, forced=forced),
    "gates.usage_read_stopped": lambda a, b, c, d: g.usage_read_stopped(enabled=a, conversation_on=b, observing=c, quiet=d),
    "gates.submission_safe": g.gate_submission_safe,
    "gates.own_budget_only": g.own_budget_only,
    "gates.was_resent": g.was_resent,
    "gates.resend_candidate": lambda r, now, w: g.resend_candidate(r, now, tuple(w)),
    "gates.chain_span": lambda r: float(g.chain_span(r)),
    "gates.waited_aside": lambda v: g.waited_aside(vec(v)),
    "gates.counted_from": g.counted_from,
    "gates.over_ceiling": g.over_ceiling,
    "gates.inherited": g.inherited,
    "gates.birth_stop": lambda p, f, l, u, now, legacy: g.birth_stop(p, f, l, u, now=now, legacy_carry=legacy),
    "gates.budgets": g.gate_budgets,
    "gates.first_refusal": lambda v: g.first_refusal(vec(v)),
    "gates.would_send_at": g.would_send_at,
    "gates.encode": lambda v: g.encode_gates(vec(v)),
    "gates.decode": g.decode_gates,
}
reasons = sorted(g.GATE_REASONS) + ["other", "bogus", ""]
results = ["PASS", "WAIT", "BLOCK", "UNKNOWN", "MAYBE"]
def random_vector(full=True):
    names = list(g.GATES) if full else rng.sample(list(g.GATES), rng.randrange(len(g.GATES)))
    return {name: [rng.choice(results[:4] if rng.random() < 0.9 else results), rng.choice(reasons)] for name in names}
cases = []
for result in results:
    for reason in reasons:
        cases.append(["gates.gate", result, reason])
for bits in range(32):
    flags = [bool(bits & (1 << n)) for n in range(4)]
    for hold in [None, "ask", "anything"]:
        cases.append(["gates.consent", *flags, hold])
    cases.append(["gates.usage_read_stopped", *flags])
times = [None, 0, 50, 99, 100, 100.0, 101, 150.5, 200]
for _ in range(3000):
    record = {name: rng.choice(times) for name in ("next_retry_at", "reset_at", "not_before")}
    cases.append(["gates.schedule", record, 100, rng.choice([None, 50, 100, 150]), rng.random() < 0.3, rng.random() < 0.3])
states = ["waiting_reset", "waiting_backoff", "waiting_for_usage", "submitting", "queued", "submission_unknown", "recovered"]
keys = ["a" * 64, "0123456789abcdef" * 4]
from codex_auto_resume.domain.ids import continuation_client_id
for _ in range(3000):
    key = rng.choice(keys)
    record = {"state": rng.choice(states), "submitted_at": rng.choice([None, 10, 50, 95.5, 1000]),
              "last_error": rng.choice(sorted(g.RESENDABLE) + ["other", None]), "queue_id": rng.choice([None, None, "q1"]),
              "first_queued_at": rng.choice([None, None, 5]), "interruption_id": key,
              "recovery_client_id": rng.choice([None, continuation_client_id(key), "foreign"]),
              "cancel_requested": rng.choice([0, 1, False, None]), "hold": rng.choice([None, None, "ask"]),
              "gate_eval": rng.choice([None, g.encode_gates({n: tuple(p) for n, p in random_vector().items()}),
                                       g.encode_gates({"submission_safe": ("PASS", "resend")}),
                                       g.encode_gates({"thread_available": ("PASS", "plugged")}), "{bad", "[]"]),
              "recovery_attempts": rng.choice([0, 1, 4, 5, None])}
    cases.append(["gates.submission_safe", record, rng.choice([0, 1, 3])])
    cases.append(["gates.own_budget_only", record, rng.choice([None, 0, 2, 5])])
    cases.append(["gates.was_resent", record])
    cases.append(["gates.resend_candidate", record, 100, rng.choice([[0, 60], [5, 10], [50, 100], [90, 90]])])
    cases.append(["gates.would_send_at", dict(record, gate_eval_at=rng.choice([None, 42, 42.5]))])
for _ in range(3000):
    vector = random_vector(full=rng.random() < 0.7)
    cases += [["gates.waited_aside", vector], ["gates.first_refusal", vector], ["gates.encode", vector]]
    if rng.random() < 0.2:
        vector["consent"] = ["BLOCK", "observe_only"]
        for name in g.GATES:
            if name != "consent":
                vector[name] = ["PASS", "ok"]
        cases.append(["gates.would_send_at", {"state": "waiting_reset", "gate_eval": g.encode_gates(vec(vector)), "gate_eval_at": 7}])
        cases.append(["gates.would_send_at", {"state": "queued", "gate_eval": g.encode_gates(vec(vector)), "gate_eval_at": 7}])
for _ in range(2000):
    row = {"chain_first_detected_at": rng.choice([0, 10, 10.5, 100]), "gate_eval_at": rng.choice([None, 50, 50.5, 200]),
           "gate_eval": g.encode_gates(vec(random_vector())), "detected_at": rng.choice([0, 5, 30, 4000.5]),
           "chain_continuations": rng.choice([0, 1, 3, 5]), "recovery_attempts": rng.choice([0, 2, 5]),
           "no_progress_count": rng.choice([0, 1, 3])}
    # The clock as every caller has it: time.time(), a float (the Rust API takes an f64).
    now = rng.choice([40.0, 50.0, 100.0, 150.25])
    limits = {"max_no_progress": rng.choice([1, 3, 5]), "max_chain_continuations": rng.choice([1, 3, 5, 20]),
              "max_recovery_attempts": rng.choice([1, 3, 5]), "max_chain_seconds": rng.choice([None, 10, 3600])}
    usage = rng.random() < 0.4
    cases += [["gates.counted_from", row, now], ["gates.chain_span", row], ["gates.over_ceiling", row, limits, usage],
              ["gates.budgets", row, limits, usage]]
    parent = rng.choice([None, dict(row, chain_origin_id="o", usage_unavailable_seconds=rng.choice([0, 12.5]),
                                    budget_resets=rng.choice([0, 1]), interruption_id="p",
                                    cancel_requested=rng.choice([0, 1]), user_joined=rng.choice([0, 0, 1]),
                                    after_user_work=rng.choice([0, 0, 1]),
                                    state=rng.choice(["recovered", "handed_over", "stopped_by_user", "waiting_reset"]))])
    progress = rng.choice([True, False, None, 1])
    legacy = rng.choice([None, 0, 2, -1, True, 2.5, "3"])
    cases.append(["gates.inherited", parent, progress, legacy])
    cases.append(["gates.birth_stop", parent, progress, rng.choice([None, limits]), usage, now, legacy])
texts = [None, 5, "", "{}", "[]", "null", "{bad", '{"consent": ["PASS", "ok"]}', '{"consent": ["PASS", "weird"]}',
         '{"consent": ["MAYBE", "ok"]}', '{"consent": ["PASS"]}', '{"consent": "PASS"}', '{"consent": [1, "ok"]}',
         '{"consent": ["PASS", 1]}', '{"consent": ["PASS", "ok"], "x": NaN}', '{"usage": ["WAIT", "\\ud800"]}',
         "x" * 4001, '{"consent": ["PASS", "ok"]}' + " " * 3990]
for _ in range(500):
    texts.append(g.encode_gates(vec(random_vector(full=rng.random() < 0.5))))
for text in texts:
    cases.append(["gates.decode", text])
finish(cases, ops)
'''

GUARDS_LADDER = r'''
from codex_auto_resume import guards, ladder, needsyou, power, projects, ownvalues
from codex_auto_resume.compat.permits import permits
rng = random.Random(7)
OWNS = [["duration", 5, 7200, ["s", "m", "h"], ""], ["duration", 900, 21600, ["m", "h"], ""], ["clock", 0, 0, [], ""],
        ["days", 0, 0, [], ""], ["count", 10000, 10000000, ["k", "m"], "above_"], ["count", 1, 64, [], ""],
        ["count", 256, 65536, ["", "k"], "mb"]]
def own(spec):
    return ownvalues.Own(spec[0], spec[1], spec[2], tuple(spec[3]), spec[4])
def measured(value):
    return sorted(value) if isinstance(value, frozenset) else value
ops = {
    "guards.task_mode": guards.task_mode, "guards.watches_task": guards.watches_task, "guards.context_mode": guards.context_mode,
    "guards.counts_tokens": guards.counts_tokens, "guards.context_limit": guards.context_limit,
    "guards.fingerprint": guards.fingerprint, "guards.is_print": guards.is_print, "guards.changed": guards.changed,
    "guards.tokens": guards.tokens, "guards.over": guards.over,
    "ladder.choices_for": ladder.choices_for, "ladder.timing": ladder.timing, "ladder.custom_steps": ladder.custom_steps,
    "ladder.ladder": ladder.ladder, "ladder.walks": ladder.walks, "ladder.wait_before": ladder.wait_before,
    "ladder.preview": ladder.preview, "ladder.previews": ladder.previews, "ladder.jittered": ladder.jittered,
    "ladder.ceiling": ladder.ceiling,
    "ladder.constants": lambda: [ladder.SPACING, ladder.PER_DAY, ladder.RATE_LIMIT_FIRST, *ladder.ADMITTED_WAITS,
                                 ladder.ADMISSION_MAX_AGE, ladder.ADMITTED_MAX_SECONDS, *ladder.CAPACITY_WAITS,
                                 ladder.CAPACITY_SPACING, ladder.CAPACITY_PER_DAY, ladder.CAPACITY_MAX_SECONDS,
                                 ladder.RESET_PER_DAY, ladder.EARLY_SPACING, ladder.EARLY_WINDOW, needsyou.WINDOW_SECONDS,
                                 needsyou.KEEP_SECONDS, quiet.MAX_POSTPONE_SECONDS, guards.MAX_TOKENS,
                                 failures.MAX_RETRY_AFTER, continuation.MAX_CUSTOM_LENGTH, continuation.PROMPT_SEND_LIMIT,
                                 continuation.COMMAND_LINE_UNITS, continuation.SEND_ARGV_ROOM, projects.MAX_KEYS,
                                 continuation.MAX_CONVERSATIONS, ladder.JITTER_SHARE, power.MIN_SLEEP_SECONDS],
    "needsyou.told": needsyou.told, "needsyou.kinds": needsyou.kinds, "needsyou.stall_seconds": needsyou.stall_seconds,
    "needsyou.minutes": needsyou.minutes,
    "needsyou.tables": lambda: [[[kind, needsyou.KIND_FIELDS[kind], needsyou.NEXT_STEPS[kind]] for kind in needsyou.KINDS],
                                needsyou.NEXT_STEPS[needsyou.STALLED]],
    "power.keep_awake": power.keep_awake, "power.awake_cap": power.awake_cap, "power.sleep_threshold": power.sleep_threshold,
    "power.waits_for_network": power.waits_for_network, "power.listens": power.listens, "power.asleep": power.asleep,
    "power.fell_due": power.fell_due, "power.waiting": power.waiting, "power.wants_awake": power.wants_awake,
    "projects.normal_folder": projects.normal_folder, "projects.key_for": projects.key_for, "projects.is_key": projects.is_key,
    "projects.parse_keys": projects.parse_keys, "projects.format_keys": projects.format_keys,
    "projects.coerce_keys": projects.coerce_keys, "projects.asks": projects.asks, "projects.allows": projects.allows,
    "projects.hold_for": projects.hold_for, "projects.rule": projects.rule,
    "permits.permits": lambda v, c, t, o, e, a: list(permits(v, c, tier=t, opt_in=o, engine_version=e, acknowledged_version=a)),
    "own.amount": lambda spec, value: measured(ownvalues.amount(own(spec), value)),
    "own.canonical": lambda spec, value, choices: ownvalues.canonical(own(spec), value, tuple(choices)),
    "own.plug": lambda: [sorted(TAKE_UP), {str(k): v for k, v in PACED_AS.items()}],
}
from codex_auto_resume import failures, continuation, quiet
from codex_auto_resume.domain.plug import TAKE_UP, PACED_AS
cases = [["ladder.constants"], ["ladder.previews"], ["needsyou.tables"], ["own.plug"]]
# ownvalues: every kind, spellings a person or a surface may send
words = ["", "s5", "s4", "s7200", "s7201", "m1", "m0", "m01", "m15", "m45", "m60", "m90", "h1", "h2", "h6", "h7", "s0005",
         "m1234567", "m12345678", "x5", "5m", "m 5", "m5 ", "m5\n", "M5", "s٣", "m１５", "00:00", "7:05", "07:05", "23:59",
         "24:00", "12:60", "1:5", "123:00", "12:345", "mon", "mon,wed,fri", "fri,mon", "mon,mon", "weekdays", "weekends",
         "every_day", "sun,sat", "mon,,tue", "Mon", "above_10k", "above_250k", "above_1m", "above_10000", "above_1000k",
         "above_10m", "above_11m", "above_9k", "above_0k", "above_010k", "above_k", "above_1km", "above_1x", "above_",
         "250k", "1", "64", "65", "0", "mb1024", "mb1280", "mb1k", "mb256", "mb100", None, 5, True, ["m5"], "off", "show"]
for spec in OWNS:
    for word in words:
        cases.append(["own.amount", spec, word])
        cases.append(["own.canonical", spec, word, ["off", "show", "m15"]])
values_pool = {
    "task_changed_guard": ["off", "hold", "tell", "bogus", None, 1],
    "context_guard": ["off", "show", "above_100k", "above_250k", "above_1m", "above_300k", "above_9k", "above_1001k", "x", None],
    "retry_timing": ["conservative", "normal", "aggressive", "custom", "bogus", None],
    "retry_wait_1": ["s5", "s15", "h2", "h3", "s7", "m45", "s7200", "s7201", "m120", "bogus", None],
    "retry_wait_2": ["m15", "h6", "s5", "m20", "m14", "h7", "bogus"],
    "retry_wait_3": ["m30", "h1", "m16", "bogus"], "retry_wait_4": ["h2", "m15"], "retry_wait_5": ["h3", "m61", "s900"],
    "retry_jitter": [True, False, 1, None],
    "chain_time_ceiling": ["off", "h1", "h3", "h24", "m15", "m14", "h168", "h169", "m90", "bogus", None],
    "notifications": [True, False, 1], "notify_needs_you": [True, False],
    "notify_needs_you_invalid": [True, False], "notify_needs_you_policy": [True, False],
    "notify_needs_you_auth": [True, None], "notify_needs_you_failure": [True, "yes"],
    "stall_after": ["off", "m10", "h2", "m5", "m4", "h168", "h169", "m61", "bogus", None],
    "keep_awake": ["off", "on_ac", "always", "bogus", None],
    "keep_awake_hours": ["h1", "h6", "unlimited", "m15", "m14", "h168", "h169", "bogus", None],
    "ask_after_sleep_minutes": ["off", "m30", "h12", "m5", "m4", "m90", "bogus", None],
    "wait_for_network": [True, False, 1],
}
def random_values():
    found = {}
    for name, choices in values_pool.items():
        if rng.random() < 0.7:
            found[name] = rng.choice(choices)
    return found
for _ in range(2500):
    values = random_values()
    for name in ["guards.task_mode", "guards.watches_task", "guards.context_mode", "guards.counts_tokens",
                 "guards.context_limit", "ladder.timing", "ladder.custom_steps", "ladder.ladder", "ladder.walks",
                 "ladder.preview", "ladder.ceiling", "needsyou.told", "needsyou.kinds", "needsyou.stall_seconds",
                 "power.keep_awake", "power.awake_cap", "power.sleep_threshold", "power.waits_for_network", "power.listens"]:
        cases.append([name, values])
    cases.append(["guards.over", values, rng.choice([None, 0, 99999, 100001, 250000, 250001, 2 ** 53, 2 ** 53 + 1, True, -1, 1.5e6])])
    cases.append(["ladder.wait_before", values, rng.choice([1, 2, 3, 5, 6, 0, -2, 10 ** 30, 2.9, True, "3", " 4 ", "x", None, 7, float("inf"), float("-inf"), float("nan")]),
                  rng.choice(["rate_limit_transient", "timeout", None])])
    cases.append(["ladder.jittered", rng.choice([5, 60, 900, 100, 3600, 7.5, True, "x", None]), values,
                  rng.choice([0.0, 0.5, 0.999999, 0.5000005, 1.0, -0.1, 0.25, 0.123456789, 1, None, "0.5"])])
for odd in [None, 5, [], "x", {}]:
    for name in ["guards.task_mode", "guards.context_mode", "guards.context_limit", "ladder.timing", "ladder.custom_steps",
                 "ladder.preview", "ladder.ceiling", "needsyou.told", "needsyou.kinds", "needsyou.stall_seconds",
                 "power.keep_awake", "power.awake_cap", "power.sleep_threshold", "power.listens"]:
        cases.append([name, odd])
for field in ["retry_wait_1", "retry_wait_2", "retry_wait_5", "x"]:
    cases.append(["ladder.choices_for", field])
for delay in [100, 1, 37, 1000003, 5.5, 10 ** 15]:
    for draw in [0.0, 0.05, 0.1, 0.123457, 0.999999999, 0.75]:
        cases.append(["ladder.jittered", delay, {"retry_jitter": True}, draw])
digests = ["a" * 64, guards.UNREADABLE, "A" * 64, "a" * 63, None, 5]
for model in [None, "gpt-5", "x\x00y", 5, "é中"]:
    for approval in [None, "never", 1.5]:
        for head in [None, "a" * 64, "ref"]:
            cases.append(["guards.fingerprint", model, approval, head])
for recorded in digests:
    for now in digests:
        cases.append(["guards.changed", recorded, now])
    cases.append(["guards.is_print", recorded])
for value in [None, 0, 1, -1, 2 ** 53, 2 ** 53 + 1, True, 1.0, "5"]:
    cases.append(["guards.tokens", value])
for seconds in [0, 59, 60, 61, 3600, -120, 59.9, "120", True, None, "x"]:
    cases.append(["needsyou.minutes", seconds])
# power
readings = [[100, 50], [200, 60], [1000, 80], [100.5, 50], [400, 340], ["160", "50"], ["x", 1], [1], [], None, "12",
            {"a": 1}, [1e308, 0], [float("inf"), 0], [0, float("inf")], [float("nan"), 0], [100, float("nan")], [float("-inf"), 0],
            [10 ** 400, 0], [True, False]]
for before in readings:
    for after in readings:
        cases.append(["power.asleep", before, after])
rows = [{"state": "waiting_reset", "next_retry_at": 100, "reset_at": None, "not_before": None, "hold": None},
        {"state": "waiting_reset", "next_retry_at": 100, "reset_at": 150, "not_before": None, "hold": None, "cancel_requested": 1},
        {"state": "waiting_backoff", "next_retry_at": 0, "reset_at": 0, "not_before": 0, "hold": None},
        {"state": "recovered", "next_retry_at": 100}, {"state": "waiting_reset", "next_retry_at": 120, "hold": "ask"},
        {"state": "waiting_for_usage", "next_retry_at": None, "reset_at": 90.5, "not_before": 130}]
for row in rows:
    for since, until in [(0, 100), (99, 100), (100, 150), (100, 200), (150, 130), (-1, 0), ("a", 5)]:
        cases.append(["power.fell_due", row, since, until])
cases += [["power.waiting", rows], ["power.waiting", []], ["power.waiting", rows[:2]], ["power.waiting", [None]]]
for mode in ["off", "on_ac", "always", None, "x"]:
    for count in [0, 1, -1, 2.5, True, "x"]:
        for mains in [True, False, None, 1]:
            cases.append(["power.wants_awake", mode, count, mains])
# projects
folders = ["C:\\Work\\Proj", "c:/work/proj/", "\\\\?\\C:\\Work\\Proj", "  C:\\Work\\Proj\\\\  ", "C:\\STRASSE", "C:\\straße",
           "", "   ", "\\", "a\nb", "a\x00b", "İstanbul", "ΣΑΣ", None, 5]
for folder in folders:
    cases.append(["projects.normal_folder", folder])
    for project in [None, "", "  ", "proj-1", " proj-1 ", "p\x00", 7]:
        cases.append(["projects.key_for", project, folder])
keys = [projects.key_for("p%d" % n) for n in range(60)]
lists = ["", keys[0], ",".join(keys[:3]), ",".join(sorted(keys[:3])), ",".join(keys[:51]), ",".join(sorted(keys[:50])),
         keys[0] + "," + keys[0], keys[0] + ",", "x", None, 5, keys[0].upper()]
for text in lists:
    cases += [["projects.parse_keys", text], ["projects.coerce_keys", text, "default"]]
cases += [["projects.format_keys", keys[:5]], ["projects.format_keys", [keys[1], keys[0], keys[1]]], ["projects.format_keys", []]]
for key in [keys[0], keys[1], keys[55], None, "x", 5]:
    cases.append(["projects.is_key", key])
    for policy in ["every", "only_listed", "except_listed", "bogus", None]:
        for always_list in ["", keys[0], ",".join(sorted(keys[:2])), "bad", ",".join(sorted(keys[:50]))]:
            for never_list in ["", keys[1], ",".join(sorted(keys[1:3]))]:
                values = {"project_policy": policy, "project_keys_always": always_list, "project_keys_never": never_list}
                cases += [["projects.asks", values], ["projects.allows", values, key], ["projects.hold_for", values, key]]
                for always in (True, False):
                    cases.append(["projects.rule", values, key, always])
for odd in [None, 5, []]:
    cases += [["projects.asks", odd], ["projects.allows", odd, keys[0]], ["projects.rule", odd, keys[0], False]]
# permits
caps = ["usage_probe", "queue_withdraw", 5, [1]]
for state in ["VERIFIED", "CHECKED", "COMPATIBLE", "FAILED_HERE", "INCOMPATIBLE", "UNKNOWN", "bogus", None]:
    for tier in ["conservative", "advanced", "experimental", "unsupported", "bogus", None]:
        for opt_in in [True, False, 1]:
            for engine, ack in [("1.0", "1.0"), ("1.0", "0.9"), (None, None), ("2.0", "2.0"), (5, 5)]:
                view = {"capabilities": {"usage_probe": {"state": state}}, "engine": {"version": "1.0"}}
                cases.append(["permits.permits", view, rng.choice(caps), tier, opt_in, engine, ack])
for view in [None, [], {}, {"capabilities": None}, {"capabilities": []}, {"capabilities": {"usage_probe": "VERIFIED"}},
             {"capabilities": {"usage_probe": {"state": "VERIFIED"}}, "engine": []},
             {"capabilities": {"usage_probe": {"state": "VERIFIED"}}, "engine": None},
             {"capabilities": [1], "engine": {"version": "1.0"}}]:
    cases.append(["permits.permits", view, "usage_probe", "experimental", True, "1.0", "1.0"])
finish(cases, ops)
'''

QUIET = ZONE + r'''
from codex_auto_resume import quiet
rng = random.Random(5)
def quiet_until(now, values, spec):
    zone = Zone(spec)
    return quiet.quiet_until(now, values, localtime=zone.localtime, mktime=zone.mktime)
def postpone_time(now, preset, spec):
    zone = Zone(spec)
    return quiet.postpone_time(now, preset, localtime=zone.localtime, mktime=zone.mktime)
def zone_case(value, spec):
    zone = Zone(spec)
    if isinstance(value, list):
        return zone.mktime(tuple(value))
    t = zone.localtime(value)
    return [t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec, t.tm_wday]
def window(values):
    found = quiet.window(values)
    return None if found is None else [found[0], found[1], sorted(found[2])]
ops = {"quiet.window": window, "quiet.quiet_until": quiet_until, "quiet.postpone_time": postpone_time,
       "quiet.postponement_problem": quiet.postponement_problem, "quiet.zone": zone_case}
cases = []
starts = list(quiet.STARTS) + ["07:15", "7:05", "23:59", "24:00", None, 5, "bogus"]
ends = list(quiet.TIMES) + ["07:15", "00:00", "bogus", None]
days = ["every_day", "weekdays", "weekends", "mon,wed", "sun", "", "bogus", None, "MISSING"]
base = 1_767_225_600  # 2026-01-01 00:00 UTC
for _ in range(6000):
    values = {"quiet_hours_start": rng.choice(starts), "quiet_hours_end": rng.choice(ends)}
    chosen = rng.choice(days)
    if chosen != "MISSING":
        values["quiet_hours_days"] = chosen
    now = rng.choice([base + rng.randrange(0, 366 * 86400), base + rng.randrange(0, 366 * 86400) + 0.5,
                      rng.choice([0, -5, 10 ** 30, True, "x", None, 1e18, float("nan"), float("inf"), float("-inf"), 2 ** 70])])
    cases.append(["quiet.window", values])
    cases.append(["quiet.quiet_until", now, values, rng.choice(ZONES)])
for spec in ZONES:
    # Every day of a year at the hours a window opens and closes, across both changes of the clock.
    for day in range(0, 366, 3):
        for hour in (0, 1, 2, 3, 6, 7, 22, 23):
            now = base + day * 86400 + hour * 3600 + rng.choice([0, 1799, 1800, 3599])
            cases.append(["quiet.quiet_until", now, {"quiet_hours_start": "22:00", "quiet_hours_end": "07:00"}, spec])
            cases.append(["quiet.quiet_until", now, {"quiet_hours_start": "01:30", "quiet_hours_end": "02:30",
                                                     "quiet_hours_days": "weekdays"}, spec])
    for value in [base, base + 0.75, 0, -1, 32503680001, 2 ** 70, 1e308]:
        cases.append(["quiet.zone", value, spec])
    for parts in [[2026, 1, 1, 0, 0, 0], [2026, 13, 1, 0, 0, 0], [2026, 2, 30, 9, 0, 0], [2026, 3, 27, 2, 30, 0],
                  [1969, 12, 31, 23, 0, 0], [3001, 1, 1, 0, 0, 0], [2026, 0, 0, 0, 0, 0]]:
        cases.append(["quiet.zone", parts, spec])
    for preset in list(quiet.PRESETS) + ["bogus", None, ["x"]]:
        for now in [base, base + 86400 * 100 + 0.5, "123", True, None, -5]:
            cases.append(["quiet.postpone_time", now, preset, spec])
for until in [None, True, 5, 100, 100.0, 101, 100 + 7 * 86400, 101 + 7 * 86400, 100.5 + 7 * 86400, 1e300, float("inf"), float("-inf"), float("nan"),
              2 ** 70, "200", [1]]:
    for now in [100, 100.5, True]:
        for not_before in [None, 50, 150, 100.0, "x"]:
            cases.append(["quiet.postponement_problem", until, now, not_before])
finish(cases, ops)
'''


class GatesDiff(Leaves):
    def test_gates(self):
        done = self.family(GATES, label="gates", expect_ops=1000)
        RECORD.append("gates: %d cases (gate, consent, schedule, submission_safe, own_budget_only, was_resent, "
                      "resend_candidate, chain_span, waited_aside, counted_from, over_ceiling, inherited, birth_stop, "
                      "budgets, first_refusal, would_send_at, usage_read_stopped, encode, decode) equal" % len(done["cases"]))


class PolicyDiff(Leaves):
    def test_guards_ladder_needsyou_power_projects_permits(self):
        done = self.family(GUARDS_LADDER, label="policy", expect_ops=1000)
        names = sorted({case[0].split(".")[0] for case in done["cases"]})
        RECORD.append("policy: %d cases of %s equal" % (len(done["cases"]), ", ".join(names)))


class QuietDiff(Leaves):
    def test_quiet_hours_and_postponements(self):
        done = self.family(QUIET, label="quiet", expect_ops=1000)
        RECORD.append("quiet: %d cases (window, quiet_until over 6 zones and a year of days, postpone_time, "
                      "postponement_problem, the test zone itself) equal" % len(done["cases"]))
