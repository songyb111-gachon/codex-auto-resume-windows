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

# The page is delivered as one resource, so the style lives in it.
_STYLE = """
:root {
  color-scheme: light dark;
  --ink: #1f2428; --muted: #5e696e; --line: #e2e6e9;
  --surface: #ffffff; --canvas: #f5f6f7; --accent: #2f6f4e; --good: #2f8f5e;
}
@media (prefers-color-scheme: dark) {
  :root { --ink: #e8ecee; --muted: #9aa3a8; --line: #333a3f;
          --surface: #1c2023; --canvas: #14181a; --accent: #6dc79a; --good: #6dc79a; }
}
* { box-sizing: border-box; }
body { margin: 0; padding: 16px; background: var(--canvas); color: var(--ink);
       font: 14px/1.5 -apple-system, "Segoe UI", system-ui, sans-serif; }
h1 { margin: 0 0 4px; font-size: 16px; }
.status { display: flex; align-items: center; gap: 8px; color: var(--muted);
          margin-bottom: 16px; flex-wrap: wrap; }
.dot { width: 9px; height: 9px; border-radius: 50%; background: var(--muted); flex: none; }
.dot.on { background: var(--good); }
.grid { display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); }
.card { background: var(--surface); border: 1px solid var(--line); border-radius: 10px;
        padding: 14px 16px; }
.card h2 { margin: 0 0 10px; font-size: 13px; letter-spacing: .02em; text-transform: uppercase;
           color: var(--muted); }
label.row { display: flex; align-items: center; gap: 9px; padding: 4px 0; cursor: pointer; }
label.row.sub { padding-left: 18px; }
label.row.master { font-weight: 600; }
label.field { display: flex; align-items: center; justify-content: space-between;
              gap: 12px; padding: 5px 0; }
input[type=number], select { background: var(--canvas); color: var(--ink);
        border: 1px solid var(--line); border-radius: 6px; padding: 4px 6px; font: inherit; }
input[type=number] { width: 72px; }
footer { display: flex; align-items: center; gap: 10px; margin-top: 16px; flex-wrap: wrap; }
button { font: inherit; padding: 7px 14px; border-radius: 7px; cursor: pointer;
         border: 1px solid var(--line); background: var(--surface); color: var(--ink); }
button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
button[disabled] { opacity: .5; cursor: default; }
.note { color: var(--muted); }
.pending { margin-top: 14px; }
.pending table { width: 100%; border-collapse: collapse; }
.pending th, .pending td { text-align: left; padding: 5px 8px 5px 0; border-bottom: 1px solid var(--line);
                           font-variant-numeric: tabular-nums; }
.pending th { color: var(--muted); font-weight: 500; }
code { font-family: ui-monospace, Consolas, monospace; font-size: 12px; }
"""

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
  box.appendChild(element('h2', null, 'Pending'));
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
    line.appendChild(element('td', null, row.state.replace(/_/g, ' ')));
    line.appendChild(element('td', null, String(row.recovery_attempts)));
    table.appendChild(line);
  });
  box.appendChild(table);
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

  root.appendChild(element('h1', null, 'Codex Auto Resume'));
  var line = element('div', 'status');
  var dot = element('span', 'dot' + (status.watcher_running && status.enabled ? ' on' : ''));
  line.appendChild(dot);
  var watcher = status.watcher_running === true ? 'Watching for interruptions'
              : status.watcher_running === false ? 'Watcher not running' : 'Watcher status unknown';
  if (status.watcher_running === true && !status.enabled) watcher = 'Watching paused';
  line.appendChild(element('span', null, watcher));
  line.appendChild(element('span', null, '·'));
  line.appendChild(element('span', null, (status.pending || 0) + ' pending'));
  line.appendChild(element('span', null, '·'));
  line.appendChild(element('span', null, 'v' + (status.version || '?')));
  root.appendChild(line);

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
  ['recovery', 'limits', 'notifications'].forEach(function (name) {
    grid.appendChild(groups[name]);
  });
  root.appendChild(grid);

  var pending = renderPending(DATA.pending);
  if (pending) root.appendChild(pending);

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
      HOST.callTool('start_watcher', {}).then(function () {
        status.watcher_running = true;
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
