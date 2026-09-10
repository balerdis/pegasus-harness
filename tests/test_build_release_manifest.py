"""Tests for tools/build_release_manifest.py.

This tool reproduces the release evidence for the already-published `v3.1.x`
tags, reading their sources with `git show <tag>:path` rather than off the
current working tree (`docs/release-distribution.md` explains why: `install.sh`
and the bundled CBM dependency are no longer tracked at HEAD). Every git
operation here is local -- no network is ever touched, on any code path.

Argument-validation tests run the real script by subprocess against this
repository's own history: several `v3.1.x` tags already exist locally, so the
regex/argparse/annotated-tag checks all run for real, no fixtures needed. The
one thing the real repo cannot exercise is the successful build path: the
curated CBM dependency archive those tags reference
(`dependencies/codebase-memory-mcp-v0.9.0-linux-x86_64.tar.gz`) is no longer
present in the working tree (only inside the old tag's git object, which the
script deliberately does not read the dependency bytes from -- see
`curated_cbm`). Reaching the full success path -- and the final-tag
promotion path -- is therefore covered against a small synthetic git
repository built in a temp directory, with the module's `ROOT` constant
monkeypatched to point at it. No file is ever written under the real repo.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "build_release_manifest.py"

sys.path.insert(0, str(ROOT / "tools"))

import build_release_manifest as brm  # noqa: E402


def _has_tag(tag: str) -> bool:
    """Whether ``tag`` really exists in this checkout's git history.

    True against a normal clone, where the `v3.1.x` release tags are already
    there; false against a `git archive` export or any other checkout that
    carries the tree but not the tag objects, where the one test that needs
    the real tag to exist would otherwise fail for a reason that has nothing
    to do with the tool under test.
    """
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", tag],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True
    )


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _init_repo(root: Path) -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "commit.gpgsign", "false")


def _write_common_release_files(root: Path) -> bytes:
    """Everything a non-final synthetic release commit needs to build clean."""
    (root / "install.sh").write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    (root / "install.sh").chmod(0o755)

    dependency_bytes = b"fake-cbm-binary-bytes"
    dependency_sha256 = hashlib.sha256(dependency_bytes).hexdigest()
    build_command = "scripts/build.sh --version v0.0.0"

    manifests = root / "manifests"
    manifests.mkdir(exist_ok=True)
    (manifests / "cbm-linux-x64-provenance.json").write_text(
        json.dumps({
            "artifact_sha256": dependency_sha256,
            "build_command": build_command,
            "build_command_sha256": hashlib.sha256(build_command.encode("utf-8")).hexdigest(),
        }),
        encoding="utf-8",
    )
    (manifests / "release-contract.json").write_text(
        json.dumps({
            "schema": "pegasus-harness-release-contract/v3",
            "version": "3.1.0",
            "dependencies": [
                {"id": "cbm", "source_url": "release-bundle:dependencies/fake-cbm.tar.gz"},
            ],
        }),
        encoding="utf-8",
    )
    (manifests / "artifact-catalog.json").write_text(json.dumps({"schema": "test"}), encoding="utf-8")

    dependencies = root / "dependencies"
    dependencies.mkdir(exist_ok=True)
    (dependencies / "fake-cbm.tar.gz").write_bytes(dependency_bytes)
    return dependency_bytes


class ArgumentValidationAgainstRealRepoTest(unittest.TestCase):
    """Validation paths that run entirely before the tool touches the CBM
    dependency, so they can be exercised against this real repository and its
    real, already-published `v3.1.x` tags -- no fixtures, no network."""

    def test_missing_required_arguments_is_an_argparse_error(self):
        result = _run()
        self.assertEqual(result.returncode, 2)
        self.assertIn("--tag", result.stderr)
        self.assertIn("--archive", result.stderr)
        self.assertIn("--output", result.stderr)

    def test_a_tag_matching_neither_the_final_nor_rc_shape_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            result = _run(
                "--tag", "v9.9.9",
                "--archive", str(Path(directory) / "a.tar.gz"),
                "--output", str(Path(directory) / "o.json"),
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("--tag must be v3.1.1 or an RC tag", result.stderr)

    def test_the_final_tag_without_its_required_promotion_rc_tag_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            result = _run(
                "--tag", "v3.1.1",
                "--archive", str(Path(directory) / "a.tar.gz"),
                "--output", str(Path(directory) / "o.json"),
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("v3.1.1 requires --promotion-rc-tag v3.1.1-rc.1", result.stderr)

    def test_an_rc_tag_is_not_allowed_to_carry_a_promotion_rc_tag(self):
        with tempfile.TemporaryDirectory() as directory:
            result = _run(
                "--tag", "v3.1.1-rc.1",
                "--promotion-rc-tag", "v3.1.1-rc.1",
                "--archive", str(Path(directory) / "a.tar.gz"),
                "--output", str(Path(directory) / "o.json"),
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("--promotion-rc-tag is valid only for v3.1.1", result.stderr)

    def test_an_existing_archive_path_is_refused_before_any_building_starts(self):
        """This tag (`v3.1.1-rc.1`) really exists in this repo's history, so the
        check reaches the archive-exists guard -- which runs before the tool
        would need the now-absent CBM dependency bytes."""
        if not _has_tag("v3.1.1-rc.1"):
            self.skipTest("v3.1.1-rc.1 is not present in this checkout's git history (e.g. a tarball export)")
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "already-here.tar.gz"
            archive.write_bytes(b"not really an archive")
            result = _run(
                "--tag", "v3.1.1-rc.1",
                "--archive", str(archive),
                "--output", str(Path(directory) / "o.json"),
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("--archive must name a new source archive", result.stderr)


class SyntheticRepositorySuccessPathTest(unittest.TestCase):
    """The full build, evidence, and manifest-writing path, exercised against a
    throwaway git repository rather than this one -- `ROOT` is monkeypatched
    for the duration of each test and restored in `tearDown`."""

    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.repo = Path(self._directory.name) / "repo"
        self.repo.mkdir()
        self._original_root = brm.ROOT
        self.addCleanup(setattr, brm, "ROOT", self._original_root)
        brm.ROOT = self.repo

    def _call(self, *args: str) -> int:
        original_argv = sys.argv
        sys.argv = ["build_release_manifest.py", *args]
        try:
            return brm.main()
        finally:
            sys.argv = original_argv

    def test_a_release_candidate_tag_builds_a_matching_archive_and_manifest(self):
        _init_repo(self.repo)
        _write_common_release_files(self.repo)
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "synthetic rc release")
        _git(self.repo, "tag", "-a", "v3.1.0-rc.1", "-m", "rc")

        archive = Path(self._directory.name) / "out" / "archive.tar.gz"
        output = Path(self._directory.name) / "out" / "manifest.json"
        exit_code = self._call(
            "--tag", "v3.1.0-rc.1", "--archive", str(archive), "--output", str(output),
        )

        self.assertEqual(exit_code, 0)
        self.assertTrue(archive.is_file())
        checksum = archive.with_name(archive.name + ".sha256")
        self.assertTrue(checksum.is_file())
        self.assertIn(hashlib.sha256(archive.read_bytes()).hexdigest(), checksum.read_text(encoding="utf-8"))

        payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema"], "pegasus-harness-release/v3")
        self.assertEqual(payload["tag"], "v3.1.0-rc.1")
        self.assertNotIn("release_kind", payload)  # only the final build sets this
        self.assertEqual(
            payload["curated_dependencies"],
            [{
                "id": "cbm",
                "path": "dependencies/fake-cbm.tar.gz",
                "sha256": hashlib.sha256(b"fake-cbm-binary-bytes").hexdigest(),
                "provenance": "manifests/cbm-linux-x64-provenance.json",
            }],
        )

    def test_the_final_tag_requires_and_records_its_promotion_and_documentation_evidence(self):
        _init_repo(self.repo)
        _write_common_release_files(self.repo)
        for name, text in (
            ("README.md", "readme"),
            ("INSTALL.md", "install"),
            ("INSTALL_BY_AGENT.md", "install by agent"),
            ("MANUAL.md", "manual"),
        ):
            (self.repo / name).write_text(text, encoding="utf-8")
        (self.repo / "docs").mkdir()
        (self.repo / "docs" / "release-distribution.md").write_text("dist", encoding="utf-8")

        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "synthetic final release")
        _git(self.repo, "tag", "-a", "v3.1.1-rc.1", "-m", "promoted rc")
        _git(self.repo, "tag", "-a", "v3.1.1", "-m", "final")

        archive = Path(self._directory.name) / "out" / "archive.tar.gz"
        output = Path(self._directory.name) / "out" / "manifest.json"
        exit_code = self._call(
            "--tag", "v3.1.1",
            "--promotion-rc-tag", "v3.1.1-rc.1",
            "--archive", str(archive),
            "--output", str(output),
        )

        self.assertEqual(exit_code, 0)
        payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(payload["release_kind"], "final")
        self.assertEqual(payload["promotion_rc_tag"], "v3.1.1-rc.1")
        documented_paths = {entry["path"] for entry in payload["documentation_evidence"]}
        self.assertEqual(
            documented_paths,
            {"README.md", "INSTALL.md", "INSTALL_BY_AGENT.md", "MANUAL.md", "docs/release-distribution.md"},
        )
        self.assertEqual(
            payload["published_assets"],
            [archive.name, archive.name + ".sha256", output.name],
        )

    def test_a_tampered_curated_dependency_checksum_is_refused(self):
        """The mismatch this tool exists to catch: a bundled dependency archive
        whose bytes no longer match its own recorded provenance checksum."""
        _init_repo(self.repo)
        _write_common_release_files(self.repo)
        # Corrupt the dependency bytes after the provenance file already
        # recorded the honest checksum.
        (self.repo / "dependencies" / "fake-cbm.tar.gz").write_bytes(b"tampered bytes")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "synthetic tampered release")
        _git(self.repo, "tag", "-a", "v3.1.0-rc.2", "-m", "rc")

        archive = Path(self._directory.name) / "out" / "archive.tar.gz"
        output = Path(self._directory.name) / "out" / "manifest.json"
        # `parser.error(...)` calls `sys.exit(2)` directly -- the same
        # mechanism the real script relies on via `raise SystemExit(main())`.
        with self.assertRaises(SystemExit) as raised:
            self._call("--tag", "v3.1.0-rc.2", "--archive", str(archive), "--output", str(output))
        self.assertEqual(raised.exception.code, 2)
        self.assertFalse(archive.exists())


if __name__ == "__main__":
    unittest.main()
