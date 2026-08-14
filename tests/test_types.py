"""Domain types: the vocabulary shared by the engine and every adapter."""
from __future__ import annotations

import dataclasses
import unittest
from pathlib import Path

from pegasus.core.types import (
    Capability,
    CapabilityManifest,
    Codec,
    ConfigKeyArtifact,
    Detection,
    Environment,
    FileArtifact,
    Layout,
    ModelAssignment,
    SupportTier,
)


class FileArtifactTest(unittest.TestCase):
    def test_holds_opaque_bytes(self):
        artifact = FileArtifact(id="skill:x", path=Path("/home/u/.config/x"), content=b"body")
        self.assertEqual(artifact.content, b"body")
        self.assertEqual(artifact.mode, 0o644)

    def test_is_immutable(self):
        artifact = FileArtifact(id="a", path=Path("/tmp/a"), content=b"")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            artifact.content = b"other"

    def test_relative_path_is_rejected(self):
        with self.assertRaises(ValueError):
            FileArtifact(id="a", path=Path("relative/a"), content=b"")

    def test_content_must_be_bytes(self):
        with self.assertRaises(TypeError):
            FileArtifact(id="a", path=Path("/tmp/a"), content="text")

    def test_mode_outside_the_permission_range_is_rejected(self):
        with self.assertRaises(ValueError):
            FileArtifact(id="a", path=Path("/tmp/a"), content=b"", mode=0o1000)


class ConfigKeyArtifactTest(unittest.TestCase):
    def test_defaults_to_json(self):
        artifact = ConfigKeyArtifact(id="agent:x", path=Path("/tmp/c.json"), pointer="/agent/x", value={})
        self.assertIs(artifact.codec, Codec.JSON)

    def test_pointer_must_be_valid(self):
        with self.assertRaises(ValueError):
            ConfigKeyArtifact(id="a", path=Path("/tmp/c.json"), pointer="agent/x", value={})

    def test_root_pointer_is_rejected(self):
        with self.assertRaises(ValueError):
            ConfigKeyArtifact(id="a", path=Path("/tmp/c.json"), pointer="", value={})

    def test_addresses_a_single_field(self):
        artifact = ConfigKeyArtifact(
            id="model:sdd-apply", path=Path("/tmp/c.json"), pointer="/agent/sdd-apply/model", value="p/m"
        )
        self.assertEqual(artifact.tokens, ("agent", "sdd-apply", "model"))


class DetectionTest(unittest.TestCase):
    def test_present_when_only_the_binary_is_found(self):
        self.assertTrue(Detection(installed=True, binary_path=Path("/usr/bin/x")).present)

    def test_present_when_only_the_config_directory_exists(self):
        self.assertTrue(Detection(config_dir=Path("/home/u/.config/x"), config_found=True).present)

    def test_absent_when_neither_is_found(self):
        self.assertFalse(Detection().present)


class CapabilityManifestTest(unittest.TestCase):
    def test_enabled_lists_only_declared_capabilities(self):
        manifest = CapabilityManifest(cli_id="probe", skills=True, slash_commands=True)
        self.assertEqual(manifest.enabled, frozenset({Capability.SKILLS, Capability.SLASH_COMMANDS}))

    def test_defaults_to_no_capabilities(self):
        self.assertEqual(CapabilityManifest(cli_id="probe").enabled, frozenset())

    def test_carries_a_versioned_schema(self):
        self.assertEqual(CapabilityManifest(cli_id="probe").schema, "pegasus/capability-manifest/v1")

    def test_empty_cli_id_is_rejected(self):
        with self.assertRaises(ValueError):
            CapabilityManifest(cli_id="")


class LayoutTest(unittest.TestCase):
    def test_anchor_reads_a_capability_directory(self):
        layout = Layout(config_dir=Path("/home/u/.config/x"), skills_dir=Path("/home/u/.config/x/skills"))
        self.assertEqual(layout.anchor(Capability.SKILLS), Path("/home/u/.config/x/skills"))

    def test_anchor_is_none_when_the_cli_lacks_the_concept(self):
        self.assertIsNone(Layout(config_dir=Path("/home/u/.config/x")).anchor(Capability.SKILLS))

    def test_capabilities_without_a_dedicated_anchor_report_none(self):
        layout = Layout(config_dir=Path("/c"), settings_file=Path("/c/s.json"))
        self.assertIsNone(layout.anchor(Capability.MCP))

    def test_config_dir_must_be_absolute(self):
        with self.assertRaises(ValueError):
            Layout(config_dir=Path("relative"))


class ModelAssignmentTest(unittest.TestCase):
    def test_parses_a_provider_qualified_spec(self):
        assignment = ModelAssignment.parse("anthropic/claude-sonnet-5")
        self.assertEqual((assignment.provider_id, assignment.model_id), ("anthropic", "claude-sonnet-5"))

    def test_keeps_slashes_that_belong_to_the_model_id(self):
        self.assertEqual(ModelAssignment.parse("openrouter/qwen/qwen3").model_id, "qwen/qwen3")

    def test_full_id_round_trips(self):
        self.assertEqual(ModelAssignment.parse("anthropic/sonnet").full_id, "anthropic/sonnet")

    def test_effort_defaults_to_the_provider_default(self):
        self.assertIsNone(ModelAssignment.parse("anthropic/sonnet").effort)

    def test_a_spec_without_a_provider_is_rejected(self):
        for spec in ("sonnet", "/sonnet", "anthropic/", ""):
            with self.assertRaises(ValueError, msg=spec):
                ModelAssignment.parse(spec)


class EnvironmentTest(unittest.TestCase):
    def test_carries_home_and_variables(self):
        environment = Environment(home=Path("/home/u"), variables={"ANTHROPIC_API_KEY": "x"})
        self.assertEqual(environment.variables["ANTHROPIC_API_KEY"], "x")

    def test_home_must_be_absolute(self):
        with self.assertRaises(ValueError):
            Environment(home=Path("u"))


class CapabilityTest(unittest.TestCase):
    def test_plugins_is_not_a_capability(self):
        """Plugins have no agnostic form, so they are adapter-owned, not a capability."""
        self.assertNotIn("plugins", {item.value for item in Capability})


class SupportTierTest(unittest.TestCase):
    def test_declares_the_three_levels(self):
        self.assertEqual(
            {tier.value for tier in SupportTier}, {"full", "partial", "experimental"}
        )


if __name__ == "__main__":
    unittest.main()
