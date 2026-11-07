# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The loopback API's web view (v0.6.22, plans/v0619-design/D-remote.md): one small page, served at `/` by api.py.

It carries no data and needs no token itself: its script reads the token from the address's fragment - which a browser
never sends - and asks `status.json` and `pending` on this same origin with `Authorization: Bearer`, then writes what
they answered as text (textContent, never markup). Its Content-Security-Policy lets it load nothing from anywhere -
no other script, style, font, image or frame - and connect only to its own origin; it names no host, carries no
inline event handler and builds no markup from what it reads. Its words are the person's language's, from this
edition's catalog, put in as a JSON value escaped for a script.
"""
from __future__ import annotations

import html
import json

CSP = ("default-src 'none'; script-src 'self' 'unsafe-inline'; connect-src 'self'; style-src 'unsafe-inline'; "
       "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
# The page's words (`page.api.*`) and their English fallbacks.
WORDS = {"title": ("page.api.title", "Codex Auto Resume - this PC"),
         "watcher": ("page.api.watcher", "Watcher"),
         "recovery": ("page.api.recovery", "Recovery"),
         "pending": ("page.api.pending", "Waiting"),
         "next_check": ("page.api.next_check", "Next check"),
         "no_token": ("page.api.ask_token", "Open this page from the address the Dashboard copied: it carries the token."),
         "refused": ("page.api.refused", "The token was not accepted."),
         "running": ("page.api.word.running", "running"),
         "stopped": ("page.api.word.stopped", "stopped"),
         "on": ("page.api.word.on", "on"),
         "paused": ("page.api.word.paused", "paused"),
         "observe_only": ("page.api.word.observe_only", "only watching")}

TEMPLATE = """<!doctype html>
<html lang="%(lang)s"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer"><title>%(title)s</title>
<style>
body{font:15px/1.5 "Segoe UI",system-ui,sans-serif;margin:24px;color:#1f2328;background:#f6f7f9}
main{max-width:640px;margin:0 auto;background:#fff;border-radius:12px;padding:16px 20px;box-shadow:0 1px 3px #0002}
h1{font-size:18px;margin:0 0 12px}dl{display:grid;grid-template-columns:max-content 1fr;gap:4px 16px;margin:0}
dt{color:#59636e}ul{padding-left:18px}li{margin:2px 0}#note{color:#9a3412}
@media (prefers-color-scheme:dark){body{background:#16181c;color:#e6e6e6}main{background:#202328}dt{color:#9aa4ae}}
</style></head>
<body><main><h1 id="title"></h1><p id="note"></p><dl id="facts"></dl><ul id="tasks"></ul></main>
<script>
"use strict";
var W = %(words)s;
function text(id, value) { document.getElementById(id).textContent = value; }
function fact(name, value) {
  var dl = document.getElementById("facts"), dt = document.createElement("dt"), dd = document.createElement("dd");
  dt.textContent = name; dd.textContent = value; dl.appendChild(dt); dl.appendChild(dd);
}
function when(seconds) { return seconds ? new Date(seconds * 1000).toLocaleString() : "-"; }
text("title", W.title);
var token = location.hash.length > 1 ? decodeURIComponent(location.hash.slice(1)) : "";
if (!token) { text("note", W.no_token); }
else {
  var asked = { headers: { "Authorization": "Bearer " + token }, cache: "no-store", credentials: "omit",
                referrerPolicy: "no-referrer" };
  fetch("status.json", asked).then(function (reply) {
    if (!reply.ok) { throw new Error("refused"); }
    return reply.json();
  }).then(function (status) {
    fact(W.watcher, W[status.watcher] || status.watcher);
    fact(W.recovery, W[status.recovery] || status.recovery);
    fact(W.pending, String(status.pending));
    fact(W.next_check, when(status.next_check_at));
    return fetch("pending", asked).then(function (reply) { return reply.ok ? reply.json() : { pending: [] }; });
  }).then(function (listed) {
    var ul = document.getElementById("tasks");
    (listed.pending || []).forEach(function (row) {
      var li = document.createElement("li");
      li.textContent = row.task + " - " + row.state + " - " + when(row.next_check_at);
      ul.appendChild(li);
    });
  }).catch(function () { text("note", W.refused); });
}
</script></body></html>
"""


def render(catalog, locale="en") -> bytes:
    """The page in `catalog`'s words (a {key: text} of this edition's catalog), as UTF-8 bytes."""
    words = {name: (catalog.get(key) if isinstance(catalog.get(key), str) else fallback)
             for name, (key, fallback) in WORDS.items()}
    # A JSON value inside a script: every "<", ">" and "&" escaped, so no word can close the script or open markup.
    script = json.dumps(words, ensure_ascii=True).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    lang = locale if isinstance(locale, str) and locale.replace("-", "").isalnum() else "en"
    return (TEMPLATE % {"lang": html.escape(lang), "title": html.escape(words["title"]), "words": script}).encode("utf-8")
