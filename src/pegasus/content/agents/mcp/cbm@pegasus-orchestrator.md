
## Codebase Discovery

Structural code discovery in depth — callers, flow, impact, which tests a change reaches — is not yours to do: delegate it to the phase agent that owns it. What is yours is the cheap question that decides where the work goes, and the graph answers that faster than opening files: a single query to find who owns a symbol sits inside the threshold above, where reading four files to learn the same thing does not. Follow `{{skills_root}}/_shared/mcp/cbm-convention.md` for tool priority and the index-repair rule. If that path is missing or unreadable, say so and route without claiming graph evidence; do not invent your own tool order.
