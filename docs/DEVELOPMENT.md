# Development history

This project was built in five phases (0 to 4) by one human maintainer working with two AI coding tools.
This page covers the work up to the v0.5 releases; [CHANGELOG.md](CHANGELOG.md) and
[ROADMAP.md](ROADMAP.md) tell what came after.
It is recorded here because the *investigation* is a large part of the value: most of the effort went
into finding out what the Windows ChatGPT/Codex desktop app actually supports, and into proving what
it does **not** support.

Identifiers in the linked evidence files are pseudonymised, and absolute paths and process ids are
generalised. No conversation content, prompt text, or credential ever left the local machine.

What each of those findings, and everything later built on them, is backed by *today* is in
[FEATURE_MATRIX.md](FEATURE_MATRIX.md), capability by capability; the part of it that only a person on a real
machine can settle is the procedure in [LIVE_ACCEPTANCE.md](LIVE_ACCEPTANCE.md).

## Phase 0 — Goals and safety constraints (songyb111-gachon)

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

## The day the bundled Python moves

The rest of this page is history; this section is a checklist. The bundled runtime is pinned on purpose and moves only when
someone decides it does. Everything below was tried against 3.15.2 while the runtime stayed on 3.14, so moving to 3.15 is this
list and nothing else, in one change on `dev`:

1. **The pin.** `PYTHON_VERSION` and `PYTHON_SHA256` in `build/make_release.py`, the digest copied from python.org's release file
   list and compared with the file it serves. `bundled_runtime` and `release_build` in `scripts/python_support.json`, and the
   three exact versions in `.github/workflows/` (`release.yml` twice, `test.yml` once) that `tests/test_python_support.py` holds
   to it. The pin in `tests/test_python315_switch.py` (the committed list is still 3.14's) goes with it.
2. **What stays of the runtime.** `python build/runtime_keep.py <the embed zip> --python X.Y.Z --sha256 <digest> --out <file>`, then
   copy the file over `build/runtime_keep.json`. The tool renames what carries a version, keeps what the zip still has, adds what
   the shipped modules fail without, and carries over each reason that still applies. What it prints under "to read" (it exits 3
   while there is any) is an import of a module that went: read it and write why it cannot run into `reviewed`, or keep the module.
   The build's own check stops on anything left unread. Against 3.15.2: 349 members kept, 14 files leave, `sre_*` are gone from
   the zip, `zipfile/_path/_functools.pyc` is added, and these imports wait to be read: `importlib.metadata` of its `_context` and
   `_typing`, `sqlite3.__main__` of `_completer`, `xml` of `xml.utils`, `zipimport` of `_zstd`.
3. **The CI.** Nothing: the 3.15 lanes block a merge already (`experimental: false` in `test.yml`).
4. **Lazy imports.** `LAZY_IMPORTS` in `src/codex_auto_resume/__init__.py`, off until this day. Set in that one place because
   every interpreter the product starts imports that package first, from any of eight command lines in three languages. On, every
   import on the bundled runtime waits for its name's first use; a source run is left alone, and `build/runtime_check.py` refuses
   it so that a missing module cannot pass as imported. Cold start, median of 20 on a working laptop under load:

   | | 3.14.10 | 3.15.2 | 3.15.2, lazy |
   |---|---|---|---|
   | one bridge call (`controlcli status`) | 702 ms | 626 ms | 449 ms |
   | MCP server's first reply | 626 ms | 595 ms | 410 ms |
   | watcher, one tick (`run --once`) | 930 ms | 967 ms | 650 ms |

   The window's long-lived bridge gains this once per opening, one-shot calls every time. `tests/test_python315_lazy.py` compares
   every module's tables and the bridge's answers with and without it on 3.15 and finds no difference; nothing here registers
   across modules at import. What it costs: a long-lived process (the watcher, the MCP server) then imports a module hours after it
   started, from files an update may have replaced. Turn it on in a beta, not a final, and watch that first update.
5. **The documents.** A `docs/CHANGELOG.md` entry in both languages, and the versions `docs/GUIDE.md`, `docs/VERIFY.md` and
   `docs/CONTRIBUTING.md` name.

What 3.15 changes by itself is the default text encoding (PEP 686): a text call with no encoding means UTF-8 there, where it meant
cp949 on this kind of PC. The product's calls all name theirs, as do the build's and the tests', and
`tests/test_python315_encoding.py` finds a new one that does not. Pipes change too: a Python child now prints UTF-8, which the
installer and the window already expect, since `plugin_setup.py` and `controlcli` set it themselves. A console program (csc,
PowerShell, cmd) still prints the code page, so its output is read with `encoding="locale", errors="replace"`, which stays cp949 on
3.15; plain `text=True` there would end in a `UnicodeDecodeError` on the first Korean word.

`tests/test_python315_ready.py` keeps out what 3.15 removes or deprecates. To see where the time goes on 3.15,
`build/profile_tachyon.py` samples a source-run bridge or watcher (Tachyon, PEP 799) in a scratch folder; it is not shipped.

## Credits

See [CONTRIBUTORS.md](CONTRIBUTORS.md). OpenAI Codex and Anthropic Claude Code are AI development
tools, not human contributors or GitHub accounts. Copyright is held by the human maintainer.
