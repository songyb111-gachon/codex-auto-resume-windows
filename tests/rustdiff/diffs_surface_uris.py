"""S6.0, car-surface: the capability URIs and their readers, the Codex and chat links, the card's presence decision and
the inbox the card host is woken through.

* UriDiff - `urllib.parse.urlsplit` and `parse_qs` as the readers use them (car-surface's `pyurl`), over generated
  URIs (the scheme's characters, the authority and its brackets, IPv6 and IPvFuture hosts, the NFKC check, tabs and
  line breaks, percent escapes good and broken, `+`, `&` fields, fragments), and the four readers and three writers
  of `notice_uris` over the same and over ids, pages and nonces of every shape; the NFKC table is the interpreter's.
* LinkDiff - `codex_link`: the two links written and read, and `open_in_codex` with explorer.exe present or not and
  starting or not - the argv and the flags recorded, nothing started.
* PresenceDiff - `card_allowed` over every answer of every probe and the odd ones (a float, a bool where an int
  belongs, None, text).
* InboxDiff - `Inbox` over scripted wakes: woken, not woken, a wake that raises, a host that takes the notice while
  being woken, the limit, detach.
"""
from __future__ import annotations

from rustdiff.surface import Surface, counted

RECORD: list[str] = []

URIS = r'''
import random, unicodedata
from codex_auto_resume import notice_uris
from urllib.parse import urlsplit, parse_qs
rng = random.Random(626)
ID = "ab" * 32
NONCE = "0123456789abcdef"
pieces = ["codex-auto-resume", "Codex-Auto-Resume", "CODEX-AUTO-RESUME", "x", "", ":", "//", "/", "?", "#", "&", "=",
          "cancel", "open", "power-stop", "Cancel", "OPEN", "i=", "i", "page=", "n=", "c=1", "c=", "c", "%", "%2", "%41",
          "%zz", "%C3%A9", "%e2%82", "%ff", "+", " ", "\t", "\n", "\r", "\x00", "\x1f", "[", "]", "[::1]", "[v1.x]",
          "[1.2.3.4]", "@", "a@b", "℀", "／", "é", "K", "İ", "history", " History ", "pending",
          ID, ID.upper(), " " + ID + " ", NONCE, NONCE.upper(), "settings", "overview", "x" * 70, "א", "%20"]
uris = []
for _ in range(2500):
    uris.append("".join(rng.choice(pieces) for _ in range(rng.randint(0, 9))))
fixed = ["codex-auto-resume:cancel?i=" + ID, "codex-auto-resume://cancel?i=" + ID, "codex-auto-resume:///cancel/?i=" + ID,
         "CODEX-AUTO-RESUME:CANCEL?i=" + ID.upper(), "codex-auto-resume:cancel?i=" + ID + "&i=" + ID,
         "codex-auto-resume:cancel?i=" + ID + "&c=1", "codex-auto-resume:cancel?i=" + ID + "&c=1&c=1",
         "codex-auto-resume:cancel?i=" + ID + "&c=2", "codex-auto-resume:cancel?i=" + ID + "#frag",
         "codex-auto-resume:cancel?i=%20" + ID, "codex-auto-resume:cancel?i=+" + ID + "+",
         "codex-auto-resume:open?page=history", "codex-auto-resume:open?page=History", "codex-auto-resume:open?page=nope",
         "codex-auto-resume:open?page=history&page=pending", "codex-auto-resume:open?page=%68istory",
         "codex-auto-resume:open?page=Kistory", "codex-auto-resume://open?page=settings",
         "codex-auto-resume:power-stop?n=" + NONCE, "codex-auto-resume:power-stop?n=" + NONCE + "&x=",
         "codex-auto-resume:power-stop?n=" + NONCE.upper(), "codex-auto-resume:power-stop?n=" + NONCE + "&n=" + NONCE,
         "codex-auto-resume:power-stop?n=", "codex-auto-resume://[::1]/cancel?i=" + ID, "codex-auto-resume://[zz]/cancel?i=" + ID,
         "codex-auto-resume://[v1.a]/open?page=history", "codex-auto-resume://[1.2.3.4]/open?page=history",
         "codex-auto-resume://℀/cancel?i=" + ID, "codex-auto-resume://Ⅰ/cancel?i=" + ID,
         "codex-auto-resume://a]b/cancel?i=" + ID, "codex-auto-resume://[fe80::1%25eth0]/open?page=history",
         "codex-auto-resume://[::ffff:1.2.3.4]/open?page=history", "codex-auto-resume://[1:2:3:4:5:6:7:8]/open?page=history",
         "codex-auto-resume://[1:2:3:4:5:6:7:8:9]/open?page=history", "codex-auto-resume://[1::2::3]/open?page=history",
         "codex-auto-resume://[:1:2:3:4:5:6:7]/open?page=history", "codex-auto-resume://[1:2:3:4:5:6:7::]/open?page=history",
         "codex-auto-resume://[::1.2.3]/open?page=history", "codex-auto-resume://[::01.2.3.4]/open?page=history",
         "codex-auto-resume://x[::1]/open?page=history", "codex-auto-resume://[::1]x/open?page=history",
         "codex-auto-resume://[::1]:80/open?page=history", "codex-auto-resume://u@[::1]/open?page=history",
         "codex-auto-resume://[12345::]/open?page=history", "codex-auto-resume://[" + "1:" * 30 + "]/open?page=history",
         " \x01codex-auto-resume:cancel?i=" + ID, "codex-auto-re\tsume:can\ncel?i=" + ID, "1codex:cancel?i=" + ID,
         "codex-auto-resume:cancel?i=" + ID[:-1], "codex-auto-resume:cancel?i=" + ID + "0", "", "codex-auto-resume:"]
uris += fixed
cases = [["uri.nfkc", sorted(c for c in range(0x80, 0x110000) if not 0xD800 <= c < 0xE000
                             and any(x in unicodedata.normalize("NFKC", chr(c)) for x in "/?#@:"))]]
for uri in uris:
    cases += [["uri.split", uri], ["uri.parse_cancel", uri], ["uri.parse_open", uri], ["uri.parse_power", uri],
              ["uri.asks_flag", uri], ["uri.with_flag", uri]]
for uri in uris[::7]:
    query = uri.split("?", 1)[-1]
    cases += [["uri.qs", query, False], ["uri.qs", query, True]]
for raw in range(300):
    query = "".join(rng.choice(["%", "%c3", "%A9", "%e2%82%ac", "%f0%9f", "%80", "%ed%a0%80", "%C0%AF", "+", "=", "&",
                                "a", "é", "%", "%4", "%%"]) for _ in range(rng.randint(0, 8)))
    cases += [["uri.qs", query, False], ["uri.qs", query, True]]
odd = [ID, ID.upper(), "", None, 5, 1.5, True, [1, "a"], {"k": "v"}, "x y", "é", "1" * 64]
for value in odd + ["history", "pending", "nope", " History"]:
    cases += [["uri.cancel", value], ["uri.open", value], ["uri.power", value]]
for value in odd + [None, 7, ["codex-auto-resume:cancel?i=" + ID]]:
    cases += [["uri.parse_cancel", value], ["uri.parse_open", value], ["uri.parse_power", value],
              ["uri.with_flag", value], ["uri.asks_flag", value]]

def split(uri):
    parts = urlsplit(uri)
    return [parts.scheme, parts.netloc, parts.path, parts.query, parts.fragment]

ops = {"uri.nfkc": lambda table: table, "uri.split": split,
       "uri.qs": lambda query, keep: parse_qs(query, keep_blank_values=keep),
       "uri.parse_cancel": notice_uris.parse_cancel_uri, "uri.parse_open": notice_uris.parse_open_uri,
       "uri.parse_power": notice_uris.parse_power_stop_uri, "uri.asks_flag": notice_uris.cancel_asks_open_codex,
       "uri.with_flag": notice_uris.with_open_codex_flag, "uri.cancel": notice_uris.cancel_uri,
       "uri.open": notice_uris.open_uri, "uri.power": notice_uris.power_stop_uri}
finish(cases, ops)
'''

LINKS = r'''
import sys
from codex_auto_resume import codex_link
recorder = Recorder()
codex_link.subprocess = recorder
UUID = "019a1b2c-3d4e-7f80-9a0b-1c2d3e4f5a6b"
values = [UUID, UUID.upper(), "{" + UUID + "}", UUID + " ", "", None, 5, [UUID], "019a1b2c3d4e7f809a0b1c2d3e4f5a6b",
          "00000000-0000-0000-0000-000000000000", "019a1b2c-3d4e-7f80-9a0b-1c2d3e4f5a6g"]
uris = []
for value in values:
    if isinstance(value, str):
        uris += [codex_link.CODEX_THREAD_LINK + value, codex_link.CHAT_LINK + value]
uris += ["codex://threads/" + UUID + "?x", "codex://threads/" + UUID + "/x", "CODEX://threads/" + UUID, "codex://threads/",
         "codex-auto-resume:chat?thread=" + UUID + "&x=1", None, 5, ["codex://threads/" + UUID]]
cases = []
for value in values:
    cases += [["link.codex", value], ["link.chat", value]]
for uri in uris:
    cases += [["link.parse_codex", uri], ["link.parse_chat", uri]]
scratch = os.getcwd()
for name, make in (("with", True), ("without", False)):
    folder = os.path.join(scratch, "root-" + name)
    os.makedirs(folder, exist_ok=True)
    if make:
        open(os.path.join(folder, "explorer.exe"), "wb").close()
for root in [os.path.join(scratch, "root-with"), os.path.join(scratch, "root-without"), os.path.join(scratch, "root-with") + "\\"]:
    for link in ["codex://threads/" + UUID, "codex://threads/" + UUID.upper(), "codex://threads/x", None, 5]:
        for outcome in [0, "oserror"]:
            cases.append(["link.open", link, root, outcome])

def open_case(link, root, outcome):
    recorder.calls, recorder.outcome = [], outcome
    os.environ["SystemRoot"] = root
    try:
        result = {"ok": codex_link.open_in_codex(link)}
    except Exception as error:
        result = {"error": type(error).__name__}
    return {"result": result, "started": recorder.calls}

ops = {"link.codex": codex_link.codex_thread_uri, "link.chat": codex_link.chat_uri,
       "link.parse_codex": codex_link.parse_codex_thread_uri, "link.parse_chat": codex_link.parse_chat_uri,
       "link.open": open_case}
finish(cases, ops)
'''

PRESENCE = r'''
import itertools
from codex_auto_resume import notice_presence as p
states = [5, 1, 2, 3, 4, 6, 7, None, 5.0, True, "5", 0]
modes = [0, 1, 2, None, 0.0, False, "0"]
apps = [0, 1, 2, 3, 4, None, False, 0.0]
flags = [False, True, None, 0]
cases = []
for state, mode, app in itertools.product(states, modes, apps):
    cases.append(["presence.allowed", {"setting": True, "tray_present": True, "notification_state": state,
                                        "notification_mode": mode, "app_notifications": app, "screen_reader": False,
                                        "remote_session": False, "session_locked": False}])
for setting, tray, reader, remote, locked in itertools.product([True, False, None, 1], [True, False, 1], flags, flags, flags):
    cases.append(["presence.allowed", {"setting": setting, "tray_present": tray, "notification_state": 5,
                                        "notification_mode": 0, "app_notifications": 0, "screen_reader": reader,
                                        "remote_session": remote, "session_locked": locked}])
cases.append(["presence.numbers"])
numbers = lambda: [p.NOTIFICATION_STATES, p.NOTIFICATION_MODES, p.APP_SETTINGS, p.SPI_GETSCREENREADER,
                   p.SPI_GETMESSAGEDURATION, p.SM_REMOTESESSION, p.DESKTOP_READOBJECTS, p.UOI_NAME, p.INPUT_DESKTOP,
                   p.TOAST_MANAGER_CLASS, p.IID_MANAGER_STATICS, p.IID_MANAGER_STATICS5, p.IID_MANAGER_FOR_USER3,
                   p.INSPECTABLE_SLOTS, p.SLOT_CREATE_NOTIFIER_WITH_ID, p.SLOT_NOTIFIER_SETTING, p.RO_INIT_MULTITHREADED,
                   p.RPC_E_CHANGED_MODE]
ops = {"presence.allowed": lambda answers: p.card_allowed(**answers), "presence.numbers": numbers}
finish(cases, ops)
'''

INBOX = r'''
import random
from codex_auto_resume.notice_inbox import Inbox
rng = random.Random(8)

def script(steps):
    box, out, wakes = Inbox(), [], []
    def wake():
        what = wakes.pop(0) if wakes else True
        if what == "raise":
            raise RuntimeError("wake")
        if what == "take":
            box.take()
            return False
        return what
    for step in steps:
        if step[0] == "attach":
            wakes[:] = list(step[1])
            box.attach(wake)
            out.append(None)
        elif step[0] == "post":
            out.append(box.post(step[1]))
        elif step[0] == "take":
            out.append(box.take())
        elif step[0] == "detach":
            out.append(box.detach())
        else:
            out.append(box.attached)
    return out

cases = [["inbox.script", [["post", 1], ["attached"], ["attach", []], ["attached"]] + [["post", n] for n in range(10)]
          + [["take"], ["detach"], ["attached"], ["post", 3]]],
         ["inbox.script", [["attach", [True, False, "raise", "take", 0, 1, "", "x"]]] + [["post", n] for n in range(9)]
          + [["take"]]],
         ["inbox.script", [["attach", [False]], ["post", 1], ["post", 1], ["take"], ["detach"]]]]
for _ in range(300):
    steps = []
    for _ in range(rng.randint(1, 30)):
        kind = rng.choice(["attach", "post", "post", "post", "take", "detach", "attached"])
        if kind == "attach":
            steps.append(["attach", [rng.choice([True, False, "raise", "take", 1, 0]) for _ in range(rng.randint(0, 6))]])
        elif kind == "post":
            steps.append(["post", rng.randint(0, 5)])
        else:
            steps.append([kind])
    cases.append(["inbox.script", steps])
ops = {"inbox.script": script}
finish(cases, ops)
'''


class UriDiff(Surface):
    def test_uris(self):
        done = self.family(URIS, label="uris")
        RECORD.append("uris: %d urlsplit, %d parse_qs, %d reader and writer cases of notice_uris equal the tag's; the NFKC "
                      "table is the interpreter's (%d code points)" % (
                          counted(done, "uri.split"), counted(done, "uri.qs"),
                          len(done["cases"]) - counted(done, "uri.split") - counted(done, "uri.qs") - 1,
                          len(done["cases"][0][1])))


class LinkDiff(Surface):
    def test_links(self):
        done = self.family(LINKS, label="links")
        RECORD.append("links: %d link cases and %d open_in_codex cases (explorer.exe present or not, started or not; argv "
                      "and flags recorded, nothing started) equal the tag's" % (
                          len(done["cases"]) - counted(done, "link.open"), counted(done, "link.open")))


class PresenceDiff(Surface):
    def test_presence(self):
        done = self.family(PRESENCE, label="presence")
        RECORD.append("presence: card_allowed over %d answer sets, and the probes' numbers, equal the tag's"
                      % counted(done, "presence.allowed"))


class InboxDiff(Surface):
    def test_inbox(self):
        done = self.family(INBOX, label="inbox")
        steps = sum(len(case[1]) for case in done["cases"])
        RECORD.append("inbox: %d scripts (%d steps: attach, post, take, detach; wakes woken, refused, raising, taking) "
                      "equal the tag's" % (len(done["cases"]), steps))
