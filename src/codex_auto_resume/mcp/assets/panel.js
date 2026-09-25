
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
// A stamp the page was served with is a documentation capture's pinned theme, which the stored
// setting must not undo. Codex is never served one.
var THEME_PINNED = !!(document.documentElement && document.documentElement.hasAttribute('data-theme-pinned'));
// Survives a re-render: set before render(), shown by it, then cleared.
var NOTICE = '';
var EDITORS = {};
// Unsaved choices, kept across a re-render. A pause or a per-conversation switch redraws
// the whole panel, and a redraw that quietly put back what somebody had just changed would
// be a Save button that saves less than the panel showed a moment ago.
var DRAFT = {};
// Which folding sections are open, for the same reason.
var OPEN = {};
var HOOKS = {};
// The pending row whose "turn off" is being confirmed, by its exact interruption id.
var CONFIRM_ROW = '';
// What each pending row's switch showed when the page was last drawn, by interruption id - the
// drawing before this one in WAS, this one's in SHOWN - and the switches to move once drawn.
// A conversation's switch changes only when a tool has confirmed the change, and that answer
// arrives with a redraw: a switch drawn already moved would jump, so it is drawn where it was and
// glides from there (glide()).
var WAS = {};
var SHOWN = {};
var GLIDES = [];
var PREVIEW = {reason: '', nodes: null, last: null, asking: ''};
// The settings whose unsaved value changes the Preview.
var PREVIEW_FIELDS = ['interface_language', 'continuation_language', 'continuation_style',
                      'custom_message_mode'];

// Every word on this panel comes from Python, in the language Python resolved. The panel
// does not consult the browser's language: the notifications, the setup output, the
// standalone window and this page all have to agree, and only one of them can decide.
var S = window.__CODEX_AUTO_RESUME_STRINGS__ || {};
// The locale those words are in, and every language's words for this page. Python still
// decides: a language chosen here is spoken the moment the watcher confirms it was saved, by
// the rule Python resolves it with, from the words Python shipped - not a page that tells
// somebody the panel will change language the next time it is opened.
var LOCALE = window.__CODEX_AUTO_RESUME_LOCALE__ || '';
var CATALOGS = window.__CODEX_AUTO_RESUME_CATALOGS__ || {};
// What the save card says once a save has redrawn the page in another language.
var SAVED = '';

function t(key, fallback) {
  var value = S[key];
  return (value === undefined || value === null) ? (fallback || key) : value;
}

function fill(key, fallback, values) {
  var text = t(key, fallback);
  Object.keys(values || {}).forEach(function (name) {
    text = text.split('{' + name + '}').join(String(values[name]));
  });
  return text;
}

// The locale a stored Interface language is spoken in, by the rule Python adopts it with: a
// language chosen by name is that language, and `system` - or no choice at all - follows
// Windows, which Python already resolved and sent as `system_language`. '' when the page has no
// words for the answer, or no answer: then it keeps the words it was served rather than
// speaking a language nobody chose.
function localeFor(preference, systemLanguage, catalogs) {
  catalogs = catalogs || {};
  var has = function (code) {
    return typeof code === 'string' && Object.prototype.hasOwnProperty.call(catalogs, code);
  };
  if (typeof preference === 'string' && preference && preference !== 'system') {
    return has(preference) ? preference : '';
  }
  return has(systemLanguage) ? systemLanguage : '';
}

// Speak the stored language. True when the words changed, and so the page has to be drawn again.
function adoptLanguage(settings) {
  var locale = localeFor((settings || {}).interface_language, DATA && DATA.system_language, CATALOGS);
  if (!locale || locale === LOCALE) return false;
  S = CATALOGS[locale];
  LOCALE = locale;
  return true;
}

// Light or Dark as chosen, and nothing for Use system setting, which leaves Codex's own scheme in
// charge - as is anything else, from a watcher older than the setting or newer than this page.
function themeStamp(preference) {
  return (preference === 'light' || preference === 'dark') ? preference : '';
}

// On the root, where the theme blocks are declared; High Contrast's forced colours replace any. The
// panel theme's own choice, or the Theme's while it is "same" - absent too, from an older watcher.
function applyTheme(root, settings, pinned) {
  if (!root || pinned) return;
  var own = (settings = settings || {}).panel_theme;
  var stamp = themeStamp(own === 'system' || own === 'light' || own === 'dark' ? own : settings.theme);
  if (stamp) root.setAttribute('data-theme', stamp);
  else root.removeAttribute('data-theme');
}

// The language the words are in, on the root: the stylesheet breaks a line of Korean between words and
// one of Japanese between phrases by it, and a screen reader reads each language in its own voice. Set on
// every draw (render), because a saved Interface language draws the page again in that language; none
// when the page has no locale to name.
function applyLanguage(root, locale) {
  if (!root || typeof root.setAttribute !== 'function') return;
  if (typeof locale === 'string' && locale) root.setAttribute('lang', locale);
  else root.removeAttribute('lang');
}

// The stored appearance and language, applied to the page in place. True when the words changed.
function adopt(settings) {
  applyTheme(document.documentElement, settings, THEME_PINNED);
  return adoptLanguage(settings);
}

// The one code that is not worth translating, because the sentence beside it says more.
// The control layer gives it to a refusal it deliberately leaves unworded - a value the
// validator rejected, whose sentence names the setting it refused - and swapping that for
// "the request could not be completed" inside "Not saved: {reason}" would throw away the
// only informative half to say nothing twice.
var GENERIC_REFUSAL = 'request_failed';

// What a refused call says, in the language the rest of the panel is already speaking.
//
// Every refusal from the control layer carries a machine code from a closed set beside its
// English sentence, and this page was served an `error.<code>` string for every member of
// that set - so the code, not the prose, is the part that can be said in Korean. Without
// it the panel could only wrap a Korean frame around an English sentence, which is half a
// translation and reads worse than either language alone.
//
// Hosts differ on whether a rejected call hands back the whole tool result or only its
// structured half, exactly as they differ on a fulfilled one, so both shapes are looked in
// rather than depending on one. A refusal that arrives with no code at all is an older
// watcher than the codes, and then its sentence is all there is - still better than a
// panel that goes quiet about why nothing was saved.
function refusal(error) {
  var sentence = (error && error.message) ? error.message : t('panel.refused', 'refused');
  var payload = (error && error.structuredContent) || error || {};
  var code = payload.error_code;
  if (!code || code === GENERIC_REFUSAL) return sentence;
  return t('error.' + code, sentence);
}

// MCP tool failures are successful JSON-RPC replies with isError set. A host may
// resolve its promise with that reply (or only its structured content), so rejection
// of the JavaScript promise alone is not evidence that the operation succeeded.
function toolPayload(result) {
  var payload = (result && result.structuredContent) || result || {};
  if ((result && result.isError) || payload.error_code) {
    var content = (result && result.content) || [];
    var text = content.filter(function (item) { return item.type === 'text'; })
                      .map(function (item) { return item.text; }).join(' ');
    var error = new Error(text || t('panel.refused', 'refused'));
    error.structuredContent = payload;
    throw error;
  }
  return payload;
}

// The parameter is not called `arguments`. It was, and inside the inner function that
// name is that function's own implicit arguments object - so every call this panel made,
// Save included, handed the host an empty object instead of what it meant to send.
function callTool(name, args) {
  return Promise.resolve().then(function () {
    return HOST.callTool(name, args);
  }).then(toolPayload);
}

function saveSettings(changes) {
  return callTool('update_settings', changes).then(function (payload) {
    if (!payload.settings || typeof payload.settings !== 'object' || Array.isArray(payload.settings)) {
      throw new Error(t('panel.refused', 'refused'));
    }
    // A later pause re-renders the panel. Keep the acknowledged settings so that
    // re-render cannot restore the values from the original open_settings snapshot.
    DATA.settings = payload.settings;
    return payload;
  });
}

function setRecoveryEnabled(enable) {
  return callTool(enable ? 'resume_auto_recovery' : 'pause_auto_recovery', {}).then(function (payload) {
    if (typeof payload.enabled !== 'boolean') throw new Error(t('panel.refused', 'refused'));
    DATA.status.enabled = payload.enabled;
    return payload;
  });
}

// Automatic recovery for one exact conversation, addressed by the thread id the row was
// drawn from and by nothing else. Not optimistic: the rows change only once a tool has
// answered for that same thread, and a reply about any other thread is a refusal.
// Turning it back on adds automation, so Codex asks the person first; that is expected.
function setThreadRecovery(threadId, enable) {
  var tool = enable ? 'enable_conversation_recovery' : 'disable_conversation_recovery';
  return callTool(tool, {thread_id: threadId}).then(function (payload) {
    if (payload.thread_id !== threadId) throw new Error(t('panel.refused', 'refused'));
    var enabled = typeof payload.enabled === 'boolean' ? payload.enabled : null;
    if (enabled === null) {
      // Turning recovery off answers with the thread alone. Turning it on has to say so.
      if (enable) throw new Error(t('panel.refused', 'refused'));
      enabled = false;
    }
    (DATA.pending || []).forEach(function (row) {
      if (row.thread_id !== threadId) return;
      row.thread_enabled = enabled;
      var overlays = (row.overlays || []).filter(function (name) { return name !== 'thread_disabled'; });
      if (!enabled) overlays.push('thread_disabled');
      row.overlays = overlays;
    });
    return enabled;
  });
}

// Which settings this panel may write. The same rule the server generates the
// update_settings schema by - the groups a person edits, and never Custom message text,
// which is written in the Windows Dashboard by the person it will speak for - kept here so
// the Save button cannot even assemble a request that carries it.
function editable(entry) {
  var groups = ['general', 'recovery', 'limits', 'notifications', 'continuation'];
  // Of the appearance settings only the two themes, which the panel is drawn in. Reduce motion
  // and the notification-area icon are Windows' own and stay in the Windows Dashboard.
  var appearance = ['theme', 'panel_theme'];
  if (!entry || typeof entry.name !== 'string') return false;
  if (entry.group === 'appearance') return appearance.indexOf(entry.name) >= 0 && !entry.multiline;
  if (groups.indexOf(entry.group) < 0 || entry.multiline) return false;
  return entry.name.indexOf('custom_message') !== 0 || entry.name === 'custom_message_mode';
}

function collectChanges(editors, schema) {
  var changes = {};
  (schema || []).forEach(function (entry) {
    if (editable(entry) && typeof editors[entry.name] === 'function') {
      changes[entry.name] = editors[entry.name]();
    }
  });
  return changes;
}

// Of the collected changes, the settings surfaces are drawn in - language and both themes - that still
// hold what the page was drawn with. This page is not told when the Dashboard or Codex changes them,
// so sending them back unedited would quietly undo that change; they go only when chosen here, the
// rule the Dashboard saves by too. Every other setting is still sent whole, as it always was.
function unedited(changes, saved) {
  saved = saved || {};
  return ['interface_language', 'theme', 'panel_theme'].filter(function (name) {
    return Object.prototype.hasOwnProperty.call(changes, name)
           && Object.prototype.hasOwnProperty.call(saved, name)
           && changes[name] === saved[name];
  });
}

// The Preview request: one kind of interruption, and the unsaved language and style.
// Exactly these four choices and nothing else - the tool refuses Custom text, and this
// never offers it one.
function previewArguments(category, read) {
  var changes = {};
  ['interface_language', 'continuation_language', 'continuation_style',
   'custom_message_mode'].forEach(function (name) {
    var value = read(name);
    if (typeof value === 'string' && value) changes[name] = value;
  });
  return {category: category, changes: changes};
}

// One word for the whole product, in the order that matters: nothing is recovered while
// no watcher runs or while the one that runs is not well, nothing is sent while paused, and
// a row already in Codex outranks a row that is still waiting. The rule every header keeps -
// the popup's and the Dashboard's too; tests/data/light_states.json holds all three to it
// (v0.6.10). One step of it is not here: a task whose time has come is "checking" in the
// Dashboard and the popup, which redraw every second, and this page is drawn once, so it has
// no clock to say a time has come by. It says waiting, and each row says "due now".
function activity(status, rows) {
  var moving = ['submission_claimed', 'submitted', 'withdrawing', 'turn_running', 'turn_finishing'];
  var codes = (status && status.codes) || {};
  var list = rows || [];
  status = status || {};
  if (status.watcher_running !== true) return 'attention';
  if (attentionCause(status, list) !== null) return 'attention';
  if (status.enabled !== true) return 'paused';
  for (var i = 0; i < moving.length; i++) {
    if (codes[moving[i]] > 0) return 'recovering';
  }
  for (var j = 0; j < list.length; j++) {
    if (moving.indexOf(list[j].code) >= 0) return 'recovering';
  }
  return (status.pending > 0 || list.length > 0) ? 'waiting' : 'monitoring';
}

// Why a watcher that runs needs a person, or null when it does not: an older watcher still
// owns the state, it has stopped ticking, the engine is not supported or failed its checks
// here - or a row is held for one of those (an overlay), which the list, read a moment after
// the status, can know first. In this order, and the rows in theirs; the Dashboard's
// AttentionCause is the same.
function attentionCause(status, rows) {
  var watcher = (status && status.watcher) || {};
  if (status && status.upgrade_pending === true) return 'upgrade_pending';
  if (watcher.ticking === false) return 'watcher_not_ticking';
  if (watcher.engine_state === 'incompatible') return 'compatibility_blocked';
  if (watcher.engine_state === 'failed_here') return 'compatibility_failed_here';
  var held = ['compatibility_blocked', 'compatibility_failed_here', 'engine_unavailable', 'watcher_not_ticking'];
  var list = rows || [];
  for (var i = 0; i < list.length; i++) {
    var overlays = list[i].overlays || [];
    for (var j = 0; j < held.length; j++) {
      if (overlays.indexOf(held[j]) >= 0) return held[j];
    }
  }
  return null;
}

// The status light for a state. Not quite the word: a watcher that is not running - or that
// nothing has confirmed is running - is a light that is off, grey as it always was, while the
// word beside it still asks for attention. Amber is for a watcher that runs and is not well.
function lightFor(status, state) {
  return (status && status.watcher_running === true) ? state : 'idle';
}

// The colour a state chip carries. Always beside its word, never instead of it.
function tone(code) {
  if (['submission_claimed', 'submitted', 'withdrawing', 'turn_running',
       'turn_finishing'].indexOf(code) >= 0) return 'active';
  if (['waiting_reset', 'waiting_usage', 'waiting_thread', 'scheduled'].indexOf(code) >= 0) return 'waiting';
  if (code === 'recovered') return 'success';
  if (['exhausted', 'failed_terminal', 'recovery_failed'].indexOf(code) >= 0) return 'danger';
  if (['failed_retryable', 'outcome_unverified', 'submission_unknown', 'no_progress',
       'engine_unavailable', 'watcher_not_ticking', 'compatibility_blocked', 'compatibility_failed_here']
      .indexOf(code) >= 0) return 'warning';
  return 'paused';
}

function label(name) {
  var known = S['field.' + name];
  if (known) return known;
  var key = name.replace(/^recover_/, '').replace(/^notify_/, '').replace(/_/g, ' ');
  return key.charAt(0).toUpperCase() + key.slice(1);
}

function element(tag, className, text) {
  var node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function card(title, extra) {
  var node = element('section', 'card' + (extra ? ' ' + extra : ''));
  if (title) node.appendChild(element('h2', null, title));
  return node;
}

// A section whose body folds away. Whether it is open survives a redraw. `aside`, when given, is what
// the section says while it is folded - beside the chevron, at the right of the title.
function folding(key, title, openByDefault, kind, aside) {
  var node = element('details', kind === 'inner' ? 'fold inner' : 'card fold');
  node.open = Object.prototype.hasOwnProperty.call(OPEN, key) ? OPEN[key] : openByDefault;
  var summary = element('summary');
  summary.appendChild(element(kind === 'inner' ? 'h3' : 'h2', null, title));
  var chevron = element('span', 'chevron');
  chevron.setAttribute('aria-hidden', 'true');
  if (aside) {
    var end = element('span', 'fold-end');
    end.appendChild(aside);
    end.appendChild(chevron);
    summary.appendChild(end);
  } else {
    summary.appendChild(chevron);
  }
  node.appendChild(summary);
  node.addEventListener('toggle', function () { OPEN[key] = node.open; });
  var body = element('div', 'fold-body');
  node.appendChild(body);
  return {node: node, body: body};
}

function endonym(code) {
  return (DATA.endonyms || {})[code] || code || '';
}

// "System (한국어)" - with the language named in itself, or with no brackets at all when an
// older watcher did not say which language the system has.
function withLanguage(key, fallback, code) {
  var text = fill(key, fallback, {language: endonym(code)});
  return code ? text : text.replace(/\s*\(\s*\)/, '');
}

function value(name) {
  if (Object.prototype.hasOwnProperty.call(DRAFT, name)) return DRAFT[name];
  return (DATA.settings || {})[name];
}

function read(name) {
  return typeof EDITORS[name] === 'function' ? EDITORS[name]() : value(name);
}

function edited(name) {
  if (HOOKS.dirty) HOOKS.dirty();
  if (PREVIEW_FIELDS.indexOf(name) >= 0) refreshPreview();
}

function unsaved(schema) {
  var saved = DATA.settings || {};
  var changes = collectChanges(EDITORS, schema);
  return Object.keys(changes).some(function (name) { return changes[name] !== saved[name]; });
}

function settingRow(title, help, control, className) {
  var row = element('div', 'setting' + (className ? ' ' + className : ''));
  var text = element('div', 'setting-text');
  var name = element('label', 'setting-label', title);
  if (control.id) name.htmlFor = control.id;
  text.appendChild(name);
  var helpNode = null;
  if (help) {
    helpNode = element('p', 'help', help);
    text.appendChild(helpNode);
  }
  row.appendChild(text);
  var box = element('div', 'setting-control');
  box.appendChild(control);
  row.appendChild(box);
  return {row: row, help: helpNode, label: name};
}

// A drop-down: a select, and the list this page opens for it (`.combo` in the stylesheet says why).
//
// The select stays in the page, hidden, and is still the value: EDITORS read it, the page listens
// to its `change`, and picking from the list sets it and fires that `change`, so nothing that reads
// a choice knows the list exists. Nothing can open the browser's own list: the select is never
// shown, never focused and never reached by Tab.
//
// What is seen, focused and read out is a combobox, as the WAI-ARIA pattern for a select-only
// combobox has it: `aria-expanded` while its list is open, `aria-activedescendant` naming the item
// the keyboard is on - focus itself never leaves the combobox - and a listbox of options, the
// current value's `aria-selected`. The listbox is the card; what scrolls inside it says nothing of
// its own. Its keys are the pattern's and the window's list's (SoftCombo) together:
//   closed  Down, Up, Enter, Space, F4, Alt+Down and Alt+Up open the list on the current value;
//           Home and End open it on the first and the last item, Page Up and Page Down a page along;
//           a letter opens it on the next item whose name begins with it;
//   open    Up, Down, Home, End, Page Up and Page Down move - a page is what shows, less one row, as
//           in the window; Enter, Space, F4, Alt+Up and Alt+Down pick and close; Tab picks and moves
//           on; Escape closes and changes nothing; Left and Right do nothing; a letter finds.
// Letters typed within a second of each other are one search, the window's TypeAhead, measured
// between the keys' own time stamps, so nothing here ticks. The search is the window's
// (SoftCombo.Find): a first letter looks from the item after the one the keyboard is on, round to
// the start, and the same letter again steps on through the items it begins; a longer search keeps
// the item the keyboard is on while that still matches, so a word typed through goes to its item and
// stays there.
//
// The pointer: a press on the field opens or closes the list, a press on an item picks it. The
// pointer moving over an item moves the keyboard's item there - shown by the item rising rather than
// by the ring - so Enter takes the item under the pointer, as in the window; a move the browser makes
// up for a pointer that stood still while the list appeared or scrolled under it leaves the keyboard
// where it is. A press anywhere else, the page losing focus - to another window, or to Codex itself -
// and Tab away all close it, since each takes focus from the combobox; only Tab picks on the way. A
// press inside the list keeps focus where it is. The wheel scrolls a long list, a row at a time, and
// stops at its ends rather than carrying on into the page.
var COMBO_ROWS = 12;
var COMBO_TYPING_MS = 1000;

function combo(select) {
  var id = select.id;
  var wrap = element('div', 'combo');
  select.hidden = true;
  select.setAttribute('tabindex', '-1');
  select.setAttribute('aria-hidden', 'true');
  wrap.appendChild(select);
  var box = element('div', 'combo-box');
  box.id = id + '-box';
  box.setAttribute('role', 'combobox');
  box.setAttribute('aria-haspopup', 'listbox');
  box.setAttribute('aria-expanded', 'false');
  box.setAttribute('aria-controls', id + '-list');
  var shown = element('span', 'combo-value');
  box.appendChild(shown);
  wrap.appendChild(box);
  var list = element('div', 'combo-list');
  list.id = id + '-list';
  list.setAttribute('role', 'listbox');
  list.setAttribute('tabindex', '-1');
  list.hidden = true;
  var scroll = element('div', 'combo-scroll');
  scroll.setAttribute('role', 'none');
  list.appendChild(scroll);
  wrap.appendChild(list);
  var items = [];
  var expanded = false;
  var active = 0;
  var typed = '';
  var typedAt = -Infinity;
  // Where the pointer last moved to, on the screen.
  var pointer = null;

  Array.prototype.forEach.call(select.options, function (option, index) {
    var item = element('div', 'combo-option');
    item.id = id + '-option-' + index;
    item.setAttribute('role', 'option');
    item.addEventListener('click', function () {
      pick(index);
      box.focus();
    });
    item.addEventListener('mousemove', function (event) { hover(index, event); });
    scroll.appendChild(item);
    items.push(item);
  });

  // The index of the value the select holds.
  function current() {
    for (var index = 0; index < select.options.length; index++) {
      if (select.options[index].value === select.value) return index;
    }
    return 0;
  }

  // The field, the items and whether any of it can be used, from the select - which is also how a
  // caller that renames an option (the Continuation language's "Same as the interface") is shown.
  function sync() {
    var chosen = current();
    shown.textContent = items.length ? select.options[chosen].textContent : '';
    items.forEach(function (item, index) {
      item.textContent = select.options[index].textContent;
      item.setAttribute('aria-selected', index === chosen ? 'true' : 'false');
    });
    if (select.disabled) {
      close();
      box.setAttribute('aria-disabled', 'true');
      box.removeAttribute('tabindex');
    } else {
      box.removeAttribute('aria-disabled');
      box.setAttribute('tabindex', '0');
    }
  }

  // From one item to the next, as laid out: an item and the gap under it.
  function pitch() {
    return items.length > 1 ? items[1].offsetTop - items[0].offsetTop : items[0].offsetHeight;
  }

  // How many rows show: as laid out, or - where nothing is laid out - what the stylesheet shows.
  function rows() {
    var step = pitch();
    var count = step > 0 ? Math.round((scroll.clientHeight - 2 * items[0].offsetTop + step - items[0].offsetHeight) / step)
                         : NaN;
    return count >= 1 ? count : Math.min(items.length, COMBO_ROWS);
  }

  // A page: what shows, less the row kept in view from the page before.
  function page() {
    return Math.max(1, rows() - 1);
  }

  // As the window places its list (SoftDropList.Place). Across, from a pad left of the field, as the
  // stylesheet has it, and moved left as far as it would run past the page, which it is never wider
  // than. Below the field, or above it when there is not room for it below and there is more above;
  // a list with room on neither side goes to the larger and is cut to the whole rows that fit there,
  // never fewer than one, and scrolls. Measured in layout, which the opening rise does not move.
  function place() {
    list.classList.toggle('up', false);
    list.style.left = '';
    list.style.maxWidth = '';
    scroll.style.maxHeight = '';
    var root = document.documentElement || {};
    var width = root.clientWidth || window.innerWidth || 0;
    if (width && typeof list.getBoundingClientRect === 'function') {
      list.style.maxWidth = width + 'px';
      var edge = list.getBoundingClientRect();
      var over = Math.min(edge.right - width, edge.left);
      if (over > 0) list.style.left = (list.offsetLeft - over) + 'px';
    }
    var view = window.innerHeight || root.clientHeight || 0;
    if (!view || typeof box.getBoundingClientRect !== 'function') return;
    var field = box.getBoundingClientRect();
    var gap = Math.max(0, list.offsetTop - box.offsetHeight);
    var height = list.offsetHeight;
    var below = view - field.bottom - 2 * gap;
    var above = field.top - 2 * gap;
    if (height <= below) return;
    var up = above > below;
    list.classList.toggle('up', up);
    var room = Math.floor(up ? above : below);
    var step = pitch(), pill = items[0].offsetHeight, inset = items[0].offsetTop;
    if (height <= room || !(step > 0)) return;
    // The card's hairlines and padding and the room around the items, above and below them.
    var frame = height - scroll.clientHeight + 2 * inset;
    var fit = Math.max(1, Math.floor((room - frame + step - pill) / step));
    scroll.style.maxHeight = (2 * inset + fit * step - (step - pill)) + 'px';
  }

  // The item the keyboard is on, scrolled into the list's view with its ring - a whole row at a time,
  // since every row starts a pitch after the one before.
  function reveal(item) {
    var room = scroll.clientHeight;
    if (!(scroll.scrollHeight > room)) return;
    var pad = items[0].offsetTop;
    var top = item.offsetTop - pad;
    var bottom = item.offsetTop + item.offsetHeight + pad;
    if (top < scroll.scrollTop) scroll.scrollTop = top;
    else if (bottom > scroll.scrollTop + room) scroll.scrollTop = bottom - room;
  }

  // The keyboard's item to `index`, kept to the list; scrolled into view unless the pointer put it there.
  function move(index, byPointer) {
    active = Math.max(0, Math.min(items.length - 1, index));
    items.forEach(function (item, at) { item.classList.toggle('active', at === active); });
    box.setAttribute('aria-activedescendant', items[active].id);
    if (!byPointer) reveal(items[active]);
  }

  // The pointer over item `index`. A move with no movement, or to where the pointer already was, is
  // one the browser makes up when the list appears or scrolls under a pointer that stood still: while
  // the keyboard leads, that leaves its item where it is. Any other hands the lead to the pointer.
  function hover(index, event) {
    if (!expanded) return;
    var at = event && typeof event.screenX === 'number' ? event.screenX + ',' + event.screenY : null;
    var still = !!event && ((event.movementX === 0 && event.movementY === 0) || (at !== null && at === pointer));
    pointer = at;
    if (still && list.classList.contains('keys')) return;
    list.classList.toggle('keys', false);
    move(index, true);
  }

  function open(index, byKeys) {
    if (select.disabled || !items.length) return;
    if (!expanded) {
      expanded = true;
      list.hidden = false;
      box.setAttribute('aria-expanded', 'true');
      list.classList.toggle('keys', !!byKeys);
      place();
    }
    move(index);
  }

  function close() {
    if (!expanded) return;
    expanded = false;
    list.hidden = true;
    list.classList.toggle('keys', false);
    box.setAttribute('aria-expanded', 'false');
    box.removeAttribute('aria-activedescendant');
    typed = '';
  }

  // The item at `index` becomes the value, and the select says so the way a select does.
  function pick(index) {
    close();
    var option = select.options[index];
    if (!option || option.value === select.value) return;
    select.value = option.value;
    sync();
    select.dispatchEvent(new Event('change', {bubbles: true}));
  }

  // What `text` finds with the keyboard on item `from`: SoftCombo.Find, the window's. -1 when nothing does.
  function seek(text, from) {
    var wanted = text.toLowerCase();
    var repeated = wanted.split('').every(function (character) { return character === wanted.charAt(0); });
    if (repeated) wanted = wanted.charAt(0);
    var start = repeated ? from + 1 : from;
    for (var step = 0; step < items.length; step++) {
      var at = (start + step) % items.length;
      if (items[at].textContent.toLowerCase().indexOf(wanted) === 0) return at;
    }
    return -1;
  }

  function typing(time) {
    return typed !== '' && time - typedAt < COMBO_TYPING_MS;
  }

  function find(letter, time) {
    if (!typing(time)) typed = '';
    typed += letter;
    typedAt = time;
    var from = expanded ? active : current();
    var at = seek(typed, from);
    open(at < 0 ? from : at, true);
  }

  box.addEventListener('keydown', function (event) {
    if (select.disabled || event.ctrlKey || event.metaKey) return;
    var key = event.key || '';
    var time = event.timeStamp || Date.now();
    var last = items.length - 1;
    if (key === 'Tab') {
      if (expanded) pick(active);
      return;
    }
    // F4, and Alt with Down or Up: what opens the window's list and takes its item. Never Alt+F4.
    var toggles = (key === 'F4' && !event.altKey) || (event.altKey && (key === 'ArrowDown' || key === 'ArrowUp'));
    if (key.length === 1 && !event.altKey && (key !== ' ' || typing(time))) find(key, time);
    else if (!expanded) {
      if (toggles || key === 'ArrowDown' || key === 'ArrowUp' || key === 'Enter' || key === ' ') open(current(), true);
      else if (key === 'Home') open(0, true);
      else if (key === 'End') open(last, true);
      else if (key === 'PageUp' || key === 'PageDown') {
        open(current(), true);
        move(active + (key === 'PageUp' ? -1 : 1) * page());
      }
      else return;
    }
    else if (toggles || key === 'Enter' || key === ' ') pick(active);
    else if (key === 'Escape') {
      close();
      event.stopPropagation();
    }
    else if (key === 'ArrowDown') move(active + 1);
    else if (key === 'ArrowUp') move(active - 1);
    else if (key === 'Home') move(0);
    else if (key === 'End') move(last);
    else if (key === 'PageUp') move(active - page());
    else if (key === 'PageDown') move(active + page());
    else if (key !== 'ArrowLeft' && key !== 'ArrowRight') return;
    event.preventDefault();
    if (expanded) list.classList.toggle('keys', true);
  });
  box.addEventListener('click', function () {
    if (select.disabled) return;
    if (expanded) close();
    else open(current(), false);
  });
  box.addEventListener('blur', close);
  list.addEventListener('mousedown', function (event) { event.preventDefault(); });
  select.addEventListener('change', sync);
  sync();

  // The setting's name names the field and its list, a press on the name puts focus on the field,
  // and the help under the name describes it.
  function labelled(labelNode, helpNode) {
    labelNode.id = id + '-label';
    box.setAttribute('aria-labelledby', labelNode.id);
    list.setAttribute('aria-labelledby', labelNode.id);
    if (helpNode) {
      helpNode.id = id + '-help';
      box.setAttribute('aria-describedby', helpNode.id);
    }
    labelNode.addEventListener('click', function () {
      if (!select.disabled) box.focus();
    });
  }

  return {node: wrap, box: box, list: list, sync: sync, labelled: labelled};
}

function toggle(entry, onChange) {
  var row = element('label', 'setting toggle');
  var text = element('span', 'setting-text');
  text.appendChild(element('span', 'setting-label', label(entry.name)));
  row.appendChild(text);
  var input = element('input', 'switch');
  input.type = 'checkbox';
  input.setAttribute('role', 'switch');
  input.checked = !!value(entry.name);
  input.disabled = !HOST;
  input.addEventListener('change', function () {
    DRAFT[entry.name] = input.checked;
    edited(entry.name);
    if (onChange) onChange(input.checked);
  });
  row.appendChild(input);
  EDITORS[entry.name] = function () { return input.checked; };
  return row;
}

// Which control an on/off setting gets, by what it means rather than by its type. A switch turns
// something that runs on or off - the notifications master, a conversation's auto-resume. A check
// box picks which items of a list apply: `recover_<category>`, which kinds of interruption may be
// recovered, and `notify_<event>`, which events notify under the master switch. The window
// draws the same setting as the same kind.
function booleanKind(entry) {
  if (!entry || entry.master) return 'switch';
  return /^(recover|notify)_[a-z0-9_]+$/.test(String(entry.name || '')) ? 'check' : 'switch';
}

// A native check box - no switch role, because it is not one - ahead of its label, inside the
// label so the whole row toggles it.
function checkItem(entry) {
  var row = element('label', 'setting check');
  var input = element('input', 'check');
  input.type = 'checkbox';
  input.checked = !!value(entry.name);
  input.disabled = !HOST;
  input.addEventListener('change', function () {
    DRAFT[entry.name] = input.checked;
    edited(entry.name);
  });
  row.appendChild(input);
  var text = element('span', 'setting-text');
  text.appendChild(element('span', 'setting-label', label(entry.name)));
  row.appendChild(text);
  EDITORS[entry.name] = function () { return input.checked; };
  return row;
}

function onOff(entry, onChange) {
  return booleanKind(entry) === 'check' ? checkItem(entry) : toggle(entry, onChange);
}

function numberField(entry) {
  var input = document.createElement('input');
  input.type = 'number';
  input.id = 'car-' + entry.name;
  if (entry.min !== undefined) input.min = entry.min;
  if (entry.max !== undefined) input.max = entry.max;
  input.value = value(entry.name);
  input.disabled = !HOST;
  input.addEventListener('input', function () {
    DRAFT[entry.name] = Number(input.value);
    edited(entry.name);
  });
  EDITORS[entry.name] = function () { return Number(input.value); };
  return settingRow(label(entry.name), '', input).row;
}

// A select whose stored value is the untranslated choice and whose label is whatever the
// caller says - a settings file whose meaning changed with the display language would be
// a bug nobody could see.
function choiceField(entry, options, help, onChange) {
  var input = document.createElement('select');
  input.id = 'car-' + entry.name;
  var chosen = value(entry.name);
  options.forEach(function (option) {
    var node = element('option', null, option.text);
    node.value = option.value;
    if (option.value === chosen) node.selected = true;
    input.appendChild(node);
  });
  input.disabled = !HOST;
  input.addEventListener('change', function () {
    DRAFT[entry.name] = input.value;
    edited(entry.name);
    if (onChange) onChange(input.value);
  });
  EDITORS[entry.name] = function () { return input.value; };
  var field = combo(input);
  var built = settingRow(label(entry.name), help, field.node, 'has-select');
  field.labelled(built.label, built.help);
  built.select = input;
  built.sync = field.sync;
  return built;
}

function segmented(entry, onChange) {
  var group = element('div', 'segmented');
  group.setAttribute('role', 'radiogroup');
  group.setAttribute('aria-label', label(entry.name));
  var chosen = value(entry.name);
  var inputs = [];
  (entry.choices || []).forEach(function (choice) {
    var item = element('label', 'segment');
    var input = document.createElement('input');
    input.type = 'radio';
    input.name = 'car-' + entry.name;
    input.value = choice;
    input.checked = choice === chosen;
    input.disabled = !HOST;
    input.addEventListener('change', function () {
      if (!input.checked) return;
      DRAFT[entry.name] = choice;
      edited(entry.name);
      if (onChange) onChange(choice);
    });
    item.appendChild(input);
    item.appendChild(element('span', null, t('choice.style.' + choice, choice)));
    group.appendChild(item);
    inputs.push(input);
  });
  EDITORS[entry.name] = function () {
    for (var i = 0; i < inputs.length; i++) {
      if (inputs[i].checked) return inputs[i].value;
    }
    return chosen;
  };
  return group;
}

// When a record is next looked at, as a local clock time.
//
// Not a ticking countdown: this page is drawn once from one tool result and is not
// refreshed, so a number counting down here would be wrong within a minute and would go
// on being wrong convincingly. A time is still true an hour later, and "due now" is what
// a moment that has already passed actually means - the watcher looks at it on its next
// pass, and nothing here can say when that is.
function nextCheck(row) {
  var at = row.eligible_at;
  if (at === null || at === undefined) return t('panel.next_unknown', 'not known yet');
  var when = new Date(at * 1000);
  if (isNaN(when.getTime())) return t('panel.next_unknown', 'not known yet');
  if (when.getTime() <= Date.now()) return t('panel.due', 'due now');
  // The clock, written the way the continuation writes a reset time. Not the browser's
  // own format: that speaks the browser's language, and put "오전 02:48" into an English
  // panel on a Korean machine.
  var pad = function (number) { return (number < 10 ? '0' : '') + number; };
  return pad(when.getHours()) + ':' + pad(when.getMinutes());
}

// The facts under the word, most consequential first: whether anything can be recovered, and
// what is waiting on it. The Dashboard's header says the same facts (SettingsForm.HeroFacts,
// held to these by tests/test_light_parity.py); only the soonest check below is the panel's own,
// a clock time where the window counts down.
function heroFacts(status, state, rows) {
  var count = status.pending || 0;
  var pending = count === 0 ? t('status.pending_none', 'Nothing pending')
              : count === 1 ? t('status.pending_one', '1 recovery pending')
              : fill('status.pending_many', '{n} recoveries pending', {n: count});
  if (status.watcher_running !== true) {
    var facts = [status.watcher_running === false ? t('status.not_running', 'Watcher not running')
                                                  : t('status.unknown', 'Watcher status unknown'),
                 t('status.recovery_idle', 'Nothing will be recovered until it is running')];
    if (count) facts.push(pending);
    return facts;
  }
  if (state === 'attention') {
    // A watcher that runs and is not well: what is wrong, not "recovery is on".
    var cause = attentionCause(status, rows);
    var why = cause === 'upgrade_pending'
              ? t('diag.upgrade_pending', 'An older watcher still owns the state; finish by restarting the watcher')
            : cause === 'compatibility_blocked' ? t('overlay.compatibility_blocked', 'Codex version not supported')
            : cause === 'compatibility_failed_here'
              ? t('overlay.compatibility_failed_here', 'Codex checks failed on this computer')
            : cause === 'engine_unavailable' ? t('status.not_running', 'Watcher not running')
            : t('status.not_responding', 'Watcher not responding');
    return [why, pending];
  }
  if (state === 'paused') return [t('status.recovery_paused', 'Automatic recovery is paused'), pending];
  return [t('status.recovery_on', 'Automatic recovery is on'), pending];
}

// The soonest check, which is the question a count raises rather than answers - while recovery
// can happen at all; null otherwise.
function soonestFact(status, state, rows) {
  if (!status.pending || status.watcher_running !== true || state === 'attention' || state === 'paused') return null;
  var soonest = null;
  (rows || []).forEach(function (row) {
    if (row.eligible_at === null || row.eligible_at === undefined) return;
    if (soonest === null || row.eligible_at < soonest) soonest = row.eligible_at;
  });
  if (soonest === null) return null;
  return fill('status.next_check', 'next check {time}', {time: nextCheck({eligible_at: soonest})});
}

function renderHero(status) {
  var state = activity(status, DATA.pending);
  var hero = element('section', 'card hero');
  hero.setAttribute('data-state', state);
  // The product name is an eyebrow rather than a heading: inside Codex the panel is
  // already attributed, and the question a reader arrives with is what it is doing.
  hero.appendChild(element('div', 'eyebrow', 'Codex Auto Resume · v' + (status.version || '?')));
  var line = element('div', 'hero-state');
  var light = lightFor(status, state);
  var halo = element('span', 'halo ' + light);
  halo.setAttribute('aria-hidden', 'true');
  line.appendChild(halo);
  line.appendChild(element('h1', null, t('activity.' + state, state)));
  hero.appendChild(line);
  var facts = element('p', 'facts');
  var shown = heroFacts(status, state, DATA.pending);
  var soonest = soonestFact(status, state, DATA.pending);
  if (soonest !== null) shown.push(soonest);
  shown.forEach(function (fact) { facts.appendChild(element('span', null, fact)); });
  hero.appendChild(facts);
  var actions = element('div', 'hero-actions');
  // Offered only when it is the thing that is wrong. Nothing is recovered while the
  // watcher is stopped, so a panel that reports it and offers no way out is a dead end.
  var start = null;
  if (status.watcher_running === false) {
    start = element('button', 'primary', t('action.start', 'Start watcher'));
    start.disabled = !HOST;
    actions.appendChild(start);
  }
  var message = element('p', 'note');
  message.setAttribute('role', 'status');
  actions.appendChild(message);
  hero.appendChild(actions);
  return {node: hero, message: message, start: start};
}

function renderPending(rows) {
  if (!rows || !rows.length) return null;
  var box = card(null, 'pending');
  var head = element('div', 'card-head');
  head.appendChild(element('h2', null, t('panel.pending_title', 'Waiting to resume')));
  head.appendChild(element('span', 'count', String(rows.length)));
  box.appendChild(head);
  var list = element('ul', 'prows');
  rows.slice(0, 8).forEach(function (row) { list.appendChild(pendingRow(row)); });
  box.appendChild(list);
  if (rows.length > 8) {
    var more = element('p', 'note', fill('panel.more', 'and {n} more', {n: rows.length - 8}));
    more.style.marginTop = '10px';
    box.appendChild(more);
  }
  return box;
}

function pendingRow(row) {
  var item = element('li', 'prow');
  var main = element('div', 'prow-main');
  var title = element('div', 'prow-title');
  // The exact thread id, shortened for display only. Every action this panel can take
  // addresses a record by its full id, never by what is shown.
  var shown = row.name || String(row.thread_id || '').slice(0, 8);
  title.appendChild(element('span', 'prow-name' + (row.name ? '' : ' mono'), shown));
  // The public code, never the engine's working state: several stored states share
  // one code, and what a person is told must not depend on engine internals.
  var code = row.code || row.state || '';
  title.appendChild(element('span', 'chip ' + tone(code), t('code.' + code, code.replace(/_/g, ' '))));
  (row.overlays || []).forEach(function (overlay) {
    title.appendChild(element('span', 'chip ' + tone(overlay),
                              t('overlay.' + overlay, overlay.replace(/_/g, ' '))));
  });
  main.appendChild(title);
  var meta = element('div', 'prow-meta');
  if (row.category && S['reason.' + row.category]) {
    meta.appendChild(element('span', null, t('reason.' + row.category, row.category)));
  }
  [[t('panel.col_next', 'Next check'), nextCheck(row)],
   [t('panel.col_attempts', 'Attempts'), String(row.recovery_attempts === undefined ? 0 : row.recovery_attempts)]
  ].forEach(function (pair) {
    var fact = element('span', null, pair[0] + ' ');
    fact.appendChild(element('b', null, pair[1]));
    meta.appendChild(fact);
  });
  main.appendChild(meta);
  item.appendChild(main);
  if (typeof row.thread_enabled === 'boolean' && row.thread_id) {
    item.appendChild(threadSwitch(row, shown));
  }
  if (CONFIRM_ROW && CONFIRM_ROW === row.interruption_id) item.appendChild(confirmOff(row, shown));
  return item;
}

function threadSwitch(row, shown) {
  var wrap = element('label', 'prow-switch');
  wrap.appendChild(element('span', null, t('pending.col_resume', 'Auto-resume')));
  var input = element('input', 'switch');
  input.type = 'checkbox';
  input.setAttribute('role', 'switch');
  input.setAttribute('aria-label', t('pending.col_resume', 'Auto-resume') + ': ' + shown);
  var was = WAS[row.interruption_id];
  input.checked = typeof was === 'boolean' ? was : row.thread_enabled;
  if (input.checked !== row.thread_enabled) GLIDES.push({input: input, to: row.thread_enabled});
  SHOWN[row.interruption_id] = row.thread_enabled;
  input.disabled = !HOST;
  input.addEventListener('change', function () {
    // The switch shows what a tool last confirmed, until a tool confirms something else. Put back
    // in the same task as the press, before anything is drawn: it never moves on the press, and so
    // never snaps back - it moves once, when the change is confirmed.
    input.checked = row.thread_enabled;
    if (row.thread_enabled) {
      // Turning it off cancels what this conversation has waiting, so it is asked first.
      CONFIRM_ROW = row.interruption_id;
      render();
      return;
    }
    changeThread(row, shown, true, [input]);
  });
  wrap.appendChild(input);
  return wrap;
}

function confirmOff(row, shown) {
  var box = element('div', 'prow-confirm');
  box.appendChild(element('p', null, fill('confirm.thread_off',
    'Turn automatic recovery off for "{name}"? Its waiting recoveries are cancelled.', {name: shown})));
  var actions = element('div', 'actions');
  var off = element('button', 'danger', t('action.thread_off', 'Turn off for this conversation'));
  var keep = element('button', null, t('action.cancel', 'Cancel'));
  off.onclick = function () { changeThread(row, shown, false, [off, keep]); };
  keep.onclick = function () { CONFIRM_ROW = ''; render(); };
  actions.appendChild(off);
  actions.appendChild(keep);
  box.appendChild(actions);
  return box;
}

function changeThread(row, shown, enable, controls) {
  controls.forEach(function (control) { control.disabled = true; });
  setThreadRecovery(row.thread_id, enable).then(function (enabled) {
    NOTICE = shown + ': ' + (enabled ? t('event.thread_enabled', 'Conversation switched back on')
                                     : t('overlay.thread_disabled', 'off for this conversation'));
    // Turning a conversation off cancels what it had waiting, so the list is read again
    // rather than guessed at. If it cannot be read, the confirmed switch is still shown.
    return callTool('list_pending', {}).then(function (payload) {
      if (!Array.isArray(payload.pending)) return;
      DATA.pending = payload.pending;
      if (DATA.status) DATA.status.pending = payload.pending.length;
    }, function () {});
  }, function (error) {
    NOTICE = refusal(error);
  }).then(function () {
    CONFIRM_ROW = '';
    render();
  });
}

// The Codex Compatibility Registry (v0.6.5), read-only, as the Windows Dashboard's Diagnostics page shows
// it: for the Codex engine on this machine, which of the things this product does can be relied on, in
// the registry's four words - each with what it means - with when that was checked and which data was in
// force. Folded until it is opened; folded, its chip says the headline.
//
// What reaches this page is codes only (the status reply's `watcher.compatibility`): the state and the
// reason of each part, where the data came from and its sequence number, what the watcher acts on, the
// refreshed data's standing, one time - no version string, no path and no word from a registry document.
// And nothing here refreshes the data: a refresh is a request to GitHub, and neither a model nor this
// page may make one. The person is told where they can.
var COMPAT_STATES = ['VERIFIED', 'CHECKED', 'COMPATIBLE', 'FAILED_HERE', 'INCOMPATIBLE', 'UNKNOWN'];
// The refreshed data's standings that are more than "in force", each said as the window's card says it:
// expired or dated ahead, its restrictions apply and its trust does not; the others, the bundled data applies.
var COMPAT_CAVEATS = ['expired', 'from_the_future', 'rejected', 'superseded', 'from_newer_product'];
// The parts, in the registry's own order; the four it does not offer yet are left out, as in the window.
var COMPAT_ORDER = ['engine_present', 'exact_thread_recovery', 'usage_limit_detection', 'usage_reset_hint',
                    'usage_probe', 'thread_eligibility', 'loaded_state_detection', 'recovery_turn_tracking',
                    'queue_withdraw', 'outcome_observation', 'transient_classification', 'projection_freshness',
                    'empty_response_recovery', 'not_loaded_recovery', 'goal_continuation', 'subagent_recovery'];

// A registry state from either word a view carries one in - a part's state, or the overall's coarse word.
// Anything else is UNKNOWN, as the registry reads it.
var COMPAT_WORDS = {verified: 'VERIFIED', checked: 'CHECKED', structurally_compatible: 'COMPATIBLE',
                    failed_here: 'FAILED_HERE', incompatible: 'INCOMPATIBLE'};
function compatState(word) {
  if (COMPAT_STATES.indexOf(word) >= 0) return word;
  return Object.prototype.hasOwnProperty.call(COMPAT_WORDS, word) ? COMPAT_WORDS[word] : 'UNKNOWN';
}

// A state's chip: green for what can be relied on, red for what cannot, grey for what is not known - as
// the window draws its checks. Always beside the word.
function compatTone(state) {
  return state === 'INCOMPATIBLE' || state === 'FAILED_HERE' ? 'danger' : state === 'UNKNOWN' ? 'paused' : 'success';
}

// A moment as a clock shows it, and its date when that is not today. Written out, as nextCheck writes a
// time, rather than in the browser's own format and language.
function clockTime(at) {
  if (typeof at !== 'number' || !isFinite(at)) return '-';
  var when = new Date(at * 1000);
  if (isNaN(when.getTime())) return '-';
  var pad = function (number) { return (number < 10 ? '0' : '') + number; };
  var time = pad(when.getHours()) + ':' + pad(when.getMinutes());
  var now = new Date();
  if (when.getFullYear() === now.getFullYear() && when.getMonth() === now.getMonth() &&
      when.getDate() === now.getDate()) return time;
  return when.getFullYear() + '-' + pad(when.getMonth() + 1) + '-' + pad(when.getDate()) + ' ' + time;
}

function renderCompatibility(status) {
  var view = status && status.watcher && status.watcher.compatibility;
  if (!view || typeof view !== 'object') return null;
  var overall = compatState(view.overall);
  var chip = element('span', 'chip ' + compatTone(overall), t('compat.state.' + overall, overall.toLowerCase()));
  var fold = folding('compat', t('compat.title', 'Codex compatibility'), false, null, chip);
  fold.node.className += ' compat';
  var body = fold.body;
  // A report that cannot be used makes every part unknown, for that one reason: said once, not listed. It
  // says nothing about the data in force either, which is '-' then, as in the window - never 'none'.
  var usable = view.status === 'ok';
  var source = (view.source === 'cache' || view.source === 'bundled') ? view.source : 'none';
  // Which data, by its sequence number when there is data and a number: the window's words for both.
  var data = t('compat.source.' + source, source);
  var sequence = view.sequence;
  if (source !== 'none' && typeof sequence === 'number' && isFinite(sequence) && sequence >= 0 &&
      Math.floor(sequence) === sequence) {
    data = fill('compat.source_sequence', '{source}, #{sequence}', {source: data, sequence: sequence});
  }
  var meta = element('div', 'prow-meta compat-meta');
  [[t('compat.checked', 'Checked'), typeof view.checked_at === 'number' ? clockTime(view.checked_at) : t('time.never', 'never')],
   [t('compat.data', 'Data in force'), usable ? data : '-']
  ].forEach(function (pair) {
    var fact = element('span', null, pair[0] + ' ');
    fact.appendChild(element('b', null, pair[1]));
    meta.appendChild(fact);
  });
  body.appendChild(meta);
  // What the view cannot vouch for, as the window's card says it and in its order: why a report cannot be
  // used; else a watcher still acting on what it found when it started, which the window tells a person
  // to restart - from the window, which this page names; and refreshed data that is not simply in force.
  var notices = [];
  if (!usable) {
    notices.push(t('compat.status.' + (typeof view.status === 'string' ? view.status : 'invalid'),
      t('compat.status.invalid', 'The last check could not be read, so nothing in it is relied on.')));
  }
  if (usable && typeof view.acting === 'string' && view.acting !== view.overall) {
    notices.push(t('panel.compat_acting_differs',
      'The watcher is still acting on what it found when it started. Stop it and start it again on the Diagnostics page of the Codex Auto Resume window to check again.'));
  }
  if (usable && COMPAT_CAVEATS.indexOf(view.cache) >= 0) {
    notices.push(t('compat.cache.' + view.cache, view.cache.replace(/_/g, ' ')));
  }
  notices.forEach(function (text) { body.appendChild(element('p', 'callout', text)); });
  // The words shown, explained - not for a report that cannot be used, which is unknown for the one reason
  // the callout gives, and which the legend's reason would contradict.
  var shown = usable ? [overall] : [];
  var capabilities = (usable && view.capabilities && typeof view.capabilities === 'object') ? view.capabilities : {};
  var rows = element('ul', 'toggles compat-rows');
  rows.setAttribute('aria-label', t('compat.title', 'Codex compatibility'));
  COMPAT_ORDER.forEach(function (name) {
    var entry = capabilities[name];
    if (!entry || typeof entry !== 'object' || entry.reason === 'not_implemented') return;
    var state = compatState(entry.state);
    if (shown.indexOf(state) < 0) shown.push(state);
    var row = element('li', 'setting');
    var text = element('div', 'setting-text');
    text.appendChild(element('span', 'setting-label', t('compat.capability.' + name, name.replace(/_/g, ' '))));
    row.appendChild(text);
    row.appendChild(element('span', 'chip compat-state ' + compatTone(state), t('compat.state.' + state, state.toLowerCase())));
    rows.appendChild(row);
  });
  if (rows.children.length) body.appendChild(rows);
  var legend = element('div', 'compat-legend');
  COMPAT_STATES.forEach(function (state) {
    if (shown.indexOf(state) >= 0) legend.appendChild(element('p', 'help', t('compat.meaning.' + state, state)));
  });
  if (legend.children.length) body.appendChild(legend);
  body.appendChild(element('p', 'help compat-refresh', t('panel.compat_refresh',
    'This data changes only when you ask: with Refresh compatibility data on the Diagnostics page of the Codex Auto Resume window, or with Check for updates.')));
  return fold.node;
}

function renderGeneral(byName) {
  var entry = byName.interface_language;
  if (!entry) return null;
  var node = card(t('group.general', 'General'));
  var rows = element('div', 'rows');
  var options = (entry.choices || []).map(function (choice) {
    return {value: choice, text: choice === 'system'
      ? withLanguage('choice.language.system', 'System ({language})', DATA.system_language)
      : endonym(choice)};
  });
  rows.appendChild(choiceField(entry, options,
    t('help.interface_language', 'Used by this window, the notification-area popup, notifications and the panel in Codex.'),
    function (chosen) { if (HOOKS.follow) HOOKS.follow(chosen); }).row);
  node.appendChild(rows);
  return node;
}

// Both themes, each in its own words. Applied once the save is confirmed, not while only on screen.
function renderAppearance(byName) {
  var shown = ['theme', 'panel_theme'].filter(function (name) { return byName[name] && editable(byName[name]); });
  if (!shown.length) return null;
  var node = card(t('group.appearance', 'Appearance')), rows = element('div', 'rows');
  var words = {theme: function (c) { return t('choice.theme.' + c, c); },
               panel_theme: function (c) { return t('choice.panel_theme.' + c, c); }};
  var help = {theme: t('help.theme', ''), panel_theme: t('help.panel_theme', '')};
  shown.forEach(function (name) {
    rows.appendChild(choiceField(byName[name], (byName[name].choices || []).map(function (choice) {
      return {value: choice, text: words[name](choice)};
    }), help[name]).row);
  });
  node.appendChild(rows);
  return node;
}

function renderRecovery(status, schema) {
  var node = card(t('group.recovery', 'Automatic recovery'));
  // The control every check box on this card depends on, first. It acts at once -
  // pausing needs no Save and resuming asks for approval - so it is a button beside what
  // it will change, rather than a switch that looks like it waits for Save. What the tile
  // says comes first - the state, and under it what the last press answered - and the
  // button last, pinned to the tile's bottom-right beside that text.
  var master = element('div', 'master');
  var body = element('div', 'master-body');
  var text = element('div', 'master-text');
  var running = status.watcher_running === true;
  text.appendChild(element('span', 'dot' + (!running ? '' : status.enabled ? ' on' : ' paused')));
  text.appendChild(element('span', null, !running
    ? t('status.recovery_idle', 'Nothing will be recovered until it is running')
    : status.enabled ? t('status.recovery_on', 'Automatic recovery is on')
    : t('status.recovery_paused', 'Automatic recovery is paused')));
  body.appendChild(text);
  var note = element('p', 'note');
  note.setAttribute('role', 'status');
  body.appendChild(note);
  master.appendChild(body);
  var pause = element('button', null, status.enabled
    ? t('action.pause', 'Pause recovery') : t('action.resume', 'Resume recovery'));
  pause.disabled = !HOST;
  master.appendChild(pause);
  node.appendChild(master);
  if (HOST) {
    pause.onclick = function () {
      pause.disabled = true;
      setRecoveryEnabled(!status.enabled).then(function () {
        render();
      }, function (error) {
        note.textContent = refusal(error);
        pause.disabled = false;
      });
    };
  }

  var toggles = element('div', 'toggles');
  schema.forEach(function (entry) {
    if (entry.group === 'recovery' && entry.type === 'boolean' && editable(entry)) {
      toggles.appendChild(onOff(entry));
    }
  });
  node.appendChild(toggles);

  var limits = schema.filter(function (entry) { return entry.group === 'limits' && editable(entry); });
  if (limits.length) {
    var fold = folding('limits', t('group.limits', 'Limits'), false, 'inner');
    fold.node.style.marginTop = '4px';
    limits.forEach(function (entry) {
      if (entry.choices) {
        fold.body.appendChild(choiceField(entry, entry.choices.map(function (choice) {
          return {value: choice, text: t('choice.' + choice, choice)};
        }), '').row);
      } else {
        fold.body.appendChild(numberField(entry));
      }
    });
    node.appendChild(fold.node);
  }
  return node;
}

function renderNotifications(schema) {
  var entries = schema.filter(function (entry) { return entry.group === 'notifications' && editable(entry); });
  if (!entries.length) return null;
  var fold = folding('notifications', t('group.notifications', 'Notifications'), false);
  var events = element('div', 'toggles');
  var master = null;
  entries.forEach(function (entry) {
    if (entry.master) {
      master = toggle(entry, function (on) { events.classList.toggle('quiet', !on); });
      events.classList.toggle('quiet', !value(entry.name));
    } else {
      events.appendChild(onOff(entry));
    }
  });
  if (master) fold.body.appendChild(master);
  fold.body.appendChild(events);
  return fold.node;
}

function renderContinuation(byName) {
  if (!byName.continuation_language && !byName.continuation_style) return null;
  var node = card(t('group.continuation', 'Continuation message'));
  var rows = element('div', 'rows');
  node.appendChild(rows);

  var language = byName.continuation_language;
  if (language) {
    var followLabel = function (interfaceChoice) {
      var code = (!interfaceChoice || interfaceChoice === 'system') ? DATA.system_language : interfaceChoice;
      return withLanguage('choice.continuation_language.follow', 'Same as the interface ({language})', code);
    };
    var field = choiceField(language, (language.choices || []).map(function (choice) {
      return {value: choice, text: choice === 'follow' ? followLabel(read('interface_language')) : endonym(choice)};
    }), t('help.continuation_language', 'The language of the message sent to Codex.'));
    var follow = null;
    Array.prototype.forEach.call(field.select.options, function (option) {
      if (option.value === 'follow') follow = option;
    });
    HOOKS.follow = function (chosen) {
      if (follow) follow.textContent = followLabel(chosen);
      field.sync();
    };
    rows.appendChild(field.row);
  }

  var custom = element('div', 'custom');
  var styleHelp = function (style) { return t('help.style.' + style, ''); };
  var showCustom = function () { custom.hidden = read('continuation_style') !== 'custom'; };
  var style = byName.continuation_style;
  if (style) {
    var row = element('div', 'setting stack');
    var heading = element('div', 'setting-text');
    heading.appendChild(element('span', 'setting-label', label(style.name)));
    row.appendChild(heading);
    var help = element('p', 'help', styleHelp(value(style.name)));
    row.appendChild(segmented(style, function (chosen) {
      help.textContent = styleHelp(chosen);
      showCustom();
    }));
    row.appendChild(help);
    rows.appendChild(row);
  }

  // Custom: which stored message is used, and what those messages say - shown, not
  // editable. The text itself is written in the Windows Dashboard.
  var stored = element('div', 'stored');
  var drawStored = function () {
    stored.textContent = '';
    var settings = DATA.settings || {};
    var mode = read('custom_message_mode');
    // A message that is set is shown whole, in a well. One that is not is a single quiet
    // line, so seven empty kinds of interruption do not bury the one that has words.
    var item = function (title, text) {
      var set = typeof text === 'string' && text.trim() !== '';
      var box = element('div', set ? 'stored-item' : 'stored-item unset');
      box.appendChild(element('div', 'stored-title', title));
      box.appendChild(element('div', set ? 'stored-text' : 'stored-empty',
                              set ? text : t('custom.not_set', 'Not set')));
      stored.appendChild(box);
    };
    if (mode === 'per_reason') {
      (DATA.reasons || []).forEach(function (reason) {
        item(t('reason.' + reason, reason), settings['custom_message_' + reason]);
      });
      item(t('choice.custom_mode.global', 'Every interruption'), settings.custom_message);
      stored.appendChild(element('p', 'help', t('custom.fallback', '')));
    } else {
      item(label('custom_message'), settings.custom_message);
    }
  };
  var mode = byName.custom_message_mode;
  if (mode) {
    custom.appendChild(choiceField(mode, (mode.choices || []).map(function (choice) {
      return {value: choice, text: t('choice.custom_mode.' + choice, choice)};
    }), '', drawStored).row);
  }
  custom.appendChild(stored);
  custom.appendChild(element('p', 'callout', t('custom.dashboard_only',
    'Custom messages are written in the Windows Dashboard.')));
  drawStored();
  showCustom();
  rows.appendChild(custom);
  return node;
}

function renderPreviewCard() {
  var node = card(t('preview.title', 'Preview'), 'preview');
  var reasons = DATA.reasons || [];
  if (reasons.indexOf(PREVIEW.reason) < 0) PREVIEW.reason = reasons[0] || '';
  if (reasons.length) {
    var select = document.createElement('select');
    select.id = 'car-preview-reason';
    reasons.forEach(function (reason) {
      var option = element('option', null, t('reason.' + reason, reason));
      option.value = reason;
      if (reason === PREVIEW.reason) option.selected = true;
      select.appendChild(option);
    });
    select.disabled = !HOST;
    select.addEventListener('change', function () {
      PREVIEW.reason = select.value;
      refreshPreview();
    });
    var field = combo(select);
    var built = settingRow(t('preview.for', 'Preview for'), '', field.node, 'has-select');
    field.labelled(built.label, built.help);
    var rows = element('div', 'rows');
    rows.appendChild(built.row);
    node.appendChild(rows);
  }
  var frame = element('div', 'bubble');
  frame.setAttribute('aria-live', 'polite');
  var text = element('p', 'bubble-text');
  text.appendChild(element('span', 'skeleton'));
  text.appendChild(element('span', 'skeleton'));
  frame.appendChild(text);
  node.appendChild(frame);
  var source = element('p', 'help source');
  source.hidden = true;
  node.appendChild(source);
  node.appendChild(element('p', 'help', t('preview.note', 'This is the text that will be sent.')));
  PREVIEW.nodes = {frame: frame, text: text, source: source};
  return node;
}

function showPreview(shown) {
  var nodes = PREVIEW.nodes;
  if (!nodes) return;
  nodes.frame.removeAttribute('aria-busy');
  nodes.frame.className = 'bubble' + (shown ? '' : ' unavailable');
  nodes.text.textContent = shown ? shown.text : t('preview.unavailable', 'Preview is not available right now.');
  var source = shown && ['global', 'per_reason', 'standard'].indexOf(shown.source) >= 0 ? shown.source : '';
  nodes.source.textContent = source ? t('preview.source.' + source, source) : '';
  nodes.source.hidden = !source;
}

// The exact text, from the watcher's own generator, for the choices on screen now. Asked
// again only when the question changed; an answer to a question nobody is asking any more
// is dropped rather than shown over a newer one.
function refreshPreview() {
  if (!PREVIEW.nodes) return;
  if (!HOST || !PREVIEW.reason) {
    showPreview(null);
    return;
  }
  var request = previewArguments(PREVIEW.reason, read);
  var key = JSON.stringify(request);
  if (PREVIEW.last && PREVIEW.last.key === key) {
    showPreview(PREVIEW.last);
    return;
  }
  PREVIEW.nodes.frame.setAttribute('aria-busy', 'true');
  if (PREVIEW.asking === key) return;
  PREVIEW.asking = key;
  callTool('preview_recovery_message', request).then(function (payload) {
    var preview = payload.preview;
    if (!preview || typeof preview.text !== 'string') throw new Error(t('panel.refused', 'refused'));
    return {key: key, text: preview.text, source: preview.source || null};
  }).then(function (shown) {
    if (PREVIEW.asking !== key) return;
    PREVIEW.asking = '';
    PREVIEW.last = shown;
    showPreview(shown);
  }, function () {
    if (PREVIEW.asking !== key) return;
    PREVIEW.asking = '';
    showPreview(null);
  });
}

function renderFooter(schema) {
  var bar = element('footer', 'savebar');
  var save = element('button', null, t('action.save', 'Save'));
  save.disabled = !HOST;
  var message = element('p', 'note');
  message.setAttribute('role', 'status');
  // What happened first, the button last: the commit sits where Windows puts it.
  bar.appendChild(message);
  bar.appendChild(save);
  // Quiet until there is something to save, so a changed switch visibly waits for it.
  HOOKS.dirty = function () { save.className = unsaved(schema) ? 'primary' : ''; };
  HOOKS.dirty();
  return {node: bar, save: save, message: message};
}

// The switches whose change a tool confirmed, moved now that they are drawn in the state they
// showed before. Reading a layout styles the page once in that state - synchronously, nothing
// waits or ticks - so the change is a transition from it rather than a switch drawn already moved.
// With less motion or in High Contrast the stylesheet has no transition, and the change is simply
// made.
function glide() {
  var moves = GLIDES;
  GLIDES = [];
  if (!moves.length) return;
  void moves[0].input.offsetWidth;
  moves.forEach(function (move) { move.input.checked = move.to; });
}

function render() {
  applyLanguage(document.documentElement, LOCALE);
  var root = document.getElementById('root');
  root.textContent = '';
  EDITORS = {};
  HOOKS = {};
  PREVIEW.nodes = null;
  WAS = SHOWN;
  SHOWN = {};
  GLIDES = [];
  if (!DATA) {
    root.appendChild(element('p', 'note',
      t('panel.unavailable', 'Settings are not available in this view.')));
    return;
  }
  var status = DATA.status || {};
  var schema = DATA.schema || [];
  var byName = {};
  schema.forEach(function (entry) { byName[entry.name] = entry; });

  var page = element('main', 'page');
  root.appendChild(page);
  // State first; then what is waiting, because it is the part that changes; then whether this
  // Codex can be relied on, folded; then what is configured, general to particular; then what
  // the configuration will say; then how the panel looks, where the Windows Dashboard puts it too.
  var hero = renderHero(status);
  page.appendChild(hero.node);
  [renderPending(DATA.pending), renderCompatibility(status), renderGeneral(byName), renderRecovery(status, schema),
   renderNotifications(schema), renderContinuation(byName), renderPreviewCard(),
   renderAppearance(byName)
  ].forEach(function (section) { if (section) page.appendChild(section); });
  var footer = renderFooter(schema);
  page.appendChild(footer.node);
  var message = hero.message;

  glide();

  // A message left over from the click that caused this render. It is carried across
  // rather than written before render(), which empties the panel and would discard it.
  if (NOTICE) {
    message.textContent = NOTICE;
    NOTICE = '';
  }
  if (SAVED) {
    footer.message.textContent = SAVED;
    SAVED = '';
    // The redraw replaced the button that was pressed; keep the keyboard where it was.
    if (typeof footer.save.focus === 'function') footer.save.focus({preventScroll: true});
  }

  refreshPreview();

  if (!HOST) {
    message.textContent = t('panel.readonly',
      'Read-only here. Use the Codex Auto Resume settings window to change these.');
    return;
  }

  var save = footer.save;
  save.onclick = function () {
    var before = DATA.settings || {};
    // Only what this panel may write, whatever else a control happens to hold.
    var changes = collectChanges(EDITORS, schema);
    // Nor the language or theme this page merely shows: either may have changed elsewhere.
    var kept = unedited(changes, before);
    kept.forEach(function (name) { delete changes[name]; });
    save.disabled = true;
    footer.message.textContent = t('panel.saving', 'Saving...');
    saveSettings(changes).then(function (payload) {
      DRAFT = {};
      var switched = before.interface_language !== undefined
                     && payload.settings.interface_language !== before.interface_language;
      // One of those did change elsewhere, and its control still shows the old value.
      var behind = kept.some(function (name) { return payload.settings[name] !== before[name]; });
      // The confirmed settings, applied at once: the theme in place, and a new language - or a
      // control left behind by a change made elsewhere - by drawing the page again from them.
      // Every draft was just saved, so a redraw loses nothing.
      if (adopt(payload.settings) || behind) {
        SAVED = t('panel.saved', 'Saved.');
        render();
        return;
      }
      // Only a language this page has no words for still waits for the next time it opens.
      var waits = switched && !localeFor(payload.settings.interface_language, DATA.system_language, CATALOGS);
      footer.message.textContent = waits
        ? t('settings.language_changed', 'Language changed. Anything already open changes the next time it opens.')
        : t('panel.saved', 'Saved.');
      save.disabled = false;
      if (HOOKS.dirty) HOOKS.dirty();
    }, function (error) {
      footer.message.textContent = fill('panel.not_saved', 'Not saved: {reason}',
        {reason: refusal(error)});
      save.disabled = false;
    });
  };

  var start = hero.start;
  if (start) {
    start.onclick = function () {
      start.disabled = true;
      message.textContent = t('panel.starting', 'Starting...');
      callTool('start_watcher', {}).then(function (result) {
        // Do not assume it worked. The panel used to set watcher_running to true here
        // and render a running watcher on the strength of the call not throwing, which
        // is a claim about a process nobody had looked at yet. Ask instead.
        // Hosts differ on whether they hand back the tool result or just its
        // structured half, so look in both rather than depending on one.
        var payload = (result && result.structuredContent) || result || {};
        var state = payload.state;
        if (state === 'running' || state === 'already-running') {
          status.watcher_running = true;
          NOTICE = '';
        } else if (state === 'exited') {
          NOTICE = t('panel.start_exited', 'It started and stopped again; nothing is watching.');
        } else {
          NOTICE = t('panel.start_unconfirmed',
            'Started, but not confirmed running yet. Ask for the status again.');
        }
        // Through NOTICE rather than onto `message`, because render() empties the panel
        // and builds a fresh span: text written here first would be on a node that is
        // detached before the browser paints it, and the click would look like nothing
        // happened - on exactly the two states that most need explaining.
        render();
      }, function (error) {
        message.textContent = fill('panel.start_failed', 'Could not start it: {reason}',
          {reason: refusal(error)});
        start.disabled = false;
      });
    };
  }
}

// The stored theme and language before anything is drawn: the page may be one Codex kept from an
// earlier read, and the tool result is what is true now.
adopt(DATA && DATA.settings);
render();
