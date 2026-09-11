"""The OpenCode adapter.

Implements exactly the capabilities its manifest declares, and nothing else: a
render method for an undeclared capability is a phantom capability and the
registry rejects it.
"""
from __future__ import annotations

import shutil
from importlib.resources import files as _package_files
from pathlib import Path, PurePosixPath
from typing import Any

from pegasus.adapters.opencode import layout as layout_module
from pegasus.adapters.opencode import manifest as manifest_module
from pegasus.adapters.opencode import models as models_module
from pegasus.adapters.opencode import naming
from pegasus.adapters.opencode import render
from pegasus.core import placeholders
from pegasus.core.content import Agent, Command, Mcp, Skill, SystemPrompt
from pegasus.core.identity import Identity
from pegasus.core.model_catalog import ModelCatalog
from pegasus.core.types import (
    Artifact,
    CapabilityManifest,
    ConfigKeyArtifact,
    Detection,
    Environment,
    FileArtifact,
    Layout,
    ModelAssignment,
    SupportTier,
)

#: Whatever `importlib.resources` hands back: a real `pathlib.Path` when the
#: package sits on a filesystem, a `zipfile.Path` when it is read straight out
#: of an archive (built with `zipapp`, for instance). Both answer `iterdir`,
#: `is_dir`, `is_file`, `read_bytes` and `joinpath`; neither call is spelled
#: here in a way that only one of the two could answer -- `stat`, `resolve`,
#: `relative_to`, `parent`, `glob` and `rglob` exist on the filesystem one and
#: not (reliably) on the other, so this module never reaches for them. See
#: `pegasus.core.content`, which hit the identical constraint first.
AssetNode = Any

ASSETS: AssetNode = _package_files(__package__) / "assets"
BINARY = "opencode"

ASSET_TARGETS: dict[str, PurePosixPath] = {
    "plugins": PurePosixPath("plugins"),
    "notifier": PurePosixPath("notifier"),
    "registry": PurePosixPath("registry"),
    # The skill registry helper lives under a subtree of its own so it never
    # sits next to files OpenCode manages itself. Named here with no product
    # prefix at all: `_skill_registry_target` below prepends this running
    # distribution's own `program_name`, so the subtree never carries a brand
    # that is not the one actually installed.
    "skill-registry": PurePosixPath("skill-registry"),
}


class MissingAssetGroupError(Exception):
    """A group named in `ASSET_TARGETS` has no matching directory at all.

    `ASSET_TARGETS` is the one place this module states which asset groups
    exist; nothing else ever adds or removes a name from it. So if a name here
    has no directory under `assets/` at all, only a packaging mistake explains
    it -- a rename, a delete, a typo between the module and the tree on disk --
    the exact same shape of self-contradiction `render.py` refuses for an
    unmapped `Distribution` member and `registry.py` refuses for a declared but
    unimplemented capability.

    This is deliberately not raised for a directory that exists but is empty.
    An asset group can legitimately ship with nothing in it -- a plugin
    retired for a release, a notifier not yet written -- and an empty
    directory earns exactly zero artifacts, which `_asset_files` already
    reports correctly on its own. Only the *absence* of the directory itself
    is treated as a mistake nothing could have intended.
    """


def _missing_asset_groups(assets_root: AssetNode, targets: dict[str, PurePosixPath]) -> list[str]:
    return sorted(group for group in targets if not (assets_root / group).is_dir())


def _check_asset_groups(assets_root: AssetNode, targets: dict[str, PurePosixPath]) -> None:
    missing = _missing_asset_groups(assets_root, targets)
    if missing:
        raise MissingAssetGroupError(
            "declared asset group(s) missing from the package: " + ", ".join(missing)
        )


# Runs once, at import time, against this package's own bundled assets --
# never against a user's environment, which does not exist yet at import.
# `ASSETS` and `ASSET_TARGETS` are both fixed the moment this module is
# defined, so there is nothing to gain by waiting for an adapter to be
# registered, let alone for an install to run, before refusing: the failure
# is exactly as deterministic here as `render.py`'s own import-time check of
# `Distribution` against `MCP_VALUE`, for the same reason -- it depends on
# nothing but the shape of the package itself.
_check_asset_groups(ASSETS, ASSET_TARGETS)

# The skill registry plugin reads its contract from this file, at the root of
# OpenCode's configuration directory. Both the plugin and `_skill_registry_
# contract` below derive its name the same way -- `f"{program_name}-skill-
# registry.env"` -- so nothing here restates a name the plugin also states;
# `SkillRegistryContractTest` holds the two derivations together by reading
# the plugin's own rendered content instead of a shared literal.
def _skill_registry_bin(identity: Identity) -> str:
    return f"{identity.program_name}-skill-registry"


def _skill_registry_contract_name(identity: Identity) -> str:
    return f"{identity.program_name}-skill-registry.env"


def _skill_registry_target(identity: Identity) -> PurePosixPath:
    return PurePosixPath(identity.program_name) / ASSET_TARGETS["skill-registry"]


#: The physical, on-disk source filenames that ship as programs -- fixed
#: forever, since one repository tree serves every distribution, and never
#: what a distribution's own installed copy is named (see `_RENAMED_ASSETS`).
#: Everything else this package carries is text. Kept as a declaration
#: because the executable bit cannot be read from inside an archive; a test
#: holds it to what the tree on disk actually says.
EXECUTABLE_ASSETS = frozenset({"skill-registry"})

#: Bundled source assets whose installed name is not their source name.
#: Keyed by the bare source filename `_asset_files` hands back -- never by
#: group, since two groups never collide on one bare name -- and mapping to
#: the callable that derives this distribution's own installed name for it.
#: Everything not listed here installs under the name it ships with.
_RENAMED_ASSETS: dict[str, Any] = {
    "skill-registry": _skill_registry_bin,
    "skill_registry.py": lambda identity: f"{naming.module_name(identity)}_skill_registry.py",
    "skill-registry.ts": lambda identity: f"{identity.program_name}-skill-registry.ts",
    "orchestrator-notifier.ts": lambda identity: f"{identity.program_name}-orchestrator-notifier.ts",
    "zellij-state.ts": lambda identity: f"{identity.program_name}-zellij-state.ts",
    "apply-patch-scope.ts": lambda identity: f"{identity.program_name}-apply-patch-scope.ts",
}


def _installed_relative(relative: PurePosixPath, identity: Identity) -> PurePosixPath:
    """The name this one bundled asset is installed under.

    Distinct from the name it ships with in the package: the source tree
    carries one physical file per asset, forever, while the installed name
    is this distribution's own -- see `_RENAMED_ASSETS`.
    """
    rename = _RENAMED_ASSETS.get(relative.name)
    if rename is None:
        return relative
    return relative.parent / rename(identity)


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

    def render_agent(self, layout: Layout, agent: Agent, assignment: ModelAssignment | None = None) -> list[Artifact]:
        return render.agent(layout, agent, assignment)

    def render_prompt(self, layout: Layout, agent: Agent) -> list[Artifact]:
        return render.prompt(layout, agent)

    def render_command(self, layout: Layout, command: Command, orchestrator_name: str) -> list[Artifact]:
        return render.command(layout, command, orchestrator_name)

    def render_system_prompt(self, layout: Layout, system_prompt: SystemPrompt, identity: Identity) -> list[Artifact]:
        return render.system_prompt(layout, system_prompt, identity)

    def render_mcp(self, layout: Layout, mcp: Mcp) -> list[Artifact]:
        return render.mcp(layout, mcp)

    # --- Models ---

    def model_catalog(self, environment: Environment) -> ModelCatalog:
        return models_module.read(environment)

    # --- What this adapter ships on its own ---

    def own_artifacts(self, layout: Layout, orchestrator_name: str, identity: Identity) -> list[Artifact]:
        """Files that exist only because OpenCode works the way it does.

        Plugins written against its plugin API, the npm manifest they depend on,
        the helper one of them invokes, and the settings keys that make OpenCode
        look for Pegasus's skills. None of these has an agnostic form.

        `orchestrator_name` is filled into every bundled asset uniformly through
        `_rendered_asset` -- one rule for all of them, never a check for which
        file happens to need it -- so a plugin naming the orchestrator (the
        notifier) asks for it the same way a skill or command body would.

        `identity` (threaded through `core.catalog` from `Runtime.identity`)
        is consulted the same way: every fixed "pegasus-*" name this method
        used to ship is now derived from it -- the skill-registry subtree and
        its binary and module, the four local plugin files and the contract
        between the first and one of the second, and the notifier's own npm
        package name -- through `_installed_relative`, `_skill_registry_
        target` and the `program_name`/`display_name`/`program_module_name`/
        `program_pascal_name`/`program_npm_name` placeholders `_asset_facts`
        answers. Only the
        wire-format env var *names* (`PEGASUS_SKILL_REGISTRY_BIN`,
        `PEGASUS_SKILL_ROOTS`) and the external notifier's own package id
        stay fixed, by design -- see `core.identity` and this repository's
        own product-identity rules for which strings are wire plumbing and
        which are brand.
        """
        facts = _asset_facts(layout, orchestrator_name, identity)
        artifacts: list[Artifact] = [
            FileArtifact(
                id=f"own:{group}/{_installed_relative(relative, identity)}",
                path=layout.config_dir
                / (_skill_registry_target(identity) if group == "skill-registry" else target)
                / _installed_relative(relative, identity),
                content=_rendered_asset(path.read_bytes(), facts),
                executable=_is_executable(path),
            )
            for group, target in sorted(ASSET_TARGETS.items())
            for path, relative in _asset_files(ASSETS / group)
        ]
        artifacts.append(_skill_registry_contract(layout, identity))
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


def _asset_facts(layout: Layout, orchestrator_name: str, identity: Identity) -> dict[str, str]:
    """What a bundled asset may ask this adapter to fill in.

    Extends `render.facts`, which answers `skills_root` for a content body,
    rather than restating that rule here: `own_artifacts` adds `orchestrator`
    plus everything a bundled asset needs from `identity` -- `program_name`
    and `display_name` as `Identity` states them, and `program_module_name`/
    `program_pascal_name`/`program_npm_name` as `naming` reshapes them for a
    context neither field can satisfy as-is. Derived and not copied, so
    changing how a layout answers `skills_root` cannot leave assets answering
    it the old way.
    """
    return {
        **render.facts(layout),
        "orchestrator": orchestrator_name,
        "program_name": identity.program_name,
        "display_name": identity.display_name,
        "program_module_name": naming.module_name(identity),
        "program_pascal_name": naming.pascal_name(identity),
        "program_npm_name": naming.npm_name(identity),
    }


def _rendered_asset(raw: bytes, facts: dict[str, str]) -> bytes:
    """Fill a bundled asset's placeholders, applied uniformly to every one of them.

    Not a filename special case: every asset in `own_artifacts` passes through
    here, so "this one plugin names the orchestrator" is nothing but an asset
    that happens to use the vocabulary, the same as any content body would.

    An asset that does not decode as UTF-8 text is shipped back unchanged.
    Every bundled asset today is text, but substitution is a text operation,
    and silently running it over an eventual binary asset would be an obscure
    way to corrupt it -- refusing that quietly is the deliberate choice, not
    an oversight.
    """
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw
    try:
        filled = placeholders.fill(text, facts)
    except placeholders.Unanswered as missing:
        raise render.RenderError(
            f"bundled asset: this layout has no {missing.name}, so it cannot be filled"
        ) from None
    return filled.encode("utf-8")


def _is_executable(source: AssetNode) -> bool:
    """Whether this asset is a program rather than text somebody reads.

    Answered from `EXECUTABLE_ASSETS` rather than from the file's own mode,
    because the mode is not always there to read: a zip-backed `Traversable`
    exposes no POSIX bits at all, and reaching past it into the archive's own
    entry would mean depending on internals this module avoids on principle.
    Asking the file on disk and asking a name in a zip would be two answers to
    one question, and they could disagree without anything saying so.

    Declaring it is not a free lunch either: an executable asset added and not
    declared here would ship without its bit, silently. That is what
    `test_opencode_adapter` closes, by comparing this set against the modes the
    package's own tree really carries — the one place the question can still be
    asked directly.
    """
    return source.name in EXECUTABLE_ASSETS


def _skill_registry_contract(layout: Layout, identity: Identity) -> FileArtifact:
    """Answer, at install time, the two paths the skill registry plugin needs.

    This file cannot be shipped as an asset: both values are absolute paths into
    the home being installed into, so the only moment they are knowable is the
    moment the layout exists. A template with placeholders would leave the plugin
    reading instructions instead of an answer.
    """
    declared = {
        "PEGASUS_SKILL_REGISTRY_BIN": layout.config_dir
        / _skill_registry_target(identity)
        / _skill_registry_bin(identity),
        "PEGASUS_SKILL_ROOTS": layout.skills_dir,
    }
    body = "".join(f"{key}={value}\n" for key, value in declared.items())
    contract_name = _skill_registry_contract_name(identity)
    return FileArtifact(
        id=f"own:{contract_name}",
        path=layout.config_dir / contract_name,
        content=body.encode("utf-8"),
        executable=False,
    )


def _asset_files(directory: AssetNode) -> list[tuple[AssetNode, PurePosixPath]]:
    """Every real file under an asset group, ignoring build leftovers.

    Written as an explicit walk over `iterdir` rather than `Path.rglob`, which
    a zip-backed `Traversable` does not reliably provide, mirroring the walk
    `pegasus.core.content` already had to write for the identical reason. A
    missing declared group never reaches here silently any more -- that is
    refused once, at import time, by `_check_asset_groups` -- so the `is_dir`
    guard below only ever matters for a directory that legitimately does not
    exist yet, such as a nested subdirectory this function recurses into.
    """
    if not directory.is_dir():
        return []
    found: list[tuple[AssetNode, PurePosixPath]] = []
    for child in directory.iterdir():
        if child.is_dir():
            if child.name == "__pycache__":
                continue
            found.extend(
                (path, PurePosixPath(child.name) / relative) for path, relative in _asset_files(child)
            )
        elif child.is_file():
            found.append((child, PurePosixPath(child.name)))
    return sorted(found, key=lambda pair: pair[1].as_posix())
