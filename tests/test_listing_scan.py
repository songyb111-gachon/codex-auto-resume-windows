"""What the plugin listings' scanner asks of this repository, held here so a change cannot quietly cost the listing.

hashgraph-online/awesome-codex-plugins and awesome-ai-plugins list a plugin only when the HOL AI Plugin Scanner
(the PyPI package plugin-scanner, 3.0.123 in ai-plugin-scanner-action caba2e96) scores its repository's default
branch at 80 or more. Its checks are plain file rules, restated here from its source (checks/manifest.py,
marketplace.py, best_practices.py, code_quality.py, security.py, security_secret_patterns.py) for the checks this
repository once failed. They read the repository only; nothing here runs the scanner.

Two of its checks are not held here, on purpose:
* "Version follows semver" wants a bare X.Y.Z, so every pre-release manifest fails it and every final passes; the
  manifest's grammar is test_plugin's.
* "No privileged untrusted checkout patterns" fails any workflow with a pull_request_target or workflow_run trigger,
  a checkout, and the text of a head ref anywhere in it - however that ref is used. test_workflow_privilege holds
  what those workflows may do; writing the same expressions in another spelling only to pass a text match would
  hide them from a reviewer, so they stay as they are.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / ".codex-plugin" / "plugin.json"
MARKETPLACE = ROOT / ".agents" / "plugins" / "marketplace.json"


def tracked(suffixes=None):
    """Every tracked file the scanner reads (it scans a fresh clone of the default branch), with its relative path."""
    listing = subprocess.run(["git", "-C", str(ROOT), "ls-files"], capture_output=True, text=True,
                             encoding="utf-8", check=True).stdout.splitlines()
    for name in listing:
        path = ROOT / name
        if path.is_file() and not path.is_symlink() and (suffixes is None or path.suffix.lower() in suffixes):
            yield Path(name), path


# The scanner's secret rules (security_secret_patterns.SECRET_PATTERNS): a name, then = or :, then a quoted value of
# eight or more characters; and the providers' own token shapes.
NAMED = [re.compile(r"password\s*[=:]\s*[\"']([^\s\"']{8,})", re.I),
         re.compile(r"secret\s*[=:]\s*[\"']([^\s\"']{8,})", re.I),
         re.compile(r"token\s*[=:]\s*[\"']([^\s\"']{8,})", re.I),
         re.compile(r"api_?key\s*[=:]\s*[\"']([^\s\"']{8,})", re.I),
         re.compile(r"PRIVATE_KEY\s*[=:]\s*[\"']([^\s\"']{8,})")]
PROVIDERS = re.compile(r"AKIA[0-9A-Z]{16}|gh[pous]_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{20,}|glpat-[A-Za-z0-9\-]{20}"
                       r"|xox[bpas]-[A-Za-z0-9\-]{10,}|xox[er]-[A-Za-z0-9\-]{10,}|xapp-[A-Za-z0-9\-]{10,}"
                       r"|(?<![A-Za-z0-9])sk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}")
AWS_SECRET = re.compile(r"aws_secret_access_key\s*[=:]\s*[\"']?[A-Za-z0-9/+=]{40}", re.I)
PRIVATE_KEY = re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----")
# Where the scanner lets a placeholder pass (security._is_example_surface): documents, tests, skills and the like.
EXAMPLE_PARTS = {"docs", "doc", "skills", "skill", "prompts", "prompt", "instructions", "instruction", "examples",
                 "example", "samples", "sample", "guides", "guide", "tutorials", "tutorial", "rules", "tests", "test",
                 "__tests__", "fixtures", "fixture"}
EXAMPLE_FILE = re.compile(r"(?:^test_|\.test\.[^.]+$|\.spec\.[^.]+$|_test\.[^.]+$)", re.I)
BINARY = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".woff", ".woff2", ".ttf", ".eot", ".otf", ".zip", ".tar",
          ".gz", ".7z", ".rar", ".wasm", ".pyc", ".so", ".dylib"}


def example_surface(relative: Path) -> bool:
    return (relative.suffix.lower() in {".md", ".mdx", ".markdown", ".rst", ".adoc", ".asciidoc"}
            or bool({part.lower() for part in relative.parts} & EXAMPLE_PARTS) or bool(EXAMPLE_FILE.search(relative.name)))


def placeholder(value: str) -> bool:
    """security._looks_like_placeholder_secret: the shapes the scanner takes for a stand-in, on an example surface."""
    value = value.strip().strip("\"'`")
    lowered = value.lower()
    return (not value or value.startswith(("${", "{{", "<", "[")) or "..." in value or "…" in value
            or lowered.startswith(("your", "example-", "sample-", "demo-"))
            or lowered.endswith(("-here", "_here", "example", "sample"))
            or lowered in {"redacted", "changeme", "set-at-runtime", "set_at_runtime"}
            or bool(re.search(r"(?:^|[-_])(x{4,}|\*{3,})(?:[-_]|$)", value, re.I)))


class ListingScanTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.marketplace = json.loads(MARKETPLACE.read_text(encoding="utf-8"))

    def test_the_interface_links_use_https_and_its_assets_are_in_the_repository(self):
        # manifest.check_interface_assets: all three URLs, both icons, and at least one screenshot.
        interface = self.manifest["interface"]
        for field in ("websiteURL", "privacyPolicyURL", "termsOfServiceURL"):
            self.assertTrue(str(interface.get(field, "")).startswith("https://"), field)
        for field in ("composerIcon", "logo"):
            self.assertTrue(interface[field].startswith("./"), field)
            self.assertTrue((ROOT / interface[field]).is_file(), field)
        self.assertTrue(interface["screenshots"])
        for picture in interface["screenshots"]:
            self.assertTrue(picture.startswith("./") and (ROOT / picture).is_file(), picture)

    def test_the_policy_links_name_documents_this_repository_has(self):
        blob = "https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/"
        for field, name in (("privacyPolicyURL", "docs/PRIVACY.md"), ("termsOfServiceURL", "LICENSE")):
            self.assertEqual(self.manifest["interface"][field], blob + name)
            self.assertTrue((ROOT / name).is_file(), name)

    def test_every_marketplace_source_is_a_dot_slash_path_inside_the_repository(self):
        # marketplace_support.validate_marketplace_path_requirements: "./" first, and no way out of the root.
        for entry in self.marketplace["plugins"]:
            path = entry["source"]["path"]
            self.assertTrue(path.startswith("./"), path)
            resolved = (ROOT / path).resolve()
            self.assertTrue(resolved == ROOT.resolve() or ROOT.resolve() in resolved.parents, path)

    def test_there_is_a_codexignore(self):
        # best_practices.check_codexignore asks only that it exists; it lists what a bundle leaves out.
        lines = [line for line in (ROOT / ".codexignore").read_text(encoding="utf-8").splitlines()
                 if line.strip() and not line.startswith("#")]
        for kept_out in (".env", "config/", "logs/", ".codex/", "build/dist/"):
            self.assertIn(kept_out, lines)

    def test_no_code_file_calls_eval_or_the_function_constructor(self):
        # code_quality.check_no_eval: any match in any .py/.js/.ts-like file, comments and tests included.
        found = []
        for relative, path in tracked({".py", ".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs"}):
            text = path.read_text(encoding="utf-8", errors="ignore")
            for match in re.finditer(r"\beval\s*\(|new\s+Function\s*\(", text):
                found.append("%s:%d" % (relative.as_posix(), text.count("\n", 0, match.start()) + 1))
        self.assertEqual(found, [], "the scanner scores each of these as dynamic code execution")

    def test_nothing_reads_as_a_hardcoded_secret(self):
        # security.check_no_hardcoded_secrets: one HIGH finding per file. A named value passes only as a placeholder
        # on an example surface; a provider-shaped token is held stricter here than the scanner holds it.
        found = []
        for relative, path in tracked():
            if relative.suffix.lower() in BINARY:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            hits = [match for pattern in NAMED for match in pattern.finditer(text)
                    if not (example_surface(relative) and placeholder(match.group(1)))]
            hits += [*PROVIDERS.finditer(text), *AWS_SECRET.finditer(text), *PRIVATE_KEY.finditer(text)]
            found += ["%s:%d" % (relative.as_posix(), text.count("\n", 0, hit.start()) + 1) for hit in hits]
        self.assertEqual(found, [], "name it otherwise (PRIVATE, ..._INK) or write the stand-in as <placeholder>")


if __name__ == "__main__":
    unittest.main()
