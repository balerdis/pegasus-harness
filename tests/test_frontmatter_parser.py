"""The frontmatter parser: exactly the shapes shipped content actually uses, nothing else.

Not a general-purpose format parser. Every shape it accepts is one measured across the
shipped descriptors (bare/quoted strings, booleans, flow-style lists, and one level of
block-style mapping nesting); everything else is refused loudly, naming the source and
the offending line, rather than silently guessed at.
"""
from __future__ import annotations

import unittest

from pegasus.core import frontmatter


class ScalarTest(unittest.TestCase):
    def test_parses_bare_string(self):
        self.assertEqual(frontmatter.parse("name: context7\n", "<test>"), {"name": "context7"})

    def test_parses_quoted_string(self):
        self.assertEqual(
            frontmatter.parse('package: "@playwright/mcp"\n', "<test>"),
            {"package": "@playwright/mcp"},
        )

    def test_quoted_string_may_contain_a_colon(self):
        self.assertEqual(
            frontmatter.parse('description: "Trigger: do the thing, then stop."\n', "<test>"),
            {"description": "Trigger: do the thing, then stop."},
        )

    def test_bare_string_may_contain_a_colon(self):
        self.assertEqual(
            frontmatter.parse("checksum: sha256:abc123\n", "<test>"),
            {"checksum": "sha256:abc123"},
        )

    def test_bare_string_with_url_and_slashes(self):
        self.assertEqual(
            frontmatter.parse("endpoint: https://example.com/a/b\n", "<test>"),
            {"endpoint": "https://example.com/a/b"},
        )

    def test_parses_true(self):
        self.assertEqual(frontmatter.parse("model_configurable: true\n", "<test>"), {"model_configurable": True})

    def test_parses_false(self):
        self.assertEqual(frontmatter.parse("user-invocable: false\n", "<test>"), {"user-invocable": False})

    def test_key_may_contain_a_dash(self):
        self.assertEqual(frontmatter.parse("disable-model-invocation: true\n", "<test>"), {"disable-model-invocation": True})


class FlowListTest(unittest.TestCase):
    def test_parses_flow_list_of_strings(self):
        self.assertEqual(
            frontmatter.parse("requires_tools: [read, bash, grep]\n", "<test>"),
            {"requires_tools": ["read", "bash", "grep"]},
        )

    def test_parses_single_item_flow_list(self):
        self.assertEqual(frontmatter.parse("requires_tools: [read]\n", "<test>"), {"requires_tools": ["read"]})

    def test_parses_empty_flow_list(self):
        self.assertEqual(frontmatter.parse("archive_members: []\n", "<test>"), {"archive_members": []})


class NestedMappingTest(unittest.TestCase):
    def test_parses_one_level_mapping(self):
        text = "metadata:\n  author: gentleman-programming\n  version: \"1.0\"\n"
        self.assertEqual(
            frontmatter.parse(text, "<test>"),
            {"metadata": {"author": "gentleman-programming", "version": "1.0"}},
        )

    def test_nested_mapping_may_contain_a_boolean(self):
        text = "metadata:\n  author: pegasus-balerdis\n  version: \"3.0\"\n  delegate_only: true\n"
        self.assertEqual(
            frontmatter.parse(text, "<test>"),
            {"metadata": {"author": "pegasus-balerdis", "version": "3.0", "delegate_only": True}},
        )


class MultiFieldTest(unittest.TestCase):
    def test_parses_a_full_descriptor(self):
        text = (
            "name: king-pegasus\n"
            "description: The teaching-architect voice\n"
            "mode: primary\n"
            "requires_tools: [read]\n"
            "model_configurable: true\n"
        )
        self.assertEqual(
            frontmatter.parse(text, "<test>"),
            {
                "name": "king-pegasus",
                "description": "The teaching-architect voice",
                "mode": "primary",
                "requires_tools": ["read"],
                "model_configurable": True,
            },
        )

    def test_empty_document_is_an_empty_mapping(self):
        self.assertEqual(frontmatter.parse("", "<test>"), {})

    def test_blank_lines_are_ignored(self):
        self.assertEqual(frontmatter.parse("name: x\n\n\ndescription: y\n", "<test>"), {"name": "x", "description": "y"})


class RefusalTest(unittest.TestCase):
    """Anything not among the measured shapes is refused loudly, at load time."""

    def test_refuses_a_line_with_no_colon(self):
        with self.assertRaises(frontmatter.FrontmatterError) as ctx:
            frontmatter.parse("just some text\n", "servers/foo.md")
        message = str(ctx.exception)
        self.assertIn("servers/foo.md", message)
        self.assertIn("1", message)

    def test_refuses_and_reports_the_correct_line_number(self):
        with self.assertRaises(frontmatter.FrontmatterError) as ctx:
            frontmatter.parse("name: ok\ndescription: also ok\nbroken line\n", "servers/foo.md")
        message = str(ctx.exception)
        self.assertIn("servers/foo.md", message)
        self.assertIn("3", message)

    def test_refuses_an_integer_value(self):
        with self.assertRaises(frontmatter.FrontmatterError):
            frontmatter.parse("count: 3\n", "<test>")

    def test_refuses_a_null_value(self):
        with self.assertRaises(frontmatter.FrontmatterError):
            frontmatter.parse("value: null\n", "<test>")

    def test_refuses_a_flow_mapping(self):
        with self.assertRaises(frontmatter.FrontmatterError):
            frontmatter.parse("metadata: {author: x, version: y}\n", "<test>")

    def test_refuses_a_list_of_mappings(self):
        with self.assertRaises(frontmatter.FrontmatterError):
            frontmatter.parse("items:\n  - name: a\n  - name: b\n", "<test>")

    def test_refuses_a_yaml_anchor(self):
        with self.assertRaises(frontmatter.FrontmatterError):
            frontmatter.parse("base: &anchor\n  x: 1\nother: *anchor\n", "<test>")

    def test_refuses_a_document_that_is_not_a_mapping(self):
        with self.assertRaises(frontmatter.FrontmatterError):
            frontmatter.parse("- a\n- b\n", "<test>")

    def test_refuses_an_unterminated_quoted_string(self):
        with self.assertRaises(frontmatter.FrontmatterError):
            frontmatter.parse('name: "unterminated\n', "<test>")

    def test_refuses_deeper_than_one_level_of_nesting(self):
        text = "metadata:\n  nested:\n    deep: 1\n"
        with self.assertRaises(frontmatter.FrontmatterError):
            frontmatter.parse(text, "<test>")

    def test_error_message_names_the_source_file(self):
        with self.assertRaises(frontmatter.FrontmatterError) as ctx:
            frontmatter.parse("weird\n", "skills/example/SKILL.md")
        self.assertIn("skills/example/SKILL.md", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
