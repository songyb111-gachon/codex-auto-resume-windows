"""The courier's pure rules against the v0.6.26 tag (seat S7.3b): every address check, the chat's name, the status page's
reading, the e-mail message as smtplib flattens it, Telegram's commands and update ids, the remote listing and metrics,
the loopback server's routes, Host gate, clients, header block and lock, and the push events.

    python -X utf8 tests/rustdiff/run.py --build --reference v0.6.26 --reference-python bundled -k diffs_advcourier
"""
from __future__ import annotations

from rustdiff import advcourier

ADDRESSES = r'''
import itertools

def _ok(check, value):
    try:
        return {"ok": check(value)}
    except address.AddressRefused as refused:
        return {"refused": refused.word}
urls = ["https://ntfy.example.org/topic", "https://NTFY.Example.ORG/x?y#z", "http://ntfy.example.org/", "HTTPS://a.b",
        "https://user@example.org/", "https://u:p@example.org/", "https://@example.org/", "https://127.0.0.1/",
        "https://[::1]/", "https://[::ffff:1.2.3.4]:443/", "https://[v1.x]/", "https://[1.2.3.4]/", "https://[::1/",
        "https://a.localhost/", "https://localhost:8080/", "https://intranet/", "https://example.org:0/",
        "https://example.org:65535/", "https://example.org:65536/", "https://example.org:x/", "https://example.org:+1/",
        "https://example.org:00443/", "https://exa／mple.org/", "https://exämple.org/", "https://exKample.org/",
        "https://-a.example.org/", "https://a-.example.org/", "https://" + "a" * 64 + ".example.org/",
        "https://example.org./", "https://example..org/", "https://1.2.3/", "https://01.2.3.4/", "https://256.1.1.1/",
        "https://fe80::1%25eth0/", "https://[fe80::1%25eth0]/", "https://example.org/é", "https://example.org/ x",
        "https://example.org/\x7f", "", "https:", "https://", "//example.org/", "https:example.org", "a" * 2049,
        "https://example.org/" + "a" * 2028, None, 5, ["https://example.org/"], "https://[::1]]/", "https://[]/",
        "https://1:2:3:4:5:6:7:8/", "https://[1:2:3:4:5:6:7:8]/", "https://[1::2::3]/", "https://[::]/",
        "https://[" + "0:" * 7 + "0000000000000000000000000000000000001]/", "https://xn--n3h.example/",
        "https://example.org:443:443/", "https://example.org。com/"]
for url in urls:
    case("address.url", url, ref=lambda url=url: _ok(address.checked_url, url))
tokens = ["abc", "", " a", "a b", "x" * 512, "x" * 513, "é", "123456789:" + "T" * 35, "123:" + "_-" * 10,
          "1" * 21 + ":" + "a" * 20, "12:" + "a" * 19, "-123", "123", "-", "1" * 20, "1" * 21, None, 7]
for token, shape in itertools.product(tokens, [None, "telegram_token", "telegram_chat"]):
    pattern = {"telegram_token": address.TELEGRAM_TOKEN, "telegram_chat": address.TELEGRAM_CHAT}.get(shape)
    case("address.token", token, shape, ref=lambda t=token, p=pattern: _ok(lambda v: address.checked_token(v, shape=p), t))
boxes = ["me@example.com", "a.b+c@mail.example.org", ".a@example.com", "a..b@example.com", "a@b.c", "a@localhost",
         "a@127.0.0.1", "a@b", "@example.com", "a@@example.com", "a b@example.com", "a\n@example.com", "x" * 65 + "@ex.com",
         "a@" + "b" * 250 + ".com", "é@example.com", "a/b=c?d^e@ex.org", None, 3]
for box in boxes:
    case("address.mailbox", box, ref=lambda b=box: _ok(address.checked_mailbox, b))
good = {"host": "smtp.example.com", "port": 465, "user": "me@example.com", "password": "made-up-pw",
        "from": "me@example.com", "to": "phone@example.com"}
blobs = [good, dict(good, port=587), dict(good, port=25), dict(good, port=True), dict(good, port="465"),
         dict(good, host="127.0.0.1"), dict(good, host="localhost"), dict(good, host=None), dict(good, user="a b"),
         dict(good, password=""), dict(good, to="bad"), dict(good, extra=1), {k: v for k, v in good.items() if k != "to"},
         [], None, dict(good, port=465.0)]
for blob in blobs:
    case("address.smtp", blob, ref=lambda b=blob: _ok(address.checked_smtp, b))
for host in ["example.org", "EXAMPLE.org.", "a", "", None, "1.2.3.4", "[::1]", "x.localhost", "a" * 254, "K.example"]:
    case("address.host", host, ref=lambda h=host: address.host_problem(h))
for args in [(47615, None, None), (1, "tok", None), (2, "", "192.168.1.2"), (3, "t#x", "10.0.0.1")]:
    case("address.web_view", *args, ref=lambda a=args: address.web_view(*a))

'''

KEEP_FEED_MIME = r'''
import json
for chat in [{"title": "Family"}, {"title": "  "}, {"title": " ​A\x07B "}, {"username": "bot_x"}, {"username": ""},
             {"title": "", "username": "u"}, {"title": "x" * 80}, {"title": 5, "username": "u"}, {}, None, [], "chat",
             {"title": "😀 smile"}, {"title": " line"}]:
    case("keep.label", chat, ref=lambda c=chat: keep.chat_label(c))
for code in ["123456", "000000", "999999"]:
    case("keep.digest", code, ref=lambda c=code: keep.digest(c))
summaries = [
    {"status": {"indicator": "none"}, "components": [{"name": "Codex in ChatGPT Desktop", "status": "operational"}], "incidents": []},
    {"status": {"indicator": "minor"}, "components": [{"name": "API"}, {"name": "Codex", "status": "partial_outage"},
                                                       {"name": "Codex 2", "status": "major_outage"}], "incidents": [1] * 120},
    {"status": {"indicator": "critical"}, "components": [{"name": "Codex", "status": 3}], "incidents": "x"},
    {"status": {"indicator": "weird"}}, {"status": "none"}, [], "x", {"components": {"name": "Codex"}}, {},
    {"status": {"indicator": ["none"]}, "components": [5, None, {"name": None}, {"name": "codex", "status": "operational"}]},
]
raws = [json.dumps(each).encode() for each in summaries] + [b"", b"\xff", b"\xef\xbb\xbf{}", b"{", b"NaN",
        b'{"status": {"indicator": "major"}, "status": {"indicator": "none"}}', b"[" * 30 + b"]" * 30,
        b" " * 65535 + b"{}", b" " * 65534 + b"{}", b'{"incidents": [' + b"1," * 98 + b"1]}"]
for raw in raws:
    case("feed.parse", list(raw), ref=lambda r=raw: [str(x) if not isinstance(x, int) else x for x in feed.parse(r)])

from email.message import EmailMessage
import email.generator
def flat(subject, sender, to, text):
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = to
    message.set_content(text)
    out = io.BytesIO()
    email.generator.BytesGenerator(out).flatten(message, linesep="\r\n")
    return list(out.getvalue())
texts = ["Usage limit detected\ntask 1 · usage_limit · 12:30\nCodex Auto Resume (advanced)",
         "사용량 한도에 도달했습니다\nCodex Auto Resume (advanced)",
         "x" * 79, "From here on\n.dot line\nend", "사" * 30 + "\n" + "é" * 50, "a\rb\r\nc", "tail space \nx",
         "é" * 100, "", "only\n", "=" * 90 + "\n" + "é", "\t" * 80]
for text in texts:
    case("mime.flatten", "Codex Auto Resume: recovered", "me@example.com", "phone@example.com", text,
         ref=lambda t=text: flat("Codex Auto Resume: recovered", "me@example.com", "phone@example.com", t))
case("mime.flatten", "Codex Auto Resume: test", "a.b+c@mail.example.org", "x/y=z@example.org", "hi",
     ref=lambda: flat("Codex Auto Resume: test", "a.b+c@mail.example.org", "x/y=z@example.org", "hi"))
'''

TELEGRAM_REMOTE_API = r'''
import json
for text in ["/status", "/STATUS", "/status@MyBot", "/status now", "/list", "/cancel 3", "/cancel task 3",
             "/cancel TASK 12", "/cancel 0", "/cancel 03", "/cancel 12345", "/cancel 1 2", "/cancel", "/continue 9999",
             "/pause", "/recovery-on", "/recovery-on x", "  /pause  ", "/cancel ٣", "/cancel 5", "hello", "",
             "/" + "x" * 64, "/cancel 1" + " " * 60, None, 5, "/CİNCEL 1"]:
    case("telegram.parse", text, ref=lambda t=text: list(telegram.parse(t)))
for raw in [b'{"ok":true,"result":[{"update_id":5}]}', b'{ "update_id" : 12345678901234567890 }', b'["update_id":3]',
            b'{"x":1, "update_id":7', b'nothing', b'{"update_id": -3}, {"update_id":4}', b'{\n"update_id":\t9}']:
    case("telegram.first_id", list(raw), ref=lambda r=raw: (lambda m: int(m.group(1)) if m else None)(telegram.UPDATE_ID.search(r)))
for raw in [b'{"ok":true,"result":[{"update_id":5},3,{"a":1}]}', b'{"ok":1,"result":[]}', b'{"ok":true,"result":{}}',
            b'{"ok":true}', b"[]", b"\xff", b"{"]:
    case("telegram.readable", list(raw), ref=lambda r=raw: telegram.readable(r))
rows = [{"interruption_id": "a", "state": "waiting_retry", "next_attempt_at": 100.0},
        {"interruption_id": 7, "state": "pending_open"}, {"interruption_id": None, "state": "held_for_person"}]
for listed in [rows, [], rows[:1]]:
    case("remote.pending", listed, ref=lambda l=listed: remote.pending(layer_of(l)))
snap = remote.snapshot(rows)
for alias, given in [("task 1", snap), ("task 3", snap), ("task 4", snap), ("task 0", snap), ("task 01", snap),
                     ("task 1", "0" * 16), ("task 1", snap.upper()), (5, snap), ("task 1", None), ("1", snap)]:
    case("remote.resolve", rows, alias, given, ref=lambda a=alias, g=given: remote.resolve(layer_of(rows), a, g))
steps = [["pause"], ["lift"], ["cancel", "task 2", snap], ["cancel", "task 9", snap], ["release", "task 1", snap]]
def acts(steps):
    made, answers = layer_of(rows), []
    for step in steps:
        try:
            found = {"pause": lambda: remote.pause(made), "lift": lambda: remote.lift_pause(made),
                     "cancel": lambda: remote.cancel(made, step[1], step[2]),
                     "release": lambda: remote.release(made, step[1], step[2])}[step[0]]()
            answers.append({"ok": found})
        except Exception as error:
            answers.append({"error": type(error).__name__})
    return {"answers": answers, "asked": made.asked}
case("remote.acts", rows, steps, ref=lambda: acts(steps))
documents = [{"watcher": "running", "recovery": "on", "pending": 2, "states": {"waiting_retry": 1, "pending_open": 1},
              "next_check_at": 1700000000.12345, "written_at": 1700000001.0},
             {"watcher": "stopped", "recovery": "paused", "pending": 0, "states": {}, "next_check_at": None, "written_at": 5},
             {"watcher": "running", "recovery": "on", "pending": True, "states": {}, "next_check_at": 0.0005, "written_at": 1e20}]
for document in documents:
    case("remote.metrics", document, ref=lambda d=document: remote.metrics(d))
for path in ["/", "/status.json", "/metrics", "/pending", "/pause", "/resume-off", "/cancel/", "/cancel/1", "/cancel/9999",
             "/cancel/10000", "/cancel/0", "/cancel/01", "/cancel/1?x=1", "/status.json#f", "/status.json?token=x",
             "/STATUS.json", "//status.json", "", "/cancel/1/", "/cancel/١"]:
    case("api.route", path, ref=lambda p=path: api.route_of(p))
for header, port, lan in [("127.0.0.1:47615", 47615, False), ("localhost:47615", 47615, False), ("LOCALHOST:5", 5, False),
                          ("127.0.0.1", 47615, False), ("192.168.1.5:47615", 47615, False), ("192.168.1.5:47615", 47615, True),
                          ("example.org:47615", 47615, True), ("[::1]:47615", 47615, True), ("01.2.3.4:1", 1, True),
                          ("127.0.0.1:476150", 47615, False), (":47615", 47615, True), ("127.0.0.1:47615 ", 47615, False)]:
    case("api.host", header, port, lan, ref=lambda h=header, p=port, l=lan: api.host_allowed(h, p, l))
for client in ["127.0.0.1", "127.9.9.9", "::1", "::ffff:127.0.0.1", "::ffff:10.0.0.2", "10.0.0.2", "fe80::1", "garbage",
               "2001:0db8:0000:0000:0000:0000:0000:0001"]:
    case("api.client", client, ref=lambda c=client: api.client_of(c))
import http.client as _client
for block in ["Host: a\r\n\r\n", "host:  a  \r\nHost: b\r\n\r\n", "Host: a\r\n b\r\n\r\n", " x\r\nHost: a\r\n\r\n",
              "garbage\r\nHost: a\r\n\r\n", ":v\r\nHost: a\r\n\r\n", "From x\r\nHost: a\r\n\r\n", "Host: a\rb\r\n\r\n",
              "Ho st: a\r\nHost: b\r\n\r\n", "Authorization:Bearer t\r\n\r\n", "Host: \xe9\r\n\r\n", "\r\n",
              "Host: a\nX: b\n\n"]:
    def parsed(block=block):
        message = _client.parse_headers(io.BytesIO(block.encode("latin-1")))
        return [[k, v] for k, v in message.items()]
    case("api.headers", block, ref=parsed)
def gate(steps):
    clock = [0.0]
    made, answers = api.Gate(lambda: clock[0]), []
    for kind, at, client in steps:
        clock[0] = at
        answers.append(made.wrong(client) if kind == "wrong" else made.closed(client))
    return {"answers": answers, "kept": [[k, v[0], v[1]] for k, v in made._clients.items()]}
steps = [["wrong", float(i), "loopback"] for i in range(10)] + [["closed", 20.0, "loopback"], ["closed", 400.0, "loopback"],
         ["wrong", 401.0, "10.0.0.1"], ["wrong", 470.0, "10.0.0.1"]]
steps += [["wrong", 500.0 + i, "10.1.%d.%d" % (i // 250, i % 250)] for i in range(260)] + [["closed", 900.0, "10.0.0.1"]]
case("api.gate", steps, ref=lambda: gate(steps))
for at in [0.0, 1764201600.7, 951782400.0, -1.5]:
    import email.utils
    case("api.date", at, ref=lambda a=at: email.utils.formatdate(a, usegmt=True))
for facts in [{"kind": "resumed"}, {"kind": "interruption", "category": "usage_limit"}, {"kind": "interruption"},
              {"kind": "memory_stopped"}, {"kind": "nope"}, {"kind": 5}, None, [], {"kind": "update_offered"}]:
    case("push.event", facts, ref=lambda f=facts: (lambda e: None if e is None else str(e))(push.event_of(f)))
for bits in [push.DEFAULT_EVENTS, 0, 127, True, "1", 1 << 40, -1]:
    for event in push.EVENTS:
        case("push.picked", bits, str(event), ref=lambda b=bits, e=event: push.picked(b, e))
case("push.constants", ref=lambda: {"events": [str(e) for e in push.EVENTS], "default": push.DEFAULT_EVENTS,
                                    "codes": list(outbox.codes())})
'''


class CourierPureDiff(advcourier.CourierDiff):
    def test_addresses(self):
        self.courier(ADDRESSES + "\nfinish()\n", label="addresses", expect_cases=150)

    def test_keep_feed_and_mail(self):
        self.courier(KEEP_FEED_MIME + "\nfinish()\n", label="keepfeed", expect_cases=30)

    def test_telegram_remote_and_api(self):
        self.courier(TELEGRAM_REMOTE_API + "\nfinish()\n", label="telegram", expect_cases=100)
