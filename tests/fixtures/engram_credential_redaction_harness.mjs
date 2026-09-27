// Node harness proving engram.ts's own POST bodies (`/prompts` and
// `/observations/passive`) never carry a fake credential value once the
// secret-transport plugin's redaction global is present -- in either import
// order, since the global is set at module top level (when OpenCode loads
// the plugin), not inside a hook, so it exists before any hook of either
// plugin ever fires.
//
// Usage: node --experimental-strip-types engram_credential_redaction_harness.mjs \
//   <engram.ts path> <secret-transport.ts path> <catalog.json path> <order: secret-first|engram-first>

import { readFileSync, writeFileSync, mkdtempSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { pathToFileURL } from "node:url"

globalThis.Bun = {
  which: () => null,
  spawnSync: () => ({ exitCode: 1, stdout: Buffer.from("") }),
  spawn: () => ({}),
  file: () => ({ exists: async () => false }),
}

const posts = []
globalThis.fetch = async (url, opts) => {
  if (url.endsWith("/health")) return { ok: true }
  if (opts?.method === "POST") posts.push({ url, body: JSON.parse(opts.body) })
  return { ok: true, json: async () => ({ ok: true }) }
}

const [engramPath, secretTransportPath, catalogPath, order] = process.argv.slice(2)
process.env.PEGASUS_SECRET_TRANSPORT_CATALOG = catalogPath

const tmpDir = mkdtempSync(join(tmpdir(), "pegasus-credential-redaction-"))
const secretTransportSource = readFileSync(secretTransportPath, "utf8").replace(/\{\{display_name\}\}/g, "Pegasus")
const tmpSecretTransportPath = join(tmpDir, "secret-transport.ts")
writeFileSync(tmpSecretTransportPath, secretTransportSource)

async function importEngram() {
  return import(pathToFileURL(engramPath).href)
}
async function importSecretTransport() {
  return import(pathToFileURL(tmpSecretTransportPath).href)
}

let engramMod
if (order === "secret-first") {
  await importSecretTransport()
  engramMod = await importEngram()
} else {
  engramMod = await importEngram()
  await importSecretTransport()
}

const ctx = { directory: process.cwd() }
const plugin = await engramMod.Engram(ctx)

await plugin.event({
  event: { type: "session.created", properties: { info: { id: "root1", parentID: undefined, title: "root" } } },
})

const fakeToken = "z".repeat(48)
const message = `here is my token: token=${fakeToken} please use it`

await plugin["chat.message"](
  { sessionID: "root1" },
  { parts: [{ type: "text", text: message }], message: {} },
)

const passiveText = `## Key Learnings\n1. This finding mentions token=${fakeToken} inline, which must not survive.\n`
await plugin["tool.execute.after"](
  { tool: "task", sessionID: "root1", callID: "c1", args: {} },
  { title: "sub", output: passiveText, metadata: {} },
)

console.log(
  JSON.stringify({
    order,
    posts: posts.map((p) => ({ url: p.url, body: p.body })),
    fakeToken,
  }),
)
