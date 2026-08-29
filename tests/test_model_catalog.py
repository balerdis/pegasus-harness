"""Which providers and models a machine can actually reach.

Pure decision logic: the three real files a CLI adapter reads are handed in
already parsed, so this stays testable without touching a filesystem.
"""
from __future__ import annotations

import unittest

from pegasus.core.model_catalog import (
    Model,
    ModelCatalog,
    Provider,
    build,
    credential_provider_names,
    declared_provider_names,
)


class CredentialProviderNamesTest(unittest.TestCase):
    def test_returns_only_the_top_level_keys(self):
        payload = {"anthropic": {"type": "oauth", "access": "super-secret-token"}}
        self.assertEqual(credential_provider_names(payload), frozenset({"anthropic"}))

    def test_a_secret_value_never_appears_in_the_result(self):
        payload = {
            "anthropic": {"type": "oauth", "access": "super-secret-token"},
            "openai": {"type": "api", "key": "sk-do-not-leak-this"},
        }
        names = credential_provider_names(payload)
        rendered = repr(names)
        self.assertNotIn("super-secret-token", rendered)
        self.assertNotIn("sk-do-not-leak-this", rendered)

    def test_a_non_object_payload_yields_no_providers(self):
        self.assertEqual(credential_provider_names(None), frozenset())
        self.assertEqual(credential_provider_names([]), frozenset())


class DeclaredProviderNamesTest(unittest.TestCase):
    def test_reads_the_provider_key(self):
        payload = {"provider": {"custom-llm": {"models": {}}}}
        self.assertEqual(declared_provider_names(payload), frozenset({"custom-llm"}))

    def test_missing_provider_key_yields_nothing(self):
        self.assertEqual(declared_provider_names({}), frozenset())


class BuildTest(unittest.TestCase):
    def test_a_credentialed_provider_is_offered(self):
        raw = {"anthropic": {"models": {"claude-sonnet-5": {"tool_call": True}}}}
        catalog = build(raw, credentialed=frozenset({"anthropic"}), declared=frozenset(), variables={})
        self.assertEqual(catalog, ModelCatalog(providers=(Provider(id="anthropic", models=(Model(id="claude-sonnet-5", tool_call=True),)),)))

    def test_a_provider_with_no_session_no_env_and_no_declaration_is_absent(self):
        raw = {"anthropic": {"models": {"claude-sonnet-5": {"tool_call": True}}}}
        catalog = build(raw, credentialed=frozenset(), declared=frozenset(), variables={})
        self.assertEqual(catalog, ModelCatalog())

    def test_all_environment_variables_set_offers_the_provider(self):
        raw = {
            "anthropic": {
                "env": ["ANTHROPIC_API_KEY"],
                "models": {"claude-sonnet-5": {"tool_call": True}},
            }
        }
        catalog = build(
            raw,
            credentialed=frozenset(),
            declared=frozenset(),
            variables={"ANTHROPIC_API_KEY": "irrelevant-here"},
        )
        self.assertEqual([p.id for p in catalog.providers], ["anthropic"])

    def test_only_some_environment_variables_set_is_not_enough(self):
        raw = {
            "custom": {
                "env": ["FOO_KEY", "BAR_KEY"],
                "models": {"m": {"tool_call": True}},
            }
        }
        catalog = build(
            raw, credentialed=frozenset(), declared=frozenset(), variables={"FOO_KEY": "x"}
        )
        self.assertEqual(catalog, ModelCatalog())

    def test_a_declared_provider_is_offered(self):
        raw = {"custom-llm": {"models": {"m": {"tool_call": True}}}}
        catalog = build(raw, credentialed=frozenset(), declared=frozenset({"custom-llm"}), variables={})
        self.assertEqual([p.id for p in catalog.providers], ["custom-llm"])

    def test_a_provider_the_catalog_marks_builtin_needs_nothing_else(self):
        raw = {"builtin-provider": {"builtin": True, "models": {"m": {"tool_call": True}}}}
        catalog = build(raw, credentialed=frozenset(), declared=frozenset(), variables={})
        self.assertEqual([p.id for p in catalog.providers], ["builtin-provider"])

    def test_a_model_without_tool_call_is_never_offered(self):
        raw = {
            "anthropic": {
                "models": {
                    "cannot-call-tools": {"tool_call": False},
                    "can-call-tools": {"tool_call": True},
                }
            }
        }
        catalog = build(raw, credentialed=frozenset({"anthropic"}), declared=frozenset(), variables={})
        self.assertEqual(len(catalog.providers), 1)
        self.assertEqual([m.id for m in catalog.providers[0].models], ["can-call-tools"])

    def test_a_provider_with_no_tool_capable_models_is_dropped_entirely(self):
        raw = {"anthropic": {"models": {"only-model": {"tool_call": False}}}}
        catalog = build(raw, credentialed=frozenset({"anthropic"}), declared=frozenset(), variables={})
        self.assertEqual(catalog, ModelCatalog())

    def test_reasoning_support_is_carried_through(self):
        raw = {"anthropic": {"models": {"m": {"tool_call": True, "reasoning": True}}}}
        catalog = build(raw, credentialed=frozenset({"anthropic"}), declared=frozenset(), variables={})
        self.assertTrue(catalog.providers[0].models[0].reasoning)

    def test_a_missing_catalog_is_not_an_error(self):
        self.assertEqual(build(None, credentialed=frozenset(), declared=frozenset(), variables={}), ModelCatalog())
        self.assertEqual(build({}, credentialed=frozenset(), declared=frozenset(), variables={}), ModelCatalog())


if __name__ == "__main__":
    unittest.main()
