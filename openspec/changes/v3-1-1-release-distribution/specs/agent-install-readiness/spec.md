# Agent Install Readiness Specification

## Purpose

Define a privacy-safe, read-only readiness gate and explicit human decision handoff for agent-assisted Pegasus acquisition and installation.

## Requirements

### Requirement: Privacy-safe read-only preflight

The agent preflight MUST inspect only the selected checkout or downloaded release and MUST NOT modify files, configuration, credentials, dependencies, or user state. It MUST report only allowlisted pass/fail results, executable discovery path and version, non-root/ownership context, archive/checksum/manifest integrity, and requested MCP readiness. It MUST NOT print `opencode debug config`, configuration bodies, provider credentials, tokens, secrets, or full/absolute OpenCode configuration contents.

#### Scenario: Ready non-root environment

- GIVEN a non-root user, discoverable Python and OpenCode executables, and an intact v3.1.1 archive with matching checksum and manifest
- WHEN the agent runs preflight
- THEN it reports readiness with only allowlisted facts
- AND it may proceed to the decision handoff without writing state

#### Scenario: Privacy or integrity failure

- GIVEN root execution, missing prerequisites, a checksum mismatch, unsafe archive, or invalid manifest
- WHEN preflight runs
- THEN it reports a bounded failure reason and stops
- AND it MUST NOT emit configuration content or distribute installer/apply commands

### Requirement: INSTALL_BY_AGENT readiness and decision flow

`INSTALL_BY_AGENT.md` MUST document versioned and latest asset locators, the preflight gate, and four independent MCP decisions: `cbm`, `engram`, `playwright`, and `context7`. The agent MUST request an explicit confirm or decline for every MCP, MUST preserve the person's decision exactly, and MUST NOT infer consent. Payload/install commands MAY be distributed only after preflight passes and all four decisions are recorded.

#### Scenario: Complete explicit handoff

- GIVEN preflight passes and the person explicitly confirms or declines each of the four MCPs
- WHEN the agent builds the installation command
- THEN each decision maps to exactly one corresponding action
- AND only confirmed MCPs are eligible for acquisition/configuration

#### Scenario: Declined or missing decision

- GIVEN an MCP is declined or has no explicit decision
- WHEN the handoff is prepared
- THEN the declined MCP MUST receive no download, configuration, or ownership record
- AND a missing decision MUST block command distribution until the person answers

#### Scenario: Existing MCP or credentials need attention

- GIVEN a user asks the agent to configure an existing provider or select a model
- WHEN the agent reaches the handoff
- THEN it MUST defer `/connect`, `/models`, and credential entry to the person
- AND it MUST not inspect or disclose credential-bearing configuration
