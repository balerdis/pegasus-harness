/** Say what `apply_patch` can reach, so its opening imperative is not read as a ban on the shell. */
import type { Plugin } from "@opencode-ai/plugin"

// Why this plugin exists at all.
//
// The runtime folds `edit`, `write` and `apply_patch` onto a single `edit`
// permission when it decides which tools to send to the model. Granting `edit`
// therefore hands over `apply_patch` as well, and there is no way to withhold
// that one tool without withholding editing entirely -- which is not a trade
// anyone wants. So the tool arrives whatever the permissions say, and its
// description arrives with it.
//
// That description opens with an imperative telling the model to use
// `apply_patch` to edit files. A model read that as a developer-priority
// instruction outranking its system prompt and refused to edit a file on
// another host over SSH, even though the person had explicitly authorized the
// change, and kept refusing after the prompt said otherwise. Text that travels
// with the tool definitions carries more weight than text that travels as a
// prompt, so the correction has to travel on the same channel. `tool.definition`
// is the only hook that writes there: whatever it leaves in `output.description`
// is what actually reaches the model.
//
// Why this appends instead of rewriting.
//
// Cutting the imperative would mean matching a sentence the runtime owns and
// may reword at any time. The day it changes, the match stops applying in
// silence and the old refusal quietly comes back. An appended paragraph stays
// true no matter how the rest of the description is worded, so it degrades into
// harmless duplication rather than into an invisible regression.
//
// The limit, which matters as much as the reason: amend the runtime's text only
// when it contradicts what this product needs *and* no permission lever exists.
// A permission that can be denied gets denied; a tool that can be withheld gets
// withheld. Only when both are closed -- as here, where the tool rides along
// with a permission we do want -- is its wording amended.

// The idempotence marker: the hook can fire more than once for the same tool,
// and the paragraph must be added exactly once. Matching on a fragment of what
// this plugin itself wrote (never on the runtime's own text) keeps the check
// under this file's control.
const SCOPE_MARKER = "writes to the local filesystem of the machine this session runs on"

const SCOPE_NOTE = [
  "",
  "",
  `Scope of this tool: it ${SCOPE_MARKER} and nowhere else. It cannot reach a file that lives on `,
  "another host. When a request is about editing files, this tool means local files. It is not an ",
  "instruction to avoid the shell, and it does not forbid editing a remote file over SSH with `bash` ",
  "when the person has authorized that change. For a destination on another machine the shell is not ",
  "a way around this tool -- it is the only way there.",
].join("")

const {{program_pascal_name}}ApplyPatchScope: Plugin = async () => ({
  "tool.definition": async (
    input: { toolID: string },
    output: { description: string; parameters: any },
  ) => {
    if (input.toolID !== "apply_patch") return
    if (typeof output.description !== "string") return
    if (output.description.includes(SCOPE_MARKER)) return
    output.description = output.description + SCOPE_NOTE
  },
})

export default {{program_pascal_name}}ApplyPatchScope
