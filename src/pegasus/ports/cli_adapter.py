"""The port every CLI integration implements.

The interface splits two questions that are easy to conflate:

- **Where** an artifact goes — answered by :meth:`CliAdapter.layout`.
- **How** it is spelled — answered by the ``render_*`` methods.

Because both live behind the adapter, the engine never asks which CLI it is
working with.

**Partial implementation is the contract, not a shortcut.** An adapter
implements only the ``render_*`` methods for the capabilities its manifest
declares. Defining a render method for an undeclared capability is a phantom
capability and the registry rejects it, exactly as it rejects a declared
capability with no implementation.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pegasus.core.identity import Identity
from pegasus.core.types import (
    Artifact,
    CapabilityManifest,
    Detection,
    DirectoryGrantBehavior,
    Environment,
    Layout,
    ModelAssignment,
    SupportTier,
)

@runtime_checkable
class CliAdapter(Protocol):
    """Everything Pegasus needs to know about one CLI."""

    # --- Identity ---

    @property
    def id(self) -> str:
        """Stable identifier, and the name of this adapter's package directory."""

    @property
    def display_name(self) -> str:
        """Name shown to the user in menus."""

    def tier(self) -> SupportTier: ...

    def capabilities(self) -> CapabilityManifest: ...

    # --- Detection ---

    def detect(self, environment: Environment) -> Detection:
        """Look for the CLI using PATH and the filesystem only. Never execute it."""

    # --- Where ---

    def layout(self, environment: Environment) -> Layout:
        """Resolve this CLI's paths. Pure path arithmetic: no filesystem access."""

    # --- How: one method per capability. Every render takes the resolved
    # layout, so an adapter carries no per-machine state of its own. ---

    def render_skill(self, layout: Layout, skill: Any) -> list[Artifact]: ...

    def render_agent(
        self,
        layout: Layout,
        agent: Any,
        assignment: ModelAssignment | None = None,
        *,
        mcp: tuple[Any, ...],
    ) -> list[Artifact]:
        """`assignment`, when given, is an already-resolved model and effort --
        a preference from Pegasus's own state, its model validated against
        what this machine can reach, never a fact the content core itself
        carries. Naming the model and spelling an effort in this CLI's own
        vocabulary (its ``variant``, say) is this adapter's job, not the
        engine's. `None` is a real state of its own here -- "no model was
        assigned" -- which is exactly why `assignment` keeps its default.

        `mcp` has none, and is keyword-only so that a required parameter can
        follow a defaulted one. `()` would mean two things at once -- "this
        agent was granted nothing" and "the caller forgot to pass it" -- and
        only the first is a state this port should let a caller reach by
        omission. A future refactor that stops passing `mcp` at the call in
        `core.catalog.render` would still find every other piece of an agent
        in place -- frontmatter, tools, body -- and render a file that looks
        complete but has silently lost every MCP server it was granted,
        exactly the silent-capability-gap failure mode `own_artifacts`'s
        `delegation_targets` already pays to close. Requiring `mcp` turns
        that drop into a loud `TypeError` at the call site instead. A caller
        exercising `render_agent` in isolation passes an empty tuple
        explicitly.

        `mcp` is the resolved `Mcp` descriptors this agent was granted --
        exactly the servers named in its `optional_mcp`, looked up back
        against `Content.mcp` by `core.catalog.render` after `select_mcp`/
        `grant_mcp` have already pruned and granted (see that function's own
        docstring). It is a tuple of descriptors, never bare server ids: an
        id alone is not enough to spell a server's definition, and spelling
        the definition is exactly the reason this parameter exists.

        Why a *server's own definition* is part of one agent's render for
        some CLIs and a separate, global fact for others is not an accident
        of this port's design -- it is a real difference in where each CLI
        keeps that definition. One CLI's adapter defines a server exactly
        once, globally, inside its own settings file, and an agent merely
        references it by id there (that adapter's own `render_agent`
        accepts `mcp` and ignores it -- see its own docstring for why).
        Another CLI has no such global location inside its own configuration
        directory: a sub-agent's own scoping syntax is documented as the
        only in-tree place a server can be scoped to less than every
        session, and that syntax lives inside the agent's own file, not a
        shared one. So the same fact -- "this agent may reach this server"
        -- is spelled once, at the top of the tree, for one CLI, and once
        per file, at the leaves, for another. `render_agent` is the one
        method every adapter already implements per agent, which is why the
        fact is threaded through here rather than through a new,
        adapter-specific seam: a port serves every CLI's shape by handing
        over the same fact to all of them and letting each adapter decide
        whether its own vocabulary has any use for it.
        """

    def render_command(self, layout: Layout, command: Any, orchestrator_name: str) -> list[Artifact]:
        """`orchestrator_name` is the content-declared name of the agent a
        session starts in (never a literal this adapter picks), and is what
        `RunsAs.ORCHESTRATOR` must render as."""

    def render_prompt(self, layout: Layout, prompt: Any) -> list[Artifact]: ...

    def render_system_prompt(self, layout: Layout, system_prompt: Any, identity: Identity) -> list[Artifact]: ...

    def render_mcp(self, layout: Layout, server: Any) -> list[Artifact]:
        """Render one server's own artifacts -- its settings key, its usage
        convention, or both, depending on what this CLI's vocabulary has a
        place for.

        This method used to declare a third parameter, `resolved`, that
        nothing ever passed: `core.catalog.render` has always called this
        with two arguments, and the one adapter that implemented it before
        this port grew a second has always taken two. `Protocol` is not
        checked against its implementers at runtime, so a phantom parameter
        with no caller and no implementation sat here, undetected, until
        this docstring's own review read the call sites side by side.
        Removed rather than wired up: nothing downstream ever needed a
        second, separately "resolved" form of a server distinct from
        `server` itself -- `Mcp` already carries everything a render needs,
        `bound_to` included -- so inventing a caller for a parameter nobody
        asked for would be solving a problem this codebase does not have.
        """

    def writes_mcp_config_key(self) -> bool:
        """Whether this CLI keeps one global, addressable configuration key
        per granted MCP server -- the `/mcp/<id>` pointer `render_mcp`
        writes for an unbound server on a CLI whose vocabulary has a place
        for one.

        `True` for a CLI that defines a server exactly once, globally, inside
        its own settings file (that adapter's `render_mcp` writes a
        `ConfigKeyArtifact` for every server it does not merely reference).
        `False` for a CLI with no such global location at all -- one where a
        granted agent's own scoping syntax is the only in-tree place a
        server is ever defined, so `render_mcp` never writes a settings key
        for *any* server, bound or not (see that adapter's own `render_mcp`
        docstring).

        This is not the same fact as `capabilities().mcp`: that says this
        CLI's vocabulary has *some* place for a granted server at all; this
        says whether that place is a config-key `doctor`/`update` can read
        back later. The engine needs the distinction because a server this
        method answers `False` for leaves the exact same journal shape a
        binding does -- a convention entry with no `mcp:<id>` key beside it
        -- for every server it installs normally, not only for one the user
        administers. Reading that shape as "granted but not installed by
        Pegasus" is true for a CLI answering `True` here (see
        `cli._bound_checks`) and false for one answering `False`: nothing
        distinguishes a normal grant from a binding there except this fact.
        """

    # --- What the user still has to do ---

    def activation_steps(self) -> tuple[str, ...]:
        """What the user must still do before a change to this CLI takes effect.

        Writing the files is not the same as the CLI having read them. A product
        that loads its configuration once, at startup, keeps running on what it
        read before Pegasus touched the disk, so an installation can be complete
        and inert at the same time — and an uninstall can be complete while the
        running session still behaves as though nothing was removed. Only the
        adapter knows whether that is true of its CLI, which is why the engine
        cannot phrase this.

        The engine asks while reporting, which is after the disk has changed, so
        this is also checked at registration: an adapter that cannot answer must
        fail before the first byte, not after the last.

        Return an empty tuple when the CLI picks changes up on its own.
        """

    # --- What this adapter contributes on its own ---

    def own_artifacts(
        self,
        layout: Layout,
        orchestrator_name: str,
        identity: Identity,
        delegation_targets: tuple[Any, ...],
    ) -> list[Artifact]:
        """Artifacts this adapter ships itself, not derived from the content core.

        Some files exist only because one CLI works the way it does: plugins
        written against its plugin API, the npm manifest those plugins depend on,
        a helper the plugin invokes. There is no agnostic form of any of them, so
        they cannot live in the content core.

        **This is an escape hatch, and the admission test is rule 2: would this
        make sense in a CLI we do not support yet?** If it would, it belongs in
        the content core, not here. Reaching for this method to avoid writing a
        descriptor is how the core slowly empties out.

        Every returned artifact must resolve inside `layout.config_dir`; the
        registry rejects an adapter that writes outside its own territory. Return
        an empty list when the adapter ships nothing of its own.

        `orchestrator_name` is the same content-declared name `render_command`
        receives for `RunsAs.ORCHESTRATOR` (never a literal this adapter picks):
        a bundled asset that needs to recognize the orchestrator session fills
        it in through `core.placeholders` rather than hardcoding it.

        `identity` is the running distribution's own `Identity` -- threaded
        explicitly from `Runtime.identity` through `core.catalog`, never read
        by the adapter on its own (an adapter must not know how to find
        `identity.json`; it only ever receives what the composition root
        resolved). The whole value is passed, not just `program_name`, because
        an adapter-shipped asset is exactly the kind of thing a distribution-
        naming task needs more than one field of `Identity` for (a plugin's
        own npm-visible display text, say, alongside the on-disk names
        `program_name` drives) -- passing the dataclass once avoids
        re-threading this same seam field by field later. A concrete adapter
        implementing this method derives every one of its own asset names
        from `identity` rather than from a fixed literal of its own -- see
        any adapter's own `own_artifacts` for the pattern.

        `delegation_targets` is `core.catalog`'s own derived fact -- every
        agent named in at least one `may_delegate_to`, with the native tools
        and MCP servers it will actually be granted, resolved after
        `select_mcp`/`grant_mcp` have already pruned and granted. It is the
        one deliberate exception to this method's own admission test above:
        the fact itself belongs in the content core (`core.catalog` computes
        it, this port only receives it), but *how it reads* -- a table, a
        list, whatever shape a given CLI's prompts expect -- is exactly the
        kind of presentation choice this method exists to hold. Required, the
        same way `identity` is: a default here would let a future refactor
        drop the argument at the call and still render a plausible-looking
        file with zero rows instead of failing loudly, which is exactly the
        silent-capability-gap failure mode this whole feature exists to
        close. A caller exercising `own_artifacts` in isolation, or an
        adapter untouched by this feature, passes an empty tuple explicitly.
        """

    def directory_grant_behavior(self) -> DirectoryGrantBehavior:
        """What `pegasus directory grant` actually does on this CLI, today.

        Not gated behind any `Capability`: unlike an MCP grant or a
        per-agent model, granting a working directory is a fact every
        registered adapter must be able to state (`content.grant_directories`
        already applies to every adapter alike, with no per-CLI branch), so
        this is required unconditionally, the same way `own_artifacts` is.

        Returning the wrong thing here does not fail loudly the way an
        undeclared render method does -- there is no capability to check it
        against -- so get both fields right the first time: `allowed_by_default`
        is whether this CLI's own baseline already lets every agent read and
        write outside the working directory (floor excepted), and
        `writes_own_entry` is whether granting a directory still renders a
        rule of its own into this CLI's configuration, distinct from that
        baseline fact. See `DirectoryGrantBehavior`'s own docstring for the
        full account of why these are two separate booleans, not one.

        `cli.directory_grant`/`cli._directory_prose` read this instead of
        ever comparing `adapter.id` against a literal to decide what to say
        -- the hexagonal violation `tests/test_cli_directory_all_clis.py`
        guards against.
        """

    # --- Models: only when the manifest declares per_agent_model ---

    def model_catalog(self, environment: Environment) -> Any:
        """Providers and models the user can actually reach on this machine.

        Only what the machine can reach is the adapter's to answer. Which
        agent was given which model is not: that is a preference Pegasus
        keeps in its own state, so nothing here reads it back out of the
        CLI's configuration.
        """

