"""7.3.0: `engram.ts` calls the secret-transport plugin's process-wide
redaction global before POSTing a prompt or a passive-capture body, in
addition to its own `stripPrivateTags`. Driven under Node against the real
plugins, in both import orders, since plugin load order across files is not
guaranteed (see `arquitectura.md`'s 7.3.0 section)."""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGRAM = ROOT / "src/pegasus/adapters/opencode/assets/plugins/engram.ts"
SECRET_TRANSPORT = ROOT / "src/pegasus/adapters/opencode/assets/plugins/secret-transport.ts"
CATALOG = ROOT / "src/pegasus/content/security/credential-transport-catalog.json"
HARNESS = ROOT / "tests/fixtures/engram_credential_redaction_harness.mjs"


class EngramCredentialRedactionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if shutil.which("node") is None:
            raise unittest.SkipTest("node is not installed — cannot run the plugin harness")

    def _run(self, order: str) -> dict:
        result = subprocess.run(
            ["node", "--experimental-strip-types", str(HARNESS), str(ENGRAM), str(SECRET_TRANSPORT), str(CATALOG), order],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"harness failed ({order}):\nstdout: {result.stdout}\nstderr: {result.stderr}",
        )
        return json.loads(result.stdout)

    def _assert_no_fake_value_posted(self, order: str):
        data = self._run(order)
        token = data["fakeToken"]
        posts = data["posts"]
        prompt_posts = [p for p in posts if p["url"].endswith("/prompts")]
        passive_posts = [p for p in posts if p["url"].endswith("/observations/passive")]
        self.assertTrue(prompt_posts, f"no /prompts POST captured ({order})")
        self.assertTrue(passive_posts, f"no /observations/passive POST captured ({order})")
        for post in prompt_posts + passive_posts:
            self.assertNotIn(token, post["body"]["content"], f"{order}: {post}")

    def test_secret_transport_loaded_first(self):
        self._assert_no_fake_value_posted("secret-first")

    def test_engram_loaded_first(self):
        self._assert_no_fake_value_posted("engram-first")


class EngramBoundaryTest(unittest.TestCase):
    """Ordering and size limits of the plugin's own posts, under Node."""

    @classmethod
    def setUpClass(cls):
        if shutil.which("node") is None:
            raise unittest.SkipTest("node is not installed — cannot run the plugin harness")
        result = subprocess.run(
            [
                "node",
                "--experimental-strip-types",
                str(ROOT / "tests/fixtures/engram_boundary_harness.mjs"),
                str(ENGRAM),
                str(SECRET_TRANSPORT),
                str(CATALOG),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, result.stderr
        cls.data = json.loads(result.stdout)

    def test_a_secret_straddling_the_prompt_limit_is_redacted_before_the_cut(self):
        self.assertEqual(len(self.data["straddling"]), 10)
        for content in self.data["straddling"]:
            self.assertNotIn("ghp_", content)

    def test_a_prompt_above_the_detection_cap_is_cut_and_redacted(self):
        (content,) = self.data["oversizedPrompt"]
        self.assertNotIn("ghp_", content)
        self.assertNotIn(self.data["oversizedSecret"][4:], content)
        self.assertLessEqual(len(content), 2003)

    def test_a_cut_inside_a_multibyte_character_does_not_skip_redaction(self):
        for name, cases in self.data["multibyte"].items():
            for case in cases:
                with self.subTest(padding=name, pad=case["pad"]):
                    (content,) = case["posted"]
                    self.assertNotIn("ghp_", content)
                    self.assertNotIn(case["secret"][4:], content)

    def test_a_passive_capture_above_the_detection_cap_is_not_posted(self):
        self.assertEqual(self.data["oversizedPassive"], 0)

    def test_many_unclosed_private_tags_are_linear(self):
        self.assertLess(self.data["unclosedMs"], 1000)

    def test_requests_opt_out_of_the_proxy_environment(self):
        self.assertEqual(self.data["proxyOptions"], [False])


if __name__ == "__main__":
    unittest.main()
