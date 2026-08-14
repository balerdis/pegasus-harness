"""What this adapter delivers for OpenCode.

The manifest is not OpenCode's feature list: it is the list of capabilities this
adapter actually implements today. The registry refuses to register an adapter
that claims more than it implements, so a capability stays False until its
render and the content it needs both exist.
"""
from __future__ import annotations

from pegasus.core.types import CapabilityManifest

CLI_ID = "opencode"
DISPLAY_NAME = "OpenCode"

MANIFEST = CapabilityManifest(
    cli_id=CLI_ID,
    skills=True,
    system_prompt=True,
    slash_commands=True,
    sub_agents=True,
    # OpenCode reads an agent's prompt from its own file, referenced with
    # {file:...}. A CLI that embeds the prompt in the agent declaration would
    # deny this and receive one artifact instead of two.
    prompts=True,
    # OpenCode does support MCP, but the mcp/ content category does not exist
    # yet: the servers still live in manifests/release-contract.json. Flips to
    # True together with that category and render_mcp.
    mcp=False,
    # Model assignment arrives with the configuration menu.
    per_agent_model=False,
)
