"""Tests for the artifact evidence in tools/build_release_evidence.py.

Only `artifact_evidence` is exercised here: it is the one piece of this tool's logic that does not
require a real annotated tag to drive (`resolve_commit`, `package_version_at`) or a real wheel/shim
pair from a prior distribution shape. It runs the artifact it is given, exactly the way a person
verifying a release would, so the fixture built by `tools/build_zipapp.py` is a real thing to run
rather than a stand-in for one.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from build_release_evidence import artifact_evidence  # noqa: E402
from build_zipapp import build  # noqa: E402

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "zipapp_source"
FIXTURE_VERSION = "9.9.9-fixture"


class ArtifactEvidenceTest(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.artifact = Path(self._directory.name) / "pegasus"
        build(FIXTURE_ROOT, self.artifact)

    def test_evidences_an_artifact_whose_reported_version_matches(self):
        evidence = artifact_evidence(self.artifact, FIXTURE_VERSION)
        self.assertEqual(evidence["name"], "pegasus")
        self.assertEqual(len(evidence["sha256"]), 64)

    def test_rejects_a_version_mismatch(self):
        with self.assertRaises(ValueError):
            artifact_evidence(self.artifact, "1.0.0")

    def test_rejects_an_artifact_not_named_pegasus(self):
        renamed = self.artifact.with_name("pegasus-renamed")
        self.artifact.rename(renamed)
        with self.assertRaises(ValueError):
            artifact_evidence(renamed, FIXTURE_VERSION)

    def test_rejects_an_artifact_that_is_not_executable(self):
        self.artifact.chmod(0o644)
        with self.assertRaises(ValueError):
            artifact_evidence(self.artifact, FIXTURE_VERSION)


if __name__ == "__main__":
    unittest.main()
