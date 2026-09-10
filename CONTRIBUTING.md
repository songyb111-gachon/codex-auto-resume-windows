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

### After a release is published: pin its digest

The Codex plugin installs the release by downloading it, so it needs to know what the
archive should hash to. `scripts/release.json` maps a version to that digest, and the entry
for a version being released is `null` until the archive exists — a chicken-and-egg the
build cannot solve, because the archive is not reproducible. (The in-box C# compiler stamps
a fresh module version GUID into every assembly, so two builds of identical source differ.
`build/make_release.py` says so in full.)

So, once the release is up:

1. Download the published `CodexAutoResume-v<version>-win-x64.zip`.
2. `Get-FileHash <zip> -Algorithm SHA256` — and check it against the published `.sha256`.
3. Put that digest in `scripts/release.json` under the version, and commit.

Until that commit exists, the plugin verifies against the published `.sha256` sidecar
instead and says so when it runs. That is weaker — the sidecar comes from the same origin
as the archive — so it is worth closing rather than leaving.

### A published version is immutable

`v0.5.4` names one archive, with one SHA-256, for as long as the release exists. There is
no supported way to change the bytes behind a published version, and the release workflow
refuses to try: publishing stops if the version already has assets.

This is not tidiness. The plugin's bootstrap pins a version's digest and refuses anything
else, so replacing a published archive either breaks every install of that version or -
worse - succeeds with bytes the pinned digest does not describe. Two people installing
"v0.5.4" a month apart have to get the same thing.

So a correction gets a new version. If a published archive turns out to be wrong, bump the
version, tag, and publish that; the mistaken release stays as a record of what was actually
released, which is the point of a release.

The manual dispatch still exists and is now a dry run: point it at any ref and it builds,
tests and verifies, then keeps the archive as a workflow artifact. It cannot create or
change a release.

> Actions → **release** → Run workflow → optionally set **ref**.

### Changing anything visual

Colours, the icon and the generated files that carry them are covered in
[`docs/BRAND.md`](docs/BRAND.md). The short version: the palette lives in
`src/codex_auto_resume/brand.py`, `gui/Brand.cs` and `assets/brand/icon.svg` are generated
from it, and `tests/test_brand.py` regenerates both and compares. Do not write a colour
literal into the settings window or the panel stylesheet; there is a test for that too.

## The MCP declaration is added at build time

The repository manifest declares only `skills`. The release build adds `mcpServers` to the
copy it packs beside the bundled interpreter. That split is deliberate: the MCP server runs
on the interpreter that ships in the release archive, so declaring it in the repository would
make a marketplace install from GitHub register a command that is not there. Please do not
"fix" that by moving the declaration into the manifest — the build refuses to run if both
declare it.

## The Korean branch is generated

`ko` is built from `main`, by `.github/workflows/sync-ko.yml`, every time main's tests
pass — and it is force-updated. A pull request against `ko` cannot be merged and an edit
made there is lost at the next sync, so please do not spend an evening on one.

It was an independent fork until v0.5.5, with its own copy of the engine, the installer,
the workflows and the tests. It ended up three releases behind while still telling Korean
readers that the tool made no network request and that installing meant downloading a
release archive. That is what a second copy of a codebase does when somebody has to
remember to merge it.

So the code on `ko` is main's code, and the only difference is the language of the
documents. To change something there:

- **code, installer, workflows, tests** — change them on `main`; they reach `ko` unchanged.
- **Korean prose** — change the `.ko.md` file on `main`. `scripts/ko_branch.json` maps each
  one to the English page it replaces, and its `not_yet_translated` list is the visible
  to-do for pages that are still English on `ko`.

`python scripts/ko_sync.py --check` shows what a sync would do without writing anything.
Adding a Korean page means adding the file and its mapping entry in the same commit;
`tests/test_korean.py` fails if a Korean page exists that nothing maps.

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
