#!/usr/bin/env python3
"""Report a frozen pre-migration capture; it is not post-migration integrity."""
from __future__ import annotations
import hashlib
import json
import sys
from pathlib import Path
data = json.loads((Path(__file__).resolve().parents[1] / "manifests/active-runtime-baseline.json").read_text())
def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
changed = [path for path, expected in data["assets"].items() if not Path(path).is_file() or digest(path) != expected]
if changed:
    print(f"HISTORICAL: {len(changed)}/{len(data['assets'])} pre-migration source assets differ after migration.")
    print("Historical evidence only; this is expected when Pegasus owns the active runtime.")
    print("Current integrity target: `pegasus --target-user <user> validate` checks the migration ownership manifest.")
    sys.exit(0)
print(f"HISTORICAL: {len(data['assets'])} pre-migration source assets still match the capture.")
print("Current integrity target remains `pegasus --target-user <user> validate`.")
