"""Document pointer navigation: the engine's only way to address configuration."""
from __future__ import annotations

import unittest

from pegasus.core import pointer


class ParseTest(unittest.TestCase):
    def test_empty_pointer_addresses_the_root(self):
        self.assertEqual(pointer.parse(""), ())

    def test_tokens_split_on_slash(self):
        self.assertEqual(pointer.parse("/agent/sdd-apply/model"), ("agent", "sdd-apply", "model"))

    def test_escaped_tokens_are_decoded(self):
        self.assertEqual(pointer.parse("/a~1b/c~0d"), ("a/b", "c~d"))

    def test_empty_token_is_a_valid_key(self):
        self.assertEqual(pointer.parse("/"), ("",))

    def test_pointer_without_leading_slash_is_rejected(self):
        with self.assertRaises(pointer.PointerError):
            pointer.parse("agent/sdd-apply")

    def test_build_is_the_inverse_of_parse(self):
        for value in ("", "/agent", "/agent/sdd-apply/model", "/a~1b/c~0d", "/"):
            self.assertEqual(pointer.build(pointer.parse(value)), value)


class GetTest(unittest.TestCase):
    def setUp(self):
        self.document = {"agent": {"sdd-apply": {"model": "anthropic/sonnet"}}, "plugin": ["a", "b"]}

    def test_reads_a_nested_value(self):
        self.assertEqual(pointer.get_at(self.document, "/agent/sdd-apply/model"), "anthropic/sonnet")

    def test_reads_an_array_item(self):
        self.assertEqual(pointer.get_at(self.document, "/plugin/1"), "b")

    def test_empty_pointer_returns_the_document(self):
        self.assertIs(pointer.get_at(self.document, ""), self.document)

    def test_missing_key_returns_the_default(self):
        self.assertIsNone(pointer.get_at(self.document, "/agent/missing/model"))
        self.assertEqual(pointer.get_at(self.document, "/nope", "fallback"), "fallback")

    def test_out_of_range_index_returns_the_default(self):
        self.assertIsNone(pointer.get_at(self.document, "/plugin/9"))

    def test_descending_into_a_scalar_returns_the_default(self):
        self.assertIsNone(pointer.get_at(self.document, "/agent/sdd-apply/model/deeper"))

    def test_exists_distinguishes_absent_from_null(self):
        document = {"key": None}
        self.assertTrue(pointer.exists_at(document, "/key"))
        self.assertFalse(pointer.exists_at(document, "/other"))


class SetTest(unittest.TestCase):
    def test_writes_a_single_field_without_touching_siblings(self):
        document = {"agent": {"sdd-apply": {"description": "keep me"}}}
        result = pointer.set_at(document, "/agent/sdd-apply/model", "anthropic/sonnet")
        self.assertEqual(
            result["agent"]["sdd-apply"], {"description": "keep me", "model": "anthropic/sonnet"}
        )

    def test_does_not_mutate_the_input_document(self):
        document = {"agent": {}}
        pointer.set_at(document, "/agent/sdd-apply", {"mode": "subagent"})
        self.assertEqual(document, {"agent": {}})

    def test_creates_missing_parents(self):
        result = pointer.set_at({}, "/agent/sdd-apply/model", "x")
        self.assertEqual(result, {"agent": {"sdd-apply": {"model": "x"}}})

    def test_overwrites_an_existing_value(self):
        result = pointer.set_at({"share": "enabled"}, "/share", "disabled")
        self.assertEqual(result, {"share": "disabled"})

    def test_replaces_an_array_item_by_index(self):
        result = pointer.set_at({"plugin": ["a", "b"]}, "/plugin/0", "z")
        self.assertEqual(result["plugin"], ["z", "b"])

    def test_appends_to_an_array_with_the_dash_token(self):
        result = pointer.set_at({"plugin": ["a"]}, "/plugin/-", "b")
        self.assertEqual(result["plugin"], ["a", "b"])

    def test_numeric_token_creates_a_list_parent(self):
        result = pointer.set_at({}, "/plugin/-", "a")
        self.assertEqual(result, {"plugin": ["a"]})

    def test_root_cannot_be_replaced(self):
        with self.assertRaises(pointer.PointerError):
            pointer.set_at({}, "", "x")

    def test_writing_through_a_scalar_is_rejected(self):
        with self.assertRaises(pointer.PointerError):
            pointer.set_at({"share": "disabled"}, "/share/nested", "x")

    def test_index_beyond_the_end_is_rejected(self):
        with self.assertRaises(pointer.PointerError):
            pointer.set_at({"plugin": ["a"]}, "/plugin/7", "z")


class UnsetTest(unittest.TestCase):
    def test_removes_a_leaf(self):
        result = pointer.unset_at({"agent": {"a": 1, "b": 2}}, "/agent/a")
        self.assertEqual(result, {"agent": {"b": 2}})

    def test_prunes_containers_left_empty(self):
        result = pointer.unset_at({"mcp": {"engram": {"type": "local"}}}, "/mcp/engram")
        self.assertEqual(result, {})

    def test_stops_pruning_at_the_first_non_empty_ancestor(self):
        document = {"mcp": {"engram": {"type": "local"}}, "share": "disabled"}
        self.assertEqual(pointer.unset_at(document, "/mcp/engram"), {"share": "disabled"})

    def test_keeps_ancestors_that_still_hold_siblings(self):
        document = {"mcp": {"engram": {"a": 1}, "cbm": {"b": 2}}}
        self.assertEqual(pointer.unset_at(document, "/mcp/engram"), {"mcp": {"cbm": {"b": 2}}})

    def test_removing_an_absent_pointer_is_a_no_op(self):
        document = {"agent": {"a": 1}}
        self.assertEqual(pointer.unset_at(document, "/agent/missing"), document)
        self.assertEqual(pointer.unset_at(document, "/nope/deep"), document)

    def test_does_not_mutate_the_input_document(self):
        document = {"agent": {"a": 1}}
        pointer.unset_at(document, "/agent/a")
        self.assertEqual(document, {"agent": {"a": 1}})

    def test_removes_an_array_item(self):
        self.assertEqual(pointer.unset_at({"plugin": ["a", "b"]}, "/plugin/0"), {"plugin": ["b"]})

    def test_root_cannot_be_removed(self):
        with self.assertRaises(pointer.PointerError):
            pointer.unset_at({}, "")


if __name__ == "__main__":
    unittest.main()
