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

What this gate does not see, all deliberate:

- Only markdown targets, so a broken reference to `assets/template.py` is invisible.
- Absolute paths and URLs are dropped whole. This is the only honest option -- a rule
  anchored to our skills root cannot judge a path anchored somewhere else -- but it is
  a real blind spot, and it falls on the form that matters most here:
  `_shared/skill-resolver.md` prescribes injecting `/absolute/path/to/skills/<name>/
  SKILL.md` into a sub-agent's prompt. Those are paths into a skills root; this test
  simply cannot tell which one.
- `skills/` is banned on every line. Right for a skill-to-skill reference, and it is
  what caught the prefix hiding inside a `{placeholder}`, but it would also reject a
  shell example or a sentence about a project-local skills directory.
- Every bare filename a skill mentions in prose must now be a listed project artifact.
  Mentioning `notes.md` in passing would fail until the name is added here, so the
  list has to stay reasoned rather than padded to fit the tree.
- A blockquote written `>text` without a space swallows the `>` into the token and
  fails a reference that is otherwise correct. Nothing in the tree writes them that way.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from pegasus.core import content as content_module

SKILLS = Path(__file__).resolve().parents[1] / "src" / "pegasus" / "content" / "skills"

#: Any path that names a markdown file, in whatever syntax. Gating only inline code
#: and link targets certifies the forms that were scanned rather than the tree: an
#: agent follows a path written bare in prose, inside a fenced diagram, or as a link
#: label just as readily.
#: The lookbehind refuses to start mid-path, which also drops absolute paths and URLs
#: whole. See the blind spot that creates, above.
REFERENCE = re.compile(r"(?<![\w/.{}<>-])[\w.{}<>-]+(?:/[\w.{}<>-]+)*\.md")

#: The dead convention. Nothing under the skills root has a `skills/` directory, so a
#: surviving prefix is always the old config-root form, even where no filename follows
#: it. A path continues into a name or a placeholder; `skills/*` is a shell glob.
DEAD_PREFIX = re.compile(r"(?<![\w/-])skills/[\w{<]")

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
        "pr-body.md",
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
        (number, match.group(0))
        for number, line in enumerate(document.read_text(encoding="utf-8").splitlines(), start=1)
        for match in REFERENCE.finditer(line)
    ]


def is_project_artifact(reference: str) -> bool:
    return reference in PROJECT_ARTIFACTS or reference.startswith(PROJECT_PREFIXES)


def is_example(reference: str) -> bool:
    return any(token in reference for token in PLACEHOLDERS)


def rendered_not_shipped() -> set[str]:
    """A server's convention resolves to nothing here on purpose.

    It is not a shipped asset but a file rendered from the server's own
    descriptor body at install time, so it exists on disk only once that
    server is selected. Derived from the shipped servers rather than listed,
    so a second server needs nobody to remember it here -- see the identical
    exclusion in `test_cbm_convention.py`'s `AgentPointerResolutionTest`.
    """
    return {
        str(content_module.mcp_convention_path(server.name))
        for server in content_module.load().mcp
    }


def offenders() -> list[str]:
    found = []
    excluded = rendered_not_shipped()
    for document in skill_documents():
        for number, reference in references(document):
            if is_project_artifact(reference) or is_example(reference):
                continue
            if reference in excluded:
                continue
            if not (SKILLS / reference).is_file():
                found.append(f"{document.relative_to(SKILLS)}:{number} -> {reference}")
    return found


class SkillReferencesResolveTest(unittest.TestCase):
    def test_documents_are_scanned(self):
        """Without this, the test below would pass by finding nothing to check."""
        self.assertTrue(skill_documents(), "no markdown found under content/skills")

    def test_references_are_found(self):
        """A canary against narrowing, not just against total breakage.

        The threshold sits just under the current count on purpose. Gating by syntax
        again -- inline code and link targets only -- yields about 206 matches, so a
        floor of 100 would let that regression through silently.
        """
        total = sum(len(references(document)) for document in skill_documents())
        self.assertGreater(total, 240, "the reference pattern narrowed")

    def test_every_skill_reference_resolves_from_the_skills_root(self):
        found = offenders()
        self.assertEqual(
            found,
            [],
            "these references do not resolve against the skills root:\n" + "\n".join(found),
        )

    def test_no_document_keeps_the_dead_config_root_prefix(self):
        """The resolution test cannot see prose or examples; this one can.

        A `skills/` prefix always meant "relative to the CLI config root". It is the
        convention this tree replaced, and it survives in places the reference scan
        skips: plain prose, and examples holding a `{placeholder}`.
        """
        found = [
            f"{document.relative_to(SKILLS)}:{number} -> {line.strip()}"
            for document in skill_documents()
            for number, line in enumerate(
                document.read_text(encoding="utf-8").splitlines(), start=1
            )
            if DEAD_PREFIX.search(line)
        ]
        self.assertEqual(
            found,
            [],
            "the config-root `skills/` prefix is the replaced convention:\n" + "\n".join(found),
        )


if __name__ == "__main__":
    unittest.main()
