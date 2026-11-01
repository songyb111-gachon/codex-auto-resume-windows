"""MB asks codex-cli 0.166's config writes in the shape its schema takes (v0.6.21).

MB failed on codex-cli 0.166.0-alpha.5.1 (2026-10-31) as on 0.162.0-alpha.17.2: config/value/write refused with -32600.
The 0.162 run read the reason on a scratch home: "model_providers contains reserved built-in provider IDs: `openai`.
Built-in providers cannot be overridden" - a refusal by design of any write under model_providers.openai, not of the
request's shape. These tests hold every write the probe makes to ConfigValueWriteParams as the 0.166 schema
(`codex app-server generate-json-schema`, 2026-10-31) gives it, copied below, and hold the one thing the probe had
wrong for 0.166: config/read there answers no version of its own - each layer carries one (ConfigLayer.version) - so
the stale-version write carried null, which Codex never checks, and MB could not pass even where writes are taken.

Every session is a fake on a scratch home the probe makes; no Codex runs.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_advanced_measure_stage4 import REPLIES, ProbeCase, refused  # noqa: E402
from codex_auto_resume_advanced import measure  # noqa: E402
from codex_auto_resume_advanced.vocabulary import Measurement  # noqa: E402

# codex-cli 0.166.0-alpha.5.1, v2/ConfigValueWriteParams.json (the parts that judge a request).
CONFIG_VALUE_WRITE_PARAMS = {
    "properties": {"expectedVersion": {"type": ["string", "null"]}, "filePath": {"type": ["string", "null"]},
                   "keyPath": {"type": "string"}, "mergeStrategy": {"enum": ["replace", "upsert"]}, "value": True},
    "required": ["keyPath", "mergeStrategy", "value"],
}
TYPES = {"string": str, "null": type(None)}


def schema_problems(params):
    """What in `params` ConfigValueWriteParams does not take: a missing required key, an unknown key, a value of the
    wrong type or outside its enum."""
    found = [key for key in CONFIG_VALUE_WRITE_PARAMS["required"] if key not in params]
    for key, value in params.items():
        rule = CONFIG_VALUE_WRITE_PARAMS["properties"].get(key)
        if rule is None:
            found.append("unknown " + key)
        elif rule is True:
            continue
        elif "enum" in rule and value not in rule["enum"]:
            found.append("enum " + key)
        elif "type" in rule and not isinstance(value, tuple(TYPES[name] for name in (
                [rule["type"]] if isinstance(rule["type"], str) else rule["type"]))):
            found.append("type " + key)
    return found


class Codex0166:
    """config/read and config/value/write as 0.166 answers them: no version of the answer's own, the user layer's
    version a string that changes with each write, a stale expectedVersion refused, a null one never checked."""

    def __init__(self, reserved=False):
        self.config, self.version, self.reserved = {}, 0, reserved
        self.writes = []

    def tag(self):
        return "sha256:%064x" % self.version

    def read(self, params):
        assert params == {"includeLayers": True}
        config = json.loads(json.dumps(self.config))
        return {"config": config, "origins": {},
                "layers": [{"name": {"type": "system", "file": "C:/ProgramData/OpenAI/Codex/config.toml"},
                            "version": "sha256:%064x" % 999, "config": {}},
                           {"name": {"type": "user", "file": "C:/scratch/config.toml"}, "version": self.tag(),
                            "config": config}]}

    def write(self, params):
        self.writes.append(params)
        if schema_problems(params):
            return refused("config/value/write", -32602)
        if self.reserved and params["keyPath"].startswith("model_providers.openai."):
            return refused("config/value/write", -32600)
        if params.get("expectedVersion") is not None and params["expectedVersion"] != self.tag():
            return refused("config/value/write", -32600)
        node = self.config
        *parents, last = params["keyPath"].split(".")
        for part in parents:
            node = node.setdefault(part, {})
        if params["value"] is None:
            node.pop(last, None)
        else:
            node[last] = params["value"]
        self.version += 1
        return {"status": "ok", "version": self.tag(), "filePath": "C:/scratch/config.toml"}


class SchemaShapeTests(ProbeCase):
    def run_mb(self, codex):
        with patch.dict(REPLIES, {Measurement.MB: {"config/read": codex.read, "config/value/write": codex.write}}):
            return self.run_one(Measurement.MB, self.factory(Measurement.MB, with_home=True))[1]

    def test_every_write_is_one_the_0166_schema_takes(self):
        codex = Codex0166()
        self.run_mb(codex)
        self.assertEqual(len(codex.writes), 4)
        for params in codex.writes:
            with self.subTest(params["keyPath"]):
                self.assertEqual(schema_problems(params), [])

    def test_on_0166_answers_the_writes_held_and_a_stale_version_refused_pass(self):
        """Fails with the old version read restored: every write carries null, the stale one is taken, and MB fails
        where the writes were all taken."""
        codex = Codex0166()
        record = self.run_mb(codex)
        self.assertEqual(record["verdict"], "pass", record)
        self.assertTrue(all(isinstance(params["expectedVersion"], str) for params in codex.writes))
        self.assertEqual(codex.writes[-1]["expectedVersion"], "sha256:%064x" % 0, "the stale write names the first")

    def test_the_built_in_providers_refusal_is_a_fail_by_design(self):
        """What 0.162 and 0.166 do: the first write under model_providers.openai refused with -32600."""
        codex = Codex0166(reserved=True)
        record = self.run_mb(codex)
        self.assertEqual((record["verdict"], record["observed"]["refused_method"], record["observed"]["refusal_code"]),
                         ("fail", "config/value/write", -32600))
        self.assertEqual(len(codex.writes), 1)
        self.assertEqual(schema_problems(codex.writes[0]), [], "the refused request was a well-formed one")

    def test_the_version_is_the_user_layers_and_never_another(self):
        self.assertEqual(measure._version_of({"layers": [{"name": {"type": "system"}, "version": "a"},
                                                         {"name": {"type": "user"}, "version": "b"}]}), "b")
        self.assertIsNone(measure._version_of({"layers": [{"name": {"type": "system"}, "version": "a"}]}))
        self.assertIsNone(measure._version_of({"layers": None}))
        self.assertEqual(measure._version_of({"version": 3}), 3, "an older Codex's own version is still read")


if __name__ == "__main__":
    unittest.main()
