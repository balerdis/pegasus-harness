---
name: _shared
description: "Shared SDD references for installed skills. Not invokable."
disable-model-invocation: true
user-invocable: false
license: MIT
metadata:
  author: gentleman-programming
  version: "1.0"
---

## Purpose

This directory stores shared reference documents consumed by real SDD skills
(for example: `_shared/sdd-phase-common.md`, `_shared/persistence-contract.md`).

`_shared/sdd-session-preflight.md` is the canonical definition of SDD Session
Preflight, which every SDD command asserts but none defines.

## Not Invokable

`_shared` is a support package only. Do not invoke it as a skill.
