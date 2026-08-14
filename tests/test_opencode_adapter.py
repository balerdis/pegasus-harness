"""The OpenCode adapter: the only place OpenCode's own names are allowed."""
from __future__ import annotations

import unittest
from pathlib import Path, PurePosixPath

from pegasus.adapters.opencode import Adapter
from pegasus.adapters.opencode import render as render_module
from pegasus.core import content as content_module
from pegasus.core.content import Agent, AgentMode, Asset, Command, Execution, RunsAs, Skill, SystemPrompt
from pegasus.core import registry as registry_module
from pegasus.core.registry import Registry
from pegasus.core.types import Capability, ConfigKeyArtifact, Environment, FileArtifact

HOME = Path("/home/probe")
ENVIRONMENT = Environment(home=HOME)
CONFIG = HOME / ".config" / "opencode"


def only(artifacts, kind):
    return [item for item in artifacts if isinstance(item, kind)]


class LayoutTest(unittest.TestCase):
    def setUp(self):
        self.layout = Adapter().layout(ENVIRONMENT)

    def test_resolves_the_standard_configuration_root(self):
        self.assertEqual(self.layout.config_dir, CONFIG)

    def test_honours_an_absolute_xdg_config_home(self):
        environment = Environment(home=HOME, variables={"XDG_CONFIG_HOME": "/opt/cfg"})
        self.assertEqual(Adapter().layout(environment).config_dir, Path("/opt/cfg/opencode"))

    def test_ignores_a_relative_xdg_config_home(self):
        environment = Environment(home=HOME, variables={"XDG_CONFIG_HOME": "relative/cfg"})
        self.assertEqual(Adapter().layout(environment).config_dir, CONFIG)

    def test_every_file_based_capability_has_its_path(self):
        """Settings-based capabilities need no directory; the registry defines which."""
        for capability in Adapter().capabilities().enabled & registry_module._NEEDS_ANCHOR:
            self.assertIsNotNone(self.layout.anchor(capability), capability.value)

    def test_sub_agents_need_no_directory(self):
        """OpenCode declares its subagents inside opencode.json, not as files."""
        self.assertIsNone(self.layout.agents_dir)

    def test_the_system_prompt_is_not_the_users_own_agents_file(self):
        self.assertEqual(self.layout.system_prompt_file, CONFIG / "pegasus-AGENTS.md")
        self.assertNotEqual(self.layout.system_prompt_file, CONFIG / "AGENTS.md")

    def test_building_a_layout_touches_no_filesystem(self):
        Adapter().layout(Environment(home=Path("/nonexistent/probe")))


class RegistrationTest(unittest.TestCase):
    def test_the_adapter_satisfies_the_registry(self):
        registry = Registry()
        registry.register(Adapter())
        self.assertEqual(registry.ids(), ("opencode",))

    def test_declares_only_what_it_implements(self):
        manifest = Adapter().capabilities()
        self.assertEqual(
            sorted(item.value for item in manifest.enabled),
            ["prompts", "skills", "slash_commands", "sub_agents", "system_prompt"],
        )

    def test_mcp_stays_undeclared_until_its_content_exists(self):
        self.assertFalse(Adapter().capabilities().mcp)
        self.assertFalse(hasattr(Adapter(), "render_mcp"))


class DetectionTest(unittest.TestCase):
    def test_reports_a_configuration_directory_that_does_not_exist(self):
        detection = Adapter().detect(Environment(home=Path("/nonexistent/probe")))
        self.assertFalse(detection.config_found)
        self.assertEqual(detection.config_dir, Path("/nonexistent/probe/.config/opencode"))

    def test_an_empty_path_finds_no_binary(self):
        detection = Adapter().detect(Environment(home=HOME, variables={"PATH": ""}))
        self.assertFalse(detection.installed)
        self.assertIsNone(detection.binary_path)


class SkillRenderTest(unittest.TestCase):
    def setUp(self):
        self.layout = Adapter().layout(ENVIRONMENT)
        self.skill = Skill(
            name="alpha",
            description="d",
            assets=(
                Asset(PurePosixPath("SKILL.md"), b"skill body"),
                Asset(PurePosixPath("references/guide.md"), b"guide"),
            ),
            source=PurePosixPath("skills/alpha/SKILL.md"),
        )

    def test_travels_verbatim(self):
        artifacts = Adapter().render_skill(self.layout, self.skill)
        self.assertEqual([item.content for item in artifacts], [b"skill body", b"guide"])

    def test_lands_under_the_skill_directory(self):
        artifacts = Adapter().render_skill(self.layout, self.skill)
        self.assertEqual(
            [item.path for item in artifacts],
            [CONFIG / "skills/alpha/SKILL.md", CONFIG / "skills/alpha/references/guide.md"],
        )


class AgentRenderTest(unittest.TestCase):
    def setUp(self):
        self.adapter = Adapter()
        self.layout = self.adapter.layout(ENVIRONMENT)

    def agent(self, **overrides):
        fields = dict(
            name="sdd-verify",
            description="Readiness authority",
            body="# Verify\n\nProve it.\n",
            mode=AgentMode.SUBAGENT,
            source=PurePosixPath("agents/sdd-verify.md"),
        )
        fields.update(overrides)
        return Agent(**fields)

    def value(self, agent):
        return only(self.adapter.render_agent(self.layout, agent), ConfigKeyArtifact)[0].value

    def test_writes_one_entry_under_the_agent_map(self):
        artifact = only(self.adapter.render_agent(self.layout, self.agent()), ConfigKeyArtifact)[0]
        self.assertEqual(artifact.pointer, "/agent/sdd-verify")
        self.assertEqual(artifact.path, CONFIG / "opencode.json")

    def test_references_the_prompt_file_instead_of_inlining_it(self):
        self.assertEqual(self.value(self.agent())["prompt"], "{file:./prompts/sdd-verify.md}")

    def test_hidden_is_only_written_when_true(self):
        self.assertTrue(self.value(self.agent(hidden=True))["hidden"])
        self.assertNotIn("hidden", self.value(self.agent()))

    def test_tools_are_translated_to_opencode_names(self):
        agent = self.agent(requires_tools=("read", "bash"), optional_tools=("codebase-memory",))
        self.assertEqual(
            self.value(agent)["tools"], {"read": True, "bash": True, "codebase-memory-mcp*": True}
        )

    def test_a_tool_with_no_opencode_name_is_refused(self):
        with self.assertRaises(render_module.RenderError) as raised:
            self.value(self.agent(requires_tools=("telepathy",)))
        self.assertIn("telepathy", str(raised.exception))

    def test_delegation_becomes_a_deny_by_default_permission_block(self):
        agent = self.agent(may_delegate_to=("explore", "sdd-verify"))
        self.assertEqual(
            self.value(agent)["permission"],
            {"task": {"*": "deny", "explore": "allow", "sdd-verify": "allow"}},
        )

    def test_a_primary_agent_also_becomes_the_default(self):
        artifacts = self.adapter.render_agent(self.layout, self.agent(mode=AgentMode.PRIMARY))
        default = [item for item in artifacts if item.pointer == "/default_agent"]
        self.assertEqual([item.value for item in default], ["sdd-verify"])

    def test_a_subagent_does_not_touch_the_default(self):
        artifacts = self.adapter.render_agent(self.layout, self.agent())
        self.assertEqual([item for item in artifacts if item.pointer == "/default_agent"], [])

    def test_the_prompt_is_a_file_of_its_own(self):
        artifact = self.adapter.render_prompt(self.layout, self.agent())[0]
        self.assertEqual(artifact.path, CONFIG / "prompts/sdd-verify.md")
        self.assertEqual(artifact.content, b"# Verify\n\nProve it.\n")


class CommandRenderTest(unittest.TestCase):
    def setUp(self):
        self.adapter = Adapter()
        self.layout = self.adapter.layout(ENVIRONMENT)

    def rendered(self, **overrides):
        fields = dict(
            name="sdd-apply",
            description="Implement SDD tasks",
            body="Do the work.\n",
            runs_as=RunsAs.ORCHESTRATOR,
            execution=Execution.ISOLATED,
            source=PurePosixPath("commands/sdd-apply.md"),
        )
        fields.update(overrides)
        return self.adapter.render_command(self.layout, Command(**fields))[0].content.decode()

    def test_lands_in_the_commands_directory(self):
        artifact = self.adapter.render_command(
            self.layout,
            Command(
                name="sdd-apply",
                description="d",
                body="b\n",
                runs_as=RunsAs.DEFAULT,
                execution=Execution.INLINE,
                source=PurePosixPath("commands/sdd-apply.md"),
            ),
        )[0]
        self.assertEqual(artifact.path, CONFIG / "commands/sdd-apply.md")

    def test_the_orchestrator_role_becomes_the_pegasus_agent(self):
        self.assertIn("agent: \"pegasus-orchestrator\"", self.rendered())

    def test_planner_and_builder_become_opencode_native_agents(self):
        self.assertIn('agent: "plan"', self.rendered(runs_as=RunsAs.PLANNER))
        self.assertIn('agent: "build"', self.rendered(runs_as=RunsAs.BUILDER))

    def test_the_default_role_omits_the_key(self):
        self.assertNotIn("agent:", self.rendered(runs_as=RunsAs.DEFAULT))

    def test_isolated_execution_becomes_subtask(self):
        self.assertIn("subtask: true", self.rendered())

    def test_inline_execution_omits_subtask(self):
        self.assertNotIn("subtask", self.rendered(execution=Execution.INLINE))

    def test_the_body_survives_untouched(self):
        self.assertTrue(self.rendered().endswith("Do the work.\n"))

    def test_a_description_with_a_colon_stays_valid(self):
        rendered = self.rendered(description="Trigger: do it now")
        self.assertIn('description: "Trigger: do it now"', rendered)


class SystemPromptRenderTest(unittest.TestCase):
    def setUp(self):
        self.adapter = Adapter()
        self.layout = self.adapter.layout(ENVIRONMENT)
        self.artifacts = self.adapter.render_system_prompt(
            self.layout, SystemPrompt(body="# Rules\n", source=PurePosixPath("system-prompt/AGENTS.md"))
        )

    def test_ships_its_own_file(self):
        file_artifact = only(self.artifacts, FileArtifact)[0]
        self.assertEqual(file_artifact.path, CONFIG / "pegasus-AGENTS.md")

    def test_wires_itself_in_by_appending_to_the_instructions_list(self):
        key = only(self.artifacts, ConfigKeyArtifact)[0]
        self.assertEqual(key.pointer, "/instructions/-")
        self.assertEqual(key.value, "./pegasus-AGENTS.md")


class OwnArtifactsTest(unittest.TestCase):
    def setUp(self):
        self.layout = Adapter().layout(ENVIRONMENT)
        self.artifacts = Adapter().own_artifacts(self.layout)

    def test_ships_the_adapter_only_assets(self):
        self.assertEqual(len(only(self.artifacts, FileArtifact)), 11)

    def test_build_leftovers_are_excluded(self):
        self.assertEqual([item for item in self.artifacts if "__pycache__" in str(item.path)], [])

    def test_the_skill_registry_helper_lives_under_a_pegasus_subtree(self):
        paths = {item.path for item in only(self.artifacts, FileArtifact)}
        self.assertIn(CONFIG / "pegasus/skill-registry/pegasus_skill_registry.py", paths)

    def test_plugins_land_in_the_plugin_directory(self):
        paths = {item.path for item in only(self.artifacts, FileArtifact)}
        self.assertIn(CONFIG / "plugins/engram.ts", paths)

    def test_settings_are_appended_not_replaced(self):
        pointers = {item.pointer for item in only(self.artifacts, ConfigKeyArtifact)}
        self.assertEqual(pointers, {"/skills/paths/-", "/plugin/-", "/share"})

    def test_everything_stays_inside_the_configuration_root(self):
        for item in self.artifacts:
            self.assertTrue(item.path.is_relative_to(self.layout.config_dir), item.path)

    def test_the_result_is_deterministic(self):
        self.assertEqual(Adapter().own_artifacts(self.layout), Adapter().own_artifacts(self.layout))


class ShippedContentRenderTest(unittest.TestCase):
    """Rendering everything this repository distributes must not collide with itself."""

    @classmethod
    def setUpClass(cls):
        adapter, cls.layout = Adapter(), Adapter().layout(ENVIRONMENT)
        loaded = content_module.load()
        cls.artifacts = [
            *(item for skill in loaded.skills for item in adapter.render_skill(cls.layout, skill)),
            *(item for agent in loaded.agents for item in adapter.render_agent(cls.layout, agent)),
            *(item for agent in loaded.agents for item in adapter.render_prompt(cls.layout, agent)),
            *(item for command in loaded.commands for item in adapter.render_command(cls.layout, command)),
            *adapter.render_system_prompt(cls.layout, loaded.system_prompt),
            *adapter.own_artifacts(cls.layout),
        ]

    def test_no_two_artifacts_claim_the_same_address(self):
        addresses = [
            (item.path, getattr(item, "pointer", None))
            for item in self.artifacts
            if not (isinstance(item, ConfigKeyArtifact) and item.pointer.endswith("/-"))
        ]
        self.assertEqual(len(addresses), len(set(addresses)))

    def test_everything_lands_inside_the_configuration_root(self):
        for item in self.artifacts:
            self.assertTrue(item.path.is_relative_to(self.layout.config_dir), item.path)

    def test_the_whole_payload_is_produced(self):
        self.assertGreater(len(self.artifacts), 70)


if __name__ == "__main__":
    unittest.main()
