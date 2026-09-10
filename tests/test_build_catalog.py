"""Tests for tools/build_catalog.py.

`build_catalog.py` is step one of the manual release procedure
(`docs/release-distribution.md`). It once broke silently -- `catalog.build`'s
signature grew a required `identity` argument and nothing caught the mismatch
until the tool crashed with `TypeError: build() missing 1 required positional
argument: 'identity'`. These tests actually run the script via subprocess
(never just import it) and then mirror its call to `catalog.build` in-process,
computing the expected digest independently. If the tool's call shape ever
drifts from the library's again, the mirrored digest stops matching the
printed one and this test fails -- it does not merely assert exit code 0.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "build_catalog.py"

sys.path.insert(0, str(ROOT / "src"))

from pegasus.adapters import available  # noqa: E402
from pegasus.cli import default_identity  # noqa: E402
from pegasus.core import catalog as catalog_module  # noqa: E402
from pegasus.core import content as content_module  # noqa: E402


def _expected_digest(cli: str) -> str:
    """The digest an in-process call to `catalog.build` produces for `cli`.

    Deliberately reconstructs the exact call the tool is supposed to make --
    the packaged content, the named adapter, and the packaged identity -- so
    this stays independent of whatever `tools/build_catalog.py` actually does
    internally.
    """
    registry = available()
    catalog = catalog_module.build(content_module.load(), registry.get(cli), default_identity())
    return catalog.digest


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True
    )


class BuildCatalogSummaryTest(unittest.TestCase):
    """`--summary` prints counts and the digest -- the shape this mirror test relies on."""

    def test_runs_successfully_for_the_default_cli(self):
        result = _run("--summary")
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_the_printed_digest_matches_catalog_build_called_in_process(self):
        """The mirror: if `catalog.build`'s signature or behavior changes and the tool
        is not updated to match, the digest computed here and the digest printed by
        the subprocess diverge and this assertion fails."""
        result = _run("--cli", "opencode", "--summary")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        lines = result.stdout.strip().splitlines()
        printed_digest = lines[-1].strip()
        self.assertEqual(printed_digest, _expected_digest("opencode"))

    def test_works_for_every_registered_cli_not_just_the_default(self):
        registry = available()
        for cli in registry.ids():
            with self.subTest(cli=cli):
                result = _run("--cli", cli, "--summary")
                self.assertEqual(result.returncode, 0, msg=result.stderr)
                printed_digest = result.stdout.strip().splitlines()[-1].strip()
                self.assertEqual(printed_digest, _expected_digest(cli))


class BuildCatalogFullOutputTest(unittest.TestCase):
    """Without `--summary`, the tool prints (or writes) the full catalog document."""

    def test_stdout_carries_a_catalog_whose_recomputed_digest_matches(self):
        result = _run("--cli", "opencode")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["cli"], "opencode")
        # Recompute the digest the same way `Catalog.digest` does, over the
        # exact document the tool printed -- proves the printed JSON is not
        # merely well-formed but actually the catalog this build shape produces.
        registry = available()
        catalog = catalog_module.build(content_module.load(), registry.get("opencode"), default_identity())
        self.assertEqual(payload, catalog.as_dict())

    def test_writes_to_out_when_given_and_reports_a_matching_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "catalog.json"
            result = _run("--cli", "opencode", "--out", str(out))
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertTrue(out.is_file())
            payload = json.loads(out.read_text(encoding="utf-8"))
            expected_digest = _expected_digest("opencode")
            self.assertIn(expected_digest, result.stdout)
            registry = available()
            catalog = catalog_module.build(content_module.load(), registry.get("opencode"), default_identity())
            self.assertEqual(payload, catalog.as_dict())


class BuildCatalogArgumentsTest(unittest.TestCase):
    """The `--cli` flag is restricted to registered adapters -- no silent typo acceptance."""

    def test_rejects_an_unknown_cli(self):
        result = _run("--cli", "not-a-real-cli", "--summary")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--cli", result.stderr)


if __name__ == "__main__":
    unittest.main()
