#!/usr/bin/env python3
"""Validate the v3 selected-payload catalog and release safety rules."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "manifests" / "artifact-catalog.json"
CONTRACT = ROOT / "manifests" / "release-contract.json"
NOTIFIER_PACKAGE = "@mohak34/opencode-notifier"
NOTIFIER_VERSION = "0.2.4"
NOTIFIER_INTEGRITY = "sha512-xsfmqr6scB43pi+fZ0R74xD63ELM0MqMZnR/9AWWSescEObYyAcXvaSgiXG/9b2KrXxc8NvcLqTOLPiVJOhKaw=="
PLAYWRIGHT_PACKAGE = "@playwright/mcp"
PLAYWRIGHT_VERSION = "0.0.79"
PLAYWRIGHT_LOCK_PACKAGES = {
    "node_modules/@playwright/mcp": {
        "version": "0.0.79",
        "resolved": "https://registry.npmjs.org/@playwright/mcp/-/mcp-0.0.79.tgz",
        "integrity": "sha512-VpqD4a3vFyGQMY9sh3UJiO6wjcurggkljKfAyCHL0QWGY5m6Ehr3MNsAAHPDHO//n13g0PCjpHatAOiulrqdZQ==",
    },
    "node_modules/playwright": {
        "version": "1.63.0-alpha-2026-08-05",
        "resolved": "https://registry.npmjs.org/playwright/-/playwright-1.63.0-alpha-2026-08-05.tgz",
        "integrity": "sha512-zbGZUK+JYkoDV3cUgfvh2czTBJL34Gmz5gHVI25xiIpvYSR17Q1M7TS8hnwECUe+IkKaeXbKrSyJTyogm2DVWw==",
    },
    "node_modules/playwright-core": {
        "version": "1.63.0-alpha-2026-08-05",
        "resolved": "https://registry.npmjs.org/playwright-core/-/playwright-core-1.63.0-alpha-2026-08-05.tgz",
        "integrity": "sha512-YussvUybTfBtyYbGXWh43f+5kNP03wg98M6mu4DphYET7PSbNVajsdLGjWE1xrsjqOw32i2wFlRP7U5mcOpMZg==",
    },
}
FORBIDDEN_PAYLOAD_SOURCES = {
    "source/core/skills/lazy-load-prompt-audit/references/deployment-transport.md",
    "source/opencode/tui.json",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tracked_source_files() -> set[str]:
    return {path.relative_to(ROOT).as_posix() for path in (ROOT / "source").rglob("*") if path.is_file()}


def main() -> int:
    errors: list[str] = []
    try:
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"FAIL\ninvalid release metadata: {error}")
        return 1
    if catalog.get("schema") != "pegasus-harness-artifact-catalog/v3" or contract.get("version") != "3.1.0":
        errors.append("v3.1 catalog and contract are required")
    for source in FORBIDDEN_PAYLOAD_SOURCES:
        if (ROOT / source).exists():
            errors.append(f"forbidden payload source is present: {source}")
    try:
        provenance = json.loads((ROOT / "manifests" / "cbm-linux-x64-provenance.json").read_text(encoding="utf-8"))
        required = {"repository", "tag", "commit", "tree", "builder_image_digest", "build_command", "build_command_sha256", "output_path", "output_sha256", "signature_verification"}
        build_command = provenance.get("build_command")
        if (set(provenance) < required
                or not isinstance(build_command, str)
                or provenance.get("build_command_sha256") != hashlib.sha256(build_command.encode("utf-8")).hexdigest()
                or provenance.get("output_sha256") != "192eb13dbbd858e0363e4cd24b889bd7c08381d81553a6bb863772d7450938f8"):
            errors.append("invalid curated CBM provenance")
    except (OSError, json.JSONDecodeError):
        errors.append("missing curated CBM provenance")
    cbm_dependency = next((item for item in contract.get("dependencies", []) if item.get("id") == "cbm"), {})
    cbm_source = cbm_dependency.get("source_url", "")
    cbm_integrity = cbm_dependency.get("integrity", {})
    if not cbm_source.startswith("release-bundle:dependencies/"):
        errors.append("invalid curated CBM bundle path")
    else:
        cbm_path = ROOT / cbm_source.removeprefix("release-bundle:")
        if (not cbm_path.is_file() or cbm_path.is_symlink()
                or digest(cbm_path) != cbm_integrity.get("sha256")
                or cbm_integrity.get("sha256") != provenance.get("artifact_sha256")
                or cbm_integrity.get("provenance") != "manifests/cbm-linux-x64-provenance.json"):
            errors.append("curated CBM bundle digest/provenance mismatch")
    catalog_sources = set()
    for entry in catalog.get("artifacts", []):
        source = entry.get("source", "")
        path = ROOT / source
        catalog_sources.add(source)
        if not path.is_file() or path.is_symlink() or digest(path) != entry.get("digest"):
            errors.append(f"catalog digest mismatch: {source}")
        if "judgment-day" in source or "sergio-" in source or source in FORBIDDEN_PAYLOAD_SOURCES:
            errors.append(f"excluded artifact in catalog: {source}")
        if entry.get("executable") and (source not in {"install.sh", "bin/pegasus"} or not os.access(path, os.X_OK)):
            errors.append(f"invalid executable artifact: {source}")
    unlisted = tracked_source_files() - catalog_sources
    if unlisted:
        errors.append("unlisted source artifacts: " + ", ".join(sorted(unlisted)))
    try:
        notifier_package = json.loads((ROOT / "source/opencode/notifier/package.json").read_text(encoding="utf-8"))
        notifier_lock = json.loads((ROOT / "source/opencode/notifier/package-lock.json").read_text(encoding="utf-8"))
        packages = notifier_lock.get("packages", {})
        notifier = packages.get(f"node_modules/{NOTIFIER_PACKAGE}", {})
        if (notifier_package.get("dependencies") != {NOTIFIER_PACKAGE: NOTIFIER_VERSION}
                or notifier_package.get("scripts")
                or packages.get("", {}).get("dependencies") != {NOTIFIER_PACKAGE: NOTIFIER_VERSION}
                or notifier.get("integrity") != NOTIFIER_INTEGRITY):
            errors.append("invalid notifier lock or lifecycle configuration")
    except (OSError, json.JSONDecodeError):
        errors.append("missing notifier lock metadata")
    try:
        playwright_package = json.loads((ROOT / "manifests/playwright-mcp-package.json").read_text(encoding="utf-8"))
        playwright_lock = json.loads((ROOT / "manifests/playwright-mcp-package-lock.json").read_text(encoding="utf-8"))
        packages = playwright_lock.get("packages", {})
        expected = set(PLAYWRIGHT_LOCK_PACKAGES)
        if (playwright_package != {"name": "pegasus-playwright-mcp", "private": True, "dependencies": {PLAYWRIGHT_PACKAGE: PLAYWRIGHT_VERSION}}
                or playwright_lock.get("name") != playwright_package["name"]
                or playwright_lock.get("lockfileVersion") != 3
                or playwright_lock.get("requires") is not True
                or set(packages) - {""} != expected
                or packages.get("", {}).get("dependencies") != playwright_package["dependencies"]
                or any(any(packages[name].get(field) != value for field, value in expected_package.items())
                       for name, expected_package in PLAYWRIGHT_LOCK_PACKAGES.items())):
            errors.append("invalid Playwright package or production lock graph")
    except (OSError, json.JSONDecodeError):
        errors.append("missing Playwright package or lock metadata")
    for dependency in contract.get("dependencies", []):
        text = json.dumps(dependency).lower()
        if dependency.get("version") == "latest" or "npx" in text or re.search(r"(?:ba)?sh\s+-c", text):
            errors.append(f"unsafe dependency contract: {dependency.get('id')}")
        if not (dependency.get("source_url", "").startswith("https://") or dependency.get("source_url", "").startswith("release-bundle:")):
            errors.append(f"unproven dependency source: {dependency.get('id')}")
        if dependency.get("id") == "playwright" and (dependency.get("install_argv") != ["npm", "ci", "--ignore-scripts"]
                or dependency.get("runtime_argv") != ["node", "{dependency}/@playwright/mcp/cli.js"]):
            errors.append("unsafe Playwright install or runtime argv")
        if dependency.get("id") == "engram" and dependency.get("archive_layout") != {
                "members": ["CHANGELOG.md", "LICENSE", "README.md", "engram"],
                "executables": {"engram": "0755"}}:
            errors.append("invalid fixed Engram Linux amd64 archive layout")
        if dependency.get("id") == "engram" and dependency.get("probe_argv") != ["{dependency}/engram", "--version"]:
            errors.append("Engram must use a standalone version probe")
    if errors:
        print("FAIL\n" + "\n".join(errors))
        return 1
    print(f"PASS: {len(catalog['artifacts'])} selected artifacts and fixed dependency metadata are valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
