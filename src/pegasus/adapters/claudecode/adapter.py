"""The Claude Code adapter.

Implements exactly the capabilities its manifest declares, and nothing else: a
render method for an undeclared capability is a phantom capability and the
registry rejects it.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from pegasus.adapters.claudecode import layout as layout_module
from pegasus.adapters.claudecode import manifest as manifest_module
from pegasus.adapters.claudecode import render
from pegasus.core.content import Agent, Command, Mcp, Skill, SystemPrompt
from pegasus.core.identity import Identity
from pegasus.core.types import (
    Artifact,
    CapabilityManifest,
    ConfigKeyArtifact,
    Detection,
    DirectoryGrantBehavior,
    Environment,
    Layout,
    McpGrantBehavior,
    ModelAssignment,
    SupportTier,
)

BINARY = "claude"


class Adapter:
    """Everything Pegasus needs to know about Claude Code."""

    id = manifest_module.CLI_ID
    display_name = manifest_module.DISPLAY_NAME
    # See the identical field on the OpenCode adapter for why this is public:
    # `tools/build_installer.py` needs the executable name to derive the
    # shell installer's per-CLI detection command.
    binary = BINARY

    def tier(self) -> SupportTier:
        return SupportTier.PARTIAL

    def capabilities(self) -> CapabilityManifest:
        return manifest_module.MANIFEST

    def activation_steps(self) -> tuple[str, ...]:
        """Nothing: this CLI reads what was written without being restarted.

        That is the one condition the port names for returning an empty
        tuple, and it is returned here on measurement rather than on
        optimism. This step used to say to restart, and said so honestly:
        the documentation covers `settings.json` and skills as hot-reloaded
        and is silent about agent and command files, and silence is not
        permission to claim either answer.

        Measuring it needed something no automated probe here could supply.
        `claude -p` starts a fresh process per invocation -- `--continue`
        included, which resumes a conversation rather than a process -- so
        every such probe proves only that a new process reads new files,
        which was never in doubt. A relocated config directory cannot stand
        in either: it relocates credentials with everything else, so the
        session it starts is logged out. What settled it was a person
        holding one live interactive session open while the files beneath it
        were edited from outside.

        Three arms, each keyed on a random sentinel no model could have
        produced from context, all positive. An existing sub-agent's
        definition is re-read on the next delegation: the same agent that
        had just answered it had no codeword returned the sentinel, in the
        same session. The shared instruction file under `rules/` is re-read
        by the main session itself, answering without delegating. And a
        slash command file that did not exist when the session opened was
        indexed and answered on first use -- covering both halves of what
        the retired text called into doubt, a command file and a newly
        written one. None of the three needed a restart-and-retry control:
        a control arm disambiguates a *negative* result, and a sentinel that
        reaches the transcript can only have come from the file it was
        written into minutes earlier.

        The OpenCode adapter's own restart step is measured too, in the
        opposite direction, and stays. The difference between the two is now
        a fact on both sides rather than a fact on one and a precaution on
        the other.
        """
        return ()

    # --- Detection: PATH and the filesystem only, never execution ---

    def detect(self, environment: Environment) -> Detection:
        binary = shutil.which(BINARY, path=environment.variables.get("PATH"))
        config = layout_module.config_dir(environment)
        return Detection(
            installed=binary is not None,
            binary_path=Path(binary) if binary else None,
            config_dir=config,
            config_found=config.is_dir(),
        )

    # --- Where ---

    def layout(self, environment: Environment) -> Layout:
        return layout_module.build(environment)

    # --- How ---

    def render_skill(self, layout: Layout, skill: Skill) -> list[Artifact]:
        return render.skill(layout, skill)

    def render_agent(
        self,
        layout: Layout,
        agent: Agent,
        assignment: ModelAssignment | None = None,
        *,
        mcp: tuple[Mcp, ...],
    ) -> list[Artifact]:
        return render.agent(layout, agent, assignment, mcp)

    def render_mcp(self, layout: Layout, mcp: Mcp) -> list[Artifact]:
        return render.mcp(layout, mcp)

    def writes_mcp_config_key(self) -> bool:
        """Never: see `render.mcp`'s own docstring. Claude Code keeps a
        server's definition inside each granted agent's own `mcpServers:`
        frontmatter, not in one global settings key, so this adapter never
        writes a `/mcp/<id>` pointer for any server -- bound or not."""
        return False

    def render_command(self, layout: Layout, command: Command, orchestrator_name: str) -> list[Artifact]:
        return render.command(layout, command, orchestrator_name)

    def directory_grant_behavior(self) -> DirectoryGrantBehavior:
        """`allowed_by_default=True`: `render.PERMISSIONS_ALLOW` already
        grants `Read(//**)`/`Edit(//**)` at every install, floor excepted --
        the same product decision already taken for OpenCode's own baseline,
        so a granted directory changes nothing today here either.

        `writes_own_entry=False`: unlike OpenCode's `external_directory`,
        this CLI has no per-directory permission concept at all -- its own
        `permissions.allow`/`deny` are anchored at the filesystem root
        (`//**`), not scoped per granted path -- so granting one renders no
        rule of its own; the journal entry is the only place it lives.

        `has_deny_floor=True`: `render.PERMISSIONS_DENY_FLOOR` writes the
        same five `content.DENY_FLOOR_DIRECTORIES`, as `Read(...)`/`Edit(...)`
        pairs, after `PERMISSIONS_ALLOW` -- deny still wins the runtime's own
        resolution -- so `cli.directory_grant` should warn here too when a
        granted path falls under one of them (`content.deny_floor_shadows`).
        """
        return DirectoryGrantBehavior(allowed_by_default=True, writes_own_entry=False, has_deny_floor=True)

    def mcp_grant_behavior(self) -> McpGrantBehavior:
        """`writes_per_agent_entry=True`: `core.catalog.render`'s `_mcp_for_
        agent` folds `item.granted_mcp` in alongside `item.optional_mcp`, so
        a key granted through `mcp grant` reaches every agent's own
        `mcpServers:` frontmatter as a bare, bound-reference entry --
        `_mcp_servers_field`'s own `is_bound` branch, the exact shape this
        adapter already writes for a shipped server bound to a key the user
        administers. If the grant is to the session-identity agent, `_tools_
        field`'s own `item.default` branch adds the matching `mcp__<key>`
        entry there too, the same as for any other server it was granted.
        Measured live on 2026-09-27 (`docs/arquitectura/arquitectura.md`'s
        7.3.3 section): a sub-agent reaches a bound server named this way,
        and did not before this key was rendered anywhere at all."""
        return McpGrantBehavior(writes_per_agent_entry=True)

    def render_system_prompt(
        self, layout: Layout, system_prompt: SystemPrompt, identity: Identity
    ) -> list[Artifact]:
        return render.system_prompt(layout, system_prompt, identity)

    # --- What this adapter ships on its own ---

    def own_artifacts(
        self,
        layout: Layout,
        orchestrator_name: str,
        identity: Identity,
        delegation_targets: tuple[Any, ...],
    ) -> list[Artifact]:
        """One artifact: the `agent` key in `settings.json`.

        Pegasus's orchestrator is an ordinary `mode: primary` agent in the
        content core; Claude Code's main session is not a file at all. This
        one key is the whole bridge between the two: `settings.json`'s
        top-level `agent` field is documented as "start every session as a
        named subagent with its prompt, tools, and model" -- so the
        orchestrator renders as an ordinary agent file, exactly like every
        other agent (see `render.agent`'s own docstring for why no special
        file shape exists for `mode: primary`), and this single key is what
        makes a fresh session adopt it, carrying its prompt, tools and model
        along with it.

        `orchestrator_name` is the same content-declared name `render_
        command` receives for `RunsAs.ORCHESTRATOR` (see `Content.
        SESSION_STARTS_IN`) -- never a literal this adapter invents -- which
        is exactly why it is written here as a value, not baked in as a key.

        `identity` is unused: this adapter ships no bundled asset that needs
        to name the running distribution, unlike OpenCode's plugins. It is
        still accepted, because the port's signature requires every adapter
        to take it.

        `delegation_targets`, unlike `identity`, IS used: it is what
        `render.delegation_capabilities` turns into the generated reference
        every delegating agent's body already points at
        (`{{skills_root}}/_shared/delegation-capabilities.md`, six agent
        bodies -- see `content.delegation_capabilities_path`). Before this,
        this adapter accepted the parameter but never wrote the file it
        describes, leaving that pointer dangling in every real Claude Code
        install: the instruction survives on its own stated fallback ("if
        this reference is missing or unreadable, do not assume the
        capability"), but the whole capability-table feature was silently
        absent for this CLI. See `render.delegation_capabilities`'s own
        docstring for why its table is not a copy of OpenCode's -- it must
        speak this CLI's own tool and MCP-denial vocabulary, not the other
        adapter's, or it would lie about what a target can actually run.

        `render.permission_artifacts` contributes the rest: the fixed
        `permissions.allow`/`permissions.deny` entries that make external
        directories allowed by default in this CLI too, with the same fixed
        five-directory deny floor OpenCode already carries -- see that
        function's own docstring for why each rule is its own appended
        `ConfigKeyArtifact` rather than one value owning the whole array.
        """
        return [
            ConfigKeyArtifact(
                id="own:orchestrator-agent",
                path=layout.settings_file,
                pointer="/agent",
                value=orchestrator_name,
            ),
            *render.delegation_capabilities(layout, delegation_targets),
            *render.permission_artifacts(layout),
        ]
