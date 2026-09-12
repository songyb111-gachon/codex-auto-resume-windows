# Development history

This project was built in four phases by one human maintainer working with two AI coding tools.
It is recorded here because the *investigation* is a large part of the value: most of the effort went
into finding out what the Windows ChatGPT/Codex desktop app actually supports, and into proving what
it does **not** support.

Identifiers in the linked evidence files are pseudonymised, and absolute paths and process ids are
generalised. No conversation content, prompt text, or credential ever left the local machine.

What each of those findings, and everything later built on them, is backed by *today* is in
[FEATURE_MATRIX.md](FEATURE_MATRIX.md), capability by capability; the part of it that only a person on a real
machine can settle is the procedure in [LIVE_ACCEPTANCE.md](LIVE_ACCEPTANCE.md).

## Phase 0 — Goals and safety constraints (Youngbin Song)

The maintainer defined the problem, the architecture direction, and — most importantly — the safety
constraints that shaped every later decision:

- Local only. No external server, no telemetry, no upload of repository or conversation data.
- Read-only against Codex's own state. Never write to Codex's databases.
- Resume the **exact** interrupted thread. Never `--last`, never a guessed thread.
- Never resume the same interruption twice.
- Fail closed: any ambiguity must result in *not* sending.
- Explicitly out of scope: GUI automation, mouse/keyboard simulation, OCR, screen scraping,
  accessibility-API clicking, binary patching, DLL injection, process-memory manipulation, and
  credential extraction.

These were treated as hard invariants for the rest of the project, not as preferences.

## Phase 1 — Investigation (OpenAI Codex)

Codex investigated how the Windows ChatGPT desktop app and its Codex engine actually work:

- The desktop app runs a separate `codex.exe` engine process as a child, connected over stdio.
- Local state lives in the Codex home directory: thread metadata, a paginated turn/item history, a
  queue database, and JSONL rollout files, plus per-thread writer lock files.
- The official CLI exposes `codex queue --thread <UUID>`, which targets one exact thread.
- The app-server protocol schema was generated from the installed binary and compared against the
  matching upstream release tag, so the adapter is pinned to a verified version rather than guessed.

## Phase 2 — Proving what works and what does not (OpenAI Codex)

Two experiments, both run against a **disposable test thread**, never a real conversation.

**Loaded thread: works.** With the thread already loaded in the app, one `codex queue --thread <UUID>`
call was delivered into that exact conversation as a real user message, and the agent replied. Proof:
[`evidence/loaded-thread-delivery.json`](evidence/loaded-thread-delivery.json).

**Unloaded thread: does not work.** After a genuine app restart, with the target thread confirmed
`notLoaded`, a single queued message stayed in the queue for the full 90-second observation window and
never became a conversation turn. The test queue item was then removed through the official API. Proof:
[`evidence/unloaded-thread-delivery.json`](evidence/unloaded-thread-delivery.json) and
[`evidence/unloaded-thread-observation.json`](evidence/unloaded-thread-observation.json).

This is the origin of the product's central limitation. It is a documented finding, not a bug.

**Usage-limit shape.** A real usage-limit interruption was captured read-only: the turn is recorded as
`status=failed` with `codexErrorInfo=usageLimitExceeded`, and the nearest preceding rate-limit snapshot
carries the numeric reset timestamp that matches the time the UI displayed, to the minute. Notably the
raw rollout event is named `task_complete` and still carries the error, so event name alone must never
be read as success. Sanitized sample: [`evidence/usage-limit-sample.json`](evidence/usage-limit-sample.json).

At the end of Phase 2, Codex had produced the detector, the durable store, the Windows adapter, and a
first scheduler, plus 65 tests. That work is preserved in the repository's first commit.

## Phase 3 — Completing the tool (Anthropic Claude Code)

Claude Code took over the partially finished prototype, reviewed it, kept what was sound, and finished it.

Two latent bugs in the inherited code were found only by running it end to end:

- `collect()` passed the detector's output straight into the store, which rejected it because of two
  extra keys. The effect was total: **no interruption was ever registered or resumed.** The watcher
  logged "detection skipped" forever.
- The entry point called `main()` without `sys.exit()`, so every exit code was 0 and the
  single-instance "busy" signal was invisible.

Added in this phase: the watcher loop, the full CLI, rotating logs that never record prompt text
(`errors.log` does carry exception text this project did not write; see `PRIVACY.md`), optional
per-user Windows autostart, clean uninstall, configuration and binary discovery, and a large
expansion of the test suite.

## Phase 4 — Review and adversarial audit (Anthropic Claude Code)

Three review rounds, each running several independent reviewers per dimension and then asking three
further independent agents to *refute* every finding. Only findings that survived refutation were fixed.

| Round | Scope | Confirmed | Rejected |
|---|---|---:|---:|
| 1 | detector, store, Windows adapter, scheduler | 12 | 6 |
| 2 | CLI, app, config, logging, autostart | 3 | 0 |
| 3 | final audit across 9 dimensions | 8 | 3 |

Representative confirmed issues, all fixed:

- The loaded-state probe could **acquire** the app's own exclusive thread writer lock when the byte
  range was momentarily free, which could make the app's own lock attempt fail. The locking code was
  removed entirely; ownership is now determined solely from the Restart Manager inventory.
- `install --startup` dropped a home directory configured by environment variable, so the autostarted
  watcher would use a different state database *and* a different single-instance mutex.
- Uninstall could delete same-named files it had never created. It now requires a provenance marker and
  refuses to touch a directory it did not create.
- A transient engine probe failure at logon terminated the watcher for the whole session.
- NTFS junctions bypassed the directory confinement checks, because `is_symlink()` does not detect them.

Rejected findings are recorded too: for example, the claim that an arbitrarily old failure could be
resumed was refuted, because a resume additionally requires that the failed turn is still the thread's
latest turn, and live usage availability is re-checked immediately before sending.

Beyond code review, three empirical techniques were used:

- **Mutation testing.** Around twenty safety guards were deliberately broken to check the suite caught
  it. Three survivors revealed genuine test gaps, all in uninstall safety; regression tests were added.
  One guard in `store.reserve()` was proven load-bearing this way: without it a double send is possible.
- **Crash-window matrix.** The process was killed at four points around sending (after reserving, before
  the CLI ran, after delivery but before recording, and after queueing but before recording). After
  restart, every case sent at most once.
- **Cross-process race.** Four processes raced to reserve the same interruption, eight times. Exactly one
  winner every time.

## Credits

See [`../CONTRIBUTORS.md`](../CONTRIBUTORS.md). OpenAI Codex and Anthropic Claude Code are AI development
tools, not human contributors or GitHub accounts. Copyright is held by the human maintainer.
