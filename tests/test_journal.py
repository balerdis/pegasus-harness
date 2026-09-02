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


def dependency_record(**overrides) -> Record:
    fields = dict(
        id="dependency:some-mcp",
        kind="dependency-tree",
        target=HOME / ".local" / "share" / "pegasus-harness" / "deps" / "some-mcp" / "1.2.3",
        after_digest="sha256:" + "d" * 64,
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

    def test_a_dependency_tree_entry_survives_serialization(self):
        """A `dependency-tree` entry's target is a directory rather than a
        file, but the journal itself treats every target the same way — as an
        absolute path inside the home — so it round-trips like any other."""
        journal = Journal(pegasus_version="4.0.0", installs=(install(dependency_record()),))
        payload = journal_module.to_dict(journal)
        self.assertEqual(journal_module.from_dict(payload, HOME), journal)

    def test_a_dependency_trees_program_fields_survive_serialization(self):
        entry = dependency_record(
            program_relpath="node_modules/probe-mcp/cli.js", program_digest="sha256:" + "e" * 64
        )
        journal = Journal(pegasus_version="4.0.0", installs=(install(entry),))
        payload = journal_module.to_dict(journal)
        self.assertEqual(journal_module.from_dict(payload, HOME), journal)

    def test_a_dependency_tree_without_program_fields_omits_them(self):
        """A record predating the program-digest pair must not fabricate
        either field on the way back out to disk."""
        payload = journal_module.to_dict(Journal(pegasus_version="4.0.0", installs=(install(dependency_record()),)))
        entry = payload["installs"][0]["entries"][0]
        self.assertNotIn("program_relpath", entry)
        self.assertNotIn("program_digest", entry)


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

    def test_a_malformed_program_digest_is_refused(self):
        payload = self.payload()
        entry = payload["installs"][0]["entries"][0]
        entry["program_relpath"] = "cli.js"
        entry["program_digest"] = "deadbeef"
        with self.assertRaises(JournalError) as raised:
            journal_module.from_dict(payload, HOME)
        self.assertIn("program_digest", str(raised.exception))

    def test_a_program_relpath_that_leaves_the_tree_is_refused(self):
        """The path is joined onto the tree root, and a join is not a boundary.

        `Path('/deps/cbm/1.0') / '/etc/passwd'` is `/etc/passwd` — the left
        operand is discarded whole — and a `..` chain walks out the same way.
        A journal that names either points `doctor`'s tamper check at a file
        of somebody's choosing: hash a file they control, record its digest
        here, and the check passes forever while the real tree is never read
        at all. It is the one input to that check nobody else validates, so it
        is refused where it is read.
        """
        for relpath in ("/etc/passwd", "../../../etc/passwd", "node_modules/../../escape"):
            with self.subTest(relpath=relpath):
                payload = self.payload()
                entry = payload["installs"][0]["entries"][0]
                entry["program_relpath"] = relpath
                entry["program_digest"] = "sha256:" + "e" * 64
                with self.assertRaises(JournalError) as raised:
                    journal_module.from_dict(payload, HOME)
                self.assertIn("program_relpath", str(raised.exception))

    def test_an_empty_program_relpath_is_refused(self):
        payload = self.payload()
        entry = payload["installs"][0]["entries"][0]
        entry["program_relpath"] = ""
        entry["program_digest"] = "sha256:" + "a" * 64
        with self.assertRaises(JournalError) as raised:
            journal_module.from_dict(payload, HOME)
        self.assertIn("program_relpath", str(raised.exception))

    def test_a_journal_from_before_this_pair_existed_still_loads(self):
        """Neither field is a plain absence, not a defect -- an entry with no
        knowledge of the program-digest pair at all must load exactly as
        cleanly as it did before the pair was invented."""
        payload = self.payload()
        parsed = journal_module.from_dict(payload, HOME)
        entry = parsed.installs[0].entries[0]
        self.assertIsNone(entry.program_relpath)
        self.assertIsNone(entry.program_digest)

    def test_a_dependency_tree_kind_is_accepted(self):
        payload = journal_module.to_dict(Journal(pegasus_version="4.0.0", installs=(install(dependency_record()),)))
        journal_module.from_dict(payload, HOME)  # raises on failure

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
