"""What the documentation is allowed to promise about the network.

Until v0.5.2 this project genuinely made no outbound request, and the documentation said
so in the strongest possible terms - "no network calls of its own", "Nothing leaves your
machine", "Third parties: none", "The tool itself does not contact GitHub". Then v0.5.2
made the Codex plugin the recommended way in, and the plugin installs the product by
downloading its release. Every one of those sentences became false on the same day, in
five files, in two languages, and nothing noticed.

So the rules are checked here rather than remembered. Two kinds:

* The **code property** the promise rests on: the recovery runtime imports no networking
  module, and exactly one shipped file reaches the network. If that ever stops being true
  the documentation is wrong no matter how carefully it is worded, so it is asserted first.
* The **wording**: an absolute claim about the network has to carry its qualifier close
  enough that a reader meets both at once. These are deliberately shape-based - a phrase
  plus a nearby qualifier - rather than exact strings, because an exact-string test would
  fail on a rewrite that is still true and pass on a rewrite that is not.
"""
from __future__ import annotations

from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]

# Modules that could open a socket. `urllib.parse` is pure string handling and is fine;
# anything that could actually connect is not.
NETWORKING = re.compile(
    r"^\s*(?:import|from)\s+"
    r"(socket|ssl|http|httplib|urllib\.request|urllib\.error|requests|httpx|aiohttp|"
    r"ftplib|smtplib|poplib|imaplib|telnetlib|xmlrpc|webbrowser|asyncio\.streams)\b",
    re.MULTILINE)

# The PowerShell verbs that would reach the network.
PS_NETWORK = re.compile(
    r"Invoke-WebRequest|Invoke-RestMethod|System\.Net\.WebClient|DownloadFile|"
    r"DownloadString|Start-BitsTransfer|\bcurl\b|\bwget\b", re.IGNORECASE)

# Claims that are only true of the recovery runtime, never of the whole product.
ABSOLUTES = (
    re.compile(r"no network calls? of its own", re.I),
    re.compile(r"nothing leaves your (?:machine|computer|PC)", re.I),
    re.compile(r"no network access from this code", re.I),
    re.compile(r"does not contact GitHub", re.I),
    re.compile(r"no (?:outbound|external) (?:network )?requests?\b", re.I),
    re.compile(r"third[- ]part(?:y|ies)\s*:?\s*none", re.I),
)

# A qualifier that makes such a sentence honest: it either scopes the claim to the part
# that really has the property, or admits the download.
QUALIFIERS = re.compile(
    r"watcher|recovery runtime|the installed tool|src/|scripts/\*?\.py|"
    r"python (?:source|code)|github|download|install|setup|bootstrap|"
    r"워처|복구 런타임|설치|내려받",   # ko: watcher, recovery runtime, install, download
    re.I)

DOCS = ("README.md", "README.ko.md", "PRIVACY.md", "SECURITY.md", "SECURITY.ko.md",
        "SUPPORT.md", "CONTRIBUTING.md", "CONTRIBUTORS.ko.md",
        "docs/PLUGIN.md", "docs/BRAND.md", "docs/COMPARISON.md",
        "docs/COMPARISON.ko.md", "docs/DEVELOPMENT.ko.md",
        "skills/codex-auto-resume/SKILL.md")

# The changelog is a record of what past releases did and must not be rewritten to match
# today; docs/DEVELOPMENT.md is the same, a history rather than a description.
HISTORICAL = ("CHANGELOG.md", "docs/DEVELOPMENT.md")


def tracked(pattern: str):
    listing = subprocess.run(["git", "-C", str(ROOT), "ls-files", pattern],
                             capture_output=True, text=True, encoding="utf-8").stdout
    return [ROOT / name for name in listing.split() if (ROOT / name).is_file()]


class CodePropertyTests(unittest.TestCase):
    """The facts the wording depends on. If these change, the wording has to."""

    def test_the_recovery_runtime_imports_no_networking_module(self):
        offenders = []
        for path in tracked("src/*") + tracked("scripts/*.py"):
            if path.suffix != ".py":
                continue
            for match in NETWORKING.finditer(path.read_text(encoding="utf-8")):
                offenders.append("%s: %s" % (path.relative_to(ROOT), match.group().strip()))
        self.assertEqual(offenders, [], "the watcher would now be able to open a connection")

    def test_exactly_one_shipped_file_reaches_the_network(self):
        # build/ is developer-only and excluded from the release payload, so it may
        # download the pinned interpreter. Everything that ships may not, except the
        # bootstrap - which is the whole point of the bootstrap.
        reaching = set()
        for path in tracked("scripts/*") + tracked("install/*") + tracked("src/*") + tracked("gui/*"):
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if PS_NETWORK.search(text):
                reaching.add(str(path.relative_to(ROOT)).replace("\\", "/"))
        self.assertEqual(reaching, {"scripts/bootstrap.ps1"},
                         "the set of files that reach the network has changed")

    def test_there_is_no_analytics_or_telemetry_endpoint(self):
        # Any host that is not GitHub's release infrastructure, in anything that ships.
        # chatgpt.com is here because the runtime *pins* it: every `codex` invocation
        # passes `chatgpt_base_url="https://chatgpt.com/backend-api/"` so a hostile local
        # config cannot redirect the queue call elsewhere. It is a constant handed to the
        # official binary, not a host this code connects to.
        allowed = re.compile(r"^https://(?:github\.com|[a-z-]+\.githubusercontent\.com|"
                             r"chatgpt\.com/backend-api/|"
                             r"www\.python\.org|agent-plugins\.org|schemas\.microsoft\.com|"
                             r"docs\.microsoft\.com|learn\.microsoft\.com)/?", re.I)
        offenders = []
        for path in tracked("scripts/*") + tracked("install/*") + tracked("src/*"):
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for url in re.findall(r"https?://[^\s\"'`)\]]+", text):
                if not allowed.match(url):
                    offenders.append("%s: %s" % (path.relative_to(ROOT), url))
        self.assertEqual(offenders, [], "a shipped file names a host we do not expect")


    def test_the_runtime_disables_codex_own_telemetry_when_it_drives_it(self):
        """Not our telemetry - Codex's, on the invocations we make.

        Every `codex` subprocess is started with analytics and every OpenTelemetry
        exporter switched off, user-prompt logging off, and the ChatGPT base URL pinned
        to the official one so a local config cannot point our queue call somewhere
        else. It is a small thing that would be easy to drop in a refactor and hard to
        notice missing.
        """
        text = (ROOT / "src" / "codex_auto_resume" / "windows.py").read_text(encoding="utf-8")
        for required in ('OTEL_SDK_DISABLED', 'analytics.enabled=false',
                         'otel.exporter="none"', 'otel.log_user_prompt=false',
                         'chatgpt_base_url="https://chatgpt.com/backend-api/"'):
            self.assertIn(required, text, required)


class WordingTests(unittest.TestCase):
    def documents(self):
        for name in DOCS:
            path = ROOT / name
            if path.is_file():
                yield name, path.read_text(encoding="utf-8")

    def test_no_absolute_network_claim_stands_unqualified(self):
        offenders = []
        for name, text in self.documents():
            lines = text.splitlines()
            for index, line in enumerate(lines):
                for pattern in ABSOLUTES:
                    if not pattern.search(line):
                        continue
                    # The qualifier may be on the line itself or immediately around it:
                    # a reader meets a sentence, not a line.
                    window = " ".join(lines[max(0, index - 2):index + 3])
                    if not QUALIFIERS.search(window):
                        offenders.append("%s:%d: %s" % (name, index + 1, line.strip()[:90]))
        self.assertEqual(offenders, [],
                         "an absolute network claim with no nearby qualifier")

    def test_privacy_separates_the_runtime_from_the_install(self):
        text = (ROOT / "PRIVACY.md").read_text(encoding="utf-8")
        self.assertRegex(text, r"(?i)github", "PRIVACY.md must name GitHub")
        self.assertRegex(text, r"(?i)(?:download|fetch)", "PRIVACY.md must say a download happens")
        # The claim that survives, and must: nothing is uploaded.
        self.assertRegex(text, r"(?i)no telemetry")

    def test_privacy_does_not_claim_there_are_no_third_parties(self):
        text = (ROOT / "PRIVACY.md").read_text(encoding="utf-8")
        section = re.search(r"##\s*Third parties(.*?)(?:\n##|\Z)", text, re.S)
        self.assertIsNotNone(section, "PRIVACY.md lost its Third parties section")
        body = section.group(1)
        self.assertRegex(body, r"(?i)github",
                         "the Third parties section must name GitHub, because the "
                         "installer contacts it")
        self.assertNotRegex(body.strip(), r"(?i)^\**none\**\.",
                            "the Third parties section must not open with None")

    def test_the_readme_summary_row_admits_the_download(self):
        for name in ("README.md", "README.ko.md"):
            text = (ROOT / name).read_text(encoding="utf-8")
            row = [line for line in text.splitlines()
                   if line.startswith("|") and re.search(r"(?i)telemetry|텔레메트리", line)]
            self.assertTrue(row, "%s has no privacy row in its summary table" % name)
            self.assertRegex(row[0], r"(?i)github",
                             "%s's privacy row must admit the download" % name)

    def test_no_released_version_has_lost_its_changelog_section(self):
        """A guard against over-correcting.

        The rule above is about current-facing prose. The changelog is the opposite: a
        record of what each release actually did, which stays true by *not* being
        updated. The failure mode worth catching is someone sweeping the tree for a
        retired phrase and deleting history along with it, so this asserts the history
        is still there rather than asserting anything about its wording.

        The floor below is spelled out rather than read from `git tag`, because CI checks
        out without tags and a test that quietly passes on an empty list guards nothing.
        Append to it when a version ships; the current version is checked separately, by
        tests/test_plugin.py.
        """
        shipped = ("v0.1.0", "v0.2.0", "v0.3.0", "v0.3.1", "v0.3.2",
                   "v0.4.0", "v0.4.1", "v0.5.0", "v0.5.1", "v0.5.2", "v0.5.3", "v0.5.4")
        text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        missing = [tag for tag in shipped
                   if not re.search(r"^##\s+%s\b" % re.escape(tag), text, re.M)]
        self.assertEqual(missing, [], "the changelog has lost a released version's section")

    def test_the_shipped_list_above_is_not_behind_the_tags(self):
        """Only meaningful where the checkout has tags; skipped where it does not.

        It exists so the hardcoded list cannot silently fall behind: a maintainer who
        tags a release and forgets this file finds out on their own machine rather than
        in a review.

        The version being released is deliberately excluded. Publishing checks out the
        tag, so at that moment the tag exists while the version is still the *current*
        one rather than a past one - and requiring it in a list of history would fail
        the release of every version, which is how this test first earned its keep.
        """
        from codex_auto_resume import config
        current = "v" + config.version()
        tags = [tag for tag in
                subprocess.run(["git", "-C", str(ROOT), "tag", "--list", "v*"],
                               capture_output=True, text=True, encoding="utf-8").stdout.split()
                if tag != current]
        if not tags:
            self.skipTest("no earlier tags visible in this checkout")
        text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        missing = [tag for tag in tags
                   if not re.search(r"^##\s+%s\b" % re.escape(tag), text, re.M)]
        self.assertEqual(missing, [], "a tagged release has no changelog section")
        source = Path(__file__).read_text(encoding="utf-8")
        unlisted = [tag for tag in tags if '"%s"' % tag not in source]
        self.assertEqual(unlisted, [], "add these to `shipped` in the test above")


if __name__ == "__main__":
    unittest.main()
