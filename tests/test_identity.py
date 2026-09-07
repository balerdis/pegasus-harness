"""`identity.parse()`: the one place a distribution's name enters as data.

Pure: no filesystem, no package resources. Reading `identity.json` off disk or
out of a zipapp is the composition root's job (`cli.py`); this module only
ever receives bytes and either returns a fully valid `Identity` or raises.
"""
from __future__ import annotations

import json
import unittest

from pegasus.core import identity as module
from pegasus.core.identity import Identity, IdentityError, ReleaseSource


def document(**overrides) -> bytes:
    payload = {
        "product_id": "pegasus-harness",
        "display_name": "Pegasus",
        "program_name": "pegasus",
        "version": "1.0.0",
        "wordmark_words": ["PEGASUS", "HARNESS"],
        "release": {
            "asset_url_template": "https://github.com/balerdis/pegasus-harness/releases/download/{tag}/{asset}",
            "binary_asset": "pegasus",
            "latest_release_api_url": "https://api.github.com/repos/balerdis/pegasus-harness/releases/latest",
            "release_page_url": "https://github.com/balerdis/pegasus-harness/releases",
        },
    }
    payload.update(overrides)
    return json.dumps(payload).encode("utf-8")


class ParseAcceptsAValidDocumentTest(unittest.TestCase):
    def test_a_fully_valid_document_parses_into_an_identity(self):
        parsed = module.parse(document())
        self.assertEqual(
            parsed,
            Identity(
                product_id="pegasus-harness",
                display_name="Pegasus",
                program_name="pegasus",
                version="1.0.0",
                wordmark_words=("PEGASUS", "HARNESS"),
                release=ReleaseSource(
                    asset_url_template="https://github.com/balerdis/pegasus-harness/releases/download/{tag}/{asset}",
                    binary_asset="pegasus",
                    latest_release_api_url="https://api.github.com/repos/balerdis/pegasus-harness/releases/latest",
                    release_page_url="https://github.com/balerdis/pegasus-harness/releases",
                ),
            ),
        )

    def test_a_one_word_identity_is_valid(self):
        parsed = module.parse(document(wordmark_words=["DARQ"]))
        self.assertEqual(parsed.wordmark_words, ("DARQ",))

    def test_a_name_with_digits_is_valid(self):
        parsed = module.parse(document(wordmark_words=["DARQ2"]))
        self.assertEqual(parsed.wordmark_words, ("DARQ2",))

    def test_a_version_with_a_pre_release_suffix_is_valid(self):
        parsed = module.parse(document(version="1.0.0-rc.1"))
        self.assertEqual(parsed.version, "1.0.0-rc.1")


class ParseRejectsAMalformedDocumentTest(unittest.TestCase):
    def test_not_json_is_rejected(self):
        with self.assertRaises(IdentityError):
            module.parse(b"not json at all")

    def test_not_an_object_is_rejected(self):
        with self.assertRaises(IdentityError):
            module.parse(b"[1, 2, 3]")

    def test_missing_product_id_is_rejected(self):
        payload = json.loads(document())
        del payload["product_id"]
        with self.assertRaises(IdentityError):
            module.parse(json.dumps(payload).encode("utf-8"))

    def test_missing_release_block_is_rejected(self):
        payload = json.loads(document())
        del payload["release"]
        with self.assertRaises(IdentityError):
            module.parse(json.dumps(payload).encode("utf-8"))

    def test_accented_character_is_rejected(self):
        with self.assertRaises(IdentityError):
            module.parse(document(wordmark_words=["MI-EQUIPO"]))

    def test_a_word_wider_than_the_glyph_grid_is_rejected(self):
        with self.assertRaises(IdentityError):
            module.parse(document(wordmark_words=["A" * (module.MAX_WORD_LENGTH + 1)]))

    def test_lowercase_is_rejected(self):
        with self.assertRaises(IdentityError):
            module.parse(document(wordmark_words=["darq"]))

    def test_three_words_is_rejected(self):
        with self.assertRaises(IdentityError):
            module.parse(document(wordmark_words=["ONE", "TWO", "THREE"]))

    def test_a_non_https_release_template_is_rejected(self):
        payload = json.loads(document())
        payload["release"]["asset_url_template"] = "http://github.com/x/y/releases/download/{tag}/{asset}"
        with self.assertRaises(IdentityError):
            module.parse(json.dumps(payload).encode("utf-8"))

    def test_a_file_uri_release_template_is_rejected(self):
        payload = json.loads(document())
        payload["release"]["asset_url_template"] = "file:///etc/passwd/{tag}/{asset}"
        with self.assertRaises(IdentityError):
            module.parse(json.dumps(payload).encode("utf-8"))

    def test_a_release_template_with_userinfo_spoofing_the_host_is_rejected(self):
        """The exact attack the reviewer confirmed: a prefix/substring check
        alone lets `github.com` sit before the `@` as bogus userinfo while
        `evil.example.com` is the real host `urlsplit(...).hostname` names."""
        payload = json.loads(document())
        payload["release"]["asset_url_template"] = (
            "https://github.com@evil.example.com/releases/download/{tag}/{asset}"
        )
        with self.assertRaises(IdentityError):
            module.parse(json.dumps(payload).encode("utf-8"))

    def test_a_release_template_with_no_hostname_is_rejected(self):
        payload = json.loads(document())
        payload["release"]["asset_url_template"] = "https:///releases/download/{tag}/{asset}"
        with self.assertRaises(IdentityError):
            module.parse(json.dumps(payload).encode("utf-8"))

    def test_a_release_api_url_with_userinfo_spoofing_the_host_is_rejected(self):
        payload = json.loads(document())
        payload["release"]["latest_release_api_url"] = "https://api.github.com@evil.example.com/x"
        with self.assertRaises(IdentityError):
            module.parse(json.dumps(payload).encode("utf-8"))

    def test_a_release_page_url_with_userinfo_spoofing_the_host_is_rejected(self):
        payload = json.loads(document())
        payload["release"]["release_page_url"] = "https://github.com@evil.example.com/releases"
        with self.assertRaises(IdentityError):
            module.parse(json.dumps(payload).encode("utf-8"))

    def test_missing_release_page_url_is_rejected(self):
        payload = json.loads(document())
        del payload["release"]["release_page_url"]
        with self.assertRaises(IdentityError):
            module.parse(json.dumps(payload).encode("utf-8"))

    def test_a_release_template_missing_the_tag_placeholder_is_rejected(self):
        payload = json.loads(document())
        payload["release"]["asset_url_template"] = "https://example.com/download/{asset}"
        with self.assertRaises(IdentityError):
            module.parse(json.dumps(payload).encode("utf-8"))

    def test_a_release_template_missing_the_asset_placeholder_is_rejected(self):
        payload = json.loads(document())
        payload["release"]["asset_url_template"] = "https://example.com/download/{tag}"
        with self.assertRaises(IdentityError):
            module.parse(json.dumps(payload).encode("utf-8"))

    def test_a_binary_asset_with_a_path_separator_is_rejected(self):
        payload = json.loads(document())
        payload["release"]["binary_asset"] = "../../x"
        with self.assertRaises(IdentityError):
            module.parse(json.dumps(payload).encode("utf-8"))

    def test_a_binary_asset_with_a_backslash_is_rejected(self):
        payload = json.loads(document())
        payload["release"]["binary_asset"] = "sub\\dir"
        with self.assertRaises(IdentityError):
            module.parse(json.dumps(payload).encode("utf-8"))

    def test_a_product_id_with_a_path_separator_is_rejected(self):
        """`product_id` is joined directly onto a filesystem path in
        `PosixFileSystem.data_dir()` -- the same class of risk
        `release.binary_asset` already guards against."""
        with self.assertRaises(IdentityError):
            module.parse(document(product_id="a/b"))

    def test_a_product_id_with_a_backslash_is_rejected(self):
        with self.assertRaises(IdentityError):
            module.parse(document(product_id="a\\b"))

    def test_a_product_id_with_parent_directory_traversal_is_rejected(self):
        with self.assertRaises(IdentityError):
            module.parse(document(product_id="../../etc"))

    def test_a_bare_parent_directory_product_id_is_rejected(self):
        with self.assertRaises(IdentityError):
            module.parse(document(product_id=".."))

    def test_invalid_utf8_is_rejected(self):
        with self.assertRaises(IdentityError):
            module.parse(b"\xff\xfe not utf-8")

    def test_missing_version_is_rejected(self):
        """`version` is required, never defaulted to the engine's own
        `pegasus.__version__` -- a distribution's version is a fact about
        that distribution, not the pinned engine it happens to be built
        from, and a silent fallback here is exactly the dead-default shape
        this codebase already refuses everywhere else identity is involved."""
        payload = json.loads(document())
        del payload["version"]
        with self.assertRaises(IdentityError):
            module.parse(json.dumps(payload).encode("utf-8"))

    def test_an_empty_version_is_rejected(self):
        with self.assertRaises(IdentityError):
            module.parse(document(version=""))

    def test_a_version_with_a_path_separator_is_rejected(self):
        """`version` flows into a release URL path (`core.upgrade._tag`) --
        the same charset `_SAFE_VERSION` already confines a remote release's
        own `tag_name` to, reused here rather than re-declared, so the two
        can never drift apart."""
        with self.assertRaises(IdentityError):
            module.parse(document(version="1.0.0/../etc"))

    def test_a_version_with_whitespace_is_rejected(self):
        with self.assertRaises(IdentityError):
            module.parse(document(version="1.0.0 "))

    def test_a_version_starting_with_a_symbol_is_rejected(self):
        with self.assertRaises(IdentityError):
            module.parse(document(version="-1.0.0"))


if __name__ == "__main__":
    unittest.main()
