"""Tests for the artifact evidence in tools/build_release_evidence.py.

Only `artifact_evidence` is exercised here: it is the one piece of this tool's logic that does not
require a real annotated tag to drive (`resolve_commit`, `package_version_at`) or a real wheel/shim
pair from a prior distribution shape. It runs the artifact it is given, exactly the way a person
verifying a release would, so the fixture built by `tools/build_zipapp.py` is a real thing to run
rather than a stand-in for one.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from build_release_evidence import (  # noqa: E402
    artifact_evidence,
    digest,
    install_sh_evidence,
    tagged_file,
)
from build_zipapp import build  # noqa: E402

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "zipapp_source"
FIXTURE_VERSION = "9.9.9-fixture"


def _run_git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, text=True, capture_output=True, check=True
    ).stdout.strip()


def _init_repo(root: Path) -> None:
    """A throwaway git repository, isolated from the real repo's config and identity."""
    _run_git("init", "-q", cwd=root)
    _run_git("config", "user.name", "Release Evidence Test", cwd=root)
    _run_git("config", "user.email", "release-evidence-test@example.invalid", cwd=root)


def _commit_all(root: Path, message: str) -> str:
    _run_git("add", "-A", cwd=root)
    _run_git("commit", "-q", "-m", message, cwd=root)
    return _run_git("rev-parse", "HEAD", cwd=root)


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


class InstallShEvidenceTest(unittest.TestCase):
    """`install_sh_evidence` against throwaway repositories, never the real one.

    Each test builds its own git repository under a temp directory and passes it as `root`, so
    none of this ever runs `git` against the actual pegasus-harness checkout.
    """

    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.repo = Path(self._directory.name)
        _init_repo(self.repo)

    def test_certifies_install_sh_bytes_from_the_commit(self):
        (self.repo / "install.sh").write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
        commit = _commit_all(self.repo, "add install.sh")

        evidence = install_sh_evidence(commit, root=self.repo)

        self.assertEqual(evidence["name"], "install.sh")
        self.assertEqual(evidence["sha256"], digest(self.repo / "install.sh"))

    def test_rejects_a_commit_with_no_install_sh(self):
        (self.repo / "pyproject.toml").write_text("[project]\nversion = \"1.0.0\"\n", encoding="utf-8")
        commit = _commit_all(self.repo, "no install.sh here")

        with self.assertRaises(ValueError) as raised:
            install_sh_evidence(commit, root=self.repo)

        self.assertIn(
            "releases/latest/download/install.sh", str(raised.exception),
            "the refusal must name the advertised one-liner that breaks without install.sh",
        )

    def test_rejects_a_working_tree_install_sh_that_differs_from_the_committed_one(self):
        (self.repo / "install.sh").write_text("#!/bin/sh\necho committed\n", encoding="utf-8")
        commit = _commit_all(self.repo, "add install.sh")
        committed_sha256 = hashlib.sha256(tagged_file(commit, "install.sh", root=self.repo)).hexdigest()
        (self.repo / "install.sh").write_text("#!/bin/sh\necho tampered\n", encoding="utf-8")
        worktree_sha256 = digest(self.repo / "install.sh")

        with self.assertRaises(ValueError) as raised:
            install_sh_evidence(commit, root=self.repo)

        message = str(raised.exception)
        self.assertIn(worktree_sha256, message)
        self.assertIn(committed_sha256, message)

    def test_manifest_assets_list_carries_both_the_artifact_and_install_sh(self):
        """The end-to-end shape `main()` writes: `assets` names both files this release ships."""
        (self.repo / "install.sh").write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
        commit = _commit_all(self.repo, "add install.sh")
        artifact_dir = tempfile.TemporaryDirectory()
        self.addCleanup(artifact_dir.cleanup)
        artifact_path = Path(artifact_dir.name) / "pegasus"
        build(FIXTURE_ROOT, artifact_path)

        artifact = artifact_evidence(artifact_path, FIXTURE_VERSION)
        install_sh = install_sh_evidence(commit, root=self.repo)
        assets = [artifact, install_sh]

        self.assertEqual({asset["name"] for asset in assets}, {"pegasus", "install.sh"})
        self.assertEqual(
            install_sh["sha256"],
            hashlib.sha256(tagged_file(commit, "install.sh", root=self.repo)).hexdigest(),
        )


if __name__ == "__main__":
    unittest.main()
