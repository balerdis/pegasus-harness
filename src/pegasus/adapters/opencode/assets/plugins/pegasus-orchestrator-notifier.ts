import type { Plugin } from "@opencode-ai/plugin"
import { spawn } from "node:child_process"

// The name of the agent a session starts in is content-declared (see
// `Agent.default` / `SESSION_STARTS_IN` in the content core), never a literal
// this plugin picks for itself: a distribution overlays its own content, so
// the real orchestrator name varies per release and a hardcoded literal here
// would silently stop matching. The value below is a placeholder the adapter
// fills at install time from that content-declared name -- see
// `core.placeholders` and `adapter.own_artifacts`.
//
// Substitution runs over an asset's whole text, comments included, so this
// prose deliberately spells no placeholder token. An earlier version of this
// comment named two of them and had itself rewritten: the sentences turned to
// nonsense and an installing machine's absolute path was baked into a shipped
// plugin. Describe a placeholder here; never write one.
const ORCHESTRATOR_AGENT = "{{orchestrator}}"
const sessionStates = new Map<string, "idle" | "blocked" | "working">()

function sessionIDFrom(event: any) {
  return event?.properties?.sessionID || ""
}

function eventState(event: any): "idle" | "blocked" | "working" | undefined {
  if (event?.type === "session.status") {
    if (event.properties?.status?.type === "idle") return "idle"
    if (event.properties?.status?.type === "busy") return "working"
  }

  if (event?.type === "session.idle") return "idle"
  if (event?.type === "permission.asked" || event?.type === "question.asked") return "blocked"
  if (event?.type === "permission.replied" || event?.type === "question.replied" || event?.type === "question.rejected") return "working"
  return undefined
}

function notify(state: "idle" | "blocked") {
  const child = spawn("/usr/bin/notify-send", ["-a", "OC", "OC", `OC ${state}`], {
    detached: true,
    stdio: "ignore",
  })
  child.on("error", () => {})
  child.unref()
}

const PegasusOrchestratorNotifier: Plugin = async ({ client }) => ({
  event: async ({ event }: any) => {
    const state = eventState(event)
    if (!state) return

    const sessionID = sessionIDFrom(event)
    if (!sessionID) return

    try {
      const response = await client.session.get({ path: { id: sessionID } })
      if (response.data?.agent !== ORCHESTRATOR_AGENT) return
    } catch {
      return
    }

    if (sessionStates.get(sessionID) === state) return
    sessionStates.set(sessionID, state)

    if (state === "idle" || state === "blocked") notify(state)
  },
})

export default PegasusOrchestratorNotifier
