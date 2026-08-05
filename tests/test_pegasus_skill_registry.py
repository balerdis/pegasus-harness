from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
import os
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import pegasus_skill_registry as registry  # noqa: E402


class PegasusSkillRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name)
        self.project = self.workspace / "project"
        self.project.mkdir()
        self.root_one = self.workspace / "skills-one"
        self.root_two = self.workspace / "skills-two"
        fixtures = ROOT / "tests" / "fixtures"
        shutil.copytree(fixtures / "skills-one", self.root_one)
        shutil.copytree(fixtures / "skills-two", self.root_two)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_generator(self, *roots: Path) -> subprocess.CompletedProcess[str]:
        roots = roots or (self.root_one, self.root_two)
        arguments = [str(ROOT / "tools" / "pegasus-skill-registry"), "--project-root", str(self.project)]
        for root in roots:
            arguments.extend(["--skill-root", str(root)])
        return subprocess.run(
            arguments,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_multiple_roots_nested_discovery_and_deterministic_output(self) -> None:
        first = self.run_generator()
        output = (self.project / ".atl" / "skill-registry.md").read_text()
        second = self.run_generator()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(output, (self.project / ".atl" / "skill-registry.md").read_text())
        self.assertIn("`alpha`", output)
        self.assertIn("`beta`", output)
        self.assertIn("`gamma`", output)
        self.assertLess(output.index("`alpha`"), output.index("`beta`"))
        self.assertLess(output.index("`beta`"), output.index("`gamma`"))
        self.assertIn("First \\| portable skill", output)

    def write_skill(self, root: Path, directory: str, name: str, description: str, *, malformed: bool = False) -> Path:
        path = root / directory / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        if malformed:
            path.write_text(f"---\nname: {name}\ndescription: {description}\n")
        else:
            path.write_text(f"---\nname: {name}\ndescription: {description}\n---\n")
        return path

    def test_project_duplicate_wins_when_user_root_is_listed_first(self) -> None:
        user = self.workspace / "user"
        project_skills = self.project / "skills"
        user_skill = self.write_skill(user, "shared", "duplicate", "user copy")
        project_skill = self.write_skill(project_skills, "shared", "duplicate", "project copy")
        completed = self.run_generator(user, project_skills)
        output = (self.project / ".atl" / "skill-registry.md").read_text()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn(f"project copy | project | `{project_skill}`", output)
        self.assertNotIn(f"user copy | user | `{user_skill}`", output)

    def test_project_duplicate_wins_when_project_root_is_listed_first(self) -> None:
        user = self.workspace / "user"
        project_skills = self.project / "skills"
        user_skill = self.write_skill(user, "shared", "duplicate", "user copy")
        project_skill = self.write_skill(project_skills, "shared", "duplicate", "project copy")
        completed = self.run_generator(project_skills, user)
        output = (self.project / ".atl" / "skill-registry.md").read_text()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn(f"project copy | project | `{project_skill}`", output)
        self.assertNotIn(f"user copy | user | `{user_skill}`", output)

    def test_same_scope_duplicate_uses_root_order_then_lexical_path(self) -> None:
        first = self.workspace / "first-user"
        second = self.workspace / "second-user"
        first_skill = self.write_skill(first, "z-first", "duplicate", "first root")
        self.write_skill(first, "a-later", "duplicate", "same root lexical winner")
        self.write_skill(second, "shared", "duplicate", "second root")
        completed = self.run_generator(first, second)
        output = (self.project / ".atl" / "skill-registry.md").read_text()
        expected = first / "a-later" / "SKILL.md"
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn(f"same root lexical winner | user | `{expected}`", output)
        self.assertNotIn(f"first root | user | `{first_skill}`", output)
        self.assertIn("duplicate name duplicate", completed.stderr)

    def test_malformed_project_duplicate_does_not_hide_valid_user_skill(self) -> None:
        user = self.workspace / "user"
        project_skills = self.project / "skills"
        user_skill = self.write_skill(user, "shared", "duplicate", "valid user copy")
        self.write_skill(project_skills, "shared", "duplicate", "broken project copy", malformed=True)
        completed = self.run_generator(project_skills, user)
        output = (self.project / ".atl" / "skill-registry.md").read_text()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("unterminated frontmatter", completed.stderr)
        self.assertIn(f"valid user copy | user | `{user_skill}`", output)

    def test_malformed_frontmatter_isolated_and_reported(self) -> None:
        completed = self.run_generator()
        output = (self.project / ".atl" / "skill-registry.md").read_text()
        self.assertEqual(completed.returncode, 0)
        self.assertIn("unterminated frontmatter", completed.stderr)
        self.assertNotIn("`invalid`", output)
        self.assertIn("`gamma`", output)

    def test_folded_yaml_description_is_parsed_without_a_yaml_dependency(self) -> None:
        skill = self.root_two / "folded" / "SKILL.md"
        skill.parent.mkdir()
        skill.write_text("---\nname: folded\ndescription: >\n  Folded frontmatter\n  remains supported\n---\n")
        fields, error = registry.parse_frontmatter(skill)
        self.assertIsNone(error)
        self.assertEqual(fields, {"name": "folded", "description": "Folded frontmatter remains supported"})

    def test_atomic_write_replaces_a_complete_temporary_file(self) -> None:
        target = self.workspace / "atomic" / "registry.md"
        original_replace = os.replace
        with patch.object(registry.os, "replace", side_effect=original_replace) as replace:
            registry.atomic_write(target, "complete\n")
            temporary, destination = replace.call_args.args
            self.assertEqual(destination, target)
        self.assertFalse(Path(temporary).exists())
        self.assertEqual(target.read_text(), "complete\n")
        self.assertFalse(list(target.parent.glob(".registry.md.*.tmp")))

    def test_production_files_and_output_have_no_external_dependency(self) -> None:
        completed = self.run_generator()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        forbidden = "gent" + "le-ai"
        production = [
            ROOT / "tools" / "pegasus_skill_registry.py",
            ROOT / "tools" / "pegasus-skill-registry",
            self.project / ".atl" / "skill-registry.md",
        ]
        for path in production:
            self.assertNotIn(forbidden, path.read_text().lower(), path)

if __name__ == "__main__":
    unittest.main()
