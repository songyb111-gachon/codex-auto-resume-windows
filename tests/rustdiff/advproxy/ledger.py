"""The per-file table of the advanced proxy (owner Q3 (c)): every `advanced/tests/test_*.py` of the reference tag, and
whether it runs green on Rust through the proxy - or what it waits for.

    python -X utf8 tests/rustdiff/advproxy/ledger.py [--tag v0.6.26] [--markdown] [--seat S7.2b]
    python -X utf8 tests/rustdiff/advproxy/ledger.py --run test_advanced_x.py ... [--debug]

A file is

* **green on Rust** - in GREEN below: it passed on the proxy lane (CODEX_AR_CORE=rust, the advanced lane's path) as on
  the reference lane, test by test, and reached car-adv (its calls to advserve counted), and every name it imports is
  forwarded, handed or data (table.py);
* **ready** - nothing it imports waits, but no run has put it in GREEN yet (`--run` it);
* **waits for <seat>** - it imports a module (or a name of a module) table.py has not forwarded: the latest of their
  seats in the waves (P7-DESIGN 2.3) is the one that unlocks it; the C# page (`pagecase.py`) is S6.2a's window and
  runs on the reference only, as do the files retired by D8.

`--run` runs each file named, one process at a time, on both lanes through scripts/test_parts.py's worker, compares
the outcomes test by test and prints the counts of calls it made to advserve - what a seat pastes into GREEN. `--run`
with no file runs every GREEN file and every "ready" one and ends with the count of GREEN. GREEN only grows; a file
leaves it only with the row of table.py that put it there.

Both lanes run on the reference's Python (Integration 10): the product's bundled embeddable 3.14.10 by default, as every
diff of tests/rustdiff does (refpython.py; `--reference-python bundled|system|PATH`, or CODEX_AR_REFERENCE_PYTHON). The
embeddable runtime ignores PYTHONPATH, so the lane's folders (this tree, `src`, `advanced/src`) reach the worker through
`refpython.script_command`'s boot; PYTHONPATH is still set for an installed interpreter and for what a test starts.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))
from rustdiff import refpython  # noqa: E402 - the reference's Python, which both lanes run on


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


table = _load("rustdiff_advproxy_table", HERE / "table.py")
advledger = _load("rustdiff_advledger_s72a", HERE.parent / "advledger_s72a.py")

# Proved green on Rust (`--run`: both lanes pass test by test, calls to advserve made), with the seat whose rows did it.
GREEN = {
    "test_advanced_keep_on_every.py": "S7.2a3 (runtime, state, arming)",
    "test_advanced_arming.py": "S7.2a3 (runtime, state, arming; patched state methods through `faults`)",
    "test_advanced_autocheck.py": "S7.2a3 (runtime)",
    "test_advanced_state_v4.py": "S7.2a3 (state)",
    "test_advanced_window_switches.py": "S7.2a3 (state)",
    "test_advanced_requires.py": "S7.2a3 (runtime, arming)",
    "test_advanced_registry.py": "S7.2a3 (runtime; the registry's own rules wait for their forwarder)",
    # Integration 10's bare --run on the bundled 3.14.10: two of the "ready" files, green through S7.2a3's rows
    "test_advanced_agent_thread_trigger.py": "Integration 10 (runtime, state, arming)",
    "test_advanced_package.py": "Integration 10 (runtime, state, arming)",
    "test_advanced_words_v019.py": "S7.3a (surfaces: advanced-words, the statement)",
    "test_advanced_account_card_findings.py": "S7.3a2 (surfaces: the account cards; `control` is data)",
    "test_advanced_autoswitch_control.py": "S7.3a2 (the saved accounts' commands through surfaces.bridge)",
    # proxy2 (completion part 1): "a build of version N" - the patched SCHEMA_VERSION, TABLES and the opening's
    # statements reach car-adv's `state::builds` for the call they are patched in (test-only, empty in the product)
    "test_advanced_state_v5.py": "proxy2 (state; state::builds for the patched SCHEMA_VERSION; NaN across the pipe)",
    "test_advanced_state_v6.py": "proxy2 (state; state::builds)",
    "test_advanced_state_v7.py": "proxy2 (state; state::builds)",
    "test_advanced_schema_v8.py": "proxy2 (state; state::builds: SCHEMA_VERSION, TABLES, UPGRADE_TO_V019, FREE_WORDINGS, "
                                  "MARKED)",
    "test_advanced_state_options.py": "proxy2 (state; state::builds; a get-only registry handed what it answers)",
    "test_advanced_every_conversation.py": "proxy2 (runtime through core's engine proxy with the test's plug, proxyplug.rs)",
    "test_advanced_usage_refusal.py": "proxy2 (arming.standing, arming.warnings_for: advserve op)",
    "test_advanced_hidden.py": "proxy2 (registry.offered: advserve op)",
    # proxy2 part 2: the forced stop on car-adv (usage_pause's world asked of the test, its answers JSON; the stop's
    # `notices` and `holding` through advserve `code_call`)
    "test_advanced_stop_held_windows.py": "proxy2 part 2 (UsageStop through its world; RustCode.holding)",
    "test_advanced_usagestop_archive_grace.py": "proxy2 part 2 (UsageStop; RustCode.notices)",
    "test_advanced_usagestop_carry_held.py": "proxy2 part 2 (UsageStop and ResetMessage through their worlds)",
    "test_advanced_usagestop_continue_off.py": "proxy2 part 2 (UsageStop through its world)",
    "test_advanced_usagestop_continue_turned_off.py": "proxy2 part 2 (UsageStop through its world)",
    "test_advanced_usagestop_reset_message.py": "proxy2 part 2 (UsageStop and ResetMessage through their worlds)",
    "test_advanced_reset_message_counting_held.py": "proxy2 part 2 (ResetMessage and UsageStop through their worlds)",
    # no advanced code reached (NO_CODE): both lanes pass test by test
    "test_advanced_korean_words.py": "proxy2 part 2 (no advanced code: NO_CODE)",
    "test_advanced_statement_programs.py": "proxy2 part 2 (no advanced code: NO_CODE)",
    "test_advanced_usage_word_split.py": "proxy2 part 2 (no advanced code: NO_CODE)",
    "test_advanced_words_late.py": "proxy2 part 2 (no advanced code: NO_CODE)",
    "test_advanced_notice_kinds.py": "proxy2 part 2 (no advanced code: NO_CODE)",
    "test_advanced_statement_stopped_route.py": "proxy2 part 2 (no advanced code: NO_CODE)",
}

# What a run found that the imports cannot say (`--run`): the seat or the reason a file still waits for, each with
# the tests that hold it. A file leaves this only into GREEN.
RUN_WAITS = {
    "test_advanced_goal_verified_resets.py": ("S7.2e1", "the shipped goal_continuation's code: car-adv's make "
                                              "table gives none until S7.2e1 (registry.make is forwarded)"),
    "test_advanced_hook_claim.py": ("P11 host", "P11 (`claim_ledger`) runs on core's own SQLite connection, in "
                                    "core's process: the integrated host (S7.3d), not a second process"),
    "test_advanced_ledger.py": ("P11 host", "the claim ledger on core's connection (`state._open`, `claim`)"),
    "test_advanced_state.py": ("P11 host", "AttachTests and RecordTests attach the file to core's connection "
                               "(`state._open`); the other 61 tests are green through the proxy"),
    "test_advanced_admission.py": ("P11 host", "core's engine proxy now carries the plug (car-harness proxyplug.rs) and "
                                   "AskStore has reserve_record/record_guard: 23 of 23 green with CODEX_AR_ADVPROXY=0; "
                                   "through the proxy 21 of 23 - EngineCase's two claim tests reach Runtime.claim (P11)"),
    "test_advanced_measure_m4b.py": ("S7.4", "reaches no forwarded code: the measurement table's words"),
    # S7.3a's --run (debug advserve, bundled 3.14.10): what still holds each file of the surfaces' row
    "test_advanced_surfaces.py": ("S7.3a", "29 of 34 equal; the one-shot bridge's two (core's controlcli stub), "
                                  "test_nothing_the_mcp_surface_reaches_can_arm (a Python patch of Arming.arm car-adv "
                                  "cannot see) and two ResetBridgeTests that patch control.sendnow.wake"),
    "test_advanced_watch_log.py": ("S7.3a", "18 of 20 equal; the two patch runtime.state.journal/arming to raise on the "
                                   "state proxy, which watchlog's own reads in car-adv do not consult (`faults`)"),
    "test_advanced_keep_on.py": ("S7.3a", "the send-again and reinstall tests drive core's engine and the claim (P11 host)"),
    "test_advanced_rows.py": ("S4.2 proxy", "no call reached advserve: the tests build core's Store and a LocalSource "
                              "of their own and hand them to rows(store=, source=) (the reference's, by design) or "
                              "core's engine proxy, which needs car-harness built"),
    "test_advanced_prompt_queue.py": ("S4.2 proxy", "drives core's Engine (car-harness's serve, not built in the seat's tree)"),
    "test_advanced_prompt_edit.py": ("S4.2 proxy", "as test_advanced_prompt_queue"),
    "test_advanced_queue_held.py": ("S4.2 proxy", "as test_advanced_prompt_queue"),
    "test_advanced_go_on_window.py": ("S4.2 proxy", "as test_advanced_prompt_queue"),
    "test_advanced_prompt_clear.py": ("S4.2 proxy", "as test_advanced_prompt_queue"),
    # S7.3a2's --run (debug advserve, bundled 3.14.10)
    "test_advanced_conversations.py": ("S7.2c", "6 of 12 differ with the card's forwarder off too: they patch "
                                       "codex.inuse.home and read codex.threads, which wait for their rows"),
    "test_advanced_analytics.py": ("S7.2e2", "17 of 23 equal; the six AggregationTests patch the card's _homes, "
                                   "_source and _recent (the reference's card answers them) over engine.analytics and "
                                   "codex.tokens, which wait for their rows"),
    "test_advanced_power_tasks.py": ("S7.2e2", "23 of 24 equal; AnswerTests.test_only_an_armed_capability_is_asked_and_"
                                     "taken drives engine.powertasks' P21 answer, which waits for its row"),
    "test_advanced_manual_switch.py": ("S7.3d", "16 of 17 equal; test_the_bridge_command hands Python stand-ins for the "
                                       "switch the Rust bridge reaches through surfaces::World (the bare world here)"),
    "test_advanced_autoswitch_delete_pending.py": ("S7.2b", "reaches no advserve call: codex.swap and profiles' own "
                                                   "functions wait for their rows"),
    # proxy2 part 2: the files whose one red test is a send of a plug record (P11 at reserve_record)
    "test_advanced_go_on_series.py": ("P11 host", "its send is a plug record: core's reserve_record asks the plug's ledger (P11, `Runtime.claim`), which runs on core's own connection in core's process - the integrated host (S7.3d); every test before the send is green through the proxy"),
    "test_advanced_prompt_command_line.py": ("P11 host", "its send is a plug record: core's reserve_record asks the plug's ledger (P11, `Runtime.claim`), which runs on core's own connection in core's process - the integrated host (S7.3d); every test before the send is green through the proxy"),
    "test_advanced_self_check_handed.py": ("P11 host", "its send is a plug record: core's reserve_record asks the plug's ledger (P11, `Runtime.claim`), which runs on core's own connection in core's process - the integrated host (S7.3d); every test before the send is green through the proxy"),
    "test_advanced_empty_response_own.py": ("P11 host", "its send is a plug record: core's reserve_record asks the plug's ledger (P11, `Runtime.claim`), which runs on core's own connection in core's process - the integrated host (S7.3d); every test before the send is green through the proxy"),
    "test_advanced_usagestop_hold_ends.py": ("P11 host", "its send is a plug record: core's reserve_record asks the plug's ledger (P11, `Runtime.claim`), which runs on core's own connection in core's process - the integrated host (S7.3d); every test before the send is green through the proxy"),
    "test_advanced_usagestop_carry_other_window.py": ("P11 host", "its send is a plug record: core's reserve_record asks the plug's ledger (P11, `Runtime.claim`), which runs on core's own connection in core's process - the integrated host (S7.3d); every test before the send is green through the proxy"),
    "test_advanced_subagent_told_at_send.py": ("P11 host", "its one test's send is a plug record: reserve_record asks "
                                               "the plug's ledger (P11, `Runtime.claim`) and is held"),
    "test_advanced_goal_set_race.py": ("S7.2e1", "goal_continuation's world is asked its goal (usage_limited) but car-adv "
                                       "asks neither M2b nor the session, so the set is not made: trace "
                                       "GoalContinuation.unloaded/route against the reference (proxy2 part 2)"),
    "test_advanced_examples.py": ("S7.1b", "statement's Catalogs (`words`, `own`, `text`, `badge`): its forwarder "
                                  "waits - proxy2 part 2's try turned hidden and registry red (`badge` takes a count, "
                                  "the catalogs' dump needs its pairs decoded) and was taken back"),
    "test_advanced_shots_render.py": ("S6.2a", "the Advanced page drawn offscreen by the C# window (a GUI set, "
                                      "gui_lock.sh): the window's seat; a proxy seat runs no GUI test"),
}

# Files that reach no advanced code at all - catalogs' files read as data, core's own words - and so prove nothing of
# car-adv: GREEN when both lanes pass test by test, with no call to advserve asked of them.
NO_CODE = {
    "test_advanced_korean_words.py": "the Korean catalog's file, read as data",
    "test_advanced_usage_word_split.py": "every catalog's file, read as data",
    "test_advanced_words_late.py": "the catalogs' files, read as data",
    "test_advanced_statement_programs.py": "statement.DIRECTORY's files, read as data",
    "test_advanced_notice_kinds.py": "core's notice kinds and notifier; the plug is made, no runtime is asked",
    "test_advanced_statement_stopped_route.py": "the catalogs' stopped-route words, read as data",
}

# The names a HANDED or THROUGH module hands car-adv as data (a test may build them): any other function of the module
# imported by name is its own rule, not yet forwarded. ALL-CAPS names are constants and always data.
HANDED_NAMES = {
    "registry": {"CapabilityDef", "Ceilings", "Option", "Registry", "RegistryError"},
    "arming": set(),
    "policy": {"Policy"},
    "statement": {"Catalogs"},
    "state": {"StateError", "StaleGeneration", "Refused", "Scoped"},
    "ledger": {"ClaimLedger"},
}


def blocking(imports: set) -> dict:
    """{module or module.Name: its seat} of every import table.py does not cover."""
    found = {}
    for each in imports:
        module = advledger.real(each, set(table.MODULES))
        row = table.MODULES.get(module)
        if row is None:
            continue
        name = each[len(module) + 1:] if each != module else ""
        if row.status in ("forwarded", "data"):
            if row.status == "forwarded" and name and name not in row.forwards and not name.isupper() \
                    and name not in HANDED_NAMES.get(module, ()):
                found[each] = row.seat
            continue
        if row.status in ("through", "handed"):
            if name and not name.isupper() and name not in HANDED_NAMES.get(module, ()):
                found[each] = row.seat
            continue
        found[each] = row.seat
    return found


def rows(tag: str) -> list:
    ledger = {row["file"]: row for row in advledger.ledger(tag)}
    tests = advledger.files(tag)
    known = set(table.MODULES)
    out = []
    for name in sorted(ledger):
        base = ledger[name]
        imports = {advledger.real(each, known) if advledger.real(each, known) == each else each
                   for each in advledger.imported(tests[name], tests)}
        waits = blocking(imports)
        if base["reason"] != "proxy":
            status, why = "waits for %s" % base["unlock"], base["reason"]
        elif name in GREEN:
            status, why = "green on Rust", GREEN[name]
        elif name in RUN_WAITS:
            status, why = "waits for %s" % RUN_WAITS[name][0], RUN_WAITS[name][1]
        elif not waits:
            status, why = "ready", "nothing it imports waits: --run it"
        else:
            seats = {seat for seat in waits.values()}
            latest = [each for each in advledger.ORDER if each in seats]
            unlock = latest[-1] if latest else sorted(seats)[0]
            status, why = "waits for %s" % unlock, ", ".join(sorted(waits))
        out.append({"file": name, "status": status, "why": why, "advancedcase": base["advancedcase"]})
    return out


# ------------------------------------------------------------------ --run

def _lane(files, proxied: bool, scratch: Path, debug: bool):
    report = scratch / ("rust.json" if proxied else "python.json")
    counts = scratch / "counts.txt"
    environment = dict(os.environ, CODEX_AR_EDITION="advanced",
                       PYTHONPATH=os.pathsep.join(("src", os.path.join("advanced", "src"))))
    environment.pop("CODEX_AR_CORE", None)
    if proxied:
        environment.update(CODEX_AR_CORE="rust", CODEX_AR_ADVPROXY_COUNT=str(counts))
        if debug:
            environment["CODEX_AR_ADVSERVE_EXE"] = str(ROOT / "advanced" / "rust" / "target" / "debug" / "examples"
                                                       / "advserve.exe")
    folders = [ROOT, ROOT / "src", ROOT / "advanced" / "src"]
    # a test lane, not a reference: advanced/tests bring tests/no_real_codex.py (test_parts' worker installs it) and their
    # own stand-ins, so refguard's program does not run here (guard=False; test_rustdiff_refguard names this one file)
    subprocess.run(refpython.script_command(ROOT / "scripts" / "test_parts.py", "--worker", "advanced/tests", "--report",
                                            str(report), *files, paths=folders, guard=False),
                   cwd=str(ROOT), env=environment, creationflags=NO_WINDOW, capture_output=True)
    outcomes = json.loads(report.read_text(encoding="utf-8")) if report.is_file() else {}
    calls = {}
    if proxied and counts.is_file():
        for line in counts.read_text(encoding="utf-8").splitlines():
            for call, number in json.loads(line)["counts"].items():
                calls[call] = calls.get(call, 0) + number
    return outcomes, calls


def _outcomes(report) -> dict:
    """scripts/test_parts.py's report: {"outcomes": {test id: "pass" | "fail" | "error" | "skip" | ...}}."""
    outcomes = report.get("outcomes") if isinstance(report, dict) else None
    return dict(outcomes) if isinstance(outcomes, dict) else {}


def run(files, debug: bool) -> int:
    worst, green = 0, 0
    print("both lanes on %s" % refpython.describe())
    for name in files:
        with tempfile.TemporaryDirectory(prefix="car-advproxy-") as scratch:
            scratch = Path(scratch)
            python, _ = _lane([name], False, scratch, debug)
            rust, calls = _lane([name], True, scratch, debug)
            want, got = _outcomes(python), _outcomes(rust)
            differ = sorted(key for key in set(want) | set(got) if want.get(key) != got.get(key))
            bad = sorted(key for key, outcome in got.items() if outcome not in ("pass", "skip", "expected-failure"))
            ok = bool(got) and not differ and not bad and (sum(calls.values()) > 0 or name in NO_CODE)
            worst = worst or (0 if ok else 1)
            green += ok
            print("%-52s %s  tests %d  calls %s%s" % (name, "GREEN" if ok else "NOT GREEN", len(got),
                                                     json.dumps(calls, sort_keys=True),
                                                     "" if not differ else "  differ: " + ", ".join(differ[:6])))
    print("GREEN %d of %d files run" % (green, len(files)))
    return worst


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default="v0.6.26")
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--seat")
    parser.add_argument("--run", nargs="*", help="these files on both lanes; none: every GREEN and ready file")
    parser.add_argument("--debug", action="store_true", help="the debug build of advserve")
    parser.add_argument("--reference-python", metavar="bundled|system|PATH",
                        help="the Python both lanes run on (refpython.py; default bundled)")
    args = parser.parse_args()
    if args.reference_python:
        refpython.select(args.reference_python)
    if args.run is not None:
        files = args.run or sorted(set(GREEN) | {row["file"] for row in rows(args.tag) if row["status"] == "ready"})
        return run(files, args.debug)
    found = rows(args.tag)
    if args.markdown:
        counts = {}
        for row in found:
            key = row["status"]
            counts.setdefault(key, [0, 0])
            counts[key][0] += 1
            counts[key][1] += row["advancedcase"]
        print("| status | files | of them advancedcase |")
        print("|---|---:|---:|")
        for key in sorted(counts, key=lambda each: (each != "green on Rust", each != "ready", each)):
            print("| %s | %d | %d |" % (key, counts[key][0], counts[key][1]))
        print("| **all** | %d | %d |" % (len(found), sum(row["advancedcase"] for row in found)))
        return 0
    for row in found:
        if args.seat and args.seat not in row["status"]:
            continue
        print("%-56s %-18s %s" % (row["file"], row["status"], row["why"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
