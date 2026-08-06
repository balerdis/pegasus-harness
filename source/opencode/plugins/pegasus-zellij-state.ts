import type { Plugin } from "@opencode-ai/plugin"
import { spawn } from "node:child_process"
import { appendFile, mkdir } from "node:fs/promises"
import { existsSync } from "node:fs"
import { homedir } from "node:os"
import { join } from "node:path"

const REPORT_SCRIPT = join(homedir(), ".config", "pegasus-zellij-state", "scripts", "agent-report.sh")
const DEBUG_LOG = join(homedir(), ".cache", "pegasus-zellij-state", "events.log")
const ACTIVE_STATUS = new Set(["active", "busy", "pending", "running", "streaming", "working", "retry"])
const blockedSessions = new Set<string>()
const blockedPermissions = new Map<string, string>()
type ReportState = "working" | "blocked" | "idle" | "orchestrator-idle"
type Reporter = (state: ReportState, message?: string) => void

function debugEnabled() {
  return process.env.PEGASUS_ZELLIJ_STATE_DEBUG === "1"
}

function safeJson(value: unknown) {
  try {
    return JSON.stringify(value)
  } catch {
    return JSON.stringify({ unserializable: true })
  }
}

async function debugLog(label: string, payload: unknown) {
  if (!debugEnabled()) return

  try {
    await mkdir(join(homedir(), ".cache", "pegasus-zellij-state"), { recursive: true })
    const line = `${new Date().toISOString()} ${label} pane=${paneId()} zellij=${inZellij()} ${safeJson(payload)}\n`
    await appendFile(DEBUG_LOG, line)
  } catch {
    // Debug logging must never break OpenCode.
  }
}

function inZellij() {
  return Boolean(process.env.ZELLIJ_PANE_ID || process.env.ZELLIJ)
}

function paneId() {
  return process.env.ZELLIJ_PANE_ID || "current"
}

function report(state: ReportState, message = "") {
  if (!inZellij()) return
  if (!existsSync(REPORT_SCRIPT)) return

  const child = spawn(REPORT_SCRIPT, [paneId(), state, message], {
    detached: true,
    stdio: "ignore",
    env: process.env,
  })

  child.unref()
}

function reportWorking(message = "working") {
  if (blockedSessions.size > 0) {
    report("blocked", "permission.pending")
    return
  }

  report("working", message)
}

function sessionIDFrom(input: any) {
  return input?.sessionID || input?.event?.properties?.sessionID || input?.properties?.sessionID || ""
}

function rememberSessionHierarchy(event: any, sessionParents: Map<string, boolean>) {
  if (event?.type !== "session.created" && event?.type !== "session.updated") return

  const info = event?.properties?.info
  const sessionID = info?.id || info?.sessionID || ""
  if (!sessionID || !info || typeof info !== "object") return

  sessionParents.set(sessionID, Boolean(info.parentID))
}

function permissionIDFrom(event: any) {
  return event?.properties?.id || event?.properties?.requestID || ""
}

function rememberBlockedPermission(event: any) {
  const sessionID = sessionIDFrom(event)
  const permissionID = permissionIDFrom(event)

  if (sessionID) blockedSessions.add(sessionID)
  if (permissionID && sessionID) blockedPermissions.set(permissionID, sessionID)
}

function clearBlockedPermission(event: any) {
  const permissionID = permissionIDFrom(event)
  const sessionID = sessionIDFrom(event) || (permissionID ? blockedPermissions.get(permissionID) : "") || ""

  if (permissionID) blockedPermissions.delete(permissionID)
  if (sessionID) blockedSessions.delete(sessionID)
}

function statusType(status: unknown) {
  if (!status) return ""
  if (typeof status === "string") return status
  if (typeof status === "object" && status !== null && "type" in status && typeof status.type === "string") {
    return status.type
  }
  return ""
}

function stateForEvent(event: any): "working" | "blocked" | "idle" | undefined {
  const type = event?.type || ""

  if (type === "session.status") {
    const current = statusType(event?.properties?.status)
    if (current === "idle") return "idle"
    if (ACTIVE_STATUS.has(current)) return "working"
    return undefined
  }

  if (type === "permission.asked" || type === "question.asked") return "blocked"
  if (type === "session.idle" || type === "session.deleted") return "idle"

  if (
    type === "permission.replied" ||
    type === "question.replied" ||
    type === "question.rejected" ||
    type === "session.compacted"
  ) {
    return "working"
  }

  return undefined
}

function eventMessage(event: any) {
  const type = event?.type || "opencode"
  const status = statusType(event?.properties?.status)
  return status ? `${type}:${status}` : type
}

function isKnownRootIdle(event: any, sessionParents: Map<string, boolean>) {
  const isExplicitIdle =
    (event?.type === "session.status" && statusType(event?.properties?.status) === "idle") ||
    event?.type === "session.idle"
  const sessionID = sessionIDFrom(event)

  return isExplicitIdle && Boolean(sessionID) && sessionParents.get(sessionID) === false
}

export function createEventProcessor(reporter: Reporter) {
  const sessionParents = new Map<string, boolean>()

  return (event: any) => {
    rememberSessionHierarchy(event, sessionParents)

    if (event?.type === "session.deleted") {
      sessionParents.delete(sessionIDFrom(event))
    }

    if (event?.type === "permission.asked") {
      rememberBlockedPermission(event)
      reporter("blocked", eventMessage(event))
      return
    }

    if (event?.type === "permission.replied") {
      clearBlockedPermission(event)
      if (blockedSessions.size > 0) reporter("blocked", "permission.pending")
      else reporter("working", eventMessage(event))
      return
    }

    const state = stateForEvent(event)
    if (state === "working") {
      if (blockedSessions.size > 0) reporter("blocked", "permission.pending")
      else reporter("working", eventMessage(event))
    }
    if (state === "blocked") reporter("blocked", eventMessage(event))
    if (state === "idle" && blockedSessions.size === 0) {
      reporter(isKnownRootIdle(event, sessionParents) ? "orchestrator-idle" : "idle", eventMessage(event))
    }
  }
}

const PegasusZellijStatePlugin: Plugin = async () => {
  await debugLog("plugin.loaded", {
    zellijPaneId: process.env.ZELLIJ_PANE_ID,
    zellij: process.env.ZELLIJ,
    reportScriptExists: existsSync(REPORT_SCRIPT),
  })

  const processEvent = createEventProcessor(report)

  return {
    event: async ({ event }: any) => {
      await debugLog("hook.event", event)
      processEvent(event)
    },

    "chat.message": async (input: any) => {
      await debugLog("hook.chat.message", input)
      reportWorking("chat.message")
    },

    "tool.execute.before": async ({ tool, ...rest }: any) => {
      await debugLog("hook.tool.execute.before", { tool, ...rest })
      reportWorking(tool ? `tool.execute.before:${tool}` : "tool.execute.before")
    },

    "tool.execute.after": async ({ tool, ...rest }: any) => {
      await debugLog("hook.tool.execute.after", { tool, ...rest })
      reportWorking(tool ? `tool.execute.after:${tool}` : "tool.execute.after")
    },

    "permission.ask": async (input: any) => {
      await debugLog("hook.permission.ask", input)
      report("blocked", "permission.asked")
    },
  }
}

export default PegasusZellijStatePlugin
