"""Planning, applying and retiring an installation.

Three properties are what these tests are really about:

**Additive.** Anything already there is left alone and reported, never
negotiated with.

**All or nothing.** A run that fails half way undoes what it created, so the
journal never describes a home that does not exist.

**Retirable.** What Pegasus recorded, Pegasus can take back — and only that.

**Real disk.** Every test in this module runs against a throwaway home and
the real `PosixFileSystem`, via `RealHomeTestCase`. Conditions are produced
rather than injected: a directory really refuses the write, and the two
failures no permission bit can express — a write and a removal that fail
once and then succeed — are stubbed at the system call.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

import fakes
from pegasus.core import ownership, planner
from pegasus.core.journal import Install, Link, Record
from pegasus.core.types import Codec, ConfigKeyArtifact, FileArtifact
from pegasus.ports.filesystem import FileSystemError
from platform_conditions import (
    fail_next_removal_once,
    fail_next_write_once,
    make_unreadable,
    make_unwritable,
)
from real_home import RealHomeTestCase as _RealHomeTestCase
from recording_filesystem import RecordingFileSystem

AT = "2026-08-14T00:00:00+00:00"
CLI = "some-cli"


def document(payload) -> bytes:
    return (json.dumps(payload, indent=2) + "\n").encode("utf-8")


class RealHomeTestCase(_RealHomeTestCase):
    """The generic real-home base plus the fixed layout every test in this
    module plans an installation against, and the helpers that used to live
    on the double's own constructor keywords.
    """

    def setUp(self):
        super().setUp()
        self.filesystem = RecordingFileSystem(self.filesystem)
        self.CONFIG = self.home / ".config" / "some-cli"
        self.SETTINGS = self.CONFIG / "settings.json"
        self.SKILL = self.CONFIG / "skills/alpha/SKILL.md"

    def seed(self, files: dict[Path, bytes] | None = None, modes: dict[Path, int] | None = None) -> None:
        """Write real files, and their real permission bits, before a test
        runs — the disk equivalent of the double's `files=`/`modes=`
        constructor keywords. Written directly rather than through the port,
        so this never counts as a write the run under test performed."""
        for path, content in (files or {}).items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            path.chmod((modes or {}).get(path, 0o644))

    def a_file(
        self,
        identifier: str = "skill:alpha",
        path: Path | None = None,
        content: bytes = b"hello",
        executable: bool = False,
    ) -> FileArtifact:
        return FileArtifact(
            id=identifier, path=self.SKILL if path is None else path, content=content, executable=executable
        )

    def a_key(
        self, identifier: str = "agent:alpha", ptr: str = "/agent/alpha", value=None, path: Path | None = None
    ) -> ConfigKeyArtifact:
        return ConfigKeyArtifact(
            id=identifier,
            path=self.SETTINGS if path is None else path,
            pointer=ptr,
            value={"model": "vendor/model"} if value is None else value,
        )

    def plan_for(self, *artifacts, installed: Install | None = None) -> planner.Plan:
        return planner.plan(self.filesystem, cli=CLI, artifacts=list(artifacts), installed=installed)


class PlanTest(RealHomeTestCase):
    def test_a_free_path_is_planned_as_a_creation(self):
        result = self.plan_for(self.a_file())
        self.assertEqual([step.action for step in result.steps], [planner.CREATE])

    def test_an_occupied_path_is_skipped(self):
        self.seed(files={self.SKILL: b"theirs"})
        result = self.plan_for(self.a_file())
        step = result.steps[0]
        self.assertEqual(step.action, planner.SKIP)
        self.assertEqual(step.reason, planner.COLLISION)

    def test_a_free_pointer_is_planned_as_a_creation(self):
        self.seed(files={self.SETTINGS: document({"agent": {}})})
        self.assertEqual([step.action for step in self.plan_for(self.a_key()).steps], [planner.CREATE])

    def test_an_occupied_pointer_is_skipped(self):
        self.seed(files={self.SETTINGS: document({"agent": {"alpha": {"model": "theirs"}}})})
        self.assertEqual([step.action for step in self.plan_for(self.a_key()).steps], [planner.SKIP])

    def test_a_pointer_in_a_file_that_does_not_exist_yet_is_a_creation(self):
        self.assertEqual([step.action for step in self.plan_for(self.a_key()).steps], [planner.CREATE])

    def test_planning_a_file_whose_existence_cannot_be_told_refuses_rather_than_creating_over_it(self):
        """`_file_step` treats `not exists` as a green light for `CREATE`.
        Letting a probe failure fall through the same branch would plan a
        creation over a file that is actually there, and `apply` would
        overwrite it with nothing kept to give back. This runs before a
        single byte reaches disk, so refusing here — rather than swallowing
        the failure — costs nothing."""
        self.SKILL.parent.mkdir(parents=True, exist_ok=True)
        self.addCleanup(make_unreadable(self.SKILL.parent))
        with self.assertRaises(FileSystemError):
            self.plan_for(self.a_file())

    def test_planning_a_key_whose_document_existence_cannot_be_told_refuses_rather_than_treating_it_as_new(self):
        """`_read_document` treats `not exists` as "no document yet". A probe
        failure taking that branch would plan the key as a fresh creation
        over a document `apply` would then overwrite."""
        self.CONFIG.mkdir(parents=True, exist_ok=True)
        self.addCleanup(make_unreadable(self.CONFIG))
        with self.assertRaises(FileSystemError):
            self.plan_for(self.a_key())

    def test_planning_writes_nothing(self):
        self.plan_for(self.a_file(), self.a_key())
        self.assertEqual(self.filesystem.writes, [])
        self.assertFalse(self.SKILL.exists())
        self.assertFalse(self.SETTINGS.exists())

    def test_every_step_carries_the_fingerprint_of_what_it_would_place(self):
        artifact = self.a_file()
        step = self.plan_for(artifact).steps[0]
        self.assertEqual(step.digest, ownership.digest(artifact))

    def test_creations_and_collisions_are_separable(self):
        self.seed(files={self.SKILL: b"theirs"})
        result = self.plan_for(self.a_file(), self.a_key())
        self.assertEqual([step.artifact.id for step in result.creations], ["agent:alpha"])
        self.assertEqual([step.artifact.id for step in result.collisions], ["skill:alpha"])

    # --- Failing closed ---

    def test_a_malformed_configuration_file_is_refused(self):
        """Guessing at a file we cannot parse is how a user's settings get lost."""
        self.seed(files={self.SETTINGS: b"{ not json"})
        with self.assertRaises(planner.PlannerError):
            self.plan_for(self.a_key())

    def test_two_artifacts_with_the_same_id_are_refused(self):
        with self.assertRaises(planner.PlannerError):
            self.plan_for(self.a_file(), self.a_file(path=self.CONFIG / "other.md"))

    def test_two_artifacts_claiming_the_same_path_are_refused(self):
        with self.assertRaises(planner.PlannerError):
            self.plan_for(self.a_file(), self.a_file(identifier="skill:beta"))

    def test_two_artifacts_claiming_the_same_pointer_are_refused(self):
        with self.assertRaises(planner.PlannerError):
            self.plan_for(self.a_key(), self.a_key(identifier="agent:beta"))

    def test_an_unsupported_artifact_shape_is_refused(self):
        with self.assertRaises(planner.PlannerError):
            self.plan_for(object())

    def test_a_plan_carries_the_entries_the_render_no_longer_asks_for(self):
        """`plan()` wires the pure set difference in, so a caller reading `Plan`
        never has to compute it a second time."""
        stale = Record(
            id="skill:alpha", kind="file", target=self.SKILL, after_digest="sha256:" + "0" * 64, created_at=AT
        )
        previous = Install(cli=CLI, installed_at=AT, config_dir=self.CONFIG, release={}, entries=(stale,))
        result = self.plan_for(installed=previous)
        self.assertEqual(result.retirements, (stale,))


class RetirementsTest(RealHomeTestCase):
    """The other half of ownership. `plan()` asks, for every artifact, whether
    an occupied address is still ours; this asks the reverse question, for
    every journal entry, whether the render still wants it. Neither loop
    answers the other's question."""

    def install(self, *entries, links=()) -> Install:
        return Install(
            cli=CLI, installed_at=AT, config_dir=self.CONFIG, release={}, entries=tuple(entries), links=tuple(links)
        )

    def entry(self, identifier: str = "skill:alpha") -> Record:
        return Record(id=identifier, kind="file", target=self.SKILL, after_digest="sha256:" + "0" * 64, created_at=AT)

    def test_an_entry_absent_from_the_render_is_returned(self):
        install = self.install(self.entry())
        self.assertEqual(planner.retirements(install, []), install.entries)

    def test_an_entry_still_rendered_is_not_returned(self):
        install = self.install(self.entry())
        self.assertEqual(planner.retirements(install, [self.a_file(identifier="skill:alpha")]), ())

    def test_without_a_journal_there_is_nothing_to_retire(self):
        self.assertEqual(planner.retirements(None, [self.a_file()]), ())

    def test_a_link_is_never_returned(self):
        """`retirements` excludes links by type, the same way `retire` does:
        a link is never something Pegasus owns, so it is never something to
        take back."""
        link = Link(id="cbm", target="/usr/local/bin/some-tool")
        install = self.install(links=(link,))
        self.assertEqual(planner.retirements(install, []), ())


class AppendTest(RealHomeTestCase):
    """Appending to a list is a create with no address of its own.

    Nothing resolves at ``/instructions/-``, so the ordinary collision question
    cannot be asked. The fingerprint answers it instead: an item Pegasus already
    placed is one it must not place twice, and on the way out it is found by
    what it is rather than by where it sits, because indices move.
    """

    def append(self, value: str = "./pegasus-AGENTS.md"):
        return ConfigKeyArtifact(
            id="system-prompt-instruction", path=self.SETTINGS, pointer="/instructions/-", value=value
        )

    def append_as(self, identifier: str, value: str = "./pegasus-AGENTS.md"):
        return ConfigKeyArtifact(id=identifier, path=self.SETTINGS, pointer="/instructions/-", value=value)

    def entry(self, value: str = "./pegasus-AGENTS.md") -> Record:
        return Record(
            id="system-prompt-instruction",
            kind="config-key",
            target=self.SETTINGS,
            pointer="/instructions/-",
            codec="json",
            after_digest=ownership.digest_of_value(value),
            created_at=AT,
        )

    def install(self, *entries) -> Install:
        return Install(cli=CLI, installed_at=AT, config_dir=self.CONFIG, release={}, entries=tuple(entries))

    def settings(self) -> dict:
        return json.loads(self.SETTINGS.read_bytes())

    def test_a_reconciled_append_can_still_be_found_by_the_release_after_it(self):
        """The interaction that makes reconciliation worth getting right.

        An append has no address, so it is located by the digest the journal
        recorded for it. Leave that digest stale and the next release cannot
        find the item it is supposed to replace: it appends a second one, and
        the user ends up with both. Reconciling the digest is what keeps the
        list from growing every time somebody's hand edit anticipated a
        release.

        The control is the point. Without the reconciliation this sequence
        ends in `["beta", "gamma"]`; with it, in `["gamma"]`.
        """
        self.SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        self.SETTINGS.write_bytes(json.dumps({"instructions": ["beta"]}).encode("utf-8"))
        # The journal still remembers the value a hand edit replaced.
        stale = self.install(self.entry("alpha"))

        reconciling = self.plan_for(self.append("beta"), installed=stale)
        self.assertEqual([step.action for step in reconciling.steps], [planner.UNCHANGED])
        applied = planner.apply(self.filesystem, reconciling, at=AT)
        self.assertEqual([record.after_digest for record in applied.reconciled],
                         [ownership.digest_of_value("beta")])

        after = self.install(*applied.reconciled)
        planner.apply(self.filesystem, self.plan_for(self.append("gamma"), installed=after), at=AT)
        self.assertEqual(self.settings()["instructions"], ["gamma"])

    def test_without_reconciling_the_next_release_appends_a_second_item(self):
        """The same sequence with the stale digest left in place, so the test
        above is proving the reconciliation and not the machinery around it."""
        self.SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        self.SETTINGS.write_bytes(json.dumps({"instructions": ["beta"]}).encode("utf-8"))
        stale = self.install(self.entry("alpha"))
        planner.apply(self.filesystem, self.plan_for(self.append("gamma"), installed=stale), at=AT)
        self.assertEqual(self.settings()["instructions"], ["beta", "gamma"])

    def test_appending_into_a_missing_list_creates_it(self):
        planner.apply(self.filesystem, self.plan_for(self.append()), at=AT)
        self.assertEqual(self.settings()["instructions"], ["./pegasus-AGENTS.md"])

    def test_an_item_already_in_the_list_is_a_collision(self):
        """Otherwise reinstalling would append the same instruction twice."""
        self.seed(files={self.SETTINGS: document({"instructions": ["./pegasus-AGENTS.md"]})})
        self.assertEqual([step.action for step in self.plan_for(self.append()).steps], [planner.SKIP])

    def test_an_item_the_user_placed_alongside_ours_does_not_block_us(self):
        self.seed(files={self.SETTINGS: document({"instructions": ["./theirs.md"]})})
        planner.apply(self.filesystem, self.plan_for(self.append()), at=AT)
        self.assertEqual(self.settings()["instructions"], ["./theirs.md", "./pegasus-AGENTS.md"])

    def test_retiring_an_append_removes_our_item_and_leaves_theirs(self):
        payload = {"instructions": ["./theirs.md", "./pegasus-AGENTS.md", "./another.md"]}
        self.seed(files={self.SETTINGS: document(payload)})
        retired = planner.retire(self.filesystem, self.install(self.entry()))
        self.assertEqual(self.settings()["instructions"], ["./theirs.md", "./another.md"])
        self.assertEqual(retired.removed, ("system-prompt-instruction",))

    def test_retiring_an_append_finds_our_item_after_the_user_reordered_the_list(self):
        payload = {"instructions": ["./pegasus-AGENTS.md", "./theirs.md"]}
        self.seed(files={self.SETTINGS: document(payload)})
        planner.retire(self.filesystem, self.install(self.entry()))
        self.assertEqual(self.settings()["instructions"], ["./theirs.md"])

    def test_an_append_we_cannot_find_is_reported_as_unaccounted_not_as_removed(self):
        """Saying "removed" would claim we did something we did not do.

        A list item has no address of its own, so a fingerprint that matches
        nothing is genuinely ambiguous: the user may have deleted our item, or
        edited it into something we can no longer recognise as ours. Both leave
        the list correct and neither is a removal, so they get their own answer
        instead of being flattened into one of the other three.
        """
        self.seed(files={self.SETTINGS: document({"instructions": ["./theirs.md"]})})
        retired = planner.retire(self.filesystem, self.install(self.entry()))
        self.assertEqual(retired.unaccounted, ("system-prompt-instruction",))
        self.assertEqual(retired.removed, ())
        self.assertEqual(self.settings()["instructions"], ["./theirs.md"])

    def test_an_append_the_user_edited_in_place_is_left_alone_and_reported(self):
        edited = {"instructions": ["./theirs.md", "./the-user-renamed-this.md"]}
        self.seed(files={self.SETTINGS: document(edited)})
        retired = planner.retire(self.filesystem, self.install(self.entry()))
        self.assertEqual(retired.unaccounted, ("system-prompt-instruction",))
        self.assertEqual(self.settings(), edited)
        self.assertEqual(self.filesystem.writes, [])

    def test_an_append_is_removed_when_the_list_itself_is_gone(self):
        """No ambiguity here: our item went with the list, it was not edited into something else."""
        self.seed(files={self.SETTINGS: document({"theme": "dark"})})
        retired = planner.retire(self.filesystem, self.install(self.entry()))
        self.assertEqual(retired.removed, ("system-prompt-instruction",))
        self.assertEqual(retired.unaccounted, ())

    def test_an_append_is_removed_when_the_whole_configuration_file_is_gone(self):
        retired = planner.retire(self.filesystem, self.install(self.entry()))
        self.assertEqual(retired.removed, ("system-prompt-instruction",))
        self.assertEqual(retired.unaccounted, ())

    def test_an_append_is_removed_when_the_list_is_empty(self):
        """An empty list holds nothing that could be a disguised version of ours."""
        self.seed(files={self.SETTINGS: document({"instructions": []})})
        retired = planner.retire(self.filesystem, self.install(self.entry()))
        self.assertEqual(retired.removed, ("system-prompt-instruction",))
        self.assertEqual(retired.unaccounted, ())

    def test_an_append_still_ours_is_removed_and_not_reported_as_unaccounted(self):
        self.seed(files={self.SETTINGS: document({"instructions": ["./pegasus-AGENTS.md"]})})
        retired = planner.retire(self.filesystem, self.install(self.entry()))
        self.assertEqual(retired.removed, ("system-prompt-instruction",))
        self.assertEqual(retired.unaccounted, ())

    def test_a_changed_value_replaces_ours_in_place_instead_of_appending_a_second(self):
        """The upgrade path, and the one an append makes easy to get wrong.

        Every installation that already carries a version of this item has the
        old value sitting in the list and recorded in its journal. Appending
        the new one would leave two of ours: the live entry and a dead one the
        runtime would still try to resolve. It is found by the fingerprint the
        journal recorded, replaced where it already sits, and the list neither
        grows nor reorders -- including around the items the user put there.
        """
        seeded = {"instructions": ["./theirs.md", "./pegasus-AGENTS.md", "./another.md"]}
        self.seed(files={self.SETTINGS: document(seeded)})
        absolute = str(self.CONFIG / "pegasus-AGENTS.md")
        plan = self.plan_for(self.append(absolute), installed=self.install(self.entry()))
        self.assertEqual([step.action for step in plan.steps], [planner.UPDATE])
        planner.apply(self.filesystem, plan, at=AT)
        self.assertEqual(
            self.settings()["instructions"], ["./theirs.md", absolute, "./another.md"]
        )

    def test_a_changed_value_the_list_no_longer_holds_is_appended_not_duplicated(self):
        """The user deleted our old item. There is nothing to replace, so this
        is a creation -- and it must still be exactly one item, not two."""
        self.seed(files={self.SETTINGS: document({"instructions": ["./theirs.md"]})})
        absolute = str(self.CONFIG / "pegasus-AGENTS.md")
        plan = self.plan_for(self.append(absolute), installed=self.install(self.entry()))
        self.assertEqual([step.action for step in plan.steps], [planner.CREATE])
        planner.apply(self.filesystem, plan, at=AT)
        self.assertEqual(self.settings()["instructions"], ["./theirs.md", absolute])

    def test_two_artifacts_appending_the_same_value_are_refused(self):
        """They would place the same item twice, and nothing later could tell them apart."""
        with self.assertRaises(planner.PlannerError):
            self.plan_for(self.append(), self.append_as("other-id"))

    def test_two_artifacts_appending_different_values_are_allowed(self):
        result = self.plan_for(self.append(), self.append_as("other-id", "./another.md"))
        self.assertEqual([step.action for step in result.steps], [planner.CREATE, planner.CREATE])

    def test_retiring_the_only_item_leaves_no_empty_list_behind(self):
        self.seed(files={self.SETTINGS: document({"instructions": ["./pegasus-AGENTS.md"]})})
        planner.retire(self.filesystem, self.install(self.entry()))
        self.assertEqual(self.settings(), {})


class UpdateTest(RealHomeTestCase):
    """Reinstalling over an address the journal claims writes it, whatever is there.

    The journal is the only question. A path that exists says nothing on its own,
    and neither do the bytes in it: what the user wrote over our own artifact is
    overwritten, and the copy taken before the write is what gives it back.
    """

    def setUp(self):
        super().setUp()
        self.previous = b"the shipped version"
        self.seed(files={self.SKILL: self.previous})
        self.artifact = self.a_file(content=b"a newer shipped version")

    def installed(self, *entries: Record) -> Install:
        return Install(cli=CLI, installed_at=AT, config_dir=self.CONFIG, release={}, entries=entries)

    def record(self, **overrides) -> Record:
        fields = {
            "id": self.artifact.id,
            "kind": "file",
            "target": self.SKILL,
            "after_digest": ownership.digest_of_bytes(self.previous),
            "created_at": AT,
            "mode": "0644",
        }
        return Record(**{**fields, **overrides})

    def plan_with(self, *entries: Record, artifact=None):
        return planner.plan(
            self.filesystem,
            cli=CLI,
            artifacts=[artifact if artifact is not None else self.artifact],
            installed=self.installed(*entries),
        )

    # --- Deciding ---

    def test_a_file_that_cannot_be_read_is_left_alone_and_reported(self):
        """Unreadable is not the same as unchanged, and not a matter of policy.

        Overwriting an address the journal claims is the rule, but it rests on
        being able to copy the address first, and something that cannot be read
        cannot be copied. Writing it anyway would destroy the one version there
        is with nothing to give back — so this is the same kind of exception as
        a list item with no address of its own: a physical impossibility, not a
        judgement about who owns the bytes.
        """
        self.addCleanup(make_unreadable(self.SKILL))

        result = self.plan_with(self.record())

        self.assertEqual([step.action for step in result.steps], [planner.SKIP])
        self.assertEqual([step.reason for step in result.steps], [planner.COLLISION])

    def test_a_file_pegasus_wrote_and_nobody_touched_is_an_update(self):
        step = self.plan_with(self.record()).steps[0]
        self.assertEqual(step.action, planner.UPDATE)

    def test_a_file_the_user_rewrote_is_overwritten_by_a_reinstall(self):
        """Install pisa what the journal claims, without asking whether it changed."""
        self.SKILL.write_bytes(b"the user's own version")
        step = self.plan_with(self.record()).steps[0]
        self.assertEqual(step.action, planner.UPDATE)

    def test_a_file_the_journal_never_recorded_is_still_skipped(self):
        step = self.plan_with().steps[0]
        self.assertEqual((step.action, step.reason), (planner.SKIP, planner.COLLISION))

    def test_a_file_already_carrying_this_content_and_mode_is_left_alone(self):
        step = self.plan_with(self.record(), artifact=self.a_file(content=self.previous)).steps[0]
        self.assertEqual(step.action, planner.UNCHANGED)

    def test_without_a_journal_nothing_updates(self):
        """The signature stays optional, so a caller that knows nothing skips as before."""
        step = self.plan_for(self.artifact).steps[0]
        self.assertEqual((step.action, step.reason), (planner.SKIP, planner.COLLISION))

    def test_updates_are_separable_from_creations(self):
        plan = self.plan_with(self.record())
        self.assertEqual(plan.creations, ())
        self.assertEqual(len(plan.updates), 1)
        self.assertEqual(plan.collisions, ())

    def test_planning_an_update_writes_nothing(self):
        self.plan_with(self.record())
        self.assertEqual(self.SKILL.read_bytes(), self.previous)

    # --- Applying ---

    def test_applying_an_update_replaces_the_content(self):
        planner.apply(self.filesystem, self.plan_with(self.record()), at=AT)
        self.assertEqual(self.SKILL.read_bytes(), self.artifact.content)

    def test_an_unchanged_file_is_not_rewritten(self):
        same = self.a_file(content=self.previous)
        applied = planner.apply(self.filesystem, self.plan_with(self.record(), artifact=same), at=AT)
        self.assertEqual(self.filesystem.writes, [])
        self.assertEqual(applied.unchanged[0].artifact.id, same.id)

    def test_a_mode_that_changed_is_an_update_even_when_the_content_did_not(self):
        """The fingerprint is of content, and a permission is not content.

        The previous unit shipped a program that installed unexecutable. Fixing
        the bit in the tree has to reach a home that already has the file, and
        the content there is byte-identical.
        """
        step = self.plan_with(self.record(), artifact=self.a_file(content=self.previous, executable=True)).steps[0]
        self.assertEqual(step.action, planner.UPDATE)

    def test_the_new_mode_reaches_the_disk(self):
        plan = self.plan_with(self.record(), artifact=self.a_file(content=self.previous, executable=True))
        planner.apply(self.filesystem, plan, at=AT)
        self.assertEqual(self.filesystem.mode_of(self.SKILL), self.filesystem.mode_for(executable=True))

    def test_an_update_is_recorded_with_the_new_fingerprint(self):
        applied = planner.apply(self.filesystem, self.plan_with(self.record()), at=AT)
        self.assertEqual(applied.records[0].after_digest, ownership.digest(self.artifact))

    def test_undoing_a_run_that_could_not_be_recorded_restores_and_leaves_alone(self):
        plan = self.plan_with(self.record())
        applied = planner.apply(self.filesystem, plan, at=AT)
        placed = self.installed(*applied.records)
        retired, failures = planner.unplace(self.filesystem, applied, placed)
        self.assertEqual(failures, [])
        self.assertEqual(self.SKILL.read_bytes(), self.previous)
        self.assertEqual(retired.removed, ())

    def test_what_would_not_go_back_is_not_retired_either(self):
        """Removing it would leave the user with neither version, which is worse."""
        plan = self.plan_with(self.record())
        applied = planner.apply(self.filesystem, plan, at=AT)
        self.addCleanup(make_unwritable(self.SKILL.parent))
        retired, failures = planner.unplace(self.filesystem, applied, self.installed(*applied.records))
        self.assertEqual([path for path, _ in failures], [self.SKILL])
        self.assertEqual(retired.removed, ())
        self.assertTrue(self.SKILL.exists())

    def test_a_failed_run_puts_the_previous_content_back(self):
        """An update has something to restore, so rolling it back is not a removal."""
        doomed = self.CONFIG / "skills/beta/SKILL.md"
        self.addCleanup(fail_next_write_once(doomed))
        plan = planner.plan(
            self.filesystem,
            cli=CLI,
            artifacts=[self.artifact, self.a_file("skill:beta", doomed, b"never lands")],
            installed=self.installed(self.record()),
        )
        with self.assertRaises(planner.PlannerError):
            planner.apply(self.filesystem, plan, at=AT)
        self.assertEqual(self.SKILL.read_bytes(), self.previous)


class KeyUpdateTest(RealHomeTestCase):
    """A configuration key Pegasus owns is updated in place; the user's is not touched.

    An append has the harder version of the question. It has no address, so its
    item is found by fingerprint, and a new value must replace the old one where
    it sits — appending instead would leave two of ours and reorder the user's.
    """

    def install(self, *entries: Record) -> Install:
        return Install(cli=CLI, installed_at=AT, config_dir=self.CONFIG, release={}, entries=entries)

    def entry(self, value, *, ptr="/agent/alpha", identifier="agent:alpha", **overrides) -> Record:
        fields = {
            "id": identifier,
            "kind": "config-key",
            "target": self.SETTINGS,
            "pointer": ptr,
            "codec": "json",
            "after_digest": ownership.digest_of_value(value),
            "created_at": AT,
        }
        return Record(**{**fields, **overrides})

    def given(self, payload):
        self.seed(files={self.SETTINGS: document(payload)})

    def plan_with(self, artifact, *entries: Record):
        return planner.plan(self.filesystem, cli=CLI, artifacts=[artifact], installed=self.install(*entries))

    def settings(self):
        return json.loads(self.SETTINGS.read_bytes())

    # --- An addressable key ---

    def test_a_value_pegasus_wrote_and_nobody_touched_is_an_update(self):
        old = {"model": "vendor/old"}
        self.given({"agent": {"alpha": old}})
        step = self.plan_with(self.a_key(), self.entry(old)).steps[0]
        self.assertEqual(step.action, planner.UPDATE)

    def test_applying_the_update_replaces_the_value(self):
        old = {"model": "vendor/old"}
        self.given({"agent": {"alpha": old}, "theirs": 1})
        planner.apply(self.filesystem, self.plan_with(self.a_key(), self.entry(old)), at=AT)
        self.assertEqual(self.settings()["agent"]["alpha"], {"model": "vendor/model"})
        self.assertEqual(self.settings()["theirs"], 1)

    def test_a_value_the_user_changed_is_overwritten_by_a_reinstall(self):
        self.given({"agent": {"alpha": {"model": "what the user chose"}}})
        step = self.plan_with(self.a_key(), self.entry({"model": "vendor/old"})).steps[0]
        self.assertEqual(step.action, planner.UPDATE)

    def test_a_value_the_journal_never_recorded_is_still_skipped(self):
        self.given({"agent": {"alpha": {"model": "vendor/old"}}})
        step = self.plan_with(self.a_key()).steps[0]
        self.assertEqual((step.action, step.reason), (planner.SKIP, planner.COLLISION))

    def test_a_value_already_in_place_is_left_alone(self):
        current = {"model": "vendor/model"}
        self.given({"agent": {"alpha": current}})
        step = self.plan_with(self.a_key(), self.entry(current)).steps[0]
        self.assertEqual(step.action, planner.UNCHANGED)

    # --- An append ---

    def an_append(self, value):
        return ConfigKeyArtifact(
            id="system-prompt-instruction", path=self.SETTINGS, pointer="/instructions/-", value=value
        )

    def test_an_append_whose_value_changed_is_replaced_where_it_sits(self):
        """Appending the new one instead would leave two of ours and move theirs."""
        self.given({"instructions": ["./theirs.md", "./pegasus-AGENTS.md", "./also-theirs.md"]})
        entry = self.entry("./pegasus-AGENTS.md", ptr="/instructions/-", identifier="system-prompt-instruction")
        plan = self.plan_with(self.an_append("./pegasus-baseline.md"), entry)
        self.assertEqual(plan.steps[0].action, planner.UPDATE)
        planner.apply(self.filesystem, plan, at=AT)
        self.assertEqual(
            self.settings()["instructions"], ["./theirs.md", "./pegasus-baseline.md", "./also-theirs.md"]
        )

    def test_an_append_already_holding_the_new_value_is_left_alone(self):
        self.given({"instructions": ["./pegasus-AGENTS.md"]})
        entry = self.entry("./pegasus-AGENTS.md", ptr="/instructions/-", identifier="system-prompt-instruction")
        step = self.plan_with(self.an_append("./pegasus-AGENTS.md"), entry).steps[0]
        self.assertEqual(step.action, planner.UNCHANGED)

    def test_the_document_goes_back_byte_for_byte_when_a_key_was_updated(self):
        """Same debt as an updated file, and it was half paid.

        Retiring an updated key removes it: the record has no ``before``, so
        removal is what retiring means — and the key was there, with the previous
        value, before this run.
        """
        old = {"model": "vendor/old"}
        self.given({"agent": {"alpha": old}, "theirs": 1})
        before = self.SETTINGS.read_bytes()
        applied = planner.apply(self.filesystem, self.plan_with(self.a_key(), self.entry(old)), at=AT)
        placed = self.install(*applied.records)
        _, failures = planner.unplace(self.filesystem, applied, placed)
        self.assertEqual(failures, [])
        self.assertEqual(self.SETTINGS.read_bytes(), before)

    def test_a_document_this_run_created_is_not_something_to_put_back(self):
        """Pegasus owns keys inside a configuration file, never the file itself."""
        applied = planner.apply(self.filesystem, self.plan_with(self.a_key()), at=AT)
        self.assertEqual(applied.replaced, ())

    def test_an_append_the_user_removed_is_placed_again(self):
        """Today's answer, kept on purpose: absence is a creation, not a verdict."""
        self.given({"instructions": ["./theirs.md"]})
        entry = self.entry("./pegasus-AGENTS.md", ptr="/instructions/-", identifier="system-prompt-instruction")
        plan = self.plan_with(self.an_append("./pegasus-AGENTS.md"), entry)
        self.assertEqual(plan.steps[0].action, planner.CREATE)
        planner.apply(self.filesystem, plan, at=AT)
        self.assertEqual(self.settings()["instructions"], ["./theirs.md", "./pegasus-AGENTS.md"])


class ApplyTest(RealHomeTestCase):
    def test_a_file_is_written_with_its_content_and_mode(self):
        planner.apply(self.filesystem, self.plan_for(self.a_file(content=b"body", executable=True)), at=AT)
        self.assertEqual(self.SKILL.read_bytes(), b"body")
        self.assertEqual(self.filesystem.mode_of(self.SKILL), self.filesystem.mode_for(executable=True))

    def test_several_keys_in_one_file_cost_a_single_write(self):
        artifacts = (self.a_key(), self.a_key(identifier="agent:beta", ptr="/agent/beta"))
        planner.apply(self.filesystem, self.plan_for(*artifacts), at=AT)
        self.assertEqual(self.filesystem.writes.count(self.SETTINGS), 1)

    def test_keys_the_user_already_had_are_preserved(self):
        self.seed(files={self.SETTINGS: document({"theme": "dark", "agent": {"theirs": {}}})})
        planner.apply(self.filesystem, self.plan_for(self.a_key()), at=AT)
        written = json.loads(self.SETTINGS.read_bytes())
        self.assertEqual(written["theme"], "dark")
        self.assertIn("theirs", written["agent"])
        self.assertEqual(written["agent"]["alpha"], {"model": "vendor/model"})

    def test_the_settings_file_keeps_the_permissions_it_had(self):
        self.seed(files={self.SETTINGS: document({})}, modes={self.SETTINGS: 0o600})
        planner.apply(self.filesystem, self.plan_for(self.a_key()), at=AT)
        self.assertEqual(self.filesystem.mode_of(self.SETTINGS), 0o600)

    def test_a_record_describes_what_was_written(self):
        artifact = self.a_file()
        applied = planner.apply(self.filesystem, self.plan_for(artifact), at=AT)
        record = applied.records[0]
        self.assertEqual(record.id, "skill:alpha")
        self.assertEqual(record.kind, "file")
        self.assertEqual(record.target, self.SKILL)
        self.assertEqual(record.after_digest, ownership.digest(artifact))
        self.assertEqual(record.created_at, AT)
        self.assertEqual(record.mode, "0644")

    def test_a_configuration_record_carries_its_pointer_and_codec(self):
        applied = planner.apply(self.filesystem, self.plan_for(self.a_key()), at=AT)
        record = applied.records[0]
        self.assertEqual(record.kind, "config-key")
        self.assertEqual(record.pointer, "/agent/alpha")
        self.assertEqual(record.codec, Codec.JSON.value)
        self.assertEqual(record.target, self.SETTINGS)

    def test_collisions_are_reported_and_never_written(self):
        self.seed(files={self.SKILL: b"theirs"})
        applied = planner.apply(self.filesystem, self.plan_for(self.a_file()), at=AT)
        self.assertEqual([step.artifact.id for step in applied.skipped], ["skill:alpha"])
        self.assertEqual(applied.records, ())
        self.assertEqual(self.SKILL.read_bytes(), b"theirs")

    def test_a_plan_that_is_all_collisions_writes_nothing(self):
        self.seed(files={self.SKILL: b"theirs"})
        planner.apply(self.filesystem, self.plan_for(self.a_file()), at=AT)
        self.assertEqual(self.filesystem.writes, [])

    # --- Rollback ---

    def test_a_failure_removes_the_files_this_run_created(self):
        doomed = self.CONFIG / "skills/beta/SKILL.md"
        self.addCleanup(fail_next_write_once(doomed))
        plan = self.plan_for(self.a_file(), self.a_file(identifier="skill:beta", path=doomed))
        with self.assertRaises(planner.PlannerError):
            planner.apply(self.filesystem, plan, at=AT)
        self.assertFalse(self.SKILL.exists())

    def test_a_failure_writing_configuration_restores_the_previous_content(self):
        before = document({"theme": "dark"})
        self.seed(files={self.SETTINGS: before})
        self.addCleanup(fail_next_write_once(self.SETTINGS))
        with self.assertRaises(planner.PlannerError):
            planner.apply(self.filesystem, self.plan_for(self.a_key()), at=AT)
        self.assertEqual(self.SETTINGS.read_bytes(), before)

    def test_a_rollback_that_cannot_finish_says_so_instead_of_hiding_it(self):
        """A home left half-installed is the one outcome worth interrupting someone for."""
        self.seed(files={self.SETTINGS: document({"theme": "dark"})})
        self.addCleanup(make_unwritable(self.SETTINGS.parent))
        with self.assertRaises(planner.PlannerError) as caught:
            planner.apply(self.filesystem, self.plan_for(self.a_key()), at=AT)
        self.assertIn("partial state", str(caught.exception))

    def test_the_original_cause_survives_a_failed_rollback(self):
        self.seed(files={self.SETTINGS: document({})})
        self.addCleanup(make_unwritable(self.SETTINGS.parent))
        with self.assertRaises(planner.PlannerError) as caught:
            planner.apply(self.filesystem, self.plan_for(self.a_key()), at=AT)
        # The real filesystem's own wording for the write it could not make,
        # rather than the double's "injected permanent failure".
        self.assertIn("Permission denied", str(caught.exception))

    def test_a_failure_removes_a_configuration_file_that_did_not_exist_before(self):
        other = self.CONFIG / "other.json"
        self.addCleanup(fail_next_write_once(other))
        plan = self.plan_for(self.a_key(), self.a_key(identifier="agent:beta", path=other))
        with self.assertRaises(planner.PlannerError):
            planner.apply(self.filesystem, plan, at=AT)
        self.assertFalse(other.exists())
        self.assertFalse(self.SETTINGS.exists())


class RollbackThatCannotFinishTest(RealHomeTestCase):
    def test_a_file_that_cannot_be_taken_back_out_is_reported_too(self):
        """The other half of the rollback: undoing a write can fail as easily as writing.

        Removing a path and creating one beside it answer to the same
        permission, so no mode can refuse only the removal — the first
        artifact has to be written before anything can refuse to take it
        back. Both failures are transient, and land on one call each.
        """
        doomed = self.CONFIG / "skills/beta/SKILL.md"
        self.addCleanup(fail_next_write_once(doomed))
        self.addCleanup(fail_next_removal_once(self.SKILL))
        plan = planner.plan(
            self.filesystem,
            cli=CLI,
            artifacts=[
                FileArtifact(id="skill:alpha", path=self.SKILL, content=b"hello", executable=False),
                FileArtifact(id="skill:beta", path=doomed, content=b"never lands", executable=False),
            ],
        )
        with self.assertRaises(planner.PlannerError) as caught:
            planner.apply(self.filesystem, plan, at=AT)
        self.assertIn("partial state", str(caught.exception))
        self.assertIn(str(self.SKILL), str(caught.exception))


class RetireTest(RealHomeTestCase):
    def install(self, *entries, links=()) -> Install:
        return Install(
            cli=CLI, installed_at=AT, config_dir=self.CONFIG, release={}, entries=tuple(entries), links=tuple(links)
        )

    def file_entry(self, content: bytes = b"hello", **overrides) -> Record:
        fields = dict(
            id="skill:alpha",
            kind="file",
            target=self.SKILL,
            after_digest=ownership.digest_of_bytes(content),
            created_at=AT,
            mode="0644",
        )
        fields.update(overrides)
        return Record(**fields)

    def key_entry(self, value=None, **overrides) -> Record:
        value = {"model": "vendor/model"} if value is None else value
        fields = dict(
            id="agent:alpha",
            kind="config-key",
            target=self.SETTINGS,
            pointer="/agent/alpha",
            codec="json",
            after_digest=ownership.digest_of_value(value),
            created_at=AT,
        )
        fields.update(overrides)
        return Record(**fields)

    def dependency_entry(self, **overrides) -> Record:
        fields = dict(
            id="dependency:some-mcp",
            kind="dependency-tree",
            target=self.home / "deps" / "some-mcp" / "1.2.3",
            after_digest="sha256:" + "1" * 64,
            created_at=AT,
        )
        fields.update(overrides)
        return Record(**fields)

    # --- Files ---

    def test_a_file_that_is_still_ours_is_removed(self):
        self.seed(files={self.SKILL: b"hello"})
        retired = planner.retire(self.filesystem, self.install(self.file_entry()))
        self.assertFalse(self.SKILL.exists())
        self.assertEqual(retired.removed, ("skill:alpha",))

    def test_a_file_the_user_edited_is_removed_too(self):
        """Uninstall removes without asking; the snapshot is the safety net, not this check."""
        self.seed(files={self.SKILL: b"edited by hand"})
        retired = planner.retire(self.filesystem, self.install(self.file_entry()))
        self.assertFalse(self.SKILL.exists())
        self.assertEqual(retired.removed, ("skill:alpha",))

    def test_a_file_already_gone_counts_as_retired(self):
        retired = planner.retire(self.filesystem, self.install(self.file_entry()))
        self.assertEqual(retired.removed, ("skill:alpha",))

    # --- Configuration keys ---

    def test_a_key_that_is_still_ours_is_unset(self):
        self.seed(files={self.SETTINGS: document({"theme": "dark", "agent": {"alpha": {"model": "vendor/model"}}})})
        retired = planner.retire(self.filesystem, self.install(self.key_entry()))
        written = json.loads(self.SETTINGS.read_bytes())
        self.assertEqual(written, {"theme": "dark"})
        self.assertEqual(retired.removed, ("agent:alpha",))

    def test_a_key_the_user_edited_is_removed_too(self):
        payload = {"agent": {"alpha": {"model": "theirs"}}}
        self.seed(files={self.SETTINGS: document(payload)})
        retired = planner.retire(self.filesystem, self.install(self.key_entry()))
        self.assertEqual(json.loads(self.SETTINGS.read_bytes()), {})
        self.assertEqual(retired.removed, ("agent:alpha",))

    def test_the_settings_file_keeps_its_permissions_when_retired(self):
        self.seed(
            files={self.SETTINGS: document({"agent": {"alpha": {"model": "vendor/model"}}})},
            modes={self.SETTINGS: 0o600},
        )
        planner.retire(self.filesystem, self.install(self.key_entry()))
        self.assertEqual(self.filesystem.mode_of(self.SETTINGS), 0o600)

    def test_a_configuration_file_the_user_deleted_is_not_recreated(self):
        retired = planner.retire(self.filesystem, self.install(self.key_entry()))
        self.assertFalse(self.SETTINGS.exists())
        self.assertEqual(retired.removed, ("agent:alpha",))

    def test_a_malformed_configuration_file_is_refused_rather_than_rewritten(self):
        self.seed(files={self.SETTINGS: b"{ not json"})
        with self.assertRaises(planner.PlannerError):
            planner.retire(self.filesystem, self.install(self.key_entry()))

    def test_retiring_a_file_whose_existence_cannot_be_told_refuses_rather_than_skipping_the_removal(self):
        """`retire`'s files loop reads `filesystem.exists` as the gate for
        whether there is anything to remove. A probe failure taking the
        "nothing to remove" branch would still report the entry as removed
        while the file — unreadably permissioned, not gone — sits there
        untouched, which is exactly the deceptive-report failure mode this
        unit exists to close."""
        self.seed(files={self.SKILL: b"hello"})
        self.addCleanup(make_unreadable(self.SKILL.parent))
        with self.assertRaises(FileSystemError):
            planner.retire(self.filesystem, self.install(self.file_entry()))

    def test_a_file_nothing_was_retired_from_is_left_exactly_as_it_was(self):
        """Unsetting a key that is not there does not touch the document at all."""
        theirs = b'{\n    "theme": "dark"\n}\n'
        self.seed(files={self.SETTINGS: theirs})
        retired = planner.retire(self.filesystem, self.install(self.key_entry()))
        self.assertEqual(self.SETTINGS.read_bytes(), theirs)
        self.assertEqual(self.filesystem.writes, [])
        self.assertEqual(retired.removed, ("agent:alpha",))

    # --- Dependency trees ---

    def test_a_dependency_tree_that_is_still_ours_is_removed(self):
        target = self.dependency_entry().target
        target.mkdir(parents=True)
        (target / "package.json").write_bytes(b"{}")
        (target / "lib").mkdir()
        (target / "lib" / "index.js").write_bytes(b"module.exports = {};")
        retired = planner.retire(self.filesystem, self.install(self.dependency_entry()))
        self.assertFalse(target.exists())
        self.assertEqual(retired.removed, ("dependency:some-mcp",))

    def test_a_dependency_tree_already_gone_counts_as_retired(self):
        retired = planner.retire(self.filesystem, self.install(self.dependency_entry()))
        self.assertEqual(retired.removed, ("dependency:some-mcp",))

    # --- Kinds retirement does not know about ---

    def test_an_entry_of_an_unrecognized_kind_cannot_vanish_silently(self):
        """Before the kind-keyed dispatch, `retire` filtered `install.entries`
        into a files list and a config-key list by hand; an entry whose kind
        matched neither filter fell through both and was never removed and
        never reported, not even as unaccounted. Building the buckets from
        `journal.KINDS` itself means a kind the journal never validated
        (forged here to prove the point, since real journals reject anything
        outside `KINDS`) blows up loudly instead of disappearing quietly."""
        mystery = self.file_entry(id="mystery:one", kind="not-a-real-kind")
        with self.assertRaises(KeyError):
            planner.retire(self.filesystem, self.install(mystery))

    # --- Links ---

    def test_a_link_is_never_removed(self):
        link = Link(id="cbm", target="/usr/local/bin/some-tool")
        retired = planner.retire(self.filesystem, self.install(links=(link,)))
        self.assertEqual(self.filesystem.removals, [])
        self.assertEqual(retired.kept_links, ("cbm",))

    # --- Idempotence ---

    def test_retiring_twice_is_the_same_as_retiring_once(self):
        """Uninstall has no rollback, so it earns its safety by repeating cleanly."""
        payload = {"agent": {"alpha": {"model": "vendor/model"}}}
        self.seed(files={self.SKILL: b"hello", self.SETTINGS: document(payload)})
        install = self.install(self.file_entry(), self.key_entry())
        first = planner.retire(self.filesystem, install)
        second = planner.retire(self.filesystem, install)
        self.assertEqual(first.removed, second.removed)
        self.assertEqual(second.unaccounted, ())


class _DefaultModeSpy:
    """Records the mode an undo path actually asked for, if any.

    Standing in for the one case ``mode_of`` cannot rule out today: an
    existing file whose permission bits could not be observed even though its
    content just was. Real disk cannot manufacture that condition on demand,
    so this narrow double is what proves a rollback defers the choice to
    whichever filesystem it is given instead of hard-coding one of its own —
    its distinctive default would never be mistaken for a value planner.py
    picked itself.
    """

    DISTINCTIVE_DEFAULT = 0o750

    def __init__(self):
        self.applied_modes: list[int] = []

    def write_atomic(self, path: Path, content: bytes, *, mode: int = DISTINCTIVE_DEFAULT) -> None:
        self.applied_modes.append(mode)

    def remove(self, path: Path) -> None:
        pass


class RollbackDefersAnUnknownModeTest(unittest.TestCase):
    """The three call sites that used to fall back to a bare ``0o644``."""

    def test_undo_omits_the_mode_when_none_was_captured(self):
        spy = _DefaultModeSpy()
        planner._undo(spy, created=[], restorable={Path("/tmp/x"): (b"content", None)})
        self.assertEqual(spy.applied_modes, [_DefaultModeSpy.DISTINCTIVE_DEFAULT])

    def test_undo_still_honours_a_mode_that_was_captured(self):
        spy = _DefaultModeSpy()
        planner._undo(spy, created=[], restorable={Path("/tmp/x"): (b"content", 0o600)})
        self.assertEqual(spy.applied_modes, [0o600])

    def test_put_back_omits_the_mode_when_none_was_captured(self):
        spy = _DefaultModeSpy()
        applied = planner.Applied(records=(), skipped=(), replaced=((Path("/tmp/x"), b"content", None),))
        planner._put_back(spy, applied)
        self.assertEqual(spy.applied_modes, [_DefaultModeSpy.DISTINCTIVE_DEFAULT])

    def test_write_document_omits_the_mode_for_a_document_created_for_the_first_time(self):
        spy = _DefaultModeSpy()
        planner._write_document(spy, Path("/tmp/settings.json"), {}, Codec.JSON, None)
        self.assertEqual(spy.applied_modes, [_DefaultModeSpy.DISTINCTIVE_DEFAULT])

    def test_write_document_still_honours_a_mode_that_was_observed(self):
        spy = _DefaultModeSpy()
        planner._write_document(spy, Path("/tmp/settings.json"), {}, Codec.JSON, 0o640)
        self.assertEqual(spy.applied_modes, [0o640])


if __name__ == "__main__":
    unittest.main()


class ReconciliationTest(unittest.TestCase):
    """What the journal says has to survive a run that wrote nothing.

    `install` decides an artifact is already current by comparing what it wants
    against what is on disk. `doctor` decides an artifact has drifted by
    comparing what is on disk against the digest the journal recorded. Those
    two answers agree until a hand edit lands on exactly the bytes a later
    release renders: the disk is right, so nothing is written, so the journal
    keeps a digest from before -- and `doctor` reports drift forever, because
    every later run reaches the same conclusion and writes nothing again.

    An unchanged step already carries both halves of the answer: the digest of
    what is wanted, and the journal entry it was judged against. So the record
    costs no disk access at all -- it is the one the journal should already
    have had.
    """

    def setUp(self):
        self.filesystem = fakes.FakeFileSystem()

    def artifact(self, content: bytes = b"body\n"):
        return FileArtifact(id="probe", path=Path("/home/probe.md"), content=content, executable=False)

    def stale_install(self, artifact, digest: str):
        return Install(
            cli="probe-cli",
            installed_at=AT,
            config_dir=Path("/home"),
            release={},
            entries=(
                Record(
                    id=artifact.id,
                    kind="file",
                    target=artifact.path,
                    after_digest=digest,
                    created_at=AT,
                ),
            ),
        )

    def test_an_unchanged_artifact_whose_record_disagrees_is_recorded_again(self):
        artifact = self.artifact()
        self.filesystem.write_atomic(artifact.path, artifact.content)
        installed = self.stale_install(artifact, "sha256:" + "0" * 64)
        plan = planner.plan(self.filesystem, cli="probe-cli", artifacts=[artifact], installed=installed)
        self.assertEqual([step.action for step in plan.steps], [planner.UNCHANGED])
        applied = planner.apply(self.filesystem, plan, at=AT)
        self.assertEqual(applied.records, ())
        self.assertEqual([record.id for record in applied.reconciled], ["probe"])
        self.assertEqual(applied.reconciled[0].after_digest, plan.steps[0].digest)

    def test_an_unchanged_artifact_whose_record_already_agrees_is_left_alone(self):
        """Reconciling what needs no reconciling would put a write in the
        journal on every run of an install that did nothing at all."""
        artifact = self.artifact()
        self.filesystem.write_atomic(artifact.path, artifact.content)
        digest = ownership.digest(artifact)
        plan = planner.plan(
            self.filesystem,
            cli="probe-cli",
            artifacts=[artifact],
            installed=self.stale_install(artifact, digest),
        )
        applied = planner.apply(self.filesystem, plan, at=AT)
        self.assertEqual(applied.reconciled, ())

    def test_a_reconciled_record_keeps_the_date_the_artifact_was_first_placed(self):
        artifact = self.artifact()
        self.filesystem.write_atomic(artifact.path, artifact.content)
        installed = self.stale_install(artifact, "sha256:" + "0" * 64)
        first = installed.entries[0].created_at
        plan = planner.plan(self.filesystem, cli="probe-cli", artifacts=[artifact], installed=installed)
        applied = planner.apply(self.filesystem, plan, at="2099-01-01T00:00:00Z")
        self.assertEqual(applied.reconciled[0].created_at, first)

    def test_reconciling_writes_nothing_to_disk(self):
        """The whole point: the bytes were already right."""
        artifact = self.artifact()
        self.filesystem.write_atomic(artifact.path, artifact.content)
        plan = planner.plan(
            self.filesystem,
            cli="probe-cli",
            artifacts=[artifact],
            installed=self.stale_install(artifact, "sha256:" + "0" * 64),
        )
        before = self.filesystem.read_bytes(artifact.path)
        planner.apply(self.filesystem, plan, at=AT)
        self.assertEqual(self.filesystem.read_bytes(artifact.path), before)
