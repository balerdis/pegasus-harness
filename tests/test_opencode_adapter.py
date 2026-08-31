"""The OpenCode adapter: the only place OpenCode's own names are allowed."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path, PurePosixPath

from pegasus.adapters.opencode import Adapter
from pegasus.adapters.opencode import adapter as adapter_module
from pegasus.adapters.opencode import render as render_module
from pegasus.core import content as content_module
from pegasus.core.content import (
    Agent,
    AgentMode,
    Asset,
    Command,
    Distribution,
    Execution,
    Mcp,
    RunsAs,
    Skill,
    SystemPrompt,
)
from pegasus.core import registry as registry_module
from pegasus.core.registry import Registry
from pegasus.core.types import Capability, ConfigKeyArtifact, Environment, FileArtifact, Layout, ModelAssignment

HOME = Path("/home/probe")
ENVIRONMENT = Environment(home=HOME, data_dir=HOME / ".local" / "share" / "pegasus-harness")
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
            [
                "mcp",
                "per_agent_model",
                "prompts",
                "skills",
                "slash_commands",
                "sub_agents",
                "system_prompt",
            ],
        )

    def test_mcp_is_declared_now_that_its_content_exists(self):
        self.assertTrue(Adapter().capabilities().mcp)
        self.assertTrue(callable(getattr(Adapter(), "render_mcp", None)))

    def test_per_agent_model_is_declared_now_that_model_catalog_is_implemented(self):
        self.assertTrue(Adapter().capabilities().per_agent_model)
        self.assertTrue(callable(getattr(Adapter(), "model_catalog", None)))


class DetectionTest(unittest.TestCase):
    def test_reports_a_configuration_directory_that_does_not_exist(self):
        detection = Adapter().detect(Environment(home=Path("/nonexistent/probe")))
        self.assertFalse(detection.config_found)
        self.assertEqual(detection.config_dir, Path("/nonexistent/probe/.config/opencode"))

    def test_an_empty_path_finds_no_binary(self):
        detection = Adapter().detect(Environment(home=HOME, variables={"PATH": ""}))
        self.assertFalse(detection.installed)
        self.assertIsNone(detection.binary_path)


class ModelCatalogTest(unittest.TestCase):
    """`model_catalog` reads three real files, but only ever ones this test made.

    Every path below is rooted in a throwaway directory this test creates and
    tears down itself, through XDG variables the adapter already honours
    elsewhere. Nothing here ever names the real machine's home.
    """

    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        root = Path(self.scratch.name)
        self.environment = Environment(
            home=root / "home",
            variables={
                "XDG_CACHE_HOME": str(root / "cache"),
                "XDG_DATA_HOME": str(root / "data"),
                "XDG_CONFIG_HOME": str(root / "config"),
            },
        )

    def _write(self, relative: str, payload: object) -> None:
        path = Path(self.scratch.name) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def test_a_missing_catalog_file_is_an_empty_catalog_not_an_error(self):
        catalog = Adapter().model_catalog(self.environment)
        self.assertEqual(catalog.providers, ())

    def test_a_credentialed_provider_offers_its_tool_capable_models(self):
        self._write(
            "cache/opencode/models.json",
            {
                "anthropic": {
                    "models": {
                        "claude-sonnet-5": {"tool_call": True},
                        "no-tools": {"tool_call": False},
                    }
                }
            },
        )
        self._write("data/opencode/auth.json", {"anthropic": {"type": "oauth", "access": "leak-me-not"}})
        catalog = Adapter().model_catalog(self.environment)
        self.assertEqual([p.id for p in catalog.providers], ["anthropic"])
        self.assertEqual([m.id for m in catalog.providers[0].models], ["claude-sonnet-5"])

    def test_a_provider_declared_in_the_users_own_config_is_offered(self):
        self._write("cache/opencode/models.json", {"custom-llm": {"models": {"m": {"tool_call": True}}}})
        self._write("config/opencode/opencode.json", {"provider": {"custom-llm": {}}})
        catalog = Adapter().model_catalog(self.environment)
        self.assertEqual([p.id for p in catalog.providers], ["custom-llm"])

    def test_a_provider_with_no_session_no_env_and_no_declaration_is_absent(self):
        self._write("cache/opencode/models.json", {"anthropic": {"models": {"m": {"tool_call": True}}}})
        catalog = Adapter().model_catalog(self.environment)
        self.assertEqual(catalog.providers, ())

    def test_a_credential_value_never_appears_anywhere_in_the_result(self):
        self._write(
            "cache/opencode/models.json",
            {"anthropic": {"models": {"claude-sonnet-5": {"tool_call": True}}}},
        )
        self._write(
            "data/opencode/auth.json",
            {"anthropic": {"type": "oauth", "access": "top-secret-oauth-token"}},
        )
        catalog = Adapter().model_catalog(self.environment)
        self.assertNotIn("top-secret-oauth-token", repr(catalog))


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

    def test_hidden_is_written_for_a_subagent_and_for_nobody_else(self):
        self.assertTrue(self.value(self.agent(mode=AgentMode.SUBAGENT))["hidden"])
        self.assertNotIn("hidden", self.value(self.agent(mode=AgentMode.PRIMARY)))

    def test_tools_are_translated_to_opencode_names(self):
        agent = self.agent(requires_tools=("read", "bash"), optional_tools=("write",))
        self.assertEqual(
            self.value(agent)["tools"],
            {"*": False, "read": True, "bash": True, "write": True},
        )

    def test_an_optional_mcp_id_is_granted_as_a_wildcard(self):
        agent = self.agent(optional_mcp=("context7",))
        self.assertEqual(self.value(agent)["tools"], {"*": False, "context7*": True})

    def test_native_tools_and_mcp_wildcards_are_granted_together(self):
        agent = self.agent(requires_tools=("read", "bash"), optional_mcp=("context7",))
        self.assertEqual(
            self.value(agent)["tools"],
            {"*": False, "read": True, "bash": True, "context7*": True},
        )

    def test_the_deny_baseline_is_written_before_anything_it_is_meant_to_lose_to(self):
        """The order of these keys decides whether any agent has any tool.

        The runtime turns this map into permission rules in the order it reads
        them, and resolves a tool against the **last** rule that matches. So a
        grant only beats the blanket deny by coming after it. Emit the deny
        last and every agent silently loses every tool, while a comparison of
        these two maps as dictionaries still passes: Python does not read
        order into that equality, and the runtime reads nothing else.
        """
        agent = self.agent(requires_tools=("read",), optional_mcp=("context7",))
        keys = list(self.value(agent)["tools"])
        self.assertEqual(keys[0], "*", f"the deny baseline must come first, got {keys}")
        self.assertGreater(len(keys), 1, "a baseline with nothing after it grants nothing")

    def test_no_declared_tools_still_renders_the_deny_baseline(self):
        """Declaring nothing must mean nothing, not the runtime's full default toolset."""
        self.assertEqual(self.value(self.agent())["tools"], {"*": False})

    def test_a_tool_with_no_opencode_name_is_refused(self):
        with self.assertRaises(render_module.RenderError) as raised:
            self.value(self.agent(requires_tools=("telepathy",)))
        self.assertIn("telepathy", str(raised.exception))

    def test_delegation_becomes_a_deny_by_default_permission_block(self):
        agent = self.agent(may_delegate_to=("explore", "sdd-verify"))
        self.assertEqual(
            self.value(agent)["permission"],
            {"*": "deny", "task": {"*": "deny", "explore": "allow", "sdd-verify": "allow"}},
        )

    def test_the_deny_baseline_is_emitted_even_with_no_declared_delegation(self):
        """An agent that names nobody must still ship a permission.task block."""
        self.assertEqual(self.value(self.agent())["permission"], {"*": "deny", "task": {"*": "deny"}})

    def test_a_granted_native_tool_is_translated_into_permission_too(self):
        agent = self.agent(requires_tools=("read", "bash"))
        permission = self.value(agent)["permission"]
        self.assertEqual(permission["read"], "allow")
        self.assertEqual(permission["bash"], "allow")

    def test_write_targets_the_runtimes_own_edit_permission_not_a_write_key(self):
        """The runtime's `permission` schema has no `write` key: its loader folds
        `write`, `edit` and `patch` onto the single `edit` permission it does
        have. A literal rename of a granted `write` into `permission["write"]`
        would govern nothing, and this agent would silently lose the ability
        to write -- so `write` has to land on `edit` here, same as `edit` does.
        """
        agent = self.agent(requires_tools=("write",))
        permission = self.value(agent)["permission"]
        self.assertEqual(permission["edit"], "allow")
        self.assertNotIn("write", permission)

    def test_edit_also_targets_the_edit_permission(self):
        agent = self.agent(requires_tools=("edit",))
        self.assertEqual(self.value(agent)["permission"]["edit"], "allow")

    def test_declaring_both_write_and_edit_still_yields_one_edit_key(self):
        agent = self.agent(requires_tools=("write", "edit"))
        permission = self.value(agent)["permission"]
        self.assertEqual(permission["edit"], "allow")
        self.assertNotIn("write", permission)

    def test_an_optional_mcp_id_is_granted_as_a_wildcard_in_permission_too(self):
        agent = self.agent(optional_mcp=("context7",))
        self.assertEqual(self.value(agent)["permission"]["context7*"], "allow")

    def test_permission_merges_native_tools_mcp_and_delegation_together(self):
        agent = self.agent(
            requires_tools=("read", "write"),
            optional_mcp=("context7",),
            may_delegate_to=("explore",),
        )
        self.assertEqual(
            self.value(agent)["permission"],
            {
                "*": "deny",
                "read": "allow",
                "edit": "allow",
                "context7*": "allow",
                "task": {"*": "deny", "explore": "allow"},
            },
        )

    def test_the_permission_deny_baseline_is_written_before_anything_it_would_lose_to(self):
        """Same resolution rule as `_tools`: the runtime keeps the *last*
        matching rule, so `"*": "deny"` only beats a grant that comes after it.
        """
        agent = self.agent(requires_tools=("read",), optional_mcp=("context7",))
        keys = list(self.value(agent)["permission"])
        self.assertEqual(keys[0], "*", f"the deny baseline must come first, got {keys}")
        self.assertGreater(len(keys), 1, "a baseline with nothing after it grants nothing")

    def test_the_agent_a_session_starts_in_becomes_the_default(self):
        starts = content_module.SESSION_STARTS_IN
        artifacts = self.adapter.render_agent(
            self.layout,
            self.agent(
                name=starts,
                mode=AgentMode.PRIMARY,
                source=PurePosixPath(f"agents/{starts}.md"),
            ),
        )
        default = [item for item in artifacts if item.pointer == "/default_agent"]
        self.assertEqual([item.value for item in default], [starts])

    def test_another_primary_agent_does_not_touch_the_default(self):
        """Being selectable at top level is one thing; being where a session opens is another."""
        artifacts = self.adapter.render_agent(self.layout, self.agent(mode=AgentMode.PRIMARY))
        self.assertEqual([item for item in artifacts if item.pointer == "/default_agent"], [])

    def test_the_real_mode_still_reaches_the_agent_entry(self):
        self.assertEqual(self.value(self.agent(mode=AgentMode.PRIMARY))["mode"], "primary")
        self.assertEqual(self.value(self.agent())["mode"], "subagent")

    def test_a_subagent_does_not_touch_the_default(self):
        artifacts = self.adapter.render_agent(self.layout, self.agent())
        self.assertEqual([item for item in artifacts if item.pointer == "/default_agent"], [])

    def test_the_prompt_is_a_file_of_its_own(self):
        artifact = self.adapter.render_prompt(self.layout, self.agent())[0]
        self.assertEqual(artifact.path, CONFIG / "prompts/sdd-verify.md")
        self.assertEqual(artifact.content, b"# Verify\n\nProve it.\n")

    def test_no_model_key_when_nothing_was_assigned(self):
        self.assertNotIn("model", self.value(self.agent()))

    def test_a_resolved_model_is_written_into_the_agent_entry(self):
        artifacts = self.adapter.render_agent(
            self.layout, self.agent(), ModelAssignment("anthropic", "claude-sonnet-5")
        )
        value = only(artifacts, ConfigKeyArtifact)[0].value
        self.assertEqual(value["model"], "anthropic/claude-sonnet-5")

    def test_no_variant_key_when_the_assignment_carries_no_effort(self):
        artifacts = self.adapter.render_agent(
            self.layout, self.agent(), ModelAssignment("anthropic", "claude-sonnet-5")
        )
        value = only(artifacts, ConfigKeyArtifact)[0].value
        self.assertNotIn("variant", value)

    def test_an_effort_is_written_as_this_clis_own_variant_key(self):
        """`variant` is OpenCode's own schema word for a model's reasoning effort --
        this adapter's job to spell, never the engine's."""
        artifacts = self.adapter.render_agent(
            self.layout, self.agent(), ModelAssignment("anthropic", "claude-sonnet-5", effort="high")
        )
        value = only(artifacts, ConfigKeyArtifact)[0].value
        self.assertEqual(value["model"], "anthropic/claude-sonnet-5")
        self.assertEqual(value["variant"], "high")


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


class McpRenderTest(unittest.TestCase):
    def setUp(self):
        self.adapter = Adapter()
        self.layout = self.adapter.layout(ENVIRONMENT)
        self.mcp = Mcp(
            name="context7",
            description="d",
            body="# Context7 Convention\n",
            distribution=Distribution.REMOTE,
            endpoint="https://mcp.context7.com/mcp",
            source=PurePosixPath("mcp/context7.md"),
        )
        self.artifacts = self.adapter.render_mcp(self.layout, self.mcp)

    def test_renders_exactly_two_artifacts(self):
        self.assertEqual(len(self.artifacts), 2)

    def test_the_server_is_a_configuration_key(self):
        key = only(self.artifacts, ConfigKeyArtifact)[0]
        self.assertEqual(key.pointer, "/mcp/context7")
        self.assertEqual(key.path, self.layout.settings_file)

    def test_a_remote_server_carries_no_headers(self):
        key = only(self.artifacts, ConfigKeyArtifact)[0]
        self.assertEqual(
            key.value,
            {"type": "remote", "url": "https://mcp.context7.com/mcp", "enabled": True},
        )

    def test_the_convention_lands_under_shared_skills(self):
        file_artifact = only(self.artifacts, FileArtifact)[0]
        self.assertEqual(
            file_artifact.path,
            self.layout.skills_dir / "_shared" / "mcp" / "context7-convention.md",
        )
        self.assertEqual(file_artifact.content, b"# Context7 Convention\n")

    def test_the_dispatch_table_covers_every_distribution_member(self):
        self.assertEqual(set(render_module.MCP_VALUE), set(Distribution))

    def test_a_layout_without_skills_refuses_instead_of_an_attribute_error(self):
        layout = Layout(config_dir=CONFIG, settings_file=CONFIG / "opencode.json")
        with self.assertRaises(render_module.RenderError) as raised:
            render_module.mcp(layout, self.mcp)
        self.assertIn("context7", str(raised.exception))


class DownloadMcpRenderTest(unittest.TestCase):
    def setUp(self):
        self.adapter = Adapter()
        self.environment = Environment(home=HOME, data_dir=HOME / ".local" / "share" / "pegasus-harness")
        self.layout = self.adapter.layout(self.environment)
        self.mcp = Mcp(
            name="probe",
            description="d",
            body="# Probe Convention\n",
            distribution=Distribution.DOWNLOAD,
            endpoint="https://example.test/releases/probe-linux-x64",
            source=PurePosixPath("mcp/probe.md"),
            version="1.2.3",
            checksum="sha256:" + "a" * 64,
        )
        self.artifacts = self.adapter.render_mcp(self.layout, self.mcp)

    def test_the_server_points_at_a_local_command(self):
        key = only(self.artifacts, ConfigKeyArtifact)[0]
        self.assertEqual(key.pointer, "/mcp/probe")
        self.assertEqual(
            key.value,
            {
                "type": "local",
                "command": [
                    str(
                        self.environment.data_dir
                        / "mcp"
                        / "probe"
                        / "1.2.3"
                        / "probe-linux-x64"
                    )
                ],
                "enabled": True,
            },
        )

    def test_a_layout_without_a_dependencies_directory_refuses(self):
        layout = Layout(config_dir=CONFIG, settings_file=CONFIG / "opencode.json", skills_dir=CONFIG / "skills")
        with self.assertRaises(render_module.RenderError) as raised:
            render_module.mcp(layout, self.mcp)
        self.assertIn("probe", str(raised.exception))

    def test_argv_is_appended_in_order_after_the_command(self):
        mcp = replace(self.mcp, argv=("mcp", "--tools=agent"))
        artifacts = self.adapter.render_mcp(self.layout, mcp)
        key = only(artifacts, ConfigKeyArtifact)[0]
        self.assertEqual(
            key.value["command"],
            [
                str(
                    self.environment.data_dir
                    / "mcp"
                    / "probe"
                    / "1.2.3"
                    / "probe-linux-x64"
                ),
                "mcp",
                "--tools=agent",
            ],
        )


class ArchiveDownloadMcpRenderTest(unittest.TestCase):
    """An archive's own asset, the `.tar.gz` itself, is never what a CLI's
    configuration should point at -- the command has to name the member
    inside it that is the program, not the fetched file's own name."""

    def setUp(self):
        self.adapter = Adapter()
        self.environment = Environment(home=HOME, data_dir=HOME / ".local" / "share" / "pegasus-harness")
        self.layout = self.adapter.layout(self.environment)
        self.mcp = Mcp(
            name="probe",
            description="d",
            body="# Probe Convention\n",
            distribution=Distribution.DOWNLOAD,
            endpoint="https://example.test/releases/probe-linux-x64.tar.gz",
            source=PurePosixPath("mcp/probe.md"),
            version="1.2.3",
            checksum="sha256:" + "a" * 64,
            archive_members=("CHANGELOG.md", "probe"),
            archive_executable="probe",
        )
        self.artifacts = self.adapter.render_mcp(self.layout, self.mcp)

    def test_the_server_points_at_the_declared_executable_member(self):
        key = only(self.artifacts, ConfigKeyArtifact)[0]
        self.assertEqual(
            key.value["command"],
            [str(self.environment.data_dir / "mcp" / "probe" / "1.2.3" / "probe")],
        )


class NpmMcpRenderTest(unittest.TestCase):
    def setUp(self):
        self.adapter = Adapter()
        self.environment = Environment(home=HOME, data_dir=HOME / ".local" / "share" / "pegasus-harness")
        self.layout = self.adapter.layout(self.environment)
        self.mcp = Mcp(
            name="probe",
            description="d",
            body="# Probe Convention\n",
            distribution=Distribution.NPM,
            endpoint="https://registry.npmjs.org/probe-mcp/-/probe-mcp-1.2.3.tgz",
            source=PurePosixPath("mcp/probe.md"),
            version="1.2.3",
            package="probe-mcp",
            integrity="sha512-" + "a" * 86 + "==",
            entry="cli.js",
        )
        self.artifacts = self.adapter.render_mcp(self.layout, self.mcp)

    def test_the_server_points_at_the_installed_script(self):
        key = only(self.artifacts, ConfigKeyArtifact)[0]
        self.assertEqual(key.pointer, "/mcp/probe")
        self.assertEqual(
            key.value,
            {
                "type": "local",
                "command": [
                    str(
                        self.environment.data_dir
                        / "mcp"
                        / "probe"
                        / "1.2.3"
                        / "node_modules"
                        / "probe-mcp"
                        / "cli.js"
                    )
                ],
                "enabled": True,
            },
        )

    def test_a_layout_without_a_dependencies_directory_refuses(self):
        layout = Layout(config_dir=CONFIG, settings_file=CONFIG / "opencode.json", skills_dir=CONFIG / "skills")
        with self.assertRaises(render_module.RenderError) as raised:
            render_module.mcp(layout, self.mcp)
        self.assertIn("probe", str(raised.exception))

    def test_argv_is_appended_in_order_after_the_installed_script(self):
        mcp = replace(self.mcp, argv=("serve",))
        artifacts = self.adapter.render_mcp(self.layout, mcp)
        key = only(artifacts, ConfigKeyArtifact)[0]
        self.assertEqual(
            key.value["command"],
            [
                str(
                    self.environment.data_dir
                    / "mcp"
                    / "probe"
                    / "1.2.3"
                    / "node_modules"
                    / "probe-mcp"
                    / "cli.js"
                ),
                "serve",
            ],
        )


class ShippedEngramCommandTest(unittest.TestCase):
    """`engram`'s binary prints usage and exits when started with no
    arguments; the real shipped descriptor must render the command that
    actually starts its MCP server."""

    def setUp(self):
        self.adapter = Adapter()
        self.environment = Environment(home=HOME, data_dir=HOME / ".local" / "share" / "pegasus-harness")
        self.layout = self.adapter.layout(self.environment)
        self.engram = next(item for item in content_module.load().mcp if item.name == "engram")
        self.artifacts = self.adapter.render_mcp(self.layout, self.engram)

    def test_the_rendered_command_starts_the_mcp_server(self):
        key = only(self.artifacts, ConfigKeyArtifact)[0]
        self.assertEqual(key.value["command"][1:], ["mcp", "--tools=agent"])


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


    def test_only_the_assets_the_tree_marks_executable_become_executable(self):
        """The tree already records which file is a program; nothing else earns the bit."""
        executable = {
            item.path.name for item in only(self.artifacts, FileArtifact) if item.executable
        }
        self.assertEqual(executable, {"pegasus-skill-registry"})

    def test_the_result_is_deterministic(self):
        self.assertEqual(Adapter().own_artifacts(self.layout), Adapter().own_artifacts(self.layout))


class MissingAssetGroupTest(unittest.TestCase):
    """A declared asset group with no matching directory must never pass silently.

    An empty-but-present directory is a different situation: an asset group can
    legitimately ship with nothing in it, so that case must not raise.
    """

    def test_a_declared_group_with_no_directory_at_all_is_reported_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "present").mkdir()
            targets = {"present": PurePosixPath("present"), "absent": PurePosixPath("absent")}
            self.assertEqual(adapter_module._missing_asset_groups(root, targets), ["absent"])

    def test_an_empty_but_present_directory_is_not_reported_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "empty").mkdir()
            targets = {"empty": PurePosixPath("empty")}
            self.assertEqual(adapter_module._missing_asset_groups(root, targets), [])

    def test_a_missing_group_is_refused_with_its_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            targets = {"plugins": PurePosixPath("plugins")}
            with self.assertRaises(adapter_module.MissingAssetGroupError) as raised:
                adapter_module._check_asset_groups(root, targets)
            self.assertIn("plugins", str(raised.exception))

    def test_the_shipped_package_itself_has_every_declared_group(self):
        """The check that runs at import time must already have passed for real."""
        self.assertEqual(
            adapter_module._missing_asset_groups(adapter_module.ASSETS, adapter_module.ASSET_TARGETS),
            [],
        )


class ZipAssetFilesTest(unittest.TestCase):
    """`own_artifacts` must read its bundled assets from inside a zip archive too.

    `importlib.resources.files` hands back a `zipfile.Path` when the package is
    read straight out of a zip (built with `zipapp`, for instance) instead of a
    real `pathlib.Path`. The two share `iterdir`, `is_dir`, `is_file` and
    `read_bytes`, so `_asset_files` must walk the tree using only those, the
    same constraint `pegasus.core.content` already had to satisfy.
    """

    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        archive_path = Path(self._directory.name) / "assets.zip"
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("plugins/engram.ts", "// plugin\n")
            archive.writestr("plugins/nested/helper.ts", "// helper\n")
        self.zip_file = zipfile.ZipFile(archive_path)
        self.addCleanup(self.zip_file.close)
        self.zip_root = zipfile.Path(self.zip_file)

    def test_files_nested_inside_a_zip_are_found(self):
        found = adapter_module._asset_files(self.zip_root / "plugins")
        relative = sorted(str(item[1]) for item in found)
        self.assertEqual(relative, ["engram.ts", "nested/helper.ts"])

    def test_content_is_read_from_inside_the_zip(self):
        found = dict(
            (str(relative), path.read_bytes())
            for path, relative in adapter_module._asset_files(self.zip_root / "plugins")
        )
        self.assertEqual(found["engram.ts"], b"// plugin\n")


class RealZipappShipsTheEngramPluginTest(unittest.TestCase):
    """The real Engram plugin must resolve from inside a real zipapp build.

    `ZipAssetFilesTest` above proves `_asset_files` can walk a `zipfile.Path`
    generically, but with a placeholder ("// plugin\\n") standing in for the
    real file -- it cannot tell a correctly shipped plugin from an accidentally
    empty one. This test builds the actual `pegasus` zipapp from this checkout's
    own source, loads `pegasus.adapters.opencode.adapter` from inside that
    archive in a subprocess, and reads back the plugin content `own_artifacts`
    hands out. This project has already shipped assets that resolved fine from
    a checkout and silently degraded once packaged, so the check only counts if
    it runs against a real archive, not a synthetic one.
    """

    @classmethod
    def setUpClass(cls):
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.source = (
            cls.repo_root
            / "src/pegasus/adapters/opencode/assets/plugins/engram.ts"
        )
        tools_dir = cls.repo_root / "tools"
        if str(tools_dir) not in sys.path:
            sys.path.insert(0, str(tools_dir))
        from build_zipapp import build as build_zipapp

        cls._tmp = tempfile.TemporaryDirectory()
        cls.archive = Path(cls._tmp.name) / "pegasus"
        build_zipapp(cls.repo_root / "src" / "pegasus", cls.archive)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def _plugin_bytes_from_the_archive(self) -> bytes:
        script = textwrap.dedent(
            f"""
            import sys
            sys.path.insert(0, {str(self.archive)!r})
            from pathlib import Path
            from pegasus.adapters.opencode.adapter import Adapter
            from pegasus.core.types import Environment

            home = Path("/dev/shm/pegasus-zip-probe-home")
            env = Environment(home=home, data_dir=home / ".local" / "share" / "pegasus-harness")
            adapter = Adapter()
            layout = adapter.layout(env)
            artifacts = adapter.own_artifacts(layout)
            plugin = next(
                item for item in artifacts
                if str(item.path).endswith("plugins/engram.ts")
            )
            sys.stdout.buffer.write(plugin.content)
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, check=True
        )
        return result.stdout

    def test_the_plugin_shipped_inside_the_archive_is_byte_identical_to_the_source(self):
        self.assertEqual(
            self._plugin_bytes_from_the_archive(),
            self.source.read_bytes(),
        )


class SkillRegistryContractTest(unittest.TestCase):
    """The one contract that spans a TypeScript plugin and a Python install plan.

    Nothing else crosses this seam, so nothing else can catch it drifting: the
    plugin reads a file the installer writes, and neither side imports the other.
    """

    PLUGIN = (
        Path(__file__).resolve().parent.parent
        / "src/pegasus/adapters/opencode/assets/plugins/pegasus-skill-registry.ts"
    )

    def setUp(self):
        self.layout = Adapter().layout(ENVIRONMENT)
        self.artifacts = Adapter().own_artifacts(self.layout)
        self.files = {item.path: item for item in only(self.artifacts, FileArtifact)}

    def contract_path(self):
        """The target the plugin reads, taken from the plugin instead of restated."""
        source = self.PLUGIN.read_text(encoding="utf-8")
        match = re.search(
            r'join\(\s*configDirectory\s*,\s*"opencode"\s*,\s*"([^"]+)"\s*\)', source
        )
        self.assertIsNotNone(match, "the plugin no longer builds its contract path this way")
        return self.layout.config_dir / match.group(1)

    def test_the_installer_writes_the_file_the_plugin_reads(self):
        self.assertIn(self.contract_path(), self.files)

    def test_the_contract_carries_resolved_paths_not_placeholders(self):
        declared = dict(
            line.split("=", 1)
            for line in self.files[self.contract_path()].content.decode("utf-8").splitlines()
            if "=" in line and not line.lstrip().startswith("#")
        )
        self.assertEqual(
            declared,
            {
                "PEGASUS_SKILL_REGISTRY_BIN": str(
                    self.layout.config_dir / "pegasus/skill-registry/pegasus-skill-registry"
                ),
                "PEGASUS_SKILL_ROOTS": str(self.layout.skills_dir),
            },
        )

    def test_every_declared_path_is_an_artifact_this_install_creates(self):
        binary = self.layout.config_dir / "pegasus/skill-registry/pegasus-skill-registry"
        self.assertIn(binary, self.files)
        self.assertEqual(self.layout.skills_dir, self.layout.config_dir / "skills")

    def test_the_binary_the_plugin_executes_is_installed_executable(self):
        """A wrapper the plugin hands to execFile is useless at 0644.

        The contract can name the right path and the plugin still fail: the
        permission travels with the artifact, not with the asset it was read from.
        """
        binary = self.files[
            self.layout.config_dir / "pegasus/skill-registry/pegasus-skill-registry"
        ]
        self.assertTrue(binary.executable, f"executable is {binary.executable}")

    def test_no_placeholder_example_is_shipped_any_more(self):
        stray = [path for path in self.files if path.name.endswith(".example")]
        self.assertEqual(stray, [])


class ShippedContentRenderTest(unittest.TestCase):
    """Rendering everything this repository distributes must not collide with itself."""

    @classmethod
    def setUpClass(cls):
        adapter, cls.layout = Adapter(), Adapter().layout(ENVIRONMENT)
        loaded = cls.loaded = content_module.load()
        cls.artifacts = [
            *(item for skill in loaded.skills for item in adapter.render_skill(cls.layout, skill)),
            *(item for agent in loaded.agents for item in adapter.render_agent(cls.layout, agent)),
            *(item for agent in loaded.agents for item in adapter.render_prompt(cls.layout, agent)),
            *(item for command in loaded.commands for item in adapter.render_command(cls.layout, command)),
            *(item for mcp in loaded.mcp for item in adapter.render_mcp(cls.layout, mcp)),
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

    def test_no_shipped_agent_renders_a_tools_map_lacking_the_deny_baseline(self):
        for agent in self.loaded.agents:
            value = only(render_module.agent(self.layout, agent), ConfigKeyArtifact)[0].value
            self.assertIs(value["tools"]["*"], False, agent.name)

    def test_no_shipped_agent_renders_a_permission_block_lacking_the_deny_baseline(self):
        for agent in self.loaded.agents:
            value = only(render_module.agent(self.layout, agent), ConfigKeyArtifact)[0].value
            self.assertEqual(value["permission"]["*"], "deny", agent.name)
            self.assertEqual(value["permission"]["task"]["*"], "deny", agent.name)

    def test_no_shipped_agent_that_declares_write_renders_an_orphaned_write_permission(self):
        """`write` has no permission of its own in the runtime's schema -- an agent
        declaring it must show up under `edit`, never under a `write` key that
        the runtime's resolver would simply never look at.
        """
        declares_write = [a for a in self.loaded.agents if "write" in (*a.requires_tools, *a.optional_tools)]
        self.assertTrue(declares_write, "fixture drifted: no shipped agent declares write any more")
        for agent in declares_write:
            value = only(render_module.agent(self.layout, agent), ConfigKeyArtifact)[0].value
            self.assertNotIn("write", value["permission"], agent.name)
            self.assertEqual(value["permission"]["edit"], "allow", agent.name)

    def test_the_persona_renders_its_declared_tools_as_a_real_restriction(self):
        """The voice declares `read`, `write` and `edit` -- what applying a change
        takes -- and only this side proves that denies everything else, `bash`
        included.
        """
        persona = next(a for a in self.loaded.agents if a.name == "king-pegasus")
        value = only(render_module.agent(self.layout, persona), ConfigKeyArtifact)[0].value
        self.assertEqual(value["tools"], {"*": False, "read": True, "write": True, "edit": True})

    def test_the_orchestrator_renders_its_declared_allows_on_top_of_the_deny_baseline(self):
        orchestrator = next(a for a in self.loaded.agents if a.name == "pegasus-orchestrator")
        value = only(render_module.agent(self.layout, orchestrator), ConfigKeyArtifact)[0].value
        self.assertEqual(value["permission"]["task"]["*"], "deny")
        for name in orchestrator.may_delegate_to:
            self.assertEqual(value["permission"]["task"][name], "allow")


class PlaceholderRenderTest(unittest.TestCase):
    """The adapter answers what the body could not know.

    A body ships one text to every CLI, so it names a fact and this adapter turns
    it into its own path. An adapter whose layout has no such concept must say so
    rather than write a blank into an agent's loading gate.
    """

    def setUp(self):
        self.adapter = Adapter()
        self.layout = self.adapter.layout(ENVIRONMENT)
        self.skills = str(CONFIG / "skills")

    def test_a_prompt_file_gets_the_installed_skills_root(self):
        agent = Agent(
            name="sdd-apply",
            description="Implementation executor",
            body="Read {{skills_root}}/sdd-apply/SKILL.md first.\n",
            mode=AgentMode.SUBAGENT,
            source=PurePosixPath("agents/sdd-apply.md"),
        )
        content = self.adapter.render_prompt(self.layout, agent)[0].content.decode("utf-8")
        self.assertIn(f"{self.skills}/sdd-apply/SKILL.md", content)
        self.assertNotIn("{{", content)

    def test_an_inlined_agent_body_gets_it_too(self):
        agent = Agent(
            name="sdd-apply",
            description="Implementation executor",
            body="Read {{skills_root}}/sdd-apply/SKILL.md first.\n",
            mode=AgentMode.SUBAGENT,
            source=PurePosixPath("agents/sdd-apply.md"),
        )
        value = render_module.agent(self.layout, agent, separate_prompt=False)[0].value
        self.assertIn(self.skills, value["prompt"])

    def test_a_command_body_gets_it(self):
        item = Command(
            name="sdd-apply",
            description="Implement tasks",
            body="Load {{skills_root}}/sdd-apply/SKILL.md.\n",
            runs_as=RunsAs.BUILDER,
            execution=Execution.ISOLATED,
            source=PurePosixPath("commands/sdd-apply.md"),
        )
        content = self.adapter.render_command(self.layout, item)[0].content.decode("utf-8")
        self.assertIn(self.skills, content)

    def test_a_system_prompt_body_gets_it(self):
        item = SystemPrompt(
            body="Skills live in {{skills_root}}.\n",
            source=PurePosixPath("system-prompt/AGENTS.md"),
        )
        artifact = only(self.adapter.render_system_prompt(self.layout, item), FileArtifact)[0]
        self.assertIn(self.skills, artifact.content.decode("utf-8"))

    def test_a_layout_without_skills_refuses_instead_of_writing_a_blank(self):
        layout = Layout(config_dir=CONFIG, prompts_dir=CONFIG / "prompts")
        agent = Agent(
            name="sdd-apply",
            description="Implementation executor",
            body="Read {{skills_root}}/sdd-apply/SKILL.md first.\n",
            mode=AgentMode.SUBAGENT,
            source=PurePosixPath("agents/sdd-apply.md"),
        )
        with self.assertRaises(render_module.RenderError) as raised:
            render_module.prompt(layout, agent)
        self.assertIn("skills_root", str(raised.exception))

    def test_a_body_with_nothing_to_fill_is_untouched(self):
        agent = Agent(
            name="sdd-verify",
            description="Readiness authority",
            body="# Verify\n\nProve it.\n",
            mode=AgentMode.SUBAGENT,
            source=PurePosixPath("agents/sdd-verify.md"),
        )
        content = self.adapter.render_prompt(self.layout, agent)[0].content.decode("utf-8")
        self.assertEqual(content, "# Verify\n\nProve it.\n")


if __name__ == "__main__":
    unittest.main()


class DeclaredProgramsMatchTheTreeTest(unittest.TestCase):
    """The executable bit is declared, and this is what keeps the declaration true.

    It has to be declared: inside an archive the bit cannot be read at all, so
    asking the file would answer one way from a checkout and another way from a
    zip, and nothing would say they disagreed.

    But a declaration drifts. An asset added with its executable bit set and not
    named here would ship as plain text, and the failure lands far away — a
    program someone's plugin cannot run. So the set is held to what this
    package's own tree really carries, on disk, which is the one place the
    question can still be asked directly.
    """

    def executables_on_disk(self) -> set[str]:
        root = Path(adapter_module.__file__).resolve().parent / "assets"
        return {
            path.name
            for path in root.rglob("*")
            if path.is_file() and path.stat().st_mode & 0o111 and "__pycache__" not in path.parts
        }

    def test_every_asset_that_is_executable_on_disk_is_declared(self):
        undeclared = self.executables_on_disk() - set(adapter_module.EXECUTABLE_ASSETS)
        self.assertEqual(
            sorted(undeclared), [], "executable assets that would ship without their bit"
        )

    def test_nothing_is_declared_that_is_not_executable_on_disk(self):
        """The other direction: a name left behind after its file stopped being
        a program would quietly hand out a bit nothing needs."""
        stale = set(adapter_module.EXECUTABLE_ASSETS) - self.executables_on_disk()
        self.assertEqual(sorted(stale), [], "declared programs that are not executable in the tree")
