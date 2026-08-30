#!/usr/bin/env python3
"""Check relative Markdown links in tracked Pegasus documentation.

Most documents resolve a relative link the ordinary way: against the
directory the linking file lives in. Skills are the deliberate exception.
`tests/test_skill_references.py` documents why: every reference inside
`src/pegasus/content/skills/` is written relative to that skills root, so the
same reference means the same thing regardless of which skill wrote it, and a
lazily-loaded agent can resolve it with one shared rule instead of a bespoke
one per skill. Resolving those links against the linking file's own
directory -- the rule everywhere else -- flags real, resolvable references as
broken. This checker resolves a link inside the skills tree against the
skills root, the same convention the shipped content and its test already
follow, and still reports a link that resolves nowhere at all.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"\[[^]]+\]\(([^)]+)\)")
SKILLS_ROOT = ROOT / "src" / "pegasus" / "content" / "skills"


def resolve(path: Path, destination: str) -> Path:
    """Where `destination`, written in `path`, is supposed to point.

    Inside the skills tree that is the skills root; everywhere else it is the
    linking file's own directory.
    """
    if SKILLS_ROOT in path.parents:
        return SKILLS_ROOT / destination
    return path.parent / destination


def main() -> int:
    result = subprocess.run(["git", "ls-files", "-co", "--exclude-standard", "-z"], cwd=ROOT, capture_output=True, check=True)
    errors: list[str] = []
    for item in result.stdout.decode().split("\0"):
        path = ROOT / item
        if not item.endswith(".md") or not path.is_file() or item.startswith("source/"):
            continue
        for target in LINK.findall(path.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            destination = target.split("#", 1)[0]
            if destination and not resolve(path, destination).exists():
                errors.append(f"broken link: {path.relative_to(ROOT)} -> {target}")
    if errors:
        print("FAIL")
        print("\n".join(errors))
        return 1
    print("PASS: relative Markdown links resolve")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
