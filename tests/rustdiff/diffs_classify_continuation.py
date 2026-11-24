"""S2.1, car-policy's `continuation.py`: the continuation text, equal in all 22 languages (PLAN 5.3, P2's done-check).

* TextDiff - `build()` for every category (the 14 the classifier has, and one it has not) in every catalog language
  (and one it has not), every style (the four, the folded `careful`, a bogus one), every Custom choice the settings
  can hold (none, global, per reason, a conversation's own; text that fills in to nothing; placeholders known,
  missing and forbidden) and every metadata a record can give (an attempt, a maximum, a reset time, none).
* SettingsDiff - the same text the way the watcher and the Preview ask for it (`for_settings`, `source_for`,
  `with_once_words`, `metadata_for`, `resolve_locale`, `custom_from`, `style_from`), from generated settings, records,
  limits, environments and reset times on a test zone.
* CheckDiff - what a person's words are checked by: `validate_custom`, `validate_prompt` (with every product text of
  every language), `validate_continuation`, `coerce_by_thread`, the command line it must fit, and `_fill`.
"""
from __future__ import annotations

from rustdiff.diffs_classify_policy import ZONE
from rustdiff.leaves import Leaves

RECORD: list[str] = []

COMMON = ZONE + r'''
import types
from codex_auto_resume import continuation, l10n, failures, reasons
l10n._windows_preferred = lambda: []
REAL_TIME = time

def with_zone(spec):
    zone = Zone(spec)
    continuation.time = types.SimpleNamespace(localtime=zone.localtime, strftime=REAL_TIME.strftime)

def refused(call):
    try:
        return ["ok", call()]
    except continuation.CustomMessageError as error:
        return ["refused", error.code, error.detail, str(error)]
    except continuation.PromptError as error:
        return ["refused", error.code]

def settings(name, *args):
    head, (values, row, limits, environ, spec) = args[:-5], args[-5:]
    with_zone(spec)
    return getattr(continuation, name)(*head, values, row=row, limits=limits, environ=environ)

def build(category, locale, style, custom, metadata):
    return continuation.build(category, locale=locale, style=style, custom=custom, metadata=metadata)

def metadata_for(row, locale, limits, reset_time):
    return continuation.metadata_for(row, locale=locale, limits=limits, reset_time=reset_time)

def reset_time(stamp, spec):
    with_zone(spec)
    return continuation.format_reset_time(stamp)

ops = {
    "continuation.validate_custom": lambda text: refused(lambda: continuation.validate_custom(text)),
    "continuation.validate_prompt": lambda text: refused(lambda: continuation.validate_prompt(text)),
    "continuation.validate_continuation": lambda text: refused(lambda: continuation.validate_continuation(text)),
    "continuation.joined_command_line": continuation.joined_command_line,
    "continuation.command_line_units": continuation.command_line_units,
    "continuation.fits_command_line": continuation.fits_command_line,
    "continuation.product_texts": lambda: sorted(continuation.product_texts()),
    "continuation.prompt_limit": lambda: continuation.PROMPT_LIMIT,
    "continuation.coerce_by_thread": continuation.coerce_by_thread,
    "continuation.conversation_text": continuation.conversation_text,
    "continuation.fill": continuation._fill,
    "continuation.metadata_for": metadata_for,
    "continuation.build": build,
    "continuation.resolve_locale": continuation.resolve_locale,
    "continuation.fold_style": continuation.fold_style,
    "continuation.style_from": continuation.style_from,
    "continuation.custom_from": continuation.custom_from,
    "continuation.format_reset_time": reset_time,
    "continuation.source_for": lambda category, *rest: settings("source_for", category, *rest),
    "continuation.for_settings": lambda category, *rest: settings("for_settings", category, *rest),
    "continuation.with_once_words": lambda message, words, category, *rest: settings("with_once_words", message, words, category, *rest),
}
CATEGORIES = sorted(failures.CATEGORIES) + ["bogus"]
LOCALES = list(l10n.LOCALES) + ["xx"]
STYLES = ["minimal", "standard", "detailed", "custom", "careful", "bogus"]
'''

TEXT = COMMON + r'''
customs = [None, {}, {"mode": "global", "text": "Please go on."},
           {"mode": "global", "text": "Again: {reason} ({category}), try {attempt} of {max_attempts}, reset {reset_time}."},
           {"mode": "per_reason", "text": "global words", "per_reason": {"usage_limit": "per usage {reset_time}", "timeout": "  "}},
           {"mode": "per_reason", "text": "{reset_time}", "per_reason": {"server_5xx": "{reset_time}"}},
           {"mode": None, "text": "", "per_reason": {"timeout": "only timeout"}},
           {"mode": "global", "text": "x", "conversation": "Conversation's own {attempt}."},
           {"mode": "global", "text": "x", "conversation": "{reset_time}"},
           {"mode": "per_reason", "per_reason": [], "text": None}]
metadatas = [None, {}, {"attempt": 2, "max_attempts": 5}, {"reset_time": "07:30"},
             {"attempt": 1, "max_attempts": 3, "reset_time": "23:59", "category": "x", "reason": "own words"}]
cases = []
for locale in LOCALES:
    for category in CATEGORIES:
        for style in STYLES:
            for custom in customs:
                for metadata in metadatas:
                    cases.append(["continuation.build", category, locale, style, custom, metadata])
for category in [None, 5, ["usage_limit"]]:
    cases.append(["continuation.build", category, "en", "standard", None, None])
finish(cases, ops)
'''

SETTINGS = COMMON + r'''
rng = random.Random(9)
threads = ["0a1b2c3d-0001-7000-8000-000000000001", "0a1b2c3d-0001-7000-8000-000000000002", "not-a-uuid"]
def random_values():
    values = {}
    pick = lambda name, choices: values.__setitem__(name, rng.choice(choices)) if rng.random() < 0.7 else None
    pick("continuation_style", STYLES + [None, 5])
    pick("continuation_language", LOCALES + ["follow", None, "pt-br"])
    pick("interface_language", LOCALES + ["system", None, " ko ", "zh_TW", "pt", "de-AT", 5])
    pick("custom_message_mode", ["global", "per_reason", "bogus", None])
    pick("custom_message", ["Keep going.", "{reason}: go on", "{reset_time}", "", "  ", None, 5, "{attempt}/{max_attempts}"])
    for category in reasons.RECOVERABLE:
        pick("custom_message_" + category, ["per {category}", "{reset_time}", "", None])
    pick("custom_message_by_thread", [None, {}, {threads[0]: "mine {attempt}"}, {threads[0]: "{prompt}", threads[1]: "ok"},
                                      {threads[2]: "x"}, {threads[0]: ""}, "x"])
    return values
def random_row():
    if rng.random() < 0.15:
        return None
    row = {}
    for name, choices in [("category", CATEGORIES + [None]), ("recovery_attempts", [None, 0, 1, 4, True, "2"]),
                          ("reset_at", [None, 0, 1_767_250_000, 1_767_250_000.5, "1767250000", -5, 10 ** 30, "x"]),
                          ("thread_id", threads + [None])]:
        if rng.random() < 0.8:
            row[name] = rng.choice(choices)
    return row
environs = [{}, {"CODEX_AUTO_RESUME_LANG": "ja"}, {"CODEX_AUTO_RESUME_LANG": "zz"}, {"LANG": "fr_FR.UTF-8"},
            {"LC_ALL": "C", "LANG": "de_DE"}, {"CODEX_AUTO_RESUME_LANG": " pt-BR "}]
cases = []
for _ in range(5000):
    values, row = random_values(), random_row()
    limits = rng.choice([None, {}, {"max_recovery_attempts": 5}, {"max_recovery_attempts": 0}, {"max_recovery_attempts": "3"}])
    environ, spec = rng.choice(environs), rng.choice(ZONES)
    category = rng.choice(CATEGORIES)
    cases.append(["continuation.for_settings", category, values, row, limits, environ, spec])
    cases.append(["continuation.source_for", category, values, row, limits, environ, spec])
    cases.append(["continuation.with_once_words", rng.choice(["Base text.", None, 5]),
                  rng.choice([None, "and also {reason}", "{reset_time}", "{prompt}", "", "plain"]), category,
                  values, row, limits, environ, spec])
    cases.append(["continuation.resolve_locale", values, environ])
    cases.append(["continuation.style_from", values])
    cases.append(["continuation.custom_from", values, rng.choice(threads + [None, 5])])
    cases.append(["continuation.conversation_text", values, rng.choice(threads + [None])])
    cases.append(["continuation.metadata_for", row, rng.choice(LOCALES), limits, rng.choice([None, "", "07:00"])])
for stamp in [None, 0, 1, 1_767_250_000, 1_767_250_000.9, "1767250000", "x", -1, 10 ** 30, True, [1]]:
    for spec in ZONES:
        cases.append(["continuation.format_reset_time", stamp, spec])
for odd in [5, "x", []]:
    cases += [["continuation.style_from", odd], ["continuation.custom_from", odd, None], ["continuation.resolve_locale", odd, {}]]
for style in STYLES + [None, 5, ["careful"]]:
    cases.append(["continuation.fold_style", style])
finish(cases, ops)
'''

CHECKS = COMMON + r'''
rng = random.Random(4)
cases = [["continuation.product_texts"], ["continuation.prompt_limit"]]
texts = [None, 5, "", " ", "\n\t", "Go on.", "x" * 2000, "x" * 2001, "{reason} {category} {attempt} {max_attempts} {reset_time}",
         "{prompt}", "{Prompt}", "{PROMPT}", "{user}", "{unknown}", "{reason}{token}", "{ reason }", "{{reason}}", "{1x}",
         "{_x}", "{reason", "reason}", "{é}", "é" * 2001, "\U0001f600" * 1000, "{reset_time} {cwd}", "a\x00b", "a\x01b",
         "a\x7fb", "tab\there", "line\r\nbreak", "[codex-auto-resume:abc]", "{a}", "{x}{y}", "{reason}" * 300]
for text in texts:
    cases += [["continuation.validate_custom", text], ["continuation.validate_continuation", text],
              ["continuation.validate_prompt", text]]
# A person's message that is one of the product's own texts, in any language, is refused.
for locale in ("en", "ko", "ar", "th", "de"):
    for category in reasons.RECOVERABLE:
        for style in ("minimal", "standard", "detailed"):
            text = continuation.build(category, locale=locale, style=style)
            cases += [["continuation.validate_prompt", text], ["continuation.validate_prompt", "  " + text.upper() + " "],
                      ["continuation.validate_prompt", text + "!"]]
for size in (29960, 29961, 29962, 29963, 30000):
    cases.append(["continuation.validate_prompt", "a" * size])
for size in (15000, 16080, 16081, 16090, 16100):
    cases += [["continuation.validate_prompt", '"' * size], ["continuation.validate_prompt", "\U0001f600" * size],
              ["continuation.fits_command_line", "\\" * size + '"']]
argvs = [[], [""], ["a b"], ["a\tb"], ['a"b'], ["a\\b"], ["a\\\\"], ["a b\\"], ["a b\\\\"], ['\\"'], ["x", "", "y z"],
         ["--message=hi there\\", "codex.exe"], ["é 中", "\U0001f600"]]
for argv in argvs:
    cases += [["continuation.joined_command_line", argv], ["continuation.command_line_units", argv]]
for _ in range(500):
    argv = ["".join(rng.choice(['a', ' ', '\\', '"', '\t', 'é', '\U0001f600']) for _ in range(rng.randrange(0, 8)))
            for _ in range(rng.randrange(1, 4))]
    cases += [["continuation.joined_command_line", argv], ["continuation.command_line_units", argv]]
threads = ["0a1b2c3d-0001-7000-8000-00000000000%d" % n for n in range(10)]
for value in [None, {}, [], "x", {threads[0]: "ok"}, {threads[0]: "{prompt}"}, {threads[0]: ""}, {"bad": "ok"},
              {threads[0]: 5}, {t: "m" for t in threads}, {"%s" % n: "m" for n in range(51)},
              {"0A1B2C3D-0001-7000-8000-000000000001": "upper"}, {threads[1]: "a", threads[2]: "{x}"}]:
    for default in [None, {"d": 1}]:
        cases.append(["continuation.coerce_by_thread", value, default])
templates = ["{reason}", "Go on {reset_time}.", "Go on {reset_time} now", "Go on  {reset_time}  now", "{reset_time} start",
             "line\n{reset_time} next", "a {reset_time}\nb", "a\t{reset_time}\tb", "a {reset_time}, b", "a {reset_time}: b",
             "a {reset_time} {attempt} b", "a {attempt} {reset_time} b", "{reset_time}{reset_time}", "a {x} b",
             "plain text", "{attempt}/{max_attempts}", "a {reset_time}\r\nb", "a{reset_time} b", "a {reset_time}b",
             "  {reset_time}  ", "a {reset_time}!", "Voici :  {reset_time} ?", "a {reset_time}　b"]
fills = [{}, {"reset_time": "07:00"}, {"reset_time": ""}, {"attempt": 2}, {"attempt": 0, "max_attempts": 5},
         {"reset_time": None, "attempt": 1.5}, {"attempt": True}, {"x": "y"}]
for template in templates:
    for values in fills:
        cases.append(["continuation.fill", template, values])
finish(cases, ops)
'''


class TextDiff(Leaves):
    def test_every_language_reason_and_option(self):
        done = self.family(TEXT, label="continuation-text", expect_ops=10000, chunk=3000)
        locales = sorted({case[2] for case in done["cases"] if case[0] == "continuation.build"})
        RECORD.append("continuation text: %d builds equal - %d languages (22 and one it lacks) x 15 categories x 6 "
                      "styles x 10 Custom choices x 5 metadata" % (len(done["cases"]), len(locales)))


class SettingsDiff(Leaves):
    def test_from_settings(self):
        done = self.family(SETTINGS, label="continuation-settings", expect_ops=1000, chunk=3000)
        RECORD.append("continuation settings: %d cases (for_settings, source_for, with_once_words, metadata_for, "
                      "resolve_locale, style_from, custom_from, format_reset_time on 6 zones) equal" % len(done["cases"]))


class CheckDiff(Leaves):
    def test_checks_of_a_persons_words(self):
        done = self.family(CHECKS, label="continuation-checks", expect_ops=100)
        texts = done["results"][0]["ok"]
        RECORD.append("continuation checks: %d cases (validate_custom/prompt/continuation, %d product texts of every "
                      "language, the command line, coerce_by_thread, _fill) equal" % (len(done["cases"]), len(texts)))
