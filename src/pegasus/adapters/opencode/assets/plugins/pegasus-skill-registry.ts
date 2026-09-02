/** Refresh the Pegasus skill registry asynchronously when OpenCode starts. */
import type { Plugin } from "@opencode-ai/plugin"
import { execFile } from "child_process"
import { existsSync, readFileSync } from "fs"
import { homedir } from "os"
import { delimiter } from "path"
import { join } from "path"
import { promisify } from "util"

const execFileAsync = promisify(execFile)
const CONTRACT_KEYS = new Set(["PEGASUS_SKILL_REGISTRY_BIN", "PEGASUS_SKILL_ROOTS"])

function loadLocalContract() {
  const configDirectory = process.env.XDG_CONFIG_HOME || join(homedir(), ".config")
  const contractPath = join(configDirectory, "opencode", "pegasus-skill-registry.env")
  if (!existsSync(contractPath)) return
  for (const line of readFileSync(contractPath, "utf8").split(/\r?\n/)) {
    const match = line.match(/^\s*(PEGASUS_SKILL_REGISTRY_BIN|PEGASUS_SKILL_ROOTS)=(.+?)\s*$/)
    if (match && CONTRACT_KEYS.has(match[1]) && !process.env[match[1]]) {
      process.env[match[1]] = match[2]
    }
  }
}

export const PegasusSkillRegistryPlugin: Plugin = async (input) => {
  // console.error alone never reaches whoever is running OpenCode -- a plugin's
  // stderr is not surfaced anywhere a person looks. Route every failure through
  // here so the log of record and the on-screen surfacing can never drift apart.
  async function reportFailure(variant: "warning" | "error", message: string, detail?: unknown) {
    if (detail === undefined) {
      console.error(`[pegasus-skill-registry] ${message}`)
    } else {
      console.error(`[pegasus-skill-registry] ${message}`, detail)
    }
    try {
      // Best-effort: `opencode run` and other non-TUI clients have nothing to
      // show a toast on, so a failed call here is an ordinary outcome, not a
      // second failure to report.
      await input.client.tui.showToast({
        body: { title: "Pegasus skill registry", message, variant },
      })
    } catch {
      // ignore, see above
    }
  }

  async function refreshSkillRegistry() {
    loadLocalContract()
    const generator = process.env.PEGASUS_SKILL_REGISTRY_BIN
    const configuredRoots = process.env.PEGASUS_SKILL_ROOTS
    if (!generator || !configuredRoots) {
      // Misconfiguration, not a crash: the registry was never wired up here.
      await reportFailure("warning", "skipped: PEGASUS_SKILL_REGISTRY_BIN and PEGASUS_SKILL_ROOTS are required")
      return
    }
    const projectRoot = input.directory || input.worktree || process.cwd()
    const args = ["--project-root", projectRoot]
    for (const root of [join(projectRoot, "skills"), join(projectRoot, ".opencode", "skills"), join(projectRoot, ".opencode", "skill")]) {
      args.push("--skill-root", root)
    }
    for (const root of configuredRoots.split(delimiter).filter(Boolean)) {
      args.push("--skill-root", root)
    }
    try {
      await execFileAsync(generator, args, { timeout: 30_000 })
    } catch (error) {
      await reportFailure("error", "refresh failed", error)
    }
  }

  void refreshSkillRegistry()
  return {}
}

export default PegasusSkillRegistryPlugin
