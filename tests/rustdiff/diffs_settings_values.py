"""S2.2, car-policy's settings held to the tag: every value through the coercers, the strict validator, the
migration, the schema and the readers of a settings dict; a person's own values (ownvalues); the Codex homes'
checks; the kinds of notice; the memory guard.

Each test makes its cases inside the reference (settingsdiff.py): hand-picked edges and generated values - every
field's choices and its own spellings, its bounds and one past them, each wrong type (a bool where a number is, an
int of any size, a NaN, an infinity, half of a surrogate pair), unknown and reserved keys - and what the tag answers
to each, the value or the exception with its sentence. The same cases go to car-harness, and every answer must be the
same, keys in the same order.
"""
from __future__ import annotations

from rustdiff.settingsdiff import Family

RECORD: list[str] = []

# The candidate values every field is tried with, made in the reference (`CANDIDATES` in the scripts below).
VALUES = r'''
from codex_auto_resume import settings, ownvalues, homes, notice_kinds, memguard, l10n
rng = random.Random(int(sys.argv[1]) if len(sys.argv) > 1 else 7)
UUID = "0a1b2c3d-0001-7000-8000-00000000000%d"
HEX = "%064x"
SUR = "\ud800"
WRONG = [None, True, False, 0, 1, -1, 2, 2 ** 70, -(2 ** 70), 1.5, 0.0, -0.0, float("nan"), float("inf"), float("-inf"),
         "", " ", "x", "\u3000", SUR, "a" + SUR, [], [1], ["a"], {}, {"a": 1}, 10 ** 30, 5e-324, 1e308]
OWN_TEXT = ["s5", "s15", "s0", "s05", "s7200", "s7201", "m1", "m45", "m60", "m90", "m120", "m121", "m15", "m010", "h1",
            "h2", "h3", "h6", "h7", "h168", "h169", "m10080", "m10081", "h999999", "m9999999", "m99999999", "S5", "m 5",
            " m5", "m5 ", "m５", "m-5", "x5", "m", "h", "off", "unlimited", "13:15", "13:00", "7:05", "07:05", "24:00",
            "23:59", "23:60", "0:00", "00:0", "1:2:3", "１３:１５", "mon", "mon,wed,fri", "fri,mon", "mon,mon",
            "mon,tue,wed,thu,fri", "sat,sun", "mon,tue,wed,thu,fri,sat,sun", "", "mon,", ",mon", "Mon", "every_day",
            "weekdays", "weekends", "mb128", "mb127", "mb1280", "mb1024", "mb16384", "mb16385", "mb0128", "mbk1",
            "mb1k", "128", "above_10k", "above_9k", "above_300k", "above_1000k", "above_1m", "above_10m", "above_11m",
            "above_10000", "above_9999", "above_250k", "above_2500000", "above_1500k", "above_k", "above_01k", "show",
            "s1234567", "s12345678", "h1" + SUR]
CUSTOM = ["Please continue.", "", "   ", "\n\t", "a" * 2000, "a" * 2001, "{reason} and {category}", "{Reason}", "{prompt}",
          "{PROMPT}", "{Project_Path}", "{unknown}", "{{reason}}", "{reason", "{9x}", "{_x}", "{a b}", "{reset_time}",
          "{max_attempts} {attempt}", "x {token} y {reason}", "hi " + SUR, SUR + "{prompt}", "\u3000x\u3000", "é" * 2000,
          "😀" * 2000, "😀" * 2001, "{email}{user}", "{}", "{reason}" * 300]
STRINGS = ["system", "en", "ko", "zh-CN", "zh-cn", "follow", "standard", "careful", "detailed", "custom", "minimal",
           "global", "per_reason", "soft", "classic", "plain", "still", "light", "dark", "same", "automatic",
           "objection_window", "ask_first", "notify_only", "resume", "every", "only_listed", "except_listed", "hold",
           "tell", "on_ac", "always", "warn", "stop", "page", "chat", "codex", "conservative", "normal", "aggressive",
           "C:\\Program Files\\codex.exe", "a" * 32767, "a" * 32768]
THREADS = [{UUID % 1: "Hello"}, {UUID % 1: "Hello", UUID % 2: "{reason}"}, {UUID % 1: ""}, {"nope": "x"},
           {UUID % 1: "{prompt}", UUID % 2: "ok"}, {(UUID % 1).upper(): "x"}, {}, {UUID % 1: SUR},
           {UUID % 1: "x", "bad": "y"}, {("0a1b2c3d-0001-7000-8000-%012d" % n): "x" for n in range(50)},
           {("0a1b2c3d-0001-7000-8000-%012d" % n): "x" for n in range(51)}, {UUID % 1: 5}, {UUID % 1: None}]
KEYS = ["", HEX % 1, HEX % 1 + "," + HEX % 2, HEX % 2 + "," + HEX % 1, HEX % 1 + "," + HEX % 1, (HEX % 1).upper(),
        ",".join(HEX % n for n in range(50)), ",".join(HEX % n for n in range(51)), HEX % 1 + ",", "x", HEX % 1 + " "]
def home(path, alias="Work"):
    return {"path": path, "alias": alias}
HOMES = [[], [home("C:\\Codex\\work")], [home("C:\\a"), home("D:\\b", "Two")], [home("C:\\a"), home("c:/A/", "Two")],
         [home("C:\\a", "Same"), home("D:\\b", "same")], [home("C:\\a", "Straße"), home("D:\\b", "STRASSE")],
         [home("C:\\a", "ǅ"), home("D:\\b", "ǆ")], [home("C:\\a", " Work"), ], [home("C:\\a", "")], [home("C:\\a", "a" * 33)],
         [home("C:\\a", "a" * 32)], [home("relative\\path")], [home("\\\\server\\share")], [home("C:")], [home("C:x")],
         [home("C:\\a\x01")], [home("C:\\" + "a" * 257)], [home("C:\\" + "a" * 258)], [home("C:\\a"), home("D:\\b", "B"),
         home("E:\\c", "C"), home("F:\\d", "D")], [{"path": "C:\\a", "alias": "A", "x": 1}], [{"path": "C:\\a"}],
         [home("C:\\a\\..\\b"), home("C:\\b", "B")], [home("C:\\a\\.\\b"), home("C:\\a\\b", "B")], [home(5)],
         [home("C:\\a", 5)], ["C:\\a"], [home("C:\\İ"), home("C:\\i̇", "B")], [home("C:\\a" + SUR)], [home("C:\\Ä"), home("c:\\ä", "B")],
         [home("1:\\a")], [home("é:\\a")], [home("C:/x/y/")], [home("C:\\a"), home("C:\\a.", "B")]]
DISMISSED = [[], ["C:\\a"], ["C:\\a", "c:/A"], ["C:\\a", "C:\\a."], ["C:\\a", "D:\\b"], ["relative"], [5],
             ["C:\\x%d" % n for n in range(16)], ["C:\\x%d" % n for n in range(17)], ["C:\\a\\..\\b", "C:\\b"],
             ["C:\\a" + SUR], ["\\\\server\\share"], "C:\\a", None]
STAYS = [[], ["interruption"], ["interruption", "interruption"], ["resumed", "power", "mine_1"], ["Bad"], [5],
         ["a" * 32], ["a" * 33], ["x%d" % n for n in range(64)], ["x%d" % n for n in range(65)], "interruption", None,
         ["_x"], ["x-y"], ["x\n"]]
CANDIDATES = WRONG + OWN_TEXT + CUSTOM + STRINGS + THREADS + KEYS + HOMES + DISMISSED + STAYS + [
    3, 4, 5, 6, 7, 8, 10, 11, 19, 20, 21, 59, 60, 61, 0.5, 5.0, 6.0, 168, 168.0, 168.00001, 167.9, -1e-9, 1e-9, 24]

def field_values(name):
    """The candidates, and the field's own choices."""
    found = list(CANDIDATES)
    found += list(settings.RANGES.get(name, {}).get("choices", []))
    return found
'''


class SettingsCoerceDiff(Family):
    def test_coerce_validate_migrate(self):
        script = VALUES + r'''
cases = []
names = list(settings.FIELDS)
for name in names:
    for value in field_values(name):
        cases.append(["settings.coerce", {name: value}])
        cases.append(["settings.validate", {name: value}])
for _ in range(1500):
    raw = {name: rng.choice(field_values(name)) for name in rng.sample(names, rng.randrange(1, len(names)))}
    if rng.random() < 0.3:
        raw["recover_auth_service_transient"] = rng.choice([True, False])
        raw["custom_message_auth_service_transient"] = "x"
    if rng.random() < 0.3:
        raw["no_such_setting"] = 1
    cases.append(["settings.coerce", raw])
    cases.append(["settings.validate", dict(list(raw.items())[:rng.randrange(1, 4)])])
for changes in [None, [], "x", 5, {}, {"zzz": 1, "aaa": 2}, {"zzz": 1, "theme": "dark"}, {"théme": 1, "Theme": 2},
                {SUR: 1}, {"design": "still"}, {"continuation_style": "careful"}, {"codex_exe": None},
                {"custom_message": None}, {"custom_message_by_thread": None}, {"theme": None},
                {"quiet_hours_end": "7:05"}, {"retry_wait_2": "m60"}, {"quiet_hours_days": "fri,mon"},
                {"memory_guard_limit": "mb1024"}, {"context_guard": "above_1000k"}, {"max_no_progress": 3.0},
                {"reduce_motion": 0}, {"notifications": 0}, {"detection_lookback_hours": 6},
                {"detection_lookback_hours": float("nan")}, {"max_recovery_attempts": 2 ** 70}]:
    cases.append(["settings.validate", changes])
for raw in [None, [], "x", {}, {"config_version": 2, "theme": "dark"}, {"theme": "dark", "zzz": 1},
            {"config_version": 1, "design": "still", "reduce_motion": False},
            {"design": "still"}, {"continuation_style": "careful"}, {"config_version": 0, "theme": "dark", "x": 1},
            {"config_version": True, "x": 1}, {"config_version": False, "x": 1}, {"config_version": "2", "x": 1},
            {"config_version": -1}, {"config_version": 2 ** 70, "x": 1}, {"config_version": -(2 ** 70), "x": 1},
            {"config_version": 1.5, "x": 1}, {"config_version": 3, "design": "still", "continuation_style": "careful"},
            {"continuation_style": 5}, {"design": ["still"]}, {"reduce_motion": True, "design": "still", "theme": "x"}]:
    cases.append(["settings.migrate", raw])
    cases.append(["settings.coerce", raw])
ops = {"settings.coerce": settings.coerce, "settings.validate": settings.validate_update,
       "settings.migrate": settings._migrate}
finish(cases, ops)
'''
        done = self.family(script, label="coerce", expect=10000)
        RECORD.append("settings: %d coerce/validate/migrate cases equal to %s's (accepted %d, refused %d)" % (
            len(done["cases"]), __import__("rustdiff.reference", fromlist=["TAG"]).TAG,
            sum(1 for each in done["results"] if "ok" in each),
            sum(1 for each in done["results"] if "error" in each)))


class SettingsSchemaDiff(Family):
    def test_schema_and_readers(self):
        script = VALUES + r'''
cases = [["settings.defaults"], ["settings.describe"]]
for name in list(settings.FIELDS):
    cases += [["settings.field_type", name], ["settings.ranges", name], ["settings.is_custom_text", name]]
for name in ["custom_message_mode", "custom_messages", "custom", "x"]:
    cases.append(["settings.is_custom_text", name])
for value in CANDIDATES + [{"a": [1, {"b": SUR}]}, [SUR], {SUR: 1}, {"k": float("nan")}]:
    cases.append(["settings.whole_text", value])
valueses = [None, {}, [], "x", 0, 1, {"theme": "dark", "design": "classic", "default_tier": "ask_first"},
            {"theme": 5, "design": "still"}, {"max_recovery_attempts": 9, "max_no_progress": 6, "max_chain_continuations": 9},
            {"max_recovery_attempts": True, "max_no_progress": 2 ** 70, "max_chain_continuations": 8.5},
            {"notifications": False, "notify_starting": True}, {"notifications": 0}, {"notify_starting": 0},
            {"notify_interruption": False}, {"recover_timeout": False, "recover_usage_limit": 0}, {"recover_timeout": []}]
for values in valueses:
    for helper in ("settings.high_limits", "settings.theme_preference", "settings.design_preference"):
        cases.append([helper, values])
    for own in [None, "ask_first", "x", 5, ["ask_first"], "notify_only"]:
        cases.append(["settings.tier_of", values, own])
    for category in ["usage_limit", "timeout", "auth_service_transient", "unknown", ""]:
        cases.append(["settings.category_enabled", values, category])
    for event in ["interruption", "starting", "result", "stopped", "needs_you", "objection", "after_sleep", "x"]:
        cases.append(["settings.notification_enabled", values, event])
for _ in range(300):
    names = rng.sample(list(settings.FIELDS), rng.randrange(1, 12))
    cases.append(["settings.bytes", {name: rng.choice(field_values(name)) for name in names}])
cases.append(["settings.bytes", {}])
def file_bytes(values):
    payload = dict(settings.coerce(values), config_version=settings.CONFIG_VERSION)
    return json.dumps(payload, indent=2, sort_keys=True, allow_nan=False, ensure_ascii=False).encode("utf-8").hex()
ops = {"settings.defaults": settings.defaults, "settings.describe": settings.describe,
       "settings.field_type": settings.field_type, "settings.ranges": settings.RANGES.get,
       "settings.is_custom_text": settings.is_custom_text, "settings.whole_text": settings.whole_text,
       "settings.high_limits": settings.high_limits, "settings.theme_preference": settings.theme_preference,
       "settings.design_preference": settings.design_preference, "settings.tier_of": settings.tier_of,
       "settings.category_enabled": settings.category_enabled,
       "settings.notification_enabled": settings.notification_enabled, "settings.bytes": file_bytes}
finish(cases, ops)
'''
        done = self.family(script, label="schema", expect=500)
        RECORD.append("settings: defaults, describe(), %d schema/reader cases equal" % len(done["cases"]))


class OwnValuesDiff(Family):
    def test_own_values(self):
        script = VALUES + r'''
cases = []
for name in settings.OWN:
    cases.append(["own.published", name])
    for value in OWN_TEXT + WRONG + ["%s%d" % (unit, n) for unit in "smh" for n in (1, 5, 59, 60, 61, 90, 120, 300, 3600)]:
        cases += [["own.amount", name, value], ["own.canonical", name, value]]
ops = {"own.published": lambda name: ownvalues.published(settings.OWN[name]),
       "own.amount": lambda name, value: ownvalues.amount(settings.OWN[name], value),
       "own.canonical": lambda name, value: ownvalues.canonical(settings.OWN[name], value)}
finish(cases, ops)
'''
        done = self.family(script, label="own", expect=1000)
        RECORD.append("ownvalues: %d amount/canonical/published cases equal" % len(done["cases"]))


class HomesKindsMemoryDiff(Family):
    def test_homes_kinds_memory(self):
        script = VALUES + r'''
cases = []
for value in HOMES + WRONG + [[home("C:\\a")] * 2]:
    cases += [["homes.well_formed", value], ["homes.coerce", value]]
for version in ["0.162.0", "0.162.1-alpha", "0.163.0", "1.0.0", "0.161.9", "codex-cli 0.162.0-alpha.17.2", "0.162",
                "", None, 5, "x.1.2.3", "１.２.３", "0.0162.0", "0.99999999999999999999999.0", "00.162.0", "0.1620.0"]:
    cases.append(["homes.unmeasured", version])
for path in ["C:\\Codex\\work", "c:/codex/WORK/", "C:\\a\\..\\b", "C:\\a.", "C:\\a ", "C:\\" + SUR, "D:\\x\\y"]:
    # Absolute paths only: a relative one is resolved against each process's own working folder.
    cases += [["homes.key", path], ["homes.as_written", path]]
found = [[{"key": "", "state": "lock_busy"}], [{"key": "x"}], [{"state": "x"}], [{"key": [1], "state": "x"}], [5, "x"],
         None, [], "abc", {"a": 1}, 0, 7, True]
for configured in [[], [home("C:\\Codex\\work")], [home("C:\\a"), home("D:\\b", "B")], "bad", [home("bad")]]:
    for each in found:
        for version in ["0.163.0", "0.150.0", None]:
            cases.append(["homes.view", configured, each, version, True])
    cases.append(["homes.view", configured, None, "0.163.0", False])
for value in STAYS + WRONG:
    cases += [["kinds.coerce", value], ["kinds.chosen", {notice_kinds.FIELD: value}]]
every = {locale: "Mine " + locale for locale in l10n.LOCALES}
for kind_id, notices, words in [("mine", ["mine_1"], every), ("Mine", ["x"], every), ("mine2", [], every),
                                ("mine3", "mine_3", every), ("mine4", ["power_now"], every), ("interruption", ["z"], every),
                                ("mine5", ["mine_5"], {"en": "x"}), ("mine6", ["mine_6"], dict(every, ko="")),
                                ("mine7", ["mine_7"], dict(every, ko="a" * 201)), ("mine8", ["mine_1"], every),
                                ("mine", ["mine_9"], every), ("mine10", ["mine_10", "Bad"], every), (5, ["x"], every),
                                ("mine11", ["mine_11"], dict(every, ko=5)), ("mine12", ("mine_12",), every)]:
    cases.append(["kinds.register", kind_id, notices, words])
    cases.append(["kinds.ids"])
for locale in ["en", "ko", "xx"]:
    cases.append(["kinds.labels", locale])
for notice in ["interruption", "unknown", "power_now", "memory_stopped", "mine_9", "demo", "x"]:
    for values in [{notice_kinds.FIELD: ["failed", "power", "mine"]}, {notice_kinds.FIELD: "x"}, None, {}]:
        cases.append(["kinds.stays", notice, values])
for values in [None, {}, {"memory_guard": "warn"}, {"memory_guard": "stop", "memory_guard_limit": "mb256"},
               {"memory_guard": "stop", "memory_guard_limit": "mb1280"}, {"memory_guard": "x", "memory_guard_limit": "mb1"},
               {"memory_guard": "warn", "memory_guard_limit": 5}, [], "stop", {"memory_guard": ["stop"]}]:
    cases += [["mem.mode", values], ["mem.limit_mib", values]]
    for private in [None, True, 0, 1, 256 * 1048576, 256 * 1048576 + 1, 2 ** 70, -5, 1.5e9, "1"]:
        for warned in [False, True, 0, "x"]:
            cases.append(["mem.verdict", values, private, warned])
for count in [0, 1, 1048575, 1048576, 1048577, 2 ** 70, 2 ** 70 + 1, -1, True, 1.0, None, "5", 10 ** 40 + 7]:
    cases.append(["mem.mib", count])
ops = {"homes.well_formed": homes.well_formed, "homes.coerce": lambda value: homes.coerce(value, []),
       "homes.unmeasured": homes.unmeasured, "homes.key": homes.key, "homes.as_written": homes.as_written,
       "homes.view": homes.view, "kinds.coerce": lambda value: notice_kinds.coerce(value, []),
       "kinds.chosen": notice_kinds.chosen,
       "kinds.register": lambda kind_id, notices, words: notice_kinds.register(
           kind_id, tuple(notices) if notices == ["mine_12"] else notices, words).id,
       "kinds.ids": notice_kinds.ids, "kinds.labels": notice_kinds.edition_labels, "kinds.stays": notice_kinds.stays,
       "mem.mode": memguard.mode, "mem.limit_mib": memguard.limit_mib, "mem.verdict": memguard.verdict,
       "mem.mib": memguard.mib}
finish(cases, ops)
'''
        done = self.family(script, label="homes", expect=500)
        RECORD.append("homes, notice kinds, memory guard: %d cases equal" % len(done["cases"]))
