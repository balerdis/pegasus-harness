import type { Plugin } from "@opencode-ai/plugin"

// The MCP provides the integration; this local plugin is intentionally inert.
const EngramPlugin: Plugin = async () => ({})

export default EngramPlugin
