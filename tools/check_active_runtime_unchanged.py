#!/usr/bin/env python3
"""Compare the recorded active-asset checksums; this script is read-only."""
from __future__ import annotations
import hashlib
import json
import sys
from pathlib import Path
data = json.loads((Path(__file__).resolve().parents[1] / "manifests/active-runtime-baseline.json").read_text())
def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
changed = [path for path, expected in data["assets"].items() if not Path(path).is_file() or digest(path) != expected]
if changed:
    print("FAIL: active assets changed or missing")
    print("\n".join(changed))
    sys.exit(1)
print(f"PASS: {len(data['assets'])} active source assets unchanged since capture.")
