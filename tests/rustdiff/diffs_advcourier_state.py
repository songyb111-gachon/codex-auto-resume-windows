"""The courier's state, senders and server against the v0.6.26 tag (seat S7.3b): the outbox's rules over a real
advanced state, each channel's request at the opener byte for byte (ntfy, webhook, Telegram), what a push says in two
languages, the outbox drained against scripted replies (sent, refused, dropped, tripped), Telegram's pairing, and the
loopback API answering raw requests - every answer, every request, and both advanced.sqlite files table by table.

    python -X utf8 tests/rustdiff/run.py --build --reference v0.6.26 --reference-python bundled -k diffs_advcourier
"""
from __future__ import annotations

from rustdiff import advcourier

OUTBOX = r'''
def scenario(name, steps):
    home = home_of(name)
    probe = Probe(home, 0.0, {})
    state, answers = probe.state, []
    ops = {"enqueue": lambda s: outbox.enqueue(state, s[1], s[2], s[3], s[4], s[5]),
           "due": lambda s: outbox.due(state, s[1]), "waiting": lambda s: outbox.waiting(state, s[1]),
           "settle": lambda s: outbox.settle(state, s[1], s[2], s[3]), "expire": lambda s: outbox.expire(state, s[1]),
           "stale": lambda s: outbox.stale(state, s[1], s[2]), "refusals": lambda s: outbox.refusals_today(state, s[1], s[2]),
           "alias": lambda s: outbox.alias(s[1])}
    for step in steps:
        try:
            answers.append({"ok": jsonable(ops[step[0]](step))})
        except Exception as error:
            answers.append({"error": type(error).__name__})
    state.close()
    case("outbox.scenario", home, steps, ref=lambda: answers)
base = 1700000000.0
steps = [["waiting", base], ["enqueue", ["ntfy", "webhook"], "recovered", "usage_limit", "task 1", base],
         ["enqueue", ["email"], "failed", None, None, base + 1], ["due", base], ["due", base + 9], ["waiting", base + 5],
         ["settle", 1, False, base + 1], ["due", base + 5], ["due", base + 10], ["settle", 1, False, base + 11],
         ["settle", 1, False, base + 80], ["settle", 1, True, base + 81], ["settle", 2, True, base + 2], ["due", base + 100],
         ["stale", base + 0.5, base + 100], ["stale", "x", base + 100], ["stale", True, base + 100],
         ["expire", base + 7 * 86400 + 2], ["refusals", "ntfy", base], ["refusals", "pigeon", base],
         ["enqueue", ["ntfy"], "nope", None, None, base], ["enqueue", ["pigeon"], "recovered", None, None, base],
         ["alias", 0], ["alias", 1], ["alias", 9999], ["alias", 10000], ["alias", True], ["alias", "1"]]
steps += [["enqueue", ["ntfy", "webhook", "telegram", "email"], "needs_you", "usage_limit", None, base + 200 + i]
          for i in range(9)] + [["waiting", base + 300]]
scenario("outbox1", steps)
'''

SEND = r'''
BOT = "123456789:" + "T" * 35
KEPT = {"ntfy_url": "https://ntfy.example.com/a-topic-made-up", "webhook_url": "https://hooks.example.com/in/made-up#frag",
        "webhook_token": "made-up-bearer", "telegram_token": BOT, "telegram_chat": "-1001234567890"}
rows = [{"event": "recovered", "category": "usage_limit", "alias": "task 2", "at": 1700000000.0},
        {"event": "needs_you", "category": None, "alias": None, "at": None},
        {"event": "usage_limit_detected", "category": "사용", "alias": "task 9999", "at": 1700000000},
        {"event": "test", "at": float("nan")}, {"event": "failed", "at": True}]
replies = [[{"status": 200, "body": [111, 107]}], [{"status": 302}], [{"raise": "HTTPError", "code": 503}],
           [{"raise": "HTTPError", "code": "x"}], [{"raise": "URLError_ssl"}], [{"raise": "URLError"}], [{"raise": "timeout"}],
           [{"raise": "ValueError"}], [{"status": 200, "read_raise": "timeout"}], [{"status": 200, "expired": True}],
           [{"status": None}], []]
def send(locale, channel, row, kept, script):
    opener = Opener(script)
    statement_locale = locale
    try:
        answer = {"ok": channels.send(channel, row, Secrets(kept), opener=opener, locale=statement_locale)}
    except Exception as error:
        answer = failure(error)
    return {"answer": answer, "requests": opener.seen}
for channel in ["ntfy", "webhook", "telegram", "email", "pigeon"]:
    for row in rows:
        for locale in ["en", "ko"]:
            case("channels.send", LOCALES, locale, channel, row, KEPT, replies[0],
                 ref=lambda c=channel, r=row, l=locale: send(l, c, r, KEPT, replies[0]))
for script in replies:
    case("channels.send", LOCALES, "en", "webhook", rows[0], KEPT, script,
         ref=lambda s=script: send("en", "webhook", rows[0], KEPT, s))
for kept in [{}, {"webhook_url": "http://hooks.example.com/"}, {"webhook_url": "https://hooks.example.com/", "webhook_token": "a b"},
             {"telegram_token": "bad", "telegram_chat": "1"}, {"telegram_token": BOT, "telegram_chat": "x"},
             {"ntfy_url": "https://127.0.0.1/t"}, {"smtp": "{"}, {"smtp": '{"host": "localhost"}'}]:
    for channel in ["ntfy", "webhook", "telegram", "email"]:
        case("channels.send", LOCALES, "en", channel, rows[0], kept, replies[0],
             ref=lambda c=channel, k=kept: send("en", c, rows[0], k, replies[0]))
for event, category, task, at in [("recovered", "usage_limit", "task 1", 1700000000.5), ("restarted", None, None, None),
                                  ("pigeon", "", "", 0), ("test", "c", None, -5.0)]:
    for locale in ["en", "ko", "ar", "xx", None]:
        case("channels.lines", LOCALES, locale, event, category, task, at,
             ref=lambda e=event, c=category, t=task, a=at, l=locale: channels.lines(e, c, t, a, l if l else "en"))
'''

DRAIN = r'''
KEPT = {"ntfy_url": "https://ntfy.example.com/a-topic-made-up", "webhook_url": "https://hooks.example.com/in/made-up",
        "telegram_token": "123456789:" + "T" * 35, "telegram_chat": "42"}
def drain(name, now, options, rows, script, refusals=()):
    home = home_of(name)
    probe = Probe(home, now, {"push_notices": "armed"})
    state = probe.state
    for channel, value in options.items():
        state.set_option("push_notices", OptionKey(channel), value, generation=state.meta()["generation"],
                         actor=Actor.DASHBOARD)
    for code in refusals:
        state.counted("push_notices", code)
    for row in rows:
        outbox.enqueue(state, *row)
    opener = Opener(script)
    import codex_auto_resume_advanced.statement as statement
    original = channels.lines
    channels.lines = lambda event, category=None, task=None, at=None, locale=None: original(event, category, task, at, "en")
    try:
        answer = {"ok": channels.drain(probe, Secrets(KEPT), opener=opener)}
    except Exception as error:
        answer = failure(error)
    finally:
        channels.lines = original
    state.close()
    case("channels.drain", home, LOCALES, now, {"push_notices": "armed"}, options, KEPT,
         [list(row) for row in rows], script, list(refusals), ref=lambda: {"answer": answer, "requests": opener.seen})
now = 1700000100.0
rows = [(["ntfy", "webhook", "telegram", "email"], "recovered", "usage_limit", "task 1", now - 50)]
drain("drain1", now, {"ntfy": 1, "webhook": 1, "telegram": 1, "email": 2}, rows,
      [{"status": 200}, {"raise": "HTTPError", "code": 404}, {"raise": "URLError_ssl"}])
drain("drain2", now, {"ntfy": 1}, [(["ntfy"], "failed", None, None, now - 7 * 86400 - 1), (["ntfy"], "failed", None, None, now)],
      [{"raise": "HTTPError", "code": 403}], refusals=["refused_ntfy_4xx"] * 19)
drain("drain3", now, {"ntfy": 1, "webhook": 1}, [(["ntfy", "webhook"], "needs_you", None, None, now - 100)],
      [{"raise": "timeout"}, {"raise": "ValueError"}])
'''

PAIR = r'''
BOT = "123456789:" + "T" * 35
def pair(name, now, kept, code, script, steps, states):
    home = home_of(name)
    probe = Probe(home, now, states)
    if code is not None:
        keep.begin_pairing(probe.state, code, now)
    opener, secrets = Opener(script), Secrets(kept)
    clock = iter(steps)
    try:
        answer = {"ok": channels.pair(probe, secrets, opener=opener, clock=lambda: next(clock, float("inf")),
                                      sleep=lambda seconds: None)}
    except Exception as error:
        answer = failure(error)
    probe.state.close()
    case("channels.pair", home, now, states, kept, code, script, steps,
         ref=lambda: {"answer": answer, "requests": opener.seen, "secrets": dict(sorted(secrets.kept.items())), "trips": probe.trips})
now = 1700000000.0
def message(update, text, chat, **chat_fields):
    return {"update_id": update, "message": {"text": text, "chat": dict({"id": chat}, **chat_fields), "date": 1}}
def reply(*updates):
    return {"status": 200, "body": list(json.dumps({"ok": True, "result": list(updates)}).encode())}
import json
pair("pair1", now, {"telegram_token": BOT}, "123456",
     [reply(message(7, "hello", 5), message(8, " 123456 ", 99, title="Family"))], [now, now + 1, now + 2, now + 3], {})
pair("pair2", now, {"telegram_token": BOT}, "123456",
     [reply(*[message(10 + i, "%06d" % i, 5) for i in range(5)])], [now, now + 1, now + 2, now + 3],
     {"telegram_remote": "armed"})
pair("pair3", now, {"telegram_token": BOT}, "123456", [{"raise": "HTTPError", "code": 409}, {"raise": "HTTPError", "code": 401}],
     [now, now + 1, now + 2, now + 3, now + 4, now + 5], {})
pair("pair4", now, {"telegram_token": "bad"}, "123456", [], [now], {})
pair("pair5", now, {"telegram_token": BOT}, None, [], [now], {})
pair("pair6", now, {"telegram_token": BOT}, "123456", [reply(), {"status": 200, "body": list(b"{")}],
     [now, now + 10, now + 50, now + 119, now + 121], {})
'''

SERVE = r'''
import json as _json
from codex_auto_resume_advanced.courier.api import Server, Gate, Service, Running
TOKEN = "made-up-token-0123456789"
rows = [{"interruption_id": "a", "state": "waiting_retry"}, {"interruption_id": "b", "state": "pending_open"}]
def serve(name, states, token, lan, requests):
    home = home_of(name)
    probe = Probe(home, 1700000000.0, states)
    layer = layer_of(rows)
    secrets = types.SimpleNamespace(read=lambda capability, key: token)
    service = Service(probe, 0, lan, layer=layer, secrets=secrets, clock=probe.clock)
    service.status = lambda: {"watcher": "running", "recovery": "on", "pending": len(rows), "states": {},
                              "next_check_at": None, "written_at": probe.clock()}
    service.page = lambda: b"<!doctype html>page"
    server = Server(("127.0.0.1", 0), service, Gate(probe.clock))
    service.port = server.server_address[1]
    running = Running(server)
    port, answers = service.port, []
    for raw in requests:
        data = raw.replace("{port}", str(port)).encode("latin-1")
        with socket.create_connection(("127.0.0.1", port), timeout=15) as connection:
            connection.sendall(data)
            connection.shutdown(socket.SHUT_WR)
            got = b""
            while True:
                piece = connection.recv(65536)
                if not piece:
                    break
                got += piece
        lines = got.decode("latin-1").split("\r\n")
        answers.append("\r\n".join("Date: DATE" if line.startswith("Date: ") else line.replace(":%d" % port, ":{port}")
                                   for line in lines))
    running.close()
    probe.state.close()
    case("api.serve", home, 1700000000.0, states, token, rows, lan, [list(r.encode("latin-1")) for r in requests],
         list(b"<!doctype html>page"), ref=lambda: {"answers": answers, "asked": layer.asked})
H = "Host: 127.0.0.1:{port}\r\n"
A = "Authorization: Bearer " + TOKEN + "\r\n"
snap = remote.snapshot(rows)
body = _json.dumps({"snapshot": snap})
requests = ["GET / HTTP/1.1\r\n" + H + "\r\n", "GET /status.json HTTP/1.1\r\n" + H + A + "\r\n",
            "GET /status.json HTTP/1.1\r\n" + H + "\r\n", "GET /status.json HTTP/1.1\r\n" + H + "Authorization: Bearer x\r\n\r\n",
            "GET /status.json HTTP/1.1\r\nHost: evil.example:{port}\r\n" + A + "\r\n",
            "GET /status.json HTTP/1.1\r\n" + H + H + A + "\r\n", "GET /metrics HTTP/1.0\r\n" + H + A + "\r\n",
            "GET /pending?token=x HTTP/1.1\r\n" + H + A + "\r\n", "HEAD /pending HTTP/1.1\r\n" + H + A + "\r\n",
            "POST /pending HTTP/1.1\r\n" + H + A + "\r\n", "GET /nope HTTP/1.1\r\n" + H + "\r\n",
            "POST /pause HTTP/1.1\r\n" + H + A + "\r\n", "OPTIONS / HTTP/1.1\r\n" + H + "\r\n",
            "POST /cancel/2 HTTP/1.1\r\n" + H + A + "Content-Length: %d\r\n\r\n%s" % (len(body), body),
            "POST /cancel/2 HTTP/1.1\r\n" + H + A + "Content-Length: 16\r\n\r\n{\"snapshot\": 1}",
            "POST /cancel/1 HTTP/1.1\r\n" + H + A + "Content-Length: 2000\r\n\r\n",
            "POST /cancel/1 HTTP/1.1\r\n" + H + A + "Content-Length: x\r\n\r\n",
            "POST /cancel/1 HTTP/1.1\r\n" + H + A + "Content-Length: -1\r\n\r\n",
            "POST /cancel/1 HTTP/1.1\r\n" + H + A + "Content-Length: 3\r\n\r\n[1]",
            "FOO / HTTP/1.1\r\n" + H + "\r\n", "GET / HTTP/2.0\r\n\r\n", "GET / HTTP/1.x\r\n\r\n", "GET /\r\n" + H + "\r\n",
            "POST /\r\n\r\n", "GET\r\n\r\n", "GET / HTTP/1.1 extra\r\n\r\n", "get / HTTP/1.1\r\n" + H + "\r\n",
            "GET //status.json HTTP/1.1\r\n" + H + A + "\r\n", "GET / HTTP/1.1\r\n" + "X: y\r\n" * 101 + "\r\n",
            "GET / HTTP/1.1\r\nHost: localhost:{port}\r\n\r\n", "GET / HTTP/1.1\r\n\r\n", ""]
serve("serve1", {"local_api": "armed", "local_api_actions": "armed"}, TOKEN, False, requests)
serve("serve2", {"local_api": "armed"}, TOKEN, False, ["POST /pause HTTP/1.1\r\n" + H + A + "\r\n"])
serve("serve3", {"local_api": "armed"}, None, True,
      ["GET /status.json HTTP/1.1\r\nHost: 10.0.0.9:{port}\r\n" + A + "\r\n"] +
      ["GET /status.json HTTP/1.1\r\n" + H + "Authorization: Bearer wrong\r\n\r\n"] * 11)
'''


class CourierStateDiff(advcourier.CourierDiff):
    def test_outbox(self):
        self.courier(OUTBOX + "\nfinish()\n", label="outbox", homes=["outbox1"])

    def test_send_and_lines(self):
        self.courier(SEND + "\nfinish()\n", label="send", expect_cases=80)

    def test_drain(self):
        self.courier(DRAIN + "\nfinish()\n", label="drain", expect_cases=3, homes=["drain1", "drain2", "drain3"])

    def test_pair(self):
        self.courier(PAIR + "\nfinish()\n", label="pair", expect_cases=6,
                     homes=["pair1", "pair2", "pair3", "pair6"])

    def test_loopback_api(self):
        self.courier(SERVE + "\nfinish()\n", label="serve", expect_cases=3)
