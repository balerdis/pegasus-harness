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

    def test_the_real_curl_case_redacts_short_key_context_values_and_the_signature_header(self):
        """7.3.1: `clientKey` (7 chars) and `apiKey` sit next to sensitive
        keys and must be redacted despite being under the old 8-char
        minimum; `X-Aco-Joven-Signature` is redacted by header-name suffix
        even though it is not a known Authorization/X-Api-Key header and its
        value is bare hex (never detected on shape alone elsewhere)."""
        data = self._run()["real_case_curl"]
        self.assertTrue(data["clientKeyGone"], data["text"])
        self.assertTrue(data["apiKeyGone"], data["text"])
        self.assertTrue(data["signatureGone"], data["text"])
        self.assertTrue(data["usesSignatureVarName"], data["text"])
        self.assertTrue(data["versionPreserved"])
        self.assertTrue(data["keyIdPreserved"])
        self.assertTrue(data["eligiblePreserved"])
        self.assertTrue(data["issuedAtPreserved"])
        self.assertTrue(data["requestIdPreserved"])
        self.assertTrue(data["obraSocialPreserved"])
        self.assertTrue(data["urlPreserved"])
        self.assertTrue(data["headerNamesPreserved"])

    def test_filler_non_values_next_to_sensitive_keys_are_never_replaced(self):
        """`null`, `false`, `TODO`, `xxx`, a run of `*` -- catalog-data
        filler skip list, matched case-insensitively as whole values,
        whatever their length."""
        data = self._run()["filler_survival"]
        for name, case in data.items():
            self.assertTrue(case["unchanged"], f"{name}: {case['text']!r}")

    def test_lookalike_keys_and_headers_are_never_mistaken_for_secrets(self):
        data = self._run()["lookalike_survival"]
        for name, case in data.items():
            self.assertTrue(case["unchanged"], f"{name}: {case['text']!r}")

    def test_a_hub_signature_header_with_a_trailing_digit_segment_is_redacted(self):
        """`X-Hub-Signature-256` -- GitHub's real webhook-signature header
        shape, the suffix followed by `-256`. Must still be redacted, with
        the variable name derived from the full header name."""
        data = self._run()["hub_signature_256"]
        self.assertTrue(data["valueGone"], data["text"])
        self.assertTrue(data["usesDerivedName"], data["text"])

    def test_a_signature_header_with_a_different_trailing_digit_segment_is_redacted(self):
        data = self._run()["signature_512"]
        self.assertTrue(data["valueGone"], data["text"])
        self.assertTrue(data["usesDerivedName"], data["text"])

    def test_an_unrelated_leading_key_never_swallows_a_real_sensitive_pair(self):
        """`note: password=<fake>` -- a review-found regression: the bare
        unquoted pass used to consume the whole remainder as `note`'s own
        (rejected) value, hiding the sensitive `password=` pair inside it."""
        data = self._run()["unrelated_prefix_note"]
        self.assertTrue(data["valueGone"], data["text"])

    def test_an_unrelated_header_name_never_swallows_a_real_sensitive_pair(self):
        """`Content-Type: password=<fake>` -- same regression, with a
        hyphenated header name as the unrelated leading key."""
        data = self._run()["unrelated_prefix_content_type"]
        self.assertTrue(data["valueGone"], data["text"])

    def test_a_cookie_token_is_redacted_and_a_later_attribute_survives(self):
        """`Set-Cookie: token=<fake>; Path=/` -- the sensitive pair is
        redacted and `Path=/`, which follows it, is left untouched."""
        data = self._run()["set_cookie_token"]
        self.assertTrue(data["valueGone"], data["text"])
        self.assertTrue(data["pathPreserved"], data["text"])

    def test_a_url_query_token_is_redacted_and_the_next_param_survives(self):
        """`?token=<fake>&page=2` -- a review-found regression: `&` and `?`
        were not excluded from `key_context.unquoted_value_pattern`, so the
        value swallowed the rest of the query string and deleted it."""
        data = self._run()["url_query_token"]
        self.assertTrue(data["valueGone"], data["text"])
        self.assertTrue(data["pageParamPreserved"], data["text"])

    def test_pathological_inputs_stay_well_under_one_second(self):
        """Two review-found quadratic-time hazards, fixed together in
        7.3.1: the bare unquoted key-context pass (a rejected leading key's
        value scan ran to the end of the string; a long identifier run with
        no separator backtracked at every position) and
        `url_credentials.pattern` (a long scheme-class run with no `://`
        did the same). Both are now anchored with a lookbehind instead of
        an unanchored repeated class, and a `max_detect_bytes` catalog cap
        (256 KiB) is a second, independent safety net for whatever
        pathological shape this fix did not anticipate. Every case here
        must finish comfortably under 1s; the actual timings are printed
        for the record (some of these inputs are also over the cap, so they
        exercise the cheap fallback path, not the fixed regexes directly --
        see `test_the_over_the_cap_path_still_redacts_a_known_value` and
        the smaller under-cap timings a manual benchmark confirmed
        separately for the regexes themselves)."""
        data = self._run()["performance"]
        for name, case in data.items():
            print(f"perf: {name} ({case['length']} chars) -> {case['ms']:.1f}ms")
            self.assertLess(case["ms"], 1000, f"{name} took {case['ms']:.1f}ms")

    def test_the_over_the_cap_path_still_redacts_a_known_value(self):
        """Beyond `max_detect_bytes`, the expensive detection passes are
        skipped, but a value already registered (from an earlier, small
        message) must still be redacted via the cheap exact-match fallback
        -- never blocked, never silently left in the clear."""
        data = self._run()["over_cap_still_redacts_known_value"]
        self.assertTrue(data["valueGone"])
        self.assertTrue(data["usesSameVariable"])


if __name__ == "__main__":
    unittest.main()
