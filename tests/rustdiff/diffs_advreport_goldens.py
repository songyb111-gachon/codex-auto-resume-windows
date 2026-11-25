"""The compatibility report's reader held to its six goldens (seat S7.3c, car-adv `report/`).

`advanced/tests/golden/report/` holds six files, written by codex-compat-reporter 1.5.0's own `build` over the homes
`reportfixtures.SCENARIOS` makes. This runs the Rust reader on exactly those homes - built by the tag's own fixtures
(Python, in a scratch folder) - and holds, for each one:

* the reader's body, written by car-machine's writer (two-space indent, ASCII), equal **as bytes** to the golden's body
  as `json.dumps(indent=2)` writes it - key order and all; no golden is regenerated (D12's rule, extended);
* what it left out equal to the golden's `left_out`;
* the envelope `report/document.assemble` puts around the body naming this product has the golden's keys, in the golden's
  order, and the golden's `format`, `attribution` and `note`;
* the whole answer equal to the tag's own reader's, over the same home, and the homes left as they were (no file made,
  none written, no `-journal`).

`reportgolden.py` is not run: it needs codex-compat-reporter 1.5.0's file, which lives outside this repository.
"""
from __future__ import annotations

import json
from pathlib import Path
import unittest

from rustdiff import advreport

RECORD = []
GOLDEN = advreport.GOLDEN

SCRIPT = r'''
import reportfixtures as fixtures
from codex_auto_resume_advanced.report import document, records

NAMES = sorted(fixtures.SCENARIOS)
HOMES = {}
for name in NAMES:
    home, asked = fixtures.scenario(name)
    HOMES[name] = (home, asked)
    view = home.raw_view()

    def read(home=home, asked=asked):
        with fixtures.isolated(home):
            return records.read(home.paths, home.codex, asked, now=fixtures.NOW, view=home.raw_view)

    def text(home=home, asked=asked):
        return json.dumps(read(home, asked)["body"], indent=2, ensure_ascii=True)

    def assemble(home=home, asked=asked):
        body = read(home, asked)["body"]
        made = document.assemble(body, fixtures.LOGIN, product_version=fixtures.PRODUCT_VERSION,
                                 windows="10.0.26100", now=fixtures.NOW)
        return {"keys": list(made), "envelope": {field: made[field] for field in ("format", "attribution", "note")},
                "bytes": document.check(made).decode("ascii")}

    case("records.read", str(home.paths.home), str(home.codex), asked, fixtures.NOW, view, ref=read)
    case("records.read_text", str(home.paths.home), str(home.codex), asked, fixtures.NOW, view, ref=text)
    case("document.assemble_of", str(home.paths.home), str(home.codex), asked, fixtures.NOW, view,
         fixtures.LOGIN, fixtures.PRODUCT_VERSION, "10.0.26100", ref=assemble)
finish()
'''


class GoldenDiff(advreport.ReportDiff):
    def test_the_six_goldens_are_the_six_homes(self):
        names = {path.stem for path in GOLDEN.glob("*.json")}
        self.assertEqual(len(names), 6, names)
        for path in sorted(GOLDEN.glob("*.json")):
            golden = json.loads(path.read_text(encoding="ascii"))
            self.assertEqual((golden["scenario"], golden["reporter"]), (path.stem, "1.5.0"))

    def test_the_reader_writes_what_the_reporter_wrote(self):
        found = self.family(SCRIPT, label="goldens", expect_cases=18, readonly=True)
        cases, results = found["cases"], found["results"]
        seen = []
        for index in range(0, len(cases), 3):
            name = Path(cases[index][1]).parent.name
            read, text, assembled = results[index], results[index + 1], results[index + 2]
            golden_text = (GOLDEN / ("%s.json" % self._scenario(index // 3))).read_text(encoding="ascii")
            golden = json.loads(golden_text)
            self.assertIn("ok", read, name)
            self.assertEqual(text["ok"], json.dumps(golden["body"], indent=2, ensure_ascii=True),
                             "%s: the body, key order and all" % golden["scenario"])
            self.assertEqual(read["ok"]["left_out"], golden["left_out"], golden["scenario"])
            self.assertEqual(read["ok"]["body"]["codex_version"], golden["body"]["codex_version"])
            self.assertEqual(assembled["ok"]["keys"], golden["keys"], golden["scenario"])
            self.assertEqual(assembled["ok"]["envelope"], golden["envelope"], golden["scenario"])
            seen.append(golden["scenario"])
        self.assertEqual(sorted(seen), sorted(path.stem for path in GOLDEN.glob("*.json")))
        RECORD.append("goldens: the six homes of reportfixtures.SCENARIOS read by the Rust reader - body bytes equal to "
                      "advanced/tests/golden/report/*.json (key order and all), left_out, the envelope's keys and fixed "
                      "values, and the tag's own reader's whole answer, with the homes left untouched")

    @staticmethod
    def _scenario(position):
        # The script runs the scenarios in sorted order.
        return sorted(path.stem for path in GOLDEN.glob("*.json"))[position]


if __name__ == "__main__":
    unittest.main()
