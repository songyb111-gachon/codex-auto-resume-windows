# Contributing

Thanks for looking. This is a small, deliberately conservative tool, so the most useful
contributions are usually bug reports with a reproduction, and fixes that keep the safety
properties intact.

## Development environment

- Windows 10/11. The product is Windows-only, and so is most of the test suite.
- Python 3.12 or newer, standard library only. There are no third-party runtime dependencies
  and no build step for the Python side.
- The ChatGPT/Codex desktop app, if you want to run anything beyond the unit tests.
- .NET Framework 4.8 (already on every supported Windows) to build the two small C#
  executables — the settings window and the MCP launcher.

Nothing here needs administrator rights.

## Running the tests

```bash
python -m unittest discover -s tests
```

Set `PYTHONPATH=src` first, or run from a checkout where `src` is importable.

The suite uses fakes and temporary directories. It never contacts the ChatGPT app, never
sends a message to a Codex conversation, and never writes to your real registry. The live
read-only checks stay skipped unless you set `CODEX_AR_LIVE=1` on Windows.

## Validating plugin metadata

The plugin manifest, the marketplace index and the MCP companion file are covered by
`tests/test_plugin.py`. Run the suite after touching any of them; it checks the manifest
against the fields Codex actually accepts, and it fails if the repository manifest starts
declaring an MCP server (see below).

## Building a release

```bash
powershell -ExecutionPolicy Bypass -File build/make_gui.ps1
python build/make_release.py
```

The first builds `CodexAutoResumeSettings.exe` and `codex-auto-resume-mcp.exe`; the second
downloads the pinned embeddable Python (checksum-verified), assembles the payload, and writes
the ZIP and its SHA-256 into `build/dist/`.

Releases are published by the tagged GitHub Actions workflow, not from a developer machine.

## The MCP declaration is added at build time

The repository manifest declares only `skills`. The release build adds `mcpServers` to the
copy it packs beside the bundled interpreter. That split is deliberate: the MCP server runs
on the interpreter that ships in the release archive, so declaring it in the repository would
make a marketplace install from GitHub register a command that is not there. Please do not
"fix" that by moving the declaration into the manifest — the build refuses to run if both
declare it.

## Fixtures and privacy

Everything committed here is public, including test fixtures and documentation examples. They
are written on a developer's machine, and that machine's own paths and identifiers leak into
them very easily. `tests/test_repo_hygiene.py` enforces the conventions below, so please keep
to them rather than working around it.

- **Home directories in examples are placeholders.** Use `ExampleUser`, `Example User` (when
  you need a path containing a space), `someone`, `<user>`, or `%USERPROFILE%`. Never a real
  account name.
- **UUIDs in tracked files are obviously synthetic.** Use the project's fixture family,
  `0a1b2c3d-0001-7000-8000-000000000001` and friends, or a repeated-nibble value such as
  `22222222-2222-7222-8222-222222222222`. Never a conversation id copied out of real Codex
  state — real ones are UUIDv7 values with a timestamp prefix and are trivially recognisable.
- **No copied runtime state.** Databases, logs and `config/` are never tracked. If you need
  evidence that something behaves a certain way, write a fixture that shows the structure with
  synthetic values, the way `docs/evidence/` does.
- **No real process ids, ports or machine-specific paths** in comments, docs or fixtures.

## Changes that need extra care

The recovery engine is small on purpose, and several of its properties are the whole reason
the tool is safe to leave running. A change that touches any of these needs a test that would
fail without it:

- a conversation is identified by its exact UUID, and by nothing else — never `--last`, never a
  title, project, working directory or recency;
- a failure that cannot be classified is never retried;
- user cancellation, permission, approval, content policy, invalid requests, context length and
  permanent authentication failures are never retried;
- a submission whose outcome is unknown is never automatically resent;
- every gate is re-checked immediately before sending, inside the dispatch lock;
- settings are policy only. Nothing in the settings schema may reach a safety limit, and the
  worst a malformed settings file can do is make recovery more conservative.

If you are unsure whether a change crosses one of those lines, open an issue first and say
what you are trying to achieve — there is usually a way to get there that keeps the property.

## Commit and pull requests

- One change per commit, with a message that says what changed and why.
- Run the full suite before pushing.
- If you fixed something a user could hit, add the regression test in the same commit.
