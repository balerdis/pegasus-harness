"""Tests for tools/check_docs_links.py.

Everything this tool does is local: `git ls-files` against a repository
already on disk and plain filesystem existence checks. No network is ever
touched, so nothing here needs to be skipped or worked around.

`resolve()` is tested directly, unit-style, since it is the one piece of real
logic (the skills-root exception). `main()` is exercised two ways: once for
real, by subprocess, against this actual repository -- a genuine regression
check that today's tracked Markdown has no broken relative links -- and once
against a small synthetic git repository (with the module's `ROOT` and
`SKILLS_ROOT` monkeypatched) to prove a broken link is actually caught and
reported with a non-zero exit code, which the real repo's passing state alone
cannot demonstrate.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "check_docs_links.py"

sys.path.insert(0, str(ROOT / "tools"))

import check_docs_links as checker  # noqa: E402


def _run() -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


class ResolveTest(unittest.TestCase):
    """The one real branch: a link inside the skills tree resolves against the
    skills root; everywhere else it resolves against the linking file's own
    directory."""

    def setUp(self):
        self._original_skills_root = checker.SKILLS_ROOT
        self.addCleanup(setattr, checker, "SKILLS_ROOT", self._original_skills_root)

    def test_a_link_outside_the_skills_tree_resolves_against_its_own_directory(self):
        checker.SKILLS_ROOT = Path("/nonexistent/skills/root")
        linking_file = ROOT / "docs" / "some-doc.md"
        self.assertEqual(
            checker.resolve(linking_file, "other-doc.md"),
            ROOT / "docs" / "other-doc.md",
        )

    def test_a_link_inside_the_skills_tree_resolves_against_the_skills_root(self):
        skills_root = ROOT / "src" / "pegasus" / "content" / "skills"
        checker.SKILLS_ROOT = skills_root
        linking_file = skills_root / "some-skill" / "SKILL.md"
        self.assertEqual(
            checker.resolve(linking_file, "some-skill/reference.md"),
            skills_root / "some-skill" / "reference.md",
        )


class RealRepositoryRegressionTest(unittest.TestCase):
    """The tool actually run, for real, against this repository's own tracked
    Markdown. This is the regression check: today's docs must have no broken
    relative links."""

    def test_the_tracked_documentation_has_no_broken_relative_links(self):
        if not (ROOT / ".git").exists():
            self.skipTest("not a git checkout (e.g. a tarball export) -- `git ls-files` has nothing to read")
        result = _run()
        self.assertEqual(result.returncode, 0, msg=result.stdout)
        self.assertIn("PASS", result.stdout)


class SyntheticRepositoryFailureTest(unittest.TestCase):
    """A broken link must actually fail the check -- proven against a
    throwaway repository, since the real repository's passing state cannot
    demonstrate what happens when a link is broken."""

    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.repo = Path(self._directory.name)
        _git(self.repo, "init", "-q")
        _git(self.repo, "config", "user.email", "test@example.invalid")
        _git(self.repo, "config", "user.name", "Test")

        self._original_root = checker.ROOT
        self._original_skills_root = checker.SKILLS_ROOT
        self.addCleanup(setattr, checker, "ROOT", self._original_root)
        self.addCleanup(setattr, checker, "SKILLS_ROOT", self._original_skills_root)
        checker.ROOT = self.repo
        checker.SKILLS_ROOT = self.repo / "src" / "pegasus" / "content" / "skills"

    def _call(self) -> int:
        original_argv = sys.argv
        sys.argv = ["check_docs_links.py"]
        try:
            return checker.main()
        finally:
            sys.argv = original_argv

    def test_a_broken_relative_link_is_reported_and_fails(self):
        (self.repo / "doc.md").write_text("see [elsewhere](missing-target.md)\n", encoding="utf-8")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "synthetic doc with a broken link")

        exit_code = self._call()

        self.assertEqual(exit_code, 1)

    def test_a_resolvable_relative_link_passes(self):
        (self.repo / "doc.md").write_text("see [elsewhere](target.md)\n", encoding="utf-8")
        (self.repo / "target.md").write_text("target\n", encoding="utf-8")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "synthetic doc with a resolvable link")

        exit_code = self._call()

        self.assertEqual(exit_code, 0)

    def test_an_absolute_url_and_an_anchor_are_never_treated_as_broken_files(self):
        (self.repo / "doc.md").write_text(
            "see [web](https://example.invalid/page) and [here](#section) and [mail](mailto:a@b.invalid)\n",
            encoding="utf-8",
        )
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "synthetic doc with non-file links")

        exit_code = self._call()

        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
