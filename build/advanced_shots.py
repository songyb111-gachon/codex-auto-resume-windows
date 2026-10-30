"""Make the Advanced features pictures (v0.6.16 final, before-after.md P1, P4, P5, P7 and P8): the real window, drawn
offscreen.

    python -X utf8 build/advanced_shots.py                    # every picture, in English and Korean, into docs/images
    python -X utf8 build/advanced_shots.py P1 P5 --locale ko  # some of them (P1 is P1-before and P1-after)
    python -X utf8 build/advanced_shots.py --out <folder>     # a proof: into <folder>, the manifest left alone
    python -X utf8 build/advanced_shots.py --list             # each picture, what it needs, what this tree lacks

Each picture is the window's client area drawn by the window itself in its render mode (gui/WindowRender.cs,
build/motion_window.py) - compiled from the working tree, the advanced edition's with advanced/gui/window.sources
after the standard sources - put in its caption, frame and corners from one captured still
(assets/screenshot-dashboard.png), as the README's motion is. Nothing is shown on the screen and nothing is captured.

What the window shows is answered from a scratch installation pinned as the stills' is (make_screenshots.
pinned_installation: the same records, clock, stand-in registry and synthetic Codex). For the advanced edition's
pictures its bridge runs with the advanced edition's own plug - a policy of none, the scratch installation's own
compatibility view, the pinned clock - and is seeded through that edition's own code, as a person's Dashboard would
seed it: each capability turned on or watched by the bridge's advanced-arm with the statement's warnings confirmed
(requirements with it), the reset message, the credit rule, the queued messages and the rule for an error code added
by their own bridge commands, and the samples of failures nothing classified kept by the state's own `admit` and
`taken`. No SQL is written here, so the seed follows the advanced state's schema as it moves (5 now; 6 with the
usage numbers; 7 with stage 4). The report's jobs, which the edition names at random, are renamed for what they are,
so the same tree gives the same answers and the same bytes.

What a picture needs of the advanced edition is named in NEEDS, the one table: a capability, a choice, a bridge
command, a module or a window source. A picture whose needs this tree does not have stops the run with "not in this
tree" before anything is drawn, and a page, a capability, a report or a Custom... the window cannot show stops the
render mode itself, so no picture is ever drawn of something else. Every read the window makes must be answered: one
that is not stops the run.

The two pictures of v0.6.16-beta.4's usage numbers, settled at the final's merge (plans/v0616-advshots/STOP-NOTES.md):

* P7-after, the Overview at 96 % of the five-hour window with the stop near a limit on. The status card's reason is the
  one the window draws - "Waiting" over the two recoveries, and under them the usage line, the five-hour window at 96 %
  and when it resets - because beta.4 holds core's records at their gate as any gate holds them (they keep waiting) and
  draws no words of its own on the Overview: a picture never shows what the product does not draw.
* P8, the usage meter's Choices card - both windows' warnings and each window's switch - scrolled to the top of the
  column (`show` "choices": the statement above it scrolled away), with the five-hour warning's drop-down holding 88%,
  a number of one's own, as one item before Custom... - as it shows a number its Custom... dialog took (`custom`, v0.6.16
  final): the one picture of "a Custom entry beside the presets". The meter is on, as in P7 (the near_limit seed), so
  the card is of a capability in use.

Into docs/images, the run first holds the window drawn offscreen to today's captured stills (motion_fidelity) and
records the result, each picture's digest and what it was made from in assets/advanced-shots.json; a page that fails
stops it. It needs Windows and the in-box C# compiler; the window is drawn at the stills' pinned scale (150 %) whatever
the display is. Run it from the main session
after the stills are made, detached, under plans/proof/gui_lock.sh.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "src"), str(ROOT / "build")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

ADVANCED_SRC = ROOT / "advanced" / "src"
ADVANCED_SOURCES = ROOT / "advanced" / "gui" / "window.sources"
MANIFEST = ROOT / "assets" / "advanced-shots.json"
OUT = ROOT / "docs" / "images"
LOCALES = ("en", "ko")
# The still whose caption, frame and corners every picture is laid in: the caption reads "Codex Auto Resume" in every
# language, so one serves both.
STILL = "assets/screenshot-dashboard.png"
# What the generator is made of, beside the window's sources and the catalogs.
CODE = ("build/advanced_shots.py", "build/motion_window.py", "build/make_screenshots.py")
# What the report is written for: a login that is plainly made up, and the Windows version it says it ran on.
LOGIN = "example-user"
WINDOWS = "10.0.26100"


# ---------------------------------------------------------------------------------------------------- the pictures
class Shot(NamedTuple):
    """One picture: its name (before-after.md's), its file under docs/images (`-ko` added in Korean), the edition whose
    window draws it, the page, the capability open, the seed it is drawn from (VARIANTS), whether the report is
    written and checked first, the part of the open capability's column scrolled to its top (AdvancedRender.cs's
    RenderShow: report, report.file, report.check, choices), and the choice Custom... is chosen on, with the number typed
    in its box - (key, text), or None (RenderCustom)."""
    name: str
    file: str
    edition: str
    page: str
    capability: str | None = None
    variant: str = "base"
    report: bool = False
    show: str | None = None
    custom: tuple | None = None


SHOTS = (
    Shot("P1-before", "advanced-page-before", "standard", "overview"),
    Shot("P1-after", "advanced-page-after", "advanced", "advanced", "compat_report"),
    Shot("P4-before", "advanced-scheduled-before", "standard", "pending"),
    Shot("P4-after", "advanced-scheduled-after", "advanced", "pending"),
    Shot("P5", "advanced-report", "advanced", "advanced", "compat_report", report=True, show="report.file"),
    Shot("P7-before", "advanced-pause-before", "standard", "overview"),
    Shot("P7-after", "advanced-pause-after", "advanced", "overview", variant="near_limit"),
    Shot("P8", "advanced-usage-numbers", "advanced", "advanced", "usage_meter", variant="near_limit", show="choices",
         custom=("warn_five_hour", "88")),
)


class Need(NamedTuple):
    """What a picture needs of the advanced edition: `kind` capability (a registry id), option (an OptionKey), command
    (a BridgeCommand), module (importable), source (an advanced window source) or decision (something to settle when
    it arrives - never present until it is written here); `name`; and where it comes from."""
    kind: str
    name: str
    comes: str


BETA4 = "v0.6.16-beta.4"
# The one table of what each advanced picture needs. P8's usage numbers and P7's stop near a limit came with
# v0.6.16-beta.4, and what each shows of it was settled when it was merged (the module docstring).
NEEDS = {
    "P1-after": (Need("capability", "compat_report", "v0.6.11"),),
    "P4-after": (Need("capability", "reset_message", "v0.6.14"), Need("capability", "reset_credit", "v0.6.14"),
                 Need("capability", "prompt_queue", "v0.6.15-beta"), Need("command", "advanced-prompts", "v0.6.15-beta")),
    "P5": (Need("capability", "compat_report", "v0.6.11"), Need("command", "advanced-report-check", "v0.6.14")),
    "P7-after": (Need("capability", "usage_meter", "v0.6.16-beta.3"), Need("capability", "usage_pause", "v0.6.16-beta.3"),
                 # The forced stop near a limit, which holds core's records at their gate as they wait for the reset.
                 Need("module", "codex_auto_resume_advanced.engine.usagestop", BETA4)),
    "P8": (Need("capability", "usage_meter", "v0.6.16-beta.3"), Need("capability", "usage_pause", "v0.6.16-beta.3"),
           Need("option", "window_five_hour", BETA4), Need("option", "warn_five_hour", "v0.6.16-beta.3"),
           Need("command", "advanced-wordings", BETA4), Need("source", "advanced/gui/AdvancedUsage.cs", BETA4)),
}

# Every capability the seed turns on ("armed") or watches ("shadow"), in this order; and each seed variant's own: the
# capabilities it adds and the five-hour window's use it reads (None: the stills' reading).
BASE_TURNED = (("compat_report", "armed"), ("reset_message", "armed"), ("reset_credit", "armed"),
               ("prompt_queue", "armed"), ("send_now", "armed"), ("capacity_retry", "armed"),
               ("structured_rules", "armed"), ("unknown_failure_budget", "watched"), ("early_reset", "watched"))
VARIANTS = {"base": {"turned": (), "five_hour": None},
            "near_limit": {"turned": (("usage_meter", "armed"), ("usage_pause", "armed")), "five_hour": 96}}
# The seed's words (before-after.md B.20, B.21): the reset message for example-project, the queued messages for
# example-service - one after the turn now running, one every day at 09:00, thirty times at most.
RESET_WORDS = "Run the tests again, then carry on with the release notes."
AFTER_TURN_WORDS = "Now write the tests."
DAILY_WORDS = "Summarise yesterday's changes."
DAILY_AT = 3600                       # 09:00 on the pictures' clock: an hour after ENVELOPE_NOW (08:00)
DAILY_TIMES = 30
# The rule for an error code (B.12) and the samples of failures nothing classified (B.13): codes plainly made up.
RULE = {"tag": "upstreamBusy", "status_from": 502, "status_to": 504, "category": "server_5xx"}
SAMPLES = ({"code": "someNewCode", "status": 500, "form": "tagged", "has_message": False,
            "items": {"agentMessage": 0, "other": 1}, "duration": 41, "ago": 3 * 3600},
           {"code": "someNewCode", "status": 500, "form": "tagged", "has_message": False,
            "items": {"agentMessage": 1}, "duration": 12, "ago": 26 * 3600})
STATE_WORDS = {"armed": "armed", "watched": "shadow"}


def shot(name: str) -> Shot:
    for each in SHOTS:
        if each.name == name:
            return each
    raise KeyError("no picture is called %s" % name)


def chosen(names) -> list:
    """The pictures `names` name: a picture's own name, or its number for both of a pair (P1: P1-before, P1-after)."""
    if not names:
        return list(SHOTS)
    picked = [each for each in SHOTS if each.name in names or each.name.split("-", 1)[0] in names]
    unknown = set(names) - {each.name for each in picked} - {each.name.split("-", 1)[0] for each in picked}
    if unknown:
        raise SystemExit("no picture is called %s" % ", ".join(sorted(unknown)))
    return picked


# ---------------------------------------------------------------------------------------------------- the needs
class NotInThisTree(RuntimeError):
    """A picture needs what this tree does not have."""


def advanced_path() -> None:
    if str(ADVANCED_SRC) not in sys.path:
        sys.path.insert(0, str(ADVANCED_SRC))


def advanced_sources() -> list:
    """The advanced window's own sources, in compile order, after the standard window's."""
    names = [line.split("#", 1)[0].strip() for line in ADVANCED_SOURCES.read_text(encoding="utf-8").splitlines()]
    return [name for name in names if name and not name.startswith("[")]


def present(need: Need) -> bool:
    """Whether this tree has `need`."""
    advanced_path()
    if need.kind == "capability":
        from codex_auto_resume_advanced import registry
        return need.name in {definition.id for definition in registry.DEFINITIONS}
    if need.kind == "option":
        from codex_auto_resume_advanced.vocabulary import OptionKey
        return need.name in {str(key) for key in OptionKey}
    if need.kind == "command":
        from codex_auto_resume_advanced.vocabulary import BridgeCommand
        return need.name in {str(command) for command in BridgeCommand}
    if need.kind == "module":
        try:
            return importlib.util.find_spec(need.name) is not None
        except ImportError:
            return False
    if need.kind == "source":
        return (ROOT / need.name).is_file() and need.name in advanced_sources()
    if need.kind == "decision":
        return False
    raise ValueError("no need is of the kind %r" % need.kind)


def missing(each: Shot) -> list:
    """What `each` needs that this tree does not have, in words."""
    return ["%s %s (%s)" % (need.kind, need.name, need.comes) for need in NEEDS.get(each.name, ()) if not present(need)]


def require(shots) -> None:
    """Stops, before anything is drawn, where a picture needs what this tree does not have."""
    lacking = {each.name: missing(each) for each in shots}
    lacking = {name: what for name, what in lacking.items() if what}
    if lacking:
        raise NotInThisTree("not in this tree: " + "; ".join("%s needs %s" % (name, ", ".join(what))
                                                              for name, what in sorted(lacking.items())))


# ---------------------------------------------------------------------------------------------------- the seed
def usage_reading(five_hour):
    """make_screenshots.sample_usage with the five-hour window at `five_hour` percent (None: as the stills read it)."""
    import make_screenshots as shots
    original = shots.sample_usage

    def reading(now):
        read_at, windows = original(now)
        if five_hour is None:
            return read_at, windows
        return read_at, [dict(window, used_percent=five_hour) if window["window_minutes"] == 300 else window
                         for window in windows]
    return reading


def ask_ok(surface, command, argument=None) -> dict:
    """A bridge request whose answer has to be done: its result, or a stop naming the refusal."""
    import make_screenshots as shots
    reply = shots.ask(surface, command, argument)
    result = reply.get("result") if isinstance(reply.get("result"), dict) else reply
    if not reply.get("ok") or result.get("done") is False:
        raise RuntimeError("the seed's %s %s was refused: %r" % (command, json.dumps(argument), reply))
    return result


def turn(surface, capability: str, state: str) -> None:
    """`capability` turned on or watched as the Dashboard turns it (advanced-arm): the generation the list was read at,
    the statement's revision, the warnings it carries now and the Codex version it names - and, to turn it on, each
    requirement that is off with it, confirmed the same way."""
    listing = ask_ok(surface, "advanced-list", {})
    items = {item["id"]: item for item in listing["capabilities"]}
    if capability not in items:
        raise NotInThisTree("not in this tree: the seed turns on %s" % capability)
    item = items[capability]
    argument = {"capability": capability, "state": STATE_WORDS[state], "revision": item["revision"],
                "generation": listing["generation"], "engine_version": listing["engine_version"],
                "warnings": item["warnings"]}
    if state == "armed" and item["requires_off"]:
        argument["also"] = [{"capability": other, "revision": items[other]["revision"],
                             "warnings": items[other]["warnings"], "engine_version": listing["engine_version"]}
                            for other in item["requires_off"]]
    ask_ok(surface, "advanced-arm", argument)


def generation(surface) -> int:
    return ask_ok(surface, "advanced-list", {})["generation"]


def seed(surface, runtime, variant: str) -> None:
    """The advanced edition's records every advanced picture shows, written through its own bridge and state."""
    import make_screenshots as shots
    now = shots.ENVELOPE_NOW
    for capability, state in BASE_TURNED + VARIANTS[variant]["turned"]:
        turn(surface, capability, state)
    ask_ok(surface, "advanced-reset-add", {"kind": "message", "bucket": "codex", "minutes": 300, "ordinal": 1,
                                           "thread_id": shots.WINDOW_THREADS[0], "words": RESET_WORDS,
                                           "generation": generation(surface)})
    ask_ok(surface, "advanced-reset-add", {"kind": "credit", "bucket": "codex", "minutes": 300, "ordinal": 1,
                                           "repeat": False, "ask_first": True, "generation": generation(surface)})
    ask_ok(surface, "advanced-prompt-add", {"thread_id": shots.WINDOW_THREADS[1], "words": AFTER_TURN_WORDS,
                                            "trigger": "after_turn", "generation": generation(surface)})
    ask_ok(surface, "advanced-prompt-add", {"thread_id": shots.WINDOW_THREADS[1], "words": DAILY_WORDS,
                                            "trigger": "recurring", "at": int(now) + DAILY_AT, "every": "day",
                                            "occurrences": DAILY_TIMES, "generation": generation(surface)})
    ask_ok(surface, "advanced-rule-add", dict(RULE, generation=generation(surface)))
    state = runtime.state
    for index, sample in enumerate(SAMPLES):
        key = "%x" % (0xa0 + index) * 32
        shape = {name: sample[name] for name in ("code", "status", "form", "has_message")}
        at = int(now) - sample["ago"]
        if not state.admit(key, "unknown_failure_budget", "admit", shape=shape, at=at):
            raise RuntimeError("the seed's sample %d was not admitted" % index)
        if not state.taken(key, "unknown_failure_budget", "sampled", at=at,
                           sample=dict(shape, items=sample["items"], duration=sample["duration"])):
            raise RuntimeError("the seed's sample %d was not kept" % index)


@contextmanager
def advanced_installation(workspace: Path, variant: str = "base"):
    """The stills' pinned scratch installation in `workspace`, with the advanced edition's bridge over it, seeded:
    yields that bridge's surface (a core Control with the advanced plug). Nothing outside `workspace` is written."""
    import make_screenshots as shots
    from unittest import mock
    advanced_path()
    from codex_auto_resume import control
    from codex_auto_resume_advanced import arming, plug, policy
    from codex_auto_resume_advanced.control import sendnow
    from codex_auto_resume_advanced.report import document, github
    with ExitStack() as stack:
        stack.enter_context(mock.patch.object(shots, "sample_usage", usage_reading(VARIANTS[variant]["five_hour"])))
        core = stack.enter_context(shots.pinned_installation(Path(workspace)))
        # The watcher's wake for a scratch home names its own event, and is not needed: the render asks nobody.
        stack.enter_context(mock.patch.object(sendnow, "wake", return_value=False))
        # No gh: the report's check says how to send it on the web, on every machine (P5's four web steps).
        stack.enter_context(mock.patch.object(github, "find_gh", return_value=None))
        stack.enter_context(mock.patch.object(document, "windows_version", return_value=WINDOWS))
        paths = core.paths
        made = plug.AdvancedPlug(paths, clock=lambda: shots.ENVELOPE_NOW, policy=lambda: policy.NONE,
                                 view=lambda: arming._view_of(paths))
        stack.callback(lambda: made._runtime is not None and made._runtime.state.close())
        surface = control.Control(paths, plug=made)
        seed(surface, made.runtime, variant)
        yield surface


# ---------------------------------------------------------------------------------------------------- the answers
def standard_reads(surface, out: list) -> dict:
    """The reads the standard pages make (motion_window.answers'), asked of `surface`, appended to `out`."""
    import make_screenshots as shots
    import motion_window
    replies = {}
    for command, argument in shots.WINDOW_READS + motion_window.EXTRA_READS:
        replies[command] = shots.ask(surface, command, argument)
        out.append((command, argument, replies[command]))
    preview = shots.preview_request((replies["describe"] or {}).get("schema") or [],
                                    (replies["settings"] or {}).get("settings") or {})
    if preview is not None:
        out.append((preview[0], None, shots.ask(surface, *preview)))
    return replies


def locale_argument(preference, capability=None) -> dict:
    """The page's request in the person's language, as AdvancedPage.LocaleArgument writes it: the capability first."""
    argument = {}
    if capability is not None:
        argument["capability"] = capability
    if preference:
        argument["locale"] = preference
    return argument


def advanced_reads(surface, preference, out: list) -> None:
    """Every read the Advanced features page and Pending's scheduled group make, for every capability, appended."""
    import make_screenshots as shots
    for command, argument in (("advanced-words", locale_argument(preference)), ("advanced-list", {}),
                              ("advanced-rules", {}), ("advanced-samples", {}), ("advanced-resets", {}),
                              ("advanced-prompts", {}), ("advanced-keep-going", {})):
        out.append((command, argument, shots.ask(surface, command, argument)))
    listing = ask_ok(surface, "advanced-list", {})
    for item in listing["capabilities"]:
        argument = locale_argument(preference, item["id"])
        out.append(("advanced-statement", argument, shots.ask(surface, "advanced-statement", argument)))
        if item["kind"] != "action":
            argument = {"capability": item["id"]}
            out.append(("advanced-watch-log", argument, shots.ask(surface, "advanced-watch-log", argument)))


def report_replies(surface, out: list) -> None:
    """The compatibility report written for LOGIN and checked, as its card's buttons ask (each a job, read until it
    ends), appended with each job renamed for what it is - the report's own ids are a random draw."""
    import make_screenshots as shots

    def run(command, argument, name):
        started = ask_ok(surface, command, argument)
        deadline = time.monotonic() + 60
        while True:
            ended = ask_ok(surface, "advanced-report-job", {"job": started["job"]})
            if ended.get("status") != "running":
                break
            if time.monotonic() > deadline:
                raise RuntimeError("the report's %s job did not end" % name)
            time.sleep(0.05)
        out.append((command, argument, {"ok": True, "result": dict(started, job=name)}))
        out.append(("advanced-report-job", {"job": name}, {"ok": True, "result": dict(ended, job=name)}))
        return ended
    built = run("advanced-report-build", {"login": LOGIN}, "report-build")
    if built.get("status") != "built":
        raise RuntimeError("the report was not written: %r" % built)
    checked = run("advanced-report-check", {"sha256": built["sha256"]}, "report-check")
    if checked.get("status") != "web":
        raise RuntimeError("the report's check did not say how to send it on the web: %r" % checked)


def read_answers(edition: str, variant: str, locale: str, report: bool = False) -> list:
    """[(command, argument, reply)]: everything the window drawing `edition`'s pictures of `variant` reads, in `locale`."""
    import make_screenshots as shots
    from codex_auto_resume import config, l10n
    out = []
    previous = os.environ.get(l10n.ENV_LANG)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as name:
        workspace = Path(name)
        with ExitStack() as stack:
            # The edition's own kinds of notice, whatever an earlier picture or test registered in this process.
            stack.enter_context(shots.edition_notice_kinds(edition))
            # The machine's power actions pinned: the Dashboard reads Windows' own sleep states and hibernation
            # (win/powerdown), which differ from PC to PC, so CI's runner read every picture as moved. Pinned as the PC
            # the pictures are drawn on answers: no sleep state, hibernation and shutting down offered.
            from unittest import mock
            from codex_auto_resume.win import powerdown
            # Who may open the state folder (win/acl) is read from the folder's real access list, which a CI runner's
            # accounts answer differently: pinned as an installation answers it, owner only.
            from codex_auto_resume.win import acl
            stack.enter_context(mock.patch.object(acl, "state_access", return_value="owner_only"))
            # Where the watcher and the bridge run (win/kernel.host_app, v0.6.17) is read from the live process table:
            # pinned as an installation started from the Start menu answers it, outside every app.
            from codex_auto_resume.win import kernel
            stack.enter_context(mock.patch.object(kernel, "host_app", side_effect=lambda pid=None, started_by=None: {
                "state": "outside", "family": None, "app": None}))
            stack.enter_context(mock.patch.object(powerdown, "available", side_effect=lambda action: {
                powerdown.SLEEP: (False, powerdown.NO_SLEEP_STATE), powerdown.HIBERNATE: (True, None),
                powerdown.SHUT_DOWN: (True, None)}.get(action, (False, None))))
            if edition == "advanced":
                surface = stack.enter_context(advanced_installation(workspace, variant))
            else:
                from unittest import mock
                stack.enter_context(mock.patch.object(shots, "sample_usage", usage_reading(VARIANTS[variant]["five_hour"])))
                surface = stack.enter_context(shots.pinned_installation(workspace))
            if os.name == "nt":
                shots.owner_only(config.Paths(workspace / "home").state_dir)
            os.environ[l10n.ENV_LANG] = locale
            try:
                replies = standard_reads(surface, out)
                if edition == "advanced":
                    advanced_reads(surface, (replies["strings"] or {}).get("preference"), out)
                    if report:
                        report_replies(surface, out)
            finally:
                if previous is None:
                    os.environ.pop(l10n.ENV_LANG, None)
                else:
                    os.environ[l10n.ENV_LANG] = previous
            failed = [command for command, _argument, reply in out if not reply.get("ok")
                      or (isinstance(reply.get("result"), dict) and reply["result"].get("done") is False)]
            if failed:
                raise RuntimeError("the pinned installation could not answer %s" % failed)
            envelope = "\n".join(json.dumps({"command": command, "argument": argument,
                                             "reply": shots._canonical(reply, shots.workspace_spellings(workspace))},
                                            ensure_ascii=False, separators=(",", ":"))
                                 for command, argument, reply in out) + "\n"
    return out, envelope


def form_answers(read: list) -> dict:
    """The render job's form for one language: {"answers": [{command, argument, reply}]}, each argument written as
    the window writes its own (compact JSON, keys in its order)."""
    return {"answers": [{"command": command, "argument": None if argument is None
                         else json.dumps(argument, separators=(",", ":")), "reply": reply}
                        for command, argument, reply in read]}


# ---------------------------------------------------------------------------------------------------- the window
def compile_window(folder: Path, edition: str) -> Path:
    """The window built from the working tree into `folder`: the standard sources, and for the advanced edition its
    own after them, with the manifest that makes it DPI-aware - as build/make_gui.ps1 -Edition builds each."""
    import make_screenshots
    import motion_window
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    exe = folder / "CodexAutoResumeSettings.exe"
    names = make_screenshots.window_sources() + (advanced_sources() if edition == "advanced" else [])
    arguments = [str(motion_window.CSC), "/nologo", "/target:winexe", "/platform:x64", "/optimize+", "/out:" + str(exe),
                 "/win32manifest:" + str(ROOT / "gui" / "app.manifest"),
                 "/reference:System.dll", "/reference:System.Drawing.dll", "/reference:System.Windows.Forms.dll"]
    arguments += [str(ROOT / name) for name in names]
    done = subprocess.run(arguments, capture_output=True, timeout=600, creationflags=motion_window.NO_WINDOW)
    if done.returncode != 0 or not exe.is_file():
        raise RuntimeError("the %s window did not compile:\n%s" % (edition, done.stdout.decode("utf-8", "replace")))
    return exe


def frame(each: Shot, locale: str, index: int) -> dict:
    """The render mode's frame for one picture: its page, the capability open, the report asked for, the lights at the
    stills' moment."""
    state = {"index": index, "locale": locale, "page": each.page, "light": 0}
    if each.capability is not None:
        state["capability"] = each.capability
    if each.report:
        state["report"] = {"login": LOGIN, "check": True}
    if each.show is not None:
        state["show"] = each.show
    if each.custom is not None:
        state["custom"] = {"key": each.custom[0], "value": each.custom[1]}
    return state


def job(shots_of: list, locales, forms: dict, out: Path) -> tuple:
    """One render job - every picture of one edition and seed, in each language, in SHOTS' order but the report last,
    as it stays written once it is - and [(picture, locale)] in the order of its frames."""
    order = [(each, locale) for locale in locales for each in sorted(shots_of, key=lambda item: item.report)]
    frames = [frame(each, locale, index) for index, (each, locale) in enumerate(order)]
    import make_screenshots as shots
    return {"out": str(out), "theme": "light", "design": "soft", "scale": shots.PINNED_SCALE, "forms": forms,
            "targets": [], "frames": frames}, order


def render(exe: Path, job_data: dict, folder: Path) -> tuple:
    """([(frame index, client RGB)], client size) from the render mode, stopping where a read went unanswered or it
    noted anything."""
    import motion_window
    result = motion_window.render(exe, job_data, folder)
    if result.get("misses"):
        raise RuntimeError("the window read what nobody answered: %s" % ", ".join(result["misses"]))
    if result.get("notes"):
        raise RuntimeError("the render mode noted: %s" % "; ".join(result["notes"]))
    return [(index, picture) for index, picture, _bounds in motion_window.pictures(result, Path(job_data["out"]))], \
        tuple(result["client"])


def compose(still: tuple, client: bytes, size: tuple) -> tuple:
    """(width, height, RGB, alpha): the still's caption and corners with the client area `client` (RGB, `size`) laid in."""
    width, height, rgb, alpha = still
    client_w, client_h = size
    if width != client_w or height < client_h:
        raise ValueError("the still is %dx%d and the client area %dx%d: not the same window"
                         % (width, height, client_w, client_h))
    top = height - client_h
    picture = bytearray(rgb[:top * width * 3]) + bytearray(client)
    return width, height, bytes(picture), alpha


def png(width: int, height: int, rgb: bytes, alpha) -> bytes:
    """An RGBA PNG (RGB without alpha), one IDAT at zlib's level 9: the same picture is the same bytes."""
    import struct
    import zlib
    import make_screenshots as shots
    kind = 6 if alpha is not None else 2
    rows = shots._png_rows(rgb, width, height, width, 0, 0, alpha)
    return (b"\x89PNG\r\n\x1a\n" + shots._png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, kind, 0, 0, 0))
            + shots._png_chunk(b"IDAT", zlib.compress(rows, 9)) + shots._png_chunk(b"IEND", b""))


def target(each: Shot, locale: str, out: Path = OUT) -> Path:
    return Path(out) / ("%s%s.png" % (each.file, "" if locale == "en" else "-" + locale))


# ---------------------------------------------------------------------------------------------------- the manifest
def render_input(each: Shot, envelope: str) -> str:
    """What one picture is made from: its row of SHOTS and NEEDS, the seed, what the bridge answered the window
    (`envelope`, canonical), the window's sources - the advanced ones too for the advanced edition's - the catalogs, the
    still its frame is from and this generator's own files. A change to any of them marks the picture stale."""
    import make_screenshots as shots
    seed_text = json.dumps({"turned": BASE_TURNED, "variant": VARIANTS[each.variant], "reset": RESET_WORDS,
                            "after_turn": AFTER_TURN_WORDS, "daily": [DAILY_WORDS, DAILY_AT, DAILY_TIMES],
                            "rule": RULE, "samples": SAMPLES, "login": LOGIN, "windows": WINDOWS}, sort_keys=True)
    parts = [json.dumps(each._asdict(), sort_keys=True), json.dumps(NEEDS.get(each.name, ())), seed_text,
             hashlib.sha256(envelope.encode("utf-8")).hexdigest(), shots.window_digest()]
    if each.edition == "advanced":
        parts += ["%s\0%s" % (name, shots.input_digest(ROOT / name)) for name in advanced_sources()]
    parts.append(shots.input_digest(ROOT / STILL))
    parts += [shots.input_digest(ROOT / name) for name in CODE]
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


def envelope_parts(envelope: str) -> dict:
    """{"NN command": digest} for each read of an envelope, in order: recorded beside a picture's input so that when the
    input reads as moved, the test can name the reads that moved instead of a bare digest (a CI runner answered some of
    them differently from the PC the pictures were drawn on)."""
    parts = {}
    for index, line in enumerate(envelope.splitlines()):
        command = json.loads(line).get("command", "?") if line.strip() else "?"
        parts["%02d %s" % (index, command)] = hashlib.sha256(line.encode("utf-8")).hexdigest()[:16]
    return parts


def manifest_key(each: Shot, locale: str) -> str:
    return "<advanced shot:%s:%s>" % (each.name, locale)


def read_manifest() -> dict:
    if MANIFEST.is_file():
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {"inputs": {}, "images": {}, "fidelity": {}}


def write_manifest(manifest: dict) -> None:
    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------------------------------- making them
def reads_report(edition: str, variant: str) -> bool:
    """Whether the answers of `edition`'s pictures of `variant` include the report's: every picture of the pair is drawn
    from one reading, so as soon as one of them shows the report, all of them are read - and recorded - with it, whichever
    of them a run draws (P1-after's and P4-after's inputs once missed what P5 put into their shared answers)."""
    return any(shot.report for shot in SHOTS if (shot.edition, shot.variant) == (edition, variant))


def make(shots_wanted: list, locales, out: Path, work: Path) -> dict:
    """Draws `shots_wanted` in `locales` into `out`; {(name, locale): (path, render input)}."""
    import make_screenshots as shots
    require(shots_wanted)
    still = shots.read_png(ROOT / STILL)
    made = {}
    groups = {}
    for each in shots_wanted:
        groups.setdefault((each.edition, each.variant), []).append(each)
    exes = {}
    for (edition, variant), group in sorted(groups.items()):
        if edition not in exes:
            exes[edition] = compile_window(work / ("window-" + edition), edition)
        report = reads_report(edition, variant)
        forms, envelopes = {}, {}
        for locale in locales:
            read, envelopes[locale] = read_answers(edition, variant, locale, report)
            forms[locale] = form_answers(read)
        folder = work / ("%s-%s" % (edition, variant))
        data, order = job(group, locales, forms, folder / "frames")
        pictures, size = render(exes[edition], data, folder)
        if [index for index, _client in pictures] != list(range(len(order))):
            raise RuntimeError("the render mode drew %d of %d frames" % (len(pictures), len(order)))
        for (_index, client), (each, locale) in zip(pictures, order):
            width, height, rgb, alpha = compose(still, client, size)
            path = target(each, locale, out)
            path.parent.mkdir(parents=True, exist_ok=True)
            shots.write_file(path, png(width, height, rgb, alpha))
            made[(each.name, locale)] = (path, render_input(each, envelopes[locale]), envelope_parts(envelopes[locale]))
            print("%-10s %-3s %s" % (each.name, locale, path))
    return made


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    names, locales, out, listing = [], list(LOCALES), None, False
    items = iter(argv)
    for item in items:
        if item == "--locale":
            locales = [next(items)]
        elif item == "--out":
            out = Path(next(items)).resolve()
        elif item == "--list":
            listing = True
        else:
            names.append(item)
    wanted = chosen(names)
    if listing:
        for each in wanted:
            lacking = missing(each)
            print("%-10s %-9s %-9s %-16s %s" % (each.name, each.edition, each.page, each.capability or "-",
                                                "ready" if not lacking else "NOT IN THIS TREE: " + ", ".join(lacking)))
        return 0
    try:
        require(wanted)
    except NotInThisTree as stop:
        raise SystemExit(str(stop))
    import make_screenshots as shots
    real = out is None
    if real:
        recorded = json.loads(shots.MANIFEST.read_text(encoding="utf-8"))
        if shots.stills_dpi_problem(recorded):
            raise SystemExit(shots.stills_dpi_problem(recorded))
        if recorded["inputs"].get("<window sources>") != shots.window_digest():
            raise SystemExit("the window's stills are stale: run build/make_screenshots.py first")
    with tempfile.TemporaryDirectory() as name:
        work = Path(name)
        manifest = read_manifest()
        if real:
            import motion_fidelity
            import motion_window
            # motion_window.compile_window writes into a folder that must exist (make_motion hands it its own work
            # folder); a fresh subfolder here did not, so csc could not write the window (2026-10-18).
            (work / "fidelity").mkdir()
            results = motion_fidelity.check(motion_window.compile_window(work / "fidelity"), work, tuple(locales))
            manifest["fidelity"] = dict(results, window=shots.window_digest())
            write_manifest(manifest)
            failed = sorted(key for key, result in results.items() if not result["passed"])
            if failed:
                raise SystemExit("the window drawn offscreen is not the captured one on %s" % ", ".join(failed))
        made = make(wanted, locales, out or OUT, work)
        if real:
            for (shot_name, locale), (path, inputs, parts) in sorted(made.items()):
                key = str(path.relative_to(ROOT)).replace("\\", "/")
                manifest["inputs"][manifest_key(shot(shot_name), locale)] = inputs
                manifest.setdefault("parts", {})[manifest_key(shot(shot_name), locale)] = parts
                manifest["images"][key] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                                           "size": shots.dimensions(path)}
            write_manifest(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
