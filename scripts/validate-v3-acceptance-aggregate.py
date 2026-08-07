#!/usr/bin/env python3
"""Validate the accepted v3.1.1-rc.1 aggregate before final-release publication."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path


PROMOTION_RC_TAG = "v3.1.1-rc.1"


def load_matrix():
    path = Path(__file__).with_name("verify-v3-acceptance-matrix.py")
    spec = importlib.util.spec_from_file_location("pegasus_acceptance_matrix", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load RC acceptance matrix validator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_aggregate(path: Path) -> dict:
    if not path.is_file() or path.is_symlink():
        raise ValueError("accepted v3.1.1-rc.1 aggregate must be a regular non-symlink file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError("accepted v3.1.1-rc.1 aggregate is invalid JSON") from error
    if not isinstance(value, dict):
        raise ValueError("accepted v3.1.1-rc.1 aggregate must be a JSON object")
    return value


def validate(aggregate_path: Path, archive: Path, checksum: Path, manifest: Path) -> dict[str, str]:
    """Return the verified promotion RC identity or reject unsuitable evidence."""
    matrix = load_matrix()
    aggregate = read_aggregate(aggregate_path)
    identity = matrix.expected_identity(archive, checksum, manifest)
    if identity["tag"] != PROMOTION_RC_TAG:
        raise ValueError("promotion input must identify v3.1.1-rc.1")
    if aggregate.get("schema") != matrix.AGGREGATE_SCHEMA:
        raise ValueError("accepted v3.1.1-rc.1 aggregate schema is invalid")
    if aggregate.get("status") != "PASS":
        raise ValueError("accepted v3.1.1-rc.1 aggregate must have status PASS")
    if aggregate.get("purpose") != "promotion-gate-input-only":
        raise ValueError("accepted v3.1.1-rc.1 aggregate purpose is invalid")
    if aggregate.get("rc") != identity:
        raise ValueError("accepted v3.1.1-rc.1 aggregate identity does not match downloaded RC assets")
    if aggregate.get("profiles") != sorted(matrix.PROFILES):
        raise ValueError("accepted v3.1.1-rc.1 aggregate profiles are incomplete")
    profile_evidence = aggregate.get("profile_evidence")
    if (not isinstance(profile_evidence, dict) or set(profile_evidence) != matrix.PROFILES
            or not all(isinstance(value, dict) for value in profile_evidence.values())):
        raise ValueError("accepted v3.1.1-rc.1 aggregate profile evidence is invalid")
    playwright_graph = aggregate.get("playwright_graph")
    if not isinstance(playwright_graph, dict) or set(playwright_graph) != matrix.PLAYWRIGHT_PROFILES:
        raise ValueError("accepted v3.1.1-rc.1 aggregate Playwright evidence is invalid")
    for graph in playwright_graph.values():
        matrix.verify_playwright_graph({"playwright_graph": graph})
    return identity


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aggregate", type=Path, required=True)
    parser.add_argument("--rc-archive", type=Path, required=True)
    parser.add_argument("--rc-checksum", type=Path, required=True)
    parser.add_argument("--release-manifest", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        validate(args.aggregate, args.rc_archive, args.rc_checksum, args.release_manifest)
    except (OSError, ValueError, KeyError) as error:
        parser.error(str(error))
    print("PASS: accepted v3.1.1-rc.1 aggregate validates for final promotion")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
