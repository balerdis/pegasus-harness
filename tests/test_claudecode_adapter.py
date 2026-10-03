"""The Claude Code adapter: the second CLI adapter, and the only place its own
vocabulary (`Read`, `Bash`, `Agent(...)`, `settings.json`'s `agent` key) is
allowed to appear.
"""
from __future__ import annotations

import unittest
from pathlib import Path, PurePosixPath

from pegasus import cli
from pegasus.adapters.claudecode import Adapter
from pegasus.adapters.claudecode import render as render_module
from pegasus.core.content import (
    Agent,
    AgentMode,
    Asset,
    Command,
    Distribution,
    Execution,
    Mcp,
    RunsAs,
    SESSION_STARTS_IN,
    Skill,
    SystemPrompt,
)
from pegasus.core import registry as registry_module
from pegasus.core.catalog import DelegationTarget
from pegasus.core.content import delegation_capabilities_path
from pegasus.core.registry import Registry
from pegasus.core.types import Capability, ConfigKeyArtifact, Environment, FileArtifact, ModelAssignment

HOME = Path("/home/probe")
ENVIRONMENT = Environment(home=HOME, data_dir=HOME / ".local" / "share" / "pegasus-harness")
CONFIG = HOME / ".claude"
ORCHESTRATOR = "pegasus-orchestrator"
IDENTITY = cli.default_identity()


def only(artifacts, kind):
    return [item for item in artifacts if isinstance(item, kind)]


class RegistrationTest(unittest.TestCase):
    def test_the_adapter_satisfies_the_registry(self):
        registry = Registry()
        registry.register(Adapter())
        self.assertEqual(registry.ids(), ("claudecode",))

    def test_declares_only_what_it_implements(self):
        manifest = Adapter().capabilities()
        self.assertEqual(
            sorted(item.value for item in manifest.enabled),
            ["mcp", "skills", "slash_commands", "sub_agents", "system_prompt"],
        )

    def test_the_tier_is_partial(self):
        from pegasus.core.types import SupportTier

        self.assertEqual(Adapter().tier(), SupportTier.PARTIAL)


class LayoutTest(unittest.TestCase):
    def setUp(self):
        self.layout = Adapter().layout(ENVIRONMENT)

    def test_resolves_the_standard_configuration_root(self):
        self.assertEqual(self.layout.config_dir, CONFIG)

    def test_honours_an_absolute_claude_config_dir(self):
        environment = Environment(home=HOME, variables={"CLAUDE_CONFIG_DIR": "/opt/claude"})
        self.assertEqual(Adapter().layout(environment).config_dir, Path("/opt/claude"))

    def test_ignores_a_relative_claude_config_dir(self):
        environment = Environment(home=HOME, variables={"CLAUDE_CONFIG_DIR": "relative/cfg"})
        self.assertEqual(Adapter().layout(environment).config_dir, CONFIG)

    def test_does_not_honour_xdg_config_home(self):
        """Claude Code does NOT honour XDG_CONFIG_HOME, unlike OpenCode."""
        environment = Environment(home=HOME, variables={"XDG_CONFIG_HOME": "/opt/xdg"})
        self.assertEqual(Adapter().layout(environment).config_dir, CONFIG)

    def test_every_file_based_capability_has_its_path(self):
        for capability in Adapter().capabilities().enabled & registry_module._NEEDS_ANCHOR:
            self.assertIsNotNone(self.layout.anchor(capability), capability.value)

    def test_agents_dir_is_a_real_anchor(self):
        self.assertEqual(self.layout.agents_dir, CONFIG / "agents")

    def test_prompts_dir_is_none(self):
        self.assertIsNone(self.layout.prompts_dir)

    def test_plugins_dir_is_none(self):
        self.assertIsNone(self.layout.plugins_dir)

    def test_skills_dir(self):
        self.assertEqual(self.layout.skills_dir, CONFIG / "skills")

    def test_commands_dir(self):
        self.assertEqual(self.layout.commands_dir, CONFIG / "commands")

    def test_settings_file(self):
        self.assertEqual(self.layout.settings_file, CONFIG / "settings.json")

    def test_dependencies_dir(self):
        self.assertEqual(
            self.layout.dependencies_dir, HOME / ".local" / "share" / "pegasus-harness" / "mcp"
        )

    def test_dependencies_dir_is_none_without_a_data_dir(self):
        environment = Environment(home=HOME)
        self.assertIsNone(Adapter().layout(environment).dependencies_dir)

    def test_building_a_layout_touches_no_filesystem(self):
        Adapter().layout(Environment(home=Path("/nonexistent/probe")))


class DetectionTest(unittest.TestCase):
    def test_reports_a_configuration_directory_that_does_not_exist(self):
        detection = Adapter().detect(Environment(home=Path("/nonexistent/probe")))
        self.assertFalse(detection.config_found)
        self.assertEqual(detection.config_dir, Path("/nonexistent/probe/.claude"))

    def test_an_empty_path_finds_no_binary(self):
        detection = Adapter().detect(Environment(home=HOME, variables={"PATH": ""}))
        self.assertFalse(detection.installed)
        self.assertIsNone(detection.binary_path)


class ActivationStepsTest(unittest.TestCase):
    def test_there_is_nothing_left_for_the_user_to_do(self):
        """Empty because this CLI was measured picking changes up on its own,
        which is the one condition the port names for returning nothing.

        This started out non-empty, and honestly so: the text said whether an
        already-running session reads a newly written agent or command file
        was undocumented, which it was. It was then measured against a real
        installation, with a person holding a live interactive session open
        while the files under it were edited from outside -- the one thing a
        `-p` probe cannot simulate, since each of those starts a fresh
        process and so proves nothing about a live one. Three arms, each
        keyed on a random sentinel the model could not have guessed, all
        positive: an existing sub-agent's definition is re-read on the next
        delegation, the shared rules file is re-read by the main session
        itself, and a slash command file that did not exist when the session
        opened is picked up and answers. A positive result needs no control
        arm to be trusted -- a sentinel that reaches the transcript can only
        have come from the file it was written into.

        So the restart line was not made redundant by a design change; it was
        retired by evidence, and keeping it would now be the unsupported
        claim. Contrast the OpenCode adapter, whose own restart step is
        equally measured in the other direction and stays.
        """
        self.assertEqual(Adapter().activation_steps(), ())


class SkillRenderTest(unittest.TestCase):
    def setUp(self):
        self.layout = Adapter().layout(ENVIRONMENT)
        self.skill = Skill(
            name="alpha",
            description="d",
            assets=(
                Asset(PurePosixPath("SKILL.md"), b"skill body {{skills_root}} unresolved"),
                Asset(PurePosixPath("references/guide.md"), b"guide"),
            ),
            source=PurePosixPath("skills/alpha/SKILL.md"),
        )

    def test_travels_verbatim(self):
        artifacts = Adapter().render_skill(self.layout, self.skill)
        self.assertEqual(
            [item.content for item in artifacts],
            [b"skill body {{skills_root}} unresolved", b"guide"],
        )

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
            body="Verify things. Skills live at {{skills_root}}.\n",
            mode=AgentMode.SUBAGENT,
            source=PurePosixPath("agents/sdd-verify.md"),
        )
        fields.update(overrides)
        return Agent(**fields)

    def render(self, **overrides):
        artifacts = self.adapter.render_agent(self.layout, self.agent(**overrides), mcp=())
        return only(artifacts, FileArtifact)[0]

    def test_lands_in_the_agents_directory(self):
        artifact = self.render()
        self.assertEqual(artifact.path, CONFIG / "agents" / "sdd-verify.md")

    def test_frontmatter_names_the_agent(self):
        content = self.render().content.decode()
        self.assertIn('name: "sdd-verify"', content)
        self.assertIn('description: "Readiness authority"', content)

    def test_tools_use_claude_codes_exact_casing(self):
        content = self.render(requires_tools=("read", "bash"), optional_tools=("grep",)).content.decode()
        self.assertIn("Bash", content)
        self.assertNotIn("bash", content)
        self.assertIn("Read", content)
        self.assertIn("Grep", content)

    def test_an_unmapped_tool_raises(self):
        with self.assertRaises(render_module.RenderError):
            self.adapter.render_agent(self.layout, self.agent(requires_tools=("nope",)), mcp=())

    def test_may_delegate_to_becomes_an_agent_entry(self):
        content = self.render(may_delegate_to=("sdd-apply", "sdd-tasks")).content.decode()
        self.assertIn("Agent(sdd-apply, sdd-tasks)", content)

    def test_no_delegation_targets_means_no_agent_entry(self):
        content = self.render(may_delegate_to=()).content.decode()
        self.assertNotIn("Agent(", content)

    def test_the_body_is_filled_and_survives(self):
        content = self.render().content.decode()
        self.assertIn(f"Skills live at {CONFIG / 'skills'}.", content)
        self.assertNotIn("{{skills_root}}", content)

    def test_no_model_key_without_an_assignment(self):
        content = self.render().content.decode()
        self.assertNotIn("model:", content)

    def test_an_assignment_renders_a_model_key(self):
        assignment = ModelAssignment(provider_id="anthropic", model_id="claude-sonnet-5")
        artifact = only(
            self.adapter.render_agent(self.layout, self.agent(), assignment, mcp=()), FileArtifact
        )[0]
        self.assertIn('model: "claude-sonnet-5"', artifact.content.decode())


class RenderAgentRequiresMcpTest(unittest.TestCase):
    """`mcp` has no default: a caller that forgets it must fail loudly with
    `TypeError`, not silently render an agent with zero servers -- the same
    silent-capability-gap failure mode `own_artifacts`'s `delegation_targets`
    already closed once (see `ports.cli_adapter.CliAdapter.render_agent`'s
    own docstring)."""

    def setUp(self):
        self.adapter = Adapter()
        self.layout = self.adapter.layout(ENVIRONMENT)

    def agent(self, **overrides):
        fields = dict(
            name="sdd-verify",
            description="Readiness authority",
            body="Verify things.\n",
            mode=AgentMode.SUBAGENT,
            source=PurePosixPath("agents/sdd-verify.md"),
        )
        fields.update(overrides)
        return Agent(**fields)

    def test_omitting_mcp_raises_type_error(self):
        with self.assertRaises(TypeError):
            self.adapter.render_agent(self.layout, self.agent())


class AgentMcpGrantRenderTest(unittest.TestCase):
    """`render_agent`'s `mcp` parameter must turn into a real, inline
    `mcpServers:` entry -- and a withheld tool must turn into a real
    `disallowedTools` entry -- naming actual output bytes, not intermediate
    shapes."""

    def setUp(self):
        self.adapter = Adapter()
        self.layout = self.adapter.layout(ENVIRONMENT)
        self.server = Mcp(
            name="context7",
            description="d",
            body="# Context7 Convention\n",
            distribution=Distribution.REMOTE,
            endpoint="https://mcp.context7.com/mcp",
            source=PurePosixPath("mcp/context7.md"),
        )

    def agent(self, **overrides):
        fields = dict(
            name="sdd-verify",
            description="Readiness authority",
            body="Verify things.\n",
            mode=AgentMode.SUBAGENT,
            source=PurePosixPath("agents/sdd-verify.md"),
        )
        fields.update(overrides)
        return Agent(**fields)

    def test_a_granted_agent_carries_the_inline_definition(self):
        artifact = only(
            self.adapter.render_agent(self.layout, self.agent(), mcp=(self.server,)), FileArtifact
        )[0]
        content = artifact.content.decode()
        self.assertIn("mcpServers", content)
        self.assertIn('"context7"', content)
        self.assertIn('"type": "http"', content)
        self.assertIn('"url": "https://mcp.context7.com/mcp"', content)

    def test_a_non_granted_agent_carries_no_mcpServers_key(self):
        artifact = only(self.adapter.render_agent(self.layout, self.agent(), mcp=()), FileArtifact)[0]
        self.assertNotIn("mcpServers", artifact.content.decode())

    def test_a_bound_server_is_a_bare_reference_not_a_second_definition(self):
        from dataclasses import replace

        bound = replace(self.server, bound_to="my-own-context7")
        artifact = only(
            self.adapter.render_agent(self.layout, self.agent(), mcp=(bound,)), FileArtifact
        )[0]
        content = artifact.content.decode()
        self.assertIn("my-own-context7", content)
        self.assertNotIn('"type": "http"', content)

    def test_a_withheld_tool_appears_in_disallowed_tools(self):
        from dataclasses import replace

        withheld = replace(self.server, withheld_tools=("dangerous_tool",))
        artifact = only(
            self.adapter.render_agent(self.layout, self.agent(), mcp=(withheld,)), FileArtifact
        )[0]
        content = artifact.content.decode()
        self.assertIn("disallowedTools", content)
        self.assertIn("mcp__context7__dangerous_tool", content)

    def test_a_withheld_tool_uses_the_bound_key_not_the_bare_name(self):
        from dataclasses import replace

        withheld = replace(self.server, bound_to="my-own-context7", withheld_tools=("dangerous_tool",))
        artifact = only(
            self.adapter.render_agent(self.layout, self.agent(), mcp=(withheld,)), FileArtifact
        )[0]
        content = artifact.content.decode()
        self.assertIn("mcp__my-own-context7__dangerous_tool", content)
        self.assertNotIn("mcp__context7__dangerous_tool", content)

    def test_no_disallowed_tools_key_when_nothing_is_withheld(self):
        artifact = only(
            self.adapter.render_agent(self.layout, self.agent(), mcp=(self.server,)), FileArtifact
        )[0]
        self.assertNotIn("disallowedTools", artifact.content.decode())


class SessionIdentityMcpToolsTest(unittest.TestCase):
    """Measured live on Claude Code 2.1.283 (see `docs/arquitectura/
    arquitectura.md`'s 7.3.3 section): the main session -- the agent named
    `SESSION_STARTS_IN`, the one `settings.json`'s `agent` key names -- gets
    ZERO MCP tools from its own `mcpServers:` alone; its `tools:` has to name
    each granted server at the server level (`mcp__<key>`) for the tools to
    appear at all. A sub-agent needs none of this: it already reaches its own
    granted servers' tools through `mcpServers:` alone, so this must never
    apply to one.
    """

    def setUp(self):
        self.adapter = Adapter()
        self.layout = self.adapter.layout(ENVIRONMENT)
        self.server = Mcp(
            name="engram",
            description="d",
            body="# Engram Convention\n",
            distribution=Distribution.REMOTE,
            endpoint="https://engram.example/mcp",
            source=PurePosixPath("mcp/engram.md"),
        )

    def session_identity_agent(self, **overrides):
        fields = dict(
            name=SESSION_STARTS_IN,
            description="Orchestrator",
            body="Orchestrate.\n",
            mode=AgentMode.PRIMARY,
            source=PurePosixPath("agents/pegasus-orchestrator.md"),
            requires_tools=("bash",),
        )
        fields.update(overrides)
        return Agent(**fields)

    def subagent(self, **overrides):
        fields = dict(
            name="sdd-verify",
            description="Readiness authority",
            body="Verify things.\n",
            mode=AgentMode.SUBAGENT,
            source=PurePosixPath("agents/sdd-verify.md"),
            requires_tools=("bash",),
        )
        fields.update(overrides)
        return Agent(**fields)

    def test_session_identity_gets_a_server_level_tool_entry(self):
        content = only(
            self.adapter.render_agent(self.layout, self.session_identity_agent(), mcp=(self.server,)),
            FileArtifact,
        )[0].content.decode()
        self.assertIn("mcp__engram", content)

    def test_session_identity_never_gets_the_silent_no_op_wildcard(self):
        """`mcp__*` was measured as a silent no-op -- never render it."""
        content = only(
            self.adapter.render_agent(self.layout, self.session_identity_agent(), mcp=(self.server,)),
            FileArtifact,
        )[0].content.decode()
        self.assertNotIn("mcp__*", content)

    def test_session_identity_gets_tool_search_to_load_deferred_mcp_tools(self):
        content = only(
            self.adapter.render_agent(self.layout, self.session_identity_agent(), mcp=(self.server,)),
            FileArtifact,
        )[0].content.decode()
        self.assertIn("ToolSearch", content)

    def test_no_mcp_servers_means_no_change_to_tools(self):
        content = only(
            self.adapter.render_agent(self.layout, self.session_identity_agent(), mcp=()), FileArtifact
        )[0].content.decode()
        self.assertNotIn("mcp__", content)
        self.assertNotIn("ToolSearch", content)

    def test_a_bound_servers_key_is_the_one_exposed(self):
        from dataclasses import replace

        bound = replace(self.server, bound_to="my-own-engram")
        content = only(
            self.adapter.render_agent(self.layout, self.session_identity_agent(), mcp=(bound,)),
            FileArtifact,
        )[0].content.decode()
        self.assertIn("mcp__my-own-engram", content)
        self.assertNotIn("mcp__engram", content)

    def test_a_subagent_gets_no_server_level_tool_entry(self):
        """A sub-agent already reaches its granted server's tools through
        `mcpServers:` alone (measured live) -- adding `mcp__<key>` to its
        `tools:` would be a change this fix never asked for."""
        content = only(
            self.adapter.render_agent(self.layout, self.subagent(), mcp=(self.server,)), FileArtifact
        )[0].content.decode()
        self.assertNotIn("mcp__", content)
        self.assertNotIn("ToolSearch", content)


class McpRenderTest(unittest.TestCase):
    """`render_mcp` writes only the shared usage convention for Claude Code --
    the server's own definition lives per agent instead (`AgentMcpGrantRenderTest`)."""

    def setUp(self):
        self.adapter = Adapter()
        self.layout = self.adapter.layout(ENVIRONMENT)
        self.server = Mcp(
            name="context7",
            description="d",
            body="# Context7 Convention\n",
            distribution=Distribution.REMOTE,
            endpoint="https://mcp.context7.com/mcp",
            source=PurePosixPath("mcp/context7.md"),
        )

    def test_renders_exactly_one_artifact(self):
        artifacts = self.adapter.render_mcp(self.layout, self.server)
        self.assertEqual(len(artifacts), 1)

    def test_it_is_the_convention_file_under_shared_skills(self):
        artifact = self.adapter.render_mcp(self.layout, self.server)[0]
        self.assertEqual(
            artifact.path, self.layout.skills_dir / "_shared" / "mcp" / "context7-convention.md"
        )
        self.assertEqual(artifact.content, b"# Context7 Convention\n")

    def test_writes_no_settings_key(self):
        artifacts = self.adapter.render_mcp(self.layout, self.server)
        self.assertEqual(only(artifacts, ConfigKeyArtifact), [])

    def test_a_bound_server_still_gets_its_convention(self):
        from dataclasses import replace

        bound = replace(self.server, bound_to="my-own-context7")
        artifacts = self.adapter.render_mcp(self.layout, bound)
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0].content, b"# Context7 Convention\n")

    def test_a_layout_without_skills_refuses(self):
        from pegasus.core.types import Layout

        layout = Layout(config_dir=CONFIG, settings_file=CONFIG / "settings.json")
        with self.assertRaises(render_module.RenderError) as raised:
            render_module.mcp(layout, self.server)
        self.assertIn("context7", str(raised.exception))

    def test_the_dispatch_table_covers_every_distribution_member(self):
        from pegasus.core.content import Distribution as DistributionEnum

        self.assertEqual(set(render_module.MCP_VALUE), set(DistributionEnum))


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
        return self.adapter.render_command(self.layout, Command(**fields), "pegasus-orchestrator")[0].content.decode()

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
            "pegasus-orchestrator",
        )[0]
        self.assertEqual(artifact.path, CONFIG / "commands" / "sdd-apply.md")

    def test_no_agent_field_for_any_runs_as(self):
        for role in RunsAs:
            content = self.rendered(runs_as=role)
            self.assertNotIn("agent:", content)

    def test_orchestrator_name_does_not_leak_into_the_file(self):
        content = self.rendered(runs_as=RunsAs.ORCHESTRATOR)
        self.assertNotIn("pegasus-orchestrator", content)

    def test_the_body_survives(self):
        self.assertTrue(self.rendered().endswith("Do the work.\n"))

    def test_a_description_with_a_colon_stays_valid(self):
        rendered = self.rendered(description="Trigger: do it now")
        self.assertIn('description: "Trigger: do it now"', rendered)


class SystemPromptRenderTest(unittest.TestCase):
    def render(self, prompt: SystemPrompt):
        return self.adapter.render_system_prompt(self.layout, prompt, IDENTITY)

    def setUp(self):
        self.adapter = Adapter()
        self.layout = self.adapter.layout(ENVIRONMENT)

    def test_ships_one_file_at_rules_program_name(self):
        artifacts = self.render(SystemPrompt(body="# Rules\n", source=PurePosixPath("system-prompt/AGENTS.md")))
        self.assertEqual(len(artifacts), 1)
        artifact = only(artifacts, FileArtifact)[0]
        self.assertEqual(artifact.path, CONFIG / "rules" / f"{IDENTITY.program_name}.md")

    def test_no_settings_wiring_is_needed(self):
        """Unlike OpenCode, `~/.claude/rules/*.md` auto-loads; nothing to append."""
        artifacts = self.render(SystemPrompt(body="# Rules\n", source=PurePosixPath("system-prompt/AGENTS.md")))
        self.assertEqual(only(artifacts, ConfigKeyArtifact), [])

    def test_body_survives(self):
        artifacts = self.render(SystemPrompt(body="# Rules\n", source=PurePosixPath("system-prompt/AGENTS.md")))
        self.assertEqual(only(artifacts, FileArtifact)[0].content.decode(), "# Rules\n")


class OwnArtifactsTest(unittest.TestCase):
    def setUp(self):
        self.adapter = Adapter()
        self.layout = self.adapter.layout(ENVIRONMENT)

    def test_exactly_forty_two_artifacts(self):
        # 42, not 1: `own_artifacts` also emits the generated
        # delegation-capabilities reference (`render.delegation_capabilities`),
        # unconditionally, the same way OpenCode's own `own_artifacts` does,
        # plus the twelve `permissions.allow`/`permissions.deny` entries and the 28
        # `permissions.ask` entries (`git push`, outward `gh` commands, sensitive files)
        # (`render.permission_artifacts`) that make external directories
        # allowed by default in this CLI too, with the same fixed
        # five-directory deny floor -- see `test_claudecode_permissions.py`
        # for the dedicated coverage of those twelve on their own.
        artifacts = self.adapter.own_artifacts(self.layout, "pegasus-orchestrator", IDENTITY, ())
        self.assertEqual(len(artifacts), 42)

    def test_it_is_a_config_key_at_settings_pointing_at_agent(self):
        artifact = self.adapter.own_artifacts(self.layout, "pegasus-orchestrator", IDENTITY, ())[0]
        self.assertIsInstance(artifact, ConfigKeyArtifact)
        self.assertEqual(artifact.path, CONFIG / "settings.json")
        self.assertEqual(artifact.pointer, "/agent")

    def test_the_value_is_the_content_declared_orchestrator_not_a_literal(self):
        artifact = self.adapter.own_artifacts(self.layout, "king-pegasus-two", IDENTITY, ())[0]
        self.assertEqual(artifact.value, "king-pegasus-two")

    def test_stays_inside_config_dir(self):
        for artifact in self.adapter.own_artifacts(self.layout, "pegasus-orchestrator", IDENTITY, ()):
            self.assertTrue(artifact.path.is_relative_to(self.layout.config_dir))


class DelegationCapabilitiesRenderTest(unittest.TestCase):
    """The generated reference itself, in Claude Code's own vocabulary --
    the fix for the gap where six shipped agent bodies pointed at
    `{{skills_root}}/_shared/delegation-capabilities.md` and this adapter
    never wrote it (see `tests/test_adapter_reference_integrity.py`)."""

    def setUp(self):
        self.adapter = Adapter()
        self.layout = self.adapter.layout(ENVIRONMENT)

    def _content(self, targets):
        artifact = only(
            self.adapter.own_artifacts(self.layout, "pegasus-orchestrator", IDENTITY, targets),
            FileArtifact,
        )[0]
        return artifact

    def test_lands_at_the_shared_delegation_capabilities_path(self):
        artifact = self._content(())
        self.assertEqual(artifact.path, self.layout.skills_dir / delegation_capabilities_path())

    def test_a_targets_tools_are_named_in_claude_codes_own_spelling(self):
        """`bash` must render `Bash`, never the lowercase agnostic name --
        the exact vocabulary check the brief calls for: a table rendered in
        the wrong CLI's spelling would lie about what a target can run."""
        target = DelegationTarget(
            name="pegasus-explorer",
            requires_tools=("read", "bash", "grep"),
            optional_tools=(),
            mcp=(),
        )
        text = self._content((target,)).content.decode("utf-8")
        self.assertIn("`pegasus-explorer`", text)
        self.assertIn("Bash", text)
        self.assertIn("Read", text)
        self.assertIn("Grep", text)
        self.assertNotIn("| bash", text)
        self.assertNotIn(", bash", text)

    def test_an_unmapped_tool_name_raises_rather_than_render_silently(self):
        target = DelegationTarget(
            name="pegasus-explorer",
            requires_tools=("no-such-tool",),
            optional_tools=(),
            mcp=(),
        )
        with self.assertRaises(render_module.RenderError):
            self.adapter.own_artifacts(self.layout, "pegasus-orchestrator", IDENTITY, (target,))

    def test_a_withheld_mcp_tool_is_shown_in_claude_codes_own_qualified_form(self):
        """`mcp__<server>__<tool>`, the exact string this adapter's own
        `disallowedTools` frontmatter key would use to refuse it -- not a
        bare tool name, and not OpenCode's `f"{key}_{tool}"` shape."""
        target = DelegationTarget(
            name="pegasus-explorer",
            requires_tools=("read",),
            optional_tools=(),
            mcp=("cbm",),
            withheld_mcp_tools=(("cbm", ("delete_project",)),),
        )
        text = self._content((target,)).content.decode("utf-8")
        self.assertIn("mcp__cbm__delete_project", text)
        self.assertIn("withholds", text)

    def test_no_targets_still_renders_a_valid_empty_table(self):
        text = self._content(()).content.decode("utf-8")
        self.assertIn("| Agent | Native tools | MCP servers |", text)


if __name__ == "__main__":
    unittest.main()
