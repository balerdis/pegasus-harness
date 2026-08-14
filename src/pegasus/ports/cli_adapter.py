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

from pegasus.core.types import (
    Artifact,
    CapabilityManifest,
    Detection,
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

    def render_agent(self, layout: Layout, agent: Any) -> list[Artifact]: ...

    def render_command(self, layout: Layout, command: Any) -> list[Artifact]: ...

    def render_prompt(self, layout: Layout, prompt: Any) -> list[Artifact]: ...

    def render_system_prompt(self, layout: Layout, system_prompt: Any) -> list[Artifact]: ...

    def render_mcp(self, layout: Layout, server: Any, resolved: Any) -> list[Artifact]: ...

    # --- What this adapter contributes on its own ---

    def own_artifacts(self, layout: Layout) -> list[Artifact]:
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
        """

    # --- Models: only when the manifest declares per_agent_model ---

    def model_catalog(self, environment: Environment) -> Any:
        """Providers and models the user can actually reach on this machine."""

    def read_model_assignments(self, environment: Environment) -> dict[str, ModelAssignment]:
        """Current per-agent assignments. Agents without one are simply absent."""

    def render_model_assignment(
        self, agent_id: str, assignment: ModelAssignment | None
    ) -> Artifact:
        """Assign a model, or clear it when ``assignment`` is None."""
