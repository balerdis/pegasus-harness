"""Planning, applying and retiring an installation.

Three properties are what these tests are really about:

**Additive.** Anything already there is left alone and reported, never
negotiated with.

**All or nothing.** A run that fails half way undoes what it created, so the
journal never describes a home that does not exist.

**Retirable.** What Pegasus recorded, Pegasus can take back — and only that.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from fakes import FakeFileSystem
from pegasus.core import ownership, planner
from pegasus.core.journal import Install, Link, Record
from pegasus.core.types import Codec, ConfigKeyArtifact, FileArtifact

HOME = Path("/home/probe")
CONFIG = HOME / ".config" / "some-cli"
SETTINGS = CONFIG / "settings.json"
SKILL = CONFIG / "skills/alpha/SKILL.md"
AT = "2026-08-14T00:00:00+00:00"
CLI = "some-cli"


def a_file(identifier: str = "skill:alpha", path: Path = SKILL, content: bytes = b"hello", mode: int = 0o644):
    return FileArtifact(id=identifier, path=path, content=content, mode=mode)


def a_key(identifier: str = "agent:alpha", ptr: str = "/agent/alpha", value=None, path: Path = SETTINGS):
    return ConfigKeyArtifact(
        id=identifier, path=path, pointer=ptr, value={"model": "vendor/model"} if value is None else value
    )


def document(payload) -> bytes:
    return (json.dumps(payload, indent=2) + "\n").encode("utf-8")


def plan_for(filesystem, *artifacts):
    return planner.plan(filesystem, cli=CLI, artifacts=list(artifacts))


class PlanTest(unittest.TestCase):
    def test_a_free_path_is_planned_as_a_creation(self):
        result = plan_for(FakeFileSystem(), a_file())
        self.assertEqual([step.action for step in result.steps], [planner.CREATE])

    def test_an_occupied_path_is_skipped(self):
        result = plan_for(FakeFileSystem(files={SKILL: b"theirs"}), a_file())
        step = result.steps[0]
        self.assertEqual(step.action, planner.SKIP)
        self.assertEqual(step.reason, planner.COLLISION)

    def test_a_free_pointer_is_planned_as_a_creation(self):
        filesystem = FakeFileSystem(files={SETTINGS: document({"agent": {}})})
        self.assertEqual([step.action for step in plan_for(filesystem, a_key()).steps], [planner.CREATE])

    def test_an_occupied_pointer_is_skipped(self):
        filesystem = FakeFileSystem(files={SETTINGS: document({"agent": {"alpha": {"model": "theirs"}}})})
        self.assertEqual([step.action for step in plan_for(filesystem, a_key()).steps], [planner.SKIP])

    def test_a_pointer_in_a_file_that_does_not_exist_yet_is_a_creation(self):
        self.assertEqual([step.action for step in plan_for(FakeFileSystem(), a_key()).steps], [planner.CREATE])

    def test_planning_writes_nothing(self):
        filesystem = FakeFileSystem()
        plan_for(filesystem, a_file(), a_key())
        self.assertEqual(filesystem.writes, [])
        self.assertEqual(filesystem.files, {})

    def test_every_step_carries_the_fingerprint_of_what_it_would_place(self):
        artifact = a_file()
        step = plan_for(FakeFileSystem(), artifact).steps[0]
        self.assertEqual(step.digest, ownership.digest(artifact))

    def test_creations_and_collisions_are_separable(self):
        filesystem = FakeFileSystem(files={SKILL: b"theirs"})
        result = plan_for(filesystem, a_file(), a_key())
        self.assertEqual([step.artifact.id for step in result.creations], ["agent:alpha"])
        self.assertEqual([step.artifact.id for step in result.collisions], ["skill:alpha"])

    # --- Failing closed ---

    def test_a_malformed_configuration_file_is_refused(self):
        """Guessing at a file we cannot parse is how a user's settings get lost."""
        filesystem = FakeFileSystem(files={SETTINGS: b"{ not json"})
        with self.assertRaises(planner.PlannerError):
            plan_for(filesystem, a_key())

    def test_two_artifacts_with_the_same_id_are_refused(self):
        with self.assertRaises(planner.PlannerError):
            plan_for(FakeFileSystem(), a_file(), a_file(path=CONFIG / "other.md"))

    def test_two_artifacts_claiming_the_same_path_are_refused(self):
        with self.assertRaises(planner.PlannerError):
            plan_for(FakeFileSystem(), a_file(), a_file(identifier="skill:beta"))

    def test_two_artifacts_claiming_the_same_pointer_are_refused(self):
        with self.assertRaises(planner.PlannerError):
            plan_for(FakeFileSystem(), a_key(), a_key(identifier="agent:beta"))

    def test_an_unsupported_artifact_shape_is_refused(self):
        with self.assertRaises(planner.PlannerError):
            plan_for(FakeFileSystem(), object())


class AppendTest(unittest.TestCase):
    """Appending to a list is a create with no address of its own.

    Nothing resolves at ``/instructions/-``, so the ordinary collision question
    cannot be asked. The fingerprint answers it instead: an item Pegasus already
    placed is one it must not place twice, and on the way out it is found by
    what it is rather than by where it sits, because indices move.
    """

    def append(self, value: str = "./pegasus-AGENTS.md"):
        return ConfigKeyArtifact(
            id="system-prompt-instruction", path=SETTINGS, pointer="/instructions/-", value=value
        )

    def append_as(self, identifier: str, value: str = "./pegasus-AGENTS.md"):
        return ConfigKeyArtifact(id=identifier, path=SETTINGS, pointer="/instructions/-", value=value)

    def entry(self, value: str = "./pegasus-AGENTS.md") -> Record:
        return Record(
            id="system-prompt-instruction",
            kind="config-key",
            target=SETTINGS,
            pointer="/instructions/-",
            codec="json",
            after_digest=ownership.digest_of_value(value),
            created_at=AT,
        )

    def install(self, *entries) -> Install:
        return Install(cli=CLI, installed_at=AT, config_dir=CONFIG, release={}, entries=tuple(entries))

    def test_appending_into_a_missing_list_creates_it(self):
        filesystem = FakeFileSystem()
        planner.apply(filesystem, plan_for(filesystem, self.append()), at=AT)
        self.assertEqual(json.loads(filesystem.files[SETTINGS])["instructions"], ["./pegasus-AGENTS.md"])

    def test_an_item_already_in_the_list_is_a_collision(self):
        """Otherwise reinstalling would append the same instruction twice."""
        filesystem = FakeFileSystem(files={SETTINGS: document({"instructions": ["./pegasus-AGENTS.md"]})})
        self.assertEqual([step.action for step in plan_for(filesystem, self.append()).steps], [planner.SKIP])

    def test_an_item_the_user_placed_alongside_ours_does_not_block_us(self):
        filesystem = FakeFileSystem(files={SETTINGS: document({"instructions": ["./theirs.md"]})})
        planner.apply(filesystem, plan_for(filesystem, self.append()), at=AT)
        self.assertEqual(
            json.loads(filesystem.files[SETTINGS])["instructions"], ["./theirs.md", "./pegasus-AGENTS.md"]
        )

    def test_retiring_an_append_removes_our_item_and_leaves_theirs(self):
        payload = {"instructions": ["./theirs.md", "./pegasus-AGENTS.md", "./another.md"]}
        filesystem = FakeFileSystem(files={SETTINGS: document(payload)})
        retired = planner.retire(filesystem, self.install(self.entry()))
        self.assertEqual(
            json.loads(filesystem.files[SETTINGS])["instructions"], ["./theirs.md", "./another.md"]
        )
        self.assertEqual(retired.removed, ("system-prompt-instruction",))

    def test_retiring_an_append_finds_our_item_after_the_user_reordered_the_list(self):
        payload = {"instructions": ["./pegasus-AGENTS.md", "./theirs.md"]}
        filesystem = FakeFileSystem(files={SETTINGS: document(payload)})
        planner.retire(filesystem, self.install(self.entry()))
        self.assertEqual(json.loads(filesystem.files[SETTINGS])["instructions"], ["./theirs.md"])

    def test_an_append_we_cannot_find_is_reported_as_unaccounted_not_as_removed(self):
        """Saying "removed" would claim we did something we did not do.

        A list item has no address of its own, so a fingerprint that matches
        nothing is genuinely ambiguous: the user may have deleted our item, or
        edited it into something we can no longer recognise as ours. Both leave
        the list correct and neither is a removal, so they get their own answer
        instead of being flattened into one of the other three.
        """
        filesystem = FakeFileSystem(files={SETTINGS: document({"instructions": ["./theirs.md"]})})
        retired = planner.retire(filesystem, self.install(self.entry()))
        self.assertEqual(retired.unaccounted, ("system-prompt-instruction",))
        self.assertEqual(retired.removed, ())
        self.assertEqual(json.loads(filesystem.files[SETTINGS])["instructions"], ["./theirs.md"])

    def test_an_append_the_user_edited_in_place_is_left_alone_and_reported(self):
        edited = {"instructions": ["./theirs.md", "./the-user-renamed-this.md"]}
        filesystem = FakeFileSystem(files={SETTINGS: document(edited)})
        retired = planner.retire(filesystem, self.install(self.entry()))
        self.assertEqual(retired.unaccounted, ("system-prompt-instruction",))
        self.assertEqual(json.loads(filesystem.files[SETTINGS]), edited)
        self.assertEqual(filesystem.writes, [])

    def test_an_append_whose_whole_list_is_gone_is_unaccounted_too(self):
        filesystem = FakeFileSystem(files={SETTINGS: document({"theme": "dark"})})
        retired = planner.retire(filesystem, self.install(self.entry()))
        self.assertEqual(retired.unaccounted, ("system-prompt-instruction",))

    def test_an_append_still_ours_is_removed_and_not_reported_as_unaccounted(self):
        filesystem = FakeFileSystem(files={SETTINGS: document({"instructions": ["./pegasus-AGENTS.md"]})})
        retired = planner.retire(filesystem, self.install(self.entry()))
        self.assertEqual(retired.removed, ("system-prompt-instruction",))
        self.assertEqual(retired.unaccounted, ())

    def test_two_artifacts_appending_the_same_value_are_refused(self):
        """They would place the same item twice, and nothing later could tell them apart."""
        with self.assertRaises(planner.PlannerError):
            plan_for(FakeFileSystem(), self.append(), self.append_as("other-id"))

    def test_two_artifacts_appending_different_values_are_allowed(self):
        result = plan_for(FakeFileSystem(), self.append(), self.append_as("other-id", "./another.md"))
        self.assertEqual([step.action for step in result.steps], [planner.CREATE, planner.CREATE])

    def test_retiring_the_only_item_leaves_no_empty_list_behind(self):
        filesystem = FakeFileSystem(files={SETTINGS: document({"instructions": ["./pegasus-AGENTS.md"]})})
        planner.retire(filesystem, self.install(self.entry()))
        self.assertEqual(json.loads(filesystem.files[SETTINGS]), {})


class ApplyTest(unittest.TestCase):
    def test_a_file_is_written_with_its_content_and_mode(self):
        filesystem = FakeFileSystem()
        planner.apply(filesystem, plan_for(filesystem, a_file(content=b"body", mode=0o600)), at=AT)
        self.assertEqual(filesystem.files[SKILL], b"body")
        self.assertEqual(filesystem.modes[SKILL], 0o600)

    def test_several_keys_in_one_file_cost_a_single_write(self):
        filesystem = FakeFileSystem()
        artifacts = (a_key(), a_key(identifier="agent:beta", ptr="/agent/beta"))
        planner.apply(filesystem, plan_for(filesystem, *artifacts), at=AT)
        self.assertEqual(filesystem.writes.count(SETTINGS), 1)

    def test_keys_the_user_already_had_are_preserved(self):
        filesystem = FakeFileSystem(files={SETTINGS: document({"theme": "dark", "agent": {"theirs": {}}})})
        planner.apply(filesystem, plan_for(filesystem, a_key()), at=AT)
        written = json.loads(filesystem.files[SETTINGS])
        self.assertEqual(written["theme"], "dark")
        self.assertIn("theirs", written["agent"])
        self.assertEqual(written["agent"]["alpha"], {"model": "vendor/model"})

    def test_the_settings_file_keeps_the_permissions_it_had(self):
        filesystem = FakeFileSystem(files={SETTINGS: document({})}, modes={SETTINGS: 0o600})
        planner.apply(filesystem, plan_for(filesystem, a_key()), at=AT)
        self.assertEqual(filesystem.modes[SETTINGS], 0o600)

    def test_a_record_describes_what_was_written(self):
        filesystem = FakeFileSystem()
        artifact = a_file()
        applied = planner.apply(filesystem, plan_for(filesystem, artifact), at=AT)
        record = applied.records[0]
        self.assertEqual(record.id, "skill:alpha")
        self.assertEqual(record.kind, "file")
        self.assertEqual(record.target, SKILL)
        self.assertEqual(record.after_digest, ownership.digest(artifact))
        self.assertIsNone(record.before)
        self.assertEqual(record.created_at, AT)
        self.assertEqual(record.mode, "0644")

    def test_a_configuration_record_carries_its_pointer_and_codec(self):
        filesystem = FakeFileSystem()
        applied = planner.apply(filesystem, plan_for(filesystem, a_key()), at=AT)
        record = applied.records[0]
        self.assertEqual(record.kind, "config-key")
        self.assertEqual(record.pointer, "/agent/alpha")
        self.assertEqual(record.codec, Codec.JSON.value)
        self.assertEqual(record.target, SETTINGS)

    def test_nothing_pegasus_owns_starts_out_adopted(self):
        """Install only ever creates what was missing, so before is always null."""
        filesystem = FakeFileSystem()
        applied = planner.apply(filesystem, plan_for(filesystem, a_file(), a_key()), at=AT)
        self.assertTrue(all(record.before is None and not record.adopted for record in applied.records))

    def test_collisions_are_reported_and_never_written(self):
        filesystem = FakeFileSystem(files={SKILL: b"theirs"})
        applied = planner.apply(filesystem, plan_for(filesystem, a_file()), at=AT)
        self.assertEqual([step.artifact.id for step in applied.skipped], ["skill:alpha"])
        self.assertEqual(applied.records, ())
        self.assertEqual(filesystem.files[SKILL], b"theirs")

    def test_a_plan_that_is_all_collisions_writes_nothing(self):
        filesystem = FakeFileSystem(files={SKILL: b"theirs"})
        planner.apply(filesystem, plan_for(filesystem, a_file()), at=AT)
        self.assertEqual(filesystem.writes, [])

    # --- Rollback ---

    def test_a_failure_removes_the_files_this_run_created(self):
        doomed = CONFIG / "skills/beta/SKILL.md"
        filesystem = FakeFileSystem(fail_on={doomed})
        plan = plan_for(filesystem, a_file(), a_file(identifier="skill:beta", path=doomed))
        with self.assertRaises(planner.PlannerError):
            planner.apply(filesystem, plan, at=AT)
        self.assertNotIn(SKILL, filesystem.files)

    def test_a_failure_writing_configuration_restores_the_previous_content(self):
        before = document({"theme": "dark"})
        filesystem = FakeFileSystem(files={SETTINGS: before}, fail_on={SETTINGS})
        with self.assertRaises(planner.PlannerError):
            planner.apply(filesystem, plan_for(filesystem, a_key()), at=AT)
        self.assertEqual(filesystem.files[SETTINGS], before)

    def test_a_rollback_that_cannot_finish_says_so_instead_of_hiding_it(self):
        """A home left half-installed is the one outcome worth interrupting someone for."""
        filesystem = FakeFileSystem(files={SETTINGS: document({"theme": "dark"})}, fail_always={SETTINGS})
        with self.assertRaises(planner.PlannerError) as caught:
            planner.apply(filesystem, plan_for(filesystem, a_key()), at=AT)
        self.assertIn("partial state", str(caught.exception))

    def test_a_file_that_cannot_be_taken_back_out_is_reported_too(self):
        """The other half of the rollback: undoing a write can fail as easily as writing."""
        doomed = CONFIG / "skills/beta/SKILL.md"
        filesystem = FakeFileSystem(fail_on={doomed}, fail_remove={SKILL})
        plan = plan_for(filesystem, a_file(), a_file(identifier="skill:beta", path=doomed))
        with self.assertRaises(planner.PlannerError) as caught:
            planner.apply(filesystem, plan, at=AT)
        self.assertIn("partial state", str(caught.exception))
        self.assertIn(str(SKILL), str(caught.exception))

    def test_the_original_cause_survives_a_failed_rollback(self):
        filesystem = FakeFileSystem(files={SETTINGS: document({})}, fail_always={SETTINGS})
        with self.assertRaises(planner.PlannerError) as caught:
            planner.apply(filesystem, plan_for(filesystem, a_key()), at=AT)
        self.assertIn("injected permanent failure", str(caught.exception))

    def test_a_failure_removes_a_configuration_file_that_did_not_exist_before(self):
        other = CONFIG / "other.json"
        filesystem = FakeFileSystem(fail_on={other})
        plan = plan_for(filesystem, a_key(), a_key(identifier="agent:beta", path=other))
        with self.assertRaises(planner.PlannerError):
            planner.apply(filesystem, plan, at=AT)
        self.assertNotIn(other, filesystem.files)
        self.assertNotIn(SETTINGS, filesystem.files)


class RetireTest(unittest.TestCase):
    def install(self, *entries, links=()) -> Install:
        return Install(
            cli=CLI, installed_at=AT, config_dir=CONFIG, release={}, entries=tuple(entries), links=tuple(links)
        )

    def file_entry(self, content: bytes = b"hello", **overrides) -> Record:
        fields = dict(
            id="skill:alpha",
            kind="file",
            target=SKILL,
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
            target=SETTINGS,
            pointer="/agent/alpha",
            codec="json",
            after_digest=ownership.digest_of_value(value),
            created_at=AT,
        )
        fields.update(overrides)
        return Record(**fields)

    # --- Files ---

    def test_a_file_that_is_still_ours_is_removed(self):
        filesystem = FakeFileSystem(files={SKILL: b"hello"})
        retired = planner.retire(filesystem, self.install(self.file_entry()))
        self.assertNotIn(SKILL, filesystem.files)
        self.assertEqual(retired.removed, ("skill:alpha",))

    def test_a_file_the_user_edited_is_preserved_and_reported(self):
        filesystem = FakeFileSystem(files={SKILL: b"edited by hand"})
        retired = planner.retire(filesystem, self.install(self.file_entry()))
        self.assertEqual(filesystem.files[SKILL], b"edited by hand")
        self.assertEqual(retired.preserved, ("skill:alpha",))
        self.assertEqual(retired.removed, ())

    def test_a_file_already_gone_counts_as_retired(self):
        retired = planner.retire(FakeFileSystem(), self.install(self.file_entry()))
        self.assertEqual(retired.removed, ("skill:alpha",))

    def test_a_file_recorded_as_adopted_is_refused(self):
        """Adoption is a configuration-key affordance; a file with it is corruption."""
        filesystem = FakeFileSystem(files={SKILL: b"hello"})
        with self.assertRaises(planner.PlannerError):
            planner.retire(filesystem, self.install(self.file_entry(before="something")))

    # --- Configuration keys ---

    def test_a_key_that_is_still_ours_is_unset(self):
        filesystem = FakeFileSystem(
            files={SETTINGS: document({"theme": "dark", "agent": {"alpha": {"model": "vendor/model"}}})}
        )
        retired = planner.retire(filesystem, self.install(self.key_entry()))
        written = json.loads(filesystem.files[SETTINGS])
        self.assertEqual(written, {"theme": "dark"})
        self.assertEqual(retired.removed, ("agent:alpha",))

    def test_a_key_the_user_edited_is_preserved_and_reported(self):
        payload = {"agent": {"alpha": {"model": "theirs"}}}
        filesystem = FakeFileSystem(files={SETTINGS: document(payload)})
        retired = planner.retire(filesystem, self.install(self.key_entry()))
        self.assertEqual(json.loads(filesystem.files[SETTINGS]), payload)
        self.assertEqual(retired.preserved, ("agent:alpha",))

    def test_an_adopted_key_is_restored_to_what_the_user_had(self):
        theirs = {"model": "theirs", "temperature": 0.2}
        current = {"agent": {"alpha": {"model": "vendor/model"}}}
        filesystem = FakeFileSystem(files={SETTINGS: document(current)})
        entry = self.key_entry(before=theirs, adopted=True)
        retired = planner.retire(filesystem, self.install(entry))
        self.assertEqual(json.loads(filesystem.files[SETTINGS])["agent"]["alpha"], theirs)
        self.assertEqual(retired.restored, ("agent:alpha",))

    def test_the_settings_file_keeps_its_permissions_when_retired(self):
        filesystem = FakeFileSystem(
            files={SETTINGS: document({"agent": {"alpha": {"model": "vendor/model"}}})}, modes={SETTINGS: 0o600}
        )
        planner.retire(filesystem, self.install(self.key_entry()))
        self.assertEqual(filesystem.modes[SETTINGS], 0o600)

    def test_a_configuration_file_the_user_deleted_is_not_recreated(self):
        filesystem = FakeFileSystem()
        retired = planner.retire(filesystem, self.install(self.key_entry()))
        self.assertEqual(filesystem.files, {})
        self.assertEqual(retired.removed, ("agent:alpha",))

    def test_a_malformed_configuration_file_is_refused_rather_than_rewritten(self):
        filesystem = FakeFileSystem(files={SETTINGS: b"{ not json"})
        with self.assertRaises(planner.PlannerError):
            planner.retire(filesystem, self.install(self.key_entry()))

    def test_a_file_nothing_was_retired_from_is_left_exactly_as_it_was(self):
        """Rewriting it would reformat the user's spacing for no reason."""
        theirs = b'{\n    "agent": {\n        "alpha": {"model": "theirs"}\n    }\n}\n'
        filesystem = FakeFileSystem(files={SETTINGS: theirs})
        planner.retire(filesystem, self.install(self.key_entry()))
        self.assertEqual(filesystem.files[SETTINGS], theirs)
        self.assertEqual(filesystem.writes, [])

    # --- Links ---

    def test_a_link_is_never_removed(self):
        link = Link(id="cbm", target="/usr/local/bin/some-tool")
        filesystem = FakeFileSystem()
        retired = planner.retire(filesystem, self.install(links=(link,)))
        self.assertEqual(filesystem.removals, [])
        self.assertEqual(retired.kept_links, ("cbm",))

    # --- Idempotence ---

    def test_retiring_twice_is_the_same_as_retiring_once(self):
        """Uninstall has no rollback, so it earns its safety by repeating cleanly."""
        payload = {"agent": {"alpha": {"model": "vendor/model"}}}
        filesystem = FakeFileSystem(files={SKILL: b"hello", SETTINGS: document(payload)})
        install = self.install(self.file_entry(), self.key_entry())
        first = planner.retire(filesystem, install)
        second = planner.retire(filesystem, install)
        self.assertEqual(first.removed, second.removed)
        self.assertEqual(second.preserved, ())


if __name__ == "__main__":
    unittest.main()
