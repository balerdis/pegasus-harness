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
  async function refreshSkillRegistry() {
    loadLocalContract()
    const generator = process.env.PEGASUS_SKILL_REGISTRY_BIN
    const configuredRoots = process.env.PEGASUS_SKILL_ROOTS
    if (!generator || !configuredRoots) {
      console.error("[pegasus-skill-registry] skipped: PEGASUS_SKILL_REGISTRY_BIN and PEGASUS_SKILL_ROOTS are required")
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
      console.error("[pegasus-skill-registry] refresh failed:", error)
    }
  }

  void refreshSkillRegistry()
  return {}
}

export default PegasusSkillRegistryPlugin
