"""The seam that lets one body be installed by every adapter.

A content body is written once and installed everywhere, so it cannot name a
path: `/home/someone/.config/opencode/skills` is one product, one machine, one
user. It names a fact instead, and the adapter answers from its own layout.

These tests fix two halves of that contract. The core owns the vocabulary and
refuses a name it does not know, while there is still a file to blame. The
adapter owns the answers and refuses to guess when its layout has none.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pegasus.core import content as content_module
from pegasus.core import placeholders

AGENT = """---
name: sdd-apply
description: Implementation executor
mode: subagent
---

# SDD Apply

Your first tool call must read {body}.
"""


class VocabularyTest(unittest.TestCase):
    def test_the_vocabulary_is_not_empty(self):
        """Without this, every test below would pass by having nothing to know."""
        self.assertTrue(placeholders.NAMES)

    def test_no_two_facts_differ_only_by_case(self):
        """Verbatim content is gated case-insensitively and bodies are not.

        Two names that fold together would be one fact to a skill and two to an
        agent, which is a contradiction nobody would find by reading either rule.
        """
        folded = {name.casefold() for name in placeholders.NAMES}
        self.assertEqual(len(folded), len(placeholders.NAMES))

    def test_finds_each_placeholder_once_in_order(self):
        body = "read {{skills_root}}/a then {{skills_root}}/b"
        self.assertEqual(placeholders.names_in(body), ("skills_root",))

    def test_a_body_without_placeholders_uses_none(self):
        self.assertEqual(placeholders.names_in("plain prose about {braces}"), ())

    def test_single_braces_are_left_to_the_prose(self):
        """`{change-name}` is something the model fills in, not the installer."""
        self.assertEqual(placeholders.names_in("write {change-name}/tasks.md"), ())

    def test_surrounding_space_does_not_make_a_different_name(self):
        self.assertEqual(placeholders.names_in("{{ skills_root }}"), ("skills_root",))

    def test_a_name_outside_the_vocabulary_is_reported(self):
        self.assertEqual(placeholders.unknown_in("{{skils_root}}"), ("skils_root",))

    def test_a_known_name_is_not_reported(self):
        self.assertEqual(placeholders.unknown_in("{{skills_root}}"), ())


class FillTest(unittest.TestCase):
    def test_every_occurrence_is_answered(self):
        filled = placeholders.fill("{{skills_root}}/a and {{skills_root}}/b", {"skills_root": "/r"})
        self.assertEqual(filled, "/r/a and /r/b")

    def test_a_body_with_nothing_to_fill_comes_back_unchanged(self):
        self.assertEqual(placeholders.fill("plain {prose}", {}), "plain {prose}")

    def test_an_unanswered_placeholder_names_itself(self):
        with self.assertRaises(KeyError) as raised:
            placeholders.fill("{{skills_root}}", {})
        self.assertIn("skills_root", str(raised.exception))


class LoadTimeRefusalTest(unittest.TestCase):
    """A typo here would ship verbatim into a loading gate and die mid-task."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "agents").mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def write(self, body: str) -> None:
        (self.root / "agents" / "sdd-apply.md").write_text(AGENT.format(body=body), encoding="utf-8")

    def test_a_known_placeholder_loads(self):
        self.write("{{skills_root}}/sdd-apply/SKILL.md")
        agent = content_module.load(self.root).agents[0]
        self.assertIn("{{skills_root}}", agent.body)

    def test_an_unknown_placeholder_is_refused_with_the_file_named(self):
        self.write("{{skils_root}}/sdd-apply/SKILL.md")
        with self.assertRaises(content_module.ContentError) as raised:
            content_module.load(self.root)
        message = str(raised.exception)
        self.assertIn("agents/sdd-apply.md", message)
        self.assertIn("skils_root", message)


class MalformedDelimiterTest(unittest.TestCase):
    """A brace pair the pattern cannot read is the very thing this module prevents."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "agents").mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def write(self, body: str) -> None:
        (self.root / "agents" / "sdd-apply.md").write_text(AGENT.format(body=body), encoding="utf-8")

    def test_an_unclosed_opener_is_refused(self):
        self.write("{{ oops then {{skills_root}}/x")
        with self.assertRaises(content_module.ContentError):
            content_module.load(self.root)

    def test_a_nested_brace_is_refused(self):
        self.write("{{{skills_root}}}")
        with self.assertRaises(content_module.ContentError):
            content_module.load(self.root)

    def test_a_well_formed_body_is_not_accused(self):
        self.write("{{skills_root}}/a and {{skills_root}}/b")
        self.assertTrue(content_module.load(self.root).agents)

    def test_ordinary_nested_prose_is_left_alone(self):
        """This content is prompts about a JSON-configured CLI. `}}` is how prose ends."""
        for body in ('{"agent": {"mode": "subagent"}}', "x = {'a': {'b': 1}}", "jq '.a|{b:{c:1}}'"):
            with self.subTest(body=body):
                self.write(body)
                self.assertTrue(content_module.load(self.root).agents)


class SkillsAreVerbatimTest(unittest.TestCase):
    """A skill is copied byte for byte, so a fact it asks for is never answered."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.skill = self.root / "skills" / "probe"
        self.skill.mkdir(parents=True)

    def tearDown(self):
        self.temporary.cleanup()

    def write(self, name: str, text: str) -> None:
        (self.skill / name).write_text(text, encoding="utf-8")

    def descriptor(self, extra: str = "") -> None:
        self.write("SKILL.md", f"---\nname: probe\ndescription: A probe\n---\n\n# Probe\n{extra}\n")

    def test_a_skill_asking_for_a_fact_is_refused_with_the_file_named(self):
        self.descriptor("Cross-reference: read {{skills_root}}/other/SKILL.md.")
        with self.assertRaises(content_module.ContentError) as raised:
            content_module.load(self.root)
        message = str(raised.exception)
        self.assertIn("SKILL.md", message)
        self.assertIn("skills_root", message)

    def test_a_reference_file_is_checked_too(self):
        self.descriptor()
        self.write("notes.md", "read {{skills_root}}/other/SKILL.md")
        with self.assertRaises(content_module.ContentError) as raised:
            content_module.load(self.root)
        self.assertIn("notes.md", str(raised.exception))

    def test_a_fact_cannot_be_smuggled_by_changing_its_case(self):
        self.descriptor("read {{SKILLS_ROOT}}/other/SKILL.md")
        with self.assertRaises(content_module.ContentError):
            content_module.load(self.root)

    def test_a_skill_is_held_to_the_same_delimiters_as_a_body(self):
        self.descriptor("read {{{skills_root}}}/other/SKILL.md")
        with self.assertRaises(content_module.ContentError):
            content_module.load(self.root)

    def test_braces_that_belong_to_another_language_are_left_alone(self):
        """A shipped Laravel checklist uses `{{ }}` for Blade, and that is not ours."""
        self.descriptor()
        self.write("blade.md", "Escape output with {{ $value }} in Blade templates.")
        self.assertTrue(content_module.load(self.root).skills)


if __name__ == "__main__":
    unittest.main()
