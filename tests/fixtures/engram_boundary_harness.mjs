// Node harness for engram.ts's size and ordering behaviour, with the real
// secret-transport plugin loaded. Prints, as JSON, what each scenario POSTed.
//
// Usage: node --experimental-strip-types engram_boundary_harness.mjs \
//   <engram.ts> <secret-transport.ts> <catalog.json>

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
const proxyOptions = []
globalThis.fetch = async (url, opts) => {
  proxyOptions.push(opts?.proxy)
  if (url.endsWith("/health")) return { ok: true }
  if (opts?.method === "POST") posts.push({ url, body: JSON.parse(opts.body) })
  return { ok: true, json: async () => ({ ok: true }) }
}

const [engramPath, transportPath, catalogPath] = process.argv.slice(2)
process.env.PEGASUS_SECRET_TRANSPORT_CATALOG = catalogPath
const dir = mkdtempSync(join(tmpdir(), "pegasus-engram-boundary-"))
const tmpTransport = join(dir, "secret-transport.ts")
writeFileSync(tmpTransport, readFileSync(transportPath, "utf8").replace(/\{\{display_name\}\}/g, "Pegasus"))
await import(pathToFileURL(tmpTransport).href)
const plugin = await (await import(pathToFileURL(engramPath).href)).Engram({ directory: process.cwd() })
await plugin.event({
  event: { type: "session.created", properties: { info: { id: "root1", parentID: undefined, title: "root" } } },
})

const secret = "ghp_" + "a1B2c3D4e5".repeat(4)
const prompt = (text) => plugin["chat.message"]({ sessionID: "root1" }, { parts: [{ type: "text", text }], message: {} })
const passive = (text) =>
  plugin["tool.execute.after"]({ tool: "task", sessionID: "root1", callID: "c", args: {} }, { title: "s", output: text, metadata: {} })
const last = (suffix) => posts.filter((p) => p.url.endsWith(suffix)).map((p) => p.body.content)

const straddling = []
for (let pad = 1990; pad < 2000; pad++) {
  await prompt("y".repeat(pad) + " " + secret)
}
straddling.push(...last("/prompts"))

posts.length = 0
await passive("## Key Learnings\n" + "z ".repeat(140000) + secret)
const oversizedPassive = last("/observations/passive").length

// Fresh secrets, never registered by an earlier scenario, so the registry's
// known-value masking cannot hide a skipped detection pass.
let freshCounter = 0
const freshSecret = () => "ghp_" + String(++freshCounter).padStart(2, "0") + "Qw7Zk3Xv9L".repeat(3) + "Rt"

posts.length = 0
const oversizedSecret = freshSecret()
await prompt(oversizedSecret + " " + "z ".repeat(200000))
const oversizedPrompt = last("/prompts")

// Above the cap, padded with multibyte characters so the cut lands inside one
// at every alignment: the cut must not push the text back above the cap.
const multibyte = {}
for (const [name, ch] of [["cjk", "\u3042"], ["emoji", "\u{1F600}"]]) {
  multibyte[name] = []
  for (let pad = 0; pad < 4; pad++) {
    posts.length = 0
    const fresh = freshSecret()
    await prompt(fresh + " " + "x".repeat(pad) + ch.repeat(100000))
    multibyte[name].push({ pad, secret: fresh, posted: last("/prompts") })
  }
}

posts.length = 0
const started = Date.now()
await prompt("<private>".repeat(28000))
const unclosedMs = Date.now() - started

console.log(
  JSON.stringify({ straddling, oversizedPassive, oversizedPrompt, oversizedSecret, multibyte, unclosedMs, proxyOptions: [...new Set(proxyOptions)] }),
)
