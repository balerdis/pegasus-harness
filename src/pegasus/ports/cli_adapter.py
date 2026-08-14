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

    # --- How: one method per capability ---

    def render_skill(self, skill: Any) -> list[Artifact]: ...

    def render_agent(self, agent: Any) -> list[Artifact]: ...

    def render_command(self, command: Any) -> list[Artifact]: ...

    def render_prompt(self, prompt: Any) -> list[Artifact]: ...

    def render_system_prompt(self, system_prompt: Any) -> list[Artifact]: ...

    def render_mcp(self, server: Any, resolved: Any) -> list[Artifact]: ...

    def render_plugin(self, plugin: Any) -> list[Artifact]: ...

    # --- Models: only when the manifest declares per_agent_model ---

    def model_catalog(self, environment: Environment) -> Any:
        """Providers and models the user can actually reach on this machine."""

    def read_model_assignments(self, environment: Environment) -> dict[str, ModelAssignment]:
        """Current per-agent assignments. Agents without one are simply absent."""

    def render_model_assignment(
        self, agent_id: str, assignment: ModelAssignment | None
    ) -> Artifact:
        """Assign a model, or clear it when ``assignment`` is None."""
