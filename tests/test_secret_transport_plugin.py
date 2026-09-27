"""Behavioral coverage for the real OpenCode secret-transport plugin
(`assets/plugins/secret-transport.ts`), driven under Node with the real,
canonical catalog data (`content/security/credential-transport-catalog.json`)
-- the same "drive the real plugin, don't re-derive the fix from a regex"
approach `test_engram_memory_scope.py`'s own Node harness test already uses.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "src/pegasus/adapters/opencode/assets/plugins/secret-transport.ts"
CATALOG = ROOT / "src/pegasus/content/security/credential-transport-catalog.json"
HARNESS = ROOT / "tests/fixtures/secret_transport_harness.mjs"


class SecretTransportPluginNodeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if shutil.which("node") is None:
            raise unittest.SkipTest("node is not installed — cannot run the plugin harness")

    def _run(self) -> dict:
        result = subprocess.run(
            ["node", "--experimental-strip-types", str(HARNESS), str(PLUGIN), str(CATALOG)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"plugin harness failed:\nstdout: {result.stdout}\nstderr: {result.stderr}",
        )
        return json.loads(result.stdout)

    def test_a_json_header_redacts_token_and_clientkey_but_not_id_or_obra_social(self):
        data = self._run()["header_json"]
        self.assertTrue(data["tokenGone"])
        self.assertTrue(data["clientKeyGone"])
        self.assertTrue(data["idPreserved"])
        self.assertTrue(data["obraSocialPreserved"])
        self.assertTrue(data["noteAppended"])

    def test_a_commit_hash_and_a_sha256_in_the_same_message_survive_untouched(self):
        data = self._run()["header_json"]
        self.assertTrue(data["commitPreserved"])
        self.assertTrue(data["sha256Preserved"])

    def test_a_url_password_is_redacted(self):
        self.assertTrue(self._run()["url_credential"]["passwordGone"])

    def test_a_bearer_jwt_is_redacted(self):
        self.assertTrue(self._run()["jwt_header"]["jwtGone"])

    def test_an_api_key_header_is_redacted(self):
        self.assertTrue(self._run()["api_key_header"]["valueGone"])

    def test_an_openai_shaped_key_is_redacted(self):
        self.assertTrue(self._run()["openai_shaped"]["keyGone"])

    def test_a_github_token_is_redacted(self):
        self.assertTrue(self._run()["github_token"]["keyGone"])

    def test_a_pem_private_key_block_is_redacted(self):
        self.assertTrue(self._run()["pem_block"]["pemGone"])

    def test_explicit_private_tag_with_a_name_uses_that_name(self):
        data = self._run()["explicit_named"]
        self.assertTrue(data["valueGone"])
        self.assertTrue(data["usesDbPasswordName"])

    def test_the_same_value_always_maps_to_the_same_variable(self):
        data = self._run()["same_value_same_variable"]
        self.assertTrue(data["same"])
        self.assertIsNotNone(data["varA"])

    def test_shell_env_exposes_every_registered_value(self):
        env = self._run()["shell_env"]
        self.assertIn("PEGASUS_SECRET_TOKEN", env)
        self.assertIn("PEGASUS_SECRET_CLIENTKEY", env)
        self.assertIn("PEGASUS_SECRET_JWT", env)

    def test_tool_execute_after_redacts_an_echoed_registered_value(self):
        data = self._run()["tool_execute_after"]
        self.assertTrue(data["valueGone"])
        self.assertNotIn("\\n", data["output"])

    def test_pasted_code_survives_the_bare_unquoted_pass(self):
        """A review-found regression: the bare `key=`/`key:` pass must never
        corrupt a code identifier, a function call, a dotted reference, or a
        shell/template interpolation -- only a real unquoted credential
        value."""
        data = self._run()["code_survival"]
        for name, case in data.items():
            self.assertTrue(case["unchanged"], f"{name}: {case['text']!r}")

    def test_a_compound_key_with_a_digit_value_is_still_detected(self):
        """`DB_PASSWORD=s3cr3tP4ss` -- a compound key (catalog key
        `password` as its trailing word) and a value that contains a digit,
        so it is not skipped by the accepted `bare_identifier_no_digit`
        false negative."""
        self.assertTrue(self._run()["db_password_with_digits"]["valueGone"])

    def test_a_quoted_plain_word_still_counts_as_a_value(self):
        """`password: "plainword"` -- quoted always counts, even though the
        word itself has no digit and would be skipped unquoted."""
        self.assertTrue(self._run()["quoted_plain_word"]["valueGone"])


if __name__ == "__main__":
    unittest.main()
