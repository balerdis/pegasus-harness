"""The OpenCode adapter.

Implements exactly the capabilities its manifest declares, and nothing else: a
render method for an undeclared capability is a phantom capability and the
registry rejects it.
"""
from __future__ import annotations

import shutil
from pathlib import Path, PurePosixPath

from pegasus.adapters.opencode import layout as layout_module
from pegasus.adapters.opencode import manifest as manifest_module
from pegasus.adapters.opencode import models as models_module
from pegasus.adapters.opencode import render
from pegasus.core.content import Agent, Command, Mcp, Skill, SystemPrompt
from pegasus.core.model_catalog import ModelCatalog
from pegasus.core.types import (
    Artifact,
    CapabilityManifest,
    ConfigKeyArtifact,
    Detection,
    Environment,
    FileArtifact,
    Layout,
    SupportTier,
)

ASSETS = Path(__file__).resolve().parent / "assets"
BINARY = "opencode"

ASSET_TARGETS: dict[str, PurePosixPath] = {
    "plugins": PurePosixPath("plugins"),
    "notifier": PurePosixPath("notifier"),
    "registry": PurePosixPath("registry"),
    # The skill registry helper lives under a Pegasus-owned subtree so it never
    # sits next to files OpenCode manages itself.
    "skill-registry": PurePosixPath("pegasus/skill-registry"),
}

# The skill registry plugin reads its contract from this file, at the root of
# OpenCode's configuration directory. The name is stated once here and once in
# the plugin, and a test reads the plugin to hold the two together.
SKILL_REGISTRY_CONTRACT = "pegasus-skill-registry.env"
SKILL_REGISTRY_BIN = "pegasus-skill-registry"

NOTIFIER_PLUGIN = "@mohak34/opencode-notifier@0.2.4"


class Adapter:
    """Everything Pegasus needs to know about OpenCode."""

    id = manifest_module.CLI_ID
    display_name = manifest_module.DISPLAY_NAME

    def tier(self) -> SupportTier:
        return SupportTier.FULL

    def capabilities(self) -> CapabilityManifest:
        return manifest_module.MANIFEST

    def activation_steps(self) -> tuple[str, ...]:
        """OpenCode reads an agent's prompt file once, when the process starts.

        Editing that file changes nothing in a session that is already open: the
        agent keeps answering from the text loaded at startup. That was measured
        -- an executor denied twice that a rule existed in its own prompt, then
        quoted it verbatim after a restart -- so an install that does not say this
        looks successful and behaves as if it never happened.
        """
        return (
            "Restart OpenCode. It reads agent prompts once at startup, "
            "so an open session keeps using the previous ones.",
        )

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

    def render_agent(self, layout: Layout, agent: Agent, model: str | None = None) -> list[Artifact]:
        return render.agent(layout, agent, model)

    def render_prompt(self, layout: Layout, agent: Agent) -> list[Artifact]:
        return render.prompt(layout, agent)

    def render_command(self, layout: Layout, command: Command) -> list[Artifact]:
        return render.command(layout, command)

    def render_system_prompt(self, layout: Layout, system_prompt: SystemPrompt) -> list[Artifact]:
        return render.system_prompt(layout, system_prompt)

    def render_mcp(self, layout: Layout, mcp: Mcp) -> list[Artifact]:
        return render.mcp(layout, mcp)

    # --- Models ---

    def model_catalog(self, environment: Environment) -> ModelCatalog:
        return models_module.read(environment)

    # --- What this adapter ships on its own ---

    def own_artifacts(self, layout: Layout) -> list[Artifact]:
        """Files that exist only because OpenCode works the way it does.

        Plugins written against its plugin API, the npm manifest they depend on,
        the helper one of them invokes, and the settings keys that make OpenCode
        look for Pegasus's skills. None of these has an agnostic form.
        """
        artifacts: list[Artifact] = [
            FileArtifact(
                id=f"own:{group}/{relative}",
                path=layout.config_dir / target / relative,
                content=path.read_bytes(),
                executable=_is_executable(path),
            )
            for group, target in sorted(ASSET_TARGETS.items())
            for path, relative in _asset_files(ASSETS / group)
        ]
        artifacts.append(_skill_registry_contract(layout))
        artifacts += [
            # Appending keeps the user's own skill paths and plugins untouched.
            ConfigKeyArtifact(
                id="own:skills-path",
                path=layout.settings_file,
                pointer="/skills/paths/-",
                value=f"./{layout.skills_dir.relative_to(layout.config_dir).as_posix()}",
            ),
            ConfigKeyArtifact(
                id="own:notifier-plugin",
                path=layout.settings_file,
                pointer="/plugin/-",
                value=NOTIFIER_PLUGIN,
            ),
            # Belongs in the policies/ content category once that exists.
            ConfigKeyArtifact(
                id="own:share",
                path=layout.settings_file,
                pointer="/share",
                value="disabled",
            ),
        ]
        return artifacts


def _is_executable(source: Path) -> bool:
    """Carry the executable bit across, because the tree already knows.

    One of these assets is a program the skill registry plugin hands to
    ``execFile``, and the rest are text somebody reads. The difference is already
    recorded, in the mode of the file itself, so reading it here is what keeps a
    single special case from being spelled out twice.
    """
    return bool(source.stat().st_mode & 0o111)


def _skill_registry_contract(layout: Layout) -> FileArtifact:
    """Answer, at install time, the two paths the skill registry plugin needs.

    This file cannot be shipped as an asset: both values are absolute paths into
    the home being installed into, so the only moment they are knowable is the
    moment the layout exists. A template with placeholders would leave the plugin
    reading instructions instead of an answer.
    """
    declared = {
        "PEGASUS_SKILL_REGISTRY_BIN": layout.config_dir
        / ASSET_TARGETS["skill-registry"]
        / SKILL_REGISTRY_BIN,
        "PEGASUS_SKILL_ROOTS": layout.skills_dir,
    }
    body = "".join(f"{key}={value}\n" for key, value in declared.items())
    return FileArtifact(
        id=f"own:{SKILL_REGISTRY_CONTRACT}",
        path=layout.config_dir / SKILL_REGISTRY_CONTRACT,
        content=body.encode("utf-8"),
        executable=False,
    )


def _asset_files(directory: Path) -> list[tuple[Path, PurePosixPath]]:
    """Every real file under an asset group, ignoring build leftovers."""
    if not directory.is_dir():
        return []
    return sorted(
        (path, PurePosixPath(path.relative_to(directory).as_posix()))
        for path in directory.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    )
