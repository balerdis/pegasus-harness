"""Codec guarantees: stable digests and no collateral damage to user files."""
from __future__ import annotations

import json
import unittest

from pegasus.core import codecs
from pegasus.core.types import Codec


class JsonCodecTest(unittest.TestCase):
    def test_round_trip_preserves_content(self):
        document = {"agent": {"sdd-apply": {"model": "anthropic/sonnet"}}, "share": "disabled"}
        self.assertEqual(codecs.loads(Codec.JSON, codecs.dumps(Codec.JSON, document)), document)

    def test_dumps_preserves_the_authors_key_order(self):
        document = {"zeta": 1, "alpha": 2, "mu": 3}
        self.assertEqual(list(codecs.loads(Codec.JSON, codecs.dumps(Codec.JSON, document))), ["zeta", "alpha", "mu"])

    def test_dumps_is_indented_and_newline_terminated(self):
        rendered = codecs.dumps(Codec.JSON, {"a": {"b": 1}})
        self.assertTrue(rendered.endswith("\n"))
        self.assertIn('\n  "a"', rendered)

    def test_dumps_keeps_non_ascii_readable(self):
        self.assertIn("ó", codecs.dumps(Codec.JSON, {"k": "versión"}))

    def test_loads_rejects_malformed_input(self):
        with self.assertRaises(codecs.CodecError):
            codecs.loads(Codec.JSON, "{not json")


class CanonicalBytesTest(unittest.TestCase):
    def test_key_order_does_not_change_the_digest_input(self):
        self.assertEqual(
            codecs.canonical_bytes({"a": 1, "b": 2}), codecs.canonical_bytes({"b": 2, "a": 1})
        )

    def test_different_values_produce_different_bytes(self):
        self.assertNotEqual(codecs.canonical_bytes({"a": 1}), codecs.canonical_bytes({"a": 2}))

    def test_output_is_compact(self):
        self.assertEqual(codecs.canonical_bytes({"b": 1, "a": 2}), b'{"a":2,"b":1}')

    def test_nested_structures_are_sorted_at_every_level(self):
        self.assertEqual(
            codecs.canonical_bytes({"x": {"b": 1, "a": 2}}), codecs.canonical_bytes({"x": {"a": 2, "b": 1}})
        )

    def test_is_independent_of_any_codec(self):
        """A digest describes the value, not the file format that carries it."""
        value = {"command": ["/usr/bin/engram", "mcp"]}
        self.assertEqual(codecs.canonical_bytes(value), json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


class UnsupportedCodecTest(unittest.TestCase):
    def test_toml_is_declared_but_not_implemented(self):
        for call in (lambda: codecs.loads(Codec.TOML, ""), lambda: codecs.dumps(Codec.TOML, {})):
            with self.assertRaises(NotImplementedError):
                call()

    def test_yaml_is_declared_but_not_implemented(self):
        for call in (lambda: codecs.loads(Codec.YAML, ""), lambda: codecs.dumps(Codec.YAML, {})):
            with self.assertRaises(NotImplementedError):
                call()

    def test_the_message_names_the_codec(self):
        with self.assertRaises(NotImplementedError) as raised:
            codecs.dumps(Codec.TOML, {})
        self.assertIn("toml", str(raised.exception).lower())


if __name__ == "__main__":
    unittest.main()
