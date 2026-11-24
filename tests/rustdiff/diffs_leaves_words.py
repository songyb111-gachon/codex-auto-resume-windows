"""S1.1, car-words: the 22 catalogs, the language choice, the direction marks and the usage sentences.

* CatalogsDiff - what Rust embeds is the tag's catalog, text for text, for each of the 22 languages; `catalog()` (English
  under the locale's own entries, in the order a dict keeps) and `messages()` are the tag's, key for key.
* FormatDiff - l10n's formatting of every key in all 22 languages with the placeholders filled (and with the
  placeholders filled by values that carry another placeholder, which the sequential `str.replace` of `fill` treats in
  its own order, and with nothing supplied).
* ChoiceDiff - `normalize`, `resolve`, `from_system`, `preferred_languages` and `set_preference` over tags and
  environments; the Windows languages are handed in, as the platform will hand them.
* BidiDiff - the first-strong class of every code point, and `embedded` over strings in each right-to-left language.
* WordsDiff - ui/words.py: `countdown`, `age`, `window_name`, `share`, `left`, `clock_time`, `usage_windows`,
  `usage_line` in every language.
"""
from __future__ import annotations

import json

from rustdiff import core, reference
from rustdiff.leaves import Leaves

RECORD: list[str] = []


class CatalogsDiff(Leaves):
    def test_catalogs(self):
        script = r'''
from pathlib import Path
from codex_auto_resume import l10n
cases = []
for locale in l10n.LOCALES:
    cases += [["words.catalog_text", locale], ["words.catalog", locale], ["words.messages", locale]]
cases += [["words.catalog", "xx"], ["l10n.available"], ["l10n.offered_endonyms"]]
ops = {"words.catalog_text": lambda locale: (Path(l10n.DIRECTORY) / (locale + ".json")).read_text(encoding="utf-8"),
       "words.catalog": lambda locale: l10n.catalog(locale), "words.messages": l10n.messages,
       "l10n.available": lambda: list(l10n.available()), "l10n.offered_endonyms": l10n.offered_endonyms}
finish(cases, ops)
'''
        done = self.family(script, label="catalogs", chunk=3)
        keys = sum(len(result["ok"]) for case, result in zip(done["cases"], done["results"])
                   if case[0] == "words.catalog" and "ok" in result)
        RECORD.append("catalogs: the 22 embedded files equal the tag's text for text; catalog() and messages() equal key for "
                      "key and in order (%d entries)" % keys)


class FormatDiff(Leaves):
    def test_every_key_in_every_language(self):
        script = r'''
from codex_auto_resume import l10n
samples = ["7", "x", "name \u00e9", 3.5, 12, "0.6.26-beta.2", "\u05d0\u05d1", "3:05"]
cases = []
for locale in l10n.LOCALES:
    for key, value in l10n.catalog(locale).items():
        names = sorted(l10n.placeholders(value))
        fields = {name: samples[(sum(map(ord, name)) + len(key)) % len(samples)] for name in names}
        cases.append(["words.text", key, locale, fields])
        if len(names) > 1:
            cases.append(["words.text", key, locale, {name: "{%s}" % names[(at + 1) % len(names)]
                                                       for at, name in enumerate(reversed(names))}])
        if names:
            cases.append(["words.text", key, locale, {}])
            cases.append(["words.text", key, locale, dict(fields, extra="zzz", **{names[0]: "{extra}"})])
cases += [["words.text", "no.such.key", "en", {}], ["words.text", "no.such.key", "ko", {"n": 1}]]
english = l10n.catalog("en")
first = next(iter(english))
cases += [["words.text", first, "xx", {}], ["words.text", first, "", {}], ["words.text", first, "EN", {}]]
for value in list(english.values()) + ["", "{", "}", "{}", "{a}", "{{a}}", "{a}}", "{{a}", "{A}", "{_}", "{a1_}", "{1a}", "{a b}", "{a.b}",
                                       "x{a}y{b}z{a}", "{\u00e9}", "{a\n}", "\u0661{a}"]:
    cases.append(["words.placeholders", value])
cases += [["words.fill", "{a}{b}", {"a": "{b}", "b": "x"}], ["words.fill", "{a}{b}", {"b": "x", "a": "{b}"}], ["words.fill", "{a}", {"a": 5}],
          ["words.fill", "{a}", {"a": 1.5}], ["words.fill", "{a}", {"a": None}], ["words.fill", "{a}", {"a": True}], ["words.fill", "", {"a": 1}],
          ["words.fill", "{a}{a}{a}", {"a": "ab"}]]
ops = {"words.text": lambda key, locale, fields: l10n.text(key, locale, **fields),
       "words.placeholders": lambda value: sorted(l10n.placeholders(value)),
       "words.fill": lambda value, fields: l10n.fill(value, **fields)}
finish(cases, ops)
'''
        done = self.family(script, label="format", chunk=3000)
        texts = [case for case in done["cases"] if case[0] == "words.text"]
        RECORD.append("format: %d formatted strings (every key of all 22 catalogs, placeholders filled; filled by braced values; "
                      "nothing supplied) and %d placeholder scans equal the tag's"
                      % (len(texts), len(done["cases"]) - len(texts)))


class ChoiceDiff(Leaves):
    def test_language_choice(self):
        script = r'''
import os
from codex_auto_resume import l10n
rng = random.Random(7)
tags = ["ko", "ko-KR", "ko_KR", "KO", " ko ", "zh", "zh-CN", "zh-Hans-CN", "zh-Hant", "zh-TW", "zh-HK", "zh-MO", "zh-SG", "zh_Hant_TW", "zh-Latn",
        "pt", "pt-PT", "pt-BR", "es-419", "es-MX", "in", "iw", "id", "he", "ar-EG", "fa-IR", "de-AT", "fr-CA", "ru-KZ", "en-US", "en", "EN-gb",
        "tl", "xx", "", " ", "-", "--", "_", "ko--KR", "-ko", "\u00e9", "\u0130", "ko\u00a0", "\u3000ko\u3000", "C", "POSIX", "und", "i-klingon",
        "ZH-hant", "zh-HANT-hk", "th", "hu-HU", "cs", "uk-UA", "vi-VN", "tr-TR", "pl", "it-IT", "ja-JP", "sr-Latn", "nb", "nn", None, 5, ["ko"], {}, True]
cases = []
for tag in tags:
    cases.append(["l10n.normalize", tag])
for tag in tags:
    for preference in [tag]:
        cases.append(["l10n.resolve", preference, {}, ["de-DE"]])
        cases.append(["l10n.resolve", preference, {}, []])
envs = [{}, {"CODEX_AUTO_RESUME_LANG": "ja"}, {"CODEX_AUTO_RESUME_LANG": "  "}, {"CODEX_AUTO_RESUME_LANG": " fr_CA "}, {"CODEX_AUTO_RESUME_LANG": "xx"},
        {"LC_ALL": "de_DE.UTF-8"}, {"LC_ALL": "C", "LC_MESSAGES": "es_ES"}, {"LC_ALL": "POSIX", "LC_MESSAGES": " ", "LANG": "ko_KR.eucKR"},
        {"LANG": "pt_BR"}, {"LANG": ""}, {"LANG": "zh_TW.UTF-8"}, {"CODEX_AUTO_RESUME_LANG": "ko", "LANG": "de"}, {"LANG": ".UTF-8"}, {"LANG": "xx_YY"}]
windows = [[], ["ko-KR"], ["xx", "ko"], ["en-US", "de-DE"], ["zh-Hans-CN"], ["pt-PT", "en"], [""], ["fa-IR"], ["he-IL"], ["iw"], ["ar"]]
for env in envs:
    for win in windows:
        cases += [["l10n.preferred_languages", env, win], ["l10n.from_system", env, win]]
        for preference in [None, "system", "", "  ", "ko", "en", "xx", "SYSTEM", "zh-Hant", " ja "]:
            cases.append(["l10n.resolve", preference, env, win])
for value in ["ko", "system", "xx", "", None, 5, "KO", "zh-TW", "zh", " ko", "pt-BR", "th"]:
    for env in envs[:4]:
        cases.append(["l10n.set_preference", value, env, ["de"]])
        cases.append(["l10n.set_preference", value, env, []])
def patched(call):
    def run(*args):
        env, win = args[-2], args[-1]
        l10n._windows_preferred = lambda: list(win)
        return call(*args[:-2], env)
    return run
def set_preference(value, env, win):
    l10n._windows_preferred = lambda: list(win)
    saved = dict(os.environ)
    os.environ.clear()
    os.environ.update(env)
    try:
        now = l10n.set_preference(value)
    finally:
        os.environ.clear()
        os.environ.update(saved)
    return [now, l10n.preference()]
ops = {"l10n.normalize": l10n.normalize,
       "l10n.preferred_languages": patched(lambda env: l10n.preferred_languages(env)),
       "l10n.from_system": patched(lambda env: l10n.from_system(env)),
       "l10n.resolve": lambda pref, env, win: patched(lambda e: l10n.resolve(pref, e))(env, win),
       "l10n.set_preference": set_preference}
finish(cases, ops)
'''
        done = self.family(script, label="choice")
        RECORD.append("choice: %d cases of normalize, resolve, from_system, preferred_languages, set_preference equal the tag's"
                      % len(done["cases"]))


class BidiDiff(Leaves):
    def test_first_strong_and_embedded(self):
        script = r'''
import unicodedata
from codex_auto_resume import l10n
strings = ["", "0.6.26", "abc", "\u05d0bc", "\u0627\u0644\u0639", "123 \u05d0", "(1) \u0627", "-.:/", "\u202aa", "\U0001f600", "\u0661\u0662", "\u00e9",
           "C:\\Users\\x", "0a1b2c3d-0001-7000-8000-000000000001", "\u0710", "\u07c0", "\u200f\u05d0", "\u200ea", "\u2067x\u2069", "1.5", "\ufb1d", "\U00010800", "\U0001e900", "\u0600\u0627"]
cases = []
for value in strings + [5, 1.5, True, None, 10 ** 30]:
    cases.append(["l10n.first_strong", value])
    for locale in l10n.LOCALES:
        cases.append(["l10n.embedded", value, locale])
cases += [["l10n.embedded", "x", "xx"], ["l10n.embedded", "x", None], ["l10n.right_to_left", "ar"], ["l10n.right_to_left", "xx"], ["l10n.right_to_left", None]]
for locale in l10n.LOCALES:
    cases.append(["l10n.right_to_left", locale])
cases.append(["bidi.classes"])
def classes():
    out = []
    for point in range(0x110000):
        if 0xD800 <= point < 0xE000:
            out.append("-")
            continue
        kind = unicodedata.bidirectional(chr(point))
        out.append("L" if kind == "L" else "R" if kind in ("R", "AL") else "-")
    return "".join(out)
ops = {"l10n.first_strong": l10n.first_strong, "l10n.embedded": l10n.embedded, "l10n.right_to_left": l10n.right_to_left, "bidi.classes": classes}
finish(cases, ops)
'''
        done = self.family(script, label="bidi")
        RECORD.append("bidi: the first-strong class of all 1114112 code points and %d embedded/first_strong/right_to_left cases "
                      "equal the tag's" % (len(done["cases"]) - 1))


class WordsDiff(Leaves):
    def test_ui_words(self):
        script = r'''
import time
from codex_auto_resume import l10n
from codex_auto_resume.ui import words
def say_for(locale):
    return lambda key, **fields: l10n.text(key, locale, **fields)
cases = []
seconds = [0, 1, 4, 5, 59, 60, 61, 3599, 3600, 3661, 86399, 86400, 90000, 400000, 12345678, -1, -100, 0.5, 4.99, 59.99, 724.9, 11100, True, False, 10 ** 12, None, [1], {}]
for value in seconds:
    cases.append(["words.countdown", value])
    for locale in l10n.LOCALES:
        cases.append(["words.age", value, locale])
minutes = [None, 0, -5, 1, 30, 59, 60, 90, 120, 300, 1440, 2880, 4320, 10080, 10081, 20160, 43200, 1.5, True, "60", [60], 100800]
for value in minutes:
    for locale in l10n.LOCALES:
        cases.append(["words.window_name", value, locale])
windows = [{}, {"used_percent": 0}, {"used_percent": 0.0}, {"used_percent": 1}, {"used_percent": 12.5}, {"used_percent": 49.99}, {"used_percent": 99.6}, {"used_percent": 99.999}, {"used_percent": 100},
           {"used_percent": 100.0}, {"used_percent": 100.5}, {"used_percent": 250}, {"used_percent": -0.5}, {"used_percent": -5}, {"used_percent": None}, {"used_percent": True},
           {"used_percent": "5"}, {"used_percent": [5]}, {"used_percent": 1e-9}, {"used_percent": 89.9}, {"used_percent": 90}, {"used_percent": 10 ** 30}, 5, None, []]
for window in windows:
    cases += [["words.share", window], ["words.left", window]]
now = 1700000000.0
stamps = {}
def stamp(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        local = time.localtime(value)
        stamps[repr(float(value))] = [local.tm_year, local.tm_mon, local.tm_mday, local.tm_hour, local.tm_min]
for moment in [now, now + 60, now + 3600 * 5, now + 86400, now + 86400 * 3 + 17, now + 86400 * 400, now - 5, 1700003000, 1700003000.5, 946684800.0]:
    stamp(moment)
reading_windows = [[], None, [{"window_minutes": 300, "used_percent": 12.5, "reset_at": now + 3600 * 3}],
                   [{"window_minutes": 10080, "used_percent": 99.6, "reset_at": now + 86400 * 3 + 17}],
                   [{"window_minutes": 300, "used_percent": 40, "reset_at": None}, {"window_minutes": 10080, "used_percent": 5, "reset_at": now + 86400}],
                   [{"window_minutes": None, "used_percent": 100, "reset_at": now + 60}], [{"window_minutes": 45, "used_percent": 0, "reset_at": 1700003000.5}],
                   [{"window_minutes": 1440, "used_percent": 3.3, "reset_at": now + 86400 * 400}], [{"window_minutes": 120, "used_percent": 7, "reset_at": 946684800.0}],
                   [{"window_minutes": 300, "used_percent": 50}], 5]
for listed in reading_windows:
    for each in listed if isinstance(listed, list) else []:
        stamp(each.get("reset_at"))
for locale in l10n.LOCALES:
    for listed in reading_windows:
        for keep in (False, True):
            cases.append(["words.usage_windows", listed, locale, keep])
            cases.append(["words.usage_line", {"windows": listed, "read_at": now - 125} if listed is not None else {"windows": None, "read_at": now}, locale, keep])
    for reading in [None, {}, {"windows": reading_windows[2]}, {"read_at": now}, {"windows": reading_windows[2], "read_at": 0}, [], 5,
                    {"windows": reading_windows[2], "read_at": now - 3}, {"windows": reading_windows[2], "read_at": now - 90000},
                    {"windows": reading_windows[4], "read_at": now + 50}]:
        cases.append(["words.usage_line", reading, locale, locale in l10n.RIGHT_TO_LEFT])
tm_pairs = [(now, now), (now + 60, now), (now + 86400, now), (now - 5, now), (now + 86400 * 400, now), (946684800.0, now)]
for moment, today in tm_pairs:
    cases.append(["words.clock_time", moment, today])
ops = {"words.countdown": words.countdown,
       "words.age": lambda value, locale: words.age(value, say_for(locale)),
       "words.window_name": lambda value, locale: words.window_name(value, say_for(locale)),
       "words.share": words.share, "words.left": words.left}
# The Rust side takes `now` and the broken-down local times as arguments: what the platform will hand it.
for case in cases:
    if case[0] in ("words.usage_windows", "words.usage_line"):
        case += [now, stamps]
    elif case[0] == "words.clock_time":
        case[:] = [case[0], [stamps[repr(float(case[1]))][i] for i in range(5)], [stamps[repr(float(case[2]))][i] for i in range(5)], case[1], case[2]]
ops["words.clock_time"] = lambda tm_at, tm_today, at, today: words.clock_time(at, today)
ops["words.usage_windows"] = lambda listed, locale, keep, now_, table: words.usage_windows(listed, say_for(locale), now_, (lambda value: l10n.embedded(value, locale)) if keep else None)
ops["words.usage_line"] = lambda reading, locale, keep, now_, table: words.usage_line(reading, say_for(locale), now_, (lambda value: l10n.embedded(value, locale)) if keep else None)
finish(cases, ops)
'''
        done = self.family(script, label="words", chunk=3000)
        RECORD.append("ui words: %d cases of countdown, age, window_name, share, left, clock_time, usage_windows, usage_line "
                      "in every language equal the tag's" % len(done["cases"]))
