#!/usr/bin/env python3
"""Check relative Markdown links in tracked Pegasus documentation."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"\[[^]]+\]\(([^)]+)\)")


def main() -> int:
    result = subprocess.run(["git", "ls-files", "-co", "--exclude-standard", "-z"], cwd=ROOT, capture_output=True, check=True)
    errors: list[str] = []
    for item in result.stdout.decode().split("\0"):
        path = ROOT / item
        if not item.endswith(".md") or not path.is_file():
            continue
        for target in LINK.findall(path.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            destination = target.split("#", 1)[0]
            if destination and not (path.parent / destination).exists():
                errors.append(f"broken link: {path.relative_to(ROOT)} -> {target}")
    if errors:
        print("FAIL")
        print("\n".join(errors))
        return 1
    print("PASS: relative Markdown links resolve")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
