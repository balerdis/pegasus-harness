"""The ownership journal: what Pegasus may take back, and what it must leave alone."""
from __future__ import annotations

import unittest
from pathlib import Path, PurePosixPath

from pegasus.core import journal as journal_module
from pegasus.core.journal import Install, Journal, JournalError, Link, Record

HOME = Path("/home/probe")
CONFIG = HOME / ".config" / "opencode"
AT = "2026-08-14T00:00:00+00:00"


def record(**overrides) -> Record:
    fields = dict(
        id="skill:alpha",
        kind="file",
        target=CONFIG / "skills/alpha/SKILL.md",
        after_digest="sha256:" + "a" * 64,
        mode="0644",
        created_at=AT,
    )
    fields.update(overrides)
    return Record(**fields)


def config_record(**overrides) -> Record:
    fields = dict(
        id="agent:sdd-verify",
        kind="config-key",
        target=CONFIG / "opencode.json",
        pointer="/agent/sdd-verify",
        codec="json",
        after_digest="sha256:" + "b" * 64,
        created_at=AT,
    )
    fields.update(overrides)
    return Record(**fields)


def install(*entries, cli="opencode", links=()) -> Install:
    return Install(
        cli=cli,
        installed_at=AT,
        config_dir=CONFIG,
        release={"version": "4.0.0", "catalog_digest": "sha256:" + "c" * 64},
        entries=tuple(entries),
        links=tuple(links),
    )


class EmptyTest(unittest.TestCase):
    def test_starts_with_no_installs(self):
        self.assertEqual(journal_module.empty("4.0.0").installs, ())

    def test_declares_its_schema(self):
        self.assertEqual(journal_module.empty("4.0.0").schema, "pegasus-harness/journal/v4")


class RoundTripTest(unittest.TestCase):
    def setUp(self):
        self.journal = Journal(pegasus_version="4.0.0", installs=(install(record(), config_record()),))

    def test_survives_serialization(self):
        payload = journal_module.to_dict(self.journal)
        self.assertEqual(journal_module.from_dict(payload, HOME), self.journal)

    def test_absolute_targets_are_kept(self):
        """The catalog is portable; the journal records what this machine actually holds."""
        payload = journal_module.to_dict(self.journal)
        self.assertEqual(
            payload["installs"][0]["entries"][0]["target"],
            "/home/probe/.config/opencode/skills/alpha/SKILL.md",
        )

    def test_fields_that_do_not_apply_are_omitted(self):
        payload = journal_module.to_dict(self.journal)
        entry = payload["installs"][0]["entries"][0]
        self.assertNotIn("pointer", entry)
        self.assertNotIn("codec", entry)

    def test_serialization_is_stable(self):
        self.assertEqual(
            journal_module.to_dict(self.journal), journal_module.to_dict(self.journal)
        )


class ValidationTest(unittest.TestCase):
    def payload(self, **overrides):
        base = journal_module.to_dict(Journal(pegasus_version="4.0.0", installs=(install(record()),)))
        base.update(overrides)
        return base

    def test_an_unknown_schema_is_refused(self):
        with self.assertRaises(JournalError) as raised:
            journal_module.from_dict(self.payload(schema="pegasus-harness/journal/v3"), HOME)
        self.assertIn("v3", str(raised.exception))

    def test_a_target_outside_the_home_is_refused(self):
        payload = self.payload()
        payload["installs"][0]["entries"][0]["target"] = "/etc/passwd"
        with self.assertRaises(JournalError) as raised:
            journal_module.from_dict(payload, HOME)
        self.assertIn("/etc/passwd", str(raised.exception))

    def test_a_relative_target_is_refused(self):
        payload = self.payload()
        payload["installs"][0]["entries"][0]["target"] = "skills/alpha/SKILL.md"
        with self.assertRaises(JournalError):
            journal_module.from_dict(payload, HOME)

    def test_a_malformed_digest_is_refused(self):
        payload = self.payload()
        payload["installs"][0]["entries"][0]["after_digest"] = "deadbeef"
        with self.assertRaises(JournalError) as raised:
            journal_module.from_dict(payload, HOME)
        self.assertIn("digest", str(raised.exception))

    def test_an_unknown_kind_is_refused(self):
        payload = self.payload()
        payload["installs"][0]["entries"][0]["kind"] = "registry-key"
        with self.assertRaises(JournalError):
            journal_module.from_dict(payload, HOME)

    def test_ownership_other_than_owned_is_refused(self):
        payload = self.payload()
        payload["installs"][0]["entries"][0]["ownership"] = "borrowed"
        with self.assertRaises(JournalError):
            journal_module.from_dict(payload, HOME)

    def test_a_link_must_declare_it_is_not_owned(self):
        payload = journal_module.to_dict(
            Journal(pegasus_version="4.0.0", installs=(install(links=(Link(id="cbm", target="/usr/bin/cbm"),)),))
        )
        payload["installs"][0]["links"][0]["ownership"] = "owned"
        with self.assertRaises(JournalError) as raised:
            journal_module.from_dict(payload, HOME)
        self.assertIn("non-owning-link", str(raised.exception))

    def test_two_installs_for_one_cli_are_refused(self):
        payload = journal_module.to_dict(
            Journal(pegasus_version="4.0.0", installs=(install(record()), install(record())))
        )
        with self.assertRaises(JournalError) as raised:
            journal_module.from_dict(payload, HOME)
        self.assertIn("opencode", str(raised.exception))

    def test_a_config_key_entry_needs_a_pointer(self):
        payload = self.payload()
        payload["installs"][0]["entries"][0]["kind"] = "config-key"
        with self.assertRaises(JournalError) as raised:
            journal_module.from_dict(payload, HOME)
        self.assertIn("pointer", str(raised.exception))


class InstallsTest(unittest.TestCase):
    def test_installs_are_kept_per_cli(self):
        journal = journal_module.empty("4.0.0")
        journal = journal_module.with_install(journal, install(record()))
        journal = journal_module.with_install(journal, install(record(), cli="other"))
        self.assertEqual([item.cli for item in journal.installs], ["opencode", "other"])

    def test_installing_again_replaces_the_previous_record(self):
        journal = journal_module.with_install(journal_module.empty("4.0.0"), install(record()))
        journal = journal_module.with_install(journal, install(record(), config_record()))
        self.assertEqual(len(journal.installs), 1)
        self.assertEqual(len(journal.installs[0].entries), 2)

    def test_finds_an_install_by_cli(self):
        journal = journal_module.with_install(journal_module.empty("4.0.0"), install(record()))
        self.assertEqual(journal_module.install_for(journal, "opencode").cli, "opencode")
        self.assertIsNone(journal_module.install_for(journal, "nope"))

    def test_removing_an_install_leaves_the_others(self):
        journal = journal_module.with_install(journal_module.empty("4.0.0"), install(record()))
        journal = journal_module.with_install(journal, install(record(), cli="other"))
        journal = journal_module.without_install(journal, "opencode")
        self.assertEqual([item.cli for item in journal.installs], ["other"])


class LegacyPayloadTest(unittest.TestCase):
    """A journal written by an earlier engine may carry fields this one no longer uses.

    Parsing is additive: it reads what it needs from a dict and never checks the
    dict is exactly that shape, so a key from a retired feature is silently
    dropped rather than rejected.
    """

    def test_before_adopted_and_mutations_are_ignored_rather_than_rejected(self):
        payload = journal_module.to_dict(Journal(pegasus_version="4.0.0", installs=(install(config_record()),)))
        entry = payload["installs"][0]["entries"][0]
        entry["before"] = {"model": "someone/else"}
        entry["adopted"] = True
        entry["mutations"] = [{"at": AT, "by": "set-model", "after_digest": "sha256:" + "d" * 64}]

        parsed = journal_module.from_dict(payload, HOME)

        entry = parsed.installs[0].entries[0]
        self.assertFalse(hasattr(entry, "before"))
        self.assertFalse(hasattr(entry, "adopted"))
        self.assertFalse(hasattr(entry, "mutations"))


if __name__ == "__main__":
    unittest.main()
