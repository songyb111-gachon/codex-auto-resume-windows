# The Codex plugin layer

This project keeps the recovery engine small, local, conservative and fail-closed, and uses
Codex itself as the installation and control interface instead of building a second
management application.

The plugin is a **thin front end**. It installs no second engine, holds no recovery logic, and
never queues a message to a thread. Everything it does goes through the same command-line
interface a manual installation uses.

```
Codex UI  ->  plugin skill  ->  existing CLI  ->  small safe watcher
```

## Layout

The repository root *is* the plugin root. There is exactly one copy of `src/`.

| Path | Purpose |
| --- | --- |
| `.agents/plugins/marketplace.json` | Marketplace index; one entry whose `source.path` is `"."`. |
| `.codex-plugin/plugin.json` | Plugin manifest. Declares `skills`, nothing else executable. |
| `skills/codex-auto-resume/SKILL.md` | What Codex reads to answer "turn on auto resume". |
| `scripts/plugin_setup.py` | The control layer the skill calls. |
| `scripts/watcher_launcher.py` | Stable autostart entry point (see below). |

`codex plugin add` copies the **plugin root subtree** into
`<CODEX_HOME>/plugins/cache/<marketplace>/<plugin>/<version>/`. Because the root is the plugin
root, `src/` travels with it. A nested `plugins/codex-auto-resume/` layout would have required
duplicating the engine, since the copy cannot reach outside the plugin root.

Verified against `codex-cli 0.153.4`, including with the plugin folder name deliberately
different from the plugin name (a clone is named `codex-auto-resume-windows`, the plugin is
`codex-auto-resume`). Codex's own `validate_plugin.py` accepts this layout.

## The MCP server

The manifest declares `skills` and `mcpServers`. `hooks` is **rejected** by Codex plugin
validation, so it is not used. The server exists so the product can be managed from inside
Codex - status, pending recoveries, settings, pause, cancel - and so those actions mean the
same thing they mean everywhere else, because every one of them calls the same validated
control layer the command line and the settings window call.

It is a front end and nothing more. No tool detects a failure, schedules an attempt, reserves
an interruption or sends a continuation; the watcher stays the only thing that recovers, and it
keeps running when the server is not. That is a property of the surface, not a rule the model is
asked to follow: there is no call that retries an unclassified failure, resolves a conversation
by anything but its exact id, resends an uncertain submission or forces a send.

### Two constraints that shaped it

**The command must be contained in the plugin.** Codex accepts a plugin stdio `command` only as a
bare executable name or a path inside the plugin, and `cwd` only as a contained `./`,
`${PLUGIN_ROOT}` or `${PLUGIN_DATA}` path. An absolute path to the bundled interpreter is
neither, and a bare `python` would put back the system-Python requirement the product removed.
So the payload ships `mcp/codex-auto-resume-mcp.exe`, a small launcher that resolves the
interpreter from the runtime home and starts the server.

**The launcher relays the standard streams; it does not let the child inherit them.** A child
process started with `CREATE_NO_WINDOW` and no explicit handle passing is given no usable
standard handles at all. The server then waits forever for input, the host waits forever for a
handshake, and nothing appears in any log. That was measured here, not guessed: the first
version inherited, and both processes sat idle until they were killed.

Registration was verified against `codex-cli 0.153.4`:

```
> codex mcp get codex-auto-resume
codex-auto-resume
  enabled: true
  transport: stdio
  command: ./mcp/codex-auto-resume-mcp.exe
  cwd: ...\plugins\cache\codex-auto-resume-windows\codex-auto-resume\0.5.0\.
```

`"cwd": "."` rather than `"${PLUGIN_ROOT}"`: both are accepted by the validator, but the
variable form is reported back as a literal path segment appended to the plugin root, so the
plain form is the one that resolves the way it reads.

## Runtime state lives outside the plugin

The plugin cache path contains the version, so it changes on every update. Two consequences are
designed around:

- **State must not live in the plugin.** Pending interruptions, settings and logs live in
  `%USERPROFILE%\.codex-auto-resume\`. Updating or removing the plugin never destroys them.
- **Autostart must not point into the plugin.** Setup copies `watcher_launcher.py` to that same
  stable directory and registers *that*. At each launch it re-resolves the newest installed
  plugin version, so an update needs no re-registration.

Tested: after replacing `0.2.0` with `0.2.1+codex.local-test` and deleting the old directory,
the launcher resolved the new one and the state was untouched.

## `codex plugin remove` vs `uninstall`

They are different operations and neither implies the other.

| | `codex plugin remove` | `plugin_setup.py uninstall` |
| --- | --- | --- |
| Removes the skill from Codex | yes | no |
| Stops a running watcher | no | yes |
| Removes sign-in autostart | no | yes |
| Deletes pending state and logs | no | yes |

There is no plugin uninstall hook to attach to, so removing the plugin cannot clean up on its
own. It does not leave a watcher running forever either: with the plugin gone the launcher finds
no engine, logs one line and exits, so autostart stops at the next sign-in. To remove everything
at once, run `uninstall` first, then `codex plugin remove`.

## Two installations are refused, not merged

A manual checkout and a plugin installation keep separate state and separate single-instance
locks, so both watchers would run and could each resume the same interruption. `setup` therefore
checks the registered autostart value and stops if it belongs to a different installation.
`status` reports the same conflict.

Related: `uninstall` only unregisters an autostart value that belongs to the home being
uninstalled. It reports and keeps anything else.

## Language

English is the default. Korean is used only when Korean is the **most preferred** UI language.

Detection reads the same source the ChatGPT desktop app uses for its own display language:
Electron's `app.getPreferredSystemLanguages()`, which on Windows is `GetUserPreferredUILanguages`.
Falling back, it reads `LC_ALL` / `LC_MESSAGES` / `LANG`, and `CODEX_AUTO_RESUME_LANG` overrides
everything. No language is inferred from an IP address, a time zone, a user name, a country or a
keyboard layout. An unavailable probe means English, never a guess.

Strings live in one small table in `src/codex_auto_resume/messages.py`. No i18n framework and no
new dependency.

## The usage-limit checkbox: not possible through any official API

The goal was to add exactly one line to the usage-limit notice Codex already shows:

> ☑ Automatically resume this task after the reset

**This cannot be done through the official Codex plugin API.** It is not implemented, and nothing
pretending to be it was built in its place. Re-checked from scratch for v0.5; the answer has not
changed.

What was checked, against `codex-cli 0.153.4` and ChatGPT desktop `26.901.5280.0`:

1. **The plugin manifest has no UI surface.** Codex's own bundled plugin-authoring documentation
   and its `validate_plugin.py` accept exactly these top-level fields: `id`, `name`, `version`,
   `description`, `skills`, `apps`, `mcpServers`, `interface`, `author`, `homepage`, `repository`,
   `license`, `keywords`. `interface` is catalog presentation only — display name, description,
   category, logo, brand colour, screenshots, default prompts. Nothing addresses an error state
   or an app surface.
2. **`apps` / `.app.json` is not a UI extension.** Its entries carry only `id` and `category`;
   it registers connector apps, it does not render controls.
3. **Plugin-provided UI is conversation-scoped.** MCP App `ui://` resources are fetched through
   `mcpServer/resource/read` with an `originCallId` and a `threadId`, and render in a sandboxed
   iframe attached to a tool result. There is no placement that anchors to app chrome.
4. **The banner is hardcoded in the desktop app.** The notice is a React component built from
   compiled `react-intl` messages (`codex.upsellBanner.merged.title`,
   `codex.upsellBanner.*.headline`) inside the Electron bundle.
5. **`pluginSlots` is unrelated.** The name looks promising but it belongs to the sidebar
   onboarding checklist, mapping roles such as `mailApp` to connector names such as `gmail` so a
   prefilled prompt can mention the right plugin. It is not a rendering slot.
6. **There is no usage-limit lifecycle hook.** The hook event names in the binary are
   `PreToolUse`, `PostToolUse`, `UserPromptSubmit`, `SessionStart`, `SessionEnd`, `Stop`,
   `SubagentStop` and `Notification`. None fires on a usage limit — and plugin validation rejects
   `hooks` anyway.

### The three options, ranked, and what each one is worth

The question was re-opened from scratch for v0.5 against the build above, on the chance that a
newer Codex had added a surface. It has not. What follows is what each option is actually worth
today, best first.

**A — a real control inside the notice. Still impossible.** Everything in the list above was
re-checked against this build. The banner is still assembled from compiled `react-intl` message
ids inside the Electron bundle (`codex.upsellBanner.*.headline`, `codex.upsellBanner.cta.*`);
there is no id, slot, prop or plugin hook anywhere near it. Nothing in the plugin manifest, the
MCP schema or the app's own bundled plugins can address app chrome.

**B — a Codex-native form at the moment of the interruption. Available in principle, not shipped.**
An MCP server can call `elicitation/create`, and this build renders it: the wire types
`ElicitRequestParamsWire::Form` and `::Url` are present, and the response is `accept` / `decline`
/ `cancel`. A boolean property becomes a real checkbox. It carries no turn id, so it is not
structurally bound to a live turn.

It is not shipped anyway, and the reason is honest rather than technical. To reach a person at
the moment of the interruption, the server would have to push a form into whatever conversation
happens to be open, about a different conversation that failed - unasked, while they are working
on something else. It also only reaches them if Codex is open, which is exactly when it is least
needed, and the feature sits behind `features.tool_call_mcp_elicitation` (Statsig layer
`223073164`, param `enable_tool_call_mcp_elicitation`), so on a machine where the gate is off it
would silently do nothing at all. Building an interruption whose delivery cannot be relied on,
into a place the user did not ask for it, is worse than not building it.

What *is* shipped is the same mechanism where it belongs: an MCP settings panel the user opens by
asking. It renders in the conversation as a `ui://` resource on a read-only tool result, shows the
current state and every option, and can pause recovery or change a setting - the whole control
surface, at the moment the user wants it rather than at a moment we chose for them.

**C — a Windows notification. Shipped, and the one that actually arrives.** The watcher raises it
the moment the interruption is recorded, whether or not Codex is open, carrying the one control
the checkbox would have offered: a **Don't resume** button for that exact conversation, with
resuming as the default. It is not inside the Codex notice, but it arrives at the same moment,
which is the part that matters.

None of this is worked around. The only ways to put a control in that banner would be DOM or
renderer injection, an Electron or binary patch, a CDP/DevTools bridge, accessibility-control
injection, or GUI automation - all of them out of scope by design, and all of them would make
this tool something a person should not install.

If Codex later exposes an official inline control surface for this state, it is a small change:
one checkbox, defaulting to on, mapped to the existing per-thread cancel. No panel, no card, no
popup, no tray.

## Local installs copy the whole working tree

Installing from a local path copies every file in the directory, including files Git ignores
(`config/`, `logs/`, build scratch). Installing from GitHub clones the repository, so only
tracked files ship. Prefer the GitHub source unless you are developing the plugin.

## Long paths

The plugin cache path plus the script path can exceed the Windows `MAX_PATH` limit of 260
characters if `CODEX_HOME` is itself deeply nested. The default location is short and unaffected.
