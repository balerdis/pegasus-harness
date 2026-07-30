#!/usr/bin/env python3
"""Validate the frozen Phase-1 snapshot without touching active configuration."""
from __future__ import annotations
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "manifests/baseline-manifest.json").read_text())
EXPECTED = ["README.md", "bin/pegasus", "source/opencode/opencode.json", "source/opencode/AGENTS.md", "source/agents/pegasus-orchestrator.md", "source/opencode/plugins/engram.ts", "source/opencode/plugins/pegasus-zellij-state.ts", "docs/migration-todos.md", "docs/bootstrap-contract.md", "manifests/bootstrap-contract.json", "examples/opencode.overlay.example.json"]
FORBIDDEN = {"retired graph tool": re.compile(r"(?i)codegraph"), "upstream runtime command": re.compile(r"(?i)gentle-ai\s+(?:sync|sdd-|review|skill-registry)")}
SECRET = re.compile(r"(?i)(?:api[_-]?key|authorization|bearer|password|cookie)\s*[:=]\s*(?![\"']?\{env:|[\"']?set-this-|[\"']?REDACTED)(?:[\"']?[A-Za-z0-9_./+=-]{12,})")
MACHINE_BOUND_PATH = re.compile(r"(?:/home/serg/|~/.config/opencode/|\{file:/(?!/)|\{file:~/)")

def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

errors = []
for relative in EXPECTED:
    if not (ROOT / relative).is_file(): errors.append(f"missing expected file: {relative}")
for item in MANIFEST["copied"] + MANIFEST.get("pegasus_owned", []):
    path = ROOT / item["frozen_path"]
    if not path.is_file(): errors.append(f"missing manifest asset: {item['frozen_path']}")
    elif digest(path) != item["frozen_sha256"]: errors.append(f"checksum mismatch: {item['frozen_path']}")
for path in (ROOT / "source").rglob("*"):
    if not path.is_file(): continue
    try: content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError: errors.append(f"binary asset not permitted: {path.relative_to(ROOT)}"); continue
    for label, pattern in FORBIDDEN.items():
        if pattern.search(content): errors.append(f"{label}: {path.relative_to(ROOT)}")
    if SECRET.search(content): errors.append(f"possible credential: {path.relative_to(ROOT)}")
try: json.loads((ROOT / "source/opencode/opencode.json").read_text())
except Exception as error: errors.append(f"invalid sanitized config JSON: {error}")
else:
    config_path = ROOT / "source/opencode/opencode.json"
    config = json.loads(config_path.read_text())
    serialized = json.dumps(config)
    if MACHINE_BOUND_PATH.search(serialized):
        errors.append("machine-bound path in portable activation template")
    for agent_name, agent in config.get("agent", {}).items():
        if not isinstance(agent, dict) or not isinstance(agent.get("prompt"), str):
            continue
        prompt = agent["prompt"]
        match = re.fullmatch(r"\{file:([^{}]+)\}", prompt)
        if not match:
            continue
        reference = match.group(1)
        if reference.startswith(("/", "~/")):
            errors.append(f"absolute prompt reference: agent.{agent_name}")
        elif not (config_path.parent / reference).resolve().is_file():
            errors.append(f"missing relative prompt target: agent.{agent_name}")
if errors:
    print("FAIL")
    print("\n".join(errors))
    sys.exit(1)
print(f"PASS: {len(MANIFEST['copied']) + len(MANIFEST.get('pegasus_owned', []))} frozen assets verified; source policy scan clean.")
