"""The OpenCode skill-registry writer keeps `.atl/` out of `git status`.

It writes `.atl/skill-registry.md` into the project root; unless the project
ignores that directory, every repository shows `?? .atl/` and the parallel
delivery procedure's clean-tree check stops on it. The writer adds the line to
the repository's local exclude file, never to `.gitignore`.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSET = ROOT / "src" / "pegasus" / "adapters" / "opencode" / "assets" / "skill-registry" / "skill_registry.py"
GIT = shutil.which("git")


def git(*arguments: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *arguments], cwd=cwd, text=True, capture_output=True, check=True)


@unittest.skipUnless(GIT, "git is required")
class RegistryExcludeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name).resolve()
        self.script = self.workspace / "skill_registry.py"
        text = ASSET.read_text(encoding="utf-8").replace("{{display_name}}", "Test").replace("{{program_name}}", "test")
        self.script.write_text(text, encoding="utf-8")
        self.skills = self.workspace / "skills"
        (self.skills / "alpha").mkdir(parents=True)
        (self.skills / "alpha" / "SKILL.md").write_text("---\nname: alpha\ndescription: An alpha skill\n---\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def repository(self, name: str = "repo") -> Path:
        path = self.workspace / name
        path.mkdir()
        git("init", "-q", cwd=path)
        git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "--allow-empty", "-m", "base", cwd=path)
        return path

    def run_registry(self, project: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(self.script), "--project-root", str(project), "--skill-root", str(self.skills)],
            text=True, capture_output=True, check=False,
        )

    def exclude_lines(self, project: Path) -> list[str]:
        out = git("rev-parse", "--git-path", "info/exclude", cwd=project).stdout.strip()
        path = Path(out) if Path(out).is_absolute() else project / out
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    def test_the_line_is_added_and_git_status_is_clean(self) -> None:
        project = self.repository()
        done = self.run_registry(project)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stderr, "")
        self.assertEqual(self.exclude_lines(project).count(".atl/"), 1)
        self.assertEqual(git("status", "--porcelain", cwd=project).stdout, "")
        self.assertFalse((project / ".gitignore").exists())

    def test_a_git_dir_in_the_environment_does_not_redirect_the_exclude(self) -> None:
        project = self.repository()
        other = self.repository("other")
        before = self.exclude_lines(other)
        environment = {**os.environ, "GIT_DIR": str(other / ".git")}
        done = subprocess.run([sys.executable, str(self.script), "--project-root", str(project), "--skill-root", str(self.skills)], text=True, capture_output=True, check=False, env=environment)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.exclude_lines(project).count(".atl/"), 1)
        self.assertEqual(self.exclude_lines(other), before)

    def test_a_second_run_does_not_duplicate_it(self) -> None:
        project = self.repository()
        self.run_registry(project)
        self.assertEqual(self.run_registry(project).returncode, 0)
        self.assertEqual(self.exclude_lines(project).count(".atl/"), 1)

    def test_an_existing_ignore_line_is_respected(self) -> None:
        for existing in (".atl/", ".atl", "/.atl/"):
            with self.subTest(existing=existing):
                project = self.repository(f"repo{existing.strip('/.')}{len(existing)}")
                exclude = project / ".git" / "info" / "exclude"
                exclude.parent.mkdir(exist_ok=True)
                exclude.write_text(f"# local\n{existing}\n", encoding="utf-8")
                self.assertEqual(self.run_registry(project).returncode, 0)
                self.assertEqual(exclude.read_text(encoding="utf-8"), f"# local\n{existing}\n")

    def test_a_missing_trailing_newline_is_kept_apart(self) -> None:
        project = self.repository()
        exclude = project / ".git" / "info" / "exclude"
        exclude.parent.mkdir(exist_ok=True)
        exclude.write_text("build/", encoding="utf-8")
        self.run_registry(project)
        self.assertEqual(exclude.read_text(encoding="utf-8"), "build/\n.atl/\n")

    def test_a_missing_info_directory_is_created(self) -> None:
        project = self.repository()
        shutil.rmtree(project / ".git" / "info", ignore_errors=True)
        self.assertEqual(self.run_registry(project).returncode, 0)
        self.assertEqual(self.exclude_lines(project).count(".atl/"), 1)

    def test_a_linked_worktree_uses_the_resolved_exclude_file(self) -> None:
        main = self.repository("main")
        linked = self.workspace / "linked"
        git("worktree", "add", "-q", "-b", "side", str(linked), cwd=main)
        self.assertTrue((linked / ".git").is_file())
        done = self.run_registry(linked)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stderr, "")
        self.assertEqual(git("status", "--porcelain", cwd=linked).stdout, "")
        self.assertEqual(self.exclude_lines(linked).count(".atl/"), 1)

    def test_a_directory_outside_git_gets_no_exclude_and_no_error(self) -> None:
        project = self.workspace / "plain"
        project.mkdir()
        done = self.run_registry(project)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stderr, "")
        self.assertTrue((project / ".atl" / "skill-registry.md").is_file())
        self.assertFalse((project / ".git").exists())

    def test_an_unwritable_exclude_target_only_warns_once(self) -> None:
        project = self.repository()
        exclude = project / ".git" / "info" / "exclude"
        exclude.parent.mkdir(exist_ok=True)
        exclude.unlink(missing_ok=True)
        exclude.mkdir()
        done = self.run_registry(project)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stderr.count("could not exclude"), 1)
        self.assertTrue((project / ".atl" / "skill-registry.md").is_file())


if __name__ == "__main__":
    unittest.main()
