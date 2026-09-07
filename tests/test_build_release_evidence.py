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
    BUILD_INSTALLER_ASSET_NAME,
    BUILD_INSTALLER_PATH,
    BUILD_ZIPAPP_ASSET_NAME,
    BUILD_ZIPAPP_PATH,
    artifact_evidence,
    build_installer_evidence,
    build_zipapp_evidence,
    digest,
    install_sh_evidence,
    tagged_file,
)
from build_zipapp import build  # noqa: E402

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "zipapp_source"
FIXTURE_IDENTITY = Path(__file__).resolve().parent / "fixtures" / "zipapp_source_identity.json"
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
        build(FIXTURE_ROOT, self.artifact, FIXTURE_IDENTITY)

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
        build(FIXTURE_ROOT, artifact_path, FIXTURE_IDENTITY)

        artifact = artifact_evidence(artifact_path, FIXTURE_VERSION)
        install_sh = install_sh_evidence(commit, root=self.repo)
        assets = [artifact, install_sh]

        self.assertEqual({asset["name"] for asset in assets}, {"pegasus", "install.sh"})
        self.assertEqual(
            install_sh["sha256"],
            hashlib.sha256(tagged_file(commit, "install.sh", root=self.repo)).hexdigest(),
        )


class BuildZipappEvidenceTest(unittest.TestCase):
    """Certifying `tools/build_zipapp.py` itself as a release asset, the same shape as
    `install.sh` -- the builder must be obtainable from the release without cloning the engine."""

    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.repo = Path(self._directory.name)
        _init_repo(self.repo)

    def test_certifies_build_zipapp_bytes_from_the_commit(self):
        tool_path = self.repo / BUILD_ZIPAPP_PATH
        tool_path.parent.mkdir(parents=True, exist_ok=True)
        tool_path.write_text("#!/usr/bin/env python3\nprint('builder')\n", encoding="utf-8")
        commit = _commit_all(self.repo, "add build_zipapp.py")

        evidence = build_zipapp_evidence(commit, root=self.repo)

        self.assertEqual(evidence["name"], BUILD_ZIPAPP_ASSET_NAME)
        self.assertEqual(evidence["sha256"], digest(tool_path))

    def test_rejects_a_commit_with_no_build_zipapp(self):
        (self.repo / "pyproject.toml").write_text("[project]\nversion = \"1.0.0\"\n", encoding="utf-8")
        commit = _commit_all(self.repo, "no build_zipapp.py here")

        with self.assertRaises(ValueError) as raised:
            build_zipapp_evidence(commit, root=self.repo)

        self.assertIn(BUILD_ZIPAPP_PATH, str(raised.exception))

    def test_rejects_a_working_tree_build_zipapp_that_differs_from_the_committed_one(self):
        tool_path = self.repo / BUILD_ZIPAPP_PATH
        tool_path.parent.mkdir(parents=True, exist_ok=True)
        tool_path.write_text("#!/usr/bin/env python3\nprint('committed')\n", encoding="utf-8")
        commit = _commit_all(self.repo, "add build_zipapp.py")
        committed_sha256 = hashlib.sha256(tagged_file(commit, BUILD_ZIPAPP_PATH, root=self.repo)).hexdigest()
        tool_path.write_text("#!/usr/bin/env python3\nprint('tampered')\n", encoding="utf-8")
        worktree_sha256 = digest(tool_path)

        with self.assertRaises(ValueError) as raised:
            build_zipapp_evidence(commit, root=self.repo)

        message = str(raised.exception)
        self.assertIn(worktree_sha256, message)
        self.assertIn(committed_sha256, message)

    def test_manifest_assets_list_carries_all_three_files(self):
        """The end-to-end shape `main()` writes: `assets` names all three files this release ships."""
        (self.repo / "install.sh").write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
        tool_path = self.repo / BUILD_ZIPAPP_PATH
        tool_path.parent.mkdir(parents=True, exist_ok=True)
        tool_path.write_text("#!/usr/bin/env python3\nprint('builder')\n", encoding="utf-8")
        commit = _commit_all(self.repo, "add install.sh and build_zipapp.py")
        artifact_dir = tempfile.TemporaryDirectory()
        self.addCleanup(artifact_dir.cleanup)
        artifact_path = Path(artifact_dir.name) / "pegasus"
        build(FIXTURE_ROOT, artifact_path, FIXTURE_IDENTITY)

        artifact = artifact_evidence(artifact_path, FIXTURE_VERSION)
        install_sh = install_sh_evidence(commit, root=self.repo)
        build_zipapp = build_zipapp_evidence(commit, root=self.repo)
        assets = [artifact, install_sh, build_zipapp]

        self.assertEqual(
            {asset["name"] for asset in assets}, {"pegasus", "install.sh", BUILD_ZIPAPP_ASSET_NAME}
        )


class BuildInstallerEvidenceTest(unittest.TestCase):
    """Certifying `tools/build_installer.py` itself as a release asset, the same shape as
    `build_zipapp.py` -- a distribution needs no source checkout to generate its own install.sh."""

    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.repo = Path(self._directory.name)
        _init_repo(self.repo)

    def test_certifies_build_installer_bytes_from_the_commit(self):
        tool_path = self.repo / BUILD_INSTALLER_PATH
        tool_path.parent.mkdir(parents=True, exist_ok=True)
        tool_path.write_text("#!/usr/bin/env python3\nprint('installer builder')\n", encoding="utf-8")
        commit = _commit_all(self.repo, "add build_installer.py")

        evidence = build_installer_evidence(commit, root=self.repo)

        self.assertEqual(evidence["name"], BUILD_INSTALLER_ASSET_NAME)
        self.assertEqual(evidence["sha256"], digest(tool_path))

    def test_rejects_a_commit_with_no_build_installer(self):
        (self.repo / "pyproject.toml").write_text("[project]\nversion = \"1.0.0\"\n", encoding="utf-8")
        commit = _commit_all(self.repo, "no build_installer.py here")

        with self.assertRaises(ValueError) as raised:
            build_installer_evidence(commit, root=self.repo)

        self.assertIn(BUILD_INSTALLER_PATH, str(raised.exception))

    def test_rejects_a_working_tree_build_installer_that_differs_from_the_committed_one(self):
        tool_path = self.repo / BUILD_INSTALLER_PATH
        tool_path.parent.mkdir(parents=True, exist_ok=True)
        tool_path.write_text("#!/usr/bin/env python3\nprint('committed')\n", encoding="utf-8")
        commit = _commit_all(self.repo, "add build_installer.py")
        committed_sha256 = hashlib.sha256(tagged_file(commit, BUILD_INSTALLER_PATH, root=self.repo)).hexdigest()
        tool_path.write_text("#!/usr/bin/env python3\nprint('tampered')\n", encoding="utf-8")
        worktree_sha256 = digest(tool_path)

        with self.assertRaises(ValueError) as raised:
            build_installer_evidence(commit, root=self.repo)

        message = str(raised.exception)
        self.assertIn(worktree_sha256, message)
        self.assertIn(committed_sha256, message)

    def test_manifest_assets_list_carries_all_four_files(self):
        """The end-to-end shape `main()` writes: `assets` now names four files this release ships."""
        (self.repo / "install.sh").write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
        zipapp_path = self.repo / BUILD_ZIPAPP_PATH
        zipapp_path.parent.mkdir(parents=True, exist_ok=True)
        zipapp_path.write_text("#!/usr/bin/env python3\nprint('zipapp builder')\n", encoding="utf-8")
        installer_path = self.repo / BUILD_INSTALLER_PATH
        installer_path.parent.mkdir(parents=True, exist_ok=True)
        installer_path.write_text("#!/usr/bin/env python3\nprint('installer builder')\n", encoding="utf-8")
        commit = _commit_all(self.repo, "add install.sh, build_zipapp.py and build_installer.py")
        artifact_dir = tempfile.TemporaryDirectory()
        self.addCleanup(artifact_dir.cleanup)
        artifact_path = Path(artifact_dir.name) / "pegasus"
        build(FIXTURE_ROOT, artifact_path, FIXTURE_IDENTITY)

        artifact = artifact_evidence(artifact_path, FIXTURE_VERSION)
        install_sh = install_sh_evidence(commit, root=self.repo)
        build_zipapp = build_zipapp_evidence(commit, root=self.repo)
        build_installer = build_installer_evidence(commit, root=self.repo)
        assets = [artifact, install_sh, build_zipapp, build_installer]

        self.assertEqual(
            {asset["name"] for asset in assets},
            {"pegasus", "install.sh", BUILD_ZIPAPP_ASSET_NAME, BUILD_INSTALLER_ASSET_NAME},
        )


if __name__ == "__main__":
    unittest.main()
