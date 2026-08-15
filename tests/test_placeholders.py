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


if __name__ == "__main__":
    unittest.main()
