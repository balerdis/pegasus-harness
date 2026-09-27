// Node harness for the OpenCode Engram plugin's passive-capture trigger.
//
// Run under `node --experimental-strip-types` (Node 24+) so the plugin's
// TypeScript type annotations are erased without a build step. The plugin
// itself is written against the Bun runtime (`Bun.which`, `Bun.spawnSync`,
// `Bun.spawn`, `Bun.file`), so this harness stubs a minimal `Bun` global
// before importing it, and stubs `fetch` to record every call instead of
// reaching a real engram server.
//
// Prints one JSON object to stdout: { cases: [{ tool, posted, body }] }.
// The Python test (`tests/test_engram_memory_scope.py`,
// `EngramPluginPassiveCaptureNodeTest`) parses this and makes the assertions
// — this file only drives the plugin and reports what happened.

globalThis.Bun = {
  which: () => null,
  spawnSync: () => ({ exitCode: 1, stdout: Buffer.from("") }),
  spawn: () => ({}),
  file: () => ({ exists: async () => false }),
}

const posts = []
globalThis.fetch = async (url, opts) => {
  if (url.endsWith("/health")) return { ok: true }
  if (opts?.method === "POST" && url.includes("/observations/passive")) {
    posts.push({ url, body: JSON.parse(opts.body) })
  }
  return { ok: true, json: async () => ({ ok: true }) }
}

import { pathToFileURL } from "node:url"

const pluginPath = process.argv[2]
const mod = await import(pathToFileURL(pluginPath).href)
const ctx = { directory: process.cwd() }
const plugin = await mod.Engram(ctx)

// Register a root (non-sub-agent) session, same as OpenCode would on
// `session.created` for the conversation the launched sub-agent runs under.
await plugin.event({
  event: {
    type: "session.created",
    properties: { info: { id: "root1", parentID: undefined, title: "root" } },
  },
})

// Register a sub-agent session (parentID set), same as OpenCode would for a
// Task()-launched agent that itself launches a further sub-agent (a
// sub-sub-agent). The passive capture must not fire when the session that
// ran the tool is itself one of these -- see `subAgentSessions.has` in
// `tool.execute.after`.
await plugin.event({
  event: {
    type: "session.created",
    properties: { info: { id: "sub1", parentID: "root1", title: "sub1 (subagent)" } },
  },
})

const learningsOutput =
  "## Key Learnings\n" +
  "1. This is a durable finding worth keeping across sessions.\n" +
  "2. Another self-contained item that clears the length floor.\n"

const cases = []

async function run(tool, outputText, sessionID = "root1", label = tool) {
  posts.length = 0
  await plugin["tool.execute.after"](
    { tool, sessionID, callID: "c-" + label, args: {} },
    { title: "sub", output: outputText, metadata: {} }
  )
  cases.push({
    tool: label,
    posted: posts.length > 0,
    body: posts.length > 0 ? posts[0].body : null,
  })
}

await run("task", learningsOutput)
await run("Task", learningsOutput)
await run("subagent", learningsOutput)
await run("read", learningsOutput)
await run("bash", learningsOutput)
// The same "task" tool, completing under a sub-agent session (`sub1`)
// instead of the root one -- must not post at all.
await run("task", learningsOutput, "sub1", "task-from-subagent-session")

console.log(JSON.stringify({ cases }))
