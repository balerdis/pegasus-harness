"""The snapshot generation manifest: pure structure, no filesystem."""
from __future__ import annotations

import unittest
from pathlib import Path

from pegasus.core import snapshot as snapshot_module
from pegasus.core.snapshot import Entry, Manifest, SnapshotError

AT = "2026-08-14T00:00:00+00:00"


def entry(**overrides) -> Entry:
    fields = dict(path=Path("/home/probe/.config/some-cli/settings.json"), existed=True, mode="0644", blob="0001.blob")
    fields.update(overrides)
    return Entry(**fields)


class EntryConstructionTest(unittest.TestCase):
    def test_an_existing_entry_needs_a_mode_and_a_blob(self):
        entry(existed=True, mode="0644", blob="0001.blob")

    def test_an_absent_entry_needs_neither(self):
        entry(existed=False, mode=None, blob=None)

    def test_an_absent_entry_cannot_carry_a_blob(self):
        with self.assertRaises(SnapshotError):
            entry(existed=False, mode=None, blob="0001.blob")

    def test_an_absent_entry_cannot_carry_a_mode(self):
        with self.assertRaises(SnapshotError):
            entry(existed=False, mode="0644", blob=None)

    def test_an_existing_entry_needs_a_blob(self):
        with self.assertRaises(SnapshotError):
            entry(existed=True, mode="0644", blob=None)

    def test_an_existing_entry_needs_a_mode(self):
        with self.assertRaises(SnapshotError):
            entry(existed=True, mode=None, blob="0001.blob")


class ManifestRoundTripTest(unittest.TestCase):
    def setUp(self):
        self.manifest = Manifest(
            taken_at=AT,
            entries=(
                entry(),
                entry(path=Path("/home/probe/.config/some-cli/other.json"), existed=False, mode=None, blob=None),
            ),
        )

    def test_survives_serialization(self):
        payload = snapshot_module.to_dict(self.manifest)
        self.assertEqual(snapshot_module.from_dict(payload), self.manifest)

    def test_fields_that_do_not_apply_are_omitted(self):
        payload = snapshot_module.to_dict(self.manifest)
        absent_entry = payload["entries"][1]
        self.assertNotIn("mode", absent_entry)
        self.assertNotIn("blob", absent_entry)

    def test_an_empty_manifest_round_trips(self):
        empty = Manifest(taken_at=AT)
        self.assertEqual(snapshot_module.from_dict(snapshot_module.to_dict(empty)), empty)


class FromDictValidationTest(unittest.TestCase):
    def test_rejects_a_non_object_payload(self):
        with self.assertRaises(SnapshotError):
            snapshot_module.from_dict([])

    def test_rejects_a_missing_taken_at(self):
        with self.assertRaises(SnapshotError):
            snapshot_module.from_dict({"entries": []})

    def test_rejects_a_blank_taken_at(self):
        with self.assertRaises(SnapshotError):
            snapshot_module.from_dict({"taken_at": "", "entries": []})

    def test_rejects_entries_that_are_not_a_list(self):
        with self.assertRaises(SnapshotError):
            snapshot_module.from_dict({"taken_at": AT, "entries": "nope"})

    def test_rejects_an_entry_that_is_not_an_object(self):
        with self.assertRaises(SnapshotError):
            snapshot_module.from_dict({"taken_at": AT, "entries": ["nope"]})

    def test_rejects_an_entry_missing_a_path(self):
        with self.assertRaises(SnapshotError):
            snapshot_module.from_dict({"taken_at": AT, "entries": [{"existed": False}]})

    def test_rejects_an_entry_missing_existed(self):
        with self.assertRaises(SnapshotError):
            snapshot_module.from_dict({"taken_at": AT, "entries": [{"path": "/a"}]})

    def test_rejects_an_entry_with_a_non_boolean_existed(self):
        with self.assertRaises(SnapshotError):
            snapshot_module.from_dict({"taken_at": AT, "entries": [{"path": "/a", "existed": "yes"}]})

    def test_rejects_an_entry_with_a_non_string_mode(self):
        with self.assertRaises(SnapshotError):
            snapshot_module.from_dict(
                {"taken_at": AT, "entries": [{"path": "/a", "existed": True, "mode": 644, "blob": "0001.blob"}]}
            )

    def test_rejects_an_entry_with_a_non_string_blob(self):
        with self.assertRaises(SnapshotError):
            snapshot_module.from_dict(
                {"taken_at": AT, "entries": [{"path": "/a", "existed": True, "mode": "0644", "blob": 1}]}
            )

    def test_rejects_an_existing_entry_that_still_lacks_a_blob(self):
        """The construction guard fires even when the payload reached from_dict."""
        with self.assertRaises(SnapshotError):
            snapshot_module.from_dict({"taken_at": AT, "entries": [{"path": "/a", "existed": True, "mode": "0644"}]})


if __name__ == "__main__":
    unittest.main()
