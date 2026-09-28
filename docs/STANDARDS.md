# The standards

These are the rules the product keeps, by id. The **standard edition** keeps every rule in families 0
and A to J. The **advanced edition** is the standard edition plus capabilities that each depart from at
least one of them on purpose: every capability names the rules it departs from, and each is off until a
person turns it on in the Dashboard after reading what it does ([EDITIONS.md](EDITIONS.md)). Family K is
the advanced edition's own rules, which every capability keeps and none may depart from.

Each rule says how it is held:

- **tested** - a test fails if the rule is broken; the tests are named.
- **code** - the code holds it, but no test checks it yet.
- **docs** - promised in these documents; nothing mechanical checks it.
- **model** - an instruction to the model in the plugin's skill, which code cannot enforce.
- **planned** - not built yet.

The ids do not change: capability statements, the registry and the other documents cite them. A new rule
takes the next number in its family, and a rule the owner changes says so, with the date. The list was
reconciled on 2026-09-23, and family K was added on 2026-09-28. Nothing reads this file at run time:
`advanced/src/codex_auto_resume_advanced/standards.py` holds the ids as a count for each family, and
`advanced/tests/test_advanced_registry.py` reads this file and fails when the two differ or when a test
named here is not in the repository ([CONTRIBUTING.md](CONTRIBUTING.md) says how a rule is added or
changed).

## 0. The edition boundary

**0.1** The standard edition is the product as it is, plus only what keeps every standard. The advanced capabilities' code is left out of its archive and its setup program, and every release build proves it (K1).  
*tested*: `build/edition_audit.py`, `test_edition_audit.py`, `test_edition_build.py`, `test_edition.py`

**0.2** Everything the product already does keeps today's constraints, and the default never changes: it never sends again when the first continuation may already have been delivered.  
*docs*

**0.3** Anything these standards forbid exists only in the advanced edition, where each capability is off until a person turns it on after being told what it does (K3, K4).  
*tested*: `test_advanced_arming.py`, `test_advanced_registry.py`

**0.4** Each edition has its own archive, setup program and pinned digest, under one build attestation. An installation updates within its edition only; changing edition is a deliberate reinstall (K2).  
*tested*: `test_edition_bootstrap.py`, `test_edition_installer.py`

**0.5** The standard edition never retries unknown failures or sign-in failures, shares an app server, wakes an unloaded conversation through thread/resume, uses thread/inject_items, changes a goal's state, recovers subagents, replays model, provider or permission settings, dispatches several tasks at once, or recovers an empty response. The advanced edition offers some of these as capabilities that say they depart from 0.5.  
*tested in part*: `test_recovery.py`, `test_failures.py`, `test_engine.py`, `test_control_continuation.py`, `test_compat.py`

**0.6** The deciding line: keep the engine small, local, conservative and fail-closed; spend complexity on install and control.  
*docs*

**0.7** The Rust core (v0.6.14) replaces the implementation, not the behaviour: exact-thread, fail-closed, the registry's semantics and both editions are kept.  
*planned*

## A. What it may send to Codex, and when

**A1** Only the watcher sends, and inside it only Engine.dispatch hands a message on: to core's backend, or, in the advanced edition, to the channel a capability that is on puts in its place, asked for once through the plug. The control layer, bridge, MCP server, popup and card have no send path.  
*tested*: `test_structural_invariants.py`, `test_control.py`, `test_mcp.py`, `test_tray_popup.py`, `test_notice_card.py`

**A2** One channel only: the official `codex queue --thread <uuid> --message <text>`, started from one function (Backend.send in codex/transport.py) as an argument list with shell=False. The only other `queue` process is the --help probe, and the only other queue-touching call is the App Server delete.  
*tested*: `test_structural_invariants.py`, `test_windows.py`

**A3** Exact identity: a canonical UUID only; never --last, a title, project, folder or recency.  
*tested*: `test_structural_invariants.py`, `test_windows.py`, `test_mcp.py`

**A4** Each interruption carries one marker `[codex-auto-resume:<16 hex>]` (from v0.6.11 the first 16 of the interruption id's 64 hex digits; a record made before keeps, and is still found by, the whole id's `<64 hex>`; `downgrade-state --to 3` writes every marker back to the whole id's; the advanced edition's opt-in marker-free sending is its own capability), and delivery counts only when that marker is in that thread. The recovery turn is the marker row's turn, never "the latest turn". Two markers, a marker at or before the failed turn, or a client-id mismatch is ambiguous.  
*tested*: `test_source.py`, `test_correlation.py`

**A5** The interruption is claimed durably (BEGIN IMMEDIATE, synchronous=FULL) before any process can accept the message, and a crash after the claim never resends.  
*tested*: `test_engine.py`

**A6** Never resend when delivery is uncertain. Only a proven "process never started" may be retried. A non-zero exit, unmatched receipt, timeout or exception after spawn becomes submission_unknown, is watched for 24 h and is never sent again.  
*tested*: `test_engine.py`, `test_windows.py`

**A7** A withdrawal (thread/queue/delete) that cannot be confirmed becomes submission_unknown and is never re-sent, even though Codex may still deliver it.  
*tested*: `test_engine.py`

**A8** 13 gates run in a fixed order: consent, engine_compatible, single_owner, submission_safe, identity, known_failure, schedule, chain_budget, attempt_budget, no_progress_budget, thread_available, no_newer_user_work, usage. A gate never evaluated counts as a refusal. The store re-checks consent, submission_safe, schedule and budgets inside the claim transaction.  
*tested*: `test_engine.py`

**A9** A change between the claim and the send (cancel, pause, conversation off, superseded, history lag, someone's queued input, our marker already there, lost home lock) hands the claim back unsent: attempts are returned, and the claim time is kept for the caps.  
*tested*: `test_correlation.py`

**A10** Inside the dispatch lock it re-checks the app process identity, the loaded state and live usage (from a reading at most 30 s old).  
*code*

**A11** It sends only while the desktop app is running and the exact thread is loaded. notLoaded or unknown waits at waiting_for_loaded_thread; nothing is queued on the off chance.  
*tested*: `test_engine.py`

**A12** Never before the real reset time, and live usage is re-checked.  
*tested*: `test_engine.py`

**A13** Only classified kinds are recovered: usage limit, connection failure, timeout (408/425), rate limit (429, including responseTooManyFailedAttempts carrying 429), 5xx, and stream disconnect. The structured code comes first; message text is used only when there is no code, against a fixed phrase list.  
*tested*: `test_failures.py`

**A14** Never retried: anything unclassified, user cancellation, permission, approval, content policy, invalid request, context length, 401/403, badRequest, sandboxError, and responseTooManyFailedAttempts without a 429.  
*tested*: `test_recovery.py`, `test_failures.py`, `test_settings.py`

**A15** Only desktop-app user conversations. Subagent, archived and non-desktop threads are never detected.  
*tested*: `test_engine.py`

**A16** A failure is eligible only while it is the thread's latest turn and completed after arming minus the look-back (default 6 h, at most 7 days).  
*tested*: `test_engine.py`

**A17** Newer human work wins. A later turn supersedes the failure; someone's queued input makes it wait; a turn or queued input after ours makes it take ours back; a queued item the person edited becomes theirs and is not deleted.  
*tested*: `test_engine.py`, `test_recovery.py`

**A18** A history that has fallen behind its rollout blocks a new send, and a missing projection table blocks as incompatible.  
*tested*: `test_engine.py`

**A19** One continuation in flight per conversation, dispatched in sequence under one lock. There is no bulk retry; the only bulk action is Cancel all, one exact record at a time.  
*tested for bulk actions; code for the in-flight gate*: `test_control_continuation.py`

**A20** Caps that are engine constants, not settings: at most 5 claims per conversation in any 24 h, at least 15 min apart; at most 5 failed queue launches; a usage chain unavailable for 7 days expires, never before its reset plus a day.  
*tested*: `test_engine.py`

**A21** Budgets are settings with capped ranges: transient attempts 4 (1-20), recoveries in a row with no progress 3 (1-10), continuations per task chain 6 (1-10, never higher). A usage limit spends no attempt.  
*tested*: `test_engine.py`, `test_recovery.py`

**A22** Waits are bounded. A transient wait comes only from a preset ladder or from Custom's five waits, each picked from a closed list and never typed; a Retry-After or jitter only lengthens a wait, and a rate limit's first wait is at least a minute.  
*tested*: `test_recovery.py`, `test_ladder_and_guards.py`

**A23** One failure is recovered once. The same Codex turn under a new identity is refused. A chain child inherits its counters, and is created already stopped if its parent was cancelled, handed over or out of budget.  
*tested*: `test_store.py`, `test_recovery.py`

**A24** Give attempts back: only for exhausted records, at most 3 per task, never for cancelled or possibly-sent ones. It sends nothing and never switches a conversation on.  
*tested*: `test_store.py`

**A25** Retry now only moves the schedule. It sends nothing, skips no gate and opens no usage window.  
*tested*: `test_mcp.py`, `test_store.py`

**A26** The continuation text comes only from shipped templates or the Custom message, only for a recoverable category, and is decided before the claim; it cannot change what is recovered.  
*tested*: `test_continuation.py`

**A27** The Custom message, and a conversation's own message, are written only in the Dashboard; MCP update_settings refuses both and the preview tool takes no text. Each is at most 2000 characters and sent exactly as typed. Placeholders come from a whitelist ({reason},{category},{attempt},{max_attempts},{reset_time}); dangerous ones are refused by name. It is re-checked on read, and text that fails the check is treated as not set.  
*tested*: `test_continuation.py`, `test_mcp.py`, `test_conversation_message.py`

**A28** A notification or card button can only cancel one exact interruption (an opaque 64-hex id) or open one page from a fixed list; anything else is ignored and logged, and a button never causes a send.  
*tested*: `test_notify.py`, `test_notice_card.py`

**A29** A switch click carries the exact interruption and conversation. A stale, finished or other-conversation click is refused and changes nothing, and a switch sends nothing.  
*tested*: `test_control_continuation.py`, `test_tray_popup.py`

**A30** An engine is accepted only while `codex queue --help` still offers --thread and --message. Anything unproven is refused, and there is no version pin.  
*tested*: `test_windows.py`

## B. What it reads, and how

**B1** Codex SQLite is opened read-only: mode=ro, PRAGMA query_only=ON, trusted_schema=OFF.  
*tested*: `test_source.py`

**B2** No Codex database, rollout or config file is ever opened for writing; the WAL -shm update is disclosed.  
*code*

**B3** Codex's state changes only through official interfaces: codex queue, thread/queue/delete, and the codex plugin CLI at install and uninstall.  
*code*

**B4** The App Server is a separate, short-lived stdio helper. It sends only initialize (plus initialized), account/rateLimits/read and thread/queue/delete; requests from the server are refused; a wrong codexHome is refused.  
*tested*: `test_windows.py`

**B5** Only the newest database generation is read, and only if every column it reads exists; paths must stay inside the Codex home.  
*tested*: `test_source.py`

**B6** Rollout files only under <home>\sessions. It reads the first line (at most 256 KiB: id and origin), and for a usage limit only, up to 8 MiB before the failure, in memory, keeping only the reset time and the limit id.  
*tested for the path; code for the byte caps*: `test_source.py`

**B7** Queries that return message content are bounded by instr(col, marker)>0; other people's rows come back only as counts or booleans.  
*tested*: `test_source.py`

**B8** It never selects title, preview or first_user_message. Labels come only from threads.name, the project or the cwd basename, are one line of at most 72 chars, and never identify a thread.  
*tested*: `test_failures.py`

**B9** The raw error is classified and dropped; only the category continues. Progress comes from lifecycle columns and a fixed item-type list, never from content, except whether a message carries our marker.  
*tested*: `test_failures.py`, `test_recovery.py`

**B10** From the usage response it keeps only numeric windows, reset times and the bucket name.  
*tested*: `test_windows.py`

**B11** It never reads auth.json, tokens, cookies, authorization headers, credential storage or process memory.  
*docs*

**B12** Loaded state comes only from the Restart Manager inventory. There is no byte-lock API and the app's writer lock is never taken; ambiguity, PID reuse or an unavailable API reads unknown.  
*tested*: `test_windows.py`

**B13** No GUI automation, input simulation, UI Automation, OCR or screen capture: nothing reads or drives another window. The popup answers screen readers about itself, and the one PrintWindow is a build-only tool.  
*tested*: `test_surface_properties.py`

**B14** No web stack: no browser control, WebView, listening socket, localhost server or second runtime; the window compiles against System, System.Drawing and System.Windows.Forms only.  
*tested*: `test_surface_properties.py`

**B15** Compatibility probes read only the schema's table and column names and whether folders exist, never a row.  
*code*

**B16** Windows is asked only content-free questions, and AppsUseLightTheme and TrayNotify are read, never written.  
*code*

**B17** Layering: the engine imports no sqlite3, ctypes or subprocess and reaches Codex only through its injected adapters; the UI and MCP never import Codex's readers; the domain layer is pure standard library; only listed modules import subprocess.  
*tested*: `test_layers.py`, `test_structural_invariants.py`

## C. Network

**C1** The runtime has no network code: no file under src/ or advanced/src/, and no scripts/*.py, imports a networking module.  
*tested*: `test_privacy_claims.py`

**C2** Exactly one shipped file reaches the network: scripts/bootstrap.ps1. build/ downloads the pinned Python while a release is built; what ships from it - the install scripts and the setup program - reaches nothing.  
*tested*: `test_privacy_claims.py`, `test_setup.py`

**C3** No telemetry, analytics or crash reporting, and shipped files name no unexpected host.  
*tested*: `test_privacy_claims.py`

**C4** Nothing happens on its own: no update polling, no schedule, nothing at start, no automatic compatibility refresh.  
*tested*: `test_convergence.py`, `test_gui_update.py`

**C5** The update check runs only when a person presses the button. It sends one HEAD to a constant releases/latest URL and reads the version from the redirect under this exact repository, rebuilt from its integers. It also reads this repository's list of releases to find a newer pre-release, which it offers with a question and installs only on a yes (amended by the owner on 2026-09-28).  
*tested*: `test_update_check.py`, `test_convergence.py`, `test_prerelease_offer.py`

**C6** Setup download: HTTPS, at most 5 redirects, URL built from constants and the manifest version, final host one of three GitHub hosts (checked after the download, which is disclosed), at most the archive and its .sha256.  
*tested*: `test_convergence.py`, `test_update_check.py`

**C7** Compatibility refresh only on request: one GET to a constant raw.githubusercontent.com URL with no query, at most 256 KiB, never parsed or run by PowerShell, never started by the watcher or any MCP tool.  
*tested*: `test_compat_bootstrap.py`, `test_compat_surfaces.py`

**C8** Requests carry no product-invented identifier. GitHub sees the IP, the time and PowerShell's User-Agent, which is disclosed.  
*tested for the constant URLs; no custom header exists in bootstrap.ps1*: `test_update_check.py`

**C9** OpenAI is reached only through official Codex: a usage read when a recovery is due, reused for 30 s, identified as codex_auto_resume with the real version.  
*code*

**C10** Every codex process it starts runs with OTEL_SDK_DISABLED, analytics off, OTel exporters none, log_user_prompt=false and chatgpt_base_url pinned.  
*tested*: `test_privacy_claims.py`, `test_windows.py`

**C11** The installer refreshes only this product's marketplace, by name.  
*code*

**C12** Translations, the panel and the window fetch nothing; the MCP manifest declares no environment or network.  
*tested*: `test_l10n.py`, `test_mcp.py`, `test_plugin.py`

**C13** Disclosure: whatever the tools and commands return becomes part of the Codex conversation and goes to OpenAI.  
*docs*

## D. Privacy and the data it keeps

**D1** Nothing goes to the developer: no prompts, replies, files, ids, credentials, raw errors, titles, paths or statistics.  
*docs*

**D2** State holds only ids, enums, counters and times, with bounded, control-character-free text and no prompt, reply or error text. The one disclosed exception is the conversation title in notifications.  
*tested*: `test_store.py`, `test_engine.py`

**D3** Logs are written from a fixed message table. Untrusted values are masked unless hex or digits, the main log keeps only exception class names, and tracebacks go to errors.log. Disclosed: the state directory path and the engine version.  
*tested*: `test_engine.py`

**D4** The journal holds closed-vocabulary codes and integer flags only, is bounded to 5,000 entries and 90 days, and is never read to decide anything.  
*tested*: `test_store.py`, `test_surface_properties.py`

**D5** Diagnostics export only on request, to a chosen path, never overwriting, and nothing sends it. Ids become per-file aliases; paths, the user name and e-mail addresses are redacted; a Custom message is recorded as set, never quoted.  
*tested*: `test_diagnostics.py`

**D6** Notifications: up to 2 one-line labels of at most 72 chars plus the UUID, no error or account text, at most 3 lines, XML-escaped; the card shows what the toast shows.  
*tested*: `test_notify.py`

**D7** get_status carries the compatibility summary as codes only and no install path. It does return the settings, including the Custom text and the codex_exe path, read-only, which is disclosed.  
*tested*: `test_mcp.py`, `test_compat_surfaces.py`

**D8** Values that reach PowerShell travel as environment variables to constant scripts, and PowerShell is run by its full System32 path.  
*tested*: `test_pwsh.py`, `test_gui_update.py`

**D9** Errors that reach a front end are static codes, and every refusal carries a code from one closed set.  
*tested*: `test_control.py`, `test_mcp.py`

**D10** Uninstall keeps settings and pending state by default; purging is opt-in.  
*tested*: `test_installer.py`

**D11** Repository and evidence hygiene: synthetic UUIDs and placeholder homes only, and content-free live evidence.  
*tested*: `test_repo_hygiene.py`, `test_screenshots.py`, `test_live_evidence.py`

**D12** The language is never inferred from the IP, time zone, user name, country or keyboard layout; only the first Windows UI language counts.  
*code*

**D13** Users are told never to paste credentials, conversations or unredacted logs into public issues.  
*docs*

## E. Failure behaviour

**E1** Fail closed: unknown loaded state, unknown usage, an unavailable probe, a missing projection table, corrupted state or a compatibility evaluation that could not run all mean waiting or refusing, never sending.  
*tested*: `test_engine.py`, `test_compat_io.py`

**E2** Rather miss a resume than resume twice.  
*docs*

**E3** A corrupt, empty, symlinked or malformed state, a newer schema or an unknown record state fails closed and is never reset. Migration runs only under the watcher mutex, after a forensic copy, in one transaction.  
*tested*: `test_store.py`

**E4** While an older watcher still owns an older schema, only actions that reduce automation work.  
*tested*: `test_control_v3.py`

**E5** A malformed or oversized settings file reads as defaults, a wrong type is refused on write, and a gate vector that does not decode reads UNKNOWN.  
*tested*: `test_settings.py`, `test_control.py`

**E6** A turn that never finishes is outcome_unverified, never a success, and unreadable history never becomes "no progress".  
*tested*: `test_outcomes.py`

**E7** Uninstall stops before removing anything, registrations included, unless the watcher is definitely not running; a process whose path cannot be read is skipped, never killed.  
*tested*: `test_cli.py`

**E8** Stopping is always a request. An upgrade waits up to a minute and never kills; only this plugin's own MCP launchers (by path) and its own short-lived Codex helpers are ever terminated.  
*tested*: `test_control.py`, `test_installer.py`, `test_upgrade_handover.py`

**E9** Bootstrap runs nothing from the archive until every check passes, and any failure deletes the download.  
*tested*: `test_convergence.py`

**E10** If the download fails, the skill stops: no other source and no hand-assembled install.  
*model*

**E11** Notifications, the tray and the failure-seen file never decide or delay a recovery; the card falls back to the toast when unsure; turning notifications off changes nothing.  
*tested*: `test_notice_card.py`

**E12** A mutex, stop event or wake event planted by a lower-integrity process is refused. Taking over a running watcher's mutex is not covered, which is disclosed.  
*tested*: `test_named_objects.py`

**E13** An update check that could not ask never reads as "up to date": four answers, four exit codes.  
*tested*: `test_gui_update.py`

**E14** A transient adapter, store or probe failure at logon defers the tick and never ends the watcher.  
*tested*: `test_cli.py`

## F. Footprint on the machine

**F1** No administrator rights, per-user only, no service, no scheduled task, nothing machine-wide.  
*tested*: `test_installer.py`

**F2** Registry writes, all under HKCU: the Run value (only if chosen, removed only while it is ours), Software\Classes\codex-auto-resume and Software\Classes\AppUserModelId\CodexAutoResume.Watcher.  
*tested per key; code that no other key is written*: `test_cli.py`, `test_notify.py`, `test_plugin.py`

**F3** Its own files: config/ and logs/ with a provenance marker, program files in the home (%USERPROFILE%\.codex-auto-resume, never AppData), a Start Menu shortcut, and diagnostics only where asked.  
*tested*: `test_plugin.py`

**F4** Path confinement: an owned directory that is a link or resolves outside the home (NTFS junctions included) is refused.  
*tested*: `test_cli.py`, `test_installer_ownership.py`

**F5** Nothing is destroyed without proven ownership; the disclosed exceptions are per-user singletons replaced by name and the marketplace repointed.  
*tested*: `test_installer_ownership.py`

**F6** Processes it starts: its own - the watcher, the settings window and the bundled Python behind them; codex app-server --stdio, codex queue, and the --version and queue --help probes; the codex plugin commands when it installs and uninstalls; and PowerShell by its full path with constant scripts - always as argument lists.  
*tested*: `test_structural_invariants.py`, `test_pwsh.py`

**F7** Single instance: a per-user, per-state-directory mutex, a stop event and a per-Codex-home lock; a second watcher exits, the send gate requires the lock, and a second installation is refused.  
*tested*: `test_engine.py`, `test_surface_properties.py`, `test_plugin.py`

**F8** No resident helpers: one watcher process hosts the icon, popup and card, with no tray process, supervisor, service, web UI or second engine; Codex helpers are short-lived.  
*tested partly*: `test_tray_popup.py`

**F9** An upgrade or repair never switches recovery back on and never re-adds a removed sign-in entry (--keep-state); an older plugin never replaces a newer install without -Force.  
*tested*: `test_installer.py`, `test_plugin.py`, `test_update_check.py`

**F10** The sign-in launcher starts only this installation, this product's marketplace copy or the recorded copy, and otherwise nothing.  
*tested*: `test_plugin.py`, `test_upgrade_handover.py`

**F11** The skill runs bootstrap.ps1 only by its absolute path, after checking the manifest names this product.  
*model*

**F12** Install safety: a named installer lock (including the bootstrap repair branch), a move-aside journal before the first move, rollback on failure, the root claimed before the first write, and state directories never replaced.  
*tested*: `test_installer.py`, `test_convergence.py`, `test_installer_ownership.py`

**F13** Standard library only, on the bundled Python; a system Python never sets up a second installation.  
*tested partly*: `test_installer.py`, `test_layers.py`

**F14** Starting the watcher when Codex starts is not offered in the standard edition: a watcher started from inside Codex ends when Codex closes (measured on Codex 26.915), so the setting exists and is not offered. The advanced edition's start-with-Codex does it outside Codex's job, through WMI.  
*tested*: `test_start_with_codex.py`, `test_settings.py`

## G. The Compatibility Registry's authority

**G1** Data can only restrict. A failed local check always wins (INCOMPATIBLE, or FAILED_HERE where the data vouched for the version), and both block every send.  
*tested*: `test_compat.py`, `test_compat_io.py`

**G2** Data may raise only a local PASS, only for an exact version, only to CHECKED or VERIFIED; that changes the word, not what is sent, and ranges only restrict.  
*tested*: `test_compat.py`

**G3** The gate sends on verified, checked or structurally_compatible; failed_here and incompatible block; anything else is UNKNOWN, which sends nothing, and a failing evaluation fails closed.  
*tested*: `test_compat_io.py`

**G4** Evidence rule: VERIFIED needs a cited evidence file recorded on that exact version from a real recovery that exercised the capability; CHECKED also needs evidence; no URL citations; the build refuses data the validator would refuse.  
*tested*: `test_compat.py`

**G5** The validator (controlcli compat-import) is the only writer of compat-cache.json. It refuses the whole document for an unknown format, malformed content, over 256 KiB (checked before parsing), a duplicate key, a non-finite number, excessive depth, a trust-granting range, requires_signature, rollback, a date more than 1 day ahead, or a newer product; a refusal leaves the cache untouched.  
*tested*: `test_compat.py`, `test_compat_io.py`

**G6** The cache is validated on every read. Expired or future-dated data keeps its restrictions and loses its trust; no clock lifts a restriction; a bad cache is ignored, never deleted.  
*tested*: `test_compat.py`, `test_compat_io.py`

**G7** The watcher's report is bound to the executable (path digest, size, mtime); readers refuse one that is damaged, stale or about a changed binary.  
*tested*: `test_compat_io.py`

**G8** Everything shown to a person or model is a closed-list code, never document text; MCP reads codes only and cannot refresh or import.  
*tested*: `test_compat.py`, `test_compat_surfaces.py`

**G9** Every installed release takes the newest data on main whole; behaviour tests read a frozen copy.  
*tested*: `frozen_registry.py`

**G10** With the bundled data, the gate decides what it decided before the registry existed.  
*tested*: `test_compat_characterization.py`

**G11** The data is unsigned; the signature slot is reserved and requires_signature is refused. The bounded worst case is recovery stopping for one build.  
*docs for the residual risk; tested for the refusal*: `test_compat.py`, `test_compat_io.py`

**G12** Capabilities without checks (empty-response, notLoaded, Goal, subagent) stay tier 'unsupported'.  
*tested*: `test_compat.py`

**G13** Reports from others are shown apart, never raise a version to Verified or Checked, and change nothing the product does; the standard edition sends nothing for them.  
*tested*: `test_community_report.py`, `test_compat.py`, `test_compat_surfaces.py`

## H. User control

**H1** Defaults: recovery on, every recoverable category ticked, notifications, card and icon on, the Standard message in the interface language, sign-in start unless -NoStartup; a fresh state starts disabled until setup enables it.  
*tested*: `test_settings.py`

**H2** Settings are policy only. None can retry unknown failures, resolve by title, resend an uncertain submission, force a send, skip revalidation or move an engine constant. Writes are strict: refused, never clamped.  
*tested*: `test_engine.py`, `test_settings.py`

**H3** Three surfaces write one settings file through one validator, and only the Dashboard writes the Custom text. update_settings does not offer the engine path, look-back, tray icon, Reduce motion, card or Custom text, and refuses them even if the schema is ignored.  
*tested*: `test_mcp.py`

**H4** Global pause is an immediate kill switch that keeps pending records. It withdraws a queued continuation; a confirmed withdrawal returns the record to waiting with its attempt back; a pause over an uncertain submission ends it final.  
*tested*: `test_engine.py`, `test_pause_unknown.py`

**H5** Switching a conversation off cancels what waits there, and a cancel is final: re-enabling does not revive it, and budget restore refuses it.  
*tested*: `test_engine.py`, `test_store.py`

**H6** Cancel always works, covers the whole chain, withdraws a still-queued item and never stops a running turn.  
*tested*: `test_store.py`

**H7** Doing nothing resumes, except where a setting holds a recovery for the person - a conversation set to Ask me first or Only notify me; a project that Projects that may resume does not allow, or, under either list, one whose project cannot be read; a task the task-changed guard finds changed, set to Hold it for me; a conversation past the context-cost guard's Hold above; what fell due during a sleep longer than Ask me after a sleep longer than - and while Observe only is on, when nothing is sent. Don't resume / Don't retry only cancels.  
*tested*: `test_notify.py`, `test_postpone_and_tiers.py`, `test_observe_and_admission.py`, `test_ladder_and_guards.py`, `test_power.py`

**H8** MCP tools that add automation or cannot be undone carry destructiveHint (resume, enable_conversation, update_settings, restore_default_settings, cancel_recovery, reset_recovery_budget, start_watcher, release_hold, clear_recovery_history); pause, conversation-off, retry_now and postpone are unmarked. This is a request, not a lock.  
*tested*: `test_mcp.py`, `test_mcp_v3.py`, `test_postpone_and_tiers.py`

**H9** If a marked tool is declined, the model must not run the matching command, must never "force" a resume, and must not work around a missing safety setting.  
*model*

**H10** Clear history only hides rows. Hidden rows count for every cap and duplicate check, and anything that may still change is never hidden.  
*tested*: `test_store.py`

**H11** Switch commands accept only real JSON booleans, so the string "false" never turns automation or the Run value on.  
*tested*: `test_control.py`

**H12** Each recoverable category has its own switch, and a switched-off category is never recorded.  
*tested*: `test_engine.py`

**H13** An explicit interface-language choice wins over Windows and CODEX_AUTO_RESUME_LANG and survives restarts, repairs and updates; motion stops under Reduce motion, Windows' animation setting, High Contrast, battery saver, a locked session and the overflow area.  
*tested*: `test_locale.py`, `test_tray_icon_motion.py`

## I. Release and supply chain

**I1** Releases are built by Actions from the tagged commit, after the full suite. The tag equals the manifest's version; a pre-release tag (-alpha or -beta, then numbered: -alpha.2, -beta.2 and so on) publishes a GitHub pre-release that is never the latest release.  
*tested*: `test_workflow_privilege.py`, `test_plugin.py`, `test_version_rule.py`

**I2** Two jobs split by privilege. build has contents: read, does not persist its token, and runs repo code; publish runs no repo code and only on a tag push; a dispatch is a dry run; no expression is spliced into a run script.  
*tested*: `test_workflow_privilege.py`, `test_convergence.py`

**I3** Every Action is pinned to a full SHA, and Dependabot proposes but never auto-merges.  
*tested*: `test_workflow_pins.py`

**I4** A published version is never replaced. This is the workflow's rule, not GitHub immutability, which is disclosed.  
*tested*: `test_convergence.py`

**I5** Each released version's digest is pinned in scripts/release.json on main from the published file.  
*tested*: `test_convergence.py`

**I6** Bootstrap checks the SHA-256 against the pin, else the sidecar, and says which; an unpinned -ArchivePath says "NOT checked"; it checks the archive is this product at this version with no escaping entry, before anything runs; it never announces an unverified archive as verified.  
*tested*: `test_convergence.py`

**I7** Every archive since v0.5.4 has a build provenance attestation, and users are told how to verify it; the product itself never checks it.  
*code*

**I8** Reproducible executables (normalised PE timestamp and MVID, built twice with a refusal if they differ) and a deterministic archive (listed files, sorted, fixed timestamps; build/, tests/, config/, logs/ and state excluded).  
*tested*: `test_reproducible.py`, `test_surface_properties.py`

**I9** Archive entries are checked in build, and the checksum again in publish; the required-entry list equals what installed bootstraps need.  
*tested*: `test_convergence.py`, `test_installer.py`

**I10** The bundled Python is pinned by version and SHA-256.  
*tested for the version; code for the SHA-256*: `test_python_support.py`

**I11** The repository manifest declares only skills; the MCP server is added at build time beside its runtime.  
*tested*: `test_plugin.py`

**I12** Updates never go to an older version without -Force, only to a version resolved under this exact repository, and install with --keep-state. A pre-release is installed only when the person says yes to it when the update check offers it, never older than what is installed, and checked against its published .sha256 (amended by the owner on 2026-09-28).  
*tested*: `test_update_check.py`, `test_prerelease_offer.py`

**I13** Nothing is Authenticode-signed, which is disclosed, and users are never asked to disable SmartScreen or Smart App Control.  
*docs*

**I14** A person runs the live acceptance before each release, and a release needs both halves.  
*docs; not met for every release*

**I15** Safety scans read the whole package through one scanner, imports point down or sideways, and module size ceilings only shrink.  
*tested*: `srcscan.py`, `test_layers.py`, `test_sizes.py`

**I16** English text changes reach every catalog or are marked reviewed; the Korean docs claim nothing the English do not; every release keeps its changelog section.  
*tested*: `test_korean.py`, `test_privacy_claims.py`

**I17** A user-visible fix ships with its regression test, and a safety change with a test that fails without it. The repository's history is not rewritten; the one exception, on 2026-09-27, removed personal data from every commit.  
*docs*

## J. Presentation rules that are promises

**J1** Evidence levels are claimed only as earned: a closed set, every cited test exists, no REAL CODEX VISUALLY TESTED row, PUBLISHED only where the published bytes were driven again.  
*tested for form only; the truth and the PUBLISHED rule are docs*: `test_feature_matrix.py`

**J2** Screenshots come from a generator and synthetic data, are never edited by hand, are not evidence of a recovery, and are regenerated when their inputs change.  
*tested*: `test_screenshots.py`

**J3** No network claim stands without a qualifier; PRIVACY names GitHub and its third parties; the README privacy row must "admit the download".  
*tested*: `test_privacy_claims.py`

**J4** The roadmap is a direction, not a promise, and limitations are stated up front: the conversation must be loaded, and the real-world evidence is one run.  
*docs*

**J5** Live acceptance: an empty directory is not a pass; never fake a usage limit or edit state; every click is a person's; the validator checks shape, not truth.  
*tested for shape only*: `test_live_evidence.py`

**J6** Approval prompts are never claimed.  
*docs*

**J7** States are never overstated. A public status is a pure function of the record, never of a setting; failed is final, never "retrying"; overlays apply only to unsent records; unknown never reads as running; outcome_unverified is not a success; "recovered" only when our own turn produced progress.  
*tested; the SKILL.md parts are model*: `test_labels_v3.py`, `test_outcomes.py`, `test_control.py`, `test_engine.py`

**J8** Statistics count one final outcome per record, include hidden rows, and show no success rate below five outcomes.  
*tested*: `test_store.py`

**J9** An uncertain submission is reported as uncertain, each notification is raised once, and a record born stopped is announced as stopped.  
*tested*: `test_engine.py`, `test_notice_card.py`

**J10** The countdown only means the watcher looks again; Retry now and budget restore replies keep the "every check still applies" caveat.  
*tested*: `test_tray_popup.py`, `test_control.py`, `test_mcp.py`

**J11** The model reports only what the command printed, never states a digest itself, and says "removed completely" only after all four steps.  
*model*

**J12** No colour without a word; contrast is 7:1 for text, 4.5:1 for secondary text and accent, 3:1 for the focus ring.  
*tested for contrast; docs for the rest*: `test_brand.py`, `test_focus_rings.py`

**J13** Compatibility words: verified, checked and compatible send alike; failed here and incompatible block; unknown is never shown as compatible; every surface says the gate's word.  
*tested*: `test_compat_surfaces.py`

**J14** Red until seen: the icon goes red only for a certain, unhidden, unseen failure after which nothing started; the seen time only moves forward.  
*tested*: `test_failure_seen.py`

## K. The advanced edition's own rules

**K1** The standard edition's archive and setup program hold no advanced code. The archive is built from trees that do not name advanced/, and build/edition_audit.py proves it from the two archives' and the two setup programs' bytes in every release build, before anything is kept: no advanced path, file, name or marker in any entry, a text file, a binary or a zip inside the zip; the standard archive built again from `git archive` with advanced/ deleted is the same file; every standard entry is in the advanced archive unchanged, but the settings window, which each edition builds for itself, and the manifest's display name. The publish job checks the listings again.  
*tested*: `build/edition_audit.py`, `test_edition_audit.py`, `test_edition_build.py`, `test_edition.py`

**K2** Updates stay within an edition. An update, and a pre-release the update check offers, fetch the installed edition's archive and check it against the digest the installed copy pins for that edition and version where it has one, and otherwise against the .sha256 published beside it (today every pre-release and every advanced archive); a bootstrap or installer that meets the other edition refuses before anything moves unless the change was asked for and confirmed, and says it first; a change of edition is a reinstall that keeps settings and pending recoveries and starts every advanced capability off.  
*tested*: `test_edition_bootstrap.py`, `test_edition_installer.py`, `test_prerelease_offer.py`

**K3** Arming only in the Dashboard. Arming.arm refuses every actor but the Dashboard, one capability at a time, and needs the statement revision, the generation, the warnings and, for on, the Codex version the Dashboard showed, each still holding; every other surface (MCP, the icon, a card) may only turn capabilities off; no MCP tool arms, whatever a client sends, and the one-shot bridge never reaches the plug.  
*tested*: `test_advanced_arming.py`, `test_advanced_surfaces.py`

**K4** Off by default, and advanced only by departing. Every capability starts off, entering the edition turns every one off, and a watched one never promotes itself; departs_from is never empty and names only standards the standard edition keeps (0.1-0.7, A-J), so a capability that keeps every standard belongs in the standard edition.  
*tested*: `test_advanced_arming.py`, `test_advanced_registry.py`

**K5** Pause and consent precede every capability. Core asks the plug only after the consent gate: a paused watcher asks it nothing, a conversation switched off or a cancelled record is never put to it, a pause that commits after the pre-send look stops a route or channel at the launch guard, and a pause stops start-with-Codex before any WMI create. Every gate, the durable claim and the pre-send look stay core's.  
*tested*: `test_plug_points.py`, `test_advanced_start_with_codex.py`, `test_advanced_marker_free.py`, `test_advanced_goal.py`

**K6** A failed measurement is a warning the person confirms, and only policy keys refuse. A measurement a route rests on that failed or has no pass for the Codex in force, a grade of FAILED_HERE, INCOMPATIBLE or UNKNOWN, or no Codex version known is shown in the statement and confirmed by arming, never a refusal (the owner, 2026-09-26, replacing decision C7). What refuses is ForbidAdvanced, AllowedCapabilities and ForceShadow (for on) under Software\Policies\CodexAutoResume, HKLM and HKCU, read and never written, together the stricter, the strictest where unreadable.  
*tested*: `test_advanced_arming.py`, `test_advanced_goal.py`, `test_advanced_marker_free.py`

**K7** Tripwires switch a capability off, and re-arming is always possible. A new statement revision, a warning the person did not confirm that says what it stands on went wrong (failed here, a local check failed, incompatible, a measurement failed), one of its hooks raising, a send it paid for gone submission_unknown, and, for one that is on, a new Codex version each turn it off; whatever turned it off, the Dashboard can turn it on again with the statement as it then reads.  
*tested*: `test_advanced_arming.py`, `test_advanced_goal.py`, `test_advanced_marker_free.py`
