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
type HeaderRule = { header_names: string[]; schemes?: string[]; name: string }
type SkipRule = { name: string; pattern: string; note?: string }

type Catalog = {
  min_value_length: number
  placeholder_patterns: string[]
  key_context: { keys: string[]; unquoted_value_pattern: string; skip_unquoted_if: SkipRule[] }
  headers: Record<string, HeaderRule>
  url_credentials: { pattern: string; name: string }
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

function isPlaceholder(value: string): boolean {
  if (!CATALOG) return false
  return CATALOG.placeholder_patterns.some((p) => new RegExp(p).test(value))
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

/** Runs every detection pass over `text`, registering each value found and
 * substituting it with its `$PEGASUS_SECRET_<NAME>` token. Returns the
 * rewritten text and whether anything changed. Fails open on any internal
 * error: the original text survives untouched rather than blocking the
 * caller, and nothing thrown here carries a value. */
function detectAndReplace(text: string): { text: string; changed: boolean } {
  if (!CATALOG || !text) return { text, changed: false }
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
      out = out.replace(re, (match, name, value) => {
        if (!value) return match
        changed = true
        const varName = register(value, name)
        return tokenOf(varName)
      })
    }

    // 2. Explicit <private>value</private> (whatever is left, i.e. no NAME=)
    {
      const re = new RegExp(CATALOG.explicit.bare.pattern, "g")
      out = out.replace(re, (match, value) => {
        if (!value) return match
        changed = true
        const varName = register(value, CATALOG!.explicit.bare.name)
        return tokenOf(varName)
      })
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

    // 4. Headers: Authorization: Bearer|Basic <v>, X-Api-Key: <v>
    for (const rule of Object.values(CATALOG.headers)) {
      const namesAlt = rule.header_names.map((n) => n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")
      const schemePart = rule.schemes ? `(?:${rule.schemes.join("|")})\\s+` : ""
      const re = new RegExp(`(?:${namesAlt})\\s*:\\s*${schemePart}([^\\s,"']{${CATALOG.min_value_length},})`, "gi")
      substitute(re, () => rule.name, (m) => m[1])
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
    // always counts, whatever it looks like.
    {
      const re = /"([A-Za-z_$][A-Za-z0-9_$-]*)"\s*:\s*"([^"]{8,})"/g
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
      const re = /\b([A-Za-z_$][A-Za-z0-9_$-]*)\s*[:=]\s*(?:"([^"]{8,})"|'([^']{8,})')/g
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
    {
      const re = new RegExp(
        `\\b([A-Za-z_$][A-Za-z0-9_$-]*)\\s*[:=]\\s*(${CATALOG.key_context.unquoted_value_pattern})`,
        "g",
      )
      out = out.replace(re, (match, key, value) => {
        if (!matchesCatalogKey(key, CATALOG!.key_context.keys)) return match
        if (isPlaceholder(value) || skipsAsUnquotedCode(value)) return match
        changed = true
        const name = register(value, key)
        return match.replace(value, tokenOf(name))
      })
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
  return text.replace(/<private>[\s\S]*?<\/private>/gi, "[REDACTED]")
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

const NOTE =
  "\n\n---\n" +
  "Some values in this message were replaced with variables shown as " +
  "`$PEGASUS_SECRET_<NAME>` — a shell command expands them at run time. " +
  "Use the variable name, never the value, in any brief, command, file or " +
  "reply, and never print it (no `echo`, no verbose flag that would dump it)."

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
        if (changed) {
          const parts = output.parts as any[]
          const lastText = [...parts].reverse().find((p) => p?.type === "text")
          if (lastText) {
            lastText.text += NOTE
          } else {
            parts.push({ type: "text", text: NOTE.trim() })
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
