---
name: jira
description: Atlassian's own remote server, for the issues and pages an organisation tracks
distribution: remote
endpoint: https://mcp.atlassian.com/v1/mcp
reaches: [king-pegasus, pegasus-general, pegasus-orchestrator, sdd-apply, sdd-design, sdd-explore, sdd-onboard, sdd-verify]
---

# Jira Convention (the organisation's system of record)

This server reaches Atlassian directly. What it exposes is Atlassian's to decide and
can change without this file changing: treat the tool list you are actually offered as
the answer, never this paragraph. What is fixed is the kind of place it reaches -- the
one an organisation tracks its work in.

Other servers here also leave this machine — a Context7 query does,
a Playwright session does — but this is the only one that can *change a record other
people read*. What a browser or a documentation lookup sends outward disappears; what
this writes stays, under someone's name, in a place a team works from.

Reach for it when the question is what an organisation decided, tracked, or wrote
down: the scope of a ticket, the acceptance criteria someone agreed to, the page
describing how a system is meant to work, who a piece of work is assigned to. Prefer
it over inferring intent from code whenever the intent was actually written down
somewhere — a commit message is one person's recollection; the ticket is what was
agreed.

## Nothing Is Withheld Here

One server in this project — `cbm` — has its destructive tools removed from reach by
name. This one has nothing removed: whatever Atlassian exposes, an agent granted this
server can call, creating and transitioning issues and editing pages included. That is
deliberate. The tool list is not enumerable without credentials, and a name guessed
wrong in a deny list withholds nothing while looking like it does — a protection that
lies is worse than none. So the whole of the judgment lives here, in prose, rather than
in a list.

So the rule is a rule about intent, not about capability:

- **Read freely.** Fetching an issue, searching, reading a page — none of it changes
  anything and none of it needs asking about.
- **Write only what was asked for, as it was asked for.** Creating an issue,
  transitioning one, commenting, editing a page: do these when someone asked for that
  specific act, not because it seemed like the tidy thing to do after finishing a
  task.
- **Never write to clean up.** Closing a stale ticket, fixing someone else's
  description, re-assigning: each of those is a decision about someone else's work,
  and it notifies them.

**When in doubt, do not write.** Say what you would have written and to which issue or
page, and let whoever asked decide. A sub-agent has no way to ask mid-task — that is
by design, not an oversight — so for a sub-agent "in doubt" resolves one way only, and
reporting the intended write is the whole of the move.

A wrong edit here is not like a wrong edit in a file. There is no local undo, the
history is public to the team, and the notification has already gone out by the time
anyone notices. Treat an unasked-for write as the thing that cannot be taken back,
because it is.

## Reading Well

- Name the issue or page you want. A broad sweep across a project returns volume, not
  an answer, and the useful half is usually already known.
- A ticket states intent, not fact. It says what someone wanted at the time it was
  written; it does not say what the code does now, and the two drift. Never present a
  ticket's description as evidence about the current behaviour of anything.
- Quote what a ticket actually says rather than summarising it into your own framing.
  The wording of an acceptance criterion is frequently the whole point of it.
- A closed ticket is not proof the work is right, only that someone marked it done.

## Never Send Upward

An issue and a page are readable by everyone in the organisation and are indexed and
retained. Never put into either: credentials, tokens, connection strings, customer
data, or the contents of a file this project treats as secret. This holds even when
the ticket is about the thing itself — describe the failure, not the secret.

## When It Is Not Available

Authentication for this server belongs to the runtime, not to this project: no
credential travels in this descriptor, and nothing here can log in on your behalf. It
also does not happen on its own — a person has to run the runtime's own one-time
authorisation for this server (under OpenCode, `opencode mcp auth jira`) before any
tool here answers. Until then every call fails the same way, and installing the server
again will not change it.

So if the server is unreachable or not authenticated, say exactly that, name that
command as the fix, and continue without it. Do not work around it by guessing at a
ticket's contents from its key, and do not present an inference about what a ticket
probably says as though it had been read.
