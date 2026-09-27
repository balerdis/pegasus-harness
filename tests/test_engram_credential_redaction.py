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


if __name__ == "__main__":
    unittest.main()
