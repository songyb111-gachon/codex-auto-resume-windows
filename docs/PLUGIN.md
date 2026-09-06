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

## No MCP server

The manifest declares only `skills`. Codex plugins may also declare `mcpServers` and `apps`,
but a skill is enough here, and an MCP server would add a long-lived process that the watcher
does not need. `hooks` is **rejected** by Codex plugin validation, so it is not used either.

## Runtime state lives outside the plugin

The plugin cache path contains the version, so it changes on every update. Two consequences are
designed around:

- **State must not live in the plugin.** Pending interruptions, settings and logs live in
  `%LOCALAPPDATA%\codex-auto-resume\`. Updating or removing the plugin never destroys them.
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

**This cannot be done through the official Codex plugin API.** It was not implemented, and no
substitute GUI was built in its place.

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

### The one official GUI mechanism, and why it still does not help

Codex does support plugin-driven UI, so "no GUI is possible" would be too strong a claim. Two
mechanisms exist:

- **MCP elicitation.** An MCP server can call `elicitation/create` with a JSON schema, and the app
  renders a real form; a boolean property becomes a real checkbox. The response comes back as
  `accept` / `decline` / `cancel`.
- **MCP App widgets.** A tool result can carry a `ui://` resource in `_meta`
  (`openai/outputTemplate` or `ui.resourceUri`) which renders in a sandboxed iframe.

Neither solves this problem, for three reasons:

1. **Both require a live turn.** They are driven by a tool call. When a usage limit hits, the turn has
   already failed, so nothing of ours is running and nothing can be rendered at that moment — which is
   exactly the moment the checkbox was for.
2. **Both render in the conversation, not in the banner.** They cannot be attached to app chrome.
3. **Elicitation is behind a remote feature flag** (`tool_call_mcp_elicitation`, Statsig-gated). On the
   development machine `electron-openai-mcp-form-elicitations-enabled` reads `false`, so the form would
   not render there at all.

A widget reachable only by asking for it would add an MCP server process and a second UI surface to
replace something the user can already do by asking in words. That trade is not worth it here, so it
was not built.

The only ways to put a control in that banner would be DOM or renderer injection, an Electron or
binary patch, a CDP/DevTools bridge, accessibility-control injection, or GUI automation. Every one
of those is out of scope for this project by design, so the checkbox is not implemented.

What exists instead is natural-language control through the skill. Per-conversation cancellation
is available today (`cancel <thread-uuid>`), which is the behaviour the checkbox would have
provided; it just does not live in that box.

If Codex later exposes an official inline control surface for this state, this is a small change:
one checkbox, defaulting to on, mapped to the existing per-thread cancel. No panel, no card, no
popup, no tray.

## Local installs copy the whole working tree

Installing from a local path copies every file in the directory, including files Git ignores
(`config/`, `logs/`, build scratch). Installing from GitHub clones the repository, so only
tracked files ship. Prefer the GitHub source unless you are developing the plugin.

## Long paths

The plugin cache path plus the script path can exceed the Windows `MAX_PATH` limit of 260
characters if `CODEX_HOME` is itself deeply nested. The default location is short and unaffected.
