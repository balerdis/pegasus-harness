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

// 14. 7.3.1 real case: the fake curl that motivated the change. `clientKey`
// (7 chars) and `apiKey` sit next to sensitive keys and must be redacted
// even though they are shorter than the old 8-char minimum, and the
// `X-Aco-Joven-Signature` header value must be redacted by header name even
// though it is bare hex and the header is not a known Authorization/X-Api-Key
// name. Everything else in the curl must survive untouched.
const clientKeyValue7 = "m".repeat(7)
const apiKeyValue8 = "n".repeat(8)
const signatureValue = "0123456789abcdef".repeat(4) // fake 64-hex
const requestId = "tdOGfakeRequestId0000000"
const curl =
  `curl --location --request GET 'http://backend-service.localhost.com/api/v1/items/?page=0&alfabeta=1&aco=true' \\\n` +
  `--header 'X-Aco-Joven-Context: {"version":"1","key_id":"tenant-a-v1","eligible":false,"issued_at":1790370617,"request_id":"${requestId}"}' \\\n` +
  `--header 'X-Aco-Joven-Signature: ${signatureValue}' \\\n` +
  `--header 'X-Authorization: {"clientKey":"${clientKeyValue7}","apiKey":"${apiKeyValue8}","obra_social":"12"}'`
const outCurl = await sendMessage(curl)
const textCurl = outCurl.parts.map((p) => p.text).join("\n")
results.real_case_curl = {
  text: textCurl,
  clientKeyGone: !textCurl.includes(clientKeyValue7),
  apiKeyGone: !textCurl.includes(apiKeyValue8),
  signatureGone: !textCurl.includes(signatureValue),
  versionPreserved: textCurl.includes('"version":"1"'),
  keyIdPreserved: textCurl.includes("tenant-a-v1"),
  eligiblePreserved: textCurl.includes('"eligible":false'),
  issuedAtPreserved: textCurl.includes("1790370617"),
  requestIdPreserved: textCurl.includes(requestId),
  obraSocialPreserved: textCurl.includes('"obra_social":"12"'),
  urlPreserved: textCurl.includes("http://backend-service.localhost.com/api/v1/items/?page=0&alfabeta=1&aco=true"),
  headerNamesPreserved:
    textCurl.includes("X-Aco-Joven-Context:") &&
    textCurl.includes("X-Aco-Joven-Signature:") &&
    textCurl.includes("X-Authorization:"),
  usesSignatureVarName: textCurl.includes("$PEGASUS_SECRET_X_ACO_JOVEN_SIGNATURE"),
}

// 15. Filler non-values next to sensitive keys are never replaced, whatever
// their length, and case-insensitively as whole values.
const fillerCases = {
  token_null: `"token": null`,
  password_false: `password: false`,
  secret_todo: `"secret": "TODO"`,
  api_key_xxx: `api_key: xxx`,
  password_stars: `"password": "****"`,
}
results.filler_survival = {}
for (const [name, snippet] of Object.entries(fillerCases)) {
  const out = await sendMessage(snippet)
  const text = out.parts[0].text
  results.filler_survival[name] = { text, unchanged: text.startsWith(snippet) }
}

// 16. Look-alike keys and headers that must never be mistaken for secrets.
const lookalikeCases = {
  token_count: "token_count: 1500",
  max_tokens: "MAX_TOKENS=4096",
  tokenizer: `"tokenizer": "cl100k_base"`,
  content_type: "Content-Type: application/json",
  request_id_header: "X-Request-Id: abc123",
  api_version_header: "X-Api-Version: 2",
  forwarded_for_header: "X-Forwarded-For: 10.0.0.1",
  bare_commit: "a".repeat(40),
  bare_sha256: "b".repeat(64),
  const_token: "const token = getToken()",
  signature_version_header: "X-Signature-Version: 2",
  api_key_version_header: "X-Api-Key-Version: 2",
}
results.lookalike_survival = {}
for (const [name, snippet] of Object.entries(lookalikeCases)) {
  const out = await sendMessage(snippet)
  const text = out.parts[0].text
  results.lookalike_survival[name] = { text, unchanged: text.startsWith(snippet) }
}

// 17. 7.3.1 follow-up (blocking): a header suffix must tolerate one
// trailing `-<digits>` segment, the exact shape GitHub's own webhook
// signature header uses (`X-Hub-Signature-256`), and a hypothetical
// `X-Signature-512`. A header that merely happens to end in digits after an
// unrelated word (`X-Signature-Version`, `X-Api-Key-Version`) must still
// survive -- covered above in `lookalike_survival`.
const hubSignatureValue = "sha256=" + "c".repeat(64)
const outHub = await sendMessage(`X-Hub-Signature-256: ${hubSignatureValue}`)
results.hub_signature_256 = {
  text: outHub.parts[0].text,
  valueGone: !outHub.parts[0].text.includes(hubSignatureValue),
  usesDerivedName: outHub.parts[0].text.includes("$PEGASUS_SECRET_X_HUB_SIGNATURE_256"),
}

const signature512Value = "5".repeat(64)
const outSig512 = await sendMessage(`X-Signature-512: ${signature512Value}`)
results.signature_512 = {
  text: outSig512.parts[0].text,
  valueGone: !outSig512.parts[0].text.includes(signature512Value),
  usesDerivedName: outSig512.parts[0].text.includes("$PEGASUS_SECRET_X_SIGNATURE_512"),
}

// 18. A rejected, unrelated leading `key:`/`key=` must never swallow a real
// sensitive `key=value` pair that sits right after it -- a review-found
// regression in the bare unquoted pass.
// A digit is required so these fake values are not skipped by the
// pre-existing `bare_identifier_no_digit` unquoted-code rule (an all-letters
// bare value reads as another identifier, not a literal secret) -- same
// reasoning as the `same_value_same_variable` case above.
const notePasswordValue = "p4ss".repeat(3)
const outNotePassword = await sendMessage(`note: password=${notePasswordValue}`)
results.unrelated_prefix_note = {
  text: outNotePassword.parts[0].text,
  valueGone: !outNotePassword.parts[0].text.includes(notePasswordValue),
}

const contentTypePasswordValue = "q1w2".repeat(3)
const outContentTypePassword = await sendMessage(`Content-Type: password=${contentTypePasswordValue}`)
results.unrelated_prefix_content_type = {
  text: outContentTypePassword.parts[0].text,
  valueGone: !outContentTypePassword.parts[0].text.includes(contentTypePasswordValue),
}

const cookieTokenValue = "r9".repeat(6)
const outCookie = await sendMessage(`Set-Cookie: token=${cookieTokenValue}; Path=/`)
const cookieText = outCookie.parts[0].text
results.set_cookie_token = {
  text: cookieText,
  valueGone: !cookieText.includes(cookieTokenValue),
  pathPreserved: cookieText.includes("Path=/"),
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

// 19. 7.3.1 follow-up: a URL query string must not lose data. `&`/`?` are
// excluded from `key_context.unquoted_value_pattern` alongside the
// pre-existing `;` exclusion, so the bare unquoted pass stops at the next
// query separator instead of swallowing the rest of the URL as the value.
const urlQueryTokenValue = "u1q2".repeat(3)
const outUrlQuery = await sendMessage(`GET /path?token=${urlQueryTokenValue}&page=2`)
const urlQueryText = outUrlQuery.parts[0].text
results.url_query_token = {
  text: urlQueryText,
  valueGone: !urlQueryText.includes(urlQueryTokenValue),
  pageParamPreserved: urlQueryText.includes("&page=2"),
}

// 20. Performance (7.3.1, review-found): a review found two quadratic-time
// hazards -- the bare unquoted key-context pass (a rejected leading key's
// value scan ran to the end of the string, and its own key-identifier scan
// backtracked at every position of a long run with no separator) and
// `url_credentials.pattern` (a long run of scheme-class characters with no
// `://` retried the same expensive backtrack at every position). Both are
// now anchored (a lookbehind, not `\b`/no anchor) so each pathological run
// is walked at most once, not once per character in it, and a
// `max_detect_bytes` catalog cap (256 KiB) is a second, independent
// safety net: beyond it, detection is skipped entirely in favor of the
// cheap, linear-in-input exact-match redaction of values already
// registered. Every one of these must run in comfortably under 1s --
// asserted generously at 1000ms in the Python test, which also prints the
// actual timings for the record.
function base64ish(n) {
  const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
  let s = ""
  for (let i = 0; i < n; i++) s += chars[i % chars.length]
  return s + "=="
}
function minifiedJsLike(bytes) {
  let s = ""
  let i = 0
  while (s.length < bytes) {
    s += `function f${i}(a,b){return a${i % 7 === 0 ? "===" : "+"}b?a:b;} var x${i}={k:${i},"s":"v${i}"};`
    i += 1
  }
  return s.slice(0, bytes)
}
const perfCases = {
  colon_separated_100000: "a:b:c:d:".repeat(100000),
  run_of_a_1mb: "a".repeat(1024 * 1024),
  scheme_class_1mb: "abc+.-".repeat(Math.ceil((1024 * 1024) / 6)),
  base64_1mb: base64ish(1024 * 1024),
  minified_js_200kb: minifiedJsLike(200 * 1024),
}
results.performance = {}
for (const [name, text] of Object.entries(perfCases)) {
  const t0 = performance.now()
  await sendMessage(text)
  results.performance[name] = { length: text.length, ms: performance.now() - t0 }
}

// 21. The over-the-cap path still redacts a value already registered (from
// case 9's `repeated`, well under the cap) -- the cheap fallback
// (`redactKnownValues`) still runs even when the expensive detection
// passes are skipped for being over `max_detect_bytes`.
const overCapText = "x".repeat(1024 * 1024) + repeated + "y".repeat(1024 * 1024)
const outOverCap = await sendMessage(overCapText)
results.over_cap_still_redacts_known_value = {
  valueGone: !outOverCap.parts[0].text.includes(repeated),
  usesSameVariable: outOverCap.parts[0].text.includes(varA ?? "$NEVER_MATCHES$"),
}

console.log(JSON.stringify(results))
