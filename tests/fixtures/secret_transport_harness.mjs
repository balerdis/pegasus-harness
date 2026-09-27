// Node harness for the OpenCode secret-transport plugin.
//
// Run under `node --experimental-strip-types` (Node 24+), same pattern as
// `engram_plugin_harness.mjs`: import the real plugin, drive its hooks, print
// one JSON object to stdout for the Python test to assert against.
//
// `PEGASUS_SECRET_TRANSPORT_CATALOG` points the plugin at the real, canonical
// catalog file (`src/pegasus/content/security/credential-transport-catalog.json`)
// instead of a rendered sidecar copy, so this test exercises the same data a
// real install would ship, unrendered placeholders and all (the plugin source
// itself has no placeholders left once `{{program_name}}` is stripped for this
// harness's own purposes — see below).

import { pathToFileURL } from "node:url"
import { readFileSync, writeFileSync, mkdtempSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"

const pluginSourcePath = process.argv[2]
const catalogPath = process.argv[3]

process.env.PEGASUS_SECRET_TRANSPORT_CATALOG = catalogPath

// Strip the one unrendered placeholder this plugin source carries
// (`{{display_name}}`, a comment only) so it imports as plain TypeScript
// under `--experimental-strip-types`, the same way a real install's render
// step would have filled it in.
const source = readFileSync(pluginSourcePath, "utf8").replace(/\{\{display_name\}\}/g, "Pegasus")
const tmpDir = mkdtempSync(join(tmpdir(), "pegasus-secret-transport-"))
const tmpPluginPath = join(tmpDir, "secret-transport.ts")
writeFileSync(tmpPluginPath, source)

const mod = await import(pathToFileURL(tmpPluginPath).href)
const plugin = await mod.SecretTransportPlugin({})

async function sendMessage(text) {
  const output = { parts: [{ type: "text", text }] }
  await plugin["chat.message"]({ sessionID: "s1" }, output)
  return output
}

async function shellEnv() {
  const output = { env: {} }
  await plugin["shell.env"]({ cwd: process.cwd() }, output)
  return output.env
}

async function toolAfter(text) {
  const output = { output: text, metadata: { output: text } }
  await plugin["tool.execute.after"]({ tool: "bash", sessionID: "s1" }, output)
  return output
}

const results = {}

// 1. Fake X-Authorization JSON header, a commit hash, and a sha256 in one message.
const commit = "a".repeat(40)
const sha256 = "b".repeat(64)
const msg1 =
  `X-Authorization: {"id":18618,"token":"${"c".repeat(64)}","clientKey":"${"d".repeat(64)}","obra_social":"12"}\n` +
  `commit ${commit}\nsha256 ${sha256}`
const tokenValue = "c".repeat(64)
const clientKeyValue = "d".repeat(64)
const out1 = await sendMessage(msg1)
const text1 = out1.parts.map((p) => p.text).join("\n")
results.header_json = {
  text: text1,
  noteAppended: text1.includes("$PEGASUS_SECRET_"),
  tokenGone: !text1.includes(tokenValue),
  clientKeyGone: !text1.includes(clientKeyValue),
  idPreserved: text1.includes("18618"),
  obraSocialPreserved: text1.includes('"obra_social":"12"'),
  commitPreserved: text1.includes(commit),
  sha256Preserved: text1.includes(sha256),
}

// 2. mysql:// URL credential
const urlPassword = "e".repeat(12)
const out2 = await sendMessage(`mysql://user:${urlPassword}@host:3306/db`)
results.url_credential = { text: out2.parts[0].text, passwordGone: !out2.parts[0].text.includes(urlPassword) }

// 3. Authorization: Bearer <JWT>
const jwt =
  "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9." +
  "eyJzdWIiOiIxMjM0NTY3ODkwIn0." +
  "f".repeat(20)
const out3 = await sendMessage(`Authorization: Bearer ${jwt}`)
results.jwt_header = { text: out3.parts[0].text, jwtGone: !out3.parts[0].text.includes(jwt) }

// 4. api-key header
const apiKeyValue = "g".repeat(24)
const out4 = await sendMessage(`api-key: ${apiKeyValue}`)
results.api_key_header = { text: out4.parts[0].text, valueGone: !out4.parts[0].text.includes(apiKeyValue) }

// 5. OpenAI-shaped key
const skKey = "sk-" + "h".repeat(24)
const out5 = await sendMessage(`use ${skKey} for the client`)
results.openai_shaped = { text: out5.parts[0].text, keyGone: !out5.parts[0].text.includes(skKey) }

// 6. GitHub token
const ghpKey = "ghp_" + "i".repeat(24)
const out6 = await sendMessage(`token is ${ghpKey}`)
results.github_token = { text: out6.parts[0].text, keyGone: !out6.parts[0].text.includes(ghpKey) }

// 7. PEM private key block
const pem = "-----BEGIN PRIVATE KEY-----\nMIIBVgIBADANBgkqhkiG9w0B\n-----END PRIVATE KEY-----"
const out7 = await sendMessage(`here is the key:\n${pem}`)
results.pem_block = { text: out7.parts[0].text, pemGone: !out7.parts[0].text.includes("MIIBVgIBADANBgkqhkiG9w0B") }

// 12. Pasted code must survive: unquoted values that are code identifiers,
// function calls, dotted paths, or shell/template variables are NOT
// substituted -- only the bare key=/key: pass is affected; quoted values,
// headers, URLs and known formats are unchanged.
const codeSnippets = {
  const_token_call: "const token = getToken()",
  bare_reassignment: "token = accessToken",
  this_password: "this.password = password",
  dotted_env_path: "password: process.env.DB_PASS",
  template_var: "api_key=${API_KEY}",
  percent_template: "secret: %(secret)s",
}
results.code_survival = {}
for (const [name, snippet] of Object.entries(codeSnippets)) {
  const out = await sendMessage(snippet)
  results.code_survival[name] = { text: out.parts[0].text, unchanged: out.parts[0].text.startsWith(snippet) }
}

// 13. Still detected despite the new skip rules.
const dbPasswordValue = "s3cr3tP4ss"
const outDbPassword = await sendMessage(`DB_PASSWORD=${dbPasswordValue}`)
results.db_password_with_digits = {
  text: outDbPassword.parts[0].text,
  valueGone: !outDbPassword.parts[0].text.includes(dbPasswordValue),
}

const quotedPlainWord = "plainword"
const outQuotedPlain = await sendMessage(`password: "${quotedPlainWord}"`)
results.quoted_plain_word = {
  text: outQuotedPlain.parts[0].text,
  valueGone: !outQuotedPlain.parts[0].text.includes(quotedPlainWord),
}

// 8. Explicit <private>NAME=value</private>
const explicitValue = "j".repeat(16)
const out8 = await sendMessage(`<private>DB_PASSWORD=${explicitValue}</private>`)
results.explicit_named = {
  text: out8.parts[0].text,
  valueGone: !out8.parts[0].text.includes(explicitValue),
  usesDbPasswordName: out8.parts[0].text.includes("$PEGASUS_SECRET_DB_PASSWORD"),
}

// 9. Same value twice -> same variable
// A digit is required so this value is not skipped by the new
// `bare_identifier_no_digit` unquoted-code rule (an all-letters bare value
// reads as another variable name, not a literal secret -- see the catalog's
// own `skip_unquoted_if`).
const repeated = "k1".repeat(10)
const out9a = await sendMessage(`token: ${repeated}`)
const out9b = await sendMessage(`token: ${repeated}`)
const varA = out9a.parts[0].text.match(/\$PEGASUS_SECRET_\w+/)?.[0]
const varB = out9b.parts[0].text.match(/\$PEGASUS_SECRET_\w+/)?.[0]
results.same_value_same_variable = { varA, varB, same: varA === varB && !!varA }

// 10. shell.env exposes every registered value
const env = await shellEnv()
results.shell_env = env

// 11. tool.execute.after redacts an echoed registered value (from case 9)
const toolOut = await toolAfter(`echoing back: ${repeated}`)
results.tool_execute_after = {
  output: toolOut.output,
  metadataOutput: toolOut.metadata.output,
  valueGone: !toolOut.output.includes(repeated) && !toolOut.metadata.output.includes(repeated),
}

console.log(JSON.stringify(results))
