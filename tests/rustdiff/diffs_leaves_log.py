"""S1.1, car-config's logbook (`logbook.py`): the lines, `skipped`, `format_local`, `tail` and the log file, held to the tag.

* LineDiff - `render` for every (state or code, reason) pair the tag has words for, each with a conversation id or none and
  a detail of each kind (an interruption hash, a count of seconds, text, a number); `skipped` for every reason; and
  `format_local` over the moments the system can and cannot say. The local time zone is the platform's, so each case
  carries the offset the reference's own `astimezone()` found for it, which is what car-platform will hand Rust.
* FileDiff - the log file: lines through `EngineLog` and `logger.info` written by both and compared by length and SHA-256
  file by file: the stamp, the mark, `\\r\\n` ends, rotation at a million bytes (one file, then six, the sixth dropped), the skip
  lines a watcher before this one wrote, said once; and `tail`.
"""
from __future__ import annotations

import json
from pathlib import Path

from rustdiff import reference
from rustdiff.diffs_leaves_config import ConfigBase, ENV
from rustdiff.leaves import Leaves

RECORD: list[str] = []


class LineDiff(Leaves):
    def test_render_skipped_format_local(self):
        script = r'''
from datetime import datetime, timezone
from codex_auto_resume import logbook
def offset_for(value):
    try:
        moment = datetime.fromtimestamp(float(value), timezone.utc).astimezone()
        return int(moment.utcoffset().total_seconds())
    except Exception:
        return None
def moment_of(detail):
    shown = str(detail) if isinstance(detail, (int, str)) and not isinstance(detail, bool) else None
    return shown if shown and shown.isascii() and shown.isdigit() and len(shown) < 13 else None
uuid = "0a1b2c3d-0001-7000-8000-000000000001"
cases = []
moments = [0, 1, -1, -0.5, 0.4, 0.9999996, 59.5, 1700000000, 1700000000.5, 1700000000.9999996, 2 ** 31, 32536799999, 32536799999.6, 32536800000, 1e18,
           True, False, "12", "1.5e3", "x", None, [1], {}, 10 ** 30, 253402300799]
for value in moments:
    cases.append(["logbook.format_local", value, offset_for(value)])
details = [None, "", "abc123", "0123456789abcdef", "f" * 64, "f" * 65, "1700000000", "17000000001", "1" * 12, "1" * 13, "12345678901234", "x" * 70, "G", 5, 1700000001, 1.5,
           True, [1], "-5", " 5", "١٢", "5\n", "0", "000"]
pairs = [(code, reason) for (code, reason) in logbook._MESSAGES]
codes = sorted({code for code, _ in pairs}) + ["unknown_code", "", "x" * 40, 5]
reasons = [None, "", "desktop_app_unavailable", "queue_process_not_started", "some reason", "x" * 81, "é", "A_b9", 5, ["a"]]
for code, reason in pairs:
    for thread in (uuid, None):
        for detail in details[:12]:
            seconds = moment_of(detail)
            cases.append(["logbook.render", thread, code, reason, detail, offset_for(int(seconds)) if seconds else None])
for code in codes:
    for reason in reasons:
        for detail in details:
            seconds = moment_of(detail)
            cases.append(["logbook.render", uuid if reason in (None, "") else "not-a-uuid", code, reason, detail, offset_for(int(seconds)) if seconds else None])
for thread in (uuid, None, "x", 5, "0A1B2C3D-0001-7000-8000-000000000001"):
    for turn in (uuid, None, "t", 5):
        for reason in list(logbook.SKIP_WORDS) + [None, "x", "other", 5, ["a"], ""]:
            for kind in (None, "vscode", "a b.c-d_e", "x" * 49, "x" * 48, "", "bad!", 5):
                cases.append(["logbook.skipped", thread, turn, reason, kind])
ops = {"logbook.format_local": lambda value, offset: logbook.format_local(value),
       "logbook.render": lambda thread, code, reason, detail, offset: logbook.render(thread, code, reason, detail),
       "logbook.skipped": logbook.skipped}
finish(cases, ops)
'''
        done = self.family(script, label="lines", chunk=3000)
        shown = sum(1 for case, result in zip(done["cases"], done["results"]) if case[0] == "logbook.format_local" and result.get("ok") != "unknown-time")
        RECORD.append("logbook lines: %d cases of render (every pair the log has words for, every kind of detail), skipped and format_local "
                      "(%d moments the system can say) equal the tag's" % (len(done["cases"]), shown))


class FileDiff(ConfigBase):
    def test_the_log_file(self):
        from rustdiff.diffs_leaves_machine import generator
        states = generator("gen_vocab").vocabulary(reference.TAG)["modules"]["domain.states"]["constants"]["STATES"]
        uuid = "0a1b2c3d-0001-7000-8000-000000000001"
        other = "0a1b2c3d-0001-7000-8000-000000000002"
        engine = []
        for state in states:
            engine += [[uuid, state, "usage_unavailable"], [uuid, state, None], [None, state, "x" * 90]]
        engine += [[uuid, "usageLimitExceeded_detected", "ab" * 32], [uuid, "reset_expected", "1700000000"], [uuid, "reset_unknown_conservative_poll", "300"],
                   [uuid, "queue_receipt_exit_nonzero", "7"], [uuid, "held_after_sleep", "3"], [uuid, "power_failed", "5"], [None, "unknown_event", "abc"],
                   [uuid, "failed_turns_seen", 4], [uuid, "needs_you_notice", "0123456789abcdefghij"], [uuid, "once_words_sent", None]]
        skips = []
        for index in range(4):
            skips += [[uuid, "not_taken_up", [other, "newer_turn", None]], [uuid, "not_taken_up", [other, "newer_turn", "x"]],
                      [uuid, "not_taken_up", [uuid, "category_off", "vscode"]], [None, "not_taken_up", ["t", "other_kind", None]],
                      [uuid, "not_taken_up", [other, "unknown_conversation", "a b"]]]
        small = engine + skips + [["info", "plain line"], ["info", "é中 percent %s 100%"], ["info", ""], ["info", "x" * 400]]
        many = [["info", "line %05d " % index + "y" * 100] for index in range(12000)]
        endless = [["info", "line %06d " % index + "z" * 110] for index in range(70000)]
        now0, step = 1700000000.0, 0.75
        seeded_lines = ("[2026-11-20 10:00:00] thread %s: failed turn %s not taken up (newer_turn): a newer turn came after it\r\n"
                        "[2026-11-20 10:00:01] thread %s: failed turn %s not taken up (category_off: vscode): recovery of this kind is turned off in Settings\r\n"
                        "[2026-11-20 10:00:02] failed turn t not taken up (other_kind): its conversation is not a desktop conversation of a person's own\r\n"
                        % (uuid, other, uuid, uuid))

        def tree(root: Path):
            (root / "seeded").mkdir()
            (root / "seeded" / "auto-resume.log.1").write_bytes(seeded_lines.encode("utf-8"))
            (root / "seeded" / "auto-resume.log").write_bytes(("[2026-11-21 10:00:00] noise\r\n" * 3).encode("utf-8"))
            (root / "nearly").mkdir()
            (root / "nearly" / "auto-resume.log").write_bytes(b"x" * 999_900)
            (root / "tails").mkdir()
            (root / "tails" / "a.log").write_bytes("one\r\ntwo\nthree\r\né four\nfive".encode("utf-8"))
            (root / "tails" / "bad.log").write_bytes(b"ok\n\xff\xfe broken\n")
        # (a "@/" in a file name is replaced by the side's root)
        template = []
        for folder, events in (("fresh", small), ("seeded", skips + [["info", "after"]]), ("nearly", [["info", "a line that takes the file past the cap"], ["info", "next"]]),
                               ("many", many)):
            for mark in ("", "[health] ", "100% "):
                template.append(["logbook.write", "@/%s-%s/auto-resume.log" % (folder, "m" if mark else "n") if folder in ("fresh", "many") else "@/%s/auto-resume.log" % folder,
                                 mark, states, events, now0, None, step])
        template.append(["logbook.write", "@/endless/auto-resume.log", "", states, endless, now0, None, step])
        for name, count in (("a.log", 2), ("a.log", 0), ("a.log", -3), ("a.log", 99), ("a.log", 5), ("bad.log", 5), ("nothing.log", 3)):
            template.append(["logbook.tail", "@/tails/" + name, count])
        # the offset the reference's astimezone() finds is the zone's offset on this PC; ask it, once
        probe = reference.run("import json, sys\nfrom datetime import datetime, timezone\nsys.stdout.write(json.dumps(int(datetime.fromtimestamp(float(sys.argv[1]), timezone.utc).astimezone().utcoffset().total_seconds())))",
                              str(now0), profile=self.profile("probe"))
        offset = json.loads(probe.stdout)
        for case in template:
            if case[0] == "logbook.write":
                case[6] = offset
        expected = self.pair("log", template, tree=tree)
        written = [result["ok"] for case, result in zip(template, expected) if case[0] == "logbook.write"]
        rotated = max(len(files) for files in written)
        self.assertEqual(rotated, 6, "the endless run reaches the sixth file: %s" % rotated)
        RECORD.append("logbook file: %d runs of EngineLog and logger.info (every state, skips said once, a log seeded by an earlier watcher, one at 999,900 "
                      "bytes, 12,000 and 70,000 lines through the 1,000,000-byte rotation to the %d files RotatingFileHandler keeps), and tail, "
                      "equal the tag's file by file in length and SHA-256" % (len(template) - 7, rotated))
