# The standards

These are the rules the product keeps, by id. The **standard edition** keeps every rule in families 0
and A to J. The **advanced edition** is the standard edition plus capabilities, each of which departs from
at least one of those rules on purpose. Every capability names the rules it departs from, and each is off
until a person turns it on in the Dashboard after reading what it does ([EDITIONS.md](EDITIONS.md)).
Family K holds the advanced edition's own rules, which every capability keeps and none departs from.

Each rule says how it is held:

- **tested** - a test fails if the rule is broken; the tests are named.
- **code** - the code holds it, but no test checks it yet.
- **docs** - promised in these documents; nothing mechanical checks it.
- **model** - an instruction to the model in the plugin's skill, which code cannot enforce.
- **planned** - not built yet.

The ids do not change, because capability statements, the registry and the other documents cite them. A
new rule takes the next number in its family, and a rule the owner changes says so, with the date. The
list was reconciled on 2026-09-23, and family K was added on 2026-09-28. The whole page was reworded at the owner's word on 2026-11-11, and each rule kept its meaning; a rule whose old sentence did not match the code says so. Nothing reads this file at run
time. `advanced/src/codex_auto_resume_advanced/standards.py` holds the ids as a count for each family, and
`advanced/tests/test_advanced_registry.py` reads this file and fails when the two differ or when a test
named here is not in the repository ([CONTRIBUTING.md](CONTRIBUTING.md) says how a rule is added or
changed).

## 0. The edition boundary

**0.1** The standard edition is the product as it is, and everything added to it keeps every standard. The advanced capabilities' code is left out of its archive and its setup program, and every release build proves it (K1).  
*tested*: `build/edition_audit.py`, `test_edition_audit.py`, `test_edition_build.py`, `test_edition.py`

**0.2** Everything the product already does keeps its existing constraints. The default never changes: the product never sends again when the first continuation may already have been delivered.  
*docs*

**0.3** The standard edition holds nothing these standards forbid. In the advanced edition, each capability that does such a thing is off until a person turns it on after being told what it does (K3, K4).  
*tested*: `test_advanced_arming.py`, `test_advanced_registry.py`

**0.4** Each edition has its own archive, setup program and pinned digest, under one build attestation. An installation updates within its edition. Changing edition is a deliberate reinstall (K2).  
*tested*: `test_edition_bootstrap.py`, `test_edition_installer.py`

**0.5** The standard edition never retries unknown failures or sign-in failures, shares an app server, wakes an unloaded conversation through thread/resume, uses thread/inject_items, changes a goal's state, recovers subagents, replays model, provider or permission settings, dispatches several tasks at once, or recovers an empty response. The advanced edition offers some of these as capabilities that say they depart from 0.5.  
*tested in part*: `test_recovery.py`, `test_failures.py`, `test_engine.py`, `test_control_continuation.py`, `test_compat.py`

**0.6** The deciding line is that the engine stays small, local, conservative and fail-closed. Complexity is spent on install and control.  
*docs*

**0.7** The Rust core (v0.6.25) replaces the implementation, not the behaviour. Exact-thread, fail-closed, the registry's semantics and both editions are kept (amended by the owner on 2026-10-21, 2026-10-26, 2026-10-31, 2026-11-04 and 2026-11-11).  
*planned*

## A. What it may send to Codex, and when

**A1** Only the watcher sends. Every message the watcher sends is handed on by Engine.dispatch: to core's backend, or, in the advanced edition, to the channel a capability that is on puts in its place, asked for once through the plug. The control layer, bridge, MCP server, popup and card have no send path.  
*tested*: `test_structural_invariants.py`, `test_control.py`, `test_mcp.py`, `test_tray_popup.py`, `test_notice_card.py`

**A2** There is one send channel: the official `codex queue --thread <uuid> --message <text>` (with `--remote unix://` where Codex's managed daemon runs). One function, Backend.send in codex/transport.py, starts it, as an argument list with shell=False. The --help probe is the one other `queue` process, and the App Server delete is the one other call that touches the queue (amended by the owner on 2026-11-10).  
*tested*: `test_structural_invariants.py`, `test_windows.py`

**A3** A conversation is identified by its exact canonical UUID. The product never uses --last, a title, a project, a folder or recency to identify one.  
*tested*: `test_structural_invariants.py`, `test_windows.py`, `test_mcp.py`

**A4** Each interruption carries one marker `[codex-auto-resume:<16 hex>]`, and delivery counts only when that marker is in that thread. From v0.6.11 the marker holds the first 16 of the interruption id's 64 hex digits. A record made before keeps, and is still found by, the whole id's `<64 hex>`. `downgrade-state --to 3` writes every marker back to the whole id's. The advanced edition's opt-in marker-free sending is its own capability. The recovery turn is the marker row's turn, never "the latest turn". Two markers, a marker at or before the failed turn, or a client-id mismatch is ambiguous.  
*tested*: `test_source.py`, `test_correlation.py`

**A5** The interruption is claimed durably (BEGIN IMMEDIATE, synchronous=FULL) before any process can accept the message. A crash after the claim never resends.  
*tested*: `test_engine.py`

**A6** The product never resends when delivery is uncertain. Only a proven "process never started" may be retried. A non-zero exit, unmatched receipt, timeout or exception after spawn becomes submission_unknown, is watched for 24 h and is never sent again.  
*tested*: `test_engine.py`, `test_windows.py`

**A7** A withdrawal (thread/queue/delete) that cannot be confirmed becomes submission_unknown and is never re-sent, even though Codex may still deliver it.  
*tested*: `test_engine.py`

**A8** 13 gates run in a fixed order: consent, engine_compatible, single_owner, submission_safe, identity, known_failure, schedule, chain_budget, attempt_budget, no_progress_budget, thread_available, no_newer_user_work, usage. A gate never evaluated counts as a refusal. The store re-checks consent, submission_safe, schedule and budgets inside the claim transaction.  
*tested*: `test_engine.py`

**A9** A change between the claim and the send hands the claim back unsent. Such a change is a cancel, a pause, a conversation switched off, a superseded failure, history lag, someone's queued input, our marker already there, or a lost home lock. Attempts are returned, and the claim time is kept for the caps.  
*tested*: `test_correlation.py`

**A10** Inside the dispatch lock the watcher re-checks the app process identity, the loaded state and live usage (from a reading at most 30 s old).  
*code*

**A11** The watcher sends only while the desktop app is running and the exact thread is loaded. notLoaded or unknown waits at waiting_for_loaded_thread, and nothing is queued on the off chance.  
*tested*: `test_engine.py`

**A12** The watcher never sends before the real reset time, and it re-checks live usage. The real reset is the newest one Codex reports, read when a recovery is due or when a person asks for it (Retry now). A reading that says the limit has not lifted, or cannot be told, or fails, changes nothing (amended by the owner on 2026-10-24).  
*tested*: `test_engine.py`, `test_retry_now_usage.py`

**A13** Only classified kinds are recovered: usage limit, connection failure, timeout (408/425), rate limit (429, including responseTooManyFailedAttempts carrying 429), 5xx, and stream disconnect. The structured code comes first. Message text is used only when there is no code, against a fixed phrase list.  
*tested*: `test_failures.py`, `test_plug_points.py`

**A14** These are never retried: anything unclassified, user cancellation, permission, approval, content policy, invalid request, context length, 401/403, badRequest, sandboxError, and responseTooManyFailedAttempts without a 429.  
*tested*: `test_recovery.py`, `test_failures.py`, `test_settings.py`, `test_plug_points.py`

**A15** Only desktop-app user conversations are detected. Codex's `thread_source` label is not required: a desktop conversation with no label, or with ChatGPT's handoff label, is the person's own. Subagent, archived and non-desktop threads are never detected. A thread an agent made is detected only when the person started its failed turn from the input box, which makes it theirs (clarified on 2026-10-15; amended by the owner on 2026-10-28, issue #54).  
*tested*: `test_engine.py`, `test_source.py`
<!-- A15 clarified, not changed, at the owner's word on 2026-10-15, after issue #27 (2026-10-13): the label is Codex's analytics classification, not a mark of whose a conversation is. -->

**A16** A failure is eligible only while it is the thread's latest turn and completed after arming minus the look-back (default 6 h, at most 7 days).  
*tested*: `test_engine.py`

**A17** Newer human work wins. A later turn supersedes the failure. Someone's queued input makes it wait. A turn or queued input after ours makes the watcher take ours back. A queued item the person edited becomes theirs and is not deleted.  
*tested*: `test_engine.py`, `test_recovery.py`

**A18** A history that has fallen behind its rollout blocks a new send. A missing projection table blocks as incompatible.  
*tested*: `test_engine.py`

**A19** One continuation is in flight per conversation, dispatched in sequence under one lock. There is no bulk retry. Cancel all and Rescan and reconcile act on the waiting recoveries one exact record at a time, and neither sends. (corrected to match the code on 2026-11-11)  
*tested for bulk actions; code for the in-flight gate*: `test_control_continuation.py`

**A20** Caps are engine constants, not settings. A conversation takes at most 5 claims in any 24 h, at least 15 min apart. There are at most 5 failed queue launches. A usage chain unavailable for 7 days expires, never before its reset plus a day.  
*tested*: `test_engine.py`

**A21** Budgets are settings with capped ranges: transient attempts 4 (1-20), recoveries in a row with no progress 3 (1-10), continuations per task chain 6 (1-10, never higher). A usage limit spends no attempt.  
*tested*: `test_engine.py`, `test_recovery.py`

**A22** Waits are bounded. A transient wait comes only from a preset ladder or from Custom's five waits, each picked from a closed list and never typed. A Retry-After or jitter only lengthens a wait. A rate limit's first wait is at least a minute.  
*tested*: `test_recovery.py`, `test_ladder_and_guards.py`

**A23** One failure is recovered once. The same Codex turn under a new identity is refused. A chain child inherits its counters. It is created already stopped if its parent was cancelled or out of budget, or handed over by a person who joined before the recovery turn made any progress (amended by the owner on 2026-10-22).  
*tested*: `test_store.py`, `test_recovery.py`

**A24** Attempts are given back only for exhausted records, at most 3 per task, and never for cancelled or possibly-sent ones. Giving them back sends nothing and never switches a conversation on.  
*tested*: `test_store.py`

**A25** Retry now moves the schedule and, for a recovery waiting for a usage reset, asks for one usage reading (A12). It sends nothing, skips no gate and opens no usage window (amended by the owner on 2026-11-10).  
*tested*: `test_mcp.py`, `test_store.py`

**A26** The continuation text has three sources: shipped templates, the Custom message, and the words a person added for one waiting interruption, which follow the text once. It is made only for a recoverable category and is decided before the claim. It cannot change what is recovered (amended by the owner on 2026-10-10).  
*tested*: `test_continuation.py`, `test_once_words_engine.py`
<!-- A26 amended at the owner's word, 2026-10-10: "대기 중인 메시지 중 하나를 골라서 이번 한번만 한도가 풀렸을 때 기존 재시도 메시지에 추가로 보내고 싶은 말을 보내고 싶은거야" - words for this time, added once to one waiting recovery's continuation. -->

**A27** The Custom message, a conversation's own message, and the words a person added for one waiting interruption are written only in the Dashboard. MCP update_settings refuses them and the preview tool takes no text. Each is at most 2000 characters and is sent exactly as typed. Placeholders come from a whitelist ({reason},{category},{attempt},{max_attempts},{reset_time}), and dangerous ones are refused by name. The text is re-checked on read, and text that fails the check is treated as not set (amended by the owner on 2026-10-10).  
*tested*: `test_continuation.py`, `test_mcp.py`, `test_conversation_message.py`, `test_once_words.py`
<!-- A27 amended at the owner's word, 2026-10-10: the words for this time are a Custom message in every way, kept in config/once-words.json beside the state. -->

**A28** A notification or card button does one of three things: it cancels one exact interruption (an opaque 64-hex id), stops the power action for one batch (named by that batch's opaque 16-hex id, which every batch end replaces), or opens one page from a fixed list. Anything else is ignored and logged. A button never causes a send (amended by the owner on 2026-10-03).  
*tested*: `test_notify.py`, `test_notice_card.py`, `test_cli.py`
<!-- A28 amended at the owner's word, 2026-10-03: "예, 버튼 넣기" - a stop button for one batch, named by that batch's nonce, on the power action's notice and card. -->

**A29** A switch click carries the exact interruption and conversation. A stale, finished or other-conversation click is refused and changes nothing. A switch sends nothing.  
*tested*: `test_control_continuation.py`, `test_tray_popup.py`

**A30** An engine is accepted only while `codex queue --help` still offers --thread and --message. Anything unproven is refused. There is no version pin.  
*tested*: `test_windows.py`

## B. What it reads, and how

**B1** Codex SQLite is opened read-only: mode=ro, PRAGMA query_only=ON, trusted_schema=OFF.  
*tested*: `test_source.py`

**B2** No Codex database, rollout or config file is ever opened for writing. The WAL -shm update is disclosed.  
*code*

**B3** Codex's state changes only through official interfaces: codex queue, thread/queue/delete, and the codex plugin CLI at install and uninstall.  
*code*

**B4** The App Server is a separate, short-lived stdio helper. The product sends it only initialize (plus initialized), account/rateLimits/read and thread/queue/delete. Requests from the server are refused. A wrong codexHome is refused.  
*tested*: `test_windows.py`

**B5** Only the newest database generation is read, and only if every column it reads exists. Paths stay inside the Codex home.  
*tested*: `test_source.py`

**B6** Rollout files are read only under <home>\sessions. The product reads the first line (at most 256 KiB: id and origin). For a usage limit only, it reads up to 8 MiB before the failure, in memory, and keeps only the reset time and the limit id. Only when a person presses *Rescan and reconcile*, and only for a waiting recovery whose history has not caught up, it reads that conversation's rollout file from start to end, a line at a time, up to 32 MiB, and a larger file is not read. Each of those lines is parsed in memory and dropped, and the product keeps only whether a message of the person's that carries no marker of its own follows the failed turn's end. It also lists the file names under <home>\sessions, opening none, to follow a conversation Codex split across files. For a conversation an agent made, it reads the file's last 32 MiB at most, a line at a time, and keeps only how the failed turn was started (corrected to match the code on 2026-10-22; added for A15's amendment of 2026-10-28; amended by the owner on 2026-11-10).  
*tested for the path; code for the byte caps*: `test_source.py`

**B7** Queries that return message content are bounded by instr(col, marker)>0. Other people's rows come back only as counts or booleans.  
*tested*: `test_source.py`

**B8** The product never selects title, preview or first_user_message. Labels come only from threads.name, the project or the cwd basename, are one line of at most 72 chars, and never identify a thread.  
*tested*: `test_failures.py`

**B9** The raw error is classified and dropped, and only the category continues. Progress comes from lifecycle columns, a fixed item-type list and whether a message carries our marker, and from no other content.  
*tested*: `test_failures.py`, `test_recovery.py`

**B10** From the usage response the product keeps only numeric windows, reset times and the bucket name.  
*tested*: `test_windows.py`

**B11** The product never reads auth.json, tokens, cookies, authorization headers, credential storage or process memory.  
*docs*

**B12** Loaded state comes only from the Restart Manager inventory. There is no byte-lock API and the app's writer lock is never taken. Ambiguity, PID reuse or an unavailable API reads unknown.  
*tested*: `test_windows.py`

**B13** The product has no GUI automation, input simulation, UI Automation, OCR or screen capture, and nothing reads what another window shows or drives another window. About another window it asks Windows for facts: the class and program file name of the window in front, and the class of its focus, around a card being shown, and the class and visibility of the overflow flyout for the icon's motion. To find this program's own windows, opening one that is already open lists every top-level window's class, visibility, owner and program file, keeps none of it, and messages only this program's own windows. The run outside another app's private view (F6) asks Explorer's desktop shell (ShellExecute) or WMI to start this product's own program. The popup answers screen readers about itself. The one PrintWindow is in a build-only tool. (corrected to match the code on 2026-11-11; amended by the owner on 2026-11-13)  
*tested*: `test_surface_properties.py`

**B14** The product has no web stack: no browser control, WebView, listening socket, localhost server or second runtime. The window compiles against System, System.Drawing and System.Windows.Forms only.  
*tested*: `test_surface_properties.py`

**B15** Compatibility probes read only the schema's table and column names and whether folders exist, never a row.  
*code*

**B16** Windows is asked only content-free questions. AppsUseLightTheme, TrayNotify and the notification-area icons' own settings (NotifyIconSettings) are read, never written. To find its own icon among them the product reads every entry's icon number and GUID and, for an entry that could be its own, the program path, and it keeps none of it. The power action asks four more questions. Whether this account holds SeShutdownPrivilege and which sleep states the PC offers are asked when the Dashboard shows the power action's card or turns it on, and while it is armed. How long ago the last input came (a time, never what it was, with no hook) and how many other sessions are signed in (a count, never a user name) are asked only while it is armed. To suggest a Codex home this PC's Codex uses and the watcher does not yet watch, an installed copy's Dashboard also reads the account's CODEX_HOME value (HKEY_CURRENT_USER\Environment), read-only and never written, when it shows Settings > Advanced and its suggestion switch is on. Windows' text size (TextScaleFactor, HKEY_CURRENT_USER\Software\Microsoft\Accessibility) and the administrator's policy values under Software\Policies\CodexAutoResume (HKEY_LOCAL_MACHINE and HKEY_CURRENT_USER) are read, never written (corrected to match the code on 2026-10-22; extended on 2026-10-22 for the Codex homes suggestion the owner asked for; corrected to match the code on 2026-11-11; amended by the owner on 2026-11-13)  
*tested partly*: `test_power_action_windows.py`

**B17** The layers are fixed. The engine imports no sqlite3, ctypes or subprocess and reaches Codex only through its injected adapters. The UI and MCP never import Codex's readers. The domain layer is pure standard library. Only listed modules import subprocess.  
*tested*: `test_layers.py`, `test_structural_invariants.py`

## C. Network

**C1** The standard edition has no network code at all: no file under src/ and no scripts/*.py imports a networking module. The advanced edition's network code does not run unless a person turns on the capability it belongs to (amended by the owner on 2026-11-10).  
*tested*: `test_privacy_claims.py`, `test_advanced_network_off.py`

**C2** Of the files the standard edition ships, scripts/bootstrap.ps1 is the one that reaches the network. build/ downloads the pinned Python while a release is built. What ships from build/, the install scripts and the setup program, reaches nothing. (corrected to match the code on 2026-11-11)  
*tested*: `test_privacy_claims.py`, `test_setup.py`

**C3** The product has no telemetry, analytics or crash reporting, and shipped files name no unexpected host. api.github.com is named for two addresses, both this repository's list of releases: the update check's ten newest, and the version picker's pages of thirty (amended by the owner on 2026-10-03).  
*tested*: `test_privacy_claims.py`

**C4** No network request happens on its own: there is no update polling, no schedule, nothing at start and no automatic compatibility refresh. (corrected to match the code on 2026-11-11)  
*tested*: `test_convergence.py`, `test_gui_update.py`

**C5** The update check runs only when a person presses the button. It sends one HEAD to a constant releases/latest URL and reads the version from the redirect under this exact repository, rebuilt from its integers. It also reads this repository's list of releases to find a newer pre-release, which it offers with a question and installs only on a yes. Once github.com has answered, it also refreshes the compatibility data as C7 says. The version picker (*Install another version...*) reads this repository's whole list of releases, paged, only when a person opens it and again when they confirm. It installs the version and edition they picked, a release or a pre-release, older or newer, only after that confirmation, which is the yes (amended by the owner on 2026-09-28 and 2026-10-03; corrected to match the code on 2026-10-22).  
*tested*: `test_update_check.py`, `test_convergence.py`, `test_prerelease_offer.py`, `test_version_picker.py`, `test_gui_versions.py`

**C6** The setup download uses HTTPS and at most 5 redirects. Its URL is built from constants and the manifest version, or from a version in the list of releases, rebuilt from its integers. Its host is one of three GitHub hosts. Each redirect is checked against them before it is followed, and where the .NET request cannot be made the final host is checked after the download, which is disclosed. It fetches at most the archive and its .sha256 (amended by the owner on 2026-10-03; corrected to match the code on 2026-11-11)  
*tested*: `test_convergence.py`, `test_update_check.py`, `test_version_picker.py`

**C7** Compatibility refresh runs only on request. It is one GET to a constant raw.githubusercontent.com URL with no query, at most 256 KiB. PowerShell never parses or runs the answer, and the watcher and MCP tools never start the refresh.  
*tested*: `test_compat_bootstrap.py`, `test_compat_surfaces.py`

**C8** Requests carry no product-invented identifier. GitHub sees the IP, the time and PowerShell's User-Agent, which is disclosed.  
*tested for the constant URLs; no custom header exists in bootstrap.ps1*: `test_update_check.py`

**C9** OpenAI is reached only through official Codex: a usage read when a recovery is due or when a person asks (Retry now, Rescan), reused for 30 s, identified as codex_auto_resume with the real version (amended by the owner on 2026-11-10).  
*code*

**C10** Every `codex queue` send, App Server helper and codex plugin command the product starts runs with OTEL_SDK_DISABLED, analytics off, OTel exporters none, log_user_prompt=false and chatgpt_base_url pinned. The --version and queue --help probes run with OTEL_SDK_DISABLED. (corrected to match the code on 2026-11-11)  
*tested*: `test_privacy_claims.py`, `test_windows.py`

**C11** The installer refreshes only this product's marketplace, by name.  
*code*

**C12** Translations, the panel and the window fetch nothing. The MCP manifest declares no environment or network.  
*tested*: `test_l10n.py`, `test_mcp.py`, `test_plugin.py`

**C13** Whatever the tools and commands return becomes part of the Codex conversation and goes to OpenAI, and this is disclosed.  
*docs*

## D. Privacy and the data it keeps

**D1** Nothing goes to the developer: no prompts, replies, files, ids, credentials, raw errors, titles, paths or statistics.  
*docs*

**D2** State holds ids, enums, counters and times, and its text is bounded and free of control characters. State holds no prompt, reply or error text. Notifications show the conversation title, which is disclosed. (corrected to match the code on 2026-11-11)  
*tested*: `test_store.py`, `test_engine.py`

**D3** Logs are written from a fixed message table. Untrusted values that are not hex or digits are masked. The main log keeps exception class names and no more of an error, and tracebacks go to errors.log. The state directory path and the engine version appear in the logs, which is disclosed.  
*tested*: `test_engine.py`

**D4** The journal holds closed-vocabulary codes and integer flags only. It is bounded to 5,000 entries and 90 days, and it is never read to decide anything.  
*tested*: `test_store.py`, `test_surface_properties.py`

**D5** Diagnostics are exported only on request, to a chosen path, never overwriting, and nothing sends the export. Ids become per-file aliases. Paths, the user name and e-mail addresses are redacted. A Custom message is recorded as set, never quoted.  
*tested*: `test_diagnostics.py`

**D6** A notification holds up to 2 one-line labels of at most 72 chars plus the UUID, and no error or account text. It has at most 3 lines and is XML-escaped. The card shows what the toast shows.  
*tested*: `test_notify.py`

**D7** get_status carries the compatibility summary as codes only and no install path. It does return the settings, including the Custom text and whether a codex_exe path is set (never the path), read-only, which is disclosed (amended by the owner on 2026-10-22).  
*tested*: `test_mcp.py`, `test_compat_surfaces.py`

**D8** Values that reach PowerShell travel as environment variables to constant scripts. PowerShell is run by its full System32 path.  
*tested*: `test_pwsh.py`, `test_gui_update.py`

**D9** Errors that reach a front end are static codes, and every refusal carries a code from one closed set.  
*tested*: `test_control.py`, `test_mcp.py`

**D10** Uninstall keeps settings and pending state by default. Purging is opt-in.  
*tested*: `test_installer.py`

**D11** The repository and its evidence use synthetic UUIDs and placeholder homes only, and live evidence is content-free.  
*tested*: `test_repo_hygiene.py`, `test_screenshots.py`, `test_live_evidence.py`

**D12** The language is never inferred from the IP, time zone, user name, country or keyboard layout. Only the first Windows UI language counts.  
*code*

**D13** Users are told never to paste credentials, conversations or unredacted logs into public issues.  
*docs*

## E. Failure behaviour

**E1** The product fails closed: unknown loaded state, unknown usage, an unavailable probe, a missing projection table, corrupted state or a compatibility evaluation that could not run all mean waiting or refusing, never sending.  
*tested*: `test_engine.py`, `test_compat_io.py`

**E2** The product would rather miss a resume than resume twice.  
*docs*

**E3** A corrupt, empty, symlinked or malformed state, a newer schema or an unknown record state fails closed and is never reset. Migration runs only under the watcher mutex, after a forensic copy, in one transaction.  
*tested*: `test_store.py`

**E4** While an older watcher still owns an older schema, only actions that reduce automation work.  
*tested*: `test_control_v3.py`

**E5** A malformed or oversized settings file reads as defaults. A wrong type is refused on write. A gate vector that does not decode reads UNKNOWN.  
*tested*: `test_settings.py`, `test_control.py`

**E6** A turn that never finishes and produced nothing is outcome_unverified, never a success. One that produced progress before Codex closed or the PC restarted is recovered, as a failed one with progress is. Unreadable history never becomes "no progress".  
*tested*: `test_outcomes.py`, `test_cut_off_turns.py`

**E7** Uninstall stops before removing anything, registrations included, unless the watcher is definitely not running. A process whose path cannot be read is skipped, never killed.  
*tested*: `test_cli.py`

**E8** Stopping the watcher is always a request. An upgrade waits up to a minute and never kills. Force ends this plugin's own MCP launchers (by path), its own short-lived Codex helpers, and a child the product itself started that overran its bound or did not bring the watcher up. (corrected to match the code on 2026-11-11)  
*tested*: `test_control.py`, `test_installer.py`, `test_upgrade_handover.py`

**E9** Bootstrap runs nothing from the archive until every check passes, and any failure deletes the download. For an older version the state is converted only after the archive passed every check, while nothing from the archive has run yet (amended by the owner on 2026-10-03).  
*tested*: `test_convergence.py`, `test_version_picker.py`

**E10** If the download fails, the skill stops. It uses no other source and no hand-assembled install.  
*model*

**E11** Notifications, the tray and the failure-seen file never decide or delay a recovery. The card falls back to the toast when unsure. Turning notifications off changes nothing.  
*tested*: `test_notice_card.py`

**E12** A mutex, stop event or wake event planted by a lower-integrity process is refused. Taking over a running watcher's mutex is not covered, which is disclosed.  
*tested*: `test_named_objects.py`

**E13** An update check that could not ask never reads as "up to date". The check has four answers and four exit codes.  
*tested*: `test_gui_update.py`

**E14** A transient adapter, store or probe failure at logon defers the tick and never ends the watcher.  
*tested*: `test_cli.py`

## F. Footprint on the machine

**F1** The product needs no administrator rights and installs per user only. It adds no service, no scheduled task and nothing machine-wide.  
*tested*: `test_installer.py`

**F2** Every registry write is under HKCU. The writes are the Run value (only if chosen, removed only while it is ours), Software\Classes\codex-auto-resume, Software\Classes\AppUserModelId\CodexAutoResume.Watcher, and the one Software\Microsoft\Windows\CurrentVersion\Uninstall key that lists the installation in Add or remove programs. That key is CodexAutoResume, or CodexAutoResumeAdvanced for the advanced edition, never both. It is written only where the installer has kept an uninstaller for it to name, and replaced or removed only while it names this installation (amended by the owner on 2026-10-16).  
*tested per key; code that no other key is written*: `test_cli.py`, `test_notify.py`, `test_plugin.py`, `test_add_remove.py`

**F3** The product's own files are config/ and logs/ with a provenance marker, program files in the home (%USERPROFILE%\.codex-auto-resume, never AppData), a Start Menu shortcut, a Desktop shortcut only where a person asks for one, and diagnostics only where asked. The one place outside the installation directory is %LOCALAPPDATA%\codex-auto-resume\homes\: empty lock files, one per watched Codex home, named by a hash of its path (and one by the folder's identity). Uninstall -Purge removes them, except those another installation holds (amended by the owner on 2026-11-05 and 2026-11-13).  
*tested*: `test_plugin.py`

**F4** Paths are confined: an owned directory that is a link or resolves outside the home (NTFS junctions included) is refused.  
*tested*: `test_cli.py`, `test_installer_ownership.py`

**F5** Nothing is destroyed without proven ownership. Per-user singletons are replaced by name and the marketplace is repointed without that proof, and both are disclosed.  
*tested*: `test_installer_ownership.py`

**F6** The processes the product starts are its own (the watcher, the settings window and the bundled Python behind them); codex app-server --stdio, codex queue, and the --version and queue --help probes; the codex plugin commands when it installs and uninstalls; and PowerShell by its full path with constant scripts. The Python code starts each as an argument list, and the C# programs give each one quoted command line. On a person's click the product also starts explorer.exe to show the logs folder, hands the guide link to the default browser, and starts a copy of its own setup program from a temporary folder to remove the installation. Inside another app's private view (the Codex app, Claude desktop), the Dashboard opens again through Explorer's ShellExecute, or through WMI's Win32_Process.Create where Explorer does not answer, and the installer the setup programs run and bootstrap's repair branch run again through WMI's Win32_Process.Create (since v0.6.17); what runs again is this product's own program (corrected to match the code on 2026-10-22; corrected to match the code on 2026-11-11; amended by the owner on 2026-11-13)  
*tested*: `test_structural_invariants.py`, `test_pwsh.py`

**F7** One instance runs, held by a per-user, per-state-directory mutex, a stop event and a per-Codex-home lock. A second watcher exits, the send gate requires the lock, and a second installation is refused.  
*tested*: `test_engine.py`, `test_surface_properties.py`, `test_plugin.py`

**F8** The product has no resident helpers: one watcher process hosts the icon, popup and card, with no tray process, supervisor, service, web UI or second engine. Codex helpers are short-lived.  
*tested partly*: `test_tray_popup.py`

**F9** An upgrade or repair never switches recovery back on and never re-adds a removed sign-in entry (--keep-state). An older plugin never replaces a newer install without -Force.  
*tested*: `test_installer.py`, `test_plugin.py`, `test_update_check.py`

**F10** The sign-in launcher starts this installation, this product's marketplace copy or the recorded copy. When it finds none of them, it starts nothing.  
*tested*: `test_plugin.py`, `test_upgrade_handover.py`

**F11** The skill runs bootstrap.ps1 only by its absolute path, after checking the manifest names this product.  
*model*

**F12** An install is held by a named installer lock (including the bootstrap repair branch), a move-aside journal before the first move, rollback on failure, and the root claimed before the first write. State directories are never replaced.  
*tested*: `test_installer.py`, `test_convergence.py`, `test_installer_ownership.py`

**F13** The product uses the standard library only, on the bundled Python. A system Python never sets up a second installation.  
*tested partly*: `test_installer.py`, `test_layers.py`

**F14** The standard edition does not offer starting the watcher when Codex starts. A watcher started from inside Codex ends when Codex closes (measured on Codex 26.915), so the setting exists and is not offered. The advanced edition's start-with-Codex does it outside Codex's job, through WMI.  
*tested*: `test_start_with_codex.py`, `test_settings.py`

**F15** The power action is the watcher's own call of SetSuspendState or ExitWindowsEx(EWX_POWEROFF) with no force flag, after enabling SeShutdownPrivilege on its own token. It offers no action to an account that does not hold that privilege. It starts no process, task or service, needs no administrator, changes no Windows setting and never shuts down while another person is signed in.  
*tested*: `test_power_action_windows.py`

## G. The Compatibility Registry's authority

**G1** Data can only restrict. A failed local check always wins (INCOMPATIBLE, or FAILED_HERE where the data vouched for the version), and both block every send.  
*tested*: `test_compat.py`, `test_compat_io.py`

**G2** Data may raise only a local PASS, only for an exact version, only to CHECKED or VERIFIED. That changes the word, not what is sent. Ranges only restrict.  
*tested*: `test_compat.py`

**G3** The gate sends on verified, checked or structurally_compatible. failed_here and incompatible block. Anything else is UNKNOWN, which sends nothing, and a failing evaluation fails closed.  
*tested*: `test_compat_io.py`

**G4** VERIFIED needs a cited evidence file recorded on that exact version from a real recovery that exercised the capability. CHECKED also needs evidence. URL citations are not accepted. The build refuses data the validator would refuse.  
*tested*: `test_compat.py`

**G5** Every write of compat-cache.json goes through the validator (controlcli compat-import). The validator refuses the whole document for an unknown format, malformed content, over 256 KiB (checked before parsing), a duplicate key, a non-finite number, excessive depth, a trust-granting range, requires_signature, rollback, a date more than 1 day ahead, or a newer product. A refusal leaves the cache untouched.  
*tested*: `test_compat.py`, `test_compat_io.py`

**G6** The cache is validated on every read. Expired or future-dated data keeps its restrictions and loses its trust. No clock lifts a restriction. A bad cache is ignored, never deleted.  
*tested*: `test_compat.py`, `test_compat_io.py`

**G7** The watcher's report is bound to the executable (path digest, size, mtime). Readers refuse one that is damaged, stale or about a changed binary.  
*tested*: `test_compat_io.py`

**G8** Everything shown to a person or model is a closed-list code, never document text. MCP reads codes only and cannot refresh or import.  
*tested*: `test_compat.py`, `test_compat_surfaces.py`

**G9** Every installed release takes the newest data on main whole. Behaviour tests read a frozen copy.  
*tested*: `frozen_registry.py`

**G10** With the bundled data, the gate decides what it decided before the registry existed.  
*tested*: `test_compat_characterization.py`

**G11** The data is unsigned. The signature slot is reserved and requires_signature is refused. The bounded worst case is recovery stopping for one build.  
*docs for the residual risk; tested for the refusal*: `test_compat.py`, `test_compat_io.py`

**G12** Capabilities without checks (empty-response, notLoaded, Goal, subagent) stay tier 'unsupported'.  
*tested*: `test_compat.py`

**G13** Reports from others are shown apart, never raise a version to Verified or Checked, and change nothing the product does. The standard edition sends nothing for them.  
*tested*: `test_community_report.py`, `test_compat.py`, `test_compat_surfaces.py`

## H. User control

**H1** The defaults are recovery on, every recoverable category ticked, notifications, card and icon on, the Standard message in the interface language, and sign-in start unless -NoStartup. A fresh state starts disabled until setup enables it.  
*tested*: `test_settings.py`

**H2** Settings are policy only. No setting can retry unknown failures, resolve by title, resend an uncertain submission, force a send, skip revalidation or move an engine constant. Writes are strict: a bad value is refused, never clamped.  
*tested*: `test_engine.py`, `test_settings.py`

**H3** Three surfaces write one settings file through one validator, and only the Dashboard writes the Custom text. update_settings does not offer the engine path, look-back, tray icon, Reduce motion, card, Design or Custom text, and refuses them even if the schema is ignored.  
*tested*: `test_mcp.py`

**H4** Global pause is an immediate kill switch that keeps pending records. It withdraws a queued continuation. A confirmed withdrawal returns the record to waiting with its attempt back. A pause over an uncertain submission ends it final.  
*tested*: `test_engine.py`, `test_pause_unknown.py`

**H5** Switching a conversation off cancels what waits there, and a cancel is final. Re-enabling does not revive it, and budget restore refuses it.  
*tested*: `test_engine.py`, `test_store.py`

**H6** Cancel always works, covers the whole chain, withdraws a still-queued item and never stops a running turn.  
*tested*: `test_store.py`

**H7** Doing nothing resumes a recovery. A setting can hold a recovery for the person in these cases: a conversation set to Ask me first or Only notify me; a project that Projects that may resume does not allow, or, under either list, one whose project cannot be read; a task the task-changed guard finds changed, set to Hold it for me; a conversation past the context-cost guard's Hold above; and what fell due during a sleep longer than Ask me after a sleep longer than. While Observe only is on, nothing is sent. Don't resume / Don't retry only cancels.  
*tested*: `test_notify.py`, `test_postpone_and_tiers.py`, `test_observe_and_admission.py`, `test_ladder_and_guards.py`, `test_power.py`

**H8** MCP tools that add automation or cannot be undone carry destructiveHint (resume, enable_conversation, update_settings, restore_default_settings, cancel_recovery, reset_recovery_budget, start_watcher, release_hold, clear_recovery_history). pause, conversation-off, retry_now, postpone and turn_off_power_action are unmarked. This is a request, not a lock.  
*tested*: `test_mcp.py`, `test_mcp_v3.py`, `test_postpone_and_tiers.py`

**H9** If a marked tool is declined, the model does not run the matching command, never "forces" a resume, and does not work around a missing safety setting.  
*model*

**H10** Clear history only hides rows. Hidden rows count for every cap and duplicate check, and anything that may still change is never hidden.  
*tested*: `test_store.py`

**H11** Switch commands accept only real JSON booleans, so the string "false" never turns automation or the Run value on.  
*tested*: `test_control.py`

**H12** Each recoverable category has its own switch, and a switched-off category is never recorded.  
*tested*: `test_engine.py`

**H13** An explicit interface-language choice wins over Windows and CODEX_AUTO_RESUME_LANG and survives restarts, repairs and updates. Motion stops under Reduce motion, Windows' animation setting, High Contrast, battery saver, a locked session and a closed overflow flyout (amended by the owner on 2026-10-22).  
*tested*: `test_locale.py`, `test_tray_icon_motion.py`

**H14** The power action after usage-limit recoveries is off by default and armed only in the Dashboard, once or always. MCP, the icon and a notice may only turn it off or stop it for its batch, and a stop is honoured before anything else is looked at. It acts only when every usage-limit recovery of its batch has ended as the person chose, no recovery is open or followed, Codex's history has caught up, no Codex turn runs, no input is queued, nobody has used the PC for two minutes and a notice's countdown has run out. Anything it cannot read means it does nothing, and it sends nothing.  
*tested*: `test_power_action.py`, `test_power_action_watcher.py`, `test_power_action_control.py`, `test_cli.py`

## I. Release and supply chain

**I1** Releases are built by Actions from the tagged commit, after the full suite. The tag equals the manifest's version. A pre-release tag (-alpha or -beta, then numbered: -alpha.2, -beta.2 and so on) publishes a GitHub pre-release that is never the latest release.  
*tested*: `test_workflow_privilege.py`, `test_plugin.py`, `test_version_rule.py`

**I2** Two jobs are split by privilege. build has contents: read, does not persist its token, and runs repo code. publish runs no repo code and runs only on a tag push. A dispatch is a dry run. No expression is spliced into a run script.  
*tested*: `test_workflow_privilege.py`, `test_convergence.py`

**I3** Every Action is pinned to a full SHA, and Dependabot proposes but never auto-merges.  
*tested*: `test_workflow_pins.py`

**I4** A published version is never replaced. This is the workflow's rule, not GitHub immutability, which is disclosed.  
*tested*: `test_convergence.py`

**I5** Each released version's digest is pinned in scripts/release.json on main from the published file.  
*tested*: `test_convergence.py`

**I6** Bootstrap checks the SHA-256 against the pin, or against the sidecar where there is no pin, and says which. An unpinned -ArchivePath says "NOT checked". Before anything runs, it checks that the archive is this product at this version with no escaping entry. It never announces an unverified archive as verified.  
*tested*: `test_convergence.py`

**I7** Every archive from v0.5.4 on has a build provenance attestation, and users are told how to verify it. The product itself never checks it.  
*code*

**I8** Executables are reproducible (normalised PE timestamp and MVID, built twice with a refusal if they differ). The archive is deterministic (listed files, sorted, fixed timestamps; build/, tests/, config/, logs/ and state excluded).  
*tested*: `test_reproducible.py`, `test_surface_properties.py`

**I9** Archive entries are checked in build, and the checksum again in publish. The required-entry list equals what installed bootstraps need.  
*tested*: `test_convergence.py`, `test_installer.py`

**I10** The bundled Python is pinned by version and SHA-256.  
*tested for the version; code for the SHA-256*: `test_python_support.py`

**I11** The repository manifest declares only skills. The MCP server is added at build time beside its runtime.  
*tested*: `test_plugin.py`

**I12** Updates never go to an older version without -Force, go only to a version resolved under this exact repository, and install with --keep-state. A pre-release the update check offers is installed only when the person says yes to that offer, and the check never offers one older than what is installed. A version a person picks by name with *Install another version...* and confirms, a pre-release too, older or newer, follows the first sentence: older only with -Force, the confirmation being the yes. A pre-release is checked against its published .sha256 (amended by the owner on 2026-09-28 and 2026-10-03).  
*tested*: `test_update_check.py`, `test_prerelease_offer.py`

**I13** Nothing is Authenticode-signed, which is disclosed. Users are never asked to disable SmartScreen or Smart App Control.  
*docs*

**I14** A person runs the live acceptance before each release, and a release needs both halves.  
*docs; not met for every release*

**I15** Safety scans read the whole package through one scanner, imports point down or sideways, and module size ceilings only shrink.  
*tested*: `srcscan.py`, `test_layers.py`, `test_sizes.py`

**I16** English text changes reach every catalog or are marked reviewed. The Korean docs claim nothing the English do not. Every release keeps its changelog section.  
*tested*: `test_korean.py`, `test_privacy_claims.py`

**I17** A user-visible fix ships with its regression test, and a safety change with a test that fails without it. The repository's history is not rewritten. It was rewritten once, on 2026-09-27, to remove personal data from every commit.  
*docs*

## J. Presentation rules that are promises

**J1** Evidence levels are claimed only as earned. They form a closed set, every cited test exists, no row reads REAL CODEX VISUALLY TESTED, and PUBLISHED appears only where the published bytes were driven again.  
*tested for form only; the truth and the PUBLISHED rule are docs*: `test_feature_matrix.py`

**J2** Screenshots come from a generator and synthetic data, are never edited by hand, are not evidence of a recovery, and are regenerated when their inputs change.  
*tested*: `test_screenshots.py`

**J3** No network claim stands without a qualifier. PRIVACY names GitHub and its third parties. The README privacy row admits the download.  
*tested*: `test_privacy_claims.py`

**J4** The roadmap is a direction, not a promise. Limitations are stated up front: the conversation has to be loaded, and the real-world evidence is one run.  
*docs*

**J5** In live acceptance an empty directory is not a pass, a usage limit is never faked and state is never edited, every click is a person's, and the validator checks shape, not truth.  
*tested for shape only*: `test_live_evidence.py`

**J6** Approval prompts are never claimed.  
*docs*

**J7** States are never overstated. A public status is a pure function of the record, never of a setting. failed is final, never "retrying". Overlays apply only to unsent records. unknown never reads as running. outcome_unverified is not a success. "recovered" is used only when our own turn produced progress.  
*tested; the SKILL.md parts are model*: `test_labels_v3.py`, `test_outcomes.py`, `test_control.py`, `test_engine.py`

**J8** Statistics count one final outcome per record, include hidden rows, and show no success rate below five outcomes.  
*tested*: `test_store.py`

**J9** An uncertain submission is reported as uncertain, each notification is raised once, and a record born stopped is announced as stopped.  
*tested*: `test_engine.py`, `test_notice_card.py`

**J10** The countdown only means the watcher looks again. Retry now and budget restore replies keep the "every check still applies" caveat.  
*tested*: `test_tray_popup.py`, `test_control.py`, `test_mcp.py`

**J11** The model reports only what the command printed, never states a digest itself, and says "removed completely" only after all four steps.  
*model*

**J12** No colour appears without a word. Contrast is 7:1 for text, 4.5:1 for secondary text and accent, and 3:1 for the focus ring.  
*tested for contrast; docs for the rest*: `test_brand.py`, `test_focus_rings.py`

**J13** The compatibility words verified, checked and compatible send alike. Failed here and incompatible block. Unknown is never shown as compatible. Every surface says the gate's word.  
*tested*: `test_compat_surfaces.py`

**J14** The icon stays red until the failure is seen. It goes red only for a certain, unhidden, unseen failure after which nothing started: a failed recovery, one whose attempts ran out, or one handed over to the person. The seen time only moves forward. A sending whose arrival or outcome cannot be confirmed asks for attention instead (amended by the owner on 2026-10-29).
*tested*: `test_failure_seen.py`

## K. The advanced edition's own rules

**K1** The standard edition's archive and setup program hold no advanced code. The archive is built from trees that do not name advanced/. build/edition_audit.py proves it from the two archives' and the two setup programs' bytes in every release build, before anything is kept. No advanced path, file, name or marker is in any entry, a text file, a binary or a zip inside the zip. The standard archive built again from `git archive` with advanced/ deleted is the same file. Every standard entry is in the advanced archive unchanged, with two differences: the settings window, which each edition builds for itself, and the manifest's display name. The publish job checks the listings again.  
*tested*: `build/edition_audit.py`, `test_edition_audit.py`, `test_edition_build.py`, `test_edition.py`

**K2** Updates stay within an edition. An update, and a pre-release the update check offers, fetch the installed edition's archive and check it against the digest the installed copy pins for that edition and version where it has one, and otherwise against the .sha256 published beside it (today every pre-release and every advanced archive). A bootstrap or installer that meets the other edition refuses before anything moves unless the change was asked for and confirmed, and says it first. A change of edition is a reinstall that keeps settings and pending recoveries and starts every advanced capability off. Installing the same edition again over the state an uninstall kept is not a change of edition: like an update, it keeps what is on, what is kept on and every choice. After an uninstall that kept the data, the same edition installed again keeps the advanced edition's choices. Two events turn every capability off: entering the advanced edition from the standard edition, and installing it over advanced state that no uninstall of the advanced edition left (amended by the owner on 2026-10-18).  
*tested*: `test_edition_bootstrap.py`, `test_edition_installer.py`, `test_prerelease_offer.py`
<!-- K2 amended at the owner's word, 2026-10-18: "같은 판 재설치는 그대로 유지" -->

**K3** Arming happens only in the Dashboard. Arming.arm accepts the Dashboard as its actor and refuses every other. It takes one capability at a time, or one together with the capabilities it requires that are not on, in the same confirmation, with every statement involved shown and each confirmed as a single capability is, and a policy on any of them refuses the whole. It needs the statement revision, the generation, the warnings and, for on, the Codex version the Dashboard showed, each still holding. Turning a required capability off turns off first what requires it, and a capability whose requirement is not on is off. Every other surface (MCP, the icon, a card) may only turn capabilities off. No MCP tool arms, whatever a client sends, and the one-shot bridge never reaches the plug. A capability that needs another turns it on in the same confirmation, and turning the needed one off turns off what needs it, named first (amended by the owner on 2026-10-15).  
*tested*: `test_advanced_arming.py`, `test_advanced_surfaces.py`
<!-- K3 amended at the owner's word, 2026-10-15: "다른 기능도 같이 켜져야 하거나 켜지게 하는 경우 있으면 둘 다 켜지게" -->

**K4** A capability is off by default, and it is advanced because it departs. Every capability starts off, entering the edition turns every one off, and a watched one never promotes itself. departs_from is never empty, and every id in it is a standard the standard edition keeps (0.1-0.7, A-J), so a capability that keeps every standard belongs in the standard edition.  
*tested*: `test_advanced_arming.py`, `test_advanced_registry.py`

**K5** Pause and consent precede every send. While paused no capability sends to Codex or starts Codex; answering what a person asks or directly tells it is not a send. Core puts a send to the plug only after the consent gate. A conversation switched off or a cancelled record is never put to it. A pause that commits after the pre-send look stops a route or channel at the launch guard. A pause stops start-with-Codex before any WMI create and a compatibility report before it asks GitHub anything. Every gate, the durable claim and the pre-send look stay core's (amended by the owner on 2026-11-10).  
*tested*: `test_plug_points.py`, `test_paused_residents.py`, `test_advanced_start_with_codex.py`, `test_advanced_marker_free.py`, `test_advanced_goal.py`, `test_advanced_report.py`

**K6** A failed measurement is a warning the person confirms, and only policy keys refuse. A measurement a route rests on that failed or has no pass for the Codex in force, a grade of FAILED_HERE, INCOMPATIBLE or UNKNOWN, or no Codex version known is shown in the statement and confirmed by arming, never a refusal. What refuses is ForbidAdvanced, AllowedCapabilities and ForceShadow (for on) under Software\Policies\CodexAutoResume, HKLM and HKCU, read and never written. Together they read as the stricter, and as the strictest where unreadable (the owner, 2026-09-26, replacing decision C7).  
*tested*: `test_advanced_arming.py`, `test_advanced_goal.py`, `test_advanced_marker_free.py`

**K7** Tripwires switch a capability off, and re-arming is always possible. Five events turn one off: a new statement revision; a warning the person did not confirm that says what it stands on went wrong (failed here, a local check failed, incompatible, a measurement failed); one of its hooks raising; a send it paid for gone submission_unknown; and, for one that is on, a new Codex version. Whatever turned it off, the Dashboard can turn it on again with the statement as it then reads. A capability kept on (K8) is not turned off by these five. A resent continuation found twice turns off what sent it again: the once-more capability, or Keep on's Send again (amended by the owner on 2026-10-03).  
*tested*: `test_advanced_arming.py`, `test_advanced_goal.py`, `test_advanced_marker_free.py`, `test_advanced_keep_on.py`, `test_advanced_once_more.py`

**K8** Keep on is set per capability and is off by default. It is set only in the Dashboard, for a capability that is on or watched, after its warning. Send again is set only with it, after its own warning. Kept on, K7's five are shown and do not turn the capability off: a new revision, an unconfirmed warning and a new Codex version are noted; a hook that raises costs that one record; a paid send gone submission_unknown is held as core holds one, or with Send again is sent once more under the once-more rules. A Codex version or a grade that cannot be read still holds it back (E1). Each is noted once, the most serious kept, until the person confirms again. The person's off, from any surface, always works and clears Keep on. The ceilings stay. ForbidAdvanced, AllowedCapabilities and ForceShadow read Keep on down first, and Send again applies only where AllowedCapabilities also admits the once-more capability (the owner, 2026-10-03).  
*tested*: `test_advanced_keep_on.py`
