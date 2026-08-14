"""Fingerprints and collisions.

A fingerprint is what lets Pegasus recognise its own work later. If the digest
the catalog publishes and the digest the journal stores ever disagree for the
same artifact, every uninstall would find a mismatch and preserve everything
forever — so one of these tests exists purely to keep the two from drifting.
"""
from __future__ import annotations

import hashlib
import unittest
from pathlib import Path

from pegasus.core import journal as journal_module, ownership
from pegasus.core.types import Codec, ConfigKeyArtifact, FileArtifact

CONFIG = Path("/home/probe/.config/some-cli")


def file_artifact(content: bytes = b"hello", **overrides) -> FileArtifact:
    fields = dict(id="skill:alpha", path=CONFIG / "skills/alpha/SKILL.md", content=content)
    fields.update(overrides)
    return FileArtifact(**fields)


def config_artifact(value=None, **overrides) -> ConfigKeyArtifact:
    fields = dict(
        id="agent:alpha",
        path=CONFIG / "settings.json",
        pointer="/agent/alpha",
        value={"model": "vendor/model"} if value is None else value,
    )
    fields.update(overrides)
    return ConfigKeyArtifact(**fields)


class DigestTest(unittest.TestCase):
    def test_a_file_is_hashed_by_its_bytes(self):
        self.assertEqual(
            ownership.digest(file_artifact(b"hello")),
            "sha256:" + hashlib.sha256(b"hello").hexdigest(),
        )

    def test_a_configuration_value_is_hashed_by_its_canonical_form(self):
        one = config_artifact({"a": 1, "b": 2})
        other = config_artifact({"b": 2, "a": 1})
        self.assertEqual(ownership.digest(one), ownership.digest(other))

    def test_a_different_value_hashes_differently(self):
        self.assertNotEqual(
            ownership.digest(config_artifact({"model": "one"})),
            ownership.digest(config_artifact({"model": "two"})),
        )

    def test_every_digest_is_shaped_the_way_the_journal_demands(self):
        for artifact in (file_artifact(), config_artifact()):
            with self.subTest(artifact=type(artifact).__name__):
                self.assertRegex(ownership.digest(artifact), journal_module.DIGEST)

    def test_an_unsupported_shape_is_refused(self):
        with self.assertRaises(ownership.OwnershipError):
            ownership.digest(object())

    def test_bytes_and_values_can_be_hashed_directly(self):
        self.assertEqual(ownership.digest_of_bytes(b"hello"), ownership.digest(file_artifact(b"hello")))
        self.assertEqual(
            ownership.digest_of_value({"model": "vendor/model"}),
            ownership.digest(config_artifact()),
        )


class DigestAgreementTest(unittest.TestCase):
    """The catalog publishes an intention; the journal records the fact.

    They describe the same artifact and must hash it identically, or ownership
    breaks the first time someone uninstalls.
    """

    def test_the_catalog_and_the_journal_hash_a_file_the_same_way(self):
        from pegasus.core import catalog

        artifact = file_artifact(b"hello")
        entry = catalog._entry(artifact, CONFIG)
        self.assertEqual(entry.digest, ownership.digest(artifact))

    def test_the_catalog_and_the_journal_hash_a_configuration_value_the_same_way(self):
        from pegasus.core import catalog

        artifact = config_artifact()
        entry = catalog._entry(artifact, CONFIG)
        self.assertEqual(entry.digest, ownership.digest(artifact))


class OccupationTest:
    """Whether something is already sitting where the artifact wants to go."""


class ConfigurationOccupationTest(unittest.TestCase):
    def test_a_pointer_that_resolves_is_occupied(self):
        document = {"agent": {"alpha": {"model": "theirs"}}}
        self.assertTrue(ownership.occupies(config_artifact(), document))

    def test_a_pointer_that_does_not_resolve_is_free(self):
        self.assertFalse(ownership.occupies(config_artifact(), {"agent": {}}))

    def test_an_absent_document_leaves_every_pointer_free(self):
        self.assertFalse(ownership.occupies(config_artifact(), None))

    def test_a_pointer_resolving_to_a_falsy_value_is_still_occupied(self):
        """An empty object is the user's, and skipping is what protects it."""
        document = {"agent": {"alpha": {}}}
        self.assertTrue(ownership.occupies(config_artifact(), document))

    def test_a_file_artifact_is_not_answered_by_a_document(self):
        with self.assertRaises(ownership.OwnershipError):
            ownership.occupies(file_artifact(), {})


class RecognitionTest:
    """Whether what is on disk now is still what Pegasus put there."""


class StillOursTest(unittest.TestCase):
    def entry(self, digest: str) -> journal_module.Record:
        return journal_module.Record(
            id="skill:alpha",
            kind="file",
            target=CONFIG / "skills/alpha/SKILL.md",
            after_digest=digest,
            created_at="2026-08-14T00:00:00+00:00",
        )

    def test_a_matching_digest_is_still_ours(self):
        digest = ownership.digest_of_bytes(b"hello")
        self.assertTrue(ownership.still_ours(self.entry(digest), digest))

    def test_a_changed_digest_is_not_ours_to_take_back(self):
        self.assertFalse(
            ownership.still_ours(self.entry(ownership.digest_of_bytes(b"hello")), ownership.digest_of_bytes(b"edited"))
        )

    def test_something_already_gone_counts_as_ours(self):
        """Retiring what the user already deleted is the outcome Pegasus wanted."""
        self.assertTrue(ownership.still_ours(self.entry(ownership.digest_of_bytes(b"hello")), None))


if __name__ == "__main__":
    unittest.main()
