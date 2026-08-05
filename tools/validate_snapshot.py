#!/usr/bin/env python3
"""Validate the tracked Pegasus v2 product surface and release contract."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "manifests" / "release-contract.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tracked_files() -> list[Path]:
    result = subprocess.run(["git", "ls-files", "-co", "--exclude-standard", "-z"], cwd=ROOT, capture_output=True, check=True)
    return [ROOT / Path(item) for item in result.stdout.decode().split("\0") if item and (ROOT / item).is_file()]


def forbidden_patterns() -> list[re.Pattern[str]]:
    parts = (
        ("gent", "le"), ("code", "graph"), ("4", "r"), ("native", "review"),
        ("judg", "ment"), ("review", "agent"), ("refut", "er"),
        ("rec", "eipt"), ("led", "ger"), ("trans", "action"),
        ("correction", "protocol"),
    )
    return [re.compile("".join(part), re.IGNORECASE) for part in parts]


def remote_installer_patterns() -> list[re.Pattern[str]]:
    return [
        re.compile(r"\b(?:curl|wget)\b", re.IGNORECASE),
        re.compile(r"\b(?:ba)?sh\s+-c\b", re.IGNORECASE),
        re.compile(r"https?://[^\s\"']*(?:install|installer)", re.IGNORECASE),
        re.compile(r"--skip-(?:opencode|cbm)-install", re.IGNORECASE),
    ]


def main() -> int:
    errors: list[str] = []
    try:
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"FAIL\ninvalid release contract: {error}")
        return 1
    installer = next((asset for asset in contract.get("distribution_assets", []) if asset.get("path") == "install.sh"), None)
    if not installer or installer.get("sha256") != digest(ROOT / "install.sh"):
        errors.append("release contract digest does not match install.sh")
    if contract.get("version") != "2.0.1":
        errors.append("release contract is not prepared for v2.0.1")
    installation = contract.get("installation", {})
    if installation.get("remote_dependency_installation") != "forbidden":
        errors.append("release contract must forbid remote dependency installation")
    prerequisites = installation.get("prerequisites", {})
    if set(prerequisites) != {"opencode", "codebase-memory-mcp"}:
        errors.append("release contract must declare OpenCode and CBM prerequisites")
    installer_surfaces = (ROOT / "install.sh", ROOT / "bin" / "pegasus")
    for path in installer_surfaces:
        content = path.read_text(encoding="utf-8")
        for pattern in remote_installer_patterns():
            if pattern.search(content):
                errors.append(f"remote installer behavior: {path.relative_to(ROOT)}")
                break
    patterns = forbidden_patterns()
    for path in tracked_files():
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            errors.append(f"binary tracked product file: {path.relative_to(ROOT)}")
            continue
        if any(pattern.search(content) for pattern in patterns):
            errors.append(f"forbidden product reference: {path.relative_to(ROOT)}")
    try:
        config = json.loads((ROOT / "source" / "opencode" / "opencode.json").read_text(encoding="utf-8"))
        if set(config["agent"]) != {"pegasus-orchestrator", "sdd-verify"}:
            errors.append("unexpected OpenCode agents")
        if set(config["mcp"]) != {"codebase-memory-mcp"}:
            errors.append("unexpected OpenCode MCP configuration")
    except (KeyError, OSError, json.JSONDecodeError) as error:
        errors.append(f"invalid OpenCode template: {error}")
    allowed_source_roots = (
        "source/adapters/claude-code/", "source/agents/", "source/core/skills/",
        "source/opencode/commands/", "source/opencode/prompts/", "source/opencode/opencode.json",
    )
    for path in tracked_files():
        relative = path.relative_to(ROOT).as_posix()
        if relative.startswith("source/") and not relative.startswith(allowed_source_roots):
            errors.append(f"unlisted distribution asset: {relative}")
    if errors:
        print("FAIL")
        print("\n".join(errors))
        return 1
    print(f"PASS: {len(tracked_files())} tracked product files passed policy and integrity checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
