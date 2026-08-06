#!/usr/bin/env python3
"""Aggregate five offline RC acceptance records into one promotion-gate record."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path


PROFILES = frozenset({"cbm", "engram", "playwright", "context7", "final"})
SCHEMA = "pegasus-harness-rc-acceptance/v3"
AGGREGATE_SCHEMA = "pegasus-harness-rc-acceptance-matrix/v3"
AGGREGATE_NAME = "rc-acceptance-aggregate.json"


def load_contract():
    path = Path(__file__).with_name("acceptance_v3_contract.py")
    spec = importlib.util.spec_from_file_location("pegasus_acceptance_contract", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load RC acceptance contract")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def safe_evidence_dir(path: Path) -> Path:
    if not path.is_absolute() or path == Path("/") or path.is_symlink() or not path.is_dir():
        raise ValueError("evidence directory must be an existing absolute non-symlink directory")
    resolved = path.resolve(strict=True)
    if resolved == Path("/home") or Path("/home") in resolved.parents:
        raise ValueError("evidence directory must be outside /home")
    return resolved


def read_evidence(directory: Path) -> list[dict]:
    records = []
    for path in sorted(directory.glob("*.json")):
        if path.name == AGGREGATE_NAME:
            raise ValueError("aggregate evidence already exists; use a fresh evidence directory")
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"evidence path is unsafe: {path.name}")
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(f"evidence is invalid JSON: {path.name}") from error
        if not isinstance(record, dict):
            raise ValueError(f"evidence must be a JSON object: {path.name}")
        records.append(record)
    return records


def expected_identity(archive: Path, checksum: Path, manifest: Path) -> dict[str, str]:
    contract = load_contract()
    root = contract.validate_rc_inputs("final", archive, checksum, manifest)
    value = json.loads(manifest.read_text(encoding="utf-8"))
    return {
        "tag": value["tag"],
        "archive_name": archive.name,
        "archive_sha256": contract.sha256(archive),
        "checksum_sha256": contract.sha256(checksum),
        "manifest_sha256": contract.sha256(manifest),
        "archive_root": root,
    }


def verify_records(records: list[dict], identity: dict[str, str]) -> dict[str, dict]:
    by_profile: dict[str, dict] = {}
    for record in records:
        profile = record.get("profile")
        if record.get("schema") != SCHEMA or not isinstance(profile, str):
            raise ValueError("evidence schema or profile is invalid")
        if profile in by_profile:
            raise ValueError(f"duplicate evidence profile: {profile}")
        by_profile[profile] = record
    if set(by_profile) != PROFILES:
        raise ValueError("evidence must contain exactly cbm, engram, playwright, context7, and final")
    for profile, record in by_profile.items():
        if record.get("status") != "PASS":
            raise ValueError(f"profile did not pass: {profile}")
        if record.get("rc") != identity:
            raise ValueError(f"RC identity mismatch for profile: {profile}")
    return by_profile


def aggregate(archive: Path, checksum: Path, manifest: Path, evidence_dir: Path) -> Path:
    directory = safe_evidence_dir(evidence_dir)
    output = directory / AGGREGATE_NAME
    if output.exists() or output.is_symlink():
        raise ValueError("aggregate evidence output must not already exist")
    identity = expected_identity(archive, checksum, manifest)
    records = verify_records(read_evidence(directory), identity)
    payload = json.dumps({
        "schema": AGGREGATE_SCHEMA,
        "status": "PASS",
        "rc": identity,
        "profiles": sorted(records),
        "profile_evidence": {profile: record["journal"] for profile, record in sorted(records.items())},
        "purpose": "promotion-gate-input-only",
    }, indent=2) + "\n"
    with output.open("x", encoding="utf-8") as stream:
        stream.write(payload)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rc-archive", type=Path, required=True)
    parser.add_argument("--rc-checksum", type=Path, required=True)
    parser.add_argument("--release-manifest", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        output = aggregate(args.rc_archive, args.rc_checksum, args.release_manifest, args.evidence_dir)
    except (OSError, ValueError, KeyError) as error:
        parser.error(str(error))
    print(f"PASS: aggregate acceptance evidence recorded at {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
