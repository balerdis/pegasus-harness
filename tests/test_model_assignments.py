"""The per-agent model preference, pure: no store, no filesystem.

Mirrors the discipline `test_journal.py`-style modules hold the ownership
journal to: types, serialization and functional updates proven without disk.
"""
from __future__ import annotations

import unittest

from pegasus.core import model_assignments as module
from pegasus.core.model_assignments import Entry, ModelAssignmentError, ModelAssignments
from pegasus.core.model_catalog import Model, ModelCatalog, Provider
from pegasus.core.types import ModelAssignment


def assignment(model="claude-sonnet-5", effort=None) -> ModelAssignment:
    return ModelAssignment(provider_id="anthropic", model_id=model, effort=effort)


class EmptyTest(unittest.TestCase):
    def test_empty_has_no_entries_and_the_current_schema(self):
        assignments = module.empty()
        self.assertEqual(assignments.entries, ())
        self.assertEqual(assignments.schema, module.SCHEMA)

    def test_getting_from_empty_is_none_not_an_error(self):
        self.assertIsNone(module.get(module.empty(), "opencode", "sdd-apply"))


class WithAssignmentTest(unittest.TestCase):
    def test_setting_one_agent_can_be_read_back(self):
        assignments = module.with_assignment(module.empty(), "opencode", "sdd-apply", assignment())
        self.assertEqual(module.get(assignments, "opencode", "sdd-apply"), assignment())

    def test_setting_again_replaces_rather_than_duplicates(self):
        assignments = module.with_assignment(module.empty(), "opencode", "sdd-apply", assignment())
        assignments = module.with_assignment(assignments, "opencode", "sdd-apply", assignment("claude-haiku"))
        self.assertEqual(len(assignments.entries), 1)
        self.assertEqual(module.get(assignments, "opencode", "sdd-apply"), assignment("claude-haiku"))

    def test_two_different_agents_coexist(self):
        assignments = module.with_assignment(module.empty(), "opencode", "sdd-apply", assignment())
        assignments = module.with_assignment(assignments, "opencode", "sdd-verify", assignment("claude-haiku"))
        self.assertEqual(len(assignments.entries), 2)


class WithoutAssignmentTest(unittest.TestCase):
    def test_removing_a_set_assignment_drops_it(self):
        assignments = module.with_assignment(module.empty(), "opencode", "sdd-apply", assignment())
        assignments = module.without_assignment(assignments, "opencode", "sdd-apply")
        self.assertIsNone(module.get(assignments, "opencode", "sdd-apply"))

    def test_removing_one_never_set_is_a_no_op(self):
        assignments = module.without_assignment(module.empty(), "opencode", "sdd-apply")
        self.assertEqual(assignments, module.empty())


class RoundTripTest(unittest.TestCase):
    def test_to_dict_and_back_preserves_the_assignment(self):
        assignments = module.with_assignment(
            module.empty(), "opencode", "sdd-apply", assignment(effort="high")
        )
        restored = module.from_dict(module.to_dict(assignments))
        self.assertEqual(restored, assignments)

    def test_effort_absent_when_none(self):
        assignments = module.with_assignment(module.empty(), "opencode", "sdd-apply", assignment())
        payload = module.to_dict(assignments)
        self.assertNotIn("effort", payload["assignments"][0])


def catalog(provider="anthropic", model="claude-sonnet-5") -> ModelCatalog:
    return ModelCatalog(providers=(Provider(id=provider, models=(Model(id=model, tool_call=True),)),))


class ResolveForRenderTest(unittest.TestCase):
    def test_a_reachable_assignment_is_honored(self):
        assignments = module.with_assignment(module.empty(), "opencode", "sdd-apply", assignment())
        honored, warnings = module.resolve_for_render(assignments, "opencode", frozenset({"sdd-apply"}), catalog())
        self.assertEqual(honored, {"sdd-apply": "anthropic/claude-sonnet-5"})
        self.assertEqual(warnings, ())

    def test_no_assignments_is_a_clean_no_op(self):
        honored, warnings = module.resolve_for_render(module.empty(), "opencode", frozenset(), catalog())
        self.assertEqual((honored, warnings), ({}, ()))

    def test_an_assignment_for_another_cli_is_ignored(self):
        assignments = module.with_assignment(module.empty(), "claude-code", "sdd-apply", assignment())
        honored, warnings = module.resolve_for_render(assignments, "opencode", frozenset({"sdd-apply"}), catalog())
        self.assertEqual((honored, warnings), ({}, ()))

    def test_an_agent_no_longer_configurable_is_dropped_with_a_warning(self):
        assignments = module.with_assignment(module.empty(), "opencode", "retired-agent", assignment())
        honored, warnings = module.resolve_for_render(assignments, "opencode", frozenset(), catalog())
        self.assertEqual(honored, {})
        self.assertEqual(len(warnings), 1)
        self.assertIn("retired-agent", warnings[0])

    def test_an_unreachable_provider_is_dropped_with_a_warning(self):
        assignments = module.with_assignment(module.empty(), "opencode", "sdd-apply", assignment())
        honored, warnings = module.resolve_for_render(
            assignments, "opencode", frozenset({"sdd-apply"}), ModelCatalog()
        )
        self.assertEqual(honored, {})
        self.assertEqual(len(warnings), 1)
        self.assertIn("anthropic", warnings[0])

    def test_a_model_no_longer_listed_is_dropped_with_a_warning(self):
        assignments = module.with_assignment(module.empty(), "opencode", "sdd-apply", assignment("retired-model"))
        honored, warnings = module.resolve_for_render(
            assignments, "opencode", frozenset({"sdd-apply"}), catalog(model="claude-sonnet-5")
        )
        self.assertEqual(honored, {})
        self.assertEqual(len(warnings), 1)
        self.assertIn("retired-model", warnings[0])


class FromDictValidationTest(unittest.TestCase):
    def test_wrong_schema_is_rejected(self):
        with self.assertRaises(ModelAssignmentError):
            module.from_dict({"schema": "wrong", "assignments": []})

    def test_not_an_object_is_rejected(self):
        with self.assertRaises(ModelAssignmentError):
            module.from_dict([])

    def test_duplicate_entries_for_the_same_cli_and_agent_are_rejected(self):
        payload = {
            "schema": module.SCHEMA,
            "assignments": [
                {"cli": "opencode", "agent": "sdd-apply", "provider_id": "anthropic", "model_id": "a"},
                {"cli": "opencode", "agent": "sdd-apply", "provider_id": "anthropic", "model_id": "b"},
            ],
        }
        with self.assertRaises(ModelAssignmentError):
            module.from_dict(payload)

    def test_missing_field_is_rejected(self):
        payload = {"schema": module.SCHEMA, "assignments": [{"cli": "opencode", "agent": "sdd-apply"}]}
        with self.assertRaises(ModelAssignmentError):
            module.from_dict(payload)
