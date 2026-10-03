/**
 * {{display_name}} secret transport — OpenCode plugin adapter.
 *
 * Detects a credential value in the user's own message, by context (a value
 * next to a sensitive key name, an auth header, a URL password, a known
 * token shape) or the explicit `<private>` fallback, and substitutes it in
 * place with `$PEGASUS_SECRET_<NAME>` before the message is persisted or
 * reaches the model. The value itself lives only in this module's own
 * in-memory registry, for the life of this OpenCode process, shared by every
 * session it runs (root and sub-agent alike) — never written to disk.
 *
 * The detection catalog is data, not code: it is read from the sidecar file
 * `{{program_name}}-secret-transport-catalog.json`, which the adapter writes
 * next to this plugin at install time from the content core's own copy (see
 * `pegasus.core.credential_transport` and `pegasus.adapters.opencode.
 * adapter`). Nothing here retypes a pattern the catalog already states.
 *
 * Fail open, always: a detection error must never block the user's message
 * or a tool call, and nothing logged here ever contains a value.
 */
import type { Plugin } from "@opencode-ai/plugin"
import { existsSync, readFileSync } from "fs"
import { dirname, join } from "path"
import { fileURLToPath } from "url"

// ─── Catalog loading ─────────────────────────────────────────────────────────

const SIDECAR_NAME = "{{program_name}}-secret-transport-catalog.json"

type KnownFormat = { name: string; pattern: string; whole_block?: boolean }
type HeaderRule =
  | { header_names: string[]; schemes?: string[]; name: string }
  | {
      header_name_suffixes: string[]
      derive_name_from_header: true
      allow_trailing_digit_segment?: boolean
      note?: string
    }
type SkipRule = { name: string; pattern: string; note?: string }

type Catalog = {
  min_value_length: number
  max_detect_bytes?: number
  placeholder_patterns: string[]
  key_context: {
    keys: string[]
    min_value_length?: number
    unquoted_value_pattern: string
    filler_skip_values?: string[]
    filler_skip_patterns?: string[]
    skip_unquoted_if: SkipRule[]
  }
  headers: Record<string, HeaderRule>
  url_credentials: { pattern: string; name: string; note?: string }
  known_formats: KnownFormat[]
  explicit: {
    named: { pattern: string }
    bare: { pattern: string; name: string }
  }
}

function catalogPath(): string {
  // A test driver points this at the real, canonical catalog file instead
  // of a sidecar copy — see `tests/fixtures/secret_transport_harness.mjs`.
  const override = process.env.PEGASUS_SECRET_TRANSPORT_CATALOG
  if (override && existsSync(override)) return override
  return join(dirname(fileURLToPath(import.meta.url)), SIDECAR_NAME)
}

function loadCatalog(): Catalog | null {
  try {
    return JSON.parse(readFileSync(catalogPath(), "utf8"))
  } catch {
    // Missing or unreadable catalog: fail open, detect nothing rather than
    // crash the hook that owns the user's message.
    return null
  }
}

const CATALOG = loadCatalog()

// ─── Naming ──────────────────────────────────────────────────────────────────

/** "clientKey" -> "CLIENTKEY", "client_secret" -> "CLIENT_SECRET", "X-Api-Key" ->
 * "X_API_KEY". Uppercase, any run of non-alphanumeric characters becomes one
 * underscore, and a leading/trailing underscore is trimmed. Never inserts a
 * separator at a camelCase boundary — there is none in the input's own
 * characters to key off, so "clientKey" folds to one word, not two. */
function normalizeName(raw: string): string {
  return raw
    .toUpperCase()
    .replace(/[^A-Z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "") || "SECRET"
}

// ─── Registry: value -> $PEGASUS_SECRET_<NAME>, process-lifetime, in memory ──

const valueToName = new Map<string, string>()
const usedNames = new Set<string>()

function register(value: string, baseName: string): string {
  const existing = valueToName.get(value)
  if (existing) return existing
  let name = normalizeName(baseName)
  if (usedNames.has(name)) {
    let n = 2
    while (usedNames.has(`${name}_${n}`)) n += 1
    name = `${name}_${n}`
  }
  usedNames.add(name)
  valueToName.set(value, name)
  return name
}

function tokenOf(name: string): string {
  return `$PEGASUS_SECRET_${name}`
}

/** Whether `value` is a placeholder or filler non-value that must never be
 * substituted, whatever its length: an already-substituted token, a
 * `${VAR}`/`<...>` interpolation, a run of `*`, or a catalog-data filler
 * word (`null`, `TODO`, `xxx`, ...) matched case-insensitively as a WHOLE
 * value -- never a substring match. */
function isPlaceholder(value: string): boolean {
  if (!CATALOG) return false
  if (CATALOG.placeholder_patterns.some((p) => new RegExp(p).test(value))) return true
  const fillerValues = CATALOG.key_context.filler_skip_values
  if (fillerValues && fillerValues.some((f) => f.toLowerCase() === value.toLowerCase())) return true
  const fillerPatterns = CATALOG.key_context.filler_skip_patterns
  if (fillerPatterns && fillerPatterns.some((p) => new RegExp(p).test(value))) return true
  return false
}

// ─── Detection passes ────────────────────────────────────────────────────────

/** An identifier split into lowercase components on `_`/`-` -- "clientKey"
 * (no separator) is one component, "DB_PASSWORD" is `["db", "password"]`. */
function keyComponents(raw: string): string[] {
  return raw
    .split(/[_-]/)
    .filter(Boolean)
    .map((part) => part.toLowerCase())
}

/** Whether `raw` (a key text captured from the message, e.g. "DB_PASSWORD",
 * "clientKey", "obra_social") names one of the catalog's sensitive keys --
 * either as the WHOLE identifier ("clientKey" against "clientkey") or as its
 * TRAILING component(s) ("DB_PASSWORD" against "password", the compound
 * key's own last word). A key like "obra_social" that shares no catalog
 * key's full word never matches. */
function matchesCatalogKey(raw: string, catalogKeys: string[]): boolean {
  const rawParts = keyComponents(raw)
  if (rawParts.length === 0) return false
  const rawWhole = rawParts.join("")
  for (const key of catalogKeys) {
    const keyParts = keyComponents(key)
    const keyWhole = keyParts.join("")
    if (rawWhole === keyWhole) return true
    if (rawParts.length >= keyParts.length) {
      const tail = rawParts.slice(rawParts.length - keyParts.length).join("")
      if (tail === keyWhole) return true
    }
  }
  return false
}

/** Whether an UNQUOTED candidate value must be left alone because it reads
 * as code, not a credential -- a function call, a dotted reference, a
 * shell/template interpolation, or a bare identifier with no digit at all
 * (see the catalog's own `skip_unquoted_if` for the accepted false negative
 * this last rule causes, and why). Quoted values never go through this --
 * see the module docstring on the bare-quoted pass below. */
function skipsAsUnquotedCode(value: string): boolean {
  if (!CATALOG) return false
  return CATALOG.key_context.skip_unquoted_if.some((rule) => new RegExp(rule.pattern).test(value))
}

/** Run an explicit `<private>...</private>` pass on the text up to its last
 * close tag only. Nothing after it can match (a match ends at a close tag), and
 * leaving it out stops a pile of unclosed open tags from making the lazy
 * catalog patterns rescan to the end of the text once per tag (quadratic). */
function onClosedPart(text: string, apply: (part: string) => string): string {
  let end = -1
  for (const m of text.matchAll(/<\/private>/gi)) end = (m.index ?? 0) + m[0].length
  if (end < 0) return text
  return apply(text.slice(0, end)) + text.slice(end)
}

/** Runs every detection pass over `text`, registering each value found and
 * substituting it with its `$PEGASUS_SECRET_<NAME>` token. Returns the
 * rewritten text and whether anything changed. Fails open on any internal
 * error: the original text survives untouched rather than blocking the
 * caller, and nothing thrown here carries a value. */
/** Size cap, defense in depth (7.3.1): every catalog-driven detection pass
 * below is anchored to avoid the specific quadratic-time shapes a review
 * found, but a giant paste or tool output (a user message, an engram
 * observation body) could still hit some pattern this cap's own author
 * never thought of, and this hook must never be the thing that freezes
 * OpenCode. Beyond `max_detect_bytes` (default 256 KiB, catalog-data), skip
 * every detection pass below and fall back to `redactKnownValues` alone --
 * an exact substring search per already-registered value, linear in the
 * text and the (small, session-lifetime) registry size, never a regex over
 * catalog patterns. A value never seen before is not caught this way, but
 * nothing here blocks the message either way. Documented in MANUAL.md's
 * "qué detecta" and the 7.3.1 section of `arquitectura.md`. */
function detectAndReplace(text: string): { text: string; changed: boolean } {
  if (!CATALOG || !text) return { text, changed: false }
  const cap = CATALOG.max_detect_bytes
  if (cap && Buffer.byteLength(text, "utf8") > cap) {
    const redacted = redactKnownValues(text)
    return { text: redacted, changed: redacted !== text }
  }
  let out = text
  let changed = false

  const substitute = (re: RegExp, baseNameFor: (...groups: string[]) => string, valueGroup: (m: RegExpExecArray) => string) => {
    out = out.replace(re, (...args: any[]) => {
      const match = args[0] as string
      const groups = args.slice(1, args.length - 2) as string[]
      const value = valueGroup([match, ...groups] as unknown as RegExpExecArray)
      if (!value || value.length < CATALOG!.min_value_length || isPlaceholder(value)) return match
      const name = register(value, baseNameFor(...groups))
      changed = true
      return match.replace(value, tokenOf(name))
    })
  }

  try {
    // 1. Explicit <private>NAME=value</private> -- the WHOLE tag is replaced,
    // not just the value inside it: nothing about the tag itself is worth
    // keeping once its value has a variable standing in for it.
    {
      const re = new RegExp(CATALOG.explicit.named.pattern, "g")
      out = onClosedPart(out, (part) =>
        part.replace(re, (match, name, value) => {
          if (!value) return match
          changed = true
          const varName = register(value, name)
          return tokenOf(varName)
        }),
      )
    }

    // 2. Explicit <private>value</private> (whatever is left, i.e. no NAME=)
    {
      const re = new RegExp(CATALOG.explicit.bare.pattern, "g")
      out = onClosedPart(out, (part) =>
        part.replace(re, (match, value) => {
          if (!value) return match
          changed = true
          const varName = register(value, CATALOG!.explicit.bare.name)
          return tokenOf(varName)
        }),
      )
    }

    // 3. Known formats (sk-…, ghp_…, AKIA…, xox…, JWT, PEM private key block)
    for (const format of CATALOG.known_formats) {
      const re = new RegExp(format.pattern, "g")
      out = out.replace(re, (match) => {
        if (match.length < CATALOG!.min_value_length || isPlaceholder(match)) return match
        const name = register(match, format.name)
        changed = true
        return tokenOf(name)
      })
    }

    // 4. Headers: Authorization: Bearer|Basic <v>, X-Api-Key: <v>, and any
    // header whose NAME ends in -Signature/-Token/-Key/-Secret (7.3.1),
    // whatever the header is called -- the variable name for this last kind
    // derives from the actual header name, not a fixed rule name.
    for (const rule of Object.values(CATALOG.headers)) {
      if ("header_names" in rule) {
        const namesAlt = rule.header_names.map((n) => n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")
        const schemePart = rule.schemes ? `(?:${rule.schemes.join("|")})\\s+` : ""
        const re = new RegExp(`(?:${namesAlt})\\s*:\\s*${schemePart}([^\\s,"']{${CATALOG.min_value_length},})`, "gi")
        substitute(re, () => rule.name, (m) => m[1])
      } else if ("header_name_suffixes" in rule) {
        const suffixAlt = rule.header_name_suffixes
          .map((s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
          .join("|")
        // GitHub's own webhook-signature header is `X-Hub-Signature-256` --
        // the sensitive suffix followed by exactly one `-<digits>` segment.
        // `X-Signature-Version`/`X-Api-Key-Version` still do not match: the
        // trailing text there is not digits, so neither branch of this
        // group can reach the colon.
        const digitSuffix = rule.allow_trailing_digit_segment ? "(?:-\\d+)?" : ""
        // A lookbehind, not `\b`, anchors where a match may START: a long
        // run of header-name-shaped characters with no matching suffix
        // anywhere would otherwise make the engine retry the same
        // expensive backtrack at every position in the run (the same
        // O(n^2) hazard as `url_credentials.pattern`, see its own note).
        const re = new RegExp(
          `(?<![A-Za-z0-9-])([A-Za-z][A-Za-z0-9-]*(?:${suffixAlt})${digitSuffix})\\s*:\\s*([^\\s,"']{${CATALOG.min_value_length},})`,
          "gi",
        )
        out = out.replace(re, (match, headerName, value) => {
          if (!value || value.length < CATALOG!.min_value_length || isPlaceholder(value)) return match
          const name = register(value, headerName)
          changed = true
          return match.replace(value, tokenOf(name))
        })
      }
    }

    // 5. URL credentials: scheme://user:password@host
    {
      const re = new RegExp(CATALOG.url_credentials.pattern, "g")
      out = out.replace(re, (match, password) => {
        if (!password || password.length < CATALOG!.min_value_length || isPlaceholder(password)) return match
        const name = register(password, CATALOG!.url_credentials.name)
        changed = true
        return match.replace(password, tokenOf(name))
      })
    }

    // 6. key-context, JSON `"key": "value"` -- key generically identifier-
    // shaped, checked against the catalog by `matchesCatalogKey` rather than
    // restricted to a literal alternation, so a compound key like
    // "DB_PASSWORD" is recognized by its trailing word. A quoted value
    // always counts, whatever it looks like. A value SITTING NEXT TO A
    // SENSITIVE KEY needs only `key_context.min_value_length` characters
    // (4), lower than the catalog's general 8-char floor (7.3.1) -- a
    // catalog-data filler skip list (`isPlaceholder`) keeps this from
    // catching `null`, `TODO`, `****`, etc.
    {
      const minLen = CATALOG.key_context.min_value_length ?? CATALOG.min_value_length
      const re = new RegExp(`"([A-Za-z_$][A-Za-z0-9_$-]*)"\\s*:\\s*"([^"]{${minLen},})"`, "g")
      out = out.replace(re, (match, key, value) => {
        if (!matchesCatalogKey(key, CATALOG!.key_context.keys)) return match
        if (isPlaceholder(value)) return match
        changed = true
        const name = register(value, key)
        return match.replace(`"${value}"`, `"${tokenOf(name)}"`)
      })
    }

    // 7. key-context, bare `key = "value"` / `key: 'value'` -- a QUOTED
    // value after a bare (unquoted) key. Quoted always counts: the point of
    // this pass is exactly the case `password: "plainword"`, a value with no
    // digit that would otherwise read as an identifier -- being inside
    // quotes is what tells this apart from a piece of code.
    {
      const minLen = CATALOG.key_context.min_value_length ?? CATALOG.min_value_length
      // A lookbehind, not `\b`, anchors where a match may START -- see the
      // note on `url_credentials.pattern`. Without it, a long run of
      // identifier-shaped characters with no `[:=]`/quote following
      // anywhere makes the engine retry the same expensive backtrack at
      // every position in the run.
      const re = new RegExp(
        `(?<![A-Za-z0-9_$-])([A-Za-z_$][A-Za-z0-9_$-]*)\\s*[:=]\\s*(?:"([^"]{${minLen},})"|'([^']{${minLen},})')`,
        "g",
      )
      out = out.replace(re, (match, key, dq, sq) => {
        const value = dq ?? sq
        if (!matchesCatalogKey(key, CATALOG!.key_context.keys)) return match
        if (isPlaceholder(value)) return match
        changed = true
        const name = register(value, key)
        return match.replace(value, tokenOf(name))
      })
    }

    // 8. key-context, bare `key=value` / `key: value` -- UNQUOTED. This is
    // the pass a review found corrupting pasted code (`const token =
    // getToken()`, `token = accessToken`, `password: process.env.DB_PASS`):
    // an unquoted value that is a function call, a dotted reference, a
    // shell/template interpolation, or a bare identifier with no digit at
    // all is left untouched (`skipsAsUnquotedCode`, driven by the catalog's
    // own `skip_unquoted_if` -- data, not a hardcoded rule here). The last
    // of those is a deliberate accepted false negative: `DB_PASSWORD=
    // secretpass` is NOT detected this way, only `<private>` catches it; a
    // value with at least one digit (`s3cr3tP4ss`) is not identifier-shaped
    // under that pattern and is still detected. See the 7.3.0 section of
    // `arquitectura.md` and MANUAL.md's "qué detecta" for the user-facing
    // statement of this gap.
    //
    // Manual scan, not `String.replace`, and deliberately so (7.3.1, a
    // review-found regression): an unrelated leading key (`note`,
    // `Content-Type`) that fails `matchesCatalogKey` used to still consume
    // the WHOLE match span as its own (rejected) value -- greedily
    // swallowing a real sensitive `key=value` pair sitting right after it
    // (`note: password=<fake>`, `Content-Type: password=<fake>`), which
    // then never got its own turn. On rejection this only advances past the
    // rejected KEY, not past its value, so the scan retries from right
    // there and still finds the sensitive pair as its own match.
    //
    // Two more, review-found performance hazards, fixed together (7.3.1):
    // `unquoted_value_pattern` now also excludes `;`, `:`, `&` and `?` --
    // without excluding `:`, a value went on being read across another
    // `key:` boundary (`"a:b:c:d:".repeat(n)` took ~5.7s at n=8000, ~4x per
    // doubling: quadratic, because each rejected candidate's value scan ran
    // all the way to the end of the string); without `&`/`?`, a query
    // string's value swallowed the rest of the URL (`?token=<v>&page=2`
    // lost `&page=2`). And the KEY portion is now anchored the same way as
    // `url_credentials.pattern` (a lookbehind, not `\b`) -- a long run of
    // identifier characters with no `[:=]` anywhere (a 1MB run of `a`, say)
    // otherwise makes the engine retry the same expensive backtrack at
    // every position in the run, which is O(n^2) on its own regardless of
    // the value pattern.
    {
      const re = new RegExp(
        `(?<![A-Za-z0-9_$-])([A-Za-z_$][A-Za-z0-9_$-]*)\\s*[:=]\\s*(${CATALOG.key_context.unquoted_value_pattern})`,
        "g",
      )
      let result = ""
      let cursor = 0
      let m: RegExpExecArray | null
      while ((m = re.exec(out))) {
        const [full, key, value] = m
        const accept = matchesCatalogKey(key, CATALOG!.key_context.keys) && !isPlaceholder(value) && !skipsAsUnquotedCode(value)
        if (accept) {
          result += out.slice(cursor, m.index)
          const name = register(value, key)
          result += full.replace(value, tokenOf(name))
          changed = true
          cursor = m.index + full.length
          re.lastIndex = cursor
        } else {
          re.lastIndex = m.index + key.length
        }
      }
      result += out.slice(cursor)
      out = result
    }
  } catch {
    // Fail open: whatever passes already ran stay applied, but a broken
    // pass never throws out of this function and never blocks the caller.
  }

  return { text: out, changed }
}

/** Replace every value this process has already registered, wherever it
 * reappears verbatim (a tool echoing a credential it was handed via
 * `shell.env`, say). Never registers a NEW value — that is `detectAndReplace`'s
 * job — this only redacts values already known. */
function redactKnownValues(text: string): string {
  if (!text) return text
  let out = text
  for (const [value, name] of valueToName) {
    if (out.includes(value)) out = out.split(value).join(tokenOf(name))
  }
  return out
}

/** Strip any `<private>` tag detection missed (should be none after
 * `detectAndReplace`'s own explicit passes — this is the same safety net
 * `engram.ts`'s own `stripPrivateTags` already applies, kept here too since
 * this function is meant to run standalone from any other plugin). */
function stripPrivateFallback(text: string): string {
  if (!text) return text
  // Linear scan equal to /<private>[\s\S]*?<\/private>/gi, which rescans to the
  // end of the text for every unclosed open tag (quadratic).
  const open = /<private>/gi
  const close = /<\/private>/gi
  let out = ""
  let pos = 0
  while (true) {
    open.lastIndex = pos
    const start = open.exec(text)
    if (!start) break
    close.lastIndex = start.index + start[0].length
    const end = close.exec(text)
    if (!end) break
    out += text.slice(pos, start.index) + "[REDACTED]"
    pos = end.index + end[0].length
  }
  return out + text.slice(pos)
}

// ─── Process-wide redaction, for other plugins (engram.ts) to call ──────────

const REDACTION_GLOBAL_KEY = "__CREDENTIAL_TRANSPORT_V1__"

function globalRedact(text: string): string {
  if (!text) return text
  try {
    const { text: afterKnown } = detectAndReplace(text)
    return stripPrivateFallback(redactKnownValues(afterKnown))
  } catch {
    // Fail open: never block whoever is calling this over a detection bug,
    // and never let an exception here carry a value in its message.
    return text
  }
}

;(globalThis as any)[REDACTION_GLOBAL_KEY] = { redact: globalRedact }

// ─── Plugin export ───────────────────────────────────────────────────────────

// A marker substring, not the whole text: used only to detect that a note
// (or warning) is ALREADY present in the message, so it is never appended
// twice -- a message can carry one appended by a past OpenCode process (see
// `UNKNOWN_VARIABLE_WARNING_MARKER` below) or by an earlier pass over the
// same text in this one.
const REPLACED_VALUES_NOTE_MARKER = "were replaced with variables shown as"
const UNKNOWN_VARIABLE_WARNING_MARKER = "no value in this session"

const REPLACED_VALUES_NOTE_BODY =
  "Some values in this message were replaced with variables shown as " +
  "`$PEGASUS_SECRET_<NAME>` — a shell command expands them at run time. " +
  "Use the variable name, never the value, in any brief, command, file or " +
  "reply, and never print it (no `echo`, no verbose flag that would dump it)."

/** Every `$PEGASUS_SECRET_<NAME>` token in `text` whose NAME this process
 * has not registered -- a variable with no value here, either because
 * OpenCode was restarted since it was registered, or because the text was
 * copied out of a different (past) OpenCode process's history. The
 * literal `<NAME>` placeholder inside the note's own prose is never
 * matched: the pattern requires at least one `[A-Z0-9_]` right after
 * `SECRET_`, and `<` is not in that class. */
function findUnknownVariableNames(text: string): string[] {
  if (!text) return []
  const re = /\$PEGASUS_SECRET_([A-Z0-9_]+)/g
  const unknown = new Set<string>()
  let m: RegExpExecArray | null
  while ((m = re.exec(text))) {
    if (!usedNames.has(m[1])) unknown.add(m[1])
  }
  return [...unknown]
}

/** Short, model- and human-readable warning naming every variable in
 * `names` that has no value in this session, why (a restart, or a paste
 * from an earlier session), what happens if used anyway (a shell command
 * expands it to empty), and the fix (paste the real value again). */
function unknownVariableWarningBody(names: string[]): string {
  const plural = names.length > 1
  const list = names.map((n) => `\`$PEGASUS_SECRET_${n}\``).join(", ")
  return (
    `${list} ${plural ? "have" : "has"} no value in this session ` +
    "(OpenCode was restarted, or this text was copied from an earlier " +
    `session). A shell command would expand ${plural ? "them" : "it"} to ` +
    `empty. Paste the real value${plural ? "s" : ""} again.`
  )
}

/** One note block, never two separate appendices: the replaced-values
 * note and the unknown-variable warning, each added only when it applies
 * and is not already present, sharing a single `---` divider. */
function buildNoteBlock(includeReplacedNote: boolean, unknownNames: string[]): string {
  const paragraphs: string[] = []
  if (includeReplacedNote) paragraphs.push(REPLACED_VALUES_NOTE_BODY)
  if (unknownNames.length > 0) paragraphs.push(unknownVariableWarningBody(unknownNames))
  return "\n\n---\n" + paragraphs.join("\n\n")
}

export const SecretTransportPlugin: Plugin = async () => {
  return {
    "chat.message": async (_input, output) => {
      try {
        let changed = false
        for (const part of output.parts as any[]) {
          if (part?.type !== "text" || typeof part.text !== "string") continue
          const result = detectAndReplace(part.text)
          if (result.changed) {
            part.text = result.text
            changed = true
          }
        }

        const parts = output.parts as any[]
        const fullText = parts
          .filter((p) => p?.type === "text" && typeof p.text === "string")
          .map((p) => p.text)
          .join("\n")

        const needsReplacedNote = changed && !fullText.includes(REPLACED_VALUES_NOTE_MARKER)
        const unknownNames = fullText.includes(UNKNOWN_VARIABLE_WARNING_MARKER) ? [] : findUnknownVariableNames(fullText)

        if (needsReplacedNote || unknownNames.length > 0) {
          const block = buildNoteBlock(needsReplacedNote, unknownNames)
          const lastText = [...parts].reverse().find((p) => p?.type === "text")
          if (lastText) {
            lastText.text += block
          } else {
            parts.push({ type: "text", text: block.trim() })
          }
        }
      } catch {
        // Fail open: never block the user's message over a detection bug.
      }
    },

    "shell.env": async (_input, output) => {
      try {
        const env: Record<string, string> = { ...(output.env ?? {}) }
        for (const [value, name] of valueToName) {
          env[`PEGASUS_SECRET_${name}`] = value
        }
        output.env = env
      } catch {
        // Fail open: never block command execution over a registry bug.
      }
    },

    "tool.execute.after": async (_input, output) => {
      try {
        if (output && typeof output.output === "string") {
          output.output = redactKnownValues(output.output)
        }
        if (output?.metadata && typeof output.metadata.output === "string") {
          output.metadata.output = redactKnownValues(output.metadata.output)
        }
      } catch {
        // Fail open: never block a tool result over a redaction bug.
      }
    },
  }
}

export default SecretTransportPlugin
