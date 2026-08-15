"""One convention for every reference a skill makes to another skill file.

While the procedure was copied into each agent prompt, a reference was decoration:
nobody followed it, so a broken or ambiguous one cost nothing. Lazy loading makes
the agent follow it at runtime. A reference that does not resolve becomes a dead
end in the middle of a task, and a reference whose form differs per skill forces a
bespoke resolution rule in every agent prompt instead of one shared rule.

The convention: every reference to a file inside the skills tree is written
relative to the skills root, so `_shared/sdd-phase-common.md` and
`sdd-apply/strict-tdd.md` mean the same thing no matter which skill wrote them.
An agent prompt can then carry a single sentence -- resolve against the skills
root -- rather than one paragraph per phase.

Project artifacts are not skill files. `tasks.md` and `design.md` live in the
change being worked on, never under the skills root, so they are named here and
excluded. Anything that is neither a listed project artifact nor a resolvable
skills-root path is an offender.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[1] / "src" / "pegasus" / "content" / "skills"

REFERENCE = re.compile(r"`([^`\n]+\.md)`")

#: A reference the reader is meant to resolve in the project, not under the skills root.
PROJECT_ARTIFACTS = frozenset(
    {
        "SKILL.md",
        "AGENTS.md",
        "agents.md",
        "CLAUDE.md",
        "GEMINI.md",
        "README.md",
        "copilot-instructions.md",
        "context.md",
        "handoff.md",
        "exploration.md",
        "proposal.md",
        "design.md",
        "tasks.md",
        "spec.md",
        "verify-report.md",
    }
)

#: Directories that only ever appear in the project being worked on. A skill cannot
#: ship the consuming repository's `docs/`, so a reference into it is never ours.
PROJECT_PREFIXES = ("openspec/", ".atl/", ".github/", "docs/")

#: A reference written as an example rather than a path to follow.
PLACEHOLDERS = ("{", "<", "*")


def skill_documents() -> list[Path]:
    return sorted(path for path in SKILLS.rglob("*.md") if "__pycache__" not in path.parts)


def references(document: Path) -> list[tuple[int, str]]:
    return [
        (number, match.group(1))
        for number, line in enumerate(document.read_text(encoding="utf-8").splitlines(), start=1)
        for match in REFERENCE.finditer(line)
    ]


def is_project_artifact(reference: str) -> bool:
    return reference in PROJECT_ARTIFACTS or reference.startswith(PROJECT_PREFIXES)


def is_example(reference: str) -> bool:
    return any(token in reference for token in PLACEHOLDERS)


def offenders() -> list[str]:
    found = []
    for document in skill_documents():
        for number, reference in references(document):
            if is_project_artifact(reference) or is_example(reference):
                continue
            if not (SKILLS / reference).is_file():
                found.append(f"{document.relative_to(SKILLS)}:{number} -> {reference}")
    return found


class SkillReferencesResolveTest(unittest.TestCase):
    def test_documents_are_scanned(self):
        """Without this, the test below would pass by finding nothing to check."""
        self.assertTrue(skill_documents(), "no markdown found under content/skills")

    def test_references_are_found(self):
        """A regex that matches nothing would make every skill look compliant."""
        total = sum(len(references(document)) for document in skill_documents())
        self.assertGreater(total, 100, "the reference pattern stopped matching")

    def test_every_skill_reference_resolves_from_the_skills_root(self):
        found = offenders()
        self.assertEqual(
            found,
            [],
            "these references do not resolve against the skills root:\n" + "\n".join(found),
        )


if __name__ == "__main__":
    unittest.main()
