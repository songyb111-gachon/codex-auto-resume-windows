# Why this project stays small

There is a larger, more ambitious project in this space:
[`sybxxx/codex-auto-retry`](https://github.com/sybxxx/codex-auto-retry). It is worth reading.
Several ideas here were shaped by studying it.

Reviewed again for v0.5.0 against its current state: `d25fda6`, release **v0.7.9**, last pushed
2026-09-02 — unchanged since the previous review, so nothing new arrived to reconsider. What did
change is this project: it now has an MCP server and a settings window, and two entries below
moved from *rejected* to *adapted* because of it. Saying so is the point of keeping this file.

Not re-reviewed for v0.5.2: that release changed how the product is installed and what it
looks like, and nothing in it came from reading another project. Saying that is cheaper than
implying a review that did not happen.

The initial v0.6.0 implementation preceded the comparison update recorded below.
What changed is this project: the Start Menu window became a Dashboard and the watcher grew a
notification-area icon, which moves two more entries below — a tray icon out of *rejected*, a
live countdown out of *deferred*.

Reviewed again for v0.6.0 on 2026-09-12, against `sybxxx/codex-auto-retry` **v0.7.11**,
published that morning. Its scope has moved since the v0.5.0 review and this file has been
corrected for it: the list of failures its watchdog says it retries is network failures,
timeouts, rate limits, HTTP 5xx, one structured upstream wrapper, interrupted streams,
completions with no final model reply, and temporarily unavailable authentication services -
and a usage limit is not in it. Its goal handling says plainly that a usage-limited goal is
never turned into a continuation. Waiting out a usage limit and continuing the exact task is
therefore the thing this project does that the larger one does not say it does, which is the
opposite of the shape this file assumed a release ago. It also now recovers empty responses,
and restores an unloaded *parent* thread - with its own persisted settings rather than current
defaults - inside goal-mode subagent chains.

Two entries below moved because of that re-read, and the rest of this file stands.

Checked again for v0.6.3 on 2026-09-14, and narrowly. `sybxxx/codex-auto-retry`'s releases
page still lists **v0.7.11** as its newest release, so it has published nothing new to
reconsider; the rest of that repository was not re-read, and the table of other projects below
was not re-surveyed for v0.6.3. Two READMEs were read that day for the ideas credited to them
further down - `saaranshM/unsnooze` and `boyso/codex-reset` - and nothing else. What changed is
this project: v0.6.3 added a per-task Auto-resume check box, a list of the safety checks behind
each wait, a Cancel all with no retry-all beside it, and a Custom continuation message, which
moves one entry out of *not exposed*. The deferred and rejected entries were re-read against
this project's own reasons, and all of them stand.

From v0.6.11 the product comes in two editions, built from one repository and released together.
The **standard** edition is the one this file has always described, and every *this project* below
means it unless a row says otherwise. The **advanced** edition adds capabilities the standard one
refuses, each off until a person turns it on; *Rejected* says, row by row, which exist today and
which both editions refuse.

## Others in the same space

Re-surveyed on 2026-09-12: every project below was checked against its repository that day, and
each line says what that project says about itself. None of them changed what this project
builds. They are here because a reader deciding between them deserves an accurate map, and
because two of them answer the same need in a way this project has ruled out, which is worth
being explicit about rather than quiet about.

| Project | What it is | How it differs from this one |
| --- | --- | --- |
| [`sybxxx/codex-auto-retry`](https://github.com/sybxxx/codex-auto-retry) | A Go watchdog for Codex on Windows with a tray controller and an embedded management panel (v0.7.11) | Broader recovery - unknown provider failures on their own budget, empty responses, goal chains, and an opt-in shared app-server that can restore an unloaded parent thread. Its stated retry list does not include a usage limit. Compared feature by feature below |
| [`saaranshM/unsnooze`](https://github.com/saaranshM/unsnooze) | A cross-platform resumer for Claude Code, Codex CLI, Grok, Qwen, Kimi, OpenCode and Antigravity across tmux, Zellij and VS Code | Far more agents and three platforms, and it reads `~/.codex/sessions` so it covers the desktop app's session files too. It resumes by **injecting keystrokes into a live terminal pane**, which it says plainly; this project does not simulate input anywhere, and resumes a conversation through Codex's own queue rather than a terminal |
| [`banana2556/codex-never-give-up`](https://github.com/banana2556/codex-never-give-up) | Auto-retry for the Codex desktop app on Windows, on the app-server IPC stream | Complementary rather than competing: it retries capacity, writer-conflict and shared-task errors and **deliberately does not retry a usage limit**, which is this project's main case. It works by injecting a hook into the app, with a DevTools console for diagnostics; this project adds no code to Codex |
| [`Matrtex/codex-auto-retry-plugin`](https://github.com/Matrtex/codex-auto-retry-plugin) | A Python Codex plugin that retries high-demand, 429, 5xx and transient stream or network errors | Similar failure classes; a plugin rather than a background watcher, so it acts while Codex is running rather than waiting out a reset after you close the app |
| [`ravhello/claude-codex-queue`](https://github.com/ravhello/claude-codex-queue) | A queue that continues Claude Code sessions and Codex App tasks after usage limits, preserving prompt order | Covers Claude Code as well, and is a queue rather than a failure classifier: it decides *when* to run queued work, where this decides *whether* a specific failure may be resumed at all |
| [`StylesDevelopments/agent-autoresume`](https://github.com/StylesDevelopments/agent-autoresume) | Auto-resume for Claude Code and Codex across usage-limit resets, with iTerm2 and tmux watchers | macOS and Linux, and terminal-shaped: it watches and drives a terminal session. This is Windows-only and watches the desktop app's own state |
| [`qxd-ljy/codex-goal-auto-retry-build`](https://github.com/qxd-ljy/codex-goal-auto-retry-build) | A Rust patch to Codex's own Goal auto-continuation, with reproducible source validation | It changes Codex; this does not, in either edition. The standard edition never reads or sets goal state; the advanced edition's goal continuation, off until a person turns it on, sets an existing goal that a usage limit paused back to active through Codex's own app server |
| [`tidingman/codex-retry-watcher`](https://github.com/tidingman/codex-retry-watcher) | A macOS menu-bar app that presses Codex Desktop's Retry button when the model is at capacity | Other platform, and the method this project rules out: it clicks the button for you |
| [`Justin1491/codex-dashboard`](https://github.com/Justin1491/codex-dashboard) | A dashboard for understanding Codex usage and resets | Shows usage; recovers nothing |
| [`terryso/claude-auto-resume`](https://github.com/terryso/claude-auto-resume) | The most-starred tool in this space (820 stars), resuming Claude CLI tasks when limits lift | Claude only, not Codex. Listed because it is where most people in this space have ended up, and because its one-line description is a lesson in being findable |

Different architecture is not worse architecture. Retrying an unknown provider failure, owning a
shared app-server so an unloaded thread can be woken, or typing into a terminal pane, each buys
real capability this project does not have; each is the wrong trade *here* because this
project's promise is narrower. If what you want is maximum recovery, or an agent other than
Codex, or a platform other than Windows, one of the others will suit you better.

One thing several of them still do better: they are easier to find. On 2026-09-12 a plain search
for the sentence this product exists to answer - automatically resume a Codex task after a usage
limit resets, on Windows - returned Codex's own issues and two unrelated tools, and not this
repository. That is a fact about this repository, not about theirs.

No code was copied, then or now. Everything here was written against this project's own
architecture, from its own reading of Codex's local state.

## The two goals

| | `codex-auto-retry` | this project |
| --- | --- | --- |
| Goal | maximum recovery capability | minimum necessary complexity for safe recovery |
| Unknown failure | retried, on its own budget | never retried |
| Authentication failure | retried, with a lower limit | never retried; a person is needed |
| Classification | message and wrapper matching | structured `codexErrorInfo`, then HTTP status |
| Unloaded threads | woken through a shared app-server | left alone until you open them |
| Long-lived processes | supervisor, worker, optional app-server, MCP server | one watcher, plus an MCP server while Codex runs and one control process while the window is open |
| Interface | tray icon, settings window, Codex panel | Start Menu Dashboard (Overview, Pending, History, Statistics, Diagnostics, Settings), notification-area icon with a popup, Codex panel, notifications with Don't resume and Open Dashboard; sixteen interface languages |

Neither column is a criticism. Retrying an unknown failure is a reasonable choice for a tool whose
goal is to recover as much as possible. It is the wrong choice for this one, whose promise is
narrower and, because of that, easier to trust: **it acts only on failures it can name.**
The right-hand column is the standard edition. The advanced edition moves some of its answers
toward the left, one capability at a time and only for a person who turns each on; the row-by-row
account is under *Rejected*.

## Feature by feature

### Adopted — taken as an idea, built here from scratch

| Idea | How it exists here |
| --- | --- |
| A **named failure taxonomy** instead of a "did it fail" boolean | Built from Codex's structured `codexErrorInfo` variants and HTTP status, not from message text |
| A **retry budget** so a chain cannot run forever | `max_recovery_attempts`, user-configurable, default 4 |
| A **no-progress limit**, separate from the retry budget | `max_no_progress`, default 3; carried across interruptions on the same thread |
| **Per-thread recovery state**, so one stuck thread cannot block another | Per-thread enable flag and per-interruption records in SQLite |
| **Progress correlation** — a later unrelated success must not mark a retry as recovered | Delivery is proven by this record's own unique marker in that exact thread |
| **Configurable wait strategy** | Three named presets rather than raw ladders, so no setting can produce a zero or unbounded delay |
| **Restart an exhausted task with a fresh budget** | `reset_recovery_budget`, which restores the budget and sends nothing |
| **Retry a pending task now** | `retry_now`, which moves the schedule and nothing else; every gate still runs |
| **A live countdown per pending recovery** | The Dashboard's Pending page counts down to each record's next check, on the window's own timer (`Dashboard.cs:UpdateCountdowns`); the notification-area tooltip carries the same countdown |
| **A persistent pause switch** | The existing global kill switch, reused rather than duplicated |
| **State writes that survive a sharing violation** | Atomic replace from a uniquely named temporary; a failed write raises rather than corrupting |
| **A self-contained Windows ZIP with a double-click installer**, no runtime prerequisite | The release carries its own Python; no administrator rights, no network at install time |

### Adapted — the same need, answered differently

| Their approach | Here |
| --- | --- |
| **An embedded Codex management panel** | Adopted in v0.5 as a settings panel over MCP. It shows state and changes settings; it cannot submit a continuation, and the watcher runs whether or not it is open. Previously rejected — the reason given was that it would replace something a user could do in words. That was true of a panel that only *displayed*; it stopped being true once there were sixteen settings to find. |
| **A graphical settings window** | Adopted in v0.5 as a standalone Start Menu window, for a different reason than theirs: settings must be reachable when Codex is closed and nothing else is running. |
| **A tray icon and a supervisor process** | The icon was adopted in v0.6.0, as a thread of the watcher itself (`runtime/app.py:App._start_tray`) rather than a second process, so it cannot show a watcher that is not running. Its menu opens the window, pauses recovery and stops the watcher; `show_tray` turns it off. Since v0.6.3 a single click opens a small popup beside it - what is waiting, when the watcher next looks, a switch per task, pause, and Open Dashboard - and a double click still opens the Dashboard. The supervisor is still rejected: another long-lived process to make one visible |
| **An MCP server** | Adopted, deliberately narrow: typed configuration and safe control only. No tool detects, schedules, reserves or sends. |
| **Notification of a retry limit being reached** | One of four lifecycle notifications, each with its own switch |
| **Empty-input continuation, so no user bubble appears** | Not possible without their app-server route. A continuation message is sent, and the README says so plainly rather than implying the conversation is untouched |
| **A fallback retry text the user can edit** | Adapted in v0.6.3 as the **Custom** continuation message, under constraints that answer the reason it was not exposed before - a user-authored instruction sent automatically into a conversation is a much larger surface than it looks. It is written only in the Dashboard and cannot be set from Codex: `update_settings` does not offer the text and `preview_recovery_message` does not accept it, because text sent into your conversations when nobody is watching must not be something a model can be talked into changing. It is sent exactly as typed, at most 2000 characters, as one message for every interruption or one per kind. It may use `{reason}`, `{category}`, `{attempt}`, `{max_attempts}` and `{reset_time}` and nothing else, and a placeholder that would carry the prompt, the reply, a title, a path, an account or a token is refused by name. The fallback is fixed: the message for that kind, else the message for every interruption, else the localized Standard message. Nothing about the text can make a failure recoverable, skip a check or choose a conversation |
| **A dry run that says what would happen and why** (`saaranshM/unsnooze`'s `preview`) | v0.6.3's **Why it is waiting**, on the Dashboard's Pending page: the watcher's safety checks for the chosen task, as the watcher last recorded them and when (`control.py:describe_record`, `gates` and `gates_at`). It evaluates nothing when asked, so it cannot disagree with the watcher by being a second code path answering the same question. The Preview beside the continuation settings is the other half: the exact text that would be sent, from the function that sends it |
| **A checkbox list of which conversations to auto-resume** (`boyso/codex-reset`, macOS) | v0.6.3's **Auto-resume** check box, a switch since v0.6.4, in the notification-area popup and on the Dashboard's Pending page, for each task that is already waiting. A click carries that task's interruption id and conversation id as they were when the row was drawn, and the control layer refuses one that reaches a record which has since finished, disappeared or turned out to belong to another conversation. It changes whether that conversation may be resumed and sends nothing; the watcher still decides and still sends. There is no list of every conversation to tick in advance: the switch exists only where there is an exact record to bind it to |
| **Bulk actions on every tracked task** (`saaranshM/unsnooze`'s `cancel --all` and `resume-now --all`) | Half of it. v0.6.3's **Cancel all** on the Pending page stops every pending recovery, one exact record at a time, through the same cancel a single task uses (`control.py:cancel_all_pending`); it can only reduce what the tool does. There is deliberately no retry-all: one record at a time under one lock is what keeps the argument that nothing is ever sent twice short enough to check. Cancel all is not an MCP tool |

### Rejected — a deliberate choice, not an omission

From v0.6.11 there are two editions, and a refusal here is the standard edition's: it keeps every
one. The advanced edition builds what they ruled out, each capability off until a person turns it on
in the Dashboard, after reading which of the standard edition's rules it breaks - except what both
editions refuse. The middle column is what the advanced edition offers today; what it is still to
build is under *Deferred*, below. Those rules are listed by id in [STANDARDS.md](STANDARDS.md), and
[EDITIONS.md](EDITIONS.md) says what each edition is.

| Feature | The standard edition refuses | The advanced edition offers, opt-in | Both refuse |
| --- | --- | --- | --- |
| **Retrying unknown provider failures** on a separate budget | The single line that defines this project. A failure it cannot name is a failure it does not act on | Not yet (v0.6.13) | Rules matched against a failure's text: the advanced edition's rules will read Codex's structured error tags only |
| **Retrying authentication failures**, even with a lower limit | An auth failure needs a person. Retrying it can only burn attempts or lock an account | Not yet (v0.6.13) | Reading Codex's credentials; retrying a policy, permission or cancelled turn, which would get around a limit or override the person's own decision |
| **A shared local app-server** (`CODEX_APP_SERVER_WS_URL`) | It means owning a piece of Codex's own transport, and a bug in it degrades Codex itself rather than degrading recovery | Not this. The marker-free and goal continuations start a short-lived `codex app-server` of their own for each send - one call, or at most two for the goal continuation where the app holds the conversation (`thread/goal/set`, then `thread/queue/add`) - which nothing else talks to (`advanced/src/codex_auto_resume_advanced/codex/protocol.py`) | Owning Codex's transport: a shared app-server, a proxy or a retry gateway would mean changing how Codex starts or connects |
| **Waking unloaded threads** via `thread/resume` | Follows from the above. The one route anybody has demonstrated - restoring an unloaded parent with its persisted settings - runs through that shared app-server, which means Codex pointing at an endpoint this project owns. Re-examined for v0.6.0 and still refused: an unloaded thread waits here until the user opens it, and the README states that limitation rather than engineering around it | Nothing is woken. For a usage limit, the goal continuation sets the paused goal of a conversation the app does not hold active again, so that Codex carries it on when the app next opens that conversation - which no record shows yet: measurement M2 found only that the app does not take such a goal up while it holds the conversation. Waking one is v0.6.13's | — |
| **Injecting items into a thread** (`thread/inject_items`) | Writing into a conversation by any route other than the documented queue is not something this tool should be able to do | The marker-free continuation adds its message to the conversation's own queue through the app server (`thread/queue/add`), the queue `codex queue` fills | `thread/inject_items`, and writing into a subagent's thread |
| **Goal-state manipulation** | Reading and setting Codex's native goal state is a second model of what a task *is*, and every ambiguity in it becomes a way to resume the wrong work | The goal continuation: for a usage limit, the conversation's existing goal that the limit paused is set active again (`thread/goal/set`), its status read back | Creating a goal, and reading or changing what a goal says |
| **Subagent recovery** | Recovering a child thread on a parent's behalf multiplies the identity problem that this project's safety rests on | Not yet (v0.6.13) | Writing into the child's thread: v0.6.13 recovers through the parent |
| **Restoring model, provider, service tier, reasoning and permission settings** before recovery | It requires reading and replaying a slice of Codex's own session configuration. Here the thread is resumed as the user left it | Not yet (v0.6.13) | — |
| **Dispatching several due tasks at once** | Sequential dispatch under one lock is what makes the no-duplicate-send argument short enough to check | Not yet (v0.6.13) | More than one send in flight in one conversation |
| **Starting the watcher when Codex starts** | Codex runs a plugin's server in a job that ends everything it starts, a few seconds later (measured for v0.6.9), so the standard edition refuses where the job would end the watcher | Start with Codex, through WMI: the watcher is started outside Codex's job and outlives it (measurement MW) | — |
| **A continuation with no marker** | The marker is how the standard edition proves which message arrived | The marker-free continuation: delivery proven by a client id derived from the interruption instead (measurement M7) | — |
| **Failures only the desktop app's renderer sees** - `writerConflict`, `resumeError`, `sharedTaskUnavailable`, `threadHandoff` | — | — | They are events inside the app, not errors Codex writes to its history; reaching them would mean injecting into the app |
| **Priming a usage window**, or keep-alive messages | — | — | A message whose only purpose is to start, align or keep a usage window shapes the service's limits instead of doing the person's work |
| **Rotating accounts**, or switching automatically when a limit hits | — | — | Its purpose is to evade a usage limit. v0.6.13 switches the active account on the person's command only |
| **Patching Codex, UI automation or code injection** - clicking Retry, a DevTools hook, a patched app or binary | — | — | Both editions act on Codex only through its official interfaces: `codex queue`, its app server and its plugin |
| **Answering approval or permission prompts automatically** | — | — | The app's approval requests go only to its own private server, and granting one unattended takes away the person's own safety decision; every request a session of the advanced edition receives is declined |

### Deferred — reasonable, not now

| Feature | Condition |
| --- | --- |
| **Empty-response recovery** — treating a completion with no assistant reply as a temporary failure | Re-examined for v0.6.0. Their handling is careful and privacy-bounded — a boolean for whether a final message was present, never its contents — and they now also note that Codex's own "finished a turn" popup fires before a completion can be classified, so a false completion cannot be un-notified. The failure is real and the detection can be content-free. It stays out of the standard edition because nothing in this repository has ever seen one: distinguishing it from a model that legitimately had nothing to say needs privacy-stripped structural captures from real Codex history, and there are none. The advanced edition plans it for v0.6.13, recognised by the kinds of item a turn left - no agent message and no progress - once per turn and off until a person turns it on |
| **A break-glass "safely disable" action** | Their version exists because shared mode can leave Codex pointing at a dead endpoint. Nothing in either edition today can put Codex in a state it needs rescuing from, so the action has nothing to undo. v0.6.13 plans the first thing that could: the advanced edition writing Codex's own retry settings through its official configuration. That capability comes with the undo - the settings backed up, and put back when it is turned off or the product uninstalled |
| **The rest of the advanced edition** - unknown failures on their own budget, a sign-in failure retried after proof, an unloaded conversation queued until it is opened or run headless, subagent recovery through the parent, several conversations at once, a headless run with the settings Codex saved for the conversation | v0.6.13, in the advanced edition only, each off until a person turns it on; the [roadmap](ROADMAP.md) lists them all. v0.6.11 was released with the first three capabilities, and the rest moved there whole |
| **Watching several Codex homes** | v0.6.13, in the standard edition. It waited on a measurement of whether the desktop app runs on a second Codex home at all, which passed on 2026-09-28 |

**Re-read for v0.6.3 on 2026-09-14**, against this project's own reasons rather than against
the other projects, which were not re-surveyed for it. Empty-response recovery stays deferred:
there are still no privacy-stripped captures of a real one to tell it apart from a model that
had nothing to say. Waking unloaded threads, goal-state manipulation and subagent recovery stay
rejected, for the reasons in their rows. v0.6.3 changed what the product says and shows, and
nothing in it moved a condition any of those reasons rests on.

**Re-read for v0.6.11 on 2026-09-28**, against this project's own reasons again; the other
projects were not re-surveyed. Every refusal above still binds the standard edition, and nothing in
v0.6.11 moved a condition any of them rests on. What changed is that the refusals are now the
standard edition's, and *Rejected* says, beside each, what the advanced edition does instead - goal
state and a continuation with no marker among them - and what both editions still refuse.

## The line that decides

> Keep the recovery engine small, local, conservative, and fail-closed; expand recovery only for
> clearly classified transient failures, and improve installation and control without turning the
> project into a second management application.

When a proposed feature would make the runtime do more rather than make the tool easier to install,
understand or trust, it belongs in the other project, not this one. The v0.5 surfaces were added
under exactly that test: they change how the product is *configured and explained*, and not one of
them can recover anything. So were v0.6.3's - nine languages, the continuation message's styles
and Custom text, a popup and a redesign - and the classifier, the gates and the one watcher
allowed to send are the ones v0.6.2 had.

This is the standard edition's line, and it keeps it. The advanced edition exists so that a person
who wants more can have it without the standard edition's code holding any of it: its capabilities
are left out of the standard archive, and `build/edition_audit.py` proves from the archives' own
bytes, in every release build, that none of them is there.
