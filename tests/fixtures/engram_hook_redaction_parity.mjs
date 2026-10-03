// Prints, for each input string read from stdin as a JSON array, what the
// OpenCode secret-transport plugin's process-wide `redact` returns for it.
// Run under `node --experimental-strip-types`, argv: <plugin.ts> <catalog.json>.
// Every input is redacted in a fresh module instance, like a hook process
// (one process, an empty registry per input), so placeholder names line up.
import { pathToFileURL } from "node:url"
import { readFileSync, writeFileSync, mkdtempSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"

const [pluginPath, catalogPath] = process.argv.slice(2)
process.env.PEGASUS_SECRET_TRANSPORT_CATALOG = catalogPath
const source = readFileSync(pluginPath, "utf8").replace(/\{\{display_name\}\}/g, "Pegasus")
const dir = mkdtempSync(join(tmpdir(), "pegasus-hook-parity-"))
const inputs = JSON.parse(readFileSync(0, "utf8"))
const outputs = []
for (let i = 0; i < inputs.length; i++) {
  const file = join(dir, `secret-transport-${i}.ts`)
  writeFileSync(file, source)
  await import(pathToFileURL(file).href)
  outputs.push(globalThis.__CREDENTIAL_TRANSPORT_V1__.redact(inputs[i]))
}
process.stdout.write(JSON.stringify(outputs))
