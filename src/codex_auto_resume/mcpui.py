"""The settings panel Codex renders inside the conversation.

One self-contained page: no network, no CDN, no framework, no fonts to fetch. A widget
that reaches for a script it cannot load is a blank rectangle, and this one has to work
on a machine whose whole point is that its network just failed.

It renders from the schema the tool returns rather than from a hardcoded list of
fields, so it shows exactly what the settings module defines - the same source the
standalone window and the command line render from.

The host API is feature-detected. Different hosts expose the widget bridge under
different names, and a version that assumed one of them would silently show a panel
whose Save button does nothing. When no bridge is found the page says so plainly and
falls back to being a readable summary, which is still worth showing.
"""
from __future__ import annotations

import json

from . import brand

# The page is delivered as one resource, so the style lives in it. Every colour comes
# from the shared palette, which is what keeps this panel, the settings window and the
# icon the same product rather than three that happen to ship together.
_STYLE = """
:root {
  color-scheme: light dark;
  %(light)s
}
@media (prefers-color-scheme: dark) {
  :root { %(dark)s }
}
* { box-sizing: border-box; }
body { margin: 0; padding: 16px; background: var(--canvas); color: var(--ink);
       font: 14px/1.5 -apple-system, "Segoe UI", system-ui, sans-serif; }

/* The card is one object, repeated: same edge, same rail, same inner padding, so the
   eye reads a list of sections rather than a pile of boxes. */
.card { background: var(--surface); border: 1px solid var(--line);
        border-left: 3px solid var(--accent); border-radius: 8px; padding: 14px 16px; }
.card h2 { margin: 0 0 10px; font-size: 12px; letter-spacing: .06em; text-transform: uppercase;
           color: var(--muted); font-weight: 600; }

/* State leads. Whether the watcher is running is the reason the panel gets opened, so
   it is the first thing on it and the largest type on it. */
.hero { margin-bottom: 14px; }
.eyebrow { font-size: 11px; letter-spacing: .08em; text-transform: uppercase;
           color: var(--muted); font-weight: 600; margin-bottom: 6px; }
.headline { display: flex; align-items: center; gap: 10px; margin: 0; font-size: 19px;
            line-height: 1.25; font-weight: 650; }
.facts { display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
         color: var(--muted); margin-top: 4px; }
.dot { width: 11px; height: 11px; border-radius: 50%%; background: var(--idle); flex: none; }
.dot.on { background: var(--active); }

/* Two columns of stacked cards rather than three loose cells. A plain auto-fit grid
   put the third card alone on a second row with a hole beside it; columns keep the
   reading order and fill the space. Below the breakpoint auto-fit collapses to one
   column and the cards stack in the same order. */
.grid { display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
        align-items: start; margin-bottom: 14px; }
.col { display: flex; flex-direction: column; gap: 12px; }
label.row { display: flex; align-items: center; gap: 9px; padding: 4px 0; cursor: pointer; }
label.row.sub { padding-left: 18px; }
label.row.master { font-weight: 600; }
label.field { display: flex; align-items: center; justify-content: space-between;
              gap: 12px; padding: 5px 0; }
input[type=number], select { background: var(--canvas); color: var(--ink);
        border: 1px solid var(--line); border-radius: 6px; padding: 4px 6px; font: inherit; }
input[type=number] { width: 72px; }
input[type=checkbox] { accent-color: var(--accent); width: 15px; height: 15px; }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

footer { display: flex; align-items: center; gap: 10px; margin-top: 4px; flex-wrap: wrap; }
button { font: inherit; padding: 7px 14px; border-radius: 7px; cursor: pointer;
         border: 1px solid var(--line); background: var(--surface); color: var(--ink); }
button.primary { background: var(--accent); border-color: var(--accent);
                 color: var(--on-accent); }
button[disabled] { opacity: .5; cursor: default; }
.note { color: var(--muted); }

/* Wide content scrolls inside its own box; the panel itself never scrolls sideways. */
.pending { margin-bottom: 14px; }
.scroll { overflow-x: auto; }
.pending table { width: 100%%; border-collapse: collapse; }
.pending th, .pending td { text-align: left; padding: 5px 10px 5px 0;
                           border-bottom: 1px solid var(--line);
                           font-variant-numeric: tabular-nums; white-space: nowrap; }
.pending tr:last-child td { border-bottom: 0; }
.pending th { color: var(--muted); font-weight: 500; font-size: 12px;
              letter-spacing: .03em; text-transform: uppercase; }
.state { display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: 12px;
         background: var(--canvas); border: 1px solid var(--line); color: var(--muted); }
code { font-family: ui-monospace, Consolas, monospace; font-size: 12px; }
"""

# Resolved once, at import: the palette is a build-time fact, not a per-request one.
_STYLE = _STYLE % {"light": brand.css_variables(brand.LIGHT),
                   "dark": brand.css_variables(brand.DARK)}

_SCRIPT = r"""
// The widget bridge is whatever the host provides. Try the documented shape first,
// then the ones seen in practice, and degrade to read-only rather than pretending.
function bridge() {
  var hosts = [window.openai, window.webplus, window.mcp, window.parent && window.parent.openai];
  for (var i = 0; i < hosts.length; i++) {
    var host = hosts[i];
    if (host && typeof host.callTool === 'function') return host;
  }
  return null;
}

function initialData() {
  var host = bridge() || window.openai || {};
  var output = host.toolOutput || host.output || window.__CODEX_AUTO_RESUME__;
  if (typeof output === 'string') { try { output = JSON.parse(output); } catch (e) { output = null; } }
  return output || null;
}

var HOST = bridge();
var DATA = initialData();
var EDITORS = {};

var LABELS = {
  usage_limit: 'Usage limits', network_transient: 'Network failures', timeout: 'Timeouts',
  rate_limit_transient: 'Temporary rate limits', server_5xx: 'Server errors',
  stream_interrupted: 'Stream interruptions', interruption: 'Interruption detected',
  starting: 'Recovery starting', result: 'Recovery result',
  stopped: 'Stopped or out of attempts', notifications: 'Show notifications',
  max_recovery_attempts: 'Attempts per interruption', max_no_progress: 'Stop after no progress',
  retry_timing: 'Retry timing'
};

function label(name) {
  var key = name.replace(/^recover_/, '').replace(/^notify_/, '');
  if (LABELS[name]) return LABELS[name];
  if (LABELS[key]) return LABELS[key];
  key = key.replace(/_/g, ' ');
  return key.charAt(0).toUpperCase() + key.slice(1);
}

function element(tag, className, text) {
  var node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function card(title) {
  var node = element('section', 'card');
  node.appendChild(element('h2', null, title));
  return node;
}

function checkbox(entry, value, extra) {
  var row = element('label', 'row' + (extra ? ' ' + extra : ''));
  var input = document.createElement('input');
  input.type = 'checkbox';
  input.checked = !!value;
  input.disabled = !HOST;
  row.appendChild(input);
  row.appendChild(element('span', null, label(entry.name)));
  EDITORS[entry.name] = function () { return input.checked; };
  return row;
}

function field(entry, value) {
  var row = element('label', 'field');
  row.appendChild(element('span', null, label(entry.name)));
  var input;
  if (entry.choices) {
    input = document.createElement('select');
    entry.choices.forEach(function (choice) {
      var option = document.createElement('option');
      option.value = choice; option.textContent = choice;
      if (choice === value) option.selected = true;
      input.appendChild(option);
    });
    EDITORS[entry.name] = function () { return input.value; };
  } else {
    input = document.createElement('input');
    input.type = 'number';
    if (entry.min !== undefined) input.min = entry.min;
    if (entry.max !== undefined) input.max = entry.max;
    input.value = value;
    EDITORS[entry.name] = function () { return Number(input.value); };
  }
  input.disabled = !HOST;
  row.appendChild(input);
  return row;
}

function renderPending(rows) {
  if (!rows || !rows.length) return null;
  var box = element('section', 'card pending');
  box.appendChild(element('h2', null, 'Waiting to resume'));
  var scroll = element('div', 'scroll');
  var table = document.createElement('table');
  var head = document.createElement('tr');
  ['Conversation', 'State', 'Attempts'].forEach(function (name) {
    head.appendChild(element('th', null, name));
  });
  table.appendChild(head);
  rows.slice(0, 8).forEach(function (row) {
    var line = document.createElement('tr');
    var first = element('td');
    // The exact thread id, shortened for display only. Every action this panel can
    // take addresses a record by its full interruption id, never by what is shown.
    var name = element('code', null, row.name || row.thread_id.slice(0, 8));
    first.appendChild(name);
    line.appendChild(first);
    var state = element('td');
    state.appendChild(element('span', 'state', row.state.replace(/_/g, ' ')));
    line.appendChild(state);
    line.appendChild(element('td', null, String(row.recovery_attempts)));
    table.appendChild(line);
  });
  scroll.appendChild(table);
  box.appendChild(scroll);
  if (rows.length > 8) {
    box.appendChild(element('p', 'note', 'and ' + (rows.length - 8) + ' more'));
  }
  return box;
}

function render() {
  var root = document.getElementById('root');
  root.textContent = '';
  if (!DATA) {
    root.appendChild(element('p', 'note', 'Settings are not available in this view.'));
    return;
  }
  var status = DATA.status || {};
  var values = DATA.settings || {};
  var schema = DATA.schema || [];

  // State first, in the largest type on the page. The product name is an eyebrow
  // rather than a heading: inside Codex the panel is already attributed, and the
  // question a reader arrives with is whether anything is being recovered.
  var hero = element('section', 'card hero');
  hero.appendChild(element('div', 'eyebrow', 'Codex Auto Resume · v' + (status.version || '?')));
  var headline = element('h1', 'headline');
  headline.appendChild(element('span', 'dot' + (status.watcher_running && status.enabled ? ' on' : '')));
  var watcher = status.watcher_running === true ? 'Watching for interruptions'
              : status.watcher_running === false ? 'Watcher not running' : 'Watcher status unknown';
  if (status.watcher_running === true && !status.enabled) watcher = 'Watching paused';
  headline.appendChild(element('span', null, watcher));
  hero.appendChild(headline);

  // Two facts under it, most consequential first: whether recovery can happen at all,
  // and then what is waiting on it.
  var count = status.pending || 0;
  var recovery = status.watcher_running !== true ? 'Nothing will be recovered until it is running'
               : status.enabled ? 'Automatic recovery is on'
               : 'Automatic recovery is paused';
  var facts = element('div', 'facts');
  facts.appendChild(element('span', null, recovery));
  facts.appendChild(element('span', null, '·'));
  facts.appendChild(element('span', null, count === 0 ? 'Nothing pending'
                    : count === 1 ? '1 recovery pending' : count + ' recoveries pending'));
  hero.appendChild(facts);
  root.appendChild(hero);

  // What is waiting comes before what is configured: it is the part that changes.
  var pending = renderPending(DATA.pending);
  if (pending) root.appendChild(pending);

  var grid = element('div', 'grid');
  var groups = {recovery: card('Automatic recovery'), limits: card('Limits'),
                notifications: card('Notifications')};
  schema.forEach(function (entry) {
    var host = groups[entry.group];
    if (!host) return;
    var value = values[entry.name];
    if (entry.type === 'boolean') {
      host.appendChild(checkbox(entry, value,
        entry.master ? 'master' : (entry.group === 'notifications' ? 'sub' : '')));
    } else {
      host.appendChild(field(entry, value));
    }
  });
  // What may be recovered on the left; how hard it tries and what it says on the right.
  var left = element('div', 'col');
  left.appendChild(groups.recovery);
  var right = element('div', 'col');
  right.appendChild(groups.limits);
  right.appendChild(groups.notifications);
  grid.appendChild(left);
  grid.appendChild(right);
  root.appendChild(grid);

  var footer = element('footer');
  var save = element('button', 'primary', 'Save');
  var pause = element('button', null, status.enabled ? 'Pause recovery' : 'Resume recovery');
  var message = element('span', 'note');
  save.disabled = !HOST;
  pause.disabled = !HOST;
  footer.appendChild(save);
  footer.appendChild(pause);
  // Offered only when it is the thing that is wrong. Nothing is recovered while the
  // watcher is stopped, so a panel that reports it and offers no way out is a dead end.
  var start = null;
  if (status.watcher_running === false) {
    start = element('button', null, 'Start watcher');
    start.disabled = !HOST;
    footer.appendChild(start);
  }
  footer.appendChild(message);
  root.appendChild(footer);

  if (!HOST) {
    message.textContent = 'Read-only here. Use the Codex Auto Resume settings window to change these.';
    return;
  }

  save.onclick = function () {
    var changes = {};
    Object.keys(EDITORS).forEach(function (name) { changes[name] = EDITORS[name](); });
    save.disabled = true;
    message.textContent = 'Saving...';
    HOST.callTool('update_settings', changes).then(function () {
      message.textContent = 'Saved.';
      save.disabled = false;
    }, function (error) {
      message.textContent = 'Not saved: ' + (error && error.message ? error.message : 'refused');
      save.disabled = false;
    });
  };

  pause.onclick = function () {
    pause.disabled = true;
    HOST.callTool('set_auto_recovery', {enabled: !status.enabled}).then(function () {
      status.enabled = !status.enabled;
      render();
    }, function () { pause.disabled = false; });
  };

  if (start) {
    start.onclick = function () {
      start.disabled = true;
      message.textContent = 'Starting...';
      HOST.callTool('start_watcher', {}).then(function (result) {
        // Do not assume it worked. The panel used to set watcher_running to true here
        // and render a running watcher on the strength of the call not throwing, which
        // is a claim about a process nobody had looked at yet. Ask instead.
        // Hosts differ on whether they hand back the tool result or just its
        // structured half, so look in both rather than depending on one.
        var payload = (result && result.structuredContent) || result || {};
        var state = payload.state;
        if (state === 'running' || state === 'already-running') {
          status.watcher_running = true;
          message.textContent = '';
        } else if (state === 'exited') {
          message.textContent = 'It started and stopped again; nothing is watching.';
          start.disabled = false;
        } else {
          message.textContent = 'Started, but not confirmed running yet. Refresh in a moment.';
          start.disabled = false;
        }
        render();
      }, function (error) {
        message.textContent = 'Could not start it: ' + (error && error.message ? error.message : 'refused');
        start.disabled = false;
      });
    };
  }
}

render();
"""


def settings_page(data=None) -> str:
    """The panel as one HTML document.

    ``data`` is only ever used for a preview: in Codex the values arrive from the tool
    result, so the served page carries no settings of its own and cannot go stale
    between being read and being shown.
    """
    seed = ""
    if data is not None:
        seed = "<script>window.__CODEX_AUTO_RESUME__=%s;</script>" % json.dumps(
            data, ensure_ascii=False, default=str).replace("<", "\\u003c")
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>Codex Auto Resume</title><style>%s</style></head>"
        "<body><div id=\"root\"></div>%s<script>%s</script></body></html>"
        % (_STYLE, seed, _SCRIPT))
