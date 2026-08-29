"""Where OpenCode keeps each kind of artifact.

Pure path arithmetic. The registry builds this against a home directory that
does not exist, so touching the filesystem here would make registration depend
on the state of the machine.
"""
from __future__ import annotations

from pathlib import Path

from pegasus.core.types import Environment, Layout

SETTINGS = "opencode.json"
SYSTEM_PROMPT = "pegasus-AGENTS.md"
MODELS_CATALOG = "models.json"
CREDENTIALS = "auth.json"


def config_dir(environment: Environment) -> Path:
    """OpenCode's configuration root, honouring XDG_CONFIG_HOME when it is absolute."""
    configured = environment.variables.get("XDG_CONFIG_HOME", "").strip()
    if configured and Path(configured).is_absolute():
        return Path(configured) / "opencode"
    return environment.home / ".config" / "opencode"


def models_catalog_file(environment: Environment) -> Path:
    """Where the CLI keeps what it knows about providers and models.

    Honours XDG_CACHE_HOME the same way `config_dir` honours XDG_CONFIG_HOME:
    only an absolute setting counts, because a relative one would name a
    directory whose meaning depends on where the process was started.
    """
    configured = environment.variables.get("XDG_CACHE_HOME", "").strip()
    if configured and Path(configured).is_absolute():
        return Path(configured) / "opencode" / MODELS_CATALOG
    return environment.home / ".cache" / "opencode" / MODELS_CATALOG


def credentials_file(environment: Environment) -> Path:
    """Where the CLI keeps which providers have a session -- key names only.

    Same XDG discipline as `models_catalog_file`, honouring XDG_DATA_HOME.
    """
    configured = environment.variables.get("XDG_DATA_HOME", "").strip()
    if configured and Path(configured).is_absolute():
        return Path(configured) / "opencode" / CREDENTIALS
    return environment.home / ".local" / "share" / "opencode" / CREDENTIALS


def build(environment: Environment) -> Layout:
    root = config_dir(environment)
    return Layout(
        config_dir=root,
        settings_file=root / SETTINGS,
        skills_dir=root / "skills",
        # OpenCode declara sus subagentes dentro de opencode.json, no como
        # archivos en un directorio, así que no hay ancla que declarar.
        agents_dir=None,
        commands_dir=root / "commands",
        prompts_dir=root / "prompts",
        plugins_dir=root / "plugins",
        # Not the user's own AGENTS.md: Pegasus ships its own file and points
        # OpenCode at it through the instructions list, so nothing collides.
        system_prompt_file=root / SYSTEM_PROMPT,
        # Pegasus's own directory, not OpenCode's -- `None` when this frame has
        # no answer for it, the same as every other environment-derived fact.
        dependencies_dir=(environment.data_dir / "mcp") if environment.data_dir is not None else None,
    )
