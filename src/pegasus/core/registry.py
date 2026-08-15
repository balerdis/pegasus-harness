"""The gate that keeps the adapter abstraction from rotting.

Registration validates an adapter's claims against what it actually implements.
An adapter that disagrees with its own manifest never gets registered, so the
failure surfaces at startup instead of halfway through writing a user's home
directory.
"""
from __future__ import annotations

from pathlib import Path

from pegasus.core.types import Capability, CapabilityManifest, Environment, Layout

PROBE = Environment(home=Path("/nonexistent/pegasus-registry-probe"))
"""A home that does not exist, used to prove layouts are pure path arithmetic."""

RENDERERS: dict[Capability, tuple[str, ...]] = {
    Capability.SKILLS: ("render_skill",),
    Capability.SYSTEM_PROMPT: ("render_system_prompt",),
    Capability.SLASH_COMMANDS: ("render_command",),
    Capability.SUB_AGENTS: ("render_agent",),
    Capability.PROMPTS: ("render_prompt",),
    Capability.MCP: ("render_mcp",),
    Capability.PER_AGENT_MODEL: (
        "model_catalog",
        "read_model_assignments",
        "render_model_assignment",
    ),
}


class RegistryError(Exception):
    """An adapter cannot be registered."""


class DuplicateAdapterError(RegistryError):
    """Two adapters claim the same identifier."""


class ManifestMismatchError(RegistryError):
    """An adapter's manifest disagrees with what it implements."""


class AdapterScopeError(RegistryError):
    """An adapter would write outside the territory of its own CLI."""


class Registry:
    """The set of adapters this installation can use."""

    def __init__(self, *adapters: object) -> None:
        self._adapters: dict[str, object] = {}
        self._manifests: dict[str, CapabilityManifest] = {}
        for adapter in adapters:
            self.register(adapter)

    def register(self, adapter: object) -> None:
        cli_id = getattr(adapter, "id", "")
        if not cli_id:
            raise ManifestMismatchError("an adapter must expose a non-empty id")
        if cli_id in self._adapters:
            raise DuplicateAdapterError(f"an adapter is already registered for {cli_id!r}")

        manifest = adapter.capabilities()
        layout = adapter.layout(PROBE)
        _check_identity(adapter, cli_id, manifest)
        _check_capabilities(adapter, cli_id, manifest, layout)
        _check_own_artifacts(adapter, cli_id, layout)
        _check_activation_steps(adapter, cli_id)

        self._adapters[cli_id] = adapter
        self._manifests[cli_id] = manifest

    def get(self, cli_id: str) -> object:
        try:
            return self._adapters[cli_id]
        except KeyError:
            raise KeyError(f"no adapter registered for {cli_id!r}") from None

    def manifest(self, cli_id: str) -> CapabilityManifest:
        self.get(cli_id)
        return self._manifests[cli_id]

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))

    def __contains__(self, cli_id: object) -> bool:
        return cli_id in self._adapters

    def __len__(self) -> int:
        return len(self._adapters)


def _check_activation_steps(adapter: object, cli_id: str) -> None:
    """Confirm the adapter can say what is still left for the user to do.

    The engine asks every adapter this while reporting, and reporting happens
    after the artifacts are already on disk. An adapter that cannot answer would
    turn a finished installation into a traceback, so the question is asked once
    here, at registration, where nothing has been written yet.
    """
    if not _implements(adapter, "activation_steps"):
        raise ManifestMismatchError(
            f"adapter {cli_id!r} must implement activation_steps; "
            "return an empty tuple when its CLI picks changes up on its own"
        )


def _check_own_artifacts(adapter: object, cli_id: str, layout: Layout) -> None:
    """Confirm the adapter's own artifacts stay inside its CLI's configuration root.

    `own_artifacts` is the one place an adapter contributes files the content core
    knows nothing about, so it is also the one place an adapter could reach into
    somewhere it has no business writing. The check runs at registration against
    the probe home: it reads the adapter's bundled assets, which are always
    present, but never the user's home.
    """
    if not _implements(adapter, "own_artifacts"):
        raise ManifestMismatchError(
            f"adapter {cli_id!r} must implement own_artifacts; return an empty list when it ships nothing"
        )
    for artifact in adapter.own_artifacts(layout):
        if not artifact.path.is_relative_to(layout.config_dir):
            raise AdapterScopeError(
                f"adapter {cli_id!r} would write {artifact.path} outside {layout.config_dir}"
            )


def _check_identity(adapter: object, cli_id: str, manifest: CapabilityManifest) -> None:
    if manifest.cli_id != cli_id:
        raise ManifestMismatchError(
            f"adapter {cli_id!r} returned a manifest for {manifest.cli_id!r}"
        )


def _check_capabilities(
    adapter: object, cli_id: str, manifest: CapabilityManifest, layout: Layout
) -> None:
    for capability in Capability:
        declared = manifest.declares(capability)
        anchor = layout.anchor(capability)
        implemented = [name for name in RENDERERS[capability] if _implements(adapter, name)]
        missing = [name for name in RENDERERS[capability] if name not in implemented]

        if declared:
            if anchor is None and capability in _NEEDS_ANCHOR:
                raise ManifestMismatchError(
                    f"adapter {cli_id!r} declares {capability.value!r} but its layout has no path for it"
                )
            if missing:
                raise ManifestMismatchError(
                    f"adapter {cli_id!r} declares {capability.value!r} but does not implement "
                    + ", ".join(missing)
                )
        else:
            if anchor is not None:
                raise ManifestMismatchError(
                    f"adapter {cli_id!r} exposes a path for {capability.value!r} without declaring it"
                )
            if implemented:
                raise ManifestMismatchError(
                    f"adapter {cli_id!r} implements " + ", ".join(implemented)
                    + f" without declaring {capability.value!r}"
                )


# A dedicated anchor can only be demanded of capabilities that materialize as
# files in every CLI. The rest may live inside the settings file instead: one CLI
# declares its subagents there while another writes them as files in a directory.
# Demanding a directory from both would force one of them to declare a path it
# never uses, which is exactly the fiction this check exists to prevent.
_SETTINGS_BASED = frozenset(
    {Capability.SUB_AGENTS, Capability.MCP, Capability.PER_AGENT_MODEL}
)
_NEEDS_ANCHOR = frozenset(
    capability for capability in Capability if capability not in _SETTINGS_BASED
)


def _implements(adapter: object, name: str) -> bool:
    return callable(getattr(adapter, name, None))
